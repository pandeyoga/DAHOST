"""core.stock_transfer — pindah stok antar lokasi yang DIJAGA (Tahap 2, 6 Nov 2026).

Dipakai dua jalur yang sama-sama memindah stok antar lokasi milik DA:
  * Transfer manual (Stok & Pergerakan → `material-transfer`): hanya penjaganya
    (`assert_movable` + `assert_destination`) — mutasinya tetap `stock_service.move`.
  * Surat Jalan INTERNAL (`routes/wms_delivery_notes.py`): stok keluar dari lokasi asal
    saat SJ diterbitkan, menunggu di lokasi DALAM PERJALANAN, lalu masuk lokasi tujuan
    saat SJ diterima (`send_leg` / `receive_leg` / `return_leg`).

Aturan:
  1. Stok KARANTINA / lokasi terblokir (termasuk lokasi Dalam Perjalanan) tidak bisa
     dipindah lewat transfer — barang reject keluar karantina hanya lewat disposisi QC.
  2. Yang boleh dipindah = qty TERSEDIA (qty − reserved), bukan qty fisik. Dulu
     `stock_service.issue` hanya menjaga qty fisik, sehingga stok karantina (fisik ada,
     reserved penuh) bisa ditransfer keluar dan `available` lokasi karantina jadi minus.
  3. Pindah antar lokasi tidak mengubah nilai persediaan (akun persediaan sama), jadi
     TIDAK ada jurnal; jejaknya ledger `rahaza_stock_ledger` + kartu stok
     `rahaza_material_movements` (stok = GL tetap terjaga).
  4. Setiap langkah idempoten per kunci (`ref.key` di ledger): proses yang terputus
     dilanjutkan tanpa memindah dua kali.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from core import stock_service
from core.stock_schema import read_qty, read_reserved

logger = logging.getLogger(__name__)

TRANSIT_CODE = "ZNA-TRANSIT"
TRANSIT_ROLE = "transit"
MOVEMENTS = "rahaza_material_movements"


class TransferError(Exception):
    """Penolakan yang pesannya ditampilkan apa adanya ke pengguna."""


def _now():
    return datetime.now(timezone.utc)


def _r(v) -> float:
    return round(float(v or 0), 4)


async def transit_location_id(db) -> str:
    """Lokasi DALAM PERJALANAN (dibuat sekali bila belum ada).

    Ditandai `blocked` supaya tidak terbaca sebagai stok jual/pakai (sama seperti karantina)
    dan tidak muncul di daftar lokasi penyimpanan (peran bukan storage)."""
    loc = await db.rahaza_locations.find_one(
        {"$or": [{"code": TRANSIT_CODE}, {"role": TRANSIT_ROLE}]}, {"_id": 0, "id": 1})
    if loc:
        return loc["id"]
    new_id = str(uuid.uuid4())
    await db.rahaza_locations.insert_one({
        "id": new_id, "code": TRANSIT_CODE, "name": "Dalam Perjalanan (Surat Jalan Internal)",
        "description": "Barang Surat Jalan internal yang sudah keluar dari lokasi asal dan belum "
                       "diterima lokasi tujuan. Stok di sini tidak tersedia untuk dipakai/dijual.",
        "type": "warehouse", "role": TRANSIT_ROLE, "blocked": True, "active": True,
        "created_at": _now(),
    })
    return new_id


async def blocked_ids(db) -> set:
    """Lokasi yang stoknya tidak boleh dipindah lewat transfer: karantina + terblokir + transit."""
    from core.catalog_stock import blocked_location_ids
    from core.quarantine import get_quarantine_location_id
    out = set(await blocked_location_ids(db))
    out.add(await get_quarantine_location_id(db))
    loc = await db.rahaza_locations.find_one(
        {"$or": [{"code": TRANSIT_CODE}, {"role": TRANSIT_ROLE}]}, {"_id": 0, "id": 1})
    if loc:
        out.add(loc["id"])
    return out


async def assert_movable(db, material_id: str, from_location_id: str, qty: float, *,
                         blocked: set | None = None) -> dict:
    """Tolak bila stok di lokasi asal tidak boleh / tidak cukup dipindah. Return baris stoknya."""
    blocked = blocked if blocked is not None else await blocked_ids(db)
    if from_location_id in blocked:
        raise TransferError("Lokasi asal adalah lokasi karantina/terblokir — barang di sana tidak bisa "
                            "dipindah lewat transfer. Selesaikan lewat keputusan karantina QC.")
    row = await db[stock_service.STOCK].find_one(
        {"material_id": material_id, "location_id": from_location_id}, {"_id": 0})
    if row and (row.get("quarantine") is True or row.get("blocked") is True):
        raise TransferError("Baris stok di lokasi asal sedang dikarantina/diblokir — tidak bisa dipindah.")
    # tersedia = fisik − reserved (dihitung, bukan dibaca: baris lama bisa tanpa `available_quantity`)
    avail = (read_qty(row) - read_reserved(row)) if row else 0.0
    if _r(qty) > _r(avail) + 0.0001:
        raise TransferError(f"Stok tersedia di lokasi asal tidak cukup: minta {_r(qty):g}, "
                            f"tersedia {max(0.0, _r(avail)):g} (stok fisik {_r(read_qty(row)):g}).")
    return row or {}


async def assert_destination(db, to_location_id: str, *, blocked: set | None = None) -> None:
    blocked = blocked if blocked is not None else await blocked_ids(db)
    if to_location_id in blocked:
        raise TransferError("Lokasi tujuan adalah lokasi karantina/terblokir. Barang masuk karantina "
                            "hanya lewat pemeriksaan QC, bukan transfer.")


async def _done(db, op: str, key: str) -> bool:
    return bool(await db[stock_service.LEDGER].find_one({"op": op, "ref.key": key}, {"_id": 0, "id": 1}))


async def _step_issue(db, material_id, loc, qty, ref, actor):
    if not await _done(db, "issue", ref["key"]):
        await stock_service.issue(material_id, loc, qty, ref=ref, actor=actor, db=db)


async def _step_add(db, material_id, loc, qty, ref, actor, meta=None):
    if not await _done(db, "add", ref["key"]):
        await stock_service.add(material_id, loc, qty, meta=meta, ref=ref, actor=actor, db=db)


async def _step_reserve(db, material_id, loc, qty, ref, actor):
    if not await _done(db, "reserve", ref["key"]):
        await stock_service.reserve(material_id, loc, qty, ref=ref, actor=actor, db=db)


async def _step_release(db, material_id, loc, qty, ref, actor):
    if not await _done(db, "release", ref["key"]):
        await stock_service.release(material_id, loc, qty, ref=ref, actor=actor, db=db)


async def _movement(db, *, key, material_id, qty, from_loc, to_loc, ref_no, ref_id, notes, actor):
    if await db[MOVEMENTS].find_one({"transfer_key": key}, {"_id": 0, "id": 1}):
        return
    ts = _now()
    await db[MOVEMENTS].insert_one({
        "id": str(uuid.uuid4()), "type": "transfer", "material_id": material_id, "qty": _r(qty),
        "from_location_id": from_loc, "to_location_id": to_loc, "ref_type": "delivery_note",
        "ref_id": ref_id, "ref_no": ref_no, "notes": notes, "transfer_key": key,
        "created_at": ts, "timestamp": ts, "created_by": (actor or {}).get("id") or "",
        "created_by_name": (actor or {}).get("name") or "",
    })


def leg_key(sj_id: str, seq, line_no, leg: str) -> str:
    """Kunci idempoten satu langkah. `seq` = percobaan terbit ke-n (terbit ulang sesudah gagal
    & dikembalikan memakai kunci baru, sehingga tidak dianggap "sudah jalan")."""
    return f"sj:{sj_id}:{int(seq or 1)}:{line_no}:{leg}"


async def send_leg(db, *, sj: dict, line: dict, transit_id: str, actor: dict) -> None:
    """SJ internal diterbitkan: lokasi asal → Dalam Perjalanan (lalu diblokir/reserve)."""
    key = leg_key(sj["id"], sj.get("stock_seq"), line["line_no"], "out")
    ref = {"source": "delivery_note", "type": "sj_internal_out", "key": key, "sj_id": sj["id"],
           "sj_number": sj.get("sj_number", ""), "line_no": line["line_no"]}
    mid, qty = line["material_id"], _r(line["qty_base"])
    # 2026-11-09 (audit gudang G8): identitas baris asal (kategori/kepemilikan) ikut ke baris tujuan.
    ident = await stock_service.identity_meta(mid, sj["from_location_id"], db=db)
    await _step_issue(db, mid, sj["from_location_id"], qty, {**ref, "move_to": transit_id}, actor)
    await _step_add(db, mid, transit_id, qty, {**ref, "move_from": sj["from_location_id"]}, actor,
                    meta={**ident, "material_code": line.get("material_code"), "unit": line.get("unit_base")})
    await _step_reserve(db, mid, transit_id, qty, ref, actor)
    await _movement(db, key=key, material_id=mid, qty=qty, from_loc=sj["from_location_id"], to_loc=transit_id,
                    ref_no=sj.get("sj_number", ""), ref_id=sj["id"],
                    notes=f"SJ internal {sj.get('sj_number', '')} — keluar, dalam perjalanan", actor=actor)


async def _out_of_transit(db, *, sj: dict, line: dict, transit_id: str, to_loc: str, leg: str,
                          actor: dict, notes: str) -> None:
    key = leg_key(sj["id"], sj.get("stock_seq"), line["line_no"], leg)
    ref = {"source": "delivery_note", "type": f"sj_internal_{leg}", "key": key, "sj_id": sj["id"],
           "sj_number": sj.get("sj_number", ""), "line_no": line["line_no"]}
    mid, qty = line["material_id"], _r(line["qty_base"])
    ident = await stock_service.identity_meta(mid, transit_id, db=db)   # 2026-11-09 (G8)
    await _step_release(db, mid, transit_id, qty, ref, actor)
    await _step_issue(db, mid, transit_id, qty, {**ref, "move_to": to_loc}, actor)
    await _step_add(db, mid, to_loc, qty, {**ref, "move_from": transit_id}, actor,
                    meta={**ident, "material_code": line.get("material_code"), "unit": line.get("unit_base")})
    await _movement(db, key=key, material_id=mid, qty=qty, from_loc=transit_id, to_loc=to_loc,
                    ref_no=sj.get("sj_number", ""), ref_id=sj["id"], notes=notes, actor=actor)


async def receive_leg(db, *, sj: dict, line: dict, transit_id: str, actor: dict) -> None:
    """SJ internal diterima: Dalam Perjalanan → lokasi tujuan."""
    await _out_of_transit(db, sj=sj, line=line, transit_id=transit_id, to_loc=sj["to_location_id"],
                          leg="in", actor=actor,
                          notes=f"SJ internal {sj.get('sj_number', '')} — diterima di tujuan")


async def return_leg(db, *, sj: dict, line: dict, transit_id: str, actor: dict) -> None:
    """SJ internal dibatalkan sesudah terbit: Dalam Perjalanan → kembali ke lokasi asal."""
    await _out_of_transit(db, sj=sj, line=line, transit_id=transit_id, to_loc=sj["from_location_id"],
                          leg="back", actor=actor,
                          notes=f"SJ internal {sj.get('sj_number', '')} — dibatalkan, kembali ke asal")

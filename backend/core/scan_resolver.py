"""core.scan_resolver — SATU pintu resolusi kode scan (barcode/QR) → entitas.

2026-11-02 (Paket 3a, fondasi scan untuk K15 scan keluar & K9 opname per rak).

Kenapa modul ini ada (diukur di DB seed `dahost_ba`, bukan dugaan):
  * Universal Scan mencari bahan di field `material_code`/`barcode` (0 dari 1.756
    dokumen `rahaza_materials` punya field itu) dan roll di koleksi
    `wms_fabric_rolls.roll_number` (roll hidup di `wh_fabric_rolls.roll_no`).
    Hasilnya: SKU FG, kode bahan, roll, dan bin TIDAK PERNAH dikenali — 13/13 kode
    uji `found=false`, termasuk QR JSON label FG.
  * Ada TUJUH pencari kode lain yang masing-masing punya aturan sendiri
    (opname3 item/bin, wms_structure by-barcode/search, putaway, receiving
    scan-in/out). Semuanya mencocokkan persis & peka huruf besar/kecil, jadi
    `da-2101-mhg-allsize` atau kode ber-prefix scanner (`]C0…`) gagal di satu
    layar tapi lolos di layar lain.

Aturan yang dipegang:
  1. `normalize_code()` adalah SATU-SATUNYA normalisasi: buang spasi tepi,
     karakter kontrol (CR/LF/TAB/GS/STX/ETX dari scanner), prefix identitas
     simbologi AIM (`]C0`, `]Q1`, …), dan bintang pembungkus Code39 (`*KODE*`).
     Frontend mencerminkannya di `scanner/scanCode.js` (aturan yang sama).
  2. Pencocokan TIDAK peka huruf besar/kecil. Jalur cepat = kesamaan persis pada
     kode HURUF BESAR (semua penulis master menyimpan kode huruf besar → pakai
     indeks); cadangan = regex `^…$` ber-`re.escape` + opsi `i`.
  3. Isi kode barang jadi = SKU varian (`rahaza_materials.code`, type `fg`). Label
     FG memuat Code128 = SKU dan QR JSON `{"type":"fg","sku":…}`; keduanya
     mengarah ke master FG yang sama.
  4. Hasil SELALU berbentuk `{tipe, id, nama, kode, sku, satuan, aktif, via, …}`
     dengan `tipe ∈ {fg, material, roll, bin, dokumen, aset, bundle}`. Dokumen
     lengkap (untuk pemanggil di backend) ada di `_doc` dan TIDAK dikirim ke klien
     (`public()` membuangnya).
  5. Resolver ini hanya MEMBACA. Tidak ada efek stok/jurnal.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

TIPE = ("fg", "material", "bin", "roll", "bundle", "dokumen", "aset")

# Prefix identitas simbologi AIM ISO/IEC 15424: "]" + huruf simbologi + modifier.
_AIM_PREFIX = re.compile(r"^\][A-Za-z][0-9A-Za-z]")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def normalize_code(raw) -> str:
    """Kode mentah dari scanner/ketikan → kode bersih (huruf asli dipertahankan)."""
    s = str(raw if raw is not None else "").replace("﻿", "")
    s = s.strip()
    s = _AIM_PREFIX.sub("", s, count=1)
    s = _CTRL.sub("", s).strip()
    # Code39 dengan "transmit start/stop" mengirim *KODE*
    if len(s) > 2 and s.startswith("*") and s.endswith("*"):
        s = s[1:-1].strip()
    return s


def code_key(raw) -> str:
    """Kunci pembanding (dinormalisasi + huruf besar)."""
    return normalize_code(raw).upper()


def parse_qr_payload(code: str) -> Optional[dict]:
    """QR berisi JSON (label FG / aset). Selain JSON objek → None."""
    if not code.startswith("{"):
        return None
    try:
        data = json.loads(code)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _ci(code: str) -> dict:
    return {"$regex": f"^{re.escape(code)}$", "$options": "i"}


async def _find_by_code(coll, field: str, code: str, extra: Optional[dict] = None,
                        proj: Optional[dict] = None) -> list:
    """Kesamaan persis (kode huruf besar, berindeks) dulu; regex tanpa-huruf cadangan."""
    extra = dict(extra or {})
    proj = proj or {"_id": 0}
    rows = await coll.find({**extra, field: code.upper()}, proj).to_list(5)
    if not rows and code != code.upper():
        rows = await coll.find({**extra, field: code}, proj).to_list(5)
    if not rows:
        rows = await coll.find({**extra, field: _ci(code)}, proj).to_list(5)
    return rows


def _prefer_active(rows: list) -> Optional[dict]:
    if not rows:
        return None
    for r in rows:
        if r.get("active", True) is not False:
            return r
    return rows[0]


def _result(tipe: str, doc: dict, *, kode: str, nama: str, via: str, satuan: str = "",
            sku: str = "", subtipe: str = "", aktif: bool = True, meta: Optional[dict] = None) -> dict:
    return {
        "tipe": tipe, "subtipe": subtipe or tipe, "id": doc.get("id"),
        "kode": kode or "", "sku": sku or "", "nama": nama or "", "satuan": satuan or "",
        "aktif": bool(aktif), "via": via, "meta": meta or {}, "_doc": doc,
    }


def public(res: Optional[dict]) -> Optional[dict]:
    """Hasil untuk klien HTTP — tanpa dokumen mentah."""
    if not res:
        return res
    return {k: v for k, v in res.items() if k != "_doc"}


# ── per tipe ─────────────────────────────────────────────────────────────────

def _material_result(m: dict, via: str) -> dict:
    is_fg = m.get("type") == "fg"
    code = m.get("code") or m.get("sku") or ""
    unit = str(m.get("unit") or m.get("uom") or "pcs")
    if is_fg:
        meta = {"Model": m.get("model_code") or m.get("model_name") or "-",
                "Warna": m.get("color_name") or m.get("color") or "-",
                "Ukuran": m.get("size_code") or m.get("size") or "-"}
        return _result("fg", m, kode=code, sku=code, nama=m.get("name") or "", satuan=unit,
                       via=via, aktif=m.get("active", True) is not False, meta=meta)
    meta = {"Jenis": m.get("type") or "-", "Kategori": m.get("category_name") or m.get("category") or "-"}
    return _result("material", m, kode=code, nama=m.get("name") or "", satuan=unit, via=via,
                   subtipe=str(m.get("type") or "material"),
                   aktif=m.get("active", True) is not False, meta=meta)


async def resolve_fg(db, code: str) -> Optional[dict]:
    """SKU varian → master FG. Urutan: kode/SKU master → barcode varian → SKU katalog."""
    rows = await _find_by_code(db.rahaza_materials, "code", code, {"type": "fg"})
    if not rows:
        rows = await _find_by_code(db.rahaza_materials, "sku", code, {"type": "fg"})
    m = _prefer_active(rows)
    if m:
        return _material_result(m, "sku")
    # 13 Nov 2026: SKU lama produk yang kodenya diganti (`core.ganti_kode_produk`) → label lama tetap terbaca.
    m = _prefer_active(await _find_by_code(db.rahaza_materials, "code_aliases", code, {"type": "fg"}))
    if m:
        return _material_result(m, "kode_lama")
    # Barcode khusus yang diisi di varian (mis. barcode pabrik/marketplace).
    var = _prefer_active(await _find_by_code(db.rahaza_model_variants, "barcode", code,
                                             proj={"_id": 0, "id": 1, "sku": 1, "active": 1}))
    if var:
        m = _prefer_active(await db.rahaza_materials.find(
            {"type": "fg", "$or": [{"variant_id": var.get("id")}, {"code": var.get("sku")}]},
            {"_id": 0}).to_list(5))
        if m:
            return _material_result(m, "barcode_varian")
    # SKU item katalog marketing yang tertaut ke FG (bila SKU toko ≠ SKU master).
    cat = await _find_by_code(db.marketing_catalog_items, "sku", code,
                              {"fg_material_id": {"$nin": [None, ""]}},
                              proj={"_id": 0, "fg_material_id": 1})
    if cat:
        m = await db.rahaza_materials.find_one({"id": cat[0]["fg_material_id"]}, {"_id": 0})
        if m and m.get("type") == "fg":
            return _material_result(m, "sku_katalog")
    return None


async def resolve_material(db, code: str) -> Optional[dict]:
    """Kode bahan/kain/aksesoris (`rahaza_materials.code`, bukan FG).

    2026-11-02: kode lama yang dirapikan (`scripts/tidy_material_codes.py`, mis. `KN-CND-DST 2` →
    `KN-CND-DST-2`) disimpan di `code_aliases` → label yang sudah tertempel tetap terbaca."""
    via = "kode"
    rows = await _find_by_code(db.rahaza_materials, "code", code, {"type": {"$ne": "fg"}})
    if not rows:
        rows = await _find_by_code(db.rahaza_materials, "barcode", code, {"type": {"$ne": "fg"}})
    if not rows:
        rows = await _find_by_code(db.rahaza_materials, "code_aliases", code, {"type": {"$ne": "fg"}})
        via = "kode_lama"
    m = _prefer_active(rows)
    return _material_result(m, via) if m else None


async def resolve_item(db, code: str) -> Optional[dict]:
    """Barang (FG atau bahan) — untuk layar hitung/keluar barang."""
    return await resolve(db, code, expect=("fg", "material"))


async def resolve_bin(db, code: str, *, include_locations: bool = True) -> Optional[dict]:
    """Posisi rak (`wh_positions.barcode`) lalu lokasi gudang (`rahaza_locations.code`).

    2026-11-02: label LAMA (kode bin panjang sebelum dipendekkan ≤ 18 karakter) tetap dikenali lewat
    `wh_positions.barcode_aliases` (via `barcode_posisi_lama`); kode yang dikembalikan = kode baru."""
    via = "barcode_posisi"
    pos = _prefer_active(await _find_by_code(db.wh_positions, "barcode", code))
    if not pos:
        pos = _prefer_active(await _find_by_code(db.wh_positions, "barcode_aliases", code))
        via = "barcode_posisi_lama"
    if pos:
        path = " / ".join(x for x in (pos.get("building_code"), pos.get("zone_code"),
                                      pos.get("rack_code"), pos.get("label")) if x)
        return _result("bin", pos, kode=pos.get("barcode") or "", nama=path or pos.get("label") or "",
                       via=via, subtipe="posisi",
                       meta={"Rak": pos.get("rack_code") or "-", "Isi": pos.get("material_code") or "-",
                             "Qty": str(pos.get("qty") or 0)})
    if not include_locations:
        return None
    loc = _prefer_active(await _find_by_code(db.rahaza_locations, "code", code))
    if loc:
        return _result("bin", loc, kode=loc.get("code") or "", nama=loc.get("name") or "",
                       via="kode_lokasi", subtipe="lokasi", aktif=loc.get("active", True) is not False,
                       meta={"Jenis": loc.get("type") or "-",
                             "Peran": loc.get("storage_role") or loc.get("role") or "-"})
    return None


async def position_by_barcode(db, code) -> Optional[dict]:
    """Dokumen `wh_positions` untuk barcode posisi hasil scan (atau None).

    Dipakai semua jalur yang menerima `position_barcode` (put-away, scan-in/out,
    opname, pencarian posisi) supaya aturannya satu."""
    code = normalize_code(code)
    if not code:
        return None
    res = await resolve_bin(db, code, include_locations=False)
    return res["_doc"] if res else None


async def resolve_roll(db, code: str) -> Optional[dict]:
    roll = _prefer_active(await _find_by_code(db.wh_fabric_rolls, "roll_no", code))
    if not roll:
        return None
    uom = roll.get("uom") or "meter"
    is_kg = str(uom).lower() in ("kg", "kilogram")
    rem = roll.get("remaining_kg") if is_kg else roll.get("remaining_m")
    return _result("roll", roll, kode=roll.get("roll_no") or "", nama=roll.get("material_name") or "",
                   satuan=uom, via="nomor_roll",
                   meta={"Bahan": roll.get("material_code") or "-", "Sisa": f"{rem or 0} {uom}",
                         "Status": roll.get("status") or "-", "Lot": roll.get("color_lot") or "-"})


async def resolve_bundle(db, code: str) -> Optional[dict]:
    b = _prefer_active(await _find_by_code(db.rahaza_bundles, "bundle_number", code))
    if not b:
        return None
    return _result("bundle", b, kode=b.get("bundle_number") or "",
                   nama=b.get("style_name") or b.get("bundle_number") or "", satuan="pcs",
                   via="nomor_bundle", meta={"No. WO": b.get("wo_number") or "-",
                                             "Qty": str(b.get("qty") or "-"),
                                             "Proses": b.get("current_process") or "-"})


async def resolve_document(db, code: str) -> Optional[dict]:
    """Dokumen bernomor: WO (production_jobs), PO pembelian, DO/surat jalan CMT."""
    from core.wo_reader import find_wo_by_number  # SSOT WO
    wo = await find_wo_by_number(db, code)
    if wo:
        return _result("dokumen", wo, kode=wo.get("wo_number") or code, subtipe="work_order",
                       nama=wo.get("style_name") or wo.get("wo_number") or "", via="nomor_wo",
                       meta={"Buyer": wo.get("buyer") or "-", "Qty": str(wo.get("qty") or "-"),
                             "Deadline": str(wo.get("due_date") or "-")[:10]})
    po = _prefer_active(await _find_by_code(db.rahaza_purchase_orders, "po_number", code))
    if po:
        return _result("dokumen", po, kode=po.get("po_number") or "", subtipe="purchase_order",
                       nama=f"PO ke {po.get('vendor_name') or '-'}", via="nomor_po",
                       meta={"Vendor": po.get("vendor_name") or "-",
                             "Tgl PO": str(po.get("po_date") or "-")[:10],
                             "Dari PR": po.get("from_pr_number") or "-"})
    # 2026-11-06 (pola P2): surat jalan dicari di koleksi yang benar-benar ditulis — kirim ke CMT
    # (`vendor_shipments`) & kirim ke buyer (`buyer_shipments`). Dulu `dewi_cmt_delivery_orders` /
    # `dewi_delivery_orders` (arsip tanpa penulis) → scan nomor surat jalan selalu "tidak dikenal".
    for coll, field, label, party in ((db.vendor_shipments, "shipment_number", "Vendor", "vendor_name"),
                                      (db.vendor_shipments, "delivery_note_number", "Vendor", "vendor_name"),
                                      (db.buyer_shipments, "shipment_number", "Customer", "customer_name")):
        sj = _prefer_active(await _find_by_code(coll, field, code))
        if sj:
            return _result("dokumen", sj, kode=sj.get(field) or "", subtipe="delivery_order",
                           nama=f"Surat jalan ke {sj.get(party) or '-'}", via="nomor_do",
                           meta={label: sj.get(party) or "-",
                                 "Tgl Kirim": str(sj.get("shipment_date") or sj.get("created_at") or "-")[:10],
                                 "No. PO": sj.get("po_number") or "-"})
    return None


async def resolve_asset(db, code: str, *, asset_id: str = "") -> Optional[dict]:
    """Aset. 2026-11-02 (registri aset tunggal): kode label = kode registri induk Keuangan
    (`rahaza_fixed_assets.code`, via `kode_aset_tetap`) → hasil menunjuk tampilan operasional tertaut
    (`dewi_assets`) bila ada, selain itu aset Keuangan itu sendiri. Nomor Portal Aset lama
    (`dewi_assets.asset_number`, label/QR lama) tetap dikenali (via `nomor_aset`)."""
    a, fa, via = None, None, "nomor_aset"
    if asset_id:
        a = await db.dewi_assets.find_one({"id": asset_id}, {"_id": 0})
    if not a and code:
        fa = _prefer_active(await _find_by_code(db.rahaza_fixed_assets, "code", code))
        if fa:
            via = "kode_aset_tetap"
            a = await db.dewi_assets.find_one({"fixed_asset_id": fa.get("id")}, {"_id": 0})
        else:
            a = _prefer_active(await _find_by_code(db.dewi_assets, "asset_number", code))
    if a and not fa and a.get("fixed_asset_id"):
        fa = await db.rahaza_fixed_assets.find_one({"id": a["fixed_asset_id"]}, {"_id": 0})
    if not a and not fa:
        return None
    doc = a or fa
    kode = (fa or {}).get("code") or (a or {}).get("asset_number") or ""
    return _result("aset", doc, kode=kode, nama=doc.get("name") or "", via=via,
                   subtipe="aset" if a else "aset_tetap",
                   aktif=(fa or {}).get("status") != "disposed",
                   meta={"Kategori": (a or {}).get("category_name") or (fa or {}).get("category") or "-",
                         "Lokasi": (a or {}).get("location") or "-",
                         "Dipegang": (a or {}).get("assigned_to_name") or "-",
                         "No. Portal Aset": (a or {}).get("asset_number") or "-"})


_RESOLVERS = (
    ("fg", resolve_fg),
    ("material", resolve_material),
    ("bin", resolve_bin),
    ("roll", resolve_roll),
    ("bundle", resolve_bundle),
    ("dokumen", resolve_document),
    ("aset", resolve_asset),
)


async def _resolve_qr(db, payload: dict, allowed: set) -> Optional[dict]:
    """QR JSON: label FG `{"type":"fg","sku":…}`, aset `{"type":"asset","asset_id":…}`,
    atau objek apa pun yang membawa `sku`/`code`/`barcode`."""
    t = str(payload.get("type") or "").lower()
    if t == "asset" and "aset" in allowed:
        return await resolve_asset(db, str(payload.get("asset_number") or ""),
                                   asset_id=str(payload.get("asset_id") or payload.get("id") or ""))
    inner = payload.get("sku") or payload.get("code") or payload.get("barcode") \
        or payload.get("roll_no") or payload.get("asset_number")
    if not inner:
        return None
    inner = normalize_code(inner)
    if t == "fg" and "fg" in allowed:
        res = await resolve_fg(db, inner)
        if res:
            res["via"] = "qr_" + res["via"]
        return res
    return await _resolve_plain(db, inner, allowed, via_prefix="qr_")


async def _resolve_plain(db, code: str, allowed: set, via_prefix: str = "") -> Optional[dict]:
    for tipe, fn in _RESOLVERS:
        if tipe not in allowed:
            continue
        try:
            res = await fn(db, code)
        except Exception as e:  # noqa: BLE001 — satu tipe gagal ≠ seluruh scan gagal (perilaku lama)
            logger.warning("scan_resolver %s gagal untuk %r: %s", tipe, code, e)
            continue
        if res:
            if via_prefix:
                res["via"] = via_prefix + res["via"]
            return res
    return None


async def resolve(db, raw, *, expect: Optional[Iterable[str]] = None) -> Optional[dict]:
    """Kode mentah → hasil baku, atau None bila tidak dikenal.

    `expect` membatasi tipe yang dicari (mis. layar opname: `("fg","material")`;
    pemilih bin: `("bin",)`). Kosong = semua tipe, urutan `_RESOLVERS`.
    """
    code = normalize_code(raw)
    if not code:
        return None
    allowed = set(expect or TIPE)
    unknown = allowed - set(TIPE)
    if unknown:
        raise ValueError(f"tipe scan tidak dikenal: {sorted(unknown)}")
    payload = parse_qr_payload(code)
    if payload is not None:
        return await _resolve_qr(db, payload, allowed)
    return await _resolve_plain(db, code, allowed)


def parse_expect(value) -> Optional[tuple]:
    """'fg,material' / ['fg'] → tuple; kosong → None. Tipe asing → ValueError."""
    if not value:
        return None
    items = value if isinstance(value, (list, tuple)) else str(value).split(",")
    out = tuple(x.strip().lower() for x in items if str(x).strip())
    bad = [x for x in out if x not in TIPE]
    if bad:
        raise ValueError(f"tipe scan tidak dikenal: {bad} (pilihan: {', '.join(TIPE)})")
    return out or None

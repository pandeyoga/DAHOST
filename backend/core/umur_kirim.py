"""Umur sejak kirim ke CMT — kolom "Umur" di Keuangan › Hutang dan Piutang (11 Nov 2026, owner).

Owner memantau barang yang masih di penjahit dengan Excel per PO: HIJAU 0–7 hari, KUNING 8–14 hari, MERAH lebih
dari 14 hari sejak TGL KIRIM ke CMT — satu baris memuat hutang ke CMT dan piutang ke klien (seller). Daftar Hutang
(jadwal hutang CMT / perkiraan PO DA) dan Piutang (piutang maklon terjadwal) memakai aturan yang SAMA dari sini.

Tanggal kirim = surat jalan NORMAL paling awal (bukan tambahan/pengganti) untuk PO tersebut, per vendor CMT bila
ada; PO berjalan hasil impor cutoff membawa TGL KIRIM Excel sebagai `shipment_date` (core.po_berjalan_import).
Hanya membaca — tidak ada yang disimpan.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, Optional

HIJAU_MAKS = 7     # 0–7 hari
KUNING_MAKS = 14   # 8–14 hari; selebihnya merah

_BATAL = ("cancelled", "canceled", "void", "voided", "dibatalkan")


def _tgl(v) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v or "")[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def hari_sejak(tgl, today: date) -> Optional[int]:
    """Jumlah hari dari `tgl` sampai `today` (boleh minus bila tanggal kirim di masa depan); None bila kosong."""
    d = _tgl(tgl)
    return (today - d).days if d else None


def kelompok_umur(hari: Optional[int]) -> Optional[str]:
    """'hijau' (≤ 7 hari) · 'kuning' (8–14) · 'merah' (> 14); None bila tanggal kirim tidak diketahui."""
    if hari is None:
        return None
    if hari <= HIJAU_MAKS:
        return "hijau"
    if hari <= KUNING_MAKS:
        return "kuning"
    return "merah"


def umur_fields(tgl, today: date) -> dict:
    """Field umur untuk satu baris daftar: `kirim_pertama`, `umur_kirim_hari`, `umur_kirim`."""
    d = _tgl(tgl)
    hari = hari_sejak(d, today) if d else None
    return {"kirim_pertama": d.isoformat() if d else None, "umur_kirim_hari": hari, "umur_kirim": kelompok_umur(hari)}


async def tanggal_kirim_cmt(db, po_ids: Iterable[str]) -> dict:
    """{po_id: {'': tanggal paling awal, <vendor_id kanonik>: tanggal paling awal vendor itu}} (date)."""
    ids = sorted({p for p in po_ids if p})
    if not ids:
        return {}
    idset = set(ids)
    # baris surat jalan lama bisa tanpa `po_id` → dicocokkan juga lewat baris PO (`po_item_id`)
    po_of_item = {i["id"]: i["po_id"] async for i in db.po_items.find(
        {"po_id": {"$in": ids}}, {"_id": 0, "id": 1, "po_id": 1})}
    items = []
    async for x in db.vendor_shipment_items.find(
            {"$or": [{"po_id": {"$in": ids}}, {"po_item_id": {"$in": list(po_of_item)}}]},
            {"_id": 0, "po_id": 1, "po_item_id": 1, "shipment_id": 1}):
        po_id = x.get("po_id") if x.get("po_id") in idset else po_of_item.get(x.get("po_item_id"))
        if po_id:
            items.append({**x, "po_id": po_id})
    ship_ids = sorted({x.get("shipment_id") for x in items if x.get("shipment_id")})
    ships = {}
    if ship_ids:
        async for s in db.vendor_shipments.find(
                {"id": {"$in": ship_ids}},
                {"_id": 0, "id": 1, "vendor_id": 1, "shipment_date": 1, "created_at": 1, "shipment_type": 1,
                 "status": 1}):
            if (s.get("shipment_type") or "NORMAL").upper() != "NORMAL":
                continue
            if str(s.get("status") or "").lower() in _BATAL:
                continue
            ships[s["id"]] = s
    from core import cmt_vendor_master
    canon: dict = {}
    out: dict = {}
    for x in items:
        s = ships.get(x.get("shipment_id"))
        if not s:
            continue
        d = _tgl(s.get("shipment_date") or s.get("created_at"))
        if not d:
            continue
        raw = s.get("vendor_id") or ""
        if raw and raw not in canon:
            canon[raw] = (await cmt_vendor_master.canonical_id(db, raw)) or raw
        per_po = out.setdefault(x["po_id"], {})
        for key in {"", canon.get(raw, "")}:
            if per_po.get(key) is None or d < per_po[key]:
                per_po[key] = d
    return out


def tanggal_untuk(kirim: dict, po_id: Optional[str], vendor_id: Optional[str] = None) -> Optional[date]:
    """Tanggal kirim vendor itu untuk PO; bila vendor tidak cocok → tanggal kirim paling awal PO."""
    per_po = kirim.get(po_id or "") or {}
    return (per_po.get(vendor_id) if vendor_id else None) or per_po.get("")

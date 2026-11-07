"""Saringan data per portal untuk layar proses Produksi & Maklon (Tahap 9, 7 Nov 2026).

Keputusan owner 2 (Tahap 9): menu DAN tampilan Portal Produksi dan Portal Maklon identik — satu
komponen yang sama, isinya disaring sesuai portal. Layar proses (Terima & QC, Perbaikan, Kirim hasil,
Bahan) dulu memuat data KEDUA portal sekaligus (penerimaan, antrean ditolak, selisih kirim, permak,
kekurangan kirim, retur material).

SATU aturan, sama dengan daftar PO (`routes/production_pos.py`) dan `services.mgmt_analytics.domain_q`:
  internal → PO ``business_type == "internal"``
  maklon   → PO ``business_type != "internal"``
Dengan begitu PO yang tampil di daftar PO portal X adalah satu-satunya PO yang datanya tampil di layar
proses portal X.

Dokumen tanpa PO (warisan) memakai jenis pada dokumennya sendiri; tanpa jenis = internal
(desain dua CV §9, `core.entities.po_business_type`).

Tanpa ``business_type`` (mis. dibuka dari Portal Gudang) tidak ada saringan — perilaku lama.
"""
from __future__ import annotations

from services.mgmt_analytics import domain_q

PORTAL_TYPES = ("internal", "maklon")
_EMPTY = [None, ""]


def portal_business_type(value) -> str | None:
    """'internal' | 'maklon' | None (tanpa saringan)."""
    v = str(value or "").strip().lower()
    return v if v in PORTAL_TYPES else None


async def portal_po_ids(db, business_type) -> set | None:
    """Id PO milik portal ini, atau None bila tidak disaring."""
    bt = portal_business_type(business_type)
    if not bt:
        return None
    return {p["id"] async for p in db.production_pos.find(domain_q(bt), {"_id": 0, "id": 1}) if p.get("id")}


def _own_type_clause(business_type: str, type_key: str = "business_type") -> dict:
    """Jenis pada dokumen tanpa PO: tanpa jenis = internal."""
    internal_vals = ["internal", None, ""]
    if business_type == "internal":
        return {type_key: {"$in": internal_vals}}
    return {type_key: {"$nin": internal_vals}}


def portal_query(po_ids: set | None, business_type, *, po_key: str = "po_id",
                 type_key: str = "business_type") -> dict:
    """Filter Mongo: dokumen ber-PO portal ini + dokumen tanpa PO yang jenisnya cocok."""
    bt = portal_business_type(business_type)
    if po_ids is None or not bt:
        return {}
    return {"$or": [{po_key: {"$in": sorted(po_ids)}},
                    {po_key: {"$in": list(_EMPTY)}, **_own_type_clause(bt, type_key)}]}


def merge_query(query: dict, extra: dict) -> dict:
    """Gabungkan filter tambahan ke kueri yang mungkin sudah punya `$or` (mis. pencarian)."""
    if not extra:
        return query
    if "$or" in query and "$or" in extra:
        query.setdefault("$and", []).append({"$or": extra["$or"]})
        return query
    query.update(extra)
    return query


def in_portal(row: dict, po_ids: set | None, business_type, *, po_key: str = "po_id",
              type_key: str = "business_type") -> bool:
    """Versi baris (untuk hasil fungsi inti yang sudah berupa daftar)."""
    bt = portal_business_type(business_type)
    if po_ids is None or not bt:
        return True
    pid = row.get(po_key)
    if pid:
        return pid in po_ids
    own = str(row.get(type_key) or "internal").strip().lower()
    own = "internal" if own == "internal" else "maklon"
    return own == bt


def keep_in_portal(rows: list, po_ids: set | None, business_type, **kw) -> list:
    return [r for r in rows or [] if in_portal(r, po_ids, business_type, **kw)]

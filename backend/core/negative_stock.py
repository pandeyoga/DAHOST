"""core/negative_stock.py — mode SEMENTARA "stok boleh minus".

Keputusan owner 2026-09-23: klien belum stock opname tetapi produksi harus jalan
(Kirim Material CMT, Pengeluaran Material, Cutting). Selama setelan sistem
`inventory_allow_negative` ON, pengeluaran material TIDAK ditolak karena stok
kurang/belum ada baris — stok dipotong sampai minus dan baris stok dibuat di
gudang bawaan. Setelah opname, owner mematikan setelan → aturan ketat kembali.
"""
from __future__ import annotations

CONFIG_KEY = "inventory_allow_negative"


async def allowed(db) -> bool:
    from routes.dewi_system_config import get_config_value
    v = await get_config_value(db, CONFIG_KEY, True)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y", "on")
    return bool(v)


def _wanted_role(material: dict) -> str:
    code = str((material or {}).get("code") or "").upper()
    return "aksesoris" if code.startswith("A-") else "bahan"


async def fallback_location(db, material: dict) -> dict | None:
    """Gudang bawaan untuk material yang belum punya baris stok sama sekali."""
    role = _wanted_role(material)
    q_active = {"active": {"$ne": False}}
    loc = await db.rahaza_locations.find_one(
        {**q_active, "$or": [{"storage_role": role}, {"role": role}]}, {"_id": 0})
    if not loc:
        loc = await db.rahaza_locations.find_one(
            {**q_active, "code": {"$regex": "^GD-"}}, {"_id": 0}, sort=[("code", 1)])
    if not loc:
        loc = await db.rahaza_locations.find_one(q_active, {"_id": 0}, sort=[("code", 1)])
    return loc


def stock_meta(material: dict, location: dict | None) -> dict:
    m = material or {}
    return {
        "material_code": m.get("code"), "material_name": m.get("name"),
        "unit": m.get("unit"), "material_type": m.get("type"),
        "location_code": (location or {}).get("code"),
    }

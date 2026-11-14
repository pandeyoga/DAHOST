"""
WMS — Warehouse Structure Management
Phase 1: Building → Zone → Rack → Shelf/Position + Barcode

Collections:
- wh_buildings: {id, code, name, address, active}
- wh_zones: {id, building_id, building_code, code, name, zone_type, description, active}
- wh_racks: {id, zone_id, building_id, code, name, num_shelves, slots_per_shelf, capacity_per_slot, unit, barcode_prefix, active}
- wh_positions: {id, rack_id, zone_id, building_id, shelf_no, slot_no, barcode, label, status, material_id, material_code, material_name, qty, unit, last_updated}

Barcode format: {BLDG}-{ZONE}-{RACK}-S{shelf}-P{slot}
e.g.: WH1-A-R01-S2-P3
2026-11-02: maksimal 18 karakter — awalan dipendekkan bila perlu (`assign_bin_prefix`, `wh_racks.bin_prefix`);
kode lama hasil migrasi disimpan di `wh_positions.barcode_aliases`.

Routes (all under /api/wms):
  Buildings:  GET/POST/PUT/DELETE /wms/buildings
  Zones:      GET/POST/PUT/DELETE /wms/zones
  Racks:      GET/POST/PUT/DELETE /wms/racks
  Positions:  GET /wms/positions?rack_id=&zone_id=
              GET /wms/positions/{barcode}  — by barcode (for scanner)
              PUT /wms/positions/{position_id}  — update content
  Map:        GET /wms/map/{building_id}  — full visual map data
"""

from routes.shared import lolos_centang  # 14 Nov 2026 (tahap 2): centang owner dihormati
import re
import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel, Field
from database import get_db
from auth import require_auth, serialize_doc, log_activity, require_demo_seed_allowed
from core.authz import izin_atau_peran_lama  # 14 Nov 2026: centang owner = penentu
from core.authz import only  # T-01 2.3
from core.roles import WAREHOUSE_ROLES  # T-01 2.3

router = APIRouter(prefix="/api/wms", tags=["wms-structure"])


def _uid(): return str(uuid.uuid4())


# ─── 2026-11-02 (keputusan owner barcode, butir 13): kode bin PENDEK ≤ 18 karakter ─────────
# Kode bin lama `{GEDUNG}-{ZONA}-{RAK}-Sxx-Pyy` bisa 25+ karakter → di label 65 mm hanya 10/24 terbaca
# (uji decode 203 dpi, core/label_render). Aturan baru, SATU generator (rak baru, tambah posisi, skrip
# migrasi `scripts/shorten_bin_codes.py`):
#   1. format lama dipakai bila kode terpanjang rak itu ≤ 18 karakter (label lama tetap sama);
#   2. selain itu awalan dipendekkan: gedung ≤3 + zona ≤2 (segmen terakhir: GD-L1 → L1, ZN-FG → FG), "-",
#      rak ≤ 4 (nomor ujung dipertahankan: RK-01 → RK01);
#   3. awalan yang sudah dipakai rak lain diberi akhiran pembeda (2..9, A..Z).
# Kode lama yang diganti skrip migrasi disimpan di `wh_positions.barcode_aliases` → tetap dikenali resolver.
BIN_CODE_MAX = 18
_SUFFIXES = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def bin_code(prefix: str, shelf: int, slot: int) -> str:
    return f"{prefix}-S{int(shelf):02d}-P{int(slot):02d}"


def _alnum(s) -> str:
    return re.sub(r"[^0-9A-Z]", "", str(s or "").upper())


def _seg(code, n: int) -> str:
    """Bagian pembeda kode gedung/zona: segmen TERAKHIR bila kode bersegmen (GD-L1 → L1, ZN-FG → FG)."""
    parts = [x for x in re.split(r"[^0-9A-Za-z]+", str(code or "").upper()) if x]
    pick = parts[-1] if len(parts) > 1 else "".join(parts)
    return pick[:n]


def _shorten(code: str, room: int) -> str:
    """Pendekkan kode rak: nomor di ujung dipertahankan (RAK01 → RA01), huruf depan dipotong."""
    if len(code) <= room:
        return code
    m = re.match(r"^(.*?)(\d+)$", code)
    if m and len(m.group(2)) < room:
        return m.group(1)[:room - len(m.group(2))] + m.group(2)
    return code[:room]


def bin_prefix_candidates(bldg: str, zone: str, rack: str, num_shelves: int, slots_per_shelf: int) -> list:
    """Urutan awalan kandidat (fungsi murni). Semua kandidat menghasilkan kode ≤ BIN_CODE_MAX."""
    budget = BIN_CODE_MAX - (len(bin_code("", num_shelves, slots_per_shelf)))
    out = []
    legacy = f"{bldg or 'WH'}-{zone or 'Z'}-{rack}"
    if len(legacy) <= budget:
        out.append(legacy)
    b, z, r = _seg(bldg, 3) or "WH", _seg(zone, 2) or "Z", _alnum(rack) or "R"
    head = f"{b}{z}-"
    room = budget - len(head)
    if room < 2:                                   # gedung+zona terlalu panjang untuk rak bernomor besar
        head = f"{b[:2]}{z[:1]}-"
        room = budget - len(head)
    r = _shorten(r, room)
    base = f"{head}{r}"
    out.append(base)
    stem = f"{head}{r[:max(1, room - 1)]}"
    out += [f"{stem}{c}" for c in _SUFFIXES]
    return list(dict.fromkeys(out))


async def assign_bin_prefix(db, rack: dict, *, taken: Optional[set] = None) -> str:
    """Awalan kode bin untuk rak ini (dipakai ulang bila sudah tersimpan & masih muat)."""
    shelves, slots = int(rack.get("num_shelves") or 1), int(rack.get("slots_per_shelf") or 1)
    cur = rack.get("bin_prefix")
    if cur and len(bin_code(cur, shelves, slots)) <= BIN_CODE_MAX:
        return cur
    taken = set(taken or ())
    async for r in db.wh_racks.find({"id": {"$ne": rack.get("id")}, "bin_prefix": {"$nin": [None, ""]}},
                                    {"_id": 0, "bin_prefix": 1}):
        taken.add(r["bin_prefix"].upper())
    for cand in bin_prefix_candidates(rack.get("building_code"), rack.get("zone_code"), rack.get("code"),
                                      shelves, slots):
        if cand.upper() in taken:
            continue
        clash = await db.wh_positions.find_one(
            {"rack_id": {"$ne": rack.get("id")},
             "$or": [{"barcode": {"$regex": f"^{re.escape(cand)}-S", "$options": "i"}},
                     {"barcode_aliases": {"$regex": f"^{re.escape(cand)}-S", "$options": "i"}}]},
            {"_id": 0, "id": 1})
        if not clash:
            return cand
    raise HTTPException(400, "Tidak menemukan kode rak pendek yang unik — ganti kode rak/zona.")
def _now(): return datetime.now(timezone.utc)


# ─── Models ───────────────────────────────────────────────────────────────────

class BuildingIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=20)
    name: str = Field(..., min_length=1)
    address: Optional[str] = None
    description: Optional[str] = None


class ZoneIn(BaseModel):
    building_id: str
    code: str = Field(..., min_length=1, max_length=20)
    name: str = Field(..., min_length=1)
    zone_type: str = Field("general", description="rm | fg | wip | general | transit")
    description: Optional[str] = None
    # 2026-11-02 (K9): lokasi gudang (`rahaza_locations.id`) tempat zona ini berada. Dibaca mesin opname
    # (`core.opname_engine.location_scope`) supaya rak/bin zona ikut cakupan opname lokasi itu.
    # None = tidak diubah (PUT) / tanpa tautan (POST); "" = lepas tautan.
    location_id: Optional[str] = None


class RackIn(BaseModel):
    zone_id: str
    code: str = Field(..., min_length=1, max_length=20)
    name: str = Field(..., min_length=1)
    num_shelves: int = Field(4, ge=1, le=50, description="Jumlah shelves dalam rak")
    slots_per_shelf: int = Field(5, ge=1, le=100, description="Jumlah slot per shelf")
    capacity_per_slot: float = Field(0, ge=0, description="Kapasitas per slot (0 = unlimited)")
    capacity_unit: Optional[str] = Field(None, description="Satuan kapasitas (kg, pcs, dll)")
    description: Optional[str] = None


class PositionUpdateIn(BaseModel):
    material_id: Optional[str] = None
    material_code: Optional[str] = None
    material_name: Optional[str] = None
    qty: float = Field(default=0, ge=0)
    unit: Optional[str] = None
    notes: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# BUILDINGS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/buildings")
async def list_buildings(request: Request):
    await require_auth(request)
    db = get_db()
    buildings = await db.wh_buildings.find({"active": True}, {"_id": 0}).sort("code", 1).to_list(500)
    # Enrich with zone + rack counts
    for b in buildings:
        b["zone_count"] = await db.wh_zones.count_documents({"building_id": b["id"], "active": True})
        b["rack_count"] = await db.wh_racks.count_documents({"building_id": b["id"], "active": True})
    return serialize_doc(buildings)


@router.post("/buildings")
async def create_building(data: BuildingIn, request: Request):
    user = await require_auth(request)
    db = get_db()
    code = data.code.upper().strip()
    if await db.wh_buildings.find_one({"code": code}):
        raise HTTPException(400, f"Kode gedung '{code}' sudah ada")
    building = building_doc(data, user)
    await db.wh_buildings.insert_one(building)
    await log_activity(user["id"], user.get("name",""), "create", "wh_building", f"Building: {code}")
    return serialize_doc({"message": "Gedung ditambahkan", "building": building})


@router.put("/buildings/{building_id}")
async def update_building(building_id: str, data: BuildingIn, request: Request):
    await require_auth(request)
    db = get_db()
    bldg = await db.wh_buildings.find_one({"id": building_id})
    if not bldg:
        raise HTTPException(404, "Gedung tidak ditemukan")
    await db.wh_buildings.update_one({"id": building_id}, {"$set": {
        "name": data.name, "address": data.address or "", "description": data.description or "",
        "updated_at": _now(),
    }})
    return {"message": "Gedung diupdate"}


# ─── Hapus permanen gedung/zona/rak (10 Nov 2026, permintaan owner "master data bisa dihapus") ─────────────
# Tanpa `?hard=true` endpoint DELETE tetap menonaktifkan (perilaku lama, dengan penjaga 400 lamanya). Dengan
# `hard`: boleh dihapus hanya bila struktur itu belum pernah menyimpan barang — tidak ada posisi terisi, stok
# bersaldo, riwayat stok/penempatan, opname, atau gulungan kain di posisinya; anak AKTIF (rak di zona, zona di
# gedung) harus dihapus dulu. Anak NONAKTIF yang juga bersih ikut terhapus (layar tidak menampilkannya lagi,
# jadi tidak bisa dihapus satu per satu). Bila sudah dipakai → 409 (`core.hapus_master`) dan layar menawarkan
# Nonaktifkan.
async def _pemakaian_lokasi(db, loc_ids: list) -> dict:
    """Stok bersaldo & riwayat stok yang menyimpan `location_id` gedung/zona/posisi ini."""
    from core.hapus_master import hitung_pemakaian
    from routes.rahaza_inventory_materials import baris_stok_bersaldo
    ids = [i for i in loc_ids if i]
    if not ids:
        return {}
    pakai = await hitung_pemakaian(db, [
        ("riwayat stok", "rahaza_stock_ledger", {"location_id": {"$in": ids}}),
    ])
    n = await baris_stok_bersaldo(db, {"location_id": {"$in": ids}})
    return {"lokasi stok bersaldo": n, **pakai} if n else pakai


async def _pemakaian_rak(db, rack_ids: list) -> dict:
    """Pemakaian posisi (bin) milik rak-rak ini: terisi, stok/riwayat, penempatan, opname, gulungan kain."""
    from core.hapus_master import hitung_pemakaian
    if not rack_ids:
        return {}
    pos_ids = [p["id"] async for p in db.wh_positions.find({"rack_id": {"$in": rack_ids}}, {"_id": 0, "id": 1})]
    pakai = await hitung_pemakaian(db, [
        ("posisi terisi", "wh_positions", {"rack_id": {"$in": rack_ids}, "status": "occupied"}),
    ])
    if pos_ids:
        pakai.update(await _pemakaian_lokasi(db, pos_ids))
        for label, n in (await hitung_pemakaian(db, [
            ("riwayat penempatan rak", "wh_placement_movements", {"position_id": {"$in": pos_ids}}),
            ("opname stok", "wh_opname3_sessions", {"lines.bin_id": {"$in": pos_ids}}),
            ("gulungan kain", "wh_fabric_rolls", {"position_id": {"$in": pos_ids}}),
        ])).items():
            pakai[label] = pakai.get(label, 0) + n
    return pakai


def _gabung(*bagian: dict) -> dict:
    out: dict = {}
    for b in bagian:
        for k, v in (b or {}).items():
            if v:
                out[k] = out.get(k, 0) + v
    return out


async def _hapus_rak_permanen(db, rack_ids: list) -> int:
    if not rack_ids:
        return 0
    await db.wh_positions.delete_many({"rack_id": {"$in": rack_ids}})
    res = await db.wh_racks.delete_many({"id": {"$in": rack_ids}})
    return res.deleted_count


def _nama(doc: dict) -> str:
    return f"{doc.get('code') or ''} {doc.get('name') or ''}".strip()


@router.delete("/buildings/{building_id}", dependencies=only(*WAREHOUSE_ROLES, perm="wh.bin.manage"))  # T-01 2.3
async def delete_building(building_id: str, request: Request, hard: bool = Query(False)):
    user = await require_auth(request)
    db = get_db()
    if hard:
        from core.hapus_master import tolak_bila_dipakai, SARAN_NONAKTIF
        bldg = await db.wh_buildings.find_one({"id": building_id}, {"_id": 0})
        if not bldg:
            raise HTTPException(404, "Gedung tidak ditemukan")
        zone_ids = [z["id"] async for z in db.wh_zones.find({"building_id": building_id}, {"_id": 0, "id": 1})]
        rack_ids = [r["id"] async for r in db.wh_racks.find(
            {"$or": [{"building_id": building_id}, {"zone_id": {"$in": zone_ids}}]}, {"_id": 0, "id": 1})]
        aktif = {
            "zona aktif": await db.wh_zones.count_documents({"building_id": building_id, "active": True}),
            "rak aktif": await db.wh_racks.count_documents({"id": {"$in": rack_ids}, "active": True}),
        }
        pakai = _gabung(aktif, await _pemakaian_rak(db, rack_ids),
                        await _pemakaian_lokasi(db, [building_id, *zone_ids]),
                        {"tautan lokasi gudang lama": await db.wh_location_migration_map.count_documents(
                            {"wh_zone_id": {"$in": zone_ids}})} if zone_ids else {})
        saran = "Hapus atau nonaktifkan zona dan raknya dulu." if any(aktif.values()) else SARAN_NONAKTIF
        tolak_bila_dipakai("Gedung", _nama(bldg), pakai, saran)
        n_rak = await _hapus_rak_permanen(db, rack_ids)
        n_zona = (await db.wh_zones.delete_many({"building_id": building_id})).deleted_count
        await db.wh_buildings.delete_one({"id": building_id})
        await log_activity(user["id"], user.get("name", ""), "delete", "wh_building",
                           f"Gedung {bldg.get('code')} dihapus permanen (zona nonaktif {n_zona}, rak nonaktif {n_rak})")
        return {"message": "Gedung dihapus", "deleted": True}
    rack_count = await db.wh_racks.count_documents({"building_id": building_id, "active": True})
    if rack_count > 0:
        raise HTTPException(400, f"Gedung masih memiliki {rack_count} rak aktif. Hapus/nonaktifkan rak dulu.")
    await db.wh_buildings.update_one({"id": building_id}, {"$set": {"active": False, "updated_at": _now()}})
    return {"message": "Gedung dinonaktifkan"}


# ══════════════════════════════════════════════════════════════════════════════
# ZONES
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/zones")
async def list_zones(request: Request, building_id: Optional[str] = None):
    await require_auth(request)
    db = get_db()
    q = {"active": True}
    if building_id:
        q["building_id"] = building_id
    zones = await db.wh_zones.find(q, {"_id": 0}).sort("code", 1).to_list(500)
    loc_ids = sorted({z.get("location_id") or z.get("rahaza_location_id") for z in zones} - {None, ""})
    locs = {x["id"]: x async for x in db.rahaza_locations.find(
        {"id": {"$in": loc_ids}}, {"_id": 0, "id": 1, "code": 1, "name": 1})} if loc_ids else {}
    for z in zones:
        z["rack_count"] = await db.wh_racks.count_documents({"zone_id": z["id"], "active": True})
        lid = z.get("location_id") or z.get("rahaza_location_id")
        z["location_id"] = lid or None
        z["location_code"] = (locs.get(lid) or {}).get("code")
        z["location_name"] = (locs.get(lid) or {}).get("name")
    return serialize_doc(zones)


async def _zone_location(db, location_id: Optional[str]) -> dict:
    """Field tautan zona → lokasi gudang (2026-11-02, K9). Lokasi wajib ada & aktif."""
    lid = (location_id or "").strip()
    if not lid:
        return {"location_id": None, "location_code": None, "location_name": None}
    loc = await db.rahaza_locations.find_one({"id": lid, "active": {"$ne": False}}, {"_id": 0})
    if not loc:
        raise HTTPException(400, "Lokasi gudang yang ditautkan tidak ditemukan / nonaktif.")
    return {"location_id": lid, "location_code": loc.get("code"), "location_name": loc.get("name")}


@router.post("/zones")
async def create_zone(data: ZoneIn, request: Request):
    user = await require_auth(request)
    db = get_db()
    building = await db.wh_buildings.find_one({"id": data.building_id, "active": True}, {"_id": 0})
    if not building:
        raise HTTPException(404, "Gedung tidak ditemukan")
    code = data.code.upper().strip()
    if await db.wh_zones.find_one({"building_id": data.building_id, "code": code}):
        raise HTTPException(400, f"Kode zona '{code}' sudah ada di gedung ini")
    zone = zone_doc(building, data, await _zone_location(db, data.location_id), user)
    await db.wh_zones.insert_one(zone)
    await log_activity(user["id"], user.get("name",""), "create", "wh_zone", f"Zone: {building['code']}-{code}")
    return serialize_doc({"message": "Zona ditambahkan", "zone": zone})


@router.put("/zones/{zone_id}")
async def update_zone(zone_id: str, data: ZoneIn, request: Request):
    await require_auth(request)
    db = get_db()
    zone = await db.wh_zones.find_one({"id": zone_id})
    if not zone:
        raise HTTPException(404, "Zona tidak ditemukan")
    upd = {"name": data.name, "zone_type": data.zone_type, "description": data.description or "",
           "updated_at": _now()}
    if data.location_id is not None:      # None = tautan lokasi tidak diubah
        upd.update(await _zone_location(db, data.location_id))
    await db.wh_zones.update_one({"id": zone_id}, {"$set": upd})
    return {"message": "Zona diupdate"}


@router.delete("/zones/{zone_id}", dependencies=only(*WAREHOUSE_ROLES, perm="wh.bin.manage"))  # T-01 2.3
async def delete_zone(zone_id: str, request: Request, hard: bool = Query(False)):
    user = await require_auth(request)
    db = get_db()
    if hard:
        from core.hapus_master import tolak_bila_dipakai, SARAN_NONAKTIF
        zone = await db.wh_zones.find_one({"id": zone_id}, {"_id": 0})
        if not zone:
            raise HTTPException(404, "Zona tidak ditemukan")
        rack_ids = [r["id"] async for r in db.wh_racks.find({"zone_id": zone_id}, {"_id": 0, "id": 1})]
        aktif = {"rak aktif": await db.wh_racks.count_documents({"zone_id": zone_id, "active": True})}
        pakai = _gabung(aktif, await _pemakaian_rak(db, rack_ids), await _pemakaian_lokasi(db, [zone_id]),
                        {"tautan lokasi gudang lama": await db.wh_location_migration_map.count_documents(
                            {"wh_zone_id": zone_id})})
        saran = "Hapus atau nonaktifkan rak di zona ini dulu." if any(aktif.values()) else SARAN_NONAKTIF
        tolak_bila_dipakai("Zona", _nama(zone), pakai, saran)
        n_rak = await _hapus_rak_permanen(db, rack_ids)
        await db.wh_zones.delete_one({"id": zone_id})
        await log_activity(user["id"], user.get("name", ""), "delete", "wh_zone",
                           f"Zona {zone.get('building_code') or ''}-{zone.get('code')} dihapus permanen (rak nonaktif {n_rak})")
        return {"message": "Zona dihapus", "deleted": True}
    rack_count = await db.wh_racks.count_documents({"zone_id": zone_id, "active": True})
    if rack_count > 0:
        raise HTTPException(400, f"Zona masih memiliki {rack_count} rak. Hapus/nonaktifkan rak dulu.")
    await db.wh_zones.update_one({"id": zone_id}, {"$set": {"active": False, "updated_at": _now()}})
    return {"message": "Zona dinonaktifkan"}


# ══════════════════════════════════════════════════════════════════════════════
# RACKS
# ══════════════════════════════════════════════════════════════════════════════

async def _generate_positions(db, rack: dict):
    """Auto-generate position slots for a rack based on num_shelves × slots_per_shelf."""
    num_shelves = rack["num_shelves"]
    slots_per_shelf = rack["slots_per_shelf"]
    bldg_code = rack.get("building_code", "WH")
    zone_code = rack.get("zone_code", "Z")
    rack_code = rack["code"]
    # 2026-11-02: awalan kode bin dari `assign_bin_prefix` (≤ 18 karakter); cadangan = format lama
    prefix = rack.get("bin_prefix") or f"{bldg_code}-{zone_code}-{rack_code}"

    positions = []
    for shelf in range(1, num_shelves + 1):
        for slot in range(1, slots_per_shelf + 1):
            positions.append(_position_doc(rack, prefix, shelf, slot, bldg_code, zone_code, rack_code))
    if positions:
        await db.wh_positions.insert_many(positions)
    return len(positions)


def _position_doc(rack: dict, prefix: str, shelf: int, slot: int,
                  bldg_code: str, zone_code: str, rack_code: str) -> dict:
    return {
        "id": _uid(),
        "rack_id": rack["id"],
        "zone_id": rack["zone_id"],
        "building_id": rack["building_id"],
        "building_code": bldg_code,
        "zone_code": zone_code,
        "rack_code": rack_code,
        "shelf_no": shelf,
        "slot_no": slot,
        "barcode": bin_code(prefix, shelf, slot),
        "label": f"Shelf {shelf}, Slot {slot}",
        "status": "empty",  # empty | occupied | reserved
        "material_id": None,
        "material_code": None,
        "material_name": None,
        "qty": 0,
        "unit": None,
        "lot_number": None,
        "notes": "",
        "last_updated": _now(),
    }


async def add_missing_positions(db, rack_id: str) -> int:
    """Tambah posisi (bin) yang belum ada untuk ukuran rak SEKARANG; posisi lama tidak dihapus (stok aman).

    2026-11-06 (T4): dipisah dari PUT /racks supaya impor Excel Data Transfer memakai jalur yang sama.
    2026-11-06 (pola P7): daftar posisi lama dulu `to_list(500)` — rak > 500 bin (mis. 10 susun × 60 slot)
    terpotong sehingga posisi yang SUDAH ada dibuat ulang (kode bin kembar). Sekarang dibaca penuh.
    """
    rack = await db.wh_racks.find_one({"id": rack_id}, {"_id": 0})
    if not rack:
        return 0
    existing = set()
    async for p in db.wh_positions.find({"rack_id": rack_id}, {"_id": 0, "shelf_no": 1, "slot_no": 1}):
        existing.add((p.get("shelf_no"), p.get("slot_no")))
    # 2026-11-02: posisi baru memakai awalan pendek (≤ 18 karakter) yang sama dengan generator rak baru
    prefix = await assign_bin_prefix(db, rack)
    if prefix != rack.get("bin_prefix"):
        await db.wh_racks.update_one({"id": rack_id}, {"$set": {"bin_prefix": prefix}})
    new_positions = [
        _position_doc(rack, prefix, shelf, slot, rack.get("building_code", "WH"), rack.get("zone_code", "Z"),
                      rack["code"])
        for shelf in range(1, int(rack["num_shelves"]) + 1)
        for slot in range(1, int(rack["slots_per_shelf"]) + 1)
        if (shelf, slot) not in existing
    ]
    if new_positions:
        await db.wh_positions.insert_many(new_positions)
    return len(new_positions)


def building_doc(data: "BuildingIn", user: dict) -> dict:
    """Bentuk dokumen gedung baru — 2026-11-06 (T4): satu sumber untuk form & impor Excel."""
    return {
        "id": _uid(), "code": data.code.upper().strip(), "name": data.name,
        "address": data.address or "", "description": data.description or "",
        "active": True, "created_at": _now(), "created_by": user.get("email", "system"),
    }


def zone_doc(building: dict, data: "ZoneIn", location_fields: dict, user: dict) -> dict:
    """Bentuk dokumen zona baru (dengan tautan lokasi K9) — 2026-11-06 (T4): form & impor Excel."""
    return {
        "id": _uid(), "building_id": building["id"], "building_code": building["code"],
        "building_name": building["name"], "code": data.code.upper().strip(), "name": data.name,
        "zone_type": data.zone_type, "description": data.description or "",
        **location_fields,
        "active": True, "created_at": _now(), "created_by": user.get("email", "system"),
    }


async def insert_rack(db, zone: dict, building: dict, data: "RackIn", user: dict, *,
                      taken: Optional[set] = None) -> tuple:
    """Simpan rak baru + buat semua posisinya. Return (rak, jumlah posisi).
    2026-11-06 (T4): dipisah dari POST /racks supaya impor Excel Data Transfer memakai jalur yang sama."""
    rack = {
        "id": _uid(),
        "zone_id": zone["id"],
        "zone_code": zone["code"],
        "zone_name": zone["name"],
        "building_id": zone["building_id"],
        "building_code": building["code"],
        "building_name": building["name"],
        "code": data.code.upper().strip(),
        "name": data.name,
        "num_shelves": data.num_shelves,
        "slots_per_shelf": data.slots_per_shelf,
        "capacity_per_slot": data.capacity_per_slot,
        "capacity_unit": data.capacity_unit or "",
        "description": data.description or "",
        "active": True,
        "created_at": _now(),
        "created_by": user.get("email", "system"),
    }
    rack["bin_prefix"] = await assign_bin_prefix(db, rack, taken=taken)   # 2026-11-02: kode bin ≤ 18 karakter
    await db.wh_racks.insert_one(rack)
    return rack, await _generate_positions(db, rack)


@router.get("/racks")
async def list_racks(request: Request, zone_id: Optional[str] = None, building_id: Optional[str] = None):
    await require_auth(request)
    db = get_db()
    q = {"active": True}
    if zone_id:
        q["zone_id"] = zone_id
    if building_id:
        q["building_id"] = building_id
    racks = await db.wh_racks.find(q, {"_id": 0}).sort("code", 1).to_list(500)
    for r in racks:
        total = r["num_shelves"] * r["slots_per_shelf"]
        occupied = await db.wh_positions.count_documents({"rack_id": r["id"], "status": "occupied"})
        r["total_positions"] = total
        r["occupied_positions"] = occupied
        r["empty_positions"] = total - occupied
        r["occupancy_pct"] = round(occupied / total * 100) if total else 0
    return serialize_doc(racks)


@router.post("/racks")
async def create_rack(data: RackIn, request: Request):
    user = await require_auth(request)
    db = get_db()
    zone = await db.wh_zones.find_one({"id": data.zone_id, "active": True}, {"_id": 0})
    if not zone:
        raise HTTPException(404, "Zona tidak ditemukan")
    building = await db.wh_buildings.find_one({"id": zone["building_id"], "active": True}, {"_id": 0})
    if not building:
        raise HTTPException(404, "Gedung tidak ditemukan")

    code = data.code.upper().strip()
    if await db.wh_racks.find_one({"zone_id": data.zone_id, "code": code}):
        raise HTTPException(400, f"Kode rak '{code}' sudah ada di zona ini")

    rack, pos_count = await insert_rack(db, zone, building, data, user)

    await log_activity(user["id"], user.get("name",""), "create", "wh_rack",
                       f"Rack {building['code']}-{zone['code']}-{code} ({pos_count} positions)")

    return serialize_doc({
        "message": f"Rak ditambahkan dengan {pos_count} posisi",
        "rack": rack,
        "positions_created": pos_count,
    })


@router.put("/racks/{rack_id}")
async def update_rack(rack_id: str, data: RackIn, request: Request):
    await require_auth(request)
    db = get_db()
    rack = await db.wh_racks.find_one({"id": rack_id}, {"_id": 0})
    if not rack:
        raise HTTPException(404, "Rak tidak ditemukan")

    old_shelves = rack["num_shelves"]
    old_slots = rack["slots_per_shelf"]
    new_shelves = data.num_shelves
    new_slots = data.slots_per_shelf
    structure_changed = (old_shelves != new_shelves) or (old_slots != new_slots)

    await db.wh_racks.update_one({"id": rack_id}, {"$set": {
        "name": data.name, "num_shelves": new_shelves,
        "slots_per_shelf": new_slots,
        "capacity_per_slot": data.capacity_per_slot,
        "capacity_unit": data.capacity_unit or "",
        "description": data.description or "", "updated_at": _now(),
    }})

    added = await add_missing_positions(db, rack_id) if structure_changed else 0

    return serialize_doc({"message": f"Rak diupdate{f', {added} posisi baru ditambahkan' if added else ''}"})


@router.delete("/racks/{rack_id}", dependencies=only(*WAREHOUSE_ROLES, perm="wh.bin.manage"))  # T-01 2.3
async def delete_rack(rack_id: str, request: Request, hard: bool = Query(False)):
    user = await require_auth(request)
    db = get_db()
    if hard:
        from core.hapus_master import tolak_bila_dipakai
        rack = await db.wh_racks.find_one({"id": rack_id}, {"_id": 0})
        if not rack:
            raise HTTPException(404, "Rak tidak ditemukan")
        tolak_bila_dipakai("Rak", _nama(rack), await _pemakaian_rak(db, [rack_id]))
        await _hapus_rak_permanen(db, [rack_id])
        await log_activity(user["id"], user.get("name", ""), "delete", "wh_rack",
                           f"Rak {rack.get('code')} dihapus permanen beserta posisinya")
        return {"message": "Rak dihapus", "deleted": True}
    occupied = await db.wh_positions.count_documents({"rack_id": rack_id, "status": "occupied"})
    if occupied > 0:
        raise HTTPException(400, f"Rak masih memiliki {occupied} posisi terisi. Pindahkan barang dulu.")
    await db.wh_racks.update_one({"id": rack_id}, {"$set": {"active": False, "updated_at": _now()}})
    return {"message": "Rak dinonaktifkan"}


# ══════════════════════════════════════════════════════════════════════════════
# POSITIONS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/positions")
async def list_positions(
    request: Request,
    rack_id: Optional[str] = None,
    zone_id: Optional[str] = None,
    building_id: Optional[str] = None,
    status: Optional[str] = None,
    material_id: Optional[str] = None,
):
    await require_auth(request)
    db = get_db()
    q = {}
    if rack_id:
        q["rack_id"] = rack_id
    if zone_id:
        q["zone_id"] = zone_id
    if building_id:
        q["building_id"] = building_id
    if status:
        q["status"] = status
    if material_id:
        q["material_id"] = material_id
    positions = await db.wh_positions.find(q, {"_id": 0}).sort([("shelf_no", 1), ("slot_no", 1)]).to_list(500)
    return serialize_doc(positions)


@router.get("/positions/by-barcode/{barcode}")
async def get_position_by_barcode(barcode: str, request: Request):
    """Scan barcode → get full position info (for scanner search)."""
    await require_auth(request)
    db = get_db()
    from core.scan_resolver import position_by_barcode  # SSOT kode scan (2026-11-02)
    pos = await position_by_barcode(db, barcode)
    if not pos:
        raise HTTPException(404, f"Posisi dengan barcode '{barcode}' tidak ditemukan")
    return serialize_doc(pos)


@router.put("/positions/{position_id}")
async def update_position(position_id: str, data: PositionUpdateIn, request: Request):
    """Manually update position content (admin correction)."""
    user = await require_auth(request)
    db = get_db()
    pos = await db.wh_positions.find_one({"id": position_id})
    if not pos:
        raise HTTPException(404, "Posisi tidak ditemukan")
    status = "occupied" if (data.material_id and data.qty > 0) else "empty"
    await db.wh_positions.update_one({"id": position_id}, {"$set": {
        "material_id": data.material_id, "material_code": data.material_code,
        "material_name": data.material_name, "qty": data.qty, "unit": data.unit,
        "notes": data.notes or "", "status": status, "last_updated": _now(),
        "updated_by": user.get("email", "system"),
    }})
    return {"message": "Posisi diupdate"}


# ══════════════════════════════════════════════════════════════════════════════
# WAREHOUSE MAP
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/map/{building_id}")
async def get_warehouse_map(building_id: str, request: Request):
    """
    Returns full warehouse map data for interactive dashboard.
    Structure: building → zones → racks → positions (summarized)
    """
    await require_auth(request)
    db = get_db()

    building = await db.wh_buildings.find_one({"id": building_id, "active": True}, {"_id": 0})
    if not building:
        raise HTTPException(404, "Gedung tidak ditemukan")

    zones = await db.wh_zones.find({"building_id": building_id, "active": True}, {"_id": 0}).sort("code", 1).to_list(500)

    for zone in zones:
        racks = await db.wh_racks.find({"zone_id": zone["id"], "active": True}, {"_id": 0}).sort("code", 1).to_list(500)
        for rack in racks:
            total = rack["num_shelves"] * rack["slots_per_shelf"]
            occupied = await db.wh_positions.count_documents({"rack_id": rack["id"], "status": "occupied"})
            reserved = await db.wh_positions.count_documents({"rack_id": rack["id"], "status": "reserved"})
            empty = total - occupied - reserved
            rack["total"] = total
            rack["occupied"] = occupied
            rack["reserved"] = reserved
            rack["empty"] = empty
            rack["occupancy_pct"] = round(occupied / total * 100) if total else 0
            # Color coding
            pct = rack["occupancy_pct"]
            rack["color"] = "red" if pct >= 90 else "orange" if pct >= 70 else "green" if pct < 30 else "yellow"

            # Top materials in this rack
            top_mats = await db.wh_positions.aggregate([
                {"$match": {"rack_id": rack["id"], "status": "occupied", "material_id": {"$ne": None}}},
                {"$group": {"_id": "$material_code", "name": {"$first": "$material_name"}, "total_qty": {"$sum": "$qty"}, "unit": {"$first": "$unit"}}},
                {"$sort": {"total_qty": -1}}, {"$limit": 3}
            ]).to_list(500)
            rack["top_materials"] = [{"code": t["_id"], "name": t["name"], "qty": t["total_qty"], "unit": t["unit"]} for t in top_mats]

        zone["racks"] = racks
        zone["rack_count"] = len(racks)
        zone_total = sum(r["total"] for r in racks)
        zone_occupied = sum(r["occupied"] for r in racks)
        zone["total_positions"] = zone_total
        zone["occupied_positions"] = zone_occupied
        zone["occupancy_pct"] = round(zone_occupied / zone_total * 100) if zone_total else 0

    building["zones"] = zones
    return serialize_doc(building)


# ══════════════════════════════════════════════════════════════════════════════
# SMART SEARCH by SCANNER / BARCODE
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/search")
async def warehouse_search(
    request: Request,
    q: Optional[str] = Query(None, description="Scan barcode or type material code/name"),
    building_id: Optional[str] = None,
):
    """
    Smart search: scan item barcode OR type material code/name.
    Returns all positions where this item is stored.
    """
    await require_auth(request)
    db = get_db()

    if not q or not q.strip():
        return {"positions": [], "materials": []}

    # 2026-11-02 — hasil scan lewat SSOT `core.scan_resolver` (normalisasi + tanpa
    # beda huruf + QR label FG). Dulu teks scan masuk mentah ke `$regex` sehingga
    # kode seperti `AST-001(` membuat HTTP 500.
    from core import scan_resolver as sr
    query_str = sr.normalize_code(q)

    # 1. Barcode posisi
    pos_by_barcode = await sr.position_by_barcode(db, query_str)
    if pos_by_barcode:
        return serialize_doc({"type": "position", "result": pos_by_barcode})

    # 2. Kode barang persis (FG/bahan) → cadangan: kode/nama mengandung teks
    hit = await sr.resolve_item(db, query_str)
    if hit:
        materials = [hit["_doc"]]
    else:
        rx = {"$regex": re.escape(query_str), "$options": "i"}
        materials = await db.rahaza_materials.find(
            {"$or": [{"code": rx}, {"name": rx}]}, {"_id": 0}).limit(5).to_list(500)
    mat_ids = [m["id"] for m in materials]

    pos_q = {"material_id": {"$in": mat_ids}, "status": "occupied"}
    if building_id:
        pos_q["building_id"] = building_id
    positions = await db.wh_positions.find(pos_q, {"_id": 0}).sort("qty", -1).to_list(500)

    return serialize_doc({
        "type": "material",
        "materials": materials,
        "positions": positions,
        "total_qty": sum(p.get("qty", 0) for p in positions),
    })


# ══════════════════════════════════════════════════════════════════════════════
# OCCUPANCY ALERTS — Rak yang penuh (>= threshold)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/alerts/occupancy")
async def occupancy_alerts(
    request: Request,
    threshold: int = Query(90, ge=0, le=100, description="Minimum occupancy percentage to flag"),
    building_id: Optional[str] = None,
):
    """
    Mengembalikan daftar rak yang occupancy-nya >= threshold% (default 90%).
    Berguna untuk banner alert di dashboard gudang.
    """
    await require_auth(request)
    db = get_db()
    rack_q = {"active": True}
    if building_id:
        rack_q["building_id"] = building_id
    racks = await db.wh_racks.find(rack_q, {"_id": 0}).to_list(500)

    critical = []
    warning = []
    for r in racks:
        total = (r.get("num_shelves") or 0) * (r.get("slots_per_shelf") or 0)
        if total <= 0:
            continue
        occupied = await db.wh_positions.count_documents({"rack_id": r["id"], "status": "occupied"})
        pct = round(occupied / total * 100) if total else 0
        if pct < threshold:
            continue
        item = {
            "rack_id": r["id"], "rack_code": r.get("code"), "rack_name": r.get("name"),
            "zone_id": r.get("zone_id"), "zone_code": r.get("zone_code"),
            "building_id": r.get("building_id"), "building_code": r.get("building_code"),
            "occupied": occupied, "total": total, "occupancy_pct": pct,
            "free_slots": total - occupied,
            "severity": "critical" if pct >= 95 else "warning",
        }
        if pct >= 95:
            critical.append(item)
        else:
            warning.append(item)
    # Sort by pct desc
    critical.sort(key=lambda x: -x["occupancy_pct"])
    warning.sort(key=lambda x: -x["occupancy_pct"])

    return serialize_doc({
        "threshold": threshold,
        "building_id": building_id,
        "critical_count": len(critical),
        "warning_count": len(warning),
        "total_alerts": len(critical) + len(warning),
        "critical": critical,
        "warning": warning,
    })


# ══════════════════════════════════════════════════════════════════════════════
# FASE B — STRUKTUR STORAGE KANONIK + PETA MIGRASI LOKASI (wh_location_migration_map)
# ══════════════════════════════════════════════════════════════════════════════
# 4 zona storage kanonik di GD-01 + pemetaan dari rahaza_locations (STORAGE saja).
# Zona PRODUKSI (GED-A/B, ZNA-CUTTING/SEWING/QC/PACKING) SENGAJA TIDAK dipetakan —
# tetap milik model produksi/HR (rahaza_locations), tidak dikonflasikan ke wh_*.
CANONICAL_STORAGE_ZONES = [
    {  # reuse zona RM generik lama (ZN-01) bila ada, agar tak muncul zona "duplikat"
        "role": "bahan", "rahaza_codes": ["ZNA-KAIN"],
        "reuse_codes": ["ZN-01", "ZN-KAIN"],
        "code": "ZN-KAIN", "name": "Zona Bahan / Kain", "zone_type": "rm",
    },
    {
        "role": "aksesoris", "rahaza_codes": ["ZNA-AKSESORIS"],
        "reuse_codes": ["ZN-AKS", "ZN-AKSESORIS"],
        "code": "ZN-AKS", "name": "Zona Aksesoris", "zone_type": "general",
    },
    {
        "role": "fg", "rahaza_codes": ["ZNA-FG"],
        "reuse_codes": ["ZN-FG"],
        "code": "ZN-FG", "name": "Zona Produk Jadi", "zone_type": "fg",
    },
    {
        "role": "sample", "rahaza_codes": ["ZNA-SAMPLE"],
        "reuse_codes": ["ZN-SAMPLE", "ZN-SMP"],
        "code": "ZN-SAMPLE", "name": "Zona Sample / RnD", "zone_type": "general",
    },
]


async def _ensure_zone(db, building, spec, user):
    """Idempotent: reuse zona lama (reuse_codes) bila ada; jika tidak, buat baru."""
    for rc in spec["reuse_codes"]:
        z = await db.wh_zones.find_one({"building_id": building["id"], "code": rc, "active": True}, {"_id": 0})
        if z:
            return z, False
    zone = {
        "id": _uid(), "building_id": building["id"], "building_code": building["code"],
        "building_name": building["name"], "code": spec["code"], "name": spec["name"],
        "zone_type": spec["zone_type"], "description": "Zona storage kanonik (Fase B).",
        "active": True, "created_at": _now(), "created_by": user.get("email", "system"),
    }
    await db.wh_zones.insert_one(zone)
    return zone, True


async def _ensure_starter_rack(db, zone, user):
    """Pastikan zona punya minimal 1 rak aktif. Jika belum ada, buat RK-01 (4x6=24 bin)."""
    if await db.wh_racks.count_documents({"zone_id": zone["id"], "active": True}) > 0:
        return None, 0
    building = await db.wh_buildings.find_one({"id": zone["building_id"]}, {"_id": 0})
    rack = {
        "id": _uid(), "zone_id": zone["id"], "zone_code": zone["code"], "zone_name": zone["name"],
        "building_id": zone["building_id"], "building_code": building["code"], "building_name": building["name"],
        "code": "RK-01", "name": "Rak Utama", "num_shelves": 4, "slots_per_shelf": 6,
        "capacity_per_slot": 50.0, "capacity_unit": "pcs", "description": "",
        "active": True, "created_at": _now(), "created_by": user.get("email", "system"),
    }
    await db.wh_racks.insert_one(rack)
    n = await _generate_positions(db, rack)
    return rack, n


@router.post("/structure/build-canonical-storage")
async def build_canonical_storage(request: Request):
    """
    FASE B (idempotent): pastikan 4 zona storage kanonik ada di GD-01 + starter rack,
    lalu bangun/refresh `wh_location_migration_map` (rahaza storage location → wh zone).
    Aman diulang; tidak menghapus/menimpa penempatan fisik yang sudah ada.
    """
    user = await require_auth(request)
    if not (izin_atau_peran_lama(user, ["admin"]) or lolos_centang(user)):
        raise HTTPException(403, "Hanya admin/superadmin yang boleh membangun struktur gudang.")
    db = get_db()

    building = await db.wh_buildings.find_one({"code": "GD-01", "active": True}, {"_id": 0}) \
        or await db.wh_buildings.find_one({"active": True}, {"_id": 0})
    if not building:
        raise HTTPException(404, "Tidak ada gedung WMS aktif. Buat gedung dulu.")

    result = {"building": building["code"], "zones_created": 0, "zones_reused": 0,
              "racks_created": 0, "positions_created": 0, "map_entries": 0, "zones": [], "map": []}

    for spec in CANONICAL_STORAGE_ZONES:
        zone, created = await _ensure_zone(db, building, spec, user)
        result["zones_created" if created else "zones_reused"] += 1
        rack, npos = await _ensure_starter_rack(db, zone, user)
        if rack:
            result["racks_created"] += 1
            result["positions_created"] += npos
        result["zones"].append({
            "role": spec["role"], "code": zone["code"], "name": zone["name"], "id": zone["id"],
            "created": created, "starter_rack": rack["code"] if rack else None,
        })
        for rcode in spec["rahaza_codes"]:
            loc = await db.rahaza_locations.find_one({"code": rcode}, {"_id": 0})
            entry = {
                "rahaza_location_id": loc["id"] if loc else None,
                "rahaza_code": rcode, "rahaza_name": (loc or {}).get("name"),
                "wh_building_id": building["id"], "wh_building_code": building["code"],
                "wh_zone_id": zone["id"], "wh_zone_code": zone["code"], "wh_zone_name": zone["name"],
                "role": spec["role"], "active": True, "updated_at": _now(),
            }
            await db.wh_location_migration_map.update_one(
                {"rahaza_code": rcode},
                {"$set": entry, "$setOnInsert": {"id": _uid(), "created_at": _now()}},
                upsert=True,
            )
            result["map_entries"] += 1
            result["map"].append({"rahaza_code": rcode, "wh_zone_code": zone["code"],
                                   "role": spec["role"], "rahaza_resolved": bool(loc)})

    await log_activity(user["id"], user.get("name", ""), "build", "wh_structure",
                       f"Canonical storage: +{result['zones_created']} zona, map {result['map_entries']}")
    return serialize_doc({"message": "Struktur storage kanonik & peta migrasi siap.", **result})


@router.get("/structure/location-map")
async def get_location_map(request: Request):
    """Peta migrasi lokasi (rahaza storage → wh zone) untuk Fase C & audit."""
    await require_auth(request)
    db = get_db()
    rows = await db.wh_location_migration_map.find({"active": True}, {"_id": 0}).sort("rahaza_code", 1).to_list(500)
    return serialize_doc(rows)



# ══════════════════════════════════════════════════════════════════════════════
# SEED DEMO STRUCTURE
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/structure/seed-demo")
async def seed_demo_structure(request: Request):
    """Seed 1 building with 2 zones (RM + FG) and sample racks."""
    require_demo_seed_allowed()  # pagar produksi: ALLOW_DEMO_SEED=false → 403 (2026-11-04)
    await require_auth(request)
    db = get_db()
    created = {"buildings": 0, "zones": 0, "racks": 0, "positions": 0}

    # Building
    if not await db.wh_buildings.find_one({"code": "WH1"}):
        bldg = {
            "id": _uid(), "code": "WH1", "name": "Gudang Utama",
            "address": "Jl. Industri No. 1", "description": "Gudang utama bahan baku dan barang jadi",
            "active": True, "created_at": _now(), "created_by": "seed",
        }
        await db.wh_buildings.insert_one(bldg)
        created["buildings"] += 1

        bldg_doc = bldg
    else:
        bldg_doc = await db.wh_buildings.find_one({"code": "WH1"}, {"_id": 0})

    # Zones
    zone_defs = [
        {"code": "RM", "name": "Zona Bahan Baku", "zone_type": "rm"},
        {"code": "FG", "name": "Zona Barang Jadi", "zone_type": "fg"},
        {"code": "WIP", "name": "Zona Work-in-Progress", "zone_type": "wip"},
    ]
    zone_docs = {}
    for zd in zone_defs:
        if not await db.wh_zones.find_one({"building_id": bldg_doc["id"], "code": zd["code"]}):
            zone = {
                "id": _uid(), "building_id": bldg_doc["id"],
                "building_code": bldg_doc["code"], "building_name": bldg_doc["name"],
                "code": zd["code"], "name": zd["name"], "zone_type": zd["zone_type"],
                "description": "", "active": True, "created_at": _now(), "created_by": "seed",
            }
            await db.wh_zones.insert_one(zone)
            created["zones"] += 1
            zone_docs[zd["code"]] = zone
        else:
            zone_docs[zd["code"]] = await db.wh_zones.find_one({"building_id": bldg_doc["id"], "code": zd["code"]}, {"_id": 0})

    # Racks (RM zone: R01-R03, FG zone: R01-R02)
    rack_defs = [
        {"zone": "RM", "code": "R01", "name": "Rak Kain A", "shelves": 4, "slots": 6},
        {"zone": "RM", "code": "R02", "name": "Rak Kain B", "shelves": 4, "slots": 6},
        {"zone": "RM", "code": "R03", "name": "Rak Aksesori", "shelves": 5, "slots": 8},
        {"zone": "FG", "code": "R01", "name": "Rak FG Kemeja", "shelves": 4, "slots": 5},
        {"zone": "FG", "code": "R02", "name": "Rak FG Celana", "shelves": 4, "slots": 5},
    ]
    for rd in rack_defs:
        zone_doc = zone_docs.get(rd["zone"])
        if not zone_doc:
            continue
        if not await db.wh_racks.find_one({"zone_id": zone_doc["id"], "code": rd["code"]}):
            rack = {
                "id": _uid(), "zone_id": zone_doc["id"], "zone_code": zone_doc["code"],
                "zone_name": zone_doc["name"], "building_id": bldg_doc["id"],
                "building_code": bldg_doc["code"], "building_name": bldg_doc["name"],
                "code": rd["code"], "name": rd["name"],
                "num_shelves": rd["shelves"], "slots_per_shelf": rd["slots"],
                "capacity_per_slot": 0, "capacity_unit": "",
                "description": "", "active": True, "created_at": _now(), "created_by": "seed",
            }
            await db.wh_racks.insert_one(rack)
            created["racks"] += 1
            pos_count = await _generate_positions(db, rack)
            created["positions"] += pos_count

    return serialize_doc({"message": "Demo struktur gudang seeded", **created})

"""
CV. Dewi Aditya Official — Master Data Produksi

Endpoints (all under /api/rahaza):
  - /locations    : Gedung & Zona
  - /processes    : Proses produksi (seed static, read + toggle)
  - /shifts       : Shift kerja (CRUD)
  - /machines     : Mesin jahit/cutting (CRUD)
  - /lines        : Line Produksi / CMT (CRUD)
  - /employees    : Karyawan/Operator (CRUD)

Conventions:
  - All documents use UUID string `id`.
  - `active` flag (soft disable).
  - Timestamps in UTC.
  - DELETE tanpa parameter = nonaktifkan (perilaku lama). `?hard=true` (10 Nov 2026, permintaan owner "master data
    bisa dihapus") = hapus permanen bila belum dipakai (`core.hapus_master` → 409 + rincian), hanya untuk pengelola
    modulnya (lihat `_GERBANG_HAPUS`).
"""
# ruff: noqa: E741
from fastapi import APIRouter, Request, HTTPException
from database import get_db
from auth import require_auth, serialize_doc, log_activity, check_role
from core.roles import HR_ROLES, PRODUCTION_ROLES, WAREHOUSE_ROLES
from typing import Optional
import uuid
import logging
import os
from datetime import datetime, timezone
from utils.waktu import today_wib

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rahaza", tags=["rahaza-master"])


def _uid() -> str:
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


# ─── SEED DEFAULTS ───────────────────────────────────────────────────────────
DEFAULT_LOCATIONS = [
    # Gedung utama CV. Dewi Aditya Official — Sragen
    {"code": "GED-A", "name": "Gedung Produksi", "type": "gedung", "parent_id": None},
    {"code": "GED-B", "name": "Gedung Gudang", "type": "gedung", "parent_id": None},
    # Zona produksi
    {"code": "ZNA-CUTTING",   "name": "Zona Cutting",     "type": "zona", "parent_code": "GED-A"},
    {"code": "ZNA-SEWING",    "name": "Zona Jahit/CMT",   "type": "zona", "parent_code": "GED-A"},
    {"code": "ZNA-QC",        "name": "Zona QC",          "type": "zona", "parent_code": "GED-A"},
    {"code": "ZNA-PACKING",   "name": "Zona Packing",     "type": "zona", "parent_code": "GED-A"},
    # Zona gudang
    {"code": "ZNA-KAIN",      "name": "Area Kain (Lt.2)", "type": "zona", "parent_code": "GED-B"},
    {"code": "ZNA-AKSESORIS", "name": "Area Aksesoris",   "type": "zona", "parent_code": "GED-B"},
    {"code": "ZNA-FG",        "name": "Area Produk Jadi", "type": "zona", "parent_code": "GED-B"},
    {"code": "ZNA-KARANTINA", "name": "Area Karantina QC (retur rusak, tidak dijual)", "type": "zona", "parent_code": "GED-B"},
    {"code": "ZNA-SAMPLE",    "name": "Area Sample/RnD",  "type": "zona", "parent_code": "GED-A"},
]

# Proses produksi — urutan sesuai alur CV. Dewi Aditya (Fashion Garment)
# Cutting → CMT Sewing → Finishing → QC → Packing
DEFAULT_PROCESSES = [
    {"code": "CUTTING",  "name": "Cutting",       "order_seq": 1, "is_rework": False, "description": "Penggulungan kain, lay, marking, dan potong sesuai pola"},
    {"code": "SEWING",   "name": "Jahit (CMT)",   "order_seq": 2, "is_rework": False, "description": "Proses jahit oleh CMT atau Divisi Pola & Sample internal"},
    {"code": "FINISHING","name": "Finishing",     "order_seq": 3, "is_rework": False, "description": "Pengecekan benang, label, obras, dan persiapan QC"},
    {"code": "QC",       "name": "QC Final",      "order_seq": 4, "is_rework": False, "description": "Quality control sebelum packing — cek kerapian, ukuran, label"},
    {"code": "PACKING",  "name": "Packing",       "order_seq": 5, "is_rework": False, "description": "Pengemasan OPP bag → polymailer, scan resi, siap kirim"},
    {"code": "REWORK",   "name": "Rework/Revisi", "order_seq": 10,"is_rework": True,  "description": "Perbaikan untuk item yang gagal QC / reject dari CMT"},
]

DEFAULT_SHIFTS = [
    {"code": "S1", "name": "Shift 1", "start_time": "07:00", "end_time": "15:00"},
    {"code": "S2", "name": "Shift 2", "start_time": "15:00", "end_time": "23:00"},
]


async def seed_rahaza_master_data():
    """Idempotent seed dipanggil dari server.py startup."""
    db = get_db()

    # Locations (2 Gedung + 4 Zona). Go-live data nyata: SEED_DEFAULT_LOCATIONS=false
    # mematikan seed ini; lokasi (dan perannya: fg/kain/aksesoris/karantina) datang
    # dari 01_LOKASI berkas master owner.
    code_to_id = {}
    seed_locations = os.environ.get("SEED_DEFAULT_LOCATIONS", "true").strip().lower() \
        not in ("false", "0", "tidak", "no")
    loc_codes = [loc["code"] for loc in DEFAULT_LOCATIONS] if seed_locations else []
    if not seed_locations:
        logging.getLogger(__name__).info("  · Seed lokasi bawaan DIMATIKAN (SEED_DEFAULT_LOCATIONS=false)")
    existing_locs = {}
    if loc_codes:
        async for d in db.rahaza_locations.find({"code": {"$in": loc_codes}}, {"_id": 0}):
            existing_locs[d["code"]] = d
    for loc in (DEFAULT_LOCATIONS if seed_locations else []):
        existing = existing_locs.get(loc["code"])
        if existing:
            code_to_id[loc["code"]] = existing["id"]
            continue
        parent_code = loc.pop("parent_code", None)
        loc_doc = {
            "id": _uid(),
            "code": loc["code"],
            "name": loc["name"],
            "type": loc["type"],
            "parent_id": code_to_id.get(parent_code) if parent_code else loc.get("parent_id"),
            "active": True,
            "created_at": _now(),
            "updated_at": _now(),
        }
        await db.rahaza_locations.insert_one(loc_doc)
        code_to_id[loc["code"]] = loc_doc["id"]
    logging.getLogger(__name__).info(f"  · Rahaza locations seeded (total codes: {len(code_to_id)})")

    # Processes (upsert + update order_seq for flow changes)
    seeded_proc = 0
    updated_proc = 0
    proc_codes = [proc["code"] for proc in DEFAULT_PROCESSES]
    existing_procs = {}
    if proc_codes:
        async for d in db.rahaza_processes.find({"code": {"$in": proc_codes}}, {"_id": 0}):
            existing_procs[d["code"]] = d
    for proc in DEFAULT_PROCESSES:
        existing = existing_procs.get(proc["code"])
        if existing:
            if str(existing.get("import_source") or "").startswith("master_template"):
                continue  # nama/keterangan milik owner (impor master) — jangan ditimpa tiap boot
            # Update order_seq, name, description, is_rework if changed
            updates = {}
            if existing.get("order_seq") != proc.get("order_seq"):
                updates["order_seq"] = proc["order_seq"]
            if existing.get("name") != proc.get("name"):
                updates["name"] = proc["name"]
            if existing.get("description") != proc.get("description"):
                updates["description"] = proc["description"]
            if existing.get("is_rework") != proc.get("is_rework"):
                updates["is_rework"] = proc["is_rework"]
            if updates:
                updates["updated_at"] = _now()
                await db.rahaza_processes.update_one({"code": proc["code"]}, {"$set": updates})
                updated_proc += 1
            continue
        await db.rahaza_processes.insert_one({
            "id": _uid(),
            **proc,
            "active": True,
            "created_at": _now(),
            "updated_at": _now(),
        })
        seeded_proc += 1
    
    # Deactivate old knit processes (RAJUT, LINKING, STEAM) if they exist (migration from PT Rahaza)
    old_procs = ["RAJUT", "LINKING", "STEAM", "WASHER", "SONTEK"]
    for code in old_procs:
        result = await db.rahaza_processes.update_one(
            {"code": code, "active": {"$ne": False}},
            {"$set": {"active": False, "updated_at": _now()}}
        )
        if result.modified_count > 0:
            logging.getLogger(__name__).info(f"  · Deactivated old process: {code}")
    
    if seeded_proc or updated_proc:
        logging.getLogger(__name__).info(f"  · Rahaza processes seeded/updated ({seeded_proc} baru, {updated_proc} diupdate)")

    # Shifts
    seeded_shift = 0
    shift_codes = [sh["code"] for sh in DEFAULT_SHIFTS]
    existing_shifts = set()
    if shift_codes:
        async for d in db.rahaza_shifts.find({"code": {"$in": shift_codes}}, {"_id": 0, "code": 1}):
            existing_shifts.add(d["code"])
    for sh in DEFAULT_SHIFTS:
        if sh["code"] in existing_shifts:
            continue
        await db.rahaza_shifts.insert_one({
            "id": _uid(),
            **sh,
            "active": True,
            "created_at": _now(),
            "updated_at": _now(),
        })
        seeded_shift += 1
    if seeded_shift:
        logging.getLogger(__name__).info(f"  · Rahaza shifts seeded ({seeded_shift} baru)")


# ─── Generic helpers ─────────────────────────────────────────────────────────
async def _require_admin(request: Request):
    # RBAC master product (keputusan user): SEMUA staff internal boleh CRUD master.
    # Hanya role eksternal (vendor/klien) yang ditolak.
    user = await require_auth(request)
    role = (user.get("role") or "").lower()
    if role in ("cmt_vendor", "vendor", "klien_maklon"):
        raise HTTPException(403, "Akses master hanya untuk staff internal.")
    return user


# ─── Hapus permanen (10 Nov 2026, owner: "pastikan table table master data bisa dihapus") ─────────────────────
# Menonaktifkan tetap boleh untuk semua staf internal (keputusan lama di atas). Menghapus permanen lebih berat →
# hanya pengelola modul pemilik master itu (kode peran ATAU izin modulnya di data/module_catalog.py).
_GERBANG_HAPUS = {
    "lokasi": (("admin", *WAREHOUSE_ROLES), ("wh.bin.manage", "warehouse.manage"),
               "Hanya pengelola gudang yang boleh menghapus lokasi."),
    "lokasi_kerja": (("admin", *HR_ROLES), ("hr.employee.manage", "hr.manage"),
                     "Hanya HR dan manajemen yang boleh menghapus lokasi kerja."),
    "produksi": (("admin", *PRODUCTION_ROLES), ("prod.master.manage", "prod.line.manage"),
                 "Hanya pengelola master produksi yang boleh menghapus lini atau mesin."),
    "shift": (("admin", *HR_ROLES), ("hr.attendance.manage", "hr.manage"),
              "Hanya HR dan manajemen yang boleh menghapus shift."),
    "karyawan": (("admin", *HR_ROLES), ("hr.employee.manage", "hr.manage"),
                 "Hanya HR dan manajemen yang boleh menghapus data karyawan."),
}


def _wajib_pengelola(user: dict, kunci: str) -> None:
    roles, perms, pesan = _GERBANG_HAPUS[kunci]
    if not check_role(user, list(roles), perms):
        raise HTTPException(403, pesan)


def _ids(v) -> dict:
    """Filter id yang tahan beda tipe (shift lama ber-id angka, master baru ber-id teks)."""
    return {"$in": list(dict.fromkeys([v, str(v)]))}


async def pemakaian_lokasi(db, lid: str) -> dict:
    """Di mana lokasi gudang dipakai: stok & mutasi per lokasi, zona/rak anak, dan master lain yang menunjuknya."""
    from core.hapus_master import hitung_pemakaian
    dari_ke = {"$or": [{"location_id": lid}, {"from_location_id": lid}, {"to_location_id": lid}]}
    return await hitung_pemakaian(db, [
        ("zona/lokasi anak", "rahaza_locations", {"parent_id": lid}),
        ("baris stok bahan", "rahaza_material_stock", {"location_id": lid}),
        ("mutasi stok", "rahaza_material_movements", dari_ke),
        ("kartu stok", "rahaza_stock_ledger", {"location_id": lid}),
        ("mutasi barang jadi", "rahaza_fg_movements", dari_ke),
        ("pengeluaran barang jadi", "rahaza_fg_issues", {"location_id": lid}),
        ("permintaan bahan", "rahaza_material_issues", {"$or": [{"location_id": lid}, {"items.location_id": lid}]}),
        ("penerimaan barang", "warehouse_receiving", {"location_id": lid}),
        ("surat jalan", "wh_delivery_notes", {"$or": [{"from_location_id": lid}, {"to_location_id": lid}]}),
        ("zona gudang", "wh_zones", {"location_id": lid}),
        ("mesin", "rahaza_machines", {"location_id": lid}),
        ("lini produksi", "rahaza_lines", {"location_id": lid}),
        # lokasi KANTOR = lokasi kerja karyawan (SDM › Lokasi kerja) dan lingkup jadwal shift
        ("karyawan", "rahaza_employees", {"location_id": lid}),
        ("jadwal shift", "rahaza_schedules", {"location_id": lid}),
    ])


async def pemakaian_lini(db, lid: str) -> dict:
    from core.hapus_master import hitung_pemakaian
    return await hitung_pemakaian(db, [
        ("penugasan lini", "rahaza_line_assignments", {"line_id": lid}),
        ("catatan produksi", "rahaza_wip_events", {"line_id": lid}),
        ("catatan mesin berhenti", "rahaza_machine_downtime", {"line_id": lid}),
    ])


async def pemakaian_mesin(db, mid: str) -> dict:
    from core.hapus_master import hitung_pemakaian
    return await hitung_pemakaian(db, [
        ("catatan mesin berhenti", "rahaza_machine_downtime", {"machine_id": mid}),
        ("catatan perawatan", "rahaza_maintenance_logs", {"machine_id": mid}),
        ("penugasan lini", "rahaza_line_assignments", {"machine_id": mid}),
        ("catatan produksi", "rahaza_wip_events", {"machine_id": mid}),
    ])


async def pemakaian_shift(db, sid) -> dict:
    """Satu master shift (`rahaza_shifts`) dipakai layar Produksi (/rahaza/shifts) dan SDM (/hr/shifts)."""
    from core.hapus_master import hitung_pemakaian
    ids = _ids(sid)
    return await hitung_pemakaian(db, [
        ("karyawan (shift utama)", "rahaza_employees", {"shift_id": ids}),
        ("penugasan shift", "hr_shift_assignments", {"shift_id": ids}),
        ("jadwal shift", "rahaza_schedules", {"shifts.shift_id": ids}),
        ("pola rotasi", "hr_shift_pola", {"urutan": ids}),
        ("absensi", "rahaza_attendance_events", {"shift_id": ids}),
        ("penugasan lini", "rahaza_line_assignments", {"shift_id": ids}),
        ("serah terima shift", "rahaza_shift_handovers", {"shift_id": ids}),
        ("permintaan tukar/ganti shift", "hr_shift_requests",
         {"$or": [{"shift_asal.id": ids}, {"shift_diminta.id": ids}, {"rekan_shift_asal.id": ids}]}),
    ])


async def pemakaian_karyawan(db, emp: dict) -> dict:
    """Riwayat apa pun milik karyawan. Hapus permanen hanya untuk data yang salah input (belum punya riwayat)."""
    from core.hapus_master import hitung_pemakaian
    eid = emp["id"]
    akun = {"$or": [{"employee_id": eid}, {"id": emp["user_id"]}]} if emp.get("user_id") else {"employee_id": eid}
    return await hitung_pemakaian(db, [
        ("absensi", "rahaza_attendance_events", {"employee_id": eid}),
        ("absensi lama", "rahaza_attendance", {"employee_id": eid}),
        ("koreksi absensi", "rahaza_attendance_corrections", {"employee_id": eid}),
        ("slip gaji", "rahaza_payslips", {"employee_id": eid}),
        ("kasbon", "rahaza_employee_loans", {"employee_id": eid}),
        ("pengajuan kasbon", "dewi_kasbon_requests", {"employee_id": eid}),
        ("klaim biaya", "rahaza_expense_claims", {"employee_id": eid}),
        ("perjalanan dinas", "employee_travel_requests", {"employee_id": eid}),
        ("pengajuan cuti", "rahaza_leave_requests", {"employee_id": eid}),
        ("saldo cuti terpakai", "rahaza_leave_balances", {"employee_id": eid, "used": {"$gt": 0}}),
        ("lembur", "rahaza_overtime_requests", {"employee_id": eid}),
        ("penyesuaian gaji", "rahaza_salary_adjustments", {"employee_id": eid}),
        ("perubahan data karyawan", "rahaza_employee_data_changes", {"employee_id": eid}),
        ("jadwal shift", "rahaza_schedules", {"shifts.employee_id": eid}),
        ("permintaan tukar/ganti shift", "hr_shift_requests", {"$or": [{"employee_id": eid}, {"rekan_employee_id": eid}]}),
        ("penugasan lini", "rahaza_line_assignments", {"$or": [{"operator_id": eid}, {"employee_id": eid}]}),
        ("catatan produksi", "rahaza_wip_events", {"operator_id": eid}),
        ("tunjangan khusus", "da_payroll_allowances", {"employee_ids": eid}),
        ("karyawan bawahan", "rahaza_employees", {"manager_id": eid}),
        ("kepala unit organisasi", "dewi_org_units", {"head_employee_id": eid}),
        ("akun login tertaut", "users", akun),
        ("dokumen karyawan", "attachments", {"entity_type": "employee", "entity_id": eid, "is_deleted": {"$ne": True}}),
    ])


# ─── LOCATIONS (Gedung & Zona; Kantor = lokasi kerja karyawan) ───────────────
# 10 Nov 2026 (keputusan owner): lokasi KANTOR (KTR-PST/ADM/HRD/MKT, dipakai karyawan sebagai lokasi kerja) memakai
# master yang sama tetapi dikelola di SDM › Lokasi kerja; Gudang › Lokasi gudang hanya menampilkan gedung & zona.
LOCATION_TYPES = ("gedung", "zona", "kantor")


def _tolak_peran_gudang_kantor(type_: str, storage_role: str) -> None:
    if type_ == "kantor" and storage_role:
        raise HTTPException(400, "Lokasi kantor tidak menyimpan stok, jadi tidak boleh punya peran gudang. "
                                 "Kosongkan peran gudang, atau pilih jenis gedung/zona.")


@router.get("/locations")
async def list_locations(request: Request, include_inactive: bool = False):
    await require_auth(request)
    db = get_db()
    q = {} if include_inactive else {"active": True}
    rows = await db.rahaza_locations.find(q, {"_id": 0}).sort([("type", 1), ("name", 1)]).to_list(500)
    # Enrich with parent name
    by_id = {r["id"]: r for r in rows}
    for r in rows:
        if r.get("parent_id"):
            parent = by_id.get(r["parent_id"])
            r["parent_name"] = parent["name"] if parent else None
    return serialize_doc(rows)


@router.post("/locations")
async def create_location(request: Request):
    user = await _require_admin(request)
    db = get_db()
    body = await request.json()
    code = (body.get("code") or "").strip().upper()
    name = (body.get("name") or "").strip()
    type_ = (body.get("type") or "zona").lower()
    if not code or not name:
        raise HTTPException(400, "code & name required")
    if type_ not in LOCATION_TYPES:
        raise HTTPException(400, "Jenis lokasi harus gedung, zona, atau kantor.")
    if await db.rahaza_locations.find_one({"code": code, "active": True}):
        raise HTTPException(409, f"Kode '{code}' sudah terpakai (aktif). Gunakan kode lain.")
    # 10 Nov 2026 (owner): zona di bawah gedung; KANTOR (lokasi kerja karyawan, layar SDM › Lokasi kerja) boleh di
    # bawah kantor induk (mis. Ruang Admin di bawah Kantor Pusat). Gedung selalu teratas.
    parent_id = (body.get("parent_id") or None) if type_ in ("zona", "kantor") else None
    # 2026-11-06 (pola P8): nama setara di induk yang sama ditolak (kode beda, tempat sama = stok terbelah)
    from core.reference_dedup import assert_unique_ref
    await assert_unique_ref(db, "rahaza_locations", name=name, label="Lokasi", scope={"parent_id": parent_id})
    from core.location_resolver import STORAGE_ROLES, EXEMPT_ROLES
    storage_role = (body.get("storage_role") or "").strip().lower()
    _tolak_peran_gudang_kantor(type_, storage_role)
    if storage_role and storage_role not in STORAGE_ROLES + EXEMPT_ROLES:
        raise HTTPException(400, f"Peran gudang '{storage_role}' tidak dikenal. Pilihan: "
                                 f"{', '.join(STORAGE_ROLES + EXEMPT_ROLES)}")
    doc = {
        "id": _uid(),
        "code": code,
        "name": name,
        "type": type_,
        "parent_id": parent_id,
        "storage_role": storage_role or None,
        "active": True,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.rahaza_locations.insert_one(doc)
    await log_activity(user["id"], user.get("name", ""), "create", "rahaza.location", f"{code} {name}")
    return serialize_doc(doc)


@router.put("/locations/{loc_id}")
async def update_location(loc_id: str, request: Request):
    user = await _require_admin(request)
    db = get_db()
    body = await request.json()
    body.pop("_id", None)
    body.pop("id", None)
    body.pop("created_at", None)
    body["updated_at"] = _now()
    if "code" in body:
        body["code"] = body["code"].strip().upper()
    if "type" in body or "storage_role" in body:   # 10 Nov 2026: kantor = lokasi kerja, bukan tempat stok
        cur = await db.rahaza_locations.find_one({"id": loc_id}, {"_id": 0, "type": 1, "storage_role": 1}) or {}
        type_ = str(body.get("type") or cur.get("type") or "").lower()
        if "type" in body and type_ not in LOCATION_TYPES:
            raise HTTPException(400, "Jenis lokasi harus gedung, zona, atau kantor.")
        # peran lama hanya diperiksa bila jenisnya BARU diganti ke kantor (data kantor lama tetap bisa diubah)
        jadi_kantor = type_ == "kantor" and str(cur.get("type") or "").lower() != "kantor"
        peran = body["storage_role"] if "storage_role" in body else (cur.get("storage_role") if jadi_kantor else None)
        _tolak_peran_gudang_kantor(type_, str(peran or "").strip())
    res = await db.rahaza_locations.update_one({"id": loc_id}, {"$set": body})
    if res.matched_count == 0:
        raise HTTPException(404, "Not found")
    await log_activity(user["id"], user.get("name", ""), "update", "rahaza.location", loc_id)
    return serialize_doc(await db.rahaza_locations.find_one({"id": loc_id}, {"_id": 0}))


@router.delete("/locations/{loc_id}")
async def deactivate_location(loc_id: str, request: Request, hard: bool = False):
    """Tanpa `hard`: nonaktifkan (perilaku lama). `?hard=true`: hapus permanen bila lokasi belum punya stok/mutasi,
    zona anak, atau dipakai master lain; selain itu 409 (layar menawarkan Nonaktifkan)."""
    user = await _require_admin(request)
    db = get_db()
    if hard:
        from core.hapus_master import tolak_bila_dipakai
        loc = await db.rahaza_locations.find_one({"id": loc_id}, {"_id": 0})
        if not loc:
            raise HTTPException(404, "Lokasi tidak ditemukan.")
        # lokasi kantor (lokasi kerja) dikelola SDM; gedung/zona dikelola gudang
        _wajib_pengelola(user, "lokasi_kerja" if str(loc.get("type") or "").lower() == "kantor" else "lokasi")
        tolak_bila_dipakai("Lokasi", loc.get("name") or loc.get("code") or "", await pemakaian_lokasi(db, loc_id))
        await db.rahaza_locations.delete_one({"id": loc_id})
        await log_activity(user["id"], user.get("name", ""), "delete", "rahaza.location", f"{loc.get('code')} {loc.get('name')}")
        return {"status": "deleted", "deleted": True}
    await db.rahaza_locations.update_one({"id": loc_id}, {"$set": {"active": False, "updated_at": _now()}})
    await log_activity(user["id"], user.get("name", ""), "deactivate", "rahaza.location", loc_id)
    return {"status": "deactivated"}


# ─── PROCESSES (static, bisa toggle active) ──────────────────────────────────
@router.get("/processes")
async def list_processes(request: Request):
    await require_auth(request)
    db = get_db()
    rows = await db.rahaza_processes.find({}, {"_id": 0}).sort("order_seq", 1).to_list(500)
    return serialize_doc(rows)


@router.put("/processes/{pid}")
async def update_process(pid: str, request: Request):
    user = await _require_admin(request)
    db = get_db()
    body = await request.json()
    allowed = {k: body[k] for k in ("active", "description", "name") if k in body}
    if not allowed:
        return serialize_doc(await db.rahaza_processes.find_one({"id": pid}, {"_id": 0}))
    if allowed.get("name"):
        # 2026-11-06 (pola P8): proses tidak boleh diganti nama menjadi kembaran proses lain ("Jahit" vs "Sewing")
        from core.reference_dedup import assert_unique_ref
        await assert_unique_ref(db, "rahaza_processes", name=allowed["name"], label="Proses", exclude_id=pid)
    allowed["updated_at"] = _now()
    await db.rahaza_processes.update_one({"id": pid}, {"$set": allowed})
    await log_activity(user["id"], user.get("name", ""), "update", "rahaza.process", pid)
    return serialize_doc(await db.rahaza_processes.find_one({"id": pid}, {"_id": 0}))


@router.delete("/processes/{pid}")
async def deactivate_process(pid: str, request: Request):
    """Nonaktifkan proses (10 Nov 2026). Tombol Nonaktifkan layar Proses Produksi (MasterDataCRUD) sudah memanggil
    DELETE ini, tetapi rutenya tidak ada (405). Proses = daftar tetap yang dibuat ulang saat server mulai bila
    hilang, jadi TIDAK ada hapus permanen — cukup nonaktif (sama dengan PUT {active:false})."""
    user = await _require_admin(request)
    db = get_db()
    res = await db.rahaza_processes.update_one({"id": pid}, {"$set": {"active": False, "updated_at": _now()}})
    if res.matched_count == 0:
        raise HTTPException(404, "Proses tidak ditemukan.")
    await log_activity(user["id"], user.get("name", ""), "deactivate", "rahaza.process", pid)
    return {"status": "deactivated"}


# ─── SHIFTS ──────────────────────────────────────────────────────────────────
@router.get("/shifts")
async def list_shifts(request: Request):
    await require_auth(request)
    db = get_db()
    rows = await db.rahaza_shifts.find({}, {"_id": 0}).sort("start_time", 1).to_list(500)
    return serialize_doc(rows)


@router.post("/shifts")
async def create_shift(request: Request):
    user = await _require_admin(request)
    db = get_db()
    body = await request.json()
    code = (body.get("code") or "").strip().upper()
    name = (body.get("name") or "").strip()
    if not code or not name:
        raise HTTPException(400, "code & name required")
    if await db.rahaza_shifts.find_one({"code": code, "active": True}):
        raise HTTPException(409, f"Kode '{code}' sudah terpakai (aktif). Gunakan kode lain.")
    from core.reference_dedup import assert_unique_ref  # 2026-11-06 (pola P8)
    await assert_unique_ref(db, "rahaza_shifts", name=name, label="Shift")
    doc = {
        "id": _uid(),
        "code": code,
        "name": name,
        "start_time": body.get("start_time", ""),
        "end_time": body.get("end_time", ""),
        "active": True,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.rahaza_shifts.insert_one(doc)
    await log_activity(user["id"], user.get("name", ""), "create", "rahaza.shift", f"{code} {name}")
    return serialize_doc(doc)


@router.put("/shifts/{sid}")
async def update_shift(sid: str, request: Request):
    user = await _require_admin(request)
    db = get_db()
    body = await request.json()
    body.pop("_id", None)
    body.pop("id", None)
    body.pop("created_at", None)
    body["updated_at"] = _now()
    if "code" in body:
        body["code"] = body["code"].strip().upper()
    res = await db.rahaza_shifts.update_one({"id": sid}, {"$set": body})
    if res.matched_count == 0:
        raise HTTPException(404, "Not found")
    await log_activity(user["id"], user.get("name", ""), "update", "rahaza.shift", sid)
    return serialize_doc(await db.rahaza_shifts.find_one({"id": sid}, {"_id": 0}))


@router.delete("/shifts/{sid}")
async def deactivate_shift(sid: str, request: Request, hard: bool = False):
    """Tanpa `hard`: nonaktifkan. `?hard=true`: hapus permanen bila shift belum dipakai karyawan, penugasan,
    jadwal, pola, absensi, lini, atau serah terima; selain itu 409."""
    user = await _require_admin(request)
    db = get_db()
    if hard:
        from core.hapus_master import tolak_bila_dipakai
        _wajib_pengelola(user, "shift")
        sh = await db.rahaza_shifts.find_one({"id": sid}, {"_id": 0})
        if not sh:
            raise HTTPException(404, "Shift tidak ditemukan.")
        tolak_bila_dipakai("Shift", sh.get("name") or sh.get("code") or "", await pemakaian_shift(db, sid))
        await db.rahaza_shifts.delete_one({"id": sid})
        await log_activity(user["id"], user.get("name", ""), "delete", "rahaza.shift", f"{sh.get('code')} {sh.get('name')}")
        return {"status": "deleted", "deleted": True}
    res = await db.rahaza_shifts.update_one({"id": sid}, {"$set": {"active": False, "updated_at": _now()}})
    if res.matched_count == 0:
        raise HTTPException(404, "Not found")
    await log_activity(user["id"], user.get("name", ""), "deactivate", "rahaza.shift", sid)
    return {"status": "deactivated"}


# ─── MACHINES (Mesin Rajut) ─────────────────────────────────────────────────
@router.get("/machines")
async def list_machines(request: Request):
    await require_auth(request)
    db = get_db()
    rows = await db.rahaza_machines.find({}, {"_id": 0}).sort("code", 1).to_list(500)
    # enrich with location
    loc_ids = [r["location_id"] for r in rows if r.get("location_id")]
    loc_map = {}
    if loc_ids:
        locs = await db.rahaza_locations.find({"id": {"$in": loc_ids}}, {"_id": 0}).to_list(500)
        loc_map = {l["id"]: l["name"] for l in locs}
    for r in rows:
        r["location_name"] = loc_map.get(r.get("location_id"))
    return serialize_doc(rows)


@router.post("/machines")
async def create_machine(request: Request):
    user = await _require_admin(request)
    db = get_db()
    body = await request.json()
    code = (body.get("code") or "").strip().upper()
    name = (body.get("name") or "").strip() or code
    if not code:
        raise HTTPException(400, "code required")
    if await db.rahaza_machines.find_one({"code": code, "active": True}):
        raise HTTPException(409, f"Kode '{code}' sudah terpakai (aktif). Gunakan kode lain.")
    if body.get("name"):  # 2026-11-06 (pola P8): nama mesin setara ditolak (nama kosong = kode, sudah dicek)
        from core.reference_dedup import assert_unique_ref
        await assert_unique_ref(db, "rahaza_machines", name=name, label="Mesin")
    doc = {
        "id": _uid(),
        "code": code,
        "name": name,
        "machine_type": body.get("machine_type") or "Jahit",
        "gauge": body.get("gauge") or "",
        "location_id": body.get("location_id") or None,
        "status": body.get("status") or "idle",  # idle | active | maintenance
        "active": True,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.rahaza_machines.insert_one(doc)
    await log_activity(user["id"], user.get("name", ""), "create", "rahaza.machine", code)
    return serialize_doc(doc)


@router.put("/machines/{mid}")
async def update_machine(mid: str, request: Request):
    user = await _require_admin(request)
    db = get_db()
    body = await request.json()
    body.pop("_id", None)
    body.pop("id", None)
    body.pop("created_at", None)
    body["updated_at"] = _now()
    if "code" in body:
        body["code"] = body["code"].strip().upper()
    res = await db.rahaza_machines.update_one({"id": mid}, {"$set": body})
    if res.matched_count == 0:
        raise HTTPException(404, "Not found")
    await log_activity(user["id"], user.get("name", ""), "update", "rahaza.machine", mid)
    return serialize_doc(await db.rahaza_machines.find_one({"id": mid}, {"_id": 0}))


@router.delete("/machines/{mid}")
async def deactivate_machine(mid: str, request: Request, hard: bool = False):
    """Tanpa `hard`: nonaktifkan. `?hard=true`: hapus permanen bila mesin belum punya catatan; selain itu 409."""
    user = await _require_admin(request)
    db = get_db()
    if hard:
        from core.hapus_master import tolak_bila_dipakai
        _wajib_pengelola(user, "produksi")
        m = await db.rahaza_machines.find_one({"id": mid}, {"_id": 0})
        if not m:
            raise HTTPException(404, "Mesin tidak ditemukan.")
        tolak_bila_dipakai("Mesin", m.get("name") or m.get("code") or "", await pemakaian_mesin(db, mid))
        await db.rahaza_machines.delete_one({"id": mid})
        await log_activity(user["id"], user.get("name", ""), "delete", "rahaza.machine", m.get("code") or mid)
        return {"status": "deleted", "deleted": True}
    await db.rahaza_machines.update_one({"id": mid}, {"$set": {"active": False, "updated_at": _now()}})
    await log_activity(user["id"], user.get("name", ""), "deactivate", "rahaza.machine", mid)
    return {"status": "deactivated"}


# ─── LINES (Line Produksi) ───────────────────────────────────────────────────
@router.get("/lines")
async def list_lines(request: Request):
    await require_auth(request)
    db = get_db()
    rows = await db.rahaza_lines.find({}, {"_id": 0}).sort("code", 1).to_list(500)
    proc_ids = [r["process_id"] for r in rows if r.get("process_id")]
    loc_ids  = [r["location_id"] for r in rows if r.get("location_id")]
    procs = await db.rahaza_processes.find({"id": {"$in": proc_ids}}, {"_id": 0}).to_list(500) if proc_ids else []
    locs  = await db.rahaza_locations.find({"id": {"$in": loc_ids}}, {"_id": 0}).to_list(500) if loc_ids else []
    proc_map = {p["id"]: p["name"] for p in procs}
    loc_map  = {l["id"]: l["name"] for l in locs}
    for r in rows:
        r["process_name"]  = proc_map.get(r.get("process_id"))
        r["location_name"] = loc_map.get(r.get("location_id"))
    return serialize_doc(rows)


@router.post("/lines")
async def create_line(request: Request):
    user = await _require_admin(request)
    db = get_db()
    body = await request.json()
    code = (body.get("code") or "").strip().upper()
    name = (body.get("name") or "").strip() or code
    if not code:
        raise HTTPException(400, "code required")
    if await db.rahaza_lines.find_one({"code": code, "active": True}):
        raise HTTPException(409, f"Kode '{code}' sudah terpakai (aktif). Gunakan kode lain.")
    if body.get("name"):  # 2026-11-06 (pola P8)
        from core.reference_dedup import assert_unique_ref
        await assert_unique_ref(db, "rahaza_lines", name=name, label="Lini produksi")
    doc = {
        "id": _uid(),
        "code": code,
        "name": name,
        "process_id": body.get("process_id") or None,
        "location_id": body.get("location_id") or None,
        "capacity_per_hour": body.get("capacity_per_hour") or 0,
        "notes": body.get("notes") or "",
        "active": True,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.rahaza_lines.insert_one(doc)
    await log_activity(user["id"], user.get("name", ""), "create", "rahaza.line", code)
    return serialize_doc(doc)


@router.put("/lines/{lid}")
async def update_line(lid: str, request: Request):
    user = await _require_admin(request)
    db = get_db()
    body = await request.json()
    body.pop("_id", None)
    body.pop("id", None)
    body.pop("created_at", None)
    body["updated_at"] = _now()
    if "code" in body:
        body["code"] = body["code"].strip().upper()
    res = await db.rahaza_lines.update_one({"id": lid}, {"$set": body})
    if res.matched_count == 0:
        raise HTTPException(404, "Not found")
    await log_activity(user["id"], user.get("name", ""), "update", "rahaza.line", lid)
    return serialize_doc(await db.rahaza_lines.find_one({"id": lid}, {"_id": 0}))


@router.delete("/lines/{lid}")
async def deactivate_line(lid: str, request: Request, hard: bool = False):
    """Tanpa `hard`: nonaktifkan. `?hard=true`: hapus permanen bila lini belum punya penugasan/catatan; selain itu 409."""
    user = await _require_admin(request)
    db = get_db()
    if hard:
        from core.hapus_master import tolak_bila_dipakai
        _wajib_pengelola(user, "produksi")
        ln = await db.rahaza_lines.find_one({"id": lid}, {"_id": 0})
        if not ln:
            raise HTTPException(404, "Lini produksi tidak ditemukan.")
        tolak_bila_dipakai("Lini produksi", ln.get("name") or ln.get("code") or "", await pemakaian_lini(db, lid))
        await db.rahaza_lines.delete_one({"id": lid})
        await log_activity(user["id"], user.get("name", ""), "delete", "rahaza.line", ln.get("code") or lid)
        return {"status": "deleted", "deleted": True}
    await db.rahaza_lines.update_one({"id": lid}, {"$set": {"active": False, "updated_at": _now()}})
    await log_activity(user["id"], user.get("name", ""), "deactivate", "rahaza.line", lid)
    return {"status": "deactivated"}


@router.post("/employees/sync-user-employee-ids")
async def sync_user_employee_ids(request: Request):
    """
    Sync users.employee_id dari rahaza_employees.user_id (backward compat untuk dewi_kpi).
    Idempotent.
    """
    admin = await _require_admin(request)
    db    = get_db()
    count = 0
    async for emp in db.rahaza_employees.find(
        {"user_id": {"$exists": True, "$ne": None}, "active": True},
        {"_id": 0, "id": 1, "user_id": 1}
    ):
        r = await db.users.update_one(
            {"id": emp["user_id"]},
            {"$set": {"employee_id": emp["id"]}}
        )
        if r.modified_count:
            count += 1
    await log_activity(admin["id"], admin.get("name",""), "sync-user-employee-ids", "system", f"synced={count}")
    return {"ok": True, "synced": count}



# ─── EMPLOYEES (Karyawan / Operator) ─────────────────────────────────────────
@router.get("/employees")
async def list_employees(
    request: Request,
    limit: int = 50,
    skip: int = 0,
    active_only: bool = False,
    location_id: Optional[str] = None,
    search: Optional[str] = None,
):
    await require_auth(request)
    db = get_db()
    q: dict = {}
    if active_only:
        q["active"] = True
    if location_id:
        q["location_id"] = location_id
    if search:
        q["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"employee_code": {"$regex": search, "$options": "i"}},
        ]
    total = await db.rahaza_employees.count_documents(q)
    rows = await db.rahaza_employees.find(q, {"_id": 0}).sort("employee_code", 1).skip(skip).limit(limit).to_list(500)
    loc_ids = list({r["location_id"] for r in rows if r.get("location_id")})
    loc_map = {}
    if loc_ids:
        locs = await db.rahaza_locations.find({"id": {"$in": loc_ids}}, {"_id": 0}).to_list(500)
        loc_map = {l["id"]: l["name"] for l in locs}
    for r in rows:
        r["location_name"] = loc_map.get(r.get("location_id"))
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "has_more": (skip + limit) < total,
        "items": serialize_doc(rows),
    }


@router.get("/expiring-contracts")
async def expiring_contracts(request: Request, days: int = 30):
    """Karyawan PKWT/Magang dengan kontrak berakhir dalam N hari ke depan."""
    await require_auth(request)
    db = get_db()
    from datetime import date
    today = today_wib()
    cutoff = (today + __import__('datetime').timedelta(days=days)).isoformat()
    today_str = today.isoformat()

    rows = await db.rahaza_employees.find(
        {
            "active": True,
            "contract_end_date": {"$exists": True, "$nin": [None, ""], "$gte": today_str, "$lte": cutoff},
            "contract_type": {"$in": ["PKWT", "Magang"]},
        },
        {"_id": 0}
    ).sort("contract_end_date", 1).to_list(500)

    # Enrich with days_remaining
    for r in rows:
        try:
            end = date.fromisoformat(str(r.get("contract_end_date", ""))[:10])
            r["days_remaining"] = (end - today).days
        except Exception:
            r["days_remaining"] = None

    return {"ok": True, "count": len(rows), "employees": serialize_doc(rows)}


@router.post("/employees")
async def create_employee(request: Request):
    user = await _require_admin(request)
    db = get_db()
    body = await request.json()
    code = (body.get("employee_code") or "").strip().upper()
    name = (body.get("name") or "").strip()
    if not code or not name:
        raise HTTPException(400, "employee_code & name required")
    if await db.rahaza_employees.find_one({"employee_code": code, "active": True}):
        raise HTTPException(409, f"Kode '{code}' sudah terpakai (aktif). Gunakan kode lain.")
    
    # Validate manager_id (Atasan) if provided
    manager_id = body.get("manager_id") or None
    manager_name = None
    if manager_id:
        mgr = await db.rahaza_employees.find_one(
            {"id": manager_id, "active": True}, {"_id": 0, "id": 1, "name": 1}
        )
        if not mgr:
            raise HTTPException(400, "Atasan (manager) yang dipilih tidak ditemukan atau tidak aktif.")
        manager_name = mgr.get("name")
    shift_fields = await _employee_shift_fields(db, body)

    doc = {
        "id": _uid(),
        "employee_code": code,
        "name": name,
        # ─── Info Dasar
        "department": body.get("department") or "",
        # 2026-11-07 (OR2): tanpa jabatan = KOSONG (dulu otomatis "Operator" — jabatan palsu di laporan,
        # slip, dan struktur). Jabatan dipilih dari Struktur Organisasi di formulir Data Karyawan.
        "job_title": (body.get("job_title") or "").strip(),
        "location_id": body.get("location_id") or None,
        # 2026-11-07 (Tahap 5): shift utama karyawan (fallback absensi `resolve_day_shift`) — dulu hanya
        # terisi lewat impor; formulir Data Karyawan kini memilihnya dari master shift.
        **shift_fields,
        "phone": body.get("phone") or "",
        "email": (body.get("email") or "").strip().lower(),
        "contract_type": body.get("contract_type") or None,       # PKWT | PKWTT | Magang | Tetap
        "contract_start_date": body.get("contract_start_date") or None,
        "contract_end_date": body.get("contract_end_date") or None,
        # 2026-11-06 (Tahap 2): skema & tarif gaji TIDAK lagi disimpan di sini — satu sumber = Profil Gaji
        # (Penggajian). Tanggal masuk/keluar dipakai payroll untuk prorata.
        "join_date": (body.get("join_date") or "")[:10] or None,
        "resign_date": (body.get("resign_date") or "")[:10] or None,
        "joined_at": body.get("joined_at") or _now().isoformat(),
        # ─── Atasan / Manager (Sprint 42 - Salary Adjustment Workflow)
        "manager_id": manager_id,
        "manager_name": manager_name,
        # ─── Data Personal
        "gender": body.get("gender") or "",                       # L | P
        "birth_date": body.get("birth_date") or None,
        "birth_place": body.get("birth_place") or "",
        "marital_status": body.get("marital_status") or "",       # single | married | divorced | widowed
        "religion": body.get("religion") or "",
        "nationality": body.get("nationality") or "Indonesia",
        "ktp_address": body.get("ktp_address") or "",             # alamat sesuai KTP
        "current_address": body.get("current_address") or "",     # alamat tinggal sekarang
        "education_level": body.get("education_level") or "",     # SD | SMP | SMA/SMK | D1-D3 | S1 | S2 | S3
        "education_institution": body.get("education_institution") or "",
        "education_major": body.get("education_major") or "",
        "photo_url": body.get("photo_url") or "",
        # ─── Data Pajak & BPJS
        "ktp_number": body.get("ktp_number") or "",               # NIK 16 digit
        "npwp_number": body.get("npwp_number") or "",             # 15 digit
        "tax_ptkp": body.get("tax_ptkp") or "TK/0",               # TK/0 | K/0 | K/1 | K/2 | K/3
        "bpjs_kesehatan_number": body.get("bpjs_kesehatan_number") or "",
        "bpjs_ketenagakerjaan_number": body.get("bpjs_ketenagakerjaan_number") or "",
        # 2026-11-02 (K23): kepesertaan BPJS per program (centang Kes/JHT/JP/JKK-JKM). Tidak dikirim →
        # field tidak ditulis dan payroll menurunkannya dari nomor kartu (resolve_bpjs_programs).
        **_bpjs_programs_field(body),
        # ─── Bank
        "bank_name": body.get("bank_name") or "",                 # BCA | BRI | Mandiri | BNI | BSI | dll
        "bank_account_number": body.get("bank_account_number") or "",
        "bank_account_holder": body.get("bank_account_holder") or name,
        # ─── Emergency Contact
        "emergency_contact_name": body.get("emergency_contact_name") or "",
        "emergency_phone": body.get("emergency_phone") or "",
        "emergency_relation": body.get("emergency_relation") or "",  # Orang Tua | Pasangan | Saudara | Teman | dll
        "active": True,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.rahaza_employees.insert_one(doc)
    await log_activity(user["id"], user.get("name", ""), "create", "rahaza.employee", f"{code} {name}")
    return serialize_doc(doc)


async def _employee_shift_fields(db, body: dict, current: Optional[dict] = None) -> dict:
    """{'shift_id', 'shift_code'} dari master `rahaza_shifts` bila `shift_id` dikirim (2026-11-07, Tahap 5).

    Kosong/None → tanpa shift tetap. Id yang tidak ada di master ditolak (dulu kolom ini tidak divalidasi).
    Tidak dikirim, atau sama dengan nilai tersimpan (`current`) → {} (field tidak disentuh — data impor lama
    yang shift-nya sudah tidak ada di master tetap bisa diubah kolom lainnya)."""
    if "shift_id" not in body:
        return {}
    sid = body.get("shift_id") or None
    if current is not None and sid == (current.get("shift_id") or None):
        body.pop("shift_id", None)
        body.pop("shift_code", None)
        return {}
    if not sid:
        return {"shift_id": None, "shift_code": None}
    sh = await db.rahaza_shifts.find_one({"id": sid}, {"_id": 0, "id": 1, "code": 1})
    if not sh:
        raise HTTPException(400, "Shift yang dipilih tidak ditemukan di master shift.")
    return {"shift_id": sh["id"], "shift_code": sh.get("code") or None}


def _bpjs_programs_field(body: dict) -> dict:
    """{'bpjs_programs': {...}} bila dikirim, {} bila tidak (2026-11-02, K23)."""
    from routes.rahaza_payroll_tax import normalize_bpjs_programs
    try:
        progs = normalize_bpjs_programs(body.get("bpjs_programs"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"bpjs_programs": progs} if progs is not None else {}


@router.put("/employees/{eid}")
async def update_employee(eid: str, request: Request):
    user = await _require_admin(request)
    db = get_db()
    body = await request.json()
    body.pop("_id", None)
    body.pop("id", None)
    body.pop("created_at", None)
    body["updated_at"] = _now()
    if "employee_code" in body:
        body["employee_code"] = body["employee_code"].strip().upper()
    # 2026-11-06 (Tahap 2): gaji hanya di Profil Gaji — field gaji lama di Data Karyawan tidak ditulis lagi.
    body.pop("base_rate", None)
    body.pop("wage_scheme", None)
    for _k in ("join_date", "resign_date"):
        if _k in body:
            body[_k] = (body[_k] or "")[:10] or None
    if "bpjs_programs" in body:  # 2026-11-02 (K23): simpan hanya bentuk bersih {kes, jht, jp, jkk_jkm}
        if body["bpjs_programs"] is None:
            body.pop("bpjs_programs")
        else:
            body.update(_bpjs_programs_field(body))
    if "shift_id" in body:   # 2026-11-07 (Tahap 5): shift dari master
        cur = await db.rahaza_employees.find_one({"id": eid}, {"_id": 0, "shift_id": 1}) or {}
        body.update(await _employee_shift_fields(db, body, cur))
    body.pop("location_name", None)   # nama turunan daftar, bukan data karyawan

    # Validate manager_id (Atasan) if being updated (Sprint 42)
    if "manager_id" in body:
        new_manager_id = body.get("manager_id")
        if new_manager_id:
            if new_manager_id == eid:
                raise HTTPException(400, "Karyawan tidak boleh menjadi atasan dirinya sendiri.")
            mgr = await db.rahaza_employees.find_one(
                {"id": new_manager_id, "active": True}, {"_id": 0, "id": 1, "name": 1}
            )
            if not mgr:
                raise HTTPException(400, "Atasan (manager) yang dipilih tidak ditemukan atau tidak aktif.")
            body["manager_name"] = mgr.get("name")
        else:
            # Clearing manager assignment
            body["manager_id"] = None
            body["manager_name"] = None
    
    res = await db.rahaza_employees.update_one({"id": eid}, {"$set": body})
    if res.matched_count == 0:
        raise HTTPException(404, "Not found")
    await log_activity(user["id"], user.get("name", ""), "update", "rahaza.employee", eid)
    return serialize_doc(await db.rahaza_employees.find_one({"id": eid}, {"_id": 0}))


@router.delete("/employees/{eid}")
async def deactivate_employee(eid: str, request: Request, hard: bool = False):
    """Tanpa `hard`: nonaktifkan (perilaku lama). `?hard=true`: hapus permanen HANYA bila karyawan belum punya
    riwayat apa pun (absensi, gaji, kasbon, klaim, cuti, lembur, jadwal, produksi, akun login, dokumen, bawahan…) —
    untuk data yang salah input. Selain itu 409 dan layar menawarkan Nonaktifkan. Ikut terhapus: konfigurasi
    miliknya sendiri yang belum pernah dipakai (profil gaji, penugasan shift, saldo cuti yang belum terpakai)."""
    user = await _require_admin(request)
    db = get_db()
    if hard:
        from core.hapus_master import tolak_bila_dipakai
        _wajib_pengelola(user, "karyawan")
        emp = await db.rahaza_employees.find_one({"id": eid}, {"_id": 0})
        if not emp:
            raise HTTPException(404, "Karyawan tidak ditemukan.")
        tolak_bila_dipakai("Karyawan", emp.get("name") or emp.get("employee_code") or "", await pemakaian_karyawan(db, emp))
        anak = {
            "profil_gaji": (await db.rahaza_payroll_profiles.delete_many({"employee_id": eid})).deleted_count,
            "penugasan_shift": (await db.hr_shift_assignments.delete_many({"employee_id": eid})).deleted_count,
            "saldo_cuti": (await db.rahaza_leave_balances.delete_many({"employee_id": eid})).deleted_count,
        }
        await db.rahaza_employees.delete_one({"id": eid})
        await log_activity(user["id"], user.get("name", ""), "delete", "rahaza.employee",
                           f"{emp.get('employee_code')} {emp.get('name')} " + ", ".join(f"{k}={v}" for k, v in anak.items()))
        return {"status": "deleted", "deleted": True}
    await db.rahaza_employees.update_one({"id": eid}, {"$set": {"active": False, "updated_at": _now()}})
    await log_activity(user["id"], user.get("name", ""), "deactivate", "rahaza.employee", eid)
    return {"status": "deactivated"}


# ── Employee Documents (reuses /api/upload + attachments collection) ──────────

@router.get("/employees/{eid}/documents")
async def list_employee_documents(eid: str, request: Request):
    """List all attachments belonging to this employee (photo + documents)."""
    await require_auth(request)
    db = get_db()
    docs = await db.attachments.find(
        {"entity_type": "employee", "entity_id": eid, "is_deleted": {"$ne": True}},
        {"_id": 0}
    ).sort("created_at", -1).to_list(500)
    return {"ok": True, "documents": [serialize_doc(d) for d in docs]}


@router.post("/employees/{eid}/photo")
async def set_employee_photo(eid: str, request: Request):
    """Set photo_url on an employee record. Body: { photo_url: str }"""
    user = await _require_admin(request)
    db = get_db()
    body = await request.json()
    url = (body.get("photo_url") or "").strip()
    res = await db.rahaza_employees.update_one(
        {"id": eid}, {"$set": {"photo_url": url, "updated_at": _now()}}
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Employee not found")
    await log_activity(user["id"], user.get("name", ""), "update-photo", "rahaza.employee", eid)
    return {"ok": True, "photo_url": url}



# ── User ↔ Employee Link ──────────────────────────────────────────────────────

@router.post("/employees/{eid}/link-user")
async def link_user_to_employee(eid: str, request: Request):
    """
    Tautkan akun login (users collection) ke record karyawan (rahaza_employees).
    Body: { user_id: str }  — ID dari koleksi users (auth).
    Berguna agar Portal Saya bisa resolve employee dari JWT user.
    """
    admin = await _require_admin(request)
    db    = get_db()
    body  = await request.json()
    user_id = (body.get("user_id") or "").strip()

    emp = await db.rahaza_employees.find_one({"id": eid}, {"_id": 0})
    if not emp:
        raise HTTPException(404, "Employee tidak ditemukan.")

    if user_id:
        # Validasi user ada
        u = await db.users.find_one({"id": user_id}, {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1})
        if not u:
            raise HTTPException(404, "User tidak ditemukan.")
        # Cek apakah user sudah di-link ke employee lain
        conflict = await db.rahaza_employees.find_one(
            {"user_id": user_id, "id": {"$ne": eid}, "active": True}, {"_id": 0, "employee_code": 1}
        )
        if conflict:
            raise HTTPException(409,
                f"User sudah terhubung ke karyawan {conflict.get('employee_code')}.")
        update_data = {
            "user_id":       user_id,
            "user_email":    u.get("email", ""),
            "user_name":     u.get("name", ""),
            "updated_at":    _now(),
        }
    else:
        # Unlink
        update_data = {"user_id": None, "user_email": None, "user_name": None, "updated_at": _now()}

    await db.rahaza_employees.update_one({"id": eid}, {"$set": update_data})
    # Sync ke users.employee_id untuk backward-compat
    if user_id:
        await db.users.update_one({"id": user_id}, {"$set": {"employee_id": eid}})
    await log_activity(admin["id"], admin.get("name", ""), "link-user", "rahaza.employee",
                       f"{eid} → user:{user_id or 'unlinked'}")
    updated = await db.rahaza_employees.find_one({"id": eid}, {"_id": 0})
    return serialize_doc({"message": "Link berhasil", "employee": updated})


@router.post("/employees/auto-link-users")
async def auto_link_users_by_email(request: Request):
    """
    Auto-link semua karyawan aktif ke akun users berdasarkan kecocokan email.
    Aman dijalankan berulang kali (idempotent).
    """
    admin = await _require_admin(request)
    db    = get_db()

    employees = await db.rahaza_employees.find(
        {"active": True}, {"_id": 0, "id": 1, "name": 1, "email": 1, "user_id": 1}
    ).to_list(500)

    users = await db.users.find(
        {}, {"_id": 0, "id": 1, "name": 1, "email": 1}
    ).to_list(500)
    user_by_email = {u["email"].lower(): u for u in users if u.get("email")}

    linked = 0
    skipped = 0
    already = 0
    details = []

    for emp in employees:
        if emp.get("user_id"):
            already += 1
            continue
        email = (emp.get("email") or "").lower()
        if not email or email not in user_by_email:
            skipped += 1
            continue
        u = user_by_email[email]
        # Check no conflict
        conflict = await db.rahaza_employees.find_one(
            {"user_id": u["id"], "id": {"$ne": emp["id"]}, "active": True}, {"_id": 0, "id": 1}
        )
        if conflict:
            skipped += 1
            continue
        await db.rahaza_employees.update_one(
            {"id": emp["id"]},
            {"$set": {
                "user_id":    u["id"],
                "user_email": u["email"],
                "user_name":  u.get("name", ""),
                "updated_at": _now(),
            }}
        )
        # Juga update users.employee_id untuk backward-compat dengan rahaza_self.py
        await db.users.update_one(
            {"id": u["id"]},
            {"$set": {"employee_id": emp["id"]}}
        )
        linked += 1
        details.append({"employee": emp["name"], "email": email, "user_id": u["id"]})

    await log_activity(admin["id"], admin.get("name",""), "auto-link-users",
                       "rahaza.employees", f"linked={linked}")
    return {
        "message": f"{linked} karyawan berhasil ditautkan ke akun login.",
        "linked":  linked,
        "already_linked": already,
        "skipped": skipped,
        "details": details,
    }
# ─── (DIHAPUS FASE 14) FUNGSI YATIM `resolve_employee_by_user` ──────────────
# Fungsi itu ditulis persis seperti endpoint (param `user_id` + `Request`,
# memanggil `require_auth`, docstring "Dipakai oleh Portal Saya") TETAPI
# DEKORATORNYA HILANG — sama seperti `rahaza_production.update_assignment`.
# FastAPI tidak pernah mendaftarkannya, jadi selama ini ia kode mati murni.
#
# Tidak dipulihkan (beda dengan update_assignment yang path-nya jelas dari
# saudara create/delete-nya) karena fungsinya SUDAH digantikan superset yang
# HIDUP: `routes/rahaza_self.py::_get_employee_for_user()` memakai 3 jalur
# resolusi (rahaza_employees.user_id → users.employee_id → email) sedangkan
# yatim ini hanya 2, dan superset itu dipakai endpoint `/api/rahaza/self/*`.
# Menebak-nebak path baru untuk fungsi yang tak punya pemanggil = menambah
# permukaan serang tanpa manfaat.
#
# Dijaga oleh CHECK D `ORPHAN_HANDLER` di scripts/preflight/verify_fe_be_contract.py.

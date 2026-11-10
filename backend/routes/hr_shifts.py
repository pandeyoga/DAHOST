"""
HR Shift Management Routes — Task 1.2
CV. Dewi Aditya

Prefix: /api/hr/shifts

Endpoints:
  GET  /                           list semua shift templates
  POST /                           buat shift template baru
  GET  /{id}                       detail shift
  PUT  /{id}                       update shift
  DELETE /{id}                     hapus (soft delete) shift
  POST /seed-defaults               seed default shifts

  GET  /assignments                 list semua assignments
  POST /assignments                 assign shift ke employee
  PUT  /assignments/{id}            update assignment
  DELETE /assignments/{id}          batalkan assignment
  GET  /assignments/employee/{emp_id}  assignments untuk employee tertentu

  GET  /employee/{emp_id}/active    shift aktif untuk employee (termasuk fallback)
  GET  /employee/{emp_id}/on-date   shift employee pada tanggal tertentu
  POST /calculate-hours             hitung jam kerja berdasarkan shift

  GET  /summary                     ringkasan assignments per shift
"""
from fastapi import APIRouter, Request, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
from database import get_db
from auth import require_auth, log_activity, check_role
from services.hr_shift_service import (
    create_shift,
    assign_shift,
    get_employee_shift,
    calculate_shift_hours,
    seed_default_shifts,
    DEFAULT_SHIFT,
    _to_hr_shape,
    _active_shift_query,
)
import logging
from core.authz import only  # T-01 2.3
from core.roles import HR_ROLES  # T-01 2.3
from utils.waktu import wib_date_str

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/hr/shifts", tags=["hr-shifts"])

# 2026-11-08 (Asisten AI Tahap B — celah izin): PENUGASAN shift ke karyawan (di sini dan di Penjadwal Shift
# `routes/dewi_shift_scheduler.py`) dulu cukup login — staf mana pun bisa memindah shift karyawan lain, dan
# jadwal itu dibaca aturan absen (`core.attendance_rules`). Kini sama dengan penghapusan penugasan yang
# sudah ada (`only(*HR_ROLES)`): HR + manajemen (+ superadmin/admin), ditambah akun yang diberi izin modul
# "Shift & Penjadwalan" (`hr.attendance.manage`, lihat `data/module_catalog.py`) atau `hr.manage`.
# Master shift (buat/ubah jam shift) TIDAK diubah: keputusan "semua staf internal boleh CRUD master".
SHIFT_WRITER_ROLES = ["admin", *HR_ROLES]
MSG_SHIFT_WRITER = "Hanya HR dan manajemen yang boleh mengatur penugasan atau jadwal shift karyawan."


def _require_shift_writer(user: dict) -> None:
    if check_role(user, SHIFT_WRITER_ROLES, "hr.attendance.manage") or "hr.manage" in (user.get("_permissions") or []):
        return
    raise HTTPException(403, MSG_SHIFT_WRITER)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_id(v: str):
    try:
        return int(v)
    except (ValueError, TypeError):
        return v


def _ok(data=None, message="", **kwargs):
    r = {"status": "ok"}
    if message:
        r["message"] = message
    if data is not None:
        r["data"] = data
    r.update(kwargs)
    return r


# ─── Pydantic ─────────────────────────────────────────────────────────────────

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class ShiftCreateModel(BaseModel):
    shift_code: str
    shift_name: str
    start_time: str              # HH:MM
    end_time: str                # HH:MM
    break_duration_minutes: int = 60
    # 2026-11-06 (pola P5): bawaan 6 hari kerja (keputusan owner, `core.workdays`), dulu Senin–Jumat
    days_active: List[str] = Field(default_factory=lambda: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"])
    is_overnight: bool = False
    is_default: bool = False
    color: str = "#64748b"
    description: str = ""
    # Tahap C (audit HR 9 Nov 2026, keputusan Q4/Q5): toleransi terlambat per shift (kosong = setelan umum) dan
    # jam mulai istirahat (acuan cuti setengah hari pagi).
    toleransi_menit: Optional[int] = None
    istirahat_mulai: Optional[str] = None


class ShiftUpdateModel(BaseModel):
    shift_name: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    break_duration_minutes: Optional[int] = None
    days_active: Optional[List[str]] = None
    is_overnight: Optional[bool] = None
    is_default: Optional[bool] = None
    color: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    toleransi_menit: Optional[int] = None     # kirim null = kembali ke setelan umum
    istirahat_mulai: Optional[str] = None     # kirim "" / null = hapus


class AssignShiftModel(BaseModel):
    employee_id: str
    shift_id: str
    effective_from: str          # YYYY-MM-DD
    effective_until: Optional[str] = None
    department: str = ""
    notes: str = ""


class AssignMassalModel(BaseModel):
    """Penugasan massal (Tahap C): pilihan baris (`employee_ids`) ATAU semua karyawan aktif satu departemen/lokasi."""
    employee_ids: Optional[List[str]] = None
    department: Optional[str] = None
    location_id: Optional[str] = None
    shift_id: str
    effective_from: str
    effective_until: Optional[str] = None
    notes: str = ""


class CalcHoursModel(BaseModel):
    clock_in: str
    clock_out: str
    shift_id: str


# ─── Shift templates ────────────────────────────────────────────────────────────

@router.get("")
async def list_shifts(
    request: Request,
    status: Optional[str] = "active",
    include_default: bool = True,
):
    await require_auth(request)
    db = get_db()
    # BACKLOG-B: kanonik = rahaza_shifts (hr_shifts lama terisolasi, di-retire)
    q = _active_shift_query(status)
    items_raw = await db.rahaza_shifts.find(q, {"_id": 0}).to_list(200)
    items = sorted((_to_hr_shape(i) for i in items_raw), key=lambda x: x.get("shift_code", ""))
    if include_default:
        items = [DEFAULT_SHIFT] + items
    return _ok(items, total=len(items))


@router.post("")
async def create_shift_endpoint(request: Request, body: ShiftCreateModel):
    user = await require_auth(request)
    db = get_db()
    try:
        doc = await create_shift(db, body.dict())
    except ValueError as e:
        raise HTTPException(400, str(e))
    await log_activity(
        str(user.get("id") or user.get("_id") or ""),
        user.get("full_name") or user.get("email") or "",
        "create_shift",
        "hr_shifts",
        body.shift_name,
    )
    return _ok(doc, message=f"Shift {body.shift_name} berhasil dibuat.")


@router.get("/summary")
async def shift_summary(request: Request):
    await require_auth(request)
    db = get_db()
    total_shifts = await db.rahaza_shifts.count_documents(_active_shift_query("active"))
    total_assigned = await db.hr_shift_assignments.count_documents({"status": "active"})
    by_shift = await db.hr_shift_assignments.aggregate([
        {"$match": {"status": "active"}},
        {"$group": {"_id": "$shift_name", "count": {"$sum": 1}, "color": {"$first": "$shift_color"}}},
        {"$sort": {"count": -1}},
    ]).to_list(50)
    return _ok({
        "total_shifts": total_shifts,
        "total_assigned_employees": total_assigned,
        "unassigned_uses_default": True,
        "by_shift": [{"shift_name": b["_id"], "count": b["count"], "color": b.get("color","#64748b")} for b in by_shift],
    })


@router.post("/seed-defaults")
async def seed_defaults(request: Request):
    user = await require_auth(request)
    if (user.get("role") or "").lower() not in ("superadmin", "admin", "owner"):
        raise HTTPException(403, "Admin only.")
    db = get_db()
    # BACKLOG-B: TIDAK ADA delete_many — rahaza_shifts kanonik dipakai attendance/APS;
    # seed idempotent by code (skip yang sudah ada).
    await seed_default_shifts(db)
    total = await db.rahaza_shifts.count_documents({})
    return _ok(message=f"Seed selesai (idempotent). Total shift sekarang: {total}.")


# ─── Assignments — HARUS sebelum /{shift_id} ──────────────────────────────────

@router.get("/assignments")
async def list_assignments(
    request: Request,
    status: Optional[str] = "active",
    department: Optional[str] = None,
    shift_id: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    skip: int = Query(0, ge=0),
):
    _require_view_all(await require_auth(request))
    db = get_db()
    q = {}
    if status:
        q["status"] = status
    if department:
        q["department"] = department
    if shift_id:
        q["shift_id"] = _coerce_id(shift_id)
    total = await db.hr_shift_assignments.count_documents(q)
    items = await db.hr_shift_assignments.find(q, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    return _ok(items, total=total, skip=skip, limit=limit)


@router.post("/assignments")
async def create_assignment(request: Request, body: AssignShiftModel):
    user = await require_auth(request)
    _require_shift_writer(user)
    db = get_db()
    assigned_by = user.get("full_name") or user.get("email") or ""
    try:
        doc = await assign_shift(
            db,
            employee_id=body.employee_id,
            shift_id=body.shift_id,
            effective_from=body.effective_from,
            effective_until=body.effective_until,
            assigned_by=assigned_by,
            department=body.department,
            notes=body.notes,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    await log_activity(
        str(user.get("id") or user.get("_id") or ""),
        user.get("full_name") or user.get("email") or "",
        "assign_shift",
        "hr_shift_assignments",
        f"emp={body.employee_id} shift={body.shift_id}",
    )
    return _ok(doc, message="Shift berhasil di-assign ke karyawan.")


MAKS_MASSAL = 500


@router.post("/assignments/massal")
async def create_assignment_massal(request: Request, body: AssignMassalModel):
    """Penugasan MASSAL (Tahap C audit HR): satu shift untuk banyak karyawan sekaligus — pilihan baris di layar
    Penugasan shift, atau semua karyawan aktif satu departemen/lokasi. Tiap karyawan memakai aturan penugasan
    tunggal yang sama (`assign_shift`: hanya bagian penugasan lama yang beririsan yang ditutup). Dulu 25 karyawan
    = 25 kali membuka formulir."""
    user = await require_auth(request)
    _require_shift_writer(user)
    db = get_db()
    from core.shift_roster import karyawan_lingkup
    if body.employee_ids is None and not (body.department or body.location_id):
        raise HTTPException(400, "Pilih karyawan, departemen, atau lokasi yang akan ditugaskan.")
    emps = await karyawan_lingkup(db, departemen=body.department or None, lokasi=body.location_id or None,
                                  employee_ids=body.employee_ids, batas=MAKS_MASSAL + 1)
    if not emps:
        raise HTTPException(400, "Tidak ada karyawan aktif yang cocok dengan pilihan ini.")
    if len(emps) > MAKS_MASSAL:
        raise HTTPException(400, f"Paling banyak {MAKS_MASSAL} karyawan sekali tugaskan. Persempit pilihan.")
    assigned_by = user.get("full_name") or user.get("name") or user.get("email") or ""
    berhasil, gagal = [], []
    for e in emps:
        try:
            doc = await assign_shift(db, employee_id=e["id"], shift_id=body.shift_id,
                                     effective_from=body.effective_from, effective_until=body.effective_until,
                                     assigned_by=assigned_by, notes=body.notes)
            berhasil.append(doc["id"])
        except ValueError as ex:
            if not berhasil and "Shift" in str(ex) and "tidak ditemukan" in str(ex):
                raise HTTPException(400, str(ex))
            gagal.append({"employee_id": e["id"], "karyawan": e.get("name") or e.get("employee_code"), "pesan": str(ex)})
    await log_activity(str(user.get("id") or ""), assigned_by, "assign_shift_massal", "hr_shift_assignments",
                       f"shift={body.shift_id} karyawan={len(berhasil)} gagal={len(gagal)}")
    pesan = f"Shift ditugaskan ke {len(berhasil)} karyawan." + (f" {len(gagal)} gagal." if gagal else "")
    return _ok({"berhasil": len(berhasil), "gagal": gagal}, message=pesan)


def _require_view_all(user: dict) -> None:
    """Audit HR P1 (9 Nov 2026): penugasan & jadwal berisi nama + shift seluruh karyawan → hanya HR/atasan/
    pemegang Portal SDM (pola `can_view_all_employees` yang sama dengan absensi). Master shift tetap terbuka."""
    from utils.employee_identity import can_view_all_employees
    if not can_view_all_employees(user):
        raise HTTPException(403, "Hanya HR dan atasan yang boleh melihat penugasan shift karyawan lain.")


@router.get("/penugasan-karyawan")
async def penugasan_per_karyawan(
    request: Request,
    tanggal: Optional[str] = None,
    department: Optional[str] = None,
    location_id: Optional[str] = None,
    q: Optional[str] = None,
):
    """Layar Penugasan shift (Tahap C): SEMUA karyawan aktif + shift yang berlaku pada `tanggal` (bawaan hari ini)
    dan asalnya (jadwal terbit / penugasan / shift utama / belum ada) — dasar pilihan baris penugasan massal."""
    user = await require_auth(request)
    _require_view_all(user)
    db = get_db()
    from core.shift_roster import GalatRoster, karyawan_lingkup, muat_shift, penugasan_aktif, sel_berlaku, tgl
    try:
        hari = tgl(tanggal).isoformat() if tanggal else wib_date_str()
    except GalatRoster as e:
        raise HTTPException(e.status, e.pesan)
    emps = await karyawan_lingkup(db, departemen=department or None, lokasi=location_id or None, cari=q)
    shifts = await muat_shift(db)
    sel = await sel_berlaku(db, emps, [hari], shifts)
    tugas = await penugasan_aktif(db, [e["id"] for e in emps], hari, "9999-12-31")
    lok = {}
    async for r in db.rahaza_locations.find({}, {"_id": 0, "id": 1, "name": 1}):
        lok[r.get("id")] = r.get("name")
    rows = []
    for e in emps:
        c = (sel.get(e["id"]) or {}).get(hari) or {}
        s = shifts.get(str(c.get("shift_id"))) if c.get("shift_id") else None
        semua = tugas.get(e["id"]) or []
        kini = next((a for a in semua if str(a.get("effective_from") or "") <= hari), None)
        nanti = sorted((a for a in semua if str(a.get("effective_from") or "") > hari),
                       key=lambda a: str(a.get("effective_from")))
        rows.append({
            "employee_id": e["id"], "employee_code": e.get("employee_code") or "", "name": e.get("name") or "",
            "department": e.get("department") or "", "location_id": e.get("location_id"),
            "location_name": lok.get(e.get("location_id")) or "",
            "shift": ({"id": s["id"], "kode": s["kode"], "nama": s["nama"], "mulai": s["mulai"], "selesai": s["selesai"],
                       "warna": s["warna"]} if s else None),
            "sumber": c.get("sumber"),
            "penugasan": ({"id": kini.get("id"), "effective_from": kini.get("effective_from"),
                           "effective_until": kini.get("effective_until") or None} if kini else None),
            "berikutnya": [{"id": a.get("id"), "shift_code": a.get("shift_code"), "effective_from": a.get("effective_from"),
                            "effective_until": a.get("effective_until") or None} for a in nanti[:3]],
        })
    return _ok(rows, total=len(rows), tanggal=hari)


@router.get("/assignments/employee/{employee_id}")
async def get_employee_assignments(request: Request, employee_id: str):
    user = await require_auth(request)
    _require_view_all(user)
    db = get_db()
    items = await db.hr_shift_assignments.find(
        {"employee_id": employee_id},
        {"_id": 0}
    ).sort("created_at", -1).to_list(50)
    return _ok(items, total=len(items))


@router.delete("/assignments/{assignment_id}", dependencies=only(*HR_ROLES, perm=("hr.attendance.manage", "hr.manage")))  # T-01 2.3
async def cancel_assignment(request: Request, assignment_id: str):
    await require_auth(request)
    db = get_db()
    await db.hr_shift_assignments.update_one(
        {"id": _coerce_id(assignment_id)},
        {"$set": {"status": "cancelled", "updated_at": _now()}},
    )
    return _ok(message="Assignment dibatalkan.")


# ─── Employee shift lookup — HARUS sebelum /{shift_id} ───────────────────────

@router.get("/employee/{employee_id}/active")
async def employee_active_shift(request: Request, employee_id: str):
    await require_auth(request)
    db = get_db()
    today = wib_date_str()
    shift = await get_employee_shift(db, employee_id, today)
    return _ok(shift)


@router.get("/employee/{employee_id}/on-date")
async def employee_shift_on_date(
    request: Request,
    employee_id: str,
    date: str = Query(..., description="YYYY-MM-DD"),
):
    await require_auth(request)
    db = get_db()
    shift = await get_employee_shift(db, employee_id, date)
    return _ok(shift)


@router.post("/calculate-hours")
async def calculate_hours(request: Request, body: CalcHoursModel):
    await require_auth(request)
    db = get_db()
    if body.shift_id == "default":
        from services.hr_shift_service import DEFAULT_SHIFT as DS
        shift = DS
    else:
        shift = await db.rahaza_shifts.find_one({"id": _coerce_id(body.shift_id)}, {"_id": 0})
        if not shift:
            raise HTTPException(404, "Shift tidak ditemukan.")
        shift = _to_hr_shape(shift)
    result = calculate_shift_hours(body.clock_in, body.clock_out, shift)
    return _ok(result)


# ─── Shift CRUD by ID — setelah semua static routes ──────────────────────────

@router.get("/{shift_id}")
async def get_shift(request: Request, shift_id: str):
    await require_auth(request)
    if shift_id == "default":
        return _ok(DEFAULT_SHIFT)
    db = get_db()
    doc = await db.rahaza_shifts.find_one({"id": _coerce_id(shift_id)}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Shift tidak ditemukan.")
    return _ok(_to_hr_shape(doc))


@router.put("/{shift_id}")
async def update_shift(request: Request, shift_id: str, body: ShiftUpdateModel):
    await require_auth(request)
    db = get_db()
    doc = await db.rahaza_shifts.find_one({"id": _coerce_id(shift_id)})
    if not doc:
        raise HTTPException(404, "Shift tidak ditemukan.")
    update = {k: v for k, v in body.dict(exclude_none=True).items()
              if k not in ("toleransi_menit", "istirahat_mulai")}
    # Tahap C: toleransi & jam istirahat — null yang DIKIRIM berarti "hapus / ikut setelan umum".
    from services.hr_shift_service import field_toleransi_istirahat
    try:
        tambahan = field_toleransi_istirahat(body.dict(), isian_ada=body.model_fields_set)
    except ValueError as e:
        raise HTTPException(400, str(e))
    update.update(tambahan["set"])
    st = update.get("start_time") or doc.get("start_time")
    et = update.get("end_time") or doc.get("end_time")
    # 2026-11-09: istirahat 0 menit sah (dulu `or` membuat 0 kembali ke nilai lama)
    brk = update["break_duration_minutes"] if "break_duration_minutes" in update else doc.get("break_duration_minutes", 60)
    ov = update.get("is_overnight") if "is_overnight" in update else doc.get("is_overnight", False)
    from services.hr_shift_service import _calc_effective_hours
    update["effective_hours"] = _calc_effective_hours(st, et, brk, ov)
    # BACKLOG-B: mirror ke field kanonik agar attendance/APS tetap konsisten
    if "shift_name" in update:
        update["name"] = update["shift_name"]
    if "start_time" in update:
        update["check_in_time"] = update["start_time"]
    if "end_time" in update:
        update["check_out_time"] = update["end_time"]
    update["working_hours"] = update["effective_hours"]
    if update.get("status"):
        update["active"] = update["status"] == "active"
    update["updated_at"] = _now()
    ops = {"$set": update}
    if tambahan["unset"]:
        ops["$unset"] = {k: "" for k in tambahan["unset"]}
    await db.rahaza_shifts.update_one({"id": _coerce_id(shift_id)}, ops)
    return _ok(message="Shift disimpan.")


@router.delete("/{shift_id}")
async def delete_shift(request: Request, shift_id: str, hard: bool = False):
    """Tanpa `hard`: nonaktifkan (perilaku lama). `?hard=true` (10 Nov 2026, owner "master data bisa dihapus"):
    hapus permanen bila shift belum dipakai (hitungan SATU dengan `routes.rahaza_master.pemakaian_shift` — master
    shift yang sama); selain itu 409 dan layar menawarkan Nonaktifkan. Gerbang peran sama dengan menonaktifkan."""
    user = await require_auth(request)
    if (user.get("role") or "").lower() not in ("superadmin", "admin", "owner"):
        raise HTTPException(403, "Hanya admin dan owner yang boleh menonaktifkan atau menghapus shift.")
    db = get_db()
    if hard:
        from core.hapus_master import tolak_bila_dipakai
        from routes.rahaza_master import pemakaian_shift
        sid = _coerce_id(shift_id)
        doc = await db.rahaza_shifts.find_one({"id": sid}, {"_id": 0})
        if not doc:
            raise HTTPException(404, "Shift tidak ditemukan.")
        nama = doc.get("shift_name") or doc.get("name") or doc.get("shift_code") or doc.get("code") or ""
        tolak_bila_dipakai("Shift", nama, await pemakaian_shift(db, sid))
        await db.rahaza_shifts.delete_one({"id": sid})
        await log_activity(user.get("id") or "", user.get("name") or "", "delete_shift", "hr_shifts", nama)
        return _ok(message=f"Shift {nama} dihapus.", deleted=True)
    await db.rahaza_shifts.update_one(
        {"id": _coerce_id(shift_id)},
        {"$set": {"status": "inactive", "active": False, "updated_at": _now()}},
    )
    return _ok(message="Shift dinonaktifkan.")

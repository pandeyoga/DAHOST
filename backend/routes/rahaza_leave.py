"""
PT Rahaza — Sprint 2.3: Leave Management (Izin/Cuti)
Fase 2 — Enhanced per UU No. 13 Tahun 2003

Collections:
  - rahaza_leave_types:    Master tipe cuti (request_type: cuti|sakit|izin, requires_document)
  - rahaza_leave_requests: Request cuti/izin/sakit karyawan
  - rahaza_leave_balances: Saldo cuti per karyawan per tahun

New fields in leave_request:
  - request_type: "cuti" | "sakit" | "izin"
  - attachment_url: URL bukti dokumen (wajib untuk leave_type.requires_document)
  - attachment_filename: nama file asli
  - is_half_day: bool
  - half_day_period: "AM" | "PM"
  - duration_working_days: hari kerja (tanpa Sabtu/Minggu)

New endpoints:
  - POST /leaves/upload-document  → upload bukti
  - POST /leaves/{id}/cancel      → batalkan cuti approved (kembalikan saldo)
"""
# ruff: noqa: E741
from fastapi import APIRouter, Request, HTTPException, UploadFile, File
from database import get_db
from auth import require_auth, serialize_doc, log_activity
from core.roles import HR_ROLES  # T-01 2.3
import uuid
import re
import logging
from datetime import datetime, timezone, date
from typing import Optional
from utils.waktu import wib_year

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/rahaza", tags=["rahaza-leave"])


from object_storage import put_object as _put_object
ALLOWED_MIMES = {"image/jpeg", "image/png", "image/webp", "image/jpg",
                 "application/pdf", "image/heic"}
MAX_FILE_BYTES = 8 * 1024 * 1024  # 8 MB


def _uid(): return str(uuid.uuid4())
def _now(): return datetime.now(timezone.utc)


async def _count_working_days_db(db, d_from: date, d_to: date) -> dict:
    """Hari kerja dalam rentang — Tahap 2 (2026-11-06): memakai SATU aturan hari kerja `core.workdays`
    (kerja 6 hari/minggu bawaan, libur Kalender Produksi). Dulu Senin–Jumat tetap di sini, sedangkan saldo
    cuti dipotong hari KALENDER.
    Returns dict: { working_days, calendar_days, weekend_days, holiday_days, holidays: [list] }"""
    from core.leave_engine import leave_period_info
    info = await leave_period_info(db, d_from.isoformat(), d_to.isoformat())
    return {k: info[k] for k in ("working_days", "calendar_days", "weekend_days", "holiday_days", "holidays")}


def _safe_ext(filename: str) -> str:
    if not filename or '.' not in filename:
        return 'jpg'
    ext = filename.rsplit('.', 1)[-1].lower()
    ext = re.sub(r'[^a-z0-9]', '', ext)
    return ext if ext in {'jpg', 'jpeg', 'png', 'webp', 'pdf', 'heic'} else 'jpg'


LEAVE_STATUSES = ["draft", "pending_approval", "pending_hr_approval", "approved", "rejected", "cancelled"]
PENDING_LEAVE_STATUSES = ("pending_approval", "pending_hr_approval")


# ── BUG-4 (2026-07-26): "dibayar / tidak" punya DUA nama field di koleksi yang
# SAMA (`unpaid` dari seeder, `paid` dari form HR). Semua pembaca di berkas ini
# WAJIB lewat SSOT `utils/leave_types` supaya "Cuti Tahunan" tidak lagi
# dilaporkan sebagai cuti tidak berbayar.
def _lt_is_paid(lt) -> bool:
    from utils.leave_types import is_paid
    return is_paid(lt)


def _lt_is_unpaid(lt) -> bool:
    from utils.leave_types import is_unpaid
    return is_unpaid(lt)


async def _require_hr_admin(request: Request):
    """Require HR, admin, or owner."""
    user = await require_auth(request)
    role = (user.get("role") or "").lower()
    if role in ("superadmin", "admin", "owner", "hr"):
        return user
    perms = user.get("_permissions") or []
    if "*" in perms or "hr.manage" in perms:
        return user
    raise HTTPException(403, "Forbidden: butuh akses HR/Admin.")


async def _require_leave_approver(request: Request):
    """Penyetuju cuti tahap HR (layar Cuti & Lembur SDM, persetujuan massal). 2026-11-09 (Q6): tahap ATASAN
    diputus atasan langsung dari Portal Saya › Persetujuan tim (`/api/portal/team-approvals`); tingkat yang boleh
    diputus diperiksa per pengajuan oleh `core.leave_engine.leave_decision_stage`."""
    from core.leave_engine import is_leave_hr_approver
    user = await require_auth(request)
    if is_leave_hr_approver(user):
        return user
    raise HTTPException(403, "Hanya HR yang boleh memutus cuti di layar ini. Atasan langsung memutus lewat "
                             "Portal Saya › Cuti & Lembur › Persetujuan tim.")


async def _require_leave_decider(db, leave_id: str, user: dict, action: str) -> str:
    """Gerbang endpoint setuju/tolak cuti (Q6): pengajuan ada + `user` berhak memutus tingkat yang sedang ditunggu
    (atasan langsung atau HR — `core.leave_engine.leave_decision_stage`). Mesin cuti memeriksa ulang saat menulis."""
    leave = await db.rahaza_leave_requests.find_one({"id": leave_id}, {"_id": 0})
    if not leave:
        raise HTTPException(404, "Pengajuan cuti tidak ditemukan.")
    from core.leave_engine import leave_decision_stage
    return await leave_decision_stage(db, leave, user, action)


async def _ensure_own_or_hr(db, user: dict, employee_id: str, message: str):
    """Pemohon sendiri atau HR/admin (T-01 2.3) — endpoint swalayan Portal Saya dilewati gerbang modul,
    jadi kepemilikan WAJIB dijaga di sini."""
    role = (user.get("role") or "").lower()
    perms = user.get("_permissions") or []
    if role in HR_ROLES + ("admin", "superadmin") or "*" in perms or "hr.manage" in perms:
        return
    from utils.employee_identity import resolve_my_employee
    my_emp = await resolve_my_employee(db, user)
    if not my_emp or my_emp.get("id") != employee_id:
        raise HTTPException(403, message)


async def _ensure_can_view(db, user: dict, employee_id: str):
    """Baca data cuti: milik sendiri, atau HR/atasan (2026-11-07, Tahap 7 — dulu cukup login)."""
    from utils.employee_identity import can_view_all_employees, resolve_my_employee
    if can_view_all_employees(user):
        return
    mine = await resolve_my_employee(db, user)
    if not mine or mine.get("id") != employee_id:
        raise HTTPException(403, "Anda hanya bisa melihat data cuti milik sendiri.")


# ── LEAVE TYPES (Master) ───────────────────────────────────────────────────────

@router.get("/leave-types")
async def list_leave_types(request: Request):
    await require_auth(request)
    db = get_db()
    rows = await db.rahaza_leave_types.find({}, {"_id": 0}).sort("code", 1).to_list(500)
    # SSOT bentuk (BUG-4): `paid`/`unpaid` selalu sinkron, field wajib tak pernah hilang
    from utils.leave_types import public_leave_type
    return serialize_doc([public_leave_type(r) for r in rows])


@router.post("/leave-types")
async def create_leave_type(request: Request):
    """Buat jenis/alasan cuti baru.

    BUG-4 (2026-07-26): endpoint ini dulu HANYA menyimpan `code`, `name`, `paid`,
    `quota_default`, `description` — padahal form HR mengirim `request_type`,
    `requires_document`, `max_days_without_doc`, `doc_note`. Semua itu dibuang
    diam-diam, jadi jenis cuti buatan HR tidak pernah bisa mewajibkan dokumen dan
    selalu dianggap 'cuti'. Sekarang seluruh dokumen dibentuk SSOT
    `utils/leave_types.build_leave_type_doc`.
    """
    user = await _require_hr_admin(request)
    db = get_db()
    body = await request.json()

    from utils.leave_types import build_leave_type_doc, public_leave_type
    doc = build_leave_type_doc(body)

    if await db.rahaza_leave_types.find_one({"code": doc["code"], "active": True}):
        raise HTTPException(409, f"Kode '{doc['code']}' sudah terpakai.")
    from core.reference_dedup import assert_unique_ref  # 2026-11-06 (pola P8)
    await assert_unique_ref(db, "rahaza_leave_types", name=doc.get("name"), label="Jenis cuti")

    doc.update({"id": _uid(), "created_at": _now()})
    await db.rahaza_leave_types.insert_one(dict(doc))
    await log_activity(user["id"], user.get("name", ""), "create", "rahaza.leave_type", doc["code"])
    return serialize_doc(public_leave_type(doc))


@router.put("/leave-types/{lt_id}")
async def update_leave_type(lt_id: str, request: Request):
    """Ubah jenis cuti.

    BUG-4: dulu `$set` seluruh body MENTAH — bisa menulis field sembarang,
    menduplikasi `code`, atau mematikan `active` tanpa validasi.
    """
    user = await _require_hr_admin(request)
    db = get_db()
    body = await request.json()

    existing = await db.rahaza_leave_types.find_one({"id": lt_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Leave type tidak ditemukan.")

    from utils.leave_types import build_leave_type_doc, public_leave_type
    doc = build_leave_type_doc(body, existing)

    if doc["code"] != existing.get("code"):
        dup = await db.rahaza_leave_types.find_one(
            {"code": doc["code"], "active": True, "id": {"$ne": lt_id}})
        if dup:
            raise HTTPException(409, f"Kode '{doc['code']}' sudah terpakai.")
    if doc.get("name") != existing.get("name"):
        from core.reference_dedup import assert_unique_ref  # 2026-11-06 (pola P8)
        await assert_unique_ref(db, "rahaza_leave_types", name=doc.get("name"), label="Jenis cuti",
                                exclude_id=lt_id)

    await db.rahaza_leave_types.update_one({"id": lt_id}, {"$set": doc})
    await log_activity(user["id"], user.get("name", ""), "update", "rahaza.leave_type", lt_id)
    fresh = await db.rahaza_leave_types.find_one({"id": lt_id}, {"_id": 0})
    return serialize_doc(public_leave_type(fresh))


@router.delete("/leave-types/{lt_id}")
async def deactivate_leave_type(lt_id: str, request: Request, hard: bool = False):
    """Nonaktifkan jenis cuti (tidak dihapus — riwayat pengajuan harus tetap terbaca).

    `?hard=true` (10 Nov 2026, owner "master data bisa dihapus"): hapus permanen bila BELUM ada pengajuan cuti
    (status apa pun) dan saldo cuti jenis ini belum terpakai; saldo kosong (dibuat otomatis saat saldo dilihat) ikut
    terhapus. Selain itu 409 dan layar menawarkan Nonaktifkan."""
    user = await _require_hr_admin(request)
    db = get_db()
    lt = await db.rahaza_leave_types.find_one({"id": lt_id}, {"_id": 0})
    if not lt:
        raise HTTPException(404, "Jenis cuti tidak ditemukan.")
    if hard:
        from core.hapus_master import hitung_pemakaian, tolak_bila_dipakai
        tolak_bila_dipakai("Jenis cuti", lt.get("name") or lt.get("code") or "", await hitung_pemakaian(db, [
            ("pengajuan cuti", "rahaza_leave_requests", {"leave_type_id": lt_id}),
            ("saldo cuti terpakai", "rahaza_leave_balances", {"leave_type_id": lt_id, "used": {"$gt": 0}}),
        ]))
        saldo = await db.rahaza_leave_balances.delete_many({"leave_type_id": lt_id})
        await db.rahaza_leave_types.delete_one({"id": lt_id})
        await log_activity(user["id"], user.get("name", ""), "delete", "rahaza.leave_type",
                           f"{lt.get('code')} saldo_kosong={saldo.deleted_count}")
        return {"status": "deleted", "deleted": True, "ok": True}
    # 2026-11-06 (pola P4): status menunggu = core.leave_engine.PENDING_STATUSES (termasuk
    # `pending_hr_approval` tahap HR — dulu terlewat sehingga jenis cuti bisa dimatikan di tengah alur)
    from core.leave_engine import PENDING_STATUSES
    pending = await db.rahaza_leave_requests.count_documents(
        {"leave_type_id": lt_id, "status": {"$in": ["draft", *PENDING_STATUSES]}})
    if pending:
        raise HTTPException(
            409, f"Masih ada {pending} pengajuan berstatus menunggu memakai jenis ini. "
                 "Proses dulu pengajuannya sebelum menonaktifkan.")
    await db.rahaza_leave_types.update_one({"id": lt_id}, {"$set": {"active": False, "updated_at": _now()}})
    return {"status": "deactivated", "ok": True}


# ── WORKING DAYS PREVIEW ──────────────────────────────────────────────────────

@router.get("/leaves/working-days")
async def working_days_preview(
    request: Request,
    from_date: str,
    to_date: str,
):
    """
    Preview hari kerja antara dua tanggal.
    Exclude Sabtu/Minggu + libur nasional dari production_calendar.
    Dipakai frontend untuk live-update saat user pilih tanggal.
    """
    await require_auth(request)
    db = get_db()
    try:
        d_from = date.fromisoformat(from_date)
        d_to   = date.fromisoformat(to_date)
        if d_to < d_from:
            raise HTTPException(400, "to_date harus >= from_date")
    except ValueError:
        raise HTTPException(400, "Format tanggal tidak valid (YYYY-MM-DD)")

    info = await _count_working_days_db(db, d_from, d_to)
    return {
        "from_date":      from_date,
        "to_date":        to_date,
        "calendar_days":  info["calendar_days"],
        "working_days":   info["working_days"],
        "weekend_days":   info["weekend_days"],
        "holiday_days":   info["holiday_days"],
        "holidays":       info["holidays"],
        "summary": (
            f"{info['working_days']} hari kerja"
            + (f" (dari {info['calendar_days']} hari kalender"
               + (f", {info['weekend_days']} akhir pekan" if info['weekend_days'] else "")
               + (f", {info['holiday_days']} libur nasional" if info['holiday_days'] else "")
               + ")")
            if info['calendar_days'] != info['working_days'] else
            f"{info['working_days']} hari kerja"
        ),
    }


# ── DOCUMENT UPLOAD ────────────────────────────────────────────────────────────

@router.post("/leaves/upload-document")
async def upload_leave_document(
    request: Request,
    file: UploadFile = File(...),
):
    """Upload bukti dokumen untuk izin/cuti. Return URL yang disimpan di leave_request."""
    user = await require_auth(request)

    if file.content_type not in ALLOWED_MIMES:
        raise HTTPException(415, "Tipe file tidak didukung. Gunakan JPG, PNG, PDF, atau WEBP.")

    data = await file.read()
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, f"Ukuran file melebihi {MAX_FILE_BYTES // (1024*1024)}MB.")
    if len(data) < 100:
        raise HTTPException(400, "File terlalu kecil / tidak valid.")

    ext = _safe_ext(file.filename or "")
    fid = _uid()
    fname = f"{fid}.{ext}"
    try:
        url = _put_object(f"leave_docs/{fname}", data, file.content_type or "application/octet-stream")["url"]
    except Exception as e:
        raise HTTPException(503, f"Penyimpanan berkas tidak tersedia: {e}")
    log.info(f"[leave_doc] uploaded {fname} by {user.get('id')}")
    return {
        "url": url,
        "filename": file.filename or fname,
        "size": len(data),
        "content_type": file.content_type,
    }

@router.get("/leaves")
async def list_leaves(
    request: Request,
    status: Optional[str] = None,
    employee_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    skip: int = 0,
    limit: int = 30,
):
    user = await require_auth(request)
    db = get_db()
    # 2026-11-07 (Tahap 7): selain HR/atasan hanya pengajuan milik sendiri — dulu alasan & surat sakit semua
    # karyawan terbaca akun staf mana pun.
    from utils.employee_identity import can_view_all_employees, resolve_my_employee
    if not can_view_all_employees(user):
        mine = await resolve_my_employee(db, user)
        if not mine or (employee_id and employee_id != mine["id"]):
            return {"total": 0, "skip": skip, "limit": limit, "has_more": False, "items": []}
        employee_id = mine["id"]
    q = {}
    if status:
        if status not in LEAVE_STATUSES:
            raise HTTPException(400, f"Status harus: {LEAVE_STATUSES}")
        q["status"] = status
    if employee_id:
        q["employee_id"] = employee_id
    if date_from:
        q["from_date"] = q.get("from_date", {})
        q["from_date"]["$gte"] = date_from
    if date_to:
        q["to_date"] = q.get("to_date", {})
        q["to_date"]["$lte"] = date_to

    total = await db.rahaza_leave_requests.count_documents(q)
    rows = await db.rahaza_leave_requests.find(q, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(500)

    # Enrich with employee & leave type names
    emp_ids = list({r["employee_id"] for r in rows if r.get("employee_id")})
    lt_ids = list({r["leave_type_id"] for r in rows if r.get("leave_type_id")})
    
    emps = await db.rahaza_employees.find({"id": {"$in": emp_ids}}, {"_id": 0}).to_list(500) if emp_ids else []
    lts = await db.rahaza_leave_types.find({"id": {"$in": lt_ids}}, {"_id": 0}).to_list(500) if lt_ids else []
    
    emp_map = {e["id"]: e for e in emps}
    lt_map = {l["id"]: l for l in lts}
    
    for r in rows:
        e = emp_map.get(r.get("employee_id")) or {}
        lt = lt_map.get(r.get("leave_type_id")) or {}
        r["employee_code"]  = e.get("employee_code")
        r["employee_name"]  = e.get("name")
        r["employee_dept"]  = e.get("department")
        r["manager_id"]     = e.get("manager_id")
        r["manager_name"]   = None
        r["leave_type_code"] = lt.get("code")
        r["leave_type_name"] = lt.get("name")
        r["leave_type_request_type"] = lt.get("request_type")
        r["is_paid"]        = _lt_is_paid(lt)   # BUG-4: dulu membaca field `paid` mentah

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "has_more": (skip + limit) < total,
        "items": serialize_doc(rows),
    }


# ── LEAVE BALANCE ──────────────────────────────────────────────────────────────

@router.get("/leaves/balance")
async def get_leave_balance(request: Request, employee_id: str, year: Optional[int] = None):
    """Get leave balance for employee (per year, per leave type)."""
    user = await require_auth(request)
    db = get_db()
    await _ensure_can_view(db, user, employee_id)

    if not year:
        year = wib_year()
    
    # Get all leave types
    leave_types = await db.rahaza_leave_types.find({"active": True}, {"_id": 0}).to_list(500)
    
    # Get approved leaves for this employee/year
    leaves = await db.rahaza_leave_requests.find({
        "employee_id": employee_id,
        "status": "approved",
        "from_date": {"$regex": f"^{year}"},
    }, {"_id": 0}).to_list(500)
    
    # Calculate used per leave type
    used_map = {}
    for lv in leaves:
        lt_id = lv.get("leave_type_id")
        if lt_id:
            used_map[lt_id] = used_map.get(lt_id, 0) + lv.get("duration_days", 0)
    
    # Build balance report
    balances = []
    for lt in leave_types:
        quota = lt.get("quota_default", 12)
        used = used_map.get(lt["id"], 0)
        remaining = max(0, quota - used)
        
        balances.append({
            "leave_type_id": lt["id"],
            "leave_type_code": lt["code"],
            "leave_type_name": lt["name"],
            "quota": quota,
            "used": used,
            "remaining": remaining,
            "is_paid": _lt_is_paid(lt),   # BUG-4: dokumen seeder hanya punya `unpaid`
        })
    
    return {
        "employee_id": employee_id,
        "year": year,
        "balances": balances,
    }


@router.get("/leaves/{leave_id}")
async def get_leave(leave_id: str, request: Request):
    user = await require_auth(request)
    db = get_db()
    leave = await db.rahaza_leave_requests.find_one({"id": leave_id}, {"_id": 0})
    if not leave:
        raise HTTPException(404, "Leave request tidak ditemukan.")
    await _ensure_can_view(db, user, leave.get("employee_id"))

    # Enrich
    if leave.get("employee_id"):
        emp = await db.rahaza_employees.find_one({"id": leave["employee_id"]}, {"_id": 0})
        leave["employee_code"] = emp.get("employee_code") if emp else None
        leave["employee_name"] = emp.get("name") if emp else None
    if leave.get("leave_type_id"):
        lt = await db.rahaza_leave_types.find_one({"id": leave["leave_type_id"]}, {"_id": 0})
        leave["leave_type_code"] = lt.get("code") if lt else None
        leave["leave_type_name"] = lt.get("name") if lt else None
        leave["is_paid"] = _lt_is_paid(lt) if lt else False
    
    return serialize_doc(leave)


@router.post("/leaves/request")
async def request_leave(request: Request):
    """Create leave/permit request (langsung pending_approval)."""
    user = await require_auth(request)
    db = get_db()
    body = await request.json()
    return await create_leave_request(db, user, body)


async def create_leave_request(db, user: dict, body: dict) -> dict:
    """SATU jalur pengajuan cuti/izin/sakit (dipakai juga Portal Saya `/api/portal/leave`, Tahap 2)."""
    employee_id    = body.get("employee_id")
    leave_type_id  = body.get("leave_type_id")
    from_date      = body.get("from_date")
    to_date        = body.get("to_date") or from_date
    reason         = (body.get("reason") or "").strip()
    attachment_url  = body.get("attachment_url") or ""
    attachment_filename = body.get("attachment_filename") or ""
    is_half_day    = bool(body.get("is_half_day", False) or body.get("half_day", False))
    half_day_period= body.get("half_day_period") or "AM"  # AM | PM
    request_type   = (body.get("leave_kind") or body.get("request_type") or "").strip().lower()
    if not employee_id:
        # 2026-11-07 (Tahap 7): tanpa employee_id = untuk diri sendiri (SSOT identitas, bukan isian klien).
        from utils.employee_identity import require_my_employee
        employee_id = (await require_my_employee(db, user))["id"]

    if not (employee_id and leave_type_id and from_date and to_date):
        raise HTTPException(400, "employee_id, leave_type_id, from_date, to_date wajib diisi.")
    # Tahap 2 (2026-11-06, keputusan owner): setiap cuti/izin/sakit WAJIB beralasan.
    if not reason:
        raise HTTPException(400, "Alasan wajib diisi.")
    await _ensure_own_or_hr(db, user, employee_id,
                            "Cuti/izin hanya bisa diajukan untuk diri sendiri; atas nama karyawan lain hanya oleh HR.")

    # Validate employee & leave type
    emp = await db.rahaza_employees.find_one({"id": employee_id})
    if not emp:
        raise HTTPException(404, "Employee tidak ditemukan.")

    lt = await db.rahaza_leave_types.find_one({"id": leave_type_id, "active": True})
    if not lt:
        raise HTTPException(404, "Leave type tidak ditemukan atau tidak aktif.")

    # Tahap 2 (2026-11-06): durasi = HARI KERJA (core.workdays), setengah hari = 0,5 dan hanya satu tanggal.
    from core.leave_engine import LEAVE_KINDS, leave_period_info
    if is_half_day and to_date != from_date:
        raise HTTPException(400, "Setengah hari hanya untuk satu tanggal (tanggal mulai = tanggal selesai).")
    wd_info = await leave_period_info(db, from_date, to_date, is_half_day)
    duration_working = wd_info["working_days"]
    holidays_in_period = wd_info["holidays"]
    if not wd_info["days"]:
        raise HTTPException(400, "Tanggal yang dipilih bukan hari kerja (Minggu atau libur). Pilih hari kerja.")
    duration = duration_working
    from core.attendance_rules import attendance_lock, lock_message
    for _d in wd_info["days"]:
        _lock = await attendance_lock(db, employee_id, _d)
        if _lock:
            raise HTTPException(409, lock_message(_d, _lock))

    # Guard (NEW-BUG-5): tolak pengajuan cuti yang TUMPANG-TINDIH dgn pengajuan aktif employee yang sama.
    # Overlap: existing.from_date <= to_date AND existing.to_date >= from_date.
    overlap = await db.rahaza_leave_requests.find_one({
        "employee_id": employee_id,
        "status": {"$nin": ["cancelled", "rejected"]},
        "from_date": {"$lte": to_date},
        "to_date": {"$gte": from_date},
    })
    if overlap:
        raise HTTPException(
            400,
            f"Pengajuan cuti tumpang-tindih dengan pengajuan aktif "
            f"({overlap.get('from_date')} s/d {overlap.get('to_date')}, status {overlap.get('status')}).",
        )

    # Validate document requirement
    requires_doc      = bool(lt.get("requires_document", False))
    max_days_no_doc   = int(lt.get("max_days_without_doc", 0))
    if requires_doc:
        # Sakit: boleh sampai max_days_without_doc tanpa dokumen
        if max_days_no_doc > 0 and duration <= max_days_no_doc:
            pass  # OK without document
        elif not attachment_url:
            doc_note = lt.get("doc_note") or "Lampirkan bukti/dokumen pendukung."
            raise HTTPException(400, f"Dokumen wajib dilampirkan untuk '{lt.get('name')}'. {doc_note}")

    # Jenis pengajuan (cuti | izin | sakit): dari jenis cutinya bila tidak dikirim.
    if request_type not in LEAVE_KINDS:
        request_type = (lt.get("request_type") or "cuti").lower()
        if request_type not in LEAVE_KINDS:
            request_type = "cuti"

    # 2026-11-09 (Q6, keputusan owner): tingkat 1 = ATASAN LANGSUNG karyawan (manager_id → akun tertaut), lalu HR;
    # atasan kosong / tanpa akun → langsung HR. Dulu: > 7 hari kerja = 2 tingkat, siapa pun penyetujunya.
    from core.approval_route import manager_route
    route = await manager_route(db, emp)
    approval_level_required = route["levels"]

    doc = {
        "id":                 _uid(),
        "employee_id":        employee_id,
        "leave_type_id":      leave_type_id,
        "request_type":       request_type,
        "leave_kind":         request_type,
        "from_date":          from_date,
        "to_date":            to_date,
        "duration_days":      duration,
        "duration_working_days": duration_working,
        "calendar_days":      wd_info["calendar_days"],
        "holidays_in_period": holidays_in_period,
        "is_half_day":        is_half_day,
        "half_day_period":    half_day_period if is_half_day else None,
        "reason":             reason,
        "attachment_url":     attachment_url,
        "attachment_filename": attachment_filename,
        "status":             "pending_approval",
        "approval_level_required": approval_level_required,
        "current_approval_level":  1,
        "approval_route":     {k: route.get(k) for k in ("level_1", "manager_employee_id", "manager_name")},
        "approval_step_1":    None,  # filled when supervisor approves
        "approval_step_2":    None,  # filled when HR approves (if needed)
        "submitted_at":       _now(),
        "submitted_by":       user["id"],
        "created_by":         user["id"],
        "created_by_name":    user.get("name", ""),
        "created_at":         _now(),
        "updated_at":         _now(),
    }
    await db.rahaza_leave_requests.insert_one(doc)
    await log_activity(user["id"], user.get("name", ""), "request", "rahaza.leave",
                       f"{emp.get('name', employee_id)} - {request_type} {duration} hari")

    # 2026-11-09 (Q6): mesin "Persetujuan Bertingkat" (approval_chain_service) TIDAK lagi diberi pengajuan cuti —
    # dulu menyetujui di sana tidak mengubah status cuti (mesin kedua yang tidak tersambung).

    # ── Notifikasi: atasan langsung (tahap 1) atau HR (bila langsung HR) ─────────
    try:
        from routes.rahaza_notifications import publish_notification
        # H6/P4 (bug pasti): dulu `manager_id` = ID KARYAWAN dikirim sebagai penerima (butuh ID AKUN) → atasan
        # tidak pernah menerima kabar. Sekarang akun atasan dari `employee_user_ids` (rute di atas).
        notify_ids = [u for u in route.get("manager_user_ids") or [] if u != user.get("id")]
        if not notify_ids:
            hr_users = await db.users.find(
                {"role": {"$in": ["hr", "superadmin", "admin", "owner"]}},
                {"_id": 0, "id": 1}
            ).to_list(10)
            notify_ids = [u2["id"] for u2 in hr_users if u2.get("id") and u2["id"] != user.get("id")]

        if notify_ids:
            level_label = (" — menunggu persetujuan Anda sebagai atasan, lalu HR" if route["levels"] == 2
                           else "")
            await publish_notification(
                db,
                type_="leave_request_submitted",
                severity="info",
                title=f"Pengajuan cuti: {emp.get('name','')} — {lt.get('name','')}",
                message=(
                    f"{emp.get('name','')} mengajukan {lt.get('name','')} "
                    f"selama {duration} hari "
                    f"({doc['from_date']} s/d {doc['to_date']}){level_label}."
                ),
                link_module="portal-cuti" if route["levels"] == 2 else "hr-leave",
                link_id=doc["id"],
                target_user_ids=notify_ids,
                dedup_key=f"leave_submitted_{doc['id']}",
            )
    except Exception as ne:
        log.warning(f"[leave] notif failed: {ne}")

    return serialize_doc(doc)


@router.get("/leaves/{leave_id}/approval-preview")
async def leave_approval_preview(leave_id: str, request: Request):
    """Isi dialog persetujuan (Tahap 2, 2026-11-06): alasan, lampiran, hari kerja yang akan ditulis,
    saldo, dan usulan dibayar/tidak. HR memilih keputusan pembayaran sendiri."""
    user = await require_auth(request)
    db = get_db()
    leave = await db.rahaza_leave_requests.find_one({"id": leave_id}, {"_id": 0})
    if not leave:
        raise HTTPException(404, "Leave request tidak ditemukan.")
    from core.leave_engine import leave_decision_stage
    stage = await leave_decision_stage(db, leave, user, "approve")   # Q6: atasan / HR
    from core.leave_engine import is_half_day, leave_kind, leave_period_info, suggest_pay_decision
    from routes.rahaza_leave_balances import balance_snapshot
    lt = await db.rahaza_leave_types.find_one({"id": leave.get("leave_type_id")}, {"_id": 0})
    info = await leave_period_info(db, leave["from_date"], leave["to_date"], is_half_day(leave))
    emp = await db.rahaza_employees.find_one({"id": leave.get("employee_id")}, {"_id": 0, "name": 1,
                                                                                 "employee_code": 1})
    year = date.fromisoformat(str(leave["from_date"])[:10]).year
    bal = await balance_snapshot(db, leave["employee_id"], leave["leave_type_id"], year, lt=lt)
    # Tahap 7: cuti lintas tahun memakai saldo masing-masing tahun → tampilkan per tahun.
    from core.leave_engine import days_per_year
    balance_by_year = []
    for y, need in days_per_year(info["days"], is_half_day(leave)).items():
        b = bal if y == year else await balance_snapshot(db, leave["employee_id"], leave["leave_type_id"], y, lt=lt)
        balance_by_year.append({"year": y, "days": need, "remaining": b["remaining"], "allocated": b["allocated"]})
    level_required = int(leave.get("approval_level_required") or 1)
    current = int(leave.get("current_approval_level") or 1)
    return serialize_doc({
        "leave": leave, "employee": emp or {}, "leave_type_name": (lt or {}).get("name"),
        "leave_kind": leave_kind(leave, lt), "half_day": is_half_day(leave),
        "reason": leave.get("reason") or "", "attachment_url": leave.get("attachment_url") or "",
        "attachment_filename": leave.get("attachment_filename") or "",
        "days": info["days"], "working_days": info["working_days"], "calendar_days": info["calendar_days"],
        "balance": bal, "balance_by_year": balance_by_year, "type_unpaid": _lt_is_unpaid(lt),
        "suggestion": suggest_pay_decision(leave, lt),
        "final_step": not (level_required > 1 and current == 1),
        "stage": stage, "approval_route": leave.get("approval_route") or {},
    })


@router.post("/leaves/{leave_id}/approve")
async def approve_leave(leave_id: str, request: Request):
    """Setujui pengajuan cuti/izin/sakit — lewat SATU mesin `core.leave_engine` (Tahap 2, 2026-11-06).

    Body (opsional): {pay_decision: 'paid'|'unpaid', notes}. Persetujuan akhir memeriksa & memotong saldo dalam
    hari kerja, menulis absensi per hari kerja (status = jenis pengajuan), dan menyimpan keputusan bayar HR.
    2026-11-09 (Q6): siapa yang boleh memutus tingkat ini diperiksa mesin cuti (atasan langsung → HR)."""
    user = await require_auth(request)
    db = get_db()
    await _require_leave_decider(db, leave_id, user, "approve")
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — tombol lama mengirim tanpa body
        body = {}
    from core.leave_engine import approve_leave_request
    res = await approve_leave_request(db, leave_id, user, pay_decision=(body or {}).get("pay_decision"),
                                      notes=(body or {}).get("notes") or "", via="utama")
    await log_activity(user["id"], user.get("name", ""), "approve" if res["final"] else "approve_step1",
                       "rahaza.leave", leave_id)
    return serialize_doc(res["leave"])


# ── 2026-11-02 — KABAR KEPUTUSAN CUTI KE PEMOHON ────────────────────────────
# Audit runtime 2026-11-02: cuti DITOLAK tidak mengabari pemohon sama sekali,
# begitu pula persetujuan massal (bulk). Hanya persetujuan satu-per-satu yang
# mengirim `leave_approved`. Helper ini satu pintu untuk kabar keputusan; juga
# boleh dipanggil jalur lain yang memutus cuti (mis. routes/hr_approval_inbox.py).
async def leave_requester_user_ids(db, leave: dict) -> list:
    """User pemohon: akun yang tertaut ke karyawan cuti (dua arah tautan, Tahap 7); cadangan = pengaju."""
    from utils.employee_identity import employee_user_ids
    ids = await employee_user_ids(db, leave.get("employee_id"))
    if not ids:
        fallback = leave.get("submitted_by") or leave.get("created_by")
        if fallback:
            ids = [fallback]
    return ids


async def notify_leave_decision(db, leave: dict, *, approved: bool, reason: str = "",
                                saldo_txt: str = "") -> Optional[dict]:
    """Kabari pemohon bahwa cutinya disetujui/ditolak (tautan: Portal Saya › Cuti)."""
    try:
        from routes.rahaza_notifications import publish_notification
        uids = await leave_requester_user_ids(db, leave)
        if not uids:
            return None
        lt = await db.rahaza_leave_types.find_one({"id": leave.get("leave_type_id")}, {"_id": 0, "name": 1})
        lt_name = (lt or {}).get("name", "Cuti")
        periode = (f"({leave.get('from_date')} s/d {leave.get('to_date')}, "
                   f"{leave.get('duration_days')} hari)")
        if approved:
            title = f"Cuti Disetujui — {lt_name}"
            msg = f"Pengajuan {lt_name} Anda {periode} telah DISETUJUI.{saldo_txt}"
        else:
            title = f"Cuti Ditolak — {lt_name}"
            msg = f"Pengajuan {lt_name} Anda {periode} DITOLAK. Alasan: {reason or '-'}."
        return await publish_notification(
            db,
            type_="leave_approved" if approved else "leave_rejected",
            severity="success" if approved else "warning",
            title=title, message=msg,
            link_module="portal-cuti", link_id=leave.get("id"),
            target_user_ids=uids,
            dedup_key=f"leave_{'approved' if approved else 'rejected'}_{leave.get('id')}",
            dedup_minutes=1440,
        )
    except Exception as ne:  # noqa: BLE001 — kabar tidak boleh menggagalkan keputusan
        log.warning(f"[leave] notif keputusan ke pemohon gagal: {ne}")
        return None


@router.post("/leaves/{leave_id}/reject")
async def reject_leave(leave_id: str, request: Request):
    """Tolak pengajuan — lewat mesin yang sama dengan Kotak Masuk SDM (Tahap 2). Q6: atasan (tingkat 1) atau HR."""
    user = await require_auth(request)
    db = get_db()
    await _require_leave_decider(db, leave_id, user, "reject")
    body = await request.json()
    reason = (body.get("reason") or "").strip() or "Tidak ada alasan"
    from core.leave_engine import reject_leave_request
    out = await reject_leave_request(db, leave_id, user, reason, via="utama")
    await log_activity(user["id"], user.get("name", ""), f"reject:{reason}", "rahaza.leave", leave_id)
    return serialize_doc(out)


@router.post("/leaves/bulk-approve")
async def bulk_approve_leaves(request: Request):
    """Setujui banyak pengajuan sekaligus — tiap pengajuan lewat `approve_leave_request` yang sama
    (saldo hari kerja, absensi per hari kerja, tingkat 2, kunci payroll). Tahap 2 (2026-11-06): dulu jalur ini
    melewati pemeriksaan saldo dan menulis "cuti" di setiap hari kalender. Keputusan bayar = usulan sistem.

    2026-11-08 (keputusan pemilik): `leave_ids` WAJIB — hanya pengajuan yang tampil di layar (sesuai penyaring)
    yang disetujui. Dulu body kosong menyetujui SEMUA pengajuan menunggu di server (≤ 500)."""
    user = await _require_leave_approver(request)
    db = get_db()
    body = await request.json()
    raw_ids = body.get("leave_ids") if isinstance(body, dict) else None
    if not isinstance(raw_ids, list):
        raise HTTPException(400, "Pilih pengajuan yang akan disetujui (daftar pengajuan kosong).")
    leave_ids = list(dict.fromkeys(str(i).strip() for i in raw_ids if isinstance(i, str) and i.strip()))
    if not leave_ids:
        raise HTTPException(400, "Pilih pengajuan yang akan disetujui (daftar pengajuan kosong).")
    if len(leave_ids) > 500:
        raise HTTPException(400, "Paling banyak 500 pengajuan sekali setuju.")

    query = {"status": {"$in": list(PENDING_LEAVE_STATUSES)}, "id": {"$in": leave_ids}}
    pending = await db.rahaza_leave_requests.find(query, {"_id": 0, "id": 1}).to_list(500)
    if not pending:
        return {"approved": 0, "skipped": 0, "message": "Tidak ada pengajuan menunggu yang bisa disetujui."}

    from core.leave_engine import approve_leave_request
    approved_count, forwarded, failed = 0, 0, []
    for lv in pending:
        try:
            res = await approve_leave_request(db, lv["id"], user, via="massal")
        except HTTPException as e:
            failed.append({"id": lv["id"], "reason": e.detail})
            continue
        if res["final"]:
            approved_count += 1
        else:
            forwarded += 1
        await log_activity(user["id"], user.get("name", ""), "bulk_approve", "rahaza.leave", lv["id"])

    msg = f"{approved_count} pengajuan disetujui."
    if forwarded:
        msg += f" {forwarded} diteruskan ke persetujuan HR."
    if failed:
        msg += f" {len(failed)} tidak bisa disetujui."
    return {"approved": approved_count, "forwarded": forwarded, "skipped": len(failed), "failed": failed,
            "message": msg}


@router.delete("/leaves/{leave_id}")
async def delete_leave(leave_id: str, request: Request):
    """Delete draft/rejected leave request — hanya pemohon sendiri atau HR/admin (T-01 2.3)."""
    user = await require_auth(request)
    db = get_db()

    leave = await db.rahaza_leave_requests.find_one({"id": leave_id}, {"_id": 0})
    if not leave:
        raise HTTPException(404, "Leave request tidak ditemukan.")
    await _ensure_own_or_hr(db, user, leave.get("employee_id"),
                            "Hanya pemohon cuti sendiri atau HR yang boleh menghapus pengajuan ini.")
    if leave.get("status") not in ("draft", "rejected"):
        raise HTTPException(400, "Hanya leave Draft/Rejected yang bisa dihapus.")

    await db.rahaza_leave_requests.delete_one({"id": leave_id})
    return {"status": "deleted"}


async def _cancel_pending_leave(db, leave: dict, user: dict, cancel_reason: str) -> dict:
    """Tarik pengajuan yang belum diputuskan: status 'cancelled', tanpa sentuh saldo/absensi."""
    leave_id = leave["id"]
    now = _now()
    res = await db.rahaza_leave_requests.update_one(
        {"id": leave_id, "status": {"$in": list(PENDING_LEAVE_STATUSES)}},
        {"$set": {"status": "cancelled", "cancelled_at": now, "cancelled_by": user["id"],
                  "cancelled_by_name": user.get("name", ""), "cancel_reason": cancel_reason,
                  "updated_at": now}})
    if not getattr(res, "matched_count", 1):
        # 2026-11-07 (Tahap 7): HR baru saja memutusnya (disetujui/ditolak) — jangan laporkan "dibatalkan".
        raise HTTPException(409, "Pengajuan ini baru saja diputuskan HR. Muat ulang halaman lalu periksa statusnya.")
    try:  # antrean persetujuan & "Perlu Tindakan" atasan/HR ikut ditutup
        await db.approval_requests.update_many(
            {"type": "leave", "ref_id": leave_id, "status": "pending"},
            {"$set": {"status": "cancelled", "updated_at": now.isoformat()}})
        from utils.notif_unified import resolve_for_source
        await resolve_for_source(db, "rahaza_leave_requests", leave_id)
    except Exception as e:  # noqa: BLE001 — pembatalan tetap sah walau antrean gagal dirapikan
        log.warning(f"[cancel_leave] antrean persetujuan {leave_id} gagal ditutup: {e}")
    await log_activity(user["id"], user.get("name", ""), "cancel", "rahaza.leave",
                       f"{leave_id} — {cancel_reason} (pengajuan ditarik)")
    out = await db.rahaza_leave_requests.find_one({"id": leave_id}, {"_id": 0})
    return serialize_doc(out)


@router.post("/leaves/{leave_id}/cancel")
async def cancel_leave(leave_id: str, request: Request):
    """
    Batalkan pengajuan cuti yang masih menunggu persetujuan, atau cuti yang sudah disetujui.
    Cuti disetujui: saldo dikembalikan dan absensi dikembalikan ke keadaan sebelum cuti (core.leave_engine).
    """
    user = await require_auth(request)
    db   = get_db()
    body = await request.json()
    cancel_reason = (body.get("reason") or "Dibatalkan oleh karyawan").strip()

    leave = await db.rahaza_leave_requests.find_one({"id": leave_id}, {"_id": 0})
    if not leave:
        raise HTTPException(404, "Leave request tidak ditemukan.")
    await _ensure_own_or_hr(db, user, leave.get("employee_id"),
                            "Hanya pemohon cuti sendiri atau HR yang boleh membatalkan cuti ini.")
    # Tahap 1 (2026-11-06): pengajuan yang MASIH MENUNGGU persetujuan juga boleh dibatalkan (tombol
    # Batalkan di Portal Saya). Dulu ditolak "Hanya leave Approved" sehingga karyawan tidak bisa menarik
    # pengajuannya. Pengajuan menunggu belum memakai saldo dan belum membuat absensi cuti.
    if leave.get("status") in PENDING_LEAVE_STATUSES:
        return await _cancel_pending_leave(db, leave, user, cancel_reason)
    if leave.get("status") != "approved":
        raise HTTPException(400, "Hanya cuti yang menunggu persetujuan atau sudah disetujui yang bisa dibatalkan.")

    # Tahap 2 (2026-11-06): saldo dikembalikan sebanyak yang dipotong (hari kerja) dan absensi dikembalikan
    # ke keadaan SEBELUM cuti — dulu record absensinya dihapus, termasuk jam masuk/pulang yang ada.
    # Karyawan hanya sebelum cuti dimulai; HR juga sesudahnya selama hari itu belum masuk gaji final.
    from core.leave_engine import cancel_approved_leave
    from utils.employee_identity import is_hr
    out = await cancel_approved_leave(db, leave, user, cancel_reason, is_hr=is_hr(user))
    await log_activity(user["id"], user.get("name", ""), "cancel", "rahaza.leave",
                       f"{leave_id} — {cancel_reason}")
    return serialize_doc(out)

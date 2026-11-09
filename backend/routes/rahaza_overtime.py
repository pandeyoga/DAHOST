"""
CV. Dewi Aditya / PT Rahaza — Overtime Request Workflow (Phase 9.1)

Self-service overtime request → supervisor approval → auto-included in payroll.

Collection:
  rahaza_overtime_requests
    - id, employee_id, date (YYYY-MM-DD), start_time, end_time, hours
    - reason, status (pending | approved | rejected | cancelled)
    - rate_multiplier — Tahap 2 (2026-11-06): dari Pengaturan Payroll (jam pertama), BUKAN isian karyawan
    - approved_by, approved_at, rejected_reason
"""
import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, Query
from database import get_db
from auth import require_auth, check_role

router = APIRouter(prefix="/api/rahaza/overtime", tags=["rahaza-overtime"])


def _uid(): return str(uuid.uuid4())
def _now(): return datetime.now(timezone.utc)
def _s(d):
    if not d:
        return None
    d = dict(d)
    d.pop("_id", None)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


# 2026-11-08: penyetuju lembur = kode peran lama ATAU izin `hr.approve` ("Setujui izin, cuti, lembur & klaim").
# Aturan yang sama dipakai daftar (melihat semua pengajuan) dan pembatalan pengajuan orang lain.
# Cermin layar: `frontend/src/components/erp/RahazaOvertimeModule.jsx` (isApprover).
OT_APPROVER_ROLES = ("superadmin", "admin", "owner", "hr", "manager")
OT_APPROVER_PERM = "hr.approve"


def is_ot_approver(user: dict) -> bool:
    return check_role(user, OT_APPROVER_ROLES, OT_APPROVER_PERM)


async def _require_approver(request: Request):
    user = await require_auth(request)
    if not is_ot_approver(user):
        raise HTTPException(403, "Hanya Supervisor/Manager/HR yang dapat approve lembur.")
    return user


def _calc_hours(start: str, end: str) -> float:
    """Compute hours between HH:MM strings, handling overnight."""
    try:
        h1, m1 = map(int, start.split(":"))
        h2, m2 = map(int, end.split(":"))
        s = h1 * 60 + m1
        e = h2 * 60 + m2
        if e < s:
            e += 24 * 60  # overnight
        return round((e - s) / 60, 2)
    except Exception:
        return 0


@router.get("")
async def list_overtime(
    request: Request,
    status: Optional[str] = None,
    employee_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
):
    user = await require_auth(request)
    db = get_db()
    filt = {}
    # Non-admin: only see own records
    if not is_ot_approver(user):
        # BUG-4: `user.get("employee_id")` dibaca MENTAH dari JWT (berlaku 24 jam),
        # jadi karyawan yang baru ditautkan HR melihat daftar KOSONG sampai login
        # ulang. Pakai SSOT identitas.
        from utils.employee_identity import resolve_my_employee
        _mine = await resolve_my_employee(db, user)
        if not _mine:
            return {"ok": True, "overtime": []}
        filt["employee_id"] = _mine["id"]
    elif employee_id:
        filt["employee_id"] = employee_id

    if status:
        filt["status"] = status
    if date_from or date_to:
        filt["date"] = {}
        if date_from:
            filt["date"]["$gte"] = date_from
        if date_to:
            filt["date"]["$lte"] = date_to

    docs = await db.rahaza_overtime_requests.find(filt, {"_id": 0}).sort([("date", -1), ("created_at", -1)]).to_list(limit)

    # Enrich employee info
    emp_ids = list({d["employee_id"] for d in docs if d.get("employee_id")})
    emps = await db.rahaza_employees.find({"id": {"$in": emp_ids}}, {"_id": 0, "id": 1, "name": 1, "employee_code": 1}).to_list(500) if emp_ids else []
    emp_map = {e["id"]: e for e in emps}

    result = []
    for d in docs:
        d2 = _s(d)
        d2["employee"] = emp_map.get(d2.get("employee_id"))
        result.append(d2)
    return {"ok": True, "overtime": result}


@router.get("/summary")
async def summary(
    request: Request,
    employee_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """Total approved overtime hours in period (used by payroll)."""
    user = await require_auth(request)
    db = get_db()
    # 2026-11-07 (Tahap 7): selain HR/atasan hanya lembur milik sendiri (sama dengan daftar lembur).
    from utils.employee_identity import can_view_all_employees, resolve_my_employee
    if not can_view_all_employees(user):
        mine = await resolve_my_employee(db, user)
        if not mine or (employee_id and employee_id != mine["id"]):
            return {"ok": True, "by_employee": {}, "total_records": 0}
        employee_id = mine["id"]
    filt = {"status": "approved"}
    if employee_id:
        filt["employee_id"] = employee_id
    if date_from or date_to:
        filt["date"] = {}
        if date_from:
            filt["date"]["$gte"] = date_from
        if date_to:
            filt["date"]["$lte"] = date_to

    docs = await db.rahaza_overtime_requests.find(filt, {"_id": 0}).to_list(500)
    by_employee = {}
    for d in docs:
        eid = d.get("employee_id")
        hrs = d.get("hours", 0)
        mult = d.get("rate_multiplier", 1.5)
        by_employee.setdefault(eid, {"total_hours": 0, "weighted_hours": 0, "entries": 0})
        by_employee[eid]["total_hours"] += hrs
        by_employee[eid]["weighted_hours"] += hrs * mult
        by_employee[eid]["entries"] += 1

    return {"ok": True, "by_employee": by_employee, "total_records": len(docs)}


MAX_OVERTIME_HOURS = 12


async def overtime_multiplier(db) -> float:
    """Pengali lembur dari Pengaturan Payroll (`rahaza_payroll_settings` key 'overtime', jam pertama).
    Tahap 2 (2026-11-06): dulu karyawan mengisi pengalinya sendiri di formulir pengajuan."""
    from routes.rahaza_payroll_settings import get_overtime_settings
    cfg = await get_overtime_settings(db)
    try:
        return float(cfg.get("first_hour_multiplier") or 1.5)
    except (TypeError, ValueError):
        return 1.5


@router.post("")
async def create_request(request: Request):
    """Employee submits overtime request."""
    user = await require_auth(request)
    db = get_db()
    body = await request.json()
    return await create_overtime_request(db, user, body)


async def create_overtime_request(db, user: dict, body: dict) -> dict:
    """SATU jalur pengajuan lembur (juga dipakai Portal Saya `/api/portal/overtime`).

    Tahap 2 (2026-11-06): karyawan mengisi TANGGAL, JUMLAH JAM, dan ALASAN saja. Jam mulai/selesai opsional
    (jam dihitung darinya bila jumlah jam kosong). Pengali TIDAK diterima dari formulir — diambil dari
    Pengaturan Payroll."""
    # Determine employee_id: from body (admin on behalf of) or user.employee_id (self)
    # BUG-4: identitas dari SSOT, bukan JWT mentah (lihat catatan di list_overtime).
    from utils.employee_identity import is_hr, resolve_my_employee
    _mine = await resolve_my_employee(db, user)
    employee_id = body.get("employee_id") or (_mine or {}).get("id")
    if not employee_id:
        raise HTTPException(
            404,
            "Akun Anda belum ditautkan ke data karyawan. Minta Admin HR menautkan "
            "lewat menu Data Karyawan → Tautkan Akun.")

    hr = is_hr(user)
    if not hr and employee_id != (_mine or {}).get("id"):
        raise HTTPException(403, "Tidak boleh submit lembur untuk karyawan lain.")

    date_str = str(body.get("date") or "").strip()[:10]
    if not date_str:
        raise HTTPException(400, "Tanggal lembur wajib diisi.")
    reason = (body.get("reason") or "").strip()
    if not reason and not hr:
        raise HTTPException(400, "Alasan lembur wajib diisi.")
    start_time = (body.get("start_time") or "").strip() or None
    end_time = (body.get("end_time") or "").strip() or None
    hours = body.get("hours")
    if hours in (None, ""):
        hours = _calc_hours(start_time or "17:00", end_time or "19:00") if (start_time or end_time) or hr else 0
    try:
        hours = round(float(hours), 2)
    except (TypeError, ValueError):
        raise HTTPException(400, "Jumlah jam lembur harus berupa angka.")
    if hours <= 0:
        raise HTTPException(400, "Jumlah jam lembur wajib diisi (lebih dari 0).")
    if hours > MAX_OVERTIME_HOURS:
        raise HTTPException(400, f"Jumlah jam lembur maksimal {MAX_OVERTIME_HOURS} jam per hari.")

    # 2026-11-09 (Q9): batas PP 35/2021 (lembur hari kerja 4 jam/hari, 18 jam/minggu) → PERINGATAN, tidak ditolak.
    limit_warnings = await overtime_limit_warnings_for(db, employee_id, date_str, hours)

    # Duplicate check: same employee + date + start_time
    existing = await db.rahaza_overtime_requests.find_one({
        "employee_id": employee_id, "date": date_str,
        "start_time": start_time,
        "status": {"$in": ["pending", "approved"]},
    })
    if existing:
        raise HTTPException(409, "Pengajuan lembur untuk tanggal (dan jam mulai) yang sama sudah ada.")

    # 2026-11-09 (Q6): tingkat 1 = atasan langsung (manager_id → akun tertaut), lalu HR; tanpa atasan → langsung HR.
    from core.approval_route import manager_route
    emp_doc = await db.rahaza_employees.find_one({"id": employee_id}, {"_id": 0}) or {"id": employee_id}
    route = await manager_route(db, emp_doc)
    doc = {
        "id": _uid(),
        "employee_id": employee_id,
        "date": date_str,
        "start_time": start_time,
        "end_time": end_time,
        "hours": hours,
        "approval_level_required": route["levels"],
        "current_approval_level": 1,
        "approval_route": {k: route.get(k) for k in ("level_1", "manager_employee_id", "manager_name")},
        "approval_step_1": None,
        "limit_warnings": limit_warnings,
        "rate_multiplier": await overtime_multiplier(db),
        "rate_multiplier_source": "pengaturan_payroll",
        "reason": reason,
        "status": "pending",
        "submitted_by": user["id"],
        "submitted_by_name": user.get("name", ""),
        "approved_by": None, "approved_at": None, "rejected_reason": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.rahaza_overtime_requests.insert_one(doc)
    if route["levels"] == 2:
        await notify_manager_overtime(db, doc, route, actor=user)   # Q6: atasan lebih dulu
    else:
        await notify_overtime_submitted(db, doc, actor=user)   # 2026-11-02 (K30)
    return {"ok": True, "overtime": _s(doc), "warnings": limit_warnings}


async def overtime_limit_warnings_for(db, employee_id: str, date_str: str, hours: float) -> list:
    """Peringatan batas lembur hari kerja untuk pengajuan baru (hari kerja saja; hari istirahat tidak dibatasi
    Pasal 26 PP 35/2021). Minggu = Senin–Minggu tanggal itu, menjumlahkan pengajuan menunggu & disetujui."""
    from datetime import date as _date, timedelta
    from core.workdays import get_work_calendar, holiday_set, is_working_day
    from routes.rahaza_payroll_rules import OT_MAX_HOURS_DAY, OT_MAX_HOURS_WEEK
    try:
        d = _date.fromisoformat(date_str)
    except ValueError:
        return []
    cal = await get_work_calendar(db)
    if not is_working_day(d, cal["off_weekdays"], await holiday_set(db, d, d)):
        return []
    out = []
    if hours > OT_MAX_HOURS_DAY:
        out.append(f"Lembur {hours:g} jam melebihi batas {OT_MAX_HOURS_DAY} jam per hari kerja (PP 35/2021).")
    mon = d - timedelta(days=d.weekday())
    sun = mon + timedelta(days=6)
    rows = await db.rahaza_overtime_requests.find(
        {"employee_id": employee_id, "status": {"$in": ["pending", "approved"]},
         "date": {"$gte": mon.isoformat(), "$lte": sun.isoformat()}}, {"_id": 0, "date": 1, "hours": 1}).to_list(50)
    hol = await holiday_set(db, mon, sun)
    week = sum(float(r.get("hours") or 0) for r in rows if is_working_day(r.get("date"), cal["off_weekdays"], hol))
    if week + hours > OT_MAX_HOURS_WEEK:
        out.append(f"Total lembur minggu ini {week + hours:g} jam melebihi batas {OT_MAX_HOURS_WEEK} jam per minggu "
                   "(PP 35/2021).")
    return out


async def notify_manager_overtime(db, ot: dict, route: dict, *, actor: dict | None = None):
    """Q6/H6 (9 Nov 2026): kabar ke AKUN atasan langsung (bukan id karyawan) — tautan Portal Saya › Cuti & Lembur."""
    try:
        from routes.rahaza_notifications import publish_notification
        emp = await db.rahaza_employees.find_one({"id": ot.get("employee_id")}, {"_id": 0, "name": 1}) or {}
        uids = [u for u in route.get("manager_user_ids") or [] if u != (actor or {}).get("id")]
        if not uids:
            return None
        return await publish_notification(
            db, type_="overtime_request_submitted", severity="info",
            title=f"Pengajuan lembur tim: {emp.get('name') or 'Karyawan'}",
            message=(f"{emp.get('name') or 'Karyawan'} mengajukan lembur {ot.get('date')} ({ot.get('hours')} jam) — "
                     "menunggu persetujuan Anda sebagai atasan, lalu HR."),
            link_module="portal-cuti", link_id=ot.get("id"), target_user_ids=uids,
            dedup_key=f"overtime_manager_{ot.get('id')}")
    except Exception as ne:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("[overtime] notif atasan gagal: %s", ne)
        return None


# ── 2026-11-02 (K30) — "PERLU TINDAKAN" UNTUK HR: PENGAJUAN LEMBUR ─────────────
# Dulu lembur masuk Perlu Tindakan hanya lewat hitungan dokumen (routes/approval_badge.py).
# Penerima = peran NYATA Portal SDM yang berwenang memutuskan (gerbang approve di berkas ini &
# kotak masuk HR); pengaju dan karyawan pemilik lembur TIDAK ikut menerima. Ditutup otomatis oleh
# resolver (`SOURCE_RULES['overtime']`) begitu status keluar dari 'pending'.
OVERTIME_DECIDER_ROLES = ("hr", "hr_manager")


async def _overtime_owner_user_ids(db, ot: dict) -> set:
    from utils.notif_recipients import active_user_filter
    ids = {ot.get("submitted_by")}
    if ot.get("employee_id"):
        rows = await db.users.find(active_user_filter({"employee_id": ot["employee_id"]}),
                                   {"_id": 0, "id": 1}).to_list(5)
        ids |= {r.get("id") for r in rows}
        emp = await db.rahaza_employees.find_one({"id": ot["employee_id"]}, {"_id": 0, "user_id": 1})
        ids.add((emp or {}).get("user_id"))
    return {i for i in ids if i}


async def notify_overtime_submitted(db, ot: dict, *, actor: dict | None = None):
    try:
        from utils.notif_unified import decider_roles, notif_insert
        emp = await db.rahaza_employees.find_one({"id": ot.get("employee_id")}, {"_id": 0, "name": 1}) or {}
        who = emp.get("name") or ot.get("submitted_by_name") or "Karyawan"
        excl = await _overtime_owner_user_ids(db, ot) | {(actor or {}).get("id")}
        return await notif_insert(
            db, type="rahaza", subtype="overtime_request_submitted", severity="warning",
            title="Pengajuan lembur menunggu persetujuan",
            body=(f"{who} mengajukan lembur {ot.get('date')} {ot.get('start_time')}–{ot.get('end_time')} "
                  f"({ot.get('hours')} jam)." + (f" Alasan: {ot.get('reason')}" if ot.get("reason") else "")),
            source_type="overtime", source_id=ot.get("id"),
            target_roles=decider_roles("hr", OVERTIME_DECIDER_ROLES),
            exclude_user_ids=sorted(x for x in excl if x), status="sent",
            meta={"link_module": "hr-approval-inbox"})
    except Exception as ne:  # noqa: BLE001 — notifikasi tidak boleh menggagalkan pengajuan
        import logging
        logging.getLogger(__name__).warning("[overtime] notif pengajuan gagal: %s", ne)
        return None


async def close_overtime_notifs(db, ot_id: str) -> int:
    """Periksa ulang action lembur ini lewat resolver K30 yang ada (sesudah diputuskan/dibatalkan)."""
    try:
        from utils.notif_unified import resolve_for_source
        return await resolve_for_source(db, "rahaza_overtime_requests", ot_id)
    except Exception:  # noqa: BLE001
        return 0


# ── 2026-11-02 — KABAR KEPUTUSAN LEMBUR KE PEMOHON ──────────────────────────
# Audit runtime 2026-11-02: lembur disetujui/ditolak tanpa satu notifikasi pun;
# pemohon harus membuka Portal Saya berkali-kali untuk tahu nasibnya. Lembur
# karyawan diajukan & dipantau di Portal Saya › Cuti & Lembur (`portal-cuti`).
# Helper ini juga boleh dipanggil jalur lain (mis. routes/hr_approval_inbox.py).
async def notify_overtime_decision(db, ot: dict, *, approved: bool, reason: str = ""):
    await close_overtime_notifs(db, ot.get("id"))   # 2026-11-02 (K30): Perlu Tindakan HR selesai
    try:
        from routes.rahaza_notifications import publish_notification
        from utils.employee_identity import employee_user_ids
        uids = await employee_user_ids(db, ot.get("employee_id"))   # dua arah tautan (Tahap 7)
        if not uids and ot.get("submitted_by"):
            uids = [ot["submitted_by"]]
        if not uids:
            return None
        when = f"{ot.get('date')} {ot.get('start_time')}–{ot.get('end_time')}, {ot.get('hours')} jam"
        if approved:
            title, msg = "Lembur Disetujui", f"Pengajuan lembur Anda ({when}) telah DISETUJUI."
        else:
            title = "Lembur Ditolak"
            msg = f"Pengajuan lembur Anda ({when}) DITOLAK. Alasan: {reason or '-'}."
        return await publish_notification(
            db,
            type_="overtime_approved" if approved else "overtime_rejected",
            severity="success" if approved else "warning",
            title=title, message=msg,
            link_module="portal-cuti", link_id=ot.get("id"),
            target_user_ids=uids,
            dedup_key=f"overtime_{'approved' if approved else 'rejected'}_{ot.get('id')}",
            dedup_minutes=1440,
        )
    except Exception as ne:  # noqa: BLE001 — kabar tidak boleh menggagalkan keputusan
        import logging
        logging.getLogger(__name__).warning("[overtime] notif keputusan gagal: %s", ne)
        return None


async def ensure_not_own_overtime(db, doc: dict, user: dict) -> None:
    """K25 (keputusan owner 2026-11-02): pengaju ≠ penyetuju. Lembur milik karyawan yang tertaut ke akun
    penyetuju, atau yang diajukan akun penyetuju sendiri, harus diputus orang lain."""
    from utils.employee_identity import resolve_my_employee
    mine = await resolve_my_employee(db, user)
    own = doc.get("submitted_by") == user.get("id") or (mine and mine.get("id") == doc.get("employee_id"))
    if own:
        raise HTTPException(403, "Pemisahan tugas: Anda tidak boleh memutus pengajuan lembur milik/ajuan Anda "
                                 "sendiri. Minta penyetuju lain.")


async def approve_overtime_request(db, ot_id: str, user: dict, note: str = "") -> dict:
    """SATU fungsi persetujuan lembur (layar Lembur & Kotak Masuk SDM)."""
    doc = await db.rahaza_overtime_requests.find_one({"id": ot_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Overtime request tidak ditemukan.")
    if doc.get("status") != "pending":
        raise HTTPException(400, f"Hanya request pending yang bisa di-approve (current: {doc.get('status')}).")
    await ensure_not_own_overtime(db, doc, user)
    # 2026-11-09 (Q6): tingkat 1 = atasan langsung, lalu HR (core.approval_route).
    from core.approval_route import STAGE_MANAGER, decision_stage, waiting_manager
    stage = await decision_stage(db, doc, user, is_hr_approver=is_ot_approver(user), what="pengajuan lembur")
    if stage == STAGE_MANAGER and waiting_manager(doc):
        step = {"step": 1, "approver_id": user["id"], "approver_name": user.get("name", ""), "stage": stage,
                "notes": note or "", "at": _now()}
        res = await db.rahaza_overtime_requests.update_one(
            {"id": ot_id, "status": "pending", "current_approval_level": 1},
            {"$set": {"approval_step_1": step, "current_approval_level": 2, "updated_at": _now()}})
        if not res.matched_count:
            raise HTTPException(409, "Pengajuan lembur ini baru saja diputuskan orang lain — muat ulang halaman.")
        out = await db.rahaza_overtime_requests.find_one({"id": ot_id}, {"_id": 0})
        await notify_overtime_submitted(db, out or doc, actor=user)   # sekarang giliran HR
        return out or doc
    step1 = doc.get("approval_step_1") or {}
    if step1.get("approver_id") and step1.get("approver_id") == user.get("id"):
        raise HTTPException(409, "Persetujuan tahap HR harus oleh orang lain: Anda sudah menyetujui sebagai atasan.")

    # 2026-11-06 (pola P9): hanya yang MASIH pending — setuju/tolak bersamaan tidak saling menimpa
    # (lembur disetujui masuk upah lembur payroll) dan yang kalah tidak mengirim kabar palsu.
    res = await db.rahaza_overtime_requests.update_one(
        {"id": ot_id, "status": "pending"},
        {"$set": {
            "status": "approved",
            "approved_by": user["id"],
            "approved_by_name": user.get("name", ""),
            "approved_at": _now(),
            "approval_note": note or "",
            "updated_at": _now(),
        }}
    )
    if not res.matched_count:
        raise HTTPException(409, "Pengajuan lembur ini baru saja diputuskan orang lain — muat ulang halaman.")
    out = await db.rahaza_overtime_requests.find_one({"id": ot_id}, {"_id": 0})
    await notify_overtime_decision(db, out or doc, approved=True)  # 2026-11-02
    return out or doc


async def reject_overtime_request(db, ot_id: str, user: dict, reason: str) -> dict:
    doc = await db.rahaza_overtime_requests.find_one({"id": ot_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Overtime request tidak ditemukan.")
    if doc.get("status") != "pending":
        raise HTTPException(400, "Hanya request pending yang bisa di-reject.")
    await ensure_not_own_overtime(db, doc, user)
    from core.approval_route import decision_stage   # Q6: atasan (tingkat 1) atau HR
    await decision_stage(db, doc, user, is_hr_approver=is_ot_approver(user), action="reject",
                         what="pengajuan lembur")
    res = await db.rahaza_overtime_requests.update_one(
        {"id": ot_id, "status": "pending"},   # 2026-11-06 (pola P9)
        {"$set": {
            "status": "rejected",
            "rejected_reason": reason,
            "rejected_by": user["id"],
            "approved_by": user["id"],
            "approved_by_name": user.get("name", ""),
            "approved_at": _now(),
            "updated_at": _now(),
        }}
    )
    if not res.matched_count:
        raise HTTPException(409, "Pengajuan lembur ini baru saja diputuskan orang lain — muat ulang halaman.")
    out = await db.rahaza_overtime_requests.find_one({"id": ot_id}, {"_id": 0})
    await notify_overtime_decision(db, out or doc, approved=False, reason=reason)  # 2026-11-02
    return out or doc


@router.put("/{ot_id}/approve")
async def approve_request(ot_id: str, request: Request):
    user = await _require_approver(request)
    db = get_db()
    out = await approve_overtime_request(db, ot_id, user)
    return {"ok": True, "overtime": _s(out)}


@router.put("/{ot_id}/reject")
async def reject_request(ot_id: str, request: Request):
    user = await _require_approver(request)
    db = get_db()
    body = await request.json()
    reason = body.get("reason") or "Tidak disebutkan"
    out = await reject_overtime_request(db, ot_id, user, reason)
    return {"ok": True, "overtime": _s(out)}


@router.delete("/{ot_id}")
async def cancel_request(ot_id: str, request: Request):
    user = await require_auth(request)
    db = get_db()
    doc = await db.rahaza_overtime_requests.find_one({"id": ot_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Overtime request tidak ditemukan.")

    # Employee can cancel own pending; admin can cancel anything
    # 2026-11-07 (Tahap 7): tombol Batalkan di Portal Saya — milik sendiri = diajukan akun ini ATAU karyawan yang
    # tertaut ke akun ini (SSOT identitas); hanya yang masih menunggu (klaim atomik di bawah → 409 bila diputus).
    if not is_ot_approver(user):
        from utils.employee_identity import resolve_my_employee
        mine = await resolve_my_employee(db, user)
        if doc.get("submitted_by") != user["id"] and not (mine and mine.get("id") == doc.get("employee_id")):
            raise HTTPException(403, "Anda hanya bisa membatalkan pengajuan lembur milik sendiri.")
        if doc.get("status") != "pending":
            raise HTTPException(409, "Pengajuan lembur ini sudah diputuskan HR sehingga tidak bisa dibatalkan.")

    # 2026-11-06 (pola P9): status lama di filter — pembatalan karyawan tidak menimpa keputusan atasan
    # yang baru saja masuk di sela baca & tulis.
    res = await db.rahaza_overtime_requests.update_one(
        {"id": ot_id, "status": doc.get("status")},
        {"$set": {"status": "cancelled", "updated_at": _now()}}
    )
    if not res.matched_count:
        raise HTTPException(409, "Pengajuan lembur ini baru saja diputuskan orang lain — muat ulang halaman.")
    await close_overtime_notifs(db, ot_id)   # 2026-11-02 (K30)
    return {"ok": True}

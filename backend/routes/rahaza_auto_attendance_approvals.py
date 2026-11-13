"""
Rahaza Auto-Attendance - Approvals
HR Approval Queue for pending attendance
"""
from routes.shared import lolos_centang  # 14 Nov 2026 (tahap 2): centang owner dihormati
import uuid
import os
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from database import get_db
from auth import require_auth, serialize_doc, log_activity, check_role
from dotenv import load_dotenv
from utils.waktu import today_wib

load_dotenv()

# WebAuthn imports (graceful fallback)
WEBAUTHN_AVAILABLE = False
try:
    from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
    from webauthn.helpers.exceptions import (
        InvalidRegistrationResponse,
        InvalidAuthenticationResponse,
    )
    WEBAUTHN_AVAILABLE = True
except Exception:
    def base64url_to_bytes(s): return b""
    def bytes_to_base64url(b): return ""
    class InvalidRegistrationResponse(Exception):
        pass
    class InvalidAuthenticationResponse(Exception):
        pass

# AI Face Compare

router = APIRouter(tags=["rahaza-auto-attendance-approvals"])

# Config
RP_ID = os.environ.get("WEBAUTHN_RP_ID", "analytics-builds.preview.emergentagent.com")
RP_NAME = os.environ.get("WEBAUTHN_RP_NAME", "Dewi Aditya ERP")
ORIGIN = os.environ.get("WEBAUTHN_ORIGIN", "https://fresh-context-1.preview.emergentagent.com")


def _uid(): return str(uuid.uuid4())
def _now(): return datetime.now(timezone.utc)
def _today_iso(): return today_wib().isoformat()




# 2026-11-08: penyetuju absen tertunda = kode peran lama ATAU izin `hr.approve` (modul Absensi, aksi Approve).
# Peran buatan owner ("HR Generalist") dulu 403 di daftar maupun tombol setujui/tolak.
ATT_APPROVER_ROLES = ("superadmin", "admin", "owner", "hr")
ATT_APPROVER_PERM = "hr.approve"


def _require_attendance_approver(user: dict) -> None:
    if lolos_centang(user):  # 14 Nov 2026 (tahap 2): centang owner dihormati
        return user
    if not (check_role(user, ATT_APPROVER_ROLES, ATT_APPROVER_PERM) or lolos_centang(user)):
        raise HTTPException(403, "Hanya HR/Admin.")


@router.get("/attendance/approvals")
async def list_approval_queue(
    request: Request,
    status: Optional[str] = "pending",
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    employee_id: Optional[str] = None,
):
    """Daftar absen yang perlu persetujuan HR."""
    user = await require_auth(request)
    _require_attendance_approver(user)
    db = get_db()

    q = {}
    if status and status != "all":
        q["approval_status"] = status
    if employee_id:
        q["employee_id"] = employee_id
    if from_date or to_date:
        q["date"] = {}
        if from_date:
            q["date"]["$gte"] = from_date
        if to_date:
            q["date"]["$lte"] = to_date

    rows = await db.rahaza_attendance_events.find(q, {"_id": 0}).sort("date", -1).to_list(500)

    # Enrich with employee info
    emp_ids = list({r["employee_id"] for r in rows if r.get("employee_id")})
    emps = await db.rahaza_employees.find({"id": {"$in": emp_ids}}, {"_id": 0, "id": 1, "name": 1, "employee_code": 1, "department": 1}).to_list(500)
    e_map = {e["id"]: e for e in emps}
    for r in rows:
        e = e_map.get(r.get("employee_id")) or {}
        r["employee_name"] = e.get("name", "?")
        r["employee_code"] = e.get("employee_code", "-")
        r["department"] = e.get("department", "-")

    return serialize_doc(rows)


async def decide_selfie(db, event_id: str, user: dict, *, approve: bool, notes: str = "") -> dict:
    """Keputusan HR atas absen selfie — SATU fungsi untuk layar Approval Absen & Kotak Masuk SDM.

    Tahap 2 (2026-11-06): tanggal yang sudah masuk gaji final ditolak (koreksi lewat pengajuan koreksi),
    perubahan dicatat di jejak absensi, dan penolakan menulis status kontrak 'alpa'. Hari cuti (setengah
    hari) tetap berstatus cutinya — yang diputus hanya selfie-nya."""
    from core.attendance_rules import ensure_not_locked, write_attendance_audit
    ev = await db.rahaza_attendance_events.find_one({"id": event_id}, {"_id": 0})
    if not ev:
        raise HTTPException(404, "Record absen tidak ditemukan.")
    # 2026-11-07 (Tahap 7): hanya selfie yang MASIH menunggu (layar Approval Absen hanya menampilkan tombol
    # untuk yang menunggu). Dulu Kotak Masuk bisa "menolak" selfie yang sudah disetujui/ditolak.
    if ev.get("approval_status") != "pending":
        raise HTTPException(409, f"Absen ini sudah diputuskan ({ev.get('approval_status') or '-'}). Muat ulang halaman.")
    # Pemisahan tugas (sejalan K25 & koreksi absen): HR tidak memutus selfie absennya sendiri.
    from utils.employee_identity import resolve_my_employee
    mine = await resolve_my_employee(db, user)
    if mine and mine.get("id") == ev.get("employee_id"):
        raise HTTPException(403, "Pemisahan tugas: absen selfie milik Anda sendiri harus diperiksa HR lain.")
    await ensure_not_locked(db, ev.get("employee_id"), ev.get("date"))
    now = _now()
    upd = {
        "approval_status": "approved" if approve else "rejected",
        "approval_by": user["id"],
        "approval_by_name": user.get("name", ""),
        "approval_notes": notes or "",
        "approval_at": now,
        "updated_by": user["id"], "updated_by_name": user.get("name", ""), "updated_at": now,
    }
    if not ev.get("leave_request_id"):
        upd["status"] = "hadir" if approve else "alpa"
    # klaim atomik (pola P9): setuju/tolak bersamaan → yang kalah 409, bukan saling menimpa
    res = await db.rahaza_attendance_events.update_one({"id": event_id, "approval_status": "pending"}, {"$set": upd})
    if not res.matched_count:
        raise HTTPException(409, "Absen ini baru saja diputuskan pengguna lain. Muat ulang halaman.")
    await write_attendance_audit(db, before=ev, after={**ev, **upd}, user=user, source="persetujuan_selfie",
                                 note=notes or "")
    if not approve:
        # Penolakan menjadikan hari itu ALPA (dipotong gaji) — karyawan wajib tahu supaya bisa mengajukan koreksi.
        await notify_selfie_rejected(db, {**ev, **upd}, notes or "")
    return {**ev, **upd}


async def notify_selfie_rejected(db, ev: dict, reason: str) -> None:
    """Kabar ke karyawan: absen selfie ditolak HR (tautan Portal Saya › Absen Saya). Tidak pernah raise."""
    from routes.rahaza_payroll_shared import notify_requester
    from utils.employee_identity import employee_user_ids
    try:
        uids = await employee_user_ids(db, ev.get("employee_id"))
    except Exception:  # noqa: BLE001 — kabar tidak boleh menggagalkan keputusan
        uids = []
    for uid in uids:
        await notify_requester(
            db, user_id=uid, subtype="attendance_selfie_rejected", severity="warning",
            title=f"Absen {ev.get('date')} ditolak HR",
            body=(f"Absen selfie tanggal {ev.get('date')} ditolak HR sehingga tercatat alpa. "
                  f"Alasan: {reason or '-'}. Bila Anda hadir, ajukan koreksi absen di Absen Saya."),
            link_module="portal-absen", source_type="attendance", source_id=ev.get("id"))


@router.post("/attendance/approvals/{event_id}/approve")
async def approve_attendance(event_id: str, request: Request):
    """HR menyetujui absen yang pending."""
    user = await require_auth(request)
    _require_attendance_approver(user)
    db = get_db()
    body = await request.json()
    await decide_selfie(db, event_id, user, approve=True, notes=body.get("notes", ""))
    await log_activity(user["id"], user.get("name", ""), "approve-attendance", "attendance", event_id)
    return {"ok": True, "message": "Absen disetujui."}


@router.post("/attendance/approvals/{event_id}/reject")
async def reject_attendance(event_id: str, request: Request):
    """HR menolak absen yang pending."""
    user = await require_auth(request)
    _require_attendance_approver(user)
    db = get_db()
    body = await request.json()
    await decide_selfie(db, event_id, user, approve=False, notes=body.get("notes", ""))
    await log_activity(user["id"], user.get("name", ""), "reject-attendance", "attendance", event_id)
    return {"ok": True, "message": "Absen ditolak."}

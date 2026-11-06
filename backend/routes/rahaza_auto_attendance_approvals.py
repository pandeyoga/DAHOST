"""
Rahaza Auto-Attendance - Approvals
HR Approval Queue for pending attendance
"""
import uuid
import os
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from database import get_db
from auth import require_auth, serialize_doc, log_activity
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
    if user.get("role") not in ("superadmin", "admin", "owner", "hr"):
        raise HTTPException(403, "Hanya HR/Admin.")
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
    await db.rahaza_attendance_events.update_one({"id": event_id}, {"$set": upd})
    await write_attendance_audit(db, before=ev, after={**ev, **upd}, user=user, source="persetujuan_selfie",
                                 note=notes or "")
    return {**ev, **upd}


@router.post("/attendance/approvals/{event_id}/approve")
async def approve_attendance(event_id: str, request: Request):
    """HR menyetujui absen yang pending."""
    user = await require_auth(request)
    if user.get("role") not in ("superadmin", "admin", "owner", "hr"):
        raise HTTPException(403, "Hanya HR/Admin.")
    db = get_db()
    body = await request.json()
    await decide_selfie(db, event_id, user, approve=True, notes=body.get("notes", ""))
    await log_activity(user["id"], user.get("name", ""), "approve-attendance", "attendance", event_id)
    return {"ok": True, "message": "Absen disetujui."}


@router.post("/attendance/approvals/{event_id}/reject")
async def reject_attendance(event_id: str, request: Request):
    """HR menolak absen yang pending."""
    user = await require_auth(request)
    if user.get("role") not in ("superadmin", "admin", "owner", "hr"):
        raise HTTPException(403, "Hanya HR/Admin.")
    db = get_db()
    body = await request.json()
    await decide_selfie(db, event_id, user, approve=False, notes=body.get("notes", ""))
    await log_activity(user["id"], user.get("name", ""), "reject-attendance", "attendance", event_id)
    return {"ok": True, "message": "Absen ditolak."}

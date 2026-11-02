"""
Rahaza Auto-Attendance - Selfie Attendance
Selfie + Geolocation → review HR

2026-11-02 (keputusan owner No.59a): verifikasi wajah via AI DIMATIKAN. Foto selfie
TIDAK lagi dikirim ke LLM; setiap absen selfie masuk antrean review HR
(`approval_status="pending"`, `approval_reason="menunggu review HR"`), disetujui/ditolak
di SDM › Absensi › Approval Absen (`/api/rahaza/attendance/approvals`).
"""
import uuid
import os
from datetime import datetime, timezone
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

router = APIRouter(tags=["rahaza-auto-attendance-selfie"])

# Config
RP_ID = os.environ.get("WEBAUTHN_RP_ID", "analytics-builds.preview.emergentagent.com")
RP_NAME = os.environ.get("WEBAUTHN_RP_NAME", "Dewi Aditya ERP")
ORIGIN = os.environ.get("WEBAUTHN_ORIGIN", "https://fresh-context-1.preview.emergentagent.com")

# 2026-11-02 (No.59a): pengganti face-match AI.
SELFIE_REVIEW_STATUS = "pending"
SELFIE_REVIEW_REASON = "menunggu review HR"
FACE_MATCH_DISABLED = {"status": "disabled", "match": None, "confidence": 0,
                       "reason": "Verifikasi wajah AI dimatikan (keputusan owner); identitas dicek HR."}


def _uid(): return str(uuid.uuid4())
def _now(): return datetime.now(timezone.utc)
def _today_iso(): return today_wib().isoformat()


@router.post("/attendance/selfie/clock-in")
async def selfie_clock_in(request: Request):
    """
    Absen masuk via selfie + GPS → menunggu review HR (2026-11-02, No.59a).
    Body: { employee_id, lat, lng, photo_base64 }  (`do_face_check` diabaikan)
    """
    user = await require_auth(request)
    db = get_db()
    body = await request.json()

    # ── SSOT identitas + otorisasi (FASE 15) ──────────────────────────────
    # DULU: `employee_id` diambil MENTAH dari body tanpa cek kepemilikan ⇒ siapa
    # pun yang punya token bisa "titip absen" untuk karyawan mana pun.
    from utils.employee_identity import compute_late_minutes, resolve_employee_for
    emp = await resolve_employee_for(db, user, body.get("employee_id"))
    emp_id = emp["id"]

    lat = body.get("lat")
    lng = body.get("lng")
    photo_b64 = body.get("photo_base64", "")

    today = _today_iso()
    existing = await db.rahaza_attendance_events.find_one({"employee_id": emp_id, "date": today})
    if existing and existing.get("clock_in"):
        raise HTTPException(400, "Karyawan sudah clock-in hari ini.")

    # ── KEBIJAKAN WAJIB (FASE 16) ─────────────────────────────────────────
    # Keputusan user 2026-07-26: selfie + lokasi WAJIB. Penegakan ada di SSOT
    # `utils/attendance_policy.py` — jangan menyalin aturannya ke sini.
    from utils.attendance_policy import enforce_attendance_policy, save_selfie
    pol = await enforce_attendance_policy(db, photo_b64=photo_b64, lat=lat,
                                          lng=lng, action="masuk")
    geo = pol["geo"]

    # ── Verifikasi wajah AI DIMATIKAN (No.59a) — foto tidak dikirim ke LLM ─
    face = dict(FACE_MATCH_DISABLED)

    # ── Approval: SELALU antrean review HR (dulu bisa auto_approved) ──────
    approval_status = SELFIE_REVIEW_STATUS

    # ── Bukti selfie DISIMPAN SUNGGUHAN (dulu hanya 20 karakter base64) ───
    selfie_url = save_selfie(emp_id, photo_b64, "in")

    now = _now()
    # ── Keterlambatan (FASE 15) ───────────────────────────────────────────
    # Sebelumnya `clock_in` TIDAK PERNAH dibandingkan dengan jam masuk shift,
    # sehingga kolom "POTONGAN TERLAMBAT" di sheet THP mustahil diisi.
    late = await compute_late_minutes(db, emp, now,
                                      (existing or {}).get("shift_id"))
    doc_fields = {
        "clock_in": now,
        **late,
        "attendance_method": "selfie_geo_ai",
        "geo_status": geo.get("status"),
        "geo_distance_m": geo.get("distance_m"),
        "clock_in_geo": {"lat": lat, "lng": lng, "status": geo.get("status"), "distance_m": geo.get("distance_m")},
        "face_match_score": face.get("confidence", 0),
        "face_match_status": face.get("status", "disabled"),
        "face_match_reason": face.get("reason", ""),
        "photo_selfie_url": selfie_url,
        "approval_status": approval_status,
        "approval_reason": SELFIE_REVIEW_REASON,
        "approval_by": None, "approval_by_name": None, "approval_notes": None, "approval_at": None,
        "status": "hadir",
        "source": "selfie_geo_ai",
        "updated_by": user["id"], "updated_by_name": user.get("name", ""), "updated_at": now,
    }

    if existing:
        await db.rahaza_attendance_events.update_one({"id": existing["id"]}, {"$set": doc_fields})
        out = await db.rahaza_attendance_events.find_one({"id": existing["id"]}, {"_id": 0})
    else:
        doc_fields.update({
            "id": _uid(), "employee_id": emp_id, "date": today,
            "clock_out": None, "clock_out_geo": None,
            "hours_worked": 0, "overtime_hours": 0, "notes": "",
            "created_by": user["id"], "created_by_name": user.get("name", ""), "created_at": now,
        })
        await db.rahaza_attendance_events.insert_one(doc_fields)
        out = doc_fields

    await log_activity(user["id"], user.get("name", ""), "selfie-clock-in", "attendance", emp_id)
    return {
        "ok": True,
        "attendance": serialize_doc(out),
        "geo": geo,
        "face": face,
        "approval_status": approval_status,
        "approval_reason": SELFIE_REVIEW_REASON,
        "message": "Absen masuk tercatat — menunggu review HR.",
    }


@router.post("/attendance/selfie/clock-out")
async def selfie_clock_out(request: Request):
    """
    Absen pulang via selfie + GPS.
    Body: { employee_id, lat, lng, photo_base64 }
    """
    user = await require_auth(request)
    db = get_db()
    body = await request.json()

    # ── SSOT identitas + otorisasi (FASE 15) — lihat catatan di clock-in ──
    from utils.employee_identity import resolve_employee_for
    emp = await resolve_employee_for(db, user, body.get("employee_id"))
    emp_id = emp["id"]

    today = _today_iso()
    existing = await db.rahaza_attendance_events.find_one({"employee_id": emp_id, "date": today})
    if not existing or not existing.get("clock_in"):
        raise HTTPException(400, "Belum clock-in hari ini.")
    if existing.get("clock_out"):
        raise HTTPException(400, "Sudah clock-out hari ini.")

    lat = body.get("lat")
    lng = body.get("lng")
    photo_b64 = body.get("photo_base64", "")

    # ── KEBIJAKAN WAJIB (FASE 16) — dulu clock-out MEMBUANG photo_base64 ──
    from utils.attendance_policy import enforce_attendance_policy, save_selfie
    pol = await enforce_attendance_policy(db, photo_b64=photo_b64, lat=lat,
                                          lng=lng, action="pulang")
    geo = pol["geo"]

    # ── Sesi istirahat/izin yang masih terbuka harus ditutup dulu ─────────
    # Pakai SSOT status sesi — sesi yang DITOLAK/DIBATALKAN memang `in_at=None`
    # tapi bukan "sedang keluar", jadi tidak boleh memblokir absen pulang.
    from routes.rahaza_attendance_sessions import is_permit_pending, is_session_out
    for s in (existing.get("sessions") or []):
        if is_session_out(s):
            raise HTTPException(
                400,
                f"Masih ada sesi {s.get('kind')} yang belum ditutup. "
                "Tekan 'Kembali Kerja' dulu sebelum absen pulang.")
        if is_permit_pending(s):
            raise HTTPException(
                400,
                "Ada pengajuan izin yang masih menunggu persetujuan. "
                "Batalkan pengajuan atau minta HR memprosesnya dulu.")

    selfie_out_url = save_selfie(emp_id, photo_b64, "out")

    now = _now()
    cin = existing.get("clock_in")
    if isinstance(cin, str):
        try:
            cin = datetime.fromisoformat(cin.replace("Z", "+00:00"))
        except Exception:
            cin = None
    elif isinstance(cin, datetime):
        # Make timezone-aware if naive
        if cin.tzinfo is None:
            cin = cin.replace(tzinfo=timezone.utc)
    hours = round((now - cin).total_seconds() / 3600, 2) if cin else 0

    # ── Jam BERSIH = jam kotor − istirahat − izin (FASE 15) ───────────────
    # `hours_worked` tetap rentang kotor supaya laporan lama tidak berubah
    # diam-diam; payroll memakai `net_hours_worked`.
    from routes.rahaza_attendance_sessions import recompute_session_totals
    totals = recompute_session_totals({**existing, "hours_worked": max(0.0, hours)})

    await db.rahaza_attendance_events.update_one({"id": existing["id"]}, {"$set": {
        "clock_out": now,
        "clock_out_geo": {"lat": lat, "lng": lng, "status": geo.get("status"), "distance_m": geo.get("distance_m")},
        "photo_selfie_out_url": selfie_out_url,
        "hours_worked": max(0.0, hours),
        **totals,
        "source": "selfie_geo_ai",
        "updated_by": user["id"], "updated_by_name": user.get("name", ""), "updated_at": now,
    }})
    out = await db.rahaza_attendance_events.find_one({"id": existing["id"]}, {"_id": 0})
    await log_activity(user["id"], user.get("name", ""), "selfie-clock-out", "attendance", emp_id)
    return {"ok": True, "attendance": serialize_doc(out), "geo": geo, "hours_worked": hours}


# ═══════════════════════════════════════════════════════════════════════════════
# 2) WEBAUTHN — REGISTRATION + AUTHENTICATION
# ═══════════════════════════════════════════════════════════════════════════════

async def _get_employee_webauthn_user(db, emp_id: str):
    emp = await db.rahaza_employees.find_one({"id": emp_id}, {"_id": 0})
    if not emp:
        raise HTTPException(404, "Karyawan tidak ditemukan.")
    return emp

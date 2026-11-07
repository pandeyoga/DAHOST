"""
Rahaza Auto-Attendance - Config
Status & Configuration endpoints
"""
import uuid
import os
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from database import get_db
from auth import require_auth, serialize_doc
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

router = APIRouter(tags=["rahaza-auto-attendance-config"])

# Config
RP_ID = os.environ.get("WEBAUTHN_RP_ID", "analytics-builds.preview.emergentagent.com")
RP_NAME = os.environ.get("WEBAUTHN_RP_NAME", "Dewi Aditya ERP")
ORIGIN = os.environ.get("WEBAUTHN_ORIGIN", "https://fresh-context-1.preview.emergentagent.com")


def _uid(): return str(uuid.uuid4())
def _now(): return datetime.now(timezone.utc)
def _today_iso(): return today_wib().isoformat()




@router.get("/attendance/my-status")
async def get_my_attendance_status(request: Request, employee_id: Optional[str] = None):
    """
    Ambil status kehadiran hari ini untuk karyawan (untuk /absen page).
    """
    user = await require_auth(request)
    db = get_db()

    # ── SSOT identitas (FASE 15) ──────────────────────────────────────────────
    # DULU: kalau email user tidak cocok karyawan mana pun, kode ini mengambil
    # `find_one({})` = KARYAWAN PERTAMA DI DATABASE. Terbukti 2026-07-26: login
    # sebagai Siti Rahayu (DA-002) menampilkan "Budi Operator (OP-001)" dan
    # tombol absen akan mencatat kehadiran ATAS NAMA ORANG LAIN.
    # Sekarang: satu resolver, tanpa tebakan; `employee_id` orang lain butuh HR.
    from utils.employee_identity import resolve_employee_for, resolve_my_employee
    if employee_id:
        emp = await resolve_employee_for(db, user, employee_id)
    else:
        emp = await resolve_my_employee(db, user)
    if not emp:
        return {
            "today": None,
            "employee": None,
            "linked": False,
            "message": ("Akun Anda belum ditautkan ke data karyawan. "
                        "Minta Admin HR menautkan lewat menu Data Karyawan → Tautkan Akun."),
        }
    emp_id = emp["id"]

    today = _today_iso()
    rec = await db.rahaza_attendance_events.find_one({"employee_id": emp_id, "date": today}, {"_id": 0})

    # Check WebAuthn credentials
    has_webauthn = await db.rahaza_webauthn_credentials.count_documents({"employee_id": emp_id, "revoked_at": None}) > 0

    # ── Sesi berjalan vs pengajuan menunggu (FASE 16) ────────────────────
    # DULU: `if not s.get("in_at")` — pengajuan izin yang MASIH MENUNGGU
    # persetujuan (out_at=None) ikut terbaca sebagai "sedang keluar", sehingga
    # Portal Saya menampilkan kartu "Sedang IZIN keluar (disetujui)" dengan jam
    # keluar "--:--". Pakai SSOT status sesi.
    from routes.rahaza_attendance_sessions import is_permit_pending, is_session_out
    active_session = None
    pending_permit = None
    for s in ((rec or {}).get("sessions") or []):
        if active_session is None and is_session_out(s):
            active_session = s
        if pending_permit is None and is_permit_pending(s):
            pending_permit = s

    # Tahap 2 (2026-11-06): shift lewat tengah malam — record KEMARIN yang masih boleh ditutup tampil sebagai
    # "absen pulang shift kemarin"; jam server ditampilkan supaya karyawan tahu jam yang akan dicatat.
    open_prev = None
    if not (rec and rec.get("clock_in")):
        from core.attendance_rules import previous_day_open_record
        open_prev = await previous_day_open_record(db, emp)
    return serialize_doc({
        "today": rec,
        "open_previous": open_prev,
        "server_time": _now(),
        "employee": emp,
        "linked": True,
        "has_webauthn": has_webauthn,
        "active_session": active_session,
        "pending_permit": pending_permit,
        "break_minutes": (rec or {}).get("break_minutes", 0),
        "permit_minutes": (rec or {}).get("permit_minutes", 0),
        "late_minutes": (rec or {}).get("late_minutes", 0),
        "date": today,
    })


@router.get("/attendance/my-schedule")
async def get_my_schedule(request: Request, days: int = 8, employee_id: Optional[str] = None):
    """Jadwal kerja karyawan: hari ini + 7 hari ke depan (Portal Saya › Absen Saya) — 2026-11-07 (Tahap 7).

    SATU sumber dengan perhitungan terlambat: shift per hari = `core.attendance_rules.resolve_day_shift`
    (Jadwal Shift terbit → penugasan shift → shift utama karyawan). Hari libur = Kalender Produksi `type=holiday`
    (libur nasional / cuti bersama / libur perusahaan), hari libur mingguan = `core.workdays` (kerja 6 hari bawaan),
    cuti/izin/sakit disetujui = absensi bertanda `leave_request_id`. Karyawan lain hanya untuk HR/atasan."""
    user = await require_auth(request)
    db = get_db()
    from datetime import timedelta
    from core import national_holidays as nh
    from core import workdays
    from core.attendance_rules import STATUS_LABELS, resolve_day_shift
    from utils.employee_identity import resolve_employee_for
    emp = await resolve_employee_for(db, user, employee_id)
    n = max(1, min(int(days or 8), 31))
    start = today_wib()
    end = start + timedelta(days=n - 1)
    cal = await workdays.get_work_calendar(db)
    # Tahap 9: kalender libur satu sumber (core.workdays — Portal SDM › Kalender libur).
    hol = {h["date"]: h for h in await workdays.holidays_between(db, start, end, limit=100)}
    leave = {str(r.get("date"))[:10]: r for r in await db.rahaza_attendance_events.find(
        {"employee_id": emp["id"], "date": {"$gte": start.isoformat(), "$lte": end.isoformat()},
         "leave_request_id": {"$nin": [None, ""]}},
        {"_id": 0, "date": 1, "status": 1, "leave_kind": 1, "half_day": 1, "leave_type_name": 1}).to_list(100)}
    rows = []
    for i in range(n):
        d = start + timedelta(days=i)
        iso = d.isoformat()
        shift = await resolve_day_shift(db, emp, iso)
        h, lv = hol.get(iso), leave.get(iso)
        note = ""
        if h:
            kind, label, note = "libur", nh.KIND_LABEL.get(h.get("kind"), "Hari libur"), h.get("name") or ""
        elif d.weekday() in cal["off_weekdays"]:
            kind, label = "libur", "Libur mingguan"
        else:
            kind, label = "kerja", ""
        # Shift tetap ditampilkan di hari libur bila HR MENJADWALKANNYA di Jadwal Shift (masuk saat libur).
        if kind == "libur" and not (shift and shift.get("source") == "jadwal"):
            shift = None
        if lv:
            lk = (lv.get("leave_kind") or lv.get("status") or "cuti").lower()
            label = STATUS_LABELS.get(lk, "Cuti") + (" setengah hari" if lv.get("half_day") else "")
            note = lv.get("leave_type_name") or ""
            kind = "cuti" if not lv.get("half_day") else kind
            if kind == "cuti":
                shift = None
        rows.append({
            "date": iso, "weekday": d.weekday(), "today": i == 0, "kind": kind, "label": label, "note": note,
            "shift": ({"code": shift.get("code"), "name": shift.get("name"), "start_time": shift.get("start_time"),
                       "end_time": shift.get("end_time"), "source": shift.get("source")} if shift else None),
        })
    return {"employee_id": emp["id"], "from": start.isoformat(), "to": end.isoformat(),
            "work_days_per_week": cal["work_days_per_week"], "days": rows}


# ═══════════════════════════════════════════════════════════════════════════════
# 5) OFFICE CONFIG — Face threshold + Geofence + kebijakan WAJIB (FASE 16)
# ═══════════════════════════════════════════════════════════════════════════════
# Endpoint ini dan `/attendance/office-location` (rahaza_attendance.py) dulu
# adalah DUA sumber kebenaran untuk dokumen yang SAMA, dengan nama field berbeda
# (`office_lat` vs `lat`). Akibatnya UI Konfigurasi membaca `office_lat` tapi
# menulis `lat` ⇒ kolom koordinat tampak beku dan HR mengira fiturnya rusak.
# Sekarang keduanya membaca/menulis lewat SSOT `utils/attendance_policy`.

@router.get("/attendance/auto-config")
async def get_auto_config(request: Request):
    """Konfigurasi absen otomatis (alias nama lama + kanonik, satu sumber)."""
    await require_auth(request)
    from utils.attendance_policy import get_office
    o = await get_office(get_db())
    return serialize_doc({
        **o,
        # alias nama lama supaya UI/skrip lama tidak pecah
        "office_name": o["name"],
        "office_lat": o["lat"],
        "office_lng": o["lng"],
        "allow_out_of_range": not o["require_geofence"],
    })


@router.put("/attendance/auto-config")
async def update_auto_config(request: Request):
    """Update konfigurasi absen otomatis (menerima nama lama maupun kanonik)."""
    user = await require_auth(request)
    if user.get("role") not in ("superadmin", "admin", "owner", "hr"):
        raise HTTPException(403, "Hanya HR/Admin.")
    db = get_db()
    body = await request.json()
    from utils.attendance_policy import get_office
    cur = await get_office(db)

    def pick(*keys, default=None):
        for k in keys:
            if body.get(k) is not None and body.get(k) != "":
                return body[k]
        return default

    updates: dict = {"is_primary": True}

    thr = pick("face_match_threshold")
    if thr is not None:
        val = float(thr)
        if not (0 <= val <= 1):
            raise HTTPException(400, "face_match_threshold harus 0.0-1.0")
        updates["face_match_threshold"] = val

    rad = pick("geofence_radius_m")
    if rad is not None:
        rad = int(rad)
        if not (10 <= rad <= 20000):
            raise HTTPException(400, "Radius harus antara 10 dan 20.000 meter.")
        updates["geofence_radius_m"] = rad

    name = pick("name", "office_name")
    if name:
        updates["name"] = str(name)
    if body.get("address") is not None:
        updates["address"] = str(body["address"])

    for canon, alias, lo, hi in (("lat", "office_lat", -90, 90),
                                 ("lng", "office_lng", -180, 180)):
        raw = pick(canon, alias)
        if raw is not None:
            try:
                v = float(raw)
            except (TypeError, ValueError):
                raise HTTPException(400, f"{canon} harus angka desimal.")
            if not (lo <= v <= hi):
                raise HTTPException(400, f"{canon} di luar rentang wajar ({lo}..{hi}).")
            updates[canon] = v

    # Tahap 2 (2026-11-06): kesegaran/akurasi GPS & jendela absen pulang lewat tengah malam
    for key, label, lo, hi, cast in (
            ("gps_max_age_s", "Umur maksimum lokasi (detik)", 10, 600, int),
            ("gps_max_accuracy_m", "Akurasi GPS terburuk (meter)", 10, 2000, int),
            ("clock_out_window_hours", "Jendela absen pulang (jam)", 0, 24, float)):
        raw = pick(key)
        if raw is not None:
            try:
                v = cast(raw)
            except (TypeError, ValueError):
                raise HTTPException(400, f"{label} harus berupa angka.")
            if not (lo <= v <= hi):
                raise HTTPException(400, f"{label} harus antara {lo} dan {hi}.")
            updates[key] = v

    if body.get("require_selfie") is not None:
        updates["require_selfie"] = bool(body["require_selfie"])
    if body.get("require_geofence") is not None:
        updates["require_geofence"] = bool(body["require_geofence"])
    elif body.get("allow_out_of_range") is not None:      # alias lama (terbalik)
        updates["require_geofence"] = not bool(body["allow_out_of_range"])

    final_geofence = updates.get("require_geofence", cur["require_geofence"])
    final_lat = updates.get("lat", cur["lat"])
    if final_geofence and final_lat is None:
        raise HTTPException(
            400,
            "Verifikasi lokasi diwajibkan tetapi koordinat kantor kosong. "
            "Isi Latitude/Longitude (tombol 'Pakai lokasi saya sekarang') atau "
            "matikan dulu kewajiban lokasi.")

    updates["updated_at"] = _now()
    updates["updated_by_name"] = user.get("name", "")
    await db.rahaza_office_locations.update_one(
        {"is_primary": True}, {"$set": updates}, upsert=True
    )
    o = await get_office(db)
    return {"ok": True, "updated": [k for k in updates if k != "is_primary"],
            "config": serialize_doc({**o, "office_name": o["name"],
                                     "office_lat": o["lat"], "office_lng": o["lng"]})}

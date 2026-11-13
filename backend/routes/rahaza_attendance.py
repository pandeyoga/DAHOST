"""
HR Attendance & HR Dashboard — PT Rahaza ERP

Endpoints:
  Clock-in/out (operator self-service)
  Attendance grid (supervisor bulk-entry)
  Attendance summary (payroll calculation input)
  HR Dashboard (Sprint 1.2 — replaces placeholder, real KPIs)
"""
from routes.shared import lolos_centang  # 14 Nov 2026 (tahap 2): centang owner dihormati
from fastapi import APIRouter, Request, HTTPException
from database import get_db
from auth import require_auth, serialize_doc, check_role
from utils.waktu import today_wib

# P3 (kebijakan absen): endpoint clock-in/out LANGSUNG (source="operator", tanpa
# verifikasi selfie/biometrik) hanya untuk HR/Supervisor/Admin sebagai FALLBACK
# koreksi manual. Absen mandiri karyawan WAJIB lewat /attendance/selfie/* atau
# /attendance/webauthn/* (dipakai AbsenPage). Ini menutup celah self-service tanpa verifikasi.
OPERATOR_ATTENDANCE_ROLES = ['admin', 'superadmin', 'hr', 'hr_manager', 'supervisor_produksi']

# Tahap 1 (2026-11-06): input/koreksi absensi oleh HR (grid harian, POST /attendance) hanya untuk HR &
# manajemen (`core.roles.HR_ROLES`) + admin. Dulu tanpa cek peran: peran internal mana pun — termasuk
# peran tanpa daftar portal — bisa menulis absensi & jam lembur dirinya sendiri lewat endpoint ini.
# Absen mandiri karyawan tetap lewat /attendance/selfie/*, /attendance/webauthn/*, /attendance/sessions/*.
from core.roles import HR_ROLES
HR_ATTENDANCE_WRITE_ROLES = ['admin', *HR_ROLES]
MSG_HR_ATTENDANCE_ONLY = ("Input absensi manual hanya untuk HR dan manajemen. "
                          "Absen mandiri lewat Portal Saya › Absen Saya.")
MSG_HR_ATTENDANCE_VIEW = ("Absensi semua karyawan hanya untuk HR dan atasan. "
                          "Absensi Anda sendiri ada di Portal Saya › Absen Saya.")
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

router = APIRouter(prefix="/api/rahaza", tags=["rahaza-hr"])


def _uid(): return str(uuid.uuid4())
def _now(): return datetime.now(timezone.utc)
def _today_iso(): return today_wib().isoformat()
def _parse_iso(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None

def _calc_hours(cin, cout) -> float:
    if not cin or not cout:
        return 0.0
    if isinstance(cin, str):
        cin = _parse_iso(cin)
    if isinstance(cout, str):
        cout = _parse_iso(cout)
    if not cin or not cout:
        return 0.0
    # Normalisasi ke timezone-aware (UTC): clock_in dari MongoDB dapat berupa naive datetime,
    # sedangkan _now() aware. Tanpa normalisasi, pengurangan memicu TypeError (naive vs aware).
    if cin.tzinfo is None:
        cin = cin.replace(tzinfo=timezone.utc)
    if cout.tzinfo is None:
        cout = cout.replace(tzinfo=timezone.utc)
    diff = (cout - cin).total_seconds() / 3600
    return round(max(0.0, diff), 2)


async def _enrich(db, rows: list):
    """Add employee_name + employee_code to rows in-place."""
    eids = {r["employee_id"] for r in rows if r.get("employee_id")}
    emps = await db.rahaza_employees.find({"id": {"$in": list(eids)}}, {"_id": 0, "id": 1, "name": 1, "employee_code": 1}).to_list(500) if eids else []
    e_map = {e["id"]: e for e in emps}
    for r in rows:
        e = e_map.get(r.get("employee_id")) or {}
        r.setdefault("employee_name", e.get("name", "?"))
        r.setdefault("employee_code", e.get("employee_code", "-"))


@router.get("/attendance/office-location")
async def get_office_location(request: Request):
    """Konfigurasi kantor + KEBIJAKAN absen (dipakai UI HR & Portal Saya).

    FASE 16: sebelumnya hanya mengembalikan dokumen mentah, sehingga UI tidak
    pernah tahu apakah selfie/geofence diwajibkan dan apakah koordinat kantor
    sudah diisi (`configured`).
    """
    await require_auth(request)
    from utils.attendance_policy import get_office
    return await get_office(get_db())


@router.put("/attendance/office-location")
async def set_office_location(request: Request):
    user = await require_auth(request)
    # 2026-11-08: kode peran lama ATAU izin `hr.attendance.manage` ("Kelola absensi, shift & izin").
    if not (check_role(user, ("superadmin", "admin", "owner", "hr"), "hr.attendance.manage") or lolos_centang(user)):
        raise HTTPException(403, "Hanya admin/HR.")
    db = get_db()
    body = await request.json()

    def _coord(key: str, lo: float, hi: float):
        if body.get(key) in (None, ""):
            return None
        try:
            v = float(body[key])
        except (TypeError, ValueError):
            raise HTTPException(400, f"{key} harus berupa angka desimal.")
        if not (lo <= v <= hi):
            raise HTTPException(400, f"{key} di luar rentang wajar ({lo}..{hi}).")
        return v

    lat, lng = _coord("lat", -90, 90), _coord("lng", -180, 180)
    if (lat is None) != (lng is None):
        raise HTTPException(400, "Isi lat DAN lng sekaligus (atau kosongkan keduanya).")

    try:
        radius = int(body.get("geofence_radius_m") or 300)
    except (TypeError, ValueError):
        raise HTTPException(400, "Radius harus berupa angka bulat (meter).")
    if not (10 <= radius <= 20000):
        raise HTTPException(400, "Radius harus antara 10 dan 20.000 meter.")

    require_geofence = bool(body.get("require_geofence", True))
    if require_geofence and lat is None:
        raise HTTPException(
            400,
            "Verifikasi lokasi diwajibkan tetapi koordinat kantor kosong. "
            "Isi lat/lng (tombol 'Pakai lokasi saya sekarang') atau matikan dulu "
            "kewajiban lokasi.")

    doc = {
        "is_primary": True,
        "name": body.get("name") or "Kantor Utama",
        "lat": lat,
        "lng": lng,
        "address": body.get("address") or "",
        "geofence_radius_m": radius,
        # FASE 16 — kebijakan "selfie & lokasi WAJIB" (keputusan user 2026-07-26)
        "require_selfie": bool(body.get("require_selfie", True)),
        "require_geofence": require_geofence,
        "face_match_threshold": float(body.get("face_match_threshold") or 0.65),
        "updated_at": _now(),
        "updated_by": user.get("id"),
        "updated_by_name": user.get("name", ""),
    }
    await db.rahaza_office_locations.update_one(
        {"is_primary": True}, {"$set": doc}, upsert=True
    )
    from utils.attendance_policy import get_office
    return {"ok": True, "office": await get_office(db)}


# ─── CLOCK IN / OUT (Operator self-service) ──────────────────────────────────

@router.post("/attendance/clock-in")
async def clock_in(request: Request):
    user = await require_auth(request)
    if not (check_role(user, OPERATOR_ATTENDANCE_ROLES) or lolos_centang(user)):
        raise HTTPException(403, "Clock-in manual (operator) hanya untuk HR/Supervisor. "
                                 "Absen mandiri gunakan verifikasi selfie/biometrik.")
    db = get_db()
    body = await request.json()
    emp_id = body.get("employee_id")
    if not emp_id:
        raise HTTPException(400, "employee_id wajib.")

    # ─── Geolokasi (FASE 16: pakai SSOT, jangan salin haversine) ─────────
    # Bug lama: `math.radians(float(office["lat"]))` meledak TypeError ketika
    # dokumen kantor ada tapi koordinatnya masih None (kasus DB baru).
    lat = body.get("lat")
    lng = body.get("lng")
    from utils.attendance_policy import check_geofence, get_office
    office = await get_office(db)
    _geo = check_geofence(lat, lng, office)
    geo_status = _geo["status"]
    geo_distance_m = _geo["distance_m"]

    d = _today_iso()
    existing = await db.rahaza_attendance_events.find_one({"employee_id": emp_id, "date": d}, {"_id": 0})
    if existing and existing.get("clock_in"):
        raise HTTPException(400, "Sudah clock-in hari ini.")
    from core.attendance_rules import ensure_not_locked, write_attendance_audit
    from utils.attendance_policy import leave_status_for_clock_in
    await ensure_not_locked(db, emp_id, d)
    day_status = leave_status_for_clock_in(existing)   # Tahap 2: hari cuti tidak ditimpa 'hadir'
    now = _now()
    # Keterlambatan juga dihitung untuk input manual HR — kalau tidak, kolom
    # "POTONGAN TERLAMBAT" di payroll kosong untuk karyawan yang diabsenkan HR.
    emp_doc = await db.rahaza_employees.find_one({"id": emp_id}, {"_id": 0}) or {}
    from utils.employee_identity import compute_late_minutes
    late = await compute_late_minutes(db, emp_doc, now, (existing or {}).get("shift_id"))
    geo_data = {"lat": lat, "lng": lng, "status": geo_status, "distance_m": geo_distance_m} if lat is not None else None
    if existing:
        await db.rahaza_attendance_events.update_one(
            {"id": existing["id"]},
            {"$set": {"clock_in": now, "source": "operator", **late, "status": day_status,
                      "clock_in_geo": geo_data,
                      "updated_by": user["id"], "updated_by_name": user.get("name", ""), "updated_at": now}}
        )
        out = await db.rahaza_attendance_events.find_one({"id": existing["id"]}, {"_id": 0})
        await write_attendance_audit(db, before=existing, after=out, user=user, source="manual",
                                     note="Absen masuk dicatat HR")
    else:
        doc = {
            "id": _uid(), "employee_id": emp_id, "date": d,
            "clock_in": now, "clock_out": None, **late,
            "clock_in_geo": geo_data, "clock_out_geo": None,
            "hours_worked": 0, "overtime_hours": 0,
            "status": "hadir", "notes": "", "source": "operator",
            "created_by": user["id"], "created_by_name": user.get("name", ""),
            "created_at": now, "updated_at": now,
        }
        await db.rahaza_attendance_events.insert_one(doc)
        out = doc
        await write_attendance_audit(db, before={}, after=doc, user=user, source="manual",
                                     note="Absen masuk dicatat HR")
    return serialize_doc(out)


@router.post("/attendance/clock-out")
async def clock_out(request: Request):
    user = await require_auth(request)
    if not (check_role(user, OPERATOR_ATTENDANCE_ROLES) or lolos_centang(user)):
        raise HTTPException(403, "Clock-out manual (operator) hanya untuk HR/Supervisor. "
                                 "Absen mandiri gunakan verifikasi selfie/biometrik.")
    db = get_db()
    body = await request.json()
    emp_id = body.get("employee_id")
    if not emp_id:
        raise HTTPException(400, "employee_id wajib.")
    # Tahap 2 (2026-11-06): lewat tengah malam → record kemarin (shift malam / jendela sesudah jam pulang).
    from core.attendance_rules import ensure_not_locked, find_clock_out_record, write_attendance_audit
    emp_doc = await db.rahaza_employees.find_one({"id": emp_id}, {"_id": 0}) or {"id": emp_id}
    existing, why = await find_clock_out_record(db, emp_doc)
    if not existing:
        raise HTTPException(400, why)
    await ensure_not_locked(db, emp_id, existing.get("date"))
    now = _now()
    cin = existing["clock_in"]
    if isinstance(cin, str):
        cin = _parse_iso(cin)
    hours = _calc_hours(cin, now)
    from core.attendance_rules import early_leave_fields
    early = await early_leave_fields(db, emp_doc, existing, now)   # 2026-11-09 (Q3): pulang cepat dicatat
    await db.rahaza_attendance_events.update_one({"id": existing["id"]}, {"$set": {
        "clock_out": now, "hours_worked": hours, "source": "operator", "updated_at": now,
        "updated_by": user["id"], "updated_by_name": user.get("name", ""), **early,
    }})
    out = await db.rahaza_attendance_events.find_one({"id": existing["id"]}, {"_id": 0})
    await write_attendance_audit(db, before=existing, after=out, user=user, source="manual",
                                 note="Absen pulang dicatat HR")
    return serialize_doc(out)


# ─── SUPERVISOR GRID ─────────────────────────────────────────────────────────

@router.get("/attendance")
async def list_attendance(
    request: Request,
    date: Optional[str] = None,
    employee_id: Optional[str] = None,
    from_: Optional[str] = None,
    to: Optional[str] = None,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
):
    user = await require_auth(request)
    db = get_db()
    # 2026-11-07 (Tahap 7): selain HR/atasan hanya absensi milik sendiri (dulu semua karyawan, termasuk
    # lokasi GPS & foto selfie, bisa dibaca akun staf mana pun).
    from utils.employee_identity import can_view_all_employees, resolve_my_employee
    if not can_view_all_employees(user):
        mine = await resolve_my_employee(db, user)
        if not mine or (employee_id and employee_id != mine["id"]):
            return {"total": 0, "skip": skip, "limit": limit, "has_more": False, "items": []}
        employee_id = mine["id"]
    q = {}
    if date:
        q["date"] = date
    if employee_id:
        q["employee_id"] = employee_id
    if status:
        q["status"] = status
    if from_ or to:
        range_q = {}
        if from_:
            range_q["$gte"] = from_
        if to:
            range_q["$lte"] = to
        q["date"] = range_q

    total = await db.rahaza_attendance_events.count_documents(q)
    rows = await db.rahaza_attendance_events.find(q, {"_id": 0}).sort("date", -1).skip(skip).limit(limit).to_list(500)
    await _enrich(db, rows)
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "has_more": (skip + limit) < total,
        "items": serialize_doc(rows),
    }


@router.get("/attendance/grid")
async def attendance_grid(request: Request, date: Optional[str] = None):
    user = await require_auth(request)
    # 2026-11-07 (Tahap 7): grid absensi SEMUA karyawan hanya untuk HR/atasan (layar Portal SDM).
    from utils.employee_identity import can_view_all_employees
    if not can_view_all_employees(user):
        raise HTTPException(403, MSG_HR_ATTENDANCE_VIEW)
    db = get_db()
    d = date or _today_iso()
    emps = await db.rahaza_employees.find({"active": True}, {"_id": 0}).sort("employee_code", 1).to_list(500)
    existing = await db.rahaza_attendance_events.find({"date": d}, {"_id": 0}).to_list(500)
    by_emp = {r["employee_id"]: r for r in existing}
    shifts = await db.rahaza_shifts.find({"active": True}, {"_id": 0}).sort("start_time", 1).to_list(500)
    # Tahap 2 (2026-11-06): lembur tanpa pengajuan disetujui tidak otomatis dibayar — HR menandainya di grid.
    ot_req = await db.rahaza_overtime_requests.find(
        {"date": d, "status": "approved"}, {"_id": 0, "employee_id": 1, "hours": 1}).to_list(500)
    ot_by_emp: dict = {}
    for o in ot_req:
        ot_by_emp[o.get("employee_id")] = ot_by_emp.get(o.get("employee_id"), 0) + float(o.get("hours") or 0)
    from core.attendance_rules import attendance_lock, default_shift_ids
    lock_cache: dict = {}
    # 2026-11-07 (Tahap 5): shift bawaan per karyawan (jadwal → penugasan → shift karyawan) untuk baris baru
    sched_off: set = set()   # 2026-11-09: libur menurut Jadwal Shift terbit (entri `libur: true`)
    default_shift = await default_shift_ids(db, emps, d, shifts, off_out=sched_off)
    rows = []
    for e in emps:
        r = by_emp.get(e["id"])
        if e["id"] not in lock_cache:
            lock_cache[e["id"]] = await attendance_lock(db, e["id"], d)
        rows.append({
            "employee_id": e["id"],
            "employee_code": e["employee_code"],
            "employee_name": e["name"],
            "role": e.get("role"),
            "line_id": e.get("line_id"),
            "existing_id": r["id"] if r else None,
            "status":        (r or {}).get("status",   "hadir"),
            "shift_id":      (r or {}).get("shift_id") or None,
            "default_shift_id": default_shift.get(e["id"]),
            "clock_in":      (r or {}).get("clock_in"),
            "clock_out":     (r or {}).get("clock_out"),
            "hours_worked":       (r or {}).get("hours_worked", 0),
            "overtime_hours":     (r or {}).get("overtime_hours", 0),
            "notes":         (r or {}).get("notes", ""),
            "source":        (r or {}).get("source", "supervisor"),
            "overtime_paid":            (r or {}).get("overtime_paid"),
            "overtime_paid_by_name":    (r or {}).get("overtime_paid_by_name"),
            "overtime_request_hours":   ot_by_emp.get(e["id"], 0),
            "leave_request_id":         (r or {}).get("leave_request_id"),
            "half_day":                 bool((r or {}).get("half_day")),
            "paid_leave":               (r or {}).get("paid_leave"),
            "approval_status":          (r or {}).get("approval_status"),
            "photo_selfie_url":         (r or {}).get("photo_selfie_url"),
            "photo_selfie_out_url":     (r or {}).get("photo_selfie_out_url"),
            "late_minutes":             (r or {}).get("late_minutes", 0),
            # 2026-11-09 (Q3/Q11/Q2): pulang cepat (dicatat), tugas luar, dan izin/sakit/cuti TANPA pengajuan
            # (akan dipotong — HR diarahkan membuat pengajuan atas nama karyawan, satu jalur dengan Portal Saya).
            "early_leave_minutes":      (r or {}).get("early_leave_minutes", 0),
            "late_reason":              (r or {}).get("late_reason"),
            "tugas_luar":               bool((r or {}).get("tugas_luar")),
            "jadwal_libur":             e["id"] in sched_off,
            "needs_leave_request":      bool(r and str(r.get("status") or "").lower() in ("izin", "sakit", "cuti")
                                             and not r.get("leave_request_id")),
            "locked":                   bool(lock_cache.get(e["id"])),
            "locked_run_number":        (lock_cache.get(e["id"]) or {}).get("run_number"),
        })
    return {"date": d, "shifts": serialize_doc(shifts), "rows": serialize_doc(rows)}


@router.post("/attendance/bulk")
async def bulk_attendance(request: Request):
    user = await require_auth(request)
    if not (check_role(user, HR_ATTENDANCE_WRITE_ROLES, "hr.manage") or lolos_centang(user)):
        raise HTTPException(403, MSG_HR_ATTENDANCE_ONLY)
    db = get_db()
    body = await request.json()
    # Terima dua bentuk payload: {"rows":[...]} (legacy) atau {"date":..,"entries":[...]} (grid UI).
    rows = body.get("rows") or body.get("entries") or []
    if not rows:
        raise HTTPException(400, "rows kosong.")
    # Tanggal default (top-level) diterapkan ke baris yang belum punya date sendiri.
    default_date = body.get("date") or _today_iso()
    for row in rows:
        if not row.get("date"):
            row["date"] = default_date
    # Batch prefetch existing attendance events for all (employee_id, date) pairs
    emp_date_pairs = set()
    for row in rows:
        eid = row.get("employee_id")
        d_row = row.get("date", _today_iso())
        if eid:
            emp_date_pairs.add((eid, d_row))
    existing_map: dict = {}
    if emp_date_pairs:
        emp_ids_bulk = list({p[0] for p in emp_date_pairs})
        dates_bulk = list({p[1] for p in emp_date_pairs})
        async for e in db.rahaza_attendance_events.find(
            {"employee_id": {"$in": emp_ids_bulk}, "date": {"$in": dates_bulk}}, {"_id": 0}
        ):
            existing_map[(e.get("employee_id"), e.get("date"))] = e

    # Tahap 2 (2026-11-06): tanggal yang sudah masuk gaji FINAL tidak boleh diubah HR (semua-atau-tidak sama
    # sekali, supaya HR tidak mengira sebagian tersimpan). Koreksinya lewat pengajuan koreksi absen.
    from core.attendance_rules import attendance_lock, lock_message, write_attendance_audit
    for row in rows:
        if not row.get("employee_id"):
            continue
        lock = await attendance_lock(db, row["employee_id"], row.get("date"))
        if lock:
            emp_doc = await db.rahaza_employees.find_one({"id": row["employee_id"]}, {"_id": 0, "name": 1}) or {}
            raise HTTPException(409, lock_message(row.get("date"), lock, emp_doc.get("name", "")))

    saved = 0
    warnings = []
    for row in rows:
        doc = await _build_att_doc(db, row, user, prefetched_existing=existing_map)
        if not doc:
            continue
        existing = existing_map.get((row["employee_id"], row.get("date", _today_iso())))
        if existing:
            await db.rahaza_attendance_events.update_one({"id": existing["id"]}, {"$set": doc})
        else:
            await db.rahaza_attendance_events.insert_one(doc)
        await write_attendance_audit(db, before=existing or {}, after={**(existing or {}), **doc}, user=user,
                                     source="grid", employee_id=row["employee_id"], day=row.get("date"))
        saved += 1
        after = {**(existing or {}), **doc}
        if str(after.get("status") or "").lower() in ("izin", "sakit", "cuti") and not after.get("leave_request_id"):
            # 2026-11-09 (Q2, keputusan owner): izin/sakit/cuti DIBAYAR hanya lewat pengajuan (satu jalur) —
            # status yang diketik di grid tanpa pengajuan dipotong payroll (rahaza_payroll_rules.classify_days).
            warnings.append({"employee_id": row["employee_id"], "date": row.get("date"), "status": after.get("status"),
                             "message": "Tanpa pengajuan cuti/izin yang disetujui, hari ini dipotong dari gaji. "
                                        "Buat pengajuan atas nama karyawan bila izin/sakitnya dibayar."})
    return {"ok": True, "saved": saved, "warnings": warnings}


def _as_dt(v):
    """Nilai jam dari body: '' / None → None, teks ISO → datetime."""
    if not v:
        return None
    return _parse_iso(v) if isinstance(v, str) else v


async def _build_att_patch(db, existing: dict, body: dict, user: dict) -> dict:
    """Record SUDAH ada: tulis HANYA kolom yang dikirim (Tahap 1, 2026-11-06).

    Dulu grid HR menimpa SELURUH record: jam masuk/pulang dan menit terlambat hasil absen selfie/mesin
    ikut terhapus (grid tidak mengirimnya, lalu ditulis None/0) setiap kali HR menekan Simpan.
    Nilai turunan dihitung ulang hanya bila sumbernya ikut diubah."""
    upd: dict = {}
    if "status" in body:
        upd["status"] = (body.get("status") or "hadir").lower()
    if "shift_id" in body:
        upd["shift_id"] = body.get("shift_id") or None
    if "notes" in body:
        upd["notes"] = body.get("notes") or ""
    if body.get("source"):
        upd["source"] = str(body["source"]).lower()
    cin, cout = existing.get("clock_in"), existing.get("clock_out")
    if "clock_in" in body:
        cin = upd["clock_in"] = _as_dt(body.get("clock_in"))
    if "clock_out" in body:
        cout = upd["clock_out"] = _as_dt(body.get("clock_out"))
    if body.get("hours_worked") not in (None, ""):
        upd["hours_worked"] = round(max(0.0, float(body["hours_worked"])), 2)
    elif "clock_in" in body or "clock_out" in body:
        upd["hours_worked"] = round(max(0.0, _calc_hours(cin, cout)), 2)
    if "overtime_hours" in body:
        upd["overtime_hours"] = round(max(0.0, float(body.get("overtime_hours") or 0)), 2)
    if {"status", "shift_id", "clock_in"} & set(body):
        from utils.employee_identity import compute_late_minutes
        status = upd.get("status", (existing.get("status") or "hadir").lower())
        shift_id = upd["shift_id"] if "shift_id" in upd else existing.get("shift_id")
        emp_doc = await db.rahaza_employees.find_one({"id": existing.get("employee_id")}, {"_id": 0}) or {}
        # Hari tidak hadir tidak punya keterlambatan; jam masuknya tetap disimpan apa adanya.
        # 2026-11-09: cuti/izin SETENGAH hari tetap dinilai (acuan paruh siang, utils.employee_identity).
        from core.attendance_rules import counts_timing
        rec_now = {**existing, **upd, "status": status, "shift_id": shift_id}
        upd.update(await compute_late_minutes(db, emp_doc, cin if counts_timing(rec_now) else None, shift_id))
    if {"status", "shift_id", "clock_out"} & set(body):
        from core.attendance_rules import early_leave_fields
        emp_doc = await db.rahaza_employees.find_one({"id": existing.get("employee_id")}, {"_id": 0}) or {}
        upd.update(await early_leave_fields(db, emp_doc, {**existing, **upd}, cout))
    if "hours_worked" in upd:
        from routes.rahaza_attendance_sessions import recompute_session_totals
        upd.update(recompute_session_totals({"sessions": existing.get("sessions") or [],
                                             "hours_worked": upd["hours_worked"]}))
    upd.update({"updated_by": user["id"], "updated_by_name": user.get("name", ""), "updated_at": _now()})
    return upd


async def _build_att_doc(db, body, user, prefetched_existing: dict = None):
    emp_id = body.get("employee_id")
    if not emp_id:
        return None
    date_str = body.get("date") or _today_iso()
    # Use prefetched map when available (bulk case), else fall back to DB lookup (single upsert case)
    if prefetched_existing is not None:
        existing = prefetched_existing.get((emp_id, date_str))
    else:
        existing = await db.rahaza_attendance_events.find_one(
            {"employee_id": emp_id, "date": date_str}, {"_id": 0})
    if existing:
        return await _build_att_patch(db, existing, body, user)
    status  = (body.get("status") or "hadir").lower()
    cin     = body.get("clock_in")
    cout    = body.get("clock_out")
    hours_override = body.get("hours_worked")
    if isinstance(cin, str) and cin:
        cin = _parse_iso(cin)
    if isinstance(cout, str) and cout:
        cout = _parse_iso(cout)
    hours = float(hours_override) if hours_override not in (None, "") else _calc_hours(cin, cout)
    ot = float(body.get("overtime_hours") or 0)

    # FASE 15 — KETERLAMBATAN & JAM BERSIH.
    # Sebelumnya record absensi TIDAK PERNAH menyimpan keterlambatan (tidak ada
    # `late_minutes`), sehingga kolom "POTONGAN TERLAMBAT" di sheet THP mustahil
    # diisi. Sekarang dihitung dari `clock_in` vs jam masuk shift + grace period.
    from utils.employee_identity import compute_late_minutes
    emp_doc = await db.rahaza_employees.find_one({"id": emp_id}, {"_id": 0}) or {}
    from core.attendance_rules import counts_timing, early_leave_fields
    late = await compute_late_minutes(db, emp_doc, cin if counts_timing({"status": status}) else None,
                                      body.get("shift_id"))
    late.update(await early_leave_fields(db, emp_doc, {"status": status, "date": date_str,
                                                       "shift_id": body.get("shift_id") or None}, cout))

    doc = {
        "employee_id": emp_id, "date": date_str,
        "shift_id": body.get("shift_id") or None,
        "clock_in": cin, "clock_out": cout,
        "hours_worked": round(max(0.0, hours), 2),
        "overtime_hours": round(max(0.0, ot), 2),
        **late,
        "status": status, "notes": body.get("notes") or "",
        "source": (body.get("source") or "supervisor").lower(),
        "updated_by": user["id"], "updated_by_name": user.get("name", ""),
        "updated_at": _now(),
    }
    # Jam BERSIH = jam kotor − istirahat − izin (record baru belum punya sesi keluar-masuk).
    from routes.rahaza_attendance_sessions import recompute_session_totals
    doc.update(recompute_session_totals({"sessions": [], "hours_worked": doc["hours_worked"]}))
    doc["id"] = _uid()
    doc["created_by"] = user["id"]
    doc["created_by_name"] = user.get("name", "")
    doc["created_at"] = _now()
    return doc


@router.post("/attendance")
async def upsert_attendance(request: Request):
    user = await require_auth(request)
    if not (check_role(user, HR_ATTENDANCE_WRITE_ROLES, "hr.manage") or lolos_centang(user)):
        raise HTTPException(403, MSG_HR_ATTENDANCE_ONLY)
    db = get_db()
    body = await request.json()
    from core.attendance_rules import ensure_not_locked, write_attendance_audit
    if body.get("employee_id"):
        await ensure_not_locked(db, body["employee_id"], body.get("date") or _today_iso())
    doc = await _build_att_doc(db, body, user)
    if not doc:
        raise HTTPException(400, "employee_id wajib.")
    existing = await db.rahaza_attendance_events.find_one({"employee_id": body["employee_id"], "date": body.get("date", _today_iso())}, {"_id": 0})
    if existing:
        await db.rahaza_attendance_events.update_one({"id": existing["id"]}, {"$set": doc})
        out = await db.rahaza_attendance_events.find_one({"id": existing["id"]}, {"_id": 0})
    else:
        await db.rahaza_attendance_events.insert_one(doc)
        out = doc
    await write_attendance_audit(db, before=existing or {}, after=out, user=user, source="manual",
                                 employee_id=body["employee_id"], day=body.get("date") or _today_iso())
    return serialize_doc(out)


# ─── HITUNG ULANG TERLAMBAT (2026-11-09, M13 audit HR) ────────────────────────
# Menit terlambat disimpan saat absen masuk. Jadwal/penugasan shift yang diubah belakangan, cuti yang disetujui
# sesudah karyawan absen, atau perbaikan aturan (H5: hari libur, cuti ½ hari) tidak memperbaiki catatan lama —
# dulu hanya bila HR mengubah status/shift/jam masuk baris itu satu per satu. Tombol ini menghitung ulang menit
# terlambat + pulang cepat seluruh catatan satu periode. Tanggal yang sudah masuk gaji FINAL dilewati (terkunci).
RECOMPUTE_MAX_DAYS = 62


@router.post("/attendance/recompute-timing")
async def recompute_timing(request: Request):
    """Body: {from, to, employee_ids?} → {checked, changed, locked, skipped_no_clock, samples}."""
    user = await require_auth(request)
    if not (check_role(user, HR_ATTENDANCE_WRITE_ROLES, ("hr.manage", "hr.attendance.manage")) or lolos_centang(user)):
        raise HTTPException(403, MSG_HR_ATTENDANCE_ONLY)
    db = get_db()
    body = await request.json()
    from datetime import date as _date
    try:
        d_from = _date.fromisoformat(str(body.get("from") or body.get("from_date") or "")[:10])
        d_to = _date.fromisoformat(str(body.get("to") or body.get("to_date") or "")[:10])
    except ValueError:
        raise HTTPException(400, "Isi periode (tanggal mulai dan selesai).")
    if d_to < d_from:
        raise HTTPException(400, "Tanggal selesai tidak boleh lebih awal dari tanggal mulai.")
    if (d_to - d_from).days + 1 > RECOMPUTE_MAX_DAYS:
        raise HTTPException(400, f"Periode paling panjang {RECOMPUTE_MAX_DAYS} hari.")
    q = {"date": {"$gte": d_from.isoformat(), "$lte": d_to.isoformat()}}
    ids = [str(i) for i in (body.get("employee_ids") or []) if i]
    if ids:
        q["employee_id"] = {"$in": ids}
    from core.attendance_rules import attendance_lock, timing_fields, write_attendance_audit
    rows = [r async for r in db.rahaza_attendance_events.find(q, {"_id": 0})]
    emp_ids = list({r.get("employee_id") for r in rows if r.get("employee_id")})
    emps = {e["id"]: e for e in await db.rahaza_employees.find(
        {"id": {"$in": emp_ids}}, {"_id": 0}).to_list(len(emp_ids) or 1)} if emp_ids else {}
    out = {"checked": 0, "changed": 0, "locked": 0, "skipped_no_clock": 0, "samples": []}
    lock_cache: dict = {}
    for r in sorted(rows, key=lambda x: (str(x.get("date")), str(x.get("employee_id")))):
        if not (r.get("clock_in") or r.get("clock_out")):
            out["skipped_no_clock"] += 1
            continue
        key = (r.get("employee_id"), str(r.get("date"))[:10])
        if key not in lock_cache:
            lock_cache[key] = await attendance_lock(db, *key)
        if lock_cache[key]:
            out["locked"] += 1
            continue
        out["checked"] += 1
        emp = emps.get(r.get("employee_id")) or {"id": r.get("employee_id")}
        new = await timing_fields(db, emp, r)
        if all((r.get(k) or 0) == (new.get(k) or 0) for k in ("late_minutes", "early_leave_minutes")):
            continue
        upd = {**new, "timing_recomputed_at": _now(), "updated_at": _now(), "updated_by": user["id"],
               "updated_by_name": user.get("name", "")}
        await db.rahaza_attendance_events.update_one({"id": r["id"]}, {"$set": upd})
        await write_attendance_audit(db, before=r, after={**r, **upd}, user=user, source="hitung_ulang",
                                     note="Hitung ulang terlambat & pulang cepat")
        out["changed"] += 1
        if len(out["samples"]) < 30:
            out["samples"].append({"employee_name": emp.get("name") or "", "date": key[1],
                                   "late_before": int(r.get("late_minutes") or 0),
                                   "late_after": int(new.get("late_minutes") or 0),
                                   "early_before": int(r.get("early_leave_minutes") or 0),
                                   "early_after": int(new.get("early_leave_minutes") or 0),
                                   "reason": new.get("late_reason") or new.get("early_leave_reason") or ""})
    out["message"] = (f"{out['changed']} catatan diperbarui dari {out['checked']} yang diperiksa"
                      + (f"; {out['locked']} catatan dilewati karena sudah masuk gaji final" if out["locked"] else "")
                      + ".")
    return out


@router.get("/attendance/summary")
async def attendance_summary(request: Request, from_: Optional[str] = None, to: Optional[str] = None, employee_id: Optional[str] = None):
    user = await require_auth(request)
    db = get_db()
    # 2026-11-09 (H8, audit HR): rekap hadir/izin/sakit/alpa SEMUA karyawan hanya untuk HR/atasan — dulu cukup
    # login (diuji: akun tim packing & PIC toko → 200). Selain itu hanya rekap milik sendiri (pola /attendance).
    from utils.employee_identity import can_view_all_employees, resolve_my_employee
    if not can_view_all_employees(user):
        mine = await resolve_my_employee(db, user)
        if not mine or (employee_id and employee_id != mine["id"]):
            return []
        employee_id = mine["id"]
    q = {}
    if from_ or to:
        rg = {}
        if from_:
            rg["$gte"] = from_
        if to:
            rg["$lte"] = to
        q["date"] = rg
    if employee_id:
        q["employee_id"] = employee_id
    # 2026-11-06 (pola P7): semua record periode (dulu to_list(500) — rekap sebulan 25 karyawan = 650 record)
    rows = [r async for r in db.rahaza_attendance_events.find(
        q, {"_id": 0, "employee_id": 1, "status": 1, "approval_status": 1, "hours_worked": 1, "overtime_hours": 1,
            "late_minutes": 1, "early_leave_minutes": 1, "half_day": 1, "tugas_luar": 1})]
    from utils.attendance_policy import attendance_counts
    from routes.rahaza_payroll_rules import timing_counts
    summary = {}
    for r in rows:
        eid = r["employee_id"]
        # 2026-11-09 (Q3): rekap memuat menit terlambat & PULANG CEPAT (dicatat, tidak memotong) + hari tugas luar.
        s = summary.setdefault(eid, {"employee_id": eid, "days_hadir": 0, "days_izin": 0, "days_sakit": 0, "days_alfa": 0, "days_cuti": 0, "days_libur": 0, "total_hours": 0, "total_overtime": 0,
                                     "total_late_minutes": 0, "days_late": 0, "total_early_leave_minutes": 0,
                                     "days_early_leave": 0, "days_tugas_luar": 0})
        if r.get("tugas_luar"):
            s["days_tugas_luar"] += 1
        if timing_counts(r, counts=attendance_counts):
            lm, em = int(r.get("late_minutes") or 0), int(r.get("early_leave_minutes") or 0)
            s["total_late_minutes"] += lm
            s["days_late"] += 1 if lm > 0 else 0
            s["total_early_leave_minutes"] += em
            s["days_early_leave"] += 1 if em > 0 else 0
        from core.attendance_rules import is_absent
        st = r.get('status', 'hadir')
        k = "days_alfa" if is_absent(st) else f"days_{st}"   # Tahap 2: 'alpa' (kontrak) & 'alfa' (lama)
        if k in s:
            s[k] += 1
        if not attendance_counts(r):   # Tahap 1: selfie ditolak HR = alfa, jamnya tidak dihitung
            continue
        s["total_hours"]    += float(r.get("hours_worked") or 0)
        s["total_overtime"] += float(r.get("overtime_hours") or 0)
    eids = list(summary.keys())
    emps = await db.rahaza_employees.find({"id": {"$in": eids}}, {"_id": 0}).to_list(500) if eids else []
    e_map = {e["id"]: e for e in emps}
    out = []
    for eid, s in summary.items():
        e = e_map.get(eid, {})
        s["employee_name"] = e.get("name", "?")
        s["employee_code"] = e.get("employee_code", "-")
        out.append(s)
    return serialize_doc(out)


@router.get("/attendance/my-today")
async def my_today(request: Request, employee_id: Optional[str] = None):
    user = await require_auth(request)
    db = get_db()
    # 2026-11-07 (Tahap 7): dulu `employee_id` dari klien tanpa cek pemilik. Kosong → karyawan sendiri;
    # karyawan lain hanya HR/atasan (SSOT resolve_employee_for).
    from utils.employee_identity import resolve_employee_for
    employee_id = (await resolve_employee_for(db, user, employee_id))["id"]
    d = _today_iso()
    rec = await db.rahaza_attendance_events.find_one({"employee_id": employee_id, "date": d}, {"_id": 0})
    if not rec:
        return {"date": d, "employee_id": employee_id, "status": None, "has_clock_in": False, "has_clock_out": False, "record": None}
    return {
        "date": d, "employee_id": employee_id,
        "status": rec.get("status"),
        "has_clock_in": bool(rec.get("clock_in")),
        "has_clock_out": bool(rec.get("clock_out")),
        "record": serialize_doc(rec),
    }


# ─── HR DASHBOARD (Sprint 1.2) ────────────────────────────────────────────────

@router.get("/hr/dashboard")
async def hr_dashboard(request: Request):
    """
    Real HR KPI dashboard (replaces HRDashboardPlaceholder).
    Returns:
      - total_employees: jumlah karyawan aktif
      - attendance_today: breakdown status untuk hari ini
      - latest_payroll_run: run terbaru (periode, status, total payout)
      - alfa_last_7d: total alfa dalam 7 hari terakhir
      - attendance_trend: hadir count per hari (7 hari terakhir)
      - recent_attendance: 10 record attendance terbaru

    2026-11-09 (H8): hanya HR/atasan (dulu akun mana pun, termasuk total gaji bersih run terakhir). Total gaji
    run terakhir hanya untuk peran penggajian/Keuangan (Q8); peran SDM lain melihat periode & statusnya saja.
    """
    user = await require_auth(request)
    from utils.employee_identity import can_view_all_employees
    if not can_view_all_employees(user):
        raise HTTPException(403, "Dasbor SDM hanya untuk HR dan atasan.")
    db = get_db()
    today = _today_iso()
    from_7d = (today_wib() - timedelta(days=6)).isoformat()

    # ── Total active employees
    total_employees = await db.rahaza_employees.count_documents({"active": True})

    # ── Attendance today: breakdown by status
    att_today = await db.rahaza_attendance_events.find(
        {"date": today}, {"_id": 0, "status": 1, "employee_id": 1}
    ).to_list(500)
    breakdown = {"hadir": 0, "izin": 0, "sakit": 0, "alfa": 0, "cuti": 0, "libur": 0}
    from core.attendance_rules import ABSENT_ALIASES, is_absent
    for a in att_today:
        k = "alfa" if is_absent(a.get("status")) else a.get("status", "hadir")
        if k in breakdown:
            breakdown[k] += 1
        else:
            breakdown["hadir"] += 1
    recorded_today = len(att_today)
    not_recorded = max(0, total_employees - recorded_today)

    # ── Latest payroll run
    latest_run = await db.rahaza_payroll_runs.find_one(
        {}, {"_id": 0, "id": 1, "period_from": 1, "period_to": 1,
             "status": 1, "total_net": 1, "total_employees": 1, "employee_count": 1, "created_at": 1},  # FIX: total_net not total_payout
        sort=[("created_at", -1)]
    )

    from routes.rahaza_payroll_shared import can_view_payroll_transfer
    if latest_run and not can_view_payroll_transfer(user):
        latest_run = {k: v for k, v in latest_run.items() if k != "total_net"}

    # ── Alfa last 7 days
    alfa_last_7d = await db.rahaza_attendance_events.count_documents(
        {"status": {"$in": list(ABSENT_ALIASES)}, "date": {"$gte": from_7d}}
    )

    # ── Attendance trend last 7 days (hadir per day)
    trend_pipeline = [
        {"$match": {"date": {"$gte": from_7d}, "status": "hadir"}},
        {"$group": {"_id": "$date", "hadir": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    trend_raw = await db.rahaza_attendance_events.aggregate(trend_pipeline).to_list(500)
    trend = [{"date": t["_id"], "hadir": t["hadir"]} for t in trend_raw]

    # ── Recent attendance (last 10 records, enriched)
    recent = await db.rahaza_attendance_events.find(
        {}, {"_id": 0, "employee_id": 1, "date": 1, "status": 1, "clock_in": 1, "clock_out": 1, "hours_worked": 1}
    ).sort("created_at", -1).limit(10).to_list(500)
    await _enrich(db, recent)

    # ── Gender/department breakdown (from employees)
    dept_pipeline = [
        {"$match": {"active": True}},
        {"$group": {"_id": {"$ifNull": ["$department", "$role", "Lainnya"]}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 8},
    ]
    dept_breakdown = await db.rahaza_employees.aggregate(dept_pipeline).to_list(500)

    return serialize_doc({
        "total_employees": total_employees,
        "attendance_today": {
            **breakdown,
            "recorded": recorded_today,
            "not_recorded": not_recorded,
            "attendance_rate": round((breakdown["hadir"] / total_employees * 100), 1) if total_employees > 0 else 0,
        },
        "latest_payroll_run": latest_run,
        "alfa_last_7d": alfa_last_7d,
        "attendance_trend": trend,
        "recent_attendance": recent,
        "dept_breakdown": [{"dept": d["_id"], "count": d["count"]} for d in dept_breakdown],
    })

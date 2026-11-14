"""Koreksi absen, tanda lembur dibayar, dan jejak perubahan absensi (2026-11-06, Tahap 2 paket absen).

Endpoint (prefix /api/rahaza, dipasang lewat routes/rahaza_auto_attendance.py):
  Portal Saya (karyawan)
    GET  /attendance/corrections/my               — pengajuan koreksi milik saya
    POST /attendance/corrections                  — "Ajukan koreksi absen" {date, status?, clock_in?, clock_out?,
                                                    reason, attachment_url?}
    POST /attendance/corrections/{id}/cancel      — tarik pengajuan yang masih menunggu
  HR
    GET  /attendance/corrections                  — daftar (status=pending|approved|rejected|all)
    POST /attendance/corrections/{id}/approve     — tanggal terbuka: langsung diterapkan ke absensi;
                                                    tanggal TERKUNCI gaji final: diteruskan ke payroll sebagai
                                                    penyesuaian di run berikutnya (absensi tidak diubah)
    POST /attendance/corrections/{id}/reject
    POST /attendance/events/{id}/overtime-paid    — HR menandai lembur tanpa pengajuan dibayar / tidak
    GET  /attendance/audit                        — jejak perubahan absensi (siapa, kapan, sebelum → sesudah)

Koleksi `rahaza_attendance_corrections` — bentuk yang dibaca paket payroll untuk penyesuaian:
  {id, employee_id, date, requested: {status?, clock_in?, clock_out?}, reason, attachment_url,
   status: pending|approved|rejected|cancelled, apply_mode: langsung|penyesuaian_payroll,
   locked_run_id, locked_run_number, current: {status, clock_in, clock_out, hours_worked} (saat disetujui),
   payroll_adjustment: {status: 'pending'|'applied', run_id, applied_at} (hanya penyesuaian_payroll)}
"""
from __future__ import annotations
from routes.shared import lolos_centang  # 14 Nov 2026 (tahap 2): centang owner dihormati

import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from auth import log_activity, require_auth, serialize_doc
from core.authz import izin_atau_peran_lama  # 14 Nov 2026: centang owner = penentu
from core.attendance_rules import (ATTENDANCE_STATUSES, attendance_lock, ensure_not_locked,
                                   write_attendance_audit)
from core.roles import HR_ROLES
from database import get_db
from utils.waktu import WIB, today_wib

router = APIRouter(tags=["rahaza-attendance-corrections"])

HR_CORRECTION_ROLES = ["admin", *HR_ROLES]
CORRECTION_STATUSES = ("pending", "approved", "rejected", "cancelled")
MSG_HR_ONLY = "Hanya HR dan manajemen yang boleh memproses koreksi absen."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_hr(user: dict) -> None:
    if lolos_centang(user):  # 14 Nov 2026 (tahap 2): centang owner dihormati
        return user
    if not (izin_atau_peran_lama(user, HR_CORRECTION_ROLES, "hr.manage") or lolos_centang(user)):
        raise HTTPException(403, MSG_HR_ONLY)


def _hhmm(v) -> Optional[time]:
    s = str(v or "").strip()
    if not s:
        return None
    try:
        hh, mm = (int(x) for x in s.split(":")[:2])
        return time(hh, mm)
    except (ValueError, TypeError):
        raise HTTPException(400, f"Jam '{s}' tidak valid. Gunakan format JJ:MM, mis. 08:05.")


def _instant(day: str, t: time) -> datetime:
    return datetime.combine(date.fromisoformat(day), t, tzinfo=WIB).astimezone(timezone.utc)


def requested_to_patch(day: str, requested: dict) -> dict:
    """Isian koreksi (jam lokal JJ:MM) → kolom absensi. Jam pulang < jam masuk = lewat tengah malam."""
    body: dict = {}
    if requested.get("status"):
        body["status"] = requested["status"]
    cin = _hhmm(requested.get("clock_in"))
    cout = _hhmm(requested.get("clock_out"))
    if cin:
        body["clock_in"] = _instant(day, cin).isoformat()
    if cout:
        out = _instant(day, cout)
        if cin and cout <= cin:
            out += timedelta(days=1)
        body["clock_out"] = out.isoformat()
    return body


async def _employee_for(db, user: dict) -> dict:
    from utils.employee_identity import require_my_employee
    return await require_my_employee(db, user)


# ── Portal Saya ─────────────────────────────────────────────────────────────
@router.get("/attendance/corrections/my")
async def my_corrections(request: Request, limit: int = 50):
    user = await require_auth(request)
    db = get_db()
    emp = await _employee_for(db, user)
    rows = await db.rahaza_attendance_corrections.find(
        {"employee_id": emp["id"]}, {"_id": 0}).sort("created_at", -1).limit(min(max(limit, 1), 200)).to_list(200)
    return {"items": serialize_doc(rows)}


@router.post("/attendance/corrections")
async def create_correction(request: Request):
    """Karyawan mengajukan koreksi absen untuk dirinya sendiri (HR boleh atas nama karyawan)."""
    user = await require_auth(request)
    db = get_db()
    body = await request.json()
    from utils.employee_identity import resolve_employee_for
    emp = await resolve_employee_for(db, user, body.get("employee_id"))
    day = str(body.get("date") or "").strip()[:10]
    try:
        d = date.fromisoformat(day)
    except ValueError:
        raise HTTPException(400, "Tanggal koreksi wajib diisi (YYYY-MM-DD).")
    if d > today_wib():
        raise HTTPException(400, "Koreksi hanya untuk tanggal hari ini atau sebelumnya.")
    reason = (body.get("reason") or "").strip()
    if not reason:
        raise HTTPException(400, "Alasan koreksi wajib diisi.")
    status = (body.get("status") or "").strip().lower() or None
    if status and status not in ATTENDANCE_STATUSES:
        raise HTTPException(400, "Status koreksi tidak dikenal.")
    if status in ("cuti", "izin", "sakit"):
        raise HTTPException(400, "Cuti, izin, dan sakit diajukan lewat menu Cuti & Lembur, bukan koreksi absen.")
    requested = {"status": status, "clock_in": (body.get("clock_in") or "").strip() or None,
                 "clock_out": (body.get("clock_out") or "").strip() or None}
    if not any(requested.values()):
        raise HTTPException(400, "Isi jam masuk, jam pulang, atau status yang benar.")
    requested_to_patch(day, requested)   # validasi format jam
    dup = await db.rahaza_attendance_corrections.find_one(
        {"employee_id": emp["id"], "date": day, "status": "pending"}, {"_id": 0, "id": 1})
    if dup:
        raise HTTPException(409, "Masih ada pengajuan koreksi untuk tanggal ini yang menunggu HR.")
    current = await db.rahaza_attendance_events.find_one({"employee_id": emp["id"], "date": day}, {"_id": 0})
    lock = await attendance_lock(db, emp["id"], day)
    now = _now()
    doc = {
        "id": str(uuid.uuid4()), "employee_id": emp["id"], "date": day, "requested": requested,
        "reason": reason, "attachment_url": body.get("attachment_url") or "",
        "attachment_filename": body.get("attachment_filename") or "",
        "event_id": (current or {}).get("id"),
        "current": {k: (current or {}).get(k) for k in ("status", "clock_in", "clock_out", "hours_worked")},
        "locked_at_request": bool(lock), "status": "pending",
        "created_by": user["id"], "created_by_name": user.get("name", ""), "created_at": now, "updated_at": now,
    }
    await db.rahaza_attendance_corrections.insert_one(dict(doc))
    await log_activity(user["id"], user.get("name", ""), "create", "rahaza.attendance_correction", doc["id"])
    return serialize_doc(doc)


@router.post("/attendance/corrections/{corr_id}/cancel")
async def cancel_correction(corr_id: str, request: Request):
    user = await require_auth(request)
    db = get_db()
    doc = await db.rahaza_attendance_corrections.find_one({"id": corr_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Pengajuan koreksi tidak ditemukan.")
    from utils.employee_identity import is_hr, resolve_my_employee
    mine = await resolve_my_employee(db, user)
    if not (is_hr(user) or (mine and mine.get("id") == doc.get("employee_id"))):
        raise HTTPException(403, "Hanya pemohon atau HR yang boleh menarik pengajuan ini.")
    if doc.get("status") != "pending":
        raise HTTPException(400, "Hanya pengajuan yang menunggu yang bisa ditarik.")
    res = await db.rahaza_attendance_corrections.update_one({"id": corr_id, "status": "pending"}, {"$set": {
        "status": "cancelled", "cancelled_by": user["id"], "cancelled_at": _now(), "updated_at": _now()}})
    if not res.matched_count:   # 2026-11-06 (pola P9)
        raise HTTPException(409, "Pengajuan koreksi ini baru saja diputuskan orang lain — muat ulang halaman.")
    return {"ok": True}


# ── HR ──────────────────────────────────────────────────────────────────────
async def _enrich(db, rows: list) -> list:
    ids = list({r.get("employee_id") for r in rows if r.get("employee_id")})
    emps = await db.rahaza_employees.find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "name": 1,
                                                                 "employee_code": 1}).to_list(500) if ids else []
    m = {e["id"]: e for e in emps}
    for r in rows:
        e = m.get(r.get("employee_id")) or {}
        r["employee_name"], r["employee_code"] = e.get("name"), e.get("employee_code")
    return rows


@router.get("/attendance/corrections")
async def list_corrections(request: Request, status: Optional[str] = "pending", employee_id: Optional[str] = None,
                           limit: int = 100):
    user = await require_auth(request)
    _require_hr(user)
    db = get_db()
    q: dict = {}
    if status and status != "all":
        if status not in CORRECTION_STATUSES:
            raise HTTPException(400, "Status tidak dikenal.")
        q["status"] = status
    if employee_id:
        q["employee_id"] = employee_id
    rows = await db.rahaza_attendance_corrections.find(q, {"_id": 0}).sort("created_at", -1).limit(
        min(max(limit, 1), 500)).to_list(500)
    return {"items": serialize_doc(await _enrich(db, rows))}


async def inbox_items(db, limit: int) -> list:
    """Bentuk item Kotak Masuk SDM (routes/hr_approval_inbox.py)."""
    rows = await db.rahaza_attendance_corrections.find({"status": "pending"}, {"_id": 0}).sort(
        "created_at", -1).limit(limit).to_list(limit)
    rows = await _enrich(db, rows)
    out = []
    for r in rows:
        req = r.get("requested") or {}
        parts = [f"masuk {req['clock_in']}" if req.get("clock_in") else "",
                 f"pulang {req['clock_out']}" if req.get("clock_out") else "",
                 f"status {req['status']}" if req.get("status") else ""]
        created = r.get("created_at")
        created = created.isoformat() if isinstance(created, datetime) else created
        out.append({
            "id": r["id"], "type": "attendance_correction", "type_label": "Koreksi Absen",
            "created_at": created, "submitted_at": created,
            "requester_id": r.get("employee_id"), "requester_name": r.get("employee_name"),
            "requester_code": r.get("employee_code"), "requester_dept": None,
            "title": f"Koreksi absen {r.get('date')} — " + ", ".join(p for p in parts if p),
            "period": r.get("date"), "reason": r.get("reason", ""), "amount": None,
            "meta": {"date": r.get("date"), "requested": req, "current": r.get("current"),
                     "attachment_url": r.get("attachment_url"),
                     "locked": bool(await attendance_lock(db, r.get("employee_id"), r.get("date")))},
            "raw": serialize_doc(r),
        })
    return out


async def decide_correction(db, corr_id: str, user: dict, *, approve: bool, note: str = "") -> dict:
    """SATU fungsi keputusan koreksi (layar Absensi HR & Kotak Masuk SDM)."""
    doc = await db.rahaza_attendance_corrections.find_one({"id": corr_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Pengajuan koreksi tidak ditemukan.")
    if doc.get("status") != "pending":
        raise HTTPException(400, "Pengajuan ini sudah diputuskan.")
    from utils.employee_identity import resolve_my_employee
    mine = await resolve_my_employee(db, user)
    if mine and mine.get("id") == doc.get("employee_id"):
        raise HTTPException(403, "Pemisahan tugas: koreksi absen milik Anda sendiri harus diputus HR lain.")
    now = _now()
    decided = {"decided_by": user.get("id"), "decided_by_name": user.get("name", ""), "decided_at": now,
               "decision_note": note or "", "updated_at": now}
    if not approve:
        if not (note or "").strip():
            raise HTTPException(400, "Alasan penolakan wajib diisi.")
        res = await db.rahaza_attendance_corrections.update_one({"id": corr_id, "status": "pending"},
                                                                {"$set": {"status": "rejected", **decided}})
        if not res.matched_count:   # 2026-11-06 (pola P9)
            raise HTTPException(409, "Pengajuan koreksi ini baru saja diputuskan orang lain — muat ulang halaman.")
        out = {**doc, "status": "rejected", **decided}
        await notify_correction_decision(db, out, approved=False)
        return out

    # 2026-11-06 (pola P9): klaim atomik pending → deciding SEBELUM absensi ditulis. Dulu Setuju ganda /
    # setuju-tolak bersamaan sama-sama lolos: absensi ditulis dua kali (atau sisipan kedua gagal di
    # indeks unik) dan keputusan saling menimpa.
    claim = await db.rahaza_attendance_corrections.update_one({"id": corr_id, "status": "pending"},
                                                              {"$set": {"status": "deciding", "updated_at": now}})
    if not claim.matched_count:
        raise HTTPException(409, "Pengajuan koreksi ini baru saja diputuskan orang lain — muat ulang halaman.")
    try:
        out = await _approve_correction_claimed(db, corr_id, doc, user, decided)
    except BaseException:
        await db.rahaza_attendance_corrections.update_one({"id": corr_id, "status": "deciding"},
                                                          {"$set": {"status": "pending"}})
        raise
    await notify_correction_decision(db, out, approved=True)
    return out


async def notify_correction_decision(db, doc: dict, *, approved: bool) -> None:
    """Kabar keputusan koreksi absen ke karyawan (tautan Portal Saya › Absen Saya) — 2026-11-07 (Tahap 7).
    Dulu koreksi diputus tanpa kabar apa pun (cuti, lembur, kasbon, izin keluar sudah mengabari). Tidak raise."""
    from routes.rahaza_payroll_shared import notify_requester
    from utils.employee_identity import employee_user_ids
    try:
        uids = await employee_user_ids(db, doc.get("employee_id"))
    except Exception:  # noqa: BLE001 — kabar tidak boleh menggagalkan keputusan
        uids = []
    if not uids and doc.get("created_by"):
        uids = [doc["created_by"]]
    day = doc.get("date")
    if approved:
        later = doc.get("apply_mode") == "penyesuaian_payroll"
        title = f"Koreksi absen {day} disetujui"
        body = (f"Koreksi absen tanggal {day} disetujui HR. "
                + ("Tanggal ini sudah digaji final — selisihnya dibayar di penggajian berikutnya."
                   if later else "Absensi Anda sudah diperbarui."))
    else:
        title = f"Koreksi absen {day} ditolak"
        body = f"Koreksi absen tanggal {day} ditolak HR. Alasan: {doc.get('decision_note') or '-'}."
    for uid in uids:
        await notify_requester(
            db, user_id=uid, subtype="attendance_correction_approved" if approved else "attendance_correction_rejected",
            severity="success" if approved else "warning", title=title, body=body, link_module="portal-absen",
            source_type="attendance_correction", source_id=doc.get("id"))


async def _approve_correction_claimed(db, corr_id: str, doc: dict, user: dict, decided: dict) -> dict:

    day, emp_id = doc["date"], doc["employee_id"]
    existing = await db.rahaza_attendance_events.find_one({"employee_id": emp_id, "date": day}, {"_id": 0})
    current = {k: (existing or {}).get(k) for k in ("status", "clock_in", "clock_out", "hours_worked")}
    lock = await attendance_lock(db, emp_id, day)
    if lock:
        # Tanggal sudah dibayar di run final → absensi TIDAK diubah; payroll menerapkannya sebagai penyesuaian
        # di run berikutnya (kontrak paket payroll, lihat docstring modul).
        upd = {"status": "approved", "apply_mode": "penyesuaian_payroll", "current": current,
               "locked_run_id": lock.get("run_id"), "locked_run_number": lock.get("run_number"),
               "payroll_adjustment": {"status": "pending", "run_id": None, "applied_at": None}, **decided}
        await db.rahaza_attendance_corrections.update_one({"id": corr_id, "status": "deciding"}, {"$set": upd})
        return {**doc, **upd}

    from routes.rahaza_attendance import _build_att_doc, _build_att_patch
    from core.attendance_rules import is_absent
    body = {"employee_id": emp_id, "date": day, **requested_to_patch(day, doc.get("requested") or {})}
    # Koreksi jam masuk pada hari tanpa record / alpa berarti karyawan hadir (status lain tidak diubah).
    if "clock_in" in body and "status" not in body and (not existing or not existing.get("status")
                                                          or is_absent(existing.get("status"))):
        body["status"] = "hadir"
    if existing:
        patch = await _build_att_patch(db, existing, body, user)
        patch["correction_id"] = corr_id
        await db.rahaza_attendance_events.update_one({"id": existing["id"]}, {"$set": patch})
        after = {**existing, **patch}
    else:
        after = await _build_att_doc(db, {**body, "source": "koreksi"}, user)
        after["correction_id"] = corr_id
        await db.rahaza_attendance_events.insert_one(dict(after))
    await write_attendance_audit(db, before=existing or {}, after=after, user=user, source="koreksi",
                                 employee_id=emp_id, day=day, note=f"Koreksi disetujui: {doc.get('reason', '')}")
    upd = {"status": "approved", "apply_mode": "langsung", "current": current, "event_id": after.get("id"),
           **decided}
    await db.rahaza_attendance_corrections.update_one({"id": corr_id, "status": "deciding"}, {"$set": upd})
    return {**doc, **upd}


@router.post("/attendance/corrections/{corr_id}/approve")
async def approve_correction(corr_id: str, request: Request):
    user = await require_auth(request)
    _require_hr(user)
    db = get_db()
    body = await request.json()
    out = await decide_correction(db, corr_id, user, approve=True, note=body.get("note") or "")
    await log_activity(user["id"], user.get("name", ""), "approve", "rahaza.attendance_correction", corr_id)
    msg = ("Koreksi disetujui. Tanggal ini sudah masuk gaji final — selisihnya diteruskan ke penggajian "
           "berikutnya sebagai penyesuaian." if out.get("apply_mode") == "penyesuaian_payroll"
           else "Koreksi disetujui dan absensi sudah diperbarui.")
    return {"ok": True, "correction": serialize_doc(out), "message": msg}


@router.post("/attendance/corrections/{corr_id}/reject")
async def reject_correction(corr_id: str, request: Request):
    user = await require_auth(request)
    _require_hr(user)
    db = get_db()
    body = await request.json()
    out = await decide_correction(db, corr_id, user, approve=False,
                                  note=(body.get("note") or body.get("reason") or ""))
    await log_activity(user["id"], user.get("name", ""), "reject", "rahaza.attendance_correction", corr_id)
    return {"ok": True, "correction": serialize_doc(out)}


# ── Lembur tanpa pengajuan: HR menandai dibayar / tidak ─────────────────────
@router.post("/attendance/events/{event_id}/overtime-paid")
async def mark_overtime_paid(event_id: str, request: Request):
    """Kontrak payroll: `overtime_hours` sehari dibayar hanya bila ada pengajuan lembur disetujui untuk hari itu,
    atau HR menandai `overtime_paid: true` di sini (dicatat `overtime_paid_by` & `overtime_paid_at`)."""
    user = await require_auth(request)
    _require_hr(user)
    db = get_db()
    body = await request.json()
    ev = await db.rahaza_attendance_events.find_one({"id": event_id}, {"_id": 0})
    if not ev:
        raise HTTPException(404, "Record absen tidak ditemukan.")
    if float(ev.get("overtime_hours") or 0) <= 0:
        raise HTTPException(400, "Hari ini tidak punya jam lembur. Isi jam lembur dulu di grid absensi.")
    approved = await db.rahaza_overtime_requests.find_one(
        {"employee_id": ev.get("employee_id"), "date": ev.get("date"), "status": "approved"}, {"_id": 0, "id": 1})
    if approved:
        raise HTTPException(400, "Lembur hari ini sudah tercakup pengajuan lembur yang disetujui; "
                                 "tidak perlu ditandai lagi.")
    await ensure_not_locked(db, ev.get("employee_id"), ev.get("date"))
    paid = bool(body.get("paid"))
    now = _now()
    upd = {"overtime_paid": paid, "overtime_paid_by": user["id"], "overtime_paid_by_name": user.get("name", ""),
           "overtime_paid_at": now, "overtime_paid_note": (body.get("note") or "").strip(),
           "updated_by": user["id"], "updated_by_name": user.get("name", ""), "updated_at": now}
    await db.rahaza_attendance_events.update_one({"id": event_id}, {"$set": upd})
    await write_attendance_audit(db, before=ev, after={**ev, **upd}, user=user, source="lembur_dibayar",
                                 note=upd["overtime_paid_note"])
    return {"ok": True, "overtime_paid": paid}


# ── Jejak perubahan ─────────────────────────────────────────────────────────
@router.get("/attendance/audit")
async def attendance_audit(request: Request, employee_id: Optional[str] = None,
                           day: Optional[str] = Query(None, alias="date"),
                           event_id: Optional[str] = None, limit: int = 50):
    user = await require_auth(request)
    _require_hr(user)
    db = get_db()
    q: dict = {}
    if event_id:
        q["event_id"] = event_id
    if employee_id:
        q["employee_id"] = employee_id
    if day:
        q["date"] = str(day)[:10]
    if not q:
        raise HTTPException(400, "Pilih karyawan, tanggal, atau record absen.")
    rows = await db.rahaza_attendance_audit.find(q, {"_id": 0}).sort("changed_at", -1).limit(
        min(max(limit, 1), 200)).to_list(200)
    return {"items": serialize_doc(rows)}

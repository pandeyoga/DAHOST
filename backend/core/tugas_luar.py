"""Dinas / tugas luar → absensi "hadir (tugas luar)" — 2026-11-09 (Q11, keputusan owner "ikuti rekomendasi").

Masalah (audit HR M15): pengajuan perjalanan dinas (`employee_travel_requests`) tidak pernah menulis absensi,
sedangkan absen selfie wajib di dalam geofence kantor → karyawan yang dinas tidak bisa absen dan harinya
"tanpa catatan" (bonus/rekap salah, terlambat dihitung bila ia absen di tempat tujuan).

Aturan:
  · Dinas DISETUJUI → setiap HARI KERJA (core.workdays) di rentang dinas ditulis `status: hadir`,
    `tugas_luar: True`, `duty_travel_id`, tanpa geofence. Jam absen yang sudah ada tetap disimpan; keadaan
    sebelumnya disimpan di `pre_duty` supaya pembatalan mengembalikannya.
  · Hari yang sudah tercatat cuti/izin/sakit DISETUJUI atau sudah masuk gaji final dilewati (dicatat di hasil).
  · Menit terlambat / pulang cepat hari tugas luar = 0 (`utils.employee_identity._zero_reason`).
  · Dinas ditolak sesudah disetujui → absensinya dikembalikan (`restore_duty_days`).
Satu modul untuk dua jalur persetujuan (layar Dinas `routes.employee_travel_requests` dan Kotak Masuk SDM).
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from core import attendance_rules as ar
from core import workdays

log = logging.getLogger(__name__)

DUTY_SNAPSHOT = ("status", "notes", "tugas_luar", "duty_travel_id")
CLEAR_DUTY = {"tugas_luar": None, "duty_travel_id": None, "duty_note": None, "pre_duty": None}


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def duty_employee(db, travel: dict) -> Optional[dict]:
    """Karyawan pemilik dinas. `employee_travel_requests.employee_id` = id AKUN login (bukan id karyawan) —
    dipetakan lewat SSOT identitas; dokumen lama yang menyimpan id karyawan tetap terbaca."""
    from utils.employee_identity import resolve_my_employee
    acc = travel.get("employee_id") or travel.get("created_by")
    if not acc:
        return None
    emp = await db.rahaza_employees.find_one({"id": acc}, {"_id": 0})
    if emp:
        return emp
    user = await db.users.find_one({"id": acc}, {"_id": 0}) or {"id": acc}
    return await resolve_my_employee(db, user)


async def duty_days(db, travel: dict) -> list:
    try:
        d_from = date.fromisoformat(str(travel.get("start_date"))[:10])
        d_to = date.fromisoformat(str(travel.get("end_date") or travel.get("start_date"))[:10])
    except (TypeError, ValueError):
        return []
    if d_to < d_from or (d_to - d_from).days > 92:
        return []
    return [d.isoformat() for d in await workdays.working_days(db, d_from, d_to)]


async def write_duty_days(db, travel: dict, user: dict) -> dict:
    """Tulis absensi tugas luar untuk dinas yang baru DISETUJUI. Tidak pernah raise (persetujuan tetap sah)."""
    out = {"created": 0, "updated": 0, "skipped": []}
    try:
        emp = await duty_employee(db, travel)
        if not emp:
            out["skipped"].append({"reason": "akun pemohon belum tertaut ke data karyawan"})
            return out
        note = f"Tugas luar: {travel.get('destination') or '-'} ({travel.get('trip_number') or travel.get('id')})"
        now = _now()
        for d in await duty_days(db, travel):
            if await ar.attendance_lock(db, emp["id"], d):
                out["skipped"].append({"date": d, "reason": "sudah masuk gaji final"})
                continue
            existing = await db.rahaza_attendance_events.find_one({"employee_id": emp["id"], "date": d}, {"_id": 0})
            fields = {"tugas_luar": True, "duty_travel_id": travel.get("id"), "duty_note": note,
                      "updated_at": now, "updated_by": user.get("id"), "updated_by_name": user.get("name", "")}
            if existing:
                if existing.get("leave_request_id"):
                    out["skipped"].append({"date": d, "reason": "sudah tercatat cuti/izin"})
                    continue
                if existing.get("duty_travel_id") not in (None, travel.get("id")):
                    out["skipped"].append({"date": d, "reason": "sudah tercatat tugas luar lain"})
                    continue
                if existing.get("duty_travel_id") != travel.get("id"):
                    fields["pre_duty"] = {k: existing.get(k) for k in DUTY_SNAPSHOT}
                fields["status"] = "hadir"
                fields.update({"late_minutes": 0, "is_late": False, "late_reason": "tugas luar",
                               "early_leave_minutes": 0, "early_leave_reason": "tugas luar"})
                await db.rahaza_attendance_events.update_one({"id": existing["id"]}, {"$set": fields})
                await ar.write_attendance_audit(db, before=existing, after={**existing, **fields}, user=user,
                                                source="tugas_luar", note=note)
                out["updated"] += 1
            else:
                doc = {"id": str(uuid.uuid4()), "employee_id": emp["id"], "date": d, "status": "hadir",
                       "clock_in": None, "clock_out": None, "hours_worked": 0, "overtime_hours": 0,
                       "late_minutes": 0, "early_leave_minutes": 0, "notes": note, "source": "tugas_luar",
                       "created_by_duty": True, "approval_status": "auto_approved",
                       "created_by": user.get("id"), "created_by_name": user.get("name", ""), "created_at": now,
                       **fields}
                await db.rahaza_attendance_events.insert_one(doc)
                out["created"] += 1
        await db.employee_travel_requests.update_one({"id": travel.get("id")}, {"$set": {"attendance_written": out}})
    except Exception as e:  # noqa: BLE001 — absensi gagal ditulis tidak membatalkan persetujuan dinas
        log.exception("[tugas_luar] absensi dinas %s gagal ditulis", travel.get("id"))
        out["error"] = str(e)
    return out


async def restore_duty_days(db, travel: dict, user: dict) -> dict:
    """Dinas ditolak/dibatalkan sesudah disetujui → absensi tugas luar dikembalikan ke keadaan sebelumnya."""
    out = {"restored": 0, "deleted": 0, "locked": 0}
    try:
        rows = await db.rahaza_attendance_events.find({"duty_travel_id": travel.get("id")}, {"_id": 0}).to_list(400)
        emp = await duty_employee(db, travel) or {}
        for r in rows:
            if await ar.attendance_lock(db, r.get("employee_id"), r.get("date")):
                out["locked"] += 1
                continue
            own = bool(r.get("clock_in") or r.get("clock_out") or r.get("sessions") or r.get("photo_selfie_url"))
            if r.get("created_by_duty") and not own:
                await db.rahaza_attendance_events.delete_one({"id": r["id"], "duty_travel_id": travel.get("id")})
                out["deleted"] += 1
                continue
            snap = r.get("pre_duty") or {}
            upd = {**CLEAR_DUTY, "status": snap.get("status") or ("hadir" if r.get("clock_in") else "alpa"),
                   "updated_at": _now(), "updated_by": user.get("id"), "updated_by_name": user.get("name", "")}
            await db.rahaza_attendance_events.update_one({"id": r["id"]}, {"$set": upd})
            if r.get("clock_in") or r.get("clock_out"):
                upd.update(await ar.timing_fields(db, emp or {"id": r.get("employee_id")}, {**r, **upd}))
                await db.rahaza_attendance_events.update_one({"id": r["id"]}, {"$set": upd})
            await ar.write_attendance_audit(db, before=r, after={**r, **upd}, user=user, source="batal_tugas_luar",
                                            note=f"Dinas {travel.get('trip_number') or travel.get('id')} dibatalkan")
            out["restored"] += 1
    except Exception as e:  # noqa: BLE001
        log.exception("[tugas_luar] absensi dinas %s gagal dikembalikan", travel.get("id"))
        out["error"] = str(e)
    return out

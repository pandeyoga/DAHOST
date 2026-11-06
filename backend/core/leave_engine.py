"""Mesin cuti / izin / sakit — SATU fungsi persetujuan untuk semua jalur (2026-11-06, Tahap 2 paket absen).

Dulu ada tiga jalur persetujuan dengan akibat berbeda: persetujuan utama (`/leaves/{id}/approve`),
persetujuan massal (`/leaves/bulk-approve`), dan Kotak Masuk SDM (`/api/hr/inbox/leave/...`). Kotak masuk
tidak memeriksa/memotong saldo dan melompati persetujuan tingkat 2; semua jalur menulis absensi "cuti" di
SETIAP hari kalender (sakit jadi cuti, Minggu & libur ikut, setengah hari jadi sehari penuh) dan menimpa
jam absen yang sudah ada. Membatalkan cuti MENGHAPUS record absensinya, termasuk jam masuk/pulang.

Sekarang semua jalur memanggil `approve_leave_request` / `reject_leave_request` / `cancel_approved_leave`.

Kontrak dengan paket payroll (data yang ditulis ke `rahaza_attendance_events` untuk cuti disetujui):
  satu record per HARI KERJA (core.workdays) dengan
    status = leave_kind (cuti | izin | sakit) · leave_request_id · paid_leave (= pay_decision == 'paid')
    half_day = True untuk cuti setengah hari (hadir dihitung 0,5)
  Jam masuk/pulang yang sudah ada tetap disimpan. Keadaan sebelum cuti disimpan di `pre_leave` supaya
  pembatalan mengembalikannya (record yang dibuat cuti dan tidak berisi absen apa pun dihapus lagi).
Di `rahaza_leave_requests`: leave_kind · reason (wajib) · attachment_url · pay_decision (paid | unpaid,
  dipilih HR saat menyetujui) · leave_days (tanggal kerja) · duration_working_days ·
  balance_deducted_days (yang dipotong dari saldo; dipakai saat batal).
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import HTTPException

from core import attendance_rules as ar
from core import workdays

log = logging.getLogger(__name__)

LEAVE_KINDS = ("cuti", "izin", "sakit")
PAY_DECISIONS = ("paid", "unpaid")
PENDING_STATUSES = ("pending_approval", "pending_hr_approval")
KIND_LABEL = {"cuti": "Cuti", "izin": "Izin", "sakit": "Sakit"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_unpaid(lt) -> bool:
    from utils.leave_types import is_unpaid
    return is_unpaid(lt)


def leave_kind(leave: dict, lt: Optional[dict] = None) -> str:
    """cuti | izin | sakit — dari pengajuan (leave_kind/request_type), lalu jenis cutinya."""
    for v in ((leave or {}).get("leave_kind"), (leave or {}).get("request_type"), (lt or {}).get("request_type")):
        s = str(v or "").strip().lower()
        if s in LEAVE_KINDS:
            return s
    return "cuti"


def is_half_day(leave: dict) -> bool:
    return bool((leave or {}).get("is_half_day") or (leave or {}).get("half_day"))


def suggest_pay_decision(leave: dict, lt: Optional[dict]) -> dict:
    """Usulan dibayar/tidak untuk dialog persetujuan HR (keputusan akhir tetap HR).

    Bawaan dari tanda `unpaid` jenis cutinya; sakit dengan lampiran (surat dokter) → dibayar; izin tanpa
    lampiran → tidak dibayar (keputusan owner 6 Nov 2026: potongan gaji hanya untuk alpa dan izin tanpa
    surat dokter)."""
    kind = leave_kind(leave, lt)
    has_doc = bool((leave or {}).get("attachment_url"))
    name = (lt or {}).get("name") or KIND_LABEL[kind]
    if kind == "sakit" and has_doc:
        return {"decision": "paid", "reason": "Sakit dengan surat dokter atau bukti terlampir."}
    if kind == "izin" and not has_doc:
        return {"decision": "unpaid", "reason": "Izin tanpa bukti terlampir dipotong dari gaji."}
    if _is_unpaid(lt):
        return {"decision": "unpaid", "reason": f"Jenis '{name}' diatur tidak dibayar."}
    return {"decision": "paid", "reason": f"Jenis '{name}' diatur dibayar."}


async def leave_period_info(db, from_date: str, to_date: str, half_day: bool = False) -> dict:
    """Hari kerja (aturan core.workdays) dalam rentang cuti + rincian untuk layar."""
    try:
        d_from, d_to = date.fromisoformat(str(from_date)[:10]), date.fromisoformat(str(to_date)[:10])
    except ValueError:
        raise HTTPException(400, "Format tanggal tidak valid (YYYY-MM-DD).")
    if d_to < d_from:
        raise HTTPException(400, "Tanggal selesai tidak boleh lebih awal dari tanggal mulai.")
    cal = await workdays.get_work_calendar(db)
    hol_docs = await db.rahaza_production_calendar.find(
        {"date": {"$gte": d_from.isoformat(), "$lte": d_to.isoformat()}, "type": "holiday"},
        {"_id": 0, "date": 1, "name": 1}).to_list(400)
    hol = {str(h.get("date"))[:10] for h in hol_docs}
    days = workdays.working_days_between(d_from, d_to, cal["off_weekdays"], hol)
    calendar_days = (d_to - d_from).days + 1
    off_days = sum(1 for i in range(calendar_days)
                   if date.fromordinal(d_from.toordinal() + i).weekday() in cal["off_weekdays"])
    holiday_days = sum(1 for h in hol
                       if date.fromisoformat(h).weekday() not in cal["off_weekdays"])
    weight = 0.5 if half_day else 1.0
    return {
        "days": [d.isoformat() for d in days],
        "working_days": len(days) * weight,
        "calendar_days": calendar_days,
        "weekend_days": off_days,
        "holiday_days": holiday_days,
        "holidays": sorted(({"date": str(h.get("date"))[:10], "name": h.get("name") or "Libur"}
                            for h in hol_docs), key=lambda x: x["date"]),
        "work_days_per_week": cal["work_days_per_week"],
    }


# ── Pemisahan tugas ─────────────────────────────────────────────────────────
async def ensure_not_own_leave(db, leave: dict, user: dict) -> None:
    """Penyetuju tidak boleh memutus cuti/izin miliknya sendiri (sejalan K25)."""
    from utils.employee_identity import resolve_my_employee
    mine = await resolve_my_employee(db, user)
    if mine and mine.get("id") == leave.get("employee_id"):
        raise HTTPException(403, "Pemisahan tugas: Anda tidak boleh memutus pengajuan cuti/izin milik Anda sendiri. "
                                 "Minta penyetuju lain.")


# ── Hari absensi cuti ───────────────────────────────────────────────────────
SNAPSHOT_FIELDS = ("status", "notes", "half_day", "paid_leave", "leave_kind")
CLEAR_LEAVE_FIELDS = {"leave_request_id": None, "leave_kind": None, "paid_leave": None, "half_day": False,
                      "leave_type_id": None, "leave_type_name": None, "pre_leave": None, "leave_note": None}


def _own_attendance_data(rec: dict) -> bool:
    """Record berisi absen sungguhan (bukan hanya tanda cuti)?"""
    return bool(rec.get("clock_in") or rec.get("clock_out") or rec.get("sessions")
                or rec.get("photo_selfie_url") or rec.get("fingerprint"))


async def write_leave_days(db, leave: dict, days: list, *, kind: str, paid: bool, half_day: bool,
                           lt: Optional[dict], user: dict) -> dict:
    now = _now()
    emp_id, leave_id = leave["employee_id"], leave["id"]
    lt_name = (lt or {}).get("name") or KIND_LABEL[kind]
    note = f"{KIND_LABEL[kind]}: {lt_name}" + (f" ({leave.get('reason')})" if leave.get("reason") else "")
    out = {"created": 0, "updated": 0, "skipped": []}
    for d in days:
        fields = {"status": kind, "leave_request_id": leave_id, "leave_kind": kind, "paid_leave": bool(paid),
                  "half_day": bool(half_day), "leave_type_id": leave.get("leave_type_id"),
                  "leave_type_name": lt_name, "leave_note": note,
                  "updated_at": now, "updated_by": user.get("id"), "updated_by_name": user.get("name", "")}
        existing = await db.rahaza_attendance_events.find_one({"employee_id": emp_id, "date": d}, {"_id": 0})
        if existing:
            other = existing.get("leave_request_id")
            if other and other != leave_id:
                out["skipped"].append({"date": d, "reason": "sudah tercatat untuk pengajuan cuti lain"})
                continue
            if other != leave_id:   # persetujuan ulang tidak menimpa keadaan sebelum cuti
                fields["pre_leave"] = {k: existing.get(k) for k in SNAPSHOT_FIELDS}
            await db.rahaza_attendance_events.update_one({"id": existing["id"]}, {"$set": fields})
            await ar.write_attendance_audit(db, before=existing, after={**existing, **fields}, user=user,
                                            source="cuti", note=f"Pengajuan {leave_id} disetujui")
            out["updated"] += 1
        else:
            doc = {"id": str(uuid.uuid4()), "employee_id": emp_id, "date": d,
                   "clock_in": None, "clock_out": None, "hours_worked": 0, "overtime_hours": 0,
                   "notes": note, "source": "leave", "created_by_leave": True,
                   "created_by": user.get("id"), "created_by_name": user.get("name", ""), "created_at": now,
                   **fields}
            await db.rahaza_attendance_events.insert_one(doc)
            out["created"] += 1
    return out


async def restore_leave_days(db, leave: dict, user: dict) -> dict:
    """Kembalikan absensi ke keadaan sebelum cuti (bukan menghapus jam absen yang ada)."""
    now = _now()
    rows = await db.rahaza_attendance_events.find(
        {"employee_id": leave["employee_id"], "leave_request_id": leave["id"]}, {"_id": 0}).to_list(400)
    out = {"restored": 0, "deleted": 0}
    for r in rows:
        snap = r.get("pre_leave")
        if not snap and not _own_attendance_data(r):
            # record dibuat oleh cuti ini dan tidak berisi absen apa pun → keadaan sebelumnya: belum ada record
            await db.rahaza_attendance_events.delete_one({"id": r["id"], "leave_request_id": leave["id"]})
            out["deleted"] += 1
            continue
        upd = dict(CLEAR_LEAVE_FIELDS)
        if snap:
            upd.update({"status": snap.get("status") or ("hadir" if r.get("clock_in") else "alpa"),
                        "notes": snap.get("notes") if snap.get("notes") is not None else r.get("notes", ""),
                        "half_day": bool(snap.get("half_day")), "paid_leave": snap.get("paid_leave"),
                        "leave_kind": snap.get("leave_kind")})
        else:   # record lama (sebelum Tahap 2) atau dibuat cuti lalu karyawan sempat absen
            upd["status"] = "hadir" if r.get("clock_in") else "alpa"
        upd.update({"updated_at": now, "updated_by": user.get("id"), "updated_by_name": user.get("name", "")})
        await db.rahaza_attendance_events.update_one({"id": r["id"]}, {"$set": upd})
        await ar.write_attendance_audit(db, before=r, after={**r, **upd}, user=user, source="batal_cuti",
                                        note=f"Pengajuan {leave['id']} dibatalkan")
        out["restored"] += 1
    return out


async def _ensure_days_unlocked(db, employee_id: str, days: list) -> None:
    for d in days:
        lock = await ar.attendance_lock(db, employee_id, d)
        if lock:
            raise HTTPException(409, ar.lock_message(d, lock))


# ── Persetujuan ─────────────────────────────────────────────────────────────
async def _close_approval_requests(db, leave_id: str, status: str) -> None:
    try:
        await db.approval_requests.update_many(
            {"type": "leave", "ref_id": leave_id, "status": "pending"},
            {"$set": {"status": status, "updated_at": _now().isoformat()}})
        from utils.notif_unified import resolve_for_source
        await resolve_for_source(db, "rahaza_leave_requests", leave_id)
    except Exception as e:  # noqa: BLE001 — keputusan tetap sah walau antrean gagal dirapikan
        log.warning("[leave] antrean persetujuan %s gagal ditutup: %s", leave_id, e)


async def _notify_hr_step2(db, leave: dict) -> None:
    try:
        from routes.rahaza_notifications import publish_notification
        hr_users = await db.users.find({"role": {"$in": ["hr", "superadmin", "admin"]}},
                                       {"_id": 0, "id": 1}).to_list(20)
        hr_ids = [u["id"] for u in hr_users if u.get("id")]
        emp = await db.rahaza_employees.find_one({"id": leave["employee_id"]}, {"_id": 0, "name": 1})
        if hr_ids:
            await publish_notification(
                db, type_="leave_hr_approval_needed", severity="info",
                title=f"Persetujuan HR dibutuhkan: {(emp or {}).get('name', '')}",
                message=(f"Pengajuan {leave.get('duration_working_days', leave.get('duration_days'))} hari kerja "
                         "sudah disetujui atasan. Butuh persetujuan HR."),
                link_module="hr-leave", link_id=leave["id"], target_user_ids=hr_ids,
                dedup_key=f"leave_hr_{leave['id']}")
    except Exception as ne:  # noqa: BLE001
        log.warning("[leave] notif tingkat 2 gagal: %s", ne)


async def approve_leave_request(db, leave_id: str, user: dict, *, pay_decision: Optional[str] = None,
                                notes: str = "", via: str = "utama") -> dict:
    """SATU-SATUNYA fungsi persetujuan cuti/izin/sakit (utama · massal · Kotak Masuk SDM · tingkat 2).

    Return {"final": bool, "leave": dokumen terbaru, "attendance": {...} bila final}."""
    leave = await db.rahaza_leave_requests.find_one({"id": leave_id}, {"_id": 0})
    if not leave:
        raise HTTPException(404, "Pengajuan cuti tidak ditemukan.")
    if leave.get("status") not in PENDING_STATUSES:
        raise HTTPException(400, f"Hanya pengajuan yang menunggu persetujuan yang bisa disetujui "
                                 f"(status sekarang: {leave.get('status')}).")
    await ensure_not_own_leave(db, leave, user)

    level_required = int(leave.get("approval_level_required") or 1)
    current = int(leave.get("current_approval_level") or 1)
    now = _now()
    step = {"step": current, "approver_id": user.get("id"), "approver_name": user.get("name", ""),
            "action": "approved", "notes": notes or "", "via": via, "at": now}

    if level_required > 1 and current == 1:
        # Tingkat 1 (atasan) selesai → menunggu HR. Saldo & absensi baru disentuh di persetujuan akhir.
        await db.rahaza_leave_requests.update_one(
            {"id": leave_id, "status": {"$in": list(PENDING_STATUSES)}},
            {"$set": {"approval_step_1": step, "status": "pending_hr_approval",
                      "current_approval_level": 2, "updated_at": now}})
        fresh = await db.rahaza_leave_requests.find_one({"id": leave_id}, {"_id": 0})
        await _notify_hr_step2(db, fresh or leave)
        return {"final": False, "leave": fresh}

    lt = await db.rahaza_leave_types.find_one({"id": leave.get("leave_type_id")}, {"_id": 0})
    kind = leave_kind(leave, lt)
    half = is_half_day(leave)
    info = await leave_period_info(db, leave["from_date"], leave["to_date"], half)
    if not info["days"]:
        raise HTTPException(400, "Rentang tanggal pengajuan ini tidak memuat hari kerja (Minggu/libur). "
                                 "Tolak pengajuan atau minta karyawan memperbaiki tanggalnya.")
    suggestion = suggest_pay_decision(leave, lt)
    decision = (pay_decision or suggestion["decision"]).strip().lower()
    if decision not in PAY_DECISIONS:
        raise HTTPException(400, "Keputusan pembayaran harus 'dibayar' atau 'tidak dibayar'.")
    await _ensure_days_unlocked(db, leave["employee_id"], info["days"])

    duration = float(info["working_days"])
    type_unpaid = _is_unpaid(lt)
    # Saldo = jatah hari kerja DIBAYAR. Jenis tak dibayar (mis. LWOP) tetap dicatat pemakaiannya;
    # keputusan "tidak dibayar" untuk jenis yang dibayar tidak memakai jatah.
    deduct = type_unpaid or decision == "paid"
    year = date.fromisoformat(str(leave["from_date"])[:10]).year
    from routes.rahaza_leave_balances import balance_snapshot, consume_balance
    if decision == "paid" and not type_unpaid:
        bal = await balance_snapshot(db, leave["employee_id"], leave["leave_type_id"], year, lt=lt)
        if bal["remaining"] < duration:
            raise HTTPException(400, f"Sisa cuti tidak cukup. Sisa: {bal['remaining']:g} hari, "
                                     f"diminta: {duration:g} hari. Pilih 'tidak dibayar' bila tetap disetujui.")

    res = await db.rahaza_leave_requests.update_one(
        {"id": leave_id, "status": {"$in": list(PENDING_STATUSES)}},
        {"$set": {f"approval_step_{current}": step, "status": "approved", "leave_kind": kind,
                  "request_type": kind, "pay_decision": decision,
                  "pay_decision_suggested": suggestion["decision"],
                  "pay_decision_by": user.get("id"), "pay_decision_by_name": user.get("name", ""),
                  "leave_days": info["days"], "duration_working_days": duration, "duration_days": duration,
                  "balance_deducted_days": duration if deduct else 0,
                  "approved_at": now, "approved_by": user.get("id"), "approved_by_name": user.get("name", ""),
                  "approval_note": notes or "", "approved_via": via, "updated_at": now}})
    if getattr(res, "matched_count", 1) == 0:
        raise HTTPException(409, "Pengajuan ini baru saja diputuskan orang lain. Muat ulang halaman.")
    if deduct:
        await consume_balance(db, leave["employee_id"], leave["leave_type_id"], year, duration)
    written = await write_leave_days(db, {**leave, "leave_kind": kind}, info["days"], kind=kind,
                                     paid=decision == "paid", half_day=half, lt=lt, user=user)
    await db.rahaza_leave_requests.update_one({"id": leave_id}, {"$set": {"attendance_written": written}})
    await _close_approval_requests(db, leave_id, "approved")

    fresh = await db.rahaza_leave_requests.find_one({"id": leave_id}, {"_id": 0})
    saldo_txt = ""
    if deduct:
        bal_after = await balance_snapshot(db, leave["employee_id"], leave["leave_type_id"], year, lt=lt)
        saldo_txt = f" Sisa saldo {(lt or {}).get('name', 'cuti')}: {bal_after['remaining']:g} hari."
    from routes.rahaza_leave import notify_leave_decision
    await notify_leave_decision(db, fresh or leave, approved=True, saldo_txt=saldo_txt)
    return {"final": True, "leave": fresh, "attendance": written}


async def reject_leave_request(db, leave_id: str, user: dict, reason: str, *, via: str = "utama") -> dict:
    leave = await db.rahaza_leave_requests.find_one({"id": leave_id}, {"_id": 0})
    if not leave:
        raise HTTPException(404, "Pengajuan cuti tidak ditemukan.")
    if leave.get("status") not in PENDING_STATUSES:
        raise HTTPException(400, f"Hanya pengajuan yang menunggu persetujuan yang bisa ditolak "
                                 f"(status sekarang: {leave.get('status')}).")
    await ensure_not_own_leave(db, leave, user)
    now = _now()
    # 2026-11-06 (pola P9): status lama di filter — dulu "tolak" bisa menimpa cuti yang baru saja disetujui
    # (hari cuti sudah tertulis di absensi & saldo terpotong, status tampak ditolak).
    res = await db.rahaza_leave_requests.update_one({"id": leave_id, "status": leave.get("status")}, {"$set": {
        "status": "rejected", "rejected_at": now, "rejected_by": user.get("id"),
        "rejected_by_name": user.get("name", ""), "rejected_reason": reason, "reject_reason": reason,
        "rejected_via": via, "updated_at": now}})
    if getattr(res, "matched_count", 1) == 0:
        raise HTTPException(409, "Pengajuan ini baru saja diputuskan orang lain. Muat ulang halaman.")
    await _close_approval_requests(db, leave_id, "rejected")
    from routes.rahaza_leave import notify_leave_decision
    await notify_leave_decision(db, leave, approved=False, reason=reason)
    return await db.rahaza_leave_requests.find_one({"id": leave_id}, {"_id": 0})


async def cancel_approved_leave(db, leave: dict, user: dict, reason: str, *, is_hr: bool) -> dict:
    """Batalkan cuti yang SUDAH disetujui: saldo dikembalikan, absensi dikembalikan ke keadaan sebelum cuti.

    Karyawan: hanya sebelum cuti dimulai. HR: juga sesudah dimulai, selama harinya belum masuk gaji final."""
    from utils.waktu import today_wib
    try:
        d_from = date.fromisoformat(str(leave["from_date"])[:10])
    except (KeyError, ValueError):
        raise HTTPException(400, "Tanggal pengajuan tidak valid.")
    if d_from < today_wib() and not is_hr:
        raise HTTPException(400, f"Tidak bisa membatalkan cuti yang sudah dimulai ({leave['from_date']}). "
                                 "Hubungi HR untuk pembatalan.")
    rows = await db.rahaza_attendance_events.find(
        {"employee_id": leave["employee_id"], "leave_request_id": leave["id"]},
        {"_id": 0, "date": 1}).to_list(400)
    await _ensure_days_unlocked(db, leave["employee_id"], sorted({str(r.get("date"))[:10] for r in rows}))

    restored_days = (float(leave["balance_deducted_days"]) if leave.get("balance_deducted_days") is not None
                     else float(leave.get("duration_days") or 0))   # pengajuan lama: dipotong duration_days
    if restored_days:
        from routes.rahaza_leave_balances import restore_balance
        await restore_balance(db, leave["employee_id"], leave["leave_type_id"], d_from.year, restored_days)
    restored = await restore_leave_days(db, leave, user)
    now = _now()
    await db.rahaza_leave_requests.update_one({"id": leave["id"]}, {"$set": {
        "status": "cancelled", "cancelled_at": now, "cancelled_by": user.get("id"),
        "cancelled_by_name": user.get("name", ""), "cancel_reason": reason,
        "cancel_restored": restored, "balance_restored_days": restored_days, "updated_at": now}})
    return await db.rahaza_leave_requests.find_one({"id": leave["id"]}, {"_id": 0})

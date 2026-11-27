"""core.batal_setuju_sdm — jenis persetujuan SDM yang bisa dibatalkan (lihat `core.batal_setuju`).

Pengaman bersama: tanggal yang sudah masuk proses gaji FINAL tidak bisa diubah lagi (`attendance_lock`) —
pembatalan persetujuan cuti/lembur/koreksi/absen pada tanggal itu ditolak dan staf diarahkan membatalkan run gaji.
Proses gaji sendiri TIDAK didaftarkan: Finalisasi sudah punya jalur Batalkan run (dua langkah HR → Keuangan).
"""
from __future__ import annotations

from datetime import datetime, timezone

from core.batal_setuju import Jenis, daftar

HR_IZIN = ("hr.approve", "hr.manage")
HR_PERAN = ("owner", "admin", "superadmin", "hr", "hr_manager", "manager")
PESAN_GAJI_FINAL = ("Tanggal {tgl} sudah masuk proses gaji FINAL {run}. Batalkan dulu proses gajinya di Penggajian, "
                    "lalu ulangi.")


def _now():
    return datetime.now(timezone.utc)


async def _hari_terkunci(db, emp_id: str, hari) -> list:
    from core.attendance_rules import attendance_lock
    for d in sorted({str(x)[:10] for x in (hari or []) if x}):
        lock = await attendance_lock(db, emp_id, d)
        if lock:
            return [PESAN_GAJI_FINAL.format(tgl=d, run=lock.get("run_number") or "")]
    return []


_BULAN = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")


def _tgl(v) -> str:
    """'2026-11-21' / datetime → '21 Nov 2026' (untuk nama dokumen di layar; teks lain dikembalikan apa adanya)."""
    s = (v.isoformat() if hasattr(v, "isoformat") else str(v or ""))[:10]
    try:
        th, bl, hr = int(s[:4]), int(s[5:7]), int(s[8:10])
        return f"{hr} {_BULAN[bl - 1]} {th}"
    except (ValueError, IndexError):
        return s


def _rentang(a, b) -> str:
    """Satu hari → '21 Nov 2026'; beberapa hari → '20 Nov 2026–22 Nov 2026'."""
    ta, tb = _tgl(a), _tgl(b)
    return ta if not tb or tb == ta else f"{ta}–{tb}"


# ── Cuti / izin / sakit — persetujuan AKHIR (saldo dipotong + absensi ditulis) ──
async def _hambatan_cuti(db, d: dict) -> list:
    hari = d.get("leave_days") or []
    if not hari:
        rows = await db.rahaza_attendance_events.find(
            {"employee_id": d.get("employee_id"), "leave_request_id": d.get("id")}, {"_id": 0, "date": 1}).to_list(400)
        hari = [r.get("date") for r in rows]
    return await _hari_terkunci(db, d.get("employee_id"), hari)


async def _balik_cuti(db, d: dict, user: dict, alasan: str) -> dict:
    from core.leave_engine import restore_leave_days
    out = {"saldo_dikembalikan": 0.0}
    hari = (float(d["balance_deducted_days"]) if d.get("balance_deducted_days") is not None
            else float(d.get("duration_days") or 0))
    if hari and d.get("leave_type_id"):
        from routes.rahaza_leave_balances import restore_balance
        per_tahun = d.get("balance_deducted_by_year") or {_tgl(d.get("from_date"))[:4]: hari}
        for y, v in per_tahun.items():
            if float(v or 0) and str(y).isdigit():
                await restore_balance(db, d["employee_id"], d["leave_type_id"], int(y), float(v))
                out["saldo_dikembalikan"] += float(v)
    out["absensi"] = await restore_leave_days(db, d, user)
    if int(d.get("approval_level_required") or 1) <= 1:   # satu tingkat: langkah 1 = persetujuan akhir ini
        await db.rahaza_leave_requests.update_one({"id": d["id"]}, {"$unset": {"approval_step_1": ""}})
    await db.approval_requests.update_many({"type": "leave", "ref_id": d["id"], "status": "approved"},
                                           {"$set": {"status": "pending"}})
    return out


daftar(Jenis(
    kode="hr-cuti", label="Cuti / izin / sakit", portal="hr", koleksi="rahaza_leave_requests", modul="hr-leave",
    status_setuju=("approved",),
    kembali_ke=lambda d: "pending_hr_approval" if int(d.get("approval_level_required") or 1) > 1 else "pending_approval",
    label_kembali="menunggu persetujuan", izin=HR_IZIN, peran_lama=HR_PERAN,
    hapus_field=("approved_at", "approved_by", "approved_by_name", "approval_note", "approved_via", "pay_decision",
                 "pay_decision_by", "pay_decision_by_name", "balance_deducted_days", "balance_deducted_by_year",
                 "attendance_written", "approval_step_2"),
    nama=lambda d: f"{d.get('employee_name') or ''} {_rentang(d.get('from_date'), d.get('to_date'))}".strip(),
    pemohon=lambda d: d.get("user_id") or d.get("created_by"), penyetuju=lambda d: d.get("approved_by"),
    hambatan=_hambatan_cuti, balikkan=_balik_cuti,
))


# ── Lembur — status saja; gaji membaca lembur DISETUJUI saat dihitung ──
async def _hambatan_lembur(db, d: dict) -> list:
    return await _hari_terkunci(db, d.get("employee_id"), [d.get("date")])


daftar(Jenis(
    kode="hr-lembur", label="Lembur", portal="hr", koleksi="rahaza_overtime_requests", modul="hr-overtime",
    status_setuju=("approved",), kembali_ke="pending", label_kembali="menunggu persetujuan",
    izin=HR_IZIN, peran_lama=HR_PERAN,
    hapus_field=("approved_by", "approved_by_name", "approved_at", "approval_note"),
    nama=lambda d: f"{d.get('employee_name') or ''} {_tgl(d.get('date'))}".strip(),
    pemohon=lambda d: d.get("user_id") or d.get("created_by"), penyetuju=lambda d: d.get("approved_by"),
    hambatan=_hambatan_lembur,
))


# ── Absen selfie — persetujuan menulis status 'hadir'; dikembalikan dari jejak absensi ──
async def _hambatan_selfie(db, d: dict) -> list:
    return await _hari_terkunci(db, d.get("employee_id"), [d.get("date")])


async def _balik_selfie(db, d: dict, user: dict, alasan: str) -> dict:
    jejak = await db.rahaza_attendance_audit.find(
        {"event_id": d.get("id"), "source": "persetujuan_selfie"}, {"_id": 0}).sort("at", -1).to_list(1)
    sebelum = ((jejak or [{}])[0].get("before") or {}).get("status")
    if sebelum and sebelum != d.get("status") and not d.get("leave_request_id"):
        await db.rahaza_attendance_events.update_one({"id": d["id"]}, {"$set": {"status": sebelum}})
        return {"status_absen_dikembalikan": sebelum}
    return {}


daftar(Jenis(
    kode="hr-absen-selfie", label="Absen selfie", portal="hr", koleksi="rahaza_attendance_events",
    modul="hr-attendance-approval", field_status="approval_status",
    status_setuju=("approved",), kembali_ke="pending", label_kembali="menunggu persetujuan",
    izin=HR_IZIN, peran_lama=HR_PERAN,
    hapus_field=("approval_by", "approval_by_name", "approval_notes", "approval_at"),
    nama=lambda d: f"{d.get('employee_name') or ''} {_tgl(d.get('date'))}".strip(),
    pemohon=lambda d: d.get("user_id"), penyetuju=lambda d: d.get("approval_by"), waktu_setuju="approval_at",
    hambatan=_hambatan_selfie, balikkan=_balik_selfie,
))


# ── Koreksi absen — langsung (absensi ditulis ulang) atau penyesuaian payroll (tanggal sudah final) ──
async def _hambatan_koreksi(db, d: dict) -> list:
    if d.get("apply_mode") == "penyesuaian_payroll":
        if (d.get("payroll_adjustment") or {}).get("status") not in (None, "pending"):
            return ["Koreksi ini sudah diterapkan di proses gaji berikutnya. Batalkan proses gaji itu dulu di Penggajian."]
        return []
    out = await _hari_terkunci(db, d.get("employee_id"), [d.get("date")])
    if out:
        return out
    ev = await db.rahaza_attendance_events.find_one({"id": d.get("event_id")}, {"_id": 0, "correction_id": 1})
    if ev and ev.get("correction_id") not in (None, d.get("id")):
        return ["Absensi tanggal itu sudah diubah lagi oleh koreksi lain. Batalkan koreksi yang lebih baru dulu."]
    return []


async def _balik_koreksi(db, d: dict, user: dict, alasan: str) -> dict:
    if d.get("apply_mode") == "penyesuaian_payroll":
        return {"penyesuaian_payroll": "tidak jadi diterapkan"}
    ev = await db.rahaza_attendance_events.find_one({"id": d.get("event_id")}, {"_id": 0})
    if not ev:
        return {}
    from core.attendance_rules import timing_fields, write_attendance_audit
    cur = d.get("current") or {}
    catatan = f"Persetujuan koreksi dibatalkan: {alasan}"
    if not any(cur.get(k) for k in ("status", "clock_in", "clock_out", "hours_worked")) and ev.get("source") == "koreksi":
        await db.rahaza_attendance_events.delete_one({"id": ev["id"], "correction_id": d["id"]})
        await write_attendance_audit(db, before=ev, after={"id": ev["id"]}, user=user, source="batal_koreksi",
                                     employee_id=ev.get("employee_id"), day=ev.get("date"), note=catatan)
        return {"absensi": "dihapus (dibuat oleh koreksi ini)"}
    upd = {k: cur.get(k) for k in ("status", "clock_in", "clock_out", "hours_worked")}
    if upd.get("clock_in") or upd.get("clock_out"):
        emp = await db.rahaza_employees.find_one({"id": ev.get("employee_id")}, {"_id": 0}) or {"id": ev.get("employee_id")}
        upd.update(await timing_fields(db, emp, {**ev, **upd}))
    await db.rahaza_attendance_events.update_one({"id": ev["id"]}, {"$set": upd, "$unset": {"correction_id": ""}})
    await write_attendance_audit(db, before=ev, after={**ev, **upd}, user=user, source="batal_koreksi",
                                 employee_id=ev.get("employee_id"), day=ev.get("date"), note=catatan)
    return {"absensi": "dikembalikan ke sebelum koreksi"}


daftar(Jenis(
    kode="hr-koreksi-absen", label="Koreksi absen", portal="hr", koleksi="rahaza_attendance_corrections",
    modul="hr-inbox", status_setuju=("approved",), kembali_ke="pending", label_kembali="menunggu persetujuan",
    izin=HR_IZIN + ("hr.attendance.manage",), peran_lama=HR_PERAN,
    hapus_field=("apply_mode", "current", "event_id", "locked_run_id", "locked_run_number", "payroll_adjustment",
                 "decided_by", "decided_by_name", "decided_at", "decision_note"),
    nama=lambda d: f"{d.get('employee_name') or ''} {_tgl(d.get('date'))}".strip(),
    pemohon=lambda d: d.get("created_by") or d.get("user_id"), penyetuju=lambda d: d.get("decided_by"),
    waktu_setuju="decided_at", hambatan=_hambatan_koreksi, balikkan=_balik_koreksi,
))


# ── Penyesuaian gaji — versi tarif baru di Profil Gaji ──
async def _hambatan_gaji(db, d: dict) -> list:
    eff = _tgl(d.get("applied_effective_from") or d.get("effective_date"))
    if not eff:
        return []
    slip = await db.rahaza_payslips.find(
        {"employee_id": d.get("employee_id"), "period_to": {"$gte": eff}}, {"_id": 0, "run_id": 1}).to_list(50)
    ids = list({s.get("run_id") for s in slip if s.get("run_id")})
    if ids:
        run = await db.rahaza_payroll_runs.find_one({"id": {"$in": ids}, "status": "finalized"}, {"_id": 0, "run_number": 1})
        if run:
            return [f"Gaji baru sudah dipakai proses gaji FINAL {run.get('run_number') or ''}. Batalkan proses gajinya "
                    "dulu, atau buat penyesuaian gaji baru untuk mengoreksi."]
    return []


async def _balik_gaji(db, d: dict, user: dict, alasan: str) -> dict:
    from routes.rahaza_payroll_profiles import _current_rates
    prof = await db.rahaza_payroll_profiles.find_one({"employee_id": d.get("employee_id"), "active": True}, {"_id": 0})
    if not prof:
        return {}
    vers = [dict(v) for v in (prof.get("rate_versions") or []) if v.get("adjustment_id") != d.get("id")]
    lama = d.get("versi_tergantikan")
    if lama and not any(v.get("effective_from") == lama.get("effective_from") for v in vers):
        vers.append(dict(lama))
    vers.sort(key=lambda v: str(v.get("effective_from") or ""))
    for i, v in enumerate(vers, 1):
        v["version"] = i
    await db.rahaza_payroll_profiles.update_one({"id": prof["id"]}, {"$set": {
        "rate_versions": vers, **(_current_rates(prof, vers) if vers else {}), "updated_at": _now(),
        "updated_by": user.get("id"), "updated_by_name": user.get("name", "")}})
    return {"profil_gaji": "tarif dari penyesuaian ini dihapus"}


daftar(Jenis(
    kode="hr-penyesuaian-gaji", label="Penyesuaian gaji", portal="hr", koleksi="rahaza_salary_adjustments",
    modul="hr-salary-adjustment", status_setuju=("approved",),
    kembali_ke=lambda d: "pending_hr" if d.get("manager_approved_at") else "pending_manager",
    label_kembali="menunggu persetujuan HR",
    izin=("hr.manage", "salary.manage"), peran_lama=("owner", "admin", "superadmin", "hr", "hr_manager"),
    hapus_field=("hr_approved_at", "hr_approved_by", "hr_approved_by_name", "hr_notes", "applied_at",
                 "applied_effective_from", "versi_tergantikan"),
    nama=lambda d: f"{d.get('employee_name') or ''} {d.get('raise_pct') or ''}%".strip(),
    pemohon=lambda d: d.get("created_by") or d.get("requested_by"), penyetuju=lambda d: d.get("hr_approved_by"),
    waktu_setuju="hr_approved_at", hambatan=_hambatan_gaji, balikkan=_balik_gaji,
))


# ── Ganti / tukar shift — persetujuan HR menerbitkan jadwal perubahan satu tanggal ──
async def _hambatan_shift(db, d: dict) -> list:
    from utils.waktu import today_wib
    tgl = _tgl(d.get("tanggal"))
    if tgl and tgl <= today_wib().isoformat():
        return [f"Tanggal shift {tgl} sudah lewat atau hari ini, jadi jadwalnya tidak bisa ditarik lagi."]
    for eid in (d.get("employee_id"), d.get("rekan_employee_id")):
        if eid:
            out = await _hari_terkunci(db, eid, [tgl])
            if out:
                return out
    return []


async def _balik_shift(db, d: dict, user: dict, alasan: str) -> dict:
    if d.get("jadwal_id"):
        await db.rahaza_schedules.update_one({"id": d["jadwal_id"], "status": "published"}, {"$set": {
            "status": "dibatalkan", "dibatalkan_at": _now(), "dibatalkan_by": user.get("id")}})
    await db.hr_shift_requests.update_one({"id": d["id"]}, {"$push": {"riwayat": {
        "tahap": "sdm", "keputusan": "persetujuan_dibatalkan", "oleh": user.get("id"), "oleh_nama": user.get("name") or "",
        "catatan": alasan[:300], "waktu": _now().isoformat()}}})
    return {"jadwal": "jadwal perubahan dibatalkan"}


daftar(Jenis(
    kode="hr-shift", label="Ganti/tukar shift", portal="hr", koleksi="hr_shift_requests", modul="hr-shift-permintaan",
    status_setuju=("disetujui",), kembali_ke="menunggu_hr", label_kembali="menunggu keputusan HR",
    izin=("hr.attendance.manage", "hr.manage"), peran_lama=("owner", "admin", "superadmin", "hr", "hr_manager", "staff_hr"),
    hapus_field=("jadwal_id",),
    nama=lambda d: f"{d.get('employee_name') or ''} {_tgl(d.get('tanggal'))}".strip(),
    pemohon=lambda d: d.get("user_id"), penyetuju=lambda d: None, waktu_setuju="updated_at",
    hambatan=_hambatan_shift, balikkan=_balik_shift,
))


# ── Pengunduran diri diterima → karyawan nonaktif ──
async def _hambatan_resign(db, d: dict) -> list:
    if not d.get("resignation_accepted_at"):
        return ["Karyawan ini dinonaktifkan tanpa pengajuan pengunduran diri. Aktifkan lewat Data Karyawan."]
    run = await db.rahaza_payroll_runs.find_one(
        {"status": "finalized", "excluded_employees.employee_id": d.get("id")}, {"_id": 0, "run_number": 1})
    if run:
        return [f"Karyawan ini sudah dikeluarkan dari proses gaji FINAL {run.get('run_number') or ''}. "
                "Batalkan proses gajinya dulu, lalu ulangi."]
    return []


daftar(Jenis(
    kode="hr-resign", label="Pengunduran diri", portal="hr", koleksi="rahaza_employees", modul="hr-admin",
    field_status="employee_status", status_setuju=("resigned",), kembali_ke="resigning",
    label_kembali="menunggu keputusan HR", isi_field={"active": True},
    izin=("hr.employee.manage", "hr.manage"), peran_lama=HR_PERAN,
    hapus_field=("resignation_accepted_by", "resignation_accepted_at", "resignation_status"),
    nama=lambda d: f"{d.get('name') or d.get('full_name') or ''} {d.get('employee_code') or ''}".strip(),
    pemohon=lambda d: d.get("user_id"), penyetuju=lambda d: d.get("resignation_accepted_by"),
    waktu_setuju="resignation_accepted_at", hambatan=_hambatan_resign,
))


# ── Perubahan data karyawan (Portal Saya) — nilai baru ditulis ke data karyawan + akun login ──
async def _hambatan_data(db, d: dict) -> list:
    emp = await db.rahaza_employees.find_one({"id": d.get("employee_id")}, {"_id": 0}) or {}
    if any(emp.get(f) != v for f, v in (d.get("applied") or {}).items()):
        return ["Data karyawan sudah diubah lagi sesudah persetujuan ini. Ubah langsung di Data Karyawan."]
    if d.get("decided_at") and await db.rahaza_employee_data_changes.count_documents(
            {"employee_id": d.get("employee_id"), "id": {"$ne": d.get("id")}, "status": "approved",
             "decided_at": {"$gt": d.get("decided_at")}}):
        return ["Ada perubahan data yang disetujui sesudahnya. Batalkan yang lebih baru dulu."]
    return []


async def _balik_data(db, d: dict, user: dict, alasan: str) -> dict:
    from core.employee_data_change import account_patch
    before = d.get("before_applied") or {}
    if not before:
        return {}
    await db.rahaza_employees.update_one({"id": d["employee_id"]}, {"$set": {**before, "updated_at": _now()}})
    emp = await db.rahaza_employees.find_one({"id": d["employee_id"]}, {"_id": 0, "user_id": 1}) or {}
    uid = d.get("user_id") or emp.get("user_id")
    if uid:
        acc = await db.users.find_one({"id": uid}, {"_id": 0, "kontak_darurat": 1}) or {}
        await db.users.update_one({"id": uid}, {"$set": account_patch(before, acc)})
    return {"data_karyawan": "dikembalikan ke nilai sebelum disetujui"}


daftar(Jenis(
    kode="hr-data-karyawan", label="Perubahan data karyawan", portal="hr", koleksi="rahaza_employee_data_changes",
    modul="hr-inbox", status_setuju=("approved",), kembali_ke="pending", label_kembali="menunggu persetujuan",
    izin=HR_IZIN, peran_lama=HR_PERAN,
    hapus_field=("applied", "before_applied", "decided_by", "decided_by_name", "decided_at", "decision_note"),
    nama=lambda d: d.get("employee_name") or d.get("employee_id") or "",
    pemohon=lambda d: d.get("user_id"), penyetuju=lambda d: d.get("decided_by"), waktu_setuju="decided_at",
    hambatan=_hambatan_data, balikkan=_balik_data,
))

"""employee_identity.py — SSOT IDENTITAS KARYAWAN (siapa saya / boleh atas nama siapa).

═══════════════════════════════════════════════════════════════════════════════
KENAPA MODUL INI ADA
═══════════════════════════════════════════════════════════════════════════════
Sebelum ini ada **4 versi berbeda** fungsi "cari karyawan dari user login":
  · routes/dewi_portal_saya_hr.py::_get_linked_employee        (hanya users.employee_id)
  · routes/dewi_portal_saya_workspace.py::_get_linked_employee (hanya users.employee_id)
  · routes/dewi_kpi_shared.py::_get_linked_employee            (employee_id → user_id → email)
  · routes/dewi_portal_saya_ext.py::_get_my_employee           (employee_id → email|id|code)

dan yang PALING berbahaya di `rahaza_auto_attendance_config.py::my-status`:

    emp = await db.rahaza_employees.find_one({"email": user.get("email")})
    if not emp:
        emp = await db.rahaza_employees.find_one({})   # ← KARYAWAN PERTAMA DI DB!

Akibatnya (DIBUKTIKAN 2026-07-26 lewat browser): login sebagai **Siti Rahayu
(DA-002, HR Manager)** lalu membuka halaman absen menampilkan **"Budi Operator
(OP-001)"** — karyawan yang sama sekali berbeda. Kalau tombol absen ditekan,
kehadiran tercatat ATAS NAMA ORANG LAIN.

Penyakit kedua: endpoint tulis absensi (`selfie/clock-in`, `webauthn/clock-in`)
menerima `employee_id` **dari body request tanpa pemeriksaan kepemilikan** ⇒
siapa pun yang punya token bisa "titip absen" untuk karyawan mana pun.

SSOT ini menutup keduanya:
  · `resolve_my_employee()` — urutan resolusi TUNGGAL, dan **tidak pernah**
    jatuh ke karyawan sembarangan. Tidak ketemu ⇒ `None` (bukan tebakan).
  · `resolve_employee_for()` — kalau pemanggil meminta karyawan LAIN, wajib
    role HR/admin. Kalau bukan ⇒ HTTP 403.

JANGAN menulis ulang query penerima/identitas di modul lain. Sentinel
`scripts/verify_fase15.py` bagian S memakai AST untuk menjaga aturan ini.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

# Zona waktu operasional perusahaan (WIB). Jam shift ("07:00") disimpan sebagai
# waktu LOKAL, sedangkan clock_in disimpan UTC — konversi wajib lewat sini.
#
# 2026-08-07 (P3) — definisinya DIPINDAH ke SSOT `utils/waktu.py`. Dulu repo ini
# punya tiga pengertian "waktu Jakarta" yang terpisah (di sini offset tetap +7, di
# `core/accessory_valuation` string "Asia/Jakarta", dan puluhan `datetime.now()`
# polos). Nama `WIB` dipertahankan supaya pemakai lama tidak berubah.
from utils.waktu import WIB  # noqa: F401 — re-export demi kompatibilitas

# Role yang boleh bertindak ATAS NAMA karyawan lain (input manual/koreksi HR).
HR_ROLES = {"superadmin", "admin", "owner", "hr", "hr_manager", "manager",
            "supervisor", "supervisor_produksi"}

# Karyawan aktif. `active` adalah field kanonik di `rahaza_employees`.
ACTIVE_EMPLOYEE_FILTER = {"active": {"$ne": False}}


def job_title_of(emp: dict | None) -> str:
    """Jabatan karyawan. 2026-11-06 (pola P3): master karyawan menulis `job_title`; beberapa layar
    dulu membaca `position` (tidak pernah ditulis) sehingga kolom Jabatan selalu kosong."""
    e = emp or {}
    return e.get("job_title") or e.get("position") or ""


def is_hr(user: dict) -> bool:
    """True bila user boleh bertindak atas nama karyawan lain."""
    role = (user.get("role") or "").lower()
    if role in HR_ROLES:
        return True
    perms = user.get("_permissions") or []
    return "*" in perms or "hr.manage" in perms


def can_view_all_employees(user: dict) -> bool:
    """Boleh membaca data SDM karyawan LAIN (absensi, cuti, saldo)? — 2026-11-07 (Tahap 7, Portal Saya).

    Dulu daftar/grid absensi, detail cuti, dan saldo cuti hanya `require_auth`: akun staf (mis. tim packing)
    membaca lokasi GPS, foto selfie, dan alasan/surat sakit seluruh karyawan lewat API. Sekarang: HR/atasan
    (`is_hr`), peran SDM (`core.roles.HR_ROLES`), atau akun yang diberi Portal SDM oleh owner. Selain itu
    hanya data milik sendiri — pola yang sama dengan daftar lembur, kasbon, dan izin keluar."""
    if is_hr(user):
        return True
    from core.roles import HR_ROLES as CORE_HR_ROLES
    if (user.get("role") or "").lower() in CORE_HR_ROLES:
        return True
    from routes.shared import check_portal_access
    return bool(check_portal_access(user, "hr"))


async def employee_user_ids(db, employee_id: Optional[str]) -> list:
    """Akun login AKTIF milik karyawan (`users.employee_id` ATAU `rahaza_employees.user_id`) — penerima
    kabar keputusan (cuti, lembur, koreksi absen, selfie). Dulu sebagian pengirim hanya melihat
    `users.employee_id`, sehingga karyawan yang ditautkan dari sisi data karyawan tidak pernah dikabari."""
    if not employee_id:
        return []
    from utils.notif_recipients import active_user_filter
    ids = [r["id"] for r in await db.users.find(active_user_filter({"employee_id": employee_id}),
                                                {"_id": 0, "id": 1}).to_list(5) if r.get("id")]
    emp = await db.rahaza_employees.find_one({"id": employee_id}, {"_id": 0, "user_id": 1})
    uid = (emp or {}).get("user_id")
    if uid and uid not in ids and await db.users.find_one(active_user_filter({"id": uid}), {"_id": 0, "id": 1}):
        ids.append(uid)
    return ids


async def resolve_my_employee(db, user: dict) -> Optional[dict]:
    """Karyawan milik user yang login. `None` bila belum ditautkan.

    Urutan (SATU-SATUNYA yang sah):
      1. `users.employee_id`            → tautan eksplisit yang dibuat HR (`link-user`)
      2. `rahaza_employees.user_id`     → tautan arah sebaliknya
      3. `rahaza_employees.email`       → pencocokan email (huruf kecil)

    TIDAK ADA langkah 4. Kalau tiga-tiganya gagal, jawabannya **tidak tahu** —
    bukan "ambil karyawan pertama".
    """
    if not user:
        return None

    emp_id = user.get("employee_id")
    if emp_id:
        emp = await db.rahaza_employees.find_one(
            {"id": emp_id, **ACTIVE_EMPLOYEE_FILTER}, {"_id": 0})
        if emp:
            return emp
        # user doc di JWT bisa basi — coba ambil ulang dari koleksi users
    uid = user.get("id")
    if uid:
        emp = await db.rahaza_employees.find_one(
            {"user_id": uid, **ACTIVE_EMPLOYEE_FILTER}, {"_id": 0})
        if emp:
            return emp
        udoc = await db.users.find_one({"id": uid}, {"_id": 0, "employee_id": 1})
        if udoc and udoc.get("employee_id"):
            emp = await db.rahaza_employees.find_one(
                {"id": udoc["employee_id"], **ACTIVE_EMPLOYEE_FILTER}, {"_id": 0})
            if emp:
                return emp

    email = (user.get("email") or "").strip().lower()
    if email:
        emp = await db.rahaza_employees.find_one(
            {"email": email, **ACTIVE_EMPLOYEE_FILTER}, {"_id": 0})
        if emp:
            return emp

    return None


async def require_my_employee(db, user: dict) -> dict:
    """Sama seperti `resolve_my_employee` tapi melempar 404 yang JELAS."""
    emp = await resolve_my_employee(db, user)
    if not emp:
        raise HTTPException(
            404,
            "Akun Anda belum ditautkan ke data karyawan. Minta Admin HR menautkan "
            "lewat menu Data Karyawan → Tautkan Akun.",
        )
    return emp


async def resolve_employee_for(db, user: dict, requested_id: Optional[str] = None) -> dict:
    """Karyawan yang menjadi SASARAN aksi.

    · `requested_id` kosong → karyawan milik user (self-service).
    · `requested_id` = karyawan sendiri → boleh.
    · `requested_id` = karyawan LAIN → hanya HR/admin (else 403).

    Dipakai semua endpoint TULIS absensi supaya tidak bisa "titip absen".
    """
    mine = await resolve_my_employee(db, user)
    if not requested_id:
        if not mine:
            raise HTTPException(
                404,
                "Akun Anda belum ditautkan ke data karyawan. Minta Admin HR menautkan "
                "lewat menu Data Karyawan → Tautkan Akun.",
            )
        return mine

    if mine and mine.get("id") == requested_id:
        return mine

    if not is_hr(user):
        raise HTTPException(
            403,
            "Anda hanya boleh melakukan absensi untuk diri sendiri. "
            "Pencatatan atas nama karyawan lain hanya untuk HR/Supervisor.",
        )

    emp = await db.rahaza_employees.find_one({"id": requested_id}, {"_id": 0})
    if not emp:
        raise HTTPException(404, "Karyawan tidak ditemukan.")
    return emp


# ═════════════════════════════════════════════════════════════════════════════
# KETERLAMBATAN & PULANG CEPAT — dasar "POTONGAN TERLAMBAT" & "BONUS KEHADIRAN"
# ═════════════════════════════════════════════════════════════════════════════
# Toleransi bawaan (setelan global lama). 2026-11-09 (Q4, keputusan owner): toleransi BISA diatur per shift
# (`rahaza_shifts.toleransi_menit`, dibaca `core.attendance_rules._shape`); shift tanpa isian memakai nilai ini.
# Perilaku dipertahankan: menit terlambat = selisih − toleransi (masuk 08:20, toleransi 5 → 15 menit).
DEFAULT_GRACE_MINUTES = 5

# Alasan menit terlambat/pulang cepat = 0 (disimpan di `late_reason` / `early_leave_reason`, tampil di rekap).
REASON_OFF_DAY = "hari libur"
REASON_LEAVE = "cuti/izin sehari penuh"
REASON_DUTY = "tugas luar"
REASON_SCHEDULE_OFF = "libur menurut jadwal shift"


def _hm(txt) -> Optional[int]:
    try:
        hh, mm = (int(x) for x in str(txt).split(":")[:2])
        return hh * 60 + mm
    except (TypeError, ValueError):
        return None


def half_day_points(shift: dict) -> tuple:
    """(akhir paruh pagi, awal paruh siang) dalam MENIT sejak jam masuk shift — 2026-11-09 (Q5).

    Jam mulai istirahat diatur (`istirahat_mulai` di master shift → `break_start`) → pagi berakhir saat istirahat
    mulai, siang mulai sesudah istirahat (mulai + lama istirahat). Tidak diatur → istirahat diletakkan di tengah jam
    kerja: kerja = rentang shift − istirahat; paruh pagi = kerja ÷ 2; paruh siang mulai sesudah istirahat.
    Istirahat tidak diatur (0) → keduanya = jam masuk + separuh rentang shift.
    Contoh 08:00–16:00 istirahat 60 menit → pagi s.d. 11:30, siang mulai 12:30; istirahat 12:00 → 12:00 / 13:00."""
    st, en = _hm(shift.get("start_time")), _hm(shift.get("end_time"))
    span = 8 * 60 if st is None or en is None else ((en - st) % (24 * 60) or 24 * 60)
    brk = max(0, min(int(shift.get("break_minutes") or 0), span))
    bs = _hm(shift.get("break_start"))
    if bs is not None and st is not None:
        off = (bs - st) % (24 * 60)
        if 0 < off < span:
            return off, min(span, off + brk)
    work = span - brk
    return work // 2, work // 2 + brk


async def attendance_day_context(db, emp: dict, day: str) -> dict:
    """Keadaan satu hari kerja karyawan untuk terlambat / pulang cepat (2026-11-09, H5 + Q5 + Q11).

    Return {workday, leave: None|'full'|'AM'|'PM', duty: bool}. Cuti/izin/sakit DISETUJUI dibaca dari catatan absen
    hari itu (`leave_request_id`) atau pengajuan disetujui yang menutup tanggalnya; tugas luar dari tanda
    `tugas_luar` di catatan absen (ditulis saat dinas disetujui, `core.tugas_luar`)."""
    from core.workdays import get_work_calendar, holiday_set, is_working_day
    day = str(day)[:10]
    emp_id = (emp or {}).get("id")
    out = {"workday": True, "leave": None, "duty": False}
    cal = await get_work_calendar(db)
    out["workday"] = is_working_day(day, cal["off_weekdays"], await holiday_set(db, day, day))
    if not emp_id:
        return out
    rec = await db.rahaza_attendance_events.find_one(
        {"employee_id": emp_id, "date": day},
        {"_id": 0, "leave_request_id": 1, "half_day": 1, "half_day_period": 1, "tugas_luar": 1}) or {}
    out["duty"] = bool(rec.get("tugas_luar"))
    if rec.get("leave_request_id"):
        lv = await db.rahaza_leave_requests.find_one(
            {"id": rec["leave_request_id"], "status": "approved"},
            {"_id": 0, "is_half_day": 1, "half_day": 1, "half_day_period": 1})
        lv = lv or {"is_half_day": rec.get("half_day"), "half_day_period": rec.get("half_day_period")}
    else:
        lv = await db.rahaza_leave_requests.find_one(
            {"employee_id": emp_id, "status": "approved", "from_date": {"$lte": day}, "to_date": {"$gte": day}},
            {"_id": 0, "is_half_day": 1, "half_day": 1, "half_day_period": 1})
    if lv:
        if lv.get("is_half_day") or lv.get("half_day"):
            period = str(lv.get("half_day_period") or rec.get("half_day_period") or "AM").upper()
            out["leave"] = "PM" if period == "PM" else "AM"
        else:
            out["leave"] = "full"
    return out


def _zero_reason(ctx: dict, shift: Optional[dict]) -> Optional[str]:
    if ctx.get("duty"):
        return REASON_DUTY
    if ctx.get("leave") == "full":
        return REASON_LEAVE
    # Hari libur/Minggu: masuk = lembur, bukan terlambat — kecuali Jadwal Shift TERBIT memang menjadwalkannya.
    if not ctx.get("workday") and (shift or {}).get("source") != "jadwal":
        return REASON_OFF_DAY
    return None


async def compute_late_minutes(db, emp: dict, clock_in_utc: datetime,
                               shift_id: Optional[str] = None) -> dict:
    """Hitung keterlambatan terhadap jam masuk shift.

    Sebelumnya sistem TIDAK PERNAH membandingkan `clock_in` dengan jam shift,
    sehingga kolom "POTONGAN TERLAMBAT" di sheet THP user mustahil diisi.

    2026-11-09 (H5, audit HR — bug pasti): dulu hanya membandingkan jam masuk dengan jam masuk shift tanggal itu.
    Akibatnya cuti setengah hari pagi + masuk 12:30 tercatat 265 menit terlambat, dan lembur hari Minggu masuk 10:00
    tercatat 115 menit (potongan + bonus hangus). Sekarang: hari libur/Minggu (tanpa jadwal terbit), cuti sehari
    penuh, dan tugas luar → 0; cuti setengah hari PAGI → acuan = awal paruh siang (sesudah istirahat, Q5).

    Mengembalikan dict siap-simpan (selalu ada kuncinya, supaya laporan tidak
    perlu menebak): `{late_minutes, is_late, shift_code, shift_start, grace_minutes, late_reason}`
    """
    out = {"late_minutes": 0, "is_late": False, "shift_code": None,
           "shift_start": None, "grace_minutes": DEFAULT_GRACE_MINUTES, "late_reason": None}
    if not clock_in_utc:
        return out

    if clock_in_utc.tzinfo is None:
        clock_in_utc = clock_in_utc.replace(tzinfo=timezone.utc)
    local = clock_in_utc.astimezone(WIB)
    day = local.date().isoformat()

    # Tahap 2 (2026-11-06): shift yang BERLAKU hari itu — shift record → Jadwal Shift terbit → penugasan shift
    # → shift bawaan karyawan (core.attendance_rules.resolve_day_shift). Dulu selalu shift bawaan karyawan,
    # sehingga jadwal di menu Shift tidak berpengaruh pada keterlambatan.
    from core.attendance_rules import resolve_day_shift
    shift = await resolve_day_shift(db, emp, day, shift_id)
    if not shift:
        # Tanpa shift → tidak bisa menyimpulkan terlambat. Jangan mengarang. Libur menurut Jadwal Shift terbit
        # (entri `libur: true`) diberi alasan supaya rekap & saran koreksi AI tahu sebabnya.
        from core.attendance_rules import scheduled_day_off
        if not shift_id and await scheduled_day_off(db, emp, day):
            out["late_reason"] = REASON_SCHEDULE_OFF
        return out

    start_txt = shift["start_time"]
    grace_raw = shift.get("grace_minutes")
    grace = DEFAULT_GRACE_MINUTES if grace_raw in (None, "") else int(grace_raw)   # 0 = tanpa toleransi (Q4)
    out.update({"shift_code": shift.get("code"), "shift_start": start_txt, "shift_source": shift.get("source"),
                "grace_minutes": grace})
    ctx = await attendance_day_context(db, emp, day)
    reason = _zero_reason(ctx, shift)
    if reason:
        out["late_reason"] = reason
        return out

    hh, mm = (int(x) for x in start_txt.split(":")[:2])
    scheduled = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if ctx.get("leave") == "AM":
        scheduled += timedelta(minutes=half_day_points(shift)[1])
        out["shift_start"] = scheduled.strftime("%H:%M")
        out["late_reason"] = "cuti setengah hari pagi: acuan sesudah istirahat"
    diff = int((local - scheduled).total_seconds() // 60)
    out["late_minutes"] = max(0, diff - grace) if diff > grace else 0
    out["is_late"] = out["late_minutes"] > 0
    return out


async def compute_early_leave_minutes(db, emp: dict, clock_out_utc, day: Optional[str] = None,
                                      shift_id: Optional[str] = None) -> dict:
    """Menit PULANG CEPAT terhadap jam pulang shift — 2026-11-09 (Q3, keputusan owner: DICATAT & tampil di rekap,
    TIDAK memotong gaji/bonus). `day` = tanggal kerja catatan absen (shift malam pulang besoknya).

    Hari libur (tanpa jadwal terbit), cuti sehari penuh, dan tugas luar → 0; cuti setengah hari SIANG → acuan =
    akhir paruh pagi. Tanpa toleransi. Return {early_leave_minutes, shift_end, early_leave_reason}."""
    out = {"early_leave_minutes": 0, "shift_end": None, "early_leave_reason": None}
    from core.attendance_rules import _aware, resolve_day_shift, shift_end_utc
    cout = _aware(clock_out_utc)
    if not cout:
        return out
    day = str(day or cout.astimezone(WIB).date().isoformat())[:10]
    shift = await resolve_day_shift(db, emp, day, shift_id)
    if not shift or not shift.get("end_time"):
        from core.attendance_rules import scheduled_day_off
        if not shift and not shift_id and await scheduled_day_off(db, emp, day):
            out["early_leave_reason"] = REASON_SCHEDULE_OFF
        return out
    end = shift_end_utc(day, shift)
    out["shift_end"] = shift["end_time"]
    ctx = await attendance_day_context(db, emp, day)
    reason = _zero_reason(ctx, shift)
    if reason:
        out["early_leave_reason"] = reason
        return out
    if ctx.get("leave") == "PM":
        start = datetime.combine(date.fromisoformat(day), time(0, 0), tzinfo=WIB) + \
            timedelta(minutes=_hm(shift["start_time"]) or 0)
        end = (start + timedelta(minutes=half_day_points(shift)[0])).astimezone(timezone.utc)
        out["shift_end"] = end.astimezone(WIB).strftime("%H:%M")
        out["early_leave_reason"] = "cuti setengah hari siang: acuan akhir paruh pagi"
    out["early_leave_minutes"] = max(0, int((end - cout).total_seconds() // 60))
    return out

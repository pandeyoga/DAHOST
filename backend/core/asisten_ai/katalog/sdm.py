"""Katalog data — karyawan dan absensi harian (Portal SDM).

Sumber (penulis diverifikasi):
  * `rahaza_employees` — `routes/rahaza_master.py` (buat/ubah/nonaktif), `routes/rahaza_resignation.py`,
    `core/employee_data_change.py`. Aktif = `{"active": True}`; status kerja `employee_status`.
  * gaji `rahaza_payroll_profiles` — `routes/rahaza_payroll_profiles.py` (`base_rate`, `pay_scheme`,
    `overtime_rate`). Hanya untuk `PERAN_GAJI` (keputusan owner no. 1 / K27).
  * absensi `rahaza_attendance_events` — satu dok per (karyawan, tanggal WIB); status baku
    `core.attendance_rules` (alfa/alpha/absent = alpa).
Data pribadi (NIK, NPWP, BPJS, rekening, HP, email, alamat, tanggal lahir, agama, kontak darurat, foto, lokasi
absen) TIDAK dimasukkan. Nama karyawan asli hanya untuk owner/superadmin/SDM; peran lain mendapat kode KRY-xxx.
"""
from __future__ import annotations

from core.asisten_ai.katalog_data import Akses, Dataset, Gabung, Kolom, e_teks
from core.attendance_rules import ABSENT_ALIASES, ATTENDANCE_STATUSES

_PERAN_SDM = ("manager_hr", "hr_manager")
AKSES_KARYAWAN = Akses(portal=("hr",), peran=_PERAN_SDM, modul=("hr_employees",))
AKSES_ABSENSI = Akses(portal=("hr",), peran=_PERAN_SDM, modul=("hr_attendance",))
# Status baku = `core.attendance_rules.normalize_status`: kosong → hadir, alias alpa → alpa, present → hadir,
# selain itu huruf kecil apa adanya.
_S = {"$toLower": {"$trim": {"input": {"$ifNull": [e_teks("$status"), ""]}}}}
EKSPR_STATUS = {"$let": {"vars": {"s": _S}, "in": {"$switch": {"branches": [
    {"case": {"$in": ["$$s", ["", "present"]]}, "then": "hadir"},
    {"case": {"$in": ["$$s", list(ABSENT_ALIASES)]}, "then": "alpa"},
], "default": "$$s"}}}}

DATASET = (
    Dataset(
        id="karyawan",
        label="Data karyawan",
        keterangan=("Daftar karyawan: kode, nama, departemen, jabatan, lokasi, shift, jenis kontrak, tanggal masuk/"
                    "keluar, status kerja. Gaji hanya terlihat oleh owner/SDM."),
        koleksi="rahaza_employees", domain="sdm", akses=AKSES_KARYAWAN, kolom_tanggal="tanggal_masuk",
        gabung=(Gabung("_lok", "rahaza_locations", "location_id", "id", ambil=("name",)),
                Gabung("_gaji", "rahaza_payroll_profiles", "id", "employee_id",
                       ambil=("base_rate", "pay_scheme", "overtime_rate"), saringan={"active": {"$ne": False}})),
        kolom=(
            Kolom("kode_karyawan", "Kode karyawan", "teks", path="employee_code"),
            Kolom("nama", "Nama", "teks", path="name", samaran="karyawan"),
            Kolom("departemen", "Departemen", "teks", path="department"),
            Kolom("jabatan", "Jabatan", "teks", path="job_title"),
            Kolom("lokasi", "Lokasi kerja", "teks", path="_lok.name", cadangan=("location_name",)),
            Kolom("shift", "Shift", "teks", path="shift_code", bawaan=False),
            Kolom("jenis_kontrak", "Jenis kontrak", "teks", path="contract_type",
                  nilai=("PKWT", "PKWTT", "Magang", "Tetap")),
            Kolom("akhir_kontrak", "Akhir kontrak", "tanggal", path="contract_end_date", simpan="teks", bawaan=False),
            Kolom("tanggal_masuk", "Tanggal masuk", "tanggal", path="join_date", simpan="teks"),
            Kolom("tanggal_keluar", "Tanggal keluar", "tanggal", path="resign_date",
                  cadangan=("last_working_date", "resignation_date"), simpan="teks"),
            Kolom("status_kerja", "Status kerja", "teks", path="employee_status",
                  nilai=("active", "resigning", "resigned", "terminated", "retired")),
            Kolom("aktif", "Aktif", "ya_tidak", path="active"),
            Kolom("skema_gaji", "Skema gaji", "teks", path="_gaji.pay_scheme", rahasia="gaji",
                  nilai=("monthly", "weekly", "hourly", "pcs")),
            Kolom("gaji_pokok", "Gaji/tarif dasar", "uang", path="_gaji.base_rate", rahasia="gaji",
                  keterangan="Sesuai skema: per bulan, per minggu, per jam, atau per pcs."),
            Kolom("tarif_lembur", "Tarif lembur", "uang", path="_gaji.overtime_rate", rahasia="gaji", bawaan=False),
        ),
        catatan=("Karyawan aktif: saring aktif = true. Jumlah per departemen: kelompok departemen + hitung.",),
    ),
    Dataset(
        id="absensi",
        label="Absensi harian",
        keterangan=("Catatan absensi per karyawan per hari: status (hadir, izin, sakit, cuti, alpa, libur), "
                    "terlambat, jam kerja, lembur."),
        koleksi="rahaza_attendance_events", domain="sdm", akses=AKSES_ABSENSI, kolom_tanggal="tanggal",
        gabung=(Gabung("_kry", "rahaza_employees", "employee_id", "id",
                       ambil=("employee_code", "name", "department", "job_title")),),
        kolom=(
            Kolom("tanggal", "Tanggal", "tanggal", path="date", simpan="teks"),
            Kolom("kode_karyawan", "Kode karyawan", "teks", path="_kry.employee_code"),
            Kolom("nama", "Nama", "teks", path="_kry.name", samaran="karyawan"),
            Kolom("departemen", "Departemen", "teks", path="_kry.department"),
            Kolom("jabatan", "Jabatan", "teks", path="_kry.job_title", bawaan=False),
            Kolom("status", "Status", "teks", ekspr=EKSPR_STATUS,
                  nilai=ATTENDANCE_STATUSES),
            Kolom("terlambat", "Terlambat", "ya_tidak", path="is_late"),
            Kolom("menit_terlambat", "Menit terlambat", "angka", path="late_minutes"),
            Kolom("jam_kerja", "Jam kerja bersih", "angka", path="net_hours_worked", cadangan=("hours_worked",)),
            Kolom("jam_lembur", "Jam lembur", "angka", path="overtime_hours"),
            Kolom("setengah_hari", "Setengah hari", "ya_tidak", path="half_day", bawaan=False),
            Kolom("jenis_cuti", "Jenis cuti/izin", "teks", path="leave_type_name", bawaan=False),
            Kolom("sumber", "Sumber catatan", "teks", path="source", bawaan=False,
                  nilai=("operator", "supervisor", "selfie_geo_ai", "webauthn", "device_zkteco", "leave", "koreksi")),
            Kolom("jam_masuk", "Jam masuk (WIB)", "waktu", path="clock_in", simpan="datetime_utc", bawaan=False),
            Kolom("jam_pulang", "Jam pulang (WIB)", "waktu", path="clock_out", simpan="datetime_utc", bawaan=False),
        ),
        catatan=("Satu baris = satu karyawan pada satu hari. Hari tanpa catatan tidak muncul (bukan berarti alpa). "
                 "Laporan SDM menghitung setengah hari sebagai 0,5 hari.",),
    ),
)

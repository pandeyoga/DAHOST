"""Tombol saran Asisten AI per peran (Kontrak B: `GET /api/asisten-ai/saran` → `[{teks}]`).

Empat analisis lama "AI Business Intelligence" (ringkasan harian, prakiraan omzet, deteksi
kejanggalan, optimasi produksi) kini menjadi saran chat.
"""
from __future__ import annotations

SARAN_MANAJEMEN = ("Ringkasan hari ini", "Omzet bulan ini per toko", "Prakiraan omzet",
                   "Cek kejanggalan transaksi", "Buat laporan bulanan")

_PERAN_MANAJEMEN = {"owner", "superadmin", "admin", "manager", "director", "ceo", "cfo", "dept_head"}

_PER_PERAN = {
    "manager_keuangan": ("Ringkasan hari ini", "Laba rugi bulan ini", "Piutang jatuh tempo minggu ini",
                         "Arus kas bulan ini", "Cek kejanggalan transaksi", "Buat laporan bulanan"),
    "manager_marketing": ("Omzet bulan ini per toko", "Iklan dan ROAS bulan ini", "Performa live minggu ini",
                          "Prakiraan omzet", "Buat laporan bulanan"),
    "manager_produksi": ("Ringkasan hari ini", "Produksi bulan ini", "PO produksi yang terlambat",
                         "Rekomendasi produksi", "Buat laporan bulanan"),
    "hr_manager": ("Ringkasan hari ini", "Kehadiran bulan ini", "Ringkasan SDM bulan ini", "Buat laporan bulanan"),
    "manager_hr": ("Ringkasan hari ini", "Kehadiran bulan ini", "Ringkasan SDM bulan ini", "Buat laporan bulanan"),
}


# Audit HR Tahap D (9 Nov 2026): saran per ruang. Portal SDM — per peran SDM (Staf HR tanpa akses run gaji tidak
# ditawari cek payroll). Portal Saya — data milik sendiri.
SARAN_SDM = ("Rekap absensi & pengecualian minggu ini", "Siapa yang lupa absen pulang kemarin?",
             "Cek payroll sebelum finalisasi", "Susun draf shift minggu depan untuk tim packing",
             "Cakupan shift minggu depan per departemen", "Cuti dan lembur yang menunggu persetujuan")
_SDM_PER_PERAN = {
    "staff_hr": ("Rekap absensi & pengecualian minggu ini", "Siapa yang lupa absen pulang kemarin?",
                 "Cakupan shift minggu depan per departemen", "Susun draf shift minggu depan untuk tim packing",
                 "Cuti dan lembur yang menunggu persetujuan"),
}
SARAN_SAYA = ("Sisa cuti saya tahun ini", "Rekap absen saya bulan ini", "Rincian slip gaji terakhir saya",
              "Shift saya minggu depan", "Kenapa ada potongan di gaji saya?")


def saran_untuk(peran: str | None, ruang: str | None = None) -> list[dict]:
    p = str(peran or "").strip().lower()
    if ruang == "saya":
        return [{"teks": t} for t in SARAN_SAYA]
    if ruang == "sdm":
        return [{"teks": t} for t in _SDM_PER_PERAN.get(p, SARAN_SDM)]
    if p in _PERAN_MANAJEMEN:
        daftar = SARAN_MANAJEMEN
    else:
        daftar = _PER_PERAN.get(p, SARAN_MANAJEMEN)
    return [{"teks": t} for t in daftar]

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


def saran_untuk(peran: str | None) -> list[dict]:
    p = str(peran or "").strip().lower()
    if p in _PERAN_MANAJEMEN:
        daftar = SARAN_MANAJEMEN
    else:
        daftar = _PER_PERAN.get(p, SARAN_MANAJEMEN)
    return [{"teks": t} for t in daftar]

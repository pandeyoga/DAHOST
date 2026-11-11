"""Bulan Marketing = tanggal 26 bulan sebelumnya s/d tanggal 25 bulan itu.

Owner 11 Nov 2026: "target bulanan cutoffnya dari tanggal 26 - 25, sekarang masih awal bulan
ke akhir bulan, perbaiki ini".

* Bulan dinamai menurut bulan tempat periodenya BERAKHIR: target **November 2026** dihitung
  dari 26 Okt 2026 sampai 25 Nov 2026.
* Mulai tanggal 26, bulan berjalan sudah bulan berikutnya (26 Nov 2026 → Desember 2026).
* Data yang tersimpan per (tahun, bulan) — target toko, target kreator, kunci periode,
  anggaran bulanan — tidak berubah bentuk; hanya rentang tanggal yang dibaca untuk
  realisasinya yang mengikuti aturan ini.

Ini SATU-SATUNYA tempat aturan tanggal tutup ditulis. Semua pembaca target/realisasi
bulanan Marketing memakai fungsi di sini; jangan menulis ``f"{y}-{m}-01"`` lagi.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional, Tuple, Union

HARI_TUTUP = 25          # tanggal terakhir satu bulan Marketing
_NAMA = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")

Tanggal = Union[str, date, datetime]


def _sebelum(y: int, m: int) -> Tuple[int, int]:
    return (y - 1, 12) if m == 1 else (y, m - 1)


def _sesudah(y: int, m: int) -> Tuple[int, int]:
    return (y + 1, 1) if m == 12 else (y, m + 1)


def rentang_date(y: int, m: int) -> Tuple[date, date]:
    """(awal, akhir) inklusif sebagai ``date``: 26 bulan lalu … 25 bulan ini."""
    py, pm = _sebelum(int(y), int(m))
    return date(py, pm, HARI_TUTUP + 1), date(int(y), int(m), HARI_TUTUP)


def rentang(y: int, m: int) -> Tuple[str, str]:
    """(awal, akhir) inklusif sebagai ``'YYYY-MM-DD'``."""
    a, b = rentang_date(y, m)
    return a.isoformat(), b.isoformat()


def rentang_periode(period: str) -> Tuple[str, str]:
    """``'YYYY-MM'`` → (awal, akhir) inklusif ``'YYYY-MM-DD'``."""
    return rentang(int(period[:4]), int(period[5:7]))


def rentang_utc(y: int, m: int) -> Tuple[datetime, datetime]:
    """[awal, akhir+1 hari) sebagai datetime UTC tengah malam — untuk field bertipe datetime."""
    a, b = rentang_date(y, m)
    return (datetime(a.year, a.month, a.day, tzinfo=timezone.utc),
            datetime(b.year, b.month, b.day, tzinfo=timezone.utc) + timedelta(days=1))


def _ke_date(tgl: Tanggal) -> date:
    if isinstance(tgl, datetime):
        return tgl.date()
    if isinstance(tgl, date):
        return tgl
    s = str(tgl)[:10]
    return date(int(s[:4]), int(s[5:7]), int(s[8:10]))


def bulan_dari(tgl: Tanggal) -> Tuple[int, int]:
    """Tanggal → (tahun, bulan) Marketing tempat tanggal itu jatuh."""
    d = _ke_date(tgl)
    if d.day > HARI_TUTUP:
        return _sesudah(d.year, d.month)
    return d.year, d.month


def periode_dari(tgl: Tanggal) -> str:
    """Tanggal → ``'YYYY-MM'`` bulan Marketing (``'2026-10-27'`` → ``'2026-11'``)."""
    y, m = bulan_dari(tgl)
    return f"{y:04d}-{m:02d}"


def bulan_berjalan(hari_ini: Optional[Tanggal] = None) -> Tuple[int, int]:
    """(tahun, bulan) Marketing hari ini (WIB bila ``hari_ini`` kosong)."""
    if hari_ini is None:
        from utils.waktu import now_wib  # impor lokal: modul ini tetap bebas ketergantungan
        hari_ini = now_wib()
    return bulan_dari(hari_ini)


def jumlah_hari(y: int, m: int) -> int:
    a, b = rentang_date(y, m)
    return (b - a).days + 1


def hari_berlalu(y: int, m: int, hari_ini: Tanggal) -> int:
    """Hari yang sudah lewat di bulan Marketing itu, termasuk hari ini (0 bila belum mulai)."""
    a, b = rentang_date(y, m)
    d = _ke_date(hari_ini)
    if d < a:
        return 0
    if d > b:
        return (b - a).days + 1
    return (d - a).days + 1


def label(y: int, m: int) -> str:
    """``'26 Okt – 25 Nov 2026'``."""
    a, b = rentang_date(y, m)
    kiri = f"{a.day} {_NAMA[a.month - 1]}" + (f" {a.year}" if a.year != b.year else "")
    return f"{kiri} – {b.day} {_NAMA[b.month - 1]} {b.year}"

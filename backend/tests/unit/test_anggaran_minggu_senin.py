"""Periode anggaran mingguan dimulai hari Senin (owner 11 Nov 2026)."""
from datetime import datetime, timedelta

from routes.marketing_budget import awal_periode_berjalan, period_bounds


def test_rabu_jatuh_ke_senin_minggu_ini():
    # 11 Nov 2026 = Rabu → minggu berjalan 9–15 Nov
    assert awal_periode_berjalan("2026-11-11", "weekly", 7) == "2026-11-09"
    assert period_bounds("2026-11-09", 7) == ("2026-11-09", "2026-11-15")


def test_senin_dan_minggu():
    assert awal_periode_berjalan("2026-11-09", "weekly", 7) == "2026-11-09"   # Senin
    assert awal_periode_berjalan("2026-11-15", "weekly", 7) == "2026-11-09"   # Minggu


def test_kelipatan_tujuh_tetap_senin():
    assert awal_periode_berjalan("2026-11-12", "weekly", 14) == "2026-11-09"


def test_panjang_bukan_kelipatan_tujuh_mulai_hari_ini():
    assert awal_periode_berjalan("2026-11-11", "weekly", 10) == "2026-11-11"


def test_bulanan():
    assert awal_periode_berjalan("2026-11-11", "monthly", 7) == "2026-11"
    assert awal_periode_berjalan("2026-11-27", "monthly", 7) == "2026-12"   # bulan Marketing 26–25


def test_daftar_mundur_selalu_senin():
    start = datetime.strptime(awal_periode_berjalan("2026-11-13", "weekly", 7), "%Y-%m-%d")
    for i in range(12):
        assert (start - timedelta(days=7 * i)).weekday() == 0

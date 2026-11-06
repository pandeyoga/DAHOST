"""core.workdays — satu aturan hari kerja aktif (6 hari/minggu bawaan, libur Kalender Produksi)."""
from datetime import date

from core import workdays


def test_enam_hari_kerja_minggu_libur():
    assert workdays.off_weekdays_for(6) == frozenset({6})
    assert workdays.off_weekdays_for(5) == frozenset({5, 6})


def test_november_2026_ada_25_hari_kerja_tanpa_libur():
    hari = workdays.working_days_between(date(2026, 11, 1), date(2026, 11, 30), workdays.off_weekdays_for(6), set())
    assert len(hari) == 25


def test_libur_kalender_produksi_dikurangi():
    hari = workdays.working_days_between("2026-11-16", "2026-11-30", workdays.off_weekdays_for(6), {"2026-11-17"})
    assert len(hari) == 12  # 13 hari kerja dikurangi 1 libur

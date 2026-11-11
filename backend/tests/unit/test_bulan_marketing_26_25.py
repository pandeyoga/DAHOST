"""Bulan Marketing = tanggal 26 bulan lalu s/d 25 (owner 11 Nov 2026: "target bulanan cutoffnya dari tanggal 26 - 25")."""
from datetime import date, datetime, timezone

from core import bulan_marketing as B
from core import marketing_cycle as C


def test_rentang_dan_nama_bulan():
    assert B.rentang(2026, 11) == ("2026-10-26", "2026-11-25")
    assert B.rentang(2027, 1) == ("2026-12-26", "2027-01-25")          # lintas tahun
    assert B.jumlah_hari(2026, 11) == 31 and B.jumlah_hari(2026, 3) == 28
    assert B.label(2026, 11) == "26 Okt – 25 Nov 2026"
    assert B.label(2027, 1) == "26 Des 2026 – 25 Jan 2027"


def test_tanggal_ke_bulan():
    assert B.periode_dari("2026-11-11") == "2026-11"
    assert B.periode_dari("2026-11-25") == "2026-11"
    assert B.periode_dari("2026-11-26") == "2026-12"                  # tanggal 26 sudah bulan depan
    assert B.periode_dari("2026-12-31") == "2027-01"
    assert B.bulan_berjalan(date(2026, 10, 27)) == (2026, 11)
    assert C.period_from_date("2026-10-30") == "2026-11"               # kunci periode ikut aturan yang sama


def test_hari_berlalu():
    assert B.hari_berlalu(2026, 11, "2026-10-26") == 1
    assert B.hari_berlalu(2026, 11, "2026-11-11") == 17
    assert B.hari_berlalu(2026, 11, "2026-10-01") == 0
    assert B.hari_berlalu(2026, 11, "2026-12-01") == 31


def test_siklus_dan_anggaran_bulanan_pakai_26_25():
    from routes.marketing_budget import awal_periode_berjalan, period_bounds
    assert C.period_range("2026-11") == ("2026-10-26", "2026-11-25")
    assert period_bounds("2026-11") == ("2026-10-26", "2026-11-25")
    assert awal_periode_berjalan("2026-11-26", "monthly") == "2026-12"
    p = C.month_progress("2026-11", datetime(2026, 11, 11, 5, tzinfo=timezone.utc))
    assert (p["days_total"], p["days_elapsed"], p["month_state"]) == (31, 17, "running")
    assert (p["date_from"], p["date_to"]) == ("2026-10-26", "2026-11-25")
    assert C.month_progress("2026-11", datetime(2026, 11, 27, tzinfo=timezone.utc))["month_state"] == "closed_month"

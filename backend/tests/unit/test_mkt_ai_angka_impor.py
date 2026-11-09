"""Uji pembaca angka/tanggal/berat/nomor mesin impor (9 Nov 2026, agen MKT-AI).

Dasar: riset_laporan_marketplace_2026-11-09 §6.2 (G1, G2, G13, G20, G21, G22) & §7.5
(fixture F07, F09, F17, F19, F20, F21). Semua nilai uji sintetis — tanpa data klien.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from core import marketing_import_engine as eng  # noqa: E402
from core.marketing_import_schema import Field, get_source_type  # noqa: E402

MO = get_source_type("marketplace_orders")


# ── G1 — gaya angka per kolom ──────────────────────────────────────────────────
def test_gaya_kolom_gmv_max_titik_desimal():
    kolom = ["40797.000", "260.768", "0.000", "31836.000"]           # F07
    assert eng.gaya_angka_kolom(kolom) == eng.GAYA_TITIK_DESIMAL
    g = eng.gaya_angka_kolom(kolom)
    assert eng.parse_number("260.768", g) == (260.768, None)
    assert eng.parse_number("40797.000", g) == (40797.0, None)
    assert eng.parse_number("0.000", g) == (0.0, None)


def test_gaya_kolom_shopee_titik_ribuan_tetap_ribuan():
    # Kolom yang SEMUA nilainya ddd.ddd ambigu → dibaca seperti dulu (titik = ribuan)
    kolom = ["100.000", "21.999", "45.000"]
    assert eng.gaya_angka_kolom(kolom) == eng.GAYA_OTOMATIS
    assert eng.parse_number("21.999", eng.gaya_angka_kolom(kolom))[0] == 21999
    # Satu nilai jutaan membuktikan titik = ribuan untuk seluruh kolom
    kolom2 = kolom + ["1.250.000"]
    assert eng.gaya_angka_kolom(kolom2) == eng.GAYA_KOMA_DESIMAL
    assert eng.parse_number("94.344,64", eng.GAYA_KOMA_DESIMAL)[0] == 94344.64


def test_gaya_kolom_bertentangan_tidak_menebak():
    assert eng.gaya_angka_kolom(["12.5", "1.250.000"]) == eng.GAYA_OTOMATIS
    assert eng.gaya_angka_kolom([1000, 2.5, None, ""]) == eng.GAYA_OTOMATIS


def test_build_rows_memakai_gaya_seluruh_kolom():
    """Baris pertama ambigu ('260.768') dibaca benar karena baris lain membuktikan gayanya."""
    st = get_source_type("tiktok_gmv_max")
    rows = [{"spend": "260.768"}, {"spend": "40797.000"}]
    used = {"spend": "spend"}
    prof = eng.profil_kolom(rows, used, st)
    assert prof["spend"]["gaya"] == eng.GAYA_TITIK_DESIMAL
    d, err, _ = eng._coerce_row(rows[0], used, st, None, prof)
    assert d["spend"] == pytest.approx(260.768)


# ── G2 — persen bertanda "%" tidak dikali 100 ──────────────────────────────────
@pytest.mark.parametrize("raw,expect", [("0,50%", 0.5), ("0.77%", 0.77), ("24,87%", 24.87),
                                        ("3.15%", 3.15)])
def test_persen_bertanda_tidak_dikali_seratus(raw, expect):                     # F09
    f = Field("x", "Konversi", "pct")
    v, err, _ = eng.coerce(f, raw)
    assert err is None and v == pytest.approx(expect)


def test_kolom_rasio_pecahan_diskalakan_sekali():
    st = get_source_type("tiktok_gmv_max")
    rows = [{"r": 0.0359}, {"r": 0.12}, {"r": 0}]
    used = {"r": "ctr_platform"}
    prof = eng.profil_kolom(rows, used, st)
    assert prof["r"]["skala_pecahan"] is True
    d, _, w = eng._coerce_row(rows[0], used, st, None, prof)
    assert d["ctr_platform"] == pytest.approx(3.59) and not w
    # kolom campuran (ada nilai > 1) → 0,5 tetap 0,5%
    rows2 = [{"r": "0.5"}, {"r": "12"}]
    prof2 = eng.profil_kolom(rows2, used, st)
    assert prof2["r"]["skala_pecahan"] is False
    d2, _, _ = eng._coerce_row(rows2[0], used, st, None, prof2)
    assert d2["ctr_platform"] == pytest.approx(0.5)


# ── G21/G22/F20 — tanggal bukan angka; tanggal Statistik Toko; kosong ──────────
def test_tanggal_tidak_terbaca_sebagai_uang():
    v, err = eng.parse_number("01/08/2026")
    assert v is None and "tanggal" in err
    assert eng.parse_number("00:01:19")[0] is None
    assert eng.parse_number("-50.000") == (-50000.0, None)
    assert eng.parse_number("(1.234)") == (-1234.0, None)                      # F21
    assert eng.parse_number("Rp1.234") == (1234.0, None)
    assert eng.parse_number("N/A") == (None, None)


def test_tanggal_statistik_toko_dan_penanda_kosong():
    d, err = eng.parse_date("13-08-2026 00:00")                                # G22
    assert err is None and (d.year, d.month, d.day, d.hour) == (2026, 8, 13, 0)
    assert eng.parse_date("Tidak Terbatas") == (None, None)
    assert eng.parse_date("-") == (None, None)
    v, err = eng.parse_date("13-08-2026-13-08-2026")
    assert v is None and "rentang" in err


# ── G13 — berat bersatuan ──────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,kg", [("200 gr", 0.2), ("0.6", 0.6), ("1,2 kg", 1.2), (0.35, 0.35),
                                    ("500 gram", 0.5)])
def test_berat_dibaca_dalam_kg(raw, kg):                                        # F19
    v, err, _ = eng.coerce(MO.field("weight_kg"), raw)
    assert err is None and v == pytest.approx(kg)


# ── G20 — nomor pesanan yang dirusak Excel ditolak ─────────────────────────────
@pytest.mark.parametrize("raw", ["5.85319535278917E+17", 5.85319535278917e17, 585319535278917000])
def test_nomor_pesanan_angka_ilmiah_ditolak(raw):                              # F17
    v, err, _ = eng.coerce(MO.field("order_id"), raw)
    assert v is None and "Excel" in err


def test_nomor_pesanan_teks_dan_bulat_kecil_aman():
    assert eng.coerce(MO.field("order_id"), "585055055923938626")[0] == "585055055923938626"
    assert eng.coerce(MO.field("order_id"), 1234.0)[0] == "1234"

"""Retur (G10/G11 + keputusan "Refund only") dan iklan (G3/G4 GMV Max, G24 CPC Shopee).

Berkas asli dipakai bila ada: `samples/marketplace_2026/retur_refund_tiktok.xlsx` (4 baris)
dan `samples/marketplace_2026/ads_tiktok.xlsx` (100.000 baris, 67 berbiaya). Fixture lain
sintetis berheader nyata (tanpa data klien).
"""
from __future__ import annotations

import csv
import io
import os
import sys
from pathlib import Path

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from core import marketing_import_engine as eng  # noqa: E402
from core import marketing_import_prenorm as prenorm  # noqa: E402
from core.marketing_import_schema import (  # noqa: E402
    NO_IDENTITY_REASON, SOURCE_TYPES, GROUP_OF, get_source_type, source_type_catalog)

RT = get_source_type("returns")
GMV = get_source_type("tiktok_gmv_max")
ADS = get_source_type("ads")
RET_TT = REPO / "samples" / "marketplace_2026" / "retur_refund_tiktok.xlsx"
ADS_TT = REPO / "samples" / "marketplace_2026" / "ads_tiktok.xlsx"
RET_SP = REPO / "samples" / "marketplace_2026" / "retur_refund_shopee.xls"


def _csv(head, rows):
    b = io.StringIO()
    csv.writer(b).writerows([head] + rows)
    return b.getvalue().encode("utf-8-sig")


# ── G10/G11 — retur TikTok asli ───────────────────────────────────────────────
def test_retur_tiktok_asli_status_kompensasi_dan_refund_only():                # F16
    if not RET_TT.exists():
        pytest.skip("berkas contoh retur TikTok tidak ada")
    h, rows = eng.parse_table(RET_TT.read_bytes(), RET_TT.name, RT)
    mp = eng.auto_map(h, RT)
    m = {x["column"]: x["field"] for x in mp}
    assert m["Compensation Amount"] == "compensation_amount"      # bukan refund ke pembeli
    assert m["Return unit price"] == "price"
    assert m["Return Sub Status"] == "substatus_raw"
    built = eng.build_rows(rows, mp, RT)
    st = [(b["data"]["status_raw"], b["data"]["status"]) for b in built]
    assert ("To Process", "pending") in st and ("In Process", "pending") in st
    assert ("Refund rejected", "rejected") in st
    assert all(b["status"] != "error" for b in built)
    jenis = {b["data"]["refund_type_raw"]: b["data"]["goods_returned"] for b in built}
    assert jenis == {"Return and refund": True, "Refund only": False}
    assert {b["data"]["reason"] for b in built} >= {"salah_kirim", "berubah_pikiran", "barang_kurang"}


def test_retur_shopee_header_asli_dan_status_resmi():
    if RET_SP.exists():
        h, _ = eng.parse_table(RET_SP.read_bytes(), RET_SP.name, RT)
        m = {x["column"]: x["field"] for x in eng.auto_map(h, RT)}
        assert m["Jumlah Kompensasi"] == "compensation_amount"
        assert m["Total Pengembalian Dana"] == "refund_amount"
    head = ["No. Pengembalian", "No. Pesanan", "Waktu Pengembalian Diajukan", "Nama Produk",
            "Status Pembatalan/ Pengembalian", "Solusi Pengembalian Barang/Dana", "Alasan Pengembalian"]
    rows = [["R1", "P1", "2026-10-01 10:00", "Kaos", "Dana Dikembalikan ke Pembeli", "Pengembalian Dana", "Barang rusak"],
            ["R2", "P2", "2026-10-01 10:00", "Kaos", "Ditolak/Dibatalkan", "Pengembalian Barang dan Dana", "Lainnya"],
            ["R3", "P3", "2026-10-01 10:00", "Kaos", "Sedang Ditinjau", "Pengembalian Barang dan Dana", "Lainnya"]]
    h, t = eng.parse_table(_csv(head, rows), "retur.csv", RT)
    built = {b["data"]["return_id"]: b["data"] for b in eng.build_rows(t, eng.auto_map(h, RT), RT)}
    assert built["R1"]["status"] == "completed" and built["R1"]["goods_returned"] is False
    assert built["R2"]["status"] == "rejected" and built["R2"]["goods_returned"] is True
    assert built["R3"]["status"] == "pending"


# ── G3/G4 — GMV Max jenis sendiri ─────────────────────────────────────────────
GMV_HEAD = ["Nama kampanye", "ID Campaign", "ID produk", "Jenis materi iklan", "Judul video", "ID video",
            "Akun TikTok", "Waktu posting", "Status", "Status sekunder penjelajahan", "Jenis otorisasi", "Biaya",
            "Pesanan SKU", "Biaya per pesanan", "Pendapatan kotor", "Impresi iklan produk",
            "Jumlah klik iklan produk", "Tingkat klik iklan produk", "Rasio konversi iklan", "Mata uang"]


def _gmv_xlsx(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(GMV_HEAD)
    for r in rows:
        ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


GMV_ROWS = [  # F07/F08 — titik desimal 3 angka, kartu produk tanpa video, baris nol
    ["K1", "1700000000000001", "1730000000000000001", "Video", "judul", "7600000000000000001", "akun_uji",
     "2024-06-01 10:00", "Dijelajahi", "Unggulan", "Resmi", "260.768", 1, "260.768", "50000.500", 100, 5, 0.05, 0.2, "IDR"],
    ["K1", "1700000000000001", "1730000000000000001", "Kartu produk", "-", "-", "-",
     "-", "Dijelajahi", "-", "N/A", "40797.000", 6, "6799.500", "1138382.100", 0, 0, 0.0, 0.0, "IDR"],
    ["K2", "1700000000000002", "1730000000000000002", "Video", "judul", "7600000000000000002", "akun_uji",
     "2025-01-01 10:00", "Tidak memenuhi syarat", "-", "N/A", "0.000", 0, "0.000", "0.000", 0, 0, 0.0, 0.0, "IDR"],
]


def test_gmv_max_wajib_periode_dan_tidak_dibaca_apa_adanya():
    raw = _gmv_xlsx(GMV_ROWS)
    with pytest.raises(prenorm.PrenormBlocked) as e:
        eng.parse_table_lenient(raw, "gmvmax.xlsx", GMV)
    assert "Periode laporan GMV Max wajib" in str(e.value)
    with pytest.raises(prenorm.PrenormBlocked):
        eng.parse_table_lenient(raw, "gmvmax_2026-07-15_2026-08-14.xlsx", GMV)   # lintas bulan


def test_gmv_max_periode_dari_nama_berkas_angka_dan_baris_nol():
    raw = _gmv_xlsx(GMV_ROWS)
    name = prenorm.penanda_periode("2026-08-01", "2026-08-31", "gmvmax.xlsx")
    assert prenorm.periode_dari_nama(name) == ("2026-08-01", "2026-08-31")
    assert prenorm.periode_dari_nama("Order.all.20260801_20260831.xlsx") == ("2026-08-01", "2026-08-31")
    h, rows, w = eng.parse_table_lenient(raw, name, GMV)
    assert w is None and len(rows) == 2                     # baris biaya 0 dibuang
    mp = eng.auto_map(h, GMV)
    built = eng.build_rows(rows, mp, GMV)
    assert all(b["status"] != "error" for b in built), [b["errors"] for b in built]
    by = {b["data"]["video_id"]: b["data"] for b in built}
    assert by["7600000000000000001"]["spend"] == pytest.approx(260.768)   # bukan 260.768 rupiah ribuan
    assert by["-"]["spend"] == pytest.approx(40797.0)
    assert by["-"]["revenue"] == pytest.approx(1138382.1)
    d = by["7600000000000000001"]
    assert d["date"] == d["period_start"] == "2026-08-01" and d["period_end"] == "2026-08-31"
    assert d["source_report"] == "tiktok_gmv_max" and d["ad_platform"] == "tiktok"
    assert d["period_days"] == 31 and d["ctr_platform"] == pytest.approx(5.0)
    assert d["video_posted_at"] == "2024-06-01 10:00"      # disimpan, tapi BUKAN tanggal biaya
    assert d["roas"] == pytest.approx(round(50000.5 / 260.768, 2))


def test_ads_tidak_lagi_memakai_waktu_posting_sebagai_tanggal():
    m = {x["column"]: x["field"] for x in eng.auto_map(GMV_HEAD, ADS)}
    assert m.get("Waktu posting") is None
    best = eng.detect_source_type(_gmv_xlsx(GMV_ROWS), "gmvmax.xlsx",
                                  [get_source_type(t["key"]) for t in source_type_catalog()])["best"]
    assert best["source_type"] == "tiktok_gmv_max"


def test_gmv_max_terdaftar_di_kelompok_dan_alasan_tanpa_identitas():
    assert "tiktok_gmv_max" in SOURCE_TYPES and GROUP_OF["tiktok_gmv_max"] == "iklan"
    assert "tiktok_gmv_max" in NO_IDENTITY_REASON


@pytest.mark.skipif(not ADS_TT.exists(), reason="berkas GMV Max asli tidak ada")
def test_gmv_max_berkas_asli_biaya_benar_dan_peringatan_terpotong():
    """Riset G1: Σ Biaya benar Rp322.063 (mesin lama: Rp5.852.211)."""
    raw = ADS_TT.read_bytes()
    name = prenorm.penanda_periode("2026-07-01", "2026-07-31", ADS_TT.name)
    h, rows, _ = eng.parse_table_lenient(raw, name, GMV)
    assert len(rows) == 67
    built = eng.build_rows(rows, eng.auto_map(h, GMV), GMV)
    assert round(sum(b["data"]["spend"] for b in built)) == 322063
    assert all("100.000 baris" in " ".join(b["warnings"]) for b in built)


# ── G24 — ejaan lain laporan iklan CPC Shopee ─────────────────────────────────
def test_cpc_shopee_ejaan_efektivitas_dan_add_to_cart():
    meta = ["Semua Laporan Iklan CPC - Shopee Indonesia", "", "Username,uji", "Nama Toko,Toko Uji",
            "ID Toko,1", "Waktu Laporan Dibuat,01/09/2026", "Periode,01/08/2026 - 31/08/2026", ""]
    head = "Urutan,Nama Iklan,Status,Biaya,Omzet Penjualan,Efektivitas Iklan,Add to Cart,Persentase Klik"
    row = '1,Iklan Uji,Berjalan,25816.10,377986,"14,64",12,0.77%'
    raw = ("\n".join(meta + [head, row]) + "\n").encode("utf-8-sig")
    h, rows = prenorm.prenorm_shopee_ads_cpc(raw, "cpc.csv")
    assert rows[0]["roas_platform"] == "14,64" and rows[0]["add_to_cart"] == "12"
    st = get_source_type("shopee_ads_cpc")
    built = eng.build_rows(rows, eng.auto_map(h, st), st)
    assert built[0]["data"]["ctr_platform"] == pytest.approx(0.77)      # G2: bukan 77 %
    assert built[0]["data"]["spend"] == pytest.approx(25816.10)

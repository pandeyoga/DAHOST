"""Lapis deterministik: sidik jenis laporan, profil nilai, dan uji rumus (riset §7.1–7.5).

Berkas asli di `samples/` dipakai untuk membuktikan sidik & rumus; fixture F01… sintetis
berheader nyata (tanpa data klien).
"""
from __future__ import annotations

import csv
import io
import os
import random
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

from core import impor_invarian as iv  # noqa: E402
from core import impor_sidik as sd  # noqa: E402
from core import marketing_import_engine as eng  # noqa: E402
from core.marketing_import_schema import get_source_type  # noqa: E402

S = REPO / "samples"
MO = get_source_type("marketplace_orders")
CONTOH = [
    ("TikTok_UntukDikirim_2026-07-19.xlsx", "pesanan_tiktok", "marketplace_orders"),
    ("marketplace_2026/pesanan_tiktok.xlsx", "pesanan_tiktok", "marketplace_orders"),
    ("marketplace_2026/order_pesanan_shopee.xlsx", "pesanan_shopee", "marketplace_orders"),
    ("marketplace_2026/ads_shopee.csv", "iklan_cpc_shopee", "shopee_ads_cpc"),
    ("shopee/shopee_ads_cpc_contoh.csv", "iklan_cpc_shopee", "shopee_ads_cpc"),
    ("marketplace_2026/ads_tiktok.xlsx", "gmv_max_tiktok", "tiktok_gmv_max"),
    ("marketplace_2026/retur_refund_shopee.xls", "retur_shopee", "returns"),
    ("marketplace_2026/retur_refund_tiktok.xlsx", "retur_tiktok", "returns"),
    ("shopee/shopee_live_1d_contoh.csv", "live_video_shopee", "shopee_content_kpi"),
    ("shopee/shopee_video_overview_contoh.csv", "live_video_shopee", "shopee_content_kpi"),
    ("shopee/shopee_shop_stats_contoh.xlsx", "statistik_toko_shopee", "shopee_shop_kpi"),
    ("settlement_tiktok_contoh.xlsx", "penghasilan_tiktok", ""),
]


def _csv(head, rows, delim=","):
    b = io.StringIO()
    csv.writer(b, delimiter=delim).writerows([head] + rows)
    return b.getvalue().encode("utf-8-sig")


def _xlsx(sheets):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for title, rows in sheets:
        ws = wb.create_sheet(title)
        for r in rows:
            ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


@pytest.mark.parametrize("rel,jenis,st", CONTOH)
def test_sidik_mengenali_berkas_asli(rel, jenis, st):
    p = S / rel
    if not p.exists():
        pytest.skip(rel)
    h = sd.kenali(p.read_bytes(), "berkas_tanpa_petunjuk" + p.suffix)   # nama berkas bukan penentu
    assert h["dikenal"] and h["jenis"] == jenis and h["source_type"] == st, h
    assert h["bukti"]["kolom_wajib"]


def test_sidik_tiktok_baris_deskripsi_terdeteksi():                              # F01
    p = S / "marketplace_2026" / "pesanan_tiktok.xlsx"
    if not p.exists():
        pytest.skip("contoh tidak ada")
    hasil, t = sd.tabel_utama(p.read_bytes(), p.name)
    assert t.deskripsi and t.deskripsi["Order ID"].endswith(".")
    assert hasil["versi"] == "65 kolom + baris deskripsi"
    assert all(r["Order ID"] != t.deskripsi["Order ID"] for r in t.rows)       # bukan pesanan palsu


def test_sidik_tiktok_pasar_lain_dan_shopee_urutan_acak():                       # F02 · F03
    tt = ["Order ID", "Order Status", "SKU ID", "Quantity", "SKU Subtotal After Discount", "Order Amount",
          "Taxes", "Small Order Fee", "Created Time"]
    assert sd.kenali(_csv(tt, [["1", "Selesai", "2", "1", "100", "100", "0", "0", "01/10/2026"]]), "x.csv")["jenis"] \
        == "pesanan_tiktok"
    sp = ["No. Pesanan", "Status Pesanan", "Waktu Pesanan Dibuat", "Subtotal Pesanan", "Harga Setelah Diskon",
          "Jumlah", "Diskon Dari Shopee", "Nama Produk"]
    random.Random(3).shuffle(sp)
    assert sd.kenali(_csv(sp, [["x"] * len(sp)]), "y.csv")["jenis"] == "pesanan_shopee"


def test_sidik_saldo_shopee_header_baris_18_dan_penghasilan_baris_3():           # F14 · F15
    meta = [["Laporan Transaksi Saldo Penjual"], ["Username (Penjual)", "uji"], ["Dari", "2026-09-01"]] + [[]] * 14
    saldo = _xlsx([("Transaction Report", meta + [["Tanggal Transaksi", "Tipe Transaksi", "Deskripsi", "No. Pesanan",
                                                    "Jenis Transaksi", "Jumlah", "Status", "Saldo Akhir"],
                                                   ["2026-09-23", "Penarikan Dana", "-", "-", "Transaksi Keluar",
                                                    "-100000.00", "Transaksi Selesai", "0.00"]])])
    h = sd.kenali(saldo, "a.xlsx")
    assert h["jenis"] == "saldo_shopee" and h["jalur"] == sd.JALUR_PENARIKAN and h["bukti"]["baris_header"] == 18
    inc = _xlsx([("Summary", [["Ringkasan"]]),
                 ("Penghasilan", [["Informasi Pesanan", "", "", "Rincian"], ["", "", "", "Total Penghasilan"],
                                  ["No.", "Lihat berdasarkan", "No. Pesanan", "Tanggal Dana Dilepaskan",
                                   "Total Penghasilan", "Biaya Administrasi"],
                                  [1, "Order", "S1", "2026-10-05", 88000, -12000]])])
    h2 = sd.kenali(inc, "b.xlsx")
    assert h2["jenis"] == "penghasilan_shopee" and h2["jalur"] == sd.JALUR_PENCAIRAN
    assert h2["versi"].startswith("format Okt 2026") and h2["tabel"]["ada_judul_grup"]


def test_sidik_penolak_dan_berkas_tak_dikenal():
    # penghasilan TikTok punya "Total settlement amount" ⇒ bukan pesanan TikTok walau ada Order ID
    head = ["Order/adjustment ID", "Order ID", "SKU Subtotal After Discount", "Order Amount", "Total settlement amount"]
    assert sd.kenali(_csv(head, [["1"] * 5]), "z.csv")["jenis"] != "pesanan_tiktok"
    h = sd.kenali(_csv(["Kolom A", "Kolom B"], [["1", "2"]]), "shopee_entah.csv")
    assert not h["dikenal"] and h["platform"] == "shopee"           # platform dari nama = bukti lemah saja


def test_profil_nilai_tersamar_dan_tingkat_uang():
    p = S / "marketplace_2026" / "order_pesanan_shopee.xlsx"
    if not p.exists():
        pytest.skip("contoh tidak ada")
    _, t = sd.tabel_utama(p.read_bytes(), p.name)
    prof = sd.profil_nilai(t.headers, t.rows, kolom_pesanan="No. Pesanan")
    assert prof["Total Pembayaran"]["tingkat"] == "per_pesanan"
    assert prof["Subtotal Pesanan"]["tingkat"] == "per_baris"
    assert prof["Waktu Pesanan Dibuat"]["tipe"] == "tanggal"
    assert prof["Waktu Pesanan Dibuat"]["urutan"] == "tahun-bulan-hari"
    assert prof["Total Berat"]["tipe"] == "berat"
    aman = sd.profil_untuk_ai(prof)
    # kolom pribadi: tidak ada contoh nilai apa pun yang ikut
    for h in ("Username (Pembeli)", "Nama Penerima", "No. Telepon", "Alamat Pengiriman"):
        if h in aman:
            assert "kategori" not in aman[h]
            assert all("A" in x or "9" in x or not x for x in aman[h].get("contoh_pola", []))
    assert sd.kolom_pribadi("Nama Penerima") and not sd.kolom_pribadi("Status Pesanan")


def test_profil_tanggal_hari_dulu_dan_id_panjang():
    rows = [{"Created Time": "19/07/2026 21:05:11", "Order ID": "585055055923938626", "R": "0,50%"},
            {"Created Time": "03/08/2026 10:00:00", "Order ID": "585055055923938627", "R": "24,87%"}]
    prof = sd.profil_nilai(["Created Time", "Order ID", "R"], rows)
    assert prof["Created Time"]["urutan"] == "hari-bulan-tahun"
    assert prof["Order ID"]["tipe"] == "id" and prof["Order ID"]["panjang"] == [18]
    assert prof["R"]["tipe"] == "persen" and prof["R"]["persen_bertanda"] == 1.0


# ── invarian sebagai hakim ─────────────────────────────────────────────────────
def test_invarian_berkas_asli_lulus():
    for rel, st_key, kode in (("TikTok_UntukDikirim_2026-07-19.xlsx", "marketplace_orders", {"sku_sesudah", "order_amount"}),
                              ("marketplace_2026/order_pesanan_shopee.xlsx", "marketplace_orders",
                               {"subtotal_harga", "total_diskon", "total_diskon_harga"}),
                              ("marketplace_2026/ads_shopee.csv", "shopee_ads_cpc", {"ctr", "roas", "acos"})):
        p = S / rel
        if not p.exists():
            continue
        r = iv.uji_berkas(get_source_type(st_key), p.read_bytes(), p.name)
        got = {x["kode"]: x for x in r["hasil"]}
        assert kode <= set(got), (rel, got)
        assert all(got[k]["lulus"] and got[k]["diuji"] > 0 for k in kode), (rel, got)
        assert r["ringkas"]["status"] == "lolos"


def _tiktok_tabel():
    p = S / "marketplace_2026" / "pesanan_tiktok.xlsx"
    if not p.exists():
        pytest.skip("contoh tidak ada")
    h, rows = eng.parse_table(p.read_bytes(), p.name, MO)
    m = eng.auto_map(h, MO)
    rows, _ = eng.strip_description_rows(rows, m, MO)
    return h, rows, m


def test_hakim_menolak_usulan_uang_yang_salah_dan_menerima_yang_benar():         # F22
    _, rows, m = _tiktok_tabel()
    # kolom "SKU Subtotal Before Discount" dilepas, lalu dua usulan bersaing untuk mengisinya
    base = [dict(x, field=None, method="none") if x["field"] == "sku_subtotal_before_discount" else x for x in m]
    salah = iv.hakim_usulan(MO, rows, base, {"Original Shipping Fee": "sku_subtotal_before_discount"})
    assert salah["Original Shipping Fee"]["diterima"] is False
    assert "hanya cocok" in salah["Original Shipping Fee"]["alasan"]
    benar = iv.hakim_usulan(MO, rows, base, {"SKU Subtotal Before Discount": "sku_subtotal_before_discount"})
    assert benar["SKU Subtotal Before Discount"]["diterima"] is True


def test_hakim_kolom_uang_tanpa_rumus_tidak_diterima_otomatis():
    _, rows, m = _tiktok_tabel()
    base = [dict(x, field=None, method="none") if x["field"] == "original_shipping_fee" else x for x in m]
    r = iv.hakim_usulan(MO, rows, base, {"Original Shipping Fee": "original_shipping_fee"})
    assert r["Original Shipping Fee"]["diterima"] is False
    assert "tidak bisa diuji" in r["Original Shipping Fee"]["alasan"]

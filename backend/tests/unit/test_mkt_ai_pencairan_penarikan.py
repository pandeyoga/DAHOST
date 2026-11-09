"""Impor penghasilan (pencairan) TikTok/Shopee & penarikan saldo — riset G7, G8, G9, G25.

Header = nama kolom NYATA (riset §4.2 peta header EN/ID dari parser publik ekspor asli; §3.3
bentuk laporan Saldo Shopee). Angka sintetis yang konsisten dengan definisi TikTok:
Total revenue = Subtotal after seller discounts − Refund subtotal after seller discounts.
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

from core import settlement_import as si  # noqa: E402
from core import withdrawal_import as wi  # noqa: E402

TT_EN = ["Order/adjustment ID", "Type", "Order created time", "Order settled time", "Currency",
         "Total settlement amount", "Total revenue", "Subtotal after seller discounts",
         "Refund subtotal after seller discounts", "Total fees", "TikTok Shop commission fee",
         "Dynamic commission", "Order processing fee", "Affiliate commission", "Shipping cost",
         "Article 22 Income Tax withheld", "Adjustment amount", "Related order ID"]
TT_ID = ["ID Pesanan/Penyesuaian", "Jenis transaksi", "Waktu pemesanan", "Waktu pembayaran pesanan", "Mata uang",
         "Jumlah penyelesaian pembayaran", "Total Pendapatan", "Subtotal setelah diskon penjual",
         "Subtotal pengembalian dana setelah diskon penjual", "Total Biaya", "Biaya komisi platform",
         "Komisi dinamis", "Biaya pemrosesan pesanan", "Komisi Afiliasi", "Ongkir", "PPh Pasal 22 dipungut",
         "Jumlah penyesuaian", "ID pesanan terkait"]
# (id, jenis, dibuat, settle, cur, NET, revenue, subtotal, refund, total_fees, komisi, dinamis, proses,
#  afiliasi, ongkir, pph, penyesuaian, terkait)
TT_ROWS = [
    ["T1", "Order", "01/08/2026", "10/08/2026", "IDR", 79250, 100000, 100000, 0, -18750, -8000, -4000, -1250,
     -5000, -2000, -500, 0, ""],
    ["T2", "Order", "02/08/2026", "11/08/2026", "IDR", 127000, 150000, 200000, -50000, -20000, -12000, -6000,
     -1250, 0, -3000, -750, 0, ""],
    ["T3", "Adjustment", "", "12/08/2026", "IDR", -15000, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, -15000, "T1"],
]


def _xlsx(head, rows, sheet="Order details"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(head)
    for r in rows:
        ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


@pytest.mark.parametrize("head", [TT_EN, TT_ID], ids=["EN", "ID"])
def test_penghasilan_tiktok_kolom_penjualan_bukan_diskon(head):                  # F13
    r = si.parse_settlement_report(_xlsx(head, TT_ROWS), "income_20260810.xlsx")
    v = r["values"]
    assert v["gross_sales"] == 300000                # subtotal SESUDAH diskon penjual = penjualan
    assert v["seller_discount"] == 0                 # dulu = 300.000 (kolom penjualan tertangkap)
    assert v["refunds"] == 50000
    assert v["platform_commission"] == 30000         # komisi + komisi dinamis
    assert v["platform_service_fee"] == 2500         # biaya pemrosesan pesanan
    assert v["affiliate_commission"] == 5000
    assert v["other_deductions"] == 6250             # ongkir + PPh 22
    assert v["adjustments"] == -15000
    assert v["net_payout"] == 191250                 # dana bersih terbaca (versi ID dulu 0)
    assert r["settlement_date"] == "2026-08-12"      # waktu settle, bukan periode pesanan
    assert (r["period_from"], r["period_to"]) == ("2026-08-01", "2026-08-02")
    assert si.guess_platform(r["headers"]) == "tiktokshop"
    # kolom ringkasan tidak ikut dijumlah, dan rumus per baris lolos semua
    assert set(r["summary_columns"]) == {head[6], head[9]}
    assert r["invariant"]["diuji"] == 3 and r["invariant"]["lolos"] == 3 and not r["warnings"]
    assert r["invariant"]["rumus_pendapatan"] == {"diuji": 3, "lolos": 3}
    # F9: penjualan − potongan + penyesuaian = dana bersih
    exp = (v["gross_sales"] - v["refunds"] - v["platform_commission"] - v["platform_service_fee"]
           - v["affiliate_commission"] - v["other_deductions"] + v["adjustments"])
    assert exp == v["net_payout"]


def test_penghasilan_tiktok_nama_kolom_okt_2026_dan_salah_eja():
    head = list(TT_EN)
    head[8] = "Total refund after discounts"
    head[16] = "Ajustment amount"
    r = si.parse_settlement_report(_xlsx(head, TT_ROWS), "income.xlsx")
    assert r["values"]["refunds"] == 50000 and r["values"]["adjustments"] == -15000


def test_rumus_gagal_memberi_peringatan():
    rows = [list(x) for x in TT_ROWS]
    rows[0][5] = 90000                               # dana bersih tidak cocok komponen
    r = si.parse_settlement_report(_xlsx(TT_EN, rows), "income.xlsx")
    assert r["invariant"]["lolos"] == 2 and r["warnings"] and "Periksa pemetaan" in r["warnings"][0]
    assert r["invariant"]["gagal_contoh"][0]["selisih"] == pytest.approx(10750)


def test_sampel_tiktok_di_repo_berheader_nyata_dan_rumusnya_benar():             # G8
    p = REPO / "samples" / "settlement_tiktok_contoh.xlsx"
    if not p.exists():
        pytest.skip("sampel tidak ada")
    r = si.parse_settlement_report(p.read_bytes(), p.name)
    assert "Subtotal after seller discounts" in r["headers"]
    assert r["values"]["seller_discount"] == 0 and r["invariant"]["lolos"] == r["invariant"]["diuji"] > 0


def test_penghasilan_shopee_view_by_baris_sku_dilewati():                         # G25 · F14
    head = ["No.", "View By", "Order ID", "Payout Completed Date", "Total Penghasilan", "Harga Produk",
            "Biaya Administrasi"]
    rows = [[1, "Order", "S1", "2026-10-05", 88000, 100000, -12000],
            [1, "Sku", "S1", "2026-10-05", 88000, 100000, -12000]]
    r = si.parse_settlement_report(_xlsx(head, rows, "Income"), "Income.released.xlsx")
    assert r["row_count"] == 1
    assert r["values"]["net_payout"] == 88000 and r["values"]["gross_sales"] == 100000


# ── G9 — laporan Saldo Shopee: header baris ~18, hanya "Penarikan Dana" ───────
SALDO_META = [["Laporan Transaksi Saldo Penjual"], ["Username (Penjual)", "toko_uji"], ["Dari", "2026-09-01"],
              ["Ke", "2026-09-30"], [], ["Saldo Awal", "0"], ["Total Saldo Masuk", "150000"],
              ["Total Saldo Keluar", "-150000"], ["Saldo Akhir", "0"]] + [[]] * 8
SALDO_HEAD = ["Tanggal Transaksi", "Tipe Transaksi", "Deskripsi", "No. Pesanan", "Jenis Transaksi", "Jumlah",
              "Status", "Saldo Akhir"]
SALDO_ROWS = [
    ["2026-09-21 11:29:57", "Penghasilan dari Pesanan", "Penghasilan dari Pesanan #X1", "X1", "Transaksi Masuk",
     "150000.00", "Transaksi Selesai", "150000.00"],
    ["2026-09-22 09:00:00", "Isi Ulang Saldo Iklan/Koin Penjual", "Isi ulang", "-", "Transaksi Keluar",
     "-50000.00", "Transaksi Selesai", "100000.00"],
    ["2026-09-23 10:00:00", "Penarikan Dana", "Penarikan Dana ke rekening", "-", "Transaksi Keluar",
     "-100000.00", "Transaksi Selesai", "0.00"],
]


@pytest.mark.parametrize("fmt", ["xlsx", "csv"])
def test_saldo_shopee_hanya_penarikan_yang_dihitung(fmt):                        # F15
    if fmt == "xlsx":
        raw = _xlsx(SALDO_META[0], SALDO_META[1:] + [SALDO_HEAD] + SALDO_ROWS, "Transaction Report")
        name = "my_balance_transaction_report.shopee.20260930.xlsx"
    else:
        b = io.StringIO()
        csv.writer(b).writerows(SALDO_META + [SALDO_HEAD] + SALDO_ROWS)
        raw, name = b.getvalue().encode("utf-8-sig"), "saldo.csv"
    r = wi.parse_withdrawal_report(raw, name)
    assert r["header_row"] == len(SALDO_META) + 1          # baris ke-18
    assert r["mapping"]["type"] == "Tipe Transaksi" and r["mapping"]["amount"] == "Jumlah"
    assert r["total_ok"] == 100000                         # dulu Rp300.000
    ok = [x for x in r["rows"] if x["ok"]]
    assert len(ok) == 1 and ok[0]["withdrawal_date"] == "2026-09-23"
    bukan = [x for x in r["rows"] if not x["ok"]]
    assert len(bukan) == 2 and all("bukan penarikan" in x["reason"] for x in bukan)
    assert r["platform_guess"] == "shopee" and r["notes"]


def test_penarikan_tiktok_type_withdrawal():
    head = ["Withdrawal ID", "Type", "Amount", "Status", "Time"]
    rows = [["W1", "Withdrawal", "500000", "Success", "2026-10-02 10:00:00"],
            ["W2", "Deposit", "20000", "Success", "2026-10-03 10:00:00"]]
    b = io.StringIO()
    csv.writer(b).writerows([head] + rows)
    r = wi.parse_withdrawal_report(b.getvalue().encode(), "withdrawal_records.csv")
    assert r["total_ok"] == 500000 and [x["ok"] for x in r["rows"]] == [True, False]


def test_penarikan_lama_tanpa_kolom_tipe_tetap_sama():
    head = ["No. Penarikan", "Tanggal Penarikan", "Jumlah Penarikan", "Status"]
    rows = [["P1", "2026-10-01", "1.000.000", "Berhasil"], ["P2", "2026-10-02", "500.000", "Gagal"]]
    b = io.StringIO()
    csv.writer(b).writerows([head] + rows)
    r = wi.parse_withdrawal_report(b.getvalue().encode(), "tarik.csv")
    assert r["total_ok"] == 1000000 and r["header_row"] == 1

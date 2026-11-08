"""Kebenaran UANG impor pesanan Seller Center — diuji dengan berkas contoh ASLI di `samples/`.

Dasar: riset_laporan_marketplace_2026-11-09 §4.1/§3.1 (rumus terbukti) & §6.2 G5, G6, G14,
G16, G17, G19; keputusan owner 9 Nov ("sesuai rekomendasi"):
  · omzet produk = sebelum diskon − diskon PENJUAL saja; diskon yang dibiayai platform ikut
    omzet dan dicatat terpisah (`platform_discount_total`);
  · TikTok "Buyer Service Fee" per SKU → dijumlah;
  · TikTok "Dikirim" + "Terkirim" → sudah diterima pembeli;
  · kanal Tokopedia di ekspor terpadu = sub-kanal toko TikTok yang sama.
Uji membaca berkas asli hanya untuk angka/rumus; tidak ada data pembeli yang dicetak.
"""
from __future__ import annotations

import collections
import csv
import io
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from core import marketing_import_engine as eng  # noqa: E402
from core.marketing_import_schema import get_source_type, is_retired_mapping  # noqa: E402
import routes.marketing_data_import as md  # noqa: E402

MO = get_source_type("marketplace_orders")
TT_KIRIM = REPO / "samples" / "TikTok_UntukDikirim_2026-07-19.xlsx"
TT_AGT = REPO / "samples" / "marketplace_2026" / "pesanan_tiktok.xlsx"
SP_ORD = REPO / "samples" / "marketplace_2026" / "order_pesanan_shopee.xlsx"


def _baca(path: Path):
    if not path.exists():
        pytest.skip(f"berkas contoh {path.name} tidak ada")
    raw = path.read_bytes()
    headers, rows = eng.parse_table(raw, path.name, MO)
    mapping = eng.auto_map(headers, MO)
    rows, _ = eng.strip_description_rows(rows, mapping, MO)
    return headers, rows, mapping, eng.build_rows(rows, mapping, MO)


def _num(v):
    n, _ = eng.parse_number(v)
    return n or 0.0


def _docs(built):
    out = []
    for b in built:
        assert b["status"] != "error", b["errors"][:3]
        doc, _ = md._finish(MO, b["data"], {"account_id": "acc-uji"}, {}, account=None)
        out.append(doc)
    return out


# ── G5 — dasar omzet = sebelum diskon − diskon penjual ────────────────────────
@pytest.mark.parametrize("path,persen", [(TT_KIRIM, 2.2), (TT_AGT, 3.9)])
def test_omzet_tiktok_ikut_diskon_platform(path, persen):
    _, rows, mapping, built = _baca(path)
    m = {x["column"]: x["field"] for x in mapping}
    assert m["SKU Subtotal After Discount"] == "sku_subtotal_after_all_discount"
    # invarian baris (674/674 di riset): sesudah = sebelum − platform − penjual
    for r in rows:
        before, plat = _num(r["SKU Subtotal Before Discount"]), _num(r["SKU Platform Discount"])
        seller, after = _num(r["SKU Seller Discount"]), _num(r["SKU Subtotal After Discount"])
        assert abs(before - plat - seller - after) <= 1
    docs = _docs(built)
    omzet = sum(d["revenue_product"] for d in docs)
    sesudah_semua = sum(_num(r["SKU Subtotal After Discount"]) for r in rows)
    sebelum_kurang_penjual = sum(_num(r["SKU Subtotal Before Discount"]) - _num(r["SKU Seller Discount"])
                                 for r in rows)
    subsidi = sum(d["platform_discount_total"] for d in docs)
    assert omzet == pytest.approx(sebelum_kurang_penjual, abs=1)
    assert omzet == pytest.approx(sesudah_semua + subsidi, abs=1)
    # dokumentasi angka: omzet naik tepat sebesar subsidi platform (2,2 % / 3,9 %)
    assert round(subsidi / omzet * 100, 1) == pytest.approx(persen, abs=0.1)
    assert all(it["omzet_basis_source"] == "sebelum_dikurangi_diskon_penjual"
               for d in docs for it in d["items"])


def test_omzet_tiktok_untuk_dikirim_angka_tepat():
    """Berkas 559 pesanan: dulu Rp59.783.811 (sesudah semua diskon) — sekarang +Rp1.374.206."""
    _, _, _, built = _baca(TT_KIRIM)
    docs = _docs(built)
    assert len(docs) == 559
    assert round(sum(d["revenue_product"] for d in docs)) == 61_158_017
    assert round(sum(d["platform_discount_total"] for d in docs)) == 1_374_206


def test_omzet_shopee_sama_bila_diskon_shopee_nol_dan_rumus_diskon_terjaga():
    _, rows, mapping, built = _baca(SP_ORD)
    m = {x["column"]: x["field"] for x in mapping}
    assert m["Subtotal Pesanan"] == "sku_subtotal_after_all_discount"
    for r in rows:                                    # 154/154 di riset
        assert abs(_num(r["Total Diskon"]) - _num(r["Diskon Dari Penjual"]) - _num(r["Diskon Dari Shopee"])) <= 1
        assert abs(_num(r["Subtotal Pesanan"]) - _num(r["Harga Setelah Diskon"]) * _num(r["Jumlah"])) <= 1
    docs = _docs(built)
    omzet = sum(d["revenue_product"] for d in docs)
    assert omzet == pytest.approx(sum(_num(r["Subtotal Pesanan"]) + _num(r["Diskon Dari Shopee"]) for r in rows), abs=1)


def test_omzet_shopee_diskon_shopee_bukan_nol_ikut_omzet():                    # F05
    head = ["No. Pesanan", "Status Pesanan", "Waktu Pesanan Dibuat", "Harga Awal", "Harga Setelah Diskon",
            "Jumlah", "Subtotal Pesanan", "Total Diskon", "Diskon Dari Penjual", "Diskon Dari Shopee"]
    rows = [["F05-1", "Selesai", "2026-10-01 10:00", "100.000", "70.000", "2", "140.000", "60.000",
             "40.000", "20.000"]]
    b = io.StringIO()
    csv.writer(b).writerows([head] + rows)
    h, t = eng.parse_table(b.getvalue().encode(), "Order.all.f05.csv", MO)
    built = eng.build_rows(t, eng.auto_map(h, MO), MO)
    doc, _ = md._finish(MO, built[0]["data"], {"account_id": "a"}, {}, account=None)
    assert doc["revenue_product"] == 160000           # 200.000 − 40.000 diskon penjual
    assert doc["platform_discount_total"] == 20000    # subsidi Shopee dicatat terpisah
    assert doc["items"][0]["sku_subtotal_after_all_discount"] == 140000


def test_pemetaan_lama_subtotal_ke_dasar_omzet_dipensiunkan():
    assert is_retired_mapping("marketplace_orders", "sku subtotal after discount", "sku_subtotal_after_discount")
    assert is_retired_mapping("marketplace_orders", "subtotal pesanan", "sku_subtotal_after_discount")
    # field dasar omzet tidak pernah dipetakan otomatis dari kemiripan namanya
    assert all(m["field"] != "sku_subtotal_after_discount"
               for m in eng.auto_map(["SKU Subtotal After Discount", "Subtotal Pesanan"], MO))


# ── G6 — Buyer Service Fee per SKU dijumlah; invarian Order Amount ────────────
@pytest.mark.parametrize("path,minimal", [(TT_KIRIM, 559), (TT_AGT, 92)])
def test_order_amount_cocok_bila_biaya_layanan_dijumlah(path, minimal):
    _, rows, _, built = _baca(path)
    by = collections.defaultdict(list)
    for r in rows:
        by[r["Order ID"]].append(r)
    docs = {d["order_id"]: d for d in _docs(built)}
    cocok = 0
    for oid, rs in by.items():
        d = docs[str(oid)]
        r0 = rs[0]
        est = (sum(_num(x["SKU Subtotal After Discount"]) for x in rs) + _num(r0["Shipping Fee After Discount"])
               + d.get("buyer_service_fee", 0) + _num(r0["Handling Fee"]) + _num(r0["Shipping Insurance"])
               + _num(r0["Item Insurance"]) - _num(r0["Payment platform discount"]))
        cocok += abs(est - _num(r0["Order Amount"])) <= 1
        assert d.get("buyer_service_fee", 0) == pytest.approx(sum(_num(x["Buyer Service Fee"]) for x in rs))
    assert cocok >= minimal
    assert "buyer_service_fee" not in MO.per_order_money and "buyer_service_fee" in MO.item_sum_fields
    # peringatan palsu "berbeda antar baris" untuk biaya layanan tidak muncul lagi
    assert not any("Biaya Layanan Pembeli berbeda" in w for b in built for w in b["warnings"])


# ── G16 — Dikirim + Terkirim = sudah diterima pembeli ─────────────────────────
def test_tiktok_dikirim_terkirim_menjadi_delivered():
    _, rows, _, built = _baca(TT_AGT)
    terkirim = {str(r["Order ID"]) for r in rows
                if str(r.get("Order Status")).strip() == "Dikirim" and str(r.get("Order Substatus")).strip() == "Terkirim"}
    assert terkirim, "berkas contoh memuat pesanan Dikirim/Terkirim"
    st = {b["data"]["order_id"]: b["data"]["status"] for b in built}
    assert all(st[o] == "delivered" for o in terkirim)
    assert all(b["data"]["status_raw"] == "Dikirim" for b in built if b["data"]["order_id"] in terkirim)


# ── G17 — kanal Tokopedia di ekspor terpadu TikTok ─────────────────────────────
def _tiktok_mini(channel_rows):
    head = ["Order ID", "Order Status", "Order Substatus", "SKU ID", "Quantity", "SKU Subtotal Before Discount",
            "SKU Platform Discount", "SKU Seller Discount", "SKU Subtotal After Discount", "Order Amount",
            "Created Time", "Purchase Channel"]
    rows = [[f"58{i:016d}", st, sub, "1730000000000000001", "1", "100000", "2000", "8000", "90000", "95000",
             "01/10/2026 10:00:00", ch] for i, (st, sub, ch) in enumerate(channel_rows)]
    b = io.StringIO()
    csv.writer(b).writerows([head] + rows)
    h, t = eng.parse_table(b.getvalue().encode(), "OrderSKUList.csv", MO)
    return eng.build_rows(t, eng.auto_map(h, MO), MO)


def test_kanal_tokopedia_jadi_subkanal_toko_tiktok():                           # F18
    built = _tiktok_mini([("Selesai", "", "TikTok"), ("Selesai", "", "Tokopedia")])
    by = {b["data"]["sales_channel"]: b["data"] for b in built}
    assert set(by) == {"tiktok", "tokopedia"}
    assert by["tokopedia"]["purchase_channel"] == "TikTok"
    assert by["tokopedia"]["purchase_channel_raw"] == "Tokopedia"
    # penjaga platform route tidak menolak berkas ini untuk toko TikTok — tapi tetap
    # menolaknya untuk toko Shopee
    assert all(md._platform_matches("tiktok", b["data"]["purchase_channel"]) for b in built)
    assert not md._platform_matches("shopee", by["tokopedia"]["purchase_channel"])


# ── G19 — status bahasa Inggris / nama API ─────────────────────────────────────
def test_status_bahasa_inggris_dan_api():
    built = _tiktok_mini([("On hold", "", "TikTok"), ("PARTIALLY_SHIPPING", "", "TikTok"),
                          ("AWAITING_SHIPMENT", "", "TikTok"), ("Shipped", "Delivered", "TikTok")])
    got = [b["data"]["status"] for b in sorted(built, key=lambda b: b["data"]["order_id"])]
    assert got == ["new", "shipped", "paid", "delivered"]


# ── G14 — waktu selesai & koin Shopee ──────────────────────────────────────────
def test_kolom_shopee_berarti_tepat():
    _, rows, mapping, built = _baca(SP_ORD)
    m = {x["column"]: x["field"] for x in mapping}
    assert m["Waktu Pesanan Selesai"] == "completed_at"
    assert m["Potongan Koin Shopee"] == "coin_platform"
    assert m["Diskon Kartu Kredit"] == "credit_card_discount"
    assert m["Total Berat"] == "weight_kg"
    w = [b["data"].get("weight_kg") for b in built if b["data"].get("weight_kg") is not None]
    assert w and max(w) < 20        # "200 gr" = 0,2 kg (dulu 200 kg)

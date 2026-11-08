"""Katalog data — penjualan marketplace, iklan, setoran (Portal Marketing / Keuangan).

Sumber & pembaca resmi:
  * rekap harian `marketing_sales_data` — penulis tunggal `core.marketing_sales_shape.build_daily_doc`, pembaca
    `core.ukuran_penjualan.baca_rekap` (revenue_type=total, data contoh dibuang). Omzet = `metrics.revenue`.
  * pesanan `marketing_orders` — impor `routes/marketing_data_import.py`, manual `routes/marketing_orders_routes.py`;
    aturan "dihitung omzet" = `core.ukuran_penjualan.filter_dihitung_omzet`; item dibaca seperti
    `core.marketing_daily_rollup.item_qty/item_revenue` dan `ukuran_penjualan.baris_item`.
  * iklan `marketing_ads_data` — `routes/marketing_ads_routes.py` + impor; tanggal campur (`tanggal_iklan`).
  * setoran `marketing_settlements` — `routes/marketing_settlements.py`; biaya platform resmi hanya dari sini.
Lingkup toko (PIC/assign) + CV toko: `core.ukuran_penjualan.toko_terlihat` (mode CV "toko").
Data pribadi pembeli (nama, username, HP, alamat, kota, pesan) sengaja TIDAK ada di katalog.
"""
from __future__ import annotations

from core import ukuran_penjualan as U
from core.asisten_ai.katalog_data import Akses, Dataset, Kolom, e_angka, e_atau, e_teks
from core.marketing_account_scope import ALL_ACCOUNTS_ROLES

_PERAN_MKT = tuple(r for r in ALL_ACCOUNTS_ROLES if r not in ("owner", "admin", "superadmin"))
AKSES_PENJUALAN = Akses(portal=("toko",), izin=("marketing.report.view_all",), peran=_PERAN_MKT,
                        modul=("mkt_dashboard", "mkt_sales"))
AKSES_PESANAN = Akses(portal=("toko",), izin=("marketing.report.view_all",), peran=_PERAN_MKT,
                      modul=("mkt_orders", "mkt_dashboard"))
AKSES_IKLAN = Akses(portal=("toko",), izin=("marketing.report.view_all",), peran=_PERAN_MKT, modul=("mkt_content",))
AKSES_SETORAN = Akses(portal=("finance", "toko"), izin=("marketing.report.view_all",), peran=_PERAN_MKT,
                      modul=("fin_marketplace",))
CV_TOKO = {"mode": "toko"}
STATUS_PESANAN = ("new", "paid", "packed", "shipped", "delivered", "completed", "cancelled", "returned")
SALURAN = ("live", "video", "product_card", "search", "ads", "affiliate", "campaign", "other")


def _toko() -> tuple:
    return (
        Kolom("toko", "Toko", "teks", path="account_name", cadangan=("account_code",)),
        Kolom("toko_id", "Id toko", "teks", path="account_id", bawaan=False,
              keterangan="Kunci toko (stabil walau nama toko berubah)."),
        Kolom("platform", "Platform", "teks", path="platform", nilai=("shopee", "tiktok", "tiktokshop", "lazada",
                                                                       "tokopedia")),
    )


# Ekspresi "pesanan ini dihitung omzet" — SETARA `ukuran_penjualan.filter_dihitung_omzet` (data contoh sudah
# dibuang saringan dasar katalog).
EKSPR_DIHITUNG = {"$and": [
    {"$not": [{"$in": ["$status", list(U.STATUS_BATAL)]}]},
    {"$or": [
        {"$ne": ["$status", U.STATUS_BARU]},
        {"$not": [{"$in": [{"$ifNull": ["$paid_at", None]}, [None, ""]]}]},
        {"$eq": ["$_source_type", U.SUMBER_MANUAL]},
        {"$eq": ["$status_assumed", True]},
        {"$in": ["$platform_status", list(U.STATUS_MENTAH_SUDAH_BAYAR)]},
    ]},
]}
_I = "items."
# Omzet satu baris item SESUDAH diskon (impor & manual) — `marketing_daily_rollup.item_revenue`.
_QTY_ITEM = e_angka(e_atau(_I + "quantity", _I + "qty", _I + "qty_ordered"))
EKSPR_OMZET_ITEM = {"$ifNull": [e_angka("$items.sku_subtotal_after_discount"), {"$ifNull": [
    e_angka("$items.subtotal"), {"$ifNull": [e_angka("$items.amount"), {"$multiply": [
        {"$ifNull": [e_angka("$items.price"), 0]}, {"$ifNull": [_QTY_ITEM, 0]}]}]}]}]}

_KOLOM_PESANAN = (
    Kolom("tanggal", "Tanggal pesanan", "tanggal", path="order_date", simpan="campur",
          keterangan="Tanggal pesanan menurut Seller Center (WIB)."),
    Kolom("no_pesanan", "Nomor pesanan", "teks", path="order_id"),
    *_toko(),
    Kolom("status", "Status pesanan", "teks", path="status", nilai=STATUS_PESANAN),
    Kolom("dihitung_omzet", "Dihitung omzet", "ya_tidak", ekspr=EKSPR_DIHITUNG,
          keterangan="ya = bukan batal dan bukan pesanan baru yang belum dibayar (aturan omzet resmi)."),
)

DATASET = (
    Dataset(
        id="penjualan_harian_toko",
        label="Penjualan harian per toko",
        keterangan=("Rekap resmi omzet, pesanan, unit, pembeli, retur, dan batal per toko per hari. Sumber angka "
                    "yang sama dengan Dashboard & Laporan Marketing."),
        koleksi=U.DAILY, domain="penjualan", akses=AKSES_PENJUALAN, kolom_tanggal="tanggal",
        saringan_dasar={"revenue_type": "total"}, cv=CV_TOKO, toko_field="account_id",
        kolom=(
            Kolom("tanggal", "Tanggal", "tanggal", path="date", simpan="teks"),
            *_toko(),
            Kolom("omzet", "Omzet", "uang", path="metrics.revenue", cadangan=("revenue",),
                  keterangan="Omzet resmi (basis toko): penjualan produk setelah diskon penjual, sebelum potongan "
                             "platform."),
            Kolom("omzet_produk", "Omzet produk", "uang", path="metrics.revenue_product",
                  cadangan=("revenue_product",), bawaan=False),
            Kolom("nilai_pesanan", "Nilai dibayar pembeli", "uang", path="metrics.revenue_order_amount",
                  cadangan=("revenue_order_amount",), bawaan=False, keterangan="Termasuk ongkir."),
            Kolom("diskon_penjual", "Diskon penjual", "uang", path="metrics.seller_discount",
                  cadangan=("seller_discount",), bawaan=False),
            Kolom("pesanan", "Jumlah pesanan", "angka", path="metrics.orders", cadangan=("orders",)),
            Kolom("unit", "Unit terjual", "angka", path="metrics.units", cadangan=("units", "quantity")),
            Kolom("pelanggan_unik", "Jumlah pembeli (unik)", "angka", path="metrics.buyers", cadangan=("buyers",)),
            Kolom("retur_nilai", "Nilai retur", "uang", ekspr={"$cond": [
                {"$eq": ["$revenue_basis", "order_amount"]}, e_atau("fulfillment.returned_value", "returned_value"),
                e_atau("fulfillment.returned_revenue_product", "fulfillment.returned_value", "returned_value")]},
                  keterangan="Pada basis omzet yang sama dengan kolom omzet."),
            Kolom("retur_pesanan", "Pesanan retur", "angka", path="fulfillment.returned_orders",
                  cadangan=("returned_orders",)),
            Kolom("batal_pesanan", "Pesanan batal", "angka", path="fulfillment.cancelled_orders",
                  cadangan=("cancelled_orders",)),
            Kolom("belum_bayar_pesanan", "Pesanan belum dibayar", "angka", path="fulfillment.unpaid_orders",
                  bawaan=False),
            Kolom("sumber", "Sumber angka", "teks", path="source", bawaan=False,
                  nilai=("orders_auto", "manual", "manual_override", "import", "import_kpi", "task_action",
                         "livehost_creator_auto")),
            Kolom("basis_omzet", "Basis omzet toko", "teks", path="revenue_basis", bawaan=False,
                  nilai=("produk_setelah_diskon", "order_amount")),
        ),
        catatan=(
            U.DEFINISI_OMZET,
            "Satu baris = satu toko pada satu tanggal. Total omzet = jumlah kolom omzet; AOV = jumlah omzet ÷ "
            "jumlah pesanan (hitung dari agregasi, jangan merata-ratakan AOV harian). Omzet setelah retur = omzet − "
            "retur_nilai.",
        ),
    ),
    Dataset(
        id="pesanan_marketplace",
        label="Pesanan marketplace",
        keterangan="Satu baris per pesanan marketplace: tanggal, toko, status, omzet produk, nilai dibayar, saluran.",
        koleksi=U.ORDERS, domain="penjualan", akses=AKSES_PESANAN, kolom_tanggal="tanggal", cv=CV_TOKO,
        toko_field="account_id",
        kolom=(
            *_KOLOM_PESANAN,
            Kolom("omzet", "Omzet produk pesanan", "uang", ekspr=U.EKSPR_OMZET_PRODUK,
                  keterangan="Setelah diskon penjual, tanpa ongkir."),
            Kolom("nilai_dibayar", "Nilai dibayar pembeli", "uang", path="order_amount", cadangan=("total_payment",),
                  bawaan=False),
            Kolom("diskon_penjual", "Diskon penjual", "uang", path="seller_discount_total",
                  cadangan=("discount_seller",), bawaan=False),
            Kolom("unit", "Unit", "angka", path="quantity"),
            Kolom("saluran", "Saluran pesanan", "teks", path="order_channel", nilai=SALURAN),
            Kolom("status_kirim", "Status pengiriman", "teks", path="fulfillment_status", bawaan=False),
            Kolom("kurir", "Kurir", "teks", path="courier", bawaan=False),
        ),
        catatan=(
            "Untuk omzet resmi per toko/hari pakai penjualan_harian_toko. Di sini, saring dihitung_omzet = true "
            "supaya meniru aturan omzet (pesanan batal & belum dibayar dibuang).",
            "Jumlah pesanan = hitung (tanpa kolom); pembeli tidak tersedia di sini (data pribadi).",
        ),
    ),
    Dataset(
        id="item_pesanan_marketplace",
        label="Baris item pesanan marketplace",
        keterangan="Satu baris per SKU di dalam pesanan: SKU, nama produk, variasi, unit, omzet baris. Untuk produk "
                   "terlaris, omzet per SKU, dan unit per produk.",
        koleksi=U.ORDERS, domain="penjualan", akses=AKSES_PESANAN, kolom_tanggal="tanggal", cv=CV_TOKO,
        toko_field="account_id", unwind="items",
        kolom=(
            *_KOLOM_PESANAN,
            Kolom("sku", "SKU", "teks", path="items.seller_sku",
                  cadangan=("items.variant_sku", "items.sku_code", "items.platform_sku_id")),
            Kolom("nama_produk", "Nama produk", "teks", path="items.product_name_raw", cadangan=("items.product_name",)),
            Kolom("variasi", "Variasi", "teks", path="items.variation_raw", cadangan=("items.variant",)),
            Kolom("unit", "Unit", "angka", ekspr=_QTY_ITEM),
            Kolom("omzet_baris", "Omzet baris (setelah diskon)", "uang", ekspr=EKSPR_OMZET_ITEM),
            Kolom("diskon_penjual", "Diskon penjual baris", "uang", path="items.sku_seller_discount", bawaan=False),
            Kolom("unit_retur", "Unit diretur", "angka", path="items.qty_returned", bawaan=False),
            Kolom("model_id", "Id model produk", "teks", path="items.model_id", bawaan=False),
            Kolom("barang_jadi_id", "Id barang jadi (stok)", "teks", path="items.fg_material_id", bawaan=False),
        ),
        catatan=(
            "Satu baris = satu SKU dalam satu pesanan; hitung pesanan unik dengan hitung_unik no_pesanan. Saring "
            "dihitung_omzet = true untuk produk terlaris versi omzet resmi.",
            "Pesanan lama tanpa rincian item tidak muncul di sini, jadi jumlah omzet_baris bisa lebih kecil dari "
            "omzet resmi penjualan_harian_toko; sebut cakupannya bila membandingkan.",
        ),
    ),
    Dataset(
        id="iklan_harian",
        label="Iklan marketplace",
        keterangan="Belanja iklan, impresi, klik, konversi, dan omzet atribusi per kampanye per hari per toko.",
        koleksi=U.ADS, domain="iklan", akses=AKSES_IKLAN, kolom_tanggal="tanggal", cv=CV_TOKO,
        toko_field="account_id",
        kolom=(
            Kolom("tanggal", "Tanggal", "tanggal", path="date", cadangan=("period_start",), simpan="campur"),
            *_toko(),
            Kolom("saluran_iklan", "Saluran iklan", "teks", path="ad_platform",
                  nilai=("shopee_ads", "tiktok_ads", "meta_ads", "google_ads", "affiliate", "lainnya")),
            Kolom("kampanye", "Kampanye", "teks", path="campaign_name"),
            Kolom("jenis_iklan", "Jenis iklan", "teks", path="ad_type", bawaan=False),
            Kolom("belanja", "Belanja iklan", "uang", path="spend"),
            Kolom("impresi", "Impresi", "angka", path="impressions"),
            Kolom("klik", "Klik", "angka", path="clicks"),
            Kolom("konversi", "Konversi", "angka", path="conversions"),
            Kolom("omzet_atribusi", "Omzet atribusi iklan", "uang", path="revenue",
                  keterangan="Klaim platform iklan, bukan omzet resmi toko."),
            Kolom("status", "Status iklan", "teks", path="status", bawaan=False, nilai=("active", "paused", "ended")),
        ),
        catatan=(
            "ROAS gabungan = jumlah omzet_atribusi ÷ jumlah belanja; CTR = klik ÷ impresi (hitung dari agregasi, "
            "jangan merata-ratakan rasio harian). Omzet atribusi bukan omzet resmi; untuk rasio belanja iklan "
            "terhadap omzet pakai omzet penjualan_harian_toko.",
        ),
    ),
    Dataset(
        id="setoran_marketplace",
        label="Setoran (dana dilepas) marketplace",
        keterangan=("Laporan dana dilepas platform per setoran: penjualan kotor, komisi & biaya platform, potongan "
                    "iklan/afiliasi, subsidi ongkir, refund, dan dana yang diterima."),
        koleksi=U.SETTLEMENTS, domain="setoran", akses=AKSES_SETORAN, kolom_tanggal="tanggal_dana", cv=CV_TOKO,
        toko_field="account_id",
        kolom=(
            Kolom("tanggal_dana", "Tanggal dana dilepas", "tanggal", path="settlement_date", simpan="teks"),
            *_toko(),
            Kolom("no_setoran", "Nomor setoran", "teks", path="settlement_id"),
            Kolom("periode_dari", "Periode pesanan dari", "tanggal", path="period_from", simpan="teks", bawaan=False),
            Kolom("periode_sampai", "Periode pesanan sampai", "tanggal", path="period_to", simpan="teks",
                  bawaan=False),
            Kolom("penjualan_kotor", "Penjualan kotor", "uang", path="gross_sales"),
            Kolom("refund", "Refund", "uang", path="refunds"),
            Kolom("diskon_penjual", "Diskon penjual", "uang", path="seller_discount", bawaan=False),
            Kolom("subsidi_ongkir", "Subsidi ongkir", "uang", path="shipping_subsidy", bawaan=False),
            Kolom("komisi_platform", "Komisi platform", "uang", path="platform_commission"),
            Kolom("biaya_layanan", "Biaya layanan platform", "uang", path="platform_service_fee"),
            Kolom("komisi_afiliasi", "Komisi afiliasi", "uang", path="affiliate_commission"),
            Kolom("potongan_iklan", "Potongan iklan", "uang", path="ads_deduction"),
            Kolom("potongan_lain", "Potongan lain", "uang", path="other_deductions", bawaan=False),
            Kolom("penyesuaian", "Penyesuaian", "uang", path="adjustments", bawaan=False,
                  keterangan="Bisa negatif."),
            Kolom("total_potongan", "Total potongan", "uang", path="total_deductions"),
            Kolom("dana_diterima", "Dana diterima", "uang", path="net_payout"),
            Kolom("status_jurnal", "Status jurnal", "teks", ekspr=e_teks({"$ifNull": ["$je_status", "belum"]}),
                  bawaan=False, nilai=("belum", "draft", "posted")),
        ),
        catatan=(
            "Biaya platform resmi HANYA dari dataset ini, dikelompokkan menurut tanggal_dana (tanggal dana dilepas), "
            "bukan tanggal pesanan — jangan dicocokkan per hari dengan omzet.",
        ),
    ),
)

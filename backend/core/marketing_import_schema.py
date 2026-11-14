"""core.marketing_import_schema — **daftar resmi jenis data impor marketing**.

KENAPA BERKAS INI ADA
---------------------
Mesin impor lama (`routes/universal_import.py`) **menebak** jenis data lewat AI
(`_ai_detect_schema`). Konsekuensinya, diukur pada audit 2026-08-11:

1. Kalau AI gagal/kuota habis → seluruh impor mati (`status: queued → failed`);
   tidak ada jalan manual sama sekali.
2. Tebakannya bisa salah, dan salah tebak berarti **baris masuk ke tabel yang
   salah**. Peta tujuannya sendiri sudah salah untuk dua jenis:
   `discount_campaign → marketing_discount_campaigns` (koleksi yang tidak pernah
   dibaca layar; yang benar `marketing_discounts`) dan
   `sample_shipping → marketing_sample_shipments` (yang benar `marketing_samples`).
   Data yang "berhasil diimpor" lalu tidak muncul di mana pun.
3. Jenis yang tidak dikenali dibuang ke koleksi karangan
   `marketing_import_<apa pun>` — tumbuh diam-diam, tidak pernah dibaca.

Berkas ini menggantikan tebakan dengan **daftar tertulis**: staf MEMILIH jenis
datanya, dan setiap jenis menyatakan secara eksplisit:

* `collection`      — tabel tujuan (satu-satunya sumber kebenaran)
* `account_scope`   — apakah wajib memilih toko/akun ("required"/"optional"/"none")
* `context`         — konteks tambahan yang wajib dipilih SEBELUM upload
                      (mis. `host` untuk sesi live, `creator` untuk sample)
* `fields`          — kolom kanonik + label Indonesia + sinonim header yang lazim
                      dipakai Shopee/TikTok/Tokopedia + contoh isi
* `dedupe`          — kunci alami untuk mencegah baris ganda saat impor diulang
* `module_hint`     — pintu mana di portal yang akan menampilkan hasilnya, supaya
                      staf tahu ke mana harus melihat setelah commit. Ditulis dengan NAMA
                      MENU yang dilihat staf (mis. "Laporan Marketing › Performa iklan"),
                      bukan id menu — teks ini tampil apa adanya di layar impor.

Sinonim ditulis apa adanya seperti yang muncul di file ekspor marketplace
(termasuk versi Bahasa Inggris), karena itulah yang membuat pemetaan otomatis
BISA berjalan **tanpa AI**.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# ── jenis nilai yang dikenali mesin impor ────────────────────────────────────
# str      : teks apa adanya
# date     : disimpan sebagai "YYYY-MM-DD" (string) — cocok untuk koleksi yang
#            memang menyimpan tanggal sebagai teks (samples/reviews/returns/…)
# datetime : disimpan sebagai objek datetime UTC — untuk koleksi yang memang
#            menyimpan datetime (orders.order_date, ads.date, live.session_date)
# int      : bilangan bulat  ≥ 0 kecuali dinyatakan lain
# num      : bilangan pecahan
# money    : rupiah; menerima "Rp 1.250.000", "1,250,000", "1250000"
# pct      : persen 0–100; menerima "12,5%" dan 12.5
# bool     : ya/tidak
# enum     : harus salah satu `choices` (dicocokkan longgar: huruf kecil, tanpa spasi)
# list     : dipisah koma / titik-koma
# kg       : berat dalam kilogram; menerima "0.6", "1,2 kg", "200 gr", "500 gram"
#            (2026-11-09, riset G13 — dulu "200 gr" tersimpan sebagai 200 kg)


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    kind: str = "str"
    required: bool = False
    synonyms: Tuple[str, ...] = ()
    choices: Tuple[str, ...] = ()
    example: str = ""
    note: str = ""
    # Field turunan: TIDAK diminta di template, diisi sistem (mis. account_id).
    derived: bool = False
    # ── F1 (2026-08-12) — kamus nilai & jejak nilai asli ─────────────────────
    # `value_map`: pasangan (nilai apa adanya di ekspor platform, nilai kanonik).
    #   Dipakai supaya "Perlu dikirim" → `paid` TERTULIS, bukan ditebak; nilai yang
    #   tidak ada di kamus **menolak baris** dengan pesan yang memuat nilai aslinya.
    # `keep_raw`: simpan nilai asli di `<name>_raw` (mis. `status_raw`) supaya jejak
    #   platform tidak hilang setelah dinormalkan.
    value_map: Tuple[Tuple[str, str], ...] = ()
    keep_raw: bool = False
    # Bila kamus tidak memuat nilainya: kosong ⇒ baris DITOLAK (default, untuk
    # field yang menentukan angka/status). Diisi ⇒ nilai jatuh ke nilai ini
    # dengan PERINGATAN (untuk field keterangan seperti kurir/kanal, supaya
    # nama kurir baru tidak pernah menghapus omzet satu pesanan).
    value_map_fallback: str = ""
    # 2026-11-06 (Tahap 2) — nilai platform yang membawa TANGGAL di dalam teksnya,
    # mis. "Pesanan diterima, namun Pembeli masih dapat mengajukan pengembalian
    # hingga 2026-10-12." Kamus biasa harus memuat satu entri per tanggal; di sini
    # cukup AWALAN teksnya: (awalan, nilai kanonik).
    value_prefix_map: Tuple[Tuple[str, str], ...] = ()
    # Label Indonesia untuk tiap nilai kanonik — layar pemetaan nilai tidak boleh
    # menampilkan kode program (`delivered`, `jnt`) ke staf.
    choice_labels: Tuple[Tuple[str, str], ...] = ()
    # 2026-11-09 (riset G20) — NOMOR yang wajib tetap TEKS (nomor pesanan 18–19 digit).
    # Berkas ekspor yang dibuka lalu disimpan ulang di Excel mengubah nomor itu menjadi
    # angka ilmiah ("5.85319535278917E+17"): digit terakhirnya hilang, dan pesanan
    # berbeda bisa jatuh ke nomor yang sama. Nilai seperti itu DITOLAK, bukan ditebak.
    id_teks: bool = False
    # 2026-11-09 (riset G5) — field yang DIHITUNG SISTEM dari kolom lain. Tidak dipetakan
    # otomatis (juga tidak lewat kemiripan dengan nama field-nya sendiri: nama
    # `sku_subtotal_after_discount` persis sama dengan header TikTok "SKU Subtotal After
    # Discount", padahal artinya beda); staf tetap boleh memetakannya manual.
    dihitung: bool = False

    @property
    def value_map_pairs(self) -> Tuple[Tuple[str, str], ...]:
        return self.value_map

    def choice_label(self, value: str) -> str:
        for k, lbl in self.choice_labels:
            if k == value:
                return lbl
        return str(value or "").replace("_", " ").capitalize()


@dataclass(frozen=True)
class SourceType:
    key: str
    label: str
    group: str
    collection: str
    describe: str
    fields: Tuple[Field, ...]
    account_scope: str = "required"      # required | optional | none
    context: Tuple[str, ...] = ()        # ("host",) | ("creator",) | ()
    dedupe: Tuple[str, ...] = ()
    module_hint: str = ""
    # ── F1 (2026-08-12) — satu dokumen dari BANYAK baris ─────────────────────
    # `group_by`      : kolom pengelompokan (mis. ("order_id",)) ⇒ 1 dokumen per nilai
    # `item_fields`   : field yang masuk `items[]` (sisanya jadi header)
    # `per_order_money`: uang per PESANAN — hanya dibaca dari baris pertama, dilarang
    #                   dijumlah antar baris (sumber salah hitung paling mahal)
    # `platform_guard`: field yang harus cocok dengan `platform` toko tujuan
    # `shop_guard`    : field yang harus cocok dengan `platform_warehouse_name`
    #                   toko tujuan — SIDIK TOKO di dalam berkas. Tanpa ini,
    #                   memilih toko yang salah di layar (dua toko TikTok bernama
    #                   mirip) memindahkan SELURUH omzet satu berkas ke toko lain
    #                   tanpa satu pun peringatan. Terbukti terjadi 2026-08-12:
    #                   559 pesanan gudang 'Outfit Boutique' masuk ke 'TikTok Daluna'.
    group_by: Tuple[str, ...] = ()
    item_fields: Tuple[str, ...] = ()
    per_order_money: Tuple[str, ...] = ()
    # 2026-11-09 (riset G6) — uang PER SKU yang juga dibutuhkan sebagai total pesanan.
    # Nilainya disimpan per baris di `items[]` DAN dijumlah ke kepala dokumen.
    # Contoh: TikTok "Buyer Service Fee" — rumus Order Amount hanya cocok 559/559
    # pesanan bila kolom ini DIJUMLAH (dulu diambil baris pertama saja).
    item_sum_fields: Tuple[str, ...] = ()
    platform_guard: str = ""
    shop_guard: str = ""
    # ── F12 (2026-08-14, sesi #11) — TANDA PENGENAL GLOBAL SATU BARIS ────────
    # `platform_guard` menangkap "berkas Shopee masuk toko TikTok" dan `shop_guard`
    # menangkap "gudang platform di berkas bukan gudang toko tujuan". Keduanya
    # HANYA ada pada `marketplace_orders`. Akibatnya lubang berikut masih terbuka:
    #
    #   · **Ekspor B/C** (`marketplace_fulfillment`) tidak punya kolom gudang
    #     maupun platform ⇒ berkas toko A yang diunggah ke toko B menghasilkan
    #     "3 baris ditolak: belum pernah diimpor". Kalimat itu BENAR tetapi
    #     menyembunyikan sebab sesungguhnya (tokonya salah pilih), sehingga staf
    #     mengira berkasnya rusak dan mencoba lagi — atau lebih buruk, memilih
    #     jenis "Pesanan Marketplace" supaya "mau masuk" ⇒ pesanan HANTU.
    #   · Berkas ekspor toko A yang diunggah ke toko B tetap bisa MASUK untuk
    #     jenis yang tidak punya sidik gudang ⇒ omzet toko A tercatat di toko B.
    #
    # `identity` = nama field yang menjadi tanda pengenal SATU baris secara GLOBAL
    # (bukan per toko): nomor pesanan platform, nomor komplain, URL konten. Kalau
    # tanda pengenal itu SUDAH tercatat pada toko LAIN, itu bukti — bukan dugaan —
    # bahwa berkasnya milik toko lain. `identity_collection` = tempat kepemilikan
    # diperiksa (nomor pesanan selalu diperiksa di `marketing_orders`, SSOT-nya,
    # bukan di koleksi turunan seperti retur/ulasan).
    #
    # JENIS TANPA `identity` WAJIB TERDAFTAR BESERTA ALASANNYA di
    # `NO_IDENTITY_REASON` (dijaga penjaga statik). Pengecualian tanpa alasan =
    # aturan yang hilang. Contoh yang SENGAJA tidak diberi `identity`:
    # `shopee_shop_kpi` hanya berisi TANGGAL & KANAL — setiap toko punya tanggal
    # yang sama, jadi memakainya sebagai tanda pengenal akan MENUDUH SALAH.
    identity: str = ""
    identity_collection: str = ""
    identity_label: str = ""
    # ── F7.2 (2026-08-13) — BERKAS YANG BARIS PERTAMANYA BUKAN HEADER ────────
    # Ekspor KPI Seller Center (statistik toko, Live/Video, laporan iklan) memuat
    # baris judul grup kolom, blok metadata, dan blok section. Dibaca apa adanya,
    # 0 kolom terpetakan. `prenorm` menunjuk penormal di
    # `core/marketing_import_prenorm.PRENORMALIZERS` yang mengubah berkas itu
    # menjadi tabel berkolom kanonik SEBELUM pemetaan berjalan.
    prenorm: str = ""
    # ── F3 (2026-08-13) — IMPOR YANG HANYA MEMPERBARUI ───────────────────────
    # Ekspor B ("Dikirim/Selesai") & C ("Batal/Retur") adalah KABAR SUSULAN tentang
    # pesanan yang sudah ada, bukan sumber pesanan baru. Kalau baris yang nomornya
    # tak dikenal boleh dibuat, satu berkas fulfillment akan melahirkan pesanan
    # HANTU tanpa item, tanpa uang, tanpa kreator — dan jumlah pesanan bulan itu
    # naik tanpa ada penjualan. `update_only=True` membuat baris seperti itu
    # DITOLAK dengan alasan yang menyebut jalan keluarnya.
    update_only: bool = False
    # Peringatan yang WAJIB tampil di layar bila pemetaan kolomnya belum pernah
    # diverifikasi dengan berkas asli milik owner (BLOKIR-DATA BD-1/BD-4).
    mapping_unverified: str = ""
    # Petunjuk untuk layar: dari mana berkas ini diunduh di Seller Center.
    export_hint: str = ""

    def field(self, name: str) -> Optional[Field]:
        for f in self.fields:
            if f.name == name:
                return f
        return None

    @property
    def is_grouped(self) -> bool:
        return bool(self.group_by)

    @property
    def input_fields(self) -> List[Field]:
        return [f for f in self.fields if not f.derived]

    @property
    def required_fields(self) -> List[Field]:
        return [f for f in self.fields if f.required and not f.derived]

    @property
    def header_fields(self) -> List[Field]:
        return [f for f in self.fields if f.name not in self.item_fields]


PLATFORMS = ("shopee", "tiktok", "tokopedia", "lazada", "blibli", "instagram", "website")
COURIERS = ("jnt", "spx", "sicepat", "jne", "anteraja", "ninja", "grab", "gojek", "lainnya")

_DATE_SYN = ("tanggal", "date", "tgl", "order date", "tanggal pesanan",
             "waktu pesanan dibuat", "created time", "tanggal transaksi", "periode")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. SALES HARIAN (rekap per akun per hari)
# ═══════════════════════════════════════════════════════════════════════════════
# 11 Nov 2026 — kolom rincian kanal: nama field `kanal_<kode kanal>` →
# `marketing_sales_shape.MANUAL_TRAFFIC_KEYS`. Dibaca `routes.marketing_data_import._finish`.
SALES_KANAL_PREFIX = "kanal_"
SALES_KANAL_FIELDS = (
    Field("kanal_live", "Kanal Live (Rp)", "money", False,
          ("omzet live", "penjualan live", "kanal live", "gmv live"), example="3000000",
          note="Bagian omzet dari live streaming (termasuk dalam Revenue)"),
    Field("kanal_video", "Kanal Video (Rp)", "money", False,
          ("omzet video", "penjualan video", "kanal video", "gmv video"), example="1500000"),
    Field("kanal_product_card", "Kanal Kartu Produk (Rp)", "money", False,
          ("kartu produk", "omzet kartu produk", "kanal kartu produk", "product card",
           "product cards")),
    Field("kanal_affiliate", "Kanal Afiliasi (Rp)", "money", False,
          ("afiliasi", "omzet afiliasi", "kanal afiliasi", "affiliate")),
    Field("kanal_ads", "Kanal Iklan (Rp)", "money", False,
          ("omzet iklan", "kanal iklan", "penjualan iklan")),
    Field("kanal_campaign", "Kanal Kampanye (Rp)", "money", False,
          ("kampanye", "omzet kampanye", "kanal kampanye", "campaign")),
    Field("kanal_search", "Kanal Pencarian (Rp)", "money", False,
          ("pencarian", "omzet pencarian", "kanal pencarian", "search")),
)

SALES = SourceType(
    key="sales_daily",
    label="Sales Harian per Akun",
    group="Penjualan",
    collection="marketing_sales_data",
    describe="Rekap harian satu akun: revenue, jumlah order, dan metrik toko "
             "(rating, conversion, keterlambatan kirim). Satu baris = satu tanggal.",
    module_hint="Input Sales",
    account_scope="required",
    dedupe=("account_id", "date", "revenue_type"),
    fields=(
        Field("date", "Tanggal", "date", True, _DATE_SYN, example="2026-08-01"),
        Field("revenue_type", "Jenis Revenue", "enum", True,
              ("tipe", "jenis", "revenue type", "sumber"),
              ("total", "live"), example="total",
              note="Isi 'total' = seluruh penjualan hari itu. Omzet live diisi di kolom "
                   "Kanal Live (Rp), bukan sebagai baris 'live'"),
        Field("revenue", "Revenue (Rp)", "money", True,
              ("penjualan", "omzet", "total penjualan", "sales", "gmv terjual",
               "total pembayaran", "net sales"), example="12500000"),
        # 11 Nov 2026 (keputusan owner) — rincian omzet total per kanal. BAGIAN dari
        # Revenue, bukan tambahan; sisanya otomatis "Lainnya". Hari yang sudah punya
        # pesanan impor: kanal dari pesanan tetap, kolom ini hanya membagi bagian
        # "Lainnya" pesanan (lihat `core.marketing_sales_shape.merge_traffic`).
        *SALES_KANAL_FIELDS,
        Field("orders", "Jumlah Order", "int", False,
              ("order", "pesanan", "jumlah pesanan", "total order", "transaksi"),
              example="48"),
        Field("aov", "AOV (Rp)", "money", False, ("average order value", "rata-rata order"),
              note="Boleh kosong — dihitung otomatis revenue ÷ orders"),
        Field("gmv", "GMV (Rp)", "money", False, ("gross merchandise value",)),
        Field("conversion_rate", "Conversion Rate (%)", "pct", False,
              ("konversi", "conversion", "cr")),
        Field("fulfillment_rate", "Fulfillment Rate (%)", "pct", False, ("pemenuhan",)),
        Field("cancellation_rate", "Cancellation Rate (%)", "pct", False, ("pembatalan", "cancel rate")),
        Field("return_rate", "Return Rate (%)", "pct", False, ("retur", "return")),
        Field("late_shipment_rate", "Late Shipment (%)", "pct", False,
              ("keterlambatan kirim", "lsr", "late shipment rate")),
        Field("rating", "Rating Toko", "num", False, ("nilai", "score", "rating toko")),
        Field("review_count", "Jumlah Ulasan", "int", False, ("ulasan", "reviews")),
        Field("response_rate", "Response Rate (%)", "pct", False, ("respon", "chat response")),
        Field("response_time_hours", "Waktu Respon (jam)", "num", False, ("response time",)),
        Field("viewers", "Penonton", "int", False, ("viewers", "penonton live")),
        Field("avg_viewers", "Rata-rata Penonton", "num", False, ("average viewers",)),
        Field("likes", "Likes", "int", False, ("suka",)),
        Field("shares", "Shares", "int", False, ("bagikan",)),
        Field("comments", "Komentar", "int", False, ("comments",)),
        Field("new_followers", "Follower Baru", "int", False, ("followers baru", "new follower")),
        Field("live_sessions", "Jumlah Sesi Live", "int", False, ("sesi live",)),
        Field("account_id", "Akun", "str", True, derived=True),
    ),
)

# ═══════════════════════════════════════════════════════════════════════════════
# 2. ORDER (transaksi)
# ═══════════════════════════════════════════════════════════════════════════════
ORDERS = SourceType(
    key="orders",
    label="Order / Pesanan",
    group="Penjualan",
    collection="marketing_orders",
    describe="Satu baris = satu pesanan. Kalau kolom SKU diisi dan SKU-nya ada di "
             "katalog toko, item katalognya ditautkan otomatis (nama produk & harga "
             "ikut master, tidak diketik ulang).",
    module_hint="Order Terpadu",
    account_scope="required",
    dedupe=("account_id", "order_id"),
    identity="order_id",
    identity_collection="marketing_orders",
    identity_label="nomor pesanan",
    fields=(
        Field("order_id", "No. Pesanan", "str", True,
              ("order id", "no pesanan", "nomor pesanan", "order sn", "invoice",
               "kode pesanan", "order number"), example="SHP-2026081001"),
        Field("order_date", "Tanggal Pesanan", "datetime", True, _DATE_SYN,
              example="2026-08-01"),
        Field("sku_id", "SKU", "str", False,
              ("sku", "kode sku", "sku induk", "seller sku", "kode produk",
               "nomor referensi sku"), example="DA-CKW-005",
              note="Dipakai untuk menautkan ke item katalog toko"),
        Field("product_name", "Nama Produk", "str", False,
              ("produk", "nama barang", "product name", "nama produk"),
              note="Boleh kosong bila SKU cocok — nama diambil dari katalog"),
        Field("variation", "Variasi", "str", False,
              ("variasi", "variant", "nama variasi", "ukuran/warna")),
        Field("quantity", "Jumlah", "int", True,
              ("qty", "jumlah", "kuantitas", "quantity"), example="2"),
        Field("price_original", "Harga Satuan (Rp)", "money", False,
              ("harga", "harga awal", "harga satuan", "original price")),
        Field("price_final", "Harga Setelah Diskon (Rp)", "money", False,
              ("harga jual", "harga final", "deal price", "harga setelah diskon")),
        Field("discount_seller", "Diskon Penjual (Rp)", "money", False,
              ("diskon", "voucher penjual", "seller discount")),
        Field("shipping_cost", "Ongkir (Rp)", "money", False,
              ("ongkir", "biaya kirim", "shipping fee")),
        Field("total_payment", "Total Bayar (Rp)", "money", False,
              ("total pembayaran", "total bayar", "grand total")),
        Field("revenue", "Revenue (Rp)", "money", False,
              ("pendapatan", "omzet", "net revenue"),
              note="Boleh kosong — dihitung dari total bayar / harga × jumlah"),
        Field("status", "Status Pesanan", "enum", False,
              ("status", "order status", "status pesanan"),
              ("new", "paid", "packed", "shipped", "delivered", "completed",
               "cancelled", "returned"), example="paid",
              choice_labels=(("new", "Belum dibayar"), ("paid", "Dibayar, perlu dikirim"),
                             ("packed", "Sedang dikemas"), ("shipped", "Dalam pengiriman"),
                             ("delivered", "Sudah diterima pembeli"), ("completed", "Selesai"),
                             ("cancelled", "Dibatalkan"), ("returned", "Dikembalikan / refund"))),
        Field("courier", "Kurir", "enum", False, ("kurir", "jasa kirim", "shipping provider"),
              COURIERS),
        Field("tracking_number", "No. Resi", "str", False, ("resi", "no resi", "tracking")),
        Field("customer_name", "Nama Pembeli", "str", False,
              ("pembeli", "nama penerima", "buyer name", "customer")),
        Field("city", "Kota", "str", False, ("kota", "kota/kabupaten", "city")),
        Field("payment_method", "Metode Bayar", "str", False, ("pembayaran", "payment method")),
        Field("note", "Catatan", "str", False, ("catatan", "note", "keterangan")),
        Field("account_id", "Akun", "str", True, derived=True),
        Field("catalog_item_id", "Item Katalog", "str", False, derived=True),
    ),
)

# ═══════════════════════════════════════════════════════════════════════════════
# 2b. PESANAN MARKETPLACE (ekspor Seller Center) — F1
#     1 baris ekspor = 1 SKU · 1 DOKUMEN = 1 PESANAN (items[])
# ═══════════════════════════════════════════════════════════════════════════════
# Kamus status: DITULIS, tidak ditebak. Nilai yang tidak ada di sini menolak baris
# dengan pesan yang memuat nilai aslinya (lihat SSOT_KONTRAK_DATA §2.4).
_ORDER_STATUS_MAP = (
    ("Perlu dikirim", "paid"), ("Menunggu pengambilan", "paid"),
    ("Menunggu pengiriman", "paid"), ("Siap dikirim", "paid"),
    ("Belum dibayar", "new"), ("Menunggu pembayaran", "new"), ("Unpaid", "new"),
    ("To ship", "paid"), ("Awaiting shipment", "paid"), ("Awaiting collection", "paid"),
    ("Dikirim", "shipped"), ("Sedang dikirim", "shipped"), ("Dalam pengiriman", "shipped"),
    ("In transit", "shipped"), ("Shipped", "shipped"),
    ("Terkirim", "delivered"), ("Delivered", "delivered"),
    ("Selesai", "completed"), ("Completed", "completed"),
    ("Dibatalkan", "cancelled"), ("Batal", "cancelled"),
    ("Cancelled", "cancelled"), ("Canceled", "cancelled"),
    ("Pengembalian", "returned"), ("Pengembalian/Refund", "returned"),
    ("Refund", "returned"), ("Returned", "returned"), ("Return/refund", "returned"),
    # ── ekspor Shopee (sesi #34, dari berkas asli pemilik) ────────────────────
    ("Perlu Dikirim", "paid"), ("Sedang Dikemas", "packed"), ("Dikemas", "packed"),
    ("Belum Bayar", "new"), ("Menunggu Konfirmasi", "new"),
    ("Dalam Proses", "paid"), ("Pengembalian Dana", "returned"),
    ("Pesanan Selesai", "completed"),
    # ── 2026-11-06 (Tahap 2) — ekspor Shopee "Order.all" ──────────────────────
    # "Sedang Dikirim" = masih di jalan; "Telah Dikirim" = paket sudah sampai di
    # pembeli tetapi pesanan belum diselesaikan ⇒ `delivered`, bukan `shipped`.
    ("Telah Dikirim", "delivered"),
    # ── 2026-11-09 (riset G19) — akun Seller Center ber-UI bahasa Inggris & nama status
    # API TikTok. Huruf besar/garis bawah disamakan kamus ("AWAITING_SHIPMENT" =
    # "Awaiting shipment"). "On hold" = pesanan ditahan platform (belum boleh dikirim).
    ("On hold", "new"), ("Partially shipping", "shipped"),
)
# 2026-11-09 (riset G16, keputusan owner "sesuai rekomendasi") — ekspor TikTok menulis
# status "Dikirim" dengan sub-status "Terkirim" untuk paket yang SUDAH sampai di pembeli.
# Status tunggal tertinggal satu langkah (`shipped`); pasangan ini berarti `delivered`.
# (status kanonik, sub-status dinormalkan) → status kanonik baru.
ORDER_SUBSTATUS_MAP: Tuple[Tuple[str, str, str], ...] = (
    ("shipped", "terkirim", "delivered"),
    ("shipped", "delivered", "delivered"),
)
# Status yang memuat tanggal di dalam teksnya (dicocokkan lewat awalan).
_ORDER_STATUS_PREFIX = (
    ("Pesanan diterima, namun", "delivered"),
)
_ORDER_STATUS_LABELS = (
    ("new", "Belum dibayar"), ("paid", "Dibayar, perlu dikirim"),
    ("packed", "Sedang dikemas"), ("shipped", "Dalam pengiriman"),
    ("delivered", "Sudah diterima pembeli"), ("completed", "Selesai"),
    ("cancelled", "Dibatalkan"), ("returned", "Dikembalikan / refund"),
)
_COURIER_LABELS = (
    ("jnt", "J&T"), ("spx", "SPX / Shopee Express"), ("sicepat", "SiCepat"),
    ("jne", "JNE"), ("anteraja", "AnterAja"), ("ninja", "Ninja Xpress"),
    ("grab", "GrabExpress"), ("gojek", "GoSend"), ("lainnya", "Kurir lain"),
)
_ORDER_CHANNEL_LABELS = (
    ("live", "Live"), ("video", "Video"), ("product_card", "Kartu produk"),
    ("search", "Pencarian"), ("ads", "Iklan"), ("affiliate", "Afiliasi"),
    ("campaign", "Kampanye"), ("other", "Lainnya"),
)
# 11 Nov 2026 — dipakai juga pesanan MANUAL (Order Terpadu): satu daftar kanal untuk
# impor dan input tangan, supaya rekap harian tidak punya dua kamus.
ORDER_CHANNEL_LABELS = _ORDER_CHANNEL_LABELS


def norm_order_channel(value) -> Optional[str]:
    """Kanal pesanan dari kode (``product_card``) atau labelnya (``Kartu produk``);
    ``None`` bila kosong atau tidak dikenal."""
    s = str(value or "").strip().lower()
    if not s:
        return None
    for key, label in _ORDER_CHANNEL_LABELS:
        if s in (key, label.lower()):
            return key
    return None

# Kamus kurir: nama kurir baru TIDAK boleh menghapus omzet ⇒ fallback `lainnya`
# + peringatan (bukan tolak).
_COURIER_MAP = (
    ("J&T Express", "jnt"), ("J&T", "jnt"), ("JNT", "jnt"), ("J&T Cargo", "jnt"),
    ("JNE Express Standard ID", "jne"), ("JNE", "jne"), ("JNE Reguler", "jne"),
    ("SPX", "spx"), ("SPX Express", "spx"), ("Shopee Express", "spx"),
    ("SiCepat", "sicepat"), ("SiCepat Express", "sicepat"),
    ("AnterAja", "anteraja"), ("Anter Aja", "anteraja"),
    ("Ninja", "ninja"), ("Ninja Xpress", "ninja"), ("Ninja Express", "ninja"),
    ("Grab", "grab"), ("GrabExpress", "grab"), ("Grab Express", "grab"),
    ("GoSend", "gojek"), ("Gojek", "gojek"), ("Go Send", "gojek"),
)
# ── Kamus RETUR/REFUND (sesi #34) — ditulis dari berkas ASLI pemilik ─────────
# Berkas "retur refund shopee.xls" & "retur refund tiktok.xlsx" memakai teks bebas.
# Kamus ini menormalkan yang SUDAH dikenal; sisanya jatuh ke `lainnya`/`pending`
# dengan PERINGATAN, dan nilai aslinya tetap tersimpan di `<field>_raw`.
_RETURN_REASON_MAP = (
    ("Ukuran tidak sesuai", "ukuran_tidak_sesuai"),
    ("Ukuran/warna salah", "ukuran_tidak_sesuai"),
    ("Barang tidak sesuai ukuran", "ukuran_tidak_sesuai"),
    ("Wrong size", "ukuran_tidak_sesuai"),
    ("Warna berbeda", "warna_berbeda"), ("Warna tidak sesuai", "warna_berbeda"),
    ("Barang rusak", "barang_rusak"), ("Produk rusak", "barang_rusak"),
    ("Barang cacat", "barang_rusak"), ("Damaged", "barang_rusak"),
    ("Barang rusak/cacat", "barang_rusak"),
    ("Salah kirim", "salah_kirim"), ("Barang salah", "salah_kirim"),
    ("Wrong item", "salah_kirim"), ("Barang tidak sesuai pesanan", "salah_kirim"),
    ("Kualitas buruk", "kualitas_buruk"),
    ("Produk tidak sesuai deskripsi", "kualitas_buruk"),
    ("Barang tidak sesuai deskripsi", "kualitas_buruk"),
    ("Quality issue", "kualitas_buruk"),
    ("Berubah pikiran", "berubah_pikiran"), ("Tidak ingin lagi", "berubah_pikiran"),
    ("Changed mind", "berubah_pikiran"), ("Buyer changed mind", "berubah_pikiran"),
    ("Lainnya", "lainnya"), ("Others", "lainnya"), ("Other", "lainnya"),
    # 2026-11-09 (riset §7.3) — nilai bahasa Inggris pada ekspor retur TikTok (berkas asli)
    ("Wrong product sent", "salah_kirim"), ("Change of mind", "berubah_pikiran"),
    ("Received parcel, but some items were missing", "barang_kurang"),
    ("Missing items", "barang_kurang"), ("Barang kurang", "barang_kurang"),
)

_REFUND_TYPE_MAP = (
    ("Pengembalian Dana", "full_refund"), ("Refund", "full_refund"),
    ("Refund Only", "full_refund"), ("Hanya Pengembalian Dana", "full_refund"),
    ("Pengembalian Barang dan Dana", "full_refund"),
    ("Return and refund", "full_refund"), ("Return & Refund", "full_refund"),
    ("Pengembalian Sebagian", "partial_refund"), ("Partial refund", "partial_refund"),
    ("Penggantian Barang", "replacement"), ("Replacement", "replacement"),
    ("Tukar barang", "replacement"),
    ("Tidak ada pengembalian", "no_refund"), ("No refund", "no_refund"),
)

_RETURN_STATUS_MAP = (
    ("Menunggu", "pending"), ("Pending", "pending"), ("Diajukan", "pending"),
    ("Requested", "pending"), ("Dalam Proses", "pending"), ("Processing", "pending"),
    ("Disetujui", "approved"), ("Approved", "approved"),
    ("Diterima", "approved"), ("Accepted", "approved"),
    ("Ditolak", "rejected"), ("Rejected", "rejected"), ("Dibatalkan", "rejected"),
    ("Cancelled", "rejected"), ("Canceled", "rejected"),
    ("Selesai", "completed"), ("Completed", "completed"),
    ("Refund Selesai", "completed"), ("Pengembalian Selesai", "completed"),
    ("Success", "completed"), ("Berhasil", "completed"),
    # ── 2026-11-09 (riset G10) — nilai NYATA di ekspor platform. Dulu semuanya jatuh ke
    # `pending` lewat nilai cadangan: retur yang ditolak/sudah dibayar tampak menunggu.
    # TikTok (nilai bahasa Inggris walau akun berbahasa Indonesia):
    ("To Process", "pending"), ("In Process", "pending"),
    ("Refund rejected", "rejected"), ("Request Canceled", "rejected"),
    ("Request Cancelled", "rejected"),
    # Shopee (status resmi Pusat Pengembalian):
    ("Sedang Ditinjau", "pending"), ("Sedang Dikembalikan", "pending"),
    ("Banding Diajukan", "pending"),
    ("Dana Dikembalikan ke Pembeli", "completed"),
    ("Ditolak/Dibatalkan", "rejected"),
)
# Sub-status retur TikTok yang MEMUTUSKAN status (dicek sesudah status utama):
# permintaan yang dibatalkan pembeli bukan retur yang menunggu.
RETURN_SUBSTATUS_MAP: Tuple[Tuple[str, str], ...] = (
    ("request canceled", "rejected"), ("request cancelled", "rejected"),
)
# 2026-11-09 (keputusan owner) — "Refund only" = dana kembali TANPA barang kembali.
# Dibedakan dari "Return and refund" supaya gudang tidak menunggu barang (tidak restock).
REFUND_ONLY_VALUES = ("refund only", "hanya pengembalian dana", "pengembalian dana",
                      "refund", "dana saja")
GOODS_RETURN_VALUES = ("return and refund", "return refund", "pengembalian barang dan dana",
                       "pengembalian barang dana", "tukar barang", "penggantian barang",
                       "replacement")

# Kanal pesanan (dasar pecahan trafik di rekap harian F2).
_ORDER_CHANNEL_MAP = (
    ("LIVE", "live"), ("Live", "live"), ("Livestream", "live"),
    ("Videos", "video"), ("Video", "video"), ("Short video", "video"),
    ("Product cards", "product_card"), ("Product card", "product_card"),
    ("Showcase", "product_card"),
    ("Search", "search"), ("Ads", "ads"), ("Advertisement", "ads"),
    ("Affiliate", "affiliate"), ("Campaign", "campaign"),
)

MARKETPLACE_ORDERS = SourceType(
    key="marketplace_orders",
    label="Pesanan Marketplace (ekspor Seller Center)",
    group="Penjualan",
    collection="marketing_orders",
    describe="Ekspor pesanan dari Seller Center (mis. TikTok 'Untuk Dikirim'). "
             "Satu baris berkas = satu SKU; sistem MENGELOMPOKKAN per No. Pesanan "
             "menjadi satu dokumen ber-items[] supaya jumlah pesanan & omzet tidak "
             "terhitung dobel. Omzet produk = harga sebelum diskon dikurangi diskon "
             "PENJUAL saja; diskon yang dibiayai platform ikut omzet dan dicatat "
             "terpisah sebagai subsidi platform. Komisi tidak ada di ekspor ini — "
             "hanya datang dari Pencairan.",
    module_hint="Order Terpadu",
    account_scope="required",
    dedupe=("account_id", "platform", "order_id"),
    identity="order_id",
    identity_collection="marketing_orders",
    identity_label="nomor pesanan",
    group_by=("order_id",),
    platform_guard="purchase_channel",
    shop_guard="warehouse_name_raw",
    item_fields=(
        "platform_sku_id", "seller_sku", "parent_sku", "product_name_raw", "variation_raw",
        "product_category_raw", "quantity", "qty_returned", "sku_unit_original_price",
        "sku_subtotal_before_discount", "sku_platform_discount", "sku_seller_discount",
        "sku_subtotal_after_discount", "is_preorder",
        # 2026-11-06 (Tahap 2) — ekspor Shopee Order.all: "Harga Setelah Diskon"
        # adalah harga SATUAN dan "Total Diskon" adalah diskon PER BARIS SKU.
        "sku_unit_deal_price", "total_discount",
        # 2026-11-09 (riset G5) — subtotal versi PLATFORM (sesudah SEMUA diskon, termasuk
        # yang dibiayai platform); `sku_subtotal_after_discount` = dasar omzet (sesudah
        # diskon PENJUAL saja) diturunkan mesin dari kolom-kolom ini.
        "sku_subtotal_after_all_discount", "omzet_basis_source",
        # 2026-11-09 (riset G6) — per SKU, dijumlah ke kepala pesanan (item_sum_fields).
        "buyer_service_fee",
    ),
    item_sum_fields=("buyer_service_fee",),
    per_order_money=(
        "order_amount", "shipping_fee_after_discount", "original_shipping_fee",
        "shipping_fee_seller_discount", "shipping_fee_platform_discount",
        "distance_shipping_fee", "distance_fee", "order_refund_amount",
        "payment_platform_discount", "handling_fee",
        "shipping_insurance", "item_insurance",
        # ekspor Shopee (sesi #34). `total_discount` DIPINDAH ke item_fields
        # (2026-11-06): nilainya berbeda per baris SKU, jadi bukan uang per pesanan.
        "total_payment", "voucher_seller", "voucher_platform",
        "bundle_discount_seller", "bundle_discount_platform",
        "coin_cashback", "buyer_paid_shipping", "shipping_fee_estimate",
        "shipping_rebate_estimate", "return_shipping_fee",
        # 2026-11-09 (riset G14 · §3.1) — terbukti sama di semua baris pesanan multi-SKU
        "coin_platform", "credit_card_discount",
    ),
    fields=(
        # ── identitas & status ────────────────────────────────────────────────
        Field("order_id", "No. Pesanan", "str", True,
              ("order id", "order sn", "no pesanan", "nomor pesanan", "kode pesanan"),
              example="585055055923938626", id_teks=True),
        Field("status", "Status Pesanan", "enum", True,
              ("order status", "status pesanan", "status"),
              ("new", "paid", "packed", "shipped", "delivered", "completed",
               "cancelled", "returned"),
              example="Perlu dikirim", value_map=_ORDER_STATUS_MAP, keep_raw=True,
              value_prefix_map=_ORDER_STATUS_PREFIX, choice_labels=_ORDER_STATUS_LABELS,
              note="Kamus status tertulis; nilai tak dikenal menolak baris — "
                   "artinya bisa dipilih sendiri di langkah pemetaan. Status 'Dikirim' "
                   "bersub-status 'Terkirim' dicatat sudah diterima pembeli"),
        Field("substatus_raw", "Sub-status", "str", False, ("order substatus",)),
        Field("return_type_raw", "Jenis Pembatalan/Pengembalian", "str", False,
              ("cancelation return type", "cancellation return type",
               "status pembatalan pengembalian", "status pembatalan/ pengembalian")),
        # ── item (masuk items[]) ──────────────────────────────────────────────
        # G2 (audit Gudang 9 Nov 2026) — "Nomor Referensi SKU" Shopee = SKU VARIASI yang
        # diisi penjual (= SKU internal) ⇒ SKU Penjual. "SKU Induk" = SKU produk induk
        # (tanpa varian) ⇒ disimpan terpisah, TIDAK lagi dipetakan ke SKU ID Platform
        # (dulu "SKU Induk" merebut SKU ID Platform lalu "Nomor Referensi SKU" ditinggal
        # tak terpetakan ⇒ 0 pesanan Shopee tertaut).
        Field("platform_sku_id", "SKU ID Platform", "str", False,
              ("sku id", "id sku", "sku"),
              example="1731234567890123456",
              note="Ekspor Shopee tidak punya kolom ini — sistem memakai SKU Penjual"),
        Field("seller_sku", "SKU Penjual", "str", False,
              ("seller sku", "nomor referensi sku", "kode sku penjual", "kode variasi"),
              note="Shopee: 'Nomor Referensi SKU' (SKU variasi) — dasar tautan ke barang"),
        Field("parent_sku", "SKU Induk (produk)", "str", False, ("sku induk",),
              note="SKU produk induk tanpa varian — hanya dicatat, tidak dipakai menautkan"),
        Field("product_name_raw", "Nama Produk (platform)", "str", False,
              ("product name", "nama produk")),
        Field("variation_raw", "Variasi (platform)", "str", False,
              ("variation", "variasi", "nama variasi")),
        Field("product_category_raw", "Kategori Produk", "str", False, ("product category",)),
        Field("quantity", "Jumlah", "int", True, ("quantity", "qty", "jumlah"), example="1"),
        Field("qty_returned", "Jumlah Dikembalikan", "int", False,
              ("sku quantity of return", "qty return", "returned quantity")),
        Field("sku_unit_original_price", "Harga Satuan Asli", "money", False,
              ("sku unit original price", "harga awal")),
        # 2026-11-06 (Tahap 2) — DULU "Subtotal Pesanan" dipetakan ke subtotal
        # SEBELUM diskon dan "Harga Setelah Diskon" (harga SATUAN) ke subtotal
        # SESUDAH diskon ⇒ omzet pesanan berisi >1 barang terhitung harga 1 barang
        # (~15% omzet hilang pada berkas contoh). Di ekspor Shopee, "Subtotal
        # Pesanan" = harga setelah diskon × jumlah; subtotal sebelum diskon tidak
        # ada kolomnya dan dihitung dari harga satuan asli × jumlah.
        Field("sku_subtotal_before_discount", "Subtotal Sebelum Diskon", "money", False,
              ("sku subtotal before discount",),
              note="Ekspor Shopee tidak punya kolom ini — dihitung dari Harga Awal × Jumlah"),
        Field("sku_platform_discount", "Diskon Platform (SKU)", "money", False,
              ("sku platform discount", "diskon dari shopee")),
        Field("sku_seller_discount", "Diskon Penjual (SKU)", "money", False,
              ("sku seller discount", "diskon dari penjual")),
        Field("sku_unit_deal_price", "Harga Satuan Setelah Diskon", "money", False,
              ("harga setelah diskon", "sku unit deal price"),
              note="Harga SATUAN — bukan subtotal baris"),
        # 2026-11-09 (riset G5, keputusan owner K1/K5 "sesuai rekomendasi") — kolom
        # platform "SKU Subtotal After Discount" (TikTok) dan "Subtotal Pesanan" (Shopee)
        # SUDAH dipotong diskon yang DIBIAYAI PLATFORM (terbukti 674/674 & 154/154 baris).
        # Omzet perusahaan = sesudah diskon PENJUAL saja. Kolom platform kini dipetakan ke
        # field sendiri; dasar omzet diturunkan mesin (`marketing_import_engine.omzet_basis_item`).
        Field("sku_subtotal_after_all_discount", "Subtotal Setelah Semua Diskon (platform)",
              "money", False, ("sku subtotal after discount", "subtotal pesanan"),
              note="Angka platform: sudah dipotong diskon penjual DAN diskon yang dibiayai "
                   "platform. Bukan dasar omzet — dipakai untuk menurunkan & memeriksanya"),
        Field("sku_subtotal_after_discount", "Subtotal Setelah Diskon Penjual (dasar omzet)",
              "money", False, (), dihitung=True,
              note="Dasar OMZET PRODUK — dihitung sistem: subtotal sebelum diskon dikurangi "
                   "diskon penjual (diskon yang dibiayai platform ikut omzet). Biasanya "
                   "tidak perlu dipetakan"),
        Field("omzet_basis_source", "Cara Menghitung Omzet", "str", False, derived=True),
        Field("is_preorder", "Normal / Pre-order", "bool", False,
              ("normal or pre order", "normal or pre-order"),
              example="Pre-order",
              value_map=(("Pre-order", "true"), ("Preorder", "true"), ("Pre order", "true"),
                         ("Normal", "false"), ("Reguler", "false"), ("Regular", "false")),
              keep_raw=True),
        # ── uang per pesanan (ditulis 1×) ─────────────────────────────────────
        Field("order_amount", "Order Amount (dibayar pembeli)", "money", False,
              ("order amount",), note="Termasuk ongkir — dipakai bila basis omzet = Order Amount"),
        Field("shipping_fee_after_discount", "Ongkir Setelah Diskon", "money", False,
              ("shipping fee after discount",)),
        Field("original_shipping_fee", "Ongkir Asli", "money", False, ("original shipping fee",)),
        Field("shipping_fee_seller_discount", "Subsidi Ongkir Penjual", "money", False,
              ("shipping fee seller discount",)),
        Field("shipping_fee_platform_discount", "Subsidi Ongkir Platform", "money", False,
              ("shipping fee platform discount",)),
        Field("distance_shipping_fee", "Ongkir Jarak", "money", False, ("distance shipping fee",)),
        Field("distance_fee", "Biaya Jarak", "money", False, ("distance fee",)),
        Field("order_refund_amount", "Nilai Refund", "money", False, ("order refund amount",)),
        Field("payment_platform_discount", "Diskon Pembayaran Platform", "money", False,
              ("payment platform discount",)),
        Field("buyer_service_fee", "Biaya Layanan Pembeli", "money", False, ("buyer service fee",),
              note="Per baris SKU — dijumlah menjadi total pesanan"),
        Field("handling_fee", "Biaya Penanganan", "money", False, ("handling fee",)),
        Field("shipping_insurance", "Asuransi Kirim", "money", False, ("shipping insurance",)),
        Field("item_insurance", "Asuransi Barang", "money", False, ("item insurance",)),
        # ── uang per pesanan khas ekspor Shopee (sesi #34, dari berkas asli) ──
        Field("total_discount", "Total Diskon (per baris SKU)", "money", False, ("total diskon",),
              note="Diskon penjual + diskon platform untuk baris SKU ini"),
        Field("voucher_seller", "Voucher Ditanggung Penjual", "money", False,
              ("voucher ditanggung penjual",)),
        # Q-1 (keputusan owner 9 Nov 2026) — biaya diskon marketing = voucher toko +
        # paket diskon penjual + subsidi ongkir penjual; selisih harga coret BUKAN biaya.
        Field("bundle_discount_seller", "Paket Diskon (ditanggung penjual)", "money", False,
              ("paket diskon diskon dari penjual",)),
        Field("bundle_discount_platform", "Paket Diskon (ditanggung platform)", "money", False,
              ("paket diskon diskon dari shopee", "paket diskon diskon dari platform")),
        Field("voucher_platform", "Voucher Ditanggung Platform", "money", False,
              ("voucher ditanggung shopee", "voucher ditanggung platform")),
        # 2026-11-09 (riset G14) — "Potongan Koin Shopee" = koin Shopee yang dipakai
        # PEMBELI (dibayar Shopee), artinya beda dengan cashback koin dari penjual.
        Field("coin_cashback", "Cashback Koin", "money", False, ("cashback koin",)),
        Field("coin_platform", "Koin Platform Dipakai Pembeli", "money", False,
              ("potongan koin shopee",),
              note="Dibayar platform — bukan biaya penjual"),
        Field("credit_card_discount", "Diskon Kartu Kredit", "money", False,
              ("diskon kartu kredit",)),
        Field("buyer_paid_shipping", "Ongkir Dibayar Pembeli", "money", False,
              ("ongkos kirim dibayar oleh pembeli",)),
        Field("shipping_fee_estimate", "Perkiraan Ongkir", "money", False,
              ("perkiraan ongkos kirim",)),
        Field("shipping_rebate_estimate", "Estimasi Potongan Ongkir", "money", False,
              ("estimasi potongan biaya pengiriman",)),
        Field("return_shipping_fee", "Ongkir Retur", "money", False,
              ("ongkos kirim pengembalian barang",)),
        # ── waktu ─────────────────────────────────────────────────────────────
        Field("order_date", "Waktu Pesanan Dibuat", "datetime", True,
              ("created time", "waktu pesanan dibuat", "order date"),
              example="19/07/2026 21:05:11"),
        Field("paid_at", "Waktu Dibayar", "datetime", False,
              ("paid time", "waktu pembayaran dilakukan")),
        Field("rts_at", "Waktu Siap Kirim", "datetime", False,
              ("rts time", "waktu pengiriman diatur")),
        Field("shipped_at", "Waktu Dikirim", "datetime", False, ("shipped time",)),
        # 2026-11-09 (riset G14) — "Waktu Pesanan Selesai" (Shopee) = pesanan DISELESAIKAN,
        # bukan paket diterima; dulu keduanya tercampur di `delivered_at`.
        Field("delivered_at", "Waktu Diterima", "datetime", False, ("delivered time",)),
        Field("completed_at", "Waktu Selesai", "datetime", False,
              ("waktu pesanan selesai", "completed time")),
        Field("cancelled_at", "Waktu Dibatalkan", "datetime", False, ("cancelled time",)),
        Field("cancel_by", "Dibatalkan Oleh", "str", False, ("cancel by",)),
        Field("cancel_reason", "Alasan Pembatalan", "str", False,
              ("cancel reason", "alasan pembatalan")),
        # ── pengiriman & kanal ────────────────────────────────────────────────
        Field("fulfillment_type", "Jenis Pemenuhan", "str", False, ("fulfillment type",)),
        Field("warehouse_name_raw", "Nama Gudang Platform", "str", False,
              ("warehouse name",), note="Dibandingkan dengan gudang platform di master toko"),
        Field("tracking_number", "No. Resi", "str", False,
              ("tracking id", "tracking number", "resi", "no resi")),
        Field("delivery_option", "Opsi Pengiriman", "str", False,
              ("delivery option", "opsi pengiriman")),
        Field("courier", "Kurir", "enum", False,
              ("shipping provider name", "kurir", "jasa kirim", "opsi pengiriman"), COURIERS,
              example="J&T Express", value_map=_COURIER_MAP, keep_raw=True,
              value_map_fallback="lainnya", choice_labels=_COURIER_LABELS),
        Field("package_id", "ID Paket", "str", False, ("package id",)),
        Field("weight_kg", "Berat (kg)", "kg", False,
              ("weight kg", "weight(kg)", "berat", "total berat"),
              note="'200 gr' dibaca 0,2 kg"),
        Field("payment_method", "Metode Bayar", "str", False,
              ("payment method", "metode pembayaran")),
        Field("purchase_channel", "Platform Sumber", "str", False,
              ("purchase channel",), example="TikTok", keep_raw=True,
              note="Kalau ada, harus cocok dengan platform toko tujuan (berkas ditolak "
                   "bila beda). Ekspor Shopee tidak memuat kolom ini — platform diambil "
                   "dari master toko yang dipilih. Pesanan kanal Tokopedia di ekspor "
                   "terpadu TikTok diterima sebagai sub-kanal toko TikTok yang sama."),
        # 2026-11-09 (riset G17, keputusan owner) — Seller Center terpadu TikTok-Tokopedia:
        # pesanan dari aplikasi Tokopedia tercatat di toko TikTok yang sama, kanalnya di sini.
        Field("sales_channel", "Sub-kanal Penjualan", "str", False, derived=True),
        Field("order_channel", "Kanal Pesanan", "enum", False,
              ("order channel",),
              ("live", "video", "product_card", "search", "ads", "affiliate",
               "campaign", "other"),
              example="LIVE", value_map=_ORDER_CHANNEL_MAP, keep_raw=True,
              value_map_fallback="other", choice_labels=_ORDER_CHANNEL_LABELS,
              note="Dasar pecahan trafik di rekap harian"),
        Field("creator_handle", "Akun Kreator", "str", False, ("creator handle",),
              note="Dasar atribusi kreator & komisi afiliasi"),
        # ── pembeli & alamat ──────────────────────────────────────────────────
        Field("buyer_username", "Username Pembeli", "str", False,
              ("buyer username", "username pembeli", "username (pembeli)")),
        Field("customer_name", "Nama Penerima", "str", False, ("recipient", "nama penerima")),
        Field("customer_phone", "Telepon", "str", False,
              ("phone", "phone #", "no hp", "no telepon")),
        Field("zipcode", "Kode Pos", "str", False, ("zipcode", "kode pos")),
        Field("country", "Negara", "str", False, ("country",)),
        Field("province", "Provinsi", "str", False, ("province", "provinsi")),
        Field("city", "Kota/Kabupaten", "str", False,
              ("regency and city", "kota", "city", "kota kabupaten")),
        Field("district", "Kecamatan", "str", False, ("districts", "kecamatan")),
        Field("village", "Kelurahan/Desa", "str", False, ("villages", "kelurahan")),
        Field("address_detail", "Alamat Detail", "str", False,
              ("detail address", "alamat", "alamat pengiriman")),
        Field("address_extra", "Info Alamat Tambahan", "str", False,
              ("additional address information",)),
        Field("buyer_message", "Pesan Pembeli", "str", False,
              ("buyer message", "catatan dari pembeli")),
        Field("seller_note", "Catatan Penjual", "str", False, ("seller note", "catatan")),
        Field("total_payment", "Total Pembayaran", "money", False, ("total pembayaran",),
              note="Ekspor Shopee: yang dibayar pembeli termasuk ongkir"),
        Field("checked_status", "Status Cek", "str", False, ("checked status",)),
        Field("checked_by", "Dicek Oleh", "str", False, ("checked marked by",)),
        Field("tokopedia_invoice_no", "No. Invoice Tokopedia", "str", False,
              ("tokopedia invoice number",)),
        # ── turunan ───────────────────────────────────────────────────────────
        Field("account_id", "Akun", "str", True, derived=True),
    ),
)

# 2026-11-06 (Tahap 2) — PEMETAAN YANG SUDAH TERBUKTI SALAH.
# "Ingat pemetaan saya" menyimpan pasangan kolom→field yang pernah dikonfirmasi.
# Pasangan di bawah ini dulu dipasang oleh kamus sinonim yang keliru; kalau
# ingatannya dipakai apa adanya, setiap impor berikutnya mengulang omzet ~15%
# terlalu rendah. Pasangan ini DIBUANG dari ingatan (dan dari draf, lewat migrasi
# `scripts/migrations/2026_11_06_impor_pesanan_subtotal.py`), lalu kolomnya
# dipetakan ulang oleh kamus yang benar.
# Kunci: jenis impor → {(header dinormalkan, field lama yang salah)}.
RETIRED_MAPPINGS: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "marketplace_orders": (
        ("harga setelah diskon", "sku_subtotal_after_discount"),
        ("subtotal pesanan", "sku_subtotal_before_discount"),
        # G2 (9 Nov 2026) — kolom SKU Shopee yang dulu tertukar
        ("sku induk", "platform_sku_id"),
        ("sku induk", "seller_sku"),
        ("nomor referensi sku", "platform_sku_id"),
        # 2026-11-09 (riset G5) — kolom subtotal PLATFORM dulu langsung menjadi dasar omzet;
        # angkanya sudah dipotong diskon yang dibiayai platform (omzet 2,2–4,1% terlalu kecil).
        ("subtotal pesanan", "sku_subtotal_after_discount"),
        ("sku subtotal after discount", "sku_subtotal_after_discount"),
        # 2026-11-09 (riset G14) — arti kolom tercampur
        ("waktu pesanan selesai", "delivered_at"),
        ("potongan koin shopee", "coin_cashback"),
    ),
    "marketplace_fulfillment": (
        ("waktu pesanan selesai", "delivered_at"),
    ),
    "returns": (
        # 2026-11-09 (riset G11) — kompensasi ke PENJUAL bukan refund ke pembeli
        ("compensation amount", "refund_amount"),
        ("jumlah kompensasi", "refund_amount"),
        ("order amount", "price"),
    ),
    "ads": (
        # 2026-11-09 (riset G3) — "Waktu posting" = tanggal unggah video, bukan tanggal biaya
        ("waktu posting", "date"),
    ),
}


def is_retired_mapping(source_type: str, header_norm: str, field: str) -> bool:
    return (header_norm, field) in RETIRED_MAPPINGS.get(source_type, ())


# ═══════════════════════════════════════════════════════════════════════════════
# 2b. F3 — STATUS PENGIRIMAN / PEMBATALAN (Ekspor B & C) — HANYA MEMPERBARUI
# ═══════════════════════════════════════════════════════════════════════════════
# Ekspor A ("Untuk Dikirim") melahirkan pesanan. Ekspor **B** ("Dikirim/Selesai")
# dan **C** ("Batal/Retur") hanya membawa KABAR SUSULAN: nomor resi terbit, paket
# dikirim, pesanan dibatalkan, barang diretur. Tanpa jenis impor ini, satu-satunya
# cara memperbarui status adalah mengunggah ulang Ekspor A — dan ekspor A tidak
# pernah memuat pesanan yang sudah selesai, jadi pesanan lama membeku di "perlu
# dikirim" selamanya. Itu yang membuat monitoring "belum dikirim" tidak bisa
# dipercaya, dan omzet retur tidak pernah keluar dari rekap.
MARKETPLACE_FULFILLMENT = SourceType(
    key="marketplace_fulfillment",
    label="Status Pengiriman / Pembatalan (Ekspor B & C)",
    group="Penjualan",
    collection="marketing_orders",
    describe="Kabar susulan untuk pesanan yang SUDAH diimpor: dikirim, selesai, "
             "dibatalkan, atau diretur. Baris yang nomor pesanannya belum pernah "
             "diimpor DITOLAK — jenis ini tidak pernah membuat pesanan baru "
             "(impor 'Pesanan Marketplace' dulu). Status tidak boleh MUNDUR "
             "kecuali ada bukti batal/retur.",
    module_hint="Order Terpadu",
    account_scope="required",
    dedupe=("account_id", "platform", "order_id"),
    identity="order_id",
    identity_collection="marketing_orders",
    identity_label="nomor pesanan",
    update_only=True,
    mapping_unverified=(
        "Pemetaan kolom jenis ini disusun dari bentuk Ekspor A (satu-satunya "
        "berkas nyata yang tersedia) dan BELUM diverifikasi dengan berkas Ekspor "
        "B/C asli. Periksa langkah 'Pemetaan kolom' sebelum menyimpan; kolom yang "
        "tidak dikenali bisa dipetakan manual di layar itu."),
    export_hint="Seller Center → Pesanan → filter 'Dikirim/Selesai' (B) atau "
                "'Batal/Pengembalian' (C) → Ekspor",
    fields=(
        Field("order_id", "No. Pesanan", "str", True,
              ("order id", "order sn", "no pesanan", "nomor pesanan", "kode pesanan"),
              example="585055055923938626", id_teks=True,
              note="KUNCI — harus sudah ada dari impor Ekspor A"),
        Field("status", "Status Pesanan", "enum", True,
              ("order status", "status pesanan", "status"),
              ("new", "paid", "packed", "shipped", "delivered", "completed",
               "cancelled", "returned"),
              example="Dikirim", value_map=_ORDER_STATUS_MAP, keep_raw=True,
              value_prefix_map=_ORDER_STATUS_PREFIX, choice_labels=_ORDER_STATUS_LABELS,
              note="Kamus status tertulis; nilai tak dikenal menolak baris"),
        Field("substatus_raw", "Sub-status", "str", False, ("order substatus",)),
        Field("return_type_raw", "Jenis Pembatalan/Pengembalian", "str", False,
              ("cancelation return type", "cancellation return type",
               "jenis pengembalian"),
              note="Adanya nilai di sini = bukti batal/retur (status boleh mundur)"),
        Field("shipped_at", "Waktu Dikirim", "datetime", False,
              ("shipped time", "waktu dikirim", "waktu pengiriman")),
        Field("delivered_at", "Waktu Diterima", "datetime", False,
              ("delivered time", "waktu diterima")),
        # 2026-11-09 (riset G14) — "Waktu Pesanan Selesai" bukan waktu paket diterima
        Field("completed_at", "Waktu Selesai", "datetime", False,
              ("waktu pesanan selesai", "completed time")),
        Field("cancelled_at", "Waktu Dibatalkan", "datetime", False,
              ("cancelled time", "waktu dibatalkan", "waktu pembatalan")),
        Field("cancel_by", "Dibatalkan Oleh", "str", False,
              ("cancel by", "dibatalkan oleh")),
        Field("cancel_reason", "Alasan Pembatalan", "str", False,
              ("cancel reason", "alasan pembatalan")),
        Field("order_refund_amount", "Nilai Refund", "money", False,
              ("order refund amount", "nilai refund", "jumlah pengembalian dana")),
        Field("tracking_number", "No. Resi", "str", False,
              ("tracking id", "tracking number", "resi", "no resi")),
        Field("courier", "Kurir", "enum", False,
              ("shipping provider name", "kurir", "jasa kirim"), COURIERS,
              example="J&T Express", value_map=_COURIER_MAP, keep_raw=True,
              value_map_fallback="lainnya", choice_labels=_COURIER_LABELS),
        # per-SKU (opsional): kalau ada, `items[].qty_returned` ikut diperbarui
        Field("platform_sku_id", "SKU ID Platform", "str", False,
              ("sku id", "id sku", "sku"),
              note="Opsional — dipakai bila berkas retur merinci per SKU"),
        Field("qty_returned", "Jumlah Dikembalikan", "int", False,
              ("sku quantity of return", "qty return", "jumlah dikembalikan")),
        # ── turunan ───────────────────────────────────────────────────────────
        Field("account_id", "Akun", "str", True, derived=True),
    ),
)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. IKLAN / ADS
# ═══════════════════════════════════════════════════════════════════════════════
ADS = SourceType(
    key="ads",
    label="Biaya & Performa Iklan",
    group="Iklan",
    collection="marketing_ads_data",
    describe="Belanja iklan per kampanye per tanggal untuk satu akun. CTR/CPA/ROAS "
             "dihitung sistem dari spend, klik, dan revenue — tidak perlu diisi.",
    module_hint="Laporan Marketing › Performa iklan, dan realisasi Iklan di Target & Anggaran",
    account_scope="required",
    dedupe=("account_id", "date", "campaign_name"),
    fields=(
        # 2026-11-09 (riset G3, keputusan owner) — DULU "Waktu posting" ekspor GMV Max
        # dipakai sebagai tanggal biaya: satu ekspor menyebar biayanya ke 15 bulan
        # (2024-06 … 2026-08) karena itu tanggal UNGGAH VIDEO, bukan tanggal belanja.
        # Ekspor GMV Max sekarang punya jenis impor sendiri (`tiktok_gmv_max`, periode
        # laporan wajib); kolom "Waktu posting" tidak lagi dikenali sebagai tanggal di sini.
        Field("date", "Tanggal", "datetime", True,
              _DATE_SYN + ("tanggal iklan",),
              example="2026-08-01", keep_raw=True),
        Field("campaign_name", "Nama Kampanye", "str", True,
              ("kampanye", "campaign", "campaign name", "nama iklan", "iklan",
               "nama kampanye"),
              example="Flash Sale Gamis Agustus"),
        Field("campaign_id", "ID Kampanye", "str", False,
              ("campaign id", "kode kampanye", "id campaign")),
        Field("ad_type", "Jenis Iklan", "enum", False,
              ("tipe iklan", "ad type", "jenis", "jenis materi iklan"),
              ("search", "discovery", "video", "live", "shop", "affiliate", "lainnya"),
              value_map=(("Video", "video"), ("Live", "live"), ("LIVE", "live"),
                         ("Gambar", "discovery"), ("Image", "discovery"),
                         ("Katalog", "shop"), ("Product card", "shop"),
                         ("Kartu produk", "shop")),
              keep_raw=True, value_map_fallback="lainnya"),
        Field("spend", "Biaya Iklan (Rp)", "money", True,
              ("biaya", "belanja iklan", "cost", "spend", "total biaya",
               "pengeluaran", "budget terpakai"), example="750000"),
        Field("impressions", "Impresi", "int", False,
              ("impresi", "impressions", "tayangan", "dilihat",
               "impresi iklan produk")),
        Field("clicks", "Klik", "int", False,
              ("klik", "clicks", "jumlah klik iklan produk")),
        Field("conversions", "Konversi", "int", False,
              ("konversi", "conversions", "pesanan dari iklan", "produk terjual",
               "pesanan sku")),
        Field("revenue", "Revenue dari Iklan (Rp)", "money", False,
              ("penjualan dari iklan", "omzet iklan", "gmv iklan", "revenue",
               "pendapatan kotor")),
        # ── kolom khas ekspor TikTok GMV Max (sesi #34, dari berkas asli) ──────
        Field("cost_per_order", "Biaya per Pesanan (Rp)", "money", False,
              ("biaya per pesanan", "cost per order", "cpo")),
        Field("product_id", "ID Produk", "str", False, ("id produk", "product id")),
        Field("video_id", "ID Video", "str", False, ("id video", "video id")),
        Field("video_title", "Judul Video", "str", False,
              ("judul video", "video title", "judul materi")),
        Field("creator_handle", "Akun Kreator", "str", False,
              ("akun tiktok", "creator handle", "akun kreator", "creator")),
        Field("authorization_type", "Jenis Otorisasi", "str", False,
              ("jenis otorisasi", "authorization type")),
        Field("ctr_platform", "CTR Platform (%)", "pct", False,
              ("tingkat klik iklan produk", "ctr platform")),
        Field("conversion_rate", "Rasio Konversi (%)", "pct", False,
              ("rasio konversi iklan", "conversion rate")),
        Field("currency", "Mata Uang", "str", False, ("mata uang", "currency")),
        Field("status", "Status", "enum", False, ("status",),
              ("active", "paused", "ended"), example="active",
              value_map=(("Dijelajahi", "active"), ("Aktif", "active"),
                         ("Active", "active"), ("Berjalan", "active"),
                         ("Dijeda", "paused"), ("Paused", "paused"),
                         ("Berakhir", "ended"), ("Ended", "ended"),
                         ("Selesai", "ended")),
              keep_raw=True, value_map_fallback="active"),
        Field("notes", "Catatan", "str", False, ("catatan", "keterangan",
                                                 "status sekunder penjelajahan")),
        Field("account_id", "Akun", "str", True, derived=True),
        Field("ctr", "CTR (%)", "pct", False, derived=True),
        Field("cpa", "CPA (Rp)", "money", False, derived=True),
        Field("roas", "ROAS", "num", False, derived=True),
    ),
)

# ═══════════════════════════════════════════════════════════════════════════════
# 4. SESI LIVE (performa host + penjualan)
# ═══════════════════════════════════════════════════════════════════════════════
LIVE_SESSIONS = SourceType(
    key="live_sessions",
    label="Sesi Live Selling (performa host + sales)",
    group="Live",
    collection="marketing_live_sessions",
    describe="Satu baris = satu sesi live. WAJIB memilih akun DAN host yang sudah "
             "di-assign ke akun itu, supaya jam kerja, gaji host, dan omzetnya "
             "tercatat pada toko yang benar.",
    module_hint="Live Selling",
    account_scope="required",
    context=("host",),
    dedupe=("account_id", "session_date", "title"),
    fields=(
        Field("session_date", "Tanggal Sesi", "datetime", True,
              _DATE_SYN + ("tanggal live", "session date"), example="2026-08-01"),
        Field("title", "Judul / Tema Sesi", "str", True,
              ("judul", "tema", "title", "nama sesi"), example="Live Gamis Malam"),
        Field("start_time", "Jam Mulai", "str", False, ("mulai", "jam mulai", "start")),
        Field("duration_minutes", "Durasi (menit)", "int", True,
              ("durasi", "duration", "lama live", "menit"), example="120"),
        Field("peak_viewers", "Penonton Puncak", "int", False,
              ("peak viewers", "penonton tertinggi", "puncak")),
        Field("total_viewers", "Total Penonton", "int", False,
              ("viewers", "penonton", "total penonton", "views")),
        Field("likes", "Likes", "int", False, ("suka", "likes")),
        Field("comments", "Komentar", "int", False, ("komentar", "comments")),
        Field("shares", "Shares", "int", False, ("dibagikan", "shares")),
        Field("orders", "Jumlah Order", "int", False,
              ("order", "pesanan", "jumlah pesanan", "produk terjual")),
        Field("revenue", "Revenue (Rp)", "money", True,
              ("omzet", "penjualan", "gmv", "revenue", "total penjualan"),
              example="8500000"),
        Field("products_featured", "Jumlah Produk Dibawakan", "int", False,
              ("produk", "jumlah produk", "products")),
        Field("status", "Status", "enum", False, ("status",),
              ("scheduled", "live", "completed", "cancelled"), example="completed"),
        Field("notes_text", "Catatan", "str", False, ("catatan", "keterangan")),
        Field("account_id", "Akun", "str", True, derived=True),
        Field("host_id", "Host", "str", True, derived=True),
        Field("host_name", "Nama Host", "str", False, derived=True),
        Field("engagement_rate", "Engagement (%)", "pct", False, derived=True),
        Field("conversion_rate", "Conversion (%)", "pct", False, derived=True),
    ),
)

# ═══════════════════════════════════════════════════════════════════════════════
# 4b. RINCIAN PRODUK PER SESI LIVE (F18#3)
# ═══════════════════════════════════════════════════════════════════════════════
# Laporan ekspor Shopee/TikTok Live memberi rekap "produk apa yang laku di sesi
# ini" — satu baris per produk. Sebelum ini tidak ada jenis data untuk itu, jadi
# satu-satunya cara mengisi `products[]` adalah tidak ada cara sama sekali, dan
# laporan "Produk Terlaris saat Live" selalu kosong.
LIVE_SESSION_PRODUCTS = SourceType(
    key="live_session_products",
    label="Rincian Produk per Sesi Live",
    group="Live",
    collection="marketing_live_session_products",
    describe="Satu baris = satu produk pada SATU sesi live. Pilih dulu toko dan "
             "sesi live-nya, lalu unggah rekap produk dari laporan platform. SKU "
             "harus ada di katalog toko itu — baris yang SKU-nya tidak dikenal "
             "ditolak (bukan disimpan tanpa tautan), karena rincian yang tidak "
             "tertaut master tidak bisa dipakai laporan.",
    module_hint="Live Selling › Sesi live (tombol Rincian pada sesi)",
    account_scope="required",
    context=("live_session",),
    dedupe=("session_id", "catalog_item_id"),
    fields=(
        Field("sku", "SKU Produk", "str", True,
              ("sku", "kode sku", "kode produk", "product sku", "seller sku",
               "sku induk", "kode barang"), example="DA-GMB-001"),
        Field("product_name", "Nama Produk", "str", False,
              ("nama produk", "produk", "product name", "nama barang", "item"),
              note="Dipakai hanya bila SKU kosong; nama final tetap dari katalog"),
        Field("units_sold", "Unit Terjual", "int", True,
              ("terjual", "qty", "quantity", "jumlah", "unit terjual",
               "produk terjual", "quantity sold", "jumlah terjual"), example="12"),
        Field("revenue", "Omzet Produk (Rp)", "money", True,
              ("omzet", "penjualan", "gmv", "revenue", "subtotal",
               "total penjualan", "nilai penjualan"), example="1176000"),
        Field("orders", "Jumlah Order", "int", False,
              ("order", "pesanan", "jumlah pesanan", "orders")),
        Field("notes", "Catatan", "str", False, ("catatan", "keterangan")),
        Field("session_id", "Sesi Live", "str", True, derived=True),
        Field("session_date", "Tanggal Sesi", "datetime", False, derived=True),
        Field("catalog_item_id", "Item Katalog", "str", True, derived=True),
        Field("account_id", "Akun", "str", True, derived=True),
        Field("price_avg", "Harga Rata-rata", "money", False, derived=True),
    ),
)

# ═══════════════════════════════════════════════════════════════════════════════
# 5. JADWAL SHIFT HOST
# ═══════════════════════════════════════════════════════════════════════════════
LIVEHOST_SHIFTS = SourceType(
    key="livehost_shifts",
    label="Jadwal Shift Host Live",
    group="Live",
    collection="marketing_livehost_shifts",
    describe="Jadwal shift host per tanggal untuk satu akun. Host wajib sudah "
             "di-assign ke akun tersebut.",
    module_hint="Live Selling › Host live",
    account_scope="required",
    context=("host",),
    dedupe=("account_id", "host_id", "date", "shift_start_time"),
    fields=(
        Field("date", "Tanggal", "date", True, _DATE_SYN, example="2026-08-01"),
        Field("shift_type", "Jenis Shift", "enum", False,
              ("shift", "tipe shift", "sesi"),
              ("morning", "afternoon", "evening", "night"), example="evening"),
        Field("shift_start_time", "Jam Mulai", "str", True,
              ("mulai", "jam mulai", "start time"), example="19:00"),
        Field("shift_end_time", "Jam Selesai", "str", True,
              ("selesai", "jam selesai", "end time"), example="22:00"),
        Field("notes", "Catatan", "str", False, ("catatan",)),
        Field("account_id", "Akun", "str", True, derived=True),
        Field("host_id", "Host", "str", True, derived=True),
    ),
)

# ═══════════════════════════════════════════════════════════════════════════════
# 6. ITEM KATALOG TOKO
# ═══════════════════════════════════════════════════════════════════════════════
CATALOG_ITEMS = SourceType(
    key="catalog_items",
    label="Item Katalog Toko",
    group="Katalog",
    collection="marketing_catalog_items",
    describe="Daftar produk yang dijual di satu akun. Kalau SKU-nya sama dengan "
             "master FG, stok & HPP bisa disinkronkan setelah impor.",
    module_hint="Manajemen Katalog",
    account_scope="required",
    context=("catalog",),
    dedupe=("catalog_id", "sku"),
    fields=(
        Field("sku", "SKU", "str", True, ("kode sku", "sku", "kode produk", "seller sku"),
              example="DA-GMS-001"),
        Field("name", "Nama Produk", "str", True,
              ("nama", "produk", "nama produk", "product name"),
              example="Gamis Syari Daluna"),
        Field("category", "Kategori", "str", False, ("kategori", "category")),
        Field("harga_jual", "Harga Jual (Rp)", "money", True,
              ("harga", "harga jual", "price", "harga final"), example="189000"),
        Field("harga_coret", "Harga Coret (Rp)", "money", False,
              ("harga coret", "harga promo", "strike price", "harga sebelum diskon")),
        Field("harga_original", "Harga List (Rp)", "money", False,
              ("harga original", "list price", "harga normal")),
        Field("hpp", "HPP (Rp)", "money", False, ("hpp", "cost", "harga pokok"),
              note="Kalau kosong dan SKU cocok master FG, HPP diambil dari master"),
        Field("stock_quantity", "Stok", "int", False, ("stok", "stock", "qty", "persediaan")),
        Field("stock_alert_threshold", "Batas Stok Rendah", "int", False,
              ("batas stok", "min stok", "reorder point")),
        Field("platform_url", "Link Produk", "str", False, ("url", "link", "tautan produk")),
        Field("description", "Deskripsi", "str", False, ("deskripsi", "description")),
        Field("is_active", "Aktif", "bool", False, ("aktif", "status", "active")),
        Field("catalog_id", "Katalog", "str", True, derived=True),
        Field("account_id", "Akun", "str", True, derived=True),
    ),
)

# ═══════════════════════════════════════════════════════════════════════════════
# 7. KALENDER KONTEN
# ═══════════════════════════════════════════════════════════════════════════════
CONTENT = SourceType(
    key="content_calendar",
    label="Kalender Konten",
    group="Konten",
    collection="marketing_content_calendar",
    describe="Rencana konten per tanggal untuk satu akun.",
    module_hint="Kalender Konten",
    account_scope="required",
    dedupe=("account_id", "date", "title"),
    fields=(
        Field("date", "Tanggal", "date", True, _DATE_SYN, example="2026-08-01"),
        Field("content_type", "Jenis Konten", "enum", True,
              ("jenis", "tipe konten", "content type", "format"),
              ("foto_produk", "video_pendek", "reels_tiktok", "live_streaming",
               "carousel", "story", "artikel", "lainnya"), example="reels_tiktok"),
        Field("title", "Judul Konten", "str", True, ("judul", "title", "topik"),
              example="Unboxing gamis ukuran M-XXXL"),
        Field("description", "Deskripsi", "str", False, ("deskripsi", "caption", "isi")),
        Field("cta", "Call To Action", "str", False, ("cta", "ajakan")),
        Field("post_time", "Jam Tayang", "str", False, ("jam", "waktu posting", "post time"),
              example="20:00"),
        Field("reference_link", "Link Referensi", "str", False, ("link", "referensi", "url")),
        Field("status", "Status", "enum", False, ("status",),
              ("draft", "scheduled", "posted", "cancelled"), example="scheduled"),
        Field("account_id", "Akun", "str", True, derived=True),
    ),
)

# ═══════════════════════════════════════════════════════════════════════════════
# 8. KAMPANYE DISKON
# ═══════════════════════════════════════════════════════════════════════════════
DISCOUNTS = SourceType(
    key="discounts",
    label="Kampanye Diskon",
    group="Konten",
    collection="marketing_discounts",
    describe="Kampanye diskon/voucher per akun beserta periode berlakunya.",
    module_hint="Kampanye Diskon",
    account_scope="required",
    dedupe=("account_id", "name", "start_date"),
    fields=(
        Field("name", "Nama Kampanye", "str", True, ("nama", "kampanye", "campaign"),
              example="Flash Sale Harbolnas"),
        Field("discount_type", "Jenis Diskon", "enum", True,
              ("tipe", "jenis diskon", "discount type"),
              ("flash_sale", "voucher", "bundling", "free_shipping", "cashback",
               "diskon_toko", "lainnya"), example="flash_sale"),
        Field("discount_value", "Nilai Diskon", "num", True,
              ("nilai", "besaran", "diskon", "value"), example="50"),
        Field("discount_unit", "Satuan", "enum", False, ("satuan", "unit"),
              ("persen", "rupiah"), example="persen"),
        Field("min_purchase", "Minimal Belanja (Rp)", "money", False,
              ("min belanja", "minimum purchase", "min pembelian")),
        Field("max_discount", "Maksimal Diskon (Rp)", "money", False,
              ("max diskon", "batas diskon")),
        Field("start_date", "Mulai", "date", True,
              ("tanggal mulai", "start", "start date", "periode mulai"),
              example="2026-08-01"),
        Field("end_date", "Berakhir", "date", True,
              ("tanggal berakhir", "end", "end date", "periode akhir"),
              example="2026-08-07"),
        Field("product_scope", "Cakupan Produk", "enum", False,
              ("cakupan", "scope", "berlaku untuk"),
              ("semua_produk", "produk_pilihan", "kategori"), example="semua_produk"),
        Field("description", "Deskripsi", "str", False, ("deskripsi", "keterangan")),
        Field("account_id", "Akun", "str", True, derived=True),
    ),
)

# ═══════════════════════════════════════════════════════════════════════════════
# 9. PELUNCURAN PRODUK
# ═══════════════════════════════════════════════════════════════════════════════
LAUNCHES = SourceType(
    key="product_launches",
    label="Peluncuran Produk",
    group="Konten",
    collection="marketing_product_launches",
    describe="Rencana/realisasi peluncuran produk baru di satu akun.",
    module_hint="Peluncuran Produk",
    account_scope="required",
    dedupe=("account_id", "product_name", "launch_date"),
    fields=(
        Field("product_name", "Nama Produk", "str", True,
              ("produk", "nama produk", "product name"),
              example="Gamis Busui Friendly DA-2026"),
        Field("sku", "SKU", "str", False, ("kode sku", "sku"),
              note="Kalau cocok dengan katalog toko, item katalognya ditautkan"),
        Field("launch_date", "Tanggal Launch", "date", True,
              ("tanggal", "tanggal launch", "launch date"), example="2026-08-01"),
        Field("material", "Bahan", "str", False, ("bahan", "material", "kain")),
        Field("model", "Model", "str", False, ("model", "tipe model")),
        Field("original_price", "Harga Normal (Rp)", "money", False,
              ("harga normal", "harga awal", "original price")),
        Field("flash_sale_price", "Harga Flash Sale (Rp)", "money", False,
              ("harga flash sale", "harga promo")),
        Field("cross_price", "Harga Coret (Rp)", "money", False, ("harga coret",)),
        Field("listing_price", "Harga Listing (Rp)", "money", False,
              ("harga listing", "harga jual", "harga tayang")),
        Field("description", "Deskripsi", "str", False, ("deskripsi",)),
        Field("status", "Status", "enum", False, ("status",),
              ("planned", "ready", "launched", "postponed", "cancelled"),
              example="planned"),
        Field("launch_notes", "Catatan", "str", False, ("catatan",)),
        Field("account_id", "Akun", "str", True, derived=True),
    ),
)

# ═══════════════════════════════════════════════════════════════════════════════
# 10. KIRIM SAMPLE
# ═══════════════════════════════════════════════════════════════════════════════
SAMPLES = SourceType(
    key="samples",
    label="Kirim Sample ke Kreator",
    group="Kreator",
    collection="marketing_samples",
    describe="Pengiriman sample produk ke kreator/afiliator. WAJIB memilih akun; "
             "kreator dipilih dari daftar yang sudah di-assign ke akun itu, sehingga "
             "biaya sample tidak dibebankan ke toko yang salah.",
    module_hint="Kirim Sample",
    account_scope="required",
    context=("creator",),
    dedupe=("account_id", "date", "username", "product"),
    fields=(
        Field("date", "Tanggal Kirim", "date", True, _DATE_SYN, example="2026-08-01"),
        Field("sample_type", "Jenis Sample", "enum", True,
              ("jenis", "tipe", "sample type"), ("live", "video"), example="video"),
        Field("product", "Produk", "str", True,
              ("produk", "nama produk", "barang"), example="Gamis Daluna Basic",
              note="Kalau cocok katalog toko, SKU/HPP/ukuran ikut master"),
        Field("sku", "SKU", "str", False, ("kode sku", "sku")),
        Field("size", "Ukuran", "str", False, ("ukuran", "size")),
        Field("color", "Warna", "str", False, ("warna", "color")),
        Field("quantity", "Jumlah", "int", True, ("qty", "jumlah"), example="1"),
        Field("hpp", "HPP Satuan (Rp)", "money", False, ("hpp", "harga pokok"),
              note="Boleh kosong — diambil dari katalog bila SKU/produk cocok"),
        Field("ongkir", "Ongkir (Rp)", "money", False, ("ongkir", "biaya kirim")),
        Field("courier", "Kurir", "enum", False, ("kurir", "ekspedisi"), COURIERS,
              example="jnt"),
        Field("video_link", "Link Video", "str", False, ("link", "url video", "tautan")),
        Field("progress", "Progress", "enum", False, ("progress", "tindak lanjut"),
              ("open", "follow_up", "sold", "no_response", "closed"), example="open"),
        Field("shipment_status", "Status Kirim", "enum", False, ("status kirim", "status"),
              ("pending", "shipped", "delivered", "returned", "cancelled"),
              example="pending"),
        Field("notes", "Catatan", "str", False, ("catatan",)),
        Field("account_id", "Akun", "str", True, derived=True),
        Field("creator_id", "Kreator", "str", False, derived=True),
        Field("username", "Username Kreator", "str", False, derived=True),
        Field("total_hpp", "Total HPP (Rp)", "money", False, derived=True),
    ),
)

# ═══════════════════════════════════════════════════════════════════════════════
# 11. KREATOR / KOL
# ═══════════════════════════════════════════════════════════════════════════════
CREATORS = SourceType(
    key="kol_creators",
    label="Master Kreator / KOL",
    group="Kreator",
    collection="marketing_kol_creators",
    describe="Master kreator. Akun yang dipilih menjadi assignment awal kreator "
             "(boleh ditambah akun lain setelah impor).",
    module_hint="KOL & Kreator",
    account_scope="optional",
    dedupe=("creator_code",),
    fields=(
        Field("name", "Nama Kreator", "str", True, ("nama", "creator", "nama lengkap"),
              example="Ayu Fashion"),
        Field("creator_code", "Kode Kreator", "str", True,
              ("kode", "code", "kode kol"), example="KOL-001"),
        Field("login_email", "Email Login", "str", True, ("email", "email login"),
              example="ayu@contoh.id"),
        Field("phone", "No. HP", "str", False, ("hp", "telepon", "phone", "wa")),
        Field("tiktok_username", "Username TikTok", "str", False,
              ("tiktok", "akun tiktok", "username tiktok")),
        Field("instagram_username", "Username Instagram", "str", False,
              ("instagram", "ig", "akun ig")),
        Field("shopee_username", "Username Shopee", "str", False, ("shopee",)),
        Field("notes", "Catatan", "str", False, ("catatan",)),
        Field("assigned_account_ids", "Akun Ter-assign", "list", False, derived=True),
    ),
)

# ═══════════════════════════════════════════════════════════════════════════════
# 12. RETUR
# ═══════════════════════════════════════════════════════════════════════════════
RETURNS = SourceType(
    key="returns",
    label="Retur & Refund",
    group="After-Sales",
    collection="marketing_returns",
    describe="Pengembalian barang per akun. Kalau No. Pesanan cocok dengan order "
             "yang ada, retur ditautkan ke order tersebut.",
    module_hint="Komplain & Retur",
    account_scope="required",
    dedupe=("account_id", "order_id", "product"),
    identity="order_id",
    identity_collection="marketing_orders",
    identity_label="nomor pesanan",
    fields=(
        Field("date", "Tanggal Retur", "date", True,
              _DATE_SYN + ("waktu pengembalian diajukan", "time requested",
                           "tanggal pengembalian", "waktu pengajuan"),
              example="2026-08-01"),
        Field("order_id", "No. Pesanan", "str", True,
              ("order id", "no pesanan", "nomor pesanan", "order sn", "no. pesanan"),
              example="SHP-2026081001", id_teks=True),
        Field("return_id", "No. Pengembalian", "str", False,
              ("no pengembalian", "return order id", "return id", "no. pengembalian"),
              id_teks=True),
        Field("product", "Produk", "str", True, ("produk", "nama produk", "product name")),
        Field("sku", "SKU", "str", False,
              ("sku induk", "seller sku", "sku id", "kode variasi", "nomor referensi sku")),
        Field("variation", "Variasi", "str", False, ("variasi", "sku name", "nama variasi")),
        Field("quantity", "Jumlah Dikembalikan", "int", False,
              ("jumlah produk dikembalikan", "return quantity", "qty", "jumlah")),
        Field("buyer_username", "Username Pembeli", "str", False,
              ("username pembeli", "username (pembeli)", "buyer username")),
        # 2026-11-09 (riset §6.1) — "Order Amount" = total PESANAN, bukan harga satuan
        # barang yang diretur; dulu keduanya bertabrakan di field ini.
        Field("price", "Harga (Rp)", "money", False,
              ("harga", "nilai", "harga satuan", "return unit price")),
        # Alasan retur di berkas asli adalah TEKS BEBAS platform ("Barang rusak",
        # "Berubah pikiran", "Produk tidak sesuai deskripsi", …). Kalau ia
        # diperlakukan enum ketat, SELURUH berkas retur ditolak. Jadi: kamus untuk
        # nilai yang sudah dikenal, `lainnya` + peringatan untuk yang baru, dan
        # nilai aslinya SELALU disimpan di `reason_raw`.
        Field("reason", "Alasan", "enum", True,
              ("alasan", "reason", "penyebab", "alasan pengembalian", "return reason"),
              ("ukuran_tidak_sesuai", "warna_berbeda", "barang_rusak", "salah_kirim",
               "kualitas_buruk", "berubah_pikiran", "barang_kurang", "lainnya"),
              example="ukuran_tidak_sesuai",
              value_map=_RETURN_REASON_MAP, keep_raw=True, value_map_fallback="lainnya"),
        Field("reason_detail", "Detail Alasan", "str", False,
              ("detail", "keterangan", "catatan pengembalian barang", "buyer note")),
        Field("courier", "Kurir", "enum", False, ("kurir",), COURIERS,
              value_map=_COURIER_MAP, keep_raw=True, value_map_fallback="lainnya"),
        Field("refund_type", "Jenis Refund", "enum", False,
              ("tipe refund", "refund", "tipe pengembalian", "return type",
               "solusi pengembalian barang dana", "solusi pengembalian barang/dana"),
              ("full_refund", "partial_refund", "replacement", "no_refund"),
              example="full_refund",
              value_map=_REFUND_TYPE_MAP, keep_raw=True, value_map_fallback="full_refund"),
        # 2026-11-09 (riset G11) — "Compensation Amount" (TikTok) / "Jumlah Kompensasi"
        # (Shopee) = kompensasi yang DITERIMA PENJUAL dari platform, bukan dana yang
        # dikembalikan ke pembeli. Dulu dicatat sebagai nilai refund.
        Field("refund_amount", "Nilai Refund (Rp)", "money", False,
              ("jumlah refund", "nilai refund", "total pengembalian dana",
               "refund amount")),
        Field("compensation_amount", "Kompensasi untuk Penjual (Rp)", "money", False,
              ("compensation amount", "jumlah kompensasi"),
              note="Dibayar platform ke penjual — tidak mengurangi omzet"),
        Field("refund_completed_at", "Waktu Refund Selesai", "date", False,
              ("waktu pengembalian dana selesai", "refund time")),
        Field("tracking_number", "No. Resi Retur", "str", False,
              ("return logistics tracking id", "no resi", "resi")),
        Field("status", "Status", "enum", False,
              ("status", "status pembatalan pengembalian",
               "status pembatalan/ pengembalian", "return status"),
              ("pending", "approved", "rejected", "completed"), example="pending",
              value_map=_RETURN_STATUS_MAP, keep_raw=True, value_map_fallback="pending"),
        Field("substatus_raw", "Sub-status Retur", "str", False, ("return sub status",),
              note="'Request Canceled' = permintaan dibatalkan (status ditolak)"),
        # Turunan (keputusan owner 9 Nov): "Refund only" = barang TIDAK kembali ke gudang.
        Field("goods_returned", "Barang Kembali ke Gudang", "bool", False, derived=True),
        Field("notes", "Catatan", "str", False, ("catatan", "buyer note")),
        Field("account_id", "Akun", "str", True, derived=True),
    ),
)

# ═══════════════════════════════════════════════════════════════════════════════
# 13. ULASAN
# ═══════════════════════════════════════════════════════════════════════════════
REVIEWS = SourceType(
    key="reviews",
    label="Rating & Ulasan",
    group="After-Sales",
    collection="marketing_reviews",
    describe="Ulasan pembeli per akun. Dipakai menghitung skor kesehatan akun.",
    module_hint="Rating & Ulasan",
    account_scope="required",
    dedupe=("account_id", "order_id", "product"),
    identity="order_id",
    identity_collection="marketing_orders",
    identity_label="nomor pesanan",
    fields=(
        Field("date", "Tanggal Ulasan", "date", True, _DATE_SYN, example="2026-08-01"),
        Field("order_id", "No. Pesanan", "str", False,
              ("order id", "no pesanan", "order sn")),
        Field("rating", "Rating (1-5)", "int", True, ("rating", "bintang", "nilai"),
              example="4"),
        Field("product", "Produk", "str", True, ("produk", "nama produk")),
        Field("category", "Kategori Keluhan", "enum", False,
              ("kategori", "jenis keluhan", "category"),
              ("kualitas_bagus", "sesuai_ekspektasi", "ukuran_tidak_sesuai",
               "warna_berbeda", "pengiriman_lama", "barang_rusak", "lainnya")),
        Field("review_text", "Isi Ulasan", "str", False, ("ulasan", "komentar", "review")),
        Field("status", "Status", "enum", False, ("status",),
              ("pending", "responded", "escalated", "closed"), example="pending"),
        Field("account_id", "Akun", "str", True, derived=True),
    ),
)

# ═══════════════════════════════════════════════════════════════════════════════
# 14. KOMPLAIN
# ═══════════════════════════════════════════════════════════════════════════════
COMPLAINTS = SourceType(
    key="complaints",
    label="Komplain Pelanggan",
    group="After-Sales",
    collection="marketing_complaints",
    describe="Komplain masuk per akun beserta tingkat keparahan (untuk SLA).",
    module_hint="Komplain & Retur",
    account_scope="required",
    dedupe=("account_id", "complaint_number"),
    identity="complaint_number",
    identity_label="nomor komplain",
    fields=(
        Field("complaint_date", "Tanggal Komplain", "datetime", True, _DATE_SYN,
              example="2026-08-01"),
        Field("complaint_number", "No. Komplain", "str", False,
              ("no komplain", "ticket", "nomor tiket"),
              note="Boleh kosong — dinomori otomatis KOMP-YYYY-####"),
        Field("customer_name", "Nama Pelanggan", "str", True,
              ("pelanggan", "pembeli", "customer")),
        Field("product_name", "Produk", "str", False, ("produk", "nama produk")),
        Field("price", "Nilai Transaksi (Rp)", "money", False, ("harga", "nilai")),
        Field("complaint_text", "Isi Komplain", "str", True,
              ("komplain", "keluhan", "isi", "pesan")),
        Field("category", "Kategori", "enum", False, ("kategori", "jenis"),
              ("barang_rusak", "salah_kirim", "pengiriman_lama", "seller_unresponsive",
               "produk_tidak_sesuai", "refund_lambat", "lainnya")),
        Field("severity", "Tingkat", "enum", False, ("tingkat", "prioritas", "severity"),
              ("low", "medium", "high", "critical"), example="medium"),
        Field("status", "Status", "enum", False, ("status",),
              ("open", "in_progress", "resolved", "closed"), example="open"),
        Field("order_id", "No. Pesanan", "str", False, ("order id", "no pesanan")),
        Field("account_id", "Akun", "str", True, derived=True),
    ),
)

# ═══════════════════════════════════════════════════════════════════════════════
# 15. KESEHATAN AKUN
# ═══════════════════════════════════════════════════════════════════════════════
HEALTH = SourceType(
    key="account_health",
    label="Kesehatan Akun (snapshot)",
    group="Penjualan",
    collection="marketing_account_health",
    describe="Snapshot metrik kesehatan akun (skor toko, keterlambatan kirim, "
             "pembatalan, respon chat) pada satu tanggal.",
    module_hint="Kesehatan Akun",
    account_scope="required",
    dedupe=("account_id", "snapshot_date"),
    fields=(
        Field("snapshot_date", "Tanggal Snapshot", "datetime", True, _DATE_SYN,
              example="2026-08-01"),
        Field("ses_score", "Skor Toko", "num", False,
              ("skor", "ses", "shop score", "nilai toko")),
        Field("late_shipment_rate", "Late Shipment (%)", "pct", False,
              ("keterlambatan kirim", "lsr")),
        Field("cancellation_rate", "Cancellation (%)", "pct", False, ("pembatalan",)),
        Field("response_rate", "Response Rate (%)", "pct", False, ("respon chat", "respon")),
        Field("response_time_hours", "Waktu Respon (jam)", "num", False, ("waktu respon",)),
        Field("order_defect_rate", "Order Defect (%)", "pct", False, ("odr", "defect")),
        Field("return_rate", "Return Rate (%)", "pct", False, ("retur",)),
        Field("rating_score", "Rating", "num", False, ("rating", "nilai")),
        Field("total_reviews", "Jumlah Ulasan", "int", False, ("ulasan",)),
        Field("account_id", "Akun", "str", True, derived=True),
    ),
)


# ═══════════════════════════════════════════════════════════════════════════════
# 16. KPI PLATFORM HARIAN (F7.2) — ekspor Seller Center: statistik toko & konten
# ═══════════════════════════════════════════════════════════════════════════════
# KENAPA KOLEKSI SENDIRI (`marketing_platform_kpi_daily`), BUKAN `marketing_sales_data`:
# omzet SSOT toko adalah TURUNAN pesanan (F2) — satu-satunya angka yang boleh dipakai
# untuk uang. Angka "Penjualan" di ekspor KPI Shopee memakai definisi platform
# (pesanan dibuat / siap dikirim / dibayar, termasuk yang nanti batal) dan **tidak
# boleh** dijumlah dengan omzet pesanan. Menaruhnya di koleksi terpisah membuat
# aturan itu berlaku secara struktural, bukan sekadar niat.
_KPI_COMMON: Tuple[Field, ...] = (
    Field("date", "Tanggal", "date", True, _DATE_SYN, example="2026-08-13"),
    Field("channel", "Kanal", "enum", True, ("kanal", "channel"),
          ("shop", "live", "video"), example="live",
          note="shop = statistik toko; live = Live Streaming; video = Video"),
    Field("source", "Sumber Ekspor", "str", True, ("sumber", "source"),
          example="shopee_live_1d",
          note="Ditulis penormal berkas — jejak dari ekspor mana angka ini datang"),
    Field("gmv_created", "Penjualan (Pesanan Dibuat)", "money", False,
          ("penjualan pesanan dibuat", "penjualan(pesanan dibuat)", "total penjualan")),
    Field("gmv_ready", "Penjualan (Siap Dikirim)", "money", False,
          ("penjualan pesanan siap dikirim", "penjualan(pesanan siap dikirim)")),
    Field("gmv_paid", "Penjualan (Dibayar)", "money", False, ("penjualan pesanan dibayar",)),
    Field("orders_created", "Pesanan (Dibuat)", "int", False,
          ("pesanan pesanan dibuat", "total pesanan")),
    Field("orders_ready", "Pesanan (Siap Dikirim)", "int", False,
          ("pesanan pesanan siap dikirim",)),
    Field("orders_paid", "Pesanan (Dibayar)", "int", False, ("pesanan pesanan dibayar",)),
    Field("products_sold", "Produk Terjual", "int", False, ("produk terjual",)),
    Field("buyers", "Pembeli", "int", False, ("pembeli",)),
    Field("visitors", "Pengunjung", "int", False, ("total pengunjung", "pengunjung")),
    Field("product_clicks", "Produk Diklik", "int", False, ("produk diklik",)),
    Field("product_views", "Produk Dilihat", "int", False, ("jumlah produk dilihat",)),
    Field("conversion_rate", "Konversi (%)", "pct", False, ("tingkat konversi pesanan",)),
    Field("ctr", "Persentase Klik (%)", "pct", False, ("persentase klik", "ctr")),
    Field("add_to_cart", "Tambah ke Keranjang", "int", False, ("tambah ke keranjang",)),
    Field("viewers", "Penonton", "int", False, ("penonton",)),
    Field("active_viewers", "Penonton Aktif", "int", False, ("penonton aktif",)),
    Field("effective_viewers", "Penonton Efektif", "int", False,
          ("penonton efektif menonton 3 detik",)),
    Field("peak_viewers", "Penonton Tertinggi", "int", False, ("penonton tertinggi",)),
    Field("views", "Ditonton / Dilihat", "int", False, ("ditonton", "dilihat")),
    Field("avg_watch_seconds", "Rata-rata Tonton (detik)", "num", False,
          ("rata rata durasi ditonton",),
          note="Durasi teks ekspor ('10j50m8d', '00:01:19') diubah menjadi detik"),
    Field("live_sessions", "Jumlah Livestream", "int", False, ("jumlah livestream",)),
    Field("live_minutes", "Durasi Live (menit)", "num", False, ("jumlah durasi livestream",)),
    Field("videos_with_product", "Video dengan Produk", "int", False,
          ("video dengan produk",)),
    Field("completion_rate", "Video Selesai Ditonton (%)", "pct", False,
          ("tingkat video selesai ditonton",)),
    Field("likes", "Suka", "int", False, ("suka", "likes")),
    Field("shares", "Share", "int", False, ("share", "dibagikan")),
    Field("comments", "Komentar", "int", False, ("komentar",)),
    Field("new_followers", "Pengikut Baru", "int", False,
          ("pengikut baru dari livestream", "pengikut baru dari video")),
    Field("voucher_shop_claimed", "Voucher Toko Diklaim", "int", False,
          ("voucher toko diklaim",)),
    Field("voucher_live_claimed", "Voucher Live Diklaim", "int", False,
          ("voucher spesial live diklaim",)),
    Field("coin_claimed", "Koin Diklaim", "int", False, ("koin diklaim",)),
    Field("gmv_product_page", "Penjualan Halaman Produk", "money", False,
          ("penjualan dari halaman produk",)),
    Field("gmv_live", "Penjualan dari Live", "money", False, ("penjualan dari live penjual",)),
    Field("gmv_video", "Penjualan dari Video", "money", False,
          ("penjualan dari video penjual",)),
    Field("gmv_affiliate", "Penjualan dari Affiliate", "money", False,
          ("penjualan dari affiliate",)),
    Field("gmv_ads", "Penjualan dari Iklan", "money", False,
          ("penjualan dari iklan shopee",)),
    Field("platform_user_id", "User Id Platform", "str", False, ("user id",)),
    Field("account_id", "Akun", "str", True, derived=True),
)

SHOPEE_SHOP_KPI = SourceType(
    key="shopee_shop_kpi",
    label="KPI Toko Shopee (Statistik Toko)",
    group="KPI Platform",
    collection="marketing_platform_kpi_daily",
    describe="Statistik toko harian dari Seller Center (.xlsx): penjualan per basis "
             "pesanan, pengunjung, klik produk, konversi, dan kontribusi kanal "
             "(halaman produk / live / video / affiliate / iklan). Angka ini KPI "
             "platform — dipakai membaca traffic & kontribusi kanal, TIDAK "
             "menggantikan omzet pesanan.",
    module_hint="Kalender Konten › KPI platform",
    export_hint="Seller Center → Data Bisnis → Statistik Toko → Ekspor (.xlsx)",
    account_scope="required",
    dedupe=("account_id", "date", "channel"),
    prenorm="shopee_shop_stats",
    fields=_KPI_COMMON,
)

SHOPEE_CONTENT_KPI = SourceType(
    key="shopee_content_kpi",
    label="KPI Konten Shopee (Live & Video)",
    group="KPI Platform",
    collection="marketing_platform_kpi_daily",
    describe="Rekap harian Live Streaming / Video dari Seller Center (.csv): "
             "penonton, ditonton, durasi tonton, suka/komentar/share, pengikut "
             "baru, dan penjualan yang diakui platform pada kanal itu. Kanal "
             "(live/video) dibaca dari kolom penanda di berkas — bukan dari nama berkas.",
    module_hint="Kalender Konten › KPI platform",
    export_hint="Seller Center → Bisnis Saya → Live Streaming / Video → Ekspor data (.csv)",
    account_scope="required",
    dedupe=("account_id", "date", "channel"),
    prenorm="shopee_content_kpi",
    fields=_KPI_COMMON,
)

# ═══════════════════════════════════════════════════════════════════════════════
# 17. LAPORAN IKLAN CPC SHOPEE (F7.2)
# ═══════════════════════════════════════════════════════════════════════════════
# Laporan ini per KAMPANYE untuk satu PERIODE (bukan per tanggal). Karena itu
# `period_start`/`period_end` disimpan apa adanya dan `date` = awal periode:
# realisasi anggaran F5 (`marketing_cycle._auto_ads`) menjumlah `spend` per bulan,
# jadi periode yang menyeberang bulan DITOLAK oleh penormal — bukan dibagi rata
# dengan asumsi yang tidak bisa dibuktikan.
SHOPEE_ADS_CPC = SourceType(
    key="shopee_ads_cpc",
    label="Laporan Iklan Shopee (CPC)",
    group="Iklan",
    collection="marketing_ads_data",
    describe="Laporan iklan CPC Shopee per kampanye untuk satu periode: biaya, "
             "tayangan, klik, konversi, omzet iklan, ROAS, dan ACOS. Biaya iklan "
             "otomatis ikut realisasi anggaran kategori 'ads' pada Target & Anggaran.",
    module_hint="Laporan Marketing › Performa iklan, dan realisasi Iklan di Target & Anggaran",
    export_hint="Seller Center → Iklan Saya → Laporan Iklan → Semua Laporan Iklan CPC (.csv)",
    account_scope="required",
    dedupe=("account_id", "campaign_name", "period_start", "period_end"),
    prenorm="shopee_ads_cpc",
    fields=(
        Field("date", "Tanggal (awal periode)", "date", True, _DATE_SYN,
              example="2026-08-07"),
        Field("period_start", "Periode Mulai", "date", True, ("periode mulai",),
              example="2026-08-07"),
        Field("period_end", "Periode Selesai", "date", True, ("periode selesai",),
              example="2026-08-13"),
        Field("campaign_name", "Nama Iklan", "str", True, ("nama iklan", "kampanye"),
              example="Iklan Produk Otomatis"),
        Field("spend", "Biaya Iklan (Rp)", "money", True, ("biaya",), example="374074"),
        Field("revenue", "Omzet dari Iklan (Rp)", "money", False, ("omzet penjualan",)),
        Field("direct_revenue", "Penjualan Langsung (Rp)", "money", False,
              ("penjualan langsung gmv langsung",)),
        Field("impressions", "Dilihat", "int", False, ("dilihat",)),
        Field("clicks", "Jumlah Klik", "int", False, ("jumlah klik",)),
        Field("conversions", "Konversi", "int", False, ("konversi",)),
        Field("direct_conversions", "Konversi Langsung", "int", False,
              ("konversi langsung",)),
        Field("products_sold", "Produk Terjual", "int", False, ("produk terjual",)),
        Field("direct_products_sold", "Terjual Langsung", "int", False,
              ("terjual langsung",)),
        Field("add_to_cart", "Tambah ke Keranjang", "int", False, ("tambah ke keranjang",)),
        Field("ctr_platform", "Persentase Klik Platform (%)", "pct", False,
              ("persentase klik",)),
        Field("acos", "ACOS (%)", "pct", False,
              ("persentase biaya iklan terhadap penjualan dari iklan acos",)),
        Field("roas_platform", "Efektifitas Iklan (ROAS platform)", "num", False,
              ("efektifitas iklan",)),
        Field("direct_roas_platform", "Efektivitas Langsung", "num", False,
              ("efektivitas langsung",)),
        Field("status", "Status", "enum", False, ("status",),
              ("active", "paused", "ended"),
              value_map=(("berjalan", "active"), ("aktif", "active"),
                         ("dijeda", "paused"), ("jeda", "paused"),
                         ("berakhir", "ended"), ("selesai", "ended"),
                         ("tidak aktif", "paused")),
              keep_raw=True, value_map_fallback="active",
              note="Status platform diterjemahkan lewat kamus; nilai asing jatuh ke "
                   "'active' dengan peringatan supaya biaya iklan tidak pernah hilang"),
        Field("ad_type", "Jenis Iklan", "str", False, ("jenis iklan",),
              note="Disimpan apa adanya (Iklan Produk, GMV Max, …) — tidak dipaksa "
                   "masuk daftar tertutup supaya jenis baru Shopee tidak menolak baris"),
        Field("product_code", "Kode Produk", "str", False, ("kode produk",)),
        Field("bidding_mode", "Mode Bidding", "str", False, ("mode bidding",)),
        Field("placement", "Penempatan Iklan", "str", False, ("penempatan iklan",)),
        Field("campaign_started", "Tanggal Mulai Kampanye", "str", False,
              ("tanggal mulai",)),
        Field("shop_name", "Nama Toko (di berkas)", "str", False, ("nama toko",)),
        Field("shop_username", "Username Toko", "str", False, ("username",)),
        Field("platform_shop_id", "ID Toko Platform", "str", False, ("id toko",)),
        Field("account_id", "Akun", "str", True, derived=True),
        Field("ctr", "CTR (%)", "pct", False, derived=True),
        Field("cpa", "CPA (Rp)", "money", False, derived=True),
        Field("roas", "ROAS", "num", False, derived=True),
    ),
)

# ═══════════════════════════════════════════════════════════════════════════════
# 17b. LAPORAN IKLAN TIKTOK GMV MAX (2026-11-09, riset G3/G4, keputusan owner)
# ═══════════════════════════════════════════════════════════════════════════════
# Ekspor GMV Max (Seller Center → Iklan → GMV Max → Ekspor) adalah AGREGAT untuk
# rentang tanggal yang dipilih saat mengekspor — berkasnya TIDAK punya kolom tanggal
# belanja. Karena itu:
#   · periode laporan WAJIB diisi staf saat unggah (atau tertulis di nama berkas);
#     periode yang menyeberang bulan ditolak, sama seperti laporan CPC Shopee;
#   · baris berbiaya 0 dibuang SEBELUM batas baris (ekspor contoh: 100.000 baris,
#     hanya 67 berbiaya), dan berkas tepat 100.000 baris diberi peringatan "mungkin
#     terpotong";
#   · kunci ganda = (toko, periode, ID kampanye, ID produk, ID video);
#   · uang ditulis dengan TITIK sebagai desimal ("40797.000" = Rp40.797) — dibaca
#     penormal dengan gaya angka per kolom (G1);
#   · "Pendapatan kotor" versi TikTok MEMUAT pesanan organik produk yang diiklankan:
#     dipakai untuk ROI iklan, TIDAK PERNAH dijumlah dengan omzet pesanan.
# Biaya iklan resmi untuk ANALISIS = laporan ini; jurnal tetap dari potongan di
# laporan penghasilan (Pencairan), supaya biaya tidak tercatat dua kali.
TIKTOK_GMV_MAX = SourceType(
    key="tiktok_gmv_max",
    label="Laporan Iklan TikTok GMV Max",
    group="Iklan",
    collection="marketing_ads_data",
    describe="Biaya & hasil iklan GMV Max TikTok per kampanye × produk × materi untuk SATU "
             "periode laporan. Berkas ekspornya tidak memuat tanggal, jadi periode wajib "
             "diisi saat unggah. Baris tanpa biaya dibuang. Pendapatan kotor TikTok "
             "termasuk pesanan organik — hanya untuk ROI iklan, bukan omzet.",
    module_hint="Laporan Marketing › Performa iklan, dan realisasi Iklan di Target & Anggaran",
    export_hint="TikTok Seller Center → Iklan → GMV Max → pilih rentang tanggal (dalam satu "
                "bulan) → Ekspor data. Tulis periodenya di layar unggah.",
    account_scope="required",
    dedupe=("account_id", "period_start", "period_end", "campaign_id", "product_id", "video_id"),
    prenorm="tiktok_gmv_max",
    fields=(
        Field("date", "Tanggal (awal periode)", "date", True, ("tanggal",), example="2026-08-01"),
        Field("period_start", "Periode Mulai", "date", True, ("periode mulai",),
              example="2026-08-01"),
        Field("period_end", "Periode Selesai", "date", True, ("periode selesai",),
              example="2026-08-31"),
        Field("campaign_name", "Nama Kampanye", "str", True, ("nama kampanye",),
              example="GMV Max Gamis"),
        Field("campaign_id", "ID Kampanye", "str", True, ("id campaign",), id_teks=True),
        Field("product_id", "ID Produk", "str", True, ("id produk",), id_teks=True),
        Field("video_id", "ID Video", "str", True, ("id video",),
              note="'-' untuk materi kartu produk (tanpa video)"),
        Field("ad_type", "Jenis Materi", "enum", False, ("jenis materi iklan",),
              ("search", "discovery", "video", "live", "shop", "affiliate", "lainnya"),
              value_map=(("Video", "video"), ("Live", "live"), ("LIVE", "live"),
                         ("Kartu produk", "shop"), ("Product card", "shop")),
              keep_raw=True, value_map_fallback="lainnya"),
        Field("video_title", "Judul Video", "str", False, ("judul video",)),
        Field("creator_handle", "Akun TikTok", "str", False, ("akun tiktok",)),
        Field("video_posted_at", "Waktu Posting Video", "str", False, ("waktu posting",),
              note="Tanggal unggah video — BUKAN tanggal biaya"),
        Field("authorization_type", "Jenis Otorisasi", "str", False, ("jenis otorisasi",)),
        Field("status_raw", "Status Materi", "str", False, ("status",)),
        Field("notes", "Catatan", "str", False, ("status sekunder penjelajahan",)),
        Field("spend", "Biaya Iklan (Rp)", "money", True, ("biaya",), example="40797"),
        Field("conversions", "Pesanan (SKU)", "int", False, ("pesanan sku",)),
        Field("cost_per_order", "Biaya per Pesanan (Rp)", "money", False, ("biaya per pesanan",)),
        Field("revenue", "Pendapatan Kotor TikTok (Rp)", "money", False, ("pendapatan kotor",),
              note="Termasuk pesanan organik — bukan omzet"),
        Field("impressions", "Impresi", "int", False, ("impresi iklan produk",)),
        Field("clicks", "Klik", "int", False, ("jumlah klik iklan produk",)),
        Field("ctr_platform", "CTR Platform (%)", "pct", False, ("tingkat klik iklan produk",)),
        Field("conversion_rate", "Rasio Konversi (%)", "pct", False, ("rasio konversi iklan",)),
        Field("currency", "Mata Uang", "str", False, ("mata uang",)),
        Field("account_id", "Akun", "str", True, derived=True),
        Field("ctr", "CTR (%)", "pct", False, derived=True),
        Field("cpa", "CPA (Rp)", "money", False, derived=True),
        Field("roas", "ROAS", "num", False, derived=True),
        Field("period_days", "Hari dalam Periode", "int", False, derived=True),
        Field("spend_per_day_avg", "Biaya Rata-rata per Hari", "money", False, derived=True),
        Field("source_report", "Sumber Laporan", "str", False, derived=True),
        Field("ad_platform", "Platform Iklan", "str", False, derived=True),
    ),
)

# ═══════════════════════════════════════════════════════════════════════════════
# 18. KPI PER KONTEN (F7.2) — kunci `published_url`
# ═══════════════════════════════════════════════════════════════════════════════
# Scorecard kreator butuh angka PER KONTEN, dan satu-satunya identitas konten yang
# tidak bisa dikarang adalah **link terbitnya**. Karena itu link adalah kunci
# dedupe: impor berulang MEMPERBARUI konten yang sama, tidak melahirkan baris baru.
CONTENT_PERFORMANCE = SourceType(
    key="content_performance",
    label="KPI per Konten (link terbit)",
    group="Konten",
    collection="marketing_content_calendar",
    describe="Angka per konten (views, suka, komentar, share, order, GMV) yang "
             "ditempelkan ke kalender konten memakai LINK TERBIT sebagai kunci. "
             "Link yang sudah ada diperbarui; link baru dibuat sebagai konten "
             "berstatus 'posted'. GMV di sini adalah angka platform per konten dan "
             "TIDAK dijumlah dengan omzet pesanan.",
    module_hint="Kalender Konten › Performa konten dan Scorecard kreator",
    export_hint="Seller Center/TikTok: ekspor daftar video/konten yang memuat kolom "
                "link konten + views/GMV per konten",
    account_scope="required",
    dedupe=("account_id", "published_url"),
    identity="published_url",
    identity_label="URL konten",
    fields=(
        Field("published_url", "Link Terbit", "str", True,
              ("link", "url", "tautan", "link konten", "url konten", "link video",
               "video url", "tautan video", "permalink"),
              example="https://shopee.co.id/video/123456"),
        Field("date", "Tanggal Tayang", "date", True,
              _DATE_SYN + ("tanggal tayang", "tanggal posting", "publish date"),
              example="2026-08-13"),
        Field("title", "Judul Konten", "str", False,
              ("judul", "title", "nama konten", "caption"),
              note="Boleh kosong — untuk konten baru judul dibuat dari link"),
        Field("content_type", "Jenis Konten", "enum", False,
              ("jenis", "tipe konten", "content type", "format"),
              ("foto_produk", "video_pendek", "reels_tiktok", "live_streaming",
               "carousel", "story", "artikel", "lainnya"), example="video_pendek"),
        Field("creator_code", "Kode/Username Kreator", "str", False,
              ("kode kreator", "username kreator", "kreator", "creator", "creator code"),
              note="Kalau cocok master kreator, konten ditautkan ke kreator itu; "
                   "kalau tidak cocok, baris tetap masuk dengan peringatan"),
        Field("views", "Views", "int", False,
              ("views", "ditonton", "dilihat", "tayangan", "penayangan")),
        Field("likes", "Suka", "int", False, ("suka", "likes")),
        Field("comments", "Komentar", "int", False, ("komentar", "comments")),
        Field("shares", "Share", "int", False, ("share", "dibagikan", "shares")),
        Field("saves", "Disimpan", "int", False, ("simpan", "tersimpan", "saves")),
        Field("watch_time_avg_sec", "Rata-rata Tonton (detik)", "num", False,
              ("durasi rata rata menonton", "avg watch time", "rata rata durasi ditonton")),
        Field("ctr", "CTR (%)", "pct", False, ("persentase klik", "ctr")),
        Field("orders", "Order dari Konten", "int", False,
              ("pesanan", "order", "pesanan pesanan dibuat")),
        Field("gmv", "GMV Konten (Rp)", "money", False,
              ("penjualan", "omzet", "gmv", "penjualan pesanan dibuat")),
        Field("platform_post_id", "ID Post Platform", "str", False,
              ("post id", "video id", "id konten")),
        Field("account_id", "Akun", "str", True, derived=True),
        Field("creator_id", "Kreator", "str", False, derived=True),
    ),
)


SOURCE_TYPES: Dict[str, SourceType] = {
    t.key: t for t in (
        SALES, ORDERS, MARKETPLACE_ORDERS, MARKETPLACE_FULFILLMENT, ADS,
        LIVE_SESSIONS, LIVE_SESSION_PRODUCTS,
        LIVEHOST_SHIFTS, CATALOG_ITEMS, CONTENT, DISCOUNTS, LAUNCHES, SAMPLES,
        CREATORS, RETURNS, REVIEWS, COMPLAINTS, HEALTH,
        # F7.2 — jalur impor KPI dari ekspor Seller Center
        SHOPEE_SHOP_KPI, SHOPEE_CONTENT_KPI, SHOPEE_ADS_CPC, CONTENT_PERFORMANCE,
        # 2026-11-09 — iklan TikTok GMV Max (periode wajib)
        TIKTOK_GMV_MAX,
    )
}

# 2026-11-09 (kebutuhan lintas-agen AI-impor) — jenis yang berkas ekspornya TIDAK memuat
# tanggal: periode laporan diisi staf saat unggah (isian ``period_start``/``period_end`` di
# ``POST /upload``, atau penanda ``periode_YYYY-MM-DD_YYYY-MM-DD__`` di nama berkas).
PERIOD_INPUT_TYPES = ("tiktok_gmv_max",)

# ══════════════════════════════════════════════════════════════════════════════
# F12 (2026-08-14, sesi #11) — JENIS YANG SENGAJA TIDAK PUNYA `identity`
# ══════════════════════════════════════════════════════════════════════════════
# Setiap jenis data WAJIB berada di salah satu dari dua tempat: punya `identity`
# (tanda pengenal GLOBAL satu baris) atau terdaftar DI SINI beserta alasannya.
# Pengecualian tanpa alasan = aturan yang hilang — dan penjaga yang memaksa semua
# jenis punya `identity` akan MENUDUH SALAH untuk berkas yang isinya memang tidak
# membawa penanda toko apa pun.
#
# Dijaga penjaga statik `A-3` di `test_core_f12_sidik_toko.py`: jenis baru yang
# tidak punya `identity` dan tidak terdaftar di sini ⇒ gate MERAH.
NO_IDENTITY_REASON: Dict[str, str] = {
    "sales_daily":
        "rekap HARIAN yang diketik/diimpor per tanggal — kuncinya tanggal + jenis "
        "omzet, dan setiap toko punya tanggal yang sama. Memakainya sebagai tanda "
        "pengenal akan menuduh semua toko saling mencuri baris.",
    "ads": "baris iklan dikunci per tanggal + nama kampanye; nama kampanye bebas "
           "diketik staf ('Iklan Agustus') sehingga kembar antar toko itu WAJAR.",
    "shopee_ads_cpc":
        "laporan iklan Shopee dikunci per nama kampanye + rentang periode. Nama "
        "kampanye tidak dijamin unik antar toko, jadi tidak bisa dipakai sebagai "
        "bukti kepemilikan. Yang menjaga jenis ini: penolakan periode BERIRISAN "
        "(409) per toko + peringatan 'berkas identik pernah masuk toko lain'.",
    "tiktok_gmv_max":
        "laporan GMV Max dikunci per periode + ID kampanye + ID produk + ID video. ID "
        "kampanye milik akun iklan, dan satu akun iklan bisa membiayai beberapa toko, jadi "
        "ID itu bukan bukti kepemilikan toko. Penjaga jenis ini: periode wajib + sidik isi "
        "berkas (berkas identik di toko lain diperingatkan).",
    "shopee_shop_kpi":
        "ekspor statistik toko hanya berisi TANGGAL & KANAL. Tidak ada satu pun "
        "penanda toko di dalam berkas — bahkan nama tokonya tidak ada. Satu-satunya "
        "penjaga yang mungkin adalah sidik gudang platform, dan ekspor ini tidak "
        "membawanya.",
    "shopee_content_kpi":
        "sama seperti statistik toko: tanggal + kanal. Kolom judul/URL konten ada "
        "pada jenis `content_performance` (yang PUNYA identity), bukan di sini.",
    "live_sessions":
        "sesi live dikunci per tanggal + judul; judul diketik staf ('Live Malam') "
        "dan kembar antar toko itu wajar.",
    "live_session_products":
        "rincian produk menempel pada SESI LIVE yang dipilih di layar (bukan pada "
        "toko lewat isi berkas); sesi live sudah berlingkup toko, dan omzet "
        "rinciannya dijaga tidak melebihi omzet sesi.",
    "livehost_shifts":
        "jadwal shift dikunci per host + tanggal + jam; host sudah di-assign ke "
        "toko (impor host yang belum di-assign DITOLAK), jadi lingkupnya dijaga "
        "lewat master host, bukan lewat isi berkas.",
    "catalog_items":
        "item katalog dikunci per katalog + SKU. Katalog dipilih di layar dan "
        "sudah berlingkup toko; SKU yang sama memang boleh dijual dua toko.",
    "content_calendar":
        "rencana konten dikunci per tanggal + judul yang diketik staf; kembar "
        "antar toko wajar. Bukti kepemilikan baru ada saat kontennya TERBIT "
        "(`content_performance`, yang punya identity URL).",
    "discounts": "kampanye diskon dikunci per nama + tanggal mulai; nama diketik "
                 "staf dan kembar antar toko wajar.",
    "product_launches":
        "peluncuran dikunci per nama produk + tanggal; produk yang sama memang "
        "diluncurkan di beberapa toko sekaligus.",
    "samples":
        "pengiriman sampel dikunci per tanggal + username + produk; kreator yang "
        "sama menerima sampel dari beberapa toko.",
    "kol_creators":
        "master kreator TIDAK berlingkup toko (satu kreator dipakai banyak toko); "
        "lingkupnya diatur `assigned_account_ids`, bukan isi berkas.",
    "account_health":
        "snapshot kesehatan akun dikunci per tanggal; setiap toko punya tanggal "
        "yang sama.",
}

# Nama lama dari mesin impor AI (universal_import) → jenis resmi.
# Dipertahankan supaya sesi impor lama masih bisa dibaca & tidak ada lagi baris
# yang jatuh ke koleksi karangan `marketing_import_<apa pun>`.
LEGACY_ALIASES: Dict[str, str] = {
    "shopee_orders": "orders",
    "tiktok_orders": "orders",
    "tokopedia_orders": "orders",
    "ratings_reviews": "reviews",
    "ads_report": "ads",
    "live_session_report": "live_sessions",
    "new_products": "product_launches",
    "discount_campaign": "discounts",       # dulu → marketing_discount_campaigns (SALAH)
    "sample_shipping": "samples",           # dulu → marketing_sample_shipments (SALAH)
    "returns_refunds": "returns",
    "complaints": "complaints",
    "account_health": "account_health",
    "content_calendar": "content_calendar",
    "sales_data": "sales_daily",
}


# ══════════════════════════════════════════════════════════════════════════════
# SESI #37 — 22 JENIS IMPOR DIRINGKAS MENJADI 6 KELOMPOK
# ══════════════════════════════════════════════════════════════════════════════
# Masalahnya diukur, bukan diduga: `GET /source-types` mengembalikan **22** jenis
# yang tersebar di **8** label grup (Penjualan, Iklan, After-Sales, Konten, KPI
# Platform, Katalog, Kreator, Live). Staf yang memegang satu berkas ekspor tidak
# bisa tahu jenis mana yang benar hanya dari namanya — dan salah pilih jenis
# membuat data masuk tabel yang salah TANPA satu pun galat.
#
# Keputusan pemilik: pilih **KELOMPOK** dulu (6 pintu, bisa dihafal), lalu jenis
# persisnya ditentukan **deteksi otomatis** dari isi berkas (`POST /detect`).
#
# ATURAN YANG DIPEGANG DI SINI:
#  1. TIDAK ADA jenis yang dihapus. `POST /upload` tetap menerima seluruh 22 kunci
#     (plus `LEGACY_ALIASES`) supaya impor yang sudah jalan tidak putus.
#  2. Jenis yang benar-benar TUMPANG TINDIH ditandai `deprecated=True` +
#     `deprecated_by` (penggantinya) dan disembunyikan dari daftar pilihan —
#     BUKAN dimatikan.
#  3. Jenis yang HANYA TERLIHAT tumpang tindih (koleksi tujuannya sama tetapi
#     berkas & maksudnya berbeda) TIDAK ditandai apa pun. Alasannya ditulis di
#     `NOT_DEPRECATED_WHY` supaya sesi berikutnya tidak "merapikan" ulang dan
#     mematikan jalur impor yang sah.
SOURCE_GROUPS: Tuple[Tuple[str, str, str, Tuple[str, ...]], ...] = (
    ("pesanan_penjualan", "Pesanan & Penjualan",
     "Ekspor pesanan dari Seller Center, status pengiriman/pembatalan, dan rekap "
     "omzet harian.",
     ("marketplace_orders", "orders", "marketplace_fulfillment", "sales_daily")),
    ("iklan", "Iklan",
     "Biaya & performa iklan — laporan CPC asli dari Shopee, laporan GMV Max TikTok, "
     "maupun rekap iklan yang diketik sendiri.",
     ("shopee_ads_cpc", "tiktok_gmv_max", "ads")),
    ("after_sales", "Retur, Komplain & Ulasan",
     "Apa yang terjadi SETELAH barang sampai: retur/refund, komplain pelanggan, "
     "dan rating/ulasan.",
     ("returns", "complaints", "reviews")),
    ("konten", "Konten",
     "Konten yang direncanakan dan yang sudah terbit, beserta KPI-nya "
     "(views, engagement, GMV).",
     ("content_performance", "shopee_content_kpi", "content_calendar")),
    ("live", "Live Selling",
     "Sesi live, rincian produk yang dijual di sesi itu, dan jadwal shift host.",
     ("live_sessions", "live_session_products", "livehost_shifts")),
    ("katalog_lain", "Katalog & Lainnya",
     "Master & data pendukung: item katalog, diskon, peluncuran produk, sample "
     "kreator, master kreator, kesehatan akun, statistik toko.",
     ("catalog_items", "discounts", "product_launches", "samples", "kol_creators",
      "account_health", "shopee_shop_kpi")),
)

GROUP_LABEL: Dict[str, str] = {g[0]: g[1] for g in SOURCE_GROUPS}
GROUP_OF: Dict[str, str] = {
    key: g[0] for g in SOURCE_GROUPS for key in g[3]
}

# Tumpang tindih NYATA: dua jenis menulis ke koleksi yang sama DAN melahirkan
# dokumen baru dari berkas yang setara. Yang lebih lengkap menang.
DEPRECATED_SOURCE_TYPES: Dict[str, Dict[str, str]] = {
    "orders": {
        "by": "marketplace_orders",
        "reason": (
            "Keduanya melahirkan pesanan baru di `marketing_orders`. "
            "'Pesanan Marketplace' membaca ekspor Seller Center APA ADANYA dan "
            "membawa dua penjaga yang tidak dimiliki jenis ini: sidik platform "
            "dan sidik gudang toko (`platform_guard` + `shop_guard`). Tanpa dua "
            "penjaga itu, satu berkas yang salah pilih toko memindahkan SELURUH "
            "omzetnya ke toko lain tanpa peringatan — dan itu pernah terjadi "
            "(559 pesanan, 2026-08-12). Jenis ini tetap DITERIMA oleh /upload "
            "untuk template ketikan manual, hanya tidak lagi ditawarkan."),
    },
}

# Jenis yang SENGAJA TIDAK ditandai tumpang tindih, beserta sebabnya.
NOT_DEPRECATED_WHY: Dict[str, str] = {
    "ads": "berkas rekap iklan yang diketik staf; `shopee_ads_cpc` butuh berkas "
           "CPC asli Shopee (perlu prenorm). Dua bentuk berkas berbeda.",
    "tiktok_gmv_max": "ekspor GMV Max TikTok tanpa tanggal belanja (periode wajib, baris "
                      "biaya 0 dibuang); `ads` = rekap ketikan per tanggal.",
    "content_calendar": "RENCANA konten (belum terbit, belum ada KPI); "
                        "`content_performance` butuh link terbit.",
    "shopee_shop_kpi": "statistik TOKO; `shopee_content_kpi` statistik KONTEN. "
                       "Koleksi tujuannya sama, isi berkasnya berbeda.",
    "marketplace_fulfillment": "hanya MEMPERBARUI pesanan yang sudah ada "
                               "(`update_only`), tidak pernah melahirkan pesanan.",
    "sales_daily": "rekap harian per jenis omzet — bukan daftar pesanan.",
}


def source_group_catalog(include_deprecated: bool = False) -> List[dict]:
    """6 kelompok + jenis di dalamnya. Dipakai wizard untuk langkah pertama."""
    cat = {t["key"]: t for t in source_type_catalog()}
    out = []
    for key, label, describe, members in SOURCE_GROUPS:
        types = []
        for m in members:
            t = cat.get(m)
            if not t:
                continue
            if t["deprecated"] and not include_deprecated:
                continue
            types.append({
                "key": t["key"], "label": t["label"], "describe": t["describe"],
                "collection": t["collection"], "prenorm": t["prenorm"],
                "export_hint": t["export_hint"], "update_only": t["update_only"],
                "account_scope": t["account_scope"], "context": t["context"],
                "deprecated": t["deprecated"], "deprecated_by": t["deprecated_by"],
            })
        out.append({
            "key": key, "label": label, "describe": describe,
            "types": types,
            "type_count": len(types),
            "hidden_count": sum(1 for m in members
                                if (cat.get(m) or {}).get("deprecated")),
        })
    orphans = [k for k in SOURCE_TYPES if k not in GROUP_OF]
    if orphans:
        # Jenis baru yang lupa dimasukkan kelompok TIDAK disembunyikan diam-diam:
        # ia muncul di kelompok "Belum dikelompokkan" supaya terlihat & diperbaiki.
        out.append({
            "key": "belum_dikelompokkan", "label": "Belum dikelompokkan",
            "describe": "Jenis impor yang belum dimasukkan ke salah satu kelompok. "
                        "Laporkan ini — bukan disembunyikan.",
            "types": [{"key": k, "label": cat[k]["label"],
                       "describe": cat[k]["describe"],
                       "collection": cat[k]["collection"], "prenorm": cat[k]["prenorm"],
                       "export_hint": cat[k]["export_hint"],
                       "update_only": cat[k]["update_only"],
                       "account_scope": cat[k]["account_scope"],
                       "context": cat[k]["context"],
                       "deprecated": False, "deprecated_by": ""} for k in orphans],
            "type_count": len(orphans), "hidden_count": 0,
        })
    return out


def get_source_type(key: str) -> SourceType:
    k = (key or "").strip()
    if k in SOURCE_TYPES:
        return SOURCE_TYPES[k]
    if k in LEGACY_ALIASES:
        return SOURCE_TYPES[LEGACY_ALIASES[k]]
    raise KeyError(
        f"Jenis data impor '{key}' tidak dikenali. Pilih salah satu: "
        + ", ".join(sorted(SOURCE_TYPES))
    )


def source_type_catalog() -> List[dict]:
    """Bentuk siap-kirim ke layar: dipakai untuk kartu 'ini import data apa'."""
    out = []
    for t in SOURCE_TYPES.values():
        dep = DEPRECATED_SOURCE_TYPES.get(t.key) or {}
        gkey = GROUP_OF.get(t.key, "belum_dikelompokkan")
        out.append({
            "key": t.key,
            "label": t.label,
            # SESI #37 — `group` sekarang label KELOMPOK KONSOLIDASI (6 pintu),
            # bukan 8 label lama. `group_legacy` disimpan supaya laporan/audit
            # lama masih bisa memetakan datanya.
            "group": GROUP_LABEL.get(gkey, "Belum dikelompokkan"),
            "group_key": gkey,
            "group_legacy": t.group,
            "deprecated": bool(dep),
            "deprecated_by": dep.get("by", ""),
            "deprecated_reason": dep.get("reason", ""),
            "not_deprecated_why": NOT_DEPRECATED_WHY.get(t.key, ""),
            "describe": t.describe,
            "collection": t.collection,
            "module_hint": t.module_hint,
            "account_scope": t.account_scope,
            "context": list(t.context),
            # F7.2 — layar perlu tahu berkas ini dinormalkan dulu (baris pertama
            # BUKAN header) dan dari mana berkasnya diunduh di Seller Center.
            "prenorm": t.prenorm,
            "export_hint": t.export_hint,
            # 2026-11-09 — layar menampilkan isian periode laporan (wajib) untuk jenis ini
            "period_input": t.key in PERIOD_INPUT_TYPES,
            # F3 — layar WAJIB memberi tahu dua hal ini sebelum staf menyimpan:
            # (1) jenis ini hanya memperbarui pesanan yang sudah ada;
            # (2) pemetaan kolomnya belum diverifikasi dengan berkas asli.
            "update_only": t.update_only,
            "mapping_unverified": t.mapping_unverified,
            "required_columns": [f.label for f in t.required_fields],
            "total_columns": len(t.input_fields),
            # F1 — layar perlu tahu bahwa banyak baris menjadi SATU dokumen
            "is_grouped": t.is_grouped,
            "group_by": list(t.group_by),
            "item_fields": list(t.item_fields),
            "fields": [
                {
                    "name": f.name, "label": f.label, "kind": f.kind,
                    "required": f.required, "choices": list(f.choices),
                    "example": f.example, "note": f.note,
                    "synonyms": list(f.synonyms),
                    "value_map": [list(p) for p in f.value_map],
                    "is_item_field": f.name in t.item_fields,
                }
                for f in t.input_fields
            ],
        })
    out.sort(key=lambda x: (x["group"], x["label"]))
    return out

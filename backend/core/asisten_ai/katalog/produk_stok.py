"""Katalog data — master produk, posisi stok, dan mutasi stok (Portal Produksi/RnD/Gudang).

Sumber & pembaca resmi:
  * varian `rahaza_model_variants` (penulis `routes/rahaza_variants.py`, `utils/variant_ssot.py`; pembaca memakai
    `{"active": True}`) + model `rahaza_models` (`routes/rahaza_production.py`; harga jual `retail_price`, HPP efektif
    `hpp` = `core.product_master.resolve_hpp`: BOM → R&D → manual).
  * stok `rahaza_material_stock` = stok kanonik SEMUA lokasi & jenis barang (penulis tunggal `core.stock_service`);
    jumlah dibaca seperti `stock_schema.read_qty` (qty → total_qty → quantity → available_quantity). Master barang
    `rahaza_materials` (bahan, aksesoris, kemasan, barang jadi `type=fg`).
  * mutasi `rahaza_stock_ledger` = satu baris per perubahan stok (`core.stock_service._log`). Operasi reservasi
    (`reserve*`, `release*`) dan ganti satuan (`uom_rebase`) bukan perpindahan fisik → dibuang.
Persediaan bernilai milik CV Dewi Aditya (mode CV "tetap" DA).
"""
from __future__ import annotations

from core.asisten_ai.katalog_data import Akses, Dataset, Gabung, Kolom, e_angka, e_atau, e_peta

_PORTAL_INTERNAL = ("management", "production", "rnd", "warehouse", "accessories", "procurement", "finance",
                    "sales", "toko", "maklon", "cutting")
AKSES_PRODUK = Akses(portal=_PORTAL_INTERNAL, modul=("prod_master_product",))
AKSES_STOK = Akses(portal=_PORTAL_INTERNAL, modul=("wh_stock", "wh_master"))
AKSES_MUTASI = Akses(portal=("warehouse", "accessories", "procurement", "production", "finance", "management"),
                     peran=("manager_produksi",), modul=("wh_stock",))
CV_DA = {"mode": "tetap", "milik": "DA"}
JENIS_BARANG = ("yarn", "fabric", "kain", "benang", "interlining", "accessory", "packaging", "fg", "other")
# Kelompok barang = `core.material_fields` (bahan / aksesoris / fg).
_PETA_KELOMPOK = {"bahan": ["yarn", "fabric", "kain", "benang", "interlining"],
                  "aksesoris": ["accessory", "packaging"], "barang_jadi": ["fg"]}

_M = Gabung("_m", "rahaza_materials", "material_id", "id",
            ambil=("code", "name", "type", "category_name", "unit", "active", "is_cut_panel"))


def _barang() -> tuple:
    return (
        Kolom("kode_barang", "Kode barang", "teks", path="_m.code", cadangan=("material_code",)),
        Kolom("nama_barang", "Nama barang", "teks", path="_m.name", cadangan=("material_name",)),
        Kolom("jenis", "Jenis barang", "teks", path="_m.type", cadangan=("material_type",), nilai=JENIS_BARANG),
        Kolom("kelompok_barang", "Kelompok barang", "teks", gabung=("_m",),
              ekspr=e_peta({"$ifNull": ["$_m.type", "$material_type"]}, _PETA_KELOMPOK, "lain"),
              nilai=("bahan", "aksesoris", "barang_jadi", "lain")),
        Kolom("kategori", "Kategori", "teks", path="_m.category_name", cadangan=("category_name",)),
        Kolom("satuan", "Satuan", "teks", path="_m.unit", cadangan=("unit",)),
        Kolom("potongan_kain", "Potongan kain (cut panel)", "ya_tidak", path="_m.is_cut_panel", bawaan=False,
              keterangan="true = potongan hasil cutting yang dicatat sebagai bahan kain."),
    )


DATASET = (
    Dataset(
        id="produk_varian",
        label="Master produk (varian SKU)",
        keterangan="Varian produk aktif (model × warna × ukuran) dengan kategori, harga jual, dan HPP model.",
        koleksi="rahaza_model_variants", domain="produk", akses=AKSES_PRODUK,
        saringan_dasar={"active": True},
        gabung=(Gabung("_model", "rahaza_models", "model_id", "id",
                       ambil=("category_name", "retail_price", "hpp", "hpp_source", "active", "status")),),
        kolom=(
            Kolom("sku", "SKU", "teks", path="sku"),
            Kolom("kode_model", "Kode model", "teks", path="model_code"),
            Kolom("nama_model", "Nama model", "teks", path="model_name"),
            Kolom("kategori", "Kategori", "teks", path="_model.category_name"),
            Kolom("warna", "Warna", "teks", path="color_name"),
            Kolom("kode_warna", "Kode warna", "teks", path="color_code", bawaan=False),
            Kolom("ukuran", "Ukuran", "teks", path="size_code"),
            Kolom("opsi", "Opsi varian", "teks", path="option_name", bawaan=False),
            Kolom("barcode", "Barcode", "teks", path="barcode", bawaan=False),
            Kolom("status_produk", "Status produk", "teks", path="product_status",
                  nilai=("new", "best_seller", "slow", "dead", "stop")),
            Kolom("harga_jual", "Harga jual (model)", "uang", path="_model.retail_price"),
            Kolom("hpp", "HPP model", "uang", path="_model.hpp",
                  keterangan="HPP efektif model: BOM → R&D → manual."),
            Kolom("sumber_hpp", "Sumber HPP", "teks", path="_model.hpp_source", bawaan=False,
                  nilai=("bom", "rnd", "manual", "none")),
            Kolom("model_aktif", "Model aktif", "ya_tidak", gabung=("_model",), bawaan=False,
                  ekspr={"$and": [{"$ne": ["$_model.active", False]}, {"$ne": ["$_model.status", "inactive"]}]}),
        ),
        catatan=("Harga jual dan HPP berlaku untuk seluruh varian satu model (bukan per ukuran). Status produk "
                 "'stop' tidak menonaktifkan varian.",),
    ),
    Dataset(
        id="posisi_stok",
        label="Posisi stok per lokasi",
        keterangan=("Stok saat ini per barang per lokasi gudang (bahan, aksesoris, kemasan, barang jadi): jumlah "
                    "fisik, dipesan, tersedia."),
        koleksi="rahaza_material_stock", domain="stok", akses=AKSES_STOK, cv=CV_DA, gabung=(_M,),
        kolom=(
            *_barang(),
            Kolom("lokasi", "Kode lokasi", "teks", path="location_code", cadangan=("location.code",)),
            Kolom("lokasi_id", "Id lokasi", "teks", path="location_id", cadangan=("location.id",), bawaan=False),
            Kolom("qty", "Stok fisik", "angka", ekspr=e_angka(e_atau("qty", "total_qty", "quantity",
                                                                      "available_quantity"))),
            Kolom("dipesan", "Dipesan (reservasi)", "angka", path="reserved_quantity", cadangan=("reserved",)),
            Kolom("tersedia", "Tersedia", "angka", path="available_quantity", cadangan=("qty",)),
            Kolom("kepemilikan", "Kepemilikan", "teks", path="ownership", bawaan=False),
            Kolom("kategori_persediaan", "Kategori persediaan", "teks", path="inventory_category", bawaan=False),
            Kolom("barang_aktif", "Barang aktif", "ya_tidak", path="_m.active", bawaan=False),
        ),
        urut_bawaan=(("kode_barang", "naik"),),
        catatan=("Stok total satu barang = jumlah qty semua lokasinya (kelompok kode_barang, agregasi jumlah qty). "
                 "Stok bisa negatif bila pengeluaran tercatat lebih dulu dari penerimaan.",
                 "Persediaan bernilai milik CV Dewi Aditya; titipan bahan klien maklon ditandai kolom kepemilikan."),
    ),
    Dataset(
        id="mutasi_stok",
        label="Mutasi stok",
        keterangan="Riwayat perubahan stok fisik: penerimaan, pengeluaran, dan penyesuaian/opname per barang.",
        koleksi="rahaza_stock_ledger", domain="stok", akses=AKSES_MUTASI, kolom_tanggal="tanggal", cv=CV_DA,
        saringan_dasar={"op": {"$in": ["add", "issue", "issue_row", "adjust"]}}, gabung=(_M,),
        kolom=(
            Kolom("tanggal", "Tanggal", "tanggal", path="created_at", simpan="datetime_utc"),
            Kolom("waktu", "Waktu (WIB)", "waktu", path="created_at", simpan="datetime_utc", bawaan=False),
            *_barang(),
            Kolom("lokasi_id", "Id lokasi", "teks", path="location_id", bawaan=False),
            Kolom("jenis_mutasi", "Jenis mutasi", "teks", path="op", nilai=("add", "issue", "issue_row", "adjust"),
                  keterangan="add = masuk, issue/issue_row = keluar, adjust = penyesuaian/opname."),
            Kolom("perubahan", "Perubahan qty", "angka", path="delta", keterangan="+ masuk, − keluar."),
            Kolom("masuk", "Qty masuk", "angka", ekspr={"$max": [{"$ifNull": [e_angka("$delta"), 0]}, 0]}),
            Kolom("keluar", "Qty keluar", "angka",
                  ekspr={"$max": [{"$multiply": [{"$ifNull": [e_angka("$delta"), 0]}, -1]}, 0]}),
            Kolom("qty_setelah", "Stok setelah mutasi", "angka", path="qty_after", bawaan=False),
            Kolom("sumber", "Sumber mutasi", "teks", path="ref.source", cadangan=("ref.type",),
                  keterangan="mis. material_receive, material_issue, fulfillment, opening_stock, undo_adjustment."),
        ),
        catatan=("Satu baris = satu perubahan stok fisik di satu lokasi. Reservasi (pesanan dipesan) tidak termasuk. "
                 "Pembatalan penyesuaian tercatat sebagai baris penyesuaian baru — jangan dibuang saat menjumlah.",),
    ),
)

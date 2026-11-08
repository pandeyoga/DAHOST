"""Katalog data — PO maklon CV Sukma (Portal Maklon).

Sumber (penulis diverifikasi): `dewi_maklon_pos` = cermin keuangan PO maklon, ditulis
`routes/production_maklon_bridge.sync_po_to_maklon_finance` dari `production_pos` (business_type maklon; id sama).
Baris `items[]`: artikel, SKU, warna, ukuran, qty, qty diproduksi/dikirim, harga jasa per pcs (`selling_price_per_pcs`)
dan subtotal = harga jasa × qty. Status cermin dipetakan dari status PO produksi (`PO_STATUS_TO_MAKLON`).
Upah CMT per pcs, biaya CMT, dan margin sengaja tidak dimasukkan. Data ini milik CV Sukma (mode CV "tetap" SMU).
"""
from __future__ import annotations

from core.asisten_ai.katalog_data import Akses, Dataset, Kolom

AKSES_MAKLON = Akses(portal=("maklon", "finance"), peran=("manager_produksi",), modul=("mak_po", "prod_po"))
_I = "items."

DATASET = (
    Dataset(
        id="po_maklon",
        label="PO maklon CV Sukma (per baris)",
        keterangan=("PO jasa jahit dari klien maklon per baris produk: klien, tanggal, tenggat, status, artikel/SKU, "
                    "qty pesanan, diproduksi, dikirim, harga jasa, dan nilai baris."),
        koleksi="dewi_maklon_pos", domain="maklon", akses=AKSES_MAKLON, kolom_tanggal="tanggal_po",
        cv={"mode": "tetap", "milik": "SMU"}, unwind="items", unwind_kosong=True,
        kolom=(
            Kolom("no_po", "Nomor PO", "teks", path="po_number"),
            Kolom("tanggal_po", "Tanggal PO", "tanggal", path="po_date", simpan="campur"),
            Kolom("tenggat", "Tenggat", "tanggal", path="deadline", simpan="campur"),
            Kolom("klien", "Klien", "teks", path="client_name", samaran="pelanggan"),
            Kolom("status", "Status PO", "teks", path="status",
                  nilai=("draft", "confirmed", "in_production", "partial_delivered", "delivered", "completed",
                         "invoiced", "cancelled")),
            Kolom("status_bayar", "Status pembayaran", "teks", path="payment_status", bawaan=False),
            Kolom("artikel", "Artikel", "teks", path=_I + "artikel"),
            Kolom("sku", "SKU", "teks", path=_I + "sku_code"),
            Kolom("warna", "Warna", "teks", path=_I + "color"),
            Kolom("ukuran", "Ukuran", "teks", path=_I + "size"),
            Kolom("qty", "Qty pesanan", "angka", path=_I + "qty"),
            Kolom("qty_diproduksi", "Qty diproduksi", "angka", path=_I + "qty_produced"),
            Kolom("qty_dikirim", "Qty dikirim ke klien", "angka", path=_I + "qty_dispatched"),
            Kolom("harga_jasa", "Harga jasa per pcs", "uang", path=_I + "selling_price_per_pcs"),
            Kolom("nilai_baris", "Nilai baris", "uang", path=_I + "subtotal",
                  keterangan="Harga jasa × qty pesanan."),
        ),
        catatan=("Nilai PO = jumlah nilai_baris; jumlah PO = hitung_unik no_po. PO aktif = confirmed, in_production, "
                 "partial_delivered. Angka qty diproduksi/dikirim diperbarui sistem dari alur produksi.",),
    ),
)

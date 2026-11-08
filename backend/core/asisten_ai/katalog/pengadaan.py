"""Katalog data — PO pembelian ke pemasok dan faktur pemasok (Portal Pengadaan / Keuangan).

Sumber (penulis diverifikasi):
  * `rahaza_purchase_orders` — `routes/rahaza_po.py` (buat/ubah/setujui/terima) + `routes/dewi_procurement.py`
    (PR → PO). `po_date` string TTTT-BB-HH (WIB). Baris barang tertanam di `items[]` (qty_ordered/qty_received
    dalam satuan dasar, unit_cost per satuan dasar, subtotal). Pembelian = buku CV Dewi Aditya.
  * `rahaza_ap_invoices` — `routes/rahaza_finance.py` (`create_ap`, status `AP_STATUS`) + faktur dari penerimaan
    barang `routes/rahaza_ap_from_gr.py`. CV = field `entity` (daftar resmi memakai `entity_match`).
NPWP pemasok, rekening bank pemasok, dan alamat sengaja tidak dimasukkan.
"""
from __future__ import annotations

from core.asisten_ai.katalog_data import Akses, Dataset, Kolom

AKSES_PO = Akses(portal=("procurement", "warehouse"), peran=("manager_produksi", "manager_keuangan"),
                 modul=("proc_po",))
AKSES_FAKTUR = Akses(portal=("finance", "procurement"), modul=("proc_match", "fin_ap"))
STATUS_PO = ("draft", "pending_approval", "approved", "partially_received", "fully_received", "rejected", "cancelled")
_I = "items."

DATASET = (
    Dataset(
        id="po_pembelian",
        label="PO pembelian ke pemasok (per baris barang)",
        keterangan=("Purchase order ke pemasok per baris barang: nomor PO, tanggal, pemasok, status, barang, qty "
                    "dipesan & diterima, harga satuan, subtotal."),
        koleksi="rahaza_purchase_orders", domain="pengadaan", akses=AKSES_PO, kolom_tanggal="tanggal_po",
        cv={"mode": "tetap", "milik": "DA"}, unwind="items", unwind_kosong=True,
        kolom=(
            Kolom("no_po", "Nomor PO", "teks", path="po_number"),
            Kolom("tanggal_po", "Tanggal PO", "tanggal", path="po_date", simpan="teks"),
            Kolom("perkiraan_tiba", "Perkiraan tiba", "tanggal", path="expected_delivery_date", simpan="teks",
                  bawaan=False),
            Kolom("pemasok", "Pemasok", "teks", path="vendor_name", samaran="vendor"),
            Kolom("status", "Status PO", "teks", path="status", nilai=STATUS_PO),
            Kolom("barang", "Barang", "teks", path=_I + "description"),
            Kolom("barang_id", "Id barang (master)", "teks", path=_I + "material_id", bawaan=False),
            Kolom("satuan", "Satuan dasar", "teks", path=_I + "base_uom", cadangan=(_I + "uom",)),
            Kolom("qty_pesan", "Qty dipesan", "angka", path=_I + "qty_ordered"),
            Kolom("qty_terima", "Qty diterima", "angka", path=_I + "qty_received"),
            Kolom("harga_satuan", "Harga satuan", "uang", path=_I + "unit_cost"),
            Kolom("subtotal", "Subtotal baris", "uang", path=_I + "subtotal"),
            Kolom("termin", "Termin bayar", "teks", path="payment_terms", bawaan=False),
        ),
        catatan=("Satu baris = satu barang dalam PO; jumlah PO = hitung_unik no_po. Nilai komitmen pembelian = "
                 "jumlah subtotal PO berstatus selain draft, rejected, cancelled. PO berjalan = approved, "
                 "partially_received.",),
    ),
    Dataset(
        id="faktur_pemasok",
        label="Faktur pemasok (hutang)",
        keterangan="Faktur dari pemasok: tanggal, jatuh tempo, pemasok, subtotal, pajak, total, terbayar, sisa hutang.",
        koleksi="rahaza_ap_invoices", domain="pengadaan", akses=AKSES_FAKTUR, kolom_tanggal="tanggal_faktur",
        saringan_dasar={"status": {"$ne": "cancelled"}}, cv={"mode": "field", "field": "entity"},
        kolom=(
            Kolom("no_faktur", "Nomor faktur", "teks", path="invoice_number"),
            Kolom("no_faktur_pemasok", "Nomor faktur dari pemasok", "teks", path="supplier_faktur_number",
                  bawaan=False),
            Kolom("tanggal_faktur", "Tanggal faktur", "tanggal", path="issue_date", simpan="teks"),
            Kolom("jatuh_tempo", "Jatuh tempo", "tanggal", path="due_date", simpan="teks"),
            Kolom("pemasok", "Pemasok", "teks", path="vendor_name", samaran="vendor"),
            Kolom("kode_pemasok", "Kode pemasok", "teks", path="vendor_code", bawaan=False),
            Kolom("status", "Status faktur", "teks", path="status",
                  nilai=("draft", "sent", "partial_paid", "paid", "overdue")),
            Kolom("subtotal", "Subtotal", "uang", path="subtotal"),
            Kolom("pajak", "PPN masukan", "uang", path="tax_amount"),
            Kolom("total", "Total faktur", "uang", path="total"),
            Kolom("terbayar", "Sudah dibayar", "uang", path="paid_amount"),
            Kolom("sisa", "Sisa hutang", "uang", path="balance"),
            Kolom("akun_beban", "Akun debit", "teks", path="gl_debit_code", bawaan=False),
            Kolom("cv", "CV", "teks", ekspr={"$ifNull": ["$entity", "DA"]}, bawaan=False, nilai=("DA", "SMU")),
        ),
        catatan=("Faktur batal tidak ikut. Draft = belum diposting ke buku besar. Hutang berjalan = jumlah sisa "
                 "faktur berstatus sent, partial_paid, overdue.",),
    ),
)

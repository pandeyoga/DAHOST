"""Katalog data — PO produksi, kiriman ke CMT, penerimaan & QC dari CMT, tagihan CMT (Portal Produksi/Maklon).

Sumber (penulis diverifikasi):
  * PO `production_pos` + baris `po_items` — `routes/production_pos.py` (`create_po_internal`, satu-satunya pembuat
    PO internal & maklon). `po_date`/`deadline` = `parse_date` (tanggal tanpa jam = tengah malam UTC).
  * kiriman `vendor_shipments` + `vendor_shipment_items` — `routes/vendor_shipment.py` (modul prod_vendor_shipment).
  * penerimaan `cmt_receipts` + `cmt_receipt_lines` — `routes/dewi_cmt_packing.py`, `routes/buyer_shipment.py`;
    status baku `core.cmt_receipt_status` (on_qc / completed_qc / cancelled, status lama dipetakan).
  * tagihan `dewi_cmt_payments` — `routes/production_maklon_bridge.mature_ap_from_cmt_receipt`; nilai =
    `production_cmt_billing._amount` (net_amount → total_amount → subtotal); sisa = outstanding_amount bila ada,
    kalau tidak nilai − terbayar. Tagihan batal (cancelled/void/voided) dibuang seperti pembaca resmi.
CV: maklon (business_type == "maklon") = CV Sukma, selain itu = CV Dewi Aditya (`core.entities.is_maklon_po`).
Tarif/upah CMT per pcs dan harga jual snapshot sengaja tidak dimasukkan.
"""
from __future__ import annotations

from core.asisten_ai.katalog_data import Akses, Dataset, Gabung, Kolom, e_angka, e_angka_atau, e_peta
from core.cmt_receipt_status import LEGACY_STATUS, STATUS_LABEL

_PERAN_PROD = ("manager_produksi", "manager", "ppic")
AKSES_PO = Akses(portal=("production", "maklon"), peran=_PERAN_PROD, modul=("prod_po",))
AKSES_KIRIM = Akses(portal=("production", "maklon"), peran=_PERAN_PROD, modul=("prod_vendor_shipment",))
AKSES_TERIMA = Akses(portal=("production", "maklon", "finance", "warehouse"), peran=_PERAN_PROD,
                     modul=("prod_cmt_receive",))
AKSES_TAGIHAN = Akses(portal=("production", "maklon", "finance"), peran=_PERAN_PROD, modul=("prod_cmt_billing",))
CV_JENIS = {"mode": "saringan", "DA": {"business_type": {"$ne": "maklon"}}, "SMU": {"business_type": "maklon"}}
EKSPR_JENIS = {"$cond": [{"$eq": ["$business_type", "maklon"]}, "maklon", "internal"]}
STATUS_PO = ("Draft", "Confirmed", "Distributed", "In Production", "Production Complete", "Variance Review",
             "Return Review", "Ready to Close", "Closed", "Completed", "Closed Short")
_JENIS = Kolom("jenis", "Jenis PO", "teks", ekspr=EKSPR_JENIS, nilai=("internal", "maklon"),
               keterangan="maklon = pesanan klien CV Sukma; internal = produk sendiri CV Dewi Aditya.")


def _baris(nama: str, dari: str, asing: str, *ambil: str) -> Gabung:
    return Gabung(nama, dari, "id", asing, ambil=ambil, banyak=True)


# Status penerimaan baku → label layar (`core.cmt_receipt_status`).
_PETA_TERIMA = {STATUS_LABEL[baku]: [m for m, b in LEGACY_STATUS.items() if b == baku]
                for baku in ("completed_qc", "cancelled")}

DATASET = (
    Dataset(
        id="po_produksi",
        label="PO produksi (per baris produk)",
        keterangan=("PO produksi internal dan maklon per baris produk: nomor PO, tanggal, tenggat, status, vendor CMT, "
                    "produk/SKU/ukuran/warna, dan qty pesanan."),
        koleksi="production_pos", domain="produksi", akses=AKSES_PO, kolom_tanggal="tanggal_po", cv=CV_JENIS,
        gabung=(_baris("_baris", "po_items", "po_id", "product_name", "sku", "size", "color", "qty", "qty_ordered",
                       "serial_number"),),
        unwind="_baris", unwind_kosong=True,
        kolom=(
            Kolom("no_po", "Nomor PO", "teks", path="po_number"),
            Kolom("tanggal_po", "Tanggal PO", "tanggal", path="po_date", simpan="campur"),
            Kolom("tenggat", "Tenggat produksi", "tanggal", path="deadline", simpan="campur"),
            Kolom("tenggat_kirim", "Tenggat kirim", "tanggal", path="delivery_deadline", simpan="campur",
                  bawaan=False),
            Kolom("status", "Status PO", "teks", path="status", nilai=STATUS_PO),
            _JENIS,
            Kolom("vendor", "Vendor CMT", "teks", path="vendor_name", samaran="vendor"),
            Kolom("pelanggan", "Pelanggan / klien", "teks", path="customer_name", samaran="pelanggan", bawaan=False),
            Kolom("produk", "Produk", "teks", path="_baris.product_name"),
            Kolom("sku", "SKU", "teks", path="_baris.sku"),
            Kolom("ukuran", "Ukuran", "teks", path="_baris.size"),
            Kolom("warna", "Warna", "teks", path="_baris.color"),
            Kolom("qty", "Qty pesanan", "angka", path="_baris.qty_ordered", cadangan=("_baris.qty",)),
            Kolom("no_seri", "Nomor seri", "teks", path="_baris.serial_number", bawaan=False),
            Kolom("ditutup_pada", "Tanggal ditutup", "tanggal", path="closed_at", simpan="datetime_utc",
                  bawaan=False),
            Kolom("qty_kurang_saat_tutup", "Qty kurang saat ditutup", "angka", path="qty_short", bawaan=False),
        ),
        catatan=("Satu baris = satu baris produk dalam PO (PO tanpa baris muncul sekali dengan kolom produk kosong). "
                 "Jumlah PO = hitung_unik no_po. Status selesai: Closed, Completed, Closed Short; Draft belum berjalan.",),
    ),
    Dataset(
        id="kiriman_cmt",
        label="Kiriman ke CMT (per baris)",
        keterangan="Kiriman bahan/potongan ke vendor CMT untuk dijahit, per baris produk: tanggal, vendor, PO, qty.",
        koleksi="vendor_shipments", domain="produksi", akses=AKSES_KIRIM, kolom_tanggal="tanggal_kirim",
        cv=CV_JENIS, unwind="_baris", unwind_kosong=True,
        gabung=(_baris("_baris", "vendor_shipment_items", "shipment_id", "product_name", "sku", "size", "color",
                       "qty_sent", "ordered_qty", "po_number"),),
        kolom=(
            Kolom("no_kiriman", "Nomor kiriman", "teks", path="shipment_number"),
            Kolom("tanggal_kirim", "Tanggal kirim", "tanggal", path="shipment_date", simpan="campur"),
            Kolom("vendor", "Vendor CMT", "teks", path="vendor_name", samaran="vendor"),
            Kolom("no_po", "Nomor PO", "teks", path="po_number", cadangan=("_baris.po_number",)),
            Kolom("jenis_kiriman", "Jenis kiriman", "teks", path="shipment_type",
                  nilai=("NORMAL", "ADDITIONAL", "REPLACEMENT", "REWORK")),
            Kolom("status", "Status kiriman", "teks", path="status", nilai=("Sent", "Received")),
            Kolom("status_periksa", "Status pemeriksaan vendor", "teks", path="inspection_status", bawaan=False),
            _JENIS,
            Kolom("produk", "Produk", "teks", path="_baris.product_name"),
            Kolom("sku", "SKU", "teks", path="_baris.sku"),
            Kolom("ukuran", "Ukuran", "teks", path="_baris.size"),
            Kolom("warna", "Warna", "teks", path="_baris.color"),
            Kolom("qty_kirim", "Qty dikirim", "angka", path="_baris.qty_sent"),
            Kolom("qty_pesanan", "Qty pesanan PO", "angka", path="_baris.ordered_qty", bawaan=False),
        ),
        catatan=("Kiriman tambahan/pengganti/perbaikan ikut terhitung (jenis_kiriman ADDITIONAL/REPLACEMENT/REWORK); "
                 "saring jenis_kiriman = NORMAL untuk kiriman utama saja.",),
    ),
    Dataset(
        id="terima_qc_cmt",
        label="Penerimaan & QC dari CMT (per baris)",
        keterangan=("Barang jadi yang diterima dari vendor CMT per baris SKU: qty diharapkan, lolos QC, reject, dan "
                    "kurang kirim, dengan status QC."),
        koleksi="cmt_receipts", domain="produksi", akses=AKSES_TERIMA, kolom_tanggal="tanggal_terima",
        cv=CV_JENIS, unwind="_baris", unwind_kosong=True,
        gabung=(_baris("_baris", "cmt_receipt_lines", "receipt_id", "sku_code", "product_name", "color", "size",
                       "qty_expected", "qty_actual", "reject_qty", "qty_short", "qty_shipped_by_cmt"),),
        kolom=(
            Kolom("no_terima", "Nomor penerimaan", "teks", path="receipt_code"),
            Kolom("tanggal_terima", "Tanggal terima", "tanggal", path="receipt_date", simpan="campur"),
            Kolom("vendor", "Vendor CMT", "teks", path="cmt_name", samaran="vendor"),
            Kolom("no_po", "Nomor PO", "teks", path="po_number"),
            Kolom("status", "Status QC", "teks", ekspr=e_peta("$status", _PETA_TERIMA, STATUS_LABEL["on_qc"]),
                  nilai=tuple(STATUS_LABEL.values())),
            _JENIS,
            Kolom("sku", "SKU", "teks", path="_baris.sku_code"),
            Kolom("produk", "Produk", "teks", path="_baris.product_name"),
            Kolom("warna", "Warna", "teks", path="_baris.color"),
            Kolom("ukuran", "Ukuran", "teks", path="_baris.size"),
            Kolom("qty_dikirim_cmt", "Qty dikirim CMT", "angka", path="_baris.qty_shipped_by_cmt", bawaan=False),
            Kolom("qty_diharapkan", "Qty diharapkan", "angka", path="_baris.qty_expected"),
            Kolom("qty_lolos_qc", "Qty diterima baik (lolos QC)", "angka", path="_baris.qty_actual",
                  keterangan="Kosong = belum dihitung."),
            Kolom("qty_reject", "Qty reject", "angka", path="_baris.reject_qty"),
            Kolom("qty_kurang", "Qty kurang kirim", "angka", path="_baris.qty_short"),
        ),
        catatan=("Status 'Selesai QC' berarti stok barang jadi dan tagihan CMT sudah terbentuk; untuk hasil produksi "
                 "yang sah saring status = Selesai QC. 'Dibatalkan' = salah input.",),
    ),
    Dataset(
        id="tagihan_cmt",
        label="Tagihan CMT",
        keterangan="Tagihan upah jahit vendor CMT per penerimaan: pcs ditagih, reject, nilai tagihan, terbayar, sisa.",
        koleksi="dewi_cmt_payments", domain="produksi", akses=AKSES_TAGIHAN, kolom_tanggal="tanggal_tagihan",
        saringan_dasar={"status": {"$nin": ["cancelled", "void", "voided"]}},
        gabung=(Gabung("_po", "production_pos", "po_id", "id", ambil=("business_type",)),),
        cv={"mode": "saringan", "gabung": "_po",
            "DA": {"$or": [{"entity": "DA"},
                           {"entity": {"$in": [None, ""]}, "_po.business_type": {"$ne": "maklon"}}]},
            "SMU": {"$or": [{"entity": "SMU"}, {"entity": {"$in": [None, ""]}, "_po.business_type": "maklon"}]}},
        kolom=(
            Kolom("no_tagihan", "Nomor tagihan", "teks", path="payment_code"),
            Kolom("tanggal_tagihan", "Tanggal tagihan", "tanggal", path="invoice_date",
                  cadangan=("period_to", "payment_date", "created_at"), simpan="campur",
                  keterangan="Tanggal penerimaan barang yang ditagih."),
            Kolom("vendor", "Vendor CMT", "teks", path="vendor_name", cadangan=("cmt_name",), samaran="vendor"),
            Kolom("no_po", "Nomor PO", "teks", path="po_number"),
            Kolom("no_terima", "Nomor penerimaan", "teks", path="source_receipt_code", bawaan=False),
            Kolom("jenis", "Jenis PO", "teks", gabung=("_po",), nilai=("internal", "maklon"),
                  ekspr={"$cond": [{"$eq": ["$_po.business_type", "maklon"]}, "maklon", "internal"]}),
            Kolom("status", "Status tagihan", "teks", path="status",
                  nilai=("draft", "submitted", "approved", "pending", "posted", "partial_paid", "paid")),
            Kolom("pcs_ditagih", "Pcs ditagih", "angka", path="total_pcs"),
            Kolom("pcs_reject", "Pcs reject", "angka", path="total_rejected"),
            Kolom("nilai_tagihan", "Nilai tagihan", "uang", path="net_amount", cadangan=("total_amount", "subtotal")),
            Kolom("potongan", "Potongan/denda", "uang", path="total_penalty", bawaan=False),
            Kolom("terbayar", "Sudah dibayar", "uang", path="paid_amount"),
            Kolom("sisa", "Sisa tagihan", "uang", ekspr={"$ifNull": [e_angka("$outstanding_amount"), {"$subtract": [
                {"$ifNull": [e_angka_atau("net_amount", "total_amount", "subtotal"), 0]},
                {"$ifNull": [e_angka("$paid_amount"), 0]}]}]}),
            Kolom("perlu_tinjau", "Perlu ditinjau Keuangan", "ya_tidak", path="variance_flagged", bawaan=False),
        ),
        catatan=("Tagihan batal tidak ikut. Total tagihan = jumlah nilai_tagihan; sisa hanya bermakna untuk status "
                 "terbuka (draft, submitted, approved, pending, posted, partial_paid).",),
    ),
)

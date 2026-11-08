"""Katalog data — baris jurnal buku besar dan mutasi kas/bank (Portal Keuangan).

Sumber (penulis diverifikasi):
  * `rahaza_journal_lines` — cermin baris jurnal yang SUDAH DIPOSTING (`routes/rahaza_posting.py` dan
    `routes/rahaza_journals._mirror_lines`; jurnal batal menghapus cerminnya). Dipakai neraca saldo & laporan
    (`core.fin_statements`). CV = field `entity` (`core.entities.entity_match`).
  * `rahaza_cash_movements` — mutasi rekening kas/bank (`routes/rahaza_finance.py`, `routes/sales_direct.py`,
    `core.intercompany`, rekonsiliasi bank). CV = pemilik rekening (`rahaza_cash_accounts.entity`).
Baris gaji/tunjangan disembunyikan bagi peran di luar `PERAN_GAJI` (keputusan owner K27, sama dengan alat keuangan).
Nomor rekening tidak dimasukkan.
"""
from __future__ import annotations

from core.asisten_ai.katalog_data import Akses, Dataset, Kolom, e_angka

AKSES_JURNAL = Akses(portal=("finance",), peran=("manager_keuangan",), modul=("fin_journal", "fin_dashboard"))
AKSES_KAS = Akses(portal=("finance",), peran=("manager_keuangan",), modul=("fin_cash",))
_CV = Kolom("cv", "CV", "teks", ekspr={"$ifNull": ["$entity", "DA"]}, bawaan=False, nilai=("DA", "SMU"))

DATASET = (
    Dataset(
        id="baris_jurnal",
        label="Baris jurnal buku besar",
        keterangan=("Setiap baris debit/kredit jurnal yang sudah diposting: tanggal, nomor jurnal, akun, jenis akun, "
                    "debit, kredit, keterangan, modul sumber. Dasar neraca saldo, laba rugi, dan buku besar."),
        koleksi="rahaza_journal_lines", domain="keuangan", akses=AKSES_JURNAL, kolom_tanggal="tanggal",
        cv={"mode": "field", "field": "entity"}, baris_gaji=("account_name", "description"),
        kolom=(
            Kolom("tanggal", "Tanggal jurnal", "tanggal", path="date", simpan="teks"),
            Kolom("periode", "Periode (TTTT-BB)", "teks", path="period_code", bawaan=False),
            Kolom("no_jurnal", "Nomor jurnal", "teks", path="je_number"),
            Kolom("kode_akun", "Kode akun", "teks", path="account_code"),
            Kolom("nama_akun", "Nama akun", "teks", path="account_name"),
            Kolom("jenis_akun", "Jenis akun", "teks", path="account_type",
                  nilai=("ASSET", "LIABILITY", "EQUITY", "REVENUE", "COGS", "EXPENSE")),
            Kolom("debit", "Debit", "uang", path="debit"),
            Kolom("kredit", "Kredit", "uang", path="credit"),
            Kolom("selisih", "Debit − kredit", "uang", ekspr={"$subtract": [
                {"$ifNull": [e_angka("$debit"), 0]}, {"$ifNull": [e_angka("$credit"), 0]}]}),
            Kolom("keterangan", "Keterangan baris", "teks", path="description", teks_bebas=True),
            Kolom("modul_sumber", "Modul sumber", "teks", path="source_module",
                  keterangan="mis. ap_invoice, ap_payment, ar_invoice, expense, manual, marketplace_settlement."),
            _CV,
        ),
        catatan=(
            "Hanya jurnal yang sudah diposting (draft & batal tidak ada). Aset, beban, dan HPP bertambah di debit; "
            "kewajiban, ekuitas, dan pendapatan bertambah di kredit. Pendapatan = jumlah (kredit − debit) akun "
            "REVENUE; beban = jumlah selisih akun EXPENSE dan COGS.",
            "Laporan resmi (laba rugi/neraca) punya aturan tambahan (eliminasi antar CV pada Gabungan, saldo awal); "
            "untuk angka resmi pakai alat laporan keuangan, dataset ini untuk rincian.",
        ),
    ),
    Dataset(
        id="mutasi_kas_bank",
        label="Mutasi kas & bank",
        keterangan="Uang masuk/keluar per rekening kas/bank: tanggal, rekening, arah, jumlah, kategori, referensi.",
        koleksi="rahaza_cash_movements", domain="keuangan", akses=AKSES_KAS, kolom_tanggal="tanggal",
        cv={"mode": "rekening", "field": "account_id"}, baris_gaji=("category", "ref_label", "notes"),
        kolom=(
            Kolom("tanggal", "Tanggal", "tanggal", path="date", simpan="campur"),
            Kolom("rekening", "Rekening", "teks", path="account_name"),
            Kolom("rekening_id", "Id rekening", "teks", path="account_id", bawaan=False),
            Kolom("arah", "Arah", "teks", path="direction", nilai=("in", "out"),
                  keterangan="in = uang masuk, out = uang keluar."),
            Kolom("jumlah", "Jumlah", "uang", path="amount"),
            Kolom("masuk", "Uang masuk", "uang", ekspr={"$cond": [{"$eq": ["$direction", "in"]},
                                                                  e_angka("$amount"), 0]}),
            Kolom("keluar", "Uang keluar", "uang", ekspr={"$cond": [{"$eq": ["$direction", "out"]},
                                                                    e_angka("$amount"), 0]}),
            Kolom("kategori", "Kategori", "teks", path="category",
                  keterangan="mis. ar_payment, ap_payment, expense, sales_refund, bank_adjustment."),
            Kolom("referensi", "Referensi", "teks", path="ref_label", teks_bebas=True),
            Kolom("catatan_mutasi", "Catatan", "teks", path="notes", teks_bebas=True, bawaan=False),
            Kolom("no_jurnal", "Nomor jurnal", "teks", path="gl_je_number", bawaan=False),
        ),
        catatan=("Arus kas bersih = jumlah masuk − jumlah keluar. Transfer antar rekening sendiri tidak tercatat di "
                 "sini (hanya di jurnal); saldo resmi rekening berasal dari buku besar (baris_jurnal akun kas/bank).",),
    ),
)

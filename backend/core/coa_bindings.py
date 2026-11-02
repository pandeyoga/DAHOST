"""core.coa_bindings — SATU daftar keterikatan akun Bagan Akun (SSOT). 2026-11-02, paket S2-H.

Permintaan owner: "untuk Chart of akun itu tolong tandai mana yang terhubung atau tidak karena
takutnya salah hapus". Dulu satu-satunya cek pemakaian akun = baris jurnal
(`routes.rahaza_coa.account_journal_usage`). Profil posting, toko, rekening, sub-ledger, pemetaan
kategori, induk Auto Akun, dan kode akun di program tidak terlihat, sehingga akun yang terhubung
bisa dihapus permanen (audit w1, uji T1–T12).

Modul ini MEMPERLUAS `account_journal_usage` (fungsi lama tetap ada sebagai pembungkus). Satu
daftar ini dipakai bersama oleh:
  * lencana "Terhubung · N" + laci rincian di layar Bagan Akun (`GET /accounts?with_usage`,
    `GET /accounts/{id}/usage`);
  * penjaga PUT/DELETE akun dan impor Excel COA (`check_action`);
  * status Setup Akuntansi + `GET /coa/integrity` (INV-COA-REF: rujukan konfigurasi → akun ada,
    aktif, dan bisa diposting).

Konstanta kode akun DIBACA dari modul pemiliknya lewat importlib (tidak disalin). Literal yang
memang tidak punya nama konstanta dicatat di `INLINE_CODES` dan dijaga uji grep
(`tests/unit/test_coa_bindings.py`) supaya daftar ini tidak menyimpang dari program.
"""
from __future__ import annotations

import importlib
import logging
import re
from collections import defaultdict

log = logging.getLogger(__name__)

# ── Tingkat keterikatan (warna lencana di layar) ──────────────────────────────
SISTEM, STRUKTUR, SEED, BEBAS = "SISTEM", "STRUKTUR", "SEED", "BEBAS"
LEVEL_RANK = {BEBAS: 0, SEED: 1, STRUKTUR: 2, SISTEM: 3}
LEVEL_LABELS = {SISTEM: "Terhubung sistem", STRUKTUR: "Struktur / laporan",
                SEED: "Akun bawaan", BEBAS: "Tidak terhubung"}

ACTIONS = ("delete", "deactivate", "make_group", "make_leaf", "change_type", "change_code")
ACTION_LABELS = {
    "delete": "dihapus permanen", "deactivate": "dinonaktifkan",
    "make_group": "dijadikan akun grup (header)", "make_leaf": "dijadikan akun rinci (bukan grup)",
    "change_type": "diubah tipenya", "change_code": "diubah kodenya",
}

# Keterikatan yang sudah tidak aktif (mis. toko nonaktif) tetap melarang hapus/ubah kode — rujukannya
# masih ada dan akan rusak bila toko dihidupkan lagi — tetapi tidak melarang nonaktif/jadikan grup.
_INACTIVE_KEEPS = {"delete", "change_code", "change_type", "make_leaf"}
_CFG = frozenset({"delete", "deactivate", "make_group", "change_code"})

# Tautan layar pengaturan (dipakai laci rincian): modul App + tab hub.
_SCR_PROFIL = {"module": "fin-accounting-master-hub", "tab": "posting", "label": "Profil Posting"}
_SCR_AUTO = {"module": "fin-accounting-master-hub", "tab": "coa-auto", "label": "Auto Akun (Subledger)"}
_SCR_GLMAP = {"module": "fin-accounting-master-hub", "tab": "glmap", "label": "Pemetaan GL"}
_SCR_COA = {"module": "fin-accounting-master-hub", "tab": "coa", "label": "Bagan Akun"}
_SCR_TOKO = {"module": "marketing-accounts", "label": "Kelola Akun toko (Tautan Finance)"}
_SCR_PAYOUT = {"module": "fin-marketplace-settlement", "label": "Tautan Rekening Bank per Toko"}
_SCR_KAS = {"module": "fin-cash", "label": "Rekening Kas & Bank"}
_SCR_PETTY = {"module": "fin-petty-cash", "label": "Kas Kecil"}
_SCR_ASET = {"module": "fin-fixed-assets", "label": "Aset Tetap"}
_SCR_ASET_KAT = {"module": "asset-management", "label": "Manajemen Aset › Kategori"}
_SCR_BUDGET = {"module": "fin-budget", "label": "Anggaran"}
_SCR_JURNAL = {"module": "fin-journal-hub", "label": "Buku Jurnal"}
_SCR_GL = {"module": "fin-general-ledger", "label": "Buku Besar"}
ENTITY_SCREENS = {
    "vendor_partners": {"module": "vendor-admin", "label": "Vendor CMT"},
    "dewi_cmt_partners": {"module": "vendor-admin", "label": "Vendor CMT (lama)"},
    "rahaza_vendors": {"module": "proc-suppliers", "label": "Master Pemasok"},
    "rahaza_customers": {"module": "sales-customers", "label": "Pelanggan"},
    "dewi_maklon_clients": {"module": "maklon-clients", "label": "Klien Maklon"},
}

KINDS = {
    "profil": {"label": "Profil Posting", "level": SISTEM, "blocks": _CFG, "postable": True},
    "toko": {"label": "Tautan Finance toko", "level": SISTEM, "blocks": _CFG, "postable": True},
    "rekening": {"label": "Rekening Kas & Bank", "level": SISTEM, "blocks": _CFG, "postable": True},
    "peta_channel": {"label": "Peta Akun Channel (dihentikan, masih dibaca invoice AR)", "level": SISTEM,
                     "blocks": _CFG, "postable": True},
    "auto_coa": {"label": "Induk Auto Akun (sub-ledger)", "level": SISTEM,
                 "blocks": frozenset({"delete", "deactivate", "change_code"}), "postable": False},
    "entitas": {"label": "Master relasi (pemasok / vendor / pelanggan / klien)", "level": SISTEM,
                "blocks": _CFG, "postable": True},
    "subledger": {"label": "Akun sub-ledger milik relasi", "level": SISTEM,
                  "blocks": frozenset({"delete", "change_code", "change_type", "make_group"}), "postable": False},
    "pemetaan_gl": {"label": "Pemetaan GL kategori (klaim / kas kecil)", "level": SISTEM, "blocks": _CFG,
                    "postable": True},
    "kas_kecil": {"label": "Dana kas kecil (rekening sumber)", "level": SISTEM, "blocks": _CFG, "postable": True},
    "kategori_aset": {"label": "Kategori aset", "level": SISTEM, "blocks": _CFG, "postable": True},
    "aset_tetap": {"label": "Register aset tetap", "level": SISTEM, "blocks": _CFG, "postable": True},
    "anggaran": {"label": "Anggaran", "level": SISTEM,
                 "blocks": frozenset({"delete", "change_code", "make_group"}), "postable": False},
    "kode_posting": {"label": "Kode akun di program (posting langsung)", "level": SISTEM, "blocks": _CFG,
                     "postable": True},
    "kode_sinkron": {"label": "Kode akun sinkron otomatis", "level": SISTEM,
                     "blocks": frozenset({"delete", "deactivate", "change_code"}), "postable": False},
    "kode_cadangan": {"label": "Kode akun cadangan di program", "level": SISTEM,
                      "blocks": frozenset({"delete", "change_code"}), "postable": True},
    "kode_laporan": {"label": "Kode akun dibaca laporan", "level": STRUKTUR,
                     "blocks": frozenset({"delete", "change_code"}), "postable": False},
    "jurnal": {"label": "Baris jurnal (posted)", "level": SISTEM,
               "blocks": frozenset({"delete", "make_group", "change_type", "change_code"}), "postable": False},
    "jurnal_draft": {"label": "Jurnal draft", "level": SISTEM,
                     "blocks": frozenset({"delete", "make_group", "change_type", "change_code"}), "postable": False},
    "anak": {"label": "Akun anak", "level": STRUKTUR,
             "blocks": frozenset({"delete", "make_leaf", "change_code", "change_type", "deactivate"}), "postable": False},
    "flag": {"label": "Penanda laporan / validator", "level": STRUKTUR, "blocks": frozenset({"delete"}),
             "postable": False},
    "sinkron_toko": {"label": "Akun pendapatan toko (dikelola sinkron toko)", "level": STRUKTUR,
                     "blocks": frozenset({"delete"}), "postable": False},
    "seed": {"label": "Akun bawaan sistem", "level": SEED, "blocks": frozenset({"delete", "change_code"}),
             "postable": False},
}
# Rujukan KONFIGURASI (bukan jurnal/struktur) — diperiksa INV-COA-REF: akun harus ada & aktif.
CONFIG_KINDS = ("profil", "toko", "rekening", "peta_channel", "auto_coa", "entitas", "pemetaan_gl",
                "kas_kecil", "kategori_aset", "aset_tetap", "anggaran", "kode_posting", "kode_sinkron")

# Penanda akun yang BENAR-BENAR dibaca program (hasil grep 2026-11-02). Penanda lain (is_inventory_rm,
# is_tax_input, …) hanya keterangan seed, tidak dibaca modul mana pun → bukan keterikatan.
FLAG_BINDINGS = {
    "is_cash": "Penanda kas → daftar akun kas, Arus Kas, sinkron Rekening Kas & Bank, rekening pencairan toko",
    "is_bank": "Penanda bank → daftar akun kas, Arus Kas, sinkron Rekening Kas & Bank, rekening pencairan toko",
    "is_ar": "Penanda piutang → pilihan akun piutang toko (Kelola Akun)",
    "is_sales": "Penanda penjualan toko → pilihan akun pendapatan toko (Kelola Akun)",
    "legacy_of": "Akun lama 3 digit → pencairan dialihkan ke akun 4 digit",
}

# ── Konstanta kode akun di program (DIBACA dari modulnya) ─────────────────────
# (modul, atribut, kunci) → kunci: None = nilai str · "*" = semua nilai dict · str = satu kunci dict ·
# ("sheet", nama) = RELATION_SHEETS · ("cat", i) = kolom ke-i CATEGORY_ACCOUNTS · ("entity", tipe).
# `role` = peran profil posting yang kini memuat akun yang sama (2026-11-02, S2-H butir 4);
# `reads_profile` = modul konsumen sudah membaca peran itu (False = masih memakai konstanta).
# 2026-11-02 (tindak lanjut S2-H butir 7): pencairan marketplace, perjalanan dinas, tutup buku, dan
# saldo awal kini membaca peran lewat `role_code()` — konstanta tinggal bawaan/cadangan.
CONSTANT_SOURCES = [
    # pencairan marketplace (jurnal draft) — routes/marketing_settlements.py
    {"module": "routes.marketing_settlements", "attr": "COA", "key": "returns", "kind": "kode_posting",
     "label": "Pencairan marketplace: retur penjualan", "role": ("marketplace_settlement", "debit_returns"), "reads_profile": True},
    {"module": "routes.marketing_settlements", "attr": "COA", "key": "discount", "kind": "kode_posting",
     "label": "Pencairan marketplace: diskon penjual", "role": ("marketplace_settlement", "debit_discount"), "reads_profile": True},
    {"module": "routes.marketing_settlements", "attr": "COA", "key": "platform_fee", "kind": "kode_posting",
     "label": "Pencairan marketplace: potongan / fee platform", "role": ("marketplace_settlement", "debit_platform_fee"), "reads_profile": True},
    {"module": "routes.marketing_settlements", "attr": "COA", "key": "ads", "kind": "kode_posting",
     "label": "Pencairan marketplace: iklan (bawaan)", "role": ("marketplace_settlement", "debit_ads_default"), "reads_profile": True},
    {"module": "routes.marketing_settlements", "attr": "COA", "key": "other", "kind": "kode_posting",
     "label": "Pencairan marketplace: pendapatan lain (subsidi ongkir)", "role": ("marketplace_settlement", "credit_other_income"), "reads_profile": True},
    {"module": "routes.marketing_settlements", "attr": "COA", "key": "other_expense", "kind": "kode_posting",
     "label": "Pencairan marketplace: potongan lain", "role": ("marketplace_settlement", "debit_other_expense"), "reads_profile": True},
    {"module": "routes.marketing_settlements", "attr": "COA", "key": "receivable", "kind": "kode_cadangan",
     "label": "Pencairan marketplace: piutang platform (cadangan; toko wajib punya piutang sendiri)"},
    {"module": "routes.marketing_settlements", "attr": "COA", "key": "revenue", "kind": "kode_cadangan",
     "label": "Pencairan marketplace: pendapatan bruto (cadangan; toko wajib punya akun sendiri)"},
    {"module": "routes.marketing_settlements", "attr": "ADS_BY_PLATFORM", "key": "shopee", "kind": "kode_posting",
     "label": "Pencairan marketplace: iklan Shopee", "role": ("marketplace_settlement", "debit_ads_shopee"), "reads_profile": True},
    {"module": "routes.marketing_settlements", "attr": "ADS_BY_PLATFORM", "key": "tiktok", "kind": "kode_posting",
     "label": "Pencairan marketplace: iklan TikTok", "role": ("marketplace_settlement", "debit_ads_tiktok"), "reads_profile": True},
    {"module": "routes.marketing_settlements", "attr": "ADS_BY_PLATFORM", "key": "tokopedia", "kind": "kode_posting",
     "label": "Pencairan marketplace: iklan Tokopedia", "role": ("marketplace_settlement", "debit_ads_tokopedia"), "reads_profile": True},
    # perjalanan dinas
    {"module": "routes.employee_travel_requests", "attr": "GL_EMPLOYEE_ADVANCE", "kind": "kode_posting",
     "label": "Perjalanan dinas: uang muka karyawan (Dr)", "role": ("employee_travel", "debit_employee_advance"), "reads_profile": True},
    {"module": "routes.employee_travel_requests", "attr": "GL_BANK_DEFAULT", "kind": "kode_cadangan",
     "label": "Perjalanan dinas: rekening bayar uang muka (cadangan)", "role": ("employee_travel", "credit_bank_default"), "reads_profile": True},
    {"module": "routes.employee_travel_settlements", "attr": "GL_TRAVEL_EXPENSE", "kind": "kode_posting",
     "label": "Penyelesaian dinas: beban perjalanan dinas (Dr)", "role": ("employee_travel", "debit_travel_expense"), "reads_profile": True},
    {"module": "routes.employee_travel_settlements", "attr": "GL_EMPLOYEE_ADVANCE", "kind": "kode_posting",
     "label": "Penyelesaian dinas: uang muka karyawan (Cr)", "role": ("employee_travel", "debit_employee_advance"), "reads_profile": True},
    {"module": "routes.employee_travel_settlements", "attr": "GL_BANK_DEFAULT", "kind": "kode_cadangan",
     "label": "Penyelesaian dinas: rekening bawaan", "role": ("employee_travel", "credit_bank_default"), "reads_profile": True},
    # tutup buku & saldo awal
    {"module": "routes.rahaza_year_end", "attr": "RETAINED_EARNINGS", "kind": "kode_posting",
     "label": "Tutup buku tahunan: laba ditahan", "role": ("year_end_close", "credit_retained_earnings"), "reads_profile": True},
    {"module": "core.opening_balance", "attr": "RETAINED_EARNINGS", "kind": "kode_posting",
     "label": "Saldo awal go-live: penyeimbang laba ditahan",
     "role": ("subledger_opening_balance", "credit_retained_earnings_balancing"), "reads_profile": True},
    {"module": "core.opening_balance", "attr": "RELATION_SHEETS", "key": ("sheet", "PIUTANG_PELANGGAN"),
     "kind": "kode_posting", "label": "Saldo awal go-live: kontrol piutang pelanggan",
     "role": ("subledger_opening_balance", "control_ar_customer"), "reads_profile": True},
    {"module": "core.opening_balance", "attr": "RELATION_SHEETS", "key": ("sheet", "PIUTANG_MAKLON"),
     "kind": "kode_posting", "label": "Saldo awal go-live: kontrol piutang maklon",
     "role": ("subledger_opening_balance", "control_ar_maklon"), "reads_profile": True},
    {"module": "core.opening_balance", "attr": "RELATION_SHEETS", "key": ("sheet", "HUTANG_SUPPLIER"),
     "kind": "kode_posting", "label": "Saldo awal go-live: kontrol hutang pemasok",
     "role": ("subledger_opening_balance", "control_ap_supplier"), "reads_profile": True},
    {"module": "core.opening_balance", "attr": "RELATION_SHEETS", "key": ("sheet", "HUTANG_VENDOR_CMT"),
     "kind": "kode_posting", "label": "Saldo awal go-live: kontrol hutang vendor CMT",
     "role": ("subledger_opening_balance", "control_ap_cmt"), "reads_profile": True},
    # cadangan yang SUDAH dibaca lewat profil (konstanta hanya bila peran kosong)
    {"module": "routes.rahaza_posting", "attr": "PAYROLL_OTHER_DEDUCTION_DEFAULT", "kind": "kode_cadangan",
     "label": "Payroll: potongan penyesuaian manual (cadangan)", "role": ("payroll_finalize", "credit_other_deduction"),
     "reads_profile": True},
    {"module": "routes.rahaza_petty_cash", "attr": "EMPLOYEE_ADVANCE_DEFAULT", "kind": "kode_cadangan",
     "label": "Kas kecil: uang muka karyawan (cadangan)", "role": ("petty_cash_expense", "debit_employee_advance"),
     "reads_profile": True},
    {"module": "routes.rahaza_fixed_assets", "attr": "CATEGORY_ACCOUNTS", "key": ("cat", 0), "kind": "kode_cadangan",
     "label": "Aset tetap: akun aset bawaan per kategori"},
    {"module": "routes.rahaza_fixed_assets", "attr": "CATEGORY_ACCOUNTS", "key": ("cat", 1), "kind": "kode_cadangan",
     "label": "Aset tetap: akumulasi penyusutan bawaan per kategori"},
    {"module": "routes.rahaza_fixed_assets", "attr": "CATEGORY_ACCOUNTS", "key": ("cat", 2), "kind": "kode_cadangan",
     "label": "Aset tetap: beban penyusutan bawaan per kategori"},
    {"module": "routes.marketing_accounts", "attr": "DEFAULT_CASH_CODE", "kind": "kode_cadangan",
     "label": "Toko baru: rekening pencairan bawaan"},
    {"module": "routes.marketing_accounts", "attr": "DEFAULT_RECEIVABLE_CODE", "kind": "kode_cadangan",
     "label": "Toko baru: piutang platform bawaan"},
    {"module": "routes.employee_expense_gl_mapping", "attr": "DEFAULT_TRAVEL_EXPENSE_GL", "kind": "kode_cadangan",
     "label": "Klaim perjalanan: akun GL bawaan"},
    # sinkron startup / Auto Akun bawaan
    {"module": "core.finance_sync", "attr": "CMT_AP_PARENT", "kind": "kode_sinkron",
     "label": "Sinkron startup: induk hutang vendor CMT + profil cmt_ap_invoice"},
    {"module": "core.finance_sync", "attr": "MAKLON_AR_PARENT", "kind": "kode_sinkron",
     "label": "Sinkron startup: induk piutang klien maklon"},
    {"module": "core.finance_sync", "attr": "CHANNEL_AR_PARENT", "kind": "kode_sinkron",
     "label": "Sinkron startup: piutang toko bawaan"},
    {"module": "core.finance_sync", "attr": "REVENUE_GROUP", "key": "*", "kind": "kode_sinkron",
     "label": "Sinkron startup: kelompok pendapatan per platform"},
    {"module": "routes.coa_auto", "attr": "DEFAULT_ENTITY_TYPES", "key": ("entity", "*"), "kind": "kode_sinkron",
     "label": "Auto Akun: induk bawaan sub-ledger"},
    # laporan
    {"module": "routes.rahaza_fin_reports", "attr": "FG_INVENTORY_ACCOUNT", "kind": "kode_laporan",
     "label": "Rekonsiliasi persediaan barang jadi vs GL"},
    {"module": "core.laporan_sisa", "attr": "DEFAULT_CASH", "kind": "kode_laporan",
     "label": "Laporan sisa: deteksi rekening pencairan bawaan"},
]

# Literal kode akun yang TIDAK punya nama konstanta di modulnya (hanya bisa dicatat di sini).
# Uji grep memastikan setiap literal di berkas-berkas ini tercatat — tambah literal baru tanpa
# mencatatnya ⇒ uji gagal. (file, kode, jenis, keterangan, peran profil yang mendahuluinya)
INLINE_CODES = [
    ("routes/rahaza_petty_cash.py", "1-1101", "kode_cadangan", "Kas kecil: akun dana kas kecil cadangan",
     ("petty_cash_replenish", "debit_petty_cash")),
    ("routes/rahaza_petty_cash.py", "1-1201", "kode_cadangan", "Kas kecil: rekening sumber cadangan",
     ("petty_cash_replenish", "credit_bank_default")),
    ("routes/employee_expense_claims.py", "6-3500", "kode_cadangan",
     "Klaim reimburse: akun beban bila kategori belum dipetakan", None),
    ("routes/sales_direct.py", "1-1404", "kode_cadangan", "Retur penjualan langsung: persediaan FG cadangan",
     ("cogs_shipment", "credit_fg_inventory")),
    ("routes/rahaza_bank_transfers.py", "1-1201", "kode_cadangan", "Transfer bank: rekening sumber cadangan",
     ("bank_transfer", "credit_bank_source")),
    ("routes/rahaza_bank_transfers.py", "1-1202", "kode_cadangan", "Transfer bank: rekening tujuan cadangan",
     ("bank_transfer", "debit_bank_target")),
    ("routes/rahaza_finance.py", "1-1100", "kode_sinkron", "Rekening tipe kas: induk sub-ledger", None),
    ("routes/rahaza_finance.py", "1-1303", "kode_laporan", "Deteksi invoice AR marketplace (awalan akun piutang)", None),
    ("core/fin_statements.py", "1-1100", "kode_laporan", "Arus kas: induk akun kas", None),
    ("core/fin_statements.py", "1-1200", "kode_laporan", "Arus kas: induk akun bank", None),
    ("core/finance_sync.py", "1-1201", "kode_cadangan", "Sinkron startup: rekening pencairan toko bawaan", None),
    ("core/finance_sync.py", "2-1100", "kode_sinkron",
     "Sinkron startup: nilai LAMA cmt_ap_invoice.credit_ap yang diganti induk vendor CMT", None),
]

CODE_RX = re.compile(r"^[1-9]-\d{3,4}(?:-[A-Za-z0-9]+)*$")


def _resolve_constant(src: dict) -> list:
    """Nilai kode akun dari satu `CONSTANT_SOURCES` (importlib — tidak disalin)."""
    try:
        val = getattr(importlib.import_module(src["module"]), src["attr"])
    except Exception as e:  # noqa: BLE001 — modul gagal dimuat: catat, jangan menjatuhkan daftar
        log.warning("[coa_bindings] konstanta %s.%s tidak terbaca: %s", src["module"], src["attr"], e)
        return []
    key = src.get("key")
    if key is None:
        return [val] if isinstance(val, str) else []
    if key == "*":
        return [v for v in (val or {}).values() if isinstance(v, str)]
    if isinstance(key, tuple) and key[0] == "sheet":
        return [row[1] for row in val if row and row[0] == key[1]]
    if isinstance(key, tuple) and key[0] == "cat":
        return sorted({t[key[1]] for t in (val or {}).values() if t and t[key[1]]})
    if isinstance(key, tuple) and key[0] == "entity":
        out = set()
        for cfg in (val or {}).values():
            if (cfg or {}).get("parent_code"):
                out.add(cfg["parent_code"])
            out |= {g for g in ((cfg or {}).get("parent_by_platform") or {}).values() if g}
        return sorted(out)
    return [val.get(key)] if isinstance(val, dict) and val.get(key) else []


def constant_bindings() -> list[dict]:
    """Semua konstanta kode akun di program: [{code, kind, label, source, role, reads_profile}]."""
    out = []
    for src in CONSTANT_SOURCES:
        for code in _resolve_constant(src):
            out.append({"code": code, "kind": src["kind"], "label": src["label"],
                        "source": f"{src['module']}.{src['attr']}" + (f"[{src['key']}]" if src.get("key") else ""),
                        "role": src.get("role"), "reads_profile": bool(src.get("reads_profile"))})
    for f, code, kind, label, role in INLINE_CODES:
        out.append({"code": code, "kind": kind, "label": label, "source": f, "role": role, "reads_profile": True})
    return out


# ── Peran profil yang dibaca mesin posting lewat TABEL PERAN (tanpa konstanta kode akun) ─────────
# 2026-11-02 (K13 + owner No.26a + K41): akun persediaan per jenis barang (bahan · aksesoris · FG) dan
# akun "Keluarkan Stok FG" per alasan. Tabelnya DIBACA dari modul pemiliknya (tidak disalin); kode
# akunnya hanya ada di profil posting (bawaan DEFAULT_PROFILES) — peran kosong ⇒ posting ditolak.
PROFILE_ROLE_TABLES = [
    {"module": "routes.rahaza_posting", "attr": "INVENTORY_ROLE_BY_KIND", "shape": "event_kind_role",
     "label": "Mesin posting persediaan: akun per jenis barang (bahan 1-1401 · aksesoris 1-1402 · barang jadi 1-1404)"},
    {"module": "routes.rahaza_posting", "attr": "FG_ISSUE_DEBIT", "shape": "reason_profile_role",
     "label": "Keluarkan Stok FG: akun debit per alasan (nilai WAC, Cr persediaan barang jadi)"},
    # 2026-11-02 (K11): Retur Pembelian & Nota Debit — klaim retur / GRNI / hutang / PPV / beban musnah
    {"module": "routes.rahaza_posting", "attr": "PURCHASE_RETURN_ROLES", "shape": "event_kind_role",
     "label": "Retur Pembelian & Nota Debit: klaim retur, GRNI, hutang, selisih harga, beban musnah"},
    # 2026-11-02 (K15): Scan Keluar Penjualan — jurnal HPP harian per lembar (komponen WAC / Cr 1-1404)
    {"module": "core.scan_out", "attr": "PROFILE_ROLES", "shape": "event_kind_role",
     "label": "Scan Keluar Penjualan: HPP harian per lembar (Dr HPP per komponen WAC / Cr persediaan barang jadi)"},
    # 2026-11-02 (K9): Sesi Opname — lawan selisih (5-1950) / barang rusak (6-4300), satu jurnal per sesi
    {"module": "core.opname_engine", "attr": "CONTRA_ROLES", "shape": "event_kind_role",
     "label": "Sesi Opname: lawan selisih hitung (5-1950) / baris rusak (6-4300); persediaan per jenis"},
]


def profile_role_reads() -> list[tuple]:
    """[(event, role, sumber, label)] dari PROFILE_ROLE_TABLES (importlib — tidak disalin)."""
    out = []
    for src in PROFILE_ROLE_TABLES:
        try:
            val = getattr(importlib.import_module(src["module"]), src["attr"])
        except Exception as e:  # noqa: BLE001
            log.warning("[coa_bindings] tabel peran %s.%s tidak terbaca: %s", src["module"], src["attr"], e)
            continue
        pairs = set()
        if src["shape"] == "event_kind_role":
            pairs = {(ev, role) for ev, by_kind in (val or {}).items() for role in (by_kind or {}).values()}
        elif src["shape"] == "reason_profile_role":
            pairs = {(ev, role) for chain in (val or {}).values() for ev, role in chain if role != "components"}
        out += [(ev, role, f"{src['module']}.{src['attr']}", src["label"]) for ev, role in sorted(pairs)]
    return out


def role_consumers() -> dict:
    """{"event.role": [{module, constant, reads_profile}]} — dipakai layar Profil Posting untuk menandai
    peran yang nilainya masih dibaca modul sebagai konstanta (belum dari profil)."""
    out: dict = defaultdict(list)
    for b in constant_bindings():
        if b.get("role"):
            out[f"{b['role'][0]}.{b['role'][1]}"].append(
                {"source": b["source"], "code": b["code"], "reads_profile": b["reads_profile"], "label": b["label"]})
    try:
        from routes.rahaza_posting_profiles import DEFAULT_PROFILES
        defaults = {p["event_type"]: p["mapping"] for p in DEFAULT_PROFILES}
    except Exception:  # noqa: BLE001
        defaults = {}
    for ev, role, source, label in profile_role_reads():
        out[f"{ev}.{role}"].append({"source": source, "code": (defaults.get(ev) or {}).get(role),
                                    "reads_profile": True, "label": label})
    return dict(out)


# ── Pengumpul keterikatan ─────────────────────────────────────────────────────
async def _count_by(coll, field: str, match: dict) -> dict:
    """{nilai field: jumlah dokumen} — aggregate bila tersedia (Mongo), cadangan iterasi (uji unit)."""
    agg = getattr(coll, "aggregate", None)
    out: dict = defaultdict(int)
    if agg is not None:
        async for r in agg([{"$match": match}, {"$group": {"_id": f"${field}", "n": {"$sum": 1}}}]):
            if r.get("_id"):
                out[r["_id"]] += int(r.get("n") or 0)
        return dict(out)
    async for d in coll.find(match, {"_id": 0, field: 1}):
        if d.get(field):
            out[d[field]] += 1
    return dict(out)


def _ent_name(d: dict) -> str:
    return str(d.get("name") or d.get("account_name") or d.get("code") or d.get("account_code") or d.get("id") or "")


async def _auto_settings(db) -> dict:
    """Setelan Auto Akun TANPA menulis (get_auto_settings menyemai dokumen bila belum ada)."""
    from routes.coa_auto import DEFAULT_ENTITY_TYPES
    doc = await db.rahaza_coa_auto_settings.find_one({"id": "default"}, {"_id": 0}) or {}
    et = {k: dict(v) for k, v in DEFAULT_ENTITY_TYPES.items()}
    for k, v in (doc.get("entity_types") or {}).items():
        et[k] = {**et.get(k, {}), **(v or {})}
    return et


async def collect_bindings(db, codes=None, *, accounts: list | None = None) -> dict:
    """{kode akun: [keterikatan]} dari SEMUA sumber. `codes` membatasi kode yang diperiksa (penjaga satu
    akun); None = semua (daftar + integritas). Kode yang dirujuk tetapi tidak ada di COA juga muncul."""
    want = {c for c in (codes or []) if c} or None
    out: dict = defaultdict(list)

    def add(code, kind, label, source, *, active=True, screen=None, ref_id=None, detail=""):
        if not isinstance(code, str):
            return
        code = code.strip()
        if not code or (want is not None and code not in want):
            return
        spec = KINDS[kind]
        out[code].append({"kind": kind, "level": spec["level"], "group_label": spec["label"], "label": label,
                          "source": source, "ref_id": ref_id, "active": bool(active),
                          "screen": screen, "detail": detail})

    if accounts is None:
        q = {"code": {"$in": sorted(want)}} if want else {}
        accounts = await db.rahaza_coa_accounts.find(q, {"_id": 0}).to_list(20000)
    by_code = {a.get("code"): a for a in accounts if a.get("code")}
    id_to_code = {a.get("id"): a.get("code") for a in accounts if a.get("id")}

    def code_of(v):
        """Rujukan berupa id COA ATAU kode → kode (None bila tidak dikenal)."""
        if not isinstance(v, str) or not v.strip():
            return None
        v = v.strip()
        if v in id_to_code:
            return id_to_code[v]
        return v if (CODE_RX.match(v) or v in by_code) else (f"id:{v}" if want is None else None)

    # 1. Profil posting (peran → akun)
    from routes.rahaza_posting_profiles import event_label, role_label
    async for p in db.rahaza_posting_profiles.find({}, {"_id": 0}):
        et = p.get("event_type")
        for role, c in (p.get("mapping") or {}).items():
            add(c, "profil", f"{event_label(et)} › {role_label(role, et)}", f"rahaza_posting_profiles.{et}.{role}",
                active=p.get("active", True) is not False, screen=_SCR_PROFIL, ref_id=et,
                detail="" if p.get("active", True) is not False else "profil nonaktif")

    # 2. Toko (Tautan Finance) — satu rujukan per akun per toko
    store_fields = (("coa_revenue_code", "akun pendapatan", _SCR_TOKO), ("ar_account_code", "piutang toko", _SCR_TOKO),
                    ("coa_receivable_code", "piutang toko", _SCR_TOKO), ("coa_cash_code", "rekening pencairan", _SCR_PAYOUT))
    async for s in db.marketing_platform_accounts.find({}, {"_id": 0}):
        seen = set()
        for f, what, scr in store_fields:
            c = s.get(f)
            if not c or (c, what) in seen:
                continue
            seen.add((c, what))
            add(c, "toko", f"Toko {s.get('account_code') or ''} {s.get('account_name') or ''}: {what}".replace("  ", " "),
                f"marketing_platform_accounts.{f}", active=s.get("active", True) is not False, screen=scr,
                ref_id=s.get("id"), detail="" if s.get("active", True) is not False else "toko nonaktif")

    # 3. Rekening Kas & Bank
    async for r in db.rahaza_cash_accounts.find({}, {"_id": 0}):
        add(r.get("gl_account_code"), "rekening", f"Rekening {r.get('code') or ''} {r.get('name') or ''}".strip(),
            "rahaza_cash_accounts.gl_account_code", active=r.get("active", True) is not False, screen=_SCR_KAS,
            ref_id=r.get("id"), detail="" if r.get("active", True) is not False else "rekening nonaktif")

    # 4. Peta Akun Channel (dihentikan D3; baris AKTIF masih dibaca post_ar_invoice)
    async for r in db.rahaza_channel_gl_mapping.find({"active": True}, {"_id": 0}):
        for f, what in (("debit_ar", "piutang"), ("credit_revenue", "pendapatan")):
            add(r.get(f), "peta_channel", f"Peta channel {r.get('channel_key') or ''}: {what}",
                f"rahaza_channel_gl_mapping.{f}", ref_id=r.get("id"))

    # 5. Auto Akun: induk sub-ledger + kelompok pendapatan toko; 6. entitas (field target)
    ets = await _auto_settings(db)
    entity_sources = []
    for et_key, cfg in ets.items():
        en = cfg.get("enabled", True) is not False
        if cfg.get("parent_code"):
            add(cfg["parent_code"], "auto_coa", f"Auto Akun › {cfg.get('label') or et_key}: induk sub-ledger",
                f"rahaza_coa_auto_settings.entity_types.{et_key}.parent_code", active=en, screen=_SCR_AUTO, ref_id=et_key,
                detail="" if en else "tipe entitas dimatikan")
        for plat, g in (cfg.get("parent_by_platform") or {}).items():
            add(g, "auto_coa", f"Auto Akun › Pendapatan toko {plat}: kelompok akun",
                f"rahaza_coa_auto_settings.entity_types.{et_key}.parent_by_platform.{plat}", active=en,
                screen=_SCR_AUTO, ref_id=et_key)
        coll, tf = cfg.get("collection"), cfg.get("target_field")
        if coll and tf and coll not in ("marketing_platform_accounts", "rahaza_cash_accounts"):
            entity_sources.append((coll, tf, cfg.get("label") or et_key))
    if not any(c == "dewi_cmt_partners" for c, _, _ in entity_sources):
        entity_sources.append(("dewi_cmt_partners", "ap_account_code", "Vendor CMT (koleksi lama)"))
    seen_src = set()
    for coll, tf, lbl in entity_sources:
        if (coll, tf) in seen_src:
            continue
        seen_src.add((coll, tf))
        q = {tf: {"$in": sorted(want)}} if want else {tf: {"$nin": [None, ""]}}
        async for e in db[coll].find(q, {"_id": 0}):
            act = e.get("active", True) is not False and (e.get("status") or "active") not in ("inactive", "deleted")
            add(e.get(tf), "entitas", f"{lbl}: {_ent_name(e)}", f"{coll}.{tf}", active=act,
                screen=ENTITY_SCREENS.get(coll), ref_id=e.get("id"), detail="" if act else "relasi nonaktif")

    # 7. Pemetaan GL kategori (klaim & kas kecil)
    async for m in db.employee_expense_gl_mappings.find({}, {"_id": 0}):
        act = m.get("is_active", True) is not False
        add(m.get("gl_account_code"), "pemetaan_gl", f"Pemetaan GL › kategori {m.get('category') or '-'}",
            "employee_expense_gl_mappings.gl_account_code", active=act, screen=_SCR_GLMAP, ref_id=m.get("id"))
    # kategori pengeluaran lama (rahaza_expense_categories): field bernilai kode akun
    async for ec in db.rahaza_expense_categories.find({}, {"_id": 0}):
        for k, v in ec.items():
            if k != "id" and isinstance(v, str) and CODE_RX.match(v):
                add(v, "pemetaan_gl", f"Kategori pengeluaran {ec.get('name') or ec.get('code') or ''}: {k}",
                    f"rahaza_expense_categories.{k}", active=ec.get("active", True) is not False, ref_id=ec.get("id"))

    # 8. Dana kas kecil
    async for f in db.rahaza_petty_cash_funds.find({}, {"_id": 0}):
        act = (f.get("status") or "active") == "active"
        add(f.get("bank_account_code"), "kas_kecil", f"Dana kas kecil {f.get('name') or ''}: rekening sumber",
            "rahaza_petty_cash_funds.bank_account_code", active=act, screen=_SCR_PETTY, ref_id=f.get("id"))

    # 9. Kategori aset & register aset tetap (rujukan id ATAU kode)
    async for k in db.dewi_asset_categories.find({}, {"_id": 0}):
        for fld, what in (("coa_asset_account", "akun aset"), ("coa_depreciation_account", "akun penyusutan")):
            add(code_of(k.get(fld)), "kategori_aset", f"Kategori aset {k.get('name') or ''}: {what}",
                f"dewi_asset_categories.{fld}", screen=_SCR_ASET_KAT, ref_id=k.get("id"))
    async for a in db.rahaza_fixed_assets.find({}, {"_id": 0}):
        act = (a.get("status") or "active") not in ("disposed", "deleted", "sold", "written_off")
        for fld, what in (("account_id_asset", "akun aset"), ("account_id_accum_depr", "akumulasi penyusutan"),
                          ("account_id_depr_expense", "beban penyusutan")):
            add(code_of(a.get(fld)), "aset_tetap", f"Aset {a.get('asset_code') or a.get('code') or ''} {a.get('name') or ''}: {what}",
                f"rahaza_fixed_assets.{fld}", active=act, screen=_SCR_ASET, ref_id=a.get("id"))

    # 10. Anggaran (account_id)
    n_budget: dict = defaultdict(int)
    async for b in db.rahaza_budget_items.find({}, {"_id": 0, "account_id": 1, "account_code": 1}):
        c = code_of(b.get("account_id")) or code_of(b.get("account_code"))
        if c:
            n_budget[c] += 1
    for c, n in n_budget.items():
        add(c, "anggaran", f"{n} baris anggaran", "rahaza_budget_items.account_id", screen=_SCR_BUDGET)

    # 11. Konstanta & literal kode akun di program
    for b in constant_bindings():
        scr = _SCR_PROFIL if b.get("role") else None
        add(b["code"], b["kind"], b["label"], b["source"], screen=scr,
            detail=(f"peran profil {b['role'][0]}.{b['role'][1]}" if b.get("role") else ""))

    # 12. Baris jurnal posted & jurnal draft
    jq = {"account_code": {"$in": sorted(want)}} if want else {}
    for c, n in (await _count_by(db.rahaza_journal_lines, "account_code", jq)).items():
        add(c, "jurnal", f"{n} baris jurnal (posted)", "rahaza_journal_lines", screen=_SCR_GL, detail=str(n))
    drafts: dict = defaultdict(int)
    async for je in db.rahaza_journal_entries.find({"status": "draft"}, {"_id": 0, "lines": 1, "je_number": 1}):
        for c in {(ln or {}).get("account_code") for ln in (je.get("lines") or [])}:
            if c:
                drafts[c] += 1
    for c, n in drafts.items():
        add(c, "jurnal_draft", f"{n} jurnal draft", "rahaza_journal_entries(status=draft)", screen=_SCR_JURNAL, detail=str(n))

    # 13. Anak (struktur pohon)
    if want:
        kids = await db.rahaza_coa_accounts.find({"parent_code": {"$in": sorted(want)}},
                                                 {"_id": 0, "code": 1, "parent_code": 1, "active": 1}).to_list(20000)
    else:
        kids = accounts
    n_kids: dict = defaultdict(lambda: [0, 0])
    for k in kids:
        p = k.get("parent_code")
        if p and p != k.get("code"):
            n_kids[p][0] += 1
            n_kids[p][1] += 1 if k.get("active", True) is not False else 0
    for p, (n, n_act) in n_kids.items():
        add(p, "anak", f"{n} akun anak ({n_act} aktif)", "rahaza_coa_accounts.parent_code", active=n_act > 0,
            screen=_SCR_COA, detail=str(n))

    # 14. Penanda yang dibaca program, akun pendapatan toko, seed & grup wajib
    from core import finance_sync as _fs
    rev_groups = set(_fs.REVENUE_GROUP.values()) | {
        g for cfg in ets.values() for g in (cfg.get("parent_by_platform") or {}).values() if g}
    from data.coa_unified import DA_UNIFIED_ACCOUNTS, UNIFIED_GROUP_CODES
    from routes.rahaza_coa import SEED_TEMPLATE
    seed_codes = {c for c, *_ in SEED_TEMPLATE} | {r[0] for r in DA_UNIFIED_ACCOUNTS}
    for a in accounts:
        c, fl = a.get("code"), a.get("flags") or {}
        for f, lbl in FLAG_BINDINGS.items():
            if fl.get(f):
                add(c, "flag", lbl + (f" ({fl.get('channel')})" if f == "is_sales" and fl.get("channel") else ""),
                    f"flags.{f}")
        if fl.get("subledger_entity_type"):
            add(c, "subledger", f"Sub-ledger {fl['subledger_entity_type']} (relasi {str(fl.get('subledger_entity_id') or '')[:8]})",
                "flags.subledger_entity_type", screen=_SCR_AUTO, ref_id=fl.get("subledger_entity_id"))
        if not a.get("is_group") and (re.match(r"^4-11[123]\d$", c or "") or a.get("parent_code") in rev_groups):
            add(c, "sinkron_toko", "Akun pendapatan toko — sinkron toko menonaktifkan akun buatan sistem yang tidak "
                "dipakai toko mana pun", "core.finance_sync._sync_stores")
        if c in seed_codes:
            add(c, "seed", "Akun bawaan (dibuat ulang otomatis saat server menyala bila dihapus)",
                "rahaza_coa.SEED_TEMPLATE / data.coa_unified.DA_UNIFIED_ACCOUNTS")
        if c in UNIFIED_GROUP_CODES:
            add(c, "seed", "Akun header wajib (startup merapikannya sebagai grup bila belum diubah pengguna)",
                "data.coa_unified.UNIFIED_GROUP_CODES")
    return dict(out)


# ── Ringkasan & penjaga (murni) ───────────────────────────────────────────────
def summarize(bindings: list[dict]) -> dict:
    """{level, count, kinds, journal_lines, draft_entries, children} — lencana di layar."""
    bindings = bindings or []
    level = max((b["level"] for b in bindings), key=lambda x: LEVEL_RANK[x], default=BEBAS)
    nonseed = [b for b in bindings if b["kind"] != "seed"]
    num = lambda k: sum(int(b.get("detail") or 0) for b in bindings if b["kind"] == k)  # noqa: E731
    return {"level": level, "count": len(nonseed),
            "kinds": sorted({b["kind"] for b in bindings}),
            "journal_lines": num("jurnal"), "draft_entries": num("jurnal_draft"), "children": num("anak"),
            "labels": [b["label"] for b in nonseed[:5]]}


def _blocked_by(action: str, bindings: list[dict]) -> list[dict]:
    out = []
    for b in bindings or []:
        blocks = KINDS[b["kind"]]["blocks"]
        if not b.get("active", True):
            blocks = blocks & _INACTIVE_KEEPS
        if action in blocks:
            out.append(b)
    return out


def describe(bindings: list[dict], limit: int = 6) -> str:
    """Daftar keterikatan untuk pesan galat: "Profil Posting: A; B · Rekening Kas & Bank: C …"."""
    grp: dict = defaultdict(list)
    for b in bindings:
        grp[b["group_label"]].append(b["label"])
    parts = []
    for g, items in grp.items():
        more = f" (+{len(items) - limit} lagi)" if len(items) > limit else ""
        parts.append(f"{g}: " + "; ".join(items[:limit]) + more)
    return " · ".join(parts)


def screens_of(bindings: list[dict]) -> str:
    names = []
    for b in bindings:
        lbl = (b.get("screen") or {}).get("label")
        if lbl and lbl not in names:
            names.append(lbl)
    return ", ".join(names)


def check_action(acc: dict, action: str, bindings: list[dict]) -> list[str]:
    """Alasan aksi `action` DITOLAK untuk akun `acc` (kosong = boleh). Fungsi murni."""
    if action not in ACTIONS:
        raise ValueError(f"aksi '{action}' tidak dikenal")
    reasons = []
    if action == "deactivate" and acc.get("active", True) is False:
        return ["akun sudah nonaktif"]
    if action == "make_group" and acc.get("is_group"):
        return ["akun sudah berupa grup"]
    if action == "make_leaf" and not acc.get("is_group"):
        return ["akun sudah berupa akun rinci"]
    for b in _blocked_by(action, bindings):
        reasons.append(f"{b['group_label']}: {b['label']}")
    return reasons


def action_matrix(acc: dict, bindings: list[dict]) -> dict:
    """{aksi: {allowed, reasons}} untuk layar (tombol aksi + alasan kunci)."""
    out = {a: {"allowed": not (r := check_action(acc, a, bindings)), "reasons": r} for a in ACTIONS}
    out["reactivate"] = {"allowed": acc.get("active", True) is False,
                         "reasons": [] if acc.get("active", True) is False else ["akun sudah aktif"]}
    return out


def blocked_message(acc: dict, action: str, bindings: list[dict]) -> str | None:
    """Pesan Indonesia untuk aksi yang ditolak, menyebut keterikatan + layar perbaikannya."""
    bl = _blocked_by(action, bindings)
    if not bl:
        return None
    where = screens_of(bl)
    fix = f" Ubah dulu rujukannya di: {where}." if where else ""
    return (f"Akun {acc.get('code')} {acc.get('name') or ''} tidak bisa {ACTION_LABELS[action]} karena masih "
            f"terhubung — {describe(bl)}.{fix}").replace("  ", " ")


async def usage_for(db, acc: dict) -> dict:
    """Rincian lengkap satu akun (laci "Keterikatan akun")."""
    bl = (await collect_bindings(db, [acc["code"]])).get(acc["code"], [])
    groups: dict = {}
    for b in bl:
        g = groups.setdefault(b["kind"], {"kind": b["kind"], "label": b["group_label"], "level": b["level"], "items": []})
        g["items"].append(b)
    order = sorted(groups.values(), key=lambda g: (-LEVEL_RANK[g["level"]], g["label"]))
    return {"account": acc, "summary": summarize(bl), "groups": order, "actions": action_matrix(acc, bl),
            "level_label": LEVEL_LABELS[summarize(bl)["level"]]}


async def integrity_report(db) -> dict:
    """INV-COA-REF — rujukan konfigurasi → akun harus ADA, AKTIF, dan (untuk target posting) BUKAN grup.
    Juga: cadangan kode yang akan terpakai karena peran profilnya kosong, dan akun pendapatan toko yang
    dilewati sinkron (buatan/ubahan pengguna)."""
    accounts = await db.rahaza_coa_accounts.find({}, {"_id": 0}).to_list(20000)
    by_code = {a["code"]: a for a in accounts if a.get("code")}
    allb = await collect_bindings(db, accounts=accounts)
    dangling, inactive, group = [], [], []
    checked = 0
    for code, bl in sorted(allb.items()):
        cfg = [b for b in bl if b["kind"] in CONFIG_KINDS and b.get("active", True)]
        if not cfg:
            continue
        checked += len(cfg)
        refs = [f"{b['group_label']}: {b['label']}" for b in cfg][:8]
        screens = [b["screen"] for b in cfg if b.get("screen")][:3]
        acc = by_code.get(code)
        row = {"code": code, "name": (acc or {}).get("name"), "refs": refs, "screens": screens, "count": len(cfg)}
        if not acc:
            dangling.append(row)
        elif acc.get("active", True) is False:
            inactive.append(row)
        elif acc.get("is_group") and any(KINDS[b["kind"]]["postable"] for b in cfg):
            group.append({**row, "refs": [f"{b['group_label']}: {b['label']}" for b in cfg if KINDS[b["kind"]]["postable"]][:8]})
    # cadangan kode yang AKAN terpakai karena peran profilnya kosong
    profiles = {p.get("event_type"): (p.get("mapping") or {}) async for p in db.rahaza_posting_profiles.find({}, {"_id": 0})}
    fallback_warnings = []
    for b in constant_bindings():
        role = b.get("role")
        if not role or b["kind"] != "kode_cadangan":
            continue
        if not (profiles.get(role[0]) or {}).get(role[1]):
            fallback_warnings.append({"code": b["code"], "name": (by_code.get(b["code"]) or {}).get("name"),
                                      "role": f"{role[0]}.{role[1]}", "label": b["label"], "source": b["source"]})
    try:
        from core.finance_sync import store_revenue_deactivation_plan
        plan = await store_revenue_deactivation_plan(db)
        sync_skipped = plan.get("skipped") or []
    except Exception as e:  # noqa: BLE001
        log.warning("[coa_bindings] rencana sinkron toko gagal dibaca: %s", e)
        sync_skipped = []
    return {"ok": not (dangling or inactive or group), "checked_refs": checked,
            "dangling_refs": dangling, "inactive_targets": inactive, "group_targets": group,
            "fallback_warnings": fallback_warnings, "sync_skipped": sync_skipped,
            "accounts": len(accounts)}

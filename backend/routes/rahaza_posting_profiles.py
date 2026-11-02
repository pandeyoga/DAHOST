"""
PT Rahaza — Phase F2 Accounting Core
Posting Profiles — mapping event_type → CoA account codes.

Collection: rahaza_posting_profiles
  id, event_type (unique), active (bool),
  mapping { <role>: <account_code> },  e.g. {'debit_ar': '1-1301', 'credit_revenue': '4-1100'}
  description, updated_at, updated_by

Seed defaults (garment manufacturing, PSAK):
  ar_invoice        : Dr AR (1-1301), Cr Revenue (4-1100), Cr Tax Output (2-1400)
  ar_payment        : Dr Bank (1-1201), Cr AR (akun jurnal penerbitan invoice)
  ap_invoice        : Dr Expense (6-2900) / Inventory RM (1-1401) / GRNI (2-1150), Cr AP (2-1100), Dr Tax Input (1-1501)
  ap_payment        : Dr AP (akun jurnal penerbitan invoice), Cr Bank (1-1201)
  expense           : Dr Expense (6-2900), Cr Bank (1-1201)
  payroll_finalize  : Dr Salary Expense (6-2100), Cr Hutang Gaji (2-1200)
  inventory_receive : Dr Inventory RM (1-1401), Cr GRNI (2-1150)
  inventory_issue   : Dr WIP (1-1403), Cr Inventory RM (1-1401)
  inventory_adjust  : Dr/Cr Inventory (1-1401) vs Selisih Persediaan (5-1950) — 2026-11-02, owner No.19a
                      (2026-11-02, K13/No.26a: akun persediaan per jenis — bahan 1-1401 · aksesoris 1-1402 · FG 1-1404)
  cogs_shipment     : Dr COGS Material (5-1000), Dr COGS Labor (5-2000), Dr COGS Overhead (5-3000), Cr FG Inventory (1-1404)
"""
from fastapi import APIRouter, Request, HTTPException
from database import get_db
from auth import require_auth, serialize_doc, log_activity
import uuid
from datetime import datetime, timezone
from core.roles import FINANCE_ROLES  # FIN-02

router = APIRouter(prefix="/api/rahaza/posting-profiles", tags=["rahaza-posting-profiles"])


def _uid(): return str(uuid.uuid4())
def _now(): return datetime.now(timezone.utc)


async def _require_fin(request: Request):
    user = await require_auth(request)
    role = (user.get("role") or "").lower()
    if role in FINANCE_ROLES:  # FIN-02
        return user
    perms = user.get("_permissions") or []
    if "*" in perms or "finance.manage" in perms:
        return user
    raise HTTPException(403, "Forbidden: butuh permission finance.")


# ───────────────────────── SEED TEMPLATE ──────────────────────────────────────
# Each event_type maps role -> CoA code.
# `role` is a free-form key used by posting helpers when building JE lines.
DEFAULT_PROFILES = [
    # Skema akun KANONIK 4-digit (audit finance 2026-09-04). Tidak ada fallback kode
    # akun di posting engine — mapping yang hilang = posting ditolak dgn pesan jelas.
    {
        "event_type": "ar_invoice",
        "description": "AR Invoice sent → Dr AR / Cr Revenue (+Tax Output) (+Sales Discount)",
        "mapping": {
            "debit_ar": "1-1301",
            "credit_revenue": "4-1100",
            "credit_tax_output": "2-1400",
            "debit_sales_discount": "4-1300",
        },
    },
    {
        "event_type": "ar_payment",
        "description": "Pembayaran AR → Dr Bank / Cr AR (akun AR = akun jurnal penerbitan invoice)",
        "mapping": {
            "debit_cash_default": "1-1201",
            "credit_ar": "1-1301",
        },
    },
    {
        "event_type": "ap_invoice",
        "description": "AP Invoice → Dr Beban/Persediaan/GRNI / Cr AP (+Tax Input)",
        "mapping": {
            "debit_expense_default": "6-2900",
            "debit_inventory_rm": "1-1401",
            "debit_grni": "2-1150",
            "debit_price_variance": "5-1900",
            "debit_tax_input": "1-1501",
            "credit_ap": "2-1100",
        },
    },
    {
        "event_type": "ap_payment",
        "description": "Pembayaran AP → Dr AP / Cr Bank (akun AP = akun jurnal penerbitan invoice)",
        "mapping": {
            "debit_ap": "2-1100",
            "credit_cash_default": "1-1201",
            "credit_purchase_discount": "4-2300",
        },
    },
    {
        "event_type": "expense",
        "description": "Expense operasional → Dr Expense / Cr Bank",
        "mapping": {
            "debit_expense_default": "6-2900",
            "credit_cash_default": "1-1201",
        },
    },
    {
        "event_type": "payroll_finalize",
        "description": "Payroll finalize → Dr Gaji Expense / Cr Hutang Gaji",
        "mapping": {
            "debit_salary_expense": "6-2100",
            "credit_salary_payable": "2-1200",
            "credit_tax_pph21": "2-1301",
            # Cadangan lama: dipakai bila peran per lembaga di bawah dikosongkan Finance.
            "credit_bpjs_payable": "2-1500",
            # 2026-11-02 (K22): hutang BPJS dipisah per LEMBAGA (potongan karyawan + iuran perusahaan)
            "credit_bpjs_kes_payable": "2-1501",
            "credit_bpjs_tk_payable": "2-1502",
            # 2026-11-02 (K22): beban iuran perusahaan — dipakai hanya bila saklar owner menyala
            "debit_bpjs_kes_employer_expense": "6-3200",
            "debit_bpjs_tk_employer_expense": "6-3300",
            # 2026-11-02 (K38, sementara): potongan penyesuaian manual — kini TAMPIL & bisa diubah
            # di layar Profil Posting (dulu peran opsional tersembunyi, cadangan kode 4-9000).
            "credit_other_deduction": "4-9000",
        },
    },
    {
        "event_type": "payroll_payment",
        "description": "Pembayaran gaji → Dr Hutang Gaji / Cr Bank",
        "mapping": {
            "debit_salary_payable":  "2-1200",
            "credit_bank_default":   "1-1201",
        },
    },
    {
        "event_type": "inventory_receive",
        "description": "Penerimaan bahan (GR) → Dr Persediaan / Cr Hutang Belum Ditagih (GRNI)",
        "mapping": {
            "debit_inventory_rm": "1-1401",
            # 2026-11-02 (K13): penerimaan AKSESORIS → 1-1402 (akun persediaan mengikuti jenis barang)
            "debit_inventory_accessory": "1-1402",
            "credit_ap_clearing": "2-1150",
        },
    },
    {
        "event_type": "inventory_issue",
        "description": "Material issue ke WO → Dr WIP / Cr Inventory RM",
        "mapping": {
            "debit_wip": "1-1403",
            "credit_inventory_rm": "1-1401",
            # 2026-11-02 (K13): pemakaian AKSESORIS (MI / kartu stok aksesoris) mengkredit 1-1402
            "credit_inventory_accessory": "1-1402",
            # 2026-11-02 (K14/P-7): aksesoris milik DA untuk pesanan MAKLON = biaya proyek maklon DA
            # (barang jadi maklon di luar neraca DA → tidak lewat WIP/FG)
            "debit_maklon_material": "5-4100",
        },
    },
    {
        "event_type": "inventory_adjust",
        "description": "Penyesuaian/opname/lepas karantina → Dr/Cr Persediaan vs Selisih Persediaan",
        "mapping": {
            "inventory_rm": "1-1401",
            # 2026-11-02 (K13 + owner No.26a): akun persediaan mengikuti JENIS barang yang disesuaikan
            "inventory_accessory": "1-1402",
            "inventory_fg": "1-1404",
            # 2026-11-02 (owner No.19a): dulu 6-2400 ATK & Supplies → beban ATK bisa minus karena opname.
            "adjustment_expense": "5-1950",
        },
    },
    {
        "event_type": "cogs_shipment",
        "description": "Shipment dispatched → Dr COGS / Cr FG Inventory (berdasarkan HPP snapshot)",
        "mapping": {
            "debit_cogs_material": "5-1000",
            "debit_cogs_labor": "5-2000",
            "debit_cogs_overhead": "5-3500",
            "credit_fg_inventory": "1-1404",
        },
    },
    {
        "event_type": "maklon_ar_invoice",
        "description": "Maklon AR Invoice → Dr AR Piutang / Cr Pendapatan Jasa Maklon",
        "mapping": {
            "debit_ar": "1-1301",
            "credit_revenue_maklon": "4-1100",
            "credit_tax_output": "2-1400",
        },
    },
    {
        "event_type": "cmt_ap_invoice",
        "description": "CMT Vendor AP Invoice → Dr Biaya Vendor CMT / Cr AP Vendor",
        "mapping": {
            # C-03 absorption: upah jahit PO INTERNAL dikapitalisasi ke WIP (bukan langsung COGS);
            # COGS lahir saat dispatch dari lapisan FG (bahan+jahit+overhead) — tidak dobel.
            "debit_cmt_wip_internal": "1-1403",
            "debit_cmt_expense_internal": "5-2200",  # dipakai HANYA bila debit_cmt_wip_internal kosong
            "debit_cmt_expense_maklon": "5-4200",    # Biaya Vendor CMT – Maklon (biaya proyek klien)
            "credit_ap": "2-1100",
            "debit_penalty_income": "4-9000",
        },
    },
    {
        "event_type": "maklon_advance_payment",
        "description": "DP Maklon dari klien → Dr Bank / Cr Uang Muka Diterima – Maklon",
        "mapping": {
            "debit_cash_default": "1-1201",
            "credit_advance_customer": "2-1700",
        },
    },
    {
        "event_type": "cash_opening_balance",
        "description": "Saldo awal rekening kas/bank → Dr Bank / Cr Modal (agar saldo kartu kas = GL)",
        "mapping": {
            "debit_cash_default": "1-1201",
            "credit_opening_equity": "3-1000",
        },
    },
    {
        "event_type": "cogs_marketplace_return",
        "description": "Retur marketplace masuk gudang (kondisi baik) → Dr FG / Cr HPP",
        "mapping": {
            "debit_fg_inventory": "1-1404",
            "credit_cogs": "5-1000",
        },
    },
    {
        "event_type": "return_damaged_loss",
        "description": "Retur kondisi rusak masuk karantina → Dr Kerugian Retur Rusak / Cr HPP (reklas, persediaan karantina nilai 0)",
        "mapping": {
            "debit_return_loss": "6-1300",
            "credit_cogs": "5-1000",
        },
    },
    {
        "event_type": "wip_to_fg_on_wo_complete",
        "description": "WO selesai: pindah nilai WIP ke Barang Jadi → Dr FG / Cr WIP",
        "mapping": {
            "debit_fg_inventory": "1-1404",
            "credit_wip":         "1-1403",
        },
    },
    {
        "event_type": "petty_cash_expense",
        "description": "Pengeluaran kas kecil → Dr Biaya / Cr Kas Kecil",
        "mapping": {
            # 2026-11-02 (K26): TIDAK lagi dipakai sebagai beban otomatis pengeluaran kas kecil
            # (akun dari pemetaan kategori, atau wajib dipilih). Tetap dipakai untuk 'return' uang muka
            # LAMA yang dulu langsung dibebankan ke akun ini.
            "debit_expense_default": "6-2400",
            "credit_petty_cash":     "1-1101",
            # 2026-11-02 (K26): uang muka kas kecil atas nama karyawan
            "debit_employee_advance": "1-1610",
        },
    },
    {
        "event_type": "petty_cash_replenish",
        "description": "Pengisian ulang kas kecil dari bank → Dr Kas Kecil / Cr Bank",
        "mapping": {
            "debit_petty_cash":   "1-1101",
            "credit_bank_default": "1-1201",
        },
    },
    {
        "event_type": "bank_transfer",
        "description": "Transfer antar rekening bank → Dr Bank Tujuan / Cr Bank Sumber",
        "mapping": {
            "debit_bank_target":  "1-1202",
            "credit_bank_source": "1-1201",
        },
    },
    {
        "event_type": "credit_note",
        "description": "Credit note untuk retur → Dr Retur Penjualan / Cr AR (akun AR pelanggan/channel)",
        "mapping": {
            "debit_revenue":  "4-1200",
            "credit_ar":      "1-1301",
        },
    },
    {
        "event_type": "variance_overproduction",
        "description": "Overproduction variance → Dr FG Inventory / Cr Variance Income",
        "mapping": {
            "debit_inventory_fg":     "1-1404",
            "credit_variance_income": "4-9000",
        },
    },
    {
        "event_type": "variance_underproduction",
        "description": "Underproduction variance → Dr Variance Loss / Cr WIP",
        "mapping": {
            "debit_variance_loss": "6-4100",
            "credit_wip":          "1-1403",
        },
    },
    {
        "event_type": "asset_acquisition",
        "description": "Asset acquisition from GRN → Dr Fixed Asset / Cr GRNI",
        "mapping": {
            "debit_fixed_asset":  "1-2500",
            "credit_ap_clearing": "2-1150",
        },
    },
    {
        "event_type": "depreciation",
        "description": "Monthly depreciation → Dr Depreciation Expense / Cr Accumulated Depreciation",
        "mapping": {
            "debit_depr_expense":  "6-2700",
            "credit_accum_depr":   "1-2501",
        },
    },
    {
        "event_type": "accrual",
        "description": "Period-end accrual → Dr Expense / Cr Accrued Expenses",
        "mapping": {
            "debit_expense":   "6-2900",
            "credit_accrued":  "2-1600",
        },
    },
    {
        "event_type": "accrual_reversal",
        "description": "Accrual reversal (next period) → Dr Accrued Expenses / Cr Expense",
        "mapping": {
            "debit_accrued":   "2-1600",
            "credit_expense":  "6-2900",
        },
    },
    {
        "event_type": "bad_debt_writeoff",
        "description": "Bad debt write-off → Dr Bad Debt Expense / Cr AR (akun AR invoice asal)",
        "mapping": {
            "debit_bad_debt_expense": "6-4400",
            "credit_ar":              "1-1301",
        },
    },
    {
        "event_type": "bank_recon_charge",
        "description": "Bank charges adjustment → Dr Bank Charges / Cr Bank",
        "mapping": {
            "debit_bank_charges": "6-4100",
            "credit_bank":        "1-1201",
        },
    },
    {
        "event_type": "bank_recon_interest",
        "description": "Bank interest income → Dr Bank / Cr Interest Income",
        "mapping": {
            "debit_bank":             "1-1201",
            "credit_interest_income": "4-2100",
        },
    },
    {
        "event_type": "bank_recon_service_fee",
        "description": "Bank service fee → Dr Service Fee / Cr Bank",
        "mapping": {
            "debit_service_fee": "6-4101",
            "credit_bank":       "1-1201",
        },
    },
    {
        "event_type": "asset_disposal",
        "description": "Asset disposal (3-way: Dr Accum Depr + Dr Cash + Dr/Cr Gain/Loss, Cr Asset)",
        "mapping": {
            "credit_fixed_asset":       "1-2500",
            "debit_accum_depr":         "1-2501",
            "debit_cash":               "1-1201",
            "debit_loss_on_disposal":   "6-4200",
            "credit_gain_on_disposal":  "4-2200",
        },
    },
    {
        "event_type": "employee_loan_disbursement",
        "description": "Employee loan disbursement → Dr Employee Loan Receivable / Cr Bank",
        "mapping": {
            "debit_employee_loan_receivable": "1-1320",
            "credit_cash":                    "1-1201",
        },
    },
    {
        "event_type": "employee_loan_repayment_payroll",
        "description": "Employee loan repayment via payroll → Dr Salary Payable / Cr Employee Loan Receivable",
        "mapping": {
            "debit_salary_payable":             "2-1200",
            "credit_employee_loan_receivable":  "1-1320",
        },
    },
    {
        "event_type": "employee_loan_repayment_manual",
        "description": "Pelunasan kasbon manual → Dr Bank / Cr Employee Loan Receivable",
        "mapping": {
            "debit_bank":                       "1-1201",
            "credit_employee_loan_receivable":  "1-1320",
        },
    },
    {
        "event_type": "inventory_scrap",
        "description": "Material scrap/waste → Dr Scrap Expense / Cr Inventory RM",
        "mapping": {
            "debit_scrap_expense":   "6-4300",
            "credit_inventory_rm":   "1-1401",
            # 2026-11-02 (K13 + owner No.26a): scrap aksesoris → 1-1402, scrap barang jadi → 1-1404
            "credit_inventory_accessory": "1-1402",
            "credit_inventory_fg":   "1-1404",
        },
    },
    {
        # 2026-11-02 (K41 = a): "Keluarkan Stok FG" dijurnal senilai WAC, Cr 1-1404 (cogs_shipment)
        "event_type": "fg_issue",
        "description": "Keluarkan Stok FG (non-penjualan) → Dr akun per alasan / Cr Persediaan Barang Jadi (WAC)",
        "mapping": {
            "debit_sample": "6-1130",     # Biaya Pemasaran Lain-lain (sampel / promosi)
            "debit_internal": "5-1000",   # HPP — keperluan internal / SJ internal / lainnya
        },
    },
    # 2026-11-02 (S2-H, permintaan owner "tandai mana yang terhubung"): akun yang dulu HANYA terikat lewat
    # kode yang ditulis langsung di program kini tampil sebagai peran profil, bawaan = kode program saat
    # ini (dijaga uji: nilai bawaan == konstanta modulnya, lihat core/coa_bindings.CONSTANT_SOURCES).
    # Modul konsumennya membaca peran ini lewat `role_code()` — sampai itu terpasang, layar Profil Posting
    # menandai peran ini "masih dibaca dari kode program".
    {
        "event_type": "marketplace_settlement",
        "description": "Pencairan dana marketplace (jurnal draft) → potongan & penyesuaian dari laporan dana dilepas",
        "mapping": {
            "debit_returns":       "4-1200",
            "debit_discount":      "4-1300",
            "debit_platform_fee":  "4-1400",
            "debit_ads_default":   "6-1130",
            "debit_ads_shopee":    "6-1112",
            "debit_ads_tiktok":    "6-1110",
            "debit_ads_tokopedia": "6-1113",
            "credit_other_income": "7-4000",
            "debit_other_expense": "6-2900",
        },
    },
    {
        "event_type": "employee_travel",
        "description": "Perjalanan dinas → Dr Uang Muka Karyawan / Cr Bank; penyelesaian Dr Beban Dinas / Cr Uang Muka",
        "mapping": {
            "debit_employee_advance": "1-1610",
            "debit_travel_expense":   "6-3400",
            "credit_bank_default":    "1-1201",
        },
    },
    {
        "event_type": "year_end_close",
        "description": "Tutup buku tahunan → saldo laba/rugi dipindah ke Laba Ditahan",
        "mapping": {
            "credit_retained_earnings": "3-2000",
        },
    },
    {
        "event_type": "subledger_opening_balance",
        "description": "Saldo awal go-live → akun kontrol rincian piutang/hutang + penyeimbang Laba Ditahan",
        "mapping": {
            "credit_retained_earnings_balancing": "3-2000",
            "control_ar_customer": "1-1301",
            "control_ar_maklon":   "1-1305",
            "control_ap_supplier": "2-1100",
            "control_ap_cmt":      "2-1110",
        },
    },
]

# ── Label manusiawi (SATU sumber; dipakai layar Profil Posting & laci keterikatan Bagan Akun) ──
# 2026-11-02 (S2-H): dulu label hanya ada di layar (10 dari 37 event, 26 peran) → sisanya tampil
# sebagai kunci teknis. Kini disajikan backend lewat GET /api/rahaza/posting-profiles/meta.
EVENT_LABELS = {
    "ar_invoice": "Faktur penjualan (AR)",
    "ar_payment": "Penerimaan pembayaran piutang",
    "ap_invoice": "Faktur pemasok (AP)",
    "ap_payment": "Pembayaran hutang pemasok",
    "expense": "Beban operasional",
    "payroll_finalize": "Finalisasi payroll",
    "payroll_payment": "Pembayaran gaji",
    "inventory_receive": "Penerimaan bahan (GR)",
    "inventory_issue": "Pengeluaran bahan ke produksi",
    "inventory_adjust": "Penyesuaian / opname persediaan",
    "cogs_shipment": "HPP pengiriman barang jadi",
    "maklon_ar_invoice": "Faktur maklon",
    "cmt_ap_invoice": "Tagihan vendor CMT",
    "maklon_advance_payment": "Uang muka (DP) klien maklon",
    "cash_opening_balance": "Saldo awal rekening kas/bank",
    "cogs_marketplace_return": "Retur marketplace kondisi baik",
    "return_damaged_loss": "Retur kondisi rusak",
    "wip_to_fg_on_wo_complete": "WIP ke barang jadi (WO selesai)",
    "petty_cash_expense": "Pengeluaran kas kecil",
    "petty_cash_replenish": "Pengisian kas kecil",
    "bank_transfer": "Transfer antar rekening",
    "credit_note": "Nota kredit (retur penjualan)",
    "variance_overproduction": "Selisih produksi lebih",
    "variance_underproduction": "Selisih produksi kurang",
    "asset_acquisition": "Perolehan aset tetap",
    "depreciation": "Penyusutan bulanan",
    "accrual": "Akrual akhir periode",
    "accrual_reversal": "Pembalikan akrual",
    "bad_debt_writeoff": "Penghapusan piutang tak tertagih",
    "bank_recon_charge": "Rekonsiliasi bank: biaya bank",
    "bank_recon_interest": "Rekonsiliasi bank: bunga",
    "bank_recon_service_fee": "Rekonsiliasi bank: biaya layanan",
    "asset_disposal": "Pelepasan aset tetap",
    "employee_loan_disbursement": "Pencairan kasbon karyawan",
    "employee_loan_repayment_payroll": "Cicilan kasbon lewat payroll",
    "employee_loan_repayment_manual": "Pelunasan kasbon manual",
    "inventory_scrap": "Scrap / bahan rusak",
    "marketplace_settlement": "Pencairan dana marketplace",
    "employee_travel": "Perjalanan dinas",
    "year_end_close": "Tutup buku tahunan",
    "subledger_opening_balance": "Saldo awal go-live (rincian piutang/hutang)",
    "fg_issue": "Keluarkan Stok FG (sampel / internal / lainnya)",
}
ROLE_LABELS = {
    "debit_ar": "Piutang (Dr)", "credit_ar": "Piutang (Cr)",
    "credit_revenue": "Pendapatan (Cr)", "credit_revenue_maklon": "Pendapatan maklon (Cr)",
    "credit_tax_output": "PPN keluaran (Cr)", "debit_tax_input": "PPN masukan (Dr)",
    "debit_sales_discount": "Diskon penjualan (Dr)",
    "debit_cash_default": "Kas/bank bawaan (Dr)", "credit_cash_default": "Kas/bank bawaan (Cr)",
    "debit_cash": "Kas/bank (Dr)", "credit_cash": "Kas/bank (Cr)",
    "debit_bank": "Bank (Dr)", "credit_bank": "Bank (Cr)", "credit_bank_default": "Bank bawaan (Cr)",
    "debit_bank_target": "Bank tujuan (Dr)", "credit_bank_source": "Bank sumber (Cr)",
    "debit_expense_default": "Beban bawaan (Dr)", "debit_expense": "Beban (Dr)", "credit_expense": "Beban (Cr)",
    "debit_inventory_rm": "Persediaan bahan baku (Dr)", "credit_inventory_rm": "Persediaan bahan baku (Cr)",
    "inventory_rm": "Persediaan bahan baku", "adjustment_expense": "Selisih persediaan",
    # 2026-11-02 (K13 + owner No.26a): akun persediaan per jenis barang
    "debit_inventory_accessory": "Persediaan aksesoris (Dr)", "credit_inventory_accessory": "Persediaan aksesoris (Cr)",
    "inventory_accessory": "Persediaan aksesoris", "inventory_fg": "Persediaan barang jadi",
    "credit_inventory_fg": "Persediaan barang jadi (Cr)",
    "debit_maklon_material": "Aksesoris DA untuk pesanan maklon → biaya proyek maklon (Dr)",
    # 2026-11-02 (K41 = a): Keluarkan Stok FG
    "debit_sample": "Sampel / promosi barang jadi → beban promosi (Dr)",
    "debit_internal": "Keperluan internal / SJ internal / lainnya → HPP (Dr)",
    "debit_grni": "Hutang belum ditagih / GRNI (Dr)", "credit_ap_clearing": "Hutang belum ditagih / GRNI (Cr)",
    "debit_price_variance": "Selisih harga pembelian (Dr)",
    "credit_ap": "Hutang usaha (Cr)", "debit_ap": "Hutang usaha (Dr)",
    "credit_purchase_discount": "Potongan pembelian (Cr)",
    "debit_salary_expense": "Beban gaji (Dr)", "credit_salary_payable": "Hutang gaji (Cr)",
    "debit_salary_payable": "Hutang gaji (Dr)", "credit_tax_pph21": "Hutang PPh 21 (Cr)",
    "credit_bpjs_payable": "Hutang BPJS gabungan — cadangan (Cr)",
    "credit_bpjs_kes_payable": "Hutang BPJS Kesehatan (Cr)", "credit_bpjs_tk_payable": "Hutang BPJS Ketenagakerjaan (Cr)",
    "debit_bpjs_kes_employer_expense": "Beban iuran BPJS Kesehatan perusahaan (Dr)",
    "debit_bpjs_tk_employer_expense": "Beban iuran BPJS Ketenagakerjaan perusahaan (Dr)",
    "credit_other_deduction": "Potongan penyesuaian manual payroll (Cr)",
    "debit_wip": "Persediaan WIP (Dr)", "credit_wip": "Persediaan WIP (Cr)",
    "debit_cogs_material": "HPP bahan (Dr)", "debit_cogs_labor": "HPP tenaga kerja (Dr)",
    "debit_cogs_overhead": "HPP overhead (Dr)", "credit_cogs": "HPP (Cr)",
    "credit_fg_inventory": "Persediaan barang jadi (Cr)", "debit_fg_inventory": "Persediaan barang jadi (Dr)",
    "debit_inventory_fg": "Persediaan barang jadi (Dr)",
    "debit_cmt_wip_internal": "Upah jahit PO internal → WIP (Dr)",
    "debit_cmt_expense_internal": "Biaya jahit internal (Dr, bila WIP kosong)",
    "debit_cmt_expense_maklon": "Biaya vendor CMT maklon (Dr)", "debit_penalty_income": "Denda vendor (Cr)",
    "credit_advance_customer": "Uang muka diterima maklon (Cr)", "credit_opening_equity": "Modal saldo awal (Cr)",
    "debit_return_loss": "Kerugian retur rusak (Dr)",
    "credit_petty_cash": "Kas kecil (Cr)", "debit_petty_cash": "Kas kecil (Dr)",
    "debit_employee_advance": "Uang muka karyawan (Dr)",
    "debit_revenue": "Retur penjualan (Dr)",
    "credit_variance_income": "Pendapatan selisih produksi (Cr)", "debit_variance_loss": "Kerugian selisih produksi (Dr)",
    "debit_fixed_asset": "Aset tetap (Dr)", "credit_fixed_asset": "Aset tetap (Cr)",
    "debit_depr_expense": "Beban penyusutan (Dr)", "credit_accum_depr": "Akumulasi penyusutan (Cr)",
    "debit_accum_depr": "Akumulasi penyusutan (Dr)",
    "debit_loss_on_disposal": "Rugi pelepasan aset (Dr)", "credit_gain_on_disposal": "Laba pelepasan aset (Cr)",
    "credit_accrued": "Beban akrual (Cr)", "debit_accrued": "Beban akrual (Dr)",
    "debit_bad_debt_expense": "Beban piutang tak tertagih (Dr)",
    "debit_bank_charges": "Biaya bank (Dr)", "credit_interest_income": "Pendapatan bunga (Cr)",
    "debit_service_fee": "Biaya layanan bank (Dr)",
    "debit_employee_loan_receivable": "Piutang kasbon karyawan (Dr)",
    "credit_employee_loan_receivable": "Piutang kasbon karyawan (Cr)",
    "debit_scrap_expense": "Beban scrap (Dr)",
    "debit_returns": "Retur penjualan (Dr)", "debit_discount": "Diskon penjual (Dr)",
    "debit_platform_fee": "Potongan / fee platform (Dr)", "debit_ads_default": "Iklan — bawaan (Dr)",
    "debit_ads_shopee": "Iklan Shopee (Dr)", "debit_ads_tiktok": "Iklan TikTok (Dr)",
    "debit_ads_tokopedia": "Iklan Tokopedia (Dr)", "credit_other_income": "Pendapatan lain / subsidi ongkir (Cr)",
    "debit_other_expense": "Potongan lain (Dr)",
    "debit_travel_expense": "Beban perjalanan dinas (Dr)",
    "credit_retained_earnings": "Laba ditahan", "credit_retained_earnings_balancing": "Penyeimbang laba ditahan",
    "control_ar_customer": "Kontrol piutang pelanggan", "control_ar_maklon": "Kontrol piutang maklon",
    "control_ap_supplier": "Kontrol hutang pemasok", "control_ap_cmt": "Kontrol hutang vendor CMT",
}
# Peran yang maknanya khusus di satu event
ROLE_LABELS_BY_EVENT = {
    ("petty_cash_expense", "debit_expense_default"): "Beban kas kecil transaksi lama (Dr) — cadangan",
    ("petty_cash_expense", "debit_employee_advance"): "Uang muka kas kecil atas nama karyawan (Dr)",
    ("employee_travel", "debit_employee_advance"): "Uang muka dinas karyawan (Dr saat bayar, Cr saat selesai)",
    ("employee_travel", "credit_bank_default"): "Rekening bayar uang muka dinas — cadangan (Cr)",
    ("payroll_finalize", "credit_bpjs_payable"): "Hutang BPJS gabungan — cadangan bila per lembaga kosong (Cr)",
}


def event_label(event_type: str) -> str:
    return EVENT_LABELS.get(event_type) or (event_type or "").replace("_", " ")


def role_label(role: str, event_type: str | None = None) -> str:
    return (ROLE_LABELS_BY_EVENT.get((event_type, role)) or ROLE_LABELS.get(role)
            or (role or "").replace("_", " "))

# Perbaikan WAJIB pada profil yang sudah tersimpan di DB (idempoten):
# (event_type, role) → kode kanonik. Dipakai upgrade_posting_profiles().
PROFILE_CODE_FIXES = {
    ("asset_disposal", "credit_fixed_asset"): "1-2500",      # C-05: dulu 1-1501 PPN Masukan
    ("asset_disposal", "debit_accum_depr"): "1-2501",        # C-05: dulu 1-1502 PPh dibayar dimuka
    ("inventory_receive", "credit_ap_clearing"): "2-1150",   # C-02: GRNI
    ("asset_acquisition", "credit_ap_clearing"): "2-1150",
    ("ar_invoice", "debit_sales_discount"): "4-1300",        # H-10: dulu 6-1100 Iklan
    ("credit_note", "debit_revenue"): "4-1200",              # H-10: Retur Penjualan
    ("ap_invoice", "debit_expense_default"): "6-2900",       # C-02: dulu 6-2200 Listrik & Air
    ("expense", "debit_expense_default"): "6-2900",
    ("bad_debt_writeoff", "debit_bad_debt_expense"): "6-4400",
    ("cmt_ap_invoice", "debit_penalty_income"): "4-9000",
    ("variance_overproduction", "credit_variance_income"): "4-9000",
    ("bank_recon_interest", "credit_interest_income"): "4-2100",
    ("cogs_shipment", "debit_cogs_overhead"): "5-3500",
    ("cmt_ap_invoice", "debit_cmt_wip_internal"): "1-1403",   # C-03 absorption
    # Iter 121 (B-04/M-06): default kas pembayaran tanpa rekening = Bank, bukan Kas Kecil
    ("ar_payment", "debit_cash_default"): "1-1201",
    ("ap_payment", "credit_cash_default"): "1-1201",
    ("expense", "credit_cash_default"): "1-1201",
    ("employee_loan_disbursement", "credit_cash"): "1-1201",
    ("asset_disposal", "debit_cash"): "1-1201",
    ("inventory_adjust", "adjustment_expense"): "5-1950",    # 2026-11-02 owner No.19a: dulu 6-2400 ATK
    # 2026-11-02 (S2-H): beban kas kecil lama pernah 6-2200 Listrik & Air (keliru) — pulihkan ke 6-2400
    ("petty_cash_expense", "debit_expense_default"): "6-2400",
}

# 2026-11-02 (audit No.47): PROFILE_CODE_FIXES dulu DITIMPA setiap startup → pilihan Finance kembali
# ke bawaan tiap restart. Kini perbaikan hanya dipasang bila (a) peran belum ada, (b) nilainya
# masih nilai LAMA yang diketahui salah (daftar di bawah, dari catatan C-02/C-05/H-10/B-04), atau
# (c) profilnya belum pernah disentuh pengguna. Peran yang diubah/dihapus pengguna lewat layar
# Profil Posting dicatat (`user_roles` / `user_removed_roles`) dan tidak pernah disentuh startup.
PROFILE_KNOWN_OLD_CODES = {
    ("asset_disposal", "credit_fixed_asset"): {"1-1501"},
    ("asset_disposal", "debit_accum_depr"): {"1-1502"},
    ("ar_invoice", "debit_sales_discount"): {"6-1100"},
    ("ap_invoice", "debit_expense_default"): {"6-2200"},
    ("ar_payment", "debit_cash_default"): {"1-1101"},
    ("ap_payment", "credit_cash_default"): {"1-1101"},
    ("expense", "credit_cash_default"): {"1-1101"},
    ("employee_loan_disbursement", "credit_cash"): {"1-1101"},
    ("asset_disposal", "debit_cash"): {"1-1101"},
    ("inventory_adjust", "adjustment_expense"): {"6-2400"},
    ("petty_cash_expense", "debit_expense_default"): {"6-2200"},
}
SYSTEM_UPDATERS = {None, "", "system", "coa-canonical-migration"}


def profile_untouched(doc: dict) -> bool:
    return (not (doc.get("user_roles") or doc.get("user_removed_roles"))
            and doc.get("updated_by") in SYSTEM_UPDATERS)


def upgrade_profile_mapping(et: str, mapping: dict, doc: dict, default_mapping: dict) -> dict:
    """Murni (tanpa DB): peta baru satu profil saat startup. `mapping` sudah di-remap legacy."""
    new_map = dict(mapping)
    user_roles = set(doc.get("user_roles") or [])
    user_removed = set(doc.get("user_removed_roles") or [])
    untouched = profile_untouched(doc)
    for (fet, role), code in PROFILE_CODE_FIXES.items():
        if fet != et or role in user_roles or role in user_removed:
            continue
        cur = new_map.get(role)
        if cur is None or untouched or cur in PROFILE_KNOWN_OLD_CODES.get((fet, role), ()):
            new_map[role] = code
    for role, code in (default_mapping or {}).items():
        if role not in user_removed:
            new_map.setdefault(role, code)
    return new_map
# Kunci role legacy (dewi_kasbon) → kunci kanonik
PROFILE_ROLE_RENAMES = {
    "employee_loan_disbursement": {"debit_loan_receivable": "debit_employee_loan_receivable"},
    "employee_loan_repayment_payroll": {"credit_loan_receivable": "credit_employee_loan_receivable"},
    "employee_loan_repayment_manual": {"credit_loan_receivable": "credit_employee_loan_receivable"},
}


async def upgrade_posting_profiles(db) -> dict:
    """Idempoten: remap kode legacy 3-digit → 4-digit, terapkan PROFILE_CODE_FIXES,
    tambahkan role yang hilang dari DEFAULT_PROFILES, insert profil yang belum ada."""
    from routes.rahaza_coa import LEGACY_CODE_MAP
    defaults = {p["event_type"]: p for p in DEFAULT_PROFILES}
    changed = []
    inserted = (await seed_posting_profiles(db))["inserted"]
    async for doc in db.rahaza_posting_profiles.find({}, {"_id": 0}):
        et = doc["event_type"]
        mapping = dict(doc.get("mapping") or {})
        new_map = {}
        renames = PROFILE_ROLE_RENAMES.get(et, {})
        for role, code in mapping.items():
            role = renames.get(role, role)
            code = LEGACY_CODE_MAP.get(code, code)
            new_map[role] = code
        new_map = upgrade_profile_mapping(et, new_map, doc, defaults.get(et, {}).get("mapping") or {})
        if new_map != mapping:
            await db.rahaza_posting_profiles.update_one(
                {"event_type": et},
                {"$set": {"mapping": new_map, "updated_at": _now(), "updated_by": "coa-canonical-migration"}})
            changed.append(et)
    return {"inserted": inserted, "updated": changed}


# ───────────────────────── ENDPOINTS ──────────────────────────────────────────
@router.get("")
async def list_profiles(request: Request):
    await require_auth(request)
    db = get_db()
    rows = await db.rahaza_posting_profiles.find({}, {"_id": 0}).sort("event_type", 1).to_list(500)
    return serialize_doc(rows)


@router.get("/meta")
async def profiles_meta(request: Request):
    """2026-11-02 (S2-H): label manusiawi event & peran + peran yang nilainya masih dibaca modul sebagai
    kode program (`consumers[*].reads_profile=False`) — layar Profil Posting menandainya."""
    await require_auth(request)
    from core.coa_bindings import role_consumers
    return {"events": EVENT_LABELS, "roles": ROLE_LABELS,
            "roles_by_event": {f"{e}.{r}": lbl for (e, r), lbl in ROLE_LABELS_BY_EVENT.items()},
            "consumers": role_consumers(),
            "defaults": {p["event_type"]: p["mapping"] for p in DEFAULT_PROFILES}}


@router.get("/{event_type}")
async def get_profile(event_type: str, request: Request):
    await require_auth(request)
    db = get_db()
    doc = await db.rahaza_posting_profiles.find_one({"event_type": event_type}, {"_id": 0})
    if not doc:
        raise HTTPException(404, f"Posting profile '{event_type}' tidak ditemukan.")
    return serialize_doc(doc)


@router.put("/{event_type}")
async def update_profile(event_type: str, request: Request):
    user = await _require_fin(request)
    db = get_db()
    body = await request.json()
    doc = await db.rahaza_posting_profiles.find_one({"event_type": event_type})
    if not doc:
        raise HTTPException(404, f"Posting profile '{event_type}' tidak ditemukan. Jalankan seed dulu.")
    upd = {"updated_at": _now(), "updated_by": user["id"], "updated_by_name": user.get("name", "")}
    if "mapping" in body and isinstance(body["mapping"], dict):
        # validate each account_code exists + leaf + active (warning but not blocker if missing)
        mapping = body["mapping"]
        clean = {}
        # Batch fetch all referenced CoA accounts in one query
        codes = [str(c).strip() for c in mapping.values() if c]
        coa_map = {}
        if codes:
            async for d in db.rahaza_coa_accounts.find({"code": {"$in": codes}}, {"_id": 0}):
                coa_map[d["code"]] = d
        # 2026-11-02 (S2-H): SEMUA peran bermasalah dilaporkan sekaligus, dengan label manusiawi + kunci
        # peran dalam [..] supaya layar menandai baris yang tepat (dulu hanya yang pertama, kunci teknis).
        problems = []
        for role, code in mapping.items():
            if not code:
                continue
            code = str(code).strip()
            acc = coa_map.get(code)
            who = f"Peran «{role_label(role, event_type)}» [{role}]"
            if not acc:
                problems.append(f"{who}: akun {code} tidak ada di Bagan Akun")
            elif acc.get("is_group"):
                problems.append(f"{who}: akun {code} adalah akun grup (header) — pilih akun rinci")
            elif not acc.get("active"):
                problems.append(f"{who}: akun {code} nonaktif — aktifkan lagi di Bagan Akun atau pilih akun lain")
            clean[role] = code
        if problems:
            raise HTTPException(400, "; ".join(problems) + ".")
        upd["mapping"] = clean
        # 2026-11-02 (audit No.47): catat peran yang DIUBAH/DIHAPUS pengguna agar startup
        # (upgrade_posting_profiles) tidak mengembalikannya ke bawaan.
        old_map = doc.get("mapping") or {}
        changed = {r for r, c in clean.items() if old_map.get(r) != c}
        removed = {r for r in old_map if r not in clean}
        upd["user_roles"] = sorted((set(doc.get("user_roles") or []) | changed) - removed)
        upd["user_removed_roles"] = sorted((set(doc.get("user_removed_roles") or []) | removed) - set(clean))
    if "description" in body:
        upd["description"] = (body.get("description") or "").strip()
    if "active" in body:
        upd["active"] = bool(body["active"])
    await db.rahaza_posting_profiles.update_one({"event_type": event_type}, {"$set": upd})
    out = await db.rahaza_posting_profiles.find_one({"event_type": event_type}, {"_id": 0})
    await log_activity(user["id"], user.get("name", ""), "update_posting_profile", "posting_profile", event_type)
    return serialize_doc(out)


async def seed_posting_profiles(db, user=None):
    """Seed default posting profiles idempotent (skip if exists).
    Reusable by both the startup auto-seed (server.py) and the /seed route."""
    uid = (user or {}).get("id", "system")
    uname = (user or {}).get("name", "system")
    inserted = 0
    skipped = 0
    # Batch fetch existing posting profiles
    event_types = [p["event_type"] for p in DEFAULT_PROFILES]
    existing_profiles_set = set()
    if event_types:
        async for d in db.rahaza_posting_profiles.find(
            {"event_type": {"$in": event_types}}, {"_id": 0, "event_type": 1}
        ):
            existing_profiles_set.add(d["event_type"])
    for p in DEFAULT_PROFILES:
        if p["event_type"] in existing_profiles_set:
            skipped += 1
            continue
        doc = {
            "id": _uid(),
            "event_type": p["event_type"],
            "description": p["description"],
            "mapping": p["mapping"],
            "active": True,
            "created_at": _now(),
            "updated_at": _now(),
            "created_by": uid,
            "created_by_name": uname,
        }
        await db.rahaza_posting_profiles.insert_one(doc)
        inserted += 1
    return {"inserted": inserted, "skipped": skipped, "total_template": len(DEFAULT_PROFILES)}


@router.post("/seed")
async def seed_defaults(request: Request):
    """Seed default posting profiles idempotent (skip if exists)."""
    user = await _require_fin(request)
    db = get_db()
    result = await seed_posting_profiles(db, user)
    await log_activity(user["id"], user.get("name", ""), "seed_posting_profiles", "posting_profile",
                       f"inserted={result['inserted']} skipped={result['skipped']}")
    return {"ok": True, **result}


async def ensure_seed(db):
    """Internal helper: auto-seed if collection is empty. Called by posting helpers."""
    cnt = await db.rahaza_posting_profiles.count_documents({})
    if cnt > 0:
        return
    for p in DEFAULT_PROFILES:
        doc = {
            "id": _uid(),
            "event_type": p["event_type"],
            "description": p["description"],
            "mapping": p["mapping"],
            "active": True,
            "created_at": _now(),
            "updated_at": _now(),
            "created_by": "system",
            "created_by_name": "system",
        }
        await db.rahaza_posting_profiles.insert_one(doc)


async def get_mapping(db, event_type: str) -> dict:
    await ensure_seed(db)
    doc = await db.rahaza_posting_profiles.find_one({"event_type": event_type, "active": True}, {"_id": 0})
    if not doc:
        return {}
    return doc.get("mapping") or {}


async def role_code(db, event_type: str, role: str, default: str | None = None) -> str | None:
    """2026-11-02 (S2-H): kode akun satu peran profil posting; kosong → `default` (konstanta modul).
    Pintu baca untuk modul yang dulu memakai kode akun yang ditulis langsung (pencairan marketplace,
    perjalanan dinas, tutup buku, saldo awal) — lihat `core.coa_bindings.CONSTANT_SOURCES`."""
    code = (await get_mapping(db, event_type)).get(role)
    return (str(code).strip() if code else "") or default


@router.post("/seed-da")
async def seed_da_profiles(request: Request):
    """DIHENTIKAN: skema 4-digit kanonik (audit 2026-09-04). Pakai /api/rahaza/coa/migrate-canonical."""
    await _require_fin(request)
    raise HTTPException(410, "Profil DA 3-digit sudah tidak dipakai — skema akun kanonik 4-digit. "
                             "Jalankan POST /api/rahaza/coa/migrate-canonical.")

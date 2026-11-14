// FIN-02: cermin core/roles.py FINANCE_ROLES — satu sumber peran keuangan untuk tombol layar.
export const FINANCE_ROLES = ['superadmin', 'admin', 'owner', 'accounting', 'staff_keuangan', 'manager_keuangan', 'finance', 'finance_manager', 'accountant'];
export const isFinanceRole = (role) => FINANCE_ROLES.includes(String(role || '').toLowerCase());
// 2026-11-06 (Tahap 2): peran user aktif dari sesi tersimpan (pola sama dengan portalAccess.currentRole) —
// untuk layar yang tidak boleh menarik peta menu portal hanya demi cek peran Keuangan.
export const isCurrentUserFinance = () => {
  try {
    return isFinanceRole(JSON.parse(localStorage.getItem('erp_user') || 'null')?.role);
  } catch { return false; }
};

// 2026-11-08: cermin core/roles.py — penyetuju klaim/dinas (APPROVER_ROLES) dan izin PASANGAN daftar peran.
// Tombol memakai `checkPerm({ user, roles, keys })` (lib/rbac.jsx) = aturan `auth.check_role` di server, supaya
// peran buatan owner ("Accounting & Finance", "HR Generalist", …) melihat tombol yang memang boleh mereka pakai.
export const APPROVER_ROLES = [...FINANCE_ROLES, 'hr', 'hr_manager', 'manager'];
export const EXPENSE_APPROVE_PERMS = ['hr.approve'];
export const SETTLEMENT_APPROVE_PERMS = ['hr.approve', 'finance.approve'];
export const FINANCE_PAY_PERMS = ['finance.manage', 'fin.payment.manage'];
export const FINANCE_BOOK_PERMS = ['finance.manage'];
export const FINANCE_CASH_PERMS = ['fin.cash.manage', 'finance.manage'];
export const EXPENSE_VIEW_ALL_PERMS = [...EXPENSE_APPROVE_PERMS, ...FINANCE_PAY_PERMS];
export const SETTLEMENT_VIEW_ALL_PERMS = [...SETTLEMENT_APPROVE_PERMS, ...FINANCE_PAY_PERMS];

// 14 Nov 2026: tombol Bayar / Jurnal hutang mengikuti CENTANG owner, bukan kode peran keuangan. Kunci = yang diminta
// gerbang modul server untuk endpoint tombolnya (data/module_catalog.py; dikunci uji
// backend/tests/unit/test_temuan_produksi.py):
//   Bayar faktur pemasok / tagihan CMT, batal pembayaran CMT → Keuangan › Pembayaran & Pencairan Uang › Setujui;
//   Jurnal tagihan CMT (…/cmt-payments/{id}/post-ap)       → Maklon › Piutang Klien › Setujui.
// Dibaca dengan `punyaCentang(hasPerm, kunci)` dari lib/rbac.jsx.
export const CENTANG_BAYAR = 'mod.fin_pencairan.approve';
export const CENTANG_JURNAL_CMT = 'mod.mak_billing.approve';

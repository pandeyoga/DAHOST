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

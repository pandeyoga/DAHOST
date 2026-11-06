// SY2 (7 Nov 2026, keputusan owner): cermin core/roles.py SYSTEM_CONFIG_ROLES — hanya peran ini yang boleh
// MENGUBAH Pengaturan Sistem. Server tetap penjaganya; layar memakai daftar ini supaya peran lain melihat
// mode baca saja, bukan tombol yang selalu ditolak.
export const SYSTEM_CONFIG_ROLES = ['superadmin', 'admin', 'owner'];
export const canEditSystemConfig = (role) => SYSTEM_CONFIG_ROLES.includes(String(role || '').toLowerCase());
// Peran user aktif dari sesi tersimpan (pola sama dengan lib/financeRoles.isCurrentUserFinance).
export const isCurrentUserConfigAdmin = () => {
  try {
    return canEditSystemConfig(JSON.parse(localStorage.getItem('erp_user') || 'null')?.role);
  } catch { return false; }
};

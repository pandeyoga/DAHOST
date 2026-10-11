// FIN-02: cermin core/roles.py FINANCE_ROLES — satu sumber peran keuangan untuk tombol layar.
export const FINANCE_ROLES = ['superadmin', 'admin', 'owner', 'accounting', 'staff_keuangan', 'manager_keuangan', 'finance', 'finance_manager', 'accountant'];
export const isFinanceRole = (role) => FINANCE_ROLES.includes(String(role || '').toLowerCase());

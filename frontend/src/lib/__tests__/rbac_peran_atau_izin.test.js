// 2026-11-08: mode "kode peran ATAU izin" checkPerm = cermin auth.check_role di server.
// 14 Nov 2026 (owner: centang = penentu): cermin `routes.shared.can_act` / `core.authz.izin_atau_peran_lama` — izin
// memutuskan; kode peran di daftar hanya berlaku selama peran itu BELUM punya centang/izin sama sekali.
import { checkPerm } from '../rbac';
import {
  APPROVER_ROLES, EXPENSE_APPROVE_PERMS, FINANCE_PAY_PERMS, FINANCE_ROLES,
} from '../financeRoles';

const akun = (role, permissions = []) => ({ id: 'u1', role, permissions });

describe('checkPerm({ roles }) — kode peran ATAU izin', () => {
  const roles = ['superadmin', 'hr', 'manager'];

  test('kode peran lama tetap lolos (tanpa izin apa pun)', () => {
    expect(checkPerm({ user: akun('hr'), roles, perm: 'hr.manage' })).toBe(true);
    expect(checkPerm({ user: akun('manager'), roles, perm: 'hr.manage' })).toBe(true);
  });

  test('kode peran di daftar TIDAK mengalahkan centang: peran yang sudah diatur tanpa izinnya ditolak', () => {
    expect(checkPerm({ user: akun('hr', ['mod.hr_leave.view']), roles, perm: 'hr.manage' })).toBe(false);
    expect(checkPerm({ user: akun('manager', ['dashboard.view']), roles, perm: 'hr.manage' })).toBe(false);
    expect(checkPerm({ user: akun('manager', ['hr.manage']), roles, perm: 'hr.manage' })).toBe(true);
  });

  test('kode peran dibandingkan tanpa beda huruf (sama dengan can_act di server)', () => {
    expect(checkPerm({ user: akun('HR', []), roles, perm: 'hr.manage' })).toBe(true);
    expect(checkPerm({ user: akun('Staf', []), roles, perm: 'hr.manage' })).toBe(false);
  });

  test('peran buatan owner dengan izinnya lolos', () => {
    expect(checkPerm({ user: akun('HR Generalist', ['hr.manage']), roles, perm: 'hr.manage' })).toBe(true);
    expect(checkPerm({ user: akun('HR Generalist', ['salary.manage']), roles, keys: ['hr.manage', 'salary.manage'] }))
      .toBe(true);
  });

  test('peran buatan owner tanpa izin → tidak lolos (tidak permisif walau izin kosong)', () => {
    expect(checkPerm({ user: akun('HR Generalist', ['dashboard.view']), roles, perm: 'hr.manage' })).toBe(false);
    expect(checkPerm({ user: akun('HR Generalist', []), roles, perm: 'hr.manage' })).toBe(false);
    expect(checkPerm({ user: null, roles, perm: 'hr.manage' })).toBe(false);
  });

  test('sama dengan server: peran super (superadmin/admin/owner) & izin "*" selalu lolos', () => {
    expect(checkPerm({ user: akun('superadmin'), roles: [], perm: 'x.y' })).toBe(true);
    expect(checkPerm({ user: akun('admin', ['*']), roles, perm: 'hr.manage' })).toBe(true);
    expect(checkPerm({ user: akun('owner'), roles, perm: 'hr.manage' })).toBe(true);
    expect(checkPerm({ user: akun('Pengawas', ['*']), roles: [], perm: 'hr.manage' })).toBe(true);
  });

  test('pemisahan tugas K25: penyetuju klaim SDM tidak otomatis boleh membayar', () => {
    const hrBuatan = akun('HR Generalist', ['hr.approve', 'hr.manage', 'fin.expense.manage']);
    expect(checkPerm({ user: hrBuatan, roles: APPROVER_ROLES, keys: EXPENSE_APPROVE_PERMS })).toBe(true);
    expect(checkPerm({ user: hrBuatan, roles: FINANCE_ROLES, keys: FINANCE_PAY_PERMS })).toBe(false);
    expect(checkPerm({ user: akun('Accounting & Finance', ['fin.payment.manage']), roles: FINANCE_ROLES,
      keys: FINANCE_PAY_PERMS })).toBe(true);
  });

  test('tanpa `roles` perilaku lama tidak berubah (super role & permisif bila izin kosong)', () => {
    expect(checkPerm({ user: akun('owner'), perm: 'hr.manage' })).toBe(true);
    expect(checkPerm({ user: akun('operator', []), perm: 'hr.manage' })).toBe(true);
    expect(checkPerm({ user: akun('operator', ['dashboard.view']), perm: 'hr.manage' })).toBe(false);
  });
});

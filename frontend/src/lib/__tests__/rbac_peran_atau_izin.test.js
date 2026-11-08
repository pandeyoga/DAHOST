// 2026-11-08: mode "kode peran ATAU izin" checkPerm = cermin auth.check_role di server.
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

  test('kode peran dibandingkan persis (sama dengan auth.check_role): peran buatan bernama "Admin" bukan admin', () => {
    expect(checkPerm({ user: akun('Admin', []), roles: ['admin', 'hr'], perm: 'hr.manage' })).toBe(false);
    expect(checkPerm({ user: akun('Superadmin', []), roles: ['hr'], perm: 'hr.manage' })).toBe(false);
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

  test('sama dengan server: superadmin & izin "*" lolos; owner hanya bila ada di daftar atau punya izinnya', () => {
    expect(checkPerm({ user: akun('superadmin'), roles: [], perm: 'x.y' })).toBe(true);
    expect(checkPerm({ user: akun('admin', ['*']), roles, perm: 'hr.manage' })).toBe(true);
    expect(checkPerm({ user: akun('owner'), roles, perm: 'hr.manage' })).toBe(false);
    expect(checkPerm({ user: akun('owner', ['hr.manage']), roles, perm: 'hr.manage' })).toBe(true);
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

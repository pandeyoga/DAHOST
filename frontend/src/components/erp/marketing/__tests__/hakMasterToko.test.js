// 13 Nov 2026 (owner: "mana yang bisa menambahkan akun mana yang tidak"): tombol tambah/ubah/hapus toko mengikuti
// centang "Kelola Akun" (mod.mkt_accounts.create/edit/delete) di Manajemen Role — bukan daftar kode peran.
import { canDeleteStores, canManageStores } from '../NoStoreScopeNotice';

const masuk = (role, permissions = []) => localStorage.setItem('erp_user', JSON.stringify({ role, permissions }));

afterEach(() => localStorage.clear());

test('centang Kelola Akun › Tambah membuka tombol kelola toko untuk peran apa pun', () => {
  masuk('Content Creator', ['mod.mkt_accounts.view', 'mod.mkt_accounts.create']);
  expect(canManageStores()).toBe(true);
  expect(canDeleteStores()).toBe(false);
  masuk('Content Creator', ['mod.mkt_accounts.delete']);
  expect(canDeleteStores()).toBe(true);
});

test('tanpa centang Kelola Akun Tambah/Ubah/Hapus → tidak boleh, walau kode perannya dulu ada di daftar', () => {
  masuk('manager_marketing', ['mod.mkt_accounts.view']);
  expect(canManageStores()).toBe(false);
  masuk('pic_toko', []);
  expect(canManageStores()).toBe(false);
});

test('owner/admin/superadmin selalu boleh', () => {
  masuk('owner');
  expect(canManageStores()).toBe(true);
  expect(canDeleteStores()).toBe(true);
});

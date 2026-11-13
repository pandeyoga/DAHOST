// 14 Nov 2026 (akses tahap 2): pintu menu yang dulu dikunci daftar kode peran kini mengikuti centang.
//  - "Koreksi Data Toko" tampil bila Kelola Akun › Ubah dicentang (`aksi: 'edit'`).
//  - "Input atas nama CMT" tidak lagi berdaftar peran — tampil/tersembunyi lewat centang Lihat modulnya.
import { navItemAllowed } from '../../portalAccess';
import { PORTAL_NAV } from '../../portal-shell/portalNav';

const akses = (moduleAccess) => localStorage.setItem('erp_access', JSON.stringify({
  portals: ['toko', 'self', 'collaboration'], hidden_modules: [], is_super: false, module_access: moduleAccess,
}));
const semuaItem = () => Object.values(PORTAL_NAV).flatMap((n) => (n.sections || []).flatMap((s) => [
  ...(s.items || []), ...(s.groups || []).flatMap((g) => g.items || [])]));

afterEach(() => localStorage.clear());

test('Koreksi Data Toko mengikuti centang Ubah, bukan kode peran', () => {
  const item = semuaItem().find((i) => i.id === 'marketing-account-review');
  expect(item.roles).toBeUndefined();
  akses({ 'marketing-account-review': ['view'] });
  expect(navItemAllowed(item, 'manager_marketing')).toBe(false);
  akses({ 'marketing-account-review': ['view', 'edit'] });
  expect(navItemAllowed(item, 'Content Creator')).toBe(true);
  expect(navItemAllowed(item, 'owner')).toBe(true);
});

test('Input atas nama CMT tidak lagi dikunci daftar kode peran', () => {
  const items = semuaItem().filter((i) => i.id === 'cmt-override-portal');
  expect(items.length).toBeGreaterThan(0);
  items.forEach((i) => expect(i.roles).toBeUndefined());
});

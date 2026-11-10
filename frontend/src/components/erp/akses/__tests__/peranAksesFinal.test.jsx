// Akses per peran (keputusan owner 10 Nov 2026): portal yang dicentang di Manajemen Role = FINAL; bawaan hanya
// untuk peran yang belum dicentang; layar menyebut portal bawaan yang tidak ikut terbuka; nama peran mirip diperingatkan.
// Tanpa @testing-library/react (peer @testing-library/dom tidak terpasang) — createRoot + act.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { ConfirmDialogHost } from '@/components/ui/confirm-dialog';
import { canAccessPortal, effectivePortals, portalBawaan } from '../../portalAccess';
import RoleManagementModule, { PortalBawaanInfo } from '../../RoleManagementModule';

jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn(), info: jest.fn() } }));
jest.mock('axios', () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn(), interceptors: { request: { use: jest.fn(), eject: jest.fn() } } } }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let root;
let container;
const q = (id) => document.querySelector(`[data-testid="${id}"]`);
const klik = (el) => act(() => { el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true })); });
const ketik = (el, v) => act(() => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, v);
  el.dispatchEvent(new Event('input', { bubbles: true }));
});
const tunggu = async (fn) => {
  let galat;
  for (let i = 0; i < 60; i += 1) {
    try { if (fn()) return; } catch (e) { galat = e; }
    // eslint-disable-next-line no-await-in-loop
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
  }
  throw galat || new Error('waktu habis');
};

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  document.body.innerHTML = '';
  window.localStorage.clear();
  delete global.fetch;
});

describe('aturan portal (cermin backend effective_portals)', () => {
  test('centangan owner final: bawaan tidak ditambahkan', () => {
    expect(portalBawaan('spv_cuting')).toEqual(expect.arrayContaining(['production', 'cutting', 'procurement']));
    expect(new Set(effectivePortals('spv_cuting', ['cutting', 'warehouse'])))
      .toEqual(new Set(['cutting', 'warehouse', 'self', 'collaboration']));
    expect(effectivePortals('pic_toko', ['toko', 'rnd'])).not.toContain('sales');
  });

  test('peran belum dicentang memakai bawaan; portal per orang ditambahkan; peran super semua', () => {
    expect(new Set(effectivePortals('tim_packing'))).toEqual(new Set(['warehouse', 'self', 'collaboration']));
    expect(effectivePortals('tim_packing', [], ['maklon'])).toEqual(expect.arrayContaining(['warehouse', 'maklon']));
    expect(effectivePortals('owner', ['self'])).toContain('finance');
  });

  test('canAccessPortal memakai daftar efektif dari server', () => {
    window.localStorage.setItem('erp_access', JSON.stringify({ portals: ['cutting', 'warehouse', 'self', 'collaboration'] }));
    expect(canAccessPortal('spv_cuting', 'production')).toBe(false);
    expect(canAccessPortal('spv_cuting', 'procurement')).toBe(false);
    expect(canAccessPortal('spv_cuting', 'cutting')).toBe(true);
  });
});

describe('PortalBawaanInfo', () => {
  test('menyebut portal bawaan yang tidak ikut terbuka + tombol centang', () => {
    const onCentang = jest.fn();
    act(() => root.render(<PortalBawaanInfo bawaan={['production', 'cutting', 'procurement']}
      dicentang={['cutting', 'warehouse']} canEdit onCentang={onCentang} />));
    expect(q('role-portal-bawaan-lepas').textContent).toMatch(/Produksi/);
    expect(q('role-portal-bawaan-centang-cutting')).toBeNull();
    klik(q('role-portal-bawaan-centang-procurement'));
    expect(onCentang).toHaveBeenCalledWith('procurement');
  });

  test('belum ada centangan → memberi tahu bawaan yang dipakai; semua tercentang → tidak tampil', () => {
    act(() => root.render(<PortalBawaanInfo bawaan={['warehouse']} dicentang={[]} canEdit />));
    expect(q('role-portal-bawaan-dipakai').textContent).toMatch(/Gudang/);
    act(() => root.render(<PortalBawaanInfo bawaan={['warehouse']} dicentang={['warehouse', 'production']} canEdit />));
    expect(q('role-portal-bawaan-lepas')).toBeNull();
    expect(q('role-portal-bawaan-dipakai')).toBeNull();
  });
});

describe('Tambah peran — nama mirip', () => {
  const PERAN = [{ id: 'r1', name: 'Operator Cuting', description: 'Operator Cutting', portals: ['cutting'],
    hidden_modules: [], permission_keys: [], user_count: 2, portal_bawaan: [] }];
  const json = (body, status = 200) => Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) });

  test('409 PERAN_MIRIP → konfirmasi → kirim ulang dengan izinkan_mirip', async () => {
    const posts = [];
    global.fetch = jest.fn((url, opts = {}) => {
      if (String(url).includes('/api/permissions')) return json({ groups: [] });
      if (opts.method === 'POST') {
        const body = JSON.parse(opts.body);
        posts.push(body);
        return body.izinkan_mirip
          ? json({ id: 'r2', name: body.name }, 201)
          : json({ detail: "Nama 'operator cutting' mirip dengan peran yang sudah ada: 'Operator Cuting'.",
            code: 'PERAN_MIRIP', mirip: ['Operator Cuting'] }, 409);
      }
      return json(PERAN);
    });
    await act(async () => { root.render(<><ConfirmDialogHost /><RoleManagementModule token="t" userRole="superadmin" /></>); });
    await tunggu(() => q('add-role-btn'));
    klik(q('add-role-btn'));
    await tunggu(() => q('new-role-name'));
    ketik(q('new-role-name'), 'operator cutting');
    await tunggu(() => !q('create-role-dialog-simpan').disabled);
    klik(q('create-role-dialog-simpan'));
    await tunggu(() => q('confirm-dialog'));
    expect(q('confirm-dialog').textContent).toMatch(/Operator Cuting/);
    klik(q('confirm-dialog-ok'));
    await tunggu(() => posts.length === 2);
    expect(posts[0].izinkan_mirip).toBeUndefined();
    expect(posts[1]).toMatchObject({ name: 'operator cutting', izinkan_mirip: true });
  });
});

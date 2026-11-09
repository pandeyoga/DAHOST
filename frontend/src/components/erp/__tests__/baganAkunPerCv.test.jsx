// Owner 9 Nov 2026: Bagan Akun DA dan Sukma tampak identik → layar mengikuti CV terpilih di Portal Keuangan.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { CvProvider } from '@/lib/entitas';
import RahazaCOAModule, { berlakuUntukCv } from '../RahazaCOAModule';

jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn(), info: jest.fn() } }));
jest.mock('../ImportExportToolbar', () => () => null);
jest.mock('axios', () => ({ __esModule: true, default: { interceptors: { request: { use: jest.fn(), eject: jest.fn() } } } }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let root;
let container;
const q = (id) => container.querySelector(`[data-testid="${id}"]`);
const tunggu = async (fn) => {
  let galat;
  for (let i = 0; i < 60; i += 1) {
    try { if (fn()) return; } catch (e) { galat = e; }
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
  }
  throw galat || new Error('waktu habis');
};

const akun = (code, name, entities, parent, extra = {}) => ({
  id: `id-${code}`, code, name, type: code.startsWith('4') ? 'REVENUE' : 'ASSET', parent_code: parent || null,
  entities, active: true, is_group: !parent || code.endsWith('00'), usage: { level: 'BEBAS', labels: [] }, ...extra,
});
const AKUN = [
  akun('1-0000', 'ASET', ['DA', 'SMU']),
  akun('1-1300', 'Piutang', ['DA', 'SMU'], '1-0000'),
  akun('1-1303', 'Piutang Platform Online Shop', ['DA'], '1-1300'),
  akun('1-1305', 'Piutang Klien Maklon', ['SMU'], '1-1300'),
  akun('4-0000', 'PENDAPATAN', ['DA', 'SMU']),
  akun('4-1110', 'Penjualan Online Shop – Shopee', ['DA'], '4-0000'),
  akun('4-1500', 'Pendapatan Maklon', ['SMU'], '4-0000'),
  akun('4-1900', 'Pendapatan lama', ['SMU'], '4-0000', { active: false }),
];

beforeEach(() => {
  global.fetch = jest.fn((url) => {
    const u = String(url);
    let body = null;
    if (u.includes('/api/rahaza/coa/accounts')) body = AKUN;
    else if (u.includes('/api/entities')) body = { entities: [{ code: 'DA', short: 'CV Dewi Aditya' }, { code: 'SMU', short: 'CV Sukma' }, { code: 'ALL' }] };
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
  });
  window.localStorage.clear();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); document.body.innerHTML = ''; });

const pasang = async (cv, { tanpaKeuangan = false } = {}) => {
  if (cv) window.localStorage.setItem('erp_keuangan_cv', cv);
  const layar = <RahazaCOAModule token="t" onNavigate={jest.fn()} />;
  await act(async () => { root.render(tanpaKeuangan ? layar : <CvProvider>{layar}</CvProvider>); });
  await tunggu(() => q('coa-row-1-0000'));
};

test('berlakuUntukCv: Gabungan/tanpa CV = semua; CV tertentu = sesuai entities', () => {
  expect(berlakuUntukCv(AKUN[2], 'ALL')).toBe(true);
  expect(berlakuUntukCv(AKUN[2], undefined)).toBe(true);
  expect(berlakuUntukCv(AKUN[2], 'SMU')).toBe(false);
  expect(berlakuUntukCv(AKUN[3], 'SMU')).toBe(true);
  expect(berlakuUntukCv({ code: 'x' }, 'DA')).toBe(false);
});

test('CV Sukma: tanpa akun khusus DA (penjualan online), induk bersama tetap tampil, angka per CV', async () => {
  await pasang('SMU');
  expect(q('coa-row-1-1305')).not.toBeNull();
  expect(q('coa-row-4-1500')).not.toBeNull();
  expect(q('coa-row-1-1300')).not.toBeNull();
  expect(q('coa-row-1-1303')).toBeNull();
  expect(q('coa-row-4-1110')).toBeNull();
  // aktif SMU: 1-0000, 1-1300, 1-1305, 4-0000, 4-1500 = 5 dari 7 akun aktif
  expect(q('coa-cv-note').textContent).toContain('CV Sukma');
  expect(q('coa-cv-note').textContent).toContain('(5 dari 7 akun aktif)');
  expect(q('coa-summary').textContent).toMatch(/^5 aktif/);
  expect(q('coa-summary').textContent).toContain('1 nonaktif');
});

test('CV Dewi Aditya: akun online tampil, akun khusus Sukma tidak', async () => {
  await pasang('DA');
  expect(q('coa-row-4-1110')).not.toBeNull();
  expect(q('coa-row-1-1303')).not.toBeNull();
  expect(q('coa-row-4-1500')).toBeNull();
  expect(q('coa-row-1-1305')).toBeNull();
  expect(q('coa-cv-note').textContent).toContain('(5 dari 7 akun aktif)');
});

test('Gabungan dan di luar Portal Keuangan: semua akun, tanpa catatan CV', async () => {
  await pasang('ALL');
  ['1-1303', '1-1305', '4-1110', '4-1500'].forEach((c) => expect(q(`coa-row-${c}`)).not.toBeNull());
  expect(q('coa-cv-note')).toBeNull();
  expect(q('coa-summary').textContent).toMatch(/^7 aktif/);
  act(() => root.unmount());
  root = createRoot(container);
  await pasang(null, { tanpaKeuangan: true });
  ['1-1303', '1-1305', '4-1110', '4-1500'].forEach((c) => expect(q(`coa-row-${c}`)).not.toBeNull());
  expect(q('coa-cv-note')).toBeNull();
});

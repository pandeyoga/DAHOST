// Owner 9 Nov 2026: daftar sumber jawaban terlalu panjang (tampilkan sebagian) dan jendela chat ingin penuh.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { asistenApi } from '../asistenApi';
import AsistenAIModule from '../AsistenAIModule';
import PesanAsisten, { BATAS_SUMBER_WEB, ringkasSumber } from '../PesanAsisten';

jest.mock('../asistenApi', () => ({
  KUNCI_SESI_AKTIF: 'asisten_ai_sesi_aktif',
  unduhLaporan: jest.fn(),
  asistenApi: {
    status: jest.fn(), saran: jest.fn(), listSessions: jest.fn(), getSession: jest.fn(), createSession: jest.fn(),
    kirimPesan: jest.fn(), putuskan: jest.fn(), renameSession: jest.fn(), deleteSession: jest.fn(),
  },
}));
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn(), info: jest.fn() } }));
jest.mock('axios', () => ({ __esModule: true, default: { interceptors: { request: { use: jest.fn(), eject: jest.fn() } } } }));
jest.mock('../GrafikAsisten', () => () => null);

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let root;
let container;
const q = (id) => container.querySelector(`[data-testid="${id}"]`);
const qa = (id) => [...container.querySelectorAll(`[data-testid="${id}"]`)];
const klik = (el) => act(() => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })); });
const diam = () => act(async () => { await new Promise((r) => setTimeout(r, 60)); });

const web = (n) => ({ jenis: 'web', url: `https://contoh${n}.id/berita`, label: `Berita ${n}` });

beforeEach(() => {
  jest.clearAllMocks();
  global.fetch = jest.fn(() => Promise.resolve({ ok: false, json: () => Promise.resolve(null) }));
  asistenApi.status.mockResolvedValue({ siap: true, model: 'Claude Opus 5.5', tindakan_aktif: true });
  asistenApi.saran.mockResolvedValue([]);
  asistenApi.listSessions.mockResolvedValue([]);
  window.localStorage.clear();
  window.sessionStorage.clear();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); document.body.innerHTML = ''; });

test('ringkasSumber: data internal selalu tampil, web dibatasi & tanpa duplikat alamat', () => {
  const item = [web(1), { jenis: 'data', label: 'Target toko' }, web(2), { ...web(2), url: 'https://contoh2.id/berita/' },
    web(3), web(4), web(5)];
  const r = ringkasSumber(item);
  expect(r.semua.map((s) => s.label)).toEqual(['Target toko', 'Berita 1', 'Berita 2', 'Berita 3', 'Berita 4', 'Berita 5']);
  expect(r.tampil).toHaveLength(1 + BATAS_SUMBER_WEB);
  expect(r.sisa).toBe(5 - BATAS_SUMBER_WEB);
  expect(ringkasSumber([web(1)]).sisa).toBe(0);
  expect(ringkasSumber(undefined).semua).toEqual([]);
});

test('sumber panjang: tampil sebagian, "+N sumber lain" membuka semua lalu "Ringkas"', () => {
  const item = [{ jenis: 'data', label: 'Target toko & rekap penjualan harian' }, ...Array.from({ length: 20 }, (_, i) => web(i + 1))];
  const pesan = { id: 'm1', peran: 'asisten', keadaan: 'selesai', blok: [{ jenis: 'teks', isi: 'Jawaban' }, { jenis: 'sumber', item }] };
  act(() => { root.render(<PesanAsisten pesan={pesan} />); });
  expect(qa('asisten-sumber-data')).toHaveLength(1);
  expect(qa('asisten-sumber-web')).toHaveLength(BATAS_SUMBER_WEB);
  const tombol = q('asisten-sumber-lainnya');
  expect(tombol.textContent).toBe(`+${20 - BATAS_SUMBER_WEB} sumber lain`);
  klik(tombol);
  expect(qa('asisten-sumber-web')).toHaveLength(20);
  expect(q('asisten-sumber-lainnya').textContent).toBe('Ringkas');
  klik(q('asisten-sumber-lainnya'));
  expect(qa('asisten-sumber-web')).toHaveLength(BATAS_SUMBER_WEB);
});

test('sumber sedikit: tidak ada tombol "sumber lain"', () => {
  const pesan = { id: 'm1', peran: 'asisten', keadaan: 'selesai', blok: [{ jenis: 'teks', isi: 'x' }, { jenis: 'sumber', item: [web(1), web(2)] }] };
  act(() => { root.render(<PesanAsisten pesan={pesan} />); });
  expect(qa('asisten-sumber-web')).toHaveLength(2);
  expect(q('asisten-sumber-lainnya')).toBeNull();
});

test('tombol layar penuh: menutupi layar, diingat, Esc mengembalikan', async () => {
  await act(async () => { root.render(<AsistenAIModule user={{ role: 'owner' }} onNavigate={jest.fn()} />); });
  await diam();
  const wadah = q('asisten-wadah');
  expect(wadah.dataset.layarPenuh).toBe('0');
  klik(q('asisten-layar-penuh'));
  expect(q('asisten-wadah').dataset.layarPenuh).toBe('1');
  expect(q('asisten-wadah').className).toContain('fixed');
  expect(window.localStorage.getItem('asisten-ai-layar-penuh')).toBe('1');
  act(() => { window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); });
  expect(q('asisten-wadah').dataset.layarPenuh).toBe('0');
  expect(window.localStorage.getItem('asisten-ai-layar-penuh')).toBe('0');
});

test('pilihan layar penuh dari kunjungan sebelumnya dipakai lagi', async () => {
  window.localStorage.setItem('asisten-ai-layar-penuh', '1');
  await act(async () => { root.render(<AsistenAIModule user={{ role: 'owner' }} onNavigate={jest.fn()} />); });
  await diam();
  expect(q('asisten-wadah').dataset.layarPenuh).toBe('1');
  expect(q('asisten-layar-penuh').getAttribute('aria-pressed')).toBe('true');
});

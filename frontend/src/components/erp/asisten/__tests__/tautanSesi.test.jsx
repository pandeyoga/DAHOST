// Tahap D (layar2): tautan langsung `?portal=management&module=asisten-ai&sesi=<id>` dan klik notifikasi
// (`deepLinkParams`) membuka percakapan itu — saat halaman dibuka DAN saat halaman sudah terbuka.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { asistenApi } from '../asistenApi';
import AsistenAIModule from '../AsistenAIModule';

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
// eslint-disable-next-line import/first
import { toast } from 'sonner';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let root;
let container;
const q = (id) => container.querySelector(`[data-testid="${id}"]`);
const tunggu = async (fn) => {
  let galat;
  for (let i = 0; i < 60; i += 1) {
    try { if (fn()) return; } catch (e) { galat = e; }
    // eslint-disable-next-line no-await-in-loop
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
  }
  throw galat || new Error('waktu habis');
};
const diam = () => act(async () => { await new Promise((r) => setTimeout(r, 60)); });

const SESI = [
  { id: 's-a', judul: 'Omzet bulan ini', updated_at: new Date().toISOString() },
  { id: 's-b', judul: 'Briefing pagi 08 Nov 2026', jenis: 'briefing', updated_at: new Date().toISOString() },
  { id: 's-c', judul: 'Stok menipis', updated_at: new Date().toISOString() },
];
const isi = (id) => ({ id, judul: SESI.find((s) => s.id === id)?.judul, pesan: [{ id: `${id}-m1`, peran: 'asisten', status: 'selesai', blok: [{ jenis: 'teks', isi: `Isi ${id}` }] }] });
const dibuka = () => asistenApi.getSession.mock.calls.map(([id]) => id);

beforeEach(() => {
  jest.clearAllMocks();
  global.fetch = jest.fn(() => Promise.resolve({ ok: false, json: () => Promise.resolve(null) }));
  asistenApi.status.mockResolvedValue({ siap: true, model: 'Claude Opus 5.5', tindakan_aktif: true });
  asistenApi.saran.mockResolvedValue([]);
  asistenApi.listSessions.mockResolvedValue(SESI);
  asistenApi.getSession.mockImplementation((id) => (id === 's-hilang'
    ? Promise.reject(Object.assign(new Error('Tidak ditemukan'), { status: 404 }))
    : Promise.resolve(isi(id))));
  window.sessionStorage.clear();
  window.history.replaceState(null, '', '/');
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); document.body.innerHTML = ''; });

const render = (props) => act(async () => { root.render(<AsistenAIModule user={{ id: 'u1', role: 'owner' }} onNavigate={jest.fn()} {...props} />); });

test('alamat ?sesi= saat halaman dibuka → percakapan itu (satu kali), alamat dibersihkan, diingat untuk muat ulang', async () => {
  window.sessionStorage.setItem('asisten_ai_sesi_aktif', 's-a');
  window.history.replaceState(null, '', '/?portal=management&module=asisten-ai&sesi=s-b#asisten-ai');
  await render({ deepLinkParams: {} });
  await tunggu(() => q('asisten-judul')?.textContent === 'Briefing pagi 08 Nov 2026');
  await diam();
  expect(dibuka()).toEqual(['s-b']);
  expect(window.location.search).toBe('?portal=management&module=asisten-ai');
  expect(window.location.hash).toBe('#asisten-ai');
  expect(window.sessionStorage.getItem('asisten_ai_sesi_aktif')).toBe('s-b');
});

test('klik notifikasi sebelum halaman terbuka (link_id) mengalahkan percakapan terakhir', async () => {
  window.sessionStorage.setItem('asisten_ai_sesi_aktif', 's-a');
  await render({ deepLinkParams: { link_id: 's-b', record_id: 's-b', from_notification: 'n1', tujuan_modul: 'asisten-ai' } });
  await tunggu(() => q('asisten-judul')?.textContent === 'Briefing pagi 08 Nov 2026');
  await diam();
  expect(dibuka()).toEqual(['s-b']);
});

test('halaman sudah terbuka: parameter baru membuka sesi itu; objek yang sama tidak dipakai dua kali; parameter basi tidak menimpa pilihan pengguna', async () => {
  window.sessionStorage.setItem('asisten_ai_sesi_aktif', 's-a');
  const kosong = {};
  await render({ deepLinkParams: kosong });
  await tunggu(() => q('asisten-judul')?.textContent === 'Omzet bulan ini');
  const p1 = { sesi: 's-b', from_notification: 'n2' };
  await render({ deepLinkParams: p1 });
  await tunggu(() => q('asisten-judul')?.textContent === 'Briefing pagi 08 Nov 2026');
  await diam();
  expect(dibuka()).toEqual(['s-a', 's-b']);
  expect(asistenApi.listSessions.mock.calls.length).toBeGreaterThanOrEqual(2); // riwayat disegarkan (briefing baru)
  // objek parameter yang sama (render ulang App) → tidak membuka lagi
  await render({ deepLinkParams: p1, user: { id: 'u1', role: 'owner' } });
  await diam();
  expect(dibuka()).toEqual(['s-a', 's-b']);
  // klik notifikasi yang sama lagi (objek baru, sesi sama) → isinya disegarkan
  await render({ deepLinkParams: { sesi: 's-b' } });
  await tunggu(() => dibuka().length === 3);
  expect(dibuka()[2]).toBe('s-b');
  // pengguna memilih percakapan lain, pindah menu, kembali dengan parameter basi p1 → tetap percakapan pilihannya
  const item = [...container.querySelectorAll('[data-testid="asisten-sesi-item"]')].find((el) => el.textContent.includes('Stok menipis'));
  await act(async () => { item.click(); });
  await tunggu(() => q('asisten-judul')?.textContent === 'Stok menipis');
  act(() => root.unmount());
  root = createRoot(container);
  asistenApi.getSession.mockClear();
  await render({ deepLinkParams: p1 });
  await tunggu(() => q('asisten-judul')?.textContent === 'Stok menipis');
  await diam();
  expect(dibuka()).toEqual(['s-c']);
});

test('parameter notifikasi layar LAIN yang masih tersimpan (dibuka lewat menu samping) tidak dibaca sebagai percakapan', async () => {
  window.sessionStorage.setItem('asisten_ai_sesi_aktif', 's-a');
  await render({ deepLinkParams: { record_id: 'AP-1', link_id: 'AP-1', from_notification: 'n9', tujuan_modul: 'fin-ap' } });
  await tunggu(() => q('asisten-judul')?.textContent === 'Omzet bulan ini');
  await diam();
  expect(dibuka()).toEqual(['s-a']);
  expect(toast.error).not.toHaveBeenCalled();
  expect(window.sessionStorage.getItem('asisten_ai_sesi_aktif')).toBe('s-a');
});

test('sesi dari tautan tidak ditemukan / bukan milik sendiri → pesan ramah, kembali ke percakapan baru', async () => {
  await render({ deepLinkParams: { sesi: 's-hilang' } });
  await tunggu(() => toast.error.mock.calls.length > 0);
  expect(toast.error).toHaveBeenCalledWith('Percakapan dari tautan tidak ditemukan atau bukan milik Anda.');
  await tunggu(() => q('asisten-judul')?.textContent === 'Percakapan baru');
});

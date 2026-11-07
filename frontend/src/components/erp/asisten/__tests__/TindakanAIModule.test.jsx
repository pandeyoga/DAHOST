// Halaman Tindakan AI dengan BENTUK JAWABAN inti yang sebenarnya (worktree asb-inti, 8 Nov 2026):
//   GET /tindakan → {items, total, halaman, per_halaman: 25, semua}   (tanpa jumlah per keadaan)
//   GET /tindakan/{id} → sebelum/sesudah = [{label, nilai}], diputuskan_oleh, milik_sendiri, balik_gagal, …
//   POST /tindakan/{id}/balikkan gagal → 409 "Pembalikan gagal: …" (keadaan tetap dijalankan)
// Tanpa @testing-library/react (peer @testing-library/dom tidak terpasang) — createRoot + act.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { ConfirmDialogHost } from '@/components/ui/confirm-dialog';
import { asistenApi } from '../asistenApi';
import TindakanAIModule from '../TindakanAIModule';

jest.mock('../asistenApi', () => ({
  KUNCI_SESI_AKTIF: 'asisten_ai_sesi_aktif',
  asistenApi: { daftarTindakan: jest.fn(), detailTindakan: jest.fn(), balikkanTindakan: jest.fn() },
}));
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn(), info: jest.fn() } }));
// lib/entitas (dipakai PageLayout) mengimpor axios versi ESM yang tidak diubah jest; cukup tiruan interceptor.
jest.mock('axios', () => ({ __esModule: true, default: { interceptors: { request: { use: jest.fn(), eject: jest.fn() } } } }));
// eslint-disable-next-line import/first
import { toast } from 'sonner';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let root;
let container;
const q = (id) => document.querySelector(`[data-testid="${id}"]`);
const tunggu = async (fn) => {
  let galat;
  for (let i = 0; i < 60; i += 1) {
    try { if (fn()) return; } catch (e) { galat = e; }
    // eslint-disable-next-line no-await-in-loop
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
  }
  throw galat || new Error('waktu habis');
};
const klik = (el) => act(() => { el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true })); });
const ketik = (el, v) => act(() => {
  Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(el, v);
  el.dispatchEvent(new Event('input', { bubbles: true }));
});

const BARIS = {
  id: 'tnd-1', dibuat: '2026-11-08T03:15:00', pengguna: { id: 'u1', nama: 'Pengguna Uji' }, sesi_id: 's1',
  nama: 'pasang_target_toko', label: 'Memasang target toko', judul: 'Pasang target toko November 2026',
  keadaan: 'dijalankan', risiko: 'rendah', ringkas: 'Target 2 toko November 2026 terpasang.', bisa_dibalikkan: true,
};
const DETAIL = {
  ...BARIS,
  rencana: { judul: BARIS.judul, ringkas: '2 toko, skenario realistis.', perubahan: [{ label: 'Shopee Toko A', sebelum: 'Rp 120.000.000', sesudah: 'Rp 135.000.000' }] },
  sebelum: [{ label: 'Shopee Toko A', nilai: 'Rp 120.000.000' }],
  sesudah: [{ label: 'Shopee Toko A', nilai: 'Rp 135.000.000' }],
  hasil: { target_ids: ['tg-1'], jumlah_toko: 2 },
  hasil_ringkas: 'Target 2 toko November 2026 terpasang.',
  diputuskan_pada: '2026-11-08T03:16:00', diputuskan_oleh: { id: 'u1', nama: 'Pengguna Uji' },
  dijalankan_pada: '2026-11-08T03:16:00', selesai_pada: '2026-11-08T03:16:02',
  kedaluwarsa_pada: '2026-11-09T03:15:00', milik_sendiri: true, alasan: null,
};

beforeEach(() => {
  jest.clearAllMocks();
  asistenApi.daftarTindakan.mockResolvedValue({ items: [BARIS], total: 1, halaman: 1, per_halaman: 25, semua: false });
  asistenApi.detailTindakan.mockResolvedValue(DETAIL);
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); document.body.innerHTML = ''; });

async function tampilkan(user = { id: 'u1', role: 'manager' }, onNavigate = jest.fn()) {
  await act(async () => { root.render(<><ConfirmDialogHost /><TindakanAIModule user={user} onNavigate={onNavigate} /></>); });
  await tunggu(() => q('tindakan-ai-baris-tnd-1'));
  return onNavigate;
}

test('daftar bentuk inti: kolom, StatusBadge, pil tanpa angka (inti tidak mengirim jumlah per keadaan), tanpa "Semua pengguna" untuk manager', async () => {
  await tampilkan();
  expect(asistenApi.daftarTindakan).toHaveBeenCalledWith(expect.stringMatching(/^dari=\d{4}-\d{2}-01&sampai=\d{4}-\d{2}-\d{2}&halaman=1$/));
  const kepala = [...container.querySelectorAll('thead th')].map((th) => th.textContent.trim().toLowerCase());
  expect(kepala).toEqual(expect.arrayContaining(['waktu', 'pengguna', 'tindakan', 'ringkas', 'status']));
  expect(q('tindakan-ai-status-tnd-1').textContent).toBe('Dijalankan');
  expect(q('tindakan-ai-status-dijalankan').textContent).toBe('Dijalankan');
  expect(q('tindakan-ai-semua')).toBeNull();
  expect(q('pagination-lite')).toBeNull();
});

test('owner melihat "Semua pengguna" → semua=1', async () => {
  await tampilkan({ id: 'u1', role: 'owner' });
  klik(q('tindakan-ai-semua'));
  await tunggu(() => asistenApi.daftarTindakan.mock.calls.some(([s]) => s.endsWith('&semua=1')));
});

test('rincian: sebelum/sesudah [{label, nilai}] tampil apa adanya, oleh siapa, tanpa istilah program; tautan percakapan', async () => {
  const onNavigate = await tampilkan();
  klik(q('tindakan-ai-buka-tnd-1'));
  await tunggu(() => q('tindakan-ai-rincian-tnd-1'));
  const sebelum = q('tindakan-ai-sebelum').textContent;
  expect(sebelum).toContain('Shopee Toko A');
  expect(sebelum).toContain('Rp 120.000.000');
  expect(sebelum).not.toMatch(/label|nilai/);
  expect(q('tindakan-ai-sesudah').textContent).toContain('Rp 135.000.000');
  expect(q('tindakan-ai-hasil').textContent).toContain('Target 2 toko November 2026 terpasang.');
  expect(q('tindakan-ai-hasil-rinci').textContent).toContain('Jumlah toko2');
  const waktu = q('tindakan-ai-waktu').textContent;
  expect(waktu).toContain('Diputuskan');
  expect(waktu).toContain('· Pengguna Uji');
  expect(waktu).toContain('Selesai');
  expect(waktu).not.toContain('Batas keputusan'); // sudah dijalankan
  expect(q('tindakan-ai-rincian-tnd-1').textContent).not.toMatch(/target_ids|_toko|snake/);
  klik(q('tindakan-ai-buka-sesi'));
  expect(window.sessionStorage.getItem('asisten_ai_sesi_aktif')).toBe('s1');
  expect(onNavigate).toHaveBeenCalledWith('asisten-ai');
});

test('rincian milik orang lain (milik_sendiri=false): tanpa tautan percakapan', async () => {
  asistenApi.detailTindakan.mockResolvedValue({ ...DETAIL, milik_sendiri: false });
  await tampilkan({ id: 'u1', role: 'owner' });
  klik(q('tindakan-ai-buka-tnd-1'));
  await tunggu(() => q('tindakan-ai-rincian-tnd-1'));
  expect(q('tindakan-ai-buka-sesi')).toBeNull();
});

test('Balikkan gagal (409 "Pembalikan gagal: …"): toast galat, keadaan tetap, rincian dimuat ulang menampilkan kegagalan', async () => {
  asistenApi.balikkanTindakan.mockRejectedValue(Object.assign(new Error('Pembalikan gagal: Target sudah dikunci periode.'), { status: 409 }));
  await tampilkan();
  klik(q('tindakan-ai-buka-tnd-1'));
  await tunggu(() => q('tindakan-ai-rincian-tnd-1'));
  asistenApi.detailTindakan.mockResolvedValue({ ...DETAIL, balik_gagal: { pesan: 'Target sudah dikunci periode.', pada: '2026-11-08T04:00:00' } });
  klik(q('tindakan-ai-balikkan-tnd-1'));
  await tunggu(() => q('confirm-dialog-input'));
  ketik(q('confirm-dialog-input'), 'Target terlalu tinggi');
  klik(q('confirm-dialog-ok'));
  await tunggu(() => q('tindakan-ai-balik-gagal'));
  expect(asistenApi.balikkanTindakan).toHaveBeenCalledWith('tnd-1', 'Target terlalu tinggi');
  expect(toast.error).toHaveBeenCalledWith('Pembalikan gagal: Target sudah dikunci periode.');
  expect(q('tindakan-ai-balik-gagal').textContent).toContain('Target sudah dikunci periode.');
  expect(q('tindakan-ai-baris-tnd-1').getAttribute('data-keadaan')).toBe('dijalankan');
});

test('Balikkan berhasil: daftar dimuat ulang, toast ringkas', async () => {
  asistenApi.balikkanTindakan.mockResolvedValue({ ok: true, id: 'tnd-1', keadaan: 'dibalikkan', ringkas: 'Nilai lama dipulihkan.' });
  await tampilkan();
  asistenApi.daftarTindakan.mockResolvedValue({ items: [{ ...BARIS, keadaan: 'dibalikkan', bisa_dibalikkan: false }], total: 1, halaman: 1, per_halaman: 25, semua: false });
  klik(q('tindakan-ai-balikkan-tnd-1'));
  await tunggu(() => q('confirm-dialog-input'));
  ketik(q('confirm-dialog-input'), 'Salah toko');
  klik(q('confirm-dialog-ok'));
  await tunggu(() => q('tindakan-ai-baris-tnd-1')?.getAttribute('data-keadaan') === 'dibalikkan');
  expect(toast.success).toHaveBeenCalledWith('Nilai lama dipulihkan.');
  expect(q('tindakan-ai-balikkan-tnd-1')).toBeNull();
});

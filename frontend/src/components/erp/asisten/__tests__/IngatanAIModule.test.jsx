// Halaman Ingatan AI (Tahap D, D1) dengan bentuk jawaban NYATA backend proaktif:
//   GET → {items, total, aktif, batas_aktif, maks_isi, kategori, ingatan_aktif}; POST → item + sudah_ada;
//   PATCH {isi?, kategori?, aktif?} → item (400 bila tanpa perubahan); DELETE → {ok}.
// Tanpa @testing-library/react (peer @testing-library/dom tidak terpasang) — createRoot + act.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { ConfirmDialogHost } from '@/components/ui/confirm-dialog';
import { asistenApi } from '../asistenApi';
import IngatanAIModule from '../IngatanAIModule';

jest.mock('../asistenApi', () => ({
  KUNCI_SESI_AKTIF: 'asisten_ai_sesi_aktif',
  asistenApi: {
    daftarIngatan: jest.fn(), tambahIngatan: jest.fn(), ubahIngatan: jest.fn(), hapusIngatan: jest.fn(), status: jest.fn(),
  },
}));
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn(), info: jest.fn() } }));
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
const ketikArea = (el, v) => act(() => {
  Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(el, v);
  el.dispatchEvent(new Event('input', { bubbles: true }));
});

const I1 = { id: 'i1', isi: 'Target omzet minimal tumbuh 8% per bulan', kategori: 'preferensi', kategori_label: 'Preferensi', sumber: { sesi_id: 's1', pesan_id: 'p1' }, aktif: true, dibuat: '2026-11-07T02:00:00Z', diperbarui: '2026-11-07T02:00:00Z' };
const I2 = { id: 'i2', isi: 'Tampilkan angka dalam juta rupiah', kategori: 'gaya', kategori_label: 'Gaya jawaban', sumber: 'manual', aktif: true, dibuat: '2026-11-08T02:00:00Z', diperbarui: '2026-11-08T02:00:00Z' };
const I0 = { ...I1, id: 'i0', isi: 'Laporan dikirim tiap Jumat', aktif: false, diperbarui: '2026-11-08T03:00:00Z' };
const daftar = (items, extra = {}) => ({
  items, total: items.length, aktif: items.filter((x) => x.aktif).length, batas_aktif: 50, maks_isi: 300,
  kategori: [{ nilai: 'preferensi', label: 'Preferensi' }, { nilai: 'fakta', label: 'Fakta' }, { nilai: 'gaya', label: 'Gaya jawaban' }],
  ingatan_aktif: true, ...extra,
});

beforeEach(() => {
  jest.clearAllMocks();
  asistenApi.daftarIngatan.mockResolvedValue(daftar([I1, I2, I0]));
  asistenApi.status.mockResolvedValue({ siap: true });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); document.body.innerHTML = ''; window.sessionStorage.clear(); });

async function tampilkan(props = {}) {
  const onNavigate = props.onNavigate || jest.fn();
  await act(async () => { root.render(<><ConfirmDialogHost /><IngatanAIModule onNavigate={onNavigate} {...props} /></>); });
  return onNavigate;
}

test('daftar: aktif dulu lalu terbaru, nonaktif tampil redup "Tidak dipakai", kategori & sumber berlabel, ringkasan, tanpa istilah program', async () => {
  await tampilkan();
  await tunggu(() => q('ingatan-baris-i1'));
  const baris = [...container.querySelectorAll('[data-testid^="ingatan-baris-"]')].map((r) => r.dataset.testid);
  expect(baris).toEqual(['ingatan-baris-i2', 'ingatan-baris-i1', 'ingatan-baris-i0']);
  expect(q('ingatan-baris-i0').dataset.aktif).toBe('0');
  expect(q('ingatan-nonaktif-i0').textContent).toBe('Tidak dipakai');
  expect(q('ingatan-aktif-i0').getAttribute('aria-checked')).toBe('false');
  expect(q('ingatan-aktif-i1').getAttribute('aria-checked')).toBe('true');
  expect(q('ingatan-baris-i2').textContent).toContain('Gaya jawaban');
  expect(q('ingatan-baris-i2').textContent).toContain('Ditambah manual');
  expect(q('ingatan-baris-i1').querySelector('[data-testid="ingatan-buka-sesi"]')).not.toBeNull();
  expect(q('ingatan-ringkas').textContent).toContain('2 dari 50 ingatan aktif terpakai; 1 sedang tidak dipakai');
  expect(q('ingatan-kategori-pil-gaya').textContent).toBe('Gaya jawaban(1)');
  expect(container.textContent).not.toMatch(/preferensi|sesi_id|snake|aktif:/);
  expect(q('ingatan-mati')).toBeNull();
});

test('kosong: EmptyState menjelaskan apa itu ingatan + tombol tambah tetap ada; pil disembunyikan', async () => {
  asistenApi.daftarIngatan.mockResolvedValue(daftar([]));
  const onNavigate = await tampilkan();
  await tunggu(() => q('ingatan-kosong'));
  expect(q('ingatan-kosong').textContent).toContain('Belum ada ingatan');
  expect(q('ingatan-kosong').textContent).toContain('target minimal tumbuh 8%');
  expect(q('ingatan-kategori-pil')).toBeNull();
  expect(q('ingatan-tambah')).not.toBeNull();
  klik(q('ingatan-ke-asisten'));
  expect(onNavigate).toHaveBeenCalledWith('asisten-ai');
});

test('tambah: validasi di dialog lalu POST {isi, kategori}; baris baru muncul', async () => {
  const I3 = { id: 'i3', isi: 'Toko A fokus pakaian anak', kategori: 'preferensi', sumber: 'manual', aktif: true, diperbarui: '2026-11-08T05:00:00Z' };
  asistenApi.tambahIngatan.mockImplementation(async () => {
    asistenApi.daftarIngatan.mockResolvedValue(daftar([I3, I1, I2])); // server sesudah simpan (dimuat ulang diam-diam)
    return { ...I3, sudah_ada: false };
  });
  await tampilkan();
  await tunggu(() => q('ingatan-baris-i1'));
  klik(q('ingatan-tambah'));
  await tunggu(() => q('ingatan-dialog'));
  ketikArea(q('ingatan-isi'), 'ab');
  klik(q('ingatan-simpan'));
  await tunggu(() => q('ingatan-dialog-galat'));
  expect(q('ingatan-dialog-galat').textContent).toContain('minimal 3 huruf');
  expect(asistenApi.tambahIngatan).not.toHaveBeenCalled();
  ketikArea(q('ingatan-isi'), 'x'.repeat(301));
  expect(q('ingatan-panjang').textContent).toBe('301/300');
  ketikArea(q('ingatan-isi'), '  Toko A   fokus pakaian anak ');
  await act(async () => { q('ingatan-simpan').click(); });
  await tunggu(() => q('ingatan-baris-i3'));
  expect(asistenApi.tambahIngatan).toHaveBeenCalledWith({ isi: 'Toko A fokus pakaian anak', kategori: 'preferensi' });
  expect(q('ingatan-dialog')).toBeNull();
  expect(toast.success).toHaveBeenCalled();
});

test('tambah ditolak server (mis. batas tercapai) → pesan di dialog, dialog tetap terbuka', async () => {
  asistenApi.tambahIngatan.mockRejectedValue(Object.assign(new Error('Batas 50 ingatan aktif tercapai.'), { status: 409 }));
  await tampilkan();
  await tunggu(() => q('ingatan-baris-i1'));
  klik(q('ingatan-tambah'));
  await tunggu(() => q('ingatan-dialog'));
  ketikArea(q('ingatan-isi'), 'Laporan dikirim tiap Jumat');
  await act(async () => { q('ingatan-simpan').click(); });
  await tunggu(() => q('ingatan-dialog-galat'));
  expect(q('ingatan-dialog-galat').textContent).toBe('Batas 50 ingatan aktif tercapai.');
  expect(q('ingatan-dialog')).not.toBeNull();
});

test('isi yang sama sudah ada (sudah_ada) → kabar, tanpa baris ganda', async () => {
  asistenApi.tambahIngatan.mockResolvedValue({ ...I2, sudah_ada: true });
  await tampilkan();
  await tunggu(() => q('ingatan-baris-i2'));
  klik(q('ingatan-tambah'));
  await tunggu(() => q('ingatan-dialog'));
  ketikArea(q('ingatan-isi'), I2.isi);
  await act(async () => { q('ingatan-simpan').click(); });
  await tunggu(() => !q('ingatan-dialog'));
  expect(toast.info).toHaveBeenCalledWith('Ingatan yang sama sudah ada, jadi tidak disimpan dua kali.');
  expect(container.querySelectorAll('[data-testid="ingatan-baris-i2"]').length).toBe(1);
});

test('ubah tanpa perubahan → dialog tertutup tanpa PATCH (backend menolak PATCH kosong)', async () => {
  await tampilkan();
  await tunggu(() => q('ingatan-baris-i2'));
  klik(q('ingatan-ubah-i2'));
  await tunggu(() => q('ingatan-dialog'));
  await act(async () => { q('ingatan-simpan').click(); });
  await tunggu(() => !q('ingatan-dialog'));
  expect(asistenApi.ubahIngatan).not.toHaveBeenCalled();
});

test('saklar "Dipakai": PATCH {aktif} saja; 409 (batas aktif) → toast galat, baris tetap', async () => {
  asistenApi.ubahIngatan.mockResolvedValueOnce({ ...I1, aktif: false })
    .mockRejectedValueOnce(Object.assign(new Error('Batas 50 ingatan aktif tercapai.'), { status: 409 }));
  await tampilkan();
  await tunggu(() => q('ingatan-aktif-i1'));
  await act(async () => { q('ingatan-aktif-i1').click(); });
  await tunggu(() => q('ingatan-nonaktif-i1'));
  expect(asistenApi.ubahIngatan).toHaveBeenCalledWith('i1', { aktif: false });
  expect(q('ingatan-aktif-i1').getAttribute('aria-checked')).toBe('false');
  await act(async () => { q('ingatan-aktif-i0').click(); });
  await tunggu(() => toast.error.mock.calls.length > 0);
  expect(asistenApi.ubahIngatan).toHaveBeenLastCalledWith('i0', { aktif: true });
  expect(toast.error).toHaveBeenCalledWith('Batas 50 ingatan aktif tercapai.');
  expect(q('ingatan-aktif-i0').getAttribute('aria-checked')).toBe('false');
});

test('ubah: dialog terisi nilai lama → PATCH /{id} hanya isi yang berubah', async () => {
  const baru = { ...I2, isi: 'Tampilkan angka dalam miliar rupiah' };
  asistenApi.ubahIngatan.mockImplementation(async () => {
    asistenApi.daftarIngatan.mockResolvedValue(daftar([baru, I1]));
    return baru;
  });
  await tampilkan();
  await tunggu(() => q('ingatan-baris-i2'));
  klik(q('ingatan-ubah-i2'));
  await tunggu(() => q('ingatan-dialog'));
  expect(q('ingatan-isi').value).toBe(I2.isi);
  expect(document.body.textContent).toContain('Ubah ingatan');
  ketikArea(q('ingatan-isi'), 'Tampilkan angka dalam miliar rupiah');
  await act(async () => { q('ingatan-simpan').click(); });
  await tunggu(() => !q('ingatan-dialog'));
  expect(asistenApi.ubahIngatan).toHaveBeenCalledWith('i2', { isi: 'Tampilkan angka dalam miliar rupiah' });
  await tunggu(() => q('ingatan-baris-i2').textContent.includes('miliar'));
  expect(asistenApi.daftarIngatan).toHaveBeenCalledTimes(2); // dimuat ulang dari server sesudah simpan
});

test('hapus lewat dialog konfirmasi; Batal = tanpa panggilan', async () => {
  asistenApi.hapusIngatan.mockResolvedValue({ ok: true });
  await tampilkan();
  await tunggu(() => q('ingatan-baris-i1'));
  klik(q('ingatan-hapus-i1'));
  await tunggu(() => q('confirm-dialog'));
  expect(q('confirm-dialog').textContent).toContain('Target omzet minimal tumbuh 8% per bulan');
  klik(q('confirm-dialog-cancel'));
  await tunggu(() => !q('confirm-dialog'));
  expect(asistenApi.hapusIngatan).not.toHaveBeenCalled();
  klik(q('ingatan-hapus-i1'));
  await tunggu(() => q('confirm-dialog-ok'));
  await act(async () => { q('confirm-dialog-ok').click(); });
  await tunggu(() => !q('ingatan-baris-i1'));
  expect(asistenApi.hapusIngatan).toHaveBeenCalledWith('i1');
  expect(toast.success).toHaveBeenCalledWith('Ingatan dihapus.');
});

test('sumber percakapan → Asisten AI dengan sesi itu; sorotan dari chip; saklar admin mati (ingatan_aktif di daftar) → pemberitahuan', async () => {
  asistenApi.daftarIngatan.mockResolvedValue(daftar([I1, I2, I0], { ingatan_aktif: false }));
  const onNavigate = await tampilkan({ deepLinkParams: { ingatan: 'i1' } });
  await tunggu(() => q('ingatan-baris-i1'));
  expect(q('ingatan-baris-i1').dataset.sorot).toBe('1');
  expect(q('ingatan-baris-i2').dataset.sorot).toBeUndefined();
  await tunggu(() => q('ingatan-mati'));
  klik(q('ingatan-baris-i1').querySelector('[data-testid="ingatan-buka-sesi"]'));
  expect(q('ingatan-baris-i1').querySelector('[data-testid="ingatan-buka-sesi-hp"]')).not.toBeNull(); // salinan HP terpisah
  expect(onNavigate).toHaveBeenCalledWith('asisten-ai', { sesi: 's1' });
  expect(window.sessionStorage.getItem('asisten_ai_sesi_aktif')).toBe('s1');
});

test('batas 50 AKTIF tercapai: tombol tambah nonaktif + pemberitahuan (nonaktif tidak dihitung)', async () => {
  asistenApi.daftarIngatan.mockResolvedValue(daftar([...Array.from({ length: 50 }, (_, i) => ({ ...I2, id: `n${i}` })), I0]));
  await tampilkan();
  await tunggu(() => q('ingatan-penuh'));
  expect(q('ingatan-tambah').disabled).toBe(true);
});

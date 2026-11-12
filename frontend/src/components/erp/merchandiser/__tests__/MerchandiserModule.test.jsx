// 12 Nov 2026 (owner K-M1..K-M10) — Portal Manajemen › Analisa Merchandiser: kartu ringkasan per kelas, tabel per model,
// pil kelas menyaring, baris dibuka → rincian per warna/ukuran (tingkat=varian), catatan cakupan + tautan Jembatan SKU.
// Data di bawah ini contoh buatan, bukan data klien.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { apiGet } from '../../../../lib/api';
import MerchandiserModule, { teksMinggu, teksToko } from '../MerchandiserModule';

jest.mock('../../../../lib/api', () => ({ apiGet: jest.fn(), apiPost: jest.fn(), apiFetch: jest.fn() }));
jest.mock('axios', () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn(), interceptors: { request: { use: jest.fn(), eject: jest.fn() } } } }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let root;
let container;
const q = (id) => document.querySelector(`[data-testid="${id}"]`);
const qa = (sel) => [...document.querySelectorAll(sel)];
const tunggu = async (fn) => {
  for (let i = 0; i < 50; i += 1) {
    if (fn()) return;
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
  }
  throw new Error('waktu habis');
};
const klik = (el) => act(() => { el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true })); });

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  apiGet.mockReset();
});
afterEach(() => { act(() => root.unmount()); document.body.innerHTML = ''; });

const baris = (o) => ({
  varian: 4, stok_sistem: 0, nilai_stok_hpp: 0, toko_terlaris: [], terjual: 0, terjual_sebelumnya: 0, laju_mingguan: 0,
  stok_perkiraan: 0, wip: 0, minggu_persediaan: 0, sell_through_persen: null, tren: null, warna: '', ukuran: '', sku: '',
  ...o,
});
const kosong = { label: '', baris: 0, stok: 0, wip: 0, nilai_stok_hpp: 0 };
const DATA = {
  periode: { dari: '2026-10-14', sampai: '2026-11-10', minggu: 4, pembanding: { dari: '2026-09-16', sampai: '2026-10-13' } },
  ambang: { laris: 3, sehat: 8, awas: 16, minggu_jual: 4 },
  tingkat: 'model',
  toko: null,
  ringkasan: {
    mati: { label: 'Mati', baris: 1, stok: 120, wip: 0, nilai_stok_hpp: 6000000 },
    lambat: { label: 'Lambat', baris: 1, stok: 300, wip: 50, nilai_stok_hpp: 9000000 },
    awas: kosong,
    sehat: kosong,
    laris: { label: 'Laris / kurang stok', baris: 1, stok: 20, wip: 0, nilai_stok_hpp: 1000000 },
    habis: kosong,
    kosong,
  },
  baris: [
    baris({ model_id: 'm1', kode: 'MDL-A', nama: 'Kemeja uji A', stok_sistem: 130, stok_perkiraan: 120, nilai_stok_hpp: 6000000,
      terjual_sebelumnya: 3, minggu_persediaan: 999, sell_through_persen: 0, kelas: 'mati', kelas_label: 'Mati',
      saran: 'Stop total. Cuci gudang.' }),
    baris({ model_id: 'm2', kode: 'MDL-B', nama: 'Celana uji B', stok_sistem: 300, stok_perkiraan: 300, wip: 50, terjual: 40,
      laju_mingguan: 10, minggu_persediaan: 35, sell_through_persen: 11.8, nilai_stok_hpp: 9000000, kelas: 'lambat',
      kelas_label: 'Lambat', saran: 'Stop produksi baru. Dorong penjualan.', toko_terlaris: [{ toko: 'Toko Satu', pcs: 30 }] }),
    baris({ model_id: 'm3', kode: 'MDL-C', nama: 'Rok uji C', stok_sistem: 20, stok_perkiraan: 20, terjual: 60, laju_mingguan: 15,
      minggu_persediaan: 1.3, sell_through_persen: 75, nilai_stok_hpp: 1000000, kelas: 'laris', kelas_label: 'Laris / kurang stok',
      saran: 'Tambah produksi.' }),
  ],
  cakupan: {
    baris_penjualan: 100, baris_tertaut: 90, persen_pcs_tertaut: 92.5, pcs_tanpa_model: 14,
    sku_tanpa_model: [{ sku: 'SKU-X', pcs: 10 }, { sku: 'SKU-Y', pcs: 4 }], penjualan_belum_scan_keluar_pcs: 25,
    stok_sistem_pcs: 450,
    catatan: ['25 pcs terjual sejak hitungan stok terakhir belum tercatat scan keluar.',
      '14 pcs penjualan belum terhubung ke model; petakan di layar Jembatan SKU supaya ikut terhitung.'],
  },
  sumber: 'Penjualan: pesanan marketplace yang dihitung omzet.',
};
const VARIAN = {
  ...DATA,
  tingkat: 'varian',
  baris: [
    baris({ model_id: 'm2', kode: 'MDL-B', nama: 'Celana uji B', warna: 'Hitam', ukuran: 'M', sku: 'B-HTM-M', stok_perkiraan: 200,
      terjual: 30, laju_mingguan: 7.5, minggu_persediaan: 26.7, kelas: 'lambat', kelas_label: 'Lambat' }),
    baris({ model_id: 'm2', kode: 'MDL-B', nama: 'Celana uji B', warna: 'Krem', ukuran: 'L', sku: 'B-KRM-L', stok_perkiraan: 100,
      terjual: 0, minggu_persediaan: 999, kelas: 'mati', kelas_label: 'Mati' }),
  ],
};

const mockApi = (data = DATA) => apiGet.mockImplementation(async (url) => {
  if (url.startsWith('/marketing/accounts')) return [{ id: 't1', account_name: 'Toko Satu' }];
  if (url.includes('tingkat=varian')) return VARIAN;
  return data;
});
const barisModel = () => qa('[data-testid^="merch-baris-"]');

test('format: minggu persediaan tak terhingga jadi "> 99"; toko terlaris', () => {
  expect(teksMinggu(999)).toBe('> 99');
  expect(teksMinggu(150)).toBe('> 99');
  expect(teksMinggu(26.66)).toBe('26,7');
  expect(teksToko([{ toko: 'Toko Satu', pcs: 30 }, { toko: 'Toko Dua', pcs: 2.5 }])).toBe('Toko Satu (30), Toko Dua (2,5)');
});

test('ringkasan per kelas, tabel per model, catatan cakupan + tautan Jembatan SKU', async () => {
  mockApi();
  const onNavigate = jest.fn();
  act(() => { root.render(<MerchandiserModule onNavigate={onNavigate} />); });
  await tunggu(() => barisModel().length === 3);

  expect(apiGet).toHaveBeenCalledWith('/merchandiser/analisa?tingkat=model');
  expect(q('merch-kartu-mati').textContent).toContain('1model');
  expect(q('merch-kartu-lambat').textContent).toContain('Rp 9.000.000');
  expect(q('merch-kartu-awas').textContent).toContain('0');
  expect(q('merch-baris-MDL-A').textContent).toContain('> 99');
  expect(q('merch-baris-MDL-A').textContent).toContain('Mati');
  expect(q('merch-baris-MDL-B').textContent).toContain('11,8%');
  expect(q('merch-baris-MDL-B').textContent).toContain('Toko Satu (30)');
  expect(q('merch-cakupan').textContent).toContain('belum terhubung ke model');
  expect(q('merch-cakupan').textContent).toContain('SKU-X (10 pcs)');
  expect(q('merch-sumber').textContent).toContain('92,5%');

  klik(q('merch-buka-jembatan'));
  expect(onNavigate).toHaveBeenCalledWith('sku-bridge');
});

test('pil kelas menyaring tabel; kartu ringkasan juga menyaring', async () => {
  mockApi();
  act(() => { root.render(<MerchandiserModule />); });
  await tunggu(() => barisModel().length === 3);

  expect(q('merch-kelas-lambat').textContent).toBe('Lambat(1)');
  klik(q('merch-kelas-lambat'));
  expect(barisModel().map((el) => el.dataset.testid)).toEqual(['merch-baris-MDL-B']);

  klik(q('merch-kelas-awas'));
  expect(barisModel()).toHaveLength(0);
  expect(q('merch-tabel').textContent).toContain('Tidak ada model yang cocok');
  expect(q('merch-tabel').textContent).toContain('Minggu persediaan');

  klik(q('merch-kelas-all'));
  expect(barisModel()).toHaveLength(3);

  klik(q('merch-kartu-laris'));
  expect(barisModel().map((el) => el.dataset.testid)).toEqual(['merch-baris-MDL-C']);
});

test('baris dibuka → rincian per warna/ukuran dari tingkat=varian + kalimat saran', async () => {
  mockApi();
  act(() => { root.render(<MerchandiserModule />); });
  await tunggu(() => barisModel().length === 3);

  klik(q('merch-buka-MDL-B'));
  await tunggu(() => qa('[data-testid="merch-varian-baris"]').length === 2);

  const url = apiGet.mock.calls.map((c) => c[0]).find((u) => u.includes('tingkat=varian'));
  expect(url).toContain('model_id=m2');
  expect(url).toContain('minggu=4');
  expect(q('merch-saran').textContent).toContain('Stop produksi baru');
  const varian = qa('[data-testid="merch-varian-baris"]');
  expect(varian[0].textContent).toContain('Hitam');
  expect(varian[0].textContent).toContain('B-HTM-M');
  expect(varian[1].textContent).toContain('> 99');

  klik(q('merch-buka-MDL-B'));
  expect(q('merch-rincian')).toBeNull();
});

test('tanpa data: kepala tabel tetap tampil dengan baris kosong, kartu dan pil disembunyikan', async () => {
  mockApi({ ...DATA, ringkasan: {}, baris: [], cakupan: { catatan: [] } });
  act(() => { root.render(<MerchandiserModule />); });
  await tunggu(() => !!q('merch-kosong'));

  expect(q('merch-tabel').textContent).toContain('Kode');
  expect(q('merch-tabel').textContent).toContain('Laju/minggu');
  expect(q('merch-kosong').textContent).toContain('Belum ada model untuk dianalisa');
  expect(q('merch-ringkasan')).toBeNull();
  expect(q('merch-kelas')).toBeNull();
  expect(q('merch-cakupan')).toBeNull();
});

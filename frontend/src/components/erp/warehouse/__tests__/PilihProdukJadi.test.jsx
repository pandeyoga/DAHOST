// 2026-11-10 — barang jadi keluar tanpa scan: cari → centang banyak; barang "bukan stok jual" tidak bisa dicentang.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import PilihProdukJadi, { stokTampil, varianTeks } from '../PilihProdukJadi';
import { apiFetch } from '@/lib/api';

jest.mock('@/lib/api', () => ({ apiFetch: jest.fn() }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let root;
let container;
const q = (id) => document.querySelector(`[data-testid="${id}"]`);
const tunggu = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
const jawab = (body, ok = true) => Promise.resolve({ ok, status: ok ? 200 : 400, json: async () => body });

const ITEMS = [
  { id: 'FG1', code: 'DA-1101-CRL', name: 'Kaos', color: 'Coral', size: 'M', unit: 'pcs', stok_lokasi: 10, masalah: null,
    lokasi: [{ location_id: 'L1', qty: 10 }] },
  { id: 'FG2', code: 'DA-2202-NVY', name: 'Kaos', color: 'Navy', size: '', unit: 'pcs', stok_lokasi: 3,
    masalah: 'DA-2202-NVY: baris stok di lokasi ini dikarantina/diblokir — bukan stok jual.', lokasi: [] },
];

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  apiFetch.mockReset();
});
afterEach(() => { act(() => root.unmount()); document.body.innerHTML = ''; });

test('rumus tampilan stok dan varian', () => {
  expect(stokTampil(ITEMS[0], 'L1')).toBe(10);
  expect(stokTampil({ lokasi: [{ qty: 2 }, { qty: 5 }] }, '')).toBe(7);
  expect(varianTeks(ITEMS[0])).toBe('Coral · M');
  expect(varianTeks(ITEMS[1])).toBe('Navy');
  // nama master sudah memuat varian → tidak ditulis dua kali; "M" di dalam kata ("Lumi") bukan ukuran
  expect(varianTeks({ name: 'Zeta Salur [HITAM · ALLSIZE]', color: 'HITAM', size: 'ALLSIZE' })).toBe('');
  expect(varianTeks({ name: 'Lumi', color: 'Hitam', size: 'M' })).toBe('Hitam · M');
  expect(varianTeks({ name: 'Lunara [Cream · ALL SIZE]', color: 'CREAM', size: 'ALLSIZE' })).toBe('');
});

test('memuat daftar per lokasi, centang memanggil onUbah, barang bermasalah tidak bisa dicentang', async () => {
  apiFetch.mockReturnValue(jawab({ items: ITEMS, total: 2, terpotong: false }));
  const onUbah = jest.fn();
  act(() => {
    root.render(<PilihProdukJadi lokasiId="L1" terpilih={{}} onUbah={onUbah} alasanTolak={(it) => it.masalah} testId="pp" />);
  });
  await tunggu();
  expect(apiFetch.mock.calls[0][0]).toBe('/api/rahaza/fg-pick?limit=50&location_id=L1');
  expect(container.textContent).toContain('DA-1101-CRL');
  expect(container.textContent).toContain('bukan stok jual');
  act(() => { q('pp-centang-DA-1101-CRL').click(); });
  expect(onUbah).toHaveBeenCalledWith(ITEMS[0], true);
  expect(q('pp-centang-DA-2202-NVY').disabled).toBe(true);
  expect(q('pp-jumlah').textContent).toContain('2 barang ditampilkan');
});

test('galat server tampil sebagai pemberitahuan', async () => {
  apiFetch.mockReturnValue(jawab({ detail: 'Akses ditolak' }, false));
  act(() => { root.render(<PilihProdukJadi adaStok terpilih={{}} onUbah={() => {}} testId="pp" />); });
  await tunggu();
  expect(apiFetch.mock.calls[0][0]).toBe('/api/rahaza/fg-pick?limit=50&ada_stok=true');
  expect(q('pp-galat').textContent).toContain('Akses ditolak');
});

test('kata cari dipegang induk (draf): langsung dipakai saat dibuka ulang, ketikan dikirim ke onCari', async () => {
  apiFetch.mockReturnValue(jawab({ items: ITEMS, total: 2, terpotong: false }));
  const onCari = jest.fn();
  act(() => {
    root.render(<PilihProdukJadi lokasiId="L1" terpilih={{}} onUbah={() => {}} cari="kaos coral" onCari={onCari} testId="pp" />);
  });
  await tunggu();
  // tanpa menunggu jeda ketik: permintaan pertama sudah memakai kata cari draf
  expect(apiFetch.mock.calls[0][0]).toBe('/api/rahaza/fg-pick?limit=50&q=kaos+coral&location_id=L1');
  expect(q('pp-cari').value).toBe('kaos coral');
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(q('pp-cari'), 'kaos navy');
    q('pp-cari').dispatchEvent(new Event('input', { bubbles: true }));
  });
  expect(onCari).toHaveBeenCalledWith('kaos navy');
});

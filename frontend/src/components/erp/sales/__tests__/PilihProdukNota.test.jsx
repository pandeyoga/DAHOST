// 2026-11-10 — Nota penjualan baru (Portal Penjualan): pilihan produk harus mudah dibaca.
// Opsi = "SKU · nama · stok N", selalu bisa dicari (SKU atau nama); setelah dipilih kotak menampilkan SKU di baris 1 dan
// nama lengkap di baris 2 (tidak dipotong), stok & HPP di bawahnya. Data di bawah ini contoh buatan, bukan data klien.
import { act, useState } from 'react';
import { createRoot } from 'react-dom/client';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { PilihProduk, labelProduk } from '../DirectSalesModule';

jest.mock('../../../../lib/api', () => ({ apiGet: jest.fn(), apiPost: jest.fn(), apiFetch: jest.fn() }));
jest.mock('axios', () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn(), interceptors: { request: { use: jest.fn(), eject: jest.fn() } } } }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let root;
let container;
const q = (id) => document.querySelector(`[data-testid="${id}"]`);
const tunggu = async (fn) => {
  for (let i = 0; i < 50; i += 1) {
    if (fn()) return;
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
  }
  throw new Error('waktu habis');
};
const klik = (el) => act(() => { el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true })); });
const ketik = (el, v) => act(() => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, v);
  el.dispatchEvent(new Event('input', { bubbles: true }));
});

const NAMA_PANJANG = 'Gamis uji lengan panjang motif bunga kecil dengan nama yang sengaja dibuat sangat panjang';
const STOK = [
  { material_id: 'M1', sku: 'UJI-001-HTM-L', name: NAMA_PANJANG, available_qty: 1200, hpp: 45000, default_price: 0 },
  { material_id: 'M2', sku: 'UJI-002-NVY-M', name: 'Kaos uji', available_qty: 3, hpp: 0, default_price: 0 },
];

function Induk({ awal = '' }) {
  const [v, setV] = useState(awal);
  return <PilihProduk stock={STOK} value={v} onChange={setV} testId="pp" />;
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); document.body.innerHTML = ''; });

test('label opsi berbunyi SKU · nama · stok', () => {
  expect(labelProduk(STOK[0])).toBe(`UJI-001-HTM-L · ${NAMA_PANJANG} · stok 1.200`);
  expect(labelProduk(STOK[1])).toBe('UJI-002-NVY-M · Kaos uji · stok 3');
});

test('daftar selalu bisa dicari (walau sedikit), lalu pilihan tampil dua baris: SKU dan nama lengkap', async () => {
  act(() => { root.render(<Induk />); });
  expect(q('pp-trigger').textContent).toContain('— Pilih produk —');
  expect(q('pp-value')).toBeNull();
  expect(q('pp-stok')).toBeNull();

  klik(q('pp-trigger'));
  await tunggu(() => q('pp-option-M1'));
  expect(q('pp-option-M1').textContent).toBe(labelProduk(STOK[0]));
  const cari = q('pp-panel').querySelector('[data-testid="select-search-input"]');
  expect(cari).not.toBeNull();
  ketik(cari, 'kaos');
  expect(q('pp-option-M1')).toBeNull();
  expect(q('pp-option-M2')).not.toBeNull();
  ketik(cari, 'uji-001');
  expect(q('pp-option-M2')).toBeNull();
  klik(q('pp-option-M1'));

  await tunggu(() => q('pp-value'));
  const isi = q('pp-value');
  const baris = isi.firstElementChild.children; // dua baris: SKU, lalu nama
  expect(baris).toHaveLength(2);
  expect(baris[0].textContent).toBe('UJI-001-HTM-L');
  expect(baris[1].textContent).toBe(NAMA_PANJANG);
  expect(q('pp-nama').textContent).toBe(NAMA_PANJANG);
  // nama lengkap tidak dipotong "…": tidak ada kelas truncate di isi tombol
  expect(isi.querySelector('.truncate')).toBeNull();
  expect(isi.classList.contains('truncate')).toBe(false);
  expect(q('pp-trigger').getAttribute('data-value')).toBe('M1');
  expect(q('pp-stok').textContent).toBe('Stok 1.200 · HPP 45.000');
});

test('HPP nol tidak ditulis; stok tetap tampil', () => {
  act(() => { root.render(<Induk awal="M2" />); });
  expect(q('pp-nama').textContent).toBe('Kaos uji');
  expect(q('pp-stok').textContent).toBe('Stok 3');
});

test('SmartNativeSelect tanpa renderValue tetap satu baris dipotong seperti sebelumnya', () => {
  act(() => {
    root.render(
      <SmartNativeSelect value="a" onChange={() => {}} data-testid="biasa">
        <option value="">— Pilih —</option><option value="a">Pilihan A</option>
      </SmartNativeSelect>,
    );
  });
  expect(q('biasa-value')).toBeNull();
  const label = q('biasa-trigger').querySelector('span');
  expect(label.textContent).toBe('Pilihan A');
  expect(label.classList.contains('truncate')).toBe(true);
});

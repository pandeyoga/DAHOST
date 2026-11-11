// 11 Nov 2026 (owner) — PO berjalan lanjutan:
//  • Tutup PO: kolom "Kurang" hanya angka; kekurangan dijumlah per ukuran di rincian baris; rincian menampilkan model/warna.
//  • Jadwal hutang CMT per PO (Portal Maklon); tagihan CMT membawa CV dari server. Keuangan menampilkan jadwal ini sebagai
//    baris "Terjadwal" di SATU daftar Keuangan › Hutang (uji di finance/__tests__/hutangPiutang.test.jsx).
// Data di bawah ini contoh buatan, bukan data klien.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { apiGet } from '../../../../lib/api';
import POClosureModule, { shortBySize, shortText } from '../POClosureModule';
import JadwalHutangCmtTabel from '../JadwalHutangCmtTabel';
import { cmtToRow } from '../../procurement/SupplierInvoiceModule';

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

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  apiGet.mockReset();
});
afterEach(() => { act(() => root.unmount()); document.body.innerHTML = ''; });

const LINES = [
  { po_item_id: 'a', sku: 'UJI-1-HTM-M', product_name: 'Kemeja uji', color: 'Hitam', size: 'M', ordered: 10, accepted: 8, fulfilled: 8, short: 2, over: 0 },
  { po_item_id: 'b', sku: 'UJI-1-PTH-M', product_name: 'Kemeja uji', color: 'Putih', size: 'M', ordered: 20, accepted: 8, fulfilled: 8, short: 12, over: 0 },
  { po_item_id: 'c', sku: 'UJI-1-HTM-XL', product_name: 'Kemeja uji', color: 'Hitam', size: 'XL', ordered: 30, accepted: 0, fulfilled: 0, short: 30, over: 0 },
  { po_item_id: 'd', sku: 'UJI-1-MRH-M', product_name: 'Kemeja uji', color: 'Merah', size: 'M', ordered: 19, accepted: 0, fulfilled: 0, short: 19, over: 0 },
];

test('kekurangan dijumlah per ukuran (sama dengan server)', () => {
  expect(shortBySize(LINES)).toEqual([['M', 33], ['XL', 30]]);
  expect(shortText(LINES)).toBe('M kurang 33, XL kurang 30');
  expect(shortText([])).toBe('');
});

test('Tutup PO: sel Kurang hanya angka; rincian per ukuran + model/warna di baris rincian', async () => {
  apiGet.mockImplementation(async (url) => {
    if (url.startsWith('/production-pos?') || url === '/production-pos') {
      return [{ id: 'po1', po_number: 'PO-UJI-1', customer_name: 'Gudang FG Sendiri', status: 'In Production' }];
    }
    if (url === '/production-pos/po1/fulfillment') {
      return { total_ordered: 79, total_received: 16, qty_short: 63, qc: { accepted: 16, reject: 0 }, lines: LINES };
    }
    return [];
  });
  act(() => { root.render(<POClosureModule portalId="production" />); });
  await tunggu(() => q('po-closure-short-po1'));
  expect(q('po-closure-short-po1').textContent).toBe('63');
  expect(q('po-closure-row-po1').textContent).not.toContain('kurang');
  klik(q('po-closure-row-po1').querySelector('button'));
  await tunggu(() => q('po-closure-short-size-po1'));
  expect(q('po-closure-short-size-po1').textContent).toBe('Kurang per ukuran: M kurang 33, XL kurang 30');
  const rincian = q('po-closure-lines-po1').textContent;
  expect(rincian).toContain('Kemeja uji · Putih');
  expect(rincian).toContain('UJI-1-MRH-M');
});

const JADWAL = [
  { id: 'sch-1', po_number: 'PO-MKL-1', vendor_name: 'Penjahit Dua', entity: 'SMU', jenis: 'jadwal', scheduled_qty: 40,
    scheduled_amount: 340000, matured_amount: 85000, payable_amount: 85000, remaining_amount: 255000, status: 'berjalan', lines: [] },
  { id: 'perkiraan-po1-vp1', po_number: 'PO-INT-1', vendor_name: 'Penjahit Satu', entity: 'DA', jenis: 'perkiraan',
    scheduled_qty: 40, scheduled_amount: 480000, matured_amount: 120000, remaining_amount: 360000, status: 'berjalan',
    lines: [{ po_item_id: 'pi1', sku: 'UJI-1-HTM-M', product_name: 'Kemeja uji', color: 'Hitam', size: 'M', qty: 40, cmt_rate: 12000, amount: 480000 }] },
];

test('tabel jadwal (Portal Maklon): kolom bisa dibayar + rincian per barang di bawah baris', async () => {
  act(() => { root.render(<JadwalHutangCmtTabel items={JADWAL} />); });
  expect(q('cmt-ap-payable-PO-MKL-1').textContent).toBe('Rp 85.000dari Rp 340.000');
  expect(q('cmt-ap-sisa-PO-INT-1').textContent).toBe('Rp 360.000');
  expect(q('cmt-ap-row-sch-1').textContent).not.toContain('CV Sukma');
  klik(q('cmt-ap-row-perkiraan-po1-vp1').querySelector('button'));
  await tunggu(() => q('cmt-ap-lines-perkiraan-po1-vp1'));
  expect(q('cmt-ap-lines-perkiraan-po1-vp1').textContent).toContain('Kemeja uji · Hitam');
});

test('tagihan CMT di daftar Keuangan memakai CV dari server (PO maklon = CV Sukma)', () => {
  expect(cmtToRow({ id: 'b1', entity: 'SMU', business_type: 'maklon' }).entity).toBe('SMU');
  expect(cmtToRow({ id: 'b2', business_type: 'maklon' }).entity).toBe('SMU');
  expect(cmtToRow({ id: 'b3', business_type: 'internal' }).entity).toBe('DA');
});

// 14 Nov 2026 — form "Buat refund" (Portal Toko › Komplain & Retur) wajib memilih pesanan yang sudah diimpor, sama
// dengan Gudang › Retur Fisik › Catat retur. Data di bawah ini contoh buatan, bukan data klien.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import axios from 'axios';
import { apiGet } from '../../../../lib/api';
import FormRefundPesanan from '../FormRefundPesanan';

jest.mock('../../../../lib/api', () => ({ apiGet: jest.fn(), apiPost: jest.fn(), apiFetch: jest.fn() }));
jest.mock('axios', () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn(), put: jest.fn(), interceptors: { request: { use: jest.fn(), eject: jest.fn() } } } }));

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
  const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, v);
  el.dispatchEvent(new Event('input', { bubbles: true }));
});

const PESANAN_MODEL = {
  id: 'o-1', order_id: '2611140002', tracking_number: 'SPXUJI02', platform: 'shopee', account_id: 'a-1',
  account_name: 'Toko Uji', customer_name: 'Pembeli Uji', status: 'completed', order_date: '2026-11-11',
  active_refunds: [],
  items: [{
    line: 1, product_name: 'Kaftan Uji', variation: 'Navy, M', seller_sku: '1512', quantity: 2, unit_price: 99000,
    link_level: 'model', model_id: 'md-1', model_code: 'MDL-1512', model_name: 'Kaftan', refund_by: [],
    usulan: { variant_id: 'v-navy-m', label: 'MDL-1512-NVY-M · Kaftan · Navy · M', keyakinan: 0.97,
      alasan: ['SKU penjual 1512 = model MDL-1512', 'warna “navy” = Navy'] },
  }],
};
const VARIAN = [
  { id: 'v-navy-m', sku: 'MDL-1512-NVY-M', model_name: 'Kaftan', color_name: 'Navy', size_code: 'M', active: true },
  { id: 'v-merah-m', sku: 'MDL-1512-MRH-M', model_name: 'Kaftan', color_name: 'Merah', size_code: 'M', active: true },
];

function render(props = {}) {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  const p = { authH: { Authorization: 'Bearer x' }, reasons: [{ value: 'ukuran_salah', label: 'Ukuran Salah' }],
    onClose: jest.fn(), onSaved: jest.fn(), onOpenExisting: jest.fn(), onNavigate: jest.fn(), ...props };
  act(() => { root.render(<FormRefundPesanan {...p} />); });
  return p;
}

beforeEach(() => {
  axios.get.mockReset(); axios.post.mockReset(); axios.put.mockReset(); apiGet.mockReset();
  apiGet.mockResolvedValue(VARIAN);
});
afterEach(() => { act(() => root.unmount()); document.body.innerHTML = ''; });

async function cari(teks, hasil) {
  axios.get.mockResolvedValueOnce({ data: { data: hasil } });
  ketik(q('return-order-search'), teks);
  klik(q('return-order-search-btn'));
  await tunggu(() => axios.get.mock.calls.length > 0);
}

test('tanpa kolom nomor pesanan ketik bebas; pesanan tidak ketemu diarahkan ke Impor Data', async () => {
  const p = render();
  expect(document.body.textContent).not.toMatch(/Opsional/);
  expect(q('return-order-input')).toBeNull();
  await cari('9999999', []);
  await tunggu(() => q('return-order-none'));
  expect(axios.get.mock.calls[0][0]).toMatch(/\/api\/marketing\/returns\/order-lookup$/);
  expect(axios.get.mock.calls[0][1].params).toEqual({ q: '9999999' });
  klik(q('return-goto-import'));
  expect(p.onNavigate).toHaveBeenCalledWith('marketing-import', {});
  // simpan tanpa pesanan → galat, tidak ada POST
  klik(q('return-form-simpan'));
  await tunggu(() => q('return-form-galat'));
  expect(q('return-form-galat').textContent).toMatch(/Pilih pesanan/);
  expect(axios.post).not.toHaveBeenCalled();
});

test('baris baru tertaut model: varian usulan terpilih, info pesanan terisi, simpan mengirim pesanan + baris + varian', async () => {
  const p = render();
  await cari('2611140002', [PESANAN_MODEL]);
  await tunggu(() => q('return-order-info'));
  expect(q('return-order-info').textContent).toMatch(/Toko Uji/);
  expect(q('return-order-info').textContent).toMatch(/SPXUJI02/);
  await tunggu(() => q('return-variant-usulan'));
  expect(q('return-variant-usulan').textContent).toMatch(/97% yakin/);
  expect(document.body.textContent).toMatch(/disimpan ke Jembatan SKU/);
  expect(apiGet).toHaveBeenCalledWith('/rahaza/variants?model_id=md-1');
  expect(q('return-qty-input').value).toBe('2');
  expect(q('return-refund-amount-input').value.replace(/\D/g, '')).toBe('198000');
  ketik(q('return-reason-detail'), 'Kebesaran');
  axios.post.mockResolvedValueOnce({ data: { success: true, warehouse: { wh_return_code: 'RET-1' } } });
  klik(q('return-form-simpan'));
  await tunggu(() => axios.post.mock.calls.length > 0);
  const [url, body] = axios.post.mock.calls[0];
  expect(url).toMatch(/\/api\/marketing\/returns$/);
  expect(body).toMatchObject({ order_doc_id: 'o-1', order_line: 1, variant_id: 'v-navy-m', qty: 2,
    refund_type: 'full_refund', refund_amount: 198000, reason_detail: 'Kebesaran' });
  expect(body.price).toBeUndefined();                    // harga dari pesanan (server)
  expect(body.account_id).toBeUndefined();               // toko dari pesanan (server)
  await tunggu(() => p.onSaved.mock.calls.length > 0);
});

test('barang yang sudah direfund: tombol simpan mati dan refund lama bisa dibuka', async () => {
  const p = render();
  const sudah = { ...PESANAN_MODEL, items: [{ ...PESANAN_MODEL.items[0], link_level: 'varian', material_code: 'MDL-1512-NVY-M',
    material_name: 'Kaftan Navy M', refund_by: [{ id: 'r-lama', date: '2026-11-12', status: 'pending', status_label: 'menunggu' }] }] };
  await cari('2611140002', [sudah]);
  await tunggu(() => q('return-sudah-ada'));
  expect(q('return-form-simpan').disabled).toBe(true);
  expect(q('return-variant-select')).toBeNull();
  klik(q('return-buka-r-lama'));
  expect(p.onOpenExisting).toHaveBeenCalledWith('r-lama');
});

test('ubah refund: pesanan & barang hanya ditampilkan, PUT tanpa pesanan/barang/harga', async () => {
  const target = { id: 'r-1', order_id: '2611140002', order_doc_id: 'o-1', account_name: 'Toko Uji', platform: 'shopee',
    product: 'Kaftan Navy M', price: 99000, qty: 1, date: '2026-11-14', reason: 'ukuran_salah', reason_detail: 'Lama',
    refund_type: 'full_refund', refund_amount: 99000, item_condition: 'Baik' };
  const p = render({ editTarget: target });
  expect(q('return-edit-info').textContent).toMatch(/2611140002/);
  expect(q('return-order-search')).toBeNull();
  expect(q('return-edit-legacy')).toBeNull();
  axios.put.mockResolvedValueOnce({ data: { success: true } });
  klik(q('return-form-simpan'));
  await tunggu(() => axios.put.mock.calls.length > 0);
  const body = axios.put.mock.calls[0][1];
  expect(body).toMatchObject({ qty: 1, reason_detail: 'Lama', refund_amount: 99000 });
  expect(Object.keys(body)).not.toEqual(expect.arrayContaining(['order_id', 'order_doc_id', 'price', 'account_id']));
  await tunggu(() => p.onSaved.mock.calls.length > 0);
});

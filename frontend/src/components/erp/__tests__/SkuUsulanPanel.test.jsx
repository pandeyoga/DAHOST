// 14 Nov 2026 — Jembatan SKU › Usulan AI: usulan varian + keyakinan + alasan per kombinasi SKU + variasi, setujui satu
// klik (jalur resmi jembatan), AI hanya mengusulkan, yang tidak bisa dipetakan tampil dengan saran.
// Data di bawah ini contoh buatan, bukan data klien.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { apiGet, apiPost } from '../../../lib/api';
import SkuUsulanPanel from '../SkuUsulanPanel';

jest.mock('../../../lib/api', () => ({ apiGet: jest.fn(), apiPost: jest.fn(), apiFetch: jest.fn(), apiDelete: jest.fn() }));
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn() } }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let root;
let container;
const q = (id) => document.querySelector(`[data-testid="${id}"]`);
const tunggu = async (fn) => {
  for (let i = 0; i < 60; i += 1) {
    if (fn()) return;
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
  }
  throw new Error('waktu habis');
};
const klik = (el) => act(() => { el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true })); });

const baris = (o) => ({ account_id: 'a-1', account_name: 'Toko Uji', pcs: 10, orders: 8, model_code: '', sumber_model: '',
  usulan: null, saran: '', ...o });
const DATA = (ai = { boleh: true, alasan: '' }) => ({
  angka: { baris: 100, varian: 72, model: 17, belum: 11 },
  ringkas: { pasti: 1, ai: 1, tidak: 1, ai_terjawab: 0 },
  total: 3,
  ai,
  rows: [
    baris({ kunci: 'k-pasti', product_name: 'Gamis Polka', variation: 'POLKA BLACK, XL (LD 120 CM)', seller_sku: '3503',
      jenis: 'pasti', model_code: 'MDL-3503', sumber_model: 'sku_penjual',
      usulan: { variant_id: 'v-1', label: 'MDL-3503-PHT-XL · Polkadot Hitam · XL', keyakinan: 0.97, sumber: 'pasti',
        alasan: ['SKU penjual 3503 = model MDL-3503', 'warna “polkadot hitam” = Polkadot Hitam'] } }),
    baris({ kunci: 'k-ai', product_name: 'Tunik Bunga', variation: 'Flower Blue', seller_sku: '1513', jenis: 'ai',
      model_code: 'MDL-1513', saran: 'Varian model MDL-1513 belum bisa dipastikan. Minta usulan AI, atau pilih manual.' }),
    baris({ kunci: 'nv:a-1:kaos|default', product_name: 'Kaos', variation: 'Default', seller_sku: '', jenis: 'tidak',
      saran: 'SKU penjual kosong di marketplace, jadi modelnya tidak terbaca.' }),
  ],
});

function render(props = {}) {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  const p = { reloadKey: 0, onChanged: jest.fn(), onPilihManual: jest.fn(), ...props };
  act(() => { root.render(<SkuUsulanPanel {...p} />); });
  return p;
}

beforeEach(() => { apiGet.mockReset(); apiPost.mockReset(); });
afterEach(() => { act(() => root.unmount()); document.body.innerHTML = ''; });

test('ringkasan tingkat tautan, usulan berkeyakinan + alasan, saran untuk yang tidak bisa dipetakan', async () => {
  apiGet.mockResolvedValue(DATA());
  render();
  await tunggu(() => q('usulan-k-pasti'));
  expect(apiGet.mock.calls[0][0]).toMatch(/^\/sku-bridge\/usulan\?limit=300/);
  expect(q('usulan-ringkas').textContent).toMatch(/72.*tertaut varian.*72%/);
  expect(q('usulan-ringkas').textContent).toMatch(/17.*baru tertaut[\s\S]*model.*17%/);
  expect(q('usulan-k-pasti').textContent).toMatch(/Polkadot Hitam/);
  expect(q('usulan-k-pasti').textContent).toMatch(/97% yakin/);
  expect(q('usulan-k-pasti').textContent).toMatch(/SKU penjual 3503/);
  expect(document.body.textContent).toMatch(/SKU penjual kosong di marketplace/);
  expect(q('setujui-k-ai')).toBeNull();                       // belum ada usulan → tidak bisa disetujui
  expect(q('tanya-ai-k-ai')).not.toBeNull();
});

test('setujui satu klik memanggil jalur resmi jembatan lalu memuat ulang', async () => {
  apiGet.mockResolvedValue(DATA());
  apiPost.mockResolvedValueOnce({ message: 'SKU ditautkan — 8 pesanan ikut diperbarui.' });
  const p = render();
  await tunggu(() => q('setujui-k-pasti'));
  klik(q('setujui-k-pasti'));
  await tunggu(() => apiPost.mock.calls.length > 0);
  expect(apiPost).toHaveBeenCalledWith('/sku-bridge/usulan/setujui', expect.objectContaining({
    kunci: 'k-pasti', variant_id: 'v-1', sumber: 'pasti', keyakinan: 0.97, account_id: 'a-1' }));
  await tunggu(() => p.onChanged.mock.calls.length > 0);
});

test('minta usulan AI dan pilih manual', async () => {
  apiGet.mockResolvedValue(DATA());
  apiPost.mockResolvedValueOnce({ message: 'AI mengusulkan varian untuk 1 dari 1 kombinasi.' });
  const p = render();
  await tunggu(() => q('usulan-minta-ai') && !q('usulan-minta-ai').disabled);
  klik(q('usulan-minta-ai'));
  await tunggu(() => apiPost.mock.calls.length > 0);
  expect(apiPost).toHaveBeenCalledWith('/sku-bridge/usulan/ai', {});
  klik(q('usulan-manual-k-ai'));
  expect(p.onPilihManual).toHaveBeenCalledWith(expect.objectContaining({ kunci: 'k-ai', platform_sku_id: 'k-ai' }));
});

test('AI dimatikan untuk akun ini: tombol mati dan alasannya tampil', async () => {
  apiGet.mockResolvedValue(DATA({ boleh: false, alasan: 'Asisten AI belum diaktifkan untuk akun Anda.' }));
  render();
  await tunggu(() => q('usulan-ai-mati'));
  expect(q('usulan-ai-mati').textContent).toMatch(/belum diaktifkan/);
  expect(q('usulan-minta-ai').disabled).toBe(true);
  expect(q('tanya-ai-k-ai')).toBeNull();
});

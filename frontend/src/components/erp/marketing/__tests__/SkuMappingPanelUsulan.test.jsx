// Usulan Pemetaan SKU (11 Nov 2026): usulan dari NOMOR MODEL + warna + ukuran ditulis apa adanya,
// bukan "100% mirip" — staf harus tahu usulan itu pasti, sedangkan usulan nama hanya kemiripan.
// Tanpa @testing-library/react (pola sama dengan asisten/__tests__): createRoot + act.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import SkuMappingPanel from '../SkuMappingPanel';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const DATA = {
  ok: true,
  unmapped: [
    { platform_sku_id: 'P-KODE', sku_label: 'P-KODE', key_kind: 'sku_platform', seller_sku: '1512',
      product_name_raw: 'MELA ONE SET', variation_raw: 'Red Elegant, M / STANDAR', rows: 3, pcs: 3,
      revenue: 180000,
      suggestion: { catalog_item_id: 'it-1', name: 'MELA [Red Elegant · M]', sku: 'DA-1512-RDE-M',
                    score: 1.0, sumber: 'kode_model' } },
    { platform_sku_id: 'P-NAMA', sku_label: 'P-NAMA', key_kind: 'sku_platform', seller_sku: '',
      product_name_raw: 'Kulot Rayon', variation_raw: 'Hitam, M', rows: 1, pcs: 1, revenue: 50000,
      suggestion: { catalog_item_id: 'it-2', name: 'Kulot Rayon Panjang', sku: 'DA-5503-HTM-M',
                    score: 0.8 } },
  ],
  unmapped_total: 2,
  groups: [],
  catalog_items: [{ id: 'it-1', name: 'MELA [Red Elegant · M]', sku: 'DA-1512-RDE-M' },
                  { id: 'it-2', name: 'Kulot Rayon Panjang', sku: 'DA-5503-HTM-M' }],
  catalog_items_total: 2,
};

let root;
let container;
beforeEach(() => {
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => DATA }));
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
  delete global.fetch;
});

async function tunggu(id) {
  for (let i = 0; i < 40; i += 1) {
    const el = document.querySelector(`[data-testid="${id}"]`);
    if (el) return el;
    // eslint-disable-next-line no-await-in-loop
    await act(async () => { await new Promise((r) => setTimeout(r, 25)); });
  }
  throw new Error(`tidak muncul: ${id}`);
}

test('usulan kode model ditulis "nomor model, warna & ukuran cocok", usulan nama tetap persen mirip', async () => {
  await act(async () => { root.render(<SkuMappingPanel sessionId="s1" token="t" onDone={() => {}} />); });
  const kode = await tunggu('sku-map-apply-suggestion-P-KODE');
  const nama = await tunggu('sku-map-apply-suggestion-P-NAMA');
  expect(kode.textContent).toContain('nomor model, warna & ukuran cocok');
  expect(kode.textContent).not.toContain('mirip');
  expect(nama.textContent).toContain('80% mirip');
});

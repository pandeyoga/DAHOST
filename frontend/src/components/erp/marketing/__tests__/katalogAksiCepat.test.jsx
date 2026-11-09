// Aksi cepat Manajemen Katalog + harga jual per SKU (klarifikasi owner 9 Nov 2026 §B & §D).
// Bentuk jawaban = backend worktree katalog (routes/marketing_catalog_items.py bulk-transition, routes/
// marketing_catalog_tools.py, routes/rahaza_sku_prices.py). Tanpa @testing-library/react — createRoot + act.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import CatalogItemsView from '../CatalogItemsView';
import CatalogFromMasterModule from '../CatalogFromMasterModule';
import SkuPriceModule from '../../SkuPriceModule';
import CatalogTidyDialog from '../CatalogTidyDialog';
import CatalogPriceUrlDialog from '../CatalogPriceUrlDialog';
import { toast } from 'sonner';

jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn(), info: jest.fn() } }));
// lib/entitas (dipakai PageLayout) mengimpor axios versi ESM yang tidak diubah jest; cukup tiruan interceptor.
jest.mock('axios', () => ({ __esModule: true, default: { interceptors: { request: { use: jest.fn(), eject: jest.fn() } } } }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let root;
let container;
const q = (id) => document.querySelector(`[data-testid="${id}"]`);
const tunggu = async (fn) => {
  let galat;
  for (let i = 0; i < 60; i += 1) {
    try { if (fn()) return; } catch (e) { galat = e; }
    await act(async () => { await new Promise((r) => setTimeout(r, 15)); });
  }
  throw galat || new Error('waktu habis');
};
const klik = async (el) => {
  await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true })); });
};
const jawab = (body, ok = true) => Promise.resolve({ ok, json: async () => body, headers: { get: () => '' } });

beforeEach(() => {
  jest.clearAllMocks();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  window.confirm = jest.fn(() => true);
});
afterEach(() => { act(() => root.unmount()); document.body.innerHTML = ''; delete global.fetch; });

const item = (i, extra = {}) => ({
  id: `it-${i}`, sku: `UJA-HTM-${i}`, name: `Blus Uji ${i}`, catalog_status: 'DRAFT', publish_state: 'draft',
  harga_jual: 0, retail_price_master: 89000, retail_price_source: 'sku', product_status: null, fg_code: `UJA-HTM-${i}`,
  available: 3, ...extra,
});

async function tampilItem(items, extraProps = {}) {
  const onReload = jest.fn();
  await act(async () => {
    root.render(
      <CatalogItemsView catalog={{ id: 'cat-1', name: 'Katalog Uji' }} token="t" items={items}
        stockSummary={{ by_status: { DRAFT: items.length }, by_product_status: { stop: 1, dead: 0, belum_diisi: items.length - 1 } }}
        statusOptions={[]} filters={{ catalogStatus: [] }} onFilterChange={jest.fn()} onReload={onReload}
        baseFilters={{}} onBaseFilter={{}} {...extraProps} />,
    );
  });
  return onReload;
}

test('baris katalog: status produk & harga resmi master per SKU tampil', async () => {
  await tampilItem([item(1, { product_status: 'stop' }), item(2, { harga_jual: 89000 })]);
  expect(q('item-product-status-UJA-HTM-1').textContent).toBe('Stop');
  expect(q('item-official-UJA-HTM-1').textContent).toContain('89.000');
  expect(q('item-official-UJA-HTM-2')).toBeNull();               // sama dengan harga jual → tidak diulang
  expect(q('catalog-filter-product-status')).not.toBeNull();
  expect(q('catalog-price-url-open').textContent).toContain('Unggah harga');
});

test('baris aksi massal lengkap + "pilih semua hasil saring"', async () => {
  const items = Array.from({ length: 30 }, (_, i) => item(i + 1));
  await tampilItem(items);
  await klik(q('catalog-select-page'));
  await tunggu(() => q('catalog-bulk-bar'));
  expect(q('bulk-count').textContent).toBe('25 item dipilih');
  for (const id of ['bulk-fill-price', 'bulk-publish', 'bulk-unpublish', 'bulk-archive', 'bulk-restore', 'bulk-more']) {
    expect(q(id)).not.toBeNull();
  }
  expect(container.textContent).not.toContain('tidak ada di aksi massal');
  await klik(q('bulk-select-all-filtered'));
  expect(q('bulk-count').textContent).toBe('30 item dipilih');
});

test('tayangkan yang ber-URL: pratinjau → konfirmasi berisi angka → jalankan → toast Batalkan', async () => {
  const calls = [];
  global.fetch = jest.fn((url, opts) => {
    const body = opts?.body ? JSON.parse(opts.body) : null;
    calls.push({ url, body });
    if (url.includes('/runs/run-1/undo')) return jawab({ message: 'Dibatalkan: 1 item dikembalikan' });
    if (body?.dry_run) {
      return jawab({ would_change: 1, skipped: 1, skip_summary: { 'belum ada URL produk': 1 } });
    }
    return jawab({ message: '1 item diperbarui (Tayangkan yang ber-URL) · 1 dilewati', run_id: 'run-1', changed: 1 });
  });
  const onReload = await tampilItem([item(1, { platform_url: 'https://shopee.co.id/x' }), item(2)]);
  await klik(q('catalog-select-page'));
  await klik(q('bulk-publish'));
  await tunggu(() => toast.success.mock.calls.length > 0);
  expect(calls[0].url).toContain('/api/marketing/catalogs/cat-1/items/bulk-transition');
  expect(calls[0].body).toEqual({ item_ids: ['it-1', 'it-2'], action: 'publish', dry_run: true });
  const pesan = window.confirm.mock.calls[0][0];
  expect(pesan).toContain('1 dari 2 item akan diubah');
  expect(pesan).toContain('1 belum ada URL produk');
  expect(pesan).toContain('URL produk sah sendiri');
  expect(calls[1].body).toEqual({ item_ids: ['it-1', 'it-2'], action: 'publish', reason: '' });
  const [, opsi] = toast.success.mock.calls[0];
  expect(opsi.action.label).toBe('Batalkan');
  expect(onReload).toHaveBeenCalled();
  await act(async () => { opsi.action.onClick(); });
  await tunggu(() => calls.some((c) => c.url.includes('/api/marketing/catalog-tools/runs/run-1/undo')));
});

test('aksi massal tanpa perubahan: tidak ada konfirmasi, alasannya disebut', async () => {
  global.fetch = jest.fn(() => jawab({ would_change: 0, skipped: 2, skip_summary: { 'tidak diarsipkan': 2 } }));
  await tampilItem([item(1), item(2)]);
  await klik(q('catalog-select-page'));
  await klik(q('bulk-restore'));
  await tunggu(() => toast.info.mock.calls.length > 0);
  expect(toast.info.mock.calls[0][0]).toContain('2 tidak diarsipkan');
  expect(window.confirm).not.toHaveBeenCalled();
  expect(global.fetch).toHaveBeenCalledTimes(1);
});

test('isi dari master: harga & status per SKU tampil, model tercentang tanpa SKU Stop/Dead', async () => {
  const calls = [];
  global.fetch = jest.fn((url, opts) => {
    calls.push({ url, body: opts?.body ? JSON.parse(opts.body) : null });
    if (url.includes('/api/marketing/accounts')) return jawab([{ id: 'acc-1', account_code: 'SHP-U', account_name: 'Toko Uji', platform: 'shopee' }]);
    if (url.includes('/assign-from-master')) {
      return jawab({ message: '1 item katalog dibuat', results: [{ account_id: 'acc-1', account_name: 'Toko Uji', created: 1, skipped: 0, rejected: 0, skipped_status: 0, notes: [] }] });
    }
    return jawab({ products: [{
      model_id: 'm-1', code: 'UJA', name: 'Blus Uji', category_name: 'Blouse', hpp: 40000, retail_price_master: 0,
      retail_price_min: 85000, retail_price_max: 89000, variant_count: 2, in_catalog_count: 0,
      variants: [
        { fg_material_id: 'fg-1', code: 'UJA-HTM-M', color: 'Hitam', size_code: 'M', hpp: 40000, sellable_stock: 2,
          in_catalog: false, retail_price_master: 89000, retail_price_source: 'sku', product_status: 'best_seller' },
        { fg_material_id: 'fg-2', code: 'UJA-HTM-S', color: 'Hitam', size_code: 'S', hpp: 40000, sellable_stock: 0,
          in_catalog: false, retail_price_master: 85000, retail_price_source: 'sku', product_status: 'stop' },
      ],
    }] });
  });
  await act(async () => { root.render(<CatalogFromMasterModule token="t" />); });
  await tunggu(() => q('cfm-toggle-UJA'));
  await klik(q('cfm-toggle-UJA'));
  await tunggu(() => q('cfm-price-UJA-HTM-M'));
  expect(q('cfm-price-UJA-HTM-M').textContent).toContain('89.000');
  expect(q('cfm-status-UJA-HTM-S').textContent).toBe('Stop');
  await klik(q('cfm-model-UJA'));
  expect(q('cfm-variant-UJA-HTM-M').getAttribute('data-state')).toBe('checked');
  expect(q('cfm-variant-UJA-HTM-S').getAttribute('data-state')).toBe('unchecked');   // Stop tidak ikut
});

test('harga jual per SKU: isi sama untuk semua SKU → Simpan mengirim perubahan saja', async () => {
  const calls = [];
  global.fetch = jest.fn((url, opts) => {
    calls.push({ url, method: opts?.method || 'GET', body: opts?.body ? JSON.parse(opts.body) : null });
    if (opts?.method === 'POST') return jawab({ message: '1 harga SKU disimpan', changed: 1 });
    return jawab({ totals: { models: 1, skus: 2, priced: 1, empty: 1 }, models: [{
      model_id: 'm-1', code: 'UJA', name: 'Blus Uji', category_name: 'Blouse', model_retail_price: 0, sku_count: 2,
      priced_count: 1, price_min: 89000, price_max: 89000,
      variants: [
        { fg_id: 'fg-1', sku: 'UJA-HTM-M', color: 'Hitam', size_code: 'M', retail_price_master: 89000, product_status: null },
        { fg_id: 'fg-4', sku: 'UJA-HTM-L', color: 'Hitam', size_code: 'L', retail_price_master: 0, product_status: 'slow' },
      ],
    }] });
  });
  await act(async () => { root.render(<SkuPriceModule token="t" />); });
  await tunggu(() => q('sku-price-toggle-UJA'));
  expect(q('sku-price-summary').textContent).toContain('2 SKU di 1 model');
  expect(q('sku-price-save').disabled).toBe(true);
  await klik(q('sku-price-toggle-UJA'));
  await tunggu(() => q('sku-price-fill-all-UJA'));
  const isi = q('sku-price-fill-all-UJA');
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(isi, '89000');
    isi.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await klik(q('sku-price-fill-all-apply-UJA'));
  await tunggu(() => !q('sku-price-save').disabled);
  expect(q('sku-price-save').textContent).toContain('(1)');            // fg-1 sudah 89.000 → tidak dihitung
  await klik(q('sku-price-save'));
  await tunggu(() => calls.some((c) => c.method === 'POST'));
  const post = calls.find((c) => c.method === 'POST');
  expect(post.url).toContain('/api/rahaza/sku-prices');
  expect(post.body).toEqual({ changes: [{ fg_id: 'fg-4', harga: 89000 }] });
  expect(window.confirm.mock.calls[0][0]).toContain('Harga jual toko yang sudah ada TIDAK berubah');
});

test('rapikan item tersembunyi: pratinjau angka → jalankan dengan angka pratinjau', async () => {
  const calls = [];
  global.fetch = jest.fn((url, opts) => {
    calls.push({ url, method: opts?.method || 'GET', body: opts?.body ? JSON.parse(opts.body) : null });
    if (url.endsWith('/hidden/apply')) return jawab({ message: 'Rapikan selesai', run_id: 'run-9' });
    return jawab({
      message: '640 item tersembunyi: 451 kembar, 189 tunggal.',
      summary: { hidden: 640, twins: 451, singles: 189, twins_copy_price: 450, twins_copy_coret: 450, twins_copy_url: 289,
        twins_publish: 289, twins_conflict: 1, singles_publish: 66, new_catalogs: 0, skipped: 0 },
      twins_sample: [{ sku: 'UJA-HTM-M', name: 'Blus Uji', toko: 'SHP-U · Toko Uji', salin: ['harga_jual', 'platform_url'], tayang: true, catatan: '' }],
      singles_sample: [], skipped: [], new_catalogs: [],
    });
  });
  const onDone = jest.fn();
  await act(async () => { root.render(<CatalogTidyDialog open token="t" onClose={jest.fn()} onDone={onDone} />); });
  await tunggu(() => q('catalog-tidy-summary'));
  expect(q('catalog-tidy-summary').textContent).toContain('451');
  expect(q('catalog-tidy-dialog-simpan').textContent).toBe('Rapikan 640 item');
  await klik(q('catalog-tidy-dialog-simpan'));
  await tunggu(() => onDone.mock.calls.length > 0);
  const ap = calls.find((c) => c.url.endsWith('/hidden/apply'));
  expect(ap.body).toEqual({ expect_twins: 451, expect_singles: 189 });
  expect(onDone.mock.calls[0][0].run_id).toBe('run-9');
});

test('unggah harga & URL: periksa berkas (pratinjau) lalu terapkan', async () => {
  const calls = [];
  global.fetch = jest.fn((url) => {
    calls.push(url);
    if (url.includes('apply=true')) return jawab({ message: '2 item diperbarui dari berkas', run_id: 'run-x', summary: { changes: 2 } });
    return jawab({ message: '2 item akan diubah · 1 baris bermasalah', errors: ['Baris 4 (UJA-X): URL produk tidak sah'],
      summary: { rows: 3, changes: 2, unchanged: 0, errors: 1, price: 2, coret: 0, url: 1, publish: 1 },
      sample: [{ row: 2, sku: 'UJA-HTM-M', katalog: 'Katalog Uji', harga_jual: [0, 89000], harga_coret: null, url: 'https://x.test/a', tayang: true }] });
  });
  const onDone = jest.fn();
  await act(async () => {
    root.render(<CatalogPriceUrlDialog open catalog={{ id: 'cat-1', name: 'Katalog Uji' }} token="t" onClose={jest.fn()} onDone={onDone} />);
  });
  await tunggu(() => q('price-url-file'));
  const inp = q('price-url-file');
  const berkas = new File(['xlsx'], 'harga.xlsx');
  Object.defineProperty(inp, 'files', { value: [berkas] });
  await act(async () => { inp.dispatchEvent(new Event('change', { bubbles: true })); });
  expect(q('price-url-dialog-simpan').textContent).toBe('Periksa berkas');
  await klik(q('price-url-dialog-simpan'));
  await tunggu(() => q('price-url-preview'));
  expect(calls[0]).toContain('/api/marketing/catalog-tools/price-url/upload?catalog_id=cat-1&apply=false&publish=true');
  expect(q('price-url-errors').textContent).toContain('URL produk tidak sah');
  expect(q('price-url-dialog-simpan').textContent).toBe('Terapkan 2 perubahan');
  await klik(q('price-url-dialog-simpan'));
  await tunggu(() => onDone.mock.calls.length > 0);
  expect(calls[1]).toContain('apply=true');
});

/**
 * Gudang › Scan Keluar Penjualan › "Pilih tanpa scan" (14 Nov 2026, keluhan owner: "ketika saja saya klik diluar
 * popup maka saya harus mulai dari awal karena hilang").
 *   • klik di luar popup tidak menutup dan tidak menghapus pilihan;
 *   • × / Esc / Batal dengan pilihan terisi → konfirmasi; "Kembali ke formulir" = pilihan utuh;
 *   • pilihan + jumlah + kata cari = draf per lokasi & jenis (sessionStorage) — bertahan saat layar dibuka ulang,
 *     hilang hanya setelah disimpan atau dibuang dengan sengaja; id pilihan sama saat disimpan ulang.
 * Tanpa @testing-library/react (peer @testing-library/dom tidak terpasang) — createRoot + act.
 */
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { ConfirmDialogHost } from '@/components/ui/confirm-dialog';
import { apiFetch } from '@/lib/api';
import WHScanOutModule, { bacaDrafPilih, kunciDrafPilih, tulisDrafPilih } from '../WHScanOutModule';

jest.mock('@/lib/api', () => ({ apiFetch: jest.fn() }));
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn(), info: jest.fn() } }));
jest.mock('axios', () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn(), interceptors: { request: { use: jest.fn(), eject: jest.fn() } } } }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const ITEM = { id: 'FG1', code: 'DA-1101-CRL', name: 'Kaos', color: 'Coral', size: 'M', unit: 'pcs', stok_lokasi: 10, masalah: null };
const LOKASI = [{ id: 'L1', code: 'GJ', name: 'Gudang Jadi', fg_qty: 10 }];
const KUNCI = kunciDrafPilih('L1', 'scan');

let root;
let container;
let luar;
let pickBodies;
const q = (id) => document.querySelector(`[data-testid="${id}"]`);
const klik = (el) => act(() => { el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true })); });
const ketik = (el, v) => act(() => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, v);
  el.dispatchEvent(new Event('input', { bubbles: true }));
});
const jeda = (ms = 30) => act(async () => { await new Promise((r) => setTimeout(r, ms)); });
const tunggu = async (fn) => {
  let galat;
  for (let i = 0; i < 80; i += 1) {
    try { if (fn()) return; } catch (e) { galat = e; }
    // eslint-disable-next-line no-await-in-loop
    await jeda(20);
  }
  throw galat || new Error('waktu habis');
};
const ketukLuar = async () => {
  await jeda();
  act(() => {
    luar.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, cancelable: true, button: 0 }));
    luar.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, button: 0 }));
    luar.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
  });
  await jeda();
};
const tekanEsc = async () => {
  await jeda();
  act(() => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })); });
  await jeda();
};
const qty = () => q(`scan-out-pilih-qty-${ITEM.code}`);
const jawab = (body, ok = true, status = 200) => Promise.resolve({ ok, status, json: async () => body });

const pasang = () => act(async () => {
  root.render(<><ConfirmDialogHost /><WHScanOutModule token="t" user={{ role: 'owner' }} /></>);
  await new Promise((r) => setTimeout(r, 20));   // jawaban lokasi/toko/hari ini masuk di dalam act
});
const bongkar = () => act(() => root.render(<ConfirmDialogHost />));
const bukaPopup = async () => {
  await tunggu(() => q('scan-out-pilih') && !q('scan-out-pilih').disabled);
  klik(q('scan-out-pilih'));
  await tunggu(() => q('scan-out-pilih-form'));
};
const pilihBarang = async (jumlah) => {
  await tunggu(() => q(`scan-out-pilih-cari-centang-${ITEM.code}`));
  klik(q(`scan-out-pilih-cari-centang-${ITEM.code}`));
  await tunggu(() => qty());
  ketik(qty(), jumlah);
};

beforeEach(() => {
  window.localStorage.setItem('whScanOut.location', 'L1');
  luar = document.createElement('button');
  document.body.appendChild(luar);
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  pickBodies = [];
  apiFetch.mockReset();
  apiFetch.mockImplementation((url, opts = {}) => {
    if (url.startsWith('/api/wh/scan-out/locations')) return jawab(LOKASI);
    if (url.startsWith('/api/wh/scan-out/stores')) return jawab([]);
    if (url.startsWith('/api/wh/scan-out/today')) return jawab({ date: '2026-11-14', can_scan: true, lines: [], totals: {} });
    if (url.startsWith('/api/rahaza/fg-pick')) return jawab({ items: [ITEM], total: 1, terpotong: false });
    if (url.startsWith('/api/wh/scan-out/pick')) {
      pickBodies.push(JSON.parse(opts.body));
      return jawab({ results: [{ result: 'accepted', line: { flags: [] } }], accepted: 1, pcs: 3 });
    }
    return jawab({});
  });
});
afterEach(() => {
  act(() => root.unmount());
  document.body.innerHTML = '';
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe('draf pilihan (sessionStorage)', () => {
  test('per lokasi & jenis; kosong = dihapus; data rusak / penyimpanan terkunci tidak membuat layar galat', () => {
    expect(kunciDrafPilih('L1', 'batal_kirim')).not.toBe(KUNCI);
    tulisDrafPilih({ kunci: KUNCI, pilihan: [{ item: ITEM, qty: '3', csid: 'c-1' }], cari: 'kaos' });
    expect(bacaDrafPilih(KUNCI)).toEqual({ kunci: KUNCI, pilihan: [{ item: ITEM, qty: '3', csid: 'c-1' }], cari: 'kaos' });
    expect(bacaDrafPilih(kunciDrafPilih('L1', 'batal_kirim')).pilihan).toEqual([]);
    tulisDrafPilih({ kunci: KUNCI, pilihan: [], cari: '' });
    expect(window.sessionStorage.getItem(KUNCI)).toBeNull();
    window.sessionStorage.setItem(KUNCI, '{rusak');
    expect(bacaDrafPilih(KUNCI).pilihan).toEqual([]);
    const asli = Storage.prototype.getItem;
    Storage.prototype.getItem = () => { throw new Error('terkunci'); };
    try { expect(bacaDrafPilih(KUNCI).pilihan).toEqual([]); } finally { Storage.prototype.getItem = asli; }
  });
});

describe('Pilih tanpa scan', () => {
  test('klik di luar tidak menutup popup dan tidak menghapus pilihan; Esc → konfirmasi → kembali utuh', async () => {
    await pasang();
    await bukaPopup();
    await pilihBarang('3');
    ketik(q('scan-out-pilih-cari-cari'), 'kaos');

    await ketukLuar();
    await ketukLuar();
    expect(q('scan-out-pilih-form')).not.toBeNull();
    expect(q('confirm-dialog')).toBeNull();
    expect(qty().value).toBe('3');
    expect(q('scan-out-pilih-cari-cari').value).toBe('kaos');

    await tekanEsc();
    expect(q('confirm-dialog')).not.toBeNull();
    expect(q('confirm-dialog').textContent).toContain('Buang pilihan barang?');
    expect(q('confirm-dialog').textContent).toContain('1 barang (3 pcs)');
    klik(q('confirm-dialog-cancel'));
    await jeda();
    expect(q('scan-out-pilih-form')).not.toBeNull();
    expect(qty().value).toBe('3');
  });

  test('layar ditutup lalu dibuka lagi (pindah menu / muat ulang): draf pilihan, jumlah, dan kata cari kembali', async () => {
    await pasang();
    await bukaPopup();
    await pilihBarang('3');
    ketik(q('scan-out-pilih-cari-cari'), 'kaos');
    const csid = bacaDrafPilih(KUNCI).pilihan[0].csid;
    expect(csid).toBeTruthy();

    bongkar();
    expect(q('scan-out-pilih-form')).toBeNull();
    await pasang();
    await tunggu(() => q('scan-out-pilih-draf'));
    expect(q('scan-out-pilih-draf').textContent).toContain('draf 1 barang');
    await bukaPopup();
    await tunggu(() => qty());
    expect(qty().value).toBe('3');
    expect(q('scan-out-pilih-cari-cari').value).toBe('kaos');

    // simpan: id pilihan sama dengan draf (simpan ulang tidak memotong stok dua kali); draf selesai
    klik(q('scan-out-pilih-form-simpan'));
    await tunggu(() => pickBodies.length === 1 && !q('scan-out-pilih-form'));
    expect(pickBodies[0].items).toEqual([{ material_id: 'FG1', qty: 3, client_scan_id: csid, code: ITEM.code }]);
    await tunggu(() => !q('scan-out-pilih-draf'));
    expect(window.sessionStorage.getItem(KUNCI)).toBeNull();
  });

  test('Batal dengan pilihan → "Buang pilihan" menghapus draf; popup dibuka lagi kosong', async () => {
    await pasang();
    await bukaPopup();
    await pilihBarang('2');
    klik(q('scan-out-pilih-form-batal'));
    await tunggu(() => q('confirm-dialog'));
    expect(q('confirm-dialog-ok').textContent).toBe('Buang pilihan');
    klik(q('confirm-dialog-ok'));
    await tunggu(() => !q('scan-out-pilih-form'));
    expect(window.sessionStorage.getItem(KUNCI)).toBeNull();
    expect(q('scan-out-pilih-draf')).toBeNull();

    await bukaPopup();
    await jeda();
    expect(qty()).toBeNull();
    expect(q('scan-out-pilih-cari-cari').value).toBe('');
  });

  test('draf "Keluar" tidak muncul di mode "Batal kirim" (dan sebaliknya)', async () => {
    await pasang();
    await bukaPopup();
    await pilihBarang('4');
    await ketukLuar();
    // tutup tanpa membuang: bongkar layar (pindah menu), pasang lagi, ganti mode
    bongkar();
    await pasang();
    await tunggu(() => q('scan-out-pilih-draf'));
    klik(q('scan-out-mode-cancel'));
    await tunggu(() => !q('scan-out-pilih-draf'));
    await bukaPopup();
    await jeda();
    expect(qty()).toBeNull();
    expect(q('scan-out-pilih-form').textContent).toContain('Batal kirim tanpa scan');
  });
});

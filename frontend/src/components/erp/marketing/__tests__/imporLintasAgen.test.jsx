// Kebutuhan lintas-agen AI-impor (9 Nov 2026): periode GMV Max di wizard satu berkas & satu popup AI pemeta.
// Tanpa @testing-library/react — createRoot + act (pola katalogAksiCepat.test.jsx).
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import axios from 'axios';
import PopupAIPemeta from '../PopupAIPemeta';
import DataImportWizard from '../DataImportWizard';
import { hariIniWIB } from '@/components/ui/date-picker';
import { cekPeriodeLaporan } from '../imporPaketAturan';

jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn(), info: jest.fn() } }));
jest.mock('axios', () => ({
  __esModule: true,
  default: {
    get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn(),
    interceptors: { request: { use: jest.fn(), eject: jest.fn() } },
  },
}));
// Pilihan toko Radix tidak bisa dioperasikan di jsdom — diganti tombol yang memilih satu toko.
jest.mock('../pickers/MarketingPickers', () => {
  const R = require('react');
  return {
    MarketingAccountSelect: ({ onChange, testId }) => R.createElement(
      'button', { type: 'button', 'data-testid': testId, onClick: () => onChange('TTK-01') }, 'pilih toko'),
    MarketingCreatorSelect: () => null,
    MarketingHostSelect: () => null,
  };
});

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
const jawab = (body, ok = true) => Promise.resolve({ ok, json: async () => body });

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); document.body.innerHTML = ''; delete global.fetch; });

describe('Periode laporan GMV Max — aturan isian', () => {
  test('wajib, mulai ≤ selesai, tidak menyeberang bulan', () => {
    expect(cekPeriodeLaporan('', '2026-08-31')).toMatch(/Isi Periode mulai/);
    expect(cekPeriodeLaporan('2026-08-01', '')).toMatch(/Isi Periode mulai/);
    expect(cekPeriodeLaporan('2026-08-31', '2026-08-01')).toMatch(/tidak boleh sesudah/);
    expect(cekPeriodeLaporan('2026-07-15', '2026-08-14')).toMatch(/menyeberang bulan/);
    expect(cekPeriodeLaporan('2026-08-01', '2026-08-31')).toBe('');
    expect(cekPeriodeLaporan('2026-08-05', '2026-08-05')).toBe('');
  });
});

describe('PopupAIPemeta — satu pintu AI pemeta', () => {
  test('memakai endpoint impor-paket, hanya usulan diterima yang dicentang, hasil terapkan diteruskan', async () => {
    const hasil = { ok: true, mapping: [{ column: 'Biaya', field: 'spend' }], mapping_report: { ready: true } };
    global.fetch = jest.fn((url, opt) => {
      if (url.endsWith('/sesi/S-1/ai-pemeta')) {
        return jawab({
          pesan: '1 usulan boleh dipakai (konfirmasi dulu).',
          usulan: [
            { kolom: 'Biaya', field: 'spend', field_label: 'Biaya Iklan (Rp)', keyakinan: 0.9, diterima: true, catatan: 'Boleh dipakai bila Anda setuju.' },
            { kolom: 'Catatan X', field: 'revenue', field_label: 'Pendapatan', keyakinan: 0.4, diterima: false, catatan: 'Tidak lolos uji rumus.' },
          ],
        });
      }
      if (url.endsWith('/sesi/S-1/terapkan-pemetaan')) return jawab(hasil);
      return jawab({ detail: 'tak dikenal' }, false);
    });
    const onSelesai = jest.fn();
    await act(async () => { root.render(<PopupAIPemeta sesiId="S-1" onClose={jest.fn()} onSelesai={onSelesai} />); });
    await tunggu(() => document.querySelectorAll('[data-testid="ai-usulan-baris"]').length === 2);
    expect(global.fetch.mock.calls[0][0]).toMatch(/\/api\/marketing\/impor-paket\/sesi\/S-1\/ai-pemeta$/);
    expect(global.fetch.mock.calls[0][1].method).toBe('POST');
    expect(document.body.textContent).toMatch(/Tidak lolos uji rumus/);
    await klik(q('popup-ai-pemeta-simpan'));
    await tunggu(() => onSelesai.mock.calls.length === 1);
    const [url, opt] = global.fetch.mock.calls[1];
    expect(url).toMatch(/\/sesi\/S-1\/terapkan-pemetaan$/);
    expect(JSON.parse(opt.body)).toEqual({ pilihan: { Biaya: 'spend' }, simpan_untuk_toko: true });
    expect(onSelesai).toHaveBeenCalledWith(hasil);
  });

  test('galat AI tampil sebagai kalimat, tombol terapkan mati tanpa pilihan', async () => {
    global.fetch = jest.fn(() => jawab({ detail: 'Asisten AI belum diaktifkan. Pemetaan manual tetap bisa dipakai.' }, false));
    await act(async () => { root.render(<PopupAIPemeta sesiId="S-2" onClose={jest.fn()} onSelesai={jest.fn()} />); });
    await tunggu(() => /belum diaktifkan/.test(q('popup-ai-pemeta-galat')?.textContent || ''));
    expect(q('popup-ai-pemeta-simpan').disabled).toBe(true);
  });
});

// ─── wizard Impor Data satu berkas ──────────────────────────────────────────────
const jenis = (key, extra = {}) => ({
  key, label: key === 'tiktok_gmv_max' ? 'Laporan Iklan TikTok GMV Max' : 'Biaya & Performa Iklan', group: 'Iklan',
  group_key: 'iklan', describe: 'uji', collection: 'x', deprecated: false, account_scope: 'required', context: [],
  prenorm: key === 'tiktok_gmv_max' ? 'tiktok_gmv_max' : '', export_hint: '', required_columns: [], fields: [],
  period_input: key === 'tiktok_gmv_max', ...extra,
});

function pasangAxios() {
  axios.get.mockImplementation((url) => {
    if (url.endsWith('/source-types')) return Promise.resolve({ data: { source_types: [jenis('tiktok_gmv_max'), jenis('ads')] } });
    if (url.endsWith('/source-groups')) return Promise.resolve({ data: { groups: [{ key: 'iklan', label: 'Iklan', describe: '' }] } });
    if (url.endsWith('/api/marketing/accounts')) return Promise.resolve({ data: [{ id: 'TTK-01', account_name: 'Toko Uji', platform: 'tiktok' }] });
    if (url.endsWith('/history')) return Promise.resolve({ data: { history: [] } });
    return Promise.resolve({ data: {} });
  });
}

async function keLangkahKonteks(key) {
  pasangAxios();
  await act(async () => { root.render(<DataImportWizard token="t" />); });
  await tunggu(() => q('import-group-iklan'));
  await klik(q('import-group-iklan'));
  await tunggu(() => q(`import-type-${key}`));
  await klik(q(`import-type-${key}`));
  await tunggu(() => q('import-context-next'));
  await klik(q('import-account-select'));
}

async function pilihTanggal(testId, ymd, geserBulan = 0) {
  await klik(q(testId));
  await tunggu(() => q(`${testId}-kalender`));
  const arah = geserBulan > 0 ? 'Bulan berikutnya' : 'Bulan sebelumnya';
  for (let i = 0; i < Math.abs(geserBulan); i += 1) {
    await klik(q(`${testId}-kalender`).querySelector(`[aria-label="${arah}"]`));
  }
  await tunggu(() => q(`${testId}-hari-${ymd}`));
  await klik(q(`${testId}-hari-${ymd}`));
}

const bulanDepan = (ym) => {
  const [y, m] = ym.split('-').map(Number);
  return m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, '0')}`;
};

describe('Wizard Impor Data — periode GMV Max & tombol AI', () => {
  test('isian periode hanya untuk GMV Max', async () => {
    await keLangkahKonteks('ads');
    expect(q('import-period-start')).toBeNull();
    expect(q('import-context-next').disabled).toBe(false);
  });

  test('periode wajib & satu bulan, dikirim ke /upload, tombol AI memakai pintu impor-paket', async () => {
    await keLangkahKonteks('tiktok_gmv_max');
    expect(q('import-period-start')).not.toBeNull();
    expect(q('import-context-next').disabled).toBe(true);                 // periode belum diisi
    const ym = hariIniWIB().slice(0, 7);
    await pilihTanggal('import-period-start', `${ym}-01`);
    await pilihTanggal('import-period-end', `${bulanDepan(ym)}-01`, 1);
    expect(q('import-period-hint').textContent).toMatch(/menyeberang bulan/);
    expect(q('import-context-next').disabled).toBe(true);
    await pilihTanggal('import-period-end', `${ym}-02`, -1);         // kalender membuka bulan nilai lama
    expect(q('import-context-next').disabled).toBe(false);
    await klik(q('import-context-next'));

    const input = await (async () => { await tunggu(() => q('import-file-input')); return q('import-file-input'); })();
    const berkas = new File(['x'], 'Ekspor GMV Max.xlsx');
    Object.defineProperty(input, 'files', { value: [berkas] });
    await act(async () => { input.dispatchEvent(new Event('change', { bubbles: true })); });
    axios.post.mockResolvedValueOnce({ data: {
      session: { id: 'S-9', filename: `periode_${ym}-01_${ym}-02__Ekspor GMV Max.xlsx`, original_filename: 'Ekspor GMV Max.xlsx',
        period_start: `${ym}-01`, period_end: `${ym}-02`, total_rows: 2, status: 'mapping', source_type: 'tiktok_gmv_max',
        mapping: [{ column: 'Kolom asing', field: null, method: 'none', candidates: [] }],
        mapping_report: { ready: false, mapped: 0, total_columns: 1, methods: {}, missing_required: [], unmapped_columns: ['Kolom asing'] } },
      preview: [], summary: {}, duplicates: {}, value_report: [] } });
    await klik(q('import-upload-btn'));
    await tunggu(() => axios.post.mock.calls.length === 1);
    const [url, fd] = axios.post.mock.calls[0];
    expect(url).toMatch(/\/api\/marketing\/data-import\/upload$/);
    expect(fd.get('source_type')).toBe('tiktok_gmv_max');
    expect([fd.get('period_start'), fd.get('period_end')]).toEqual([`${ym}-01`, `${ym}-02`]);
    expect(fd.get('file').name).toBe('Ekspor GMV Max.xlsx');                 // nama berkas tidak diubah layar

    await tunggu(() => q('import-ai-assist'));
    expect(q('import-period-badge').textContent).toMatch(/^Periode /);
    expect(document.body.textContent).toMatch(/Ekspor GMV Max\.xlsx/);
    global.fetch = jest.fn(() => jawab({ pesan: 'Tidak ada usulan.', usulan: [] }));
    await klik(q('import-ai-assist'));
    await tunggu(() => global.fetch.mock.calls.length === 1);
    expect(global.fetch.mock.calls[0][0]).toMatch(/\/api\/marketing\/impor-paket\/sesi\/S-9\/ai-pemeta$/);
    expect(axios.post.mock.calls.some(([u]) => /ai-assist/.test(u))).toBe(false);
  });
});

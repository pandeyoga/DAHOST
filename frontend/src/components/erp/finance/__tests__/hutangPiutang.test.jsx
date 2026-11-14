// 11 Nov 2026 (owner) — Keuangan › Hutang dan Piutang: satu daftar per menu, tanpa tab, penyaring status/jenis/nama;
// nama menu "Hutang" dan "Piutang"; kolom Umur seperti Excel owner (hijau 0–7 · kuning 8–14 · merah > 14 hari sejak
// kirim ke CMT). Data di bawah ini contoh buatan, bukan data klien.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { apiGet } from '../../../../lib/api';
import HutangModule, { cocokStatus, ringkasHutang, susunHutang } from '../HutangModule';
import PiutangModule, { jenisFaktur, ringkasPiutang, susunPiutang } from '../PiutangModule';
import { hariTerlambat, teksJatuhTempo } from '../umurTagihan';

jest.mock('../../../../lib/api', () => ({ apiGet: jest.fn(), apiPost: jest.fn(), apiFetch: jest.fn() }));
jest.mock('../../../../lib/waktu', () => ({ ...jest.requireActual('../../../../lib/waktu'), todayWIB: () => '2026-11-11' }));
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
  localStorage.setItem('erp_user', JSON.stringify({ role: 'accounting' }));
  sessionStorage.clear();
});
afterEach(() => { act(() => root.unmount()); document.body.innerHTML = ''; localStorage.clear(); });

const HARI_INI = '2026-11-11';

// ─── Hutang ────────────────────────────────────────────────────────────────────
const FAKTUR = [
  { id: 'f1', invoice_number: 'AP-1', vendor_name: 'Pemasok Kain A', status: 'sent', total: 15997000, paid_amount: 0,
    balance: 15997000, issue_date: '2026-10-01', due_date: '2026-10-31', entity: 'DA', po_numbers: ['PO-B-1'] },
  { id: 'f2', invoice_number: 'AP-2', vendor_name: 'Pemasok Kain B', status: 'paid', total: 500000, paid_amount: 500000,
    balance: 0, issue_date: '2026-09-01', entity: 'DA' },
];
const CMT = [
  { id: 'c1', payment_code: 'PAY-CMT-1', cmt_name: 'Penjahit Satu', po_number: 'PO-MKL-1', amount: 85000,
    outstanding_amount: 85000, paid_amount: 0, status: 'posted', gl_posted: true, issue_date: '2026-11-09',
    entity: 'SMU', business_type: 'maklon' },
];
const JADWAL = [
  { id: 'sch-1', po_number: 'PO-MKL-1', vendor_name: 'Penjahit Satu', entity: 'SMU', jenis: 'jadwal',
    scheduled_qty: 40, scheduled_amount: 340000, matured_amount: 85000, remaining_amount: 255000,
    kirim_pertama: '2026-11-05', umur_kirim_hari: 6, umur_kirim: 'hijau', lines: [] },
  { id: 'perkiraan-po2-vp1', po_number: 'PO-INT-2', vendor_name: 'Penjahit Dua', entity: 'DA', jenis: 'perkiraan',
    scheduled_qty: 10, scheduled_amount: 120000, matured_amount: 0, remaining_amount: 120000,
    kirim_pertama: '2026-10-13', umur_kirim_hari: 29, umur_kirim: 'merah',
    lines: [{ po_item_id: 'pi1', product_name: 'Kemeja uji', color: 'Hitam', size: 'M', qty: 10, cmt_rate: 12000, amount: 120000 }] },
  { id: 'sch-habis', po_number: 'PO-MKL-9', vendor_name: 'Penjahit Satu', entity: 'SMU', jenis: 'jadwal',
    scheduled_amount: 50000, matured_amount: 50000, remaining_amount: 0 },
];
const GR = [{ id: 'g1', receipt_number: 'GR-1', supplier_name: 'Pemasok Kain A', po_number: 'PO-B-2',
  receivable_amount: 700000, received_at: '2026-11-08', billable_lines: [] }];

test('umur jatuh tempo: terlambat / hari ini / hari lagi', () => {
  expect(hariTerlambat('2026-10-31', HARI_INI)).toBe(11);
  expect(teksJatuhTempo(11)).toBe('terlambat 11 hari');
  expect(teksJatuhTempo(0)).toBe('jatuh tempo hari ini');
  expect(teksJatuhTempo(-3)).toBe('jatuh tempo 3 hari lagi');
  expect(hariTerlambat(null, HARI_INI)).toBeNull();
});

test('Hutang: empat sumber jadi satu daftar; jadwal tanpa sisa tidak ikut; ringkasan tidak dobel', () => {
  const rows = susunHutang({ faktur: FAKTUR, cmt: CMT, jadwal: JADWAL, penerimaan: GR }, HARI_INI);
  const st = Object.fromEntries(rows.map((r) => [r.nomor, r.status]));
  expect(st).toEqual({ 'AP-1': 'belum_dibayar', 'AP-2': 'lunas', 'PAY-CMT-1': 'belum_dibayar', 'PO-MKL-1': 'terjadwal',
    'PO-INT-2': 'terjadwal', 'GR-1': 'belum_difakturkan' });
  const r = ringkasHutang(rows);
  // jadwal PO-MKL-1 340.000 = tagihan lolos QC 85.000 + belum jatuh tempo 255.000 (tidak dihitung dua kali)
  expect(r.terjadwal).toBe(375000);
  expect(r.belumDibayar).toBe(15997000 + 85000);
  // AP-1 jatuh tempo 31 Okt; tagihan CMT jatuh tempo saat terbit (9 Nov) — aturan core.payables / Beranda Keuangan
  expect(r.lewat).toBe(15997000 + 85000);
  expect(r.belumDifakturkan).toBe(700000);
  expect(r.totalTerbuka).toBe(15997000 + 85000 + 375000 + 700000);
  expect(r.perCv).toEqual({ DA: 15997000 + 120000, SMU: 85000 + 255000 });
  expect(r.kirim).toEqual({ hijau: 255000, kuning: 0, merah: 120000 });
  expect(rows.filter((x) => cocokStatus(x, 'lewat')).map((x) => x.nomor)).toEqual(['AP-1', 'PAY-CMT-1']);
  expect(rows.filter((x) => cocokStatus(x, 'terbuka')).length).toBe(5);
});

const mockHutang = () => apiGet.mockImplementation(async (url) => {
  if (url.startsWith('/api/rahaza/ap-invoices')) return FAKTUR;
  if (url.startsWith('/api/production/cmt-billing/schedules')) return { items: JADWAL };
  if (url.startsWith('/api/production/cmt-billing')) return { items: CMT };
  if (url.startsWith('/api/rahaza/grs/available-for-invoice')) return { items: GR };
  return [];
});

test('Keuangan › Hutang: satu daftar tanpa tab, terjadwal tanpa tombol Bayar, umur seperti Excel, penyaring jenis', async () => {
  mockHutang();
  // 14 Nov 2026: tombol Bayar mengikuti centang Pembayaran & Pencairan Uang › Setujui (hasPerm dari App).
  act(() => { root.render(<HutangModule token="t" hasPerm={(k) => k === 'mod.fin_pencairan.approve'} />); });
  await tunggu(() => q('hutang-baris-jadwal-sch-1'));
  expect(document.querySelector('[role="tablist"]')).toBeNull();
  expect(q('hutang-baris-ap-f1')).not.toBeNull();
  expect(q('hutang-baris-cmt-c1')).not.toBeNull();
  expect(q('hutang-baris-gr-g1')).not.toBeNull();
  expect(q('hutang-baris-ap-f2')).toBeNull();                       // lunas tidak tampil di "Belum lunas"
  expect(q('hutang-baris-jadwal-sch-habis')).toBeNull();
  // terjadwal: Rincian ada, Bayar tidak
  expect(q('hutang-bayar-jadwal-sch-1')).toBeNull();
  expect(q('hutang-rincian-jadwal-sch-1')).not.toBeNull();
  expect(q('hutang-bayar-ap-f1')).not.toBeNull();
  expect(q('hutang-bayar-cmt-c1')).not.toBeNull();
  expect(q('hutang-buat-faktur-gr-g1')).not.toBeNull();
  expect(q('hutang-umur-jadwal-sch-1').textContent).toBe('6 hari');
  expect(q('hutang-umur-jadwal-perkiraan-po2-vp1').textContent).toBe('29 hari');
  expect(q('hutang-perkiraan-jadwal-perkiraan-po2-vp1').textContent).toBe('Perkiraan');
  expect(q('hutang-sisa-jadwal-sch-1').textContent).toBe('Rp 255.000');
  const ringkas = q('hutang-ringkasan').textContent;
  expect(ringkas).toContain('Belum dibayar Rp 16.082.000');
  expect(ringkas).toContain('terjadwal Rp 375.000');
  expect(ringkas).toContain('belum difakturkan Rp 700.000');
  expect(q('hutang-umur-kirim').textContent).toContain('0–7 hari');
  // pil status
  klik(q('hutang-status-terjadwal'));
  await tunggu(() => !q('hutang-baris-ap-f1'));
  expect(q('hutang-baris-jadwal-sch-1')).not.toBeNull();
  klik(q('hutang-status-lunas'));
  await tunggu(() => q('hutang-baris-ap-f2'));
  klik(q('hutang-status-terbuka'));
  await tunggu(() => q('hutang-baris-ap-f1'));
  // rincian terjadwal = popup per barang
  klik(q('hutang-rincian-jadwal-perkiraan-po2-vp1'));
  await tunggu(() => q('hutang-rincian-jadwal-barang'));
  expect(q('hutang-rincian-jadwal-barang').textContent).toContain('Kemeja uji · Hitam');
});

test('14 Nov 2026: tombol Bayar mengikuti centang, bukan kode peran keuangan', async () => {
  mockHutang();
  // kode peran keuangan TANPA centang Pembayaran & Pencairan Uang › Setujui → tidak ada tombol Bayar (server menolak)
  act(() => { root.render(<HutangModule token="t" hasPerm={() => false} />); });
  await tunggu(() => q('hutang-baris-ap-f1'));
  expect(q('hutang-bayar-ap-f1')).toBeNull();
  expect(q('hutang-bayar-cmt-c1')).toBeNull();
  act(() => root.unmount());
  // peran buatan owner yang dicentang (dibaca dari sesi tersimpan bila hasPerm tidak dikirim) → tombol tampil
  localStorage.setItem('erp_user', JSON.stringify({ role: 'Finance & Purchase', permissions: ['mod.fin_pencairan.approve'] }));
  root = createRoot(container);
  act(() => { root.render(<HutangModule token="t" />); });
  await tunggu(() => q('hutang-bayar-ap-f1'));
  expect(q('hutang-bayar-cmt-c1')).not.toBeNull();
});

test('tautan lama ke tab "Hutang CMT terjadwal" membuka daftar Hutang dengan pil Terjadwal', async () => {
  mockHutang();
  sessionStorage.setItem('hub_tab_fin-ap-hub', 'cmt-terjadwal');
  act(() => { root.render(<HutangModule token="t" />); });
  await tunggu(() => q('hutang-baris-jadwal-sch-1'));
  expect(q('hutang-status-terjadwal').getAttribute('aria-pressed')).toBe('true');
  expect(q('hutang-baris-ap-f1')).toBeNull();
});

// ─── Piutang ───────────────────────────────────────────────────────────────────
const AR = [
  { id: 'a1', invoice_number: 'INV-1', customer_id: 'cus1', customer_name: 'Reseller Satu', source_module: 'direct_sale',
    status: 'issued', total: 1000000, paid_amount: 250000, balance: 750000, issue_date: '2026-10-01',
    due_date: '2026-10-20', entity: 'DA', maklon: false },
  { id: 'a2', invoice_number: 'NAC-00001', customer_name: 'Penjahit Satu', source_module: 'cmt_accessory', status: 'issued',
    total: 40000, paid_amount: 0, balance: 40000, issue_date: '2026-11-10', due_date: '2026-11-25', entity: 'DA', maklon: false },
  // dokumen piutang PO maklon juga ada di daftar faktur — diambil dari sumber Portal Maklon, bukan dari sini
  { id: 'm1', invoice_number: 'AR-MKL-1', source_module: 'maklon_po', schedule_mode: 'v2', status: 'scheduled', total: 0,
    balance: 0, entity: 'SMU', maklon: true },
];
const MAKLON = [
  { id: 'm1', invoice_number: 'AR-MKL-1', mode: 'terjadwal', po_number: 'PO-MKL-1', client_name: 'Klien Maklon A',
    status: 'scheduled', scheduled_total: 2702500, billed_total: 0, paid_total: 0, amount_due: 0, advance_balance: 0,
    scheduled_remaining: 2702500, outstanding_total: 2702500, entity: 'SMU', kirim_pertama: '2026-10-29',
    umur_kirim_hari: 13, umur_kirim: 'kuning' },
  { id: 'm2', invoice_number: 'AR-MKL-2', mode: 'terjadwal', po_number: 'PO-MKL-2', client_name: 'Klien Maklon B',
    status: 'issued', scheduled_total: 580500, billed_total: 300000, paid_total: 100000, amount_due: 200000,
    advance_balance: 0, scheduled_remaining: 280500, outstanding_total: 480500, due_date: '2026-11-30', entity: 'SMU' },
];
const MP = [
  { account_id: 'toko1', account_code: 'SHP-1', account_name: 'Toko Shopee', platform: 'shopee', released_total: 900000,
    withdrawn_total: 600000, balance: 300000 },
  { account_id: 'toko2', account_name: 'Toko kosong', platform: 'tiktok', released_total: 0, withdrawn_total: 0, balance: 0 },
];

test('Piutang: jenis faktur, maklon tidak dobel, ringkasan maklon sama dengan Portal Maklon', () => {
  expect(AR.map(jenisFaktur)).toEqual(['reseller', 'lainnya', 'maklon']);
  const rows = susunPiutang({ faktur: AR, maklon: MAKLON, marketplace: MP }, HARI_INI);
  expect(rows.map((r) => r.key).sort()).toEqual(['ar-a1', 'ar-a2', 'maklon-m1', 'maklon-m2', 'mp-toko1']);
  const r = ringkasPiutang(rows);
  // Portal Maklon › Piutang klien: summary.scheduled_remaining = Σ scheduled_remaining, amount_due = Σ amount_due
  const maklon = ringkasPiutang(rows.filter((x) => x.jenis === 'maklon'));
  expect(maklon.terjadwal).toBe(2702500 + 280500);
  expect(maklon.tertagih).toBe(200000);
  expect(r.tertagih).toBe(750000 + 40000 + 200000 + 300000);
  expect(r.lewat).toBe(750000);                     // INV-1 jatuh tempo 20 Okt
  expect(r.totalTerbuka).toBe(750000 + 40000 + 2702500 + 480500 + 300000);
  expect(r.kirim).toEqual({ hijau: 0, kuning: 2702500, merah: 0 });
});

const mockPiutang = () => apiGet.mockImplementation(async (url) => {
  if (url.startsWith('/api/rahaza/ar-invoices')) return AR;
  if (url.startsWith('/api/dewi/maklon/receivables')) return { items: MAKLON, summary: {} };
  if (url.startsWith('/api/marketing/settlements/platform-balance')) return { data: MP };
  if (url.startsWith('/api/rahaza/customers')) return [{ id: 'cus1', name: 'Reseller Satu' }];
  return [];
});

test('Keuangan › Piutang langsung membuka daftar piutang (bukan Faktur); maklon terjadwal tampil sisa nilai PO', async () => {
  mockPiutang();
  act(() => { root.render(<PiutangModule token="t" />); });
  await tunggu(() => q('piutang-baris-maklon-m1'));
  expect(document.querySelector('[role="tablist"]')).toBeNull();
  expect(q('piutang-sisa-maklon-m1').textContent).toBe('Rp 2.702.500');
  expect(q('piutang-umur-maklon-m1').textContent).toBe('13 hari');
  expect(q('piutang-baris-mp-toko1')).not.toBeNull();
  expect(q('piutang-baris-mp-toko2')).toBeNull();
  expect(q('piutang-baris-ar-m1')).toBeNull();                       // tidak dobel dengan baris maklon
  expect(q('piutang-terjadwal').textContent).toBe('Rp 2.983.000');
  expect(q('piutang-bayar-ar-a1')).not.toBeNull();
  expect(q('piutang-bayar-maklon-m1')).not.toBeNull();                // uang muka klien boleh sebelum kirim
  // penyaring jenis
  klik(q('piutang-jenis-trigger'));
  await tunggu(() => q('piutang-jenis-option-maklon'));
  klik(q('piutang-jenis-option-maklon'));
  await tunggu(() => !q('piutang-baris-ar-a1'));
  expect(q('piutang-baris-maklon-m2')).not.toBeNull();
});

test('tautan lama "Hapus buku" membuka Piutang dengan pil Lewat jatuh tempo', async () => {
  mockPiutang();
  sessionStorage.setItem('hub_tab_fin-ar-hub', 'writeoff');
  act(() => { root.render(<PiutangModule token="t" />); });
  await tunggu(() => q('piutang-baris-ar-a1'));
  expect(q('piutang-status-lewat').getAttribute('aria-pressed')).toBe('true');
  expect(q('piutang-baris-maklon-m1')).toBeNull();
  klik(q('piutang-lainnya-ar-a1'));
});

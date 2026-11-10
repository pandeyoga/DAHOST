// Asisten AI per pengguna (10 Nov 2026): tabel Monitor AI › Pengaturan + layar status chat untuk akun yang dimatikan /
// batas pertanyaan tercapai.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import AsistenPerPengguna, { asalStatus, bacaBatas, teksPakai } from '../AsistenPerPengguna';
import { KODE_GALAT_AKUN, PLACEHOLDER_BELUM_SIAP, StatusBelumSiap } from '../StatusAsisten';

jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn(), info: jest.fn() } }));
// eslint-disable-next-line import/first
import { toast } from 'sonner';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let root;
let container;
const q = (id) => document.querySelector(`[data-testid="${id}"]`);
const klik = (el) => act(() => { el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true })); });
const ketik = (el, v) => act(() => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, v);
  el.dispatchEvent(new Event('input', { bubbles: true }));
});
const tunggu = async (fn) => {
  let galat;
  for (let i = 0; i < 60; i += 1) {
    try { if (fn()) return; } catch (e) { galat = e; }
    // eslint-disable-next-line no-await-in-loop
    await act(async () => { await new Promise((r) => setTimeout(r, 5)); });
  }
  throw galat || new Error('kondisi tidak terpenuhi');
};

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
  jest.restoreAllMocks();
  delete global.fetch;
});

describe('helper tabel', () => {
  test('teksPakai: batas 0 = tanpa batas', () => {
    expect(teksPakai(3, 20)).toBe('3 / 20');
    expect(teksPakai(3, 0)).toBe('3 · tanpa batas');
  });
  test('asalStatus', () => {
    expect(asalStatus({ selalu_aktif: true, sumber: 'peran' })).toMatch(/Selalu aktif/);
    expect(asalStatus({ sumber: 'akun' })).toBe('Diatur untuk akun ini');
    expect(asalStatus({ sumber: 'bawaan' })).toBe('Ikut bawaan');
  });
  test('bacaBatas: kosong = ikut bawaan, salah = undefined', () => {
    expect(bacaBatas('')).toBeNull();
    expect(bacaBatas(' 12 ')).toBe(12);
    expect(bacaBatas('0')).toBe(0);
    expect(bacaBatas('1001')).toBeUndefined();
    expect(bacaBatas('-1')).toBeUndefined();
    expect(bacaBatas('2,5')).toBeUndefined();
  });
});

describe('status chat untuk akun', () => {
  test('akun dimatikan dan batas pertanyaan punya layar & teks sendiri', () => {
    act(() => root.render(<StatusBelumSiap status={{ memuat: false, data: { alasan: 'pengguna_nonaktif' } }} peran="staff_gudang" />));
    expect(q('asisten-status-pengguna-nonaktif').textContent).toMatch(/belum aktif untuk akun Anda/);
    act(() => root.render(<StatusBelumSiap status={{ memuat: false, data: { alasan: 'batas_pertanyaan', pesan: 'Batas 5 pertanyaan.' } }} peran="staff_gudang" />));
    expect(q('asisten-status-batas-pertanyaan').textContent).toMatch(/Batas 5 pertanyaan\./);
    expect(PLACEHOLDER_BELUM_SIAP.pengguna_nonaktif).toBeTruthy();
    expect(KODE_GALAT_AKUN).toEqual(['pengguna_nonaktif', 'batas_pertanyaan']);
  });
});

const DATA = {
  bawaan: { aktif: false, batas_pertanyaan: 0, batas_tindakan: 30 },
  boleh_ubah: true,
  items: [
    { id: 'u-owner', name: 'Pemilik', email: 'o@contoh.test', role: 'owner', aktif: true, sumber: 'peran', selalu_aktif: true,
      batas_pertanyaan: 0, batas_tindakan: 30, atur: { aktif: null, batas_pertanyaan_harian: null, batas_tindakan_harian: null },
      pertanyaan_hari_ini: 4, tindakan_hari_ini: 1, biaya_hari_ini_usd: 0.5 },
    { id: 'u-staf', name: 'Staf Gudang', email: 's@contoh.test', role: 'staff_gudang', aktif: false, sumber: 'bawaan',
      selalu_aktif: false, batas_pertanyaan: 0, batas_tindakan: 30,
      atur: { aktif: null, batas_pertanyaan_harian: null, batas_tindakan_harian: null },
      pertanyaan_hari_ini: 0, tindakan_hari_ini: 0, biaya_hari_ini_usd: 0 },
  ],
};

test('tabel per pengguna: tampil, saring, dan simpan mengirim isian yang benar', async () => {
  const panggil = [];
  global.fetch = jest.fn(async (url, opt = {}) => {
    panggil.push({ url, opt });
    if (opt.method === 'PUT') return { ok: true, json: async () => ({ success: true, data: {} }) };
    return { ok: true, json: async () => ({ success: true, data: DATA }) };
  });
  act(() => root.render(<AsistenPerPengguna token="tok" />));
  await tunggu(() => q('ai-asisten-pengguna-ubah-u-staf'));
  const baris = [...document.querySelectorAll('[data-testid="ai-asisten-pengguna-tabel-baris"]')];
  expect(baris).toHaveLength(2);
  expect(baris[0].textContent).toMatch(/Pemilik.*Selalu aktif.*4 · tanpa batas/);
  expect(baris[1].textContent).toMatch(/Staf Gudang.*Mati.*Ikut bawaan/);
  // saring "Mati" → hanya staf
  klik([...document.querySelectorAll('button')].find((b) => /^Mati/.test(b.textContent.trim())));
  await tunggu(() => document.querySelectorAll('[data-testid="ai-asisten-pengguna-tabel-baris"]').length === 1);

  // buka popup Ubah untuk staf → pilih Aktif + batas pertanyaan 10 → simpan
  klik(q('ai-asisten-pengguna-ubah-u-staf'));
  await tunggu(() => q('ai-ap-aktif-trigger'));
  klik(q('ai-ap-aktif-trigger'));
  await tunggu(() => q('ai-ap-aktif-option-aktif'));
  klik(q('ai-ap-aktif-option-aktif'));
  ketik(q('ai-ap-pertanyaan'), '10');
  const tombolSimpan = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Simpan');
  klik(tombolSimpan);
  await tunggu(() => panggil.some((p) => p.opt.method === 'PUT'));
  const put = panggil.find((p) => p.opt.method === 'PUT');
  expect(put.url).toMatch(/\/api\/ai\/usage\/asisten-pengguna\/u-staf$/);
  expect(JSON.parse(put.opt.body)).toEqual({ aktif: true, batas_pertanyaan_harian: 10, batas_tindakan_harian: null });
  await tunggu(() => toast.success.mock.calls.length > 0);
});

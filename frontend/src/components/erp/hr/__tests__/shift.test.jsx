// Tahap C audit HR (9 Nov 2026): layar Shift — Roster (pilih baris × tanggal → isi shift massal), Pola rotasi (isi cepat
// per minggu dari hari kerja shift), Portal Saya › Jadwal Shift (jawab ajakan tukar / persetujuan atasan).
// Bentuk data = jawaban NYATA backend (`/api/hr/shift-scheduler/roster`, `/api/portal/shift/*`).
// Tanpa @testing-library/react — createRoot + act (pola tes asisten).
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { ConfirmDialogHost } from '@/components/ui/confirm-dialog';
import { seninDari, teksDiAtas, shiftApi } from '../shiftShared';
import { mingguDariShift, ringkasPola } from '../ShiftPolaModule';
import ShiftRosterModule from '../ShiftRosterModule';
import PortalShiftSayaModule from '../../portal/PortalShiftSayaModule';

jest.mock('../shiftShared', () => {
  const asli = jest.requireActual('../shiftShared');
  return { ...asli, shiftApi: jest.fn() };
});
jest.mock('../hrPickers', () => ({
  useActiveEmployees: () => ({ employees: [], loaded: true }),
  useHrMasters: () => ({ units: [], positions: [], shifts: [], loaded: true }),
  useDepartmentFilterOptions: () => [{ value: 'Gudang', label: 'Gudang' }],
  EmployeeSelect: () => null,
}));
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn(), warning: jest.fn(), info: jest.fn() } }));
jest.mock('axios', () => ({ __esModule: true, default: jest.fn(() => Promise.resolve({ data: {} })) }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let root;
let container;
const semua = (id) => [...document.querySelectorAll(`[data-testid="${id}"]`)];
const q = (id) => document.querySelector(`[data-testid="${id}"]`);
const tunggu = async (fn) => {
  let galat;
  for (let i = 0; i < 60; i += 1) {
    try { if (fn()) return; } catch (e) { galat = e; }
    // eslint-disable-next-line no-await-in-loop
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
  }
  throw galat || new Error('waktu habis');
};
const klik = (el) => act(() => { el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true })); });

beforeEach(() => {
  jest.clearAllMocks();
  window.localStorage.setItem('erp_token', 'tok');
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); document.body.innerHTML = ''; });

describe('bantuan shift', () => {
  test('Senin dari minggu & warna teks', () => {
    expect(seninDari('2026-11-12')).toBe('2026-11-09');
    expect(seninDari('2026-11-15')).toBe('2026-11-09');   // Minggu → Senin minggu itu
    expect(seninDari('2026-11-16')).toBe('2026-11-16');
    expect(teksDiAtas('#f59e0b')).toBe('#111827');
    expect(teksDiAtas('#3b82f6')).toBe('#ffffff');
  });
  test('pola: isi seminggu memakai hari kerja shift, ringkasan per minggu', () => {
    const pagi = { id: 'p', kode: 'PAGI', hari_aktif: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'] };
    const minggu = mingguDariShift(pagi);
    expect(minggu).toEqual(['p', 'p', 'p', 'p', 'p', 'p', null]);
    expect(ringkasPola([...minggu, ...Array(7).fill('s')], { p: 'PAGI', s: 'SIANG' })).toBe('M1: PAGI 6, libur 1 · M2: SIANG 7');
  });
});

const ROSTER = {
  tanggal: [{ t: '2026-11-16', label: 'Sen 16 Nov', libur: null }, { t: '2026-11-17', label: 'Sel 17 Nov', libur: null }],
  shift: [{ id: 'sh-p', kode: 'PAGI', nama: 'Pagi', mulai: '07:00', selesai: '15:00', warna: '#f59e0b', aktif: true }],
  karyawan: [
    { id: 'e1', kode: 'K01', nama: 'Ani', departemen: 'Gudang', sel: [
      { t: '2026-11-16', s: 'sh-p', src: 'draf', lj: false, kunci: null, ket: null, setengah: false, bentrok: null },
      { t: '2026-11-17', s: null, src: null, lj: false, kunci: 'cuti', ket: 'Cuti tahunan', setengah: false, bentrok: null }] },
    { id: 'e2', kode: 'K02', nama: 'Budi', departemen: 'Gudang', sel: [
      { t: '2026-11-16', s: 'sh-p', src: 'penugasan', lj: false, kunci: null, ket: null, setengah: false, bentrok: 'peringatan' },
      { t: '2026-11-17', s: 'sh-p', src: 'penugasan', lj: false, kunci: null, ket: null, setengah: false, bentrok: null }] },
  ],
  bentrok: [{ employee_id: 'e2', karyawan: 'Budi', date: '2026-11-16', tanggal: 'Sen 16 Nov', jenis: 'libur', tingkat: 'peringatan', pesan: 'Masuk PAGI di hari libur.' }],
  jumlah_bentrok: { berat: 0, peringatan: 1, info: 0 },
  jadwal: { id: 'j1', judul: 'Jadwal uji', status: 'draft', start_date: '2026-11-16', end_date: '2026-11-17' },
};

describe('Roster', () => {
  test('sel berwarna shift, cuti terkunci, pilih baris × tanggal → isi massal', async () => {
    shiftApi.mockImplementation((m, path) => {
      if (path.endsWith('/roster')) return Promise.resolve({ data: ROSTER });
      if (path.endsWith('/schedules')) return Promise.resolve({ data: [{ ...ROSTER.jadwal, metadata: { total_shifts: 3 } }] });
      if (path.endsWith('/pola')) return Promise.resolve({ data: [] });
      if (path.endsWith('/sel')) return Promise.resolve({ message: '2 sel diubah.', data: { diubah: 2, dilewati: [] } });
      return Promise.resolve([]);
    });
    act(() => root.render(<><ShiftRosterModule user={{ role: 'hr' }} /><ConfirmDialogHost /></>));
    await tunggu(() => semua('roster-baris').length === 2);
    const sel = semua('roster-sel');
    expect(sel.map((s) => s.textContent)).toEqual(['PAGI', 'Cuti', 'PAGI', 'PAGI']);
    expect(sel[0].style.backgroundColor).toBeTruthy();
    expect(q('roster-ringkasan').textContent).toContain('Bentrok: 0 berat, 1 peringatan');
    // pilih baris Budi + tanggal 17 → 1 sel; klik sel Ani 16 → 2 sel
    const cek = [...document.querySelectorAll('[role="checkbox"]')];
    await klik(cek[2]);
    await klik(semua('roster-tanggal')[1]);
    await klik(sel[0]);
    await tunggu(() => /Isi shift \(2\)/.test(q('roster-isi').textContent));
  });
});

describe('Portal Saya › Jadwal Shift', () => {
  const JADWAL = { employee_id: 'e1', hari: [
    { date: '2026-11-10', label: 'Sel 10 Nov', hari_ini: true, shift: { id: 'sh-p', kode: 'PAGI', mulai: '07:00', selesai: '15:00', warna: '#f59e0b' }, sumber: 'penugasan', keterangan: null },
    { date: '2026-11-11', label: 'Rab 11 Nov', hari_ini: false, shift: null, sumber: null, keterangan: 'Libur mingguan' }] };
  const AJAKAN = { id: 'r1', jenis: 'tukar', label_jenis: 'Tukar shift', status: 'menunggu_rekan', label_status: 'Menunggu rekan',
    tanggal: '2026-11-12', employee_name: 'Budi', rekan_name: 'Ani', shift_asal: { kode: 'SIANG' }, rekan_shift_asal: { kode: 'PAGI' }, alasan: 'Kuliah' };

  test('jadwal tampil; ajakan rekan dijawab Setuju', async () => {
    shiftApi.mockImplementation((m, path) => {
      if (path.endsWith('/jadwal-saya')) return Promise.resolve(JADWAL);
      if (path.endsWith('/permintaan') && m === 'get') return Promise.resolve({ milik_saya: [], sebagai_rekan: [AJAKAN], perlu_persetujuan_saya: [] });
      return Promise.resolve({ message: 'Jawaban terkirim.' });
    });
    act(() => root.render(<><PortalShiftSayaModule /><ConfirmDialogHost /></>));
    await tunggu(() => q('shift-saya-rekan-tabel'));
    expect(q('shift-saya-jadwal').textContent).toContain('PAGI');
    expect(q('shift-saya-jadwal').textContent).toContain('Libur mingguan');
    expect(q('shift-saya-ringkas').textContent).toContain('1 ajakan tukar');
    const setuju = [...q('shift-saya-rekan-tabel').querySelectorAll('button')].find((b) => b.textContent.includes('Setuju'));
    await klik(setuju);
    await tunggu(() => [...document.querySelectorAll('button')].some((b) => b.textContent === 'Setuju' && b.closest('[role="alertdialog"],[role="dialog"]')));
    const ok = [...document.querySelectorAll('[role="alertdialog"] button,[role="dialog"] button')].find((b) => b.textContent === 'Setuju');
    await klik(ok);
    await tunggu(() => shiftApi.mock.calls.some(([m, p]) => m === 'post' && p.endsWith('/permintaan/r1/rekan')));
    const panggil = shiftApi.mock.calls.find(([m, p]) => m === 'post' && p.endsWith('/permintaan/r1/rekan'));
    expect(panggil[2].data).toEqual({ setuju: true, catatan: '' });
  });
});

// Bagian "Asisten AI proaktif" di Monitor AI › Pengaturan (Tahap D): saklar, jam JJ:MM, penerima (≤ 20), Jalankan
// sekarang, jadwal berikutnya + riwayat (GET /proaktif). Bentuk jawaban = bentuk NYATA backend proaktif.
import { act, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ConfirmDialogHost } from '@/components/ui/confirm-dialog';
import { asistenApi } from '../asistenApi';
import { bacaPengaturanProaktif } from '../adapterTahapCD';
import PengaturanProaktif from '../PengaturanProaktif';

jest.mock('../asistenApi', () => ({
  asistenApi: { daftarPenggunaManajemen: jest.fn(), jalankanProaktif: jest.fn(), ringkasanProaktif: jest.fn() },
}));
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn(), info: jest.fn() } }));
// eslint-disable-next-line import/first
import { toast } from 'sonner';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let root;
let container;
let formTerakhir;
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
const ketik = (el, v) => act(() => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, v);
  el.dispatchEvent(new Event('input', { bubbles: true }));
});
const blur = (el) => act(() => { el.dispatchEvent(new FocusEvent('focusout', { bubbles: true })); });

const SERVER = { asisten_briefing_jam: '07:00', asisten_briefing_penerima: ['u1'] };
const RINGKASAN = {
  jadwal: {
    briefing: { aktif: true, jam: '07:00', berikutnya: '2026-11-09T07:00:00+07:00', label: 'Briefing pagi' },
    peringatan: { aktif: true, jam: '07:00', berikutnya: '2026-11-09T07:00:00+07:00', label: 'Peringatan harian' },
    laporan_mingguan: { aktif: false, jam: '07:30', berikutnya: null, label: 'Laporan mingguan' },
  },
  penerima: ['u1'], ai_aktif: true,
  riwayat: [
    { id: 'r1', jenis: 'briefing', tanggal: '2026-11-08', user_id: 'u1', pemicu: 'jadwal', status: 'selesai', sesi_id: 'sesi-b0', dibuat: '2026-11-08T00:00:10+00:00' },
    { id: 'r2', jenis: 'peringatan', tanggal: '2026-11-08', kondisi: 'piutang', pemicu: 'jadwal', status: 'terkirim', jumlah: 3, dibuat: '2026-11-08T00:00:05+00:00' },
    { id: 'r3', jenis: 'briefing', tanggal: '2026-11-08', user_id: 'u2', pemicu: 'jadwal', status: 'dilewati', alasan: 'tanpa_akses', dibuat: '2026-11-08T00:00:01+00:00' },
  ],
};

function Induk({ user, onNavigate, galat }) {
  const [form, setForm] = useState(() => bacaPengaturanProaktif(SERVER));
  formTerakhir = form;
  return (
    <PengaturanProaktif form={form} setField={(k, v) => setForm((f) => ({ ...f, [k]: v }))} galat={galat}
      tersimpan={SERVER} user={user} onNavigate={onNavigate} />
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  asistenApi.daftarPenggunaManajemen.mockResolvedValue([
    { id: 'u1', name: 'Pemilik Uji', role: 'owner' }, { id: 'u2', name: 'Manajer Uji', role: 'manager' },
  ]);
  asistenApi.ringkasanProaktif.mockResolvedValue(RINGKASAN);
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); document.body.innerHTML = ''; });

async function tampilkan({ user = { id: 'u1', role: 'owner' }, onNavigate = jest.fn(), galat = {} } = {}) {
  await act(async () => { root.render(<><ConfirmDialogHost /><Induk user={user} onNavigate={onNavigate} galat={galat} /></>); });
  await tunggu(() => q('ai-set-penerima-u1')?.textContent.includes('Pemilik Uji'));
  return onNavigate;
}

test('saklar ingatan + 3 jadwal, jam bawaan, penerima dari server', async () => {
  await tampilkan();
  expect(q('ai-set-ingatan-aktif').getAttribute('aria-checked')).toBe('true');
  for (const j of ['briefing', 'peringatan', 'laporan_mingguan']) {
    expect(q(`ai-set-${j}-aktif`).getAttribute('aria-checked')).toBe('true');
    expect(q(`ai-set-${j}-jalankan`)).not.toBeNull();
  }
  expect(q('ai-set-briefing-jam').value).toBe('07:00');
  expect(q('ai-set-laporan_mingguan-jam').value).toBe('07:30');
  expect(q('ai-set-penerima-u1').textContent).toContain('Owner');
  klik(q('ai-set-briefing-aktif'));
  expect(formTerakhir.asisten_briefing_aktif).toBe(false);
  expect(container.textContent).not.toMatch(/asisten_|snake|HH:MM/);
});

test('jam: dirapikan saat keluar isian ("6.30" → "06:30"); salah → galat tampil', async () => {
  await tampilkan();
  const jam = q('ai-set-peringatan-jam');
  ketik(jam, '6.30');
  blur(jam);
  expect(formTerakhir.asisten_peringatan_jam).toBe('06:30');
  expect(q('ai-set-peringatan-jam-galat')).toBeNull();
  ketik(jam, '25:99');
  blur(jam);
  expect(q('ai-set-peringatan-jam-galat').textContent).toContain('JJ:MM');
  expect(jam.getAttribute('aria-invalid')).toBe('true');
});

test('galat dari percobaan simpan induk tampil di baris jamnya', async () => {
  root.render(<></>);
  await act(async () => {
    root.render(<Induk user={{ id: 'u1', role: 'owner' }} onNavigate={jest.fn()} galat={{ asisten_briefing_jam: 'Jam briefing pagi salah.' }} />);
  });
  await tunggu(() => q('ai-set-briefing-jam'));
  ketik(q('ai-set-briefing-jam'), 'x');
  expect(q('ai-set-briefing-jam-galat').textContent).toBe('Jam briefing pagi salah.');
});

test('penerima: tambah dari pilihan, hapus lewat ikon; kosong = semua owner aktif', async () => {
  await tampilkan();
  klik(q('ai-set-penerima-tambah-trigger'));
  await tunggu(() => q('ai-set-penerima-tambah-option-u2'));
  klik(q('ai-set-penerima-tambah-option-u2'));
  expect(formTerakhir.asisten_briefing_penerima).toEqual(['u1', 'u2']);
  await tunggu(() => q('ai-set-penerima-u2'));
  klik(q('ai-set-penerima-hapus-u1'));
  klik(q('ai-set-penerima-hapus-u2'));
  expect(formTerakhir.asisten_briefing_penerima).toEqual([]);
  expect(q('ai-set-penerima-bawaan').textContent).toBe('Semua owner aktif');
});

test('jadwal berikutnya per jenis + riwayat jalan (nama penerima, kondisi, alasan berbahasa Indonesia, buka percakapan sendiri)', async () => {
  const onNavigate = await tampilkan();
  await tunggu(() => q('ai-set-proaktif-riwayat'));
  expect(q('ai-set-briefing-berikutnya').textContent).toMatch(/Berikutnya: Senin, 09 Nov 2026 07[.:]00 WIB/);
  expect(q('ai-set-laporan_mingguan-berikutnya').textContent).toBe('Tidak terjadwal: sedang dimatikan.');
  const baris = [...document.querySelectorAll('[data-testid="ai-set-proaktif-riwayat-baris"]')];
  expect(baris.map((b) => b.dataset.status)).toEqual(['selesai', 'terkirim', 'dilewati']);
  expect(baris[1].textContent).toContain('Piutang jatuh tempo · 3');
  expect(baris[2].textContent).toContain('Manajer Uji');
  expect(baris[2].textContent).toContain('penerima tidak punya akses Asisten AI');
  expect(q('ai-set-proaktif-riwayat').textContent).not.toMatch(/tanpa_akses|piutang:|sesi-b0/);
  expect(q('ai-set-proaktif-ai-mati')).toBeNull();
  klik(baris[0].querySelector('[data-testid="ai-set-proaktif-buka-sesi"]'));
  expect(onNavigate).toHaveBeenCalledWith('asisten-ai', { sesi: 'sesi-b0' });
  expect(baris[2].querySelector('[data-testid="ai-set-proaktif-buka-sesi"]')).toBeNull(); // sesi orang lain
});

test('AI dimatikan → pemberitahuan; GET /proaktif gagal (403) → jadwal & riwayat disembunyikan', async () => {
  asistenApi.ringkasanProaktif.mockResolvedValueOnce({ ...RINGKASAN, ai_aktif: false });
  await tampilkan();
  await tunggu(() => q('ai-set-proaktif-ai-mati'));
  act(() => root.unmount());
  root = createRoot(container);
  asistenApi.ringkasanProaktif.mockRejectedValueOnce(Object.assign(new Error('Hanya owner'), { status: 403 }));
  await tampilkan();
  await act(async () => { await new Promise((r) => setTimeout(r, 50)); });
  expect(q('ai-set-proaktif-riwayat')).toBeNull();
  expect(q('ai-set-briefing-berikutnya')).toBeNull();
});

test('penerima paling banyak 20: pilihan tambah dinonaktifkan', async () => {
  root.render(<></>);
  const ids = Array.from({ length: 20 }, (_, i) => `x${i}`);
  function Penuh() {
    const [form, setForm] = useState(() => ({ ...bacaPengaturanProaktif(SERVER), asisten_briefing_penerima: ids }));
    return <PengaturanProaktif form={form} setField={(k, v) => setForm((f) => ({ ...f, [k]: v }))} user={{ id: 'u1', role: 'owner' }} />;
  }
  await act(async () => { root.render(<Penuh />); });
  await tunggu(() => q('ai-set-penerima-tambah-trigger'));
  expect(q('ai-set-penerima-tambah-trigger').disabled).toBe(true);
  expect(q('ai-set-penerima-tambah-trigger').textContent).toContain('Sudah 20 penerima');
});

test('Jalankan sekarang (owner): dialog konfirmasi → POST jenis → 202 berjalan → toast pesan server + "Buka percakapan"; riwayat dimuat ulang', async () => {
  asistenApi.jalankanProaktif.mockResolvedValue({
    jenis: 'briefing', status: 'berjalan', sesi_id: 'sesi-b1', tautan: '?portal=management&module=asisten-ai&sesi=sesi-b1',
    pesan: 'Briefing pagi sedang disusun. Notifikasi dikirim bila sudah siap.',
  });
  const onNavigate = await tampilkan();
  klik(q('ai-set-briefing-aktif')); // perubahan belum disimpan → disebut di dialog
  klik(q('ai-set-briefing-jalankan'));
  await tunggu(() => q('confirm-dialog'));
  expect(q('confirm-dialog').textContent).toContain('Jalankan briefing pagi sekarang?');
  expect(q('confirm-dialog').textContent).toContain('belum disimpan');
  klik(q('confirm-dialog-cancel'));
  await tunggu(() => !q('confirm-dialog'));
  expect(asistenApi.jalankanProaktif).not.toHaveBeenCalled();
  klik(q('ai-set-briefing-jalankan'));
  await tunggu(() => q('confirm-dialog-ok'));
  await act(async () => { q('confirm-dialog-ok').click(); });
  await tunggu(() => toast.success.mock.calls.length > 0);
  expect(asistenApi.jalankanProaktif).toHaveBeenCalledWith('briefing');
  const [pesan, opsi] = toast.success.mock.calls[0];
  expect(pesan).toBe('Briefing pagi sedang disusun. Notifikasi dikirim bila sudah siap.');
  await tunggu(() => asistenApi.ringkasanProaktif.mock.calls.length >= 2);
  expect(opsi.action.label).toBe('Buka percakapan');
  opsi.action.onClick();
  expect(onNavigate).toHaveBeenCalledWith('asisten-ai', { sesi: 'sesi-b1' });
});

test('peringatan: toast jumlah notifikasi tanpa tautan; galat server → toast galat', async () => {
  asistenApi.jalankanProaktif.mockResolvedValueOnce({
    jenis: 'peringatan', tanggal: '2026-11-08', pemicu: 'manual', pemeriksa: { omzet: 'ok', stok: 'ok', po_piutang: 'ok' },
    kondisi: [{ kondisi: 'omzet', penerima: 'owner', jumlah: 1, dikirim: true }, { kondisi: 'stok', penerima: 'pic', jumlah: 4, dikirim: true }],
    notifikasi: 2,
  })
    .mockRejectedValueOnce(Object.assign(new Error('Hanya owner/superadmin.'), { status: 403 }));
  await tampilkan();
  klik(q('ai-set-peringatan-jalankan'));
  await tunggu(() => q('confirm-dialog-ok'));
  expect(q('confirm-dialog').textContent).toContain('tanpa biaya AI');
  await act(async () => { q('confirm-dialog-ok').click(); });
  await tunggu(() => toast.success.mock.calls.length > 0);
  expect(toast.success.mock.calls[0]).toEqual(['Peringatan harian diperiksa: 2 notifikasi dikirim.', undefined]);
  klik(q('ai-set-laporan_mingguan-jalankan'));
  await tunggu(() => q('confirm-dialog-ok'));
  await act(async () => { q('confirm-dialog-ok').click(); });
  await tunggu(() => toast.error.mock.calls.length > 0);
  expect(toast.error).toHaveBeenCalledWith('Hanya owner/superadmin.');
});

test('admin: tanpa tombol Jalankan sekarang + keterangan; GET /proaktif tidak dipanggil', async () => {
  await tampilkan({ user: { id: 'u3', role: 'admin' } });
  expect(q('ai-set-briefing-jalankan')).toBeNull();
  expect(q('ai-set-proaktif-hanya-owner')).not.toBeNull();
  expect(asistenApi.ringkasanProaktif).not.toHaveBeenCalled();
});

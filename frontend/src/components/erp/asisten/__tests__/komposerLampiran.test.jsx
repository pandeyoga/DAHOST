// Tahap E (layar): lampiran di kotak tanya Asisten AI — pilih/seret berkas, batas 5 berkas & 20 MB, unggah satu per
// satu, chip (mengunggah · gagal · siap), hapus, kirim ditahan selama unggah, kirim membawa id lalu chip kosong.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { toast } from 'sonner';
import { asistenApi } from '../asistenApi';
import AsistenAIModule from '../AsistenAIModule';
import KomposerAsisten from '../KomposerAsisten';
import { MAKS_UKURAN } from '../lampiranAsisten';

jest.mock('../asistenApi', () => ({
  KUNCI_SESI_AKTIF: 'asisten_ai_sesi_aktif',
  unduhLaporan: jest.fn(),
  unduhBerkas: jest.fn(),
  ambilBlobBerkas: jest.fn(),
  asistenApi: {
    status: jest.fn(), saran: jest.fn(), listSessions: jest.fn(), getSession: jest.fn(), createSession: jest.fn(),
    kirimPesan: jest.fn(), putuskan: jest.fn(), renameSession: jest.fn(), deleteSession: jest.fn(),
    unggahLampiran: jest.fn(), hapusLampiran: jest.fn(),
  },
}));
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn(), info: jest.fn() } }));
jest.mock('axios', () => ({ __esModule: true, default: { interceptors: { request: { use: jest.fn(), eject: jest.fn() } } } }));
jest.mock('../GrafikAsisten', () => () => null);

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let root;
let container;
const q = (id) => container.querySelector(`[data-testid="${id}"]`);
const qa = (id) => [...container.querySelectorAll(`[data-testid="${id}"]`)];
const chips = () => qa('asisten-lampiran-chip');
const keadaan = () => chips().map((c) => c.dataset.keadaan);
const diam = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

const berkas = (nama, size = 1000) => {
  const f = new File(['x'], nama);
  Object.defineProperty(f, 'size', { value: size });
  return f;
};
const pilihBerkas = (files) => act(async () => {
  const input = q('asisten-berkas-input');
  Object.defineProperty(input, 'files', { value: files, configurable: true });
  input.dispatchEvent(new Event('change', { bubbles: true }));
});
const ketik = (teks) => act(() => {
  const el = q('asisten-input');
  Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(el, teks);
  el.dispatchEvent(new Event('input', { bubbles: true }));
});
const klik = (el) => act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true })); });

/** Unggahan yang bisa diselesaikan dari uji: setiap panggilan `unggahLampiran` mendapat janji sendiri. */
let unggahan;
function pasangUnggahTertunda() {
  unggahan = [];
  asistenApi.unggahLampiran.mockImplementation((file, opsi) => new Promise((resolve, reject) => {
    unggahan.push({ file, opsi, resolve, reject });
  }));
}
const selesaikan = (i, hasil) => act(async () => { unggahan[i].resolve(hasil); await Promise.resolve(); });

beforeEach(() => {
  jest.clearAllMocks();
  asistenApi.hapusLampiran.mockResolvedValue({ ok: true });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); document.body.innerHTML = ''; });

const renderKomposer = (props = {}) => act(async () => {
  root.render(<KomposerAsisten onKirim={props.onKirim || jest.fn()} lampiranAktif {...props} />);
});

test('tanpa `lampiranAktif` (Asisten ERP) tidak ada tombol lampirkan', async () => {
  await act(async () => { root.render(<KomposerAsisten onKirim={jest.fn()} />); });
  expect(q('asisten-lampirkan')).toBeNull();
  expect(q('asisten-berkas-input')).toBeNull();
});

test('tombol klip membuka pemilih berkas tersembunyi (beberapa berkas, jenis yang didukung)', async () => {
  await renderKomposer();
  const tombol = q('asisten-lampirkan');
  expect(tombol.getAttribute('aria-label')).toBe('Lampirkan berkas');
  const input = q('asisten-berkas-input');
  expect(input.className).toContain('hidden');
  expect(input.multiple).toBe(true);
  expect(input.getAttribute('accept')).toBe('.xlsx,.xls,.csv,.pdf,.png,.jpg,.jpeg,.webp,.gif,.txt,.md,.json');
  const klikInput = jest.spyOn(input, 'click').mockImplementation(() => {});
  await klik(tombol);
  expect(klikInput).toHaveBeenCalledTimes(1);
});

test('jenis tidak didukung & lebih dari 20 MB ditolak dengan pesan; berkas sah diunggah lalu siap', async () => {
  pasangUnggahTertunda();
  await renderKomposer();
  await pilihBerkas([berkas('program.exe'), berkas('besar.pdf', MAKS_UKURAN + 1), berkas('stok.xlsx', 2048)]);
  expect(toast.error).toHaveBeenCalledWith('"program.exe" tidak bisa dilampirkan. Jenis yang bisa: Excel, CSV, PDF, gambar, atau teks.');
  expect(toast.error).toHaveBeenCalledWith('"besar.pdf" lebih dari 20 MB, tidak bisa dilampirkan.');
  expect(asistenApi.unggahLampiran).toHaveBeenCalledTimes(1);
  expect(unggahan[0].file.name).toBe('stok.xlsx');
  expect(keadaan()).toEqual(['mengunggah']);
  act(() => unggahan[0].opsi.onProgress(40));
  expect(q('asisten-lampiran-chip-status').textContent).toBe('Mengunggah 40%');
  await selesaikan(0, { id: 'L1', nama: 'stok.xlsx', jenis: 'tabel', ukuran_kb: 2, ringkas: 'Excel, 1 lembar' });
  expect(keadaan()).toEqual(['siap']);
  expect(q('asisten-lampiran-chip-nama').textContent).toBe('stok.xlsx');
  expect(q('asisten-lampiran-chip-status').textContent).toBe('2 KB');
  expect(q('asisten-lampiran-chip').getAttribute('title')).toBe('stok.xlsx — Excel, 1 lembar');
});

test('paling banyak 5 berkas; unggahan berjalan satu per satu', async () => {
  pasangUnggahTertunda();
  await renderKomposer();
  await pilihBerkas(['a.csv', 'b.csv', 'c.csv', 'd.csv', 'e.csv', 'f.csv'].map((n) => berkas(n)));
  expect(toast.error).toHaveBeenCalledWith('Paling banyak 5 berkas untuk satu pertanyaan.');
  expect(chips()).toHaveLength(5);
  expect(asistenApi.unggahLampiran).toHaveBeenCalledTimes(1); // yang lain menunggu giliran
  await selesaikan(0, { id: 'L1', nama: 'a.csv', jenis: 'tabel', ukuran_kb: 1 });
  await diam();
  expect(asistenApi.unggahLampiran).toHaveBeenCalledTimes(2);
  expect(unggahan[1].file.name).toBe('b.csv');
  // sudah penuh → klik tombol klip tidak membuka pemilih, hanya pesan
  const input = q('asisten-berkas-input');
  const klikInput = jest.spyOn(input, 'click').mockImplementation(() => {});
  toast.error.mockClear();
  await klik(q('asisten-lampirkan'));
  expect(klikInput).not.toHaveBeenCalled();
  expect(toast.error).toHaveBeenCalledWith('Paling banyak 5 berkas untuk satu pertanyaan.');
});

test('kirim ditahan selama unggah; setelah siap kirim membawa id lampiran lalu chip dikosongkan', async () => {
  pasangUnggahTertunda();
  const onKirim = jest.fn();
  await renderKomposer({ onKirim });
  await pilihBerkas([berkas('stok.xlsx')]);
  await ketik('Bandingkan dengan stok sistem');
  expect(q('asisten-kirim').disabled).toBe(true);
  // Enter selama unggah → tidak terkirim, ada pesan tunggu
  await act(async () => { q('asisten-input').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); });
  expect(onKirim).not.toHaveBeenCalled();
  expect(toast.info).toHaveBeenCalledWith('Tunggu sampai berkas selesai diunggah.');
  await selesaikan(0, { id: 'L1', nama: 'stok.xlsx', jenis: 'tabel', ukuran_kb: 48 });
  expect(q('asisten-kirim').disabled).toBe(false);
  await klik(q('asisten-kirim'));
  expect(onKirim).toHaveBeenCalledWith('Bandingkan dengan stok sistem', {
    lampiran: [{ id: 'L1', nama: 'stok.xlsx', jenis: 'tabel', ukuran_kb: 48 }],
  });
  expect(chips()).toHaveLength(0);
  expect(q('asisten-input').value).toBe('');
  expect(asistenApi.hapusLampiran).not.toHaveBeenCalled(); // terkirim → tidak dihapus
});

test('teks tetap wajib: lampiran saja tidak bisa dikirim', async () => {
  asistenApi.unggahLampiran.mockResolvedValue({ id: 'L1', nama: 'a.pdf', jenis: 'pdf', ukuran_kb: 5 });
  const onKirim = jest.fn();
  await renderKomposer({ onKirim });
  await pilihBerkas([berkas('a.pdf')]);
  await diam();
  expect(keadaan()).toEqual(['siap']);
  expect(q('asisten-kirim').disabled).toBe(true);
  await klik(q('asisten-kirim'));
  expect(onKirim).not.toHaveBeenCalled();
});

test('hapus chip: yang sudah diunggah dihapus di server; yang sedang diunggah dibatalkan', async () => {
  pasangUnggahTertunda();
  await renderKomposer();
  await pilihBerkas([berkas('a.csv'), berkas('b.png')]);
  await selesaikan(0, { id: 'L1', nama: 'a.csv', jenis: 'tabel', ukuran_kb: 1 });
  await diam();
  expect(keadaan()).toEqual(['siap', 'mengunggah']);
  const tombolHapus = qa('asisten-lampiran-chip-hapus');
  expect(tombolHapus[0].getAttribute('aria-label')).toBe('Hapus lampiran a.csv');
  await klik(tombolHapus[0]);
  expect(asistenApi.hapusLampiran).toHaveBeenCalledWith('L1');
  expect(keadaan()).toEqual(['mengunggah']);
  const sinyal = unggahan[1].opsi.signal;
  await klik(qa('asisten-lampiran-chip-hapus')[0]);
  expect(sinyal.aborted).toBe(true);
  expect(chips()).toHaveLength(0);
  // server tetap selesai menyimpan sebelum batal sampai → lampiran itu dihapus juga, chip tidak muncul lagi
  await selesaikan(1, { id: 'L2', nama: 'b.png', jenis: 'gambar', ukuran_kb: 3 });
  expect(asistenApi.hapusLampiran).toHaveBeenCalledWith('L2');
  expect(chips()).toHaveLength(0);
});

test('unggah gagal → chip "Gagal" + pesan; tidak ikut terkirim dan tidak menghitung batas', async () => {
  asistenApi.unggahLampiran.mockRejectedValue(Object.assign(new Error('Jenis berkas tidak didukung.'), { status: 400 }));
  const onKirim = jest.fn();
  await renderKomposer({ onKirim });
  await pilihBerkas([berkas('rusak.xlsx')]);
  await diam();
  expect(keadaan()).toEqual(['gagal']);
  expect(q('asisten-lampiran-chip').getAttribute('title')).toBe('rusak.xlsx — Jenis berkas tidak didukung.');
  expect(q('asisten-lampiran-chip-status').textContent).toBe('Gagal');
  expect(toast.error).toHaveBeenCalledWith('"rusak.xlsx" gagal diunggah. Jenis berkas tidak didukung.');
  await ketik('Tolong baca');
  await klik(q('asisten-kirim'));
  expect(onKirim).toHaveBeenCalledWith('Tolong baca', { lampiran: [] });
});

test('seret-dan-lepas berkas ke kotak tanya', async () => {
  asistenApi.unggahLampiran.mockResolvedValue({ id: 'L9', nama: 'catatan.txt', jenis: 'teks', ukuran_kb: 1 });
  await renderKomposer();
  const kotak = q('asisten-kotak');
  const dataTransfer = { types: ['Files'], files: [berkas('catatan.txt')], dropEffect: 'none' };
  const seret = (jenis) => act(async () => {
    const e = new Event(jenis, { bubbles: true, cancelable: true });
    Object.defineProperty(e, 'dataTransfer', { value: dataTransfer });
    kotak.dispatchEvent(e);
  });
  await seret('dragover');
  expect(kotak.dataset.seret).toBe('1');
  expect(q('asisten-lepas').textContent).toBe('Lepaskan berkas di sini untuk melampirkan');
  await seret('drop');
  await diam();
  expect(kotak.dataset.seret).toBeUndefined();
  expect(asistenApi.unggahLampiran).toHaveBeenCalledWith(dataTransfer.files[0], expect.any(Object));
  expect(keadaan()).toEqual(['siap']);
});

test('keluar dari halaman: lampiran yang belum dikirim dihapus di server', async () => {
  asistenApi.unggahLampiran.mockResolvedValue({ id: 'L5', nama: 'a.csv', jenis: 'tabel', ukuran_kb: 1 });
  await renderKomposer();
  await pilihBerkas([berkas('a.csv')]);
  await diam();
  act(() => root.render(<div />));
  await diam();
  expect(asistenApi.hapusLampiran).toHaveBeenCalledWith('L5');
});

test('halaman Asisten AI: kirim dengan lampiran → id ke server, chip tampil di gelembung pertanyaan', async () => {
  window.sessionStorage.clear();
  global.fetch = jest.fn(() => Promise.resolve({ ok: false, json: () => Promise.resolve(null) }));
  asistenApi.status.mockResolvedValue({ siap: true, model: 'Claude Opus 5.5', tindakan_aktif: true });
  asistenApi.saran.mockResolvedValue([]);
  asistenApi.listSessions.mockResolvedValue([]);
  asistenApi.createSession.mockResolvedValue({ id: 's-baru', judul: 'Cocokkan stok' });
  asistenApi.kirimPesan.mockImplementation(async (sid, isi, { onEvent }) => {
    onEvent({ event: 'teks', data: { delta: 'Sudah saya cocokkan.' } });
    onEvent({ event: 'berkas', data: { id: 'f1', nama: 'selisih_stok.xlsx', format: 'xlsx', ukuran_kb: 12, url: '/api/asisten-ai/berkas/f1' } });
    onEvent({ event: 'selesai', data: { pesan_id: 'p1' } });
    return { aborted: false };
  });
  asistenApi.unggahLampiran.mockResolvedValue({ id: 'L1', nama: 'stok-gudang.xlsx', jenis: 'tabel', ukuran_kb: 48 });
  await act(async () => { root.render(<AsistenAIModule user={{ id: 'u1', role: 'owner' }} onNavigate={jest.fn()} />); });
  await diam();
  await pilihBerkas([berkas('stok-gudang.xlsx')]);
  await diam();
  await ketik('Cocokkan stok');
  await klik(q('asisten-kirim'));
  await diam();
  expect(asistenApi.kirimPesan).toHaveBeenCalledWith('s-baru', expect.objectContaining({ teks: 'Cocokkan stok', lampiran: ['L1'] }), expect.any(Object));
  const gelembung = q('asisten-pesan-pengguna');
  expect(gelembung.querySelector('[data-testid="asisten-pesan-lampiran-chip-nama"]').textContent).toBe('stok-gudang.xlsx');
  expect(chips()).toHaveLength(0); // kotak tanya kosong lagi
  expect(q('asisten-berkas-nama').textContent).toBe('selisih_stok.xlsx');
  expect(q('asisten-pesan-asisten').dataset.keadaan).toBe('selesai');
});

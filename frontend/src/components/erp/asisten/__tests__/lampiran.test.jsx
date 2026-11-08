// Tahap E (layar): logika lampiran & berkas keluaran, peristiwa SSE `berkas`, kartu unduh, chip lampiran di riwayat,
// dan panggilan API lampiran (kirim membawa id, unggah multipart field `berkas` bertoken).
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { toast } from 'sonner';
import {
  MAKS_UKURAN, blokBerkas, infoFormat, jenisLampiran, normalLampiran, potongNama, saringBerkas, teksUkuranKb,
} from '../lampiranAsisten';
import { JENIS_ISI, dariRiwayat, pesanAsistenBaru, terapkanPeristiwa } from '../peristiwaSse';
import { ambilBlobBerkas, asistenApi, unduhBerkas } from '../asistenApi';
import PesanAsisten from '../PesanAsisten';
import UtasPesan from '../UtasPesan';
import { sseFetch } from '@/lib/sseFetch';

jest.mock('../asistenApi', () => {
  const asli = jest.requireActual('../asistenApi');
  return { ...asli, unduhBerkas: jest.fn(), ambilBlobBerkas: jest.fn() };
});
jest.mock('@/lib/sseFetch', () => ({ sseFetch: jest.fn() }));
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn(), info: jest.fn() } }));
jest.mock('axios', () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn(), interceptors: { request: { use: jest.fn(), eject: jest.fn() } } } }));
jest.mock('../GrafikAsisten', () => () => null);

const berkas = (nama, size = 1000) => {
  const f = new File(['x'], nama);
  Object.defineProperty(f, 'size', { value: size });
  return f;
};

describe('lampiranAsisten (logika murni)', () => {
  test('jenis lampiran dari nama berkas (Kontrak K2)', () => {
    expect(['a.xlsx', 'b.XLS', 'c.csv', 'd.pdf', 'e.png', 'f.JPG', 'g.jpeg', 'h.webp', 'i.gif', 'j.txt', 'k.md', 'l.json']
      .map(jenisLampiran)).toEqual(['tabel', 'tabel', 'tabel', 'pdf', 'gambar', 'gambar', 'gambar', 'gambar', 'gambar', 'teks', 'teks', 'teks']);
    expect(jenisLampiran('kontrak.docx')).toBeNull();
    expect(jenisLampiran('tanpa-ekstensi')).toBeNull();
  });

  test('saring: jenis tidak didukung, > 20 MB, kosong, dan batas 5 berkas → pesan jelas', () => {
    const { diterima, ditolak } = saringBerkas([
      berkas('virus.exe'), berkas('besar.pdf', MAKS_UKURAN + 1), berkas('kosong.csv', 0),
      berkas('a.xlsx'), berkas('b.csv'), berkas('c.png'),
    ], 3);
    expect(diterima.map((f) => f.name)).toEqual(['a.xlsx', 'b.csv']);
    expect(ditolak.map((t) => t.alasan)).toEqual(['jenis', 'ukuran', 'kosong', 'jumlah']);
    expect(ditolak[0].pesan).toBe('"virus.exe" tidak bisa dilampirkan. Jenis yang bisa: Excel, CSV, PDF, gambar, atau teks.');
    expect(ditolak[1].pesan).toBe('"besar.pdf" lebih dari 20 MB, tidak bisa dilampirkan.');
    expect(ditolak[3].pesan).toBe('Paling banyak 5 berkas untuk satu pertanyaan.');
    // tepat 20 MB masih boleh
    expect(saringBerkas([berkas('pas.pdf', MAKS_UKURAN)]).diterima).toHaveLength(1);
  });

  test('ukuran & nama untuk dibaca orang', () => {
    expect(teksUkuranKb(0.2)).toBe('1 KB');
    expect(teksUkuranKb(48)).toBe('48 KB');
    expect(teksUkuranKb(1536)).toBe('1,5 MB');
    expect(teksUkuranKb(20480)).toBe('20 MB');
    expect(teksUkuranKb(null)).toBe('');
    expect(potongNama('pendek.xlsx')).toBe('pendek.xlsx');
    const p = potongNama('laporan-penjualan-semua-toko-oktober-2026.xlsx');
    expect(p.length).toBeLessThanOrEqual(28);
    expect(p.endsWith('.xlsx')).toBe(true);
    expect(p).toContain('…');
  });

  test('format berkas keluaran → kelompok ikon & label', () => {
    expect(['xlsx', 'csv', 'docx', 'pptx', 'png', 'jpg', 'pdf', 'zip'].map((f) => infoFormat(f).kelompok))
      .toEqual(['tabel', 'tabel', 'dokumen', 'presentasi', 'gambar', 'gambar', 'pdf', 'lain']);
    expect(infoFormat('xlsx').label).toBe('Excel');
    expect(infoFormat('zip').label).toBe('Berkas ZIP');
  });

  test('normalLampiran & blokBerkas: tanpa id dibuang; format dari nama; url cadangan', () => {
    expect(normalLampiran([{ id: 'L1', nama: 'a.csv', ukuran_kb: 3 }, { nama: 'tanpa-id.pdf' }, null]))
      .toEqual([{ id: 'L1', nama: 'a.csv', jenis: 'tabel', ukuran_kb: 3 }]);
    expect(blokBerkas({ nama: 'x.xlsx' })).toBeNull();
    expect(blokBerkas({ id: 'b 1', nama: 'pivot.xlsx', ukuran_kb: 24 })).toEqual({
      jenis: 'berkas', id: 'b 1', nama: 'pivot.xlsx', format: 'xlsx', ukuran_kb: 24, url: '/api/asisten-ai/berkas/b%201',
    });
  });
});

describe('peristiwa SSE `berkas` (Kontrak K3)', () => {
  test('menjadi blok berkas, termasuk isi jawaban; id sama tidak digandakan; tanpa id diabaikan', () => {
    let p = pesanAsistenBaru('t');
    p = terapkanPeristiwa(p, 'teks', { delta: 'Berkasnya sudah siap.' });
    p = terapkanPeristiwa(p, 'berkas', { id: 'f1', nama: 'pivot_omzet.xlsx', format: 'xlsx', ukuran_kb: 24, url: '/api/asisten-ai/berkas/f1' });
    p = terapkanPeristiwa(p, 'berkas', { id: 'f1', nama: 'pivot_omzet.xlsx', format: 'xlsx', ukuran_kb: 25, url: '/api/asisten-ai/berkas/f1' });
    const sama = terapkanPeristiwa(p, 'berkas', { nama: 'tanpa-id.png' });
    expect(sama).toBe(p);
    expect(p.blok.map((b) => b.jenis)).toEqual(['teks', 'berkas']);
    expect(p.blok[1]).toEqual({ jenis: 'berkas', id: 'f1', nama: 'pivot_omzet.xlsx', format: 'xlsx', ukuran_kb: 25, url: '/api/asisten-ai/berkas/f1' });
    expect(JENIS_ISI.has('berkas')).toBe(true);
  });

  test('riwayat: pesan pengguna membawa lampiran; pesan asisten tidak', () => {
    const u = dariRiwayat({ id: 'u1', peran: 'user', teks: 'Bandingkan', lampiran: [{ id: 'L1', nama: 'stok.xlsx', jenis: 'tabel', ukuran_kb: 48 }] });
    expect(u.lampiran).toEqual([{ id: 'L1', nama: 'stok.xlsx', jenis: 'tabel', ukuran_kb: 48 }]);
    expect(dariRiwayat({ id: 'u2', peran: 'user', teks: 'Halo' }).lampiran).toEqual([]);
    expect(dariRiwayat({ id: 'a1', peran: 'asisten', blok: [] }).lampiran).toBeUndefined();
  });
});

describe('asistenApi lampiran', () => {
  test('kirimPesan meneruskan id lampiran; tanpa lampiran badan tetap seperti dulu', async () => {
    sseFetch.mockResolvedValue({ aborted: false });
    await asistenApi.kirimPesan('s1', { teks: 'Ringkas', cv: 'DA', lampiran: ['L1', { id: 'L2' }] });
    expect(sseFetch.mock.calls[0][1].body).toEqual({ teks: 'Ringkas', cv: 'DA', lampiran: ['L1', 'L2'] });
    await asistenApi.kirimPesan('s1', { teks: 'Halo', cv: 'DA' });
    expect(sseFetch.mock.calls[1][1].body).toEqual({ teks: 'Halo', cv: 'DA' });
  });

  describe('unggahLampiran (XHR)', () => {
    let xhr;
    const XhrAsli = global.XMLHttpRequest;
    beforeEach(() => {
      window.localStorage.setItem('erp_token', 'tok-uji');
      xhr = null;
      global.XMLHttpRequest = jest.fn(function FakeXhr() {
        xhr = this;
        this.headers = {};
        this.upload = {};
        this.open = jest.fn((m, u) => { this.method = m; this.url = u; });
        this.setRequestHeader = jest.fn((k, v) => { this.headers[k] = v; });
        this.send = jest.fn((body) => { this.body = body; });
        this.abort = jest.fn(() => this.onabort?.());
      });
    });
    afterEach(() => { global.XMLHttpRequest = XhrAsli; window.localStorage.clear(); });

    test('multipart field `berkas`, token, kemajuan, lalu hasil server', async () => {
      const onProgress = jest.fn();
      const f = berkas('stok.xlsx', 2048);
      const janji = asistenApi.unggahLampiran(f, { onProgress });
      expect(xhr.method).toBe('POST');
      expect(xhr.url).toMatch(/\/api\/asisten-ai\/lampiran$/);
      expect(xhr.headers.Authorization).toBe('Bearer tok-uji');
      expect(xhr.body).toBeInstanceOf(FormData);
      expect(xhr.body.get('berkas')).toBe(f);
      xhr.upload.onprogress({ lengthComputable: true, loaded: 1, total: 4 });
      expect(onProgress).toHaveBeenCalledWith(25);
      xhr.status = 200;
      xhr.responseText = JSON.stringify({ id: 'L1', nama: 'stok.xlsx', jenis: 'tabel', ukuran_kb: 2 });
      xhr.onload();
      await expect(janji).resolves.toMatchObject({ id: 'L1', jenis: 'tabel' });
    });

    test('413 tanpa badan JSON → pesan ramah; batal → galat `dibatalkan`', async () => {
      const j1 = asistenApi.unggahLampiran(berkas('besar.pdf'));
      xhr.status = 413;
      xhr.responseText = '<html>Request Entity Too Large</html>';
      xhr.onload();
      await expect(j1).rejects.toMatchObject({ status: 413, message: 'Berkas lebih dari 20 MB.' });

      const ctrl = new AbortController();
      const j2 = asistenApi.unggahLampiran(berkas('a.csv'), { signal: ctrl.signal });
      ctrl.abort();
      await expect(j2).rejects.toMatchObject({ dibatalkan: true });
    });

    test('400 dengan pesan server → pesan server ditampilkan', async () => {
      const j = asistenApi.unggahLampiran(berkas('a.csv'));
      xhr.status = 400;
      xhr.responseText = JSON.stringify({ detail: 'Jenis berkas tidak didukung.' });
      xhr.onload();
      await expect(j).rejects.toMatchObject({ status: 400, message: 'Jenis berkas tidak didukung.' });
    });
  });
});

describe('tampilan', () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  let root;
  let container;
  const q = (id) => container.querySelector(`[data-testid="${id}"]`);
  const qa = (id) => [...container.querySelectorAll(`[data-testid="${id}"]`)];
  let revokeObjectURL;

  beforeEach(() => {
    jest.clearAllMocks();
    URL.createObjectURL = jest.fn(() => 'blob:pratinjau-1');
    revokeObjectURL = jest.fn();
    URL.revokeObjectURL = revokeObjectURL;
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(() => { act(() => root.unmount()); document.body.innerHTML = ''; });

  test('kartu berkas: ikon menurut format, nama, format & ukuran, Unduh lewat unduhBerkas', async () => {
    unduhBerkas.mockResolvedValue();
    const pesan = {
      id: 'm1', peran: 'asisten', keadaan: 'selesai', blok: [
        { jenis: 'teks', isi: 'Ini hasil pivotnya.' },
        { jenis: 'berkas', id: 'f1', nama: 'pivot_omzet.xlsx', format: 'xlsx', ukuran_kb: 24, url: '/api/asisten-ai/berkas/f1' },
        { jenis: 'berkas', id: 'f2', nama: 'ringkasan.docx', format: 'docx', ukuran_kb: 2048, url: '/api/asisten-ai/berkas/f2' },
        { jenis: 'berkas', id: 'f3', nama: 'paparan.pptx', format: 'pptx', ukuran_kb: 300, url: '/api/asisten-ai/berkas/f3' },
      ],
    };
    await act(async () => { root.render(<PesanAsisten pesan={pesan} />); });
    const kartu = qa('asisten-berkas');
    expect(kartu.map((k) => k.dataset.format)).toEqual(['xlsx', 'docx', 'pptx']);
    expect(qa('asisten-berkas-ikon').map((i) => i.dataset.kelompok)).toEqual(['tabel', 'dokumen', 'presentasi']);
    expect(qa('asisten-berkas-nama').map((n) => n.textContent)).toEqual(['pivot_omzet.xlsx', 'ringkasan.docx', 'paparan.pptx']);
    expect(qa('asisten-berkas-info').map((n) => n.textContent)).toEqual(['Excel · 24 KB', 'Dokumen Word · 2 MB', 'Presentasi PowerPoint · 300 KB']);
    expect(q('asisten-laporan')).toBeNull(); // bukan tombol laporan lama
    expect(qa('asisten-berkas-pratinjau')).toHaveLength(0); // bukan gambar → tanpa pratinjau
    await act(async () => { qa('asisten-berkas-unduh')[0].dispatchEvent(new MouseEvent('click', { bubbles: true })); });
    expect(unduhBerkas).toHaveBeenCalledWith(expect.objectContaining({ id: 'f1', nama: 'pivot_omzet.xlsx', url: '/api/asisten-ai/berkas/f1' }));
  });

  test('unduh gagal → toast galat', async () => {
    unduhBerkas.mockRejectedValue(new Error('Berkas tidak ditemukan.'));
    const pesan = { id: 'm', peran: 'asisten', keadaan: 'selesai', blok: [{ jenis: 'berkas', id: 'f1', nama: 'a.csv', format: 'csv', ukuran_kb: 1 }] };
    await act(async () => { root.render(<PesanAsisten pesan={pesan} />); });
    await act(async () => { q('asisten-berkas-unduh').dispatchEvent(new MouseEvent('click', { bubbles: true })); });
    expect(toast.error).toHaveBeenCalledWith('Berkas tidak ditemukan.');
  });

  test('gambar: pratinjau dimuat bertoken → alamat sementara, dibersihkan saat kartu hilang', async () => {
    ambilBlobBerkas.mockResolvedValue(new Blob(['png'], { type: 'image/png' }));
    const pesan = { id: 'm', peran: 'asisten', keadaan: 'selesai', blok: [{ jenis: 'berkas', id: 'g1', nama: 'tren.png', format: 'png', ukuran_kb: 80 }] };
    await act(async () => { root.render(<PesanAsisten pesan={pesan} />); });
    expect(ambilBlobBerkas).toHaveBeenCalledWith({ id: 'g1', url: '/api/asisten-ai/berkas/g1' });
    const img = q('asisten-berkas-pratinjau');
    expect(img.getAttribute('src')).toBe('blob:pratinjau-1');
    expect(img.getAttribute('alt')).toBe('Pratinjau tren.png');
    expect(qa('asisten-berkas-info')[0].textContent).toBe('Gambar PNG · 80 KB');
    act(() => root.render(<div />));
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:pratinjau-1');
  });

  test('pesan pengguna menampilkan chip lampiran (nama + ukuran) di atas gelembungnya', () => {
    const pesan = [
      { kunci: 'u1', peran: 'user', teks: 'Cocokkan dengan stok sistem', lampiran: [
        { id: 'L1', nama: 'stok-gudang.xlsx', jenis: 'tabel', ukuran_kb: 48 },
        { id: 'L2', nama: 'foto-rak.jpg', jenis: 'gambar', ukuran_kb: 900 },
      ] },
      { kunci: 'u2', peran: 'user', teks: 'Tanpa lampiran' },
    ];
    act(() => { root.render(<UtasPesan pesan={pesan} memuat={false} kosong={null} />); });
    const gelembung = qa('asisten-pesan-pengguna');
    const chips = [...gelembung[0].querySelectorAll('[data-testid="asisten-pesan-lampiran-chip"]')];
    expect(chips.map((c) => c.querySelector('[data-testid="asisten-pesan-lampiran-chip-nama"]').textContent)).toEqual(['stok-gudang.xlsx', 'foto-rak.jpg']);
    expect(chips.map((c) => c.querySelector('[data-testid="asisten-pesan-lampiran-chip-status"]').textContent)).toEqual(['48 KB', '900 KB']);
    expect(chips[0].querySelector('button')).toBeNull(); // di riwayat tidak bisa dihapus
    expect(gelembung[0].textContent).toContain('Cocokkan dengan stok sistem');
    expect(gelembung[1].querySelector('[data-testid="asisten-pesan-lampiran"]')).toBeNull();
  });
});

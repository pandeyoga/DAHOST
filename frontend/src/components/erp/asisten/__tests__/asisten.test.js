import { validasiSpec, irisanPai, pemformatSatuan } from '../grafikSpec';
import { terapkanPeristiwa, pesanAsistenBaru, kelompokkanSesi, judulDariTeks, dariRiwayat } from '../peristiwaSse';

describe('validasiSpec (Kontrak B grafik)', () => {
  const dasar = { jenis: 'batang', judul: 'Omzet', satuan: 'Rp', x: ['A', 'B'], seri: [{ nama: 'Nov', nilai: [1, 2] }] };

  test('spesifikasi sah', () => {
    const v = validasiSpec(dasar);
    expect(v.ok).toBe(true);
    expect(v.seri[0].nilai).toEqual([1, 2]);
  });

  test.each([
    [null, 'data grafik kosong'],
    [{ ...dasar, jenis: 'radar' }, 'jenis grafik tidak dikenal'],
    [{ ...dasar, x: [] }, 'tidak ada kategori'],
    [{ ...dasar, seri: [] }, 'tidak ada seri angka'],
    [{ ...dasar, seri: [{ nama: 'x', nilai: ['abc', null] }] }, 'semua nilai kosong'],
  ])('tidak sah → alasan, tidak melempar (%#)', (spec, alasan) => {
    expect(validasiSpec(spec)).toEqual({ ok: false, alasan });
  });

  test('batas: 4 seri, 31 titik; pai 1 seri; pai bernilai negatif → batang', () => {
    const banyak = { ...dasar, x: Array.from({ length: 40 }, (_, i) => `d${i}`), seri: Array.from({ length: 6 }, (_, i) => ({ nama: `s${i}`, nilai: [i] })) };
    const v = validasiSpec(banyak);
    expect(v.x).toHaveLength(31);
    expect(v.seri).toHaveLength(4);
    expect(validasiSpec({ ...banyak, jenis: 'pai' }).seri).toHaveLength(1);
    expect(validasiSpec({ ...dasar, jenis: 'pai', seri: [{ nama: 'x', nilai: [5, -1] }] }).jenis).toBe('batang');
  });

  test('pai: maksimal 5 warna + Lainnya', () => {
    const v = validasiSpec({ jenis: 'pai', x: ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'], seri: [{ nama: 'x', nilai: [8, 7, 6, 5, 4, 3, 2, 1] }] });
    const ir = irisanPai(v);
    expect(ir).toHaveLength(6);
    expect(ir[5].nama).toBe('Lainnya (3)');
    expect(ir[5].nilai).toBe(6);
  });

  test('pemformat satuan gaya Indonesia', () => {
    expect(pemformatSatuan('Rp').penuh(142300000)).toBe('Rp 142.300.000');
    expect(pemformatSatuan('Rp').sumbu(142300000)).toBe('142,3 jt');
    expect(pemformatSatuan('%').penuh(17.5)).toBe('17,5%');
    expect(pemformatSatuan('pcs').penuh(1200)).toBe('1.200 pcs');
  });
});

describe('terapkanPeristiwa (SSE → blok)', () => {
  test('urutan lengkap Kontrak B', () => {
    let p = pesanAsistenBaru('tmp');
    const ev = [
      ['mulai', { pesan_id: 'p1' }],
      ['status', { teks: 'Membaca ringkasan penjualan…' }],
      ['alat', { id: 't1', nama: 'ringkasan_penjualan', label: 'Membaca ringkasan penjualan', keadaan: 'mulai' }],
      ['pikir', { teks: 'Bandingkan ' }],
      ['pikir', { teks: 'Okt dan Nov.' }],
      ['alat', { id: 't1', nama: 'ringkasan_penjualan', keadaan: 'selesai' }],
      ['teks', { delta: 'Omzet ' }],
      ['teks', { delta: 'naik.' }],
      ['grafik', { id: 'g1', spec: { jenis: 'garis' } }],
      ['teks', { delta: 'Rinciannya:' }],
      ['tabel', { id: 'tb1', judul: 'Per toko', kolom: ['Toko'], baris: [['A']] }],
      ['sumber', { item: [{ jenis: 'web', label: 'Situs', url: 'https://example.com' }] }],
      ['laporan', { id: 'l1', judul: 'Laporan', format: 'pdf', url: '/api/asisten-ai/laporan/l1' }],
      ['selesai', { pesan_id: 'p1', pemakaian: { token_masuk: 10 } }],
    ];
    ev.forEach(([e, d]) => { p = terapkanPeristiwa(p, e, d); });
    expect(p.id).toBe('p1');
    expect(p.keadaan).toBe('selesai');
    expect(p.blok.map((b) => b.jenis)).toEqual(['alat', 'pikir_ringkas', 'teks', 'grafik', 'teks', 'tabel', 'sumber', 'laporan']);
    expect(p.blok[0]).toMatchObject({ keadaan: 'selesai', label: 'Membaca ringkasan penjualan' });
    expect(p.blok[1].isi).toBe('Bandingkan Okt dan Nov.');
    expect(p.blok[2].isi).toBe('Omzet naik.');
    expect(p.pemakaian).toEqual({ token_masuk: 10 });
  });

  test('galat → pesan ramah', () => {
    const p = terapkanPeristiwa(pesanAsistenBaru('t'), 'galat', { kode: 'anggaran_habis', pesan: 'Anggaran habis.' });
    expect(p.keadaan).toBe('galat');
    expect(p.galat).toEqual({ kode: 'anggaran_habis', pesan: 'Anggaran habis.' });
  });

  test('peristiwa tak dikenal tidak mengubah pesan', () => {
    const p = pesanAsistenBaru('t');
    expect(terapkanPeristiwa(p, 'aneh', {})).toBe(p);
  });
});

describe('riwayat', () => {
  test('kelompok Hari ini / Kemarin / Lebih lama (WIB)', () => {
    const now = new Date('2026-11-08T05:00:00Z'); // 12.00 WIB
    const g = kelompokkanSesi([
      { id: 'a', updated_at: '2026-11-08T01:00:00Z' },
      { id: 'b', updated_at: '2026-11-07T10:00:00Z' },
      { id: 'c', updated_at: '2026-11-07T18:30:00Z' }, // 01.30 WIB 8 Nov → hari ini
      { id: 'd', updated_at: '2026-10-01T10:00:00Z' },
    ], now);
    expect(g.map((x) => [x.label, x.items.map((i) => i.id)])).toEqual([
      ['Hari ini', ['a', 'c']], ['Kemarin', ['b']], ['Lebih lama', ['d']],
    ]);
  });

  test('judul dari teks dan pesan dari riwayat', () => {
    expect(judulDariTeks('  omzet   bulan ini  ')).toBe('omzet bulan ini');
    expect(judulDariTeks('x'.repeat(80))).toHaveLength(58);
    const u = dariRiwayat({ id: 'm1', peran: 'user', blok: [{ jenis: 'teks', isi: 'Halo' }] });
    expect(u).toMatchObject({ peran: 'user', teks: 'Halo' });
    expect(dariRiwayat({ id: 'm2', peran: 'asisten', blok: [], keadaan: 'terhenti' }).keadaan).toBe('terhenti');
    // bentuk asli backend (simpan.py): kolom `status`
    expect(dariRiwayat({ id: 'm3', peran: 'asisten', blok: [], status: 'terhenti' }).keadaan).toBe('terhenti');
    expect(dariRiwayat({ id: 'm4', peran: 'asisten', blok: [], status: 'gagal' }).keadaan).toBe('galat');
    expect(dariRiwayat({ id: 'm5', peran: 'asisten', blok: [], status: 'selesai' }).keadaan).toBe('selesai');
  });
});

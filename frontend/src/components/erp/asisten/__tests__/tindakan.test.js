import { JENIS_ISI, dariRiwayat, pesanAsistenBaru, terapkanPeristiwa } from '../peristiwaSse';
import {
  KEADAAN_TINDAKAN, bacaDaftarTindakan, bacaNilaiUbah, bolehSemuaPengguna, formatNilaiUbah, kartuMenunggu,
  keadaanEfektif, keadaanTindakan, kedaluwarsakanMenunggu, labelKunci, queryDaftar, ratakanNilai, susunUbahan,
  tautanAman, terapkanStatusTindakan, terapkanUbahanKeRencana, ubahKartu,
} from '../tindakanAsisten';

const RENCANA = {
  judul: 'Pasang target toko November 2026',
  ringkas: '3 toko, skenario realistis.',
  perubahan: [
    { label: 'Shopee Toko A', sebelum: 'Rp 120.000.000', sesudah: 'Rp 135.000.000' },
    { label: 'TikTok Toko C', sebelum: '—', sesudah: 'Rp 80.000.000' },
  ],
  catatan: ['Periode November masih terbuka.'],
  peringatan: [],
  ubah: [
    { kunci: 'toko.0.target', label: 'Target Shopee Toko A', jenis: 'rupiah', nilai: 135000000 },
    { kunci: 'toko.1.target', label: 'Target TikTok Toko C', jenis: 'rupiah', nilai: 80000000 },
    { kunci: 'rasio', label: 'Rasio', jenis: 'angka', nilai: 1.12 },
    { kunci: 'catatan', label: 'Catatan', jenis: 'teks', nilai: 'Realistis' },
    { kunci: 'mulai', label: 'Mulai', jenis: 'tanggal', nilai: '2026-11-01' },
    { kunci: 'skenario', label: 'Skenario', jenis: 'pilihan', nilai: 2, pilihan: [{ nilai: 1, label: 'Konservatif' }, { nilai: 2, label: 'Realistis' }] },
  ],
  tautan: { label: 'Buka layar Target', menu: 'mkt-targets' },
};
const EV_TINDAKAN = { id: 'tnd-1', nama: 'pasang_target_toko', label: 'Memasang target toko', risiko: 'rendah', keadaan: 'menunggu', rencana: RENCANA, kedaluwarsa_pada: '2026-11-09T03:00:00Z' };

describe('terapkanPeristiwa: tindakan & tindakan_status (Kontrak E)', () => {
  test('`tindakan` menambah blok kartu sesuai urutan datang, bentuk = blok tersimpan', () => {
    let p = pesanAsistenBaru('tmp');
    p = terapkanPeristiwa(p, 'teks', { delta: 'Saya siapkan targetnya.' });
    p = terapkanPeristiwa(p, 'tindakan', EV_TINDAKAN);
    expect(p.blok.map((b) => b.jenis)).toEqual(['teks', 'tindakan']);
    expect(p.blok[1]).toEqual({
      jenis: 'tindakan', id: 'tnd-1', nama: 'pasang_target_toko', label: 'Memasang target toko', risiko: 'rendah',
      keadaan: 'menunggu', rencana: RENCANA, kedaluwarsa_pada: '2026-11-09T03:00:00Z',
    });
    // id sama datang lagi → digabung, tidak dobel
    const q = terapkanPeristiwa(p, 'tindakan', { ...EV_TINDAKAN, label: 'Label baru' });
    expect(q.blok.filter((b) => b.jenis === 'tindakan')).toHaveLength(1);
    expect(q.blok[1].label).toBe('Label baru');
    // tanpa id diabaikan; risiko tak dikenal → rendah
    expect(terapkanPeristiwa(p, 'tindakan', { nama: 'x' })).toBe(p);
    expect(terapkanPeristiwa(pesanAsistenBaru('t'), 'tindakan', { id: 'z', risiko: 'aneh' }).blok[0].risiko).toBe('rendah');
  });

  test('`tindakan_status` mengubah keadaan + ringkas/pesan kartu miliknya; id lain = pesan yang sama', () => {
    let p = terapkanPeristiwa(pesanAsistenBaru('tmp'), 'tindakan', EV_TINDAKAN);
    p = terapkanPeristiwa(p, 'tindakan_status', { id: 'tnd-1', keadaan: 'disetujui' });
    expect(p.blok[0].keadaan).toBe('disetujui');
    p = terapkanPeristiwa(p, 'tindakan_status', { id: 'tnd-1', keadaan: 'dijalankan', ringkas: 'Target 3 toko terpasang.' });
    expect(p.blok[0]).toMatchObject({ keadaan: 'dijalankan', ringkas: 'Target 3 toko terpasang.', rencana: RENCANA });
    expect(terapkanPeristiwa(p, 'tindakan_status', { id: 'lain', keadaan: 'gagal' })).toBe(p);
  });

  test('kartu dihitung sebagai isi jawaban (jawaban yang berhenti di kartu = selesai, bukan "terputus")', () => {
    expect(JENIS_ISI.has('tindakan')).toBe(true);
  });

  test('`selesai` inti untuk jawaban yang berhenti di kartu (status menunggu_konfirmasi, tindakan_menunggu) → pesan selesai', () => {
    let p = terapkanPeristiwa(pesanAsistenBaru('tmp'), 'tindakan', { ...EV_TINDAKAN, bisa_dibalikkan: false });
    p = terapkanPeristiwa(p, 'selesai', { pesan_id: 'p9', pemakaian: {}, status: 'menunggu_konfirmasi', tindakan_menunggu: ['tnd-1'] });
    expect(p).toMatchObject({ id: 'p9', keadaan: 'selesai' });
    expect(p.blok[0].keadaan).toBe('menunggu');
  });

  test('riwayat: pesan `menunggu_konfirmasi` → selesai, kartu membawa keadaan sekarang dari server', () => {
    const r = dariRiwayat({ id: 'm2', peran: 'asisten', status: 'menunggu_konfirmasi', blok: [{ jenis: 'tindakan', id: 'tnd-1', keadaan: 'menunggu', rencana: RENCANA }] });
    expect(r.keadaan).toBe('selesai');
    expect(r.blok[0].keadaan).toBe('menunggu');
  });
});

describe('utas: status untuk kartu di jawaban sebelumnya', () => {
  const utas = () => [
    { kunci: 'u1', peran: 'user', teks: 'pasang target' },
    { kunci: 'a1', peran: 'asisten', blok: [{ jenis: 'teks', isi: 'x' }, { jenis: 'tindakan', id: 'tnd-1', keadaan: 'menunggu', rencana: RENCANA }] },
    { kunci: 'a2', peran: 'asisten', blok: [{ jenis: 'tindakan', id: 'tnd-2', keadaan: 'dijalankan', rencana: {} }] },
  ];

  test('terapkanStatusTindakan hanya mengganti pesan yang memuat kartunya', () => {
    const a = utas();
    const b = terapkanStatusTindakan(a, { id: 'tnd-1', keadaan: 'dibatalkan' });
    expect(b[1].blok[1].keadaan).toBe('dibatalkan');
    expect(b[0]).toBe(a[0]);
    expect(b[2]).toBe(a[2]);
    expect(terapkanStatusTindakan(a, { id: 'tidak-ada', keadaan: 'gagal' })).toBe(a);
  });

  test('kartu menunggu → kedaluwarsa saat ada pertanyaan baru; kartu lain tetap', () => {
    const a = utas();
    expect(kartuMenunggu(a).map((b) => b.id)).toEqual(['tnd-1']);
    const b = kedaluwarsakanMenunggu(a);
    expect(b[1].blok[1].keadaan).toBe('kedaluwarsa');
    expect(b[1].blok[1].pesan).toMatch(/pertanyaan baru/);
    expect(b[2]).toBe(a[2]);
    expect(kartuMenunggu(b)).toEqual([]);
  });

  test('ubahKartu memasang ubahan ke rencana kartu (catatan "diubah")', () => {
    const b = ubahKartu(utas(), 'tnd-1', (k) => ({ ...k, rencana: terapkanUbahanKeRencana(k.rencana, { 'toko.0.target': 140000000 }) }));
    expect(b[1].blok[1].rencana.diubah).toEqual([{ kunci: 'toko.0.target', label: 'Target Shopee Toko A', sebelum: 135000000, sesudah: 140000000, jenis: 'rupiah', pilihan: undefined }]);
  });
});

describe('keadaan → label & warna StatusBadge', () => {
  test.each([
    ['menunggu', 'Menunggu', 'warning'],
    ['disetujui', 'Disetujui', 'primary'],
    ['dijalankan', 'Dijalankan', 'success'],
    ['dibatalkan', 'Dibatalkan', 'muted'],
    ['gagal', 'Gagal', 'danger'],
    ['kedaluwarsa', 'Kedaluwarsa', 'muted'],
    ['dibalikkan', 'Dibalikkan', 'default'],
  ])('%s', (k, label, tone) => {
    expect(keadaanTindakan(k)).toEqual({ label, tone });
  });

  test('keadaan tak dikenal aman; semua keadaan Kontrak E terpetakan', () => {
    expect(keadaanTindakan('aneh').label).toBe('Tidak dikenal');
    expect(Object.keys(KEADAAN_TINDAKAN).sort()).toEqual(['dibalikkan', 'dibatalkan', 'dijalankan', 'disetujui', 'gagal', 'kedaluwarsa', 'menunggu']);
  });

  test('menunggu yang lewat batas waktu tampil kedaluwarsa', () => {
    const b = { keadaan: 'menunggu', kedaluwarsa_pada: '2026-11-09T03:00:00' };
    expect(keadaanEfektif(b, new Date('2026-11-09T02:59:00Z'))).toBe('menunggu');
    expect(keadaanEfektif(b, new Date('2026-11-09T03:00:01Z'))).toBe('kedaluwarsa');
    expect(keadaanEfektif({ keadaan: 'dijalankan', kedaluwarsa_pada: '2000-01-01T00:00:00Z' })).toBe('dijalankan');
    expect(keadaanEfektif({})).toBe('menunggu');
  });

  test('tautan hanya ke id modul yang sah', () => {
    expect(tautanAman({ label: 'Buka layar Target', menu: 'mkt-targets' })).toEqual({ label: 'Buka layar Target', menu: 'mkt-targets' });
    expect(tautanAman({ menu: 'javascript:alert(1)' })).toBeNull();
    expect(tautanAman({ menu: 'https://example.com' })).toBeNull();
    expect(tautanAman(null)).toBeNull();
  });
});

describe('isian "Ubah" → ubahan {kunci: nilai} (jalur bertitik)', () => {
  test('hanya kunci yang berubah, nilai bertipe, kunci jalur dipertahankan', () => {
    const r = susunUbahan(RENCANA.ubah, {
      'toko.0.target': '140000000', // MoneyInput mengirim angka polos
      'toko.1.target': '80000000',  // tidak berubah → tidak dikirim
      rasio: '1.25',
      catatan: '  Realistis plus ',
      mulai: '2026-11-02',
      skenario: '1',
    });
    expect(r.ok).toBe(true);
    expect(r.ubahan).toEqual({ 'toko.0.target': 140000000, rasio: 1.25, catatan: 'Realistis plus', mulai: '2026-11-02', skenario: 1 });
    expect(r.jumlah).toBe(5);
  });

  test('isian yang tidak dibuka tidak ikut; tanpa perubahan → ubahan kosong', () => {
    expect(susunUbahan(RENCANA.ubah, { 'toko.0.target': '135000000' })).toEqual({ ok: true, ubahan: {}, galat: {}, jumlah: 0 });
    expect(susunUbahan(RENCANA.ubah, {}).ubahan).toEqual({});
  });

  test('galat ramah: kosong, minus, bukan angka, tanggal salah, pilihan asing', () => {
    const r = susunUbahan(RENCANA.ubah, { 'toko.0.target': '', 'toko.1.target': '-5', rasio: 'abc', mulai: '2026-13-45', skenario: '9' });
    expect(r.ok).toBe(false);
    expect(r.galat).toEqual({
      'toko.0.target': 'Isian ini wajib diisi.',
      'toko.1.target': 'Angka tidak boleh minus.',
      rasio: 'Isi dengan angka.',
      mulai: 'Pilih tanggal yang benar.',
      skenario: 'Pilih salah satu pilihan.',
    });
  });

  test('angka gaya Indonesia juga terbaca; rupiah dibulatkan', () => {
    expect(bacaNilaiUbah({ jenis: 'rupiah' }, 'Rp 1.500.000')).toEqual({ ok: true, nilai: 1500000 });
    expect(bacaNilaiUbah({ jenis: 'rupiah' }, 1500000.6)).toEqual({ ok: true, nilai: 1500001 });
    expect(bacaNilaiUbah({ jenis: 'angka' }, '12,5')).toEqual({ ok: true, nilai: 12.5 });
    expect(bacaNilaiUbah({ jenis: 'aneh' }, 'x')).toEqual({ ok: true, nilai: 'x' }); // jenis tak dikenal = teks
  });

  test('terapkanUbahanKeRencana: nilai dipasang per kunci, rencana lama tidak diubah', () => {
    const b = terapkanUbahanKeRencana(RENCANA, { 'toko.0.target': 140000000, skenario: 1 });
    expect(b.ubah[0].nilai).toBe(140000000);
    expect(b.ubah[5].nilai).toBe(1);
    expect(b.ubah[1]).toBe(RENCANA.ubah[1]);
    expect(RENCANA.ubah[0].nilai).toBe(135000000);
    expect(b.diubah.map((d) => d.kunci)).toEqual(['toko.0.target', 'skenario']);
    expect(terapkanUbahanKeRencana(RENCANA, {})).toBe(RENCANA);
    expect(terapkanUbahanKeRencana(RENCANA, { 'tidak.ada': 1 })).toBe(RENCANA);
  });

  test('tampilan nilai isian', () => {
    expect(formatNilaiUbah({ jenis: 'rupiah' }, 140000000)).toBe('Rp 140.000.000');
    expect(formatNilaiUbah({ jenis: 'angka' }, 1250.5)).toBe('1.250,5');
    expect(formatNilaiUbah({ jenis: 'tanggal' }, '2026-11-09')).toBe('09 Nov 2026');
    expect(formatNilaiUbah(RENCANA.ubah[5], 1)).toBe('Konservatif');
    expect(formatNilaiUbah({ jenis: 'teks' }, '')).toBe('—');
  });
});

describe('halaman Tindakan AI', () => {
  test('query daftar dari penyaring', () => {
    expect(queryDaftar({ status: 'dijalankan', period: { preset: 'month', from: '2026-11-01', to: '2026-11-08' }, halaman: 2, semua: true }))
      .toBe('status=dijalankan&dari=2026-11-01&sampai=2026-11-08&halaman=2&semua=1');
    expect(queryDaftar({ status: '', period: { preset: 'all', from: '', to: '' }, halaman: 0, semua: false })).toBe('halaman=1');
  });

  test('jawaban daftar bentuk inti {items, total, halaman, per_halaman, semua} → tanpa jumlah per keadaan', () => {
    const rows = [{ id: 'a' }];
    expect(bacaDaftarTindakan({ items: rows, total: 30, halaman: 2, per_halaman: 25, semua: true }, 2))
      .toEqual({ baris: rows, total: 30, halaman: 2, perHalaman: 25, jumlah: null });
  });

  test('tindakan_status kedaluwarsa di aliran PESAN BARU (sesudah mulai) memperbarui kartu di pesan sebelumnya', () => {
    const utas = [
      { kunci: 'a1', peran: 'asisten', blok: [{ jenis: 'tindakan', id: 'tnd-1', keadaan: 'menunggu', rencana: {} }] },
      { kunci: 'u2', peran: 'user', teks: 'halo' },
      { kunci: 'a2', peran: 'asisten', blok: [] },
    ];
    const b = terapkanStatusTindakan(utas, { id: 'tnd-1', keadaan: 'kedaluwarsa', pesan: 'Tidak diputuskan; tindakan tidak dijalankan.' });
    expect(b[0].blok[0]).toMatchObject({ keadaan: 'kedaluwarsa', pesan: 'Tidak diputuskan; tindakan tidak dijalankan.' });
    expect(b[2]).toBe(utas[2]);
  });

  test('jawaban daftar: bentuk toleran + jumlah per keadaan opsional', () => {
    const rows = [{ id: 'a' }, { id: 'b' }];
    expect(bacaDaftarTindakan(rows)).toEqual({ baris: rows, total: 2, halaman: 1, perHalaman: 25, jumlah: null });
    const d = bacaDaftarTindakan({ items: rows, total: 60, halaman: 3, per_halaman: 20, per_keadaan: { menunggu: 1, dijalankan: '5' } }, 3);
    expect(d).toMatchObject({ baris: rows, total: 60, halaman: 3, perHalaman: 20 });
    expect(d.jumlah).toEqual({ menunggu: 1, dijalankan: 5, dibatalkan: 0, gagal: 0, kedaluwarsa: 0, dibalikkan: 0 });
    expect(bacaDaftarTindakan({ tindakan: rows }).baris).toBe(rows);
    expect(bacaDaftarTindakan(null).baris).toEqual([]);
  });

  test('"Semua pengguna" hanya untuk owner/superadmin', () => {
    expect(bolehSemuaPengguna('owner')).toBe(true);
    expect(bolehSemuaPengguna('SUPERADMIN')).toBe(true);
    expect(bolehSemuaPengguna('admin')).toBe(false);
    expect(bolehSemuaPengguna('manager')).toBe(false);
    expect(bolehSemuaPengguna(undefined)).toBe(false);
  });

  test('sebelum/sesudah dibaca staf: kunci teknis disembunyikan, tingkat jadi "Induk › anak"', () => {
    const { baris, lebih } = ratakanNilai({
      _id: 'x', id: 'y', toko_ids: ['a'],
      toko: [{ nama: 'Shopee Toko A', target_omzet: 135000000, store_id: 's1' }],
      periode: '2026-11',
      aktif: true,
      diubah_pada: '2026-11-08T03:15:00Z',
    });
    expect(lebih).toBe(0);
    expect(baris).toEqual([
      { label: 'Toko 1 › nama', nilai: 'Shopee Toko A' },
      { label: 'Toko 1 › target omzet', nilai: '135.000.000' },
      { label: 'Periode', nilai: '2026-11' },
      { label: 'Aktif', nilai: 'Ya' },
      { label: 'Diubah pada', nilai: '08 Nov 2026, 10.15' },
    ]);
    expect(labelKunci('target_omzet')).toBe('Target omzet');
    // bentuk inti: sebelum/sesudah = [{label, nilai}] (label sudah kalimat staf)
    expect(ratakanNilai([{ label: 'Shopee Toko A', nilai: 'Rp 120.000.000' }, { label: 'Aktif', nilai: true }, { label: 'Catatan', nilai: null }]).baris)
      .toEqual([{ label: 'Shopee Toko A', nilai: 'Rp 120.000.000' }, { label: 'Aktif', nilai: 'Ya' }, { label: 'Catatan', nilai: '—' }]);
    expect(ratakanNilai([{ label: 'Target', nilai: { bulan: '2026-11', omzet: 5 } }]).baris).toEqual([{ label: 'Target', nilai: 'Bulan: 2026-11 · Omzet: 5' }]);
    expect(ratakanNilai(null).baris).toEqual([]);
    expect(ratakanNilai({ a: 1, b: 2, c: 3 }, 2).lebih).toBe(1);
  });
});

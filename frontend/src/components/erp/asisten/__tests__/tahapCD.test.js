// Asisten AI Tahap C + D (layar2): logika murni adapter bentuk data + peristiwa SSE `ingatan`.
import {
  alamatTanpaSesi, bacaDaftarIngatan, bacaDaftarPengguna, bacaHasilJalankan, bacaIngatan, bacaPengaturanProaktif,
  bacaRingkasanProaktif, blokIngatan, bolehJalankanProaktif, hitungKategori, ingatanAktifDariStatus, jenisSesi,
  JADWAL_PROAKTIF, jumlahAktif, labelJenisSesi, labelKategori, labelPeran, normalJam, periksaIngatan, proaktifBerubah,
  sesiDariAlamat, sesiDariParams, susunPengaturanProaktif, tautanSesi, teksChipIngatan, teksHasilJalankan,
  teksWaktuJadwal, ubahanIngatan,
} from '../adapterTahapCD';
import { dariRiwayat, pesanAsistenBaru, terapkanPeristiwa } from '../peristiwaSse';

describe('ingatan: daftar & isian', () => {
  test('daftar toleran bentuk; aktif dulu lalu terbaru; nonaktif tetap ikut; sumber percakapan/manual', () => {
    const rows = [
      { id: 'i1', isi: 'Target minimal tumbuh 8%', kategori: 'preferensi', sumber: { sesi_id: 's1', pesan_id: 'p1' }, aktif: true, dibuat: '2026-11-01T01:00:00Z', diperbarui: '2026-11-01T01:00:00Z' },
      { id: 'i2', isi: 'Angka dalam juta', kategori: 'gaya', sumber: 'manual', aktif: true, diperbarui: '2026-11-07T01:00:00Z' },
      { id: 'i3', isi: 'Lama', kategori: 'fakta', sumber: 'manual', aktif: false },
      { isi: 'tanpa id' },
    ];
    for (const d of [rows, { items: rows }, { ingatan: rows, batas: 40 }, { data: rows }]) {
      const r = bacaDaftarIngatan(d);
      expect(r.items.map((x) => x.id)).toEqual(['i2', 'i1', 'i3']);
      expect(r.items[1].sumber).toEqual({ jenis: 'percakapan', sesi_id: 's1', pesan_id: 'p1' });
      expect(r.items[0].sumber).toEqual({ jenis: 'manual' });
      expect(r.items[2].aktif).toBe(false);
      expect(jumlahAktif(r.items)).toBe(2);
    }
    expect(bacaDaftarIngatan({ ingatan: rows, batas: 40 }).batas).toBe(40);
    expect(bacaDaftarIngatan(null)).toEqual({ items: [], batas: 50, maksIsi: 300, ingatanAktif: null });
    expect(hitungKategori(bacaDaftarIngatan(rows).items)).toEqual({ preferensi: 1, fakta: 1, gaya: 1 });
  });

  test('bentuk NYATA backend proaktif: {items, total, aktif, batas_aktif, maks_isi, kategori, ingatan_aktif}', () => {
    const d = {
      items: [{ id: 'ing-7f4e77339a1b', isi: 'Jawab singkat, angka utama dulu', kategori: 'gaya', kategori_label: 'Gaya jawaban',
        sumber: { sesi_id: 's-1', pesan_id: 'p-1' }, aktif: true, dibuat: '2026-11-08T01:00:00+00:00', diperbarui: '2026-11-08T01:00:00+00:00' }],
      total: 1, aktif: 1, batas_aktif: 45, maks_isi: 250, kategori: [{ nilai: 'gaya', label: 'Gaya jawaban' }], ingatan_aktif: false,
    };
    const r = bacaDaftarIngatan(d);
    expect(r.batas).toBe(45);
    expect(r.maksIsi).toBe(250);
    expect(r.ingatanAktif).toBe(false);
    expect(r.items[0].kategoriLabel).toBe('Gaya jawaban');
    expect(bacaIngatan({ id: 'x', kategori: 'baru', kategori_label: 'Kategori baru' }).kategoriLabel).toBe('Kategori baru');
    expect(bacaIngatan({ id: 'x', isi: 'a', kategori: 'gaya', sudah_ada: true }).sudahAda).toBe(true);
    expect(periksaIngatan({ isi: 'x'.repeat(260), kategori: 'gaya' }, 250).galat).toContain('250');
  });

  test('ubahanIngatan: PATCH hanya membawa yang berubah; tanpa perubahan → null', () => {
    const lama = { id: 'i1', isi: 'Juta', kategori: 'gaya', aktif: true };
    expect(ubahanIngatan(lama, { isi: 'Juta', kategori: 'gaya' })).toBeNull();
    expect(ubahanIngatan(lama, { isi: 'Miliar', kategori: 'gaya' })).toEqual({ isi: 'Miliar' });
    expect(ubahanIngatan(lama, { isi: 'Juta', kategori: 'fakta' })).toEqual({ kategori: 'fakta' });
    expect(ubahanIngatan(lama, { aktif: false })).toEqual({ aktif: false });
  });

  test('satu ingatan dari jawaban POST/PATCH (polos, {ingatan}, {data})', () => {
    const x = { id: 'i9', isi: ' Toko A fokus anak ', kategori: 'fakta', sumber: 'manual', created_at: '2026-11-08T01:00:00Z' };
    expect(bacaIngatan(x).isi).toBe('Toko A fokus anak');
    expect(bacaIngatan({ ingatan: x }).id).toBe('i9');
    expect(bacaIngatan({ ok: true, data: x }).diperbarui).toBe('2026-11-08T01:00:00Z');
    expect(bacaIngatan({ ok: true })).toBeNull();
    expect(bacaIngatan({ id: 'i1', sumber: { sesi_id: '../x' } }).sumber).toEqual({ jenis: 'manual' }); // id sesi aneh ditolak
  });

  test('periksaIngatan: 3–300 huruf, spasi dirapikan, kategori wajib', () => {
    expect(periksaIngatan({ isi: ' a ', kategori: 'fakta' }).ok).toBe(false);
    expect(periksaIngatan({ isi: 'x'.repeat(301), kategori: 'fakta' }).galat).toContain('301');
    expect(periksaIngatan({ isi: 'Angka   dalam\njuta', kategori: 'gaya' })).toEqual({ ok: true, nilai: { isi: 'Angka dalam juta', kategori: 'gaya' } });
    expect(periksaIngatan({ isi: 'Angka dalam juta', kategori: 'lain' }).galat).toBe('Pilih kategori ingatan.');
    expect(labelKategori('gaya')).toBe('Gaya jawaban');
    expect(labelKategori('aneh')).toBe('Lainnya');
  });
});

describe('chip ingatan (SSE `ingatan` & blok tersimpan)', () => {
  test('normalisasi aksi + kalimat chip', () => {
    expect(blokIngatan({ id: 'i1', isi: 'Target 8%', kategori: 'preferensi', aksi: 'disimpan' }))
      .toEqual({ jenis: 'ingatan', id: 'i1', isi: 'Target 8%', kategori: 'preferensi', aksi: 'disimpan' });
    expect(blokIngatan({ jenis: 'ingatan', id: 'i1', isi: 'Target 8%', aksi: 'dilupakan' }).aksi).toBe('dihapus');
    expect(blokIngatan({ ingatan: { id: 'i2', isi: 'Juta' }, aksi: 'diperbarui' }).aksi).toBe('diperbarui');
    expect(blokIngatan({ aksi: 'dihapus' })).toBeNull();
    expect(teksChipIngatan(blokIngatan({ id: 'i1', isi: 'Target 8%' }))).toBe('Diingat: Target 8%');
    expect(teksChipIngatan(blokIngatan({ id: 'i1', aksi: 'dihapus' }))).toBe('Dilupakan: satu ingatan');
    expect(teksChipIngatan({ aksi: 'diperbarui', isi: 'Juta' })).toBe('Diperbarui: Juta');
  });

  test('peristiwa `ingatan` menambah blok (bukan isi jawaban), urutan tetap; data rusak diabaikan', () => {
    let p = pesanAsistenBaru('a1');
    p = terapkanPeristiwa(p, 'teks', { delta: 'Baik, saya ingat.' });
    p = terapkanPeristiwa(p, 'ingatan', { id: 'i1', isi: 'Target 8%', kategori: 'preferensi', aksi: 'disimpan' });
    const sama = terapkanPeristiwa(p, 'ingatan', null);
    expect(sama).toBe(p);
    expect(p.blok.map((b) => b.jenis)).toEqual(['teks', 'ingatan']);
    expect(p.blok[1].isi).toBe('Target 8%');
    // dari riwayat: blok tersimpan apa adanya (dinormalkan saat dirender)
    const r = dariRiwayat({ id: 'm1', peran: 'asisten', status: 'selesai', blok: [{ jenis: 'ingatan', id: 'i1', isi: 'Target 8%', aksi: 'disimpan' }] });
    expect(r.blok[0].jenis).toBe('ingatan');
  });

  test('pesan pengguna buatan sistem (`otomatis`) ditandai; pesan biasa tidak', () => {
    expect(dariRiwayat({ id: 'u1', peran: 'user', otomatis: true, blok: [{ jenis: 'teks', isi: 'Susun briefing pagi' }] }).otomatis).toBe(true);
    expect(dariRiwayat({ id: 'u2', peran: 'user', blok: [{ jenis: 'teks', isi: 'Halo' }] }).otomatis).toBeUndefined();
  });
});

describe('riwayat: jenis percakapan', () => {
  test('briefing / laporan mingguan', () => {
    expect(jenisSesi({ jenis: 'briefing' })).toBe('briefing');
    expect(labelJenisSesi({ jenis: 'laporan_mingguan' })).toBe('Laporan mingguan');
    expect(labelJenisSesi({ jenis: 'chat' })).toBeNull(); // bentuk nyata: percakapan biasa = "chat"
    expect(labelJenisSesi({ jenis: 'constructor' })).toBeNull();
    expect(labelJenisSesi({})).toBeNull();
  });
});

describe('tautan langsung ke percakapan', () => {
  test('dari parameter navigasi (sesi; link_id/record_id hanya bila tujuan_modul asisten-ai) dan alamat', () => {
    expect(sesiDariParams({ sesi: 's-1' })).toBe('s-1');
    expect(sesiDariParams({ link_id: 'abc_9', record_id: 'zz', from_notification: 'n1', tujuan_modul: 'asisten-ai' })).toBe('abc_9');
    expect(sesiDariParams({ record_id: 'r1', tujuan_modul: 'asisten-ai' })).toBe('r1');
    // parameter notifikasi layar LAIN yang masih tersimpan di App (menu samping tidak menghapusnya) bukan id percakapan
    expect(sesiDariParams({ link_id: 'AP-1', record_id: 'AP-1', from_notification: 'n9', tujuan_modul: 'fin-ap' })).toBeNull();
    expect(sesiDariParams({ link_id: 'AP-1' })).toBeNull();
    expect(sesiDariParams({ sesi: '<script>' })).toBeNull();
    expect(sesiDariParams({ tab: 'x' })).toBeNull();
    expect(sesiDariParams(null)).toBeNull();
    expect(sesiDariAlamat('?portal=management&module=asisten-ai&sesi=s-9')).toBe('s-9');
    expect(sesiDariAlamat('?sesi=s-9')).toBe('s-9');
    expect(sesiDariAlamat('?module=fin-ap&sesi=s-9')).toBeNull();
    expect(sesiDariAlamat('?module=asisten-ai')).toBeNull();
    expect(alamatTanpaSesi('/', '?portal=management&module=asisten-ai&sesi=s-9', '#asisten-ai'))
      .toBe('/?portal=management&module=asisten-ai#asisten-ai');
    expect(alamatTanpaSesi('/', '?sesi=s-9', '')).toBe('/');
    expect(tautanSesi('s 1')).toBe('/?portal=management&module=asisten-ai&sesi=s%201');
  });
});

describe('pengaturan proaktif', () => {
  test('normalJam', () => {
    expect(normalJam('07:00')).toBe('07:00');
    expect(normalJam('7.30')).toBe('07:30');
    expect(normalJam('0730')).toBe('07:30');
    expect(normalJam('7')).toBe('07:00');
    expect(normalJam('24:00')).toBeNull();
    expect(normalJam('07:60')).toBeNull();
    expect(normalJam('jam 7')).toBeNull();
    expect(normalJam('')).toBeNull();
  });

  test('bawaan untuk server lama; nilai server dipakai', () => {
    expect(bacaPengaturanProaktif({})).toEqual({
      asisten_ingatan_aktif: true, asisten_briefing_aktif: true, asisten_peringatan_aktif: true,
      asisten_laporan_mingguan_aktif: true, asisten_briefing_jam: '07:00', asisten_peringatan_jam: '07:00',
      asisten_laporan_mingguan_jam: '07:30', asisten_briefing_penerima: [],
    });
    const d = bacaPengaturanProaktif({ asisten_briefing_aktif: false, asisten_briefing_jam: '6:15', asisten_briefing_penerima: ['u1', 'u1', { id: 'u2' }, ''] });
    expect(d.asisten_briefing_aktif).toBe(false);
    expect(d.asisten_briefing_jam).toBe('06:15');
    expect(d.asisten_briefing_penerima).toEqual(['u1', 'u2']);
  });

  test('susun: jam salah → galat per kunci; jam sah dinormalkan; 8 kunci', () => {
    const form = { ...bacaPengaturanProaktif({}), asisten_peringatan_jam: '25:00', asisten_laporan_mingguan_jam: '8.05' };
    const r = susunPengaturanProaktif(form);
    expect(r.ok).toBe(false);
    expect(Object.keys(r.galat)).toEqual(['asisten_peringatan_jam']);
    expect(r.pesan).toContain('JJ:MM');
    const ok = susunPengaturanProaktif({ ...form, asisten_peringatan_jam: '06:00', asisten_briefing_penerima: ['u2'] });
    expect(ok.ok).toBe(true);
    expect(Object.keys(ok.nilai).sort()).toEqual([
      'asisten_briefing_aktif', 'asisten_briefing_jam', 'asisten_briefing_penerima', 'asisten_ingatan_aktif',
      'asisten_laporan_mingguan_aktif', 'asisten_laporan_mingguan_jam', 'asisten_peringatan_aktif', 'asisten_peringatan_jam']);
    expect(ok.nilai.asisten_laporan_mingguan_jam).toBe('08:05');
    expect(ok.nilai.asisten_briefing_penerima).toEqual(['u2']);
  });

  test('perubahan belum disimpan + hak "Jalankan sekarang"', () => {
    const server = { asisten_briefing_jam: '07:00', asisten_briefing_penerima: ['a', 'b'] };
    const form = bacaPengaturanProaktif(server);
    expect(proaktifBerubah(form, server)).toBe(false);
    expect(proaktifBerubah({ ...form, asisten_briefing_penerima: ['b', 'a'] }, server)).toBe(false);
    expect(proaktifBerubah({ ...form, asisten_briefing_jam: '7.00' }, server)).toBe(false);
    expect(proaktifBerubah({ ...form, asisten_briefing_aktif: false }, server)).toBe(true);
    expect(bolehJalankanProaktif('owner')).toBe(true);
    expect(bolehJalankanProaktif('superadmin')).toBe(true);
    expect(bolehJalankanProaktif('admin')).toBe(false);
  });

  test('hasil jalankan-sekarang: sesi milik sendiri, peringatan, dilewati', () => {
    const [briefing, peringatan, laporan] = JADWAL_PROAKTIF;
    const h1 = bacaHasilJalankan({ hasil: [{ user_id: 'u9', sesi_id: 's-lain' }, { user_id: 'u1', sesi_id: 's-saya' }] }, 'u1');
    expect(h1.sesiId).toBe('s-saya');
    expect(teksHasilJalankan(briefing, h1)).toBe('Briefing pagi dibuat untuk 2 penerima.');
    expect(bacaHasilJalankan({ sesi: { id: 's-2' } }).sesiId).toBe('s-2');
    expect(teksHasilJalankan(laporan, bacaHasilJalankan({ sesi_id: 's-3' }))).toBe('Laporan mingguan sudah dibuat.');
    expect(teksHasilJalankan(laporan, bacaHasilJalankan({ ok: true }))).toContain('sedang disusun');
    expect(teksHasilJalankan(peringatan, bacaHasilJalankan({ terkirim: 3 }))).toBe('Peringatan harian diperiksa: 3 notifikasi dikirim.');
    expect(teksHasilJalankan(peringatan, bacaHasilJalankan({ jumlah_notifikasi: 0 }))).toContain('tidak ada');
    const lewat = bacaHasilJalankan({ dilewati: true, alasan: 'anggaran_habis' });
    expect(teksHasilJalankan(briefing, lewat)).toBe('Briefing pagi tidak dijalankan: anggaran AI sudah habis.');
    expect(teksHasilJalankan(briefing, bacaHasilJalankan({ dilewati: true, pesan: 'Briefing hari ini sudah ada.', sesi_id: 's-1' }))).toBe('Briefing hari ini sudah ada.');
  });

  test('bentuk NYATA jalankan-sekarang: 202 berjalan (briefing/laporan) dan 200 peringatan berkondisi', () => {
    const [briefing, peringatan, laporan] = JADWAL_PROAKTIF;
    const b202 = bacaHasilJalankan({ jenis: 'briefing', status: 'berjalan', sesi_id: 'sesi-9', tautan: '?portal=management&module=asisten-ai&sesi=sesi-9',
      pesan: 'Briefing pagi sedang disusun. Notifikasi dikirim bila sudah siap.' }, 'u1');
    expect(b202.sesiId).toBe('sesi-9');
    expect(b202.berjalan).toBe(true);
    expect(teksHasilJalankan(briefing, b202)).toBe('Briefing pagi sedang disusun. Notifikasi dikirim bila sudah siap.');
    expect(teksHasilJalankan(laporan, bacaHasilJalankan({ status: 'berjalan', sesi_id: 's' }))).toBe('Laporan mingguan sedang disusun; notifikasi dikirim setelah selesai.');
    const p = bacaHasilJalankan({ jenis: 'peringatan', tanggal: '2026-11-08', pemicu: 'manual',
      pemeriksa: { omzet: 'ok', stok: 'gagal', po_piutang: 'ok' },
      kondisi: [{ kondisi: 'omzet', penerima: 'owner', jumlah: 2, dikirim: true },
        { kondisi: 'po', penerima: 'pic', jumlah: 1, dikirim: false, alasan: 'sudah_dikirim_hari_ini' }],
      notifikasi: 1 });
    expect(teksHasilJalankan(peringatan, p)).toBe('Peringatan harian diperiksa: 1 notifikasi dikirim. 1 kondisi sudah dikabarkan hari ini. Pemeriksaan stok gagal.');
    const nol = bacaHasilJalankan({ kondisi: [{ kondisi: 'stok', dikirim: false, alasan: 'sudah_dikirim_hari_ini' }], notifikasi: 0 });
    expect(teksHasilJalankan(peringatan, nol)).toBe('Peringatan harian diperiksa: tidak ada notifikasi baru. 1 kondisi sudah dikabarkan hari ini.');
    expect(teksHasilJalankan(peringatan, bacaHasilJalankan({ kondisi: [], notifikasi: 0 }))).toBe('Peringatan harian diperiksa: tidak ada yang perlu diperingatkan.');
  });

  test('GET /proaktif: jadwal berikutnya + riwayat tanpa kode program', () => {
    const r = bacaRingkasanProaktif({
      jadwal: {
        briefing: { aktif: true, jam: '07:00', berikutnya: '2026-11-09T07:00:00+07:00', label: 'Briefing pagi' },
        peringatan: { aktif: false, jam: '07:00', berikutnya: null, label: 'Peringatan harian' },
      },
      penerima: [], ai_aktif: false,
      riwayat: [
        { id: 'r1', jenis: 'peringatan', tanggal: '2026-11-08', kondisi: 'stok', pemicu: 'jadwal', status: 'terkirim', jumlah: 4, dibuat: '2026-11-08T00:00:05+00:00' },
        { id: 'r2', jenis: 'briefing', tanggal: '2026-11-08', user_id: 'u1', pemicu: 'manual', status: 'dilewati', alasan: 'tanpa_akses', sesi_id: 's-1', dibuat: '2026-11-08T00:01:00+00:00' },
        { id: 'r3', jenis: 'laporan_mingguan', pemicu: 'jadwal', status: 'gagal', alasan: 'kode_baru_x' },
      ],
    });
    expect(r.aiAktif).toBe(false);
    expect(r.jadwal.briefing).toEqual({ aktif: true, jam: '07:00', berikutnya: '2026-11-09T07:00:00+07:00' });
    expect(r.jadwal.peringatan.aktif).toBe(false);
    expect(r.jadwal.laporan_mingguan).toBeNull();
    expect(r.riwayat[0]).toMatchObject({ judul: 'Peringatan harian', rincian: 'Stok di bawah titik pesan ulang', jumlah: 4, statusLabel: 'Terkirim', tone: 'success', pemicu: 'Terjadwal' });
    expect(r.riwayat[1]).toMatchObject({ judul: 'Briefing pagi', userId: 'u1', sesiId: 's-1', statusLabel: 'Dilewati', alasan: 'penerima tidak punya akses Asisten AI', pemicu: 'Manual' });
    expect(r.riwayat[2].alasan).toBe('alasan lain');
    expect(teksWaktuJadwal('2026-11-09T07:00:00+07:00')).toMatch(/Senin, 09 Nov 2026 07[.:]00/);
    expect(teksWaktuJadwal(null)).toBe('');
  });

  test('penerima paling banyak 20', () => {
    const banyak = Array.from({ length: 21 }, (_, i) => `u${i}`);
    const r = susunPengaturanProaktif({ ...bacaPengaturanProaktif({}), asisten_briefing_penerima: banyak });
    expect(r.ok).toBe(false);
    expect(r.galat.asisten_briefing_penerima).toBe('Penerima briefing paling banyak 20 orang.');
  });

  test('pengguna & status', () => {
    expect(bacaDaftarPengguna([{ id: 2, name: 'Uji B', role: 'admin_produksi' }, { id: 'u1', name: 'Uji A', role: 'owner' }, { name: 'x' }]))
      .toEqual([{ id: 'u1', nama: 'Uji A', peran: 'Owner' }, { id: '2', nama: 'Uji B', peran: 'Admin produksi' }]);
    expect(bacaDaftarPengguna({ users: [{ id: 'u', email: 'a@b' }] })[0].nama).toBe('a@b');
    expect(labelPeran('')).toBe('');
    expect(ingatanAktifDariStatus({ siap: true })).toBe(true);
    expect(ingatanAktifDariStatus({ ingatan_aktif: false })).toBe(false);
  });
});

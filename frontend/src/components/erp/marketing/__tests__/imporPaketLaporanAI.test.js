import { hitungStatus, kalimatHasil, labelPeriode, statusBerkas, tahapBerikut } from '../imporPaketAturan';
import { kalimatAnomali, pilihanBulan, pilihanPekan } from '../laporanAIAturan';

describe('Impor banyak berkas — aturan tampilan', () => {
  test('tahap berikut mengikuti status paket & berkas', () => {
    expect(tahapBerikut(null)).toBe('unggah');
    expect(tahapBerikut({ status: 'pratinjau', berkas: [{ status: 'perlu_isian' }] })).toBe('lengkapi');
    expect(tahapBerikut({ status: 'pratinjau', berkas: [{ status: 'siap_diperiksa' }] })).toBe('periksa');
    expect(tahapBerikut({ status: 'diperiksa', berkas: [{ status: 'diperiksa' }, { status: 'perlu_pemetaan' }] })).toBe('simpan');
    expect(tahapBerikut({ status: 'menyimpan', berkas: [] })).toBe('menunggu');
    expect(tahapBerikut({ status: 'selesai', berkas: [] })).toBe('selesai');
  });

  test('label status Indonesia tanpa kode program', () => {
    for (const s of ['perlu_isian', 'diperiksa', 'keuangan', 'gagal']) {
      expect(statusBerkas(s).label).not.toMatch(/_/);
    }
    expect(statusBerkas('entah').label).toBe('Belum diketahui');
    expect(hitungStatus([{ status: 'diperiksa' }, { status: 'diperiksa' }, { status: 'gagal' }])).toEqual({ diperiksa: 2, gagal: 1 });
  });

  test('periode & kalimat hasil', () => {
    expect(labelPeriode('2026-08-01', '2026-08-31')).toBe('1–31 Agu 2026');
    expect(labelPeriode('2026-07-28', '2026-08-03')).toBe('28 Jul 2026 – 3 Agu 2026');
    expect(labelPeriode(null, '2026-08-01')).toBe('—');
    expect(kalimatHasil({ inserted: 3, updated: 2, rejected: 1 })).toBe('3 baris baru · 2 diperbarui · 1 ditolak');
    expect(kalimatHasil({})).toBe('Tidak ada baris yang berubah');
  });
});

describe('Laporan AI — pilihan periode', () => {
  test('pekan lalu Senin–Minggu dan bulan lalu penuh', () => {
    const hari = new Date(2026, 10, 9); // Senin 9 Nov 2026
    const p = pilihanPekan(hari, 2);
    expect(p[0]).toMatchObject({ dari: '2026-11-02', sampai: '2026-11-08' });
    expect(p[1]).toMatchObject({ dari: '2026-10-26', sampai: '2026-11-01' });
    const b = pilihanBulan(hari, 2);
    expect(b[0]).toEqual({ dari: '2026-10-01', sampai: '2026-10-31', label: 'Oktober 2026' });
    expect(b[1].dari).toBe('2026-09-01');
  });

  test('kalimat anomali memakai angka dari server', () => {
    const rp = (v) => `Rp${v}`;
    expect(kalimatAnomali({ jenis: 'batal_melonjak', persen_batal: 30, persen_batal_sebelumnya: 8 }, rp))
      .toBe('Pesanan batal 30% (sebelumnya 8%).');
    expect(kalimatAnomali({ jenis: 'kampanye_rugi', kampanye: 'K1', belanja: 9, roas: 0.4 }, rp)).toContain('Rp9');
    expect(kalimatAnomali({ jenis: 'lain' }, rp)).toBe('');
  });
});

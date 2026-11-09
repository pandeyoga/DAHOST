/**
 * Aturan tampilan "Impor banyak berkas" (tanpa React) — dipakai layar & uji.
 * Status berkas dari server (`core/impor_paket.STATUS_LABEL`) → label & warna token.
 */
export const STATUS_BERKAS = {
  perlu_isian: { label: 'Perlu dilengkapi', tone: 'warning' },
  siap_diperiksa: { label: 'Siap diperiksa', tone: 'info' },
  diperiksa: { label: 'Siap disimpan', tone: 'success' },
  perlu_pemetaan: { label: 'Pemetaan belum lengkap', tone: 'warning' },
  ditolak: { label: 'Ditolak', tone: 'danger' },
  disimpan: { label: 'Tersimpan', tone: 'success' },
  gagal: { label: 'Gagal disimpan', tone: 'danger' },
  dilewati: { label: 'Tidak diimpor', tone: 'muted' },
  dibatalkan: { label: 'Dibatalkan', tone: 'muted' },
  keuangan: { label: 'Diproses di Keuangan', tone: 'info' },
};

export const STATUS_PAKET = {
  pratinjau: 'Belum diperiksa',
  diperiksa: 'Siap disimpan',
  menyimpan: 'Sedang disimpan',
  selesai: 'Tersimpan',
  sebagian: 'Sebagian tersimpan',
  gagal: 'Gagal disimpan',
  dibatalkan: 'Dibatalkan',
};

export function statusBerkas(s) {
  return STATUS_BERKAS[s] || { label: 'Belum diketahui', tone: 'muted' };
}

/** Hitungan per status untuk kartu ringkasan (hanya yang bukan nol). */
export function hitungStatus(berkas) {
  const n = {};
  (berkas || []).forEach((b) => { n[b.status] = (n[b.status] || 0) + 1; });
  return n;
}

/** Tombol utama tahap berikutnya: unggah → periksa → simpan → (selesai). */
export function tahapBerikut(paket) {
  if (!paket) return 'unggah';
  const st = paket.status;
  if (st === 'menyimpan') return 'menunggu';
  if (['selesai', 'sebagian', 'gagal', 'dibatalkan'].includes(st)) return 'selesai';
  const b = paket.berkas || [];
  if (b.some((x) => x.status === 'diperiksa')) return 'simpan';
  if (b.some((x) => ['siap_diperiksa', 'perlu_pemetaan', 'ditolak'].includes(x.status))) return 'periksa';
  return 'lengkapi';
}

/** "1–31 Agu 2026" dari dua tanggal ISO (tanpa hari bila kosong). */
const BLN = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
export function labelPeriode(a, b) {
  if (!a || !b) return '—';
  const [ya, ma, da] = a.split('-').map(Number);
  const [yb, mb, db] = b.split('-').map(Number);
  if (ya === yb && ma === mb) return `${da}–${db} ${BLN[ma - 1]} ${ya}`;
  return `${da} ${BLN[ma - 1]} ${ya} – ${db} ${BLN[mb - 1]} ${yb}`;
}

/** Kalimat hasil satu berkas sesudah disimpan. */
export function kalimatHasil(h) {
  if (!h) return '';
  const bagian = [];
  if (h.inserted) bagian.push(`${h.inserted} baris baru`);
  if (h.updated) bagian.push(`${h.updated} diperbarui`);
  if (h.skipped_duplicates) bagian.push(`${h.skipped_duplicates} duplikat dilewati`);
  if (h.rejected) bagian.push(`${h.rejected} ditolak`);
  return bagian.length ? bagian.join(' · ') : 'Tidak ada baris yang berubah';
}

/**
 * Periode laporan yang diisi staf untuk jenis tanpa tanggal di berkas (GMV Max).
 * → '' bila sah, atau kalimat galat (aturan sama dengan `/upload`: wajib, mulai ≤ selesai, satu bulan).
 */
export function cekPeriodeLaporan(mulai, selesai) {
  if (!mulai || !selesai) return 'Isi Periode mulai dan Periode selesai sesuai rentang saat mengekspor laporan.';
  if (mulai > selesai) return 'Tanggal mulai periode tidak boleh sesudah tanggal selesai.';
  if (mulai.slice(0, 7) !== selesai.slice(0, 7)) {
    return 'Periode tidak boleh menyeberang bulan — ekspor ulang laporannya per bulan, lalu unggah masing-masing.';
  }
  return '';
}

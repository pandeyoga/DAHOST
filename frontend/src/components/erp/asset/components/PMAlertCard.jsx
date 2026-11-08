/**
 * Peringatan pemeliharaan — label jenis & kalimat keterangan berbahasa Indonesia.
 *
 * Standar UI/UX v2 (8 Nov 2026): peringatan tampil sebagai BARIS TABEL (dulu kartu berwarna per peringatan,
 * berisi emoji dan istilah Inggris "Overdue/Upcoming/Stale/Snooze"). Kalimat keterangan disusun di sini dari
 * angka yang sudah dikirim server (hari lewat, jadwal, jumlah perbaikan, perkiraan) — teks rekomendasi server
 * masih bercampur istilah Inggris ("maintenance", "replacement", "root cause").
 */
import { fmtCurrency, fmtDate } from '../utils';

export const JENIS_PERINGATAN = {
  overdue:        { label: 'Lewat jadwal',       tone: 'danger' },
  high_frequency: { label: 'Perbaikan berulang', tone: 'warning' },
  upcoming:       { label: 'Segera jatuh tempo', tone: 'warning' },
  predicted:      { label: 'Perkiraan jadwal',   tone: 'info' },
  stale:          { label: 'Lama tidak dirawat', tone: 'muted' },
};

/** Urutan tampil (sama dengan urutan bagian di layar lama). */
export const URUTAN_JENIS = ['overdue', 'high_frequency', 'upcoming', 'predicted', 'stale'];

const angkaID = (v) => Number(v || 0).toLocaleString('id-ID', { maximumFractionDigits: 1 });

/** Kalimat keterangan satu peringatan, dari angka yang dikirim server. */
export function keteranganPeringatan(a) {
  switch (a.kind) {
    case 'overdue':
      return `Lewat ${a.days_overdue} hari dari jadwal ${fmtDate(a.scheduled_date)}. Lakukan pemeliharaan segera.`;
    case 'upcoming':
      return `Jadwal ${fmtDate(a.scheduled_date)} (${a.days_until} hari lagi). Siapkan pemeliharaan.`;
    case 'stale':
      return `${angkaID(a.months_since_maintenance)} bulan tanpa pemeliharaan. Jadwalkan pemeriksaan rutin.`;
    case 'high_frequency':
      return `${a.recent_count} kali pemeliharaan dalam ${a.window_days} hari`
        + `${a.recent_total_cost ? ` (biaya ${fmtCurrency(a.recent_total_cost)})` : ''}. `
        + 'Pertimbangkan penggantian atau cari penyebabnya.';
    case 'predicted': {
      const tiap = a.avg_interval_days ? `, rata-rata tiap ${Math.round(a.avg_interval_days)} hari` : '';
      const kapan = a.days_offset < 0
        ? `seharusnya ${fmtDate(a.predicted_next_due_date)} (sudah lewat)`
        : `diperkirakan ${fmtDate(a.predicted_next_due_date)} (${a.days_offset} hari lagi)`;
      return `Dari ${a.total_maintenance_count || 0} kali pemeliharaan${tiap}, pemeliharaan berikutnya ${kapan}.`;
    }
    default:
      return a.recommended_action || '—';
  }
}

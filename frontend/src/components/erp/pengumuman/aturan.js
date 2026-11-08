/**
 * Aturan tampilan Papan Pengumuman (murni, tanpa React) — dipakai halaman & tes.
 * Waktu dari server dibaca sebagai UTC bila tanpa zona (data lama); tanggal ditampilkan dalam WIB.
 */
import { toWIBDate } from '@/lib/waktu';
import { formatTanggalID } from '@/components/ui/date-picker';
import { NAMA_PORTAL } from '../portalAccess';

export const NAMA = Object.fromEntries(NAMA_PORTAL.map((p) => [p.id, p.nama]));

// Waktu dari server: bila tanpa zona (data lama), anggap UTC.
export const instan = (s) => (s ? new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : `${s}Z`) : null);
export const ymd = (s) => (s ? toWIBDate(instan(s)) : '');

/** Keadaan pengumuman menurut waktu WIB sekarang. */
export function keadaanPengumuman(a, sekarang = Date.now()) {
  if (!a.is_active) return 'nonaktif';
  const mulai = instan(a.start_date);
  const akhir = instan(a.end_date);
  if (mulai && mulai.getTime() > sekarang) return 'terjadwal';
  if (akhir && akhir.getTime() < sekarang) return 'berakhir';
  return 'tampil';
}
export const KEADAAN = {
  tampil: { label: 'Sedang tampil', tone: 'success' },
  terjadwal: { label: 'Terjadwal', tone: 'info' },
  berakhir: { label: 'Berakhir', tone: 'muted' },
  nonaktif: { label: 'Nonaktif', tone: 'muted' },
};

export function labelPeriode(a) {
  const m = ymd(a.start_date);
  const b = ymd(a.end_date);
  if (m && b) return m === b ? formatTanggalID(m) : `${formatTanggalID(m)} – ${formatTanggalID(b)}`;
  if (m) return `Mulai ${formatTanggalID(m)}`;
  if (b) return `Sampai ${formatTanggalID(b)}`;
  return 'Tanpa batas waktu';
}
export function labelTujuan(target, maks = 2) {
  const t = target && target.length ? target : ['all'];
  if (t.includes('all')) return 'Semua portal';
  const nama = t.map((p) => NAMA[p] || p);
  return nama.length > maks ? `${nama.slice(0, maks).join(', ')} +${nama.length - maks}` : nama.join(', ');
}


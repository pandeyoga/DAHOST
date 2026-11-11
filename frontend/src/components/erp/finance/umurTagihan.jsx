/**
 * Kolom "Umur" untuk Keuangan › Hutang dan Piutang (11 Nov 2026, owner).
 *
 *  • Barang yang masih di CMT (jadwal hutang CMT, perkiraan PO DA, piutang maklon terjadwal): hari sejak kirim ke CMT
 *    dengan warna seperti Excel owner — hijau 0–7 hari, kuning 8–14 hari, merah lebih dari 14 hari. Angka hari dan
 *    kelompoknya dihitung server (`core.umur_kirim`) supaya Portal Maklon dan Keuangan memakai aturan yang sama.
 *  • Tagihan / faktur yang sudah punya jatuh tempo: "terlambat N hari" / "jatuh tempo N hari lagi".
 */
import { StatusBadge } from '../moduleAtoms';
import { todayWIB } from '@/lib/waktu';

export const KELOMPOK_KIRIM = {
  hijau: { label: '0–7 hari', tone: 'success' },
  kuning: { label: '8–14 hari', tone: 'warning' },
  merah: { label: 'lebih dari 14 hari', tone: 'danger' },
};

const hariKe = (iso) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
  return m ? Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])) / 86400000 : null;
};

/** Hari lewat jatuh tempo (positif = terlambat, 0 = hari ini, negatif = belum jatuh tempo); null bila tanpa tanggal. */
export function hariTerlambat(jatuhTempo, hariIni = todayWIB()) {
  const a = hariKe(jatuhTempo);
  const b = hariKe(hariIni);
  return a === null || b === null ? null : Math.round(b - a);
}

export function teksJatuhTempo(hari) {
  if (hari === null || hari === undefined) return '';
  if (hari > 0) return `terlambat ${hari} hari`;
  if (hari === 0) return 'jatuh tempo hari ini';
  return `jatuh tempo ${-hari} hari lagi`;
}

/** Umur sejak kirim ke CMT — pil berwarna seperti Excel owner. */
export function UmurKirim({ hari, kelompok, testId }) {
  if (hari === null || hari === undefined || !kelompok) return <span className="text-muted-foreground">—</span>;
  const k = KELOMPOK_KIRIM[kelompok] || KELOMPOK_KIRIM.merah;
  return (
    <span className="inline-flex flex-col items-start gap-0.5" title={`Sejak kirim ke CMT · kelompok ${k.label}`}>
      <StatusBadge status={kelompok} label={`${Math.max(hari, 0)} hari`} tone={k.tone} testId={testId} />
      <span className="text-xs text-muted-foreground">sejak kirim ke CMT</span>
    </span>
  );
}

/** Umur tagihan dari jatuh tempo. */
export function UmurJatuhTempo({ hari, testId }) {
  if (hari === null || hari === undefined) return <span className="text-muted-foreground">—</span>;
  return (
    <span data-testid={testId}
      className={`whitespace-nowrap ${hari > 0 ? 'font-medium text-[hsl(var(--danger-text))]' : 'text-muted-foreground'}`}>
      {teksJatuhTempo(hari)}
    </span>
  );
}

/** Jumlah per kelompok umur kirim (hijau/kuning/merah) dari baris yang punya `umurKirim`. */
export function jumlahPerKelompokKirim(rows, nilai) {
  const out = { hijau: 0, kuning: 0, merah: 0 };
  rows.forEach((r) => {
    const k = r.umurKirim?.kelompok;
    if (k && out[k] !== undefined) out[k] += Number(nilai(r) || 0);
  });
  return out;
}

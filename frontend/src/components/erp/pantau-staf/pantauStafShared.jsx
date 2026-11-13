/**
 * Bersama untuk layar Pemantauan staf & Aturan kewajiban (Portal Manajemen, keputusan owner 10 Nov 2026;
 * alur kerja harian 14 Nov 2026).
 * Angka dari /api/pantau-staf/* (`core/pantau_staf`, satu sumber untuk kartu, tabel, rincian, Asisten AI).
 */
import { useCallback, useEffect, useState } from 'react';
import { StatusBadge } from '../moduleAtoms';
import { apiGet } from '../../../lib/api';
import { formatDateID, formatDateTimeID } from '@/lib/format';
import { labelKodePeran } from '../akses/labelPeran';

export const STATUS = {
  menunggu: { label: 'Menunggu', tone: 'info' },
  terlambat: { label: 'Terlambat', tone: 'danger' },
  selesai: { label: 'Selesai', tone: 'success' },
  terlewat: { label: 'Terlewat', tone: 'danger' },
  batal: { label: 'Batal', tone: 'muted' },
  dimaafkan: { label: 'Dimaafkan', tone: 'muted' },
};

export function StatusKewajiban({ k }) {
  if (!k) return null;
  if (k.status === 'selesai') {
    if (k.oleh_orang_lain) return <StatusBadge status="lain" label="Selesai oleh orang lain" tone="warning" />;
    return <StatusBadge status="selesai" label={k.tepat ? 'Tepat waktu' : 'Selesai terlambat'} tone={k.tepat ? 'success' : 'warning'} />;
  }
  const m = STATUS[k.status] || { label: k.status, tone: 'muted' };
  return <StatusBadge status={k.status} label={m.label} tone={m.tone} />;
}

const NADA_NILAI = { A: 'success', B: 'success', C: 'warning', D: 'warning', E: 'danger' };
export function NilaiBadge({ nilai, ujiCoba }) {
  if (!nilai?.huruf) return <span className="text-muted-foreground">—</span>;
  return (
    <StatusBadge status={nilai.huruf} label={`${nilai.huruf} · ${nilai.label}${ujiCoba ? ' (uji coba)' : ''}`}
      tone={NADA_NILAI[nilai.huruf] || 'muted'} />
  );
}

export const waktu = (v) => formatDateTimeID(v, { fallback: '—' });

/** Jam WIB "09.34" dari waktu tersimpan. */
export const jamWIB = (v) => (v
  ? new Date(v).toLocaleTimeString('id-ID', { timeZone: 'Asia/Jakarta', hour: '2-digit', minute: '2-digit' })
  : '—');

/** Tanggal hari ini WIB "YYYY-MM-DD" (nilai DatePicker). */
export const hariIniWIB = () => new Date(Date.now() + 7 * 3600 * 1000).toISOString().slice(0, 10);

/** Angka gaya Indonesia: 1.234 / 1.234,5. */
export const angka = (v) => Number(v || 0).toLocaleString('id-ID', { maximumFractionDigits: 1 });

/** Keadaan satu langkah alur kerja → label & nada (warna) yang sama di semua tab. */
export const KEADAAN_LANGKAH = {
  macet: { label: 'Macet', tone: 'danger' },
  menunggu: { label: 'Ada yang menunggu', tone: 'warning' },
  dikerjakan: { label: 'Dikerjakan', tone: 'success' },
  kosong: { label: 'Tidak ada kegiatan', tone: 'muted' },
};
export const KEADAAN_ALUR = {
  macet: { label: 'Macet', tone: 'danger' },
  menunggu: { label: 'Ada yang menunggu', tone: 'warning' },
  jalan: { label: 'Berjalan', tone: 'success' },
  kosong: { label: 'Tidak ada kegiatan', tone: 'muted' },
};

/** Nama peran untuk layar: peran buatan owner ("HR Generalist") apa adanya, kode ("pic_toko") diterjemahkan. */
export const namaPeran = (r) => (!r ? '—' : /[A-Z\s&/]/.test(r) ? r : labelKodePeran(r));

/** Label dokumen/periode: kewajiban harian memakai tanggal Indonesia, bukan "2026-11-09". */
const tglPendek = (p) => formatDateID(`${p}T00:00:00+07:00`, { day: 'numeric', month: 'short' });

export function labelDokumen(k) {
  if (!k) return '—';
  if (k.gabungan > 1) {
    const r = `${k.gabungan} hari (${tglPendek(k.periode_awal)} – ${tglPendek(k.periode_akhir)})`;
    return k.nomor && k.nomor !== k.periode ? `${k.nomor} · ${r}` : r;
  }
  if (k.periode) {
    const tgl = formatDateID(`${k.periode}T00:00:00+07:00`);
    return k.nomor && k.nomor !== k.periode ? `${k.nomor} · ${tgl}` : tgl;
  }
  return k.nomor || '—';
}
export const persen = (v) => (v === null || v === undefined ? '—' : `${Number(v).toLocaleString('id-ID', { maximumFractionDigits: 1 })}%`);

/** "2 hari kerja" / "5 jam" — lama terlambat untuk layar. */
export function lamaTerlambat(k) {
  if (!k || k.status !== 'terlambat') return '—';
  if (k.terlambat_hari_kerja > 0) return `${k.terlambat_hari_kerja} hari kerja`;
  const j = Number(k.terlambat_jam || 0);
  return j >= 1 ? `${Math.round(j)} jam` : 'kurang dari 1 jam';
}

/** Nama penanggung jawab kewajiban (pemegang aturan) untuk layar. */
export function pemegangLabel(k) {
  if (!k?.pemegang?.length) return null;
  return k.pemegang.join(', ') + (k.dialihkan_ke_cadangan ? ' (cadangan)' : '');
}

export function useApi(path) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const reload = useCallback(async () => {
    if (!path) return;
    setLoading(true); setError('');
    try { setData(await apiGet(path)); }
    catch (e) { setError(e.message || 'Gagal memuat data.'); }
    finally { setLoading(false); }
  }, [path]);
  useEffect(() => { reload(); }, [reload]);
  return { data, loading, error, reload };
}

export const qs = (obj) => {
  const p = Object.entries(obj).filter(([, v]) => v !== undefined && v !== null && v !== '');
  return p.length ? `?${p.map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&')}` : '';
};

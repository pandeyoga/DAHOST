/**
 * Bantuan bersama layar Shift (Tahap C audit HR, 9 Nov 2026): panggilan API, titik warna shift, label asal shift,
 * dan tanggal. Dipakai Roster, Pola rotasi, Permintaan shift (Portal SDM) dan Jadwal Shift (Portal Saya).
 */
import axios from 'axios';
import { addDaysISO } from '@/lib/waktu';

const API = process.env.REACT_APP_BACKEND_URL;

export const shiftApi = (method, path, { data, params } = {}) => axios({
  method, url: `${API}${path}`, data, params,
  headers: { Authorization: `Bearer ${localStorage.getItem('erp_token')}` },
}).then((r) => r.data);

/** Pesan galat ramah dari respons server (detail teks atau {message}). */
export const pesanGalat = (e, cadangan = 'Permintaan gagal. Coba lagi.') => {
  const d = e?.response?.data?.detail;
  if (typeof d === 'string') return d;
  if (d && typeof d === 'object' && d.message) return d.message;
  return cadangan;
};

export const SUMBER_SHIFT = {
  draf: 'Draf jadwal', jadwal: 'Jadwal terbit', penugasan: 'Penugasan', karyawan: 'Shift utama karyawan',
};
export const labelSumber = (s) => SUMBER_SHIFT[s] || 'Belum ada shift';

export const HARI_PENDEK = ['Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab', 'Min'];
export const HARI_KODE = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/** Senin dari minggu tanggal `iso` (YYYY-MM-DD). */
export function seninDari(iso) {
  const [y, m, d] = String(iso).slice(0, 10).split('-').map(Number);
  const hari = (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7;
  return addDaysISO(String(iso).slice(0, 10), -hari);
}

export const tambahHari = (iso, n) => addDaysISO(String(iso).slice(0, 10), n);

/** Teks warna yang terbaca di atas warna shift (warna adalah data shift, bukan hiasan). */
export function teksDiAtas(hex) {
  const h = String(hex || '').replace('#', '');
  if (h.length !== 6) return undefined;
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  return (0.299 * r + 0.587 * g + 0.114 * b) > 150 ? '#111827' : '#ffffff';
}

/** Kode shift dengan titik warna shift. */
export function TitikShift({ kode, warna, jam }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-sm text-foreground">
      <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-muted-foreground" aria-hidden="true"
        style={warna ? { backgroundColor: warna } : undefined} />
      <span className="font-medium">{kode || '—'}</span>
      {jam && <span className="tabular-nums text-muted-foreground">{jam}</span>}
    </span>
  );
}

export const jamShift = (s) => (s?.mulai ? `${s.mulai}–${s.selesai}` : (s?.start_time ? `${s.start_time}–${s.end_time}` : ''));

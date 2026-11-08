/**
 * Manajemen Aset — fungsi bantu bersama (panggilan API, format angka/tanggal, unduhan semua halaman).
 */
import { useEffect, useState } from 'react';
import { formatDateID, formatDateTimeID, formatPercent } from '@/lib/format';

const API = process.env.REACT_APP_BACKEND_URL || '';

export async function apicall(method, path, token, body) {
  const opts = {
    method,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
  };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch(`${API}${path}`, opts);
  // Always read body once, even on error responses
  let data;
  try {
    data = await r.json();
  } catch {
    data = {};
  }
  if (!r.ok) {
    const msg = data?.detail || data?.message || `HTTP ${r.status}`;
    throw Object.assign(new Error(msg), { status: r.status, data });
  }
  return data;
}

/** "Rp 1.234.567"; kosong → "—". */
export function fmtCurrency(v) {
  if (!v && v !== 0) return '—';
  return 'Rp ' + Number(v).toLocaleString('id-ID');
}

/** "04 Nov 2026" (dibaca dalam WIB); kosong → "—". */
export function fmtDate(s) {
  return formatDateID(s);
}

/** "04 Nov 2026, 08.30" (WIB). */
export function fmtDateTime(s) {
  return formatDateTimeID(s);
}

/** "45,3%" (koma desimal). */
export function fmtPersen(v, digits = 1) {
  return formatPercent(v, digits);
}

/** Angka uang mentah untuk berkas unduhan (tetap angka di Excel). */
export const angka = (v) => (v === null || v === undefined || v === '' ? '' : Number(v) || 0);

/**
 * Ambil SEMUA halaman dari daftar berhalaman server ({ items, pagination: { total_pages } }) untuk unduhan.
 * `ambilHalaman(page)` mengembalikan respons satu halaman.
 */
export async function ambilSemuaHalaman(ambilHalaman, batas = 100) {
  const semua = [];
  for (let page = 1; page <= batas; page += 1) {
    const d = await ambilHalaman(page);
    semua.push(...(d?.items || []));
    if (!d?.pagination || page >= (d.pagination.total_pages || 1)) break;
  }
  return semua;
}

/**
 * true bila layar HP (< 640 px). Dipakai untuk menaruh alat (Unduh, muat ulang) di baris penyaring pada HP:
 * Toolbar bersama menaruh alat di samping penyaring, sehingga di 390 px kotak cari terjepit ±200 px dan pil
 * penyaring tertimpa tombol Unduh.
 */
export function useHP(batas = 640) {
  const q = `(max-width: ${batas - 1}px)`;
  const [hp, setHp] = useState(() => typeof window !== 'undefined' && !!window.matchMedia?.(q).matches);
  useEffect(() => {
    const m = window.matchMedia?.(q);
    if (!m) return undefined;
    const ubah = () => setHp(m.matches);
    ubah();
    m.addEventListener?.('change', ubah);
    return () => m.removeEventListener?.('change', ubah);
  }, [q]);
  return hp;
}

// Re-export API base for components that need it directly (e.g., multipart/file uploads)
export { API };

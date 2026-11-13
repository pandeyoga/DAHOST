/**
 * cuttingApi — pembungkus fetch untuk Portal Cutting.
 * Semua path memakai prefix /api (ingress Kubernetes merutekan /api/* ke backend).
 */
import { StatusBadge } from '../moduleAtoms';

const BASE = process.env.REACT_APP_BACKEND_URL || '';

export async function cuttingApi(method, path, token, body) {
  const res = await fetch(`${BASE}/api/cutting${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (!res.ok) {
    const msg = (data && (data.detail || data.message)) || `HTTP ${res.status}`;
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return data;
}

// Standar UI/UX v2: status memakai StatusBadge (token warna, kontras cukup) — dulu kelas slate/abu buatan sendiri.
export const STATUS_META = {
  draft: { label: 'Draf', tone: 'muted' },
  // 14 Nov 2026: status TAMPILAN dari server (`display_status`) — draf yang kainnya belum cukup di gudang.
  waiting_fabric: { label: 'Menunggu kain', tone: 'warning' },
  in_progress: { label: 'Berjalan', tone: 'warning' },
  completed: { label: 'Selesai', tone: 'success' },
  cancelled: { label: 'Dibatalkan', tone: 'danger' },
};

export function StatusPill({ status }) {
  const m = STATUS_META[status] || STATUS_META.draft;
  return <StatusBadge status={status} label={m.label} tone={m.tone} />;
}

export const fmtNum = (n, d = 0) =>
  Number(n || 0).toLocaleString('id-ID', { minimumFractionDigits: d, maximumFractionDigits: d });

/**
 * Angka kain per satuan dari `by_unit` dashboard (Tahap 1, 6 Nov 2026): kg, yard, dan meter
 * tidak dijumlah jadi satu angka. Contoh: "12,50 kg · 300,00 yard". Tanpa data → "–".
 * `key` = 'consumed' | 'waste' | 'yield'; untuk yield satuannya "pcs/<satuan>".
 */
export function fmtPerUnit(byUnit, key, d = 2) {
  const parts = (byUnit || [])
    .filter((u) => u[key] !== null && u[key] !== undefined)
    .map((u) => `${fmtNum(u[key], d)} ${key === 'yield' ? `pcs/${u.unit}` : u.unit}`);
  return parts.length ? parts.join(' · ') : '–';
}

export const fmtRp = (n) => `Rp ${Number(n || 0).toLocaleString('id-ID')}`;

export function fmtDate(iso) {
  if (!iso) return '-';
  try {
    return new Date(iso).toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' });
  } catch {
    return String(iso).slice(0, 10);
  }
}

export function fmtDateTime(iso) {
  if (!iso) return '-';
  try {
    return new Date(iso).toLocaleString('id-ID', {
      day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return String(iso).slice(0, 16);
  }
}

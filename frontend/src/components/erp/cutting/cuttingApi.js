/**
 * cuttingApi — pembungkus fetch untuk Portal Cutting.
 * Semua path memakai prefix /api (ingress Kubernetes merutekan /api/* ke backend).
 */
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

export const STATUS_META = {
  draft: { label: 'Draft', cls: 'bg-slate-100 text-slate-700 border-slate-300 dark:bg-slate-400/15 dark:text-slate-300 dark:border-slate-400/30' },
  in_progress: { label: 'Berjalan', cls: 'bg-[hsl(var(--warning)/0.1)] text-[hsl(var(--warning))] border-[hsl(var(--warning)/0.35)]   ' },
  completed: { label: 'Selesai', cls: 'bg-[hsl(var(--success)/0.1)] text-[hsl(var(--success))] border-[hsl(var(--success)/0.35)]   ' },
  cancelled: { label: 'Dibatalkan', cls: 'bg-[hsl(var(--destructive)/0.1)] text-[hsl(var(--destructive))] border-[hsl(var(--destructive)/0.35)]   ' },
};

export function StatusPill({ status }) {
  const m = STATUS_META[status] || STATUS_META.draft;
  return (
    <span className={`inline-flex items-center text-[11px] font-semibold px-2 py-0.5 rounded-full border ${m.cls}`}>
      {m.label}
    </span>
  );
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

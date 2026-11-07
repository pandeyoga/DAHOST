/**
 * Bahan bersama layar Pantau (Tahap 9, 7 Nov 2026): Pantau Produksi, Laporan Selisih, Dashboard.
 *
 * Satu layar dipakai DUA portal (keputusan owner no. 7: menu DAN tampilan identik). Portal menentukan
 * saringan PO: Portal Produksi = PO internal, Portal Maklon = PO maklon. Semua angka dari /api/pantau/*
 * (backend `core.pantau_produksi`, satu sumber per baris PO) — layar tidak menghitung ulang.
 */
import { useCallback, useEffect, useState } from 'react';
import { RefreshCw, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Skeleton } from '@/components/ui/skeleton';
import FilterChips from '@/components/ui/filter-chips';
import { StatusBadge } from '../moduleAtoms';
import { apiGet } from '../../../lib/api';

/** 'internal' | 'maklon' — dari prop eksplisit, lalu dari portal yang sedang dibuka. */
export function portalBusinessType({ businessType, portalId } = {}) {
  if (businessType === 'internal' || businessType === 'maklon') return businessType;
  return portalId === 'maklon' ? 'maklon' : 'internal';
}

export const PORTAL_LABEL = { internal: 'PO internal', maklon: 'PO maklon' };

export const n = (v) => Number(v || 0).toLocaleString('id-ID');
export const pct = (v) => `${Number(v || 0).toLocaleString('id-ID', { maximumFractionDigits: 1 })}%`;

/** Status satu PO / baris PO — dihitung backend dari angka nyata (selesai = lolos QC ≥ dipesan). */
export const STATE_META = {
  belum: { label: 'Belum mulai', tone: 'muted' },
  jalan: { label: 'Berjalan', tone: 'info' },
  selesai: { label: 'Selesai QC', tone: 'success' },
  ditutup: { label: 'Ditutup', tone: 'default' },
};
export const RISK_META = {
  telat: { label: 'Lewat batas kirim', tone: 'danger' },
  berisiko: { label: 'Berisiko telat', tone: 'warning' },
  aman: { label: 'Sesuai jadwal', tone: 'success' },
  tanpa_deadline: { label: 'Tanpa batas kirim', tone: 'muted' },
};
export const BUCKET_META = {
  telat: { label: 'Telat', tone: 'danger' },
  jatuh_tempo: { label: 'Jatuh tempo', tone: 'warning' },
  mendekati: { label: 'Mendekati target', tone: 'warning' },
  on_track: { label: 'Sesuai jadwal', tone: 'success' },
  aman: { label: 'Sudah kembali', tone: 'muted' },
  tanpa_deadline: { label: 'Tanpa batas kirim', tone: 'muted' },
};
export const KIND_LABEL = { NORMAL: 'Normal', REPLACEMENT: 'Pengganti', ADDITIONAL: 'Tambahan', REWORK: 'Permak ke CMT' };
export const ENTRY_META = {
  staff: { label: 'Diinput staf DA', tone: 'warning' },
  mixed: { label: 'Sebagian diinput staf DA', tone: 'warning' },
  vendor: { label: 'Diisi vendor', tone: 'default' },
};
/** Status PO tersimpan (kode Inggris lama) → kata yang dipahami staf. */
const PO_STATUS_ID = {
  Draft: 'Draf', Confirmed: 'Dikonfirmasi', Distributed: 'Bahan dikirim', 'In Production': 'Produksi',
  'Production Complete': 'Produksi selesai', 'Variance Review': 'Cek selisih', 'Return Review': 'Cek retur',
  'Ready to Close': 'Siap ditutup', Completed: 'Selesai', Closed: 'Ditutup', 'Closed Short': 'Ditutup kurang',
  Cancelled: 'Dibatalkan',
};
export const poStatusLabel = (s) => PO_STATUS_ID[s] || s || '—';
const JOB_STATUS_ID = {
  Open: 'Terbuka', 'In Progress': 'Berjalan', 'In Production': 'Berjalan', Completed: 'Selesai', Closed: 'Ditutup',
  Cancelled: 'Dibatalkan', 'Menunggu kirim material': 'Menunggu kiriman bahan',
};
export const jobStatusLabel = (s) => JOB_STATUS_ID[s] || s || '—';

export function Badge({ meta, testId }) {
  if (!meta) return <span className="text-muted-foreground">—</span>;
  return <StatusBadge label={meta.label} tone={meta.tone} testId={testId} />;
}

/** Muat satu endpoint /api/pantau/* (atau lain) — data, memuat, galat, muat ulang. */
export function useApi(path, { auto = 0 } = {}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const reload = useCallback(async () => {
    if (!path) return;
    setLoading(true); setError('');
    try { setData(await apiGet(path)); }
    catch (e) { setError(e.message || 'Gagal memuat data'); }
    finally { setLoading(false); }
  }, [path]);
  useEffect(() => { reload(); }, [reload]);
  useEffect(() => {
    if (!auto) return undefined;
    const t = setInterval(reload, auto);
    return () => clearInterval(t);
  }, [auto, reload]);
  return { data, loading, error, reload };
}

export function SearchBox({ value, onChange, placeholder, testId }) {
  return (
    <div className="relative w-72 max-w-full">
      <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
      <GlassInput className="pl-9 h-9" placeholder={placeholder} value={value}
        onChange={(e) => onChange(e.target.value)} data-testid={testId} aria-label={placeholder} />
    </div>
  );
}

export function RefreshButton({ onClick, loading, testId = 'pantau-refresh' }) {
  return (
    <Button variant="outline" size="icon" onClick={onClick} title="Muat ulang" aria-label="Muat ulang" data-testid={testId}>
      <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
    </Button>
  );
}

export function ScopeChips({ value, onChange, testId = 'pantau-scope' }) {
  return (
    <FilterChips value={value} onChange={onChange} testId={testId} ariaLabel="Cakupan PO"
      options={[{ key: 'running', label: 'PO berjalan' }, { key: 'all', label: 'Semua PO' }]} />
  );
}

/** Judul kecil satu bagian + isinya dalam SATU kartu (tabel). */
export function Section({ title, hint, children, testId }) {
  return (
    <section className="space-y-2" data-testid={testId}>
      {title && (
        <div className="flex items-baseline justify-between gap-3 flex-wrap">
          <p className="text-sm font-semibold text-foreground">{title}</p>
          {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
        </div>
      )}
      <GlassCard className="p-0 overflow-hidden">{children}</GlassCard>
    </section>
  );
}

export function LoadingRows({ rows = 5 }) {
  return <div className="space-y-2 p-4">{Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className="h-11 rounded-lg" />)}</div>;
}

/** Sel angka standar (rata kanan, tabular). `tone` = success | warning | danger | muted. */
export function numClass(tone) {
  return {
    success: 'text-[hsl(var(--success-text))] font-semibold',
    warning: 'text-[hsl(var(--warning-text))] font-semibold',
    danger: 'text-[hsl(var(--danger-text))] font-semibold',
    muted: 'text-muted-foreground',
  }[tone] || '';
}

/** "+12" hijau / "−3" merah / "0" abu — selisih. */
export function Signed({ v }) {
  const x = Number(v || 0);
  if (!x) return <span className="text-muted-foreground tabular-nums">0</span>;
  return <span className={`tabular-nums font-semibold ${x > 0 ? 'text-[hsl(var(--warning-text))]' : 'text-[hsl(var(--danger-text))]'}`}>
    {x > 0 ? `+${n(x)}` : `−${n(-x)}`}
  </span>;
}

/** Simpan tab awal untuk HubTabs (`hub_tab_<hubId>`) dari deep link / prop `initialTab`. */
export function primeHubTab(hubId, tab, keys) {
  if (!tab || !keys.includes(tab)) return;
  try { sessionStorage.setItem(`hub_tab_${hubId}`, tab); } catch (e) { /* sessionStorage tidak tersedia */ }
}

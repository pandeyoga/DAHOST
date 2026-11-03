/**
 * Umur hutang — tab di menu "Hutang Pemasok & CMT".
 *
 * 2026-11-04 (audit Keuangan): data dari SSOT `core.payables` (tagihan pemasok + tagihan CMT, tanpa
 * batas 500 baris). Lima kartu kelompok umur diganti satu batang bertumpuk; "Days Overdue" minus
 * (−23) diganti kalimat ("jatuh tempo 23 hari lagi"); judul kolom (Rp); tampilan per pemasok
 * menggantikan daftar "hutang per pemasok" yang dulu ada di Rekap dan Nota Debit.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { RefreshCw, CreditCard, Download, FileBarChart, AlertTriangle } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { PageHeader, StatTile } from './moduleAtoms';
import { EmptyState } from './EmptyState';
import { Skeleton } from '@/components/ui/skeleton';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatDateID, formatNumber, formatRupiah } from '@/lib/format';
import { todayWIB } from '@/lib/waktu';

const BUCKETS = [
  { key: 'current', label: 'Belum jatuh tempo', cls: 'bg-emerald-500' },
  { key: '1_30', label: '1–30 hari', cls: 'bg-amber-400' },
  { key: '31_60', label: '31–60 hari', cls: 'bg-orange-500' },
  { key: '61_90', label: '61–90 hari', cls: 'bg-rose-500' },
  { key: '90_plus', label: '> 90 hari', cls: 'bg-red-700' },
];
const KIND = { ap: 'Bahan & jasa', cmt: 'CMT' };

export function lateText(days) {
  if (days > 0) return `terlambat ${days} hari`;
  if (days === 0) return 'jatuh tempo hari ini';
  return `jatuh tempo ${-days} hari lagi`;
}

export default function RahazaAPAgingModule({ token }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [view, setView] = useState('bills');
  const [kind, setKind] = useState('');
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchData = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const r = await fetch('/api/rahaza/ap-aging', { headers });
      if (!r.ok) { setError(`Gagal memuat (HTTP ${r.status})`); return; }
      setData(await r.json());
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);
  useEffect(() => { fetchData(); }, [fetchData]);

  const details = useMemo(() => (data?.details || []).filter(r => !kind || r.kind === kind), [data, kind]);
  const byVendor = useMemo(() => {
    const m = new Map();
    details.forEach(r => {
      const v = m.get(r.vendor_name) || { vendor_name: r.vendor_name, count: 0, balance: 0, overdue: 0, oldest: -99999 };
      v.count += 1; v.balance += r.balance; if (r.days_overdue > 0) v.overdue += r.balance;
      v.oldest = Math.max(v.oldest, r.days_overdue);
      m.set(r.vendor_name, v);
    });
    return [...m.values()].sort((a, b) => b.balance - a.balance);
  }, [details]);
  const list = view === 'vendors' ? byVendor : details;
  const { page, setPage, totalPages, paged } = useClientPagination(list, 25);
  const total = data?.total || 0;

  const exportCSV = () => {
    const esc = (c) => { const v = String(c ?? ''); return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v; };
    const rows = details.map(r => [KIND[r.kind] || r.kind, r.number, r.vendor_name, r.issue_date, r.due_date,
      lateText(r.days_overdue), r.total, r.paid, r.balance]);
    const csv = [['Jenis', 'No. tagihan', 'Pemasok', 'Tanggal', 'Jatuh tempo', 'Keterlambatan', 'Total', 'Dibayar', 'Sisa'], ...rows]
      .map(r => r.map(esc).join(',')).join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a'); link.href = url; link.download = `umur-hutang-${todayWIB()}.csv`; link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-4" data-testid="ap-aging-page">
      <PageHeader
        icon={CreditCard}
        title="Umur Hutang"
        subtitle="Hutang yang belum dibayar menurut tanggal jatuh tempo, termasuk tagihan CMT."
        actions={
          <>
            <Button variant="ghost" onClick={fetchData} className="h-9 border border-[var(--glass-border)]" title="Muat ulang" aria-label="Muat ulang" data-testid="apa-refresh"><RefreshCw className="w-3.5 h-3.5" /></Button>
            <Button variant="ghost" onClick={exportCSV} disabled={!details.length} className="h-9 border border-[var(--glass-border)]" data-testid="apa-export"><Download className="w-3.5 h-3.5 mr-1.5" />Unduh CSV</Button>
          </>
        }
      />

      {error && <GlassCard className="p-3 text-sm text-[hsl(var(--destructive))]" data-testid="apa-error">{error}</GlassCard>}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <StatTile label="Hutang tercatat · hari ini" value={formatRupiah(total)} testId="apa-total" />
        <StatTile label="Lewat jatuh tempo" value={formatRupiah(data?.overdue || 0)} accent={(data?.overdue || 0) > 0 ? 'danger' : 'default'} testId="apa-overdue" />
        <StatTile label="Jumlah tagihan terbuka" value={formatNumber((data?.details || []).length)} testId="apa-count" />
      </div>

      {(data?.unposted || []).length > 0 && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 text-amber-800 dark:text-amber-200 px-3 py-2 text-sm flex items-center gap-2" data-testid="apa-unposted">
          <AlertTriangle className="w-4 h-4" />
          {data.unposted.length} tagihan CMT ({formatRupiah(data.unposted_total)}) belum dijurnal sehingga belum masuk total di atas — buka tab Tagihan untuk mempostingnya.
        </div>
      )}

      {total > 0 && (
        <GlassCard className="p-4 space-y-2" data-testid="apa-bar">
          <div className="flex h-3.5 rounded overflow-hidden bg-foreground/10" role="img"
               aria-label={BUCKETS.map(b => `${b.label} ${formatRupiah(data.buckets[b.key] || 0)}`).join(', ')}>
            {BUCKETS.map(b => (data.buckets[b.key] || 0) > 0 && (
              <div key={b.key} className={b.cls} style={{ width: `${(data.buckets[b.key] / total) * 100}%` }} title={`${b.label}: ${formatRupiah(data.buckets[b.key])}`} />
            ))}
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
            {BUCKETS.map(b => (
              <span key={b.key} data-testid={`apa-kpi-${b.key}`}><span className={`inline-block w-2 h-2 rounded-sm mr-1.5 align-middle ${b.cls}`} />{b.label} <b className="text-foreground">{formatRupiah(data.buckets[b.key] || 0)}</b></span>
            ))}
          </div>
        </GlassCard>
      )}

      <div className="flex items-center gap-2 flex-wrap">
        <div className="inline-flex rounded-lg border border-[var(--glass-border)] overflow-hidden text-xs" role="tablist" aria-label="Tampilan">
          {[['bills', 'Per tagihan'], ['vendors', 'Per pemasok']].map(([k, l]) => (
            <button key={k} type="button" role="tab" aria-selected={view === k} onClick={() => { setView(k); setPage(1); }}
              className={`px-3 py-1.5 ${view === k ? 'bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))] font-medium' : 'text-muted-foreground'}`}
              data-testid={`apa-view-${k}`}>{l}</button>
          ))}
        </div>
        <select value={kind} onChange={e => { setKind(e.target.value); setPage(1); }} aria-label="Jenis tagihan"
          className="h-8 rounded-[var(--radius-sm)] bg-[var(--card-surface)] border border-[var(--glass-border)] px-2 text-xs text-foreground" data-testid="apa-kind">
          <option value="">Semua jenis</option>
          <option value="ap">Bahan &amp; jasa</option>
          <option value="cmt">CMT</option>
        </select>
      </div>

      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-12 rounded-lg" />)}
          </div>
        ) : !list.length ? (
          <EmptyState icon={FileBarChart} title="Tidak ada hutang yang belum dibayar"
            description="Semua tagihan pemasok dan CMT sudah lunas." data-testid="apa-empty" />
        ) : view === 'vendors' ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-muted-foreground border-b border-[var(--glass-border)]">
                <th className="py-2 px-3 font-medium">Pemasok</th><th className="py-2 px-3 font-medium text-right">Tagihan</th>
                <th className="py-2 px-3 font-medium">Paling lama</th>
                <th className="py-2 px-3 font-medium text-right">Lewat jatuh tempo (Rp)</th><th className="py-2 px-3 font-medium text-right">Sisa (Rp)</th>
              </tr></thead>
              <tbody>
                {paged.map(v => (
                  <tr key={v.vendor_name} className="border-b border-[var(--glass-border)]" data-testid={`apa-vendor-${v.vendor_name}`}>
                    <td className="py-2 px-3">{v.vendor_name}</td>
                    <td className="py-2 px-3 text-right tabular-nums">{v.count}</td>
                    <td className={`py-2 px-3 text-xs ${v.oldest > 0 ? 'text-red-600 dark:text-red-300' : 'text-muted-foreground'}`}>{lateText(v.oldest)}</td>
                    <td className="py-2 px-3 text-right font-mono text-xs">{formatNumber(v.overdue)}</td>
                    <td className="py-2 px-3 text-right font-mono text-xs font-semibold">{formatNumber(v.balance)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground border-b border-[var(--glass-border)]">
                  <th className="py-2 px-3 font-medium">No. tagihan</th>
                  <th className="py-2 px-3 font-medium">Jenis</th>
                  <th className="py-2 px-3 font-medium">Pemasok</th>
                  <th className="py-2 px-3 font-medium">Jatuh tempo</th>
                  <th className="py-2 px-3 font-medium">Keterlambatan</th>
                  <th className="py-2 px-3 font-medium text-right">Total (Rp)</th>
                  <th className="py-2 px-3 font-medium text-right">Dibayar (Rp)</th>
                  <th className="py-2 px-3 font-medium text-right">Sisa (Rp)</th>
                </tr>
              </thead>
              <tbody>
                {paged.map(r => (
                  <tr key={`${r.kind}-${r.id}`} className="border-b border-[var(--glass-border)] hover:bg-foreground/5" data-testid={`apa-row-${r.number}`}>
                    <td className="py-2 px-3 font-mono text-xs">{r.number}</td>
                    <td className="py-2 px-3 text-xs">{KIND[r.kind] || r.kind}</td>
                    <td className="py-2 px-3">{r.vendor_name}</td>
                    <td className="py-2 px-3 text-xs whitespace-nowrap">{formatDateID(r.due_date)}</td>
                    <td className={`py-2 px-3 text-xs ${r.days_overdue > 0 ? 'text-red-600 dark:text-red-300 font-medium' : 'text-muted-foreground'}`}>{lateText(r.days_overdue)}</td>
                    <td className="py-2 px-3 text-right font-mono text-xs">{formatNumber(r.total)}</td>
                    <td className="py-2 px-3 text-right font-mono text-xs">{formatNumber(r.paid)}</td>
                    <td className="py-2 px-3 text-right font-mono text-xs font-semibold">{formatNumber(r.balance)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {totalPages > 1 && <div className="px-3 py-2"><PaginationLite page={page} totalPages={totalPages} total={list.length} pageSize={25} onPageChange={setPage} /></div>}
      </GlassCard>
    </div>
  );
}

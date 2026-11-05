/**
 * Umur hutang — tab di menu "Hutang Pemasok & CMT".
 *
 * 2026-11-04 (audit Keuangan): data dari SSOT `core.payables` (tagihan pemasok + tagihan CMT, tanpa
 * batas 500 baris). Lima kartu kelompok umur diganti satu batang bertumpuk; "Days Overdue" minus
 * (−23) diganti kalimat ("jatuh tempo 23 hari lagi"); judul kolom (Rp); tampilan per pemasok
 * menggantikan daftar "hutang per pemasok" yang dulu ada di Rekap dan Nota Debit.
 *
 * 2026-11-05 (PANDUAN_UI G1/G4/G8): cetakan PageLayout — "Per tagihan | Per pemasok" jadi pil penyaring
 * (dulu segmen buatan sendiri) dan pilihan jenis memakai SmartNativeSelect; warna batang umur hanya token
 * (abu = belum jatuh tempo, kuning = perhatian, merah = masalah).
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { RefreshCw, Download, FileBarChart, AlertTriangle } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import FilterChips from '@/components/ui/filter-chips';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { StatTile, EmptyState, Notice } from './moduleAtoms';
import PageLayout from './layout/PageLayout';
import { Skeleton } from '@/components/ui/skeleton';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatDateID, formatNumber, formatRupiah } from '@/lib/format';
import { todayWIB } from '@/lib/waktu';

const BUCKETS = [
  { key: 'current', label: 'Belum jatuh tempo', cls: 'bg-foreground/30' },
  { key: '1_30', label: '1–30 hari', cls: 'bg-[hsl(var(--warning)/0.6)]' },
  { key: '31_60', label: '31–60 hari', cls: 'bg-[hsl(var(--warning))]' },
  { key: '61_90', label: '61–90 hari', cls: 'bg-[hsl(var(--destructive)/0.7)]' },
  { key: '90_plus', label: '> 90 hari', cls: 'bg-[hsl(var(--destructive))]' },
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

  const filters = (
    <>
      <FilterChips value={view} onChange={(k) => { setView(k); setPage(1); }} testId="apa-view" ariaLabel="Tampilan" hideWhenEmpty={false}
        options={[{ key: 'bills', label: 'Per tagihan', count: details.length }, { key: 'vendors', label: 'Per pemasok', count: byVendor.length }]} />
      <SmartNativeSelect value={kind} onChange={e => { setKind(e.target.value); setPage(1); }} aria-label="Jenis tagihan"
        searchable={false} className="h-9 w-44" data-testid="apa-kind">
        <option value="">Semua jenis</option>
        <option value="ap">Bahan &amp; jasa</option>
        <option value="cmt">CMT</option>
      </SmartNativeSelect>
    </>
  );

  return (
    <PageLayout
      testId="ap-aging-page"
      title="Umur Hutang"
      subtitle="Hutang yang belum dibayar menurut tanggal jatuh tempo, termasuk tagihan CMT."
      filters={filters}
      tools={<>
        <Button size="icon" variant="outline" onClick={fetchData} title="Muat ulang" aria-label="Muat ulang" data-testid="apa-refresh"><RefreshCw className="w-4 h-4" /></Button>
        <Button variant="outline" onClick={exportCSV} disabled={!details.length} data-testid="apa-export"><Download className="w-4 h-4" />Unduh CSV</Button>
      </>}
      summary={<>
        {error && <Notice tone="danger" icon={AlertTriangle} testId="apa-error">{error}</Notice>}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <StatTile label="Hutang tercatat · hari ini" value={formatRupiah(total)} testId="apa-total" />
          <StatTile label="Lewat jatuh tempo" value={formatRupiah(data?.overdue || 0)} accent={(data?.overdue || 0) > 0 ? 'danger' : 'default'} testId="apa-overdue" />
          <StatTile label="Jumlah tagihan terbuka" value={formatNumber((data?.details || []).length)} testId="apa-count" />
        </div>
        {(data?.unposted || []).length > 0 && (
          <Notice tone="warning" icon={AlertTriangle} testId="apa-unposted">
            {data.unposted.length} tagihan CMT ({formatRupiah(data.unposted_total)}) belum dijurnal sehingga belum masuk total di atas — buka tab Tagihan untuk mempostingnya.
          </Notice>
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
                <span key={b.key} className="whitespace-nowrap" data-testid={`apa-kpi-${b.key}`}><span className={`inline-block w-2 h-2 rounded-sm mr-1.5 align-middle ${b.cls}`} />{b.label} <b className="text-foreground tabular-nums">{formatRupiah(data.buckets[b.key] || 0)}</b></span>
              ))}
            </div>
          </GlassCard>
        )}
      </>}
      footer={totalPages > 1 && <PaginationLite page={page} totalPages={totalPages} total={list.length} pageSize={25} onPageChange={setPage} />}
    >
      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-12 rounded-lg" />)}
          </div>
        ) : !list.length ? (
          <EmptyState icon={FileBarChart} title="Tidak ada hutang yang belum dibayar"
            description={kind ? 'Tidak ada tagihan terbuka untuk jenis ini.' : 'Semua tagihan pemasok dan CMT sudah lunas.'} testId="apa-empty" />
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
                    <td className={`py-2 px-3 text-xs whitespace-nowrap ${v.oldest > 0 ? 'text-[hsl(var(--destructive))]' : 'text-muted-foreground'}`}>{lateText(v.oldest)}</td>
                    <td className="py-2 px-3 text-right tabular-nums whitespace-nowrap text-xs">{formatNumber(v.overdue)}</td>
                    <td className="py-2 px-3 text-right tabular-nums whitespace-nowrap text-xs font-semibold">{formatNumber(v.balance)}</td>
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
                    <td className="py-2 px-3 text-xs whitespace-nowrap">{r.number}</td>
                    <td className="py-2 px-3 text-xs whitespace-nowrap">{KIND[r.kind] || r.kind}</td>
                    <td className="py-2 px-3">{r.vendor_name}</td>
                    <td className="py-2 px-3 text-xs whitespace-nowrap">{formatDateID(r.due_date)}</td>
                    <td className={`py-2 px-3 text-xs whitespace-nowrap ${r.days_overdue > 0 ? 'text-[hsl(var(--destructive))] font-medium' : 'text-muted-foreground'}`}>{lateText(r.days_overdue)}</td>
                    <td className="py-2 px-3 text-right tabular-nums whitespace-nowrap text-xs">{formatNumber(r.total)}</td>
                    <td className="py-2 px-3 text-right tabular-nums whitespace-nowrap text-xs">{formatNumber(r.paid)}</td>
                    <td className="py-2 px-3 text-right tabular-nums whitespace-nowrap text-xs font-semibold">{formatNumber(r.balance)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
    </PageLayout>
  );
}

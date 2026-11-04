import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Download, FileBarChart } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { PageHeader, StatTile, EmptyState } from './moduleAtoms';
import { Skeleton } from '@/components/ui/skeleton';
import { formatDateID } from '@/lib/format';
import PeriodPicker, { periodFromPreset } from './finance/PeriodPicker';
import StatementTable from './finance/StatementTable';

const fmt = (n) => Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 0 });

/**
 * Laba Rugi (menu Laporan › Laba Rugi › Total periode).
 * 2026-11-04 (PANDUAN_UI G7): satu tabel laporan — dulu tiap kelompok satu kartu bulat dan subtotal
 * berupa "pil" berlabel Inggris (Gross Profit / Operating Income), angka berhuruf mesin ketik.
 * Beban & HPP ditulis minus supaya alurnya terbaca: Pendapatan − HPP = Laba kotor − Beban = Laba usaha.
 */
export default function RahazaPnLModule({ token }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [period, setPeriod] = useState(() => periodFromPreset('ytd'));
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchData = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const params = new URLSearchParams({ from: period.from, to: period.to });
      const r = await fetch(`/api/rahaza/finance/reports/profit-loss?${params}`, { headers });
      if (!r.ok) { setError(`Gagal memuat laporan (HTTP ${r.status})`); return; }
      setData(await r.json());
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, period.from, period.to]);
  useEffect(() => { fetchData(); }, [fetchData]);

  const exportCSV = () => {
    if (!data) return;
    const lines = [['Kelompok', 'Kode', 'Akun', 'Jumlah']];
    Object.values(data.groups || {}).forEach((g) => {
      (g.accounts || []).forEach((a) => lines.push([g.label, a.code, a.name, a.amount]));
      lines.push([`Total ${g.label}`, '', '', g.total]);
    });
    const t = data.totals || {};
    lines.push(['Laba kotor', '', '', t.gross_profit], ['Laba usaha', '', '', t.operating_income], ['Laba bersih', '', '', t.net_income]);
    const csv = lines.map((r) => r.map((c) => (typeof c === 'string' && c.includes(',')) ? `"${c}"` : c).join(',')).join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url; link.download = `laba-rugi-${period.from}-${period.to}.csv`; link.click();
    URL.revokeObjectURL(url);
  };

  const t = data?.totals || {};
  const g = data?.groups || {};
  const group = (key, sign) => {
    const x = g[key] || { label: key, total: 0, accounts: [] };
    return {
      kind: 'group', id: key, label: x.label, values: { amount: sign * Number(x.total || 0) }, hideZeroChildren: true,
      children: (x.accounts || []).map((a) => ({ code: a.code, label: a.name, values: { amount: sign * Number(a.amount || 0) } })),
    };
  };
  const rows = data ? [
    group('revenue', 1),
    group('cogs', -1),
    { kind: 'subtotal', label: 'Laba kotor', values: { amount: t.gross_profit } },
    group('expense', -1),
    { kind: 'subtotal', label: 'Laba usaha', values: { amount: t.operating_income } },
    group('other_income', 1),
    group('other_expense', -1),
    { kind: 'total', label: Number(t.net_income) >= 0 ? 'Laba bersih' : 'Rugi bersih', values: { amount: t.net_income }, testId: 'pnl-net-summary' },
  ] : [];
  const periodLabel = `${formatDateID(period.from)} – ${formatDateID(period.to)}`;

  return (
    <div className="space-y-4" data-testid="pnl-page">
      <PageHeader
        title="Laba Rugi"
        subtitle="Pendapatan − HPP − beban = laba bersih, dari buku besar."
        actions={
          <>
            <PeriodPicker value={period} onChange={setPeriod} testId="pnl-period" />
            <Button variant="outline" size="icon" onClick={fetchData} title="Muat ulang" aria-label="Muat ulang" data-testid="pnl-refresh"><RefreshCw className="w-4 h-4" /></Button>
            <Button variant="outline" onClick={exportCSV} disabled={!data} data-testid="pnl-export"><Download className="w-4 h-4" />Unduh CSV</Button>
          </>
        }
      />

      {error && <GlassCard className="p-3 text-sm text-[hsl(var(--destructive))]" data-testid="pnl-error">{error}</GlassCard>}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatTile label="Pendapatan" value={fmt(t.revenue)} testId="pnl-kpi-revenue" />
        <StatTile label="HPP" value={fmt(t.cogs)} testId="pnl-kpi-cogs" />
        <StatTile label="Laba kotor" value={fmt(t.gross_profit)} accent={Number(t.gross_profit) < 0 ? 'danger' : 'default'} testId="pnl-kpi-gross" />
        <StatTile label={Number(t.net_income) >= 0 ? 'Laba bersih' : 'Rugi bersih'} value={fmt(t.net_income)} accent={Number(t.net_income) < 0 ? 'danger' : 'default'} testId="pnl-kpi-net" />
      </div>

      {loading ? (
        <Skeleton className="h-80 rounded-[var(--radius-lg)]" />
      ) : !data ? (
        <EmptyState icon={FileBarChart} title="Belum ada laporan" description="Laba rugi muncul setelah ada jurnal di periode ini." />
      ) : (
        <StatementTable testId="pnl" columns={[{ key: 'amount', label: periodLabel }]} rows={rows} />
      )}
    </div>
  );
}

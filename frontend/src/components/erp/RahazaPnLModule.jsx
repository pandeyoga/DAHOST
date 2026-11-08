import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, FileBarChart } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { EmptyState } from './moduleAtoms';
import PageLayout from './layout/PageLayout';
import IntercompanyNotes from './finance/IntercompanyNotes';
import { Skeleton } from '@/components/ui/skeleton';
import { formatDateID } from '@/lib/format';
import PeriodPicker, { periodFromPreset } from './finance/PeriodPicker';
import StatementTable, { unduhanLaporan } from './finance/StatementTable';

const fmt = (n) => Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 0 });

/**
 * Laba Rugi (menu Laporan › Laba Rugi › Total periode).
 * 2026-11-04 (PANDUAN_UI G7): satu tabel laporan — dulu tiap kelompok satu kartu bulat dan subtotal
 * berupa "pil" berlabel Inggris (Gross Profit / Operating Income), angka berhuruf mesin ketik.
 * Beban & HPP ditulis minus supaya alurnya terbaca: Pendapatan − HPP = Laba kotor − Beban = Laba usaha.
 * 2026-11-05 (PANDUAN_UI G1): cetakan PageLayout — periode di toolbar kiri, muat ulang & unduh di kanan.
 * 2026-11-08 (Standar UI/UX v2): unduh Excel/CSV (dulu CSV saja); 4 kartu angka yang mengulang baris subtotal di
 * tabel diganti satu kalimat ringkas (angka sama) supaya laporan tidak terdorong ke bawah, terutama di HP.
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
  const kolomLap = [{ key: 'amount', label: periodLabel }];
  const neg = (n) => (Number(n) < 0 ? 'text-[hsl(var(--danger-text))]' : 'text-foreground');

  return (
    <PageLayout
      testId="pnl-page"
      title="Laba Rugi"
      subtitle="Pendapatan − HPP − beban = laba bersih, dari buku besar."
      filters={<PeriodPicker value={period} onChange={setPeriod} testId="pnl-period" />}
      tools={<>
        <Button variant="outline" size="icon" onClick={fetchData} title="Muat ulang" aria-label="Muat ulang" data-testid="pnl-refresh"><RefreshCw className="w-4 h-4" /></Button>
        <TombolUnduh namaBerkas={`laba-rugi-${period.from}-${period.to}`} namaLembar="Laba rugi" testId="pnl-export"
          baris={unduhanLaporan(kolomLap, rows).baris} kolom={unduhanLaporan(kolomLap, rows).kolom} />
      </>}
      summary={<>
        {error && <p className="text-sm text-[hsl(var(--danger-text))]" data-testid="pnl-error">{error}</p>}
        {/* Tahap 8 fase 3: Gabungan = setelah eliminasi antar CV; selisih yang belum tereliminasi tampil di sini */}
        <IntercompanyNotes data={data} testId="pnl-ic-notes" />
        {data && (
          <p className="text-sm text-muted-foreground" data-testid="pnl-ringkas">
            Pendapatan <b className="text-foreground tabular-nums" data-testid="pnl-kpi-revenue">{fmt(t.revenue)}</b>
            {/* HP: HPP & laba kotor hanya di tabel (baris tepat di bawah) — kalimat ringkas tetap 1–2 baris */}
            <span className="hidden sm:inline">
              {' '}− HPP <b className="text-foreground tabular-nums" data-testid="pnl-kpi-cogs">{fmt(t.cogs)}</b>
              {' '}= laba kotor <b className={`tabular-nums ${neg(t.gross_profit)}`} data-testid="pnl-kpi-gross">{fmt(t.gross_profit)}</b>
            </span>
            {' '}· {Number(t.net_income) >= 0 ? 'laba' : 'rugi'} bersih <b className={`tabular-nums ${neg(t.net_income)}`} data-testid="pnl-kpi-net">{fmt(t.net_income)}</b>
          </p>
        )}
      </>}
    >
      {loading ? (
        <Skeleton className="h-80 rounded-[var(--radius-lg)]" />
      ) : !data ? (
        <GlassCard className="p-0">
          <EmptyState icon={FileBarChart} title="Belum ada laporan" description="Laba rugi muncul setelah ada jurnal di periode ini." />
        </GlassCard>
      ) : (
        <StatementTable testId="pnl" columns={kolomLap} rows={rows} />
      )}
    </PageLayout>
  );
}

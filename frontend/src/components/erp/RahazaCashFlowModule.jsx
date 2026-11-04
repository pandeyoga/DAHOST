import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Wallet, Download, FileSpreadsheet } from 'lucide-react';
import { toast } from 'sonner';
import { downloadXlsx } from './finance/reportShared';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import FilterChips from '@/components/ui/filter-chips';
import { PageHeader, StatTile, EmptyState } from './moduleAtoms';
import { Skeleton } from '@/components/ui/skeleton';
import { formatDateID } from '@/lib/format';
import PeriodPicker, { periodFromPreset } from './finance/PeriodPicker';
import StatementTable from './finance/StatementTable';

const fmt = (n) => Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 0 });
const COLS = [{ key: 'in', label: 'Masuk' }, { key: 'out', label: 'Keluar' }, { key: 'net', label: 'Bersih' }];

/**
 * Arus Kas › Sudah terjadi.
 * 2026-11-02 (audit No.46 / K19): kedua tampilan dari buku besar — Per akun lawan (OPR/INV/PND) dan
 * Per jenis transaksi (sumber jurnal yang menyentuh kas/bank).
 * 2026-11-04 (PANDUAN_UI G7): satu tabel laporan (Masuk · Keluar · Bersih) — dulu tiap aktivitas satu
 * kartu berwarna, ringkasan berupa kartu besar, dan angka berhuruf mesin ketik hijau/merah.
 */
export default function RahazaCashFlowModule({ token }) {
  const [view, setView] = useState('account');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [period, setPeriod] = useState(() => periodFromPreset('month'));
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
  const { from, to } = period;

  const fetchData = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const params = new URLSearchParams({ from, to });
      const r = await fetch(`/api/rahaza/finance/reports/cash-flow?${params}`, { headers });
      if (!r.ok) { setError(`Gagal memuat arus kas (HTTP ${r.status})`); return; }
      setData(await r.json());
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, from, to]);
  useEffect(() => { fetchData(); }, [fetchData]);

  const exportCSV = () => {
    if (!data) return;
    const lines = [['Aktivitas', 'Jenis', 'Masuk', 'Keluar', 'Bersih', 'Jumlah jurnal']];
    Object.values(data.activities || {}).forEach((act) => {
      (act.items || []).forEach((r) => lines.push([act.label, r.label, r.inflow, r.outflow, r.net, r.count]));
      lines.push([`Total ${act.label}`, '', '', '', act.total, '']);
    });
    lines.push(['Perubahan kas', '', '', '', data.totals.net_change_in_cash, '']);
    lines.push(['Kas awal', '', '', '', data.totals.opening_cash, '']);
    lines.push(['Kas akhir', '', '', '', data.totals.closing_cash, '']);
    const csv = lines.map((r) => r.map((c) => (typeof c === 'string' && c.includes(',')) ? `"${c}"` : c).join(',')).join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url; link.download = `arus-kas-${from}-${to}.csv`; link.click();
    URL.revokeObjectURL(url);
  };
  const exportXlsx = () => downloadXlsx(`/api/rahaza/finance/reports/export-xlsx?report=cash-flow&from=${from}&to=${to}`, token, `arus-kas-${from}-${to}.xlsx`)
    .catch((e) => toast.error(`Ekspor gagal: ${e.message}`));

  const t = data?.totals || {};
  const ba = data?.by_account;
  const vals = (r) => ({ in: r.inflow || 0, out: r.outflow ? -r.outflow : 0, net: r.net || 0 });
  const sum = (items) => items.reduce((a, r) => ({ in: a.in + (r.inflow || 0), out: a.out - (r.outflow || 0), net: a.net + (r.net || 0) }), { in: 0, out: 0, net: 0 });

  let rows = [];
  let opening = 0; let closing = 0;
  if (data && view === 'account' && ba) {
    opening = ba.totals?.opening_cash_gl; closing = ba.totals?.closing_cash_gl;
    rows = [{ kind: 'line', label: 'Kas awal periode', values: { net: opening } }];
    ['OPR', 'INV', 'PND'].forEach((g) => {
      const grp = ba.groups[g] || { label: g, items: [], total: 0 };
      rows.push({ kind: 'group', id: `acc-${g}`, label: grp.label, values: { ...sum(grp.items), net: grp.total },
        children: grp.items.map((r) => ({ code: r.code, label: r.name, note: r.tag_source === 'default' ? '(kelompok bawaan)' : '', values: vals(r) })) });
    });
    rows.push({ kind: 'subtotal', label: 'Perubahan kas', values: { net: Number(closing || 0) - Number(opening || 0) } });
    rows.push({ kind: 'total', label: 'Kas akhir periode', values: { net: closing }, testId: 'cf-summary' });
  } else if (data) {
    opening = t.opening_cash; closing = t.closing_cash;
    rows = [{ kind: 'line', label: 'Kas awal periode', values: { net: opening } }];
    ['operating', 'investing', 'financing'].forEach((k) => {
      const act = data.activities[k];
      rows.push({ kind: 'group', id: `cat-${k}`, label: act.label, values: { ...sum(act.items), net: act.total },
        children: act.items.map((r) => ({ label: r.label, note: `${r.count} jurnal`, values: vals(r) })) });
    });
    rows.push({ kind: 'subtotal', label: 'Perubahan kas', values: { net: t.net_change_in_cash } });
    rows.push({ kind: 'total', label: 'Kas akhir periode', values: { net: closing }, testId: 'cf-summary' });
  }

  return (
    <div className="space-y-4" data-testid="cf-page">
      <PageHeader
        title="Arus Kas"
        subtitle="Uang masuk dan keluar rekening kas/bank, dari buku besar."
        actions={
          <>
            <PeriodPicker value={period} onChange={setPeriod} testId="cf-period" />
            <Button variant="outline" size="icon" onClick={fetchData} title="Muat ulang" aria-label="Muat ulang" data-testid="cf-refresh"><RefreshCw className="w-4 h-4" /></Button>
            <Button variant="outline" onClick={exportCSV} disabled={!data} data-testid="cf-export"><Download className="w-4 h-4" />Unduh CSV</Button>
            <Button variant="outline" onClick={exportXlsx} disabled={!data} data-testid="cf-export-xlsx"><FileSpreadsheet className="w-4 h-4" />Unduh Excel</Button>
          </>
        }
      />

      <div className="flex items-center gap-3 flex-wrap">
        <FilterChips value={view} onChange={setView} testId="cf-view" ariaLabel="Tampilan" hideWhenEmpty={false}
          options={[{ key: 'account', label: 'Per kelompok akun' }, { key: 'category', label: 'Per jenis transaksi' }]} />
        {view === 'account' && ba && (
          <span className="text-xs text-muted-foreground">
            {ba.totals?.journals || 0} jurnal kas dikelompokkan menurut akun lawan (Operasi / Investasi / Pendanaan di Bagan Akun).
          </span>
        )}
      </div>

      {error && <GlassCard className="p-3 text-sm text-[hsl(var(--destructive))]" data-testid="cf-error">{error}</GlassCard>}

      {data && (
        <div className="grid grid-cols-3 gap-3">
          <StatTile label="Kas awal" value={fmt(opening)} testId="cf-kpi-open" />
          <StatTile label="Perubahan kas" value={fmt(Number(closing || 0) - Number(opening || 0))} accent={Number(closing) < Number(opening) ? 'danger' : 'default'} testId="cf-kpi-net" />
          <StatTile label="Kas akhir" value={fmt(closing)} testId="cf-kpi-closing" />
        </div>
      )}

      {loading ? (
        <Skeleton className="h-80 rounded-[var(--radius-lg)]" />
      ) : !data ? (
        <EmptyState icon={Wallet} title="Belum ada arus kas" description="Arus kas muncul setelah ada jurnal yang menyentuh rekening kas/bank." />
      ) : (
        <>
          <StatementTable testId={view === 'account' ? 'cf-by-account' : 'cf-by-category'} columns={COLS} rows={rows}
            labelHeader={`${formatDateID(from)} – ${formatDateID(to)}`} blankZeroChildren />
          {view === 'account' && Math.abs(ba?.totals?.unexplained || 0) > 0.5 && (
            <p className="text-sm text-[hsl(var(--destructive))]" data-testid="cf-acc-unexplained">
              Selisih {fmt(ba.totals.unexplained)} antara perubahan kas di buku besar dan jumlah per akun lawan — ada jurnal kas ke kas yang tidak seimbang.
            </p>
          )}
          {view === 'category' && data.cash_accounts?.length > 0 && (
            <GlassCard className="p-0 overflow-hidden" data-testid="cf-accounts">
              <div className="px-4 py-3 border-b border-[var(--glass-border)]">
                <h3 className="font-semibold text-sm text-foreground">Saldo rekening kas/bank saat ini</h3>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead><tr><th className="text-left">Rekening</th><th className="text-left">Jenis</th><th className="text-right">Saldo</th></tr></thead>
                  <tbody>
                    {data.cash_accounts.map((a) => (
                      <tr key={a.id}>
                        <td><span className="text-xs text-muted-foreground mr-2">{a.code}</span>{a.name}</td>
                        <td className="text-muted-foreground">{a.type === 'bank' ? 'Bank' : 'Kas'}</td>
                        <td className="text-right">{fmt(a.balance)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </GlassCard>
          )}
        </>
      )}
    </div>
  );
}

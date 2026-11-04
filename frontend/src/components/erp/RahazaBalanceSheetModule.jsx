import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Download, FileBarChart, CheckCircle2, AlertTriangle } from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { PageHeader, StatTile, EmptyState } from './moduleAtoms';
import { Skeleton } from '@/components/ui/skeleton';
import { todayWIB } from '@/lib/waktu';
import { formatDateID } from '@/lib/format';
import StatementTable from './finance/StatementTable';

const fmt = (n) => Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 0 });

/**
 * Neraca per tanggal (menu Laporan › Neraca).
 * 2026-11-04 (PANDUAN_UI G7): dua tabel laporan berdampingan (Aset | Liabilitas + Ekuitas) — dulu tiga
 * kartu dengan tabel tanpa judul kolom dan angka berhuruf mesin ketik berwarna-warni.
 */
export default function RahazaBalanceSheetModule({ token }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [asOf, setAsOf] = useState(todayWIB());
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchData = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const r = await fetch(`/api/rahaza/finance/reports/balance-sheet?as_of=${asOf}`, { headers });
      if (!r.ok) { setError(`Gagal memuat neraca (HTTP ${r.status})`); return; }
      setData(await r.json());
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, asOf]);
  useEffect(() => { fetchData(); }, [fetchData]);

  const exportCSV = () => {
    if (!data) return;
    const lines = [['Kelompok', 'Kode', 'Akun', 'Jumlah']];
    [['Aset', data.assets], ['Liabilitas', data.liabilities], ['Ekuitas', data.equity]].forEach(([label, sec]) => {
      (sec.accounts || []).forEach((a) => lines.push([label, a.code, a.name, a.amount]));
      lines.push([`Total ${label}`, '', '', sec.total]);
    });
    const csv = lines.map((r) => r.map((c) => (typeof c === 'string' && c.includes(',')) ? `"${c}"` : c).join(',')).join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url; link.download = `neraca-${asOf}.csv`; link.click();
    URL.revokeObjectURL(url);
  };

  const t = data?.totals || {};
  const grp = (id, label, sec) => ({
    kind: 'group', id, label, values: { amount: sec?.total },
    children: (sec?.accounts || []).map((a) => ({ code: a.code, label: a.name, note: a.computed ? '(laba berjalan)' : '', values: { amount: a.amount } })),
  });
  const col = [{ key: 'amount', label: `Per ${formatDateID(asOf)}` }];

  return (
    <div className="space-y-4" data-testid="bs-page">
      <PageHeader
        title="Neraca"
        subtitle="Posisi aset, liabilitas, dan ekuitas pada satu tanggal."
        actions={
          <>
            <span className="text-xs text-muted-foreground">Per tanggal</span>
            <GlassInput type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} className="h-9 w-40" data-testid="bs-as-of" />
            <Button variant="outline" size="icon" onClick={fetchData} title="Muat ulang" aria-label="Muat ulang" data-testid="bs-refresh"><RefreshCw className="w-4 h-4" /></Button>
            <Button variant="outline" onClick={exportCSV} disabled={!data} data-testid="bs-export"><Download className="w-4 h-4" />Unduh CSV</Button>
          </>
        }
      />

      {error && <GlassCard className="p-3 text-sm text-[hsl(var(--destructive))]" data-testid="bs-error">{error}</GlassCard>}
      {data && (
        <p className={`flex items-center gap-1.5 text-sm ${data.balanced ? 'text-muted-foreground' : 'text-[hsl(var(--destructive))] font-medium'}`} data-testid="bs-balanced">
          {data.balanced
            ? <><CheckCircle2 className="w-4 h-4 text-[hsl(var(--success))]" /> Seimbang: aset = liabilitas + ekuitas</>
            : <><AlertTriangle className="w-4 h-4" /> Tidak seimbang, selisih {fmt(t.diff)} — periksa jurnal tanpa akun neraca</>}
        </p>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatTile label="Total aset" value={fmt(t.assets)} testId="bs-kpi-assets" />
        <StatTile label="Total liabilitas" value={fmt(t.liabilities)} testId="bs-kpi-liab" />
        <StatTile label="Total ekuitas" value={fmt(t.equity)} testId="bs-kpi-equity" />
        <StatTile label={Number(t.current_earnings) >= 0 ? 'Laba tahun berjalan' : 'Rugi tahun berjalan'} value={fmt(t.current_earnings)} accent={Number(t.current_earnings) < 0 ? 'danger' : 'default'} testId="bs-kpi-earnings" />
      </div>

      {loading ? (
        <Skeleton className="h-80 rounded-[var(--radius-lg)]" />
      ) : !data ? (
        <EmptyState icon={FileBarChart} title="Belum ada neraca" description="Neraca muncul setelah ada jurnal atau saldo awal." />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
          <StatementTable testId="bs-assets" defaultOpen columns={col}
            rows={[grp('assets', 'Aset', data.assets), { kind: 'total', label: 'Total aset', values: { amount: data.assets.total } }]} />
          <StatementTable testId="bs-liab" defaultOpen columns={col}
            rows={[grp('liabilities', 'Liabilitas', data.liabilities), grp('equity', 'Ekuitas', data.equity),
              { kind: 'total', label: 'Total liabilitas + ekuitas', values: { amount: t.liab_plus_equity } }]} />
        </div>
      )}
    </div>
  );
}

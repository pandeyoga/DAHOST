import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Boxes, Download, BookCheck } from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { PageHeader, StatTile } from './moduleAtoms';
import { Skeleton } from '@/components/ui/skeleton';
import { todayWIB } from '@/lib/waktu';

const fmt = (n) => Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 0 });

export default function RahazaFGValuationModule({ token }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [asOf, setAsOf] = useState(todayWIB());
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`/api/rahaza/finance/reports/fg-inventory-valuation?as_of=${asOf}`, { headers });
      if (r.ok) setData(await r.json());
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, asOf]);
  useEffect(() => { fetchData(); }, [fetchData]);

  const exportCSV = () => {
    if (!data?.rows) return;
    const csv = [
      ['Kode', 'Nama', 'Stok Fisik', 'Qty Lapisan', 'Selisih Qty', 'WAC / pcs', 'Nilai WAC', 'Belum Berjurnal', 'Qty Tanpa Biaya'],
      ...data.rows.map(r => [r.code, r.name, r.stock_qty, r.layer_qty, r.qty_diff, r.avg_unit_cost, r.layer_value, r.unposted_value, r.uncosted_qty]),
    ].map(r => r.map(c => typeof c === 'string' && c.includes(',') ? `"${c}"` : c).join(',')).join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const a = document.createElement('a'); a.href = url; a.download = `nilai-persediaan-fg-${asOf}.csv`; a.click(); URL.revokeObjectURL(url);
  };

  const t = data?.totals || {};
  return (
    <div className="space-y-5" data-testid="rahaza-fgval-page">
      <PageHeader
        icon={Boxes}
        title="Nilai Persediaan Barang Jadi"
        subtitle="Stok barang jadi × harga rata-rata, dibandingkan saldo akun Persediaan Barang Jadi di buku besar."
        actions={
          <>
            <Button size="icon" variant="outline" onClick={fetchData} data-testid="fgval-refresh" title="Muat ulang" aria-label="Muat ulang"><RefreshCw className="w-3.5 h-3.5" /></Button>
            <Button variant="outline" onClick={exportCSV} disabled={!data?.rows?.length} data-testid="fgval-export"><Download className="w-3.5 h-3.5 mr-1.5" />Unduh CSV</Button>
          </>
        }
      />

      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-xs text-muted-foreground">Saldo buku besar per</span>
        <GlassInput type="date" value={asOf} onChange={e => setAsOf(e.target.value)} className="h-8 w-36" data-testid="fgval-asof" />
        <span className={`text-[10px] uppercase tracking-wider font-semibold px-2 py-0.5 rounded border ${data?.reconciled ? 'text-emerald-300 bg-emerald-400/10 border-emerald-400/25' : data?.explained ? 'text-amber-300 bg-amber-400/10 border-amber-400/25' : 'text-red-300 bg-red-400/10 border-red-400/25'}`} data-testid="fgval-status">
          {data?.reconciled ? 'Cocok dengan GL' : data?.explained ? 'Selisih terjelaskan (lapisan belum berjurnal)' : 'Selisih belum terjelaskan'}
        </span>
      </div>

      {(Number(t.layer_value) || Number(t.gl_balance) || Number(t.unposted_layers)) ? <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatTile label="Nilai persediaan (harga rata-rata)" value={`Rp ${fmt(t.layer_value)}`} accent="primary" testId="fgval-kpi-layer" />
        <StatTile label="Saldo buku besar" value={`Rp ${fmt(t.gl_balance)}`} testId="fgval-kpi-gl" />
        <StatTile label="Selisih" value={`Rp ${fmt(t.difference)}`} accent={Math.abs(t.difference || 0) < 1 ? 'success' : 'danger'} testId="fgval-kpi-diff" />
        <StatTile label="Belum dijurnal" value={`Rp ${fmt(t.unposted_value)} · ${t.unposted_layers || 0} lapisan`} accent={t.unposted_layers ? 'danger' : 'default'} testId="fgval-kpi-unposted" />
      </div> : null}

      {t.unposted_layers > 0 && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-sm text-amber-700 dark:text-amber-300" data-testid="fgval-unposted-hint">
          <BookCheck className="w-4 h-4 mt-0.5 shrink-0" />
          <span>{t.unposted_layers} lapisan barang jadi dari CMT belum dijurnal. Minta admin menjalankan
            “Jurnal WIP → Barang Jadi yang tertinggal” di Adm. Sistem › Perawatan Data Keuangan.</span>
        </div>
      )}

      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <div className="space-y-2 p-4">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
        ) : !data?.rows?.length ? (
          <div className="py-16 text-center text-muted-foreground text-sm" data-testid="fgval-empty">Belum ada lapisan HPP / stok FG internal.</div>
        ) : (
          <table className="w-full text-xs" data-testid="fgval-table">
            <thead className="bg-foreground/5 text-muted-foreground">
              <tr>
                <th className="text-left px-3 py-2">SKU</th>
                <th className="text-right px-3 py-2">Stok Fisik</th>
                <th className="text-right px-3 py-2">Qty Lapisan</th>
                <th className="text-right px-3 py-2">Selisih Qty</th>
                <th className="text-right px-3 py-2">WAC / pcs</th>
                <th className="text-right px-3 py-2">Nilai WAC</th>
                <th className="text-right px-3 py-2">Belum Berjurnal</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map(r => (
                <tr key={r.material_id} className="border-t border-foreground/5" data-testid={`fgval-row-${r.code}`}>
                  <td className="px-3 py-2"><div className="font-mono">{r.code}</div><div className="text-muted-foreground">{r.name}</div></td>
                  <td className="px-3 py-2 text-right">{fmt(r.stock_qty)}</td>
                  <td className="px-3 py-2 text-right">{fmt(r.layer_qty)}{r.uncosted_qty > 0 && <div className="text-[10px] text-amber-300">{fmt(r.uncosted_qty)} tanpa biaya</div>}</td>
                  <td className={`px-3 py-2 text-right ${r.qty_diff ? 'text-amber-300' : ''}`}>{fmt(r.qty_diff)}</td>
                  <td className="px-3 py-2 text-right">Rp {fmt(r.avg_unit_cost)}</td>
                  <td className="px-3 py-2 text-right font-semibold">Rp {fmt(r.layer_value)}</td>
                  <td className={`px-3 py-2 text-right ${r.unposted_value ? 'text-red-300' : 'text-muted-foreground'}`}>Rp {fmt(r.unposted_value)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot className="bg-foreground/5 font-semibold">
              <tr>
                <td className="px-3 py-2">Total</td>
                <td className="px-3 py-2 text-right">{fmt(t.stock_qty)}</td>
                <td className="px-3 py-2 text-right">{fmt(t.layer_qty)}</td>
                <td className="px-3 py-2 text-right">{fmt((t.stock_qty || 0) - (t.layer_qty || 0))}</td>
                <td className="px-3 py-2" />
                <td className="px-3 py-2 text-right">Rp {fmt(t.layer_value)}</td>
                <td className="px-3 py-2 text-right">Rp {fmt(t.unposted_value)}</td>
              </tr>
            </tfoot>
          </table>
        )}
      </GlassCard>
    </div>
  );
}

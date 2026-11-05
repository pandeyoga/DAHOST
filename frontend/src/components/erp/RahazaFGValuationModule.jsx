import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Boxes, Download, BookCheck } from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { StatTile, StatusBadge, EmptyState } from './moduleAtoms';
import PageLayout from './layout/PageLayout';
import { Skeleton } from '@/components/ui/skeleton';
import { todayWIB } from '@/lib/waktu';

const fmt = (n) => Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 0 });

/**
 * Nilai Persediaan Barang Jadi (stok × harga rata-rata vs saldo buku besar).
 * 2026-11-05 (PANDUAN_UI G1/G7/G8): cetakan PageLayout; status rekonsiliasi memakai StatusBadge (dulu pil warna
 * palet langsung); angka uang tidak dipatah ke 2 baris; label tanpa singkatan teknis (WAC, GL, SKU).
 */
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
      ['Kode', 'Nama', 'Stok fisik', 'Qty lapisan', 'Selisih qty', 'Harga rata-rata / pcs', 'Nilai', 'Belum dijurnal', 'Qty tanpa biaya'],
      ...data.rows.map(r => [r.code, r.name, r.stock_qty, r.layer_qty, r.qty_diff, r.avg_unit_cost, r.layer_value, r.unposted_value, r.uncosted_qty]),
    ].map(r => r.map(c => typeof c === 'string' && c.includes(',') ? `"${c}"` : c).join(',')).join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const a = document.createElement('a'); a.href = url; a.download = `nilai-persediaan-fg-${asOf}.csv`; a.click(); URL.revokeObjectURL(url);
  };

  const t = data?.totals || {};
  const hasTotals = !!(Number(t.layer_value) || Number(t.gl_balance) || Number(t.unposted_layers));
  const status = data?.reconciled
    ? { tone: 'success', label: 'Cocok dengan buku besar' }
    : data?.explained
      ? { tone: 'warning', label: 'Selisih terjelaskan (lapisan belum dijurnal)' }
      : { tone: 'danger', label: 'Selisih belum terjelaskan' };
  const num = 'px-3 py-2 text-right tabular-nums whitespace-nowrap';

  return (
    <PageLayout
      testId="rahaza-fgval-page"
      title="Nilai Persediaan Barang Jadi"
      subtitle="Stok barang jadi × harga rata-rata, dibandingkan saldo buku besar."
      filters={<>
        <span className="text-sm text-muted-foreground">Saldo buku besar per</span>
        <GlassInput type="date" value={asOf} onChange={e => setAsOf(e.target.value)} className="h-9 w-40" aria-label="Saldo buku besar per tanggal" data-testid="fgval-asof" />
        {data && <StatusBadge tone={status.tone} label={status.label} testId="fgval-status" />}
      </>}
      tools={<>
        <Button size="icon" variant="outline" onClick={fetchData} data-testid="fgval-refresh" title="Muat ulang" aria-label="Muat ulang"><RefreshCw className="w-4 h-4" /></Button>
        <Button variant="outline" onClick={exportCSV} disabled={!data?.rows?.length} data-testid="fgval-export"><Download className="w-4 h-4" />Unduh CSV</Button>
      </>}
      summary={<>
        {hasTotals && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatTile label="Nilai persediaan (harga rata-rata)" value={`Rp ${fmt(t.layer_value)}`} testId="fgval-kpi-layer" />
            <StatTile label="Saldo buku besar" value={`Rp ${fmt(t.gl_balance)}`} testId="fgval-kpi-gl" />
            <StatTile label="Selisih" value={`Rp ${fmt(t.difference)}`} accent={Math.abs(t.difference || 0) < 1 ? 'success' : 'danger'} testId="fgval-kpi-diff" />
            <StatTile label="Belum dijurnal" value={`Rp ${fmt(t.unposted_value)} · ${t.unposted_layers || 0} lapisan`} accent={t.unposted_layers ? 'danger' : 'default'} testId="fgval-kpi-unposted" />
          </div>
        )}
        {t.unposted_layers > 0 && (
          <p className="flex items-start gap-2 text-sm text-[hsl(var(--warning))]" data-testid="fgval-unposted-hint">
            <BookCheck className="w-4 h-4 mt-0.5 shrink-0" />
            <span>{t.unposted_layers} lapisan barang jadi dari CMT belum dijurnal. Minta admin menjalankan
              “Jurnal WIP → Barang Jadi yang tertinggal” di Adm. Sistem › Perawatan Data Keuangan.</span>
          </p>
        )}
      </>}
    >
      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <div className="space-y-2 p-4">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
        ) : !data?.rows?.length ? (
          <EmptyState icon={Boxes} testId="fgval-empty" title="Belum ada stok barang jadi internal"
            description="Nilai persediaan muncul setelah ada barang jadi dengan lapisan HPP." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs" data-testid="fgval-table">
              <thead>
                <tr>
                  <th className="text-left px-3 py-2">Barang</th>
                  <th className="text-right px-3 py-2">Stok fisik</th>
                  <th className="text-right px-3 py-2">Qty lapisan</th>
                  <th className="text-right px-3 py-2">Selisih qty</th>
                  <th className="text-right px-3 py-2">Harga rata-rata / pcs</th>
                  <th className="text-right px-3 py-2">Nilai</th>
                  <th className="text-right px-3 py-2">Belum dijurnal</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map(r => (
                  <tr key={r.material_id} className="border-t border-foreground/5" data-testid={`fgval-row-${r.code}`}>
                    <td className="px-3 py-2"><div className="text-muted-foreground whitespace-nowrap">{r.code}</div><div>{r.name}</div></td>
                    <td className={num}>{fmt(r.stock_qty)}</td>
                    <td className={num}>{fmt(r.layer_qty)}{r.uncosted_qty > 0 && <div className="text-[10px] text-[hsl(var(--warning))]">{fmt(r.uncosted_qty)} tanpa biaya</div>}</td>
                    <td className={`${num} ${r.qty_diff ? 'text-[hsl(var(--warning))]' : ''}`}>{fmt(r.qty_diff)}</td>
                    <td className={num}>Rp {fmt(r.avg_unit_cost)}</td>
                    <td className={`${num} font-semibold`}>Rp {fmt(r.layer_value)}</td>
                    <td className={`${num} ${r.unposted_value ? 'text-[hsl(var(--destructive))]' : 'text-muted-foreground'}`}>Rp {fmt(r.unposted_value)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot className="font-semibold">
                <tr className="border-t-2 border-[var(--glass-border)]">
                  <td className="px-3 py-2">Total</td>
                  <td className={num}>{fmt(t.stock_qty)}</td>
                  <td className={num}>{fmt(t.layer_qty)}</td>
                  <td className={num}>{fmt((t.stock_qty || 0) - (t.layer_qty || 0))}</td>
                  <td className="px-3 py-2" />
                  <td className={num}>Rp {fmt(t.layer_value)}</td>
                  <td className={num}>Rp {fmt(t.unposted_value)}</td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </GlassCard>
    </PageLayout>
  );
}

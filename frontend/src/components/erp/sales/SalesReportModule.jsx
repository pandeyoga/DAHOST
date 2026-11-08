/**
 * Laporan Penjualan (Portal Penjualan).
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout · penyaring satu baris (kelompok + PeriodPicker standar, dulu kotak
 * tanggal bawaan peramban) · 4 kartu StatTile · tabel standar + baris total · unduh Excel/CSV (kolom & baris total
 * sama dengan CSV server yang dulu dipakai tombol "Export CSV").
 * Penjualan bersih = bruto − diskon − retur (tanpa PPN). Sumber: GET /api/sales/report.
 */
import { useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import PeriodPicker, { periodFromPreset } from '../finance/PeriodPicker';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatTile } from '../moduleAtoms';
import { apiGet } from '../../../lib/api';

const fmt = (n) => `Rp ${Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 0 })}`;
const angka = (n) => Number(n || 0).toLocaleString('id-ID');
const GROUPS = [['customer', 'Per pelanggan'], ['sku', 'Per SKU'], ['day', 'Per hari'], ['month', 'Per bulan']];
const HEAD = { customer: 'Pelanggan', sku: 'SKU', day: 'Tanggal', month: 'Bulan' };

export default function SalesReportModule() {
  const [group, setGroup] = useState('customer');
  const [period, setPeriod] = useState(() => periodFromPreset('month'));
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(false);
  const from = period.from;
  const to = period.to;
  const qs = `group_by=${group}&date_from=${from}&date_to=${to}`;
  const load = async () => { setBusy(true); try { setD(await apiGet(`/sales/report?${qs}`)); } catch (e) { toast.error(e.message); } finally { setBusy(false); } };
  useEffect(() => { load(); }, [group, from, to]); // eslint-disable-line react-hooks/exhaustive-deps
  const t = d?.totals;
  const rows = d?.rows || [];
  const head = HEAD[group];
  // Baris unduhan = baris tabel + baris TOTAL (sama dengan CSV server).
  const barisUnduh = rows.length && t ? [...rows, { ...t, label: 'TOTAL', key: '__total' }] : rows;

  return (
    <PageLayout testId="sales-report" title="Laporan Penjualan"
      subtitle="Penjualan bersih = bruto − diskon − retur (tanpa PPN); HPP sudah dikurangi HPP barang retur."
      filters={<>
        <SmartNativeSelect value={group} onChange={(e) => setGroup(e.target.value)} searchable={false}
          className="h-9 w-44" wrapperClassName="w-44" aria-label="Kelompokkan" data-testid="report-group-tabs">
          {GROUPS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </SmartNativeSelect>
        <PeriodPicker value={period} onChange={setPeriod} testId="report-period" />
      </>}
      tools={<>
        <TombolUnduh namaBerkas={`laporan-penjualan-${group}-${from}-${to}`} namaLembar="Laporan penjualan" baris={barisUnduh}
          testId="report-export"
          kolom={[
            { label: head, nilai: (r) => r.label }, { label: 'Nota', nilai: (r) => Number(r.notes || 0) },
            { label: 'Qty', nilai: (r) => Number(r.qty || 0) }, { label: 'Bruto', nilai: (r) => Number(r.gross || 0) },
            { label: 'Diskon', nilai: (r) => Number(r.discount || 0) }, { label: 'PPN', nilai: (r) => Number(r.tax || 0) },
            { label: 'Retur', nilai: (r) => Number(r.returns || 0) }, { label: 'Penjualan bersih', nilai: (r) => Number(r.net_sales || 0) },
            { label: 'HPP', nilai: (r) => Number(r.cogs || 0) }, { label: 'Laba kotor', nilai: (r) => Number(r.margin || 0) },
            { label: 'Margin %', nilai: (r) => Number(r.margin_pct || 0) }, { label: 'Qty retur', nilai: (r) => Number(r.return_qty || 0) },
          ]} />
        <Button variant="outline" size="icon" onClick={load} disabled={busy} title="Muat ulang" aria-label="Muat ulang"
          data-testid="report-refresh">
          <RefreshCw className={busy ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Nota" value={t ? angka(t.notes) : '—'} testId="report-kpi-notes"
            sub={`${angka(t?.qty)} pcs · retur ${angka(t?.return_qty)} pcs`} />
          <StatTile label="Penjualan bersih" value={fmt(t?.net_sales)} accent="primary" testId="report-kpi-net"
            sub={`Bruto ${fmt(t?.gross)} · PPN ${fmt(t?.tax)} (tidak termasuk)`} />
          <StatTile label="Diskon + retur" value={fmt((t?.discount || 0) + (t?.returns || 0))} testId="report-kpi-deductions"
            sub={`Diskon ${fmt(t?.discount)} · retur ${fmt(t?.returns)}`} />
          <StatTile label="Laba kotor" value={fmt(t?.margin)} accent={(t?.margin || 0) >= 0 ? 'success' : 'danger'} testId="report-kpi-margin"
            sub={`HPP ${fmt(t?.cogs)} · margin ${t?.margin_pct || 0}%`} />
        </div>
      }>
      {busy && !d ? (
        <div className="space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
      ) : (
        <div className="overflow-x-auto">
          <Table data-testid="report-table">
            <TableHeader><TableRow>
              <TableHead>{head}</TableHead><TableHead className="text-right">Nota</TableHead><TableHead className="text-right">Qty</TableHead>
              <TableHead className="text-right">Bruto</TableHead><TableHead className="text-right">Diskon</TableHead>
              <TableHead className="text-right">Retur</TableHead><TableHead className="text-right">Bersih</TableHead>
              <TableHead className="text-right">HPP</TableHead><TableHead className="text-right">Laba kotor</TableHead>
              <TableHead className="text-right">Margin</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {!rows.length && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={10} className="p-0 [&>div]:py-8"><EmptyState testId="report-empty" title="Tidak ada penjualan pada rentang ini" description="Ubah periode atau kelompok laporan." /></TableCell>
                </TableRow>
              )}
              {rows.map((r) => (
                <TableRow key={r.key} data-testid={`report-row-${r.key}`}>
                  <TableCell className="font-medium">{r.label}</TableCell>
                  <TableCell className="text-right tabular-nums">{angka(r.notes)}</TableCell>
                  <TableCell className="text-right tabular-nums">{angka(r.qty)}{r.return_qty
                    ? <span className="text-[hsl(var(--warning-text))]"> (−{angka(r.return_qty)})</span> : ''}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">{fmt(r.gross)}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">{fmt(r.discount)}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">{fmt(r.returns)}</TableCell>
                  <TableCell className="text-right font-semibold tabular-nums whitespace-nowrap">{fmt(r.net_sales)}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">{fmt(r.cogs)}</TableCell>
                  <TableCell className="text-right font-semibold tabular-nums whitespace-nowrap">{fmt(r.margin)}</TableCell>
                  <TableCell className="text-right tabular-nums">{r.margin_pct}%</TableCell>
                </TableRow>
              ))}
            </TableBody>
            {t && rows.length > 0 && (
            <TableFooter>
              <TableRow data-testid="report-total-row">
                <TableCell>Total</TableCell>
                <TableCell className="text-right tabular-nums">{angka(t.notes)}</TableCell>
                <TableCell className="text-right tabular-nums">{angka(t.qty)}</TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap">{fmt(t.gross)}</TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap">{fmt(t.discount)}</TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap">{fmt(t.returns)}</TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap">{fmt(t.net_sales)}</TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap">{fmt(t.cogs)}</TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap">{fmt(t.margin)}</TableCell>
                <TableCell className="text-right tabular-nums">{t.margin_pct}%</TableCell>
              </TableRow>
            </TableFooter>
            )}
          </Table>
        </div>
      )}
    </PageLayout>
  );
}

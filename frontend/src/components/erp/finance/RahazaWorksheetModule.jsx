import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, FileBarChart, CheckCircle2, AlertTriangle } from 'lucide-react';
import { Checkbox } from '@/components/ui/checkbox';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PeriodPicker, { periodFromPreset } from './PeriodPicker';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { toast } from 'sonner';
import { EmptyState } from '../moduleAtoms';
import PageLayout from '../layout/PageLayout';
import { fmt, fmtCell, authHeaders } from './reportShared';

const COLS = ['opening_debit', 'opening_credit', 'period_debit', 'period_credit', 'end_debit', 'end_credit', 'pl_debit', 'pl_credit', 'bs_debit', 'bs_credit'];
const HEAD = [['Saldo awal', 2], ['Mutasi', 2], ['Saldo akhir', 2], ['Laba rugi', 2], ['Neraca', 2]];
const tdN = 'text-right tabular-nums whitespace-nowrap';
const sentence = (s) => (s ? s.charAt(0) + s.slice(1).toLowerCase() : s);

/**
 * Buku Besar › Neraca lajur (kertas kerja 10 kolom seperti sheet N-Lajur).
 * 2026-11-05 (PANDUAN_UI G1/G7): cetakan PageLayout; angka tanpa huruf mesin ketik dan tanpa warna palet; tabel
 * tidak lagi bergulir di wadah setinggi 70% layar (baris total tertutup tombol chat).
 * 2026-11-08 (Standar UI/UX v2): unduh Excel & CSV (isi = tabel ini termasuk baris jumlah); 4 kartu yang mengulang
 * baris tabel diganti satu kalimat; kotak centang aplikasi.
 */
export default function RahazaWorksheetModule({ token }) {
  // PANDUAN_UI G6 (2026-11-04): pemilih periode standar (dulu dua kotak tanggal)
  const [period, setPeriod] = useState(() => periodFromPreset('ytd'));
  const { from, to } = period;
  const [showZero, setShowZero] = useState(false);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const q = new URLSearchParams({ from, to, show_zero: showZero ? 'true' : 'false' });
      const r = await fetch(`/api/rahaza/finance/reports/worksheet?${q}`, { headers: authHeaders(token) });
      if (r.ok) setData(await r.json()); else toast.error(`Gagal memuat (HTTP ${r.status})`);
    } finally { setLoading(false); }
  }, [token, from, to, showZero]);
  useEffect(() => { fetchData(); }, [fetchData]);

  const t = data?.totals || {};
  const b = data?.balancing || {};
  const g = data?.grand_totals || {};
  const netLabel = sentence(b.label) || 'Laba bersih';
  const hasRows = !!data?.rows?.length;

  return (
    <PageLayout
      testId="worksheet-page"
      title="Neraca lajur"
      subtitle="Saldo awal · mutasi · saldo akhir, lalu tiap akun dipisah ke kolom laba rugi atau neraca."
      filters={<>
        <PeriodPicker value={period} onChange={setPeriod} testId="ws-period" />
        <label className="inline-flex items-center gap-2 text-sm text-foreground/80">
          <Checkbox checked={showZero} onCheckedChange={(v) => setShowZero(!!v)} data-testid="ws-show-zero" />
          Tampilkan akun saldo 0
        </label>
      </>}
      tools={<>
        <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={fetchData} data-testid="ws-refresh"><RefreshCw className="w-4 h-4" /></Button>
        <TombolUnduh namaBerkas={`neraca-lajur-${from}-${to}`} namaLembar="Neraca lajur" testId="ws-export"
          baris={hasRows ? [...data.rows,
            { code: '', name: 'Jumlah', ...t },
            { code: '', name: netLabel, pl_debit: b.pl_debit, pl_credit: b.pl_credit, bs_debit: b.bs_debit, bs_credit: b.bs_credit },
            { code: '', name: 'Total', pl_debit: g.pl_debit, pl_credit: g.pl_credit, bs_debit: g.bs_debit, bs_credit: g.bs_credit }] : []}
          kolom={[
            { label: 'Kode', nilai: (r) => r.code },
            { label: 'Akun', nilai: (r) => r.name },
            { label: 'Laporan', nilai: (r) => (r.statement ? (r.statement === 'pl' ? 'Laba rugi' : 'Neraca') : '') },
            ...[['opening', 'Saldo awal'], ['period', 'Mutasi'], ['end', 'Saldo akhir'], ['pl', 'Laba rugi'], ['bs', 'Neraca']].flatMap(([k, l]) => [
              { label: `${l} debit`, nilai: (r) => (r[`${k}_debit`] === undefined ? '' : Number(r[`${k}_debit`]) || 0) },
              { label: `${l} kredit`, nilai: (r) => (r[`${k}_credit`] === undefined ? '' : Number(r[`${k}_credit`]) || 0) },
            ]),
          ]} />
      </>}
      summary={hasRows && <>
        <p className={`flex items-center gap-1.5 text-sm ${data.balanced ? 'text-muted-foreground' : 'text-[hsl(var(--danger-text))] font-medium'}`} data-testid="ws-balanced">
          {data.balanced
            ? <><CheckCircle2 className="w-4 h-4 shrink-0 text-[hsl(var(--success-text))]" />
                <span>Seimbang: mutasi debit = kredit <b className="text-foreground tabular-nums" data-testid="ws-kpi-pd">{fmt(t.period_debit)}</b>
                {' '}· {netLabel.toLowerCase()} <b className={`tabular-nums ${(b.net_income || 0) < 0 ? 'text-[hsl(var(--danger-text))]' : 'text-foreground'}`} data-testid="ws-kpi-net">{fmt(b.net_income)}</b>
                <span className="hidden sm:inline">{' '}menyeimbangkan kolom laba rugi dan neraca · total neraca <b className="text-foreground tabular-nums" data-testid="ws-kpi-bs">{fmt(g.bs_debit)}</b></span></span></>
            : <><AlertTriangle className="w-4 h-4 shrink-0" /> Tidak seimbang — periksa jurnal yang debit dan kreditnya berbeda</>}
        </p>
      </>}
    >
      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <div className="space-y-2 p-4">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
        ) : !hasRows ? (
          <EmptyState icon={FileBarChart} testId="ws-empty" title="Tidak ada data pada periode ini"
            description="Ubah periode atau centang “Tampilkan akun saldo 0”." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="ws-table">
              <thead>
                <tr>
                  <th rowSpan={2} className="text-left">Kode</th>
                  <th rowSpan={2} className="text-left">Akun</th>
                  {HEAD.map(([l, span]) => <th key={l} colSpan={span} className="text-center border-l border-[var(--glass-border)]">{l}</th>)}
                </tr>
                <tr>
                  {HEAD.map(([l]) => [<th key={`${l}-d`} className="text-right border-l border-[var(--glass-border)]">Debit</th>, <th key={`${l}-k`} className="text-right">Kredit</th>])}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.code} className="border-b border-[var(--glass-border)] hover:bg-foreground/5" data-testid={`ws-row-${r.code}`}>
                    <td className="whitespace-nowrap text-muted-foreground">{r.code}</td>
                    <td className="whitespace-nowrap">{r.name} <span className="text-xs text-muted-foreground ml-1">{r.statement === 'pl' ? 'laba rugi' : 'neraca'}</span></td>
                    {COLS.map((c, i) => <td key={c} className={`${tdN} ${i % 2 === 0 ? 'border-l border-[var(--glass-border)]' : ''}`}>{fmtCell(r[c])}</td>)}
                  </tr>
                ))}
                <tr className="font-semibold border-t-2 border-[var(--glass-border)]" data-testid="ws-totals">
                  <td colSpan={2}>Jumlah</td>
                  {COLS.map((c, i) => <td key={c} className={`${tdN} ${i % 2 === 0 ? 'border-l border-[var(--glass-border)]' : ''}`}>{fmt(t[c])}</td>)}
                </tr>
                <tr data-testid="ws-balancing">
                  <td colSpan={2} className={(b.net_income || 0) < 0 ? 'text-[hsl(var(--danger-text))]' : ''}>{netLabel}</td>
                  {COLS.slice(0, 6).map((c, i) => <td key={c} className={`${tdN} ${i % 2 === 0 ? 'border-l border-[var(--glass-border)]' : ''}`} />)}
                  {['pl_debit', 'pl_credit', 'bs_debit', 'bs_credit'].map((c, i) => <td key={c} className={`${tdN} font-semibold ${i % 2 === 0 ? 'border-l border-[var(--glass-border)]' : ''}`}>{fmtCell(b[c])}</td>)}
                </tr>
                <tr className="font-bold border-t-[3px] border-double border-[var(--glass-border)]" data-testid="ws-grand">
                  <td colSpan={2}>Total</td>
                  {COLS.slice(0, 6).map((c, i) => <td key={c} className={`${tdN} ${i % 2 === 0 ? 'border-l border-[var(--glass-border)]' : ''}`} />)}
                  {['pl_debit', 'pl_credit', 'bs_debit', 'bs_credit'].map((c, i) => <td key={c} className={`${tdN} ${i % 2 === 0 ? 'border-l border-[var(--glass-border)]' : ''}`}>{fmt(g[c])}</td>)}
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
    </PageLayout>
  );
}

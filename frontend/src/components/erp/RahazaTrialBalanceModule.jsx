import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, FileBarChart, Search, CheckCircle2, AlertTriangle } from 'lucide-react';
import PeriodPicker, { periodFromPreset } from './finance/PeriodPicker';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Checkbox } from '@/components/ui/checkbox';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { EmptyState } from './moduleAtoms';
import PageLayout from './layout/PageLayout';
import { TYPE_LABELS, TYPE_ORDER } from './RahazaCOATreeNode';
import { Skeleton } from '@/components/ui/skeleton';

const fmt = (n) => Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 2 });
const HEAD = [['Saldo awal', 'opening'], ['Mutasi', 'period'], ['Saldo akhir', 'end']];

/**
 * Buku Besar › Saldo semua akun (neraca saldo).
 * 2026-11-05 (PANDUAN_UI G1/G7/G11): cetakan PageLayout; label Indonesia (dulu "Trial Balance", "Period Debit",
 * "UNBALANCED!", tipe akun berkode ASSET); angka tanpa huruf mesin ketik dan tanpa warna hijau/biru; tabel tidak
 * lagi bergulir di wadah setinggi 600 px (baris total tertutup tombol chat).
 * 2026-11-08 (Standar UI/UX v2): unduh Excel/CSV (isi = baris yang tampil); 4 kartu yang mengulang baris Total diganti
 * kalimat; baris Total mengikuti saringan tipe/cari (dulu tetap total SEMUA akun walau daftar disaring — menyesatkan).
 */
export default function RahazaTrialBalanceModule({ token }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  // PANDUAN_UI G6 (2026-11-04): pemilih periode standar (dulu dua kotak tanggal)
  const [period, setPeriod] = useState(() => periodFromPreset('month'));
  const { from, to } = period;
  const [showZero, setShowZero] = useState(false);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ from, to, show_zero: showZero ? 'true' : 'false' });
      const r = await fetch(`/api/rahaza/finance/reports/trial-balance?${params}`, { headers });
      if (r.ok) setData(await r.json());
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, from, to, showZero]);
  useEffect(() => { fetchData(); }, [fetchData]);

  const filtered = (data?.rows || []).filter(r => {
    if (typeFilter && r.type !== typeFilter) return false;
    if (!search) return true;
    const s = search.toLowerCase();
    return r.code.toLowerCase().includes(s) || r.name.toLowerCase().includes(s);
  });
  const disaring = !!(typeFilter || search);
  const KUNCI = ['opening_debit', 'opening_credit', 'period_debit', 'period_credit', 'end_debit', 'end_credit'];
  const tot = disaring
    ? Object.fromEntries(KUNCI.map((k) => [k, filtered.reduce((a, r) => a + Number(r[k] || 0), 0)]))
    : (data?.totals || {});
  const totSemua = data?.totals || {};
  const cell = (v) => (v ? fmt(v) : '');

  return (
    <PageLayout
      testId="rahaza-tb-page"
      title="Saldo semua akun"
      subtitle="Saldo awal, mutasi, dan saldo akhir tiap akun. Total debit harus sama dengan total kredit."
      filters={<>
        <PeriodPicker value={period} onChange={setPeriod} testId="tb-period" />
        <SmartNativeSelect value={typeFilter} onChange={e => setTypeFilter(e.target.value)} searchable={false}
          className="h-9 w-44" aria-label="Tipe akun" data-testid="tb-type">
          <option value="">Semua tipe</option>
          {TYPE_ORDER.map((k) => <option key={k} value={k}>{TYPE_LABELS[k]}</option>)}
        </SmartNativeSelect>
        <div className="relative w-full sm:w-64">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <GlassInput value={search} onChange={e => setSearch(e.target.value)} placeholder="Cari kode / nama akun…" className="pl-9 h-9" data-testid="tb-search" />
        </div>
        <label className="inline-flex items-center gap-2 text-sm text-foreground/80">
          <Checkbox checked={showZero} onCheckedChange={(v) => setShowZero(!!v)} data-testid="tb-show-zero" />
          Tampilkan akun saldo 0
        </label>
      </>}
      tools={<>
        <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={fetchData} data-testid="tb-refresh"><RefreshCw className="w-4 h-4" /></Button>
        <TombolUnduh namaBerkas={`saldo-semua-akun-${from}-${to}`} namaLembar="Saldo akun" baris={filtered} testId="tb-export"
          kolom={[
            { label: 'Kode', nilai: (r) => r.code },
            { label: 'Akun', nilai: (r) => r.name },
            { label: 'Tipe', nilai: (r) => TYPE_LABELS[r.type] || r.type },
            { label: 'Saldo awal debit', nilai: (r) => Number(r.opening_debit) || 0 },
            { label: 'Saldo awal kredit', nilai: (r) => Number(r.opening_credit) || 0 },
            { label: 'Mutasi debit', nilai: (r) => Number(r.period_debit) || 0 },
            { label: 'Mutasi kredit', nilai: (r) => Number(r.period_credit) || 0 },
            { label: 'Saldo akhir debit', nilai: (r) => Number(r.end_debit) || 0 },
            { label: 'Saldo akhir kredit', nilai: (r) => Number(r.end_credit) || 0 },
          ]} />
      </>}
      summary={data?.totals && data.rows?.length > 0 && <>
        <p className={`flex items-center gap-1.5 text-sm ${data.balanced ? 'text-muted-foreground' : 'text-[hsl(var(--danger-text))] font-medium'}`} data-testid="tb-balanced">
          {data.balanced
            ? <><CheckCircle2 className="w-4 h-4 shrink-0 text-[hsl(var(--success-text))]" />
                <span>Seimbang (semua akun): mutasi debit = kredit <b className="text-foreground tabular-nums" data-testid="tb-kpi-pd">{fmt(totSemua.period_debit)}</b>
                <span className="hidden sm:inline">{' '}· saldo akhir debit = kredit <b className="text-foreground tabular-nums" data-testid="tb-kpi-ed">{fmt(totSemua.end_debit)}</b></span></span></>
            : <><AlertTriangle className="w-4 h-4 shrink-0" /> Tidak seimbang — saldo akhir debit {fmt(totSemua.end_debit)} ≠ kredit {fmt(totSemua.end_credit)}</>}
        </p>
      </>}
    >
      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <div className="space-y-2 p-4">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-12 rounded-lg" />)}</div>
        ) : filtered.length === 0 ? (
          <EmptyState icon={FileBarChart} title="Tidak ada akun yang cocok"
            description="Ubah periode, pencarian, atau centang “Tampilkan akun saldo 0”." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="tb-table">
              <thead>
                <tr>
                  <th rowSpan={2} className="text-left">Kode</th>
                  <th rowSpan={2} className="text-left">Akun</th>
                  <th rowSpan={2} className="text-left">Tipe</th>
                  {HEAD.map(([l]) => <th key={l} colSpan={2} className="text-center border-l border-[var(--glass-border)]">{l}</th>)}
                </tr>
                <tr>
                  {HEAD.map(([l]) => [
                    <th key={`${l}-d`} className="text-right border-l border-[var(--glass-border)]">Debit</th>,
                    <th key={`${l}-k`} className="text-right">Kredit</th>,
                  ])}
                </tr>
              </thead>
              <tbody>
                {filtered.map(r => (
                  <tr key={r.code} className="border-b border-[var(--glass-border)] hover:bg-foreground/5" data-testid={`tb-row-${r.code}`}>
                    <td className="whitespace-nowrap text-muted-foreground">{r.code}</td>
                    <td>{r.name}</td>
                    <td className="whitespace-nowrap text-muted-foreground">{TYPE_LABELS[r.type] || r.type}</td>
                    <td className="text-right tabular-nums border-l border-[var(--glass-border)]">{cell(r.opening_debit)}</td>
                    <td className="text-right tabular-nums">{cell(r.opening_credit)}</td>
                    <td className="text-right tabular-nums border-l border-[var(--glass-border)]">{cell(r.period_debit)}</td>
                    <td className="text-right tabular-nums">{cell(r.period_credit)}</td>
                    <td className="text-right tabular-nums font-semibold border-l border-[var(--glass-border)]">{cell(r.end_debit)}</td>
                    <td className="text-right tabular-nums font-semibold">{cell(r.end_credit)}</td>
                  </tr>
                ))}
                {data?.totals && (
                  <tr className="font-semibold border-t-2 border-[var(--glass-border)]" data-testid="tb-totals">
                    <td colSpan={3}>{disaring ? `Total ${filtered.length} akun yang tampil` : 'Total'}</td>
                    <td className="text-right tabular-nums border-l border-[var(--glass-border)]">{fmt(tot.opening_debit)}</td>
                    <td className="text-right tabular-nums">{fmt(tot.opening_credit)}</td>
                    <td className="text-right tabular-nums border-l border-[var(--glass-border)]">{fmt(tot.period_debit)}</td>
                    <td className="text-right tabular-nums">{fmt(tot.period_credit)}</td>
                    <td className="text-right tabular-nums border-l border-[var(--glass-border)]">{fmt(tot.end_debit)}</td>
                    <td className="text-right tabular-nums">{fmt(tot.end_credit)}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
    </PageLayout>
  );
}

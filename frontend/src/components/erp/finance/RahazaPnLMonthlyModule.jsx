import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, FileBarChart } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { toast } from 'sonner';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { EmptyState } from '../moduleAtoms';
import PageLayout from '../layout/PageLayout';
import IntercompanyNotes from './IntercompanyNotes';
import StatementTable, { unduhanLaporan } from './StatementTable';
import { fmt, authHeaders, yearOptions } from './reportShared';

const GROUPS = ['revenue', 'cogs', 'expense', 'other_income', 'other_expense'];
// Sama dengan tab "Total periode": HPP & beban ditulis minus supaya alurnya terbaca.
const SIGN = { revenue: 1, cogs: -1, expense: -1, other_income: 1, other_expense: -1 };
// Kolom akun tetap terlihat saat tabel 13 kolom digulir ke samping. Latar = permukaan kartu di atas latar
// halaman (tema gelap: kartu tembus pandang, angka yang bergulir tidak boleh terlihat di balik nama akun).
const STICKY_LABEL = '[&_tr>:first-child]:sticky [&_tr>:first-child]:left-0 [&_tr>:first-child]:z-[1] [&_tr>:first-child]:whitespace-nowrap '
  + '[&_tr>:first-child]:[background:linear-gradient(var(--card-surface),var(--card-surface)),hsl(var(--background))]';

/**
 * Laba Rugi › Per bulan (Jan–Des, total tahun, akumulasi).
 * 2026-11-05 (PANDUAN_UI G1/G7): cetakan PageLayout dan tabel laporan yang sama dengan tab "Total periode"
 * (StatementTable). Dulu tabel sendiri berhuruf mesin ketik, judul baris KAPITAL, warna palet langsung, dan
 * wadah bergulir setinggi 70% layar sehingga baris terakhir tertutup tombol chat.
 * 2026-11-08 (Standar UI/UX v2): unduh Excel & CSV (TombolUnduh, isi = tabel ini); 4 kartu yang mengulang kolom
 * Total diganti satu kalimat (angka sama); pilihan tahun dilebarkan (dulu "Tahun 2026" terpotong).
 */
export default function RahazaPnLMonthlyModule({ token }) {
  const [year, setYear] = useState(new Date().getFullYear());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`/api/rahaza/finance/reports/profit-loss-monthly?year=${year}`, { headers: authHeaders(token) });
      if (r.ok) setData(await r.json()); else toast.error(`Gagal memuat (HTTP ${r.status})`);
    } finally { setLoading(false); }
  }, [token, year]);
  useEffect(() => { fetchData(); }, [fetchData]);


  const L = data?.lines || {};
  const labels = data?.meta?.month_labels || [];
  const hasData = data && GROUPS.some((g) => data.groups[g].accounts.length > 0);

  const columns = [
    ...labels.map((l, i) => ({ key: `m${i}`, label: `${l} ${String(year).slice(2)}` })),
    { key: 'total', label: 'Total' },
  ];
  const vals = (months, total, sign = 1) => {
    const v = {};
    (months || []).forEach((n, i) => { v[`m${i}`] = sign * Number(n || 0); });
    if (total !== undefined) v.total = sign * Number(total || 0);
    return v;
  };
  const rows = [];
  if (hasData) {
    GROUPS.forEach((g) => {
      const grp = data.groups[g];
      const sign = SIGN[g];
      rows.push({
        kind: 'group', id: `total-${g}`, label: grp.label, values: vals(grp.months, grp.total, sign),
        children: grp.accounts.map((a) => ({ code: a.code, label: a.name, values: vals(a.months, a.total, sign) })),
      });
      if (g === 'cogs') rows.push({ kind: 'subtotal', label: 'Laba kotor', values: vals(L.gross_profit.months, L.gross_profit.total), testId: 'pnl12-gross' });
      if (g === 'expense') rows.push({ kind: 'subtotal', label: 'Laba usaha', values: vals(L.operating_income.months, L.operating_income.total), testId: 'pnl12-operating' });
    });
    rows.push({ kind: 'total', label: Number(L.net_income.total) >= 0 ? 'Laba bersih' : 'Rugi bersih', values: vals(L.net_income.months, L.net_income.total), testId: 'pnl12-net' });
    rows.push({ kind: 'line', label: 'Akumulasi s/d bulan', values: vals(L.net_income_cumulative.months, L.net_income_cumulative.total), testId: 'pnl12-cum' });
  }
  const net = Number(L.net_income?.total || 0);

  return (
    <PageLayout
      testId="pnl12-page"
      title="Laba Rugi per bulan"
      subtitle="Pendapatan, HPP, beban, dan laba bersih tiap bulan dari buku besar; jurnal penutup tidak ikut."
      filters={
        <SmartNativeSelect value={String(year)} onChange={(e) => setYear(Number(e.target.value))} searchable={false}
          className="h-9 w-36" aria-label="Tahun" data-testid="pnl12-year">
          {yearOptions().map((y) => <option key={y} value={y}>{`Tahun ${y}`}</option>)}
        </SmartNativeSelect>
      }
      tools={<>
        <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={fetchData} data-testid="pnl12-refresh"><RefreshCw className="w-4 h-4" /></Button>
        <TombolUnduh namaBerkas={`laba-rugi-12-bulan-${year}`} namaLembar={`Laba rugi ${year}`} testId="pnl12-export"
          baris={unduhanLaporan(columns, rows).baris} kolom={unduhanLaporan(columns, rows).kolom} />
      </>}
      summary={hasData && (<>
        <IntercompanyNotes data={data} testId="pnl12-ic-notes" />
        <p className="text-sm text-muted-foreground" data-testid="pnl12-ringkas">
          Tahun {year}: pendapatan <b className="text-foreground tabular-nums" data-testid="pnl12-kpi-rev">{fmt(data?.groups?.revenue?.total)}</b>
          {' '}· laba kotor <b className={`tabular-nums ${Number(L.gross_profit?.total) < 0 ? 'text-[hsl(var(--danger-text))]' : 'text-foreground'}`} data-testid="pnl12-kpi-gross">{fmt(L.gross_profit?.total)}</b>
          {' '}· beban operasional <b className="text-foreground tabular-nums" data-testid="pnl12-kpi-exp">{fmt(data?.groups?.expense?.total)}</b>
          {' '}· {net >= 0 ? 'laba' : 'rugi'} bersih <b className={`tabular-nums ${net < 0 ? 'text-[hsl(var(--danger-text))]' : 'text-foreground'}`} data-testid="pnl12-kpi-net">{fmt(net)}</b>
        </p>
      </>)}
    >
      {loading ? (
        <div className="space-y-2">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
      ) : !hasData ? (
        <GlassCard className="p-0">
          <EmptyState icon={FileBarChart} testId="pnl12-empty" title={`Belum ada jurnal laba rugi di tahun ${year}`}
            description="Laba rugi per bulan muncul setelah ada jurnal pendapatan atau beban yang terposting." />
        </GlassCard>
      ) : (
        <div data-testid="pnl12-table">
          <StatementTable testId="pnl12" defaultOpen columns={columns} rows={rows} className={STICKY_LABEL} />
        </div>
      )}
    </PageLayout>
  );
}

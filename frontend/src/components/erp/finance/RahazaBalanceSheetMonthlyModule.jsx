import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Download, FileBarChart, CheckCircle2, AlertTriangle } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { toast } from 'sonner';
import { StatTile, EmptyState } from '../moduleAtoms';
import PageLayout from '../layout/PageLayout';
import IntercompanyNotes from './IntercompanyNotes';
import StatementTable from './StatementTable';
import { fmt, authHeaders, downloadXlsx, yearOptions } from './reportShared';

const SECTIONS = ['assets', 'liabilities', 'equity'];
// Kolom akun tetap terlihat saat tabel 12 bulan digulir ke samping. Latar = permukaan kartu di atas latar
// halaman (tema gelap: kartu tembus pandang, angka yang bergulir tidak boleh terlihat di balik nama akun).
const STICKY_LABEL = '[&_tr>:first-child]:sticky [&_tr>:first-child]:left-0 [&_tr>:first-child]:z-[1] [&_tr>:first-child]:whitespace-nowrap '
  + '[&_tr>:first-child]:[background:linear-gradient(var(--card-surface),var(--card-surface)),hsl(var(--background))]';

/**
 * Neraca › Akhir tiap bulan.
 * 2026-11-05 (PANDUAN_UI G1/G7): cetakan PageLayout dan tabel laporan yang sama dengan tab "Per tanggal"
 * (StatementTable). Dulu tabel sendiri berhuruf mesin ketik, warna palet langsung, dan wadah bergulir setinggi
 * 70% layar sehingga baris terakhir tertutup tombol chat.
 */
export default function RahazaBalanceSheetMonthlyModule({ token }) {
  const [year, setYear] = useState(new Date().getFullYear());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`/api/rahaza/finance/reports/balance-sheet-monthly?year=${year}`, { headers: authHeaders(token) });
      if (r.ok) setData(await r.json()); else toast.error(`Gagal memuat (HTTP ${r.status})`);
    } finally { setLoading(false); }
  }, [token, year]);
  useEffect(() => { fetchData(); }, [fetchData]);

  const exportXlsx = () => downloadXlsx(`/api/rahaza/finance/reports/export-xlsx?report=balance-sheet-monthly&year=${year}`, token, `neraca-12-bulan-${year}.xlsx`)
    .catch((e) => toast.error(`Unduhan gagal: ${e.message}`));

  const labels = data?.meta?.month_labels || [];
  const hasData = data && SECTIONS.some((s) => data.sections[s].accounts.length > 0);
  // 2026-11-04 (audit Keuangan): kartu = posisi bulan BERJALAN untuk tahun ini (dulu selalu kolom Des,
  // berlabel "Des 2026" padahal bulan belum sampai Desember).
  const thisYear = new Date().getFullYear();
  const idx = year === thisYear ? new Date().getMonth() : 11;
  const at = (arr) => (arr && arr.length ? (arr[Math.min(idx, arr.length - 1)] ?? 0) : 0);
  const asOf = `${labels[idx] || ''} ${year}`.trim();

  const columns = labels.map((l, i) => ({ key: `m${i}`, label: `${l} ${String(year).slice(2)}` }));
  const vals = (months) => {
    const v = {};
    (months || []).forEach((n, i) => { v[`m${i}`] = Number(n || 0); });
    return v;
  };
  const rows = [];
  if (hasData) {
    SECTIONS.forEach((s) => {
      const sec = data.sections[s];
      rows.push({
        kind: 'group', id: `total-${s}`, label: sec.label, values: vals(sec.months),
        children: sec.accounts.map((a) => ({ code: a.computed ? '' : a.code, label: a.name, note: a.computed ? '(laba berjalan)' : '', values: vals(a.months) })),
      });
    });
    rows.push({ kind: 'total', label: 'Total liabilitas + ekuitas', values: vals(data.totals.liab_plus_equity), testId: 'bs12-liab-eq' });
    rows.push({ kind: 'line', label: 'Selisih (aset − liabilitas − ekuitas)', values: vals(data.totals.diff), testId: 'bs12-diff' });
  }

  return (
    <PageLayout
      testId="bs12-page"
      title="Neraca akhir tiap bulan"
      subtitle="Posisi keuangan per akhir bulan Jan–Des; tiap kolom harus seimbang."
      filters={
        <SmartNativeSelect value={String(year)} onChange={(e) => setYear(Number(e.target.value))} searchable={false}
          className="h-9 w-28" aria-label="Tahun" data-testid="bs12-year">
          {yearOptions().map((y) => <option key={y} value={y}>{`Tahun ${y}`}</option>)}
        </SmartNativeSelect>
      }
      tools={<>
        <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={fetchData} data-testid="bs12-refresh"><RefreshCw className="w-4 h-4" /></Button>
        <Button variant="outline" onClick={exportXlsx} disabled={!data} data-testid="bs12-export"><Download className="w-4 h-4" />Unduh Excel</Button>
      </>}
      summary={hasData && <>
        <IntercompanyNotes data={data} testId="bs12-ic-notes" />
        <p className={`flex items-center gap-1.5 text-sm ${data.balanced ? 'text-muted-foreground' : 'text-[hsl(var(--destructive))] font-medium'}`} data-testid="bs12-balanced">
          {data.balanced
            ? <><CheckCircle2 className="w-4 h-4 text-[hsl(var(--success))]" /> Semua kolom seimbang: aset = liabilitas + ekuitas</>
            : <><AlertTriangle className="w-4 h-4" /> Ada kolom tidak seimbang — periksa jurnal tanpa akun neraca</>}
        </p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatTile label={`Total aset ${asOf}`} value={fmt(at(data?.sections?.assets?.months))} testId="bs12-kpi-assets" />
          <StatTile label={`Total liabilitas ${asOf}`} value={fmt(at(data?.sections?.liabilities?.months))} testId="bs12-kpi-liab" />
          <StatTile label={`Total ekuitas ${asOf}`} value={fmt(at(data?.sections?.equity?.months))} testId="bs12-kpi-eq" />
          <StatTile label={`Laba berjalan ${asOf}`} value={fmt(at(data?.totals?.current_earnings))} accent={at(data?.totals?.current_earnings) < 0 ? 'danger' : 'default'} testId="bs12-kpi-earn" />
        </div>
      </>}
    >
      {loading ? (
        <div className="space-y-2">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
      ) : !hasData ? (
        <GlassCard className="p-0">
          <EmptyState icon={FileBarChart} testId="bs12-empty" title={`Belum ada saldo neraca sampai akhir ${year}`}
            description="Isi saldo awal di Pengaturan Keuangan › Saldo awal, atau catat jurnal di tahun ini." />
        </GlassCard>
      ) : (
        <div data-testid="bs12-table">
          <StatementTable testId="bs12" defaultOpen columns={columns} rows={rows} className={STICKY_LABEL} />
        </div>
      )}
    </PageLayout>
  );
}

import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, FileBarChart, CheckCircle2, AlertTriangle } from 'lucide-react';
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
 * 2026-11-08 (Standar UI/UX v2): unduh Excel & CSV (TombolUnduh, isi = tabel ini); 4 kartu yang mengulang kolom
 * bulan berjalan diganti satu kalimat (angka sama); pilihan tahun dilebarkan (dulu "Tahun 2026" terpotong).
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
        children: sec.accounts.map((a) => ({ code: a.computed ? '' : a.code, label: a.computed ? 'Laba tahun berjalan (dihitung dari Laba Rugi)' : a.name, values: vals(a.months) })),
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
          className="h-9 w-36" aria-label="Tahun" data-testid="bs12-year">
          {yearOptions().map((y) => <option key={y} value={y}>{`Tahun ${y}`}</option>)}
        </SmartNativeSelect>
      }
      tools={<>
        <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={fetchData} data-testid="bs12-refresh"><RefreshCw className="w-4 h-4" /></Button>
        <TombolUnduh namaBerkas={`neraca-12-bulan-${year}`} namaLembar={`Neraca ${year}`} testId="bs12-export"
          baris={unduhanLaporan(columns, rows).baris} kolom={unduhanLaporan(columns, rows).kolom} />
      </>}
      summary={hasData && <>
        <IntercompanyNotes data={data} testId="bs12-ic-notes" />
        <p className={`flex items-center gap-1.5 text-sm ${data.balanced ? 'text-muted-foreground' : 'text-[hsl(var(--danger-text))] font-medium'}`} data-testid="bs12-balanced">
          {data.balanced
            ? <><CheckCircle2 className="w-4 h-4 shrink-0 text-[hsl(var(--success-text))]" />
                <span>Semua kolom seimbang. Akhir {asOf}: aset <b className="text-foreground tabular-nums" data-testid="bs12-kpi-assets">{fmt(at(data?.sections?.assets?.months))}</b>
                {' '}= liabilitas <b className="text-foreground tabular-nums" data-testid="bs12-kpi-liab">{fmt(at(data?.sections?.liabilities?.months))}</b>
                {' '}+ ekuitas <b className="text-foreground tabular-nums" data-testid="bs12-kpi-eq">{fmt(at(data?.sections?.equity?.months))}</b>
                <span className="hidden sm:inline">{' '}(laba berjalan <b className={`tabular-nums ${at(data?.totals?.current_earnings) < 0 ? 'text-[hsl(var(--danger-text))]' : 'text-foreground'}`} data-testid="bs12-kpi-earn">{fmt(at(data?.totals?.current_earnings))}</b>)</span></span></>
            : <><AlertTriangle className="w-4 h-4 shrink-0" /> Ada kolom tidak seimbang — periksa jurnal tanpa akun neraca</>}
        </p>
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

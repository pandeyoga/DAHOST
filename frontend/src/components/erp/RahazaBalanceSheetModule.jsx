import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, FileBarChart, CheckCircle2, AlertTriangle } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import DatePicker from '@/components/ui/date-picker';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { EmptyState } from './moduleAtoms';
import PageLayout from './layout/PageLayout';
import IntercompanyNotes from './finance/IntercompanyNotes';
import { Skeleton } from '@/components/ui/skeleton';
import { todayWIB } from '@/lib/waktu';
import { formatDateID } from '@/lib/format';
import StatementTable, { unduhanLaporan } from './finance/StatementTable';

const fmt = (n) => Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 0 });

/**
 * Neraca per tanggal (menu Laporan › Neraca).
 * 2026-11-04 (PANDUAN_UI G7): dua tabel laporan berdampingan (Aset | Liabilitas + Ekuitas) — dulu tiga
 * kartu dengan tabel tanpa judul kolom dan angka berhuruf mesin ketik berwarna-warni.
 * 2026-11-05 (PANDUAN_UI G1/G6): cetakan PageLayout — satu pilihan "Per tanggal" di toolbar kiri.
 * 2026-11-08 (Standar UI/UX v2): "Per tanggal" = DatePicker; unduh Excel/CSV; 4 kartu angka yang mengulang baris
 * total di tabel diganti satu kalimat (angka sama) supaya laporan tidak terdorong ke bawah; kode program
 * "LABA_BERJALAN" tidak ditampilkan (baris itu = laba tahun berjalan hasil hitung Laba Rugi).
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

  const t = data?.totals || {};
  const grp = (id, label, sec) => ({
    kind: 'group', id, label, values: { amount: sec?.total },
    children: (sec?.accounts || []).map((a) => (a.computed || a.code === 'LABA_BERJALAN'
      ? { code: '', label: 'Laba tahun berjalan (dihitung dari Laba Rugi)', values: { amount: a.amount } }
      : { code: a.code, label: a.name, values: { amount: a.amount } })),
  });
  const kiri = data ? [grp('assets', 'Aset', data.assets), { kind: 'total', label: 'Total aset', values: { amount: data.assets.total } }] : [];
  const kanan = data ? [grp('liabilities', 'Liabilitas', data.liabilities), grp('equity', 'Ekuitas', data.equity),
    { kind: 'total', label: 'Total liabilitas + ekuitas', values: { amount: t.liab_plus_equity } }] : [];
  const col = [{ key: 'amount', label: `Per ${formatDateID(asOf)}` }];

  return (
    <PageLayout
      testId="bs-page"
      title="Neraca"
      subtitle="Posisi aset, liabilitas, dan ekuitas pada satu tanggal."
      filters={<>
        <span className="text-sm text-muted-foreground">Per tanggal</span>
        <div className="w-44"><DatePicker value={asOf} onChange={(v) => setAsOf(v || todayWIB())} bolehKosong={false} testId="bs-as-of" /></div>
      </>}
      tools={<>
        <Button variant="outline" size="icon" onClick={fetchData} title="Muat ulang" aria-label="Muat ulang" data-testid="bs-refresh"><RefreshCw className="w-4 h-4" /></Button>
        <TombolUnduh namaBerkas={`neraca-${asOf}`} namaLembar="Neraca" testId="bs-export"
          baris={data ? unduhanLaporan(col, [...kiri, ...kanan]).baris : []} kolom={unduhanLaporan(col, []).kolom} />
      </>}
      summary={<>
        {error && <p className="text-sm text-[hsl(var(--danger-text))]" data-testid="bs-error">{error}</p>}
        {/* Tahap 8 fase 3: Gabungan = setelah eliminasi antar CV; selisih yang belum tereliminasi tampil di sini */}
        <IntercompanyNotes data={data} testId="bs-ic-notes" />
        {data && (
          <p className={`flex items-center gap-1.5 text-sm ${data.balanced ? 'text-muted-foreground' : 'text-[hsl(var(--danger-text))] font-medium'}`} data-testid="bs-balanced">
            {data.balanced
              ? <><CheckCircle2 className="w-4 h-4 shrink-0 text-[hsl(var(--success-text))]" />
                  <span>Seimbang: aset <b className="text-foreground tabular-nums" data-testid="bs-kpi-assets">{fmt(t.assets)}</b> = liabilitas <b className="text-foreground tabular-nums" data-testid="bs-kpi-liab">{fmt(t.liabilities)}</b> + ekuitas <b className="text-foreground tabular-nums" data-testid="bs-kpi-equity">{fmt(t.equity)}</b>
                  {' '}(termasuk {Number(t.current_earnings) >= 0 ? 'laba' : 'rugi'} tahun berjalan <b className={`tabular-nums ${Number(t.current_earnings) < 0 ? 'text-[hsl(var(--danger-text))]' : 'text-foreground'}`} data-testid="bs-kpi-earnings">{fmt(t.current_earnings)}</b>)</span></>
              : <><AlertTriangle className="w-4 h-4 shrink-0" /> Tidak seimbang, selisih {fmt(t.diff)} — periksa jurnal tanpa akun neraca</>}
          </p>
        )}
      </>}
    >
      {loading ? (
        <Skeleton className="h-80 rounded-[var(--radius-lg)]" />
      ) : !data ? (
        <GlassCard className="p-0">
          <EmptyState icon={FileBarChart} title="Belum ada neraca" description="Neraca muncul setelah ada jurnal atau saldo awal." />
        </GlassCard>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
          <StatementTable testId="bs-assets" defaultOpen columns={col} rows={kiri} />
          <StatementTable testId="bs-liab" defaultOpen columns={col} rows={kanan} />
        </div>
      )}
    </PageLayout>
  );
}

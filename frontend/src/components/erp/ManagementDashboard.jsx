/**
 * Dashboard Eksekutif — CV. Dewi Aditya ERP.
 * Ringkasan lintas bagian: penjualan (faktur), piutang & hutang, produksi, SDM.
 *
 * Standar UI/UX v2 (keputusan owner 8 Nov 2026): cetakan PageLayout (kepala tipis, tanpa kartu hero), kartu angka
 * satu gaya (StatTile, maks. 4 sebaris, dengan keterangan), tanpa warna mentah/HURUF BESAR, tabel umur piutang bisa
 * diunduh. Angka diperiksa terhadap data (lihat LAPORAN uji ketajaman):
 *  • "Revenue" = faktur piutang (reseller/grosir) per tanggal faktur — omzet marketplace TIDAK termasuk → label jujur.
 *  • Karyawan aktif dari /api/rahaza/management/overview (karyawan aktif). /api/dashboard `activeEmployees` jatuh ke
 *    jumlah AKUN pengguna bila data karyawan memakai `active: true` (48 akun vs 24 karyawan) → tidak dipakai.
 *  • PO berjalan & ketepatan kirim dari sumber PO produksi (production_pos / buyer_shipments) yang sama dengan
 *    Ringkasan Bisnis; `totalPOs`/`onTimeRate` /api/dashboard membaca koleksi pesanan lama (selalu 0) dan tren ±5%
 *    di kartu tepat waktu dulu karangan → tidak dipakai.
 *  • "Margin" (total faktur piutang − total tagihan pemasok) bukan margin → disembunyikan. OEE selalu kosong
 *    (mesin OEE diarsipkan) → disembunyikan. Tren 6 bulan PO membaca koleksi pesanan lama → disembunyikan.
 *  • Pilihan periode lama tidak memengaruhi angka apa pun (API tidak menerima periode) → tidak ditampilkan.
 *  • 8 Nov 2026: server /api/dashboard kini juga membaca PO dari production_pos, karyawan aktif dari `active: true`,
 *    dan output produksi dari sumber Ringkasan Bisnis (progres internal + penerimaan dari CMT).
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell,
} from 'recharts';
import { RefreshCw, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { ChartCard, GlassTooltip, CHART_PALETTE } from './dashboardAtoms';
import NextActionWidget from './NextActionWidget';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatTile } from './moduleAtoms';
import { thisYearWIB } from '@/lib/waktu';

const fmtNum = (v) => Number(v || 0).toLocaleString('id-ID');
const fmtShortIDR = (n) => {
  const v = Number(n || 0);
  const abs = Math.abs(v);
  const sign = v < 0 ? '−' : '';
  if (abs >= 1e9) return `${sign}Rp ${(abs / 1e9).toLocaleString('id-ID', { maximumFractionDigits: 1 })} M`;
  if (abs >= 1e6) return `${sign}Rp ${(abs / 1e6).toLocaleString('id-ID', { maximumFractionDigits: 1 })} jt`;
  if (abs >= 1e3) return `${sign}Rp ${(abs / 1e3).toLocaleString('id-ID', { maximumFractionDigits: 0 })} rb`;
  return `${sign}Rp ${abs.toLocaleString('id-ID')}`;
};
const fmtIDR = (n) => `Rp ${Math.round(Number(n || 0)).toLocaleString('id-ID')}`;

// Umur piutang: warna token (hijau → kuning → merah), bukan kode warna mentah.
const UMUR = [
  { label: 'Belum jatuh tempo', key: 'current', warna: 'hsl(var(--success))' },
  { label: '1–30 hari', key: 'd30', warna: 'hsl(var(--warning))' },
  { label: '31–60 hari', key: 'd60', warna: 'hsl(var(--warning))' },
  { label: '61–90 hari', key: 'd90', warna: 'hsl(var(--destructive))' },
  { label: 'Lebih dari 90 hari', key: 'd90plus', warna: 'hsl(var(--destructive))' },
  { label: 'Tanpa jatuh tempo', key: 'noDueDate', warna: 'hsl(var(--muted-foreground))' },
];

const STATUS_JOB = {
  draft: 'Draf', released: 'Dirilis', in_progress: 'Sedang dikerjakan', on_hold: 'Ditahan',
  completed: 'Selesai', closed: 'Ditutup', cancelled: 'Dibatalkan',
};

function UmurPiutang({ data }) {
  const baris = UMUR.map((u) => ({ ...u, nilai: Number(data?.[u.key] || 0) })).filter((u) => u.nilai > 0 || u.key !== 'noDueDate');
  const total = baris.reduce((s, b) => s + b.nilai, 0);
  if (!data || total === 0) {
    return <EmptyState className="py-8" title="Tidak ada piutang terbuka" description="Semua faktur piutang sudah lunas." />;
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Umur</TableHead>
          <TableHead className="hidden sm:table-cell">Porsi</TableHead>
          <TableHead className="text-right">Sisa piutang</TableHead>
          <TableHead className="w-14 text-right">%</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {baris.map((b) => {
          const pct = total > 0 ? (b.nilai / total) * 100 : 0;
          return (
            <TableRow key={b.key}>
              <TableCell className="whitespace-nowrap">{b.label}</TableCell>
              <TableCell className="hidden w-1/3 sm:table-cell">
                <div className="h-2 overflow-hidden rounded-full bg-[var(--glass-bg)]">
                  <div className="h-2 rounded-full" style={{ width: `${pct}%`, backgroundColor: b.warna }} />
                </div>
              </TableCell>
              <TableCell className="text-right tabular-nums">{fmtIDR(b.nilai)}</TableCell>
              <TableCell className="text-right tabular-nums text-muted-foreground">{Math.round(pct)}%</TableCell>
            </TableRow>
          );
        })}
        <TableRow>
          <TableCell className="font-semibold">Total</TableCell>
          <TableCell className="hidden sm:table-cell" />
          <TableCell className="text-right font-semibold tabular-nums">{fmtIDR(total)}</TableCell>
          <TableCell />
        </TableRow>
      </TableBody>
    </Table>
  );
}

export default function ManagementDashboard({ token, onNavigate, onModuleChange }) {
  const [metrics, setMetrics] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [overview, setOverview] = useState(null);
  const [onTime, setOnTime] = useState(null);
  const [loading, setLoading] = useState(true);
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);

  // Task 2.4/Dashboard 13→12: unified navigate helper (supports both onNavigate and onModuleChange)
  const drill = (moduleId) => () => {
    if (onModuleChange) onModuleChange(moduleId);
    else if (onNavigate) onNavigate(moduleId);
  };

  const fetchData = useCallback(async () => {
    setLoading(true);
    const ambil = (url) => fetch(url, { headers }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    try {
      const [m, a, ov, ot] = await Promise.all([
        ambil('/api/dashboard'),
        ambil('/api/dashboard/analytics'),
        ambil('/api/rahaza/management/overview?domain=all'),
        ambil('/api/rahaza/management/on-time-delivery?domain=all&days=90'),
      ]);
      setMetrics(m);
      setAnalytics(a);
      setOverview(ov);
      setOnTime(ot);
    } finally { setLoading(false); }
  }, [headers]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const weeklyTP = analytics?.weeklyThroughput || [];
  const adaOutput = weeklyTP.some((w) => Number(w.qty) > 0);
  const woStatusData = (metrics?.woStatus || []).map((s) => ({ name: STATUS_JOB[s._id] || 'Lainnya', value: s.count }));
  const karyawan = overview?.hr?.employees_active;
  const hadir = metrics?.attendanceTodayCount;
  const pctHadir = karyawan ? Math.min(100, Math.round(((hadir || 0) / karyawan) * 100)) : null;
  const ord = overview?.orders || {};
  const fakturTerbuka = (metrics?.unpaidInvoices || 0) + (metrics?.partialInvoices || 0);

  const tools = (
    <Button variant="outline" size="icon" onClick={fetchData} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
      data-testid="mgmt-dashboard-refresh">
      <RefreshCw className={loading ? 'animate-spin' : ''} />
    </Button>
  );
  const actions = (onModuleChange || onNavigate) ? (
    // 2026-11-02: dulu `drill(...)()` dipanggil saat render. 2026-11-08: langsung ke 'asisten-ai'.
    <Button onClick={drill('asisten-ai')} variant="outline" title="Buka Asisten AI" data-testid="mgmt-buka-asisten-ai">
      <Sparkles />Buka Asisten AI
    </Button>
  ) : null;

  if (loading && !metrics) {
    return (
      <PageLayout testId="management-dashboard" title="Dashboard Eksekutif"
        subtitle="Ringkasan lintas bagian: penjualan, piutang dan hutang, produksi, SDM." actions={actions} tools={tools}>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {[...Array(8)].map((_, i) => <div key={i} className="h-24 animate-pulse rounded-[var(--radius-md)] border border-[var(--glass-border)] bg-[var(--card-surface)]" />)}
        </div>
      </PageLayout>
    );
  }

  return (
    <PageLayout testId="management-dashboard" title="Dashboard Eksekutif"
      subtitle="Ringkasan lintas bagian: penjualan, piutang dan hutang, produksi, SDM."
      actions={actions} tools={tools}>
      <NextActionWidget
        token={token}
        portal="management"
        onNavigate={(moduleId) => onNavigate && onNavigate(moduleId)}
        onOpenSetupWizard={() => { onNavigate && onNavigate('production-dashboard'); }}
        maxCards={5}
      />

      {/* Keuangan */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="mgmt-kpi-keuangan" data-konten-utama="">
        <StatTile testId="kpi-revenue-today" label="Faktur penjualan hari ini" value={fmtShortIDR(metrics?.revenueToday)}
          sub={`Bulan ini ${fmtShortIDR(metrics?.revenueMTD)}`}
          hint="Total faktur piutang (reseller/grosir) per tanggal faktur. Omzet marketplace tidak termasuk." />
        <StatTile testId="kpi-revenue-ytd" label={`Faktur penjualan ${thisYearWIB()}`} value={fmtShortIDR(metrics?.revenueYTD)}
          sub="Sejak 1 Januari, per tanggal faktur" onClick={drill('fin-ar-invoices')}
          hint="Lihat faktur" />
        <StatTile testId="mgmt-kpi-ar" label="Piutang belum dibayar" value={fmtShortIDR(metrics?.outstandingAR)}
          sub={`${fmtNum(fakturTerbuka)} faktur terbuka`} accent={metrics?.outstandingAR > 0 ? 'warning' : 'default'}
          onClick={drill('fin-ar-invoices')} hint="Lihat faktur" />
        <StatTile testId="mgmt-kpi-ap" label="Hutang belum dibayar" value={fmtShortIDR(metrics?.outstandingAP)}
          sub="Sisa tagihan pemasok" accent={metrics?.outstandingAP > 0 ? 'warning' : 'default'}
          onClick={drill('fin-ap-aging')} hint="Lihat hutang" />
      </div>

      {/* Operasional & SDM */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="mgmt-kpi-operasional">
        <StatTile testId="mgmt-kpi-orders" label="PO produksi berjalan" value={overview ? fmtNum(ord.running) : '—'}
          sub={overview ? `dari ${fmtNum(ord.total)} PO · ${fmtNum(metrics?.activeJobs)} job aktif` : 'Data PO tidak terbaca'}
          onClick={drill('prod-orders')} hint="Lihat PO" />
        <StatTile testId="mgmt-kpi-ontime" label="Ketepatan kirim (90 hari)"
          value={onTime?.total_po ? `${String(onTime.rate_pct).replace('.', ',')}%` : '—'}
          sub={onTime?.total_po ? `${fmtNum(onTime.on_time)} dari ${fmtNum(onTime.total_po)} PO tepat waktu` : 'Belum ada PO berdeadline yang sudah dikirim'}
          accent={onTime?.total_po ? (onTime.rate_pct >= 80 ? 'success' : 'warning') : 'default'}
          onClick={drill('prod-orders')} hint="Lihat PO" />
        <StatTile testId="mgmt-kpi-employees" label="Karyawan aktif" value={karyawan != null ? fmtNum(karyawan) : '—'}
          sub={karyawan ? `${fmtNum(hadir)} hadir hari ini (${pctHadir}%)` : 'Data karyawan tidak terbaca'}
          onClick={drill('hr-employees')} hint="Lihat karyawan" />
        <StatTile testId="mgmt-kpi-shipments" label="Surat jalan terbuka" value={fmtNum(metrics?.pendingShipments)}
          sub="Draf atau terbit, belum diterima pelanggan" onClick={drill('wh-stock')} hint="Lihat gudang" />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ChartCard testId="chart-ar-aging" title="Umur piutang" subtitle="Sisa faktur piutang menurut lama lewat jatuh tempo."
          actions={(
            <TombolUnduh namaBerkas="umur-piutang" namaLembar="Umur piutang" testId="mgmt-ar-aging-unduh"
              baris={UMUR.map((u) => ({ ...u, nilai: Number(metrics?.arAging?.[u.key] || 0) }))}
              kolom={[{ label: 'Umur', nilai: (b) => b.label }, { label: 'Sisa piutang (Rp)', nilai: (b) => b.nilai }]} />
          )}>
          <UmurPiutang data={metrics?.arAging} />
        </ChartCard>

        <ChartCard title="Status job produksi" subtitle="Jumlah job menurut status saat ini.">
          {woStatusData.length > 0 ? (
            <div className="flex flex-col items-center gap-4 sm:flex-row">
              <div style={{ width: 160, height: 160 }}>
                <ResponsiveContainer>
                  <PieChart>
                    <Pie data={woStatusData} cx="50%" cy="50%" innerRadius={44} outerRadius={70} paddingAngle={3} dataKey="value" strokeWidth={0}>
                      {woStatusData.map((_, i) => <Cell key={i} fill={CHART_PALETTE[i % CHART_PALETTE.length]} />)}
                    </Pie>
                    <Tooltip content={<GlassTooltip />} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <ul className="w-full flex-1 space-y-1.5">
                {woStatusData.map((e, i) => (
                  <li key={e.name} className="flex items-center justify-between text-sm">
                    <span className="flex items-center gap-2">
                      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: CHART_PALETTE[i % CHART_PALETTE.length] }} />
                      {e.name}
                    </span>
                    <span className="font-semibold tabular-nums">{fmtNum(e.value)}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <EmptyState className="py-8" title="Belum ada job produksi" description="Job tercatat setelah PO produksi dirilis ke lantai produksi." />
          )}
        </ChartCard>
      </div>

      <ChartCard title="Output produksi per minggu" subtitle="Progres jahit internal + barang diterima dari CMT (sumber sama dengan Ringkasan Bisnis), 8 minggu terakhir.">
        {adaOutput ? (
          <div style={{ width: '100%', height: 220 }}>
            <ResponsiveContainer>
              <BarChart data={weeklyTP} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 4" stroke="var(--chart-grid)" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 12, fill: 'hsl(var(--muted-foreground))' }} stroke="var(--chart-grid)" />
                <YAxis tick={{ fontSize: 12, fill: 'hsl(var(--muted-foreground))' }} stroke="var(--chart-grid)" width={40} />
                <Tooltip content={<GlassTooltip formatter={(v) => `${fmtNum(v)} pcs`} />} cursor={{ fill: 'var(--glass-bg-hover)' }} />
                <Bar dataKey="qty" name="Output" fill={CHART_PALETTE[0]} radius={[6, 6, 0, 0]} maxBarSize={44} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <EmptyState className="py-8" title="Belum ada output produksi tercatat dalam 8 minggu terakhir"
            description="Grafik muncul setelah output produksi dicatat." />
        )}
      </ChartCard>
    </PageLayout>
  );
}

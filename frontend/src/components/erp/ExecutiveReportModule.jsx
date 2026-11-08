/**
 * Laporan Eksekutif — laporan gabungan lintas bagian (keuangan, produksi, SDM, pemasaran) untuk manajemen.
 * Fitur: ringkasan per bulan, analisis naratif AI, perbandingan 6 bulan, tren multi-indikator.
 *
 * Standar UI/UX v2 (keputusan owner 8 Nov 2026): cetakan PageLayout (pilihan bulan di `filters`, muat ulang di
 * `tools`), bagian = pil penyaring di baris yang sama (dulu deret tombol buatan sendiri; tanpa tab di dalam modul), kartu angka satu gaya (StatTile),
 * tabel standar yang bisa diunduh Excel/CSV, grafik tren memakai recharts dengan DUA seri yang memang ditampilkan
 * (dulu legenda menyebut 2 seri tetapi batang hanya pendapatan), tanpa warna mentah / istilah Inggris.
 * Angka diperiksa (lihat LAPORAN): "Piutang lewat jatuh tempo" adalah posisi SAAT INI (bukan per bulan) → label
 * diperjelas & kolomnya dikeluarkan dari tabel per bulan; jumlah faktur ≠ sumber pendapatan (buku besar) → dipisah.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import axios from 'axios';
import { Loader2, RefreshCw, Sparkles } from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import { Button } from '../ui/button';
import SmartNativeSelect from '../ui/smart-native-select';
import FilterChips from '../ui/filter-chips';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../ui/table';
import TombolUnduh from '../ui/tombol-unduh';
import { GlassCard } from '../ui/glass';
import { useToast } from '../../hooks/use-toast';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile } from './moduleAtoms';
import { ChartCard, GlassTooltip, CHART_PALETTE } from './dashboardAtoms';
import { monthOptions } from './finance/PeriodPicker';
import { thisMonthWIB } from '@/lib/waktu';

const API = process.env.REACT_APP_BACKEND_URL || '';
const FMT_IDR = (v) => `Rp ${Math.round(+v || 0).toLocaleString('id-ID')}`;
const FMT_NUM = (v) => (+v || 0).toLocaleString('id-ID');
const FMT_PCT = (v) => `${(+v || 0).toLocaleString('id-ID', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
const BULAN = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'];
const labelBulan = (p) => {
  const [y, m] = String(p || '').split('-').map(Number);
  return y && m ? `${BULAN[m - 1]} ${y}` : String(p || '—');
};
const fmtJuta = (v) => {
  const n = Number(v || 0);
  if (Math.abs(n) >= 1e9) return `${(n / 1e9).toLocaleString('id-ID', { maximumFractionDigits: 1 })} M`;
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toLocaleString('id-ID', { maximumFractionDigits: 0 })} jt`;
  return n.toLocaleString('id-ID');
};

/** "Naik 3,1% dari bulan lalu" — teks, bukan panah berwarna. */
function teksDelta(pct) {
  if (pct == null) return 'Tanpa pembanding bulan lalu';
  const v = Number(pct);
  if (v === 0) return 'Sama dengan bulan lalu';
  return `${v > 0 ? 'Naik' : 'Turun'} ${Math.abs(v).toLocaleString('id-ID', { maximumFractionDigits: 1 })}% dari bulan lalu`;
}

// Penyaji markdown ringan (tanpa dependensi) — judul #/##/###, daftar, dan **tebal** untuk narasi AI.
function renderInline(text) {
  const parts = String(text).split(/(\*\*[^*]+\*\*)/g);
  return parts.map((p, i) =>
    p.startsWith('**') && p.endsWith('**')
      ? <strong key={i} className="font-semibold text-foreground">{p.slice(2, -2)}</strong>
      : <span key={i}>{p}</span>
  );
}

function MarkdownLite({ text }) {
  const lines = String(text || '').split('\n');
  const blocks = [];
  let list = [];
  const flush = (key) => {
    if (list.length) {
      blocks.push(<ul key={`ul-${key}`} className="my-2 list-disc space-y-1 pl-5">{list}</ul>);
      list = [];
    }
  };
  lines.forEach((raw, idx) => {
    const line = raw.trimEnd();
    if (/^###\s+/.test(line)) { flush(idx); blocks.push(<p key={idx} className="mb-1 mt-3 text-sm font-semibold text-foreground">{renderInline(line.replace(/^###\s+/, ''))}</p>); }
    else if (/^##\s+/.test(line)) { flush(idx); blocks.push(<p key={idx} className="mb-1 mt-4 text-base font-semibold text-foreground">{renderInline(line.replace(/^##\s+/, ''))}</p>); }
    else if (/^#\s+/.test(line)) { flush(idx); blocks.push(<p key={idx} className="mb-1 mt-2 text-lg font-semibold text-foreground">{renderInline(line.replace(/^#\s+/, ''))}</p>); }
    else if (/^[-*]\s+/.test(line)) { list.push(<li key={idx} className="text-sm leading-relaxed text-foreground/90">{renderInline(line.replace(/^[-*]\s+/, ''))}</li>); }
    else if (line.trim() === '') { flush(idx); }
    else { flush(idx); blocks.push(<p key={idx} className="my-1 text-sm leading-relaxed text-foreground/90">{renderInline(line)}</p>); }
  });
  flush('end');
  return <div>{blocks}</div>;
}

/** Kartu satu bagian: daftar "indikator : nilai". */
function KartuBagian({ judul, baris, catatan, loading }) {
  return (
    <ChartCard title={judul}>
      <dl className="divide-y divide-[var(--glass-border)]">
        {baris.map(([k, v]) => (
          <div key={k} className="flex items-baseline justify-between gap-3 py-1.5 text-sm">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="text-right tabular-nums text-foreground">{loading ? '…' : v}</dd>
          </div>
        ))}
      </dl>
      {catatan && <p className="mt-2 text-xs text-muted-foreground">{catatan}</p>}
    </ChartCard>
  );
}

export default function ExecutiveReportModule({ user, headers }) {
  const [summary, setSummary] = useState(null);
  const [kpiComparison, setKpiComparison] = useState([]);
  const [trend, setTrend] = useState([]);
  const [loading, setLoading] = useState(false);
  const [bulan, setBulan] = useState(() => thisMonthWIB());
  const [trendMonths, setTrendMonths] = useState('6');
  const [activeSection, setActiveSection] = useState('summary');
  const [aiNarrative, setAiNarrative] = useState('');
  const [aiMeta, setAiMeta] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  // 2026-11-02 (K33): akses diatur owner di Manajemen Role (izin mod.fin_exec_report.view).
  const [denied, setDenied] = useState('');
  const { toast } = useToast();
  const authH = useMemo(() => headers || {}, [headers]);
  const bulanOpsi = useMemo(() => monthOptions(24), []);
  const [selectedYear, selectedMonth] = bulan.split('-').map((x) => String(Number(x)));

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const params = { year: parseInt(selectedYear, 10), month: parseInt(selectedMonth, 10) };
      const [sumRes, cmpRes, trendRes] = await Promise.all([
        axios.get(`${API}/api/reports/executive/summary`, { headers: authH, params }),
        axios.get(`${API}/api/reports/executive/kpi-comparison`, { headers: authH, params: { months: 6 } }),
        axios.get(`${API}/api/reports/executive/trend`, { headers: authH, params: { months: parseInt(trendMonths, 10) } }),
      ]);
      setSummary(sumRes.data);
      setKpiComparison(cmpRes.data?.data || []);
      setTrend(trendRes.data?.data || []);
      setDenied('');
    } catch (e) {
      if (e.response?.status === 403) {
        setDenied(e.response?.data?.detail || 'Akses Laporan Eksekutif tidak diizinkan untuk peran Anda.');
        return;
      }
      toast({ title: 'Laporan gagal dimuat', description: e.response?.data?.detail || 'Coba muat ulang.', variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  }, [selectedYear, selectedMonth, trendMonths, authH, toast]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const generateNarrative = useCallback(async (refresh = false) => {
    setAiLoading(true);
    try {
      const params = { year: parseInt(selectedYear, 10), month: parseInt(selectedMonth, 10), refresh };
      const res = await axios.get(`${API}/api/reports/executive/ai-narrative`, { headers: authH, params });
      if (res.data?.ok) {
        setAiNarrative(res.data.narrative || '');
        setAiMeta({ cache_hit: res.data.cache_hit, generated_at: res.data.generated_at });
        if (refresh) toast({ title: 'Analisis AI diperbarui' });
      } else {
        toast({ title: 'AI tidak tersedia', description: res.data?.error || 'Analisis gagal dibuat.', variant: 'destructive' });
      }
    } catch (e) {
      toast({ title: 'Analisis AI gagal dibuat', description: e.response?.data?.detail || 'Coba lagi.', variant: 'destructive' });
    } finally {
      setAiLoading(false);
    }
  }, [selectedYear, selectedMonth, authH, toast]);

  // Reset narasi AI saat periode berubah (hindari tampil data periode lain)
  useEffect(() => { setAiNarrative(''); setAiMeta(null); }, [selectedYear, selectedMonth]);

  const fin = summary?.finance || {};
  const prod = summary?.production || {};
  const hr = summary?.hr || {};
  const mkt = summary?.marketing || {};
  const v = (x) => (loading ? '…' : x);
  const judulPeriode = labelBulan(bulan);

  const barisKeuangan = [
    // 2026-11-04 (audit Keuangan): "Faktur reseller sudah dibayar" = bagian faktur periode ini yang sudah dibayar —
    // bukan pendapatan buku besar (yang memuat marketplace).
    ['Pendapatan (buku besar)', FMT_IDR(fin.revenue_rp)],
    ['Faktur reseller sudah dibayar', FMT_IDR(fin.paid_revenue_rp)],
    ['Total biaya', FMT_IDR(fin.total_expenses_rp)],
    ['Laba bersih', FMT_IDR(fin.net_income_rp)],
    ['Piutang lewat jatuh tempo (posisi saat ini)', `${FMT_IDR(fin.ar_overdue_rp)} (${FMT_NUM(fin.ar_overdue_count)} faktur)`],
  ];
  const barisProduksi = [
    ['Total WO', FMT_NUM(prod.total_wo)],
    ['WO selesai', `${FMT_NUM(prod.completed_wo)} (${FMT_PCT(prod.completion_rate_pct)})`],
    ['WO aktif', FMT_NUM(prod.active_wo)],
    ['Qty dipesan', FMT_NUM(prod.total_qty_ordered)],
    ['Tingkat cacat', FMT_PCT(prod.defect_rate_pct)],
  ];
  const barisSdm = [
    ['Karyawan aktif', FMT_NUM(hr.total_active_employees)],
    ['Karyawan baru', FMT_NUM(hr.new_hires)],
    ['Tingkat kehadiran', FMT_PCT(hr.attendance_rate_pct)],
    ['Jam lembur', `${FMT_NUM(hr.overtime_hours)} jam`],
    ['Total gaji', FMT_IDR(hr.payroll_total_rp)],
  ];
  const barisPemasaran = [
    ['Sesi live', FMT_NUM(mkt.live_sessions)],
    ['Omzet live', FMT_IDR(mkt.live_revenue_rp)],
    ['Pesanan live', FMT_NUM(mkt.live_orders)],
    ['Pesanan marketplace (otomatis)', FMT_NUM(mkt.marketplace_orders_via_webhook)],
    /* F10 — menggantikan metrik mati "kampanye KOL"; sumbernya kalender konten F7. */
    ['Konten terbit', FMT_NUM(mkt.content_posted)],
    ['Kreator aktif', FMT_NUM(mkt.active_creators)],
    ['GMV konten (angka platform)*', FMT_IDR(mkt.content_gmv_kpi_rp)],
  ];
  const semuaIndikator = [
    ...barisKeuangan.map(([k, x]) => ({ bagian: 'Keuangan', k, x })),
    ...barisProduksi.map(([k, x]) => ({ bagian: 'Produksi', k, x })),
    ...barisSdm.map(([k, x]) => ({ bagian: 'SDM', k, x })),
    ...barisPemasaran.map(([k, x]) => ({ bagian: 'Pemasaran', k, x })),
  ];

  const BAGIAN = [
    { key: 'summary', label: 'Ringkasan' }, { key: 'ai', label: 'Analisis AI' }, { key: 'finance', label: 'Keuangan' },
    { key: 'production', label: 'Produksi' }, { key: 'hr', label: 'SDM' }, { key: 'trend', label: 'Tren' },
  ];
  const filters = (
    <>
      <FilterChips options={BAGIAN} value={activeSection} onChange={setActiveSection} hideWhenEmpty={false}
        ariaLabel="Bagian laporan" testId="tab-exec" />
      <SmartNativeSelect value={bulan} onChange={(e) => setBulan(e.target.value)} searchable={false}
        className="h-9 w-48" aria-label="Bulan laporan" data-testid="exec-bulan">
        {bulanOpsi.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </SmartNativeSelect>
    </>
  );
  const tools = (
    <Button variant="outline" size="icon" onClick={fetchAll} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
      data-testid="btn-refresh-exec">
      <RefreshCw className={loading ? 'animate-spin' : ''} />
    </Button>
  );

  if (denied) {
    return (
      <PageLayout testId="exec-report-denied" title="Laporan Eksekutif" subtitle="Laporan gabungan lintas bagian untuk manajemen.">
        <Notice tone="warning" title="Laporan Eksekutif tidak tersedia untuk peran Anda">{denied}</Notice>
      </PageLayout>
    );
  }

  return (
    <PageLayout testId="exec-report" title="Laporan Eksekutif"
      subtitle="Laporan gabungan keuangan, produksi, SDM, dan pemasaran untuk manajemen."
      filters={filters} tools={tools}
      summary={summary ? (
        <p className="text-sm text-muted-foreground">
          Periode laporan: <span className="font-medium text-foreground">{judulPeriode}</span>
          {summary.period?.range && ` (${summary.period.range.from} s.d. ${summary.period.range.to})`}
        </p>
      ) : null}>
      <div className="space-y-4">

        {/* Ringkasan */}
        {activeSection === 'summary' && (<div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatTile label="Pendapatan bulan ini" value={v(FMT_IDR(fin.revenue_rp))} sub={teksDelta(fin.revenue_delta_vs_prev_pct)}
              testId="exec-kpi-pendapatan" />
            <StatTile label="Laba bersih" value={v(FMT_IDR(fin.net_income_rp))} sub={`Margin ${FMT_PCT(fin.profit_margin_pct)}`}
              accent={fin.net_income_rp < 0 ? 'danger' : 'default'} />
            <StatTile label="WO selesai" value={v(FMT_NUM(prod.completed_wo))} sub={`dari ${FMT_NUM(prod.total_wo)} WO`} />
            <StatTile label="Karyawan aktif" value={v(FMT_NUM(hr.total_active_employees))} sub={`${FMT_NUM(hr.absent_count)} tidak hadir hari ini`} />
          </div>
          <div className="flex justify-end">
            <TombolUnduh namaBerkas={`laporan-eksekutif-${bulan}`} namaLembar="Ringkasan" baris={summary ? semuaIndikator : []}
              testId="exec-ringkasan-unduh"
              kolom={[{ label: 'Bagian', nilai: (r) => r.bagian }, { label: 'Indikator', nilai: (r) => r.k }, { label: 'Nilai', nilai: (r) => r.x }]} />
          </div>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <KartuBagian judul="Keuangan" baris={barisKeuangan} loading={loading}
              catatan={`Pendapatan dari akun pendapatan buku besar (termasuk marketplace). Faktur piutang bulan ini: ${FMT_NUM(fin.invoice_count)} faktur, ${FMT_IDR(fin.invoice_revenue_gross_rp)}.`} />
            <KartuBagian judul="Produksi" baris={barisProduksi} loading={loading} />
            <KartuBagian judul="SDM" baris={barisSdm} loading={loading} />
            <KartuBagian judul="Pemasaran" baris={barisPemasaran} loading={loading}
              catatan="*GMV konten adalah angka platform per konten — jangan dijumlah dengan omzet pesanan (menghitung satu penjualan dua kali)." />
          </div>
        </div>)}

        {/* Analisis AI (WS-B a) */}
        {activeSection === 'ai' && (<div className="space-y-4">
          <GlassCard className="space-y-3 p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-base font-semibold text-foreground">Analisis eksekutif AI</p>
                <p className="text-sm text-muted-foreground">Ringkasan naratif dan rekomendasi strategis untuk {judulPeriode}.</p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {aiMeta?.generated_at && (
                  <span className="text-xs text-muted-foreground" data-testid="exec-ai-meta">
                    {aiMeta.cache_hit ? 'Dari simpanan' : 'Baru dibuat'} · {new Date(aiMeta.generated_at).toLocaleString('id-ID')}
                  </span>
                )}
                <Button onClick={() => generateNarrative(!!aiNarrative)} disabled={aiLoading} data-testid="btn-generate-exec-ai">
                  {aiLoading ? <Loader2 className="animate-spin" /> : <Sparkles />}
                  {aiLoading ? 'Menganalisis…' : (aiNarrative ? 'Buat ulang analisis' : 'Buat analisis')}
                </Button>
              </div>
            </div>

            {aiLoading && !aiNarrative && (
              <div className="space-y-2 animate-pulse" data-testid="exec-ai-loading">
                <div className="h-4 w-1/3 rounded bg-[var(--glass-bg)]" />
                <div className="h-3 w-full rounded bg-[var(--glass-bg)]" />
                <div className="h-3 w-5/6 rounded bg-[var(--glass-bg)]" />
                <div className="h-3 w-4/6 rounded bg-[var(--glass-bg)]" />
              </div>
            )}
            {!aiLoading && !aiNarrative && (
              <EmptyState className="py-8" testId="exec-ai-empty" title="Belum ada analisis untuk bulan ini"
                description="Tekan Buat analisis untuk membuat ringkasan eksekutif berbasis AI dari indikator bulan ini." />
            )}
            {aiNarrative && (
              <div className="border-t border-[var(--glass-border)] pt-3" data-testid="exec-ai-narrative">
                <MarkdownLite text={aiNarrative} />
              </div>
            )}
          </GlassCard>
        </div>)}

        {/* Keuangan */}
        {activeSection === 'finance' && (<div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3" data-konten-utama="">
            <StatTile label="Pendapatan (buku besar)" value={v(FMT_IDR(fin.revenue_rp))} sub={teksDelta(fin.revenue_delta_vs_prev_pct)} />
            <StatTile label="Laba bersih" value={v(FMT_IDR(fin.net_income_rp))} sub={`Margin ${FMT_PCT(fin.profit_margin_pct)}`}
              accent={fin.net_income_rp < 0 ? 'danger' : 'default'} />
            <StatTile label="Piutang lewat jatuh tempo (saat ini)" value={v(FMT_IDR(fin.ar_overdue_rp))}
              sub={`${FMT_NUM(fin.ar_overdue_count)} faktur, jatuh tempo sebelum hari ini`}
              accent={fin.ar_overdue_rp > 0 ? 'warning' : 'default'} />
          </div>
          <ChartCard title="Perbandingan 6 bulan" subtitle="Pendapatan dan laba bersih per bulan (buku besar)."
            actions={(
              <TombolUnduh namaBerkas="laporan-eksekutif-6-bulan" namaLembar="Perbandingan 6 bulan" baris={kpiComparison}
                testId="exec-banding-unduh"
                kolom={[
                  { label: 'Bulan', nilai: (r) => labelBulan(r.period) },
                  { label: 'Pendapatan (Rp)', nilai: (r) => r.revenue_rp },
                  { label: 'Laba bersih (Rp)', nilai: (r) => r.net_income_rp },
                  { label: 'WO selesai', nilai: (r) => r.wo_completed },
                ]} />
            )}>
            {kpiComparison.length === 0 ? <EmptyState className="py-8" title="Belum ada data" /> : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Bulan</TableHead>
                    <TableHead className="text-right">Pendapatan</TableHead>
                    <TableHead className="text-right">Laba bersih</TableHead>
                    <TableHead className="text-right">WO selesai</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {kpiComparison.map((r) => (
                    <TableRow key={r.period}>
                      <TableCell className="whitespace-nowrap">{labelBulan(r.period)}</TableCell>
                      <TableCell className="text-right tabular-nums">{FMT_IDR(r.revenue_rp)}</TableCell>
                      <TableCell className={`text-right tabular-nums ${r.net_income_rp < 0 ? 'text-[hsl(var(--danger-text))]' : ''}`}>{FMT_IDR(r.net_income_rp)}</TableCell>
                      <TableCell className="text-right tabular-nums">{FMT_NUM(r.wo_completed)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </ChartCard>
        </div>)}

        {/* Produksi */}
        {activeSection === 'production' && (<div className="space-y-0">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-konten-utama="">
            <StatTile label="Total WO" value={v(FMT_NUM(prod.total_wo))}
              sub={`${FMT_NUM(prod.completed_wo)} selesai (${FMT_PCT(prod.completion_rate_pct)}) · ${FMT_NUM(prod.active_wo)} aktif`} />
            <StatTile label="Qty dipesan" value={v(FMT_NUM(prod.total_qty_ordered))} sub="pcs" />
            <StatTile label="Qty selesai" value={v(FMT_NUM(prod.total_qty_completed))} sub={`${FMT_PCT(prod.fulfillment_rate_pct)} dari qty dipesan`} />
            <StatTile label="Tingkat cacat" value={v(FMT_PCT(prod.defect_rate_pct))} accent={prod.defect_rate_pct > 2 ? 'danger' : 'default'} />
          </div>
        </div>)}

        {/* SDM */}
        {activeSection === 'hr' && (<div className="space-y-0">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-konten-utama="">
            <StatTile label="Karyawan aktif" value={v(FMT_NUM(hr.total_active_employees))} sub={`${FMT_NUM(hr.new_hires)} karyawan baru bulan ini`} />
            <StatTile label="Tingkat kehadiran" value={v(FMT_PCT(hr.attendance_rate_pct))}
              accent={hr.attendance_rate_pct && hr.attendance_rate_pct < 90 ? 'warning' : 'default'} sub={`${FMT_NUM(hr.absent_count)} tidak hadir hari ini`} />
            <StatTile label="Jam lembur" value={v(`${FMT_NUM(hr.overtime_hours)} jam`)} />
            <StatTile label="Total gaji" value={v(FMT_IDR(hr.payroll_total_rp))} />
          </div>
        </div>)}

        {/* Tren */}
        {activeSection === 'trend' && (<div className="space-y-4" data-konten-utama="">
          <ChartCard title="Pendapatan dan laba bersih" subtitle="Per bulan, dari buku besar."
            actions={(
              <SmartNativeSelect value={trendMonths} onChange={(e) => setTrendMonths(e.target.value)} searchable={false}
                className="h-9 w-40" aria-label="Rentang tren" data-testid="exec-tren-bulan">
                <option value="3">3 bulan terakhir</option>
                <option value="6">6 bulan terakhir</option>
                <option value="12">12 bulan terakhir</option>
              </SmartNativeSelect>
            )}>
            {trend.length === 0 ? <EmptyState className="py-8" title="Belum ada data" /> : (
              <div style={{ width: '100%', height: 240 }}>
                <ResponsiveContainer>
                  <BarChart data={trend.map((r) => ({ ...r, bulan: labelBulan(r.period).slice(0, 3) }))} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 4" stroke="var(--chart-grid)" vertical={false} />
                    <XAxis dataKey="bulan" tick={{ fontSize: 12, fill: 'hsl(var(--muted-foreground))' }} stroke="var(--chart-grid)" />
                    <YAxis tickFormatter={fmtJuta} width={56} tick={{ fontSize: 12, fill: 'hsl(var(--muted-foreground))' }} stroke="var(--chart-grid)" />
                    <Tooltip content={<GlassTooltip formatter={FMT_IDR} />} cursor={{ fill: 'var(--glass-bg-hover)' }} />
                    <Legend wrapperStyle={{ fontSize: 12 }} formatter={(nilai) => <span className="text-foreground">{nilai}</span>} />
                    <Bar dataKey="revenue_rp" name="Pendapatan" fill={CHART_PALETTE[0]} radius={[4, 4, 0, 0]} maxBarSize={32} />
                    <Bar dataKey="net_income_rp" name="Laba bersih" fill={CHART_PALETTE[1]} radius={[4, 4, 0, 0]} maxBarSize={32} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </ChartCard>
          <ChartCard title="Data tren" subtitle="Indikator per bulan."
            actions={(
              <TombolUnduh namaBerkas="laporan-eksekutif-tren" namaLembar="Tren" baris={trend} testId="exec-tren-unduh"
                kolom={[
                  { label: 'Bulan', nilai: (r) => labelBulan(r.period) },
                  { label: 'Pendapatan (Rp)', nilai: (r) => r.revenue_rp },
                  { label: 'Laba bersih (Rp)', nilai: (r) => r.net_income_rp },
                  { label: 'Tingkat kehadiran (%)', nilai: (r) => r.attendance_rate_pct },
                  { label: 'Total gaji (Rp)', nilai: (r) => r.payroll_total_rp },
                ]} />
            )}>
            {trend.length === 0 ? <EmptyState className="py-8" title="Belum ada data" /> : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Bulan</TableHead>
                    <TableHead className="text-right">Pendapatan</TableHead>
                    <TableHead className="text-right">Laba bersih</TableHead>
                    <TableHead className="hidden text-right sm:table-cell">Kehadiran</TableHead>
                    <TableHead className="hidden text-right sm:table-cell">Total gaji</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {trend.map((r) => (
                    <TableRow key={r.period}>
                      <TableCell className="whitespace-nowrap">{labelBulan(r.period)}</TableCell>
                      <TableCell className="text-right tabular-nums">{FMT_IDR(r.revenue_rp)}</TableCell>
                      <TableCell className="text-right tabular-nums">{FMT_IDR(r.net_income_rp)}</TableCell>
                      <TableCell className="hidden text-right tabular-nums sm:table-cell">{FMT_PCT(r.attendance_rate_pct)}</TableCell>
                      <TableCell className="hidden text-right tabular-nums sm:table-cell">{FMT_IDR(r.payroll_total_rp)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </ChartCard>
        </div>)}
      </div>
    </PageLayout>
  );
}

/**
 * MonthlyReportModule — Laporan Bulanan PIC Portal Marketing
 * Target vs actual per akun, task completion, sales input rate.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, pemilih bulan standar, 6 kartu → 4 StatTile, tabel standar + unduh
 * Excel/CSV, grafik omzet harian per akun dibuka di popup rincian (dulu baris yang membuka di tabel), warna token.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { RefreshCw, ChevronLeft, ChevronRight, Loader2, FileDown, BarChart3 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { formatTanggalID } from '@/components/ui/date-picker';
import { toast } from 'sonner';
import { formatRupiah } from '@/lib/format';
import { bulanMarketingWIB } from '@/lib/waktu';
import PageLayout from '../layout/PageLayout';
import { monthOptions } from '../finance/PeriodPicker';
import { EmptyState, StatTile, StatusBadge } from '../moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;
const MONTH_NAMES = ['Januari','Februari','Maret','April','Mei','Juni','Juli','Agustus','September','Oktober','November','Desember'];
const fmtRp = formatRupiah;
const fmtNum = (n) => new Intl.NumberFormat('id-ID').format(n || 0);
const pctTxt = (v) => (v == null ? '—' : `${Number(v).toLocaleString('id-ID')}%`);

const STATUS_CONFIG = {
  on_track:  { label: 'Sesuai jalur', tone: 'success' },
  warning:   { label: 'Perlu dorongan', tone: 'warning' },
  behind:    { label: 'Tertinggal', tone: 'danger' },
  no_target: { label: 'Belum ada target', tone: 'muted' },
};
const warnaSkor = (v) => (v >= 80 ? 'text-[hsl(var(--success-text))]' : v >= 60 ? 'text-[hsl(var(--warning-text))]' : 'text-[hsl(var(--danger-text))]');

function Capaian({ actual, target, pct, status, fmt }) {
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.no_target;
  return (
    <div className="text-right">
      <p className="font-medium tabular-nums">{fmt(actual)}</p>
      {target != null && target > 0
        ? <p className="text-xs text-muted-foreground">dari {fmt(target)} · <StatusBadge status={status} label={pctTxt(pct)} tone={cfg.tone} /></p>
        : <p className="text-xs text-muted-foreground">Belum ada target</p>}
    </div>
  );
}

export default function MonthlyReportModule({ token }) {
  const [ym] = useState(() => bulanMarketingWIB().split('-').map(Number));   // bulan Marketing 26–25
  const [year, setYear]     = useState(ym[0]);
  const [month, setMonth]   = useState(ym[1]);
  const [report, setReport] = useState(null);
  const [loading, setLoading]   = useState(true);
  const [exporting, setExporting] = useState(false);
  const [detail, setDetail] = useState(null);

  const authH = { Authorization: `Bearer ${token}` };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/marketing/reports/monthly?year=${year}&month=${month}`, { headers: authH });
      if (!res.ok) throw new Error('Gagal memuat laporan');
      setReport(await res.json());
    } catch (e) { toast.error(e.message); }
    finally { setLoading(false); }
  }, [year, month, token]); // eslint-disable-line

  useEffect(() => { load(); }, [load]);

  const prevMonth = () => { if (month === 1) { setMonth(12); setYear(y => y - 1); } else setMonth(m => m - 1); };
  const nextMonth = () => { if (month === 12) { setMonth(1); setYear(y => y + 1); } else setMonth(m => m + 1); };
  const ymValue = `${year}-${String(month).padStart(2, '0')}`;
  const opsiBulan = monthOptions(36);
  if (!opsiBulan.some((o) => o.value === ymValue)) opsiBulan.unshift({ value: ymValue, label: `${MONTH_NAMES[month - 1]} ${year}` });

  const handleExportPDF = async () => {
    setExporting(true);
    try {
      const res = await fetch(
        `${API}/api/marketing/reports/monthly/export-pdf?year=${year}&month=${month}`,
        { headers: authH }
      );
      if (!res.ok) throw new Error('Gagal membuat PDF');
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href     = url;
      a.download = `laporan-marketing-${MONTH_NAMES[month-1].toLowerCase()}-${year}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success('PDF diunduh');
    } catch (e) { toast.error(e.message); }
    finally { setExporting(false); }
  };

  const s = report?.summary || {};
  const rows = report?.accounts || [];

  const kolom = [
    { kunci: 'akun', label: 'Akun', hp: 'judul', isi: (r) => (
      <div data-testid={`monthly-row-${r.account_code}`}><p className="font-medium">{r.account_name}</p><p className="text-xs text-muted-foreground">{r.account_code}</p></div>) },
    { kunci: 'omzet', label: 'Omzet', rata: 'kanan', isi: (r) => (
      <Capaian actual={r.actual.revenue} target={r.target.revenue} pct={r.achievement.revenue_pct} status={r.achievement.revenue_status} fmt={fmtRp} />) },
    { kunci: 'pesanan', label: 'Pesanan', rata: 'kanan', isi: (r) => (
      <Capaian actual={r.actual.orders} target={r.target.orders} pct={r.achievement.orders_pct} status={r.achievement.orders_status} fmt={fmtNum} />) },
    { kunci: 'input', label: 'Input sales', rata: 'kanan', isi: (r) => (
      <div className="text-right"><p className="tabular-nums">{r.actual.sales_days} hari</p>
        <p className={`text-xs ${r.actual.input_rate >= 80 ? 'text-[hsl(var(--success-text))]' : 'text-[hsl(var(--warning-text))]'}`}>{pctTxt(r.actual.input_rate)} hari terisi</p></div>) },
    { kunci: 'tugas', label: 'Tugas', rata: 'kanan', isi: (r) => (
      <div className="text-right"><p className="tabular-nums">{r.task_stats.done}/{r.task_stats.total}</p>
        {r.task_stats.completion_rate != null && <p className="text-xs text-muted-foreground">{pctTxt(r.task_stats.completion_rate)}</p>}</div>) },
    { kunci: 'sehat', label: 'Kesehatan', rata: 'kanan', isi: (r) => (r.health_score == null
      ? <span className="text-muted-foreground">Belum ada</span>
      : <span className={`font-semibold tabular-nums ${warnaSkor(r.health_score)}`}>{r.health_score}</span>) },
  ];

  const maxHarian = detail ? Math.max(...(detail.daily_chart || []).map((x) => x.revenue), 1) : 1;

  return (
    <PageLayout testId="monthly-report-module" title="Laporan bulanan"
      subtitle={`Target dan hasil per akun — ${MONTH_NAMES[month - 1]} ${year}.`}
      actions={(
        <Button variant="outline" onClick={handleExportPDF} disabled={exporting || loading} data-testid="export-pdf-btn">
          {exporting ? <Loader2 className="animate-spin" /> : <FileDown />}Unduh PDF
        </Button>
      )}
      filters={(
        <div className="flex items-center gap-1">
          <Button variant="outline" size="icon" onClick={prevMonth} title="Bulan sebelumnya" aria-label="Bulan sebelumnya"><ChevronLeft /></Button>
          <SmartNativeSelect className="w-44" value={ymValue} searchable={false} data-testid="monthly-month"
            onChange={(e) => { const [y, m] = e.target.value.split('-').map(Number); setYear(y); setMonth(m); }}>
            {opsiBulan.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </SmartNativeSelect>
          <Button variant="outline" size="icon" onClick={nextMonth} title="Bulan berikutnya" aria-label="Bulan berikutnya"><ChevronRight /></Button>
        </div>
      )}
      tools={<>
        <TombolUnduh namaBerkas={`laporan-bulanan-${ymValue}`} namaLembar="Per akun" baris={rows} testId="monthly-unduh"
          kolom={[
            { label: 'Akun', nilai: (r) => r.account_name }, { label: 'Kode', nilai: (r) => r.account_code },
            { label: 'Omzet', nilai: (r) => Number(r.actual.revenue || 0) }, { label: 'Target omzet', nilai: (r) => r.target.revenue ?? '' },
            { label: 'Capai omzet (%)', nilai: (r) => r.achievement.revenue_pct ?? '' },
            { label: 'Pesanan', nilai: (r) => Number(r.actual.orders || 0) }, { label: 'Target pesanan', nilai: (r) => r.target.orders ?? '' },
            { label: 'Hari input sales', nilai: (r) => r.actual.sales_days }, { label: 'Hari terisi (%)', nilai: (r) => r.actual.input_rate },
            { label: 'Tugas selesai', nilai: (r) => r.task_stats.done }, { label: 'Tugas total', nilai: (r) => r.task_stats.total },
            { label: 'Skor kesehatan', nilai: (r) => r.health_score ?? '' },
          ]} />
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={report && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Omzet" value={fmtRp(s.rev_actual)} sub={s.rev_target > 0 ? `Target ${fmtRp(s.rev_target)}` : `Belum ada target · ${s.total_accounts || 0} akun`} />
          <StatTile label="Pencapaian omzet" value={pctTxt(s.rev_pct)}
            accent={s.rev_pct == null ? 'default' : s.rev_pct >= 90 ? 'success' : s.rev_pct >= 70 ? 'warning' : 'danger'}
            sub={s.rev_pct == null ? 'Isi target dulu' : `${s.rev_pct >= 90 ? 'Sesuai jalur' : s.rev_pct >= 70 ? 'Perlu dorongan' : 'Jauh dari target'}${s.accounts_without_target ? ` · ${s.accounts_with_target} toko bertarget` : ''}`} />
          <StatTile label="Pesanan" value={fmtNum(s.ord_actual)} sub={s.ord_target > 0 ? `Target ${fmtNum(s.ord_target)}` : 'Belum ada target'} />
          <StatTile label="Tugas selesai" value={pctTxt(s.task_completion)}
            sub={`Rata-rata hari terisi ${pctTxt(s.avg_sales_input_rate)} per akun`} />
        </div>
      )}>
      {loading && !report ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat laporan…</p>
      ) : (
        <TabelData kolom={kolom} baris={rows} kunci={(r) => r.account_id} onKlikBaris={setDetail} testId="monthly-report-table"
          kosong={<EmptyState icon={BarChart3} title="Belum ada akun aktif" description="Akun toko aktif akan muncul di laporan ini." />} />
      )}

      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} judul={detail.account_name} testId="monthly-detail"
          keterangan={`${detail.account_code} · ${MONTH_NAMES[month - 1]} ${year}`}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Omzet">{fmtRp(detail.actual.revenue)}{detail.target.revenue ? ` dari target ${fmtRp(detail.target.revenue)} (${pctTxt(detail.achievement.revenue_pct)})` : ' · belum ada target'}</BarisDetail>
            <BarisDetail label="Pesanan">{fmtNum(detail.actual.orders)}{detail.target.orders ? ` dari target ${fmtNum(detail.target.orders)} (${pctTxt(detail.achievement.orders_pct)})` : ' · belum ada target'}</BarisDetail>
            <BarisDetail label="Input sales">{detail.actual.sales_days} hari · {pctTxt(detail.actual.input_rate)} hari terisi</BarisDetail>
            <BarisDetail label="Tugas">{detail.task_stats.done} dari {detail.task_stats.total} selesai</BarisDetail>
            <BarisDetail label="Skor kesehatan">{detail.health_score ?? 'Belum ada'}</BarisDetail>
          </dl>
          <section className="space-y-2">
            <p className="text-sm font-medium">Omzet harian</p>
            {(detail.daily_chart || []).length === 0 ? (
              <p className="text-sm text-muted-foreground">Belum ada omzet harian bulan ini.</p>
            ) : (
              <div className="flex h-24 items-end gap-1" role="img" aria-label="Grafik omzet harian">
                {detail.daily_chart.map((d) => (
                  <div key={d.date} className="min-w-[4px] flex-1 rounded-t bg-[hsl(var(--primary)/0.6)]"
                    style={{ height: `${Math.round((d.revenue / maxHarian) * 100)}%`, minHeight: d.revenue > 0 ? '2px' : '0' }}
                    title={`${formatTanggalID(d.date)}: ${fmtRp(d.revenue)}`} />
                ))}
              </div>
            )}
          </section>
        </DetailPopup>
      )}
    </PageLayout>
  );
}

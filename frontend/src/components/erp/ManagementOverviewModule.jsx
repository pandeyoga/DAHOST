/**
 * Ringkasan Bisnis (Management Overview) — dipisah per DOMAIN + jejak sumber.
 *
 * 2026-08-06 — DIPERBAIKI TOTAL. Backend `routes/rahaza_reports.py` membaca SSOT (production_pos / po_items /
 * production_jobs / production_job_items / production_progress / cmt_receipts / buyer_shipments / rahaza_ar_invoices)
 * dan setiap respons mengirim `sources` → ditampilkan sebagai baris "Sumber data" berbahasa biasa.
 * Keputusan owner: **domain dipisah tegas** — Produksi Internal DA vs Maklon.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout (domain = pil penyaring, periode, muat ulang), 4 kartu angka
 * StatTile dengan keterangan yang benar, ambang peringatan & persetujuan PR diubah lewat FormPopup (isian & simpan
 * sama), daftar peringatan / tahapan PO / produk / pelanggan = tabel yang bisa diunduh, tanpa kode koleksi di layar,
 * tanpa warna mentah, gradasi, atau HURUF BESAR.
 */
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { RefreshCw, SlidersHorizontal } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import FilterChips from '@/components/ui/filter-chips';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { ChartCard, GlassTooltip, DonutProgress, CHART_PALETTE } from './dashboardAtoms';
import { PeriodPicker, resolvePreset } from './PeriodPicker';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from './moduleAtoms';
import {
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area,
} from 'recharts';
import { formatRupiah } from '@/lib/format';

const fmtNum = (n) => Number(n || 0).toLocaleString('id-ID');
const fmtShortIDR = (n) => {
  const v = Number(n || 0);
  if (v >= 1e9) return `Rp ${(v / 1e9).toLocaleString('id-ID', { maximumFractionDigits: 1 })} M`;
  if (v >= 1e6) return `Rp ${(v / 1e6).toLocaleString('id-ID', { maximumFractionDigits: 1 })} jt`;
  if (v >= 1e3) return `Rp ${(v / 1e3).toLocaleString('id-ID', { maximumFractionDigits: 0 })} rb`;
  return formatRupiah(v);
};
const tglID = (ymd) => {
  if (!ymd) return '';
  const [y, m, d] = String(ymd).slice(0, 10).split('-');
  const B = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
  return `${Number(d)} ${B[Number(m) - 1] || ''} ${y}`;
};
const sisaHari = (n) => (n < 0 ? `Lewat ${Math.abs(n)} hari` : `Sisa ${n} hari`);
const DOMAIN_LABEL = { internal: 'Internal DA', maklon: 'Maklon' };

const DOMAINS = [
  { key: 'all', label: 'Gabungan' },
  { key: 'internal', label: 'Internal DA' },
  { key: 'maklon', label: 'Maklon' },
];

// Kode koleksi → nama yang dipahami staf (dulu tampil apa adanya: "production_pos 0").
const NAMA_SUMBER = {
  production_pos: 'PO produksi', po_items: 'Item PO', production_jobs: 'Job produksi',
  production_job_items: 'Buku kuantitas job', production_progress: 'Progres produksi', cmt_receipts: 'Terima dari CMT',
  buyer_shipments: 'Kirim ke buyer', rahaza_ar_invoices: 'Faktur piutang', rahaza_materials: 'Master material',
};

/** Jejak sumber — menjawab "angka ini dari mana?" tanpa istilah program. */
function SourceTrace({ rows, domainLabel }) {
  if (!rows?.length) return null;
  return (
    <p className="text-xs text-muted-foreground" data-testid="overview-source-trace">
      Sumber data{domainLabel ? ` (${domainLabel})` : ''}:{' '}
      {rows.map((s) => `${NAMA_SUMBER[s.collection] || 'Data lain'} ${fmtNum(s.count)}`).join(' · ')} dokumen.
    </p>
  );
}

const TAHAP_PO = [
  ['Draf', 'draft', 'Belum dikonfirmasi'],
  ['Dikonfirmasi', 'confirmed', 'Siap didistribusi'],
  ['Berjalan', 'running', 'Sedang diproduksi'],
  ['Selesai', 'done', 'Selesai atau ditutup'],
  ['Dibatalkan', 'cancelled', 'Dibatalkan'],
];

export default function ManagementOverviewModule({ token }) {
  const [domain, setDomain] = useState('all');
  const [data, setData] = useState(null);
  const [daily, setDaily] = useState([]);
  const [topModels, setTopModels] = useState([]);
  const [topCustomers, setTopCustomers] = useState([]);
  const [onTime, setOnTime] = useState(null);
  const [alerts, setAlerts] = useState(null);   // peringatan otomatis (PO deadline & piutang)
  const [alertCfg, setAlertCfg] = useState(null);   // ambang hari (bisa diatur owner)
  const [cfgDraft, setCfgDraft] = useState({
    po_warn_days: '', ar_warn_days: '', rnd_attention_days: '', rnd_stale_days: '',
    // 2026-08-07 — ambang NILAI (Rp) yang menentukan berapa tahap persetujuan
    // yang wajib dilalui sebuah Permintaan Pengadaan (PR).
    pr_1_stage_max: '', pr_2_stage_max: '',
  });
  const [savingCfg, setSavingCfg] = useState(false);
  const [bukaAmbang, setBukaAmbang] = useState(false);
  // Muat otomatis tiap 60 detik tidak boleh menimpa isian yang sedang diubah di popup ambang.
  const bukaAmbangRef = useRef(false);
  useEffect(() => { bukaAmbangRef.current = bukaAmbang; }, [bukaAmbang]);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [period, setPeriod] = useState({ preset: '30d', from: null, to: null });

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  const dateRange = useMemo(() => {
    let { from, to } = period || {};
    if (!from || !to) {
      // Rentang preset (tanggal WIB) dari SSOT PeriodPicker — tidak dihitung ulang di sini.
      ({ from, to } = resolvePreset(period?.preset || '30d'));
    }
    return { from, to };
  }, [period]);

  const isiDraft = (cfg) => setCfgDraft({
    po_warn_days: String(cfg?.po_warn_days ?? 3),
    ar_warn_days: String(cfg?.ar_warn_days ?? 3),
    rnd_attention_days: String(cfg?.rnd_attention_days ?? 3),
    rnd_stale_days: String(cfg?.rnd_stale_days ?? 7),
    pr_1_stage_max: String(cfg?.pr_1_stage_max ?? 1000000),
    pr_2_stage_max: String(cfg?.pr_2_stage_max ?? 25000000),
  });

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const qs = `?domain=${domain}` +
        (dateRange.from && dateRange.to ? `&date_from=${dateRange.from}&date_to=${dateRange.to}` : '');
      const [ov, dl, tm, tc, ot, al, cfg] = await Promise.all([
        fetch(`/api/rahaza/management/overview${qs}`, { headers }).then(r => r.json()),
        fetch(`/api/rahaza/management/daily-output${qs}`, { headers }).then(r => r.json()),
        fetch(`/api/rahaza/management/top-models?domain=${domain}&limit=5`, { headers }).then(r => r.json()),
        fetch(`/api/rahaza/management/top-customers?domain=${domain}&limit=5`, { headers }).then(r => r.json()),
        fetch(`/api/rahaza/management/on-time-delivery?domain=${domain}&days=90`, { headers }).then(r => r.json()),
        fetch('/api/rahaza/management/alerts', { headers }).then(r => r.json()),
        fetch('/api/rahaza/management/alert-config', { headers }).then(r => r.json()),
      ]);
      setData(ov);
      setDaily(dl.timeline || []);
      setTopModels(tm.items || []);
      setTopCustomers(tc.items || []);
      setOnTime(ot);
      setAlerts(al);
      setAlertCfg(cfg);
      if (!bukaAmbangRef.current) isiDraft(cfg);
      setLastUpdate(new Date());
    } finally { setLoading(false); }
  }, [headers, domain, dateRange.from, dateRange.to]);

  const saveAlertConfig = async () => {
    setSavingCfg(true);
    try {
      const res = await fetch('/api/rahaza/management/alert-config', {
        method: 'PUT',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          po_warn_days: Number(cfgDraft.po_warn_days),
          ar_warn_days: Number(cfgDraft.ar_warn_days),
          rnd_attention_days: Number(cfgDraft.rnd_attention_days),
          rnd_stale_days: Number(cfgDraft.rnd_stale_days),
          pr_1_stage_max: Number(cfgDraft.pr_1_stage_max),
          pr_2_stage_max: Number(cfgDraft.pr_2_stage_max),
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || `Permintaan gagal (kode ${res.status}).`);
      setAlertCfg(body);
      toast.success('Ambang disimpan', {
        description: `PO ${body.po_warn_days} hari · Piutang ${body.ar_warn_days} hari · `
          + `RnD kuning ${body.rnd_attention_days} hari / merah ${body.rnd_stale_days} hari · `
          + `PR 1 tahap ≤ ${fmtShortIDR(body.pr_1_stage_max)} · 2 tahap ≤ ${fmtShortIDR(body.pr_2_stage_max)}`,
      });
      setBukaAmbang(false);
      const al = await fetch('/api/rahaza/management/alerts', { headers }).then(r => r.json());
      setAlerts(al);
    } catch (e) {
      toast.error('Gagal menyimpan ambang', { description: e.message });
    } finally {
      setSavingCfg(false);
    }
  };

  useEffect(() => {
    fetchAll();
    const t = setInterval(fetchAll, 60000);
    return () => clearInterval(t);
  }, [fetchAll]);

  const prod = data?.production || {};
  const ord = data?.orders || {};
  const fin = data?.finance || {};
  const setDraft = (k) => (e) => setCfgDraft((p) => ({ ...p, [k]: e.target.value }));
  const adaOutput = daily.some((d) => d.total);
  const poAlerts = alerts?.po_alerts || [];
  const arAlerts = alerts?.ar_alerts || [];

  const filters = (
    <>
      <FilterChips options={DOMAINS} value={domain} onChange={setDomain} hideWhenEmpty={false}
        ariaLabel="Pilih domain bisnis" testId="overview-domain" />
      <PeriodPicker value={period} onChange={setPeriod} compareEnabled={false} testId="mgmt-overview-period" />
    </>
  );
  const tools = (
    <Button variant="outline" size="icon" onClick={fetchAll} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
      data-testid="overview-refresh">
      <RefreshCw className={loading ? 'animate-spin' : ''} />
    </Button>
  );

  if (loading && !data) {
    return (
      <PageLayout testId="management-overview-page" title="Ringkasan Bisnis"
        subtitle="Angka langsung dari dokumen kerja: PO, job produksi, terima CMT, pengiriman, dan faktur."
        filters={filters} tools={tools}>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-24 animate-pulse rounded-[var(--radius-md)] border border-[var(--glass-border)] bg-[var(--card-surface)]" />
          ))}
        </div>
      </PageLayout>
    );
  }

  return (
    <PageLayout
      testId="management-overview-page"
      title="Ringkasan Bisnis"
      subtitle="Angka langsung dari dokumen kerja: PO, job produksi, terima CMT, pengiriman, dan faktur."
      filters={filters}
      tools={tools}
      summary={(
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-konten-utama="">
            <StatTile testId="kpi-output" label="Output periode" value={`${fmtNum(prod.output_period)} pcs`}
              sub={prod.qty_produced
                ? `${String(prod.accept_rate_pct).replace('.', ',')}% diterima dari ${fmtNum(prod.qty_produced)} diproduksi · ${fmtNum(prod.qty_reject)} ditolak`
                : `Progres ${fmtNum(prod.output_progress_period)} + terima CMT ${fmtNum(prod.output_received_period)}`} />
            <StatTile testId="kpi-orders" label="PO berjalan" value={fmtNum(ord.running)}
              sub={`dari ${fmtNum(ord.total)} PO · ${fmtNum(ord.qty_ordered)} pcs dipesan`} />
            <StatTile testId="kpi-ar" label="Piutang belum tertagih" value={fmtShortIDR(fin.ar_outstanding)}
              accent={fin.ar_overdue_count > 0 ? 'warning' : 'default'}
              sub={`${fmtNum(fin.ar_overdue_count)} faktur lewat jatuh tempo · dari ${fmtNum(fin.ar_invoices)} faktur`} />
            <StatTile testId="kpi-low-stock" label="Material di bawah stok minimum" value={fmtNum(data?.warehouse?.low_stock_materials)}
              accent={(data?.warehouse?.low_stock_materials || 0) > 0 ? 'warning' : 'default'}
              sub={`dari ${fmtNum(data?.warehouse?.materials_tracked)} material aktif`} />
          </div>
          <p className="text-xs text-muted-foreground" data-testid="overview-ringkas">
            {data?.domain_label || 'Gabungan'} · periode {tglID(data?.date_from)} – {tglID(data?.date_to)}
            {' · '}{fmtNum(data?.hr?.employees_active)} karyawan aktif
            {lastUpdate ? ` · diperbarui ${lastUpdate.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' })}` : ''}
          </p>
        </div>
      )}
    >
      {/* ── Peringatan otomatis + ambang yang bisa diatur ───────────────── */}
      <ChartCard testId="card-alerts" title="Peringatan perlu tindakan"
        subtitle={`Dikirim otomatis ke manajemen setiap pagi pukul 07.00: PO ${alertCfg?.po_warn_days ?? 3} hari dan piutang ${alertCfg?.ar_warn_days ?? 3} hari sebelum tenggat (juga saat sudah lewat).`}
        actions={(
          <Button variant="outline" onClick={() => { isiDraft(alertCfg); setBukaAmbang(true); }} data-testid="alert-threshold-open">
            <SlidersHorizontal />Atur ambang
          </Button>
        )}>
        <div className="space-y-4">
          {poAlerts.length > 0 && (
            <div className="space-y-2" data-testid="alert-po-list">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-medium text-foreground">PO mendekati / lewat tenggat ({fmtNum(alerts.po_count)})</p>
                <TombolUnduh namaBerkas="peringatan-po" namaLembar="Peringatan PO" baris={poAlerts} testId="alert-po-unduh"
                  kolom={[
                    { label: 'No. PO', nilai: (a) => a.po_number },
                    { label: 'Domain', nilai: (a) => DOMAIN_LABEL[a.domain] || a.domain },
                    { label: 'Pelanggan', nilai: (a) => a.customer },
                    { label: 'Tenggat', nilai: (a) => sisaHari(a.days_left) },
                    { label: 'Kurang (pcs)', nilai: (a) => a.qty_short },
                  ]} />
              </div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>No. PO</TableHead>
                    <TableHead className="hidden sm:table-cell">Pelanggan</TableHead>
                    <TableHead>Tenggat</TableHead>
                    <TableHead className="text-right">Kurang</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {poAlerts.slice(0, 5).map((a) => (
                    <TableRow key={a.po_id}>
                      <TableCell className="font-medium">{a.po_number}
                        <span className="block text-xs text-muted-foreground">{DOMAIN_LABEL[a.domain] || a.domain}</span></TableCell>
                      <TableCell className="hidden sm:table-cell">{a.customer}</TableCell>
                      <TableCell><StatusBadge status="tenggat" label={sisaHari(a.days_left)} tone={a.days_left < 0 ? 'danger' : 'warning'} /></TableCell>
                      <TableCell className="text-right tabular-nums">{fmtNum(a.qty_short)} pcs</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {poAlerts.length > 5 && <p className="text-xs text-muted-foreground">Menampilkan 5 dari {fmtNum(poAlerts.length)}; semua ada di unduhan.</p>}
            </div>
          )}
          {arAlerts.length > 0 && (
            <div className="space-y-2" data-testid="alert-ar-list">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-medium text-foreground">Piutang mendekati / lewat jatuh tempo ({fmtNum(alerts.ar_count)})</p>
                <TombolUnduh namaBerkas="peringatan-piutang" namaLembar="Peringatan piutang" baris={arAlerts} testId="alert-ar-unduh"
                  kolom={[
                    { label: 'No. faktur', nilai: (a) => a.invoice_number },
                    { label: 'Pelanggan', nilai: (a) => a.customer },
                    { label: 'Sisa tagihan (Rp)', nilai: (a) => a.outstanding },
                    { label: 'Jatuh tempo', nilai: (a) => sisaHari(a.days_left) },
                  ]} />
              </div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>No. faktur</TableHead>
                    <TableHead className="hidden sm:table-cell">Pelanggan</TableHead>
                    <TableHead>Jatuh tempo</TableHead>
                    <TableHead className="text-right">Sisa tagihan</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {arAlerts.slice(0, 5).map((a) => (
                    <TableRow key={a.invoice_id}>
                      <TableCell className="font-medium">{a.invoice_number}
                        <span className="block text-xs text-muted-foreground sm:hidden">{a.customer}</span></TableCell>
                      <TableCell className="hidden sm:table-cell">{a.customer}</TableCell>
                      <TableCell><StatusBadge status="jatuh-tempo" label={sisaHari(a.days_left)} tone={a.days_left < 0 ? 'danger' : 'warning'} /></TableCell>
                      <TableCell className="text-right tabular-nums">{formatRupiah(a.outstanding)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {arAlerts.length > 5 && <p className="text-xs text-muted-foreground">Menampilkan 5 dari {fmtNum(arAlerts.length)}; semua ada di unduhan.</p>}
            </div>
          )}
          {!alerts?.po_count && !alerts?.ar_count && (
            <p className="py-4 text-center text-sm text-muted-foreground" data-testid="alert-empty">
              Tidak ada PO atau piutang yang mendekati tenggat pada ambang saat ini.
            </p>
          )}
          <p className="text-xs text-muted-foreground" data-testid="alert-threshold-ringkas">
            Ambang: PO {alertCfg?.po_warn_days ?? 3} hari · piutang {alertCfg?.ar_warn_days ?? 3} hari ·
            {' '}RnD kuning {alertCfg?.rnd_attention_days ?? 3} / merah {alertCfg?.rnd_stale_days ?? 7} hari ·
            {' '}PR cukup 1 tahap ≤ {fmtShortIDR(alertCfg?.pr_1_stage_max ?? 1000000)}, 2 tahap ≤ {fmtShortIDR(alertCfg?.pr_2_stage_max ?? 25000000)}
            {alertCfg?.updated_by ? ` · terakhir diubah ${alertCfg.updated_by}` : ''}
          </p>
        </div>
      </ChartCard>

      {/* ── Output harian + ketepatan kirim ─────────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <ChartCard testId="chart-daily-output" title="Output per hari" className="lg:col-span-2"
          subtitle="Internal = catatan progres produksi · Maklon = penerimaan barang dari CMT.">
          {!adaOutput ? (
            <EmptyState className="py-8" testId="daily-output-empty" title="Belum ada output pada periode ini"
              description="Output tercatat saat progres produksi diinput atau saat barang dari CMT diterima dan diperiksa." />
          ) : (
            <div style={{ width: '100%', height: 240 }}>
              <ResponsiveContainer>
                <AreaChart data={daily} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 4" stroke="var(--chart-grid)" vertical={false} />
                  <XAxis dataKey="date" stroke="var(--chart-grid)"
                    tick={{ fontSize: 12, fill: 'hsl(var(--muted-foreground))' }}
                    tickFormatter={(v) => (v ? `${v.slice(8, 10)}/${v.slice(5, 7)}` : '')} />
                  <YAxis width={40} stroke="var(--chart-grid)" tick={{ fontSize: 12, fill: 'hsl(var(--muted-foreground))' }} />
                  <Tooltip content={<GlassTooltip formatter={(v) => `${fmtNum(v)} pcs`} />} cursor={{ fill: 'var(--glass-bg-hover)' }} />
                  <Area type="monotone" dataKey="internal" name="Internal DA" stackId="1"
                    stroke={CHART_PALETTE[0]} strokeWidth={2} fill={CHART_PALETTE[0]} fillOpacity={0.2} />
                  <Area type="monotone" dataKey="maklon" name="Maklon" stackId="1"
                    stroke={CHART_PALETTE[1]} strokeWidth={2} fill={CHART_PALETTE[1]} fillOpacity={0.2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </ChartCard>

        <ChartCard testId="card-on-time" title="Ketepatan kirim ke buyer" subtitle="Kirim terakhir dibanding tenggat PO, 90 hari.">
          {onTime?.total_po ? (
            <div className="flex flex-col items-center justify-center gap-3 py-2">
              <DonutProgress value={onTime.rate_pct || 0} size={150} stroke={14} label="Tepat waktu"
                sub={`${fmtNum(onTime.on_time)} dari ${fmtNum(onTime.total_po)} PO`}
                accent={(onTime.rate_pct || 0) >= 85 ? 'success' : (onTime.rate_pct || 0) >= 60 ? 'primary' : 'warning'} />
              <p className="text-center text-xs text-muted-foreground">{onTime.measurable_note}</p>
            </div>
          ) : (
            <EmptyState className="py-8" title="Belum bisa dinilai"
              description="Belum ada PO yang punya tenggat sekaligus sudah dikirim ke buyer dalam 90 hari terakhir." />
          )}
        </ChartCard>
      </div>

      {/* ── Tahapan PO + Top produk + Top pelanggan ─────────────────────── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <ChartCard testId="card-po-funnel" title="Tahapan PO" subtitle="Sebaran PO menurut status alur kerja."
          actions={(
            <TombolUnduh namaBerkas="tahapan-po" namaLembar="Tahapan PO" testId="po-funnel-unduh"
              baris={TAHAP_PO.map(([label, k, hint]) => ({ label, hint, n: ord[k] || 0 }))}
              kolom={[{ label: 'Tahap', nilai: (r) => r.label }, { label: 'Keterangan', nilai: (r) => r.hint }, { label: 'Jumlah PO', nilai: (r) => r.n }]} />
          )}>
          <Table>
            <TableBody>
              {TAHAP_PO.map(([label, k, hint]) => (
                <TableRow key={k} data-testid={`po-bucket-${label}`}>
                  <TableCell>{label}<span className="block text-xs text-muted-foreground">{hint}</span></TableCell>
                  <TableCell className="text-right font-semibold tabular-nums">{fmtNum(ord[k])}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </ChartCard>

        <ChartCard testId="card-top-models" title="5 produk teratas" subtitle="Qty dipesan (PO) dan qty sudah diterima."
          actions={(
            <TombolUnduh namaBerkas="produk-teratas" namaLembar="Produk teratas" baris={topModels} testId="top-models-unduh"
              kolom={[
                { label: 'Produk', nilai: (m) => m.name || m.sku },
                { label: 'SKU', nilai: (m) => m.sku || '' },
                { label: 'Qty dipesan', nilai: (m) => m.qty },
                { label: 'Qty diterima', nilai: (m) => m.accepted },
              ]} />
          )}>
          <Table>
            <TableHeader>
              <TableRow><TableHead>Produk</TableHead><TableHead className="text-right">Diterima / dipesan</TableHead></TableRow>
            </TableHeader>
            <TableBody>
              {topModels.length === 0 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={2} className="p-0 [&>div]:py-8"><EmptyState title="Belum ada item PO" /></TableCell>
                </TableRow>
              )}
              {topModels.map((m, idx) => (
                <TableRow key={`${m.sku}-${idx}`} data-testid={`top-model-${idx}`}>
                  <TableCell className="max-w-[12rem] truncate" title={m.name || m.sku}>{m.name || m.sku}</TableCell>
                  <TableCell className="whitespace-nowrap text-right tabular-nums">{fmtNum(m.accepted)} / {fmtNum(m.qty)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </ChartCard>

        <ChartCard testId="card-top-customers" title="5 pelanggan / klien teratas" subtitle="Volume PO (dan nilai order untuk maklon)."
          actions={(
            <TombolUnduh namaBerkas="pelanggan-teratas" namaLembar="Pelanggan teratas" baris={topCustomers} testId="top-customers-unduh"
              kolom={[
                { label: 'Pelanggan', nilai: (c) => c.name },
                { label: 'Jumlah PO', nilai: (c) => c.orders },
                { label: 'Qty (pcs)', nilai: (c) => c.total_qty },
                { label: 'Nilai order (Rp)', nilai: (c) => c.total_value || '' },
              ]} />
          )}>
          <Table>
            <TableHeader>
              <TableRow><TableHead>Pelanggan</TableHead><TableHead className="text-right">Qty</TableHead></TableRow>
            </TableHeader>
            <TableBody>
              {topCustomers.length === 0 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={2} className="p-0 [&>div]:py-8"><EmptyState title="Belum ada PO" /></TableCell>
                </TableRow>
              )}
              {topCustomers.map((c, idx) => (
                <TableRow key={`${c.name}-${idx}`} data-testid={`top-customer-${idx}`}>
                  <TableCell className="max-w-[12rem]">
                    <span className="block truncate font-medium" title={c.name}>{c.name}</span>
                    <span className="text-xs text-muted-foreground">{fmtNum(c.orders)} PO{c.total_value ? ` · ${fmtShortIDR(c.total_value)}` : ''}</span>
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-right tabular-nums">{fmtNum(c.total_qty)} pcs</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </ChartCard>
      </div>

      <SourceTrace rows={data?.sources} domainLabel={data?.domain_label} />

      {/* ── Ambang peringatan & persetujuan PR (popup form) ─────────────── */}
      <FormPopup open={bukaAmbang} onClose={() => setBukaAmbang(false)} ukuran="panjang" judul="Atur ambang"
        keterangan="Berlaku untuk penjadwal harian, kokpit RnD, layar ini, dan persetujuan Permintaan Pengadaan (PR)."
        onSimpan={saveAlertConfig} menyimpan={savingCfg} labelSimpan="Simpan ambang" testId="alert-threshold-form">
        <p className="text-sm font-medium text-foreground">Ambang peringatan (hari)</p>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Isian label="PO — hari sebelum tenggat" htmlFor="po-warn-days">
            <Input id="po-warn-days" type="number" min="0" max="60" className="w-full sm:w-32"
              value={cfgDraft.po_warn_days} data-testid="alert-po-days-input" onChange={setDraft('po_warn_days')} />
          </Isian>
          <Isian label="Piutang — hari sebelum jatuh tempo" htmlFor="ar-warn-days">
            <Input id="ar-warn-days" type="number" min="0" max="60" className="w-full sm:w-32"
              value={cfgDraft.ar_warn_days} data-testid="alert-ar-days-input" onChange={setDraft('ar_warn_days')} />
          </Isian>
          <Isian label="RnD — kuning setelah (hari)" htmlFor="rnd-attention-days">
            <Input id="rnd-attention-days" type="number" min="0" max="60" className="w-full sm:w-32"
              value={cfgDraft.rnd_attention_days} data-testid="alert-rnd-attention-input" onChange={setDraft('rnd_attention_days')} />
          </Isian>
          <Isian label="RnD — merah / terlambat (hari)" htmlFor="rnd-stale-days">
            <Input id="rnd-stale-days" type="number" min="0" max="60" className="w-full sm:w-32"
              value={cfgDraft.rnd_stale_days} data-testid="alert-rnd-stale-input" onChange={setDraft('rnd_stale_days')} />
          </Isian>
        </div>
        <p className="text-xs text-muted-foreground">
          Bawaan PO/piutang {alertCfg?.defaults?.po_warn_days ?? 3} hari · RnD {alertCfg?.defaults?.rnd_attention_days ?? 3}/{alertCfg?.defaults?.rnd_stale_days ?? 7} hari.
        </p>

        {/* Permintaan owner 2026-08-07: "PR bernilai kecil jangan dipaksa lewat 3 tahap." Ambang DIBEKUKAN pada
            tiap PR saat diajukan — mengubahnya hanya memengaruhi PR BARU. */}
        <p className="border-t border-[var(--glass-border)] pt-4 text-sm font-medium text-foreground" data-testid="pr-chain-threshold-form">
          Ambang persetujuan Permintaan Pengadaan (PR)
        </p>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Isian label="Cukup 1 tahap bila nilai ≤ (Rp)" htmlFor="pr-1-stage-max"
            petunjuk={`= ${fmtShortIDR(Number(cfgDraft.pr_1_stage_max) || 0)} · hanya persetujuan departemen`}>
            <MoneyInput id="pr-1-stage-max" value={cfgDraft.pr_1_stage_max} data-testid="pr-1-stage-max-input"
              onChange={setDraft('pr_1_stage_max')} />
          </Isian>
          <Isian label="Cukup 2 tahap bila nilai ≤ (Rp)" htmlFor="pr-2-stage-max"
            petunjuk={`= ${fmtShortIDR(Number(cfgDraft.pr_2_stage_max) || 0)} · departemen + keuangan`}>
            <MoneyInput id="pr-2-stage-max" value={cfgDraft.pr_2_stage_max} data-testid="pr-2-stage-max-input"
              onChange={setDraft('pr_2_stage_max')} />
          </Isian>
        </div>
        <p className="text-xs text-muted-foreground">
          Di atas {fmtShortIDR(Number(cfgDraft.pr_2_stage_max) || 0)} → 3 tahap (departemen + keuangan + final/direksi).
          Ambang dibekukan saat PR diajukan, jadi perubahan di sini hanya berlaku untuk PR baru.
          {alertCfg?.updated_by ? ` Terakhir diubah ${alertCfg.updated_by}.` : ''}
        </p>
      </FormPopup>
    </PageLayout>
  );
}

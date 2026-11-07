/**
 * Penilaian kinerja tahunan (Portal SDM › Manajemen Kinerja) — siklus review tahunan/semesteran untuk KPI/OKR
 * strategis. KPI operasional bulanan ada di tab "KPI bulanan".
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, siklus/templat KPI/penugasan/penilaian = tabel + unduh
 * Excel/CSV (dulu kartu berulang), form = FormPopup, tanggal = DatePicker, status berbahasa Indonesia, warna token.
 * Angka: "Rata-rata skor" dulu "0.00" walau belum ada penilaian final — kini "—" dengan alasan.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { ClipboardCheck, Edit2, Plus, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { toast } from 'sonner';
import { formatDateID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';

const API_BASE = process.env.REACT_APP_BACKEND_URL;

const CYCLE_STATUS = { draft: { label: 'Draf', tone: 'muted' }, active: { label: 'Aktif', tone: 'success' }, closed: { label: 'Ditutup', tone: 'info' } };
const ASSIGNMENT_STATUS = {
  assigned: { label: 'Ditugaskan', tone: 'info' }, in_progress: { label: 'Berjalan', tone: 'warning' },
  review: { label: 'Dinilai', tone: 'primary' }, completed: { label: 'Selesai', tone: 'success' },
};
const REVIEW_STATUS = {
  draft: { label: 'Draf', tone: 'muted' }, self_submitted: { label: 'Penilaian diri terkirim', tone: 'info' },
  manager_review: { label: 'Dinilai atasan', tone: 'warning' }, finalized: { label: 'Final', tone: 'success' },
};
const PERIOD_TYPE = { quarterly: 'Triwulan', half_year: 'Semester', yearly: 'Tahunan' };
const CATEGORY_LABELS = {
  sales: 'Penjualan', quality: 'Kualitas', attendance: 'Kehadiran',
  teamwork: 'Kerja sama', innovation: 'Inovasi',
  productivity: 'Produktivitas', leadership: 'Kepemimpinan',
};
const RATING_LABEL = { 5: 'Sangat baik', 4: 'Baik', 3: 'Cukup', 2: 'Kurang', 1: 'Buruk' };

const fmtDate = (d) => (d ? formatDateID(d) : '—');
const fmtScore = (n) => (n || 0).toFixed(2);
function Status({ map, status }) {
  const c = map[status] || { label: status || '—', tone: 'default' };
  return <StatusBadge status={status} label={c.label} tone={c.tone} />;
}
function BarisAlat({ kiri, kanan }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="min-w-0 text-sm text-muted-foreground">{kiri}</div>
      <div className="flex flex-wrap items-center gap-2">{kanan}</div>
    </div>
  );
}

export default function HRPerformanceModule({ token, defaultTab = 'cycles' }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);
  const [activeTab, setActiveTab] = useState(defaultTab);

  const [summary, setSummary] = useState(null);
  const [cycles, setCycles] = useState([]);
  const [kpis, setKpis] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [reviews, setReviews] = useState([]);
  const [loading, setLoading] = useState(false);

  // KPI Monthly Trend for review reference
  const [kpiTrend, setKpiTrend] = useState(null);
  const [kpiTrendLoading, setKpiTrendLoading] = useState(false);
  const [kpiDialog, setKpiDialog] = useState(null);
  // BUG-FIX 2026-07-25: state ini TIDAK PERNAH dideklarasikan padahal dipakai di
  // 12+ tempat (dialog "Siklus Baru"). Akibatnya render komponen langsung
  // ReferenceError: cycleDialog is not defined ⇒ modul HR Performance blank/crash.
  const [cycleDialog, setCycleDialog] = useState(null);
  const [reviewDialog, setReviewDialog] = useState(null);
  const [reviewActor, setReviewActor] = useState('self');
  const [reviewScores, setReviewScores] = useState([]);
  const [reviewOverallNotes, setReviewOverallNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [s, c, k, a, r] = await Promise.all([
        fetch(`${API_BASE}/api/dewi/hris/performance/summary`, { headers }),
        fetch(`${API_BASE}/api/dewi/hris/performance/cycles`, { headers }),
        fetch(`${API_BASE}/api/dewi/hris/performance/kpis`, { headers }),
        fetch(`${API_BASE}/api/dewi/hris/performance/assignments`, { headers }),
        fetch(`${API_BASE}/api/dewi/hris/performance/reviews`, { headers }),
      ]);
      if (s.ok) setSummary(await s.json());
      if (c.ok) setCycles(await c.json());
      if (k.ok) setKpis(await k.json());
      if (a.ok) setAssignments(await a.json());
      if (r.ok) setReviews(await r.json());
    } catch (e) {
      toast.error('Gagal memuat data penilaian kinerja');
    } finally {
      setLoading(false);
    }
  }, [headers]);

  useEffect(() => { loadAll(); }, [loadAll]);

  // ── Cycle save ──
  const saveCycle = async () => {
    if (!cycleDialog?.cycle_code || !cycleDialog?.name) { toast.error('Kode & nama wajib diisi'); return; }
    setSubmitting(true);
    try {
      const r = await fetch(`${API_BASE}/api/dewi/hris/performance/cycles`, {
        method: 'POST', headers, body: JSON.stringify(cycleDialog),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Gagal');
      toast.success('Siklus berhasil dibuat');
      setCycleDialog(null);
      loadAll();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  // ── KPI save ──
  const saveKpi = async () => {
    if (!kpiDialog?.kpi_code || !kpiDialog?.name) { toast.error('Code & nama wajib diisi'); return; }
    setSubmitting(true);
    try {
      const r = await fetch(`${API_BASE}/api/dewi/hris/performance/kpis`, {
        method: 'POST', headers, body: JSON.stringify(kpiDialog),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Gagal');
      toast.success('Templat KPI berhasil dibuat');
      setKpiDialog(null);
      loadAll();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  // ── Review open ──
  const openReviewDialog = async (review, actor = 'self') => {
    const assignment = assignments.find(a => a.id === review.assignment_id);
    const kpis = assignment?.kpis || [];
    const existingScores = actor === 'self' ? (review.self_scores || []) : (review.manager_scores || []);
    const existingNotes = actor === 'self' ? (review.self_overall_notes || '') : (review.manager_overall_notes || '');
    const scores = kpis.map(k => {
      const existing = existingScores.find(s => s.kpi_id === k.kpi_id);
      return {
        kpi_id: k.kpi_id,
        kpi_name: k.kpi_name,
        target_value: k.target_value,
        target_operator: k.target_operator,
        measurement: k.measurement,
        weight: k.weight,
        actual_value: existing?.actual_value ?? 0,
        rating: existing?.rating ?? 3,
        notes: existing?.notes ?? '',
      };
    });
    setReviewDialog({ ...review, _assignment: assignment });
    setReviewActor(actor);
    setReviewScores(scores);
    setReviewOverallNotes(existingNotes);
    setKpiTrend(null);

    // Fetch KPI monthly trend for this employee
    const empId = review.employee_id || assignment?.employee_id;
    if (empId) {
      setKpiTrendLoading(true);
      try {
        const r = await fetch(`${API_BASE}/api/dewi/kpi/trend/${empId}?limit=12`, { headers });
        if (r.ok) setKpiTrend(await r.json());
      } catch { /* noop */ }
      finally { setKpiTrendLoading(false); }
    }
  };

  const submitReview = async () => {
    if (!reviewDialog) return;
    setSubmitting(true);
    try {
      const payload = {
        actor: reviewActor,
        scores: reviewScores.map(s => ({
          kpi_id: s.kpi_id,
          actual_value: Number(s.actual_value) || 0,
          rating: Number(s.rating),
          notes: s.notes || '',
        })),
        overall_notes: reviewOverallNotes,
      };
      const r = await fetch(`${API_BASE}/api/dewi/hris/performance/reviews/${reviewDialog.id}/submit`, {
        method: 'PUT', headers, body: JSON.stringify(payload),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Gagal mengirim');

      // P2.1: Show raise proposal notification
      if (d.raise_proposal_created) {
        toast.success(
          `Penilaian tersimpan. Skor: ${d.final_score?.toFixed(1)}/5,0`,
          {
            description: `Usulan kenaikan gaji ${d.raise_pct}% otomatis dibuat — perlu persetujuan SDM/atasan.`,
            duration: 7000,
          }
        );
      } else {
        toast.success(`Penilaian ${reviewActor === 'self' ? 'karyawan' : 'atasan'} berhasil dikirim`);
      }
      setReviewDialog(null);
      loadAll();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  const runSeed = async () => {
    setSubmitting(true);
    try {
      const r = await fetch(`${API_BASE}/api/dewi/hris/performance/seed-demo`, { method: 'POST', headers });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Gagal memuat contoh');
      toast.success(`Data contoh dimuat — ${d.counts.cycles} siklus, ${d.counts.kpis} KPI, ${d.counts.assignments} penugasan, ${d.counts.reviews} penilaian`);
      loadAll();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  const adaFinal = (summary?.finalized_reviews || 0) > 0;
  const kolomSiklus = [
    { kunci: 'kode', label: 'Siklus', hp: 'judul', isi: (c) => (
      <div data-testid={`cycle-card-${c.cycle_code}`}><p className="font-medium text-foreground">{c.cycle_code}</p><p className="text-xs text-muted-foreground">{c.name}</p></div>) },
    { kunci: 'jenis', label: 'Jenis', isi: (c) => <span className="text-sm">{PERIOD_TYPE[c.period_type] || c.period_type || '—'}</span> },
    { kunci: 'periode', label: 'Periode', isi: (c) => <span className="text-sm md:whitespace-nowrap">{fmtDate(c.start_date)} – {fmtDate(c.end_date)}</span> },
    { kunci: 'status', label: 'Status', isi: (c) => <Status map={CYCLE_STATUS} status={c.status} /> },
  ];
  const kolomKpi = [
    { kunci: 'nama', label: 'KPI', hp: 'judul', isi: (k) => (
      <div><p className="font-medium text-foreground">{k.name}</p><p className="text-xs text-muted-foreground">{k.kpi_code}</p></div>) },
    { kunci: 'kategori', label: 'Kategori', isi: (k) => <span className="text-sm">{CATEGORY_LABELS[k.category] || k.category}</span> },
    { kunci: 'target', label: 'Target', isi: (k) => <span className="text-sm">{k.target_operator} {k.target_value} {k.measurement}</span> },
    { kunci: 'bobot', label: 'Bobot bawaan', rata: 'kanan', isi: (k) => <span className="tabular-nums">{k.weight_default}%</span> },
  ];
  const kolomPenugasan = [
    { kunci: 'nama', label: 'Karyawan', hp: 'judul', isi: (a) => (
      <div data-testid={`assignment-row-${a.employee_nik}`}><p className="font-medium text-foreground">{a.employee_name}</p><p className="text-xs text-muted-foreground">{a.position}</p></div>) },
    { kunci: 'siklus', label: 'Siklus', isi: (a) => <span className="text-sm">{a.cycle_code}</span> },
    { kunci: 'dept', label: 'Departemen', isi: (a) => <span className="text-sm">{a.department || '—'}</span> },
    { kunci: 'kpi', label: 'KPI', isi: (a) => <span className="text-sm">{(a.kpis || []).length} KPI · bobot {a.total_weight}%</span> },
    { kunci: 'kemajuan', label: 'Kemajuan', isi: (a) => (
      <div className="flex items-center gap-2">
        <div className="h-1.5 w-20 overflow-hidden rounded-full bg-[var(--glass-border)]"><div className="h-full bg-primary" style={{ width: `${a.progress_pct}%` }} /></div>
        <span className="text-sm tabular-nums text-muted-foreground">{a.progress_pct}%</span>
      </div>) },
    { kunci: 'status', label: 'Status', isi: (a) => <Status map={ASSIGNMENT_STATUS} status={a.status} /> },
  ];
  const kolomPenilaian = [
    { kunci: 'nama', label: 'Karyawan', hp: 'judul', isi: (r) => (
      <div data-testid={`review-card-${r.employee_nik}`}><p className="font-medium text-foreground">{r.employee_name}</p><p className="text-xs text-muted-foreground">{r.department} · {r.cycle_code}</p></div>) },
    { kunci: 'diri', label: 'Penilaian diri', isi: (r) => <span className="text-sm">{r.self_submitted_at ? 'Sudah' : 'Belum'}</span> },
    { kunci: 'atasan', label: 'Penilaian atasan', isi: (r) => <span className="text-sm">{r.manager_submitted_at ? 'Sudah' : 'Belum'}</span> },
    { kunci: 'skor', label: 'Skor akhir', rata: 'kanan', isi: (r) => <span className="font-semibold tabular-nums">{r.final_score > 0 ? `${fmtScore(r.final_score)} / 5` : '—'}</span> },
    { kunci: 'status', label: 'Status', isi: (r) => <Status map={REVIEW_STATUS} status={r.status} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="outline" onClick={() => openReviewDialog(r, 'self')} disabled={r.status === 'finalized'}
          data-testid={`btn-review-self-${r.employee_nik}`}><Edit2 />Penilaian diri</Button>
        <Button size="sm" variant="outline" onClick={() => openReviewDialog(r, 'manager')} disabled={r.status === 'finalized' || r.status === 'draft'}
          data-testid={`btn-review-mgr-${r.employee_nik}`}><ClipboardCheck />Penilaian atasan</Button>
      </div>) },
  ];
  const trenTerisi = (kpiTrend?.trend || []).filter(t => t.kpi_final != null);

  return (
    <PageLayout testId="hr-performance-module" headerTestId="hr-performance-header" title="Penilaian kinerja tahunan"
      subtitle="Siklus review tahunan/semesteran untuk KPI strategis. KPI operasional ada di tab KPI bulanan."
      actions={<Button variant="outline" onClick={runSeed} disabled={submitting} data-testid="perf-seed-btn">Muat contoh</Button>}
      tools={
        <Button variant="outline" size="icon" onClick={loadAll} disabled={loading} title="Muat ulang" aria-label="Muat ulang" data-testid="perf-refresh-btn">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      }
      summary={
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="perf-summary-tiles">
          <StatTile label="Siklus aktif" value={summary?.active_cycle?.cycle_code || '—'} testId="tile-active-cycle"
            sub={summary?.active_cycle?.name || 'Belum ada siklus berstatus aktif.'} />
          <StatTile label="Penugasan" value={summary?.total_assignments || 0} testId="tile-assignments"
            sub={`${summary?.completed_assignments || 0} selesai, ${summary?.in_progress || 0} berjalan.`} />
          <StatTile label="Penilaian final" value={summary?.finalized_reviews || 0} testId="tile-finalized"
            sub={`Dari ${summary?.total_reviews || 0} penilaian.`} />
          <StatTile label="Rata-rata skor" value={adaFinal ? fmtScore(summary?.avg_final_score) : '—'} testId="tile-avg-score"
            sub={adaFinal ? 'Skala 1–5, dari penilaian final.' : 'Belum ada penilaian final.'} />
        </div>
      }>
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList data-testid="perf-tabs">
          <TabsTrigger value="cycles" data-testid="tab-cycles">Siklus</TabsTrigger>
          <TabsTrigger value="kpis" data-testid="tab-kpis">KPI & penugasan</TabsTrigger>
          <TabsTrigger value="reviews" data-testid="tab-reviews">Penilaian</TabsTrigger>
        </TabsList>

        <TabsContent value="cycles" className="mt-4 space-y-3">
          <BarisAlat kiri={`${cycles.length} siklus penilaian.`} kanan={<>
            <TombolUnduh namaBerkas="siklus-penilaian" namaLembar="Siklus" baris={cycles} testId="perf-unduh-siklus"
              kolom={[
                { label: 'Kode', nilai: (c) => c.cycle_code }, { label: 'Nama', nilai: (c) => c.name },
                { label: 'Jenis', nilai: (c) => PERIOD_TYPE[c.period_type] || c.period_type || '' },
                { label: 'Mulai', nilai: (c) => fmtDate(c.start_date) }, { label: 'Selesai', nilai: (c) => fmtDate(c.end_date) },
                { label: 'Status', nilai: (c) => CYCLE_STATUS[c.status]?.label || c.status || '' },
              ]} />
            <Button onClick={() => setCycleDialog({
              cycle_code: '', name: '', period_type: 'quarterly',
              start_date: '', end_date: '', status: 'draft', notes: '',
            })} data-testid="btn-create-cycle"><Plus />Siklus baru</Button>
          </>} />
          <TabelData kolom={kolomSiklus} baris={cycles} testId="perf-cycles"
            kosong={<EmptyState testId="cycles-empty" title="Belum ada siklus" description='Klik "Siklus baru" atau "Muat contoh".' />} />
        </TabsContent>

        <TabsContent value="kpis" className="mt-4 space-y-4">
          <div className="space-y-2">
            <BarisAlat kiri={<span className="font-medium text-foreground">Templat KPI ({kpis.length})</span>} kanan={<>
              <TombolUnduh namaBerkas="templat-kpi-tahunan" namaLembar="Templat KPI" baris={kpis} testId="perf-unduh-kpi"
                kolom={[
                  { label: 'Kode', nilai: (k) => k.kpi_code }, { label: 'Nama', nilai: (k) => k.name },
                  { label: 'Kategori', nilai: (k) => CATEGORY_LABELS[k.category] || k.category || '' },
                  { label: 'Target', nilai: (k) => `${k.target_operator} ${k.target_value} ${k.measurement || ''}`.trim() },
                  { label: 'Bobot bawaan (%)', nilai: (k) => k.weight_default },
                ]} />
              <Button variant="outline" onClick={() => setKpiDialog({
                kpi_code: '', name: '', category: 'productivity',
                description: '', measurement: '', target_value: 0,
                target_operator: '>=', weight_default: 20, is_active: true,
              })} data-testid="btn-create-kpi"><Plus />KPI baru</Button>
            </>} />
            <TabelData kolom={kolomKpi} baris={kpis} testId="kpi-list"
              kosong={<EmptyState title="Belum ada templat KPI" />} />
          </div>
          <div className="space-y-2">
            <BarisAlat kiri={<span className="font-medium text-foreground">Penugasan ({assignments.length})</span>} kanan={
              <TombolUnduh namaBerkas="penugasan-kpi-tahunan" namaLembar="Penugasan" baris={assignments} testId="perf-unduh-penugasan"
                kolom={[
                  { label: 'Karyawan', nilai: (a) => a.employee_name }, { label: 'Jabatan', nilai: (a) => a.position || '' },
                  { label: 'Siklus', nilai: (a) => a.cycle_code }, { label: 'Departemen', nilai: (a) => a.department || '' },
                  { label: 'Jumlah KPI', nilai: (a) => (a.kpis || []).length }, { label: 'Total bobot (%)', nilai: (a) => a.total_weight },
                  { label: 'Kemajuan (%)', nilai: (a) => a.progress_pct }, { label: 'Status', nilai: (a) => ASSIGNMENT_STATUS[a.status]?.label || a.status || '' },
                ]} />} />
            <TabelData kolom={kolomPenugasan} baris={assignments} testId="assignment-table"
              kosong={<EmptyState title="Belum ada penugasan" />} />
          </div>
        </TabsContent>

        <TabsContent value="reviews" className="mt-4 space-y-3">
          <BarisAlat kiri={`${reviews.length} penilaian.`} kanan={
            <TombolUnduh namaBerkas="penilaian-tahunan" namaLembar="Penilaian" baris={reviews} testId="perf-unduh-penilaian"
              kolom={[
                { label: 'Karyawan', nilai: (r) => r.employee_name }, { label: 'Departemen', nilai: (r) => r.department || '' },
                { label: 'Siklus', nilai: (r) => r.cycle_code }, { label: 'Penilaian diri', nilai: (r) => (r.self_submitted_at ? 'Sudah' : 'Belum') },
                { label: 'Penilaian atasan', nilai: (r) => (r.manager_submitted_at ? 'Sudah' : 'Belum') },
                { label: 'Skor akhir', nilai: (r) => (r.final_score > 0 ? Number(r.final_score) : '') },
                { label: 'Status', nilai: (r) => REVIEW_STATUS[r.status]?.label || r.status || '' },
              ]} />} />
          <TabelData kolom={kolomPenilaian} baris={reviews} testId="perf-reviews"
            kosong={<EmptyState title="Belum ada penilaian" />} />
        </TabsContent>
      </Tabs>

      {/* ─── Form siklus ─── */}
      <FormPopup open={!!cycleDialog} onClose={() => setCycleDialog(null)} ukuran="pendek" onSimpan={saveCycle} menyimpan={submitting}
        judul="Siklus penilaian baru" testId="cycle-dialog">
        {cycleDialog && (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
              <Isian label="Kode" wajib htmlFor="perf-cyc-kode">
                <Input id="perf-cyc-kode" value={cycleDialog.cycle_code} placeholder="Q3-2026" data-testid="input-cycle-code"
                  onChange={(e) => setCycleDialog({ ...cycleDialog, cycle_code: e.target.value })} />
              </Isian>
              <Isian label="Nama" wajib htmlFor="perf-cyc-nama">
                <Input id="perf-cyc-nama" value={cycleDialog.name} placeholder="Triwulan 3 — 2026" data-testid="input-cycle-name"
                  onChange={(e) => setCycleDialog({ ...cycleDialog, name: e.target.value })} />
              </Isian>
              <Isian label="Jenis">
                <SmartNativeSelect searchable={false} value={cycleDialog.period_type} data-testid="select-cycle-type"
                  onChange={(e) => setCycleDialog({ ...cycleDialog, period_type: e.target.value })}>
                  {Object.entries(PERIOD_TYPE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </SmartNativeSelect>
              </Isian>
              <Isian label="Status">
                <SmartNativeSelect searchable={false} value={cycleDialog.status} data-testid="select-cycle-status"
                  onChange={(e) => setCycleDialog({ ...cycleDialog, status: e.target.value })}>
                  {Object.entries(CYCLE_STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
                </SmartNativeSelect>
              </Isian>
              <Isian label="Tanggal mulai" wajib>
                <DatePicker value={cycleDialog.start_date} testId="input-cycle-start"
                  onChange={(v) => setCycleDialog({ ...cycleDialog, start_date: v })} />
              </Isian>
              <Isian label="Tanggal selesai" wajib>
                <DatePicker value={cycleDialog.end_date} min={cycleDialog.start_date || undefined} testId="input-cycle-end"
                  onChange={(v) => setCycleDialog({ ...cycleDialog, end_date: v })} />
              </Isian>
            </div>
            <Isian label="Catatan" htmlFor="perf-cyc-catatan">
              <Textarea id="perf-cyc-catatan" value={cycleDialog.notes || ''} rows={2}
                onChange={(e) => setCycleDialog({ ...cycleDialog, notes: e.target.value })} />
            </Isian>
          </>
        )}
      </FormPopup>

      {/* ─── Form templat KPI ─── */}
      <FormPopup open={!!kpiDialog} onClose={() => setKpiDialog(null)} ukuran="pendek" onSimpan={saveKpi} menyimpan={submitting}
        judul="Templat KPI baru" testId="kpi-dialog">
        {kpiDialog && (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
              <Isian label="Kode" wajib htmlFor="perf-kpi-kode">
                <Input id="perf-kpi-kode" value={kpiDialog.kpi_code} data-testid="input-kpi-code"
                  onChange={(e) => setKpiDialog({ ...kpiDialog, kpi_code: e.target.value })} />
              </Isian>
              <Isian label="Nama" wajib htmlFor="perf-kpi-nama">
                <Input id="perf-kpi-nama" value={kpiDialog.name} data-testid="input-kpi-name"
                  onChange={(e) => setKpiDialog({ ...kpiDialog, name: e.target.value })} />
              </Isian>
              <Isian label="Kategori">
                <SmartNativeSelect searchable={false} value={kpiDialog.category} data-testid="select-kpi-category"
                  onChange={(e) => setKpiDialog({ ...kpiDialog, category: e.target.value })}>
                  {Object.entries(CATEGORY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </SmartNativeSelect>
              </Isian>
              <Isian label="Bobot bawaan (%)" htmlFor="perf-kpi-bobot">
                <Input id="perf-kpi-bobot" type="number" min={0} max={100} value={kpiDialog.weight_default}
                  onChange={(e) => setKpiDialog({ ...kpiDialog, weight_default: Number(e.target.value) })} />
              </Isian>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <Isian label="Pembanding">
                <SmartNativeSelect searchable={false} value={kpiDialog.target_operator}
                  onChange={(e) => setKpiDialog({ ...kpiDialog, target_operator: e.target.value })}>
                  <option value=">=">{'≥'}</option>
                  <option value="<=">{'≤'}</option>
                  <option value="=">=</option>
                  <option value=">">{'>'}</option>
                  <option value="<">{'<'}</option>
                </SmartNativeSelect>
              </Isian>
              <Isian label="Target" htmlFor="perf-kpi-target">
                <Input id="perf-kpi-target" type="number" value={kpiDialog.target_value}
                  onChange={(e) => setKpiDialog({ ...kpiDialog, target_value: Number(e.target.value) })} />
              </Isian>
              <Isian label="Satuan" htmlFor="perf-kpi-satuan">
                <Input id="perf-kpi-satuan" value={kpiDialog.measurement} placeholder="%"
                  onChange={(e) => setKpiDialog({ ...kpiDialog, measurement: e.target.value })} />
              </Isian>
            </div>
            <Isian label="Deskripsi" htmlFor="perf-kpi-desk">
              <Textarea id="perf-kpi-desk" rows={2} value={kpiDialog.description || ''}
                onChange={(e) => setKpiDialog({ ...kpiDialog, description: e.target.value })} />
            </Isian>
          </>
        )}
      </FormPopup>

      {/* ─── Form penilaian ─── */}
      <FormPopup open={!!reviewDialog} onClose={() => setReviewDialog(null)} ukuran="panjang" onSimpan={submitReview} menyimpan={submitting}
        bisaSimpan={reviewScores.length > 0} testId="review-dialog"
        judul={`${reviewActor === 'self' ? 'Penilaian diri' : 'Penilaian atasan'} — ${reviewDialog?.employee_name || ''}`}
        keterangan={reviewDialog ? `Siklus ${reviewDialog.cycle_code} · ${reviewDialog.department || '—'}` : undefined}
        labelSimpan={`Kirim ${reviewActor === 'self' ? 'penilaian diri' : 'penilaian atasan'}`}>
        {reviewDialog && (
          <>
            {(kpiTrendLoading || (kpiTrend?.trend?.length > 0)) && (
              <Notice tone="info" title="Acuan: KPI bulanan" testId="kpi-trend-panel">
                {kpiTrendLoading ? 'Memuat data KPI…' : (
                  <>
                    {trenTerisi.length > 0 && (
                      <p>Rata-rata {(trenTerisi.reduce((a, t) => a + t.kpi_final, 0) / trenTerisi.length).toFixed(2)}/100 dari {trenTerisi.length} bulan.</p>
                    )}
                    <p className="mt-1">
                      {kpiTrend.trend.map((t) => `${t.period_name || `Bulan ${t.month}`}: ${t.kpi_final != null ? t.kpi_final.toFixed(0) : '—'}${t.grade ? ` (${t.grade})` : ''}`).join(' · ')}
                    </p>
                  </>
                )}
              </Notice>
            )}

            {reviewScores.length === 0 && (
              <p className="py-4 text-center text-sm text-muted-foreground">Penugasan ini belum punya KPI, jadi belum bisa dinilai.</p>
            )}

            {reviewScores.length > 0 && (
              <div className="divide-y divide-[var(--glass-border)] rounded-lg border border-[var(--glass-border)]">
                {reviewScores.map((s, idx) => (
                  <div key={s.kpi_id} className="space-y-2 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-sm font-medium text-foreground">{s.kpi_name}</p>
                      <p className="text-xs text-muted-foreground">Target {s.target_operator} {s.target_value} {s.measurement} · bobot {s.weight}%</p>
                    </div>
                    <div className="grid gap-3 sm:grid-cols-3">
                      <Isian label="Nilai aktual">
                        <Input type="number" value={s.actual_value} data-testid={`input-actual-${idx}`}
                          onChange={(e) => setReviewScores(reviewScores.map((rs, i) => i === idx ? { ...rs, actual_value: e.target.value } : rs))} />
                      </Isian>
                      <Isian label="Nilai (1–5)">
                        <SmartNativeSelect searchable={false} value={String(s.rating)} data-testid={`select-rating-${idx}`}
                          onChange={(e) => setReviewScores(reviewScores.map((rs, i) => i === idx ? { ...rs, rating: Number(e.target.value) } : rs))}>
                          {[1, 2, 3, 4, 5].map(n => <option key={n} value={String(n)}>{n} — {RATING_LABEL[n]}</option>)}
                        </SmartNativeSelect>
                      </Isian>
                      <Isian label="Catatan">
                        <Input value={s.notes || ''} placeholder="Catatan"
                          onChange={(e) => setReviewScores(reviewScores.map((rs, i) => i === idx ? { ...rs, notes: e.target.value } : rs))} />
                      </Isian>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <Isian label="Catatan keseluruhan" htmlFor="perf-rev-catatan">
              <Textarea id="perf-rev-catatan" value={reviewOverallNotes} rows={2} placeholder="Catatan keseluruhan penilaian"
                onChange={(e) => setReviewOverallNotes(e.target.value)} />
            </Isian>
          </>
        )}
      </FormPopup>
    </PageLayout>
  );
}

/**
 * KPI bulanan (Portal SDM › Manajemen Kinerja) — evaluasi operasional per periode:
 * kinerja 60% · sikap 20% · absensi 20%. Review tahunan ada di tab "Penilaian tahunan".
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout (di dalam hub: judul hub, bagian KPI jadi pil), daftar
 * periode/soal/sasaran = tabel + unduh Excel/CSV (dulu kartu berulang), semua form = FormPopup, detail hasil =
 * DetailPopup, konfirmasi = confirmDialog (dulu window.confirm), tanggal = DatePicker, warna token, bahasa
 * Indonesia (Perform → kinerja, Attitude → sikap, Goals → sasaran, Publish → terbitkan).
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import {
  Award, BarChart3, CheckCircle2, ChevronDown, ClipboardList, Clock, Download, Edit2, Loader2, Plus, RefreshCw,
  Save, Send, Trash2, X, AlertCircle, BookOpen,
} from 'lucide-react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, BarChart, Bar,
} from 'recharts';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import DatePicker from '@/components/ui/date-picker';
import { EmployeeSelect } from './hr/hrPickers';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { toast } from 'sonner';
import KPIGamificationTab from './KPIGamificationTab';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatDateID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge as Lencana } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;
const kpi = (path, opts = {}) => fetch(`${API}/api/dewi/kpi${path}`, opts);

const GRADE_CFG = {
  A: { tone: 'success', label: 'Sangat baik', raise: '10%' },
  B: { tone: 'info', label: 'Baik', raise: '7%' },
  C: { tone: 'warning', label: 'Cukup', raise: '-' },
  D: { tone: 'warning', label: 'Kurang', raise: '-' },
  E: { tone: 'danger', label: 'Sangat kurang', raise: '-' },
};

const STATUS_CFG = {
  draft: { tone: 'muted', label: 'Draf' },
  open: { tone: 'success', label: 'Buka' },
  closed: { tone: 'warning', label: 'Ditutup' },
  finalized: { tone: 'info', label: 'Final' },
};

const EVAL_TYPE_CFG = {
  self: { label: 'Penilaian diri', weight: '20%' },
  peer: { label: 'Penilaian rekan', weight: '20%' },
  supervisor_to_staff: { label: 'Atasan → staf', weight: '35%' },
  staff_to_supervisor: { label: 'Staf → atasan', weight: '25%' },
};

const GOAL_STATUS = {
  achieved: { label: 'Tercapai', tone: 'success', bar: 'bg-[hsl(var(--success))]' },
  on_track: { label: 'Sesuai jalur', tone: 'info', bar: 'bg-primary' },
  at_risk: { label: 'Berisiko', tone: 'warning', bar: 'bg-[hsl(var(--warning))]' },
  missed: { label: 'Terlewat', tone: 'danger', bar: 'bg-[hsl(var(--destructive))]' },
};

const fmtScore = (n) => (n === null || n === undefined) ? '—' : Number(n).toFixed(1);
const fmtPct = (n) => (n === null || n === undefined) ? '—' : `${Number(n).toFixed(1)}%`;
const SUMBU = { fontSize: 12, fill: 'hsl(var(--muted-foreground))' };
const TOOLTIP = { background: 'var(--card-surface)', border: '1px solid var(--glass-border)', borderRadius: 8, fontSize: 12 };

function GradeBadge({ grade }) {
  if (!grade) return <span className="text-sm text-muted-foreground">—</span>;
  const cfg = GRADE_CFG[grade] || {};
  return <Lencana status={`grade-${grade}`} label={grade} tone={cfg.tone} />;
}

function StatusBadge({ status }) {
  const cfg = STATUS_CFG[status] || STATUS_CFG.draft;
  return <Lencana status={status} label={cfg.label} tone={cfg.tone} />;
}

function ScoreBar({ score, max = 100 }) {
  const pct = Math.min(100, Math.max(0, (score / max) * 100));
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--glass-border)]">
      <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${pct}%` }} />
    </div>
  );
}

/** Baris judul kecil + alat di dalam satu bagian KPI. */
function BarisAlat({ kiri, kanan }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="min-w-0 text-sm text-muted-foreground">{kiri}</div>
      <div className="flex flex-wrap items-center gap-2">{kanan}</div>
    </div>
  );
}

const Tick = ({ ok }) => (ok
  ? <CheckCircle2 className="mx-auto h-4 w-4 text-[hsl(var(--success-text))]" aria-label="Sudah" />
  : <Clock className="mx-auto h-4 w-4 text-muted-foreground" aria-label="Belum" />);

export default function HRKPIModule({ token }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);
  const [tab, setTab] = useState('periods');

  const [periods, setPeriods] = useState([]);
  const [questions, setQuestions] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [selectedPeriod, setSelectedPeriod] = useState(null);
  const [progressData, setProgressData] = useState(null);
  const [reportData, setReportData] = useState(null);
  const [performData, setPerformData] = useState([]);
  const [bulkMode, setBulkMode] = useState(false);
  const [bulkScores, setBulkScores] = useState({});
  const [bulkSaving, setBulkSaving] = useState(false);
  const [fairnessData, setFairnessData] = useState(null);
  const [fairnessLoading, setFairnessLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [calculating, setCalculating] = useState(false);

  const loadFairness = useCallback(async (pid) => {
    if (!pid) return;
    setFairnessLoading(true);
    try {
      const r = await kpi(`/fairness/${pid}`, { headers });
      const d = await r.json();
      setFairnessData(d);
    } catch (e) { console.error(e); }
    finally { setFairnessLoading(false); }
  }, [headers]);

  const handleBulkSave = async () => {
    if (!selectedPeriod) return;
    const entries = Object.entries(bulkScores).filter(([, v]) => v.perform_score !== '' && v.perform_score !== null && v.perform_score !== undefined);
    if (!entries.length) { toast.error('Tidak ada nilai yang diinput'); return; }
    setBulkSaving(true);
    try {
      const payload = entries.map(([employee_id, v]) => ({
        employee_id,
        perform_score: parseFloat(v.perform_score) || 0,
        notes: v.notes || '',
      }));
      const r = await kpi(`/perform/${selectedPeriod.period_id}/bulk`, {
        method: 'POST', headers, body: JSON.stringify({ scores: payload }),
      });
      const d = await r.json();
      if (!r.ok) { toast.error(d.detail || 'Gagal simpan'); return; }
      toast.success(`${d.saved} nilai kinerja disimpan, ${d.skipped} dilewati`);
      setBulkScores({});
      loadPerform(selectedPeriod.period_id);
    } catch (e) { toast.error('Gagal menyimpan'); }
    finally { setBulkSaving(false); }
  };

  // Trend & Goals state
  const [trendEmployeeId, setTrendEmployeeId] = useState('');
  const [trendData, setTrendData] = useState(null);
  const [companyTrend, setCompanyTrend] = useState(null);
  const [goals, setGoals] = useState([]);
  const [goalsPeriodId, setGoalsPeriodId] = useState('');
  const [goalsEmployeeId, setGoalsEmployeeId] = useState('');
  const [goalDialog, setGoalDialog] = useState(null);
  const [kpiStats, setKpiStats] = useState(null);
  const [trendLoading, setTrendLoading] = useState(false);
  const [goalsLoading, setGoalsLoading] = useState(false);

  // Dialogs
  const [periodDialog, setPeriodDialog] = useState(null);
  const [questionDialog, setQuestionDialog] = useState(null);
  const [performDialog, setPerformDialog] = useState(null);
  const [resultDialog, setResultDialog] = useState(null);

  const loadPeriods = useCallback(async () => {
    try {
      const r = await kpi('/periods', { headers });
      const d = await r.json();
      setPeriods(d.periods || []);
    } catch (e) { console.error(e); }
  }, [headers]);

  const loadQuestions = useCallback(async () => {
    try {
      const r = await kpi('/questions', { headers });
      const d = await r.json();
      setQuestions(d.questions || []);
    } catch (e) { console.error(e); }
  }, [headers]);

  const loadEmployees = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/rahaza/employees?active_only=true&limit=500`, { headers });
      const d = await r.json();
      setEmployees(Array.isArray(d) ? d : (d.items || d.rows || d.employees || []));
    } catch (e) { console.error(e); }
  }, [headers]);

  const loadProgress = useCallback(async (pid) => {
    if (!pid) return;
    try {
      const r = await kpi(`/monitor/${pid}`, { headers });
      const d = await r.json();
      setProgressData(d);
    } catch (e) { console.error(e); }
  }, [headers]);

  const loadReport = useCallback(async (pid) => {
    if (!pid) return;
    try {
      const r = await kpi(`/reports/summary/${pid}`, { headers });
      const d = await r.json();
      setReportData(d);
    } catch (e) { console.error(e); }
  }, [headers]);

  const loadPerform = useCallback(async (pid) => {
    if (!pid) return;
    try {
      const r = await kpi(`/perform/${pid}`, { headers });
      const d = await r.json();
      setPerformData(d.perform_scores || []);
    } catch (e) { console.error(e); }
  }, [headers]);

  const loadTrend = useCallback(async (empId) => {
    if (!empId) return;
    setTrendLoading(true);
    try {
      const r = await kpi(`/trend/${empId}`, { headers });
      const d = await r.json();
      setTrendData(d);
    } catch (e) { console.error(e); }
    finally { setTrendLoading(false); }
  }, [headers]);

  const loadCompanyTrend = useCallback(async () => {
    try {
      const r = await kpi('/trend', { headers });
      const d = await r.json();
      setCompanyTrend(d);
    } catch (e) { console.error(e); }
  }, [headers]);

  const loadGoals = useCallback(async (pid, empId) => {
    setGoalsLoading(true);
    try {
      const params = new URLSearchParams();
      if (pid) params.set('period_id', pid);
      if (empId) params.set('employee_id', empId);
      const r = await kpi(`/goals?${params}`, { headers });
      const d = await r.json();
      setGoals(d.goals || []);
    } catch (e) { console.error(e); }
    finally { setGoalsLoading(false); }
  }, [headers]);

  const loadKpiStats = useCallback(async () => {
    try {
      const r = await kpi('/stats', { headers });
      const d = await r.json();
      setKpiStats(d);
    } catch (e) { console.error(e); }
  }, [headers]);

  useEffect(() => {
    loadPeriods();
    loadEmployees();
    loadKpiStats();
  }, [loadPeriods, loadEmployees, loadKpiStats]);

  useEffect(() => {
    if (tab === 'questions') loadQuestions();
    if (tab === 'perform' && selectedPeriod) loadPerform(selectedPeriod.period_id);
    if (tab === 'monitor' && selectedPeriod) loadProgress(selectedPeriod.period_id);
    if (tab === 'reports' && selectedPeriod) { loadReport(selectedPeriod.period_id); }
    if (tab === 'trend') { loadCompanyTrend(); if (trendEmployeeId) loadTrend(trendEmployeeId); }
    if (tab === 'goals') { loadGoals(goalsPeriodId, goalsEmployeeId); }
  }, [tab, selectedPeriod, loadQuestions, loadProgress, loadReport, loadPerform, loadCompanyTrend, loadTrend, trendEmployeeId, loadGoals, goalsPeriodId, goalsEmployeeId, loadKpiStats]);

  const handleSeedDefaults = async () => {
    const r = await kpi('/questions/seed-defaults', { method: 'POST', headers });
    const d = await r.json();
    toast(d.message || 'Selesai');
    loadQuestions();
  };

  const handleSavePeriod = async (form) => {
    const isEdit = !!form.period_id;
    const url = isEdit ? `/periods/${form.period_id}` : '/periods';
    const method = isEdit ? 'PUT' : 'POST';
    const r = await kpi(url, { method, headers, body: JSON.stringify(form) });
    const d = await r.json();
    if (!r.ok) { toast.error(d.detail || 'Gagal menyimpan periode'); return; }
    toast.success(isEdit ? 'Periode disimpan' : 'Periode dibuat');
    setPeriodDialog(null);
    loadPeriods();
  };

  const handleChangeStatus = async (period, newStatus) => {
    const r = await kpi(`/periods/${period.period_id}`, {
      method: 'PUT', headers, body: JSON.stringify({ status: newStatus }),
    });
    const d = await r.json();
    if (!r.ok) { toast.error(d.detail || 'Gagal ubah status'); return; }
    toast.success(`Status diubah ke "${STATUS_CFG[newStatus]?.label}"`);
    loadPeriods();
    if (selectedPeriod?.period_id === period.period_id) {
      setSelectedPeriod(d.period);
    }
  };

  const handleDeletePeriod = async (period) => {
    if (!(await confirmDialog({ title: `Hapus periode "${period.name}"?`, danger: true }))) return;
    const r = await kpi(`/periods/${period.period_id}`, { method: 'DELETE', headers });
    const d = await r.json();
    if (!r.ok) { toast.error(d.detail || 'Gagal hapus'); return; }
    toast.success('Periode dihapus');
    loadPeriods();
    if (selectedPeriod?.period_id === period.period_id) setSelectedPeriod(null);
  };

  const handleSaveQuestion = async (form) => {
    const isEdit = !!form.question_id;
    const url = isEdit ? `/questions/${form.question_id}` : '/questions';
    const method = isEdit ? 'PUT' : 'POST';
    const r = await kpi(url, { method, headers, body: JSON.stringify(form) });
    const d = await r.json();
    if (!r.ok) { toast.error(d.detail || 'Gagal'); return; }
    toast.success(isEdit ? 'Pertanyaan disimpan' : 'Pertanyaan ditambahkan');
    setQuestionDialog(null);
    loadQuestions();
  };

  const handleDeleteQuestion = async (qid) => {
    if (!(await confirmDialog({ title: 'Nonaktifkan pertanyaan ini?', danger: true }))) return;
    const r = await kpi(`/questions/${qid}`, { method: 'DELETE', headers });
    if (!r.ok) { toast.error('Gagal menonaktifkan pertanyaan'); return; }  // 2026-11-06 (pola P6): dulu selalu "berhasil"
    toast.success('Pertanyaan dinonaktifkan');
    loadQuestions();
  };

  const handleSavePerform = async (form) => {
    const r = await kpi(`/perform/${form.period_id}/${form.employee_id}`, {
      method: 'PUT', headers, body: JSON.stringify(form),
    });
    const d = await r.json();
    if (!r.ok) { toast.error(d.detail || 'Gagal'); return; }
    toast.success('Nilai kinerja disimpan');
    setPerformDialog(null);
    loadPerform(form.period_id);
  };

  const handleCalculate = async () => {
    if (!selectedPeriod) return;
    setCalculating(true);
    try {
      const r = await kpi(`/results/${selectedPeriod.period_id}/calculate`, { method: 'POST', headers });
      const d = await r.json();
      if (!r.ok) { toast.error(d.detail || 'Gagal kalkulasi'); return; }
      toast.success(`KPI dihitung untuk ${d.calculated} karyawan`);
      loadReport(selectedPeriod.period_id);
    } finally {
      setCalculating(false);
    }
  };

  const handlePublish = async (force = false) => {
    if (!selectedPeriod) return;
    if (!force && !(await confirmDialog({ title: 'Terbitkan hasil KPI?', body: 'Karyawan akan bisa melihat hasilnya.', confirmLabel: 'Terbitkan' }))) return;
    const r = await kpi(`/results/${selectedPeriod.period_id}/publish`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ force }),
    });
    const d = await r.json();
    if (!r.ok) { toast.error(d.detail || 'Gagal menerbitkan'); return; }
    // Completion warning
    if (d.warning) {
      if (await confirmDialog({
        title: 'Data penilaian belum lengkap', body: `${d.message} Lanjutkan menerbitkan dengan data yang ada?`, confirmLabel: 'Tetap terbitkan',
      })) {
        return handlePublish(true);
      }
      return;
    }
    const raiseMsg = d.raise_proposals
      ? ` | ${d.raise_proposals.created} usulan kenaikan gaji otomatis dibuat`
      : '';
    toast.success(`${d.published} hasil KPI diterbitkan (${d.completion_pct}% lengkap)${raiseMsg}`, {
      description: d.raise_proposals?.created > 0
        ? 'Buka SDM → Penggajian → Kenaikan gaji untuk menyetujui usulan.'
        : undefined,
      duration: 6000,
    });
    loadPeriods();
    loadReport(selectedPeriod.period_id);
    loadKpiStats();
  };

  // Sprint 42 — Generate raise proposals from this KPI period (Grade A/B → 10%/7%)
  const [generatingRaise, setGeneratingRaise] = useState(false);
  const handleGenerateRaiseProposals = async () => {
    if (!selectedPeriod) return;
    if (!(await confirmDialog({
      title: 'Buat usulan kenaikan gaji?',
      body: 'Untuk semua karyawan grade A (10%) atau B (7%) di periode ini. Usulan masuk persetujuan berjenjang: atasan lalu SDM. '
        + 'Karyawan yang sudah punya usulan aktif untuk periode ini dilewati.',
      confirmLabel: 'Buat usulan',
    }))) return;

    setGeneratingRaise(true);
    try {
      const API_URL = process.env.REACT_APP_BACKEND_URL;
      const r = await fetch(
        `${API_URL}/api/rahaza/salary-adjustments/generate-from-kpi/${selectedPeriod.period_id}`,
        { method: 'POST', headers }
      );
      const d = await r.json();
      if (!r.ok) {
        toast.error(d.detail || 'Gagal membuat usulan');
        return;
      }
      toast.success(
        `${d.message || `Berhasil ${d.created} usulan, ${d.skipped} di-skip`}`,
        {
          description: `Buka menu SDM → Penggajian → Kenaikan gaji untuk menyetujui.`,
          duration: 5000,
        }
      );
    } catch (e) {
      toast.error(e.message || 'Gagal membuat usulan');
    } finally {
      setGeneratingRaise(false);
    }
  };

  const empOptions = employees.map(e => ({ value: e.id, label: `${e.employee_code} — ${e.name}` }));

  // RC-UI-03: client-side pagination (10/page) for KPI periods & goals lists
  const periodsPg = useClientPagination(periods, 10);
  const goalsPg   = useClientPagination(goals, 10);
  const namaKaryawan = (id) => employees.find(e => e.id === id);
  const pilihPeriodeDulu = (
    <EmptyState title="Pilih periode terlebih dahulu" description='Klik salah satu periode di bagian "Periode".'
      action={<Button variant="outline" onClick={() => setTab('periods')}>Buka daftar periode</Button>} />
  );

  // ── Kolom tabel ──
  const kolomPeriode = [
    { kunci: 'nama', label: 'Periode', hp: 'judul', isi: (p) => (
      <div className="min-w-0">
        <p className="font-medium text-foreground">
          {p.name}
          {selectedPeriod?.period_id === p.period_id && <Lencana className="ml-2 align-middle" status="dipilih" label="Dipilih" tone="primary" />}
        </p>
        <p className="text-xs text-muted-foreground">
          {p.period_from && p.period_to ? `${formatDateID(p.period_from)} – ${formatDateID(p.period_to)}` : 'Tanggal belum diatur'}
        </p>
      </div>) },
    { kunci: 'hari', label: 'Hari kerja', rata: 'kanan', isi: (p) => <span className="tabular-nums">{p.working_days ?? '—'}</span> },
    { kunci: 'peserta', label: 'Peserta', rata: 'kanan', isi: (p) => <span className="tabular-nums">{p.participant_count || 0}</span> },
    { kunci: 'status', label: 'Status', isi: (p) => <StatusBadge status={p.status} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (p) => (
      <div className="flex justify-end gap-2">
        {p.status === 'draft' && <Button size="sm" variant="outline" onClick={() => handleChangeStatus(p, 'open')}>Buka formulir</Button>}
        {p.status === 'open' && <Button size="sm" variant="outline" onClick={() => handleChangeStatus(p, 'closed')}>Tutup formulir</Button>}
        {p.status === 'closed' && (
          <Button size="sm" variant="success" onClick={() => { setSelectedPeriod(p); setTab('reports'); setTimeout(() => handlePublish(), 100); }}>
            <Send />Terbitkan hasil
          </Button>
        )}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="sm" variant="ghost" aria-label="Aksi lainnya" title="Aksi lainnya">Lainnya<ChevronDown /></Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => setPeriodDialog(p)}><Edit2 className="mr-2 h-4 w-4" />Ubah</DropdownMenuItem>
            {p.status === 'draft' && (
              <DropdownMenuItem onSelect={() => handleDeletePeriod(p)} className="text-[hsl(var(--danger-text))]">
                <Trash2 className="mr-2 h-4 w-4" />Hapus
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>) },
  ];

  const soalUrut = Object.keys(EVAL_TYPE_CFG).flatMap(type => questions.filter(q => q.eval_type === type));
  const kolomSoal = [
    { kunci: 'soal', label: 'Pertanyaan', hp: 'judul', isi: (q) => <span className="block text-sm md:max-w-[28rem]">{q.question_text}</span> },
    { kunci: 'jenis', label: 'Jenis penilaian', isi: (q) => (
      <span className="text-sm">{EVAL_TYPE_CFG[q.eval_type]?.label || '—'} <span className="text-muted-foreground">({EVAL_TYPE_CFG[q.eval_type]?.weight})</span></span>) },
    { kunci: 'kategori', label: 'Kategori', isi: (q) => <span className="text-sm">{q.category}</span> },
    { kunci: 'bobot', label: 'Bobot', rata: 'kanan', isi: (q) => <span className="tabular-nums">{(q.category_weight * 100).toFixed(0)}%</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (q) => (
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="outline" onClick={() => setQuestionDialog(q)}><Edit2 />Ubah</Button>
        <Button size="sm" variant="destructive" onClick={() => handleDeleteQuestion(q.question_id)}>Nonaktifkan</Button>
      </div>) },
  ];

  const barisKinerja = (selectedPeriod?.participant_employee_ids || []).map((empId) => {
    const emp = namaKaryawan(empId);
    const perf = performData.find(p => p.employee_id === empId);
    return { empId, emp, perf };
  });

  const kolomHasil = [
    { kunci: 'nama', label: 'Karyawan', hp: 'judul', isi: (r) => (
      <div><p className="font-medium text-foreground">{r.employee_name}</p><p className="text-xs text-muted-foreground">{r.employee_code}</p></div>) },
    { kunci: 'kinerja', label: 'Kinerja', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtScore(r.perform_score)}</span> },
    { kunci: 'sikap', label: 'Sikap', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtScore(r.attitude_score)}</span> },
    { kunci: 'absensi', label: 'Absensi', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtScore(r.absensi_score)}</span> },
    { kunci: 'final', label: 'KPI final', rata: 'kanan', isi: (r) => <span className="font-semibold tabular-nums">{fmtScore(r.kpi_final)}</span> },
    { kunci: 'grade', label: 'Grade', isi: (r) => <GradeBadge grade={r.grade} /> },
    { kunci: 'status', label: 'Status', isi: (r) => (r.publish_status === 'published'
      ? <Lencana status="published" label="Terbit" tone="success" /> : <Lencana status="draft" label="Draf" tone="muted" />) },
    { kunci: 'pdf', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <Button size="icon-sm" variant="ghost" title="Unduh PDF" aria-label="Unduh PDF"
        onClick={() => window.open(`${API}/api/dewi/kpi/results/${selectedPeriod.period_id}/${r.employee_id}/pdf?token=${token}`, '_blank')}>
        <Download />
      </Button>) },
  ];

  const kolomSasaran = [
    { kunci: 'judul', label: 'Sasaran', hp: 'judul', isi: (g) => (
      <div className="min-w-0 md:max-w-[22rem]">
        <p className="font-medium text-foreground">{g.title}</p>
        {g.description && <p className="truncate text-xs text-muted-foreground" title={g.description}>{g.description}</p>}
      </div>) },
    { kunci: 'karyawan', label: 'Karyawan', isi: (g) => <span className="text-sm">{g.employee_name || '—'}</span> },
    { kunci: 'periode', label: 'Periode', isi: (g) => <span className="text-sm">{g.period_name || '—'}</span> },
    { kunci: 'kemajuan', label: 'Kemajuan', isi: (g) => {
      const pct = g.progress_pct || 0;
      const st = GOAL_STATUS[g.status];
      return (
        <div className="w-44 max-w-full">
          <div className="flex justify-between text-xs text-muted-foreground"><span>{g.actual_value} / {g.target_value} {g.unit}</span><span className="tabular-nums">{pct.toFixed(1)}%</span></div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[var(--glass-border)]">
            <div className={`h-full rounded-full ${st?.bar || 'bg-muted-foreground'}`} style={{ width: `${Math.min(100, pct)}%` }} />
          </div>
        </div>
      );
    } },
    { kunci: 'status', label: 'Status', isi: (g) => {
      const st = GOAL_STATUS[g.status];
      return st ? <Lencana status={g.status} label={st.label} tone={st.tone} /> : <span className="text-muted-foreground">—</span>;
    } },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (goal) => (
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="outline" onClick={() => setGoalDialog(goal)}><Edit2 />Ubah</Button>
        <Button size="sm" variant="destructive" onClick={async () => {
          if (!(await confirmDialog({ title: 'Hapus sasaran ini?', danger: true, confirmLabel: 'Hapus' }))) return;
          const r = await kpi(`/goals/${goal.goal_id}`, { method: 'DELETE', headers });
          if (!r.ok) { toast.error('Gagal menghapus sasaran'); return; }  // 2026-11-06 (pola P6): dulu selalu "berhasil"
          toast.success('Sasaran dihapus');
          loadGoals(goalsPeriodId, goalsEmployeeId);
        }}><Trash2 />Hapus</Button>
      </div>) },
  ];

  const rs = reportData?.summary;

  return (
    <PageLayout testId="hr-kpi-module" title="KPI bulanan"
      subtitle="Evaluasi operasional per periode: kinerja 60%, sikap 20%, absensi 20%."
      tools={
        <Button variant="outline" size="icon" onClick={() => { loadPeriods(); loadEmployees(); }} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw />
        </Button>
      }>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="h-auto flex-wrap">
          <TabsTrigger value="periods">Periode</TabsTrigger>
          <TabsTrigger value="questions">Bank soal</TabsTrigger>
          <TabsTrigger value="perform">Nilai kinerja</TabsTrigger>
          <TabsTrigger value="monitor">Kemajuan</TabsTrigger>
          <TabsTrigger value="reports">Laporan</TabsTrigger>
          <TabsTrigger value="trend">Tren KPI</TabsTrigger>
          <TabsTrigger value="goals">Sasaran</TabsTrigger>
          <TabsTrigger value="gamifikasi">Gamifikasi</TabsTrigger>
        </TabsList>

        {/* ── PERIODE ── */}
        <TabsContent value="periods" className="mt-4 space-y-3">
          <BarisAlat
            kiri={selectedPeriod ? <>Periode terpilih: <span className="font-medium text-foreground">{selectedPeriod.name}</span> — dipakai di Nilai kinerja, Kemajuan, dan Laporan.</>
              : `${periods.length} periode. Klik satu periode untuk memilihnya.`}
            kanan={<>
              <TombolUnduh namaBerkas="periode-kpi" namaLembar="Periode" baris={periods} testId="kpi-unduh-periode"
                kolom={[
                  { label: 'Periode', nilai: (p) => p.name }, { label: 'Mulai', nilai: (p) => formatDateID(p.period_from) },
                  { label: 'Selesai', nilai: (p) => formatDateID(p.period_to) }, { label: 'Hari kerja', nilai: (p) => p.working_days ?? '' },
                  { label: 'Peserta', nilai: (p) => p.participant_count || 0 }, { label: 'Status', nilai: (p) => (STATUS_CFG[p.status] || STATUS_CFG.draft).label },
                ]} />
              <Button onClick={() => setPeriodDialog({ participant_employee_ids: [], supervisor_assignments: [] })} data-testid="kpi-new-period">
                <Plus />Buat periode
              </Button>
            </>} />
          <TabelData kolom={kolomPeriode} baris={periodsPg.paged} kunci={(p) => p.period_id} onKlikBaris={setSelectedPeriod} testId="kpi-periods"
            kosong={<EmptyState title="Belum ada periode KPI"
              action={<Button onClick={() => setPeriodDialog({ participant_employee_ids: [], supervisor_assignments: [] })}><Plus />Buat periode pertama</Button>} />} />
          {periodsPg.total > 10 && <PaginationLite page={periodsPg.page} totalPages={periodsPg.totalPages} total={periodsPg.total} pageSize={10} onPageChange={periodsPg.setPage} />}
        </TabsContent>

        {/* ── BANK SOAL ── */}
        <TabsContent value="questions" className="mt-4 space-y-3">
          <BarisAlat kiri={`${questions.length} pertanyaan aktif.`}
            kanan={<>
              <TombolUnduh namaBerkas="bank-soal-kpi" namaLembar="Bank soal" baris={soalUrut} testId="kpi-unduh-soal"
                kolom={[
                  { label: 'Pertanyaan', nilai: (q) => q.question_text }, { label: 'Jenis penilaian', nilai: (q) => EVAL_TYPE_CFG[q.eval_type]?.label || '' },
                  { label: 'Kategori', nilai: (q) => q.category }, { label: 'Bobot (%)', nilai: (q) => Math.round(q.category_weight * 100) },
                  { label: 'Urutan', nilai: (q) => q.order ?? '' },
                ]} />
              <Button variant="outline" onClick={handleSeedDefaults}><BookOpen />Muat soal bawaan DA</Button>
              <Button onClick={() => setQuestionDialog({ eval_type: 'self', category_weight: 0.10 })}><Plus />Tambah soal</Button>
            </>} />
          <TabelData kolom={kolomSoal} baris={soalUrut} kunci={(q) => q.question_id} testId="kpi-questions"
            kosong={<EmptyState title="Bank soal kosong" description="Muat soal bawaan DA atau tambah soal sendiri."
              action={<Button onClick={handleSeedDefaults}>Muat soal bawaan DA</Button>} />} />
        </TabsContent>

        {/* ── NILAI KINERJA ── */}
        <TabsContent value="perform" className="mt-4 space-y-3">
          {!selectedPeriod ? pilihPeriodeDulu : (
            <>
              <BarisAlat
                kiri={<><span className="font-medium text-foreground">{selectedPeriod.name}</span> · {performData.length} karyawan sudah diisi</>}
                kanan={<>
                  <TombolUnduh namaBerkas={`nilai-kinerja-${selectedPeriod.name}`} namaLembar="Nilai kinerja" baris={barisKinerja} testId="kpi-unduh-kinerja"
                    kolom={[
                      { label: 'Kode', nilai: (b) => b.emp?.employee_code || '' }, { label: 'Karyawan', nilai: (b) => b.emp?.name || '' },
                      { label: 'Nilai kinerja', nilai: (b) => (b.perf ? Number(b.perf.perform_score) : '') }, { label: 'Catatan', nilai: (b) => b.perf?.notes || '' },
                    ]} />
                  <Button variant={bulkMode ? 'default' : 'outline'} onClick={() => { setBulkMode(!bulkMode); setBulkScores({}); }}>
                    <ClipboardList />{bulkMode ? 'Kembali ke isian biasa' : 'Isi massal'}
                  </Button>
                  {!bulkMode && (
                    <Button onClick={() => setPerformDialog({
                      period_id: selectedPeriod.period_id,
                      items: [{ label: 'KPI Utama', target: 100, actual: 0, score: 0, weight: 1 }],
                    })}><Plus />Isi nilai</Button>
                  )}
                  {bulkMode && (
                    <Button variant="success" onClick={handleBulkSave} disabled={bulkSaving || !Object.keys(bulkScores).length}>
                      {bulkSaving ? <Loader2 className="animate-spin" /> : <Save />}Simpan semua ({Object.keys(bulkScores).length})
                    </Button>
                  )}
                </>} />
              {bulkMode && (
                <Notice tone="info" icon={ClipboardList} title="Isi massal">
                  Ketik nilai kinerja (0–100) langsung di kolom isian, lalu klik "Simpan semua". Nilai kosong tidak disimpan.
                </Notice>
              )}
              {barisKinerja.length > 0 ? (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Karyawan</TableHead>
                        <TableHead className="text-right">Nilai kinerja</TableHead>
                        {bulkMode && <TableHead className="text-right">Isian baru</TableHead>}
                        <TableHead>{bulkMode ? 'Catatan baru' : 'Catatan'}</TableHead>
                        {!bulkMode && <TableHead />}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {barisKinerja.map(({ empId, emp, perf }) => {
                        const bulkVal = bulkScores[empId] || {};
                        return (
                          <TableRow key={empId}>
                            <TableCell>
                              <p className="font-medium">{emp?.name || 'Karyawan'}</p>
                              <p className="text-xs text-muted-foreground">{emp?.employee_code || empId.slice(0, 8)}</p>
                            </TableCell>
                            <TableCell className="text-right">
                              {perf ? <span className="font-semibold tabular-nums">{fmtScore(perf.perform_score)}</span>
                                : <span className="text-sm text-muted-foreground">Belum diisi</span>}
                            </TableCell>
                            {bulkMode && (
                              <TableCell className="text-right">
                                <Input type="number" min={0} max={100} step={0.5} className="ml-auto w-24 text-right"
                                  placeholder={perf?.perform_score?.toFixed(1) || '0–100'} value={bulkVal.perform_score ?? ''}
                                  onChange={e => setBulkScores(prev => ({ ...prev, [empId]: { ...prev[empId], perform_score: e.target.value } }))} />
                              </TableCell>
                            )}
                            <TableCell className="text-sm text-muted-foreground">
                              {bulkMode ? (
                                <Input placeholder="Catatan" value={bulkVal.notes ?? ''}
                                  onChange={e => setBulkScores(prev => ({ ...prev, [empId]: { ...prev[empId], notes: e.target.value } }))} />
                              ) : (perf?.notes || '—')}
                            </TableCell>
                            {!bulkMode && (
                              <TableCell className="text-right">
                                <Button size="sm" variant="outline"
                                  onClick={() => setPerformDialog({
                                    period_id: selectedPeriod.period_id,
                                    employee_id: empId,
                                    employee_name: emp?.name,
                                    perform_score: perf?.perform_score || 0,
                                    items: perf?.items || [{ label: 'KPI Utama', target: 100, actual: 0, score: 0, weight: 1 }],
                                    notes: perf?.notes || '',
                                  })}>
                                  {perf ? <><Edit2 />Ubah</> : <><Plus />Isi</>}
                                </Button>
                              </TableCell>
                            )}
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              ) : <EmptyState title="Periode ini belum punya peserta" description="Tambahkan peserta lewat Ubah periode." />}
            </>
          )}
        </TabsContent>

        {/* ── KEMAJUAN PENGISIAN ── */}
        <TabsContent value="monitor" className="mt-4 space-y-3">
          {!selectedPeriod ? pilihPeriodeDulu : (
            <>
              <BarisAlat kiri={<><span className="font-medium text-foreground">{selectedPeriod.name}</span> · kemajuan pengisian</>}
                kanan={<>
                  <TombolUnduh namaBerkas={`kemajuan-kpi-${selectedPeriod.name}`} namaLembar="Kemajuan" baris={progressData?.progress || []} testId="kpi-unduh-kemajuan"
                    kolom={[
                      { label: 'Kode', nilai: (p) => p.employee_code || '' }, { label: 'Karyawan', nilai: (p) => p.employee_name || '' },
                      { label: 'Departemen', nilai: (p) => p.department || '' }, { label: 'Penilaian diri', nilai: (p) => (p.self_done ? 'Sudah' : 'Belum') },
                      { label: 'Penilaian rekan', nilai: (p) => `${p.peer_done}/${p.peer_total}` },
                      { label: 'Staf → atasan', nilai: (p) => (p.staff_to_sup_done ? 'Sudah' : 'Belum') },
                      { label: 'Ulasan atasan', nilai: (p) => (p.supervisor_reviewed ? 'Sudah' : 'Belum') },
                      { label: 'Nilai kinerja', nilai: (p) => (p.perform_input ? Number(p.perform_score) : '') },
                    ]} />
                  <Button variant="outline" onClick={() => loadFairness(selectedPeriod.period_id)} disabled={fairnessLoading}>
                    {fairnessLoading ? <Loader2 className="animate-spin" /> : <CheckCircle2 />}Cek keadilan penilaian rekan
                  </Button>
                  <Button variant="outline" size="icon" onClick={() => loadProgress(selectedPeriod.period_id)} title="Muat ulang kemajuan" aria-label="Muat ulang kemajuan">
                    <RefreshCw />
                  </Button>
                </>} />

              {fairnessData && (
                <Notice tone={fairnessData.overall_severity === 'error' ? 'danger' : fairnessData.overall_severity === 'warning' ? 'warning' : 'success'}
                  icon={fairnessData.overall_severity === 'ok' ? CheckCircle2 : AlertCircle} title="Hasil cek keadilan penilaian rekan"
                  action={<Button size="icon-sm" variant="ghost" onClick={() => setFairnessData(null)} aria-label="Tutup hasil" title="Tutup hasil"><X /></Button>}>
                  <p>{fairnessData.summary}</p>
                  {fairnessData.issues?.length > 0 ? (
                    <ul className="mt-2 space-y-1">
                      {fairnessData.issues.map(item => (
                        <li key={item.employee_id}>
                          <span className="font-medium text-foreground">{item.employee_name}</span>
                          <span className="text-muted-foreground"> ({item.employee_code}, {item.reviewer_count} penilai)</span>: {item.issues.map(iss => iss.message).join('; ')}
                        </li>
                      ))}
                    </ul>
                  ) : <p className="mt-1">Semua {fairnessData.total_participants} karyawan lulus cek — tidak ada masalah ditemukan.</p>}
                </Notice>
              )}

              <TabelData baris={progressData?.progress || []} kunci={(p) => p.employee_id} testId="kpi-progress"
                kolom={[
                  { kunci: 'nama', label: 'Karyawan', hp: 'judul', isi: (p) => (
                    <div><p className="font-medium text-foreground">{p.employee_name}</p><p className="text-xs text-muted-foreground">{p.employee_code} · {p.department}</p></div>) },
                  { kunci: 'self', label: 'Diri', rata: 'tengah', isi: (p) => <Tick ok={p.self_done} /> },
                  { kunci: 'peer', label: 'Rekan', rata: 'tengah', isi: (p) => <span className="tabular-nums">{p.peer_done}/{p.peer_total}</span> },
                  { kunci: 'sup', label: 'Staf → atasan', rata: 'tengah', isi: (p) => <Tick ok={p.staff_to_sup_done} /> },
                  { kunci: 'review', label: 'Ulasan atasan', rata: 'tengah', isi: (p) => <Tick ok={p.supervisor_reviewed} /> },
                  { kunci: 'kinerja', label: 'Kinerja', rata: 'kanan', isi: (p) => (p.perform_input
                    ? <span className="font-medium tabular-nums">{fmtScore(p.perform_score)}</span>
                    : <span className="text-sm text-[hsl(var(--danger-text))]">Belum</span>) },
                ]}
                kosong={<EmptyState title="Belum ada data kemajuan" description="Peserta periode ini akan tampil di sini." />} />
            </>
          )}
        </TabsContent>

        {/* ── LAPORAN & FINALISASI ── */}
        <TabsContent value="reports" className="mt-4 space-y-3">
          {!selectedPeriod ? pilihPeriodeDulu : (
            <>
              <BarisAlat kiri={<span className="font-medium text-foreground">{selectedPeriod.name}</span>}
                kanan={<>
                  <TombolUnduh namaBerkas={`hasil-kpi-${selectedPeriod.name}`} namaLembar="Hasil KPI" baris={reportData?.details || []} testId="kpi-unduh-hasil"
                    kolom={[
                      { label: 'Kode', nilai: (r) => r.employee_code || '' }, { label: 'Karyawan', nilai: (r) => r.employee_name || '' },
                      { label: 'Kinerja', nilai: (r) => r.perform_score ?? '' }, { label: 'Sikap', nilai: (r) => r.attitude_score ?? '' },
                      { label: 'Absensi', nilai: (r) => r.absensi_score ?? '' }, { label: 'KPI final', nilai: (r) => r.kpi_final ?? '' },
                      { label: 'Grade', nilai: (r) => r.grade || '' }, { label: 'Status', nilai: (r) => (r.publish_status === 'published' ? 'Terbit' : 'Draf') },
                    ]} />
                  <Button variant="outline" onClick={handleCalculate} disabled={calculating}>
                    {calculating ? <Loader2 className="animate-spin" /> : <BarChart3 />}Hitung KPI
                  </Button>
                  {selectedPeriod.status === 'closed' && (
                    <Button variant="success" onClick={() => handlePublish()}><Send />Terbitkan hasil</Button>
                  )}
                  {selectedPeriod.status === 'finalized' && (
                    <Button onClick={handleGenerateRaiseProposals} disabled={generatingRaise} data-testid="kpi-generate-raise-btn">
                      {generatingRaise ? <Loader2 className="animate-spin" /> : <Award />}Buat usulan kenaikan gaji
                    </Button>
                  )}
                  <Button variant="outline" size="icon" onClick={() => loadReport(selectedPeriod.period_id)} title="Muat ulang laporan" aria-label="Muat ulang laporan">
                    <RefreshCw />
                  </Button>
                </>} />

              {reportData && reportData.finalized_count > 0 ? (
                <>
                  <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                    <StatTile label="Rata-rata KPI" value={fmtPct(rs.avg_kpi)} sub={`${reportData.finalized_count} karyawan sudah dihitung.`} />
                    <StatTile label="Rata-rata kinerja" value={fmtPct(rs.avg_perform)} sub="Bobot 60% dari KPI." />
                    <StatTile label="Rata-rata sikap" value={fmtPct(rs.avg_attitude)} sub="Bobot 20% dari KPI." />
                    <StatTile label="Rata-rata absensi" value={fmtPct(rs.avg_absensi)} sub="Bobot 20% dari KPI." />
                  </div>
                  <p className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                    Sebaran grade:
                    {Object.entries(rs.grade_distribution || {}).map(([g, cnt]) => (
                      <span key={g} className="inline-flex items-center gap-1"><GradeBadge grade={g} /><span className="font-medium text-foreground tabular-nums">{cnt}</span></span>
                    ))}
                  </p>
                  <TabelData kolom={kolomHasil} baris={reportData.details} kunci={(r) => r.employee_id} onKlikBaris={setResultDialog} testId="kpi-results" />
                </>
              ) : (
                <EmptyState title="Hasil KPI belum dihitung" description='Klik "Hitung KPI" untuk menghitung otomatis.' />
              )}
            </>
          )}
        </TabsContent>

        {/* ── TREN KPI ── */}
        <TabsContent value="trend" className="mt-4 space-y-3">
          <BarisAlat kiri="Tren KPI per periode."
            kanan={<>
              <SmartNativeSelect className="w-56" value={trendEmployeeId} aria-label="Pilih karyawan"
                onChange={e => { setTrendEmployeeId(e.target.value); if (e.target.value) loadTrend(e.target.value); }}>
                <option value="">Pilih karyawan</option>
                {employees.map(e => <option key={e.id} value={e.id}>{e.employee_code} — {e.name}</option>)}
              </SmartNativeSelect>
              <Button variant="outline" size="icon" title="Muat ulang tren" aria-label="Muat ulang tren"
                onClick={() => { loadCompanyTrend(); if (trendEmployeeId) loadTrend(trendEmployeeId); }}>
                <RefreshCw />
              </Button>
            </>} />

          {companyTrend?.trend && companyTrend.trend.length > 0 && (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <GlassCard hover={false} className="space-y-2 p-4">
                <p className="text-sm font-medium text-foreground">Rata-rata KPI perusahaan ({companyTrend.trend.length} periode terakhir)</p>
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={companyTrend.trend}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--glass-border)" vertical={false} />
                    <XAxis dataKey="period_name" tick={SUMBU} />
                    <YAxis domain={[0, 100]} tick={SUMBU} />
                    <Tooltip contentStyle={TOOLTIP} formatter={(v, name) => [`${Number(v).toFixed(1)}`, name]} />
                    <Line type="monotone" dataKey="company_avg" stroke="hsl(var(--primary))" strokeWidth={2} dot={{ r: 3 }} name="Rata-rata KPI" />
                  </LineChart>
                </ResponsiveContainer>
              </GlassCard>
              <GlassCard hover={false} className="space-y-2 p-4">
                <p className="text-sm font-medium text-foreground">Sebaran grade per periode</p>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={companyTrend.trend} barSize={14}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--glass-border)" vertical={false} />
                    <XAxis dataKey="period_name" tick={SUMBU} />
                    <YAxis tick={SUMBU} allowDecimals={false} />
                    <Tooltip contentStyle={TOOLTIP} />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Bar dataKey="grade_distribution.A" fill="hsl(var(--success))" name="Grade A" stackId="a" />
                    <Bar dataKey="grade_distribution.B" fill="hsl(var(--info))" name="Grade B" stackId="a" />
                    <Bar dataKey="grade_distribution.C" fill="hsl(var(--warning))" name="Grade C" stackId="a" />
                    <Bar dataKey="grade_distribution.D" fill="hsl(var(--muted-foreground))" name="Grade D" stackId="a" />
                    <Bar dataKey="grade_distribution.E" fill="hsl(var(--destructive))" name="Grade E" stackId="a" />
                  </BarChart>
                </ResponsiveContainer>
              </GlassCard>
            </div>
          )}

          {trendEmployeeId && (
            <div className="space-y-2">
              <p className="text-sm font-medium text-foreground">
                Tren {employees.find(e => e.id === trendEmployeeId)?.name || 'karyawan'}
                {trendData?.department && <span className="font-normal text-muted-foreground"> · {trendData.department}</span>}
              </p>
              {trendLoading && <p className="py-6 text-center text-sm text-muted-foreground">Memuat tren…</p>}
              {!trendLoading && trendData?.trend && trendData.trend.length > 0 && (
                <>
                  <ResponsiveContainer width="100%" height={220}>
                    <LineChart data={trendData.trend}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--glass-border)" vertical={false} />
                      <XAxis dataKey="period_name" tick={SUMBU} />
                      <YAxis domain={[0, 100]} tick={SUMBU} />
                      <Tooltip contentStyle={TOOLTIP} formatter={(v, name) => [v !== null ? `${Number(v).toFixed(1)}` : '—', name]} />
                      <Legend wrapperStyle={{ fontSize: 12 }} />
                      <Line type="monotone" dataKey="kpi_final" stroke="hsl(var(--primary))" strokeWidth={2} dot={{ r: 3 }} name="KPI final" connectNulls />
                      <Line type="monotone" dataKey="perform_score" stroke="hsl(var(--info))" strokeWidth={1.5} dot={{ r: 2 }} name="Kinerja" connectNulls strokeDasharray="4 2" />
                      <Line type="monotone" dataKey="attitude_score" stroke="hsl(var(--success))" strokeWidth={1.5} dot={{ r: 2 }} name="Sikap" connectNulls strokeDasharray="4 2" />
                      <Line type="monotone" dataKey="dept_avg" stroke="hsl(var(--warning))" strokeWidth={1.5} dot={false} name="Rata-rata departemen" strokeDasharray="6 3" />
                    </LineChart>
                  </ResponsiveContainer>
                  <div className="flex justify-end">
                    <TombolUnduh namaBerkas="tren-kpi-karyawan" namaLembar="Tren" baris={trendData.trend} testId="kpi-unduh-tren"
                      kolom={[
                        { label: 'Periode', nilai: (r) => r.period_name }, { label: 'KPI final', nilai: (r) => r.kpi_final ?? '' },
                        { label: 'Kinerja', nilai: (r) => r.perform_score ?? '' }, { label: 'Sikap', nilai: (r) => r.attitude_score ?? '' },
                        { label: 'Absensi', nilai: (r) => r.absensi_score ?? '' }, { label: 'Grade', nilai: (r) => r.grade || '' },
                        { label: 'Rata-rata departemen', nilai: (r) => r.dept_avg ?? '' },
                      ]} />
                  </div>
                  <TabelData baris={trendData.trend} kunci={(r) => r.period_id} testId="kpi-trend-table"
                    kolom={[
                      { kunci: 'periode', label: 'Periode', hp: 'judul' , isi: (r) => r.period_name },
                      { kunci: 'final', label: 'KPI final', rata: 'kanan', isi: (r) => <span className="font-semibold tabular-nums">{fmtScore(r.kpi_final)}</span> },
                      { kunci: 'kinerja', label: 'Kinerja', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtScore(r.perform_score)}</span> },
                      { kunci: 'sikap', label: 'Sikap', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtScore(r.attitude_score)}</span> },
                      { kunci: 'absensi', label: 'Absensi', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtScore(r.absensi_score)}</span> },
                      { kunci: 'grade', label: 'Grade', isi: (r) => <GradeBadge grade={r.grade} /> },
                      { kunci: 'dept', label: 'Rata-rata departemen', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtScore(r.dept_avg)}</span> },
                    ]} />
                </>
              )}
              {!trendLoading && (!trendData?.trend || trendData.trend.length === 0) && (
                <EmptyState title="Belum ada data KPI untuk karyawan ini" />
              )}
            </div>
          )}

          {!trendEmployeeId && !companyTrend?.trend?.length && (
            <EmptyState title="Belum ada tren KPI" description="Tren muncul setelah ada periode yang hasilnya sudah dihitung. Pilih karyawan untuk melihat tren perorangan." />
          )}
        </TabsContent>

        {/* ── SASARAN ── */}
        <TabsContent value="goals" className="mt-4 space-y-3">
          <BarisAlat
            kiri={<div className="flex flex-wrap items-center gap-2">
              <SmartNativeSelect className="w-48" value={goalsPeriodId} aria-label="Saring periode"
                onChange={e => { setGoalsPeriodId(e.target.value); loadGoals(e.target.value, goalsEmployeeId); }}>
                <option value="">Semua periode</option>
                {periods.map(p => <option key={p.period_id} value={p.period_id}>{p.name}</option>)}
              </SmartNativeSelect>
              <SmartNativeSelect className="w-56" value={goalsEmployeeId} aria-label="Saring karyawan"
                onChange={e => { setGoalsEmployeeId(e.target.value); loadGoals(goalsPeriodId, e.target.value); }}>
                <option value="">Semua karyawan</option>
                {employees.map(e => <option key={e.id} value={e.id}>{e.employee_code} — {e.name}</option>)}
              </SmartNativeSelect>
            </div>}
            kanan={<>
              <TombolUnduh namaBerkas="sasaran-kpi" namaLembar="Sasaran" baris={goals} testId="kpi-unduh-sasaran"
                kolom={[
                  { label: 'Sasaran', nilai: (g) => g.title }, { label: 'Deskripsi', nilai: (g) => g.description || '' },
                  { label: 'Karyawan', nilai: (g) => g.employee_name || '' }, { label: 'Periode', nilai: (g) => g.period_name || '' },
                  { label: 'Target', nilai: (g) => g.target_value }, { label: 'Aktual', nilai: (g) => g.actual_value },
                  { label: 'Satuan', nilai: (g) => g.unit || '' }, { label: 'Kemajuan (%)', nilai: (g) => g.progress_pct || 0 },
                  { label: 'Status', nilai: (g) => GOAL_STATUS[g.status]?.label || '' },
                ]} />
              <Button onClick={() => setGoalDialog({ period_id: goalsPeriodId, employee_id: goalsEmployeeId })}><Plus />Tambah sasaran</Button>
            </>} />
          {goalsLoading ? <p className="py-6 text-center text-sm text-muted-foreground">Memuat sasaran…</p> : (
            <TabelData kolom={kolomSasaran} baris={goalsPg.paged} kunci={(g) => g.goal_id} testId="kpi-goals"
              kosong={<EmptyState title="Belum ada sasaran untuk saringan ini" description='Klik "Tambah sasaran" untuk membuat sasaran karyawan.' />} />
          )}
          {goalsPg.total > 10 && <PaginationLite page={goalsPg.page} totalPages={goalsPg.totalPages} total={goalsPg.total} pageSize={10} onPageChange={goalsPg.setPage} />}
        </TabsContent>

        {/* ── GAMIFIKASI ── */}
        <TabsContent value="gamifikasi" className="mt-4 space-y-3">
          <p className="text-sm text-muted-foreground">Papan peringkat, lencana, dan pencapaian untuk memotivasi karyawan.</p>
          <KPIGamificationTab token={token} periods={periods} isHR={true} />
        </TabsContent>
      </Tabs>

      {periodDialog !== null && (
        <PeriodDialog initial={periodDialog} employees={employees} headers={headers} onSave={handleSavePeriod} onClose={() => setPeriodDialog(null)} />
      )}
      {questionDialog !== null && (
        <QuestionDialog initial={questionDialog} onSave={handleSaveQuestion} onClose={() => setQuestionDialog(null)} />
      )}
      {performDialog !== null && (
        <PerformDialog initial={performDialog} employees={employees} onSave={handleSavePerform} onClose={() => setPerformDialog(null)} />
      )}
      {resultDialog !== null && (
        <ResultDetailDialog result={resultDialog} onClose={() => setResultDialog(null)} />
      )}
      {goalDialog !== null && (
        <GoalDialog
          initial={goalDialog}
          periods={periods}
          employees={employees}
          headers={headers}
          onSave={async (form) => {
            const isEdit = !!form.goal_id;
            const r = await kpi(
              isEdit ? `/goals/${form.goal_id}` : '/goals',
              { method: isEdit ? 'PUT' : 'POST', headers, body: JSON.stringify(form) }
            );
            const d = await r.json();
            if (!r.ok) { toast.error(d.detail || 'Gagal menyimpan sasaran'); return; }
            toast.success(isEdit ? 'Sasaran disimpan' : 'Sasaran dibuat');
            setGoalDialog(null);
            loadGoals(goalsPeriodId, goalsEmployeeId);
          }}
          onClose={() => setGoalDialog(null)}
        />
      )}
    </PageLayout>
  );
}

// ═══════════════════════════════════════════════════════
// SUB-KOMPONEN (form popup standar)
// ═══════════════════════════════════════════════════════

function DaftarCentang({ items, terpilih, onAlih, kosong }) {
  return (
    <div className="grid gap-x-4 rounded-lg border border-[var(--glass-border)] px-3 py-1 sm:grid-cols-2">
      {items.map(emp => (
        <label key={emp.id} className="flex min-w-0 cursor-pointer items-center gap-2 py-1.5">
          <input type="checkbox" className="rounded" checked={terpilih.includes(emp.id)} onChange={() => onAlih(emp.id)} />
          <span className="min-w-0 text-sm" title={emp.job_title || undefined}>{emp.employee_code} — {emp.name}</span>
        </label>
      ))}
      {items.length === 0 && <p className="py-3 text-center text-sm text-muted-foreground sm:col-span-2">{kosong}</p>}
    </div>
  );
}

function PeriodDialog({ initial, employees, headers, onSave, onClose }) {
  const [form, setForm] = useState({
    // 2026-11-06 (pola P5): kosong = dihitung server dari hari kerja per minggu + Kalender Produksi (dulu 26 tetap)
    name: '', period_from: '', period_to: '', working_days: '',
    notes: '', participant_employee_ids: [], supervisor_assignments: [],
    ...initial,
  });
  const [saving, setSaving] = useState(false);

  const handleSubmit = async () => {
    setSaving(true);
    await onSave(form);
    setSaving(false);
  };

  const toggleEmployee = (empId) => {
    setForm(f => ({
      ...f,
      participant_employee_ids: f.participant_employee_ids.includes(empId)
        ? f.participant_employee_ids.filter(id => id !== empId)
        : [...f.participant_employee_ids, empId],
    }));
  };

  const selectAll = () => setForm(f => ({ ...f, participant_employee_ids: employees.map(e => e.id) }));
  const clearAll = () => setForm(f => ({ ...f, participant_employee_ids: [] }));
  const setSa = (i, patch) => setForm(f => ({
    ...f, supervisor_assignments: f.supervisor_assignments.map((s, idx) => (idx === i ? { ...s, ...patch } : s)),
  }));

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" onSimpan={handleSubmit} menyimpan={saving} bisaSimpan={!!form.name}
      judul={form.period_id ? 'Ubah periode' : 'Buat periode KPI'} testId="kpi-period-form">
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Nama periode" wajib htmlFor="kpi-per-nama">
          <Input id="kpi-per-nama" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="KPI Januari 2026" required />
        </Isian>
        <Isian label="Hari kerja" htmlFor="kpi-per-hari" petunjuk="Kosong = dihitung otomatis dari Kalender Produksi.">
          <Input id="kpi-per-hari" type="number" value={form.working_days} min={1}
            onChange={e => setForm(f => ({ ...f, working_days: parseInt(e.target.value) || '' }))} />
        </Isian>
        <Isian label="Tanggal mulai">
          <DatePicker value={form.period_from} onChange={v => setForm(f => ({ ...f, period_from: v }))} testId="kpi-per-mulai" />
        </Isian>
        <Isian label="Tanggal selesai">
          <DatePicker value={form.period_to} min={form.period_from || undefined} onChange={v => setForm(f => ({ ...f, period_to: v }))} testId="kpi-per-selesai" />
        </Isian>
      </div>

      <Isian label={`Peserta (${form.participant_employee_ids.length} dipilih)`}>
        <div className="mb-1 flex gap-2">
          <Button type="button" size="sm" variant="link" className="h-auto p-0" onClick={selectAll}>Pilih semua</Button>
          <Button type="button" size="sm" variant="link" className="h-auto p-0" onClick={clearAll}>Kosongkan</Button>
        </div>
        <DaftarCentang items={employees} terpilih={form.participant_employee_ids} onAlih={toggleEmployee} kosong="Belum ada data karyawan" />
      </Isian>

      <Isian label="Catatan" htmlFor="kpi-per-catatan">
        <Textarea id="kpi-per-catatan" value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} placeholder="Catatan (opsional)" rows={2} />
      </Isian>

      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Label>Penugasan atasan ({form.supervisor_assignments.length} kelompok)</Label>
          <Button type="button" size="sm" variant="outline"
            onClick={() => setForm(f => ({ ...f, supervisor_assignments: [...f.supervisor_assignments, { supervisor_employee_id: '', employee_ids: [] }] }))}>
            <Plus />Tambah atasan
          </Button>
        </div>
        {form.supervisor_assignments.length === 0 && (
          <p className="text-xs text-muted-foreground">Atasan belum ditugaskan — formulir staf → atasan tidak akan muncul.</p>
        )}
        {form.supervisor_assignments.map((sa, i) => {
          const calon = employees.filter(e => form.participant_employee_ids.includes(e.id) && e.id !== sa.supervisor_employee_id);
          return (
            <div key={i} className="space-y-2 rounded-lg border border-[var(--glass-border)] p-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-foreground">Atasan {i + 1}</span>
                <Button type="button" size="sm" variant="ghost" className="text-[hsl(var(--danger-text))]"
                  onClick={() => setForm(f => ({ ...f, supervisor_assignments: f.supervisor_assignments.filter((_, idx) => idx !== i) }))}>
                  Hapus
                </Button>
              </div>
              <SmartNativeSelect value={sa.supervisor_employee_id} onChange={e => setSa(i, { supervisor_employee_id: e.target.value })} aria-label="Atasan">
                <option value="">Pilih atasan</option>
                {employees.map(e => <option key={e.id} value={e.id}>{`${e.employee_code} — ${e.name}`}</option>)}
              </SmartNativeSelect>
              <p className="text-xs text-muted-foreground">Bawahan (dari peserta) · {sa.employee_ids.length} dipilih</p>
              <DaftarCentang items={calon} terpilih={sa.employee_ids} kosong="Tambahkan peserta terlebih dahulu"
                onAlih={(empId) => setSa(i, { employee_ids: sa.employee_ids.includes(empId) ? sa.employee_ids.filter(id => id !== empId) : [...sa.employee_ids, empId] })} />
            </div>
          );
        })}
      </div>
    </FormPopup>
  );
}

function QuestionDialog({ initial, onSave, onClose }) {
  const [form, setForm] = useState({
    eval_type: 'self', category: '', category_weight: 0.10,
    question_text: '', order: 99,
    ...initial,
  });
  const [saving, setSaving] = useState(false);

  const handleSubmit = async () => {
    setSaving(true);
    await onSave(form);
    setSaving(false);
  };

  return (
    <FormPopup open onClose={onClose} ukuran="pendek" onSimpan={handleSubmit} menyimpan={saving}
      judul={form.question_id ? 'Ubah pertanyaan' : 'Tambah pertanyaan'} testId="kpi-question-form">
      <Isian label="Jenis penilaian">
        <SmartNativeSelect searchable={false} value={form.eval_type} onChange={e => setForm(f => ({ ...f, eval_type: e.target.value }))}>
          {Object.entries(EVAL_TYPE_CFG).map(([k, v]) => <option key={k} value={k}>{v.label} ({v.weight})</option>)}
        </SmartNativeSelect>
      </Isian>
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Kategori" wajib htmlFor="kpi-q-kategori">
          <Input id="kpi-q-kategori" value={form.category} onChange={e => setForm(f => ({ ...f, category: e.target.value }))} placeholder="misal: Tanggung jawab" required />
        </Isian>
        <Isian label="Bobot kategori (0–1)" htmlFor="kpi-q-bobot">
          <Input id="kpi-q-bobot" type="number" value={form.category_weight} step={0.05} min={0.01} max={1}
            onChange={e => setForm(f => ({ ...f, category_weight: parseFloat(e.target.value) || 0.10 }))} />
        </Isian>
      </div>
      <Isian label="Teks pertanyaan" wajib htmlFor="kpi-q-teks">
        <Textarea id="kpi-q-teks" value={form.question_text} onChange={e => setForm(f => ({ ...f, question_text: e.target.value }))}
          placeholder="Tuliskan pertanyaan" rows={3} required />
      </Isian>
      <Isian label="Urutan" htmlFor="kpi-q-urutan">
        <Input id="kpi-q-urutan" type="number" value={form.order} min={1} onChange={e => setForm(f => ({ ...f, order: parseInt(e.target.value) || 99 }))} />
      </Isian>
    </FormPopup>
  );
}

function PerformDialog({ initial, employees, onSave, onClose }) {
  const [form, setForm] = useState({
    period_id: '', employee_id: '', employee_name: '',
    items: [{ label: 'KPI Utama', target: 100, actual: 0, score: 0, weight: 1 }],
    notes: '',
    ...initial,
  });
  const [saving, setSaving] = useState(false);

  const totalWeight = form.items.reduce((sum, it) => sum + (parseFloat(it.weight) || 0), 0);
  const weightedScore = totalWeight > 0
    ? form.items.reduce((sum, it) => sum + (parseFloat(it.score) || 0) * (parseFloat(it.weight) || 0), 0) / totalWeight
    : 0;

  const addItem = () => setForm(f => ({
    ...f,
    items: [...f.items, { label: 'KPI Baru', target: 100, actual: 0, score: 0, weight: 1 }],
  }));
  const removeItem = (i) => setForm(f => ({ ...f, items: f.items.filter((_, idx) => idx !== i) }));
  const updateItem = (i, key, val) => setForm(f => ({
    ...f,
    items: f.items.map((it, idx) => idx === i ? { ...it, [key]: val } : it),
  }));

  const handleSubmit = async () => {
    setSaving(true);
    await onSave({ ...form, perform_score: Math.round(weightedScore * 10) / 10 });
    setSaving(false);
  };

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" onSimpan={handleSubmit} menyimpan={saving} bisaSimpan={!!form.employee_id}
      judul="Isi nilai kinerja" keterangan={form.employee_name ? `Karyawan: ${form.employee_name}` : undefined} testId="kpi-perform-form">
      {!form.employee_id && (
        <Isian label="Karyawan" wajib>
          {/* Tahap 5 (2026-11-07): pemilih karyawan bisa dicari (dulu Select tanpa kotak cari) */}
          <EmployeeSelect employees={employees} value={form.employee_id} testId="kpi-goal-employee" className="w-full"
            onChange={v => {
              const emp = employees.find(e => e.id === v);
              setForm(f => ({ ...f, employee_id: v, employee_name: emp?.name || '' }));
            }} />
        </Isian>
      )}

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label>Item KPI ({form.items.length})</Label>
          <Button type="button" size="sm" variant="outline" onClick={addItem}><Plus />Tambah item</Button>
        </div>
        <div className="divide-y divide-[var(--glass-border)] rounded-lg border border-[var(--glass-border)]">
          {form.items.map((item, i) => (
            <div key={i} className="grid grid-cols-2 gap-2 p-3 sm:grid-cols-[1fr_6rem_6rem_1fr_auto] sm:items-end">
              <Isian label="Nama KPI" className="col-span-2 sm:col-span-1">
                <Input value={item.label} onChange={e => updateItem(i, 'label', e.target.value)} placeholder="Nama KPI" />
              </Isian>
              <Isian label="Skor (0–100)">
                <Input type="number" value={item.score} min={0} max={100} onChange={e => updateItem(i, 'score', parseFloat(e.target.value) || 0)} />
              </Isian>
              <Isian label="Bobot">
                <Input type="number" value={item.weight} min={0.1} step={0.1} onChange={e => updateItem(i, 'weight', parseFloat(e.target.value) || 1)} />
              </Isian>
              <Isian label="Catatan">
                <Input value={item.notes || ''} onChange={e => updateItem(i, 'notes', e.target.value)} placeholder="opsional" />
              </Isian>
              <Button type="button" size="icon" variant="ghost" className="text-[hsl(var(--danger-text))]" onClick={() => removeItem(i)}
                aria-label="Hapus item" title="Hapus item">
                <X />
              </Button>
            </div>
          ))}
        </div>
      </div>

      <p className="flex items-center justify-between rounded-lg border border-[var(--glass-border)] px-4 py-3 text-sm">
        <span className="text-muted-foreground">Nilai kinerja terhitung (rata-rata berbobot)</span>
        <span className="text-xl font-semibold tabular-nums text-foreground">{weightedScore.toFixed(1)}</span>
      </p>

      <Isian label="Catatan atasan" htmlFor="kpi-perf-catatan">
        <Textarea id="kpi-perf-catatan" value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} placeholder="Catatan evaluasi" rows={2} />
      </Isian>
    </FormPopup>
  );
}

function ResultDetailDialog({ result, onClose }) {
  const g = GRADE_CFG[result.grade] || {};
  return (
    <DetailPopup open onClose={onClose} testId="kpi-result-detail" judul={`Detail KPI — ${result.employee_name}`}
      keterangan={result.employee_code}
      status={result.grade ? <Lencana status={`grade-${result.grade}`} label={`Grade ${result.grade} — ${g.label}`} tone={g.tone} /> : null}>
      <dl className="divide-y divide-[var(--glass-border)]">
        <BarisDetail label="KPI final"><span className="text-base font-semibold tabular-nums">{fmtScore(result.kpi_final)}</span> <span className="text-muted-foreground">dari 100</span></BarisDetail>
        {[
          { label: 'Kinerja (60%)', score: result.perform_score },
          { label: 'Sikap (20%)', score: result.attitude_score },
          { label: 'Absensi (20%)', score: result.absensi_score },
        ].map(c => (
          <BarisDetail key={c.label} label={c.label}>
            <div className="flex items-center gap-3"><span className="w-10 tabular-nums">{fmtScore(c.score)}</span><div className="flex-1"><ScoreBar score={c.score || 0} /></div></div>
          </BarisDetail>
        ))}
        {result.status_kpi && <BarisDetail label="Status">{result.status_kpi}</BarisDetail>}
        {result.raise_pct > 0 && <BarisDetail label="Kenaikan gaji">{result.raise_pct}%</BarisDetail>}
      </dl>
      {result.absensi_detail && (
        <div>
          <p className="mb-1 text-sm font-medium text-foreground">Rincian absensi</p>
          <dl className="divide-y divide-[var(--glass-border)]">
            {Object.entries(result.absensi_detail.breakdown || {}).filter(([, v]) => v > 0).map(([k, v]) => (
              <BarisDetail key={k} label={k.charAt(0).toUpperCase() + k.slice(1).replace(/_/g, ' ')}>{v}</BarisDetail>
            ))}
            <BarisDetail label="Hari tidak hadir">{result.absensi_detail.absent_days || 0} dari {result.absensi_detail.working_days} hari kerja</BarisDetail>
          </dl>
        </div>
      )}
    </DetailPopup>
  );
}

// ─── SASARAN ──────────────────────────────────────────────────────────────
function GoalDialog({ initial, periods, employees, headers, onSave, onClose }) {
  const [form, setForm] = useState({
    period_id: '',
    employee_id: '',
    title: '',
    description: '',
    target_value: 100,
    unit: '',
    actual_value: 0,
    notes: '',
    ...initial,
  });
  const [saving, setSaving] = useState(false);

  const progress = form.target_value > 0
    ? Math.min(100, Math.round((form.actual_value / form.target_value) * 100))
    : 0;

  const handleSubmit = async () => {
    setSaving(true);
    await onSave(form);
    setSaving(false);
  };

  return (
    <FormPopup open onClose={onClose} ukuran="pendek" onSimpan={handleSubmit} menyimpan={saving}
      bisaSimpan={!!(form.period_id && form.employee_id && form.title)}
      judul={form.goal_id ? 'Ubah sasaran' : 'Tambah sasaran'} testId="kpi-goal-form">
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Periode" wajib>
          <SmartNativeSelect value={form.period_id} onChange={e => setForm(f => ({ ...f, period_id: e.target.value }))}>
            <option value="">Pilih periode</option>
            {periods.map(p => <option key={p.period_id} value={p.period_id}>{p.name}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Karyawan" wajib>
          <SmartNativeSelect value={form.employee_id} onChange={e => setForm(f => ({ ...f, employee_id: e.target.value }))}>
            <option value="">Pilih karyawan</option>
            {employees.map(e => <option key={e.id} value={e.id}>{e.employee_code} — {e.name}</option>)}
          </SmartNativeSelect>
        </Isian>
      </div>
      <Isian label="Judul sasaran" wajib htmlFor="kpi-goal-judul">
        <Input id="kpi-goal-judul" value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))} placeholder="contoh: Produksi 1000 pcs per bulan" required />
      </Isian>
      <Isian label="Deskripsi (opsional)" htmlFor="kpi-goal-desk">
        <Textarea id="kpi-goal-desk" value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} rows={2} />
      </Isian>
      <div className="grid grid-cols-3 gap-3">
        <Isian label="Target" wajib htmlFor="kpi-goal-target">
          <Input id="kpi-goal-target" type="number" value={form.target_value} min={0} step={0.1} required
            onChange={e => setForm(f => ({ ...f, target_value: parseFloat(e.target.value) || 0 }))} />
        </Isian>
        <Isian label="Aktual" htmlFor="kpi-goal-aktual">
          <Input id="kpi-goal-aktual" type="number" value={form.actual_value} min={0} step={0.1}
            onChange={e => setForm(f => ({ ...f, actual_value: parseFloat(e.target.value) || 0 }))} />
        </Isian>
        <Isian label="Satuan" htmlFor="kpi-goal-satuan">
          <Input id="kpi-goal-satuan" value={form.unit} onChange={e => setForm(f => ({ ...f, unit: e.target.value }))} placeholder="pcs, %, dll" />
        </Isian>
      </div>
      <div className="space-y-1">
        <div className="flex justify-between text-sm"><span className="text-muted-foreground">Perkiraan kemajuan</span><span className="font-semibold tabular-nums">{progress}%</span></div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-[var(--glass-border)]">
          <div className="h-2 rounded-full bg-primary transition-all" style={{ width: `${Math.min(100, progress)}%` }} />
        </div>
      </div>
      <Isian label="Catatan" htmlFor="kpi-goal-catatan">
        <Textarea id="kpi-goal-catatan" value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} rows={2} />
      </Isian>
    </FormPopup>
  );
}

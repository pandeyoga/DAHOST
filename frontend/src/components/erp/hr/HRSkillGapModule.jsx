/**
 * Kesenjangan keahlian (Portal SDM › AI SDM) — bandingkan keahlian aktual dengan kebutuhan, per individu,
 * departemen, atau seluruh perusahaan, lengkap dengan rekomendasi pelatihan & rekrutmen.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout (di hub: bagian jadi pil), kebutuhan/kesenjangan/riwayat =
 * tabel + unduh Excel/CSV (dulu baris kartu & kartu bergradien), form kebutuhan = FormPopup, detail riwayat =
 * DetailPopup, kartu angka StatTile, warna token, bahasa Indonesia (Technical/Critical/High… → label Indonesia;
 * nilai yang dikirim ke server tetap sama). Riwayat dulu 20 terakhir — kini sampai 200.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { Loader2, Plus, RefreshCw, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup from '@/components/ui/detail-popup';
import { formatDateTimeID } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from '../moduleAtoms';

const CATEGORY_OPTIONS = [
  { value: 'technical', label: 'Teknis' },
  { value: 'soft', label: 'Nonteknis' },
  { value: 'domain', label: 'Pengetahuan bidang' },
];
const PRIORITY_OPTIONS = [
  { value: 'critical', label: 'Kritis', tone: 'danger' },
  { value: 'high', label: 'Tinggi', tone: 'warning' },
  { value: 'medium', label: 'Sedang', tone: 'info' },
  { value: 'low', label: 'Rendah', tone: 'muted' },
];
const SEVERITY = { High: 'Tinggi', Medium: 'Sedang', Low: 'Rendah' };
const LEVEL = { individual: 'Individu (diri sendiri)', department: 'Departemen', company: 'Seluruh perusahaan' };
const labelKategori = (v) => CATEGORY_OPTIONS.find(o => o.value === v)?.label || v || '—';
const labelPrioritas = (v) => PRIORITY_OPTIONS.find(o => o.value === v)?.label || v || '—';
function Prioritas({ nilai }) {
  if (!nilai) return <span className="text-muted-foreground">—</span>;
  const o = PRIORITY_OPTIONS.find(x => x.value === nilai) || { label: nilai, tone: 'default' };
  return <StatusBadge status={nilai} label={o.label} tone={o.tone} />;
}
const REQ_KOSONG = { skill_name: '', category: 'technical', required_level: 3, priority: 'high', for_role: '', for_department: '' };

function BarisAlat({ kiri, kanan }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex min-w-0 flex-wrap items-center gap-2 text-sm text-muted-foreground">{kiri}</div>
      <div className="flex flex-wrap items-center gap-2">{kanan}</div>
    </div>
  );
}

export default function HRSkillGapModule({ token }) {
  const [activeTab, setActiveTab] = useState('analysis');
  const [requirements, setRequirements] = useState([]);
  const [analyses, setAnalyses] = useState([]);
  const [departments, setDepartments] = useState([]);

  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [currentResult, setCurrentResult] = useState(null);

  // analysis form
  const [analysisLevel, setAnalysisLevel] = useState('department');
  const [targetDept, setTargetDept] = useState('');

  // requirement form
  const [reqDialogOpen, setReqDialogOpen] = useState(false);
  const [reqForm, setReqForm] = useState(REQ_KOSONG);

  // detail
  const [detailData, setDetailData] = useState(null);

  const headers = useMemo(
    () => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }),
    [token]
  );

  const BASE = process.env.REACT_APP_BACKEND_URL;

  // ───────────────────────────── Fetchers ──────────────────────────────
  const fetchRequirements = useCallback(async () => {
    try {
      const r = await fetch(`${BASE}/api/hr/skill-gap/requirements`, { headers });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setRequirements(data?.data || []);
    } catch (e) {
      console.error('fetchRequirements:', e);
      toast.error(`Gagal memuat kebutuhan keahlian: ${e.message}`);
    }
  }, [BASE, headers]);

  const fetchAnalyses = useCallback(async () => {
    try {
      const r = await fetch(`${BASE}/api/hr/skill-gap/analyses?limit=200`, { headers });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setAnalyses(data?.data || []);
    } catch (e) {
      console.error('fetchAnalyses:', e);
    }
  }, [BASE, headers]);

  const fetchDepartments = useCallback(async () => {
    try {
      // Use dedicated skill-gap endpoint (avoids dependency on hr/ai employees list bug)
      const r = await fetch(`${BASE}/api/hr/skill-gap/departments`, { headers });
      if (!r.ok) return;
      const data = await r.json();
      const arr = (data?.data || []).filter(Boolean).sort();
      setDepartments(arr);
      if (arr.length && !targetDept) setTargetDept(arr[0]);
    } catch (e) {
      console.error('fetchDepartments:', e);
    }
  }, [BASE, headers, targetDept]);

  const muatSemua = useCallback(() => {
    setLoading(true);
    Promise.all([fetchRequirements(), fetchAnalyses(), fetchDepartments()]).finally(() => setLoading(false));
  }, [fetchRequirements, fetchAnalyses, fetchDepartments]);

  useEffect(() => { muatSemua(); }, [muatSemua]);

  // ───────────────────────── Create requirement ─────────────────────────
  const handleCreateRequirement = async () => {
    if (!reqForm.skill_name?.trim()) {
      toast.error('Nama keahlian wajib diisi');
      return;
    }
    if (!reqForm.for_role && !reqForm.for_department) {
      toast.error('Isi minimal salah satu: jabatan atau departemen');
      return;
    }
    try {
      const body = {
        skill_name: reqForm.skill_name.trim(),
        category: reqForm.category,
        required_level: Number(reqForm.required_level) || 1,
        priority: reqForm.priority,
        for_role: reqForm.for_role?.trim() || null,
        for_department: reqForm.for_department?.trim() || null,
      };
      const r = await fetch(`${BASE}/api/hr/skill-gap/requirements`, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      toast.success('Kebutuhan keahlian disimpan');
      setReqDialogOpen(false);
      setReqForm(REQ_KOSONG);
      fetchRequirements();
    } catch (e) {
      toast.error(`Gagal menyimpan: ${e.message}`);
    }
  };

  // ───────────────────────── Run analysis ─────────────────────────
  const handleAnalyze = async () => {
    if (analysisLevel === 'department' && !targetDept) {
      toast.error('Pilih departemen dahulu');
      return;
    }
    setAnalyzing(true);
    setCurrentResult(null);
    try {
      const endpoint =
        analysisLevel === 'department'
          ? `${BASE}/api/hr/skill-gap/analyze/department`
          : analysisLevel === 'company'
          ? `${BASE}/api/hr/skill-gap/analyze/company`
          : `${BASE}/api/hr/skill-gap/analyze/individual`;

      const body = {
        level: analysisLevel,
        target_id: analysisLevel === 'department' ? targetDept : null,
        include_recommendations: true,
      };
      const r = await fetch(endpoint, { method: 'POST', headers, body: JSON.stringify(body) });
      if (!r.ok) {
        let msg = `HTTP ${r.status}`;
        try {
          const j = await r.json();
          msg = j.detail || msg;
        } catch {
          /* noop */
        }
        throw new Error(msg);
      }
      const data = await r.json();
      setCurrentResult(data?.data);
      toast.success('Analisis selesai', { icon: <Sparkles className="h-4 w-4" /> });
      fetchAnalyses();
    } catch (e) {
      toast.error(`Analisis gagal: ${e.message}`);
    } finally {
      setAnalyzing(false);
    }
  };

  const kolomKebutuhan = [
    { kunci: 'nama', label: 'Keahlian', hp: 'judul', isi: (r) => <span className="font-medium text-foreground">{r.skill_name}</span> },
    { kunci: 'kat', label: 'Kategori', isi: (r) => <span className="text-sm">{labelKategori(r.category)}</span> },
    { kunci: 'lv', label: 'Tingkat', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.required_level}/5</span> },
    { kunci: 'pri', label: 'Prioritas', isi: (r) => <Prioritas nilai={r.priority} /> },
    { kunci: 'role', label: 'Jabatan', isi: (r) => <span className="text-sm">{r.for_role || '—'}</span> },
    { kunci: 'dept', label: 'Departemen', isi: (r) => <span className="text-sm">{r.for_department || '—'}</span> },
  ];
  const kolomRiwayat = [
    { kunci: 'level', label: 'Cakupan', hp: 'judul', isi: (a) => (
      <div><p className="font-medium text-foreground">{LEVEL[a.level] || a.level || '—'}</p>
        <p className="text-xs text-muted-foreground">{a.department || a.employee_name || ''}</p></div>) },
    { kunci: 'tgl', label: 'Waktu', isi: (a) => <span className="text-sm md:whitespace-nowrap">{a.analyzed_at ? formatDateTimeID(a.analyzed_at) : '—'}</span> },
    { kunci: 'gap', label: 'Kesenjangan', rata: 'kanan', isi: (a) => <span className="tabular-nums">{typeof a.gap_count === 'number' ? a.gap_count : '—'}</span> },
    { kunci: 'kritis', label: 'Kritis', rata: 'kanan', isi: (a) => <span className="tabular-nums">{typeof a.critical_gaps === 'number' ? a.critical_gaps : '—'}</span> },
  ];

  return (
    <PageLayout testId="hr-skill-gap-module" title="Kesenjangan keahlian"
      subtitle="Bandingkan keahlian aktual dengan kebutuhan, lengkap dengan rekomendasi pelatihan dan rekrutmen."
      tools={
        <Button variant="outline" size="icon" onClick={muatSemua} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      }>
      {loading && !requirements.length && !analyses.length ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat data…</p>
      ) : (
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList>
            <TabsTrigger value="analysis" data-testid="skill-gap-tab-analysis">Analisis</TabsTrigger>
            <TabsTrigger value="requirements" data-testid="skill-gap-tab-requirements">Kebutuhan keahlian</TabsTrigger>
            <TabsTrigger value="history" data-testid="skill-gap-tab-history">Riwayat</TabsTrigger>
          </TabsList>

          {/* ── Analisis ── */}
          <TabsContent value="analysis" className="mt-4 space-y-3">
            <BarisAlat
              kiri={<>
                <SmartNativeSelect searchable={false} value={analysisLevel} onChange={(e) => setAnalysisLevel(e.target.value)} className="w-56"
                  aria-label="Cakupan analisis" data-testid="skill-gap-level">
                  {Object.entries(LEVEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </SmartNativeSelect>
                {analysisLevel === 'department' && (
                  <SmartNativeSelect value={targetDept} onChange={(e) => setTargetDept(e.target.value)} className="w-56"
                    aria-label="Departemen" data-testid="skill-gap-dept">
                    <option value="">Pilih departemen</option>
                    {departments.map((d) => <option key={d} value={d}>{d}</option>)}
                  </SmartNativeSelect>
                )}
              </>}
              kanan={
                <Button data-testid="skill-gap-run-analyze" onClick={handleAnalyze} disabled={analyzing}>
                  {analyzing ? <><Loader2 className="animate-spin" />Menganalisis…</> : <><Sparkles />Analisis sekarang</>}
                </Button>
              } />
            <p className="text-sm text-muted-foreground">
              Analisis membandingkan keahlian aktual karyawan dengan kebutuhan keahlian yang sudah ditetapkan, lalu memberi rekomendasi pelatihan dan rekrutmen.
            </p>
            {currentResult ? <HasilAnalisis data={currentResult} /> : (
              <EmptyState title="Belum ada hasil" description='Pilih cakupan lalu klik "Analisis sekarang".' />
            )}
          </TabsContent>

          {/* ── Kebutuhan keahlian ── */}
          <TabsContent value="requirements" className="mt-4 space-y-3">
            <BarisAlat kiri={`${requirements.length} kebutuhan keahlian per jabatan atau departemen.`}
              kanan={<>
                <TombolUnduh namaBerkas="kebutuhan-keahlian" namaLembar="Kebutuhan" baris={requirements} testId="skill-gap-unduh-kebutuhan"
                  kolom={[
                    { label: 'Keahlian', nilai: (r) => r.skill_name }, { label: 'Kategori', nilai: (r) => labelKategori(r.category) },
                    { label: 'Tingkat (1–5)', nilai: (r) => r.required_level }, { label: 'Prioritas', nilai: (r) => labelPrioritas(r.priority) },
                    { label: 'Jabatan', nilai: (r) => r.for_role || '' }, { label: 'Departemen', nilai: (r) => r.for_department || '' },
                  ]} />
                <Button data-testid="skill-gap-add-requirement-btn" onClick={() => setReqDialogOpen(true)}><Plus />Tambah kebutuhan</Button>
              </>} />
            <TabelData kolom={kolomKebutuhan} baris={requirements} kunci={(r) => r.id} testId="skill-gap-requirements"
              kosong={<EmptyState title="Belum ada kebutuhan keahlian" description='Klik "Tambah kebutuhan" untuk mulai.' />} />
          </TabsContent>

          {/* ── Riwayat ── */}
          <TabsContent value="history" className="mt-4 space-y-3">
            <BarisAlat kiri={`${analyses.length} analisis tersimpan.`}
              kanan={
                <TombolUnduh namaBerkas="riwayat-analisis-keahlian" namaLembar="Riwayat" baris={analyses} testId="skill-gap-unduh-riwayat"
                  kolom={[
                    { label: 'Cakupan', nilai: (a) => LEVEL[a.level] || a.level || '' }, { label: 'Departemen', nilai: (a) => a.department || '' },
                    { label: 'Karyawan', nilai: (a) => a.employee_name || '' }, { label: 'Waktu', nilai: (a) => (a.analyzed_at ? formatDateTimeID(a.analyzed_at) : '') },
                    { label: 'Kesenjangan', nilai: (a) => (typeof a.gap_count === 'number' ? a.gap_count : '') },
                    { label: 'Kritis', nilai: (a) => (typeof a.critical_gaps === 'number' ? a.critical_gaps : '') },
                  ]} />
              } />
            <TabelData kolom={kolomRiwayat} baris={analyses} kunci={(a) => a.id || a.analyzed_at} onKlikBaris={setDetailData} testId="skill-gap-history"
              kosong={<EmptyState title="Belum ada analisis" description='Jalankan analisis baru di bagian "Analisis".' />} />
          </TabsContent>
        </Tabs>
      )}

      {/* Form kebutuhan */}
      <FormPopup open={reqDialogOpen} onClose={() => setReqDialogOpen(false)} ukuran="pendek" onSimpan={handleCreateRequirement}
        judul="Tambah kebutuhan keahlian" keterangan="Isi minimal salah satu: jabatan atau departemen." testId="skill-gap-req-form">
        <Isian label="Nama keahlian" wajib htmlFor="sg-nama">
          <Input id="sg-nama" data-testid="skill-gap-req-name" placeholder="Mis. menjahit overdeck, pola, Adobe Illustrator"
            value={reqForm.skill_name} onChange={(e) => setReqForm({ ...reqForm, skill_name: e.target.value })} />
        </Isian>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Kategori">
            <SmartNativeSelect searchable={false} value={reqForm.category} data-testid="skill-gap-req-category"
              onChange={(e) => setReqForm({ ...reqForm, category: e.target.value })}>
              {CATEGORY_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Tingkat dibutuhkan (1–5)" htmlFor="sg-level">
            <Input id="sg-level" data-testid="skill-gap-req-level" type="number" min={1} max={5} value={reqForm.required_level}
              onChange={(e) => setReqForm({ ...reqForm, required_level: Number(e.target.value) })} />
          </Isian>
          <Isian label="Prioritas">
            <SmartNativeSelect searchable={false} value={reqForm.priority} data-testid="skill-gap-req-priority"
              onChange={(e) => setReqForm({ ...reqForm, priority: e.target.value })}>
              {PRIORITY_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Untuk jabatan (opsional)" htmlFor="sg-role">
            <Input id="sg-role" data-testid="skill-gap-req-role" placeholder="Mis. Operator potong" value={reqForm.for_role}
              onChange={(e) => setReqForm({ ...reqForm, for_role: e.target.value })} />
          </Isian>
        </div>
        <Isian label="Untuk departemen (opsional)">
          <SmartNativeSelect value={reqForm.for_department || ''} data-testid="skill-gap-req-dept"
            onChange={(e) => setReqForm({ ...reqForm, for_department: e.target.value })}>
            <option value="">— Tidak spesifik —</option>
            {departments.map((d) => <option key={d} value={d}>{d}</option>)}
          </SmartNativeSelect>
        </Isian>
      </FormPopup>

      {/* Detail riwayat */}
      {detailData && (
        <DetailPopup open onClose={() => setDetailData(null)} judul="Detail analisis kesenjangan keahlian" testId="skill-gap-detail"
          keterangan={detailData.analyzed_at ? formatDateTimeID(detailData.analyzed_at) : undefined}>
          <HasilAnalisis data={detailData} />
        </DetailPopup>
      )}
    </PageLayout>
  );
}

// ───────────────────────── Hasil analisis ─────────────────────────
function HasilAnalisis({ data }) {
  if (!data) return null;
  const individu = data.level === 'individual' || data.employee_id;
  const departemen = !individu && (data.level === 'department' || data.department);

  const kolomGap = [
    { kunci: 'skill', label: 'Keahlian', hp: 'judul', isi: (g) => (
      <div><p className="font-medium text-foreground">{g.skill_name}</p><p className="text-xs text-muted-foreground">{labelKategori(g.category)}</p></div>) },
    { kunci: 'pri', label: 'Prioritas', isi: (g) => <Prioritas nilai={g.priority} /> },
    { kunci: 'sev', label: 'Keparahan', isi: (g) => <span className="text-sm">{SEVERITY[g.gap_severity] || g.gap_severity || '—'}</span> },
    ...(individu ? [
      { kunci: 'lv', label: 'Tingkat sekarang', rata: 'kanan', isi: (g) => <span className="tabular-nums">{g.current_level ?? 0}/{g.required_level}</span> },
      { kunci: 'capai', label: 'Tercapai', rata: 'kanan', isi: (g) => (
        <span className="tabular-nums">{g.required_level ? Math.round(((g.current_level || 0) / g.required_level) * 100) : 0}%</span>) },
    ] : [
      { kunci: 'n', label: 'Karyawan kurang', rata: 'kanan', isi: (g) => <span className="tabular-nums">{g.employees_with_gap ?? '—'}</span> },
      { kunci: 'avg', label: 'Rata-rata tingkat', rata: 'kanan', isi: (g) => <span className="tabular-nums">{g.average_level ?? '—'}/{g.required_level}</span> },
      { kunci: 'cov', label: 'Terpenuhi', rata: 'kanan', isi: (g) => <span className="tabular-nums">{Number(g.coverage_percentage || 0)}%</span> },
    ]),
  ];

  return (
    <div className="space-y-4">
      {individu ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Karyawan" value={data.employee_name || '—'} />
          <StatTile label="Kesenjangan" value={data.total_gaps ?? 0} sub="Keahlian di bawah tingkat yang dibutuhkan." />
          <StatTile label="Kesenjangan kritis" value={data.critical_gaps ?? 0} accent={data.critical_gaps ? 'danger' : 'default'} sub="Prioritas kritis." />
        </div>
      ) : departemen ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Departemen" value={data.department || '—'} />
          <StatTile label="Karyawan" value={data.total_employees ?? 0} sub="Dianalisis di departemen ini." />
          <StatTile label="Kesenjangan" value={data.total_gaps ?? 0} sub="Keahlian yang belum terpenuhi." />
          <StatTile label="Kesenjangan kritis" value={data.critical_gaps ?? 0} accent={data.critical_gaps ? 'danger' : 'default'} sub="Prioritas kritis." />
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Karyawan" value={data.total_employees ?? 0} sub="Seluruh perusahaan." />
          <StatTile label="Departemen" value={data.total_departments ?? 0} />
          <StatTile label="Departemen dengan kebutuhan" value={data.department_breakdown?.length ?? 0} sub="Punya kebutuhan keahlian." />
        </div>
      )}

      {(individu || departemen) && data.gaps?.length > 0 && (
        <section className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-foreground">Kesenjangan keahlian</p>
            <TombolUnduh namaBerkas="kesenjangan-keahlian" namaLembar="Kesenjangan" baris={data.gaps}
              kolom={[
                { label: 'Keahlian', nilai: (g) => g.skill_name }, { label: 'Kategori', nilai: (g) => labelKategori(g.category) },
                { label: 'Prioritas', nilai: (g) => labelPrioritas(g.priority) }, { label: 'Keparahan', nilai: (g) => SEVERITY[g.gap_severity] || g.gap_severity || '' },
                { label: 'Tingkat dibutuhkan', nilai: (g) => g.required_level },
                { label: individu ? 'Tingkat sekarang' : 'Rata-rata tingkat', nilai: (g) => (individu ? g.current_level : g.average_level) ?? '' },
                ...(individu ? [] : [{ label: 'Karyawan kurang', nilai: (g) => g.employees_with_gap ?? '' }, { label: 'Terpenuhi (%)', nilai: (g) => g.coverage_percentage ?? '' }]),
              ]} />
          </div>
          <TabelData kolom={kolomGap} baris={data.gaps} kunci={(g) => g.skill_name} testId="skill-gap-gaps" />
        </section>
      )}

      {!individu && !departemen && data.department_breakdown?.length > 0 && (
        <section className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-foreground">Per departemen</p>
            <TombolUnduh namaBerkas="keahlian-per-departemen" namaLembar="Per departemen" baris={data.department_breakdown}
              kolom={[{ label: 'Departemen', nilai: (d) => d.department }, { label: 'Karyawan', nilai: (d) => d.employee_count },
                { label: 'Kebutuhan keahlian', nilai: (d) => d.skill_requirements }]} />
          </div>
          <TabelData baris={data.department_breakdown} kunci={(d) => d.department} testId="skill-gap-breakdown"
            kolom={[
              { kunci: 'dept', label: 'Departemen', hp: 'judul', isi: (d) => <span className="font-medium text-foreground">{d.department}</span> },
              { kunci: 'emp', label: 'Karyawan', rata: 'kanan', isi: (d) => <span className="tabular-nums">{d.employee_count}</span> },
              { kunci: 'req', label: 'Kebutuhan keahlian', rata: 'kanan', isi: (d) => <span className="tabular-nums">{d.skill_requirements}</span> },
            ]} />
        </section>
      )}

      {data.recommendations?.length > 0 && (
        <section className="space-y-2">
          <p className="text-sm font-semibold text-foreground">Rekomendasi</p>
          <ul className="divide-y divide-[var(--glass-border)] rounded-lg border border-[var(--glass-border)]">
            {data.recommendations.map((rec, i) => (
              <li key={i} className="space-y-1 px-3 py-2">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-sm font-medium text-foreground">{rec.title}</p>
                  {rec.priority && <Prioritas nilai={rec.priority} />}
                </div>
                {rec.description && <p className="text-sm text-muted-foreground">{rec.description}</p>}
                {(rec.skills || rec.skills_addressed || rec.skills_needed || []).length > 0 && (
                  <p className="text-xs text-muted-foreground">Keahlian: {(rec.skills || rec.skills_addressed || rec.skills_needed).join(', ')}</p>
                )}
                {(rec.estimated_cost || rec.estimated_budget || rec.timeline || rec.estimated_duration) && (
                  <p className="text-xs text-muted-foreground">
                    {(rec.estimated_cost || rec.estimated_budget) && <>Perkiraan biaya: {rec.estimated_cost || rec.estimated_budget}. </>}
                    {(rec.timeline || rec.estimated_duration) && <>Waktu: {rec.timeline || rec.estimated_duration}.</>}
                  </p>
                )}
                {rec.suggested_actions?.length > 0 && (
                  <ul className="list-disc space-y-0.5 pl-5 text-sm text-muted-foreground">{rec.suggested_actions.map((a, k) => <li key={k}>{a}</li>)}</ul>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

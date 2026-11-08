/**
 * Portal Saya › KPI — isi form penilaian (diri, rekan, atasan) dan lihat hasil KPI.
 *
 * Standar UI/UX v2 (8 Nov 2026): satu halaman PageLayout (dulu 4 "halaman" bergantian dengan tombol Kembali);
 * periode aktif & riwayat hasil = tabel (+ unduh Excel/CSV); daftar form satu periode, rincian hasil, dan
 * pencapaian dibuka sebagai popup; mengisi form = FormPopup panjang (Simpan draf · Batal · Kirim form hijau);
 * nilai pakai lencana StatusBadge (dulu kartu gradien warna-warni); istilah Indonesia. Endpoint tidak berubah.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { ChevronRight, Eye, RefreshCw, Trophy } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { toast } from 'sonner';
import { formatDateID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from './moduleAtoms';
import KPIGamificationTab from './KPIGamificationTab';

const API = process.env.REACT_APP_BACKEND_URL;
const kpi = (path, opts = {}) => fetch(`${API}/api/dewi/kpi${path}`, opts);

const GRADE_CFG = {
  A: { tone: 'success', label: 'Sangat baik', raise: 'Naik gaji 10%' },
  B: { tone: 'info', label: 'Baik', raise: 'Pertahankan / perpanjang kontrak (7%)' },
  C: { tone: 'warning', label: 'Cukup', raise: 'Mediasi / evaluasi' },
  D: { tone: 'danger', label: 'Kurang', raise: 'Putus kontrak (cut off)' },
  E: { tone: 'danger', label: 'Sangat kurang', raise: 'Putus kontrak (cut off)' },
};

const EVAL_TYPE_CFG = {
  self: { label: 'Penilaian diri', desc: 'Penilaian diri sendiri' },
  peer: { label: 'Penilaian rekan', desc: 'Menilai rekan kerja (anonim)' },
  supervisor_to_staff: { label: 'Atasan → staf', desc: 'Penilaian atasan untuk Anda' },
  staff_to_supervisor: { label: 'Staf → atasan', desc: 'Menilai atasan Anda (anonim)' },
};
const STATUS_FORM = {
  submitted: { label: 'Terkirim', tone: 'success' },
  draft: { label: 'Draf', tone: 'warning' },
  not_started: { label: 'Belum dimulai', tone: 'muted' },
};
const statusForm = (s) => STATUS_FORM[s] || STATUS_FORM.not_started;
const angka = (v) => (v != null ? Number(v).toFixed(1).replace('.', ',') : '—');
const tgl = (v) => (v ? formatDateID(String(v).slice(0, 10)) : '—');

function NilaiBadge({ grade }) {
  if (!grade) return <span className="text-muted-foreground">—</span>;
  const g = GRADE_CFG[grade];
  return <StatusBadge status={grade} label={`Nilai ${grade}${g ? ` · ${g.label}` : ''}`} tone={g?.tone || 'default'} />;
}

export default function KPIPortalModule({ token }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);
  const [view, setView] = useState('list'); // list | form | results | achievement (popup yang terbuka)
  const [periods, setPeriods] = useState([]);
  const [myResults, setMyResults] = useState([]);
  const [currentPeriod, setCurrentPeriod] = useState(null);
  const [formData, setFormData] = useState(null); // {period, forms_to_fill, questions_by_type, ...}
  const [activeForm, setActiveForm] = useState(null); // form item being filled
  const [answers, setAnswers] = useState({}); // {question_id: score}
  const [submitting, setSubmitting] = useState(false);
  const [loading, setLoading] = useState(true);
  const [selectedResult, setSelectedResult] = useState(null);

  const loadPeriods = useCallback(async () => {
    try {
      const r = await kpi('/my/periods', { headers });
      const d = await r.json();
      setPeriods(d.periods || []);
    } catch (e) { console.error(e); }
  }, [headers]);

  const loadResults = useCallback(async () => {
    try {
      const r = await kpi('/my/results', { headers });
      const d = await r.json();
      setMyResults(d.results || []);
    } catch (e) { console.error(e); }
  }, [headers]);

  useEffect(() => {
    Promise.all([loadPeriods(), loadResults()]).finally(() => setLoading(false));
  }, [loadPeriods, loadResults]);

  const openForms = async (period) => {
    setCurrentPeriod(period);
    try {
      const r = await kpi(`/my/forms/${period.period_id}`, { headers });
      const d = await r.json();
      if (!r.ok) { toast.error(d.detail || 'Gagal memuat form'); return; }
      setFormData(d);
      setView('form');
    } catch (e) {
      toast.error('Gagal memuat form');
    }
  };

  const startForm = (formItem) => {
    setActiveForm(formItem);
    setAnswers({});
  };

  const handleAnswer = (qid, score) => {
    setAnswers(prev => ({ ...prev, [qid]: score }));
  };

  const submitForm = async (isSubmit) => {
    const answersArr = Object.entries(answers).map(([question_id, score]) => ({ question_id, score }));
    const r = await kpi('/submissions', {
      method: 'POST',
      headers,
      body: JSON.stringify({
        period_id: currentPeriod.period_id,
        eval_type: activeForm.eval_type,
        evaluatee_id: activeForm.evaluatee_id,
        answers: answersArr,
        submit: isSubmit,
      }),
    });
    const d = await r.json();
    if (!r.ok) { toast.error(d.detail || 'Gagal'); throw new Error(d.detail); }
    return d;
  };

  const handleSaveDraft = async () => {
    if (!activeForm) return;
    setSubmitting(true);
    try {
      await submitForm(false);
      toast.success('Draf tersimpan.');
    } catch { /* pesan sudah tampil */ } finally { setSubmitting(false); }
  };

  const handleSubmitForm = async () => {
    const questions = formData?.questions_by_type?.[activeForm.eval_type] || [];
    const unanswered = questions.filter(q => !answers[q.question_id]);
    if (unanswered.length > 0) {
      if (!(await confirmDialog({ title: `Masih ada ${unanswered.length} pertanyaan yang belum dijawab. Tetap kirim?`, confirmLabel: 'Tetap kirim' }))) return;
    }
    setSubmitting(true);
    try {
      await submitForm(true);
      toast.success('Form berhasil dikirim.');
      setActiveForm(null);
      // Muat ulang daftar form periode ini
      const r = await kpi(`/my/forms/${currentPeriod.period_id}`, { headers });
      const d = await r.json();
      setFormData(d);
    } catch { /* pesan sudah tampil */ } finally {
      setSubmitting(false);
    }
  };

  const openResult = async (period) => {
    try {
      const r = await kpi(`/my/result/${period.period_id}`, { headers });
      const d = await r.json();
      if (!r.ok) { toast.error(d.detail || 'Gagal'); return; }
      setSelectedResult(d);
      setView('results');
    } catch (e) { toast.error('Gagal memuat hasil'); }
  };

  const aktif = periods.filter(p => p.status === 'open');
  const tutup = () => { setView('list'); setSelectedResult(null); };

  // ── Popup: rincian hasil ───────────────────────────────────────────────────
  const popupHasil = () => {
    const res = selectedResult?.result;
    const g = GRADE_CFG[res?.grade];
    return (
      <DetailPopup open onClose={tutup} testId="kpi-result-detail" judul="Hasil KPI"
        keterangan={res?.period_name || selectedResult?.period?.name}>
        {!selectedResult?.published ? (
          <EmptyState title="Hasil KPI sedang diproses" description={selectedResult?.message} />
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <StatTile label="Nilai akhir KPI" value={angka(res.kpi_final)} sub={g?.raise} />
              <StatTile label="Kinerja (60%)" value={angka(res.perform_score)} />
              <StatTile label="Sikap (20%)" value={angka(res.attitude_score)} />
              <StatTile label="Absensi (20%)" value={angka(res.absensi_score)} />
            </div>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <NilaiBadge grade={res.grade} />
              {g?.raise && <span className="text-muted-foreground">Tindak lanjut: {g.raise}</span>}
            </div>
            {res.attitude_detail?.component_scores && (
              <div>
                <p className="mb-1 text-sm font-medium">Rincian sikap (360°)</p>
                <dl className="divide-y divide-[var(--glass-border)]">
                  {[
                    { key: 'self', label: 'Penilaian diri (20%)' },
                    { key: 'peer', label: 'Penilaian rekan (20%)' },
                    { key: 'supervisor_to_staff', label: 'Atasan → Anda (35%)' },
                    { key: 'staff_to_supervisor', label: 'Anda → atasan (25%)' },
                  ].map(c => {
                    const s = res.attitude_detail.component_scores[c.key];
                    return <BarisDetail key={c.key} label={c.label}>{s != null ? angka(s) : <span className="text-muted-foreground">Belum ada</span>}</BarisDetail>;
                  })}
                </dl>
              </div>
            )}
            {res.absensi_detail?.breakdown && (
              <div>
                <p className="mb-1 text-sm font-medium">Rincian absensi</p>
                <dl className="divide-y divide-[var(--glass-border)]">
                  {Object.entries(res.absensi_detail.breakdown).filter(([, v]) => v > 0).map(([k, v]) => (
                    <BarisDetail key={k} label={k.charAt(0).toUpperCase() + k.slice(1)}>{v} hari</BarisDetail>
                  ))}
                  <BarisDetail label="Total tidak hadir">{res.absensi_detail.absent_days} dari {res.absensi_detail.working_days} hari kerja</BarisDetail>
                </dl>
              </div>
            )}
          </>
        )}
      </DetailPopup>
    );
  };

  // ── Popup: daftar form satu periode ────────────────────────────────────────
  const popupForms = () => {
    const allForms = [...(formData.forms_to_fill || []), ...(formData.supervisor_forms || []).map((f) => ({ ...f, _sup: true }))];
    const completedForms = allForms.filter(f => f.status === 'submitted').length;
    return (
      <DetailPopup open onClose={tutup} testId="kpi-forms" judul={formData.period?.name || 'Form KPI'}
        keterangan={`${tgl(formData.period?.period_from)} – ${tgl(formData.period?.period_to)} · ${completedForms} dari ${allForms.length} form selesai`}>
        <TabelData baris={allForms} kunci={(f) => `${f._sup ? 'sup' : 'me'}-${f.eval_type}-${f.evaluatee_id || ''}`}
          kosong={<EmptyState title="Tidak ada form untuk Anda di periode ini" />}
          kolom={[
            { kunci: 'jenis', label: 'Form', hp: 'judul', isi: (f) => (f._sup ? `Penilaian untuk ${f.evaluatee_name}` : (EVAL_TYPE_CFG[f.eval_type]?.label || 'Form')) },
            { kunci: 'untuk', label: 'Keterangan', isi: (f) => <span className="text-sm text-muted-foreground">{
              f._sup ? 'Atasan → staf' : f.eval_type === 'self' ? 'Untuk diri sendiri'
                : f.eval_type === 'peer' ? `Menilai: ${f.evaluatee_name}`
                  : f.eval_type === 'staff_to_supervisor' ? 'Menilai atasan Anda (anonim)' : EVAL_TYPE_CFG[f.eval_type]?.desc}</span> },
            { kunci: 'status', label: 'Status', isi: (f) => <StatusBadge status={f.status} label={statusForm(f.status).label} tone={statusForm(f.status).tone} /> },
            { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (f) => (
              <Button size="sm" variant={f.status === 'submitted' ? 'outline' : 'default'} disabled={f.status === 'submitted'}
                onClick={() => startForm(f)} data-testid={f._sup ? undefined : `start-form-${f.eval_type}`}>
                {f.status === 'submitted' ? 'Selesai' : f.status === 'draft' ? 'Lanjutkan' : f._sup ? 'Isi form' : 'Mulai'}
              </Button>) },
          ]} />
      </DetailPopup>
    );
  };

  // ── Popup: mengisi satu form ───────────────────────────────────────────────
  const popupIsi = () => {
    const questions = formData.questions_by_type?.[activeForm.eval_type] || [];
    const categories = [...new Set(questions.map(q => q.category))];
    const answeredCount = Object.keys(answers).filter(qid => questions.find(q => q.question_id === qid)).length;
    return (
      <FormPopup open onClose={() => setActiveForm(null)} ukuran="panjang" testId="kpi-fill-form"
        judul={`${EVAL_TYPE_CFG[activeForm.eval_type]?.label || 'Form'}${activeForm.is_anonymous ? ' (anonim)' : ''}`}
        keterangan={`${activeForm.eval_type === 'peer' ? `Menilai: ${activeForm.evaluatee_name} · ` : ''}${answeredCount} dari ${questions.length} pertanyaan dijawab. Skala 1 = sangat tidak setuju, 5 = sangat setuju.`}
        onSimpan={handleSubmitForm} menyimpan={submitting} labelSimpan="Kirim form"
        aksiKiri={<Button type="button" variant="outline" onClick={handleSaveDraft} disabled={submitting}>Simpan draf</Button>}>
        {categories.map(cat => (
          <div key={cat} className="space-y-3">
            <p className="text-sm font-medium text-foreground">{cat}</p>
            {questions.filter(q => q.category === cat).map((q, qi) => (
              <div key={q.question_id} className="space-y-2 border-b border-[var(--glass-border)] pb-3 last:border-0">
                <p className="text-sm text-foreground">{q.question_text}</p>
                <div className="flex gap-2" role="radiogroup" aria-label={q.question_text} data-testid={`question-${qi}`}>
                  {[1, 2, 3, 4, 5].map(score => (
                    <button key={score} type="button" role="radio" aria-checked={answers[q.question_id] === score}
                      onClick={() => handleAnswer(q.question_id, score)}
                      className={`h-9 flex-1 rounded-md border text-sm font-semibold transition-colors ${
                        answers[q.question_id] === score
                          ? 'border-primary bg-primary text-primary-foreground'
                          : 'border-[var(--glass-border)] bg-[var(--card-surface)] text-muted-foreground hover:text-foreground'}`}>
                      {score}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ))}
      </FormPopup>
    );
  };

  return (
    <PageLayout testId="kpi-portal" title="KPI" subtitle="Isi form penilaian dan lihat hasil KPI Anda."
      tools={<>
        <Button variant="outline" onClick={() => setView('achievement')}><Trophy />Pencapaian</Button>
        <Button variant="outline" size="icon" onClick={() => { loadPeriods(); loadResults(); }} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw />
        </Button>
      </>}>
      {loading ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat KPI…</p>
      ) : periods.length === 0 && myResults.length === 0 ? (
        <EmptyState title="Belum ada periode KPI" description="HR akan membuka periode KPI saat tersedia." />
      ) : (
        <>
          {aktif.length > 0 && (
            <GlassCard className="space-y-3 p-4">
              <h3 className="text-lg font-semibold text-foreground">Form aktif</h3>
              <TabelData baris={aktif} kunci={(p) => p.period_id} kolom={[
                { kunci: 'name', label: 'Periode', hp: 'judul', isi: (p) => <span className="font-medium">{p.name}</span> },
                { kunci: 'rentang', label: 'Rentang', isi: (p) => <span className="whitespace-nowrap text-sm">{tgl(p.period_from)} – {tgl(p.period_to)}</span> },
                { kunci: 'kirim', label: 'Form terkirim', rata: 'kanan', isi: (p) => <span className="tabular-nums">{p.my_submitted_forms || 0}</span> },
                { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (p) => (
                  <Button size="sm" onClick={() => openForms(p)} data-testid="open-kpi-form-btn">Isi form<ChevronRight /></Button>) },
              ]} />
            </GlassCard>
          )}

          <GlassCard className="space-y-3 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-lg font-semibold text-foreground">Riwayat hasil KPI</h3>
              {myResults.length > 0 && (
                <TombolUnduh namaBerkas="hasil-kpi-saya" namaLembar="Hasil KPI" baris={myResults} testId="kpi-unduh" kolom={[
                  { label: 'Periode', nilai: (r) => r.period_name }, { label: 'Nilai akhir', nilai: (r) => r.kpi_final ?? '' },
                  { label: 'Nilai', nilai: (r) => r.grade || '' }, { label: 'Kinerja', nilai: (r) => r.perform_score ?? '' },
                  { label: 'Sikap', nilai: (r) => r.attitude_score ?? '' }, { label: 'Absensi', nilai: (r) => r.absensi_score ?? '' },
                ]} />
              )}
            </div>
            <TabelData baris={myResults} kunci={(r) => r.result_id} onKlikBaris={openResult}
              kosong={periods.some(p => p.status !== 'open')
                ? <EmptyState title="Hasil KPI sedang diproses oleh HR" />
                : <EmptyState title="Belum ada hasil KPI" />}
              kolom={[
              { kunci: 'period_name', label: 'Periode', hp: 'judul', isi: (r) => <span className="font-medium" data-testid={`kpi-result-${r.period_id}`}>{r.period_name}</span> },
              { kunci: 'final', label: 'Nilai akhir', rata: 'kanan', isi: (r) => <span className="font-semibold tabular-nums">{angka(r.kpi_final)}</span> },
              { kunci: 'grade', label: 'Nilai', isi: (r) => <NilaiBadge grade={r.grade} /> },
              { kunci: 'perform', label: 'Kinerja', rata: 'kanan', isi: (r) => <span className="tabular-nums">{angka(r.perform_score)}</span> },
              { kunci: 'attitude', label: 'Sikap', rata: 'kanan', isi: (r) => <span className="tabular-nums">{angka(r.attitude_score)}</span> },
              { kunci: 'absensi', label: 'Absensi', rata: 'kanan', isi: (r) => <span className="tabular-nums">{angka(r.absensi_score)}</span> },
              { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
                <Button size="sm" variant="outline" onClick={() => openResult(r)}><Eye />Rincian</Button>) },
            ]} />
          </GlassCard>
        </>
      )}

      {view === 'results' && selectedResult && popupHasil()}
      {view === 'form' && formData && popupForms()}
      {view === 'form' && formData && activeForm && popupIsi()}
      {view === 'achievement' && (
        <DetailPopup open onClose={tutup} testId="kpi-achievement" judul="Pencapaian saya"
          keterangan="Lencana dan penghargaan yang telah Anda raih.">
          <KPIGamificationTab token={token} periods={periods} isHR={false} />
        </DetailPopup>
      )}
    </PageLayout>
  );
}

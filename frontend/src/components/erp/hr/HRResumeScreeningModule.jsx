/**
 * Screening CV (Portal SDM) — analisis CV pelamar dengan AI sebagai USULAN (K28: HR yang memutuskan).
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, form screening = FormPopup (dulu panel besar di halaman),
 * hasil = DetailPopup, riwayat = tabel + unduh Excel/CSV (dulu kartu berulang, diam-diam 10 terakhir),
 * label rekomendasi/kecocokan/area fokus berbahasa Indonesia (nilai yang dikirim ke server tetap sama),
 * tanpa gradien/ikon besar, warna token.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { RefreshCw, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { formatDateID } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatusBadge } from '../moduleAtoms';
import AISuggestionPanel from '../AISuggestionPanel';

// Nilai dari server (bahasa Inggris) → label layar.
const REKOMENDASI = {
  'Strongly Recommended': { label: 'Sangat disarankan', tone: 'success' },
  'Recommended': { label: 'Disarankan', tone: 'info' },
  'Consider': { label: 'Pertimbangkan', tone: 'warning' },
  'Not Recommended': { label: 'Tidak disarankan', tone: 'danger' },
};
const labelRek = (r) => REKOMENDASI[r]?.label || r || '—';
function Rekomendasi({ nilai }) {
  if (!nilai) return <span className="text-muted-foreground">—</span>;
  const r = REKOMENDASI[nilai] || { label: nilai, tone: 'default' };
  return <StatusBadge status={nilai} label={r.label} tone={r.tone} />;
}

// K28 (2026-11-02): skor AI kandidat = usulan; HR Terima/Ubah/Tolak sebelum jadi skor resmi.
const SCORE_SUGGESTION_FIELDS = [
  { key: 'ai_score', label: 'Skor AI (0–100)', type: 'number' },
  { key: 'ai_recommendation', label: 'Rekomendasi', options: Object.entries(REKOMENDASI).map(([v, r]) => ({ value: v, label: r.label })) },
];

const MATCH_BADGE = {
  yes: { label: 'Cocok', tone: 'success' },
  partial: { label: 'Sebagian', tone: 'warning' },
  no: { label: 'Tidak cocok', tone: 'danger' },
};
const AREA_FOKUS = [
  { nilai: 'skills', label: 'Keahlian' },
  { nilai: 'experience', label: 'Pengalaman' },
  { nilai: 'education', label: 'Pendidikan' },
  { nilai: 'communication', label: 'Komunikasi' },
];
const KOSONG = { job_requirements: '', focus_areas: [] };

/** Isi hasil analisis (dipakai untuk hasil baru dan riwayat). */
function IsiAnalisis({ analysis = {} }) {
  return (
    <>
      <dl className="divide-y divide-[var(--glass-border)]">
        <BarisDetail label="Skor keseluruhan">
          <span className="text-base font-semibold tabular-nums">{analysis.overall_score ?? '—'}</span>
          <span className="text-muted-foreground"> / 100</span>
        </BarisDetail>
        <BarisDetail label="Rekomendasi"><Rekomendasi nilai={analysis.recommendation} /></BarisDetail>
      </dl>
      {analysis.summary && <p className="text-sm leading-relaxed text-foreground">{analysis.summary}</p>}
      {analysis.strengths?.length > 0 && (
        <div>
          <p className="mb-1 text-sm font-medium text-foreground">Kekuatan</p>
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            {analysis.strengths.map((s, i) => <li key={i}>{s}</li>)}
          </ul>
        </div>
      )}
      {analysis.weaknesses?.length > 0 && (
        <div>
          <p className="mb-1 text-sm font-medium text-foreground">Area pengembangan</p>
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            {analysis.weaknesses.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        </div>
      )}
      {analysis.skill_match?.length > 0 && (
        <div>
          <p className="mb-1 text-sm font-medium text-foreground">Kesesuaian keahlian</p>
          <TabelData baris={analysis.skill_match} kunci={(sm) => sm.skill} testId="resume-skill-match"
            kolom={[
              { kunci: 'skill', label: 'Keahlian', hp: 'judul' },
              { kunci: 'match', label: 'Kecocokan', isi: (sm) => {
                const b = MATCH_BADGE[sm.match] || MATCH_BADGE.no;
                return <StatusBadge status={sm.match} label={b.label} tone={b.tone} />;
              } },
            ]} />
        </div>
      )}
    </>
  );
}

export default function HRResumeScreeningModule({ token }) {
  const [candidates, setCandidates] = useState([]);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [screening, setScreening] = useState(false);
  const [bukaForm, setBukaForm] = useState(false);
  const [selectedCandidate, setSelectedCandidate] = useState(null);
  const [result, setResult] = useState(null);       // hasil screening baru (popup)
  const [lihat, setLihat] = useState(null);         // baris riwayat (popup)
  const [formData, setFormData] = useState(KOSONG);

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);

  const fetchCandidates = useCallback(async () => {
    setLoading(true);
    try {
      // 2026-11-02: daftar PELAMAR (dewi_recruitment_candidates), bukan daftar karyawan —
      // dulu id karyawan dikirim sebagai candidate_id sehingga screening selalu 404.
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/dewi/recruitment/candidates?limit=200`, { headers });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setCandidates(data?.candidates || []);
    } catch (e) {
      toast.error(`Gagal memuat kandidat: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [headers]);

  const fetchHistory = useCallback(async () => {
    try {
      // Dulu 20 terakhir & hanya 10 yang tampil; kini sampai 200 riwayat.
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/hr/ai/resume-screen/history?limit=200`, { headers });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setHistory(data?.data || []);
    } catch (e) {
      console.error('History fetch failed:', e);
    }
  }, [headers]);

  useEffect(() => {
    fetchCandidates();
    fetchHistory();
  }, [fetchCandidates, fetchHistory]);

  const muatUlang = () => { fetchCandidates(); fetchHistory(); };

  const handleScreen = async () => {
    if (!selectedCandidate) {
      toast.error('Pilih kandidat terlebih dahulu');
      return;
    }
    setScreening(true);
    setResult(null);
    try {
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/hr/ai/resume-screen/${selectedCandidate}`, {
        method: 'POST',
        headers,
        body: JSON.stringify(formData),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setResult(data?.data);
      setBukaForm(false);
      toast.success('Screening selesai!', { icon: <Sparkles className="h-4 w-4" /> });
      fetchHistory();
    } catch (e) {
      toast.error(`Screening gagal: ${e.message}`);
    } finally {
      setScreening(false);
    }
  };

  const alihFokus = (area) => setFormData((f) => ({
    ...f,
    focus_areas: f.focus_areas.includes(area) ? f.focus_areas.filter((a) => a !== area) : [...f.focus_areas, area],
  }));
  const namaKandidat = (id) => {
    const c = candidates.find((x) => x.candidate_id === id);
    return c ? `${c.name} — ${c.job_title || c.position_applied || 'posisi belum diisi'}` : '';
  };

  const kolom = [
    { kunci: 'nama', label: 'Kandidat', hp: 'judul', isi: (h) => <span className="font-medium text-foreground">{h.candidate_name || '—'}</span> },
    { kunci: 'posisi', label: 'Posisi', hp: 'keterangan', isi: (h) => <span className="text-sm">{h.position || '—'}</span> },
    { kunci: 'tanggal', label: 'Tanggal', isi: (h) => <span className="text-sm md:whitespace-nowrap">{formatDateID(h.generated_at)}</span> },
    { kunci: 'skor', label: 'Skor', rata: 'kanan', isi: (h) => <span className="font-semibold tabular-nums">{h.analysis?.overall_score ?? '—'}</span> },
    { kunci: 'rek', label: 'Rekomendasi', isi: (h) => <Rekomendasi nilai={h.analysis?.recommendation} /> },
  ];

  return (
    <PageLayout testId="hr-resume-screening" title="Screening CV"
      subtitle="Nilai CV pelamar dengan AI sebagai usulan; keputusan skor tetap di tangan SDM."
      actions={<Button onClick={() => setBukaForm(true)} data-testid="resume-screen-new"><Sparkles />Screening baru</Button>}
      tools={<>
        <TombolUnduh namaBerkas="riwayat-screening-cv" namaLembar="Riwayat" baris={history} testId="resume-history-unduh"
          kolom={[
            { label: 'Kandidat', nilai: (h) => h.candidate_name || '' },
            { label: 'Posisi', nilai: (h) => h.position || '' },
            { label: 'Tanggal', nilai: (h) => formatDateID(h.generated_at) },
            { label: 'Skor', nilai: (h) => h.analysis?.overall_score ?? '' },
            { label: 'Rekomendasi', nilai: (h) => labelRek(h.analysis?.recommendation) },
            { label: 'Ringkasan', nilai: (h) => h.analysis?.summary || '' },
          ]} />
        <Button variant="outline" size="icon" onClick={muatUlang} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}>
      <TabelData kolom={kolom} baris={history} kunci={(h) => h.id || `${h.candidate_id}-${h.generated_at}`} onKlikBaris={setLihat}
        testId="resume-history"
        kosong={<EmptyState title="Belum ada riwayat screening"
          description={candidates.length ? 'Klik "Screening baru", pilih pelamar, lalu biarkan AI menilai CV-nya.'
            : 'Belum ada pelamar. Tambahkan pelamar di menu Rekrutmen & ATS terlebih dahulu.'}
          action={<Button onClick={() => setBukaForm(true)}><Sparkles />Screening baru</Button>} />} />

      {/* ─── Form screening (popup) ─── */}
      <FormPopup open={bukaForm} onClose={() => setBukaForm(false)} ukuran="pendek" onSimpan={handleScreen}
        menyimpan={screening} bisaSimpan={!!selectedCandidate} labelSimpan="Mulai screening" testId="resume-screen-form"
        judul="Screening CV baru" keterangan="AI membaca CV pelamar dan memberi skor serta rekomendasi sebagai usulan.">
        <Isian label="Kandidat" wajib htmlFor="resume-kandidat"
          petunjuk={candidates.length ? `${candidates.length} pelamar tersedia.` : 'Belum ada pelamar di Rekrutmen & ATS.'}>
          <SmartNativeSelect id="resume-kandidat" value={selectedCandidate || ''} onChange={(e) => setSelectedCandidate(e.target.value || null)}
            data-testid="resume-candidate-select">
            <option value="">Pilih kandidat…</option>
            {candidates.map((c) => (
              <option key={c.candidate_id} value={c.candidate_id}>{c.name} - {c.job_title || c.position_applied || 'posisi belum diisi'}</option>
            ))}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Persyaratan tambahan (opsional)" htmlFor="resume-syarat">
          <Textarea id="resume-syarat" rows={3} value={formData.job_requirements}
            onChange={(e) => setFormData({ ...formData, job_requirements: e.target.value })}
            placeholder="Misal: minimal 3 tahun pengalaman di garmen" />
        </Isian>
        <Isian label="Area fokus" petunjuk="Boleh lebih dari satu, atau kosongkan untuk penilaian umum.">
          <div className="flex flex-wrap gap-1.5">
            {AREA_FOKUS.map((a) => {
              const aktif = formData.focus_areas.includes(a.nilai);
              return (
                <Button key={a.nilai} type="button" size="sm" variant={aktif ? 'default' : 'outline'} className="rounded-full"
                  onClick={() => alihFokus(a.nilai)} aria-pressed={aktif} data-testid={`resume-focus-${a.nilai}`}>
                  {a.label}
                </Button>
              );
            })}
          </div>
        </Isian>
      </FormPopup>

      {/* ─── Hasil screening baru (popup) ─── */}
      {result && (
        <DetailPopup open onClose={() => setResult(null)} testId="resume-result"
          judul={result.candidate?.name || namaKandidat(selectedCandidate) || 'Hasil screening'}
          keterangan="Skor dan rekomendasi AI adalah usulan — terima, ubah, atau tolak di bawah."
          status={<Rekomendasi nilai={result.analysis?.recommendation} />}>
          {result.ai_suggestion && (
            <AISuggestionPanel
              suggestion={result.ai_suggestion}
              fields={SCORE_SUGGESTION_FIELDS}
              decideUrl={`${process.env.REACT_APP_BACKEND_URL}/api/hr/ai/resume-screen/${selectedCandidate}/suggestion`}
              headers={{ Authorization: headers.Authorization }}
              testId="candidate-ai-suggestion"
              onDecided={(data) => {
                setResult(prev => ({ ...prev, ai_suggestion: data?.data?.ai_suggestion || prev.ai_suggestion }));
                toast.success('Keputusan skor AI tersimpan');
              }}
            />
          )}
          <IsiAnalisis analysis={result.analysis} />
        </DetailPopup>
      )}

      {/* ─── Rincian riwayat (popup) ─── */}
      {lihat && (
        <DetailPopup open onClose={() => setLihat(null)} testId="resume-history-detail"
          judul={lihat.candidate_name || 'Riwayat screening'}
          keterangan={[lihat.position, formatDateID(lihat.generated_at)].filter(Boolean).join(' · ')}
          status={<Rekomendasi nilai={lihat.analysis?.recommendation} />}>
          <IsiAnalisis analysis={lihat.analysis} />
        </DetailPopup>
      )}
    </PageLayout>
  );
}

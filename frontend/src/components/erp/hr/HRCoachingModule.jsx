/**
 * Coaching AI (Portal SDM › AI SDM) — rencana coaching personal berbasis AI untuk pengembangan karyawan.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, form = FormPopup (dulu panel besar di halaman), rencana =
 * DetailPopup, riwayat = tabel + unduh Excel/CSV (dulu kartu, diam-diam 10 dari 20 terakhir — kini sampai 200),
 * tanpa gradien/emoji, warna token, bahasa Indonesia (SMART goals → sasaran SMART, milestone → tonggak).
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
import DetailPopup from '@/components/ui/detail-popup';
import { formatDateID } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatusBadge } from '../moduleAtoms';

const FOCUS_OPTIONS = [
  { value: 'performance', label: 'Peningkatan kinerja' },
  { value: 'leadership', label: 'Kepemimpinan' },
  { value: 'technical', label: 'Keahlian teknis' },
  { value: 'communication', label: 'Komunikasi' },
  { value: 'time_management', label: 'Manajemen waktu' },
  { value: 'overall', label: 'Keseluruhan' },
];
const labelFokus = (v) => FOCUS_OPTIONS.find(o => o.value === v)?.label || v || '—';

function Bagian({ judul, children }) {
  return <div><p className="mb-1 text-sm font-medium text-foreground">{judul}</p>{children}</div>;
}

/** Isi satu rencana coaching (dipakai untuk hasil baru dan riwayat). */
function IsiRencana({ plan = {}, employee }) {
  return (
    <>
      {employee && <p className="text-sm text-muted-foreground">{[employee.name, employee.job_title, employee.department].filter(Boolean).join(' · ')}</p>}
      {plan.employee_summary && <Bagian judul="Ringkasan situasi"><p className="text-sm leading-relaxed text-muted-foreground">{plan.employee_summary}</p></Bagian>}
      {plan.key_development_areas?.length > 0 && (
        <Bagian judul="Area pengembangan utama">
          <div className="flex flex-wrap gap-1.5">{plan.key_development_areas.map((a, i) => <StatusBadge key={i} status="area" label={a} tone="default" />)}</div>
        </Bagian>
      )}
      {plan.smart_goals?.length > 0 && (
        <Bagian judul="Sasaran SMART">
          <TabelData baris={plan.smart_goals} kunci={(g) => g.goal} testId="coaching-goals"
            kolom={[
              { kunci: 'goal', label: 'Sasaran', hp: 'judul', isi: (g) => <span className="text-sm">{g.goal}</span> },
              { kunci: 'waktu', label: 'Waktu', isi: (g) => <span className="text-sm">{g.timeline || '—'}</span> },
              { kunci: 'ukur', label: 'Cara mengukur', isi: (g) => <span className="text-sm">{g.measurement || '—'}</span> },
            ]} />
        </Bagian>
      )}
      {plan.weekly_actions?.length > 0 && (
        <Bagian judul="Langkah mingguan">
          <ol className="list-decimal space-y-1 pl-5 text-sm text-muted-foreground">{plan.weekly_actions.map((w, i) => <li key={i}>{w}</li>)}</ol>
        </Bagian>
      )}
      {plan.recommended_trainings?.length > 0 && (
        <Bagian judul="Pelatihan yang disarankan">
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">{plan.recommended_trainings.map((t, i) => <li key={i}>{t}</li>)}</ul>
        </Bagian>
      )}
      {plan.manager_support && <Bagian judul="Dukungan atasan"><p className="text-sm text-muted-foreground">{plan.manager_support}</p></Bagian>}
      {plan.milestones?.length > 0 && (
        <Bagian judul="Tonggak">
          <ul className="space-y-1 text-sm text-muted-foreground">{plan.milestones.map((m, i) => <li key={i}><span className="font-medium text-foreground">Bulan {m.month}:</span> {m.target}</li>)}</ul>
        </Bagian>
      )}
      {plan.motivational_message && <p className="text-sm italic text-muted-foreground">"{plan.motivational_message}"</p>}
    </>
  );
}

export default function HRCoachingModule({ token }) {
  const [employees, setEmployees] = useState([]);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [bukaForm, setBukaForm] = useState(false);
  const [selectedEmployee, setSelectedEmployee] = useState(null);
  const [result, setResult] = useState(null);
  const [lihat, setLihat] = useState(null);
  const [formData, setFormData] = useState({ focus: 'overall', goals: '' });

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);

  const fetchEmployees = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/hr/ai/employees/list`, { headers });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setEmployees(data?.data || []);
    } catch (e) {
      toast.error(`Gagal memuat karyawan: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [headers]);

  const fetchHistory = useCallback(async () => {
    try {
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/hr/ai/coaching/history?limit=200`, { headers });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setHistory(data?.data || []);
    } catch (e) {
      console.error('History fetch failed:', e);
    }
  }, [headers]);

  useEffect(() => {
    fetchEmployees();
    fetchHistory();
  }, [fetchEmployees, fetchHistory]);

  const handleGenerate = async () => {
    if (!selectedEmployee) {
      toast.error('Pilih karyawan terlebih dahulu');
      return;
    }
    setGenerating(true);
    setResult(null);
    try {
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/hr/ai/coaching/${selectedEmployee}`, {
        method: 'POST',
        headers,
        body: JSON.stringify(formData),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setResult(data?.data);
      setBukaForm(false);
      toast.success('Rencana coaching berhasil dibuat!', { icon: <Sparkles className="h-4 w-4" /> });
      fetchHistory();
    } catch (e) {
      toast.error(`Gagal membuat rencana coaching: ${e.message}`);
    } finally {
      setGenerating(false);
    }
  };

  const kolom = [
    { kunci: 'nama', label: 'Karyawan', hp: 'judul', isi: (h) => <span className="font-medium text-foreground">{h.employee_name || '—'}</span> },
    { kunci: 'judul', label: 'Rencana', isi: (h) => <span className="text-sm">{h.plan?.coaching_title || '—'}</span> },
    { kunci: 'fokus', label: 'Fokus', isi: (h) => <span className="text-sm">{labelFokus(h.focus)}</span> },
    { kunci: 'tgl', label: 'Dibuat', isi: (h) => <span className="text-sm md:whitespace-nowrap">{formatDateID(h.generated_at)}</span> },
  ];

  return (
    <PageLayout testId="hr-coaching-module" title="Coaching AI"
      subtitle="Rencana coaching personal berbasis AI untuk pengembangan karyawan."
      actions={<Button onClick={() => setBukaForm(true)} data-testid="coaching-new"><Sparkles />Buat rencana coaching</Button>}
      tools={<>
        <TombolUnduh namaBerkas="riwayat-coaching" namaLembar="Riwayat" baris={history} testId="coaching-unduh"
          kolom={[
            { label: 'Karyawan', nilai: (h) => h.employee_name || '' }, { label: 'Rencana', nilai: (h) => h.plan?.coaching_title || '' },
            { label: 'Fokus', nilai: (h) => labelFokus(h.focus) }, { label: 'Dibuat', nilai: (h) => formatDateID(h.generated_at) },
            { label: 'Sasaran', nilai: (h) => (h.plan?.smart_goals || []).map(g => g.goal).join('; ') },
          ]} />
        <Button variant="outline" size="icon" onClick={() => { fetchEmployees(); fetchHistory(); }} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}>
      <TabelData kolom={kolom} baris={history} kunci={(h) => h.id || `${h.employee_id}-${h.generated_at}`} onKlikBaris={setLihat} testId="coaching-history"
        kosong={<EmptyState title="Belum ada rencana coaching" description='Klik "Buat rencana coaching", pilih karyawan dan fokusnya.'
          action={<Button onClick={() => setBukaForm(true)}><Sparkles />Buat rencana coaching</Button>} />} />

      <FormPopup open={bukaForm} onClose={() => setBukaForm(false)} ukuran="pendek" onSimpan={handleGenerate} menyimpan={generating}
        bisaSimpan={!!selectedEmployee} labelSimpan="Buat rencana" judul="Rencana coaching baru" testId="coaching-form"
        keterangan="AI menyusun sasaran, langkah mingguan, dan pelatihan berdasarkan data karyawan.">
        <Isian label="Karyawan" wajib>
          <SmartNativeSelect value={selectedEmployee || ''} onChange={(e) => setSelectedEmployee(e.target.value || null)} searchable>
            <option value="">Pilih karyawan…</option>
            {employees.map(e => (
              <option key={e.id || e.employee_code} value={e.id || e.employee_code}>{e.name} - {e.department || 'tanpa departemen'} ({e.job_title || 'tanpa jabatan'})</option>
            ))}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Fokus coaching">
          <SmartNativeSelect searchable={false} value={formData.focus} onChange={(e) => setFormData({ ...formData, focus: e.target.value })}>
            {FOCUS_OPTIONS.map(opt => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Tujuan khusus (opsional)" htmlFor="coaching-tujuan">
          <Textarea id="coaching-tujuan" rows={3} value={formData.goals} onChange={(e) => setFormData({ ...formData, goals: e.target.value })}
            placeholder="Misal: naikkan produktivitas 20% dalam 3 bulan, kurangi kesalahan QC" />
        </Isian>
      </FormPopup>

      {result && (
        <DetailPopup open onClose={() => setResult(null)} judul={result.plan?.coaching_title || 'Rencana coaching'} testId="coaching-result">
          <IsiRencana plan={result.plan} employee={result.employee} />
        </DetailPopup>
      )}
      {lihat && (
        <DetailPopup open onClose={() => setLihat(null)} judul={lihat.plan?.coaching_title || 'Rencana coaching'} testId="coaching-history-detail"
          keterangan={`${lihat.employee_name || ''} · fokus ${labelFokus(lihat.focus).toLowerCase()} · ${formatDateID(lihat.generated_at)}`}>
          <IsiRencana plan={lihat.plan} />
        </DetailPopup>
      )}
    </PageLayout>
  );
}

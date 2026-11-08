/**
 * HRATSModule — Rekrutmen & ATS (Actionable Pipeline)
 * Fitur:
 *  - Pindah tahap dengan isian per tahap (jadwal wawancara, penawaran, catatan screening, alasan tolak)
 *  - Unggah CV (berkas atau tautan)
 *  - Jadwal + nilai wawancara
 *  - Penawaran kerja
 *  - Onboarding otomatis saat diterima
 *  - Detail kandidat lengkap
 *
 * Standar UI/UX v2 (8 Nov 2026): tab halaman (HubTabs) + cetakan PageLayout, lowongan/kandidat/talent pool/
 * analitik = tabel + unduh Excel/CSV (dulu kartu berulang & grafik berwarna hex), papan pipeline ringkas
 * (kolom berisi daftar, bukan kartu bertumpuk), detail kandidat = DetailPopup (bagian bertumpuk, tanpa tab di
 * dalam popup), semua form = FormPopup, tanggal = DatePicker (+ jam), nama tahap berbahasa Indonesia di layar
 * (nilai yang dikirim ke server tetap sama), warna token.
 * Perbaikan angka: "Diterima" per lowongan dulu penghitung tersimpan (data contoh mengisinya angka karangan) —
 * kini dihitung dari kandidat bertahap "Hired". Daftar lowongan/kandidat dulu diam-diam 50/100 pertama.
 */
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  Bookmark, BookmarkCheck, ChevronDown, ChevronRight, FileText, Link2, Pencil, Plus, RefreshCw, Search, Send,
  Star, Upload, UserMinus, X,
} from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import DatePicker from '@/components/ui/date-picker';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { MoneyInput } from '@/components/ui/money-input';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { cn } from '@/lib/utils';
import { formatDateID, formatDateTimeID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import HubTabs from './hubs/HubTabs';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';
import { useHrMasters, departmentOptions } from './hr/hrPickers';
import { confirmDialog } from '@/components/ui/confirm-dialog';

const BASE = process.env.REACT_APP_BACKEND_URL;
const api = (path, opts = {}) =>
  fetch(`${BASE}/api/dewi/recruitment${path}`, { cache: 'no-store', ...opts });

const fmtDate = (d) => (d ? formatDateID(d) : '—');
const fmtCurrency = n =>
  n ? new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', minimumFractionDigits: 0 }).format(n) : 'Negosiasi';

const STAGES = ['Lamaran Masuk','Screening CV','Interview HR','Interview User','Offering','Hired','Rejected'];
// Nilai tahap di server tetap; layar memakai label Indonesia.
const STAGE_CFG = {
  'Lamaran Masuk':  { label: 'Lamaran masuk',    tone: 'default' },
  'Screening CV':   { label: 'Screening CV',     tone: 'info' },
  'Interview HR':   { label: 'Wawancara SDM',    tone: 'primary' },
  'Interview User': { label: 'Wawancara atasan', tone: 'primary' },
  'Offering':       { label: 'Penawaran',        tone: 'warning' },
  'Hired':          { label: 'Diterima',         tone: 'success' },
  'Rejected':       { label: 'Ditolak',          tone: 'danger' },
};
const labelTahap = (s) => STAGE_CFG[s]?.label || s || '—';
const JOB_STATUS = {
  open:    { label: 'Buka',    tone: 'success' },
  closed:  { label: 'Ditutup', tone: 'muted' },
  draft:   { label: 'Draf',    tone: 'muted' },
  on_hold: { label: 'Ditunda', tone: 'warning' },
};
const JOB_TYPE = { 'Full-time': 'Penuh waktu', 'Part-time': 'Paruh waktu', Contract: 'Kontrak', Magang: 'Magang' };
const JOB_LEVEL = { Staff: 'Staf', Senior: 'Senior', Supervisor: 'Supervisor', Manager: 'Manajer' };
const MODE_LABEL = { 'Tatap Muka': 'Tatap muka', 'Video Call': 'Panggilan video', Phone: 'Telepon' };
const SUMBER_LABEL = { 'Walk-in': 'Datang langsung', Referral: 'Rekomendasi', Website: 'Situs web' };
const labelSumber = (s) => SUMBER_LABEL[s] || s || '—';
const IV_STATUS = { scheduled: { label: 'Terjadwal', tone: 'info' }, done: { label: 'Selesai', tone: 'success' },
  cancelled: { label: 'Dibatalkan', tone: 'danger' }, no_show: { label: 'Tidak hadir', tone: 'warning' } };
const IV_RESULT = { pass: { label: 'Lulus', tone: 'success' }, fail: { label: 'Tidak lulus', tone: 'danger' }, hold: { label: 'Ditunda', tone: 'warning' } };

function StageBadge({ stage }) {
  const c = STAGE_CFG[stage] || { label: stage || '—', tone: 'default' };
  return <StatusBadge status="tahap" label={c.label} tone={c.tone} />;
}
function RatingStars({ rating = 0, onRate }) {
  return (
    <div className="flex gap-0.5" aria-label={`Nilai ${rating || 0} dari 5`}>
      {[1,2,3,4,5].map(s => (
        <Star key={s} className={cn('h-3.5 w-3.5', onRate && 'cursor-pointer')} onClick={() => onRate && onRate(s)}
          fill={s <= rating ? 'hsl(var(--warning))' : 'none'} stroke={s <= rating ? 'hsl(var(--warning))' : 'hsl(var(--muted-foreground))'} />
      ))}
    </div>
  );
}
const gabungTanggalJam = (tgl, jam) => (tgl ? `${tgl}T${jam || '09:00'}` : '');

// ────────────────────────────────────────────────────────────────────────────
// PINDAH TAHAP (form popup)
// ────────────────────────────────────────────────────────────────────────────
function StageActionModal({ candidate, targetStage, headers, onSuccess, onClose }) {
  const [form, setForm] = useState({
    notes: '',
    scheduled_at: '',
    interviewer: '',
    mode: 'Tatap Muka',
    type: targetStage,
    salary: '',
    allowances: '',
    start_date: '',
    contract_type: 'PKWTT',
    position: candidate?.job_title || '',
    rejection_reason: 'Tidak memenuhi kualifikasi',
  });
  const [tglWawancara, setTglWawancara] = useState('');
  const [jamWawancara, setJamWawancara] = useState('09:00');
  const [saving, setSaving] = useState(false);

  // Nilai tanggal-jam tetap "YYYY-MM-DDTHH:mm" seperti input datetime-local dulu.
  useEffect(() => {
    setForm(p => ({ ...p, scheduled_at: gabungTanggalJam(tglWawancara, jamWawancara) }));
  }, [tglWawancara, jamWawancara]);

  const handleSubmit = async () => {
    setSaving(true);
    try {
      // Add stage-specific data before moving
      if (targetStage === 'Interview HR' || targetStage === 'Interview User') {
        if (form.scheduled_at) {
          await api(`/candidates/${candidate.candidate_id}/interviews`, {
            method: 'POST', headers,
            body: JSON.stringify({
              type: targetStage,
              scheduled_at: form.scheduled_at,
              interviewer: form.interviewer,
              mode: form.mode,
              notes: form.notes,
            }),
          });
        }
      }
      if (targetStage === 'Offering') {
        await api(`/candidates/${candidate.candidate_id}`, {
          method: 'PUT', headers,
          body: JSON.stringify({
            offer: {
              salary: parseFloat(form.salary) || 0,
              allowances: form.allowances,
              start_date: form.start_date,
              contract_type: form.contract_type,
              position: form.position,
              offered_at: new Date().toISOString(),
            },
          }),
        });
      }
      // Advance the stage
      const r = await api(`/candidates/${candidate.candidate_id}`, {
        method: 'PUT', headers,
        body: JSON.stringify({ stage: targetStage, stage_note: form.notes || form.rejection_reason || '' }),
      });
      const d = await r.json().catch(() => ({}));
      if (d.ok) {
        toast.success(targetStage === 'Hired'
          ? 'Kandidat diterima! Onboarding otomatis dibuat.'
          : `Kandidat dipindahkan ke "${labelTahap(targetStage)}"`);
        onSuccess();
      } else {
        // 2026-11-06 (pola P6): dulu penolakan server diam saja (popup tetap terbuka tanpa pesan)
        toast.error(typeof d.detail === 'string' ? d.detail : 'Gagal memperbarui');
      }
    } catch (e) {
      toast.error('Gagal memperbarui');
    } finally { setSaving(false); }
  };

  const isInterview = targetStage === 'Interview HR' || targetStage === 'Interview User';
  const isOffer = targetStage === 'Offering';
  const isHired = targetStage === 'Hired';
  const isReject = targetStage === 'Rejected';

  return (
    <FormPopup open onClose={onClose} ukuran="pendek" onSimpan={handleSubmit} menyimpan={saving} testId="ats-stage-form"
      judul={`Pindahkan ke "${labelTahap(targetStage)}"`}
      keterangan={`${candidate?.name || 'Kandidat'}: ${labelTahap(candidate?.stage)} → ${labelTahap(targetStage)}`}
      labelSimpan={isHired ? 'Terima kandidat' : isReject ? 'Simpan penolakan' : 'Pindahkan'}>
      {targetStage === 'Screening CV' && (
        <Isian label="Catatan screening" htmlFor="ats-catatan-screening">
          <Textarea id="ats-catatan-screening" rows={4} value={form.notes} onChange={e => setForm(p => ({ ...p, notes: e.target.value }))}
            placeholder="Kualifikasi yang terpenuhi, poin penting dari CV" />
        </Isian>
      )}

      {isInterview && (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <Isian label="Tanggal wawancara" wajib petunjuk="Kosong = tahap dipindah tanpa jadwal.">
              <DatePicker value={tglWawancara} onChange={setTglWawancara} testId="ats-iv-tanggal" />
            </Isian>
            <Isian label="Jam" htmlFor="ats-iv-jam">
              <Input id="ats-iv-jam" type="time" value={jamWawancara} onChange={e => setJamWawancara(e.target.value)} />
            </Isian>
            <Isian label="Cara wawancara">
              <SmartNativeSelect searchable={false} value={form.mode} onChange={e => setForm(p => ({ ...p, mode: e.target.value }))}>
                <option value="Tatap Muka">Tatap muka</option><option value="Video Call">Panggilan video</option><option value="Phone">Telepon</option>
              </SmartNativeSelect>
            </Isian>
            <Isian label="Pewawancara" htmlFor="ats-iv-pewawancara">
              <Input id="ats-iv-pewawancara" value={form.interviewer} onChange={e => setForm(p => ({ ...p, interviewer: e.target.value }))} placeholder="Nama pewawancara" />
            </Isian>
          </div>
          <Isian label="Catatan tambahan" htmlFor="ats-iv-catatan">
            <Textarea id="ats-iv-catatan" rows={2} value={form.notes} onChange={e => setForm(p => ({ ...p, notes: e.target.value }))}
              placeholder="Topik yang akan dibahas, persiapan khusus" />
          </Isian>
        </>
      )}

      {isOffer && (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <Isian label="Gaji ditawarkan (Rp)">
              <MoneyInput value={form.salary} onChange={e => setForm(p => ({ ...p, salary: e.target.value }))} placeholder="3.000.000" />
            </Isian>
            <Isian label="Jenis kontrak">
              <SmartNativeSelect searchable={false} value={form.contract_type} onChange={e => setForm(p => ({ ...p, contract_type: e.target.value }))}>
                <option value="PKWTT">PKWTT (tetap)</option>
                <option value="PKWT">PKWT (kontrak)</option>
                <option value="Magang">Magang</option>
              </SmartNativeSelect>
            </Isian>
            <Isian label="Mulai bekerja">
              <DatePicker value={form.start_date} onChange={v => setForm(p => ({ ...p, start_date: v }))} testId="ats-offer-mulai" />
            </Isian>
            <Isian label="Posisi" htmlFor="ats-offer-posisi">
              <Input id="ats-offer-posisi" value={form.position} onChange={e => setForm(p => ({ ...p, position: e.target.value }))} />
            </Isian>
          </div>
          <Isian label="Tunjangan / fasilitas" htmlFor="ats-offer-tunjangan">
            <Input id="ats-offer-tunjangan" value={form.allowances} onChange={e => setForm(p => ({ ...p, allowances: e.target.value }))}
              placeholder="BPJS, transport, makan, dll." />
          </Isian>
        </>
      )}

      {isHired && (
        <>
          <Notice tone="success" title="Konfirmasi penerimaan">
            {candidate?.name} ditandai diterima. Sistem otomatis membuat data karyawan baru dan checklist onboarding.
          </Notice>
          <Isian label="Catatan penerimaan (opsional)" htmlFor="ats-catatan-terima">
            <Textarea id="ats-catatan-terima" rows={2} value={form.notes} onChange={e => setForm(p => ({ ...p, notes: e.target.value }))} />
          </Isian>
        </>
      )}

      {isReject && (
        <>
          <Isian label="Alasan penolakan">
            <SmartNativeSelect searchable={false} value={form.rejection_reason} onChange={e => setForm(p => ({ ...p, rejection_reason: e.target.value }))}>
              <option value="Tidak memenuhi kualifikasi">Tidak memenuhi kualifikasi</option>
              <option value="Gaji tidak sesuai">Gaji tidak sesuai</option>
              <option value="Posisi sudah diisi">Posisi sudah diisi</option>
              <option value="Hasil interview kurang">Hasil wawancara kurang</option>
              <option value="Mengundurkan diri">Mengundurkan diri</option>
            </SmartNativeSelect>
          </Isian>
          <Isian label="Catatan tambahan (opsional)" htmlFor="ats-catatan-tolak">
            <Textarea id="ats-catatan-tolak" rows={2} value={form.notes} onChange={e => setForm(p => ({ ...p, notes: e.target.value }))} />
          </Isian>
        </>
      )}

      {candidate?.email && (
        <p className="text-xs text-muted-foreground">
          Email pemberitahuan dicatat untuk {candidate.email} — integrasi email belum aktif, jadi email belum benar-benar terkirim.
        </p>
      )}
    </FormPopup>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// HASIL WAWANCARA (form popup)
// ────────────────────────────────────────────────────────────────────────────
function InterviewResultModal({ interview, candidateId, headers, onSuccess, onClose }) {
  const [form, setForm] = useState({
    status: interview?.status || 'done',
    result: interview?.result || '',
    score: interview?.score || '',
    notes: interview?.notes || '',
  });
  const [saving, setSaving] = useState(false);

  const handleSubmit = async () => {
    setSaving(true);
    try {
      const r = await api(`/candidates/${candidateId}/interviews/${interview.interview_id}`, {
        method: 'PUT', headers,
        body: JSON.stringify({
          status: form.status,
          result: form.result,
          score: form.score ? parseInt(form.score, 10) : null,
          notes: form.notes,
        }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);  // 2026-11-06 (pola P6): sukses hanya bila server menerima
      toast.success('Hasil wawancara disimpan');
      onSuccess();
    } catch { toast.error('Gagal menyimpan'); }
    finally { setSaving(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="pendek" onSimpan={handleSubmit} menyimpan={saving} testId="ats-iv-result-form"
      judul="Hasil wawancara" keterangan={`${labelTahap(interview?.type)} · ${formatDateTimeID(interview?.scheduled_at)}`}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Hasil">
          <SmartNativeSelect searchable={false} value={form.result} onChange={e => setForm(p => ({ ...p, result: e.target.value }))}>
            <option value="">Pilih hasil</option>
            <option value="pass">Lulus</option>
            <option value="fail">Tidak lulus</option>
            <option value="hold">Ditunda</option>
          </SmartNativeSelect>
        </Isian>
        <Isian label="Skor (1–100)" htmlFor="ats-iv-skor">
          <Input id="ats-iv-skor" type="number" min="0" max="100" value={form.score} onChange={e => setForm(p => ({ ...p, score: e.target.value }))} placeholder="75" />
        </Isian>
      </div>
      <Isian label="Catatan pewawancara" htmlFor="ats-iv-hasil-catatan">
        <Textarea id="ats-iv-hasil-catatan" rows={3} value={form.notes} onChange={e => setForm(p => ({ ...p, notes: e.target.value }))} />
      </Isian>
    </FormPopup>
  );
}

function Bagian({ judul, children, alat }) {
  return (
    <section className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold text-foreground">{judul}</p>
        {alat}
      </div>
      {children}
    </section>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// DETAIL KANDIDAT (popup)
// ────────────────────────────────────────────────────────────────────────────
function CandidateDetailModal({ candidate: initCandidate, headers, jobs, onStageAction, onRefresh, onClose }) {
  const [candidate, setCandidate] = useState(initCandidate);
  const [stageAction, setStageAction] = useState(null);
  const [interviewResult, setInterviewResult] = useState(null);
  const [noteText, setNoteText] = useState('');
  const [savingNote, setSavingNote] = useState(false);
  const [cvInput, setCvInput] = useState({ url: candidate?.cv_url || '', mode: 'url' });
  const [uploadingCV, setUploadingCV] = useState(false);
  const [emailBuka, setEmailBuka] = useState(null);
  const fileRef = useRef(null);

  const refreshCandidate = async () => {
    try {
      const r = await api(`/candidates/${candidate.candidate_id}`, { headers, cache: 'no-store' });
      const d = await r.json();
      if (d.ok) { setCandidate(d.candidate); onRefresh(); }
    } catch (_e) { /* ignore */ }
  };

  const handleAddNote = async () => {
    if (!noteText.trim()) return;
    setSavingNote(true);
    try {
      await api(`/candidates/${candidate.candidate_id}/notes`, {
        method: 'POST', headers,
        body: JSON.stringify({ text: noteText }),
      });
      setNoteText('');
      refreshCandidate();
    } catch { toast.error('Gagal tambah catatan'); }
    finally { setSavingNote(false); }
  };

  const handleCVSave = async () => {
    setUploadingCV(true);
    try {
      if (cvInput.mode === 'url') {
        const r = await api(`/candidates/${candidate.candidate_id}/upload-cv`, {
          method: 'POST', headers,
          body: JSON.stringify({ cv_url: cvInput.url }),
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);  // 2026-11-06 (pola P6): sukses hanya bila server menerima
      }
      toast.success('CV disimpan');
      refreshCandidate();
    } catch { toast.error('Gagal menyimpan CV'); }
    finally { setUploadingCV(false); }
  };

  const handleFileUpload = async (file) => {
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) { toast.error('Berkas terlalu besar. Maks 5 MB'); return; }
    setUploadingCV(true);
    try {
      const reader = new FileReader();
      reader.onload = async (e) => {
        const base64 = e.target.result.split(',')[1];
        const r = await api(`/candidates/${candidate.candidate_id}/upload-cv`, {
          method: 'POST', headers,
          body: JSON.stringify({ cv_data: base64, cv_filename: file.name, cv_size: file.size }),
        });
        setUploadingCV(false);
        // 2026-11-06 (pola P6): onload berjalan di luar try → cek jawaban di sini
        if (!r.ok) { toast.error('Gagal mengunggah CV'); return; }
        toast.success('CV berhasil diunggah');
        refreshCandidate();
      };
      reader.readAsDataURL(file);
    } catch { toast.error('Gagal mengunggah CV'); setUploadingCV(false); }
  };

  const handleRating = async (rating) => {
    await api(`/candidates/${candidate.candidate_id}`, {
      method: 'PUT', headers,
      body: JSON.stringify({ rating }),
    });
    setCandidate(p => ({...p, rating}));
    onRefresh();
  };

  const alihTalentPool = async () => {
    const r = await api(`/talent-pool/${candidate.candidate_id}/toggle`, { method: 'POST', headers });
    if (!r.ok) { toast.error('Gagal mengubah talent pool'); return; }  // 2026-11-06 (pola P6): dulu selalu "berhasil"
    setCandidate(p => ({...p, is_talent_pool: !p.is_talent_pool}));
    onRefresh();
    toast.success(candidate.is_talent_pool ? 'Dikeluarkan dari talent pool' : 'Ditambahkan ke talent pool');
  };

  // Pilihan tahap sama seperti dulu: tiga tahap pertama selain tahap sekarang & Ditolak.
  const pilihanTahap = STAGES.filter(s => s !== candidate.stage && s !== 'Rejected').slice(0, 3);
  const interviews = candidate.interviews || [];
  const catatan = [...(candidate.activity_notes || [])].reverse();
  const emails = [...(candidate.email_logs || [])].reverse();

  return (
    <DetailPopup open onClose={onClose} testId="ats-candidate-detail" judul={candidate.name}
      keterangan={candidate.job_title}
      status={<><StageBadge stage={candidate.stage} /><RatingStars rating={candidate.rating} onRate={handleRating} /></>}
      aksi={<>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="sm" variant="outline" data-testid="ats-move-stage">Pindahkan ke<ChevronDown /></Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {pilihanTahap.map(s => (
              <DropdownMenuItem key={s} onSelect={() => setStageAction(s)}>{labelTahap(s)}</DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
        {candidate.stage !== 'Rejected' && (
          <Button size="sm" variant="destructive" onClick={() => setStageAction('Rejected')} data-testid="ats-reject-btn"><X />Tolak</Button>
        )}
        <Button size="sm" variant="outline" onClick={alihTalentPool} data-testid="toggle-talent-pool-btn">
          {candidate.is_talent_pool ? <><BookmarkCheck />Dalam talent pool</> : <><Bookmark />Masukkan talent pool</>}
        </Button>
      </>}>
      <Bagian judul="Data pelamar">
        <dl className="divide-y divide-[var(--glass-border)]">
          <BarisDetail label="Email">{candidate.email || '—'}</BarisDetail>
          <BarisDetail label="No. HP">{candidate.phone || '—'}</BarisDetail>
          <BarisDetail label="Pendidikan">{candidate.education || '—'}</BarisDetail>
          <BarisDetail label="Pengalaman">{candidate.experience_years ?? 0} tahun</BarisDetail>
          <BarisDetail label="Sumber">{labelSumber(candidate.source)}</BarisDetail>
          <BarisDetail label="Melamar">{fmtDate(candidate.applied_at)}</BarisDetail>
          {candidate.address && <BarisDetail label="Alamat">{candidate.address}</BarisDetail>}
          {candidate.skills?.length > 0 && <BarisDetail label="Keahlian">{candidate.skills.join(', ')}</BarisDetail>}
          {candidate.portfolio_url && (
            <BarisDetail label="Portofolio">
              <a href={candidate.portfolio_url} target="_blank" rel="noreferrer" className="break-all text-primary hover:underline">{candidate.portfolio_url}</a>
            </BarisDetail>
          )}
        </dl>
      </Bagian>

      {candidate.timeline?.length > 0 && (
        <Bagian judul="Riwayat tahap">
          <TabelData baris={[...candidate.timeline].reverse()} kunci={(t) => `${t.stage}-${t.date}`} testId="ats-timeline"
            kolom={[
              { kunci: 'tahap', label: 'Tahap', hp: 'judul', isi: (t) => <StageBadge stage={t.stage} /> },
              { kunci: 'tgl', label: 'Tanggal', isi: (t) => fmtDate(t.date) },
              { kunci: 'oleh', label: 'Oleh', isi: (t) => t.by || '—' },
              { kunci: 'catatan', label: 'Catatan', hp: 'keterangan', isi: (t) => <span className="text-sm text-muted-foreground">{t.note || '—'}</span> },
            ]} />
        </Bagian>
      )}

      <Bagian judul="CV & dokumen">
        {(candidate.cv_url || candidate.cv_filename) ? (
          <div className="space-y-1 text-sm">
            {candidate.cv_filename && (
              <p className="flex flex-wrap items-center gap-2">
                <FileText className="h-4 w-4 text-primary" />{candidate.cv_filename}
                {candidate.cv_data && (
                  <a href={`data:application/pdf;base64,${candidate.cv_data}`} download={candidate.cv_filename} className="text-primary hover:underline">Unduh</a>
                )}
              </p>
            )}
            {candidate.cv_url && (
              <p className="flex items-center gap-2"><Link2 className="h-4 w-4 text-primary" />
                <a href={candidate.cv_url} target="_blank" rel="noreferrer" className="truncate text-primary hover:underline">{candidate.cv_url}</a>
              </p>
            )}
          </div>
        ) : <p className="text-sm text-muted-foreground">CV belum diunggah.</p>}
        <div className="flex flex-wrap items-center gap-2">
          <SmartNativeSelect searchable={false} value={cvInput.mode} onChange={e => setCvInput(p => ({ ...p, mode: e.target.value }))} className="w-40"
            aria-label="Cara menyimpan CV">
            <option value="url">Tautan</option>
            <option value="file">Unggah berkas</option>
          </SmartNativeSelect>
          {cvInput.mode === 'url' ? (
            <>
              <Input value={cvInput.url} onChange={e => setCvInput(p => ({ ...p, url: e.target.value }))} placeholder="https://drive.google.com/…" className="w-full sm:w-80" />
              <Button size="sm" variant="success" onClick={handleCVSave} disabled={uploadingCV || !cvInput.url}>{uploadingCV ? 'Menyimpan…' : 'Simpan'}</Button>
            </>
          ) : (
            <>
              <input type="file" ref={fileRef} className="hidden" accept=".pdf,.doc,.docx" onChange={e => handleFileUpload(e.target.files?.[0])} />
              <Button size="sm" variant="outline" onClick={() => fileRef.current?.click()} disabled={uploadingCV}>
                <Upload />{uploadingCV ? 'Mengunggah…' : 'Pilih berkas (PDF, maks 5 MB)'}
              </Button>
            </>
          )}
        </div>
      </Bagian>

      <Bagian judul={`Wawancara (${interviews.length})`}>
        <TabelData baris={interviews} kunci={(iv) => iv.interview_id} testId="ats-interviews"
          kolom={[
            { kunci: 'jenis', label: 'Wawancara', hp: 'judul', isi: (iv) => (
              <div><p className="font-medium text-foreground">{labelTahap(iv.type)}</p>
                <p className="text-xs text-muted-foreground">{MODE_LABEL[iv.mode] || iv.mode}{iv.interviewer ? ` · ${iv.interviewer}` : ''}</p></div>) },
            { kunci: 'jadwal', label: 'Jadwal', isi: (iv) => <span className="text-sm">{formatDateTimeID(iv.scheduled_at)}</span> },
            { kunci: 'status', label: 'Status', isi: (iv) => {
              const c = IV_STATUS[iv.status] || { label: iv.status || '—', tone: 'default' };
              return <StatusBadge status={iv.status} label={c.label} tone={c.tone} />;
            } },
            { kunci: 'hasil', label: 'Hasil', isi: (iv) => (iv.result
              ? <StatusBadge status={iv.result} label={IV_RESULT[iv.result]?.label || iv.result} tone={IV_RESULT[iv.result]?.tone} />
              : '—') },
            { kunci: 'skor', label: 'Skor', rata: 'kanan', isi: (iv) => <span className="tabular-nums">{iv.score != null ? iv.score : '—'}</span> },
            { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (iv) => (iv.status === 'scheduled'
              ? <Button size="sm" variant="outline" onClick={() => setInterviewResult(iv)}>Isi hasil</Button> : null) },
          ]}
          kosong={<p className="text-sm text-muted-foreground">Belum ada jadwal wawancara. Pindahkan kandidat ke "Wawancara SDM" untuk menjadwalkan.</p>} />
      </Bagian>

      <Bagian judul="Penawaran">
        {candidate.offer ? (
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Gaji">{fmtCurrency(candidate.offer.salary)}</BarisDetail>
            <BarisDetail label="Jenis kontrak">{candidate.offer.contract_type || '—'}</BarisDetail>
            <BarisDetail label="Mulai kerja">{fmtDate(candidate.offer.start_date)}</BarisDetail>
            <BarisDetail label="Posisi">{candidate.offer.position || candidate.job_title || '—'}</BarisDetail>
            {candidate.offer.allowances && <BarisDetail label="Tunjangan">{candidate.offer.allowances}</BarisDetail>}
            <BarisDetail label="Ditawarkan">{fmtDate(candidate.offer.offered_at)}</BarisDetail>
          </dl>
        ) : <p className="text-sm text-muted-foreground">Belum ada penawaran. Pindahkan kandidat ke tahap "Penawaran" untuk membuatnya.</p>}
        {candidate.onboarding_checklist_id && (
          <Notice tone="success" title="Onboarding sudah dibuat">Checklist onboarding karyawan ini tersedia di menu Onboarding.</Notice>
        )}
      </Bagian>

      <Bagian judul={`Catatan (${catatan.length})`}>
        {catatan.length > 0 && (
          <ul className="divide-y divide-[var(--glass-border)] rounded-lg border border-[var(--glass-border)]">
            {catatan.map(n => (
              <li key={n.note_id} className="px-3 py-2">
                <p className="text-sm text-foreground">{n.text}</p>
                <p className="text-xs text-muted-foreground">{n.by} · {fmtDate(n.created_at)}</p>
              </li>
            ))}
          </ul>
        )}
        <div className="flex gap-2">
          <Input value={noteText} onChange={e => setNoteText(e.target.value)} placeholder="Tambah catatan"
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleAddNote(); } }} />
          <Button size="icon" onClick={handleAddNote} disabled={savingNote || !noteText.trim()} aria-label="Kirim catatan" title="Kirim catatan">
            <Send />
          </Button>
        </div>
      </Bagian>

      <Bagian judul={`Email (${emails.length})`}>
        <p className="text-xs text-muted-foreground">Integrasi email belum aktif — email hanya tersimpan di catatan ini, belum benar-benar terkirim.</p>
        {emails.length > 0 && (
          <ul className="divide-y divide-[var(--glass-border)] rounded-lg border border-[var(--glass-border)]">
            {emails.map(log => (
              <li key={log.log_id} className="px-3 py-2">
                <div className="flex items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-foreground">{log.subject}</p>
                    <p className="text-xs text-muted-foreground">Ke {log.to} · {fmtDate(log.sent_at)} · oleh {log.sent_by} · {labelTahap(log.stage)}</p>
                  </div>
                  <Button variant="ghost" size="icon-sm" onClick={() => setEmailBuka(emailBuka === log.log_id ? null : log.log_id)}
                    aria-label={emailBuka === log.log_id ? 'Tutup isi email' : 'Lihat isi email'} title={emailBuka === log.log_id ? 'Tutup isi email' : 'Lihat isi email'}>
                    {emailBuka === log.log_id ? <ChevronDown /> : <ChevronRight />}
                  </Button>
                </div>
                {emailBuka === log.log_id && <p className="mt-2 whitespace-pre-wrap text-sm text-muted-foreground">{log.body}</p>}
              </li>
            ))}
          </ul>
        )}
      </Bagian>

      {stageAction && (
        <StageActionModal
          candidate={candidate}
          targetStage={stageAction}
          headers={headers}
          onSuccess={() => { setStageAction(null); refreshCandidate(); }}
          onClose={() => setStageAction(null)}
        />
      )}
      {interviewResult && (
        <InterviewResultModal
          interview={interviewResult}
          candidateId={candidate.candidate_id}
          headers={headers}
          onSuccess={() => { setInterviewResult(null); refreshCandidate(); }}
          onClose={() => setInterviewResult(null)}
        />
      )}
    </DetailPopup>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// PAPAN PIPELINE (kolom berisi daftar ringkas)
// ────────────────────────────────────────────────────────────────────────────
function PipelineView({ pipeline, onViewCandidate }) {
  const stages = STAGES.filter(s => s !== 'Rejected');
  return (
    <GlassCard hover={false} className="overflow-x-auto p-0">
      <div className="flex min-w-max divide-x divide-[var(--glass-border)]">
        {stages.map(stage => {
          const col = pipeline?.[stage] || { count: 0, candidates: [] };
          return (
            <section key={stage} className="w-56 shrink-0" data-testid={`pipeline-col-${stage}`}>
              <div className="flex items-center justify-between border-b border-[var(--glass-border)] px-3 py-2">
                <span className="text-sm font-medium text-foreground">{labelTahap(stage)}</span>
                <span className="text-sm tabular-nums text-muted-foreground">{col.count}</span>
              </div>
              {col.candidates.length === 0 ? (
                <p className="px-3 py-3 text-xs text-muted-foreground">Kosong</p>
              ) : (
                <ul className="max-h-[28rem] divide-y divide-[var(--glass-border)] overflow-y-auto">
                  {col.candidates.map(c => (
                    <li key={c.candidate_id} data-testid={`pipeline-card-${c.candidate_id}`}>
                      <Button variant="ghost" onClick={() => onViewCandidate(c)}
                        className="h-auto w-full flex-col items-start gap-0.5 whitespace-normal rounded-none px-3 py-2 text-left font-normal">
                        <span className="text-sm font-medium text-foreground">{c.name}</span>
                        <span className="text-xs text-muted-foreground">{c.job_title || '—'}</span>
                        <span className="text-xs text-muted-foreground">
                          {fmtDate(c.applied_at)}{(c.cv_url || c.cv_filename) ? ' · CV ada' : ''}{c.interviews?.length ? ` · ${c.interviews.length} wawancara` : ''}
                        </span>
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          );
        })}
      </div>
    </GlassCard>
  );
}

/** Isi satu tab: cetakan PageLayout di dalam hub. */
function IsiTab({ actions, filters, tools, summary, footer, children }) {
  return <PageLayout actions={actions} filters={filters} tools={tools} summary={summary} footer={footer}>{children}</PageLayout>;
}

// ────────────────────────────────────────────────────────────────────────────
// MAIN MODULE
// ────────────────────────────────────────────────────────────────────────────
export default function HRATSModule({ token }) {
  // Tahap 5 (2026-11-07): departemen lowongan dari master Struktur Organisasi (dulu diketik bebas)
  const { units: orgUnits } = useHrMasters(token, { positions: false, shifts: false });
  const [tab, setTab] = useState('pipeline');
  const [jobs, setJobs] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [pipeline, setPipeline] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [talentPool, setTalentPool] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedCandidate, setSelectedCandidate] = useState(null);
  const [showJobForm, setShowJobForm] = useState(false);
  const [showCandForm, setShowCandForm] = useState(false);
  const [editJob, setEditJob] = useState(null);
  const [seeding, setSeeding] = useState(false);
  const [filterJobId, setFilterJobId] = useState('');
  const [q, setQ] = useState('');
  const [talentSearch, setTalentSearch] = useState('');
  const [jobForm, setJobForm] = useState({ title: '', department: '', location: 'Bandung', type: 'Full-time', level: 'Staff', salary_min: 0, salary_max: 0, headcount: 1, description: '', status: 'open', deadline: '' });
  const [candForm, setCandForm] = useState({ name: '', email: '', phone: '', job_id: '', source: 'Walk-in', education: 'SMA/SMK', experience_years: 0, notes: '', cv_url: '', gender: '', address: '' });
  const [saving, setSaving] = useState(false);
  const [cvFile, setCvFile] = useState(null);
  const cvFileRef = useRef(null);

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);

  // ── Effects (async IIFE pattern)
  useEffect(() => {
    (async () => {
      setLoading(true); setError(null);
      try {
        const [jRes, pRes, aRes] = await Promise.all([
          api(`/jobs?limit=500`, { headers }),
          api(`/pipeline`, { headers }),
          api(`/analytics`, { headers }),
        ]);
        const [jd, pd, ad] = await Promise.all([jRes.json(), pRes.json(), aRes.json()]);
        setJobs(jd.jobs || []);
        setPipeline(pd.pipeline || null);
        setAnalytics(ad);
      } catch (e) { setError(e.message); }
      finally { setLoading(false); }
    })();
  }, [headers]);

  useEffect(() => {
    if (tab !== 'candidates') return;
    (async () => {
      try {
        const r = await api(`/candidates?limit=500${filterJobId ? `&job_id=${filterJobId}` : ''}`, { headers });
        const d = await r.json();
        setCandidates(d.candidates || []);
      } catch (_e) { /* ignore */ }
    })();
  }, [tab, filterJobId, headers]);

  useEffect(() => {
    if (tab !== 'talent_pool') return;
    (async () => {
      try {
        const r = await api(`/talent-pool${talentSearch ? `?search=${encodeURIComponent(talentSearch)}` : ''}`, { headers });
        const d = await r.json();
        setTalentPool(d.candidates || []);
      } catch (_e) { /* ignore */ }
    })();
  }, [tab, talentSearch, headers]);

  const refresh = useCallback(async () => {
    try {
      const [pRes, aRes, jRes] = await Promise.all([
        api(`/pipeline${filterJobId ? `?job_id=${filterJobId}` : ''}`, { headers }),
        api(`/analytics`, { headers }),
        api(`/jobs?limit=500`, { headers }),
      ]);
      const [pd, ad, jd] = await Promise.all([pRes.json(), aRes.json(), jRes.json()]);
      setPipeline(pd.pipeline || null);
      setAnalytics(ad);
      setJobs(jd.jobs || []);
      if (tab === 'candidates') {
        const r = await api(`/candidates?limit=500${filterJobId ? `&job_id=${filterJobId}` : ''}`, { headers });
        const d = await r.json();
        setCandidates(d.candidates || []);
      }
      if (tab === 'talent_pool') {
        const r = await api(`/talent-pool${talentSearch ? `?search=${encodeURIComponent(talentSearch)}` : ''}`, { headers });
        const d = await r.json();
        setTalentPool(d.candidates || []);
      }
    } catch (_e) { /* ignore */ }
  }, [headers, filterJobId, tab, talentSearch]);

  // Pipeline ikut saringan lowongan (dulu hanya saat muat ulang).
  useEffect(() => {
    if (loading) return;
    (async () => {
      try {
        const r = await api(`/pipeline${filterJobId ? `?job_id=${filterJobId}` : ''}`, { headers });
        const d = await r.json();
        setPipeline(d.pipeline || null);
      } catch (_e) { /* ignore */ }
    })();
  }, [filterJobId]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSeed = async () => {
    // Tahap 5 (2026-11-07): data contoh dulu MENGHAPUS semua lowongan & kandidat; kini hanya ke rekrutmen kosong
    if (!(await confirmDialog({ title: 'Muat data contoh rekrutmen?', body: 'Hanya bisa bila belum ada lowongan dan kandidat.', confirmLabel: 'Muat contoh' }))) return;
    setSeeding(true);
    try {
      const r = await api(`/seed`, { method: 'POST', headers });
      if (!r.ok) { const d = await r.json().catch(() => ({})); toast.error(typeof d.detail === 'string' ? d.detail : 'Gagal memuat contoh'); return; }
      await refresh();
      toast.success('Data contoh dimuat');
    } catch { toast.error('Gagal memuat contoh'); }
    finally { setSeeding(false); }
  };

  const openJobForm = (j = null) => {
    setEditJob(j);
    setJobForm(j ? { title: j.title, department: j.department, location: j.location, type: j.type, level: j.level, salary_min: j.salary_min, salary_max: j.salary_max, headcount: j.headcount, description: j.description, status: j.status, deadline: j.deadline ? j.deadline.slice(0, 10) : '' }
      : { title: '', department: '', location: 'Bandung', type: 'Full-time', level: 'Staff', salary_min: 0, salary_max: 0, headcount: 1, description: '', status: 'open', deadline: '' });
    setShowJobForm(true);
  };

  const handleSaveJob = async () => {
    setSaving(true);
    try {
      const r = editJob
        ? await api(`/jobs/${editJob.job_id}`, { method: 'PUT', headers, body: JSON.stringify(jobForm) })
        : await api(`/jobs`, { method: 'POST', headers, body: JSON.stringify(jobForm) });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);  // 2026-11-06 (pola P6): dulu form ditutup walau ditolak
      setShowJobForm(false);
      await refresh();
      toast.success(editJob ? 'Lowongan diperbarui' : 'Lowongan dibuat');
    } catch { toast.error('Gagal menyimpan'); } finally { setSaving(false); }
  };

  const handleSaveCand = async () => {
    setSaving(true);
    try {
      const r = await api(`/candidates`, { method: 'POST', headers, body: JSON.stringify(candForm) });
      const d = await r.json().catch(() => ({}));
      // 2026-11-06 (pola P6): dulu "Kandidat ditambahkan" muncul & form ditutup walau server menolak
      if (!r.ok || !d.ok) { toast.error(typeof d.detail === 'string' ? d.detail : 'Gagal menambah kandidat'); return; }
      if (d.ok && cvFile) {
        const reader = new FileReader();
        reader.onload = async (e) => {
          const base64 = e.target.result.split(',')[1];
          const rc = await api(`/candidates/${d.candidate.candidate_id}/upload-cv`, {
            method: 'POST', headers,
            body: JSON.stringify({ cv_data: base64, cv_filename: cvFile.name, cv_size: cvFile.size }),
          });
          if (!rc.ok) toast.error('Kandidat tersimpan, tetapi CV gagal diunggah. Unggah ulang dari detail kandidat.');  // 2026-11-06 (pola P6): dulu penolakan server diam saja
        };
        reader.readAsDataURL(cvFile);
      }
      setShowCandForm(false);
      setCvFile(null);
      await refresh();
      toast.success('Kandidat ditambahkan');
    } catch { toast.error('Gagal menambah kandidat'); } finally { setSaving(false); }
  };

  const keluarkanPool = async (c) => {
    const r = await api(`/talent-pool/${c.candidate_id}/toggle`, { method: 'POST', headers });
    if (!r.ok) { toast.error('Gagal mengeluarkan dari talent pool'); return; }
    refresh();
    toast.success('Dikeluarkan dari talent pool');
  };

  const filteredCandidates = useMemo(() =>
    candidates.filter(c => !q || c.name?.toLowerCase().includes(q.toLowerCase()) || c.email?.toLowerCase().includes(q.toLowerCase())),
  [candidates, q]);
  const { page, setPage, totalPages, total, paged } = useClientPagination(filteredCandidates, 20);

  // "Diterima" per lowongan dihitung dari kandidat bertahap Hired di pipeline (bukan penghitung tersimpan).
  const diterimaPerLowongan = useMemo(() => {
    const m = {};
    (pipeline?.Hired?.candidates || []).forEach((c) => { m[c.job_id] = (m[c.job_id] || 0) + 1; });
    return m;
  }, [pipeline]);
  const diterima = (j) => (filterJobId && filterJobId !== j.job_id ? (j.hired_count || 0) : (diterimaPerLowongan[j.job_id] || 0));

  const s = analytics?.summary || {};
  const ringkasan = analytics && (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <StatTile label="Lowongan dibuka" value={s.open_jobs ?? 0} sub={`Dari ${s.total_jobs ?? 0} lowongan.`} />
      <StatTile label="Kandidat" value={s.total_candidates ?? 0} sub={`${s.in_progress ?? 0} masih diproses, ${s.rejected ?? 0} ditolak.`} />
      <StatTile label="Diterima" value={s.hired ?? 0} accent={s.hired ? 'success' : 'default'} sub="Kandidat di tahap diterima." />
      <StatTile label="Tingkat diterima" value={s.total_candidates ? `${s.conversion_rate || 0}%` : '—'}
        sub={s.total_candidates ? 'Diterima ÷ semua kandidat.' : 'Belum ada kandidat.'} />
    </div>
  );
  const muatUlang = <Button variant="outline" size="icon" onClick={refresh} title="Muat ulang" aria-label="Muat ulang"><RefreshCw /></Button>;
  const pilihLowongan = (
    <SmartNativeSelect value={filterJobId} onChange={e => setFilterJobId(e.target.value)} className="w-56" aria-label="Saring lowongan">
      <option value="">Semua lowongan</option>
      {jobs.map(j => <option key={j.job_id} value={j.job_id}>{j.title}</option>)}
    </SmartNativeSelect>
  );
  const galat = error && <Notice tone="danger" title="Gagal memuat data rekrutmen">{error}</Notice>;
  const memuat = <p className="py-6 text-center text-sm text-muted-foreground">Memuat rekrutmen…</p>;
  const aksiHalaman = <>
    <Button variant="outline" onClick={handleSeed} disabled={seeding}>{seeding ? 'Memuat…' : 'Muat contoh'}</Button>
    <Button onClick={() => openJobForm()} data-testid="ats-new-job"><Plus />Buat lowongan</Button>
  </>;

  const kolomLowongan = [
    { kunci: 'posisi', label: 'Posisi', hp: 'judul', isi: (j) => (
      <div className="min-w-0" data-testid={`job-card-${j.job_id}`}>
        <p className="font-medium text-foreground">{j.title}</p>
        <p className="text-xs text-muted-foreground">
          {[j.department, j.location, JOB_TYPE[j.type] || j.type, JOB_LEVEL[j.level] || j.level].filter(Boolean).join(' · ')}
        </p>
      </div>) },
    { kunci: 'status', label: 'Status', isi: (j) => {
      const c = JOB_STATUS[j.status] || JOB_STATUS.draft;
      return <StatusBadge status={j.status} label={c.label} tone={c.tone} />;
    } },
    { kunci: 'kandidat', label: 'Kandidat', rata: 'kanan', isi: (j) => <span className="tabular-nums">{j.candidate_count || 0}</span> },
    { kunci: 'diterima', label: 'Diterima', rata: 'kanan', isi: (j) => <span className="tabular-nums">{diterima(j)}</span> },
    { kunci: 'tenggat', label: 'Tenggat', isi: (j) => <span className="text-sm md:whitespace-nowrap">{fmtDate(j.deadline)}</span> },
    { kunci: 'gaji', label: 'Kisaran gaji', isi: (j) => <span className="text-sm tabular-nums">{j.salary_min && j.salary_max ? `${fmtCurrency(j.salary_min)} – ${fmtCurrency(j.salary_max)}` : 'Negosiasi'}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (j) => <Button size="sm" variant="outline" onClick={() => openJobForm(j)}><Pencil />Ubah</Button> },
  ];
  const kolomKandidat = [
    { kunci: 'nama', label: 'Nama', hp: 'judul', isi: (c) => (
      <div className="min-w-0"><p className="font-medium text-foreground">{c.name}</p><p className="text-xs text-muted-foreground">{c.email || '—'}</p></div>) },
    { kunci: 'posisi', label: 'Posisi', isi: (c) => <span className="text-sm">{c.job_title || '—'}</span> },
    { kunci: 'tahap', label: 'Tahap', isi: (c) => <StageBadge stage={c.stage} /> },
    { kunci: 'cv', label: 'CV', isi: (c) => <span className="text-sm">{c.cv_url || c.cv_filename ? 'Ada' : '—'}</span> },
    { kunci: 'nilai', label: 'Nilai', isi: (c) => <RatingStars rating={c.rating} /> },
    { kunci: 'melamar', label: 'Melamar', isi: (c) => <span className="text-sm md:whitespace-nowrap">{fmtDate(c.applied_at)}</span> },
  ];
  const kolomUnduhKandidat = [
    { label: 'Nama', nilai: (c) => c.name }, { label: 'Email', nilai: (c) => c.email || '' }, { label: 'No. HP', nilai: (c) => c.phone || '' },
    { label: 'Posisi', nilai: (c) => c.job_title || c.position_applied || '' }, { label: 'Tahap', nilai: (c) => labelTahap(c.stage) },
    { label: 'Sumber', nilai: (c) => labelSumber(c.source) }, { label: 'Pendidikan', nilai: (c) => c.education || '' },
    { label: 'Pengalaman (tahun)', nilai: (c) => c.experience_years ?? '' }, { label: 'Nilai', nilai: (c) => c.rating || '' },
    { label: 'CV', nilai: (c) => (c.cv_url || c.cv_filename ? 'Ada' : '') }, { label: 'Melamar', nilai: (c) => fmtDate(c.applied_at) },
  ];
  const kolomPool = [
    { kunci: 'nama', label: 'Kandidat', hp: 'judul', isi: (c) => (
      <div className="min-w-0"><p className="font-medium text-foreground">{c.name}</p><p className="text-xs text-muted-foreground">{c.education || '—'}</p></div>) },
    { kunci: 'posisi', label: 'Posisi', isi: (c) => (
      <div><p className="text-sm">{c.position_applied || c.job_title || '—'}</p><p className="text-xs text-muted-foreground">{labelSumber(c.source)}</p></div>) },
    { kunci: 'tahap', label: 'Tahap', isi: (c) => <StageBadge stage={c.stage} /> },
    { kunci: 'kontak', label: 'Kontak', isi: (c) => <div className="text-sm"><p>{c.phone || '—'}</p><p className="text-xs text-muted-foreground">{c.email || '—'}</p></div> },
    { kunci: 'ditambahkan', label: 'Ditambahkan', isi: (c) => <span className="text-sm">{fmtDate(c.talent_pool_added_at)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (c) => (
      <Button size="sm" variant="destructive" onClick={() => keluarkanPool(c)} data-testid={`remove-talent-pool-${c.candidate_id}`}>
        <UserMinus />Keluarkan
      </Button>) },
  ];
  const totalKandidat = s.total_candidates || 0;
  const tahapRows = (analytics?.pipeline_stages || []).map((r) => ({ ...r, porsi: totalKandidat ? Math.round((r.count / totalKandidat) * 100) : 0 }));
  const sumberRows = (analytics?.source_breakdown || []).map((r) => ({
    sumber: r.source ?? r._id, count: r.count, porsi: totalKandidat ? Math.round((r.count / totalKandidat) * 100) : 0,
  }));

  return (
    <div data-testid="hr-ats-module">
      <HubTabs hubId="hr-recruitment" title="Rekrutmen & ATS" subtitle="Lowongan dan kandidat, dari lamaran masuk sampai diterima dan onboarding."
        value={tab} onValueChange={setTab}
        tabs={[
          { key: 'pipeline', label: 'Pipeline', Component: IsiTab, props: {
            actions: aksiHalaman, summary: ringkasan,
            filters: <>
              {pilihLowongan}
              <Button variant="outline" onClick={() => setShowCandForm(true)} data-testid="ats-add-candidate"><Plus />Tambah kandidat</Button>
            </>,
            tools: muatUlang,
            children: <>
              {galat}
              {loading ? memuat : pipeline ? <PipelineView pipeline={pipeline} onViewCandidate={setSelectedCandidate} />
                : <EmptyState title="Belum ada kandidat" description="Tambah kandidat atau muat data contoh." />}
            </>,
          } },
          { key: 'jobs', label: `Lowongan (${jobs.length})`, Component: IsiTab, props: {
            actions: aksiHalaman,
            tools: <>
              <TombolUnduh namaBerkas="lowongan-rekrutmen" namaLembar="Lowongan" baris={jobs} testId="ats-unduh-lowongan"
                kolom={[
                  { label: 'Posisi', nilai: (j) => j.title }, { label: 'Departemen', nilai: (j) => j.department || '' },
                  { label: 'Lokasi', nilai: (j) => j.location || '' }, { label: 'Jenis', nilai: (j) => JOB_TYPE[j.type] || j.type || '' },
                  { label: 'Tingkat', nilai: (j) => JOB_LEVEL[j.level] || j.level || '' },
                  { label: 'Status', nilai: (j) => (JOB_STATUS[j.status] || JOB_STATUS.draft).label },
                  { label: 'Kebutuhan orang', nilai: (j) => j.headcount ?? '' }, { label: 'Kandidat', nilai: (j) => j.candidate_count || 0 },
                  { label: 'Diterima', nilai: (j) => diterima(j) }, { label: 'Tenggat', nilai: (j) => fmtDate(j.deadline) },
                  { label: 'Gaji minimum', nilai: (j) => j.salary_min || '' }, { label: 'Gaji maksimum', nilai: (j) => j.salary_max || '' },
                ]} />
              {muatUlang}
            </>,
            children: loading ? memuat : (
              <TabelData kolom={kolomLowongan} baris={jobs} kunci={(j) => j.job_id} onKlikBaris={openJobForm} testId="ats-jobs"
                kosong={<EmptyState title="Belum ada lowongan" action={<Button onClick={() => openJobForm()}><Plus />Buat lowongan</Button>} />} />
            ),
          } },
          { key: 'candidates', label: 'Kandidat', Component: IsiTab, props: {
            actions: <Button onClick={() => setShowCandForm(true)} data-testid="ats-add-candidate-2"><Plus />Tambah kandidat</Button>,
            filters: <>
              <div className="relative w-full sm:w-64">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input value={q} onChange={e => setQ(e.target.value)} placeholder="Cari nama atau email" className="pl-8" />
              </div>
              {pilihLowongan}
            </>,
            tools: <>
              <TombolUnduh namaBerkas="kandidat-rekrutmen" namaLembar="Kandidat" baris={filteredCandidates} kolom={kolomUnduhKandidat} testId="ats-unduh-kandidat" />
              {muatUlang}
            </>,
            footer: total > 20 ? <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={20} onPageChange={setPage} /> : null,
            children: (
              <TabelData kolom={kolomKandidat} baris={paged} kunci={(c) => c.candidate_id} onKlikBaris={setSelectedCandidate} testId="ats-candidates"
                kosong={<EmptyState title={candidates.length ? 'Tidak ada kandidat yang cocok' : 'Belum ada kandidat'}
                  description={candidates.length ? 'Ubah kata pencarian atau saringan lowongan.' : 'Tambah kandidat dari tombol di atas.'} />} />
            ),
          } },
          { key: 'talent_pool', label: 'Talent pool', Component: IsiTab, props: {
            filters: (
              <div className="relative w-full sm:w-64">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input value={talentSearch} onChange={e => setTalentSearch(e.target.value)} placeholder="Cari nama, posisi, keahlian"
                  className="pl-8" data-testid="talent-pool-search" />
              </div>
            ),
            tools: <>
              <TombolUnduh namaBerkas="talent-pool" namaLembar="Talent pool" baris={talentPool} kolom={kolomUnduhKandidat} testId="ats-unduh-pool" />
              {muatUlang}
            </>,
            children: (
              <TabelData kolom={kolomPool} baris={talentPool} kunci={(c) => c.candidate_id} onKlikBaris={setSelectedCandidate} testId="ats-talent-pool"
                kosong={<EmptyState title="Talent pool kosong" description="Kandidat bagus yang belum diterima bisa disimpan di sini dari detail kandidat." />} />
            ),
          } },
          { key: 'analytics', label: 'Analitik', Component: IsiTab, props: {
            tools: muatUlang,
            children: (
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <Bagian judul="Kandidat per tahap" alat={
                  <TombolUnduh namaBerkas="kandidat-per-tahap" namaLembar="Per tahap" baris={tahapRows}
                    kolom={[{ label: 'Tahap', nilai: (r) => labelTahap(r.stage) }, { label: 'Kandidat', nilai: (r) => r.count }, { label: 'Porsi (%)', nilai: (r) => r.porsi }]} />}>
                  <TabelData baris={tahapRows} kunci={(r) => r.stage} testId="ats-per-tahap"
                    kolom={[
                      { kunci: 'tahap', label: 'Tahap', hp: 'judul', isi: (r) => labelTahap(r.stage) },
                      { kunci: 'jumlah', label: 'Kandidat', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.count}</span> },
                      { kunci: 'porsi', label: 'Porsi', rata: 'kanan', isi: (r) => <span className="tabular-nums text-muted-foreground">{r.porsi}%</span> },
                    ]}
                    kosong={<EmptyState title="Belum ada kandidat" />} />
                </Bagian>
                <Bagian judul="Sumber kandidat" alat={
                  <TombolUnduh namaBerkas="sumber-kandidat" namaLembar="Sumber" baris={sumberRows}
                    kolom={[{ label: 'Sumber', nilai: (r) => labelSumber(r.sumber) }, { label: 'Kandidat', nilai: (r) => r.count }, { label: 'Porsi (%)', nilai: (r) => r.porsi }]} />}>
                  <TabelData baris={sumberRows} kunci={(r) => String(r.sumber)} testId="ats-per-sumber"
                    kolom={[
                      { kunci: 'sumber', label: 'Sumber', hp: 'judul', isi: (r) => labelSumber(r.sumber) },
                      { kunci: 'jumlah', label: 'Kandidat', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.count}</span> },
                      { kunci: 'porsi', label: 'Porsi', rata: 'kanan', isi: (r) => <span className="tabular-nums text-muted-foreground">{r.porsi}%</span> },
                    ]}
                    kosong={<EmptyState title="Belum ada kandidat" />} />
                </Bagian>
              </div>
            ),
          } },
        ]} />

      {/* DETAIL KANDIDAT */}
      {selectedCandidate && (
        <CandidateDetailModal
          candidate={selectedCandidate}
          headers={headers}
          jobs={jobs}
          onStageAction={() => {}}
          onRefresh={refresh}
          onClose={() => setSelectedCandidate(null)}
        />
      )}

      {/* FORM LOWONGAN */}
      <FormPopup open={showJobForm} onClose={() => setShowJobForm(false)} ukuran="panjang" onSimpan={handleSaveJob} menyimpan={saving}
        bisaSimpan={!!jobForm.title} judul={editJob ? 'Ubah lowongan' : 'Buat lowongan baru'} labelSimpan={editJob ? 'Simpan' : 'Buat lowongan'}
        testId="ats-job-form">
        <Isian label="Judul posisi" wajib htmlFor="ats-job-judul">
          <Input id="ats-job-judul" value={jobForm.title} onChange={e => setJobForm(p => ({ ...p, title: e.target.value }))} />
        </Isian>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Departemen">
            <SmartNativeSelect value={jobForm.department || ''} onChange={e => setJobForm(p => ({ ...p, department: e.target.value }))} data-testid="ats-job-department">
              <option value="">— Pilih departemen —</option>
              {departmentOptions(orgUnits, jobForm.department).map(d => <option key={d.value} value={d.value}>{d.label}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Lokasi" htmlFor="ats-job-lokasi">
            <Input id="ats-job-lokasi" value={jobForm.location} onChange={e => setJobForm(p => ({ ...p, location: e.target.value }))} />
          </Isian>
          <Isian label="Jenis">
            <SmartNativeSelect searchable={false} value={jobForm.type} onChange={e => setJobForm(p => ({ ...p, type: e.target.value }))}>
              <option value="Full-time">Penuh waktu</option><option value="Part-time">Paruh waktu</option><option value="Contract">Kontrak</option><option value="Magang">Magang</option>
            </SmartNativeSelect>
          </Isian>
          <Isian label="Tingkat">
            <SmartNativeSelect searchable={false} value={jobForm.level} onChange={e => setJobForm(p => ({ ...p, level: e.target.value }))}>
              <option value="Staff">Staf</option><option value="Senior">Senior</option><option value="Supervisor">Supervisor</option><option value="Manager">Manajer</option>
            </SmartNativeSelect>
          </Isian>
          <Isian label="Gaji minimum (Rp)">
            <MoneyInput value={jobForm.salary_min} onChange={e => setJobForm(p => ({ ...p, salary_min: +e.target.value }))} />
          </Isian>
          <Isian label="Gaji maksimum (Rp)">
            <MoneyInput value={jobForm.salary_max} onChange={e => setJobForm(p => ({ ...p, salary_max: +e.target.value }))} />
          </Isian>
          <Isian label="Kebutuhan orang" htmlFor="ats-job-headcount">
            <Input id="ats-job-headcount" type="number" min={1} value={jobForm.headcount} onChange={e => setJobForm(p => ({ ...p, headcount: +e.target.value }))} />
          </Isian>
          <Isian label="Tenggat" petunjuk="Kosong = tanpa tenggat.">
            <DatePicker value={jobForm.deadline} onChange={v => setJobForm(p => ({ ...p, deadline: v }))} placeholder="Tanpa tenggat" testId="ats-job-deadline" />
          </Isian>
          <Isian label="Status">
            <SmartNativeSelect searchable={false} value={jobForm.status} onChange={e => setJobForm(p => ({ ...p, status: e.target.value }))}>
              <option value="open">Buka</option><option value="draft">Draf</option><option value="on_hold">Tunda</option><option value="closed">Tutup</option>
            </SmartNativeSelect>
          </Isian>
        </div>
        <Isian label="Deskripsi" htmlFor="ats-job-desk">
          <Textarea id="ats-job-desk" rows={3} value={jobForm.description} onChange={e => setJobForm(p => ({ ...p, description: e.target.value }))} />
        </Isian>
      </FormPopup>

      {/* FORM KANDIDAT */}
      <FormPopup open={showCandForm} onClose={() => setShowCandForm(false)} ukuran="panjang" onSimpan={handleSaveCand} menyimpan={saving}
        bisaSimpan={!!candForm.name} judul="Tambah kandidat" labelSimpan="Tambah kandidat" testId="ats-cand-form">
        <Isian label="Nama lengkap" wajib htmlFor="ats-cand-nama">
          <Input id="ats-cand-nama" value={candForm.name} onChange={e => setCandForm(p => ({ ...p, name: e.target.value }))} />
        </Isian>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Email" htmlFor="ats-cand-email">
            <Input id="ats-cand-email" value={candForm.email} onChange={e => setCandForm(p => ({ ...p, email: e.target.value }))} />
          </Isian>
          <Isian label="No. HP" htmlFor="ats-cand-hp">
            <Input id="ats-cand-hp" value={candForm.phone} onChange={e => setCandForm(p => ({ ...p, phone: e.target.value }))} />
          </Isian>
          <Isian label="Lowongan">
            <SmartNativeSelect value={candForm.job_id} onChange={e => setCandForm(p => ({ ...p, job_id: e.target.value }))}>
              <option value="">Pilih lowongan</option>
              {jobs.map(j => <option key={j.job_id} value={j.job_id}>{j.title}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Sumber">
            <SmartNativeSelect searchable={false} value={candForm.source} onChange={e => setCandForm(p => ({ ...p, source: e.target.value }))}>
              <option value="Walk-in">Datang langsung</option><option value="Jobstreet">Jobstreet</option><option value="LinkedIn">LinkedIn</option><option value="Referral">Rekomendasi</option><option value="Website">Situs web</option>
            </SmartNativeSelect>
          </Isian>
          <Isian label="Pendidikan">
            <SmartNativeSelect searchable={false} value={candForm.education} onChange={e => setCandForm(p => ({ ...p, education: e.target.value }))}>
              <option value="SMA/SMK">SMA/SMK</option><option value="D3">D3</option><option value="S1">S1</option><option value="S2">S2</option>
            </SmartNativeSelect>
          </Isian>
          <Isian label="Pengalaman (tahun)" htmlFor="ats-cand-pengalaman">
            <Input id="ats-cand-pengalaman" type="number" min={0} value={candForm.experience_years} onChange={e => setCandForm(p => ({ ...p, experience_years: +e.target.value }))} />
          </Isian>
        </div>
        <Isian label="CV" petunjuk="Isi tautan CV, atau unggah berkas PDF.">
          <div className="space-y-2">
            <Input value={candForm.cv_url} onChange={e => setCandForm(p => ({ ...p, cv_url: e.target.value }))} placeholder="Tautan CV (Google Drive, dll.)" />
            <div className="flex flex-wrap items-center gap-2">
              <input type="file" ref={cvFileRef} className="hidden" accept=".pdf,.doc,.docx" onChange={e => setCvFile(e.target.files?.[0] || null)} />
              <Button type="button" size="sm" variant="outline" onClick={() => cvFileRef.current?.click()}>
                <Upload />{cvFile ? cvFile.name : 'Unggah berkas PDF'}
              </Button>
              {cvFile && (
                <Button type="button" size="icon-sm" variant="ghost" onClick={() => setCvFile(null)} aria-label="Batalkan berkas" title="Batalkan berkas">
                  <X />
                </Button>
              )}
            </div>
          </div>
        </Isian>
      </FormPopup>
    </div>
  );
}

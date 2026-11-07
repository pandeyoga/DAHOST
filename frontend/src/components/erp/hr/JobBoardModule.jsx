/**
 * Job Board (Portal SDM) — lowongan internal, lamaran saya, jalur karier.
 *
 * Standar UI/UX v2 (8 Nov 2026): tab halaman (HubTabs) + cetakan PageLayout, lowongan & lamaran = tabel
 * + unduh Excel/CSV (dulu kartu besar berulang), detail lowongan = DetailPopup, form pasang lowongan &
 * lamar = FormPopup, tenggat = DatePicker (dulu input tanggal bawaan), bahasa Indonesia, tanpa gradien.
 * Daftar lowongan dulu diam-diam 50 pertama — kini sampai 500 (batas server).
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { Plus, RefreshCw, Send } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import DatePicker from '@/components/ui/date-picker';
import { formatDateID, formatRupiah } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import HubTabs from '../hubs/HubTabs';
import { EmptyState, StatusBadge } from '../moduleAtoms';
import { DepartmentSelect } from './hrPickers';

// Nilai dari server → label layar (nilai yang dikirim tetap sama).
const REKOMENDASI = {
  'Strongly Recommended': { label: 'Sangat cocok', tone: 'success' },
  'Recommended': { label: 'Cocok', tone: 'info' },
  'Consider': { label: 'Pertimbangkan', tone: 'warning' },
  'Not Recommended': { label: 'Kurang cocok', tone: 'danger' },
};
const LEVEL = { junior: 'Junior', mid: 'Menengah', senior: 'Senior', lead: 'Pimpinan tim' };
const JENIS = { 'full-time': 'Penuh waktu', 'part-time': 'Paruh waktu', contract: 'Kontrak' };
const STATUS_LAMARAN = {
  pending: { label: 'Terkirim', tone: 'muted' },
  reviewing: { label: 'Ditinjau', tone: 'info' },
  shortlisted: { label: 'Masuk daftar pendek', tone: 'primary' },
  accepted: { label: 'Diterima', tone: 'success' },
  rejected: { label: 'Ditolak', tone: 'danger' },
};
const labelLevel = (l) => LEVEL[l] || l || '—';
const labelJenis = (j) => JENIS[j] || j || '—';
const tanggal = (d) => (d ? formatDateID(d) : '—');
const gaji = (j) => (j.salary_range_min && j.salary_range_max
  ? `${formatRupiah(j.salary_range_min)} – ${formatRupiah(j.salary_range_max)}` : '—');

const FORM_KOSONG = {
  title: '', department: '', location: '', job_type: 'full-time', level: 'mid',
  description: '', responsibilities: [], required_skills: [], preferred_skills: [],
  salary_range_min: null, salary_range_max: null, deadline: '',
};

/** Isi satu tab: cetakan PageLayout di dalam hub. */
function IsiTab({ actions, tools, children }) {
  return <PageLayout actions={actions} tools={tools}>{children}</PageLayout>;
}

function DaftarKeahlian({ judul, isi }) {
  if (!isi?.length) return null;
  return (
    <div>
      <p className="mb-1 text-sm font-medium text-foreground">{judul}</p>
      <div className="flex flex-wrap gap-1.5">
        {isi.map((s, i) => <StatusBadge key={i} status="skill" label={s} tone="default" />)}
      </div>
    </div>
  );
}

export default function JobBoardModule({ token }) {
  const [activeTab, setActiveTab] = useState('browse'); // browse, my-applications, career-paths
  const [jobs, setJobs] = useState([]);
  const [myApplications, setMyApplications] = useState([]);
  const [selectedJob, setSelectedJob] = useState(null);
  const [loading, setLoading] = useState(false);
  const [userRole, setUserRole] = useState('');

  // Post job dialog
  const [showPostDialog, setShowPostDialog] = useState(false);
  const [jobForm, setJobForm] = useState(FORM_KOSONG);

  // Apply dialog
  const [showApplyDialog, setShowApplyDialog] = useState(false);
  const [applyForm, setApplyForm] = useState({
    job_id: '',
    cover_letter: '',
    additional_info: '',
    resume_url: ''
  });

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);

  const fetchJobs = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/hr/job-board/jobs?status=open&limit=500`, { headers });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setJobs(data?.data || []);
    } catch (e) {
      toast.error(`Gagal memuat lowongan: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [headers]);

  const fetchMyApplications = useCallback(async () => {
    try {
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/hr/job-board/applications/my`, { headers });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setMyApplications(data?.data || []);
    } catch (e) {
      toast.error(`Gagal memuat lamaran: ${e.message}`);
    }
  }, [headers]);

  useEffect(() => {
    fetchJobs();
    fetchMyApplications();
    // Get user role from token (simplified - could decode JWT)
    setUserRole('user'); // Default
  }, [fetchJobs, fetchMyApplications]);

  const handleViewJob = async (jobId) => {
    try {
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/hr/job-board/jobs/${jobId}`, { headers });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setSelectedJob(data?.data);
    } catch (e) {
      toast.error(`Gagal memuat rincian: ${e.message}`);
    }
  };

  const handlePostJob = async () => {
    if (!jobForm.title || !jobForm.department || !jobForm.description) {
      toast.error('Lengkapi isian lowongan: posisi, departemen, dan deskripsi');
      return;
    }

    try {
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/hr/job-board/jobs`, {
        method: 'POST',
        headers,
        body: JSON.stringify(jobForm)
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      toast.success('Lowongan berhasil dipasang!');
      setShowPostDialog(false);
      setJobForm(FORM_KOSONG);
      fetchJobs();
    } catch (e) {
      toast.error(`Gagal memasang lowongan: ${e.message}`);
    }
  };

  const handleApply = async () => {
    if (!applyForm.cover_letter) {
      toast.error('Surat lamaran harus diisi');
      return;
    }

    try {
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/hr/job-board/applications`, {
        method: 'POST',
        headers,
        body: JSON.stringify(applyForm)
      });
      if (!r.ok) {
        const errorData = await r.json();
        throw new Error(errorData.detail || `HTTP ${r.status}`);
      }
      toast.success('Lamaran berhasil dikirim!');
      setShowApplyDialog(false);
      setApplyForm({ job_id: '', cover_letter: '', additional_info: '', resume_url: '' });
      fetchMyApplications();
      setSelectedJob(null);
    } catch (e) {
      toast.error(`Lamaran gagal: ${e.message}`);
    }
  };

  const openApplyDialog = (job) => {
    setApplyForm({ ...applyForm, job_id: job.id });
    setShowApplyDialog(true);
  };

  const muatUlang = (
    <Button variant="outline" size="icon" onClick={() => { fetchJobs(); fetchMyApplications(); }} disabled={loading}
      title="Muat ulang" aria-label="Muat ulang">
      <RefreshCw className={loading ? 'animate-spin' : ''} />
    </Button>
  );
  // Tombol pasang lowongan hanya untuk SDM/manajer (perilaku lama dipertahankan).
  const aksiPasang = (userRole === 'hr' || userRole === 'manager') ? (
    <Button onClick={() => setShowPostDialog(true)}><Plus />Pasang lowongan</Button>
  ) : null;

  const kolomLowongan = [
    { kunci: 'posisi', label: 'Posisi', hp: 'judul', isi: (j) => (
      <div className="min-w-0">
        <p className="font-medium text-foreground">{j.title}</p>
        <p className="text-xs text-muted-foreground">{j.department || '—'}</p>
      </div>) },
    { kunci: 'lokasi', label: 'Lokasi', isi: (j) => <span className="text-sm">{j.location || '—'}</span> },
    { kunci: 'tingkat', label: 'Tingkat', isi: (j) => <span className="text-sm">{labelLevel(j.level)}</span> },
    { kunci: 'tenggat', label: 'Tenggat', isi: (j) => <span className="text-sm md:whitespace-nowrap">{tanggal(j.deadline)}</span> },
    { kunci: 'gaji', label: 'Kisaran gaji', isi: (j) => <span className="text-sm tabular-nums">{gaji(j)}</span> },
    { kunci: 'pelamar', label: 'Pelamar', rata: 'kanan', isi: (j) => <span className="tabular-nums">{j.application_count || 0}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (j) => (
      <Button size="sm" variant="outline" onClick={() => openApplyDialog(j)} data-testid={`job-apply-${j.id}`}><Send />Lamar</Button>) },
  ];
  const kolomLamaran = [
    { kunci: 'posisi', label: 'Posisi', hp: 'judul', isi: (a) => <span className="font-medium text-foreground">{a.job_title || '—'}</span> },
    { kunci: 'tanggal', label: 'Dilamar', isi: (a) => <span className="text-sm md:whitespace-nowrap">{tanggal(a.applied_at)}</span> },
    { kunci: 'status', label: 'Status', isi: (a) => {
      const s = STATUS_LAMARAN[a.status] || { label: a.status || '—', tone: 'default' };
      return <StatusBadge status={a.status} label={s.label} tone={s.tone} />;
    } },
    { kunci: 'surat', label: 'Surat lamaran', hp: 'keterangan', isi: (a) => (
      <span className="block truncate text-sm text-muted-foreground md:max-w-[28rem]" title={a.cover_letter}>{a.cover_letter || '—'}</span>) },
  ];

  const sm = selectedJob?.skill_match;
  const rek = sm ? (REKOMENDASI[sm.recommendation] || { label: sm.recommendation, tone: 'default' }) : null;

  return (
    <div data-testid="job-board-module">
      <HubTabs hubId="hr-job-board" title="Job Board" subtitle="Lowongan internal untuk karyawan yang ingin pindah posisi atau naik jenjang."
        value={activeTab} onValueChange={setActiveTab}
        tabs={[
          { key: 'browse', label: `Lowongan (${jobs.length})`, Component: IsiTab, props: {
            actions: aksiPasang,
            tools: <>
              <TombolUnduh namaBerkas="lowongan-internal" namaLembar="Lowongan" baris={jobs} testId="job-board-unduh"
                kolom={[
                  { label: 'Posisi', nilai: (j) => j.title }, { label: 'Departemen', nilai: (j) => j.department || '' },
                  { label: 'Lokasi', nilai: (j) => j.location || '' }, { label: 'Tingkat', nilai: (j) => labelLevel(j.level) },
                  { label: 'Jenis', nilai: (j) => labelJenis(j.job_type) }, { label: 'Tenggat', nilai: (j) => tanggal(j.deadline) },
                  { label: 'Gaji minimum', nilai: (j) => j.salary_range_min ?? '' }, { label: 'Gaji maksimum', nilai: (j) => j.salary_range_max ?? '' },
                  { label: 'Pelamar', nilai: (j) => j.application_count || 0 },
                ]} />
              {muatUlang}
            </>,
            children: loading && jobs.length === 0 ? <p className="py-10 text-center text-sm text-muted-foreground">Memuat lowongan…</p> : (
              <TabelData kolom={kolomLowongan} baris={jobs} onKlikBaris={(j) => handleViewJob(j.id)} testId="job-board-jobs"
                kosong={<EmptyState title="Belum ada lowongan terbuka" description="Lowongan internal yang dipasang SDM akan tampil di sini." />} />
            ),
          } },
          { key: 'my-applications', label: `Lamaran saya (${myApplications.length})`, Component: IsiTab, props: {
            tools: <>
              <TombolUnduh namaBerkas="lamaran-saya" namaLembar="Lamaran" baris={myApplications} testId="job-board-unduh-lamaran"
                kolom={[
                  { label: 'Posisi', nilai: (a) => a.job_title || '' }, { label: 'Dilamar', nilai: (a) => tanggal(a.applied_at) },
                  { label: 'Status', nilai: (a) => STATUS_LAMARAN[a.status]?.label || a.status || '' },
                  { label: 'Surat lamaran', nilai: (a) => a.cover_letter || '' },
                ]} />
              {muatUlang}
            </>,
            children: (
              <TabelData kolom={kolomLamaran} baris={myApplications} testId="job-board-applications"
                kosong={<EmptyState title="Anda belum pernah melamar" description="Pilih lowongan di tab Lowongan, lalu klik Lamar." />} />
            ),
          } },
          { key: 'career-paths', label: 'Jalur karier', Component: IsiTab, props: {
            children: <EmptyState title="Jalur karier segera hadir"
              description="Nantinya tampil peta jabatan dan jenjang yang bisa dituju dari posisi Anda sekarang." />,
          } },
        ]} />

      {/* ─── Rincian lowongan (popup) ─── */}
      {selectedJob && (
        <DetailPopup open onClose={() => setSelectedJob(null)} judul={selectedJob.title} testId="job-board-detail"
          keterangan={[selectedJob.department, selectedJob.location].filter(Boolean).join(' · ')}
          aksi={<Button size="sm" onClick={() => openApplyDialog(selectedJob)}><Send />Lamar posisi ini</Button>}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Departemen">{selectedJob.department || '—'}</BarisDetail>
            <BarisDetail label="Lokasi">{selectedJob.location || '—'}</BarisDetail>
            <BarisDetail label="Tingkat">{labelLevel(selectedJob.level)}</BarisDetail>
            <BarisDetail label="Jenis">{labelJenis(selectedJob.job_type)}</BarisDetail>
            <BarisDetail label="Tenggat">{tanggal(selectedJob.deadline)}</BarisDetail>
            <BarisDetail label="Kisaran gaji">{gaji(selectedJob)}</BarisDetail>
          </dl>

          {sm && (
            <div className="space-y-2 rounded-lg border border-[var(--glass-border)] p-3">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-sm font-medium text-foreground">Kecocokan Anda</p>
                <span className="text-base font-semibold tabular-nums">{sm.overall_score}%</span>
                {rek && <StatusBadge status={sm.recommendation} label={rek.label} tone={rek.tone} />}
              </div>
              <dl>
                <BarisDetail label="Keahlian wajib cocok">{sm.required_match ?? '—'}</BarisDetail>
                <BarisDetail label="Keahlian tambahan cocok">{sm.preferred_match ?? '—'}</BarisDetail>
              </dl>
              {sm.missing_required?.length > 0 && (
                <div>
                  <p className="mb-1 text-xs text-muted-foreground">Keahlian wajib yang belum Anda miliki</p>
                  <div className="flex flex-wrap gap-1.5">
                    {sm.missing_required.map((s, i) => <StatusBadge key={i} status="kurang" label={s} tone="danger" />)}
                  </div>
                </div>
              )}
            </div>
          )}

          <div>
            <p className="mb-1 text-sm font-medium text-foreground">Deskripsi</p>
            <p className="text-sm leading-relaxed text-muted-foreground">{selectedJob.description || '—'}</p>
          </div>
          {selectedJob.responsibilities?.length > 0 && (
            <div>
              <p className="mb-1 text-sm font-medium text-foreground">Tanggung jawab</p>
              <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                {selectedJob.responsibilities.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            </div>
          )}
          <DaftarKeahlian judul="Keahlian wajib" isi={selectedJob.required_skills} />
          <DaftarKeahlian judul="Keahlian tambahan" isi={selectedJob.preferred_skills} />
        </DetailPopup>
      )}

      {/* ─── Pasang lowongan (popup) ─── */}
      <FormPopup open={showPostDialog} onClose={() => setShowPostDialog(false)} ukuran="panjang" onSimpan={handlePostJob}
        judul="Pasang lowongan baru" labelSimpan="Pasang lowongan" testId="job-board-post-form">
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Posisi" wajib htmlFor="job-posisi">
            <Input id="job-posisi" value={jobForm.title} onChange={e => setJobForm({ ...jobForm, title: e.target.value })} placeholder="Contoh: Kepala regu jahit" />
          </Isian>
          <Isian label="Departemen" wajib>
            {/* 2026-11-07 (OR1): dari Struktur Organisasi (satu daftar untuk semua formulir) */}
            <DepartmentSelect token={token} value={jobForm.department} testId="job-board-department"
              onChange={v => setJobForm(f => ({ ...f, department: v }))} />
          </Isian>
          <Isian label="Lokasi" htmlFor="job-lokasi">
            <Input id="job-lokasi" value={jobForm.location} onChange={e => setJobForm({ ...jobForm, location: e.target.value })} placeholder="Contoh: Bandung" />
          </Isian>
          <Isian label="Jenis pekerjaan">
            <SmartNativeSelect searchable={false} value={jobForm.job_type} onChange={e => setJobForm({ ...jobForm, job_type: e.target.value })}>
              {Object.entries(JENIS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Tingkat">
            <SmartNativeSelect searchable={false} value={jobForm.level} onChange={e => setJobForm({ ...jobForm, level: e.target.value })}>
              {Object.entries(LEVEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Tenggat lamaran" petunjuk="Kosong = tanpa tenggat.">
            <DatePicker value={jobForm.deadline} onChange={v => setJobForm(f => ({ ...f, deadline: v }))} placeholder="Tanpa tenggat" testId="job-board-deadline" />
          </Isian>
        </div>
        <Isian label="Deskripsi" wajib htmlFor="job-deskripsi">
          <Textarea id="job-deskripsi" value={jobForm.description} onChange={e => setJobForm({ ...jobForm, description: e.target.value })} rows={4} />
        </Isian>
      </FormPopup>

      {/* ─── Lamar (popup) ─── */}
      <FormPopup open={showApplyDialog} onClose={() => setShowApplyDialog(false)} ukuran="pendek" onSimpan={handleApply}
        judul="Lamar posisi" labelSimpan="Kirim lamaran" testId="job-board-apply-form"
        keterangan={jobs.find((j) => j.id === applyForm.job_id)?.title || selectedJob?.title}>
        <Isian label="Surat lamaran" wajib htmlFor="job-surat">
          <Textarea id="job-surat" value={applyForm.cover_letter} rows={5}
            onChange={e => setApplyForm({ ...applyForm, cover_letter: e.target.value })}
            placeholder="Jelaskan mengapa Anda cocok untuk posisi ini" />
        </Isian>
        <Isian label="Informasi tambahan (opsional)" htmlFor="job-info">
          <Textarea id="job-info" value={applyForm.additional_info} rows={2}
            onChange={e => setApplyForm({ ...applyForm, additional_info: e.target.value })} />
        </Isian>
        <Isian label="Tautan CV (opsional)" htmlFor="job-cv">
          <Input id="job-cv" value={applyForm.resume_url} onChange={e => setApplyForm({ ...applyForm, resume_url: e.target.value })} placeholder="https://…" />
        </Isian>
      </FormPopup>
    </div>
  );
}

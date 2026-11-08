/**
 * Pembelajaran (Portal SDM) — kursus, materi, pendaftaran, dan kemajuan karyawan.
 *
 * Standar UI/UX v2 (8 Nov 2026): tab halaman (HubTabs) + cetakan PageLayout per tab, daftar kursus = tabel
 * (dulu kartu besar berulang), detail kursus = popup, form kursus = FormPopup, unduh Excel/CSV di tiap tabel,
 * kartu angka StatTile, warna token.
 * Perbaikan angka: "Peserta"/"Selesai" per kursus dulu dari penghitung tersimpan (data contoh mengisinya
 * angka karangan, dan "selesai" hanya bertambah bila lulus) — kini dihitung dari daftar pendaftaran yang sama
 * dengan tab Pendaftaran. Daftar kursus/pendaftaran dulu diam-diam 50 baris pertama — kini semua halaman.
 * Materi kursus kini benar-benar tampil di detail (dulu daftar tidak membawa materi).
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { Pencil, Plus, RefreshCw, Search, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatDateID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import HubTabs from './hubs/HubTabs';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = (path, opts = {}) => fetch(`${BACKEND_URL}/api/dewi/lms${path}`, opts);
const fmtDate = (d) => (d ? formatDateID(d) : '—');

const STATUS_CONFIG = {
  enrolled:    { label: 'Terdaftar',  tone: 'info' },
  in_progress: { label: 'Berjalan',   tone: 'warning' },
  completed:   { label: 'Selesai',    tone: 'success' },
  failed:      { label: 'Gagal',      tone: 'danger' },
  draft:       { label: 'Draf',       tone: 'muted' },
  active:      { label: 'Aktif',      tone: 'success' },
  archived:    { label: 'Diarsipkan', tone: 'muted' },
};
const labelStatus = (s) => (STATUS_CONFIG[s] || STATUS_CONFIG.draft).label;
function Status({ status }) {
  const c = STATUS_CONFIG[status] || STATUS_CONFIG.draft;
  return <StatusBadge status={status} label={c.label} tone={c.tone} />;
}

const MATERIAL_TYPE = { text: 'Teks', video: 'Video', pdf: 'PDF', slides: 'Slide', quiz: 'Kuis' };
const LEVEL_CONFIG = { Beginner: 'Pemula', Intermediate: 'Menengah', Advanced: 'Lanjutan' };
const labelLevel = (l) => LEVEL_CONFIG[l] || l || '—';
const KOSONG = { title: '', description: '', category: 'Umum', level: 'Beginner', duration_hours: 4, instructor: '', pass_score: 75, status: 'draft' };

/** Ambil semua halaman satu daftar (API membatasi 200 baris per halaman). */
async function ambilSemua(path, kunci, headers) {
  const semua = [];
  for (let page = 1; page <= 50; page += 1) {
    const r = await API(`${path}${path.includes('?') ? '&' : '?'}limit=200&page=${page}`, { headers });
    if (!r.ok) throw new Error(`Gagal memuat (${r.status})`);
    const d = await r.json();
    const rows = d[kunci] || [];
    semua.push(...rows);
    if (rows.length < 200 || (d.total != null && semua.length >= d.total)) break;
  }
  return semua;
}

/** Isi satu tab: cetakan PageLayout di dalam hub. */
function IsiTab({ actions, filters, tools, summary, footer, children }) {
  return <PageLayout actions={actions} filters={filters} tools={tools} summary={summary} footer={footer}>{children}</PageLayout>;
}

/** Pendaftaran berhalaman (20 baris), tetap di tab sendiri. */
function TabelPendaftaran({ enrollments, alat }) {
  const { page, setPage, totalPages, total, paged } = useClientPagination(enrollments, 20);
  const kolom = [
    { kunci: 'karyawan', label: 'Karyawan', hp: 'judul', isi: (e) => <span className="font-medium text-foreground">{e.employee_name || '—'}</span> },
    { kunci: 'kursus', label: 'Kursus', hp: 'keterangan', isi: (e) => <span className="block truncate md:max-w-[18rem]" title={e.course_title}>{e.course_title || '—'}</span> },
    { kunci: 'status', label: 'Status', isi: (e) => <Status status={e.status} /> },
    { kunci: 'progres', label: 'Kemajuan', rata: 'kanan', isi: (e) => <span className="tabular-nums">{e.progress_pct || 0}%</span> },
    { kunci: 'nilai', label: 'Nilai', rata: 'kanan', isi: (e) => (e.quiz_score != null
      ? <span className={`font-semibold tabular-nums ${e.passed ? 'text-[hsl(var(--success-text))]' : 'text-[hsl(var(--danger-text))]'}`}>{e.quiz_score}</span>
      : <span className="text-muted-foreground">—</span>) },
    { kunci: 'sertifikat', label: 'Sertifikat', isi: (e) => <span className="text-sm">{e.certificate_issued ? e.certificate_no : '—'}</span> },
    { kunci: 'terdaftar', label: 'Terdaftar', isi: (e) => <span className="text-sm md:whitespace-nowrap">{fmtDate(e.enrolled_at)}</span> },
  ];
  return (
    <IsiTab tools={alat}
      footer={total > 20 ? <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={20} onPageChange={setPage} /> : null}>
      <TabelData kolom={kolom} baris={paged} kunci={(e) => e.enrollment_id} testId="lms-enrollments"
        kosong={<EmptyState title="Belum ada pendaftaran" description="Karyawan yang didaftarkan ke kursus akan tampil di sini." />} />
    </IsiTab>
  );
}

// ─── Main Component ──────────────────────────────────────────────────────────
export default function HRLMSModule({ token }) {
  const [tab, setTab] = useState('courses'); // courses | enrollments | analytics
  const [courses, setCourses] = useState([]);
  const [enrollments, setEnrollments] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [q, setQ] = useState('');
  const [filterCat, setFilterCat] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [selected, setSelected] = useState(null); // course detail
  const [materi, setMateri] = useState(null);     // materi kursus terpilih (GET /courses/{id})
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(KOSONG);
  const [saving, setSaving] = useState(false);
  const [seeding, setSeeding] = useState(false);

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);

  const fetchAll = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [cs, es, aRes] = await Promise.all([
        ambilSemua('/courses', 'courses', headers),
        ambilSemua('/enrollments', 'enrollments', headers),
        API(`/analytics`, { headers }),
      ]);
      setCourses(cs);
      setEnrollments(es);
      setAnalytics(aRes.ok ? await aRes.json() : null);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, [headers]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // Materi kursus hanya dibawa oleh GET /courses/{id}
  useEffect(() => {
    if (!selected) { setMateri(null); return; }
    let batal = false;
    (async () => {
      try {
        const r = await API(`/courses/${selected.course_id}`, { headers });
        const d = r.ok ? await r.json() : null;
        if (!batal) setMateri(d?.course?.materials || []);
      } catch { if (!batal) setMateri([]); }
    })();
    return () => { batal = true; };
  }, [selected, headers]);

  const handleSeed = async () => {
    // Tahap 5 (2026-11-07): data contoh dulu MENGHAPUS semua kursus/materi/peserta; kini hanya ke data kosong
    if (!(await confirmDialog({ title: 'Muat data contoh pembelajaran?', body: 'Hanya bisa bila belum ada kursus.', confirmLabel: 'Muat contoh' }))) return;
    setSeeding(true);
    const r = await API(`/seed`, { method: 'POST', headers });
    if (!r.ok) { const d = await r.json().catch(() => ({})); toast.error(typeof d.detail === 'string' ? d.detail : 'Gagal memuat contoh'); }
    setSeeding(false);
    fetchAll();
  };

  const openForm = (c = null) => {
    setEditing(c);
    setForm(c ? { title: c.title, description: c.description, category: c.category, level: c.level,
      duration_hours: c.duration_hours, instructor: c.instructor, pass_score: c.pass_score, status: c.status }
      : KOSONG);
    setShowForm(true);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const r = editing
        ? await API(`/courses/${editing.course_id}`, { method: 'PUT', headers, body: JSON.stringify(form) })
        : await API(`/courses`, { method: 'POST', headers, body: JSON.stringify(form) });
      // 2026-11-06 (pola P6): dulu form ditutup walau server menolak, tanpa pesan apa pun
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        toast.error(typeof d.detail === 'string' ? d.detail : 'Gagal menyimpan kursus');
        return;
      }
      setShowForm(false);
      fetchAll();
    } catch {} finally { setSaving(false); }
  };

  const handleDelete = async (cid) => {
    if (!(await confirmDialog({ title: 'Yakin hapus kursus ini?', danger: true, confirmLabel: 'Hapus' }))) return;
    const r = await API(`/courses/${cid}`, { method: 'DELETE', headers });
    if (!r.ok) { toast.error('Gagal menghapus kursus'); return; }  // 2026-11-06 (pola P6): dulu penolakan diam
    fetchAll();
    if (selected?.course_id === cid) setSelected(null);
  };

  // Peserta & selesai per kursus dihitung dari pendaftaran (bukan penghitung tersimpan).
  const hitungKursus = useMemo(() => {
    const m = {};
    enrollments.forEach((e) => {
      const k = m[e.course_id] || (m[e.course_id] = { peserta: 0, selesai: 0 });
      k.peserta += 1;
      if (e.status === 'completed') k.selesai += 1;
    });
    return m;
  }, [enrollments]);
  const peserta = (c) => hitungKursus[c.course_id]?.peserta || 0;
  const selesai = (c) => hitungKursus[c.course_id]?.selesai || 0;
  const persenSelesai = (c) => (peserta(c) ? Math.round((selesai(c) / peserta(c)) * 100) : null);

  const filtered = useMemo(() => courses.filter(c => {
    if (filterCat && c.category !== filterCat) return false;
    if (filterStatus && c.status !== filterStatus) return false;
    if (q && !(c.title || '').toLowerCase().includes(q.toLowerCase()) && !(c.description || '').toLowerCase().includes(q.toLowerCase())) return false;
    return true;
  }), [courses, q, filterCat, filterStatus]);

  const categories = useMemo(() => [...new Set(courses.map(c => c.category).filter(Boolean))], [courses]);

  const perKategori = useMemo(() => categories.map((cat) => {
    const cs = courses.filter((c) => c.category === cat);
    return { kategori: cat, kursus: cs.length, peserta: cs.reduce((a, c) => a + peserta(c), 0), selesai: cs.reduce((a, c) => a + selesai(c), 0) };
  }).sort((a, b) => b.kursus - a.kursus), [categories, courses, hitungKursus]); // eslint-disable-line react-hooks/exhaustive-deps
  const palingDiminati = useMemo(() => [...courses].filter((c) => peserta(c) > 0)
    .sort((a, b) => peserta(b) - peserta(a)).slice(0, 5), [courses, hitungKursus]); // eslint-disable-line react-hooks/exhaustive-deps

  const muatUlang = (
    <Button variant="outline" size="icon" onClick={fetchAll} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
      <RefreshCw className={loading ? 'animate-spin' : ''} />
    </Button>
  );
  const aksiHalaman = (
    <>
      <Button variant="outline" onClick={handleSeed} disabled={seeding} data-testid="lms-seed-btn">
        {seeding ? 'Memuat…' : 'Muat contoh'}
      </Button>
      <Button onClick={() => openForm()} data-testid="lms-add-btn"><Plus />Kursus baru</Button>
    </>
  );

  const kolomKursus = [
    { kunci: 'judul', label: 'Kursus', hp: 'judul', isi: (c) => (
      <div className="min-w-0 md:max-w-[22rem]" data-testid={`course-card-${c.course_id}`}>
        <p className="truncate font-medium text-foreground" title={c.title}>{c.title}</p>
        {c.description && <p className="hidden truncate text-xs text-muted-foreground md:block" title={c.description}>{c.description}</p>}
      </div>) },
    { kunci: 'kategori', label: 'Kategori', isi: (c) => <span className="text-sm">{c.category || '—'}</span> },
    { kunci: 'tingkat', label: 'Tingkat', isi: (c) => <span className="text-sm">{labelLevel(c.level)}</span> },
    { kunci: 'durasi', label: 'Durasi', rata: 'kanan', isi: (c) => <span className="tabular-nums">{c.duration_hours ?? '—'} jam</span> },
    { kunci: 'peserta', label: 'Peserta', rata: 'kanan', isi: (c) => <span className="tabular-nums">{peserta(c)}</span> },
    { kunci: 'selesai', label: 'Selesai', rata: 'kanan', isi: (c) => (
      <span className="tabular-nums">{selesai(c)}{persenSelesai(c) != null && <span className="text-muted-foreground"> ({persenSelesai(c)}%)</span>}</span>) },
    { kunci: 'status', label: 'Status', isi: (c) => <Status status={c.status} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (c) => (
      <Button size="sm" variant="outline" onClick={() => openForm(c)} data-testid={`lms-edit-${c.course_id}`}><Pencil />Ubah</Button>) },
  ];
  const kolomUnduhKursus = [
    { label: 'Kursus', nilai: (c) => c.title },
    { label: 'Deskripsi', nilai: (c) => c.description || '' },
    { label: 'Kategori', nilai: (c) => c.category || '' },
    { label: 'Tingkat', nilai: (c) => labelLevel(c.level) },
    { label: 'Durasi (jam)', nilai: (c) => c.duration_hours ?? '' },
    { label: 'Nilai lulus (%)', nilai: (c) => c.pass_score ?? '' },
    { label: 'Instruktur', nilai: (c) => c.instructor || '' },
    { label: 'Peserta', nilai: (c) => peserta(c) },
    { label: 'Selesai', nilai: (c) => selesai(c) },
    { label: 'Status', nilai: (c) => labelStatus(c.status) },
  ];

  const galat = error && <Notice tone="danger" title="Gagal memuat data pembelajaran">{error}</Notice>;
  const memuat = loading && courses.length === 0;

  // ─── Tab: kursus ───
  const tabKursus = (
    <>
      {galat}
      {memuat ? <p className="py-6 text-center text-sm text-muted-foreground">Memuat kursus…</p> : (
        <TabelData kolom={kolomKursus} baris={filtered} kunci={(c) => c.course_id} onKlikBaris={setSelected} testId="lms-courses"
          kosong={<EmptyState title={courses.length ? 'Tidak ada kursus yang cocok' : 'Belum ada kursus'}
            description={courses.length ? 'Ubah saringan atau kata pencarian.' : 'Klik "Kursus baru", atau "Muat contoh" untuk melihat contoh.'} />} />
      )}
    </>
  );

  // ─── Tab: analitik ───
  const s = analytics?.summary || {};
  const tabAnalitik = (
    <div className="space-y-4">
      {galat}
      {analytics ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Kursus" value={s.total_courses ?? 0} sub={`${s.active_courses ?? 0} aktif`} />
          <StatTile label="Pendaftaran" value={s.total_enrollments ?? 0} sub={`${s.in_progress ?? 0} sedang berjalan`} />
          <StatTile label="Selesai" value={s.completed ?? 0}
            sub={s.total_enrollments ? `${s.completion_rate ?? 0}% dari semua pendaftaran` : 'Belum ada pendaftaran'} />
          <StatTile label="Sertifikat terbit" value={s.certificates_issued ?? 0} sub="Peserta yang lulus nilai minimum." />
        </div>
      ) : !loading && <p className="text-sm text-muted-foreground">Ringkasan tidak dapat dimuat.</p>}

      <section className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-base font-semibold text-foreground">Per kategori</p>
          <TombolUnduh namaBerkas="pembelajaran-per-kategori" namaLembar="Per kategori" baris={perKategori}
            kolom={[{ label: 'Kategori', nilai: (r) => r.kategori }, { label: 'Kursus', nilai: (r) => r.kursus },
              { label: 'Peserta', nilai: (r) => r.peserta }, { label: 'Selesai', nilai: (r) => r.selesai }]} />
        </div>
        <TabelData baris={perKategori} kunci={(r) => r.kategori} testId="lms-per-kategori"
          kolom={[
            { kunci: 'kategori', label: 'Kategori', hp: 'judul' },
            { kunci: 'kursus', label: 'Kursus', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.kursus}</span> },
            { kunci: 'peserta', label: 'Peserta', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.peserta}</span> },
            { kunci: 'selesai', label: 'Selesai', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.selesai}</span> },
          ]}
          kosong={<EmptyState title="Belum ada kursus" description="Kategori muncul setelah kursus dibuat." />} />
      </section>

      <section className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-base font-semibold text-foreground">Kursus paling banyak peserta</p>
          <TombolUnduh namaBerkas="kursus-paling-diminati" namaLembar="Paling diminati" baris={palingDiminati}
            kolom={[{ label: 'Kursus', nilai: (c) => c.title }, { label: 'Kategori', nilai: (c) => c.category || '' },
              { label: 'Peserta', nilai: (c) => peserta(c) }, { label: 'Selesai', nilai: (c) => selesai(c) }]} />
        </div>
        <TabelData baris={palingDiminati} kunci={(c) => c.course_id} onKlikBaris={setSelected} testId="lms-top-courses"
          kolom={[
            { kunci: 'judul', label: 'Kursus', hp: 'judul', isi: (c) => <span className="font-medium text-foreground">{c.title}</span> },
            { kunci: 'kategori', label: 'Kategori', isi: (c) => c.category || '—' },
            { kunci: 'peserta', label: 'Peserta', rata: 'kanan', isi: (c) => <span className="tabular-nums">{peserta(c)}</span> },
            { kunci: 'selesai', label: 'Selesai', rata: 'kanan', isi: (c) => <span className="tabular-nums">{selesai(c)}</span> },
          ]}
          kosong={<EmptyState title="Belum ada peserta" description="Urutan muncul setelah karyawan didaftarkan ke kursus." />} />
      </section>
    </div>
  );

  return (
    <div data-testid="hr-lms-module">
      <HubTabs hubId="hr-lms" title="Pembelajaran" subtitle="Kursus, materi, dan kemajuan belajar karyawan."
        value={tab} onValueChange={setTab}
        tabs={[
          { key: 'courses', label: `Kursus (${courses.length})`, Component: IsiTab, props: {
            actions: aksiHalaman,
            filters: <>
              <div className="relative w-full sm:w-64">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari kursus" className="pl-8" data-testid="lms-search" />
              </div>
              <SmartNativeSelect value={filterCat} onChange={(e) => setFilterCat(e.target.value)} className="w-44" data-testid="lms-filter-cat">
                <option value="">Semua kategori</option>
                {categories.map((c) => <option key={c} value={c}>{c}</option>)}
              </SmartNativeSelect>
              <SmartNativeSelect searchable={false} value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} className="w-40">
                <option value="">Semua status</option>
                <option value="active">Aktif</option>
                <option value="draft">Draf</option>
                <option value="archived">Diarsipkan</option>
              </SmartNativeSelect>
            </>,
            tools: <>
              <TombolUnduh namaBerkas="kursus-pembelajaran" namaLembar="Kursus" baris={filtered} kolom={kolomUnduhKursus} testId="lms-unduh-kursus" />
              {muatUlang}
            </>,
            children: tabKursus,
          } },
          { key: 'enrollments', label: `Pendaftaran (${enrollments.length})`, Component: TabelPendaftaran, props: {
            enrollments,
            alat: <>
              <TombolUnduh namaBerkas="pendaftaran-kursus" namaLembar="Pendaftaran" baris={enrollments} testId="lms-unduh-pendaftaran"
                kolom={[
                  { label: 'Karyawan', nilai: (e) => e.employee_name || '' },
                  { label: 'Kursus', nilai: (e) => e.course_title || '' },
                  { label: 'Status', nilai: (e) => labelStatus(e.status) },
                  { label: 'Kemajuan (%)', nilai: (e) => e.progress_pct || 0 },
                  { label: 'Nilai', nilai: (e) => e.quiz_score ?? '' },
                  { label: 'Sertifikat', nilai: (e) => (e.certificate_issued ? e.certificate_no : '') },
                  { label: 'Terdaftar', nilai: (e) => fmtDate(e.enrolled_at) },
                ]} />
              {muatUlang}
            </>,
          } },
          { key: 'analytics', label: 'Analitik', Component: IsiTab, props: { tools: muatUlang, children: tabAnalitik } },
        ]} />

      {/* ─── Detail kursus (popup) ─── */}
      {selected && (
        <DetailPopup open onClose={() => setSelected(null)} judul={selected.title} testId="lms-course-detail"
          keterangan={selected.description} status={<Status status={selected.status} />}
          aksi={<>
            <Button size="sm" variant="outline" onClick={() => { openForm(selected); setSelected(null); }}><Pencil />Ubah</Button>
            <Button size="sm" variant="destructive" onClick={() => handleDelete(selected.course_id)} data-testid="lms-delete-btn"><Trash2 />Hapus</Button>
          </>}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Kategori">{selected.category || '—'}</BarisDetail>
            <BarisDetail label="Tingkat">{labelLevel(selected.level)}</BarisDetail>
            <BarisDetail label="Durasi">{selected.duration_hours ?? '—'} jam</BarisDetail>
            <BarisDetail label="Nilai lulus">{selected.pass_score ?? '—'}%</BarisDetail>
            <BarisDetail label="Instruktur">{selected.instructor || '—'}</BarisDetail>
            <BarisDetail label="Peserta">{peserta(selected)} terdaftar · {selesai(selected)} selesai</BarisDetail>
            {selected.tags?.length > 0 && <BarisDetail label="Label">{selected.tags.join(', ')}</BarisDetail>}
          </dl>
          <div className="space-y-2">
            <p className="text-sm font-medium text-foreground">Materi kursus</p>
            {materi === null ? <p className="text-sm text-muted-foreground">Memuat materi…</p> : (
              <TabelData baris={materi} kunci={(m) => m.material_id} testId="lms-materials"
                kolom={[
                  { kunci: 'judul', label: 'Materi', hp: 'judul', isi: (m) => <span className="font-medium text-foreground">{m.title}</span> },
                  { kunci: 'jenis', label: 'Jenis', isi: (m) => MATERIAL_TYPE[m.type] || 'Teks' },
                  { kunci: 'durasi', label: 'Durasi', rata: 'kanan', isi: (m) => <span className="tabular-nums">{m.duration_minutes ?? '—'} menit</span> },
                ]}
                kosong={<EmptyState title="Kursus ini belum punya materi" />} />
            )}
          </div>
        </DetailPopup>
      )}

      {/* ─── Form kursus (popup) ─── */}
      <FormPopup open={showForm} onClose={() => setShowForm(false)} ukuran="panjang" onSimpan={handleSave} menyimpan={saving}
        bisaSimpan={!!form.title} judul={editing ? 'Ubah kursus' : 'Buat kursus baru'}
        labelSimpan={editing ? 'Simpan' : 'Buat kursus'} testId="lms-form">
        <Isian label="Judul kursus" wajib htmlFor="lms-judul">
          <Input id="lms-judul" value={form.title} onChange={(e) => setForm((p) => ({ ...p, title: e.target.value }))} placeholder="Judul kursus" />
        </Isian>
        <Isian label="Deskripsi" htmlFor="lms-deskripsi">
          <Textarea id="lms-deskripsi" rows={3} value={form.description} onChange={(e) => setForm((p) => ({ ...p, description: e.target.value }))} placeholder="Deskripsi kursus" />
        </Isian>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Kategori" htmlFor="lms-kategori">
            <Input id="lms-kategori" value={form.category} onChange={(e) => setForm((p) => ({ ...p, category: e.target.value }))} placeholder="Contoh: K3, Orientasi" />
          </Isian>
          <Isian label="Tingkat" htmlFor="lms-tingkat">
            <SmartNativeSelect id="lms-tingkat" searchable={false} value={form.level} onChange={(e) => setForm((p) => ({ ...p, level: e.target.value }))}>
              <option value="Beginner">Pemula</option><option value="Intermediate">Menengah</option><option value="Advanced">Lanjutan</option>
            </SmartNativeSelect>
          </Isian>
          <Isian label="Durasi (jam)" htmlFor="lms-durasi">
            <Input id="lms-durasi" type="number" min={1} value={form.duration_hours} onChange={(e) => setForm((p) => ({ ...p, duration_hours: +e.target.value }))} />
          </Isian>
          <Isian label="Nilai lulus (%)" htmlFor="lms-lulus">
            <Input id="lms-lulus" type="number" min={0} max={100} value={form.pass_score} onChange={(e) => setForm((p) => ({ ...p, pass_score: +e.target.value }))} />
          </Isian>
          <Isian label="Instruktur" htmlFor="lms-instruktur">
            <Input id="lms-instruktur" value={form.instructor} onChange={(e) => setForm((p) => ({ ...p, instructor: e.target.value }))} placeholder="Nama instruktur" />
          </Isian>
          <Isian label="Status" htmlFor="lms-status">
            <SmartNativeSelect id="lms-status" searchable={false} value={form.status} onChange={(e) => setForm((p) => ({ ...p, status: e.target.value }))}>
              <option value="draft">Draf</option><option value="active">Aktif</option><option value="archived">Diarsipkan</option>
            </SmartNativeSelect>
          </Isian>
        </div>
      </FormPopup>
    </div>
  );
}

/**
 * MyCourses.jsx — Kursus saya: semua kursus yang diikuti, disaring per status.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout · status = FilterChips (dulu tab) · daftar = tabel standar (kartu ringkas
 * di HP; dulu kartu besar berulang) yang bisa diunduh · bahasa Indonesia. Klik baris membuka rincian kursus seperti dulu.
 */
import { useState, useEffect } from 'react';
import { ArrowRight, BookOpen, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import apiFetch from '@/lib/apiFetch';
import PageLayout from '../../layout/PageLayout';
import { EmptyState, StatusBadge } from '../../moduleAtoms';
import { labelKategori } from './CourseCatalog';

const STATUS_TABS = [
  { value: 'all', label: 'Semua' },
  { value: 'in_progress', label: 'Berjalan' },
  { value: 'completed', label: 'Selesai' },
  { value: 'not_started', label: 'Belum mulai' },
];
const STATUS_META = {
  completed: { label: 'Selesai', tone: 'success' },
  in_progress: { label: 'Berjalan', tone: 'info' },
  not_started: { label: 'Belum mulai', tone: 'muted' },
};
const formatDate = (dateStr) => (dateStr ? new Date(dateStr).toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric' }) : '');

export default function MyCourses({ onNavigate }) {
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('all');
  const [courses, setCourses] = useState([]);

  const fetchMyCourses = async () => {
    try {
      setLoading(true);
      const data = await apiFetch(`/lms/student/my-courses?status=${activeTab}`);
      setCourses(data.courses || []);
    } catch (error) {
      toast.error('Gagal memuat kursus');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { fetchMyCourses(); }, [activeTab]); // eslint-disable-line react-hooks/exhaustive-deps
  const buka = (c) => onNavigate && onNavigate('course-detail', { courseId: c.course_id });

  const kolom = [
    { kunci: 'judul', label: 'Kursus', hp: 'judul', isi: (c) => (
      <div className="min-w-0 md:max-w-[24rem]">
        <p className="font-medium text-foreground">{c.title}</p>
        {c.next_material && <p className="truncate text-xs text-muted-foreground">Berikutnya: {c.next_material.title}</p>}
      </div>) },
    { kunci: 'kategori', label: 'Kategori', hp: 'keterangan', isi: (c) => labelKategori(c.category) },
    { kunci: 'durasi', label: 'Durasi', rata: 'kanan', isi: (c) => <span className="tabular-nums">{c.duration_hours} jam</span> },
    { kunci: 'daftar', label: 'Terdaftar', isi: (c) => <span className="whitespace-nowrap">{formatDate(c.enrolled_at) || '—'}</span> },
    { kunci: 'progres', label: 'Progres', isi: (c) => (c.enrollment_status === 'not_started' ? <span className="text-muted-foreground">—</span> : (
      <div className="min-w-[8rem] space-y-1">
        <Progress value={c.progress_percent} />
        <p className="text-xs text-muted-foreground">{c.progress_percent}% · {c.completed_items}/{c.total_items} materi</p>
      </div>)) },
    { kunci: 'status', label: 'Status', isi: (c) => {
      const m = STATUS_META[c.enrollment_status] || STATUS_META.not_started;
      return (
        <span className="flex flex-col items-start gap-0.5">
          <StatusBadge status={c.enrollment_status} label={m.label} tone={m.tone} />
          {c.enrollment_status === 'completed' && c.last_accessed && <span className="text-xs text-muted-foreground">{formatDate(c.last_accessed)}</span>}
        </span>
      );
    } },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (c) => (
      <Button size="sm" variant={c.enrollment_status === 'completed' ? 'outline' : 'default'} onClick={() => buka(c)}>
        {c.enrollment_status === 'completed' ? 'Lihat sertifikat' : c.enrollment_status === 'not_started' ? 'Mulai belajar' : 'Lanjutkan'}
        {c.enrollment_status !== 'completed' && <ArrowRight />}
      </Button>) },
  ];

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-4 sm:px-6">
        <PageLayout title="Kursus saya" subtitle="Semua kursus yang Anda ikuti beserta kemajuannya."
          filters={<FilterChips value={activeTab} onChange={setActiveTab} hideWhenEmpty={false} ariaLabel="Status kursus"
            options={STATUS_TABS.map((t) => ({ key: t.value, label: t.label }))} />}
          tools={<>
            <TombolUnduh namaBerkas="kursus-saya" namaLembar="Kursus saya" baris={courses} testId="my-courses-unduh"
              kolom={[{ label: 'Kursus', nilai: (c) => c.title }, { label: 'Kategori', nilai: (c) => labelKategori(c.category) },
                { label: 'Durasi (jam)', nilai: (c) => Number(c.duration_hours || 0) }, { label: 'Terdaftar', nilai: (c) => formatDate(c.enrolled_at) },
                { label: 'Progres %', nilai: (c) => Number(c.progress_percent || 0) },
                { label: 'Status', nilai: (c) => (STATUS_META[c.enrollment_status] || STATUS_META.not_started).label }]} />
            <Button variant="outline" size="icon" onClick={fetchMyCourses} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
              <RefreshCw className={loading ? 'animate-spin' : ''} />
            </Button>
          </>}>
          {loading && !courses.length ? (
            <p className="py-10 text-center text-sm text-muted-foreground">Memuat kursus…</p>
          ) : (
            <TabelData kolom={kolom} baris={courses} kunci={(c) => c.course_id} onKlikBaris={buka} testId="my-courses-table"
              kosong={<EmptyState icon={BookOpen}
                title={activeTab !== 'all' ? `Belum ada kursus berstatus ${(STATUS_TABS.find((t) => t.value === activeTab) || {}).label?.toLowerCase()}` : 'Belum ada kursus'}
                action={<Button onClick={() => onNavigate && onNavigate('course-catalog')}>Buka katalog kursus</Button>} />} />
          )}
        </PageLayout>
      </div>
    </div>
  );
}

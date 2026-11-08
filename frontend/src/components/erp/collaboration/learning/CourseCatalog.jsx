/**
 * CourseCatalog.jsx — Katalog kursus: telusuri dan daftar kursus.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout · penyaring satu baris (SmartNativeSelect, dulu kartu penyaring 2 baris)
 * · daftar kursus = tabel standar (kartu ringkas di HP; dulu kartu besar berulang) yang bisa diunduh · bahasa
 * Indonesia. Nilai penyaring yang dikirim ke server tetap sama.
 */
import { useState, useEffect } from 'react';
import { ArrowRight, BookOpen, RefreshCw, Search } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import apiFetch from '@/lib/apiFetch';
import PageLayout from '../../layout/PageLayout';
import { EmptyState, StatusBadge } from '../../moduleAtoms';

// value = nilai yang dikirim ke server (tidak diubah); label = bahasa staf
const CATEGORIES = [
  { value: 'all', label: 'Semua kategori' },
  { value: 'Compliance', label: 'Kepatuhan' },
  { value: 'Technical Skills', label: 'Keterampilan teknis' },
  { value: 'Soft Skills', label: 'Keterampilan kerja' },
  { value: 'Product Knowledge', label: 'Pengetahuan produk' },
];
const LEVELS = [
  { value: 'all', label: 'Semua tingkat' },
  { value: 'Beginner', label: 'Pemula' },
  { value: 'Intermediate', label: 'Menengah' },
  { value: 'Advanced', label: 'Mahir' },
];
const SORT_OPTIONS = [
  { value: 'newest', label: 'Terbaru' },
  { value: 'popular', label: 'Paling diminati' },
  { value: 'rating', label: 'Nilai tertinggi' },
];
export const labelKategori = (v) => (CATEGORIES.find((c) => c.value === v) || { label: v || '—' }).label;
export const labelTingkat = (v) => (LEVELS.find((c) => c.value === v) || { label: v || '—' }).label;

export default function CourseCatalog({ onNavigate }) {
  const [loading, setLoading] = useState(true);
  const [courses, setCourses] = useState([]);
  const [category, setCategory] = useState('all');
  const [level, setLevel] = useState('all');
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState('newest');

  const fetchCourses = async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      if (category !== 'all') params.append('category', category);
      if (level !== 'all') params.append('level', level);
      if (search) params.append('search', search);
      params.append('sort', sort);
      params.append('limit', '50');
      const data = await apiFetch(`/lms/student/catalog?${params.toString()}`);
      setCourses(data?.courses || []);
    } catch (error) {
      toast.error('Gagal memuat katalog kursus');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { fetchCourses(); }, [category, level, search, sort]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleEnroll = async (courseId) => {
    try {
      await apiFetch(`/lms/student/courses/${courseId}/enroll`, { method: 'POST' });
      toast.success('Berhasil mendaftar kursus');
      fetchCourses();
    } catch (error) {
      toast.error('Gagal mendaftar kursus');
    }
  };
  const buka = (c) => onNavigate && onNavigate('course-detail', { courseId: c.course_id });

  const kolom = [
    { kunci: 'judul', label: 'Kursus', hp: 'judul', isi: (c) => (
      <div className="min-w-0 md:max-w-[26rem]">
        <p className="font-medium text-foreground">{c.title}</p>
        <p className="line-clamp-2 text-xs text-muted-foreground">{c.description}</p>
      </div>) },
    { kunci: 'kategori', label: 'Kategori', hp: 'keterangan', isi: (c) => labelKategori(c.category) },
    { kunci: 'tingkat', label: 'Tingkat', isi: (c) => labelTingkat(c.level) },
    { kunci: 'durasi', label: 'Durasi', rata: 'kanan', isi: (c) => <span className="tabular-nums">{c.duration_hours} jam</span> },
    { kunci: 'peserta', label: 'Peserta', rata: 'kanan', isi: (c) => <span className="tabular-nums">{c.enrollment_count || 0}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (c) => (c.is_enrolled ? (
      <span className="inline-flex items-center gap-2">
        <StatusBadge status="terdaftar" label="Terdaftar" tone="success" />
        <Button size="sm" variant="outline" onClick={() => buka(c)}>Lanjutkan<ArrowRight /></Button>
      </span>
    ) : (
      <Button size="sm" onClick={() => handleEnroll(c.course_id)}>Daftar</Button>
    )) },
  ];

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-4 sm:px-6">
        <PageLayout title="Katalog kursus" subtitle="Telusuri pelatihan yang tersedia dan daftar untuk meningkatkan keterampilan."
          filters={<>
            <div className="relative w-full sm:w-64">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input placeholder="Cari kursus" value={search} onChange={(e) => setSearch(e.target.value)} className="pl-8" />
            </div>
            <SmartNativeSelect value={category} onChange={(e) => setCategory(e.target.value)} searchable={false}
              className="h-9 w-48" wrapperClassName="w-48" aria-label="Kategori">
              {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </SmartNativeSelect>
            <SmartNativeSelect value={level} onChange={(e) => setLevel(e.target.value)} searchable={false}
              className="h-9 w-40" wrapperClassName="w-40" aria-label="Tingkat">
              {LEVELS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </SmartNativeSelect>
            <SmartNativeSelect value={sort} onChange={(e) => setSort(e.target.value)} searchable={false}
              className="h-9 w-40" wrapperClassName="w-40" aria-label="Urutkan">
              {SORT_OPTIONS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </SmartNativeSelect>
          </>}
          tools={<>
            <TombolUnduh namaBerkas="katalog-kursus" namaLembar="Kursus" baris={courses} testId="catalog-unduh"
              kolom={[{ label: 'Kursus', nilai: (c) => c.title }, { label: 'Kategori', nilai: (c) => labelKategori(c.category) },
                { label: 'Tingkat', nilai: (c) => labelTingkat(c.level) }, { label: 'Durasi (jam)', nilai: (c) => Number(c.duration_hours || 0) },
                { label: 'Peserta', nilai: (c) => Number(c.enrollment_count || 0) }, { label: 'Terdaftar', nilai: (c) => (c.is_enrolled ? 'Ya' : 'Tidak') }]} />
            <Button variant="outline" size="icon" onClick={fetchCourses} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
              <RefreshCw className={loading ? 'animate-spin' : ''} />
            </Button>
          </>}>
          {loading && !courses.length ? (
            <p className="py-10 text-center text-sm text-muted-foreground">Memuat kursus…</p>
          ) : (
            <TabelData kolom={kolom} baris={courses} kunci={(c) => c.course_id} onKlikBaris={buka} testId="catalog-table"
              kosong={<EmptyState icon={BookOpen} title="Tidak ada kursus" description="Ubah kata pencarian atau penyaring." />} />
          )}
        </PageLayout>
      </div>
    </div>
  );
}

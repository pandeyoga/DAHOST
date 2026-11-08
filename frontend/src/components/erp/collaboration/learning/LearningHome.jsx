/**
 * LearningHome.jsx — Beranda belajar (Portal Kolaborasi).
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout · 4 kartu StatTile · kursus berjalan = tabel standar (bisa diunduh) ·
 * tiga kartu "aksi cepat" besar diganti tombol di kepala halaman · bahasa Indonesia, tanpa emoji.
 * Perbaikan angka: kartu "Completed" dulu memakai jumlah SERTIFIKAT (sama persis dengan kartu "Certificates").
 * Kini: kursus diikuti (total_courses_enrolled) dan sertifikat — keduanya dari /lms/student/certificates.
 */
import { useState, useEffect } from 'react';
import { ArrowRight, Award, BookOpen, ChevronDown, Library, RefreshCw } from 'lucide-react';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import apiFetch from '@/lib/apiFetch';
import PageLayout from '../../layout/PageLayout';
import { EmptyState, StatTile } from '../../moduleAtoms';
import ActivityFeed from './ActivityFeed';

const angka = (n) => Number(n || 0).toLocaleString('id-ID');

export default function LearningHome({ onNavigate }) {
  const [loading, setLoading] = useState(true);
  const [activeCourses, setActiveCourses] = useState([]);
  const [stats, setStats] = useState({ totalEnrolled: 0, inProgress: 0, certificates: 0, learningHours: 0 });

  const fetchDashboardData = async () => {
    try {
      setLoading(true);
      const data = await apiFetch('/lms/student/my-courses?status=in_progress');
      setActiveCourses(data.courses || []);
      const certData = await apiFetch('/lms/student/certificates');
      setStats({
        totalEnrolled: certData.stats?.total_courses_enrolled || 0,
        inProgress: data.courses?.length || 0,
        certificates: certData.stats?.total_certificates || 0,
        learningHours: certData.stats?.total_learning_hours || 0,
      });
    } catch (error) {
      toast.error('Gagal memuat beranda belajar');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { fetchDashboardData(); }, []);
  const ke = (v, opt) => onNavigate && onNavigate(v, opt);

  const kolom = [
    { kunci: 'judul', label: 'Kursus', hp: 'judul', isi: (c) => (
      <div className="min-w-0 md:max-w-[24rem]">
        <p className="font-medium text-foreground">{c.title}</p>
        {c.next_material && <p className="truncate text-xs text-muted-foreground">Berikutnya: {c.next_material.title}</p>}
      </div>) },
    { kunci: 'kategori', label: 'Kategori', hp: 'keterangan', isi: (c) => c.category || '—' },
    { kunci: 'progres', label: 'Progres', isi: (c) => (
      <div className="min-w-[8rem] space-y-1">
        <Progress value={c.progress_percent} />
        <p className="text-xs text-muted-foreground">{c.progress_percent}% · {c.completed_items}/{c.total_items} materi</p>
      </div>) },
  ];

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-4 sm:px-6">
        <PageLayout title="Beranda belajar" subtitle="Ringkasan kursus yang sedang Anda ikuti, sertifikat, dan aktivitas terbaru."
          actions={<>
            <DropdownMenu>
              <DropdownMenuTrigger asChild><Button variant="outline">Buka<ChevronDown /></Button></DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => ke('course-catalog')}><Library className="mr-2 h-4 w-4" />Katalog kursus</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => ke('my-courses')}><BookOpen className="mr-2 h-4 w-4" />Kursus saya</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => ke('certificates')}><Award className="mr-2 h-4 w-4" />Sertifikat</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </>}
          tools={<>

            <Button variant="outline" size="icon" onClick={fetchDashboardData} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
              <RefreshCw className={loading ? 'animate-spin' : ''} />
            </Button>
          </>}
          summary={
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <StatTile label="Sedang berjalan" value={loading ? '—' : angka(stats.inProgress)} sub="Kursus yang belum selesai" />
              <StatTile label="Kursus diikuti" value={loading ? '—' : angka(stats.totalEnrolled)} sub="Semua kursus yang Anda daftar" />
              <StatTile label="Sertifikat" value={loading ? '—' : angka(stats.certificates)} sub="Kursus selesai dengan sertifikat" />
              <StatTile label="Jam belajar" value={loading ? '—' : angka(stats.learningHours)} sub="Total durasi kursus yang selesai" />
            </div>
          }>
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <p className="text-base font-semibold text-foreground">Kursus berjalan</p>
              <div className="flex items-center gap-2">
                <TombolUnduh namaBerkas="kursus-berjalan" namaLembar="Kursus berjalan" baris={activeCourses} testId="learning-home-unduh"
              kolom={[{ label: 'Kursus', nilai: (c) => c.title }, { label: 'Kategori', nilai: (c) => c.category || '' },
                { label: 'Progres %', nilai: (c) => Number(c.progress_percent || 0) },
                { label: 'Materi selesai', nilai: (c) => Number(c.completed_items || 0) }, { label: 'Total materi', nilai: (c) => Number(c.total_items || 0) }]} />
                {activeCourses.length > 3 && (
                  <Button variant="ghost" size="sm" onClick={() => ke('my-courses')}>Lihat semua<ArrowRight /></Button>
                )}
              </div>
            </div>
            <TabelData kolom={kolom} baris={activeCourses.slice(0, 3)} kunci={(c) => c.course_id}
              onKlikBaris={(c) => ke('course-detail', { courseId: c.course_id })} testId="learning-home-courses"
              kosong={<EmptyState icon={BookOpen} className="py-8" title={loading ? 'Memuat kursus…' : 'Belum ada kursus yang sedang berjalan'}
                description={loading ? undefined : 'Pilih kursus dari katalog untuk mulai belajar.'}
                action={!loading && <Button onClick={() => ke('course-catalog')}>Buka katalog kursus</Button>} />} />
          </div>
          <ActivityFeed onNavigate={onNavigate} />
        </PageLayout>
      </div>
    </div>
  );
}

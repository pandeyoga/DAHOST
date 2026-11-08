/**
 * StudyGroups.jsx
 * Phase 3.8: Study Groups - Social Learning Component
 * List study groups + create new group + navigate to detail
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, daftar = tabel standar (dulu kartu berulang) yang bisa diunduh,
 * buat kelompok = FormPopup pendek (dulu Dialog), bahasa Indonesia.
 */

import { useState, useEffect } from 'react';
import { ArrowRight, Plus, RefreshCw, Users } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Skeleton } from '@/components/ui/skeleton';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import PageLayout from '../../layout/PageLayout';
import { EmptyState, StatusBadge } from '../../moduleAtoms';
import { toast } from 'sonner';
import apiFetch from '@/lib/apiFetch';

export default function StudyGroups({ onNavigate }) {
  const [loading, setLoading] = useState(true);
  const [groups, setGroups] = useState([]);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [courses, setCourses] = useState([]);
  
  // Form state
  const [formData, setFormData] = useState({
    name: '',
    course_id: '',
    description: '',
  });
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetchStudyGroups();
    fetchEnrolledCourses();
  }, []);

  const fetchStudyGroups = async () => {
    try {
      setLoading(true);
      const data = await apiFetch('/collab/study-groups');
      setGroups(data.study_groups || []);
    } catch (error) {
      console.error('Error fetching study groups:', error);
      toast.error('Gagal memuat kelompok belajar');
    } finally {
      setLoading(false);
    }
  };

  const fetchEnrolledCourses = async () => {
    try {
      const data = await apiFetch('/lms/student/my-courses?status=all');
      setCourses(data.courses || []);
    } catch (error) {
      console.error('Error fetching courses:', error);
    }
  };

  const handleCreateGroup = async () => {
    if (!formData.name.trim()) {
      toast.error('Nama kelompok wajib diisi');
      return;
    }
    if (!formData.course_id) {
      toast.error('Pilih kursus terlebih dahulu');
      return;
    }

    try {
      setSubmitting(true);
      const payload = {
        name: formData.name.trim(),
        course_id: formData.course_id,
        description: formData.description.trim(),
        member_ids: [], // Initial empty, creator will be added automatically
      };

      const data = await apiFetch('/collab/study-groups', {
        method: 'POST',
        body: JSON.stringify(payload),
      });

      toast.success(`Kelompok belajar "${data.study_group.name}" dibuat`);
      setCreateDialogOpen(false);
      resetForm();
      fetchStudyGroups(); // Refresh list
    } catch (error) {
      console.error('Error creating study group:', error);
      toast.error(error.message || 'Gagal membuat kelompok belajar');
    } finally {
      setSubmitting(false);
    }
  };

  const resetForm = () => {
    setFormData({
      name: '',
      course_id: '',
      description: '',
    });
  };

  const formatRelativeTime = (isoDate) => {
    if (!isoDate) return 'Tidak ada aktivitas';
    const date = new Date(isoDate);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'Baru saja';
    if (diffMins < 60) return `${diffMins} menit lalu`;
    if (diffHours < 24) return `${diffHours} jam lalu`;
    if (diffDays < 7) return `${diffDays} hari lalu`;
    return date.toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric' });
  };

  const kolom = [
    { kunci: 'nama', label: 'Kelompok', hp: 'judul', isi: (g) => (
      <div className="min-w-0 md:max-w-[22rem]" data-testid={`study-group-card-${g.id}`}>
        <p className="font-medium text-foreground">{g.name}</p>
        {g.description && <p className="truncate text-xs text-muted-foreground">{g.description}</p>}
      </div>) },
    { kunci: 'kursus', label: 'Kursus', hp: 'keterangan', isi: (g) => g.course?.title || '—' },
    { kunci: 'anggota', label: 'Anggota', rata: 'kanan', isi: (g) => <span className="tabular-nums">{g.member_count || 0}</span> },
    { kunci: 'aktivitas', label: 'Aktivitas terakhir', isi: (g) => (
      <span className="inline-flex items-center gap-2 whitespace-nowrap">
        {g.last_activity_at && <StatusBadge status="aktif" label="Aktif" tone="success" />}
        <span className="text-muted-foreground">{formatRelativeTime(g.last_activity_at || g.created_at)}</span>
      </span>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (g) => (
      <Button variant="outline" size="sm" onClick={() => onNavigate('study-group-detail', { groupId: g.id })}>Buka<ArrowRight /></Button>) },
  ];

  return (
    <div className="h-full overflow-y-auto" data-testid="study-groups-view">
      <div className="p-4 sm:px-6">
        <PageLayout title="Kelompok belajar" subtitle="Belajar bersama rekan di kursus yang sama, dengan kanal diskusi dan folder dokumen."
          actions={<Button onClick={() => setCreateDialogOpen(true)} data-testid="create-study-group-btn"><Plus />Buat kelompok belajar</Button>}
          tools={<>
            <TombolUnduh namaBerkas="kelompok-belajar" namaLembar="Kelompok belajar" baris={groups} testId="study-groups-unduh"
              kolom={[{ label: 'Kelompok', nilai: (g) => g.name }, { label: 'Kursus', nilai: (g) => g.course?.title || '' },
                { label: 'Anggota', nilai: (g) => Number(g.member_count || 0) }, { label: 'Deskripsi', nilai: (g) => g.description || '' },
                { label: 'Aktivitas terakhir', nilai: (g) => formatRelativeTime(g.last_activity_at || g.created_at) }]} />
            <Button variant="outline" size="icon" onClick={fetchStudyGroups} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
              <RefreshCw className={loading ? 'animate-spin' : ''} />
            </Button>
          </>}>
          {loading && !groups.length ? (
            <div className="space-y-2">{[1, 2, 3].map((i) => <Skeleton key={i} className="h-10 w-full" />)}</div>
          ) : (
            <TabelData kolom={kolom} baris={groups} onKlikBaris={(g) => onNavigate('study-group-detail', { groupId: g.id })} testId="study-groups-grid"
              kosong={<EmptyState icon={Users} title="Belum ada kelompok belajar"
                description="Buat kelompok untuk belajar bersama rekan di kursus yang sama; kanal diskusi dan folder dokumen dibuat otomatis."
                action={<Button onClick={() => setCreateDialogOpen(true)}><Plus />Buat kelompok belajar pertama</Button>} />} />
          )}
        </PageLayout>
      </div>

      <FormPopup open={createDialogOpen} onClose={() => { setCreateDialogOpen(false); resetForm(); }} ukuran="pendek"
        judul="Kelompok belajar baru" keterangan="Kanal diskusi pribadi untuk anggota dan folder dokumen bersama dibuat otomatis."
        onSimpan={handleCreateGroup} menyimpan={submitting} labelSimpan="Buat kelompok" testId="create-study-group-dialog">
        <Isian label="Nama kelompok" wajib htmlFor="group-name">
          <Input id="group-name" data-testid="group-name-input" placeholder="Mis. Pelatihan K3 kelompok A"
            value={formData.name} onChange={(e) => setFormData({ ...formData, name: e.target.value })} />
        </Isian>
        <Isian label="Kursus" wajib petunjuk="Hanya peserta kursus ini yang bisa ditambahkan sebagai anggota.">
          <SmartNativeSelect value={formData.course_id} onChange={(e) => setFormData({ ...formData, course_id: e.target.value })}
            className="h-9 w-full" aria-label="Kursus" data-testid="course-select">
            <option value="">— Pilih kursus —</option>
            {courses.map((c) => <option key={c.course_id} value={c.course_id}>{c.title}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Deskripsi" petunjuk="Opsional." htmlFor="group-desc">
          <Textarea id="group-desc" data-testid="group-description-input" placeholder="Tujuan kelompok belajar ini"
            value={formData.description} onChange={(e) => setFormData({ ...formData, description: e.target.value })} rows={3} />
        </Isian>
      </FormPopup>
    </div>
  );
}

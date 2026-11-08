/**
 * Pelatihan host live (Live Selling › Host live › Pelatihan).
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, daftar kartu → tabel + unduh, deskripsi lengkap di popup detail
 * (Ubah/Hapus/Tugaskan juga ada di sana), label Indonesia (dulu "Add Training", "Assign to Hosts", "Required").
 * Permintaan ke server sama.
 */
import { useState, useEffect, useCallback } from 'react';
import { TrendingUp, Plus, Edit, Trash2, RefreshCw, UserCheck } from 'lucide-react';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { Button } from '@/components/ui/button';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { toast } from 'sonner';
import PageLayout from '../../layout/PageLayout';
import { EmptyState, StatusBadge } from '../../moduleAtoms';
import { API } from './utils';
import TrainingModal from './TrainingModal';
import AssignTrainingModal from './AssignTrainingModal';

const KATEGORI = { product_knowledge: 'Pengetahuan produk', platform_rules: 'Aturan platform', engagement: 'Teknik interaksi', sales_techniques: 'Teknik penjualan' };
const JENIS = { video: 'Video', pdf: 'PDF', quiz: 'Kuis', external_link: 'Tautan luar' };

export default function TrainingTab({ authH }) {
  const [trainings, setTrainings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editingTraining, setEditingTraining] = useState(null);
  const [showAssignModal, setShowAssignModal] = useState(false);
  const [selectedTraining, setSelectedTraining] = useState(null);
  const [detail, setDetail] = useState(null);

  const fetchTrainings = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/marketing/livehost/training`, { headers: authH });
      if (res.ok) {
        const data = await res.json();
        setTrainings(data);
      }
    } catch (e) {
      toast.error('Gagal memuat pelatihan');
    } finally {
      setLoading(false);
    }
  }, [authH]);

  useEffect(() => {
    fetchTrainings();
  }, [fetchTrainings]);

  const handleDelete = async (training) => {
    if (!(await confirmDialog({ title: `Hapus pelatihan "${training.title}"?`, confirmLabel: 'Hapus', danger: true }))) return;
    try {
      const res = await fetch(`${API}/api/marketing/livehost/training/${training.id}`, {
        method: 'DELETE',
        headers: authH,
      });
      if (res.ok) {
        toast.success('Pelatihan dihapus.');
        setDetail(null);
        fetchTrainings();
      }
    } catch (e) {
      toast.error('Gagal menghapus pelatihan');
    }
  };

  const { page, setPage, totalPages, total, paged } = useClientPagination(trainings, 10);
  const kategori = (t) => KATEGORI[t.category] || t.category || '—';
  const jenis = (t) => JENIS[t.content_type] || t.content_type || '—';
  const bukaBaru = () => { setEditingTraining(null); setShowModal(true); };
  const ubah = (t) => { setDetail(null); setEditingTraining(t); setShowModal(true); };
  const tugaskan = (t) => { setDetail(null); setSelectedTraining(t); setShowAssignModal(true); };

  const kolom = [
    { kunci: 'judul', label: 'Judul', hp: 'judul', isi: (t) => (
      <span><span className="font-medium">{t.title}</span>
        <span className="block max-w-md truncate text-xs text-muted-foreground">{t.description}</span></span>) },
    { kunci: 'kat', label: 'Kategori', hp: 'keterangan', isi: kategori },
    { kunci: 'jenis', label: 'Jenis materi', isi: jenis },
    { kunci: 'durasi', label: 'Durasi', rata: 'kanan', isi: (t) => <span className="tabular-nums">{t.duration_minutes ? `${t.duration_minutes} menit` : '—'}</span> },
    { kunci: 'wajib', label: 'Wajib', isi: (t) => (t.is_required ? <StatusBadge tone="danger" label="Wajib" /> : <span className="text-muted-foreground">Tidak</span>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (t) => (
      <div className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
        <Button variant="outline" size="sm" onClick={() => tugaskan(t)}><UserCheck />Tugaskan</Button>
        <Button variant="ghost" size="icon-sm" onClick={() => ubah(t)} title="Ubah pelatihan" aria-label="Ubah pelatihan"><Edit /></Button>
        <Button variant="ghost" size="icon-sm" className="text-[hsl(var(--danger-text))]" onClick={() => handleDelete(t)}
          title="Hapus pelatihan" aria-label="Hapus pelatihan"><Trash2 /></Button>
      </div>) },
  ];

  return (
    <PageLayout testId="training-tab" title="Pelatihan host live" subtitle="Materi pelatihan dan penugasannya ke host live."
      actions={<Button onClick={bukaBaru} data-testid="add-training-btn"><Plus />Tambah pelatihan</Button>}
      tools={<>
        <TombolUnduh namaBerkas="pelatihan-host-live" namaLembar="Pelatihan" baris={trainings} testId="training-unduh"
          kolom={[
            { label: 'Judul', nilai: (t) => t.title || '' }, { label: 'Kategori', nilai: kategori }, { label: 'Jenis materi', nilai: jenis },
            { label: 'Durasi (menit)', nilai: (t) => Number(t.duration_minutes) || 0 }, { label: 'Wajib', nilai: (t) => (t.is_required ? 'Ya' : 'Tidak') },
            { label: 'Nilai lulus (%)', nilai: (t) => t.passing_score ?? '' }, { label: 'Masa berlaku (bulan)', nilai: (t) => t.expiry_months ?? '' },
            { label: 'Deskripsi', nilai: (t) => t.description || '' },
          ]} />
        <Button variant="outline" size="icon" onClick={fetchTrainings} title="Muat ulang" aria-label="Muat ulang" data-testid="refresh-trainings">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      footer={trainings.length > 10 && <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />}>
      {loading && trainings.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat pelatihan…</p>
      ) : (
        <TabelData kolom={kolom} baris={paged} testId="trainings-table" onKlikBaris={setDetail}
          kosong={<EmptyState icon={TrendingUp} title="Belum ada pelatihan" description="Tambahkan materi pelatihan untuk host live."
            action={<Button onClick={bukaBaru}><Plus />Tambah pelatihan</Button>} />} />
      )}

      <DetailPopup open={!!detail} onClose={() => setDetail(null)} judul={detail?.title} keterangan={detail && `${kategori(detail)} · ${jenis(detail)}`}
        status={detail?.is_required && <StatusBadge tone="danger" label="Wajib" />} testId="training-detail"
        aksi={detail && <>
          <Button variant="outline" className="text-[hsl(var(--danger-text))]" onClick={() => handleDelete(detail)}><Trash2 />Hapus</Button>
          <Button variant="outline" onClick={() => ubah(detail)}><Edit />Ubah</Button>
          <Button onClick={() => tugaskan(detail)}><UserCheck />Tugaskan ke host</Button>
        </>}>
        {detail && <>
          <BarisDetail label="Durasi">{detail.duration_minutes ? `${detail.duration_minutes} menit` : '—'}</BarisDetail>
          <BarisDetail label="Nilai lulus">{detail.passing_score ? `${detail.passing_score}%` : '—'}</BarisDetail>
          <BarisDetail label="Masa berlaku">{detail.expiry_months ? `${detail.expiry_months} bulan` : '—'}</BarisDetail>
          <div className="mt-3 whitespace-pre-wrap text-sm">{detail.description}</div>
        </>}
      </DetailPopup>

      {showModal && (
        <TrainingModal
          training={editingTraining}
          authH={authH}
          onClose={() => {
            setShowModal(false);
            setEditingTraining(null);
          }}
          onSuccess={() => {
            setShowModal(false);
            setEditingTraining(null);
            fetchTrainings();
          }}
        />
      )}

      {showAssignModal && selectedTraining && (
        <AssignTrainingModal
          training={selectedTraining}
          authH={authH}
          onClose={() => {
            setShowAssignModal(false);
            setSelectedTraining(null);
          }}
          onSuccess={() => {
            setShowAssignModal(false);
            setSelectedTraining(null);
            toast.success('Pelatihan ditugaskan.');
          }}
        />
      )}
    </PageLayout>
  );
}

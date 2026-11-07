/**
 * Certificates.jsx — Sertifikat saya: pencapaian dari kursus yang sudah selesai.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout · 3 kartu StatTile (dulu kartu ikon warna-warni) · sertifikat = tabel
 * standar (dulu kartu bergradasi berulang) yang bisa diunduh · tanpa emoji/huruf kapital semua. Aksi sama:
 * unduh (masih pemberitahuan — PDF belum tersedia di server) dan salin tautan verifikasi.
 */
import { useState, useEffect } from 'react';
import { Award, Download, RefreshCw, Share2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import apiFetch from '@/lib/apiFetch';
import PageLayout from '../../layout/PageLayout';
import { EmptyState, StatTile } from '../../moduleAtoms';

const formatDate = (dateStr) => (dateStr ? new Date(dateStr).toLocaleDateString('id-ID', { day: 'numeric', month: 'long', year: 'numeric' }) : '—');

export default function Certificates({ onNavigate }) {
  const [loading, setLoading] = useState(true);
  const [certificates, setCertificates] = useState([]);
  const [stats, setStats] = useState({ total_certificates: 0, total_courses_enrolled: 0, total_learning_hours: 0 });

  const fetchCertificates = async () => {
    try {
      setLoading(true);
      const data = await apiFetch('/lms/student/certificates');
      setCertificates(data.certificates || []);
      setStats(data.stats || { total_certificates: 0, total_courses_enrolled: 0, total_learning_hours: 0 });
    } catch (error) {
      toast.error('Gagal memuat sertifikat');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { fetchCertificates(); }, []);

  const handleDownload = (cert) => {
    // PDF sertifikat belum dibuat server — hanya pemberitahuan (sama seperti dulu)
    toast.info(`Sertifikat ${cert.verification_code}: berkas PDF belum tersedia`);
  };
  const handleShare = (cert) => {
    const url = `${window.location.origin}/verify/${cert.verification_code}`;
    navigator.clipboard.writeText(url)
      .then(() => toast.success('Tautan verifikasi disalin'))
      .catch(() => toast.error('Gagal menyalin tautan'));
  };

  const kolom = [
    { kunci: 'kursus', label: 'Kursus', hp: 'judul', isi: (c) => (
      <span className="inline-flex items-center gap-2" data-testid={`cert-card-${c.certificate_id}`}>
        <Award className="h-4 w-4 shrink-0 text-primary" /><span className="font-medium">{c.course_title}</span>
      </span>) },
    { kunci: 'terbit', label: 'Terbit', hp: 'keterangan', isi: (c) => formatDate(c.issued_date) },
    { kunci: 'kode', label: 'Kode verifikasi', isi: (c) => <span className="tabular-nums">{c.verification_code}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (c) => (
      <div className="flex justify-end gap-1.5">
        <Button variant="outline" size="sm" onClick={() => handleDownload(c)} data-testid={`cert-download-${c.certificate_id}`}><Download />Unduh</Button>
        <Button variant="outline" size="sm" onClick={() => handleShare(c)} data-testid={`cert-share-${c.certificate_id}`}><Share2 />Bagikan</Button>
      </div>) },
  ];

  return (
    <div className="h-full overflow-y-auto" data-testid="certificates-view">
      <div className="p-4 sm:px-6">
        <PageLayout title="Sertifikat" subtitle="Sertifikat dari kursus yang sudah Anda selesaikan."
          tools={<>
            <TombolUnduh namaBerkas="sertifikat-saya" namaLembar="Sertifikat" baris={certificates} testId="cert-unduh"
              kolom={[{ label: 'Kursus', nilai: (c) => c.course_title }, { label: 'Terbit', nilai: (c) => formatDate(c.issued_date) },
                { label: 'Kode verifikasi', nilai: (c) => c.verification_code }]} />
            <Button variant="outline" size="icon" onClick={fetchCertificates} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
              <RefreshCw className={loading ? 'animate-spin' : ''} />
            </Button>
          </>}
          summary={
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <StatTile label="Sertifikat" value={loading ? '—' : stats.total_certificates} testId="stat-certificates" sub="Kursus yang sudah selesai" />
              <StatTile label="Kursus diikuti" value={loading ? '—' : stats.total_courses_enrolled} testId="stat-enrolled" sub="Semua kursus yang Anda daftar" />
              <StatTile label="Jam belajar" value={loading ? '—' : `${stats.total_learning_hours} jam`} testId="stat-hours" sub="Durasi kursus yang selesai" />
            </div>
          }>
          {loading && !certificates.length ? (
            <p className="py-10 text-center text-sm text-muted-foreground">Memuat sertifikat…</p>
          ) : (
            <TabelData kolom={kolom} baris={certificates} kunci={(c) => c.certificate_id} testId="cert-table"
              kosong={<EmptyState icon={Award} title="Belum ada sertifikat" description="Selesaikan kursus untuk mendapatkan sertifikat."
                action={<Button onClick={() => onNavigate && onNavigate('course-catalog')} data-testid="browse-catalog-btn">Buka katalog kursus</Button>} />} />
          )}
        </PageLayout>
      </div>
    </div>
  );
}

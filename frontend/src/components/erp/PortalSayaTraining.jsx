/**
 * Portal Saya › Training — kursus yang diikuti karyawan, progres, dan sertifikat.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout (dulu judul buatan + `p-6 max-w-3xl`), ringkasan = StatTile (dulu cincin
 * SVG berwarna hex), daftar kursus = TabelData + unduh Excel/CSV, warna token. Angka kartu dihitung dari daftar yang
 * sama (dulu "total" dari server dibandingkan dengan "selesai" dari daftar).
 */
import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { Button } from '@/components/ui/button';
import { Download, Loader2 } from 'lucide-react';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { useToast } from '@/hooks/use-toast';
import { formatDateID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;

const STATUS_CFG = {
  completed: { label: 'Selesai', tone: 'success' },
  enrolled:  { label: 'Sedang belajar', tone: 'info' },
  pending:   { label: 'Belum mulai', tone: 'muted' },
};
const cfg = (s) => STATUS_CFG[s] || STATUS_CFG.pending;

export default function PortalSayaTraining({ user, headers }) {
  const { toast } = useToast();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState({});

  const load = useCallback(async () => {
    try {
      const { data: d } = await axios.get(`${API}/api/portal/training`, { headers });
      setData(d);
    } catch (e) {
      if (e.response?.status === 409) setData({ error: e.response.data.detail });
    } finally {
      setLoading(false);
    }
  }, [headers]);

  useEffect(() => { load(); }, [load]);

  const downloadCertificate = async (item) => {
    const id = item.id;
    setDownloading(p => ({ ...p, [id]: true }));
    try {
      const res = await axios.get(`${API}/api/portal/training/${id}/certificate`, {
        headers,
        responseType: 'blob',
      });
      const url = URL.createObjectURL(new Blob([res.data], { type: 'application/pdf' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = `sertifikat_${item.course_title?.replace(/ /g, '_') || 'kursus'}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
      toast({ title: 'Sertifikat berhasil diunduh.' });
    } catch (e) {
      toast({ title: 'Gagal mengunduh sertifikat.', description: e.response?.data?.detail, variant: 'destructive' });
    } finally {
      setDownloading(p => ({ ...p, [id]: false }));
    }
  };

  const items = data?.items || [];
  const total = items.length;
  const completed = items.filter(i => i.status === 'completed').length;
  const pct = total ? Math.round(completed / total * 100) : 0;

  const kolom = [
    { kunci: 'judul', label: 'Kursus', hp: 'judul', isi: (item) => (
      <div className="min-w-0 md:max-w-[22rem]">
        <p className="font-medium">{item.course_title || '(Kursus tidak ada)'}</p>
        {item.course_category && <p className="text-xs text-muted-foreground">{item.course_category}</p>}
      </div>) },
    { kunci: 'status', label: 'Status', isi: (item) => <StatusBadge status={item.status} label={cfg(item.status).label} tone={cfg(item.status).tone} /> },
    { kunci: 'progres', label: 'Progres', rata: 'kanan', isi: (item) => (
      <span className="tabular-nums">{item.status === 'completed' ? '100%' : item.progress_pct !== undefined ? `${item.progress_pct || 0}%` : '—'}</span>) },
    { kunci: 'selesai', label: 'Selesai pada', isi: (item) => <span className="whitespace-nowrap text-sm">{item.completed_at ? formatDateID(item.completed_at.slice(0, 10)) : '—'}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (item) => (item.status === 'completed' ? (
      <Button size="sm" variant="outline" onClick={() => downloadCertificate(item)} disabled={downloading[item.id]}
        data-testid={`btn-cert-${items.indexOf(item)}`}>
        {downloading[item.id] ? <Loader2 className="animate-spin" /> : <Download />}Sertifikat
      </Button>) : null) },
  ];

  return (
    <PageLayout testId="portal-training" title="Training"
      subtitle={data?.employee ? `${data.employee} — kursus yang Anda ikuti, progres, dan sertifikat.` : 'Kursus yang Anda ikuti, progres, dan sertifikat.'}
      tools={items.length > 0 && (
        <TombolUnduh namaBerkas="training-saya" namaLembar="Training" baris={items} testId="training-unduh" kolom={[
          { label: 'Kursus', nilai: (i) => i.course_title || '' }, { label: 'Kategori', nilai: (i) => i.course_category || '' },
          { label: 'Status', nilai: (i) => cfg(i.status).label },
          { label: 'Progres (%)', nilai: (i) => (i.status === 'completed' ? 100 : (i.progress_pct ?? '')) },
          { label: 'Selesai pada', nilai: (i) => (i.completed_at ? formatDateID(i.completed_at.slice(0, 10)) : '') },
        ]} />
      )}
      summary={!loading && !data?.error && total > 0 && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatTile label="Kursus selesai" value={`${completed} dari ${total}`} sub={`${pct}% selesai`} testId="training-selesai" />
          <StatTile label="Sertifikat tersedia" value={completed} sub="Bisa diunduh dari daftar" testId="training-sertifikat" />
        </div>
      )}>
      {loading ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat training…</p>
      ) : data?.error ? (
        <Notice tone="warning" title="Training belum bisa ditampilkan">{data.error}</Notice>
      ) : (
        <TabelData kolom={kolom} baris={items} kunci={(i) => i.id || i.course_title} testId="training-table"
          kosong={<EmptyState title="Belum terdaftar di training" description="Kursus yang didaftarkan HR untuk Anda akan muncul di sini." />} />
      )}
    </PageLayout>
  );
}

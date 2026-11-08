/**
 * RnDAnalyticsModule — ringkasan angka Portal RnD.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, 4 StatTile berketerangan + satu tabel rincian per keadaan
 * (bisa diunduh). Dulu kartu "Style aktif 0" disorot ungu di bawah "Total style 104" sehingga terbaca
 * "tidak ada style yang hidup", padahal 'active' hanya salah satu status (data uji: 29 disetujui owner,
 * 75 dipromosikan). Rincian status style kini diambil dari daftar style (`/dewi/rnd/styles`, API yang sama
 * dengan Style & Desain); angka lain tetap dari `/dewi/rnd/analytics`.
 */
import { useState, useEffect } from 'react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Skeleton } from '@/components/ui/skeleton';
import { RefreshCw } from 'lucide-react';
import { toast } from '../ui/sonner';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatTile } from './moduleAtoms';
import { STATUS_STYLE } from './RnDStyleDetailPage';

const API = process.env.REACT_APP_BACKEND_URL || '';

export default function RnDAnalyticsModule({ token }) {
  const h = { Authorization: `Bearer ${token}` };
  const [data, setData] = useState(null);
  const [styles, setStyles] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/dewi/rnd/analytics`, { headers: h });
      if (!res.ok) throw new Error();
      setData(await res.json());
    } catch { toast.error('Gagal memuat ringkasan RnD'); }
    try {
      const res = await fetch(`${API}/api/dewi/rnd/styles?limit=1000`, { headers: h });
      if (res.ok) {
        const list = await res.json();
        setStyles(Array.isArray(list) ? list : null);
      }
    } catch { /* rincian status style opsional */ }
    finally { setLoading(false); }
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

  const st = data?.styles || {};
  const sr = data?.sample_requests || {};
  const mt = data?.materials || {};
  const rv = data?.revisions || {};

  // Rincian status style dari daftar style (hanya bila daftarnya lengkap = sama dengan total analitik).
  const perStatus = {};
  (styles || []).forEach((s) => { const k = s.status || 'draft'; perStatus[k] = (perStatus[k] || 0) + 1; });
  const styleLengkap = styles && styles.length === (st.total || 0);
  const labelStyle = (k) => (STATUS_STYLE[k] || { label: k }).label;
  const ringkasStyle = styleLengkap
    ? Object.entries(perStatus).sort((a, b) => b[1] - a[1]).map(([k, n]) => `${n} ${labelStyle(k).toLowerCase()}`).join(' · ')
    : `${st.active ?? 0} berstatus aktif`;

  const sampleLain = Math.max(0, (sr.total || 0) - (sr.pending || 0) - (sr.approved || 0));
  const matLain = Math.max(0, (mt.total || 0) - (mt.active || 0));
  const rincian = [
    ...(styleLengkap
      ? Object.entries(perStatus).sort((a, b) => b[1] - a[1]).map(([k, n]) => ({ id: `style-${k}`, bagian: 'Style', keadaan: labelStyle(k), jumlah: n }))
      : [{ id: 'style-total', bagian: 'Style', keadaan: 'Semua', jumlah: st.total || 0 },
         { id: 'style-active', bagian: 'Style', keadaan: 'Aktif', jumlah: st.active || 0 }]),
    { id: 'sr-pending', bagian: 'Sample request', keadaan: 'Menunggu persetujuan', jumlah: sr.pending || 0 },
    { id: 'sr-approved', bagian: 'Sample request', keadaan: 'Disetujui', jumlah: sr.approved || 0 },
    { id: 'sr-lain', bagian: 'Sample request', keadaan: 'Draf atau ditolak', jumlah: sampleLain },
    { id: 'mt-active', bagian: 'Riset material', keadaan: 'Aktif', jumlah: mt.active || 0 },
    { id: 'mt-lain', bagian: 'Riset material', keadaan: 'Tidak aktif', jumlah: matLain },
    { id: 'rv', bagian: 'Revisi', keadaan: 'Semua', jumlah: rv.total || 0 },
  ];

  return (
    <PageLayout testId="rnd-analytics-module" title="RnD Analytics"
      subtitle="Jumlah style, sample request, riset material, dan revisi di Portal RnD."
      tools={<>
        {data && (
          <TombolUnduh namaBerkas="rnd-analytics" namaLembar="RnD Analytics" baris={rincian} testId="rnd-analytics-unduh"
            kolom={[
              { label: 'Bagian', nilai: (r) => r.bagian },
              { label: 'Keadaan', nilai: (r) => r.keadaan },
              { label: 'Jumlah', nilai: (r) => r.jumlah },
            ]} />
        )}
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="rnd-analytics-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={data && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <StatTile label="Style" value={st.total ?? 0} sub={ringkasStyle} testId="rnd-analytics-styles" />
          <StatTile label="Sample request" value={sr.total ?? 0} accent={sr.pending ? 'warning' : 'default'}
            sub={`${sr.pending ?? 0} menunggu persetujuan · ${sr.approved ?? 0} disetujui`} testId="rnd-analytics-samples" />
          <StatTile label="Riset material" value={mt.total ?? 0} sub={`${mt.active ?? 0} aktif`} testId="rnd-analytics-materials" />
          <StatTile label="Revisi desain" value={rv.total ?? 0} sub="Semua revisi tercatat" testId="rnd-analytics-revisions" />
        </div>
      )}>
      {loading && !data ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24" />)}</div>
      ) : !data ? (
        <GlassCard><EmptyState title="RnD Analytics belum bisa dimuat" description="Tekan muat ulang untuk mencoba lagi." /></GlassCard>
      ) : (
        <GlassCard className="p-0 overflow-hidden">
          <TabelData baris={rincian} testId="rnd-analytics-table"
            kolom={[
              { kunci: 'bagian', label: 'Bagian', hp: 'judul', isi: (r) => <span className="font-medium">{r.bagian}</span> },
              { kunci: 'keadaan', label: 'Keadaan', hp: 'keterangan', isi: (r) => r.keadaan },
              { kunci: 'jumlah', label: 'Jumlah', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.jumlah}</span> },
            ]} />
        </GlassCard>
      )}
    </PageLayout>
  );
}

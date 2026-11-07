/**
 * VendorDashboard — Ringkasan Portal Vendor CMT (juga tab "Ringkasan" di Input atas nama CMT).
 *
 * Standar UI/UX v2 (8 Nov 2026):
 *  • Cetakan PageLayout (di dalam hub judulnya otomatis disembunyikan → tidak ada kepala ganda).
 *  • Kartu angka hanya yang DIKIRIM server (`GET /vendor/dashboard`): job aktif, job selesai, diproduksi / bahan
 *    tersedia, kiriman masuk. Dulu 12 kartu, 8 di antaranya (Material diterima/kurang/cacat, permintaan tambahan &
 *    pengganti, buyer shipments, inspeksi pending, job overdue) membaca kolom yang TIDAK pernah dikirim server
 *    sehingga selalu 0 walau datanya ada — kartu itu disembunyikan (keputusan 9). Angka job lewat tenggat diambil
 *    dari daftar peringatan server.
 *  • Job lewat / mendekati tenggat = satu tabel, bisa diunduh.
 */
import { useEffect, useState } from 'react';
import { Briefcase, Package, RefreshCw, Send, TrendingUp } from 'lucide-react';
import { Button } from '@/components/ui/button';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { formatDateID } from '@/lib/format';
import { apiGet } from '../../../lib/api';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from '../moduleAtoms';

const n = (v) => Number(v || 0).toLocaleString('id-ID');

export default function VendorDashboard({ user, onNavigate }) {
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');

  const load = () => {
    setLoading(true); setErr('');
    apiGet('/vendor/dashboard')
      .then(setMetrics)
      .catch((e) => setErr(e.message || 'Gagal memuat ringkasan'))
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  const overdue = metrics?.alerts?.overdueJobs || [];
  const near = metrics?.alerts?.nearDeadlineJobs || [];
  const perhatian = [
    ...overdue.map((j) => ({ ...j, keadaan: 'lewat' })),
    ...near.map((j) => ({ ...j, keadaan: 'dekat' })),
  ];
  const nilai = (v) => (metrics ? n(v) : '—');

  const kolom = [
    { kunci: 'job', label: 'Job', hp: 'judul', isi: (j) => <span className="font-medium tabular-nums">{j.job_number || '—'}</span> },
    { kunci: 'po', label: 'PO', isi: (j) => <span className="tabular-nums">{j.po_number || '—'}</span> },
    { kunci: 'tenggat', label: 'Tenggat', isi: (j) => formatDateID(j.deadline, { fallback: '—' }) },
    { kunci: 'sisa', label: 'Sisa hari', rata: 'kanan', isi: (j) => <span className="tabular-nums">{j.days_left}</span> },
    { kunci: 'keadaan', label: 'Keadaan', isi: (j) => (j.keadaan === 'lewat'
      ? <StatusBadge status="overdue" tone="danger" label="Lewat tenggat" />
      : <StatusBadge status="near" tone="warning" label="≤ 7 hari lagi" />) },
  ];

  return (
    <PageLayout testId="vendor-dashboard" title="Ringkasan vendor" subtitle={`Ikhtisar produksi ${user?.name || ''}`.trim()}
      actions={onNavigate && <>
        <Button variant="outline" onClick={() => onNavigate('receiving')}><Package className="w-4 h-4" />Penerimaan material</Button>
        <Button variant="outline" onClick={() => onNavigate('production-jobs')}><Briefcase className="w-4 h-4" />Job produksi</Button>
        <Button variant="outline" onClick={() => onNavigate('progress')}><TrendingUp className="w-4 h-4" />Isi progress</Button>
        <Button variant="outline" onClick={() => onNavigate('buyer-shipments')}><Send className="w-4 h-4" />Kirim ke DA</Button>
      </>}
      tools={<Button variant="outline" size="icon" onClick={load} title="Muat ulang" aria-label="Muat ulang">
        <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
      </Button>}
      summary={<>
        {err && <p className="text-sm text-[hsl(var(--danger-text))]" role="alert">{err}</p>}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3" data-testid="vendor-dashboard-tiles">
          <StatTile label="Job produksi aktif" value={nilai(metrics?.activeJobs)} sub="Job induk berstatus berjalan" />
          <StatTile label="Job selesai" value={nilai(metrics?.completedJobs)} sub="Job berstatus selesai" />
          <StatTile label="Diproduksi" value={metrics ? `${n(metrics.totalProduced)} pcs` : '—'}
            sub={metrics ? `${metrics.progressPct || 0}% dari ${n(metrics.totalAvailable)} pcs bahan tersedia` : 'Memuat…'} />
          <StatTile label="Kiriman masuk" value={nilai(metrics?.incomingShipments)} accent={metrics?.incomingShipments > 0 ? 'warning' : 'default'}
            sub="Menunggu dikonfirmasi diterima" />
        </div>
      </>}>
      <section className="space-y-2" data-testid="vendor-dashboard-alerts">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm font-semibold text-foreground">
            Job perlu perhatian {metrics ? `(${overdue.length} lewat tenggat · ${near.length} ≤ 7 hari)` : ''}
          </p>
          <TombolUnduh namaBerkas="job-perlu-perhatian" namaLembar="Job" baris={perhatian} kolom={[
            { label: 'Job', nilai: (j) => j.job_number || '' }, { label: 'PO', nilai: (j) => j.po_number || '' },
            { label: 'Tenggat', nilai: (j) => formatDateID(j.deadline, { fallback: '' }) },
            { label: 'Sisa hari', nilai: (j) => Number(j.days_left) || 0 },
            { label: 'Keadaan', nilai: (j) => (j.keadaan === 'lewat' ? 'Lewat tenggat' : '7 hari lagi atau kurang') },
          ]} />
        </div>
        <TabelData kolom={kolom} baris={perhatian} kunci={(j) => `${j.keadaan}-${j.id}`} testId="vendor-dashboard-alert-table"
          kosong={<EmptyState title={loading ? 'Memuat…' : 'Tidak ada job yang lewat atau mendekati tenggat'}
            description={loading ? '' : 'Job yang tenggatnya lewat atau tinggal 7 hari muncul di sini.'} />} />
      </section>
    </PageLayout>
  );
}

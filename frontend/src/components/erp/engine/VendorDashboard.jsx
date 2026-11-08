/**
 * VendorDashboard — Ringkasan Portal Vendor CMT (juga tab "Ringkasan" di Input atas nama CMT).
 *
 * Standar UI/UX v2 (8 Nov 2026):
 *  • Cetakan PageLayout (di dalam hub judulnya otomatis disembunyikan → tidak ada kepala ganda).
 *  • Kartu angka hanya yang DIKIRIM server (`GET /vendor/dashboard`). 8 kartu (Material diterima/kurang/cacat,
 *    permintaan tambahan & pengganti, kiriman ke DA, inspeksi menunggu, job lewat tenggat) dulu disembunyikan karena
 *    server tidak pernah mengirim angkanya (selalu 0). Sejak 8 Nov 2026 server menghitungnya dengan definisi yang sama
 *    dengan layar asalnya (Inspeksi material, Permintaan material, Kirim ke DA, Penerimaan material) → tampil lagi,
 *    dikelompokkan: ringkasan job (atas), bahan dari DA, permintaan & kiriman.
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
  const pcs = (v) => (metrics ? `${n(v)} pcs` : '—');
  const buka = (modul) => (onNavigate ? () => onNavigate(modul) : undefined);
  const lewat = metrics ? (metrics.overdueJobs ?? overdue.length) : null;

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
        <Button type="button" variant="outline" onClick={() => onNavigate('receiving')}><Package className="w-4 h-4" />Penerimaan material</Button>
        <Button type="button" variant="outline" onClick={() => onNavigate('production-jobs')}><Briefcase className="w-4 h-4" />Job produksi</Button>
        <Button type="button" variant="outline" onClick={() => onNavigate('progress')}><TrendingUp className="w-4 h-4" />Isi progress</Button>
        <Button type="button" variant="outline" onClick={() => onNavigate('buyer-shipments')}><Send className="w-4 h-4" />Kirim ke DA</Button>
      </>}
      tools={<Button type="button" variant="outline" size="icon" onClick={load} title="Muat ulang" aria-label="Muat ulang">
        <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
      </Button>}
      summary={<>
        {err && <p className="text-sm text-[hsl(var(--danger-text))]" role="alert">{err}</p>}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3" data-testid="vendor-dashboard-tiles">
          <StatTile label="Job produksi aktif" value={nilai(metrics?.activeJobs)} sub="Job induk berstatus berjalan" />
          <StatTile label="Job selesai" value={nilai(metrics?.completedJobs)} sub="Job berstatus selesai" />
          <StatTile label="Diproduksi" value={metrics ? `${n(metrics.totalProduced)} pcs` : '—'}
            sub={metrics ? `${metrics.progressPct || 0}% dari ${n(metrics.totalAvailable)} pcs bahan tersedia` : 'Memuat…'} />
          <StatTile label="Job lewat tenggat" value={nilai(lewat)} accent={lewat > 0 ? 'danger' : 'default'}
            sub="Job belum selesai yang melewati tenggat" />
        </div>
      </>}>
      <section className="space-y-2" data-testid="vendor-dashboard-bahan">
        <p className="text-sm font-semibold text-foreground">Bahan dari DA</p>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <StatTile testId="vendor-kpi-kiriman-masuk" label="Kiriman masuk" value={nilai(metrics?.incomingShipments)}
            accent={metrics?.incomingShipments > 0 ? 'warning' : 'default'} sub="Menunggu dikonfirmasi diterima"
            onClick={buka('receiving')} hint="Buka penerimaan material" />
          <StatTile testId="vendor-kpi-inspeksi" label="Menunggu inspeksi" value={nilai(metrics?.pendingInspections)}
            accent={metrics?.pendingInspections > 0 ? 'warning' : 'default'} sub="Sudah diterima, belum diinspeksi"
            onClick={buka('inspeksi')} hint="Buka inspeksi material" />
          <StatTile testId="vendor-kpi-diterima" label="Material diterima" value={pcs(metrics?.totalReceived)}
            sub="Jumlah diterima menurut inspeksi" onClick={buka('inspeksi')} hint="Buka riwayat inspeksi" />
          <StatTile testId="vendor-kpi-kurang" label="Material kurang" value={pcs(metrics?.totalMissing)}
            accent={metrics?.totalMissing > 0 ? 'warning' : 'default'} sub="Kurang dari surat jalan saat inspeksi"
            onClick={buka('inspeksi')} hint="Buka riwayat inspeksi" />
        </div>
      </section>
      <section className="space-y-2" data-testid="vendor-dashboard-permintaan">
        <p className="text-sm font-semibold text-foreground">Permintaan & kiriman</p>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <StatTile testId="vendor-kpi-tambahan" label="Permintaan tambahan" value={nilai(metrics?.pendingAdditional)}
            accent={metrics?.pendingAdditional > 0 ? 'warning' : 'default'} sub="Menunggu persetujuan DA"
            onClick={buka('material-requests')} hint="Buka permintaan material" />
          <StatTile testId="vendor-kpi-pengganti" label="Permintaan pengganti" value={nilai(metrics?.pendingReplacement)}
            accent={metrics?.pendingReplacement > 0 ? 'warning' : 'default'} sub="Menunggu persetujuan DA"
            onClick={buka('material-requests')} hint="Buka permintaan material" />
          <StatTile testId="vendor-kpi-cacat" label="Material cacat" value={pcs(metrics?.totalDefect)}
            accent={metrics?.totalDefect > 0 ? 'danger' : 'default'} sub="Dari laporan cacat material" />
          <StatTile testId="vendor-kpi-kirim-da" label="Kiriman ke DA" value={nilai(metrics?.pendingBuyerShipments)}
            sub="Semua surat jalan vendor ini ke DA" onClick={buka('buyer-shipments')} hint="Buka kirim ke DA" />
        </div>
      </section>
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

/**
 * PayrollDashboardModule — tab "Dasbor" di hub Penggajian.
 *
 * 2026-11-06 (Tahap 2): dulu layar ini jalur run KEDUA — tombol "Jalankan Payroll" membuat run hantu tanpa slip,
 * KPI membaca field hantu (selalu 0), dan "Jadwal Auto-Run" tidak pernah menjalankan apa pun. Semua itu dihapus.
 * Dasbor kini HANYA membaca run gaji sungguhan; run dibuat, dihitung ulang, difinalisasi, dan dibayar di tab
 * Proses Gaji. Cetakan PageLayout (PANDUAN_UI G1).
 *
 * Standar UI/UX v2 (8 Nov 2026): kartu angka diberi keterangan sumbernya (ringkasan run hanya periode tahun ini —
 * `GET /api/payroll/automation/dashboard`), riwayat = TabelData (kartu ringkas di HP) + unduh Excel/CSV.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Info, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatDateID, formatRupiah } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL || '';

const STATUS_LABEL = { draft: 'Draf', finalized: 'Final', cancelled: 'Dibatalkan' };

function payLabel(r) {
  if (r.status !== 'finalized') return '—';
  return r.payment_status === 'paid' ? 'Dibayar' : 'Belum dibayar';
}
const periode = (r) => `${formatDateID(r.period_from)} – ${formatDateID(r.period_to)}`;

export default function PayrollDashboardModule({ token, headers }) {
  const authH = useMemo(() => headers || (token ? { Authorization: `Bearer ${token}` } : {}), [headers, token]);
  const [dashboard, setDashboard] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const get = async (path) => {
        const r = await fetch(`${API}/api/payroll/automation/${path}`, { headers: authH });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      };
      const [d, a, h] = await Promise.all([get('dashboard'), get('alerts'), get('history?limit=12')]);
      setDashboard(d);
      setAlerts(a?.data || []);
      setHistory(h?.data || []);
    } catch (e) {
      toast.error(`Gagal memuat dasbor penggajian: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [authH]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const d = dashboard || {};
  const runSummary = d.run_summary || {};
  const coverage = d.employee_profile_coverage || {};
  const { page, setPage, totalPages, total, paged } = useClientPagination(history, 10);
  const muatAwal = loading && !dashboard;

  const kolom = [
    { kunci: 'run', label: 'Nomor run', hp: 'judul', isi: (r) => <span className="font-medium">{r.run_number}</span> },
    { kunci: 'periode', label: 'Periode', hp: 'keterangan', isi: (r) => <span className="text-sm md:whitespace-nowrap">{periode(r)}</span> },
    { kunci: 'status', label: 'Status', isi: (r) => <StatusBadge status={r.status} label={STATUS_LABEL[r.status]} /> },
    { kunci: 'bayar', label: 'Pembayaran', isi: (r) => <span className="text-sm">{payLabel(r)}</span> },
    { kunci: 'karyawan', label: 'Karyawan', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.total_employees ?? '—'}</span> },
    { kunci: 'bersih', label: 'Gaji bersih', rata: 'kanan', isi: (r) => <span className="tabular-nums">{formatRupiah(r.total_net || 0)}</span> },
    { kunci: 'dibuat', label: 'Dibuat', rata: 'kanan', isi: (r) => <span className="text-sm">{r.created_at ? formatDateID(r.created_at) : '—'}</span> },
  ];

  const tools = (
    <>
      <TombolUnduh namaBerkas="riwayat-run-gaji" namaLembar="Riwayat run" baris={history} testId="pd-unduh"
        kolom={[
          { label: 'Nomor run', nilai: (r) => r.run_number },
          { label: 'Periode', nilai: periode },
          { label: 'Status', nilai: (r) => STATUS_LABEL[r.status] || r.status },
          { label: 'Pembayaran', nilai: payLabel },
          { label: 'Karyawan', nilai: (r) => r.total_employees ?? '' },
          { label: 'Gaji bruto', nilai: (r) => Number(r.total_gross || 0) },
          { label: 'Gaji bersih', nilai: (r) => Number(r.total_net || 0) },
          { label: 'Dibuat', nilai: (r) => (r.created_at ? formatDateID(r.created_at) : '') },
        ]} />
      <Button variant="outline" size="icon" onClick={fetchAll} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
        data-testid="btn-refresh-payroll">
        <RefreshCw className={loading ? 'animate-spin' : ''} />
      </Button>
    </>
  );

  return (
    <PageLayout
      title="Dasbor penggajian"
      subtitle="Ringkasan run gaji tahun ini. Run dibuat dan dibayar di tab Proses gaji."
      tools={tools}
      testId="payroll-dashboard-page"
      summary={!muatAwal && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatTile label="Dibayar tahun ini" value={formatRupiah(d.total_disbursed_ytd || 0)} accent="success" testId="pd-paid-ytd"
            sub="Gaji bersih run final yang sudah dibayar, periode mulai 1 Januari." />
          <StatTile label="Run draf tahun ini" value={String(runSummary.draft?.count ?? 0)} testId="pd-draft"
            sub={`${formatRupiah(runSummary.draft?.total_net_rp || 0)} gaji bersih, belum final.`} />
          <StatTile label="Final belum dibayar" value={formatRupiah(d.total_unpaid_finalized || 0)} accent="warning" testId="pd-unpaid"
            sub="Gaji bersih run final tahun ini yang belum dicatat dibayar." />
          <StatTile label="Cakupan profil gaji" value={`${String(coverage.coverage_pct ?? 0).replace('.', ',')}%`} testId="pd-coverage"
            sub={`${coverage.with_payroll_profile ?? 0} dari ${coverage.total_active_employees ?? 0} karyawan aktif punya profil gaji aktif.`} />
        </div>
      )}
      footer={history.length > 10 && (
        <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />
      )}
    >
      {alerts.map((a) => (
        <Notice key={a.type} tone={a.severity === 'warning' ? 'warning' : 'info'} icon={a.severity === 'warning' ? AlertTriangle : Info}
          title={a.message} testId={`pd-alert-${a.type}`}>{a.action}</Notice>
      ))}

      {muatAwal ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat dasbor penggajian…</p>
      ) : (
        <div className="space-y-2">
          {history.length > 0 && <p className="text-sm font-medium text-foreground">Riwayat run terakhir (maksimal 12)</p>}
          <TabelData kolom={kolom} baris={paged} testId="pd-history"
            kunci={(r) => r.id}
            kosong={<EmptyState title="Belum ada run gaji"
              description="Buat run pertama di tab Proses gaji; ringkasannya akan tampil di sini." />} />
        </div>
      )}
    </PageLayout>
  );
}

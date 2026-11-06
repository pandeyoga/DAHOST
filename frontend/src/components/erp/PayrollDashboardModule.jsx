/**
 * PayrollDashboardModule — tab "Dasbor" di hub Penggajian.
 *
 * 2026-11-06 (Tahap 2): dulu layar ini jalur run KEDUA — tombol "Jalankan Payroll" membuat run hantu tanpa slip,
 * KPI membaca field hantu (selalu 0), dan "Jadwal Auto-Run" tidak pernah menjalankan apa pun. Semua itu dihapus.
 * Dasbor kini HANYA membaca run gaji sungguhan; run dibuat, dihitung ulang, difinalisasi, dan dibayar di tab
 * Proses Gaji. Cetakan PageLayout (PANDUAN_UI G1).
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, BarChart3, Info, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
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

  const tools = (
    <Button variant="outline" size="icon" onClick={fetchAll} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
      data-testid="btn-refresh-payroll">
      <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
    </Button>
  );

  return (
    <PageLayout
      title="Dasbor penggajian"
      subtitle="Ringkasan run gaji. Run dibuat dan dibayar di tab Proses Gaji."
      tools={tools}
      testId="payroll-dashboard-page"
      summary={(
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatTile label="Dibayar tahun ini" value={formatRupiah(d.total_disbursed_ytd || 0)} accent="success" testId="pd-paid-ytd" />
          <StatTile label="Run draf" value={String(runSummary.draft?.count ?? 0)}
            sub={`${formatRupiah(runSummary.draft?.total_net_rp || 0)} gaji bersih`} testId="pd-draft" />
          <StatTile label="Final belum dibayar" value={formatRupiah(d.total_unpaid_finalized || 0)} accent="warning" testId="pd-unpaid" />
          <StatTile label="Cakupan profil gaji" value={`${String(coverage.coverage_pct ?? 0).replace('.', ',')}%`}
            sub={`${coverage.with_payroll_profile ?? 0} dari ${coverage.total_active_employees ?? 0} karyawan aktif`} testId="pd-coverage" />
        </div>
      )}
    >
      {alerts.map((a) => (
        <Notice key={a.type} tone={a.severity === 'warning' ? 'warning' : 'info'} icon={a.severity === 'warning' ? AlertTriangle : Info}
          title={a.message} testId={`pd-alert-${a.type}`}>{a.action}</Notice>
      ))}

      <GlassCard className="p-0 overflow-hidden">
        {history.length === 0 ? (
          <EmptyState icon={BarChart3} title="Belum ada run gaji"
            description="Buat run pertama di tab Proses Gaji; ringkasannya akan tampil di sini." />
        ) : (
          <>
            <Table data-testid="pd-history">
              <TableHeader>
                <TableRow>
                  <TableHead>Nomor run</TableHead>
                  <TableHead>Periode</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Pembayaran</TableHead>
                  <TableHead className="text-right">Karyawan</TableHead>
                  <TableHead className="text-right">Gaji bersih</TableHead>
                  <TableHead className="text-right">Dibuat</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {paged.map((r) => (
                  <TableRow key={r.id} data-testid={`pd-row-${r.run_number}`}>
                    <TableCell className="text-xs">{r.run_number}</TableCell>
                    <TableCell className="text-xs">{formatDateID(r.period_from)} – {formatDateID(r.period_to)}</TableCell>
                    <TableCell><StatusBadge status={r.status} label={STATUS_LABEL[r.status]} /></TableCell>
                    <TableCell className="text-xs">{payLabel(r)}</TableCell>
                    <TableCell className="text-right tabular-nums">{r.total_employees ?? '—'}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatRupiah(r.total_net || 0)}</TableCell>
                    <TableCell className="text-right text-xs">{r.created_at ? formatDateID(r.created_at) : '—'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} className="px-1" />
          </>
        )}
      </GlassCard>
    </PageLayout>
  );
}

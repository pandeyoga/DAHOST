/**
 * Portal Saya › Tinjauan Tahunan — penilaian kinerja tahunan: periode aktif, tugas review, riwayat nilai, KPI.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout (dulu kepala buatan berikon gradien + `p-6`), tiap daftar = TabelData
 * (kartu ringkas di HP) + unduh Excel/CSV, rincian kriteria nilai di popup, status pakai StatusBadge (dulu warna hex),
 * tanggal format Indonesia, istilah Indonesia (Submitted/Actual/Pending → Dikirim/Realisasi/Menunggu).
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { formatDateID } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatusBadge } from '../moduleAtoms';

const STATUS = {
  pending: { label: 'Menunggu', tone: 'warning' },
  in_progress: { label: 'Sedang berjalan', tone: 'info' },
  completed: { label: 'Selesai', tone: 'success' },
  cancelled: { label: 'Dibatalkan', tone: 'muted' },
};
const st = (s) => STATUS[s] || { label: s || '—', tone: 'default' };
const tgl = (v) => (v ? formatDateID(v) : '—');

function Bagian({ judul, alat, children, testId }) {
  return (
    <GlassCard className="space-y-3 p-4" data-testid={testId}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-lg font-semibold text-foreground">{judul}</h3>
        {alat}
      </div>
      {children}
    </GlassCard>
  );
}

export default function MyAnnualReviewModule({ token }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [rincian, setRincian] = useState(null);

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  const fetchReview = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/portal-saya/annual-review`, { headers });
      if (!r.ok) throw new Error(`kode ${r.status}`);
      const result = await r.json();
      setData(result?.data || {});
    } catch (e) {
      toast.error(`Gagal memuat data: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [headers]);

  useEffect(() => { fetchReview(); }, [fetchReview]);

  const employee = data?.employee || {};
  const assignments = data?.assignments || [];
  const reviews = data?.reviews || [];
  const cycles = data?.cycles || [];
  const kpis = data?.kpis || [];
  const kosongSemua = assignments.length === 0 && reviews.length === 0 && cycles.length === 0 && kpis.length === 0;
  const isReviewer = (a) => a.reviewer_id === (employee.id || employee.employee_code);

  return (
    <PageLayout testId="my-annual-review-module" title="Tinjauan tahunan"
      subtitle={employee.name
        ? `${employee.name}${employee.job_title ? ` · ${employee.job_title}` : ''}${employee.department ? ` · ${employee.department}` : ''} — penilaian kinerja tahunan dan tugas review.`
        : 'Penilaian kinerja tahunan dan tugas review Anda.'}
      tools={(
        <Button variant="outline" size="icon" onClick={fetchReview} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      )}>
      {loading && !data ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat penilaian…</p>
      ) : kosongSemua ? (
        <EmptyState title="Belum ada data penilaian tahunan" description="Periode review dan hasil penilaian dari HR akan muncul di sini." />
      ) : (
        <>
          {cycles.length > 0 && (
            <Bagian judul="Periode review aktif" testId="annual-cycles">
              <TabelData baris={cycles} kolom={[
                { kunci: 'cycle_name', label: 'Periode', hp: 'judul', isi: (c) => <span className="font-medium">{c.cycle_name}</span> },
                { kunci: 'mulai', label: 'Mulai', isi: (c) => tgl(c.start_date) },
                { kunci: 'selesai', label: 'Selesai', isi: (c) => tgl(c.end_date) },
                { kunci: 'status', label: 'Status', isi: (c) => <StatusBadge status={c.status} label={st(c.status).label} tone={st(c.status).tone} /> },
              ]} />
            </Bagian>
          )}

          {assignments.length > 0 && (
            <Bagian judul="Tugas review saya" testId="annual-assignments"
              alat={<TombolUnduh namaBerkas="tugas-review-saya" namaLembar="Tugas review" baris={assignments} kolom={[
                { label: 'Peran', nilai: (a) => (isReviewer(a) ? 'Saya menilai' : 'Saya dinilai') },
                { label: 'Pihak lain', nilai: (a) => (isReviewer(a) ? a.employee_id : a.reviewer_id) },
                { label: 'Periode', nilai: (a) => a.review_period || '' }, { label: 'Status', nilai: (a) => st(a.status).label },
              ]} />}>
              <TabelData baris={assignments} kolom={[
                { kunci: 'peran', label: 'Tugas', hp: 'judul', isi: (a) => (isReviewer(a) ? `Review untuk ${a.employee_id}` : `Direview oleh ${a.reviewer_id}`) },
                { kunci: 'periode', label: 'Periode', isi: (a) => a.review_period || '—' },
                { kunci: 'status', label: 'Status', isi: (a) => <StatusBadge status={a.status} label={st(a.status).label} tone={st(a.status).tone} /> },
              ]} />
            </Bagian>
          )}

          {reviews.length > 0 && (
            <Bagian judul="Riwayat penilaian" testId="annual-reviews"
              alat={<TombolUnduh namaBerkas="riwayat-penilaian-saya" namaLembar="Riwayat" baris={reviews} kolom={[
                { label: 'Periode', nilai: (r) => r.review_period || '' }, { label: 'Dikirim', nilai: (r) => tgl(r.submitted_at) },
                { label: 'Skor akhir', nilai: (r) => r.final_score ?? '' },
              ]} />}>
              <TabelData baris={reviews} onKlikBaris={setRincian} kolom={[
                { kunci: 'periode', label: 'Periode', hp: 'judul', isi: (r) => <span className="font-medium">{r.review_period || '—'}</span> },
                { kunci: 'dikirim', label: 'Dikirim', isi: (r) => tgl(r.submitted_at) },
                { kunci: 'skor', label: 'Skor akhir', rata: 'kanan', isi: (r) => <span className="font-semibold tabular-nums">{r.final_score ?? '—'}</span> },
                { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (r.criteria_scores && Object.keys(r.criteria_scores).length > 0
                  ? <Button size="sm" variant="outline" onClick={() => setRincian(r)}>Rincian</Button> : null) },
              ]} />
            </Bagian>
          )}

          {kpis.length > 0 && (
            <Bagian judul="Sasaran KPI" testId="annual-kpis"
              alat={<TombolUnduh namaBerkas="sasaran-kpi-saya" namaLembar="KPI" baris={kpis} kolom={[
                { label: 'KPI', nilai: (k) => k.kpi_name || 'KPI' }, { label: 'Target', nilai: (k) => k.target_value ?? '' },
                { label: 'Satuan', nilai: (k) => k.unit || '' }, { label: 'Realisasi', nilai: (k) => k.actual_value ?? '' },
              ]} />}>
              <TabelData baris={kpis} kolom={[
                { kunci: 'nama', label: 'KPI', hp: 'judul', isi: (k) => k.kpi_name || 'KPI' },
                { kunci: 'target', label: 'Target', rata: 'kanan', isi: (k) => <span className="tabular-nums">{k.target_value} {k.unit}</span> },
                { kunci: 'realisasi', label: 'Realisasi', rata: 'kanan', isi: (k) => <span className="tabular-nums">{k.actual_value ?? '—'}</span> },
              ]} />
            </Bagian>
          )}
        </>
      )}

      {rincian && (
        <DetailPopup open onClose={() => setRincian(null)} judul={`Penilaian ${rincian.review_period || ''}`.trim()}
          keterangan={`Dikirim ${tgl(rincian.submitted_at)} · skor akhir ${rincian.final_score ?? '—'}`} testId="annual-review-detail">
          <dl className="divide-y divide-[var(--glass-border)]">
            {Object.entries(rincian.criteria_scores || {}).map(([k, v]) => <BarisDetail key={k} label={k}>{v}</BarisDetail>)}
          </dl>
        </DetailPopup>
      )}
    </PageLayout>
  );
}

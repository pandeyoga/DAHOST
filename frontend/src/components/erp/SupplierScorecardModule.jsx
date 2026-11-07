/**
 * SupplierScorecardModule — Penilaian Supplier (Portal Pengadaan; juga Gudang › wh-supplier-scorecard)
 *
 * 2026-08-06 — DIPINDAH KE SSOT MASTER SUPPLIER.
 * Sebelumnya modul ini memanggil `/api/rahaza/grn-qc/supplier-scorecard` yang
 * MENGELOMPOKKAN BERDASARKAN TEKS `supplier_name`. Akibat nyatanya: satu
 * perusahaan yang ditulis "PT. Benang Jaya" dan "PT Benang Jaya" muncul sebagai
 * DUA baris dengan nilai terbelah — penilaian supplier jadi tidak bisa dipakai
 * untuk keputusan (user story 5 Phase 2).
 *
 * Sekarang memakai:
 *   · GET /api/procurement/supplier-scorecard          → dikelompokkan `supplier_id`
 *   · GET /api/procurement/suppliers/{id}/scorecard     → detail (tren, alasan
 *     reject, inspeksi terbaru, rekap PO) termasuk riwayat ejaan nama lama.
 * Baris yang BELUM tertaut master ditandai jelas + diarahkan ke migrasi, bukan
 * disembunyikan, supaya data lama tidak "hilang diam-diam".
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, 4 StatTile berketerangan (dulu 6 kartu huruf kapital),
 * tabel + unduh, detail = DetailPopup, kalkulator AQL = popup (dulu tab), warna token.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { Calculator, Link2Off, RefreshCw, Search } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { Skeleton } from '@/components/ui/skeleton';
import { useToast } from '@/hooks/use-toast';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatDateID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';

// Batas grade = `_grade()` di routes/procurement_suppliers.py (tingkat terima).
const GRADE = {
  'A+': { tone: 'success', label: 'Sangat baik' },
  A: { tone: 'success', label: 'Baik' },
  B: { tone: 'info', label: 'Cukup' },
  C: { tone: 'warning', label: 'Di bawah target' },
  D: { tone: 'danger', label: 'Kritis' },
  '-': { tone: 'muted', label: 'Belum dinilai' },
};
const gradeOf = (g) => GRADE[g] || GRADE['-'];

const SEVERITY = {
  critical: { label: 'Kritis', tone: 'danger' },
  major: { label: 'Mayor', tone: 'warning' },
  minor: { label: 'Minor', tone: 'info' },
};
const HASIL_INSPEKSI = {
  accepted: { label: 'Diterima', tone: 'success' },
  partial: { label: 'Sebagian', tone: 'warning' },
  rejected: { label: 'Ditolak', tone: 'danger' },
};

const PO_STATUS_LABEL = {
  draft: 'Draf', pending_approval: 'Menunggu persetujuan', approved: 'Disetujui',
  sent: 'Terkirim', partially_received: 'Diterima sebagian', fully_received: 'Diterima penuh',
  completed: 'Selesai', cancelled: 'Dibatalkan', rejected: 'Ditolak',
};

const PERIODE = [
  { v: 30, label: '30 hari terakhir' }, { v: 90, label: '90 hari terakhir' },
  { v: 180, label: '180 hari terakhir' }, { v: 365, label: '1 tahun terakhir' },
];
const AQL_PILIHAN = [
  { v: '0.65', label: '0,65% — kritis' }, { v: '1', label: '1,0% — mayor' },
  { v: '2.5', label: '2,5% — standar (disarankan)' }, { v: '4', label: '4,0% — minor' },
  { v: '6.5', label: '6,5% — kosmetik' },
];

const BULAN = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
const labelBulan = (ym) => {
  const [y, m] = String(ym || '').split('-').map(Number);
  return y && m ? `${BULAN[m - 1]} ${y}` : (ym || '—');
};
const num = (n, max = 2) => Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: max });
const rp = (n) => `Rp ${Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 0 })}`;
const TEKS = {
  success: 'text-[hsl(var(--success-text))]', warning: 'text-[hsl(var(--warning-text))]',
  danger: 'text-[hsl(var(--danger-text))]',
};
const nadaTerima = (r) => (r >= 95 ? TEKS.success : r >= 85 ? TEKS.warning : TEKS.danger);
const nadaCacat = (r) => (r <= 2 ? TEKS.success : r <= 5 ? TEKS.warning : TEKS.danger);

function GradeBadge({ grade }) {
  const g = gradeOf(grade);
  return <StatusBadge status={`grade-${grade}`} tone={g.tone} label={grade === '-' ? g.label : `${grade} · ${g.label}`} />;
}

function Seksi({ judul, alat, children }) {
  return (
    <section className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">{judul}</h3>
        {alat}
      </div>
      {children}
    </section>
  );
}

export default function SupplierScorecardModule({ token, onNavigate }) {
  const { toast } = useToast();
  const [scorecards, setScorecards] = useState([]);
  const [summary, setSummary] = useState(null);
  const [periodDays, setPeriodDays] = useState(90);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [search, setSearch] = useState('');
  const [detailSupplier, setDetailSupplier] = useState(null);
  const [detailData, setDetailData] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Kalkulator AQL (popup)
  const [aqlOpen, setAqlOpen] = useState(false);
  const [aqlLot, setAqlLot] = useState(500);
  const [aqlValue, setAqlValue] = useState('2.5');
  const [aqlResult, setAqlResult] = useState(null);
  const [aqlLoading, setAqlLoading] = useState(false);
  const [aqlError, setAqlError] = useState('');

  const h = useMemo(() => ({
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
  }), [token]);

  const fetchScorecards = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      const res = await fetch(`/api/procurement/supplier-scorecard?period_days=${periodDays}`, { headers: h });
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`);
      setScorecards(Array.isArray(data?.items) ? data.items : []);
      setSummary(data?.summary || null);
    } catch (e) {
      setScorecards([]);
      setSummary(null);
      setLoadError(e.message);
      toast({ title: 'Gagal memuat penilaian supplier', description: e.message, variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  }, [h, periodDays, toast]);

  useEffect(() => { fetchScorecards(); }, [fetchScorecards]);

  const openDetail = async (row) => {
    if (!row.supplier_id) {
      toast({
        title: 'Supplier ini belum tertaut Master Supplier',
        description: 'Jalankan "Migrasi Data Lama" di modul Master Supplier agar riwayatnya menyatu.',
      });
      return;
    }
    setDetailSupplier(row);
    setDetailLoading(true);
    setDetailData(null);
    try {
      const res = await fetch(
        `/api/procurement/suppliers/${row.supplier_id}/scorecard?period_days=180`,
        { headers: h },
      );
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`);
      setDetailData(data);
    } catch (e) {
      toast({ title: 'Gagal memuat detail', description: e.message, variant: 'destructive' });
    } finally {
      setDetailLoading(false);
    }
  };

  const handleAqlCalc = async () => {
    setAqlLoading(true);
    setAqlError('');
    try {
      const res = await fetch('/api/rahaza/grn-qc/aql/calculate', {
        method: 'POST', headers: h,
        body: JSON.stringify({ lot_size: parseInt(aqlLot, 10), aql: parseFloat(aqlValue) }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Perhitungan AQL gagal');
      setAqlResult(data);
    } catch (e) {
      setAqlError(e.message);
      toast({ title: e.message, variant: 'destructive' });
    } finally {
      setAqlLoading(false);
    }
  };

  const filteredScorecards = useMemo(() => {
    if (!search) return scorecards;
    const q = search.toLowerCase();
    return scorecards.filter(s =>
      (s.supplier_name || '').toLowerCase().includes(q) ||
      (s.supplier_code || '').toLowerCase().includes(q));
  }, [scorecards, search]);
  const { page, setPage, totalPages, total, paged } = useClientPagination(filteredScorecards, 25);

  // Kartu angka — dihitung dari daftar yang SAMA dengan tabel (semua baris periode ini, bukan halaman).
  const kpi = useMemo(() => {
    const totalSup = scorecards.length;
    const aGrade = scorecards.filter(s => s.quality_grade === 'A+' || s.quality_grade === 'A').length;
    const cdGrade = scorecards.filter(s => s.quality_grade === 'C' || s.quality_grade === 'D').length;
    const totalGRNs = scorecards.reduce((a, s) => a + (s.total_grns || 0), 0);
    const totalRejected = scorecards.reduce((a, s) => a + (s.total_rejected || 0), 0);
    const totalReceived = scorecards.reduce((a, s) => a + (s.total_received || 0), 0);
    const avgDefect = totalReceived > 0 ? (totalRejected / totalReceived * 100) : null;
    const unlinked = summary?.unlinked ?? scorecards.filter(s => !s.linked).length;
    return { totalSup, aGrade, cdGrade, totalGRNs, avgDefect, unlinked };
  }, [scorecards, summary]);
  const periodeLabel = (PERIODE.find((p) => p.v === periodDays) || {}).label || `${periodDays} hari`;

  const kolom = [
    { kunci: 'pemasok', label: 'Pemasok', hp: 'judul', isi: (s) => (
      <div className="min-w-0">
        <p className="truncate font-medium text-foreground">{s.supplier_name}</p>
        <div className="flex flex-wrap items-center gap-1.5">
          {s.supplier_code && <span className="font-mono text-xs text-muted-foreground">{s.supplier_code}</span>}
          {!s.linked && <StatusBadge status="unlinked" tone="warning" label="Belum tertaut master" />}
        </div>
      </div>) },
    { kunci: 'grade', label: 'Grade', isi: (s) => <GradeBadge grade={s.quality_grade} /> },
    { kunci: 'terima', label: 'Tingkat terima', rata: 'kanan', isi: (s) => (
      <span className={`tabular-nums font-semibold ${nadaTerima(s.accept_rate)}`}>{num(s.accept_rate)}%</span>) },
    { kunci: 'cacat', label: 'Tingkat cacat', rata: 'kanan', isi: (s) => (
      <span className={`tabular-nums ${nadaCacat(s.defect_rate)}`}>{num(s.defect_rate)}%</span>) },
    { kunci: 'tepat', label: 'Tepat waktu', rata: 'kanan', isi: (s) => (s.on_time_rate == null
      ? <span className="text-muted-foreground" title="Belum ada penerimaan yang bisa dibandingkan dengan tanggal terima PO">—</span>
      : <span className="tabular-nums">{num(s.on_time_rate)}% <span className="text-xs text-muted-foreground">({s.on_time_samples})</span></span>) },
    { kunci: 'inspeksi', label: 'Inspeksi', rata: 'kanan', isi: (s) => <span className="tabular-nums">{s.total_grns}</span> },
    { kunci: 'diterima', label: 'Qty lolos', rata: 'kanan', isi: (s) => <span className="tabular-nums">{num(s.total_accepted)}</span> },
    { kunci: 'ditolak', label: 'Qty ditolak', rata: 'kanan', isi: (s) => <span className="tabular-nums">{num(s.total_rejected)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (s) => (
      <Button size="sm" variant="outline" onClick={() => openDetail(s)} disabled={!s.supplier_id}
        title={s.supplier_id ? 'Lihat rincian penilaian' : 'Belum tertaut Master Supplier'}
        data-testid={`scorecard-detail-${s.supplier_code || s.supplier_name}`}>
        Rincian
      </Button>) },
  ];

  const d = detailData;
  const sc = d?.scorecard;
  const poStatus = Object.entries(d?.po_by_status || {}).map(([st, v]) => ({ st, ...v }));
  const tren = d?.monthly_trend || [];
  const alasan = d?.top_reject_reasons || [];
  const inspeksi = (d?.recent_inspections || []).slice(0, 8);
  const namaBerkasDetail = `penilaian-${detailSupplier?.supplier_code || detailSupplier?.supplier_name || 'pemasok'}`;

  return (
    <PageLayout testId="supplier-scorecard-page" title="Penilaian Supplier"
      subtitle="Mutu pemasok dari hasil inspeksi penerimaan barang, dikelompokkan per Master Supplier."
      actions={
        <Button variant="outline" onClick={() => setAqlOpen(true)} data-testid="tab-aql">
          <Calculator />Kalkulator AQL
        </Button>
      }
      filters={<>
        <SmartNativeSelect value={String(periodDays)} onChange={(e) => setPeriodDays(parseInt(e.target.value, 10))}
          className="w-44" data-testid="period-select" aria-label="Periode">
          {PERIODE.map((p) => <option key={p.v} value={String(p.v)}>{p.label}</option>)}
        </SmartNativeSelect>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder="Cari nama atau kode pemasok" className="pl-8" value={search}
            onChange={(e) => setSearch(e.target.value)} data-testid="scorecard-search" />
        </div>
      </>}
      tools={<>
        <TombolUnduh namaBerkas={`penilaian-supplier-${periodDays}-hari`} namaLembar="Penilaian" baris={filteredScorecards}
          testId="scorecard-unduh"
          kolom={[
            { label: 'Kode', nilai: (s) => s.supplier_code || '' },
            { label: 'Pemasok', nilai: (s) => s.supplier_name },
            { label: 'Tertaut master', nilai: (s) => (s.linked ? 'Ya' : 'Belum') },
            { label: 'Grade', nilai: (s) => (s.quality_grade === '-' ? 'Belum dinilai' : s.quality_grade) },
            { label: 'Tingkat terima (%)', nilai: (s) => Number(s.accept_rate || 0) },
            { label: 'Tingkat cacat (%)', nilai: (s) => Number(s.defect_rate || 0) },
            { label: 'Tepat waktu (%)', nilai: (s) => (s.on_time_rate == null ? '' : Number(s.on_time_rate)) },
            { label: 'Penerimaan dibandingkan', nilai: (s) => s.on_time_samples || 0 },
            { label: 'Inspeksi', nilai: (s) => s.total_grns || 0 },
            { label: 'Qty diperiksa', nilai: (s) => Number(s.total_received || 0) },
            { label: 'Qty lolos', nilai: (s) => Number(s.total_accepted || 0) },
            { label: 'Qty ditolak', nilai: (s) => Number(s.total_rejected || 0) },
            { label: 'Inspeksi terakhir', nilai: (s) => (s.last_inspection_at ? formatDateID(s.last_inspection_at) : '') },
          ]} />
        <Button variant="outline" size="icon" onClick={fetchScorecards} disabled={loading} title="Muat ulang"
          aria-label="Muat ulang" data-testid="scorecard-refresh-btn">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={scorecards.length > 0 && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <StatTile label="Pemasok dinilai" value={kpi.totalSup} testId="kpi-total-suppliers"
            sub={`${summary?.linked ?? kpi.totalSup - kpi.unlinked} tertaut master · ${kpi.unlinked} belum`} />
          <StatTile label="Grade A dan A+" value={kpi.aGrade} accent={kpi.aGrade ? 'success' : 'default'}
            sub="Tingkat terima ≥ 97%" />
          <StatTile label="Grade C dan D" value={kpi.cdGrade} accent={kpi.cdGrade ? 'danger' : 'default'}
            sub="Tingkat terima < 93% — perlu ditinjau" />
          <StatTile label="Tingkat cacat gabungan"
            value={kpi.avgDefect == null ? '—' : `${num(kpi.avgDefect)}%`}
            accent={kpi.avgDefect == null ? 'muted' : kpi.avgDefect > 5 ? 'danger' : kpi.avgDefect > 2 ? 'warning' : 'success'}
            sub={kpi.avgDefect == null ? 'Belum ada qty yang diperiksa'
              : `Qty ditolak ÷ qty diperiksa, dari ${kpi.totalGRNs} inspeksi`} />
        </div>
      )}
      footer={filteredScorecards.length > 25 && (
        <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />
      )}>
      {loadError && <Notice tone="danger" testId="scorecard-error" title="Penilaian gagal dimuat">{loadError}</Notice>}

      {kpi.unlinked > 0 && (
        <Notice tone="warning" icon={Link2Off} testId="scorecard-unlinked-hint"
          title={`${kpi.unlinked} nama pemasok di riwayat inspeksi belum tertaut Master Supplier`}
          action={onNavigate && (
            <Button size="sm" variant="outline" onClick={() => onNavigate('proc-suppliers')}
              data-testid="scorecard-goto-migration">
              Buka Master Supplier
            </Button>
          )}>
          Nilainya berdiri sendiri. Tautkan lewat Master Supplier › Migrasi data lama.
        </Notice>
      )}

      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-10" />)}
          </div>
        ) : (
          <TabelData kolom={kolom} baris={paged} kunci={(s) => s.supplier_id || `unlinked-${s.supplier_name}`}
            onKlikBaris={openDetail} testId="scorecard-table"
            kosong={
              <EmptyState
                title={scorecards.length === 0 ? `Belum ada inspeksi penerimaan dalam ${periodeLabel}` : 'Tidak ada pemasok yang cocok'}
                description={scorecards.length === 0
                  ? 'Nilai muncul otomatis setelah barang diterima dan diinspeksi di Portal Gudang › Penerimaan Barang.'
                  : 'Ubah kata pencarian.'} />
            } />
        )}
      </GlassCard>

      {/* Rincian satu pemasok */}
      {detailSupplier && (
        <DetailPopup open onClose={() => setDetailSupplier(null)} testId="scorecard-detail-modal"
          judul={detailSupplier.supplier_name}
          keterangan={`Penilaian 180 hari terakhir${detailSupplier.supplier_code ? ` · ${detailSupplier.supplier_code}` : ''}`}
          status={sc && <GradeBadge grade={sc.quality_grade} />}>
          {detailLoading && (
            <div className="space-y-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-8" />)}</div>
          )}
          {!detailLoading && sc && (
            <>
              <dl className="divide-y divide-[var(--glass-border)]">
                <BarisDetail label="Tingkat terima">
                  <span className={`font-semibold tabular-nums ${nadaTerima(sc.accept_rate)}`}>{num(sc.accept_rate)}%</span>
                </BarisDetail>
                <BarisDetail label="Tingkat cacat">
                  <span className={`tabular-nums ${nadaCacat(sc.defect_rate)}`}>{num(sc.defect_rate)}%</span>
                </BarisDetail>
                <BarisDetail label="Inspeksi">{sc.total_grns} inspeksi · qty diperiksa {num(sc.total_received)}</BarisDetail>
                <BarisDetail label="Tepat waktu">
                  {sc.on_time_rate == null ? '— (belum ada penerimaan yang bisa dibandingkan)'
                    : `${num(sc.on_time_rate)}% dari ${sc.on_time_samples} penerimaan`}
                </BarisDetail>
              </dl>

              {(d.name_variants_merged || []).length > 1 && (
                <Seksi judul="Ejaan nama yang disatukan menjadi satu penilaian">
                  <div className="flex flex-wrap gap-1.5" data-testid="scorecard-name-variants">
                    {d.name_variants_merged.map((n) => <StatusBadge key={n} status="nama" tone="muted" label={n} />)}
                  </div>
                </Seksi>
              )}

              {poStatus.length > 0 && (
                <Seksi judul="Purchase order per status" alat={
                  <TombolUnduh namaBerkas={`${namaBerkasDetail}-po`} namaLembar="PO per status" baris={poStatus}
                    kolom={[
                      { label: 'Status', nilai: (r) => PO_STATUS_LABEL[r.st] || r.st },
                      { label: 'Jumlah PO', nilai: (r) => r.count },
                      { label: 'Nilai (Rp)', nilai: (r) => Number(r.value || 0) },
                    ]} />
                }>
                  <TabelData baris={poStatus} kunci={(r) => r.st} testId="scorecard-po-status"
                    kolom={[
                      { kunci: 'st', label: 'Status', hp: 'judul', isi: (r) => PO_STATUS_LABEL[r.st] || r.st },
                      { kunci: 'n', label: 'Jumlah PO', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.count}</span> },
                      { kunci: 'v', label: 'Nilai', rata: 'kanan', isi: (r) => <span className="tabular-nums">{rp(r.value)}</span> },
                    ]} />
                </Seksi>
              )}

              {tren.length > 0 && (
                <Seksi judul="Tren bulanan" alat={
                  <TombolUnduh namaBerkas={`${namaBerkasDetail}-tren`} namaLembar="Tren bulanan" baris={tren}
                    kolom={[
                      { label: 'Bulan', nilai: (m) => labelBulan(m.month) },
                      { label: 'Tingkat terima (%)', nilai: (m) => Number(m.accept_rate || 0) },
                      { label: 'Inspeksi', nilai: (m) => m.grns },
                    ]} />
                }>
                  <TabelData baris={tren} kunci={(m) => m.month} testId="scorecard-trend"
                    kolom={[
                      { kunci: 'bulan', label: 'Bulan', hp: 'judul', isi: (m) => labelBulan(m.month) },
                      { kunci: 'terima', label: 'Tingkat terima', rata: 'kanan', isi: (m) => (
                        <span className={`tabular-nums font-semibold ${nadaTerima(m.accept_rate)}`}>{num(m.accept_rate)}%</span>) },
                      { kunci: 'n', label: 'Inspeksi', rata: 'kanan', isi: (m) => <span className="tabular-nums">{m.grns}</span> },
                    ]} />
                </Seksi>
              )}

              {alasan.length > 0 && (
                <Seksi judul="Alasan penolakan terbanyak" alat={
                  <TombolUnduh namaBerkas={`${namaBerkasDetail}-alasan-tolak`} namaLembar="Alasan tolak" baris={alasan}
                    kolom={[
                      { label: 'Alasan', nilai: (r) => r.label },
                      { label: 'Tingkat', nilai: (r) => (SEVERITY[r.severity] || {}).label || r.severity || '' },
                      { label: 'Qty ditolak', nilai: (r) => Number(r.total_qty || 0) },
                    ]} />
                }>
                  <TabelData baris={alasan} kunci={(r) => r.code} testId="scorecard-reject-reasons"
                    kolom={[
                      { kunci: 'alasan', label: 'Alasan', hp: 'judul', isi: (r) => r.label },
                      { kunci: 'tingkat', label: 'Tingkat', isi: (r) => {
                        const s = SEVERITY[r.severity];
                        return s ? <StatusBadge status={r.severity} tone={s.tone} label={s.label} /> : '—';
                      } },
                      { kunci: 'qty', label: 'Qty ditolak', rata: 'kanan', isi: (r) => <span className="tabular-nums">{num(r.total_qty)}</span> },
                    ]} />
                </Seksi>
              )}

              {inspeksi.length > 0 && (
                <Seksi judul="Inspeksi terbaru" alat={
                  <TombolUnduh namaBerkas={`${namaBerkasDetail}-inspeksi`} namaLembar="Inspeksi" baris={inspeksi}
                    kolom={[
                      { label: 'No. inspeksi', nilai: (i) => i.inspection_no || '' },
                      { label: 'Penerimaan', nilai: (i) => i.receipt_number || i.supplier_name_recorded || '' },
                      { label: 'Riwayat lama', nilai: (i) => (i.legacy_unlinked ? 'Ya' : '') },
                      { label: 'Hasil', nilai: (i) => (HASIL_INSPEKSI[i.overall_result] || {}).label || i.overall_result || '' },
                      { label: 'Tingkat cacat (%)', nilai: (i) => Number(i.defect_rate || 0) },
                    ]} />
                }>
                  <TabelData baris={inspeksi} testId="scorecard-recent-inspections"
                    kolom={[
                      { kunci: 'no', label: 'No. inspeksi', hp: 'judul', isi: (i) => <span className="font-mono text-xs">{i.inspection_no || '—'}</span> },
                      { kunci: 'gr', label: 'Penerimaan', hp: 'keterangan', isi: (i) => (
                        <span>{i.receipt_number || i.supplier_name_recorded || '—'}
                          {i.legacy_unlinked && <span className="ml-1.5 text-xs text-[hsl(var(--warning-text))]">(riwayat lama)</span>}
                        </span>) },
                      { kunci: 'hasil', label: 'Hasil', isi: (i) => {
                        const r = HASIL_INSPEKSI[i.overall_result];
                        return r ? <StatusBadge status={i.overall_result} tone={r.tone} label={r.label} /> : '—';
                      } },
                      { kunci: 'cacat', label: 'Cacat', rata: 'kanan', isi: (i) => <span className="tabular-nums">{num(i.defect_rate)}%</span> },
                    ]} />
                </Seksi>
              )}
            </>
          )}
          {!detailLoading && d && !sc && (
            <EmptyState title="Belum ada data inspeksi untuk pemasok ini" description="Dalam 180 hari terakhir." />
          )}
        </DetailPopup>
      )}

      {/* Kalkulator sampling AQL (dulu tab sendiri) */}
      <FormPopup open={aqlOpen} onClose={() => setAqlOpen(false)} testId="aql-popup"
        judul="Kalkulator sampling AQL"
        keterangan="Ukuran sample dan batas terima/tolak menurut ANSI/ASQ Z1.4, inspeksi umum level II."
        labelSimpan="Hitung rencana sample" onSimpan={handleAqlCalc} menyimpan={aqlLoading}
        bisaSimpan={!!aqlLot && parseInt(aqlLot, 10) > 0} galat={aqlError}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Ukuran lot (total qty diterima)" htmlFor="aql-lot" wajib>
            <Input id="aql-lot" type="number" min="1" inputMode="numeric" value={aqlLot}
              onChange={(e) => setAqlLot(e.target.value)} placeholder="Contoh: 500" data-testid="aql-lot-input" />
          </Isian>
          <Isian label="Batas mutu (AQL)" htmlFor="aql-value">
            <SmartNativeSelect id="aql-value" value={aqlValue} onChange={(e) => setAqlValue(e.target.value)}
              data-testid="aql-value-select">
              {AQL_PILIHAN.map((o) => <option key={o.v} value={o.v}>{o.label}</option>)}
            </SmartNativeSelect>
          </Isian>
        </div>
        {aqlResult ? (
          <div className="space-y-3" data-testid="aql-result">
            <div className="grid grid-cols-2 gap-3">
              <StatTile label="Ukuran sample" value={aqlResult.sample_size} accent="primary"
                sub={`pcs diperiksa dari lot ${Number(aqlResult.lot_size).toLocaleString('id-ID')}`} />
              <StatTile label="Kode huruf" value={aqlResult.code_letter} sub={`AQL ${num(aqlResult.aql)}%`} />
              <StatTile label="Terima lot bila cacat" value={`≤ ${aqlResult.accept_limit}`} accent="success" />
              <StatTile label="Tolak lot bila cacat" value={`≥ ${aqlResult.reject_limit}`} accent="danger" />
            </div>
            <dl className="divide-y divide-[var(--glass-border)]">
              <BarisDetail label="Level inspeksi">{aqlResult.inspection_level}</BarisDetail>
              <BarisDetail label="Standar">{aqlResult.standard}</BarisDetail>
            </dl>
            <Notice tone="info" title="Cara pakai">
              Ambil acak {aqlResult.sample_size} pcs dari lot {Number(aqlResult.lot_size).toLocaleString('id-ID')} pcs,
              lalu periksa cacatnya. Bila ditemukan ≤ {aqlResult.accept_limit} cacat, terima seluruh lot. Bila
              ≥ {aqlResult.reject_limit} cacat, tolak seluruh lot.
            </Notice>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Isi ukuran lot, lalu tekan Hitung rencana sample.</p>
        )}
      </FormPopup>
    </PageLayout>
  );
}

export { SupplierScorecardModule };

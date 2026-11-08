/**
 * ProcurementDashboardModule — Dashboard Portal Pengadaan
 *
 * Membaca `/api/procurement/overview` + `/pipeline` yang meng-agregat SELURUH
 * koleksi siklus pengadaan (PR, PO, GR, inspeksi QC, AP, master supplier,
 * price list, PR aksesoris) — bukan satu koleksi saja.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, kartu angka StatTile berketerangan, daftar = tabel
 * + unduh. "Alur pengadaan" dulu berjudul "90 hari" padahal permintaan & faktur dihitung SEMUA WAKTU
 * (lihat `procurement_pipeline`) — kini periode ditulis per baris dan status memakai label Indonesia
 * (dulu kode mentah "paid/sent").
 */
import { useCallback, useEffect, useState } from 'react';
import { ArrowRight, RefreshCw } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Skeleton } from '@/components/ui/skeleton';
import { toast } from 'sonner';
import PageLayout from '../layout/PageLayout';
import { Notice, StatTile, StatusBadge } from '../moduleAtoms';
import { EP, apiGet, fmtDate, fmtRp } from './procApi';

// Label status per tahap (sama dengan label di layar Permintaan, PO, Penerimaan, dan Faktur).
const STATUS_TAHAP = {
  requests: {
    draft: 'Draf', submitted: 'Menunggu persetujuan dept', dept_approved: 'Menunggu persetujuan keuangan',
    finance_approved: 'Menunggu persetujuan final', approved: 'Disetujui', in_procurement: 'Sedang pengadaan',
    rejected: 'Ditolak', completed: 'Selesai', cancelled: 'Dibatalkan',
  },
  purchase_orders: {
    draft: 'Draf', pending_approval: 'Menunggu persetujuan', approved: 'Disetujui',
    partially_received: 'Diterima sebagian', fully_received: 'Diterima penuh', rejected: 'Ditolak',
    cancelled: 'Dibatalkan',
  },
  goods_receipts: {
    draft: 'Draf', received: 'Diterima', completed: 'Selesai', partial_received: 'Diterima sebagian',
  },
  ap_invoices: {
    draft: 'Draf', sent: 'Terbit', issued: 'Terbit', approved: 'Disetujui', overdue: 'Lewat jatuh tempo',
    partial_paid: 'Dibayar sebagian', partial: 'Dibayar sebagian', paid: 'Lunas', posted: 'Terposting',
    voided: 'Dibatalkan', void: 'Dibatalkan', cancelled: 'Dibatalkan',
  },
};
const labelStatus = (tahap, s) => STATUS_TAHAP[tahap]?.[s] || (s === 'unknown' ? 'Tanpa status' : s);

// Periode tiap tahap mengikuti query backend (`procurement_pipeline`).
const TAHAP = [
  { key: 'requests', label: 'Permintaan pengadaan', periode: 'Semua waktu' },
  { key: 'purchase_orders', label: 'Purchase order', periode: '90 hari (tanggal PO)' },
  { key: 'goods_receipts', label: 'Penerimaan barang', periode: '90 hari (tanggal dibuat)' },
  { key: 'ap_invoices', label: 'Faktur pemasok', periode: 'Semua waktu' },
];

function Bagian({ judul, keterangan, alat, children, testId }) {
  return (
    <GlassCard className="p-4 space-y-3 min-w-0" data-testid={testId}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-base font-semibold text-foreground">{judul}</h3>
          {keterangan && <p className="text-sm text-muted-foreground">{keterangan}</p>}
        </div>
        {alat && <div className="flex items-center gap-2">{alat}</div>}
      </div>
      {children}
    </GlassCard>
  );
}

const Kosong = ({ children }) => <p className="text-sm text-muted-foreground">{children}</p>;

export default function ProcurementDashboardModule({ token, onNavigate }) {
  const [ov, setOv] = useState(null);
  const [pipe, setPipe] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setErr('');
    try {
      const [o, p] = await Promise.all([
        apiGet(token, EP.overview),
        apiGet(token, EP.pipeline),
      ]);
      setOv(o);
      setPipe(p);
    } catch (e) {
      setErr(e.message);
      toast.error(`Gagal memuat dashboard pengadaan: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const k = ov?.kpi || {};
  const alerts = ov?.alerts || {};
  const go = (id) => (onNavigate ? () => onNavigate(id) : undefined);

  // PO terlambat + PO yang dijadwalkan tiba ≤ 7 hari → satu tabel "perlu perhatian".
  const poPerhatian = [
    ...(alerts.po_overdue || []).map((p) => ({ ...p, _kunci: `t-${p.id}`, keadaan: 'terlambat' })),
    ...(alerts.po_due_soon || []).map((p) => ({ ...p, _kunci: `s-${p.id}`, keadaan: 'segera' })),
  ];
  const tahapBaris = TAHAP.map((t) => {
    const rows = pipe?.[t.key] || [];
    return {
      ...t,
      jumlah: rows.reduce((s, r) => s + (r.count || 0), 0),
      rincian: rows.map((r) => `${labelStatus(t.key, r.status)} ${r.count}`).join(' · '),
    };
  });
  const recentPr = ov?.recent?.requests || [];
  const recentPo = ov?.recent?.purchase_orders || [];

  return (
    <PageLayout testId="proc-dashboard-page" title="Dashboard Pengadaan"
      subtitle="Ringkasan siklus pengadaan: permintaan, pesanan, penerimaan, dan faktur pemasok."
      tools={
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang"
          aria-label="Muat ulang" data-testid="proc-dashboard-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      }
      summary={loading && !ov ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3" data-testid="proc-dashboard-loading">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-[var(--radius-md)]" />)}
        </div>
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <StatTile label="Permintaan menunggu" value={k.pr_pending ?? 0} accent={k.pr_pending ? 'warning' : 'default'}
              sub={`dari ${k.pr_total ?? 0} permintaan seluruhnya`}
              hint="Buka permintaan" onClick={go('proc-requests')} testId="proc-kpi-pr-pending" />
            <StatTile label="PO berjalan" value={k.po_open ?? 0}
              sub={`Nilai ${fmtRp(k.open_po_value)} · ${k.po_pending_approval ?? 0} menunggu persetujuan`}
              hint="Buka PO" onClick={go('proc-purchase-orders')} testId="proc-kpi-po-open" />
            <StatTile label="Hutang pemasok" value={fmtRp(k.ap_outstanding)} accent={k.ap_outstanding ? 'danger' : 'default'}
              sub={`${k.ap_unpaid ?? 0} faktur belum lunas (tanpa CMT)`}
              hint="Buka faktur" onClick={go('proc-ap-invoices')} testId="proc-kpi-ap" />
            <StatTile label="Belanja bulan ini" value={fmtRp(k.po_value_this_month)}
              sub="PO bulan ini, tanpa draf/ditolak/batal"
              hint="Buka analisis" onClick={go('proc-analytics')} testId="proc-kpi-spend-month" />
          </div>
          {/* Angka pendukung dalam satu kalimat (dulu 4 kartu tambahan → 8 kartu berjejer). */}
          <p className="flex flex-wrap items-center gap-x-1 gap-y-1 text-sm text-muted-foreground" data-testid="proc-dashboard-sekunder">
            {poPerhatian.length === 0 && (<>
              <span className="text-[hsl(var(--success-text))]" data-testid="proc-alert-po">Tidak ada PO terlambat atau tiba ≤ 7 hari</span>
              <span aria-hidden="true">·</span>
            </>)}
            <span data-testid="proc-kpi-gr">Penerimaan barang <b className="tabular-nums text-foreground">{k.gr_received ?? 0}</b>
              {' '}({k.gr_draft ?? 0} draf, {k.qc_pending ?? 0} belum diperiksa QC)</span>
            <span aria-hidden="true">·</span>
            <Button variant="link" size="sm" className="h-auto p-0" onClick={go('proc-suppliers')} disabled={!onNavigate}
              data-testid="proc-kpi-suppliers">
              Pemasok aktif <b className="tabular-nums">{k.suppliers_active ?? 0}</b> dari {k.suppliers_total ?? 0}
            </Button>
            <span aria-hidden="true">·</span>
            <Button variant="link" size="sm" className="h-auto p-0" onClick={go('proc-suppliers')} disabled={!onNavigate}
              data-testid="proc-kpi-price-rows">
              Baris daftar harga aktif <b className="tabular-nums">{k.price_list_rows ?? 0}</b>
            </Button>
            <span aria-hidden="true">·</span>
            <Button variant="link" size="sm" className="h-auto p-0" onClick={go('proc-accessory-pr')} disabled={!onNavigate}
              data-testid="proc-kpi-acc-pr">
              Request aksesoris <b className="tabular-nums">{k.accessory_pr_total ?? 0}</b>
              {' '}({k.accessory_pr_awaiting_approval ?? 0} menunggu persetujuan, {k.accessory_pr_pending ?? 0} berjalan)
            </Button>
          </p>
        </div>
      )}>
      {err && <Notice tone="danger" title="Dashboard gagal dimuat">{err}</Notice>}

      {(alerts.po_without_supplier_master || 0) > 0 && (
        <Notice tone="warning" testId="proc-alert-unlinked-supplier"
          title={`${alerts.po_without_supplier_master} PO belum tertaut Master Supplier`}
          action={
            <Button size="sm" variant="outline" onClick={() => onNavigate?.('proc-suppliers')}
              data-testid="proc-alert-goto-suppliers">
              Buka Master Supplier
            </Button>
          }>
          PO lama masih memakai nama pemasok teks bebas. Jalankan tarik data di Master Supplier supaya penilaian
          pemasok tidak terpecah oleh perbedaan ejaan.
        </Notice>
      )}

      {poPerhatian.length > 0 && (
        <Bagian judul="PO perlu perhatian" testId="proc-alert-po"
          keterangan="PO berjalan yang lewat tanggal terima atau dijadwalkan tiba 7 hari ke depan."
          alat={(
            <TombolUnduh namaBerkas="po-perlu-perhatian" namaLembar="PO perlu perhatian" baris={poPerhatian}
              testId="proc-alert-po-unduh"
              kolom={[
                { label: 'No. PO', nilai: (p) => p.po_number },
                { label: 'Pemasok', nilai: (p) => p.vendor_name || '' },
                { label: 'Tanggal terima', nilai: (p) => fmtDate(p.expected_delivery_date) },
                { label: 'Keadaan', nilai: (p) => (p.keadaan === 'terlambat' ? 'Terlambat' : 'Tiba ≤ 7 hari') },
              ]} />
          )}>
          <TabelData baris={poPerhatian} kunci={(p) => p._kunci} testId="proc-alert-po-table"
              onKlikBaris={onNavigate ? () => onNavigate('proc-purchase-orders') : undefined}
              kolom={[
                { kunci: 'po', label: 'No. PO', hp: 'judul', isi: (p) => <span className="font-mono text-xs">{p.po_number}</span> },
                { kunci: 'pemasok', label: 'Pemasok', hp: 'keterangan', isi: (p) => p.vendor_name || '—' },
                { kunci: 'tgl', label: 'Tanggal terima', isi: (p) => fmtDate(p.expected_delivery_date) },
                { kunci: 'keadaan', label: 'Keadaan', isi: (p) => (p.keadaan === 'terlambat'
                  ? <StatusBadge status="overdue" label="Terlambat" tone="danger" />
                  : <StatusBadge status="pending" label="Tiba ≤ 7 hari" tone="warning" />) },
              ]} />
        </Bagian>
      )}
        <Bagian judul="Dokumen per tahap" testId="proc-pipeline"
          alat={
            <TombolUnduh namaBerkas="dokumen-pengadaan-per-tahap" namaLembar="Per tahap" baris={tahapBaris}
              testId="proc-pipeline-unduh"
              kolom={[
                { label: 'Tahap', nilai: (t) => t.label },
                { label: 'Periode', nilai: (t) => t.periode },
                { label: 'Jumlah dokumen', nilai: (t) => t.jumlah },
                { label: 'Rincian status', nilai: (t) => t.rincian },
              ]} />
          }>
          <TabelData baris={tahapBaris} kunci={(t) => t.key} testId="proc-pipeline-table"
            kolom={[
              { kunci: 'tahap', label: 'Tahap', hp: 'judul', isi: (t) => <span className="font-medium">{t.label}</span> },
              { kunci: 'periode', label: 'Periode', hp: 'keterangan', isi: (t) => <span className="text-muted-foreground">{t.periode}</span> },
              { kunci: 'jumlah', label: 'Jumlah', rata: 'kanan', isi: (t) => <span className="tabular-nums">{t.jumlah}</span> },
              { kunci: 'rincian', label: 'Rincian status', isi: (t) => (t.rincian || <span className="text-muted-foreground">Belum ada dokumen</span>) },
            ]} />
        </Bagian>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Bagian judul="Permintaan terbaru" testId="proc-recent-pr"
          alat={recentPr.length > 0 && (
            <>
              <TombolUnduh namaBerkas="permintaan-terbaru" namaLembar="Permintaan" baris={recentPr} testId="proc-recent-pr-unduh"
                kolom={[
                  { label: 'No. permintaan', nilai: (r) => r.request_number },
                  { label: 'Judul', nilai: (r) => r.title },
                  { label: 'Estimasi (Rp)', nilai: (r) => Number(r.total_estimated || 0) },
                ]} />
              {onNavigate && (
                <Button variant="link" size="sm" onClick={() => onNavigate('proc-requests')}>
                  Semua<ArrowRight />
                </Button>
              )}
            </>
          )}>
          {recentPr.length === 0 ? <Kosong>Belum ada permintaan pengadaan.</Kosong> : (
            <TabelData baris={recentPr} testId="proc-recent-pr-table"
              kolom={[
                { kunci: 'no', label: 'No. permintaan', hp: 'judul', isi: (r) => <span className="font-mono text-xs">{r.request_number}</span> },
                { kunci: 'judul', label: 'Judul', hp: 'keterangan', isi: (r) => <span className="line-clamp-1">{r.title}</span> },
                { kunci: 'nilai', label: 'Estimasi', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtRp(r.total_estimated)}</span> },
              ]} />
          )}
        </Bagian>

        <Bagian judul="Purchase order terbaru" testId="proc-recent-po"
          alat={recentPo.length > 0 && (
            <>
              <TombolUnduh namaBerkas="po-terbaru" namaLembar="PO" baris={recentPo} testId="proc-recent-po-unduh"
                kolom={[
                  { label: 'No. PO', nilai: (p) => p.po_number },
                  { label: 'Pemasok', nilai: (p) => p.vendor_name || '' },
                  { label: 'Nilai (Rp)', nilai: (p) => Number(p.total_value || 0) },
                ]} />
              {onNavigate && (
                <Button variant="link" size="sm" onClick={() => onNavigate('proc-purchase-orders')}>
                  Semua<ArrowRight />
                </Button>
              )}
            </>
          )}>
          {recentPo.length === 0 ? <Kosong>Belum ada purchase order.</Kosong> : (
            <TabelData baris={recentPo} testId="proc-recent-po-table"
              kolom={[
                { kunci: 'no', label: 'No. PO', hp: 'judul', isi: (p) => <span className="font-mono text-xs">{p.po_number}</span> },
                { kunci: 'pemasok', label: 'Pemasok', hp: 'keterangan', isi: (p) => <span className="line-clamp-1">{p.vendor_name}</span> },
                { kunci: 'nilai', label: 'Nilai', rata: 'kanan', isi: (p) => <span className="tabular-nums">{fmtRp(p.total_value)}</span> },
              ]} />
          )}
        </Bagian>
      </div>
    </PageLayout>
  );
}

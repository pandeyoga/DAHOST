/**
 * RahazaHPPModule — "HPP per PO" (menu HPP › HPP per PO), SATU layar untuk Portal Produksi & Maklon.
 *
 * Tahap 9 (keputusan owner 7 Nov 2026 No. 6 & 13):
 *   • HPP aktual per PO = potongan (nilai dari cutting) + aksesoris yang diserahkan + upah CMT (tagihan) + permak.
 *     BOM hanya pembanding (kolom "Standar/pcs"); semua angka dari server (`core/hpp_aktual`).
 *   • Maklon: isian overhead/margin yang diketik sendiri dihapus — margin = harga jasa − HPP, otomatis.
 *   • 8 Nov 2026 (keputusan owner): margin maklon = MARGIN TEREALISASI (pendapatan pcs terkirim − biaya pcs terkirim,
 *     dasar sepadan). Total biaya sampai saat ini (termasuk bahan pcs yang belum dikirim) tampil terpisah.
 *   • Biaya umum produksi per pcs tampil sebagai INFORMASI (tidak masuk HPP).
 *   • Rekap upah jahit per baris (dulu menu Biaya Jahit) ada di rincian PO; tarif diubah di form PO.
 *   • Disaring per portal: Produksi = PO internal, Maklon = PO maklon (Keuangan: pilih jenis).
 *   • PANDUAN_UI: PageLayout · tabel · rincian PO dibuka di halaman (DetailPanel), konfirmasi lewat dialog aplikasi.
 *
 *   GET  /api/rahaza/hpp/po?business_type&search&status&date_from&date_to&client_id&page
 *   GET  /api/rahaza/hpp/po/{po_id}
 *   POST /api/costing/po-wip/{po_id}/clear       (tutup sisa biaya PO internal yang sudah ditutup)
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Calculator, Info, RefreshCw, Search } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import FilterChips from '@/components/ui/filter-chips';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import PaginationLite from '@/components/ui/pagination-lite';
import { Skeleton } from '@/components/ui/skeleton';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PageLayout, { DetailPanel } from './layout/PageLayout';
import { PageLayoutSatuBaris } from './engine/DataTable';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Input } from '@/components/ui/input';
import { ambilSemuaHalaman } from './engine/DataTable';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';
import PeriodPicker, { ALL_TIME, PERIOD_PRESETS, periodFromPreset } from './finance/PeriodPicker';
import { apiGet, apiPost } from '@/lib/api';

const PER_PAGE = 25;
const rp = (v) => (v === null || v === undefined ? '—' : `Rp ${Math.round(Number(v || 0)).toLocaleString('id-ID')}`);
const num = (v) => Number(v || 0).toLocaleString('id-ID', { maximumFractionDigits: 2 });
const pct = (v) => (v === null || v === undefined ? '—' : `${Number(v).toLocaleString('id-ID', { maximumFractionDigits: 1 })}%`);
const BULAN = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
const monthLabel = (ym) => {
  const [y, m] = String(ym || '').split('-');
  return m ? `${BULAN[Number(m) - 1] || m} ${y}` : '—';
};

const STATUS = {
  confirmed: ['Dikonfirmasi', 'info'], 'in production': ['Diproduksi', 'info'], 'in_production': ['Diproduksi', 'info'],
  'partially shipped': ['Terkirim sebagian', 'warning'], completed: ['Selesai', 'success'], closed: ['Ditutup', 'muted'],
  'closed short': ['Ditutup (kurang)', 'muted'], draft: ['Draf', 'muted'], cancelled: ['Dibatalkan', 'muted'],
};
function PoStatus({ status }) {
  const [label, tone] = STATUS[String(status || '').toLowerCase()] || [status || '—', 'default'];
  return <StatusBadge tone={tone} label={label} />;
}
const KIND_TONE = { potongan: 'info', aksesoris: 'default', bahan_pembantu: 'muted' };
const FIN_ROLES = ['superadmin', 'admin', 'owner', 'accounting', 'finance', 'staff_keuangan', 'manager_keuangan'];
const JENIS = { internal: 'Internal', maklon: 'Maklon' };

/** Jenis PO dari portal: Produksi = internal, Maklon = maklon, Keuangan = pilihan. */
export function portalBusinessType(portalId) {
  if (portalId === 'production') return 'internal';
  if (portalId === 'maklon') return 'maklon';
  return '';
}

export default function RahazaHPPModule({ portalId, userRole }) {
  const fixedType = portalBusinessType(portalId);
  const [jenis, setJenis] = useState(fixedType);
  const businessType = fixedType || jenis;
  const isMaklon = businessType === 'maklon';
  const [status, setStatus] = useState('');
  const [search, setSearch] = useState('');
  const [period, setPeriod] = useState(() => periodFromPreset('all'));
  const [clientId, setClientId] = useState('');
  const [clients, setClients] = useState([]);
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [detail, setDetail] = useState(null);
  const [residuals, setResiduals] = useState([]);
  const canClear = FIN_ROLES.includes(String(userRole || '').toLowerCase());

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const qs = new URLSearchParams({ page: String(page), per_page: String(PER_PAGE) });
      if (businessType) qs.set('business_type', businessType);
      if (status) qs.set('status', status);
      if (search.trim()) qs.set('search', search.trim());
      if (period.from) qs.set('date_from', period.from);
      if (period.to) qs.set('date_to', period.to);
      if (clientId && businessType !== 'internal') qs.set('client_id', clientId);
      setData(await apiGet(`/rahaza/hpp/po?${qs}`));
      // PO internal yang sudah ditutup tetapi masih menyisakan biaya di barang dalam proses (dulu tab "Sisa WIP per PO")
      if (businessType !== 'maklon') {
        apiGet('/costing/po-wip').then((d) => setResiduals(d?.items || [])).catch(() => setResiduals([]));
      } else setResiduals([]);
    } catch (e) {
      setError(e?.message || 'Gagal memuat HPP per PO');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [businessType, status, search, period, clientId, page]);

  useEffect(() => { load(); }, [businessType, status, period, clientId, page]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (businessType === 'internal') { setClients([]); return; }
    apiGet('/dewi/maklon/clients').then((d) => setClients(Array.isArray(d) ? d.filter((c) => c.status !== 'inactive') : [])).catch(() => setClients([]));
  }, [businessType]);

  const openDetail = useCallback(async (poId) => {
    if (detail?.po_id === poId) { setDetail(null); return; }
    setDetail({ po_id: poId, loading: true });
    try { setDetail(await apiGet(`/rahaza/hpp/po/${poId}`)); }
    catch (e) { toast.error(`Gagal memuat rincian HPP: ${e?.message || e}`); setDetail(null); }
  }, [detail?.po_id]);

  const items = data?.items || [];
  const counts = data?.counts || {};
  const sum = data?.summary || {};
  const oh = data?.overhead;
  const filtered = !!(status || search.trim() || clientId || period.preset !== 'all');
  const resetFilters = () => { setStatus(''); setSearch(''); setClientId(''); setPeriod(periodFromPreset('all')); setPage(1); };
  const totalPages = Math.max(1, Math.ceil((data?.total || 0) / PER_PAGE));
  const showMargin = isMaklon || (!businessType && items.some((r) => r.business_type === 'maklon'));

  return (
    <PageLayoutSatuBaris
      testId="hpp-po-page"
      title="HPP per PO"
      subtitle="HPP aktual = potongan + aksesoris yang diserahkan + upah CMT + permak. Biaya umum tidak masuk HPP."
      filters={<>
        <FilterChips value={status} onChange={(v) => { setStatus(v); setPage(1); }} testId="hpp-po-status" ariaLabel="Status PO"
          hideWhenEmpty={false}
          options={[{ key: '', label: 'Semua', count: counts.all ?? 0 }, { key: 'open', label: 'Berjalan', count: counts.open ?? 0 },
            { key: 'closed', label: 'Selesai/ditutup', count: counts.closed ?? 0 }]} />
        <div className="relative w-full sm:w-64">
          <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { setPage(1); load(); } }}
            placeholder="Cari PO, vendor, klien (Enter)" className="pl-8" data-testid="hpp-po-search" />
        </div>
        {!fixedType && (
          <SmartNativeSelect value={jenis} onChange={(e) => { setJenis(e.target.value); setPage(1); }} searchable={false}
            className="w-40" aria-label="Jenis PO" data-testid="hpp-po-jenis">
            <option value="">Semua jenis PO</option>
            <option value="internal">PO internal</option>
            <option value="maklon">PO maklon</option>
          </SmartNativeSelect>
        )}
        {businessType !== 'internal' && clients.length > 0 && (
          <SmartNativeSelect value={clientId} onChange={(e) => { setClientId(e.target.value); setPage(1); }}
            className="w-52" aria-label="Klien maklon" data-testid="hpp-po-client">
            <option value="">Semua klien maklon</option>
            {clients.map((c) => <option key={c.id} value={c.id}>{c.code ? `${c.code} — ${c.name}` : c.name}</option>)}
          </SmartNativeSelect>
        )}
        <PeriodPicker value={period} onChange={(p) => { setPeriod(p); setPage(1); }} presets={[ALL_TIME, ...PERIOD_PRESETS]} testId="hpp-po-period" />
      </>}
      tools={<>
        {/* Standar UI/UX v2: unduh Excel/CSV SEMUA PO hasil saringan (bukan hanya halaman ini). */}
        <TombolUnduh namaBerkas="hpp-per-po" namaLembar="HPP per PO" baris={items} testId="hpp-po-unduh"
          ambilSemua={() => ambilSemuaHalaman(({ page: pg, per_page }) => {
            const qs = new URLSearchParams({ page: String(pg), per_page: String(per_page) });
            if (businessType) qs.set('business_type', businessType);
            if (status) qs.set('status', status);
            if (search.trim()) qs.set('search', search.trim());
            if (period.from) qs.set('date_from', period.from);
            if (period.to) qs.set('date_to', period.to);
            if (clientId && businessType !== 'internal') qs.set('client_id', clientId);
            return apiGet(`/rahaza/hpp/po?${qs}`).then((d) => ({ ...d, total_pages: Math.ceil((d?.total || 0) / (d?.per_page || per_page)) }));
          }, { perHalaman: 100 })}
          kolom={[
            { label: 'PO', nilai: (r) => r.po_number }, { label: 'Jenis', nilai: (r) => JENIS[r.business_type] || '' },
            { label: 'Klien', nilai: (r) => r.client_name || '' }, { label: 'Vendor CMT', nilai: (r) => r.vendor_name || '' },
            { label: 'Status', nilai: (r) => r.status || '' }, { label: 'Pesan (pcs)', nilai: (r) => Number(r.qty_ordered) || 0 },
            { label: 'Lolos QC (pcs)', nilai: (r) => Number(r.qty_accepted) || 0 },
            { label: 'Potongan (Rp)', nilai: (r) => Number(r.cut_cost) || 0 }, { label: 'Aksesoris (Rp)', nilai: (r) => Number(r.accessory_cost) || 0 },
            { label: 'Upah CMT (Rp)', nilai: (r) => Number(r.cmt_cost) || 0 }, { label: 'Permak (Rp)', nilai: (r) => Number(r.permak_cost) || 0 },
            { label: 'Total HPP (Rp)', nilai: (r) => Number(r.total_hpp) || 0 },
            { label: 'HPP per pcs lolos QC (Rp)', nilai: (r) => (r.hpp_per_pcs == null ? '' : Number(r.hpp_per_pcs)) },
            { label: 'Bahan belum jadi barang (Rp)', nilai: (r) => Number(r.unabsorbed_cost) || 0 },
            { label: 'Harga jasa per pcs (Rp)', nilai: (r) => (r.selling_price_per_pcs == null ? '' : Number(r.selling_price_per_pcs)) },
            { label: 'Margin per pcs (Rp)', nilai: (r) => (r.margin_per_pcs == null ? '' : Number(r.margin_per_pcs)) },
            { label: 'Dikirim ke klien (pcs)', nilai: (r) => (r.business_type === 'maklon' ? Number(r.qty_dispatched) || 0 : '') },
            { label: 'Pendapatan jasa (Rp)', nilai: (r) => (r.business_type === 'maklon' ? Number(r.revenue) || 0 : '') },
            { label: 'Biaya pcs terkirim (Rp)', nilai: (r) => (r.realized_cost == null ? '' : Number(r.realized_cost)) },
            { label: 'Margin terealisasi (Rp)', nilai: (r) => (r.margin_realized == null ? '' : Number(r.margin_realized)) },
          ]} />
        <Button type="button" variant="outline" size="icon" onClick={load} title="Muat ulang" aria-label="Muat ulang" data-testid="hpp-po-refresh">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </>}
      summary={<>
        {error && <Notice tone="danger" icon={AlertTriangle} title="Gagal memuat data" testId="hpp-po-error">{error}</Notice>}
        {(sum.po_count > 0) && (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <StatTile testId="hpp-kpi-total" label={showMargin ? 'Total biaya sampai saat ini' : 'Total HPP aktual'} value={rp(sum.total_hpp)}
              sub={`${num(sum.po_count)} PO · potongan + aksesoris + upah CMT + permak (termasuk bahan pcs yang belum diterima)`} />
            <StatTile testId="hpp-kpi-pcs" label="HPP per pcs lolos QC" value={sum.hpp_per_pcs == null ? '—' : rp(sum.hpp_per_pcs)} accent="primary"
              sub={sum.hpp_per_pcs == null ? 'belum ada pcs lolos QC' : `biaya yang terserap ÷ ${num(sum.qty_accepted)} pcs lolos QC`} />
            {showMargin ? (
              <StatTile testId="hpp-kpi-margin" label="Margin terealisasi (maklon)" value={rp(sum.margin_realized ?? sum.margin)}
                accent={Number(sum.margin_realized ?? sum.margin) < 0 ? 'danger' : 'success'}
                sub={sum.margin_realized == null
                  ? `pendapatan ${rp(sum.revenue)} − total HPP · ${pct(sum.margin_pct)}`
                  : `pendapatan ${rp(sum.revenue)} − biaya pcs terkirim ${rp(sum.realized_cost)} · ${pct(sum.margin_realized_pct)}`} />
            ) : (
              <StatTile testId="hpp-kpi-selisih" label="Bahan belum jadi barang" value={rp(sum.unabsorbed_cost)}
                sub="bahan untuk pcs yang belum/tidak diterima; ditutup saat PO ditutup" />
            )}
            <StatTile testId="hpp-kpi-overhead" label="Biaya umum per pcs" value={oh?.per_pcs == null ? 'belum ada data' : rp(oh.per_pcs)}
              sub={`informasi, tidak masuk HPP · ${monthLabel(oh?.month)}`} />
          </div>
        )}
        {data?.capped && (
          <Notice tone="warning" icon={AlertTriangle} testId="hpp-po-capped">
            Ringkasan dan daftar dihitung dari 500 PO terbaru yang cocok dengan penyaring. Persempit penyaring (periode, jenis, klien) agar semua PO terhitung.
          </Notice>
        )}
        {residuals.length > 0 && (
          <Notice tone="warning" icon={AlertTriangle} testId="hpp-po-residuals"
            title={`${residuals.length} PO yang sudah ditutup masih menyisakan biaya di barang dalam proses`}>
            {residuals.slice(0, 8).map((r) => (
              <Button type="button" key={r.po_id} variant="link" size="sm" className="h-auto p-0 mr-3" onClick={() => openDetail(r.po_id)}
                data-testid={`hpp-residual-${r.po_number}`}>{r.po_number} · {rp(r.residual)}</Button>
            ))}
          </Notice>
        )}
        {oh && sum.po_count > 0 && (
          <p className="text-sm text-muted-foreground" data-testid="hpp-overhead-sentence">
            Biaya umum produksi {monthLabel(oh.month)} ({oh.entity === 'SMU' ? 'CV Sukma' : 'CV Dewi Aditya'}): {rp(oh.overhead)}
            {' '}÷ {num(oh.pcs)} pcs lolos QC{oh.per_pcs != null ? ` = ${rp(oh.per_pcs)} per pcs` : ' (belum bisa dibagi)'}. Angka ini informasi saja dan tidak masuk HPP.
          </p>
        )}
      </>}
      detail={detail && <PoHppDetail detail={detail} canClear={canClear} onClose={() => setDetail(null)}
        onChanged={async () => { await load(); const id = detail.po_id; setDetail(null); await openDetail(id); }} />}
      footer={(data?.total || 0) > PER_PAGE && (
        <PaginationLite page={page} totalPages={totalPages} total={data?.total || 0} pageSize={PER_PAGE} onPageChange={setPage} />
      )}
    >
      <GlassCard className="p-0 overflow-x-auto">
        {loading && !items.length ? (
          <div className="space-y-2 p-4">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
        ) : items.length === 0 ? (
          <div data-testid="hpp-po-empty">
            {filtered ? (
              <EmptyState icon={Calculator} title="Tidak ada PO yang cocok dengan penyaring"
                description="Ubah atau hapus penyaring untuk melihat PO lain."
                action={<Button type="button" variant="outline" size="sm" onClick={resetFilters}>Tampilkan semua PO</Button>} />
            ) : (
              <EmptyState icon={Calculator} title="Belum ada PO dengan biaya"
                description="HPP aktual muncul setelah PO dikonfirmasi dan bahan diserahkan ke CMT." />
            )}
          </div>
        ) : (
          <Table data-testid="hpp-po-table">
            <TableHeader><TableRow>
              <TableHead>PO</TableHead>
              {!fixedType && <TableHead>Jenis</TableHead>}
              <TableHead>{isMaklon ? 'Klien · vendor CMT' : 'Vendor CMT'}</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Pesan</TableHead>
              <TableHead className="text-right">Lolos QC</TableHead>
              <TableHead className="text-right">Bahan</TableHead>
              <TableHead className="text-right">Upah CMT</TableHead>
              <TableHead className="text-right">Permak</TableHead>
              <TableHead className="text-right">Total HPP</TableHead>
              <TableHead className="text-right">HPP/pcs</TableHead>
              {showMargin && <TableHead className="text-right">Harga jasa/pcs</TableHead>}
              {showMargin && <TableHead className="text-right">Margin/pcs</TableHead>}
            </TableRow></TableHeader>
            <TableBody>
              {items.map((r) => (
                <TableRow key={r.po_id} data-testid={`hpp-po-row-${r.po_number}`}
                  className={detail?.po_id === r.po_id ? 'bg-[hsl(var(--primary)/0.06)]' : ''}>
                  <TableCell className="whitespace-nowrap">
                    <Button type="button" variant="link" size="sm" className="h-auto p-0 font-semibold" onClick={() => openDetail(r.po_id)}
                      data-testid={`hpp-po-open-${r.po_number}`}>{r.po_number}</Button>
                  </TableCell>
                  {!fixedType && <TableCell>{JENIS[r.business_type] || '—'}</TableCell>}
                  <TableCell className="text-sm">
                    {isMaklon && r.client_name ? <span className="block">{r.client_name}</span> : null}
                    <span className={isMaklon ? 'text-xs text-muted-foreground' : ''}>{r.vendor_name || 'Belum ada penjahit'}</span>
                  </TableCell>
                  <TableCell><PoStatus status={r.status} /></TableCell>
                  <TableCell className="text-right tabular-nums">{num(r.qty_ordered)}</TableCell>
                  <TableCell className="text-right tabular-nums">{num(r.qty_accepted)}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">{rp(r.cut_cost + r.accessory_cost)}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">
                    {rp(r.cmt_cost)}
                    {r.items_missing_rate > 0 && <span className="block text-xs text-[hsl(var(--warning-text))]">{r.items_missing_rate} baris tanpa tarif</span>}
                  </TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">{rp(r.permak_cost)}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap font-semibold">{rp(r.total_hpp)}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">{rp(r.hpp_per_pcs)}</TableCell>
                  {showMargin && <TableCell className="text-right tabular-nums whitespace-nowrap">{r.business_type === 'maklon' ? rp(r.selling_price_per_pcs) : '—'}</TableCell>}
                  {showMargin && (
                    <TableCell className={`text-right tabular-nums whitespace-nowrap ${Number(r.margin_per_pcs) < 0 ? 'text-[hsl(var(--danger-text))]' : ''}`}>
                      {r.business_type === 'maklon' ? rp(r.margin_per_pcs) : '—'}
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </GlassCard>
    </PageLayoutSatuBaris>
  );
}

/** Rincian satu PO — di halaman, di atas tabel (PANDUAN_UI G13). */
function PoHppDetail({ detail, canClear, onClose, onChanged }) {
  const [busy, setBusy] = useState(false);
  const d = detail;
  const maklon = d.business_type === 'maklon';
  const wip = d.wip;
  const residual = Number(wip?.residual || 0);
  const rows = useMemo(() => d.lines || [], [d.lines]);
  if (d.loading) {
    return <DetailPanel title="Memuat rincian HPP…" onClose={onClose} testId="hpp-po-detail"><Skeleton className="h-32 w-full" /></DetailPanel>;
  }

  const clearWip = async () => {
    const ok = await confirmDialog({
      title: `Tutup sisa biaya PO ${d.po_number}?`,
      body: `Sisa ${rp(Math.abs(residual))} dipindah dari barang dalam proses ke akun selisih biaya PO dengan satu jurnal.`,
      confirmLabel: 'Tutup sisa biaya',
    });
    if (!ok) return;
    setBusy(true);
    try {
      await apiPost(`/costing/po-wip/${d.po_id}/clear`, {});
      toast.success(`Sisa biaya PO ${d.po_number} dipindah ke selisih biaya PO.`);
      await onChanged();
    } catch (e) { toast.error(e?.message || 'Gagal menutup sisa biaya'); }
    finally { setBusy(false); }
  };

  return (
    <DetailPanel testId="hpp-po-detail" closeTestId="hpp-po-detail-close" onClose={onClose}
      title={`${d.po_number} · ${maklon ? (d.client_name || 'Klien maklon') : 'PO internal'}`}
      description={`Vendor CMT ${d.vendor_name || '—'} · pesan ${num(d.qty_ordered)} · dikirim ke CMT ${num(d.qty_sent)}${d.sent_basis === 'pesanan' ? ' (belum ada surat jalan, dihitung dari pesanan)' : ''} · lolos QC ${num(d.qty_accepted)} pcs`}
      actions={canClear && !maklon && d.closed && Math.abs(residual) >= 0.01 && (
        <Button type="button" onClick={clearWip} disabled={busy} data-testid="hpp-po-clear-wip">Tutup sisa biaya</Button>
      )}>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Figure label={maklon ? 'Total biaya sampai saat ini' : 'Total HPP aktual'} value={rp(d.total_hpp)} testId="hpp-detail-total" />
        <Figure label="HPP per pcs lolos QC" value={rp(d.hpp_per_pcs)} testId="hpp-detail-per-pcs" strong />
        {maklon ? (
          <>
            <Figure label="Harga jasa per pcs" value={rp(d.selling_price_per_pcs)} testId="hpp-detail-price" />
            <Figure label="Margin per pcs (harga jasa − HPP)" value={`${rp(d.margin_per_pcs)} · ${pct(d.margin_pct)}`} testId="hpp-detail-margin" />
          </>
        ) : (
          <>
            <Figure label="Masuk barang jadi" value={rp(d.fg_layer_value)} testId="hpp-detail-fg" />
            <Figure label="Bahan untuk pcs tidak diterima" value={rp(d.unabsorbed_cost)} testId="hpp-detail-unabsorbed" />
          </>
        )}
      </div>

      <Table data-testid="hpp-detail-components">
        <TableHeader><TableRow>
          <TableHead>Komponen HPP</TableHead><TableHead className="text-right">Nilai</TableHead>
          <TableHead className="text-right">Bagian pcs lolos QC</TableHead><TableHead className="text-right">Per pcs</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {(d.components || []).map((c) => (
            <TableRow key={c.key} data-testid={`hpp-comp-${c.key}`}>
              <TableCell>{c.label}</TableCell>
              <TableCell className="text-right tabular-nums">{rp(c.amount)}</TableCell>
              <TableCell className="text-right tabular-nums">{rp(c.absorbed)}</TableCell>
              <TableCell className="text-right tabular-nums">{rp(c.per_pcs)}</TableCell>
            </TableRow>
          ))}
          <TableRow className="font-semibold">
            <TableCell>Total HPP aktual</TableCell>
            <TableCell className="text-right tabular-nums">{rp(d.total_hpp)}</TableCell>
            <TableCell className="text-right tabular-nums">{rp(d.absorbed_cost)}</TableCell>
            <TableCell className="text-right tabular-nums">{rp(d.hpp_per_pcs)}</TableCell>
          </TableRow>
          {Number(d.unabsorbed_cost || 0) > 0 && (
            <TableRow data-testid="hpp-comp-selisih">
              <TableCell colSpan={2} className="text-muted-foreground">
                Bahan untuk {num(Math.max(0, Number(d.qty_sent || 0) - Number(d.qty_accepted || 0)))} pcs yang {d.closed ? 'tidak diterima' : 'belum/tidak diterima'} — tetap biaya PO{maklon ? '' : '; ditutup sebagai selisih biaya PO saat PO ditutup'}
              </TableCell>
              <TableCell className="text-right tabular-nums text-muted-foreground">{rp(d.unabsorbed_cost)}</TableCell>
              <TableCell />
            </TableRow>
          )}
          {maklon && (
            <TableRow>
              <TableCell>Pendapatan jasa ({num(d.qty_dispatched)} pcs dikirim ke klien × harga jasa) · margin terealisasi = pendapatan − biaya {num(d.qty_dispatched)} pcs terkirim ({rp(d.realized_cost)})</TableCell>
              <TableCell className="text-right tabular-nums">{rp(d.revenue)}</TableCell>
              <TableCell colSpan={2} className={`text-right tabular-nums ${Number(d.margin_realized ?? d.margin) < 0 ? 'text-[hsl(var(--danger-text))]' : ''}`} data-testid="hpp-detail-margin-total">margin terealisasi {rp(d.margin_realized ?? d.margin)}{d.margin_realized_pct != null ? ` · ${pct(d.margin_realized_pct)}` : ''}</TableCell>
            </TableRow>
          )}
          {maklon && d.margin_realized != null && (
            <TableRow data-testid="hpp-detail-margin-sd-kini">
              <TableCell className="text-muted-foreground">Pendapatan − total biaya sampai saat ini (termasuk {rp(d.cost_not_shipped)} biaya pcs yang belum dikirim ke klien)</TableCell>
              <TableCell />
              <TableCell colSpan={2} className="text-right tabular-nums text-muted-foreground">{rp(d.margin)}</TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      <Notice tone="info" icon={Info} testId="hpp-detail-overhead" title={`Biaya umum per pcs: ${d.overhead_info?.per_pcs == null ? 'belum ada data' : rp(d.overhead_info.per_pcs)} — informasi, tidak masuk HPP`}>
        {(d.overhead_info?.months || []).length > 0
          ? `${d.overhead_info.months.map((m) => `${monthLabel(m.month)}: ${rp(m.overhead)} ÷ ${num(m.pcs)} pcs lolos QC${m.per_pcs != null ? ` = ${rp(m.per_pcs)}/pcs` : ''} (PO ini ${num(m.pcs_po)} pcs)`).join(' · ')}.`
          : 'Belum ada barang PO ini yang lolos QC, jadi biaya umumnya belum bisa dibagi.'}
        {Number(d.aux_cost_excluded || 0) > 0 && ` Bahan pembantu (benang dsb.) ${rp(d.aux_cost_excluded)} ikut terkirim; dibebankan langsung ke biaya produksi, tidak masuk HPP.`}
      </Notice>

      {(d.gaps || []).length > 0 && (
        <Notice tone="warning" icon={AlertTriangle} title="Yang belum lengkap" testId="hpp-detail-gaps">
          <ul className="list-disc pl-4 space-y-0.5">{d.gaps.map((g, i) => <li key={i}>{g}</li>)}</ul>
        </Notice>
      )}

      <p className="text-sm font-semibold text-foreground">Per baris PO — upah jahit & bahan per pcs</p>
      <Table data-testid="hpp-detail-lines">
        <TableHeader><TableRow>
          <TableHead>Barang</TableHead><TableHead className="text-right">Pesan</TableHead><TableHead className="text-right">Dikirim</TableHead>
          <TableHead className="text-right">Lolos QC</TableHead><TableHead className="text-right">Tarif jahit/pcs</TableHead>
          <TableHead className="text-right">Potongan/pcs</TableHead><TableHead className="text-right">Aksesoris/pcs</TableHead>
          {!maklon && <TableHead className="text-right">Standar BOM/pcs</TableHead>}
          {maklon && <TableHead className="text-right">Harga jasa/pcs</TableHead>}
        </TableRow></TableHeader>
        <TableBody>
          {rows.map((ln) => (
            <TableRow key={ln.po_item_id} data-testid={`hpp-line-${ln.sku}`}>
              <TableCell>
                <span className="block">{ln.product_name || ln.sku || '—'}</span>
                <span className="text-xs text-muted-foreground">{[ln.sku, ln.color, ln.size].filter(Boolean).join(' · ')}</span>
              </TableCell>
              <TableCell className="text-right tabular-nums">{num(ln.qty_ordered)}</TableCell>
              <TableCell className="text-right tabular-nums">{num(ln.qty_sent)}</TableCell>
              <TableCell className="text-right tabular-nums">{num(ln.qty_accepted)}</TableCell>
              <TableCell className={`text-right tabular-nums ${Number(ln.cmt_rate) > 0 ? '' : 'text-[hsl(var(--warning-text))]'}`}>
                {Number(ln.cmt_rate) > 0 ? rp(ln.cmt_rate) : 'belum diisi'}
              </TableCell>
              <TableCell className="text-right tabular-nums">{rp(ln.cut_per_pcs)}</TableCell>
              <TableCell className="text-right tabular-nums">{rp(ln.accessory_per_pcs)}</TableCell>
              {!maklon && <TableCell className="text-right tabular-nums text-muted-foreground">{rp(ln.standard_per_pcs)}</TableCell>}
              {maklon && <TableCell className="text-right tabular-nums">{rp(ln.selling_price)}</TableCell>}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="text-xs text-muted-foreground">Tarif jahit diubah di form PO (kolom upah jahit) sampai tagihan CMT terbit. {!maklon && 'Standar BOM = bahan BOM × harga master + tarif jahit — pembanding, bukan HPP.'}</p>

      <p className="text-sm font-semibold text-foreground">Bahan & aksesoris yang diserahkan ({(d.issue_lines || []).length})</p>
      {(d.issue_lines || []).length === 0 ? (
        <EmptyState icon={Calculator} className="py-6" title="Belum ada penyerahan bahan" description="Bahan tercatat saat Kirim ke CMT atau permintaan aksesoris untuk PO ini." />
      ) : (
        <Table data-testid="hpp-detail-issues">
          <TableHeader><TableRow>
            <TableHead>Dokumen</TableHead><TableHead>Barang</TableHead><TableHead>Jenis</TableHead>
            <TableHead className="text-right">Qty</TableHead><TableHead className="text-right">Harga</TableHead>
            <TableHead className="text-right">Nilai</TableHead><TableHead>Asal harga</TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {d.issue_lines.map((ln, i) => (
              <TableRow key={`${ln.doc}-${ln.material_id}-${i}`}>
                <TableCell className="text-xs whitespace-nowrap">{ln.doc || ln.source}</TableCell>
                <TableCell>{ln.material_name || ln.material_code}<span className="block text-xs text-muted-foreground">{ln.material_code}</span></TableCell>
                <TableCell><StatusBadge tone={KIND_TONE[ln.kind] || 'default'} label={ln.kind_label} /></TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap">{num(ln.qty)} {ln.unit}</TableCell>
                <TableCell className="text-right tabular-nums">{rp(ln.unit_cost)}</TableCell>
                <TableCell className="text-right tabular-nums">{rp(ln.value)}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{ln.cost_source_label}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      {!maklon && wip && !wip.error && (wip.groups || []).length > 0 && (
        <>
          <p className="text-sm font-semibold text-foreground" data-testid="hpp-detail-wip-title">
            Barang dalam proses PO ini — sisa {rp(residual)}{d.closed ? '' : ' (ditutup otomatis saat PO ditutup)'}
          </p>
          <Table data-testid="hpp-detail-wip">
            <TableHeader><TableRow>
              <TableHead>Sumber</TableHead><TableHead className="text-right">Masuk</TableHead>
              <TableHead className="text-right">Keluar</TableHead><TableHead className="text-right">Bersih</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {wip.groups.map((g) => (
                <TableRow key={g.source}>
                  <TableCell>{g.label}</TableCell>
                  <TableCell className="text-right tabular-nums">{rp(g.debit)}</TableCell>
                  <TableCell className="text-right tabular-nums">{rp(g.credit)}</TableCell>
                  <TableCell className="text-right tabular-nums">{rp(g.net)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      )}
    </DetailPanel>
  );
}

/** Angka ringkas di dalam panel (tanpa kartu di dalam kartu). */
function Figure({ label, value, testId, strong }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`text-lg font-semibold tabular-nums ${strong ? 'text-[hsl(var(--primary))]' : 'text-foreground'}`} data-testid={testId}>{value}</p>
    </div>
  );
}

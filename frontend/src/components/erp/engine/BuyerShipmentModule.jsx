/**
 * BuyerShipmentModule — "Kirim hasil": surat jalan barang jadi (Portal Produksi: ke gudang DA ·
 * Portal Maklon: ke klien). Satu surat jalan bisa dikirim bertahap (dispatch #1, #2, … nomor tetap).
 *
 * Tahap 9 (7 Nov 2026):
 *   • Keputusan 2 — tampilan IDENTIK di dua portal; semua tampilan disaring per portal
 *     (`?business_type=`): daftar surat jalan, kekurangan kirim, barang belum sampai di klien,
 *     pilihan PO dan penerimaan CMT sumber.
 *   • Cetakan PageLayout: tabel + rincian di bawah barisnya (RowDetail); formulir surat jalan dan
 *     rincian surat jalan dibuka DI HALAMAN (DetailPanel); popup hanya isian pendek (qty diterima,
 *     keputusan selisih) dan konfirmasi hapus.
 *   • "Laporan selisih terima" tetap satu tampilan di sini, isinya komponen bersama
 *     `BuyerReceiptVarianceReport` (endpoint `/buyer-receipt-variance`, pemilik: Laporan Selisih).
 *
 * Angka "sisa bisa kirim" SELALU dari backend (`/api/buyer-dispatch-capacity`, FASE E) — rumus yang sama
 * dengan pagar yang menolak saat Simpan.
 */
import { Fragment, useState, useEffect, useMemo, useCallback } from 'react';
import {
  Plus, Eye, Trash2, Package, CheckCircle, Download, History, ClipboardCheck, RefreshCw, Search, Loader2,
  PackageSearch, Info,
} from 'lucide-react';
import { toast } from 'sonner';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Button } from '@/components/ui/button';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Checkbox } from '@/components/ui/checkbox';
import { Textarea } from '@/components/ui/textarea';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import FilterChips from '@/components/ui/filter-chips';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PageLayout, { DetailPanel, RowDetail, RowToggle } from '../layout/PageLayout';
import { PageLayoutSatuBaris } from './DataTable';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';
import { Field } from './FormDialog';
import FormPopup from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Input } from '@/components/ui/input';
import FileAttachmentPanel from './FileAttachmentPanel';
import ImportExportPanel from './ImportExportPanel';
import BuyerReceiptVarianceReport from './BuyerReceiptVarianceReport';
import { BizBadge } from './BusinessTypeBadge';
import { apiGet, apiPut, apiDelete, apiFetch, apiPost } from '../../../lib/api';
import { postWithOverQtyReason } from '../../../lib/overQty';
import { todayWIB } from '../../../lib/waktu';
import { formatDateID } from '@/lib/format';
import { portalBusinessType, portalQuery } from '@/lib/portalScope';

const fmtNum = (v) => Number(v || 0).toLocaleString('id-ID');
const fmtRp = (v) => `Rp ${Math.round(Number(v || 0)).toLocaleString('id-ID')}`;
const fmtDate = (d) => (d ? formatDateID(d) : '—');
const shipStatus = (pct) => (pct >= 100 ? ['Terkirim penuh', 'success'] : pct > 0 ? ['Terkirim sebagian', 'warning'] : ['Menunggu', 'muted']);
const BUYER_RESOLUTIONS = [
  ['dikirim_ulang', 'Akan dikirim ulang (barang ketinggalan / salah hitung)'],
  ['tanggungan_cmt', 'Hilang — ditanggung vendor CMT (keputusan Keuangan)'],
  ['tanggungan_da', 'Hilang — ditanggung DA (keputusan Keuangan)'],
  ['dibatalkan', 'Batalkan (qty diterima salah dicatat)'],
];

async function downloadBlob(path, filename) {
  const res = await apiFetch(path);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function BuyerShipmentModule({ userRole, hasPerm = () => false, portalId }) {
  // Pemisahan data per proses bisnis: Portal Produksi = internal, Portal Maklon = maklon.
  const businessType = portalBusinessType(portalId);
  const receiverLabel = businessType === 'internal' ? 'gudang DA' : businessType === 'maklon' ? 'klien' : 'pembeli';
  const [shipments, setShipments] = useState([]);
  const [pos, setPOs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState('list');            // list | variance | outstanding | shorts
  const [search, setSearch] = useState('');
  // 'buyer' = surat jalan ke penerima (bawaan), 'da' = deklarasi vendor → DA, 'all' = semua
  const [recvFilter, setRecvFilter] = useState('buyer');
  const [bizFilter, setBizFilter] = useState('all');   // hanya bila dibuka di luar dua portal
  const [expanded, setExpanded] = useState({});
  const [shipDetail, setShipDetail] = useState({});    // {id: 'loading' | detail}
  const [panel, setPanel] = useState(null);            // {kind:'form', continueShip, poId} | {kind:'detail', data}
  const [recvItem, setRecvItem] = useState(null);
  const [buyerShorts, setBuyerShorts] = useState({ items: [], total_qty_open: 0 });
  const [resolveBShort, setResolveBShort] = useState(null);
  // FASE E — kekurangan kirim
  const [outstanding, setOutstanding] = useState({ items: [], buyers: [], totals: null });
  const [outLoading, setOutLoading] = useState(false);
  const [outBuyer, setOutBuyer] = useState('');
  const [outShowSettled, setOutShowSettled] = useState('open');

  const canCreate = ['superadmin', 'admin'].includes(userRole) || hasPerm('shipment.create');
  const canEdit = canCreate;
  const canForceEdit = ['superadmin', 'admin'].includes(userRole);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [sData, sh, allPOs] = await Promise.all([
        apiGet(`/buyer-shipments${portalQuery(businessType)}`),
        apiGet(`/buyer-shorts${portalQuery(businessType, { status: 'open' })}`).catch(() => ({ items: [], total_qty_open: 0 })),
        apiGet(`/production-pos${portalQuery(businessType)}`).catch(() => []),
      ]);
      setShipments(Array.isArray(sData) ? sData : []);
      setBuyerShorts(sh && typeof sh === 'object' ? sh : { items: [], total_qty_open: 0 });
      // PO yang masih punya sisa untuk dikirim
      setPOs((Array.isArray(allPOs) ? allPOs : []).filter((p) =>
        ['In Production', 'Completed', 'Distributed'].includes(p.status) && (p.remaining_qty_to_ship || p.total_qty) > 0));
    } catch (e) {
      toast.error(`Gagal memuat surat jalan: ${e.message || e}`);
      setShipments([]); setPOs([]);
    } finally {
      setLoading(false);
    }
  }, [businessType]);
  useEffect(() => { fetchAll(); }, [fetchAll]);

  const loadOutstanding = useCallback(async (buyer = outBuyer, settled = outShowSettled) => {
    setOutLoading(true);
    try {
      const res = await apiGet(`/buyer-dispatch-outstanding${portalQuery(businessType, {
        buyer, include_settled: settled === 'all' ? '1' : '' })}`);
      setOutstanding((prev) => ({
        items: Array.isArray(res?.items) ? res.items : [],
        // daftar pembeli dari muatan TANPA saringan supaya pilihan tidak menyusut sendiri
        buyers: (res?.buyers?.length ? res.buyers : prev.buyers) || [],
        totals: res?.totals || null,
      }));
    } catch (e) {
      toast.error(`Gagal memuat kekurangan kirim: ${e.message || 'kesalahan jaringan'}`);
      setOutstanding({ items: [], buyers: [], totals: null });
    } finally { setOutLoading(false); }
  }, [businessType, outBuyer, outShowSettled]);

  const changeView = (v) => { setView(v); if (v === 'outstanding') loadOutstanding(); };
  const refresh = () => { fetchAll(); if (view === 'outstanding') loadOutstanding(); };

  const toggleExpand = async (id) => {
    const willOpen = !expanded[id];
    setExpanded((p) => ({ ...p, [id]: willOpen }));
    if (willOpen && !shipDetail[id]) {
      setShipDetail((p) => ({ ...p, [id]: 'loading' }));
      try {
        const d = await apiGet(`/buyer-shipments/${id}`);
        setShipDetail((p) => ({ ...p, [id]: d || {} }));
      } catch { setShipDetail((p) => ({ ...p, [id]: {} })); }
    }
  };

  const openDetail = async (row) => {
    try {
      setPanel({ kind: 'detail', data: await apiGet(`/buyer-shipments/${row.id}`) });
    } catch (e) { toast.error(e.message || 'Gagal memuat rincian'); }
  };

  const handleDelete = async (row) => {
    if (!(await confirmDialog({ title: `Hapus surat jalan ${row.shipment_number}?`, body: 'Stok barang jadi yang sudah keluar dikembalikan.',
      confirmLabel: 'Hapus surat jalan', danger: true }))) return;
    try {
      await apiDelete(`/buyer-shipments/${row.id}`);
      toast.success(`Surat jalan ${row.shipment_number} dihapus`);
      fetchAll();
    } catch (e) { toast.error(e.message || 'Gagal menghapus'); }
  };

  const downloadPDF = async (row) => {
    try { await downloadBlob(`/export-pdf?type=buyer-shipment&id=${row.id}`, `Surat-Jalan-${row.shipment_number || row.id}.pdf`); }
    catch (e) { toast.error(`Gagal mengunduh PDF: ${e.message}`); }
  };

  // ── Papan sisa kirim per PO (angka dari /buyer-dispatch-outstanding, tanpa rumus baru) ──
  const poBoard = useMemo(() => {
    const map = new Map();
    for (const r of (outstanding.items || [])) {
      const key = r.po_id || r.po_number || '-';
      const g = map.get(key) || { key, po_id: r.po_id, po_number: r.po_number || '-', buyer: r.buyer || '', ordered: 0, dispatched: 0, shippable: 0, remaining: 0 };
      g.ordered += Number(r.ordered || 0);
      g.dispatched += Number(r.dispatched || 0);
      g.shippable += Number(r.shippable || 0);
      g.remaining += Number(r.remaining_vs_order || 0);
      if (!g.buyer && r.buyer) g.buyer = r.buyer;
      map.set(key, g);
    }
    return Array.from(map.values()).map((g) => ({
      ...g,
      pct: g.ordered > 0 ? Math.min(100, Math.round((g.dispatched / g.ordered) * 100)) : 0,
      openShip: shipments.find((s) => {
        const ids = (s.po_ids?.length ? s.po_ids : [s.po_id]).filter(Boolean);
        return ids.includes(g.po_id) && (s.progress_pct || 0) < 100;
      }) || null,
    })).sort((a, b) => b.shippable - a.shippable || b.remaining - a.remaining);
  }, [outstanding.items, shipments]);

  const exportOutstandingCSV = () => {
    const rows = outstanding.items || [];
    if (rows.length === 0) { toast.error('Tidak ada data untuk diunduh'); return; }
    const head = ['No. PO', 'Penerima', 'SKU', 'Produk', 'Ukuran', 'Warna', 'Qty pesan', 'Sumber', 'Siap kirim',
      'Hasil permak', 'Sudah dikirim', 'Sisa pesanan', 'Sisa bisa kirim', 'Stok barang jadi'];
    const esc = (v) => { const s = v == null ? '' : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const body = rows.map((r) => [r.po_number, r.buyer, r.sku, r.product_name, r.size, r.color, r.ordered,
      r.source === 'internal' ? 'produksi internal' : 'CMT', r.source === 'internal' ? r.internal_produced : r.good_from_cmt,
      r.reworked_ok, r.dispatched, r.remaining_vs_order, r.shippable, r.fg_stock == null ? '' : Math.round(r.fg_stock)].map(esc).join(','));
    const url = URL.createObjectURL(new Blob([`﻿${[head.join(','), ...body].join('\n')}`], { type: 'text/csv;charset=utf-8;' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `kekurangan-kirim-${todayWIB()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success(`${rows.length} baris diunduh`);
  };

  // ── Saringan daftar ───────────────────────────────────────────────────────
  const isToBuyer = (s) => (s.receiver_type || 'buyer') !== 'da';
  const q = search.trim().toLowerCase();
  const byBiz = shipments.filter((s) => businessType || bizFilter === 'all'
    || (bizFilter === 'maklon' ? s.business_type === 'maklon' : s.business_type !== 'maklon'));
  const recvCounts = { buyer: byBiz.filter(isToBuyer).length, da: byBiz.filter((s) => !isToBuyer(s)).length, all: byBiz.length };
  const filteredShipments = useMemo(() => byBiz
    .filter((s) => (recvFilter === 'all' ? true : recvFilter === 'da' ? !isToBuyer(s) : isToBuyer(s)))
    .filter((s) => !q || [s.shipment_number, s.po_number, s.customer_name, ...(s.po_numbers || [])]
      .some((v) => String(v || '').toLowerCase().includes(q))),
  [byBiz, recvFilter, q]); // eslint-disable-line react-hooks/exhaustive-deps
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(filteredShipments, 25);
  const fullyShipped = filteredShipments.filter((s) => (s.progress_pct || 0) >= 100).length;
  const partialShipped = filteredShipments.filter((s) => (s.progress_pct || 0) > 0 && (s.progress_pct || 0) < 100).length;
  const shortRows = (buyerShorts.items || []).filter((s) => !q || [s.short_number, s.shipment_number, s.po_number, s.customer_name, s.sku]
    .some((v) => String(v || '').toLowerCase().includes(q)));
  const outRows = (outstanding.items || []).filter((r) => !q || [r.po_number, r.buyer, r.sku, r.product_name]
    .some((v) => String(v || '').toLowerCase().includes(q)));

  const viewOptions = [
    { key: 'shipment-list', label: 'Daftar pengiriman' },
    { key: 'receipt-variance', label: 'Laporan selisih terima' },
    { key: 'dispatch-outstanding', label: 'Kekurangan kirim', count: outstanding.totals?.items > 0 ? outstanding.totals.items : undefined },
    ...((buyerShorts.items || []).length || view === 'shorts'
      ? [{ key: 'buyer-shorts', label: `Belum sampai di ${receiverLabel}`, count: (buyerShorts.items || []).length }] : []),
  ];
  const VIEW_KEY = { list: 'shipment-list', variance: 'receipt-variance', outstanding: 'dispatch-outstanding', shorts: 'buyer-shorts' };
  const KEY_VIEW = { 'shipment-list': 'list', 'receipt-variance': 'variance', 'dispatch-outstanding': 'outstanding', 'buyer-shorts': 'shorts' };

  return (
    <PageLayoutSatuBaris
      testId="buyer-shipment-module"
      title="Kirim hasil"
      subtitle={businessType === 'internal'
        ? 'Serah terima barang jadi ke gudang DA. Satu surat jalan bisa dikirim bertahap.'
        : `Pengiriman barang jadi ke ${receiverLabel}. Satu surat jalan bisa dikirim bertahap.`}
      actions={canEdit && (
        <Button type="button" onClick={() => setPanel({ kind: 'form', key: Date.now() })} data-testid="buyer-shipment-new">
          <Plus className="w-4 h-4" />Buat surat jalan
        </Button>
      )}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari surat jalan, PO, penerima"
            className="pl-8" data-testid="buyer-shipment-search" />
        </div>
        <FilterChips testId="tab" ariaLabel="Tampilan" hideWhenEmpty={false} value={VIEW_KEY[view]}
          onChange={(k) => changeView(KEY_VIEW[k])} options={viewOptions} />
        {view === 'list' && (
          <div data-testid="shipment-receiver-filter">
            <FilterChips value={recvFilter} onChange={setRecvFilter} testId="shipment-recv" ariaLabel="Penerima" hideWhenEmpty={false}
              options={[{ key: 'buyer', label: `Ke ${receiverLabel}`, count: recvCounts.buyer },
                { key: 'da', label: 'Deklarasi vendor → DA', count: recvCounts.da },
                { key: 'all', label: 'Semua', count: recvCounts.all }]} />
          </div>
        )}
        {view === 'list' && !businessType && (
          <FilterChips value={bizFilter} onChange={setBizFilter} testId="biz-filter" ariaLabel="Jenis PO" hideWhenEmpty={false}
            options={[{ key: 'all', label: 'Semua jenis' }, { key: 'internal', label: 'Internal' }, { key: 'maklon', label: 'Maklon' }]} />
        )}
        {view === 'outstanding' && (<>
          <SmartNativeSelect value={outBuyer} data-testid="outstanding-buyer-filter" aria-label="Penerima" className="w-52"
            onChange={(e) => { setOutBuyer(e.target.value); loadOutstanding(e.target.value, outShowSettled); }}>
            <option value="">Semua penerima</option>
            {(outstanding.buyers || []).map((b) => <option key={b} value={b}>{b}</option>)}
          </SmartNativeSelect>
          <FilterChips value={outShowSettled} testId="outstanding-show-settled" ariaLabel="Lunas" hideWhenEmpty={false}
            onChange={(v) => { setOutShowSettled(v); loadOutstanding(outBuyer, v); }}
            options={[{ key: 'open', label: 'Belum lunas' }, { key: 'all', label: 'Termasuk yang lunas' }]} />
        </>)}
      </>}
      tools={<>
        {/* Standar UI/UX v2: tiap tampilan bertabel bisa diunduh Excel + CSV (TombolUnduh). Unduhan lama tetap. */}
        {view === 'outstanding' ? (<>
          <TombolUnduh namaBerkas="kekurangan-kirim" namaLembar="Kekurangan kirim" baris={outstanding.items || []} testId="outstanding-unduh" kolom={[
            { label: 'No. PO', nilai: (r) => r.po_number || '' }, { label: 'Penerima', nilai: (r) => r.buyer || '' },
            { label: 'SKU', nilai: (r) => r.sku || '' }, { label: 'Produk', nilai: (r) => r.product_name || '' },
            { label: 'Ukuran', nilai: (r) => r.size || '' }, { label: 'Warna', nilai: (r) => r.color || '' },
            { label: 'Qty pesan', nilai: (r) => Number(r.ordered) || 0 }, { label: 'Sumber', nilai: (r) => (r.source === 'internal' ? 'produksi internal' : 'CMT') },
            { label: 'Siap kirim', nilai: (r) => Number(r.source === 'internal' ? r.internal_produced : r.good_from_cmt) || 0 },
            { label: 'Hasil permak', nilai: (r) => Number(r.reworked_ok) || 0 }, { label: 'Sudah dikirim', nilai: (r) => Number(r.dispatched) || 0 },
            { label: 'Sisa pesanan', nilai: (r) => Number(r.remaining_vs_order) || 0 }, { label: 'Sisa bisa kirim', nilai: (r) => Number(r.shippable) || 0 },
            { label: 'Stok barang jadi', nilai: (r) => (r.fg_stock == null ? '' : Math.round(r.fg_stock)) },
          ]} />
          <span className="sr-only" data-testid="outstanding-export-csv" />
        </>) : view === 'list' ? (<>
          <TombolUnduh namaBerkas="surat-jalan-kirim-hasil" namaLembar="Surat jalan" baris={filteredShipments} testId="buyer-shipment-unduh" kolom={[
            { label: 'No. surat jalan', nilai: (s) => s.shipment_number || '' }, { label: 'PO', nilai: (s) => s.po_number || '' },
            { label: 'Penerima', nilai: (s) => s.customer_name || s.buyer_name || '' }, { label: 'Vendor', nilai: (s) => s.vendor_name || '' },
            { label: 'Dipesan', nilai: (s) => Number(s.total_ordered) || 0 }, { label: 'Dikirim', nilai: (s) => Number(s.total_shipped) || 0 },
            { label: 'Kemajuan (%)', nilai: (s) => Number(s.progress_pct) || 0 }, { label: 'Jumlah kiriman', nilai: (s) => Number(s.dispatch_count || s.last_dispatch_seq) || 0 },
          ]} />
          <ImportExportPanel importType={null} exportType="buyer-shipments" exportFilters={businessType ? { business_type: businessType } : {}}
            exportLabel="Unduh per barang" exportTitle="Excel dari server: satu baris per barang kiriman" />
        </>) : view === 'shorts' ? (
          <TombolUnduh namaBerkas="belum-sampai-penerima" baris={shortRows} testId="buyer-short-unduh" kolom={[
            { label: 'No. selisih', nilai: (s) => s.short_number || '' }, { label: 'Surat jalan', nilai: (s) => s.shipment_number || '' },
            { label: 'PO', nilai: (s) => s.po_number || '' }, { label: 'Penerima', nilai: (s) => s.customer_name || '' },
            { label: 'SKU', nilai: (s) => s.sku || '' }, { label: 'Belum sampai', nilai: (s) => Number(s.qty_open ?? s.qty_short) || 0 },
          ]} />
        ) : null}
        <Button type="button" variant="outline" size="icon" onClick={refresh} data-testid="outstanding-refresh" title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={`w-4 h-4 ${loading || outLoading ? 'animate-spin' : ''}`} />
        </Button>
      </>}
      summary={view === 'list' ? (<>
        {(buyerShorts.items || []).length > 0 && (
          <Notice tone="danger" icon={PackageSearch} testId="buyer-short-panel" title={`${fmtNum(buyerShorts.total_qty_open)} pcs belum sampai di ${receiverLabel}`}
            action={<Button type="button" size="sm" variant="outline" onClick={() => changeView('shorts')} data-testid="buyer-short-open">Lihat</Button>}>
            Barang sudah dikembalikan ke stok barang jadi — kirim ulang, atau tentukan siapa yang menanggung.
          </Notice>
        )}
        {filteredShipments.length > 0 && (
          <div className="grid grid-cols-3 gap-3">
            <StatTile testId="ship-kpi-total" label="Surat jalan (sesuai saringan)" value={fmtNum(filteredShipments.length)} />
            <StatTile testId="ship-kpi-full" label="Terkirim penuh" value={fmtNum(fullyShipped)} accent="success" />
            <StatTile testId="ship-kpi-partial" label="Terkirim sebagian" value={fmtNum(partialShipped)} accent="warning" />
          </div>
        )}
      </>) : view === 'outstanding' && outstanding.totals && outstanding.totals.items > 0 ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <StatTile label="Item belum lunas" value={fmtNum(outstanding.totals.items)} testId="outstanding-kpi-items" />
          <StatTile label="Total qty pesan" value={fmtNum(outstanding.totals.ordered)} testId="outstanding-kpi-ordered" />
          <StatTile label="Sudah dikirim" value={fmtNum(outstanding.totals.dispatched)} testId="outstanding-kpi-dispatched" />
          <StatTile label="Siap dikirim sekarang" value={fmtNum(outstanding.totals.shippable)} accent="success" testId="outstanding-kpi-shippable" />
        </div>
      ) : null}
      detail={panel?.kind === 'form' ? (
        <ShipmentForm key={panel.key} businessType={businessType} pos={pos} setPOs={setPOs} continueShip={panel.continueShip}
          presetPoId={panel.poId} onClose={() => setPanel(null)} onSaved={() => { setPanel(null); fetchAll(); }} />
      ) : panel?.kind === 'detail' ? (
        <ShipmentDetail data={panel.data} canForceEdit={canForceEdit} onClose={() => setPanel(null)}
          onEditReceived={(item, seq) => setRecvItem({ ...item, dispatch_seq: item.dispatch_seq || seq })} />
      ) : null}
      footer={view === 'list' && filteredShipments.length > pageSize && (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />
      )}
    >
      {view === 'variance' ? (
        <BuyerReceiptVarianceReport portalId={portalId} businessType={businessType} />
      ) : (
        <GlassCard className="p-0 overflow-x-auto">
          {view === 'outstanding' ? (
            <OutstandingView loading={outLoading} rows={outRows} poBoard={poBoard} canEdit={canEdit}
              onDispatch={(g) => setPanel(g.openShip ? { kind: 'form', key: Date.now(), continueShip: g.openShip }
                : { kind: 'form', key: Date.now(), poId: g.po_id })} />
          ) : view === 'shorts' ? (
            <BuyerShortTable rows={shortRows} onResolve={setResolveBShort} />
          ) : loading && !shipments.length ? (
            <div className="p-4 text-sm text-muted-foreground"><Loader2 className="w-4 h-4 animate-spin inline mr-2" />Memuat…</div>
          ) : filteredShipments.length === 0 ? (
            <EmptyState icon={Package} title="Belum ada surat jalan pada penyaring ini"
              description={canEdit ? 'Buat surat jalan dari barang yang sudah lolos QC.' : 'Surat jalan muncul setelah barang lolos QC dikirim.'} />
          ) : (
            <Table data-testid="buyer-shipment-table">
              <TableHeader><TableRow>
                <TableHead className="w-10" />
                <TableHead>No. surat jalan</TableHead><TableHead>No. PO</TableHead><TableHead>Penerima</TableHead>
                <TableHead>Progres pengiriman</TableHead><TableHead>Status</TableHead><TableHead className="text-right">Aksi</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {paged.map((row) => {
                  const nums = row.po_numbers?.length ? row.po_numbers : (row.po_number ? [row.po_number] : []);
                  const pct = row.progress_pct || 0;
                  const [stLabel, stTone] = shipStatus(pct);
                  const open = !!expanded[row.id];
                  return (
                    <Fragment key={row.id}>
                      <TableRow data-testid={`shipment-row-${row.shipment_number}`}>
                        <TableCell>
                          <RowToggle open={open} onClick={() => toggleExpand(row.id)} label="Lihat riwayat kirim" testId={`shipment-expand-${row.shipment_number}`} />
                        </TableCell>
                        <TableCell>
                          <Button type="button" variant="link" size="sm" className="h-auto p-0 font-semibold" onClick={() => openDetail(row)}
                            data-testid={`shipment-open-${row.shipment_number}`}>{row.shipment_number}</Button>
                          <span className="flex flex-wrap gap-1 mt-1">
                            {!businessType && <BizBadge type={row.business_type} size="xs" />}
                            {row.is_consolidated && <StatusBadge status="gabungan" label={`Gabungan ${nums.length} PO`} tone="primary" />}
                            {row.receiver_type === 'da' && <StatusBadge status="vendor-da" label="Vendor → DA" tone="warning" />}
                          </span>
                        </TableCell>
                        <TableCell className="text-xs">
                          {nums.length === 0 ? '—' : nums.length === 1 ? nums[0] : (
                            <><span className="font-medium">{nums.length} PO</span><span className="block text-muted-foreground">{nums.join(', ')}</span></>
                          )}
                        </TableCell>
                        <TableCell>{row.customer_name || '—'}</TableCell>
                        <TableCell className="min-w-[180px]">
                          <div className="flex items-center justify-between text-xs mb-1 tabular-nums">
                            <span>{fmtNum(row.total_shipped)} / {fmtNum(row.total_ordered)} pcs</span><span className="font-medium">{pct}%</span>
                          </div>
                          <div className="w-full h-1.5 bg-muted rounded-full overflow-hidden">
                            <div className={`h-full rounded-full ${pct >= 100 ? 'bg-[hsl(var(--success))]' : 'bg-[hsl(var(--primary))]'}`} style={{ width: `${Math.min(pct, 100)}%` }} />
                          </div>
                          <span className="text-xs text-muted-foreground">Sisa {fmtNum(row.remaining)} pcs{row.dispatch_count ? ` · ${row.dispatch_count} kali kirim` : ''}</span>
                        </TableCell>
                        <TableCell><StatusBadge status={stLabel} label={stLabel} tone={stTone} /></TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-1">
                            {canEdit && pct < 100 && (
                              <Button type="button" size="sm" variant="outline" onClick={() => setPanel({ kind: 'form', key: Date.now(), continueShip: row })}
                                data-testid={`continue-dispatch-${row.shipment_number}`} title="Kirim sisa pada surat jalan ini (nomor tidak berubah)">
                                <Plus className="w-3.5 h-3.5" />Kirim lagi
                              </Button>
                            )}
                            <Button type="button" size="icon-sm" variant="ghost" onClick={() => openDetail(row)} title="Rincian" aria-label="Rincian"><Eye className="w-4 h-4" /></Button>
                            <Button type="button" size="icon-sm" variant="ghost" onClick={() => downloadPDF(row)} title="Cetak surat jalan (PDF)" aria-label="Cetak surat jalan (PDF)"
                              data-testid="buyer-shipment-print-sj"><Download className="w-4 h-4" /></Button>
                            {canCreate && (
                              <Button type="button" size="icon-sm" variant="ghost" onClick={() => handleDelete(row)} title="Hapus" aria-label="Hapus"
                                data-testid={`shipment-delete-${row.shipment_number}`}><Trash2 className="w-4 h-4" /></Button>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                      {open && (
                        <RowDetail colSpan={7} testId={`shipment-consolidation-${row.id}`}>
                          <ShipmentRowDetail row={row} detail={shipDetail[row.id]} />
                        </RowDetail>
                      )}
                    </Fragment>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </GlassCard>
      )}

      {recvItem && (
        <ReceivedDialog item={recvItem} onClose={() => setRecvItem(null)}
          onSaved={async () => {
            setRecvItem(null);
            if (panel?.kind === 'detail' && panel.data?.id) await openDetail({ id: panel.data.id });
            fetchAll();
          }} />
      )}
      {resolveBShort && (
        <BuyerShortDialog short={resolveBShort} onClose={() => setResolveBShort(null)}
          onSaved={() => { setResolveBShort(null); fetchAll(); }} />
      )}
    </PageLayoutSatuBaris>
  );
}

/* ── Rincian di bawah baris: per PO, sumber penerimaan, riwayat kirim ──────── */
function ShipmentRowDetail({ row, detail }) {
  const det = detail && detail !== 'loading' ? detail : null;
  const poBreak = det?.po_breakdown || [];
  const childShips = det?.child_shipments || [];
  const srcReceipts = det?.source_receipts || [];
  const parentShip = det?.parent_shipment;
  const groups = {};
  for (const item of row.items || []) {
    const seq = item.dispatch_seq || 1;
    if (!groups[seq]) groups[seq] = { seq, date: item.dispatch_date || item.created_at, items: [], qty: 0 };
    groups[seq].items.push(item);
    groups[seq].qty += item.qty_shipped || 0;
  }
  const dispatches = Object.values(groups).sort((a, b) => a.seq - b.seq);
  let cumulative = 0;
  return (
    <div className="space-y-3 text-sm">
      {detail === 'loading' && <p className="text-xs text-muted-foreground">Memuat rincian…</p>}
      {poBreak.length > 1 && (
        <div>
          <p className="text-xs font-medium text-muted-foreground mb-1">Rincian per PO (surat jalan gabungan {poBreak.length} PO)</p>
          <Table>
            <TableHeader><TableRow>
              <TableHead>No. PO</TableHead><TableHead>Penerima</TableHead><TableHead className="text-right">Item</TableHead><TableHead className="text-right">Qty kirim</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {poBreak.map((p, i) => (
                <TableRow key={p.po_id || i}>
                  <TableCell>{p.po_number || '—'}</TableCell><TableCell>{p.customer_name || p.buyer_name || '—'}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNum(p.line_count ?? p.item_count ?? (p.items || []).length)}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNum(p.qty_shipped)} pcs</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {(srcReceipts.length > 0 || parentShip || childShips.length > 0) && (
        <p className="text-xs text-muted-foreground">
          {srcReceipts.length > 0 && <>Sumber penerimaan CMT: <span className="text-foreground">{srcReceipts.map((r) => `${r.receipt_code || r.id}${r.po_number ? ` (${r.po_number})` : ''}`).join(', ')}</span>. </>}
          {parentShip && <>Bagian dari surat jalan induk <span className="text-foreground">{parentShip.shipment_number}</span>. </>}
          {childShips.length > 0 && <>Kiriman tambahan/pengganti: <span className="text-foreground">{childShips.map((c) => `${c.shipment_number} (${fmtNum((c.items || []).reduce((s, x) => s + (x.qty_shipped || 0), 0))} pcs)`).join(', ')}</span>.</>}
        </p>
      )}
      {dispatches.length === 0 ? (
        <EmptyState icon={Package} title="Belum ada barang pada surat jalan ini" description="Tambahkan kiriman untuk mencatat barang yang dikirim." />
      ) : (
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground flex items-center gap-1.5"><History className="w-3.5 h-3.5" />Riwayat kirim ({dispatches.length} kali)</p>
          <Table>
            <TableHeader><TableRow>
              <TableHead>Kirim</TableHead><TableHead>SKU</TableHead><TableHead>Produk</TableHead><TableHead>Ukuran / warna</TableHead>
              <TableHead className="text-right">Qty kirim</TableHead><TableHead className="text-right">HPP batch (FIFO)</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {dispatches.map((d) => {
                cumulative += d.qty;
                return d.items.map((item, idx) => (
                  <TableRow key={item.id || `${d.seq}-${idx}`}>
                    <TableCell className="whitespace-nowrap">
                      {idx === 0 ? <><span className="font-medium">#{d.seq}</span> <span className="text-xs text-muted-foreground">{fmtDate(d.date)} · kumulatif {fmtNum(cumulative)}/{fmtNum(row.total_ordered)}</span></> : ''}
                    </TableCell>
                    <TableCell className="whitespace-nowrap">{item.sku || '—'}{item.serial_number ? <span className="block text-xs text-muted-foreground">{item.serial_number}</span> : null}</TableCell>
                    <TableCell>{item.product_name}</TableCell>
                    <TableCell className="whitespace-nowrap">{item.size || '—'} / {item.color || '—'}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmtNum(item.qty_shipped)}</TableCell>
                    <TableCell className="text-right tabular-nums" data-testid={`item-cogs-${item.id || idx}`}>
                      <CogsCell item={item} />
                    </TableCell>
                  </TableRow>
                ));
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

function CogsCell({ item }) {
  return (
    <>
      {Number(item.fg_cogs || 0) <= 0 ? (
        <span className="text-muted-foreground" title={item.fg_cogs == null ? 'Barang ini keluar sebelum lapisan biaya batch dipasang'
          : 'Batch masuknya belum punya biaya (BOM/upah jahit belum lengkap) — bukan Rp 0'}>
          {item.fg_cogs == null ? '—' : 'belum berbiaya'}
        </span>
      ) : fmtRp(item.fg_cogs)}
      {Number(item.fg_cogs_uncosted_qty || 0) > 0 && (
        <span className="block text-xs text-[hsl(var(--warning-text))]">{fmtNum(item.fg_cogs_uncosted_qty)} pcs tanpa lapisan biaya</span>
      )}
    </>
  );
}

/* ── Kekurangan kirim: papan per PO + rincian per item ───────────────────── */
function OutstandingView({ loading, rows, poBoard, canEdit, onDispatch }) {
  if (loading) return <div className="p-4 text-sm text-muted-foreground"><Loader2 className="w-4 h-4 animate-spin inline mr-2" />Memuat…</div>;
  if (!rows.length) {
    return <EmptyState icon={CheckCircle} testId="outstanding-empty" title="Tidak ada kekurangan kirim" description="Semua item sudah terkirim penuh." />;
  }
  return (
    <div data-testid="dispatch-outstanding-panel">
      <p className="px-4 pt-3 text-xs text-muted-foreground">
        Sisa bisa kirim = siap kirim (maklon: lolos QC + hasil permak · internal: hasil produksi) − sudah dikirim.
        Bila sisa 0 tetapi sisa pesanan masih ada, barangnya belum diterima dari CMT.
      </p>
      <Table data-testid="po-board-table">
        <TableHeader><TableRow>
          <TableHead>No. PO</TableHead><TableHead>Penerima</TableHead><TableHead className="text-right">Pesan</TableHead>
          <TableHead className="text-right">Sudah dikirim</TableHead><TableHead className="text-right">Sisa pesanan</TableHead>
          <TableHead className="text-right">Sisa bisa kirim</TableHead><TableHead>Surat jalan berjalan</TableHead><TableHead className="text-right">Aksi</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {poBoard.map((g) => (
            <TableRow key={g.key} data-testid={`po-board-row-${g.po_number}`}>
              <TableCell className="font-medium whitespace-nowrap">{g.po_number}</TableCell>
              <TableCell>{g.buyer || '—'}</TableCell>
              <TableCell className="text-right tabular-nums">{fmtNum(g.ordered)}</TableCell>
              <TableCell className="text-right tabular-nums">{fmtNum(g.dispatched)} <span className="text-xs text-muted-foreground">({g.pct}%)</span></TableCell>
              <TableCell className="text-right tabular-nums">{fmtNum(g.remaining)}</TableCell>
              <TableCell className="text-right tabular-nums">
                {g.shippable > 0 ? <span className="font-medium text-[hsl(var(--success-text))]" data-testid={`po-board-shippable-${g.po_number}`}>{fmtNum(g.shippable)}</span>
                  : <span className="text-xs text-muted-foreground">belum ada barang</span>}
              </TableCell>
              <TableCell className="text-xs">{g.openShip ? `${g.openShip.shipment_number} (${g.openShip.progress_pct || 0}%)` : <span className="text-muted-foreground">belum ada</span>}</TableCell>
              <TableCell className="text-right">
                {canEdit && (
                  <Button type="button" size="sm" variant="outline" disabled={g.shippable <= 0} onClick={() => onDispatch(g)} data-testid={`board-dispatch-${g.po_number}`}
                    title={g.shippable > 0 ? (g.openShip ? `Tambah kiriman ke ${g.openShip.shipment_number}` : 'Buat surat jalan pertama untuk PO ini') : 'Barang belum diterima dari CMT'}>
                    <Plus className="w-3.5 h-3.5" />{g.openShip ? 'Kirim lagi' : 'Surat jalan baru'}
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="px-4 pt-4 pb-1 text-xs font-medium text-muted-foreground">Rincian per item</p>
      <Table data-testid="outstanding-table">
        <TableHeader><TableRow>
          <TableHead>No. PO</TableHead><TableHead>SKU</TableHead><TableHead>Produk</TableHead><TableHead>Ukuran / warna</TableHead>
          <TableHead className="text-right">Pesan</TableHead><TableHead className="text-right">Siap kirim</TableHead><TableHead className="text-right">Permak</TableHead>
          <TableHead className="text-right">Dikirim</TableHead><TableHead className="text-right">Sisa bisa kirim</TableHead><TableHead className="text-right">Stok barang jadi</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.key} data-testid={`outstanding-row-${r.sku || r.key}`}>
              <TableCell className="whitespace-nowrap">{r.po_number || '—'}</TableCell>
              <TableCell className="whitespace-nowrap">{r.sku || '—'}</TableCell>
              <TableCell>{r.product_name || '—'}</TableCell>
              <TableCell className="whitespace-nowrap">{r.size || '—'} / {r.color || '—'}</TableCell>
              <TableCell className="text-right tabular-nums">{fmtNum(r.ordered)}</TableCell>
              <TableCell className="text-right tabular-nums">
                {fmtNum(r.source === 'internal' ? r.internal_produced : r.good_from_cmt)}
                <span className="block text-xs text-muted-foreground">{r.source === 'internal' ? 'hasil produksi' : 'lolos QC'}</span>
              </TableCell>
              <TableCell className="text-right tabular-nums">{r.source === 'internal' ? '—' : fmtNum(r.reworked_ok)}</TableCell>
              <TableCell className="text-right tabular-nums">{fmtNum(r.dispatched)}</TableCell>
              <TableCell className="text-right tabular-nums">
                {r.shippable > 0 ? <span className="font-medium text-[hsl(var(--success-text))]" data-testid={`outstanding-shippable-${r.sku || r.key}`}>{fmtNum(r.shippable)}</span>
                  : <span className="text-xs text-muted-foreground">belum ada barang</span>}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {r.fg_stock == null ? <span title="Barang jadi untuk SKU ini belum ada di gudang (bukan stok 0)">—</span> : fmtNum(Math.round(r.fg_stock))}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

/* ── Barang belum sampai di penerima ─────────────────────────────────────── */
function BuyerShortTable({ rows, onResolve }) {
  if (!rows.length) return <EmptyState icon={PackageSearch} title="Tidak ada barang yang belum sampai" description="Selisih terima muncul di sini setelah qty diterima dicatat." />;
  return (
    <Table data-testid="buyer-short-table">
      <TableHeader><TableRow>
        <TableHead>No. selisih</TableHead><TableHead>Surat jalan / PO</TableHead><TableHead>Penerima</TableHead><TableHead>SKU</TableHead>
        <TableHead className="text-right">Dikirim</TableHead><TableHead className="text-right">Diterima</TableHead>
        <TableHead className="text-right">Belum sampai</TableHead><TableHead className="text-right">Aksi</TableHead>
      </TableRow></TableHeader>
      <TableBody>
        {rows.map((s) => (
          <TableRow key={s.id}>
            <TableCell className="font-medium whitespace-nowrap">{s.short_number}</TableCell>
            <TableCell>{s.shipment_number || '—'}<span className="block text-xs text-muted-foreground">{s.po_number || '—'}</span></TableCell>
            <TableCell>{s.customer_name || '—'}</TableCell>
            <TableCell className="whitespace-nowrap">{s.sku || '—'}</TableCell>
            <TableCell className="text-right tabular-nums">{fmtNum(s.qty_shipped_claimed)}</TableCell>
            <TableCell className="text-right tabular-nums">{fmtNum(s.qty_received)}</TableCell>
            <TableCell className="text-right tabular-nums font-medium text-[hsl(var(--danger-text))]">{fmtNum(s.qty_open ?? s.qty_short)}</TableCell>
            <TableCell className="text-right">
              <Button type="button" size="sm" variant="outline" data-testid={`buyer-short-resolve-${s.short_number}`} onClick={() => onResolve(s)}>Putuskan</Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/* ── Formulir surat jalan (buat baru / kirim lagi) — di halaman ─────────── */
function ShipmentForm({ businessType, pos, setPOs, continueShip, presetPoId, onClose, onSaved }) {
  const [form, setForm] = useState({ shipment_number: continueShip?.shipment_number || '', po_id: '', shipment_date: todayWIB(), notes: '', items: [], source_receipt_ids: [] });
  const [selectedPO, setSelectedPO] = useState(null);
  const [availableReceipts, setAvailableReceipts] = useState([]);
  const [capTotals, setCapTotals] = useState(null);
  const [capLoading, setCapLoading] = useState(false);
  // Phase D: satu surat jalan untuk banyak PO milik penerima yang sama
  const [consolidate, setConsolidate] = useState(false);
  const [consBuyer, setConsBuyer] = useState('');
  const [consReceipts, setConsReceipts] = useState([]);
  const [consLoading, setConsLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const isInternalPO = selectedPO?.business_type === 'internal';

  const fetchCapacity = async (param, ids) => {
    const list = (ids || []).filter(Boolean);
    if (!list.length) { setCapTotals(null); return {}; }
    setCapLoading(true);
    try {
      const res = await apiGet(`/buyer-dispatch-capacity?with_fg_stock=1&${param}=${encodeURIComponent(list.join(','))}`);
      const map = {};
      for (const r of (res?.items || [])) map[r.key] = r;
      setCapTotals(res?.totals || null);
      return map;
    } catch (e) {
      toast.error(`Gagal memuat sisa bisa kirim: ${e.message || 'kesalahan jaringan'}`);
      setCapTotals(null);
      return {};
    } finally { setCapLoading(false); }
  };
  const capCols = (r) => ({
    good_from_cmt: r?.good_from_cmt || 0, reworked_ok: r?.reworked_ok || 0, internal_produced: r?.internal_produced || 0,
    dispatched: r?.dispatched || 0, shippable: r ? (r.shippable || 0) : 0, fg_stock: r?.fg_stock,
    qty_shipped: r && r.shippable > 0 ? String(r.shippable) : '',
  });
  const annotate = (items, map) => items.map((it) => ({ ...it, ...capCols(map[`poi:${it.po_item_id}`]) }));
  const rowsFromCapacity = (map) => Object.values(map).filter((r) => r.po_item_id).map((r) => ({
    po_item_id: r.po_item_id, sku: r.sku || '', product_name: r.product_name || '', size: r.size || '', color: r.color || '',
    serial_number: r.serial_number || '', po_number: r.po_number || '', po_id: r.po_id || '', ordered_qty: r.ordered || 0, ...capCols(r),
  }));

  const ensurePO = async (poId) => {
    if (!poId) return null;
    const found = pos.find((p) => p.id === poId);
    if (found) return found;
    try {
      const po = await apiGet(`/production-pos/${poId}`);
      if (po?.id) { setPOs((prev) => [po, ...prev]); return po; }
    } catch { /* hanya label PO yang kosong */ }
    return null;
  };

  const loadPOItems = async (poId, poOverride = null) => {
    setCapTotals(null); setAvailableReceipts([]);
    if (!poId) { setSelectedPO(null); setForm((f) => ({ ...f, po_id: '', items: [], source_receipt_ids: [] })); return []; }
    const data = await apiGet(`/po-items?po_id=${poId}`).catch(() => []);
    const po = poOverride || pos.find((p) => p.id === poId);
    setSelectedPO(po);
    const items = (Array.isArray(data) ? data : []).map((pi) => ({
      po_item_id: pi.id, product_name: pi.product_name, sku: pi.sku || '', size: pi.size || '', color: pi.color || '',
      serial_number: pi.serial_number || '', ordered_qty: pi.qty, qty_shipped: '',
    }));
    setForm((f) => ({ ...f, po_id: poId, items, source_receipt_ids: [] }));
    // PO internal: kapasitas = hasil produksi job internal, tanpa pemilih penerimaan CMT.
    if (po && po.business_type === 'internal') {
      const map = await fetchCapacity('po_item_ids', items.map((i) => i.po_item_id));
      setForm((f) => ({ ...f, items: annotate(items, map) }));
      return items;
    }
    const rcpAll = await apiGet(`/prod/cmt-receipts${portalQuery(businessType, { status: 'Approved', po_id: poId })}`).catch(() => []);
    setAvailableReceipts((Array.isArray(rcpAll) ? rcpAll : []).filter((r) => r.po_id === poId
      || (po && (r.po_number === po.po_number || r.wo_number === po.po_number))));
    return items;
  };

  const enterConsolidation = async () => {
    setConsLoading(true);
    try {
      const [rcpAll, allPOs] = await Promise.all([
        apiGet(`/prod/cmt-receipts${portalQuery(businessType, { status: 'Approved' })}`),
        apiGet(`/production-pos${portalQuery(businessType)}`),
      ]);
      const poList = Array.isArray(allPOs) ? allPOs : [];
      const poById = Object.fromEntries(poList.map((p) => [p.id, p]));
      setConsReceipts((Array.isArray(rcpAll) ? rcpAll : []).map((r) => {
        const po = poById[r.po_id] || poList.find((p) => p.po_number === (r.po_number || r.wo_number));
        return { ...r, _buyer: (po?.customer_name || '').trim(), _po_number: po?.po_number || r.po_number || r.wo_number || '' };
      }).filter((r) => r._buyer));
    } catch { setConsReceipts([]); }
    setConsLoading(false);
  };

  // Lanjut kirim pada surat jalan yang ada, atau PO terpilih dari papan kekurangan kirim
  useEffect(() => {
    (async () => {
      if (presetPoId) { await loadPOItems(presetPoId, await ensurePO(presetPoId)); return; }
      if (!continueShip) return;
      try {
        const det = await apiGet(`/buyer-shipments/${continueShip.id}`);
        const srcIds = (det?.source_receipt_ids || []).filter(Boolean);
        const poIds = (det?.po_ids || []).filter(Boolean).length ? det.po_ids.filter(Boolean) : (det?.po_id ? [det.po_id] : []);
        if (poIds.length > 1) {
          setConsolidate(true); setConsBuyer(det.customer_name || '');
          await enterConsolidation();
          setForm((f) => ({ ...f, source_receipt_ids: srcIds }));
          const map = await fetchCapacity('receipt_ids', srcIds);
          setForm((f) => ({ ...f, items: rowsFromCapacity(map) }));
        } else {
          const items = await loadPOItems(poIds[0] || '', await ensurePO(poIds[0] || ''));
          setForm((f) => ({ ...f, source_receipt_ids: srcIds }));
          if (srcIds.length) {
            const map = await fetchCapacity('receipt_ids', srcIds);
            setForm((f) => ({ ...f, items: annotate(items, map) }));
          }
        }
        if (!srcIds.length && det?.business_type !== 'internal') {
          toast.warning('Surat jalan ini belum punya sumber penerimaan CMT — pilih penerimaan yang sudah selesai QC.');
        }
      } catch (e) { toast.error(e.message || 'Gagal memuat surat jalan yang dilanjutkan'); }
    })();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleReceipt = async (rid, multi) => {
    const has = form.source_receipt_ids.includes(rid);
    const src = has ? form.source_receipt_ids.filter((x) => x !== rid) : [...form.source_receipt_ids, rid];
    setForm((f) => ({ ...f, source_receipt_ids: src }));
    const map = await fetchCapacity('receipt_ids', src);
    setForm((f) => ({ ...f, items: multi ? rowsFromCapacity(map) : annotate(f.items, map) }));
  };
  const toggleConsolidate = (on) => {
    setConsolidate(on); setConsBuyer(''); setSelectedPO(null); setAvailableReceipts([]); setCapTotals(null);
    setForm((f) => ({ ...f, po_id: '', items: [], source_receipt_ids: [] }));
    if (on) enterConsolidation();
  };
  const updateItemQty = (idx, val) => {
    setForm((f) => {
      const items = [...f.items];
      const row = items[idx];
      // Batas KERAS = sisa bisa kirim (angka yang sama dengan pagar backend).
      const cap = row.shippable != null ? Number(row.shippable) : Number(row.ordered_qty || 0);
      let next = val;
      if (val !== '') {
        const n = Number(val);
        next = String(Number.isFinite(n) ? Math.max(0, Math.min(n, cap)) : 0);
        if (Number.isFinite(n) && n > cap) toast.warning(`${row.sku || 'Item'}: maksimal ${fmtNum(cap)} pcs (sisa bisa kirim).`);
      }
      items[idx] = { ...row, qty_shipped: next };
      return { ...f, items };
    });
  };

  const submit = async () => {
    const validItems = form.items.filter((i) => Number(i.qty_shipped) > 0);
    if (consolidate) {
      if (!consBuyer) { toast.error('Pilih penerima terlebih dahulu'); return; }
      if (!form.source_receipt_ids.length) { toast.error('Pilih minimal 1 penerimaan CMT yang sudah selesai QC'); return; }
    } else {
      if (!form.po_id) { toast.error('Pilih PO terlebih dahulu'); return; }
      if (!isInternalPO && !form.source_receipt_ids.length) {
        toast.error('Pilih minimal 1 penerimaan CMT yang sudah selesai QC sebagai sumber barang. Belum ada? Selesaikan QC di Terima & QC dulu.');
        return;
      }
    }
    if (!validItems.length) { toast.error('Isi minimal 1 item dengan qty > 0'); return; }
    const over = validItems.filter((i) => i.shippable != null && Number(i.qty_shipped) > Number(i.shippable));
    if (over.length) { toast.error(`${over[0].sku || 'Item'}: qty kirim ${over[0].qty_shipped} melebihi sisa bisa kirim ${fmtNum(over[0].shippable)} pcs.`); return; }
    const payload = consolidate ? {
      shipment_date: form.shipment_date, notes: form.notes, receiver_type: 'buyer',
      items: validItems.map((i) => ({ po_item_id: i.po_item_id, sku: i.sku, qty_shipped: Number(i.qty_shipped) })),
      source_receipt_ids: form.source_receipt_ids,
    } : {
      ...form, receiver_type: 'buyer', source_receipt_ids: form.source_receipt_ids,
      items: validItems.map((i) => ({ ...i, qty_shipped: Number(i.qty_shipped), ordered_qty: Number(i.ordered_qty) })),
    };
    if (continueShip) { payload.shipment_id = continueShip.id; delete payload.shipment_number; }
    else if (!form.shipment_number.trim()) delete payload.shipment_number;
    setSaving(true);
    try {
      const data = await postWithOverQtyReason('/buyer-shipments', payload);
      toast.success(continueShip ? `Kiriman #${data.dispatch_seq || ''} ditambahkan ke surat jalan ${data.shipment_number || ''}`
        : consolidate ? `Surat jalan gabungan ${data.shipment_number || ''} dibuat (${(data.po_ids || []).length} PO)`
          : `Surat jalan ${data.shipment_number || ''} dibuat`);
      onSaved();
    } catch (err) { toast.error(err.message || 'Gagal menyimpan surat jalan'); }
    finally { setSaving(false); }
  };

  const consBuyers = [...new Set(consReceipts.map((r) => r._buyer))].sort();
  const receiptList = consolidate ? consReceipts.filter((r) => r._buyer === consBuyer) : availableReceipts;
  const showReceipts = consolidate ? !!consBuyer : (form.po_id && !isInternalPO);
  const capSummary = capTotals && (isInternalPO
    ? `Sisa bisa diserahkan ${fmtNum(capTotals.shippable)} pcs (lolos QC ${fmtNum(capTotals.accepted_total ?? capTotals.internal_produced)} − sudah diserahkan ${fmtNum(capTotals.dispatched)}).`
    : `Sisa bisa kirim ${fmtNum(capTotals.shippable)} pcs (lolos QC ${fmtNum(capTotals.good_from_cmt)}${capTotals.reworked_ok ? ` + permak ${fmtNum(capTotals.reworked_ok)}` : ''} − sudah dikirim ${fmtNum(capTotals.dispatched)}).`);

  return (
    // Standar UI/UX v2 (8 Nov 2026): form = FormPopup panjang (dulu panel di atas tabel).
    <FormPopup open onClose={onClose} ukuran="panjang" testId="buyer-shipment-form"
      judul={continueShip ? `Kirim lagi — ${continueShip.shipment_number}` : 'Buat surat jalan'}
      keterangan={continueShip ? 'Kiriman ditambahkan sebagai kiriman berikutnya pada surat jalan ini; nomornya tidak berubah.'
        : 'Qty maksimal = sisa bisa kirim (lolos QC + hasil permak − yang sudah dikirim).'}
      onSimpan={submit} menyimpan={saving} labelSimpan={continueShip ? 'Tambah kiriman' : 'Simpan'}>
      {continueShip && <Notice tone="info" icon={Info} testId="continue-dispatch-banner">
        Progres pengiriman PO naik pada surat jalan yang sama ({continueShip.shipment_number}).
      </Notice>}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="No. surat jalan" hint={continueShip ? 'Tetap, tidak berubah' : 'Kosongkan untuk nomor otomatis'}>
          <GlassInput placeholder="otomatis sesuai format" disabled={!!continueShip} className="h-9"
            value={form.shipment_number} onChange={(e) => setForm((f) => ({ ...f, shipment_number: e.target.value }))} data-testid="sj-number-input" />
        </Field>
        <Field label="Tanggal">
          <DatePicker value={form.shipment_date} onChange={(v) => setForm((f) => ({ ...f, shipment_date: v }))} bolehKosong={false} testId="sj-date" />
        </Field>
        {!consolidate ? (
          <Field label="PO *" className="sm:col-span-2">
            <SmartNativeSelect className="w-full h-9" data-testid="buyer-shipment-po-select" aria-label="PO" disabled={!!continueShip}
              value={form.po_id} onChange={(e) => loadPOItems(e.target.value)}>
              <option value="">— Pilih PO —</option>
              {pos.map((p) => (
                <option key={p.id} value={p.id}>
                  {[p.po_number, p.customer_name, p.vendor_name ? `CMT ${p.vendor_name}` : '', p.created_at ? fmtDate(p.created_at) : ''].filter(Boolean).join(' · ')}
                </option>
              ))}
            </SmartNativeSelect>
          </Field>
        ) : (
          <Field label="Penerima *" className="lg:col-span-2"
            hint={!consLoading && !consBuyers.length ? 'Belum ada penerimaan CMT yang selesai QC untuk dikirim.' : undefined}>
            <SmartNativeSelect className="w-full h-9" value={consBuyer} aria-label="Penerima" data-testid="cons-buyer-select"
              onChange={(e) => { setConsBuyer(e.target.value); setCapTotals(null); setForm((f) => ({ ...f, source_receipt_ids: [], items: [] })); }}>
              <option value="">{consLoading ? 'Memuat…' : '— Pilih penerima —'}</option>
              {consBuyers.map((b) => <option key={b} value={b}>{b}</option>)}
            </SmartNativeSelect>
          </Field>
        )}
      </div>
      <label className={`flex items-center gap-2 text-sm ${continueShip ? 'opacity-60' : 'cursor-pointer'}`} data-testid="consolidate-toggle">
        <Checkbox checked={consolidate} disabled={!!continueShip} onCheckedChange={(v) => toggleConsolidate(!!v)} />
        Gabungkan beberapa PO milik penerima yang sama dalam satu surat jalan (progres tetap dihitung per PO)
      </label>

      {!consolidate && form.po_id && isInternalPO && (
        <Notice tone="info" icon={Info} testId="internal-dispatch-info" title="PO internal — serah terima hasil produksi ke gudang sendiri">
          Tidak perlu memilih penerimaan CMT. Dokumen ini hanya mencatat serah terima: stok barang jadi sudah bertambah lewat
          Terima & QC, jadi stok tidak dikurangi dan HPP tidak dibukukan di sini. {capLoading ? 'Menghitung sisa…' : capSummary}
        </Notice>
      )}
      {showReceipts && (
        <div className="space-y-1" data-testid="source-receipt-picker">
          <p className="text-xs font-medium text-muted-foreground">Sumber barang: penerimaan CMT yang sudah selesai QC</p>
          {receiptList.length === 0 ? (
            <Notice tone="warning" icon={Info}>Belum ada penerimaan CMT yang selesai QC untuk {consolidate ? 'penerima' : 'PO'} ini. Selesaikan QC di Terima & QC dulu.</Notice>
          ) : (
            <div className="max-h-48 overflow-y-auto space-y-1">
              {receiptList.map((r) => (
                <label key={r.id} className="flex items-center gap-2 text-sm cursor-pointer" data-testid={`${consolidate ? 'cons' : 'source'}-receipt-${r.receipt_code}`}>
                  <Checkbox checked={form.source_receipt_ids.includes(r.id)} onCheckedChange={() => toggleReceipt(r.id, consolidate)} />
                  <span>
                    {consolidate && <span className="font-medium">{r._po_number} · </span>}{r.receipt_code}
                    <span className="text-muted-foreground"> · {r.cmt_name || '—'} · lolos QC {fmtNum(r.total_actual ?? r.total_qty_actual)} pcs
                      {Number(r.total_rejected ?? r.total_qty_reject ?? 0) > 0 && ` (ditolak ${fmtNum(r.total_rejected ?? r.total_qty_reject)})`}</span>
                  </span>
                </label>
              ))}
            </div>
          )}
          {form.source_receipt_ids.length > 0 && (
            <p className="text-xs text-muted-foreground" data-testid="single-po-capacity-summary">
              Dipilih {form.source_receipt_ids.length} penerimaan. {capLoading ? 'Menghitung sisa bisa kirim…' : capSummary}
            </p>
          )}
        </div>
      )}

      {form.items.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs text-muted-foreground" data-testid="dispatch-capacity-formula">
            {isInternalPO ? 'Sisa bisa kirim = hasil produksi − sudah dikirim.' : 'Sisa bisa kirim = lolos QC + hasil permak − sudah dikirim.'}
            {capTotals && !capLoading && <span className="font-medium text-foreground" data-testid="dispatch-capacity-total"> Total sisa bisa kirim {fmtNum(capTotals.shippable)} pcs.</span>}
          </p>
          <div className="overflow-x-auto">
            <Table data-testid="dispatch-items-table">
              <TableHeader><TableRow>
                {consolidate && <TableHead>PO</TableHead>}
                <TableHead>SKU</TableHead><TableHead>Produk</TableHead><TableHead>Ukuran / warna</TableHead>
                <TableHead className="text-right">Qty pesan</TableHead><TableHead className="text-right">{isInternalPO ? 'Diproduksi' : 'Lolos QC'}</TableHead>
                <TableHead className="text-right">Hasil permak</TableHead><TableHead className="text-right">Sudah dikirim</TableHead>
                <TableHead className="text-right">Sisa bisa kirim</TableHead><TableHead className="text-right">Qty kirim *</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {form.items.map((item, idx) => {
                  const hasCap = item.shippable != null;
                  const sisa = Number(item.shippable || 0);
                  const lunas = hasCap && sisa <= 0;
                  const notProduced = lunas && isInternalPO && Number(item.internal_produced || 0) === 0;
                  const lowStock = hasCap && item.fg_stock != null && Number(item.fg_stock) < sisa;
                  return (
                    <TableRow key={`${item.po_item_id}-${idx}`} data-testid={`dispatch-item-row-${item.sku || idx}`}>
                      {consolidate && <TableCell className="whitespace-nowrap">{item.po_number || '—'}</TableCell>}
                      <TableCell className="whitespace-nowrap">{item.sku || '—'}{item.serial_number ? <span className="block text-xs text-muted-foreground">{item.serial_number}</span> : null}</TableCell>
                      <TableCell>{item.product_name}</TableCell>
                      <TableCell className="whitespace-nowrap">{item.size || '—'} / {item.color || '—'}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmtNum(item.ordered_qty)}</TableCell>
                      <TableCell className="text-right tabular-nums">{hasCap ? fmtNum(isInternalPO ? item.internal_produced : item.good_from_cmt) : '—'}</TableCell>
                      <TableCell className="text-right tabular-nums">{hasCap ? fmtNum(item.reworked_ok) : '—'}</TableCell>
                      <TableCell className="text-right tabular-nums">{hasCap ? fmtNum(item.dispatched) : '—'}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {!hasCap ? '—' : lunas ? (
                          <StatusBadge status="lunas" label={notProduced ? 'Belum produksi' : 'Lunas'} tone="muted" testId={`dispatch-item-lunas-${item.sku || idx}`} />
                        ) : <span className="font-medium text-[hsl(var(--success-text))]" data-testid={`dispatch-item-shippable-${item.sku || idx}`}>{fmtNum(sisa)}</span>}
                      </TableCell>
                      <TableCell className="text-right">
                        <GlassInput type="number" min="0" max={hasCap ? sisa : item.ordered_qty} disabled={lunas}
                          data-testid={`dispatch-item-qty-${item.sku || idx}`} aria-label="Qty kirim"
                          className="w-24 h-8 text-right ml-auto" value={item.qty_shipped} onChange={(e) => updateItemQty(idx, e.target.value)} />
                        {lowStock && <span className="block text-xs text-[hsl(var(--warning-text))]" title="Stok fisik gudang lebih kecil dari sisa dokumen">stok {fmtNum(item.fg_stock)}</span>}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        </div>
      )}
      <Field label="Catatan">
        <Textarea rows={2} value={form.notes} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} />
      </Field>
    </FormPopup>
  );
}

/* ── Rincian satu surat jalan — di halaman ───────────────────────────────── */
function ShipmentDetail({ data, canForceEdit, onClose, onEditReceived }) {
  const items = data.items || [];
  const totalShipped = items.reduce((s, i) => s + (i.qty_shipped || 0), 0);
  const totalReceived = items.reduce((s, i) => s + (i.qty_received != null ? i.qty_received : (i.qty_shipped || 0)), 0);
  const [stLabel, stTone] = shipStatus(data.progress_pct || 0);
  const pdf = async (path, name) => { try { await downloadBlob(path, name); } catch (e) { toast.error(`Gagal mengunduh PDF: ${e.message}`); } };
  let cumulative = 0;
  return (
    <DetailPanel testId="buyer-shipment-detail" title={`Surat jalan ${data.shipment_number}`} onClose={onClose}
      description={[data.po_ids?.length > 1 ? `${data.po_ids.length} PO` : data.po_number, data.customer_name, data.vendor_name ? `CMT ${data.vendor_name}` : '', `dibuat ${fmtDate(data.created_at)}`].filter(Boolean).join(' · ')}
      actions={<>
        <StatusBadge status={stLabel} label={stLabel} tone={stTone} />
        <Button variant="outline" onClick={() => pdf(`/export-pdf?type=buyer-shipment&id=${data.id}`, `${data.shipment_number || 'Surat-Jalan'}-Total.pdf`)}
          data-testid="export-cumulative-pdf"><Download className="w-4 h-4" />PDF kumulatif</Button>
      </>}>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3" data-testid="received-summary-strip">
        <StatTile label="Total pesan" value={fmtNum(data.total_ordered)} suffix="pcs" />
        <StatTile label="Sudah dikirim" value={fmtNum(totalShipped)} suffix="pcs" sub={`${data.progress_pct || 0}% · sisa ${fmtNum(data.remaining)} pcs`} />
        <StatTile label="Diterima (aktual)" value={fmtNum(totalReceived)} suffix="pcs" />
        <StatTile label="Selisih" value={fmtNum(totalShipped - totalReceived)} suffix="pcs" accent={totalShipped - totalReceived > 0 ? 'danger' : 'muted'} />
      </div>
      {(data.dispatches || []).length > 0 && (
        <div className="overflow-x-auto">
          <Table data-testid="detail-dispatch-table">
            <TableHeader><TableRow>
              <TableHead>Kirim</TableHead><TableHead>SKU</TableHead><TableHead>Produk</TableHead>
              <TableHead className="text-right">Dikirim</TableHead><TableHead className="text-right">Diterima</TableHead>
              <TableHead className="text-right">Selisih</TableHead><TableHead className="text-right">HPP batch (FIFO)</TableHead>
              <TableHead className="text-right">Aksi</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {data.dispatches.map((d) => {
                cumulative += d.total_qty;
                return d.items.map((item, idx) => {
                  const received = item.qty_received != null ? item.qty_received : item.qty_shipped;
                  const variance = (item.qty_shipped || 0) - received;
                  return (
                    <TableRow key={item.id || `${d.dispatch_seq}-${idx}`}>
                      <TableCell className="whitespace-nowrap">
                        {idx === 0 ? <>
                          <span className="font-medium">#{d.dispatch_seq}</span>{' '}
                          <span className="text-xs text-muted-foreground">{fmtDate(d.dispatch_date)} · kumulatif {fmtNum(cumulative)}</span>
                          <Button variant="link" size="sm" className="h-auto p-0 ml-2" data-testid={`export-dispatch-${d.dispatch_seq}-pdf`}
                            onClick={() => pdf(`/export-pdf?type=buyer-shipment-dispatch&shipment_id=${data.id}&dispatch_seq=${d.dispatch_seq}`, `${data.shipment_number || 'Kiriman'}-D${d.dispatch_seq}.pdf`)}>PDF</Button>
                        </> : ''}
                      </TableCell>
                      <TableCell className="whitespace-nowrap">{item.sku || '—'}</TableCell>
                      <TableCell>{item.product_name} <span className="text-xs text-muted-foreground">{item.size}/{item.color}</span></TableCell>
                      <TableCell className="text-right tabular-nums">{fmtNum(item.qty_shipped)}</TableCell>
                      <TableCell className="text-right tabular-nums" data-testid={`received-badge-${item.id}`}>
                        {fmtNum(received)}{item.qty_received != null && <ClipboardCheck className="w-3 h-3 inline ml-1 text-muted-foreground" aria-label="dicatat" />}
                      </TableCell>
                      <TableCell className={`text-right tabular-nums ${variance > 0 ? 'text-[hsl(var(--danger-text))]' : ''}`}>
                        {variance > 0 ? fmtNum(variance) : variance < 0 ? `+${fmtNum(-variance)}` : '0'}
                      </TableCell>
                      <TableCell className="text-right tabular-nums" data-testid={`detail-item-cogs-${item.id || idx}`}><CogsCell item={item} /></TableCell>
                      <TableCell className="text-right">
                        {canForceEdit && (
                          <Button type="button" size="icon-sm" variant="ghost" onClick={() => onEditReceived(item, d.dispatch_seq)} title="Catat qty diterima (aktual)"
                            aria-label="Catat qty diterima" data-testid={`set-received-item-${item.id}`}><ClipboardCheck className="w-4 h-4" /></Button>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                });
              })}
            </TableBody>
          </Table>
        </div>
      )}
      {(data.summary_items || []).length > 0 && (
        <div className="overflow-x-auto">
          <p className="text-xs font-medium text-muted-foreground mb-1">Ringkasan per item</p>
          <Table>
            <TableHeader><TableRow>
              <TableHead>SKU</TableHead><TableHead>Produk</TableHead><TableHead className="text-right">Qty pesan</TableHead>
              <TableHead className="text-right">Total kirim</TableHead><TableHead className="text-right">Sisa</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {data.summary_items.map((item, idx) => (
                <TableRow key={idx}>
                  <TableCell className="whitespace-nowrap">{item.sku || '—'}</TableCell>
                  <TableCell>{item.product_name} <span className="text-xs text-muted-foreground">{item.size}/{item.color}</span></TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNum(item.ordered_qty)}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNum(item.cumulative_shipped)}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNum(Math.max(0, (item.ordered_qty || 0) - (item.cumulative_shipped || 0)))}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      <FileAttachmentPanel entityType="buyer_shipment" entityId={data.id} />
    </DetailPanel>
  );
}

/* ── Isian pendek: qty diterima aktual ───────────────────────────────────── */
function ReceivedDialog({ item, onClose, onSaved }) {
  const current = item.qty_received != null ? item.qty_received : item.qty_shipped;
  const [qty, setQty] = useState(String(current ?? 0));
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const short = qty !== '' ? (item.qty_shipped || 0) - Number(qty) : 0;
  const save = async () => {
    if (qty === '' || Number(qty) < 0) { toast.error('Qty diterima tidak valid'); return; }
    setSaving(true);
    try {
      const res = await apiPut(`/buyer-shipment-items/${item.id}/received`, { qty_received: Number(qty), reason: reason.trim() });
      const bs = res?.buyer_short;
      toast.success(`Qty diterima disimpan: ${res?.qty_received} pcs` + (bs
        ? ` · ${bs.qty_short} pcs belum sampai → catatan selisih ${bs.short_number} dibuka, surat jalan dikoreksi & stok barang jadi dikembalikan`
        : ` (selisih ${res?.variance ?? 0} pcs)`), { duration: bs ? 10000 : 5000 });
      onSaved();
    } catch (err) { toast.error(err.message || 'Gagal menyimpan qty diterima'); }
    finally { setSaving(false); }
  };
  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="set-received-form" judul="Catat qty diterima (aktual)"
      keterangan={`${item.product_name || '—'} · ${item.sku || '—'} · kiriman #${item.dispatch_seq || 1} · dikirim ${fmtNum(item.qty_shipped)} pcs`}
      onSimpan={save} menyimpan={saving} labelSimpan="Simpan qty diterima">
      <Field label="Qty diterima aktual (pcs) *" hint={qty !== '' ? `Selisih ${fmtNum(short)} pcs` : undefined}>
        <GlassInput type="number" min="0" autoFocus className="h-9" data-testid="set-received-qty-input" value={qty} onChange={(e) => setQty(e.target.value)} />
      </Field>
      {short > 0 && (
        <Notice tone="danger" icon={Info} testId="recv-short-notice" title={`${fmtNum(short)} pcs dianggap belum sampai`}>
          Qty surat jalan dikoreksi menjadi {fmtNum(Number(qty))} pcs (klaim awal tetap di jejak audit), catatan selisih dibuka,
          barangnya dikembalikan ke stok barang jadi supaya bisa dikirim ulang, dan Admin & Keuangan diberi tahu.
        </Notice>
      )}
      <Field label="Catatan (opsional)">
        <Textarea rows={2} data-testid="set-received-reason-input" placeholder="Contoh: 3 pcs cacat saat diterima" value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      {item.received_history?.length > 0 && (
        <div className="text-xs text-muted-foreground space-y-0.5">
          <p className="font-medium flex items-center gap-1"><History className="w-3.5 h-3.5" />Riwayat qty diterima</p>
          {item.received_history.map((h, i) => (
            <p key={i}><span className="tabular-nums text-foreground">{h.old_qty}→{h.new_qty}</span> · {fmtDate(h.edited_at)} · {h.edited_by}{h.reason ? `: ${h.reason}` : ''}</p>
          ))}
        </div>
      )}
    </FormPopup>
  );
}

/* ── Isian pendek: keputusan atas barang belum sampai ────────────────────── */
function BuyerShortDialog({ short, onClose, onSaved }) {
  const [resType, setResType] = useState('dikirim_ulang');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const save = async () => {
    setSaving(true);
    try {
      const res = await apiPost(`/buyer-shorts/${short.id}/resolve`, { resolution: resType, notes: notes.trim() });
      const wo = res?.short?.stock_writeoff_qty;
      toast.success(`Selisih ${short.short_number} diselesaikan` + (wo ? ` · ${wo} pcs stok barang jadi dihapusbukukan` : ''), { duration: 8000 });
      onSaved();
    } catch (e) { toast.error(e.message || 'Gagal menyimpan keputusan selisih'); }
    finally { setSaving(false); }
  };
  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="buyer-short-dialog" judul={`Putuskan selisih ${short.short_number}`}
      keterangan={`${short.shipment_number || '—'} · ${short.po_number || '—'} · ${short.customer_name || '—'} · ${short.sku || '—'} · dikirim ${fmtNum(short.qty_shipped_claimed)} → diterima ${fmtNum(short.qty_received)} pcs`}
      onSimpan={save} menyimpan={saving} labelSimpan="Simpan keputusan">
      <Field label="Keputusan *">
        <SmartNativeSelect value={resType} onChange={(e) => setResType(e.target.value)} data-testid="buyer-short-resolution" className="w-full h-9" aria-label="Keputusan">
          {BUYER_RESOLUTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </SmartNativeSelect>
      </Field>
      <Field label="Catatan">
        <Textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} data-testid="buyer-short-notes" placeholder="mis. hasil investigasi ekspedisi: barang hilang di jalan" />
      </Field>
      <Notice tone="info" icon={Info}>
        Pilihan hilang menghapusbukukan stok barang jadi {fmtNum(short.qty_open ?? short.qty_short)} pcs yang tadi dikembalikan, lalu mencatat
        pihak yang menanggung untuk diproses Keuangan. Dikirim ulang membiarkan barang tetap di stok — selisih tertutup otomatis saat kiriman ulang dibuat.
      </Notice>
    </FormPopup>
  );
}

/**
 * Order Terpadu (Portal Marketing) — pesanan dari semua platform marketplace.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, kartu angka StatTile (ikut toko yang dipilih — dulu kartu
 * selalu semua toko walau tabel disaring toko), pil status FilterChips, tabel standar + unduh Excel/CSV semua
 * baris hasil saringan, rincian pesanan = popup, ubah status / ubah massal = FormPopup, tanpa emoji.
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  ShoppingBag, Truck, RotateCcw, Search, RefreshCw, AlertCircle, AlertTriangle, X, ClipboardList,
  ChevronDown, Pencil, Eye,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { Textarea } from '@/components/ui/textarea';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import PaginationLite from '@/components/ui/pagination-lite';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useToast } from '@/hooks/use-toast';
import axios from 'axios';
import { formatDateID, formatDateTimeID } from '@/lib/format';
import { parseServerTime } from '@/lib/waktu';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';
import { MarketingAccountSelect } from './pickers/MarketingPickers';
import { labelKanal } from '@/lib/kanalPenjualan';

const API = process.env.REACT_APP_BACKEND_URL;

// ── Constants ──
const STATUS_CONFIG = {
  new:       { label: 'Baru',     tone: 'info' },
  packed:    { label: 'Dikemas',  tone: 'warning' },
  shipped:   { label: 'Dikirim',  tone: 'primary' },
  delivered: { label: 'Terkirim', tone: 'success' },
  cancelled: { label: 'Batal',    tone: 'danger' },
  returned:  { label: 'Retur',    tone: 'warning' },
};
const PLATFORM_LABEL = { shopee: 'Shopee', tiktok: 'TikTok', tiktokshop: 'TikTok', tokopedia: 'Tokopedia', lazada: 'Lazada' };
const labelPlatform = (p) => PLATFORM_LABEL[String(p || '').toLowerCase()] || p || '—';
const labelStatus = (s) => STATUS_CONFIG[s]?.label || s || '—';

function fmt(n) { return new Intl.NumberFormat('id-ID').format(n || 0); }
function fmtRp(n) { return `Rp ${fmt(n)}`; }
// order_date = jam dinding WIB tanpa zona; stempel lain = UTC tanpa zona → parseServerTime
const fmtDate = (d) => (d ? formatDateTimeID(parseServerTime(d)) : '—');
const fmtTgl = (d) => (d ? formatDateID(parseServerTime(d)) : '—');

function StatusPesanan({ status }) {
  const c = STATUS_CONFIG[status] || STATUS_CONFIG.new;
  return <StatusBadge status={status} label={c.label} tone={c.tone} />;
}

// 14 Nov 2026 — pesanan yang sudah dikirim boleh dibatalkan (COD gagal kirim / paket ditolak): server membuat
// tugas Gudang › Retur Fisik "Menunggu paket" lewat jalur yang sama dengan ubah status massal. "Retur" hanya
// mengubah status (retur dari pembeli diurus di Komplain & Retur), jadi paket kembali dari ekspedisi dicatat Batal.
const VALID_NEXT = {
  new: ['packed', 'cancelled'],
  packed: ['shipped', 'cancelled'],
  shipped: ['delivered', 'cancelled', 'returned'],
  delivered: ['cancelled', 'returned'],
  cancelled: [],
  returned: [],
};
const sudahDikirim = (o) => ['shipped', 'delivered', 'completed'].includes(o?.status)
  || !!(o?.shipped_date || o?.delivered_date);

// ── Rincian pesanan (popup) + ubah status (form popup) ──
function OrderDetailPopup({ order, onClose, onStatusChange }) {
  const [formOpen, setFormOpen] = useState(false);
  const [updating, setUpdating] = useState(false);
  const [newStatus, setNewStatus] = useState('');
  const [note, setNote] = useState('');
  const [galat, setGalat] = useState('');
  const { toast } = useToast();

  if (!order) return null;
  const nexts = VALID_NEXT[order.status] || [];
  const dikirim = sudahDikirim(order);
  const batalSetelahKirim = newStatus === 'cancelled' && dikirim;
  const labelPilihan = (s) => (s === 'cancelled' && dikirim ? 'Batal (gagal kirim / paket kembali)' : labelStatus(s));

  const handleStatusUpdate = async () => {
    if (!newStatus) { setGalat('Pilih status baru.'); return; }
    if (batalSetelahKirim && !note.trim()) { setGalat('Isi alasan pembatalan.'); return; }
    setUpdating(true);
    setGalat('');
    try {
      const res = await axios.patch(`${API}/api/marketing/orders/${order.id}/status`,
        { status: newStatus, note: note.trim() || null },
        { headers: { Authorization: `Bearer ${localStorage.getItem('erp_token')}` } }
      );
      const freed = Number(res?.data?.reservation_released || 0);
      toast({
        title: `Status diubah ke ${labelStatus(newStatus)}`,
        description: freed > 0
          ? `Reservasi stok ${freed.toLocaleString('id-ID')} pcs dilepas kembali ke stok jual.`
          : undefined,
      });
      setFormOpen(false);
      onStatusChange();
      onClose();
    } catch (e) {
      // F10 — alasan penolakan WAJIB sampai ke layar (mis. menghidupkan order yang sudah dibatalkan).
      setGalat(e?.response?.data?.detail || e.message);
    } finally {
      setUpdating(false);
    }
  };

  return (
    <>
      <DetailPopup open onClose={onClose} judul={order.order_id} testId="order-detail"
        keterangan={`${labelPlatform(order.platform)} · ${order.account_name || 'toko belum diketahui'}`}
        status={<StatusPesanan status={order.status} />}
        aksi={nexts.length > 0 && (
          <Button size="sm" onClick={() => { setNewStatus(''); setNote(''); setGalat(''); setFormOpen(true); }}
            data-testid="order-detail-ubah-status"><Pencil />Ubah status</Button>
        )}>
        <section className="space-y-1">
          <p className="text-sm font-medium">Pesanan</p>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Produk">{order.product_name || '—'}</BarisDetail>
            <BarisDetail label="Variasi">{order.variation || '—'}</BarisDetail>
            <BarisDetail label="SKU">{order.sku_id || '—'}</BarisDetail>
            <BarisDetail label="Jumlah">{fmt(order.quantity)}</BarisDetail>
            <BarisDetail label="Harga">{fmtRp(order.price_final)}</BarisDetail>
            <BarisDetail label="Diskon penjual">{order.discount_seller > 0 ? fmtRp(order.discount_seller) : '—'}</BarisDetail>
            <BarisDetail label="Ongkir">{fmtRp(order.shipping_cost)}</BarisDetail>
            <BarisDetail label="Total dibayar"><b>{fmtRp(order.total_payment)}</b></BarisDetail>
            <BarisDetail label="Metode bayar">{order.payment_method || '—'}</BarisDetail>
            {/* 11 Nov 2026 — dari mana pembeli datang (dasar pecahan kanal di rekap harian) */}
            <BarisDetail label="Kanal">{order.order_channel ? labelKanal(order.order_channel) : 'Lainnya (tanpa kanal)'}</BarisDetail>
            <BarisDetail label="Akun kreator">{order.creator_handle || '—'}</BarisDetail>
          </dl>
        </section>
        <section className="space-y-1">
          <p className="text-sm font-medium">Pengiriman</p>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Penerima">{order.customer_name || '—'}</BarisDetail>
            <BarisDetail label="Kota">{order.city || '—'}</BarisDetail>
            <BarisDetail label="Kurir">{order.courier || '—'}</BarisDetail>
            <BarisDetail label="Resi">{order.tracking_number || '—'}</BarisDetail>
            <BarisDetail label="Dipesan">{fmtDate(order.order_date)}</BarisDetail>
            <BarisDetail label="Dikemas">{fmtDate(order.packed_date)}</BarisDetail>
            <BarisDetail label="Dikirim">{fmtDate(order.shipped_date)}</BarisDetail>
            <BarisDetail label="Terkirim">{fmtDate(order.delivered_date)}</BarisDetail>
          </dl>
        </section>
      </DetailPopup>
      <FormPopup open={formOpen} onClose={() => setFormOpen(false)} ukuran="pendek" onSimpan={handleStatusUpdate}
        menyimpan={updating} galat={galat} bisaSimpan={!!newStatus && (!batalSetelahKirim || !!note.trim())}
        judul="Ubah status pesanan" testId="order-status-form"
        keterangan={`${order.order_id} · sekarang ${labelStatus(order.status)}`}>
        <Isian label="Status baru" wajib htmlFor="order-status-baru"
          petunjuk={newStatus === 'returned' && dikirim
            ? 'Retur hanya mengubah status; retur dari pembeli diurus di menu Komplain & Retur. Paket yang kembali dari ekspedisi (COD gagal kirim, ditolak pembeli) catat sebagai Batal supaya menjadi tugas Gudang.'
            : undefined}>
          <SmartNativeSelect id="order-status-baru" className="w-full" value={newStatus}
            onChange={(e) => setNewStatus(e.target.value)} data-testid="order-status-select">
            <option value="">Pilih status baru…</option>
            {nexts.map(s => <option key={s} value={s}>{labelPilihan(s)}</option>)}
          </SmartNativeSelect>
        </Isian>
        {batalSetelahKirim ? (
          <Isian label="Alasan pembatalan" wajib htmlFor="order-cancel-reason"
            petunjuk='Pesanan ini sudah dikirim: otomatis menjadi tugas Gudang › Retur Fisik "Menunggu paket". Stok bertambah setelah gudang menerima paketnya.'>
            <Textarea id="order-cancel-reason" value={note} onChange={(e) => setNote(e.target.value)} rows={2}
              placeholder="Contoh: COD gagal kirim / paket ditolak pembeli" data-testid="order-cancel-reason-input" />
          </Isian>
        ) : (
          <Isian label="Catatan" htmlFor="order-status-catatan">
            <Input id="order-status-catatan" placeholder="Opsional" value={note} onChange={e => setNote(e.target.value)} />
          </Isian>
        )}
      </FormPopup>
    </>
  );
}

// ── Daftar ambil barang (picking list) ──
// BUG (2026-08-14): komponen ini dulu memakai `accountFilter` milik induk ⇒ ReferenceError. Lingkup toko
// DIKIRIM sebagai prop — daftar picking mengikuti toko yang sedang dipilih di layar.
function PickingListPopup({ open, onClose, token, accountFilter = '' }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [platform, setPlatform] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // 2026-11-09 (audit gudang G10): pesanan "Perlu Dikirim" (paid) + "Dikemas"; barang per baris pesanan (items[])
      const params = { statuses: 'paid,packed' };
      if (accountFilter) params.account_id = accountFilter;
      if (platform) params.platform = platform;
      const res = await axios.get(`${API}/api/marketing/orders/picking-list`, {
        params,
        // Kunci token app ini `erp_token` (lihat lib/apiFetch.js)
        headers: { Authorization: `Bearer ${token || localStorage.getItem('erp_token') || ''}` },
      });
      setData(res.data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [platform, token, accountFilter]);

  useEffect(() => { if (open) load(); }, [open, load]);
  const daftar = data?.picking_list || [];

  return (
    <DetailPopup open={open} onClose={onClose} judul="Daftar ambil barang" testId="picking-list"
      keterangan="SKU per baris barang dari pesanan Perlu Dikirim dan Dikemas — untuk disiapkan gudang. Barang yang belum tertaut master ditandai."
      aksi={<>
        <SmartNativeSelect className="w-40" value={platform} onChange={(e) => setPlatform(e.target.value)}
          data-testid="picking-platform">
          <option value="">Semua platform</option>
          <option value="shopee">Shopee</option>
          <option value="tiktok">TikTok</option>
          <option value="tokopedia">Tokopedia</option>
        </SmartNativeSelect>
        <TombolUnduh namaBerkas="daftar-ambil-barang" namaLembar="Ambil barang" baris={daftar} testId="picking-unduh"
          kolom={[
            { label: 'SKU', nilai: (i) => i.sku_id }, { label: 'Variasi', nilai: (i) => i.variation || '' },
            { label: 'Tertaut master', nilai: (i) => (i.linked ? 'Ya' : 'Belum') },
            { label: 'Produk', nilai: (i) => i.product_name || '' }, { label: 'Jumlah (pcs)', nilai: (i) => Number(i.total_qty || 0) },
            { label: 'Pesanan', nilai: (i) => Number(i.order_count || 0) },
          ]} />
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}>
      {data && <p className="text-sm text-muted-foreground">{fmt(data.total_items)} SKU dari {fmt(data.total_orders)} pesanan.</p>}
      {loading && !data ? (
        <p className="py-8 text-center text-sm text-muted-foreground">Memuat daftar…</p>
      ) : (
        <TabelData baris={daftar} kunci={(i) => `${i.fg_material_id || i.sku_id}-${i.variation}-${i.product_name}`} testId="picking-table"
          kosong={<EmptyState icon={ClipboardList} title="Tidak ada pesanan untuk dikemas"
            description="Pesanan berstatus Perlu Dikirim atau Dikemas akan muncul di sini." />}
          kolom={[
            { kunci: 'sku', label: 'SKU', hp: 'judul', isi: (i) => (
              <span className="font-medium">{i.sku_id || '—'}{!i.linked && <span className="ml-1 text-xs font-normal text-[hsl(var(--warning-text))]">belum tertaut</span>}</span>) },
            { kunci: 'var', label: 'Variasi', isi: (i) => i.variation || '—' },
            { kunci: 'produk', label: 'Produk', isi: (i) => <span className="block max-w-[16rem] truncate" title={i.product_name}>{i.product_name}</span> },
            { kunci: 'qty', label: 'Jumlah', rata: 'kanan', isi: (i) => <span className="tabular-nums font-semibold">{fmt(i.total_qty)} pcs</span> },
            { kunci: 'order', label: 'Pesanan', rata: 'kanan', isi: (i) => <span className="tabular-nums">{fmt(i.order_count)}</span> },
          ]} />
      )}
    </DetailPopup>
  );
}

// ── Main Component ──
export default function UnifiedOrdersDashboard({ token, onNavigate }) {
  const { toast } = useToast();
  const [summary, setSummary] = useState(null);
  const [orders, setOrders] = useState([]);
  const [pagination, setPagination] = useState(null);
  const [loading, setLoading] = useState(true);
  const [summaryLoading, setSummaryLoading] = useState(true);

  // Filters
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [platformFilter, setPlatformFilter] = useState('');
  const [accountFilter, setAccountFilter] = useState('');
  const [page, setPage] = useState(1);

  // UI state
  const [selectedOrder, setSelectedOrder] = useState(null);
  const [showPickingList, setShowPickingList] = useState(false);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [bulkStatus, setBulkStatus] = useState('');
  const [bulkDialog, setBulkDialog] = useState(false);
  const [bulkSaving, setBulkSaving] = useState(false);
  // 2026-11-02 (K6) — alasan WAJIB untuk membatalkan pesanan yang sudah dikirim
  // (server menolak tanpa alasan; pembatalan itu membuat pengajuan Retur Fisik RTS).
  const [bulkNote, setBulkNote] = useState('');
  // F10 — hasil massal per-order (order mana yang GAGAL & kenapa).
  const [bulkResult, setBulkResult] = useState(null);

  const authH = { Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` };
  const debounceRef = useRef(null);

  const fetchSummary = useCallback(async () => {
    setSummaryLoading(true);
    try {
      // F14 — ringkasan memakai lingkup toko yang SAMA dengan tabel (dulu kartu selalu semua toko)
      const params = accountFilter ? { account_id: accountFilter } : {};
      const res = await axios.get(`${API}/api/marketing/orders/summary`, { params, headers: authH });
      setSummary(res.data);
    } finally { setSummaryLoading(false); }
  }, [token, accountFilter]); // eslint-disable-line

  const paramsSaring = () => {
    const params = {};
    // F14 — filter per TOKO memakai `account_id` (SSOT), bukan mencocokkan nama.
    if (accountFilter)  params.account_id = accountFilter;
    if (statusFilter)   params.status   = statusFilter;
    if (platformFilter) params.platform = platformFilter;
    if (search)         params.search   = search;
    return params;
  };

  const fetchOrders = useCallback(async () => {
    setLoading(true);
    try {
      const params = { page, page_size: 25, ...paramsSaring() };
      const res = await axios.get(`${API}/api/marketing/orders`, { params, headers: authH });
      setOrders(res.data.orders || []);
      setPagination(res.data.pagination);
    } finally { setLoading(false); }
  }, [page, statusFilter, platformFilter, accountFilter, search, token]); // eslint-disable-line

  useEffect(() => { fetchSummary(); }, [fetchSummary]);
  useEffect(() => { fetchOrders(); }, [fetchOrders]);

  // Unduh = SEMUA pesanan hasil saringan (bukan hanya halaman yang tampil)
  const ambilSemua = async () => {
    const out = [];
    // M-22 (audit 9 Nov 2026) — server membatasi page_size ≤ 100; dulu 200 ⇒ HTTP 422 dan
    // "Unduh semua" gagal. Halaman 100 baris diulang sampai habis (maks. 40.000 pesanan).
    for (let p = 1; p <= 400; p += 1) {
      const res = await axios.get(`${API}/api/marketing/orders`, { params: { page: p, page_size: 100, ...paramsSaring() }, headers: authH });
      out.push(...(res.data.orders || []));
      if (p >= (res.data.pagination?.total_pages || 1)) break;
    }
    return out;
  };

  const handleSearchChange = (e) => {
    const val = e.target.value;
    setSearch(val);
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setPage(1), 400);
  };

  const handleBulkStatus = async () => {
    if (!bulkStatus || selectedIds.size === 0) return;
    setBulkSaving(true);
    try {
      const res = await axios.post(`${API}/api/marketing/orders/bulk-status`,
        { order_ids: Array.from(selectedIds), status: bulkStatus, note: bulkNote.trim() || null },
        { headers: authH }
      );
      // F10 — backend melapor per-order; kegagalan TIDAK boleh ditelan.
      const d = res.data || {};
      const done = d.updated_count ?? selectedIds.size;
      const failed = d.failed_count || 0;
      const freed = Number(d.reservation_released || 0);
      setBulkResult(failed ? { failed: d.failed || [], done, status: bulkStatus } : null);
      toast({
        title: `${done} pesanan diubah ke ${labelStatus(bulkStatus)}`
          + (failed ? ` · ${failed} gagal` : ''),
        description: freed > 0
          ? `Reservasi stok ${freed.toLocaleString('id-ID')} pcs dilepas kembali ke stok jual.`
          : (failed ? (d.failed || [])[0]?.reason : undefined),
        variant: failed ? 'destructive' : undefined,
      });
      setSelectedIds(new Set()); setBulkStatus(''); setBulkNote('');
      fetchOrders(); fetchSummary();
    } catch (e) {
      toast({
        title: 'Ubah status massal gagal',
        description: e?.response?.data?.detail || e.message,
        variant: 'destructive',
      });
    } finally {
      setBulkSaving(false);
    }
    setBulkDialog(false);
  };

  const byStatus = summary?.by_status || {};
  const byPlatform = summary?.by_platform || {};
  const rincianPlatform = Object.entries(byPlatform)
    .map(([p, v]) => `${fmt(v?.count)} ${labelPlatform(p)}`).join(' · ');
  const lingkup = accountFilter ? 'toko terpilih' : 'semua toko';
  const nilai = (v) => (summaryLoading && !summary ? '…' : v);
  const opsiStatus = [
    { key: '', label: 'Semua', count: summary?.total_orders || 0 },
    ...Object.entries(STATUS_CONFIG).filter(([s]) => byStatus[s] || statusFilter === s)
      .map(([s, cfg]) => ({ key: s, label: cfg.label, count: byStatus[s] || 0 })),
  ];

  const semuaDipilih = orders.length > 0 && orders.every(o => selectedIds.has(o.id));
  const kolom = [
    { kunci: 'pilih', hp: 'aksi', lebar: 'w-8',
      label: <Checkbox checked={semuaDipilih} aria-label="Pilih semua di halaman ini"
        onCheckedChange={(v) => setSelectedIds(v ? new Set(orders.map(o => o.id)) : new Set())} />,
      isi: (o) => <Checkbox checked={selectedIds.has(o.id)} aria-label={`Pilih ${o.order_id}`}
        onCheckedChange={(v) => { const n = new Set(selectedIds); if (v) n.add(o.id); else n.delete(o.id); setSelectedIds(n); }} /> },
    { kunci: 'order', label: 'Pesanan', hp: 'judul', isi: (o) => (
      <div data-testid={`order-row-${o.id}`}>
        <p className="font-medium text-foreground">{o.order_id}</p>
        <p className="text-xs text-muted-foreground">{labelPlatform(o.platform)}{o.account_name ? ` · ${o.account_name}` : ''}</p>
      </div>) },
    { kunci: 'produk', label: 'Produk', isi: (o) => (
      <div className="min-w-0 md:max-w-[16rem]">
        <p className="truncate text-sm" title={o.product_name}>{o.product_name}</p>
        <p className="truncate text-xs text-muted-foreground">{[o.variation, o.sku_id].filter(Boolean).join(' · ')}</p>
      </div>) },
    { kunci: 'qty', label: 'Jumlah', rata: 'kanan', isi: (o) => <span className="tabular-nums">{fmt(o.quantity)}</span> },
    { kunci: 'total', label: 'Total', rata: 'kanan', isi: (o) => <span className="tabular-nums md:whitespace-nowrap">{fmtRp(o.total_payment)}</span> },
    { kunci: 'pembeli', label: 'Pembeli', isi: (o) => (
      <div><p className="text-sm">{o.customer_name || '—'}</p><p className="text-xs text-muted-foreground">{o.city}</p></div>) },
    { kunci: 'status', label: 'Status', isi: (o) => <StatusPesanan status={o.status} /> },
    { kunci: 'tgl', label: 'Tanggal pesan', isi: (o) => <span className="text-sm text-muted-foreground md:whitespace-nowrap">{fmtTgl(o.order_date)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (o) => (
      <Button size="sm" variant="outline" onClick={() => setSelectedOrder(o)} data-testid={`btn-order-detail-${o.id}`}>
        <Eye />Rincian
      </Button>) },
  ];

  const alurLanjut = typeof onNavigate === 'function' && (
    // RC-FLOW-UX-CORE — lanjutan alur pesanan (dulu kotak "Lanjutkan alur order" selebar halaman)
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" data-testid="orders-alur-lanjut">Alur berikutnya<ChevronDown /></Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        {/* 2026-11-02 (K6) — pesanan marketplace dikirim lewat Seller Center → Monitoring kirim */}
        <DropdownMenuItem onSelect={() => onNavigate('marketing-fulfillment', {})}><Truck className="mr-2 h-4 w-4" />Monitoring kirim</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => onNavigate('marketing-complaints', {})}><AlertCircle className="mr-2 h-4 w-4" />Komplain pelanggan</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => onNavigate('marketing-returns', {})}><RotateCcw className="mr-2 h-4 w-4" />Retur &amp; refund</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );

  return (
    <PageLayout testId="orders-dashboard" title="Order terpadu"
      subtitle="Pesanan dari semua platform marketplace, statusnya, dan daftar ambil barang."
      actions={<>
        {alurLanjut}
        <Button onClick={() => setShowPickingList(true)} data-testid="btn-picking-list"><ClipboardList />Daftar ambil barang</Button>
      </>}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder="Cari nomor pesanan, produk, pembeli" className="pl-8" value={search}
            onChange={handleSearchChange} data-testid="search-orders" />
        </div>
        <div className="w-full sm:w-52">
          <MarketingAccountSelect token={token} value={accountFilter}
            onChange={(v) => { setAccountFilter(v); setPage(1); }} label=""
            includeAll allLabel="Semua toko" required={false} testId="orders-filter-account" />
        </div>
        <SmartNativeSelect className="w-40" value={platformFilter} data-testid="orders-filter-platform"
          onChange={(e) => { setPlatformFilter(e.target.value); setPage(1); }}>
          <option value="">Semua platform</option>
          <option value="shopee">Shopee</option>
          <option value="tiktok">TikTok</option>
          <option value="tokopedia">Tokopedia</option>
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="pesanan-marketplace" namaLembar="Pesanan" baris={orders} ambilSemua={ambilSemua}
          testId="orders-export-csv"
          kolom={[
            { label: 'Nomor pesanan', nilai: (o) => o.order_id }, { label: 'Platform', nilai: (o) => labelPlatform(o.platform) },
            { label: 'Toko', nilai: (o) => o.account_name || '' }, { label: 'Produk', nilai: (o) => o.product_name || '' },
            { label: 'Variasi', nilai: (o) => o.variation || '' }, { label: 'SKU', nilai: (o) => o.sku_id || '' },
            { label: 'Jumlah', nilai: (o) => Number(o.quantity || 0) }, { label: 'Total (Rp)', nilai: (o) => Number(o.total_payment || 0) },
            { label: 'Pembeli', nilai: (o) => o.customer_name || '' }, { label: 'Kota', nilai: (o) => o.city || '' },
            { label: 'Status', nilai: (o) => labelStatus(o.status) }, { label: 'Tanggal pesan', nilai: (o) => fmtTgl(o.order_date) },
          ]} />
        <Button variant="outline" size="icon" onClick={() => { fetchSummary(); fetchOrders(); }} disabled={loading}
          title="Muat ulang" aria-label="Muat ulang" data-testid="orders-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={<>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="orders-kpi">
          <StatTile label="Pesanan" value={nilai(fmt(summary?.total_orders))}
            sub={`Semua status, ${lingkup}${rincianPlatform ? ` · ${rincianPlatform}` : ''}`} />
          <StatTile label="Perlu tindakan" value={nilai(fmt(summary?.need_action))} accent={summary?.need_action ? 'warning' : 'default'}
            sub={`${fmt(byStatus.new || 0)} baru + ${fmt(byStatus.packed || 0)} dikemas`} />
          <StatTile label="Omzet (semua waktu)" value={nilai(fmtRp(summary?.total_revenue))}
            sub={`Hari ini ${fmtRp(summary?.today?.revenue)}${summary?.returned_revenue ? ` · retur ${fmtRp(summary.returned_revenue)}` : ''}`} />
          <StatTile label="Minggu ini" value={nilai(`${fmt(summary?.this_week?.orders)} pesanan`)}
            sub={`Omzet ${fmtRp(summary?.this_week?.revenue)} sejak Senin`} />
        </div>
        <FilterChips options={opsiStatus} value={statusFilter} hideWhenEmpty={false} testId="orders-status-chips"
          onChange={(v) => { setStatusFilter(v); setPage(1); }} />
      </>}
      footer={pagination && pagination.total > 0 && (
        <PaginationLite page={page} totalPages={pagination.total_pages || 1} total={pagination.total || 0} pageSize={25}
          onPageChange={setPage} />
      )}>
      {selectedIds.size > 0 && (
        <div className="flex flex-wrap items-center gap-2" data-testid="orders-bulk-bar">
          <span className="text-sm font-medium">{selectedIds.size} pesanan dipilih</span>
          <SmartNativeSelect className="w-40" value={bulkStatus} onChange={(e) => setBulkStatus(e.target.value)}
            data-testid="orders-bulk-status">
            <option value="">Ubah status ke…</option>
            {['packed', 'shipped', 'delivered', 'cancelled'].map(s => <option key={s} value={s}>{labelStatus(s)}</option>)}
          </SmartNativeSelect>
          <Button size="sm" variant="outline" onClick={() => bulkStatus && setBulkDialog(true)} disabled={!bulkStatus}>Terapkan</Button>
          <Button size="sm" variant="link" onClick={() => setSelectedIds(new Set())}><X />Batalkan pilihan</Button>
        </div>
      )}

      {loading && orders.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat pesanan…</p>
      ) : (
        <TabelData kolom={kolom} baris={orders} onKlikBaris={setSelectedOrder} testId="orders-table"
          kosong={<EmptyState icon={ShoppingBag} title="Tidak ada pesanan"
            description={summary?.total_orders ? 'Ubah pencarian atau saringan.' : 'Belum ada pesanan. Impor ekspor pesanan Seller Center di menu Impor Data.'} />} />
      )}

      {selectedOrder && (
        <OrderDetailPopup order={selectedOrder} onClose={() => setSelectedOrder(null)}
          onStatusChange={() => { fetchOrders(); fetchSummary(); }} />
      )}

      <PickingListPopup open={showPickingList} onClose={() => setShowPickingList(false)} token={token} accountFilter={accountFilter} />

      {/* Konfirmasi ubah status massal */}
      <FormPopup open={bulkDialog} onClose={() => setBulkDialog(false)} ukuran="pendek" onSimpan={handleBulkStatus}
        menyimpan={bulkSaving} labelSimpan="Terapkan" testId="bulk-status-dialog"
        judul={`Ubah status ${selectedIds.size} pesanan?`}
        keterangan={`Status diubah ke ${labelStatus(bulkStatus)} untuk ${selectedIds.size} pesanan yang dipilih.`}>
        {/* F10 — konsekuensi STOK ditulis di depan: membatalkan order melepas reservasinya. */}
        {(bulkStatus === 'cancelled' || bulkStatus === 'returned') && (
          <Notice tone="warning" icon={AlertTriangle} testId="bulk-cancel-stock-note" title="Reservasi stok akan dilepas">
            Stok yang ditahan untuk pesanan ini kembali menjadi stok jual. Pesanan yang sudah dibatalkan/diretur tidak bisa
            dihidupkan lagi — bila pembeli memesan ulang, buat pesanan baru.
          </Notice>
        )}
        {bulkStatus === 'cancelled' && (
          <Isian label="Alasan pembatalan" htmlFor="bulk-cancel-reason"
            petunjuk='Wajib untuk pesanan yang SUDAH dikirim: otomatis menjadi pengajuan Retur Fisik "RTS" di Gudang, stok bertambah setelah gudang menerima paketnya. Tanpa alasan, pesanan terkirim dilewati.'>
            <div data-testid="bulk-cancel-reason">
              <Textarea id="bulk-cancel-reason" value={bulkNote} onChange={(e) => setBulkNote(e.target.value)} rows={2}
                placeholder="Contoh: gagal kirim / paket ditolak pembeli" data-testid="bulk-cancel-reason-input" />
            </div>
          </Isian>
        )}
      </FormPopup>

      {/* F10 — laporan kegagalan per-order */}
      <DetailPopup open={!!bulkResult} onClose={() => setBulkResult(null)} testId="bulk-status-result"
        judul={`${bulkResult?.done || 0} berhasil · ${bulkResult?.failed?.length || 0} tidak bisa diubah`}
        keterangan="Pesanan berikut tidak diubah. Alasannya ditulis apa adanya supaya bisa ditindaklanjuti.">
        <TabelData baris={bulkResult?.failed || []} kunci={(f) => f.order_id} testId="bulk-status-failed"
          kolom={[
            { kunci: 'order', label: 'Pesanan', hp: 'judul', isi: (f) => f.order_ref || f.order_id },
            { kunci: 'alasan', label: 'Alasan', isi: (f) => f.reason },
          ]} />
      </DetailPopup>
    </PageLayout>
  );
}

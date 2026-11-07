/**
 * Peluncuran produk (Portal Toko) — rencana peluncuran produk multi-platform.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, penyaring satu baris, ViewToggle Tabel/Linimasa di alat,
 * 4 StatTile berketerangan, tabel + unduh Excel/CSV semua baris (dulu CSV halaman ini saja), detail popup,
 * form = FormPopup + DatePicker, label Indonesia, tanpa emoji. Linimasa dibuat ringkas (dulu kartu per produk).
 * F14b (produk wajib dari Master Produk) dan peringatan "belum tertaut" tetap.
 */
import { confirmDialog } from '@/components/ui/confirm-dialog';
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Plus, Pencil, Trash2, RefreshCw, AlertTriangle, Search, Table2, CalendarDays } from 'lucide-react';
import axios from 'axios';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import { Textarea } from '@/components/ui/textarea';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import DatePicker from '@/components/ui/date-picker';
import ViewToggle from '@/components/ui/view-toggle';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import PaginationLite from '@/components/ui/pagination-lite';
import { useToast } from '@/hooks/use-toast';
import { formatRupiah, formatDateID } from '@/lib/format';
import { todayWIB } from '@/lib/waktu';
import { cn } from '@/lib/utils';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';
import { MarketingAccountSelect, useStorePlatforms } from './pickers/MarketingPickers';
// F14b (temuan pemilik) — produk yang diluncurkan WAJIB produk yang ada di Master Produk.
import MasterProductSelect from '../pickers/MasterProductSelect';

const API = process.env.REACT_APP_BACKEND_URL;

const PLATFORM_LABEL = { shopee: 'Shopee', tiktok: 'TikTok', tokopedia: 'Tokopedia', instagram: 'Instagram', website: 'Situs web' };
const labelPlatform = (p) => PLATFORM_LABEL[p] || (p ? p.charAt(0).toUpperCase() + p.slice(1) : '—');
const STATUS_CONFIG = {
  planning: { label: 'Perencanaan', tone: 'muted' },
  ready: { label: 'Siap diluncurkan', tone: 'info' },
  launched: { label: 'Sudah diluncurkan', tone: 'success' },
  postponed: { label: 'Ditunda', tone: 'warning' },
  cancelled: { label: 'Dibatalkan', tone: 'danger' },
};
const StatusPeluncuran = ({ status }) => {
  const c = STATUS_CONFIG[status] || STATUS_CONFIG.planning;
  return <StatusBadge status={status} label={c.label} tone={c.tone} />;
};
const VIEWS = [
  { key: 'table', label: 'Tampilan tabel', icon: Table2 },
  { key: 'timeline', label: 'Tampilan linimasa', icon: CalendarDays },
];
const tgl = (v) => (v ? formatDateID(String(v).slice(0, 10)) : '—');
const fmtRp = (n) => n ? formatRupiah(n) : '—';
function fmt(n)   { return new Intl.NumberFormat('id-ID').format(n || 0); }

const EMPTY_FORM = {
  // F14 — peluncuran WAJIB milik satu toko. Sebelum ini 8/8 dokumen demo tidak
  // punya `account_id` maupun `target_account_ids`, jadi rencana peluncuran tidak
  // bisa dicari dari toko mana pun.
  account_id: '',
  // F14b — identitas produk datang dari MASTER, bukan diketik. Yang disimpan
  // form hanyalah `model_id`; nama/kode/kategori/HPP/harga resmi DITULIS SERVER
  // (kiriman browser diabaikan), jadi layar tidak bisa berbeda dengan master.
  model_id: '',
  master: null,          // objek master terpilih — hanya untuk TAMPILAN
  launch_date: '',
  original_price: '', flash_sale_price: '', cross_price: '', listing_price: '',
  platforms: [], description: '', status: 'planning', launch_notes: ''
};

export default function ProductLaunchModule({ token }) {
  const { toast } = useToast();
  const authH = useMemo(() => ({ Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` }), [token]);
  const PLATFORMS = useStorePlatforms(token);

  const [summary,    setSummary]    = useState(null);
  const [items,      setItems]      = useState([]);
  const [pagination, setPagination] = useState(null);
  const [unlinked,   setUnlinked]   = useState(0);
  const [loading,    setLoading]    = useState(true);
  const [filterAccountId, setFilterAccountId] = useState('');

  const [filterStatus,  setFilterStatus]  = useState('');
  const [filterPlatform,setFilterPlatform]= useState('');
  const [search,        setSearch]        = useState('');
  const [page,          setPage]          = useState(1);
  const [viewMode,      setViewMode]      = useState('table'); // 'table' | 'timeline'
  const [detail,        setDetail]        = useState(null);
  const [galatForm,     setGalatForm]     = useState('');

  const [showForm,    setShowForm]    = useState(false);
  const [editTarget,  setEditTarget]  = useState(null);
  const [form,        setForm]        = useState(EMPTY_FORM);
  const [formLoading, setFormLoading] = useState(false);

  const fetchSummary = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/api/marketing/product-launches/summary`, { headers: authH });
      if (res.data.success) setSummary(res.data.data);
    } catch { /* ringkasan gagal dibaca — daftar di bawah tetap ditampilkan */ }
  }, [authH]);

  const fetchItems = useCallback(async () => {
    setLoading(true);
    try {
      const params = { page, page_size: 20 };
      if (filterStatus)   params.status   = filterStatus;
      if (filterPlatform) params.platform = filterPlatform;
      if (filterAccountId) params.account_id = filterAccountId;
      if (search)         params.search   = search;
      const res = await axios.get(`${API}/api/marketing/product-launches`, { params, headers: authH });
      if (res.data.success) {
        setItems(res.data.data || []);
        setPagination(res.data.pagination);
        // F14b — jumlah rencana yang belum tertaut master DIHITUNG SERVER dan
        // diakui di layar. Angka warisan yang disembunyikan adalah cara paling
        // mudah membuat orang percaya semuanya sudah beres.
        setUnlinked(res.data.master_link?.unlinked_total || 0);
      }
    } catch { toast({ title: 'Gagal memuat rencana peluncuran', variant: 'destructive' }); }
    finally { setLoading(false); }
  }, [page, filterStatus, filterPlatform, filterAccountId, search, authH, toast]);

  useEffect(() => { fetchSummary(); }, [fetchSummary]);
  useEffect(() => { fetchItems();   }, [fetchItems]);

  const openCreate = () => { setEditTarget(null); setForm(EMPTY_FORM); setGalatForm(''); setShowForm(true); };
  const openEdit   = (item) => {
    setEditTarget(item);
    setForm({
      account_id: item.account_id || '',
      // Dokumen WARISAN tidak punya `model_id`. Formnya sengaja terbuka dengan
      // pemilih KOSONG + peringatan, bukan diisi tebakan dari nama lamanya —
      // menebak akan menautkan rencana ke produk yang salah dan itu lebih
      // berbahaya daripada tautan yang jujur-jujur belum ada.
      model_id: item.model_id || '',
      master: item.model_id ? {
        model_id: item.model_id, code: item.model_code || item.model || '',
        name: item.product_name || '', category_name: item.category_name || '',
        hpp: item.hpp_master || 0, retail_price_master: item.retail_price_master || 0,
      } : null,
      legacy_name: item.model_id ? '' : (item.product_name || ''),
      launch_date: item.launch_date || '',
      original_price: item.original_price ?? '', flash_sale_price: item.flash_sale_price ?? '',
      cross_price: item.cross_price ?? '', listing_price: item.listing_price ?? '',
      platforms: item.platforms || [], description: item.description || '',
      status: item.status || 'planning', launch_notes: item.launch_notes || ''
    });
    setGalatForm('');
    setShowForm(true);
  };

  const togglePlatform = (p) => {
    setForm(f => ({
      ...f, platforms: f.platforms.includes(p)
        ? f.platforms.filter(x => x !== p)
        : [...f.platforms, p]
    }));
  };

  const handleSave = async () => {
    // F14b — produk WAJIB dari master. Pesannya menyebut jalan keluarnya, bukan
    // hanya melarang: staf yang produknya belum terdaftar harus tahu ke mana.
    if (!form.model_id) {
      setGalatForm('Pilih produk dari Master Produk. Kalau produknya belum ada, daftarkan dulu di Master Produk.');
      return;
    }
    if (!form.launch_date) {
      setGalatForm('Isi tanggal peluncuran.'); return;
    }
    if (!form.account_id) {
      // F14 — peluncuran tanpa toko tidak akan pernah muncul di layar yang
      // difilter per toko, dan backend menolaknya (400).
      setGalatForm('Pilih toko dulu — rencana peluncuran harus menempel pada satu toko.'); return;
    }
    setGalatForm('');
    setFormLoading(true);
    try {
      const payload = {
        account_id:        form.account_id,
        model_id:          form.model_id,
        launch_date:       form.launch_date,
        platforms:         form.platforms,
        description:       form.description,
        status:            form.status,
        launch_notes:      form.launch_notes,
        original_price:    parseFloat(form.original_price)    || 0,
        flash_sale_price:  parseFloat(form.flash_sale_price)  || 0,
        cross_price:       parseFloat(form.cross_price)       || 0,
        listing_price:     parseFloat(form.listing_price)     || 0,
      };
      if (editTarget) {
        await axios.put(`${API}/api/marketing/product-launches/${editTarget.id}`, payload, { headers: authH });
        toast({ title: 'Rencana peluncuran disimpan.' });
      } else {
        await axios.post(`${API}/api/marketing/product-launches`, payload, { headers: authH });
        toast({ title: 'Rencana peluncuran ditambahkan.' });
      }
      setShowForm(false);
      fetchSummary();
      fetchItems();
    } catch (e) {
      // Alasan penolakan server (mis. produk sudah tidak aktif di master) harus
      // sampai ke staf — "Gagal menyimpan" saja membuat orang menebak.
      setGalatForm(e?.response?.data?.detail || e?.message || 'Gagal menyimpan.');
    }
    finally { setFormLoading(false); }
  };

  const handleDelete = async (id) => {
    if (!(await confirmDialog({ title: 'Hapus rencana peluncuran ini?', body: 'Rencana dihapus dari daftar.', confirmLabel: 'Hapus', danger: true }))) return;
    setDetail(null);
    try {
      await axios.delete(`${API}/api/marketing/product-launches/${id}`, { headers: authH });
      toast({ title: 'Rencana peluncuran dihapus.' });
      fetchSummary();
      fetchItems();
    } catch { toast({ title: 'Gagal menghapus', variant: 'destructive' }); }
  };

  const handleStatusChange = async (id, newStatus) => {
    try {
      await axios.post(`${API}/api/marketing/product-launches/${id}/status`, { status: newStatus }, { headers: authH });
      toast({ title: `Status diubah: ${STATUS_CONFIG[newStatus]?.label}` });
      fetchSummary();
      fetchItems();
    } catch { toast({ title: 'Gagal mengubah status', variant: 'destructive' }); }
  };

  // Urut tanggal peluncuran untuk linimasa
  const sortedItems = [...items].sort((a, b) => a.launch_date?.localeCompare(b.launch_date) || 0);
  const paramSaring = () => {
    const params = {};
    if (filterStatus)   params.status   = filterStatus;
    if (filterPlatform) params.platform = filterPlatform;
    if (filterAccountId) params.account_id = filterAccountId;
    if (search)         params.search   = search;
    return params;
  };
  /** Unduh semua rencana hasil saringan (dulu hanya 20 baris halaman ini). */
  const ambilSemua = async () => {
    const semua = [];
    for (let p = 1; p <= 200; p += 1) {
      const res = await axios.get(`${API}/api/marketing/product-launches`, { params: { page: p, page_size: 100, ...paramSaring() }, headers: authH });
      semua.push(...(res.data.data || []));
      if (p >= (res.data.pagination?.total_pages || 1)) break;
    }
    return semua;
  };
  const adaSaring = !!(filterStatus || filterPlatform || filterAccountId || search);
  const labelTertaut = (item) => (item.master_linked
    ? <span className="tabular-nums text-xs text-muted-foreground" data-testid={`launch-code-${item.id}`}>{item.model_code || item.model}</span>
    : <span title="Rencana ini belum tertaut Master Produk — buka Ubah lalu pilih produknya." data-testid={`launch-unlinked-${item.id}`}>
        <StatusBadge status="belum-tertaut" label="Belum tertaut" tone="warning" />
      </span>);
  const hargaRingkas = (item) => (
    <span className="tabular-nums md:whitespace-nowrap">
      {item.listing_price > 0 ? <span className="font-medium">{fmtRp(item.listing_price)}</span> : <span className="text-muted-foreground">—</span>}
      {item.flash_sale_price > 0 && item.flash_sale_price !== item.listing_price && (
        <span className="block text-xs text-muted-foreground">Flash sale {fmtRp(item.flash_sale_price)}</span>)}
      {item.cross_price > 0 && <span className="block text-xs text-muted-foreground line-through">{fmtRp(item.cross_price)}</span>}
    </span>);
  const pilihStatus = (item) => (
    <SmartNativeSelect value={item.status} onChange={(e) => handleStatusChange(item.id, e.target.value)} className="w-40"
      searchable={false} data-testid={`launch-status-${item.id}`}>
      {Object.entries(STATUS_CONFIG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
    </SmartNativeSelect>);

  const kolom = [
    { kunci: 'produk', label: 'Produk', hp: 'judul', isi: (item) => (
      <div className="min-w-0 md:max-w-[15rem]"><p className="truncate font-medium" title={item.product_name}>{item.product_name}</p>
        <div className="mt-0.5">{labelTertaut(item)}</div></div>) },
    { kunci: 'bahan', label: 'Bahan / kategori', isi: (item) => (
      <span className="text-sm">{item.material || <span className="text-muted-foreground">—</span>}
        <span className="block text-xs text-muted-foreground">{item.category_name || ''}</span></span>) },
    { kunci: 'tanggal', label: 'Tanggal peluncuran', hp: 'keterangan', isi: (item) => <span className="tabular-nums md:whitespace-nowrap">{tgl(item.launch_date)}</span> },
    { kunci: 'harga', label: 'Harga', rata: 'kanan', isi: hargaRingkas },
    { kunci: 'platform', label: 'Platform', isi: (item) => <span className="text-sm">{(item.platforms || []).map(labelPlatform).join(', ') || '—'}</span> },
    { kunci: 'status', label: 'Status', hp: 'aksi', isi: pilihStatus },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (item) => (
      <Button size="icon-sm" variant="ghost" onClick={() => openEdit(item)} title="Ubah rencana" aria-label="Ubah rencana"><Pencil /></Button>) },
  ];

  return (
    <PageLayout testId="product-launch-dashboard" title="Peluncuran produk"
      subtitle="Rencana peluncuran produk dari Master Produk: tanggal, harga, dan platform."
      actions={<Button onClick={openCreate} data-testid="btn-add-launch"><Plus />Tambah rencana</Button>}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="pl-8" placeholder="Cari produk" value={search}
            onChange={e => { setSearch(e.target.value); setPage(1); }} data-testid="launch-search" />
        </div>
        <MarketingAccountSelect token={token} value={filterAccountId} className="w-56"
          onChange={(v) => { setFilterAccountId(v); setPage(1); }} label=""
          includeAll allLabel="Semua toko" required={false} testId="launch-filter-account" />
        <SmartNativeSelect value={filterStatus} onChange={(e) => { setFilterStatus(e.target.value); setPage(1); }} className="w-44" searchable={false}>
          <option value="">Semua status</option>
          {Object.entries(STATUS_CONFIG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={filterPlatform} onChange={(e) => { setFilterPlatform(e.target.value); setPage(1); }} className="w-40" searchable={false}>
          <option value="">Semua platform</option>
          {PLATFORMS.map(p => <option key={p} value={p}>{labelPlatform(p)}</option>)}
        </SmartNativeSelect>
      </>}
      tools={<>
        <ViewToggle value={viewMode} onChange={setViewMode} options={VIEWS} testId="launch-view" />
        <TombolUnduh namaBerkas="peluncuran-produk" namaLembar="Peluncuran" baris={items} ambilSemua={ambilSemua} testId="launch-export-csv"
          kolom={[
            { label: 'Kode master', nilai: (it) => it.model_code || it.model || '' },
            { label: 'Produk', nilai: (it) => it.product_name },
            { label: 'Kategori', nilai: (it) => it.category_name || '' },
            { label: 'Bahan', nilai: (it) => it.material || '' },
            { label: 'Tanggal peluncuran', nilai: (it) => tgl(it.launch_date) },
            { label: 'Harga listing', nilai: (it) => Number(it.listing_price) || 0 },
            { label: 'Harga coret', nilai: (it) => Number(it.cross_price) || 0 },
            { label: 'Harga flash sale', nilai: (it) => Number(it.flash_sale_price) || 0 },
            { label: 'Harga resmi master', nilai: (it) => (it.retail_price_master ?? '') },
            { label: 'Platform', nilai: (it) => (it.platforms || []).map(labelPlatform).join(', ') },
            { label: 'Status', nilai: (it) => STATUS_CONFIG[it.status]?.label || it.status || '' },
            { label: 'Tertaut master', nilai: (it) => (it.master_linked ? 'Ya' : 'Belum') },
          ]} />
        <Button variant="outline" size="icon" onClick={() => { fetchSummary(); fetchItems(); }} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={<>
        {(summary?.total || 0) > 0 && (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="launch-kpi">
            <StatTile label="Total rencana" value={fmt(summary?.total)}
              sub={`${fmt(summary?.planning)} perencanaan · ${fmt(summary?.postponed)} ditunda`} hint="Semua toko; tidak ikut penyaring." />
            <StatTile label="Siap diluncurkan" value={fmt(summary?.ready)} accent="primary" hint="Rencana berstatus siap diluncurkan." />
            <StatTile label="Sudah diluncurkan" value={fmt(summary?.launched)} accent="success" hint="Produk yang sudah di pasar." />
            <StatTile label="Dalam 30 hari" value={fmt(summary?.upcoming_30)} accent="warning" hint="Tanggal peluncuran dalam 30 hari ke depan." />
          </div>
        )}
        {/* F14b — WARISAN DIAKUI, BUKAN DISEMBUNYIKAN. */}
        {unlinked > 0 && (
          <Notice tone="warning" icon={AlertTriangle} testId="launch-unlinked-banner"
            title={`${unlinked} rencana peluncuran belum tertaut Master Produk`}>
            Dibuat sebelum aturan "produk wajib dari master", jadi namanya masih teks bebas. Buka Ubah pada baris bertanda
            "Belum tertaut" lalu pilih produknya — supaya stok, HPP, dan harga resminya punya satu sumber.
          </Notice>
        )}
      </>}
      footer={viewMode === 'table' && pagination && pagination.total_pages > 1 && (
        <PaginationLite page={page} totalPages={pagination.total_pages} total={pagination.total} pageSize={20} onPageChange={setPage} />
      )}>
      {loading && items.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat rencana peluncuran…</p>
      ) : items.length === 0 ? (
        <EmptyState title={adaSaring ? 'Tidak ada rencana yang cocok' : 'Belum ada rencana peluncuran'}
          description={adaSaring ? 'Ubah saringan atau kata pencarian.' : 'Tambahkan rencana peluncuran produk dari Master Produk.'}
          action={!adaSaring && <Button onClick={openCreate}><Plus />Tambah rencana</Button>} />
      ) : viewMode === 'table' ? (
        <TabelData kolom={kolom} baris={items} onKlikBaris={setDetail} testId="launch-table" />
      ) : (
        /* Linimasa ringkas: satu baris per rencana, urut tanggal (dulu kartu besar per produk). */
        <ol className="space-y-0 border-l-2 border-[var(--glass-border)] pl-4" data-testid="launch-timeline">
          {sortedItems.map(item => {
            const today = todayWIB();
            const isToday = item.launch_date === today;
            return (
              <li key={item.id} className="relative cursor-pointer py-2" onClick={() => setDetail(item)}>
                <span className={cn('absolute -left-[1.3rem] top-3.5 h-2.5 w-2.5 rounded-full border-2 border-background',
                  item.status === 'launched' ? 'bg-[hsl(var(--success))]' : item.status === 'cancelled' ? 'bg-[hsl(var(--destructive))]'
                    : isToday ? 'bg-primary' : 'bg-muted-foreground/50')} />
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="w-28 shrink-0 text-sm tabular-nums text-muted-foreground">{tgl(item.launch_date)}</span>
                  <span className="min-w-0 flex-1 truncate text-sm font-medium">{item.product_name}</span>
                  <span className="text-sm text-muted-foreground">{(item.platforms || []).map(labelPlatform).join(', ')}</span>
                  {item.listing_price > 0 && <span className="text-sm tabular-nums">{fmtRp(item.listing_price)}</span>}
                  <StatusPeluncuran status={item.status} />
                </div>
              </li>
            );
          })}
        </ol>
      )}

      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} judul={detail.product_name} testId="launch-detail"
          status={<StatusPeluncuran status={detail.status} />}
          keterangan={`Peluncuran ${tgl(detail.launch_date)}`}
          aksi={<>
            <Button size="sm" variant="outline" onClick={() => { const it = detail; setDetail(null); openEdit(it); }}><Pencil />Ubah</Button>
            <Button size="sm" variant="destructive" onClick={() => handleDelete(detail.id)}><Trash2 />Hapus</Button>
          </>}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Kode master">{labelTertaut(detail)}</BarisDetail>
            <BarisDetail label="Bahan / kategori">{[detail.material, detail.category_name].filter(Boolean).join(' · ') || '—'}</BarisDetail>
            <BarisDetail label="Harga listing">{fmtRp(detail.listing_price)}</BarisDetail>
            <BarisDetail label="Harga flash sale">{fmtRp(detail.flash_sale_price)}</BarisDetail>
            <BarisDetail label="Harga coret">{fmtRp(detail.cross_price)}</BarisDetail>
            <BarisDetail label="Harga resmi master">{fmtRp(detail.retail_price_master)}</BarisDetail>
            <BarisDetail label="Platform">{(detail.platforms || []).map(labelPlatform).join(', ') || '—'}</BarisDetail>
            {detail.description && <BarisDetail label="Deskripsi">{detail.description}</BarisDetail>}
            {detail.launch_notes && <BarisDetail label="Catatan peluncuran">{detail.launch_notes}</BarisDetail>}
          </dl>
          <div className="flex flex-wrap items-center gap-2 border-t border-[var(--glass-border)] pt-3">
            <span className="text-sm text-muted-foreground">Ubah status:</span>
            {pilihStatus(detail)}
          </div>
        </DetailPopup>
      )}

      <FormPopup open={showForm} onClose={() => setShowForm(false)} ukuran="panjang" onSimpan={handleSave} menyimpan={formLoading}
        judul={editTarget ? 'Ubah rencana peluncuran' : 'Tambah rencana peluncuran'} galat={galatForm} testId="launch-form"
        labelSimpan={editTarget ? 'Simpan perubahan' : 'Tambah rencana'}>
        <MarketingAccountSelect token={token} value={form.account_id}
          onChange={(v) => setForm(f => ({ ...f, account_id: v }))} testId="launch-account-select" />
        {/* F14b — SATU pemilih, bukan tiga kotak ketik. Nama, kode, kategori, HPP, dan harga resmi mengikuti master. */}
        <MasterProductSelect
          token={token}
          value={form.model_id}
          testId="launch-product-select"
          onChange={(m) => setForm(f => ({
            ...f,
            model_id: m?.model_id || '',
            master: m || null,
            // Harga BOLEH beda dari master (K-3a), tetapi titik berangkatnya harga RESMI.
            original_price: f.original_price !== '' && f.original_price != null
              ? f.original_price : (m?.retail_price_master ?? ''),
          }))}
          helpText="Daftar ini sama persis dengan daftar di layar Katalog dari Master — satu sumber."
        />
        {/* Dokumen WARISAN: katakan apa adanya, jangan ditebak. */}
        {editTarget && !form.model_id && (
          <Notice tone="warning" icon={AlertTriangle} title="Belum tertaut Master Produk" testId="launch-legacy-warning">
            Rencana ini dibuat sebelum aturan "produk wajib dari master", isinya teks bebas
            {form.legacy_name ? ` — "${form.legacy_name}"` : ''}. Pilih produknya di atas untuk menautkannya.
          </Notice>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Tanggal peluncuran" wajib>
            <DatePicker value={form.launch_date || ''} onChange={(v) => setForm(f => ({...f, launch_date: v}))} testId="launch-date" />
          </Isian>
          <Isian label="Status" htmlFor="launch-status-form">
            <SmartNativeSelect id="launch-status-form" value={form.status} searchable={false} onChange={(e) => setForm(f => ({...f, status: e.target.value}))}>
              {Object.entries(STATUS_CONFIG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </SmartNativeSelect>
          </Isian>
          {/* F14b — Bahan & Model milik master (hanya dibaca). */}
          <Isian label="Bahan (dari master)">
            <p className="flex h-9 items-center text-sm" data-testid="launch-material-readonly">
              {form.master?.material || form.master
                ? (form.master?.material || <span className="text-muted-foreground">Belum dicatat di Master Produk</span>)
                : <span className="text-muted-foreground">Pilih produk dulu</span>}
            </p>
          </Isian>
          <Isian label="Kode model (dari master)">
            <p className="flex h-9 items-center text-sm tabular-nums" data-testid="launch-model-readonly">
              {form.master?.code || <span className="text-muted-foreground">Pilih produk dulu</span>}
            </p>
          </Isian>
          <Isian label="Harga asli (Rp)"
            galat={form.master && Number(form.master.retail_price_master || 0) > 0 && Number(form.original_price || 0) > 0
              && Number(form.original_price) !== Number(form.master.retail_price_master)
              ? `Beda ${fmtRp(Math.abs(Number(form.original_price) - Number(form.master.retail_price_master)))} dari harga resmi master (${fmtRp(form.master.retail_price_master)}).`
              : undefined}>
            <MoneyInput value={form.original_price} onChange={e => setForm(f => ({...f, original_price: e.target.value}))}
              placeholder="0" data-testid="launch-original-price" />
          </Isian>
          <Isian label="Harga pasang / listing (Rp)">
            <MoneyInput value={form.listing_price} onChange={e => setForm(f => ({...f, listing_price: e.target.value}))} placeholder="0" />
          </Isian>
          <Isian label="Harga flash sale (Rp)">
            <MoneyInput value={form.flash_sale_price} onChange={e => setForm(f => ({...f, flash_sale_price: e.target.value}))} placeholder="0" />
          </Isian>
          <Isian label="Harga coret (Rp)">
            <MoneyInput value={form.cross_price} onChange={e => setForm(f => ({...f, cross_price: e.target.value}))} placeholder="0" />
          </Isian>
        </div>
        <Isian label="Platform tujuan">
          <div className="flex flex-wrap gap-1.5">
            {PLATFORMS.map(p => {
              const aktif = form.platforms.includes(p);
              return (
                <Button key={p} type="button" size="sm" variant={aktif ? 'default' : 'outline'} aria-pressed={aktif}
                  onClick={() => togglePlatform(p)}>{labelPlatform(p)}</Button>
              );
            })}
          </div>
        </Isian>
        <Isian label="Deskripsi" htmlFor="launch-desc">
          <Textarea id="launch-desc" value={form.description} rows={2} placeholder="Rincian produk"
            onChange={e => setForm(f => ({...f, description: e.target.value}))} />
        </Isian>
        <Isian label="Catatan peluncuran" htmlFor="launch-notes">
          <Textarea id="launch-notes" value={form.launch_notes} rows={2} placeholder="Persiapan, daftar periksa, dll."
            onChange={e => setForm(f => ({...f, launch_notes: e.target.value}))} />
        </Isian>
      </FormPopup>
    </PageLayout>
  );
}

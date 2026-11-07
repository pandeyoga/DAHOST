/**
 * CatalogManagementModule — Manajemen Katalog (Portal Marketing).
 * Katalog per toko + isi item + stok jual.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, daftar katalog = tabel (dulu kartu berulang),
 * semua form = FormPopup, tabel bisa diunduh Excel/CSV, warna token, bahasa Indonesia.
 *
 * Perbaikan angka (keluhan owner): kolom stok per katalog dulu memakai `low_stock_count/out_of_stock_count`
 * TERSIMPAN (cache basi) → kartu "100% sehat" padahal 640 item stok habis. Kini angkanya dari
 * `/stock-dashboard` → `catalog_breakdown` (dihitung langsung, stok jual LIVE, item aktif), sumber yang sama
 * dengan kartu ringkasan di atas — tabel dan kartu tidak bisa lagi berbeda.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import {
  Plus, RefreshCw, Search, Pencil, Trash2, MoreHorizontal, Eye, Layers, Loader2, ArrowRightLeft, Coins, Link2,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { formatDateTimeID } from '@/lib/format';
import { parseServerTime } from '@/lib/waktu';
import { toast } from 'sonner';
import { FGProductPickerDialog } from './FGProductPickerDialog';
// 2026-08-12 — "Isi dari Master Produk" (banyak toko sekaligus) hidup sebagai TAB di
// sini, bukan sebagai pintu menu terpisah: staf yang membuka Manajemen Katalog dan
// menemukan katalog kosong harus bisa mengisinya DI TEMPAT, bukan mencari menu lain.
import CatalogFromMasterModule from './marketing/CatalogFromMasterModule';
import CatalogItemsView from './marketing/CatalogItemsView';
import PageLayout, { Toolbar } from './layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from './moduleAtoms';
import { readField, FIELD } from '@/lib/materialFields';  // FASE 6.6-B

const API = process.env.REACT_APP_BACKEND_URL;
const cat = (path, opts = {}) => fetch(`${API}/api/marketing/catalogs${path}`, opts);

// Nama platform untuk layar (data menyimpan kode huruf kecil: shopee, tiktok, …)
const PLATFORM_LABEL = {
  shopee: 'Shopee', tiktok: 'TikTok', 'tiktok shop': 'TikTok Shop', tokopedia: 'Tokopedia', lazada: 'Lazada',
  blibli: 'Blibli', instagram: 'Instagram', website: 'Website', other: 'Lainnya', lainnya: 'Lainnya',
};
export const labelPlatform = (p) => PLATFORM_LABEL[String(p || '').toLowerCase()] || p || '—';

// Status stok jual (dihitung server dari stok live)
export const STOK = {
  in_stock: { label: 'Tersedia', tone: 'success' },
  low_stock: { label: 'Stok menipis', tone: 'warning' },
  out_of_stock: { label: 'Stok habis', tone: 'danger' },
  unlinked: { label: 'Belum tertaut', tone: 'muted' },
};

const TAB_KEYS = ['catalogs', 'items', 'stock', 'history', 'from-master'];
const TAB_LIST_CLASS = 'h-auto max-w-full justify-start gap-1 max-sm:flex-nowrap max-sm:overflow-x-auto sm:flex-wrap';
const jam = (v) => formatDateTimeID(parseServerTime(v));
const angka = (n) => Number(n || 0).toLocaleString('id-ID');
const persen = (a, b) => (b ? `${(Math.round((a / b) * 1000) / 10).toLocaleString('id-ID')}%` : '—');

// ─── Main Component ───────────────────────────────────────────────────────────

export default function CatalogManagementModule({ token, moduleId, initialTab }) {
  const headers = useMemo(
    () => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }),
    [token]
  );

  // Tab awal: deep-link `marketing-catalog-from-master` mendarat di tab "Isi dari
  // Master". Dipilih dari `moduleId` (dikirim App.js) — BUKAN dari sessionStorage
  // yang harus ditulis modul lain lebih dulu; urutan mount itu terbukti tidak bisa
  // diandalkan dan membuat deep-link mendarat di tab pertama.
  const [tab, setTab] = useState(() => {
    if (initialTab && TAB_KEYS.includes(initialTab)) return initialTab;
    if (moduleId === 'marketing-catalog-from-master') return 'from-master';
    try {
      const saved = sessionStorage.getItem('hub_tab_marketing-catalog');
      if (saved && TAB_KEYS.includes(saved)) {
        sessionStorage.removeItem('hub_tab_marketing-catalog');
        return saved;
      }
    } catch (e) { /* sessionStorage tidak tersedia */ }
    return 'catalogs';
  });
  const [accounts, setAccounts] = useState([]);
  const [catalogs, setCatalogs] = useState([]);
  const [selectedCatalog, setSelectedCatalog] = useState(null);
  const [items, setItems] = useState([]);
  const [dashboard, setDashboard] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searchQ, setSearchQ] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [filterAccount, setFilterAccount] = useState('');

  // Dialogs
  const [catalogDialog, setCatalogDialog] = useState(null);
  const [itemDialog, setItemDialog] = useState(null);
  const [stockDialog, setStockDialog] = useState(null);
  const [bulkStockDialog, setBulkStockDialog] = useState(false);
  const [bulkStockData, setBulkStockData] = useState({});

  const [syncing, setSyncing] = useState(false);
  const [refreshingHpp, setRefreshingHpp] = useState(false);
  const [refreshingMaster, setRefreshingMaster] = useState(false);
  // F6 — kategori dari MASTER (bukan teks bebas). Dipakai filter + form item.
  const [productCategories, setProductCategories] = useState([]);
  const [filterCategoryId, setFilterCategoryId] = useState('');
  // F11 — "Perlu Perhatian": saring item bermasalah (belum tertaut master / stok
  // basi). WAJIB dikerjakan server: item bermasalah bisa ada di halaman ke-2.
  const [filterAttention, setFilterAttention] = useState('');
  const [stockSummary, setStockSummary] = useState({ stale: 0, unlinked: 0, attention: 0 });
  // F4 — saringan penayangan/status/foto/urutan. SEMUA dikerjakan SERVER: statusnya
  // turunan (dihitung dari publish_state + stok jual), jadi menyaringnya di layar
  // hanya akan benar untuk baris yang kebetulan sedang tampil.
  const [f4, setF4] = useState({
    catalogStatus: [], publishState: '', hasPhoto: '', sort: 'name', order: 'asc',
  });
  const [statusOptions, setStatusOptions] = useState([]);

  // ── Load functions ────────────────────────────────────────────────

  const loadProductCategories = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/rahaza/product-categories`, { headers });
      const d = await r.json();
      setProductCategories(d.categories || []);
    } catch (e) { console.error(e); }
  }, [headers]);

  const loadAccounts = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/marketing/accounts?status=active`, { headers });
      const d = await r.json();
      // /api/marketing/accounts mengembalikan daftar langsung (dulu dibaca `d.accounts` → pilihan toko selalu kosong)
      setAccounts(Array.isArray(d) ? d : (d.accounts || []));
    } catch (e) { console.error(e); }
  }, [headers]);

  const loadCatalogs = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filterAccount) params.set('account_id', filterAccount);
      const r = await cat(`?${params}`, { headers });
      const d = await r.json();
      setCatalogs(d.catalogs || []);
    } catch (e) { toast.error('Gagal memuat katalog'); }
    finally { setLoading(false); }
  }, [headers, filterAccount]);

  const loadItems = useCallback(async (cid, search = '', status = '', categoryId = '',
                                       attention = '', f4opts = null) => {
    if (!cid) return;
    try {
      const params = new URLSearchParams();
      if (search) params.set('search', search);
      if (status) params.set('status', status);
      if (categoryId) params.set('category_id', categoryId);
      // F11 — filter item bermasalah dikerjakan SERVER supaya bekerja lintas halaman
      if (attention) params.set('attention', attention);
      // F4 — status penayangan / foto / urutan juga dikerjakan server
      const o = f4opts || {};
      if ((o.catalogStatus || []).length) params.set('catalog_status', o.catalogStatus.join(','));
      if (o.publishState) params.set('publish_state', o.publishState);
      if (o.hasPhoto) params.set('has_photo', o.hasPhoto);
      if (o.sort) params.set('sort', o.sort);
      if (o.order) params.set('order', o.order);
      // Ambil cukup banyak baris supaya paginasi di layar tidak memotong
      // katalog besar (bawaan server 100 dulu menyembunyikan item ke-101 dst.)
      params.set('limit', '500');
      const r = await cat(`/${cid}/items?${params}`, { headers });
      const d = await r.json();
      if (!r.ok) { toast.error(d.detail || 'Gagal memuat item katalog'); return; }
      setItems(d.items || []);
      setStatusOptions(d.status_options || []);
      setStockSummary(d.stock_summary || { stale: 0, unlinked: 0, attention: 0 });
    } catch (e) { console.error(e); }
  }, [headers]);

  const loadDashboard = useCallback(async () => {
    try {
      const r = await cat('/stock-dashboard', { headers });
      const d = await r.json();
      setDashboard(d);
    } catch (e) { console.error(e); }
  }, [headers]);

  const loadHistory = useCallback(async (cid) => {
    if (!cid) return;
    try {
      const r = await cat(`/${cid}/stock-history?limit=30`, { headers });
      const d = await r.json();
      setHistory(d.history || []);
    } catch (e) { console.error(e); }
  }, [headers]);

  useEffect(() => {
    loadAccounts();
    loadDashboard();
    loadProductCategories();
  }, [loadAccounts, loadDashboard, loadProductCategories]);

  useEffect(() => {
    if (tab === 'catalogs' || tab === 'items' || tab === 'history') loadCatalogs();
    if (tab === 'stock') loadDashboard();
  }, [tab, loadCatalogs, loadDashboard]);

  useEffect(() => {
    if (selectedCatalog) {
      loadItems(selectedCatalog.id, searchQ, filterStatus, filterCategoryId, filterAttention, f4);
      if (tab === 'history') loadHistory(selectedCatalog.id);
    }
  }, [selectedCatalog, searchQ, filterStatus, filterCategoryId, filterAttention, f4,
      tab, loadItems, loadHistory]);

  const reloadItems = () => {
    if (!selectedCatalog) return;
    loadItems(selectedCatalog.id, searchQ, filterStatus, filterCategoryId, filterAttention, f4);
  };
  const reloadCatalogs = () => { loadCatalogs(); loadDashboard(); };

  // ── Handlers ─────────────────────────────────────────────────────

  const handleSaveCatalog = async (form) => {
    const isEdit = !!form.id;
    const r = await cat(
      isEdit ? `/${form.id}` : '',
      { method: isEdit ? 'PUT' : 'POST', headers, body: JSON.stringify(form) }
    );
    const d = await r.json();
    if (!r.ok) { throw new Error(d.detail || 'Gagal menyimpan katalog'); }
    toast.success(isEdit ? 'Katalog disimpan' : 'Katalog dibuat');
    setCatalogDialog(null);
    reloadCatalogs();
  };

  const handleDeleteCatalog = async (catalog) => {
    const ok = await confirmDialog({
      title: `Hapus katalog "${catalog.name}"?`,
      body: 'Katalog dan semua itemnya dihapus.',
      confirmLabel: 'Hapus', danger: true,
    });
    if (!ok) return;
    const r = await cat(`/${catalog.id}`, { method: 'DELETE', headers });
    const d = await r.json();
    if (!r.ok) { toast.error(d.detail || 'Gagal menghapus katalog'); return; }
    toast.success(d.message || 'Katalog dihapus');
    if (selectedCatalog?.id === catalog.id) setSelectedCatalog(null);
    reloadCatalogs();
  };

  const handleSaveItem = async (form) => {
    if (!selectedCatalog) return;
    const isEdit = !!form.id;

    // Two-mode payload: from-fg vs manual
    if (!isEdit && form._mode === 'from_fg' && form.fg_material_id) {
      // Create from FG master
      const payload = {
        fg_material_id: form.fg_material_id,
        price: parseFloat(form.harga_jual ?? form.price) || 0,
        original_price: parseFloat(form.harga_coret ?? form.original_price) || 0,
        platform_price: parseFloat(form.platform_price) || 0,
        harga_jual: parseFloat(form.harga_jual ?? form.price) || 0,
        harga_coret: parseFloat(form.harga_coret ?? form.original_price) || 0,
        harga_original: parseFloat(form.harga_original) || 0,
        platform_url: form.platform_url || '',
        stock_alert_threshold: parseFloat(form.stock_alert_threshold) || 10,
        tags: form.tags ? form.tags.split(',').map(t => t.trim()).filter(Boolean) : [],
        description_override: form.description || '',
      };
      const r = await cat(`/${selectedCatalog.id}/items/from-fg`, {
        method: 'POST', headers, body: JSON.stringify(payload),
      });
      const d = await r.json();
      if (!r.ok) { throw new Error(d.detail || 'Gagal menyimpan item dari FG'); }
      toast.success(d.message || 'Item ditambahkan dari FG');
    } else {
      // Manual entry (edit existing or new manual)
      const payload = {
        ...form,
        tags: typeof form.tags === 'string'
          ? form.tags.split(',').map(t => t.trim()).filter(Boolean)
          : (form.tags || []),
        price: parseFloat(form.harga_jual ?? form.price) || 0,
        original_price: parseFloat(form.harga_coret ?? form.original_price) || 0,
        platform_price: parseFloat(form.platform_price) || 0,
        harga_jual: parseFloat(form.harga_jual ?? form.price) || 0,
        harga_coret: parseFloat(form.harga_coret ?? form.original_price) || 0,
        harga_original: parseFloat(form.harga_original) || 0,
        stock_quantity: parseFloat(form.stock_quantity) || 0,
        stock_alert_threshold: parseFloat(form.stock_alert_threshold) || 10,
        weight_gram: parseFloat(form.weight_gram) || 0,
      };
      // hpp bersifat read-only (dari RnD) — jangan kirim dari form manual
      delete payload.hpp;
      delete payload._mode;
      delete payload.fg_preview;
      // ── F6/T3 — kategori TIDAK lagi dikirim sebagai teks bebas ──────────────
      // Yang dikirim `category_id` (tervalidasi), dan HANYA untuk item yang belum tertaut
      // master — item tertaut kategorinya milik Master Produk (server balas 400 kalau dipaksa).
      const _linkedToMaster = !!(form.fg_material_id || form.material_id || form.variant_id);
      delete payload.category;
      delete payload.fg_material_id;
      if (_linkedToMaster || !form.category_id) {
        delete payload.category_id;
      }
      const r = await cat(
        isEdit ? `/${selectedCatalog.id}/items/${form.id}` : `/${selectedCatalog.id}/items`,
        { method: isEdit ? 'PUT' : 'POST', headers, body: JSON.stringify(payload) }
      );
      const d = await r.json();
      if (!r.ok) { throw new Error(d.detail || 'Gagal menyimpan item'); }
      toast.success(isEdit ? 'Item disimpan' : 'Item ditambahkan');
    }
    setItemDialog(null);
    loadItems(selectedCatalog.id, searchQ, filterStatus, filterCategoryId, filterAttention);
    reloadCatalogs();
  };

  const handleDeleteItem = async (item) => {
    const ok = await confirmDialog({
      title: `Hapus item "${item.name}"?`, body: 'Item dihapus dari katalog ini.',
      confirmLabel: 'Hapus', danger: true,
    });
    if (!ok) return;
    const r = await cat(`/${selectedCatalog.id}/items/${item.id}`, { method: 'DELETE', headers });
    if (!r.ok) { toast.error('Gagal menghapus item'); return; }
    toast.success('Item dihapus');
    loadItems(selectedCatalog.id, searchQ, filterStatus, filterCategoryId, filterAttention);
    reloadCatalogs();
  };

  const handleUpdateStock = async (form) => {
    const r = await cat(`/${selectedCatalog.id}/items/${form.id}/stock`, {
      method: 'PUT', headers, body: JSON.stringify({ stock_quantity: form.stock_quantity, notes: form.notes }),
    });
    const d = await r.json();
    if (!r.ok) { throw new Error(d.detail || 'Gagal mengubah stok'); }
    toast.success(`Stok diubah: ${d.old_stock} → ${d.new_stock}`);
    setStockDialog(null);
    loadItems(selectedCatalog.id, searchQ, filterStatus, filterCategoryId, filterAttention);
    reloadCatalogs();
    loadHistory(selectedCatalog.id);
  };

  const handleBulkStockSave = async () => {
    if (!selectedCatalog) return;
    const updates = Object.entries(bulkStockData)
      .filter(([, v]) => v.qty !== '' && v.qty !== undefined)
      .map(([item_id, v]) => ({ item_id, stock_quantity: parseFloat(v.qty) || 0, notes: v.notes || '' }));
    if (!updates.length) { throw new Error('Belum ada stok baru yang diisi.'); }
    const r = await cat(`/${selectedCatalog.id}/bulk-stock-update`, {
      method: 'POST', headers, body: JSON.stringify({ updates }),
    });
    const d = await r.json();
    if (!r.ok) { throw new Error(d.detail || 'Gagal mengubah stok massal'); }
    toast.success(`${d.saved} item stok diperbarui`);
    setBulkStockDialog(false);
    setBulkStockData({});
    loadItems(selectedCatalog.id, searchQ, filterStatus, filterCategoryId, filterAttention);
    reloadCatalogs();
    loadHistory(selectedCatalog.id);
  };

  const handleWmsSync = async () => {
    if (!selectedCatalog) return;
    setSyncing(true);
    try {
      const r = await cat(`/${selectedCatalog.id}/sync-from-wms`, { method: 'POST', headers });
      const d = await r.json();
      if (!r.ok) { toast.error(d.detail || 'Gagal sinkron stok'); return; }
      toast.success(d.message);
      loadItems(selectedCatalog.id, searchQ, filterStatus, filterCategoryId, filterAttention);
      reloadCatalogs();
    } finally { setSyncing(false); }
  };

  // Tarik-ulang HPP dari RnD (Model/FG) — SEMUA item katalog (massal)
  const handleRefreshHppBulk = async () => {
    if (!selectedCatalog) return;
    setRefreshingHpp(true);
    try {
      const r = await cat(`/${selectedCatalog.id}/refresh-hpp`, { method: 'POST', headers });
      const d = await r.json();
      if (!r.ok) { toast.error(d.detail || 'Gagal menarik ulang HPP'); return; }
      const skipped = d.skipped_no_source || 0;
      toast.success(
        `HPP diperbarui: ${d.updated} item${skipped ? ` · ${skipped} item tanpa sumber RnD dilewati` : ''}`
      );
      loadItems(selectedCatalog.id, searchQ, filterStatus, filterCategoryId, filterAttention);
    } catch (e) {
      toast.error('Gagal menarik ulang HPP');
    } finally { setRefreshingHpp(false); }
  };

  // F8/M7 — Segarkan field TAMPILAN item katalog dari MASTER (nama, kategori,
  // berat, info varian, HPP, harga resmi) + stoknya.
  const handleRefreshFromMaster = async () => {
    if (!selectedCatalog) return;
    setRefreshingMaster(true);
    try {
      const r = await cat(`/${selectedCatalog.id}/refresh-from-master`, { method: 'POST', headers });
      const d = await r.json();
      if (!r.ok) { toast.error(d.detail || 'Gagal menyegarkan dari master'); return; }
      toast.success(d.message || `${d.updated} item disegarkan dari master`);
      loadItems(selectedCatalog.id, searchQ, filterStatus, filterCategoryId, filterAttention);
      reloadCatalogs();
    } catch (e) {
      toast.error('Gagal menyegarkan dari master');
    } finally { setRefreshingMaster(false); }
  };

  // ── Angka per katalog (LIVE, dari stock-dashboard → catalog_breakdown) ────────────────
  // Cadangan bila server belum mengirim `catalog_breakdown` (server lama): hitung dari daftar item tiap
  // katalog aktif — `stock_live_status` di sana memakai rumus yang SAMA (stok jual live, ambang kosong = 10).
  const [hitungCadangan, setHitungCadangan] = useState(null);
  useEffect(() => {
    if (!dashboard || dashboard.catalog_breakdown || !catalogs.length) return undefined;
    let batal = false;
    (async () => {
      const hasil = {};
      await Promise.all(catalogs.filter((c) => c.is_active !== false).map(async (c) => {
        try {
          const r = await cat(`/${c.id}/items?limit=500`, { headers });
          const d = await r.json();
          if (!r.ok) return;
          const h = { total: 0, in_stock: 0, low_stock: 0, out_of_stock: 0, unlinked: 0 };
          (d.items || []).filter((i) => i.is_active !== false).forEach((i) => {
            h.total += 1;
            const st = i.stock_live_status || 'unlinked';
            if (h[st] !== undefined) h[st] += 1;
          });
          hasil[c.id] = h;
        } catch (e) { /* katalog ini tetap "—" */ }
      }));
      if (!batal) setHitungCadangan(hasil);
    })();
    return () => { batal = true; };
  }, [dashboard, catalogs, headers]);
  const perKatalog = dashboard?.catalog_breakdown || hitungCadangan || null;
  const sm = dashboard?.summary || {};
  const adaBelumTertaut = !!sm.unlinked;
  const hitungKatalog = (c) => (perKatalog ? perKatalog[c.id] || null : null);
  const alasanKosong = (c) => (c.is_active === false
    ? 'Katalog nonaktif tidak dihitung dalam ringkasan stok'
    : 'Jumlah stok per katalog belum tersedia — muat ulang halaman');
  const pilihKatalog = (c) => { setSelectedCatalog(c); setTab('items'); };

  const Sel = ({ c, k, tone }) => {
    const h = hitungKatalog(c);
    if (!h) return <span className="text-muted-foreground" title={alasanKosong(c)}>—</span>;
    const v = h[k] || 0;
    const cls = v > 0 && tone === 'danger' ? 'text-[hsl(var(--danger-text))] font-medium'
      : v > 0 && tone === 'warning' ? 'text-[hsl(var(--warning-text))] font-medium' : '';
    return <span className={`tabular-nums ${cls}`}>{angka(v)}</span>;
  };

  const kolomKatalog = [
    { kunci: 'nama', label: 'Katalog', hp: 'judul', isi: (c) => (
      <div className="min-w-0 md:max-w-[22rem]">
        <p className="truncate font-medium text-foreground" title={c.name}>{c.name}</p>
        {c.description && <p className="hidden truncate text-xs text-muted-foreground md:block" title={c.description}>{c.description}</p>}
      </div>) },
    { kunci: 'toko', label: 'Toko', hp: 'keterangan', isi: (c) => (
      <span className="text-sm">{labelPlatform(c.platform)}{c.account_name ? ` · ${c.account_name}` : ''}</span>) },
    { kunci: 'total', label: 'Item aktif', rata: 'kanan', isi: (c) => <Sel c={c} k="total" /> },
    { kunci: 'tersedia', label: 'Tersedia', rata: 'kanan', isi: (c) => <Sel c={c} k="in_stock" /> },
    { kunci: 'menipis', label: 'Stok menipis', rata: 'kanan', isi: (c) => <Sel c={c} k="low_stock" tone="warning" /> },
    { kunci: 'habis', label: 'Stok habis', rata: 'kanan', isi: (c) => <Sel c={c} k="out_of_stock" tone="danger" /> },
    ...(adaBelumTertaut ? [{ kunci: 'unlinked', label: 'Belum tertaut', rata: 'kanan', isi: (c) => <Sel c={c} k="unlinked" /> }] : []),
    { kunci: 'status', label: 'Status', isi: (c) => (c.is_active === false
      ? <StatusBadge status="nonaktif" label="Nonaktif" tone="muted" />
      : <StatusBadge status="aktif" label="Aktif" tone="success" />) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (c) => (
      <div className="flex items-center justify-end gap-1">
        <Button size="sm" variant="outline" onClick={() => pilihKatalog(c)} data-testid={`catalog-open-${c.id}`}>
          <Eye />Lihat item
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="icon-sm" variant="ghost" aria-label="Aksi lain" title="Aksi lain" data-testid={`catalog-more-${c.id}`}>
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => setCatalogDialog(c)}><Pencil className="mr-2 h-4 w-4" />Ubah katalog</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => handleDeleteCatalog(c)} className="text-[hsl(var(--danger-text))]">
              <Trash2 className="mr-2 h-4 w-4" />Hapus katalog
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>) },
  ];

  const nilaiKatalog = (k) => (c) => { const h = hitungKatalog(c); return h ? (h[k] || 0) : ''; };
  const unduhKatalog = [
    { label: 'Katalog', nilai: (c) => c.name },
    { label: 'Deskripsi', nilai: (c) => c.description || '' },
    { label: 'Platform', nilai: (c) => labelPlatform(c.platform) },
    { label: 'Toko', nilai: (c) => c.account_name || '' },
    { label: 'Item aktif', nilai: nilaiKatalog('total') },
    { label: 'Tersedia', nilai: nilaiKatalog('in_stock') },
    { label: 'Stok menipis', nilai: nilaiKatalog('low_stock') },
    { label: 'Stok habis', nilai: nilaiKatalog('out_of_stock') },
    { label: 'Belum tertaut master', nilai: nilaiKatalog('unlinked') },
    { label: 'Status', nilai: (c) => (c.is_active === false ? 'Nonaktif' : 'Aktif') },
  ];

  const tombolMuat = (fn, sedang = false, testId) => (
    <Button variant="outline" size="icon" onClick={fn} disabled={sedang} title="Muat ulang" aria-label="Muat ulang" data-testid={testId}>
      <RefreshCw className={sedang ? 'animate-spin' : ''} />
    </Button>
  );

  const pemilihKatalog = (tab === 'items' || tab === 'history') && (
    <SmartNativeSelect className="w-full sm:w-72" value={selectedCatalog?.id || ''} placeholder="Pilih katalog"
      onChange={(e) => setSelectedCatalog(catalogs.find((c) => c.id === e.target.value) || null)}
      data-testid="catalog-picker">
      <option value="">Pilih katalog…</option>
      {catalogs.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
    </SmartNativeSelect>
  );

  // Alat satu katalog (jarang dipakai) dikumpulkan dalam satu menu supaya baris penyaring tetap satu baris.
  const alatKatalog = (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" data-testid="catalog-tools">
          {(syncing || refreshingHpp || refreshingMaster) ? <Loader2 className="animate-spin" /> : <MoreHorizontal />}
          Alat katalog
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuItem onSelect={() => setBulkStockDialog(true)} data-testid="catalog-bulk-stock">
          <ArrowRightLeft className="mr-2 h-4 w-4" />Ubah stok massal
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={handleWmsSync} disabled={syncing} data-testid="catalog-sync-wms"
          title="Sinkron stok semua item dari gudang barang jadi (lewat material & varian/SKU)">
          <RefreshCw className="mr-2 h-4 w-4" />Sinkron stok FG
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={handleRefreshHppBulk} disabled={refreshingHpp} data-testid="catalog-refresh-hpp-bulk"
          title="Tarik ulang HPP semua item dari master (R&D / HPP dasar manual)">
          <Coins className="mr-2 h-4 w-4" />Tarik ulang HPP
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={handleRefreshFromMaster} disabled={refreshingMaster} data-testid="catalog-refresh-from-master"
          title="Segarkan nama, kategori, berat, info varian, HPP & harga resmi dari Master Produk">
          <Link2 className="mr-2 h-4 w-4" />Segarkan dari master
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );

  const pageAction = tab === 'catalogs'
    ? <Button onClick={() => setCatalogDialog({})} data-testid="catalog-create-btn"><Plus />Buat katalog</Button>
    : tab === 'items' && selectedCatalog
      ? <>{alatKatalog}<Button onClick={() => setItemDialog({})} data-testid="catalog-add-item-btn"><Plus />Tambah item</Button></>
      : null;

  // ── Render ────────────────────────────────────────────────────────

  return (
    <PageLayout testId="catalog-management" title="Manajemen katalog"
      subtitle="Katalog per toko, isi itemnya, dan stok jual yang dihitung langsung dari gudang barang jadi."
      actions={pageAction}>
      <Tabs value={tab} onValueChange={setTab}>
        <div className="flex flex-wrap items-center gap-3">
          <TabsList className={TAB_LIST_CLASS}>
            <TabsTrigger value="catalogs" className="shrink-0" data-testid="catalog-tab-catalogs">Katalog</TabsTrigger>
            <TabsTrigger value="items" className="shrink-0" data-testid="catalog-tab-items">Item</TabsTrigger>
            <TabsTrigger value="from-master" className="shrink-0" data-testid="catalog-tab-from-master">Isi dari master</TabsTrigger>
            <TabsTrigger value="stock" className="shrink-0" data-testid="catalog-tab-stock">Ringkasan stok</TabsTrigger>
            <TabsTrigger value="history" className="shrink-0" data-testid="catalog-tab-history">Riwayat stok</TabsTrigger>
          </TabsList>
          {pemilihKatalog && <div className="w-full sm:ml-auto sm:w-auto">{pemilihKatalog}</div>}
        </div>

        {/* ── TAB 1: KATALOG ── */}
        <TabsContent value="catalogs" className="mt-4 space-y-4">
          <Toolbar
            filters={(
              <SmartNativeSelect className="w-full sm:w-64" value={filterAccount}
                onChange={e => setFilterAccount(e.target.value)} data-testid="catalog-filter-account">
                <option value="">Semua toko</option>
                {accounts.map(a => <option key={a.id} value={a.id}>{labelPlatform(a.platform)} — {a.account_name || a.name}</option>)}
              </SmartNativeSelect>
            )}
            tools={<>
              <TombolUnduh namaBerkas="katalog-toko" namaLembar="Katalog" baris={catalogs} kolom={unduhKatalog}
                testId="catalog-unduh" />
              {tombolMuat(reloadCatalogs, loading, 'catalog-refresh')}
            </>} />

          {dashboard && (
            // Ringkasan stok satu kalimat — sumber sama dengan kartu di tab "Ringkasan stok" (stok jual LIVE,
            // item aktif di katalog aktif yang boleh Anda lihat); item belum tertaut master = summary?.unlinked.
            <p className="text-sm text-muted-foreground" data-testid="catalog-stock-sentence">
              <b className="text-foreground">{angka(sm.total_items)}</b> item aktif di {angka(sm.catalogs)} katalog aktif ·{' '}
              <b className="text-foreground">{angka(sm.in_stock)}</b> tersedia ·{' '}
              <b className={sm.low_stock ? 'text-[hsl(var(--warning-text))]' : 'text-foreground'}>{angka(sm.low_stock)}</b> stok menipis ·{' '}
              <b className={sm.out_of_stock ? 'text-[hsl(var(--danger-text))]' : 'text-foreground'}>{angka(sm.out_of_stock)}</b> stok habis
              {dashboard.summary?.unlinked ? <> · {angka(dashboard.summary.unlinked)} belum tertaut master</> : null}
              {' '}(stok jual dihitung langsung dari gudang barang jadi).
            </p>
          )}
          {loading && catalogs.length === 0 ? (
            <p className="py-10 text-center text-sm text-muted-foreground">Memuat katalog…</p>
          ) : (
            <TabelData kolom={kolomKatalog} baris={catalogs} onKlikBaris={pilihKatalog} testId="catalog-table"
              kosong={<EmptyState icon={Layers} title={filterAccount ? 'Toko ini belum punya katalog' : 'Belum ada katalog'}
                description='Klik "Buat katalog", atau isi katalog toko lewat tab "Isi dari master".'
                action={<Button onClick={() => setCatalogDialog({})}><Plus />Buat katalog</Button>} />} />
          )}
          {perKatalog === null && dashboard && catalogs.length > 0 && (
            <p className="text-xs text-muted-foreground" data-testid="catalog-count-missing">
              Jumlah stok per katalog belum tersedia dari server — tampil "—". Angka di kartu atas tetap dihitung langsung.
            </p>
          )}
        </TabsContent>

        {/* ── TAB 2: ITEM ── */}
        <TabsContent value="items" className="mt-4 space-y-4">
          {!selectedCatalog ? (
            <EmptyState icon={Layers} title="Pilih katalog dulu"
              description="Pilih katalog di kanan atas, atau klik satu baris di tab Katalog." />
          ) : (
            <CatalogItemsView
              catalog={selectedCatalog}
              token={token}
              items={items}
              stockSummary={stockSummary}
              statusOptions={statusOptions}
              filters={f4}
              onFilterChange={(patch) => setF4((s) => ({ ...s, ...patch }))}
              baseFilters={{ search: searchQ, stock: filterStatus, category: filterCategoryId, attention: filterAttention }}
              onBaseFilter={{ search: setSearchQ, stock: setFilterStatus, category: setFilterCategoryId, attention: setFilterAttention }}
              productCategories={productCategories}
              onEdit={(it) => setItemDialog(it)}
              onDelete={(it) => handleDeleteItem(it)}
              onReload={() => { reloadItems(); reloadCatalogs(); }}
            />
          )}
        </TabsContent>

        {/* ── TAB 3: RINGKASAN STOK ── */}
        <TabsContent value="stock" className="mt-4 space-y-4">
          <StockSummaryTab dashboard={dashboard} onReload={loadDashboard} tombolMuat={tombolMuat} />
        </TabsContent>

        {/* ── TAB 4: RIWAYAT ── */}
        <TabsContent value="history" className="mt-4 space-y-4">
          {!selectedCatalog ? (
            <EmptyState icon={Layers} title="Pilih katalog dulu" description="Riwayat stok ditampilkan per katalog." />
          ) : (
            <HistoryTab catalog={selectedCatalog} history={history}
              onReload={() => loadHistory(selectedCatalog.id)} tombolMuat={tombolMuat} />
          )}
        </TabsContent>

        {/* ── TAB 5: ISI DARI MASTER PRODUK ──────────────────────────────────
            Jalur lama hanya bisa menambah SATU varian ke SATU katalog per aksi;
            untuk 9 toko × puluhan varian itu ratusan klik, dan yang benar-benar
            terjadi bukan "staf sabar" melainkan katalog dibiarkan KOSONG. */}
        <TabsContent value="from-master" className="mt-4">
          {tab === 'from-master' && (
            <CatalogFromMasterModule
              token={token}
              onAssigned={reloadCatalogs}
            />
          )}
        </TabsContent>
      </Tabs>

      {/* ── POPUP ── */}
      <CatalogDialog
        open={catalogDialog !== null}
        initial={catalogDialog || {}}
        accounts={accounts}
        onSave={handleSaveCatalog}
        onClose={() => setCatalogDialog(null)}
      />

      {itemDialog !== null && selectedCatalog && (
        <ItemDialog
          initial={itemDialog}
          catalog={selectedCatalog}
          token={token}
          productCategories={productCategories}
          onSave={handleSaveItem}
          onClose={() => setItemDialog(null)}
        />
      )}

      {stockDialog !== null && (
        <StockUpdateDialog
          item={stockDialog}
          onSave={handleUpdateStock}
          onClose={() => setStockDialog(null)}
        />
      )}

      {bulkStockDialog && selectedCatalog && (
        <BulkStockDialog
          items={items}
          data={bulkStockData}
          onChange={setBulkStockData}
          onSave={handleBulkStockSave}
          onClose={() => { setBulkStockDialog(false); setBulkStockData({}); }}
        />
      )}
    </PageLayout>
  );
}

// ─── Tab ringkasan stok ───────────────────────────────────────────────────────

function StockSummaryTab({ dashboard, onReload, tombolMuat }) {
  if (!dashboard) return <p className="py-10 text-center text-sm text-muted-foreground">Memuat ringkasan stok…</p>;
  const s = dashboard.summary || {};
  const sm = s;
  const plat = dashboard.platform_breakdown || [];
  const rendah = dashboard.low_stock_items || [];
  const totalMasalah = (s.low_stock || 0) + (s.out_of_stock || 0);
  const kolomPlatform = [
    { kunci: 'platform', label: 'Platform', hp: 'judul', isi: (p) => <span className="font-medium">{labelPlatform(p.platform)}</span> },
    { kunci: 'total', label: 'Item aktif', rata: 'kanan', isi: (p) => <span className="tabular-nums">{angka(p.total)}</span> },
    { kunci: 'in', label: 'Tersedia', rata: 'kanan', isi: (p) => <span className="tabular-nums">{angka(p.in_stock)}</span> },
    { kunci: 'low', label: 'Stok menipis', rata: 'kanan', isi: (p) => <span className="tabular-nums">{angka(p.low_stock)}</span> },
    { kunci: 'out', label: 'Stok habis', rata: 'kanan', isi: (p) => (
      <span className={`tabular-nums ${p.out_of_stock ? 'font-medium text-[hsl(var(--danger-text))]' : ''}`}>{angka(p.out_of_stock)}</span>) },
    { kunci: 'unl', label: 'Belum tertaut', rata: 'kanan', isi: (p) => <span className="tabular-nums">{angka(p.unlinked)}</span> },
    { kunci: 'pct', label: '% tersedia', rata: 'kanan', isi: (p) => <span className="tabular-nums">{persen(p.in_stock || 0, p.total || 0)}</span> },
  ];
  const kolomRendah = [
    { kunci: 'produk', label: 'Produk', hp: 'judul', isi: (i) => (
      <div className="min-w-0"><p className="truncate font-medium">{i.name}</p><p className="text-xs text-muted-foreground">{i.sku}</p></div>) },
    { kunci: 'platform', label: 'Platform', isi: (i) => labelPlatform(i.platform) },
    { kunci: 'stok', label: 'Stok jual', rata: 'kanan', isi: (i) => <span className="tabular-nums font-medium">{angka(i.stock_quantity)}</span> },
    { kunci: 'min', label: 'Batas peringatan', rata: 'kanan', isi: (i) => <span className="tabular-nums">{i.stock_alert_threshold ?? 10}</span> },
    { kunci: 'status', label: 'Status', isi: (i) => {
      const c = STOK[i.stock_status] || STOK.low_stock;
      return <StatusBadge status={i.stock_status} label={c.label} tone={c.tone} />;
    } },
  ];
  return (
    <>
      {/* Stats — 2026-11-06 (Tahap 2): dihitung server dari ISI katalog yang boleh Anda lihat, dengan stok jual LIVE;
          item yang belum tertaut master dihitung terpisah (summary?.unlinked). */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="catalog-stock-tiles">
        <StatTile label="Item aktif" value={angka(sm.total_items)}
          sub={[sm.catalogs ? `di ${sm.catalogs} katalog aktif` : null,
            s.unlinked ? `${angka(s.unlinked)} belum tertaut master` : null]
            .filter(Boolean).join(' · ') || 'Item aktif di katalog aktif'}
          testId="catalog-stock-total" />
        <StatTile label="Tersedia" value={angka(sm.in_stock)} accent="success"
          sub={`${persen(sm.in_stock || 0, sm.total_items || 0)} dari item aktif`} />
        <StatTile label="Stok menipis" value={angka(sm.low_stock)} accent="warning"
          sub="Stok jual di bawah batas peringatan" />
        <StatTile label="Stok habis" value={angka(sm.out_of_stock)} accent="danger"
          sub="Stok jual di gudang 0" testId="catalog-stock-out" />
      </div>

      <section className="space-y-2" data-testid="catalog-stock-platform">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-base font-semibold">Per platform</p>
          <div className="flex items-center gap-2">
          {dashboard.last_sync?.synced_at && <span className="text-xs text-muted-foreground">Sinkron terakhir {jam(dashboard.last_sync.synced_at)}</span>}
          {tombolMuat(onReload, false, 'catalog-stock-refresh')}
          <TombolUnduh namaBerkas="stok-katalog-per-platform" namaLembar="Per platform" baris={plat} testId="catalog-platform-unduh"
            kolom={[
              { label: 'Platform', nilai: (p) => labelPlatform(p.platform) },
              { label: 'Item aktif', nilai: (p) => p.total || 0 },
              { label: 'Tersedia', nilai: (p) => p.in_stock || 0 },
              { label: 'Stok menipis', nilai: (p) => p.low_stock || 0 },
              { label: 'Stok habis', nilai: (p) => p.out_of_stock || 0 },
              { label: 'Belum tertaut master', nilai: (p) => p.unlinked || 0 },
            ]} />
          </div>
        </div>
        <TabelData kolom={kolomPlatform} baris={plat} kunci={(p) => p.platform} testId="catalog-platform-table"
          kosong={<EmptyState title="Belum ada item aktif" description="Isi katalog lewat tab Isi dari master." />} />
      </section>

      <section className="space-y-2" data-testid="catalog-restock">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="text-base font-semibold">Perlu restock</p>
            {rendah.length > 0 && (
              <p className="text-xs text-muted-foreground">
                {rendah.length < totalMasalah
                  ? `${rendah.length} item dengan stok terendah dari ${angka(totalMasalah)} item stok menipis/habis.`
                  : `${rendah.length} item stok menipis/habis.`}
              </p>
            )}
          </div>
          <TombolUnduh namaBerkas="perlu-restock" namaLembar="Perlu restock" baris={rendah} testId="catalog-restock-unduh"
            kolom={[
              { label: 'Produk', nilai: (i) => i.name },
              { label: 'SKU', nilai: (i) => i.sku },
              { label: 'Platform', nilai: (i) => labelPlatform(i.platform) },
              { label: 'Stok jual', nilai: (i) => Number(i.stock_quantity || 0) },
              { label: 'Batas peringatan', nilai: (i) => i.stock_alert_threshold ?? 10 },
              { label: 'Status', nilai: (i) => (STOK[i.stock_status] || STOK.low_stock).label },
            ]} />
        </div>
        <TabelData kolom={kolomRendah} baris={rendah} testId="catalog-restock-table"
          kosong={<EmptyState title="Semua item stok aman" description="Tidak ada item aktif dengan stok menipis atau habis." />} />
        {/* 2026-11-06: SKU berstatus produk Stop tidak diusulkan restock — alasannya disebut */}
        {dashboard.restock_excluded?.count > 0 && (
          <p className="text-xs text-muted-foreground" data-testid="restock-excluded-stop">
            Tidak diusulkan restock: {dashboard.restock_excluded.count} item. {dashboard.restock_excluded.reason}.
            {(dashboard.restock_excluded.skus || []).length > 0 && ` SKU: ${dashboard.restock_excluded.skus.join(', ')}.`}
          </p>
        )}
      </section>
    </>
  );
}

// ─── Tab riwayat stok ─────────────────────────────────────────────────────────

const JENIS_SINKRON = {
  manual: 'Manual', manual_update: 'Ubah manual', bulk: 'Massal', bulk_update: 'Ubah massal',
  wms_sync: 'Sinkron gudang', fg_sync: 'Sinkron FG', sync: 'Sinkron', import: 'Impor', order: 'Pesanan',
};
const labelJenis = (t) => JENIS_SINKRON[t] || (t ? String(t).replace(/_/g, ' ').replace(/^\w/, (x) => x.toUpperCase()) : '—');

function HistoryTab({ catalog, history, onReload, tombolMuat }) {
  const kolom = [
    { kunci: 'produk', label: 'Produk', hp: 'judul', isi: (l) => (
      <div className="min-w-0"><p className="truncate font-medium">{l.name}</p><p className="text-xs text-muted-foreground">{l.sku}</p></div>) },
    { kunci: 'old', label: 'Sebelum', rata: 'kanan', isi: (l) => <span className="tabular-nums">{angka(l.old_stock)}</span> },
    { kunci: 'delta', label: 'Selisih', rata: 'kanan', isi: (l) => (
      <span className={`tabular-nums font-medium ${l.delta > 0 ? 'text-[hsl(var(--success-text))]' : l.delta < 0 ? 'text-[hsl(var(--danger-text))]' : 'text-muted-foreground'}`}>
        {l.delta > 0 ? '+' : ''}{angka(l.delta)}
      </span>) },
    { kunci: 'new', label: 'Sesudah', rata: 'kanan', isi: (l) => <span className="tabular-nums font-medium">{angka(l.new_stock)}</span> },
    { kunci: 'jenis', label: 'Jenis', isi: (l) => labelJenis(l.sync_type) },
    { kunci: 'waktu', label: 'Waktu', isi: (l) => <span className="text-sm text-muted-foreground md:whitespace-nowrap">{jam(l.synced_at)}</span> },
  ];
  return (
    <>
      <Toolbar
        filters={<p className="text-sm text-muted-foreground">30 perubahan stok terakhir di {catalog.name}.</p>}
        tools={<>
          <TombolUnduh namaBerkas={`riwayat-stok-${catalog.name}`} namaLembar="Riwayat stok" baris={history} testId="catalog-history-unduh"
            kolom={[
              { label: 'Produk', nilai: (l) => l.name }, { label: 'SKU', nilai: (l) => l.sku },
              { label: 'Sebelum', nilai: (l) => Number(l.old_stock || 0) }, { label: 'Selisih', nilai: (l) => Number(l.delta || 0) },
              { label: 'Sesudah', nilai: (l) => Number(l.new_stock || 0) }, { label: 'Jenis', nilai: (l) => labelJenis(l.sync_type) },
              { label: 'Waktu', nilai: (l) => jam(l.synced_at) },
            ]} />
          {tombolMuat(onReload, false, 'catalog-history-refresh')}
        </>} />
      <TabelData kolom={kolom} baris={history} testId="catalog-history-table"
        kosong={<EmptyState title="Belum ada riwayat stok" description="Perubahan stok (manual, massal, atau sinkron gudang) tercatat di sini." />} />
    </>
  );
}

// ─── Form katalog ─────────────────────────────────────────────────────────────

function CatalogDialog({ open, initial, accounts, onSave, onClose }) {
  const [form, setForm] = useState({ is_active: true, name: '', description: '', account_id: '', platform: '' });
  const [saving, setSaving] = useState(false);
  const [galat, setGalat] = useState('');

  useEffect(() => {
    if (!open) return;
    setGalat('');
    setForm({ is_active: true, name: '', description: '', account_id: '', platform: '', ...initial });
  }, [open, initial]);

  // Auto-fill platform from account
  useEffect(() => {
    if (form.account_id) {
      const acc = accounts.find(a => a.id === form.account_id);
      if (acc) setForm(f => ({ ...f, platform: acc.platform }));
    }
  }, [form.account_id, accounts]);

  const simpan = async () => {
    if (!form.account_id) { setGalat('Pilih toko dulu.'); return; }
    if (!String(form.name || '').trim()) { setGalat('Nama katalog wajib diisi.'); return; }
    setSaving(true);
    setGalat('');
    try { await onSave(form); } catch (e) { setGalat(e.message); } finally { setSaving(false); }
  };

  return (
    <FormPopup open={open} onClose={onClose} ukuran="pendek" onSimpan={simpan} menyimpan={saving} galat={galat}
      judul={form.id ? 'Ubah katalog' : 'Buat katalog'} keterangan="Satu katalog berisi produk yang dijual di satu toko."
      testId="catalog-form">
      <div className="grid gap-4 sm:grid-cols-2">
      <Isian label="Toko" wajib htmlFor="cat-akun">
        <SmartNativeSelect id="cat-akun" className="w-full" value={form.account_id}
          onChange={e => setForm(f => ({ ...f, account_id: e.target.value }))} data-testid="catalog-form-account">
          <option value="">Pilih toko…</option>
          {accounts.map(a => <option key={a.id} value={a.id}>{labelPlatform(a.platform)} — {a.account_name || a.name}</option>)}
        </SmartNativeSelect>
      </Isian>
      <Isian label="Nama katalog" wajib htmlFor="cat-nama">
        <Input id="cat-nama" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
          placeholder="Contoh: Katalog produk utama" data-testid="catalog-form-name" />
      </Isian>
      </div>
      <Isian label="Deskripsi" htmlFor="cat-desk">
        <Textarea id="cat-desk" value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} rows={2} />
      </Isian>
      <label className="flex items-center gap-3 text-sm" htmlFor="cat-aktif">
        <Switch id="cat-aktif" checked={!!form.is_active} onCheckedChange={(v) => setForm(f => ({ ...f, is_active: v }))} />
        <span>Aktif</span>
      </label>
    </FormPopup>
  );
}

// ─── Form item ────────────────────────────────────────────────────────────────

function ItemDialog({ initial, catalog, token, productCategories = [], onSave, onClose }) {
  const isEdit = !!initial.id;
  // Mode: 'from_fg' (bawaan item baru) | 'manual' (mengubah item yang sudah ada)
  const [mode] = useState(isEdit ? 'manual' : 'from_fg');
  const [fgPickerOpen, setFgPickerOpen] = useState(false);
  const [fgPreview, setFgPreview] = useState(null);
  const [galat, setGalat] = useState('');

  const [form, setForm] = useState({
    is_active: true, sku: '', name: '', description: '', price: 0,
    original_price: 0, platform_price: 0, stock_quantity: 0, stock_alert_threshold: 10,
    material_id: '', fg_material_id: '', platform_url: '', weight_gram: 0,
    category: '', variant_info: '', variant_id: '',
    ...initial,
    // Kompat: item lama mungkin hanya punya price/original_price.
    harga_jual: initial.harga_jual ?? initial.price ?? 0,
    harga_coret: initial.harga_coret ?? initial.original_price ?? 0,
    harga_original: initial.harga_original ?? 0,
    hpp: initial.hpp ?? 0,
    category_id: initial.category_id ?? '',
    tags: Array.isArray(initial.tags) ? initial.tags.join(', ') : (initial.tags || ''),
  });
  const [saving, setSaving] = useState(false);

  // F6 — kategori item katalog MILIK MASTER PRODUK (lihat catatan di handleSaveItem).
  const linkedToMaster = !!(form.fg_material_id || form.material_id || form.variant_id)
    || mode === 'from_fg';
  // SKU/nama/varian milik master bila item tertaut; item lama tanpa tautan wajib ditautkan dulu.
  const lockMaster = mode === 'from_fg' || !!(form.fg_material_id || form.material_id || form.variant_id);
  const masterCategoryLabel = [initial.category_code, initial.category_name || initial.category]
    .filter(Boolean).join(' · ');

  // Fase 3b: daftar varian produksi internal (rahaza_model_variants) utk penautan stok Toko<->FG
  const [prodVariants, setProdVariants] = useState([]);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`${API}/api/rahaza/variants`, { headers: { Authorization: `Bearer ${token}` } });
        if (r.ok && !cancelled) {
          const data = await r.json();
          setProdVariants(Array.isArray(data) ? data : (data.variants || data.items || []));
        }
      } catch (_e) { /* silent */ }
    })();
    return () => { cancelled = true; };
  }, [token]);

  // If editing item that came from FG, show its FG preview
  useEffect(() => {
    if (isEdit && (initial.fg_material_id || initial.source === 'from_fg')) {
      setFgPreview({
        id: initial.fg_material_id || initial.material_id,
        code: initial.fg_code || initial.sku,
        name: initial.fg_name || initial.name,
        color: initial.fg_color || '',
        unit: initial.unit || 'pcs',
        stock_qty: initial.stock_quantity,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleFGSelect = (fg) => {
    setFgPreview(fg);
    setGalat('');
    setForm(f => ({
      ...f,
      fg_material_id: fg.id,
      sku: (fg.code || '').toUpperCase(),
      name: fg.name || '',
      category: fg.category || fg.subtype || '',
      variant_info: [
        fg.color ? `Warna: ${fg.color}` : null,
        fg.size_code ? `Size: ${fg.size_code}` : null,
        readField(fg, FIELD.composition) ? `Material: ${readField(fg, FIELD.composition)}` : null,
      ].filter(Boolean).join(' | '),
      stock_quantity: fg.stock_qty || 0,
      weight_gram: fg.weight_gram || 0,
    }));
  };

  const simpan = async () => {
    if (mode === 'from_fg' && !form.fg_material_id) { setGalat('Pilih produk dari Master FG dulu.'); return; }
    if (mode === 'manual' && (!String(form.sku || '').trim() || !String(form.name || '').trim())) {
      setGalat('SKU dan nama produk wajib diisi.'); return;
    }
    setSaving(true);
    setGalat('');
    try {
      await onSave({ ...form, _mode: mode });
    } catch (e) {
      setGalat(e.message);
    } finally {
      setSaving(false);
    }
  };

  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }));

  return (
    <>
      <FormPopup open onClose={onClose} ukuran="panjang" onSimpan={simpan} menyimpan={saving} galat={galat}
        bisaSimpan={!(mode === 'from_fg' && !form.fg_material_id)}
        judul={isEdit ? 'Ubah item katalog' : 'Tambah item katalog'} keterangan={catalog.name}
        testId="catalog-item-dialog">
        {/* Produk dari Master FG — item baru selalu diambil dari master supaya SKU, nama, dan stok ikut otomatis */}
        {mode === 'from_fg' && (
          <Isian label="Produk Master FG" wajib
            petunjuk="SKU, nama, dan stok mengikuti Master FG secara otomatis.">
            {fgPreview ? (
              <div className="flex items-center justify-between gap-3 rounded-md border border-[hsl(var(--primary)/0.4)] px-3 py-2"
                data-testid="mode-from-fg">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{fgPreview.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {fgPreview.code}{fgPreview.color ? ` · ${fgPreview.color}` : ''} · Stok master {angka(fgPreview.stock_qty)}
                  </p>
                </div>
                {!isEdit && (
                  <Button type="button" size="sm" variant="outline" onClick={() => setFgPickerOpen(true)}>Ganti</Button>
                )}
              </div>
            ) : (
              <Button type="button" variant="outline" className="w-full justify-start" onClick={() => setFgPickerOpen(true)}
                data-testid="open-fg-picker">
                <Search />Pilih dari Master FG…
              </Button>
            )}
          </Isian>
        )}

        {(mode === 'manual' || fgPreview) && (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
              <Isian label="SKU" wajib htmlFor="itm-sku" petunjuk={mode === 'from_fg' ? 'Otomatis dari FG' : undefined}>
                <Input id="itm-sku" value={form.sku} onChange={set('sku')} placeholder="SKU-001"
                  readOnly={lockMaster} className={lockMaster ? 'bg-muted/30' : ''} data-testid="catalog-item-sku" />
              </Isian>
              <Isian label="Kategori" petunjuk={linkedToMaster
                ? 'Mengikuti Master Produk — ubah di Master Produk, lalu "Segarkan dari master".'
                : 'Dari Master Kategori Produk (bukan teks bebas).'}>
                {linkedToMaster ? (
                  <div className="flex h-9 items-center gap-2 rounded-md border border-input bg-muted/30 px-3 text-sm text-foreground"
                    data-testid="item-category-readonly">
                    {(initial.category_code || form.category_code) && (
                      <Badge variant="outline">{initial.category_code || form.category_code}</Badge>
                    )}
                    <span className={masterCategoryLabel || form.category ? '' : 'text-muted-foreground'}>
                      {initial.category_name || form.category_name || form.category || 'Otomatis dari Master Produk'}
                    </span>
                  </div>
                ) : (
                  <SmartNativeSelect className="w-full" value={form.category_id || ''}
                    onChange={e => setForm(f => ({ ...f, category_id: e.target.value }))}
                    data-testid="item-category-select">
                    <option value="">Pilih kategori…</option>
                    {productCategories.map(c => (
                      <option key={c.id} value={c.id}>{c.sku_prefix} · {c.name}</option>
                    ))}
                  </SmartNativeSelect>
                )}
              </Isian>
            </div>

            <Isian label="Nama produk" wajib htmlFor="itm-nama" petunjuk={mode === 'from_fg' ? 'Otomatis dari FG' : undefined}>
              <Input id="itm-nama" value={form.name} onChange={set('name')} placeholder="Nama lengkap produk"
                readOnly={lockMaster} className={lockMaster ? 'bg-muted/30' : ''} data-testid="catalog-item-name" />
            </Isian>

            <Isian label="Varian" htmlFor="itm-varian" petunjuk={mode === 'from_fg' ? 'Otomatis dari FG' : undefined}>
              <Input id="itm-varian" value={form.variant_info} onChange={set('variant_info')}
                placeholder="Contoh: Warna: Hitam, Putih | Size: S, M, L"
                readOnly={lockMaster} className={lockMaster ? 'bg-muted/30' : ''} data-testid="catalog-item-variant" />
            </Isian>

            {/* 2026-11-07 (Tahap 5) — penautan varian HANYA untuk item lama yang belum tertaut Master FG. */}
            {mode === 'manual' && !(initial.fg_material_id || initial.material_id) && (
              <Isian label="Tautkan varian produksi (opsional)"
                petunjuk="Tautkan ke SKU varian produksi internal agar stok toko dan FG selaras.">
                <Select
                  value={form.variant_id || 'none'}
                  onValueChange={(val) => {
                    if (val === 'none') { setForm(f => ({ ...f, variant_id: '' })); return; }
                    const v = prodVariants.find(x => x.id === val);
                    setForm(f => ({
                      ...f,
                      variant_id: val,
                      sku: v?.sku || f.sku,
                      variant_info: v ? `Warna: ${v.color_name}, Size: ${v.size_code}` : f.variant_info,
                    }));
                  }}
                >
                  <SelectTrigger data-testid="catalog-variant-selector">
                    <SelectValue placeholder="Tidak ditautkan" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">Tidak ditautkan</SelectItem>
                    {prodVariants.map(v => (
                      <SelectItem key={v.id} value={v.id}>
                        {[v.sku, v.model_name, v.color_name, v.size_code].filter(Boolean).join(' · ')}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Isian>
            )}

            <div className="grid gap-4 sm:grid-cols-3">
              <Isian label="Harga jual (Rp)" wajib petunjuk="Harga akhir ke pembeli">
                <MoneyInput value={form.harga_jual} data-testid="catalog-input-harga-jual"
                  onChange={e => setForm(f => ({ ...f, harga_jual: e.target.value, price: e.target.value }))} />
              </Isian>
              <Isian label="Harga coret (Rp)" petunjuk="Dicoret untuk promo (≥ harga jual)">
                <MoneyInput value={form.harga_coret} data-testid="catalog-input-harga-coret"
                  onChange={e => setForm(f => ({ ...f, harga_coret: e.target.value, original_price: e.target.value }))} />
              </Isian>
              <Isian label="Harga resmi (Rp)" petunjuk="Harga normal / daftar resmi">
                <MoneyInput value={form.harga_original} data-testid="catalog-input-harga-original"
                  onChange={e => setForm(f => ({ ...f, harga_original: e.target.value }))} />
              </Isian>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <Isian label="Harga di platform (Rp)" petunjuk="Harga yang tertera di marketplace">
                <MoneyInput value={form.platform_price} onChange={e => setForm(f => ({ ...f, platform_price: e.target.value }))} />
              </Isian>
              <Isian label="HPP (Rp)" petunjuk="Biaya pokok dari R&D, otomatis. Tidak tampil ke pembeli.">
                <MoneyInput value={form.hpp || 0} readOnly disabled data-testid="catalog-input-hpp" className="bg-muted/40" />
              </Isian>
            </div>

            {/* Stok — mode manual bisa diisi; mode FG otomatis dari master */}
            {mode === 'manual' ? (
              <div className="grid gap-4 sm:grid-cols-3">
                <Isian label="Stok awal">
                  <Input type="number" min={0} value={form.stock_quantity} onChange={set('stock_quantity')} />
                </Isian>
                <Isian label="Batas peringatan stok">
                  <Input type="number" min={0} value={form.stock_alert_threshold} onChange={set('stock_alert_threshold')} />
                </Isian>
                <Isian label="Berat (gram)">
                  <Input type="number" min={0} value={form.weight_gram} onChange={set('weight_gram')} />
                </Isian>
              </div>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2">
                <Isian label="Batas peringatan stok">
                  <Input type="number" min={0} value={form.stock_alert_threshold} onChange={set('stock_alert_threshold')} />
                </Isian>
                <Isian label="Stok (otomatis)">
                  <Input type="number" value={form.stock_quantity} readOnly className="bg-muted/30" />
                </Isian>
              </div>
            )}

            <Isian label="URL produk di platform (opsional)">
              <Input value={form.platform_url} onChange={set('platform_url')} placeholder="https://shopee.co.id/..." />
            </Isian>

            <Isian label="Tag" petunjuk="Pisahkan dengan koma">
              <Input value={form.tags} onChange={set('tags')} placeholder="fashion, wanita, terlaris" />
            </Isian>

            {mode === 'manual' && (
              <label className="flex items-center gap-3 text-sm" htmlFor="item_active">
                <Switch id="item_active" checked={!!form.is_active} onCheckedChange={(v) => setForm(f => ({ ...f, is_active: v }))} />
                <span>Item aktif</span>
              </label>
            )}
          </>
        )}
      </FormPopup>

      {/* Pemilih produk Master FG */}
      <FGProductPickerDialog
        open={fgPickerOpen}
        onOpenChange={setFgPickerOpen}
        onSelect={handleFGSelect}
        token={token}
        title="Pilih produk dari Master FG"
        description={`Pilih produk barang jadi untuk ditambahkan ke katalog "${catalog.name}".`}
      />
    </>
  );
}

// ─── Form ubah stok satu item ─────────────────────────────────────────────────

function StockUpdateDialog({ item, onSave, onClose }) {
  const [qty, setQty] = useState(item.stock_quantity || 0);
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [galat, setGalat] = useState('');

  const delta = qty - (item.stock_quantity || 0);

  const simpan = async () => {
    setSaving(true);
    setGalat('');
    try { await onSave({ ...item, stock_quantity: parseFloat(qty) || 0, notes }); }
    catch (e) { setGalat(e.message); }
    finally { setSaving(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="pendek" onSimpan={simpan} menyimpan={saving} galat={galat}
      judul="Ubah stok" keterangan={`${item.name} · SKU ${item.sku} · stok saat ini ${angka(item.stock_quantity)} · batas ${item.stock_alert_threshold}`}
      labelSimpan="Simpan stok" testId="catalog-stock-form">
      <Isian label="Stok baru" wajib htmlFor="stk-baru"
        petunjuk={delta !== 0 ? `${delta > 0 ? `+${delta}` : delta} dari stok saat ini` : undefined}>
        <Input id="stk-baru" type="number" min={0} step={1} value={qty} onChange={e => setQty(e.target.value)} autoFocus />
      </Isian>
      <Isian label="Catatan" htmlFor="stk-cat">
        <Input id="stk-cat" value={notes} onChange={e => setNotes(e.target.value)} placeholder="Contoh: restock dari gudang, koreksi opname" />
      </Isian>
    </FormPopup>
  );
}

// ─── Form ubah stok massal ────────────────────────────────────────────────────

function BulkStockDialog({ items, data, onChange, onSave, onClose }) {
  const editCount = Object.values(data).filter(v => v.qty !== '' && v.qty !== undefined).length;
  const [saving, setSaving] = useState(false);
  const [galat, setGalat] = useState('');
  const simpan = async () => {
    setSaving(true);
    setGalat('');
    try { await onSave(); } catch (e) { setGalat(e.message); } finally { setSaving(false); }
  };
  const ubah = (id, k) => (e) => onChange(prev => ({ ...prev, [id]: { ...prev[id], [k]: e.target.value } }));

  const kolom = [
    { kunci: 'produk', label: 'Produk', hp: 'judul', isi: (item) => (
      <div className="min-w-0"><p className="truncate text-sm font-medium">{item.name}</p><p className="text-xs text-muted-foreground">{item.sku}</p></div>) },
    { kunci: 'kini', label: 'Stok saat ini', rata: 'kanan', isi: (item) => <span className="tabular-nums font-medium">{angka(item.stock_quantity)}</span> },
    { kunci: 'baru', label: 'Stok baru', isi: (item) => (
      <Input type="number" min={0} step={1} placeholder="—" value={data[item.id]?.qty ?? ''} onChange={ubah(item.id, 'qty')}
        className="w-24 text-right" aria-label={`Stok baru ${item.name}`} />) },
    { kunci: 'catatan', label: 'Catatan', isi: (item) => (
      <Input placeholder="Catatan" value={data[item.id]?.notes ?? ''} onChange={ubah(item.id, 'notes')}
        aria-label={`Catatan ${item.name}`} />) },
  ];

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" onSimpan={simpan} menyimpan={saving} galat={galat}
      bisaSimpan={editCount > 0} labelSimpan={editCount > 0 ? `Simpan (${editCount})` : 'Simpan'}
      judul="Ubah stok massal" keterangan="Isi stok baru untuk item yang ingin diubah. Kosongkan bila tidak diubah."
      testId="catalog-bulk-stock-form">
      <TabelData kolom={kolom} baris={items} testId="catalog-bulk-stock-table"
        kosong={<EmptyState title="Tidak ada item" description="Katalog ini belum punya item." />} />
    </FormPopup>
  );
}

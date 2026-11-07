
import { useState, useEffect, useRef } from 'react';
import { Plus, Eye, Pencil, Trash2, X, Zap, AlertTriangle, Loader2, Layers, Lock } from 'lucide-react';
import DataTable from './DataTable';
import Modal from './Modal';
import StatusBadge from './StatusBadge';
import ConfirmDialog from './ConfirmDialog';
import POWorkflowIndicator from './POWorkflowIndicator';
import FileAttachmentPanel from './FileAttachmentPanel';
import { PdfColumnPicker } from '../pdf/PdfColumnPicker';
import SearchableSelect from './SearchableSelect';
import ImportExportPanel from './ImportExportPanel';
import ImportExportToolbar from '../ImportExportToolbar';
import QuickCompleteModal from './QuickCompleteModal';
import { BizBadge } from './BusinessTypeBadge';
import { apiGet, apiPost, apiPut, apiDelete, apiFetch } from '../../../lib/api';
import { formatRupiah } from '@/lib/format';
import { MoneyInput } from '@/components/ui/money-input';
import { todayWIB, toWIBDate } from '@/lib/waktu';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { Notice, StatTile } from '../moduleAtoms';
import PageLayout from '../layout/PageLayout';

const STATUS_OPTIONS = ['Draft', 'Confirmed', 'Distributed', 'In Production', 'Completed', 'Closed'];
// PO yang sudah ditutup terkunci untuk semua peran (Tahap 2) — tombol Ubah/Tutup tidak ditawarkan.
const CLOSED_PO = ['Closed', 'Completed', 'Closed Short'];
// 2026-11-06 (Tahap 2): tombol Tutup PO memakai pemeriksaan qty PER UKURAN yang sama dengan menu Tutup PO.
// Kosong = semua ukuran terpenuhi; ada ukuran kurang ⇒ server meminta salah satu alasan tutup kurang.
const CLOSE_REASONS = ['', 'deadline_expired', 'buyer_material_shortage', 'cmt_quality_reject_final', 'mutual_agreement'];
// Label tampilan alasan tutup PO (termasuk kode lama untuk PO yang ditutup sebelum Tahap 2).
const CLOSE_REASON_LABELS = {
  '': 'Semua ukuran terpenuhi (tanpa kekurangan)',
  deadline_expired: 'Batas waktu terlewati',
  buyer_material_shortage: 'Bahan dari klien kurang',
  cmt_quality_reject_final: 'Reject kualitas CMT (final)',
  mutual_agreement: 'Kesepakatan bersama',
  full_fulfillment: 'Semua ukuran terpenuhi',
  'Under Production': 'Produksi kurang dari order',
  'Over Production': 'Produksi lebih dari order',
  'Price Adjustment': 'Penyesuaian harga',
  'Customer Agreement': 'Kesepakatan dengan pelanggan',
  Other: 'Lainnya',
};

// ── K12 (7 Nov 2026): SATU bentuk form untuk PO internal & PO maklon ───────────────────────────────────
// Urutan bagian sama: kepala → baris → aksesoris → total. Bedanya hanya yang memang beda bisnis: buyer,
// artikel katalog & harga jasa ke klien (maklon); tujuan barang jadi & cek HPP (internal). Upah jahit per pcs
// tampil di SETIAP baris kedua jenis — angka yang sama dengan menu Biaya Jahit (`po_items.cmt_price_snapshot`).
let lineSeq = 0;
const newLineKey = () => { lineSeq += 1; return `baris-${Date.now().toString(36)}-${lineSeq}`; };
const isBlank = (v) => v === '' || v === null || v === undefined;
const rupiah = (v) => formatRupiah(Number(v) || 0);
const stripUi = (it) => Object.fromEntries(Object.entries(it).filter(([k]) => !k.startsWith('__')));
const USED_DEEP_LINKS = new WeakSet();

function Field({ label, required, hint, children, className = '', testId }) {
  return (
    <div className={`min-w-0 ${className}`} data-testid={testId}>
      <label className="block text-xs font-medium text-muted-foreground mb-1">
        {label}{required && <span className="text-[hsl(var(--destructive))]"> *</span>}
      </label>
      {children}
      {hint && <p className="text-[11px] text-muted-foreground mt-1">{hint}</p>}
    </div>
  );
}

function SectionTitle({ children, aside, testId }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2" data-testid={testId}>
      <p className="text-sm font-semibold text-foreground">{children}</p>
      {aside}
    </div>
  );
}

export default function ProductionPOModule({ userRole, businessType, onNavigate, deepLinkParams }) {
  // FASE 5 DA: businessType 'internal' | 'maklon' (menu PO Produksi Internal / PO Maklon)
  const isInternal = businessType !== 'maklon';
  const bizKey = isInternal ? 'internal' : 'maklon';
  const [pos, setPOs] = useState([]);
  // [FASE 4 CLEANUP] Legacy `products`/`product_variants` state removed — dead code.
  // Maklon now uses buyer-catalog (`catalog_item_id`); Internal uses `rahaza_models` + `rahaza_variant_id`.
  const [catalogItems, setCatalogItems] = useState([]);  // maklon: dewi_maklon_buyer_catalog (master produk maklon, per buyer)
  const [models, setModels] = useState([]);   // internal: rahaza_models (D3 FK)
  const [vendors, setVendors] = useState([]);
  const [buyers, setBuyers] = useState([]);
  const [accessories, setAccessories] = useState([]);
  // ── AKSESORIS BOM MUAT OTOMATIS DI FORM (keluhan pemilik 2026-06) ─────────
  // Katalog maklon sudah punya BOM aksesoris dan angkanya sudah benar di Surat
  // Jalan/SPP, TAPI form buat PO tidak menampilkannya sama sekali — pemakai
  // menyangka BOM belum kena lalu mengetik ulang barisnya (kerja dobel & baris
  // kembar). Panel di bawah membaca `POST /api/dewi/maklon/bom-templates/
  // preview-accessories`, yaitu MESIN YANG SAMA dengan yang menulis
  // `po_accessories` saat PO disimpan — jadi angka di layar tidak mungkin
  // berbeda dari yang tersimpan. Baris ini TIDAK dikirim di payload (backend
  // yang menuliskannya) supaya tidak ada baris kembar.
  const [bomAcc, setBomAcc] = useState({ rows: [], warnings: [], total_pcs: 0, loading: false });
  const [rahazaVariants, setRahazaVariants] = useState({}); // Fase 2: cache varian internal per model_id
  const [showModal, setShowModal] = useState(false);
  const [showDetail, setShowDetail] = useState(false);
  // W2 (sesi #29) — dialog pemilih kolom untuk cetak SPP (termasuk Serial No).
  const [sppPickerOpen, setSppPickerOpen] = useState(false);
  const [showCloseModal, setShowCloseModal] = useState(false);
  const [editData, setEditData] = useState(null);
  const [detailData, setDetailData] = useState(null);
  const [costCheck, setCostCheck] = useState(null); // peringatan harga bahan/upah PO internal
  // ACC-1 — kebutuhan aksesoris PO (dari BOM) + posisi stok
  const [accReq, setAccReq] = useState(null);
  const [accReqLoading, setAccReqLoading] = useState(false);
  const [accReqCreating, setAccReqCreating] = useState(false);
  // ACC-1 — hasil aksi "Buat Permintaan" ditampilkan INLINE (bukan `alert()` native)
  // supaya pesan anti-dobel tetap terbaca di konteks tabelnya & tidak memblokir UI.
  const [accReqMsg, setAccReqMsg] = useState(null); // { type:'success'|'error', text }
  const [closeTargetPO, setCloseTargetPO] = useState(null);
  const [filterStatus, setFilterStatus] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [closeForm, setCloseForm] = useState({ close_reason: CLOSE_REASONS[0], close_notes: '' });
  const [refetchKey, setRefetchKey] = useState(0);
  const [form, setForm] = useState({ po_number: '', customer_name: '', buyer_id: '', vendor_id: '', po_date: '', deadline: '', delivery_deadline: '', notes: '', items: [], po_accessories: [] });
  // KELUHAN #1 (2026-07-31) — validasi form TIDAK boleh pakai `alert()` native:
  // pesannya hilang begitu diklik, tidak bisa dibaca ulang, dan menutupi konteks
  // baris item yang salah. Sekarang: banner inline di dalam modal (data-testid
  // `po-form-error`) + fokus otomatis ke baris item bermasalah.
  const [formError, setFormError] = useState(null);   // { text, itemIdx }
  // FASE G (2026-08-16) — kebijakan nomor dokumen (otomatis/manual) dibaca dari
  // SSOT penomoran. Tanpa ini layar tetap menyuruh mengetik nomor walau owner
  // sudah menyetelnya OTOMATIS, dan pemakai menanggung penolakan backend atas
  // setelan yang tidak pernah ia lihat.
  const [numPolicy, setNumPolicy] = useState(null);

  useEffect(() => {
    const key = businessType === 'maklon'
      ? 'production_pos.po_number_maklon' : 'production_pos.po_number';
    apiGet(`/doc-number-policy?key=${key}`)
      .then(setNumPolicy)
      .catch(() => setNumPolicy(null));   // gagal baca kebijakan ⇒ perlakukan manual
  }, [businessType, showModal]);        // dibaca ulang tiap modal dibuka → pratinjau nomor segar
  // Fase 3 — Cek seri dobel (live, non-blocking) saat BUAT ORDER. { [idx]: {loading, usages} }
  const [serialChecks, setSerialChecks] = useState({});
  const serialDebounce = useRef({});

  // Cek 1 seri ke SSOT (po_items.serial_number) untuk peringatan (tidak block simpan).
  const handleSerialChange = (idx, value) => {
    updateItem(idx, 'serial_number', value);
    if (serialDebounce.current[idx]) clearTimeout(serialDebounce.current[idx]);
    const v = (value || '').trim();
    if (!v) { setSerialChecks(s => ({ ...s, [idx]: null })); return; }
    serialDebounce.current[idx] = setTimeout(async () => {
      setSerialChecks(s => ({ ...s, [idx]: { loading: true, usages: [] } }));
      try {
        const params = new URLSearchParams({ serial: v, scope: 'all' });
        if (editData?.id) params.set('exclude_po_id', editData.id);
        const res = await apiGet(`/dewi/cmt-intake/serial-lookup?${params.toString()}`);
        setSerialChecks(s => ({ ...s, [idx]: { loading: false, usages: res.usages || [] } }));
      } catch { setSerialChecks(s => ({ ...s, [idx]: null })); }
    }, 450);
  };

  // 2026-11-07 (Tahap 8): tombol Buat/Ubah/Hapus memakai hak dari SERVER (aturan yang sama dengan simpan):
  // peran produksi/maklon bawaan atau izin Tambah/Ubah/Hapus modul PO di Peran & Hak Akses. Dulu layar
  // mencari kunci `production_po.create`/`po.create` (= PO pembelian) sehingga hanya superadmin yang melihat
  // tombol Buat PO, padahal server mengizinkan admin produksi/maklon.
  const [poPerms, setPoPerms] = useState({ can_create: false, can_edit: false, can_delete: false });
  useEffect(() => {
    let alive = true;
    apiGet(`/production-pos/permissions?business_type=${bizKey}`)
      .then(p => { if (alive && p) setPoPerms(p); })
      .catch(() => { if (alive) setPoPerms({ can_create: false, can_edit: false, can_delete: false }); });
    return () => { alive = false; };
  }, [bizKey]);
  const canEdit = !!poPerms.can_edit;
  const canCreate = !!poPerms.can_create;
  const canDelete = !!poPerms.can_delete;
  const formRef = useRef(form);
  formRef.current = form;

  useEffect(() => {
    fetchAccessories();
    fetchVendors();  // vendor/CMT dibutuhkan di Internal & Maklon (kirim material ke vendor)
    if (isInternal) { fetchModels(); }
    else { fetchBuyers(); }
  }, [isInternal]);

  // Pratinjau aksesoris BOM ikut berubah setiap artikel/qty item berubah.
  // Kuncinya diringkas jadi string supaya efek tidak jalan saat field lain
  // (mis. nomor seri) disunting; debounce 400ms supaya ketikan qty tidak
  // memanggil server per angka.
  const bomAccKey = isInternal ? '' : (form.items || [])
    .map(it => `${it.catalog_item_id || ''}:${Number(it.qty) || 0}`).join('|');
  useEffect(() => {
    if (isInternal || !showModal) {
      setBomAcc({ rows: [], warnings: [], total_pcs: 0, loading: false });
      return;
    }
    const payloadItems = (form.items || [])
      .filter(it => it.catalog_item_id && Number(it.qty) > 0)
      .map(it => ({ catalog_item_id: it.catalog_item_id, qty: Number(it.qty),
        label: it.product_name || it.sku || '' }));
    if (payloadItems.length === 0) {
      setBomAcc({ rows: [], warnings: [], total_pcs: 0, loading: false });
      return;
    }
    setBomAcc(s => ({ ...s, loading: true }));
    const t = setTimeout(async () => {
      try {
        const res = await apiPost('/dewi/maklon/bom-templates/preview-accessories',
          { items: payloadItems });
        setBomAcc({ rows: res?.accessories || [], warnings: res?.warnings || [],
          total_pcs: res?.total_pcs || 0, loading: false });
      } catch (e) {
        setBomAcc({ rows: [], total_pcs: 0, loading: false,
          warnings: [`Gagal memuat aksesoris BOM: ${e.message || 'kesalahan jaringan'}`] });
      }
    }, 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bomAccKey, isInternal, showModal]);

  const refetchPOs = () => setRefetchKey((k) => k + 1);

  // Server-paginated fetcher (Phase 10C)
  const posFetcher = async ({ page, per_page, sort_by, sort_dir, search }) => {
    const params = new URLSearchParams();
    params.set('page', String(page));
    params.set('per_page', String(per_page));
    if (sort_by) params.set('sort_by', sort_by);
    if (sort_dir) params.set('sort_dir', sort_dir);
    if (search) params.set('search', search);
    if (filterStatus) params.set('status', filterStatus);
    if (businessType) params.set('business_type', businessType);
    const env = await apiGet(`/production-pos?${params.toString()}`);
    // Keep `pos` array around so `expandedRowRender` can show item details
    const items = Array.isArray(env?.items) ? env.items : (Array.isArray(env) ? env : []);
    setPOs(items);
    return env;
  };

  const fetchBuyers = async () => {
    try {
      // DA: klien maklon = dewi_maklon_clients
      const data = await apiGet('/dewi/maklon/clients');
      const rows = Array.isArray(data) ? data : (data?.items || []);
      setBuyers(rows.filter(b => b.active !== false).map(b => ({
        ...b, buyer_name: b.buyer_name || b.name || '', buyer_code: b.buyer_code || b.code || '',
      })));
    } catch (e) { console.error(e); }
  };

  const fetchAccessories = async () => {
    try {
      // SSOT aksesoris = rahaza_materials (type=accessory) via /acc/items.
      // Endpoint lama /accessories sudah DEPRECATED & mengembalikan kosong.
      const data = await apiGet('/acc/items?type=accessory');
      const rows = Array.isArray(data) ? data : (data?.items || []);
      setAccessories(rows.filter(a => a.active !== false && a.status !== 'inactive'));
    } catch (e) { setAccessories([]); }
  };

  const fetchVendors = async () => {
    try {
      // SSOT vendor/CMT = vendor_partners. Diekspos via /garments (require_auth saja,
      // BUKAN admin-only) supaya staff Produksi yang membuat PO tetap bisa memuat daftar.
      const data = await apiGet('/garments');
      const rows = Array.isArray(data) ? data : (data?.items || []);
      setVendors(rows
        .filter(v => v.status !== 'inactive' && v.active !== false && v.is_active !== false)
        .map(v => ({
          ...v, garment_name: v.garment_name || v.name || '', garment_code: v.garment_code || v.code || '',
        })));
    } catch (e) { setVendors([]); }
  };

  const fetchModels = async () => {
    try {
      const data = await apiGet('/rahaza/models?active=true&limit=500');
      const rows = Array.isArray(data) ? data : (data?.items || []);
      setModels(rows);
    } catch (e) { setModels([]); }
  };


  // Fase 2: ambil daftar varian ber-SKU untuk sebuah model (di-cache per model_id)
  const fetchRahazaVariants = async (modelId) => {
    if (!modelId) return [];
    try {
      const data = await apiGet(`/rahaza/models/${modelId}/variants`);
      const list = (data && data.variants) ? data.variants : [];
      setRahazaVariants(prev => ({ ...prev, [modelId]: list }));
      return list;
    } catch (e) {
      setRahazaVariants(prev => ({ ...prev, [modelId]: [] }));
      return [];
    }
  };

  // [FASE 4 CLEANUP] Removed dead helpers `fetchProducts()` and `fetchVariantsForProduct()`.
  // They read the legacy `products`/`product_variants` collections which are no longer
  // rendered by any picker (Maklon → buyer-catalog, Internal → rahaza_models/variants).

  // MAKLON: master produk = Buyer Catalog (dewi_maklon_buyer_catalog), di-scope per buyer/klien.
  const fetchCatalog = async (clientId) => {
    if (!clientId) { setCatalogItems([]); return; }
    try {
      const data = await apiGet(`/dewi/maklon/buyer-catalog?client_id=${clientId}&status=active`);
      setCatalogItems(Array.isArray(data) ? data : (data?.items || []));
    } catch (e) { setCatalogItems([]); }
  };

  const openCreate = () => {
    setEditData(null);
    setFormError(null);
    setForm({ po_number: '', customer_name: isInternal ? 'Gudang FG Sendiri' : '', buyer_id: '', vendor_id: '', po_date: todayWIB(), deadline: '', delivery_deadline: '', notes: '', items: [], po_accessories: [] });
    setShowModal(true);
  };

  // Satu bentuk baris untuk kedua jenis PO. Kunci `__…` hanya untuk layar (tidak dikirim ke server):
  // __key = identitas baris, __sug = usulan upah + asalnya, __typed = upah diketik/dimuat (bukan usulan).
  const blankLine = () => (isInternal
    ? { __key: newLineKey(), model_id: '', rahaza_variant_id: '', size_id: '', product_name: '', size: '', color: '', sku: '', qty: '', serial_number: '', cmt_price_snapshot: '' }
    : { __key: newLineKey(), catalog_item_id: '', product_id: '', product_name: '', variant_id: '', maklon_variant_id: '', buyer_ref_code: '', size: '', color: '', color_code: '', sku: '', qty: '', serial_number: '', selling_price_snapshot: '', cmt_price_snapshot: '' });

  const addItem = () => {
    setFormError(null);
    setForm(f => ({ ...f, items: [...f.items, blankLine()] }));
  };

  // ── Upah jahit per pcs: usulan dari server (pintu yang sama dengan menu Biaya Jahit) ───────────────────
  const rateLocked = !!editData?.rate_lock;
  const fetchRateSuggestions = async (lines, vendorId, excludePoId) => {
    const payload = (lines || []).filter(l => l.model_id || l.catalog_item_id || l.sku)
      .map(l => ({ key: l.__key, model_id: l.model_id || '', catalog_item_id: l.catalog_item_id || '', sku: l.sku || '' }));
    if (!payload.length) return {};
    try {
      const res = await apiPost('/production-pos/rate-suggest', {
        vendor_id: vendorId || '', business_type: bizKey,
        exclude_po_id: excludePoId === undefined ? (editData?.id || '') : excludePoId, lines: payload });
      return res?.items || {};
    } catch { return {}; }
  };

  // Pasang usulan ke baris: kotak upah yang KOSONG (atau berisi usulan lama, belum diketik) diisi usulan;
  // upah yang diketik pengguna tidak pernah diganti diam-diam.
  const applySuggestions = (sug, { fill = true } = {}) => {
    setForm(f => ({ ...f, items: f.items.map(l => {
      const s = sug[l.__key];
      if (!s) return l;
      const replaceable = isBlank(l.cmt_price_snapshot) || !l.__typed;
      return { ...l, __sug: s,
        ...(fill && !rateLocked && replaceable && Number(s.rate) > 0 ? { cmt_price_snapshot: s.rate, __typed: false } : {}) };
    }) }));
  };

  const suggestForLines = async (lines, opts = {}) => {
    const sug = await fetchRateSuggestions(lines, opts.vendorId ?? formRef.current.vendor_id, opts.excludePoId);
    applySuggestions(sug, opts);
    return sug;
  };

  // Penjahit diganti → usulan dihitung ulang untuk penjahit baru. Kotak kosong langsung diisi; kotak yang sudah
  // berisi angka lain hanya diganti bila pengguna setuju (confirmDialog).
  const changeVendor = async (vendorId, { lines, excludePoId } = {}) => {
    setForm(f => ({ ...f, vendor_id: vendorId }));
    const cur = (lines || formRef.current.items).filter(l => l.model_id || l.catalog_item_id);
    if (!cur.length || rateLocked) return;
    const sug = await fetchRateSuggestions(cur, vendorId, excludePoId);
    const differ = cur.filter(l => {
      const s = sug[l.__key];
      return s && Number(s.rate) > 0 && !isBlank(l.cmt_price_snapshot) && Number(l.cmt_price_snapshot) !== Number(s.rate);
    });
    setForm(f => ({ ...f, items: f.items.map(l => {
      const s = sug[l.__key];
      if (!s) return l;
      return { ...l, __sug: s, ...(isBlank(l.cmt_price_snapshot) && Number(s.rate) > 0 ? { cmt_price_snapshot: s.rate, __typed: false } : {}) };
    }) }));
    if (!differ.length) return;
    const vName = vendors.find(v => v.id === vendorId)?.garment_name || 'penjahit baru';
    const ok = await confirmDialog({
      title: `Pakai upah jahit ${vName}?`,
      body: `${differ.length} baris sudah berisi upah lain: `
        + differ.slice(0, 4).map(l => `${l.sku || l.product_name || 'baris'} ${rupiah(l.cmt_price_snapshot)} → ${rupiah(sug[l.__key].rate)}`).join('; ')
        + (differ.length > 4 ? ` (+${differ.length - 4} lagi)` : '') + '. Pilih "Biarkan" untuk tetap memakai angka yang sekarang.',
      confirmLabel: 'Pakai tarif baru', cancelLabel: 'Biarkan',
    });
    if (!ok) return;
    const keys = new Set(differ.map(l => l.__key));
    setForm(f => ({ ...f, items: f.items.map(l => (keys.has(l.__key) && sug[l.__key]
      ? { ...l, cmt_price_snapshot: sug[l.__key].rate, __typed: false } : l)) }));
  };

  const addAccessoryItem = () => {
    setForm(f => ({ ...f, po_accessories: [...(f.po_accessories || []), { accessory_id: '', accessory_name: '', accessory_code: '', qty_needed: '', unit: 'pcs', notes: '' }] }));
  };

  const removeAccessoryItem = (idx) => {
    setForm(f => ({ ...f, po_accessories: (f.po_accessories || []).filter((_, i) => i !== idx) }));
  };

  const updateAccessoryItem = (idx, field, value) => {
    const items = [...(form.po_accessories || [])];
    items[idx] = { ...items[idx], [field]: value };
    if (field === 'accessory_id') {
      const acc = accessories.find(a => a.id === value);
      if (acc) {
        // Support both canonical (accessory_name/accessory_code) and legacy (name/code) shapes.
        items[idx].accessory_name = acc.accessory_name || acc.name || '';
        items[idx].accessory_code = acc.accessory_code || acc.code || '';
        items[idx].unit = acc.unit || 'pcs';
      }
    }
    setForm(f => ({ ...f, po_accessories: items }));
  };

  const removeItem = (idx) => {
    setForm(f => ({ ...f, items: f.items.filter((_, i) => i !== idx) }));
  };

  const updateItem = async (idx, field, value) => {
    // pesan error validasi dibersihkan begitu baris yang ditandai disentuh lagi
    setFormError(prev => (prev && (prev.itemIdx === idx || prev.itemIdx === null) ? null : prev));
    const newItems = [...formRef.current.items];
    newItems[idx] = { ...newItems[idx], [field]: value };
    // upah yang diketik pengguna tidak lagi diganti usulan
    if (field === 'cmt_price_snapshot') newItems[idx].__typed = !isBlank(value);
    // produk baris diganti → upah lama milik produk lain: dikosongkan lalu diisi usulan produk baru
    const productChanged = field === 'model_id' || field === 'catalog_item_id';
    if (productChanged) { newItems[idx].cmt_price_snapshot = ''; newItems[idx].__typed = false; newItems[idx].__sug = null; }
    if (field === 'model_id') {
      const model = models.find(m => m.id === value);
      newItems[idx].product_name = model?.name || '';
      // Fase 2: model berubah → reset varian & derived fields; muat daftar varian
      newItems[idx].rahaza_variant_id = '';
      newItems[idx].size_id = '';
      newItems[idx].size = '';
      newItems[idx].color = '';
      newItems[idx].sku = '';
      if (value) fetchRahazaVariants(value);
    }
    if (field === 'rahaza_variant_id') {
      const list = rahazaVariants[newItems[idx].model_id] || [];
      const v = list.find(x => x.id === value);
      if (v) {
        newItems[idx].size_id = v.size_id || '';
        newItems[idx].size = v.size_code || '';
        newItems[idx].color = v.color_name || '';
        newItems[idx].sku = v.sku || '';
      } else {
        newItems[idx].size_id = ''; newItems[idx].size = ''; newItems[idx].color = ''; newItems[idx].sku = '';
      }
    }
    if (field === 'catalog_item_id') {
      const cat = catalogItems.find(c => c.id === value);
      newItems[idx].product_name = cat?.product_name || '';
      newItems[idx].selling_price_snapshot = cat?.default_selling_price ?? '';
      newItems[idx].buyer_ref_code = cat?.buyer_ref_code || '';
      // reset variant-derived fields
      newItems[idx].maklon_variant_id = '';
      newItems[idx].color = ''; newItems[idx].color_code = ''; newItems[idx].size = '';
      const vars = (cat?.variants || []).filter(v => v.active !== false);
      // Bila artikel punya varian master data → SKU HARUS dipilih dari varian (kosongkan dulu).
      // Bila tidak ada varian → fallback custom, sku default = artikel_code.
      newItems[idx].sku = vars.length > 0 ? '' : (cat?.artikel_code || '');
    }
    if (field === 'maklon_variant_sku') {
      const cat = catalogItems.find(c => c.id === newItems[idx].catalog_item_id);
      const v = (cat?.variants || []).find(x => x.sku === value);
      if (v) {
        newItems[idx].maklon_variant_id = v.id || v.sku;
        newItems[idx].sku = v.sku || '';
        newItems[idx].color = v.color || '';
        newItems[idx].color_code = v.color_code || '';
        newItems[idx].size = v.size || '';
        if (v.buyer_ref_code) newItems[idx].buyer_ref_code = v.buyer_ref_code;
      } else {
        newItems[idx].maklon_variant_id = '';
        newItems[idx].sku = ''; newItems[idx].color = ''; newItems[idx].color_code = ''; newItems[idx].size = '';
      }
    }
    // [FASE 4 CLEANUP] Removed dead `product_id`/`variant_id` handlers (legacy products/
    // product_variants). No picker renders them; Maklon uses `catalog_item_id`.
    setForm(f => ({ ...f, items: newItems }));
    // K12: usulan upah jahit begitu produk/varian baris diketahui (model + penjahit yang sama)
    if ((productChanged && value) || field === 'rahaza_variant_id' || field === 'maklon_variant_sku') {
      suggestForLines([newItems[idx]]);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const fail = (text, itemIdx = null) => { setFormError({ text, itemIdx }); return false; };
    setFormError(null);
    if (!isInternal && !editData && !form.buyer_id) { fail('Pilih buyer (klien maklon) dulu — artikel katalog selalu milik satu buyer.'); return; }
    if (form.items.length === 0) { fail('Tambahkan minimal 1 baris produk.'); return; }
    // Satu urutan pemeriksaan & satu bunyi pesan untuk kedua jenis PO. Varian wajib dari master data:
    // internal → rantai stok FG per warna; maklon → bila artikel katalog punya varian ber-SKU.
    for (let i = 0; i < form.items.length; i++) {
      const it = form.items[i];
      const n = i + 1;
      if (isInternal ? !it.model_id : !it.catalog_item_id) {
        fail(`Baris #${n}: pilih ${isInternal ? 'model produk' : 'artikel katalog buyer'} dulu.`, i); return;
      }
      const cat = isInternal ? null : catalogItems.find(c => c.id === it.catalog_item_id);
      const vars = (cat?.variants || []).filter(v => v.active !== false);
      const variantMissing = isInternal ? !it.rahaza_variant_id : (vars.length > 0 && !vars.some(v => v.sku === it.sku));
      if (variantMissing) { fail(`Baris #${n}: pilih varian (warna · ukuran · SKU) dari master data.`, i); return; }
      if (!it.qty || Number(it.qty) <= 0) { fail(`Baris #${n}: qty harus lebih dari 0.`, i); return; }
      if (!isBlank(it.cmt_price_snapshot) && !(Number(it.cmt_price_snapshot) >= 0)) {
        fail(`Baris #${n}: upah jahit per pcs harus angka 0 atau lebih.`, i); return;
      }
    }
    // Phase 8.6 — Send items + po_accessories together in the body (PUT supports delta update).
    // K12: upah jahit per pcs dikirim untuk KEDUA jenis PO; harga jasa ke klien hanya maklon.
    const itemsPayload = form.items.map(it => ({
      ...stripUi(it),
      qty: Number(it.qty),
      cmt_price_snapshot: isBlank(it.cmt_price_snapshot) ? 0 : Number(it.cmt_price_snapshot),
      ...(isInternal ? {} : { selling_price_snapshot: Number(it.selling_price_snapshot) || 0 }),
    }));
    const accPayload = (form.po_accessories || [])
      .filter(a => a.accessory_name || a.accessory_id)
      .map(a => ({ ...a, qty_needed: Number(a.qty_needed) || 0 }));
    const payload = { ...form, items: itemsPayload, po_accessories: accPayload, business_type: bizKey };
    // FASE G (2026-08-16) — mode OTOMATIS: nomor JANGAN dikirim. Backend menolak
    // nomor ketikan saat mode otomatis (dan menyebut nomor yang akan dipakai),
    // supaya tidak ada nomor yang "lolos" tanpa mengikuti pola.
    if (!editData && numPolicy?.mode === 'auto') delete payload.po_number;
    try {
      const data = editData
        ? await apiPut(`/production-pos/${editData.id}`, payload)
        : await apiPost('/production-pos', payload);
      // For create path, backend doesn't accept po_accessories in POST; keep legacy secondary call
      if (!editData && accPayload.length > 0) {
        try {
          await apiPost('/po-accessories', { po_id: data.id, items: accPayload });
        } catch (e) {
          // 2026-11-06 (pola P6): PO tersimpan, tetapi aksesorisnya tidak — dulu ditelan tanpa pesan
          toast.error(`PO tersimpan, tetapi aksesoris gagal disimpan: ${e.message}. Tambahkan lagi dari detail PO.`);
        }
      }
      setShowModal(false);
      refetchPOs();
    } catch (err) { setFormError({ text: err.message || 'Gagal menyimpan PO', itemIdx: null }); }
  };

  const openDetail = async (row) => {
    try {
      const data = await apiGet(`/production-pos/${row.id}`);
      setDetailData(data);
      setShowDetail(true);
      loadAccReq(row.id);
      setCostCheck(null);
      if (isInternal) apiGet(`/production-pos/${row.id}/cost-check`).then(setCostCheck).catch(() => setCostCheck(null));
    } catch (e) { toast.error(e.message || 'Gagal memuat detail'); }
  };

  // ── ACC-1 — kebutuhan aksesoris PO (BOM explode + posisi stok + kekurangan) ──
  const loadAccReq = async (poId, { keepMessage = false } = {}) => {
    setAccReqLoading(true);
    setAccReq(null);
    // Pesan hasil aksi TIDAK dihapus saat refresh yang dipicu oleh aksi itu
    // sendiri — kalau tidak, notifikasi sukses langsung hilang sebelum terbaca.
    if (!keepMessage) setAccReqMsg(null);
    try {
      const d = await apiGet(`/production-pos/${poId}/accessory-requirements`);
      setAccReq(d);
    } catch (e) {
      setAccReq({ error: e.message || 'Gagal memuat kebutuhan aksesoris' });
    } finally { setAccReqLoading(false); }
  };

  const createAccRequest = async (poId, onlyShortage = true) => {
    setAccReqCreating(true);
    setAccReqMsg(null);
    try {
      const res = await apiFetch(`/production-pos/${poId}/accessory-requirements/create-request`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ only_shortage: onlyShortage }),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d?.detail || 'Gagal mengajukan pembelian aksesoris');
      // 2026-11-06 (Tahap 2): kekurangan = PEMBELIAN (Permintaan Pengadaan), bukan pengeluaran stok
      setAccReqMsg({ type: 'success', text: d.message || 'Permintaan Pengadaan untuk aksesoris yang kurang dibuat & diajukan.' });
      loadAccReq(poId, { keepMessage: true });
    } catch (e) {
      setAccReqMsg({ type: 'error', text: e.message || 'Gagal membuat permintaan aksesoris' });
    } finally { setAccReqCreating(false); }
  };

  // `opts.vendorId` (dari Kirim Material CMT): penjahit dipilih saat kirim tetapi upahnya belum ada — form
  // dibuka dengan penjahit itu terisi dan usulan upahnya langsung ditawarkan (satu tempat mengetik upah).
  const openEdit = async (row, opts = {}) => {
    // Phase 8.6 — Load full PO detail (items + po_accessories) so user can edit everything.
    try {
      const [poData, statsData] = await Promise.all([
        apiGet(`/production-pos/${row.id}`),
        apiGet(`/po-items-produced?po_id=${row.id}`),
      ]);
      const statsById = {};
      (Array.isArray(statsData) ? statsData : []).forEach(s => { statsById[s.id] = s; });
      // [FASE 4 CLEANUP] Removed dead per-item `/product-variants` fetch loop (legacy).
      // Historical PO items keep their stored size/color/sku fields; no variant dropdown
      // is rendered anymore (Internal uses rahaza variants, Maklon uses buyer-catalog).

      const mappedItems = (poData.items || []).map(it => {
        const st = statsById[it.id] || {};
        const rate = Number(it.cmt_price_snapshot) > 0 ? it.cmt_price_snapshot : '';
        return {
          __key: newLineKey(),
          id: it.id,
          catalog_item_id: it.catalog_item_id || '',
          product_id: it.product_id || '',
          product_name: it.product_name || '',
          variant_id: it.variant_id || '',
          model_id: it.model_id || '',
          rahaza_variant_id: it.rahaza_variant_id || '',
          maklon_variant_id: it.maklon_variant_id || '',
          buyer_ref_code: it.buyer_ref_code || '',
          color_code: it.color_code || '',
          size_id: it.size_id || '',
          size: it.size || '',
          color: it.color || '',
          sku: it.sku || '',
          qty: it.qty || '',
          serial_number: it.serial_number || '',
          ...(isInternal ? {} : { selling_price_snapshot: it.selling_price_snapshot || '' }),
          cmt_price_snapshot: rate,
          __typed: rate !== '',
          // guardrail hints
          __has_shipments: (st.total_shipped || 0) > 0 || (st.total_produced || 0) > 0,
          __min_qty: Math.max(st.total_shipped || 0, st.total_produced || 0),
        };
      });
      // Additionally fetch po-items to discover vendor-ship amount per item
      const piData = await apiGet(`/po-items?po_id=${row.id}`);
      const vendorSentById = {};
      (Array.isArray(piData) ? piData : []).forEach(pi => { vendorSentById[pi.id] = pi.total_sent_to_vendor || 0; });
      mappedItems.forEach(m => {
        const vendorSent = vendorSentById[m.id] || 0;
        if (vendorSent > 0) m.__has_shipments = true;
        m.__min_qty = Math.max(m.__min_qty || 0, vendorSent);
      });

      setEditData(poData);
      if (!isInternal) fetchCatalog(poData.buyer_id);
      else {
        // Fase 2: prefetch daftar varian untuk tiap model item internal (agar dropdown terisi)
        const modelIds = [...new Set(mappedItems.map(m => m.model_id).filter(Boolean))];
        modelIds.forEach(mid => fetchRahazaVariants(mid));
      }
      setFormError(null);
      setForm({
        po_number: poData.po_number || '',
        customer_name: poData.customer_name || '',
        buyer_id: poData.buyer_id || '',
        vendor_id: poData.vendor_id || '',
        po_date: toWIBDate(poData.po_date),
        deadline: toWIBDate(poData.deadline),
        delivery_deadline: toWIBDate(poData.delivery_deadline),
        notes: poData.notes || '',
        items: mappedItems,
        po_accessories: (poData.po_accessories || []).map(a => ({
          id: a.id,
          accessory_id: a.accessory_id || '',
          accessory_name: a.accessory_name || '',
          accessory_code: a.accessory_code || '',
          qty_needed: a.qty_needed || '',
          unit: a.unit || 'pcs',
          notes: a.notes || '',
        })),
      });
      setShowModal(true);
      if (opts.vendorId && !poData.vendor_id && !poData.rate_lock) {
        // penjahit dari Kirim Material: kotak upah yang kosong diisi usulan penjahit itu
        await changeVendor(opts.vendorId, { lines: mappedItems, excludePoId: poData.id });
      } else {
        // PO lama: upah tersimpan TIDAK diubah — usulan hanya tampil sebagai keterangan di bawah kotaknya
        const sug = await fetchRateSuggestions(mappedItems, poData.vendor_id, poData.id);
        applySuggestions(sug, { fill: false });
      }
    } catch (err) {
      toast.error('Gagal memuat detail PO: ' + (err.message || err));
    }
  };

  // Tautan dari Kirim Material CMT / Biaya Jahit: { edit_po_id, vendor_id } → buka form ubah PO itu SEKALI.
  // Objek parameter yang sudah dipakai dicatat (USED_DEEP_LINKS) supaya kembali ke menu ini lewat sidebar —
  // parameter tautan lama masih tersimpan di App — tidak membuka form itu lagi.
  useEffect(() => {
    const pid = deepLinkParams?.edit_po_id;
    if (!pid || USED_DEEP_LINKS.has(deepLinkParams)) return;
    USED_DEEP_LINKS.add(deepLinkParams);
    openEdit({ id: pid }, { vendorId: deepLinkParams?.vendor_id || '' });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deepLinkParams]);

  const transitionStatus = async (poId, nextStatus) => {
    // FASE 5 DA: transisi status HANYA dari allowed_next backend (state machine)
    try {
      await apiPost(`/production-pos/${poId}/status`, { status: nextStatus });
      const data = await apiGet(`/production-pos/${poId}`);
      setDetailData(data);
      refetchPOs();
    } catch (err) { toast.error(err.message || 'Perubahan status ditolak server'); }
  };

  const handleClosePO = async (e) => {
    e.preventDefault();
    try {
      await apiPost(`/production-pos/${closeTargetPO.id}/close`, closeForm);
      setShowCloseModal(false);
      refetchPOs();
    } catch (e) { toast.error(e.message || 'Gagal menutup PO'); }
  };

  const handleDelete = async () => {
    if (!confirmDelete) return;
    try {
      await apiDelete(`/production-pos/${confirmDelete.id}`);
      setConfirmDelete(null);
      refetchPOs();
    } catch (e) { toast.error(e.message || 'Gagal menghapus PO'); }
  };

  const [expandedPOs, setExpandedPOs] = useState({});
  const [quickCompletePO, setQuickCompletePO] = useState(null);
  const togglePO = (id) => setExpandedPOs(prev => ({ ...prev, [id]: !prev[id] }));

  const fmtDate = (d) => d ? new Date(d).toLocaleDateString('id-ID') : '-';
  const fmt = (v) => v ? formatRupiah(v) : 'Rp 0';

  const columns = [
    { key: 'po_number', label: 'No. PO / Identifikasi', render: (v, row) => (
      <div>
        <div className="flex items-center gap-2">
          <span className="font-bold text-[hsl(var(--primary))]">{v}</span>
          <BizBadge type={row.business_type} size="xs" />
        </div>
        <div className="text-xs text-muted-foreground/70 mt-0.5">
          {row.vendor_name ? <span className="text-[hsl(var(--primary))]">{row.vendor_name}</span> : <span>-</span>}
          {' · '}{fmtDate(row.po_date || row.created_at)}
        </div>
        {(row.serial_numbers || []).length > 0 && (
          <div className="text-xs text-[hsl(var(--success))] mt-0.5 flex flex-wrap gap-1">
            {row.serial_numbers.slice(0, 3).map((sn, i) => (
              <span key={i} className="bg-[hsl(var(--success)/0.1)] px-1.5 py-0.5 rounded tabular-nums">{sn}</span>
            ))}
            {row.serial_numbers.length > 3 && <span className="text-muted-foreground/70">+{row.serial_numbers.length - 3} lagi</span>}
          </div>
        )}
      </div>
    )},
    { key: 'customer_name', label: 'Customer' },
    // FASE 9 (keluhan #4 owner: "bentuk cards yang memotong content dalamnya"):
    // `whitespace-nowrap` + `shrink-0` mencegah teks "2 item" terbelah dua baris
    // di dalam kotak rounded ketika kolom menyempit.
    { key: 'item_count', label: 'Items', render: (v, row) => (
      <button onClick={(e) => { e.stopPropagation(); togglePO(row.id); }}
        data-testid={`po-toggle-items-${row.id}`}
        className="inline-flex shrink-0 items-center gap-1 px-2 py-0.5 bg-muted text-foreground/90 text-xs rounded-full font-medium whitespace-nowrap leading-none hover:bg-[hsl(var(--primary)/0.15)] hover:text-[hsl(var(--primary))] transition-colors">
        <span className="text-[10px]">{expandedPOs[row.id] ? '▼' : '▶'}</span>
        <span>{v || 0} item</span>
      </button>
    )},
    { key: 'total_qty', label: 'Total Qty', render: (v) => v?.toLocaleString('id-ID') },
    { key: 'deadline', label: 'Deadline Prod.', render: (v) => {
      if (!v) return '-';
      const isOverdue = toWIBDate(v) < todayWIB();
      return <span className={isOverdue ? 'text-[hsl(var(--destructive))] font-medium' : ''}>{fmtDate(v)}</span>;
    }},
    { key: 'delivery_deadline', label: 'Deadline Kirim', render: (v) => {
      if (!v) return '-';
      const isOverdue = toWIBDate(v) < todayWIB();
      return <span className={isOverdue ? 'text-[hsl(var(--warning))] font-medium' : 'text-muted-foreground'}>{fmtDate(v)}</span>;
    }},
    { key: 'status', label: 'Status / Workflow', render: (v, row) => (
      <div className="space-y-1.5">
        <StatusBadge status={v} />
        <POWorkflowIndicator status={v} compact={true} />
      </div>
    )},
    { key: 'created_by', label: 'Dibuat' },
    { key: 'actions', label: 'Aksi', render: (_, row) => (
      <div className="flex items-center gap-1">
        <button onClick={() => openDetail(row)} data-testid={`po-detail-btn-${row.id}`} className="p-1.5 rounded hover:bg-[hsl(var(--primary)/0.1)] text-[hsl(var(--primary))]" title="Detail"><Eye className="w-4 h-4" /></button>
        {/* 2026-08-01: pintu masuk ke BOM PO Maklon (Detail 360° → tab BOM).
            Sebelumnya BOM Template maklon tidak punya jalur dari daftar PO. */}
        {!isInternal && onNavigate && (
          <button
            onClick={() => onNavigate('maklon-po-360', { po_id: row.id, tab: 'bom' })}
            data-testid={`po-bom-btn-${row.id}`}
            className="p-1.5 rounded hover:bg-[hsl(var(--primary)/0.1)] text-[hsl(var(--primary))]"
            title="BOM & kebutuhan material (Detail 360°)"><Layers className="w-4 h-4" /></button>
        )}
        {canEdit && !CLOSED_PO.includes(row.status) && (
          <>
            <button onClick={() => openEdit(row)} data-testid={`po-edit-btn-${row.id}`} className="p-1.5 rounded hover:bg-[hsl(var(--warning)/0.1)] text-[hsl(var(--warning))]" title="Ubah PO" aria-label="Ubah PO"><Pencil className="w-4 h-4" /></button>
            <button
              onClick={() => setQuickCompletePO(row)}
              data-testid={`quick-complete-btn-${row.id}`}
              className="p-1.5 rounded hover:bg-[hsl(var(--primary)/0.1)] text-[hsl(var(--primary))]"
              title="Selesaikan cepat — semua alur produksi sekaligus"
            >
              <Zap className="w-4 h-4" />
            </button>
            <button onClick={() => { setCloseTargetPO(row); setCloseForm({ close_reason: CLOSE_REASONS[0], close_notes: '' }); setShowCloseModal(true); }}
              className="p-1.5 rounded hover:bg-[hsl(var(--warning)/0.1)] text-[hsl(var(--warning))] text-xs" title="Tutup PO">Tutup</button>
          </>
        )}
        {canDelete && (
          <button onClick={() => setConfirmDelete(row)} data-testid={`po-delete-btn-${row.id}`} className="p-1.5 rounded hover:bg-[hsl(var(--destructive)/0.1)] text-[hsl(var(--destructive))]" title="Hapus PO" aria-label="Hapus PO"><Trash2 className="w-4 h-4" /></button>
        )}
      </div>
    )}
  ];

  // Custom expandable row render for DataTable
  const expandedRowRender = (row) => {
    if (!expandedPOs[row.id] || !row.items || row.items.length === 0) return null;
    // FASE 9: konten expand DIBUNGKUS kartu dengan scroll horizontal SENDIRI
    // (`max-w-full overflow-x-auto`) supaya kolom paling kanan (Qty) tidak
    // terpotong oleh lebar tabel induk.
    return (
      <div className="bg-[hsl(var(--warning)/0.3)] border-t border-[hsl(var(--warning)/0.35)] px-4 py-3 max-w-full">
        <p className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wide">Detail Item PO</p>
        <div className="max-w-full overflow-x-auto rounded-lg bg-[var(--card-surface,#fff)] border border-[var(--glass-border,rgba(0,0,0,0.08))]">
          <table className="w-full text-xs min-w-[760px]">
            <thead>
              <tr className="border-b border-[hsl(var(--warning)/0.35)]">
                <th className="text-left py-1.5 pl-3 pr-3 text-[hsl(var(--warning))] font-semibold whitespace-nowrap">Serial/Batch</th>
                <th className="text-left py-1.5 pr-3 text-muted-foreground font-semibold">SKU</th>
                <th className="text-left py-1.5 pr-3 text-muted-foreground font-semibold">Produk</th>
                <th className="text-left py-1.5 pr-3 text-muted-foreground font-semibold">Size</th>
                <th className="text-left py-1.5 pr-3 text-muted-foreground font-semibold">Warna</th>
                <th className="text-right py-1.5 pr-3 text-muted-foreground font-semibold whitespace-nowrap">Qty</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[hsl(var(--warning)/0.35)]">
              {row.items.map(item => (
                <tr key={item.id} className="hover:bg-[hsl(var(--warning)/0.1)]">
                  <td className="py-1.5 pl-3 pr-3 tabular-nums text-[hsl(var(--warning))] font-semibold whitespace-nowrap">{item.serial_number || <span className="text-muted-foreground/50">—</span>}</td>
                  <td className="py-1.5 pr-3 tabular-nums text-[hsl(var(--primary))]">{item.sku || '-'}</td>
                  <td className="py-1.5 pr-3 text-foreground/90">{item.product_name}</td>
                  <td className="py-1.5 pr-3 text-muted-foreground">{item.size || '-'}</td>
                  <td className="py-1.5 pr-3 text-muted-foreground">{item.color || '-'}</td>
                  <td className="py-1.5 pr-3 text-right font-bold text-foreground/90 whitespace-nowrap">{(item.qty || 0).toLocaleString('id-ID')} pcs</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  };

  const totals = form.items.reduce((t, it) => {
    const q = Number(it.qty) || 0;
    t.qty += q;
    t.rate += q * (Number(it.cmt_price_snapshot) || 0);
    t.selling += q * (Number(it.selling_price_snapshot) || 0);
    if (!(Number(it.cmt_price_snapshot) > 0)) t.noRate += 1;
    return t;
  }, { qty: 0, rate: 0, selling: 0, noRate: 0 });
  const autoNumber = numPolicy?.mode === 'auto' && !editData;

  return (
    <PageLayout
      title={isInternal ? 'PO Produksi Internal' : 'PO Maklon'}
      subtitle={isInternal
        ? 'Pesanan produksi untuk stok sendiri: model, varian, qty, dan upah jahit per baris.'
        : 'Pesanan jasa maklon per klien: artikel katalog, varian, qty, harga jasa, dan upah jahit.'}
      actions={canCreate ? <Button onClick={openCreate} data-testid="create-po-btn"><Plus className="w-4 h-4" /> Buat PO</Button> : null}
      filters={(
        <FilterChips
          value={filterStatus}
          onChange={setFilterStatus}
          testId="po-filter"
          ariaLabel="Penyaring status PO"
          options={['', ...STATUS_OPTIONS].map(s => ({ key: s, label: s || 'Semua' }))}
        />
      )}
    >
      <DataTable
        columns={columns}
        searchKeys={['po_number', 'customer_name']}
        expandedRow={expandedRowRender}
        storageKey="productionPOs"
        serverPagination={{
          fetcher: posFetcher,
          deps: [filterStatus, refetchKey],
          itemLabel: 'PO',
          initialSort: { key: 'created_at', dir: 'desc' },
          virtualize: true,
          virtualizeHeight: 650,
          estimatedRowHeight: 80,
        }}
        actions={
          <div className="flex items-center gap-2">
            {/* 2026-11-06 (T6): impor PO lama (/import-data) dihentikan — satu jalur impor PO berjalan saat
                cutoff lewat Data Transfer (pratinjau per baris; hanya admin/owner yang melihat tombolnya). */}
            <ImportExportPanel importType={null} exportType="production-pos" exportFilters={{ status: filterStatus }} />
            <ImportExportToolbar collectionKey="po_berjalan" label="PO berjalan saat cutoff"
              importLabel="Impor PO berjalan" size="default" onImported={() => refetchPOs()} />
          </div>
        }
      />

      {/* Form PO — K12 (7 Nov 2026): SATU bentuk untuk PO internal & maklon.
          Urutan bagian: kepala → baris → aksesoris → total. */}
      {showModal && (
        <Modal title={editData ? `Ubah PO ${editData.po_number}` : (isInternal ? 'Buat PO produksi internal' : 'Buat PO maklon')} onClose={() => { setShowModal(false); setFormError(null); }} size="xl">
          <form onSubmit={handleSubmit} className="space-y-4" data-testid="po-form" data-business-type={bizKey}>
            {formError && (
              <Notice tone="danger" icon={AlertTriangle} testId="po-form-error"
                action={<Button type="button" size="icon-sm" variant="ghost" onClick={() => setFormError(null)} className="text-[hsl(var(--destructive))]" title="Tutup pesan" aria-label="Tutup pesan"><X className="w-3.5 h-3.5" /></Button>}>
                {formError.text}
              </Notice>
            )}
            {rateLocked && (
              <Notice tone="warning" icon={Lock} testId="po-rate-locked">{editData.rate_lock.message}</Notice>
            )}
            {editData && (
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <StatusBadge status={editData.status} />
                <span>Status diubah lewat tombol aksi di detail PO. Baris yang sudah dikirim/diproduksi tidak bisa
                  diganti produknya, dan qty-nya tidak bisa di bawah jumlah yang sudah dikirim.</span>
              </div>
            )}

            {/* 1 · Kepala */}
            <section className="space-y-2" data-testid="po-form-header">
              <SectionTitle>Kepala PO</SectionTitle>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <Field label="Jenis PO">
                  <div className="h-9 flex items-center gap-2 text-sm" data-testid="po-form-type">
                    <BizBadge type={bizKey} size="xs" />
                    <span className="text-foreground/80">{isInternal ? 'Produksi untuk stok sendiri' : 'Jasa jahit untuk klien maklon'}</span>
                  </div>
                </Field>
                <Field label="Nomor PO" required={!autoNumber}
                  hint={autoNumber
                    ? `Dibuat sistem saat disimpan (pola ${numPolicy.format}). Ubah ke manual di Administrasi Sistem → Penomoran Dokumen.`
                    : (numPolicy?.format && !editData ? `Wajib mengikuti pola ${numPolicy.format} — contoh ${numPolicy.contoh}.` : null)}>
                  {autoNumber ? (
                    <GlassInput readOnly disabled data-testid="po-number-auto" className="tabular-nums"
                      value={numPolicy.nomor_berikutnya || numPolicy.contoh || 'dibuat otomatis'} />
                  ) : (
                    <GlassInput required data-testid="po-number-input" className="tabular-nums"
                      value={form.po_number} onChange={e => setForm({ ...form, po_number: e.target.value })}
                      placeholder={numPolicy?.contoh || 'PO-2026-001'} />
                  )}
                </Field>
                {isInternal ? (
                  <Field label="Tujuan barang jadi">
                    <GlassInput data-testid="po-customer-input" value={form.customer_name}
                      onChange={e => setForm({ ...form, customer_name: e.target.value })} placeholder="Gudang FG Sendiri" />
                  </Field>
                ) : (
                  <Field label="Buyer (klien maklon)" required>
                    <SearchableSelect
                      options={buyers.map(b => ({ value: b.id, label: b.buyer_name, sub: b.buyer_code }))}
                      value={form.buyer_id}
                      onChange={val => {
                        const buyer = buyers.find(b => b.id === val);
                        setForm(f => ({ ...f, buyer_id: val, customer_name: buyer?.buyer_name || '',
                          items: f.items.map(it => ({ ...it, catalog_item_id: '', product_name: '', sku: '', size: '', color: '', maklon_variant_id: '', cmt_price_snapshot: '', selling_price_snapshot: '', __typed: false, __sug: null })) }));
                        fetchCatalog(val);
                      }}
                      placeholder="Pilih buyer"
                      disabled={!!editData && editData.status !== 'Draft'}
                      data-testid="po-buyer-select"
                    />
                  </Field>
                )}
                <Field label="Penjahit (CMT)" hint="Boleh diisi belakangan — saat Kirim Material CMT. Upah jahit diusulkan per penjahit.">
                  <SearchableSelect
                    options={vendors.map(v => ({ value: v.id, label: v.garment_name, sub: v.garment_code }))}
                    value={form.vendor_id}
                    onChange={val => { if (val !== form.vendor_id) changeVendor(val); }}
                    placeholder="Pilih penjahit"
                    data-testid="po-vendor-select"
                  />
                </Field>
                <Field label="Tanggal PO">
                  <GlassInput type="date" value={form.po_date} onChange={e => setForm({ ...form, po_date: e.target.value })} data-testid="po-date" />
                </Field>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Tenggat produksi">
                    <GlassInput type="date" value={form.deadline} onChange={e => setForm({ ...form, deadline: e.target.value })} data-testid="po-deadline" />
                  </Field>
                  <Field label="Tenggat kirim">
                    <GlassInput type="date" value={form.delivery_deadline} onChange={e => setForm({ ...form, delivery_deadline: e.target.value })} data-testid="po-delivery-deadline" />
                  </Field>
                </div>
              </div>
            </section>

            {/* 2 · Baris produk */}
            <section className="space-y-2" data-testid="po-form-lines">
              <SectionTitle aside={(
                <Button type="button" variant="outline" size="sm" onClick={addItem} data-testid="po-add-line">
                  <Plus className="w-3.5 h-3.5" /> Tambah item
                </Button>
              )}>Baris produk <span className="text-[hsl(var(--destructive))]">*</span></SectionTitle>
              {form.items.length === 0 && (
                <p className="text-sm text-muted-foreground text-center py-3 border border-dashed border-border rounded-lg">
                  Klik "Tambah item" untuk menambahkan produk ke PO.
                </p>
              )}
              {form.items.map((item, idx) => {
                const hasShipments = !!item.__has_shipments;
                const minQty = item.__min_qty || 0;
                const maklonCat = !isInternal ? catalogItems.find(c => c.id === item.catalog_item_id) : null;
                const maklonVariants = (maklonCat?.variants || []).filter(v => v.active !== false);
                // Ukuran/warna/SKU diketik hanya untuk artikel maklon tanpa varian ber-SKU; selain itu ikut varian
                // (dulu ditampilkan lagi sebagai kotak terkunci + "SKU terpilih" → SKU tampil 3 kali).
                const manualVariant = !isInternal && !!item.catalog_item_id && maklonVariants.length === 0;
                const qty = Number(item.qty) || 0;
                const rate = Number(item.cmt_price_snapshot) || 0;
                const sug = item.__sug;
                const sugDiffers = sug && Number(sug.rate) > 0 && Number(sug.rate) !== rate;
                return (
                  <GlassCard key={item.__key || idx} className={`p-3 space-y-2 ${formError?.itemIdx === idx ? 'ring-1 ring-[hsl(var(--destructive)/0.6)]' : hasShipments ? 'ring-1 ring-[hsl(var(--warning)/0.5)]' : ''}`} data-testid={`po-item-row-${idx}`}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-semibold text-muted-foreground">
                        Baris #{idx + 1}
                        {hasShipments && <span className="ml-2 text-[hsl(var(--warning))]">sudah dikirim — qty minimal {minQty}</span>}
                      </span>
                      {hasShipments ? (
                        <span className="text-xs text-muted-foreground" title="Tidak dapat dihapus karena sudah ada kiriman/produksi">Tidak dapat dihapus</span>
                      ) : (
                        <Button type="button" variant="ghost" size="icon-sm" onClick={() => removeItem(idx)} className="text-[hsl(var(--destructive))]"
                          title="Hapus baris" aria-label="Hapus baris" data-testid={`po-item-${idx}-remove`}><X className="w-4 h-4" /></Button>
                      )}
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      {isInternal ? (
                        <Field label="Model produk" required>
                          <SearchableSelect
                            options={models
                              // 2026-11-07: model non-aktif tidak ditawarkan (server mengirim semua model) — kecuali
                              // yang sudah tersimpan di baris ini supaya PO lama tetap terbaca.
                              .filter(m => m.active !== false || m.id === item.model_id)
                              .map(m => ({ value: m.id, label: m.name, sub: m.code }))}
                            value={item.model_id}
                            onChange={val => updateItem(idx, 'model_id', val)}
                            placeholder="Pilih model"
                            required
                            disabled={hasShipments}
                            data-testid={`po-item-${idx}-model`}
                          />
                        </Field>
                      ) : (
                        <Field label="Artikel katalog buyer" required
                          hint={maklonCat && ((maklonCat.color_options || []).length || (maklonCat.size_options || []).length)
                            ? `Warna: ${(maklonCat.color_options || []).join(', ') || '-'} · Ukuran: ${(maklonCat.size_options || []).join(', ') || '-'}` : null}>
                          <SearchableSelect
                            options={catalogItems.map(c => ({ value: c.id, label: c.product_name, sub: c.artikel_code }))}
                            value={item.catalog_item_id}
                            onChange={val => updateItem(idx, 'catalog_item_id', val)}
                            placeholder={form.buyer_id ? 'Pilih artikel katalog buyer' : 'Pilih buyer dulu'}
                            required
                            disabled={!form.buyer_id || hasShipments}
                            data-testid={`po-item-${idx}-catalog`}
                          />
                        </Field>
                      )}
                      {/* Varian: label warna · ukuran, SKU satu kali (baris kedua pilihan). */}
                      {isInternal ? (
                        <Field label="Varian (warna · ukuran · SKU)" required>
                          <SearchableSelect
                            options={(rahazaVariants[item.model_id] || []).map(v => ({
                              value: v.id, label: `${v.color_name || '-'} · ${v.size_code || '-'}`, sub: v.sku,
                            }))}
                            value={item.rahaza_variant_id}
                            onChange={val => updateItem(idx, 'rahaza_variant_id', val)}
                            placeholder={item.model_id ? 'Pilih varian' : 'Pilih model dulu'}
                            required
                            disabled={!item.model_id || hasShipments}
                            data-testid={`po-item-${idx}-variant`}
                          />
                          {item.model_id && (rahazaVariants[item.model_id] || []).length === 0 && (
                            <p className="text-[11px] text-[hsl(var(--warning))] mt-1">Model ini belum punya varian — buat di Master Produk → tab Varian.</p>
                          )}
                        </Field>
                      ) : (
                        <Field label="Varian (warna · ukuran · SKU)" required={maklonVariants.length > 0}>
                          {maklonVariants.length > 0 || !item.catalog_item_id ? (
                            <SearchableSelect
                              options={maklonVariants.map(v => ({ value: v.sku, label: `${v.color || '-'} · ${v.size || '-'}`, sub: v.sku }))}
                              value={item.sku}
                              onChange={val => updateItem(idx, 'maklon_variant_sku', val)}
                              placeholder={item.catalog_item_id ? 'Pilih varian' : 'Pilih artikel dulu'}
                              required
                              disabled={!item.catalog_item_id || hasShipments}
                              data-testid={`po-item-${idx}-variant`}
                            />
                          ) : (
                            <p className="text-[11px] text-[hsl(var(--warning))] h-9 flex items-center">Artikel ini belum punya varian ber-SKU — isi ukuran, warna, dan SKU di bawah.</p>
                          )}
                        </Field>
                      )}
                    </div>
                    {!isInternal && (
                      <Field label="Kode artikel buyer (boleh beda per varian)">
                        <GlassInput className="tabular-nums" value={item.buyer_ref_code || ''} onChange={e => updateItem(idx, 'buyer_ref_code', e.target.value)}
                          placeholder="kode artikel buyer" disabled={hasShipments} data-testid={`po-item-${idx}-buyer-ref`} />
                      </Field>
                    )}
                    {manualVariant && (
                      <div className="grid grid-cols-3 gap-2">
                        <Field label="Ukuran"><GlassInput value={item.size} onChange={e => updateItem(idx, 'size', e.target.value)} placeholder="M" disabled={hasShipments} /></Field>
                        <Field label="Warna"><GlassInput value={item.color} onChange={e => updateItem(idx, 'color', e.target.value)} placeholder="Hitam" disabled={hasShipments} /></Field>
                        <Field label="SKU"><GlassInput className="tabular-nums" value={item.sku} onChange={e => updateItem(idx, 'sku', e.target.value)} placeholder="ART-HTM-M" disabled={hasShipments} /></Field>
                      </div>
                    )}
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                      <Field label={hasShipments ? `Qty (min ${minQty})` : 'Qty'} required>
                        <GlassInput required type="number" min={hasShipments ? minQty : 1} value={item.qty}
                          onChange={e => updateItem(idx, 'qty', e.target.value)} placeholder="100" data-testid={`po-item-${idx}-qty`} />
                      </Field>
                      <Field label="No. seri / batch" required>
                        <GlassInput required className="tabular-nums" value={item.serial_number || ''}
                          onChange={e => handleSerialChange(idx, e.target.value)} placeholder="SN-2026-001" data-testid={`po-item-serial-${idx}`} />
                      </Field>
                      <Field label="Upah jahit per pcs (Rp)" className="col-span-2 sm:col-span-1">
                        <MoneyInput glass value={item.cmt_price_snapshot} disabled={rateLocked}
                          onChange={e => updateItem(idx, 'cmt_price_snapshot', e.target.value)}
                          placeholder="0" data-testid={`po-item-${idx}-rate`} />
                      </Field>
                      {!isInternal && (
                        <Field label="Harga jasa ke klien (Rp)" className="col-span-2 sm:col-span-1">
                          <MoneyInput glass value={item.selling_price_snapshot}
                            onChange={e => updateItem(idx, 'selling_price_snapshot', e.target.value)}
                            placeholder="85.000" data-testid={`po-item-${idx}-selling`} />
                        </Field>
                      )}
                    </div>
                    {(() => {
                      const cur = (item.serial_number || '').trim().toUpperCase().replace(/\s+/g, ' ');
                      if (!cur) return null;
                      const inFormDup = form.items.some((o, j) => j !== idx && (o.serial_number || '').trim().toUpperCase().replace(/\s+/g, ' ') === cur);
                      const chk = serialChecks[idx];
                      if (chk?.loading) {
                        return <p className="text-[11px] text-muted-foreground inline-flex items-center gap-1"><Loader2 size={10} className="animate-spin" /> Mengecek nomor seri…</p>;
                      }
                      const dbUsages = (chk && chk.usages) || [];
                      if (inFormDup || dbUsages.length > 0) {
                        return (
                          <p className="text-[11px] text-[hsl(var(--destructive))] flex items-start gap-1" data-testid={`po-item-serial-warn-${idx}`}>
                            <AlertTriangle size={11} className="mt-px flex-shrink-0" />
                            <span>
                              Nomor seri dobel.{inFormDup ? ' Sama dengan baris lain di PO ini.' : ''}
                              {dbUsages.length > 0 ? ` Sudah dipakai di ${dbUsages[0].po_number}${dbUsages.length > 1 ? ` +${dbUsages.length - 1} lagi` : ''}.` : ''}
                              <span className="text-muted-foreground"> Boleh lanjut — hanya peringatan.</span>
                            </span>
                          </p>
                        );
                      }
                      return chk && !chk.loading ? <p className="text-[11px] text-[hsl(var(--success))]">Nomor seri unik.</p> : null;
                    })()}
                    <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-[11px]">
                      <span className="text-muted-foreground" data-testid={`po-item-${idx}-rate-hint`} data-source={sug?.source || ''}>
                        {sug ? (
                          <>
                            {sugDiffers ? `Usulan ${rupiah(sug.rate)} — ` : (Number(sug.rate) > 0 ? 'Usulan: ' : '')}{sug.note}
                            {sugDiffers && !rateLocked && (
                              <Button type="button" variant="link" size="sm" className="h-auto p-0 ml-1 text-[11px]"
                                onClick={() => updateItem(idx, 'cmt_price_snapshot', sug.rate)} data-testid={`po-item-${idx}-rate-use`}>Pakai usulan</Button>
                            )}
                          </>
                        ) : (isInternal
                          ? (item.model_id ? 'Mencari usulan upah…' : 'Pilih model untuk melihat usulan upah.')
                          : (item.catalog_item_id ? 'Mencari usulan upah…' : 'Pilih artikel untuk melihat usulan upah.'))}
                      </span>
                      <span className="tabular-nums text-foreground/80" data-testid={`po-item-${idx}-rate-total`}>
                        Upah jahit baris: <b>{rupiah(rate * qty)}</b>
                        {!isInternal && <> · Nilai jasa: <b>{rupiah((Number(item.selling_price_snapshot) || 0) * qty)}</b></>}
                      </span>
                    </div>
                  </GlassCard>
                );
              })}
            </section>

            {/* 3 · Aksesoris — bagian yang sama untuk kedua jenis: dari BOM (otomatis) + tambahan di luar BOM */}
            <section className="space-y-2" data-testid="po-form-accessories">
              <SectionTitle aside={(
                <Button type="button" variant="outline" size="sm" onClick={addAccessoryItem} data-testid="po-add-accessory">
                  <Plus className="w-3.5 h-3.5" /> Tambah aksesoris
                </Button>
              )}>Aksesoris</SectionTitle>
              <div data-testid="po-bom-accessories-panel" className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground flex items-center gap-2">
                  Dari BOM (otomatis, tidak perlu diketik)
                  {bomAcc.loading && <span className="inline-flex items-center gap-1"><Loader2 className="w-3.5 h-3.5 animate-spin" /> menghitung…</span>}
                </p>
                {isInternal ? (
                  <p className="text-xs text-muted-foreground border border-dashed border-border rounded-lg px-3 py-2" data-testid="po-bom-acc-internal">
                    Dihitung dari BOM aktif tiap model × qty saat PO disimpan, lalu tampil di detail PO beserta posisi stoknya.
                  </p>
                ) : bomAcc.rows.length === 0 ? (
                  <p className="text-xs text-muted-foreground border border-dashed border-border rounded-lg px-3 py-2" data-testid="po-bom-acc-empty">
                    {bomAcc.loading
                      ? 'Menghitung kebutuhan aksesoris dari BOM…'
                      : 'Pilih artikel katalog dan isi qty — aksesoris muncul otomatis bila artikel itu punya template BOM aktif.'}
                  </p>
                ) : (
                  <div className="rounded-lg border border-border overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead className="bg-muted/40">
                        <tr>
                          <th className="text-left px-3 py-1.5 text-muted-foreground">Aksesoris</th>
                          <th className="text-left px-3 py-1.5 text-muted-foreground">Kode</th>
                          <th className="text-right px-3 py-1.5 text-muted-foreground">Kebutuhan</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border">
                        {bomAcc.rows.map((r, i) => (
                          <tr key={`${r.accessory_name}-${i}`} data-testid={`po-bom-acc-row-${i}`}>
                            <td className="px-3 py-1.5 text-foreground/90">
                              {r.accessory_name}
                              {r.unlinked && <span className="ml-1.5 text-[hsl(var(--destructive))] text-[10px] font-semibold">belum tertaut master</span>}
                            </td>
                            <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{r.accessory_code || '-'}</td>
                            <td className="px-3 py-1.5 text-right tabular-nums font-semibold">{Number(r.qty_needed || 0).toLocaleString('id-ID')} {r.unit || 'pcs'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <p className="px-3 py-1.5 text-[11px] text-muted-foreground">
                      Untuk {Number(bomAcc.total_pcs || 0).toLocaleString('id-ID')} pcs. Ditulis sistem saat PO disimpan — jangan ditambahkan lagi di bawah.
                    </p>
                  </div>
                )}
                {(bomAcc.warnings || []).length > 0 && (
                  <Notice tone="warning" icon={AlertTriangle} testId="po-bom-acc-warning">
                    <div className="space-y-0.5">{bomAcc.warnings.map((w, i) => <p key={i} className="text-[11px]">{w}</p>)}</div>
                  </Notice>
                )}
              </div>
              <p className="text-xs font-medium text-muted-foreground">Tambahan di luar BOM (opsional)</p>
              {(form.po_accessories || []).length === 0 && (
                <p className="text-xs text-muted-foreground border border-dashed border-border rounded-lg px-3 py-2">Klik "Tambah aksesoris" bila perlu aksesoris di luar BOM.</p>
              )}
              {(form.po_accessories || []).map((acc, idx) => (
                <div key={acc.id || idx} className="grid grid-cols-[1fr_auto] sm:grid-cols-[1fr_7rem_3rem_9rem_auto] items-center gap-2" data-testid={`po-acc-row-${idx}`}>
                  <SearchableSelect
                    options={accessories.map(a => ({ value: a.id, label: a.accessory_name || a.name, sub: a.accessory_code || a.code || a.category || '' }))}
                    value={acc.accessory_id}
                    onChange={val => updateAccessoryItem(idx, 'accessory_id', val)}
                    placeholder="Pilih aksesoris"
                  />
                  <Button type="button" variant="ghost" size="icon-sm" onClick={() => removeAccessoryItem(idx)} className="text-[hsl(var(--destructive))] sm:order-last"
                    title="Hapus aksesoris" aria-label="Hapus aksesoris"><X className="w-4 h-4" /></Button>
                  <GlassInput type="number" min="0" step="any" value={acc.qty_needed} onChange={e => updateAccessoryItem(idx, 'qty_needed', e.target.value)} placeholder="Qty" />
                  <span className="text-xs text-muted-foreground">{acc.unit || 'pcs'}</span>
                  <GlassInput className="col-span-2 sm:col-span-1" value={acc.notes || ''} onChange={e => updateAccessoryItem(idx, 'notes', e.target.value)} placeholder="Catatan" />
                </div>
              ))}
            </section>

            {/* 4 · Total — blok yang sama untuk kedua jenis; nilai jasa ke klien hanya maklon */}
            <section className="space-y-2" data-testid="po-form-totals">
              <SectionTitle>Total</SectionTitle>
              <div className={`grid grid-cols-2 ${isInternal ? 'sm:grid-cols-3' : 'sm:grid-cols-4'} gap-2`}>
                <StatTile label="Baris" value={form.items.length.toLocaleString('id-ID')} testId="po-total-lines" />
                <StatTile label="Total qty" value={`${totals.qty.toLocaleString('id-ID')} pcs`} testId="po-total-qty" />
                <StatTile label="Total upah jahit" value={rupiah(totals.rate)} testId="po-total-rate"
                  sub={totals.noRate ? `${totals.noRate} baris belum berupah` : 'semua baris berupah'} subTone={totals.noRate ? 'warning' : undefined} />
                {!isInternal && <StatTile label="Total harga jasa" value={rupiah(totals.selling)} testId="po-total-selling" />}
              </div>
            </section>

            <Field label="Catatan">
              <textarea rows="2" className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-transparent focus:outline-none focus:ring-2 focus:ring-[hsl(var(--primary)/0.35)]" value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} data-testid="po-notes" />
            </Field>
            <div className="flex gap-3">
              <Button type="button" variant="outline" onClick={() => setShowModal(false)} className="flex-1">Batal</Button>
              <Button type="submit" className="flex-1" data-testid="po-submit">{editData ? 'Simpan perubahan' : 'Buat PO'}</Button>
            </div>
          </form>
        </Modal>
      )}

      {/* Manual Close PO Modal */}
      {showCloseModal && closeTargetPO && (
        <Modal title={`Tutup PO Manual: ${closeTargetPO.po_number}`} onClose={() => setShowCloseModal(false)}>
          <form onSubmit={handleClosePO} className="space-y-4">
            <Notice tone="warning" icon={AlertTriangle}>
              Qty diperiksa per ukuran. Semua terpenuhi ⇒ PO <strong>Ditutup</strong>; ada ukuran yang kurang ⇒ pilih alasan dan PO
              menjadi <strong>Ditutup kurang</strong>. PO yang ditutup terkunci dari kiriman dan perubahan.
            </Notice>
            <div>
              <label className="block text-sm font-medium text-foreground/90 mb-1">Alasan penutupan</label>
              <SmartNativeSelect className="w-full" value={closeForm.close_reason} onChange={e => setCloseForm({...closeForm, close_reason: e.target.value, closed_reason: e.target.value})}>
                {CLOSE_REASONS.map(r => <option key={r} value={r}>{CLOSE_REASON_LABELS[r] || r}</option>)}
              </SmartNativeSelect>
            </div>
            <div>
              <label className="block text-sm font-medium text-foreground/90 mb-1">Keterangan Tambahan</label>
              <textarea rows="3" className="w-full border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--primary)/0.35)]" value={closeForm.close_notes} onChange={e => setCloseForm({...closeForm, close_notes: e.target.value})} placeholder="Jelaskan detail alasan penutupan PO..." />
            </div>
            <div className="flex gap-3">
              <Button type="submit" className="flex-1">Tutup PO</Button>
              <Button type="button" variant="outline" onClick={() => setShowCloseModal(false)} className="flex-1">Batal</Button>
            </div>
          </form>
        </Modal>
      )}

      {/* Detail Modal */}
      {showDetail && detailData && (
        <Modal title={`Detail PO: ${detailData.po_number}`} onClose={() => setShowDetail(false)} size="xl">
          <div className="space-y-4">
            {isInternal && costCheck && costCheck.items_with_issues > 0 && (
              <div className="bg-[hsl(var(--warning)/0.1)] border border-[hsl(var(--warning)/0.35)]  rounded-lg p-3" data-testid="po-cost-warning">
                <p className="text-sm font-semibold text-[hsl(var(--warning))] flex items-center gap-2"><AlertTriangle className="w-4 h-4" />Harga bahan / upah belum lengkap pada {costCheck.items_with_issues} item — lapisan HPP barang jadi akan bernilai terlalu rendah (bahkan nol).</p>
                <ul className="mt-1.5 text-xs text-[hsl(var(--warning))] space-y-0.5">
                  {costCheck.items.filter(i => i.issues.length).map(i => (
                    <li key={i.po_item_id} data-testid={`po-cost-issue-${i.sku}`}><span className="tabular-nums">{i.sku || i.product_name}</span>: {i.issues.join('; ')} — bahan {fmt(i.material_cost)}/pcs · jahit {fmt(i.sewing_cost)}/pcs</li>
                  ))}
                </ul>
                <p className="text-[11px] text-[hsl(var(--warning))] mt-1.5">Isi upah jahit per pcs di form PO (tombol Ubah) — angkanya sama dengan menu <b>Biaya Jahit</b> — dan harga bahan di master material/BOM sebelum barang jadi diterima dari CMT.</p>
              </div>
            )}
            {isInternal && costCheck && costCheck.ok && (
              <p className="text-xs text-[hsl(var(--success))] " data-testid="po-cost-ok">Harga bahan & upah semua item terisi — estimasi nilai batch {fmt(costCheck.estimated_batch_value)}.</p>
            )}
            {/* PDF Export + Quick Complete */}
            <div className="flex justify-between items-center flex-wrap gap-2">
              {/* Quick Complete button (only for non-completed/closed POs) */}
              {canEdit && !['Completed', 'Closed'].includes(detailData.status) && (
                <button
                  onClick={() => { setShowDetail(false); setQuickCompletePO(detailData); }}
                  data-testid="detail-quick-complete-btn"
                  className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-[hsl(var(--primary)/0.1)] to-[hsl(var(--primary)/0.1)] text-white rounded-lg text-sm font-bold hover:from-[hsl(var(--primary)/0.1)] hover:to-[hsl(var(--primary)/0.1)] shadow-md hover:shadow-lg transition-all"
                >
                  <Zap className="w-4 h-4" />
                  Selesaikan cepat
                </button>
              )}
              <button
                onClick={() => setSppPickerOpen(true)}
                data-testid="spp-export-pdf-btn"
                className="flex items-center gap-2 px-4 py-2 bg-[hsl(var(--destructive))] text-white rounded-lg text-sm hover:bg-[hsl(var(--destructive)/0.9)] font-medium">
                Unduh PDF (SPP) — pilih kolom
              </button>
            </div>
            {/* FASE 5 DA: Aksi status dinamis dari allowed_next backend */}
            {canEdit && (Array.isArray(detailData.allowed_next) && detailData.allowed_next.length > 0 || detailData.can_close) && (
              <div data-testid="po-detail-actions" className="flex items-center flex-wrap gap-2 bg-[hsl(var(--primary)/0.1)] border border-[hsl(var(--primary)/0.35)]  rounded-xl p-3">
                <span className="text-xs font-semibold text-[hsl(var(--primary))] uppercase tracking-wide mr-1">Aksi:</span>
                {(detailData.allowed_next || []).map(ns => (
                  <button key={ns} data-testid={`po-action-${ns.toLowerCase().replace(/\s+/g, '-')}`}
                    onClick={() => transitionStatus(detailData.id, ns)}
                    className="px-3 py-1.5 rounded-lg text-sm font-semibold bg-[hsl(var(--primary))] text-white hover:bg-[hsl(var(--primary)/0.9)] transition-colors">
                    → {ns}
                  </button>
                ))}
                {detailData.can_close && (
                  <button data-testid="po-action-close"
                    onClick={() => { setShowDetail(false); setCloseTargetPO(detailData); setCloseForm({ close_reason: CLOSE_REASONS[0], close_notes: '' }); setShowCloseModal(true); }}
                    className="px-3 py-1.5 rounded-lg text-sm font-semibold border border-[hsl(var(--warning)/0.35)] text-[hsl(var(--warning))] hover:bg-[hsl(var(--warning)/0.1)] transition-colors">
                    Tutup PO
                  </button>
                )}
              </div>
            )}
            {/* Workflow Indicator */}
            <div className="bg-muted/40 rounded-xl p-4">
              <p className="text-xs font-semibold text-muted-foreground mb-3 uppercase tracking-wide">Status Workflow</p>
              <POWorkflowIndicator status={detailData.status} />
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {[{l:'No. PO',v:<span className="font-bold text-[hsl(var(--primary))]">{detailData.po_number}</span>},
                {l:isInternal ? 'Tujuan barang jadi' : 'Buyer',v:detailData.customer_name},
                {l:'Penjahit (CMT)',v:detailData.vendor_name||'Belum dipilih'},
                {l:'Status',v:<StatusBadge status={detailData.status} />},
                {l:'Tgl. PO',v:fmtDate(detailData.po_date)},
                {l:'Tenggat produksi',v:fmtDate(detailData.deadline)},
                {l:'Tenggat kirim',v:fmtDate(detailData.delivery_deadline)},
                {l:'Dibuat',v:detailData.created_by}
              ].map(it => <div key={it.l} className="bg-muted/40 rounded-lg p-3"><p className="text-xs text-muted-foreground">{it.l}</p><div className="font-medium text-sm mt-0.5">{it.v}</div></div>)}
            </div>
            {detailData.close_reason && (
              <div className="bg-[hsl(var(--warning)/0.1)] border border-[hsl(var(--warning)/0.35)] rounded-lg p-3">
                <p className="text-sm font-semibold text-[hsl(var(--warning))]">Alasan Penutupan: {CLOSE_REASON_LABELS[detailData.close_reason] || detailData.close_reason}</p>
                {detailData.close_notes && <p className="text-xs text-[hsl(var(--warning))] mt-1">{detailData.close_notes}</p>}
                <p className="text-xs text-[hsl(var(--warning))] mt-1">Ditutup oleh: {detailData.closed_by} pada {fmtDate(detailData.closed_at)}</p>
              </div>
            )}
            {detailData.items?.length > 0 && (
              <div className="space-y-3">
                <p className="text-sm font-semibold text-foreground">Baris produk ({detailData.items.length})</p>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    {/* K12: kolom sama untuk kedua jenis PO; harga jasa & margin hanya maklon */}
                    <thead><tr className="bg-muted">
                      <th className="text-left px-3 py-2 text-xs text-muted-foreground">Produk</th>
                      <th className="text-left px-3 py-2 text-xs text-muted-foreground">SKU</th>
                      <th className="text-left px-3 py-2 text-xs text-muted-foreground">No. seri</th>
                      <th className="text-left px-3 py-2 text-xs text-muted-foreground">Ukuran / warna</th>
                      <th className="text-right px-3 py-2 text-xs text-muted-foreground">Qty</th>
                      <th className="text-right px-3 py-2 text-xs text-muted-foreground">Upah jahit / pcs</th>
                      <th className="text-right px-3 py-2 text-xs text-muted-foreground">Total upah</th>
                      {!isInternal && <th className="text-right px-3 py-2 text-xs text-muted-foreground">Harga jasa / pcs</th>}
                      {!isInternal && <th className="text-right px-3 py-2 text-xs text-muted-foreground">Margin / pcs</th>}
                    </tr></thead>
                    <tbody>{detailData.items.map(it => {
                      const marginPcs = (it.selling_price_snapshot || 0) - (it.cmt_price_snapshot || 0);
                      return (
                        <tr key={it.id} className="border-t border-border/60" data-testid={`po-detail-line-${it.sku || it.id}`}>
                          <td className="px-3 py-2">{it.product_name}</td>
                          <td className="px-3 py-2 tabular-nums text-xs">{it.sku || '-'}</td>
                          <td className="px-3 py-2 tabular-nums text-xs">{it.serial_number || <span className="text-muted-foreground/50">—</span>}</td>
                          <td className="px-3 py-2 text-xs">{it.size || '-'} / {it.color || '-'}</td>
                          <td className="px-3 py-2 text-right tabular-nums font-semibold">{(it.qty || 0).toLocaleString('id-ID')}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{fmt(it.cmt_price_snapshot)}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{fmt((it.qty || 0) * (it.cmt_price_snapshot || 0))}</td>
                          {!isInternal && <td className="px-3 py-2 text-right tabular-nums">{fmt(it.selling_price_snapshot)}</td>}
                          {!isInternal && <td className={`px-3 py-2 text-right tabular-nums ${marginPcs < 0 ? 'text-[hsl(var(--destructive))]' : ''}`}>{fmt(marginPcs)}</td>}
                        </tr>
                      );
                    })}</tbody>
                    <tfoot><tr className="bg-muted/40 font-semibold border-t-2 border-border">
                      <td className="px-3 py-2" colSpan={4}>Total</td>
                      <td className="px-3 py-2 text-right tabular-nums">{detailData.items.reduce((s,i)=>s+(i.qty||0),0).toLocaleString('id-ID')} pcs</td>
                      <td className="px-3 py-2" />
                      <td className="px-3 py-2 text-right tabular-nums" data-testid="po-detail-total-rate">{fmt(detailData.items.reduce((s,i)=>s+(i.qty||0)*(i.cmt_price_snapshot||0),0))}</td>
                      {!isInternal && <td className="px-3 py-2 text-right tabular-nums">{fmt(detailData.items.reduce((s,i)=>s+(i.qty||0)*(i.selling_price_snapshot||0),0))}</td>}
                      {!isInternal && <td className="px-3 py-2 text-right tabular-nums">{fmt(detailData.items.reduce((s,i)=>s+(i.qty||0)*((i.selling_price_snapshot||0)-(i.cmt_price_snapshot||0)),0))}</td>}
                    </tr></tfoot>
                  </table>
                </div>

                {/* 2026-11-02 (K16): PO INTERNAL tidak punya harga jual — "Est. Gross Margin"
                    = 0 − CMT selalu negatif (−150.000) dan menyesatkan. Tampilkan HPP batch
                    nyata (bahan BOM warna varian + jahit SPK) dari /cost-check. */}
                {isInternal && (
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3" data-testid="po-internal-hpp">
                    <StatTile label="Bahan (BOM warna varian)" accent="warning" sub="Harga bahan × qty"
                      value={fmt((costCheck?.items || []).reduce((s, i) => s + (i.material_cost || 0) * (Number(i.qty) || 0), 0))} />
                    <StatTile label="Upah jahit" accent="warning" sub="Upah jahit per pcs × qty"
                      value={fmt(detailData.items.reduce((s,i)=>s+(i.qty||0)*(i.cmt_price_snapshot||0),0))} />
                    <StatTile label="Estimasi HPP batch" accent="primary" sub="PO internal = stok sendiri; margin lahir saat barang terjual"
                      value={<span data-testid="po-internal-hpp-batch">{costCheck ? fmt(costCheck.estimated_batch_value) : '…'}</span>} />
                  </div>
                )}
                {/* Financial Summary */}
                {!isInternal && (() => {
                  const totalSales = detailData.items.reduce((s,i)=>s+(i.qty||0)*(i.selling_price_snapshot||0),0);
                  const totalCMT = detailData.items.reduce((s,i)=>s+(i.qty||0)*(i.cmt_price_snapshot||0),0);
                  const grossMargin = totalSales - totalCMT;
                  const marginPct = totalSales > 0 ? Math.round((grossMargin / totalSales) * 100) : 0;
                  return (
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                      <StatTile label="Total harga jasa" accent="success" sub="Harga jasa ke klien × qty" value={fmt(totalSales)} />
                      <StatTile label="Total upah jahit" accent="warning" sub="Upah jahit per pcs × qty" value={fmt(totalCMT)} />
                      <StatTile label="Perkiraan laba kotor" accent={grossMargin >= 0 ? 'primary' : 'danger'}
                        sub={`${marginPct}% dari nilai penjualan`} value={fmt(grossMargin)} />
                    </div>
                  );
                })()}
              </div>
            )}
            {/* ── ACC-1: Kebutuhan Aksesoris (BOM explode + posisi stok + kekurangan) ── */}
            <div className="space-y-3" data-testid="po-accessory-requirements">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h4 className="font-semibold text-foreground/90 flex items-center gap-2">
                  <span className="w-5 h-5 bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))] rounded-full flex items-center justify-center text-xs font-bold">
                    {accReq?.requirements?.length ?? (detailData.po_accessories?.length || 0)}
                  </span>
                  Kebutuhan Aksesoris
                </h4>
                {accReq?.requirements?.length > 0 && (
                  <div className="flex items-center gap-2">
                    {accReq.summary?.shortage_lines > 0 ? (
                      <Button
                        size="sm"
                        onClick={() => createAccRequest(detailData.id, true)}
                        disabled={accReqCreating}
                        data-testid="po-acc-create-request-btn"
                      >
                        {accReqCreating ? 'Mengajukan...' : `Ajukan Pembelian (${accReq.summary.shortage_lines} kurang)`}
                      </Button>
                    ) : (
                      <span className="text-xs text-[hsl(var(--success))] font-medium">
                        Stok mencukupi — tidak perlu pembelian
                      </span>
                    )}
                  </div>
                )}
              </div>
              {/* 2026-11-06 (Tahap 2): kekurangan diajukan sebagai pembelian, stok yang ada keluar saat kirim */}
              {accReq?.requirements?.length > 0 && (
                <p className="text-xs text-muted-foreground" data-testid="po-acc-req-help">
                  Kekurangan aksesoris milik DA diajukan sebagai Permintaan Pengadaan yang tertaut ke PO ini, lalu
                  dibeli lewat PO dan diterima di Penerimaan Barang. Stok yang sudah ada dikeluarkan saat Kirim
                  Material CMT, jadi tidak diminta lagi. Aksesoris yang disediakan klien tidak ikut dibeli.
                </p>
              )}

              {accReqLoading && <p className="text-xs text-muted-foreground">Memuat kebutuhan aksesoris...</p>}
              {accReq?.error && (
                <p className="text-xs text-[hsl(var(--destructive))] ">{accReq.error}</p>
              )}

              {accReqMsg && (
                <Notice
                  testId="po-acc-req-message"
                  tone={accReqMsg.type === 'success' ? 'success' : 'danger'}
                  className="text-xs"
                >
                  {accReqMsg.text}
                </Notice>
              )}

              {!accReqLoading && accReq && !accReq.error && accReq.requirements.length === 0 && (
                <p className="text-xs text-muted-foreground/80 italic border border-dashed border-border rounded-lg py-3 px-3">
                  Belum ada kebutuhan aksesoris. Untuk PO internal, kebutuhan dihitung otomatis dari
                  <strong> BOM aktif</strong> tiap item (qty per pcs × qty order). Pastikan BOM berisi
                  baris aksesoris, lalu simpan ulang PO.
                </p>
              )}

              {accReq?.summary?.unlinked_lines > 0 && (
                <div className="text-xs bg-[hsl(var(--warning)/0.15)] border border-[hsl(var(--warning)/0.35)]  text-[hsl(var(--warning))]  rounded-lg px-3 py-2">
                  <strong>{accReq.summary.unlinked_lines} baris belum tertaut ke master material</strong> —
                  stoknya tidak bisa dicek dan tidak akan ikut dalam permintaan. Perbaiki di modul BOM
                  (pilih material dari master, atau tombol "Perbaiki Otomatis").
                </div>
              )}

              {accReq?.requirements?.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm" data-testid="po-acc-req-table">
                    <thead><tr className="bg-[hsl(var(--success)/0.1)] ">
                      <th className="text-left px-3 py-2 text-xs text-[hsl(var(--success))] font-semibold">#</th>
                      <th className="text-left px-3 py-2 text-xs text-[hsl(var(--success))] font-semibold">Aksesoris</th>
                      <th className="text-left px-3 py-2 text-xs text-[hsl(var(--success))] font-semibold">Sumber</th>
                      <th className="text-right px-3 py-2 text-xs text-[hsl(var(--success))] font-semibold">Dibutuhkan</th>
                      <th className="text-right px-3 py-2 text-xs text-[hsl(var(--success))] font-semibold">Sudah keluar</th>
                      <th className="text-right px-3 py-2 text-xs text-[hsl(var(--success))] font-semibold">Tersedia</th>
                      <th className="text-right px-3 py-2 text-xs text-[hsl(var(--success))] font-semibold">Kurang</th>
                      <th className="text-left px-3 py-2 text-xs text-[hsl(var(--success))] font-semibold">Status</th>
                    </tr></thead>
                    <tbody>{accReq.requirements.map((a, idx) => (
                      <tr key={a.id || idx} className="border-t border-[hsl(var(--success)/0.35)] hover:bg-[hsl(var(--success)/0.3)] "
                        data-testid={`po-acc-req-row-${idx}`}>
                        <td className="px-3 py-2 text-xs text-muted-foreground/70">{idx + 1}</td>
                        <td className="px-3 py-2">
                          <div className="font-medium text-foreground/90">{a.material_name || a.accessory_name}</div>
                          <div className="tabular-nums text-xs text-[hsl(var(--success))] ">{a.material_code || a.accessory_code || '-'}</div>
                        </td>
                        <td className="px-3 py-2 text-xs text-muted-foreground">
                          {a.source === 'bom_auto' ? 'BOM (otomatis)' : 'Manual'}
                        </td>
                        <td className="px-3 py-2 text-right font-bold text-foreground">
                          {(a.qty_needed || 0).toLocaleString('id-ID')} <span className="text-xs font-normal text-muted-foreground">{a.unit}</span>
                        </td>
                        <td className="px-3 py-2 text-right text-foreground/80">
                          {a.linked ? (a.issued || 0).toLocaleString('id-ID') : <span className="text-muted-foreground">-</span>}
                        </td>
                        <td className="px-3 py-2 text-right text-foreground/80">
                          {a.linked ? (a.available || 0).toLocaleString('id-ID') : <span className="text-muted-foreground">-</span>}
                        </td>
                        <td className={`px-3 py-2 text-right font-semibold ${a.shortage > 0 ? 'text-[hsl(var(--destructive))] ' : 'text-[hsl(var(--success))] '}`}>
                          {a.linked ? (a.shortage || 0).toLocaleString('id-ID') : '-'}
                        </td>
                        <td className="px-3 py-2 text-xs">
                          {a.status === 'ok' && <span className="px-2 py-0.5 rounded-full bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]  border border-[hsl(var(--success)/0.4)]">Cukup</span>}
                          {a.status === 'shortage' && <span className="px-2 py-0.5 rounded-full bg-[hsl(var(--destructive)/0.15)] text-[hsl(var(--destructive))]  border border-[hsl(var(--destructive)/0.4)]">Kurang</span>}
                          {a.status === 'unlinked' && <span className="px-2 py-0.5 rounded-full bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]  border border-[hsl(var(--warning)/0.4)]">Belum tertaut</span>}
                          {a.status === 'client' && <span className="px-2 py-0.5 rounded-full bg-muted text-muted-foreground border border-border">Disediakan klien</span>}
                        </td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              )}

              {accReq?.existing_requests?.length > 0 && (
                <div className="text-xs text-muted-foreground" data-testid="po-acc-existing-requests">
                  Permintaan Pengadaan aksesoris untuk PO ini:{' '}
                  {accReq.existing_requests.map(r => (
                    <span key={r.id} className="inline-block mr-2 px-2 py-0.5 rounded-full border border-border bg-muted/40 tabular-nums">
                      {r.request_code} · {r.status}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* File Attachments */}
            <FileAttachmentPanel
              entityType="production_po"
              entityId={detailData.id}
              userRole={userRole}
            />
          </div>
        </Modal>
      )}

      {confirmDelete && <ConfirmDialog title="Hapus Production PO?" message={`PO "${confirmDelete.po_number}" beserta semua work order dan progres akan dihapus permanen.`} onConfirm={handleDelete} onCancel={() => setConfirmDelete(null)} />}

      {/* Quick Complete Modal */}
      {quickCompletePO && (
        <QuickCompleteModal
          po={quickCompletePO}
          onClose={() => setQuickCompletePO(null)}
          onSuccess={() => { setQuickCompletePO(null); refetchPOs(); }}
        />
      )}
      {/* W2 — cetak SPP dengan kolom pilihan pemakai (Serial No dst.) */}
      {detailData && (
        <PdfColumnPicker
          docType="production-po"
          open={sppPickerOpen}
          onOpenChange={setSppPickerOpen}
          title={`Kolom PDF — SPP ${detailData.po_number || ''}`}
          hint="Centang kolom yang ingin tercetak pada tabel item SPP (mis. Serial No)."
          onConfirm={async (cols) => {
            try {
              const q = cols?.length ? `&cols=${encodeURIComponent(cols.join(','))}` : '';
              const res = await apiFetch(`/export-pdf?type=production-po&id=${detailData.id}${q}`);
              if (!res.ok) { toast.error('Gagal mengunduh PDF'); return; }
              const blob = await res.blob();
              const url = URL.createObjectURL(blob);
              const a = document.createElement('a');
              a.href = url; a.download = `SPP-${detailData.po_number}.pdf`; a.click();
              URL.revokeObjectURL(url);
            } catch (e) { toast.error('Gagal mengunduh PDF: ' + e.message); }
          }}
        />
      )}
    </PageLayout>
  );
}


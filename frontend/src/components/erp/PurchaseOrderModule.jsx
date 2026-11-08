/**
 * PurchaseOrderModule — Purchase Order (Portal Pengadaan).
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, penyaring satu baris, daftar = tabel (kartu ringkas di HP)
 * dengan paling banyak 2 tombol aksi + menu "Lainnya", detail = popup, form = FormPopup (buat PO, ubah harga,
 * setujui, impor), konfirmasi ajukan/tolak/batalkan/hapus lewat confirmDialog, tanggal lewat DatePicker,
 * unduh Excel/CSV. Endpoint, isian, aturan, dan hak akses tidak berubah.
 */
import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { materialOptionLabel } from '@/lib/materialFields';
import {
  Plus, Eye, Trash2, CheckCircle2, XCircle, AlertTriangle, Send, TruckIcon, Upload, Download, Tag,
  MoreHorizontal, RefreshCw, Package,
} from 'lucide-react';
import { MoneyInput } from '@/components/ui/money-input';
import { todayWIB } from '@/lib/waktu';
import { formatDateID, formatDateTimeID } from '@/lib/format';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import DatePicker from '@/components/ui/date-picker';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { toast } from 'sonner';
import * as XLSX from 'xlsx';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';
import DocNumberField, { useDocNumberPolicy, docNumberPayload } from './docnum/DocNumberField';

const STATUS_META = {
  draft:               { label: 'Draf',                tone: 'muted' },
  pending_approval:    { label: 'Menunggu persetujuan', tone: 'warning' },
  approved:            { label: 'Disetujui',           tone: 'success' },
  partially_received:  { label: 'Diterima sebagian',   tone: 'info' },
  fully_received:      { label: 'Diterima penuh',      tone: 'success' },
  rejected:            { label: 'Ditolak',             tone: 'danger' },
  cancelled:           { label: 'Dibatalkan',          tone: 'muted' },
};

function POStatusBadge({ status }) {
  const s = STATUS_META[status] || STATUS_META.draft;
  return <StatusBadge status={status} label={s.label} tone={s.tone} />;
}

const GR_STATUS = {
  draft: { label: 'Draf', tone: 'muted' },
  received: { label: 'Diterima', tone: 'success' },
  completed: { label: 'Selesai', tone: 'success' },
  partial_received: { label: 'Diterima sebagian', tone: 'warning' },
};

const fmtTgl = (v) => formatDateID(v);
const fmtRpNum = (v, max = 0) => `Rp ${Number(v || 0).toLocaleString('id-ID', { maximumFractionDigits: max })}`;
const fmtQty = (v) => Number(v || 0).toLocaleString('id-ID', { maximumFractionDigits: 4 });

export default function PurchaseOrderModule({ token, onNavigate }) {
  const [list, setList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [materials, setMaterials] = useState([]);
  const [suppliers, setSuppliers] = useState([]);
  const [uomMap, setUomMap] = useState({});      // material_id -> {base_unit, units[]}
  const [priceHint, setPriceHint] = useState({}); // item_id -> {price, uom, supplier_name}
  const [filterStatus, setFilterStatus] = useState('');
  const [filterSupplier, setFilterSupplier] = useState('');
  const [createModal, setCreateModal] = useState(false);
  const [detailModal, setDetailModal] = useState(false);
  const [approveModal, setApproveModal] = useState(false);
  const [selectedPO, setSelectedPO] = useState(null);
  const [approveNote, setApproveNote] = useState('');
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState('');
  // 2026-11-06 (Tahap 2): ubah harga baris PO yang sudah keluar dari draf — Keuangan saja, alasan wajib
  const [priceEdit, setPriceEdit] = useState(null);   // { item, value, reason }
  // SESI #19 — kebijakan penomoran PO Pembelian (Otomatis/Manual) dari Administrasi
  // Sistem → Penomoran Dokumen. PO adalah komitmen UANG: nomor bebas tidak bisa
  // diurutkan maupun dicari di arsip, jadi mode manual pun wajib mengikuti pola.
  const numPolicy = useDocNumberPolicy('rahaza_purchase_orders.po_number', token);
  const [poNumber, setPoNumber] = useState('');
  const [bulkModal, setBulkModal] = useState(false);
  const [bulkRows, setBulkRows] = useState([]);
  const [bulkVendor, setBulkVendor] = useState('');
  const [bulkErrors, setBulkErrors] = useState([]);
  const csvRef = useRef(null);

  const [poForm, setPOForm] = useState({
    supplier_id: '',
    vendor_name: '',
    vendor_contact: '',
    vendor_address: '',
    po_date: todayWIB(),
    expected_delivery_date: '',
    notes: '',
    items: [],
  });

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      if (filterStatus) qs.set('status', filterStatus);
      if (filterSupplier) qs.set('supplier_id', filterSupplier);
      const r = await fetch(`/api/rahaza/purchase-orders${qs.toString() ? `?${qs}` : ''}`, { headers });
      if (r.ok) setList(await r.json());
      else toast.error(`Gagal memuat PO (HTTP ${r.status})`);
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, filterStatus, filterSupplier]);

  useEffect(() => { fetchList(); }, [fetchList]);

  useEffect(() => {
    const h = { Authorization: `Bearer ${token}` };
    // 2026-11-07 (Tahap 6 PG1): barang jadi tidak dibeli → disaring di sumbernya (daftar menyusut, bukan disembunyikan)
    fetch('/api/rahaza/materials?exclude_type=fg', { headers: h })
      .then(r => r.ok ? r.json() : [])
      .then(m => setMaterials((Array.isArray(m) ? m : m?.items || []).filter(x => x.active)));
    // Master Supplier (SSOT) — pengganti input nama vendor teks bebas
    fetch('/api/procurement/suppliers/options', { headers: h })
      .then(r => r.ok ? r.json() : { items: [] })
      .then(d => setSuppliers(d?.items || []));
  }, [token]);

  /** Ambil daftar satuan SAH + faktornya untuk material (server yang menentukan). */
  const ensureUom = useCallback(async (materialId) => {
    if (!materialId || uomMap[materialId]) return uomMap[materialId];
    try {
      const r = await fetch(`/api/rahaza/materials/uom-options?material_ids=${materialId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!r.ok) return null;
      const d = await r.json();
      const o = (d?.options || {})[materialId] || null;
      if (o) setUomMap(prev => ({ ...prev, [materialId]: o }));
      return o;
    } catch { return null; }
  }, [token, uomMap]);

  /** Harga berlaku dari daftar harga supplier → auto-isi harga PO. */
  const fetchPriceHint = useCallback(async (itemId, materialId, supplierId) => {
    if (!materialId) return null;
    try {
      const qs = `material_id=${materialId}${supplierId ? `&supplier_id=${supplierId}` : ''}`;
      const r = await fetch(`/api/procurement/price-lookup?${qs}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!r.ok) return null;
      const d = await r.json();
      // 2026-11-06 (Tahap 2): pemasok tanpa daftar harga → harga PO TERAKHIR barang ini sebagai saran
      const last = d?.last_po && Number(d.last_po.price) > 0
        ? { ...d.last_po, supplier_name: `PO terakhir ${d.last_po.po_number || ''}`.trim(), from_last_po: true }
        : null;
      const best = d?.best || last;
      setPriceHint(prev => ({ ...prev, [itemId]: best }));
      return best;
    } catch { return null; }
  }, [token]);

  const resetForm = () => {
    setPOForm({
      supplier_id: '',
      vendor_name: '',
      vendor_contact: '',
      vendor_address: '',
      po_date: todayWIB(),
      expected_delivery_date: '',
      notes: '',
      items: [],
    });
    setPriceHint({});
    setFormError('');
  };

  const openCreate = () => {
    resetForm();
    setCreateModal(true);
  };

  const addItem = () => {
    setPOForm(prev => ({
      ...prev,
      items: [...prev.items, {
        id: crypto.randomUUID(), material_id: '', description: '',
        uom: '', qty_input: 0, unit_cost_input: 0, notes: '',
      }],
    }));
  };

  const updateItem = (itemId, field, value) => {
    setPOForm(prev => ({
      ...prev,
      items: prev.items.map(it => it.id === itemId ? { ...it, [field]: value } : it),
    }));
  };

  /** Pilih material → muat satuan sah, set satuan beli default, auto-isi harga. */
  const pickMaterial = async (itemId, materialId) => {
    updateItem(itemId, 'material_id', materialId);
    if (!materialId) {
      updateItem(itemId, 'uom', '');
      return;
    }
    const opt = await ensureUom(materialId);
    const mat = materials.find(m => m.id === materialId);
    const best = await fetchPriceHint(itemId, materialId, poForm.supplier_id);
    // Satuan beli default: dari daftar harga supplier → purchase_uom master → satuan dasar
    const defaultUom = best?.uom || mat?.purchase_uom || opt?.base_unit || mat?.unit || '';
    const known = (opt?.units || []).some(u => u.unit === defaultUom);
    updateItem(itemId, 'uom', known ? defaultUom : (opt?.base_unit || ''));
    if (best?.price) updateItem(itemId, 'unit_cost_input', Number(best.price));
  };

  const removeItem = (itemId) => {
    setPOForm(prev => ({
      ...prev,
      items: prev.items.filter(it => it.id !== itemId),
    }));
  };

  /** Faktor satuan terpilih → satuan dasar (untuk pratinjau konversi). */
  const factorOf = useCallback((item) => {
    const opt = uomMap[item.material_id];
    if (!opt) return 1;
    if (!item.uom || item.uom === opt.base_unit) return 1;
    const row = (opt.units || []).find(u => u.unit === item.uom);
    return row ? Number(row.factor_to_base) : 1;
  }, [uomMap]);

  const formTotal = useMemo(
    () => poForm.items.reduce((s, it) => s + (Number(it.qty_input) || 0) * (Number(it.unit_cost_input) || 0), 0),
    [poForm.items],
  );

  const selectedSupplier = useMemo(
    () => suppliers.find(s => s.id === poForm.supplier_id) || null,
    [suppliers, poForm.supplier_id],
  );

  // 2026-11-07 (Tahap 6 PG2): barang yang ada di daftar harga supplier terpilih (berlaku hari ini, aturan sama
  // dengan saran harga) tampil PALING ATAS di pilihan material, bertanda harganya. Material lain tetap bisa dipilih.
  const [supplierPrices, setSupplierPrices] = useState({}); // material_id → harga termurah {price, uom, price_base}
  useEffect(() => {
    const sid = poForm.supplier_id;
    if (!createModal || !sid) { setSupplierPrices({}); return undefined; }
    let off = false;
    fetch(`/api/procurement/suppliers/${sid}/price-list?current=true`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => (r.ok ? r.json() : { items: [] }))
      .then((d) => {
        if (off) return;
        const best = {};
        (d?.items || []).forEach((row) => {
          const cur = best[row.material_id];
          if (!cur || Number(row.price_base || 0) < Number(cur.price_base || 0)) best[row.material_id] = row;
        });
        setSupplierPrices(best);
      })
      .catch(() => { if (!off) setSupplierPrices({}); });
    return () => { off = true; };
  }, [token, createModal, poForm.supplier_id]);
  const materialChoices = useMemo(() => {
    const priced = materials.filter(m => supplierPrices[m.id]);
    return { priced, others: priced.length ? materials.filter(m => !supplierPrices[m.id]) : materials };
  }, [materials, supplierPrices]);
  // Tanda harga di DEPAN label: kolom material sempit, akhiran terpotong "…" sehingga tandanya tak terlihat.
  const pricedLabel = (m) => {
    const p = supplierPrices[m.id];
    return `Rp ${Number(p.price || 0).toLocaleString('id-ID')}/${p.uom || m.unit || ''} (daftar harga) · ${materialOptionLabel(m)}`;
  };

  const createPO = async () => {
    setSaving(true);
    setFormError('');
    try {
      if (!poForm.supplier_id && !poForm.vendor_name.trim()) {
        throw new Error('Pilih supplier dari Master Supplier terlebih dahulu.');
      }
      if (poForm.items.length === 0) throw new Error('Tambahkan minimal 1 item.');

      const validItems = poForm.items.filter(
        it => (it.material_id || (it.description || '').trim()) && Number(it.qty_input) > 0,
      );
      if (validItems.length === 0) {
        throw new Error('Tidak ada item valid (pilih material atau tulis keterangan, dan qty > 0).');
      }

      const r = await fetch('/api/rahaza/purchase-orders', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          ...poForm,
          ...docNumberPayload(numPolicy, 'po_number', poNumber),
          items: validItems.map(it => ({
            material_id: it.material_id || undefined,
            description: it.description || undefined,
            uom: it.uom || undefined,
            qty_input: Number(it.qty_input) || 0,
            unit_cost_input: Number(it.unit_cost_input) || 0,
            notes: it.notes || '',
          })),
        }),
      });

      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(typeof err.detail === 'string' ? err.detail : `Gagal membuat PO (HTTP ${r.status})`);
      }

      toast.success('Purchase order berhasil dibuat');
      setCreateModal(false);
      resetForm();
      fetchList();
    } catch (e) {
      setFormError(e.message);
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  };

  const openDetail = async (po) => {
    const r = await fetch(`/api/rahaza/purchase-orders/${po.id}`, { headers });
    if (r.ok) {
      const detail = await r.json();
      // P1.C: also fetch GR audit trail in parallel
      try {
        const gr_r = await fetch(`/api/rahaza/purchase-orders/${po.id}/grs`, { headers });
        if (gr_r.ok) {
          detail._grs = await gr_r.json();
        }
      } catch {
        // non-fatal: audit trail GR opsional
      }
      setSelectedPO(detail);
      setDetailModal(true);
    }
  };

  const savePriceEdit = async () => {
    if (!priceEdit || !selectedPO) return;
    if (!String(priceEdit.reason || '').trim()) { toast.error('Alasan perubahan harga wajib diisi.'); return; }
    setSaving(true);
    try {
      const r = await fetch(`/api/rahaza/purchase-orders/${selectedPO.id}/items/${priceEdit.item.id}/price`, {
        method: 'POST', headers,
        body: JSON.stringify({ unit_cost_input: Number(priceEdit.value) || 0, reason: priceEdit.reason.trim() }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : `Gagal mengubah harga (HTTP ${r.status})`);
      toast.success(`Harga ${priceEdit.item.material_name || priceEdit.item.description || 'baris'} diubah`);
      setPriceEdit(null);
      await openDetail(selectedPO);
      fetchList();
    } catch (e) {
      toast.error(e.message);
    } finally { setSaving(false); }
  };

  // 2026-08-07 — pesan galat dari SERVER harus DITAMPILKAN.
  // Sebelumnya ketiga aksi ini membuang isi respons dan menampilkan teks generik
  // ("Gagal menyetujui PO"), padahal backend mengirim alasan yang tepat dan
  // berbahasa Indonesia (mis. "Anda pembuat permintaan ini…", "Tahap saat ini
  // Persetujuan Keuangan — hanya keuangan yang berhak memutuskan."). Tanpa ini
  // pengguna hanya tahu "gagal" tanpa pernah tahu APA yang harus dilakukan.
  const serverError = async (r, fallback) => {
    try {
      const b = await r.json();
      return b?.detail || b?.message || fallback;
    } catch { return fallback; }
  };

  const submitPO = async (po) => {
    if (!po) return;
    setSaving(true);
    try {
      const r = await fetch(`/api/rahaza/purchase-orders/${po.id}/submit`, { method: 'POST', headers });
      if (r.ok) {
        const d = await r.json().catch(() => ({}));
        toast.success(
          d?.total_stages > 1
            ? `PO diajukan — butuh ${d.total_stages} tahap persetujuan, sekarang menunggu ${d.stage_label || 'tahap pertama'}`
            : `PO diajukan — menunggu ${d?.stage_label || 'persetujuan'}`
        );
        await fetchList();
      } else {
        throw new Error(await serverError(r, 'Gagal mengajukan PO'));
      }
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  };

  // Konfirmasi ajukan (dulu popup buatan sendiri; teks dan aksi sama)
  const openSubmitModal = async (po) => {
    setSelectedPO(po);
    const ok = await confirmDialog({
      title: `Ajukan PO ${po.po_number} untuk persetujuan?`,
      body: 'Setelah diajukan, status PO menjadi Menunggu persetujuan dan menunggu penyetuju menyetujui sebelum dapat dibuatkan penerimaan barang.',
      confirmLabel: 'Ya, ajukan',
    });
    if (ok) submitPO(po);
  };

  const openApproveModal = (po) => {
    setSelectedPO(po);
    setApproveNote('');
    setApproveModal(true);
  };

  const approvePO = async () => {
    setSaving(true);
    try {
      const r = await fetch(`/api/rahaza/purchase-orders/${selectedPO.id}/approve`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ comment: approveNote }),
      });
      if (r.ok) {
        const d = await r.json().catch(() => ({}));
        toast.success(
          d?.next_stage
            ? `${selectedPO.po_number} disetujui — lanjut ke ${d.next_stage_label}`
            : `${selectedPO.po_number} disetujui penuh — siap dikirim ke supplier`
        );
        setApproveModal(false);
        fetchList();
        if (detailModal) openDetail(selectedPO);
      } else {
        throw new Error(await serverError(r, 'Gagal menyetujui PO'));
      }
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  };

  const rejectPO = async (po, reason) => {
    // Alasan WAJIB. Dulu frontend mengirim "Tidak ada alasan" secara otomatis,
    // sehingga aturan "penolakan harus beralasan" tidak ada artinya dan pembuat
    // PO tidak pernah tahu apa yang harus diperbaiki.
    if (!String(reason || '').trim()) {
      toast.error('Alasan penolakan wajib diisi agar pembuat PO tahu apa yang harus diperbaiki.');
      return;
    }
    setSaving(true);
    try {
      const r = await fetch(`/api/rahaza/purchase-orders/${po.id}/reject`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ reason: String(reason).trim() }),
      });
      if (r.ok) {
        toast.success(`PO ${po.po_number} ditolak`);
        fetchList();
      } else {
        throw new Error(await serverError(r, 'Gagal menolak PO'));
      }
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  };

  // Tolak: alasan wajib diisi di dialog konfirmasi (dulu popup buatan sendiri dengan isian yang sama)
  const openRejectModal = async (po) => {
    setSelectedPO(po);
    const reason = await confirmDialog({
      title: `Tolak PO ${po.po_number}?`,
      body: 'Alasan dikirim ke pembuat PO supaya ia tahu apa yang harus diperbaiki.',
      confirmLabel: 'Tolak PO', danger: true,
      input: { label: 'Alasan penolakan (wajib)', placeholder: 'Masukkan alasan penolakan' },
    });
    if (reason) rejectPO(po, reason);
  };

  const cancelPO = async (po, reason) => {
    setSaving(true);
    try {
      const r = await fetch(`/api/rahaza/purchase-orders/${po.id}/cancel`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ reason: reason || 'Tidak ada alasan' }),
      });
      if (r.ok) {
        toast.success(`PO ${po.po_number} dibatalkan`);
        fetchList();
      } else {
        throw new Error('Gagal membatalkan PO');
      }
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  };

  const openCancelModal = async (po) => {
    setSelectedPO(po);
    const reason = await confirmDialog({
      title: `Batalkan PO ${po.po_number}?`,
      body: 'PO yang dibatalkan tidak bisa diterima di gudang.',
      confirmLabel: 'Batalkan PO', danger: true,
      input: { label: 'Alasan pembatalan (wajib)', placeholder: 'Masukkan alasan pembatalan' },
    });
    if (reason) cancelPO(po, reason);
  };

  // 2026-11-07 (Tahap 5): konfirmasi hapus memakai dialog aplikasi (dulu window.confirm bawaan browser)
  const deletePO = async (po) => {
    const ok = await confirmDialog({
      title: `Hapus PO ${po.po_number}?`, body: 'PO draf ini akan dihapus permanen.',
      confirmLabel: 'Hapus', danger: true,
    });
    if (ok) doDeletePO(po);
  };
  const doDeletePO = async (po) => {
    const r = await fetch(`/api/rahaza/purchase-orders/${po.id}`, { method: 'DELETE', headers });
    if (r.ok) {
      toast.success('PO berhasil dihapus');
      fetchList();
      setDetailModal(false);
    } else {
      toast.error('Gagal menghapus PO');
    }
  };

  const createGRFromPO = async (po) => {
    // P1.C: Call backend create-gr endpoint then navigate to receiving
    try {
      const r = await fetch(`/api/rahaza/purchase-orders/${po.id}/create-gr`, {
        method: 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ notes: `Auto-created from PO ${po.po_number}` }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: 'Gagal membuat penerimaan barang' }));
        toast.error(err.detail || 'Gagal membuat penerimaan barang dari PO');
        return;
      }
      const gr = await r.json();
      toast.success(`Penerimaan ${gr.receipt_number} dibuat dari PO ${po.po_number}. ${gr.items.length} item siap diterima.`);
      // Navigate to ReceivingModule with the new GR id (let module handle the deep link)
      onNavigate?.('wh-receiving', { receipt_id: gr.id, po_id: po.id, po_number: po.po_number });
      fetchList();
      setDetailModal(false);
    } catch (e) {
      toast.error('Gagal membuat penerimaan barang: ' + (e?.message || ''));
    }
  };

  const runBulkImport = async () => {
    setSaving(true);
    try {
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/rahaza/purchase-orders/bulk-import`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ vendor_name: bulkVendor, rows: bulkRows }),
      });
      const d = await r.json();
      if (!r.ok) {
        setBulkErrors(d.errors || [d.detail || 'Impor gagal']);
      } else {
        toast.success(`${d.created} PO berhasil dibuat`);
        if (d.row_errors?.length) setBulkErrors(d.row_errors);
        else { setBulkModal(false); setBulkRows([]); setBulkErrors([]); }
        // BUG-FIX 2026-07-25: dulu memanggil `loadList()` yang TIDAK ADA
        // ⇒ ReferenceError setelah import sukses ⇒ tertangkap catch di
        // bawah sehingga user melihat toast "Gagal import PO" padahal PO
        // BERHASIL dibuat, dan daftar tidak pernah ter-refresh.
        fetchList();
      }
    } catch {
      toast.error('Gagal impor PO');
    } finally {
      setSaving(false);
    }
  };
  const closeBulk = () => { setBulkModal(false); setBulkRows([]); setBulkErrors([]); };

  const { paged, page, setPage, totalPages, total, pageSize } = useClientPagination(list, 25);

  // ── Kolom daftar ──────────────────────────────────────────────────────────
  const aksiBaris = (po) => {
    const bisaAjukan = (po.status === 'draft' || po.status === 'rejected') && po.can_submit !== false;
    const bisaHapus = bisaAjukan && po.status === 'draft';
    const bisaPutus = po.status === 'pending_approval' && po.can_approve;
    const bisaGR = po.status === 'approved' || po.status === 'partially_received';
    const bisaBatal = po.status !== 'fully_received' && po.status !== 'cancelled';
    return (
      <div className="flex items-center justify-end gap-1">
        {bisaAjukan && (
          <Button size="sm" variant="outline" onClick={() => openSubmitModal(po)} data-testid={`po-submit-${po.id}`}>
            <Send />Ajukan
          </Button>
        )}
        {/* 2026-08-07 — tombol Setujui/Tolak mengikuti FLAG SERVER (`can_approve`/`can_reject`),
            bukan sekadar status. Kalau tidak berhak, alasannya DITAMPILKAN di kolom status. */}
        {bisaPutus && (
          <Button size="sm" variant="success" onClick={() => openApproveModal(po)}
            title={po.stage_label ? `Setujui — ${po.stage_label}` : 'Setujui'} data-testid={`po-approve-${po.id}`}>
            <CheckCircle2 />Setujui
          </Button>
        )}
        {bisaGR && (
          <Button size="sm" variant="outline" onClick={() => createGRFromPO(po)} data-testid={`po-create-gr-${po.id}`}>
            <TruckIcon />Terima barang
          </Button>
        )}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="icon-sm" variant="ghost" title="Lainnya" aria-label="Aksi lainnya" data-testid={`po-more-${po.id}`}>
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => openDetail(po)} data-testid={`po-view-${po.id}`}>
              <Eye className="mr-2 h-4 w-4" />Lihat detail
            </DropdownMenuItem>
            {bisaPutus && (
              <DropdownMenuItem onSelect={() => openRejectModal(po)} data-testid={`po-reject-${po.id}`}>
                <XCircle className="mr-2 h-4 w-4" />Tolak
              </DropdownMenuItem>
            )}
            {(bisaBatal || bisaHapus) && <DropdownMenuSeparator />}
            {bisaBatal && (
              <DropdownMenuItem onSelect={() => openCancelModal(po)} data-testid={`po-cancel-${po.id}`}>
                <XCircle className="mr-2 h-4 w-4" />Batalkan PO
              </DropdownMenuItem>
            )}
            {bisaHapus && (
              <DropdownMenuItem onSelect={() => deletePO(po)} data-testid={`po-delete-${po.id}`}
                className="text-[hsl(var(--danger-text))]">
                <Trash2 className="mr-2 h-4 w-4" />Hapus draf
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    );
  };

  const kolom = [
    { kunci: 'no', label: 'No. PO', hp: 'judul', isi: (po) => (
      <span className="font-medium whitespace-nowrap" data-testid={`po-row-${po.id}`}>{po.po_number}</span>) },
    { kunci: 'tgl', label: 'Tanggal', isi: (po) => <span className="whitespace-nowrap">{fmtTgl(po.po_date)}</span> },
    { kunci: 'supplier', label: 'Supplier', hp: 'keterangan', isi: (po) => (
      <div className="min-w-0">
        <p className="font-medium text-foreground">{po.supplier_name || po.vendor_name}</p>
        <p className="flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
          {po.supplier_code
            ? <span>{po.supplier_code}</span>
            : <span className="inline-flex items-center gap-1 text-[hsl(var(--warning-text))]">
                <AlertTriangle className="h-3 w-3" /> belum tertaut master
              </span>}
          {po.vendor_contact && <span>· {po.vendor_contact}</span>}
        </p>
      </div>) },
    { kunci: 'item', label: 'Item', rata: 'kanan', isi: (po) => <span className="tabular-nums">{po.item_count}</span> },
    { kunci: 'nilai', label: 'Total nilai', rata: 'kanan', isi: (po) => (
      <span className="whitespace-nowrap tabular-nums">{fmtRpNum(po.total_value)}</span>) },
    { kunci: 'status', label: 'Status', isi: (po) => (
      <div className="space-y-1">
        <POStatusBadge status={po.status} />
        {/* Tahap aktif dari SERVER — dulu kolom ini hanya menampilkan
            "Menunggu Persetujuan" tanpa memberi tahu tahap ke berapa
            dari berapa, sehingga tidak ada yang tahu siapa gilirannya. */}
        {po.status === 'pending_approval' && po.stage_label && (
          <p className="text-xs text-muted-foreground" data-testid={`po-stage-${po.id}`}>
            {po.stage_label}{po.total_stages ? ` (${po.stage_order}/${po.total_stages})` : ''}
          </p>
        )}
        {po.status === 'pending_approval' && !po.can_approve && (
          <p className="max-w-[16rem] text-xs text-muted-foreground" data-testid={`po-blocked-${po.id}`}>
            {po.blocked_reason || 'Menunggu penyetuju yang berhak.'}
          </p>
        )}
        {po.exceeds_pr_value && (
          <p className="text-xs font-medium text-[hsl(var(--warning-text))]" data-testid={`po-exceeds-${po.id}`}>
            Melebihi nilai PR yang disetujui
          </p>
        )}
      </div>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: aksiBaris },
  ];

  const kolomUnduh = [
    { label: 'No. PO', nilai: (po) => po.po_number },
    { label: 'Tanggal', nilai: (po) => fmtTgl(po.po_date) },
    { label: 'Kode supplier', nilai: (po) => po.supplier_code || '' },
    { label: 'Supplier', nilai: (po) => po.supplier_name || po.vendor_name || '' },
    { label: 'Kontak', nilai: (po) => po.vendor_contact || '' },
    { label: 'Jumlah item', nilai: (po) => Number(po.item_count || 0) },
    { label: 'Total nilai (Rp)', nilai: (po) => Number(po.total_value || 0) },
    { label: 'Diterima (%)', nilai: (po) => Number(po.received_pct || 0) },
    { label: 'Status', nilai: (po) => (STATUS_META[po.status] || STATUS_META.draft).label },
    { label: 'Tahap persetujuan', nilai: (po) => (po.status === 'pending_approval' ? po.stage_label || '' : '') },
    { label: 'Dari permintaan', nilai: (po) => po.from_pr_number || '' },
  ];

  const adaSaringan = !!(filterStatus || filterSupplier);
  const sp = selectedPO;
  const spItems = sp?.items || [];

  return (
    <PageLayout testId="purchase-order-page" title="Purchase Order"
      subtitle="Kelola pembelian material dari supplier. PO harus disetujui sebelum bisa diterima di gudang."
      actions={<>
        {/* U2 — Impor massal dari CSV/Excel */}
        <Button variant="outline" onClick={() => setBulkModal(true)} data-testid="po-bulk-import-btn">
          <Upload />Impor CSV
        </Button>
        <Button onClick={openCreate} data-testid="po-create-btn"><Plus />Buat PO</Button>
      </>}
      filters={<>
        <SmartNativeSelect value={filterStatus} onChange={e => setFilterStatus(e.target.value)}
          className="w-48 h-9" data-testid="po-filter-status">
          <option value="">Semua status</option>
          {Object.entries(STATUS_META).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={filterSupplier} onChange={e => setFilterSupplier(e.target.value)}
          className="w-56 h-9" data-testid="po-filter-supplier">
          <option value="">Semua supplier</option>
          {suppliers.map(s => (
            <option key={s.id} value={s.id}>{`${s.code} — ${s.name}`}</option>
          ))}
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="purchase-order" namaLembar="Purchase order" baris={list} kolom={kolomUnduh}
          testId="po-unduh" />
        <Button variant="outline" size="icon" onClick={fetchList} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="po-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      footer={list.length > 0 && (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />
      )}>
      {loading && list.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat purchase order…</p>
      ) : (
        <TabelData kolom={kolom} baris={paged} onKlikBaris={openDetail} testId="po-table"
          kosong={<EmptyState icon={Package}
            title={adaSaringan ? 'Tidak ada PO yang cocok dengan saringan' : 'Belum ada purchase order'}
            description={adaSaringan ? 'Ubah saringan status atau supplier.' : 'Buat PO baru atau impor dari CSV. PO juga bisa dibuat dari permintaan pengadaan yang disetujui.'}
            action={!adaSaringan && <Button onClick={openCreate}><Plus />Buat PO</Button>} />} />
      )}

      {/* ── Form buat PO ─────────────────────────────────────────────────── */}
      <FormPopup open={createModal} onClose={() => setCreateModal(false)} ukuran="panjang" testId="po-form"
        judul="Buat purchase order" keterangan="Disimpan sebagai draf; ajukan untuk persetujuan dari daftar atau detail PO."
        onSimpan={createPO} menyimpan={saving} galat={formError} labelSimpan="Simpan draf PO">
        <div className="grid gap-4 md:grid-cols-2">
          <Isian label="Supplier" wajib>
            <SmartNativeSelect
              value={poForm.supplier_id}
              onChange={(e) => {
                const sid = e.target.value;
                const s = suppliers.find(x => x.id === sid);
                const prevSup = suppliers.find(x => x.id === poForm.supplier_id);
                // 2026-11-07 (Tahap 5): kontak & alamat MENGIKUTI supplier yang baru dipilih. Dulu supplier
                // tanpa telepon/alamat mewarisi kontak supplier SEBELUMNYA (tercetak di PO yang salah).
                // Isian ketikan sendiri (bukan dari master) tetap dipertahankan.
                const fromPrev = (v, k) => !prevSup || v === (prevSup[k] || '');
                setPOForm(prev => ({
                  ...prev,
                  supplier_id: sid,
                  vendor_name: s?.name || '',
                  vendor_contact: s?.phone || (fromPrev(prev.vendor_contact, 'phone') ? '' : prev.vendor_contact),
                  vendor_address: s?.address || (fromPrev(prev.vendor_address, 'address') ? '' : prev.vendor_address),
                }));
                // Harga bisa berbeda per supplier → segarkan saran harga
                poForm.items.forEach(it => {
                  if (it.material_id) fetchPriceHint(it.id, it.material_id, sid);
                });
              }}
              data-testid="po-form-supplier"
            >
              <option value="">Pilih supplier dari master</option>
              {suppliers.map(s => (
                <option key={s.id} value={s.id}>{`${s.code} — ${s.name}`}</option>
              ))}
            </SmartNativeSelect>
            {suppliers.length === 0 && (
              <p className="text-xs text-[hsl(var(--warning-text))]">
                Master Supplier masih kosong. Buka menu Master Supplier untuk menambah
                atau menarik data supplier dari dokumen lama.
              </p>
            )}
            {selectedSupplier && (
              <p className="text-xs text-muted-foreground" data-testid="po-form-supplier-info">
                Termin {selectedSupplier.payment_terms || '-'} · {selectedSupplier.currency || 'IDR'}
                {selectedSupplier.lead_time_days ? ` · waktu kirim ${selectedSupplier.lead_time_days} hari` : ''}
              </p>
            )}
            {selectedSupplier && materialChoices.priced.length > 0 && (
              <p className="text-xs text-primary" data-testid="po-form-supplier-pricelist-info">
                {materialChoices.priced.length} barang ada di daftar harga supplier ini — tampil paling atas di pilihan material.
              </p>
            )}
          </Isian>
          <Isian label="Kontak supplier" htmlFor="po-form-vendor-contact">
            <Input id="po-form-vendor-contact" value={poForm.vendor_contact}
              onChange={e => setPOForm({ ...poForm, vendor_contact: e.target.value })}
              placeholder="0812-3456-7890" data-testid="po-form-vendor-contact" />
          </Isian>
        </div>

        <Isian label="Alamat supplier" htmlFor="po-form-vendor-address">
          <Textarea id="po-form-vendor-address" rows={2} value={poForm.vendor_address}
            onChange={e => setPOForm({ ...poForm, vendor_address: e.target.value })}
            placeholder="Jl. Raya Industri No. 123, Bandung" data-testid="po-form-vendor-address" />
        </Isian>

        <DocNumberField policy={numPolicy} value={poNumber} onChange={setPoNumber} label="Nomor PO" testId="po-number" />

        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Tanggal PO">
            <DatePicker value={poForm.po_date} onChange={(v) => setPOForm({ ...poForm, po_date: v })}
              bolehKosong={false} testId="po-form-date" />
          </Isian>
          <Isian label="Estimasi terima">
            <DatePicker value={poForm.expected_delivery_date} min={poForm.po_date || undefined}
              onChange={(v) => setPOForm({ ...poForm, expected_delivery_date: v })}
              placeholder="Pilih tanggal" testId="po-form-expected-delivery" />
          </Isian>
        </div>

        <Isian label="Catatan" htmlFor="po-form-notes">
          <Textarea id="po-form-notes" rows={2} value={poForm.notes}
            onChange={e => setPOForm({ ...poForm, notes: e.target.value })}
            placeholder="Catatan tambahan" data-testid="po-form-notes" />
        </Isian>

        <div className="space-y-3 border-t border-[var(--glass-border)] pt-4">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <p className="text-sm font-semibold text-foreground">Item pesanan</p>
              <p className="text-xs text-muted-foreground">
                Pilih satuan beli (mis. karton). Qty & harga otomatis dikonversi ke satuan dasar untuk stok dan jurnal.
              </p>
            </div>
            <Button type="button" size="sm" variant="outline" onClick={addItem} data-testid="po-form-add-item">
              <Plus />Tambah item
            </Button>
          </div>

          {poForm.items.length === 0 && (
            <p className="py-3 text-center text-sm text-muted-foreground">Klik &quot;Tambah item&quot; untuk menambahkan barang yang dipesan.</p>
          )}

          {poForm.items.map((item, idx) => {
            const opt = uomMap[item.material_id];
            const f = factorOf(item);
            const hint = priceHint[item.id];
            const qtyBase = (Number(item.qty_input) || 0) * f;
            const costBase = f ? (Number(item.unit_cost_input) || 0) / f : Number(item.unit_cost_input) || 0;
            // Label kolom: baris pertama di layar lebar; tiap baris di HP (tanpa kepala kolom).
            const lbl = idx === 0 ? 'mb-1 block text-xs font-medium' : 'mb-1 block text-xs font-medium md:hidden';
            return (
              <div key={item.id} className="border-b border-[var(--glass-border)] pb-3 last:border-0">
                <div className="grid grid-cols-12 items-end gap-2">
                  <div className="col-span-12 md:col-span-4">
                    <span className={lbl}>Material / keterangan</span>
                    <SmartNativeSelect
                      value={item.material_id}
                      onChange={e => pickMaterial(item.id, e.target.value)}
                      data-testid={`po-form-item-material-${idx}`}
                    >
                      <option value="">Item bebas (jasa / non-master)</option>
                      {materialChoices.priced.map(m => (
                        <option key={m.id} value={m.id}>{pricedLabel(m)}</option>
                      ))}
                      {materialChoices.priced.length > 0 && (
                        <option value="__lain" disabled>Material lain (tanpa daftar harga supplier ini)</option>
                      )}
                      {materialChoices.others.map(m => (
                        <option key={m.id} value={m.id}>{materialOptionLabel(m)}</option>
                      ))}
                    </SmartNativeSelect>
                    {!item.material_id && (
                      <Input className="mt-1" value={item.description} aria-label="Keterangan item"
                        onChange={e => updateItem(item.id, 'description', e.target.value)}
                        placeholder="Keterangan item, mis. jasa kirim ekspedisi" data-testid={`po-form-item-desc-${idx}`} />
                    )}
                  </div>
                  <div className="col-span-4 md:col-span-2">
                    <span className={lbl}>Satuan beli</span>
                    {item.material_id && opt ? (
                      <SmartNativeSelect value={item.uom} onChange={e => updateItem(item.id, 'uom', e.target.value)}
                        data-testid={`po-form-item-uom-${idx}`}>
                        {(opt.units || []).map(u => (
                          <option key={u.unit} value={u.unit}>{u.unit}</option>
                        ))}
                      </SmartNativeSelect>
                    ) : (
                      <Input value={item.uom} aria-label="Satuan beli" onChange={e => updateItem(item.id, 'uom', e.target.value)}
                        placeholder="pcs" data-testid={`po-form-item-uom-${idx}`} />
                    )}
                  </div>
                  <div className="col-span-4 md:col-span-2">
                    <span className={lbl}>Qty</span>
                    <Input type="number" step="0.01" value={item.qty_input} aria-label="Qty"
                      onChange={e => updateItem(item.id, 'qty_input', parseFloat(e.target.value) || 0)}
                      placeholder="0" className="text-right" data-testid={`po-form-item-qty-${idx}`} />
                  </div>
                  <div className="col-span-4 md:col-span-2">
                    <span className={lbl}>Harga / satuan</span>
                    <MoneyInput decimals={2} value={item.unit_cost_input} aria-label="Harga per satuan"
                      onChange={e => updateItem(item.id, 'unit_cost_input', parseFloat(e.target.value) || 0)}
                      placeholder="0" className="text-right" data-testid={`po-form-item-cost-${idx}`} />
                  </div>
                  <div className="col-span-8 md:col-span-1">
                    <span className={lbl}>Total</span>
                    <div className="flex h-9 items-center justify-end px-1 text-sm tabular-nums text-muted-foreground"
                      data-testid={`po-form-item-total-${idx}`}>
                      {((Number(item.qty_input) || 0) * (Number(item.unit_cost_input) || 0)).toLocaleString('id-ID', { maximumFractionDigits: 0 })}
                    </div>
                  </div>
                  <div className="col-span-4 flex justify-end md:col-span-1">
                    <Button type="button" variant="ghost" size="icon" onClick={() => removeItem(item.id)}
                      title="Hapus item" aria-label="Hapus item" data-testid={`po-form-item-remove-${idx}`}>
                      <Trash2 className="text-[hsl(var(--danger-text))]" />
                    </Button>
                  </div>
                </div>

                {/* Pratinjau konversi + saran harga dari daftar harga supplier */}
                <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1">
                  {item.material_id && opt && item.uom && item.uom !== opt.base_unit && (
                    <span className="text-xs text-muted-foreground" data-testid={`po-form-item-preview-${idx}`}>
                      1 {item.uom} = {f.toLocaleString('id-ID', { maximumFractionDigits: 4 })} {opt.base_unit} ⇒{' '}
                      <span className="font-semibold text-foreground">
                        {qtyBase.toLocaleString('id-ID', { maximumFractionDigits: 4 })} {opt.base_unit}
                      </span>{' '}
                      @ Rp {costBase.toLocaleString('id-ID', { maximumFractionDigits: 2 })}/{opt.base_unit}
                    </span>
                  )}
                  {hint && (
                    <Button type="button" size="sm" variant="outline" className="rounded-full"
                      onClick={() => {
                        updateItem(item.id, 'unit_cost_input', Number(hint.price));
                        if ((uomMap[item.material_id]?.units || []).some(u => u.unit === hint.uom)) {
                          updateItem(item.id, 'uom', hint.uom);
                        }
                        toast.success(hint.from_last_po ? `Harga diisi dari ${hint.supplier_name}` : `Harga diisi dari daftar harga ${hint.supplier_name}`);
                      }}
                      data-testid={`po-form-item-price-hint-${idx}`}>
                      <Tag />Harga {hint.supplier_name}: Rp {Number(hint.price).toLocaleString('id-ID')} / {hint.uom}
                    </Button>
                  )}
                </div>
              </div>
            );
          })}

          {poForm.items.length > 0 && (
            <div className="flex items-baseline justify-end gap-3">
              <span className="text-sm text-muted-foreground">Total nilai PO</span>
              <span className="text-lg font-bold tabular-nums" data-testid="po-form-grand-total">
                Rp {formTotal.toLocaleString('id-ID', { maximumFractionDigits: 0 })}
              </span>
            </div>
          )}
        </div>
      </FormPopup>

      {/* ── Detail PO (popup) ────────────────────────────────────────────── */}
      {detailModal && sp && (
        <DetailPopup open onClose={() => setDetailModal(false)} testId="po-detail"
          judul={`PO ${sp.po_number}`}
          keterangan={`Dibuat ${formatDateTimeID(sp.created_at)}${sp.created_by_name ? ` oleh ${sp.created_by_name}` : ''}`}
          status={<POStatusBadge status={sp.status} />}
          aksi={<>
            {(sp.status === 'draft' || sp.status === 'rejected') && sp.can_submit !== false && (
              <Button size="sm" onClick={() => { setDetailModal(false); openSubmitModal(sp); }} data-testid="po-detail-submit">
                <Send />{sp.status === 'rejected' ? 'Ajukan ulang' : 'Ajukan persetujuan'}
              </Button>
            )}
            {sp.status === 'pending_approval' && sp.can_approve && (<>
              <Button size="sm" variant="success" onClick={() => { setDetailModal(false); openApproveModal(sp); }}
                data-testid="po-detail-approve">
                <CheckCircle2 />{sp.stage_label ? `Setujui — ${sp.stage_label}` : 'Setujui'}
              </Button>
              <Button size="sm" variant="destructive" onClick={() => { setDetailModal(false); openRejectModal(sp); }}
                data-testid="po-detail-reject">
                <XCircle />Tolak
              </Button>
            </>)}
            {(sp.status === 'approved' || sp.status === 'partially_received') && (
              <Button size="sm" onClick={() => createGRFromPO(sp)} data-testid="po-detail-create-gr">
                <TruckIcon />Buat penerimaan barang
              </Button>
            )}
          </>}>
          {sp.rejected_reason && <Notice tone="danger" title="Alasan ditolak">{sp.rejected_reason}</Notice>}
          {sp.cancelled_reason && <Notice tone="info" title="Alasan dibatalkan">{sp.cancelled_reason}</Notice>}

          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Supplier">
              <p className="font-medium">{sp.supplier_name || sp.vendor_name}</p>
              {sp.supplier_code && <p className="text-xs text-muted-foreground">{sp.supplier_code}</p>}
              {sp.vendor_contact && <p className="text-xs text-muted-foreground">{sp.vendor_contact}</p>}
              {sp.vendor_address && <p className="text-xs text-muted-foreground">{sp.vendor_address}</p>}
              {sp.supplier?.npwp && <p className="text-xs text-muted-foreground">NPWP: {sp.supplier.npwp}</p>}
              {sp.payment_terms && <p className="text-xs text-muted-foreground">Termin: {sp.payment_terms} · {sp.currency || 'IDR'}</p>}
              {sp.supplier?.bank_accounts?.[0] && (
                <p className="text-xs text-muted-foreground">
                  {sp.supplier.bank_accounts[0].bank_name} {sp.supplier.bank_accounts[0].account_number}
                </p>
              )}
            </BarisDetail>
            <BarisDetail label="Tanggal PO">{fmtTgl(sp.po_date)}</BarisDetail>
            {sp.expected_delivery_date && <BarisDetail label="Estimasi terima">{fmtTgl(sp.expected_delivery_date)}</BarisDetail>}
            {sp.from_pr_number && <BarisDetail label="Dari permintaan">{sp.from_pr_number}</BarisDetail>}
            {sp.notes && <BarisDetail label="Catatan">{sp.notes}</BarisDetail>}
          </dl>

          {/* ── Rantai persetujuan PO (2026-08-07) — tahap ke berapa dari berapa, siapa yang sudah
              memutuskan, dan siapa giliran berikutnya. */}
          {Array.isArray(sp.chain) && sp.chain.length > 0 && (
            <div className="space-y-2">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-sm font-semibold text-foreground">Rantai persetujuan</p>
                <p className="text-xs text-muted-foreground">
                  {sp.total_stages} tahap untuk nilai {fmtRpNum(sp.total_value)}
                </p>
              </div>
              <ol className="space-y-2" data-testid="po-approval-stepper">
                {sp.chain.map((s) => (
                  <li key={s.stage} className="flex items-start gap-3 rounded-lg border border-[var(--glass-border)] px-3 py-2">
                    <span className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
                      s.done ? 'bg-[hsl(var(--success-strong))] text-white'
                        : s.current ? 'bg-[hsl(var(--warning))] text-white' : 'bg-foreground/10 text-muted-foreground'}`}>
                      {s.order}
                    </span>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2 text-sm font-medium text-foreground">
                        {s.label}
                        {s.current && <StatusBadge status="current" label="Menunggu sekarang" tone="warning" />}
                        {s.override && <StatusBadge status="override" label="Ditembus admin" tone="primary" />}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {s.done
                          ? `${s.actor_name}${s.timestamp ? ` — ${formatDateTimeID(s.timestamp)}` : ''}`
                          : `Menunggu ${s.role_hint}`}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
              {sp.next_approver_label && (
                <p className="text-xs text-muted-foreground">Berikutnya setelah tahap ini: {sp.next_approver_label}</p>
              )}
              {sp.status === 'pending_approval' && !sp.can_approve && sp.blocked_reason && (
                <Notice tone="warning" testId="po-detail-blocked">{sp.blocked_reason}</Notice>
              )}
              {sp.exceeds_pr_value && (
                <Notice tone="danger" testId="po-detail-exceeds">
                  Nilai PO ini <strong>{fmtRpNum(sp.total_value)}</strong> melebihi nilai permintaan yang sudah disetujui
                  (<strong>{fmtRpNum(sp.pr_approved_value)}</strong>{sp.from_pr_number ? ` pada ${sp.from_pr_number}` : ''}).
                  Karena itu PO ini wajib melewati rantai persetujuan penuh.
                </Notice>
              )}
              {Array.isArray(sp.approval_steps) && sp.approval_steps.length > 0 && (
                <div className="border-t border-[var(--glass-border)] pt-2">
                  <p className="mb-1 text-xs font-semibold text-foreground">Riwayat</p>
                  <ul className="space-y-0.5">
                    {sp.approval_steps.map((s, i) => (
                      <li key={s.id || i} className="flex flex-wrap items-baseline gap-2 text-xs">
                        <span className="tabular-nums text-muted-foreground">{s.timestamp ? formatDateTimeID(s.timestamp) : '-'}</span>
                        <span className="font-medium text-foreground">{s.action_label || s.action}</span>
                        <span className="text-muted-foreground">— {s.actor_name}</span>
                        {s.comment && <span className="italic text-muted-foreground">“{s.comment}”</span>}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          <div>
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-semibold text-foreground">Item ({spItems.length})</p>
              <TombolUnduh namaBerkas={`item-${sp.po_number}`} namaLembar="Item PO" baris={spItems} testId="po-detail-unduh"
                kolom={[
                  { label: 'Kode', nilai: (it) => it.material_code || '' },
                  { label: 'Item', nilai: (it) => it.material_name || it.description || '' },
                  { label: 'Satuan dasar', nilai: (it) => it.base_uom || it.unit || '' },
                  { label: 'Dipesan', nilai: (it) => Number(it.qty_ordered || 0) },
                  { label: 'Diterima', nilai: (it) => Number(it.qty_received || 0) },
                  { label: 'Sisa', nilai: (it) => Number(it.qty_remaining || 0) },
                  { label: 'Harga per satuan dasar (Rp)', nilai: (it) => Number(it.unit_cost || 0) },
                  { label: 'Total (Rp)', nilai: (it) => Number(it.subtotal ?? (it.qty_ordered * it.unit_cost)) },
                ]} />
            </div>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Item</TableHead>
                    <TableHead className="text-right">Dipesan</TableHead>
                    <TableHead className="text-right">Diterima</TableHead>
                    <TableHead className="text-right">Harga</TableHead>
                    <TableHead className="text-right">Total</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody data-testid="po-detail-items">
                  {spItems.map((it, idx) => {
                    const f = Number(it.uom_factor || 1) || 1;
                    const hasPack = it.uom && it.base_uom && it.uom !== it.base_uom && f !== 1;
                    const lengkap = Number(it.qty_received) >= Number(it.qty_ordered);
                    return (
                      <TableRow key={it.id}>
                        <TableCell>
                          {/* 2026-08-07 — APA yang dibeli lebih dulu, baru kodenya. */}
                          <p className="font-medium">{it.material_name || it.description || 'Item tanpa nama'}</p>
                          <p className="text-xs text-muted-foreground">
                            {it.material_code || (it.material_linked === false ? 'Item bebas (non-master)' : '')}
                          </p>
                          {hasPack && (
                            <p className="text-xs text-primary">1 {it.uom} = {fmtQty(f)} {it.base_uom}</p>
                          )}
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-right tabular-nums">
                          <p>{fmtQty(it.qty_ordered)} {it.base_uom || it.unit}</p>
                          {hasPack && <p className="text-xs text-muted-foreground">({fmtQty(it.qty_input)} {it.uom})</p>}
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-right tabular-nums">
                          <p className={lengkap ? 'text-[hsl(var(--success-text))]' : 'text-[hsl(var(--warning-text))]'}>
                            {fmtQty(it.qty_received)} {it.base_uom || it.unit}
                          </p>
                          {Number(it.qty_remaining) > 0 && (
                            <p className="text-xs text-muted-foreground">sisa {fmtQty(it.qty_remaining)}</p>
                          )}
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-right tabular-nums">
                          <p>{fmtRpNum(it.unit_cost, 2)}</p>
                          <p className="text-xs text-muted-foreground">/ {it.base_uom || it.unit}</p>
                          {hasPack && (
                            <p className="text-xs text-muted-foreground">({fmtRpNum(it.unit_cost_input, 2)} / {it.uom})</p>
                          )}
                          {sp.can_edit_price && (
                            <Button variant="link" size="sm" className="h-auto p-0 text-xs"
                              onClick={() => setPriceEdit({ item: it, value: Number(it.unit_cost_input || it.unit_cost || 0), reason: '' })}
                              data-testid={`po-detail-price-edit-${idx}`}>
                              Ubah harga
                            </Button>
                          )}
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-right tabular-nums">
                          {fmtRpNum(it.subtotal ?? (it.qty_ordered * it.unit_cost))}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
                <TableFooter>
                  <TableRow>
                    <TableCell colSpan={4} className="text-right font-semibold">Total nilai PO</TableCell>
                    <TableCell className="whitespace-nowrap text-right font-semibold tabular-nums">
                      {fmtRpNum(spItems.reduce((sum, it) => sum + (it.qty_ordered * it.unit_cost), 0) || 0)}
                    </TableCell>
                  </TableRow>
                </TableFooter>
              </Table>
            </div>
          </div>

          {/* 2026-11-06 (Tahap 2): jejak perubahan harga baris PO (Keuangan, dengan alasan) */}
          {(sp.price_changes?.length || 0) > 0 && (
            <div data-testid="po-detail-price-changes">
              <p className="mb-2 text-sm font-semibold text-foreground">Perubahan harga ({sp.price_changes.length})</p>
              <ul className="space-y-1 text-xs">
                {sp.price_changes.map((c) => (
                  <li key={c.id} className="text-muted-foreground">
                    <span className="text-foreground">{c.description || 'Baris PO'}</span>
                    {' · '}{fmtRpNum(c.old_unit_cost_input, 2)}
                    {' → '}{fmtRpNum(c.new_unit_cost_input, 2)}
                    {c.uom ? ` / ${c.uom}` : ''} · {c.by_name} · {c.at ? formatDateTimeID(c.at) : ''}
                    {' · '}Alasan: {c.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* P1.C: jejak penerimaan barang atas PO ini */}
          {(sp._grs?.length || 0) > 0 && (
            <div data-testid="po-detail-grs">
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <p className="flex items-center gap-2 text-sm font-semibold text-foreground">
                  <TruckIcon className="h-4 w-4 text-muted-foreground" />Penerimaan barang ({sp._grs.length})
                </p>
                <TombolUnduh namaBerkas={`penerimaan-${sp.po_number}`} namaLembar="Penerimaan" baris={sp._grs}
                  testId="po-detail-grs-unduh"
                  kolom={[
                    { label: 'No. penerimaan', nilai: (g) => g.receipt_number },
                    { label: 'Tanggal', nilai: (g) => (g.created_at ? formatDateTimeID(g.created_at) : '') },
                    { label: 'Penerima', nilai: (g) => g.received_by || '' },
                    { label: 'Jumlah item', nilai: (g) => Number(g.items_count || 0) },
                    { label: 'Net diterima', nilai: (g) => Number(g.total_net || 0) },
                    { label: 'Status', nilai: (g) => (GR_STATUS[g.status] || { label: g.status }).label },
                  ]} />
              </div>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>No. penerimaan</TableHead>
                      <TableHead>Tanggal</TableHead>
                      <TableHead>Penerima</TableHead>
                      <TableHead className="text-right">Item</TableHead>
                      <TableHead className="text-right">Net diterima</TableHead>
                      <TableHead>Status</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {sp._grs.map((gr) => {
                      const g = GR_STATUS[gr.status] || { label: gr.status || '—', tone: 'warning' };
                      return (
                        <TableRow key={gr.id} data-testid={`po-gr-row-${gr.id}`}>
                          <TableCell className="font-medium">{gr.receipt_number}</TableCell>
                          <TableCell className="whitespace-nowrap">{gr.created_at ? formatDateTimeID(gr.created_at) : '-'}</TableCell>
                          <TableCell>{gr.received_by || '-'}</TableCell>
                          <TableCell className="text-right tabular-nums">{gr.items_count}</TableCell>
                          <TableCell className="text-right tabular-nums">{fmtQty(gr.total_net)}</TableCell>
                          <TableCell><StatusBadge status={gr.status} label={g.label} tone={g.tone} /></TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            </div>
          )}
        </DetailPopup>
      )}

      {/* 2026-11-06 (Tahap 2): ubah harga satu baris PO — formulir pendek Keuangan */}
      <FormPopup open={!!(priceEdit && selectedPO)} onClose={() => setPriceEdit(null)} ukuran="pendek"
        testId="po-price-edit-modal" judul="Ubah harga baris PO"
        keterangan={priceEdit && selectedPO
          ? `${priceEdit.item.material_name || priceEdit.item.description || 'Baris PO'} di ${selectedPO.po_number}. Harga baru berlaku untuk barang yang belum diterima; selisih barang yang sudah diterima diselesaikan lewat faktur pemasok (masuk HPP).`
          : undefined}
        onSimpan={savePriceEdit} menyimpan={saving} labelSimpan="Simpan harga"
        bisaSimpan={!!String(priceEdit?.reason || '').trim()}>
        {priceEdit && (<>
          <Isian label={`Harga per ${priceEdit.item.uom || priceEdit.item.base_uom || 'satuan'} (Rp)`} htmlFor="po-price-edit-value">
            <MoneyInput id="po-price-edit-value" value={priceEdit.value}
              onChange={e => setPriceEdit(p => ({ ...p, value: e.target.value }))}
              className="text-right" data-testid="po-price-edit-value" />
          </Isian>
          <Isian label="Alasan" wajib htmlFor="po-price-edit-reason">
            <Input id="po-price-edit-reason" value={priceEdit.reason}
              onChange={e => setPriceEdit(p => ({ ...p, reason: e.target.value }))}
              placeholder="mis. harga naik sesuai penawaran baru" data-testid="po-price-edit-reason" />
          </Isian>
        </>)}
      </FormPopup>

      {/* Setujui PO — catatan opsional */}
      <FormPopup open={!!(approveModal && selectedPO)} onClose={() => setApproveModal(false)} ukuran="pendek"
        testId="po-approve-form" judul="Konfirmasi persetujuan"
        keterangan={selectedPO ? `Setujui PO ${selectedPO.po_number} senilai ${fmtRpNum(selectedPO.total_value)}?` : undefined}
        onSimpan={approvePO} menyimpan={saving}
        labelSimpan={selectedPO?.stage_label ? `Setujui — ${selectedPO.stage_label}` : 'Ya, setujui'}>
        {selectedPO && (<>
          {/* Tahap yang SEDANG disetujui harus jelas — approver perlu tahu ini
              langkah ke berapa dan siapa yang harus memutuskan setelahnya. */}
          {selectedPO.stage_label && (
            <Notice tone="warning">
              Anda menyetujui tahap <strong>{selectedPO.stage_label}</strong>
              {selectedPO.total_stages ? ` (${selectedPO.stage_order} dari ${selectedPO.total_stages})` : ''}.
              {selectedPO.next_stage
                ? ` Setelah ini masih menunggu ${selectedPO.next_approver_label}.`
                : ' Ini tahap terakhir — PO langsung disetujui penuh.'}
            </Notice>
          )}
          {selectedPO.is_override && selectedPO.override_note && (
            <Notice tone="info" testId="po-override-note">{selectedPO.override_note}</Notice>
          )}
          {selectedPO.exceeds_pr_value && (
            <Notice tone="danger">
              Perhatian: nilai PO ini melebihi nilai permintaan yang sudah disetujui
              ({fmtRpNum(selectedPO.pr_approved_value)}).
            </Notice>
          )}
          <Isian label="Catatan persetujuan (opsional)" htmlFor="po-approve-note">
            <Textarea id="po-approve-note" rows={2} value={approveNote} onChange={e => setApproveNote(e.target.value)}
              placeholder="Mis. harga sudah dicek terhadap daftar harga supplier" data-testid="po-approve-note" />
          </Isian>
        </>)}
      </FormPopup>

      {/* U2 — Impor PO massal dari CSV/Excel */}
      <FormPopup open={bulkModal} onClose={closeBulk} ukuran="panjang" testId="bulk-po-modal"
        judul="Impor PO dari CSV" keterangan="Satu baris = satu item PO. Baris dengan supplier yang sama digabung menjadi satu PO."
        onSimpan={runBulkImport} menyimpan={saving} bisaSimpan={bulkRows.length > 0}
        labelSimpan={`Impor ${bulkRows.length} baris`}>
        <Notice tone="info" icon={Download}
          action={
            <Button type="button" size="sm" variant="outline" data-testid="po-template-download"
              onClick={() => {
                const ws = XLSX.utils.json_to_sheet([
                  { vendor_name: 'PT Supplier A', material_code: 'ACC-BTN-001', qty_ordered: 100, unit_cost: 500, unit: 'pcs' },
                  { vendor_name: 'PT Supplier A', material_code: 'YRN-W-001',   qty_ordered: 50,  unit_cost: 12000, unit: 'kg' },
                ]);
                const wb = XLSX.utils.book_new();
                XLSX.utils.book_append_sheet(wb, ws, 'Template PO');
                XLSX.writeFile(wb, 'template-bulk-po.xlsx');
              }}>
              <Download />Templat Excel
            </Button>
          }>
          Unduh templat Excel untuk format kolom yang benar.
        </Notice>

        <Isian label="Supplier bawaan" petunjuk="Opsional — bisa diganti per baris lewat kolom vendor_name di berkas.">
          {/* 2026-11-07 (Tahap 5): dipilih dari Master Supplier (dulu teks bebas → PO "belum tertaut master"
              bila ejaannya beda). Server menautkan lewat nama yang sama persis dengan master. */}
          <SmartNativeSelect value={bulkVendor} onChange={e => setBulkVendor(e.target.value)} data-testid="bulk-vendor-input">
            <option value="">Tanpa supplier bawaan (ambil dari kolom vendor_name)</option>
            {suppliers.map(s => (
              <option key={s.id} value={s.name}>{`${s.code} — ${s.name}`}</option>
            ))}
          </SmartNativeSelect>
        </Isian>

        <Isian label="Berkas Excel/CSV">
          <input
            ref={csvRef}
            type="file"
            accept=".xlsx,.xls,.csv"
            className="hidden"
            onChange={async (e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              const buf = await file.arrayBuffer();
              const wb = XLSX.read(buf);
              const ws = wb.Sheets[wb.SheetNames[0]];
              const rows = XLSX.utils.sheet_to_json(ws, { defval: '' });
              setBulkRows(rows);
              setBulkErrors([]);
            }}
          />
          <Button type="button" variant="outline" className="w-full border-dashed" onClick={() => csvRef.current?.click()}
            data-testid="bulk-file-picker">
            <Upload />Pilih berkas Excel/CSV
          </Button>
        </Isian>

        {bulkRows.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">{bulkRows.length} baris terbaca{bulkRows.length > 8 ? ' (8 pertama ditampilkan)' : ''}:</p>
            <div className="max-h-48 overflow-auto rounded-lg border border-[var(--glass-border)]">
              <Table>
                <TableHeader>
                  <TableRow>{Object.keys(bulkRows[0]).map(k => <TableHead key={k}>{k}</TableHead>)}</TableRow>
                </TableHeader>
                <TableBody>
                  {bulkRows.slice(0, 8).map((r, i) => (
                    <TableRow key={i}>
                      {Object.values(r).map((v, j) => <TableCell key={j} className="whitespace-nowrap">{String(v)}</TableCell>)}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            {bulkErrors.length > 0 && (
              <Notice tone="danger" icon={AlertTriangle}>
                <ul className="space-y-0.5">{bulkErrors.map((e, i) => <li key={i}>{e}</li>)}</ul>
              </Notice>
            )}
          </div>
        )}
      </FormPopup>
    </PageLayout>
  );
}


import { useState, useEffect } from 'react';
import { Plus, Eye, Trash2, Download, CheckCircle, XCircle, Clock, Truck, AlertTriangle, ChevronRight, RotateCcw, FilePlus, BookOpen } from 'lucide-react';
import { toast } from 'sonner';
import DataTable from './DataTable';
import Modal from './Modal';
import StatusBadge from './StatusBadge';
import ConfirmDialog from './ConfirmDialog';
import FileAttachmentPanel from './FileAttachmentPanel';
import SearchableSelect from './SearchableSelect';
import ImportExportPanel from './ImportExportPanel';
import AdditionalRequestModal from './AdditionalRequestModal';
import MaterialRequestTracker from './MaterialRequestTracker';
import { useSortableTable, SortableHeader } from './useSortableTable';
import { BizBadge, BizFilter, matchBiz } from './BusinessTypeBadge';
import { apiGet, apiPost, apiPut, apiDelete, apiFetch } from '../../../lib/api';
import { todayWIB } from '../../../lib/waktu';
import DocNumberField, { useDocNumberPolicy, docNumberPayload } from '../docnum/DocNumberField';
import { GlassCard, GlassInput, GlassPanel } from '@/components/ui/glass';
import FilterChips from '@/components/ui/filter-chips';
import { Notice } from '../moduleAtoms';
import { Button } from '@/components/ui/button';
import { formatRupiah } from '@/lib/format';

const TABS = [
  { id: 'shipments', label: 'Daftar Shipment', icon: Truck },
  { id: 'additional', label: 'Permintaan Tambahan', icon: Plus },
  { id: 'replacement', label: 'Permintaan Pengganti', icon: AlertTriangle },
];

export default function VendorShipmentModule({ userRole, hasPerm = () => false, portalId, onNavigate }) {
  // Pemisahan data per proses bisnis: Portal Produksi = internal, Portal Maklon = maklon.
  const businessType = portalId === 'maklon' ? 'maklon' : portalId === 'production' ? 'internal' : null;
  const [activeTab, setActiveTab] = useState('shipments');

  return (
    <div className="space-y-4">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
          <Truck className="w-6 h-6 text-[hsl(var(--primary))]" /> Vendor Shipment
          {businessType && <BizBadge type={businessType} />}
        </h1>
        <p className="text-muted-foreground text-sm mt-1">
          Kelola pengiriman material ke vendor. Shipment tambahan/pengganti diproses melalui permintaan vendor.
          {businessType && (
            <span className="ml-1 font-medium text-foreground/80">
              Menampilkan data <strong>{businessType === 'maklon' ? 'Produksi Maklon (CMT)' : 'Produksi Internal'}</strong>.
            </span>
          )}
        </p>
      </div>

      {/* Pilihan tampilan — PANDUAN_UI G4 (2026-11-05): FilterChips bersama, dulu deret tombol bergaris bawah. */}
      <FilterChips value={activeTab} onChange={setActiveTab} ariaLabel="Tampilan" hideWhenEmpty={false}
        options={TABS.map(tab => ({ key: tab.id, label: tab.label, icon: tab.icon }))} />

      {/* Tab Content */}
      {activeTab === 'shipments' && <ShipmentList userRole={userRole} hasPerm={hasPerm} businessType={businessType} onNavigate={onNavigate} />}
      {activeTab === 'additional' && <MaterialRequestList userRole={userRole} requestType="ADDITIONAL" />}
      {activeTab === 'replacement' && <MaterialRequestList userRole={userRole} requestType="REPLACEMENT" />}
    </div>
  );
}

// ─── SHIPMENT LIST ─────────────────────────────────────────────────────────────
// 2026-11-07: `onNavigate` diteruskan — dulu dipakai di sini (tautan Retur Material) padahal tidak pernah diterima.
function ShipmentList({ userRole, hasPerm = () => false, businessType = null, onNavigate }) {
  const [shipments, setShipments] = useState([]);
  const [vendors, setVendors] = useState([]);
  const [pos, setPOs] = useState([]);
  const [poItems, setPoItems] = useState([]);
  const [showModal, setShowModal] = useState(false);
  const [showDetail, setShowDetail] = useState(false);
  const [detailData, setDetailData] = useState(null);
  const [detailTimeline, setDetailTimeline] = useState([]);
  const [detailChildren, setDetailChildren] = useState([]);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [selectedPO, setSelectedPO] = useState(null);
  const [poAccessories, setPoAccessories] = useState([]);
  // FASE H-1: pratinjau material yang akan keluar dari gudang (BOM × qty kirim)
  const [matPreview, setMatPreview] = useState(null);
  const [matLoading, setMatLoading] = useState(false);
  // 2026-11-05 (owner: "aksesoris BOM tidak langsung terload di pengiriman CMT") — aksesoris yang
  // IKUT kiriman ini dihitung server dari BOM PO (maklon: disegarkan dari BOM Katalog Buyer aktif),
  // sebanding qty garmen yang dikirim; jumlahnya boleh diubah sebelum disimpan.
  const [accPlan, setAccPlan] = useState(null);
  const [accQty, setAccQty] = useState({});
  const [form, setForm] = useState({
    shipment_number: '', delivery_note_number: '', vendor_id: '',
    shipment_date: todayWIB(), notes: '', items: []
  });
  // 2026-09-23 — nomor shipment mengikuti kebijakan Otomatis/Manual owner;
  // dibaca ulang tiap modal dibuka supaya pratinjau nomor berikutnya selalu segar.
  const numPolicy = useDocNumberPolicy('vendor_shipments.shipment_number',
                                       localStorage.getItem('erp_token'), null, showModal);

  const isSuperAdmin = userRole === 'superadmin';
  const isVendor = userRole === 'vendor';
  const canCreate = userRole === 'superadmin' || hasPerm('vendor_shipment.create') || hasPerm('shipment.create');
  const canDelete = userRole === 'superadmin' || hasPerm('vendor_shipment.delete') || hasPerm('shipment.delete');
  const canEdit = userRole === 'superadmin' || hasPerm('vendor_shipment.update') || hasPerm('shipment.update');

  // Phase 16: state untuk modal "Buat Permintaan Manual"
  const [manualReqShipment, setManualReqShipment] = useState(null);
  const [manualReqItems, setManualReqItems] = useState([]);
  const [loadingManualReq, setLoadingManualReq] = useState(false);

  const openManualRequest = async (shipment) => {
    setLoadingManualReq(true);
    try {
      const fullShip = await apiGet(`/vendor-shipments/${shipment.id}`);
      const items = (fullShip.items || []).map(si => ({
        shipment_item_id: si.id,
        po_item_id: si.po_item_id || '',
        sku: si.sku || '',
        product_name: si.product_name || '',
        size: si.size || '',
        color: si.color || '',
        serial_number: si.serial_number || '',
        requested_qty: 0, // user akan isi qty yang diminta
        reason: '',
      }));
      setManualReqShipment({
        id: shipment.id,
        shipment_number: shipment.shipment_number,
        vendor_name: shipment.vendor_name,
        po_id: fullShip.po_id || (fullShip.items?.[0]?.po_id || ''),
        po_number: fullShip.po_number || (fullShip.items?.[0]?.po_number || ''),
      });
      setManualReqItems(items);
    } catch (e) {
      toast.error(e.message || 'Gagal memuat detail shipment');
    } finally {
      setLoadingManualReq(false);
    }
  };

  useEffect(() => { fetchAll(); }, [businessType]);

  const fetchAll = async () => {
    try {
      const btq = businessType ? `?business_type=${businessType}` : '';
      const [sData, vData, pData] = await Promise.all([
        apiGet(`/vendor-shipments${btq}`),
        apiGet('/garments'),
        apiGet('/production-pos'),
      ]);
      setShipments(Array.isArray(sData) ? sData : []);
      setVendors(Array.isArray(vData) ? vData.filter(v => v.status === 'active') : []);
      // Phase 8.5: keep only POs that are still shippable to the vendor
      // + sesuaikan proses bisnis portal (internal vs maklon)
      setPOs(Array.isArray(pData) ? pData.filter(p =>
        !['Completed', 'Closed'].includes(p.status) &&
        (typeof p.remaining_qty_to_vendor === 'number' ? p.remaining_qty_to_vendor > 0 : true) &&
        (!businessType || (businessType === 'maklon' ? p.business_type === 'maklon' : p.business_type !== 'maklon'))
      ) : []);
    } catch (e) {
      setShipments([]); setVendors([]); setPOs([]);
    }
  };

  const loadPOItems = async (poId) => {
    if (!poId) { setPoItems([]); setSelectedPO(null); setPoAccessories([]); return; }
    try {
      const [itemsData, accData] = await Promise.all([
        apiGet(`/po-items?po_id=${poId}`),
        apiGet(`/po-accessories?po_id=${poId}`),
      ]);
      // Phase 8.5: hide fully-shipped po_items from the picker (remaining_qty_to_vendor === 0)
      const filteredItems = Array.isArray(itemsData)
        ? itemsData.filter(i => typeof i.remaining_qty_to_vendor === 'number' ? i.remaining_qty_to_vendor > 0 : true)
        : [];
      setPoItems(filteredItems);
      setPoAccessories(Array.isArray(accData) ? accData : []);
      setSelectedPO(pos.find(p => p.id === poId) || null);
    } catch (e) { setPoItems([]); setPoAccessories([]); }
  };

  const addShipmentItem = (poItem) => {
    if (form.items.find(i => i.po_item_id === poItem.id)) {
      toast.error('Item ini sudah ditambahkan ke shipment');
      return;
    }
    // Phase 8.5: cap initial qty_sent by remaining_qty_to_vendor (if provided)
    const remaining = typeof poItem.remaining_qty_to_vendor === 'number' ? poItem.remaining_qty_to_vendor : poItem.qty;
    const initialQty = Math.min(poItem.qty || 0, remaining);
    setForm(f => ({
      ...f,
      items: [...f.items, {
        po_id: poItem.po_id, po_number: poItem.po_number,
        po_item_id: poItem.id, product_name: poItem.product_name,
        size: poItem.size, color: poItem.color, sku: poItem.sku,
        serial_number: poItem.serial_number || '',
        qty_sent: initialQty,
        remaining_qty_to_vendor: remaining,
        // K12: upah jahit baris PO; penjahit dipilih di surat jalan ini bila PO belum ber-vendor
        cmt_price_snapshot: Number(poItem.cmt_price_snapshot) || 0,
        po_without_vendor: !!(selectedPO && selectedPO.id === poItem.po_id && !selectedPO.vendor_id),
      }]
    }));
  };

  const removeItem = (idx) => setForm(f => ({ ...f, items: f.items.filter((_, i) => i !== idx) }));

  // ═══════════════════════════════════════════════════════════════════════════
  // FASE H-1 (2026-08-15) — PRATINJAU MATERIAL YANG KELUAR DARI GUDANG
  // ═══════════════════════════════════════════════════════════════════════════
  // Mengirim material ke CMT sekarang MEMOTONG stok gudang (dulu tidak sama sekali
  // — kain & aksesoris keluar tanpa jejak). Karena itu pemakai HARUS bisa melihat
  // apa yang akan berkurang SEBELUM menekan Simpan; kalau tidak, satu-satunya cara
  // mengetahui stok kurang adalah ditolak saat menyimpan — UX yang persis
  // dikeluhkan pemilik pada layar dispatch ke buyer.
  const fetchMaterialPreview = async (items) => {
    const lines = (items || []).filter(i => i.po_item_id && Number(i.qty_sent) > 0);
    if (lines.length === 0) { setMatPreview(null); return; }
    setMatLoading(true);
    try {
      const res = await apiPost('/vendor-shipments/material-preview', {
        items: lines.map(i => ({ po_item_id: i.po_item_id, qty_sent: Number(i.qty_sent) })),
      });
      setMatPreview(res || null);
    } catch (e) {
      setMatPreview({ applicable: false, reason: e.message || 'gagal memuat pratinjau', materials: [] });
    } finally { setMatLoading(false); }
  };

  // Tanda tangan isi item — dipakai sebagai dependensi efek supaya pratinjau
  // dihitung ulang HANYA saat po_item/qty berubah, bukan setiap render.
  const itemsSignature = (form.items || [])
    .map(i => `${i.po_item_id}:${i.qty_sent}`).join('|');

  useEffect(() => {
    if (!showModal) { setMatPreview(null); return; }
    // debounce 450ms: pemakai masih mengetik qty, jangan panggil server per ketikan
    const t = setTimeout(() => fetchMaterialPreview(form.items), 450);
    return () => clearTimeout(t);
  }, [showModal, itemsSignature]);

  const accKey = (r) => r.accessory_id || r.accessory_code || r.accessory_name;
  const shipPoId = selectedPO?.id || (form.items[0] || {}).po_id || '';
  useEffect(() => {
    if (!showModal || !shipPoId) { setAccPlan(null); return; }
    const lines = (form.items || []).filter(i => i.po_item_id && Number(i.qty_sent) > 0);
    const t = setTimeout(async () => {
      try {
        const res = await apiPost('/vendor-shipments/accessory-plan', {
          po_id: shipPoId,
          items: lines.map(i => ({ po_item_id: i.po_item_id, qty_sent: Number(i.qty_sent) })),
        });
        setAccPlan(res || null);
        setAccQty({});           // qty garmen berubah → jatah dihitung ulang
      } catch (e) {
        setAccPlan({ rows: [], warnings: [e.message || 'Aksesoris belum bisa dihitung'] });
      }
    }, 450);
    return () => clearTimeout(t);
  }, [showModal, shipPoId, itemsSignature]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.items.length) { toast.error('Tambahkan minimal 1 item'); return; }
    // Phase 8.5: client-side guard — block over-ship and invalid qty before hitting backend
    for (const item of form.items) {
      const remaining = typeof item.remaining_qty_to_vendor === 'number' ? item.remaining_qty_to_vendor : undefined;
      if (!item.qty_sent || item.qty_sent < 1) {
        toast.error(`Qty item "${item.product_name}" harus lebih dari 0`);
        return;
      }
      if (remaining !== undefined && item.qty_sent > remaining) {
        toast.error(`Qty item "${item.product_name}" (${item.qty_sent}) melebihi sisa ke vendor (${remaining}). Kurangi qty atau gunakan permintaan ADDITIONAL.`);
        return;
      }
    }
    // K12 (7 Nov 2026): penjahit baru dipilih saat kirim → baris yang dikirim wajib sudah punya upah jahit.
    // Upah diisi di form PO (satu sumber), bukan di surat jalan; server menolak dengan pesan yang sama.
    if (shipNoRate.length) {
      toast.error(`Upah jahit per pcs belum diisi untuk ${shipNoRate.map(i => i.sku || i.product_name).slice(0, 4).join(', ')}. `
        + 'Isi dulu di form PO (tautan "Isi upah di form PO"), lalu buat surat jalan lagi.');
      return;
    }
    // FASE H-1: tolak di layar bila stok material kurang — pesannya menyebut
    // materialnya, bukan "gagal menyimpan". Mode sementara "stok boleh minus"
    // (2026-09-23): kekurangan hanya PERINGATAN, kecuali material tidak terdaftar.
    const blocking = matPreview?.applicable && (
      matPreview.blocking ?? (matPreview.has_shortage && !matPreview.allow_negative));
    if (blocking) {
      const s = (matPreview.materials || []).find(m => m.blocking ?? m.shortage);
      toast.error(
        `Stok material tidak cukup: ${s?.code} butuh ${Number(s?.qty_required || 0).toLocaleString('id-ID')} ` +
        `${s?.unit || ''}, tersedia ${Number(s?.available || 0).toLocaleString('id-ID')}` +
        (s?.problem ? ` (${s.problem})` : '') + `. Surat jalan tidak akan dibuat.`);
      return;
    }
    try {
      const { shipment_number: _typed, ...rest } = form;
      const accessory_items = accPlan ? (accPlan.rows || []).map(r => {
        const typed = accQty[accKey(r)];
        return { ...r, qty_sent: typed === undefined || typed === '' ? r.qty_suggested : Number(typed),
                 auto: typed === undefined || typed === '' };
      }) : undefined;
      const data = await apiPost('/vendor-shipments', {
        ...rest, ...docNumberPayload(numPolicy, 'shipment_number', _typed), shipment_type: 'NORMAL',
        ...(accessory_items ? { accessory_items } : {}) });
      const mi = data.material_issue;
      toast.success(
        `Shipment ${data.shipment_number || ''} dibuat`
        + ((data.po_vendor_assigned || []).length ? ` · vendor PO ${data.po_vendor_assigned.join(', ')} diisi ${data.vendor_name || ''}` : '')
        + (data.accessory_lines ? ` · ${data.accessory_lines} aksesoris ikut tercatat` : '')
        + (mi?.mi_number
            ? ` · pengeluaran material ${mi.mi_number} (${mi.material_lines} bahan) otomatis terbit & stok berkurang`
            : ''));
      if ((mi?.negative_stock_lines || []).length) {
        toast.warning(
          `${mi.negative_stock_lines.length} material kini bersaldo MINUS (${mi.negative_stock_lines.map(l => l.material_code).join(', ')}). ` +
          'Betulkan lewat stock opname.', { duration: 8000 });
      }
      setShowModal(false);
      fetchAll();
    } catch (err) { toast.error(err.message || 'Gagal membuat shipment'); }
  };

  const openDetail = async (row) => {
    try {
      const data = await apiGet(`/vendor-shipments/${row.id}`);
      setDetailData(data);

      // Build material timeline
      const timeline = [];
      timeline.push({ icon: '📦', text: `Shipment ${data.shipment_number} dibuat`, date: data.created_at, type: 'shipment' });
      if (data.status === 'Received') timeline.push({ icon: '✅', text: 'Material diterima vendor', date: data.updated_at, type: 'received' });
      if (data.inspection_status === 'Inspected') {
        timeline.push({ icon: '🔍', text: `Inspeksi selesai — Diterima: ${data.total_received || 0} pcs, Missing: ${data.total_missing || 0} pcs`, date: data.inspected_at, type: 'inspection' });
      }
      // Find material requests
      const allReqs = await apiGet('/material-requests?status=');
      const relReqs = Array.isArray(allReqs) ? allReqs.filter(r => r.original_shipment_id === row.id) : [];
      for (const req of relReqs) {
        timeline.push({
          icon: req.request_type === 'ADDITIONAL' ? '➕' : '🔄',
          text: `${req.request_type === 'ADDITIONAL' ? 'Permintaan Tambahan' : 'Permintaan Pengganti'} ${req.request_number} — Status: ${req.status}`,
          date: req.created_at, type: 'request'
        });
        if (req.child_shipment_id) {
          timeline.push({ icon: '🚚', text: `Child Shipment ${req.child_shipment_number} dikirim`, date: req.approved_at, type: 'child_shipment' });
        }
      }
      timeline.sort((a, b) => new Date(a.date) - new Date(b.date));
      setDetailTimeline(timeline);

      // Find child shipments
      const children = shipments.filter(s => s.parent_shipment_id === row.id);
      setDetailChildren(children);

      setShowDetail(true);
    } catch (e) { toast.error(e.message || 'Gagal memuat detail'); }
  };

  // ── Unduh dokumen PDF (satu jalur untuk semua jenis) ────────────────────────
  // Ditulis satu kali agar tombol Surat Jalan & Panduan Produk konsisten.
  // Catatan: `a` DIPASANG ke DOM dan `revokeObjectURL` DITUNDA — pola lama
  // (elemen lepas + revoke serentak) bisa membuat unduhan dibatalkan browser.
  const downloadPdf = async (type, id, filename, label) => {
    try {
      const res = await apiFetch(`/export-pdf?type=${type}&id=${id}`);
      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        try {
          const err = await res.json();
          const d = err?.detail;
          msg = typeof d === 'string' ? d : (d?.reason || d?.message || msg);
        } catch { /* biarkan msg default */ }
        toast.error(`Gagal mencetak ${label}: ${msg}`);
        return false;
      }
      const blob = await res.blob();
      if (!blob || blob.size === 0) { toast.error(`${label} kosong (0 byte)`); return false; }
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.style.display = 'none';
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 4000);
      toast.success(`${label} diunduh`);
      return true;
    } catch (e) {
      toast.error(e.message || `Gagal mencetak ${label}`);
      return false;
    }
  };

  const downloadDeliveryNote = (row) => downloadPdf(
    'vendor-shipment', row.id,
    `SJ-Material-${row.shipment_number || row.id}.pdf`, 'Surat Jalan',
  );

  // Panduan Produk & Proses Produksi (SOP) untuk artikel pada pengiriman ini —
  // sengaja diletakkan bersebelahan dengan tombol Surat Jalan supaya user tidak
  // perlu berpindah modul (permintaan owner).
  const downloadProductionGuide = (row) => downloadPdf(
    'production-guide', row.id,
    `Panduan-Produk-${row.shipment_number || row.id}.pdf`, 'Panduan Produk',
  );

  const handleDelete = async () => {
    const target = confirmDelete;
    try {
      await apiDelete(`/vendor-shipments/${target.id}`);
      setConfirmDelete(null);
      fetchAll();
    } catch (e) {
      setConfirmDelete(null);
      // 2026-11-02 (K10): SJ yang bahannya sudah keluar dikunci backend → arahkan ke Retur Material.
      const locked = /Retur Material/i.test(e.message || '');
      toast.error(e.message || 'Gagal menghapus', locked && onNavigate ? {
        duration: 12000,
        action: { label: 'Buka Retur Material', onClick: () => onNavigate('prod-material-returns', { vendor_shipment_id: target.id }) },
      } : undefined);
    }
  };

  const fmtDate = (d) => d ? new Date(d).toLocaleDateString('id-ID') : '-';

  // Remove old columns definition - now using custom hierarchical table

  const poOptions = pos
    // Phase 8.5: PO selector shows only POs assigned to the currently selected vendor.
    // 2026-11-07 (Tahap 6, PR4): + PO yang BELUM punya vendor (vendor opsional di PO internal) — dulu tidak
    // pernah muncul. Vendornya = vendor surat jalan ini, dan server ikut mencatatnya di PO.
    .filter(p => !form.vendor_id || !p.vendor_id || p.vendor_id === form.vendor_id)
    .map(p => ({
      value: p.id,
      label: `${p.po_number} – ${p.vendor_name || 'belum ada vendor'} – ${fmtDate(p.po_date)}`,
      sub: p.customer_name
    }));
  const selectedPoNoVendor = !!(selectedPO && !selectedPO.vendor_id);
  // K12: baris PO tanpa upah jahit — penjahit dipilih di sini, jadi upahnya harus ada dulu di form PO
  const poNoRate = selectedPoNoVendor ? poItems.filter(pi => !(Number(pi.cmt_price_snapshot) > 0)) : [];
  const shipNoRate = (form.items || []).filter(i => i.po_without_vendor && !(Number(i.cmt_price_snapshot) > 0));
  const openPoRates = () => {
    if (!selectedPO || !onNavigate) return;
    setShowModal(false);
    onNavigate(selectedPO.business_type === 'maklon' ? 'maklon-pos-engine' : 'prod-pos-internal',
      { edit_po_id: selectedPO.id, vendor_id: form.vendor_id });
  };

  // Separate parent shipments (no parent_shipment_id) from child shipments
  const parentShipments = shipments.filter(s => !s.parent_shipment_id);
  const childShipmentMap = shipments.reduce((acc, s) => {
    if (s.parent_shipment_id) {
      if (!acc[s.parent_shipment_id]) acc[s.parent_shipment_id] = [];
      acc[s.parent_shipment_id].push(s);
    }
    return acc;
  }, {});

  const [expandedRows, setExpandedRows] = useState({});
  const toggleRow = (id) => setExpandedRows(prev => ({ ...prev, [id]: !prev[id] }));
  const [search, setSearch] = useState('');
  // Identifier + filter Internal/Maklon — hanya relevan saat list menggabungkan kedua tipe
  // (portal produksi tidak meng-inject businessType, jadi data tergabung).
  const [bizFilter, setBizFilter] = useState('all');
  const showBizFilter = !businessType;
  const bizCounts = {
    all: parentShipments.length,
    internal: parentShipments.filter(s => s.business_type !== 'maklon').length,
    maklon: parentShipments.filter(s => s.business_type === 'maklon').length,
  };
  const filteredParents = parentShipments.filter(s =>
    (!search || s.shipment_number?.toLowerCase().includes(search.toLowerCase()) || s.vendor_name?.toLowerCase().includes(search.toLowerCase()))
    && (!showBizFilter || matchBiz(s.business_type, bizFilter))
  );
  // Phase 8.4 — sortable parent rows with persisted state
  const { sortedData: sortedParents, sortKey, sortDir, toggleSort } = useSortableTable(filteredParents, {
    storageKey: 'vendorShipments',
    defaultKey: 'shipment_date',
    defaultDir: 'desc',
  });

  return (
    <div className="space-y-4">
      {/* Info about request-driven child shipments */}
      <div className="bg-[hsl(var(--primary)/0.1)] border border-[hsl(var(--primary)/0.35)] rounded-xl p-3 text-sm text-[hsl(var(--primary))]">
        ℹ️ Shipment <strong>ADDITIONAL</strong> dan <strong>REPLACEMENT</strong> hanya dapat dibuat setelah vendor mengajukan permintaan dan admin menyetujuinya. Gunakan tab di atas untuk mengelola permintaan.
      </div>

      <div className="flex items-center justify-between gap-3">
        <input
          type="text" placeholder="Cari shipment atau vendor..."
          className="flex-1 max-w-xs border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--primary)/0.35)]"
          value={search} onChange={e => setSearch(e.target.value)}
        />
        <div className="flex items-center gap-2">
          {showBizFilter && <BizFilter value={bizFilter} onChange={setBizFilter} counts={bizCounts} />}
          <ImportExportPanel importType={null} exportType="vendor-shipments" />
          {canCreate && (
            <button onClick={() => { setForm({ shipment_number: '', delivery_note_number: '', vendor_id: '', shipment_date: todayWIB(), notes: '', items: [] }); setSelectedPO(null); setPoItems([]); setPoAccessories([]); setShowModal(true); }}
              className="flex items-center gap-2 px-4 py-2 bg-[hsl(var(--primary))] text-white rounded-lg text-sm hover:bg-[hsl(var(--primary)/0.9)]">
              <Plus className="w-4 h-4" /> Buat Shipment Normal
            </button>
          )}
        </div>
      </div>

      {/* Custom hierarchical table */}
      <div className="bg-card rounded-xl border border-border shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 border-b border-border">
            <tr>
              <th className="text-left px-4 py-2.5 text-xs font-semibold text-muted-foreground w-8"></th>
              <SortableHeader columnKey="shipment_number" sortKey={sortKey} sortDir={sortDir} onToggle={toggleSort} className="px-4 py-2.5 text-xs font-semibold text-muted-foreground">No. Shipment</SortableHeader>
              <SortableHeader columnKey="vendor_name" sortKey={sortKey} sortDir={sortDir} onToggle={toggleSort} className="px-4 py-2.5 text-xs font-semibold text-muted-foreground">Vendor</SortableHeader>
              <SortableHeader columnKey="shipment_date" sortKey={sortKey} sortDir={sortDir} onToggle={toggleSort} className="px-4 py-2.5 text-xs font-semibold text-muted-foreground">Tanggal</SortableHeader>
              <th className="text-left px-4 py-2.5 text-xs font-semibold text-muted-foreground">Items</th>
              <SortableHeader columnKey="status" sortKey={sortKey} sortDir={sortDir} onToggle={toggleSort} className="px-4 py-2.5 text-xs font-semibold text-muted-foreground">Status</SortableHeader>
              <SortableHeader columnKey="inspection_status" sortKey={sortKey} sortDir={sortDir} onToggle={toggleSort} className="px-4 py-2.5 text-xs font-semibold text-muted-foreground">Inspeksi</SortableHeader>
              <th className="text-left px-4 py-2.5 text-xs font-semibold text-muted-foreground">Aksi</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/40">
            {sortedParents.length === 0 ? (
              <tr><td colSpan={8} className="px-4 py-8 text-center text-muted-foreground/70 text-sm">Tidak ada shipment</td></tr>
            ) : sortedParents.map(row => {
              const children = childShipmentMap[row.id] || [];
              const isExpanded = expandedRows[row.id];
              return [
                /* Parent row */
                <tr key={row.id} className="hover:bg-muted/60 transition-colors">
                  <td className="px-4 py-3">
                    {children.length > 0 && (
                      <button onClick={() => toggleRow(row.id)}
                        className="w-5 h-5 rounded flex items-center justify-center hover:bg-muted transition-colors text-muted-foreground">
                        <span className="text-xs">{isExpanded ? '▼' : '▶'}</span>
                      </button>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-bold text-[hsl(var(--primary))] tabular-nums whitespace-nowrap">{row.shipment_number}</span>
                      <BizBadge type={row.business_type} size="xs" />
                      {/* FASE 22 — tipe surat jalan non-normal (REWORK/ADDITIONAL/REPLACEMENT)
                          dulu tidak terlihat di baris induk, jadi admin tidak bisa
                          membedakan kiriman rework dari kiriman material biasa. */}
                      {row.shipment_type && !['NORMAL', 'REGULAR', ''].includes(String(row.shipment_type)) && (
                        <span className={`px-1.5 py-0.5 rounded text-xs font-bold whitespace-nowrap ${
                          row.shipment_type === 'REWORK' ? 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]'
                          : row.shipment_type === 'ADDITIONAL' ? 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]'
                          : 'bg-[hsl(var(--destructive)/0.15)] text-[hsl(var(--destructive))]'}`}
                          title={row.rework_permak_number ? `Rework dari permak ${row.rework_permak_number}` : row.shipment_type}>
                          {row.shipment_type === 'REWORK' ? '🔄 REWORK' : row.shipment_type}
                        </span>
                      )}
                      {children.length > 0 && (
                        <span className="px-1.5 py-0.5 bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))] rounded text-xs font-medium whitespace-nowrap">
                          +{children.length} child
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-foreground/90">{row.vendor_name}</td>
                  <td className="px-4 py-3 text-muted-foreground text-xs">{fmtDate(row.shipment_date)}</td>
                  <td className="px-4 py-3">
                    <span className="px-2 py-0.5 bg-muted text-foreground/90 text-xs rounded-full font-medium">{(row.items || []).length} item</span>
                  </td>
                  <td className="px-4 py-3"><StatusBadge status={row.status} /></td>
                  <td className="px-4 py-3">
                    {row.inspection_status ? (
                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${row.inspection_status === 'Inspected' ? 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]' : 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]'}`}>{row.inspection_status}</span>
                    ) : <span className="text-xs text-muted-foreground/50">Belum</span>}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1">
                      <button onClick={() => openDetail(row)} className="p-1.5 rounded hover:bg-[hsl(var(--primary)/0.1)] text-[hsl(var(--primary))]" title="Detail"><Eye className="w-4 h-4" /></button>
                      <button onClick={() => downloadDeliveryNote(row)} className="p-1.5 rounded hover:bg-[hsl(var(--success)/0.1)] text-[hsl(var(--success))]" title="Cetak Surat Jalan (PDF) — termasuk aksesoris" data-testid={`vendor-shipment-print-sj-${row.id}`}><Download className="w-4 h-4" /></button>
                      <button onClick={() => downloadProductionGuide(row)} className="p-1.5 rounded hover:bg-[hsl(var(--primary)/0.1)] text-[hsl(var(--primary))]" title="Cetak Panduan Produk & Proses Produksi (PDF)" data-testid={`vendor-shipment-print-guide-${row.id}`}><BookOpen className="w-4 h-4" /></button>
                      {/* Phase 16: Vendor dapat buat permintaan manual untuk shipment yang sudah ter-inspeksi */}
                      {isVendor && row.inspection_status === 'Inspected' && (
                        <button
                          onClick={() => openManualRequest(row)}
                          disabled={loadingManualReq}
                          className="p-1.5 rounded hover:bg-[hsl(var(--warning)/0.1)] text-[hsl(var(--warning))] disabled:opacity-50"
                          title="Buat Permintaan Tambahan Manual"
                          data-testid={`manual-request-btn-${row.id}`}
                        >
                          <FilePlus className="w-4 h-4" />
                        </button>
                      )}
                      {canDelete && <button onClick={() => setConfirmDelete(row)} className="p-1.5 rounded hover:bg-[hsl(var(--destructive)/0.1)] text-[hsl(var(--destructive))]"><Trash2 className="w-4 h-4" /></button>}
                    </div>
                  </td>
                </tr>,
                /* Child rows (nested) */
                ...(isExpanded ? children.map(child => (
                  <tr key={child.id} className="bg-muted/40/60 hover:bg-muted/60">
                    <td className="px-4 py-2.5"></td>
                    <td className="px-4 py-2.5 pl-8">
                      <div className="flex items-center gap-2">
                        <div className="w-3 h-px bg-muted-foreground/30 mr-1" />
                        <span className="tabular-nums text-sm font-medium text-foreground/90">{child.shipment_number}</span>
                        <span className={`px-1.5 py-0.5 rounded text-xs font-bold ${child.shipment_type === 'ADDITIONAL' ? 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]' : 'bg-[hsl(var(--destructive)/0.15)] text-[hsl(var(--destructive))]'}`}>{child.shipment_type}</span>
                      </div>
                    </td>
                    <td className="px-4 py-2.5 text-muted-foreground text-xs">{child.vendor_name}</td>
                    <td className="px-4 py-2.5 text-muted-foreground text-xs">{fmtDate(child.shipment_date)}</td>
                    <td className="px-4 py-2.5">
                      <span className="px-2 py-0.5 bg-muted text-muted-foreground text-xs rounded-full">{(child.items || []).length} item</span>
                    </td>
                    <td className="px-4 py-2.5"><StatusBadge status={child.status} /></td>
                    <td className="px-4 py-2.5">
                      {child.inspection_status ? (
                        <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${child.inspection_status === 'Inspected' ? 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]' : 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]'}`}>{child.inspection_status}</span>
                      ) : <span className="text-xs text-muted-foreground/50">Belum</span>}
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-1">
                        <button onClick={() => openDetail(child)} className="p-1.5 rounded hover:bg-[hsl(var(--primary)/0.1)] text-[hsl(var(--primary))]" title="Detail"><Eye className="w-4 h-4" /></button>
                        <button onClick={() => downloadDeliveryNote(child)} className="p-1.5 rounded hover:bg-[hsl(var(--success)/0.1)] text-[hsl(var(--success))]" title="Cetak Surat Jalan (PDF) — termasuk aksesoris" data-testid={`vendor-shipment-print-sj-${child.id}`}><Download className="w-4 h-4" /></button>
                        <button onClick={() => downloadProductionGuide(child)} className="p-1.5 rounded hover:bg-[hsl(var(--primary)/0.1)] text-[hsl(var(--primary))]" title="Cetak Panduan Produk & Proses Produksi (PDF)" data-testid={`vendor-shipment-print-guide-${child.id}`}><BookOpen className="w-4 h-4" /></button>
                        {/* Phase 16: Vendor manual request untuk child yang sudah ter-inspeksi */}
                        {isVendor && child.inspection_status === 'Inspected' && (
                          <button
                            onClick={() => openManualRequest(child)}
                            disabled={loadingManualReq}
                            className="p-1.5 rounded hover:bg-[hsl(var(--warning)/0.1)] text-[hsl(var(--warning))] disabled:opacity-50"
                            title="Buat Permintaan Tambahan Manual"
                            data-testid={`manual-request-btn-${child.id}`}
                          >
                            <FilePlus className="w-4 h-4" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                )) : [])
              ];
            })}
          </tbody>
        </table>
      </div>

      {/* Create Shipment Modal */}
      {showModal && (
        <Modal title="Buat Vendor Shipment" onClose={() => setShowModal(false)} size="xl">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <DocNumberField policy={numPolicy} value={form.shipment_number}
                onChange={v => setForm({ ...form, shipment_number: v })}
                testId="vendor-shipment-number" label="No. Shipment" />
              <div>
                <label className="block text-sm font-medium text-foreground/90 mb-1">No. Surat Jalan</label>
                <input className="w-full border border-border rounded-lg px-3 py-2 text-sm" value={form.delivery_note_number} onChange={e => setForm({...form, delivery_note_number: e.target.value})} placeholder="SJ-001" />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-foreground/90 mb-1">Vendor *</label>
                <SearchableSelect options={vendors.map(v => ({ value: v.id, label: v.garment_name, sub: v.garment_code }))} value={form.vendor_id} onChange={val => {
                  // Phase 8.5: clear PO selection + items when vendor changes to avoid
                  // carrying over a PO not assigned to the new vendor.
                  if (val !== form.vendor_id) {
                    setForm(f => ({...f, vendor_id: val, items: []}));
                    setSelectedPO(null);
                    setPoItems([]);
                    setPoAccessories([]);
                  } else {
                    setForm({...form, vendor_id: val});
                  }
                }} placeholder="Pilih Vendor" required data-testid="vship-vendor-select" />
              </div>
              <div>
                <label className="block text-sm font-medium text-foreground/90 mb-1">Tanggal Pengiriman</label>
                <GlassInput type="date" value={form.shipment_date} onChange={e => setForm({...form, shipment_date: e.target.value})} />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-foreground/90 mb-1">Load Item dari PO</label>
              <SearchableSelect
                options={poOptions}
                value={selectedPO?.id || ''}
                onChange={val => loadPOItems(val)}
                placeholder={form.vendor_id ? 'Pilih PO untuk load items' : 'Pilih vendor terlebih dahulu'}
                disabled={!form.vendor_id}
                data-testid="vship-po-select"
              />
              {form.vendor_id && poOptions.length === 0 && (
                <p className="text-xs text-[hsl(var(--warning))] mt-1">Tidak ada PO aktif untuk vendor ini (atau sudah fully shipped).</p>
              )}
              {selectedPoNoVendor && (
                <p className="text-xs text-muted-foreground mt-1" data-testid="vship-po-no-vendor">
                  PO {selectedPO.po_number} belum punya vendor — vendor pengiriman ini akan dicatat sebagai vendor PO.
                </p>
              )}
              {selectedPoNoVendor && poNoRate.length > 0 && (
                <Notice tone="warning" icon={AlertTriangle} className="mt-2" testId="vship-po-no-rate"
                  title={`Upah jahit belum diisi untuk ${poNoRate.length} baris PO ${selectedPO.po_number}`}
                  action={onNavigate ? (
                    <Button type="button" variant="link" size="sm" onClick={openPoRates} data-testid="vship-po-no-rate-link">
                      Isi upah di form PO
                    </Button>
                  ) : null}>
                  Penjahit dipilih saat kirim, jadi upah jahit per pcs untuk penjahit ini diisi dulu di form PO
                  ({poNoRate.slice(0, 4).map(pi => pi.sku || pi.product_name).join(', ')}{poNoRate.length > 4 ? ` +${poNoRate.length - 4} lagi` : ''}).
                  Baris yang sudah berupah boleh dikirim.
                </Notice>
              )}
              {selectedPoNoVendor && poItems.length > 0 && poNoRate.length === 0 && (
                <p className="text-xs text-muted-foreground mt-1" data-testid="vship-po-rate-ok">
                  Upah jahit semua baris PO sudah diisi ({poItems.slice(0, 3).map(pi => `${pi.sku || pi.product_name} ${formatRupiah(Number(pi.cmt_price_snapshot) || 0)}`).join(', ')}{poItems.length > 3 ? ' …' : ''}).
                </p>
              )}
            </div>

            {poItems.length > 0 && (
              <div className="border border-border rounded-xl overflow-hidden">
                <div className="bg-muted/40 px-3 py-2 flex items-center justify-between">
                  <span className="text-xs font-semibold text-muted-foreground">Items dari PO (klik untuk tambah)</span>
                  <button type="button" onClick={() => { poItems.forEach(pi => addShipmentItem(pi)); }}
                    className="text-xs bg-[hsl(var(--primary))] text-white px-3 py-1 rounded-lg hover:bg-[hsl(var(--primary)/0.9)] font-medium" data-testid="add-all-items-btn">
                    + Add All Items ({poItems.length})
                  </button>
                </div>
                <div className="divide-y divide-border/60">
                  {poItems.map(pi => {
                    const remaining = typeof pi.remaining_qty_to_vendor === 'number' ? pi.remaining_qty_to_vendor : pi.qty;
                    const alreadySent = typeof pi.total_sent_to_vendor === 'number' ? pi.total_sent_to_vendor : 0;
                    return (
                      <div key={pi.id} className="flex items-center justify-between px-3 py-2 hover:bg-[hsl(var(--primary)/0.1)] cursor-pointer transition-colors" onClick={() => addShipmentItem(pi)}>
                        <div>
                          <span className="text-sm font-medium text-foreground/90">{pi.product_name}</span>
                          <span className="text-xs text-muted-foreground/70 ml-2">{pi.sku} • {pi.size}/{pi.color}</span>
                          {pi.serial_number && <span className="text-xs text-[hsl(var(--warning))] ml-2">SN: {pi.serial_number}</span>}
                        </div>
                        <div className="text-right">
                          <span className="text-xs text-muted-foreground font-medium">{pi.qty?.toLocaleString('id-ID')} pcs</span>
                          <div className="text-[11px] text-muted-foreground/70 mt-0.5">
                            <span className="text-[hsl(var(--success))] font-semibold">sisa: {remaining.toLocaleString('id-ID')}</span>
                            {alreadySent > 0 && <span className="ml-1 text-muted-foreground/70">(terkirim: {alreadySent})</span>}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Aksesoris ikut kiriman ini (dari BOM PO, dihitung otomatis — 2026-11-05) */}
            {form.items.length > 0 && accPlan && ((accPlan.rows || []).length > 0 || (accPlan.warnings || []).length > 0) && (
              <GlassCard className="p-0 overflow-hidden" data-testid="shipment-accessory-plan">
                <div className="px-3 py-2 border-b border-[var(--glass-border)]">
                  <p className="text-sm font-semibold text-foreground">Aksesoris ikut kiriman ini ({(accPlan.rows || []).length})</p>
                  <p className="text-xs text-muted-foreground">
                    Dihitung dari BOM PO sebanding qty yang dikirim ({accPlan.shipment_qty || 0} dari {accPlan.po_qty || 0} pcs).
                    Ubah jumlahnya bila perlu — yang tersimpan tercetak di Surat Jalan kiriman ini.
                  </p>
                </div>
                {(accPlan.warnings || []).length > 0 && (
                  <Notice tone="warning" className="m-3" title="Perlu diperiksa">
                    {(accPlan.warnings || []).slice(0, 4).join(' · ')}
                  </Notice>
                )}
                {(accPlan.rows || []).length > 0 && (
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-muted-foreground border-b border-[var(--glass-border)]">
                        <th className="text-left px-3 py-1.5 font-normal">Aksesoris</th>
                        <th className="text-right px-3 py-1.5 font-normal">Kebutuhan PO</th>
                        <th className="text-right px-3 py-1.5 font-normal">Sudah dikirim</th>
                        <th className="text-right px-3 py-1.5 font-normal">Ikut kiriman ini</th>
                      </tr>
                    </thead>
                    <tbody>
                      {accPlan.rows.map(r => (
                        <tr key={accKey(r)} className="border-b border-[var(--glass-border)] last:border-0"
                          data-testid={`shipment-acc-${r.accessory_code || r.accessory_name}`}>
                          <td className="px-3 py-1.5">
                            <span className="font-medium text-foreground">{r.accessory_name}</span>
                            {r.accessory_code && <span className="ml-2 tabular-nums text-muted-foreground">{r.accessory_code}</span>}
                            {r.unlinked && <span className="ml-2 text-[hsl(var(--warning))]">belum tertaut master</span>}
                          </td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{Number(r.qty_needed || 0).toLocaleString('id-ID')} {r.unit}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{Number(r.qty_sent_before || 0).toLocaleString('id-ID')}</td>
                          <td className="px-3 py-1.5 text-right">
                            <GlassInput type="number" min="0" step="any" className="w-24 text-right ml-auto"
                              value={accQty[accKey(r)] ?? r.qty_suggested}
                              onChange={e => setAccQty(q => ({ ...q, [accKey(r)]: e.target.value }))}
                              data-testid={`shipment-acc-qty-${r.accessory_code || r.accessory_name}`} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </GlassCard>
            )}

            {/* PO Accessories Display — sebelum item garmen dipilih: kebutuhan seluruh PO */}
            {form.items.length === 0 && poAccessories.length > 0 && (
              <div className="border border-[hsl(var(--success)/0.35)] rounded-xl overflow-hidden" data-testid="po-accessories-section">
                <div className="bg-[hsl(var(--success)/0.1)] px-3 py-2">
                  <span className="text-xs font-semibold text-[hsl(var(--success))] flex items-center gap-1.5">
                    Kebutuhan aksesoris PO ({poAccessories.length} item)
                  </span>
                  <span className="text-xs text-[hsl(var(--success))] mt-0.5 block">Kebutuhan seluruh PO. Pilih item garmen di bawah — jatah aksesoris untuk kiriman ini dihitung otomatis.</span>
                </div>
                <div className="divide-y divide-[hsl(var(--success)/0.35)]">
                  {poAccessories.map((acc, idx) => (
                    <div key={acc.id || idx} className="flex items-center justify-between px-3 py-2 bg-card hover:bg-[hsl(var(--success)/0.4)] transition-colors">
                      <div>
                        <span className="text-sm font-medium text-foreground/90">{acc.accessory_name}</span>
                        <span className="text-xs text-[hsl(var(--success))] ml-2 tabular-nums">{acc.accessory_code || ''}</span>
                        {acc.notes && <span className="text-xs text-muted-foreground/70 ml-2">({acc.notes})</span>}
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-muted-foreground font-bold">{(acc.qty_needed || 0).toLocaleString('id-ID')}</span>
                        <span className="text-xs text-muted-foreground/70">{acc.unit || 'pcs'}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {form.items.length > 0 && (
              <div>
                <label className="block text-sm font-semibold text-foreground/90 mb-2">Items Shipment ({form.items.length})</label>
                <div className="space-y-2">
                  {form.items.map((item, idx) => {
                    const maxQty = typeof item.remaining_qty_to_vendor === 'number' ? item.remaining_qty_to_vendor : undefined;
                    const over = maxQty !== undefined && item.qty_sent > maxQty;
                    return (
                      <GlassPanel key={idx} className={`flex items-center justify-between px-3 py-2 ${over ? 'bg-[hsl(var(--destructive)/0.1)] border-[hsl(var(--destructive)/0.35)]' : ''}`}>
                        <div>
                          <span className="text-sm font-medium text-foreground">{item.product_name}</span>
                          <span className="text-xs text-muted-foreground ml-2">{item.sku} • {item.size}/{item.color}</span>
                          {item.serial_number && <span className="text-xs text-[hsl(var(--warning))] ml-2 tabular-nums">SN: {item.serial_number}</span>}
                          {maxQty !== undefined && (
                            <span className={`text-xs ml-2 font-semibold ${over ? 'text-[hsl(var(--destructive))]' : 'text-[hsl(var(--success))]'}`}>
                              sisa: {maxQty.toLocaleString('id-ID')}
                            </span>
                          )}
                          {over && <span className="block text-xs text-[hsl(var(--destructive))] mt-0.5">Qty melebihi sisa ke vendor. Kurangi qty atau gunakan permintaan ADDITIONAL.</span>}
                        </div>
                        <div className="flex items-center gap-2">
                          <input type="number" min="1" max={maxQty || undefined} value={item.qty_sent}
                            onChange={e => {
                              const v = Number(e.target.value);
                              const items = [...form.items];
                              items[idx].qty_sent = v;
                              setForm(f => ({...f, items}));
                            }}
                            className={`w-20 border rounded px-2 py-1 text-xs text-right ${over ? 'border-[hsl(var(--destructive)/0.35)]' : 'border-border'}`} />
                          <button type="button" onClick={() => removeItem(idx)} className="text-[hsl(var(--destructive))] hover:text-[hsl(var(--destructive))] text-xs">✕</button>
                        </div>
                      </GlassPanel>
                    );
                  })}
                </div>
              </div>
            )}

            {/* ── FASE H-1 — MATERIAL YANG AKAN KELUAR DARI GUDANG ────────────
                Mengirim material ke CMT sekarang memotong stok gudang + menerbitkan
                dokumen pengeluaran + jurnal. Panel ini menampilkan angkanya SEBELUM
                Simpan, supaya kekurangan stok tidak baru diketahui saat ditolak. */}
            {form.items.length > 0 && (
              <GlassCard className="overflow-hidden" data-testid="material-preview-panel">
                <div className="px-3 py-2 bg-muted/40 border-b border-border/60 flex items-center justify-between gap-2 flex-wrap">
                  <span className="text-xs font-bold text-foreground">
                    Material yang akan KELUAR dari gudang
                  </span>
                  {matLoading ? (
                    <span className="text-xs text-[hsl(var(--primary))]" data-testid="material-preview-loading">Menghitung dari BOM…</span>
                  ) : matPreview?.applicable ? (
                    <span className={`text-xs font-semibold ${matPreview.has_shortage ? (matPreview.blocking ? 'text-[hsl(var(--destructive))]' : 'text-[hsl(var(--warning))]') : 'text-[hsl(var(--success))]'}`}
                      data-testid="material-preview-status">
                      {matPreview.has_shortage
                        ? (matPreview.blocking
                            ? 'Stok tidak cukup — surat jalan akan ditolak'
                            : 'Stok kurang — akan MINUS (mode sementara sebelum opname), surat jalan tetap dibuat')
                        : `${matPreview.materials.length} bahan · nilai Rp ${Number(matPreview.total_value || 0).toLocaleString('id-ID')}`}
                    </span>
                  ) : null}
                </div>
                {!matLoading && matPreview && !matPreview.applicable && (
                  <p className="px-3 py-2.5 text-xs text-muted-foreground" data-testid="material-preview-na">
                    {matPreview.reason || 'Tidak ada material gudang yang dipotong untuk kiriman ini.'}
                  </p>
                )}
                {!matLoading && matPreview?.applicable && (
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs" data-testid="material-preview-table">
                      <thead className="bg-muted/30">
                        <tr>
                          <th className="text-left px-3 py-1.5 text-muted-foreground">Kode</th>
                          <th className="text-left px-3 py-1.5 text-muted-foreground">Material</th>
                          <th className="text-right px-3 py-1.5 text-muted-foreground">Keluar</th>
                          <th className="text-right px-3 py-1.5 text-muted-foreground">Stok Tersedia</th>
                          <th className="text-right px-3 py-1.5 text-muted-foreground">Nilai</th>
                        </tr>
                      </thead>
                      <tbody>
                        {matPreview.materials.map(m => (
                          <tr key={m.code} className={`border-t border-border/50 ${m.shortage ? (m.blocking ? 'bg-[hsl(var(--destructive)/0.1)] ' : 'bg-[hsl(var(--warning)/0.1)] ') : ''}`}
                            data-testid={`material-preview-row-${m.code}`}>
                            <td className="px-3 py-1.5 tabular-nums text-[hsl(var(--primary))]">{m.code}</td>
                            <td className="px-3 py-1.5 text-foreground/90">
                              {m.name}
                              {m.shortage && m.problem && (
                                <span className={`ml-1 font-medium ${m.blocking ? 'text-[hsl(var(--destructive))]' : 'text-[hsl(var(--warning))]'}`}>({m.problem})</span>
                              )}
                            </td>
                            <td className="px-3 py-1.5 text-right font-semibold text-[hsl(var(--warning))]">
                              {Number(m.qty_required).toLocaleString('id-ID')} {m.unit}
                            </td>
                            <td className={`px-3 py-1.5 text-right ${m.shortage ? (m.blocking ? 'text-[hsl(var(--destructive))] font-bold' : 'text-[hsl(var(--warning))] font-bold') : 'text-muted-foreground'}`}>
                              {Number(m.available).toLocaleString('id-ID')} {m.unit}
                            </td>
                            <td className="px-3 py-1.5 text-right text-muted-foreground">
                              {m.value ? `Rp ${Number(m.value).toLocaleString('id-ID')}` : '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {(matPreview.bom_notes || []).length > 0 && (
                      <p className="px-3 py-2 text-xs text-[hsl(var(--warning))] border-t border-border/50">
                        Catatan BOM: {matPreview.bom_notes.join('; ')}
                      </p>
                    )}
                  </div>
                )}
              </GlassCard>
            )}

            <div>
              <label className="block text-sm font-medium text-foreground/90 mb-1">Catatan</label>
              <textarea rows="2" className="w-full border border-border rounded-lg px-3 py-2 text-sm" value={form.notes} onChange={e => setForm({...form, notes: e.target.value})} />
            </div>
            <div className="flex gap-3">
              <button type="submit" disabled={shipNoRate.length > 0} data-testid="vship-submit" className="flex-1 bg-[hsl(var(--primary))] text-white py-2 rounded-lg text-sm font-medium hover:bg-[hsl(var(--primary)/0.9)] disabled:opacity-50">Buat Shipment</button>
              <button type="button" onClick={() => setShowModal(false)} className="flex-1 border border-border py-2 rounded-lg text-sm hover:bg-muted/60">Batal</button>
            </div>
          </form>
        </Modal>
      )}

      {/* Shipment Detail Modal */}
      {showDetail && detailData && (
        <Modal title={`Detail Shipment: ${detailData.shipment_number}`} onClose={() => setShowDetail(false)} size="xl">
          <div className="space-y-5">
            {/* PDF Export — Surat Jalan + Panduan Produk bersebelahan (1 layar, tanpa
                pindah modul). Aksesoris kini ikut tercetak di Surat Jalan. */}
            <div className="flex flex-wrap justify-end gap-2">
              <button
                onClick={() => downloadProductionGuide(detailData)}
                className="flex items-center gap-2 px-4 py-2 bg-[hsl(var(--primary))] text-white rounded-lg text-sm hover:bg-[hsl(var(--primary)/0.9)] font-medium"
                data-testid="vendor-shipment-print-guide-detail"
                title="Cetak Panduan Produk & Proses Produksi (SOP) untuk artikel pada pengiriman ini">
                <BookOpen className="w-4 h-4" /> Panduan Produk (PDF)
              </button>
              <button
                onClick={() => downloadDeliveryNote(detailData)}
                className="flex items-center gap-2 px-4 py-2 bg-[hsl(var(--destructive))] text-white rounded-lg text-sm hover:bg-[hsl(var(--destructive)/0.9)] font-medium"
                data-testid="vendor-shipment-print-sj-detail"
                title="Cetak Surat Jalan pengiriman material (termasuk tabel aksesoris)">
                <Download className="w-4 h-4" /> Cetak Surat Jalan (PDF)
              </button>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {[
                { l: 'No. Shipment', v: <span className="font-bold text-[hsl(var(--primary))] tabular-nums">{detailData.shipment_number}</span> },
                { l: 'Tipe', v: <span className={`px-2 py-0.5 rounded text-xs font-bold ${detailData.shipment_type === 'ADDITIONAL' ? 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]' : detailData.shipment_type === 'REPLACEMENT' ? 'bg-[hsl(var(--destructive)/0.15)] text-[hsl(var(--destructive))]' : 'bg-muted text-foreground/90'}`}>{detailData.shipment_type || 'NORMAL'}</span> },
                { l: 'Status', v: <StatusBadge status={detailData.status} /> },
                { l: 'Inspeksi', v: <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${detailData.inspection_status === 'Inspected' ? 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]' : 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]'}`}>{detailData.inspection_status || 'Belum Diinspeksi'}</span> },
                { l: 'Vendor', v: detailData.vendor_name },
                { l: 'Tanggal', v: fmtDate(detailData.shipment_date) },
                { l: 'Total Diterima', v: <span className="text-[hsl(var(--success))] font-bold">{detailData.total_received || 0} pcs</span> },
                { l: 'Total Missing', v: <span className={`font-bold ${(detailData.total_missing || 0) > 0 ? 'text-[hsl(var(--destructive))]' : 'text-muted-foreground/70'}`}>{detailData.total_missing || 0} pcs</span> },
              ].map(it => (
                <div key={it.l} className="bg-muted/40 rounded-lg p-3">
                  <p className="text-xs text-muted-foreground">{it.l}</p>
                  <div className="font-medium text-sm mt-0.5">{it.v}</div>
                </div>
              ))}
            </div>

            {/* Items Table */}
            <div>
              <h4 className="font-semibold text-foreground/90 mb-2">Item Shipment</h4>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-muted">
                      <th className="text-left px-3 py-2 text-xs">Produk</th>
                      <th className="text-left px-3 py-2 text-xs">SKU</th>
                      <th className="text-left px-3 py-2 text-xs text-[hsl(var(--warning))]">No. Seri</th>
                      <th className="text-left px-3 py-2 text-xs">Size/Warna</th>
                      <th className="text-right px-3 py-2 text-xs">Qty Dikirim</th>
                      <th className="text-left px-3 py-2 text-xs">PO</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(detailData.items || []).map(item => (
                      <tr key={item.id} className="border-t border-border/60">
                        <td className="px-3 py-2 font-medium">{item.product_name}</td>
                        <td className="px-3 py-2 tabular-nums text-xs text-[hsl(var(--primary))]">{item.sku || '-'}</td>
                        <td className="px-3 py-2 tabular-nums text-xs text-[hsl(var(--warning))] font-semibold">{item.serial_number || <span className="text-muted-foreground/50">—</span>}</td>
                        <td className="px-3 py-2 text-xs">{item.size}/{item.color}</td>
                        <td className="px-3 py-2 text-right font-bold">{item.qty_sent?.toLocaleString('id-ID')} pcs</td>
                        <td className="px-3 py-2 text-xs text-muted-foreground">{item.po_number || '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* PO Accessories Section */}
            {(detailData.po_accessories || []).length > 0 && (
              <div data-testid="shipment-detail-accessories">
                <h4 className="font-semibold text-foreground/90 mb-2 flex items-center gap-2">
                  <span className="w-5 h-5 bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))] rounded-full flex items-center justify-center text-xs font-bold">{detailData.po_accessories.length}</span>
                  Aksesoris terkait PO
                </h4>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-[hsl(var(--success)/0.1)]">
                        <th className="text-left px-3 py-2 text-xs text-[hsl(var(--success))] font-semibold">Aksesoris</th>
                        <th className="text-left px-3 py-2 text-xs text-[hsl(var(--success))] font-semibold">Kode</th>
                        <th className="text-right px-3 py-2 text-xs text-[hsl(var(--success))] font-semibold">Qty Dibutuhkan</th>
                        <th className="text-left px-3 py-2 text-xs text-[hsl(var(--success))] font-semibold">Satuan</th>
                        <th className="text-left px-3 py-2 text-xs text-[hsl(var(--success))] font-semibold">PO</th>
                        <th className="text-left px-3 py-2 text-xs text-[hsl(var(--success))] font-semibold">Catatan</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detailData.po_accessories.map((acc, idx) => (
                        <tr key={acc.id || idx} className="border-t border-[hsl(var(--success)/0.35)] hover:bg-[hsl(var(--success)/0.3)]">
                          <td className="px-3 py-2 font-medium text-foreground/90">{acc.accessory_name}</td>
                          <td className="px-3 py-2 tabular-nums text-xs text-[hsl(var(--success))]">{acc.accessory_code || '-'}</td>
                          <td className="px-3 py-2 text-right font-bold text-foreground">{(acc.qty_needed || 0).toLocaleString('id-ID')}</td>
                          <td className="px-3 py-2 text-xs text-muted-foreground">{acc.unit || 'pcs'}</td>
                          <td className="px-3 py-2 text-xs text-[hsl(var(--primary))] tabular-nums">{acc.po_number || '-'}</td>
                          <td className="px-3 py-2 text-xs text-muted-foreground/70">{acc.notes || '-'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Child Shipments */}
            {detailChildren.length > 0 && (
              <div>
                <h4 className="font-semibold text-foreground/90 mb-2">Child Shipments ({detailChildren.length})</h4>
                <div className="space-y-1">
                  {detailChildren.map(child => (
                    <div key={child.id} className="flex items-center justify-between bg-muted/40 rounded-lg px-3 py-2">
                      <div className="flex items-center gap-2">
                        <ChevronRight className="w-3.5 h-3.5 text-muted-foreground/70" />
                        <span className="tabular-nums text-sm font-medium text-[hsl(var(--primary))]">{child.shipment_number}</span>
                        <span className={`px-1.5 py-0.5 rounded text-xs font-bold ${child.shipment_type === 'ADDITIONAL' ? 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]' : 'bg-[hsl(var(--destructive)/0.15)] text-[hsl(var(--destructive))]'}`}>{child.shipment_type}</span>
                      </div>
                      <StatusBadge status={child.status} />
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Material Timeline */}
            {detailTimeline.length > 0 && (
              <div>
                <h4 className="font-semibold text-foreground/90 mb-3">Timeline Material</h4>
                <div className="relative">
                  <div className="absolute left-4 top-0 bottom-0 w-0.5 bg-muted" />
                  <div className="space-y-3">
                    {detailTimeline.map((event, idx) => (
                      <div key={idx} className="relative flex items-start gap-3 pl-10">
                        <div className="absolute left-2.5 -translate-x-1/2 w-5 h-5 flex items-center justify-center bg-card border-2 border-border rounded-full text-xs z-10">
                          {event.icon}
                        </div>
                        <div className="flex-1 bg-muted/40 rounded-lg px-3 py-2">
                          <p className="text-sm text-foreground/90">{event.text}</p>
                          <p className="text-xs text-muted-foreground/70 mt-0.5">{event.date ? fmtDate(event.date) : ''}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* File Attachments */}
            <FileAttachmentPanel entityType="vendor_shipment" entityId={detailData.id} />
          </div>
        </Modal>
      )}

      {/* 2026-11-02 (K10): teks konfirmasi mengikuti kunci backend — SJ yang bahannya sudah keluar tidak bisa dihapus */}
      {confirmDelete && <ConfirmDialog title="Hapus Shipment?" message={`Shipment "${confirmDelete.shipment_number}" akan dihapus. Surat jalan tidak bisa dihapus setelah bahan keluar — gunakan Retur Material untuk mengembalikan bahan ke gudang (stok kembali & jurnal dibalik), lalu hapus.`} onConfirm={handleDelete} onCancel={() => setConfirmDelete(null)} />}

      {/* Phase 16: Modal Buat Permintaan Manual (untuk shipment yang sudah ter-inspeksi) */}
      {manualReqShipment && (
        <AdditionalRequestModal
          shipment={manualReqShipment}
          defaultItems={manualReqItems}
          defaultReason={`Permintaan tambahan manual untuk shipment ${manualReqShipment.shipment_number}`}
          mode="manual"
          onClose={() => { setManualReqShipment(null); setManualReqItems([]); }}
          onSuccess={() => { setManualReqShipment(null); setManualReqItems([]); fetchAll(); }}
        />
      )}
    </div>
  );
}

// ─── MATERIAL REQUEST LIST (Additional/Replacement) ───────────────────────────
function MaterialRequestList({ userRole, requestType }) {
  const [requests, setRequests] = useState([]);
  const [showDetail, setShowDetail] = useState(false);
  const [selectedReq, setSelectedReq] = useState(null);
  const [adminNotes, setAdminNotes] = useState('');
  // 2026-09-24: aksesoris kurang (hasil inspeksi asal) yang ikut dikirim di child shipment — qty bisa diubah
  const [accRows, setAccRows] = useState([]);
  const [loading, setLoading] = useState(false);

  // Phase 16: state untuk modal Ajukan Ulang (resubmit)
  const [resubmitData, setResubmitData] = useState(null);

  const canApprove = ['superadmin', 'admin'].includes(userRole);
  const isVendor = userRole === 'vendor';
  const isAdditional = requestType === 'ADDITIONAL';

  useEffect(() => { fetchRequests(); }, [requestType]);

  const fetchRequests = async () => {
    try {
      const data = await apiGet(`/material-requests?request_type=${requestType}`);
      setRequests(Array.isArray(data) ? data : []);
    } catch (e) { setRequests([]); }
  };

  const handleAction = async (req, action) => {
    // Phase 16: admin_notes WAJIB diisi saat reject
    if (action === 'Rejected' && !adminNotes.trim()) {
      toast.error('Catatan admin wajib diisi saat menolak permintaan. Mohon jelaskan alasannya.');
      return;
    }
    setLoading(true);
    try {
      const data = await apiPut(`/material-requests/${req.id}`, {
        status: action, admin_notes: adminNotes,
        ...(action === 'Approved' ? { accessory_items: accRows.map(a => ({ ...a, qty_sent: Number(a.qty_sent) || 0 })) } : {}),
      });
      if (action === 'Approved' && data.child_shipment) {
        const nAcc = (data.child_shipment?.accessory_items || []).length;
        toast.success(`Disetujui! Child Shipment ${data.child_shipment_number} berhasil dibuat${nAcc ? ` · ${nAcc} aksesoris kurang ikut dikirim` : ''}.`);
      } else if (action === 'Rejected') {
        toast.info('Permintaan telah ditolak. Vendor akan diberitahu.');
      }
      setShowDetail(false);
      setAdminNotes('');
      fetchRequests();
    } catch (e) {
      toast.error(e.message || 'Gagal');
    } finally {
      setLoading(false);
    }
  };

  // Phase 16: buka modal Ajukan Ulang dengan prefilled items & reason
  const openResubmit = async (req) => {
    // Fetch shipment items untuk auto-fill serial_number jika hilang (data lama)
    let shipByKey = {};
    let shipById = {};
    if (req.original_shipment_id) {
      try {
        const fullShip = await apiGet(`/vendor-shipments/${req.original_shipment_id}`);
        for (const si of (fullShip.items || [])) {
          const k = `${si.sku || ''}|${si.size || ''}|${si.color || ''}`;
          if (!shipByKey[k] || (si.serial_number && !shipByKey[k].serial_number)) shipByKey[k] = si;
          if (si.id) shipById[si.id] = si;
        }
      } catch (e) { /* silent — backend punya defensive lookup */ }
    }
    const items = (req.items || []).map(it => {
      let serial = it.serial_number || '';
      let poItemId = it.po_item_id || '';
      let shipmentItemId = it.shipment_item_id || '';
      if (!serial || !poItemId) {
        let matched = null;
        if (shipmentItemId && shipById[shipmentItemId]) matched = shipById[shipmentItemId];
        else {
          const k = `${it.sku || ''}|${it.size || ''}|${it.color || ''}`;
          matched = shipByKey[k];
        }
        if (matched) {
          if (!serial) serial = matched.serial_number || '';
          if (!poItemId) poItemId = matched.po_item_id || '';
          if (!shipmentItemId) shipmentItemId = matched.id || '';
        }
      }
      return {
        shipment_item_id: shipmentItemId,
        po_item_id: poItemId,
        sku: it.sku || '',
        product_name: it.product_name || '',
        size: it.size || '',
        color: it.color || '',
        serial_number: serial,
        requested_qty: Number(it.requested_qty || 0),
        reason: it.reason || req.reason || '',
      };
    });
    setResubmitData({
      shipment: {
        id: req.original_shipment_id,
        shipment_number: req.original_shipment_number || '-',
        vendor_name: req.vendor_name,
        po_id: req.po_id,
        po_number: req.po_number,
      },
      defaultItems: items,
      defaultReason: req.reason || '',
      previousRequestId: req.id,
      previousRequestNumber: req.request_number,
    });
    setShowDetail(false);
  };

  const fmtDate = (d) => d ? new Date(d).toLocaleDateString('id-ID') : '-';

  const STATUS_COLORS = {
    'Pending': 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]',
    'Approved': 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]',
    'Rejected': 'bg-[hsl(var(--destructive)/0.15)] text-[hsl(var(--destructive))]',
  };

  const columns = [
    { key: 'request_number', label: 'No. Permintaan', render: v => <span className="font-bold tabular-nums text-sm">{v}</span> },
    { key: 'vendor_name', label: 'Vendor' },
    { key: 'original_shipment_number', label: 'Shipment Asal', render: v => <span className="tabular-nums text-[hsl(var(--primary))] text-xs">{v}</span> },
    { key: 'total_requested_qty', label: 'Total Qty', render: v => <span className="font-semibold">{v?.toLocaleString('id-ID')} pcs</span> },
    { key: 'created_at', label: 'Tgl. Permintaan', render: v => fmtDate(v) },
    { key: 'status', label: 'Status', render: v => (
      <span className={`px-2 py-1 rounded-full text-xs font-medium ${STATUS_COLORS[v] || 'bg-muted text-muted-foreground'}`}>{v}</span>
    )},
    // Rantai pengganti: bukan hanya nomornya, tapi sampai mana barangnya (INV-F28)
    { key: 'child_shipment_number', label: 'Surat Jalan Pengganti & Jejaknya',
      render: (_v, row) => <MaterialRequestTracker req={row} /> },
    { key: 'actions', label: 'Aksi', render: (_, row) => (
      <div className="flex items-center gap-1">
        <button onClick={() => { setSelectedReq(row); setAdminNotes(row.admin_notes || ''); setAccRows((row.accessory_shortages || []).map(a => ({ ...a }))); setShowDetail(true); }} className="p-1.5 rounded hover:bg-[hsl(var(--primary)/0.1)] text-[hsl(var(--primary))]" title="Detail" data-testid={`material-request-detail-btn-${row.id}`}><Eye className="w-4 h-4" /></button>
        {/* Phase 16: Vendor dapat Ajukan Ulang dari request yang Rejected (jika belum diresubmit) */}
        {isVendor && isAdditional && row.status === 'Rejected' && !row.resubmitted_as_id && (
          <button
            onClick={() => openResubmit(row)}
            className="p-1.5 rounded hover:bg-[hsl(var(--warning)/0.1)] text-[hsl(var(--warning))]"
            title="Ajukan Ulang"
            data-testid={`material-request-resubmit-btn-${row.id}`}
          >
            <RotateCcw className="w-4 h-4" />
          </button>
        )}
      </div>
    )}
  ];

  return (
    <div className="space-y-4">
      {/* Info box */}
      <Notice tone={isAdditional ? 'warning' : 'danger'}>
        {isAdditional
          ? '➕ Permintaan material tambahan dari vendor (akibat material kurang saat inspeksi). Setujui untuk membuat child shipment otomatis.'
          : '🔄 Permintaan material pengganti dari vendor (akibat laporan cacat). Setujui untuk membuat child shipment pengganti otomatis.'
        }
      </Notice>

      <DataTable columns={columns} data={requests} searchKeys={['request_number', 'vendor_name']} storageKey="vendorMaterialRequests" />

      {showDetail && selectedReq && (
        <Modal title={`Detail Permintaan: ${selectedReq.request_number}`} onClose={() => setShowDetail(false)} size="xl">
          <div className="space-y-4">
            {/* PDF Export */}
            <div className="flex justify-end">
              <button
                onClick={async () => {
                  try {
                    const res = await apiFetch(`/export-pdf?type=material-request&id=${selectedReq.id}`);
                    if (!res.ok) { toast.error('Gagal export PDF'); return; }
                    const blob = await res.blob();
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url; a.download = `Permohonan-${selectedReq.request_number}.pdf`; a.click();
                    URL.revokeObjectURL(url);
                  } catch (e) { toast.error('Gagal export PDF: ' + e.message); }
                }}
                className="flex items-center gap-2 px-4 py-2 bg-[hsl(var(--destructive))] text-white rounded-lg text-sm hover:bg-[hsl(var(--destructive)/0.9)] font-medium">
                📄 Export PDF (Surat Permohonan)
              </button>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              {[
                { l: 'No. Permintaan', v: <span className="font-bold tabular-nums">{selectedReq.request_number}</span> },
                { l: 'Tipe', v: <span className={`px-2 py-0.5 rounded text-xs font-bold ${isAdditional ? 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]' : 'bg-[hsl(var(--destructive)/0.15)] text-[hsl(var(--destructive))]'}`}>{selectedReq.request_type}</span> },
                { l: 'Status', v: <span className={`px-2 py-0.5 rounded text-xs font-bold ${STATUS_COLORS[selectedReq.status]}`}>{selectedReq.status}</span> },
                { l: 'Vendor', v: selectedReq.vendor_name },
                { l: 'Shipment Asal', v: <span className="tabular-nums text-[hsl(var(--primary))]">{selectedReq.original_shipment_number}</span> },
                { l: 'Total Qty', v: <span className="font-bold">{selectedReq.total_requested_qty?.toLocaleString('id-ID')} pcs</span> },
                { l: 'Tanggal', v: fmtDate(selectedReq.created_at) },
                { l: 'Alasan', v: selectedReq.reason || '-' },
                { l: 'Dibuat Oleh', v: selectedReq.created_by },
              ].map(it => (
                <div key={it.l} className="bg-muted/40 rounded-lg p-3">
                  <p className="text-xs text-muted-foreground">{it.l}</p>
                  <div className="font-medium text-sm mt-0.5">{it.v}</div>
                </div>
              ))}
            </div>

            {selectedReq.items?.length > 0 && (
              <div>
                <h4 className="font-semibold text-foreground/90 mb-2">Item yang Diminta</h4>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-muted">
                        <th className="text-left px-3 py-2 text-xs">Produk</th>
                        <th className="text-left px-3 py-2 text-xs">SKU</th>
                        <th className="text-left px-3 py-2 text-xs text-[hsl(var(--warning))]">No. Seri</th>
                        <th className="text-left px-3 py-2 text-xs">Size/Warna</th>
                        <th className="text-right px-3 py-2 text-xs">Qty Diminta</th>
                        <th className="text-left px-3 py-2 text-xs">Alasan</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedReq.items.map((item, idx) => (
                        <tr key={idx} className="border-t border-border/60">
                          <td className="px-3 py-2 font-medium">{item.product_name}</td>
                          <td className="px-3 py-2 tabular-nums text-xs text-[hsl(var(--primary))]">{item.sku || '-'}</td>
                          <td className="px-3 py-2 tabular-nums text-xs text-[hsl(var(--warning))] font-semibold">{item.serial_number || '—'}</td>
                          <td className="px-3 py-2 text-xs">{item.size}/{item.color}</td>
                          <td className="px-3 py-2 text-right font-bold">{Number(item.requested_qty)?.toLocaleString('id-ID')} pcs</td>
                          <td className="px-3 py-2 text-xs text-muted-foreground">{item.reason || '-'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {selectedReq.status === 'Pending' && accRows.length > 0 && (
              <div data-testid="material-request-accessories">
                <label className="block text-sm font-semibold text-[hsl(var(--success))] mb-2">Aksesoris Kurang (dari inspeksi) — ikut dikirim di child shipment</label>
                <div className="overflow-x-auto border border-[hsl(var(--success)/0.35)] rounded-lg">
                  <table className="w-full text-sm">
                    <thead className="bg-[hsl(var(--success)/0.1)]"><tr>
                      <th className="text-left px-3 py-2 text-xs">Aksesoris</th>
                      <th className="text-left px-3 py-2 text-xs">Kode</th>
                      <th className="text-right px-3 py-2 text-xs">Kurang</th>
                      <th className="text-right px-3 py-2 text-xs">Qty Dikirim</th>
                    </tr></thead>
                    <tbody>
                      {accRows.map((a, idx) => (
                        <tr key={a.accessory_id || a.accessory_code || idx} className="border-t border-border/60" data-testid={`material-request-acc-row-${a.accessory_code}`}>
                          <td className="px-3 py-2 font-medium">{a.accessory_name || '-'}</td>
                          <td className="px-3 py-2 tabular-nums text-xs text-[hsl(var(--success))]">{a.accessory_code || '-'}</td>
                          <td className="px-3 py-2 text-right text-[hsl(var(--destructive))] font-semibold">{a.missing_qty} {a.unit}</td>
                          <td className="px-3 py-2 text-right">
                            <input type="number" min="0" max={a.missing_qty} value={a.qty_sent}
                              data-testid={`material-request-acc-qty-${a.accessory_code}`}
                              onChange={e => setAccRows(rows => rows.map((r, i) => i === idx ? { ...r, qty_sent: e.target.value } : r))}
                              className="w-24 border border-border rounded px-2 py-1 text-right text-sm" />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="text-[11px] text-muted-foreground mt-1">Isi 0 bila aksesoris itu tidak ikut dikirim sekarang.</p>
              </div>
            )}
            {selectedReq.accessory_items_sent?.length > 0 && (
              <div className="text-xs text-[hsl(var(--success))] bg-[hsl(var(--success)/0.1)] border border-[hsl(var(--success)/0.35)] rounded-lg p-2" data-testid="material-request-acc-sent">
                Aksesoris ikut dikirim: {selectedReq.accessory_items_sent.map(a => `${a.accessory_code || a.accessory_name} ×${a.qty_sent}`).join(', ')}
              </div>
            )}

            {selectedReq.child_shipment_number && (
              <div className="bg-[hsl(var(--success)/0.1)] border border-[hsl(var(--success)/0.35)] rounded-lg p-3 text-sm text-[hsl(var(--success))]">
                ✅ Child shipment <strong>{selectedReq.child_shipment_number}</strong> sudah dibuat. Disetujui oleh {selectedReq.approved_by} pada {fmtDate(selectedReq.approved_at)}.
              </div>
            )}

            {/* Phase 16: Banner status Rejected */}
            {selectedReq.status === 'Rejected' && (
              <div className="bg-[hsl(var(--destructive)/0.1)] border border-[hsl(var(--destructive)/0.35)] rounded-lg p-3 text-sm">
                <p className="font-semibold text-[hsl(var(--destructive))] flex items-center gap-2">
                  <XCircle className="w-4 h-4" /> Permintaan Ditolak
                </p>
                {selectedReq.admin_notes && (
                  <p className="text-[hsl(var(--destructive))] mt-1.5">
                    <span className="font-medium">Alasan admin:</span> {selectedReq.admin_notes}
                  </p>
                )}
                {selectedReq.rejected_by && (
                  <p className="text-[hsl(var(--destructive))] text-xs mt-1">
                    Ditolak oleh {selectedReq.rejected_by} pada {fmtDate(selectedReq.rejected_at)}
                  </p>
                )}
                {isVendor && isAdditional && !selectedReq.resubmitted_as_id && (
                  <button
                    onClick={() => openResubmit(selectedReq)}
                    className="mt-3 flex items-center gap-2 bg-[hsl(var(--warning))] text-white px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-[hsl(var(--warning)/0.9)]"
                    data-testid="material-request-resubmit-detail-btn"
                  >
                    <RotateCcw className="w-3.5 h-3.5" /> Ajukan Ulang dengan Revisi
                  </button>
                )}
              </div>
            )}

            {/* Phase 16: Banner sudah diresubmit */}
            {selectedReq.resubmitted_as_number && (
              <div className="bg-[hsl(var(--primary)/0.1)] border border-[hsl(var(--primary)/0.35)] rounded-lg p-3 text-sm text-[hsl(var(--primary))]">
                ↻ Permintaan ini sudah diajukan ulang sebagai <strong className="tabular-nums">{selectedReq.resubmitted_as_number}</strong>
              </div>
            )}

            {/* Phase 16: Banner asal dari resubmit */}
            {selectedReq.previous_request_number && (
              <div className="bg-[hsl(var(--primary)/0.1)] border border-[hsl(var(--primary)/0.35)] rounded-lg p-3 text-sm text-[hsl(var(--primary))]">
                ↻ Permintaan ini merupakan resubmit dari <strong className="tabular-nums">{selectedReq.previous_request_number}</strong>
              </div>
            )}

            {canApprove && selectedReq.status === 'Pending' && (
              <div className="space-y-3 pt-3 border-t border-border">
                <div>
                  <label className="block text-sm font-medium text-foreground/90 mb-1">
                    Catatan Admin <span className="text-[hsl(var(--destructive))]">(wajib jika menolak)</span>
                  </label>
                  <textarea
                    rows="2"
                    className="w-full border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--primary)/0.35)]"
                    value={adminNotes}
                    onChange={e => setAdminNotes(e.target.value)}
                    placeholder="Catatan untuk vendor (wajib diisi saat menolak)..."
                    data-testid="material-request-admin-notes"
                  />
                </div>
                <div className="flex gap-3">
                  <button
                    onClick={() => handleAction(selectedReq, 'Approved')}
                    disabled={loading}
                    className="flex-1 flex items-center justify-center gap-2 bg-[hsl(var(--success))] text-white py-2 rounded-lg text-sm font-medium hover:bg-[hsl(var(--success)/0.9)] disabled:opacity-50"
                    data-testid="material-request-approve-btn"
                  >
                    <CheckCircle className="w-4 h-4" /> {loading ? 'Memproses...' : `Setujui & Buat Child Shipment`}
                  </button>
                  <button
                    onClick={() => handleAction(selectedReq, 'Rejected')}
                    disabled={loading || !adminNotes.trim()}
                    title={!adminNotes.trim() ? 'Isi catatan admin terlebih dahulu' : ''}
                    className="flex-1 flex items-center justify-center gap-2 bg-[hsl(var(--destructive))] text-white py-2 rounded-lg text-sm font-medium hover:bg-[hsl(var(--destructive)/0.9)] disabled:opacity-50 disabled:cursor-not-allowed"
                    data-testid="material-request-reject-btn"
                  >
                    <XCircle className="w-4 h-4" /> Tolak
                  </button>
                </div>
                {!adminNotes.trim() && (
                  <p className="text-xs text-[hsl(var(--warning))] flex items-center gap-1">
                    <AlertTriangle className="w-3 h-3" /> Tombol &quot;Tolak&quot; akan aktif setelah Anda mengisi catatan admin.
                  </p>
                )}
              </div>
            )}
          </div>
        </Modal>
      )}

      {/* Phase 16: Modal Ajukan Ulang (Resubmit) */}
      {resubmitData && (
        <AdditionalRequestModal
          shipment={resubmitData.shipment}
          defaultItems={resubmitData.defaultItems}
          defaultReason={resubmitData.defaultReason}
          previousRequestId={resubmitData.previousRequestId}
          previousRequestNumber={resubmitData.previousRequestNumber}
          mode="resubmit"
          onClose={() => setResubmitData(null)}
          onSuccess={() => { setResubmitData(null); fetchRequests(); }}
        />
      )}
    </div>
  );
}

/**
 * Penerimaan Barang (GR) — pintu masuk seluruh stok gudang.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout (dulu kepala buatan "Goods Receiving" + dua spanduk +
 * kotak "Langkah berikutnya" yang mendorong tabel ke bawah); daftar = TabelData (kartu ringkas di HP; tampilan
 * "Kartu" besar di layar lebar dihapus) dengan pilihan urutan; unduhan Excel + CSV; form penerimaan = FormPopup
 * panjang; detail/konfirmasi = DetailPopup; hapus lewat confirmDialog; tanggal kedaluwarsa = DatePicker.
 * Isian, aturan validasi, dan API tidak berubah.
 */
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import DatePicker from '@/components/ui/date-picker';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import {
  ArrowDownToLine, Plus, Eye, CheckCircle, Trash2,
  Search, RefreshCw, AlertCircle, MapPin, Warehouse, ScanLine, Loader2,
} from 'lucide-react';
import { Combobox } from './Combobox';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';
// Sprint A.1: UniversalScanner SSOT
import UniversalScanner from './scanner/UniversalScanner';
import ScanResult from './scanner/ScanResult';
import { sameScanCode, scanFeedback } from './scanner/scanCode';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
// FASE H-5 — rincian gulungan kain diisi DI SINI (pintu masuk kain), nomor roll otomatis.
import RollLinesEditor from './warehouse/RollLinesEditor';
import { isRollUnit, acceptedOf, rollLinesState, fmtQty } from './warehouse/rollLines';
import { toast } from 'sonner';
// 2026-11-06 (Tahap 2): harga GR tanpa PO hanya diisi Keuangan (cermin core/roles.FINANCE_ROLES)
import { isCurrentUserFinance } from '../../lib/financeRoles';

const fmtDate = (d) => d ? new Date(d).toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '-';

// Status GR dalam bahasa staf (dulu kode mentah "draft/received" tampil di layar)
const STATUS_GR = {
  draft:      { label: 'Draf', tone: 'muted' },
  inspecting: { label: 'Diperiksa', tone: 'warning' },
  received:   { label: 'Diterima', tone: 'success' },
  failed:     { label: 'Gagal', tone: 'danger' },
};
const statusGRLabel = (s) => (STATUS_GR[s] || {}).label || s || '—';
function StatusGR({ status }) {
  const m = STATUS_GR[status] || { label: status || '—', tone: 'default' };
  return <StatusBadge status={status} label={m.label} tone={m.tone} />;
}
// Pilihan urutan daftar (dulu tombol di kepala kolom): kunci:arah
const URUTAN = [
  ['created_at:desc', 'Tanggal terbaru'], ['created_at:asc', 'Tanggal terlama'],
  ['receipt_number:asc', 'No. penerimaan'], ['source_label:asc', 'Supplier A–Z'],
  ['status:asc', 'Status'], ['item_count:desc', 'Jumlah item terbanyak'],
  ['received_total:desc', 'Qty diterima terbanyak'], ['rejected_total:desc', 'Qty ditolak terbanyak'],
];

const EMPTY_ITEM = () => ({
  product_name: '', sku: '',
  material_id: '', material_name: '',
  expected_qty: 0, received_qty: 0, rejected_qty: 0, unit: 'pcs',
  lot_number: '',   // U7: lot tracking
  expiry_date: '',  // U7: expiry date
  reject_reason: '', // FASE 6: alasan reject → dibawa ke Karantina QC
  rolls: [],        // FASE H-5: rincian gulungan (kain/benang) — nomor roll otomatis
  unit_price: '',   // 2026-11-02 (K11): harga satuan WAJIB untuk penerimaan tanpa PO
});

// 2026-11-02 (K11): alasan reject FISIK → Karantina QC; alasan DOKUMEN/KUANTITAS → catatan saja
// (tidak menambah stok; sisa PO tetap terbuka). Jenisnya dari backend (`kind` kategori reject).
function rejectHint(cats, code, qty, unit) {
  const kind = (cats.find((c) => c.code === code) || {}).kind;
  if (kind === 'dokumen') {
    return <>Qty ditolak {qty} {unit} <strong>tidak masuk stok</strong> (catatan di GR saja; sisa PO tetap terbuka)</>;
  }
  return <>Qty ditolak {qty} {unit} akan masuk <strong>Karantina QC</strong></>;
}
const rejectOptLabel = (rc) => `${rc.label}${rc.kind === 'dokumen' ? ' · catatan saja' : ' · karantina'}`;
const priceOf = (it) => parseFloat(it?.unit_price) || parseFloat(it?.unit_cost) || 0;
// 2026-11-07 (Tahap 6 PG3): jenis sumber dalam bahasa staf (GR lama bersumber produksi/pindahan tetap terbaca)
const SOURCE_LABEL = { supplier: 'Pemasok', production: 'Produksi', transfer: 'Pindahan gudang' };
const sourceLabel = (t) => SOURCE_LABEL[t] || t || '';

export default function ReceivingModule({ token, deepLinkParams, onNavigate }) {
  const [receipts, setReceipts]   = useState([]);
  const [locations, setLocations] = useState([]);
  const [materials, setMaterials] = useState([]);
  // Sprint 2.1: PO integration
  const [purchaseOrders, setPurchaseOrders] = useState([]);
  const [suppliers, setSuppliers] = useState([]);
  const [loading, setLoading]     = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [showDetail, setShowDetail] = useState(null);
  const [search, setSearch] = useState('');
  // FASE 6: kategori alasan reject (dipakai saat qty rejected > 0 → masuk Karantina QC)
  const [rejectCats, setRejectCats] = useState([]);
  // FASE H-5: petunjuk nomor roll berikutnya (nomor TIDAK diketik) + salinan item
  // yang bisa disunting saat konfirmasi penerimaan (rincian gulungan sering baru
  // diketahui saat barang benar-benar ditimbang di gudang, bukan saat GR dibuat).
  const [rollPolicy, setRollPolicy] = useState(null);
  const [detailItems, setDetailItems] = useState([]);
  // Lokasi tujuan yang dipilih saat konfirmasi penerimaan (GR dari PO lahir
  // tanpa lokasi — kalau tidak ditanyakan di sini, stok mendarat di lokasi kosong).
  const [detailLocationId, setDetailLocationId] = useState('');
  const [receiveResult, setReceiveResult] = useState(null);
  const [missingRolls, setMissingRolls] = useState([]);
  // Jumlah SEMUA baris kain tanpa gulungan (field `total` server) — daftar hanya memuat 50 contoh.
  const [missingRollsTotal, setMissingRollsTotal] = useState(0);
  // 2026-11-06 (audit layar scan Gudang): scan SKU per baris → bunyi + ScanResult singkat di bawah barisnya.
  const [skuScanIdx, setSkuScanIdx] = useState(null);   // baris yang sedang di-scan (kamera terbuka)
  const [skuScan, setSkuScan] = useState(null);         // { idx, tone, title, detail }
  useEffect(() => {
    if (!skuScan) return undefined;
    const t = setTimeout(() => setSkuScan(null), 6000);
    return () => clearTimeout(t);
  }, [skuScan]);
  // Penjaga klik ganda: tombol simpan/konfirmasi terkunci selama permintaan berjalan
  // (dulu dua klik = dua kali konfirmasi = stok masuk dua kali).
  const [posting, setPosting] = useState(false);
  const postingRef = useRef(false);
  const runOnce = async (fn) => {
    if (postingRef.current) return;
    postingRef.current = true; setPosting(true);
    try { await fn(); } finally { postingRef.current = false; setPosting(false); }
  };

  // M12: memoized headers
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);
  // 2026-11-06 (Tahap 2): harga baris ber-PO = harga PO (tidak bisa diubah di sini); penerimaan tanpa PO
  // hanya Keuangan yang memberi harga. Satuan = salah satu satuan barang itu (server mengonversi ke dasar).
  const finance = isCurrentUserFinance();
  const [uomMap, setUomMap] = useState({});   // material_id → {base_unit, units[]} dari server
  const ensureUom = useCallback(async (ids) => {
    const need = [...new Set((ids || []).filter((id) => id && !uomMap[id]))];
    if (!need.length) return;
    try {
      const r = await fetch(`/api/rahaza/materials/uom-options?material_ids=${need.join(',')}`,
        { headers: { Authorization: `Bearer ${token}` } });
      if (r.ok) {
        const d = await r.json();
        setUomMap((prev) => ({ ...prev, ...(d?.options || {}) }));
      }
    } catch { /* daftar satuan gagal dimuat — pilihan tetap satuan dasar */ }
  }, [token, uomMap]);
  const unitOptions = (item) => {
    const o = uomMap[item.material_id];
    if (!o) return [{ unit: item.unit || 'pcs', label: item.unit || 'pcs' }];
    return o.units || [{ unit: o.base_unit, label: o.base_unit }];
  };
  const baseUnitOf = (item) => uomMap[item.material_id]?.base_unit || item.unit;
  const factorOf = (item) => {
    const o = uomMap[item.material_id];
    if (!o || !item.unit || item.unit === o.base_unit) return 1;
    return Number((o.units || []).find((u) => u.unit === item.unit)?.factor_to_base || 1);
  };

  const [form, setForm] = useState({
    source_type: 'supplier', source_ref: '', supplier_name: '',
    location_id: '', location_name: '', notes: '',
    // Sprint 2.1: PO fields
    po_id: '', po_number: '',
    items: [EMPTY_ITEM()]
  });

  const fetchData = useCallback(async () => {
    try {
      const [rRes, lRes, mRes, poRes, poPartRes, supRes] = await Promise.all([
        fetch('/api/wms/legacy/receiving',    { headers: { Authorization: `Bearer ${token}` } }),
        // FASE F+ (2026-07-25): dropdown lokasi tujuan pakai SSOT storage-locations
        // (wh_zones + rahaza storage), bukan lagi legacy warehouse_locations.
        fetch('/api/rahaza/storage-locations', { headers: { Authorization: `Bearer ${token}` } }),
        // 2026-11-07 (Tahap 6 PG1): barang jadi tidak dibeli → tidak dimuat ke pilihan barang penerimaan
        fetch('/api/rahaza/materials?exclude_type=fg', { headers: { Authorization: `Bearer ${token}` } }),
        // Sprint 2.1: PO yang bisa diterima. 2026-11-07 (Tahap 5): + PO "Diterima Sebagian" — dulu hanya
        // `approved`, sehingga SISA PO yang baru datang sebagian tidak bisa dipilih di form ini.
        fetch('/api/rahaza/purchase-orders?status=approved', { headers: { Authorization: `Bearer ${token}` } }),
        fetch('/api/rahaza/purchase-orders?status=partially_received', { headers: { Authorization: `Bearer ${token}` } }),
        // Master Supplier — penerimaan tanpa PO dari pemasok memilih nama dari master (dulu teks bebas)
        fetch('/api/procurement/suppliers/options', { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      if (rRes.ok) setReceipts(await rRes.json());
      if (lRes.ok) setLocations(await lRes.json());
      if (mRes.ok) {
        const data = await mRes.json();
        setMaterials(Array.isArray(data) ? data : (data.items || []));
      }
      const poA = poRes.ok ? await poRes.json() : [];
      const poP = poPartRes.ok ? await poPartRes.json() : [];
      setPurchaseOrders([...(Array.isArray(poA) ? poA : []), ...(Array.isArray(poP) ? poP : [])]);
      if (supRes.ok) setSuppliers((await supRes.json())?.items || []);
      // FASE H-5: baris kain yang sudah masuk stok tetapi belum punya gulungan.
      // Ditarik bersama daftar penerimaan supaya lubangnya terlihat di layar yang
      // sama tempat lubang itu tercipta.
      try {
        const mr = await fetch('/api/wms/fabric-rolls/missing-from-receipts?limit=50',
          { headers: { Authorization: `Bearer ${token}` } });
        if (mr.ok) {
          const d = await mr.json();
          setMissingRolls(d.items || []);
          setMissingRollsTotal(Number(d.total ?? (d.items || []).length) || 0);
        }
      } catch { /* noop */ }
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [token]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // FASE 6: ambil daftar kategori alasan reject sekali
  useEffect(() => {
    (async () => {
      try {
        const r = await fetch('/api/wms/quarantine/reject-categories', { headers: { Authorization: `Bearer ${token}` } });
        if (r.ok) setRejectCats(await r.json());
      } catch { /* noop */ }
    })();
  }, [token]);

  // FASE H-5: kebijakan nomor roll (mode otomatis + nomor berikutnya) untuk ditampilkan
  // sebagai petunjuk. Kalau gagal diambil, layar tetap jalan — hanya petunjuknya hilang.
  useEffect(() => {
    (async () => {
      try {
        const r = await fetch('/api/wms/fabric-rolls/number-policy', { headers: { Authorization: `Bearer ${token}` } });
        if (r.ok) setRollPolicy(await r.json());
      } catch { /* noop */ }
    })();
  }, [token]);

  // Buka detail → siapkan salinan item yang bisa disunting (rincian gulungan).
  const openDetail = (receipt) => {
    setShowDetail(receipt);
    setDetailItems((receipt.items || []).map(it => ({ ...it, rolls: (it.rolls || []).map(l => ({ ...l })) })));
    setDetailLocationId(receipt.location_id || '');
  };
  const updateDetailItem = (idx, patch) => setDetailItems(items =>
    items.map((it, i) => (i === idx ? { ...it, ...patch } : it)));

  // Total qty pada layar detail — dihitung SEKALI supaya ringkasan, peringatan
  // "masih 0", dan tombol Confirm memakai angka yang sama benda-nya.
  const detailTotals = useMemo(() => {
    const items = detailItems.length ? detailItems : (showDetail?.items || []);
    const sum = (f) => items.reduce((s, it) => s + (parseFloat(it?.[f]) || 0), 0);
    const received = sum('received_qty');
    const rejected = sum('rejected_qty');
    return { received, rejected, expected: sum('expected_qty'), touched: received + rejected };
  }, [detailItems, showDetail]);

  // P1.C: Open the just-created GR from PO (deep-link from PurchaseOrderModule)
  useEffect(() => {
    if (deepLinkParams?.receipt_id && receipts.length > 0) {
      const gr = receipts.find(r => r.id === deepLinkParams.receipt_id);
      if (gr) {
        openDetail(gr);
      }
    }
  }, [deepLinkParams, receipts]);

  // Sprint 1.1: When user picks a material from dropdown, auto-fill name + unit
  const handleMaterialPick = (idx, materialId) => {
    const mat = materials.find(m => m.id === materialId);
    if (materialId) ensureUom([materialId]);
    setForm(f => ({
      ...f,
      items: f.items.map((it, i) => i === idx ? {
        ...it,
        material_id:   mat?.id   || '',
        material_name: mat?.name || '',
        product_name:  mat?.name || it.product_name,
        sku:           mat?.code || it.sku,
        unit:          mat?.unit || it.unit,
        // FASE H-5: rincian gulungan hanya berlaku untuk satuan kain/benang.
        // Ganti material ke satuan pcs ⇒ rincian lama dibuang, bukan dibiarkan
        // menempel diam-diam dan ditolak server saat konfirmasi.
        rolls: isRollUnit(mat?.unit) ? (it.rolls || []) : [],
      } : it)
    }));
  };

  // Sprint 2.1: When user picks a PO, auto-fill vendor and items
  const handlePOPick = (poId) => {
    const po = purchaseOrders.find(p => p.id === poId);
    if (!po) {
      setForm(f => ({ ...f, po_id: '', po_number: '' }));
      return;
    }
    
    // Pre-fill items from PO
    // 2026-11-07 (Tahap 5): baris yang sudah diterima penuh tidak ikut; qty = SISA (satuan dasar). Dulu qty
    // pesanan penuh walau PO sudah diterima sebagian → GR kedua tercatat lebih (selisih stok & tagihan).
    const remainingOf = (item) => (item.qty_remaining != null
      ? Number(item.qty_remaining) : Math.max(0, Number(item.qty_ordered || 0) - Number(item.qty_received || 0)));
    const poItems = (po.items || []).filter(item => remainingOf(item) > 0).map(item => ({
      product_name:  item.material_name || '',
      sku:           item.material_code || '',
      material_id:   item.material_id,
      material_name: item.material_name || '',
      expected_qty:  remainingOf(item),
      received_qty:  remainingOf(item),
      rejected_qty:  0,
      unit:          item.unit || 'pcs',
      // 2026-11-02 (K11): harga baris PO (satuan dasar) ikut — dulu GR dari pilih-PO tanpa harga
      po_item_id:    item.id,
      unit_price:    item.unit_cost || 0,
    }));

    ensureUom(poItems.map(it => it.material_id));
    setForm(f => ({
      ...f,
      po_id: po.id,
      po_number: po.po_number,
      source_type: 'supplier',
      supplier_name: po.supplier_name || po.vendor_name,
      items: poItems.length > 0 ? poItems : [EMPTY_ITEM()],
    }));
  };

  const handleCreate = async () => {
    try {
      const loc = locations.find(l => l.id === form.location_id);
      // FASE H-5: cegah rincian gulungan yang tidak menjelaskan qty diterima SEBELUM
      // dikirim — biar penolakannya bukan kejutan setelah tombol simpan ditekan.
      const badRoll = (form.items || []).find(it => {
        if (!isRollUnit(it.unit) || !(it.rolls || []).length) return false;
        return rollLinesState(it.rolls, acceptedOf(it)).state !== 'match';
      });
      if (badRoll) {
        const st = rollLinesState(badRoll.rolls, acceptedOf(badRoll));
        toast.error(`Rincian gulungan ${badRoll.sku || badRoll.product_name} belum cocok: `
          + `${st.count} gulungan = ${fmtQty(st.total)} ${badRoll.unit}, qty diterima ${fmtQty(acceptedOf(badRoll))} ${badRoll.unit}`
          + `${st.diff ? ` (selisih ${st.diff > 0 ? '+' : ''}${fmtQty(st.diff, 3)})` : ''}. `
          + 'Perbaiki angkanya — stok dan gulungan harus menjelaskan penerimaan yang sama.', { duration: 10000 });
        return;
      }
      // 2026-11-02 (K11): penerimaan TANPA PO boleh, tetapi harga satuan WAJIB.
      // 2026-11-06 (Tahap 2): harganya diisi Keuangan — gudang menyimpan dulu, GR "menunggu harga dari Keuangan".
      if (!form.po_id && finance) {
        const noPrice = (form.items || []).find(it => it.material_id
          && (parseFloat(it.received_qty) || 0) > 0 && !(priceOf(it) > 0));
        if (noPrice) {
          toast.error(`Harga satuan wajib diisi untuk penerimaan tanpa PO (${noPrice.sku || noPrice.product_name || 'baris'}). `
            + 'Harga ini menjadi nilai persediaan, HPP rata-rata, dan dasar tagihan pemasok.', { duration: 10000 });
          return;
        }
      }
      // FASE 6: ubah `reject_reason` (UI) → `reject_reasons[]` (kontrak backend/karantina)
      const items = (form.items || []).map(it => {
        const rej = parseFloat(it.rejected_qty) || 0;
        const out = { ...it };
        delete out.reject_reason;
        out.reject_reasons = rej > 0
          ? [{ code: it.reject_reason || 'OTHER', qty: rej, notes: '' }]
          : [];
        // gulungan selalu dalam satuan dasar — baris bersatuan lain mengisinya sesudah disimpan (detail)
        out.rolls = isRollUnit(it.unit) && factorOf(it) === 1
          ? (it.rolls || []).filter(l => parseFloat(l.qty) > 0)
            .map(l => ({ qty: parseFloat(l.qty), color_lot: l.color_lot || '', notes: l.notes || '' }))
          : [];
        return out;
      });
      const payload = { ...form, items, location_name: loc?.name || form.location_name };
      const res = await fetch('/api/wms/legacy/receiving', { method: 'POST', headers, body: JSON.stringify(payload) });
      if (res.ok) {
        const saved = await res.json().catch(() => ({}));
        if (saved?.awaiting_finance_price) {
          toast.info(`Penerimaan ${saved.receipt_number || ''} tersimpan — menunggu harga dari Keuangan sebelum bisa dikonfirmasi.`);
        }
        setShowCreate(false); resetForm(); fetchData();
      }
      else {
        const err = await res.json().catch(() => ({}));
        toast.error('Error: ' + (err.detail || res.status));
      }
    } catch (e) { toast.error('Error: ' + e.message); }
  };

  const handleStatusChange = async (receipt, newStatus) => {
    try {
      // FASE H-5: item yang dikirim adalah SALINAN YANG DISUNTING di layar detail
      // (rincian gulungan biasanya baru terisi di sini, saat kain ditimbang).
      //
      // 2026-08-19 — DUA cacat diperbaiki pada jalur ini:
      //  (1) `reject_reason` (bentuk UI) TIDAK pernah dipetakan ke
      //      `reject_reasons[]` (kontrak backend/karantina) — `handleCreate`
      //      melakukannya, jalur konfirmasi detail TIDAK. Akibatnya alasan reject
      //      yang dipilih di modal detail hilang dalam perjalanan.
      //  (2) tidak ada penjaga qty 0: menekan Confirm pada GR dari PO (yang selalu
      //      lahir `received_qty=0`) mencatat penerimaan TANPA menambah stok
      //      sedikit pun — pembelian tampak selesai tetapi gudang tetap kosong.
      const items = (detailItems.length ? detailItems : receipt.items || []).map(it => {
        const rej = parseFloat(it.rejected_qty) || 0;
        const out = {
          ...it,
          received_qty: parseFloat(it.received_qty) || 0,
          rejected_qty: rej,
          rolls: isRollUnit(it.unit)
            ? (it.rolls || []).filter(l => parseFloat(l.qty) > 0)
              .map(l => ({ qty: parseFloat(l.qty), color_lot: l.color_lot || '', notes: l.notes || '' }))
            : [],
        };
        delete out.reject_reason;
        out.reject_reasons = rej > 0
          ? [{ code: it.reject_reason || 'OTHER', qty: rej, notes: '' }]
          : [];
        return out;
      });
      if (newStatus === 'received') {
        const touched = items.reduce(
          (s, it) => s + (parseFloat(it.received_qty) || 0) + (parseFloat(it.rejected_qty) || 0), 0);
        if (touched <= 0) {
          toast.error('Qty diterima masih 0.\n\nIsi dulu jumlah yang benar-benar datang pada '
            + 'setiap baris (atau tekan "Terima semua sesuai PO").\n\n'
            + 'Kalau dikonfirmasi sekarang, penerimaan tercatat tetapi stok TIDAK '
            + 'bertambah sama sekali — inilah sebabnya pembelian terlihat selesai '
            + 'padahal gudang tetap kosong.');
          return;
        }
        if (!(detailLocationId || receipt.location_id)) {
          toast.error('Lokasi tujuan belum dipilih.\n\nStok yang masuk harus mendarat di rak '
            + 'yang jelas — tanpa lokasi, barangnya ada di sistem tetapi tidak ada di '
            + 'rak mana pun, dan Put-Away tidak bisa menemukannya.');
          return;
        }
        // 2026-11-02 (K11): GR tanpa PO wajib berharga (backend menolak bila kosong).
        // 2026-11-06 (Tahap 2): harga diisi Keuangan; baris ber-PO memakai harga PO.
        const noPrice = items.find(it => it.material_id && (parseFloat(it.received_qty) || 0) > 0 && !(priceOf(it) > 0));
        if (noPrice) {
          toast.error(`Penerimaan ini menunggu harga dari Keuangan (${noPrice.sku || noPrice.product_name || 'baris'}).\n\n`
            + (receipt.po_id ? 'Harga baris PO masih 0 — Keuangan mengubah harga baris PO lebih dulu.'
              : 'Penerimaan tanpa PO diberi harga oleh Keuangan sebelum bisa dikonfirmasi.'));
          return;
        }
      }
      const locPick = locations.find(l => l.id === (detailLocationId || receipt.location_id));
      const badRoll = items.find(it => (it.rolls || []).length
        && rollLinesState(it.rolls, acceptedOf(it)).state !== 'match');
      if (badRoll) {
        const st = rollLinesState(badRoll.rolls, acceptedOf(badRoll));
        toast.error(`Rincian gulungan ${badRoll.sku || badRoll.product_name} belum cocok:\n\n`
          + `${st.count} gulungan = ${fmtQty(st.total)} ${badRoll.unit}, qty diterima ${fmtQty(acceptedOf(badRoll))} ${badRoll.unit}.\n\n`
          + 'Perbaiki angkanya dulu — kalau tidak, stok dan gulungan akan bercerita beda.');
        return;
      }
      const res = await fetch(`/api/wms/legacy/receiving/${receipt.id}`, {
        method: 'PUT',
        headers,
        body: JSON.stringify({
          status: newStatus,
          items,
          location_id: detailLocationId || receipt.location_id || '',
          location_name: locPick ? `${locPick.code} - ${locPick.name}` : (receipt.location_name || ''),
        }),
      });
      if (res.ok) {
        // FASE 6: beri tahu bila ada qty reject yang masuk Karantina QC
        const updated = await res.json().catch(() => ({}));
        const qs = updated?.quarantine_summary;
        const ds = updated?.reject_doc_summary;
        if (qs?.total_qty > 0 || ds?.total_qty > 0) {
          toast.success('Barang diterima.\n\n'
            + (qs?.total_qty > 0 ? `${qs.total_qty} unit REJECT fisik dipindahkan ke ${qs.location?.name || 'Karantina QC'} `
              + '(stok diblokir).\nTindak lanjuti di menu Gudang → "Karantina QC": lepas ke stok, Buat Retur Pembelian, atau scrap.\n\n' : '')
            + (ds?.total_qty > 0 ? `${ds.total_qty} unit ditolak karena alasan dokumen/kuantitas — TIDAK masuk stok, `
              + 'hanya dicatat di GR; sisa PO tetap terbuka.' : ''));
        }
        // FASE H-5: umpan balik gulungan — nomor yang terbit & baris kain yang
        // masih menunggu gulungan (supaya Cutting tidak mandek tanpa peringatan).
        const created = updated?.rolls_created || [];
        const pending = updated?.rolls_pending || [];
        if (created.length || pending.length) {
          setReceiveResult({ receipt_number: updated?.receipt_number || receipt.receipt_number, created, pending });
        }
        setShowDetail(null); setDetailItems([]); fetchData();
      }
      else {
        const err = await res.json().catch(() => ({}));
        toast.error('Error: ' + (err.detail || res.status));
      }
    } catch (e) { toast.error('Error: ' + e.message); }
  };

  // 2026-11-06 (Tahap 2): Keuangan memberi harga penerimaan tanpa PO TANPA harus mengonfirmasinya —
  // gudang yang menghitung barang tetap bisa mengonfirmasi sesudahnya.
  const saveDetailPrices = async (receipt) => {
    try {
      const items = (detailItems.length ? detailItems : receipt.items || []).map(it => {
        const rej = parseFloat(it.rejected_qty) || 0;
        const out = { ...it, unit_price: parseFloat(it.unit_price) || 0 };
        if ('reject_reason' in out) {
          out.reject_reasons = rej > 0 ? [{ code: it.reject_reason || 'OTHER', qty: rej, notes: '' }] : [];
          delete out.reject_reason;
        }
        return out;
      });
      const res = await fetch(`/api/wms/legacy/receiving/${receipt.id}`, {
        method: 'PUT', headers, body: JSON.stringify({ items }),
      });
      const out = await res.json().catch(() => ({}));
      if (!res.ok) { toast.error(out.detail || `Gagal menyimpan harga (HTTP ${res.status})`); return; }
      toast.success(out.awaiting_finance_price
        ? `Harga tersimpan, tetapi masih ada baris tanpa harga: ${(out.price_pending_lines || []).join(', ')}`
        : `Harga ${receipt.receipt_number} tersimpan — penerimaan siap dikonfirmasi.`);
      openDetail(out);
      fetchData();
    } catch (e) { toast.error(e.message); }
  };

  const handleDelete = async (id) => {
    try {
      const r = await fetch(`/api/wms/legacy/receiving/${id}`, { method: 'DELETE', headers });
      // 2026-11-06 (pola P6): dulu penolakan server (bukan peran gudang, sudah diproses) diam saja
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(typeof d.detail === 'string' ? d.detail : 'Gagal menghapus penerimaan');
      }
      toast.success('Penerimaan draf dihapus.');
      fetchData();
    } catch (e) { toast.error('Error: ' + e.message); }
  };

  const resetForm = () => setForm({
    source_type: 'supplier', source_ref: '', supplier_name: '',
    location_id: '', location_name: '', notes: '',
    items: [EMPTY_ITEM()]
  });

  const addItem    = () => setForm(f => ({ ...f, items: [...f.items, EMPTY_ITEM()] }));
  const removeItem = (idx) => setForm(f => ({ ...f, items: f.items.filter((_, i) => i !== idx) }));
  const updateItem = (idx, field, val) => setForm(f => ({
    ...f, items: f.items.map((it, i) => i === idx ? { ...it, [field]: val } : it)
  }));

  // Scan SKU satu baris: isinya tetap seperti dulu (kode → kolom SKU); yang baru hanya umpan baliknya.
  // Master material di layar ini dimuat maks. 500 — kode yang tidak ketemu diberi tanda kuning, bukan ditolak.
  const handleSkuScan = (idx, code) => {
    if (!code) {
      scanFeedback('error');
      setSkuScan({ idx, tone: 'error', title: 'Kode kosong — scan ulang' });
      return;
    }
    updateItem(idx, 'sku', code);
    const mat = materials.find(m => sameScanCode(m.code, code));
    if (mat) {
      scanFeedback('ok');
      setSkuScan({ idx, tone: 'ok', title: `SKU terisi: ${code}`, detail: `${mat.code} · ${mat.name}` });
    } else {
      scanFeedback('dup');
      setSkuScan({ idx, tone: 'dup', title: `SKU terisi: ${code}`,
        detail: 'Tidak ditemukan di master material — periksa kodenya, atau pilih material di kolom atas.' });
    }
  };

  const filtered = search ? receipts.filter(r =>
    r.receipt_number?.toLowerCase().includes(search.toLowerCase()) ||
    r.supplier_name?.toLowerCase().includes(search.toLowerCase())
  ) : receipts;

  // ── F13-B (sesi #12) — PENERIMAAN BARANG HARUS BISA DIBAWA ────────────────
  // Ini pintu masuk SELURUH stok: setiap angka di gudang berawal di sini.
  // Sebelum ini layarnya hanya kartu — tidak ada kolom qty diterima/ditolak,
  // tidak ada urutan, tidak ada unduhan. Akibatnya dua pertanyaan yang paling
  // sering ditanya tidak terjawab tanpa membuka satu per satu:
  //   · "minggu ini kita menerima apa saja, dari supplier mana, berapa?"
  //   · "berapa yang DITOLAK, dan dari penerimaan yang mana?"  ← qty ditolak
  //     adalah dasar klaim ke supplier; kalau harus dihitung dengan mata,
  //     klaimnya tidak pernah diajukan.
  const [sort, setSort] = useState({ key: 'created_at', dir: 'desc' });

  // Ringkasan per penerimaan dihitung SEKALI di sini supaya tabel, kartu, dan
  // CSV memakai angka yang sama benda-nya (bukan tiga perhitungan berbeda).
  const enriched = useMemo(() => filtered.map((r) => {
    const items = r.items || [];
    const sum = (f) => items.reduce((s, it) => s + Number(it?.[f] || 0), 0);
    return {
      ...r,
      item_count: items.length,
      expected_total: sum('expected_qty'),
      received_total: sum('received_qty'),
      rejected_total: sum('rejected_qty'),
      source_label: r.supplier_name || sourceLabel(r.source_type) || '—',
    };
  }), [filtered]);

  const rows = useMemo(() => {
    const list = [...enriched];
    const { key, dir } = sort;
    list.sort((a, b) => {
      const av = a?.[key], bv = b?.[key];
      const num = typeof av === 'number' || typeof bv === 'number';
      const cmp = num ? (Number(av || 0) - Number(bv || 0))
        : String(av ?? '').localeCompare(String(bv ?? ''), 'id');
      return dir === 'asc' ? cmp : -cmp;
    });
    return list;
  }, [enriched, sort]);
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(rows, 25);


  if (loading) return <div className="flex items-center justify-center h-64"><div className="animate-spin rounded-full h-10 w-10 border-b-2 border-primary" /></div>;

  const detailList = showDetail ? (detailItems.length ? detailItems : (showDetail.items || [])) : [];
  const isDraft = showDetail?.status === 'draft';

  const kolom = [
    { kunci: 'no', label: 'No. penerimaan', hp: 'judul', isi: (r) => (
      <span className="font-medium tabular-nums" data-testid={`receipt-row-${r.receipt_number}`}>{r.receipt_number}</span>) },
    { kunci: 'sumber', label: 'Supplier / sumber', hp: 'keterangan', isi: (r) => r.source_label },
    { kunci: 'po', label: 'No. PO', hp: false, isi: (r) => <span className="tabular-nums">{r.po_number || '—'}</span> },
    { kunci: 'status', label: 'Status', isi: (r) => (
      <span className="inline-flex flex-wrap gap-1">
        <StatusGR status={r.status} />
        {r.awaiting_finance_price && r.status !== 'received' && (
          <span data-testid={`receipt-price-pending-${r.receipt_number}`}>
            <StatusBadge tone="warning" label="Menunggu harga dari Keuangan" />
          </span>
        )}
      </span>) },
    { kunci: 'item', label: 'Item', hp: false, rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.item_count}</span> },
    { kunci: 'diharap', label: 'Qty diharap', hp: false, rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.expected_total.toLocaleString('id-ID')}</span> },
    { kunci: 'diterima', label: 'Qty diterima', rata: 'kanan', isi: (r) => <span className="font-medium tabular-nums">{r.received_total.toLocaleString('id-ID')}</span> },
    // Qty ditolak diberi warna hanya kalau memang > 0 — angka nol yang diwarnai merah membuat orang berhenti memperhatikan.
    { kunci: 'ditolak', label: 'Qty ditolak', rata: 'kanan', isi: (r) => (
      <span className={`tabular-nums ${r.rejected_total > 0 ? 'font-medium text-[hsl(var(--danger-text))]' : 'text-muted-foreground'}`}>
        {r.rejected_total.toLocaleString('id-ID')}
      </span>) },
    { kunci: 'tanggal', label: 'Tanggal', hp: false, isi: (r) => <span className="whitespace-nowrap">{fmtDate(r.created_at)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: false, isi: (r) => (
      <Button size="sm" variant="outline" onClick={() => openDetail(r)} data-testid={`receipt-detail-btn-${r.receipt_number}`}>
        <Eye />Detail
      </Button>) },
  ];

  const hapusDraf = async (receipt) => {
    const ok = await confirmDialog({
      title: 'Hapus penerimaan?', body: `GR draf ${receipt.receipt_number} akan dihapus permanen.`,
      confirmLabel: 'Hapus', danger: true,
    });
    if (!ok) return;
    setShowDetail(null);
    handleDelete(receipt.id);
  };

  return (
    <PageLayout
      testId="wh-receiving-module"
      title="Penerimaan Barang"
      subtitle="Terima barang dari pemasok, dengan atau tanpa PO. Stok bertambah saat penerimaan dikonfirmasi."
      actions={(
        <Button onClick={() => setShowCreate(true)} data-testid="create-receipt-btn">
          <Plus />Penerimaan baru
        </Button>
      )}
      filters={<>
        {(
        <>
          <div className="relative w-full sm:w-64">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input placeholder="Cari no. penerimaan / supplier" value={search}
              onChange={e => setSearch(e.target.value)} className="pl-8"
              data-testid="receiving-search" />
          </div>
          <SmartNativeSelect value={`${sort.key}:${sort.dir}`} aria-label="Urutkan"
            onChange={(e) => { const [key, dir] = e.target.value.split(':'); setSort({ key, dir }); }}
            className="w-full sm:w-52" wrapperClassName="w-full sm:w-52" data-testid="receiving-sort">
            {URUTAN.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </SmartNativeSelect>
        </>
      )}
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {(
        <>
          <TombolUnduh namaBerkas="penerimaan-barang" namaLembar="Penerimaan" baris={rows} testId="receiving-unduh"
            kolom={[
              { label: 'No. penerimaan', nilai: (r) => r.receipt_number },
              { label: 'Supplier / sumber', nilai: (r) => r.source_label },
              { label: 'Jenis', nilai: (r) => sourceLabel(r.source_type) },
              { label: 'No. PO', nilai: (r) => r.po_number || '' },
              { label: 'Status', nilai: (r) => statusGRLabel(r.status) },
              { label: 'Jumlah item', nilai: (r) => r.item_count },
              { label: 'Qty diharap', nilai: (r) => r.expected_total },
              { label: 'Qty diterima', nilai: (r) => r.received_total },
              { label: 'Qty ditolak', nilai: (r) => r.rejected_total },
              { label: 'Lokasi', nilai: (r) => r.location_name || r.location_code || '' },
              { label: 'Tanggal', nilai: (r) => fmtDate(r.created_at) },
              { label: 'Diterima oleh', nilai: (r) => r.received_by_name || r.created_by || '' },
            ]} />
          <Button variant="outline" size="icon" onClick={fetchData} title="Muat ulang penerimaan" aria-label="Muat ulang penerimaan"
            data-testid="receiving-refresh">
            <RefreshCw />
          </Button>
        </>
      )}
        </div>
      </>}
      summary={missingRollsTotal > 0 ? (
        // FASE H-5: kain yang masuk stok tanpa gulungan — Cutting menolak memotongnya.
        <Notice tone="warning" icon={AlertCircle} testId="gr-missing-rolls-banner"
          title={`${missingRollsTotal} baris penerimaan kain belum punya gulungan`}
          action={onNavigate && (
            <Button size="sm" variant="outline" onClick={() => onNavigate('wms-fabric-rolls')} data-testid="gr-banner-goto-rolls">
              Terbitkan roll
            </Button>
          )}>
          Kain ini ada di stok tetapi tidak bisa dipotong di Cutting sampai gulungannya diterbitkan
          ({missingRolls.slice(0, 3).map(m => m.material_code).join(', ')}
          {missingRollsTotal > 3 ? `, +${missingRollsTotal - 3} lagi` : ''}).
        </Notice>
      ) : null}
      footer={(
        <>
          {total > 0 && (
            <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />
          )}
          {/* RC-FLOW-UX Alur 1/2 — GRN → Put-Away → Stok (dulu di atas daftar, mendorong tabel ke bawah) */}
          {/* Dulu OnwardCTA bersama (judul HURUF BESAR "LANGKAH BERIKUTNYA"); tujuan & tombolnya sama. */}
          {onNavigate && (
            <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground" data-testid="onward-cta">
              <span>Langkah berikutnya:</span>
              <Button size="sm" variant="outline" onClick={() => onNavigate('wh-putaway')} title="Alokasikan barang yang sudah diterima ke lokasi/bin"
                data-testid="onward-cta-wh-putaway"><MapPin />Simpan ke rak sekarang</Button>
              <Button size="sm" variant="outline" onClick={() => onNavigate('wms-stock-hub')} title="Cek stok terkini setelah penerimaan"
                data-testid="onward-cta-wms-stock-hub"><Warehouse />Lihat stok</Button>
            </div>
          )}
        </>
      )}
    >
      <TabelData kolom={kolom} baris={paged} onKlikBaris={openDetail} testId="receiving-table"
        kosong={<EmptyState icon={ArrowDownToLine}
          title={search ? 'Tidak ada penerimaan yang cocok' : 'Belum ada penerimaan barang'}
          description={search ? 'Ubah kata pencarian.' : 'Penerimaan dari PO muncul di sini; penerimaan tanpa PO dibuat dengan tombol "Penerimaan baru".'}
          action={!search && <Button onClick={() => setShowCreate(true)}><Plus />Penerimaan baru</Button>} />} />

      {/* ── Form penerimaan baru (popup panjang) ───────────────────────────────── */}
      <FormPopup open={showCreate} onClose={() => setShowCreate(false)} ukuran="panjang" testId="gr-create-form"
        judul="Penerimaan barang baru"
        keterangan="Setiap baris wajib tertaut ke master item — stok tercatat saat penerimaan dikonfirmasi. Harga mengikuti PO; penerimaan tanpa PO diberi harga oleh Keuangan."
        onSimpan={() => runOnce(handleCreate)} menyimpan={posting} labelSimpan="Simpan penerimaan">
        <Isian label="Tautkan ke purchase order (opsional)"
          petunjuk={form.po_number ? `Barang diisi otomatis dari sisa PO ${form.po_number}.` : 'Pilih PO agar barang, qty sisa, dan harga terisi otomatis.'}>
          <Combobox
            value={form.po_id}
            onChange={(v) => handlePOPick(v)}
            options={[
              { value: '', label: 'Manual (tanpa PO)' },
              ...purchaseOrders.map(po => ({
                value: po.id,
                label: `${po.po_number} - ${po.supplier_name || po.vendor_name}`,
                description: po.status === 'partially_received' ? `sisa · ${po.item_count} item` : `${po.item_count} item`,
              }))
            ]}
            placeholder="Manual (tanpa PO)"
            searchPlaceholder="Cari PO atau vendor..."
            emptyMessage="PO tidak ditemukan"
            data-testid="gr-po-select"
          />
        </Isian>

        {/* 2026-11-07 (Tahap 6 PG3, keputusan owner): Penerimaan Barang manual hanya dari PEMASOK. Pilihan
            sumber "Produksi" / "Pindahan gudang" dengan asal barang yang diketik dihapus — memindahkan stok lewat
            menu Transfer (server juga menolak GR manual baru bersumber itu). */}
        <p className="text-sm text-muted-foreground" data-testid="gr-transfer-hint">
          Penerimaan Barang hanya untuk barang dari pemasok. Barang hasil produksi atau pindahan antar gudang
          dipindahkan lewat menu <strong className="text-foreground">Transfer</strong> (Stok &amp; Akurasi › Stok &amp; Pergerakan › Transfer A↔B).
          {onNavigate && (
            <Button type="button" variant="link" size="sm" className="h-auto px-1 py-0" data-testid="gr-transfer-link"
              onClick={() => { setShowCreate(false); onNavigate('wh-stock'); }}>
              Buka Transfer
            </Button>
          )}
        </p>

        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="No. referensi (surat jalan / dokumen)" htmlFor="gr-ref">
            <Input id="gr-ref" value={form.source_ref} onChange={e => setForm(f => ({ ...f, source_ref: e.target.value }))} placeholder="SJ-001" />
          </Isian>
          <Isian label="Supplier" htmlFor="gr-supplier" petunjuk={form.po_id ? 'Mengikuti PO.' : undefined}>
            {/* 2026-11-07 (Tahap 5): sumber pemasok dipilih dari Master Supplier (dulu teks bebas → nama beda
                ejaan tidak tertaut saat faktur/penilaian supplier). Ber-PO: supplier dari PO (terkunci). */}
            <SmartNativeSelect id="gr-supplier" value={form.supplier_name}
              onChange={e => setForm(f => ({ ...f, supplier_name: e.target.value }))}
              disabled={!!form.po_id}
              data-testid="gr-supplier-select">
              <option value="">— pilih supplier —</option>
              {form.supplier_name && !suppliers.some(s => s.name === form.supplier_name) && (
                <option value={form.supplier_name}>{form.supplier_name}</option>
              )}
              {suppliers.map(s => <option key={s.id} value={s.name}>{`${s.code} — ${s.name}`}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Lokasi tujuan">
            <Combobox
              value={form.location_id}
              onChange={(v) => setForm(f => ({ ...f, location_id: v }))}
              options={locations.map(l => ({
                value: l.id,
                label: `${l.code} - ${l.name}`,
                testId: `gr-location-option-${l.code}`,
              }))}
              placeholder="Pilih lokasi..."
              searchPlaceholder="Cari lokasi..."
              emptyMessage="Lokasi tidak ditemukan"
              data-testid="gr-location-select"
            />
          </Isian>
        </div>

        {/* Baris barang — Enter di isian baris tidak menyimpan seluruh penerimaan */}
        <div className="space-y-3" onKeyDown={(e) => { if (e.key === 'Enter' && e.target.tagName === 'INPUT') e.preventDefault(); }}>
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-foreground">Barang</p>
            <Button type="button" variant="link" size="sm" onClick={addItem} data-testid="gr-add-item"><Plus />Tambah barang</Button>
          </div>
          {form.items.map((item, idx) => (
            <div key={idx} className="space-y-3 rounded-lg border border-[var(--glass-border)] p-3" data-testid={`gr-item-${idx}`}>
              <div className="grid gap-3 sm:grid-cols-2">
                {/* 2026-11-06 (Tahap 2): tautan Master Item WAJIB — konfirmasi menolak baris tanpa tautan */}
                <Isian label="Master item" wajib
                  petunjuk={!item.material_id ? 'Pilih barangnya. Baris tanpa master item tidak bisa masuk stok dan ditolak saat penerimaan dikonfirmasi.' : undefined}>
                  <Combobox
                    value={item.material_id || ''}
                    onChange={(v) => handleMaterialPick(idx, v)}
                    options={[
                      { value: '', label: '— pilih barang —' },
                      ...materials.map(m => ({
                        value: m.id,
                        label: `${m.code} — ${m.name}`,
                        description: m.unit,
                        testId: `item-material-option-${m.code}`,
                      }))
                    ]}
                    placeholder="— pilih barang —"
                    searchPlaceholder="Cari material..."
                    emptyMessage="Material tidak ditemukan"
                    data-testid={`item-material-select-${idx}`}
                  />
                  {!item.material_id && <span className="sr-only" data-testid={`item-material-hint-${idx}`}>Master item belum dipilih</span>}
                </Isian>
                <Isian label="Nama produk" htmlFor={`gr-nama-${idx}`}>
                  <Input id={`gr-nama-${idx}`} value={item.product_name} onChange={e => updateItem(idx, 'product_name', e.target.value)}
                    placeholder="Nama produk" />
                </Isian>
              </div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <Isian label="SKU" htmlFor={`sku-input-${idx}`}>
                  <div className="flex gap-1">
                    <Input id={`sku-input-${idx}`} value={item.sku} onChange={e => updateItem(idx, 'sku', e.target.value)} placeholder="SKU"
                      className="min-w-0 flex-1" data-testid={`sku-input-${idx}`} />
                    {/* Satu kamera untuk semua baris; hasilnya diumumkan di bawah baris. */}
                    <Button type="button" variant="outline" size="icon" className="shrink-0"
                      onClick={() => setSkuScanIdx(idx)} title="Scan SKU" aria-label="Scan SKU"
                      data-testid={`scan-sku-${idx}`}>
                      <ScanLine />
                    </Button>
                  </div>
                </Isian>
                <Isian label="Satuan" htmlFor={`item-unit-${idx}`}
                  petunjuk={factorOf(item) !== 1
                    ? <span data-testid={`item-unit-convert-${idx}`}>= {fmtQty((parseFloat(item.received_qty) || 0) * factorOf(item))} {baseUnitOf(item)}</span>
                    : undefined}>
                  {/* 2026-11-06 (Tahap 2): hanya satuan barang ini (kemasan + satuan sedimensi, sumber
                      server yang sama dengan PO); server mengonversi qty & harga ke satuan dasar. */}
                  <SmartNativeSelect id={`item-unit-${idx}`} value={item.unit} onChange={e => updateItem(idx, 'unit', e.target.value)}
                    data-testid={`item-unit-${idx}`}>
                    {unitOptions(item).map(u => <option key={u.unit} value={u.unit}>{u.label}</option>)}
                  </SmartNativeSelect>
                </Isian>
                {/* 2026-11-02 (K11): harga satuan — WAJIB bila tanpa PO (nilai persediaan & HPP).
                    2026-11-06 (Tahap 2): ber-PO = harga PO (terkunci); tanpa PO = hanya Keuangan. */}
                <Isian label={form.po_id ? 'Harga dari PO' : finance ? `Harga per ${item.unit || 'satuan'} (Rp)` : 'Harga — diisi Keuangan'}
                  wajib={!form.po_id && finance} htmlFor={`item-price-${idx}`}>
                  <Input id={`item-price-${idx}`} type="number" min="0" step="any" value={form.po_id || finance ? (item.unit_price ?? '') : ''}
                    onChange={e => updateItem(idx, 'unit_price', e.target.value)}
                    disabled={!!form.po_id || !finance}
                    placeholder={form.po_id ? 'dari PO' : finance ? 'wajib' : 'menunggu Keuangan'}
                    data-testid={`item-price-${idx}`} />
                </Isian>
                <Isian label="Diharap" htmlFor={`item-expected-${idx}`}>
                  <Input id={`item-expected-${idx}`} type="number" value={item.expected_qty} onChange={e => updateItem(idx, 'expected_qty', parseFloat(e.target.value) || 0)}
                    data-testid={`item-expected-${idx}`} />
                </Isian>
                <Isian label="Diterima" htmlFor={`item-received-${idx}`}>
                  <Input id={`item-received-${idx}`} type="number" value={item.received_qty} onChange={e => updateItem(idx, 'received_qty', parseFloat(e.target.value) || 0)}
                    data-testid={`item-received-${idx}`} />
                </Isian>
                <Isian label="Ditolak" htmlFor={`item-rejected-${idx}`}>
                  <Input id={`item-rejected-${idx}`} type="number" value={item.rejected_qty} onChange={e => updateItem(idx, 'rejected_qty', parseFloat(e.target.value) || 0)}
                    data-testid={`item-rejected-${idx}`} />
                </Isian>
                {/* FASE 6: alasan reject — qty reject otomatis masuk Karantina QC */}
                {(parseFloat(item.rejected_qty) || 0) > 0 && (
                  <Isian label="Alasan ditolak" className="col-span-2 sm:col-span-3" htmlFor={`item-reject-reason-${idx}`}
                    petunjuk={rejectHint(rejectCats, item.reject_reason, item.rejected_qty, item.unit)}>
                    <SmartNativeSelect id={`item-reject-reason-${idx}`} value={item.reject_reason || ''}
                      onChange={e => updateItem(idx, 'reject_reason', e.target.value)}
                      data-testid={`item-reject-reason-${idx}`}>
                      <option value="">— pilih alasan —</option>
                      {rejectCats.map(rc => <option key={rc.code} value={rc.code}>{rejectOptLabel(rc)}</option>)}
                    </SmartNativeSelect>
                  </Isian>
                )}
                {/* U7 — Lot & Expiry */}
                <Isian label="No. lot / batch" htmlFor={`receiving-lot-${idx}`}>
                  <Input id={`receiving-lot-${idx}`} value={item.lot_number} onChange={e => updateItem(idx, 'lot_number', e.target.value)}
                    placeholder="LOT-001" data-testid={`receiving-lot-${idx}`} />
                </Isian>
                <Isian label="Tanggal kedaluwarsa">
                  <DatePicker value={item.expiry_date || ''} onChange={(v) => updateItem(idx, 'expiry_date', v)}
                    placeholder="Tidak ada" testId={`receiving-expiry-${idx}`} />
                </Isian>
                {form.items.length > 1 && (
                  <div className="flex items-end justify-end">
                    <Button type="button" variant="outline" size="sm" onClick={() => removeItem(idx)}
                      title="Hapus baris ini" aria-label={`Hapus baris barang ${idx + 1}`} data-testid={`gr-remove-item-${idx}`}>
                      <Trash2 />Hapus baris
                    </Button>
                  </div>
                )}
              </div>
              {skuScan?.idx === idx && <ScanResult {...skuScan} testId={`scan-sku-result-${idx}`} />}
              {/* ── FASE H-5: rincian gulungan untuk baris kain/benang ───────── */}
              {/* 2026-11-06 (Tahap 2): gulungan selalu satuan dasar — baris bersatuan kemasan mengisinya di detail */}
              {isRollUnit(item.unit) && factorOf(item) === 1 && (
                <RollLinesEditor
                  lines={item.rolls || []}
                  accepted={acceptedOf(item)}
                  unit={item.unit}
                  onChange={(lines) => updateItem(idx, 'rolls', lines)}
                  testPrefix={`gr-roll-lines-${idx}`}
                  nextNumberHint={rollPolicy?.next_number || ''}
                  subtitle={`Kain/benang dilacak per gulungan. Isi berat/panjang tiap gulungan — nomornya diterbitkan otomatis saat penerimaan dikonfirmasi. Total harus ${fmtQty(acceptedOf(item))} ${item.unit}.`}
                />
              )}
            </div>
          ))}
        </div>

        <Isian label="Catatan" htmlFor="gr-catatan">
          <Textarea id="gr-catatan" rows={2} value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} placeholder="Opsional" />
        </Isian>
      </FormPopup>
      {/* Kamera scan SKU — di LUAR form popup: kirim form "ketik manual" kamera tidak boleh ikut menyimpan penerimaan. */}
      <UniversalScanner
        variant="modal"
        open={skuScanIdx !== null}
        onClose={() => setSkuScanIdx(null)}
        onScan={(code) => { const i = skuScanIdx; setSkuScanIdx(null); if (i !== null) handleSkuScan(i, code); }}
        title="Scan SKU"
      />

      {/* ── Detail penerimaan (popup) — konfirmasi qty, lokasi, harga, gulungan ───── */}
      {showDetail && (
        <DetailPopup open onClose={() => setShowDetail(null)} testId="gr-detail"
          judul={`Penerimaan ${showDetail.receipt_number}`}
          keterangan={[showDetail.supplier_name || sourceLabel(showDetail.source_type), showDetail.po_number ? `PO ${showDetail.po_number}` : null].filter(Boolean).join(' · ')}
          status={<StatusGR status={showDetail.status} />}
          aksi={isDraft ? (
            <>
              <Button size="sm" variant="destructive" onClick={() => hapusDraf(showDetail)} data-testid="gr-detail-delete">
                <Trash2 />Hapus
              </Button>
              {finance && !showDetail.po_id && (
                <Button size="sm" variant="outline" onClick={() => runOnce(() => saveDetailPrices(showDetail))}
                  disabled={posting} data-testid="gr-detail-save-price">
                  Simpan harga
                </Button>
              )}
              <Button size="sm" variant="success" onClick={() => runOnce(() => handleStatusChange(showDetail, 'received'))}
                disabled={detailTotals.touched <= 0 || posting} aria-busy={posting}
                data-testid="confirm-receive-btn">
                {posting ? <><Loader2 className="animate-spin" />Menyimpan…</> : <><CheckCircle />Konfirmasi diterima</>}
              </Button>
            </>
          ) : null}>
          <dl className="grid gap-x-6 sm:grid-cols-2">
            <BarisDetail label="Sumber">{showDetail.supplier_name || sourceLabel(showDetail.source_type) || '—'}</BarisDetail>
            <BarisDetail label="Referensi">{showDetail.source_ref || '—'}</BarisDetail>
            <BarisDetail label="Lokasi">{showDetail.location_name || '—'}</BarisDetail>
            <BarisDetail label="Tanggal">{fmtDate(showDetail.created_at)}</BarisDetail>
          </dl>

          {/* FASE 6: banner karantina bila ada qty reject yang ditahan */}
          {showDetail.quarantine_summary?.total_qty > 0 && (
            <Notice tone="warning" icon={AlertCircle} testId="gr-quarantine-banner"
              title={`${showDetail.quarantine_summary.total_qty} unit ditolak ditahan di ${showDetail.quarantine_summary.location?.name || 'Karantina QC'}`}
              action={onNavigate && (
                <Button size="sm" variant="outline" onClick={() => { setShowDetail(null); onNavigate('wh-quarantine'); }}
                  data-testid="gr-open-quarantine">
                  Buka Karantina QC
                </Button>
              )}>
              Stok diblokir sampai ada keputusan (lepas ke stok / retur pembelian / scrap).
            </Notice>
          )}

          {isDraft && (
            <div className="space-y-3 rounded-lg border border-[var(--glass-border)] p-3">
              {/* LOKASI TUJUAN — GR yang lahir dari PO dibuat tanpa lokasi (`location_id: ""`); tanpa pemilih di sini
                  stok mendarat di baris berlokasi KOSONG dan Put-Away tidak bisa menemukannya. */}
              <Isian label="Lokasi tujuan" wajib
                petunjuk={!(detailLocationId || showDetail.location_id) ? 'Wajib dipilih sebelum konfirmasi — stok harus mendarat di rak yang jelas.' : undefined}>
                <Combobox
                  value={detailLocationId || showDetail.location_id || ''}
                  onChange={setDetailLocationId}
                  options={locations.map(l => ({
                    value: l.id,
                    label: `${l.code} - ${l.name}`,
                    testId: `gr-detail-location-option-${l.code}`,
                  }))}
                  placeholder="Pilih lokasi penyimpanan..."
                  searchPlaceholder="Cari lokasi..."
                  emptyMessage="Lokasi tidak ditemukan"
                  data-testid="gr-detail-location-select"
                />
              </Isian>
              {/* Jalan cepat untuk kasus paling umum: barang datang lengkap sesuai PO. */}
              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" variant="outline"
                  onClick={() => setDetailItems(items => (items.length ? items : (showDetail.items || []))
                    .map(it => ({ ...it, received_qty: Number(it.expected_qty || 0), rejected_qty: 0 })))}
                  data-testid="gr-detail-receive-all">
                  Terima semua sesuai PO
                </Button>
                <span className="text-sm text-muted-foreground" data-testid="gr-detail-total">
                  Total diterima <strong className="text-foreground tabular-nums">{fmtQty(detailTotals.received)}</strong>
                  {detailTotals.rejected > 0 && (
                    <> · ditolak <strong className="tabular-nums text-[hsl(var(--danger-text))]">{fmtQty(detailTotals.rejected)}</strong></>
                  )}
                  {' '}dari {fmtQty(detailTotals.expected)} diharap
                </span>
              </div>
              {detailTotals.touched <= 0 && (
                <Notice tone="warning" testId="gr-detail-zero-warning" title="Qty diterima masih 0">
                  Isi dulu jumlah yang benar-benar datang — mengonfirmasi angka 0 berarti penerimaan tercatat tetapi
                  stok tidak bertambah sama sekali.
                </Notice>
              )}
            </div>
          )}

          <div className="space-y-2">
            <p className="text-sm font-medium text-foreground">Barang ({detailList.length})</p>
            {detailList.map((item, idx) => (
              <div key={idx} className="space-y-3 rounded-lg border border-[var(--glass-border)] p-3" data-testid={`gr-detail-item-${idx}`}>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-foreground">{item.product_name}</p>
                    <p className="text-xs tabular-nums text-muted-foreground">
                      {item.sku}{item.material_id ? ' · tertaut ke master item' : ' · belum tertaut ke master item'}
                    </p>
                  </div>
                  <div className="text-right text-sm">
                    <p>Diterima <strong className="tabular-nums">{fmtQty(item.received_qty)}</strong> / {fmtQty(item.expected_qty)} {item.unit}</p>
                    {item.rejected_qty > 0 && <p className="text-xs text-[hsl(var(--danger-text))]">Ditolak {fmtQty(item.rejected_qty)}</p>}
                    {item.quarantined_qty > 0 && (
                      <p className="text-xs text-[hsl(var(--warning-text))]">Ke Karantina QC {fmtQty(item.quarantined_qty)} {item.unit}</p>
                    )}
                    {item.material_id && showDetail.status === 'received' && (
                      <p className="inline-flex items-center gap-1 text-xs text-[hsl(var(--success-text))]">
                        <CheckCircle className="h-3 w-3" /> stok sudah masuk
                      </p>
                    )}
                  </div>
                </div>

                {/* ── QTY DITERIMA / DITOLAK — HARUS BISA DIISI DI SINI ──────────
                    GR yang lahir dari PO SELALU dibuat dengan `received_qty: 0.0`; satu-satunya layar untuk memprosesnya
                    adalah popup ini, jadi qty harus bisa diisi di sini (dulu hanya teks → konfirmasi angka NOL). */}
                {isDraft && (
                  <div className="space-y-2" data-testid={`gr-detail-qty-${idx}`}>
                    <div className="grid grid-cols-3 gap-3">
                      <Isian label="Diharap (PO)">
                        <p className="flex h-9 items-center text-sm font-medium tabular-nums">
                          {fmtQty(item.expected_qty)} <span className="ml-1 text-xs font-normal text-muted-foreground">{item.unit}</span>
                        </p>
                      </Isian>
                      <Isian label="Qty diterima" wajib htmlFor={`gr-detail-received-${idx}`}>
                        <Input id={`gr-detail-received-${idx}`} type="number" min="0" step="any"
                          value={item.received_qty ?? 0}
                          onChange={e => updateDetailItem(idx, { received_qty: parseFloat(e.target.value) || 0 })}
                          data-testid={`gr-detail-received-${idx}`} />
                      </Isian>
                      <Isian label="Qty ditolak" htmlFor={`gr-detail-rejected-${idx}`}>
                        <Input id={`gr-detail-rejected-${idx}`} type="number" min="0" step="any"
                          value={item.rejected_qty ?? 0}
                          onChange={e => updateDetailItem(idx, { rejected_qty: parseFloat(e.target.value) || 0 })}
                          data-testid={`gr-detail-rejected-${idx}`} />
                      </Isian>
                    </div>
                    {/* Anti over-receive: backend menolaknya (HTTP 400); dikatakan di sini supaya bukan kejutan. */}
                    {showDetail.enforce_po_qty
                      && acceptedOf(item) - Number(item.expected_qty || 0) > 0.0001 && (
                      <p className="text-xs text-[hsl(var(--danger-text))]" data-testid={`gr-detail-over-${idx}`}>
                        Netto diterima {fmtQty(acceptedOf(item))} {item.unit} melebihi sisa PO
                        {' '}{fmtQty(item.expected_qty)} {item.unit} — penerimaan akan ditolak.
                      </p>
                    )}
                    {(parseFloat(item.rejected_qty) || 0) > 0 && (
                      <Isian label="Alasan ditolak" htmlFor={`gr-detail-reject-reason-${idx}`}
                        petunjuk={rejectHint(rejectCats, item.reject_reason, item.rejected_qty, item.unit)}>
                        <SmartNativeSelect id={`gr-detail-reject-reason-${idx}`} value={item.reject_reason || ''}
                          onChange={e => updateDetailItem(idx, { reject_reason: e.target.value })}
                          data-testid={`gr-detail-reject-reason-${idx}`}>
                          <option value="">— pilih alasan —</option>
                          {rejectCats.map(rc => <option key={rc.code} value={rc.code}>{rejectOptLabel(rc)}</option>)}
                        </SmartNativeSelect>
                      </Isian>
                    )}
                    {/* 2026-11-02 (K11): GR tanpa PO — harga satuan wajib sebelum dikonfirmasi.
                        2026-11-06 (Tahap 2): hanya Keuangan yang mengisinya; ber-PO = harga PO (terkunci). */}
                    {!showDetail.po_id && item.material_id && finance && (
                      <Isian label={`Harga per ${item.unit} (Rp) — tanpa PO, diisi Keuangan`} wajib htmlFor={`gr-detail-price-${idx}`}>
                        <Input id={`gr-detail-price-${idx}`} type="number" min="0" step="any"
                          value={item.unit_price ?? item.unit_cost ?? ''}
                          onChange={e => updateDetailItem(idx, { unit_price: e.target.value })}
                          data-testid={`gr-detail-price-${idx}`} />
                      </Isian>
                    )}
                    {item.material_id && (showDetail.po_id || !finance) && (
                      <p className={`text-xs ${priceOf(item) > 0 ? 'text-muted-foreground' : 'font-medium text-[hsl(var(--warning-text))]'}`}
                        data-testid={`gr-detail-price-locked-${idx}`}>
                        {priceOf(item) > 0
                          ? `Harga ${showDetail.po_id ? 'dari PO' : 'dari Keuangan'}: Rp ${priceOf(item).toLocaleString('id-ID', { maximumFractionDigits: 2 })} / ${item.unit}`
                          : 'Menunggu harga dari Keuangan — penerimaan belum bisa dikonfirmasi.'}
                      </p>
                    )}
                  </div>
                )}
                {/* ── FASE H-5: gulungan kain per baris ────────────────────────── */}
                {isRollUnit(item.unit) && showDetail.status !== 'received' && (
                  <RollLinesEditor
                    lines={item.rolls || []}
                    accepted={acceptedOf(item)}
                    unit={item.unit}
                    onChange={(lines) => updateDetailItem(idx, { rolls: lines })}
                    testPrefix={`gr-detail-roll-lines-${idx}`}
                    nextNumberHint={rollPolicy?.next_number || ''}
                    title="Rincian gulungan (isi sebelum konfirmasi)"
                    subtitle={`Timbang/ukur tiap gulungan sekarang. Nomor roll otomatis. Total harus ${fmtQty(acceptedOf(item))} ${item.unit} — kalau dilewati, kain masuk daftar "Penerimaan tanpa roll" dan Cutting akan menolak memotongnya.`}
                  />
                )}
                {(item.roll_numbers || []).length > 0 && (
                  <div data-testid={`gr-item-rolls-${idx}`}>
                    <p className="text-xs font-medium text-muted-foreground">{item.roll_numbers.length} gulungan terbit dari baris ini</p>
                    <p className="mt-0.5 text-xs tabular-nums text-foreground">{item.roll_numbers.join(' · ')}</p>
                  </div>
                )}
                {showDetail.status === 'received' && isRollUnit(item.unit)
                  && !(item.roll_numbers || []).length && acceptedOf(item) > 0 && (
                  <Notice tone="warning" testId={`gr-item-rolls-missing-${idx}`}
                    title={`${fmtQty(acceptedOf(item))} ${item.unit} masuk stok tanpa gulungan`}
                    action={onNavigate && (
                      <Button size="sm" variant="outline" onClick={() => { setShowDetail(null); onNavigate('wms-fabric-rolls'); }}
                        data-testid={`gr-open-fabric-rolls-${idx}`}>
                        Terbitkan roll
                      </Button>
                    )}>
                    Cutting menolak memotong kain yang tidak punya gulungan — terbitkan gulungannya di Roll Kain.
                  </Notice>
                )}
              </div>
            ))}
          </div>
        </DetailPopup>
      )}

      {/* ── FASE H-5: hasil penerbitan gulungan setelah GR dikonfirmasi ────────── */}
      {receiveResult && (
        <DetailPopup open onClose={() => setReceiveResult(null)} testId="gr-roll-result"
          judul={`Gulungan — ${receiveResult.receipt_number}`}
          aksi={onNavigate && (receiveResult.pending.length > 0 || receiveResult.created.length > 0) ? (
            <Button size="sm" onClick={() => { setReceiveResult(null); onNavigate('wms-fabric-rolls'); }}
              data-testid={receiveResult.pending.length > 0 ? 'gr-result-goto-rolls' : 'gr-result-view-rolls'}>
              {receiveResult.pending.length > 0 ? 'Buka Roll Kain' : 'Lihat Roll Kain'}
            </Button>
          ) : null}>
          {receiveResult.created.length > 0 && (
            <Notice tone="success" icon={CheckCircle} title={`${receiveResult.created.length} gulungan diterbitkan otomatis`}>
              <span className="block tabular-nums">{receiveResult.created.join(' · ')}</span>
              <span className="mt-1 block">Gulungan ini sudah bisa ditunjuk di Portal Cutting — sisa tiap gulungan berkurang saat kainnya dipotong.</span>
            </Notice>
          )}
          {receiveResult.pending.length > 0 && (
            <Notice tone="warning" icon={AlertCircle} title={`${receiveResult.pending.length} baris kain masuk stok tanpa gulungan`}>
              <ul className="space-y-0.5 tabular-nums">
                {receiveResult.pending.map((p) => (
                  <li key={p.item_id}>{p.material_code} — {fmtQty(p.accepted_qty)} {p.unit}</li>
                ))}
              </ul>
              <span className="mt-1 block">
                Cutting akan menolak memotong kain tanpa gulungan. Terbitkan gulungannya di Gudang › Roll Kain › “Penerimaan tanpa roll”.
              </span>
            </Notice>
          )}
        </DetailPopup>
      )}
    </PageLayout>
  );
}

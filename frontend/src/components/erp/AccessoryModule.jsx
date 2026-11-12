/**
 * Aksesoris Management — Full Implementation (Blueprint §3.3)
 * Tabs:
 *   1. Master & Stok   — CRUD + stock levels + alerts
 *   2. Request Internal — divisi → Admin Aksesoris
 *   3. Stok Opname      — sesi count fisik + adjustment
 *   4. Peminjaman       — borrow & return tracking
 *   5. Purchase Request — PR ke Finance
 *   6. Valuasi HPP      — nilai persediaan, set HPP (rata-rata bergerak), scrap bernilai (FASE 8)
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout di setiap tab; tab memakai HubTabs (tombol tab
 * buatan sendiri dihapus) sehingga tombol tab pindah ke baris tab; 4 kartu angka (dulu 7 kartu warna-warni
 * + 4 kartu ganda di tab Master); daftar = TabelData; form = FormPopup; detail = DetailPopup;
 * hapus/tolak lewat confirmDialog (dulu modal buatan & window.prompt); tanggal lewat DatePicker;
 * semua tabel bisa diunduh Excel/CSV.
 */

import { useState, useEffect, useCallback } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import {
  Package, Plus, Pencil, Trash2, Search, X, FileText, RotateCcw, ShoppingCart, RefreshCw, Eye, Check,
  XCircle, ArrowDownCircle, AlertTriangle, PackageMinus, PackagePlus, MoreHorizontal,
} from 'lucide-react';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import UomEditor from './UomEditor';
// MATERIAL_UNITS = cermin persis daftar satuan backend (satu sumber, tanpa konversi diam-diam)
import { resolveUoms, sanitizeUoms, purchaseUomOf, issueUomOf, displayUomOf, MATERIAL_UNITS } from '@/lib/uom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import DatePicker from '@/components/ui/date-picker';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { hapusMaster } from '@/lib/hapusMaster';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import useUomOptions from '@/hooks/useUomOptions';
import { UomSelect, UomConversionHint, baseUnitOf, toBaseQty } from './uom/UomPicker';
// FASE 8: tab valuasi HPP aksesoris (nilai persediaan + set HPP + scrap bernilai)
import AccessoryValuationTab from './accessory/AccessoryValuationTab';
import { MoneyInput } from '@/components/ui/money-input';
import DocNumberField, { useDocNumberPolicy, docNumberPayload } from './docnum/DocNumberField';
// 2026-11-02 (K9): tab Stok Opname = layar Sesi Opname bersama (mesin tunggal), terfilter aksesoris
import WMSOpnameScanModule from './WMSOpnameScanModule';
// 2026-11-07 (Tahap 6 HR3): pemohon Request Internal = karyawan dari master (pemilih SDM bersama)
import { useActiveEmployees, EmployeeSelect } from './hr/hrPickers';
import PageLayout from './layout/PageLayout';
import HubTabs from './hubs/HubTabs';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';
import { denganAlasanMerchandiser } from '@/lib/alasanMerchandiser';   // 12 Nov 2026 (K-M2)

const API = process.env.REACT_APP_BACKEND_URL || '';

// 2026-11-06 (Tahap 1): pilihan satuan = MATERIAL_UNITS (sama dengan yang diterima backend).
// Dulu daftar sendiri: "lembar" tersimpan jadi "pcs", "roll" jadi "rol", pak/gross tidak ada.
// Satuan lama item yang tidak ada di daftar tetap ditampilkan supaya tidak berubah diam-diam.
const unitOptions = (current) => (current && !MATERIAL_UNITS.includes(current)
  ? [current, ...MATERIAL_UNITS] : MATERIAL_UNITS);

// Status (kode server) → label Indonesia + nada StatusBadge (dulu teks Inggris & warna mentah).
const STOCK_STATUS = {
  ok: { label: 'Aman', tone: 'success' },
  low: { label: 'Menipis', tone: 'warning' },
  out: { label: 'Habis', tone: 'danger' },
};
const REQ_STATUS = {
  Draft: { label: 'Draf', tone: 'muted' },
  Pending: { label: 'Menunggu', tone: 'warning' },
  Approved: { label: 'Disetujui', tone: 'info' },
  Issued: { label: 'Diserahkan', tone: 'success' },
  Rejected: { label: 'Ditolak', tone: 'danger' },
  Cancelled: { label: 'Dibatalkan', tone: 'muted' },
};
const PR_STATUS_TONE = {
  Draft: 'muted', Forwarded: 'primary', Submitted: 'warning', Approved: 'info', Rejected: 'danger',
  Ordered: 'info', Received: 'success', Cancelled: 'muted',
};
const PR_PRIORITY_TONE = { Urgent: 'danger', Normal: 'info', Low: 'muted' };

function Lencana({ peta, status, label }) {
  const m = peta[status] || { label: label || status || '-', tone: 'muted' };
  return <StatusBadge status={String(status || '')} label={label || m.label} tone={m.tone} />;
}

function fmtDate(iso) {
  if (!iso) return '-';
  try { return new Date(iso).toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' }); }
  catch { return iso?.slice(0, 10) || '-'; }
}

function fmtNum(n) { return Number(n || 0).toLocaleString('id-ID'); }
// FASE 8: format rupiah untuk nilai persediaan / HPP aksesoris
function fmtRp(n) { return `Rp ${Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 2 })}`; }

async function api(method, path, token, body) {
  const opts = { method, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(`${API}${path}`, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = data.detail;
    const e = new Error(typeof d === 'string' ? d : (d?.message || `Server menolak permintaan ini (kode ${r.status}).`));
    e.status = r.status; // 10 Nov 2026: 409 = data sudah dipakai (lib/hapusMaster menawarkan Nonaktifkan)
    throw e;
  }
  return data;
}

// 2026-11-06 (Tahap 2): SATU daftar divisi pemohon dari backend (GET /api/acc/divisions), lengkap
// dengan akun beban yang dipakai jurnal pengeluaran per divisi. Dulu daftar ini disalin di layar.
function useDivisions(token) {
  const [divs, setDivs] = useState([]);
  useEffect(() => {
    let alive = true;
    api('GET', '/api/acc/divisions', token)
      .then(d => { if (alive) setDivs(Array.isArray(d) ? d : []); })
      .catch(() => { /* daftar kosong → form menolak kirim tanpa divisi */ });
    return () => { alive = false; };
  }, [token]);
  return divs;
}

// 2026-11-07 (Tahap 5): supplier aksesoris & PR aksesoris dipilih dari Master Supplier (dulu teks bebas →
// ejaan berbeda tidak tertaut ke supplier/PO). Sejak Tahap 6 (PG5) yang disimpan `supplier_id` + nama (SupplierPick).
function useSupplierOptions(token) {
  const [rows, setRows] = useState([]);
  useEffect(() => {
    let alive = true;
    api('GET', '/api/procurement/suppliers/options', token)
      .then(d => { if (alive) setRows(d?.items || []); })
      .catch(() => { /* master kosong → hanya nilai lama yang tampil */ });
    return () => { alive = false; };
  }, [token]);
  return rows;
}

// 2026-11-07 (Tahap 6 PG5): supplier DISIMPAN sebagai id Master Supplier (`supplier_id`); nama ikut untuk
// tampilan (server mengambilnya dari master). Nama lama yang belum tertaut tetap tampil sebagai pilihan bertanda.
const LEGACY_SUPPLIER = '__nama_lama__';
function SupplierPick({ suppliers, form, setForm, className, 'data-testid': testId }) {
  const linkedMissing = form.supplier_id && !suppliers.some(s => s.id === form.supplier_id);
  return (
    <SmartNativeSelect value={form.supplier_id || (form.supplier ? LEGACY_SUPPLIER : '')}
      onChange={e => {
        const v = e.target.value;
        if (v === LEGACY_SUPPLIER) return;
        const s = suppliers.find(x => x.id === v);
        setForm(f => ({ ...f, supplier_id: v, supplier: v ? (s?.name || f.supplier) : '' }));
      }}
      className={className} data-testid={testId}>
      <option value="">— pilih supplier —</option>
      {!form.supplier_id && form.supplier && <option value={LEGACY_SUPPLIER}>{`${form.supplier} (belum di Master Supplier)`}</option>}
      {linkedMissing && <option value={form.supplier_id}>{`${form.supplier || 'Supplier'} (nonaktif)`}</option>}
      {suppliers.map(s => <option key={s.id} value={s.id}>{`${s.code} — ${s.name}`}</option>)}
    </SmartNativeSelect>
  );
}

// Prioritas PR: nilai server tetap (Urgent/Normal/Low), label berbahasa Indonesia
const PR_PRIORITY_LABEL = { Urgent: 'Mendesak', Normal: 'Normal', Low: 'Rendah' };

function divisionHint(divs, value) {
  const d = (divs || []).find(x => x.value === value);
  if (!d) return '';
  return `Dicatat sebagai: ${d.cost_label}${d.account_code ? ` · akun ${d.account_code}${d.account_name ? ` ${d.account_name}` : ''}` : ''}`;
}

/** Kotak cari standar toolbar (± 16 rem, tidak pernah selebar layar). */
function KotakCari({ value, onChange, placeholder, testId }) {
  return (
    <div className="relative w-full sm:w-64">
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
      <Input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder}
        className="pl-8 pr-8" data-testid={testId} />
      {value && (
        <Button type="button" variant="ghost" size="icon-sm" onClick={() => onChange('')}
          className="absolute right-0.5 top-1/2 -translate-y-1/2" title="Hapus pencarian" aria-label="Hapus pencarian">
          <X />
        </Button>
      )}
    </div>
  );
}

function TombolMuatUlang({ onClick, memuat, testId }) {
  return (
    <Button variant="outline" size="icon" onClick={onClick} disabled={memuat} title="Muat ulang" aria-label="Muat ulang"
      data-testid={testId}>
      <RefreshCw className={memuat ? 'animate-spin' : ''} />
    </Button>
  );
}

const Memuat = ({ teks }) => <p className="py-6 text-center text-sm text-muted-foreground">{teks}</p>;

// ─── TAB 1: MASTER & STOK ────────────────────────────────────────────────────
function MasterTab({ token, onRefreshDash, onOpenValuation, title, subtitle }) {
  const [items, setItems]       = useState([]);
  const [loading, setLoading]   = useState(true);
  const [search, setSearch]     = useState('');
  const [catFilter, setCat]     = useState('');
  const [statusF, setStatusF]   = useState('');
  const [showForm, setShowForm] = useState(false);
  const [editItem, setEditItem] = useState(null);
  const [form, setForm]         = useState({ code:'', name:'', category_id:'', sub_category:'', unit:'pcs', description:'', min_stock:0, unit_cost:0, supplier:'', supplier_id:'', notes:'', uoms:[], purchase_uom:'', issue_uom:'', display_uom:'', pack_unit:'pack', pack_size:1, display_in_packs:false });
  const [showMove, setShowMove] = useState(null); // {id, name, action:'in'|'out'}
  const [moveForm, setMoveForm] = useState({ qty:'', notes:'', input_unit:'base', unit_cost:'', divisi:'' });
  // 2026-11-06 (Tahap 2): divisi pemohon (Keluarkan Stok) + harga penerimaan (hanya Keuangan yang mengubah)
  const divisions = useDivisions(token);
  const suppliers = useSupplierOptions(token);
  const [recvPrice, setRecvPrice] = useState(null); // {can_set_price, unit_cost, source_label}
  // 2026-11-06 (Tahap 2): pilihan kategori dari master kategori material (dulu teks bebas → ID tampil)
  const [catMaster, setCatMaster] = useState([]);
  const [moveResult, setMoveResult] = useState('');
  const [saving, setSaving]     = useState(false);
  const [err, setErr]           = useState('');
  const [formErr, setFormErr]   = useState('');
  const [msg, setMsg]           = useState('');

  // ROADMAP P1 (2026-08-05) — pemilih satuan pada penerimaan & pengeluaran stok:
  // daftar satuan sah + faktornya untuk aksesoris yang sedang dibuka di modal.
  const { options: moveUomOpts } = useUomOptions(showMove?.id ? [showMove.id] : []);
  const moveUomOpt = showMove?.id ? moveUomOpts[showMove.id] : null;
  const moveBaseUnit = baseUnitOf(moveUomOpt, showMove?.unit || '');
  const moveUnit = (moveForm.input_unit && moveForm.input_unit !== 'base')
    ? moveForm.input_unit : moveBaseUnit;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (search) params.set('search', search);
      if (catFilter) params.set('category', catFilter);
      const data = await api('GET', `/api/acc/items?${params}`, token);
      setItems(Array.isArray(data) ? data : []);
    } catch(e) { setErr(e.message); }
    finally { setLoading(false); }
  }, [token, search, catFilter]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    api('GET', '/api/rahaza/material-categories', token)
      .then(d => setCatMaster(Array.isArray(d) ? d : []))
      .catch(() => { /* kategori opsional — form tetap bisa disimpan tanpa memilih */ });
  }, [token]);
  // Harga penerimaan: Keuangan boleh mengetik; selain itu harga PO terakhir / HPP master (Tahap 2)
  useEffect(() => {
    setRecvPrice(null);
    if (showMove?.action !== 'in' || !showMove?.id) return;
    api('GET', `/api/acc/stock/receive-price/${showMove.id}`, token)
      .then(setRecvPrice)
      .catch(() => setRecvPrice({ can_set_price: false, unit_cost: 0, source_label: 'HPP master aksesoris' }));
  }, [showMove, token]);

  // Pilihan filter kategori: nilai = id master (atau teks lama), label = NAMA kategori
  const cats = [...new Map(items.filter(i => i.category)
    .map(i => [i.category_id || i.category, i.category])).entries()];

  const openAdd = () => { setEditItem(null); setFormErr(''); setForm({ code:'', name:'', category_id:'', sub_category:'', unit:'pcs', description:'', min_stock:0, unit_cost:0, supplier:'', supplier_id:'', notes:'', uoms:[], purchase_uom:'', issue_uom:'', display_uom:'', pack_unit:'pack', pack_size:1, display_in_packs:false }); setShowForm(true); };
  const openEdit = it => { setEditItem(it); setFormErr(''); setForm({ code: it.code||'', name: it.name||'', category_id: it.category_id||'', sub_category: it.sub_category||'', unit: it.unit||'pcs', description: it.description||'', min_stock: it.min_stock||0, unit_cost: it.unit_cost||0, supplier: it.supplier||'', supplier_id: it.supplier_id||'', notes: it.notes||'', uoms: resolveUoms(it), purchase_uom: purchaseUomOf(it), issue_uom: issueUomOf(it), display_uom: displayUomOf(it), pack_unit: it.pack_unit||'pack', pack_size: it.pack_size||1, display_in_packs: it.display_in_packs||false }); setShowForm(true); };

  const save = async () => {
    if (!form.name.trim()) return;
    setSaving(true); setFormErr('');
    try {
      // Satuan dinormalkan dulu; backend (core/uom) memvalidasi ulang dan
      // menulis cermin pack_unit/pack_size sendiri (INV-UOM-4).
      const payload = { ...form, uoms: sanitizeUoms(form.uoms, form.unit) };
      // Kategori kosong (item lama berkategori teks) → tidak dikirim supaya tidak berubah
      if (!payload.category_id) delete payload.category_id;
      // HPP item lama tidak dikirim: perubahan HPP hanya lewat Set HPP (revaluasi berjurnal, K12)
      if (editItem) { delete payload.unit_cost; await api('PUT', `/api/acc/items/${editItem.id}`, token, payload); }
      else          await api('POST', '/api/acc/items', token, payload);
      setShowForm(false); load(); onRefreshDash();
    } catch(e) { setFormErr(e.message); }
    finally { setSaving(false); }
  };

  // 10 Nov 2026 (permintaan owner): "Hapus" kini hapus permanen sungguhan (dulu hanya menonaktifkan, padahal
  // kalimatnya menjanjikan penolakan bila berstok/di BOM — server tidak memeriksa apa pun). Server menolak (409)
  // bila aksesoris sudah dipakai stok, BOM, PR/PO/penerimaan, opname, dll. → dialog kedua menawarkan Nonaktifkan.
  const del = async it => {
    setErr(''); setMsg('');
    setSaving(true);
    try {
      const hasil = await hapusMaster({ jenis: 'aksesoris', nama: [it.code, it.name].filter(Boolean).join(' '),
        hapus: () => api('DELETE', `/api/acc/items/${it.id}?hard=true`, token),
        nonaktifkan: () => api('DELETE', `/api/acc/items/${it.id}`, token) });
      if (hasil) { load(); onRefreshDash(); }
    }
    finally { setSaving(false); }
  };

  const openMove = (it, action) => {
    const item = items.find(x => x.id === it.id);
    setShowMove({ id: it.id, name: it.name, action, unit: item?.unit, pack_unit: item?.pack_unit, pack_size: item?.pack_size, display_in_packs: item?.display_in_packs });
    setMoveForm({ qty:'', notes:'', input_unit:'base', unit_cost:'', divisi:'' }); setFormErr(''); setMoveResult('');
  };

  const doMove = async () => {
    const qty = parseFloat(moveForm.qty);
    if (!qty || qty <= 0) { setFormErr('Qty harus > 0'); return; }
    if (showMove.action === 'out' && !moveForm.divisi) { setFormErr('Pilih divisi pemakai — divisi menentukan akun bebannya.'); return; }
    setSaving(true); setFormErr(''); setMoveResult('');
    try {
      const isIn = showMove.action === 'in';
      const path = isIn ? '/api/acc/stock/receive' : '/api/acc/stock/issue';
      const unitCode = (moveUnit && moveUnit !== moveBaseUnit) ? moveUnit : 'base';
      const payload = { acc_id: showMove.id, qty, notes: moveForm.notes, input_unit: unitCode };
      if (!isIn) payload.divisi = moveForm.divisi;
      // FASE 8: harga satuan penerimaan (opsional) → memperbarui HPP master (rata-rata bergerak)
      // BUG-1: kirim `cost_unit` eksplisit supaya backend tahu harga yang diketik user
      // mengacu ke satuan kemasan atau satuan dasar. Backend selalu menyimpan per satuan dasar.
      // 2026-11-06 (Tahap 2): hanya Keuangan yang mengirim harga; lainnya memakai harga dari server.
      if (isIn && recvPrice?.can_set_price && moveForm.unit_cost !== '' && Number(moveForm.unit_cost) >= 0) {
        payload.unit_cost = Number(moveForm.unit_cost);
        payload.cost_unit = unitCode;
      }
      const res = await api('POST', path, token, payload);
      const je = res?.je || {};
      const parts = [];
      if (isIn) {
        parts.push(`Diterima ${fmtNum(res.qty_received ?? qty)} ${moveBaseUnit || showMove.unit || ''}`);
        if (unitCode !== 'base') parts.push(`input ${fmtNum(qty)} ${unitCode}`);
        if (res.cost_unit && res.cost_unit !== 'base' && res.unit_cost_input > 0) {
          parts.push(`harga ${fmtRp(res.unit_cost_input)}/${res.cost_unit === 'pack' ? res.pack_unit : res.cost_unit} = ${fmtRp(res.unit_cost_in)}/${moveBaseUnit || showMove.unit}`);
        }
        if (res.cost_changed) parts.push(`HPP ${fmtRp(res.old_unit_cost)} → ${fmtRp(res.unit_cost)} (rata-rata bergerak)`);
        else if (res.unit_cost > 0) parts.push(`HPP tetap ${fmtRp(res.unit_cost)}`);
      } else {
        parts.push(`Dikeluarkan ${fmtNum(res.qty_issued ?? qty)} ${moveBaseUnit || showMove.unit || ''}`);
        if (unitCode !== 'base') parts.push(`input ${fmtNum(qty)} ${unitCode}`);
        if (res.value > 0) parts.push(`nilai ${fmtRp(res.value)}`);
      }
      parts.push(je.posted ? `jurnal ${je.je_number} di-posting` : `tanpa jurnal (${je.error || 'HPP belum diisi'})`);
      setMoveResult(parts.join(' · '));
      setShowMove(null); setMoveForm({ qty:'', notes:'', input_unit:'base', unit_cost:'', divisi:'' }); load(); onRefreshDash();
    } catch(e) { setFormErr(e.message); }
    finally { setSaving(false); }
  };

  const hitung = (k) => items.filter(i => i.stock_status === k).length;
  const opsiStatus = [
    { key: '', label: 'Semua', count: items.length },
    { key: 'ok', label: 'Aman', count: hitung('ok') },
    { key: 'low', label: 'Menipis', count: hitung('low') },
    { key: 'out', label: 'Habis', count: hitung('out') },
  ];
  const tampil = statusF ? items.filter(i => i.stock_status === statusF) : items;

  // RC-UI-03: paginasi di sisi layar (25/halaman, PANDUAN G7)
  const itemsPg = useClientPagination(tampil, 25);

  const kolom = [
    { kunci: 'kode', label: 'Kode', hp: 'keterangan', isi: (it) => <span className="whitespace-nowrap tabular-nums">{it.code || '—'}</span> },
    { kunci: 'nama', label: 'Nama', hp: 'judul', isi: (it) => <span className="font-medium">{it.name}</span> },
    { kunci: 'kategori', label: 'Kategori', isi: (it) => (
      // 2026-11-06 (Tahap 2): nama kategori (dulu ID master mentah) + sub kategori
      <div className="text-sm">
        <div>{it.category || '—'}</div>
        {it.sub_category && <div className="text-xs text-muted-foreground">{it.sub_category}</div>}
      </div>) },
    { kunci: 'stok', label: 'Stok', rata: 'kanan', isi: (it) => (it.display_in_packs ? (
      <div className="tabular-nums">
        <div>{fmtNum(it.stock_qty_in_packs)} {it.pack_unit}</div>
        <div className="text-xs text-muted-foreground">({fmtNum(it.stock_qty)} {it.unit})</div>
      </div>
    ) : <span className="tabular-nums">{fmtNum(it.stock_qty)} <span className="text-xs text-muted-foreground">{it.unit}</span></span>) },
    { kunci: 'min', label: 'Minimum', rata: 'kanan', isi: (it) => (
      <span className="tabular-nums text-muted-foreground">
        {it.display_in_packs ? `${fmtNum(it.min_stock_in_packs)} ${it.pack_unit}` : fmtNum(it.min_stock)}
      </span>) },
    { kunci: 'hpp', label: 'Harga satuan', rata: 'kanan', isi: (it) => ((it.unit_cost || 0) > 0
      ? <span className="tabular-nums">{fmtRp(it.unit_cost)}</span>
      : <span className="text-[hsl(var(--warning-text))]" title="Belum ada harga satuan — selisih opname tidak akan masuk jurnal keuangan">belum diisi</span>) },
    { kunci: 'nilai', label: 'Nilai stok', rata: 'kanan', isi: (it) => (
      <span className="tabular-nums text-muted-foreground">{(it.stock_value || 0) > 0 ? fmtRp(it.stock_value) : '—'}</span>) },
    { kunci: 'status', label: 'Status', isi: (it) => <Lencana peta={STOCK_STATUS} status={it.stock_status} /> },
    { kunci: 'aksi', label: 'Aksi', rata: 'kanan', hp: 'aksi', isi: (it) => (
      <div className="flex items-center justify-end gap-1">
        <Button variant="outline" size="icon-sm" onClick={() => openMove(it, 'in')} title="Terima stok"
          aria-label={`Terima stok ${it.name}`} data-testid={`acc-in-${it.id}`}>
          <PackagePlus />
        </Button>
        <Button variant="outline" size="icon-sm" onClick={() => openMove(it, 'out')} title="Keluarkan stok"
          aria-label={`Keluarkan stok ${it.name}`} data-testid={`acc-out-${it.id}`}>
          <PackageMinus />
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" title="Lainnya" aria-label={`Aksi lain ${it.name}`}>
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => openEdit(it)} data-testid={`edit-acc-${it.id}`}>
              <Pencil className="mr-2 h-4 w-4" /> Ubah
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => del(it)} disabled={saving} data-testid={`del-acc-${it.id}`}
              className="text-[hsl(var(--danger-text))]">
              <Trash2 className="mr-2 h-4 w-4" /> Hapus
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>) },
  ];

  return (
    <PageLayout title={title} subtitle={subtitle} testId="acc-master-tab"
      actions={<Button onClick={openAdd} data-testid="add-acc-btn"><Plus /> Tambah aksesoris</Button>}
      filters={<>
        <KotakCari value={search} onChange={setSearch} placeholder="Cari kode atau nama" testId="acc-search" />
        <SmartNativeSelect value={catFilter} onChange={e=>setCat(e.target.value)} className="w-44" data-testid="acc-cat-filter">
          <option value="">Semua kategori</option>
          {cats.map(([v, label])=><option key={v} value={v}>{label}</option>)}
        </SmartNativeSelect>
        <FilterChips options={opsiStatus} value={statusF} onChange={setStatusF} testId="acc-status-filter" />
      </>}
      tools={<>
        <TombolUnduh namaBerkas="master-aksesoris" namaLembar="Aksesoris" baris={tampil} testId="acc-master-unduh"
          kolom={[
            { label: 'Kode', nilai: (it) => it.code },
            { label: 'Nama', nilai: (it) => it.name },
            { label: 'Kategori', nilai: (it) => it.category || '' },
            { label: 'Sub kategori', nilai: (it) => it.sub_category || '' },
            { label: 'Stok', nilai: (it) => Number(it.stock_qty || 0) },
            { label: 'Satuan', nilai: (it) => it.unit },
            { label: 'Stok minimum', nilai: (it) => Number(it.min_stock || 0) },
            { label: 'Harga satuan (Rp)', nilai: (it) => Number(it.unit_cost || 0) },
            { label: 'Nilai stok (Rp)', nilai: (it) => Number(it.stock_value || 0) },
            { label: 'Status', nilai: (it) => (STOCK_STATUS[it.stock_status] || {}).label || '' },
            { label: 'Supplier', nilai: (it) => it.supplier || '' },
          ]} />
        <TombolMuatUlang onClick={load} memuat={loading} />
      </>}
      footer={itemsPg.total > 0 && <PaginationLite page={itemsPg.page} totalPages={itemsPg.totalPages} total={itemsPg.total} pageSize={itemsPg.pageSize} onPageChange={itemsPg.setPage} />}>
      {err && <Notice tone="danger" testId="acc-master-error">{err}</Notice>}
      {msg && <Notice tone="success" testId="acc-master-msg">{msg}</Notice>}
      {moveResult && <Notice tone="success" testId="acc-move-result">{moveResult}</Notice>}

      {loading && items.length === 0 ? <Memuat teks="Memuat aksesoris…" /> : (
        <TabelData kolom={kolom} baris={itemsPg.paged} testId="acc-master-table"
          kosong={<EmptyState icon={Package}
            title={items.length ? 'Tidak ada aksesoris yang cocok' : 'Belum ada item aksesoris'}
            description={items.length ? 'Ubah saringan status.' : 'Tambah item pertama untuk mulai mengelola stok aksesoris.'} />} />
      )}

      {/* Form tambah / ubah (popup panjang) */}
      <FormPopup open={showForm} onClose={() => setShowForm(false)} ukuran="panjang" onSimpan={save}
        menyimpan={saving} bisaSimpan={!!form.name} galat={formErr} testId="acc-form"
        judul={editItem ? 'Ubah aksesoris' : 'Tambah aksesoris'} labelSimpan="Simpan">
        {/* 2026-11-06 (Tahap 2): kategori dipilih dari master kategori material; rincian bebas
            (mis. Trimming) di Sub kategori — dulu teks bebas yang tertimpa ID master. */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Isian label="Kategori">
            <SmartNativeSelect value={form.category_id} onChange={e=>setForm({...form,category_id:e.target.value})}
              className="w-full" data-testid="acc-category-select">
              <option value="">{!editItem ? 'Aksesoris (bawaan)'
                : (editItem.category && !editItem.category_id ? `${editItem.category} (lama)` : 'Tidak diubah')}</option>
              {catMaster.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Sub kategori" htmlFor="acc-subkat">
            <Input id="acc-subkat" value={form.sub_category||''} onChange={e=>setForm({...form,sub_category:e.target.value})}
              placeholder="Trimming" data-testid="acc-subcategory-input" />
          </Isian>
          <Isian label="Kode" htmlFor="acc-kode">
            <Input id="acc-kode" value={form.code||''} onChange={e=>setForm({...form,code:e.target.value})}
              placeholder="ACC-001" data-testid="acc-field-code" />
          </Isian>
          <Isian label="Nama" wajib htmlFor="acc-nama">
            <Input id="acc-nama" value={form.name||''} onChange={e=>setForm({...form,name:e.target.value})}
              placeholder="Kancing" data-testid="acc-field-name" />
          </Isian>
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Isian label="Supplier">
            <SupplierPick suppliers={suppliers} form={form} setForm={setForm}
              className="w-full" data-testid="acc-supplier-select" />
          </Isian>
          <Isian label="Satuan">
            <SmartNativeSelect value={form.unit} onChange={e=>setForm({...form,unit:e.target.value})} className="w-full" data-testid="acc-unit-select">
              {unitOptions(editItem?.unit).map(u=><option key={u} value={u}>{u}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Stok minimum" htmlFor="acc-min">
            <Input id="acc-min" type="number" min="0" value={form.min_stock} onChange={e=>setForm({...form,min_stock:e.target.value})} />
          </Isian>
        </div>
        {/* FASE G+: harga satuan — dasar nilai selisih opname & jurnal keuangan */}
        {editItem ? (
          // 2026-11-06 (Tahap 1, K12): HPP item yang sudah ada hanya diubah lewat Set HPP
          // (revaluasi berjurnal + alasan) — bukan ditimpa dari form ini.
          <Isian label="Harga satuan / HPP"
            petunjuk="HPP diubah lewat Set HPP di Valuasi HPP supaya perubahan nilai stok tercatat dengan jurnal dan alasannya.">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm tabular-nums" data-testid="acc-unit-cost-readonly">{fmtRp(editItem.unit_cost)}</span>
              {onOpenValuation && (
                <Button type="button" variant="link" size="sm" className="px-0"
                  onClick={() => { setShowForm(false); onOpenValuation(); }} data-testid="acc-open-set-hpp">
                  Buka Valuasi HPP
                </Button>
              )}
            </div>
          </Isian>
        ) : (
          <Isian label="Harga satuan / HPP (Rp)" htmlFor="acc-hpp"
            petunjuk="Harga awal. Dipakai untuk menilai stok & jurnal penyesuaian keuangan saat opname disetujui. Kosong/0 = selisih opname tidak masuk keuangan.">
            <MoneyInput id="acc-hpp" value={form.unit_cost}
              onChange={e=>setForm({...form,unit_cost:e.target.value})}
              placeholder="0" data-testid="acc-unit-cost-input" />
          </Isian>
        )}

        {/* Satuan & kemasan berjenjang (maks 3 tingkat) — SSOT lib/uom.js */}
        <UomEditor
          baseUnit={form.unit}
          uoms={form.uoms}
          purchaseUom={form.purchase_uom}
          issueUom={form.issue_uom}
          displayUom={form.display_uom}
          resetKey={editItem?.id || 'new'}
          onChange={patch => setForm(f => ({ ...f, ...patch }))}
        />

        <Isian label="Catatan" htmlFor="acc-catatan">
          <Textarea id="acc-catatan" value={form.notes} onChange={e=>setForm({...form,notes:e.target.value})} rows={2} />
        </Isian>
      </FormPopup>

      {/* Terima / keluarkan stok (popup pendek) */}
      {showMove && (
        <FormPopup open onClose={() => setShowMove(null)} ukuran="pendek" onSimpan={doMove} menyimpan={saving}
          galat={formErr} testId="acc-move-form"
          judul={showMove.action === 'in' ? 'Terima stok masuk' : 'Keluarkan stok'} keterangan={showMove.name}
          labelSimpan={showMove.action === 'in' ? 'Terima' : 'Keluarkan'}>
          <Isian label="Satuan input"
            petunjuk={showMove.display_in_packs && showMove.pack_unit
              ? `1 ${showMove.pack_unit} = ${fmtNum(showMove.pack_size)} ${showMove.unit}` : undefined}>
            <UomSelect opt={moveUomOpt} value={moveUnit} fallbackUnit={showMove.unit}
              onChange={e=>setMoveForm({...moveForm,input_unit:e.target.value})}
              testId="move-uom-select" className="w-full" />
          </Isian>
          <Isian label={`Jumlah (${moveUnit || showMove.unit})`} wajib htmlFor="move-qty">
            <Input id="move-qty" type="number" min="0.0001" step="0.0001" value={moveForm.qty} onChange={e=>setMoveForm({...moveForm,qty:e.target.value})}
              placeholder="0" data-testid="move-qty-input" />
            <UomConversionHint opt={moveUomOpt} qty={moveForm.qty} unit={moveUnit}
              fallbackUnit={showMove.unit} testId="move-uom-hint" className="mt-1" />
          </Isian>
          {showMove.action === 'out' && (
            // 2026-11-06 (Tahap 2): divisi pemakai menentukan akun beban jurnal pengeluaran
            <Isian label="Divisi pemakai" wajib
              petunjuk="Aksesoris untuk PO produksi dikeluarkan lewat Kirim Material CMT atau permintaan ber-PO, bukan dari sini.">
              <SmartNativeSelect value={moveForm.divisi} onChange={e=>setMoveForm({...moveForm,divisi:e.target.value})}
                className="w-full" data-testid="move-divisi-select">
                <option value="">Pilih divisi...</option>
                {divisions.map(d=><option key={d.value} value={d.value}>{d.label}</option>)}
              </SmartNativeSelect>
              {moveForm.divisi && (
                <p className="text-xs text-muted-foreground" data-testid="move-divisi-hint">
                  {divisionHint(divisions, moveForm.divisi)}
                </p>
              )}
            </Isian>
          )}
          {showMove.action === 'in' && recvPrice && !recvPrice.can_set_price && (
            <p className="text-sm text-muted-foreground" data-testid="move-price-locked">
              Harga penerimaan: <b className="text-foreground">{fmtRp(recvPrice.unit_cost)}</b> per {moveBaseUnit || showMove.unit}
              {' '}({recvPrice.source_label}). Hanya Keuangan yang boleh mengubah harga.
            </p>
          )}
          {showMove.action === 'in' && recvPrice?.can_set_price && (
            <Isian label={`Harga satuan beli per ${moveUnit || showMove.unit} (Rp), opsional`} htmlFor="move-cost"
              petunjuk="Bila diisi, HPP master diperbarui dengan metode rata-rata bergerak dan jurnal persediaan dibuat otomatis.">
              <MoneyInput id="move-cost" decimals={2} value={moveForm.unit_cost}
                onChange={e=>setMoveForm({...moveForm,unit_cost:e.target.value})}
                placeholder="kosongkan bila harga tidak berubah" data-testid="move-unit-cost-input" />
              <p className="text-xs text-muted-foreground">
                Acuan: {fmtRp(recvPrice.unit_cost)} per {moveBaseUnit || showMove.unit} ({recvPrice.source_label}).
              </p>
              {moveUnit && moveBaseUnit && moveUnit !== moveBaseUnit && moveForm.unit_cost && (
                <p className="text-xs text-muted-foreground" data-testid="move-cost-conversion-hint">
                  = {fmtRp(Number(moveForm.unit_cost) / (toBaseQty(moveUomOpt, 1, moveUnit) || 1))} per {moveBaseUnit}
                </p>
              )}
            </Isian>
          )}
          <Isian label="Catatan" htmlFor="move-notes">
            <Input id="move-notes" value={moveForm.notes} onChange={e=>setMoveForm({...moveForm,notes:e.target.value})}
              placeholder="Keterangan..." />
          </Isian>
        </FormPopup>
      )}
    </PageLayout>
  );
}

// ─── TAB 2: REQUEST INTERNAL ────────────────────────────────────────────────
// FASE 10 — DIPINDAH KE SSOT `dewi_accessory_requests` (request_type='internal_issuance').
// Sebelumnya tab ini memakai `/api/acc/internal-requests` yang menulis ke koleksi
// legacy `acc_internal_requests`. Akibat nyata: KPI "Request Pending" di dashboard
// (yang membaca SSOT) SELALU 0, inbox/approval SSOT tidak pernah melihat permintaan
// ini, dan koleksi legacy tidak bisa di-drop. Sekarang satu jalur saja:
//   buat → submitted · setujui → allocated · serahkan → delivered (POTONG STOK) ·
//   tolak → rejected.
// Kode status lama (Pending/Approved/Issued/Rejected) dipertahankan di dalam layar; label tampilnya
// berbahasa Indonesia (REQ_STATUS).
const REQ_STATUS_FROM_SSOT = {
  draft: 'Draft', submitted: 'Pending', allocated: 'Approved',
  delivered: 'Issued', rejected: 'Rejected', cancelled: 'Cancelled',
};
const REQ_STATUS_TO_SSOT = {
  Draft: 'draft', Pending: 'submitted', Approved: 'allocated',
  Issued: 'delivered', Rejected: 'rejected', Cancelled: 'cancelled',
};

function reqFromSSOT(d) {
  return {
    ...d,
    request_number: d.request_code || d.request_number || d.id,
    status: REQ_STATUS_FROM_SSOT[d.status] || d.status,
    needed_by: d.needed_by_date || d.needed_by || '',
    items: (d.items || []).map(it => ({
      acc_id: it.material_id || it.acc_id || '',
      acc_name: it.material_name || it.acc_name || it.material_code || '',
      acc_code: it.material_code || it.acc_code || '',
      qty_requested: it.qty ?? it.qty_requested ?? 0,
      unit: it.unit || 'pcs',
      notes: it.notes || '',
    })),
  };
}

function RequestInternalTab({ token, items, title, subtitle }) {
  const [requests, setReqs]   = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShow]   = useState(false);
  const [form, setForm]       = useState({ divisi:'', requester_employee_id:'', purpose:'', needed_by:'', items:[] });
  const [lines, setLines]     = useState([{ acc_id:'', qty_requested:1, unit:'pcs', notes:'' }]);
  const [detail, setDetail]   = useState(null);
  // 2026-11-07 (Tahap 6 HR3): "Nama Pemohon" = karyawan dari Data Karyawan (dulu teks bebas di catatan).
  // Bawaan = karyawan yang tertaut ke akun login (SSOT identitas karyawan di server); bisa diganti.
  const { employees } = useActiveEmployees(token, { enabled: showForm });
  useEffect(() => {
    if (!showForm) return undefined;
    let off = false;
    api('GET', '/api/portal-saya/me/employee', token)
      .then(e => { if (!off && e?.id) setForm(f => (f.requester_employee_id ? f : { ...f, requester_employee_id: e.id })); })
      .catch(() => { /* akun belum tertaut ke karyawan → pemohon dipilih manual */ });
    return () => { off = true; };
  }, [showForm, token]);
  const [saving, setSaving]   = useState(false);
  const [err, setErr]         = useState('');
  const [formErr, setFormErr] = useState('');
  const [msg, setMsg]         = useState('');
  const [statusFilter, setStatusF] = useState('');
  // SESI #27 — kebijakan penomoran Permintaan Aksesoris. TIPE=INT-REQ (pengeluaran internal).
  const numPolicy = useDocNumberPolicy('dewi_accessory_requests.request_code', token,
                                       { TIPE: 'INT-REQ' });
  const [reqCode, setReqCode] = useState('');
  const divisions = useDivisions(token);   // 2026-11-06 (Tahap 2): daftar divisi dari backend

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams({ request_type: 'internal_issuance', limit: '200' });
      if (statusFilter) qs.set('status', REQ_STATUS_TO_SSOT[statusFilter] || statusFilter);
      const data = await api('GET', `/api/dewi/accessory-requests?${qs}`, token);
      const rows = Array.isArray(data) ? data : (data.items || data.requests || []);
      setReqs(rows.map(reqFromSSOT));
    } catch(e) { setErr(e.message); }
    finally { setLoading(false); }
  }, [token, statusFilter]);

  useEffect(() => { load(); }, [load]);

  const addLine = () => setLines([...lines, { acc_id:'', qty_requested:1, unit:'pcs', notes:'' }]);
  const removeLine = idx => setLines(lines.filter((_,i)=>i!==idx));
  const updateLine = (idx, key, val) => setLines(lines.map((l,i)=>i===idx?{...l,[key]:val}:l));

  const lineChange = (idx, acc_id) => {
    const acc = items.find(a=>a.id===acc_id);
    updateLine(idx, 'acc_id', acc_id);
    if (acc) {
      setLines(prev => prev.map((l,i)=>i===idx ? {...l, acc_id, acc_name:acc.name, acc_code:acc.code, unit:acc.unit} : l));
    }
  };

  const submit = async () => {
    if (!form.divisi) { setFormErr('Divisi wajib dipilih'); return; }
    if (!form.requester_employee_id) { setFormErr('Pemohon wajib dipilih dari Data Karyawan'); return; }
    const validLines = lines.filter(l=>l.acc_id && l.qty_requested>0);
    if (validLines.length === 0) { setFormErr('Minimal 1 item'); return; }
    setSaving(true); setFormErr(''); setMsg('');
    try {
      const res = await api('POST', '/api/dewi/accessory-requests', token, {
        request_type: 'internal_issuance',
        status: 'submitted',
        ...docNumberPayload(numPolicy, 'request_code', reqCode),
        divisi: form.divisi,
        purpose: form.purpose,
        needed_by_date: form.needed_by,
        requester_employee_id: form.requester_employee_id,
        items: validLines.map(l => ({
          material_id: l.acc_id, material_code: l.acc_code || '', material_name: l.acc_name || '',
          qty: Number(l.qty_requested) || 0, unit: l.unit || 'pcs', notes: l.notes || '',
        })),
      });
      setShow(false); setLines([{ acc_id:'', qty_requested:1, unit:'pcs', notes:'' }]);
      setForm({ divisi:'', requester_employee_id:'', purpose:'', needed_by:'', items:[] });
      setMsg(`Permintaan ${res.request_code || ''} dibuat & menunggu persetujuan.`);
      load();
    } catch(e) { setFormErr(e.message); }
    finally { setSaving(false); }
  };

  // Approve → allocate · Reject → reject · Issue → deliver (SSOT memotong stok + jurnal)
  const updateStatus = async (id, status, notes='') => {
    setErr(''); setMsg('');
    try {
      if (status === 'Approved') {
        await api('POST', `/api/dewi/accessory-requests/${id}/allocate`, token, { notes });
        setMsg('Permintaan disetujui. Klik “Serahkan” untuk mengeluarkan barang & memotong stok.');
      } else if (status === 'Rejected') {
        await api('POST', `/api/dewi/accessory-requests/${id}/reject`, token, { reason: notes || 'Ditolak admin aksesoris' });
        setMsg('Permintaan ditolak. Stok tidak berubah.');
      } else if (status === 'Issued') {
        const res = await api('POST', `/api/dewi/accessory-requests/${id}/deliver`, token, { notes });
        const n = (res.issued_items || []).length;
        setMsg(n
          ? `Barang diserahkan · ${n} item keluar dari stok · nilai ${fmtRp(res.total_value)}.`
          : 'Barang diserahkan.');
      }
      load();
      if (detail?.id === id) setDetail(null);
    } catch(e) { setErr(e.message); }
  };

  // RC-UI-03: paginasi di sisi layar (25/halaman)
  const requestsPg = useClientPagination(requests, 25);

  const aksiStatus = (r) => (
    <>
      {r.status === 'Pending' && (
        <>
          <Button size="sm" variant="success" onClick={()=>updateStatus(r.id,'Approved')} data-testid={`approve-req-${r.id}`}>
            <Check /> Setujui
          </Button>
          <Button size="sm" variant="destructive" onClick={()=>updateStatus(r.id,'Rejected')} data-testid={`reject-req-${r.id}`}>
            <XCircle /> Tolak
          </Button>
        </>
      )}
      {r.status === 'Approved' && (
        <Button size="sm" onClick={()=>updateStatus(r.id,'Issued')} data-testid={`issue-req-${r.id}`}>
          <ArrowDownCircle /> Serahkan
        </Button>
      )}
    </>
  );

  const kolom = [
    { kunci: 'no', label: 'No. permintaan', hp: 'judul', isi: (r) => <span className="font-medium tabular-nums">{r.request_number}</span> },
    { kunci: 'divisi', label: 'Divisi', isi: (r) => r.divisi || '—' },
    { kunci: 'pemohon', label: 'Pemohon', isi: (r) => r.requester_name || '—' },
    { kunci: 'keperluan', label: 'Keperluan', hp: 'keterangan', isi: (r) => (
      <span className="block max-w-xs truncate text-muted-foreground" title={r.purpose || ''}>{r.purpose || '—'}</span>) },
    { kunci: 'butuh', label: 'Tanggal butuh', isi: (r) => <span className="whitespace-nowrap">{fmtDate(r.needed_by)}</span> },
    { kunci: 'status', label: 'Status', isi: (r) => <Lencana peta={REQ_STATUS} status={r.status} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <div className="flex items-center justify-end gap-1">
        {aksiStatus(r)}
        {r.status !== 'Pending' && (
          <Button variant="ghost" size="icon-sm" onClick={()=>setDetail(r)} title="Lihat rincian"
            aria-label={`Lihat rincian ${r.request_number}`} data-testid={`view-req-${r.id}`}>
            <Eye />
          </Button>
        )}
      </div>) },
  ];

  return (
    <PageLayout title={title} subtitle={subtitle} testId="acc-internal-tab"
      actions={<Button onClick={()=>{setShow(true);setFormErr('');}} data-testid="add-int-req-btn"><Plus /> Buat permintaan</Button>}
      filters={
        <FilterChips value={statusFilter} onChange={setStatusF} hideWhenEmpty={false} testId="acc-req-status"
          options={[{ key: '', label: 'Semua' }, ...['Pending','Approved','Rejected','Issued'].map(s => ({ key: s, label: REQ_STATUS[s].label }))]} />
      }
      tools={<>
        <TombolUnduh namaBerkas="permintaan-internal-aksesoris" namaLembar="Permintaan internal" baris={requests}
          testId="acc-req-unduh"
          kolom={[
            { label: 'No. permintaan', nilai: (r) => r.request_number },
            { label: 'Divisi', nilai: (r) => r.divisi || '' },
            { label: 'Pemohon', nilai: (r) => r.requester_name || '' },
            { label: 'Keperluan', nilai: (r) => r.purpose || '' },
            { label: 'Tanggal butuh', nilai: (r) => (r.needed_by ? fmtDate(r.needed_by) : '') },
            { label: 'Status', nilai: (r) => (REQ_STATUS[r.status] || {}).label || r.status },
            { label: 'Item', nilai: (r) => (r.items || []).map(it => `${it.acc_name || it.acc_code} ${it.qty_requested} ${it.unit}`).join('; ') },
          ]} />
        <TombolMuatUlang onClick={load} memuat={loading} />
      </>}
      footer={requestsPg.total > 0 && <PaginationLite page={requestsPg.page} totalPages={requestsPg.totalPages} total={requestsPg.total} pageSize={requestsPg.pageSize} onPageChange={requestsPg.setPage} />}>
      {err && <Notice tone="danger" testId="acc-req-error">{err}</Notice>}
      {msg && <Notice tone="success" testId="acc-req-msg">{msg}</Notice>}

      {loading && requests.length === 0 ? <Memuat teks="Memuat permintaan…" /> : (
        <TabelData kolom={kolom} baris={requestsPg.paged} onKlikBaris={setDetail} testId="acc-req-table"
          kosong={<EmptyState icon={FileText} title="Belum ada permintaan internal" description="Permintaan dari divisi akan muncul di sini." />} />
      )}

      {/* Rincian permintaan (popup) */}
      {detail && (
        <DetailPopup open onClose={()=>setDetail(null)} judul={detail.request_number} testId="acc-req-detail"
          status={<Lencana peta={REQ_STATUS} status={detail.status} />}
          aksi={aksiStatus(detail)}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Divisi">{detail.divisi || '—'}</BarisDetail>
            <BarisDetail label="Pemohon">{detail.requester_name || '—'}</BarisDetail>
            <BarisDetail label="Keperluan">{detail.purpose || '—'}</BarisDetail>
            <BarisDetail label="Tanggal butuh">{fmtDate(detail.needed_by)}</BarisDetail>
            {detail.admin_notes && <BarisDetail label="Catatan admin">{detail.admin_notes}</BarisDetail>}
          </dl>
          <div>
            <p className="mb-2 text-sm font-medium">Item yang diminta</p>
            <dl className="divide-y divide-[var(--glass-border)]">
              {(detail.items||[]).map((it,i)=>(
                <BarisDetail key={i} label={it.acc_name || it.acc_code || (items.find(a => a.id === it.acc_id) || {}).name || 'Aksesoris tanpa nama'}>
                  <span className="tabular-nums">{it.qty_requested} {it.unit}</span>
                </BarisDetail>
              ))}
            </dl>
          </div>
        </DetailPopup>
      )}

      {/* Form permintaan internal (popup panjang) */}
      <FormPopup open={showForm} onClose={()=>setShow(false)} ukuran="panjang" onSimpan={submit} menyimpan={saving}
        galat={formErr} judul="Buat permintaan internal" labelSimpan="Kirim permintaan" testId="acc-req-form">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Isian label="Divisi" wajib>
            <SmartNativeSelect value={form.divisi} onChange={e=>setForm({...form,divisi:e.target.value})} className="w-full" data-testid="req-divisi">
              <option value="">Pilih...</option>
              {divisions.map(d=><option key={d.value} value={d.value}>{d.label}</option>)}
            </SmartNativeSelect>
            {form.divisi && (
              <p className="text-xs text-muted-foreground" data-testid="req-divisi-hint">
                {divisionHint(divisions, form.divisi)}
              </p>
            )}
          </Isian>
          <Isian label="Pemohon" wajib>
            <EmployeeSelect employees={employees} value={form.requester_employee_id}
              onChange={v => setForm(f => ({ ...f, requester_employee_id: v }))}
              placeholder="— pilih karyawan —" testId="req-requester" className="w-full" />
          </Isian>
          <Isian label="Keperluan" htmlFor="req-keperluan">
            <Input id="req-keperluan" value={form.purpose} onChange={e=>setForm({...form,purpose:e.target.value})} placeholder="Untuk apa..." />
          </Isian>
          <Isian label="Dibutuhkan tanggal">
            <DatePicker value={form.needed_by} onChange={v=>setForm(f => ({ ...f, needed_by: v }))} testId="req-needed-by" />
          </Isian>
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium">Item yang diminta</p>
            <Button type="button" variant="link" size="sm" className="px-0" onClick={addLine}><Plus /> Tambah item</Button>
          </div>
          {lines.map((ln,i) => (
            <div key={i} className="flex items-center gap-2">
              <SmartNativeSelect value={ln.acc_id} onChange={e=>lineChange(i,e.target.value)} className="w-full" wrapperClassName="min-w-0 flex-1 sm:max-w-[26rem]" data-testid={`req-item-${i}`}>
                <option value="">Pilih item...</option>
                {items.map(a=><option key={a.id} value={a.id}>{`${a.code ? `${a.code} · ` : ''}${a.name} (stok: ${a.stock_qty} ${a.unit})`}</option>)}
              </SmartNativeSelect>
              <Input type="number" min="1" value={ln.qty_requested} onChange={e=>updateLine(i,'qty_requested',+e.target.value)}
                className="w-20" placeholder="Qty" aria-label="Jumlah" />
              <span className="w-10 text-sm text-muted-foreground">{ln.unit}</span>
              {lines.length > 1 && (
                <Button type="button" variant="ghost" size="icon-sm" onClick={()=>removeLine(i)} title="Hapus baris" aria-label="Hapus baris">
                  <X />
                </Button>
              )}
            </div>
          ))}
        </div>

        <DocNumberField
          policy={numPolicy} value={reqCode} onChange={setReqCode}
          testId="int-req-docnum" label="Nomor Permintaan" />
      </FormPopup>
    </PageLayout>
  );
}

// ─── TAB 3: STOK OPNAME ─────────────────────────────────────────────────────
// 2026-11-02 (keputusan owner K9 — "dipisahkan saja pakai mesin yang sama"): tab ini dulu punya
// mesin opname sendiri (stok sistem = total SEMUA lokasi, baris tak dihitung dilewati, satu jurnal
// per material, tidak buta). Menu Portal Aksesoris tetap ada, tetapi menampilkan layar Sesi Opname
// bersama (mesin tunggal `core/opname_engine.py`) terfilter jenis aksesoris: hitung buta, per lokasi,
// "belum dihitung" ≠ 0, satu jurnal per sesi ke 1-1402. Sesi lama tampil sebagai arsip baca-saja.
function StokOpnameTab({ token }) {
  return <WMSOpnameScanModule token={token} kind="aksesoris" />;
}

// ─── PENUNJUK ARAH: PEMINJAMAN (tab lama dilepas di FASE 10) ─────────────────
// Tab "Peminjaman" dihapus karena satu-satunya sumber datanya adalah koleksi legacy
// `acc_loans` — yang di FASE 10 sudah ditutup (semua pinjaman lama dikembalikan +
// stok dipulihkan lewat migrasi terpandu) lalu di-drop. Peminjaman alat/aset adalah
// domain ASET sejak ACC-3. Tautan/bookmark lama (`?tab=pinjam`) tidak dibiarkan
// buntu: user diarahkan ke tempat yang benar, bukan melihat layar kosong/500.
function LegacyLoanRedirect({ onNavigate, onBack }) {
  return (
    <EmptyState icon={RotateCcw} testId="acc-loans-moved" title="Peminjaman pindah ke Manajemen Aset"
      description="Yang dipinjam-kembalikan adalah unit aset bernomor (mesin, alat, gunting), bukan stok aksesoris habis pakai. Peminjaman kini dicatat di Manajemen Aset › Peminjaman Alat; data pinjaman aksesoris lama sudah ditutup dan stoknya dikembalikan. Aksesoris habis pakai tetap lewat Permintaan internal › Persetujuan › Serahkan."
      action={
        <div className="flex flex-wrap items-center justify-center gap-2">
          <Button variant="outline" onClick={onBack} data-testid="acc-loans-back">Kembali ke Master & stok</Button>
          {onNavigate && (
            <Button onClick={() => onNavigate('asset-loans')} data-testid="acc-loans-open-asset-loans">
              Buka Peminjaman Alat
            </Button>
          )}
        </div>
      } />
  );
}

// ─── TAB 5: PURCHASE REQUEST ─────────────────────────────────────────────────
// 2026-11-06 (Tahap 2): label status berbahasa Indonesia; "(lama)" = alur sebelum lewat Pengadaan
const PR_STATUS_LABEL = {
  Draft: 'Draf', Forwarded: 'Diteruskan ke Pengadaan', Submitted: 'Diajukan (lama)',
  Approved: 'Disetujui (lama)', Rejected: 'Ditolak', Ordered: 'Dipesan (lama)',
  Received: 'Diterima (lama)', Cancelled: 'Dibatalkan',
};

function PurchaseRequestTab({ token, items, title, subtitle, ringkasan }) {
  const [prs, setPRs]         = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShow]   = useState(false);
  const [form, setForm]       = useState({ priority:'Normal', purpose:'', supplier:'', supplier_id:'', notes:'', items:[] });
  const [lines, setLines]     = useState([{ acc_id:'', qty_requested:1, unit:'pcs', estimated_price:0, notes:'' }]);
  const [filter, setFilter]   = useState('');
  const [saving, setSaving]   = useState(false);
  const [err, setErr]         = useState('');
  const [formErr, setFormErr] = useState('');
  // SESI #27 — nomor PR aksesoris mengikuti kebijakan Otomatis/Manual milik owner.
  const numPolicy = useDocNumberPolicy('acc_purchase_requests.pr_number', token);
  const [prNumber, setPrNumber] = useState('');
  const suppliers = useSupplierOptions(token);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = filter ? `?status=${filter}` : '';
      const data = await api('GET', `/api/acc/purchase-requests${params}`, token);
      setPRs(Array.isArray(data) ? data : []);
    } catch(e) { setErr(e.message); }
    finally { setLoading(false); }
  }, [token, filter]);

  useEffect(() => { load(); }, [load]);

  const addLine = () => setLines([...lines,{acc_id:'',qty_requested:1,unit:'pcs',estimated_price:0,notes:''}]);
  const removeLine = idx => setLines(lines.filter((_,i)=>i!==idx));
  const updateLine = (idx,k,v) => setLines(lines.map((l,i)=>i===idx?{...l,[k]:v}:l));

  const lineChange = (idx, acc_id) => {
    const acc = items.find(a=>a.id===acc_id);
    setLines(prev => prev.map((l,i)=>i===idx ? {...l, acc_id, acc_name:acc?.name||'', unit:acc?.unit||'pcs'} : l));
  };

  const submit = async () => {
    const validLines = lines.filter(l=>l.acc_id && l.qty_requested>0);
    if (!validLines.length) { setFormErr('Minimal 1 item'); return; }
    setSaving(true); setFormErr('');
    try {
      // 12 Nov 2026 (K-M2): aksesoris yang hanya dipakai model lambat/tidak laku → dialog alasan lalu kirim ulang.
      await denganAlasanMerchandiser((extra) => api('POST', '/api/acc/purchase-requests', token,
                { ...form, items: validLines, ...extra,
                  ...docNumberPayload(numPolicy, 'pr_number', prNumber) }));
      setShow(false); setLines([{acc_id:'',qty_requested:1,unit:'pcs',estimated_price:0,notes:''}]);
      setForm({ priority:'Normal', purpose:'', supplier:'', supplier_id:'', notes:'', items:[] });
      load();
    } catch(e) { setFormErr(e.message); }
    finally { setSaving(false); }
  };

  // 2026-08-07 — keputusan persetujuan TIDAK lagi lewat PUT status.
  // Sebelumnya `PUT /api/acc/purchase-requests/{id}` menerima status apa pun
  // tanpa RBAC sama sekali: siapa pun yang login (termasuk PEMBUAT PR-nya)
  // bisa menyetujui pembelian bernilai berapa pun. Sekarang submit/approve/
  // reject memakai mesin persetujuan yang SAMA dengan Permintaan Pengadaan
  // (bertahap sesuai nilai, tidak boleh setujui PR sendiri, override admin
  // tercatat), dan tombolnya mengikuti flag `can_approve`/`can_reject` dari
  // server — bukan ditebak dari status di frontend.
  const [prMsg, setPrMsg] = useState('');
  const act = async (id, action, body = {}) => {
    setErr(''); setPrMsg('');
    try {
      const res = await api('POST', `/api/acc/purchase-requests/${id}/${action}`, token, body);
      if (res?.message) setPrMsg(res.message);
      else if (action === 'forward' && res?.procurement_pr_number) setPrMsg(`Diteruskan ke Permintaan Pengadaan ${res.procurement_pr_number}.`);
      load();
    }
    catch(e) { setErr(e.message); }
  };

  // Alasan penolakan lewat dialog aplikasi (dulu window.prompt bawaan peramban).
  const doReject = async (pr) => {
    const reason = await confirmDialog({
      title: `Tolak ${pr.pr_number}?`,
      body: 'Alasan wajib diisi agar pemohon tahu apa yang harus diperbaiki.',
      confirmLabel: 'Tolak', danger: true,
      input: { label: 'Alasan penolakan', placeholder: 'Mis. jumlah melebihi kebutuhan bulan ini' },
    });
    if (reason === false || reason === null) return;
    if (!String(reason).trim()) { setErr('Alasan penolakan wajib diisi.'); return; }
    await act(pr.id, 'reject', { reason });
  };

  // 2026-11-06 (Tahap 2): tombol "Order" & "Terima Barang" DIHAPUS — "Terima Barang" dulu menambah
  // stok tanpa nilai & tanpa jurnal. Pesan & terima lewat Pengadaan (PO → Penerimaan Barang).

  const totalEst = lines.reduce((s,l)=>s + (parseFloat(l.qty_requested)||0)*(parseFloat(l.estimated_price)||0), 0);

  const kolom = [
    { kunci: 'no', label: 'No. PR', hp: 'judul', isi: (pr) => <span className="font-medium tabular-nums">{pr.pr_number}</span> },
    { kunci: 'keperluan', label: 'Keperluan', hp: 'keterangan', isi: (pr) => (
      <span className="block max-w-xs truncate" title={pr.purpose || ''}>{pr.purpose || '—'}</span>) },
    { kunci: 'supplier', label: 'Supplier', isi: (pr) => <span className="text-muted-foreground">{pr.supplier || '—'}</span> },
    { kunci: 'prioritas', label: 'Prioritas', isi: (pr) => (
      <StatusBadge status={pr.priority} label={PR_PRIORITY_LABEL[pr.priority] || pr.priority} tone={PR_PRIORITY_TONE[pr.priority] || 'muted'} />) },
    { kunci: 'total', label: 'Perkiraan total', rata: 'kanan', isi: (pr) => <span className="font-medium tabular-nums">{fmtRp(pr.total_estimated)}</span> },
    { kunci: 'status', label: 'Status', isi: (pr) => (
      <div className="space-y-1">
        <StatusBadge status={pr.status} label={PR_STATUS_LABEL[pr.status] || pr.status} tone={PR_STATUS_TONE[pr.status] || 'muted'} />
        {pr.procurement && (
          <div className="text-xs leading-snug text-muted-foreground" data-testid={`pr-proc-${pr.id}`}>
            <div className="tabular-nums">{pr.procurement.pr_number} · {pr.procurement.pr_status_label}</div>
            {pr.procurement.po_number && (
              <div className="tabular-nums">PO {pr.procurement.po_number}{pr.procurement.receive_label ? ` · ${pr.procurement.receive_label}` : ''}</div>
            )}
          </div>
        )}
        {pr.status === 'Submitted' && pr.stage_label && (
          <div className="text-xs text-muted-foreground" data-testid={`pr-stage-${pr.id}`}>
            {pr.stage_label}{pr.total_stages ? ` (${pr.stage_order}/${pr.total_stages})` : ''}
          </div>
        )}
      </div>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (pr) => (
      <div className="flex flex-wrap items-center justify-end gap-1">
        {(pr.status === 'Draft' || pr.status === 'Forwarded') && pr.can_submit && (
          <Button size="sm" variant="outline" onClick={()=>act(pr.id,'submit')} data-testid={`submit-pr-${pr.id}`}>Ajukan</Button>
        )}
        {pr.status === 'Submitted' && pr.can_approve && (
          <>
            <Button size="sm" variant="success" onClick={()=>act(pr.id,'approve')} data-testid={`approve-pr-${pr.id}`}
              title={pr.stage_label ? `Setujui — ${pr.stage_label}` : 'Setujui'}>Setujui</Button>
            <Button size="sm" variant="destructive" onClick={()=>doReject(pr)} data-testid={`reject-pr-${pr.id}`}>Tolak</Button>
          </>
        )}
        {pr.status === 'Submitted' && !pr.can_approve && (
          <span className="max-w-[16rem] text-right text-xs leading-snug text-muted-foreground" data-testid={`pr-blocked-${pr.id}`}>
            {pr.blocked_reason || 'Menunggu penyetuju yang berhak.'}
          </span>
        )}
        {/* 2026-11-06 (Tahap 2): PR lama yang sudah disetujui/dipesan diteruskan ke Pengadaan
            supaya dibuatkan PO dan diterima lewat Penerimaan Barang (bernilai & berjurnal). */}
        {(pr.status === 'Approved' || pr.status === 'Ordered') && (
          <Button size="sm" variant="outline" onClick={()=>act(pr.id,'forward')} data-testid={`forward-pr-${pr.id}`}>
            Teruskan ke Pengadaan
          </Button>
        )}
      </div>) },
  ];

  return (
    <PageLayout title={title} subtitle={subtitle} testId="acc-pr-tab"
      actions={<Button onClick={()=>{setShow(true);setFormErr('');}} data-testid="add-pr-btn"><Plus /> Buat permintaan beli</Button>}
      filters={
        <SmartNativeSelect value={filter} onChange={e=>setFilter(e.target.value)} className="w-56" data-testid="pr-status-filter">
          <option value="">Semua status</option>
          {['Draft','Forwarded','Submitted','Approved','Rejected','Ordered','Received'].map(s=><option key={s} value={s}>{PR_STATUS_LABEL[s] || s}</option>)}
        </SmartNativeSelect>
      }
      tools={<>
        <TombolUnduh namaBerkas="permintaan-beli-aksesoris" namaLembar="Permintaan beli" baris={prs} testId="pr-unduh"
          kolom={[
            { label: 'No. PR', nilai: (pr) => pr.pr_number },
            { label: 'Keperluan', nilai: (pr) => pr.purpose || '' },
            { label: 'Supplier', nilai: (pr) => pr.supplier || '' },
            { label: 'Prioritas', nilai: (pr) => PR_PRIORITY_LABEL[pr.priority] || pr.priority || '' },
            { label: 'Perkiraan total (Rp)', nilai: (pr) => Number(pr.total_estimated || 0) },
            { label: 'Status', nilai: (pr) => PR_STATUS_LABEL[pr.status] || pr.status },
            { label: 'Permintaan pengadaan', nilai: (pr) => (pr.procurement ? `${pr.procurement.pr_number} · ${pr.procurement.pr_status_label || ''}` : '') },
            { label: 'PO', nilai: (pr) => pr.procurement?.po_number || '' },
          ]} />
        <TombolMuatUlang onClick={load} memuat={loading} />
      </>}
      summary={<>
        {ringkasan}
        {/* 2026-11-06 (Tahap 2): alur pembelian aksesoris = alur Pengadaan */}
        <p className="text-sm text-muted-foreground" data-testid="pr-flow-help">
          PR yang diajukan diteruskan ke Permintaan Pengadaan dan disetujui di sana. Barang masuk stok lewat PO
          dan Penerimaan Barang, sehingga nilai persediaan dan jurnalnya tercatat.
        </p>
      </>}>
      {prMsg && <Notice tone="success" testId="pr-msg">{prMsg}</Notice>}
      {err && <Notice tone="danger">{err}</Notice>}

      {loading && prs.length === 0 ? <Memuat teks="Memuat permintaan beli…" /> : (
        <TabelData kolom={kolom} baris={prs} testId="acc-pr-table"
          kosong={<EmptyState icon={ShoppingCart} title="Belum ada permintaan beli aksesoris"
            description="Buat permintaan beli untuk mengajukan pembelian aksesoris lewat Pengadaan." />} />
      )}

      {/* Form permintaan beli (popup panjang) */}
      <FormPopup open={showForm} onClose={()=>setShow(false)} ukuran="panjang" onSimpan={submit} menyimpan={saving}
        galat={formErr} judul="Buat permintaan beli aksesoris" labelSimpan="Simpan draf" testId="acc-pr-form">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Isian label="Prioritas">
            <SmartNativeSelect value={form.priority} onChange={e=>setForm({...form,priority:e.target.value})} className="w-full" data-testid="pr-priority">
              {['Urgent','Normal','Low'].map(p=><option key={p} value={p}>{PR_PRIORITY_LABEL[p]}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Supplier usulan">
            <SupplierPick suppliers={suppliers} form={form} setForm={setForm}
              className="w-full" data-testid="pr-supplier" />
          </Isian>
        </div>
        <Isian label="Keperluan / alasan" htmlFor="pr-keperluan">
          <Input id="pr-keperluan" value={form.purpose} onChange={e=>setForm({...form,purpose:e.target.value})}
            placeholder="Stok habis, mendesak untuk order WO-XXX..." data-testid="pr-purpose" />
        </Isian>
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium">Item yang dipesan</p>
            <Button type="button" variant="link" size="sm" className="px-0" onClick={addLine}><Plus /> Tambah item</Button>
          </div>
          {lines.map((ln,i)=>(
            <div key={i} className="flex flex-wrap items-center gap-2 sm:flex-nowrap">
              <SmartNativeSelect value={ln.acc_id} onChange={e=>lineChange(i,e.target.value)} className="w-full" wrapperClassName="w-full min-w-0 sm:w-auto sm:flex-1 sm:max-w-[22rem]" data-testid={`pr-item-${i}`}>
                <option value="">Pilih item...</option>
                {items.map(a=><option key={a.id} value={a.id}>{`${a.code ? `${a.code} · ` : ''}${a.name} (stok: ${a.stock_qty} ${a.unit})`}</option>)}
              </SmartNativeSelect>
              <Input type="number" min="1" value={ln.qty_requested} onChange={e=>updateLine(i,'qty_requested',+e.target.value)}
                className="w-20" placeholder="Qty" aria-label="Jumlah" />
              <span className="text-sm text-muted-foreground">{ln.unit}</span>
              <MoneyInput value={ln.estimated_price} onChange={e=>updateLine(i,'estimated_price',+e.target.value)}
                className="w-32" placeholder="Perkiraan harga" aria-label="Perkiraan harga satuan" />
              {lines.length>1 && (
                <Button type="button" variant="ghost" size="icon-sm" onClick={()=>removeLine(i)} title="Hapus baris" aria-label="Hapus baris">
                  <X />
                </Button>
              )}
            </div>
          ))}
          <p className="text-right text-sm font-medium text-[hsl(var(--primary))]">Perkiraan total: {fmtRp(totalEst)}</p>
        </div>
        <Isian label="Catatan" htmlFor="pr-catatan">
          <Textarea id="pr-catatan" value={form.notes} onChange={e=>setForm({...form,notes:e.target.value})} rows={2} />
        </Isian>

        <DocNumberField
          policy={numPolicy} value={prNumber} onChange={setPrNumber}
          testId="pr-docnum" label="Nomor Permintaan Beli" />
      </FormPopup>
    </PageLayout>
  );
}

// ─── ROOT COMPONENT ──────────────────────────────────────────────────────────
/**
 * 2026-08-06 — `allowedTabs` + judul/subjudul yang bisa ditimpa.
 *
 * KENAPA: pintu Portal Pengadaan `proc-accessory-pr` me-render modul ini dengan
 * tab 'pr' terpilih, TAPI seluruh tab lain (Master & Stok, Request Internal,
 * Stok Opname, Valuasi HPP) tetap terlihat. Akibatnya pekerjaan Portal Aksesoris
 * bisa dibuka dari Portal Pengadaan — melanggar prinsip "satu pintu satu tempat"
 * yang jadi alasan portal ini dipisah, dan membingungkan staf pengadaan yang
 * hanya perlu MEMBELI. Dengan `allowedTabs` pintu pengadaan menampilkan tab
 * pembelian saja; Portal Aksesoris tetap memakai modul yang sama tanpa batasan
 * (tidak ada duplikasi komponen).
 */
export default function AccessoryModule({
  token, userRole, defaultTab = 'master', onNavigate,
  allowedTabs = null, headerTitle, headerSubtitle,
}) {
  const [tab, setTab]     = useState(defaultTab);
  const [dash, setDash]   = useState(null);
  const [items, setItems] = useState([]);  // shared items list for sub-tabs

  const loadDash = useCallback(async () => {
    try {
      const d = await api('GET', '/api/acc/dashboard', token);
      setDash(d);
    } catch { /* dashboard opsional — jangan blokir layar */ }
  }, [token]);

  const loadItems = useCallback(async () => {
    try {
      const data = await api('GET', '/api/acc/items', token);
      setItems(Array.isArray(data) ? data : []);
    } catch { /* daftar item opsional — sub-tab menangani kosong */ }
  }, [token]);

  useEffect(() => { loadDash(); loadItems(); }, [loadDash, loadItems]);

  const refreshAll = () => { loadDash(); loadItems(); };
  // Judul = label menu yang membuka modul ini (Standar UI/UX v2: judul halaman = label menu).
  const JUDUL_MENU = { master: 'Master Aksesoris', opname: 'Stok Opname', internal: 'Request Internal' };
  const judul = headerTitle || JUDUL_MENU[defaultTab] || 'Manajemen Aksesoris';
  const sub = headerSubtitle || 'Master, stok, permintaan internal, permintaan beli, dan valuasi aksesoris produksi.';

  // FASE 10 — tab "Peminjaman" DILEPAS. Peminjaman alat/aset sudah pindah ke
  // Manajemen Aset → Peminjaman Alat sejak ACC-3; tab ini hanya membaca koleksi
  // legacy `acc_loans` yang kini sudah ditutup & di-drop. Deep-link lama
  // (`?tab=pinjam`) tetap ditangani: lihat LegacyLoanRedirect di bawah.
  const ALL_TABS = [
    { id:'master',   label:'Master & stok',       Component: MasterTab,
      props: { token, onRefreshDash: refreshAll, title: judul, subtitle: sub } },
    { id:'internal', label:'Permintaan internal', Component: RequestInternalTab,
      props: { token, items, title: judul, subtitle: sub } },
    { id:'opname',   label:'Stok opname',         Component: StokOpnameTab, props: { token } },
    { id:'pr',       label:'Permintaan beli',     Component: PurchaseRequestTab,
      props: { token, items, title: judul, subtitle: sub } },
    { id:'valuasi',  label:'Valuasi HPP',         Component: AccessoryValuationTab,
      props: { token, onRefreshDash: refreshAll } },
  ];
  const TABS = Array.isArray(allowedTabs) && allowedTabs.length
    ? ALL_TABS.filter(t => allowedTabs.includes(t.id))
    : ALL_TABS;
  const scoped = TABS.length !== ALL_TABS.length;
  // "Buka Valuasi HPP" dari form Master hanya bila tab Valuasi ada di pintu ini
  const masterTab = TABS.find(t => t.id === 'master');
  if (masterTab) masterTab.props.onOpenValuation = TABS.some(t => t.id === 'valuasi') ? () => setTab('valuasi') : null;

  // Stok habis / menipis — di pintu pengadaan justru pemicu pembelian. Dulu hanya item "menipis"
  // (maks 5) yang tampil; item yang stoknya HABIS tidak disebut sama sekali (data uji: 324 dari 324 habis).
  const habis = Number(dash?.out_of_stock || 0);
  const menipis = Number(dash?.low_stock || 0);
  const daftarMenipis = dash?.low_stock_items || [];
  const peringatanStok = dash && (habis > 0 || menipis > 0) && (
    <Notice tone="warning" icon={AlertTriangle} testId="acc-low-stock-alert"
      title={`${fmtNum(habis)} aksesoris stok habis · ${fmtNum(menipis)} stok menipis — perlu permintaan beli`}>
      {daftarMenipis.length > 0 && (
        <span>
          Menipis: {daftarMenipis.map(it => `${it.name} ${fmtNum(it.stock_qty)}/${fmtNum(it.min_stock)} ${it.unit}`).join(' · ')}
          {menipis > daftarMenipis.length ? ` · dan ${fmtNum(menipis - daftarMenipis.length)} lainnya` : ''}.
        </span>
      )}
    </Notice>
  );

  // Pintu satu tab (mis. Portal Pengadaan › Request Aksesoris): tab dirender langsung sebagai halaman.
  if (TABS.length < 2) {
    const t = TABS[0];
    if (!t) return null;
    return <t.Component {...t.props} ringkasan={peringatanStok} />;
  }

  // Ringkasan modul = satu kalimat (dulu 4 kartu di atas tab; di tab Valuasi HPP jadi dua baris kartu
  // sehingga tabel baru mulai di tengah layar). Angka & sumbernya tetap sama (`/api/acc/dashboard`).
  const ringkasan = dash && !scoped && (
    <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-sm text-muted-foreground" data-testid="acc-summary">
      <span title="Aksesoris aktif yang stoknya 0 atau kurang.">
        Stok habis <b className={habis ? 'tabular-nums text-[hsl(var(--danger-text))]' : 'tabular-nums text-foreground'}>{fmtNum(habis)}</b>
        {' '}dari {fmtNum(dash.total_items)} item aktif
      </span>
      <span aria-hidden="true">·</span>
      <span title="Masih ada, tetapi di bawah stok minimum.">
        Stok menipis <b className={menipis ? 'tabular-nums text-[hsl(var(--warning-text))]' : 'tabular-nums text-foreground'}>{fmtNum(menipis)}</b>
      </span>
      <span aria-hidden="true">·</span>
      {/* FASE 8 — KPI valuasi menggantikan kartu "Dipinjam" (peminjaman pindah ke Portal Aset sejak ACC-3) */}
      <span>
        Nilai persediaan <b className="tabular-nums text-foreground">{fmtRp(dash.total_stock_value)}</b>
        {dash.unvalued_items
          ? <span className="text-[hsl(var(--warning-text))]"> ({fmtNum(dash.unvalued_items)} item belum punya HPP)</span>
          : ' (semua item sudah punya HPP)'}
      </span>
      <span aria-hidden="true">·</span>
      <span title="Permintaan aksesoris yang diajukan dan belum diputuskan (semua jenis, sama dengan Inbox Persetujuan).">
        Permintaan menunggu <b className="tabular-nums text-foreground">{fmtNum(dash.pending_requests)}</b>
        {' '}({fmtNum(dash.pending_pr)} permintaan beli berjalan)
      </span>
    </p>
  );

  return (
    <PageLayout testId="accessory-module" title={judul} subtitle={sub}
      summary={(ringkasan || daftarMenipis.length > 0) && (
        <>
          {ringkasan}
          {/* Daftar item menipis tetap tampil (pemicu pembelian); jumlah habis sudah ada di kartu. */}
          {daftarMenipis.length > 0 && (
            <Notice tone="warning" icon={AlertTriangle} testId="acc-low-stock-alert"
              title={`${fmtNum(menipis)} aksesoris stok menipis — perlu permintaan beli`}>
              {daftarMenipis.map(it => `${it.name} ${fmtNum(it.stock_qty)}/${fmtNum(it.min_stock)} ${it.unit}`).join(' · ')}
              {menipis > daftarMenipis.length ? ` · dan ${fmtNum(menipis - daftarMenipis.length)} lainnya` : ''}.
            </Notice>
          )}
        </>
      )}>
      {/* FASE 10 — tautan lama `?tab=pinjam` tidak boleh buntu: penunjuk arah ke tempat yang benar. */}
      {tab === 'pinjam' ? (
        <LegacyLoanRedirect onNavigate={onNavigate} onBack={() => setTab('master')} />
      ) : (
        <HubTabs hubId="acc-tabs" value={TABS.some(t => t.id === tab) ? tab : TABS[0].id} onValueChange={setTab}
          tabs={TABS.map(t => ({ key: t.id, label: t.label, Component: t.Component, props: t.props }))} />
      )}
    </PageLayout>
  );
}

/**
 * Aksesoris Management — Full Implementation (Blueprint §3.3)
 * Tabs:
 *   1. Master & Stok   — CRUD + stock levels + alerts
 *   2. Request Internal — divisi → Admin Aksesoris
 *   3. Stok Opname      — sesi count fisik + adjustment
 *   4. Peminjaman       — borrow & return tracking
 *   5. Purchase Request — PR ke Finance
 *   6. Valuasi HPP      — nilai persediaan, set HPP (rata-rata bergerak), scrap bernilai (FASE 8)
 */

import { useState, useEffect, useCallback } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import {
  Package, Plus, Edit2, Trash2, Search, X, CheckCircle, Clock,
  AlertTriangle, TrendingDown, FileText, RotateCcw, ShoppingCart,
  ChevronDown, ChevronUp, RefreshCw, Eye, Check, XCircle,  ArrowUpCircle, ArrowDownCircle, ClipboardCheck, Banknote,
  PackageMinus, PackagePlus, Info, BarChart3
} from 'lucide-react';
import { EmptyState } from './EmptyState';
import { Skeleton } from '@/components/ui/skeleton';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import UomEditor from './UomEditor';
// MATERIAL_UNITS = cermin persis daftar satuan backend (satu sumber, tanpa konversi diam-diam)
import { resolveUoms, sanitizeUoms, purchaseUomOf, issueUomOf, displayUomOf, MATERIAL_UNITS } from '@/lib/uom';
import { Button } from '@/components/ui/button';
import useUomOptions from '@/hooks/useUomOptions';
import { UomSelect, UomConversionHint, baseUnitOf, toBaseQty } from './uom/UomPicker';
// FASE 8: tab valuasi HPP aksesoris (nilai persediaan + set HPP + scrap bernilai)
import AccessoryValuationTab from './accessory/AccessoryValuationTab';
// F15-B — kelas Tailwind tidak boleh dirakit saat berjalan; lihat lib/tone.js
import { tone } from '@/lib/tone';
import { MoneyInput } from '@/components/ui/money-input';
import DocNumberField, { useDocNumberPolicy, docNumberPayload } from './docnum/DocNumberField';
// 2026-11-02 (K9): tab Stok Opname = layar Sesi Opname bersama (mesin tunggal), terfilter aksesoris
import WMSOpnameScanModule from './WMSOpnameScanModule';

const API = process.env.REACT_APP_BACKEND_URL || '';

const DIVISI = ['Produksi', 'Cutting', 'CMT', 'Gudang', 'Kantor', 'SDM', 'QC', 'Packing', 'Marketing', 'Lainnya'];
// 2026-11-06 (Tahap 1): pilihan satuan = MATERIAL_UNITS (sama dengan yang diterima backend).
// Dulu daftar sendiri: "lembar" tersimpan jadi "pcs", "roll" jadi "rol", pak/gross tidak ada.
// Satuan lama item yang tidak ada di daftar tetap ditampilkan supaya tidak berubah diam-diam.
const unitOptions = (current) => (current && !MATERIAL_UNITS.includes(current)
  ? [current, ...MATERIAL_UNITS] : MATERIAL_UNITS);
const STATUS_COLOR = {
  ok:      'text-emerald-600 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-500/10',
  low:     'text-amber-700 dark:text-amber-400 bg-amber-100 dark:bg-amber-500/10',
  out:     'text-red-700 dark:text-red-400 bg-red-100 dark:bg-red-500/10',
  Pending:   'text-amber-700 dark:text-amber-400 bg-amber-100 dark:bg-amber-500/10',
  Approved:  'text-sky-600 dark:text-sky-400 bg-sky-100 dark:bg-sky-500/10',
  Rejected:  'text-red-700 dark:text-red-400 bg-red-100 dark:bg-red-500/10',
  Issued:    'text-emerald-600 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-500/10',
  Active:    'text-sky-600 dark:text-sky-400 bg-sky-100 dark:bg-sky-500/10',
  Returned:  'text-emerald-600 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-500/10',
  Overdue:   'text-red-700 dark:text-red-400 bg-red-100 dark:bg-red-500/10',
  Draft:     'text-muted-foreground bg-muted dark:bg-slate-500/10',
  Submitted: 'text-amber-700 dark:text-amber-400 bg-amber-100 dark:bg-amber-500/10',
  Completed: 'text-emerald-600 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-500/10',
  Cancelled: 'text-muted-foreground bg-muted dark:bg-slate-500/10',
  Ordered:   'text-violet-600 dark:text-violet-400 bg-violet-100 dark:bg-violet-500/10',
  Received:  'text-emerald-600 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-500/10',
};

function Badge({ status, label }) {
  const cls = STATUS_COLOR[status] || 'text-muted-foreground bg-secondary';
  return <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${cls}`}>{label || status}</span>;
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
  if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
  return data;
}

// ─── TAB 1: MASTER & STOK ────────────────────────────────────────────────────
function MasterTab({ token, onRefreshDash, onOpenValuation }) {
  const [items, setItems]       = useState([]);
  const [loading, setLoading]   = useState(true);
  const [search, setSearch]     = useState('');
  const [catFilter, setCat]     = useState('');
  const [showForm, setShowForm] = useState(false);
  const [editItem, setEditItem] = useState(null);
  const [form, setForm]         = useState({ code:'', name:'', category:'Umum', unit:'pcs', description:'', min_stock:0, unit_cost:0, supplier:'', notes:'', uoms:[], purchase_uom:'', issue_uom:'', display_uom:'', pack_unit:'pack', pack_size:1, display_in_packs:false });
  const [showMove, setShowMove] = useState(null); // {id, name, action:'in'|'out'}
  const [moveForm, setMoveForm] = useState({ qty:'', notes:'', input_unit:'base', unit_cost:'' });
  const [moveResult, setMoveResult] = useState('');
  const [saving, setSaving]     = useState(false);
  const [err, setErr]           = useState('');
  const [msg, setMsg]           = useState('');
  // FASE 10: konfirmasi hapus memakai modal seragam (bukan window.confirm native)
  const [delItem, setDelItem]   = useState(null); // {id, name, code}

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

  const cats = [...new Set(items.map(i => i.category).filter(Boolean))];

  const openAdd = () => { setEditItem(null); setForm({ code:'', name:'', category:'Umum', unit:'pcs', description:'', min_stock:0, unit_cost:0, supplier:'', notes:'', uoms:[], purchase_uom:'', issue_uom:'', display_uom:'', pack_unit:'pack', pack_size:1, display_in_packs:false }); setShowForm(true); };
  const openEdit = it => { setEditItem(it); setForm({ code: it.code||'', name: it.name||'', category: it.category||'Umum', unit: it.unit||'pcs', description: it.description||'', min_stock: it.min_stock||0, unit_cost: it.unit_cost||0, supplier: it.supplier||'', notes: it.notes||'', uoms: resolveUoms(it), purchase_uom: purchaseUomOf(it), issue_uom: issueUomOf(it), display_uom: displayUomOf(it), pack_unit: it.pack_unit||'pack', pack_size: it.pack_size||1, display_in_packs: it.display_in_packs||false }); setShowForm(true); };

  const save = async () => {
    if (!form.name.trim()) return;
    setSaving(true); setErr('');
    try {
      // Satuan dinormalkan dulu; backend (core/uom) memvalidasi ulang dan
      // menulis cermin pack_unit/pack_size sendiri (INV-UOM-4).
      const payload = { ...form, uoms: sanitizeUoms(form.uoms, form.unit) };
      // HPP item lama tidak dikirim: perubahan HPP hanya lewat Set HPP (revaluasi berjurnal, K12)
      if (editItem) { delete payload.unit_cost; await api('PUT', `/api/acc/items/${editItem.id}`, token, payload); }
      else          await api('POST', '/api/acc/items', token, payload);
      setShowForm(false); load(); onRefreshDash();
    } catch(e) { setErr(e.message); }
    finally { setSaving(false); }
  };

  const del = async it => {
    setErr(''); setMsg('');
    setDelItem({ id: it.id, name: it.name, code: it.code });
  };

  const confirmDel = async () => {
    setSaving(true); setErr('');
    try {
      await api('DELETE', `/api/acc/items/${delItem.id}`, token);
      setMsg(`Aksesoris ${delItem.code || ''} ${delItem.name} dihapus.`);
      setDelItem(null);
      load(); onRefreshDash();
    }
    catch(e) { setErr(e.message); }
    finally { setSaving(false); }
  };

  const doMove = async () => {
    const qty = parseFloat(moveForm.qty);
    if (!qty || qty <= 0) { setErr('Qty harus > 0'); return; }
    setSaving(true); setErr(''); setMoveResult('');
    try {
      const isIn = showMove.action === 'in';
      const path = isIn ? '/api/acc/stock/receive' : '/api/acc/stock/issue';
      const unitCode = (moveUnit && moveUnit !== moveBaseUnit) ? moveUnit : 'base';
      const payload = { acc_id: showMove.id, qty, notes: moveForm.notes, input_unit: unitCode };
      // FASE 8: harga satuan penerimaan (opsional) → memperbarui HPP master (rata-rata bergerak)
      // BUG-1: kirim `cost_unit` eksplisit supaya backend tahu harga yang diketik user
      // mengacu ke satuan kemasan atau satuan dasar. Backend selalu menyimpan per satuan dasar.
      if (isIn && moveForm.unit_cost !== '' && Number(moveForm.unit_cost) >= 0) {
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
      setShowMove(null); setMoveForm({ qty:'', notes:'', input_unit:'base', unit_cost:'' }); load(); onRefreshDash();
    } catch(e) { setErr(e.message); }
    finally { setSaving(false); }
  };

  const lowCount = items.filter(i => i.stock_status === 'low').length;
  const outCount = items.filter(i => i.stock_status === 'out').length;

  // RC-UI-03: client-side pagination (10/page) for accessory item catalog
  const itemsPg = useClientPagination(items, 10);

  return (
    <div className="space-y-5">
      {/* Stat Row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label:'Total Item', val: items.length, icon: Package, color:'violet' },
          { label:'Stok Aman', val: items.filter(i=>i.stock_status==='ok').length, icon: CheckCircle, color:'emerald' },
          { label:'Stok Rendah', val: lowCount, icon: AlertTriangle, color:'amber' },
          { label:'Habis', val: outCount, icon: TrendingDown, color:'red' },
        ].map(s => (
          <div key={s.label} className={`border rounded-xl p-3 ${tone(s.color).surface}`}>
            <div className="flex items-center gap-2 mb-1">
              <s.icon className={`w-4 h-4 ${tone(s.color).text}`} />
              <span className="text-xs text-muted-foreground">{s.label}</span>
            </div>
            <div className={`text-2xl font-bold ${tone(s.color).text}`}>{s.val}</div>
          </div>
        ))}
      </div>

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2 border border-border rounded-lg px-3 py-2 bg-[var(--card-surface)] flex-1 min-w-48">
          <Search className="w-4 h-4 text-muted-foreground" />
          <input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Cari aksesoris..." className="flex-1 bg-transparent text-sm focus:outline-none" data-testid="acc-search" />
          {search && <button onClick={()=>setSearch('')}><X className="w-4 h-4 text-muted-foreground" /></button>}
        </div>
        <SmartNativeSelect value={catFilter} onChange={e=>setCat(e.target.value)} className="border border-border rounded-lg px-3 py-2 bg-[var(--card-surface)] text-sm" data-testid="acc-cat-filter">
          <option value="">Semua Kategori</option>
          {cats.map(c=><option key={c} value={c}>{c}</option>)}
        </SmartNativeSelect>
        <button onClick={load} className="p-2 border border-border rounded-lg hover:bg-foreground/5"><RefreshCw className="w-4 h-4" /></button>
        <button onClick={openAdd} className="flex items-center gap-2 px-4 py-2 bg-primary text-foreground rounded-lg text-sm font-medium hover:brightness-110" data-testid="add-acc-btn">
          <Plus className="w-4 h-4" /> Tambah Aksesoris
        </button>
      </div>

      {err && <div className="text-sm text-red-700 dark:text-red-400 bg-red-100 dark:bg-red-500/10 rounded-lg px-4 py-2" data-testid="acc-master-error">{err}</div>}
      {msg && (
        <div className="text-sm text-emerald-700 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-500/10 border border-emerald-300 dark:border-emerald-500/20 rounded-lg px-4 py-2"
          data-testid="acc-master-msg">{msg}</div>
      )}

      {/* Modal hapus aksesoris (pengganti window.confirm native) */}
      {delItem && (
        <div className="fixed inset-0 bg-foreground/40 z-50 flex items-center justify-center p-4" onClick={()=>setDelItem(null)}>
          <div className="bg-[var(--card-surface)] rounded-2xl shadow-xl w-full max-w-sm p-6" onClick={e=>e.stopPropagation()}
            data-testid="acc-delete-modal">
            <h3 className="text-lg font-bold mb-1">Hapus Aksesoris</h3>
            <p className="text-sm text-muted-foreground mb-4">
              <span className="font-mono">{delItem.code}</span> — <strong>{delItem.name}</strong> akan
              dihapus dari master. Riwayat mutasi & jurnal yang sudah terbentuk tetap tersimpan.
              Item yang masih berstok atau terpakai di BOM akan ditolak sistem.
            </p>
            <div className="flex gap-3">
              <button onClick={()=>setDelItem(null)} className="flex-1 py-2 border border-border rounded-lg text-sm hover:bg-foreground/5"
                data-testid="acc-delete-cancel">Batal</button>
              <button onClick={confirmDel} disabled={saving}
                className="flex-1 py-2 bg-red-600 text-white rounded-lg text-sm hover:brightness-110 disabled:opacity-50"
                data-testid="acc-delete-confirm">{saving ? 'Menghapus...' : 'Hapus'}</button>
            </div>
          </div>
        </div>
      )}

      {moveResult && (
        <div className="text-sm text-emerald-700 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-500/10 border border-emerald-300 dark:border-emerald-500/20 rounded-lg px-4 py-2"
          data-testid="acc-move-result">{moveResult}</div>
      )}

      {/* Table */}
      <div className="bg-[var(--card-surface)] rounded-xl border border-border overflow-x-auto">
        <table className="w-full text-sm min-w-[700px]">
          <thead className="bg-[var(--glass-bg)] border-b border-border">
            <tr>
              <th className="text-left px-4 py-3 text-muted-foreground font-medium">Kode</th>
              <th className="text-left px-4 py-3 text-muted-foreground font-medium">Nama</th>
              <th className="text-left px-4 py-3 text-muted-foreground font-medium">Kategori</th>
              <th className="text-right px-4 py-3 text-muted-foreground font-medium">Stok</th>
              <th className="text-right px-4 py-3 text-muted-foreground font-medium">Min</th>
              <th className="text-right px-4 py-3 text-muted-foreground font-medium">Harga Satuan</th>
              <th className="text-right px-4 py-3 text-muted-foreground font-medium">Nilai Stok</th>
              <th className="text-center px-4 py-3 text-muted-foreground font-medium">Status</th>
              <th className="text-right px-4 py-3 text-muted-foreground font-medium">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <tr key={i}>{[...Array(9)].map((__, j) => <td key={j} className="px-3 py-2.5"><Skeleton className="h-4" /></td>)}</tr>
              ))
            ) : items.length === 0 ? (
              <tr><td colSpan="9">
                <EmptyState icon={Package} title="Belum ada item aksesoris" description="Tambah item pertama untuk mulai mengelola stok aksesoris." />
              </td></tr>
            ) : itemsPg.paged.map(it => (
              <tr key={it.id} className="border-b border-border hover:bg-foreground/[0.02]" data-testid={`acc-row-${it.id}`}>
                <td className="px-4 py-3 font-mono text-xs text-muted-foreground">{it.code}</td>
                <td className="px-4 py-3 font-medium">{it.name}</td>
                <td className="px-4 py-3 text-muted-foreground">{it.category}</td>
                <td className="px-4 py-3 text-right font-medium">
                  {it.display_in_packs ? (
                    <div>
                      <div>{fmtNum(it.stock_qty_in_packs)} {it.pack_unit}</div>
                      <div className="text-xs text-muted-foreground">({fmtNum(it.stock_qty)} {it.unit})</div>
                    </div>
                  ) : (
                    <>{fmtNum(it.stock_qty)} <span className="text-xs text-muted-foreground">{it.unit}</span></>
                  )}
                </td>
                <td className="px-4 py-3 text-right text-muted-foreground text-xs">
                  {it.display_in_packs ? (
                    <>{fmtNum(it.min_stock_in_packs)} {it.pack_unit}</>
                  ) : (
                    <>{fmtNum(it.min_stock)}</>
                  )}
                </td>
                <td className="px-4 py-3 text-right text-xs">
                  {(it.unit_cost || 0) > 0
                    ? <span className="text-foreground">Rp {fmtNum(it.unit_cost)}</span>
                    : <span className="text-amber-700 dark:text-amber-400" title="Belum ada harga satuan — selisih opname tidak akan masuk jurnal keuangan">belum diisi</span>}
                </td>
                <td className="px-4 py-3 text-right text-xs text-muted-foreground">
                  {(it.stock_value || 0) > 0 ? <>Rp {fmtNum(it.stock_value)}</> : '-'}
                </td>
                <td className="px-4 py-3 text-center">
                  <Badge status={it.stock_status} label={it.stock_status==='ok'?'Aman':it.stock_status==='low'?'Rendah':'Habis'} />
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-1">
                    <button onClick={()=>{const item=items.find(x=>x.id===it.id); setShowMove({id:it.id,name:it.name,action:'in',unit:item?.unit,pack_unit:item?.pack_unit,pack_size:item?.pack_size,display_in_packs:item?.display_in_packs}); setMoveForm({qty:'',notes:'',input_unit:'base',unit_cost:''}); setErr(''); setMoveResult('');}}
                      className="p-1 hover:bg-emerald-100 dark:bg-emerald-500/10 rounded" title="Terima Stok" data-testid={`acc-in-${it.id}`}>
                      <PackagePlus className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                    </button>
                    <button onClick={()=>{const item=items.find(x=>x.id===it.id); setShowMove({id:it.id,name:it.name,action:'out',unit:item?.unit,pack_unit:item?.pack_unit,pack_size:item?.pack_size,display_in_packs:item?.display_in_packs}); setMoveForm({qty:'',notes:'',input_unit:'base',unit_cost:''}); setErr(''); setMoveResult('');}}
                      className="p-1 hover:bg-amber-100 dark:bg-amber-500/10 rounded" title="Keluarkan Stok" data-testid={`acc-out-${it.id}`}>
                      <PackageMinus className="w-4 h-4 text-amber-700 dark:text-amber-400" />
                    </button>
                    <button onClick={()=>openEdit(it)} className="p-1 hover:bg-foreground/5 rounded" data-testid={`edit-acc-${it.id}`}><Edit2 className="w-4 h-4 text-muted-foreground" /></button>
                    <button onClick={()=>del(it)} className="p-1 hover:bg-red-100 dark:bg-red-500/10 rounded" data-testid={`del-acc-${it.id}`}><Trash2 className="w-4 h-4 text-red-700 dark:text-red-400" /></button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {itemsPg.total > 0 && <PaginationLite page={itemsPg.page} totalPages={itemsPg.totalPages} total={itemsPg.total} pageSize={itemsPg.pageSize} onPageChange={itemsPg.setPage} />}

      {/* Form Modal */}
      {showForm && (
        <div className="fixed inset-0 bg-foreground/40 z-50 flex items-center justify-center p-4" onClick={()=>setShowForm(false)}>
          <div className="bg-[var(--card-surface)] rounded-2xl shadow-xl w-full max-w-md p-6" onClick={e=>e.stopPropagation()}>
            <h3 className="text-lg font-bold mb-4">{editItem ? 'Edit Aksesoris' : 'Tambah Aksesoris'}</h3>
            <div className="space-y-3">
              {[
                {label:'Kode', key:'code', placeholder:'ACC-001'},
                {label:'Nama *', key:'name', placeholder:'Kancing'},
                {label:'Kategori', key:'category', placeholder:'Trimming'},
                {label:'Supplier', key:'supplier', placeholder:'CV. Supplier'},
              ].map(f => (
                <div key={f.key}>
                  <label className="text-xs text-muted-foreground block mb-1">{f.label}</label>
                  <input value={form[f.key]||''} onChange={e=>setForm({...form,[f.key]:e.target.value})}
                    className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-[var(--card-surface)]" placeholder={f.placeholder} />
                </div>
              ))}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-muted-foreground block mb-1">Unit</label>
                  <SmartNativeSelect value={form.unit} onChange={e=>setForm({...form,unit:e.target.value})} className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-[var(--card-surface)]" data-testid="acc-unit-select">
                    {unitOptions(editItem?.unit).map(u=><option key={u} value={u}>{u}</option>)}
                  </SmartNativeSelect>
                </div>
                <div>
                  <label className="text-xs text-muted-foreground block mb-1">Stok Minimum</label>
                  <input type="number" min="0" value={form.min_stock} onChange={e=>setForm({...form,min_stock:e.target.value})}
                    className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-[var(--card-surface)]" />
                </div>
              </div>
              {/* FASE G+: harga satuan — dasar nilai selisih opname & jurnal keuangan */}
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Harga Satuan / HPP (Rp)</label>
                {editItem ? (
                  // 2026-11-06 (Tahap 1, K12): HPP item yang sudah ada hanya diubah lewat Set HPP
                  // (revaluasi berjurnal + alasan) — bukan ditimpa dari form ini.
                  <>
                    <div className="text-sm tabular-nums" data-testid="acc-unit-cost-readonly">{fmtRp(editItem.unit_cost)}</div>
                    <p className="text-[11px] text-muted-foreground mt-1">
                      HPP diubah lewat Set HPP di Valuasi HPP supaya perubahan nilai stok tercatat dengan jurnal dan alasannya.
                      {onOpenValuation && (
                        <> <Button variant="link" size="sm" className="px-0" onClick={() => { setShowForm(false); onOpenValuation(); }}
                          data-testid="acc-open-set-hpp">Buka Valuasi HPP</Button></>
                      )}
                    </p>
                  </>
                ) : (
                  <>
                    <MoneyInput unstyled value={form.unit_cost}
                      onChange={e=>setForm({...form,unit_cost:e.target.value})}
                      className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-[var(--card-surface)]"
                      placeholder="0" data-testid="acc-unit-cost-input" />
                    <p className="text-[11px] text-muted-foreground mt-1">Harga awal. Dipakai untuk menilai stok &amp; <strong>jurnal penyesuaian keuangan</strong> saat opname disetujui. Kosong/0 = selisih opname tidak masuk keuangan.</p>
                  </>
                )}
              </div>
              
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

              <div>
                <label className="text-xs text-muted-foreground block mb-1">Catatan</label>
                <textarea value={form.notes} onChange={e=>setForm({...form,notes:e.target.value})} rows="2"
                  className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-[var(--card-surface)] resize-none" />
              </div>
              {err && <div className="text-xs text-red-700 dark:text-red-400">{err}</div>}
            </div>
            <div className="flex gap-3 mt-5">
              <button onClick={()=>setShowForm(false)} className="flex-1 py-2 border border-border rounded-lg text-sm hover:bg-foreground/5">Batal</button>
              <button onClick={save} disabled={!form.name||saving} className="flex-1 py-2 bg-primary text-foreground rounded-lg text-sm hover:brightness-110 disabled:opacity-50" data-testid="save-acc-btn">
                {saving ? 'Menyimpan...' : 'Simpan'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Move Modal */}
      {showMove && (
        <div className="fixed inset-0 bg-foreground/40 z-50 flex items-center justify-center p-4" onClick={()=>setShowMove(null)}>
          <div className="bg-[var(--card-surface)] rounded-2xl shadow-xl w-full max-w-sm p-6" onClick={e=>e.stopPropagation()}>
            <h3 className="text-lg font-bold mb-1">
              {showMove.action === 'in' ? 'Terima Stok Masuk' : 'Keluarkan Stok'}
            </h3>
            <p className="text-sm text-muted-foreground mb-4">{showMove.name}</p>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Satuan Input</label>
                <UomSelect opt={moveUomOpt} value={moveUnit} fallbackUnit={showMove.unit}
                  onChange={e=>setMoveForm({...moveForm,input_unit:e.target.value})}
                  testId="move-uom-select" className="w-full" />
                {showMove.display_in_packs && showMove.pack_unit && (
                  <small className="text-[11px] text-muted-foreground">
                    1 {showMove.pack_unit} = {fmtNum(showMove.pack_size)} {showMove.unit}
                  </small>
                )}
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">
                  Jumlah ({moveUnit || showMove.unit}) *
                </label>
                <input type="number" min="0.0001" step="0.0001" value={moveForm.qty} onChange={e=>setMoveForm({...moveForm,qty:e.target.value})}
                  className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-[var(--card-surface)]" placeholder="0" data-testid="move-qty-input" />
                <UomConversionHint opt={moveUomOpt} qty={moveForm.qty} unit={moveUnit}
                  fallbackUnit={showMove.unit} testId="move-uom-hint" className="mt-1" />
              </div>
              {showMove.action === 'in' && (
                <div>
                  <label className="text-xs text-muted-foreground block mb-1">
                    Harga satuan beli (Rp) — per{' '}
                    <b className="text-foreground">{moveUnit || showMove.unit}</b>{' '}
                    — opsional
                  </label>
                  <MoneyInput unstyled decimals={2} value={moveForm.unit_cost}
                    onChange={e=>setMoveForm({...moveForm,unit_cost:e.target.value})}
                    className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-[var(--card-surface)]"
                    placeholder="kosongkan bila harga tidak berubah" data-testid="move-unit-cost-input" />
                  {moveUnit && moveBaseUnit && moveUnit !== moveBaseUnit && moveForm.unit_cost && (
                    <small className="block text-[11px] text-muted-foreground" data-testid="move-cost-conversion-hint">
                      = {fmtRp(Number(moveForm.unit_cost) / (toBaseQty(moveUomOpt, 1, moveUnit) || 1))} per {moveBaseUnit}
                    </small>
                  )}
                  <small className="text-[11px] text-muted-foreground">
                    Bila diisi, HPP master diperbarui dengan metode rata-rata bergerak dan jurnal persediaan dibuat otomatis.
                  </small>
                </div>
              )}
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Catatan</label>
                <input value={moveForm.notes} onChange={e=>setMoveForm({...moveForm,notes:e.target.value})}
                  className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-[var(--card-surface)]" placeholder="Keterangan..." />
              </div>
              {err && <div className="text-xs text-red-700 dark:text-red-400">{err}</div>}
            </div>
            <div className="flex gap-3 mt-5">
              <button onClick={()=>setShowMove(null)} className="flex-1 py-2 border border-border rounded-lg text-sm hover:bg-foreground/5">Batal</button>
              <button onClick={doMove} disabled={saving}
                className={`flex-1 py-2 text-foreground rounded-lg text-sm hover:brightness-110 disabled:opacity-50 ${showMove.action==='in'?'bg-emerald-600':'bg-amber-600'}`}
                data-testid="confirm-move-btn">
                {saving ? 'Memproses...' : showMove.action==='in' ? 'Terima' : 'Keluarkan'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── TAB 2: REQUEST INTERNAL ─────────────────────────────────────────────────
// ─── TAB 2: REQUEST INTERNAL ────────────────────────────────────────────────
// FASE 10 — DIPINDAH KE SSOT `dewi_accessory_requests` (request_type='internal_issuance').
// Sebelumnya tab ini memakai `/api/acc/internal-requests` yang menulis ke koleksi
// legacy `acc_internal_requests`. Akibat nyata: KPI "Request Pending" di dashboard
// (yang membaca SSOT) SELALU 0, inbox/approval SSOT tidak pernah melihat permintaan
// ini, dan koleksi legacy tidak bisa di-drop. Sekarang satu jalur saja:
//   buat → submitted · setujui → allocated · serahkan → delivered (POTONG STOK) ·
//   tolak → rejected.
// Label lama (Pending/Approved/Issued/Rejected) dipertahankan di layar supaya
// kebiasaan pengguna tidak berubah.
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

function RequestInternalTab({ token, items }) {
  const [requests, setReqs]   = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShow]   = useState(false);
  const [form, setForm]       = useState({ divisi:'', requester_name:'', purpose:'', needed_by:'', items:[] });
  const [lines, setLines]     = useState([{ acc_id:'', qty_requested:1, unit:'pcs', notes:'' }]);
  const [detail, setDetail]   = useState(null);
  const [saving, setSaving]   = useState(false);
  const [err, setErr]         = useState('');
  const [msg, setMsg]         = useState('');
  const [statusFilter, setStatusF] = useState('');
  // SESI #27 — kebijakan penomoran Permintaan Aksesoris. TIPE=INT-REQ (pengeluaran internal).
  const numPolicy = useDocNumberPolicy('dewi_accessory_requests.request_code', token,
                                       { TIPE: 'INT-REQ' });
  const [reqCode, setReqCode] = useState('');

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
    if (!form.divisi) { setErr('Divisi wajib dipilih'); return; }
    const validLines = lines.filter(l=>l.acc_id && l.qty_requested>0);
    if (validLines.length === 0) { setErr('Minimal 1 item'); return; }
    setSaving(true); setErr(''); setMsg('');
    try {
      const res = await api('POST', '/api/dewi/accessory-requests', token, {
        request_type: 'internal_issuance',
        status: 'submitted',
        ...docNumberPayload(numPolicy, 'request_code', reqCode),
        divisi: form.divisi,
        purpose: form.purpose,
        needed_by_date: form.needed_by,
        notes: form.requester_name ? `Pemohon: ${form.requester_name}` : '',
        items: validLines.map(l => ({
          material_id: l.acc_id, material_code: l.acc_code || '', material_name: l.acc_name || '',
          qty: Number(l.qty_requested) || 0, unit: l.unit || 'pcs', notes: l.notes || '',
        })),
      });
      setShow(false); setLines([{ acc_id:'', qty_requested:1, unit:'pcs', notes:'' }]);
      setForm({ divisi:'', requester_name:'', purpose:'', needed_by:'', items:[] });
      setMsg(`Request ${res.request_code || ''} dibuat & menunggu persetujuan.`);
      load();
    } catch(e) { setErr(e.message); }
    finally { setSaving(false); }
  };

  // Approve → allocate · Reject → reject · Issue → deliver (SSOT memotong stok + jurnal)
  const updateStatus = async (id, status, notes='') => {
    setErr(''); setMsg('');
    try {
      if (status === 'Approved') {
        await api('POST', `/api/dewi/accessory-requests/${id}/allocate`, token, { notes });
        setMsg('Request disetujui. Klik ikon “Serahkan” untuk mengeluarkan barang & memotong stok.');
      } else if (status === 'Rejected') {
        await api('POST', `/api/dewi/accessory-requests/${id}/reject`, token, { reason: notes || 'Ditolak admin aksesoris' });
        setMsg('Request ditolak. Stok tidak berubah.');
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

  // RC-UI-03: client-side pagination (10/page) for accessory requests
  const requestsPg = useClientPagination(requests, 10);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3 justify-between">
        <div className="flex items-center gap-2">
          <SmartNativeSelect value={statusFilter} onChange={e=>setStatusF(e.target.value)} className="border border-border rounded-lg px-3 py-2 bg-[var(--card-surface)] text-sm">
            <option value="">Semua Status</option>
            {['Pending','Approved','Rejected','Issued'].map(s=><option key={s} value={s}>{s}</option>)}
          </SmartNativeSelect>
          <button onClick={load} className="p-2 border border-border rounded-lg hover:bg-foreground/5"><RefreshCw className="w-4 h-4" /></button>
        </div>
        <button onClick={()=>{setShow(true);setErr('');}} className="flex items-center gap-2 px-4 py-2 bg-primary text-foreground rounded-lg text-sm font-medium hover:brightness-110" data-testid="add-int-req-btn">
          <Plus className="w-4 h-4" /> Buat Request
        </button>
      </div>

      {err && <div className="text-sm text-red-700 dark:text-red-400 bg-red-100 dark:bg-red-500/10 rounded-lg px-4 py-2" data-testid="acc-req-error">{err}</div>}
      {msg && (
        <div className="text-sm text-emerald-700 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-500/10 border border-emerald-300 dark:border-emerald-500/20 rounded-lg px-4 py-2"
          data-testid="acc-req-msg">{msg}</div>
      )}

      <div className="bg-[var(--card-surface)] rounded-xl border border-border overflow-x-auto">
        <table className="w-full text-sm min-w-[650px]">
          <thead className="bg-[var(--glass-bg)] border-b border-border">
            <tr>
              <th className="text-left px-4 py-3 text-muted-foreground font-medium">No. Request</th>
              <th className="text-left px-4 py-3 text-muted-foreground font-medium">Divisi</th>
              <th className="text-left px-4 py-3 text-muted-foreground font-medium">Pemohon</th>
              <th className="text-left px-4 py-3 text-muted-foreground font-medium">Keperluan</th>
              <th className="text-left px-4 py-3 text-muted-foreground font-medium">Tgl Butuh</th>
              <th className="text-center px-4 py-3 text-muted-foreground font-medium">Status</th>
              <th className="text-right px-4 py-3 text-muted-foreground font-medium">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {loading ? Array.from({ length: 5 }).map((_, i) => (
              <tr key={i}>{[...Array(7)].map((__, j) => <td key={j} className="px-3 py-2.5"><Skeleton className="h-4" /></td>)}</tr>
            )) : requests.length === 0 ? <tr><td colSpan="7"><EmptyState icon={FileText} title="Belum ada request internal" description="Request dari divisi akan muncul di sini." /></td></tr>
            : requestsPg.paged.map(r => (
              <tr key={r.id} className="border-b border-border hover:bg-foreground/[0.02]" data-testid={`req-row-${r.id}`}>
                <td className="px-4 py-3 font-mono text-xs">{r.request_number}</td>
                <td className="px-4 py-3">{r.divisi}</td>
                <td className="px-4 py-3 text-muted-foreground">{r.requester_name}</td>
                <td className="px-4 py-3 text-muted-foreground max-w-xs truncate">{r.purpose || '-'}</td>
                <td className="px-4 py-3 text-muted-foreground text-xs">{fmtDate(r.needed_by)}</td>
                <td className="px-4 py-3 text-center"><Badge status={r.status} /></td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-1">
                    <button onClick={()=>setDetail(r)} className="p-1 hover:bg-foreground/5 rounded" title="Detail" data-testid={`view-req-${r.id}`}>
                      <Eye className="w-4 h-4 text-muted-foreground" />
                    </button>
                    {r.status === 'Pending' && (
                      <>
                        <button onClick={()=>updateStatus(r.id,'Approved')} className="p-1 hover:bg-emerald-100 dark:bg-emerald-500/10 rounded" title="Setujui" data-testid={`approve-req-${r.id}`}>
                          <Check className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                        </button>
                        <button onClick={()=>updateStatus(r.id,'Rejected')} className="p-1 hover:bg-red-100 dark:bg-red-500/10 rounded" title="Tolak">
                          <XCircle className="w-4 h-4 text-red-700 dark:text-red-400" />
                        </button>
                      </>
                    )}
                    {r.status === 'Approved' && (
                      <button onClick={()=>updateStatus(r.id,'Issued')} className="p-1 hover:bg-sky-100 dark:bg-sky-500/10 rounded" title="Issue / Keluarkan" data-testid={`issue-req-${r.id}`}>
                        <ArrowDownCircle className="w-4 h-4 text-sky-600 dark:text-sky-400" />
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {requestsPg.total > 0 && <PaginationLite page={requestsPg.page} totalPages={requestsPg.totalPages} total={requestsPg.total} pageSize={requestsPg.pageSize} onPageChange={requestsPg.setPage} />}

      {/* Detail Panel */}
      {detail && (
        <div className="fixed inset-0 bg-foreground/40 z-50 flex items-center justify-center p-4" onClick={()=>setDetail(null)}>
          <div className="bg-[var(--card-surface)] rounded-2xl shadow-xl w-full max-w-lg p-6" onClick={e=>e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-bold">{detail.request_number}</h3>
              <Badge status={detail.status} />
            </div>
            <div className="grid grid-cols-2 gap-3 mb-4 text-sm">
              <div><span className="text-muted-foreground">Divisi:</span> <span className="font-medium ml-1">{detail.divisi}</span></div>
              <div><span className="text-muted-foreground">Pemohon:</span> <span className="font-medium ml-1">{detail.requester_name}</span></div>
              <div><span className="text-muted-foreground">Keperluan:</span> <span className="font-medium ml-1">{detail.purpose||'-'}</span></div>
              <div><span className="text-muted-foreground">Tgl Butuh:</span> <span className="font-medium ml-1">{fmtDate(detail.needed_by)}</span></div>
            </div>
            <p className="text-xs text-muted-foreground mb-2 font-medium uppercase tracking-wide">Item yang diminta:</p>
            <div className="space-y-1 mb-4">
              {(detail.items||[]).map((it,i)=>(
                <div key={i} className="flex items-center justify-between text-sm bg-foreground/[0.03] rounded-lg px-3 py-2">
                  <span>{it.acc_name || it.acc_id}</span>
                  <span className="font-medium">{it.qty_requested} {it.unit}</span>
                </div>
              ))}
            </div>
            {detail.admin_notes && <p className="text-xs text-muted-foreground">Catatan admin: {detail.admin_notes}</p>}
            <button onClick={()=>setDetail(null)} className="mt-4 w-full py-2 border border-border rounded-lg text-sm hover:bg-foreground/5">Tutup</button>
          </div>
        </div>
      )}

      {/* Create Form Modal */}
      {showForm && (
        <div className="fixed inset-0 bg-foreground/40 z-50 flex items-center justify-center p-4" onClick={()=>setShow(false)}>
          <div className="bg-[var(--card-surface)] rounded-2xl shadow-xl w-full max-w-lg p-6 max-h-[90vh] overflow-y-auto" onClick={e=>e.stopPropagation()}>
            <h3 className="text-lg font-bold mb-4">Buat Request Internal</h3>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-muted-foreground block mb-1">Divisi *</label>
                  <select value={form.divisi} onChange={e=>setForm({...form,divisi:e.target.value})} className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-[var(--card-surface)]" data-testid="req-divisi">
                    <option value="">Pilih...</option>
                    {DIVISI.map(d=><option key={d} value={d}>{d}</option>)}
                  </select>
                </div>
                <div>
                  <label className="text-xs text-muted-foreground block mb-1">Nama Pemohon</label>
                  <input value={form.requester_name} onChange={e=>setForm({...form,requester_name:e.target.value})} className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-[var(--card-surface)]" placeholder="Nama..." />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-muted-foreground block mb-1">Keperluan</label>
                  <input value={form.purpose} onChange={e=>setForm({...form,purpose:e.target.value})} className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-[var(--card-surface)]" placeholder="Untuk apa..." />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground block mb-1">Dibutuhkan Tgl</label>
                  <input type="date" value={form.needed_by} onChange={e=>setForm({...form,needed_by:e.target.value})} className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-[var(--card-surface)]" />
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-xs text-muted-foreground font-medium uppercase tracking-wide">Item yang Diminta</label>
                  <button onClick={addLine} className="text-xs text-primary flex items-center gap-1 hover:underline"><Plus className="w-3 h-3" /> Tambah</button>
                </div>
                {lines.map((ln,i) => (
                  <div key={i} className="flex items-center gap-2 mb-2">
                    <SmartNativeSelect value={ln.acc_id} onChange={e=>lineChange(i,e.target.value)} className="flex-1 border border-border rounded-lg px-2 py-1.5 text-xs bg-[var(--card-surface)]" data-testid={`req-item-${i}`}>
                      <option value="">Pilih item...</option>
                      {items.map(a=><option key={a.id} value={a.id}>{a.name} (stok: {a.stock_qty} {a.unit})</option>)}
                    </SmartNativeSelect>
                    <input type="number" min="1" value={ln.qty_requested} onChange={e=>updateLine(i,'qty_requested',+e.target.value)}
                      className="w-16 border border-border rounded-lg px-2 py-1.5 text-xs bg-[var(--card-surface)]" placeholder="Qty" />
                    <span className="text-xs text-muted-foreground w-8">{ln.unit}</span>
                    {lines.length > 1 && <button onClick={()=>removeLine(i)}><X className="w-4 h-4 text-muted-foreground hover:text-red-700 dark:text-red-400" /></button>}
                  </div>
                ))}
              </div>
              {err && <div className="text-xs text-red-700 dark:text-red-400">{err}</div>}

              <DocNumberField
                policy={numPolicy} value={reqCode} onChange={setReqCode}
                testId="int-req-docnum" label="Nomor Permintaan" />
            </div>
            <div className="flex gap-3 mt-5">
              <button onClick={()=>setShow(false)} className="flex-1 py-2 border border-border rounded-lg text-sm hover:bg-foreground/5">Batal</button>
              <button onClick={submit} disabled={saving} className="flex-1 py-2 bg-primary text-foreground rounded-lg text-sm hover:brightness-110 disabled:opacity-50" data-testid="submit-int-req-btn">
                {saving ? 'Mengirim...' : 'Kirim Request'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
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
    <div className="max-w-2xl mx-auto text-center py-10 space-y-4" data-testid="acc-loans-moved">
      <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-amber-100 dark:bg-amber-500/10">
        <RotateCcw className="w-7 h-7 text-amber-700 dark:text-amber-400" />
      </div>
      <h3 className="text-lg font-bold">Peminjaman pindah ke Manajemen Aset</h3>
      <p className="text-sm text-muted-foreground">
        Yang dipinjam-kembalikan adalah <strong>unit aset ber-nomor</strong> (mesin, alat,
        gunting, dsb), bukan stok aksesoris habis pakai. Karena itu seluruh peminjaman kini
        dicatat di <strong>Manajemen Aset → Peminjaman Alat</strong>, lengkap dengan jadwal
        kembali dan riwayat kondisi barang.
      </p>
      <p className="text-xs text-muted-foreground">
        Data pinjaman aksesoris lama sudah ditutup dan stoknya dikembalikan ke gudang
        (migrasi FASE 10). Aksesoris habis pakai tetap lewat jalur
        <strong> Request Internal → Persetujuan → Serahkan</strong>.
      </p>
      <div className="flex items-center justify-center gap-3 pt-2">
        <button onClick={onBack}
          className="px-4 py-2 border border-border rounded-lg text-sm hover:bg-foreground/5"
          data-testid="acc-loans-back">
          Kembali ke Master &amp; Stok
        </button>
        {onNavigate && (
          <button onClick={() => onNavigate('asset-loans')}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-amber-500 text-white hover:brightness-110"
            data-testid="acc-loans-open-asset-loans">
            Buka Peminjaman Alat →
          </button>
        )}
      </div>
    </div>
  );
}

// ─── TAB 5: PURCHASE REQUEST ─────────────────────────────────────────────────
function PurchaseRequestTab({ token, items }) {
  const [prs, setPRs]         = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShow]   = useState(false);
  const [form, setForm]       = useState({ priority:'Normal', purpose:'', supplier:'', notes:'', items:[] });
  const [lines, setLines]     = useState([{ acc_id:'', qty_requested:1, unit:'pcs', estimated_price:0, notes:'' }]);
  const [filter, setFilter]   = useState('');
  const [saving, setSaving]   = useState(false);
  const [err, setErr]         = useState('');
  // SESI #27 — nomor PR aksesoris mengikuti kebijakan Otomatis/Manual milik owner.
  const numPolicy = useDocNumberPolicy('acc_purchase_requests.pr_number', token);
  const [prNumber, setPrNumber] = useState('');

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
    if (!validLines.length) { setErr('Minimal 1 item'); return; }
    setSaving(true); setErr('');
    try {
      await api('POST', '/api/acc/purchase-requests', token,
                { ...form, items: validLines,
                  ...docNumberPayload(numPolicy, 'pr_number', prNumber) });
      setShow(false); setLines([{acc_id:'',qty_requested:1,unit:'pcs',estimated_price:0,notes:''}]);
      setForm({ priority:'Normal', purpose:'', supplier:'', notes:'', items:[] });
      load();
    } catch(e) { setErr(e.message); }
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
  const act = async (id, action, body = {}) => {
    setErr('');
    try { await api('POST', `/api/acc/purchase-requests/${id}/${action}`, token, body); load(); }
    catch(e) { setErr(e.message); }
  };

  const doReject = async (pr) => {
    const reason = window.prompt(
      `Alasan menolak ${pr.pr_number}? (wajib diisi agar pemohon tahu apa yang harus diperbaiki)`);
    if (reason === null) return;
    if (!reason.trim()) { setErr('Alasan penolakan wajib diisi.'); return; }
    await act(pr.id, 'reject', { reason });
  };

  const updateStatus = async (id, status, notes='') => {
    setErr('');
    try { await api('PUT', `/api/acc/purchase-requests/${id}`, token, { status, finance_notes: notes }); load(); }
    catch(e) { setErr(e.message); }
  };

  const totalEst = lines.reduce((s,l)=>s + (parseFloat(l.qty_requested)||0)*(parseFloat(l.estimated_price)||0), 0);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3 justify-between">
        <div className="flex items-center gap-2">
          <SmartNativeSelect value={filter} onChange={e=>setFilter(e.target.value)} className="border border-border rounded-lg px-3 py-2 bg-[var(--card-surface)] text-sm">
            <option value="">Semua Status</option>
            {['Draft','Submitted','Approved','Rejected','Ordered','Received'].map(s=><option key={s} value={s}>{s}</option>)}
          </SmartNativeSelect>
          <button onClick={load} className="p-2 border border-border rounded-lg hover:bg-foreground/5"><RefreshCw className="w-4 h-4" /></button>
        </div>
        <button onClick={()=>{setShow(true);setErr('');}} className="flex items-center gap-2 px-4 py-2 bg-primary text-foreground rounded-lg text-sm font-medium hover:brightness-110" data-testid="add-pr-btn">
          <Plus className="w-4 h-4" /> Buat Purchase Request
        </button>
      </div>

      {err && <div className="text-sm text-red-700 dark:text-red-400 bg-red-100 dark:bg-red-500/10 rounded-lg px-4 py-2">{err}</div>}

      <div className="bg-[var(--card-surface)] rounded-xl border border-border overflow-x-auto">
        <table className="w-full text-sm min-w-[700px]">
          <thead className="bg-[var(--glass-bg)] border-b border-border">
            <tr>
              <th className="text-left px-4 py-3 text-muted-foreground font-medium">No. PR</th>
              <th className="text-left px-4 py-3 text-muted-foreground font-medium">Keperluan</th>
              <th className="text-left px-4 py-3 text-muted-foreground font-medium">Supplier</th>
              <th className="text-center px-4 py-3 text-muted-foreground font-medium">Prioritas</th>
              <th className="text-right px-4 py-3 text-muted-foreground font-medium">Est. Total</th>
              <th className="text-center px-4 py-3 text-muted-foreground font-medium">Status</th>
              <th className="text-right px-4 py-3 text-muted-foreground font-medium">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {loading ? Array.from({ length: 5 }).map((_, i) => (
              <tr key={i}>{[...Array(7)].map((__, j) => <td key={j} className="px-3 py-2.5"><Skeleton className="h-4" /></td>)}</tr>
            )) : prs.length === 0 ? <tr><td colSpan="7"><EmptyState icon={ShoppingCart} title="Belum ada purchase request" description="Buat PR baru untuk mengajukan pengadaan aksesoris ke Finance." /></td></tr>
            : prs.map(pr => (
              <tr key={pr.id} className="border-b border-border hover:bg-foreground/[0.02]" data-testid={`pr-row-${pr.id}`}>
                <td className="px-4 py-3 font-mono text-xs">{pr.pr_number}</td>
                <td className="px-4 py-3 max-w-xs truncate">{pr.purpose||'-'}</td>
                <td className="px-4 py-3 text-muted-foreground">{pr.supplier||'-'}</td>
                <td className="px-4 py-3 text-center">
                  <span className={`px-2 py-0.5 rounded-full text-xs ${pr.priority==='Urgent'?'bg-red-100 dark:bg-red-500/10 text-red-700 dark:text-red-400':pr.priority==='Low'?'bg-muted dark:bg-slate-500/10 text-muted-foreground':'bg-sky-100 dark:bg-sky-500/10 text-sky-600 dark:text-sky-400'}`}>
                    {pr.priority}
                  </span>
                </td>
                <td className="px-4 py-3 text-right font-medium">Rp {fmtNum(pr.total_estimated)}</td>
                <td className="px-4 py-3 text-center">
                  <Badge status={pr.status} />
                  {pr.status === 'Submitted' && pr.stage_label && (
                    <div className="mt-1 text-[10px] text-muted-foreground" data-testid={`pr-stage-${pr.id}`}>
                      {pr.stage_label}{pr.total_stages ? ` (${pr.stage_order}/${pr.total_stages})` : ''}
                    </div>
                  )}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-1">
                    {pr.status === 'Draft' && pr.can_submit !== false && (
                      <button onClick={()=>act(pr.id,'submit')} className="px-2 py-1 bg-sky-600/10 text-sky-600 dark:text-sky-400 rounded text-xs hover:bg-sky-600/20" data-testid={`submit-pr-${pr.id}`}>Ajukan</button>
                    )}
                    {pr.status === 'Submitted' && pr.can_approve && (
                      <>
                        <button onClick={()=>act(pr.id,'approve')} className="px-2 py-1 bg-emerald-600/10 text-emerald-600 dark:text-emerald-400 rounded text-xs hover:bg-emerald-600/20" data-testid={`approve-pr-${pr.id}`} title={pr.stage_label ? `Setujui — ${pr.stage_label}` : 'Setujui'}>Setujui</button>
                        <button onClick={()=>doReject(pr)} className="px-2 py-1 bg-red-600/10 text-red-700 dark:text-red-400 rounded text-xs hover:bg-red-600/20" data-testid={`reject-pr-${pr.id}`}>Tolak</button>
                      </>
                    )}
                    {pr.status === 'Submitted' && !pr.can_approve && (
                      <span className="max-w-[260px] text-[10px] leading-snug text-muted-foreground text-right" data-testid={`pr-blocked-${pr.id}`}>
                        {pr.blocked_reason || 'Menunggu approver yang berhak.'}
                      </span>
                    )}
                    {pr.status === 'Approved' && (
                      <button onClick={()=>updateStatus(pr.id,'Ordered')} className="px-2 py-1 bg-violet-600/10 text-violet-600 dark:text-violet-400 rounded text-xs hover:bg-violet-600/20" data-testid={`order-pr-${pr.id}`}>Order</button>
                    )}
                    {pr.status === 'Ordered' && (
                      <button onClick={()=>updateStatus(pr.id,'Received')} className="px-2 py-1 bg-emerald-600/10 text-emerald-600 dark:text-emerald-400 rounded text-xs hover:bg-emerald-600/20" data-testid={`receive-pr-${pr.id}`}>Terima Barang</button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Create PR Modal */}
      {showForm && (
        <div className="fixed inset-0 bg-foreground/40 z-50 flex items-center justify-center p-4" onClick={()=>setShow(false)}>
          <div className="bg-[var(--card-surface)] rounded-2xl shadow-xl w-full max-w-xl p-6 max-h-[90vh] overflow-y-auto" onClick={e=>e.stopPropagation()}>
            <h3 className="text-lg font-bold mb-4">Buat Purchase Request</h3>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-muted-foreground block mb-1">Prioritas</label>
                  <SmartNativeSelect value={form.priority} onChange={e=>setForm({...form,priority:e.target.value})} className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-[var(--card-surface)]" data-testid="pr-priority">
                    {['Urgent','Normal','Low'].map(p=><option key={p} value={p}>{p}</option>)}
                  </SmartNativeSelect>
                </div>
                <div>
                  <label className="text-xs text-muted-foreground block mb-1">Supplier</label>
                  <input value={form.supplier} onChange={e=>setForm({...form,supplier:e.target.value})} className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-[var(--card-surface)]" placeholder="Nama supplier..." />
                </div>
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Keperluan / Alasan</label>
                <input value={form.purpose} onChange={e=>setForm({...form,purpose:e.target.value})} className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-[var(--card-surface)]" placeholder="Stok habis, urgent untuk order WO-XXX..." data-testid="pr-purpose" />
              </div>
              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-xs text-muted-foreground font-medium uppercase tracking-wide">Item yang Dipesan</label>
                  <button onClick={addLine} className="text-xs text-primary flex items-center gap-1 hover:underline"><Plus className="w-3 h-3" />Tambah</button>
                </div>
                {lines.map((ln,i)=>(
                  <div key={i} className="flex items-center gap-2 mb-2">
                    <SmartNativeSelect value={ln.acc_id} onChange={e=>lineChange(i,e.target.value)} className="flex-1 border border-border rounded-lg px-2 py-1.5 text-xs bg-[var(--card-surface)]">
                      <option value="">Pilih item...</option>
                      {items.map(a=><option key={a.id} value={a.id}>{a.name} (stok: {a.stock_qty} {a.unit})</option>)}
                    </SmartNativeSelect>
                    <input type="number" min="1" value={ln.qty_requested} onChange={e=>updateLine(i,'qty_requested',+e.target.value)} className="w-14 border border-border rounded-lg px-2 py-1.5 text-xs bg-[var(--card-surface)]" placeholder="Qty" />
                    <span className="text-xs text-muted-foreground">{ln.unit}</span>
                    <MoneyInput unstyled value={ln.estimated_price} onChange={e=>updateLine(i,'estimated_price',+e.target.value)} className="w-24 border border-border rounded-lg px-2 py-1.5 text-xs bg-[var(--card-surface)]" placeholder="Harga Est." />
                    {lines.length>1 && <button onClick={()=>removeLine(i)}><X className="w-4 h-4 text-muted-foreground" /></button>}
                  </div>
                ))}
                <div className="text-right text-sm font-medium text-primary mt-1">Est. Total: Rp {fmtNum(totalEst)}</div>
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Catatan</label>
                <textarea value={form.notes} onChange={e=>setForm({...form,notes:e.target.value})} rows="2" className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-[var(--card-surface)] resize-none" />
              </div>
              {err && <div className="text-xs text-red-700 dark:text-red-400">{err}</div>}

              <DocNumberField
                policy={numPolicy} value={prNumber} onChange={setPrNumber}
                testId="pr-docnum" label="Nomor Permintaan Beli" />
            </div>
            <div className="flex gap-3 mt-5">
              <button onClick={()=>setShow(false)} className="flex-1 py-2 border border-border rounded-lg text-sm hover:bg-foreground/5">Batal</button>
              <button onClick={submit} disabled={saving} className="flex-1 py-2 bg-primary text-foreground rounded-lg text-sm hover:brightness-110 disabled:opacity-50" data-testid="save-pr-btn">
                {saving?'Menyimpan...':'Simpan Draft'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
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

  // FASE 10 — tab "Peminjaman" DILEPAS. Peminjaman alat/aset sudah pindah ke
  // Manajemen Aset → Peminjaman Alat sejak ACC-3; tab ini hanya membaca koleksi
  // legacy `acc_loans` yang kini sudah ditutup & di-drop. Deep-link lama
  // (`?tab=pinjam`) tetap ditangani: lihat `LEGACY_TAB_REDIRECT` di bawah.
  const ALL_TABS = [
    { id:'master',   label:'Master & Stok',     icon: Package },
    { id:'internal', label:'Request Internal',  icon: FileText },
    { id:'opname',   label:'Stok Opname',       icon: ClipboardCheck },
    { id:'pr',       label:'Purchase Request',  icon: ShoppingCart },
    { id:'valuasi',  label:'Valuasi HPP',       icon: Banknote },
  ];
  const TABS = Array.isArray(allowedTabs) && allowedTabs.length
    ? ALL_TABS.filter(t => allowedTabs.includes(t.id))
    : ALL_TABS;
  const scoped = TABS.length !== ALL_TABS.length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold">{headerTitle || 'Manajemen Aksesoris'}</h1>
        <p className="text-muted-foreground text-sm mt-1">
          {headerSubtitle || 'Master, stok, request internal, purchase request, dan valuasi aksesoris produksi'}
        </p>
      </div>

      {/* Dashboard Summary */}
      {dash && !scoped && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          {[
            { label:'Total Item', val: dash.total_items, color:'violet', icon: Package },
            { label:'Stok Habis', val: dash.out_of_stock, color:'red', icon: TrendingDown },
            { label:'Stok Rendah', val: dash.low_stock, color:'amber', icon: AlertTriangle },
            { label:'Request Pending', val: dash.pending_requests, color:'sky', icon: Clock },
            // FASE 8 — KPI valuasi menggantikan kartu "Dipinjam" (sisa domain lama:
            // peminjaman aksesoris sudah pindah ke Portal Aset sejak ACC-3, nilainya selalu 0).
            { label:'Nilai Persediaan', val: fmtRp(dash.total_stock_value), color:'emerald', icon: Banknote },
            { label:'Belum Dinilai', val: dash.unvalued_items ?? 0, color:'orange', icon: Info },
            { label:'PR Pending', val: dash.pending_pr, color:'emerald', icon: ShoppingCart },
          ].map(s=>(
            <div key={s.label} className={`border rounded-xl p-3 ${tone(s.color).surface}`}>
              <div className="flex items-center gap-1.5 mb-1">
                <s.icon className={`w-3.5 h-3.5 ${tone(s.color).text}`} />
                <span className="text-xs text-muted-foreground">{s.label}</span>
              </div>
              <div className={`text-xl font-bold ${tone(s.color).text}`}>{s.val}</div>
            </div>
          ))}
        </div>
      )}

      {/* Low Stock Alerts — tetap ditampilkan di pintu pengadaan: justru pemicu pembelian */}
      {dash?.low_stock_items?.length > 0 && (
        <div className="bg-amber-100 dark:bg-amber-500/5 border border-amber-300 dark:border-amber-500/20 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle className="w-4 h-4 text-amber-700 dark:text-amber-400" />
            <span className="text-sm font-medium text-amber-700 dark:text-amber-400">Stok Rendah — Perlu Purchase Request</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {dash.low_stock_items.map(it=>(
              <span key={it.id} className="px-3 py-1 bg-amber-100 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 rounded-full text-xs">
                {it.name}: {fmtNum(it.stock_qty)}/{fmtNum(it.min_stock)} {it.unit}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Tabs — disembunyikan bila pintu ini memang hanya punya satu tab */}
      <div className={`flex items-center gap-1 border-b border-border overflow-x-auto pb-0 ${TABS.length < 2 ? 'hidden' : ''}`}>
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            data-testid={`acc-tab-${t.id}`}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition whitespace-nowrap -mb-px ${
              tab === t.id
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}>
            <t.icon className="w-4 h-4" />
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div>
        {tab === 'master'   && <MasterTab token={token} onRefreshDash={() => { loadDash(); loadItems(); }}
          onOpenValuation={TABS.some(t => t.id === 'valuasi') ? () => setTab('valuasi') : null} />}
        {tab === 'internal' && <RequestInternalTab token={token} items={items} />}
        {tab === 'opname'   && <StokOpnameTab token={token} />}
        {/* FASE 10 — tautan lama `?tab=pinjam` tidak boleh buntu: tampilkan penunjuk arah
            (bukan halaman kosong) ke tempat yang benar. */}
        {tab === 'pinjam'   && <LegacyLoanRedirect onNavigate={onNavigate} onBack={() => setTab('master')} />}
        {tab === 'pr'       && <PurchaseRequestTab token={token} items={items} />}
        {tab === 'valuasi'  && <AccessoryValuationTab token={token} onRefreshDash={() => { loadDash(); loadItems(); }} />}
      </div>
    </div>
  );
}

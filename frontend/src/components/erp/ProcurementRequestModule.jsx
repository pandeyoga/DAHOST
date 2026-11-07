/**
 * ProcurementRequestModule — Pengadaan Barang/Jasa (Purchase Requests)
 * CV. Dewi Aditya — P1.C Procure-to-Pay
 *
 * Backend: /api/procurement/*
 * Flows: Draft → Submit → Approve/Reject → Complete
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout; tab buatan → pil penyaring satu baris; kartu angka StatTile
 * berketerangan; form buat PR & buat PO = FormPopup; detail = popup; daftar = tabel (kartu ringkas di HP), unduh
 * Excel/CSV SEMUA baris hasil saringan (dulu hanya 15 baris halaman yang tampil). Data & alur tidak berubah.
 */
import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import axios from 'axios';
import {
  Plus, RefreshCw, ChevronRight, ChevronDown, Search, AlertTriangle,
  CheckCircle2, XCircle, Clock, ShoppingCart, FileText,
  Send, Trash2, History, ShieldAlert, Info,
  Check, Circle, Layers, Loader2, Package, ArrowUpDown, X,
} from 'lucide-react';
import { formatDateID, formatRupiah } from '@/lib/format';
import { materialOptionLabel } from '@/lib/materialFields';
import { MoneyInput } from '@/components/ui/money-input';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import FilterChips from '@/components/ui/filter-chips';
import ViewToggle from '@/components/ui/view-toggle';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import DatePicker from '@/components/ui/date-picker';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import PaginationLite from '@/components/ui/pagination-lite';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';
import DocNumberField, { useDocNumberPolicy, docNumberPayload } from './docnum/DocNumberField';
import { DepartmentSelect } from './hr/hrPickers';

const API = process.env.REACT_APP_BACKEND_URL;

// F13-B (sesi #12) — pengalih Tabel/Kartu yang DIINGAT.
// PR adalah komitmen UANG: "PR mana yang paling besar & menunggu siapa" harus
// bisa dijawab tanpa menggulir, dan bisa dibawa ke rapat sebagai berkas.
const PR_VIEW_KEY = 'procurement_pr_view';
const PAGE_SIZE = 15;

// Label pendek tiap tahap untuk stepper ringkas di daftar.
// Label panjangnya datang dari server (`chain[].label`) — SATU sumber kebenaran.
const STAGE_SHORT = { dept: 'Dept', finance: 'Keuangan', final: 'Final' };

/** Tanggal + jam ringkas (id-ID). Aman untuk nilai kosong / rusak. */
function fmtDT(v) {
  if (!v) return '-';
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return '-';
  return d.toLocaleString('id-ID', {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Jakarta',
  });
}
const fmtTgl = (v) => (v ? formatDateID(v) : '—');

const PRIORITY_CFG = {
  low:    { label: 'Rendah',   tone: 'muted' },
  medium: { label: 'Sedang',   tone: 'info' },
  high:   { label: 'Tinggi',   tone: 'warning' },
  urgent: { label: 'Mendesak', tone: 'danger' },
};

const STATUS_CFG = {
  draft:            { label: 'Draf',                          tone: 'muted' },
  submitted:        { label: 'Menunggu persetujuan dept',     tone: 'warning' },
  dept_approved:    { label: 'Menunggu persetujuan keuangan', tone: 'warning' },
  finance_approved: { label: 'Menunggu persetujuan final',    tone: 'warning' },
  approved:         { label: 'Disetujui',                     tone: 'success' },
  in_procurement:   { label: 'Sedang pengadaan',              tone: 'info' },
  rejected:         { label: 'Ditolak',                       tone: 'danger' },
  completed:        { label: 'Selesai',                       tone: 'success' },
  cancelled:        { label: 'Dibatalkan',                    tone: 'muted' },
};

const TYPE_LABELS = {
  asset: 'Aset tetap', consumable: 'Barang habis pakai',
  service: 'Jasa', subscription: 'Langganan / SaaS',
  maintenance: 'Kontrak pemeliharaan', rental: 'Sewa alat/fasilitas',
  project: 'Berbasis proyek', other: 'Lainnya',
};

const fmtRp = formatRupiah;

function PRStatusBadge({ status }) {
  const c = STATUS_CFG[status] || { label: status || '—', tone: 'default' };
  return <StatusBadge status={status} label={c.label} tone={c.tone} />;
}

function PriorityBadge({ priority }) {
  const c = PRIORITY_CFG[priority] || PRIORITY_CFG.medium;
  return <StatusBadge status={priority} label={c.label} tone={c.tone} />;
}

/** Penanda jenis dokumen di kotak persetujuan gabungan (PR, PR aksesoris, PO). */
function KindBadges({ it }) {
  return (
    <>
      {it.kind === 'acc_pr' && <StatusBadge status="acc_pr" label={<><Package className="h-3 w-3" />Aksesoris</>} tone="primary" />}
      {/* 2026-08-07 — Purchase Order ikut ke kotak persetujuan gabungan.
          PO adalah KOMITMEN UANG ke supplier, jadi harus mudah dikenali. */}
      {it.kind === 'po' && <StatusBadge status="po" label={<><ShoppingCart className="h-3 w-3" />Purchase Order</>} tone="info" />}
      {it.exceeds_pr_value && <StatusBadge status="exceeds" label="Melebihi nilai PR" tone="danger" />}
    </>
  );
}

// ── Form buat PR (popup standar) ─────────────────────────────────────────────
function CreatePRModal({ onClose, onCreated, token }) {
  const [form, setForm] = useState({
    title: '', description: '', justification: '',
    priority: 'medium', request_type: 'consumable', department: '',
    request_number: '',
  });
  // SESI #19 — kebijakan penomoran PR (Otomatis/Manual) dibaca dari Administrasi
  // Sistem → Penomoran Dokumen. Tanpa ini, setelan MANUAL membuat PR tidak bisa
  // dibuat (backend menolak "nomor wajib diisi" atas setelan yang tak terlihat).
  const numPolicy = useDocNumberPolicy('dewi_procurement_requests.request_number', token);
  const [items, setItems] = useState([{ material_id: '', name: '', specification: '', qty: 1, unit: 'pcs', estimated_price: 0, notes: '' }]);
  const [materials, setMaterials] = useState([]);
  const [uomMap, setUomMap] = useState({});
  const [saving, setSaving] = useState(false);
  const [error, setError]   = useState('');
  const [requestTypes, setRequestTypes] = useState(Object.entries(TYPE_LABELS).map(([value, label]) => ({ value, label })));

  // Fetch request types dari API (Phase 5B)
  useEffect(() => {
    const fetchTypes = async () => {
      try {
        const res = await fetch(`${API}/api/procurement/request-types`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.ok) {
          const data = await res.json();
          if (data.items?.length > 0) {
            setRequestTypes(data.items);
          }
        }
      } catch {
        // fallback ke TYPE_LABELS jika fetch gagal
      }
    };
    fetchTypes();
  }, [token]);

  // Master material + daftar satuan sah (Portal Pengadaan 2026-08-06):
  // item PR kini boleh menunjuk material master supaya PO hasilnya bisa masuk
  // stok kanonik, dan satuan beli dikonversi otomatis ke satuan dasar.
  useEffect(() => {
    const h = { Authorization: `Bearer ${token}` };
    // 2026-11-07 (Tahap 6 PG1): barang jadi tidak dibeli → tidak dimuat ke pilihan material PR
    fetch(`${API}/api/rahaza/materials?exclude_type=fg`, { headers: h })
      .then((r) => (r.ok ? r.json() : []))
      .then((m) => setMaterials((Array.isArray(m) ? m : m?.items || []).filter((x) => x.active !== false)))
      .catch(() => {});
  }, [token]);

  const loadUom = async (materialId) => {
    if (!materialId || uomMap[materialId]) return uomMap[materialId];
    try {
      const r = await fetch(`${API}/api/rahaza/materials/uom-options?material_ids=${materialId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!r.ok) return null;
      const d = await r.json();
      const o = (d?.options || {})[materialId] || null;
      if (o) setUomMap((p) => ({ ...p, [materialId]: o }));
      return o;
    } catch { return null; }
  };

  const pickMaterial = async (i, materialId) => {
    const mat = materials.find((m) => m.id === materialId);
    // 2026-11-07 (Tahap 5): nama item ikut material baru bila nama itu dulu terisi otomatis dari material
    // sebelumnya (dulu tetap nama material LAMA saat material diganti → PR berisi nama ≠ barang).
    const prevMat = materials.find((m) => m.id === items[i]?.material_id);
    const autoName = (nm) => !nm?.trim() || (prevMat && nm.trim() === (prevMat.name || '').trim());
    setItem(i, 'material_id', materialId);
    if (!materialId) return;
    const opt = await loadUom(materialId);
    setItems((p) => p.map((it, idx) => (idx === i ? {
      ...it,
      material_id: materialId,
      name: autoName(it.name) ? (mat?.name || '') : it.name,
      unit: opt?.base_unit || mat?.unit || it.unit,
    } : it)));
    // Saran harga dari daftar harga supplier (harga per satuan beli)
    try {
      const r = await fetch(`${API}/api/procurement/price-lookup?material_id=${materialId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (r.ok) {
        const d = await r.json();
        if (d?.best?.price) {
          setItems((p) => p.map((it, idx) => (idx === i ? {
            ...it, unit: d.best.uom || it.unit, estimated_price: Number(d.best.price),
          } : it)));
        }
      }
    } catch { /* saran harga opsional */ }
  };

  const addItem = () => setItems(p => [...p, { material_id: '', name: '', specification: '', qty: 1, unit: 'pcs', estimated_price: 0, notes: '' }]);
  const rmItem  = (i) => setItems(p => p.filter((_, idx) => idx !== i));
  const setItem = (i, k, v) => setItems(p => p.map((it, idx) => idx === i ? { ...it, [k]: v } : it));

  const factorOf = (it) => {
    const opt = uomMap[it.material_id];
    if (!opt || !it.unit || it.unit === opt.base_unit) return 1;
    const row = (opt.units || []).find((u) => u.unit === it.unit);
    return row ? Number(row.factor_to_base) : 1;
  };

  const totalEst = items.reduce((s, it) => s + Number(it.qty||0) * Number(it.estimated_price||0), 0);

  const submit = async () => {
    if (!form.title.trim()) return setError('Judul wajib diisi');
    // 2026-11-07 (Tahap 5): periksa SEMUA baris. Dulu hanya baris pertama; baris tanpa nama dibuang diam-diam
    // oleh server dan qty 0 tersimpan sebagai 1.
    const filled = items.filter((it) => it.material_id || (it.name || '').trim());
    if (filled.length === 0) return setError('Minimal 1 item harus diisi');
    const noName = filled.findIndex((it) => !(it.name || '').trim());
    if (noName >= 0) return setError(`Nama item baris ${items.indexOf(filled[noName]) + 1} wajib diisi`);
    const noQty = filled.findIndex((it) => !(Number(it.qty) > 0));
    if (noQty >= 0) return setError(`Qty item "${filled[noQty].name}" harus lebih dari 0`);
    if (numPolicy?.mode === 'manual' && !form.request_number.trim()) {
      return setError(`Nomor PR wajib diisi (pola ${numPolicy.format}).`);
    }
    setSaving(true); setError('');
    try {
      const { request_number: _rn, ...rest } = form;
      await axios.post(`${API}/api/procurement/requests`, {
        ...rest,
        ...docNumberPayload(numPolicy, 'request_number', form.request_number),
        items: filled.map((it) => ({
          material_id: it.material_id || undefined,
          name: it.name,
          specification: it.specification,
          qty: Number(it.qty) || 0,
          uom: it.unit,
          estimated_price: Number(it.estimated_price) || 0,
          notes: it.notes,
        })),
      }, { headers: { Authorization: `Bearer ${token}` } });
      onCreated();
    } catch (e) {
      setError(e.response?.data?.detail || 'Gagal membuat PR');
    } finally { setSaving(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" testId="pr-create-form"
      judul="Buat permintaan pengadaan"
      keterangan="Disimpan sebagai draf. Ajukan ke approver dari detail permintaan."
      onSimpan={submit} menyimpan={saving} galat={error} labelSimpan="Simpan draf">
      <DocNumberField
        policy={numPolicy}
        value={form.request_number}
        onChange={(v) => setForm(p => ({ ...p, request_number: v }))}
        label="Nomor PR"
        testId="pr-number"
      />
      <Isian label="Judul permintaan" wajib htmlFor="pr-form-title">
        <Input id="pr-form-title" placeholder="mis. Pembelian laptop karyawan baru" value={form.title}
          onChange={e => setForm(p => ({ ...p, title: e.target.value }))} data-testid="pr-form-title" />
      </Isian>
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Tipe pengadaan">
          <SmartNativeSelect value={form.request_type} onChange={e => setForm(p => ({ ...p, request_type: e.target.value }))} data-testid="pr-form-type">
            {requestTypes.map(rt => <option key={rt.value} value={rt.value}>{rt.label}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Prioritas">
          <SmartNativeSelect value={form.priority} onChange={e => setForm(p => ({ ...p, priority: e.target.value }))} data-testid="pr-form-priority">
            {Object.entries(PRIORITY_CFG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </SmartNativeSelect>
        </Isian>
      </div>
      <Isian label="Departemen" petunjuk="Dari struktur organisasi; bawaan = departemen Anda.">
        {/* 2026-11-07 (OR1): dari Struktur Organisasi; bawaan = departemen karyawan pemohon */}
        <DepartmentSelect token={token} value={form.department} defaultToMine testId="pr-form-department"
          className="w-full h-9" onChange={v => setForm(p => ({ ...p, department: v }))} />
      </Isian>
      <Isian label="Justifikasi / alasan" htmlFor="pr-form-justification">
        <Textarea id="pr-form-justification" rows={2} placeholder="Jelaskan mengapa pengadaan ini diperlukan"
          value={form.justification} onChange={e => setForm(p => ({ ...p, justification: e.target.value }))} />
      </Isian>

      <div className="space-y-2 border-t border-[var(--glass-border)] pt-4">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-semibold text-foreground">Item ({items.length})</p>
          <Button type="button" size="sm" variant="outline" onClick={addItem} data-testid="pr-item-add">
            <Plus />Tambah item
          </Button>
        </div>
        {items.map((it, i) => {
          const opt = uomMap[it.material_id];
          const f = factorOf(it);
          const qtyBase = (Number(it.qty) || 0) * f;
          return (
            <div key={i} className="space-y-2 rounded-lg border border-[var(--glass-border)] p-3">
              <div className="flex gap-2">
                <div className="min-w-0 flex-1">
                  <SmartNativeSelect
                    value={it.material_id}
                    onChange={e => pickMaterial(i, e.target.value)}
                    data-testid={`pr-item-material-${i}`}
                  >
                    <option value="">Item bebas / non-master</option>
                    {materials.map(m => (
                      <option key={m.id} value={m.id}>{materialOptionLabel(m)}</option>
                    ))}
                  </SmartNativeSelect>
                </div>
                {items.length > 1 && (
                  <Button type="button" variant="ghost" size="icon" onClick={() => rmItem(i)}
                    title="Hapus item" aria-label="Hapus item" data-testid={`pr-item-remove-${i}`}>
                    <Trash2 className="text-[hsl(var(--danger-text))]" />
                  </Button>
                )}
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                <Input placeholder="Nama item *" aria-label="Nama item" value={it.name}
                  onChange={e => setItem(i, 'name', e.target.value)} data-testid={`pr-item-name-${i}`} />
                <Input placeholder="Spesifikasi" aria-label="Spesifikasi" value={it.specification}
                  onChange={e => setItem(i, 'specification', e.target.value)} />
              </div>
              <div className="grid grid-cols-3 gap-2">
                <Input type="number" min="0" step="0.01" placeholder="Qty" aria-label="Qty" value={it.qty}
                  onChange={e => setItem(i, 'qty', e.target.value)} data-testid={`pr-item-qty-${i}`} />
                {it.material_id && opt ? (
                  <SmartNativeSelect value={it.unit} onChange={e => setItem(i, 'unit', e.target.value)}
                    data-testid={`pr-item-uom-${i}`}>
                    {(opt.units || []).map(u => <option key={u.unit} value={u.unit}>{u.unit}</option>)}
                  </SmartNativeSelect>
                ) : (
                  <Input placeholder="Satuan" aria-label="Satuan" value={it.unit}
                    onChange={e => setItem(i, 'unit', e.target.value)} data-testid={`pr-item-uom-${i}`} />
                )}
                <MoneyInput placeholder="Estimasi harga" aria-label="Estimasi harga" value={it.estimated_price}
                  onChange={e => setItem(i, 'estimated_price', e.target.value)} data-testid={`pr-item-price-${i}`} />
              </div>
              {it.material_id && opt && it.unit && it.unit !== opt.base_unit && (
                <p className="text-xs text-muted-foreground" data-testid={`pr-item-preview-${i}`}>
                  1 {it.unit} = {f.toLocaleString('id-ID', { maximumFractionDigits: 4 })} {opt.base_unit} ⇒{' '}
                  <span className="font-semibold text-foreground">
                    {qtyBase.toLocaleString('id-ID', { maximumFractionDigits: 4 })} {opt.base_unit}
                  </span>{' '}
                  · harga per {opt.base_unit}: {fmtRp((Number(it.estimated_price) || 0) / (f || 1))}
                </p>
              )}
            </div>
          );
        })}
        <p className="text-right text-sm text-muted-foreground">
          Total estimasi: <span className="font-semibold tabular-nums text-foreground">{fmtRp(totalEst)}</span>
        </p>
      </div>
    </FormPopup>
  );
}

// ── Form buat PO dari PR (popup standar) ─────────────────────────────────────
function CreatePOFromPRModal({ pr, token, onClose, onCreated }) {
  const [form, setForm] = useState({
    supplier_id: '', vendor_name: '', vendor_contact: '', vendor_address: '',
    expected_delivery_date: '', notes: '',
  });
  const [suppliers, setSuppliers] = useState([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    fetch(`${API}/api/procurement/suppliers/options`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.json() : { items: [] }))
      .then((d) => setSuppliers(d?.items || []))
      .catch(() => {});
  }, [token]);

  const submit = async () => {
    if (!form.supplier_id && !form.vendor_name.trim()) {
      return setError('Pilih supplier dari Master Supplier terlebih dahulu');
    }
    setSaving(true); setError('');
    try {
      await axios.post(`${API}/api/procurement/requests/${pr.id}/create-po`, form, {
        headers: { Authorization: `Bearer ${token}` }
      });
      onCreated();
    } catch (e) {
      setError(e.response?.data?.detail || 'Gagal membuat PO');
    } finally { setSaving(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="create-po-from-pr-modal"
      judul="Buat purchase order" keterangan={`Dari PR ${pr.request_number} — ${pr.title}`}
      onSimpan={submit} menyimpan={saving} galat={error} labelSimpan="Buat PO">
      <Isian label="Supplier (master)" wajib
        petunjuk={suppliers.length === 0 ? 'Master Supplier masih kosong. Tambahkan supplier di menu Master Supplier.' : undefined}>
        <SmartNativeSelect
          value={form.supplier_id}
          onChange={(e) => {
            const sid = e.target.value;
            const s = suppliers.find((x) => x.id === sid);
            // 2026-11-07 (Tahap 5): kontak & alamat ikut supplier baru (dulu mewarisi supplier sebelumnya)
            const prevSup = suppliers.find((x) => x.id === form.supplier_id);
            const fromPrev = (v, k) => !prevSup || v === (prevSup[k] || '');
            setForm((p) => ({
              ...p,
              supplier_id: sid,
              vendor_name: s?.name || '',
              vendor_contact: s?.phone || (fromPrev(p.vendor_contact, 'phone') ? '' : p.vendor_contact),
              vendor_address: s?.address || (fromPrev(p.vendor_address, 'address') ? '' : p.vendor_address),
            }));
          }}
          data-testid="po-vendor-name"
        >
          <option value="">Pilih supplier dari master</option>
          {suppliers.map((s) => (
            <option key={s.id} value={s.id}>{`${s.code} — ${s.name}`}</option>
          ))}
        </SmartNativeSelect>
      </Isian>
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Kontak supplier" htmlFor="po-pr-contact">
          <Input id="po-pr-contact" placeholder="Telepon / email" value={form.vendor_contact}
            onChange={e => setForm(p => ({ ...p, vendor_contact: e.target.value }))} />
        </Isian>
        <Isian label="Tanggal kirim diharapkan">
          <DatePicker value={form.expected_delivery_date} placeholder="Pilih tanggal" testId="po-pr-expected-date"
            onChange={(v) => setForm(p => ({ ...p, expected_delivery_date: v }))} />
        </Isian>
      </div>
      <Isian label="Alamat supplier" htmlFor="po-pr-address">
        <Input id="po-pr-address" placeholder="Alamat lengkap supplier" value={form.vendor_address}
          onChange={e => setForm(p => ({ ...p, vendor_address: e.target.value }))} />
      </Isian>
      <Isian label="Catatan" htmlFor="po-pr-notes">
        <Textarea id="po-pr-notes" rows={2} placeholder="Instruksi tambahan untuk supplier" value={form.notes}
          onChange={e => setForm(p => ({ ...p, notes: e.target.value }))} />
      </Isian>
      {/* Pratinjau item */}
      <div className="rounded-lg border border-[var(--glass-border)] p-3">
        <p className="mb-2 text-xs text-muted-foreground">Item dari PR ({(pr.items || []).length} item)</p>
        <ul className="space-y-1">
          {(pr.items || []).map((it, i) => (
            <li key={i} className="flex justify-between gap-2 text-sm">
              <span className="min-w-0 text-foreground">{it.name} <span className="text-muted-foreground">× {it.qty} {it.unit}</span></span>
              <span className="shrink-0 tabular-nums">{fmtRp(it.total_price)}</span>
            </li>
          ))}
        </ul>
        <div className="mt-2 flex justify-between border-t border-[var(--glass-border)] pt-2 text-sm font-semibold">
          <span>Total estimasi</span>
          <span className="tabular-nums">{fmtRp(pr.total_estimated)}</span>
        </div>
      </div>
    </FormPopup>
  );
}

// ── Rantai persetujuan (stepper) ─────────────────────────────────────────────
// Menampilkan tahap yang WAJIB dilalui PR ini. Jumlah tahap TIDAK tetap: ia
// mengikuti nilai PR dan ambang yang diatur owner di Ringkasan Bisnis, lalu
// DIBEKUKAN saat PR diajukan. Semua data (`chain`) datang dari server.
function ApprovalStepper({ chain, compact = false }) {
  if (!Array.isArray(chain) || chain.length === 0) return null;

  if (compact) {
    return (
      <span className="inline-flex flex-wrap items-center gap-1" data-testid="pr-stepper-compact">
        {chain.map((s, i) => (
          <span key={s.stage} className="inline-flex items-center gap-1">
            <StatusBadge status={s.stage} tone={s.done ? 'success' : s.current ? 'warning' : 'muted'}
              label={<>{s.done ? <Check className="h-3 w-3" /> : s.current ? <Clock className="h-3 w-3" /> : <Circle className="h-3 w-3" />}
                {STAGE_SHORT[s.stage] || s.label}</>} />
            {i < chain.length - 1 && <ChevronRight className="h-3 w-3 text-muted-foreground" />}
          </span>
        ))}
      </span>
    );
  }

  return (
    <ol className="space-y-2" data-testid="pr-approval-stepper">
      {chain.map((s) => (
        <li key={s.stage} data-testid={`pr-stage-${s.stage}`}
          className="flex items-start gap-3 rounded-lg border border-[var(--glass-border)] px-3 py-2">
          <span className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
            s.done ? 'bg-[hsl(var(--success-strong))] text-white'
              : s.current ? 'bg-[hsl(var(--warning))] text-white' : 'bg-foreground/10 text-muted-foreground'}`}>
            {s.done ? <Check className="h-3 w-3" /> : s.order}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium text-foreground">{s.label}</span>
              {s.done && <StatusBadge status="done" label="Selesai" tone="success" />}
              {s.current && <StatusBadge status="current" label="Menunggu sekarang" tone="warning" />}
              {s.override && <StatusBadge status="override" label={<><ShieldAlert className="h-3 w-3" />Ditembus admin</>} tone="warning" />}
            </div>
            <p className="text-xs text-muted-foreground">
              {s.done
                ? `Oleh ${s.actor_name || '—'}${s.timestamp ? ` · ${fmtDT(s.timestamp)}` : ''}`
                : `Menunggu ${s.role_hint || 'approver'}`}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}

// ── Penjelasan hak: kenapa tombol muncul / tidak muncul ──────────────────────
// Kalau approver tidak berhak, ia harus TAHU alasannya — bukan sekadar melihat
// tombol hilang (itu yang dulu terjadi dan membuat rantai persetujuan "mati").
function GateNotice({ item }) {
  if (item?.can_approve && item?.is_override) {
    return (
      <Notice tone="warning" icon={ShieldAlert} testId="pr-override-notice">
        {item.override_note
          || 'Anda menembus aturan pemisahan wewenang sebagai admin/owner — tindakan ini dicatat di riwayat.'}
      </Notice>
    );
  }
  if (!item?.can_approve && item?.blocked_reason) {
    // Hanya berguna saat masih ADA tahap yang menunggu. Pada PR yang sudah
    // selesai/ditolak, "tidak ada persetujuan yang menunggu" cuma kebisingan.
    if (!item?.stage) return null;
    return <Notice tone="info" icon={Info} testId="pr-blocked-reason">{item.blocked_reason}</Notice>;
  }
  return null;
}

// ── Detail (popup standar) ────────────────────────────────────────────────────
function DetailModal({ item, onClose, onAction, token, focusReject = false }) {
  const [pr, setPr] = useState(item);
  const [note, setNote] = useState('');
  const [acting, setActing] = useState('');
  const [err, setErr] = useState('');
  const [okMsg, setOkMsg] = useState('');
  const [timeline, setTimeline] = useState([]);
  const [loadTL, setLoadTL] = useState(true);
  const [showCreatePO, setShowCreatePO] = useState(false);

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  // Basis endpoint datang dari SERVER (`api_base`): satu dialog melayani
  // Permintaan Pengadaan (/api/procurement/requests) DAN Request Pembelian
  // Aksesoris (/api/acc/purchase-requests) — keduanya kini memakai mesin
  // persetujuan yang sama, jadi UI-nya tidak perlu dua cabang.
  const base = item.api_base || '/api/procurement/requests';

  const reload = useCallback(async () => {
    setLoadTL(true);
    try {
      const [d, t] = await Promise.all([
        axios.get(`${API}${base}/${item.id}`, { headers }),
        axios.get(`${API}${base}/${item.id}/timeline`, { headers }),
      ]);
      setPr(d.data);
      setTimeline(t.data?.steps || []);
    } catch {
      /* tetap pakai data dari daftar bila detail gagal dimuat */
    } finally {
      setLoadTL(false);
    }
  }, [item.id, headers, base]);

  useEffect(() => { reload(); }, [reload]);

  const doAction = async (action) => {
    setErr(''); setOkMsg('');
    if (action === 'reject' && !note.trim()) {
      setErr('Alasan penolakan wajib diisi agar pemohon tahu apa yang harus diperbaiki.');
      return;
    }
    setActing(action);
    try {
      const res = await axios.post(
        `${API}${base}/${item.id}/${action}`,
        { comment: note, reason: note },
        { headers },
      );
      const d = res.data || {};
      if (action === 'approve') {
        setOkMsg(d.next_stage_label
          ? `Disetujui. Lanjut ke ${d.next_stage_label}.`
          : 'Disetujui penuh — permintaan siap dijadikan purchase order.');
      }
      setNote('');
      await reload();
      onAction(d);
    } catch (e) {
      setErr(e.response?.data?.detail || `Gagal ${action === 'approve' ? 'menyetujui' : action === 'reject' ? 'menolak' : 'memproses'}`);
    } finally {
      setActing('');
    }
  };

  // SEMUA keputusan tombol datang dari SERVER (`can_approve` / `can_reject`).
  // Modul ini SENGAJA tidak punya daftar peran sendiri: daftar peran kembar di
  // frontend inilah yang dulu menyembunyikan tombol Setujui/Tolak dari approver
  // ASLI (accounting / supervisor_produksi / admin_gudang) sehingga rantai
  // persetujuan mati di layar walau backend mengizinkan.
  const canApprove = !!pr.can_approve;
  const canReject = !!pr.can_reject;
  const canSubmit = pr.status === 'draft';
  const canComplete = pr.status === 'in_procurement';
  const canCreatePO = pr.status === 'approved' && !pr.linked_po_number
    && (item.kind || 'pr') === 'pr';
  const hasActions = canApprove || canReject || canSubmit || canComplete || canCreatePO;
  const prItems = pr.items || [];

  return (
    <>
      <DetailPopup open onClose={onClose} testId="pr-detail-modal"
        judul={pr.title}
        keterangan={pr.request_number}
        status={<><PRStatusBadge status={pr.status} /><PriorityBadge priority={pr.priority} /></>}
        aksi={prItems.length > 0 && (
          <TombolUnduh namaBerkas={`item-${pr.request_number || 'pr'}`} namaLembar="Item PR" baris={prItems}
            testId="pr-detail-unduh"
            kolom={[
              { label: 'Nama item', nilai: (it) => it.name },
              { label: 'Spesifikasi', nilai: (it) => it.specification || '' },
              { label: 'Qty', nilai: (it) => Number(it.qty || 0) },
              { label: 'Satuan', nilai: (it) => it.unit || '' },
              { label: 'Total (Rp)', nilai: (it) => Number(it.total_price || 0) },
            ]} />
        )}>
        {okMsg && <Notice tone="success" icon={CheckCircle2} testId="pr-action-success">{okMsg}</Notice>}
        {err && <Notice tone="danger" icon={AlertTriangle} testId="pr-action-error">{err}</Notice>}

        <dl className="divide-y divide-[var(--glass-border)]">
          {pr.linked_po_number && (
            <BarisDetail label="Purchase order terhubung">
              <span className="inline-flex items-center gap-1.5 font-medium"><FileText className="h-4 w-4 text-muted-foreground" />{pr.linked_po_number}</span>
            </BarisDetail>
          )}
          <BarisDetail label="Tipe">{TYPE_LABELS[pr.request_type] || pr.request_type || '—'}</BarisDetail>
          <BarisDetail label="Departemen">{pr.department || '—'}</BarisDetail>
          <BarisDetail label="Total estimasi"><span className="font-semibold tabular-nums">{fmtRp(pr.total_estimated)}</span></BarisDetail>
          {pr.justification && <BarisDetail label="Justifikasi">{pr.justification}</BarisDetail>}
        </dl>

        {pr.status === 'rejected' && pr.rejection_reason && (
          <Notice tone="danger" title="Alasan penolakan" testId="pr-rejection-reason">{pr.rejection_reason}</Notice>
        )}

        {/* Rantai persetujuan — jumlah tahap mengikuti nilai PR */}
        {Array.isArray(pr.chain) && pr.chain.length > 0 && (
          <div>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
                <Layers className="h-4 w-4" /> Rantai persetujuan
              </span>
              <span className="text-xs text-muted-foreground" data-testid="pr-chain-summary">
                {pr.total_stages} tahap untuk nilai {fmtRp(pr.total_estimated)}
                {pr.status === 'draft' ? ' (perkiraan — dibekukan saat diajukan)' : ''}
              </span>
            </div>
            <ApprovalStepper chain={pr.chain} />
            {pr.stage && (
              <p className="mt-2 text-xs text-muted-foreground" data-testid="pr-next-approver">
                Berikutnya setelah tahap ini: {pr.next_approver_label}
              </p>
            )}
          </div>
        )}

        <div>
          <p className="mb-2 text-sm font-semibold text-foreground">Item ({prItems.length})</p>
          {prItems.length === 0 ? <p className="text-sm text-muted-foreground">Tidak ada item.</p> : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Nama item</TableHead>
                    <TableHead>Spesifikasi</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead className="text-right">Total</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {prItems.map((it, i) => (
                    <TableRow key={i}>
                      <TableCell className="font-medium">{it.name}</TableCell>
                      <TableCell className="text-muted-foreground">{it.specification || '—'}</TableCell>
                      <TableCell className="whitespace-nowrap text-right tabular-nums">{it.qty} {it.unit}</TableCell>
                      <TableCell className="whitespace-nowrap text-right tabular-nums">{fmtRp(it.total_price)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </div>

        {/* Riwayat keputusan */}
        <div>
          <p className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-foreground">
            <History className="h-4 w-4" /> Riwayat
          </p>
          {loadTL ? (
            <p className="text-sm text-muted-foreground">Memuat riwayat…</p>
          ) : timeline.length === 0 ? (
            <p className="text-sm text-muted-foreground">Permintaan masih draf — riwayat muncul setelah diajukan.</p>
          ) : (
            <ul className="space-y-1" data-testid="pr-timeline">
              {timeline.map((t, i) => (
                <li key={i} className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="w-32 shrink-0 text-xs text-muted-foreground">{fmtDT(t.timestamp)}</span>
                  <span className="text-foreground">{t.action_label || t.action}</span>
                  {t.actor_name && <span className="text-muted-foreground">— {t.actor_name}</span>}
                  {t.override && <StatusBadge status="override" label="Ditembus admin" tone="warning" />}
                  {t.comment && <span className="italic text-muted-foreground">“{t.comment}”</span>}
                </li>
              ))}
            </ul>
          )}
        </div>

        <GateNotice item={pr} />

        {hasActions && (
          <div className="space-y-2 border-t border-[var(--glass-border)] pt-4">
            {(canApprove || canReject) && (
              <Textarea
                rows={2}
                autoFocus={focusReject}
                aria-label="Catatan keputusan"
                placeholder={canReject ? 'Catatan persetujuan / alasan penolakan (wajib bila menolak)' : 'Catatan (opsional)'}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                data-testid="pr-decision-note"
              />
            )}
            <div className="flex flex-wrap justify-end gap-2">
              {canSubmit && (
                <Button onClick={() => doAction('submit')} disabled={!!acting} data-testid="btn-submit-pr">
                  {acting === 'submit' ? <Loader2 className="animate-spin" /> : <Send />}
                  {acting === 'submit' ? 'Mengirim…' : 'Ajukan ke approver'}
                </Button>
              )}
              {canReject && (
                <Button variant="destructive" onClick={() => doAction('reject')} disabled={!!acting} data-testid="btn-reject-pr">
                  <XCircle />{acting === 'reject' ? 'Menolak…' : 'Tolak'}
                </Button>
              )}
              {canApprove && (
                <Button variant="success" onClick={() => doAction('approve')} disabled={!!acting} data-testid="btn-approve-pr">
                  <CheckCircle2 />
                  {acting === 'approve' ? 'Menyetujui…' : `Setujui — ${pr.stage_label || 'tahap ini'}`}
                </Button>
              )}
              {canCreatePO && (
                <Button onClick={() => setShowCreatePO(true)} disabled={!!acting} data-testid="btn-create-po-from-pr">
                  <FileText />Buat purchase order
                </Button>
              )}
              {canComplete && (
                <Button variant="success" onClick={() => doAction('complete')} disabled={!!acting} data-testid="btn-complete-pr">
                  <CheckCircle2 />{acting === 'complete' ? 'Menyelesaikan…' : 'Tandai selesai'}
                </Button>
              )}
            </div>
          </div>
        )}
      </DetailPopup>

      {showCreatePO && (
        <CreatePOFromPRModal
          pr={pr}
          token={token}
          onClose={() => setShowCreatePO(false)}
          onCreated={async () => {
            // Muat ulang detailnya: tanpa ini dialog tetap menampilkan data lama
            // (nomor PO tidak muncul dan tombol "Buat Purchase Order" masih ada,
            // padahal PO-nya sudah terbentuk) — bug staleness yang terlihat saat
            // verifikasi UI 2026-08-07.
            setShowCreatePO(false);
            setOkMsg('Purchase order berhasil dibuat dari permintaan ini.');
            await reload();
            onAction({});
          }}
        />
      )}
    </>
  );
}

// ── Kartu PR (tampilan Kartu & HP) ───────────────────────────────────────────
function PRCard({ it, onOpen, onQuickApprove, quickBusy, showChain = true }) {
  return (
    <div
      onClick={() => onOpen(it)}
      className="cursor-pointer rounded-lg border border-[var(--glass-border)] bg-[var(--card-surface)] p-3 transition-colors hover:border-[hsl(var(--primary)/0.35)]"
      data-testid={`pr-card-${it.request_number}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <PRStatusBadge status={it.status} />
            <PriorityBadge priority={it.priority} />
            <KindBadges it={it} />
            {it.can_approve && <StatusBadge status="perlu" label="Perlu keputusan Anda" tone="success" />}
          </div>
          <p className="mt-1.5 text-sm font-semibold leading-snug text-foreground">{it.title}</p>
          <p className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-muted-foreground">
            <span>{it.request_number}</span>
            {it.department && <span>{it.department}</span>}
            <span>{it.requested_by_name || 'Admin'}</span>
            <span>{fmtTgl(it.created_at)}</span>
            <span className="font-medium text-foreground tabular-nums">{fmtRp(it.total_estimated)}</span>
            <span>{(it.items || []).length} item</span>
          </p>
          {showChain && Array.isArray(it.chain) && it.chain.length > 0 && (
            <div className="mt-2"><ApprovalStepper chain={it.chain} compact /></div>
          )}
          {!it.can_approve && it.blocked_reason && it.stage && (
            <p className="mt-1.5 text-xs text-muted-foreground" data-testid={`pr-blocked-${it.request_number}`}>
              {it.blocked_reason}
            </p>
          )}
        </div>
        {onQuickApprove && it.can_approve && (
          <Button size="sm" variant="success" disabled={quickBusy === it.id}
            onClick={(e) => { e.stopPropagation(); onQuickApprove(it); }}
            data-testid={`btn-quick-approve-${it.request_number}`}>
            {quickBusy === it.id ? <Loader2 className="animate-spin" /> : <Check />}Setujui
          </Button>
        )}
      </div>
    </div>
  );
}

// ── Kolom tabel & unduhan ────────────────────────────────────────────────────
const KOLOM_URUT = [
  ['request_number', 'No. PR'], ['title', 'Judul'],
  ['request_type', 'Jenis'], ['department', 'Departemen'],
  ['priority', 'Prioritas'], ['status', 'Status'],
  ['total_estimated', 'Nilai (Rp)'],
  ['requested_by_name', 'Pemohon'],
  ['needed_by', 'Dibutuhkan'],
  ['created_at', 'Dibuat'],
];
const LABEL_URUT = Object.fromEntries(KOLOM_URUT);

const KOLOM_UNDUH = [
  { label: 'No. PR', nilai: (it) => it.request_number },
  { label: 'Judul', nilai: (it) => it.title },
  { label: 'Jenis', nilai: (it) => TYPE_LABELS[it.request_type] || it.request_type || '' },
  { label: 'Departemen', nilai: (it) => it.department || '' },
  { label: 'Prioritas', nilai: (it) => PRIORITY_CFG[it.priority]?.label || it.priority || '' },
  { label: 'Status', nilai: (it) => STATUS_CFG[it.status]?.label || it.status || '' },
  { label: 'Nilai (Rp)', nilai: (it) => Number(it.total_estimated || 0) },
  { label: 'Pemohon', nilai: (it) => it.requested_by_name || '' },
  { label: 'Dibutuhkan', nilai: (it) => (it.needed_by ? formatDateID(it.needed_by) : '') },
  { label: 'Dibuat', nilai: (it) => (it.created_at ? formatDateID(it.created_at) : '') },
  { label: 'Menunggu', nilai: (it) => it.next_approver_label || '' },
  { label: 'No. PO', nilai: (it) => it.linked_po_number || '' },
];

// ── Main Module ───────────────────────────────────────────────────────────────
export default function ProcurementRequestModule({ token, user, onNavigate }) {
  const [tab, setTab] = useState('all');            // all | inbox | mine
  const [stats, setStats] = useState(null);
  const [items, setItems] = useState([]);
  const [inbox, setInbox] = useState([]);
  const [loading, setLoading] = useState(true);
  const [inboxLoading, setInboxLoading] = useState(true);
  const [quickBusy, setQuickBusy] = useState('');
  const [banner, setBanner] = useState(null);       // {type, text}
  const [search, setSearch] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [filterPriority, setFilterPriority] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [detail, setDetail] = useState(null);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalRows, setTotalRows] = useState(0);
  // F13-B (sesi #12) — PR adalah KOMITMEN UANG. Pengurutan sengaja dikerjakan SERVER
  // (`sort_by`/`sort_dir`) supaya urutannya berlaku untuk SELURUH data, bukan
  // 15 baris yang kebetulan sedang terbuka.
  const [view, setView] = useState(() => {
    try { return localStorage.getItem(PR_VIEW_KEY) || 'table'; } catch { return 'table'; }
  });
  useEffect(() => {
    try { localStorage.setItem(PR_VIEW_KEY, view); } catch { /* penyimpanan diblokir */ }
  }, [view]);
  const [sort, setSort] = useState({ key: 'created_at', dir: 'desc' });
  const toggleSort = (key) => {
    setPage(1);
    setSort((s) => (s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' }
      : { key, dir: 'desc' }));
  };

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);
  // Sekali saja: kalau approver punya pekerjaan menunggu, buka langsung di
  // kotak persetujuan (itu yang ia cari saat masuk lewat lencana/notifikasi).
  // Begitu ia memilih tab sendiri, pilihannya tidak diganggu lagi.
  const tabTouched = useRef(false);
  const autoTabDone = useRef(false);

  const loadInbox = useCallback(async () => {
    setInboxLoading(true);
    try {
      const r = await axios.get(`${API}/api/procurement/inbox`, { headers });
      const list = Array.isArray(r.data) ? r.data : (r.data?.items || []);
      setInbox(list);
      if (!autoTabDone.current && !tabTouched.current && list.length > 0) {
        autoTabDone.current = true;
        setTab('inbox');
      }
    } catch {
      setInbox([]);
    } finally {
      setInboxLoading(false);
    }
  }, [headers]);

  /** Parameter daftar yang sama untuk layar dan unduhan (saringan + urutan). */
  const listParams = useCallback(() => {
    const params = { sort_by: sort.key, sort_dir: sort.dir };
    if (filterStatus) params.status = filterStatus;
    if (filterPriority) params.priority = filterPriority;
    if (search) params.search = search;
    if (tab === 'mine') params.my_only = true;
    return params;
  }, [filterStatus, filterPriority, search, tab, sort]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { page, limit: PAGE_SIZE, ...listParams() };
      const [listRes, dashRes] = await Promise.all([
        axios.get(`${API}/api/procurement/requests`, { headers, params }),
        axios.get(`${API}/api/procurement/dashboard`, { headers }),
      ]);
      setItems(listRes.data?.items || []);
      setTotalPages(listRes.data?.pagination?.total_pages || 1);
      setTotalRows(listRes.data?.pagination?.total ?? (listRes.data?.items || []).length);
      setStats(dashRes.data?.summary || null);
    } catch (e) {
      console.error('Procurement load error', e);
    } finally {
      setLoading(false);
    }
  }, [headers, page, listParams]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadInbox(); }, [loadInbox]);

  const refreshAll = useCallback(() => { load(); loadInbox(); }, [load, loadInbox]);

  /** Unduhan = SEMUA baris hasil saringan & urutan saat ini (server, per 100 baris). */
  const ambilSemua = useCallback(async () => {
    const semua = [];
    for (let p = 1; p <= 200; p += 1) {
      const r = await axios.get(`${API}/api/procurement/requests`, {
        headers, params: { page: p, limit: 100, ...listParams() },
      });
      semua.push(...(r.data?.items || []));
      if (p >= (r.data?.pagination?.total_pages || 1)) break;
    }
    return semua;
  }, [headers, listParams]);

  const quickApprove = async (it) => {
    setQuickBusy(it.id); setBanner(null);
    // Basis endpoint dari server: PR pengadaan dan Request Pembelian Aksesoris
    // memakai mesin persetujuan yang sama tapi endpoint-nya berbeda.
    const apiBase = it.api_base || '/api/procurement/requests';
    try {
      const res = await axios.post(
        `${API}${apiBase}/${it.id}/approve`,
        { comment: '' },
        { headers },
      );
      const d = res.data || {};
      setBanner({
        type: 'ok',
        text: d.next_stage_label
          ? `${it.request_number} disetujui — lanjut ke ${d.next_stage_label}.`
          : `${it.request_number} disetujui penuh — siap dijadikan purchase order.`,
      });
      refreshAll();
    } catch (e) {
      setBanner({ type: 'err', text: e.response?.data?.detail || `Gagal menyetujui ${it.request_number}` });
    } finally {
      setQuickBusy('');
    }
  };

  const inboxValue = inbox.reduce((s, i) => s + Number(i.total_estimated || 0), 0);
  const prRows = items || [];

  const selectTab = (v) => { tabTouched.current = true; setTab(v); setPage(1); };
  const adaSaringan = !!(search || filterStatus || filterPriority);

  const tabOpsi = [
    { key: 'all', label: 'Semua', count: stats?.total },
    { key: 'inbox', label: 'Perlu keputusan saya', count: inbox.length },
    { key: 'mine', label: 'Milik saya', count: stats?.my_requests },
  ];

  const kolomInbox = [
    { kunci: 'judul', label: 'Permintaan', hp: 'judul', isi: (it) => (
      <div className="min-w-0 md:max-w-[22rem]">
        <p className="truncate font-medium" title={it.title}>{it.title}</p>
        <p className="text-xs text-muted-foreground">{it.request_number}{it.department ? ` · ${it.department}` : ''}</p>
      </div>) },
    { kunci: 'jenis', label: 'Jenis', isi: (it) => (
      <span className="inline-flex flex-wrap gap-1">
        {it.kind === 'acc_pr' || it.kind === 'po' || it.exceeds_pr_value ? <KindBadges it={it} /> : <span className="text-sm">Permintaan pengadaan</span>}
      </span>) },
    { kunci: 'pemohon', label: 'Pemohon', isi: (it) => it.requested_by_name || '—' },
    { kunci: 'nilai', label: 'Nilai', rata: 'kanan', isi: (it) => <span className="tabular-nums whitespace-nowrap">{fmtRp(it.total_estimated)}</span> },
    { kunci: 'tahap', label: 'Tahap', isi: (it) => <ApprovalStepper chain={it.chain} compact /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (it) => it.can_approve && (
      <Button size="sm" variant="success" disabled={quickBusy === it.id} onClick={() => quickApprove(it)}
        data-testid={`btn-quick-approve-${it.request_number}`}>
        {quickBusy === it.id ? <Loader2 className="animate-spin" /> : <Check />}Setujui
      </Button>) },
  ];

  const tableView = (
    <div className="overflow-x-auto">
      <Table data-testid="pr-table">
        <TableHeader>
          <TableRow>
            {KOLOM_URUT.map(([k, label]) => (
              <TableHead key={k} className={`whitespace-nowrap ${k === 'total_estimated' ? 'text-right' : ''}`}
                aria-sort={sort.key === k ? (sort.dir === 'asc' ? 'ascending' : 'descending') : undefined}>
                <Button type="button" variant="ghost" size="sm" onClick={() => toggleSort(k)}
                  data-testid={`pr-sort-${k}`} title={`Urutkan menurut ${label.toLowerCase()}`}
                  className="-mx-2 h-7 px-2 font-semibold">
                  {label}
                  <ArrowUpDown className={sort.key === k ? 'text-primary' : 'opacity-30'} />
                </Button>
              </TableHead>
            ))}
            <TableHead className="whitespace-nowrap text-right">Persetujuan</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {prRows.map((it) => (
            <TableRow key={it.id} className="cursor-pointer" onClick={() => setDetail(it)}
              data-testid={`pr-row-${it.request_number}`}>
              <TableCell className="whitespace-nowrap font-medium">{it.request_number}</TableCell>
              <TableCell className="max-w-[16rem] truncate" title={it.title}>{it.title}</TableCell>
              <TableCell className="whitespace-nowrap">{TYPE_LABELS[it.request_type] || it.request_type}</TableCell>
              <TableCell className="whitespace-nowrap">{it.department || '—'}</TableCell>
              <TableCell><PriorityBadge priority={it.priority} /></TableCell>
              <TableCell><PRStatusBadge status={it.status} /></TableCell>
              <TableCell className="whitespace-nowrap text-right font-medium tabular-nums">{formatRupiah(it.total_estimated || 0)}</TableCell>
              <TableCell className="whitespace-nowrap">{it.requested_by_name || '—'}</TableCell>
              <TableCell className="whitespace-nowrap">{fmtTgl(it.needed_by)}</TableCell>
              <TableCell className="whitespace-nowrap">{fmtTgl(it.created_at)}</TableCell>
              <TableCell className="whitespace-nowrap text-right" onClick={(e) => e.stopPropagation()}>
                {/* Kolom ini menjawab "siapa yang ditunggu" — pertanyaan
                    yang paling sering ditanyakan tentang PR yang mandek. */}
                {it.can_approve ? (
                  <Button size="sm" variant="success" disabled={quickBusy === it.id} onClick={() => quickApprove(it)}
                    data-testid={`pr-quick-approve-${it.request_number}`}>
                    {quickBusy === it.id ? <Loader2 className="animate-spin" /> : <Check />}Setujui
                  </Button>
                ) : (
                  <span className="text-xs text-muted-foreground">{it.next_approver_label || '—'}</span>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );

  const cardsView = (
    <div className="space-y-2">
      {prRows.map((it) => (
        <PRCard key={it.id} it={it} onOpen={setDetail} onQuickApprove={quickApprove} quickBusy={quickBusy} />
      ))}
    </div>
  );

  return (
    <PageLayout testId="procurement-module" title="Permintaan Pengadaan"
      subtitle="Ajukan, setujui, dan pantau permintaan pembelian — jumlah tahap persetujuan mengikuti nilai permintaan."
      actions={<>
        {/* RC-FLOW-UX: onward — PR → Purchase Order → GRN (dulu kotak "Langkah berikutnya" selebar halaman). */}
        {typeof onNavigate === 'function' && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" data-testid="onward-cta">Langkah berikutnya<ChevronDown /></Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-72">
              <DropdownMenuItem onSelect={() => onNavigate('proc-purchase-orders', {})} data-testid="onward-proc-purchase-orders">
                <div>
                  <p className="text-sm font-medium">Buat purchase order</p>
                  <p className="text-xs text-muted-foreground">PR disetujui → terbitkan PO ke supplier</p>
                </div>
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => onNavigate('wh-receiving', {})} data-testid="onward-wh-receiving">
                <div>
                  <p className="text-sm font-medium">Penerimaan barang</p>
                  <p className="text-xs text-muted-foreground">Setelah barang datang, catat penerimaan (Portal Gudang)</p>
                </div>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
        <Button onClick={() => setShowCreate(true)} data-testid="btn-open-create-pr"><Plus />Buat PR</Button>
      </>}
      filters={<>
        <FilterChips options={tabOpsi} value={tab} onChange={selectTab} hideWhenEmpty={false}
          testId="pr-tab" ariaLabel="Pilih daftar" />
        {tab !== 'inbox' && (<>
          <div className="relative w-full sm:w-48">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input className="pl-8" placeholder="Cari judul atau nomor PR"
              value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }}
              data-testid="pr-search" />
          </div>
          <SmartNativeSelect className="w-44 h-9"
            value={filterStatus} onChange={(e) => { setFilterStatus(e.target.value); setPage(1); }}
            data-testid="pr-filter-status">
            <option value="">Semua status</option>
            {Object.entries(STATUS_CFG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </SmartNativeSelect>
          <SmartNativeSelect className="w-36 h-9"
            value={filterPriority} onChange={(e) => { setFilterPriority(e.target.value); setPage(1); }}
            data-testid="pr-filter-priority">
            <option value="">Semua prioritas</option>
            {Object.entries(PRIORITY_CFG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </SmartNativeSelect>
        </>)}
      </>}
      tools={<>
        {tab === 'inbox' ? (
          <TombolUnduh namaBerkas="menunggu-keputusan-saya" namaLembar="Menunggu keputusan" baris={inbox}
            testId="pr-inbox-unduh" kolom={KOLOM_UNDUH} />
        ) : (<>
          <ViewToggle value={view} onChange={setView} testId="pr-view" />
          <TombolUnduh namaBerkas="permintaan-pengadaan" namaLembar="Permintaan" baris={prRows}
            ambilSemua={ambilSemua} testId="pr-export-csv" kolom={KOLOM_UNDUH} />
        </>)}
        <Button variant="outline" size="icon" onClick={refreshAll} title="Muat ulang" aria-label="Muat ulang"
          data-testid="pr-refresh">
          <RefreshCw className={loading || inboxLoading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={<>
        {banner && (
          <Notice tone={banner.type === 'ok' ? 'success' : 'danger'} icon={banner.type === 'ok' ? CheckCircle2 : AlertTriangle}
            testId="pr-banner"
            action={<Button variant="ghost" size="icon-sm" onClick={() => setBanner(null)} title="Tutup" aria-label="Tutup"><X /></Button>}>
            {banner.text}
          </Notice>
        )}
        {stats && Number(stats.total) > 0 && (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="pr-stats">
            <StatTile label="Total PR" value={Number(stats.total).toLocaleString('id-ID')}
              hint="Semua permintaan pengadaan, tanpa saringan." />
            <StatTile label="Perlu keputusan saya" value={Number(stats.my_pending_approval || 0).toLocaleString('id-ID')}
              accent="warning" hint="Hanya permintaan yang tahap aktifnya memang hak Anda (aturan sama dengan pil Perlu keputusan saya)." />
            <StatTile label="Disetujui, belum diproses" value={Number(stats.approved || 0).toLocaleString('id-ID')}
              accent="success" hint="Permintaan berstatus Disetujui yang belum dijadikan PO atau selesai." />
            <StatTile label="Nilai disetujui bulan ini" value={fmtRp(stats.total_value_approved_this_month)}
              hint="Jumlah nilai PR berstatus Disetujui atau Selesai yang diajukan sejak awal bulan ini (WIB)." />
          </div>
        )}
        {tab === 'inbox' && inbox.length > 0 && (
          <p className="text-sm text-muted-foreground" data-testid="pr-inbox-summary">
            {inbox.length} permintaan menunggu keputusan Anda · total nilai{' '}
            <span className="font-semibold text-foreground tabular-nums">{fmtRp(inboxValue)}</span>
          </p>
        )}
      </>}
      footer={tab !== 'inbox' && !loading && prRows.length > 0 && (
        <div className="space-y-1">
          {/* Pagination — halaman diambil dari server, jadi `total` dan `totalPages` datang dari server juga. */}
          <PaginationLite page={page} totalPages={totalPages} total={totalRows} pageSize={PAGE_SIZE} onPageChange={setPage} />
          <p className="text-xs text-muted-foreground">
            Urut menurut {(LABEL_URUT[sort.key] || sort.key).toLowerCase()} — {sort.dir === 'desc' ? 'terbesar/terbaru dulu' : 'terkecil/terlama dulu'},
            berlaku untuk seluruh data.
          </p>
        </div>
      )}>
      {tab === 'inbox' ? (
        <div data-testid="pr-inbox-panel">
          {inboxLoading ? (
            <p className="py-6 text-center text-sm text-muted-foreground">Memuat daftar persetujuan…</p>
          ) : (
            <TabelData kolom={kolomInbox} baris={inbox} onKlikBaris={setDetail} testId="pr-inbox-table"
              kosong={<EmptyState testId="pr-inbox-empty" title="Tidak ada permintaan yang menunggu keputusan Anda"
                description="Daftar ini menggabungkan permintaan pengadaan dan request pembelian aksesoris. Permintaan muncul hanya saat giliran Anda: tahap aktif cocok dengan peran Anda, bukan permintaan buatan Anda sendiri, dan Anda belum menyetujuinya di tahap sebelumnya." />} />
          )}
        </div>
      ) : loading ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat permintaan…</p>
      ) : prRows.length === 0 ? (
        <EmptyState icon={ShoppingCart}
          title={adaSaringan ? 'Tidak ada permintaan yang cocok' : tab === 'mine' ? 'Anda belum pernah membuat permintaan pengadaan' : 'Belum ada permintaan pengadaan'}
          description={adaSaringan ? 'Ubah kata pencarian atau saringan status dan prioritas.' : 'Buat permintaan untuk barang atau jasa yang perlu dibeli; approver akan menerimanya sesuai nilai.'}
          action={!adaSaringan && <Button onClick={() => setShowCreate(true)}><Plus />Buat permintaan pertama</Button>} />
      ) : (
        <>
          {/* HP: selalu kartu ringkas (tanpa geser samping); layar lebar: sesuai pilihan Tabel/Kartu. */}
          <div className="md:hidden">{cardsView}</div>
          <div className="hidden md:block">{view === 'table' ? tableView : cardsView}</div>
        </>
      )}

      {/* Popup */}
      {showCreate && (
        <CreatePRModal token={token} onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); refreshAll(); }} />
      )}
      {detail && (
        <DetailModal
          item={detail}
          token={token}
          onClose={() => { setDetail(null); refreshAll(); }}
          onAction={() => refreshAll()}
        />
      )}
    </PageLayout>
  );
}

/**
 * Kalkulator HPP (Portal RnD › Costing & HPP › tab "Kalkulator HPP").
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, daftar = tabel + unduh Excel/CSV, rincian = popup,
 * form = FormPopup panjang (Simpan & setujui hijau, Simpan draf garis), hapus lewat confirmDialog, warna token.
 * Hanya tampilan yang berubah — semua hitungan tetap di server (/preview, /compute-from-bom), isian & API sama.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';
import { MoneyInput } from '@/components/ui/money-input';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import {
  Calculator, Plus, Trash2, Pencil, RefreshCw, Wand2, AlertTriangle, Database,
  PenLine, CheckCircle2, History, X, Search,
} from 'lucide-react';
import { toast } from '../ui/sonner';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatRupiah, formatDateID } from '@/lib/format';
import { apiDelete } from '@/lib/api';
import { cn } from '@/lib/utils';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL || '';

const fmt = (n) => (n != null && n !== '' ? formatRupiah(n) : '—');
const fmtPersen = (n) => (n != null && n !== '' ? `${Number(n).toLocaleString('id-ID', { maximumFractionDigits: 2 })}%` : '—');

const emptyAcc = { name: '', unit_cost: 0, qty: 1 };

/** F4 — sumber biaya PER BARIS. Menggantikan saklar global `use_bom`
 *  (semua-atau-tidak) yang membuat master + custom MUSTAHIL dicampur. */
const SOURCES = [
  { value: 'master',   label: 'Master',    tone: 'info',    hint: 'Harga dari master material' },
  { value: 'techpack', label: 'Tech pack', tone: 'primary', hint: 'Dari BOM tech pack terbaru style ini' },
  { value: 'manual',   label: 'Manual',    tone: 'warning', hint: 'Isian bebas — nama & harga sendiri' },
];
const sumberLabel = (s) => SOURCES.find(x => x.value === s)?.label || s;

const STATUS_HPP = {
  draft:    { label: 'Draf', tone: 'muted' },
  approved: { label: 'Disetujui', tone: 'success' },
};
const statusHpp = (s) => STATUS_HPP[s] || { label: s ? 'Lainnya' : 'Draf', tone: 'muted' };

/** Aturan HPP owner 6 Nov 2026 = bahan + kemasan + CMT. Dokumen lama menyimpan HPP yang masih memuat cutting &
 *  overhead (angka tersimpan tidak diubah) — layar memberi tanda supaya tidak dibandingkan apa adanya. */
const aturanLama = (r) => r.hpp_rule !== 'bahan_cmt_2026_11_06'
  && (Number(r.cutting_cost || 0) > 0 || Number(r.overhead_value || 0) > 0);

const emptyForm = {
  hpp_code: '', style_id: '', style_code: '', style_name: '',
  fabric_usage_per_pcs: 0,
  fabric_price_per_meter: 0,
  fabric_source: 'manual', fabric_size: '',
  accessories_cost: [{ name: 'Label / Tag', unit_cost: 500, qty: 1 }],
  cost_lines: [],
  cmt_cost_per_pcs: 0, cmt_cost_source: 'manual', cmt_cost_ref: '',
  cutting_cost_per_pcs: 0,
  packaging_cost_per_pcs: 0,
  overhead_pct: 0,   // 2026-11-06 (Tahap 2): overhead tidak masuk HPP — bawaan 0
  margin_pct: 30,
  use_bom: false,
  notes: '', status: 'draft',
};

const PREVIEW_INIT = {
  fabric_cost: 0, accessories_total: 0, material_cost: 0, cmt_cost: 0, cutting_cost: 0,
  packaging_cost: 0, direct_cost: 0, overhead_value: 0,
  hpp_total: 0, selling_price_proposal: 0,
  margin_pct: 30, overhead_pct: 0,
};

let lineSeq = 0;
const newLineId = () => `l_${Date.now().toString(36)}_${lineSeq++}`;

async function readErr(res, fallback) {
  try { const d = await res.json(); return d?.detail || fallback; } catch { return fallback; }
}

/** Label kecil di atas isian baris biaya. */
const Lbl = ({ children }) => <span className="mb-1 block text-xs text-muted-foreground">{children}</span>;

/** Satu baris "label ........ nilai" di ringkasan hasil hitung. */
function BarisHasil({ label, nilai, tebal, redup, testId }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1">
      <span className={cn('text-sm', tebal ? 'font-medium text-foreground' : 'text-muted-foreground')}>{label}</span>
      <span className={cn('text-sm tabular-nums', tebal ? 'font-semibold text-foreground' : redup ? 'text-muted-foreground' : 'text-foreground')}
        data-testid={testId}>{nilai}</span>
    </div>
  );
}

export default function RnDHPPCalculatorModule({ token }) {
  const hdr = useMemo(() => ({ 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }), [token]);
  const [records, setRecords]   = useState([]);
  const [styles,  setStyles]    = useState([]);
  const [matOpts, setMatOpts]   = useState([]);
  const [cmtOpts, setCmtOpts]   = useState([]);
  const [loading, setLoading]   = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [editing,  setEditing]  = useState(null);
  const [form,     setForm]     = useState({ ...emptyForm });
  const [preview,  setPreview]  = useState(PREVIEW_INIT);
  const [prevLoading, setPrevLoading] = useState(false);
  const [prevError, setPrevError] = useState('');
  const [computed, setComputed] = useState([]);   // cost_lines hasil hitungan server
  const [stale,    setStale]    = useState(null);
  const [saving,   setSaving]   = useState(false);
  const [detail,   setDetail]   = useState(null);
  const [cari,     setCari]     = useState('');

  const f = (name, val) => setForm(prev => ({ ...prev, [name]: val }));

  // ── estimasi kain dari techpack (mode lama, tetap dipertahankan) ──
  const [fabricEst, setFabricEst] = useState(null);
  const [fabricEstLoading, setFabricEstLoading] = useState(false);

  const hybrid = (form.cost_lines || []).length > 0;

  // ─────────────────────────── loaders ───────────────────────────
  const loadRecords = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/dewi/rnd/hpp-calculator`, { headers: hdr });
      const d = await res.json();
      setRecords(Array.isArray(d) ? d : []);
    } catch { toast.error('Gagal memuat HPP'); }
    finally { setLoading(false); }
  }, [hdr]);

  const loadStyles = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/dewi/rnd/styles`, { headers: hdr });
      const data = await res.json();
      setStyles(Array.isArray(data) ? data : (data.items || []));
    } catch { /* ignore */ }
  }, [hdr]);

  const loadMatOpts = useCallback(async () => {
    try {
      // 2026-11-08 (Standar UI/UX v2, perbaikan pemilih): bawaan server 500 baris, diurut aksesoris dulu →
      // ±600 kain aktif tidak pernah muncul di pilihan baris Master. Minta sampai batas server (2000).
      const res = await fetch(`${API}/api/dewi/rnd/material-options?limit=2000`, { headers: hdr });
      if (res.ok) setMatOpts(await res.json());
    } catch { /* ignore */ }
  }, [hdr]);

  const loadCmtOpts = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/dewi/rnd/hpp-calculator/cmt-suggestions`, { headers: hdr });
      if (res.ok) setCmtOpts(await res.json());
    } catch { /* ignore */ }
  }, [hdr]);

  useEffect(() => { loadRecords(); loadStyles(); loadMatOpts(); loadCmtOpts(); },
    [loadRecords, loadStyles, loadMatOpts, loadCmtOpts]);

  // ─────────────────────────── live preview ───────────────────────────
  const fetchPreview = useCallback(async (formData) => {
    setPrevLoading(true);
    try {
      const useLines = (formData.cost_lines || []).length > 0;
      const endpoint = useLines
        ? 'preview'
        : (formData.use_bom ? 'compute-from-bom' : 'preview');
      const res = await fetch(`${API}/api/dewi/rnd/hpp-calculator/${endpoint}`, {
        method: 'POST', headers: hdr, body: JSON.stringify(formData),
      });
      if (res.ok) {
        const data = await res.json();
        setPreview(data);
        setPrevError('');
        setComputed(useLines ? (data.cost_lines || []) : (data.material_breakdown || []));
      } else {
        setPrevError(await readErr(res, 'Gagal menghitung'));
      }
    } catch { setPrevError('Gagal menghubungi server'); }
    finally { setPrevLoading(false); }
  }, [hdr]);

  useEffect(() => {
    if (!showForm) return;
    const t = setTimeout(() => fetchPreview(form), 450);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    form.fabric_usage_per_pcs, form.fabric_price_per_meter,
    form.accessories_cost, form.cost_lines, form.cmt_cost_per_pcs,
    form.cutting_cost_per_pcs, form.packaging_cost_per_pcs,
    form.overhead_pct, form.margin_pct, form.use_bom, form.style_id,
    showForm, fetchPreview,
  ]);

  // ─────────────────────────── open / edit ───────────────────────────
  const openNew = () => {
    setForm({ ...emptyForm, hpp_code: `HPP-${Date.now().toString(36).toUpperCase()}` });
    setPreview(PREVIEW_INIT); setComputed([]); setStale(null); setPrevError('');
    setEditing(null); setShowForm(true);
  };

  const openEdit = async (rec) => {
    setDetail(null);
    setForm({
      hpp_code: rec.hpp_code || '',
      style_id: rec.style_id || '',
      style_code: rec.style_code || '',
      style_name: rec.style_name || '',
      fabric_usage_per_pcs: rec.fabric_usage_per_pcs || 0,
      fabric_price_per_meter: rec.fabric_price_per_meter || 0,
      fabric_source: rec.fabric_source || 'manual',
      fabric_size: rec.fabric_size || '',
      accessories_cost: rec.accessories_cost?.length ? rec.accessories_cost : [{ ...emptyAcc }],
      // dokumen lama dibaca sebagai cost_lines oleh backend (legacy mapping)
      cost_lines: (rec.cost_lines || []).map(l => ({ ...l, line_id: l.line_id || newLineId() })),
      cmt_cost_per_pcs: rec.cmt_cost_per_pcs || 0,
      cmt_cost_source: rec.cmt_cost_source || 'manual',
      cmt_cost_ref: rec.cmt_cost_ref || '',
      cutting_cost_per_pcs: rec.cutting_cost_per_pcs || 0,
      packaging_cost_per_pcs: rec.packaging_cost_per_pcs || 0,
      overhead_pct: rec.overhead_pct ?? 0,
      margin_pct: rec.margin_pct ?? 30,
      use_bom: !!rec.use_bom,
      notes: rec.notes || '',
      status: rec.status || 'draft',
    });
    setComputed(rec.cost_lines || rec.bom_breakdown || []);
    setPreview({
      fabric_cost: rec.fabric_cost, accessories_total: rec.accessories_total,
      material_cost: rec.material_cost,
      cmt_cost: rec.cmt_cost, cutting_cost: rec.cutting_cost,
      packaging_cost: rec.packaging_cost, direct_cost: rec.direct_cost,
      overhead_value: rec.overhead_value, hpp_total: rec.hpp_total,
      selling_price_proposal: rec.selling_price_proposal,
      margin_pct: rec.margin_pct, overhead_pct: rec.overhead_pct,
    });
    setPrevError(''); setEditing(rec.id); setShowForm(true);
    checkStale(rec.id);
  };

  const checkStale = async (id) => {
    setStale(null);
    try {
      const res = await fetch(`${API}/api/dewi/rnd/hpp-calculator/${id}/stale-check`, { headers: hdr });
      if (res.ok) setStale(await res.json());
    } catch { /* ignore */ }
  };

  const setStyleField = (styleId) => {
    const sel = styles.find(s => s.id === styleId);
    setForm(prev => ({ ...prev, style_id: styleId, style_code: sel?.style_code || '', style_name: sel?.style_name || '' }));
    setFabricEst(null);
  };

  // ─────────────────────────── cost lines ───────────────────────────
  const setLine = (i, patch) => setForm(prev => {
    const lines = [...(prev.cost_lines || [])];
    lines[i] = { ...lines[i], ...patch };
    return { ...prev, cost_lines: lines };
  });

  const removeLine = (i) => setForm(prev => ({
    ...prev, cost_lines: (prev.cost_lines || []).filter((_, j) => j !== i),
  }));

  const addManualLine = () => setForm(prev => ({
    ...prev,
    cost_lines: [...(prev.cost_lines || []), {
      line_id: newLineId(), label: '', source: 'manual',
      qty: 1, unit: 'pcs', unit_cost_used: 0, override: false, override_reason: '',
    }],
  }));

  const addMasterLine = () => setForm(prev => ({
    ...prev,
    cost_lines: [...(prev.cost_lines || []), {
      line_id: newLineId(), label: '', source: 'master', material_id: '',
      qty: 1, unit: '', unit_cost_used: 0, override: false, override_reason: '',
    }],
  }));

  const pullFromTechpack = async () => {
    if (!form.style_id) return toast.error('Pilih style dulu untuk menarik BOM tech pack');
    try {
      const res = await fetch(`${API}/api/dewi/rnd/hpp-calculator/cost-lines/from-techpack`, {
        method: 'POST', headers: hdr, body: JSON.stringify({ style_id: form.style_id }),
      });
      if (!res.ok) return toast.error(await readErr(res, 'Gagal menarik BOM tech pack'), { duration: 7000 });
      const d = await res.json();
      const incoming = (d.cost_lines || []).map(l => ({ ...l, line_id: l.line_id || newLineId() }));
      setForm(prev => ({ ...prev, cost_lines: [...(prev.cost_lines || []), ...incoming] }));
      toast.success(`${incoming.length} baris BOM tech pack ditambahkan (sumber: Tech pack)`);
      if (d.unlinked_count > 0) {
        toast.warning(`${d.unlinked_count} baris tidak tertaut master — harganya Rp0. Tautkan materialnya di tech pack, atau ubah sumbernya jadi Manual.`, { duration: 9000 });
      }
    } catch { toast.error('Gagal menarik BOM tech pack'); }
  };

  const applyMasterPrices = () => {
    // buang override → semua baris master/techpack kembali ke harga master terbaru
    setForm(prev => ({
      ...prev,
      cost_lines: (prev.cost_lines || []).map(l => l.source === 'manual'
        ? l : { ...l, override: false, override_reason: '', unit_cost_used: 0 }),
    }));
    toast.success('Semua baris master dikembalikan ke harga master terbaru');
  };

  const setAcc = (idx, field, val) => {
    const acc = [...form.accessories_cost];
    acc[idx] = { ...acc[idx], [field]: ['unit_cost', 'qty'].includes(field) ? Number(val) : val };
    f('accessories_cost', acc);
  };
  const addAcc = () => f('accessories_cost', [...form.accessories_cost, { ...emptyAcc }]);
  const removeAcc = (idx) => f('accessories_cost', form.accessories_cost.filter((_, i) => i !== idx));

  const loadFabricEstimate = async () => {
    if (!form.style_id) { toast.error('Pilih style dulu untuk menghitung kain dari tech pack'); return; }
    setFabricEstLoading(true);
    try {
      const res = await fetch(`${API}/api/dewi/rnd/hpp/fabric-estimate?style_id=${form.style_id}`, { headers: hdr });
      const data = await res.json();
      if (!res.ok) { toast.error(data?.detail || 'Tech pack belum ada untuk style ini'); setFabricEst(null); return; }
      if (!data.sizes || data.sizes.length === 0) { toast.error('Tech pack belum punya data penggunaan bahan'); setFabricEst(null); return; }
      setFabricEst(data);
      if (data.has_unresolved_price) toast.warning('Sebagian harga kain belum diisi di Riset Material (dianggap Rp0).');
      else toast.success('Estimasi kain dimuat dari tech pack');
    } catch { toast.error('Gagal memuat estimasi kain'); }
    finally { setFabricEstLoading(false); }
  };

  const applyFabricSize = (sz) => {
    setForm(prev => ({ ...prev,
      fabric_usage_per_pcs: sz.meters_per_pcs,
      fabric_price_per_meter: sz.weighted_price_per_meter,
      fabric_source: 'techpack', fabric_size: sz.size,
    }));
    toast.success(`Kain ukuran ${sz.size} diterapkan`);
  };

  // ─────────────────────────── save / delete ───────────────────────────
  const handleSave = async (statusOverride) => {
    if (!form.hpp_code) return toast.error('Isi kode HPP');
    const bad = (form.cost_lines || []).find(l =>
      l.override && l.source !== 'manual' && !String(l.override_reason || '').trim());
    if (bad) return toast.error(`Baris "${bad.label || 'tanpa nama'}": harga master ditimpa tapi alasannya belum diisi.`, { duration: 7000 });

    setSaving(true);
    const payload = { ...form, ...(statusOverride ? { status: statusOverride } : {}) };
    try {
      const method = editing ? 'PUT' : 'POST';
      const url = editing
        ? `${API}/api/dewi/rnd/hpp-calculator/${editing}`
        : `${API}/api/dewi/rnd/hpp-calculator`;
      const res = await fetch(url, { method, headers: hdr, body: JSON.stringify(payload) });
      if (!res.ok) { toast.error(await readErr(res, 'Gagal menyimpan HPP'), { duration: 8000 }); return; }
      // 2026-11-06 (Tahap 2): HPP R&D disimpan di dokumen R&D saja — tidak lagi menimpa master/FG/katalog.
      toast.success(`${editing ? 'HPP disimpan' : 'HPP dibuat'} di dokumen R&D. HPP produk ditetapkan lewat HPP per potong.`);
      setShowForm(false);
      loadRecords();
    } catch { toast.error('Gagal menyimpan HPP'); }
    finally { setSaving(false); }
  };

  const handleDelete = async (rec) => {
    const ok = await confirmDialog({
      title: 'Hapus HPP ini?',
      body: `Kalkulasi ${rec.hpp_code || 'HPP'} dihapus permanen.`,
      confirmLabel: 'Hapus', danger: true,
    });
    if (!ok) return;
    try {
      // 2026-11-06 (pola P6): helper lib/api melempar bila server menolak → pesan sukses hanya bila benar tersimpan
      await apiDelete(`/api/dewi/rnd/hpp-calculator/${rec.id}`);
      toast.success('HPP dihapus');
      setDetail(null);
      loadRecords();
    } catch { toast.error('Gagal menghapus'); }
  };

  const computedById = useMemo(() => {
    const m = {};
    (computed || []).forEach(l => { if (l.line_id) m[l.line_id] = l; });
    return m;
  }, [computed]);

  const linesTotal = useMemo(
    () => (computed || []).reduce((a, l) => a + Number(l.line_cost || 0), 0),
    [computed]);

  const staleIds = useMemo(
    () => new Set(((stale?.stale_lines) || []).map(l => l.line_id)), [stale]);

  const sourceMix = (rec) => {
    const set = new Set((rec.cost_lines || []).map(l => l.source));
    return [...set];
  };

  const q = cari.trim().toLowerCase();
  const baris = useMemo(() => (records || []).filter(r => !q
    || `${r.hpp_code || ''} ${r.style_code || ''} ${r.style_name || ''}`.toLowerCase().includes(q)), [records, q]);
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(baris, 10);

  /** HPP yang baris bersumber-masternya sudah tidak sesuai harga master sekarang. */
  const staleRecords = useMemo(
    () => (records || []).filter(r => (r.stale_count || 0) > 0), [records]);

  const kolom = [
    { kunci: 'kode', label: 'Kode HPP', hp: 'judul', isi: (r) => <span className="font-medium text-foreground">{r.hpp_code}</span> },
    { kunci: 'style', label: 'Style', hp: 'keterangan', isi: (r) => (
      <div className="min-w-0">
        <p className="text-foreground">{r.style_code || '—'}</p>
        {r.style_name && <p className="text-xs text-muted-foreground">{r.style_name}</p>}
      </div>) },
    { kunci: 'status', label: 'Status', isi: (r) => <StatusBadge status={r.status} label={statusHpp(r.status).label} tone={statusHpp(r.status).tone} /> },
    { kunci: 'sumber', label: 'Sumber biaya', isi: (r) => (
      <div className="flex flex-wrap gap-1" data-testid={`rnd-hpp-sources-${r.id}`}>
        {sourceMix(r).length === 0 ? <span className="text-xs text-muted-foreground">Manual</span>
          : sourceMix(r).map(s => <StatusBadge key={s} status={s} label={sumberLabel(s)} tone={SOURCES.find(x => x.value === s)?.tone || 'muted'} />)}
        {r.cost_lines_legacy && (r.cost_lines || []).length > 0 && (
          <StatusBadge status="lama" tone="muted" label="Dokumen lama" />
        )}
      </div>) },
    { kunci: 'master', label: 'Harga master', isi: (r) => (
      <span data-testid={`rnd-hpp-stale-cell-${r.id}`}>
        {(r.stale_count || 0) > 0 ? (
          <Button variant="outline" size="sm" onClick={(e) => { e.stopPropagation(); openEdit(r); }}
            title={'Harga master sudah berubah sejak HPP ini dihitung. Angka HPP tersimpan tidak diubah otomatis — buka lalu simpan ulang untuk memakai harga baru.'}
            className="text-[hsl(var(--warning-text))]" data-testid={`rnd-hpp-stale-badge-${r.id}`}>
            <AlertTriangle />{r.stale_count} harga berubah
          </Button>
        ) : (r.stale_checked_lines || 0) > 0 ? (
          <span className="inline-flex items-center gap-1 text-xs text-[hsl(var(--success-text))]"
            title={`${r.stale_checked_lines} baris bersumber master — semuanya masih sesuai harga master sekarang`}
            data-testid={`rnd-hpp-stale-ok-${r.id}`}>
            <CheckCircle2 className="h-3.5 w-3.5 shrink-0" /> Sesuai master
          </span>
        ) : (
          <span className="text-muted-foreground"
            title="Tidak ada baris bersumber master untuk dibandingkan (semua manual / dokumen lama)">—</span>
        )}
      </span>) },
    { kunci: 'langsung', label: 'Biaya langsung', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmt(r.direct_cost)}</span> },
    { kunci: 'hpp', label: 'HPP/pcs', rata: 'kanan', isi: (r) => (
      <span className="tabular-nums font-semibold text-foreground"
        title={aturanLama(r) ? 'Dokumen lama: HPP tersimpan masih memuat cutting/overhead' : 'Bahan + kemasan + ongkos CMT'}>
        {fmt(r.hpp_total)}{aturanLama(r) && <span className="block text-xs font-normal text-[hsl(var(--warning-text))]">aturan lama</span>}
      </span>) },
    { kunci: 'jual', label: 'Usulan harga jual', rata: 'kanan', isi: (r) => <span className="tabular-nums font-medium">{fmt(r.selling_price_proposal)}</span> },
    { kunci: 'margin', label: 'Margin', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtPersen(r.margin_pct)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <div className="flex justify-end gap-1">
        <Button variant="ghost" size="icon-sm" onClick={() => openEdit(r)} title="Ubah" aria-label="Ubah"
          data-testid={`rnd-hpp-edit-${r.id}`}><Pencil /></Button>
        <Button variant="ghost" size="icon-sm" onClick={() => handleDelete(r)} title="Hapus" aria-label="Hapus"
          data-testid={`rnd-hpp-del-${r.id}`}><Trash2 className="text-[hsl(var(--danger-text))]" /></Button>
      </div>) },
  ];

  const unduhKolom = [
    { label: 'Kode HPP', nilai: (r) => r.hpp_code || '' },
    { label: 'Kode style', nilai: (r) => r.style_code || '' },
    { label: 'Nama style', nilai: (r) => r.style_name || '' },
    { label: 'Status', nilai: (r) => statusHpp(r.status).label },
    { label: 'Sumber biaya', nilai: (r) => (sourceMix(r).map(sumberLabel).join(', ') || 'Manual') },
    { label: 'Baris harga master berubah', nilai: (r) => Number(r.stale_count || 0) },
    { label: 'Biaya bahan (Rp)', nilai: (r) => Number(r.material_cost || 0) },
    { label: 'Ongkos CMT (Rp)', nilai: (r) => Number(r.cmt_cost || 0) },
    { label: 'Kemasan (Rp)', nilai: (r) => Number(r.packaging_cost || 0) },
    { label: 'Biaya langsung (Rp)', nilai: (r) => Number(r.direct_cost || 0) },
    { label: 'Cutting di luar HPP (Rp)', nilai: (r) => Number(r.cutting_cost || 0) },
    { label: 'Overhead di luar HPP (Rp)', nilai: (r) => Number(r.overhead_value || 0) },
    { label: 'HPP per pcs (Rp)', nilai: (r) => Number(r.hpp_total || 0) },
    { label: 'Usulan harga jual (Rp)', nilai: (r) => Number(r.selling_price_proposal || 0) },
    { label: 'Margin (%)', nilai: (r) => Number(r.margin_pct || 0) },
    { label: 'Dibuat', nilai: (r) => (r.created_at ? formatDateID(r.created_at) : '') },
    { label: 'Catatan', nilai: (r) => r.notes || '' },
  ];

  return (
    <PageLayout testId="rnd-hpp-module" title="Kalkulator HPP"
      subtitle="Biaya bahan bersumber per baris — master, tech pack, dan manual boleh bercampur."
      actions={<Button onClick={openNew} data-testid="rnd-hpp-add-btn"><Plus />Hitung HPP baru</Button>}
      filters={records.length > 0 && (
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={cari} onChange={e => setCari(e.target.value)} placeholder="Cari kode HPP atau style"
            className="pl-8" data-testid="rnd-hpp-search" />
        </div>
      )}
      tools={<>
        <TombolUnduh namaBerkas="kalkulator-hpp" namaLembar="HPP" baris={baris} kolom={unduhKolom} testId="rnd-hpp-unduh" />
        <Button variant="outline" size="icon" onClick={loadRecords} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={staleRecords.length > 0 && (
        // Peringatan harga master basi — di DAFTAR, bukan hanya di dalam form (dulu stale-check hanya jalan
        // saat form Ubah dibuka, jadi HPP yang harganya basi tidak kelihatan sampai dibuka satu per satu).
        <Notice tone="warning" icon={AlertTriangle} testId="rnd-hpp-stale-list-banner"
          title={`${staleRecords.length} HPP memakai harga master yang sudah berubah`}>
          <p>Angka yang tersimpan <b>tidak diubah otomatis</b>. Buka HPP-nya lalu simpan ulang bila ingin memakai harga master terbaru.</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {staleRecords.map(r => (
              <Button key={r.id} size="sm" variant="outline" onClick={() => openEdit(r)}
                data-testid={`rnd-hpp-stale-jump-${r.id}`}>
                {r.hpp_code} · {r.stale_count} baris
              </Button>
            ))}
          </div>
        </Notice>
      )}
      footer={total > pageSize && (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />
      )}>
      {loading && records.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat kalkulasi HPP…</p>
      ) : (
        <TabelData kolom={kolom} baris={paged} onKlikBaris={setDetail} testId="rnd-hpp-table"
          kosong={<EmptyState icon={Calculator}
            title={records.length ? 'Tidak ada HPP yang cocok' : 'Belum ada kalkulasi HPP'}
            description={records.length ? 'Ubah kata pencarian.' : 'Hitung HPP pertama dari BOM tech pack, master material, atau isian manual.'}
            action={!records.length && <Button onClick={openNew}><Plus />Hitung HPP baru</Button>} />} />
      )}

      {/* ───────────────────── Rincian (popup) ───────────────────── */}
      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} testId="rnd-hpp-detail"
          judul={detail.hpp_code}
          keterangan={[detail.style_code, detail.style_name].filter(Boolean).join(' · ') || undefined}
          status={<StatusBadge status={detail.status} label={statusHpp(detail.status).label} tone={statusHpp(detail.status).tone} />}
          aksi={<>
            <Button size="sm" variant="outline" onClick={() => openEdit(detail)}><Pencil />Ubah</Button>
            <Button size="sm" variant="destructive" onClick={() => handleDelete(detail)}><Trash2 />Hapus</Button>
          </>}>
          {(detail.stale_count || 0) > 0 && (
            <Notice tone="warning" icon={History} title={`${detail.stale_count} baris memakai harga master yang sudah berubah`}>
              <ul className="space-y-0.5">
                {(detail.stale_lines || []).map(l => (
                  <li key={l.line_id}>{l.label || l.material_code || 'Baris'}: {fmt(l.unit_cost_snapshot)} → {fmt(l.unit_cost_now)}</li>
                ))}
              </ul>
            </Notice>
          )}
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Biaya bahan">{fmt(detail.material_cost)}</BarisDetail>
            <BarisDetail label="Ongkos CMT">{fmt(detail.cmt_cost)}</BarisDetail>
            <BarisDetail label="Kemasan">{fmt(detail.packaging_cost)}</BarisDetail>
            <BarisDetail label="Biaya langsung">{fmt(detail.direct_cost)}</BarisDetail>
            <BarisDetail label="Cutting">{fmt(detail.cutting_cost)} <span className="text-muted-foreground">(di luar HPP)</span></BarisDetail>
            <BarisDetail label="Overhead">{fmt(detail.overhead_value)} <span className="text-muted-foreground">({fmtPersen(detail.overhead_pct)}, di luar HPP)</span></BarisDetail>
            <BarisDetail label="HPP per pcs">
              <span className="font-semibold">{fmt(detail.hpp_total)}</span>{' '}
              <span className="text-muted-foreground">
                {aturanLama(detail) ? '(dokumen lama: masih memuat cutting/overhead)' : '(bahan + kemasan + ongkos CMT)'}
              </span>
            </BarisDetail>
            <BarisDetail label="Usulan harga jual">{fmt(detail.selling_price_proposal)} <span className="text-muted-foreground">(margin {fmtPersen(detail.margin_pct)} dari harga jual)</span></BarisDetail>
            {detail.created_at && <BarisDetail label="Dibuat">{formatDateID(detail.created_at)}</BarisDetail>}
            {detail.notes && <BarisDetail label="Catatan">{detail.notes}</BarisDetail>}
          </dl>
          {(detail.cost_lines || []).length > 0 && (
            <div className="space-y-2">
              <p className="text-sm font-semibold text-foreground">Baris biaya bahan</p>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Baris</TableHead>
                    <TableHead>Sumber</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead className="text-right">Harga dipakai</TableHead>
                    <TableHead className="text-right">Biaya</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {detail.cost_lines.map((l, i) => (
                    <TableRow key={l.line_id || i}>
                      <TableCell>
                        {l.label || l.material_name || '—'}
                        {l.override && <span className="block text-xs text-[hsl(var(--warning-text))]">Harga ditimpa: {l.override_reason || '—'}</span>}
                      </TableCell>
                      <TableCell>{sumberLabel(l.source)}</TableCell>
                      <TableCell className="text-right tabular-nums">{l.qty} {l.unit}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmt(l.unit_cost_used)}</TableCell>
                      <TableCell className="text-right tabular-nums font-medium">{fmt(l.line_cost)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </DetailPopup>
      )}

      {/* ───────────────────── Form HPP (popup standar, panjang) ───────────────────── */}
      <FormPopup open={showForm} onClose={() => setShowForm(false)} ukuran="panjang"
        judul={editing ? 'Ubah HPP' : 'Hitung HPP baru'}
        keterangan="Semua angka dihitung server. HPP = bahan + kemasan + ongkos CMT; cutting & overhead di luar HPP."
        onSimpan={() => handleSave('approved')} labelSimpan="Simpan & setujui" menyimpan={saving}
        aksiKiri={<Button type="button" variant="outline" disabled={saving} onClick={() => handleSave('draft')}
          data-testid="rnd-hpp-save-draft-btn">Simpan draf</Button>}
        testId="rnd-hpp-form">
        {/* Enter di kolom isian TIDAK menyimpan/menyetujui (sama seperti sebelumnya) — form ini punya banyak baris. */}
        <div className="space-y-5" onKeyDown={e => { if (e.key === 'Enter' && e.target.tagName === 'INPUT') e.preventDefault(); }}>
          {/* Ringkasan hasil — tetap terlihat saat form digulir */}
          <div className="sticky top-0 z-10 -mx-5 -mt-4 flex flex-wrap items-center gap-x-5 gap-y-1 border-b border-[var(--glass-border)] bg-background px-5 py-2 text-sm"
            data-testid="hpp-preview-strip">
            <span className="text-muted-foreground">HPP/pcs <b className="tabular-nums text-foreground">{fmt(preview.hpp_total)}</b></span>
            <span className="text-muted-foreground">Usulan harga jual <b className="tabular-nums text-foreground">{fmt(preview.selling_price_proposal)}</b></span>
            {prevLoading && <span className="inline-flex items-center gap-1 text-xs text-muted-foreground"><RefreshCw className="h-3 w-3 animate-spin" />Menghitung…</span>}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Isian label="Kode HPP" wajib htmlFor="hpp-code">
              <Input id="hpp-code" value={form.hpp_code}
                onChange={e => f('hpp_code', e.target.value)} data-testid="hpp-code-input" />
            </Isian>
            <Isian label="Style" petunjuk="Opsional. Dibutuhkan untuk menarik BOM tech pack.">
              <SmartNativeSelect value={form.style_id} onChange={e => setStyleField(e.target.value)}
                data-testid="hpp-style-select" className="w-full">
                <option value="">Pilih style</option>
                {styles.map(s => <option key={s.id} value={s.id}>{`${s.style_code} — ${s.style_name}`}</option>)}
              </SmartNativeSelect>
            </Isian>
          </div>

          {/* ── F4: Biaya bahan — sumber PER BARIS ── */}
          <section className="space-y-3" data-testid="hpp-cost-lines-card">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="text-sm font-semibold text-foreground">Biaya bahan — sumber per baris</p>
                <p className="text-xs text-muted-foreground">Master, tech pack, dan manual boleh bercampur. Total = jumlah semua baris.</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button type="button" variant="outline" size="sm" onClick={pullFromTechpack} data-testid="hpp-pull-techpack">
                  <Wand2 />Tarik dari BOM tech pack
                </Button>
                <Button type="button" variant="outline" size="sm" onClick={addMasterLine} data-testid="hpp-add-master-line">
                  <Database />Baris master
                </Button>
                <Button type="button" variant="outline" size="sm" onClick={addManualLine} data-testid="hpp-add-manual-line">
                  <PenLine />Baris manual
                </Button>
              </div>
            </div>

            {prevError && (
              <Notice tone="danger" icon={AlertTriangle} testId="hpp-preview-error">{prevError}</Notice>
            )}

            {stale && stale.stale_count > 0 && (
              <Notice tone="warning" icon={History} testId="hpp-stale-banner"
                title={`${stale.stale_count} baris memakai harga master yang sudah berubah`}
                action={<Button type="button" variant="outline" size="sm" onClick={applyMasterPrices}
                  data-testid="hpp-refresh-master-prices">Pakai harga master terbaru</Button>}>
                <p>Angka tersimpan tidak diubah otomatis — perbarui bila setuju.</p>
                <ul className="mt-1 space-y-0.5">
                  {stale.stale_lines.slice(0, 4).map(l => (
                    <li key={l.line_id}>{l.label}: {fmt(l.unit_cost_snapshot)} → {fmt(l.unit_cost_now)}</li>
                  ))}
                </ul>
              </Notice>
            )}

            {!hybrid ? (
              <p className="text-sm text-muted-foreground">
                Belum ada baris biaya. Mode lama (kain + aksesoris manual di bawah) masih dipakai —
                tambahkan baris di atas untuk memakai mode campuran.
              </p>
            ) : (
              <div className="space-y-2" data-testid="hpp-cost-lines-table">
                {(form.cost_lines || []).map((l, i) => {
                  const c = computedById[l.line_id] || {};
                  const isManual = l.source === 'manual';
                  const unlinked = !isManual && c.master_linked === false;
                  const isStale = staleIds.has(l.line_id);
                  const reasonEmpty = !String(l.override_reason || '').trim();
                  return (
                    <div key={l.line_id} data-testid={`hpp-line-${i}`}
                      className={cn('space-y-2 rounded-[var(--radius-md)] border p-2.5',
                        unlinked ? 'border-[hsl(var(--destructive)/0.4)] bg-[hsl(var(--destructive)/0.05)]' : 'border-[var(--glass-border)]')}>
                      <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 sm:grid-cols-[minmax(0,1fr)_120px_minmax(0,1.4fr)_36px]">
                        <div className="col-span-2 sm:col-span-1">
                          <Lbl>Baris biaya</Lbl>
                          <Input value={l.label || ''} onChange={e => setLine(i, { label: e.target.value })}
                            placeholder="Nama baris" data-testid={`hpp-line-label-${i}`} />
                        </div>
                        <div>
                          <Lbl>Sumber</Lbl>
                          <SmartNativeSelect value={l.source} searchable={false}
                            onChange={e => setLine(i, { source: e.target.value,
                              ...(e.target.value === 'manual' ? { material_id: '', override: false, override_reason: '' } : {}) })}
                            data-testid={`hpp-line-source-${i}`} className="w-full">
                            {SOURCES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
                          </SmartNativeSelect>
                        </div>
                        <div className="flex items-end justify-end sm:order-last">
                          <Button type="button" variant="ghost" size="icon" onClick={() => removeLine(i)}
                            title="Hapus baris" aria-label="Hapus baris" data-testid={`hpp-line-del-${i}`}>
                            <X className="text-[hsl(var(--danger-text))]" />
                          </Button>
                        </div>
                        <div className="col-span-2 min-w-0 sm:col-span-1">
                          <Lbl>Master material</Lbl>
                          {isManual ? (
                            <p className="py-2 text-sm text-muted-foreground">Isian bebas — nama &amp; harga sendiri</p>
                          ) : (
                            <>
                              <SmartNativeSelect value={l.material_id || ''}
                                onChange={e => {
                                  const opt = matOpts.find(m => m.material_id === e.target.value);
                                  setLine(i, { material_id: e.target.value,
                                    material_code: opt?.code || '',
                                    material_name: opt?.name || '',
                                    label: l.label || opt?.name || '',
                                    unit: l.unit || opt?.base_unit || '' });
                                }}
                                data-testid={`hpp-line-material-${i}`} className="w-full">
                                <option value="">Pilih master material…</option>
                                {matOpts.map(m => <option key={m.material_id} value={m.material_id}>{`${m.code} — ${m.name} (${m.base_unit})`}</option>)}
                              </SmartNativeSelect>
                              {unlinked && (
                                <p className="mt-1 flex items-start gap-1 text-xs text-[hsl(var(--danger-text))]"
                                  data-testid={`hpp-line-unlinked-${i}`}>
                                  <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                                  <span>Tanpa master: harga &amp; konversi satuan tidak dihitung.</span>
                                </p>
                              )}
                            </>
                          )}
                        </div>
                      </div>
                      <div className="grid grid-cols-2 gap-2 sm:grid-cols-[80px_96px_minmax(0,1fr)_minmax(0,1.3fr)_minmax(0,1fr)]">
                        <div>
                          <Lbl>Qty</Lbl>
                          <Input type="number" step="0.01" value={l.qty ?? 1}
                            onChange={e => setLine(i, { qty: Number(e.target.value) })}
                            className="text-right" data-testid={`hpp-line-qty-${i}`} />
                        </div>
                        <div>
                          <Lbl>Satuan</Lbl>
                          <Input value={l.unit || ''} onChange={e => setLine(i, { unit: e.target.value })}
                            placeholder="pcs" data-testid={`hpp-line-unit-${i}`} />
                        </div>
                        <div>
                          <Lbl>Harga master</Lbl>
                          {isManual ? <p className="py-2 text-sm text-muted-foreground">—</p> : (
                            <p className={cn('py-2 text-sm tabular-nums', isStale ? 'font-medium text-[hsl(var(--warning-text))]' : 'text-muted-foreground')}>
                              {fmt(c.unit_cost_master)}
                              {isStale && <AlertTriangle className="ml-1 -mt-0.5 inline h-3 w-3" aria-label="Harga master berubah" />}
                            </p>
                          )}
                        </div>
                        <div className="sm:order-last">
                          <Lbl>Biaya</Lbl>
                          <p className="py-2 text-right text-sm font-semibold tabular-nums text-foreground"
                            data-testid={`hpp-line-cost-${i}`}>{fmt(c.line_cost)}</p>
                        </div>
                        <div className="col-span-2 sm:col-span-1">
                          <Lbl>Harga dipakai</Lbl>
                          {isManual || l.override ? (
                            <MoneyInput decimals={2} value={l.unit_cost_used ?? 0}
                              onChange={e => setLine(i, { unit_cost_used: Number(e.target.value) })}
                              className="text-right" data-testid={`hpp-line-price-${i}`} />
                          ) : (
                            <p className="py-2 text-right text-sm font-medium tabular-nums text-foreground">{fmt(c.unit_cost_used)}</p>
                          )}
                          {!isManual && (
                            <label className="mt-1 flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
                              <Checkbox checked={!!l.override}
                                onCheckedChange={(v) => {
                                  const on = v === true;
                                  setLine(i, { override: on,
                                    unit_cost_used: on ? (c.unit_cost_master || 0) : 0,
                                    ...(on ? {} : { override_reason: '' }) });
                                }}
                                data-testid={`hpp-line-override-${i}`} />
                              Timpa harga master
                            </label>
                          )}
                          {!isManual && l.override && (
                            <Input value={l.override_reason || ''}
                              onChange={e => setLine(i, { override_reason: e.target.value })}
                              placeholder="Alasan menimpa harga (wajib)"
                              aria-invalid={reasonEmpty}
                              className={cn('mt-1', reasonEmpty && 'border-[hsl(var(--destructive))]')}
                              data-testid={`hpp-line-reason-${i}`} />
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
                <div className="flex items-center justify-end gap-3 pt-1 text-sm">
                  <span className="text-muted-foreground">Total biaya bahan ({(form.cost_lines || []).length} baris)</span>
                  <span className="font-semibold tabular-nums text-primary" data-testid="hpp-cost-lines-total">{fmt(linesTotal)}</span>
                </div>
              </div>
            )}
          </section>

          {/* Mode lama — hanya ditampilkan bila belum ada baris biaya */}
          {!hybrid && (
            <>
              <section className="space-y-3 border-t border-[var(--glass-border)] pt-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-foreground">
                    Bahan kain (mode lama)
                    {form.fabric_source === 'techpack' && (
                      <StatusBadge status="techpack" tone="primary" label={`Dari tech pack${form.fabric_size ? ` · ${form.fabric_size}` : ''}`} />
                    )}
                  </p>
                  <Button type="button" variant="outline" size="sm" onClick={loadFabricEstimate}
                    disabled={fabricEstLoading} data-testid="hpp-fabric-from-techpack">
                    <Wand2 />{fabricEstLoading ? 'Memuat…' : 'Hitung dari tech pack'}
                  </Button>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Isian label="Pemakaian kain/pcs (meter)">
                    <Input type="number" step="0.01" value={form.fabric_usage_per_pcs}
                      onChange={e => { f('fabric_usage_per_pcs', Number(e.target.value)); f('fabric_source', 'manual'); }} />
                  </Isian>
                  <Isian label="Harga kain/meter (Rp)">
                    <MoneyInput decimals={2} value={form.fabric_price_per_meter}
                      onChange={e => { f('fabric_price_per_meter', Number(e.target.value)); f('fabric_source', 'manual'); }} />
                  </Isian>
                </div>
                <p className="text-xs text-muted-foreground">
                  Biaya kain = {form.fabric_usage_per_pcs} m × {fmt(Number(form.fabric_price_per_meter))} = <b className="text-foreground">{fmt(form.fabric_usage_per_pcs * form.fabric_price_per_meter)}</b>
                </p>

                {fabricEst && fabricEst.sizes?.length > 0 && (
                  <div className="space-y-2" data-testid="hpp-fabric-estimate-panel">
                    <p className="text-xs text-muted-foreground">
                      Estimasi tech pack <b>{fabricEst.style_code}</b> — klik ukuran untuk dipakai.
                      {fabricEst.has_unresolved_price && <span className="ml-1 text-[hsl(var(--warning-text))]">Sebagian harga Rp0 — isi di Riset Material.</span>}
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {fabricEst.sizes.map(sz => {
                        const dipilih = form.fabric_size === sz.size && form.fabric_source === 'techpack';
                        return (
                          <Button key={sz.size} type="button" size="sm" variant={dipilih ? 'default' : 'outline'}
                            className="h-auto whitespace-normal py-1.5 text-left" onClick={() => applyFabricSize(sz)}>
                            <b>{sz.size}</b>: {sz.meters_per_pcs} m × {fmt(Number(sz.weighted_price_per_meter))} = {fmt(sz.fabric_cost_per_pcs)}
                          </Button>
                        );
                      })}
                    </div>
                  </div>
                )}
              </section>

              <section className="space-y-3 border-t border-[var(--glass-border)] pt-4">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-sm font-semibold text-foreground">Aksesoris (mode lama)</p>
                  <Button type="button" variant="outline" size="sm" onClick={addAcc}><Plus />Tambah</Button>
                </div>
                {form.accessories_cost.length > 0 && (
                  <div className="hidden gap-2 text-xs text-muted-foreground sm:grid sm:grid-cols-[minmax(0,1fr)_120px_80px_36px]">
                    <span>Nama item</span><span>Harga/unit</span><span>Qty</span><span />
                  </div>
                )}
                {form.accessories_cost.map((acc, i) => (
                  <div key={i} className="grid grid-cols-[minmax(0,1fr)_96px_64px_36px] gap-2 sm:grid-cols-[minmax(0,1fr)_120px_80px_36px]">
                    <Input value={acc.name} onChange={e => setAcc(i, 'name', e.target.value)} placeholder="Nama item" />
                    <MoneyInput decimals={2} value={acc.unit_cost}
                      onChange={e => setAcc(i, 'unit_cost', e.target.value)} placeholder="Harga/unit" />
                    <Input type="number" value={acc.qty} min="1"
                      onChange={e => setAcc(i, 'qty', e.target.value)} placeholder="Qty" />
                    <Button type="button" variant="ghost" size="icon" onClick={() => removeAcc(i)}
                      title="Hapus item" aria-label="Hapus item">
                      <X className="text-[hsl(var(--danger-text))]" />
                    </Button>
                  </div>
                ))}
              </section>
            </>
          )}

          {/* Biaya proses */}
          <section className="space-y-3 border-t border-[var(--glass-border)] pt-4">
            <p className="text-sm font-semibold text-foreground">Biaya proses per pcs</p>
            <div className="grid gap-3 sm:grid-cols-3">
              <Isian label="Ongkos CMT (Rp)">
                <MoneyInput value={form.cmt_cost_per_pcs}
                  onChange={e => setForm(p => ({ ...p, cmt_cost_per_pcs: Number(e.target.value), cmt_cost_source: 'manual', cmt_cost_ref: '' }))}
                  data-testid="hpp-cmt-input" />
                {cmtOpts.length > 0 && (
                  <SmartNativeSelect value={form.cmt_cost_ref || ''}
                    onChange={e => {
                      const opt = cmtOpts.find(o => o.catalog_id === e.target.value);
                      if (!opt) return;
                      setForm(p => ({ ...p, cmt_cost_per_pcs: opt.cmt_price,
                        cmt_cost_source: 'catalog', cmt_cost_ref: opt.catalog_id }));
                      toast.success(`Ongkos CMT dari master katalog ${opt.code}: ${formatRupiah(opt.cmt_price)}`);
                    }}
                    data-testid="hpp-cmt-catalog" className="mt-1 w-full">
                    <option value="">Ambil dari master katalog buyer…</option>
                    {cmtOpts.map(o => (
                      <option key={o.catalog_id} value={o.catalog_id}>{`${o.code} — ${o.name} · ${formatRupiah(o.cmt_price)}`}</option>
                    ))}
                  </SmartNativeSelect>
                )}
                {form.cmt_cost_source === 'catalog' && (
                  <p className="mt-1 flex items-center gap-1 text-xs text-[hsl(var(--info-text))]">
                    <CheckCircle2 className="h-3 w-3" /> Dari master katalog buyer
                  </p>
                )}
              </Isian>
              <Isian label="Biaya cutting (Rp)" petunjuk="Tidak masuk HPP.">
                <MoneyInput value={form.cutting_cost_per_pcs}
                  onChange={e => f('cutting_cost_per_pcs', Number(e.target.value))} />
              </Isian>
              <Isian label="Kemasan per pcs (Rp)">
                <MoneyInput value={form.packaging_cost_per_pcs}
                  onChange={e => f('packaging_cost_per_pcs', Number(e.target.value))} />
              </Isian>
            </div>
          </section>

          {/* Overhead & margin */}
          <section className="space-y-3 border-t border-[var(--glass-border)] pt-4">
            <p className="text-sm font-semibold text-foreground">Overhead & target margin</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <Isian label="Overhead (%)" petunjuk="Informasi saja, tidak masuk HPP — overhead pabrik tetap beban bulanan.">
                <Input type="number" step="0.5" value={form.overhead_pct}
                  onChange={e => f('overhead_pct', Number(e.target.value))} />
              </Isian>
              <Isian label="Target margin (%)" petunjuk="Dihitung dari harga jual.">
                <Input type="number" step="0.5" value={form.margin_pct}
                  onChange={e => f('margin_pct', Number(e.target.value))} />
              </Isian>
            </div>
          </section>

          <Isian label="Catatan" htmlFor="hpp-notes">
            <Textarea id="hpp-notes" rows={2} value={form.notes} onChange={e => f('notes', e.target.value)} />
          </Isian>

          {/* Hasil kalkulasi (dari server) */}
          <section className="space-y-1 rounded-[var(--radius-md)] border border-[var(--glass-border)] bg-[var(--card-surface)] p-4"
            data-testid="hpp-preview-panel">
            <p className="flex items-center gap-2 pb-1 text-sm font-semibold text-foreground">
              Hasil kalkulasi
              {prevLoading && <RefreshCw className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
            </p>
            {hybrid ? (
              <BarisHasil label={`Biaya bahan (${(form.cost_lines || []).length} baris)`} nilai={fmt(preview.material_cost)} testId="hpp-preview-material" />
            ) : (
              <>
                <BarisHasil label="Biaya kain" nilai={fmt(preview.fabric_cost)} />
                <BarisHasil label="Biaya aksesoris" nilai={fmt(preview.accessories_total)} />
              </>
            )}
            <BarisHasil label="Ongkos CMT" nilai={fmt(preview.cmt_cost)} />
            <BarisHasil label="Kemasan" nilai={fmt(preview.packaging_cost)} />
            <div className="border-t border-[var(--glass-border)] pt-1">
              <BarisHasil label="Biaya langsung (masuk HPP)" nilai={fmt(preview.direct_cost)} tebal />
              <BarisHasil label="Biaya cutting — tidak masuk HPP" nilai={fmt(preview.cutting_cost)} redup />
              <BarisHasil label={`Overhead (${fmtPersen(preview.overhead_pct)}) — tidak masuk HPP`} nilai={fmt(preview.overhead_value)} redup />
            </div>
            <div className="border-t border-[var(--glass-border)] pt-1">
              <BarisHasil label="HPP / pcs" nilai={fmt(preview.hpp_total)} tebal testId="hpp-preview-total" />
              <BarisHasil label={`Usulan harga jual (margin ${fmtPersen(preview.margin_pct)} dari harga jual)`}
                nilai={<span className="text-base font-semibold text-primary">{fmt(preview.selling_price_proposal)}</span>} />
            </div>
            {hybrid && (
              <div className="flex flex-wrap items-center gap-1 pt-1 text-xs text-muted-foreground">
                Sumber baris:
                {[...new Set((form.cost_lines || []).map(l => l.source))].map(s => (
                  <StatusBadge key={s} status={s} label={sumberLabel(s)} tone={SOURCES.find(x => x.value === s)?.tone || 'muted'} />
                ))}
              </div>
            )}
          </section>
        </div>
      </FormPopup>
    </PageLayout>
  );
}

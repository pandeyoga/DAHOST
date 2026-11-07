/**
 * Tech pack (Portal RnD › Style & Desain › tab "Tech Pack").
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, daftar kartu → tabel (kartu ringkas di HP) + unduh Excel/CSV,
 * rincian (kain, colorway, konstruksi, penggunaan bahan, BOM, ukuran) = popup, form & impor Excel = FormPopup
 * panjang, hapus lewat confirmDialog, status = StatusBadge, warna token, label Indonesia.
 * Hanya tampilan yang berubah — API, isian, aturan kolom ukuran (col_id stabil), dan impor sama seperti sebelumnya.
 */
import { useState, useEffect, useRef } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  FileText, Plus, Trash2, Pencil, Search, CheckCircle2, ChevronUp, ChevronDown, MoreHorizontal, RefreshCw,
  ExternalLink, X, Upload, AlertTriangle,
} from 'lucide-react';
import { toast } from '../ui/sonner';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { cn } from '@/lib/utils';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';
import RnDUnitSelect, { UOM_STATUS } from './RnDUnitSelect';
import { ColorSelect, ColorMultiSelect, useColorOptions } from './RnDColorPicker';
import { apiPost, apiDelete } from '@/lib/api';

const API = process.env.REACT_APP_BACKEND_URL || '';

const STATUS_CONF = {
  draft:      { label: 'Draf',       tone: 'warning' },
  approved:   { label: 'Disetujui',  tone: 'success' },
  superseded: { label: 'Digantikan', tone: 'muted' },
};
const statusTp = (s) => STATUS_CONF[s] || STATUS_CONF.draft;
const peranKain = (r) => (r === 'main' ? 'Utama' : 'Kombinasi');
/** Baris BOM yang belum tertaut master (dihitung server: `master_linked`). */
const bomTanpaMaster = (tp) => (tp.bom_unlinked_count || 0);

/** Label kecil di atas isian baris BOM. */
const Lbl = ({ children }) => <span className="mb-1 block text-xs text-muted-foreground">{children}</span>;

const emptyBOM = { material: '', spec: '', qty: 0, unit: 'meter', supplier: '', material_id: '', color_id: '', color_code: '', color_name: '', color_hex: '' };
const emptyCP = { seq: 0, title: '', description: '' };
const emptyFab = { name: '', role: 'main', color_id: '', color_code: '', color_name: '', color_hex: '' };
const emptyCons = { size: '', fabric_role: 'main', length_cm: '', width_cm: '', yield_pcs: '' };
const DEFAULT_SIZE_COLS = ['S', 'M', 'L', 'XL', 'XXL'];

/** F3/C3 — kolom ukuran selalu `[{col_id,label}]`. `col_id` STABIL: mengganti
 *  label tidak boleh lagi membuat nilai measurement yatim (bug §2.3.3). */
let _colSeq = 0;
const newColId = () => `col_new_${Date.now().toString(36)}_${_colSeq++}`;

function normSizeCols(raw) {
  const out = [];
  (raw || []).forEach((c) => {
    if (c && typeof c === 'object') {
      out.push({ col_id: c.col_id || newColId(), label: String(c.label ?? c.name ?? c.size ?? '') });
    } else if (String(c ?? '').trim()) {
      out.push({ col_id: newColId(), label: String(c).trim() });
    }
  });
  return out;
}

const emptyForm = {
  style_id: '', style_code: '', style_name: '',
  version: 'v1', title: '', description: '',
  doc_url: '', doc_type: 'pdf',
  bom_items: [{ ...emptyBOM }],
  fabrics: [{ ...emptyFab }],
  fabric_consumption: [],
  construction_points: [],
  construction_notes: '', stitch_type: '', seam_allowance_mm: 10,
  size_grading_notes: '', base_size: 'M', size_range: 'S-XL',
  size_columns: DEFAULT_SIZE_COLS.map((c, i) => ({ col_id: `col_seed_${i}`, label: c })),
  colorways: [],
  fit_categories: [],
  measurements: [],
  status: 'draft',
};

/** Nilai measurement dikunci `col_id`. Menerima 3 bentuk lama tanpa kehilangan:
 *   a) values sudah ber-col_id            → dipakai
 *   b) values ber-NAMA kolom              → dipetakan ke col_id
 *   c) baris pipih {point, S:'50', M:'52'} → dibaca sebagai nama kolom
 *  Kunci yang kolomnya sudah hilang disimpan di `orphan_values` (tidak dibuang). */
function normMeasurements(rows, sizeCols) {
  const cols = normSizeCols(sizeCols);
  const ids = new Set(cols.map(c => c.col_id));
  const byLabel = {};
  cols.forEach(c => { if (c.label) byLabel[c.label.toUpperCase()] = c.col_id; });
  const reserved = new Set(['point', 'values', 'values_legacy', 'orphan_values', 'note', 'notes', 'seq', 'unit', 'tolerance']);

  return (rows || []).map(m => {
    const src = {};
    if (m && m.values && typeof m.values === 'object' && Object.keys(m.values).length) {
      Object.assign(src, m.values);
    } else if (m && m.values_legacy && typeof m.values_legacy === 'object') {
      Object.assign(src, m.values_legacy);
    } else if (m) {
      Object.keys(m).forEach(k => {
        if (!reserved.has(k) && m[k] != null && m[k] !== '' && typeof m[k] !== 'object') src[k] = m[k];
      });
    }
    const values = {};
    const orphans = { ...(m?.orphan_values || {}) };
    Object.entries(src).forEach(([k, v]) => {
      if (v == null || v === '') return;
      if (ids.has(k)) values[k] = v;
      else if (byLabel[String(k).toUpperCase()]) values[byLabel[String(k).toUpperCase()]] = v;
      else orphans[k] = v;
    });
    const row = { point: (m && m.point) || '', values };
    if (Object.keys(orphans).length) row.orphan_values = orphans;
    return row;
  });
}

export default function RnDTechPackModule({ token }) {
  const h = { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` };
  const { colors: colorOpts, addColor } = useColorOptions();
  // F2: SATU daftar ukuran per style — dipakai base_size, size_range, dan
  // dropdown ukuran pada Penggunaan Bahan (menutup penyimpangan §2.3.2).
  const [styleSizes, setStyleSizes] = useState({ size_list: [], unmatched: [], size_range: '', base_size: '' });
  const hMultipart = { Authorization: `Bearer ${token}` }; // no Content-Type → browser sets boundary
  const [techPacks, setTechPacks] = useState([]);
  const [styles,    setStyles]    = useState([]);
  const [matOpts,   setMatOpts]   = useState([]);
  const [loading,   setLoading]   = useState(false);
  const [search,    setSearch]    = useState('');
  const [filterStyle, setFilterStyle] = useState('');
  const [showForm,  setShowForm]  = useState(false);
  const [editing,   setEditing]   = useState(null);
  const [form,      setForm]      = useState({ ...emptyForm });
  const [detail,    setDetail]    = useState(null);
  const [tab,       setTab]       = useState('info'); // info | konstruksi | bahan | bom | measurements

  // Import Excel state
  const [showImport, setShowImport] = useState(false);
  const [importPreview, setImportPreview] = useState(null);
  const [importSummary, setImportSummary] = useState(null);
  const [importBusy, setImportBusy] = useState(false);
  const fileRef = useRef(null);
  const [pickedFileName, setPickedFileName] = useState('');

  const f = (k, v) => setForm(p => ({ ...p, [k]: v }));

  const loadTechPacks = async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      if (filterStyle) qs.set('style_id', filterStyle);
      if (search) qs.set('search', search);
      const res = await fetch(`${API}/api/dewi/rnd/tech-packs?${qs}`, { headers: h });
      setTechPacks(await res.json());
    } catch { toast.error('Gagal memuat tech pack'); }
    finally { setLoading(false); }
  };

  const loadStyles = async () => {
    try {
      const res = await fetch(`${API}/api/dewi/rnd/styles`, { headers: h });
      if (res.ok) setStyles(await res.json());
    } catch { /* ignore */ }
  };

  // Master material untuk MENAUTKAN baris BOM → tanpa tautan ini satuan tidak
  // bisa dikonversi (faktor kemasan/gramasi ada di master material).
  // 2026-11-08 (Standar UI/UX v2, perbaikan pemilih): bawaan server 500 baris, diurut aksesoris dulu →
  // ±600 kain aktif tidak pernah muncul di pilihan "Tautan master". Minta sampai batas server (2000).
  const loadMatOpts = async () => {
    try {
      const res = await fetch(`${API}/api/dewi/rnd/material-options?limit=2000`, { headers: h });
      if (res.ok) setMatOpts(await res.json());
    } catch { /* ignore */ }
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { loadTechPacks(); }, [filterStyle]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { loadStyles(); loadMatOpts(); }, []);

  /** F2 — ambil daftar ukuran style (satu sumber untuk Varian & Tech Pack). */
  const loadStyleSizes = async (sid) => {
    if (!sid) { setStyleSizes({ size_list: [], unmatched: [], size_range: '', base_size: '' }); return null; }
    try {
      const res = await fetch(`${API}/api/dewi/rnd/styles/${sid}/size-list`, { headers: h });
      if (!res.ok) return null;
      const d = await res.json();
      setStyleSizes(d);
      return d;
    } catch { return null; }
  };

  /** Kolom measurement masih "bawaan" (belum disentuh pengguna)? col_id seed. */
  const colsUntouched = (cols) => (cols || []).length > 0
    && (cols || []).every(c => String(c?.col_id || '').startsWith('col_seed_'));

  const setStyleField = async sid => {
    const sel = styles.find(s => s.id === sid);
    setForm(p => ({ ...p, style_id: sid, style_code: sel?.style_code || '', style_name: sel?.style_name || '' }));
    const d = await loadStyleSizes(sid);
    if (d) {
      setForm(p => ({
        ...p,
        base_size: (d.size_list || []).includes(p.base_size) ? p.base_size : (d.base_size || ''),
        size_range: d.size_range || p.size_range,
        // §C "satu sumber": tech pack BARU memakai daftar ukuran style sebagai kolom
        // measurement. Kalau pengguna sudah menyunting kolomnya, JANGAN ditimpa
        // (kasus importir Excel yang memakai kategori STANDAR/JUMBO tetap aman).
        size_columns: (!editing && colsUntouched(p.size_columns) && (d.size_list || []).length)
          ? (d.size_list || []).map((sz, i) => ({ col_id: `col_seed_${i}`, label: sz }))
          : p.size_columns,
      }));
    }
  };

  // BOM helpers
  const setBOM = (i, k, v) => { const items = [...form.bom_items]; items[i] = { ...items[i], [k]: k === 'qty' ? Number(v) : v }; f('bom_items', items); };
  const addBOM = () => f('bom_items', [...form.bom_items, { ...emptyBOM }]);
  const removeBOM = i => f('bom_items', form.bom_items.filter((_, j) => j !== i));

  // Construction point helpers (b)
  const setCP = (i, k, v) => { const items = [...(form.construction_points || [])]; items[i] = { ...items[i], [k]: v }; f('construction_points', items); };
  const addCP = () => f('construction_points', [...(form.construction_points || []), { ...emptyCP }]);
  const removeCP = i => f('construction_points', (form.construction_points || []).filter((_, j) => j !== i));
  const moveCP = (i, dir) => {
    const items = [...(form.construction_points || [])];
    const j = i + dir; if (j < 0 || j >= items.length) return;
    [items[i], items[j]] = [items[j], items[i]];
    f('construction_points', items);
  };

  // Fabric helpers (c)
  const setFab = (i, k, v) => { const items = [...(form.fabrics || [])]; items[i] = { ...items[i], [k]: v }; f('fabrics', items); };
  const addFab = () => f('fabrics', [...(form.fabrics || []), { ...emptyFab }]);
  const removeFab = i => f('fabrics', (form.fabrics || []).filter((_, j) => j !== i));

  // Consumption helpers (c)
  const setCons = (i, k, v) => { const items = [...(form.fabric_consumption || [])]; items[i] = { ...items[i], [k]: v }; f('fabric_consumption', items); };
  const addCons = () => f('fabric_consumption', [...(form.fabric_consumption || []), { ...emptyCons }]);
  const removeCons = i => f('fabric_consumption', (form.fabric_consumption || []).filter((_, j) => j !== i));

  // F3/C3 — kolom ukuran: hanya LABEL yang diubah, `col_id` tidak pernah disentuh,
  // sehingga nilai measurement tidak mungkin hilang saat kolom diganti nama.
  const setSizeCol = (i, v) => {
    const c = [...(form.size_columns || [])];
    c[i] = { ...c[i], label: v };
    f('size_columns', c);
  };
  const addSizeCol = () => f('size_columns', [...(form.size_columns || []), { col_id: newColId(), label: '' }]);
  const removeSizeCol = (i) => {
    const cols = form.size_columns || [];
    const gone = cols[i];
    f('size_columns', cols.filter((_, j) => j !== i));
    // nilai kolom yang dihapus dipindah ke orphan_values, BUKAN dibuang
    if (gone?.col_id) {
      const meas = (form.measurements || []).map(m => {
        if (!m.values || !(gone.col_id in m.values)) return m;
        const values = { ...m.values };
        const orphan = { ...(m.orphan_values || {}), [gone.label || gone.col_id]: values[gone.col_id] };
        delete values[gone.col_id];
        return { ...m, values, orphan_values: orphan };
      });
      f('measurements', meas);
    }
  };

  // Measurements (dynamic columns)
  const setMeasPoint = (i, v) => { const items = [...(form.measurements || [])]; items[i] = { ...items[i], point: v }; f('measurements', items); };
  const setMeasVal = (i, col, v) => { const items = [...(form.measurements || [])]; const values = { ...(items[i].values || {}) }; values[col] = v; items[i] = { ...items[i], values }; f('measurements', items); };
  const addMeas = () => f('measurements', [...(form.measurements || []), { point: '', values: {} }]);
  const removeMeas = i => f('measurements', (form.measurements || []).filter((_, j) => j !== i));

  const openNew = async () => {
    const sel = styles.find(s => s.id === filterStyle);
    setForm({ ...emptyForm, style_id: sel?.id || '', style_code: sel?.style_code || '', style_name: sel?.style_name || '' });
    setEditing(null); setTab('info'); setShowForm(true);
    const d = await loadStyleSizes(sel?.id);
    if (d) setForm(p => ({
      ...p,
      base_size: d.base_size || p.base_size,
      size_range: d.size_range || p.size_range,
      size_columns: (d.size_list || []).length
        ? (d.size_list || []).map((sz, i) => ({ col_id: `col_seed_${i}`, label: sz }))
        : p.size_columns,
    }));
  };

  const openEdit = async tp => {
    setDetail(null);
    const sizeCols = normSizeCols(
      (tp.size_columns && tp.size_columns.length) ? tp.size_columns : DEFAULT_SIZE_COLS);
    setForm({
      style_id: tp.style_id || '', style_code: tp.style_code || '', style_name: tp.style_name || '',
      version: String(tp.version || 'v1'), title: tp.title || '', description: tp.description || '',
      doc_url: tp.doc_url || '', doc_type: tp.doc_type || 'pdf',
      bom_items: tp.bom_items?.length ? tp.bom_items : [{ ...emptyBOM }],
      fabrics: tp.fabrics?.length ? tp.fabrics : [{ ...emptyFab }],
      fabric_consumption: tp.fabric_consumption || [],
      construction_points: (tp.construction_points && tp.construction_points.length)
        ? tp.construction_points
        : (tp.construction_notes
            ? tp.construction_notes.split('\n').filter(Boolean).map((d, i) => ({ seq: i + 1, title: '', description: d }))
            : []),
      construction_notes: tp.construction_notes || '',
      stitch_type: tp.stitch_type || '',
      seam_allowance_mm: tp.seam_allowance_mm ?? 10,
      size_grading_notes: tp.size_grading_notes || '',
      base_size: tp.base_size || 'M',
      size_range: tp.size_range || 'S-XL',
      size_columns: sizeCols,
      colorways: tp.colorways || [],
      fit_categories: tp.fit_categories || [],
      measurements: normMeasurements(tp.measurements, sizeCols),
      status: tp.status || 'draft',
    });
    setEditing(tp.id); setTab('info'); setShowForm(true);
    const d = await loadStyleSizes(tp.style_id);
    if (d) setForm(p => ({
      ...p,
      base_size: (d.size_list || []).includes(p.base_size) ? p.base_size : (d.base_size || p.base_size),
      size_range: d.size_range || p.size_range,
    }));
  };

  const handleApprove = async id => {
    try {
      // 2026-11-06 (pola P6): helper lib/api melempar bila server menolak → pesan sukses hanya bila benar tersimpan
      await apiPost(`/api/dewi/rnd/tech-packs/${id}/approve`, {});
      toast.success('Tech pack disetujui');
      setDetail(null);
      loadTechPacks();
    } catch { toast.error('Gagal menyetujui tech pack'); }
  };

  const handleSave = async () => {
    if (!form.style_id) return toast.error('Pilih style terlebih dahulu');
    if (!form.version.trim()) return toast.error('Versi wajib diisi');
    // keep construction_notes synced from structured points (backward-compat)
    const payload = {
      ...form,
      construction_points: (form.construction_points || []).map((cp, i) => ({ ...cp, seq: i + 1 })),
      construction_notes: (form.construction_points || []).map(cp => cp.description).filter(Boolean).join('\n') || form.construction_notes,
      // F3/C3: kirim {col_id,label} — col_id dipertahankan supaya nilai tidak yatim
      size_columns: (form.size_columns || []).filter(c => c && (c.label || '').trim()),
    };
    try {
      const method = editing ? 'PUT' : 'POST';
      const url = editing ? `${API}/api/dewi/rnd/tech-packs/${editing}` : `${API}/api/dewi/rnd/tech-packs`;
      const res = await fetch(url, { method, headers: h, body: JSON.stringify(payload) });
      if (!res.ok) {
        let msg = 'Gagal menyimpan tech pack';
        try { const e = await res.json(); msg = e?.detail || msg; } catch { /* ignore */ }
        toast.error(msg, { duration: 7000 });
        return;
      }
      const saved = await res.json();
      const unlinked = saved?.bom_unlinked_count || 0;
      toast.success(editing ? 'Tech pack disimpan' : 'Tech pack ditambahkan');
      if (unlinked > 0) {
        toast.warning(`${unlinked} baris BOM belum tertaut master material — HPP dari BOM untuk baris itu belum bisa dihitung.`, { duration: 8000 });
      }
      setShowForm(false);
      loadTechPacks();
    } catch { toast.error('Gagal menyimpan tech pack'); }
  };

  const handleDelete = async (tp) => {
    const ok = await confirmDialog({
      title: 'Hapus tech pack ini?',
      body: `${tp.title || `Tech pack ${tp.version || ''}`} (${tp.style_code || '—'}) dihapus permanen.`,
      confirmLabel: 'Hapus', danger: true,
    });
    if (!ok) return;
    try {
      await apiDelete(`/api/dewi/rnd/tech-packs/${tp.id}`);  // 2026-11-06 (pola P6): lihat approve
      toast.success('Tech pack dihapus');
      setDetail(null); loadTechPacks();
    } catch { toast.error('Gagal menghapus'); }
  };

  // ── Import Excel ──
  const openImport = () => { setImportPreview(null); setImportSummary(null); setPickedFileName(''); if (fileRef.current) fileRef.current.value = ''; setShowImport(true); };

  const doImport = async (mode) => {
    const file = fileRef.current?.files?.[0];
    if (!file) return toast.error('Pilih berkas Excel (.xlsx) terlebih dahulu');
    const fd = new FormData();
    fd.append('file', file);
    setImportBusy(true);
    try {
      const url = `${API}/api/dewi/rnd/techpack/import/${mode}`;
      const res = await fetch(url, { method: 'POST', headers: hMultipart, body: fd });
      const data = await res.json();
      if (!res.ok) { toast.error(data?.detail || 'Impor gagal'); return; }
      if (mode === 'preview') {
        setImportPreview(data); setImportSummary(null);
        toast.success(`Pratinjau: ${data.total} produk terbaca (${data.errors?.length || 0} bermasalah)`);
      } else {
        setImportSummary(data); setImportPreview(null);
        toast.success(`Impor selesai: ${data.styles_created} style baru, ${data.styles_updated} diperbarui, ${data.techpacks} tech pack`);
        loadTechPacks(); loadStyles();
      }
    } catch { toast.error('Impor gagal (koneksi)'); }
    finally { setImportBusy(false); }
  };

  const filtered = techPacks.filter(tp => {
    if (!search) return true;
    const q = search.toLowerCase();
    return String(tp.title || '').toLowerCase().includes(q)
      || String(tp.style_code || '').toLowerCase().includes(q)
      || String(tp.style_name || '').toLowerCase().includes(q)
      || String(tp.version || '').toLowerCase().includes(q);
  });
  const filteredPg = useClientPagination(filtered, 10);

  // F3/C1 — jumlah baris BOM yang belum tertaut master (badge peringatan di tab BOM)
  const unlinkedBom = (form.bom_items || []).filter(b => !b.material_id && (b.material || b.qty)).length;

  const detailSizeCols = (tp) => normSizeCols(
    (tp.size_columns && tp.size_columns.length) ? tp.size_columns : DEFAULT_SIZE_COLS);

  const tpJudul = (tp) => tp.title || `Tech pack ${tp.version || ''}`.trim();

  const kolom = [
    { kunci: 'judul', label: 'Tech pack', hp: 'judul', isi: (tp) => (
      <div className="min-w-0 md:max-w-[20rem]">
        <p className="truncate font-medium text-foreground" title={tpJudul(tp)}>{tpJudul(tp)}</p>
        <p className="text-xs text-muted-foreground">Versi {tp.version || '—'}</p>
      </div>) },
    { kunci: 'style', label: 'Style', hp: 'keterangan', isi: (tp) => (
      <div className="min-w-0">
        <p className="text-foreground">{tp.style_code || '—'}</p>
        {tp.style_name && <p className="text-xs text-muted-foreground">{tp.style_name}</p>}
      </div>) },
    { kunci: 'ukuran', label: 'Ukuran', isi: (tp) => (
      <span className="md:whitespace-nowrap">Dasar {tp.base_size || '—'} · {tp.size_range || '—'}</span>) },
    { kunci: 'bom', label: 'BOM', isi: (tp) => (
      <div className="text-sm">
        <span className="tabular-nums">{(tp.bom_items || []).length} baris</span>
        {bomTanpaMaster(tp) > 0 && (
          <span className="block text-xs text-[hsl(var(--danger-text))]" data-testid={`techpack-bom-unlinked-${tp.id}`}>
            {bomTanpaMaster(tp)} tanpa master
          </span>
        )}
      </div>) },
    { kunci: 'status', label: 'Status', isi: (tp) => (
      <div className="flex flex-wrap gap-1">
        <StatusBadge status={tp.status} label={statusTp(tp.status).label} tone={statusTp(tp.status).tone} />
        {tp.is_latest && <StatusBadge status="terbaru" tone="primary" label="Terbaru" />}
        {tp.source === 'excel_import' && <StatusBadge status="impor" tone="info" label="Impor Excel" />}
      </div>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (tp) => (
      <div className="flex justify-end gap-1">
        <Button variant="ghost" size="icon-sm" onClick={() => openEdit(tp)} title="Ubah" aria-label="Ubah"
          data-testid={`techpack-edit-${tp.id}`}><Pencil /></Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" title="Lainnya" aria-label="Lainnya" data-testid={`techpack-more-${tp.id}`}>
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {tp.status !== 'approved' && (
              <DropdownMenuItem onSelect={() => handleApprove(tp.id)} data-testid={`techpack-approve-${tp.id}`}>
                <CheckCircle2 className="mr-2 h-4 w-4" />Setujui
              </DropdownMenuItem>
            )}
            {tp.doc_url && (
              <DropdownMenuItem onSelect={() => window.open(tp.doc_url, '_blank', 'noopener,noreferrer')}>
                <ExternalLink className="mr-2 h-4 w-4" />Buka dokumen
              </DropdownMenuItem>
            )}
            <DropdownMenuItem onSelect={() => handleDelete(tp)} className="text-[hsl(var(--danger-text))]"
              data-testid={`techpack-delete-${tp.id}`}>
              <Trash2 className="mr-2 h-4 w-4" />Hapus
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>) },
  ];

  const unduhKolom = [
    { label: 'Judul', nilai: (tp) => tpJudul(tp) },
    { label: 'Versi', nilai: (tp) => tp.version || '' },
    { label: 'Kode style', nilai: (tp) => tp.style_code || '' },
    { label: 'Nama style', nilai: (tp) => tp.style_name || '' },
    { label: 'Ukuran dasar', nilai: (tp) => tp.base_size || '' },
    { label: 'Rentang ukuran', nilai: (tp) => tp.size_range || '' },
    { label: 'Kategori fit', nilai: (tp) => (tp.fit_categories || []).join(', ') },
    { label: 'Kain', nilai: (tp) => (tp.fabrics || []).map(fb => `${fb.name} (${peranKain(fb.role)})`).join('; ') },
    { label: 'Jumlah colorway', nilai: (tp) => (tp.colorways || []).length },
    { label: 'Poin konstruksi', nilai: (tp) => (tp.construction_points || []).length },
    { label: 'Baris BOM', nilai: (tp) => (tp.bom_items || []).length },
    { label: 'BOM tanpa master', nilai: (tp) => bomTanpaMaster(tp) },
    { label: 'Status', nilai: (tp) => statusTp(tp.status).label },
    { label: 'Terbaru', nilai: (tp) => (tp.is_latest ? 'Ya' : 'Tidak') },
    { label: 'Sumber', nilai: (tp) => (tp.source === 'excel_import' ? 'Impor Excel' : 'Manual') },
    { label: 'Tautan dokumen', nilai: (tp) => tp.doc_url || '' },
  ];

  const pg = filteredPg;
  const cols = detail ? detailSizeCols(detail) : [];
  /** Enter di kolom isian tidak langsung menyimpan (form 5 bagian, banyak baris) — sama seperti sebelumnya. */
  const tahanEnter = (e) => { if (e.key === 'Enter' && e.target.tagName === 'INPUT') e.preventDefault(); };

  return (
    <PageLayout testId="rnd-techpack-module" title="Tech pack"
      subtitle="BOM, konstruksi per poin, penggunaan bahan per ukuran, dan ukuran per kategori."
      actions={<>
        <Button variant="outline" onClick={openImport} data-testid="techpack-import-btn"><Upload />Impor Excel</Button>
        <Button onClick={openNew} data-testid="techpack-add-btn"><Plus />Buat tech pack</Button>
      </>}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={e => setSearch(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && loadTechPacks()}
            placeholder="Cari style atau judul" className="pl-8" data-testid="techpack-search" />
        </div>
        <SmartNativeSelect value={filterStyle} onChange={e => setFilterStyle(e.target.value)}
          className="w-full sm:w-56" data-testid="techpack-style-filter">
          <option value="">Semua style</option>
          {styles.map(s => <option key={s.id} value={s.id}>{s.style_code} — {s.style_name}</option>)}
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="tech-pack" namaLembar="Tech pack" baris={filtered} kolom={unduhKolom} testId="techpack-unduh" />
        <Button variant="outline" size="icon" onClick={loadTechPacks} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      footer={pg.total > pg.pageSize && (
        <PaginationLite page={pg.page} totalPages={pg.totalPages} total={pg.total} pageSize={pg.pageSize} onPageChange={pg.setPage} />
      )}>
      {loading && techPacks.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat tech pack…</p>
      ) : (
        <TabelData kolom={kolom} baris={pg.paged} onKlikBaris={setDetail} testId="techpack-table"
          kosong={<EmptyState icon={FileText}
            title={techPacks.length ? 'Tidak ada tech pack yang cocok' : 'Belum ada tech pack'}
            description={techPacks.length ? 'Ubah kata pencarian atau pilihan style.' : 'Buat tech pack pertama, atau impor dari berkas Excel ringkasan produk.'}
            action={!techPacks.length && (
              <div className="flex flex-wrap justify-center gap-2">
                <Button variant="outline" onClick={openImport}><Upload />Impor Excel</Button>
                <Button onClick={openNew}><Plus />Buat tech pack</Button>
              </div>
            )} />} />
      )}

      {/* ── Rincian (popup) ── */}
      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} testId="techpack-detail"
          judul={tpJudul(detail)}
          keterangan={`${detail.style_code || '—'} — ${detail.style_name || ''} · Versi ${detail.version || '—'}`}
          status={<>
            <StatusBadge status={detail.status} label={statusTp(detail.status).label} tone={statusTp(detail.status).tone} />
            {detail.is_latest && <StatusBadge status="terbaru" tone="primary" label="Terbaru" />}
          </>}
          aksi={<>
            {detail.status !== 'approved' && (
              <Button size="sm" variant="success" onClick={() => handleApprove(detail.id)}><CheckCircle2 />Setujui</Button>
            )}
            {detail.doc_url && (
              <Button size="sm" variant="outline" asChild>
                <a href={detail.doc_url} target="_blank" rel="noreferrer"><ExternalLink />Dokumen</a>
              </Button>
            )}
            <Button size="sm" variant="outline" onClick={() => openEdit(detail)}><Pencil />Ubah</Button>
            <Button size="sm" variant="destructive" onClick={() => handleDelete(detail)}><Trash2 />Hapus</Button>
          </>}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Ukuran">Dasar {detail.base_size || '—'} · rentang {detail.size_range || '—'}</BarisDetail>
            {(detail.fit_categories || []).length > 0 && <BarisDetail label="Kategori fit">{detail.fit_categories.join(' / ')}</BarisDetail>}
            {detail.description && <BarisDetail label="Deskripsi">{detail.description}</BarisDetail>}
            {detail.stitch_type && <BarisDetail label="Jahitan">{detail.stitch_type} · kampuh {detail.seam_allowance_mm} mm</BarisDetail>}
            {detail.size_grading_notes && <BarisDetail label="Catatan grading">{detail.size_grading_notes}</BarisDetail>}
          </dl>

          {detail.fabrics?.length > 0 && (
            <div className="space-y-2">
              <p className="text-sm font-semibold text-foreground">Material / kain</p>
              <div className="flex flex-wrap gap-2">
                {detail.fabrics.map((fb, i) => (
                  <span key={i} className="inline-flex items-center gap-1.5 rounded-full border border-[var(--glass-border)] px-2 py-0.5 text-xs">
                    {fb.color_hex && <span className="h-2.5 w-2.5 rounded-full border border-[var(--glass-border)]" style={{ backgroundColor: fb.color_hex }} />}
                    {fb.name} · {peranKain(fb.role)}
                    {fb.color_name && <span className="text-muted-foreground">{fb.color_code || fb.color_name}</span>}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* F3/C4 Colorways resmi */}
          {detail.colorways?.length > 0 && (
            <div className="space-y-2" data-testid={`techpack-colorways-${detail.id}`}>
              <p className="text-sm font-semibold text-foreground">Colorway resmi ({detail.colorways.length})</p>
              <div className="flex flex-wrap gap-2">
                {detail.colorways.map((c) => (
                  <span key={c.color_id || c.code} className="inline-flex items-center gap-1.5 rounded-full border border-[var(--glass-border)] px-2 py-0.5 text-xs">
                    <span className="h-3 w-3 rounded-full border border-[var(--glass-border)]" style={{ backgroundColor: c.hex }} />
                    <span className="text-foreground">{c.name}</span>
                    <span className="text-muted-foreground">{c.code}</span>
                  </span>
                ))}
              </div>
            </div>
          )}

          {detail.construction_points?.length > 0 ? (
            <div className="space-y-2">
              <p className="text-sm font-semibold text-foreground">Konstruksi ({detail.construction_points.length} poin)</p>
              <ol className="list-inside list-decimal space-y-0.5 text-sm text-foreground">
                {detail.construction_points.map((cp, i) => (
                  <li key={i}>{cp.title ? <span className="font-medium">{cp.title}: </span> : null}{cp.description}</li>
                ))}
              </ol>
            </div>
          ) : detail.construction_notes ? (
            <div className="space-y-2">
              <p className="text-sm font-semibold text-foreground">Konstruksi</p>
              <p className="whitespace-pre-line text-sm text-foreground">{detail.construction_notes}</p>
            </div>
          ) : null}

          {detail.fabric_consumption?.length > 0 && (
            <div className="space-y-2">
              <p className="text-sm font-semibold text-foreground">Penggunaan bahan per ukuran</p>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Ukuran</TableHead><TableHead>Kain</TableHead>
                    <TableHead className="text-right">Panjang (cm)</TableHead><TableHead className="text-right">Lebar (cm)</TableHead>
                    <TableHead className="text-right">Hasil (pcs)</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {detail.fabric_consumption.map((e, i) => (
                    <TableRow key={i}>
                      <TableCell className="font-medium">
                        {e.size}
                        {e.size_off_list && <StatusBadge status="luar" tone="warning" label="di luar daftar ukuran style" className="ml-1" />}
                      </TableCell>
                      <TableCell>{peranKain(e.fabric_role)}</TableCell>
                      <TableCell className="text-right tabular-nums">{e.length_cm ?? '—'}</TableCell>
                      <TableCell className="text-right tabular-nums">{e.width_cm ?? '—'}</TableCell>
                      <TableCell className="text-right tabular-nums">{e.yield_pcs ?? '—'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}

          {detail.bom_items?.length > 0 && (
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-sm font-semibold text-foreground">BOM (daftar bahan)</p>
                {bomTanpaMaster(detail) > 0 && (
                  <StatusBadge status="tanpa-master" tone="danger" label={`${bomTanpaMaster(detail)} baris tanpa master — HPP baris itu belum benar`} />
                )}
              </div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Material</TableHead><TableHead>Tautan master</TableHead><TableHead>Warna</TableHead>
                    <TableHead>Spesifikasi</TableHead><TableHead className="text-right">Qty</TableHead><TableHead>Satuan</TableHead>
                    <TableHead>Qty satuan dasar</TableHead><TableHead>Pemasok</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {detail.bom_items.map((b, i) => {
                    const st = UOM_STATUS[b.uom_status] || {};
                    return (
                      <TableRow key={i}>
                        <TableCell className="font-medium">{b.material || b.material_name}</TableCell>
                        <TableCell>
                          {b.master_linked
                            ? <StatusBadge status="tertaut" tone="success" label={b.material_code || 'Tertaut'} />
                            : <span title={b.master_link_note || ''}><StatusBadge status="tanpa-master" tone="danger" label="Tanpa master" /></span>}
                        </TableCell>
                        <TableCell>
                          {b.color_name ? (
                            <span className="inline-flex items-center gap-1 text-xs">
                              <span className="h-2.5 w-2.5 rounded-full border border-[var(--glass-border)]" style={{ backgroundColor: b.color_hex || 'transparent' }} />
                              {b.color_code || b.color_name}
                            </span>
                          ) : <span className="text-muted-foreground">—</span>}
                        </TableCell>
                        <TableCell>{b.spec || '—'}</TableCell>
                        <TableCell className="text-right tabular-nums">{b.qty}</TableCell>
                        <TableCell>{b.unit}</TableCell>
                        <TableCell className={st.warn ? 'text-[hsl(var(--danger-text))]' : ''}>
                          {b.qty_base != null ? <>{b.qty_base} {b.unit_base}{st.warn ? ` · ${st.label}` : ''}</> : '—'}
                        </TableCell>
                        <TableCell>{b.supplier || '—'}</TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}

          {detail.measurements?.length > 0 && (
            <div className="space-y-2">
              <p className="text-sm font-semibold text-foreground">Ukuran detail (cm)</p>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Titik ukur</TableHead>
                    {cols.map(c => <TableHead key={c.col_id} className="text-right">{c.label}</TableHead>)}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {normMeasurements(detail.measurements, cols).map((m, i) => (
                    <TableRow key={i}>
                      <TableCell className="font-medium">{m.point}</TableCell>
                      {cols.map(c => <TableCell key={c.col_id} className="text-right tabular-nums">{m.values[c.col_id] || '—'}</TableCell>)}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </DetailPopup>
      )}

      {/* ── Impor Excel (popup standar) ── */}
      <FormPopup open={showImport} onClose={() => setShowImport(false)} ukuran="panjang"
        judul="Impor tech pack dari Excel"
        keterangan='Berkas "Data Techpack Ringkasan Produk" (.xlsx, format V5). Membuat/memperbarui style, varian per warna, dan tech pack.'
        onSimpan={() => doImport('commit')} labelSimpan="Impor sekarang" menyimpan={importBusy}
        aksiKiri={<Button type="button" variant="outline" disabled={importBusy} onClick={() => doImport('preview')}
          data-testid="techpack-import-preview-btn"><Search />Pratinjau</Button>}
        testId="techpack-import-modal">
        <p className="text-sm text-muted-foreground">
          Yang dibaca: konstruksi per poin, penggunaan bahan per ukuran, dan ukuran per kategori.
          Klik <b>Pratinjau</b> untuk memeriksa isi berkas sebelum diimpor.
        </p>
        <Isian label="Berkas Excel (.xlsx)" htmlFor="techpack-import-file">
          <div className="flex flex-wrap items-center gap-3">
            <input id="techpack-import-file" ref={fileRef} type="file" accept=".xlsx" data-testid="techpack-import-file"
              onChange={e => { setPickedFileName(e.target.files?.[0]?.name || ''); setImportPreview(null); setImportSummary(null); }}
              className="max-w-full text-sm text-foreground file:mr-3 file:rounded-md file:border-0 file:bg-[hsl(var(--primary)/0.12)] file:px-3 file:py-1.5 file:text-sm file:text-[hsl(var(--primary))]" />
            {pickedFileName && <span className="max-w-[200px] truncate text-xs text-muted-foreground">{pickedFileName}</span>}
          </div>
        </Isian>

        {importPreview && (
          <div className="space-y-2">
            <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-foreground">
              {importPreview.total} produk terbaca
              {importPreview.errors?.length > 0 && (
                <span className="inline-flex items-center gap-1 text-xs font-normal text-[hsl(var(--warning-text))]">
                  <AlertTriangle className="h-3 w-3" /> {importPreview.errors.length} baris bermasalah
                </span>
              )}
            </p>
            <div className="max-h-[320px] overflow-auto rounded-[var(--radius-md)] border border-[var(--glass-border)]">
              <Table>
                <TableHeader>
                  <TableRow>
                    {['Kode', 'Nama', 'Kategori', 'Warna', 'Ukuran', 'Poin jahit', 'Kain', 'Kategori ukuran'].map(c => (
                      <TableHead key={c}>{c}</TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {importPreview.products.map((p, i) => (
                    <TableRow key={i}>
                      <TableCell className="font-medium">{p.style_code}</TableCell>
                      <TableCell>{p.style_name}</TableCell>
                      <TableCell>{p.category}</TableCell>
                      <TableCell className="tabular-nums">{(p.colors || []).length}</TableCell>
                      <TableCell>{(p.sizes || []).join(', ')}</TableCell>
                      <TableCell className="tabular-nums">{(p.construction_points || []).length}</TableCell>
                      <TableCell>{(p.fabrics || []).map(fb => fb.name).join(' + ')}</TableCell>
                      <TableCell>{(p.measurement_categories || []).join(', ') || '—'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        )}

        {importSummary && (
          <Notice tone="success" icon={CheckCircle2} title="Impor berhasil" testId="techpack-import-summary">
            <p className="tabular-nums">
              {importSummary.styles_created} style baru · {importSummary.styles_updated} style diperbarui ·{' '}
              {importSummary.variants} varian · {importSummary.techpacks} tech pack
            </p>
            {importSummary.errors?.length > 0 && (
              <p className="mt-1 text-[hsl(var(--warning-text))]">{importSummary.errors.length} baris bermasalah (dilewati).</p>
            )}
          </Notice>
        )}
      </FormPopup>

      {/* ── Form tech pack (popup standar, panjang) ── */}
      <FormPopup open={showForm} onClose={() => setShowForm(false)} ukuran="panjang" onSimpan={handleSave}
        judul={editing ? 'Ubah tech pack' : 'Buat tech pack'}
        keterangan="Lima bagian: informasi, konstruksi, bahan, BOM, dan ukuran. Simpan menyimpan semua bagian."
        testId="techpack-form">
        <div className="space-y-4" onKeyDown={tahanEnter}>
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList className="max-w-full flex-wrap justify-start">
              {[['info', 'Informasi'], ['konstruksi', 'Konstruksi'], ['bahan', 'Bahan'], ['bom', 'BOM'], ['measurements', 'Ukuran']].map(([id, lbl]) => (
                <TabsTrigger key={id} value={id} data-testid={`techpack-form-tab-${id}`}>
                  {lbl}{id === 'bom' && unlinkedBom > 0 ? ` (${unlinkedBom} tanpa master)` : ''}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>

          {tab === 'info' && (
            <div className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <Isian label="Style" wajib>
                  <SmartNativeSelect value={form.style_id} onChange={e => setStyleField(e.target.value)}
                    className="w-full" data-testid="techpack-style-select">
                    <option value="">Pilih style</option>
                    {styles.map(s => <option key={s.id} value={s.id}>{s.style_code} — {s.style_name}</option>)}
                  </SmartNativeSelect>
                </Isian>
                <Isian label="Versi" wajib htmlFor="tp-versi">
                  <Input id="tp-versi" value={form.version} onChange={e => f('version', e.target.value)} placeholder="v1" />
                </Isian>
              </div>
              <Isian label="Judul tech pack" htmlFor="tp-judul">
                <Input id="tp-judul" value={form.title} onChange={e => f('title', e.target.value)} placeholder="Contoh: JENIFER Blouse TP v1" />
              </Isian>
              <Isian label="Deskripsi" htmlFor="tp-desk">
                <Textarea id="tp-desk" rows={2} value={form.description} onChange={e => f('description', e.target.value)} />
              </Isian>
              <div className="grid gap-4 sm:grid-cols-2">
                <Isian label="Tautan dokumen (PDF/gambar)" htmlFor="tp-url">
                  <Input id="tp-url" value={form.doc_url} onChange={e => f('doc_url', e.target.value)} placeholder="https://..." />
                </Isian>
                <Isian label="Jenis dokumen">
                  <SmartNativeSelect value={form.doc_type} onChange={e => f('doc_type', e.target.value)}
                    searchable={false} className="w-full" data-testid="tp-doc-type">
                    <option value="pdf">PDF</option>
                    <option value="image">Gambar</option>
                    <option value="link">Tautan luar</option>
                    <option value="excel_import">Impor Excel</option>
                  </SmartNativeSelect>
                </Isian>
              </div>

              <section className="space-y-3 border-t border-[var(--glass-border)] pt-4">
                <div>
                  <p className="text-sm font-semibold text-foreground">Ukuran & grading</p>
                  <p className="text-xs text-muted-foreground">Daftar ukuran diambil dari style — satu sumber dengan Varian produk.</p>
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  <Isian label="Ukuran dasar" petunjuk="Dipilih dari daftar ukuran style.">
                    <SmartNativeSelect value={form.base_size} onChange={e => f('base_size', e.target.value)}
                      data-testid="techpack-base-size" className="w-full">
                      <option value="">Pilih ukuran</option>
                      {(styleSizes.size_list || []).map(sz => <option key={sz} value={sz}>{sz}</option>)}
                    </SmartNativeSelect>
                  </Isian>
                  <Isian label="Rentang ukuran" petunjuk="Otomatis dari daftar ukuran style.">
                    <Input className="bg-muted" value={styleSizes.size_range || form.size_range}
                      readOnly data-testid="techpack-size-range"
                      title="Dihitung otomatis dari daftar ukuran style — tidak perlu diketik lagi" />
                  </Isian>
                  <Isian label="Daftar ukuran style" petunjuk='Ubah daftarnya di Varian produk → "Tambah ukuran".'>
                    <div className="flex min-h-9 flex-wrap items-center gap-1 rounded-md border border-input px-2 py-1.5">
                      {(styleSizes.size_list || []).length === 0 ? (
                        <span className="text-xs text-muted-foreground">Pilih style dulu</span>
                      ) : (styleSizes.size_list || []).map(sz => {
                        const belum = (styleSizes.unmatched || []).includes(sz);
                        return (
                          <span key={sz} title={belum ? 'Belum dipadankan ke master ukuran produksi' : ''}>
                            <StatusBadge status={sz} label={sz} tone={belum ? 'warning' : 'muted'} />
                          </span>
                        );
                      })}
                    </div>
                  </Isian>
                </div>
                <Isian label="Catatan grading" htmlFor="tp-grading">
                  <Input id="tp-grading" value={form.size_grading_notes} onChange={e => f('size_grading_notes', e.target.value)} />
                </Isian>
                <Isian label="Kategori fit" htmlFor="tp-fit" petunjuk="Informasi, mis. Standar, Jumbo — tidak mengubah SKU/varian. Pisahkan dengan koma.">
                  <Input id="tp-fit" value={(form.fit_categories || []).join(', ')}
                    onChange={e => f('fit_categories', e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
                    placeholder="Standar, Jumbo" data-testid="techpack-fit-categories" />
                </Isian>
              </section>

              {/* F3/C4 — Colorway resmi untuk gaya ini */}
              <section className="space-y-2 border-t border-[var(--glass-border)] pt-4">
                <div>
                  <p className="text-sm font-semibold text-foreground">Colorway resmi</p>
                  <p className="text-xs text-muted-foreground">
                    Warna resmi style ini (mis. 3 colorway), dari master warna yang sama dengan produksi &amp; gudang —
                    bisa disambung ke SKU barang jadi.
                  </p>
                </div>
                <ColorMultiSelect colors={colorOpts} addColor={addColor}
                  value={form.colorways || []} onChange={v => f('colorways', v)}
                  testId="techpack-colorways" label="Tambah colorway" />
              </section>
            </div>
          )}

          {tab === 'konstruksi' && (
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-semibold text-foreground">Jenis jahitan / konstruksi per poin</p>
                <Button type="button" variant="outline" size="sm" onClick={addCP}><Plus />Tambah poin</Button>
              </div>
              {(form.construction_points || []).length === 0 && (
                <p className="py-4 text-center text-sm text-muted-foreground">Belum ada poin konstruksi. Klik "Tambah poin".</p>
              )}
              {(form.construction_points || []).map((cp, i) => (
                <div key={i} className="flex items-start gap-2 rounded-[var(--radius-md)] border border-[var(--glass-border)] p-2">
                  <div className="w-6 pt-2 text-center text-sm font-semibold text-primary">{i + 1}</div>
                  <div className="min-w-0 flex-1 space-y-2">
                    <Input value={cp.title || ''} onChange={e => setCP(i, 'title', e.target.value)} placeholder="Judul (opsional, mis. Kepala lengan)" />
                    <Textarea rows={2} value={cp.description || ''} onChange={e => setCP(i, 'description', e.target.value)}
                      placeholder="Uraian poin jahitan…" />
                  </div>
                  <div className="flex flex-col gap-1">
                    <Button type="button" variant="ghost" size="icon-sm" onClick={() => moveCP(i, -1)} title="Naikkan" aria-label="Naikkan"><ChevronUp /></Button>
                    <Button type="button" variant="ghost" size="icon-sm" onClick={() => moveCP(i, 1)} title="Turunkan" aria-label="Turunkan"><ChevronDown /></Button>
                    <Button type="button" variant="ghost" size="icon-sm" onClick={() => removeCP(i)} title="Hapus poin" aria-label="Hapus poin">
                      <X className="text-[hsl(var(--danger-text))]" />
                    </Button>
                  </div>
                </div>
              ))}
              <div className="grid gap-3 border-t border-[var(--glass-border)] pt-3 sm:grid-cols-3">
                <Isian label="Jenis jahitan (umum)" htmlFor="tp-stitch" className="sm:col-span-2">
                  <Input id="tp-stitch" value={form.stitch_type} onChange={e => f('stitch_type', e.target.value)} placeholder="Obras / jahit satu jarum…" />
                </Isian>
                <Isian label="Lebar kampuh (mm)" htmlFor="tp-seam">
                  <Input id="tp-seam" type="number" value={form.seam_allowance_mm} onChange={e => f('seam_allowance_mm', Number(e.target.value))} />
                </Isian>
              </div>
            </div>
          )}

          {tab === 'bahan' && (
            <div className="space-y-5">
              <section className="space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-sm font-semibold text-foreground">Material / kain (utama + kombinasi)</p>
                  <Button type="button" variant="outline" size="sm" onClick={addFab}><Plus />Tambah kain</Button>
                </div>
                {(form.fabrics || []).length > 0 && (
                  <div className="hidden gap-2 text-xs text-muted-foreground sm:grid sm:grid-cols-[minmax(0,1fr)_130px_minmax(0,1fr)_36px]">
                    <span>Nama kain</span><span>Peran</span><span>Warna (master)</span><span />
                  </div>
                )}
                {(form.fabrics || []).map((fb, i) => (
                  <div key={i} className="grid grid-cols-[minmax(0,1fr)_120px] gap-2 rounded-[var(--radius-md)] border border-[var(--glass-border)] p-2 sm:grid-cols-[minmax(0,1fr)_130px_minmax(0,1fr)_36px] sm:items-start sm:border-0 sm:p-0">
                    <Input value={fb.name} onChange={e => setFab(i, 'name', e.target.value)} placeholder="Nama kain (mis. CONDRU)" className="col-span-2 sm:col-span-1" data-testid={`tp-fab-name-${i}`} />
                    <SmartNativeSelect value={fb.role} onChange={e => setFab(i, 'role', e.target.value)}
                      searchable={false} className="w-full" data-testid={`tp-fab-role-${i}`}>
                      <option value="main">Utama</option>
                      <option value="combination">Kombinasi</option>
                    </SmartNativeSelect>
                    <div className="flex justify-end sm:order-last">
                      <Button type="button" variant="ghost" size="icon" onClick={() => removeFab(i)} title="Hapus kain" aria-label="Hapus kain">
                        <X className="text-[hsl(var(--danger-text))]" />
                      </Button>
                    </div>
                    <div className="col-span-2 min-w-0 sm:col-span-1">
                      <ColorSelect colors={colorOpts} addColor={addColor}
                        value={fb.color_id || ''} testId={`tp-fab-color-${i}`}
                        placeholder="Warna kain"
                        onChange={(c) => {
                          const items = [...(form.fabrics || [])];
                          items[i] = { ...items[i],
                            color_id: c?.color_id || '', color_code: c?.code || '',
                            color_name: c?.name || '', color_hex: c?.hex || '' };
                          f('fabrics', items);
                        }} />
                    </div>
                  </div>
                ))}
              </section>
              <section className="space-y-2 border-t border-[var(--glass-border)] pt-4">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-sm font-semibold text-foreground">Penggunaan bahan per ukuran</p>
                  <Button type="button" variant="outline" size="sm" onClick={addCons}><Plus />Tambah baris</Button>
                </div>
                {(form.fabric_consumption || []).length === 0 && (
                  <p className="py-2 text-center text-sm text-muted-foreground">Belum ada data pemakaian. Contoh: M / Utama / 463 cm / 150 / 5 pcs.</p>
                )}
                {(styleSizes.size_list || []).length === 0 && (
                  <Notice tone="warning">
                    Pilih style di bagian Informasi dulu supaya pilihan ukuran muncul (ukuran diambil dari daftar style).
                  </Notice>
                )}
                {(form.fabric_consumption || []).length > 0 && (
                  <div className="hidden gap-2 text-xs text-muted-foreground sm:grid sm:grid-cols-[130px_120px_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_36px]">
                    <span>Ukuran</span><span>Kain</span><span>Panjang (cm)</span><span>Lebar (cm)</span><span>Hasil (pcs)</span><span />
                  </div>
                )}
                {(form.fabric_consumption || []).map((e, i) => (
                  <div key={i} className="grid grid-cols-2 gap-2 rounded-[var(--radius-md)] border border-[var(--glass-border)] p-2 sm:grid-cols-[130px_120px_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_36px] sm:border-0 sm:p-0">
                    <SmartNativeSelect value={e.size || ''} onChange={ev => setCons(i, 'size', ev.target.value)}
                      data-testid={`tp-cons-size-${i}`} className="w-full">
                      <option value="">Ukuran</option>
                      {(styleSizes.size_list || []).map(sz => <option key={sz} value={sz}>{sz}</option>)}
                      {e.size && !(styleSizes.size_list || []).includes(e.size) && (
                        <option value={e.size}>{`${e.size} (di luar daftar)`}</option>
                      )}
                    </SmartNativeSelect>
                    <SmartNativeSelect value={e.fabric_role || 'main'} onChange={ev => setCons(i, 'fabric_role', ev.target.value)}
                      searchable={false} className="w-full" data-testid={`tp-cons-role-${i}`}>
                      <option value="main">Utama</option>
                      <option value="combination">Kombinasi</option>
                    </SmartNativeSelect>
                    <Input type="number" value={e.length_cm ?? ''} onChange={ev => setCons(i, 'length_cm', ev.target.value)} placeholder="Panjang cm" aria-label="Panjang (cm)" />
                    <Input type="number" value={e.width_cm ?? ''} onChange={ev => setCons(i, 'width_cm', ev.target.value)} placeholder="Lebar cm" aria-label="Lebar (cm)" />
                    <Input type="number" value={e.yield_pcs ?? ''} onChange={ev => setCons(i, 'yield_pcs', ev.target.value)} placeholder="Hasil pcs" aria-label="Hasil (pcs)" />
                    <div className="flex justify-end">
                      <Button type="button" variant="ghost" size="icon" onClick={() => removeCons(i)} title="Hapus baris" aria-label="Hapus baris">
                        <X className="text-[hsl(var(--danger-text))]" />
                      </Button>
                    </div>
                  </div>
                ))}
              </section>
            </div>
          )}

          {tab === 'bom' && (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-semibold text-foreground">BOM (daftar bahan)</p>
                <div className="flex items-center gap-2">
                  {unlinkedBom > 0 && (
                    <span data-testid="tp-bom-unlinked-badge">
                      <StatusBadge status="tanpa-master" tone="danger" label={`${unlinkedBom} baris tanpa master`} />
                    </span>
                  )}
                  <Button type="button" variant="outline" size="sm" onClick={addBOM} data-testid="tp-bom-add"><Plus />Tambah item</Button>
                </div>
              </div>
              <Notice tone="info">
                <b>Tautan master adalah kolom utama.</b> Baris tanpa tautan master tidak punya harga &amp; faktor konversi
                satuan (gram→kg, lusin→pcs, meter↔kg lewat gramasi &amp; lebar), sehingga <b>HPP dari BOM untuk baris itu
                akan meleset</b> — karena itu barisnya diberi tanda merah.
              </Notice>
              {form.bom_items.map((b, i) => {
                const st = UOM_STATUS[b.uom_status] || {};
                const linked = !!b.material_id;
                return (
                  <div key={i} className={cn('space-y-2 rounded-[var(--radius-md)] border p-2.5', linked
                    ? 'border-[var(--glass-border)]'
                    : 'border-[hsl(var(--destructive)/0.4)] bg-[hsl(var(--destructive)/0.05)]')}>
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-[minmax(0,1.5fr)_minmax(0,1.2fr)_130px_72px_96px_36px] sm:items-start">
                      <div className="col-span-2 min-w-0 sm:col-span-1">
                        <Lbl>Tautan master *</Lbl>
                        <SmartNativeSelect value={b.material_id || ''} onChange={e => {
                            const opt = matOpts.find(m => m.material_id === e.target.value);
                            const items = [...form.bom_items];
                            items[i] = { ...items[i], material_id: e.target.value,
                              material: items[i].material || opt?.name || '',
                              material_code: opt?.code || items[i].material_code || '',
                              unit: items[i].unit || opt?.base_unit || 'pcs' };
                            f('bom_items', items);
                          }}
                          data-testid={`tp-bom-master-${i}`} className="w-full">
                          <option value="">Belum ditautkan…</option>
                          {matOpts.map(m => <option key={m.material_id} value={m.material_id}>{`${m.code} — ${m.name} (${m.base_unit})`}</option>)}
                        </SmartNativeSelect>
                      </div>
                      <div className="col-span-2 sm:col-span-1">
                        <Lbl>Nama baris</Lbl>
                        <Input value={b.material} onChange={e => setBOM(i, 'material', e.target.value)} placeholder="Nama bebas" data-testid={`tp-bom-material-${i}`} />
                      </div>
                      <div className="col-span-2 min-w-0 sm:col-span-1">
                        <Lbl>Warna</Lbl>
                        <ColorSelect colors={colorOpts} addColor={addColor}
                          value={b.color_id || ''} testId={`tp-bom-color-${i}`} placeholder="Warna"
                          onChange={(c) => {
                            const items = [...form.bom_items];
                            items[i] = { ...items[i],
                              color_id: c?.color_id || '', color_code: c?.code || '',
                              color_name: c?.name || '', color_hex: c?.hex || '' };
                            f('bom_items', items);
                          }} />
                      </div>
                      <div>
                        <Lbl>Qty</Lbl>
                        <Input type="number" value={b.qty} onChange={e => setBOM(i, 'qty', e.target.value)} placeholder="0" className="text-right" data-testid={`tp-bom-qty-${i}`} />
                      </div>
                      <div>
                        <Lbl>Satuan</Lbl>
                        <RnDUnitSelect value={b.unit} onChange={e => setBOM(i, 'unit', e.target.value)} testId={`tp-bom-unit-${i}`} />
                      </div>
                      <div className="col-span-2 flex justify-end sm:col-span-1 sm:pt-5">
                        <Button type="button" variant="ghost" size="icon" onClick={() => removeBOM(i)} title="Hapus baris" aria-label="Hapus baris"
                          data-testid={`tp-bom-del-${i}`}><X className="text-[hsl(var(--danger-text))]" /></Button>
                      </div>
                    </div>
                    <div className="grid gap-2 sm:grid-cols-2">
                      <Input value={b.spec} onChange={e => setBOM(i, 'spec', e.target.value)} placeholder="Spesifikasi / keterangan" aria-label="Spesifikasi" />
                      <Input value={b.supplier} onChange={e => setBOM(i, 'supplier', e.target.value)} placeholder="Pemasok" aria-label="Pemasok" />
                    </div>
                    {!linked && (
                      <p className="flex items-start gap-1 text-xs text-[hsl(var(--danger-text))]" data-testid={`tp-bom-warn-${i}`}>
                        <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                        <span>Tanpa master: <b>harga &amp; konversi satuan tidak dihitung</b> ⇒ HPP baris ini salah.
                          Pilih materialnya di kolom "Tautan master", atau hapus barisnya.</span>
                      </p>
                    )}
                    {linked && b.uom_status && (
                      <p className={cn('text-xs', st.warn ? 'text-[hsl(var(--danger-text))]' : 'text-muted-foreground')}>
                        {st.warn && <AlertTriangle className="mr-1 -mt-0.5 inline h-3 w-3" />}
                        {b.qty} {b.unit} = <b>{b.qty_base}</b> {b.unit_base} · {b.uom_note || st.label}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {tab === 'measurements' && (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-semibold text-foreground">Ukuran detail per kategori (cm)</p>
                <div className="flex gap-2">
                  <Button type="button" variant="outline" size="sm" onClick={addSizeCol}><Plus />Kategori ukuran</Button>
                  <Button type="button" variant="outline" size="sm" onClick={addMeas}><Plus />Titik ukur</Button>
                </div>
              </div>
              <Notice tone="info">
                Nilai ukuran dikunci ke <b>kolom yang stabil</b>, bukan ke namanya. Mengganti nama kolom (mis. XL → EXTRA L)
                <b> tidak menghilangkan</b> nilai yang sudah diisi; menghapus kolom pun tidak membuang nilainya — nilai itu
                disimpan sebagai cadangan.
              </Notice>
              {/* Kepala kategori ukuran yang bisa diubah — hanya LABEL yang berubah */}
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-muted-foreground">Kategori ukuran:</span>
                {(form.size_columns || []).map((c, i) => (
                  <div key={c.col_id} className="flex items-center gap-1">
                    <Input value={c.label} onChange={e => setSizeCol(i, e.target.value.toUpperCase())}
                      className="h-8 w-28" placeholder="STANDAR" aria-label={`Kategori ukuran ${i + 1}`}
                      data-testid={`tp-size-col-${i}`} />
                    <Button type="button" variant="ghost" size="icon-sm" onClick={() => removeSizeCol(i)}
                      title="Hapus kolom" aria-label="Hapus kolom" data-testid={`tp-size-coldel-${i}`}>
                      <X className="text-[hsl(var(--danger-text))]" />
                    </Button>
                  </div>
                ))}
              </div>
              {(form.measurements || []).length > 0 && (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Titik ukur</TableHead>
                      {(form.size_columns || []).map(c => <TableHead key={c.col_id} className="w-24 text-center">{c.label || '—'}</TableHead>)}
                      <TableHead className="w-10" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(form.measurements || []).map((m, i) => (
                      <TableRow key={i}>
                        <TableCell className="min-w-[8rem]">
                          <Input value={m.point} onChange={e => setMeasPoint(i, e.target.value)} placeholder="Contoh: LD" className="h-8" aria-label="Titik ukur" />
                        </TableCell>
                        {(form.size_columns || []).map(col => (
                          <TableCell key={col.col_id}>
                            <Input value={(m.values && m.values[col.col_id]) || ''}
                              onChange={e => setMeasVal(i, col.col_id, e.target.value)}
                              className="h-8 w-20 text-center" placeholder="0" aria-label={`${m.point || 'Titik'} ${col.label}`}
                              data-testid={`tp-meas-${i}-${col.col_id}`} />
                          </TableCell>
                        ))}
                        <TableCell>
                          <Button type="button" variant="ghost" size="icon-sm" onClick={() => removeMeas(i)} title="Hapus titik ukur" aria-label="Hapus titik ukur">
                            <X className="text-[hsl(var(--danger-text))]" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
              {(form.measurements || []).length === 0 && (
                <p className="py-4 text-center text-sm text-muted-foreground">Belum ada titik ukur. Klik "Titik ukur" untuk mulai.</p>
              )}
            </div>
          )}
        </div>
      </FormPopup>
    </PageLayout>
  );
}

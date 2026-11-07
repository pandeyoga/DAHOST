/**
 * Varian produk RnD (tab "Varian produk" di menu Style & Desain).
 *
 * Standar UI/UX v2 (8 Nov 2026): dulu 644 varian tampil sebagai kartu berulang (gulir tanpa ujung) — kini
 * tabel 25 baris per halaman (kartu ringkas di HP) + unduh Excel/CSV; klik baris = popup rincian ukuran & SKU;
 * temuan SKU yang tidak sesuai aturan dibuka di popup (dulu panel yang memanjang di atas daftar); form =
 * FormPopup panjang; hapus lewat confirmDialog. Isian, aturan SKU, dan panggilan API tidak berubah.
 */
import { useState, useEffect, useCallback, useMemo, Fragment } from 'react';
import {
  Plus, Trash2, Pencil, Search, X, Palette, Ruler, AlertTriangle, Wrench, CheckCircle2, Save, RefreshCw,
} from 'lucide-react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { toast } from '../ui/sonner';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL || '';
const PER_HALAMAN = 25;

const STATUS_OPTS = [
  { value: 'active',   label: 'Aktif',      tone: 'success' },
  { value: 'draft',    label: 'Draf',       tone: 'muted' },
  { value: 'archived', label: 'Diarsipkan', tone: 'muted' },
];
const statusOf = (s) => STATUS_OPTS.find(o => o.value === s) || { label: 'Aktif', tone: 'muted' };

const NEW_COLOR = '__new__';

/** Aturan SKU dari server ("{STYLE}-{COLOR_CODE}-{SIZE}") dalam kata yang dipahami staf. */
const aturanTeks = (c) => String(c || '{STYLE}-{COLOR_CODE}-{SIZE}')
  .replace('COLOR_CODE', 'KODE WARNA').replace('SIZE', 'UKURAN');

/** Hex untuk swatch. Dokumen lama menyimpan HEX di `color_code`; dokumen baru
 *  memakai `color_hex` (dan `color_code` berisi KODE master, mis. NVY).
 *  (Nilai ini ikut terkirim saat menyimpan Ubah varian — jangan diubah.) */
const swatchOf = (v) => {
  const hx = String(v?.color_hex || '').trim();
  if (hx.startsWith('#')) return hx;
  const legacy = String(v?.color_code || '').trim();
  return legacy.startsWith('#') ? legacy : '#9CA3AF';
};

/** KODE master warna dari sebuah varian (kosong bila masih hex/legacy). */
const codeOf = (v) => {
  const c = String(v?.color_code || '').trim();
  return c.startsWith('#') ? '' : c.toUpperCase();
};

/** Baris ukuran sebuah varian → selalu list objek.
 *  Importir Excel menulis `sizes` sebagai daftar STRING (`['S','M','L']`),
 *  sedangkan modal Varian menulis daftar objek `{size, sku, qty_plan}`.
 *  Tanpa normalisasi ini, varian hasil impor tidak menampilkan chip ukuran
 *  sama sekali (dan modal Edit-nya kehilangan daftar ukurannya). */
const sizeRows = (v) => ((v?.sizes) || []).map(s =>
  typeof s === 'string' ? { size: s, sku: '', qty_plan: 0 } : (s || {})
).filter(s => s.size);

const canonicalSku = (styleCode, colorCode, size) =>
  [styleCode, colorCode, size].map(s => String(s || '').trim().toUpperCase())
    .filter(Boolean).join('-');

const qtyTotal = (v) => sizeRows(v).reduce((t, s) => t + (Number(s.qty_plan) || 0), 0);
const skuKurang = (v) => sizeRows(v).filter(s => !s.sku).length;

function Swatch({ hex, className = 'h-4 w-4' }) {
  return (
    <span className={`inline-block shrink-0 rounded border border-[var(--glass-border)] ${className}`}
      style={hex ? { backgroundColor: hex } : undefined} aria-hidden="true" />
  );
}

async function readErr(res, fallback) {
  try {
    const data = await res.json();
    return data?.detail || data?.message || fallback;
  } catch { return fallback; }
}

export default function RnDVariantModule({ token }) {
  const h = { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` };

  const [variants, setVariants] = useState([]);
  const [styles, setStyles]     = useState([]);
  const [colorOpts, setColorOpts] = useState([]);
  const [loading, setLoading]   = useState(false);
  const [search, setSearch]     = useState('');
  const [filterStyle, setFilterStyle] = useState('');
  const [detail, setDetail]     = useState(null);   // varian yang dibuka di popup rincian

  // ── SKU audit (bug §2.5.1 — SKU R&D terbalik dari SSOT) ──
  const [audit, setAudit]       = useState(null);
  const [showAudit, setShowAudit] = useState(false);
  const [fixing, setFixing]     = useState('');

  // ── Modal state ──
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing]   = useState(null);   // variant id saat edit
  const [styleId, setStyleId]   = useState('');
  const [styleCode, setStyleCode] = useState('');
  const [styleName, setStyleName] = useState('');
  const [colorRows, setColorRows] = useState([]);   // [{key, color_id, code, name, hex, isNew, draft:{name,code,hex}}]
  const [sizes, setSizes]       = useState([]);     // ['XS','S',...]
  const [sizeMap, setSizeMap]   = useState([]);     // [{size,size_id,matched}]
  const [sizeSource, setSizeSource] = useState('default');
  const [sizeDirty, setSizeDirty]   = useState(false);
  const [matrix, setMatrix]     = useState({});     // {colorKey: {size: {sku, qty_plan}}}
  const [status, setStatus]     = useState('active');
  const [notes, setNotes]       = useState('');
  const [saving, setSaving]     = useState(false);

  // ─────────────────────────── loaders ───────────────────────────
  const loadVariants = useCallback(async () => {
    setLoading(true);
    try {
      const url = filterStyle
        ? `${API}/api/dewi/rnd/variants?style_id=${filterStyle}`
        : `${API}/api/dewi/rnd/variants`;
      const res = await fetch(url, { headers: h });
      const data = await res.json();
      setVariants(Array.isArray(data) ? data : []);
    } catch { toast.error('Gagal memuat varian'); }
    finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterStyle, token]);

  const loadStyles = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/dewi/rnd/styles`, { headers: h });
      const data = await res.json();
      setStyles(Array.isArray(data) ? data : (data.items || []));
    } catch { /* ignore */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const loadColors = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/dewi/rnd/color-options`, { headers: h });
      if (res.ok) setColorOpts(await res.json());
    } catch { /* ignore */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const loadAudit = useCallback(async () => {
    try {
      const qs = filterStyle ? `?style_id=${filterStyle}` : '';
      const res = await fetch(`${API}/api/dewi/rnd/variants/sku-audit${qs}`, { headers: h });
      if (res.ok) setAudit(await res.json());
    } catch { /* ignore */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterStyle, token]);

  useEffect(() => { loadVariants(); loadAudit(); }, [loadVariants, loadAudit]);
  useEffect(() => { loadStyles(); loadColors(); }, [loadStyles, loadColors]);

  const loadSizeList = async (sid) => {
    if (!sid) { setSizes([]); setSizeMap([]); setSizeSource('default'); return []; }
    try {
      const res = await fetch(`${API}/api/dewi/rnd/styles/${sid}/size-list`, { headers: h });
      if (!res.ok) return [];
      const d = await res.json();
      setSizes(d.size_list || []);
      setSizeMap(d.size_map || []);
      setSizeSource(d.source || 'default');
      setSizeDirty(false);
      return d.size_list || [];
    } catch { return []; }
  };

  // ─────────────────────────── modal open ───────────────────────────
  const resetModal = () => {
    setColorRows([]); setMatrix({}); setStatus('active'); setNotes('');
    setSizes([]); setSizeMap([]); setSizeDirty(false); setSaving(false);
  };

  const openNew = async () => {
    const sel = styles.find(s => s.id === filterStyle);
    resetModal();
    setEditing(null);
    setStyleId(sel?.id || '');
    setStyleCode(sel?.style_code || '');
    setStyleName(sel?.style_name || '');
    setShowForm(true);
    if (sel?.id) await loadSizeList(sel.id);
    setColorRows([blankColorRow()]);
  };

  const openEdit = async (v) => {
    resetModal();
    setEditing(v.id);
    setStyleId(v.style_id || '');
    setStyleCode(v.style_code || '');
    setStyleName(v.style_name || '');
    setStatus(v.status || 'active');
    setNotes(v.notes || '');
    setShowForm(true);

    const list = await loadSizeList(v.style_id);
    const rows = sizeRows(v);
    const rowSizes = rows.map(s => s.size);
    const merged = rowSizes.length ? rowSizes : list;
    setSizes(merged);

    const key = v.color_id || codeOf(v) || 'legacy';
    setColorRows([{
      key,
      color_id: v.color_id || '',
      code: codeOf(v),
      name: v.color || '',
      hex: swatchOf(v),
      isNew: false,
      draft: { name: '', code: '', hex: '#4F46E5' },
    }]);
    const cell = {};
    rows.forEach(s => {
      cell[s.size] = { sku: s.sku || '', qty_plan: Number(s.qty_plan || 0) };
    });
    setMatrix({ [key]: cell });
  };

  const blankColorRow = () => ({
    key: `row-${Math.random().toString(36).slice(2, 9)}`,
    color_id: '', code: '', name: '', hex: '#9CA3AF',
    isNew: false, draft: { name: '', code: '', hex: '#4F46E5' },
  });

  const onStyleChange = async (sid) => {
    const sel = styles.find(s => s.id === sid);
    setStyleId(sid);
    setStyleCode(sel?.style_code || '');
    setStyleName(sel?.style_name || '');
    if (sid) await loadSizeList(sid);
  };

  // ─────────────────────────── color rows ───────────────────────────
  const addColorRow = () => setColorRows(rows => [...rows, blankColorRow()]);

  const removeColorRow = (key) => {
    setColorRows(rows => rows.filter(r => r.key !== key));
    setMatrix(m => { const n = { ...m }; delete n[key]; return n; });
  };

  const pickColor = (key, value) => {
    if (value === NEW_COLOR) {
      setColorRows(rows => rows.map(r => r.key === key
        ? { ...r, isNew: true, color_id: '', code: '', name: '' } : r));
      return;
    }
    const opt = colorOpts.find(c => c.color_id === value);
    if (!opt) return;
    if (colorRows.some(r => r.key !== key && r.color_id === opt.color_id)) {
      toast.error(`Warna "${opt.name}" sudah ada di daftar. Satu warna cukup satu baris.`);
      return;
    }
    const oldKey = key;
    setColorRows(rows => rows.map(r => r.key === key
      ? { ...r, isNew: false, color_id: opt.color_id, code: opt.code, name: opt.name, hex: opt.hex }
      : r));
    // SKU lama (dari warna sebelumnya) tidak boleh nyangkut
    setMatrix(m => ({ ...m, [oldKey]: {} }));
  };

  const setDraft = (key, field, val) =>
    setColorRows(rows => rows.map(r => r.key === key
      ? { ...r, draft: { ...r.draft, [field]: val } } : r));

  const saveNewColor = async (row) => {
    const name = (row.draft.name || '').trim();
    if (!name) return toast.error('Isi nama warna baru');
    try {
      const res = await fetch(`${API}/api/dewi/rnd/color-options`, {
        method: 'POST', headers: h,
        body: JSON.stringify({ name, code: (row.draft.code || '').trim(), hex: row.draft.hex }),
      });
      if (!res.ok) return toast.error(await readErr(res, 'Gagal menambah warna ke master'));
      const created = await res.json();
      setColorOpts(prev => [...prev, created]);
      setColorRows(rows => rows.map(r => r.key === row.key
        ? { ...r, isNew: false, color_id: created.color_id, code: created.code,
            name: created.name, hex: created.hex }
        : r));
      toast.success(`Warna "${created.name}" (${created.code}) ditambahkan ke master & terpilih`);
    } catch { toast.error('Gagal menambah warna ke master'); }
  };

  // ─────────────────────────── sizes ───────────────────────────
  const addSize = () => { setSizes(s => [...s, '']); setSizeDirty(true); };

  const renameSize = (idx, val) => {
    const old = sizes[idx];
    setSizes(prev => prev.map((s, i) => (i === idx ? val : s)));
    setSizeDirty(true);
    if (old && old !== val) {
      setMatrix(m => {
        const n = {};
        Object.entries(m).forEach(([ck, cell]) => {
          const c2 = { ...cell };
          if (Object.prototype.hasOwnProperty.call(c2, old)) {
            c2[val] = c2[old];
            delete c2[old];
          }
          n[ck] = c2;
        });
        return n;
      });
    }
  };

  const removeSize = (idx) => {
    const gone = sizes[idx];
    setSizes(prev => prev.filter((_, i) => i !== idx));
    setSizeDirty(true);
    setMatrix(m => {
      const n = {};
      Object.entries(m).forEach(([ck, cell]) => {
        const c2 = { ...cell }; delete c2[gone]; n[ck] = c2;
      });
      return n;
    });
  };

  const persistSizeList = async (silent = false) => {
    const clean = sizes.map(s => String(s || '').trim()).filter(Boolean);
    if (!styleId) { if (!silent) toast.error('Pilih style dulu'); return false; }
    if (clean.length === 0) { if (!silent) toast.error('Daftar ukuran tidak boleh kosong'); return false; }
    try {
      const res = await fetch(`${API}/api/dewi/rnd/styles/${styleId}/size-list`, {
        method: 'PUT', headers: h, body: JSON.stringify({ size_list: clean }),
      });
      if (!res.ok) { if (!silent) toast.error(await readErr(res, 'Gagal menyimpan daftar ukuran')); return false; }
      const d = await res.json();
      setSizes(d.size_list || clean);
      setSizeMap(d.size_map || []);
      setSizeSource(d.source || 'style');
      setSizeDirty(false);
      if (!silent) {
        toast.success(`Daftar ukuran style ${styleCode} disimpan (${(d.size_list || []).length} ukuran)`);
        if ((d.unmatched || []).length) {
          toast.warning(`Belum dipadankan ke master produksi: ${d.unmatched.join(', ')}`);
        }
      }
      return true;
    } catch { if (!silent) toast.error('Gagal menyimpan daftar ukuran'); return false; }
  };

  // ─────────────────────────── matrix cells ───────────────────────────
  const cellVal = (ck, size, field) => {
    const v = matrix[ck]?.[size];
    if (!v) return field === 'qty_plan' ? 0 : '';
    return v[field] ?? (field === 'qty_plan' ? 0 : '');
  };

  const setCell = (ck, size, field, val) => setMatrix(m => ({
    ...m,
    [ck]: { ...(m[ck] || {}), [size]: {
      ...(m[ck]?.[size] || { sku: '', qty_plan: 0 }),
      [field]: field === 'qty_plan' ? Number(val || 0) : val,
    } },
  }));

  const autoGenSKU = () => {
    const ready = colorRows.filter(r => r.code || r.name);
    if (!styleCode) return toast.error('Pilih style dulu (kode style dipakai di SKU)');
    if (ready.length === 0) return toast.error('Pilih minimal satu warna dulu');
    const clean = sizes.map(s => String(s || '').trim()).filter(Boolean);
    setMatrix(m => {
      const n = { ...m };
      ready.forEach(r => {
        const ck = r.key;
        n[ck] = { ...(n[ck] || {}) };
        clean.forEach(sz => {
          const prev = n[ck][sz] || { sku: '', qty_plan: 0 };
          n[ck][sz] = { ...prev, sku: canonicalSku(styleCode, r.code || r.name, sz) };
        });
      });
      return n;
    });
    toast.success('SKU dibuat otomatis mengikuti aturan {STYLE}-{KODE WARNA}-{UKURAN}');
  };

  // ─────────────────────────── save ───────────────────────────
  const handleSave = async () => {
    if (!styleId) return toast.error('Pilih style terlebih dahulu');
    const cleanSizes = sizes.map(s => String(s || '').trim()).filter(Boolean);
    if (cleanSizes.length === 0) return toast.error('Tambahkan minimal satu ukuran');

    const chosen = colorRows.filter(r => r.color_id || r.name);
    if (chosen.length === 0) return toast.error('Tambahkan minimal satu warna');
    const pending = colorRows.find(r => r.isNew && !r.color_id);
    if (pending) return toast.error('Ada warna baru yang belum disimpan ke master — klik "Simpan ke master"');

    setSaving(true);
    try {
      if (sizeDirty) await persistSizeList(true);

      if (editing) {
        const r = chosen[0];
        const body = {
          style_id: styleId, style_code: styleCode, style_name: styleName,
          color_id: r.color_id || undefined, color: r.name, color_code: r.code,
          color_hex: r.hex, status, notes,
          sizes: cleanSizes.map(sz => ({
            size: sz,
            sku: cellVal(r.key, sz, 'sku') || canonicalSku(styleCode, r.code || r.name, sz),
            qty_plan: Number(cellVal(r.key, sz, 'qty_plan') || 0),
          })),
        };
        const res = await fetch(`${API}/api/dewi/rnd/variants/${editing}`, {
          method: 'PUT', headers: h, body: JSON.stringify(body),
        });
        if (!res.ok) { toast.error(await readErr(res, 'Gagal memperbarui varian')); return; }
        toast.success('Varian diperbarui');
      } else {
        const mtx = {};
        chosen.forEach(r => {
          const id = r.color_id || r.code;
          mtx[id] = {};
          cleanSizes.forEach(sz => {
            mtx[id][sz] = {
              sku: cellVal(r.key, sz, 'sku') || '',
              qty_plan: Number(cellVal(r.key, sz, 'qty_plan') || 0),
            };
          });
        });
        const body = {
          style_id: styleId, style_code: styleCode, style_name: styleName,
          colors: chosen.map(r => ({ color_id: r.color_id, code: r.code, name: r.name, hex: r.hex })),
          sizes: cleanSizes, matrix: mtx, status, notes,
        };
        const res = await fetch(`${API}/api/dewi/rnd/variants/bulk`, {
          method: 'POST', headers: h, body: JSON.stringify(body),
        });
        if (!res.ok) { toast.error(await readErr(res, 'Gagal menyimpan varian'), { duration: 7000 }); return; }
        const out = await res.json();
        toast.success(`${out.created_count} varian dibuat (${chosen.length} warna × ${cleanSizes.length} ukuran)`);
      }
      setShowForm(false);
      loadVariants();
      loadAudit();
    } catch { toast.error('Gagal menyimpan varian'); }
    finally { setSaving(false); }
  };

  const handleDelete = async (v) => {
    const ok = await confirmDialog({
      title: 'Hapus varian ini?',
      body: `${v.color || 'Varian'} · ${v.style_code || ''} dihapus permanen.`,
      confirmLabel: 'Hapus', danger: true,
    });
    if (!ok) return;
    try {
      const res = await fetch(`${API}/api/dewi/rnd/variants/${v.id}`, { method: 'DELETE', headers: h });
      if (!res.ok) { toast.error(await readErr(res, 'Gagal menghapus')); return; }
      toast.success('Varian dihapus');
      setDetail(null);
      loadVariants(); loadAudit();
    } catch { toast.error('Gagal menghapus'); }
  };

  const fixSku = async (vid) => {
    setFixing(vid);
    try {
      const res = await fetch(`${API}/api/dewi/rnd/variants/${vid}/fix-sku`, { method: 'POST', headers: h });
      if (!res.ok) { toast.error(await readErr(res, 'Gagal memperbaiki SKU')); return; }
      const out = await res.json();
      toast.success(`${out.changed_count} SKU diperbaiki mengikuti aturan`);
      loadVariants(); loadAudit();
    } catch { toast.error('Gagal memperbaiki SKU'); }
    finally { setFixing(''); }
  };

  const filtered = variants.filter(v => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (v.color || '').toLowerCase().includes(q)
      || (v.color_code || '').toLowerCase().includes(q)
      || (v.style_code || '').toLowerCase().includes(q)
      || (v.style_name || '').toLowerCase().includes(q);
  });

  const unmatchedSizes = new Set((sizeMap || []).filter(m => !m.matched).map(m => m.size));
  const activeColors = colorRows.filter(r => r.color_id || r.name);
  const cleanSizesView = sizes;

  // Tampilan saja: varian yang belum punya hex memakai hex master warnanya (data dari /color-options).
  const hexMaster = useMemo(() => Object.fromEntries((colorOpts || []).map(c => [c.color_id, c.hex])), [colorOpts]);
  const warnaTampil = (v) => {
    const hx = String(v?.color_hex || '').trim();
    if (hx.startsWith('#')) return hx;
    const legacy = String(v?.color_code || '').trim();
    if (legacy.startsWith('#')) return legacy;
    return hexMaster[v?.color_id] || null;
  };

  const { page, setPage, totalPages, total, paged } = useClientPagination(filtered, PER_HALAMAN);
  const muatUlang = () => { loadVariants(); loadAudit(); };
  const adaAudit = audit && (audit.drift_variants > 0 || audit.colors_not_in_master > 0);

  const kolom = [
    { kunci: 'warna', label: 'Warna', hp: 'judul', isi: (v) => (
      <span className="inline-flex items-center gap-2">
        <Swatch hex={warnaTampil(v)} />
        <span className="font-medium">{v.color || '(tanpa nama)'}</span>
        {codeOf(v) && <span className="text-xs text-muted-foreground">{codeOf(v)}</span>}
      </span>) },
    { kunci: 'style', label: 'Style', hp: 'keterangan', isi: (v) => (
      <span className="text-sm"><span className="tabular-nums">{v.style_code}</span>{v.style_name ? ` — ${v.style_name}` : ''}</span>) },
    { kunci: 'ukuran', label: 'Ukuran', isi: (v) => sizeRows(v).map(s => s.size).join(', ') || '—' },
    { kunci: 'sku', label: 'SKU', isi: (v) => {
      const n = sizeRows(v).length;
      const kurang = skuKurang(v);
      if (!n) return <span className="text-muted-foreground">—</span>;
      return kurang
        ? <span className="text-[hsl(var(--warning-text))]">{kurang} belum dibuat</span>
        : <span className="tabular-nums">{n} SKU</span>;
    } },
    { kunci: 'qty', label: 'Qty rencana', rata: 'kanan', isi: (v) => {
      const q = qtyTotal(v);
      return q > 0 ? <span className="tabular-nums">{q} pcs</span> : <span className="text-muted-foreground">—</span>;
    } },
    { kunci: 'status', label: 'Status', isi: (v) => <StatusBadge status={v.status} label={statusOf(v.status).label} tone={statusOf(v.status).tone} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (v) => (
      <div className="flex items-center justify-end gap-1">
        <Button variant="ghost" size="icon-sm" onClick={() => openEdit(v)} title="Ubah varian" aria-label="Ubah varian"
          data-testid={`rnd-variant-edit-${v.id}`}>
          <Pencil />
        </Button>
        <Button variant="ghost" size="icon-sm" onClick={() => handleDelete(v)} title="Hapus varian" aria-label="Hapus varian"
          className="text-[hsl(var(--danger-text))]" data-testid={`rnd-variant-del-${v.id}`}>
          <Trash2 />
        </Button>
      </div>) },
  ];

  const kolomUnduh = [
    { label: 'Kode style', nilai: (v) => v.style_code || '' },
    { label: 'Nama style', nilai: (v) => v.style_name || '' },
    { label: 'Warna', nilai: (v) => v.color || '' },
    { label: 'Kode warna', nilai: (v) => codeOf(v) },
    { label: 'Ukuran', nilai: (v) => sizeRows(v).map(s => s.size).join(', ') },
    { label: 'SKU', nilai: (v) => sizeRows(v).map(s => s.sku).filter(Boolean).join(', ') },
    { label: 'SKU belum dibuat', nilai: (v) => skuKurang(v) },
    { label: 'Qty rencana (pcs)', nilai: (v) => qtyTotal(v) },
    { label: 'Status', nilai: (v) => statusOf(v.status).label },
    { label: 'Catatan', nilai: (v) => v.notes || '' },
  ];

  const auditBaris = (audit?.items || []).flatMap(it => (it.rows || []).filter(r => !r.ok).map(r => ({ ...r, it })));

  return (
    <PageLayout testId="rnd-variant-module" title="Varian produk"
      subtitle={`Warna dari master × ukuran per style; SKU mengikuti aturan ${aturanTeks(audit?.convention)}.`}
      actions={<Button onClick={openNew} data-testid="rnd-variant-add-btn"><Plus />Tambah varian</Button>}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Cari warna, kode, atau style" className="pl-8" data-testid="rnd-variant-search" />
        </div>
        <SmartNativeSelect value={filterStyle} onChange={e => setFilterStyle(e.target.value)}
          className="w-56" wrapperClassName="w-56" aria-label="Style" data-testid="rnd-variant-filter-style">
          <option value="">Semua style</option>
          {styles.map(s => <option key={s.id} value={s.id}>{s.style_code} — {s.style_name}</option>)}
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="varian-produk-rnd" namaLembar="Varian" baris={filtered} kolom={kolomUnduh}
          testId="rnd-variant-unduh" />
        <Button variant="outline" size="icon" onClick={muatUlang} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={adaAudit ? (
        <Notice tone="warning" icon={AlertTriangle} testId="rnd-sku-audit-banner"
          title={`${audit.drift_rows} SKU tidak sesuai aturan${audit.colors_not_in_master > 0 ? ` · ${audit.colors_not_in_master} varian warnanya belum ada di master` : ''}`}
          action={(
            <Button variant="outline" size="sm" onClick={() => setShowAudit(true)} data-testid="rnd-sku-audit-toggle">
              Lihat {audit.items.length} varian
            </Button>
          )}>
          Aturan: <span className="tabular-nums">{aturanTeks(audit.convention)}</span>. SKU lama tidak diubah otomatis —
          perbaiki per varian supaya Anda yang memutuskan.
        </Notice>
      ) : null}
      footer={!loading && filtered.length > PER_HALAMAN ? (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={PER_HALAMAN} onPageChange={setPage} />
      ) : null}>
      {loading && variants.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat varian…</p>
      ) : (
        <TabelData kolom={kolom} baris={paged} onKlikBaris={setDetail} testId="rnd-variant-table"
          kosong={<EmptyState title={variants.length ? 'Tidak ada varian yang cocok' : 'Belum ada varian produk'}
            description={variants.length ? 'Ubah kata pencarian atau pilihan style.' : 'Tambah varian: pilih style, warna dari master, lalu ukuran.'}
            action={!variants.length && <Button onClick={openNew}><Plus />Tambah varian</Button>} />} />
      )}

      {/* ── Rincian satu varian ── */}
      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} testId="rnd-variant-detail"
          judul={`${detail.color || 'Varian'} · ${detail.style_code || ''}`}
          keterangan={detail.style_name}
          status={<StatusBadge status={detail.status} label={statusOf(detail.status).label} tone={statusOf(detail.status).tone} />}
          aksi={<>
            <Button size="sm" variant="outline" onClick={() => { const v = detail; setDetail(null); openEdit(v); }}><Pencil />Ubah</Button>
            <Button size="sm" variant="destructive" onClick={() => handleDelete(detail)}><Trash2 />Hapus</Button>
          </>}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Style">{detail.style_code} — {detail.style_name}</BarisDetail>
            <BarisDetail label="Warna">
              <span className="inline-flex items-center gap-2"><Swatch hex={warnaTampil(detail)} />{detail.color || '—'}
                {codeOf(detail) && <span className="text-xs text-muted-foreground">{codeOf(detail)}</span>}</span>
            </BarisDetail>
            {detail.notes && <BarisDetail label="Catatan">{detail.notes}</BarisDetail>}
          </dl>
          <TabelData baris={sizeRows(detail)} kunci={(s) => s.size} testId="rnd-variant-detail-sizes"
            kosong={<EmptyState title="Varian ini belum punya ukuran." className="py-6" />}
            kolom={[
              { kunci: 'size', label: 'Ukuran', hp: 'judul', isi: (s) => <span className="font-medium">{s.size}</span> },
              { kunci: 'sku', label: 'SKU', isi: (s) => (s.sku
                ? <span className="text-xs">{s.sku}</span>
                : <span className="text-[hsl(var(--warning-text))]">SKU belum dibuat</span>) },
              { kunci: 'qty', label: 'Qty rencana', rata: 'kanan', isi: (s) => <span className="tabular-nums">{Number(s.qty_plan) || 0} pcs</span> },
            ]} />
        </DetailPopup>
      )}

      {/* ── SKU tidak sesuai aturan ── */}
      {showAudit && adaAudit && (
        <DetailPopup open onClose={() => setShowAudit(false)} testId="rnd-sku-audit-panel"
          judul="SKU tidak sesuai aturan"
          keterangan={`Aturan: ${aturanTeks(audit.convention)}. Perbaiki per varian.`}
          aksi={(
            <TombolUnduh namaBerkas="sku-tidak-sesuai-aturan" namaLembar="SKU" baris={auditBaris} testId="rnd-sku-audit-unduh"
              kolom={[
                { label: 'Style', nilai: (r) => r.it.style_code || '' },
                { label: 'Warna', nilai: (r) => r.it.color || '' },
                { label: 'Kode warna', nilai: (r) => r.it.color_code || '' },
                { label: 'Warna ada di master', nilai: (r) => (r.it.color_in_master ? 'Ya' : 'Belum') },
                { label: 'Ukuran', nilai: (r) => r.size },
                { label: 'SKU sekarang', nilai: (r) => r.sku_now || '' },
                { label: 'SKU seharusnya', nilai: (r) => r.sku_canonical || '' },
              ]} />
          )}>
          <TabelData baris={audit.items} kunci={(it) => it.variant_id} testId="rnd-sku-audit-table"
            kolom={[
              { kunci: 'warna', label: 'Warna', hp: 'judul', isi: (it) => (
                <span className="inline-flex items-center gap-2"><Swatch hex={it.color_hex} />{it.color || '(tanpa nama)'}</span>) },
              { kunci: 'master', label: 'Master warna', isi: (it) => (it.color_in_master
                ? <span className="text-xs">{it.color_code}</span>
                : <StatusBadge status="missing" label="Belum ada di master" tone="danger" />) },
              { kunci: 'style', label: 'Style', isi: (it) => <span className="text-sm">{it.style_code}</span> },
              { kunci: 'salah', label: 'SKU sekarang → seharusnya', isi: (it) => (
                <div className="space-y-0.5">
                  {(it.rows || []).filter(r => !r.ok).map((r, i) => (
                    <p key={i} className="text-xs">
                      <span className="font-medium">{r.size}:</span>{' '}
                      <span className="text-[hsl(var(--danger-text))] line-through">{r.sku_now || '—'}</span>{' → '}
                      <span className="text-[hsl(var(--success-text))]">{r.sku_canonical || '—'}</span>
                    </p>
                  ))}
                </div>) },
              { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (it) => (
                <Button size="sm" variant="outline" disabled={fixing === it.variant_id}
                  onClick={() => fixSku(it.variant_id)} data-testid={`rnd-sku-fix-${it.variant_id}`}>
                  <Wrench />{fixing === it.variant_id ? 'Memperbaiki…' : 'Perbaiki SKU'}
                </Button>) },
            ]} />
        </DetailPopup>
      )}

      {/* ───────────────────────── Form ───────────────────────── */}
      <FormPopup open={showForm} onClose={() => setShowForm(false)} ukuran="panjang" onSimpan={handleSave}
        menyimpan={saving} testId="rnd-variant-form"
        judul={editing ? 'Ubah varian' : 'Tambah varian'}
        keterangan={editing ? undefined : 'Bisa banyak warna sekaligus: satu varian dibuat per warna.'}
        labelSimpan={editing ? 'Simpan' : `Simpan ${activeColors.length || ''} varian`.replace('  ', ' ')}>
        <Isian label="Style produk" wajib>
          <SmartNativeSelect value={styleId} onChange={e => onStyleChange(e.target.value)}
            className="w-full" aria-label="Style produk" data-testid="rnd-variant-style-select">
            <option value="">— Pilih style —</option>
            {styles.map(s => <option key={s.id} value={s.id}>{s.style_code} — {s.style_name}</option>)}
          </SmartNativeSelect>
        </Isian>

        {/* ── WARNA (multi) ── */}
        <div className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="flex items-center gap-1.5 text-sm font-medium text-foreground">
              <Palette className="h-4 w-4" /> Warna
              {!editing && <span className="text-xs font-normal text-muted-foreground">(bisa lebih dari satu)</span>}
            </p>
            {!editing && (
              <Button type="button" variant="outline" size="sm" onClick={addColorRow} data-testid="rnd-variant-add-color">
                <Plus /> Tambah warna
              </Button>
            )}
          </div>

          <div className="divide-y divide-[var(--glass-border)] rounded-lg border border-[var(--glass-border)]">
            {colorRows.length === 0 && (
              <p className="p-4 text-center text-sm text-muted-foreground">Warna belum dipilih. Klik "Tambah warna".</p>
            )}
            {colorRows.map((r, idx) => (
              <div key={r.key} className="p-3" data-testid={`rnd-variant-color-row-${idx}`}>
                <div className="flex items-center gap-2">
                  <Swatch hex={r.hex} className="h-7 w-7 rounded-md" />
                  <SmartNativeSelect
                    value={r.isNew ? NEW_COLOR : (r.color_id || '')}
                    onChange={e => pickColor(r.key, e.target.value)}
                    className="w-full" wrapperClassName="min-w-0 flex-1" aria-label="Warna dari master"
                    data-testid={`rnd-variant-color-select-${idx}`}>
                    <option value="">— Pilih warna dari master —</option>
                    {colorOpts.map(c => (
                      <option key={c.color_id} value={c.color_id}>{`${c.name} (${c.code})`}</option>
                    ))}
                    <option value={NEW_COLOR}>+ Warna baru…</option>
                  </SmartNativeSelect>
                  {r.code && <span className="text-xs text-muted-foreground">{r.code}</span>}
                  {!editing && (
                    <Button type="button" variant="ghost" size="icon-sm" onClick={() => removeColorRow(r.key)}
                      className="text-[hsl(var(--danger-text))]" title="Hapus baris warna" aria-label="Hapus baris warna"
                      data-testid={`rnd-variant-del-color-${idx}`}>
                      <Trash2 />
                    </Button>
                  )}
                </div>

                {r.isNew && (
                  <div className="mt-2 space-y-1.5 sm:ml-9">
                    <div className="flex flex-wrap items-center gap-2">
                      <Input value={r.draft.name} onChange={e => setDraft(r.key, 'name', e.target.value)}
                        placeholder="Nama warna baru (mis. Biru dongker)" className="min-w-0 flex-1 basis-48"
                        aria-label="Nama warna baru" data-testid={`rnd-variant-new-color-name-${idx}`} />
                      <Input value={r.draft.code} onChange={e => setDraft(r.key, 'code', e.target.value.toUpperCase())}
                        placeholder="Kode" className="w-24" aria-label="Kode warna"
                        data-testid={`rnd-variant-new-color-code-${idx}`} />
                      <input type="color" value={r.draft.hex} aria-label="Contoh warna"
                        onChange={e => setDraft(r.key, 'hex', e.target.value)}
                        className="h-9 w-11 cursor-pointer rounded border border-input bg-background" />
                      <Button type="button" size="sm" variant="success" onClick={() => saveNewColor(r)}
                        data-testid={`rnd-variant-save-color-${idx}`}>
                        <Save /> Simpan ke master
                      </Button>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Kode dipakai di SKU (mis. NVY). Warna ini ditulis ke master warna yang sama dengan produksi
                      &amp; gudang — tidak perlu pindah menu.
                    </p>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* ── UKURAN & SKU (matriks warna × ukuran) ── */}
        <div className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="flex flex-wrap items-center gap-1.5 text-sm font-medium text-foreground">
              <Ruler className="h-4 w-4" /> Ukuran &amp; SKU
              <span className="text-xs font-normal text-muted-foreground">
                {sizeSource === 'default' ? '(daftar bawaan — simpan untuk jadikan milik style ini)' : `(daftar style ${styleCode})`}
              </span>
            </p>
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline" size="sm" onClick={addSize} data-testid="rnd-variant-add-size">
                <Plus /> Tambah ukuran
              </Button>
              <Button type="button" variant="outline" size="sm" onClick={() => persistSizeList(false)}
                disabled={!styleId} data-testid="rnd-variant-save-sizes">
                <Save /> Simpan daftar ukuran{sizeDirty ? ' *' : ''}
              </Button>
              <Button type="button" variant="outline" size="sm" onClick={autoGenSKU} data-testid="rnd-variant-autogen-sku">
                Buat SKU otomatis
              </Button>
            </div>
          </div>

          {sizeDirty && (
            <Notice tone="warning">Daftar ukuran berubah — ikut tersimpan ke style saat Anda menekan Simpan.</Notice>
          )}

          <div className="rounded-lg border border-[var(--glass-border)]">
            <Table data-testid="rnd-variant-matrix">
              <TableHeader>
                <TableRow>
                  <TableHead rowSpan={2} className="w-56 align-bottom">Ukuran</TableHead>
                  {activeColors.map(r => (
                    <TableHead key={r.key} colSpan={2} className="border-l border-[var(--glass-border)] text-center">
                      <span className="inline-flex items-center gap-1.5">
                        <Swatch hex={r.hex} className="h-3 w-3" />
                        {r.name || '(warna)'}{r.code ? ` · ${r.code}` : ''}
                      </span>
                    </TableHead>
                  ))}
                  <TableHead rowSpan={2} className="w-9" />
                </TableRow>
                <TableRow>
                  {activeColors.map(r => (
                    <Fragment key={`hdr-${r.key}`}>
                      <TableHead className="h-8 border-l border-[var(--glass-border)] text-xs">SKU</TableHead>
                      <TableHead className="h-8 w-20 text-right text-xs">Qty</TableHead>
                    </Fragment>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {cleanSizesView.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={2 + activeColors.length * 2} className="py-6 text-center text-sm text-muted-foreground">
                      Belum ada ukuran. Klik "Tambah ukuran" — bebas, boleh "All Size" atau "28/30".
                    </TableCell>
                  </TableRow>
                )}
                {cleanSizesView.map((sz, i) => (
                  <TableRow key={i}>
                    <TableCell>
                      <div className="flex items-center gap-1.5">
                        <Input value={sz} onChange={e => renameSize(i, e.target.value)}
                          placeholder="Ukuran" className="h-8 min-w-[72px] text-sm font-medium" aria-label="Ukuran"
                          data-testid={`rnd-variant-size-input-${i}`} />
                        {unmatchedSizes.has(sz) && (
                          <span title="Belum ada di master ukuran produksi — nanti perlu dipadankan saat masuk PO produksi">
                            <StatusBadge status="unmatched" label="Belum dipadankan" tone="warning" />
                          </span>
                        )}
                      </div>
                    </TableCell>
                    {activeColors.map(r => (
                      <Fragment key={`${r.key}-${i}`}>
                        <TableCell className="border-l border-[var(--glass-border)]">
                          <Input value={cellVal(r.key, sz, 'sku')}
                            onChange={e => setCell(r.key, sz, 'sku', e.target.value)}
                            placeholder={canonicalSku(styleCode, r.code || r.name, sz) || 'SKU'}
                            className="h-8 text-xs" aria-label={`SKU ${sz}`}
                            data-testid={`rnd-variant-sku-${i}-${r.code || r.key}`} />
                        </TableCell>
                        <TableCell>
                          <Input type="number" min="0" value={cellVal(r.key, sz, 'qty_plan')}
                            onChange={e => setCell(r.key, sz, 'qty_plan', e.target.value)}
                            className="h-8 text-right text-sm tabular-nums" aria-label={`Qty ${sz}`}
                            data-testid={`rnd-variant-qty-${i}-${r.code || r.key}`} />
                        </TableCell>
                      </Fragment>
                    ))}
                    <TableCell className="px-1">
                      <Button type="button" variant="ghost" size="icon-sm" onClick={() => removeSize(i)}
                        className="text-[hsl(var(--danger-text))]" title="Hapus ukuran" aria-label="Hapus ukuran"
                        data-testid={`rnd-variant-del-size-${i}`}>
                        <X />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {!editing && activeColors.length > 0 && cleanSizesView.length > 0 && (
            <p className="flex items-center gap-1 text-xs text-muted-foreground">
              <CheckCircle2 className="h-3.5 w-3.5 text-[hsl(var(--success-text))]" />
              Simpan akan membuat <b className="text-foreground">{activeColors.length} varian</b>
              {' '}(satu per warna), masing-masing dengan {cleanSizesView.length} ukuran.
            </p>
          )}
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Status">
            <SmartNativeSelect value={status} onChange={e => setStatus(e.target.value)}
              className="w-full" aria-label="Status" data-testid="rnd-variant-status">
              {STATUS_OPTS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Catatan" htmlFor="rnd-variant-notes">
            <Input id="rnd-variant-notes" value={notes} onChange={e => setNotes(e.target.value)}
              data-testid="rnd-variant-notes" />
          </Isian>
        </div>
      </FormPopup>
    </PageLayout>
  );
}

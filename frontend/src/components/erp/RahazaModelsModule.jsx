import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Plus, Edit2, Trash2, X, Upload, Camera, FileText, Video, Image as ImageIcon,
  ArrowUp, ArrowDown, Link2, ListChecks, BookOpen, Info, Wand2, AlertTriangle,
} from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import Modal from './Modal';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup from '@/components/ui/detail-popup';
import { Checkbox } from '@/components/ui/checkbox';
import { DataTable } from './DataTableV2';
import { PageHeader, EmptyState, Notice } from './moduleAtoms';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import ImportExportToolbar from './ImportExportToolbar';
import { toast } from 'sonner';
import { readField, readNumber, FIELD } from '@/lib/materialFields';  // FASE 6.6-B
import { MoneyInput } from '@/components/ui/money-input';

// Kotak uang bergaya GlassInput (latar & tinggi sama dengan kolom lain di form ini).

// F3 — kategori TIDAK LAGI hardcode. Dulu daftar ini hidup di 4 tempat berbeda
// dengan isi berbeda (Master Produk · Buyer Catalog Maklon · AI Quote · seeder),
// dan servernya menerima teks apa pun di luar daftar. Sekarang satu master:
// GET /api/rahaza/product-categories.
const DEFAULT_FORM = {
  code: '', name: '', category_id: '', material_kg_per_pcs: 0, bundle_size: 30,
  description: '', base_hpp: 0, retail_price: 0, weight_gram: 0,
};
const MAX_PHOTOS = 8;

const IMAGE_FALLBACK = `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='48' height='48' viewBox='0 0 24 24' fill='none' stroke='%23cbd5e1' stroke-width='1.5'%3E%3Crect x='3' y='3' width='18' height='18' rx='2'/%3E%3Ccircle cx='8.5' cy='8.5' r='1.5'/%3E%3Cpath d='M21 15l-5-5L5 21'/%3E%3C/svg%3E`;

const fileUrl = (path, token) => `/api/files/${path}?auth=${encodeURIComponent(token)}`;

const rupiah = (v) => {
  const n = Number(v || 0);
  if (!n) return '—';
  return `Rp ${n.toLocaleString('id-ID')}`;
};

const HPP_SOURCE_LABEL = {
  // 2026-08-23 — sumber baru & DIDAHULUKAN: HPP lahir dari BOM × harga pembelian
  // + upah CMT/cutting (layar "HPP per Potong"), bukan ketikan master.
  bom: { text: 'BOM + pembelian', cls: 'bg-[hsl(var(--success)/0.1)] border-[hsl(var(--success)/0.4)] text-[hsl(var(--success-text))] ' },
  rnd: { text: 'dari R&D', cls: 'bg-[hsl(var(--primary)/0.1)] border-[hsl(var(--primary)/0.4)] text-[hsl(var(--primary))] ' },
  manual: { text: 'manual', cls: 'bg-[hsl(var(--warning)/0.1)] border-[hsl(var(--warning)/0.4)] text-[hsl(var(--warning-text))] ' },
  none: { text: 'belum ada', cls: 'bg-[hsl(var(--destructive)/0.1)] border-[hsl(var(--destructive)/0.4)] text-[hsl(var(--danger-text))] ' },
};

function HppCell({ row }) {
  const src = HPP_SOURCE_LABEL[row?.hpp_source] || HPP_SOURCE_LABEL.none;
  const val = Number(row?.hpp || 0);
  return (
    <div className="flex flex-col gap-0.5" data-testid={`model-hpp-${row?.code}`}>
      <span className={val ? 'text-foreground font-medium' : 'text-muted-foreground'}>{rupiah(val)}</span>
      <span className={`text-xs px-1.5 py-0.5 rounded-full border w-fit ${src.cls}`}>{src.text}</span>
    </div>
  );
}

function ytId(url) {
  const m = String(url || '').match(/(?:youtu\.be\/|youtube\.com\/(?:watch\?v=|embed\/|shorts\/))([\w-]{11})/);
  return m ? m[1] : null;
}

function ImageThumb({ path, token, onDelete, large = false }) {
  const url = useMemo(() => fileUrl(path, token), [path, token]);
  const sz = large ? 'w-24 h-24' : 'w-12 h-12';
  return (
    <div className={`relative group ${sz} rounded-lg overflow-hidden border border-[var(--glass-border)]`}>
      <img src={url} alt="model" className="w-full h-full object-cover"
        onError={(e) => { e.target.src = IMAGE_FALLBACK; e.target.style.objectFit = 'contain'; e.target.style.padding = '6px'; }} />
      {onDelete && (
        <button type="button" onClick={onDelete}
          className="absolute top-0.5 right-0.5 p-1 rounded-full bg-[hsl(var(--destructive)/0.9)] text-white opacity-0 group-hover:opacity-100 transition-opacity"
          data-testid="model-image-delete" title="Hapus foto">
          <X className="w-3 h-3" />
        </button>
      )}
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// PANDUAN PRODUKSI DIALOG — Foto Produk + SOP langkah + Video/Referensi
// ════════════════════════════════════════════════════════════════════════════
function PanduanProduksiDialog({ model, token, onClose, onUpdated }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);
  const [tab, setTab] = useState('foto');
  const [paths, setPaths] = useState(model.image_paths || []);
  const [steps, setSteps] = useState(() =>
    (model.sop_steps || []).map((s) => ({
      id: s.id || crypto.randomUUID(), title: s.title || '', description: s.description || '', image_path: s.image_path || '',
    }))
  );
  const [videos, setVideos] = useState(() => (model.reference_videos || []).map((v) => ({ url: v.url || '', title: v.title || '' })));
  const [refImages, setRefImages] = useState(() => (model.reference_images || []).map((v) => ({ url: v.url || '', caption: v.caption || '' })));
  const [uploading, setUploading] = useState(false);
  const [stepUploading, setStepUploading] = useState(null);
  const [saving, setSaving] = useState(false);

  // ── Foto Produk ────────────────────────────────────────────────────────────
  const handleUploadPhoto = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (paths.length >= MAX_PHOTOS) { toast.error(`Maksimal ${MAX_PHOTOS} foto per model`); return; }
    setUploading(true);
    try {
      const fd = new FormData(); fd.append('file', file);
      const r = await fetch(`/api/rahaza/models/${model.id}/images`, { method: 'POST', headers, body: fd });
      if (!r.ok) { const err = await r.json().catch(() => ({})); toast.error(err.detail || 'Upload gagal'); return; }
      const data = await r.json();
      setPaths(data.image_paths || []);
      toast.success('Foto diupload');
      onUpdated && onUpdated();
    } finally { setUploading(false); e.target.value = ''; }
  };

  const handleDeletePhoto = async (path) => {
    if (!(await confirmDialog({ title: 'Hapus foto ini?', confirmLabel: 'Hapus', danger: true }))) return;
    const r = await fetch(`/api/rahaza/models/${model.id}/images`, {
      method: 'DELETE', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify({ storage_path: path }),
    });
    if (r.ok) { const data = await r.json(); setPaths(data.image_paths || []); toast.success('Foto dihapus'); onUpdated && onUpdated(); }
    else toast.error('Gagal menghapus foto');
  };

  // ── SOP langkah ──────────────────────────────────────────────────────────────
  const addStep = () => setSteps((s) => [...s, { id: crypto.randomUUID(), title: '', description: '', image_path: '' }]);
  const removeStep = (idx) => setSteps((s) => s.filter((_, i) => i !== idx));
  const updateStep = (idx, patch) => setSteps((s) => s.map((st, i) => (i === idx ? { ...st, ...patch } : st)));
  const moveStep = (idx, dir) => setSteps((s) => {
    const j = idx + dir; if (j < 0 || j >= s.length) return s;
    const c = [...s]; [c[idx], c[j]] = [c[j], c[idx]]; return c;
  });

  const uploadStepPhoto = async (idx, file) => {
    if (!file) return;
    setStepUploading(idx);
    try {
      const fd = new FormData(); fd.append('file', file);
      const r = await fetch(`/api/rahaza/models/${model.id}/sop-image`, { method: 'POST', headers, body: fd });
      if (!r.ok) { const err = await r.json().catch(() => ({})); toast.error(err.detail || 'Upload gagal'); return; }
      const data = await r.json();
      updateStep(idx, { image_path: data.storage_path });
      toast.success('Foto langkah diupload');
    } finally { setStepUploading(null); }
  };

  // ── Video & Referensi ─────────────────────────────────────────────────────────
  const addVideo = () => setVideos((v) => [...v, { url: '', title: '' }]);
  const removeVideo = (idx) => setVideos((v) => v.filter((_, i) => i !== idx));
  const updateVideo = (idx, patch) => setVideos((v) => v.map((it, i) => (i === idx ? { ...it, ...patch } : it)));
  const addRefImage = () => setRefImages((v) => [...v, { url: '', caption: '' }]);
  const removeRefImage = (idx) => setRefImages((v) => v.filter((_, i) => i !== idx));
  const updateRefImage = (idx, patch) => setRefImages((v) => v.map((it, i) => (i === idx ? { ...it, ...patch } : it)));

  const saveSop = async () => {
    setSaving(true);
    try {
      const r = await fetch(`/api/rahaza/models/${model.id}/sop`, {
        method: 'PUT', headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ sop_steps: steps, reference_videos: videos, reference_images: refImages }),
      });
      if (!r.ok) { const err = await r.json().catch(() => ({})); toast.error(err.detail || 'Gagal menyimpan'); return; }
      toast.success('Panduan Produksi tersimpan');
      onUpdated && onUpdated();
      onClose();
    } finally { setSaving(false); }
  };

  return (
    // Standar UI/UX v2: FormPopup panjang — kaki Batal · Simpan panduan (hijau).
    <FormPopup open onClose={onClose} ukuran="panjang" testId="panduan-produksi-popup" onSimpan={saveSop} menyimpan={saving}
      judul={`Panduan produksi ${model.code} — ${model.name}`} labelSimpan="Simpan panduan (SOP + video)">
      <div className="space-y-4" data-testid="panduan-produksi-dialog">
        <FilterChips value={tab} onChange={setTab} testId="panduan-tab" ariaLabel="Bagian panduan produksi" hideWhenEmpty={false}
          options={[
            { key: 'foto', label: 'Foto produk', icon: Camera, count: paths.length },
            { key: 'sop', label: 'SOP produksi', icon: ListChecks, count: steps.length },
            { key: 'video', label: 'Video & referensi', icon: Video, count: videos.length + refImages.length },
          ]} />

        {/* ── FOTO ── */}
        {tab === 'foto' && (
          <div className="space-y-3" data-testid="panduan-foto-tab">
            <p className="text-sm text-muted-foreground">
              Upload sampai <b>{MAX_PHOTOS} foto jadi / referensi</b> (max 5MB). Tampil di LKP & Portal Vendor CMT.
            </p>
            <div className="grid grid-cols-4 sm:grid-cols-6 gap-3">
              {paths.map((p) => <ImageThumb key={p} path={p} token={token} large onDelete={() => handleDeletePhoto(p)} />)}
              {paths.length < MAX_PHOTOS && (
                <label className="w-24 h-24 rounded-lg border-2 border-dashed border-[var(--glass-border)] flex flex-col items-center justify-center gap-1 cursor-pointer hover:border-primary hover:bg-[var(--glass-bg-hover)] transition-colors"
                  data-testid="model-image-upload-label">
                  {uploading ? <span className="text-xs text-muted-foreground">Uploading...</span> : (<>
                    <Upload className="w-5 h-5 text-muted-foreground" />
                    <span className="text-xs text-muted-foreground">Tambah foto</span>
                  </>)}
                  <input type="file" accept="image/*" className="hidden" disabled={uploading} onChange={handleUploadPhoto} data-testid="model-image-upload-input" />
                </label>
              )}
            </div>
            <div className="text-xs text-muted-foreground">{paths.length}/{MAX_PHOTOS} foto · JPG, PNG, WebP. (Tersimpan otomatis)</div>
          </div>
        )}

        {/* ── SOP ── */}
        {tab === 'sop' && (
          <div className="space-y-3" data-testid="panduan-sop-tab">
            <p className="text-sm text-muted-foreground">
              Tata cara pembuatan model — langkah berurutan. Vendor CMT membaca ini untuk tahu cara produksi.
            </p>
            <div className="space-y-3 max-h-[45vh] overflow-y-auto pr-1">
              {steps.map((st, idx) => (
                <GlassCard key={st.id} className="p-3" data-testid={`sop-step-${idx}`}>
                  <div className="flex items-start gap-3">
                    <div className="flex flex-col items-center gap-1 pt-1">
                      <span className="w-6 h-6 rounded-full bg-primary/15 text-primary text-xs font-bold flex items-center justify-center">{idx + 1}</span>
                      <Button type="button" variant="ghost" size="icon-sm" onClick={() => moveStep(idx, -1)} disabled={idx === 0} title="Naik" aria-label="Naik"><ArrowUp className="w-3.5 h-3.5" /></Button>
                      <Button type="button" variant="ghost" size="icon-sm" onClick={() => moveStep(idx, 1)} disabled={idx === steps.length - 1} title="Turun" aria-label="Turun"><ArrowDown className="w-3.5 h-3.5" /></Button>
                    </div>
                    <div className="flex-1 space-y-2">
                      <GlassInput value={st.title} onChange={(e) => updateStep(idx, { title: e.target.value })}
                        placeholder="Judul langkah (cth: Potong kain sesuai pola)" data-testid={`sop-step-${idx}-title`} />
                      <textarea value={st.description} onChange={(e) => updateStep(idx, { description: e.target.value })}
                        placeholder="Deskripsi / instruksi detail..." rows={2}
                        className="w-full px-3 py-2 rounded-lg bg-[var(--glass-bg)] border border-[var(--glass-border)] text-sm text-foreground resize-y"
                        data-testid={`sop-step-${idx}-desc`} />
                      <div className="flex items-center gap-3">
                        {st.image_path ? (
                          <div className="relative group">
                            <img src={fileUrl(st.image_path, token)} alt="step" className="w-20 h-20 rounded-lg object-cover border border-[var(--glass-border)]"
                              onError={(e) => { e.target.src = IMAGE_FALLBACK; }} />
                            <button type="button" onClick={() => updateStep(idx, { image_path: '' })}
                              className="absolute -top-1.5 -right-1.5 p-1 rounded-full bg-[hsl(var(--destructive)/0.9)] text-white" title="Hapus foto langkah"><X className="w-3 h-3" /></button>
                          </div>
                        ) : (
                          <label className="w-20 h-20 rounded-lg border-2 border-dashed border-[var(--glass-border)] flex flex-col items-center justify-center gap-1 cursor-pointer hover:border-primary text-muted-foreground"
                            data-testid={`sop-step-${idx}-photo-label`}>
                            {stepUploading === idx ? <span className="text-xs">...</span> : (<><ImageIcon className="w-4 h-4" /><span className="text-xs">Foto</span></>)}
                            <input type="file" accept="image/*" className="hidden" onChange={(e) => uploadStepPhoto(idx, e.target.files?.[0])} />
                          </label>
                        )}
                        <button type="button" onClick={() => removeStep(idx)} className="ml-auto flex items-center gap-1 text-xs text-[hsl(var(--danger-text))] hover:text-[hsl(var(--danger-text))]" data-testid={`sop-step-${idx}-remove`}>
                          <Trash2 className="w-3.5 h-3.5" /> Hapus langkah
                        </button>
                      </div>
                    </div>
                  </div>
                </GlassCard>
              ))}
              {steps.length === 0 && (
                <EmptyState icon={ListChecks} className="py-8" title="Belum ada langkah"
                  description='Klik "Tambah Langkah" untuk menulis langkah pertama.' />
              )}
            </div>
            <Button type="button" variant="outline" size="sm" onClick={addStep} data-testid="sop-add-step-btn"><Plus className="w-4 h-4 mr-1" /> Tambah Langkah</Button>
          </div>
        )}

        {/* ── VIDEO & REFERENSI ── */}
        {tab === 'video' && (
          <div className="space-y-5" data-testid="panduan-video-tab">
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-semibold text-foreground flex items-center gap-1.5"><Video className="w-4 h-4 text-primary" /> Referensi Video</span>
                <Button type="button" variant="outline" size="sm" onClick={addVideo} data-testid="ref-add-video-btn"><Plus className="w-4 h-4 mr-1" /> Video</Button>
              </div>
              <div className="space-y-2">
                {videos.map((v, idx) => {
                  const yid = ytId(v.url);
                  return (
                    <GlassCard key={idx} className="flex items-center gap-3 p-2" data-testid={`ref-video-${idx}`}>
                      {yid ? <img src={`https://img.youtube.com/vi/${yid}/default.jpg`} alt="yt" className="w-16 h-12 rounded object-cover" />
                           : <div className="w-16 h-12 rounded bg-foreground/10 flex items-center justify-center"><Video className="w-5 h-5 text-muted-foreground" /></div>}
                      <div className="flex-1 space-y-1">
                        <GlassInput value={v.title} onChange={(e) => updateVideo(idx, { title: e.target.value })} placeholder="Judul video" data-testid={`ref-video-${idx}-title`} />
                        <GlassInput value={v.url} onChange={(e) => updateVideo(idx, { url: e.target.value })} placeholder="https://youtu.be/... atau link Drive" data-testid={`ref-video-${idx}-url`} />
                      </div>
                      <Button type="button" variant="ghost" size="icon-sm" onClick={() => removeVideo(idx)} title="Hapus video" aria-label="Hapus video" data-testid={`ref-video-${idx}-remove`}><Trash2 className="w-4 h-4" /></Button>
                    </GlassCard>
                  );
                })}
                {videos.length === 0 && (
                  <EmptyState icon={Video} className="py-6" title="Belum ada video referensi"
                    description="Klik tombol Video untuk menambah tautan YouTube atau Drive." />
                )}
              </div>
            </div>
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-semibold text-foreground flex items-center gap-1.5"><Link2 className="w-4 h-4 text-primary" /> Gambar Referensi (link)</span>
                <Button type="button" variant="outline" size="sm" onClick={addRefImage} data-testid="ref-add-image-btn"><Plus className="w-4 h-4 mr-1" /> Gambar</Button>
              </div>
              <div className="space-y-2">
                {refImages.map((v, idx) => (
                  <GlassCard key={idx} className="flex items-center gap-3 p-2" data-testid={`ref-image-${idx}`}>
                    <img src={v.url || IMAGE_FALLBACK} alt="ref" className="w-14 h-14 rounded object-cover bg-foreground/5" onError={(e) => { e.target.src = IMAGE_FALLBACK; e.target.style.objectFit = 'contain'; e.target.style.padding = '4px'; }} />
                    <div className="flex-1 space-y-1">
                      <GlassInput value={v.caption} onChange={(e) => updateRefImage(idx, { caption: e.target.value })} placeholder="Keterangan" data-testid={`ref-image-${idx}-caption`} />
                      <GlassInput value={v.url} onChange={(e) => updateRefImage(idx, { url: e.target.value })} placeholder="https://.../gambar.jpg" data-testid={`ref-image-${idx}-url`} />
                    </div>
                    <Button type="button" variant="ghost" size="icon-sm" onClick={() => removeRefImage(idx)} title="Hapus gambar" aria-label="Hapus gambar" data-testid={`ref-image-${idx}-remove`}><Trash2 className="w-4 h-4" /></Button>
                  </GlassCard>
                ))}
                {refImages.length === 0 && (
                  <EmptyState icon={ImageIcon} className="py-6" title="Belum ada gambar referensi"
                    description="Klik tombol Gambar untuk menambah tautan gambar." />
                )}
              </div>
            </div>
          </div>
        )}

      </div>
    </FormPopup>
  );
}

// Tahap 9 (7 Nov 2026): `renderPage(slots, body)` — halaman pemanggil (Portal Produksi › Master Produk) memegang
// cetakan PageLayout; modul ini hanya mengisi slotnya (penyaring, alat, tombol utama, ringkasan).
export default function RahazaModelsModule({ token, onNavigate, embedded = false, renderPage = null }) {
  const [rows, setRows] = useState([]);
  const [categories, setCategories] = useState([]);
  const [catFilter, setCatFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(DEFAULT_FORM);
  const [autoCode, setAutoCode] = useState(true);
  const [saving, setSaving] = useState(false);
  const [panduanModel, setPanduanModel] = useState(null);
  const [techpackModel, setTechpackModel] = useState(null);

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);

  const fetchRows = useCallback(async () => {
    setLoading(true);
    try {
      const [rm, rc] = await Promise.all([
        fetch('/api/rahaza/models', { headers }),
        fetch('/api/rahaza/product-categories', { headers }),
      ]);
      if (rm.ok) setRows(await rm.json());
      if (rc.ok) {
        const d = await rc.json();
        setCategories(d.categories || []);
      }
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => { fetchRows(); }, [fetchRows]);

  const visibleRows = useMemo(
    () => (catFilter ? rows.filter((r) => r.category_id === catFilter) : rows),
    [rows, catFilter],
  );

  const noCategoryCount = useMemo(
    () => rows.filter((r) => !r.category_id && r.active !== false).length,
    [rows],
  );

  const selectedCat = useMemo(
    () => categories.find((c) => c.id === form.category_id) || null,
    [categories, form.category_id],
  );

  const openCreate = () => {
    setEditing(null);
    setForm({ ...DEFAULT_FORM, category_id: categories[0]?.id || '' });
    setAutoCode(true);
    setModalOpen(true);
  };
  const openEdit = (row) => {
    setEditing(row);
    setForm({
      code: row.code || '', name: row.name || '', category_id: row.category_id || '',
      material_kg_per_pcs: readNumber(row, FIELD.materialKgPerPcs), bundle_size: row.bundle_size || 30,
      description: row.description || '',
      base_hpp: Number(row.base_hpp || 0), retail_price: Number(row.retail_price || 0),
      weight_gram: Number(row.weight_gram || 0),
    });
    setAutoCode(false);
    setModalOpen(true);
  };

  const handleSave = async () => {
    if (!form.name) { toast.error('Nama model wajib diisi'); return; }
    if (!form.category_id) { toast.error('Kategori wajib dipilih'); return; }
    if (!editing && !autoCode && !form.code) { toast.error('Kode wajib diisi (atau aktifkan kode otomatis)'); return; }
    setSaving(true);
    try {
      const url = editing ? `/api/rahaza/models/${editing.id}` : '/api/rahaza/models';
      const method = editing ? 'PUT' : 'POST';
      const payload = { ...form };
      if (!editing && autoCode) delete payload.code;   // K-1A: server yang membuat kode
      const r = await fetch(url, { method, headers, body: JSON.stringify(payload) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { toast.error(d.detail || `HTTP ${r.status}`); return; }
      if (editing) {
        const p = d.propagated || {};
        const extra = (p.fg || p.catalog_items)
          ? ` · ikut disegarkan: ${p.fg || 0} barang jadi, ${p.catalog_items || 0} item katalog`
          : '';
        toast.success(`Model diperbarui${extra}`);
      } else {
        toast.success(`Model dibuat · kode ${d.code || ''}`);
      }
      setModalOpen(false);
      fetchRows();
    } finally { setSaving(false); }
  };

  const handleDelete = async (row) => {
    if (!(await confirmDialog({
      title: `Nonaktifkan model ${row.code}?`,
      body: 'Item katalog marketing yang menawarkan produk ini akan ikut dinonaktifkan '
        + 'supaya barang yang sudah dihentikan tidak bisa dijual.',
      confirmLabel: 'Nonaktifkan', danger: true,
    }))) return;
    const r = await fetch(`/api/rahaza/models/${row.id}`, { method: 'DELETE', headers });
    const d = await r.json().catch(() => ({}));
    if (r.ok) {
      const n = d.affected_count || 0;
      toast.success(n ? `Model dinonaktifkan · ${n} item katalog ikut dinonaktifkan` : 'Model dinonaktifkan');
      fetchRows();
    } else toast.error(d.detail || 'Gagal menonaktifkan');
  };

  const columns = [
    { key: 'code', label: 'Kode', sortable: true, render: (row) => <span className="tabular-nums text-xs">{row.code}</span> },
    { key: 'name', label: 'Nama Model', sortable: true },
    {
      key: 'category_name', label: 'Kategori', sortable: true,
      render: (row) => {
        if (!row.category_id) {
          return (
            <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border bg-[hsl(var(--warning)/0.1)] border-[hsl(var(--warning)/0.4)] text-[hsl(var(--warning-text))] "
              title="Kategori belum dipilih — tidak ditebak oleh sistem" data-testid={`model-nocat-${row.code}`}>
              <AlertTriangle className="w-3 h-3" /> belum dipilih
            </span>
          );
        }
        return (
          <span className="inline-flex items-center gap-1.5" data-testid={`model-cat-${row.code}`}>
            <span className="tabular-nums text-xs px-1.5 py-0.5 rounded bg-primary/10 text-primary border border-primary/30">
              {row.category_code || '—'}
            </span>
            <span className="text-sm">{row.category_name || row.category}</span>
          </span>
        );
      },
    },
    { key: 'hpp', label: 'HPP', sortable: true, render: (row) => <HppCell row={row} /> },
    {
      key: 'retail_price', label: 'Harga Jual Resmi', sortable: true,
      render: (row) => (
        <span className={Number(row.retail_price || 0) ? 'text-foreground' : 'text-muted-foreground'}
          data-testid={`model-retail-${row.code}`}>
          {rupiah(row.retail_price)}
        </span>
      ),
    },
    {
      key: 'weight_gram', label: 'Berat', sortable: true,
      render: (row) => (
        <span className={Number(row.weight_gram || 0) ? 'text-foreground' : 'text-muted-foreground'}
          data-testid={`model-weight-${row.code}`}>
          {Number(row.weight_gram || 0) ? `${Number(row.weight_gram)} g` : '—'}
        </span>
      ),
    },
    {
      key: 'image_paths', label: 'Foto',
      render: (row) => {
        const arr = Array.isArray(row?.image_paths) ? row.image_paths : [];
        return (
          <div className="flex items-center gap-1.5" data-testid={`model-images-${row.code}`}>
            {arr.slice(0, 3).map((p) => <ImageThumb key={p} path={p} token={token} />)}
            {arr.length > 3 && <span className="text-xs text-muted-foreground">+{arr.length - 3}</span>}
          </div>
        );
      },
    },
    {
      key: 'sop_steps', label: 'Panduan',
      render: (row) => {
        const nSop = (row?.sop_steps || []).length;
        const nVid = (row?.reference_videos || []).length;
        return (
          <Button type="button" variant="outline" size="sm" onClick={(e) => { e.stopPropagation(); setPanduanModel(row); }}
            data-testid={`model-panduan-${row.code}`} title="Panduan produksi (SOP, foto, video)">
            <BookOpen className="w-3.5 h-3.5" />
            <span>{nSop} SOP · {nVid} video</span>
          </Button>
        );
      },
    },
    {
      key: 'techpack', label: 'Tech Pack',
      render: (row) => {
        const tp = row?.techpack;
        if (!tp) return <span className="text-xs text-muted-foreground">—</span>;
        return (
          <Button type="button" variant="outline" size="sm" onClick={(e) => { e.stopPropagation(); setTechpackModel(row); }}
            data-testid={`model-techpack-${row.code}`} title="Ringkasan spesifikasi dari R&D (hanya baca)">
            <FileText className="w-3.5 h-3.5" />
            <span>v{tp.version ?? '?'} · {(tp.bom_items || []).length} bahan</span>
          </Button>
        );
      },
    },
    { key: 'material_kg_per_pcs', label: 'Kain/pcs (kg) · catatan lama', render: (row) => { const v = readNumber(row, FIELD.materialKgPerPcs); return v ? Number(v).toFixed(3) : '-'; } },
    { key: 'bundle_size', label: 'Bundle', render: (row, v) => `${v || 30} pcs` },
    {
      key: 'actions', label: 'Aksi',
      render: (row) => (
        <div className="flex items-center gap-1">
          <Button type="button" variant="ghost" size="icon-sm" onClick={(e) => { e.stopPropagation(); openEdit(row); }}
            title="Ubah" aria-label="Ubah" data-testid={`model-edit-${row.code}`}>
            <Edit2 className="w-3.5 h-3.5" />
          </Button>
          <Button type="button" variant="ghost" size="icon-sm" onClick={(e) => { e.stopPropagation(); handleDelete(row); }}
            title="Nonaktifkan" aria-label="Nonaktifkan" data-testid={`model-deactivate-${row.code}`}>
            <Trash2 className="w-3.5 h-3.5" />
          </Button>
        </div>
      ),
    },
  ];

  const categoryFilter = (
    <SmartNativeSelect value={catFilter} onChange={(e) => setCatFilter(e.target.value)}
      className="w-56"
      data-testid="model-filter-category" aria-label="Kategori">
      <option value="">Semua kategori</option>
      {categories.map((c) => <option key={c.id} value={c.id}>{c.sku_prefix} · {c.name}</option>)}
    </SmartNativeSelect>
  );
  const importExport = <ImportExportToolbar collectionKey="models" label="Model Produk" onImported={fetchRows} />;
  const createBtn = (
    <Button type="button" onClick={openCreate} className="gap-1.5" data-testid="model-create-btn">
      <Plus className="w-4 h-4" /> Tambah model
    </Button>
  );
  const noCatNotice = noCategoryCount > 0 && (
    <Notice tone="warning" icon={AlertTriangle} testId="model-nocat-banner">
      <b>{noCategoryCount} produk belum punya kategori.</b> Sistem <b>tidak menebak</b> —
      pengelompokan & filter katalog marketing baru bisa dipercaya setelah kategorinya dipilih.
      Buka Ubah pada baris bertanda “belum dipilih”.
    </Notice>
  );
  const table = (
    <GlassCard>
      <DataTable tableId="rahaza-models" columns={columns} rows={visibleRows} loading={loading}
        emptyTitle="Belum ada model" emptyDescription="Model internal idealnya lahir dari R&D. Klik Tambah model untuk input manual." rowKey="id" />
    </GlassCard>
  );
  const dialogs = (
    <>
      {modalOpen && (
        // Standar UI/UX v2 (8 Nov 2026): FormPopup panjang — kaki Batal · Simpan (hijau), isian & simpan sama.
        <FormPopup open onClose={() => setModalOpen(false)} ukuran="panjang" testId="model-form-popup"
          judul={editing ? `Ubah model ${editing.code}` : 'Tambah model baru'} onSimpan={handleSave} menyimpan={saving}>
          <div className="space-y-4" data-testid="model-form">
            {!editing && (
              <Notice tone="warning" icon={Info} testId="model-rnd-hint" className="text-xs">
                <b>Disarankan lewat R&D:</b> produk internal idealnya lahir dari modul R&D (publish style → otomatis jadi master + bawa foto desain). Input manual ini untuk kasus khusus.
              </Notice>
            )}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Isian label="Nama model" wajib>
                <GlassInput value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Contoh: Vest Rajut Formal" data-testid="model-form-name" />
              </Isian>
              <Isian label="Kategori" wajib petunjuk="Untuk saringan & pengelompokan katalog; daftar dari tab Kategori.">
                <SmartNativeSelect value={form.category_id} onChange={(e) => setForm({ ...form, category_id: e.target.value })}
                  className="w-full" data-testid="model-form-category" aria-label="Kategori">
                  <option value="">Pilih kategori</option>
                  {categories.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.sku_prefix})</option>)}
                </SmartNativeSelect>
              </Isian>
            </div>

            {/* ── Kode produk: otomatis dari prefix kategori (K-1A) ── */}
            <div className="space-y-2 rounded-lg border border-[var(--glass-border)] p-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-foreground">Kode produk</span>
                {!editing && (
                  <label className="flex items-center gap-1.5 text-sm text-muted-foreground cursor-pointer select-none">
                    <Checkbox checked={autoCode} onCheckedChange={(v) => setAutoCode(!!v)} data-testid="model-form-autocode" />
                    Buat otomatis
                  </label>
                )}
              </div>
              {!editing && autoCode ? (
                <div className="flex items-center gap-2 text-sm text-foreground" data-testid="model-form-code-auto">
                  <Wand2 className="w-4 h-4 text-primary" />
                  <span className="tabular-nums">
                    {selectedCat ? `${selectedCat.sku_prefix}-0001` : '(pilih kategori dulu)'}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    — nomor urut berikutnya dibuat server; SKU varian menjadi{' '}
                    <span className="tabular-nums">{selectedCat ? `${selectedCat.sku_prefix}-0001-NVY-M` : '…'}</span>
                  </span>
                </div>
              ) : (
                <GlassInput value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })}
                  placeholder="Contoh: VST-0001" data-testid="model-form-code" />
              )}
            </div>

            {/* ── HPP · Harga Jual · Berat (F5 — menutup P1 & P4) ── */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <Isian label="HPP dasar (Rp)" petunjuk="Dipakai bila belum ada HPP dari R&D.">
                <MoneyInput glass value={form.base_hpp}
                  onChange={(e) => setForm({ ...form, base_hpp: e.target.value })} data-testid="model-form-base-hpp" />
              </Isian>
              <Isian label="Harga jual resmi (Rp)" petunjuk="Jadi nilai awal harga di katalog.">
                <MoneyInput glass value={form.retail_price}
                  onChange={(e) => setForm({ ...form, retail_price: e.target.value })} data-testid="model-form-retail-price" />
              </Isian>
              <Isian label="Berat satuan (gram)" petunjuk="Dipakai hitung biaya kirim.">
                <GlassInput type="number" min="0" value={form.weight_gram}
                  onChange={(e) => setForm({ ...form, weight_gram: e.target.value })} data-testid="model-form-weight-gram" />
              </Isian>
            </div>

            {editing && (
              <div className="rounded-lg border border-[var(--glass-border)] p-3 text-xs space-y-1"
                data-testid="model-form-hpp-info">
                <div className="flex items-center gap-2">
                  <span className="text-muted-foreground">HPP berlaku:</span>
                  <span className="font-medium text-foreground">{rupiah(editing.hpp)}</span>
                  <span className={`px-1.5 py-0.5 rounded-full border ${(HPP_SOURCE_LABEL[editing.hpp_source] || HPP_SOURCE_LABEL.none).cls}`}>
                    {(HPP_SOURCE_LABEL[editing.hpp_source] || HPP_SOURCE_LABEL.none).text}
                  </span>
                  {editing.hpp_updated_at && (
                    <span className="text-muted-foreground">
                      diperbarui {String(editing.hpp_updated_at).slice(0, 10)}
                    </span>
                  )}
                </div>
                <p className="text-muted-foreground">
                  Perubahan kategori / berat / harga di sini <b>otomatis turun</b> ke Barang Jadi (FG)
                  dan item katalog marketing yang tertaut.
                </p>
                {/* 2026-08-23 — HPP produk tidak lagi perlu diketik: layar "HPP per
                    Potong" menghitungnya dari BOM × harga pembelian + upah CMT/cutting. */}
                <Button type="button" variant="link" size="sm" className="h-auto p-0"
                  onClick={() => (typeof onNavigate === 'function'
                    ? onNavigate('fin-hpp-produk')
                    : (window.location.hash = 'fin-hpp-produk'))}
                  data-testid="model-goto-hpp-potong">
                  Hitung HPP dari BOM &amp; harga pembelian (HPP per potong) →
                </Button>
              </div>
            )}

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Isian label="Ukuran bundle (pcs)">
                <GlassInput type="number" value={form.bundle_size}
                  onChange={(e) => setForm({ ...form, bundle_size: parseInt(e.target.value) || 30 })} data-testid="model-form-bundle-size" />
              </Isian>
              <Isian label="Bahan utama per pcs (kg)">
                <GlassInput type="number" step="0.001" value={form.material_kg_per_pcs}
                  onChange={(e) => setForm({ ...form, material_kg_per_pcs: e.target.value })} data-testid="model-form-material-kg" />
              </Isian>
            </div>
            <Isian label="Deskripsi">
              <GlassInput value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="Opsional" data-testid="model-form-description" />
            </Isian>
            {editing && (
              <p className="text-xs text-muted-foreground">
                <b>Panduan produksi</b> (SOP, foto jadi, video) dikelola lewat tombol <BookOpen className="inline w-3 h-3" /> di kolom Panduan pada tabel.
              </p>
            )}
          </div>
        </FormPopup>
      )}

      {panduanModel && (
        <PanduanProduksiDialog model={panduanModel} token={token} onClose={() => setPanduanModel(null)} onUpdated={fetchRows} />
      )}

      {techpackModel && (
        <DetailPopup open onClose={() => setTechpackModel(null)} testId="model-techpack-popup"
          judul={`Tech pack (R&D) · ${techpackModel.code} — ${techpackModel.name}`}>
          <div className="space-y-3 text-sm" data-testid="model-techpack-dialog">
            <p className="text-xs text-muted-foreground">
              Ringkasan spesifikasi hasil promosi dari R&D — <b>hanya baca</b>. Sumber kebenarannya
              tetap Tech Pack di modul R&D.
            </p>
            {(() => {
              const tp = techpackModel.techpack || {};
              const rowsTp = [
                ['Versi', tp.version ?? '—'],
                ['Rentang size', tp.size_range || '—'],
                ['Base size', tp.base_size || '—'],
                ['Jenis jahitan', tp.stitch_type || '—'],
                ['Kelonggaran jahit', tp.seam_allowance_mm != null ? `${tp.seam_allowance_mm} mm` : '—'],
                ['Jumlah bahan (BOM)', (tp.bom_items || []).length],
                ['Jumlah ukuran diukur', (tp.measurements || []).length],
              ];
              return (
                <div className="rounded-lg border border-[var(--glass-border)] overflow-hidden">
                  {rowsTp.map(([k, v], i) => (
                    <div key={k} className={`flex items-center justify-between px-3 py-2 ${i % 2 ? 'bg-[var(--glass-bg)]' : ''}`}>
                      <span className="text-muted-foreground text-xs">{k}</span>
                      <span className="text-foreground">{String(v)}</span>
                    </div>
                  ))}
                  {tp.construction_notes && (
                    <div className="px-3 py-2 border-t border-[var(--glass-border)]">
                      <div className="text-muted-foreground text-xs mb-1">Catatan konstruksi</div>
                      <pre className="whitespace-pre-wrap text-xs text-foreground font-sans">{tp.construction_notes}</pre>
                    </div>
                  )}
                </div>
              );
            })()}
          </div>
        </DetailPopup>
      )}
    </>
  );

  if (renderPage) {
    return renderPage({ filters: categoryFilter, tools: importExport, actions: createBtn, summary: noCatNotice || null },
      <div data-testid="rahaza-models-module">{table}{dialogs}</div>);
  }
  const actions = <>{categoryFilter}{importExport}{createBtn}</>;
  return (
    <div className="space-y-4" data-testid="rahaza-models-module">
      {/* `embedded`: dipanggil dari Master Produk yang sudah punya kepala halaman sendiri — cukup baris aksi. */}
      {embedded
        ? <div className="flex items-center justify-end gap-2 flex-wrap" data-testid="models-toolbar">{actions}</div>
        : <PageHeader
            title="Model Produk (Internal)"
            subtitle="Master model produksi: kategori, HPP, harga jual resmi, berat, + Panduan Produksi (SOP, foto, video) yang dibaca Vendor CMT."
            actions={actions}
          />}
      {noCatNotice}
      {table}
      {dialogs}
    </div>
  );
}

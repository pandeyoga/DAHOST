/**
 * ProductionGuideDialog — editor Panduan Produksi (SOP) yang REUSABLE.
 * Dipakai oleh master data mana pun yang punya field:
 *   sop_steps[], reference_videos[], reference_images[], (opsional) image_paths[].
 *
 * Props:
 *   entity     : objek master data { id, sop_steps?, reference_videos?, reference_images?, image_paths? }
 *   token      : JWT
 *   title      : judul dialog
 *   endpoints  : { sop:'PUT url', sopImage:'POST url', photos?:'POST url', photosDelete?:'DELETE url' }
 *                photos/photosDelete opsional → jika tidak ada, tab "Foto Produk" disembunyikan.
 *   onClose, onUpdated
 *
 * Standar UI/UX v2 (8 Nov 2026): FormPopup panjang (dulu Modal + tombol buatan sendiri); pilihan bagian memakai
 * Button standar; ukuran huruf standar. Isian & panggilan server tidak berubah.
 */
import { useState, useMemo } from 'react';
import {
  Plus, Trash2, X, Upload, Camera, Video, Image as ImageIcon,
  ArrowUp, ArrowDown, Link2, ListChecks,
} from 'lucide-react';
import { GlassCard, GlassPanel } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import FormPopup from '@/components/ui/form-popup';
import { EmptyState } from './moduleAtoms';
import { toast } from 'sonner';

const MAX_PHOTOS = 8;
const IMAGE_FALLBACK = `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='48' height='48' viewBox='0 0 24 24' fill='none' stroke='%23cbd5e1' stroke-width='1.5'%3E%3Crect x='3' y='3' width='18' height='18' rx='2'/%3E%3Ccircle cx='8.5' cy='8.5' r='1.5'/%3E%3Cpath d='M21 15l-5-5L5 21'/%3E%3C/svg%3E`;
const fileUrl = (path, token) => `/api/files/${path}?auth=${encodeURIComponent(token)}`;

function ytId(url) {
  const m = String(url || '').match(/(?:youtu\.be\/|youtube\.com\/(?:watch\?v=|embed\/|shorts\/))([\w-]{11})/);
  return m ? m[1] : null;
}

export default function ProductionGuideDialog({ entity, token, title, endpoints, onClose, onUpdated }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);
  const hasPhotos = !!endpoints?.photos;
  const [tab, setTab] = useState(hasPhotos ? 'foto' : 'sop');
  const [paths, setPaths] = useState(entity.image_paths || []);
  const [steps, setSteps] = useState(() =>
    (entity.sop_steps || []).map((s) => ({
      id: s.id || crypto.randomUUID(), title: s.title || '', description: s.description || '', image_path: s.image_path || '',
    }))
  );
  const [videos, setVideos] = useState(() => (entity.reference_videos || []).map((v) => ({ url: v.url || '', title: v.title || '' })));
  const [refImages, setRefImages] = useState(() => (entity.reference_images || []).map((v) => ({ url: v.url || '', caption: v.caption || '' })));
  const [uploading, setUploading] = useState(false);
  const [stepUploading, setStepUploading] = useState(null);
  const [saving, setSaving] = useState(false);

  // ── Foto Produk (opsional) ──────────────────────────────────────────────────
  const handleUploadPhoto = async (e) => {
    const file = e.target.files?.[0];
    if (!file || !endpoints.photos) return;
    if (paths.length >= MAX_PHOTOS) { toast.error(`Maksimal ${MAX_PHOTOS} foto`); return; }
    setUploading(true);
    try {
      const fd = new FormData(); fd.append('file', file);
      const r = await fetch(endpoints.photos, { method: 'POST', headers, body: fd });
      if (!r.ok) { const err = await r.json().catch(() => ({})); toast.error(err.detail || 'Unggah gagal'); return; }
      const data = await r.json();
      setPaths(data.image_paths || []);
      toast.success('Foto diunggah');
      onUpdated && onUpdated();
    } finally { setUploading(false); e.target.value = ''; }
  };

  const handleDeletePhoto = async (path) => {
    if (!endpoints.photosDelete) return;
    if (!(await confirmDialog({ title: 'Hapus foto ini?', body: 'Foto tidak tampil lagi di Portal Vendor CMT.', confirmLabel: 'Hapus', danger: true }))) return;
    const r = await fetch(endpoints.photosDelete, {
      method: 'DELETE', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify({ storage_path: path }),
    });
    if (r.ok) { const data = await r.json(); setPaths(data.image_paths || []); toast.success('Foto dihapus'); onUpdated && onUpdated(); }
    else toast.error('Gagal menghapus foto');
  };

  // ── SOP langkah ────────────────────────────────────────────────────────────
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
      const r = await fetch(endpoints.sopImage, { method: 'POST', headers, body: fd });
      if (!r.ok) { const err = await r.json().catch(() => ({})); toast.error(err.detail || 'Unggah gagal'); return; }
      const data = await r.json();
      updateStep(idx, { image_path: data.storage_path });
      toast.success('Foto langkah diunggah');
    } finally { setStepUploading(null); }
  };

  // ── Video & Referensi ────────────────────────────────────────────────────────
  const addVideo = () => setVideos((v) => [...v, { url: '', title: '' }]);
  const removeVideo = (idx) => setVideos((v) => v.filter((_, i) => i !== idx));
  const updateVideo = (idx, patch) => setVideos((v) => v.map((it, i) => (i === idx ? { ...it, ...patch } : it)));
  const addRefImage = () => setRefImages((v) => [...v, { url: '', caption: '' }]);
  const removeRefImage = (idx) => setRefImages((v) => v.filter((_, i) => i !== idx));
  const updateRefImage = (idx, patch) => setRefImages((v) => v.map((it, i) => (i === idx ? { ...it, ...patch } : it)));

  const saveSop = async () => {
    setSaving(true);
    try {
      const r = await fetch(endpoints.sop, {
        method: 'PUT', headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ sop_steps: steps, reference_videos: videos, reference_images: refImages }),
      });
      if (!r.ok) { const err = await r.json().catch(() => ({})); toast.error(err.detail || 'Gagal menyimpan'); return; }
      toast.success('Panduan produksi tersimpan');
      onUpdated && onUpdated();
      onClose();
    } finally { setSaving(false); }
  };

  const TabBtn = ({ id, icon: Icon, label, count }) => (
    <Button type="button" size="sm" variant={tab === id ? 'secondary' : 'outline'} onClick={() => setTab(id)}
      aria-pressed={tab === id} data-testid={`panduan-tab-${id}`}>
      <Icon /> {label}
      {count != null && <span className="tabular-nums text-muted-foreground">({count})</span>}
    </Button>
  );

  return (
    <FormPopup open onClose={onClose} judul={title} ukuran="panjang" onSimpan={saveSop} menyimpan={saving}
      labelSimpan="Simpan panduan" testId="panduan-produksi-popup"
      keterangan="SOP produksi, foto, dan referensi yang dibaca vendor CMT.">
      <div className="space-y-4" data-testid="panduan-produksi-dialog">
        <div className="flex items-center gap-2 flex-wrap">
          {hasPhotos && <TabBtn id="foto" icon={Camera} label="Foto produk" count={paths.length} />}
          <TabBtn id="sop" icon={ListChecks} label="SOP produksi" count={steps.length} />
          <TabBtn id="video" icon={Video} label="Video & referensi" count={videos.length + refImages.length} />
        </div>

        {(entity.sop_updated_by || entity.sop_updated_at) && (
          <div className="text-xs text-muted-foreground" data-testid="sop-updated-meta">
            Terakhir diperbarui
            {entity.sop_updated_by ? ` oleh ${entity.sop_updated_by}` : ''}
            {entity.sop_updated_at ? ` · ${new Date(entity.sop_updated_at).toLocaleString('id-ID', { dateStyle: 'medium', timeStyle: 'short' })}` : ''}
          </div>
        )}

        {/* ── FOTO ── */}
        {hasPhotos && tab === 'foto' && (
          <div className="space-y-3" data-testid="panduan-foto-tab">
            <p className="text-sm text-muted-foreground">
              Unggah sampai <b>{MAX_PHOTOS} foto jadi / referensi</b> (maks. 5MB). Tampil di Portal Vendor CMT.
            </p>
            <div className="grid grid-cols-4 sm:grid-cols-6 gap-3">
              {paths.map((p) => (
                <GlassPanel key={p} className="relative group w-24 h-24 overflow-hidden">
                  <img src={fileUrl(p, token)} alt="foto" className="w-full h-full object-cover"
                    onError={(e) => { e.target.src = IMAGE_FALLBACK; e.target.style.objectFit = 'contain'; e.target.style.padding = '6px'; }} />
                  <Button type="button" variant="destructive" size="icon-sm" onClick={() => handleDeletePhoto(p)}
                    className="absolute right-0.5 top-0.5 h-6 w-6 rounded-full" title="Hapus foto" aria-label="Hapus foto">
                    <X />
                  </Button>
                </GlassPanel>
              ))}
              {paths.length < MAX_PHOTOS && (
                <label className="w-24 h-24 rounded-lg border-2 border-dashed border-[var(--glass-border)] flex flex-col items-center justify-center gap-1 cursor-pointer hover:border-primary hover:bg-[var(--glass-bg-hover)] transition-colors">
                  {uploading ? <span className="text-xs text-muted-foreground">Mengunggah...</span> : (<>
                    <Upload className="w-5 h-5 text-muted-foreground" />
                    <span className="text-xs text-muted-foreground">Tambah foto</span>
                  </>)}
                  <input type="file" accept="image/*" className="hidden" disabled={uploading} onChange={handleUploadPhoto} />
                </label>
              )}
            </div>
          </div>
        )}

        {/* ── SOP ── */}
        {tab === 'sop' && (
          <div className="space-y-3" data-testid="panduan-sop-tab">
            <p className="text-sm text-muted-foreground">
              Tata cara pembuatan produk — langkah berurutan. Vendor CMT membaca ini untuk tahu cara produksi.
            </p>
            <div className="space-y-3 max-h-[45vh] overflow-y-auto pr-1">
              {steps.map((st, idx) => (
                <GlassCard key={st.id} className="p-4" data-testid={`sop-step-${idx}`}>
                  <div className="flex items-start gap-3">
                    <div className="flex flex-col items-center gap-1 pt-1">
                      <span className="w-6 h-6 rounded-full bg-primary/15 text-primary text-xs font-bold flex items-center justify-center">{idx + 1}</span>
                      <Button type="button" variant="ghost" size="icon-sm" onClick={() => moveStep(idx, -1)} disabled={idx === 0} className="h-6 w-6" title="Naikkan langkah" aria-label="Naikkan langkah"><ArrowUp /></Button>
                      <Button type="button" variant="ghost" size="icon-sm" onClick={() => moveStep(idx, 1)} disabled={idx === steps.length - 1} className="h-6 w-6" title="Turunkan langkah" aria-label="Turunkan langkah"><ArrowDown /></Button>
                    </div>
                    <div className="flex-1 space-y-2">
                      <Input value={st.title} onChange={(e) => updateStep(idx, { title: e.target.value })}
                        placeholder="Judul langkah (cth: Potong kain sesuai pola)" data-testid={`sop-step-${idx}-title`} />
                      <Textarea value={st.description} onChange={(e) => updateStep(idx, { description: e.target.value })}
                        placeholder="Deskripsi / instruksi detail" rows={2} aria-label="Deskripsi langkah"
                        data-testid={`sop-step-${idx}-desc`} />
                      <div className="flex items-center gap-3">
                        {st.image_path ? (
                          <div className="relative group">
                            <img src={fileUrl(st.image_path, token)} alt="step" className="w-20 h-20 rounded-lg object-cover border border-[var(--glass-border)]"
                              onError={(e) => { e.target.src = IMAGE_FALLBACK; }} />
                            <Button type="button" variant="destructive" size="icon-sm" onClick={() => updateStep(idx, { image_path: '' })}
                              className="absolute -right-1.5 -top-1.5 h-6 w-6 rounded-full" title="Hapus foto langkah" aria-label="Hapus foto langkah"><X /></Button>
                          </div>
                        ) : (
                          <label className="w-20 h-20 rounded-lg border-2 border-dashed border-[var(--glass-border)] flex flex-col items-center justify-center gap-1 cursor-pointer hover:border-primary text-muted-foreground"
                            data-testid={`sop-step-${idx}-photo-label`}>
                            {stepUploading === idx ? <span className="text-xs">…</span> : (<><ImageIcon className="w-4 h-4" /><span className="text-xs">Foto</span></>)}
                            <input type="file" accept="image/*" className="hidden" onChange={(e) => uploadStepPhoto(idx, e.target.files?.[0])} />
                          </label>
                        )}
                        <Button type="button" variant="ghost" size="sm" onClick={() => removeStep(idx)} className="ml-auto text-[hsl(var(--danger-text))]" data-testid={`sop-step-${idx}-remove`}>
                          <Trash2 /> Hapus langkah
                        </Button>
                      </div>
                    </div>
                  </div>
                </GlassCard>
              ))}
              {steps.length === 0 && (
                <EmptyState icon={ListChecks} title="Belum ada langkah"
                  description='Klik "Tambah langkah" untuk menulis tata cara pembuatan produk.' />
              )}
            </div>
            <Button type="button" variant="outline" size="sm" onClick={addStep} data-testid="sop-add-step-btn"><Plus /> Tambah langkah</Button>
          </div>
        )}

        {/* ── VIDEO & REFERENSI ── */}
        {tab === 'video' && (
          <div className="space-y-4" data-testid="panduan-video-tab">
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-semibold text-foreground flex items-center gap-1.5"><Video className="w-4 h-4 text-primary" /> Referensi video</span>
                <Button type="button" variant="outline" size="sm" onClick={addVideo} data-testid="ref-add-video-btn"><Plus /> Video</Button>
              </div>
              <div className="space-y-2">
                {videos.map((v, idx) => {
                  const yid = ytId(v.url);
                  return (
                    <GlassPanel key={idx} className="flex items-center gap-3 p-2" data-testid={`ref-video-${idx}`}>
                      {yid ? <img src={`https://img.youtube.com/vi/${yid}/default.jpg`} alt="yt" className="w-16 h-12 rounded object-cover" />
                           : <div className="w-16 h-12 rounded bg-foreground/10 flex items-center justify-center"><Video className="w-5 h-5 text-muted-foreground" /></div>}
                      <div className="flex-1 space-y-1">
                        <Input value={v.title} onChange={(e) => updateVideo(idx, { title: e.target.value })} placeholder="Judul video" data-testid={`ref-video-${idx}-title`} />
                        <Input value={v.url} onChange={(e) => updateVideo(idx, { url: e.target.value })} placeholder="https://youtu.be/... atau link Drive" data-testid={`ref-video-${idx}-url`} />
                      </div>
                      <Button type="button" variant="ghost" size="icon-sm" onClick={() => removeVideo(idx)} title="Hapus video" aria-label="Hapus video" data-testid={`ref-video-${idx}-remove`}><Trash2 /></Button>
                    </GlassPanel>
                  );
                })}
                {videos.length === 0 && (
                  <EmptyState icon={Video} title="Belum ada video referensi"
                    description="Klik tombol Video untuk menambah tautan YouTube atau Drive." />
                )}
              </div>
            </div>
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-semibold text-foreground flex items-center gap-1.5"><Link2 className="w-4 h-4 text-primary" /> Gambar referensi (tautan)</span>
                <Button type="button" variant="outline" size="sm" onClick={addRefImage} data-testid="ref-add-image-btn"><Plus /> Gambar</Button>
              </div>
              <div className="space-y-2">
                {refImages.map((v, idx) => (
                  <GlassPanel key={idx} className="flex items-center gap-3 p-2" data-testid={`ref-image-${idx}`}>
                    <img src={v.url || IMAGE_FALLBACK} alt="ref" className="w-14 h-14 rounded object-cover bg-foreground/5" onError={(e) => { e.target.src = IMAGE_FALLBACK; e.target.style.objectFit = 'contain'; e.target.style.padding = '4px'; }} />
                    <div className="flex-1 space-y-1">
                      <Input value={v.caption} onChange={(e) => updateRefImage(idx, { caption: e.target.value })} placeholder="Keterangan" data-testid={`ref-image-${idx}-caption`} />
                      <Input value={v.url} onChange={(e) => updateRefImage(idx, { url: e.target.value })} placeholder="https://.../gambar.jpg" data-testid={`ref-image-${idx}-url`} />
                    </div>
                    <Button type="button" variant="ghost" size="icon-sm" onClick={() => removeRefImage(idx)} title="Hapus gambar" aria-label="Hapus gambar" data-testid={`ref-image-${idx}-remove`}><Trash2 /></Button>
                  </GlassPanel>
                ))}
                {refImages.length === 0 && (
                  <EmptyState icon={ImageIcon} title="Belum ada gambar referensi"
                    description="Klik tombol Gambar untuk menambah tautan gambar contoh." />
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </FormPopup>
  );
}

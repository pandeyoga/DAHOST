/**
 * Pola & marking (Portal RnD › Style & Desain › tab "Pola & Marking").
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, tabel + unduh Excel/CSV (kartu ringkas di HP), rincian = popup,
 * form = FormPopup panjang, hapus pola & hapus media lewat confirmDialog, status = StatusBadge, warna token.
 * Hanya tampilan yang berubah — API, isian, unggah media, dan setujui pola sama seperti sebelumnya.
 */
import { useState, useEffect, useRef } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { MoneyInput } from '@/components/ui/money-input';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Ruler, Plus, Trash2, Pencil, Search, CheckCircle2, MoreHorizontal, RefreshCw,
  Calculator, FileImage, Upload, X as XIcon, Image as ImageIcon, Video as VideoIcon,
} from 'lucide-react';
import { toast } from '../ui/sonner';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatRupiah } from '@/lib/format';
import { apiPost, apiPut, apiDelete } from '@/lib/api';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatusBadge } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL || '';

const STATUS_POLA = {
  approved: { label: 'Disetujui', tone: 'success' },
  draft:    { label: 'Draf', tone: 'warning' },
};
const statusPola = (s) => STATUS_POLA[s] || STATUS_POLA.draft;
const fmtAngka = (n, akhiran = '') => (n ? `${Number(n).toLocaleString('id-ID', { maximumFractionDigits: 2 })}${akhiran}` : '—');

const emptyForm = {
  pattern_code: '', style_id: '', style_code: '', style_name: '',
  size_range: 'S-XL',
  total_pieces: 0,
  fabric_width: 150,
  fabric_usage_per_pcs: 0,
  hpp_fabric_per_pcs: 0,
  efficiency_pct: 0,
  fabric_source: 'manual', fabric_size: '',
  marking_photo_url: '',
  marking_media: [],
  notes: '',
  status: 'draft',
};

/** Gambar/ikon satu media marking (dipakai di form & rincian). */
function MediaThumb({ m, token }) {
  if (m.kind === 'video') {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center text-muted-foreground">
        <VideoIcon className="mb-1 h-6 w-6" />
        <span className="w-full truncate px-1 text-center text-xs">{m.original_filename || 'video'}</span>
      </div>
    );
  }
  if (m.url) {
    return (
      <img
        src={`${m.url}${m.url.includes('?') ? '&' : '?'}auth=${encodeURIComponent(token)}`}
        alt={m.original_filename || 'marking'}
        className="h-full w-full object-cover"
        onError={(e) => { e.currentTarget.style.display = 'none'; }}
      />
    );
  }
  return (
    <div className="flex h-full w-full flex-col items-center justify-center text-muted-foreground">
      <ImageIcon className="mb-1 h-6 w-6" />
      <span className="w-full truncate px-1 text-center text-xs">{m.original_filename || 'foto'}</span>
    </div>
  );
}

export default function RnDPatternModule({ token }) {
  const h = { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` };
  const [patterns, setPatterns] = useState([]);
  const [styles,   setStyles]   = useState([]);
  const [loading,  setLoading]  = useState(false);
  const [search,   setSearch]   = useState('');
  const [filterStyle, setFilterStyle] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [editing,  setEditing]  = useState(null);
  const [form,     setForm]     = useState({ ...emptyForm });
  const [detail,   setDetail]   = useState(null);
  const [uploadingMedia, setUploadingMedia] = useState(false);
  const fileInputRef = useRef(null);

  const f = (name, val) => setForm(prev => ({ ...prev, [name]: val }));

  // #3a: estimasi kain dari fabric_consumption techpack (untuk isi Penggunaan Kain & HPP Bahan/pcs)
  const [fabricEst, setFabricEst] = useState(null);
  const [fabricEstLoading, setFabricEstLoading] = useState(false);
  const loadFabricEstimate = async () => {
    if (!form.style_id) { toast.error('Pilih style dulu untuk menarik data dari tech pack'); return; }
    setFabricEstLoading(true);
    try {
      const res = await fetch(`${API}/api/dewi/rnd/hpp/fabric-estimate?style_id=${form.style_id}`, { headers: h });
      const data = await res.json();
      if (!res.ok) { toast.error(data?.detail || 'Tech pack belum ada untuk style ini'); setFabricEst(null); return; }
      if (!data.sizes?.length) { toast.error('Tech pack belum punya data penggunaan bahan'); setFabricEst(null); return; }
      setFabricEst(data);
      if (data.has_unresolved_price) toast.warning('Sebagian harga kain belum diisi di Riset Material (HPP dianggap Rp0).');
    } catch { toast.error('Gagal memuat estimasi kain'); }
    finally { setFabricEstLoading(false); }
  };
  const applyFabricSize = (sz) => {
    setForm(prev => ({ ...prev,
      fabric_usage_per_pcs: sz.meters_per_pcs,
      hpp_fabric_per_pcs: sz.fabric_cost_per_pcs,
      fabric_source: 'techpack', fabric_size: sz.size,
    }));
    toast.success(`Kain ukuran ${sz.size} diterapkan (${sz.meters_per_pcs} m, HPP ${formatRupiah(sz.fabric_cost_per_pcs)})`);
  };

  const loadPatterns = async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      if (filterStyle) qs.set('style_id', filterStyle);
      if (search) qs.set('search', search);
      const res = await fetch(`${API}/api/dewi/rnd/patterns?${qs}`, { headers: h });
      setPatterns(await res.json());
    } catch { toast.error('Gagal memuat pola'); }
    finally { setLoading(false); }
  };

  const loadStyles = async () => {
    try {
      const res = await fetch(`${API}/api/dewi/rnd/styles`, { headers: h });
      const data = await res.json();
      setStyles(Array.isArray(data) ? data : (data.items || []));
    } catch { /* ignore */ }
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { loadPatterns(); }, [filterStyle]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { loadStyles(); }, []);

  const openNew = () => {
    const sel = styles.find(s => s.id === filterStyle);
    setForm({
      ...emptyForm,
      pattern_code: `POL-${Date.now().toString(36).toUpperCase()}`,
      style_id: sel?.id || '',
      style_code: sel?.style_code || '',
      style_name: sel?.style_name || '',
    });
    setEditing(null);
    setShowForm(true);
  };

  const openEdit = (p) => {
    setDetail(null);
    setForm({
      pattern_code: p.pattern_code || '',
      style_id: p.style_id || '',
      style_code: p.style_code || '',
      style_name: p.style_name || '',
      size_range: p.size_range || 'S-XL',
      total_pieces: p.total_pieces || 0,
      fabric_width: p.fabric_width || 150,
      fabric_usage_per_pcs: p.fabric_usage_per_pcs || 0,
      hpp_fabric_per_pcs: p.hpp_fabric_per_pcs || 0,
      efficiency_pct: p.efficiency_pct || 0,
      marking_photo_url: p.marking_photo_url || '',
      marking_media: p.marking_media || [],
      notes: p.notes || '',
      status: p.status || 'draft',
    });
    setEditing(p.id);
    setShowForm(true);
  };

  const setStyleField = (styleId) => {
    const sel = styles.find(s => s.id === styleId);
    setForm(prev => ({ ...prev, style_id: styleId, style_code: sel?.style_code || '', style_name: sel?.style_name || '' }));
    setFabricEst(null);
  };

  const handleSave = async () => {
    if (!form.pattern_code) return toast.error('Isi kode pola');
    if (!form.style_id) return toast.error('Pilih style terlebih dahulu');
    try {
      // 2026-11-06 (pola P6): helper lib/api melempar bila server menolak → pesan sukses hanya bila benar tersimpan
      if (editing) await apiPut(`/api/dewi/rnd/patterns/${editing}`, form);
      else await apiPost('/api/dewi/rnd/patterns', form);
      toast.success(editing ? 'Pola disimpan' : 'Pola ditambahkan');
      setShowForm(false);
      loadPatterns();
    } catch { toast.error('Gagal menyimpan pola'); }
  };

  const handleApprove = async (id) => {
    try {
      await apiPost(`/api/dewi/rnd/patterns/${id}/approve`, {});  // 2026-11-06 (pola P6): lihat handleSave
      toast.success('Pola disetujui');
      setDetail(null);
      loadPatterns();
    } catch { toast.error('Gagal menyetujui pola'); }
  };

  const handleDelete = async (p) => {
    const ok = await confirmDialog({
      title: 'Hapus pola ini?',
      body: `Pola ${p.pattern_code || ''} dihapus permanen.`,
      confirmLabel: 'Hapus', danger: true,
    });
    if (!ok) return;
    try {
      await apiDelete(`/api/dewi/rnd/patterns/${p.id}`);  // 2026-11-06 (pola P6): lihat handleSave
      toast.success('Pola dihapus');
      setDetail(null);
      loadPatterns();
    } catch { toast.error('Gagal menghapus'); }
  };

  // ── Session 27: Marking Media Upload ──────────────────────────────────────
  const handleUploadMedia = async (files) => {
    if (!editing) {
      toast.error('Simpan pola terlebih dahulu sebelum mengunggah media');
      return;
    }
    if (!files || files.length === 0) return;

    setUploadingMedia(true);
    let successCount = 0;
    const newMedia = [];
    try {
      for (const file of Array.from(files)) {
        // Validate file type and size
        const isImage = file.type.startsWith('image/');
        const isVideo = file.type.startsWith('video/');
        if (!isImage && !isVideo) {
          toast.error(`${file.name}: hanya foto/video yang diizinkan`);
          continue;
        }
        if (file.size > 10 * 1024 * 1024) {
          toast.error(`${file.name}: ukuran melebihi 10MB`);
          continue;
        }

        // Step 1: Upload file via /api/upload
        const fd = new FormData();
        fd.append('file', file);
        const uploadUrl = `${API}/api/upload?entity_type=rnd_pattern_media&entity_id=${editing}`;
        const upRes = await fetch(uploadUrl, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
          body: fd,
        });
        if (!upRes.ok) {
          toast.error(`${file.name}: unggah gagal`);
          continue;
        }
        const upData = await upRes.json();

        // Step 2: Attach metadata to pattern
        const attachRes = await fetch(`${API}/api/dewi/rnd/patterns/${editing}/attach-media`, {
          method: 'POST', headers: h,
          body: JSON.stringify({
            attachment_id: upData.id,
            storage_path: upData.storage_path,
            url: upData.storage_path ? `${API}/api/files/${upData.storage_path}` : '',
            content_type: upData.content_type,
            original_filename: upData.original_filename,
            size: upData.size,
          }),
        });
        if (!attachRes.ok) {
          toast.error(`${file.name}: gagal melampirkan ke pola`);
          continue;
        }
        const attachData = await attachRes.json();
        newMedia.push(attachData.media);
        successCount++;
      }
      if (successCount > 0) {
        toast.success(`${successCount} file berhasil diunggah`);
        setForm(prev => ({ ...prev, marking_media: [...(prev.marking_media || []), ...newMedia] }));
        loadPatterns();
      }
    } finally {
      setUploadingMedia(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleRemoveMedia = async (attachmentId) => {
    if (!editing) return;
    const ok = await confirmDialog({ title: 'Hapus media ini?', body: 'Foto/video marking dilepas dari pola ini.', confirmLabel: 'Hapus', danger: true });
    if (!ok) return;
    try {
      const res = await fetch(`${API}/api/dewi/rnd/patterns/${editing}/media/${attachmentId}`, {
        method: 'DELETE', headers: h,
      });
      if (!res.ok) throw new Error();
      setForm(prev => ({
        ...prev,
        marking_media: (prev.marking_media || []).filter(m => m.attachment_id !== attachmentId),
      }));
      toast.success('Media dihapus');
      loadPatterns();
    } catch { toast.error('Gagal menghapus media'); }
  };

  const filtered = patterns.filter(p => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (p.pattern_code || '').toLowerCase().includes(q)
      || (p.style_code || '').toLowerCase().includes(q)
      || (p.style_name || '').toLowerCase().includes(q);
  });

  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(filtered, 10);

  const kolom = [
    { kunci: 'kode', label: 'Kode pola', hp: 'judul', isi: (p) => <span className="font-medium text-foreground">{p.pattern_code}</span> },
    { kunci: 'style', label: 'Style', hp: 'keterangan', isi: (p) => (
      <div className="min-w-0">
        <p className="text-foreground">{p.style_code || '—'}</p>
        {p.style_name && <p className="text-xs text-muted-foreground">{p.style_name}</p>}
      </div>) },
    { kunci: 'ukuran', label: 'Ukuran', isi: (p) => p.size_range || '—' },
    { kunci: 'kain', label: 'Kain/pcs', rata: 'kanan', isi: (p) => <span className="tabular-nums">{fmtAngka(p.fabric_usage_per_pcs, ' m')}</span> },
    { kunci: 'hpp', label: 'HPP bahan/pcs', rata: 'kanan', isi: (p) => <span className="tabular-nums">{p.hpp_fabric_per_pcs ? formatRupiah(p.hpp_fabric_per_pcs) : '—'}</span> },
    { kunci: 'efisiensi', label: 'Efisiensi', rata: 'kanan', isi: (p) => <span className="tabular-nums">{fmtAngka(p.efficiency_pct, '%')}</span> },
    { kunci: 'media', label: 'Media', rata: 'kanan', isi: (p) => ((p.marking_media || []).length > 0 ? (
      <span className="inline-flex items-center gap-1 text-sm tabular-nums" data-testid={`rnd-pattern-media-count-${p.id}`}>
        <FileImage className="h-3.5 w-3.5 text-muted-foreground" />{p.marking_media.length}
      </span>) : <span className="text-muted-foreground">—</span>) },
    { kunci: 'status', label: 'Status', isi: (p) => <StatusBadge status={p.status} label={statusPola(p.status).label} tone={statusPola(p.status).tone} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (p) => (
      <div className="flex justify-end gap-1">
        <Button variant="ghost" size="icon-sm" onClick={() => openEdit(p)} title="Ubah" aria-label="Ubah"
          data-testid={`rnd-pattern-edit-${p.id}`}><Pencil /></Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" title="Lainnya" aria-label="Lainnya" data-testid={`rnd-pattern-more-${p.id}`}>
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {p.status !== 'approved' && (
              <DropdownMenuItem onSelect={() => handleApprove(p.id)} data-testid={`rnd-pattern-approve-${p.id}`}>
                <CheckCircle2 className="mr-2 h-4 w-4" />Setujui
              </DropdownMenuItem>
            )}
            <DropdownMenuItem onSelect={() => handleDelete(p)} className="text-[hsl(var(--danger-text))]"
              data-testid={`rnd-pattern-delete-${p.id}`}>
              <Trash2 className="mr-2 h-4 w-4" />Hapus
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>) },
  ];

  return (
    <PageLayout testId="rnd-pattern-module" title="Pola & marking"
      subtitle="Dokumentasi pola, marking, dan perhitungan HPP bahan per pcs."
      actions={<Button onClick={openNew} data-testid="rnd-pattern-add-btn"><Plus />Tambah pola</Button>}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={e => { setSearch(e.target.value); }}
            placeholder="Cari kode pola atau style" className="pl-8" data-testid="rnd-pattern-search"
            onKeyDown={e => e.key === 'Enter' && loadPatterns()} />
        </div>
        <SmartNativeSelect value={filterStyle} onChange={e => setFilterStyle(e.target.value)}
          className="w-full sm:w-56" data-testid="rnd-pattern-style-filter">
          <option value="">Semua style</option>
          {styles.map(s => <option key={s.id} value={s.id}>{s.style_code} — {s.style_name}</option>)}
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="pola-marking" namaLembar="Pola" baris={filtered} testId="rnd-pattern-unduh"
          kolom={[
            { label: 'Kode pola', nilai: (p) => p.pattern_code || '' },
            { label: 'Kode style', nilai: (p) => p.style_code || '' },
            { label: 'Nama style', nilai: (p) => p.style_name || '' },
            { label: 'Rentang ukuran', nilai: (p) => p.size_range || '' },
            { label: 'Jumlah potongan', nilai: (p) => Number(p.total_pieces || 0) },
            { label: 'Lebar kain (cm)', nilai: (p) => Number(p.fabric_width || 0) },
            { label: 'Kain per pcs (m)', nilai: (p) => Number(p.fabric_usage_per_pcs || 0) },
            { label: 'HPP bahan per pcs (Rp)', nilai: (p) => Number(p.hpp_fabric_per_pcs || 0) },
            { label: 'Efisiensi (%)', nilai: (p) => Number(p.efficiency_pct || 0) },
            { label: 'Jumlah media', nilai: (p) => (p.marking_media || []).length },
            { label: 'Status', nilai: (p) => statusPola(p.status).label },
            { label: 'Catatan', nilai: (p) => p.notes || '' },
          ]} />
        <Button variant="outline" size="icon" onClick={loadPatterns} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      footer={total > pageSize && (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />
      )}>
      {loading && patterns.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat pola…</p>
      ) : (
        <TabelData kolom={kolom} baris={paged} onKlikBaris={setDetail} testId="rnd-pattern-table"
          kosong={<EmptyState icon={Ruler}
            title={patterns.length ? 'Tidak ada pola yang cocok' : 'Belum ada dokumentasi pola'}
            description={patterns.length ? 'Ubah kata pencarian atau pilihan style.' : 'Catat pola, marking, dan pemakaian kain per pcs untuk style.'}
            action={!patterns.length && <Button onClick={openNew}><Plus />Tambah pola</Button>} />} />
      )}

      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} testId="rnd-pattern-detail"
          judul={`Pola ${detail.pattern_code}`}
          keterangan={[detail.style_code, detail.style_name].filter(Boolean).join(' · ') || undefined}
          status={<StatusBadge status={detail.status} label={statusPola(detail.status).label} tone={statusPola(detail.status).tone} />}
          aksi={<>
            {detail.status !== 'approved' && (
              <Button size="sm" variant="success" onClick={() => handleApprove(detail.id)}><CheckCircle2 />Setujui</Button>
            )}
            <Button size="sm" variant="outline" onClick={() => openEdit(detail)}><Pencil />Ubah</Button>
            <Button size="sm" variant="destructive" onClick={() => handleDelete(detail)}><Trash2 />Hapus</Button>
          </>}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Rentang ukuran">{detail.size_range || '—'}</BarisDetail>
            <BarisDetail label="Jumlah potongan">{detail.total_pieces || '—'}</BarisDetail>
            <BarisDetail label="Lebar kain">{fmtAngka(detail.fabric_width, ' cm')}</BarisDetail>
            <BarisDetail label="Kain per pcs">
              {fmtAngka(detail.fabric_usage_per_pcs, ' m')}
              {detail.fabric_source === 'techpack' && <span className="text-muted-foreground"> (dari tech pack{detail.fabric_size ? `, ukuran ${detail.fabric_size}` : ''})</span>}
            </BarisDetail>
            <BarisDetail label="HPP bahan per pcs">{detail.hpp_fabric_per_pcs ? formatRupiah(detail.hpp_fabric_per_pcs) : '—'}</BarisDetail>
            <BarisDetail label="Efisiensi">{fmtAngka(detail.efficiency_pct, '%')}</BarisDetail>
            {detail.marking_photo_url && (
              <BarisDetail label="Tautan foto marking">
                <a href={detail.marking_photo_url} target="_blank" rel="noreferrer" className="break-all text-primary underline-offset-4 hover:underline">
                  {detail.marking_photo_url}
                </a>
              </BarisDetail>
            )}
            {detail.notes && <BarisDetail label="Catatan">{detail.notes}</BarisDetail>}
          </dl>
          {(detail.marking_media || []).length > 0 && (
            <div className="space-y-2">
              <p className="text-sm font-semibold text-foreground">Dokumentasi marking ({detail.marking_media.length})</p>
              <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
                {detail.marking_media.map((m, idx) => (
                  <div key={m.attachment_id || idx}
                    className="aspect-square overflow-hidden rounded-[var(--radius-md)] border border-[var(--glass-border)]">
                    <MediaThumb m={m} token={token} />
                  </div>
                ))}
              </div>
            </div>
          )}
        </DetailPopup>
      )}

      {/* Form pola (popup standar, panjang) */}
      <FormPopup open={showForm} onClose={() => setShowForm(false)} ukuran="panjang" onSimpan={handleSave}
        judul={editing ? 'Ubah pola' : 'Tambah pola'}
        keterangan="Data kain bisa ditarik dari penggunaan bahan di tech pack style."
        testId="rnd-pattern-form">
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Kode pola" wajib htmlFor="pola-kode">
            <Input id="pola-kode" value={form.pattern_code}
              onChange={e => f('pattern_code', e.target.value)} placeholder="POL-xxx" data-testid="rnd-pattern-code-input" />
          </Isian>
          <Isian label="Style" wajib>
            <SmartNativeSelect value={form.style_id} onChange={e => setStyleField(e.target.value)}
              className="w-full" data-testid="rnd-pattern-style-select">
              <option value="">Pilih style</option>
              {styles.map(s => <option key={s.id} value={s.id}>{s.style_code} — {s.style_name}</option>)}
            </SmartNativeSelect>
          </Isian>
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          <Isian label="Rentang ukuran" htmlFor="pola-ukuran">
            <Input id="pola-ukuran" value={form.size_range} onChange={e => f('size_range', e.target.value)} placeholder="S-XL" />
          </Isian>
          <Isian label="Jumlah potongan" htmlFor="pola-potong">
            <Input id="pola-potong" type="number" value={form.total_pieces} onChange={e => f('total_pieces', Number(e.target.value))} />
          </Isian>
          <Isian label="Lebar kain (cm)" htmlFor="pola-lebar">
            <Input id="pola-lebar" type="number" value={form.fabric_width} onChange={e => f('fabric_width', Number(e.target.value))} />
          </Isian>
        </div>

        <section className="space-y-3 border-t border-[var(--glass-border)] pt-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold text-foreground">Data kain & marking</p>
            <Button type="button" variant="outline" size="sm" onClick={loadFabricEstimate}
              disabled={fabricEstLoading} data-testid="pattern-fabric-from-techpack">
              <Calculator />{fabricEstLoading ? 'Memuat…' : 'Tarik dari tech pack'}
            </Button>
          </div>
          {fabricEst && fabricEst.sizes?.length > 0 && (
            <div className="space-y-2" data-testid="pattern-fabric-estimate-panel">
              <p className="text-xs text-muted-foreground">
                Tech pack <b>{fabricEst.style_code}</b> — klik ukuran untuk mengisi kain per pcs & HPP bahan per pcs.
                {fabricEst.has_unresolved_price && <span className="ml-1 text-[hsl(var(--warning-text))]">Sebagian harga Rp0.</span>}
              </p>
              <div className="flex flex-wrap gap-2">
                {fabricEst.sizes.map(sz => {
                  const dipilih = form.fabric_size === sz.size && form.fabric_source === 'techpack';
                  return (
                    <Button key={sz.size} type="button" size="sm" variant={dipilih ? 'default' : 'outline'}
                      onClick={() => applyFabricSize(sz)}>
                      <b>{sz.size}</b>: {sz.meters_per_pcs} m · {formatRupiah(sz.fabric_cost_per_pcs)}/pcs
                    </Button>
                  );
                })}
              </div>
            </div>
          )}
          <div className="grid gap-4 sm:grid-cols-3">
            <Isian label="Kain per pcs (m)" htmlFor="pola-kain">
              <Input id="pola-kain" type="number" step="0.01" value={form.fabric_usage_per_pcs}
                onChange={e => { f('fabric_usage_per_pcs', Number(e.target.value)); f('fabric_source', 'manual'); }} />
            </Isian>
            <Isian label="HPP bahan per pcs (Rp)">
              <MoneyInput value={form.hpp_fabric_per_pcs}
                onChange={e => f('hpp_fabric_per_pcs', Number(e.target.value))} />
            </Isian>
            <Isian label="Efisiensi (%)" htmlFor="pola-efisiensi">
              <Input id="pola-efisiensi" type="number" step="0.1" max="100" value={form.efficiency_pct}
                onChange={e => f('efficiency_pct', Number(e.target.value))} />
            </Isian>
          </div>
          <Isian label="Tautan foto marking" htmlFor="pola-url" petunjuk="Opsional, tautan manual.">
            <Input id="pola-url" value={form.marking_photo_url}
              onChange={e => f('marking_photo_url', e.target.value)} placeholder="https://..." />
          </Isian>
        </section>

        {/* ── Session 27 GAP-R4: Marking Media Upload ─────────────── */}
        <section className="space-y-2 border-t border-[var(--glass-border)] pt-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="flex items-center gap-2 text-sm font-semibold text-foreground">
              Dokumentasi marking (foto/video)
              {form.marking_media && form.marking_media.length > 0 && (
                <span className="text-xs font-normal text-muted-foreground">({form.marking_media.length})</span>
              )}
            </p>
            {editing && (
              <>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*,video/*"
                  multiple
                  className="hidden"
                  onChange={e => handleUploadMedia(e.target.files)}
                  data-testid="rnd-pattern-media-input"
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={uploadingMedia}
                  onClick={() => fileInputRef.current?.click()}
                  data-testid="rnd-pattern-media-upload-btn"
                >
                  {uploadingMedia ? <RefreshCw className="animate-spin" /> : <Upload />}
                  {uploadingMedia ? 'Mengunggah…' : 'Unggah foto/video'}
                </Button>
              </>
            )}
          </div>
          {!editing ? (
            <p className="text-xs text-muted-foreground">
              Simpan pola terlebih dahulu untuk dapat mengunggah dokumentasi marking.
            </p>
          ) : (form.marking_media && form.marking_media.length > 0) ? (
            <div className="grid grid-cols-3 gap-2 sm:grid-cols-4" data-testid="rnd-pattern-media-grid">
              {form.marking_media.map((m, idx) => (
                <div key={m.attachment_id || idx}
                  className="relative aspect-square overflow-hidden rounded-[var(--radius-md)] border border-[var(--glass-border)]">
                  <MediaThumb m={m} token={token} />
                  <Button type="button" size="icon-sm" variant="destructive"
                    onClick={() => handleRemoveMedia(m.attachment_id)}
                    className="absolute right-1 top-1 h-6 w-6"
                    title="Hapus media" aria-label="Hapus media"
                    data-testid={`rnd-pattern-media-remove-${idx}`}>
                    <XIcon className="h-3 w-3" />
                  </Button>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">Belum ada dokumentasi marking. Klik "Unggah foto/video".</p>
          )}
        </section>

        <Isian label="Catatan" htmlFor="pola-catatan">
          <Textarea id="pola-catatan" rows={3} value={form.notes} onChange={e => f('notes', e.target.value)}
            placeholder="Catatan tambahan pola…" />
        </Isian>
      </FormPopup>
    </PageLayout>
  );
}

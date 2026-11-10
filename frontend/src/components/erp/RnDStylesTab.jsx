/**
 * Daftar style RnD (tab "Daftar style" di menu Style & Desain).
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout (penyaring satu baris, unduh Excel/CSV), tabel dengan
 * kartu ringkas di HP, klik baris = popup detail, aksi baris paling banyak 2 (aksi alur + "Lainnya"),
 * semua form = FormPopup (Tambah/Ubah style, Ajukan ke owner, Tinjau desain), konfirmasi = confirmDialog.
 * Fitur, isian, dan panggilan API tidak berubah.
 */
import { useState, useEffect } from 'react';
import {
  Plus, Search, Pencil, Trash2, X, Eye, Send, Clock, CheckCircle2, XCircle, AlertCircle, MessageSquare,
  ImagePlus, Loader2, Rocket, RefreshCw, MoreHorizontal,
} from 'lucide-react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { BarisDetail } from '@/components/ui/detail-popup';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { toast } from '../ui/sonner';
import { apiFetch, ApiError } from '@/lib/apiFetch';
import { hapusMaster } from '@/lib/hapusMaster';
import { formatDateID } from '@/lib/format';
import { cn } from '@/lib/utils';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice } from './moduleAtoms';
import RnDStyleDetailPage, { STATUS_STYLE, StyleStatusBadge } from './RnDStyleDetailPage';

const API = process.env.REACT_APP_BACKEND_URL || '';
const PER_HALAMAN = 25;

// Status keputusan — hanya boleh berpindah lewat tombol Ajukan/Setujui/Tolak
// (backend juga menolak perubahannya lewat PUT /styles/{id}).
const LIFECYCLE_STATUSES = ['pending_owner_review', 'approved_for_launch'];

/** Riwayat keputusan owner: siapa memutuskan + alasan lengkap (satu baris kecil di bawah nama style). */
function ReviewHistoryLine({ style }) {
  if (!style.owner_review_result) return null;
  const approved = style.owner_review_result === 'approved';
  const Icon = approved ? CheckCircle2 : XCircle;
  return (
    <p className={cn('mt-0.5 flex items-start gap-1 text-xs',
      approved ? 'text-[hsl(var(--info-text))]' : 'text-[hsl(var(--danger-text))]')}>
      <Icon className="mt-0.5 h-3 w-3 shrink-0" />
      <span>
        {approved ? 'Disetujui' : 'Ditolak'} oleh {style.owner_reviewed_by}
        {style.owner_review_notes ? <span className="text-muted-foreground"> — {style.owner_review_notes}</span> : null}
      </span>
    </p>
  );
}

export default function RnDStylesTab({ token, user }) {
  const [styles, setStyles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null);
  const [saving, setSaving] = useState(false);
  const [formErr, setFormErr] = useState('');
  const [detailStyleId, setDetailStyleId] = useState(null);
  const [submitReviewDialog, setSubmitReviewDialog] = useState(null);
  const [ownerReviewDialog, setOwnerReviewDialog] = useState(null);
  const [pendingCount, setPendingCount] = useState(0);
  const [showPendingInbox, setShowPendingInbox] = useState(false);

  const [form, setForm] = useState({
    style_code: '', style_name: '', category: '',
    client_id: '', buyer: '', fabric_type: '', season: '', description: '', status: 'draft',
  });

  // Foto desain (unggah di form Tambah/Ubah style → galeri persetujuan manajemen)
  const [photos, setPhotos] = useState([]);            // foto yang sudah tersimpan
  const [pendingPhotos, setPendingPhotos] = useState([]); // dipilih saat mode Tambah
  const [uploadingPhoto, setUploadingPhoto] = useState(false);

  // Detect if current user is owner/superadmin
  const isOwner = user && (user.role === 'superadmin' || user.role === 'owner' || user.role === 'admin');

  useEffect(() => {
    fetchStyles();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, filterStatus]);

  useEffect(() => {
    if (isOwner) fetchPendingCount();
  }, [isOwner]);

  // 2026-11-07 (Tahap 5): kategori style DARI MASTER Kategori Produk. Dulu diketik bebas ("T-Shirt") —
  // saat style dipromosikan jadi Model DA, teks yang tidak sama persis dengan nama master membuat model
  // lahir TANPA kategori (kode model & prefix SKU tidak bisa dibuat dari kategori).
  const [categories, setCategories] = useState([]);
  useEffect(() => {
    if (!showForm || categories.length) return;
    apiFetch('/rahaza/product-categories')
      .then(d => setCategories((Array.isArray(d) ? d : (d?.categories || [])).filter(c => c.active !== false)))
      .catch(() => setCategories([]));
  }, [showForm]); // eslint-disable-line react-hooks/exhaustive-deps

  // 2026-11-07 (Tahap 6, PR3): Buyer dari master Klien maklon (kosong = produk internal DA) dan Jenis kain dari
  // master kain (nama kain di Master Material). Dulu teks bebas. Nilai lama tetap tampil (ditandai "lama").
  const [formOpts, setFormOpts] = useState({ buyers: [], fabric_types: [] });
  useEffect(() => {
    if (!showForm) return;
    apiFetch('/dewi/rnd/style-form-options')
      .then(d => setFormOpts({ buyers: d?.buyers || [], fabric_types: d?.fabric_types || [] }))
      .catch(() => setFormOpts({ buyers: [], fabric_types: [] }));
  }, [showForm]);
  const LEGACY = '__lama__';
  const buyerValue = form.client_id || (form.buyer ? LEGACY : '');
  const pickBuyer = (v) => {
    if (v === LEGACY) return;
    const b = formOpts.buyers.find(x => x.id === v);
    setForm(p => ({ ...p, client_id: v, buyer: b?.name || '' }));
  };
  const fabricLegacy = !!form.fabric_type
    && !formOpts.fabric_types.some(n => n.toLowerCase() === form.fabric_type.toLowerCase());

  const fetchStyles = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (search) params.set('search', search);
      if (filterStatus) params.set('status', filterStatus);
      const qs = params.toString();
      const data = await apiFetch(`/dewi/rnd/styles${qs ? '?' + qs : ''}`);
      setStyles(Array.isArray(data) ? data : []);
    } catch (e) {
      if (e instanceof ApiError && !e.isUnauthorized) toast.error(e.userMessage || 'Gagal memuat data style');
    } finally {
      setLoading(false);
    }
  };

  const fetchPendingCount = async () => {
    try {
      const data = await apiFetch('/dewi/rnd/styles/pending-review');
      setPendingCount(Array.isArray(data) ? data.length : 0);
    } catch {}
  };

  const openCreate = () => {
    setEditing(null);
    setFormErr('');
    setForm({ style_code: '', style_name: '', category: '', client_id: '', buyer: '', fabric_type: '', season: '', description: '', status: 'draft' });
    setPhotos([]);
    setPendingPhotos([]);
    setShowForm(true);
  };

  const openEdit = (style) => {
    setEditing(style);
    setFormErr('');
    setPhotos(Array.isArray(style.design_images) ? style.design_images.filter((p) => p && p.url) : []);
    setPendingPhotos([]);
    setForm({
      style_code: style.style_code || '', style_name: style.style_name || '',
      category: style.category || '', client_id: style.client_id || '', buyer: style.buyer || '',
      fabric_type: style.fabric_type || '', season: style.season || '',
      description: style.description || '', status: style.status || 'draft',
    });
    setShowForm(true);
  };

  const handleSave = async () => {
    if (!form.style_code.trim() || !form.style_name.trim()) {
      setFormErr('Kode style dan nama style wajib diisi.');
      return;
    }
    setFormErr('');
    setSaving(true);
    try {
      if (editing) {
        await apiFetch(`/dewi/rnd/styles/${editing.id}`, { method: 'PUT', body: form });
        toast.success('Style disimpan');
      } else {
        const created = await apiFetch('/dewi/rnd/styles', { method: 'POST', body: form });
        if (pendingPhotos.length && created?.id) {
          for (const file of pendingPhotos) await uploadPhoto(created.id, file);
        }
        toast.success(pendingPhotos.length
          ? `Style dibuat + ${pendingPhotos.length} foto desain diunggah`
          : 'Style berhasil dibuat');
      }
      setShowForm(false);
      setPendingPhotos([]);
      fetchStyles();
    } catch (e) {
      if (e instanceof ApiError && !e.isUnauthorized) {
        toast.error(e.userMessage || 'Gagal menyimpan style');
        setFormErr(e.userMessage || 'Gagal menyimpan style.');
      }
    } finally {
      setSaving(false);
    }
  };

  const uploadPhoto = (styleId, file) => {
    const fd = new FormData();
    fd.append('file', file);
    return apiFetch(`/dewi/rnd/styles/${styleId}/images`, { method: 'POST', formData: fd });
  };

  const handlePhotoInput = async (e) => {
    const files = Array.from(e.target.files || []);
    e.target.value = '';
    if (!files.length) return;
    const tooBig = files.find((f) => f.size > 10 * 1024 * 1024);
    if (tooBig) { toast.error(`${tooBig.name} lebih dari 10MB`); return; }
    if (!editing) { setPendingPhotos((p) => [...p, ...files]); return; }
    setUploadingPhoto(true);
    try {
      for (const file of files) {
        const entry = await uploadPhoto(editing.id, file);
        setPhotos((p) => [...p, entry]);
      }
      toast.success('Foto desain diunggah');
      fetchStyles();
    } catch (err) {
      toast.error(err.userMessage || err.detail || 'Gagal mengunggah foto');
    } finally {
      setUploadingPhoto(false);
    }
  };

  const handlePhotoDelete = async (imgId) => {
    try {
      await apiFetch(`/dewi/rnd/styles/${editing.id}/images/${imgId}`, { method: 'DELETE' });
      setPhotos((p) => p.filter((x) => x.id !== imgId));
      toast.success('Foto desain dihapus');
      fetchStyles();
    } catch (err) {
      toast.error(err.userMessage || 'Gagal menghapus foto');
    }
  };

  // 10 Nov 2026 (owner "master data bisa dihapus"): server kini menolak (409) style yang sudah punya tech pack,
  // HPP, sampel, atau sudah jadi produk; dialog kedua menawarkan Nonaktifkan = Arsipkan (status draft/aktif saja — status
  // keputusan owner tidak bisa diubah dari sini).
  const handleDelete = async (s) => {
    const bisaArsip = s.status === 'draft' || s.status === 'active';
    const hasil = await hapusMaster({
      jenis: 'style', nama: [s.style_code, s.style_name].filter(Boolean).join(' '),
      keterangan: 'Style dihapus permanen beserta varian warna dan riwayat revisinya. Bila sudah punya tech pack, '
        + 'HPP, sampel, atau sudah jadi produk, penghapusan ditolak' + (bisaArsip ? ' dan Anda bisa menonaktifkannya (arsipkan) saja.' : '.'),
      hapus: () => apiFetch(`/dewi/rnd/styles/${s.id}`, { method: 'DELETE' }),
      nonaktifkan: bisaArsip ? () => apiFetch(`/dewi/rnd/styles/${s.id}`, { method: 'PUT', body: { status: 'archived' } }) : null,
    });
    if (hasil) fetchStyles();
  };

  // GAP-R2: Ajukan ke owner
  const handleSubmitForReview = async (styleId, notes) => {
    try {
      await apiFetch(`/dewi/rnd/styles/${styleId}/submit-for-review`, { method: 'POST', body: { notes } });
      toast.success('Style diajukan ke owner untuk ditinjau');
      setSubmitReviewDialog(null);
      fetchStyles();
      if (isOwner) fetchPendingCount();
    } catch (e) {
      if (e instanceof ApiError && !e.isUnauthorized) toast.error(e.userMessage || 'Gagal mengajukan ke owner');
    }
  };

  // GAP-R2: Owner menyetujui
  const handleOwnerApprove = async (styleId, notes) => {
    try {
      await apiFetch(`/dewi/rnd/styles/${styleId}/owner-approve`, { method: 'POST', body: { notes } });
      toast.success('Style berhasil disetujui');
      setOwnerReviewDialog(null);
      fetchStyles();
      if (isOwner) fetchPendingCount();
    } catch (e) {
      if (e instanceof ApiError && !e.isUnauthorized) toast.error(e.userMessage || 'Gagal menyetujui style');
    }
  };

  // GAP-R2: Owner menolak
  const handleOwnerReject = async (styleId, notes) => {
    if (!notes.trim()) { toast.error('Catatan penolakan wajib diisi'); return; }
    try {
      await apiFetch(`/dewi/rnd/styles/${styleId}/owner-reject`, { method: 'POST', body: { notes } });
      toast.success('Style ditolak dan dikembalikan ke draf');
      setOwnerReviewDialog(null);
      fetchStyles();
      if (isOwner) fetchPendingCount();
    } catch (e) {
      if (e instanceof ApiError && !e.isUnauthorized) toast.error(e.userMessage || 'Gagal menolak style');
    }
  };

  // RND-01: promosi style approved_for_launch → Model DA (POST /styles/{id}/promote-to-production)
  const [promotingId, setPromotingId] = useState(null);
  const handlePromote = async (style) => {
    const ok = await confirmDialog({
      title: `Promosikan ${style.style_code} — ${style.style_name} menjadi Model DA?`,
      body: `Model baru muncul di Portal Produksi dengan kode produk ${style.style_code} (ubah di Master Produk bila perlu).`,
      confirmLabel: 'Promosikan',
    });
    if (!ok) return;
    setPromotingId(style.id);
    try {
      const res = await apiFetch(`/dewi/rnd/styles/${style.id}/promote-to-production`, { method: 'POST', body: {} });
      toast.success(`Style dipromosikan → Model ${res?.model_code || res?.model?.code || style.style_code}`);
      fetchStyles();
    } catch (e) {
      if (e instanceof ApiError && !e.isUnauthorized) toast.error(e.userMessage || e.detail || 'Gagal mempromosikan style');
    } finally {
      setPromotingId(null);
    }
  };

  const { page: stylesPage, setPage: setStylesPage, totalPages: stylesTotalPages, total: stylesTotal, paged: pagedStyles } = useClientPagination(styles, PER_HALAMAN);

  const togglePendingInbox = () => {
    setShowPendingInbox(!showPendingInbox);
    if (!showPendingInbox) setFilterStatus('pending_owner_review'); else setFilterStatus('');
  };

  /** Aksi alur sesuai status (paling banyak satu yang berlaku: Tinjau / Promosikan / Ajukan). */
  const aksiAlur = (style) => {
    const canSubmitReview = (style.status === 'draft' || style.status === 'active');
    const pendingReview = style.status === 'pending_owner_review';
    const canPromote = style.status === 'approved_for_launch' && style.rnd_type !== 'maklon_product' && !style.promoted_to_model_id;
    if (isOwner && pendingReview) {
      return (
        <Button size="sm" variant="outline" onClick={() => setOwnerReviewDialog(style)} title="Tinjau desain"
          data-testid={`owner-review-style-${style.id}`}>
          <MessageSquare />Tinjau
        </Button>
      );
    }
    if (canPromote) {
      return (
        <Button size="sm" variant="outline" onClick={() => handlePromote(style)} disabled={promotingId === style.id}
          title="Promosikan style ini menjadi Model DA di Portal Produksi" data-testid={`promote-style-${style.id}`}>
          <Rocket />{promotingId === style.id ? 'Mempromosikan…' : 'Promosikan'}
        </Button>
      );
    }
    if (canSubmitReview) {
      return (
        <Button size="sm" variant="outline" onClick={() => setSubmitReviewDialog(style)} title="Ajukan ke owner"
          data-testid={`submit-review-${style.id}`}>
          <Send />Ajukan
        </Button>
      );
    }
    return null;
  };

  const kolom = [
    { kunci: 'kode', label: 'Kode', hp: 'keterangan', isi: (s) => <span className="text-sm font-medium">{s.style_code}</span> },
    { kunci: 'nama', label: 'Nama style', hp: 'judul', isi: (s) => (
      <div className="min-w-0 md:max-w-[20rem]">
        <p className="font-medium text-foreground">{s.style_name}</p>
        <ReviewHistoryLine style={s} />
        {s.status === 'pending_owner_review' && s.submitted_for_review_by && (
          <p className="mt-0.5 flex items-center gap-1 text-xs text-[hsl(var(--warning-text))]">
            <Clock className="h-3 w-3" />Diajukan oleh {s.submitted_for_review_by}
          </p>
        )}
      </div>) },
    { kunci: 'kategori', label: 'Kategori', isi: (s) => s.category || '—' },
    { kunci: 'klien', label: 'Klien', hp: false, isi: (s) => s.client_name || s.buyer || 'Internal DA' },
    { kunci: 'musim', label: 'Musim', hp: false, isi: (s) => s.season || '—' },
    { kunci: 'varian', label: 'Varian', rata: 'kanan', isi: (s) => {
      const n = s.variants_count ?? (s.variants || []).length;
      return n > 0 ? <span className="tabular-nums">{n}</span> : <span className="text-muted-foreground">—</span>;
    } },
    { kunci: 'status', label: 'Status', isi: (s) => <StyleStatusBadge status={s.status} /> },
    { kunci: 'aksi', label: 'Aksi', rata: 'kanan', hp: 'aksi', isi: (s) => (
      <div className="flex items-center justify-end gap-1">
        {aksiAlur(s)}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="icon-sm" variant="ghost" title="Lainnya" aria-label={`Aksi lain untuk ${s.style_code}`}
              data-testid={`more-style-${s.id}`}>
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => setDetailStyleId(s.id)} data-testid={`detail-style-${s.id}`}>
              <Eye className="mr-2 h-4 w-4" />Lihat detail
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => openEdit(s)} data-testid={`edit-style-${s.id}`}>
              <Pencil className="mr-2 h-4 w-4" />Ubah
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => handleDelete(s)} data-testid={`delete-style-${s.id}`}
              className="text-[hsl(var(--danger-text))] focus:text-[hsl(var(--danger-text))]">
              <Trash2 className="mr-2 h-4 w-4" />Hapus
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>) },
  ];

  const statusLabel = (s) => (STATUS_STYLE[s] || STATUS_STYLE.draft).label;

  return (
    <PageLayout testId="rnd-styles-tab" title="Daftar style"
      subtitle="Style desain RnD: ajukan ke owner, setujui, lalu promosikan menjadi model produksi."
      actions={<Button onClick={openCreate} data-testid="create-style-btn"><Plus />Tambah style</Button>}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari kode atau nama style"
            className="pl-8" data-testid="rnd-style-search" />
        </div>
        <SmartNativeSelect value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}
          className="w-52" wrapperClassName="w-52" aria-label="Status" data-testid="filter-status-select">
          <option value="">Semua status</option>
          <option value="draft">Draf</option>
          <option value="active">Aktif</option>
          <option value="pending_owner_review">Menunggu tinjauan owner</option>
          <option value="approved_for_launch">Disetujui owner</option>
          <option value="promoted">Dipromosikan</option>
          <option value="archived">Diarsipkan</option>
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="daftar-style-rnd" namaLembar="Style" baris={styles} testId="rnd-style-unduh"
          kolom={[
            { label: 'Kode', nilai: (s) => s.style_code },
            { label: 'Nama style', nilai: (s) => s.style_name },
            { label: 'Kategori', nilai: (s) => s.category || '' },
            { label: 'Klien', nilai: (s) => s.client_name || s.buyer || 'Internal DA' },
            { label: 'Jenis kain', nilai: (s) => s.fabric_type || '' },
            { label: 'Musim', nilai: (s) => s.season || '' },
            { label: 'Varian', nilai: (s) => Number(s.variants_count ?? (s.variants || []).length) || 0 },
            { label: 'Status', nilai: (s) => statusLabel(s.status) },
            { label: 'Keputusan owner', nilai: (s) => (s.owner_review_result
              ? `${s.owner_review_result === 'approved' ? 'Disetujui' : 'Ditolak'} oleh ${s.owner_reviewed_by || ''}${s.owner_review_notes ? ` — ${s.owner_review_notes}` : ''}`
              : '') },
            { label: 'Dibuat', nilai: (s) => (s.created_at ? formatDateID(s.created_at) : '') },
          ]} />
        <Button variant="outline" size="icon" onClick={fetchStyles} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={isOwner && pendingCount > 0 ? (
        <Notice tone="warning" icon={AlertCircle} title={`${pendingCount} style menunggu tinjauan Anda`}
          action={(
            <Button size="sm" variant="outline" onClick={togglePendingInbox} data-testid="view-pending-review-btn">
              {showPendingInbox ? 'Tampilkan semua' : 'Lihat yang menunggu'}
            </Button>
          )} />
      ) : null}
      footer={!loading && styles.length > PER_HALAMAN ? (
        <PaginationLite page={stylesPage} totalPages={stylesTotalPages} total={stylesTotal} pageSize={PER_HALAMAN}
          onPageChange={setStylesPage} />
      ) : null}>
      {loading && styles.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat style…</p>
      ) : (
        <TabelData kolom={kolom} baris={pagedStyles} onKlikBaris={(s) => setDetailStyleId(s.id)} testId="rnd-style-table"
          kosong={<EmptyState title={search || filterStatus ? 'Tidak ada style yang cocok' : 'Belum ada style'}
            description={search || filterStatus ? 'Ubah kata pencarian atau pilihan status.' : 'Tambah style pertama untuk mulai mendokumentasikan desain.'}
            action={!search && !filterStatus && <Button onClick={openCreate}><Plus />Tambah style</Button>} />} />
      )}

      {/* ── Form Tambah/Ubah style ── */}
      <FormPopup open={showForm} onClose={() => setShowForm(false)} ukuran="panjang" onSimpan={handleSave}
        menyimpan={saving} galat={formErr} testId="rnd-style-form"
        judul={editing ? 'Ubah style' : 'Tambah style'}
        keterangan="Kategori, klien, dan jenis kain diambil dari master supaya cocok saat style naik ke produksi."
        labelSimpan={editing ? 'Simpan perubahan' : 'Simpan style'}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Kode style" wajib htmlFor="style-code">
            <Input id="style-code" value={form.style_code} onChange={(e) => setForm({ ...form, style_code: e.target.value.toUpperCase() })}
              placeholder="ST-001" data-testid="style-code-input" />
          </Isian>
          <Isian label="Nama style" wajib htmlFor="style-name">
            <Input id="style-name" value={form.style_name} onChange={(e) => setForm({ ...form, style_name: e.target.value })}
              placeholder="Kaus dasar premium" data-testid="style-name-input" />
          </Isian>
          <Isian label="Kategori" petunjuk="Dari master Kategori Produk.">
            <SmartNativeSelect value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}
              className="w-full" aria-label="Kategori" data-testid="style-category-select">
              <option value="">— Pilih kategori produk —</option>
              {form.category && !categories.some(c => c.name === form.category) && (
                <option value={form.category}>{`${form.category} (belum ada di master)`}</option>
              )}
              {categories.map(c => <option key={c.id} value={c.name}>{c.name}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Klien" petunjuk="Dari master Klien maklon. Kosong = produk internal DA.">
            <SmartNativeSelect value={buyerValue} onChange={(e) => pickBuyer(e.target.value)}
              className="w-full" aria-label="Klien" data-testid="style-buyer-select">
              <option value="">— Internal DA (tanpa klien) —</option>
              {buyerValue === LEGACY && <option value={LEGACY}>{`${form.buyer} (lama, belum di master)`}</option>}
              {formOpts.buyers.map(b => <option key={b.id} value={b.id}>{`${b.code ? `${b.code} · ` : ''}${b.name}`}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Jenis kain" petunjuk="Dari master kain (Master Material).">
            <SmartNativeSelect value={form.fabric_type} onChange={(e) => setForm({ ...form, fabric_type: e.target.value })}
              className="w-full" aria-label="Jenis kain" data-testid="style-fabric-select">
              <option value="">— Pilih jenis kain —</option>
              {fabricLegacy && <option value={form.fabric_type}>{`${form.fabric_type} (lama, belum ada di master)`}</option>}
              {formOpts.fabric_types.map(n => <option key={n} value={n}>{n}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Musim" htmlFor="style-season">
            <Input id="style-season" value={form.season} onChange={(e) => setForm({ ...form, season: e.target.value })}
              placeholder="Lebaran 2027" data-testid="style-season-input" />
          </Isian>
          <Isian label="Deskripsi" htmlFor="style-desc" className="sm:col-span-2">
            <Textarea id="style-desc" rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder="Kaus leher bulat klasik…" data-testid="style-desc-input" />
          </Isian>
          <Isian label="Status"
            petunjuk={LIFECYCLE_STATUSES.includes(form.status)
              ? 'Diatur lewat tombol Ajukan / Setujui / Tolak agar keputusan tercatat beserta pemutus dan alasannya.'
              : undefined}>
            {LIFECYCLE_STATUSES.includes(form.status) ? (
              /* Status keputusan (menunggu tinjauan / disetujui owner) TIDAK boleh diubah dari form ubah —
                 dulu pilihannya menampilkan "Draft" secara keliru sehingga status tinjauan bisa terhapus. */
              <div className="flex h-9 items-center" data-testid="style-status-locked">
                <StyleStatusBadge status={form.status} />
              </div>
            ) : (
              <SmartNativeSelect value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}
                className="w-full" aria-label="Status" data-testid="style-status-select">
                {form.status === 'promoted' && <option value="promoted">Dipromosikan</option>}
                <option value="draft">Draf</option>
                <option value="active">Aktif</option>
                <option value="archived">Diarsipkan</option>
              </SmartNativeSelect>
            )}
          </Isian>
        </div>

        {/* ── Foto / sketsa desain ── */}
        <Isian label="Foto / sketsa desain"
          petunjuk="Tampil di galeri persetujuan manajemen dan ikut tersimpan pada riwayat revisi. Maks 10MB per foto.">
          <div className="space-y-3" data-testid="style-photos-section">
            <Button asChild variant="outline" size="sm">
              <label className="cursor-pointer" data-testid="style-photo-upload-label">
                {uploadingPhoto ? <Loader2 className="animate-spin" /> : <ImagePlus />}
                {uploadingPhoto ? 'Mengunggah…' : 'Pilih foto'}
                <input type="file" accept="image/*" multiple hidden disabled={uploadingPhoto}
                  onChange={handlePhotoInput} data-testid="style-photo-input" />
              </label>
            </Button>
            {photos.length === 0 && pendingPhotos.length === 0 ? (
              <p className="text-sm text-muted-foreground" data-testid="style-photo-empty">Foto desain belum diunggah.</p>
            ) : (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4" data-testid="style-photo-grid">
                {photos.map((p) => (
                  <div key={p.id} className="relative overflow-hidden rounded-lg border border-[var(--glass-border)]">
                    <img
                      src={`${API}${p.url}${(p.url || '').includes('?') ? '&' : '?'}auth=${encodeURIComponent(token || '')}`}
                      alt={p.caption || 'Foto desain'} className="h-24 w-full object-cover" loading="lazy"
                    />
                    <Button type="button" variant="outline" size="icon-sm" onClick={() => handlePhotoDelete(p.id)}
                      className="absolute right-1 top-1 text-[hsl(var(--danger-text))]" title="Hapus foto" aria-label="Hapus foto"
                      data-testid={`style-photo-delete-${p.id}`}>
                      <Trash2 />
                    </Button>
                    <p className="truncate px-2 py-1 text-xs text-muted-foreground">{p.caption || '—'}</p>
                  </div>
                ))}
                {pendingPhotos.map((f, i) => (
                  <div key={`pending-${i}`} className="relative overflow-hidden rounded-lg border border-dashed border-[var(--glass-border)]">
                    <img src={URL.createObjectURL(f)} alt={f.name} className="h-24 w-full object-cover" />
                    <Button type="button" variant="outline" size="icon-sm"
                      onClick={() => setPendingPhotos((p) => p.filter((_, idx) => idx !== i))}
                      className="absolute right-1 top-1" title="Batal unggah" aria-label="Batal unggah"
                      data-testid={`style-photo-pending-remove-${i}`}>
                      <X />
                    </Button>
                    <p className="truncate px-2 py-1 text-xs text-[hsl(var(--warning-text))]">Akan diunggah: {f.name}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </Isian>
      </FormPopup>

      {submitReviewDialog && (
        <SubmitForReviewDialog
          style={submitReviewDialog}
          onClose={() => setSubmitReviewDialog(null)}
          onSubmit={handleSubmitForReview}
        />
      )}

      {ownerReviewDialog && (
        <OwnerReviewDialog
          style={ownerReviewDialog}
          onClose={() => setOwnerReviewDialog(null)}
          onApprove={handleOwnerApprove}
          onReject={handleOwnerReject}
        />
      )}

      {detailStyleId && (
        <RnDStyleDetailPage
          token={token}
          styleId={detailStyleId}
          onClose={() => setDetailStyleId(null)}
        />
      )}
    </PageLayout>
  );
}

// ─── Sub-komponen ──────────────────────────────────────────────────────────────

function SubmitForReviewDialog({ style, onClose, onSubmit }) {
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);

  const handleSubmit = async () => {
    setSaving(true);
    await onSubmit(style.id, notes);
    setSaving(false);
  };

  return (
    <FormPopup open onClose={onClose} ukuran="pendek" onSimpan={handleSubmit} menyimpan={saving}
      judul="Ajukan ke owner" keterangan={`${style.style_code} — ${style.style_name}`}
      labelSimpan="Ajukan" testId="submit-review-dialog">
      <p className="text-sm text-muted-foreground">
        Style ini dikirim ke owner untuk ditinjau dan disetujui sebelum dilanjutkan ke produksi.
      </p>
      <Isian label="Catatan untuk owner" petunjuk="Opsional." htmlFor="review-notes">
        <Textarea id="review-notes" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)}
          placeholder="Contoh: style siap ditinjau, sample sudah disiapkan…" data-testid="review-notes-input" />
      </Isian>
    </FormPopup>
  );
}

function OwnerReviewDialog({ style, onClose, onApprove, onReject }) {
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [galat, setGalat] = useState('');

  const approve = async () => {
    setGalat('');
    setSaving(true);
    await onApprove(style.id, notes);
    setSaving(false);
  };
  const reject = async () => {
    if (!notes.trim()) { setGalat('Catatan penolakan wajib diisi.'); return; }
    setGalat('');
    setSaving(true);
    await onReject(style.id, notes);
    setSaving(false);
  };

  return (
    <FormPopup open onClose={onClose} ukuran="pendek" onSimpan={approve} menyimpan={saving} galat={galat}
      judul="Tinjau desain style" keterangan={`${style.style_code} — ${style.style_name}`}
      labelSimpan="Setujui" testId="owner-review-dialog"
      aksiKiri={(
        <Button type="button" variant="destructive" onClick={reject} disabled={saving} data-testid="owner-reject-option">
          <XCircle />Tolak
        </Button>
      )}>
      <dl className="divide-y divide-[var(--glass-border)]">
        {style.category && <BarisDetail label="Kategori">{style.category}</BarisDetail>}
        <BarisDetail label="Klien">{style.client_name || style.buyer || 'Internal DA'}</BarisDetail>
        {style.fabric_type && <BarisDetail label="Jenis kain">{style.fabric_type}</BarisDetail>}
        {style.season && <BarisDetail label="Musim">{style.season}</BarisDetail>}
        {style.description && <BarisDetail label="Deskripsi">{style.description}</BarisDetail>}
        {style.submitted_for_review_by && (
          <BarisDetail label="Diajukan oleh">
            {style.submitted_for_review_by}
            {style.review_notes && <span className="text-muted-foreground"> — {style.review_notes}</span>}
          </BarisDetail>
        )}
      </dl>
      <Isian label="Catatan" htmlFor="owner-review-notes" petunjuk="Wajib diisi bila menolak; opsional bila menyetujui.">
        <Textarea id="owner-review-notes" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)}
          placeholder="Alasan penolakan atau catatan tambahan…" data-testid="owner-review-notes-input" />
      </Isian>
    </FormPopup>
  );
}

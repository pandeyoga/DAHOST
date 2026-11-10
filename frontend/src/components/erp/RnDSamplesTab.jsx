/**
 * RnDSamplesTab — Sample Request (Portal RnD; juga tab di RnDModule lama).
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, penyaring satu baris (pil status + cari), tabel + unduh,
 * aksi baris maks 2 + "Lainnya", rincian = DetailPopup, semua form = FormPopup (buat request, setujui,
 * request aksesoris), tolak & hapus lewat confirmDialog, tanggal lewat DatePicker, warna token.
 * Kotak "Setelah sample disetujui" (huruf kapital, selebar halaman) → menu "Langkah berikutnya".
 * Endpoint, isian, dan validasi tidak berubah.
 *
 * 2026-11-10 (keputusan owner): baris request aksesoris DIPILIH dari master aksesoris (satuan & stok gudang
 * tampil); barang yang belum ada di master tetap bisa diketik lewat pilihan "Belum ada di master" dan ditandai
 * "Belum tertaut". Status sample tidak berubah karena aksesoris — kolom status diberi keterangan
 * "Aksesoris menunggu / disiapkan / terkirim / ditolak" (`accessory_status` dari server).
 */
import { useState, useEffect, useMemo } from 'react';
import {
  ArrowRight, CheckCircle, FileStack, Factory, FlaskConical, MoreHorizontal, Package, Plus, RefreshCw,
  Search, Send, Trash2, XCircle,
} from 'lucide-react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import DatePicker from '@/components/ui/date-picker';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Skeleton } from '@/components/ui/skeleton';
import { toast } from '../ui/sonner';
import { apiFetch, ApiError } from '@/lib/apiFetch';
import { formatDateID, formatDateTimeID } from '@/lib/format';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import DocNumberField, { useDocNumberPolicy, docNumberPayload } from './docnum/DocNumberField';
import RnDUnitSelect from './RnDUnitSelect';
import { useActiveEmployees, employeeLabel } from './hr/hrPickers';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatusBadge } from './moduleAtoms';

const STATUS_CONF = {
  draft:     { label: 'Draf',      tone: 'muted' },
  submitted: { label: 'Diajukan',  tone: 'warning' },
  approved:  { label: 'Disetujui', tone: 'success' },
  rejected:  { label: 'Ditolak',   tone: 'danger' },
};
const PRIORITY = {
  high:   { label: 'Tinggi', tone: 'danger' },
  normal: { label: 'Normal', tone: 'info' },
  low:    { label: 'Rendah', tone: 'muted' },
};
const statusOf = (s) => STATUS_CONF[s] || STATUS_CONF.draft;
const prioOf = (p) => PRIORITY[p] || PRIORITY.normal;

const emptyForm = {
  style_id: '', quantity: 1, priority: 'normal', sample_pic: '', sample_pic_employee_id: '',
  sample_pic_external: false, due_date: '', notes: '',
};
const BARIS_AKS = () => ({ material_id: '', material_code: '', material_name: '', qty: 1, unit: 'pcs', notes: '', manual: false });
// Pilihan cadangan: barang belum ada di master → diketik, ditautkan tim aksesoris saat diserahkan.
const AKS_MANUAL = '__manual__';
// Keterangan aksesoris di daftar sample (status sample sendiri tidak berubah).
const AKS_STATE = {
  submitted: 'menunggu',
  allocated: 'disiapkan',
  delivered: 'terkirim',
  rejected: 'ditolak',
};
const aksesorisTeks = (a) => {
  if (!a || !AKS_STATE[a.state]) return '';
  const aktif = (a.total || 0) - (a.rejected || 0);
  return `Aksesoris ${AKS_STATE[a.state]}${aktif > 1 && a.state !== 'delivered' ? ` · ${a.delivered || 0}/${aktif} terkirim` : ''}`;
};
const angka = (v) => Number(v || 0).toLocaleString('id-ID', { maximumFractionDigits: 2 });

// 2026-11-07 (Tahap 6, HR4): PIC sample DIPILIH dari karyawan aktif — karyawan bagian sample (departemen /
// jabatan / peran memuat "sample", "RnD", "riset") ditawarkan paling atas. Penjahit luar tetap bisa lewat
// pilihan eksplisit "Penjahit luar — ketik nama" (disimpan dengan penanda `sample_pic_external`).
const PIC_EXTERNAL = '__luar__';
const SAMPLE_DEPT_RX = /sampl|\brnd\b|r\s*&\s*d|riset/i;
const isSampleStaff = (e) => [e?.department, e?.job_title, e?.position, e?.role_hint]
  .some((v) => v && SAMPLE_DEPT_RX.test(String(v)));

const tgl = (v) => (v ? formatDateID(v) : '—');

export default function RnDSamplesTab({ token, onNavigate }) {
  const [samples,  setSamples]  = useState([]);
  const [styles,   setStyles]   = useState([]);
  const [loading,  setLoading]  = useState(false);
  const [filterStatus, setFilterStatus] = useState('');
  const [search,   setSearch]   = useState('');
  const [showForm, setShowForm] = useState(false);
  const [form,     setForm]     = useState({ ...emptyForm });
  const [saving,   setSaving]   = useState(false);
  // Popup setujui (catatan opsional). Tolak memakai confirmDialog dengan alasan wajib.
  const [actionModal, setActionModal] = useState(null); // { id, type: 'approve', notes: '' }
  const [detail, setDetail] = useState(null);

  // Session 27 — Accessory Request Modal (GAP-R3)
  const [accReqModal, setAccReqModal] = useState(null); // { sample: {...}, items: [...], urgent, needed_by_date, notes }
  // SESI #27 — kebijakan penomoran Permintaan Aksesoris. TIPE=REQ-AKS (sampel R&D).
  const accNumPolicy = useDocNumberPolicy('dewi_accessory_requests.request_code',
                                          localStorage.getItem('erp_token'),
                                          { TIPE: 'REQ-AKS' });
  const [accReqCode, setAccReqCode] = useState('');
  // Master aksesoris (kode, nama, satuan, stok gudang) — dimuat saat form request aksesoris dibuka.
  const [accMasters, setAccMasters] = useState(null);
  const masterById = useMemo(() => new Map((accMasters || []).map((m) => [m.id, m])), [accMasters]);

  const f = (k, v) => setForm(p => ({ ...p, [k]: v }));

  const { employees } = useActiveEmployees(token, { enabled: showForm });
  const picChoices = useMemo(() => {
    const list = (employees || []).filter((e) => e && e.id);
    return [...list.filter(isSampleStaff).map((e) => ({ ...e, sampleStaff: true })),
            ...list.filter((e) => !isSampleStaff(e))];
  }, [employees]);
  const picValue = form.sample_pic_employee_id || (form.sample_pic_external ? PIC_EXTERNAL : '');
  const pickPic = (v) => {
    if (v === PIC_EXTERNAL) { setForm(p => ({ ...p, sample_pic_employee_id: '', sample_pic_external: true, sample_pic: '' })); return; }
    const emp = (employees || []).find((e) => e.id === v);
    setForm(p => ({ ...p, sample_pic_employee_id: v, sample_pic_external: false, sample_pic: emp?.name || '' }));
  };

  const fetchSamples = async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      if (filterStatus) qs.set('status', filterStatus);
      if (search) qs.set('search', search);
      const data = await apiFetch(`/dewi/rnd/sample-requests${qs.toString() ? '?' + qs : ''}`);
      setSamples(Array.isArray(data) ? data : []);
    } catch (e) {
      if (e instanceof ApiError && !e.isUnauthorized) toast.error('Gagal memuat sample');
    } finally { setLoading(false); }
  };

  const fetchStyles = async () => {
    try {
      const data = await apiFetch('/dewi/rnd/styles');
      setStyles(Array.isArray(data) ? data : []);
    } catch { /* ignore */ }
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { fetchSamples(); }, [filterStatus]);
  useEffect(() => { fetchStyles(); }, []);

  const handleCreate = async () => {
    if (!form.style_id) return toast.error('Pilih style terlebih dahulu');
    if (!(Number(form.quantity) > 0)) return toast.error('Jumlah sample minimal 1 pcs');
    if (form.sample_pic_external && !String(form.sample_pic || '').trim()) return toast.error('Ketik nama penjahit luar');
    setSaving(true);
    try {
      await apiFetch('/dewi/rnd/sample-requests', { method: 'POST', body: { ...form, quantity: Number(form.quantity) } });
      toast.success('Request sample berhasil dibuat');
      setShowForm(false);
      setForm({ ...emptyForm });
      fetchSamples();
    } catch (e) {
      if (e instanceof ApiError && !e.isUnauthorized) toast.error('Gagal membuat sample');
    } finally { setSaving(false); }
  };

  const handleSubmit = async (id) => {
    try {
      await apiFetch(`/dewi/rnd/sample-requests/${id}/submit`, { method: 'POST' });
      toast.success('Sample berhasil diajukan');
      setDetail(null);
      fetchSamples();
    } catch (e) {
      if (e instanceof ApiError && !e.isUnauthorized) toast.error('Gagal mengajukan sample');
    }
  };

  const kirimKeputusan = async (id, type, notes) => {
    try {
      await apiFetch(`/dewi/rnd/sample-requests/${id}/${type}`, {
        method: 'POST', body: { notes },
      });
      toast.success(type === 'approve' ? 'Sample disetujui' : 'Sample ditolak');
      setActionModal(null);
      setDetail(null);
      fetchSamples();
    } catch (e) {
      if (e instanceof ApiError && !e.isUnauthorized) toast.error(type === 'approve' ? 'Gagal menyetujui sample' : 'Gagal menolak sample');
    }
  };

  const handleApprove = () => {
    if (!actionModal) return;
    kirimKeputusan(actionModal.id, 'approve', actionModal.notes || '');
  };

  const tolak = async (s) => {
    const alasan = await confirmDialog({
      title: `Tolak sample ${s.sample_code}?`, body: 'Alasan penolakan wajib diisi dan tercatat di request ini.',
      confirmLabel: 'Tolak sample', danger: true,
      input: { label: 'Alasan penolakan', placeholder: 'Alasan penolakan wajib diisi…', minLength: 1 },
    });
    if (alasan === false || alasan === null || alasan === undefined) return;
    if (!String(alasan).trim()) return toast.error('Alasan tolak wajib diisi');
    kirimKeputusan(s.id, 'reject', String(alasan));
  };

  const hapus = async (s) => {
    const ok = await confirmDialog({
      title: 'Hapus request sample?', body: `${s.sample_code} akan dihapus permanen.`,
      confirmLabel: 'Hapus', danger: true,
    });
    if (!ok) return;
    try {
      await apiFetch(`/dewi/rnd/sample-requests/${s.id}`, { method: 'DELETE' });
      toast.success('Sample dihapus');
      setDetail(null);
      fetchSamples();
    } catch { toast.error('Gagal menghapus'); }
  };

  // ── Session 27 — GAP-R3 Accessory Request Handlers ────────────────────────
  const openAccReq = (sample) => {
    setDetail(null);
    setAccReqModal({
      sample,
      items: [BARIS_AKS()],
      urgent: false,
      needed_by_date: '',
      notes: '',
      submitting: false,
    });
    if (accMasters === null) {
      apiFetch('/acc/items')
        .then((data) => setAccMasters(Array.isArray(data) ? data : []))
        .catch(() => { setAccMasters([]); toast.error('Daftar master aksesoris gagal dimuat — barang bisa diketik manual.'); });
    }
  };

  const updateAccReqItem = (idx, field, value) => {
    setAccReqModal(prev => {
      if (!prev) return prev;
      const items = [...prev.items];
      items[idx] = { ...items[idx], [field]: value };
      return { ...prev, items };
    });
  };

  // Pilih master (kode, nama, satuan dari master) atau beralih ke ketik manual ("belum tertaut").
  const pickAccMaster = (idx, value) => {
    setAccReqModal(prev => {
      if (!prev) return prev;
      const items = [...prev.items];
      const cur = items[idx];
      if (value === AKS_MANUAL) {
        items[idx] = { ...cur, manual: true, material_id: '', material_code: '', material_name: '' };
      } else {
        const m = masterById.get(value);
        items[idx] = m
          ? { ...cur, manual: false, material_id: m.id, material_code: m.code || '', material_name: m.name || '', unit: m.unit || 'pcs' }
          : { ...cur, manual: false, material_id: '', material_code: '', material_name: '' };
      }
      return { ...prev, items };
    });
  };

  const addAccReqItemRow = () => {
    setAccReqModal(prev => prev ? ({ ...prev, items: [...prev.items, BARIS_AKS()] }) : prev);
  };

  const removeAccReqItemRow = (idx) => {
    setAccReqModal(prev => {
      if (!prev) return prev;
      if (prev.items.length <= 1) return prev;
      return { ...prev, items: prev.items.filter((_, i) => i !== idx) };
    });
  };

  const handleSubmitAccReq = async () => {
    if (!accReqModal) return;
    const terisi = (it) => it.material_id || (it.manual && String(it.material_name || '').trim());
    const validItems = accReqModal.items
      .filter(it => terisi(it) && Number(it.qty) > 0)
      .map(({ manual, ...it }) => ({
        ...it, qty: Number(it.qty),
        material_id: manual ? '' : it.material_id,
        material_name: String(it.material_name || '').trim(),
        material_code: String(it.material_code || '').trim(),
      }));
    if (accReqModal.items.some(it => it.manual && !String(it.material_name || '').trim() && Number(it.qty) > 0)) {
      toast.error('Barang yang diketik manual wajib diberi nama.');
      return;
    }
    if (validItems.length === 0) {
      toast.error('Pilih minimal 1 aksesoris dengan jumlah lebih dari 0.');
      return;
    }
    try {
      setAccReqModal(p => ({ ...p, submitting: true }));
      const payload = {
        sample_request_id: accReqModal.sample.id,
        style_id: accReqModal.sample.style_id,
        style_code: accReqModal.sample.style_code,
        style_name: accReqModal.sample.style_name,
        items: validItems,
        urgent: !!accReqModal.urgent,
        needed_by_date: accReqModal.needed_by_date || '',
        notes: accReqModal.notes || '',
        status: 'submitted',  // langsung submit ke Admin Aksesoris
        ...docNumberPayload(accNumPolicy, 'request_code', accReqCode),
      };
      const res = await apiFetch('/dewi/accessory-requests', { method: 'POST', body: payload });
      toast.success(`Request aksesoris ${res.request_code} terkirim ke tim aksesoris`);
      setAccReqModal(null);
      fetchSamples();
    } catch (e) {
      if (e instanceof ApiError && !e.isUnauthorized) {
        toast.error(e?.body?.detail || 'Gagal membuat request aksesoris');
      } else if (!(e instanceof ApiError)) {
        toast.error('Gagal membuat request aksesoris');
      }
      setAccReqModal(p => p ? ({ ...p, submitting: false }) : p);
    }
  };

  const filtered = samples.filter(s => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (s.sample_code || '').toLowerCase().includes(q)
      || (s.style_name || '').toLowerCase().includes(q)
      || (s.style_code || '').toLowerCase().includes(q);
  });

  const { page, setPage, totalPages, total, paged } = useClientPagination(filtered, 25);

  /** Aksi baris: paling banyak 2 tombol tampil, sisanya di "Lainnya". */
  const AksiBaris = ({ s }) => {
    return (
      <div className="flex items-center justify-end gap-1.5">
        {s.status === 'draft' && (
          <Button size="sm" variant="outline" onClick={() => handleSubmit(s.id)} data-testid={`submit-sample-${s.id}`}>
            <Send />Ajukan
          </Button>
        )}
        {s.status === 'submitted' && (
          <>
            <Button size="sm" variant="success" onClick={() => setActionModal({ id: s.id, type: 'approve', notes: '', code: s.sample_code })}
              data-testid={`approve-sample-${s.id}`}>
              <CheckCircle />Setujui
            </Button>
            <Button size="sm" variant="outline" onClick={() => tolak(s)} data-testid={`reject-sample-${s.id}`}>
              <XCircle />Tolak
            </Button>
          </>
        )}
        {s.status === 'approved' && (
          <Button size="sm" variant="outline" onClick={() => openAccReq(s)} title="Request aksesoris ke Admin Aksesoris"
            data-testid={`req-acc-sample-${s.id}`}>
            <Package />Aksesoris
          </Button>
        )}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="icon-sm" variant="ghost" aria-label="Lainnya" title="Lainnya" data-testid={`more-sample-${s.id}`}>
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => setDetail(s)}>Lihat rincian</DropdownMenuItem>
            {s.status === 'submitted' && (
              <DropdownMenuItem onSelect={() => openAccReq(s)} data-testid={`req-acc-sample-${s.id}`}>
                <Package className="mr-2 h-4 w-4" />Request aksesoris
              </DropdownMenuItem>
            )}
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => hapus(s)} className="text-[hsl(var(--danger-text))]"
              data-testid={`delete-sample-${s.id}`}>
              <Trash2 className="mr-2 h-4 w-4" />Hapus
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    );
  };

  const kolom = [
    { kunci: 'kode', label: 'Kode sample', hp: 'judul', isi: (s) => <span className="font-mono text-xs font-semibold">{s.sample_code}</span> },
    { kunci: 'style', label: 'Style', hp: 'keterangan', isi: (s) => (
      <div className="min-w-0">
        <p className="truncate font-medium text-foreground md:max-w-[16rem]">{s.style_name}</p>
        <p className="text-xs text-muted-foreground">{s.style_code}</p>
      </div>) },
    { kunci: 'qty', label: 'Qty', rata: 'kanan', isi: (s) => <span className="tabular-nums">{s.quantity} pcs</span> },
    { kunci: 'pic', label: 'PIC / pembuat', isi: (s) => (
      <span className="text-sm" data-testid={`sample-pic-${s.id}`}>
        {s.sample_pic || <span className="text-muted-foreground">Belum ditentukan</span>}
        {s.sample_pic && s.sample_pic_external && <span className="ml-1 text-xs text-muted-foreground">(penjahit luar)</span>}
      </span>) },
    { kunci: 'prio', label: 'Prioritas', isi: (s) => <StatusBadge status={`prio-${s.priority}`} tone={prioOf(s.priority).tone} label={prioOf(s.priority).label} /> },
    { kunci: 'due', label: 'Target selesai', isi: (s) => <span className="text-sm md:whitespace-nowrap">{tgl(s.due_date)}</span> },
    { kunci: 'status', label: 'Status', isi: (s) => (
      <div className="flex flex-col items-start gap-1">
        <StatusBadge status={s.status} tone={statusOf(s.status).tone} label={statusOf(s.status).label} />
        {aksesorisTeks(s.accessory_status) && (
          <span className="text-xs text-muted-foreground" data-testid={`sample-acc-status-${s.id}`}>
            {aksesorisTeks(s.accessory_status)}
          </span>
        )}
      </div>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (s) => <AksiBaris s={s} /> },
  ];

  const chips = [
    { key: '', label: 'Semua' },
    ...Object.entries(STATUS_CONF).map(([k, v]) => ({ key: k, label: v.label })),
  ];

  return (
    <PageLayout testId="rnd-samples-tab" title="Sample Request"
      subtitle="Permintaan sample produk per style: buat, ajukan, setujui, lalu lanjut ke tech pack atau PO maklon."
      actions={<>
        {typeof onNavigate === 'function' && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" className="max-sm:px-2.5" aria-label="Langkah berikutnya" title="Langkah berikutnya"
                data-testid="sample-onward"><span className="hidden sm:inline">Langkah berikutnya</span><ArrowRight /></Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => onNavigate('rnd-techpack')} data-testid="onward-rnd-techpack">
                <FileStack className="mr-2 h-4 w-4" />Buat tech pack dari sample disetujui
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => onNavigate('maklon-po')} data-testid="onward-maklon-po">
                <Factory className="mr-2 h-4 w-4" />Buat PO maklon berdasarkan sample
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
        <Button onClick={() => setShowForm(true)} data-testid="create-sample-btn">
          <Plus />Request sample baru
        </Button>
      </>}
      filters={<>
        <FilterChips options={chips} value={filterStatus} onChange={setFilterStatus} hideWhenEmpty={false}
          testId="sample-status-filter" ariaLabel="Status" />
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={e => setSearch(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && fetchSamples()}
            placeholder="Cari kode atau style" className="pl-8" data-testid="sample-search" />
        </div>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="sample-request" namaLembar="Sample request" baris={filtered} testId="sample-unduh"
          kolom={[
            { label: 'Kode sample', nilai: (s) => s.sample_code },
            { label: 'Kode style', nilai: (s) => s.style_code || '' },
            { label: 'Style', nilai: (s) => s.style_name || '' },
            { label: 'Qty (pcs)', nilai: (s) => Number(s.quantity || 0) },
            { label: 'PIC / pembuat', nilai: (s) => `${s.sample_pic || ''}${s.sample_pic && s.sample_pic_external ? ' (penjahit luar)' : ''}` },
            { label: 'Prioritas', nilai: (s) => prioOf(s.priority).label },
            { label: 'Target selesai', nilai: (s) => (s.due_date ? formatDateID(s.due_date) : '') },
            { label: 'Status', nilai: (s) => statusOf(s.status).label },
            { label: 'Aksesoris', nilai: (s) => aksesorisTeks(s.accessory_status).replace(/^Aksesoris /, '') },
            { label: 'Catatan', nilai: (s) => s.notes || '' },
          ]} />
        <Button variant="outline" size="icon" onClick={fetchSamples} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      footer={filtered.length > 25 && (
        <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />
      )}>
      <GlassCard className="p-0 overflow-hidden">
        {loading && samples.length === 0 ? (
          <div className="space-y-2 p-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-10" />)}</div>
        ) : (
          <TabelData kolom={kolom} baris={paged} onKlikBaris={setDetail} testId="sample-table"
            kosong={
              <EmptyState icon={FlaskConical}
                title={samples.length ? 'Tidak ada sample yang cocok' : filterStatus ? `Belum ada sample berstatus ${statusOf(filterStatus).label.toLowerCase()}` : 'Belum ada request sample'}
                description={samples.length || filterStatus ? 'Ubah saringan atau kata pencarian.' : 'Buat request sample pertama dari style yang sudah ada.'}
                action={!samples.length && !filterStatus && <Button onClick={() => setShowForm(true)}><Plus />Request sample baru</Button>} />
            } />
        )}
      </GlassCard>

      {/* Rincian satu request */}
      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} testId="sample-detail"
          judul={detail.sample_code} keterangan={`${detail.style_code || ''} — ${detail.style_name || ''}`}
          status={<StatusBadge status={detail.status} tone={statusOf(detail.status).tone} label={statusOf(detail.status).label} />}
          aksi={<AksiBaris s={detail} />}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Jumlah">{detail.quantity} pcs</BarisDetail>
            <BarisDetail label="Prioritas">{prioOf(detail.priority).label}</BarisDetail>
            <BarisDetail label="PIC / pembuat">
              {detail.sample_pic || 'Belum ditentukan'}{detail.sample_pic && detail.sample_pic_external ? ' (penjahit luar)' : ''}
            </BarisDetail>
            <BarisDetail label="Target selesai">{tgl(detail.due_date)}</BarisDetail>
            {detail.accessory_status && (
              <BarisDetail label="Aksesoris">
                {aksesorisTeks(detail.accessory_status).replace(/^Aksesoris /, '')}
                {typeof onNavigate === 'function' && (
                  <Button size="sm" variant="link" className="ml-2 px-0" onClick={() => onNavigate('rnd-accessory-requests')}
                    data-testid="sample-detail-acc-link">Lihat permintaan</Button>
                )}
              </BarisDetail>
            )}
            <BarisDetail label="Catatan">{detail.notes || '—'}</BarisDetail>
            {detail.approved_by_name && (
              <BarisDetail label="Diputuskan">{detail.approved_by_name}{detail.approved_at ? ` · ${formatDateTimeID(detail.approved_at)}` : ''}</BarisDetail>
            )}
            {detail.approval_notes && <BarisDetail label="Catatan keputusan">{detail.approval_notes}</BarisDetail>}
            {detail.created_at && (
              <BarisDetail label="Dibuat">{formatDateTimeID(detail.created_at)}{detail.created_by_name ? ` · ${detail.created_by_name}` : ''}</BarisDetail>
            )}
          </dl>
        </DetailPopup>
      )}

      {/* Form request baru */}
      <FormPopup open={showForm} onClose={() => setShowForm(false)} judul="Request sample baru"
        keterangan="Sample dibuat dari style yang sudah ada di Style & Desain." ukuran="pendek"
        onSimpan={handleCreate} labelSimpan="Buat request" menyimpan={saving} testId="sample-form">
        <Isian label="Style" wajib htmlFor="sample-style">
          <SmartNativeSelect id="sample-style" value={form.style_id} onChange={e => f('style_id', e.target.value)}
            data-testid="sample-style-select">
            <option value="">Pilih style</option>
            {styles.map(s => <option key={s.id} value={s.id}>{s.style_code} — {s.style_name}</option>)}
          </SmartNativeSelect>
        </Isian>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Jumlah (pcs)" wajib htmlFor="sample-qty">
            <Input id="sample-qty" type="number" min="1" inputMode="numeric" value={form.quantity}
              onChange={e => f('quantity', e.target.value === '' ? '' : parseInt(e.target.value, 10))}
              data-testid="sample-qty-input" />
          </Isian>
          <Isian label="Prioritas" htmlFor="sample-prio">
            <SmartNativeSelect id="sample-prio" value={form.priority} onChange={e => f('priority', e.target.value)}
              data-testid="sample-priority-select">
              <option value="low">Rendah</option>
              <option value="normal">Normal</option>
              <option value="high">Tinggi</option>
            </SmartNativeSelect>
          </Isian>
          <Isian label="PIC / pembuat sample" htmlFor="sample-pic">
            <SmartNativeSelect id="sample-pic" value={picValue} onChange={e => pickPic(e.target.value)}
              searchable={true} aria-label="PIC / pembuat sample" data-testid="sample-pic-select">
              <option value="">Belum ditentukan</option>
              <option value={PIC_EXTERNAL}>Penjahit luar — ketik nama</option>
              {picChoices.map((e) => (
                <option key={e.id} value={e.id}>{`${employeeLabel(e)}${e.sampleStaff ? ' — bagian sample' : ''}`}</option>
              ))}
            </SmartNativeSelect>
            {form.sample_pic_external && (
              <Input className="mt-1.5" value={form.sample_pic} onChange={e => f('sample_pic', e.target.value)}
                placeholder="Nama penjahit luar" data-testid="sample-pic-input" />
            )}
          </Isian>
          <Isian label="Target selesai">
            <DatePicker value={form.due_date} onChange={(v) => f('due_date', v)} placeholder="Belum ditentukan"
              testId="sample-due-date" />
          </Isian>
        </div>
        <Isian label="Catatan" htmlFor="sample-notes">
          <Textarea id="sample-notes" rows={3} value={form.notes} onChange={e => f('notes', e.target.value)}
            placeholder="Spesifikasi khusus, referensi, dll." />
        </Isian>
      </FormPopup>

      {/* Setujui (catatan opsional) */}
      <FormPopup open={!!actionModal} onClose={() => setActionModal(null)} ukuran="pendek"
        judul={`Setujui sample ${actionModal?.code || ''}`.trim()} keterangan="Catatan persetujuan boleh dikosongkan."
        onSimpan={handleApprove} labelSimpan="Setujui" testId="sample-approve">
        <Isian label="Catatan persetujuan" htmlFor="sample-approve-notes">
          <Textarea id="sample-approve-notes" rows={3} value={actionModal?.notes || ''}
            onChange={e => setActionModal(a => ({ ...a, notes: e.target.value }))}
            placeholder="Catatan opsional" data-testid="action-notes-input" />
        </Isian>
      </FormPopup>

      {/* ── Session 27 — GAP-R3 Request aksesoris ──────────────────── */}
      <FormPopup open={!!accReqModal} onClose={() => setAccReqModal(null)} ukuran="panjang"
        judul={`Request aksesoris — ${accReqModal?.sample?.sample_code || ''}`}
        keterangan={accReqModal ? `${accReqModal.sample.style_code} — ${accReqModal.sample.style_name} · sample ${accReqModal.sample.quantity} pcs` : ''}
        onSimpan={handleSubmitAccReq} labelSimpan="Kirim request" menyimpan={!!accReqModal?.submitting}
        testId="acc-req-form">
        {accReqModal && (
          <>
            <Isian label="Daftar aksesoris"
              petunjuk="Pilih dari master aksesoris. Bila barangnya belum ada di master, pilih 'Belum ada di master' lalu ketik namanya.">
              <div className="space-y-3">
                {accReqModal.items.map((it, idx) => {
                  const m = it.material_id ? masterById.get(it.material_id) : null;
                  const stok = m ? Number(m.stock_qty || 0) : null;
                  const kurang = m && Number(it.qty) > stok;
                  return (
                    <div key={idx} className="space-y-1.5" data-testid={`acc-req-row-${idx}`}>
                      <div className="grid grid-cols-2 gap-2 sm:grid-cols-12 sm:items-start">
                        <div className="col-span-2 sm:col-span-6">
                          <SmartNativeSelect value={it.manual ? AKS_MANUAL : it.material_id} searchable={true}
                            onChange={e => pickAccMaster(idx, e.target.value)} aria-label="Aksesoris"
                            data-testid={`acc-req-master-${idx}`}>
                            <option value="">{accMasters === null ? 'Memuat master aksesoris…' : 'Pilih aksesoris'}</option>
                            <option value={AKS_MANUAL}>Belum ada di master — ketik manual</option>
                            {(accMasters || []).map((a) => (
                              <option key={a.id} value={a.id}>{`${a.code} · ${a.name} (stok ${angka(a.stock_qty)} ${a.unit || 'pcs'})`}</option>
                            ))}
                          </SmartNativeSelect>
                        </div>
                        <Input className="sm:col-span-2" type="number" min="0" step="0.1" placeholder="Jumlah" aria-label="Jumlah"
                          value={it.qty} onChange={e => updateAccReqItem(idx, 'qty', e.target.value)}
                          data-testid={`acc-req-qty-${idx}`} />
                        {/* Satuan: dari master bila tertaut (stok dipotong dalam satuan master); ketik manual memakai
                            daftar satuan RnD yang sama dengan Costing/Tech Pack (2026-11-07). */}
                        <div className="sm:col-span-3">
                          {it.manual ? (
                            <RnDUnitSelect value={it.unit} onChange={e => updateAccReqItem(idx, 'unit', e.target.value)}
                              testId={`acc-req-unit-${idx}`} />
                          ) : (
                            <p className="flex h-9 items-center text-sm text-muted-foreground" data-testid={`acc-req-unit-${idx}`}>
                              {m ? (m.unit || 'pcs') : 'Satuan dari master'}
                            </p>
                          )}
                        </div>
                        <Button type="button" variant="outline" size="icon" className="sm:col-span-1"
                          onClick={() => removeAccReqItemRow(idx)} disabled={accReqModal.items.length <= 1}
                          aria-label="Hapus baris" title="Hapus baris" data-testid={`acc-req-remove-row-${idx}`}>
                          <Trash2 />
                        </Button>
                      </div>
                      {it.manual && (
                        <div className="grid grid-cols-2 gap-2 sm:grid-cols-12 sm:items-center">
                          <Input className="sm:col-span-3" placeholder="Kode (opsional)" aria-label="Kode aksesoris"
                            value={it.material_code} onChange={e => updateAccReqItem(idx, 'material_code', e.target.value)} />
                          <Input className="sm:col-span-6" placeholder="Nama aksesoris" aria-label="Nama aksesoris"
                            value={it.material_name} onChange={e => updateAccReqItem(idx, 'material_name', e.target.value)}
                            data-testid={`acc-req-name-${idx}`} />
                          <div className="col-span-2 sm:col-span-3">
                            <StatusBadge status="belum-tertaut" tone="warning" label="Belum tertaut"
                              testId={`acc-req-unlinked-${idx}`} />
                          </div>
                        </div>
                      )}
                      {m && (
                        <p className={`text-xs ${kurang ? 'text-[hsl(var(--warning-text))]' : 'text-muted-foreground'}`}
                          data-testid={`acc-req-stock-${idx}`}>
                          Stok gudang {angka(stok)} {m.unit || 'pcs'}
                          {kurang ? ' — kurang dari jumlah diminta; tim aksesoris akan menindaklanjuti (bisa lewat pembelian).' : '.'}
                        </p>
                      )}
                    </div>
                  );
                })}
                <Button type="button" variant="outline" size="sm" onClick={addAccReqItemRow} data-testid="acc-req-add-row">
                  <Plus />Tambah baris
                </Button>
              </div>
            </Isian>
            <div className="grid gap-4 sm:grid-cols-2">
              <Isian label="Butuh sebelum">
                <DatePicker value={accReqModal.needed_by_date} placeholder="Tidak ditentukan"
                  onChange={(v) => setAccReqModal(p => ({ ...p, needed_by_date: v }))} testId="acc-req-needed-by-date" />
              </Isian>
              <label className="flex items-center gap-2 text-sm sm:mt-7" htmlFor="acc-req-urgent" data-testid="acc-req-urgent-label">
                <Checkbox id="acc-req-urgent" checked={!!accReqModal.urgent}
                  onCheckedChange={(v) => setAccReqModal(p => ({ ...p, urgent: !!v }))} data-testid="acc-req-urgent-checkbox" />
                Tandai mendesak
              </label>
            </div>
            <Isian label="Catatan" htmlFor="acc-req-notes">
              <Textarea id="acc-req-notes" rows={3} placeholder="Spesifikasi warna, ukuran khusus, dll."
                value={accReqModal.notes} onChange={e => setAccReqModal(p => ({ ...p, notes: e.target.value }))}
                data-testid="acc-req-notes" />
            </Isian>
            <DocNumberField policy={accNumPolicy} value={accReqCode} onChange={setAccReqCode}
              testId="acc-req-docnum" label="Nomor permintaan aksesoris" />
          </>
        )}
      </FormPopup>
    </PageLayout>
  );
}

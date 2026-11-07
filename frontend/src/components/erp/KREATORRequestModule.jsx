/**
 * Permintaan kreator (Portal Toko › KOL & Kreator, juga Portal RnD › rnd-kreator-requests).
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout (judul disembunyikan di hub), penyaring satu baris, 4 StatTile, tabel +
 * unduh, rincian = DetailPopup, form & aksi (setujui/tolak/kirim) = FormPopup (dulu Modal buatan sendiri),
 * hapus = confirmDialog (dulu ConfirmDialog buatan sendiri), tenggat = DatePicker. Props & perilaku tetap
 * (dipakai dua portal). Panggilan API & isi yang dikirim tidak berubah.
 */
import { useState, useEffect, useMemo } from 'react';
import { Users, Plus, Trash2, Search, CheckCircle2, XCircle, Send, Truck, Clock, Radio, Video, Sparkles, Pencil, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import DatePicker from '@/components/ui/date-picker';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { toast } from '../ui/sonner';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';
import DocNumberField, { useDocNumberPolicy, docNumberPayload } from './docnum/DocNumberField';
import { MarketingAccountSelect, MarketingCreatorSelect, MasterChipsSelect, useMasterList } from './marketing/pickers/MarketingPickers';

const API = process.env.REACT_APP_BACKEND_URL || '';

const STATUS_CONF = {
  draft:            { label: 'Draf',          tone: 'muted', cls: 'bg-muted text-muted-foreground border-border ',     Icon: Clock },
  submitted:        { label: 'Menunggu RnD', tone: 'warning',    cls: 'bg-[hsl(var(--warning)/0.12)] text-[hsl(var(--warning-text))] border-[hsl(var(--warning)/0.35)] ', Icon: Send },
  approved_by_rnd:  { label: 'Disetujui RnD', tone: 'info', cls: 'bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))] border-[hsl(var(--primary)/0.35)] ',       Icon: CheckCircle2 },
  sample_ready:     { label: 'Sample siap',   tone: 'info',   cls: 'bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))] border-[hsl(var(--primary)/0.35)] ', Icon: Sparkles },
  delivered:        { label: 'Dikirim',       tone: 'success',       cls: 'bg-[hsl(var(--success)/0.12)] text-[hsl(var(--success-text))] border-[hsl(var(--success)/0.35)] ', Icon: Truck },
  rejected:         { label: 'Ditolak',       tone: 'danger',       cls: 'bg-[hsl(var(--destructive)/0.12)] text-[hsl(var(--danger-text))] border-[hsl(var(--destructive)/0.35)] ',       Icon: XCircle },
  cancelled:        { label: 'Batal',         tone: 'muted',         cls: 'bg-muted text-muted-foreground border-border ',     Icon: XCircle },
};

const KREATOR_TYPE_CONF = {
  live_streaming: { label: 'Live streaming', tone: 'primary', cls: 'bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))] border-[hsl(var(--primary)/0.35)] ', Icon: Radio },
  tiktok_video:   { label: 'Video TikTok',   tone: 'success',   cls: 'bg-[hsl(var(--success)/0.12)] text-[hsl(var(--success-text))] border-[hsl(var(--success)/0.35)] ', Icon: Video },
};

const DELIVERY_LABEL = { courier: 'Kurir (JNE/J&T/SiCepat)', pickup: 'Diambil langsung', mail: 'Pos' };

const emptyForm = {
  account_id: '',
  kreator_id: '',
  model_id: '',
  kreator_type: 'live_streaming',
  product_concept: '',
  reference_links: [],
  target_segment: '',
  sample_qty: 1,
  sample_colors: [],
  sample_sizes: [],
  deadline: '',
  notes: '',
};

export default function KREATORRequestModule({ token, currentUser, user, moduleId }) {
  const h = { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` };
  // RC-IA T-3: scope per portal (lightweight). Derived from module-id:
  //   • marketing-kreator-requests = Marketing (buat & lacak request KREATOR)
  //   • rnd-kreator-requests       = RnD (antrian review & approve; default filter 'submitted')
  const scope = moduleId === 'rnd-kreator-requests' ? 'rnd' : 'marketing';
  const isRndScope = scope === 'rnd';
  const actor = currentUser || user;
  const roleIsRnd = (actor?.role || '').toLowerCase().includes('rnd')
    || ['superadmin', 'admin', 'manager', 'owner'].includes((actor?.role || '').toLowerCase());
  // Aksi approve/tolak RnD tampil pada scope RnD (portal sudah role-guarded) atau untuk role RnD-capable.
  const isRnd = isRndScope || roleIsRnd;

  const [requests, setRequests] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(false);
  const [filterStatus, setFilterStatus] = useState(isRndScope ? 'submitted' : ''); // RnD: fokus antrian "Tunggu RnD"
  const [filterType, setFilterType] = useState('');
  const [search, setSearch] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ ...emptyForm });
  const [editing, setEditing] = useState(null);
  const [detail, setDetail] = useState(null);
  const [actionModal, setActionModal] = useState(null); // { id, type, notes }
  // SESI #27 — kebijakan penomoran Permintaan Kreator (Otomatis/Manual) milik owner.
  const numPolicy = useDocNumberPolicy('dewi_kreator_requests.request_code',
                                       localStorage.getItem('erp_token'));
  const [reqCode, setReqCode] = useState('');
  const [delId, setDelId] = useState(null);
  const [galatForm, setGalatForm] = useState('');
  const [galatAksi, setGalatAksi] = useState('');

  const f = (k, v) => setForm(p => ({ ...p, [k]: v }));
  // 2026-11-07 (Tahap 6, MK2): varian aktif memberi WARNA model acuan (tampil duluan di pilihan warna).
  // Varian juga melengkapi daftar model: Master Model (/rahaza/models, berisi HPP) tertutup untuk peran
  // marketing (pic_toko/marketing_kol), sehingga dulu pilihan Model Referensi kosong bagi mereka.
  const masterModels = useMasterList('/api/rahaza/models', token);
  const variants = useMasterList('/api/rahaza/variants', token);
  const models = useMemo(() => {
    const byId = new Map(masterModels.map(m => [m.id, { id: m.id, code: m.code, name: m.name }]));
    variants.forEach(v => {
      if (v.model_id && !byId.has(v.model_id)) byId.set(v.model_id, { id: v.model_id, code: v.model_code, name: v.model_name });
    });
    return [...byId.values()].sort((a, b) => String(a.code || '').localeCompare(String(b.code || '')));
  }, [masterModels, variants]);
  const modelColors = useMemo(() => {
    if (!form.model_id) return [];
    const seen = new Map();
    variants.filter(v => v.model_id === form.model_id && (v.color_id || v.color_name)).forEach(v => {
      const k = v.color_id || v.color_name;
      if (!seen.has(k)) seen.set(k, { id: v.color_id, name: v.color_name });
    });
    return [...seen.values()];
  }, [variants, form.model_id]);

  const fetchRequests = async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      if (filterStatus) qs.set('status', filterStatus);
      if (filterType) qs.set('kreator_type', filterType);
      if (search) qs.set('search', search);
      const res = await fetch(`${API}/api/dewi/kreator-requests?${qs}`, { headers: h });
      setRequests(await res.json());
    } catch { toast.error('Gagal memuat data'); }
    finally { setLoading(false); }
  };

  const fetchStats = async () => {
    try {
      const res = await fetch(`${API}/api/dewi/kreator-requests/stats/summary`, { headers: h });
      if (res.ok) setStats(await res.json());
    } catch { /* ignore */ }
  };

  useEffect(() => { fetchRequests(); }, [filterStatus, filterType]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { fetchStats(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const openNew = () => {
    setForm({ ...emptyForm });
    setEditing(null);
    setGalatForm('');
    setShowForm(true);
  };

  const openEdit = (r) => {
    setForm({
      account_id: r.account_id || '',
      kreator_id: r.kreator_id || '',
      model_id: r.model_id || '',
      kreator_type: r.kreator_type || 'live_streaming',
      product_concept: r.product_concept || '',
      reference_links: r.reference_links || [],
      target_segment: r.target_segment || '',
      sample_qty: r.sample_qty || 1,
      sample_colors: r.sample_colors || [],
      sample_sizes: r.sample_sizes || [],
      deadline: r.deadline || '',
      notes: r.notes || '',
    });
    setEditing(r.id);
    setGalatForm('');
    setShowForm(true);
  };

  const handleSave = async () => {
    setGalatForm('');
    if (!form.account_id) return setGalatForm('Pilih toko dulu.');
    if (!form.kreator_id) return setGalatForm('Pilih kreator dari master KOL.');
    if (!form.product_concept?.trim()) return setGalatForm('Konsep produk wajib diisi.');
    const payload = { ...form, sample_qty: Number(form.sample_qty) || 1 };
    try {
      const url = editing ? `${API}/api/dewi/kreator-requests/${editing}` : `${API}/api/dewi/kreator-requests`;
      const method = editing ? 'PUT' : 'POST';
      const body = editing ? payload
        : { ...payload, ...docNumberPayload(numPolicy, 'request_code', reqCode) };
      const res = await fetch(url, { method, headers: h, body: JSON.stringify(body) });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Gagal menyimpan');
      }
      toast.success(editing ? 'Permintaan disimpan.' : 'Permintaan kreator dibuat.');
      setShowForm(false);
      fetchRequests();
      fetchStats();
    } catch (e) {
      setGalatForm(e.message || 'Gagal menyimpan');
    }
  };

  const handleSubmit = async (id) => {
    try {
      const res = await fetch(`${API}/api/dewi/kreator-requests/${id}/submit`, { method: 'POST', headers: h });
      if (!res.ok) throw new Error();
      toast.success('Permintaan dikirim ke RnD untuk disetujui.');
      fetchRequests();
      fetchStats();
    } catch { toast.error('Gagal mengirim permintaan'); }
  };

  const handleApprove = async () => {
    if (!actionModal) return;
    try {
      const res = await fetch(`${API}/api/dewi/kreator-requests/${actionModal.id}/approve-by-rnd`, {
        method: 'POST', headers: h, body: JSON.stringify({ notes: actionModal.notes || '' }),
      });
      if (!res.ok) throw new Error();
      toast.success('Permintaan disetujui RnD.');
      setActionModal(null);
      fetchRequests();
      fetchStats();
    } catch { setGalatAksi('Gagal menyetujui.'); }
  };

  const handleReject = async () => {
    if (!actionModal) return;
    if (!actionModal.notes?.trim()) return setGalatAksi('Alasan penolakan wajib diisi.');
    try {
      const res = await fetch(`${API}/api/dewi/kreator-requests/${actionModal.id}/reject`, {
        method: 'POST', headers: h, body: JSON.stringify({ reason: actionModal.notes }),
      });
      if (!res.ok) throw new Error();
      toast.success('Permintaan ditolak.');
      setActionModal(null);
      fetchRequests();
      fetchStats();
    } catch { setGalatAksi('Gagal menolak.'); }
  };

  const handleMarkSampleReady = async (id) => {
    try {
      const res = await fetch(`${API}/api/dewi/kreator-requests/${id}/mark-sample-ready`, { method: 'POST', headers: h });
      if (!res.ok) throw new Error();
      toast.success('Sample ditandai siap.');
      fetchRequests();
      fetchStats();
    } catch { toast.error('Gagal mengubah status'); }
  };

  const handleMarkDelivered = async () => {
    if (!actionModal) return;
    try {
      const res = await fetch(`${API}/api/dewi/kreator-requests/${actionModal.id}/mark-delivered`, {
        method: 'POST', headers: h,
        body: JSON.stringify({
          delivery_method: actionModal.delivery_method || '',
          tracking_number: actionModal.tracking_number || '',
        }),
      });
      if (!res.ok) throw new Error();
      toast.success('Sample ditandai dikirim.');
      setActionModal(null);
      fetchRequests();
      fetchStats();
    } catch { setGalatAksi('Gagal mencatat pengiriman.'); }
  };

  const handleDelete = async () => {
    try {
      const res = await fetch(`${API}/api/dewi/kreator-requests/${delId}`, { method: 'DELETE', headers: h });
      if (!res.ok) throw new Error();
      toast.success('Permintaan dihapus.');
      setDelId(null);
      fetchRequests();
      fetchStats();
    } catch { toast.error('Gagal menghapus'); }
  };

  useEffect(() => {
    if (!delId) return;
    (async () => {
      const ok = await confirmDialog({ title: 'Hapus permintaan?', body: 'Permintaan kreator dihapus permanen.', confirmLabel: 'Hapus', danger: true });
      if (ok) handleDelete(); else setDelId(null);
    })();
  }, [delId]); // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = useMemo(() => requests.filter(r => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (r.request_code || '').toLowerCase().includes(q)
      || (r.kreator_name || '').toLowerCase().includes(q)
      || (r.product_concept || '').toLowerCase().includes(q);
  }), [requests, search]);

  const formatDate = (iso) => {
    if (!iso) return '—';
    try { return new Date(iso).toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' }); }
    catch { return iso; }
  };

  const { page, setPage, totalPages, total, paged } = useClientPagination(filtered, 10);
  const tc = (r) => KREATOR_TYPE_CONF[r.kreator_type] || KREATOR_TYPE_CONF.live_streaming;
  const sc = (r) => STATUS_CONF[r.status] || STATUS_CONF.draft;
  const aksiBaris = (r) => (
    <div className="flex flex-wrap justify-end gap-1">
      {r.status === 'draft' && <>
        <Button size="sm" variant="outline" onClick={() => handleSubmit(r.id)} data-testid={`kreator-req-submit-${r.id}`}><Send />Kirim ke RnD</Button>
        <Button size="icon-sm" variant="ghost" onClick={() => openEdit(r)} data-testid={`kreator-req-edit-${r.id}`} title="Ubah permintaan" aria-label="Ubah permintaan"><Pencil /></Button>
      </>}
      {r.status === 'submitted' && isRnd && <>
        <Button size="sm" variant="success" onClick={() => { setGalatAksi(''); setActionModal({ id: r.id, type: 'approve', notes: '' }); }} data-testid={`kreator-req-approve-${r.id}`}><CheckCircle2 />Setujui</Button>
        <Button size="sm" variant="destructive" onClick={() => { setGalatAksi(''); setActionModal({ id: r.id, type: 'reject', notes: '' }); }} data-testid={`kreator-req-reject-${r.id}`}><XCircle />Tolak</Button>
      </>}
      {r.status === 'approved_by_rnd' && (
        <Button size="sm" variant="outline" onClick={() => handleMarkSampleReady(r.id)} data-testid={`kreator-req-sample-ready-${r.id}`}><Sparkles />Sample siap</Button>
      )}
      {r.status === 'sample_ready' && (
        <Button size="sm" variant="outline" onClick={() => { setGalatAksi(''); setActionModal({ id: r.id, type: 'deliver', notes: '', delivery_method: '', tracking_number: '' }); }}
          data-testid={`kreator-req-deliver-${r.id}`}><Truck />Kirim sample</Button>
      )}
    </div>
  );
  const kolom = [
    { kunci: 'kode', label: 'Kode', hp: 'keterangan', isi: (r) => <span className="tabular-nums font-medium">{r.request_code}</span> },
    { kunci: 'kreator', label: 'Kreator', hp: 'judul', isi: (r) => (
      <span><span className="font-medium">{r.kreator_name}</span>
        {r.kreator_handle && <span className="block text-xs text-muted-foreground">@{String(r.kreator_handle).replace(/^@/, '')}</span>}
        {r.account_name && <span className="block text-xs text-muted-foreground" data-testid={`kreator-req-toko-${r.id}`}>Toko: {r.account_name}</span>}</span>) },
    { kunci: 'tipe', label: 'Tipe', isi: (r) => <StatusBadge status={r.kreator_type} label={tc(r).label} tone={tc(r).tone} /> },
    { kunci: 'konsep', label: 'Konsep produk', isi: (r) => <p className="truncate md:max-w-[18rem]" title={r.product_concept}>{r.product_concept}</p> },
    { kunci: 'qty', label: 'Qty', rata: 'kanan', isi: (r) => (
      <span className="tabular-nums">{r.sample_qty} pcs{(r.sample_colors || []).length > 0 && <span className="block text-xs text-muted-foreground">{r.sample_colors.join(', ')}</span>}</span>) },
    { kunci: 'status', label: 'Status', isi: (r) => <StatusBadge status={r.status} label={sc(r).label} tone={sc(r).tone} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: aksiBaris },
  ];
  const s = stats || {};

  return (
    <PageLayout testId="kreator-request-module" title={isRndScope ? 'Persetujuan permintaan kreator' : 'Permintaan kreator'}
      subtitle={isRndScope
        ? 'Antrian tinjauan permintaan produk dari kreator: setujui/tolak lalu tandai sample siap.'
        : 'Permintaan produk dari kreator (live streaming & video TikTok) — koordinasi Marketing ↔ RnD.'}
      actions={!isRndScope && <Button onClick={openNew} data-testid="kreator-req-add-btn"><Plus />Permintaan baru</Button>}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={e => setSearch(e.target.value)} onKeyDown={e => e.key === 'Enter' && fetchRequests()}
            placeholder="Cari kode, kreator, konsep" className="pl-8" data-testid="kreator-req-search-input" />
        </div>
        <SmartNativeSelect value={filterType} onChange={e => setFilterType(e.target.value)} className="w-40" searchable={false}
          data-testid="kreator-req-filter-type">
          <option value="">Semua tipe</option>
          <option value="live_streaming">Live streaming</option>
          <option value="tiktok_video">Video TikTok</option>
        </SmartNativeSelect>
        <SmartNativeSelect value={filterStatus} onChange={e => setFilterStatus(e.target.value)} className="w-44" searchable={false}
          data-testid="kreator-req-filter-status">
          <option value="">Semua status</option>
          {Object.entries(STATUS_CONF).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="permintaan-kreator" namaLembar="Permintaan" baris={filtered} testId="kreator-req-unduh"
          kolom={[
            { label: 'Kode', nilai: (r) => r.request_code || '' }, { label: 'Kreator', nilai: (r) => r.kreator_name || '' },
            { label: 'Toko', nilai: (r) => r.account_name || '' }, { label: 'Tipe', nilai: (r) => tc(r).label },
            { label: 'Konsep produk', nilai: (r) => r.product_concept || '' }, { label: 'Qty', nilai: (r) => Number(r.sample_qty) || 0 },
            { label: 'Warna', nilai: (r) => (r.sample_colors || []).join(', ') }, { label: 'Ukuran', nilai: (r) => (r.sample_sizes || []).join(', ') },
            { label: 'Tenggat', nilai: (r) => (r.deadline ? formatDate(r.deadline) : '') }, { label: 'Status', nilai: (r) => sc(r).label },
          ]} />
        <Button variant="outline" size="icon" onClick={() => { fetchRequests(); fetchStats(); }} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={(s.total || 0) > 0 && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="kreator-req-stats">
          <StatTile label="Live streaming" value={s.live_streaming || 0} sub={`dari ${s.total} permintaan`}
            hint="Semua permintaan; tidak ikut penyaring." testId="stats-live-streaming" />
          <StatTile label="Video TikTok" value={s.tiktok_video || 0} testId="stats-tiktok-video" hint="Semua permintaan; tidak ikut penyaring." />
          <StatTile label="Menunggu RnD" value={s.pending_rnd_approval || 0} accent="warning" hint="Sudah dikirim, belum disetujui RnD." />
          <StatTile label="Siap dikirim" value={s.ready_to_deliver || 0} accent="primary" hint="Sample siap, belum dikirim ke kreator." />
        </div>
      )}
      footer={filtered.length > 10 && <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />}>
      {loading && requests.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat permintaan…</p>
      ) : (
        <TabelData kolom={kolom} baris={paged} onKlikBaris={setDetail} testId="kreator-req-table"
          kosong={<EmptyState icon={Users}
            title={isRndScope ? 'Tidak ada permintaan yang menunggu persetujuan' : 'Belum ada permintaan kreator'}
            description={isRndScope ? 'Ubah penyaring status untuk melihat permintaan lain.' : 'Buat permintaan produk untuk kreator.'}
            action={!isRndScope && <Button variant="outline" onClick={openNew}><Plus />Buat permintaan pertama</Button>} />} />
      )}

      {/* Form buat/ubah */}
      <FormPopup open={showForm} onClose={() => setShowForm(false)} ukuran="panjang" onSimpan={handleSave} galat={galatForm}
        judul={editing ? 'Ubah permintaan kreator' : 'Permintaan kreator baru'} labelSimpan={editing ? 'Simpan' : 'Buat permintaan'}
        testId="kreator-form">
        <div className="grid gap-4 sm:grid-cols-2">
          <MarketingAccountSelect token={token} value={form.account_id} label="Toko"
            onChange={(v) => setForm(p => ({ ...p, account_id: v, kreator_id: '' }))}
            testId="kreator-form-account" />
          <MarketingCreatorSelect token={token} accountId={form.account_id} value={form.kreator_id}
            label="Kreator / KOL" onChange={(v) => f('kreator_id', v)} testId="kreator-form-creator" />
        </div>
        <Isian label="Tipe kreator" wajib petunjuk="Live streaming: 1 pcs per warna terlaris · Video TikTok: 1 pcs warna acak.">
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(KREATOR_TYPE_CONF).map(([k, v]) => {
              const Icon = v.Icon;
              return (
                <Button key={k} type="button" size="sm" variant={form.kreator_type === k ? 'default' : 'outline'} aria-pressed={form.kreator_type === k}
                  onClick={() => f('kreator_type', k)} data-testid={`kreator-form-type-${k}`}><Icon />{v.label}</Button>
              );
            })}
          </div>
        </Isian>
        <Isian label="Konsep produk" wajib htmlFor="kr-concept">
          <Textarea id="kr-concept" value={form.product_concept} rows={4} onChange={e => f('product_concept', e.target.value)}
            placeholder="Deskripsi produk yang diminta kreator" data-testid="kreator-form-concept" />
        </Isian>
        <div className="grid gap-4 sm:grid-cols-3">
          <Isian label="Qty sample" htmlFor="kr-qty">
            <Input id="kr-qty" type="number" min="1" value={form.sample_qty} onChange={e => f('sample_qty', e.target.value)} data-testid="kreator-form-qty" />
          </Isian>
          <Isian label="Model referensi" petunjuk="Opsional." htmlFor="kr-model" className="sm:col-span-2">
            <SmartNativeSelect id="kr-model" value={form.model_id} onChange={e => f('model_id', e.target.value)} data-testid="kreator-form-model">
              <option value="">Konsep baru / tanpa model</option>
              {models.map(m => <option key={m.id} value={m.id}>{m.code} · {m.name}</option>)}
            </SmartNativeSelect>
          </Isian>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Warna (master warna)">
            <MasterChipsSelect token={token} path="/api/rahaza/colors" value={form.sample_colors}
              onChange={(v) => f('sample_colors', v)} testId="kreator-form-colors"
              priority={modelColors} priorityLabel="Warna model ini" otherLabel="Warna lain" />
          </Isian>
          <Isian label="Ukuran (master ukuran)">
            <MasterChipsSelect token={token} path="/api/rahaza/sizes" value={form.sample_sizes}
              onChange={(v) => f('sample_sizes', v)} testId="kreator-form-sizes" />
          </Isian>
          <Isian label="Target segmen" htmlFor="kr-seg">
            <Input id="kr-seg" value={form.target_segment} onChange={e => f('target_segment', e.target.value)} placeholder="Mahasiswa, ibu-ibu, dll." />
          </Isian>
          <Isian label="Tenggat">
            <DatePicker value={form.deadline || ''} onChange={(v) => f('deadline', v)} testId="kreator-form-deadline" />
          </Isian>
        </div>
        <Isian label="Catatan" htmlFor="kr-notes">
          <Textarea id="kr-notes" value={form.notes} rows={2} onChange={e => f('notes', e.target.value)} placeholder="Catatan tambahan untuk RnD" />
        </Isian>
        {!editing && (
          <DocNumberField policy={numPolicy} value={reqCode} onChange={setReqCode} testId="kreator-docnum" label="Nomor permintaan kreator" />
        )}
      </FormPopup>

      {/* Rincian */}
      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} judul={`Permintaan ${detail.request_code}`} testId="kreator-req-detail"
          status={<><StatusBadge status={detail.status} label={sc(detail).label} tone={sc(detail).tone} />
            <StatusBadge status={detail.kreator_type} label={tc(detail).label} tone={tc(detail).tone} /></>}
          aksi={<>
            {aksiBaris(detail)}
            {(detail.status === 'draft' || detail.status === 'rejected' || detail.status === 'cancelled') && (
              <Button size="sm" variant="destructive" onClick={() => { setDelId(detail.id); setDetail(null); }} data-testid={`kreator-req-delete-${detail.id}`}><Trash2 />Hapus</Button>
            )}
          </>}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Kreator">{detail.kreator_name}{detail.kreator_handle ? ` (@${String(detail.kreator_handle).replace(/^@/, '')})` : ''}</BarisDetail>
            {detail.account_name && <BarisDetail label="Toko">{detail.account_name}</BarisDetail>}
            {detail.model_code && <BarisDetail label="Model">{detail.model_code} · {detail.model_name}</BarisDetail>}
            <BarisDetail label="Qty sample">{detail.sample_qty} pcs</BarisDetail>
            <BarisDetail label="Warna / ukuran">{(detail.sample_colors || []).join(', ') || '—'} · {(detail.sample_sizes || []).join(', ') || '—'}</BarisDetail>
            <BarisDetail label="Konsep produk"><span className="whitespace-pre-wrap">{detail.product_concept}</span></BarisDetail>
            {detail.target_segment && <BarisDetail label="Target segmen">{detail.target_segment}</BarisDetail>}
            {detail.deadline && <BarisDetail label="Tenggat">{formatDate(detail.deadline)}</BarisDetail>}
            {detail.style_code && <BarisDetail label="Style tertaut">{detail.style_code} — {detail.style_name}</BarisDetail>}
            {detail.notes && <BarisDetail label="Catatan">{detail.notes}</BarisDetail>}
            {detail.approved_by && <BarisDetail label="Disetujui">{detail.approved_by} · {formatDate(detail.approved_at)}</BarisDetail>}
            {detail.delivered_by && (
              <BarisDetail label="Dikirim">{detail.delivered_by} · {formatDate(detail.delivered_at)}
                {detail.delivery_method && ` · ${DELIVERY_LABEL[detail.delivery_method] || detail.delivery_method}`}
                {detail.tracking_number && ` · resi ${detail.tracking_number}`}</BarisDetail>
            )}
          </dl>
          {detail.rejection_reason && <Notice tone="danger" title="Alasan penolakan">{detail.rejection_reason}</Notice>}
        </DetailPopup>
      )}

      {/* Aksi: setujui / tolak / catat kirim */}
      {actionModal && (
        <FormPopup open onClose={() => setActionModal(null)} ukuran="pendek" galat={galatAksi} testId="kreator-action"
          judul={actionModal.type === 'approve' ? 'Setujui permintaan (RnD)' : actionModal.type === 'reject' ? 'Tolak permintaan' : 'Catat pengiriman sample'}
          labelSimpan={actionModal.type === 'approve' ? 'Setujui' : actionModal.type === 'reject' ? 'Tolak' : 'Catat kirim'}
          onSimpan={actionModal.type === 'approve' ? handleApprove : actionModal.type === 'reject' ? handleReject : handleMarkDelivered}>
          {actionModal.type === 'deliver' ? (
            <>
              <Isian label="Metode pengiriman" htmlFor="kr-dlv">
                <SmartNativeSelect id="kr-dlv" value={actionModal.delivery_method || ''} searchable={false}
                  onChange={e => setActionModal(p => ({ ...p, delivery_method: e.target.value }))} data-testid="kreator-deliver-method">
                  <option value="">Pilih metode</option>
                  {Object.entries(DELIVERY_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </SmartNativeSelect>
              </Isian>
              <Isian label="Nomor resi" petunjuk="Opsional." htmlFor="kr-trk">
                <Input id="kr-trk" value={actionModal.tracking_number || ''} placeholder="JNE12345…"
                  onChange={e => setActionModal(p => ({ ...p, tracking_number: e.target.value }))} data-testid="kreator-deliver-tracking" />
              </Isian>
            </>
          ) : (
            <Isian label={actionModal.type === 'approve' ? 'Catatan persetujuan' : 'Alasan penolakan'} wajib={actionModal.type === 'reject'}
              petunjuk={actionModal.type === 'approve' ? 'Opsional.' : undefined} htmlFor="kr-act-notes">
              <Textarea id="kr-act-notes" value={actionModal.notes || ''} rows={4}
                onChange={e => setActionModal(p => ({ ...p, notes: e.target.value }))}
                placeholder={actionModal.type === 'reject' ? 'Alasan penolakan' : 'Catatan'} data-testid="kreator-action-notes" />
            </Isian>
          )}
        </FormPopup>
      )}
    </PageLayout>
  );
}

/**
 * AccessoryRequestInbox — Portal Aksesoris › Inbox persetujuan (juga Portal R&D › Request Aksesoris, mode pantau).
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout · penyaring satu baris · daftar = tabel (kartu ringkas di HP) yang
 * bisa diunduh · klik baris = rincian (popup) · Siapkan / Tandai kirim = form popup · Tolak = konfirmasi dengan
 * alasan (tombol merah) · Hapus = konfirmasi. Alur, isian, dan panggilan server tidak berubah.
 *
 * RC-IA T-2: RnD (rnd-accessory-requests) = PANTAU sampel; Gudang/Aksesoris = inbox penuh.
 *
 * 2026-11-10 (keputusan owner): R&D bisa MEMBATALKAN permintaannya selama belum diserahkan (alasan wajib,
 * tim aksesoris dikabari); kartu ringkasan R&D hanya menghitung sampel R&D; baris yang diketik manual
 * ditandai "Belum tertaut"; stok kurang saat Tandai kirim → tawaran "Buat draf pembelian" berisi kekurangannya
 * (draf Request Pembelian Aksesoris, tetap diajukan lewat menu Pembelian).
 */
import { useState, useEffect, useMemo } from 'react';
import { AlertTriangle, Ban, CheckCircle2, Inbox, Package, RefreshCw, Search, ShoppingCart, Trash2, Truck, XCircle } from 'lucide-react';
import { toast } from '../ui/sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL || '';

const STATUS_CONF = {
  draft:     { label: 'Draf',      tone: 'muted' },
  submitted: { label: 'Menunggu',  tone: 'warning' },
  allocated: { label: 'Disiapkan', tone: 'info' },
  delivered: { label: 'Terkirim',  tone: 'success' },
  rejected:  { label: 'Ditolak',   tone: 'danger' },
  cancelled: { label: 'Batal',     tone: 'muted' },
};

// P3 TD-009: jenis permintaan (request_type) dalam bahasa staf
const TYPE_CONF = {
  rnd_sample:         { label: 'Sampel R&D' },
  internal_issuance:  { label: 'Pemakaian divisi' },
  vendor_additional:  { label: 'Tambahan vendor' },
  vendor_replacement: { label: 'Pengganti vendor' },
};
const typeLabel = (t) => (TYPE_CONF[t] || TYPE_CONF.rnd_sample).label;
const statusConf = (s) => STATUS_CONF[s] || STATUS_CONF.draft;
// Belum diserahkan → peminta (R&D) masih bisa membatalkan.
const BISA_BATAL = ['draft', 'submitted', 'allocated'];
const angka = (v) => Number(v || 0).toLocaleString('id-ID', { maximumFractionDigits: 2 });

const formatDate = (iso) => {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' }); }
  catch { return iso; }
};

/** Konteks permintaan per jenis: divisi/tujuan · PO/vendor · style. */
function konteks(r) {
  if (r.request_type === 'internal_issuance') return { utama: r.divisi || '—', kedua: r.purpose || '' };
  if (r.request_type === 'vendor_additional' || r.request_type === 'vendor_replacement') {
    return { utama: r.po_number || '—', kedua: `Vendor: ${r.vendor_name || '—'}` };
  }
  return { utama: r.style_code || '—', kedua: r.style_name || '' };
}

export default function AccessoryRequestInbox({ token, moduleId }) {
  const isRndMonitor = moduleId === 'rnd-accessory-requests';
  const h = { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` };
  const [requests, setRequests] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(false);
  const [filterStatus, setFilterStatus] = useState(isRndMonitor ? '' : 'submitted'); // RnD: semua status sampel
  const [filterType, setFilterType] = useState(isRndMonitor ? 'rnd_sample' : '');   // RnD: terkunci ke sampel
  const [search, setSearch] = useState('');
  const [urgentOnly, setUrgentOnly] = useState(false);
  const [detail, setDetail] = useState(null);
  const [actionModal, setActionModal] = useState(null); // { id, type: 'allocate'|'deliver', notes, ... }
  const [saving, setSaving] = useState(false);

  const fetchRequests = async () => {
    setLoading(true);
    try {
      // limit 1000 (batas server): dulu memakai bawaan 200 sehingga permintaan lama hilang dari daftar tanpa tanda.
      const qs = new URLSearchParams({ limit: '1000' });
      if (filterStatus) qs.set('status', filterStatus);
      if (filterType) qs.set('request_type', filterType);
      if (urgentOnly) qs.set('urgent_only', 'true');
      if (search) qs.set('search', search);
      const res = await fetch(`${API}/api/dewi/accessory-requests?${qs}`, { headers: h });
      const data = await res.json();
      setRequests(Array.isArray(data) ? data : []);
    } catch { toast.error('Gagal memuat daftar permintaan.'); }
    finally { setLoading(false); }
  };

  const fetchStats = async () => {
    try {
      // R&D: ringkasan hanya sampel R&D (sama dengan daftarnya); inbox Portal Aksesoris: semua jenis.
      const qs = isRndMonitor ? '?request_type=rnd_sample' : '';
      const res = await fetch(`${API}/api/dewi/accessory-requests/stats/summary${qs}`, { headers: h });
      if (res.ok) setStats(await res.json());
    } catch { /* ringkasan opsional */ }
  };

  useEffect(() => { fetchRequests(); }, [filterStatus, filterType, urgentOnly]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { fetchStats(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const muatUlang = () => { fetchRequests(); fetchStats(); };

  // 2026-11-06 (Tahap 1): aksi berhasil HANYA bila server menjawab ok; pesan server ditampilkan bila ditolak.
  const sendAction = async (path, method, body) => {
    const res = await fetch(`${API}/api/dewi/accessory-requests/${path}`, {
      method, headers: h, ...(body ? { body: JSON.stringify(body) } : {}),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const d = data?.detail;
      const err = new Error(typeof d === 'string' ? d : (d?.message || `Server menolak permintaan ini (kode ${res.status}).`));
      err.detail = d;   // 2026-11-06 (Tahap 2): mis. {code:'over_issue', lines} → minta alasan kelebihan
      throw err;
    }
    return data;
  };

  // 2026-11-06 (Tahap 2): baris tanpa master (sampel R&D diketik bebas) dipilihkan master saat diserahkan.
  const [accItems, setAccItems] = useState([]);
  const openDeliver = async (r) => {
    setActionModal({ id: r.id, code: r.request_code, type: 'deliver', notes: '', items: r.items || [], links: {}, reason: '',
      overIssue: null, poNumber: r.po_number || '', shortage: null, draft: r.purchase_draft_number || '' });
    if ((r.items || []).some((it) => !it.material_id) && accItems.length === 0) {
      try {
        const res = await fetch(`${API}/api/acc/items`, { headers: h });
        if (res.ok) setAccItems(await res.json());
      } catch { /* daftar master opsional — server tetap menolak baris tanpa master */ }
    }
  };
  const openAllocate = (r) => setActionModal({ id: r.id, code: r.request_code, type: 'allocate', notes: '' });

  const handleAllocate = async () => {
    if (!actionModal) return;
    setSaving(true);
    try {
      await sendAction(`${actionModal.id}/allocate`, 'POST', { notes: actionModal.notes || '' });
      toast.success('Permintaan disiapkan.');
      setActionModal(null);
      muatUlang();
    } catch (e) { toast.error(e.message || 'Gagal menyiapkan.'); }
    finally { setSaving(false); }
  };

  const itemLinks = (m) => Object.entries(m?.links || {}).filter(([, v]) => v)
    .map(([index, material_id]) => ({ index: Number(index), material_id }));

  const handleDeliver = async () => {
    if (!actionModal) return;
    setSaving(true);
    try {
      const res = await sendAction(`${actionModal.id}/deliver`, 'POST', {
        notes: actionModal.notes || '',
        item_links: itemLinks(actionModal),
        over_issue_reason: (actionModal.reason || '').trim(),
      });
      const n = (res.issued_items || []).length;
      toast.success(n ? `Diserahkan · ${n} aksesoris keluar dari stok dan dijurnal.` : 'Permintaan ditandai sudah diterima.');
      setActionModal(null);
      muatUlang();
    } catch (e) {
      if (e.detail?.code === 'over_issue') {
        setActionModal((p) => ({ ...p, overIssue: e.detail }));
        toast.error('Melebihi kebutuhan PO — isi alasan kelebihan lalu tandai kirim lagi.');
        return;
      }
      if (e.detail?.code === 'stock_short') {
        // 2026-11-10 (keputusan owner): tampilkan kekurangannya + tawarkan draf pembelian
        setActionModal((p) => ({ ...p, shortage: e.detail, draft: p.draft || e.detail.purchase_draft_number || '' }));
        toast.error('Stok tidak cukup — lihat kekurangannya di form.');
        return;
      }
      toast.error(e.message || 'Gagal menyimpan status.');
    } finally { setSaving(false); }
  };

  // Stok kurang → SATU draf Request Pembelian Aksesoris berisi kekurangannya (tidak memotong stok).
  const [drafting, setDrafting] = useState(false);
  const handlePurchaseDraft = async () => {
    if (!actionModal) return;
    setDrafting(true);
    try {
      const res = await sendAction(`${actionModal.id}/purchase-draft`, 'POST', { item_links: itemLinks(actionModal) });
      setActionModal((p) => ({ ...p, draft: res.pr_number || '' }));
      toast.success(res.already
        ? `Draf pembelian ${res.pr_number} sudah ada untuk permintaan ini.`
        : `Draf pembelian ${res.pr_number} dibuat. Periksa harga lalu ajukan dari menu Pembelian aksesoris.`);
      fetchRequests();
    } catch (e) { toast.error(e.message || 'Gagal membuat draf pembelian.'); }
    finally { setDrafting(false); }
  };

  // R&D menarik permintaan yang belum diserahkan (alasan wajib; tim aksesoris dikabari).
  const handleCancel = async (r) => {
    const reason = await confirmDialog({
      title: `Batalkan permintaan ${r.request_code}?`,
      body: r.status === 'allocated'
        ? 'Tim aksesoris sudah menyiapkan barangnya dan akan dikabari. Permintaan yang dibatalkan tidak bisa diaktifkan lagi.'
        : 'Tim aksesoris akan dikabari. Permintaan yang dibatalkan tidak bisa diaktifkan lagi.',
      confirmLabel: 'Batalkan permintaan', danger: true,
      input: { label: 'Alasan pembatalan', placeholder: 'Sample ditunda / desain diganti…', minLength: 1 },
    });
    if (!reason) return;
    try {
      await sendAction(`${r.id}/cancel`, 'POST', { reason });
      toast.success('Permintaan dibatalkan.');
      setDetail(null);
      muatUlang();
    } catch (e) { toast.error(e.message || 'Gagal membatalkan.'); }
  };

  // Tolak = konfirmasi bertombol merah yang meminta alasan (dulu popup biasa; alasan tetap wajib).
  const handleReject = async (r) => {
    const reason = await confirmDialog({
      title: `Tolak permintaan ${r.request_code}?`,
      body: 'Peminta melihat alasan ini. Permintaan yang ditolak tidak bisa disiapkan lagi.',
      confirmLabel: 'Tolak', danger: true,
      input: { label: 'Alasan penolakan', placeholder: 'Stok kosong / di luar standar…', minLength: 1 },
    });
    if (!reason) return;
    try {
      await sendAction(`${r.id}/reject`, 'POST', { reason });
      toast.success('Permintaan ditolak.');
      setDetail(null);
      muatUlang();
    } catch (e) { toast.error(e.message || 'Gagal menolak.'); }
  };

  const handleDelete = async (r) => {
    if (!(await confirmDialog({ title: `Hapus permintaan ${r.request_code}?`, body: 'Permintaan aksesoris dihapus permanen.',
      confirmLabel: 'Hapus', danger: true }))) return;
    try {
      await sendAction(r.id, 'DELETE');
      toast.success('Permintaan dihapus.');
      setDetail(null);
      muatUlang();
    } catch (e) { toast.error(e.message || 'Gagal menghapus.'); }
  };

  const filtered = useMemo(() => requests.filter((r) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (r.request_code || '').toLowerCase().includes(q)
      || (r.style_code || '').toLowerCase().includes(q)
      || (r.style_name || '').toLowerCase().includes(q)
      || (r.requester_name || '').toLowerCase().includes(q);
  }), [requests, search]);
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(filtered, 25);

  // Aksi baris (paling banyak 2 tampil); rincian = klik baris.
  const aksiBaris = (r) => {
    if (isRndMonitor) {
      return BISA_BATAL.includes(r.status) ? (
        <Button size="sm" variant="outline" onClick={() => handleCancel(r)} data-testid={`acc-req-cancel-${r.id}`}>
          <Ban />Batalkan
        </Button>
      ) : null;
    }
    if (r.status === 'submitted') return (
      <div className="flex justify-end gap-1.5">
        <Button size="sm" variant="success" onClick={() => openAllocate(r)} data-testid={`acc-req-allocate-${r.id}`}>
          <Package />Siapkan
        </Button>
        <Button size="sm" variant="outline" onClick={() => handleReject(r)} data-testid={`acc-req-reject-${r.id}`}>
          <XCircle />Tolak
        </Button>
      </div>
    );
    if (r.status === 'allocated') return (
      <Button size="sm" variant="success" onClick={() => openDeliver(r)} data-testid={`acc-req-deliver-${r.id}`}>
        <Truck />Tandai kirim
      </Button>
    );
    if (['draft', 'rejected', 'cancelled'].includes(r.status)) return (
      <Button size="icon-sm" variant="ghost" onClick={() => handleDelete(r)} title="Hapus permintaan" aria-label="Hapus permintaan"
        data-testid={`acc-req-delete-${r.id}`}>
        <Trash2 />
      </Button>
    );
    return null;
  };

  const kolom = [
    { kunci: 'kode', label: 'Kode', hp: 'judul', isi: (r) => (
      <span className="inline-flex flex-wrap items-center gap-1.5">
        <span className="font-medium tabular-nums text-foreground">{r.request_code}</span>
        {r.urgent && <StatusBadge status="mendesak" label="Mendesak" tone="danger" />}
      </span>) },
    // R&D: daftar selalu sampel R&D — kolom jenis tidak perlu (memberi ruang untuk tombol Batalkan)
    ...(isRndMonitor ? [] : [{ kunci: 'jenis', label: 'Jenis', hp: 'keterangan', isi: (r) => <span data-testid={`acc-req-type-badge-${r.id}`}>{typeLabel(r.request_type)}</span> }]),
    { kunci: 'konteks', label: 'Style / konteks', isi: (r) => {
      const k = konteks(r);
      return (
        <div className="min-w-0 md:max-w-[14rem]">
          <p className="truncate text-sm text-foreground">{k.utama}</p>
          {k.kedua && <p className="truncate text-xs text-muted-foreground" title={k.kedua}>{k.kedua}</p>}
        </div>
      );
    } },
    { kunci: 'item', label: 'Item', rata: 'kanan', isi: (r) => <span className="tabular-nums">{(r.items || []).length}</span> },
    { kunci: 'butuh', label: 'Butuh tanggal', isi: (r) => <span className="whitespace-nowrap">{formatDate(r.needed_by_date)}</span> },
    { kunci: 'status', label: 'Status', isi: (r) => <StatusBadge status={r.status} label={statusConf(r.status).label} tone={statusConf(r.status).tone} /> },
    { kunci: 'peminta', label: 'Peminta', hp: false, isi: (r) => r.requester_name || '—' },
    { kunci: 'dibuat', label: 'Dibuat', hp: false, isi: (r) => <span className="whitespace-nowrap text-muted-foreground">{formatDate(r.created_at)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: aksiBaris },
  ];

  const opsiStatus = [
    { key: '', label: 'Semua' }, { key: 'submitted', label: 'Menunggu' }, { key: 'allocated', label: 'Disiapkan' },
    { key: 'delivered', label: 'Terkirim' }, { key: 'rejected', label: 'Ditolak' }, { key: 'cancelled', label: 'Batal' },
  ];
  const lingkup = isRndMonitor ? 'Sampel R&D' : 'Semua jenis permintaan';
  const jumlahJenis = (k) => (stats?.by_request_type ? ` (${stats.by_request_type[k] || 0})` : '');

  return (
    <PageLayout testId="accessory-request-inbox"
      title={isRndMonitor ? 'Request aksesoris' : 'Inbox persetujuan'}
      subtitle={isRndMonitor
        ? 'Pantau permintaan aksesoris sampel R&D dan batalkan yang belum diserahkan. Penyiapan dan pengiriman oleh Portal Aksesoris.'
        : 'Semua permintaan aksesoris. Saat ditandai kirim, stok dipotong dan dijurnal.'}
      filters={<>
        <FilterChips options={opsiStatus} value={filterStatus} onChange={setFilterStatus} hideWhenEmpty={false}
          testId="acc-req-filter" ariaLabel="Status permintaan" />
        {!isRndMonitor && (
          <SmartNativeSelect value={filterType} onChange={(e) => setFilterType(e.target.value)} searchable={false}
            className="h-9 w-48" wrapperClassName="w-48" aria-label="Jenis permintaan" data-testid="acc-req-type-filter">
            <option value="">Semua jenis</option>
            {Object.entries(TYPE_CONF).map(([k, t]) => <option key={k} value={k}>{`${t.label}${jumlahJenis(k)}`}</option>)}
          </SmartNativeSelect>
        )}
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && fetchRequests()}
            placeholder="Cari kode, style, peminta" className="pl-8" data-testid="acc-req-search-input" />
        </div>
        <label className="flex items-center gap-2 text-sm" htmlFor="acc-req-urgent" data-testid="acc-req-urgent-only-label">
          <Checkbox id="acc-req-urgent" checked={urgentOnly} onCheckedChange={(v) => setUrgentOnly(!!v)}
            data-testid="acc-req-urgent-only-checkbox" />
          Mendesak saja
        </label>
      </>}
      tools={<>
        <TombolUnduh namaBerkas={isRndMonitor ? 'permintaan-sampel-rnd' : 'inbox-permintaan-aksesoris'} namaLembar="Permintaan"
          baris={filtered} testId="acc-req-unduh"
          kolom={[
            { label: 'Kode', nilai: (r) => r.request_code },
            { label: 'Jenis', nilai: (r) => typeLabel(r.request_type) },
            { label: 'Style / konteks', nilai: (r) => konteks(r).utama },
            { label: 'Keterangan', nilai: (r) => konteks(r).kedua },
            { label: 'Jumlah item', nilai: (r) => (r.items || []).length },
            { label: 'Butuh tanggal', nilai: (r) => (r.needed_by_date ? formatDate(r.needed_by_date) : '') },
            { label: 'Status', nilai: (r) => statusConf(r.status).label },
            { label: 'Mendesak', nilai: (r) => (r.urgent ? 'Ya' : 'Tidak') },
            { label: 'Peminta', nilai: (r) => r.requester_name || '' },
            { label: 'Dibuat', nilai: (r) => formatDate(r.created_at) },
          ]} />
        <Button variant="outline" size="icon" onClick={muatUlang} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={<>
        {isRndMonitor && (
          <Notice tone="info" testId="acc-req-rnd-monitor-banner">
            Permintaan baru dibuat dari Sample Request (tombol Aksesoris). Di sini R&D memantau dan bisa membatalkan
            permintaan yang belum diserahkan; menyiapkan, mengirim, dan menolak dilakukan Portal Aksesoris.
          </Notice>
        )}
        {stats && (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="acc-req-stats">
            <StatTile label="Menunggu persetujuan" value={stats.submitted ?? 0} testId="acc-req-stats-submitted"
              sub={lingkup} />
            <StatTile label="Disiapkan, belum dikirim" value={stats.allocated ?? 0} sub={lingkup} />
            <StatTile label="Mendesak" value={stats.urgent_pending ?? 0} accent={stats.urgent_pending ? 'danger' : 'default'}
              testId="acc-req-stats-urgent" sub="Menunggu atau disiapkan" />
            <StatTile label="Terkirim" value={stats.delivered ?? 0} sub={`Dari ${stats.total ?? 0} permintaan tercatat`} />
          </div>
        )}
      </>}
      footer={filtered.length > pageSize && (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />
      )}>
      {loading && requests.length === 0 ? (
        <div className="space-y-2">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
      ) : (
        <TabelData kolom={kolom} baris={paged} onKlikBaris={setDetail} testId="acc-req-table"
          kosong={<EmptyState icon={Inbox} testId="inbox-empty" title="Tidak ada permintaan aksesoris"
            description="Permintaan yang masuk tampil di sini. Ubah saringan untuk melihat status lain." />} />
      )}

      {detail && (
        <RincianPermintaan r={detail} onClose={() => setDetail(null)} isRndMonitor={isRndMonitor}
          onAllocate={() => { openAllocate(detail); setDetail(null); }}
          onDeliver={() => { openDeliver(detail); setDetail(null); }}
          onReject={() => handleReject(detail)} onDelete={() => handleDelete(detail)}
          onCancel={() => handleCancel(detail)} />
      )}

      {actionModal && (
        <FormPopup open onClose={() => setActionModal(null)} menyimpan={saving}
          ukuran={actionModal.type === 'deliver' && (actionModal.items || []).length > 4 ? 'panjang' : 'pendek'}
          judul={actionModal.type === 'allocate' ? `Siapkan aksesoris · ${actionModal.code || ''}` : `Tandai sudah diterima · ${actionModal.code || ''}`}
          keterangan={actionModal.type === 'deliver' ? 'Stok aksesoris berikut dipotong dan dijurnal saat ditandai kirim.' : 'Barang disiapkan untuk diserahkan ke peminta.'}
          labelSimpan={actionModal.type === 'allocate' ? 'Siapkan' : 'Tandai kirim'}
          onSimpan={actionModal.type === 'allocate' ? handleAllocate : handleDeliver}
          testId="acc-req-action-form">
          {actionModal.type === 'deliver' && (
            <div className="space-y-3" data-testid="acc-req-deliver-lines">
              {(actionModal.items || []).map((it, idx) => (
                <div key={idx} className="space-y-1.5 text-sm">
                  <div className="flex justify-between gap-2">
                    <span>{it.material_name || it.material_code || '—'}</span>
                    <span className="tabular-nums">{it.qty} {it.unit}</span>
                  </div>
                  {!it.material_id && (
                    <SmartNativeSelect value={actionModal.links?.[idx] || ''}
                      onChange={(e) => setActionModal((p) => ({ ...p, links: { ...(p.links || {}), [idx]: e.target.value } }))}
                      className="h-9 w-full" aria-label="Aksesoris di master" data-testid={`acc-req-link-${idx}`}>
                      <option value="">Pilih aksesoris di master (wajib, barang ini belum tertaut)…</option>
                      {accItems.map((a) => <option key={a.id} value={a.id}>{`${a.code} · ${a.name} (stok ${a.stock_qty} ${a.unit})`}</option>)}
                    </SmartNativeSelect>
                  )}
                </div>
              ))}
              {actionModal.shortage && (
                <Notice tone="warning" icon={AlertTriangle} title="Stok tidak cukup — belum ada barang yang dikeluarkan"
                  testId="acc-req-shortage"
                  action={actionModal.draft ? null : (
                    <Button size="sm" variant="outline" onClick={handlePurchaseDraft} disabled={drafting}
                      data-testid="acc-req-purchase-draft">
                      <ShoppingCart />{drafting ? 'Membuat…' : 'Buat draf pembelian'}
                    </Button>
                  )}>
                  <ul className="list-disc space-y-0.5 pl-4">
                    {(actionModal.shortage.lines || []).map((l) => (
                      <li key={l.material_id}>
                        {`${l.material_code || l.material_name}: butuh ${angka(l.needed)}, bisa dipakai ${angka(l.usable)} — kurang ${angka(l.short)} ${l.unit || ''}`}
                      </li>
                    ))}
                  </ul>
                  {actionModal.shortage.other_problems > 0 && (
                    <p className="mt-1">Ada baris lain yang belum tertaut ke master — pilih masternya di atas.</p>
                  )}
                  <p className="mt-1" data-testid="acc-req-purchase-draft-info">
                    {actionModal.draft
                      ? `Draf pembelian ${actionModal.draft} sudah dibuat untuk kekurangan ini. Ajukan dari menu Pembelian aksesoris; serahkan setelah barang datang.`
                      : 'Buat draf pembelian berisi kekurangannya (tidak memotong stok), atau serahkan setelah stok cukup.'}
                  </p>
                </Notice>
              )}
              {actionModal.overIssue && (
                <Isian label="Alasan kelebihan" wajib htmlFor="acc-req-over"
                  petunjuk={`Melebihi kebutuhan PO ${actionModal.overIssue.po_number || actionModal.poNumber}: ${(actionModal.overIssue.lines || [])
                    .map((l) => `${l.code || l.name} kebutuhan ${l.need}, sudah keluar ${l.issued}, diminta ${l.qty}`).join('; ')}.`}>
                  <div data-testid="acc-req-over-issue">
                    <Input id="acc-req-over" value={actionModal.reason || ''}
                      onChange={(e) => setActionModal((p) => ({ ...p, reason: e.target.value }))}
                      placeholder="Mis. pengganti kancing cacat dari vendor" data-testid="acc-req-over-issue-reason" />
                  </div>
                </Isian>
              )}
            </div>
          )}
          <Isian label="Catatan" petunjuk="Opsional." htmlFor="acc-req-notes">
            <Textarea id="acc-req-notes" rows={3} value={actionModal.notes}
              onChange={(e) => setActionModal((p) => ({ ...p, notes: e.target.value }))}
              placeholder={actionModal.type === 'allocate' ? 'Sudah disiapkan di rak A-3…' : 'Diterima oleh…'}
              data-testid="acc-req-action-notes" />
          </Isian>
        </FormPopup>
      )}
    </PageLayout>
  );
}

function RincianPermintaan({ r, onClose, isRndMonitor, onAllocate, onDeliver, onReject, onDelete, onCancel }) {
  const st = statusConf(r.status);
  const isVendor = r.request_type === 'vendor_additional' || r.request_type === 'vendor_replacement';
  const items = r.items || [];
  return (
    <DetailPopup open onClose={onClose} judul={`Permintaan ${r.request_code}`} testId="acc-req-detail"
      keterangan={`${typeLabel(r.request_type)} · dibuat ${formatDate(r.created_at)}`}
      status={<>
        <StatusBadge status={r.status} label={st.label} tone={st.tone} />
        {r.urgent && <StatusBadge status="mendesak" label="Mendesak" tone="danger" />}
      </>}
      aksi={isRndMonitor ? (BISA_BATAL.includes(r.status) && (
        <Button size="sm" variant="destructive" onClick={onCancel} data-testid="acc-req-detail-cancel"><Ban />Batalkan</Button>
      )) : <>
        {r.status === 'submitted' && <>
          <Button size="sm" variant="success" onClick={onAllocate}><Package />Siapkan</Button>
          <Button size="sm" variant="destructive" onClick={onReject}><XCircle />Tolak</Button>
        </>}
        {r.status === 'allocated' && <Button size="sm" variant="success" onClick={onDeliver}><Truck />Tandai kirim</Button>}
        {['draft', 'rejected', 'cancelled'].includes(r.status) && (
          <Button size="sm" variant="destructive" onClick={onDelete}><Trash2 />Hapus</Button>
        )}
      </>}>
      <dl className="divide-y divide-[var(--glass-border)]">
        {r.request_type === 'internal_issuance' ? <>
          <BarisDetail label="Divisi">{r.divisi || '—'}</BarisDetail>
          <BarisDetail label="Tujuan pemakaian">{r.purpose || '—'}</BarisDetail>
        </> : isVendor ? <>
          {/* 2026-11-06 (Tahap 2): nama vendor & nomor surat jalan — dulu ID mentah */}
          <BarisDetail label="Vendor">{r.vendor_name || '—'}</BarisDetail>
          <BarisDetail label="Nomor PO"><span className="tabular-nums">{r.po_number || '—'}</span></BarisDetail>
          {r.original_shipment_id && <BarisDetail label="Surat jalan asal">{r.original_shipment_number || '—'}</BarisDetail>}
          {r.child_shipment_number && <BarisDetail label="Surat jalan susulan">{r.child_shipment_number}</BarisDetail>}
        </> : <>
          <BarisDetail label="Style">{r.style_code} — {r.style_name}</BarisDetail>
          <BarisDetail label="Kode sampel"><span className="tabular-nums">{r.sample_code || '—'}</span></BarisDetail>
        </>}
        <BarisDetail label="Peminta">{r.requester_name || '—'}</BarisDetail>
        <BarisDetail label="Butuh tanggal">{formatDate(r.needed_by_date)}</BarisDetail>
        {r.notes && <BarisDetail label="Catatan">{r.notes}</BarisDetail>}
        {r.allocated_by && <BarisDetail label="Disiapkan">{r.allocated_by} · {formatDate(r.allocated_at)}</BarisDetail>}
        {r.delivered_by && <BarisDetail label="Dikirim">{r.delivered_by} · {formatDate(r.delivered_at)}</BarisDetail>}
        {r.rejection_reason && <BarisDetail label="Alasan ditolak"><span className="text-[hsl(var(--danger-text))]">{r.rejection_reason}</span></BarisDetail>}
        {r.status === 'cancelled' && <>
          <BarisDetail label="Dibatalkan">{r.cancelled_by || '—'}{r.cancelled_at ? ` · ${formatDate(r.cancelled_at)}` : ''}</BarisDetail>
          {r.cancel_reason && <BarisDetail label="Alasan dibatalkan">{r.cancel_reason}</BarisDetail>}
        </>}
        {r.purchase_draft_number && (
          <BarisDetail label="Draf pembelian kekurangan"><span className="tabular-nums">{r.purchase_draft_number}</span></BarisDetail>
        )}
      </dl>
      <div className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-medium text-foreground">Item aksesoris ({items.length})</p>
          <TombolUnduh namaBerkas={`permintaan-${r.request_code}`} namaLembar="Item" baris={items} testId="acc-req-detail-unduh"
            kolom={[
              { label: 'Kode', nilai: (it) => it.material_code || '' }, { label: 'Nama', nilai: (it) => it.material_name || '' },
              { label: 'Qty', nilai: (it) => Number(it.qty || 0) }, { label: 'Satuan', nilai: (it) => it.unit || '' },
              { label: 'Catatan', nilai: (it) => it.notes || '' },
            ]} />
        </div>
        {items.length === 0 ? <p className="text-sm text-muted-foreground">Tidak ada item.</p> : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader><TableRow>
                <TableHead>Kode</TableHead><TableHead>Nama</TableHead><TableHead className="text-right">Qty</TableHead>
                <TableHead>Satuan</TableHead><TableHead>Catatan</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {items.map((it, idx) => (
                  <TableRow key={idx}>
                    <TableCell className="tabular-nums">{it.material_code || '—'}</TableCell>
                    <TableCell>
                      <span className="inline-flex flex-wrap items-center gap-1.5">
                        {it.material_name}
                        {!it.material_id && (
                          <StatusBadge status="belum-tertaut" tone="warning" label="Belum tertaut" testId={`acc-req-item-unlinked-${idx}`} />
                        )}
                      </span>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{it.qty}</TableCell>
                    <TableCell>{it.unit}</TableCell>
                    <TableCell className="text-muted-foreground">{it.notes || '—'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
      {r.status === 'delivered' && (
        <p className="flex items-center gap-1.5 text-sm text-[hsl(var(--success-text))]"><CheckCircle2 className="h-4 w-4" />Barang sudah diserahkan.</p>
      )}
      {r.urgent && r.status === 'submitted' && (
        <p className="flex items-center gap-1.5 text-sm text-[hsl(var(--danger-text))]"><AlertTriangle className="h-4 w-4" />Ditandai mendesak oleh peminta.</p>
      )}
    </DetailPopup>
  );
}

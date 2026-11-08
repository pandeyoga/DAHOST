/**
 * Kirim sample (Portal Toko) — pengiriman sample ke kreator/KOL dan tindak lanjut hasilnya.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, penyaring satu baris, 4 StatTile berketerangan (dulu 6 kartu),
 * tabel 10 kolom + unduh Excel/CSV semua baris (dulu CSV halaman ini saja; kolom SKU/HPP satuan/ongkir/kurir/resi
 * kini di popup detail & berkas unduhan), detail popup berisi form tindak lanjut, form = FormPopup + DatePicker.
 * Tampilan "Kartu" lama diganti tabel (di HP otomatis kartu ringkas). Video (F10) kini baris kedua kolom Tindak lanjut, "Umur" (F10) baris kedua kolom Tanggal ("55 hari lalu") — keduanya tetap terlihat, tabel muat tanpa geser.
 * Perbaikan ikut: penyaring "Semua …" dulu mengirim nilai spasi ke server.
 */
import { confirmDialog } from '@/components/ui/confirm-dialog';
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Plus, Pencil, Trash2, RefreshCw, CheckCircle2, Truck, Loader2, Video, Search, TrendingUp } from 'lucide-react';
import axios from 'axios';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import { Textarea } from '@/components/ui/textarea';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import DatePicker from '@/components/ui/date-picker';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import PaginationLite from '@/components/ui/pagination-lite';
import { useToast } from '@/hooks/use-toast';
import { useMarketingAccounts } from '@/hooks/useMarketingAccounts';
import { todayWIB, toWIBDate, daysBetweenISO } from '@/lib/waktu';
import { formatDateID, formatRupiahShort } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from '../moduleAtoms';
import { getPlatformConfig } from './AccountBadge';
import {
  MarketingAccountSelect, MarketingCreatorSelect, CatalogItemSelect,
} from './pickers/MarketingPickers';

const API = process.env.REACT_APP_BACKEND_URL;

// Tanggal kalender WIB: 'YYYY-MM-DD' dibiarkan, instan (created_at) dibaca dalam WIB.
const fmtDate = (v) => {
  if (!v) return '—';
  const ymd = toWIBDate(v) || String(v).slice(0, 10);
  return formatDateID(ymd) || ymd;
};
// Umur dalam HARI KALENDER WIB (dulu selisih jam dibulatkan → lewat 19.00 WIB sudah +1).
const ageDays = (v) => {
  const d = v ? toWIBDate(v) : '';
  if (!d) return '—';
  return Math.max(0, daysBetweenISO(d, todayWIB()));
};
const rp = (n) => `Rp ${(Number(n) || 0).toLocaleString('id-ID')}`;
const SHIPMENT_STATUS_CONFIG = {
  pending: { label: 'Belum dikirim', tone: 'warning' },
  shipped: { label: 'Dikirim', tone: 'info' },
  delivered: { label: 'Sampai', tone: 'success' },
};
const PROGRESS_STATUS_CONFIG = {
  open: { label: 'Terbuka', tone: 'info' },
  follow_up: { label: 'Ditindaklanjuti', tone: 'info' },
  sold: { label: 'Terjual', tone: 'success' },
  no_response: { label: 'Tidak ada respons', tone: 'muted' },
  closed: { label: 'Ditutup', tone: 'danger' },
};
const JENIS_SAMPLE = { live: 'Live streaming', video: 'Video ulasan' };
const KURIR = { jnt: 'J&T', spx: 'SPX', sicepat: 'SiCepat' };
const NAMA_PLATFORM = { shopee: 'Shopee', tiktok: 'TikTok', tiktokshop: 'TikTok', tokopedia: 'Tokopedia', instagram: 'Instagram', lazada: 'Lazada' };
const labelPlatform = (p) => NAMA_PLATFORM[String(p || '').toLowerCase()] || (getPlatformConfig(p).label !== 'Platform' ? getPlatformConfig(p).label
  : (p ? String(p).replace(/^./, (x) => x.toUpperCase()) : '—'));
const Lencana = ({ peta, nilai }) => (nilai
  ? <StatusBadge status={nilai} label={peta[nilai]?.label || nilai} tone={peta[nilai]?.tone} />
  : <span className="text-muted-foreground">—</span>);

const EMPTY_FORM = {
  account_id: '', account_name: '',
  date: '', username: '', sample_type: 'video', platform: 'tiktok', product: '',
  size: 'M', color: '', quantity: 1, hpp: 0, ongkir: 0, courier: 'jnt', video_link: '', notes: ''
};

export default function SampleDeliveryModule({ token }) {
  const { toast } = useToast();
  const authH = useMemo(() => ({ Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` }), [token]);
  const { accounts: masterAccounts, byId: accountById } = useMarketingAccounts(token);
  const [summary, setSummary] = useState(null);
  const [samples, setSamples] = useState([]);
  const [pagination, setPagination] = useState(null);

  const [loading, setLoading] = useState(true);

  const [filterShipmentStatus, setFilterShipmentStatus] = useState('');
  const [filterProgress, setFilterProgress] = useState('');
  const [filterPlatform, setFilterPlatform] = useState('');
  // F14 — filter per TOKO. Sebelum ini `marketing_samples` bahkan tidak punya
  // `account_id`, jadi pertanyaan "berapa biaya sample toko X" tidak terjawab.
  const [filterAccountId, setFilterAccountId] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [currentPage, setCurrentPage] = useState(1);

  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [formLoading, setFormLoading] = useState(false);

  // Opsi ukuran & warna mengikuti item katalog yang dipilih (bukan teks bebas).
  const [sizeOptions, setSizeOptions] = useState([]);
  const [colorOptions, setColorOptions] = useState([]);

  const [showDetail, setShowDetail] = useState(null);
  const [progressUpdate, setProgressUpdate] = useState({ progress: '', sales_update: '' });
  const [actionLoading, setActionLoading] = useState('');
  const [galatForm, setGalatForm] = useState('');

  const fetchSummary = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/api/marketing/samples/summary`, {
        headers: authH,
        params: filterAccountId ? { account_id: filterAccountId } : {},
      });
      setSummary(res.data.data || {});
    } catch (e) {
      console.error('Summary fetch error:', e);
    }
  }, [authH, filterAccountId]);

  const fetchSamples = useCallback(async (page = 1) => {
    try {
      setLoading(true);
      const params = { page, page_size: 20 };
      if (filterShipmentStatus) params.shipment_status = filterShipmentStatus;
      if (filterProgress) params.progress = filterProgress;
      if (filterPlatform) params.platform = filterPlatform;
      if (filterAccountId) params.account_id = filterAccountId;
      if (searchQuery) params.search = searchQuery;

      const res = await axios.get(`${API}/api/marketing/samples`, { headers: authH, params });
      setSamples(res.data.data || []);
      setPagination(res.data.pagination || {});
    } catch (e) {
      toast({ title: 'Gagal', description: e.response?.data?.detail || e.message, variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  }, [authH, toast, filterShipmentStatus, filterProgress, filterPlatform, filterAccountId, searchQuery]);

  useEffect(() => {
    fetchSummary();
  }, [fetchSummary]);

  useEffect(() => {
    fetchSamples(currentPage);
  }, [fetchSamples, currentPage]);

  const openForm = (sample = null) => {
    if (sample) {
      setEditTarget(sample);
      setForm({
        account_id: sample.account_id || '',
        account_name: sample.account_name || '',
        date: sample.date,
        username: sample.username,
        sample_type: sample.sample_type,
        platform: sample.platform,
        product: sample.product,
        size: sample.size,
        color: sample.color,
        quantity: sample.quantity,
        hpp: sample.hpp,
        ongkir: sample.ongkir,
        courier: sample.courier,
        video_link: sample.video_link || '',
        notes: sample.notes || ''
      });
    } else {
      setEditTarget(null);
      setForm({ ...EMPTY_FORM, date: todayWIB() });
    }
    setGalatForm('');
    setShowForm(true);
  };

  // When account_id changes, auto-fill account_name & platform from master
  const handleAccountChange = (accountId) => {
    const acc = accountById[accountId];
    setForm(f => ({
      ...f,
      account_id: accountId,
      account_name: acc?.account_name || acc?.name || '',
      platform: acc?.platform || f.platform,
    }));
  };

  const closeForm = () => {
    setShowForm(false);
    setEditTarget(null);
    setForm(EMPTY_FORM);
  };

  const handleSave = async () => {
    setGalatForm('');
    // F14/F15 — toko, kreator, dan produk katalog WAJIB dipilih dari master.
    // Dulu `username`/`product`/`size`/`color`/`hpp` semuanya teks/angka ketikan:
    // satu kreator bisa pecah jadi beberapa baris laporan hanya karena beda ejaan,
    // dan HPP yang salah ketik langsung menjadi biaya sample yang salah.
    if (!form.account_id) {
      setGalatForm('Toko belum dipilih — sample harus menempel pada satu toko.');
      return;
    }
    if (!form.creator_id) {
      setGalatForm('Kreator belum dipilih — pilih kreator yang ditugaskan ke toko ini.');
      return;
    }
    if (!form.catalog_item_id && !form.product) {
      setGalatForm('Produk belum dipilih — pilih produk dari katalog toko.');
      return;
    }
    try {
      setFormLoading(true);
      if (editTarget) {
        await axios.put(`${API}/api/marketing/samples/${editTarget.id}`, form, { headers: authH });
        toast({ title: 'Berhasil', description: 'Sample disimpan.' });
      } else {
        await axios.post(`${API}/api/marketing/samples`, form, { headers: authH });
        toast({ title: 'Berhasil', description: 'Sample ditambahkan.' });
      }
      closeForm();
      fetchSamples(currentPage);
      fetchSummary();
    } catch (e) {
      setGalatForm(e.response?.data?.detail || e.message);
    } finally {
      setFormLoading(false);
    }
  };

  const handleDelete = async (id) => {
    if (!(await confirmDialog({ title: 'Hapus sample ini?', body: 'Catatan pengiriman sample dihapus dari daftar.', confirmLabel: 'Hapus', danger: true }))) return;
    setShowDetail(null);
    try {
      await axios.delete(`${API}/api/marketing/samples/${id}`, { headers: authH });
      toast({ title: 'Berhasil', description: 'Sample dihapus.' });
      fetchSamples(currentPage);
      fetchSummary();
    } catch (e) {
      toast({ title: 'Gagal', description: e.response?.data?.detail || e.message, variant: 'destructive' });
    }
  };

  const handleShip = async (id) => {
    try {
      setActionLoading(id);
      await axios.post(`${API}/api/marketing/samples/${id}/ship`, {}, { headers: authH });
      toast({ title: 'Berhasil', description: 'Sample ditandai dikirim.' });
      fetchSamples(currentPage);
      fetchSummary();
    } catch (e) {
      toast({ title: 'Gagal', description: e.response?.data?.detail || e.message, variant: 'destructive' });
    } finally {
      setActionLoading('');
    }
  };

  const handleDeliver = async (id) => {
    try {
      setActionLoading(id);
      await axios.post(`${API}/api/marketing/samples/${id}/deliver`, {}, { headers: authH });
      toast({ title: 'Berhasil', description: 'Sample ditandai sampai.' });
      fetchSamples(currentPage);
      fetchSummary();
    } catch (e) {
      toast({ title: 'Gagal', description: e.response?.data?.detail || e.message, variant: 'destructive' });
    } finally {
      setActionLoading('');
    }
  };

  const handleUpdateProgress = async () => {
    if (!progressUpdate.progress) {
      toast({ title: 'Pilih status tindak lanjut', variant: 'destructive' });
      return;
    }
    try {
      setActionLoading(showDetail.id);
      await axios.post(`${API}/api/marketing/samples/${showDetail.id}/update-progress`, progressUpdate, { headers: authH });
      toast({ title: 'Berhasil', description: 'Tindak lanjut disimpan.' });
      setShowDetail(null);
      setProgressUpdate({ progress: '', sales_update: '' });
      fetchSamples(currentPage);
      fetchSummary();
    } catch (e) {
      toast({ title: 'Gagal', description: e.response?.data?.detail || e.message, variant: 'destructive' });
    } finally {
      setActionLoading('');
    }
  };

  const clearFilters = () => {
    setFilterShipmentStatus('');
    setFilterProgress('');
    setFilterPlatform('');
    setSearchQuery('');
    setCurrentPage(1);
  };

  const s = summary || {};
  const adaSaring = [filterShipmentStatus, filterProgress, filterPlatform, filterAccountId, searchQuery].filter(Boolean).length > 0;

  const paramSaring = () => {
    const params = {};
    if (filterShipmentStatus) params.shipment_status = filterShipmentStatus;
    if (filterProgress) params.progress = filterProgress;
    if (filterPlatform) params.platform = filterPlatform;
    if (filterAccountId) params.account_id = filterAccountId;
    if (searchQuery) params.search = searchQuery;
    return params;
  };
  /** Unduh semua sample hasil saringan (dulu hanya 20 baris halaman ini). */
  const ambilSemua = async () => {
    const semua = [];
    for (let p = 1; p <= 200; p += 1) {
      const res = await axios.get(`${API}/api/marketing/samples`, { headers: authH, params: { page: p, page_size: 100, ...paramSaring() } });
      semua.push(...(res.data.data || []));
      if (p >= (res.data.pagination?.total_pages || 1)) break;
    }
    return semua;
  };
  const bukaDetail = (smp) => { setShowDetail(smp); setProgressUpdate({ progress: smp.progress, sales_update: smp.sales_update }); };

  const tombolKirim = (smp) => (smp.shipment_status === 'pending' ? (
    <Button onClick={() => handleShip(smp.id)} disabled={actionLoading === smp.id} variant="outline" size="sm" title="Tandai dikirim">
      {actionLoading === smp.id ? <Loader2 className="animate-spin" /> : <Truck />}Dikirim
    </Button>
  ) : smp.shipment_status === 'shipped' ? (
    <Button onClick={() => handleDeliver(smp.id)} disabled={actionLoading === smp.id} variant="outline" size="sm" title="Tandai sampai">
      {actionLoading === smp.id ? <Loader2 className="animate-spin" /> : <CheckCircle2 />}Sampai
    </Button>
  ) : null);

  const kolom = [
    { kunci: 'tanggal', label: 'Tanggal', hp: 'keterangan', isi: (x) => (
      <span className="tabular-nums md:whitespace-nowrap">{fmtDate(x.date || x.created_at)}
        <span className="block text-xs text-muted-foreground">{ageDays(x.date || x.created_at)} hari lalu</span></span>) },
    { kunci: 'kreator', label: 'Kreator', hp: 'judul', isi: (x) => (
      <span className="md:whitespace-nowrap"><span className="font-medium text-foreground">{x.username || '—'}</span>
        <span className="block text-xs text-muted-foreground">{x.account_name || '—'} · {JENIS_SAMPLE[x.sample_type] || x.sample_type_label || '—'}</span></span>) },
    { kunci: 'produk', label: 'Produk', isi: (x) => (
      <p className="md:max-w-[13rem] md:truncate" title={x.product}>{x.product || '—'}
        {(x.size || x.color) && <span className="text-xs text-muted-foreground"> · {[x.size, x.color].filter(Boolean).join(' ')}</span>}</p>) },
    { kunci: 'qty', label: 'Qty', rata: 'kanan', isi: (x) => <span className="tabular-nums">{x.quantity || 0}</span> },
    { kunci: 'hpp', label: 'HPP (Rp)', rata: 'kanan', isi: (x) => <span className="tabular-nums font-medium">{(x.total_hpp || 0).toLocaleString('id-ID')}</span> },
    { kunci: 'kirim', label: 'Status kirim', isi: (x) => <Lencana peta={SHIPMENT_STATUS_CONFIG} nilai={x.shipment_status} /> },
    { kunci: 'progres', label: 'Tindak lanjut · video', isi: (x) => (
      <span className="flex flex-col items-start gap-1"><Lencana peta={PROGRESS_STATUS_CONFIG} nilai={x.progress} />
        {x.video_link ? (
          <a href={x.video_link} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}
            className="inline-flex items-center gap-1 text-xs text-primary hover:underline"><Video className="h-3.5 w-3.5" />Buka video</a>
        ) : <span className="text-xs text-[hsl(var(--warning-text))]">Video belum ada</span>}</span>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (x) => (
      <div className="flex justify-end gap-1">
        {tombolKirim(x)}
        <Button onClick={() => openForm(x)} variant="ghost" size="icon-sm" title="Ubah sample" aria-label="Ubah sample"><Pencil /></Button>
      </div>) },
  ];

  return (
    <PageLayout testId="sample-delivery-module" title="Kirim sample"
      subtitle="Pengiriman sample ke kreator/KOL, biaya HPP + ongkir, dan hasil tindak lanjutnya."
      actions={<Button onClick={() => openForm()} data-testid="sample-create"><Plus />Tambah sample</Button>}
      filters={<>
        <div className="relative w-full sm:w-44">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder="Cari kreator atau produk" value={searchQuery} className="pl-8"
            onChange={e => { setSearchQuery(e.target.value); setCurrentPage(1); }} data-testid="sample-search" />
        </div>
        {/* F14 — filter per TOKO (biaya sample per toko). */}
        <MarketingAccountSelect token={token} value={filterAccountId}
          onChange={(v) => { setFilterAccountId(v); setCurrentPage(1); }}
          label="" includeAll allLabel="Semua toko" required={false} className="w-44"
          testId="sample-filter-account" />
        <SmartNativeSelect value={filterShipmentStatus} onChange={(e) => { setFilterShipmentStatus(e.target.value); setCurrentPage(1); }} className="w-44" searchable={false}>
          <option value="">Semua status kirim</option>
          {Object.entries(SHIPMENT_STATUS_CONFIG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={filterProgress} onChange={(e) => { setFilterProgress(e.target.value); setCurrentPage(1); }} className="w-48" searchable={false}>
          <option value="">Semua tindak lanjut</option>
          {Object.entries(PROGRESS_STATUS_CONFIG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={filterPlatform} onChange={(e) => { setFilterPlatform(e.target.value); setCurrentPage(1); }} className="w-40" searchable={false}>
          <option value="">Semua platform</option>
          <option value="tiktok">TikTok</option>
          <option value="instagram">Instagram</option>
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="kirim-sample-kreator" namaLembar="Sample" baris={samples} ambilSemua={ambilSemua} testId="sample-export-csv"
          kolom={[
            { label: 'Tanggal', nilai: (x) => fmtDate(x.date || x.created_at) },
            { label: 'Toko', nilai: (x) => x.account_name || '' },
            { label: 'Platform', nilai: (x) => labelPlatform(x.platform) },
            { label: 'Kreator', nilai: (x) => x.username || '' },
            { label: 'Jenis', nilai: (x) => JENIS_SAMPLE[x.sample_type] || x.sample_type_label || '' },
            { label: 'Produk', nilai: (x) => x.product || '' },
            { label: 'SKU', nilai: (x) => x.sku || '' },
            { label: 'Warna', nilai: (x) => x.color || '' },
            { label: 'Ukuran', nilai: (x) => x.size || '' },
            { label: 'Qty', nilai: (x) => Number(x.quantity) || 0 },
            { label: 'HPP', nilai: (x) => Number(x.hpp) || 0 },
            { label: 'Total HPP', nilai: (x) => Number(x.total_hpp) || 0 },
            { label: 'Ongkir', nilai: (x) => Number(x.ongkir) || 0 },
            { label: 'Kurir', nilai: (x) => KURIR[x.courier] || x.courier || '' },
            { label: 'Resi', nilai: (x) => x.tracking_number || '' },
            { label: 'Status kirim', nilai: (x) => SHIPMENT_STATUS_CONFIG[x.shipment_status]?.label || x.shipment_status || '' },
            { label: 'Tindak lanjut', nilai: (x) => PROGRESS_STATUS_CONFIG[x.progress]?.label || x.progress || '' },
            { label: 'Link video', nilai: (x) => x.video_link || '' },
            { label: 'Umur (hari)', nilai: (x) => ageDays(x.date || x.created_at) },
          ]} />
        <Button onClick={() => { fetchSamples(currentPage); fetchSummary(); }} variant="outline" size="icon" title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={(s.total || 0) > 0 && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="sample-kpi">
          <StatTile label="Total sample" value={s.total || 0}
            sub={`${s.pending || 0} belum dikirim · ${s.shipped || 0} dikirim · ${s.delivered || 0} sampai`}
            hint={filterAccountId ? 'Toko terpilih; tidak ikut penyaring lain.' : 'Semua toko; tidak ikut penyaring status.'} />
          <StatTile label="Belum dikirim" value={s.pending || 0} accent={(s.pending || 0) > 0 ? 'warning' : 'default'}
            hint="Sample yang belum ditandai dikirim." />
          <StatTile label="Terjual" value={s.sold || 0} accent="success"
            sub={`${s.follow_up || 0} ditindaklanjuti · ${s.no_response || 0} tanpa respons`}
            hint="Sample dengan tindak lanjut 'Terjual'." />
          <StatTile label="Biaya sample" value={formatRupiahShort(s.total_investment || 0)}
            sub={`HPP ${formatRupiahShort(s.total_hpp || 0)} + ongkir ${formatRupiahShort(s.total_ongkir || 0)}`}
            hint={`${rp(s.total_investment)} — jumlah total HPP + ongkir semua sample.`} />
        </div>
      )}
      footer={pagination && pagination.total_pages > 1 && (
        <PaginationLite page={currentPage} totalPages={pagination.total_pages} total={pagination.total} pageSize={20}
          onPageChange={setCurrentPage} />
      )}>
      {loading && samples.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat sample…</p>
      ) : (
        <TabelData kolom={kolom} baris={samples} onKlikBaris={bukaDetail} testId="sample-table"
          kosong={<EmptyState title={adaSaring ? 'Tidak ada sample yang cocok' : 'Belum ada sample'}
            description={adaSaring ? 'Ubah saringan atau kata pencarian.' : 'Catat sample yang dikirim ke kreator dengan tombol Tambah sample.'}
            action={!adaSaring && <Button onClick={() => openForm()}><Plus />Tambah sample</Button>} />} />
      )}

      {/* Form sample (popup) */}
      <FormPopup open={showForm} onClose={closeForm} ukuran="panjang" onSimpan={handleSave} menyimpan={formLoading}
        judul={editTarget ? 'Ubah sample' : 'Tambah sample'} galat={galatForm} testId="sample-form">
        <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Akun / toko marketplace" wajib htmlFor="sample-account"
          petunjuk={form.account_id ? `Platform: ${labelPlatform(form.platform)} (otomatis dari akun)` : 'Toko asal sample.'}>
          <SmartNativeSelect id="sample-account" value={form.account_id || ''} onChange={(e) => handleAccountChange(e.target.value)}
            data-testid="sample-account-select">
            <option value="">{masterAccounts.length === 0 ? 'Belum ada akun aktif' : 'Pilih akun'}</option>
            {masterAccounts.map(acc => <option key={acc.id} value={acc.id}>{`${acc.account_name} · ${labelPlatform(acc.platform)}`}</option>)}
          </SmartNativeSelect>
        </Isian>
        {/* F15 — produk dari KATALOG toko; SKU, HPP, ukuran & warna ikut master. */}
        <Isian label="Produk" wajib>
          <CatalogItemSelect
            token={token} accountId={form.account_id} label=""
            value={form.catalog_item_id || ''}
            onChange={(item) => { setSizeOptions(item?.sizes || []); setColorOptions(item?.colors || []); setForm({
              ...form,
              catalog_item_id: item?.id || '',
              product: item?.name || '',
              sku: item?.sku || '',
              hpp: item?.hpp || 0,
              size: (item?.sizes && item.sizes[0]) || form.size,
              color: (item?.colors && item.colors[0]) || form.color,
            }); }}
            testId="sample-item-select" />
        </Isian>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Tanggal">
            <DatePicker value={form.date || ''} onChange={(v) => setForm({ ...form, date: v })} testId="sample-date" />
          </Isian>
          {/* F15 — kreator dipilih dari master yang DI-ASSIGN ke toko ini; `username` diisi server. */}
          <Isian label="Kreator / KOL" wajib>
            <MarketingCreatorSelect token={token} accountId={form.account_id} label=""
              value={form.creator_id || ''} onChange={(v) => setForm({ ...form, creator_id: v })} testId="sample-creator-select" />
          </Isian>
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          <Isian label="Jenis" htmlFor="sample-type">
            <SmartNativeSelect id="sample-type" value={form.sample_type} searchable={false} onChange={(e) => setForm({ ...form, sample_type: e.target.value })}>
              {Object.entries(JENIS_SAMPLE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Platform" htmlFor="sample-platform">
            <SmartNativeSelect id="sample-platform" value={form.platform} searchable={false} onChange={(e) => setForm({ ...form, platform: e.target.value })}>
              <option value="tiktok">TikTok</option>
              <option value="instagram">Instagram</option>
            </SmartNativeSelect>
          </Isian>
          <Isian label="Kurir" htmlFor="sample-courier">
            <SmartNativeSelect id="sample-courier" value={form.courier} searchable={false} onChange={(e) => setForm({ ...form, courier: e.target.value })}>
              {Object.entries(KURIR).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </SmartNativeSelect>
          </Isian>
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          <Isian label="Ukuran" htmlFor="sample-size">
            <SmartNativeSelect id="sample-size" value={form.size || ''} onChange={(e) => setForm({ ...form, size: e.target.value })}
              data-testid="sample-size-select">
              {(sizeOptions.length ? sizeOptions : ['All Size']).map(sz => <option key={sz} value={sz}>{sz === 'All Size' ? 'Semua ukuran' : sz}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Warna" htmlFor="sample-color">
            <SmartNativeSelect id="sample-color" value={form.color || ''} onChange={(e) => setForm({ ...form, color: e.target.value })}
              data-testid="sample-color-select">
              {(colorOptions.length ? colorOptions : ['-']).map(c => <option key={c} value={c}>{c}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Qty" htmlFor="sample-qty">
            <Input id="sample-qty" type="number" value={form.quantity} onChange={e => setForm({ ...form, quantity: parseInt(e.target.value) })} />
          </Isian>
          <Isian label="HPP per pcs" petunjuk={form.catalog_item_id ? 'Dari katalog — ubah di Manajemen Katalog bila salah.' : undefined}>
            <MoneyInput value={form.hpp} disabled={!!form.catalog_item_id}
              onChange={e => setForm({ ...form, hpp: parseFloat(e.target.value) })} data-testid="sample-hpp" />
          </Isian>
          <Isian label="Ongkir">
            <MoneyInput value={form.ongkir} onChange={e => setForm({ ...form, ongkir: parseFloat(e.target.value) })} />
          </Isian>
        </div>
        <Isian label="Tautan video" htmlFor="sample-video">
          <Input id="sample-video" value={form.video_link} onChange={e => setForm({ ...form, video_link: e.target.value })} placeholder="https://vt.tiktok.com/..." />
        </Isian>
        <Isian label="Catatan" htmlFor="sample-notes">
          <Textarea id="sample-notes" value={form.notes} rows={2} onChange={e => setForm({ ...form, notes: e.target.value })} />
        </Isian>
      </FormPopup>

      {/* Detail + tindak lanjut (popup) */}
      {showDetail && (
        <DetailPopup open onClose={() => setShowDetail(null)} testId="sample-detail"
          judul={`Sample untuk ${showDetail.username || 'kreator'}`}
          status={<><Lencana peta={SHIPMENT_STATUS_CONFIG} nilai={showDetail.shipment_status} />
            <Lencana peta={PROGRESS_STATUS_CONFIG} nilai={showDetail.progress} /></>}
          keterangan={`${showDetail.account_name || '—'} · ${labelPlatform(showDetail.platform)} · ${fmtDate(showDetail.date || showDetail.created_at)}`}
          aksi={<>
            {tombolKirim(showDetail)}
            <Button size="sm" variant="outline" onClick={() => { const r = showDetail; setShowDetail(null); openForm(r); }}><Pencil />Ubah</Button>
            <Button size="sm" variant="destructive" onClick={() => handleDelete(showDetail.id)}><Trash2 />Hapus</Button>
          </>}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Produk">{showDetail.product || '—'}{(showDetail.size || showDetail.color) ? ` · ${[showDetail.size, showDetail.color].filter(Boolean).join(' ')}` : ''}</BarisDetail>
            <BarisDetail label="SKU">{showDetail.sku || '—'}</BarisDetail>
            <BarisDetail label="Jenis">{JENIS_SAMPLE[showDetail.sample_type] || showDetail.sample_type_label || '—'}</BarisDetail>
            <BarisDetail label="Qty × HPP">{showDetail.quantity || 0} × {rp(showDetail.hpp)} = <span className="font-medium">{rp(showDetail.total_hpp)}</span></BarisDetail>
            <BarisDetail label="Ongkir">{rp(showDetail.ongkir)}</BarisDetail>
            <BarisDetail label="Kurir · resi">{KURIR[showDetail.courier] || showDetail.courier || '—'} · {showDetail.tracking_number || 'belum ada resi'}</BarisDetail>
            <BarisDetail label="Video">{showDetail.video_link
              ? <a href={showDetail.video_link} target="_blank" rel="noopener noreferrer" className="break-all text-primary hover:underline">{showDetail.video_link}</a>
              : <span className="text-[hsl(var(--warning-text))]">belum ada</span>}</BarisDetail>
            <BarisDetail label="Umur">{ageDays(showDetail.date || showDetail.created_at)} hari</BarisDetail>
            {showDetail.notes && <BarisDetail label="Catatan">{showDetail.notes}</BarisDetail>}
          </dl>
          <div className="space-y-3 border-t border-[var(--glass-border)] pt-3">
            <p className="text-sm font-medium text-foreground">Tindak lanjut</p>
            <div className="grid gap-3 sm:grid-cols-[14rem_1fr]">
              <SmartNativeSelect value={progressUpdate.progress || ''} searchable={false}
                onChange={(e) => setProgressUpdate({ ...progressUpdate, progress: e.target.value })} data-testid="sample-progress-select">
                <option value="">Pilih status</option>
                {Object.entries(PROGRESS_STATUS_CONFIG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
              </SmartNativeSelect>
              <Textarea value={progressUpdate.sales_update || ''} rows={2} placeholder="Contoh: terjual 5 pcs…"
                onChange={e => setProgressUpdate({ ...progressUpdate, sales_update: e.target.value })} />
            </div>
            <Button variant="success" onClick={handleUpdateProgress} disabled={actionLoading === showDetail.id}>
              {actionLoading === showDetail.id ? <Loader2 className="animate-spin" /> : <TrendingUp />}Simpan tindak lanjut
            </Button>
          </div>
        </DetailPopup>
      )}
    </PageLayout>
  );
}

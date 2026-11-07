/**
 * Rating & ulasan (Portal Toko) — ulasan produk dari berbagai platform, balasan, dan usulan kategori AI.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, penyaring satu baris (akun aktif kini pilihan di baris
 * penyaring, dulu bar lebar), 4 StatTile berketerangan (dulu 5 kartu), tabel + unduh Excel/CSV semua baris
 * (dulu CSV halaman ini saja), detail & form popup, tanggal = DatePicker. Tampilan "Kartu" lama diganti tabel
 * (di HP otomatis kartu ringkas). Kolom "Balasan" tetap menyebut "belum dibalas" terang-terangan (F10).
 * Perbaikan ikut: penyaring "Semua …" dulu mengirim nilai spasi ke server.
 */
import { confirmDialog } from '@/components/ui/confirm-dialog';
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Star, Plus, Pencil, Trash2, Sparkles, RefreshCw, Loader2, Search, Send } from 'lucide-react';
import axios from 'axios';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
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
import { useActiveMarketingAccount } from '@/hooks/useActiveMarketingAccount';
import { todayWIB, toWIBDate } from '@/lib/waktu';
import { formatDateID } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from '../moduleAtoms';
import { getPlatformConfig } from './AccountBadge';
import { CatalogItemSelect } from './pickers/MarketingPickers';
import AISuggestionPanel from '../AISuggestionPanel';

const API = process.env.REACT_APP_BACKEND_URL;

// Tanggal kalender WIB: 'YYYY-MM-DD' dibiarkan, instan (created_at) dibaca dalam WIB.
const fmtDate = (v) => {
  if (!v) return '—';
  const ymd = toWIBDate(v) || String(v).slice(0, 10);
  return formatDateID(ymd) || ymd;
};
const STATUS_CONFIG = {
  pending: { label: 'Belum dibalas', tone: 'warning' },
  reviewed: { label: 'Sudah dibalas', tone: 'success' },
};
const NAMA_PLATFORM = { shopee: 'Shopee', tiktok: 'TikTok', tiktokshop: 'TikTok', tokopedia: 'Tokopedia', instagram: 'Instagram', lazada: 'Lazada' };
const labelPlatform = (p) => NAMA_PLATFORM[String(p || '').toLowerCase()] || (getPlatformConfig(p).label !== 'Platform' ? getPlatformConfig(p).label
  : (p ? String(p).replace(/^./, (x) => x.toUpperCase()) : '—'));
// Label kategori dari server bergaya Judul ("Produk Tidak Sesuai Deskripsi") → huruf besar hanya di awal.
const kalimat = (s) => String(s || '').split(' ').map((w, i) => (i === 0 || /^[A-Z0-9]{2,4}$/.test(w) ? w : w.toLowerCase())).join(' ');
const StatusUlasan = ({ status }) => (status
  ? <StatusBadge status={status} label={STATUS_CONFIG[status]?.label || status} tone={STATUS_CONFIG[status]?.tone} />
  : <span className="text-muted-foreground">—</span>);

function StarRating({ rating }) {
  return (
    <span className="inline-flex items-center gap-0.5" aria-label={`${rating} bintang`} title={`${rating} bintang`}>
      {[1, 2, 3, 4, 5].map(i => (
        <Star key={i} className={`h-3.5 w-3.5 ${i <= rating ? 'fill-[hsl(var(--warning))] text-[hsl(var(--warning))]' : 'text-muted-foreground/40'}`} />
      ))}
    </span>
  );
}

/** Pilihan akun aktif di baris penyaring (pengganti bar akun selebar layar). Sumber & penyimpanan sama: hook akun aktif. */
function PilihAkun({ accounts = [], activeAccount, onChange, testId = 'pilih-akun' }) {
  const aktif = accounts.filter((a) => a.status === 'active' || !a.status);
  const daftar = activeAccount && !aktif.some((a) => a.id === activeAccount.id) ? [activeAccount, ...aktif] : aktif;
  return (
    <SmartNativeSelect value={activeAccount?.id || ''} className="w-36" data-testid={testId}
      onChange={(e) => onChange(daftar.find((a) => a.id === e.target.value) || null)}>
      <option value="">Semua toko</option>
      {daftar.map((a) => <option key={a.id} value={a.id}>{`${a.account_name} · ${labelPlatform(a.platform)}`}</option>)}
    </SmartNativeSelect>
  );
}

const EMPTY_FORM = {
  catalog_item_id: '', sku: '',
  account_id: '', account_name: '',
  date: '', order_id: '', platform: 'shopee', rating: 5, product: '',
  category: 'tanpa_keterangan', review_text: '', screenshot_url: '', response_text: ''
};

export default function RatingReviewModule({ token }) {
  const { toast } = useToast();
  const authH = useMemo(() => ({ Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` }), [token]);
  const { accounts: masterAccounts, byId: accountById } = useMarketingAccounts(token);
  const { activeAccount, setActiveAccount } = useActiveMarketingAccount();
  const [summary, setSummary] = useState(null);
  const [reviews, setReviews] = useState([]);
  const [pagination, setPagination] = useState(null);
  const [categories, setCategories] = useState([]);
  const [platforms, setPlatforms] = useState([]);

  const [loading, setLoading] = useState(true);
  const [aiLoading, setAiLoading] = useState('');

  const [filterStatus, setFilterStatus] = useState('');
  const [filterPlatform, setFilterPlatform] = useState('');
  const [filterRating, setFilterRating] = useState(0);
  const [filterCategory, setFilterCategory] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [currentPage, setCurrentPage] = useState(1);

  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [formLoading, setFormLoading] = useState(false);

  const [showDetail, setShowDetail] = useState(null);
  const [galatForm, setGalatForm] = useState('');
  const [responseText, setResponseText] = useState('');
  const [respondLoading, setRespondLoading] = useState(false);

  const fetchMeta = useCallback(async () => {
    try {
      const [catRes, platRes] = await Promise.all([
        axios.get(`${API}/api/marketing/reviews/categories`, { headers: authH }),
        axios.get(`${API}/api/marketing/reviews/platforms`, { headers: authH })
      ]);
      setCategories(catRes.data.categories || []);
      setPlatforms(platRes.data.platforms || []);
    } catch (e) {
      console.error('Meta fetch error:', e);
    }
  }, [authH]);

  const fetchSummary = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/api/marketing/reviews/summary`, { headers: authH });
      setSummary(res.data.data || {});
    } catch (e) {
      console.error('Summary fetch error:', e);
    }
  }, [authH]);

  const fetchReviews = useCallback(async (page = 1) => {
    try {
      setLoading(true);
      const params = { page, page_size: 20 };
      if (filterStatus) params.status = filterStatus;
      if (filterPlatform) params.platform = filterPlatform;
      if (filterRating > 0) params.rating = filterRating;
      if (filterCategory) params.category = filterCategory;
      if (searchQuery) params.search = searchQuery;
      if (activeAccount?.id) params.account_id = activeAccount.id;

      const res = await axios.get(`${API}/api/marketing/reviews`, { headers: authH, params });
      setReviews(res.data.data || []);
      setPagination(res.data.pagination || {});
    } catch (e) {
      console.error('Reviews fetch error:', e);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authH, filterStatus, filterPlatform, filterRating, filterCategory, searchQuery, activeAccount]);

  useEffect(() => {
    fetchMeta();
    fetchSummary();
  }, [fetchMeta, fetchSummary]);

  useEffect(() => {
    fetchReviews(currentPage);
  }, [fetchReviews, currentPage]);


  const openForm = (review = null) => {
    if (review) {
      setEditTarget(review);
      setForm({
        account_id: review.account_id || '',
        account_name: review.account_name || '',
        date: review.date,
        order_id: review.order_id,
        platform: review.platform,
        rating: review.rating,
        product: review.product,
        category: review.category,
        review_text: review.review_text,
        screenshot_url: review.screenshot_url || '',
        response_text: review.response_text || ''
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
    if (!form.account_id) {
      setGalatForm('Pilih akun / toko marketplace.');
      return;
    }
    if (!form.order_id || !(form.catalog_item_id || form.product) || !form.review_text) {
      setGalatForm('Nomor pesanan, produk, dan isi ulasan wajib diisi.');
      return;
    }
    try {
      setFormLoading(true);
      if (editTarget) {
        await axios.put(`${API}/api/marketing/reviews/${editTarget.id}`, form, { headers: authH });
        toast({ title: 'Berhasil', description: 'Ulasan disimpan.' });
      } else {
        await axios.post(`${API}/api/marketing/reviews`, form, { headers: authH });
        toast({ title: 'Berhasil', description: 'Ulasan ditambahkan.' });
      }
      closeForm();
      fetchReviews(currentPage);
      fetchSummary();
    } catch (e) {
      setGalatForm(e.response?.data?.detail || e.message);
    } finally {
      setFormLoading(false);
    }
  };

  const handleDelete = async (id) => {
    if (!(await confirmDialog({ title: 'Hapus ulasan ini?', body: 'Catatan ulasan dihapus dari daftar.', confirmLabel: 'Hapus', danger: true }))) return;
    setShowDetail(null);
    try {
      await axios.delete(`${API}/api/marketing/reviews/${id}`, { headers: authH });
      toast({ title: 'Berhasil', description: 'Ulasan dihapus.' });
      fetchReviews(currentPage);
      fetchSummary();
    } catch (e) {
      toast({ title: 'Gagal', description: e.response?.data?.detail || e.message, variant: 'destructive' });
    }
  };

  // K28 (2026-11-02): AI hanya membuat USULAN kategori; detail dibuka agar pengguna
  // menekan Terima/Ubah/Tolak (kategori resmi berubah di server saat diterima).
  const handleAICategorize = async (reviewId) => {
    try {
      setAiLoading(reviewId);
      const res = await axios.post(`${API}/api/marketing/reviews/${reviewId}/ai-categorize`, {}, { headers: authH });
      const cat = res.data.ai_suggestion?.values?.category;
      toast({ title: 'Usulan AI dibuat', description: `Usulan kategori: ${categories.find(c => c.value === cat)?.label || cat || '—'} — tinjau lalu terima, ubah, atau tolak` });
      const detailRes = await axios.get(`${API}/api/marketing/reviews/${reviewId}`, { headers: authH });
      setShowDetail(detailRes.data?.data || detailRes.data);
      fetchReviews(currentPage);
    } catch (e) {
      toast({ title: 'AI gagal', description: e.response?.data?.detail || e.message, variant: 'destructive' });
    } finally {
      setAiLoading('');
    }
  };

  const handleRespond = async () => {
    if (!responseText) {
      toast({ title: 'Balasan wajib diisi', variant: 'destructive' });
      return;
    }
    try {
      setRespondLoading(true);
      await axios.post(`${API}/api/marketing/reviews/${showDetail.id}/respond`, { response_text: responseText }, { headers: authH });
      toast({ title: 'Berhasil', description: 'Balasan terkirim.' });
      setShowDetail(null);
      setResponseText('');
      fetchReviews(currentPage);
      fetchSummary();
    } catch (e) {
      toast({ title: 'Gagal', description: e.response?.data?.detail || e.message, variant: 'destructive' });
    } finally {
      setRespondLoading(false);
    }
  };

  const clearFilters = () => {
    setFilterStatus('');
    setFilterPlatform('');
    setFilterRating(0);
    setFilterCategory('');
    setSearchQuery('');
    setCurrentPage(1);
  };

  const s = summary || {};
  const adaSaring = [filterStatus, filterPlatform, filterRating > 0, filterCategory, searchQuery, activeAccount?.id].filter(Boolean).length > 0;
  const labelKategori = (r) => kalimat(r.category_label || categories.find((c) => c.value === r.category)?.label) || '—';

  const paramSaring = () => {
    const params = {};
    if (filterStatus) params.status = filterStatus;
    if (filterPlatform) params.platform = filterPlatform;
    if (filterRating > 0) params.rating = filterRating;
    if (filterCategory) params.category = filterCategory;
    if (searchQuery) params.search = searchQuery;
    if (activeAccount?.id) params.account_id = activeAccount.id;
    return params;
  };
  /** Unduh semua ulasan hasil saringan (dulu hanya 20 baris halaman ini). */
  const ambilSemua = async () => {
    const semua = [];
    for (let p = 1; p <= 200; p += 1) {
      const res = await axios.get(`${API}/api/marketing/reviews`, { headers: authH, params: { page: p, page_size: 100, ...paramSaring() } });
      semua.push(...(res.data.data || []));
      if (p >= (res.data.pagination?.total_pages || 1)) break;
    }
    return semua;
  };

  const tombolAI = (r) => (
    <Button onClick={() => handleAICategorize(r.id)} variant="ghost" size="icon-sm" disabled={aiLoading === r.id}
      title="Minta usulan kategori AI" aria-label="Minta usulan kategori AI">
      {aiLoading === r.id ? <Loader2 className="animate-spin" /> : <Sparkles />}
    </Button>
  );

  const kolom = [
    { kunci: 'tanggal', label: 'Tanggal', hp: 'keterangan', isi: (r) => <span className="tabular-nums md:whitespace-nowrap">{fmtDate(r.date || r.created_at)}</span> },
    { kunci: 'rating', label: 'Bintang', isi: (r) => <StarRating rating={r.rating} /> },
    { kunci: 'produk', label: 'Produk / toko', hp: 'judul', isi: (r) => (
      <span className="block md:max-w-[13rem]"><span className="block truncate" title={r.product}>{r.product || '—'}</span>
        <span className="block truncate text-xs text-muted-foreground">{r.account_name || '—'} · {labelPlatform(r.platform)}</span></span>) },
    { kunci: 'ulasan', label: 'Isi ulasan', isi: (r) => <p className="line-clamp-2 md:max-w-[16rem]" title={r.review_text}>{r.review_text || '—'}</p> },
    { kunci: 'kategori', label: 'Kategori', isi: (r) => <span className="block md:max-w-[10rem]">{labelKategori(r)}</span> },
    { kunci: 'status', label: 'Balasan', isi: (r) => <StatusUlasan status={r.status} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <div className="flex justify-end gap-1">
        {tombolAI(r)}
        <Button onClick={() => openForm(r)} variant="ghost" size="icon-sm" title="Ubah ulasan" aria-label="Ubah ulasan"><Pencil /></Button>
      </div>) },
  ];

  return (
    <PageLayout testId="rating-review-module" title="Rating & ulasan"
      subtitle="Ulasan produk dari semua platform, balasan, dan kategori keluhan."
      actions={<Button onClick={() => openForm()} data-testid="reviews-create"><Plus />Tambah ulasan</Button>}
      filters={<>
        <div className="relative w-full sm:w-44">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder="Cari pesanan atau produk" value={searchQuery} className="pl-8"
            onChange={e => { setSearchQuery(e.target.value); setCurrentPage(1); }} data-testid="reviews-search" />
        </div>
        <PilihAkun accounts={masterAccounts} activeAccount={activeAccount} testId="reviews-account"
          onChange={(acc) => { setActiveAccount(acc); setCurrentPage(1); }} />
        <SmartNativeSelect value={filterStatus} onChange={(e) => { setFilterStatus(e.target.value); setCurrentPage(1); }} className="w-40" searchable={false}>
          <option value="">Semua balasan</option>
          {Object.entries(STATUS_CONFIG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={String(filterRating)} onChange={(e) => { setFilterRating(parseInt(e.target.value, 10) || 0); setCurrentPage(1); }}
          className="w-36" searchable={false}>
          <option value="0">Semua bintang</option>
          {[1, 2, 3, 4, 5].map((n) => <option key={n} value={String(n)}>{n} bintang</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={filterPlatform} onChange={(e) => { setFilterPlatform(e.target.value); setCurrentPage(1); }} className="w-40" searchable={false}>
          <option value="">Semua platform</option>
          {platforms.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={filterCategory} onChange={(e) => { setFilterCategory(e.target.value); setCurrentPage(1); }} className="w-40">
          <option value="">Semua kategori</option>
          {categories.map(c => <option key={c.value} value={c.value}>{kalimat(c.label)}</option>)}
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="rating-ulasan-toko" namaLembar="Ulasan" baris={reviews} ambilSemua={ambilSemua} testId="reviews-export-csv"
          kolom={[
            { label: 'Tanggal', nilai: (r) => fmtDate(r.date || r.created_at) },
            { label: 'Bintang', nilai: (r) => Number(r.rating) || 0 },
            { label: 'Platform', nilai: (r) => labelPlatform(r.platform) },
            { label: 'Nomor pesanan', nilai: (r) => r.order_id || '' },
            { label: 'Toko', nilai: (r) => r.account_name || '' },
            { label: 'Produk', nilai: (r) => r.product || '' },
            { label: 'Isi ulasan', nilai: (r) => r.review_text || '' },
            { label: 'Kategori', nilai: labelKategori },
            { label: 'Status', nilai: (r) => STATUS_CONFIG[r.status]?.label || r.status || '' },
            { label: 'Balasan', nilai: (r) => r.response_text || '' },
          ]} />
        <Button onClick={() => { fetchReviews(currentPage); fetchSummary(); }} variant="outline" size="icon" title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={(s.total || 0) > 0 && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="reviews-kpi">
          <StatTile label="Total ulasan" value={s.total || 0} sub={`${s.reviewed || 0} sudah dibalas`}
            hint="Semua toko yang bisa Anda lihat; tidak ikut pilihan akun & penyaring." />
          <StatTile label="Rata-rata bintang" value={String(s.avg_rating ?? 0).replace('.', ',')} suffix="/ 5"
            hint="Rata-rata bintang semua ulasan." />
          <StatTile label="Bintang rendah (1–2)" value={s.low_rating || 0} accent={(s.low_rating || 0) > 0 ? 'danger' : 'default'}
            hint="Ulasan bintang 1 atau 2." />
          <StatTile label="Belum dibalas" value={s.pending || 0} accent={(s.pending || 0) > 0 ? 'warning' : 'default'}
            hint="Ulasan yang belum diberi balasan." />
        </div>
      )}
      footer={pagination && pagination.total_pages > 1 && (
        <PaginationLite page={currentPage} totalPages={pagination.total_pages} total={pagination.total} pageSize={20}
          onPageChange={setCurrentPage} />
      )}>
      {loading && reviews.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat ulasan…</p>
      ) : (
        <TabelData kolom={kolom} baris={reviews} onKlikBaris={(r) => { setShowDetail(r); setResponseText(''); }} testId="reviews-table"
          kosong={<EmptyState title={adaSaring ? 'Tidak ada ulasan yang cocok' : 'Belum ada ulasan'}
            description={adaSaring ? 'Ubah saringan, akun, atau kata pencarian.' : 'Catat ulasan pembeli dengan tombol Tambah ulasan.'}
            action={!adaSaring && <Button onClick={() => openForm()}><Plus />Tambah ulasan</Button>} />} />
      )}

      {/* Form ulasan (popup) */}
      <FormPopup open={showForm} onClose={closeForm} ukuran="panjang" onSimpan={handleSave} menyimpan={formLoading}
        judul={editTarget ? 'Ubah ulasan' : 'Tambah ulasan'} galat={galatForm} testId="review-form">
        <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Akun / toko marketplace" wajib htmlFor="review-account"
          petunjuk={form.account_id ? `Platform: ${labelPlatform(form.platform)} (otomatis dari akun)` : undefined}>
          <SmartNativeSelect id="review-account" value={form.account_id || ''} onChange={(e) => handleAccountChange(e.target.value)}
            data-testid="review-account-select">
            <option value="">{masterAccounts.length === 0 ? 'Belum ada akun aktif' : 'Pilih akun'}</option>
            {masterAccounts.map(acc => <option key={acc.id} value={acc.id}>{`${acc.account_name} · ${labelPlatform(acc.platform)}`}</option>)}
          </SmartNativeSelect>
        </Isian>
        {/* F15 — produk DIPILIH dari katalog toko (dulu teks bebas → laporan per produk tidak bisa dijawab). */}
        <Isian label="Produk" wajib>
          <CatalogItemSelect
            token={token} accountId={form.account_id} label=""
            value={form.catalog_item_id || ''}
            onChange={(item) => setForm({
              ...form,
              catalog_item_id: item?.id || '',
              product: item?.name || '',
              sku: item?.sku || '',
            })}
            testId="review-item-select" />
        </Isian>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Tanggal">
            <DatePicker value={form.date || ''} onChange={(v) => setForm({ ...form, date: v })} testId="review-date" />
          </Isian>
          <Isian label="Nomor pesanan" wajib htmlFor="review-order">
            <Input id="review-order" value={form.order_id} onChange={e => setForm({ ...form, order_id: e.target.value })} placeholder="ORD-123456" />
          </Isian>
          <Isian label="Bintang" htmlFor="review-rating">
            <SmartNativeSelect id="review-rating" value={String(form.rating)} searchable={false}
              onChange={(e) => setForm({ ...form, rating: parseInt(e.target.value, 10) })}>
              {[1, 2, 3, 4, 5].map(r => <option key={r} value={String(r)}>{r} bintang</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Kategori" htmlFor="review-category">
            <SmartNativeSelect id="review-category" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
              {categories.map(c => <option key={c.value} value={c.value}>{kalimat(c.label)}</option>)}
            </SmartNativeSelect>
          </Isian>
        </div>
        <Isian label="Isi ulasan" wajib htmlFor="review-text">
          <Textarea id="review-text" value={form.review_text} rows={3} placeholder="Salin isi ulasan pembeli"
            onChange={e => setForm({ ...form, review_text: e.target.value })} />
        </Isian>
        <Isian label="Balasan" petunjuk="Opsional." htmlFor="review-response">
          <Textarea id="review-response" value={form.response_text} rows={3}
            onChange={e => setForm({ ...form, response_text: e.target.value })} />
        </Isian>
      </FormPopup>

      {/* Detail + balas (popup) */}
      {showDetail && (
        <DetailPopup open onClose={() => setShowDetail(null)} testId="review-detail"
          judul={showDetail.product || 'Ulasan'} status={<StatusUlasan status={showDetail.status} />}
          keterangan={`${showDetail.account_name || '—'} · ${labelPlatform(showDetail.platform)} · ${fmtDate(showDetail.date || showDetail.created_at)}`}
          aksi={<>
            <Button size="sm" variant="outline" onClick={() => handleAICategorize(showDetail.id)} disabled={aiLoading === showDetail.id}>
              {aiLoading === showDetail.id ? <Loader2 className="animate-spin" /> : <Sparkles />}Minta usulan AI
            </Button>
            <Button size="sm" variant="outline" onClick={() => { const r = showDetail; setShowDetail(null); openForm(r); }}><Pencil />Ubah</Button>
            <Button size="sm" variant="destructive" onClick={() => handleDelete(showDetail.id)}><Trash2 />Hapus</Button>
          </>}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Bintang"><StarRating rating={showDetail.rating} /></BarisDetail>
            <BarisDetail label="Nomor pesanan">{showDetail.order_id || '—'}</BarisDetail>
            <BarisDetail label="Isi ulasan"><span className="whitespace-pre-wrap">{showDetail.review_text || '—'}</span></BarisDetail>
            <BarisDetail label="Kategori resmi">{labelKategori(showDetail)}</BarisDetail>
            {showDetail.response_text && <BarisDetail label="Balasan"><span className="whitespace-pre-wrap">{showDetail.response_text}</span></BarisDetail>}
          </dl>
          {showDetail.ai_suggestion && (
            <AISuggestionPanel
              suggestion={showDetail.ai_suggestion}
              fields={[{ key: 'category', label: 'Kategori', options: categories }]}
              decideUrl={`${API}/api/marketing/reviews/${showDetail.id}/ai-suggestion`}
              headers={authH}
              testId="review-ai-suggestion"
              onDecided={async () => {
                const res = await axios.get(`${API}/api/marketing/reviews/${showDetail.id}`, { headers: authH });
                setShowDetail(res.data?.data || res.data);
                fetchReviews(currentPage);
              }}
            />
          )}
          {showDetail.status === 'pending' && (
            <div className="space-y-2 border-t border-[var(--glass-border)] pt-3">
              <label className="text-sm font-medium text-foreground" htmlFor="review-reply">Kirim balasan</label>
              <Textarea id="review-reply" value={responseText} onChange={e => setResponseText(e.target.value)} rows={3}
                placeholder="Tulis balasan untuk pembeli…" />
              <Button variant="success" onClick={handleRespond} disabled={respondLoading || !responseText}>
                {respondLoading ? <Loader2 className="animate-spin" /> : <Send />}Kirim balasan
              </Button>
            </div>
          )}
        </DetailPopup>
      )}
    </PageLayout>
  );
}

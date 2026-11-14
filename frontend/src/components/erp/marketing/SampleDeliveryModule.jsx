/**
 * Kirim sample (Portal Toko) — pengiriman sample ke kreator/KOL dan tindak lanjut hasilnya.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, penyaring satu baris, 4 StatTile berketerangan, tabel + unduh
 * Excel/CSV semua baris, detail popup berisi form tindak lanjut, form = FormPopup + DatePicker.
 *
 * 14 Nov 2026 (keputusan owner, permintaan PIC toko):
 *  • SATU kiriman = banyak produk + SATU ongkir (kreator live sering menerima sampai 6 sampel). Baris produk
 *    ditambah/dihapus di formulir; tiap baris memilih item katalog toko yang sama, HPP ikut katalog (tidak diketik).
 *    Kiriman lama (satu produk) tampil sebagai satu baris.
 *  • Status kirim (Belum dikirim / Dikirim / Sampai) dan tindak lanjut = pilihan di baris tabel, boleh kembali ke
 *    status sebelumnya (dulu tombol truk satu arah).
 *  • Kolom Gudang: stok cukup → "Menunggu gudang" sampai gudang mencatat Keluarkan stok (alasan Sampel);
 *    stok kurang → "Diproduksi · PO-…" (draf PO Sampel R&D otomatis). Server: `core.kirim_sampel`.
 */
import { confirmDialog } from '@/components/ui/confirm-dialog';
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Plus, Pencil, Trash2, RefreshCw, Loader2, Video, Search, TrendingUp, X } from 'lucide-react';
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
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';
import { getPlatformConfig } from './AccountBadge';
import {
  MarketingAccountSelect, MarketingCreatorSelect, useCatalogItems, catalogItemLabel,
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
// rupiah utuh — HPP rata-rata bisa berdesimal (mis. 55.497,25); layar menampilkan rupiah bulat
const rp = (n) => `Rp ${Math.round(Number(n) || 0).toLocaleString('id-ID')}`;
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
// Status gudang per baris produk (server: core.kirim_sampel.hitung_baris)
const GUDANG_TONE = {
  menunggu_gudang: 'warning', keluar_sebagian: 'warning', sudah_keluar: 'success', diproduksi: 'info',
  perlu_po_manual: 'danger',
};
const JENIS_SAMPLE = { live: 'Live streaming', video: 'Video ulasan' };
const KURIR = { jnt: 'J&T', spx: 'SPX', sicepat: 'SiCepat' };
const NAMA_PLATFORM = { shopee: 'Shopee', tiktok: 'TikTok', tiktokshop: 'TikTok', tokopedia: 'Tokopedia', instagram: 'Instagram', lazada: 'Lazada' };
const labelPlatform = (p) => NAMA_PLATFORM[String(p || '').toLowerCase()] || (getPlatformConfig(p).label !== 'Platform' ? getPlatformConfig(p).label
  : (p ? String(p).replace(/^./, (x) => x.toUpperCase()) : '—'));
const Lencana = ({ peta, nilai }) => (nilai
  ? <StatusBadge status={nilai} label={peta[nilai]?.label || nilai} tone={peta[nilai]?.tone} />
  : <span className="text-muted-foreground">—</span>);
const LencanaGudang = ({ baris }) => (baris.status_gudang
  ? <StatusBadge status={baris.status_gudang} label={baris.status_gudang_label} tone={GUDANG_TONE[baris.status_gudang] || 'muted'} />
  : <span className="text-xs text-muted-foreground">{baris.status_gudang_label || '—'}</span>);

let urutBaris = 0;
const barisKosong = () => ({ key: `b${(urutBaris += 1)}`, catalog_item_id: '', size: '', color: '', quantity: 1 });
const EMPTY_FORM = {
  account_id: '', account_name: '', platform: 'tiktok', date: '', creator_id: '', sample_type: 'live',
  courier: 'jnt', ongkir: 0, tracking_number: '', video_link: '', notes: '', lines: [],
};
const ringkasProduk = (x) => {
  const ls = x.lines || [];
  if (!ls.length) return x.product || '—';
  return ls.length > 1 ? `${ls[0].product || ls[0].sku} + ${ls.length - 1} produk lain` : (ls[0].product || ls[0].sku || '—');
};
// Baris yang sudah keluar gudang / sudah dibuatkan draf PO sampel: produk & jumlahnya terkunci (server menolak).
const barisTerkunci = (b) => Number(b.qty_keluar || 0) > 0 || !!b.po_number;

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
  // F14 — filter per TOKO (biaya sample per toko).
  const [filterAccountId, setFilterAccountId] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [currentPage, setCurrentPage] = useState(1);

  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [formLoading, setFormLoading] = useState(false);
  const [galatForm, setGalatForm] = useState('');
  // Katalog toko yang dipilih — dimuat SEKALI untuk semua baris produk.
  const { items: katalog, loading: katalogMemuat } = useCatalogItems(token, form.account_id);
  const itemById = useMemo(() => Object.fromEntries(katalog.map((i) => [i.id, i])), [katalog]);

  const [showDetail, setShowDetail] = useState(null);
  const [progressUpdate, setProgressUpdate] = useState({ progress: '', sales_update: '' });
  const [actionLoading, setActionLoading] = useState('');

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
        platform: sample.platform || 'tiktok',
        date: sample.date,
        creator_id: sample.creator_id || '',
        sample_type: sample.sample_type || 'live',
        courier: sample.courier || 'jnt',
        ongkir: sample.ongkir || 0,
        tracking_number: sample.tracking_number || '',
        video_link: sample.video_link || '',
        notes: sample.notes || '',
        lines: (sample.lines || []).map((b) => ({ ...b, key: b.id })),
      });
    } else {
      setEditTarget(null);
      setForm({ ...EMPTY_FORM, date: todayWIB(), lines: [barisKosong()] });
    }
    setGalatForm('');
    setShowForm(true);
  };

  // Ganti toko: platform ikut master; baris produk dikosongkan (katalog toko lain tidak berlaku).
  const handleAccountChange = (accountId) => {
    const acc = accountById[accountId];
    setForm(f => ({
      ...f,
      account_id: accountId,
      account_name: acc?.account_name || acc?.name || '',
      platform: acc?.platform || f.platform,
      creator_id: accountId === f.account_id ? f.creator_id : '',
      lines: accountId === f.account_id ? f.lines : f.lines.filter(barisTerkunci).concat(f.lines.some(barisTerkunci) ? [] : [barisKosong()]),
    }));
  };

  const ubahBaris = (key, patch) => setForm((f) => ({ ...f, lines: f.lines.map((b) => (b.key === key ? { ...b, ...patch } : b)) }));
  const pilihProduk = (key, id) => {
    const it = itemById[id];
    ubahBaris(key, { catalog_item_id: id, sku: it?.sku || '', product: it?.name || '', hpp: Number(it?.hpp || 0),
      size: (it?.sizes && it.sizes[0]) || '', color: (it?.colors && it.colors[0]) || '' });
  };
  const tambahBaris = () => setForm((f) => ({ ...f, lines: [...f.lines, barisKosong()] }));
  const hapusBaris = (key) => setForm((f) => ({ ...f, lines: f.lines.filter((b) => b.key !== key) }));
  const hppBaris = (b) => (b.catalog_item_id && itemById[b.catalog_item_id] ? Number(itemById[b.catalog_item_id].hpp || 0) : Number(b.hpp || 0));
  const totalHpp = form.lines.reduce((a, b) => a + hppBaris(b) * (Number(b.quantity) || 0), 0);
  const totalPcs = form.lines.reduce((a, b) => a + (Number(b.quantity) || 0), 0);
  const adaIsian = form.lines.some((b) => b.catalog_item_id) || !!form.creator_id;

  const closeForm = () => {
    setShowForm(false);
    setEditTarget(null);
    setForm(EMPTY_FORM);
  };

  const ringkasHasil = (data) => {
    const ls = data?.lines || [];
    const n = (st) => ls.filter((b) => b.status_gudang === st).length;
    const po = [...new Set(ls.map((b) => b.po_number).filter(Boolean))];
    const bagian = [];
    if (n('menunggu_gudang') + n('keluar_sebagian')) bagian.push(`${n('menunggu_gudang') + n('keluar_sebagian')} produk menunggu gudang`);
    if (po.length) bagian.push(`${n('diproduksi')} produk dibuatkan draf PO sampel ${po.join(', ')}`);
    if (n('perlu_po_manual')) bagian.push(`${n('perlu_po_manual')} produk perlu PO manual`);
    return bagian.join(' · ');
  };

  const handleSave = async () => {
    setGalatForm('');
    // F14/F15 — toko, kreator, dan produk katalog WAJIB dipilih dari master.
    if (!form.account_id) {
      setGalatForm('Toko belum dipilih — sample harus menempel pada satu toko.');
      return;
    }
    if (!form.creator_id) {
      setGalatForm('Kreator belum dipilih — pilih kreator yang ditugaskan ke toko ini.');
      return;
    }
    const lines = form.lines.filter((b) => b.catalog_item_id || b.product);
    if (!lines.length) {
      setGalatForm('Produk belum dipilih — pilih minimal satu produk dari katalog toko.');
      return;
    }
    if (lines.some((b) => !(Number(b.quantity) >= 1))) {
      setGalatForm('Jumlah setiap produk minimal 1 pcs.');
      return;
    }
    const ids = lines.map((b) => b.catalog_item_id).filter(Boolean);
    if (new Set(ids).size !== ids.length) {
      setGalatForm('Ada produk yang dipilih dua kali — gabungkan jumlahnya.');
      return;
    }
    const { account_name: _an, lines: _l, ...rest } = form;
    const payload = {
      ...rest,
      ongkir: Number(form.ongkir) || 0,
      lines: lines.map((b) => ({ id: b.id, catalog_item_id: b.catalog_item_id || undefined, size: b.size || '',
        color: b.color || '', quantity: Number(b.quantity), product: b.catalog_item_id ? undefined : b.product,
        sku: b.catalog_item_id ? undefined : b.sku, hpp: b.catalog_item_id ? undefined : b.hpp })),
    };
    try {
      setFormLoading(true);
      const res = editTarget
        ? await axios.put(`${API}/api/marketing/samples/${editTarget.id}`, payload, { headers: authH })
        : await axios.post(`${API}/api/marketing/samples`, payload, { headers: authH });
      toast({ title: editTarget ? 'Kiriman sampel disimpan' : 'Kiriman sampel ditambahkan', description: ringkasHasil(res.data?.data) || undefined });
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
    if (!(await confirmDialog({ title: 'Hapus kiriman sampel ini?', body: 'Catatan pengiriman sampel dihapus dari daftar.', confirmLabel: 'Hapus', danger: true }))) return;
    try {
      await axios.delete(`${API}/api/marketing/samples/${id}`, { headers: authH });
      setShowDetail(null);
      toast({ title: 'Berhasil', description: 'Kiriman sampel dihapus.' });
      fetchSamples(currentPage);
      fetchSummary();
    } catch (e) {
      toast({ title: 'Gagal', description: e.response?.data?.detail || e.message, variant: 'destructive' });
    }
  };

  // Status kirim / tindak lanjut: pilihan bebas maju-mundur (PUT /status).
  const ubahStatus = async (smp, patch) => {
    try {
      setActionLoading(smp.id);
      const res = await axios.put(`${API}/api/marketing/samples/${smp.id}/status`, patch, { headers: authH });
      const baru = res.data?.data;
      if (baru) {
        setSamples((xs) => xs.map((x) => (x.id === baru.id ? baru : x)));
        setShowDetail((d) => (d && d.id === baru.id ? baru : d));
      }
      fetchSummary();
      return true;
    } catch (e) {
      toast({ title: 'Gagal', description: e.response?.data?.detail || e.message, variant: 'destructive' });
      return false;
    } finally {
      setActionLoading('');
    }
  };

  const handleUpdateProgress = async () => {
    if (!progressUpdate.progress) {
      toast({ title: 'Pilih status tindak lanjut', variant: 'destructive' });
      return;
    }
    if (await ubahStatus(showDetail, progressUpdate)) toast({ title: 'Berhasil', description: 'Tindak lanjut disimpan.' });
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

  // Pilihan status di baris tabel — klik tidak membuka detail baris. Fungsi (bukan komponen) supaya pilihan
  // tidak dipasang ulang setiap layar digambar ulang.
  const pilihStatus = (smp, field, peta, testId) => (
    <div onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()} role="presentation">
      <SmartNativeSelect value={smp[field] || ''} searchable={false} className="h-8 w-full text-sm" wrapperClassName="w-40 max-w-full"
        aria-label={field === 'shipment_status' ? 'Status kirim' : 'Tindak lanjut'} data-testid={`${testId}-${smp.id}`}
        disabled={actionLoading === smp.id}
        onChange={(e) => { if (e.target.value && e.target.value !== smp[field]) ubahStatus(smp, { [field]: e.target.value }); }}>
        {!peta[smp[field]] && <option value={smp[field] || ''}>{smp[field] || 'Pilih'}</option>}
        {Object.entries(peta).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
      </SmartNativeSelect>
    </div>
  );

  const kolom = [
    { kunci: 'tanggal', label: 'Tanggal', hp: 'keterangan', isi: (x) => (
      <span className="tabular-nums md:whitespace-nowrap">{fmtDate(x.date || x.created_at)}
        <span className="block text-xs text-muted-foreground">{ageDays(x.date || x.created_at)} hari lalu</span></span>) },
    { kunci: 'kreator', label: 'Kreator', hp: 'judul', isi: (x) => (
      <span className="md:whitespace-nowrap"><span className="font-medium text-foreground">{x.username || '—'}</span>
        <span className="block text-xs text-muted-foreground">{x.account_name || '—'} · {JENIS_SAMPLE[x.sample_type] || x.sample_type_label || '—'}</span></span>) },
    { kunci: 'produk', label: 'Produk', isi: (x) => (
      <p className="md:max-w-[14rem] md:truncate" title={(x.lines || []).map((b) => `${b.sku || b.product} ×${b.quantity}`).join(', ')}>{ringkasProduk(x)}
        <span className="block text-xs text-muted-foreground">{x.total_qty || x.quantity || 0} pcs</span></p>) },
    { kunci: 'hpp', label: 'HPP + ongkir (Rp)', rata: 'kanan', isi: (x) => (
      <span className="tabular-nums font-medium">{Math.round(Number(x.biaya_total) || 0).toLocaleString('id-ID')}
        <span className="block text-xs font-normal text-muted-foreground">ongkir {Math.round(Number(x.ongkir) || 0).toLocaleString('id-ID')}</span></span>) },
    { kunci: 'gudang', label: 'Gudang', isi: (x) => (
      <span className="text-xs md:max-w-[11rem] md:whitespace-normal">{x.ringkas_gudang || <span className="text-muted-foreground">—</span>}</span>) },
    { kunci: 'kirim', label: 'Status kirim', isi: (x) => pilihStatus(x, 'shipment_status', SHIPMENT_STATUS_CONFIG, 'sample-ship-select') },
    { kunci: 'progres', label: 'Tindak lanjut · video', isi: (x) => (
      <span className="flex flex-col items-start gap-1">{pilihStatus(x, 'progress', PROGRESS_STATUS_CONFIG, 'sample-progress-row')}
        {x.video_link ? (
          <a href={x.video_link} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}
            className="inline-flex items-center gap-1 text-xs text-primary hover:underline"><Video className="h-3.5 w-3.5" />Buka video</a>
        ) : <span className="text-xs text-[hsl(var(--warning-text))]">Video belum ada</span>}</span>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (x) => (
      <div className="flex justify-end gap-1">
        <Button onClick={(e) => { e.stopPropagation(); openForm(x); }} variant="ghost" size="icon-sm" title="Ubah kiriman" aria-label="Ubah kiriman"><Pencil /></Button>
      </div>) },
  ];

  const kolomBaris = [
    { kunci: 'produk', label: 'Produk', hp: 'judul', isi: (b) => (
      <span><span className="font-medium text-foreground">{b.product || '—'}</span>
        <span className="block text-xs text-muted-foreground">{[b.sku, b.size, b.color].filter(Boolean).join(' · ') || '—'}</span></span>) },
    { kunci: 'qty', label: 'Qty', rata: 'kanan', isi: (b) => <span className="tabular-nums">{b.quantity || 0}</span> },
    { kunci: 'hpp', label: 'HPP (Rp)', rata: 'kanan', isi: (b) => (
      <span className="tabular-nums">{Math.round(Number(b.total_hpp) || 0).toLocaleString('id-ID')}
        <span className="block text-xs text-muted-foreground">{Math.round(Number(b.hpp) || 0).toLocaleString('id-ID')}/pcs</span></span>) },
    { kunci: 'gudang', label: 'Gudang', isi: (b) => (
      <span className="flex flex-col items-start gap-1"><LencanaGudang baris={b} />
        {b.keterangan_gudang && <span className="text-xs text-muted-foreground">{b.keterangan_gudang}</span>}
        {(b.barang_keluar || []).length > 0 && (
          <span className="text-xs text-muted-foreground">{b.barang_keluar.map((k) => `${k.issue_number || 'Keluar'} · ${k.qty} pcs`).join(', ')}</span>
        )}</span>) },
  ];

  return (
    <PageLayout testId="sample-delivery-module" title="Kirim sample"
      subtitle="Pengiriman sample ke kreator/KOL, biaya HPP + ongkir, dan hasil tindak lanjutnya."
      actions={<Button onClick={() => openForm()} data-testid="sample-create"><Plus />Tambah kiriman</Button>}
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
        <SmartNativeSelect value={filterShipmentStatus} onChange={(e) => { setFilterShipmentStatus(e.target.value); setCurrentPage(1); }} className="w-full" wrapperClassName="w-44 max-w-full" searchable={false}>
          <option value="">Semua status kirim</option>
          {Object.entries(SHIPMENT_STATUS_CONFIG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={filterProgress} onChange={(e) => { setFilterProgress(e.target.value); setCurrentPage(1); }} className="w-full" wrapperClassName="w-48 max-w-full" searchable={false}>
          <option value="">Semua tindak lanjut</option>
          {Object.entries(PROGRESS_STATUS_CONFIG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={filterPlatform} onChange={(e) => { setFilterPlatform(e.target.value); setCurrentPage(1); }} className="w-full" wrapperClassName="w-40 max-w-full" searchable={false}>
          <option value="">Semua platform</option>
          <option value="tiktok">TikTok</option>
          <option value="instagram">Instagram</option>
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="kirim-sample-kreator" namaLembar="Sample" baris={samples} ambilSemua={ambilSemua} testId="sample-export-csv"
          kolom={[
            { label: 'Kode kiriman', nilai: (x) => x.sample_code || '' },
            { label: 'Tanggal', nilai: (x) => fmtDate(x.date || x.created_at) },
            { label: 'Toko', nilai: (x) => x.account_name || '' },
            { label: 'Platform', nilai: (x) => labelPlatform(x.platform) },
            { label: 'Kreator', nilai: (x) => x.username || '' },
            { label: 'Jenis', nilai: (x) => JENIS_SAMPLE[x.sample_type] || x.sample_type_label || '' },
            { label: 'Produk', nilai: (x) => (x.lines || []).map((b) => `${b.sku || b.product} ${[b.size, b.color].filter(Boolean).join(' ')} ×${b.quantity}`.trim()).join('; ') },
            { label: 'Jumlah produk', nilai: (x) => (x.lines || []).length },
            { label: 'Qty', nilai: (x) => Number(x.total_qty || x.quantity) || 0 },
            { label: 'Total HPP', nilai: (x) => Number(x.total_hpp) || 0 },
            { label: 'Ongkir', nilai: (x) => Number(x.ongkir) || 0 },
            { label: 'HPP + ongkir', nilai: (x) => Number(x.biaya_total) || 0 },
            { label: 'Kurir', nilai: (x) => KURIR[x.courier] || x.courier || '' },
            { label: 'Resi', nilai: (x) => x.tracking_number || '' },
            { label: 'Gudang', nilai: (x) => x.ringkas_gudang || '' },
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
          <StatTile label="Total kiriman" value={s.total || 0}
            sub={`${s.pending || 0} belum dikirim · ${s.shipped || 0} dikirim · ${s.delivered || 0} sampai`}
            hint={filterAccountId ? 'Toko terpilih; tidak ikut penyaring lain.' : 'Semua toko; tidak ikut penyaring status.'} />
          <StatTile label="Belum dikirim" value={s.pending || 0} accent={(s.pending || 0) > 0 ? 'warning' : 'default'}
            hint="Kiriman berstatus Belum dikirim." />
          <StatTile label="Terjual" value={s.sold || 0} accent="success"
            sub={`${s.follow_up || 0} ditindaklanjuti · ${s.no_response || 0} tanpa respons`}
            hint="Kiriman dengan tindak lanjut 'Terjual'." />
          <StatTile label="Biaya sample" value={formatRupiahShort(s.total_investment || 0)}
            sub={`HPP ${formatRupiahShort(s.total_hpp || 0)} + ongkir ${formatRupiahShort(s.total_ongkir || 0)}`}
            hint={`${rp(s.total_investment)} — jumlah HPP semua produk + ongkir semua kiriman.`} />
        </div>
      )}
      footer={pagination && pagination.total_pages > 1 && (
        <PaginationLite page={currentPage} totalPages={pagination.total_pages} total={pagination.total} pageSize={20}
          onPageChange={setCurrentPage} />
      )}>
      {loading && samples.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat kiriman sampel…</p>
      ) : (
        <TabelData kolom={kolom} baris={samples} onKlikBaris={bukaDetail} testId="sample-table"
          kosong={<EmptyState title={adaSaring ? 'Tidak ada kiriman yang cocok' : 'Belum ada kiriman sampel'}
            description={adaSaring ? 'Ubah saringan atau kata pencarian.' : 'Catat sampel yang dikirim ke kreator dengan tombol Tambah kiriman.'}
            action={!adaSaring && <Button onClick={() => openForm()}><Plus />Tambah kiriman</Button>} />} />
      )}

      {/* Form kiriman (popup) — banyak produk, satu ongkir */}
      <FormPopup open={showForm} onClose={closeForm} ukuran="panjang" onSimpan={handleSave} menyimpan={formLoading}
        judul={editTarget ? `Ubah kiriman ${editTarget.sample_code || ''}`.trim() : 'Tambah kiriman sampel'} galat={galatForm}
        adaIsian={adaIsian} testId="sample-form"
        keterangan="Satu kiriman boleh berisi beberapa produk dengan satu ongkir.">
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Akun / toko marketplace" wajib htmlFor="sample-account"
            petunjuk={form.account_id ? `Platform: ${labelPlatform(form.platform)} (otomatis dari akun)` : 'Toko asal sampel.'}>
            <SmartNativeSelect id="sample-account" value={form.account_id || ''} onChange={(e) => handleAccountChange(e.target.value)}
              data-testid="sample-account-select">
              <option value="">{masterAccounts.length === 0 ? 'Belum ada akun aktif' : 'Pilih akun'}</option>
              {masterAccounts.map(acc => <option key={acc.id} value={acc.id}>{`${acc.account_name} · ${labelPlatform(acc.platform)}`}</option>)}
            </SmartNativeSelect>
          </Isian>
          {/* F15 — kreator dipilih dari master yang DI-ASSIGN ke toko ini; `username` diisi server. */}
          <Isian label="Kreator / KOL" wajib>
            <MarketingCreatorSelect token={token} accountId={form.account_id} label=""
              value={form.creator_id || ''} onChange={(v) => setForm({ ...form, creator_id: v })} testId="sample-creator-select" />
          </Isian>
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          <Isian label="Tanggal kirim">
            <DatePicker value={form.date || ''} onChange={(v) => setForm({ ...form, date: v })} testId="sample-date" />
          </Isian>
          <Isian label="Jenis" htmlFor="sample-type">
            <SmartNativeSelect id="sample-type" value={form.sample_type} searchable={false} onChange={(e) => setForm({ ...form, sample_type: e.target.value })}>
              {Object.entries(JENIS_SAMPLE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Kurir" htmlFor="sample-courier">
            <SmartNativeSelect id="sample-courier" value={form.courier} searchable={false} onChange={(e) => setForm({ ...form, courier: e.target.value })}>
              {Object.entries(KURIR).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </SmartNativeSelect>
          </Isian>
        </div>

        {/* Produk — satu baris per item katalog; HPP dari katalog (tidak diketik) */}
        <Isian label="Produk" wajib
          petunjuk={form.account_id ? 'HPP ikut katalog — ubah di Manajemen Katalog bila salah.' : 'Pilih toko dulu.'}>
          <div className="space-y-3" data-testid="sample-lines">
            {form.lines.map((b, idx) => {
              const it = itemById[b.catalog_item_id];
              const kunci = barisTerkunci(b);
              const hpp = hppBaris(b);
              return (
                <div key={b.key} className="space-y-1.5" data-testid={`sample-line-${idx}`}>
                  <div className="grid grid-cols-[minmax(0,1fr)_5rem_auto] items-start gap-2">
                    {b.catalog_item_id || !b.product ? (
                      <SmartNativeSelect value={b.catalog_item_id || ''} searchable={true} disabled={!form.account_id || kunci}
                        onChange={(e) => pilihProduk(b.key, e.target.value)} aria-label={`Produk ${idx + 1}`}
                        data-testid={`sample-line-item-${idx}`}>
                        <option value="">{!form.account_id ? 'Pilih toko dulu' : katalogMemuat ? 'Memuat katalog…' : 'Pilih produk'}</option>
                        {b.catalog_item_id && !it && <option value={b.catalog_item_id}>{[b.sku, b.product].filter(Boolean).join(' · ')}</option>}
                        {katalog.map((i) => <option key={i.id} value={i.id}>{catalogItemLabel(i)}</option>)}
                      </SmartNativeSelect>
                    ) : (
                      <p className="flex h-9 items-center text-sm">{b.product}<span className="ml-1 text-xs text-muted-foreground">(tanpa katalog)</span></p>
                    )}
                    <Input type="number" min="1" inputMode="numeric" value={b.quantity} disabled={kunci} aria-label={`Jumlah produk ${idx + 1}`}
                      className="text-right" data-testid={`sample-line-qty-${idx}`}
                      onChange={(e) => ubahBaris(b.key, { quantity: e.target.value === '' ? '' : parseInt(e.target.value, 10) })} />
                    <Button type="button" variant="outline" size="icon" onClick={() => hapusBaris(b.key)}
                      disabled={kunci || form.lines.length <= 1} aria-label={`Hapus produk ${idx + 1}`} title="Hapus produk"
                      data-testid={`sample-line-remove-${idx}`}><X /></Button>
                  </div>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                    {(it?.sizes || []).length > 1 ? (
                      <SmartNativeSelect value={b.size || ''} searchable={false} className="h-8 text-xs" wrapperClassName="w-32"
                        aria-label="Ukuran" disabled={kunci} onChange={(e) => ubahBaris(b.key, { size: e.target.value })}>
                        {it.sizes.map((sz) => <option key={sz} value={sz}>{sz}</option>)}
                      </SmartNativeSelect>
                    ) : null}
                    {(it?.colors || []).length > 1 ? (
                      <SmartNativeSelect value={b.color || ''} searchable={false} className="h-8 text-xs" wrapperClassName="w-32"
                        aria-label="Warna" disabled={kunci} onChange={(e) => ubahBaris(b.key, { color: e.target.value })}>
                        {it.colors.map((c) => <option key={c} value={c}>{c}</option>)}
                      </SmartNativeSelect>
                    ) : null}
                    {(b.catalog_item_id || b.product) && (
                      <span className="tabular-nums" data-testid={`sample-line-hpp-${idx}`}>
                        {[b.size, b.color].filter(Boolean).join(' · ')}{(b.size || b.color) ? ' · ' : ''}HPP {rp(hpp)}/pcs · {rp(hpp * (Number(b.quantity) || 0))}
                      </span>
                    )}
                    {b.status_gudang_label && <LencanaGudang baris={b} />}
                  </div>
                  {kunci && (
                    <p className="text-xs text-muted-foreground">Sudah keluar gudang atau sudah ber-PO sampel — produk dan jumlahnya tidak bisa diubah.</p>
                  )}
                </div>
              );
            })}
            <Button type="button" variant="outline" size="sm" onClick={tambahBaris} disabled={!form.account_id || form.lines.length >= 20}
              data-testid="sample-line-add"><Plus />Tambah produk</Button>
          </div>
        </Isian>

        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Ongkir (satu kiriman)">
            <MoneyInput value={form.ongkir} onChange={e => setForm({ ...form, ongkir: parseFloat(e.target.value) || 0 })} data-testid="sample-ongkir" />
          </Isian>
          <Isian label="No. resi" htmlFor="sample-resi" petunjuk="Opsional">
            <Input id="sample-resi" value={form.tracking_number} onChange={e => setForm({ ...form, tracking_number: e.target.value })} />
          </Isian>
        </div>
        <p className="text-sm tabular-nums" data-testid="sample-form-total">
          {form.lines.filter((b) => b.catalog_item_id || b.product).length} produk · {totalPcs} pcs · HPP {rp(totalHpp)} + ongkir {rp(form.ongkir)} = <span className="font-medium">{rp(totalHpp + (Number(form.ongkir) || 0))}</span>
        </p>
        <Notice tone="info" testId="sample-form-stok-note">
          Stok tiap produk diperiksa saat disimpan: stok cukup → menunggu gudang mengeluarkan (Keluarkan stok, alasan Sampel);
          stok kurang → draf PO produksi berlabel Sampel R&D dibuat otomatis.
        </Notice>
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
          judul={`Kiriman ${showDetail.sample_code || ''} untuk ${showDetail.username || 'kreator'}`}
          status={<><Lencana peta={SHIPMENT_STATUS_CONFIG} nilai={showDetail.shipment_status} />
            <Lencana peta={PROGRESS_STATUS_CONFIG} nilai={showDetail.progress} /></>}
          keterangan={`${showDetail.account_name || '—'} · ${labelPlatform(showDetail.platform)} · ${fmtDate(showDetail.date || showDetail.created_at)}`}
          aksi={<>
            {pilihStatus(showDetail, 'shipment_status', SHIPMENT_STATUS_CONFIG, 'sample-detail-ship')}
            <Button size="sm" variant="outline" onClick={() => { const r = showDetail; setShowDetail(null); openForm(r); }}><Pencil />Ubah</Button>
            <Button size="sm" variant="destructive" onClick={() => handleDelete(showDetail.id)}><Trash2 />Hapus</Button>
          </>}>
          <TabelData kolom={kolomBaris} baris={showDetail.lines || []} testId="sample-detail-lines"
            kosong={<EmptyState title="Belum ada produk" />} />
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Jenis">{JENIS_SAMPLE[showDetail.sample_type] || showDetail.sample_type_label || '—'}</BarisDetail>
            <BarisDetail label="Biaya">{rp(showDetail.total_hpp)} HPP + {rp(showDetail.ongkir)} ongkir = <span className="font-medium">{rp(showDetail.biaya_total)}</span></BarisDetail>
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

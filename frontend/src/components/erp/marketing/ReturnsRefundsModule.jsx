/**
 * Refund & nota kredit (tab di Komplain & Retur, Portal Toko) — retur dari marketplace sisi Toko/Marketing.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout (judul disembunyikan di hub), penyaring satu baris (akun aktif
 * kini pilihan di baris penyaring), 4 StatTile berketerangan, tabel 8 kolom + unduh semua baris (kolom lain di popup
 * detail & berkas unduhan), detail popup, form = FormPopup panjang, tanggal = DatePicker. Tampilan "Kartu" lama
 * diganti tabel (di HP otomatis kartu ringkas). Handler simpan/setujui/tolak/selesaikan/gudang tidak berubah.
 * Perbaikan ikut: penyaring "Semua …" dulu mengirim nilai spasi ke server.
 *
 * 14 Nov 2026 — form "Buat refund" WAJIB memilih pesanan yang sudah diimpor (sama dengan Gudang › Retur Fisik ›
 * Catat retur): lihat `FormRefundPesanan.jsx`. Detail menampilkan resi, baris pesanan, dan barang master.
 */
import { confirmDialog } from '@/components/ui/confirm-dialog';
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Plus, Pencil, Trash2, RefreshCw, CheckCircle2, Loader2, ThumbsUp, ThumbsDown, Warehouse, FileText, AlertCircle, Search,
} from 'lucide-react';
import axios from 'axios';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import PaginationLite from '@/components/ui/pagination-lite';
import { useToast } from '@/hooks/use-toast';
import { useMarketingAccounts } from '@/hooks/useMarketingAccounts';
import { useActiveMarketingAccount } from '@/hooks/useActiveMarketingAccount';
import { toWIBDate } from '@/lib/waktu';
import { formatDateID } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';
import { getPlatformConfig } from './AccountBadge';
import FormRefundPesanan, { REFUND_TYPE } from './FormRefundPesanan';

const API = process.env.REACT_APP_BACKEND_URL;

// Tanggal kalender WIB: 'YYYY-MM-DD' dibiarkan, instan (created_at) dibaca dalam WIB.
const fmtDate = (v) => {
  if (!v) return '—';
  const ymd = toWIBDate(v) || String(v).slice(0, 10);
  return formatDateID(ymd) || ymd;
};
const rp = (n) => `Rp ${(Number(n) || 0).toLocaleString('id-ID')}`;
const STATUS_CONFIG = {
  pending: { label: 'Menunggu', tone: 'warning' },
  approved: { label: 'Disetujui', tone: 'info' },
  completed: { label: 'Selesai', tone: 'success' },
  rejected: { label: 'Ditolak', tone: 'danger' },
};
const NAMA_PLATFORM = { shopee: 'Shopee', tiktok: 'TikTok', tiktokshop: 'TikTok', tokopedia: 'Tokopedia', instagram: 'Instagram', lazada: 'Lazada' };
// Label alasan dari server bergaya Judul ("Warna Berbeda dari Gambar") → huruf besar hanya di awal.
const kalimat = (t) => String(t || '').split(' ').map((w, i) => (i === 0 || /^[A-Z0-9]{2,4}$/.test(w) ? w : w.toLowerCase())).join(' ');
const labelPlatform = (p) => NAMA_PLATFORM[String(p || '').toLowerCase()] || ((getPlatformConfig(p).label !== 'Platform' ? getPlatformConfig(p).label
  : (p ? String(p).replace(/^./, (x) => x.toUpperCase()) : '—')));
// Status Retur Fisik gudang (nilai tersimpan berbahasa Inggris) → kata staf.
const STATUS_GUDANG = { Pending: 'menunggu paket', Received: 'diterima', Inspected: 'diinspeksi', Resolved: 'selesai',
  Cancelled: 'dibatalkan', Reversed: 'keputusan dibalik' };
const statusGudang = (s) => STATUS_GUDANG[s] || s || 'menunggu paket';
const StatusRetur = ({ status }) => (status
  ? <StatusBadge status={status} label={STATUS_CONFIG[status]?.label || status} tone={STATUS_CONFIG[status]?.tone} />
  : <span className="text-muted-foreground">—</span>);

/** Pilihan akun aktif di baris penyaring (pengganti bar akun selebar layar). Sumber & penyimpanan sama: hook akun aktif. */
function PilihAkun({ accounts = [], activeAccount, onChange, testId = 'pilih-akun' }) {
  const aktif = accounts.filter((a) => a.status === 'active' || !a.status);
  const daftar = activeAccount && !aktif.some((a) => a.id === activeAccount.id) ? [activeAccount, ...aktif] : aktif;
  return (
    <SmartNativeSelect value={activeAccount?.id || ''} className="w-full" wrapperClassName="w-36 max-w-full" data-testid={testId}
      onChange={(e) => onChange(daftar.find((a) => a.id === e.target.value) || null)}>
      <option value="">Semua toko</option>
      {daftar.map((a) => <option key={a.id} value={a.id}>{`${a.account_name} · ${labelPlatform(a.platform)}`}</option>)}
    </SmartNativeSelect>
  );
}

export default function ReturnsRefundsModule({ token, onNavigate }) {
  const { toast } = useToast();
  const authH = useMemo(() => ({ Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` }), [token]);
  const { accounts: masterAccounts } = useMarketingAccounts(token);
  const { activeAccount, setActiveAccount } = useActiveMarketingAccount();
  const [summary, setSummary] = useState(null);
  const [returns, setReturns] = useState([]);
  const [pagination, setPagination] = useState(null);
  const [reasons, setReasons] = useState([]);

  const [loading, setLoading] = useState(true);

  const [filterStatus, setFilterStatus] = useState('');
  const [filterPlatform, setFilterPlatform] = useState('');
  const [filterReason, setFilterReason] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [currentPage, setCurrentPage] = useState(1);

  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);

  const [showDetail, setShowDetail] = useState(null);
  const [actionLoading, setActionLoading] = useState('');

  const fetchReasons = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/api/marketing/returns/reasons`, { headers: authH });
      setReasons(res.data.reasons || []);
    } catch (e) {
      console.error('Reasons fetch error:', e);
    }
  }, [authH]);

  const fetchSummary = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/api/marketing/returns/summary`, { headers: authH });
      setSummary(res.data.data || {});
    } catch (e) {
      console.error('Summary fetch error:', e);
    }
  }, [authH]);

  const fetchReturns = useCallback(async (page = 1) => {
    try {
      setLoading(true);
      const params = { page, page_size: 20 };
      if (filterStatus) params.status = filterStatus;
      if (filterPlatform) params.platform = filterPlatform;
      if (filterReason) params.reason = filterReason;
      if (searchQuery) params.search = searchQuery;
      if (activeAccount?.id) params.account_id = activeAccount.id;

      const res = await axios.get(`${API}/api/marketing/returns`, { headers: authH, params });
      setReturns(res.data.data || []);
      setPagination(res.data.pagination || {});
    } catch (e) {
      console.error('Returns fetch error:', e);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authH, filterStatus, filterPlatform, filterReason, searchQuery, activeAccount]);

  useEffect(() => {
    fetchReasons();
    fetchSummary();
  }, [fetchReasons, fetchSummary]);

  useEffect(() => {
    fetchReturns(currentPage);
  }, [fetchReturns, currentPage]);


  const openForm = (ret = null) => {
    setEditTarget(ret);
    setShowForm(true);
  };

  const closeForm = () => {
    setShowForm(false);
    setEditTarget(null);
  };

  // 14 Nov 2026 — simpan lewat FormRefundPesanan (pesanan dipilih dari data impor; varian baru → Jembatan SKU).
  const handleSaved = (res, isEdit) => {
    if (isEdit) {
      toast({ title: 'Berhasil', description: 'Refund disimpan.' });
    } else {
      // W4 — beri tahu APA YANG TERJADI PADA STOK, bukan cuma "tersimpan".
      // 2026-11-02 (K1) — stok TIDAK lagi bertambah saat retur dibuat.
      const wh = res?.warehouse || {};
      const desc = [
        wh.wh_return_code
          ? `Refund tersimpan. Retur fisik ${wh.wh_return_code} dibuat di Gudang untuk pesanan & barang yang sama (menunggu paket) · `
            + 'stok & omzet setelah retur berubah setelah Gudang menerima dan memutuskan.'
          : 'Refund tersimpan (pekerjaan gudang belum terbuat — cek menu Gudang › Retur Fisik).',
        res?.sku_bridge ? `Varian disimpan ke Jembatan SKU: ${res.sku_bridge.orders_updated || 0} pesanan ikut tertaut.` : '',
      ].filter(Boolean).join(' ');
      toast({ title: 'Berhasil', description: desc });
    }
    closeForm();
    fetchReturns(currentPage);
    fetchSummary();
  };

  // Form menemukan barang yang sudah direfund → buka refund yang ada (bukan mencatat dua kali).
  const openExisting = async (id) => {
    closeForm();
    try {
      const res = await axios.get(`${API}/api/marketing/returns/${id}`, { headers: authH });
      if (res?.data?.data) setShowDetail(res.data.data);
    } catch (e) {
      toast({ title: 'Gagal', description: e.response?.data?.detail || e.message, variant: 'destructive' });
    }
  };

  const handleDelete = async (id) => {
    if (!(await confirmDialog({ title: 'Hapus retur ini?', body: 'Catatan retur dihapus dari daftar.', confirmLabel: 'Hapus', danger: true }))) return;
    setShowDetail(null);
    try {
      await axios.delete(`${API}/api/marketing/returns/${id}`, { headers: authH });
      toast({ title: 'Berhasil', description: 'Retur dihapus.' });
      fetchReturns(currentPage);
      fetchSummary();
    } catch (e) {
      toast({ title: 'Gagal', description: e.response?.data?.detail || e.message, variant: 'destructive' });
    }
  };

  const handleApprove = async (id) => {
    try {
      setActionLoading(id);
      await axios.post(`${API}/api/marketing/returns/${id}/approve`, {}, { headers: authH });
      toast({ title: 'Berhasil', description: 'Retur disetujui.' });
      fetchReturns(currentPage);
      fetchSummary();
      setShowDetail(null);
    } catch (e) {
      toast({ title: 'Gagal', description: e.response?.data?.detail || e.message, variant: 'destructive' });
    } finally {
      setActionLoading('');
    }
  };

  const handleReject = async (id, notes) => {
    try {
      setActionLoading(id);
      await axios.post(`${API}/api/marketing/returns/${id}/reject`, { notes }, { headers: authH });
      toast({ title: 'Berhasil', description: 'Retur ditolak.' });
      fetchReturns(currentPage);
      fetchSummary();
      setShowDetail(null);
    } catch (e) {
      toast({ title: 'Gagal', description: e.response?.data?.detail || e.message, variant: 'destructive' });
    } finally {
      setActionLoading('');
    }
  };

  const handleComplete = async (id) => {
    try {
      setActionLoading(id);
      const res = await axios.post(`${API}/api/marketing/returns/${id}/complete`, {}, { headers: authH });
      const warning = res?.data?.warning;
      // 2026-11-02 — /complete kini benar-benar menerbitkan nota kredit; sebutkan nomornya.
      const cnMsg = res?.data?.credit_note_message || '';
      if (warning) {
        toast({ title: 'Diselesaikan (dengan peringatan)', description: [cnMsg, warning].filter(Boolean).join(' · '), variant: 'default' });
      } else {
        toast({ title: 'Berhasil', description: cnMsg || 'Retur diselesaikan.' });
      }
      fetchReturns(currentPage);
      fetchSummary();
      setShowDetail(null);
    } catch (e) {
      toast({ title: 'Gagal', description: e.response?.data?.detail || e.message, variant: 'destructive' });
    } finally {
      setActionLoading('');
    }
  };

  // 2026-11-02 — retur yang sudah selesai TANPA nota kredit (data lama, ketika tombol
  // "Selesaikan & Terbitkan Nota Kredit" belum menerbitkan apa pun) bisa diterbitkan di sini.
  const handleIssueCreditNote = async (id) => {
    try {
      setActionLoading(id);
      const res = await axios.post(`${API}/api/marketing/returns/${id}/create-credit-note`, {}, { headers: authH });
      toast({ title: 'Berhasil', description: `Nota kredit ${res?.data?.data?.cn_number || ''} diterbitkan` });
      const refreshed = await axios.get(`${API}/api/marketing/returns/${id}`, { headers: authH });
      if (refreshed?.data?.data) setShowDetail(refreshed.data.data);
      fetchReturns(currentPage);
    } catch (e) {
      toast({ title: 'Gagal', description: e.response?.data?.detail || e.message, variant: 'destructive' });
    } finally {
      setActionLoading('');
    }
  };

  // RC-FLOW-UX-11a (opsi B): tombol manual "Buat Retur Fisik di Gudang" untuk
  // menghubungkan marketing_returns → wh_returns. Idempoten (backend cek back-ref).
  const handleCreateWhReturn = async (id) => {
    try {
      setActionLoading(id);
      const res = await axios.post(
        `${API}/api/marketing/returns/${id}/create-wh-return`,
        {},
        { headers: authH }
      );
      const code = res?.data?.wh_return_code || res?.data?.data?.return_code;
      const already = res?.data?.already_exists;
      const restocked = res?.data?.restocked;
      const effect = res?.data?.stock_effect;
      toast({
        title: already ? 'Sudah terhubung' : 'Berhasil',
        description: (already
          ? `Retur ini sudah punya entry Gudang ${code || ''}`
          : `Retur fisik dibuat di Gudang: ${code}.`)
          + (restocked
            ? ` Stok sudah diperbarui (${effect === 'sellable' ? 'masuk stok jual' : 'ditahan di karantina'}).`
            : ' Menunggu Gudang menerima paket & memutuskan (stok belum bergerak).'),
      });
      // refresh list & detail
      const refreshed = await axios.get(`${API}/api/marketing/returns/${id}`, { headers: authH });
      if (refreshed?.data?.data) setShowDetail(refreshed.data.data);
      fetchReturns(currentPage);
    } catch (e) {
      toast({ title: 'Gagal', description: e.response?.data?.detail || e.message, variant: 'destructive' });
    } finally {
      setActionLoading('');
    }
  };

  const clearFilters = () => {
    setFilterStatus('');
    setFilterPlatform('');
    setFilterReason('');
    setSearchQuery('');
    setCurrentPage(1);
  };

  const s = summary || {};
  const adaSaring = [filterStatus, filterPlatform, filterReason, searchQuery, activeAccount?.id].filter(Boolean).length > 0;

  const paramSaring = () => {
    const params = {};
    if (filterStatus) params.status = filterStatus;
    if (filterPlatform) params.platform = filterPlatform;
    if (filterReason) params.reason = filterReason;
    if (searchQuery) params.search = searchQuery;
    if (activeAccount?.id) params.account_id = activeAccount.id;
    return params;
  };
  /** Unduh semua retur hasil saringan (bukan hanya 20 baris halaman ini). */
  const ambilSemua = async () => {
    const semua = [];
    for (let p = 1; p <= 200; p += 1) {
      const res = await axios.get(`${API}/api/marketing/returns`, { headers: authH, params: { page: p, page_size: 100, ...paramSaring() } });
      semua.push(...(res.data.data || []));
      if (p >= (res.data.pagination?.total_pages || 1)) break;
    }
    return semua;
  };

  const kolom = [
    { kunci: 'tanggal', label: 'Tanggal', hp: 'keterangan', isi: (r) => <span className="tabular-nums md:whitespace-nowrap">{fmtDate(r.date || r.created_at)}</span> },
    { kunci: 'pesanan', label: 'Nomor pesanan', isi: (r) => <span className="tabular-nums">{r.order_id || '—'}</span> },
    { kunci: 'toko', label: 'Toko', isi: (r) => (
      <span className="md:whitespace-nowrap">{r.account_name || '—'}<span className="block text-xs text-muted-foreground">{labelPlatform(r.platform)}</span></span>) },
    { kunci: 'produk', label: 'Produk', hp: 'judul', isi: (r) => <p className="truncate md:max-w-[14rem]" title={r.product}>{r.product || '—'}</p> },
    { kunci: 'alasan', label: 'Alasan', isi: (r) => <p className="truncate md:max-w-[12rem]" title={r.reason_detail}>{kalimat(r.reason_label || r.reason) || '—'}</p> },
    { kunci: 'refund', label: 'Refund (Rp)', rata: 'kanan', isi: (r) => <span className="tabular-nums font-medium">{(r.refund_amount || 0).toLocaleString('id-ID')}</span> },
    { kunci: 'status', label: 'Status', isi: (r) => <StatusRetur status={r.status} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <div className="flex justify-end gap-1">
        <Button onClick={() => openForm(r)} variant="ghost" size="icon-sm" title="Ubah retur" aria-label="Ubah retur"><Pencil /></Button>
        <Button onClick={() => handleDelete(r.id)} variant="ghost" size="icon-sm" title="Hapus retur" aria-label="Hapus retur"
          className="text-[hsl(var(--danger-text))]"><Trash2 /></Button>
      </div>) },
  ];

  return (
    <PageLayout testId="returns-refunds-module" title="Refund & nota kredit"
      subtitle="Pengembalian dana dan nota kredit dari retur marketplace — sisi Toko/Marketing."
      actions={<>
        {typeof onNavigate === 'function' && (
          <Button variant="outline" onClick={() => onNavigate('wh-returns', {})} data-testid="returns-to-wh">
            <Warehouse />Terima retur fisik di gudang
          </Button>
        )}
        <Button onClick={() => openForm()} data-testid="returns-create"><Plus />Buat refund</Button>
      </>}
      filters={<>
        <div className="relative w-full sm:w-44">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder="Cari pesanan atau produk" value={searchQuery} className="pl-8"
            onChange={e => { setSearchQuery(e.target.value); setCurrentPage(1); }} data-testid="returns-search" />
        </div>
        <PilihAkun accounts={masterAccounts} activeAccount={activeAccount} testId="returns-account"
          onChange={(acc) => { setActiveAccount(acc); setCurrentPage(1); }} />
        <SmartNativeSelect value={filterStatus} onChange={(e) => { setFilterStatus(e.target.value); setCurrentPage(1); }} className="w-full" wrapperClassName="w-36 max-w-full" searchable={false}>
          <option value="">Semua status</option>
          {Object.entries(STATUS_CONFIG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={filterPlatform} onChange={(e) => { setFilterPlatform(e.target.value); setCurrentPage(1); }} className="w-full" wrapperClassName="w-40 max-w-full" searchable={false}>
          <option value="">Semua platform</option>
          <option value="shopee">Shopee</option>
          <option value="tiktok">TikTok</option>
          <option value="tokopedia">Tokopedia</option>
        </SmartNativeSelect>
        <SmartNativeSelect value={filterReason} onChange={(e) => { setFilterReason(e.target.value); setCurrentPage(1); }} className="w-full" wrapperClassName="w-44 max-w-full">
          <option value="">Semua alasan</option>
          {reasons.map(r => <option key={r.value} value={r.value}>{kalimat(r.label)}</option>)}
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="refund-retur" namaLembar="Retur" baris={returns} ambilSemua={ambilSemua} testId="returns-unduh"
          kolom={[
            { label: 'Tanggal', nilai: (r) => fmtDate(r.date || r.created_at) },
            { label: 'Platform', nilai: (r) => labelPlatform(r.platform) },
            { label: 'Nomor pesanan', nilai: (r) => r.order_id || '' },
            { label: 'Toko', nilai: (r) => r.account_name || '' },
            { label: 'Produk', nilai: (r) => r.product || '' },
            { label: 'Qty', nilai: (r) => r.qty ?? '' },
            { label: 'Harga satuan', nilai: (r) => Number(r.price) || 0 },
            { label: 'Alasan', nilai: (r) => kalimat(r.reason_label || r.reason) },
            { label: 'Rincian alasan', nilai: (r) => r.reason_detail || '' },
            { label: 'Jenis refund', nilai: (r) => REFUND_TYPE[r.refund_type] || '' },
            { label: 'Refund', nilai: (r) => Number(r.refund_amount) || 0 },
            { label: 'Status', nilai: (r) => STATUS_CONFIG[r.status]?.label || r.status || '' },
            { label: 'Hasil banding', nilai: (r) => r.appeal_result || '' },
            { label: 'Retur fisik gudang', nilai: (r) => r.wh_return_code || '' },
            { label: 'Nota kredit', nilai: (r) => r.credit_note_number || '' },
            { label: 'Catatan', nilai: (r) => r.notes || '' },
          ]} />
        <Button onClick={() => { fetchReturns(currentPage); fetchSummary(); }} variant="outline" size="icon" title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={(s.total || 0) > 0 && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="returns-kpi">
          <StatTile label="Total retur" value={s.total || 0}
            sub={`${s.approved || 0} disetujui · ${s.rejected || 0} ditolak`}
            hint="Semua toko yang bisa Anda lihat; tidak ikut pilihan akun & penyaring." />
          <StatTile label="Menunggu keputusan" value={s.pending || 0} accent="warning" hint="Retur berstatus menunggu." />
          <StatTile label="Selesai" value={s.completed || 0} accent="success" hint="Retur yang sudah diselesaikan (nota kredit terbit bila ada refund)." />
          <StatTile label="Nilai refund tercatat" value={rp(s.total_refund)}
            sub="Semua status, termasuk yang belum selesai"
            hint="Jumlah nominal refund semua retur (menunggu, disetujui, selesai, ditolak) — bukan uang yang sudah dikembalikan." />
        </div>
      )}
      footer={pagination && pagination.total_pages > 1 && (
        <PaginationLite page={currentPage} totalPages={pagination.total_pages} total={pagination.total} pageSize={20}
          onPageChange={setCurrentPage} />
      )}>
      {loading && returns.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat retur…</p>
      ) : (
        <TabelData kolom={kolom} baris={returns} onKlikBaris={setShowDetail} testId="returns-table"
          kosong={<EmptyState title={adaSaring ? 'Tidak ada retur yang cocok' : 'Belum ada retur'}
            description={adaSaring ? 'Ubah saringan, akun, atau kata pencarian.' : 'Catat retur dari marketplace dengan tombol Buat refund.'}
            action={!adaSaring && <Button onClick={() => openForm()}><Plus />Buat refund</Button>} />} />
      )}

      {/* Form refund (popup) — 14 Nov 2026: pesanan wajib dipilih dari data impor */}
      {showForm && (
        <FormRefundPesanan editTarget={editTarget} authH={authH} reasons={reasons} onClose={closeForm}
          onSaved={handleSaved} onOpenExisting={openExisting} onNavigate={onNavigate} />
      )}

      {/* Detail retur (popup) */}
      {showDetail && (
        <DetailPopup open onClose={() => setShowDetail(null)} testId="return-detail"
          judul={showDetail.order_id ? `Refund pesanan ${showDetail.order_id}` : 'Refund tanpa nomor pesanan'}
          status={<StatusRetur status={showDetail.status} />}
          keterangan={`${showDetail.account_name || '—'} · ${labelPlatform(showDetail.platform)} · ${fmtDate(showDetail.date || showDetail.created_at)}`}
          aksi={<>
            <Button size="sm" variant="outline" onClick={() => { const r = showDetail; setShowDetail(null); openForm(r); }}><Pencil />Ubah</Button>
            <Button size="sm" variant="destructive" onClick={() => handleDelete(showDetail.id)}><Trash2 />Hapus</Button>
          </>}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Produk">{showDetail.product || '—'}{showDetail.qty ? ` · ${showDetail.qty} pcs` : ''}</BarisDetail>
            {showDetail.order_line_label && <BarisDetail label="Barang di pesanan">{showDetail.order_line_label}</BarisDetail>}
            {showDetail.sku && <BarisDetail label="SKU master">{showDetail.sku}</BarisDetail>}
            {showDetail.order_tracking_number && <BarisDetail label="No. resi">{showDetail.order_tracking_number}</BarisDetail>}
            <BarisDetail label="Harga satuan">{rp(showDetail.price)}</BarisDetail>
            <BarisDetail label="Alasan">{kalimat(showDetail.reason_label || showDetail.reason) || '—'}</BarisDetail>
            <BarisDetail label="Rincian alasan">{showDetail.reason_detail || '—'}</BarisDetail>
            <BarisDetail label="Jenis refund">{REFUND_TYPE[showDetail.refund_type] || '—'}</BarisDetail>
            <BarisDetail label="Refund"><span className="font-medium tabular-nums">{rp(showDetail.refund_amount)}</span></BarisDetail>
            {showDetail.appeal_result && <BarisDetail label="Hasil banding">{showDetail.appeal_result}</BarisDetail>}
            {showDetail.notes && <BarisDetail label="Catatan">{showDetail.notes}</BarisDetail>}
            {showDetail.wh_return_code && (
              <BarisDetail label="Retur fisik (gudang)">{showDetail.wh_return_code} · {statusGudang(showDetail.wh_return_status)}</BarisDetail>
            )}
            {/* 2026-11-09 — "Refund only": barang tidak kembali, jadi tidak ada Retur Fisik. */}
            {!showDetail.wh_return_id && showDetail.goods_returned === false && (
              <BarisDetail label="Retur fisik (gudang)">
                <span data-testid="mkt-ret-refund-only">
                  Tidak dibuat{showDetail.wh_skip_reason ? `: ${showDetail.wh_skip_reason}` : ' — barang tidak dikirim balik ke gudang.'}
                </span>
              </BarisDetail>
            )}
            {/* W4 — apa yang terjadi pada STOK, dinyatakan terang-terangan. */}
            {showDetail.wh_return_id && (
              <BarisDetail label="Efek stok">
                <span data-testid="mkt-ret-stock-effect">
                  {showDetail.wh_restocked ? (
                    <StatusBadge status="stok" tone={showDetail.wh_stock_effect === 'sellable' ? 'success' : 'warning'}
                      label={showDetail.wh_stock_effect === 'sellable'
                        ? `+${showDetail.wh_restock_qty || 0} stok jual (${showDetail.wh_restock_location_code || 'ZNA-FG'})`
                        : `+${showDetail.wh_restock_qty || 0} karantina (${showDetail.wh_restock_location_code || 'ZNA-KARANTINA'})`} />
                  ) : (
                    <StatusBadge status="stok" tone="muted"
                      label={showDetail.wh_return_status === 'Resolved'
                        ? `diputuskan: ${showDetail.wh_action_taken || '-'}`
                        : `menunggu keputusan gudang (${statusGudang(showDetail.wh_return_status)})`} />
                  )}
                  {showDetail.wh_link_status && showDetail.wh_link_status !== 'linked' && (
                    <span className="mt-1 block text-xs text-[hsl(var(--warning-text))]">{showDetail.wh_link_reason}</span>
                  )}
                </span>
              </BarisDetail>
            )}
            {showDetail.credit_note_number && <BarisDetail label="Nota kredit">{showDetail.credit_note_number}</BarisDetail>}
          </dl>

          {/* RC-FLOW-UX-11c (opsi B, soft-warning): retur approved > 24 jam & belum ada wh_return_id */}
          {showDetail.status === 'approved' && !showDetail.wh_return_id && showDetail.goods_returned !== false && (() => {
            const upd = new Date(showDetail.updated_at || showDetail.date || 0).getTime();
            const hours = (Date.now() - upd) / 36e5;
            if (hours < 24) return null;
            return (
              <Notice tone="warning" icon={AlertCircle} title="Barang belum diterima gudang">
                Retur disetujui {Math.floor(hours)} jam lalu, tetapi belum ada retur fisik di gudang. Stok baru bertambah setelah
                gudang menerima &amp; memutuskan. Klik Kirim ke gudang untuk melanjutkan.
              </Notice>
            );
          })()}
          {showDetail.status === 'approved' && showDetail.wh_return_id && (
            <Notice tone="success" icon={CheckCircle2} title={`Terhubung ke gudang: ${showDetail.wh_return_code || ''}`}
              action={onNavigate && (
                <Button size="sm" variant="outline" onClick={() => onNavigate('wh-returns', { return_id: showDetail.wh_return_id })}
                  data-testid="btn-open-wh-return">Buka di gudang</Button>
              )} />
          )}

          <div className="flex flex-wrap gap-2 border-t border-[var(--glass-border)] pt-3">
            {/* W4 — retur LAMA (sebelum jembatan otomatis) bisa ditarik ke gudang, apa pun statusnya selain ditolak/dibatalkan. */}
            {!showDetail.wh_return_id && showDetail.goods_returned !== false && !['rejected', 'cancelled'].includes(showDetail.status) && (
              <Button onClick={() => handleCreateWhReturn(showDetail.id)} disabled={actionLoading === showDetail.id}
                variant="outline" data-testid="btn-create-wh-return">
                {actionLoading === showDetail.id ? <Loader2 className="animate-spin" /> : <Warehouse />}
                Kirim ke gudang (menunggu paket)
              </Button>
            )}
            {showDetail.status === 'pending' && <>
              <Button variant="success" onClick={() => handleApprove(showDetail.id)} disabled={actionLoading === showDetail.id}>
                {actionLoading === showDetail.id ? <Loader2 className="animate-spin" /> : <ThumbsUp />}Setujui
              </Button>
              <Button onClick={() => handleReject(showDetail.id, 'Tidak memenuhi syarat')} disabled={actionLoading === showDetail.id} variant="destructive">
                {actionLoading === showDetail.id ? <Loader2 className="animate-spin" /> : <ThumbsDown />}Tolak
              </Button>
            </>}
            {showDetail.status === 'approved' && (
              <Button variant="success" onClick={() => handleComplete(showDetail.id)} disabled={actionLoading === showDetail.id}
                data-testid="btn-complete-return">
                {actionLoading === showDetail.id ? <Loader2 className="animate-spin" /> : <CheckCircle2 />}
                {(showDetail.refund_amount || 0) > 0
                  ? 'Selesaikan & terbitkan nota kredit'
                  : 'Selesaikan (tanpa nota kredit — refund Rp 0)'}
              </Button>
            )}
            {/* 2026-11-02 — retur selesai tanpa nota kredit (data lama) bisa diterbitkan susulan. */}
            {showDetail.status === 'completed' && !showDetail.credit_note_id && (showDetail.refund_amount || 0) > 0 && (
              <Button onClick={() => handleIssueCreditNote(showDetail.id)} disabled={actionLoading === showDetail.id}
                variant="outline" data-testid="btn-issue-credit-note">
                {actionLoading === showDetail.id ? <Loader2 className="animate-spin" /> : <FileText />}
                Terbitkan nota kredit
              </Button>
            )}
          </div>
        </DetailPopup>
      )}
    </PageLayout>
  );
}

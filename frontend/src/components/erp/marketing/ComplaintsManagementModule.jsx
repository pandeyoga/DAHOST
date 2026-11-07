/**
 * Komplain (tab di Komplain & Retur, Portal Toko) — keluhan pelanggan dengan batas waktu (SLA) dan usulan AI.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout (judul disembunyikan di hub), penyaring satu baris (akun aktif
 * kini pilihan di baris penyaring, dulu bar lebar), 4 StatTile berketerangan, tabel + unduh semua baris, detail popup.
 * Ajakan "Proses retur & refund" (dulu kotak lebar) kini tombol di baris tab. Panggilan API & isian tidak berubah.
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Search, RefreshCw, Loader2, Bot, MessageSquare, RotateCcw } from 'lucide-react';
import axios from 'axios';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import PaginationLite from '@/components/ui/pagination-lite';
import { useToast } from '@/hooks/use-toast';
import { useActiveMarketingAccount } from '@/hooks/useActiveMarketingAccount';
import { useMarketingAccounts } from '@/hooks/useMarketingAccounts';
import { formatDateID, formatDateTimeID } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from '../moduleAtoms';
import { getPlatformConfig } from './AccountBadge';
import AISuggestionPanel from '../AISuggestionPanel';

const API = process.env.REACT_APP_BACKEND_URL;

// ── Label ──
const SLA_CONFIG = {
  on_time: { label: 'Tepat waktu', tone: 'success' },
  at_risk: { label: 'Hampir lewat', tone: 'warning' },
  overdue: { label: 'Lewat batas', tone: 'danger' },
  resolved: { label: 'Selesai', tone: 'muted' },
};
const STATUS_CONFIG = {
  open: { label: 'Terbuka', tone: 'danger' },
  in_progress: { label: 'Diproses', tone: 'info' },
  resolved: { label: 'Selesai', tone: 'success' },
  closed: { label: 'Ditutup', tone: 'muted' },
};
const SEVERITY_CONFIG = {
  critical: { label: 'Kritis', tone: 'danger' },
  high: { label: 'Tinggi', tone: 'warning' },
  medium: { label: 'Sedang', tone: 'warning' },
  low: { label: 'Rendah', tone: 'muted' },
};
const CATEGORY_LABELS = {
  missing_item: 'Produk kurang',
  wrong_item: 'Produk salah',
  quality_defect: 'Cacat/rusak',
  size_mismatch: 'Ukuran salah',
  late_delivery: 'Pengiriman lambat',
  packaging_damage: 'Kemasan rusak',
  seller_unresponsive: 'Penjual tidak merespons',
  description_mismatch: 'Tidak sesuai deskripsi',
  other: 'Lainnya',
};
const labelKategori = (c, fallback) => CATEGORY_LABELS[c] || fallback || 'Lainnya';
const NAMA_PLATFORM = { shopee: 'Shopee', tiktok: 'TikTok', tiktokshop: 'TikTok', tokopedia: 'Tokopedia', instagram: 'Instagram', lazada: 'Lazada' };
const labelPlatform = (p) => NAMA_PLATFORM[String(p || '').toLowerCase()] || (getPlatformConfig(p).label !== 'Platform' ? getPlatformConfig(p).label
  : (p ? String(p).replace(/^./, (x) => x.toUpperCase()) : '—'));

// K28 (2026-11-02): field usulan AI yang bisa Diterima/Diubah (daftar baku = enum server).
const AI_SUGGESTION_FIELDS = [
  { key: 'category', label: 'Kategori', options: Object.entries(CATEGORY_LABELS).map(([value, label]) => ({ value, label })) },
  { key: 'severity', label: 'Tingkat keparahan', options: Object.entries(SEVERITY_CONFIG).map(([value, c]) => ({ value, label: c.label })) },
  { key: 'response_template', label: 'Templat respons' },
];

const tgl = (d) => (d ? formatDateID(d) : '—');
const jamTersisa = (c) => {
  if (!c.sla_due_at || c.sla_status === 'resolved') return '';
  const h = (new Date(c.sla_due_at) - Date.now()) / 3600000;
  if (Number.isNaN(h)) return '';
  const hari = Math.round(Math.abs(h) / 24);
  const teks = Math.abs(h) >= 48 ? `${hari} hari` : `${Math.round(Math.abs(h))} jam`;
  return h < 0 ? `lewat ${teks}` : `sisa ${teks}`;
};

function SLABadge({ c }) {
  const cfg = SLA_CONFIG[c.sla_status] || SLA_CONFIG.on_time;
  const sisa = jamTersisa(c);
  return (
    <span className="inline-flex flex-col items-start gap-0.5">
      <StatusBadge status={c.sla_status} label={cfg.label} tone={cfg.tone} />
      {sisa && <span className="text-xs text-muted-foreground">{sisa}</span>}
    </span>
  );
}
const StatusKomplain = ({ status }) => {
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.open;
  return <StatusBadge status={status} label={cfg.label} tone={cfg.tone} />;
};

/** Pilihan akun aktif di baris penyaring (pengganti bar akun selebar layar). Sumber & penyimpanan sama: hook akun aktif. */
function PilihAkun({ accounts = [], activeAccount, onChange, testId = 'pilih-akun', lebar = 'w-56' }) {
  const aktif = accounts.filter((a) => a.status === 'active' || !a.status);
  const daftar = activeAccount && !aktif.some((a) => a.id === activeAccount.id) ? [activeAccount, ...aktif] : aktif;
  return (
    <SmartNativeSelect value={activeAccount?.id || ''} className={lebar} data-testid={testId}
      onChange={(e) => onChange(daftar.find((a) => a.id === e.target.value) || null)}>
      <option value="">Semua toko</option>
      {daftar.map((a) => <option key={a.id} value={a.id}>{`${a.account_name} · ${labelPlatform(a.platform)}`}</option>)}
    </SmartNativeSelect>
  );
}

// ── Detail komplain (popup) ──
function ComplaintDetailModal({ complaint, open, onClose, onUpdate, token }) {
  const { toast } = useToast();
  const [newStatus, setNewStatus] = useState('');
  const [noteText, setNoteText] = useState('');
  const [updating, setUpdating] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);
  const [detail, setDetail] = useState(null);

  const authH = { Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` };

  useEffect(() => {
    if (open && complaint) {
      setDetail(complaint);
      setNewStatus('');
      setNoteText('');
    }
  }, [open, complaint]);

  const handleStatusUpdate = async () => {
    if (!newStatus) return;
    setUpdating(true);
    try {
      await axios.patch(`${API}/api/marketing/complaints/${detail.id}/status`,
        { status: newStatus, note: noteText || undefined },
        { headers: authH }
      );
      toast({ title: `Status diubah ke ${STATUS_CONFIG[newStatus]?.label}` });
      onUpdate();
      onClose();
    } catch (e) {
      toast({ title: 'Gagal mengubah status', variant: 'destructive' });
    } finally { setUpdating(false); }
  };

  const handleAddNote = async () => {
    if (!noteText.trim()) return;
    setUpdating(true);
    try {
      await axios.post(`${API}/api/marketing/complaints/${detail.id}/notes`,
        { text: noteText },
        { headers: authH }
      );
      toast({ title: 'Catatan ditambahkan' });
      const res = await axios.get(`${API}/api/marketing/complaints/${detail.id}`, { headers: authH });
      setDetail(res.data);
      setNoteText('');
    } catch (e) {
      toast({ title: 'Gagal menambah catatan', variant: 'destructive' });
    } finally { setUpdating(false); }
  };

  // K28 (2026-11-02): AI hanya membuat USULAN; kategori/severity resmi berubah saat
  // pengguna menekan Terima/Ubah di panel usulan (server mencatat aktornya).
  const handleAiClassify = async () => {
    setAiLoading(true);
    try {
      const res = await axios.post(`${API}/api/marketing/complaints/${detail.id}/ai-classify`,
        {}, { headers: authH });
      const s = res.data.ai_suggestion;
      toast({ title: `Usulan AI: ${labelKategori(s?.values?.category, s?.values?.category)} — tinjau lalu terima, ubah, atau tolak` });
      setDetail(prev => ({ ...prev, ai_suggestion: s }));
    } catch (e) {
      toast({ title: 'AI gagal', description: e.response?.data?.detail, variant: 'destructive' });
    } finally { setAiLoading(false); }
  };

  if (!detail || !open) return null;

  const nexts = { open: ['in_progress', 'resolved', 'closed'], in_progress: ['resolved', 'closed'], resolved: ['closed'], closed: [] };
  const nextStatuses = nexts[detail.status] || [];

  return (
    <DetailPopup open onClose={onClose} judul={detail.complaint_number || 'Komplain'} testId="complaint-detail"
      status={<>
        <StatusKomplain status={detail.status} />
        <SLABadge c={detail} />
        {detail.severity && <StatusBadge status={detail.severity} label={SEVERITY_CONFIG[detail.severity]?.label || detail.severity}
          tone={SEVERITY_CONFIG[detail.severity]?.tone} />}
      </>}
      keterangan={`${labelPlatform(detail.platform)} · ${detail.account_name || '—'} · ${tgl(detail.complaint_date)}`}
      aksi={
        <Button size="sm" variant="outline" onClick={handleAiClassify} disabled={aiLoading} data-testid="complaint-ai-classify">
          {aiLoading ? <Loader2 className="animate-spin" /> : <Bot />}Minta usulan AI
        </Button>
      }>
      {detail.ai_suggestion && (
        <AISuggestionPanel
          suggestion={detail.ai_suggestion}
          fields={AI_SUGGESTION_FIELDS}
          decideUrl={`${API}/api/marketing/complaints/${detail.id}/ai-suggestion`}
          headers={authH}
          testId="complaint-ai-suggestion"
          onDecided={async () => {
            const res = await axios.get(`${API}/api/marketing/complaints/${detail.id}`, { headers: authH });
            setDetail(res.data);
            onUpdate();
          }}
        />
      )}

      <dl className="divide-y divide-[var(--glass-border)]">
        <BarisDetail label="Kategori">{labelKategori(detail.category, detail.category_label)}</BarisDetail>
        <BarisDetail label="Pelanggan">{detail.customer_name || '—'}</BarisDetail>
        <BarisDetail label="Produk">{detail.product_name || '—'}</BarisDetail>
        <BarisDetail label="Keluhan"><span className="whitespace-pre-wrap">{detail.complaint_text || '—'}</span></BarisDetail>
        {detail.response_template && (
          <BarisDetail label="Templat respons AI"><span className="italic text-muted-foreground">{detail.response_template}</span></BarisDetail>
        )}
        {(detail.orders || []).length > 0 && (
          <BarisDetail label="Pesanan terkait">
            {detail.orders.map((o, i) => (
              <span key={i} className="block tabular-nums">{o.order_id} · {o.qty} pcs · {o.courier}</span>
            ))}
          </BarisDetail>
        )}
      </dl>

      {(detail.notes || []).length > 0 && (
        <div className="space-y-2">
          <p className="text-sm font-medium text-foreground">Catatan internal</p>
          {detail.notes.map((n, i) => (
            <div key={i} className="border-l-2 border-[hsl(var(--primary)/0.3)] pl-3">
              <p className="text-xs text-muted-foreground">{n.author} · {n.added_at ? formatDateTimeID(n.added_at) : ''}</p>
              <p className="text-sm">{n.text}</p>
            </div>
          ))}
        </div>
      )}

      <div className="space-y-2 border-t border-[var(--glass-border)] pt-3">
        <label className="text-sm font-medium text-foreground" htmlFor="complaint-note">Tambah catatan internal</label>
        <Textarea id="complaint-note" placeholder="Tulis catatan untuk tim…" value={noteText}
          onChange={e => setNoteText(e.target.value)} rows={3} data-testid="note-textarea" />
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="outline" onClick={handleAddNote} disabled={!noteText.trim() || updating}>
            <MessageSquare />Tambah catatan
          </Button>
          {nextStatuses.length > 0 && <>
            <span className="ml-auto text-sm text-muted-foreground">Ubah status:</span>
            <SmartNativeSelect value={newStatus} onChange={(e) => setNewStatus(e.target.value)} className="w-40" searchable={false}
              data-testid="complaint-next-status">
              <option value="">Pilih status</option>
              {nextStatuses.map(s => <option key={s} value={s}>{STATUS_CONFIG[s]?.label}</option>)}
            </SmartNativeSelect>
            <Button size="sm" variant="success" onClick={handleStatusUpdate} disabled={!newStatus || updating}>
              {updating && <Loader2 className="animate-spin" />}Simpan status
            </Button>
          </>}
        </div>
        {nextStatuses.length > 0 && newStatus && noteText.trim() && (
          <p className="text-xs text-muted-foreground">Catatan di atas ikut disimpan bersama perubahan status.</p>
        )}
      </div>
    </DetailPopup>
  );
}

// ── Modul ──
export default function ComplaintsManagementModule({ token, onNavigate }) {
  const { activeAccount, setActiveAccount } = useActiveMarketingAccount();
  const { accounts: masterAccounts } = useMarketingAccounts(token);
  const [summary, setSummary] = useState(null);
  const [complaints, setComplaints] = useState([]);
  const [pagination, setPagination] = useState(null);
  const [loading, setLoading] = useState(true);
  const [summaryLoading, setSummaryLoading] = useState(true);

  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [slaFilter, setSlaFilter] = useState('');
  const [catFilter, setCatFilter] = useState('');
  const [platformFilter, setPlatformFilter] = useState('');
  const [page, setPage] = useState(1);

  const [selectedComplaint, setSelectedComplaint] = useState(null);
  const debounceRef = useRef(null);
  const authH = { Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` };

  const fetchSummary = useCallback(async () => {
    setSummaryLoading(true);
    try {
      const res = await axios.get(`${API}/api/marketing/complaints/summary`, { headers: authH });
      setSummary(res.data);
    } finally { setSummaryLoading(false); }
  }, [token]); // eslint-disable-line

  const paramSaring = () => {
    const params = {};
    if (statusFilter)         params.status     = statusFilter;
    if (slaFilter)            params.sla_status = slaFilter;
    if (catFilter)            params.category   = catFilter;
    if (platformFilter)       params.platform   = platformFilter;
    if (search)               params.search     = search;
    if (activeAccount?.id)    params.account_id = activeAccount.id;
    return params;
  };

  const fetchComplaints = useCallback(async () => {
    setLoading(true);
    try {
      const params = { page, page_size: 25, ...paramSaring() };
      const res = await axios.get(`${API}/api/marketing/complaints`, { params, headers: authH });
      setComplaints(res.data.complaints || []);
      setPagination(res.data.pagination);
    } finally { setLoading(false); }
  }, [page, statusFilter, slaFilter, catFilter, platformFilter, search, activeAccount, token]); // eslint-disable-line

  useEffect(() => { fetchSummary(); }, [fetchSummary]);
  useEffect(() => { fetchComplaints(); }, [fetchComplaints]);

  const handleSearchChange = (e) => {
    setSearch(e.target.value);
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setPage(1), 400);
  };

  /** Unduh semua komplain hasil saringan (bukan hanya 25 baris halaman ini). */
  const ambilSemua = async () => {
    const semua = [];
    for (let p = 1; p <= 200; p += 1) {
      const res = await axios.get(`${API}/api/marketing/complaints`, { params: { page: p, page_size: 100, ...paramSaring() }, headers: authH });
      semua.push(...(res.data.complaints || []));
      const tp = res.data.pagination?.total_pages || 1;
      if (p >= tp) break;
    }
    return semua;
  };

  const kolom = [
    { kunci: 'nomor', label: 'Nomor', hp: 'judul', isi: (c) => <span className="font-medium tabular-nums md:whitespace-nowrap">{c.complaint_number}</span> },
    { kunci: 'platform', label: 'Platform', isi: (c) => labelPlatform(c.platform) },
    { kunci: 'kategori', label: 'Kategori', isi: (c) => <span className="md:whitespace-nowrap">{labelKategori(c.category, c.category_label)}</span> },
    { kunci: 'pelanggan', label: 'Pelanggan / produk', hp: 'keterangan', isi: (c) => (
      <div className="min-w-0 md:max-w-[16rem]">
        <p className="truncate text-sm font-medium">{c.customer_name}</p>
        <p className="truncate text-xs text-muted-foreground" title={c.product_name}>{c.product_name}</p>
      </div>) },
    { kunci: 'tanggal', label: 'Tanggal', isi: (c) => <span className="tabular-nums md:whitespace-nowrap">{tgl(c.complaint_date)}</span> },
    { kunci: 'status', label: 'Status', isi: (c) => <StatusKomplain status={c.status} /> },
    { kunci: 'sla', label: 'Batas waktu', isi: (c) => <SLABadge c={c} /> },
  ];
  const adaSaring = !!(search || statusFilter || slaFilter || catFilter || platformFilter || activeAccount?.id);
  const s = summary || {};
  const angka = (v) => (summaryLoading ? '…' : (v ?? 0));

  return (
    <PageLayout testId="complaints-dashboard" title="Komplain"
      subtitle="Keluhan pelanggan dengan batas waktu penanganan dan usulan klasifikasi AI."
      actions={typeof onNavigate === 'function' && (
        <Button variant="outline" onClick={() => onNavigate('marketing-returns', {})} data-testid="complaint-to-returns">
          <RotateCcw />Proses retur & refund
        </Button>
      )}
      filters={<>
        <div className="relative w-full sm:w-44">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder="Cari nomor, keluhan, produk" className="pl-8" value={search} onChange={handleSearchChange}
            data-testid="search-complaints" />
        </div>
        <PilihAkun accounts={masterAccounts} activeAccount={activeAccount} testId="complaint-account" lebar="w-36"
          onChange={(acc) => { setActiveAccount(acc); setPage(1); }} />
        <SmartNativeSelect value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }} className="w-36" searchable={false}>
          <option value="">Semua status</option>
          {Object.entries(STATUS_CONFIG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={slaFilter} onChange={(e) => { setSlaFilter(e.target.value); setPage(1); }} className="w-40" searchable={false}
          data-testid="complaint-sla-filter">
          <option value="">Semua tenggat</option>
          {Object.entries(SLA_CONFIG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={catFilter} onChange={(e) => { setCatFilter(e.target.value); setPage(1); }} className="w-40">
          <option value="">Semua kategori</option>
          {Object.entries(CATEGORY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={platformFilter} onChange={(e) => { setPlatformFilter(e.target.value); setPage(1); }} className="w-40" searchable={false}>
          <option value="">Semua platform</option>
          <option value="shopee">Shopee</option>
          <option value="tiktok">TikTok</option>
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="komplain" namaLembar="Komplain" baris={complaints} ambilSemua={ambilSemua} testId="complaints-unduh"
          kolom={[
            { label: 'Nomor', nilai: (c) => c.complaint_number },
            { label: 'Platform', nilai: (c) => labelPlatform(c.platform) },
            { label: 'Akun', nilai: (c) => c.account_name || '' },
            { label: 'Kategori', nilai: (c) => labelKategori(c.category, c.category_label) },
            { label: 'Tingkat keparahan', nilai: (c) => SEVERITY_CONFIG[c.severity]?.label || '' },
            { label: 'Pelanggan', nilai: (c) => c.customer_name || '' },
            { label: 'Produk', nilai: (c) => c.product_name || '' },
            { label: 'Keluhan', nilai: (c) => c.complaint_text || '' },
            { label: 'Tanggal', nilai: (c) => tgl(c.complaint_date) },
            { label: 'Status', nilai: (c) => STATUS_CONFIG[c.status]?.label || c.status },
            { label: 'Batas waktu', nilai: (c) => `${SLA_CONFIG[c.sla_status]?.label || ''} ${jamTersisa(c)}`.trim() },
          ]} />
        <Button variant="outline" size="icon" onClick={() => { fetchSummary(); fetchComplaints(); }} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={(summaryLoading || (s.total ?? 0) > 0) && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="complaints-kpi">
          <StatTile label="Total komplain" value={angka(s.total)} sub={`${s.by_status?.open || 0} terbuka`}
            hint="Semua toko yang bisa Anda lihat; tidak ikut pilihan akun & penyaring." />
          <StatTile label="Lewat batas waktu" value={angka(s.overdue)} accent="danger" sub={`${s.at_risk || 0} hampir lewat`}
            hint="Komplain belum selesai yang sudah melewati batas waktu penanganan." />
          <StatTile label="Tingkat selesai" value={summaryLoading ? '…' : `${String(s.resolve_rate ?? 0).replace('.', ',')}%`} accent="success"
            sub={`${s.resolved || 0} selesai/ditutup dari ${s.total || 0}`} hint="Selesai + ditutup dibagi total komplain." />
          <StatTile label="Sedang diproses" value={angka(s.by_status?.in_progress)} accent="warning"
            sub={`${s.by_status?.open || 0} masih terbuka`} hint="Komplain berstatus diproses." />
        </div>
      )}
      footer={pagination && pagination.total_pages > 1 && (
        <PaginationLite page={page} totalPages={pagination.total_pages} total={pagination.total} pageSize={25} onPageChange={setPage} />
      )}>
      {loading && complaints.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat komplain…</p>
      ) : (
        <TabelData kolom={kolom} baris={complaints} onKlikBaris={setSelectedComplaint} testId="complaints-table"
          kosong={<EmptyState title={adaSaring ? 'Tidak ada komplain yang cocok' : 'Belum ada komplain'}
            description={adaSaring ? 'Ubah saringan, akun, atau kata pencarian.' : 'Komplain pelanggan dari marketplace muncul di sini.'} />} />
      )}

      <ComplaintDetailModal
        complaint={selectedComplaint}
        open={!!selectedComplaint}
        onClose={() => setSelectedComplaint(null)}
        onUpdate={() => { fetchComplaints(); fetchSummary(); }}
        token={token}
      />
    </PageLayout>
  );
}

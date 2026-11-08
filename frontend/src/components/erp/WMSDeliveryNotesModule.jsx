/**
 * Surat Jalan (Portal Gudang) — daftar lintas sumber (FASE H-7) + surat jalan gudang (buat, terbitkan, terima, PDF).
 * P0-WH-2: Create, issue, and download PDF delivery notes.
 *
 * Standar UI/UX v2 (8 Nov 2026): HubTabs (Semua sumber · SJ gudang; dulu 5 tab bercampur status), status = pil
 * penyaring, tiap tab PageLayout + TabelData (kartu di HP) + unduh Excel/CSV, periode = PeriodPicker (dulu
 * input tanggal bawaan), form buat = FormPopup panjang, rincian = DetailPopup, label Indonesia (Terbitkan/Terbit/
 * Diterima; dulu Issue/Issued/Received). Tampilan "Kartu" di desktop dihapus (daftar > 6 = tabel); di HP tabel
 * otomatis jadi kartu ringkas. Urutan kolom lewat pilihan "Urutkan" (dulu klik judul kolom).
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  FileText, Plus, RefreshCw, Eye, Download, X, CheckCircle2, Loader2, Search, Package, Layers,
  ChevronRight, MoreHorizontal,
} from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { Skeleton } from '@/components/ui/skeleton';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { materialOptionLabel } from '@/lib/materialFields';
import { formatDateID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import HubTabs from './hubs/HubTabs';
import PeriodPicker, { ALL_TIME, PERIOD_PRESETS, periodFromPreset } from './finance/PeriodPicker';
import { EmptyState, StatusBadge } from './moduleAtoms';
import DocNumberField, { useDocNumberPolicy, docNumberPayload } from './docnum/DocNumberField';

const API = process.env.REACT_APP_BACKEND_URL;
const BATAS_SUMBER = 2000; // batas `limit` GET /delivery-notes/sources

const SOURCE_BADGE = {
  gudang: { label: 'Gudang', tone: 'success' },
  vendor: { label: 'Vendor CMT', tone: 'primary' },
  buyer: { label: 'Buyer', tone: 'info' },
};
const fmtQty = (n) => Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 2 });
const tgl = (d) => (d ? formatDateID(d) : '—');

const SJ_TYPES = {
  'SJ-CMT': { label: 'CMT' },
  'SJ-MAKLON': { label: 'Maklon' },
  'SJ-SUPPLIER': { label: 'Retur ke pemasok' },
  'SJ-INTERNAL': { label: 'Pindah antar lokasi' },
  'SJ-ONLINE': { label: 'Toko online' },
};

const STATUS_SJ = {
  draft: { label: 'Draf', tone: 'muted' },
  issued: { label: 'Terbit', tone: 'info' },
  received: { label: 'Diterima', tone: 'success' },
  cancelled: { label: 'Dibatalkan', tone: 'danger' },
};
function StatusSJ({ status }) {
  const s = STATUS_SJ[status] || { label: status || '—', tone: 'muted' };
  return <StatusBadge status={status} label={s.label} tone={s.tone} />;
}

// ─── Unduh PDF dokumen asli (bukan generator kedua) — nomor & isi tetap milik sumbernya. ─────────────────
async function unduhPdf(token, url, filename) {
  try {
    const r = await fetch(`${API}${url}`, { headers: { Authorization: `Bearer ${token}` } });
    if (!r.ok) {
      const t = await r.text().catch(() => '');
      throw new Error(t.slice(0, 160) || `HTTP ${r.status}`);
    }
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = window.URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    window.URL.revokeObjectURL(a.href);
    toast.success(`PDF ${filename} diunduh`);
  } catch (e) {
    toast.error(`Gagal mengunduh PDF: ${e.message}`, { duration: 8000 });
  }
}

function KotakCari({ value, onChange, placeholder, testId }) {
  return (
    <div className="relative w-full sm:w-64">
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
      <Input placeholder={placeholder} value={value} onChange={(e) => onChange(e.target.value)} className="pl-8" data-testid={testId} />
    </div>
  );
}

// ─── Tab 1 · Semua sumber (FASE H-7, hanya baca) ────────────────────────────────────────────────────────
// Satu daftar surat jalan lintas sumber: gudang, kirim material ke CMT, dispatch buyer. Tiap baris mencetak PDF
// RESMI dari dokumen aslinya dan bisa dibuka di modul sumbernya — tidak ada nomor baru & tidak ada generator kedua.
function TabSemuaSumber({ token, onNavigate, onBuat }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);
  const [allRows, setAllRows] = useState([]);
  const [allMeta, setAllMeta] = useState({ total: 0, by_source: {}, total_qty: 0 });
  const [counts, setCounts] = useState({});
  const [allLoading, setAllLoading] = useState(false);
  const [srcFilter, setSrcFilter] = useState('all');
  const [period, setPeriod] = useState(() => periodFromPreset('all'));
  const [search, setSearch] = useState('');
  const range = { from: period.from || '', to: period.to || '' };

  const loadAllSources = useCallback(async () => {
    setAllLoading(true);
    try {
      const p = new URLSearchParams();
      if (search) p.set('q', search);
      if (range.from) p.set('date_from', range.from);
      if (range.to) p.set('date_to', range.to);
      const pAll = new URLSearchParams(p);
      if (srcFilter && srcFilter !== 'all') p.set('source', srcFilter);
      p.set('limit', String(BATAS_SUMBER));
      const r = await fetch(`${API}/api/wms/delivery-notes/sources?${p}`, { headers });
      const d = await r.json();
      setAllRows(d.items || []);
      setAllMeta({ total: d.total || 0, by_source: d.by_source || {}, total_qty: d.total_qty || 0 });
      // Angka pil sumber: server menghitung `by_source` SESUDAH saringan sumber (pil lain jadi 0). Saat satu sumber
      // dipilih, angka per sumber diambil dari permintaan yang sama tanpa saringan sumber.
      if (srcFilter && srcFilter !== 'all') {
        pAll.set('limit', '1');
        const r2 = await fetch(`${API}/api/wms/delivery-notes/sources?${pAll}`, { headers });
        const d2 = await r2.json().catch(() => ({}));
        setCounts({ ...(d2.by_source || {}), all: d2.total || 0 });
      } else {
        setCounts({ ...(d.by_source || {}), all: d.total || 0 });
      }
    } catch {
      toast.error('Gagal memuat daftar surat jalan lintas sumber');
    } finally {
      setAllLoading(false);
    }
  }, [headers, srcFilter, search, range.from, range.to]);

  useEffect(() => {
    const t = setTimeout(loadAllSources, 250);
    return () => clearTimeout(t);
  }, [loadAllSources]);

  const downloadRecap = () => {
    const p = new URLSearchParams();
    if (srcFilter && srcFilter !== 'all') p.set('source', srcFilter);
    if (search) p.set('q', search);
    if (range.from) p.set('date_from', range.from);
    if (range.to) p.set('date_to', range.to);
    unduhPdf(token, `/api/wms/delivery-notes/sources/recap-pdf?${p}`, `rekap-surat-jalan-${range.from || 'semua'}.pdf`);
  };

  const kolom = [
    { kunci: 'no', label: 'No. surat jalan', hp: 'judul', isi: (r) => (
      <span className="font-medium md:whitespace-nowrap" data-testid={`sj-all-row-${r.number}`}>{r.number}</span>) },
    { kunci: 'sumber', label: 'Sumber', isi: (r) => {
      const b = SOURCE_BADGE[r.source] || SOURCE_BADGE.gudang;
      return <StatusBadge status={r.source} label={b.label} tone={b.tone} />;
    } },
    { kunci: 'jenis', label: 'Jenis', hp: false, isi: (r) => <span className="text-sm md:whitespace-nowrap">{r.doc_type || '—'}</span> },
    { kunci: 'tanggal', label: 'Tanggal', isi: (r) => <span className="text-sm md:whitespace-nowrap">{tgl(r.date)}</span> },
    { kunci: 'tujuan', label: 'Tujuan', hp: 'keterangan', isi: (r) => r.recipient || '—' },
    { kunci: 'acuan', label: 'Acuan', hp: false, isi: (r) => <span className="text-sm">{r.reference || '—'}</span> },
    { kunci: 'status', label: 'Status', isi: (r) => <span className="text-sm">{r.status || '—'}</span> },
    { kunci: 'baris', label: 'Baris', hp: false, rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.lines}</span> },
    { kunci: 'qty', label: 'Total qty', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtQty(r.qty)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <div className="inline-flex flex-wrap justify-end gap-1">
        <Button size="sm" variant="outline" onClick={() => unduhPdf(token, r.pdf_url, `${(r.number || 'surat-jalan').replace(/[/#]/g, '-')}.pdf`)}
          data-testid={`sj-all-pdf-${r.number}`}>
          <Download /> PDF
        </Button>
        {(r.pdf_alt_url || onNavigate) && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="icon-sm" variant="ghost" title="Lainnya" aria-label="Lainnya" data-testid={`sj-all-more-${r.number}`}>
                <MoreHorizontal />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {r.pdf_alt_url && (
                <DropdownMenuItem data-testid={`sj-all-pdf-alt-${r.number}`}
                  onSelect={() => unduhPdf(token, r.pdf_alt_url, `${(r.number || 'sj').replace(/[/#]/g, '-')}-kumulatif.pdf`)}>
                  <Download className="mr-2 h-4 w-4" />{r.pdf_alt_label || 'PDF kumulatif'}
                </DropdownMenuItem>
              )}
              {onNavigate && (
                <DropdownMenuItem onSelect={() => onNavigate(r.module)} data-testid={`sj-all-open-${r.number}`}>
                  <ChevronRight className="mr-2 h-4 w-4" />Buka sumber
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>) },
  ];

  const pil = [
    { key: 'all', label: 'Semua', count: counts.all ?? allMeta.total },
    { key: 'gudang', label: 'Gudang', count: counts.gudang ?? 0 },
    { key: 'vendor', label: 'Vendor CMT', count: counts.vendor ?? 0 },
    { key: 'buyer', label: 'Buyer', count: counts.buyer ?? 0 },
  ];

  return (
    <PageLayout testId="sj-all-sources-panel" title="Semua sumber"
      subtitle="Satu daftar surat jalan dari gudang, kirim material ke CMT, dan dispatch ke buyer."
      actions={<Button onClick={onBuat} data-testid="create-sj-btn"><Plus /> Surat jalan baru</Button>}
      filters={<>
        <FilterChips className="w-full sm:w-auto" value={srcFilter} onChange={setSrcFilter} options={pil} hideWhenEmpty={false}
          testId="sj-src" ariaLabel="Sumber surat jalan" />
        <KotakCari value={search} onChange={setSearch} placeholder="Cari nomor, tujuan, acuan" testId="search-sj-sources" />
        <PeriodPicker value={period} onChange={setPeriod} presets={[ALL_TIME, ...PERIOD_PRESETS]} testId="sj-period" />
        {/* Alat di akhir baris penyaring (bukan slot tools): di HP 390 px Toolbar bersama memeras penyaring. */}
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <TombolUnduh namaBerkas="surat-jalan-semua-sumber" namaLembar="Surat jalan" baris={allRows} testId="sj-all-export-csv"
            kolom={[
              { label: 'No. surat jalan', nilai: (r) => r.number },
              { label: 'Sumber', nilai: (r) => r.source_label || (SOURCE_BADGE[r.source] || SOURCE_BADGE.gudang).label },
              { label: 'Jenis', nilai: (r) => r.doc_type || '' },
              { label: 'Tanggal', nilai: (r) => tgl(r.date) },
              { label: 'Tujuan', nilai: (r) => r.recipient || '' },
              { label: 'Acuan (PO/ref)', nilai: (r) => r.reference || '' },
              { label: 'Status', nilai: (r) => r.status || '' },
              { label: 'Jumlah baris', nilai: (r) => Number(r.lines || 0) },
              { label: 'Total qty', nilai: (r) => Number(r.qty || 0) },
            ]} />
          <Button variant="outline" onClick={downloadRecap} disabled={!allRows.length} data-testid="sj-recap-pdf">
            <Download /> Cetak rekap
          </Button>
          <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={loadAllSources} disabled={allLoading}
            data-testid="sj-all-refresh">
            <RefreshCw className={allLoading ? 'animate-spin' : ''} />
          </Button>
        </div>
      </>}
      summary={
        // Verifikasi 8 Nov 2026: dulu juga "Total X qty" = jumlah qty lintas satuan (kg, m, pcs) dari tiga sumber —
        // tidak bermakna, dihapus. Jumlah dokumen = `total` server (semua baris hasil saringan).
        <p className="text-sm text-muted-foreground" data-testid="sj-sources-ringkas">
          <span className="font-medium tabular-nums text-foreground">{allMeta.total.toLocaleString('id-ID')}</span> surat jalan
          {allRows.length < allMeta.total ? ` (ditampilkan ${allRows.length.toLocaleString('id-ID')} terbaru)` : ''}. Tombol PDF
          mengunduh dokumen resmi dari sumbernya — nomornya tidak dibuat ulang di sini.
        </p>
      }>
      {allLoading && allRows.length === 0 ? (
        <div className="space-y-2" data-testid="sj-all-loading">
          {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}
        </div>
      ) : (
        <TabelData kolom={kolom} baris={allRows} kunci={(r) => r.key} testId="sj-all-sources-table"
          kosong={<EmptyState icon={FileText} title="Tidak ada surat jalan pada saringan ini"
            description="Ubah sumber atau periode, atau buat surat jalan gudang baru." />} />
      )}
    </PageLayout>
  );
}

// ─── Tab 2 · Surat jalan gudang (buat, terbitkan, terima, PDF) ─────────────────────────────────────────
function TabSJGudang({ token, onNavigate, onBuat, buatTerbuka, setBuatTerbuka }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);
  const [notes, setNotes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState('');
  const [search, setSearch] = useState('');
  // Bawaan: SJ paling BARU di atas (yang sedang dikerjakan gudang hari ini).
  const [urut, setUrut] = useState('created_at:desc');
  const [viewDialog, setViewDialog] = useState(null);

  // Semua halaman dimuat (dulu hanya halaman pertama = 50 SJ, lalu dihalamankan di layar → SJ ke-51 dst. hilang).
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const semua = [];
      for (let page = 1; page <= 50; page += 1) {
        const params = new URLSearchParams({ page: String(page), limit: '200' });
        if (search) params.set('search', search);
        const r = await fetch(`${API}/api/wms/delivery-notes?${params}`, { headers });
        const d = await r.json();
        semua.push(...(d.items || []));
        if (!d.pagination?.has_next) break;
      }
      setNotes(semua);
    } catch {
      toast.error('Gagal memuat surat jalan');
    } finally {
      setLoading(false);
    }
  }, [headers, search]);

  useEffect(() => {
    const t = setTimeout(load, 250);
    return () => clearTimeout(t);
  }, [load]);

  const handleIssue = async (id) => {
    try {
      const r = await fetch(`${API}/api/wms/delivery-notes/${id}/issue`, { method: 'POST', headers, body: JSON.stringify({}) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d?.detail || 'Gagal menerbitkan surat jalan');
      toast.success(d?.message || 'Surat jalan diterbitkan');
      load();
    } catch (err) {
      toast.error(err?.message || 'Gagal menerbitkan surat jalan', { duration: 9000 });
    }
  };

  const handleReceive = async (id) => {
    try {
      const r = await fetch(`${API}/api/wms/delivery-notes/${id}/receive`, {
        method: 'POST', headers, body: JSON.stringify({ received_by: '' }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d?.detail || 'Gagal konfirmasi terima surat jalan');
      toast.success('Surat jalan dikonfirmasi diterima');
      load();
    } catch (err) {
      toast.error(err?.message || 'Gagal konfirmasi terima surat jalan', { duration: 9000 });
    }
  };

  const handleDownloadPDF = async (id) => {
    try {
      const r = await fetch(`${API}/api/wms/delivery-notes/${id}/pdf`, { headers });
      if (!r.ok) throw new Error();
      const blob = await r.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `SJ-${id}.pdf`;
      a.click();
      toast.success('PDF berhasil diunduh');
    } catch {
      toast.error('Gagal mengunduh PDF');
    }
  };

  const hitung = (st) => notes.filter((n) => n.status === st).length;
  const filteredNotes = useMemo(() => {
    const base = status ? notes.filter((n) => n.status === status) : notes;
    const list = [...base];
    const [key, dir] = urut.split(':');
    list.sort((a, b) => {
      const av = key === 'lines' ? (a?.lines?.length || 0) : a?.[key];
      const bv = key === 'lines' ? (b?.lines?.length || 0) : b?.[key];
      const num = key === 'lines';
      const cmp = num ? (Number(av || 0) - Number(bv || 0))
        : String(av ?? '').localeCompare(String(bv ?? ''), 'id');
      return dir === 'asc' ? cmp : -cmp;
    });
    return list;
  }, [notes, status, urut]);

  // RC-UI-03: paginasi di layar (25/hal)
  const { page, setPage, totalPages, total, paged } = useClientPagination(filteredNotes, 25);

  const kolom = [
    { kunci: 'no', label: 'No. SJ', hp: 'judul', isi: (n) => (
      <span className="font-medium md:whitespace-nowrap" data-testid={`sj-row-${n.sj_number}`}>{n.sj_number}</span>) },
    { kunci: 'jenis', label: 'Jenis', hp: false, isi: (n) => <span className="text-sm">{SJ_TYPES[n.sj_type]?.label || n.sj_type || '—'}</span> },
    { kunci: 'status', label: 'Status', isi: (n) => <StatusSJ status={n.status} /> },
    { kunci: 'penerima', label: 'Penerima', hp: 'keterangan', isi: (n) => (
      <div className="min-w-0 md:max-w-[16rem]">
        <p className="truncate" title={n.recipient_name}>{n.recipient_name}</p>
        <p className="hidden truncate text-xs text-muted-foreground md:block" title={n.recipient_address}>{n.recipient_address}</p>
      </div>) },
    { kunci: 'kendaraan', label: 'Kendaraan', hp: false, isi: (n) => <span className="text-sm md:whitespace-nowrap">{n.vehicle_no || '—'}</span> },
    { kunci: 'item', label: 'Item', hp: false, rata: 'kanan', isi: (n) => <span className="tabular-nums">{n.lines?.length || 0}</span> },
    { kunci: 'dibuat', label: 'Dibuat', isi: (n) => <span className="text-sm md:whitespace-nowrap">{tgl(n.created_at)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (n) => (
      <div className="inline-flex flex-wrap justify-end gap-1">
        {n.status === 'draft' && (
          <Button size="sm" variant="outline" onClick={() => handleIssue(n.id)} data-testid={`issue-btn-${n.sj_number}`}>
            <CheckCircle2 /> Terbitkan
          </Button>
        )}
        {n.status === 'issued' && (
          <Button size="sm" variant="success" onClick={() => handleReceive(n.id)} data-testid={`receive-btn-${n.sj_number}`}>
            <CheckCircle2 /> Terima
          </Button>
        )}
        {n.status === 'received' && (
          <Button size="sm" variant="outline" onClick={() => handleDownloadPDF(n.id)} data-testid={`download-btn-${n.sj_number}`}>
            <Download /> PDF
          </Button>
        )}
        <Button size="icon-sm" variant="ghost" onClick={() => setViewDialog(n)} title="Rincian" aria-label="Rincian"
          data-testid={`view-btn-${n.sj_number}`}><Eye /></Button>
      </div>) },
  ];

  return (
    <PageLayout testId="sj-gudang-panel" title="Surat jalan gudang"
      subtitle="Buat, terbitkan, dan konfirmasi terima surat jalan gudang; PDF untuk dibawa pengirim."
      actions={<Button onClick={onBuat} data-testid="create-sj-btn"><Plus /> Surat jalan baru</Button>}
      filters={<>
        <FilterChips className="w-full sm:w-auto" value={status} onChange={setStatus} hideWhenEmpty={false} testId="sj-status"
          ariaLabel="Status surat jalan" options={[
            { key: '', label: 'Semua', count: notes.length },
            { key: 'draft', label: 'Draf', count: hitung('draft') },
            { key: 'issued', label: 'Terbit', count: hitung('issued') },
            { key: 'received', label: 'Diterima', count: hitung('received') },
          ]} />
        <KotakCari value={search} onChange={setSearch} placeholder="Cari nomor SJ, penerima" testId="search-sj-input" />
        <SmartNativeSelect value={urut} onChange={(e) => setUrut(e.target.value)} className="w-full" wrapperClassName="w-full sm:w-48"
          searchable={false} aria-label="Urutkan" data-testid="sj-sort">
          <option value="created_at:desc">Terbaru dulu</option>
          <option value="created_at:asc">Terlama dulu</option>
          <option value="sj_number:asc">No. SJ (A–Z)</option>
          <option value="recipient_name:asc">Penerima (A–Z)</option>
          <option value="status:asc">Status</option>
          <option value="lines:desc">Item terbanyak</option>
        </SmartNativeSelect>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {onNavigate && (
            // Dulu kotak "LANGKAH BERIKUTNYA" (OnwardCTA, huruf besar); tujuannya sama.
            <Button variant="outline" onClick={() => onNavigate('wms-stock-hub')} title="Cek posisi stok setelah barang keluar gudang"
              data-testid="sj-lihat-stok">
              <Package /> Lihat stok
            </Button>
          )}
          <TombolUnduh namaBerkas="surat-jalan" namaLembar="Surat jalan" baris={filteredNotes} testId="sj-export-csv"
            kolom={[
              { label: 'No. SJ', nilai: (n) => n.sj_number },
              { label: 'Jenis', nilai: (n) => SJ_TYPES[n.sj_type]?.label || n.sj_type || '' },
              { label: 'Status', nilai: (n) => (STATUS_SJ[n.status] || { label: n.status || '' }).label },
              { label: 'Penerima', nilai: (n) => n.recipient_name || '' },
              { label: 'Alamat', nilai: (n) => n.recipient_address || '' },
              { label: 'No. HP', nilai: (n) => n.recipient_phone || '' },
              { label: 'Pengirim', nilai: (n) => n.shipper_name || '' },
              { label: 'No. kendaraan', nilai: (n) => n.vehicle_no || '' },
              { label: 'Jumlah item', nilai: (n) => (n.lines?.length || 0) },
              { label: 'Dibuat', nilai: (n) => tgl(n.created_at) },
            ]} />
          <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={load} disabled={loading}
            data-testid="refresh-sj-btn">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
        </div>
      </>}
      footer={filteredNotes.length > 25 ? <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={25} onPageChange={setPage} /> : null}>
      {loading && notes.length === 0 ? (
        <div className="space-y-2" data-testid="loading-sj">
          {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}
        </div>
      ) : (
        <TabelData kolom={kolom} baris={paged} kunci={(n) => n.id} onKlikBaris={setViewDialog} testId="sj-table"
          kosong={<EmptyState icon={FileText} title={notes.length ? 'Tidak ada surat jalan yang cocok' : 'Belum ada surat jalan'}
            description={notes.length ? 'Ubah saringan status atau kata pencarian.' : 'Surat jalan muncul di sini setelah dibuat. Klik "Surat jalan baru" untuk memulai.'}
            testId="empty-sj" />} />
      )}

      <FormBuatSJ token={token} open={buatTerbuka} onClose={() => setBuatTerbuka(false)} onTersimpan={load} />

      {viewDialog && (
        <DetailPopup open onClose={() => setViewDialog(null)} judul={viewDialog.sj_number} testId="view-sj-dialog"
          status={<StatusSJ status={viewDialog.status} />}
          keterangan={SJ_TYPES[viewDialog.sj_type]?.label || viewDialog.sj_type}
          aksi={<>
            {viewDialog.status === 'draft' && (
              <Button size="sm" onClick={() => { handleIssue(viewDialog.id); setViewDialog(null); }}><CheckCircle2 /> Terbitkan</Button>
            )}
            {viewDialog.status === 'issued' && (
              <Button size="sm" variant="success" onClick={() => { handleReceive(viewDialog.id); setViewDialog(null); }}><CheckCircle2 /> Terima</Button>
            )}
            {(viewDialog.status === 'issued' || viewDialog.status === 'received') && (
              <Button size="sm" variant="outline" onClick={() => handleDownloadPDF(viewDialog.id)}><Download /> PDF</Button>
            )}
          </>}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Penerima">{viewDialog.recipient_name}</BarisDetail>
            <BarisDetail label="Telepon">{viewDialog.recipient_phone || '—'}</BarisDetail>
            <BarisDetail label="Alamat">{viewDialog.recipient_address}</BarisDetail>
            <BarisDetail label="Pengirim">{viewDialog.shipper_name || '—'}</BarisDetail>
            <BarisDetail label="Kendaraan">{viewDialog.vehicle_no || '—'}</BarisDetail>
            {(viewDialog.from_location_name || viewDialog.to_location_name) && (<>
              <BarisDetail label="Dari lokasi">{viewDialog.from_location_name || '—'}</BarisDetail>
              <BarisDetail label="Ke lokasi">{viewDialog.to_location_name || '—'}</BarisDetail>
              <BarisDetail label="Gerak stok">
                <span data-testid="view-sj-locations">
                  {viewDialog.stock_in_at ? 'Stok sudah masuk lokasi tujuan.'
                    : viewDialog.stock_out_at ? 'Stok sudah keluar dari lokasi asal — dalam perjalanan.'
                      : viewDialog.stock_legacy ? 'Surat jalan lama: stok tidak dipindah sistem (dokumen saja).'
                        : 'Stok belum bergerak (masih draf).'}
                </span>
              </BarisDetail>
            </>)}
            {viewDialog.notes && <BarisDetail label="Catatan">{viewDialog.notes}</BarisDetail>}
          </dl>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-base font-semibold text-foreground">Barang ({viewDialog.lines?.length || 0})</p>
            <TombolUnduh namaBerkas={`surat-jalan-${viewDialog.sj_number}`} namaLembar="Barang" baris={viewDialog.lines || []}
              testId="view-sj-unduh" kolom={[
                { label: 'No', nilai: (l) => l.line_no || '' },
                { label: 'Kode', nilai: (l) => l.material_code || '' },
                { label: 'Uraian', nilai: (l) => l.description || '' },
                { label: 'Qty', nilai: (l) => Number(l.qty || 0) },
                { label: 'Satuan', nilai: (l) => l.unit || '' },
                { label: 'Keterangan', nilai: (l) => l.remarks || '' },
              ]} />
          </div>
          <TabelData baris={(viewDialog.lines || []).map((l, i) => ({ ...l, _k: i }))} kunci={(l) => l._k} testId="view-sj-lines"
            kolom={[
              { kunci: 'uraian', label: 'Uraian', hp: 'judul', isi: (l) => (
                <div><p>{l.description}</p>{l.remarks && <p className="text-xs text-muted-foreground">{l.remarks}</p>}</div>) },
              { kunci: 'qty', label: 'Qty', rata: 'kanan', isi: (l) => <span className="tabular-nums">{fmtQty(l.qty)} {l.unit}</span> },
            ]}
            kosong={<p className="text-sm text-muted-foreground">Tidak ada barang.</p>} />
        </DetailPopup>
      )}
    </PageLayout>
  );
}

// ─── Form buat surat jalan (FormPopup panjang) ─────────────────────────────────────────────────────────
const BARIS_BARU = () => ({ line_no: 1, description: '', qty: 0, unit: 'pcs', remarks: '' });

function FormBuatSJ({ token, open, onClose, onTersimpan }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);
  // SESI #19 — kebijakan penomoran Surat Jalan Gudang (Otomatis/Manual) dibaca dari
  // Administrasi Sistem → Penomoran Dokumen supaya layar & backend tidak bisa berbeda.
  const [sjType, setSjType] = useState('');
  const numPolicy = useDocNumberPolicy('wh_delivery_notes.sj_number', token,
    // {TIPE} ikut menentukan nomor, jadi pratinjaunya harus memakai tipe yang BENAR-BENAR dipilih.
    useMemo(() => ({ TIPE: sjType }), [sjType]));
  const [sjNumber, setSjNumber] = useState('');
  const [f, setF] = useState({ recipient_name: '', recipient_address: '', recipient_phone: '', shipper_name: '', vehicle_no: '', notes: '' });
  const [editingLines, setEditingLines] = useState([BARIS_BARU()]);
  // FASE P4: auto-isi Surat Jalan Internal dari BOM aktif (yarn + aksesoris) x qty job
  const [jobs, setJobs] = useState([]);
  const [selectedJobId, setSelectedJobId] = useState('');
  const [bomLoading, setBomLoading] = useState(false);
  // 2026-11-06 (Tahap 2): SJ internal = transfer antar lokasi — lokasi asal/tujuan + barang dari master.
  const [fromLoc, setFromLoc] = useState('');
  const [toLoc, setToLoc] = useState('');
  const [storageLocs, setStorageLocs] = useState([]);
  const [materials, setMaterials] = useState([]);
  const [menyimpan, setMenyimpan] = useState(false);
  const [galat, setGalat] = useState('');
  const isInternal = sjType === 'SJ-INTERNAL';
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }));

  useEffect(() => {
    if (!open || !isInternal || storageLocs.length) return;
    (async () => {
      try {
        const [a, b] = await Promise.all([
          fetch(`${API}/api/rahaza/storage-locations`, { headers }),
          fetch(`${API}/api/rahaza/materials`, { headers }),
        ]);
        if (a.ok) setStorageLocs(await a.json());
        if (b.ok) {
          const m = await b.json();
          setMaterials(Array.isArray(m) ? m : (m.items || []));
        }
      } catch { /* daftar pilihan tetap kosong; simpan ditolak backend dengan pesan jelas */ }
    })();
  }, [open, isInternal, storageLocs.length, headers]);

  useEffect(() => {
    if (!open) return;
    (async () => {
      try {
        const r = await fetch(`${API}/api/production-jobs?business_type=internal`, { headers });
        const d = await r.json();
        setJobs(Array.isArray(d) ? d : (d.items || []));
      } catch { /* senyap — pilihan BOM opsional */ }
    })();
  }, [open, headers]);

  const reset = () => {
    setSjNumber(''); setSjType(''); setF({ recipient_name: '', recipient_address: '', recipient_phone: '', shipper_name: '', vehicle_no: '', notes: '' });
    setEditingLines([BARIS_BARU()]); setSelectedJobId(''); setFromLoc(''); setToLoc(''); setGalat('');
  };
  const tutup = () => { setSelectedJobId(''); setGalat(''); onClose(); };

  const handleCreate = async () => {
    setGalat('');
    if (!sjType) { setGalat('Pilih tipe surat jalan.'); return; }
    if (!f.recipient_name.trim() || !f.recipient_address.trim()) { setGalat('Nama dan alamat penerima wajib diisi.'); return; }
    const data = {
      sj_type: sjType,
      ...docNumberPayload(numPolicy, 'sj_number', sjNumber),
      recipient_name: f.recipient_name,
      recipient_address: f.recipient_address,
      recipient_phone: f.recipient_phone || '',
      shipper_name: f.shipper_name || '',
      vehicle_no: f.vehicle_no || '',
      notes: f.notes || '',
      lines: editingLines.filter(l => l.description || l.material_id),
      ...(isInternal ? { from_location_id: fromLoc, to_location_id: toLoc } : {}),
    };
    setMenyimpan(true);
    try {
      const r = await fetch(`${API}/api/wms/delivery-notes`, { method: 'POST', headers, body: JSON.stringify(data) });
      // SESI #19 — penolakan penomoran berisi jalan keluarnya (pola nomor yang benar) — tampilkan apa adanya.
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d?.detail || 'Gagal membuat surat jalan');
      toast.success('Surat jalan berhasil dibuat');
      reset();
      onClose();
      onTersimpan();
    } catch (err) {
      setGalat(err?.message || 'Gagal membuat surat jalan');
    } finally {
      setMenyimpan(false);
    }
  };

  const addLine = () => setEditingLines([...editingLines, { line_no: editingLines.length + 1, description: '', qty: 0, unit: 'pcs', remarks: '' }]);
  const removeLine = (idx) => setEditingLines(editingLines.filter((_, i) => i !== idx));
  const updateLine = (idx, field, value) => {
    const updated = [...editingLines];
    updated[idx][field] = value;
    setEditingLines(updated);
  };
  // SJ internal: barang dipilih dari master → kode, uraian, satuan ikut master.
  const pickMaterial = (idx, mid) => {
    const m = materials.find((x) => x.id === mid);
    const updated = [...editingLines];
    updated[idx] = { ...updated[idx], material_id: mid, material_code: m?.code || '',
      description: m?.name || updated[idx].description, unit: m?.unit || updated[idx].unit };
    setEditingLines(updated);
  };

  // FASE P4: ambil baris material dari BOM aktif job internal & append ke item pengiriman.
  const handleFillFromBOM = async () => {
    if (!selectedJobId) { toast.error('Pilih job produksi internal dulu'); return; }
    setBomLoading(true);
    try {
      const r = await fetch(`${API}/api/production-jobs/${selectedJobId}/bom-material-lines`, { headers });
      if (!r.ok) throw new Error();
      const d = await r.json();
      const bomLines = d.lines || [];
      if (bomLines.length === 0) {
        toast.warning('Tidak ada baris BOM untuk job ini (BOM belum aktif / item tanpa BOM)');
        return;
      }
      setEditingLines((prev) => {
        const existing = prev.filter((l) => l.description && l.description.trim());
        const merged = [
          ...existing,
          ...bomLines.map((l) => ({ description: l.description, qty: l.qty, unit: l.unit, remarks: l.remarks || '' })),
        ];
        return merged.map((l, i) => ({ ...l, line_no: i + 1 }));
      });
      toast.success(`${bomLines.length} baris material BOM ditambahkan (Job ${d.job_number || ''})`);
      if (Array.isArray(d.missing_bom) && d.missing_bom.length > 0) {
        toast.warning(`${d.missing_bom.length} item job tidak punya BOM aktif dan dilewati`);
      }
    } catch {
      toast.error('Gagal mengambil baris BOM job');
    } finally {
      setBomLoading(false);
    }
  };

  return (
    <FormPopup open={open} onClose={tutup} ukuran="panjang" judul="Surat jalan baru" testId="create-sj-dialog"
      keterangan="Surat jalan dibuat sebagai draf; stok bergerak saat diterbitkan."
      onSimpan={handleCreate} menyimpan={menyimpan} galat={galat} labelSimpan="Simpan">
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Tipe surat jalan" wajib>
          <SmartNativeSelect value={sjType} onChange={(e) => setSjType(e.target.value)} className="w-full" searchable={false}
            aria-label="Tipe surat jalan" data-testid="input-sj-type">
            <option value="">Pilih tipe</option>
            {Object.entries(SJ_TYPES).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Nama penerima" wajib htmlFor="sj-recipient-name">
          <Input id="sj-recipient-name" value={f.recipient_name} onChange={set('recipient_name')} data-testid="input-recipient-name" />
        </Isian>
      </div>

      {/* SESI #19 — kolom nomor mengikuti kebijakan Otomatis/Manual owner. Tanpa kolom ini, setelan MANUAL
          membuat surat jalan TIDAK BISA dibuat ("nomor wajib diisi"). */}
      <DocNumberField policy={numPolicy} value={sjNumber} onChange={setSjNumber} label="Nomor surat jalan" testId="sj-number" />

      {isInternal && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2" data-testid="sj-internal-locations">
          <Isian label="Dari lokasi" wajib>
            <SmartNativeSelect value={fromLoc} onChange={(e) => setFromLoc(e.target.value)} className="w-full" aria-label="Dari lokasi"
              data-testid="input-sj-from-location">
              <option value="">Pilih lokasi asal</option>
              {storageLocs.map((l) => <option key={l.id} value={l.id}>{l.code}{l.name ? ` · ${l.name}` : ''}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Ke lokasi" wajib>
            <SmartNativeSelect value={toLoc} onChange={(e) => setToLoc(e.target.value)} className="w-full" aria-label="Ke lokasi"
              data-testid="input-sj-to-location">
              <option value="">Pilih lokasi tujuan</option>
              {storageLocs.filter((l) => l.id !== fromLoc).map((l) => <option key={l.id} value={l.id}>{l.code}{l.name ? ` · ${l.name}` : ''}</option>)}
            </SmartNativeSelect>
          </Isian>
          <p className="text-xs text-muted-foreground sm:col-span-2">
            Saat diterbitkan, stok keluar dari lokasi asal dan tercatat dalam perjalanan. Stok masuk ke lokasi tujuan saat
            surat jalan dikonfirmasi diterima. Barang setiap baris wajib dipilih dari master.
          </p>
        </div>
      )}

      <Isian label="Alamat penerima" wajib htmlFor="sj-recipient-address">
        <Textarea id="sj-recipient-address" rows={2} value={f.recipient_address} onChange={set('recipient_address')} data-testid="input-recipient-address" />
      </Isian>
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Telepon penerima" htmlFor="sj-recipient-phone">
          <Input id="sj-recipient-phone" value={f.recipient_phone} onChange={set('recipient_phone')} inputMode="tel" data-testid="input-recipient-phone" />
        </Isian>
        <Isian label="Nama pengirim" htmlFor="sj-shipper-name">
          <Input id="sj-shipper-name" value={f.shipper_name} onChange={set('shipper_name')} data-testid="input-shipper-name" />
        </Isian>
        <Isian label="Nomor kendaraan" htmlFor="sj-vehicle-no">
          <Input id="sj-vehicle-no" value={f.vehicle_no} onChange={set('vehicle_no')} data-testid="input-vehicle-no" />
        </Isian>
        <Isian label="Catatan" htmlFor="sj-notes">
          <Input id="sj-notes" value={f.notes} onChange={set('notes')} data-testid="input-sj-notes" />
        </Isian>
      </div>

      {/* FASE P4: Auto-isi dari BOM (Job Produksi Internal) */}
      <div className="space-y-2 border-t border-[var(--glass-border)] pt-4">
        <p className="flex items-center gap-2 text-sm font-medium text-foreground"><Layers className="h-4 w-4 text-primary" /> Isi dari BOM (job internal)</p>
        <p className="text-xs text-muted-foreground">
          Pilih job produksi internal untuk menambahkan kebutuhan material (bahan + aksesoris) dari BOM aktif.
          Kuantitas dihitung otomatis = qty BOM per unit × qty job.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <div className="min-w-0 flex-1">
            <SmartNativeSelect value={selectedJobId} onChange={(e) => setSelectedJobId(e.target.value)} className="w-full"
              aria-label="Job produksi internal" data-testid="bom-job-select">
              <option value="">{jobs.length ? 'Pilih job produksi internal' : 'Tidak ada job internal'}</option>
              {jobs.map((j) => (
                <option key={j.id} value={j.id}>{j.job_number} · {j.status}{j.total_available ? ` · ${j.total_available} pcs` : ''}</option>
              ))}
            </SmartNativeSelect>
          </div>
          <Button type="button" variant="outline" onClick={handleFillFromBOM} disabled={bomLoading || !selectedJobId} data-testid="fill-from-bom-btn">
            {bomLoading ? <Loader2 className="animate-spin" /> : <Layers />} Isi dari BOM
          </Button>
        </div>
      </div>

      {/* Baris barang */}
      <div className="space-y-2 border-t border-[var(--glass-border)] pt-4">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-medium text-foreground">Barang dikirim</p>
          <Button type="button" size="sm" variant="outline" onClick={addLine} data-testid="add-line-btn"><Plus /> Tambah barang</Button>
        </div>
        <div className="divide-y divide-[var(--glass-border)]">
          {editingLines.map((line, idx) => (
            <div key={idx} className="flex items-start gap-2 py-2">
              <div className="grid flex-1 grid-cols-2 gap-2 sm:grid-cols-4">
                {isInternal ? (
                  <div className="col-span-2">
                    <SmartNativeSelect value={line.material_id || ''} onChange={(e) => pickMaterial(idx, e.target.value)} className="w-full"
                      aria-label="Barang" data-testid={`line-material-${idx}`}>
                      <option value="">Pilih barang dari master</option>
                      {materials.map((m) => <option key={m.id} value={m.id}>{materialOptionLabel(m)}</option>)}
                    </SmartNativeSelect>
                  </div>
                ) : (
                  <Input placeholder="Uraian barang" value={line.description} aria-label="Uraian barang"
                    onChange={(e) => updateLine(idx, 'description', e.target.value)} className="col-span-2" data-testid={`line-desc-${idx}`} />
                )}
                <Input type="number" placeholder="Qty" value={line.qty} aria-label="Qty" inputMode="decimal"
                  onChange={(e) => updateLine(idx, 'qty', parseFloat(e.target.value) || 0)} data-testid={`line-qty-${idx}`} />
                {/* 2026-11-07 (Tahap 5): barang dari master → satuan = satuan dasar barang (terkunci). Dulu bisa diketik
                    bebas sehingga "12 lusin" tercatat sebagai 12 pcs saat stok dipindah. */}
                <Input placeholder="Satuan" value={line.unit} aria-label="Satuan" onChange={(e) => updateLine(idx, 'unit', e.target.value)}
                  disabled={isInternal && !!line.material_id}
                  title={isInternal && line.material_id ? 'Satuan dasar barang dari master' : undefined}
                  data-testid={`line-unit-${idx}`} />
              </div>
              <Button type="button" size="icon-sm" variant="ghost" onClick={() => removeLine(idx)} title="Hapus baris" aria-label="Hapus baris"
                data-testid={`remove-line-${idx}`}>
                <X />
              </Button>
            </div>
          ))}
        </div>
      </div>
    </FormPopup>
  );
}

export default function WMSDeliveryNotesModule({ token, onNavigate }) {
  const [tab, setTab] = useState('sources');
  const [buatTerbuka, setBuatTerbuka] = useState(false);
  // Tombol "Surat jalan baru" ada di kedua tab; form-nya milik tab SJ gudang.
  const onBuat = useCallback(() => { setTab('gudang'); setBuatTerbuka(true); }, []);
  const tabs = useMemo(() => [
    // FASE H-7 — pintu utama: SATU daftar lintas sumber
    { key: 'sources', label: 'Semua sumber', Component: TabSemuaSumber },
    { key: 'gudang', label: 'SJ gudang', Component: TabSJGudang },
  ], []);
  return (
    <div data-testid="wms-delivery-notes-module">
      <HubTabs hubId="wms-delivery-notes" title="Surat Jalan"
        subtitle="Surat jalan gudang, kirim material ke CMT, dan dispatch ke buyer dalam satu tempat."
        tabs={tabs} value={tab} onValueChange={setTab}
        token={token} onNavigate={onNavigate} onBuat={onBuat} buatTerbuka={buatTerbuka} setBuatTerbuka={setBuatTerbuka} />
    </div>
  );
}

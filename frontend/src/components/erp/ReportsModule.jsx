/**
 * Laporan Umum (Portal Manajemen) — laporan data SSOT: PO produksi, job, buku kuantitas, penerimaan CMT,
 * pengiriman, faktur piutang, permintaan material, per klien maklon. Domain dipisah (keputusan owner).
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout; jenis laporan = satu pilihan (dulu 8 kartu besar), domain = pil,
 * periode = PeriodPicker (dulu dua <input type="date">), semua dalam satu baris penyaring; tabel standar dengan judul
 * kolom & status berbahasa biasa; unduh Excel/CSV = SEMUA baris hasil saringan (dulu CSV hanya halaman yang tampil
 * dan Excel server tidak ikut domain); PDF (pilih kolom) tetap. Kartu ringkasan dihitung dari baris yang dimuat —
 * bila data lebih dari satu halaman, labelnya menyebut "halaman ini" (dulu tampil seolah total).
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { FileText, RefreshCw, Search } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import FilterChips from '@/components/ui/filter-chips';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { GlassCard } from '@/components/ui/glass';
import PaginationBar from './PaginationBar';
import { PdfColumnPicker } from './pdf/PdfColumnPicker';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from './moduleAtoms';
import PeriodPicker, { ALL_TIME, PERIOD_PRESETS } from './finance/PeriodPicker';
import { formatRupiah } from '@/lib/format';
import { todayWIB } from '@/lib/waktu';

const REPORT_TYPES = [
  { id: 'production', label: 'Laporan produksi', description: 'PO + item + buku kuantitas (produksi/diterima/ditolak).' },
  { id: 'per-po', label: 'Rekap per PO', description: 'Satu baris per PO: pesan, produksi, terima, kirim, nilai order.' },
  { id: 'progress', label: 'Laporan progres', description: 'Catatan progres produksi harian per job.' },
  { id: 'financial', label: 'Laporan keuangan', description: 'Faktur piutang: tagihan, terbayar, sisa piutang.' },
  { id: 'shipment', label: 'Laporan pengiriman', description: 'Surat jalan ke buyer + qty barang jadi keluar.' },
  { id: 'rework', label: 'Laporan ditolak & permak', description: 'Baris penerimaan CMT yang ditolak + tindak lanjut permak.' },
  { id: 'material-issue', label: 'Permintaan material', description: 'Pengeluaran material dari gudang ke job.' },
  { id: 'per-client', label: 'Laporan per klien maklon', description: 'KPI & HPP per klien maklon.' },
];

/* Domain wajib dipisah (keputusan owner): produksi internal DA vs maklon. */
const DOMAIN_TABS = [
  { key: 'all', label: 'Gabungan' },
  { key: 'internal', label: 'Internal DA' },
  { key: 'maklon', label: 'Maklon' },
];

const BULAN = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
const fmt = formatRupiah;
const fmtDate = (d) => {
  if (!d) return '—';
  const s = String(d);
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) {
    const [y, m, dd] = s.slice(0, 10).split('-').map(Number);
    return `${String(dd).padStart(2, '0')} ${BULAN[m - 1]} ${y}`;
  }
  const t = new Date(d);
  return Number.isNaN(t.getTime()) ? s : `${String(t.getDate()).padStart(2, '0')} ${BULAN[t.getMonth()]} ${t.getFullYear()}`;
};
const fmtNum = (v) => (v || 0).toLocaleString('id-ID');

// Kode status dari server → label + nada StatusBadge.
const STATUS = {
  paid: ['Lunas', 'success'], issued: ['Terbit', 'info'], sent: ['Terkirim', 'info'], partial_paid: ['Dibayar sebagian', 'warning'],
  partial: ['Sebagian', 'warning'], overdue: ['Lewat jatuh tempo', 'danger'], unpaid: ['Belum dibayar', 'warning'],
  draft: ['Draf', 'muted'], cancelled: ['Dibatalkan', 'muted'], void: ['Dibatalkan', 'muted'], closed: ['Ditutup', 'muted'],
  completed: ['Selesai', 'success'], done: ['Selesai', 'success'], received: ['Diterima', 'success'], approved: ['Disetujui', 'success'],
  in_progress: ['Sedang dikerjakan', 'info'], in_production: ['Diproduksi', 'info'], running: ['Berjalan', 'info'],
  confirmed: ['Dikonfirmasi', 'info'], released: ['Dirilis', 'info'], pending: ['Menunggu', 'warning'], rejected: ['Ditolak', 'danger'],
  delivered: ['Terkirim', 'success'], shipped: ['Dikirim', 'info'], posted: ['Diposting', 'success'],
};
const statusInfo = (v) => {
  if (v === null || v === undefined || v === '' || v === '-') return null;
  const k = String(v).toLowerCase().replace(/\s+/g, '_');
  if (STATUS[k]) return { label: STATUS[k][0], tone: STATUS[k][1] };
  const t = String(v).replace(/_/g, ' ');
  return { label: t.charAt(0).toUpperCase() + t.slice(1), tone: 'default' };
};
const KOLOM_STATUS = new Set(['status', 'status_po', 'status_bayar', 'status_permak', 'inspection_status']);
// Judul kolom: HURUF BESAR → kalimat biasa (istilah Inggris diterjemahkan).
const ISTILAH = { 'no invoice': 'no. faktur', deadline: 'tenggat', reject: 'ditolak', rework: 'permak', 'on time': 'tepat waktu', 'fg keluar': 'barang jadi keluar', 'total order': 'total order' };
function kalimat(label) {
  let s = String(label || '').toLowerCase();
  Object.entries(ISTILAH).forEach(([k, v]) => { s = s.replace(new RegExp(`\\b${k}\\b`, 'g'), v); });
  s = s.replace(/\bno (\w)/g, 'no. $1').replace(/\b(po|sku|mi|hpp|cmt|qty)\b/g, (m) => (m === 'qty' ? 'qty' : m.toUpperCase()));
  return s.charAt(0).toUpperCase() + s.slice(1);
}
const PER_HALAMAN_UNDUH = 200;

export default function ReportsModule({ token }) {
  const [activeReport, setActiveReport] = useState('production');
  const [domain, setDomain] = useState('all');
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);

  // Pagination state
  const [page, setPage] = useState(1);
  const [limit] = useState(50);
  const [pagination, setPagination] = useState(null); // {page, limit, total, total_pages, has_next, has_prev}

  // Filters
  const [filters, setFilters] = useState({
    date_from: '', date_to: '', status: ''
  });
  // W2 — dialog pemilih kolom PDF (per jenis laporan)
  const [pickerOpen, setPickerOpen] = useState(false);

  // Reset page when report type changes
  useEffect(() => {
    setPage(1);
    setPagination(null);
    fetchReport(1);
  }, [activeReport, domain]); // eslint-disable-line

  // When page changes, re-fetch
  useEffect(() => {
    fetchReport(page);
  }, [page]); // eslint-disable-line

  // 2026-08-06: 'per-po' dulu di-hardcode kosong di FE (setData([])) sehingga laporan
  // ini SELALU kosong. Sekarang dilayani backend SSOT seperti tipe lainnya.
  const PAGINATED_TYPES = ['production', 'per-po', 'progress', 'financial', 'shipment', 'rework', 'material-issue'];

  const fetchReport = useCallback(async (targetPage = 1) => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      Object.entries(filters).forEach(([k, v]) => { if (v) params.append(k, v); });
      params.set('domain', domain);

      let res;
      if (activeReport === 'per-client') {
        // Per Client report - fetch all clients with analysis
        res = await fetch(`/api/dewi/maklon/clients`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        const clients = await res.json();
        // Fetch analysis for each client (simplified - in production would batch this)
        const clientData = [];
        for (const client of clients.slice(0, 10)) { // limit to 10 for performance
          try {
            const analysisRes = await fetch(`/api/rahaza/hpp/maklon-client/${client.id}`, {
              headers: { Authorization: `Bearer ${token}` }
            });
            if (analysisRes.ok) {
              const analysis = await analysisRes.json();
              clientData.push({
                client_code: client.code,
                client_name: client.name,
                total_orders: analysis.total_orders,
                total_qty: analysis.total_qty,
                total_revenue: analysis.total_revenue,
                total_hpp: analysis.total_hpp_actual,
                margin: analysis.margin_amount,
                margin_pct: analysis.margin_pct,
                on_time_rate: analysis.on_time_rate,
              });
            }
          } catch (e) {
            // Skip failed client
          }
        }
        setData(clientData);
        setPagination(null);
      } else if (PAGINATED_TYPES.includes(activeReport)) {
        // Paginated reports
        params.set('page', targetPage);
        params.set('limit', limit);
        res = await fetch(`/api/rahaza/reports/${activeReport}?${params.toString()}`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        const result = await res.json();
        if (result && result.items && result.pagination) {
          setData(result.items);
          setPagination(result.pagination);
        } else {
          // Fallback: legacy response
          setData(Array.isArray(result) ? result : []);
          setPagination(null);
        }
      } else {
        res = await fetch(`/api/rahaza/reports/${activeReport}?${params.toString()}`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        const result = await res.json();
        setData(Array.isArray(result) ? result : []);
        setPagination(null);
      }
    } catch (e) {
      setData([]);
      setPagination(null);
    }
    setLoading(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeReport, filters, token, limit, domain]);

  const resetFilters = () => {
    setFilters({ date_from: '', date_to: '', status: '' });
  };


  // PDF export
  // W2 (sesi #29) — kolom DIPILIH PEMAKAI tepat sebelum mencetak. Sebelum ini
  // daftar kolom hanya bisa diubah di layar setelan, sehingga kolom Serial No
  // (yang sudah ada di katalog PDF) tidak pernah bisa dipilih dari sini.
  const exportToPDF = async (cols) => {
    if (!data.length) return;
    try {
      const params = new URLSearchParams({ type: `report-${activeReport}` });
      Object.entries(filters).forEach(([k, v]) => { if (v) params.append(k, v); });
      if (Array.isArray(cols) && cols.length) params.append('cols', cols.join(','));
      const res = await fetch(`/api/export-pdf?${params.toString()}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `laporan_${activeReport}_${todayWIB()}.pdf`;
        a.click();
        URL.revokeObjectURL(url);
      } else {
        // Fallback: CSV download
        toast.error('PDF gagal dibuat. Coba unduh Excel/CSV.');
      }
    } catch (e) {
      toast.error(`PDF gagal dibuat: ${e.message}`);
    }
  };


  const getColumns = () => {
    switch (activeReport) {
      case 'production':
        return [
          { key: 'tanggal', label: 'TANGGAL', format: 'date' },
          { key: 'no_po', label: 'NO PO' },
          { key: 'domain', label: 'DOMAIN' },
          { key: 'pelanggan', label: 'PELANGGAN' },
          { key: 'vendor', label: 'PELAKSANA' },
          { key: 'sku', label: 'SKU' },
          { key: 'produk', label: 'PRODUK' },
          { key: 'ukuran', label: 'UKURAN' },
          { key: 'warna', label: 'WARNA' },
          { key: 'qty_pesan', label: 'QTY PESAN', format: 'number' },
          { key: 'qty_produksi', label: 'QTY PRODUKSI', format: 'number' },
          { key: 'qty_diterima', label: 'QTY DITERIMA', format: 'number' },
          { key: 'qty_reject', label: 'QTY REJECT', format: 'number' },
          { key: 'pct_selesai', label: '% SELESAI', format: 'number' },
          { key: 'status_po', label: 'STATUS PO' },
          { key: 'deadline', label: 'DEADLINE', format: 'date' },
        ];
      case 'per-po':
        return [
          { key: 'tanggal', label: 'TANGGAL', format: 'date' },
          { key: 'no_po', label: 'NO PO' },
          { key: 'domain', label: 'DOMAIN' },
          { key: 'pelanggan', label: 'PELANGGAN' },
          { key: 'status_po', label: 'STATUS' },
          { key: 'baris_item', label: 'ITEM', format: 'number' },
          { key: 'qty_pesan', label: 'QTY PESAN', format: 'number' },
          { key: 'qty_produksi', label: 'PRODUKSI', format: 'number' },
          { key: 'qty_diterima', label: 'DITERIMA', format: 'number' },
          { key: 'qty_reject', label: 'REJECT', format: 'number' },
          { key: 'qty_rework_terbuka', label: 'REWORK', format: 'number' },
          { key: 'qty_selisih_kirim', label: 'SELISIH KIRIM', format: 'number' },
          { key: 'qty_kirim_buyer', label: 'KIRIM BUYER', format: 'number' },
          { key: 'jumlah_job', label: 'JOB', format: 'number' },
          { key: 'jumlah_penerimaan', label: 'PENERIMAAN', format: 'number' },
          { key: 'pct_selesai', label: '% SELESAI', format: 'number' },
          { key: 'nilai_order', label: 'NILAI ORDER', format: 'currency' },
          { key: 'status_bayar', label: 'BAYAR' },
          { key: 'deadline', label: 'DEADLINE', format: 'date' },
        ];
      case 'progress':
        return [
          { key: 'tanggal', label: 'TANGGAL', format: 'date' },
          { key: 'no_job', label: 'NO JOB' },
          { key: 'no_po', label: 'NO PO' },
          { key: 'pelanggan', label: 'PELANGGAN' },
          { key: 'pelaksana', label: 'PELAKSANA' },
          { key: 'sku', label: 'SKU' },
          { key: 'produk', label: 'PRODUK' },
          { key: 'ukuran', label: 'UKURAN' },
          { key: 'warna', label: 'WARNA' },
          { key: 'qty', label: 'QTY', format: 'number' },
          { key: 'dicatat_oleh', label: 'DICATAT OLEH' },
          { key: 'catatan', label: 'CATATAN' },
        ];
      case 'financial':
        return [
          { key: 'tanggal', label: 'TANGGAL', format: 'date' },
          { key: 'no_invoice', label: 'NO INVOICE' },
          { key: 'pelanggan', label: 'PELANGGAN' },
          { key: 'no_po_maklon', label: 'NO PO MAKLON' },
          { key: 'subtotal', label: 'SUBTOTAL', format: 'currency' },
          { key: 'pajak', label: 'PAJAK', format: 'currency' },
          { key: 'total', label: 'TOTAL', format: 'currency' },
          { key: 'terbayar', label: 'TERBAYAR', format: 'currency' },
          { key: 'sisa', label: 'SISA', format: 'currency' },
          { key: 'status', label: 'STATUS' },
          { key: 'jatuh_tempo', label: 'JATUH TEMPO', format: 'date' },
          { key: 'sumber', label: 'SUMBER' },
        ];
      case 'shipment':
        return [
          { key: 'tanggal', label: 'TANGGAL', format: 'date' },
          { key: 'no_pengiriman', label: 'NO SURAT JALAN' },
          { key: 'no_po', label: 'NO PO' },
          { key: 'pelanggan', label: 'PELANGGAN' },
          { key: 'vendor', label: 'PELAKSANA' },
          { key: 'baris', label: 'BARIS', format: 'number' },
          { key: 'qty', label: 'QTY KIRIM', format: 'number' },
          { key: 'qty_fg_keluar', label: 'FG KELUAR', format: 'number' },
          { key: 'status', label: 'STATUS' },
          { key: 'catatan', label: 'CATATAN' },
        ];
      case 'rework':
        return [
          { key: 'tanggal', label: 'TANGGAL', format: 'date' },
          { key: 'no_penerimaan', label: 'NO PENERIMAAN' },
          { key: 'no_po', label: 'NO PO' },
          { key: 'vendor_cmt', label: 'VENDOR CMT' },
          { key: 'sku', label: 'SKU' },
          { key: 'produk', label: 'PRODUK' },
          { key: 'ukuran', label: 'UKURAN' },
          { key: 'warna', label: 'WARNA' },
          { key: 'qty_diterima', label: 'QTY DITERIMA', format: 'number' },
          { key: 'qty_reject', label: 'QTY REJECT', format: 'number' },
          { key: 'alasan_reject', label: 'ALASAN' },
          { key: 'tindak_lanjut', label: 'TINDAK LANJUT' },
          { key: 'status_permak', label: 'STATUS PERMAK' },
        ];
      case 'material-issue':
        return [
          { key: 'tanggal', label: 'TANGGAL', format: 'date' },
          { key: 'no_mi', label: 'NO MI' },
          { key: 'no_po', label: 'NO PO' },
          { key: 'no_job', label: 'NO JOB' },
          { key: 'material', label: 'MATERIAL' },
          { key: 'qty_diminta', label: 'QTY DIMINTA', format: 'number' },
          { key: 'qty_dikeluarkan', label: 'QTY KELUAR', format: 'number' },
          { key: 'satuan', label: 'SATUAN' },
          { key: 'status', label: 'STATUS' },
          { key: 'dibuat_oleh', label: 'DIBUAT OLEH' },
          { key: 'catatan', label: 'CATATAN' },
        ];
      case 'per-client':
        return [
          { key: 'client_code', label: 'KODE KLIEN' },
          { key: 'client_name', label: 'NAMA KLIEN' },
          { key: 'total_orders', label: 'TOTAL ORDER', format: 'number' },
          { key: 'total_qty', label: 'TOTAL QTY', format: 'number' },
          { key: 'total_revenue', label: 'PENDAPATAN', format: 'currency' },
          // Tahap 1: HPP & margin order maklon belum ada sumbernya (null) → "–", bukan Rp 0
          { key: 'total_hpp', label: 'HPP', format: 'currency', nullable: true },
          { key: 'margin', label: 'MARGIN', format: 'currency', nullable: true },
          { key: 'margin_pct', label: 'MARGIN %', format: 'number', nullable: true },
          { key: 'on_time_rate', label: 'ON TIME %', format: 'number' },
        ];
      default: return [];
    }
  };


  // Periode = PeriodPicker (bawaan "Semua waktu", sama dengan isian tanggal kosong dulu); status = teks, diterapkan
  // dengan Enter / tombol Terapkan. Perubahan penyaring memuat ulang halaman 1.
  const [period, setPeriod] = useState({ preset: 'all', from: '', to: '' });
  const [statusDraft, setStatusDraft] = useState('');
  const awalFilter = useRef(true);
  useEffect(() => {
    if (awalFilter.current) { awalFilter.current = false; return; }
    setPage(1);
    fetchReport(1);
  }, [filters]); // eslint-disable-line react-hooks/exhaustive-deps
  const gantiPeriode = (p) => {
    setPeriod(p);
    setFilters((f) => ({ ...f, date_from: p.from || '', date_to: p.to || '' }));
  };
  const terapkanStatus = () => setFilters((f) => (f.status === statusDraft.trim() ? f : { ...f, status: statusDraft.trim() }));
  const hapusSaringan = () => {
    setPeriod({ preset: 'all', from: '', to: '' });
    setStatusDraft('');
    resetFilters();
  };

  const renderValue = (val, format, nullable) => {
    if (nullable && val == null) return '—';
    if (format === 'date') return fmtDate(val);
    if (format === 'currency') return fmt(val);
    if (format === 'number') return fmtNum(val);
    if (val === null || val === undefined || val === '' || val === '-') return '—';
    return val;
  };
  const nilaiUnduh = (row, c) => {
    const val = row[c.key];
    if (c.nullable && val == null) return 'belum ada data';
    if (c.format === 'date') return val ? fmtDate(val) : '';
    if (c.format === 'currency' || c.format === 'number') return Number(val || 0);
    if (KOLOM_STATUS.has(c.key)) return statusInfo(val)?.label || '';
    return val === '-' ? '' : (val ?? '');
  };

  // Unduh = SEMUA baris hasil saringan (laporan berhalaman diambil halaman demi halaman lewat API yang sama).
  const ambilSemua = async () => {
    if (!PAGINATED_TYPES.includes(activeReport)) return data;
    const semua = [];
    for (let p = 1; p <= 100; p += 1) {
      const params = new URLSearchParams();
      Object.entries(filters).forEach(([k, v]) => { if (v) params.append(k, v); });
      params.set('domain', domain);
      params.set('page', p);
      params.set('limit', PER_HALAMAN_UNDUH);
      // eslint-disable-next-line no-await-in-loop
      const res = await fetch(`/api/rahaza/reports/${activeReport}?${params.toString()}`, { headers: { Authorization: `Bearer ${token}` } });
      // eslint-disable-next-line no-await-in-loop
      const r = await res.json();
      const items = r?.items || (Array.isArray(r) ? r : []);
      semua.push(...items);
      if (!r?.pagination || !r.pagination.has_next || !items.length) break;
    }
    return semua;
  };

  // Ringkasan dari baris yang DIMUAT. Lebih dari satu halaman → label "halaman ini" (dulu terbaca sebagai total).
  const banyakHalaman = !!pagination && pagination.total_pages > 1;
  const akhiran = banyakHalaman ? ' (halaman ini)' : '';
  const getSummary = () => {
    if (!data.length) return null;
    switch (activeReport) {
      case 'production':
      case 'per-po': {
        const totalQty = data.reduce((s, r) => s + (r.qty_pesan || 0), 0);
        const totalProd = data.reduce((s, r) => s + (r.qty_produksi || 0), 0);
        const totalTerima = data.reduce((s, r) => s + (r.qty_diterima || 0), 0);
        const totalReject = data.reduce((s, r) => s + (r.qty_reject || 0), 0);
        const poSet = new Set(data.map((r) => r.no_po));
        return [
          { label: (activeReport === 'per-po' ? 'Jumlah PO' : 'Baris item') + akhiran, value: fmtNum(activeReport === 'per-po' ? poSet.size : data.length) },
          { label: `Qty dipesan${akhiran}`, value: `${fmtNum(totalQty)} pcs` },
          { label: `Qty diterima${akhiran}`, value: `${fmtNum(totalTerima)} pcs`, sub: `dari ${fmtNum(totalProd)} pcs diproduksi` },
          { label: `Qty ditolak${akhiran}`, value: `${fmtNum(totalReject)} pcs`,
            sub: totalProd ? `Diterima ${(totalTerima / totalProd * 100).toLocaleString('id-ID', { maximumFractionDigits: 1 })}% dari produksi` : 'Belum ada produksi' },
        ];
      }
      case 'financial': {
        const totalInv = data.reduce((s, r) => s + (r.total || 0), 0);
        const totalPaid = data.reduce((s, r) => s + (r.terbayar || 0), 0);
        const totalSisa = data.reduce((s, r) => s + (r.sisa || 0), 0);
        return [
          { label: `Jumlah faktur${akhiran}`, value: fmtNum(data.length) },
          { label: `Total tagihan${akhiran}`, value: fmt(totalInv) },
          { label: `Total terbayar${akhiran}`, value: fmt(totalPaid) },
          { label: `Sisa piutang${akhiran}`, value: fmt(totalSisa) },
        ];
      }
      case 'shipment': {
        const totalQty = data.reduce((s, r) => s + (r.qty || 0), 0);
        return [
          { label: `Jumlah pengiriman${akhiran}`, value: fmtNum(data.length) },
          { label: `Qty dikirim${akhiran}`, value: `${fmtNum(totalQty)} pcs` },
        ];
      }
      case 'rework': {
        const totalTerima = data.reduce((s, r) => s + (r.qty_diterima || 0), 0);
        const totalReject = data.reduce((s, r) => s + (r.qty_reject || 0), 0);
        const belum = data.filter((r) => r.tindak_lanjut === 'belum diputuskan').length;
        return [
          { label: `Baris ditolak${akhiran}`, value: fmtNum(data.length) },
          { label: `Qty diterima${akhiran}`, value: `${fmtNum(totalTerima)} pcs` },
          { label: `Qty ditolak${akhiran}`, value: `${fmtNum(totalReject)} pcs`,
            sub: totalTerima ? `${(totalReject / totalTerima * 100).toLocaleString('id-ID', { maximumFractionDigits: 1 })}% dari diterima` : undefined },
          { label: `Belum ditindak${akhiran}`, value: fmtNum(belum) },
        ];
      }
      default: return null;
    }
  };

  const summary = getSummary();
  const jenis = REPORT_TYPES.find((r) => r.id === activeReport);
  const kolom = getColumns().filter((c) => c.key !== '_no');
  const adaSaringan = !!(filters.date_from || filters.date_to || filters.status);

  return (
    <PageLayout
      testId="reports-module"
      title="Laporan Umum"
      subtitle="Data dari PO produksi, job, buku kuantitas, penerimaan CMT, pengiriman, dan faktur piutang."
      filters={(
        <>
          <SmartNativeSelect value={activeReport} onChange={(e) => setActiveReport(e.target.value)} searchable={false}
            className="h-9 w-56" aria-label="Jenis laporan" data-testid="report-type-select">
            {REPORT_TYPES.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
          </SmartNativeSelect>
          <FilterChips options={DOMAIN_TABS} value={domain} onChange={setDomain} hideWhenEmpty={false}
            ariaLabel="Pilih domain bisnis" testId="reports-domain" />
          <PeriodPicker value={period} onChange={gantiPeriode} presets={[ALL_TIME, ...PERIOD_PRESETS]} testId="reports-period" />
          <div className="relative w-full sm:w-44">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input value={statusDraft} onChange={(e) => setStatusDraft(e.target.value)} placeholder="Status (Enter)"
              onKeyDown={(e) => { if (e.key === 'Enter') terapkanStatus(); }} onBlur={terapkanStatus}
              className="h-9 pl-8" aria-label="Saring status" data-testid="reports-status-filter" />
          </div>
          {adaSaringan && (
            <Button variant="link" size="sm" onClick={hapusSaringan} data-testid="reports-reset-filter">Hapus saringan</Button>
          )}
        </>
      )}
      tools={(
        <>
          <TombolUnduh namaBerkas={`laporan-${activeReport}-${todayWIB()}`} namaLembar={jenis?.label || 'Laporan'} baris={data}
            ambilSemua={ambilSemua} testId="report-unduh"
            kolom={kolom.map((c) => ({ label: kalimat(c.label), nilai: (r) => nilaiUnduh(r, c) }))} />
          <Button variant="outline" onClick={() => setPickerOpen(true)} disabled={!data.length} data-testid="report-export-pdf-btn">
            <FileText />PDF
          </Button>
          <Button variant="outline" size="icon" onClick={() => fetchReport(page)} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
        </>
      )}
      summary={summary && data.length > 0 ? (
        <div className={`grid grid-cols-2 gap-3 ${summary.length > 2 ? 'md:grid-cols-4' : 'md:grid-cols-2 lg:w-1/2'}`} data-testid="report-summary">
          {summary.map((s) => <StatTile key={s.label} label={s.label} value={s.value} sub={s.sub} />)}
        </div>
      ) : null}
      footer={pagination && pagination.total_pages > 1 ? <PaginationBar pagination={pagination} onPageChange={setPage} /> : null}
    >
      <GlassCard className="p-0">
        <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-[var(--glass-border)] px-4 py-3">
          <div className="min-w-0">
            <p className="text-base font-semibold text-foreground">{jenis?.label}</p>
            <p className="text-sm text-muted-foreground">{jenis?.description}</p>
          </div>
          <p className="text-sm text-muted-foreground">
            {pagination
              ? `${pagination.total.toLocaleString('id-ID')} baris · halaman ${pagination.page} dari ${Math.max(1, pagination.total_pages)}`
              : `${fmtNum(data.length)} baris`}
          </p>
        </div>

        {loading ? (
          <p className="py-10 text-center text-sm text-muted-foreground">Memuat laporan…</p>
        ) : !data.length ? (
          <EmptyState icon={FileText} className="py-10" title="Tidak ada data untuk laporan ini"
            description="Coba ubah domain, periode, atau status." />
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10">No.</TableHead>
                  {kolom.map((c) => (
                    <TableHead key={c.key} className={`whitespace-nowrap ${c.format === 'number' || c.format === 'currency' ? 'text-right' : ''}`}>
                      {kalimat(c.label)}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((row, i) => (
                  <TableRow key={i}>
                    <TableCell className="text-muted-foreground tabular-nums">{((page - 1) * limit) + i + 1}</TableCell>
                    {kolom.map((c) => {
                      const st = KOLOM_STATUS.has(c.key) ? statusInfo(row[c.key]) : null;
                      const angka = c.format === 'number' || c.format === 'currency';
                      return (
                        <TableCell key={c.key} className={`whitespace-nowrap ${angka ? 'text-right tabular-nums' : ''}`}>
                          {KOLOM_STATUS.has(c.key)
                            ? (st ? <StatusBadge status={String(row[c.key])} label={st.label} tone={st.tone} /> : '—')
                            : renderValue(row[c.key], c.format, c.nullable)}
                        </TableCell>
                      );
                    })}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </GlassCard>

      {/* W2 — pemilih kolom PDF: kolom yang tercetak DIPILIH pemakai, termasuk Serial */}
      <PdfColumnPicker
        docType={`report-${activeReport}`}
        token={token}
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        onConfirm={(cols) => exportToPDF(cols)}
        title={`Kolom PDF — ${jenis?.label || 'Laporan'}`}
        hint="Centang kolom yang ingin tercetak (mis. Serial produksi). Pilihan diingat untuk cetakan berikutnya."
      />
    </PageLayout>
  );
}

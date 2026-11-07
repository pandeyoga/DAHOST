/**
 * Laporan Maklon — laporan & dashboard produksi maklon.
 *
 * Tab: Harian (penerimaan CMT + progres + kirim per hari) · Bulanan (per vendor CMT & per klien) · Per PO (buku
 * kuantitas + pengiriman + keuangan) · Realisasi vs target (per job & per PO) · Tren (N hari terakhir).
 *
 * 2026-08-06 — SUMBER DATA SSOT (`routes/dewi_phase7_reports.py`): production_pos / po_items / production_jobs /
 * production_job_items / production_progress / cmt_receipts / vendor_shipments / buyer_shipments. Setiap respons
 * mengirim `sources` → ditampilkan sebagai satu baris "Sumber data" berbahasa biasa.
 *
 * Standar UI/UX v2 (keputusan owner 8 Nov 2026 — "komposisi buruk, kartu tidak konsisten"): cetakan PageLayout,
 * tab standar rata kiri, SATU gaya kartu angka (StatTile; dulu kartu berwarna-warni dengan ikon), tabel standar +
 * unduh Excel/CSV, pemilih tanggal/bulan seragam (dulu <input type="date">, tahun ketik, dan periode "YYYY-MM" ketik),
 * grafik memakai warna token, tanpa judul ganda / kotak abu / kartu di dalam kartu. Angka yang belum bisa dihitung
 * (lulus QC tanpa barang diproses) tampil "—" + alasan, bukan 0%. Kartu "Defect Rate" yang berisi JUMLAH gagal QC
 * diberi label yang benar. Ekspor: CSV lengkap (server), Excel/CSV per tabel, PDF (jsPDF + html2canvas).
 */
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { Download, FileText, Loader2, Printer, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import DatePicker from '@/components/ui/date-picker';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { BarisDetail } from '@/components/ui/detail-popup';
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend, PieChart, Pie, Cell,
} from 'recharts';
import { toast } from 'sonner';
import jsPDF from 'jspdf';
import html2canvas from 'html2canvas';
import { formatRupiah } from '@/lib/format';
import { todayWIB, thisMonthWIB } from '@/lib/waktu';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from './moduleAtoms';
import { ChartCard, GlassTooltip, CHART_PALETTE } from './dashboardAtoms';
import { monthOptions } from './finance/PeriodPicker';

const API = process.env.REACT_APP_BACKEND_URL;
const BULAN = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'];
const BLN = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];

function fmtNum(v) { return Number(v || 0).toLocaleString('id-ID'); }
const fmtCurrency = formatRupiah;
function fmtPct(v) { return `${Number(v || 0).toLocaleString('id-ID', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`; }
function fmtDate(d) {
  if (!d) return '—';
  const s = String(d);
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) {
    const [y, m, dd] = s.slice(0, 10).split('-').map(Number);
    return `${String(dd).padStart(2, '0')} ${BLN[m - 1]} ${y}`;
  }
  return new Date(d).toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' });
}
const tglPendek = (v) => (v ? `${String(v).slice(8, 10)}/${String(v).slice(5, 7)}` : '');
const dibuatPada = () => new Date().toLocaleString('id-ID', { dateStyle: 'medium', timeStyle: 'short' });

// Status dari server → label + nada.
const STATUS = {
  paid: ['Lunas', 'success'], partial: ['Dibayar sebagian', 'warning'], partial_paid: ['Dibayar sebagian', 'warning'],
  unpaid: ['Belum dibayar', 'danger'], issued: ['Terbit', 'info'], draft: ['Draf', 'muted'], open: ['Terbuka', 'info'],
  in_progress: ['Sedang dikerjakan', 'info'], running: ['Berjalan', 'info'], confirmed: ['Dikonfirmasi', 'info'],
  completed: ['Selesai', 'success'], done: ['Selesai', 'success'], closed: ['Ditutup', 'muted'], cancelled: ['Dibatalkan', 'muted'],
  dispatched: ['Dikirim', 'info'], shipped: ['Dikirim', 'info'], delivered: ['Terkirim', 'success'], received: ['Diterima', 'success'],
  pending: ['Menunggu', 'warning'],
};
function Status({ value }) {
  if (!value) return <span className="text-muted-foreground">—</span>;
  const k = String(value).toLowerCase();
  const [label, tone] = STATUS[k] || [String(value).replace(/_/g, ' '), 'default'];
  return <StatusBadge status={k} label={label.charAt(0).toUpperCase() + label.slice(1)} tone={tone} />;
}

// Kode koleksi → nama yang dipahami staf (dulu tampil "production_pos 0", "rahaza_stock_ledger 0").
const NAMA_SUMBER = {
  production_pos: 'PO produksi', po_items: 'Item PO', production_jobs: 'Job produksi', production_job_items: 'Buku kuantitas job',
  production_progress: 'Progres produksi', cmt_receipts: 'Terima dari CMT', vendor_shipments: 'Surat jalan ke CMT',
  buyer_shipments: 'Kirim ke buyer', rahaza_stock_ledger: 'Penyesuaian stok', dewi_maklon_pos: 'PO maklon',
};
/** Jejak sumber — menjawab "angkanya dari mana?" tanpa istilah program. */
function SourceTrace({ data }) {
  const rows = data?.sources || [];
  if (!rows.length) return null;
  return (
    <p className="text-xs text-muted-foreground" data-testid="report-source-trace">
      Sumber data{data?.domain_label ? ` (${data.domain_label})` : ''}:{' '}
      {rows.map((s) => `${NAMA_SUMBER[s.collection] || 'Data lain'} ${fmtNum(s.count)}`).join(' · ')}.
    </p>
  );
}

// Grafik: sumbu & kisi memakai token tema.
const SUMBU = { stroke: 'var(--chart-grid)', tick: { fontSize: 12, fill: 'hsl(var(--muted-foreground))' } };

/** Warna latar tema saat ini (rgb) untuk kanvas PDF — dulu kode warna gelap tetap. */
function latarTema() {
  try {
    const el = document.createElement('div');
    el.style.background = 'hsl(var(--background))';
    document.body.appendChild(el);
    const c = getComputedStyle(el).backgroundColor;
    el.remove();
    return c && c !== 'rgba(0, 0, 0, 0)' ? c : 'rgb(255, 255, 255)';
  } catch { return 'rgb(255, 255, 255)'; }
}

async function exportToPDF(elementRef, filename) {
  if (!elementRef.current) {
    toast.error('Bagian laporan tidak ditemukan');
    return;
  }
  try {
    toast.info('Membuat PDF…');
    const bg = latarTema();
    const canvas = await html2canvas(elementRef.current, { backgroundColor: bg, scale: 1.5, logging: false, useCORS: true });
    const imgData = canvas.toDataURL('image/png');
    const pdf = new jsPDF('p', 'mm', 'a4');
    const pdfWidth = pdf.internal.pageSize.getWidth();
    const pdfHeight = pdf.internal.pageSize.getHeight();
    const imgWidthMM = pdfWidth;
    const imgHeightMM = (canvas.height * pdfWidth) / canvas.width;
    if (imgHeightMM <= pdfHeight) {
      pdf.addImage(imgData, 'PNG', 0, 0, imgWidthMM, imgHeightMM);
    } else {
      // Banyak halaman: potong kanvas per tinggi halaman
      const pageHeightPx = Math.floor((pdfHeight * canvas.width) / pdfWidth);
      let yOffset = 0;
      let pageNum = 0;
      while (yOffset < canvas.height) {
        const sliceHeight = Math.min(pageHeightPx, canvas.height - yOffset);
        const sliceCanvas = document.createElement('canvas');
        sliceCanvas.width = canvas.width;
        sliceCanvas.height = sliceHeight;
        const ctx = sliceCanvas.getContext('2d');
        ctx.fillStyle = bg;
        ctx.fillRect(0, 0, sliceCanvas.width, sliceCanvas.height);
        ctx.drawImage(canvas, 0, yOffset, canvas.width, sliceHeight, 0, 0, canvas.width, sliceHeight);
        const sliceImg = sliceCanvas.toDataURL('image/png');
        const sliceHeightMM = (sliceHeight * pdfWidth) / canvas.width;
        if (pageNum > 0) pdf.addPage();
        pdf.addImage(sliceImg, 'PNG', 0, 0, imgWidthMM, sliceHeightMM);
        pdf.setFontSize(8);
        pdf.setTextColor(150);
        pdf.text(`Halaman ${pageNum + 1}`, pdfWidth - 25, pdfHeight - 5);
        yOffset += sliceHeight;
        pageNum += 1;
      }
    }
    pdf.save(`${filename}.pdf`);
    toast.success(`PDF diunduh: ${filename}.pdf`);
  } catch (e) {
    toast.error('Gagal membuat PDF');
  }
}

/** Unduh CSV lengkap dari server (dengan header otorisasi). */
function unduhCsvServer(url, nama, headers) {
  fetch(url, { headers })
    .then((r) => { if (!r.ok) throw new Error(); return r.blob(); })
    .then((blob) => {
      const href = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = href;
      a.download = nama;
      a.click();
      window.URL.revokeObjectURL(href);
      toast.success('CSV lengkap diunduh');
    })
    .catch(() => toast.error('Gagal mengunduh CSV'));
}

/** Baris alat di atas isi tab: pilihan di kiri, unduhan + muat ulang di kanan. */
function BarisAlat({ kiri, kanan, loading, onMuat }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex flex-1 flex-wrap items-center gap-2">{kiri}</div>
      <div className="flex flex-wrap items-center gap-2">
        {kanan}
        {onMuat && (
          <Button variant="outline" size="icon" onClick={onMuat} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
        )}
      </div>
    </div>
  );
}

const Memuat = ({ teks = 'Memuat laporan…' }) => (
  <p className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
    <Loader2 className="h-4 w-4 animate-spin" />{teks}
  </p>
);

/** Tabel sederhana: kolom [{label, nilai(row), angka?}] */
function TabelSederhana({ kolom, baris, kunci, kosong = 'Belum ada data.' }) {
  if (!baris?.length) return <p className="py-6 text-center text-sm text-muted-foreground">{kosong}</p>;
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            {kolom.map((k) => <TableHead key={k.label} className={k.angka ? 'text-right' : ''}>{k.label}</TableHead>)}
          </TableRow>
        </TableHeader>
        <TableBody>
          {baris.map((r, i) => (
            <TableRow key={kunci ? kunci(r) : i}>
              {kolom.map((k) => (
                <TableCell key={k.label} className={k.angka ? 'whitespace-nowrap text-right tabular-nums' : ''}>{k.tampil ? k.tampil(r) : k.nilai(r)}</TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

// ─── 1. LAPORAN HARIAN ─────────────────────────────────────────────────────────
function DailyReportTab({ headers }) {
  const [reportDate, setReportDate] = useState(todayWIB());
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);
  const printRef = useRef(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/dewi/reports/daily?date=${reportDate}`, { headers });
      if (r.ok) setData(await r.json());
      else toast.error('Gagal memuat laporan harian');
    } catch (e) {
      toast.error('Koneksi gagal. Coba muat ulang.');
    } finally {
      setLoading(false);
    }
  }, [reportDate, headers]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // 2026-11-08: dulu juga membuka tab baru dengan token di alamat (unduhan ganda) → kini hanya unduhan berotorisasi.
  const handleCSVExport = () => unduhCsvServer(`${API}/api/dewi/reports/export/daily.csv?date=${reportDate}`,
    `laporan-harian-${reportDate}.csv`, headers);

  const prod = data?.production;
  const kolomVendor = [
    { label: 'Vendor CMT', nilai: (v) => v.cmt_name || '—' },
    { label: 'Diproses', nilai: (v) => Number(v.qty_processed || 0), tampil: (v) => fmtNum(v.qty_processed), angka: true },
  ];

  return (
    <div className="space-y-4">
      <BarisAlat loading={loading} onMuat={fetchData}
        kiri={(
          <div className="w-44">
            <DatePicker value={reportDate} onChange={(v) => v && setReportDate(v)} bolehKosong={false} testId="daily-report-date" />
          </div>
        )}
        kanan={(
          <>
            <TombolUnduh namaBerkas={`laporan-harian-${reportDate}`} namaLembar="Produksi per vendor" baris={prod?.by_vendor || []}
              kolom={kolomVendor} testId="daily-unduh" />
            <Button variant="outline" onClick={handleCSVExport} data-testid="daily-csv-lengkap" title="CSV lengkap dari server"><Download /><span className="hidden sm:inline">CSV lengkap</span></Button>
            <Button variant="outline" onClick={() => exportToPDF(printRef, `laporan-harian-${reportDate}`)} disabled={!data}>
              <Printer /><span className="hidden sm:inline">PDF</span>
            </Button>
          </>
        )} />

      {loading || !data ? <Memuat /> : (
        <div ref={printRef} className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Laporan harian {fmtDate(data.date)} · CV. Dewi Aditya · dibuat {dibuatPada()}
          </p>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-konten-utama="">
            <StatTile testId="stat-Total Diproses" label="Barang diproses" value={fmtNum(prod.total_processed)} sub="pcs, hari ini" />
            <StatTile testId="stat-Lolos QC" label="Lolos QC" value={fmtNum(prod.total_passed)}
              sub={prod.total_processed ? `${fmtPct(prod.pass_rate_pct)} dari diproses` : 'Belum ada barang diproses'} />
            <StatTile testId="stat-Gagal QC" label="Gagal QC" value={fmtNum(prod.total_failed)} sub="pcs"
              accent={prod.total_failed > 0 ? 'danger' : 'default'} />
            <StatTile testId="stat-Adjustment Stok" label="Penyesuaian stok" value={fmtNum(data.stock_adjustments)} sub="catatan hari ini" />
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <ChartCard title="Produksi per vendor CMT">
              {prod.by_vendor.length === 0 ? (
                <EmptyState className="py-8" title="Belum ada produksi tercatat" />
              ) : (
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={prod.by_vendor}>
                    <CartesianGrid strokeDasharray="3 4" stroke="var(--chart-grid)" vertical={false} />
                    <XAxis dataKey="cmt_name" {...SUMBU} />
                    <YAxis {...SUMBU} width={40} />
                    <Tooltip content={<GlassTooltip formatter={(v) => `${fmtNum(v)} pcs`} />} cursor={{ fill: 'var(--glass-bg-hover)' }} />
                    <Bar dataKey="qty_processed" fill={CHART_PALETTE[0]} name="Diproses" radius={[4, 4, 0, 0]} maxBarSize={40} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </ChartCard>
            <ChartCard title="Asal catatan produksi" subtitle="Penerimaan CMT vs catatan progres.">
              {prod.by_step.length === 0 ? (
                <EmptyState className="py-8" title="Belum ada data" />
              ) : (
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie data={prod.by_step} dataKey="qty" nameKey="step" cx="50%" cy="50%" outerRadius={75}>
                      {prod.by_step.map((entry, idx) => <Cell key={`cell-${idx}`} fill={CHART_PALETTE[idx % CHART_PALETTE.length]} />)}
                    </Pie>
                    <Tooltip content={<GlassTooltip formatter={(v) => `${fmtNum(v)} pcs`} />} />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                  </PieChart>
                </ResponsiveContainer>
              )}
            </ChartCard>
          </div>

          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatTile label="Surat jalan ke CMT" value={fmtNum(data.delivery_orders.issued)} sub={`${fmtNum(data.delivery_orders.received)} penerimaan dari CMT`} />
            <StatTile label="Kirim ke buyer" value={fmtNum(data.buyer_delivery?.qty_today)} sub={`pcs · ${fmtNum(data.buyer_delivery?.po_with_dispatch)} PO`} />
            <StatTile label="Pesanan online dikirim" value={fmtNum(data.fulfillment.dispatched_orders)} sub={`${fmtNum(data.fulfillment.dispatched_qty)} pcs`} />
          </div>
          <SourceTrace data={data} />
        </div>
      )}
    </div>
  );
}

// ─── 2. LAPORAN BULANAN ────────────────────────────────────────────────────────
function MonthlyReportTab({ headers }) {
  const [bulan, setBulan] = useState(() => thisMonthWIB());
  const opsi = useMemo(() => monthOptions(36), []);
  const [year, month] = bulan.split('-').map(Number);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);
  const printRef = useRef(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/dewi/reports/monthly?year=${year}&month=${month}`, { headers });
      if (r.ok) setData(await r.json());
    } catch (e) {
      toast.error('Koneksi gagal. Coba muat ulang.');
    } finally {
      setLoading(false);
    }
  }, [year, month, headers]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const nama = `laporan-bulanan-${year}-${String(month).padStart(2, '0')}`;
  const kolomVendor = [
    { label: 'Vendor CMT', nilai: (v) => v.cmt_name || '—' },
    { label: 'Diproses', nilai: (v) => Number(v.total_processed || 0), tampil: (v) => fmtNum(v.total_processed), angka: true },
    { label: 'Lolos QC', nilai: (v) => Number(v.total_passed || 0), tampil: (v) => fmtNum(v.total_passed), angka: true },
    { label: 'Gagal QC', nilai: (v) => Number(v.total_failed || 0), tampil: (v) => fmtNum(v.total_failed), angka: true },
    { label: 'Lolos (%)', nilai: (v) => Number(v.pass_rate_pct || 0), tampil: (v) => fmtPct(v.pass_rate_pct), angka: true },
    { label: 'Hari aktif', nilai: (v) => Number(v.active_days || 0), tampil: (v) => fmtNum(v.active_days), angka: true },
    { label: 'Job', nilai: (v) => Number(v.jobs_count || 0), tampil: (v) => fmtNum(v.jobs_count), angka: true },
  ];
  const kolomKlien = [
    { label: 'Klien', nilai: (c) => c.client_name || '—' },
    { label: 'Jumlah PO', nilai: (c) => Number(c.po_count || 0), tampil: (c) => fmtNum(c.po_count), angka: true },
    { label: 'Total qty', nilai: (c) => Number(c.total_qty || 0), tampil: (c) => fmtNum(c.total_qty), angka: true },
    { label: 'Nilai order', nilai: (c) => Number(c.total_value || 0), tampil: (c) => fmtCurrency(c.total_value), angka: true },
    { label: 'Dibayar', nilai: (c) => Number(c.amount_paid || 0), tampil: (c) => fmtCurrency(c.amount_paid), angka: true },
    { label: 'Sisa tagihan', nilai: (c) => Number(c.outstanding || 0), tampil: (c) => fmtCurrency(c.outstanding), angka: true },
  ];

  return (
    <div className="space-y-4">
      <BarisAlat loading={loading} onMuat={fetchData}
        kiri={(
          <SmartNativeSelect value={bulan} onChange={(e) => setBulan(e.target.value)} searchable={false}
            className="h-9 w-48" aria-label="Bulan laporan" data-testid="monthly-month-select">
            {opsi.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </SmartNativeSelect>
        )}
        kanan={(
          <>
            <Button variant="outline" onClick={() => unduhCsvServer(`${API}/api/dewi/reports/export/monthly.csv?year=${year}&month=${month}`, `${nama}.csv`, headers)}>
              <Download /><span className="hidden sm:inline">CSV lengkap</span>
            </Button>
            <Button variant="outline" onClick={() => exportToPDF(printRef, nama)} disabled={!data}><Printer /><span className="hidden sm:inline">PDF</span></Button>
          </>
        )} />

      {loading || !data ? <Memuat /> : (
        <div ref={printRef} className="space-y-4">
          <p className="text-sm text-muted-foreground">Laporan bulanan {BULAN[month - 1]} {year} · CV. Dewi Aditya · dibuat {dibuatPada()}</p>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-konten-utama="">
            <StatTile label="Total diproses" value={fmtNum(data.summary.total_processed)}
              sub={data.summary.total_processed ? `${fmtPct(data.summary.pass_rate_pct)} lolos QC` : 'Belum ada barang diproses'} />
            <StatTile label="Vendor CMT aktif" value={fmtNum(data.summary.vendor_count)} />
            <StatTile label="PO maklon" value={fmtNum(data.summary.maklon_po_count)} sub={fmtCurrency(data.summary.maklon_total_value)} />
            <StatTile label="Surat jalan ke CMT" value={fmtNum(data.summary.do_issued)} sub={`${fmtNum(data.summary.do_received)} penerimaan`} />
          </div>
          <ChartCard title="Produksi per vendor CMT"
            actions={<TombolUnduh namaBerkas={`${nama}-vendor`} namaLembar="Produksi per vendor" baris={data.production_by_vendor} kolom={kolomVendor} testId="monthly-vendor-unduh" />}>
            <TabelSederhana kolom={kolomVendor} baris={data.production_by_vendor} kunci={(v) => v.cmt_partner_id} />
          </ChartCard>
          <ChartCard title="Maklon per klien"
            actions={<TombolUnduh namaBerkas={`${nama}-klien`} namaLembar="Maklon per klien" baris={data.maklon_by_client} kolom={kolomKlien} testId="monthly-klien-unduh" />}>
            <TabelSederhana kolom={kolomKlien} baris={data.maklon_by_client} kunci={(c) => c.client_id} />
          </ChartCard>
          <SourceTrace data={data} />
        </div>
      )}
    </div>
  );
}

// ─── 3. LAPORAN PER PO ─────────────────────────────────────────────────────────
function PerPOReportTab({ headers }) {
  const [pos, setPos] = useState([]);
  const [selectedPO, setSelectedPO] = useState('');
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);
  const printRef = useRef(null);

  useEffect(() => {
    // 2026-11-08: batas 200 → 500 (batas maksimal API) supaya PO lama tidak hilang dari pilihan.
    fetch(`${API}/api/dewi/maklon/pos?limit=500`, { headers })
      .then((r) => r.json())
      .then((d) => setPos(Array.isArray(d) ? d : (d.items || [])))
      .catch(() => toast.error('Gagal memuat daftar PO'));
  }, [headers]);

  const fetchPO = useCallback(async () => {
    if (!selectedPO) return;
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/dewi/reports/po/${selectedPO}`, { headers });
      if (r.ok) setData(await r.json());
      else toast.error('Gagal memuat laporan PO');
    } catch (e) {
      toast.error('Koneksi gagal. Coba muat ulang.');
    } finally {
      setLoading(false);
    }
  }, [selectedPO, headers]);

  useEffect(() => { fetchPO(); }, [fetchPO]);

  const kolomItem = [
    { label: 'Artikel', nilai: (it) => it.artikel || '—' },
    { label: 'Qty', nilai: (it) => Number(it.qty || 0), tampil: (it) => fmtNum(it.qty), angka: true },
    { label: 'Dikirim', nilai: (it) => Number(it.qty_dispatched || 0), tampil: (it) => fmtNum(it.qty_dispatched), angka: true },
    { label: 'Status', nilai: (it) => (STATUS[String(it.status || '').toLowerCase()]?.[0] || it.status || ''), tampil: (it) => <Status value={it.status} /> },
  ];
  const kolomKirim = [
    { label: 'No. kirim', nilai: (d) => d.dispatch_number || '—' },
    { label: 'Tanggal', nilai: (d) => fmtDate(d.dispatch_date) },
    { label: 'Qty', nilai: (d) => Number(d.qty || 0), tampil: (d) => `${fmtNum(d.qty)} pcs`, angka: true },
    { label: 'Status', nilai: (d) => (STATUS[String(d.status || '').toLowerCase()]?.[0] || d.status || ''), tampil: (d) => <Status value={d.status} /> },
  ];

  return (
    <div className="space-y-4">
      <BarisAlat
        kiri={(
          <SmartNativeSelect value={selectedPO} onChange={(e) => setSelectedPO(e.target.value)} className="h-9 w-full sm:w-80"
            aria-label="Pilih PO maklon" data-testid="po-select">
            <option value="">Pilih PO maklon…</option>
            {pos.map((po) => (
              <option key={po.id} value={po.id}>{po.po_number} — {po.client_name} ({fmtNum(po.total_qty)} pcs)</option>
            ))}
          </SmartNativeSelect>
        )}
        kanan={data ? (
          <Button variant="outline" onClick={() => exportToPDF(printRef, `laporan-po-${data.po.po_number}`)}><Printer /><span className="hidden sm:inline">PDF</span></Button>
        ) : null}
        loading={loading} onMuat={selectedPO ? fetchPO : undefined} />

      {!selectedPO ? (
        <EmptyState icon={FileText} title="Pilih PO untuk melihat laporannya"
          description={pos.length ? `${fmtNum(pos.length)} PO maklon tersedia di pilihan di atas.` : 'Belum ada PO maklon.'} />
      ) : loading ? <Memuat teks="Memuat…" /> : data ? (
        <div ref={printRef} className="space-y-4">
          <p className="text-sm text-muted-foreground">
            <span className="font-medium text-foreground">PO {data.po.po_number}</span> · {data.po.client_name} · dibuat {dibuatPada()}
          </p>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-konten-utama="">
            <StatTile label="Target" value={fmtNum(data.progress.target_qty)} sub="pcs dipesan" />
            <StatTile label="Diproduksi" value={fmtNum(data.progress.qty_produced)} sub={`${fmtPct(data.progress.production_pct)} dari target`} />
            <StatTile label="Dikirim" value={fmtNum(data.progress.qty_dispatched)} sub={`${fmtPct(data.progress.dispatch_pct)} dari target`} />
            <StatTile label="Sisa" value={fmtNum(data.progress.qty_remaining)} sub="pcs belum dikirim"
              accent={data.progress.qty_remaining > 0 ? 'warning' : 'default'} />
          </div>
          <div className="space-y-1">
            <div className="flex justify-between text-sm text-muted-foreground">
              <span>Kemajuan pengiriman</span><span className="tabular-nums">{fmtPct(data.progress.dispatch_pct)}</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-[var(--glass-bg)]">
              <div className="h-full rounded-full bg-primary" style={{ width: `${Math.min(100, data.progress.dispatch_pct)}%` }} />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <ChartCard title={`Item PO (${fmtNum((data.po.items || []).length)})`}
              actions={<TombolUnduh namaBerkas={`po-${data.po.po_number}-item`} namaLembar="Item PO" baris={data.po.items || []} kolom={kolomItem} testId="po-item-unduh" />}>
              <TabelSederhana kolom={kolomItem} baris={data.po.items || []} kunci={(it) => it.item_id} />
            </ChartCard>
            <ChartCard title={`Riwayat pengiriman (${fmtNum(data.dispatches.length)})`}
              actions={<TombolUnduh namaBerkas={`po-${data.po.po_number}-kirim`} namaLembar="Pengiriman" baris={data.dispatches} kolom={kolomKirim} testId="po-kirim-unduh" />}>
              <TabelSederhana kolom={kolomKirim} baris={data.dispatches} kunci={(d) => d.id} kosong="Belum ada pengiriman." />
            </ChartCard>
          </div>

          <ChartCard title="Status keuangan">
            <dl className="grid grid-cols-1 gap-x-6 sm:grid-cols-2">
              <BarisDetail label="Faktur piutang">{data.finance.ar_invoice_number || '—'}</BarisDetail>
              <BarisDetail label="Status bayar"><Status value={data.finance.payment_status} /></BarisDetail>
              <BarisDetail label="Jurnal">
                <StatusBadge status={data.finance.gl_posted ? 'posted' : 'belum'} label={data.finance.gl_posted ? 'Sudah dijurnal' : 'Belum dijurnal'}
                  tone={data.finance.gl_posted ? 'success' : 'muted'} />
              </BarisDetail>
              <BarisDetail label="Nilai order"><span className="tabular-nums">{fmtCurrency(data.po.total_value)}</span></BarisDetail>
              <BarisDetail label="Dibayar"><span className="tabular-nums">{fmtCurrency(data.finance.amount_paid)}</span></BarisDetail>
              <BarisDetail label="Sisa tagihan"><span className="tabular-nums">{fmtCurrency(data.finance.outstanding)}</span></BarisDetail>
            </dl>
          </ChartCard>
          <SourceTrace data={data} />
        </div>
      ) : null}
    </div>
  );
}

// ─── 4. REALISASI VS TARGET ────────────────────────────────────────────────────
function Capaian({ pct }) {
  const v = Number(pct || 0);
  return <StatusBadge status="capaian" label={fmtPct(v)} tone={v >= 100 ? 'success' : v >= 75 ? 'warning' : 'danger'} />;
}

function ActualVsTargetTab({ headers }) {
  const [period, setPeriod] = useState(thisMonthWIB());
  const opsi = useMemo(() => monthOptions(24), []);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/dewi/reports/actual-vs-target?period=${period}`, { headers });
      if (r.ok) setData(await r.json());
    } catch (e) {
      toast.error('Koneksi gagal. Coba muat ulang.');
    } finally {
      setLoading(false);
    }
  }, [period, headers]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const kolomJob = [
    { label: 'Job', nilai: (j) => j.job_code || '—' },
    { label: 'Produk', nilai: (j) => j.product_name || '—' },
    { label: 'Vendor', nilai: (j) => j.cmt_name || '—' },
    { label: 'Target', nilai: (j) => Number(j.target || 0), tampil: (j) => fmtNum(j.target), angka: true },
    { label: 'Realisasi', nilai: (j) => Number(j.actual || 0), tampil: (j) => fmtNum(j.actual), angka: true },
    { label: 'Selisih', nilai: (j) => Number(j.variance || 0),
      tampil: (j) => <span className={j.variance < 0 ? 'text-[hsl(var(--danger-text))]' : ''}>{j.variance > 0 ? '+' : ''}{fmtNum(j.variance)}</span>, angka: true },
    { label: 'Capaian', nilai: (j) => Number(j.achievement_pct || 0), tampil: (j) => <Capaian pct={j.achievement_pct} />, angka: true },
  ];
  const kolomPo = [
    { label: 'PO', nilai: (p) => p.po_number || '—' },
    { label: 'Klien', nilai: (p) => p.client_name || '—' },
    { label: 'Target', nilai: (p) => Number(p.target_qty || 0), tampil: (p) => fmtNum(p.target_qty), angka: true },
    { label: 'Dikirim', nilai: (p) => Number(p.dispatched_qty || 0), tampil: (p) => fmtNum(p.dispatched_qty), angka: true },
    { label: 'Sisa', nilai: (p) => Number(p.remaining_qty || 0), tampil: (p) => fmtNum(p.remaining_qty), angka: true },
    { label: 'Capaian', nilai: (p) => Number(p.achievement_pct || 0), tampil: (p) => <Capaian pct={p.achievement_pct} />, angka: true },
    { label: 'Status', nilai: (p) => (STATUS[String(p.status || '').toLowerCase()]?.[0] || p.status || ''), tampil: (p) => <Status value={p.status} /> },
  ];

  return (
    <div className="space-y-4">
      <BarisAlat loading={loading} onMuat={fetchData}
        kiri={(
          <SmartNativeSelect value={period} onChange={(e) => setPeriod(e.target.value)} searchable={false}
            className="h-9 w-48" aria-label="Periode" data-testid="period-input">
            {opsi.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </SmartNativeSelect>
        )} />

      {loading || !data ? <Memuat teks="Memuat…" /> : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-konten-utama="">
            <StatTile label="Target job CMT" value={fmtNum(data.summary.cmt_total_target)} sub={`${fmtNum(data.summary.cmt_job_count)} job`} />
            <StatTile label="Realisasi job CMT" value={fmtNum(data.summary.cmt_total_actual)}
              sub={data.summary.cmt_total_target ? `${fmtPct(data.summary.cmt_total_actual / data.summary.cmt_total_target * 100)} dari target` : 'Belum ada target'} />
            <StatTile label="Target PO maklon" value={fmtNum(data.summary.maklon_total_target)} sub={`${fmtNum(data.summary.maklon_po_count)} PO`} />
            <StatTile label="Dikirim (PO maklon)" value={fmtNum(data.summary.maklon_total_dispatched)}
              sub={data.summary.maklon_total_target ? `${fmtPct(data.summary.maklon_total_dispatched / data.summary.maklon_total_target * 100)} dari target` : 'Belum ada target'} />
          </div>
          <ChartCard title={`Job CMT: target vs realisasi (${fmtNum(data.cmt_jobs.length)})`}
            actions={<TombolUnduh namaBerkas={`realisasi-vs-target-job-${period}`} namaLembar="Job CMT" baris={data.cmt_jobs} kolom={kolomJob} testId="avt-job-unduh" />}>
            <TabelSederhana kolom={kolomJob} baris={data.cmt_jobs} kunci={(j) => j.job_id} />
          </ChartCard>
          <ChartCard title={`PO maklon: target vs kirim (${fmtNum(data.maklon_pos.length)})`}
            actions={<TombolUnduh namaBerkas={`realisasi-vs-target-po-${period}`} namaLembar="PO maklon" baris={data.maklon_pos} kolom={kolomPo} testId="avt-po-unduh" />}>
            <TabelSederhana kolom={kolomPo} baris={data.maklon_pos} kunci={(p) => p.po_id} />
          </ChartCard>
          <SourceTrace data={data} />
        </div>
      )}
    </div>
  );
}

// ─── 5. TREN PRODUKSI ──────────────────────────────────────────────────────────
function ProductionTrendTab({ headers }) {
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/dewi/reports/production-trend?days=${days}`, { headers });
      if (r.ok) setData(await r.json());
    } catch (e) {
      toast.error('Koneksi gagal. Coba muat ulang.');
    } finally {
      setLoading(false);
    }
  }, [days, headers]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const trend = data?.trend || [];
  const adaIsi = trend.some((t) => t.total_processed || t.total_passed || t.total_failed || t.dispatched_qty);
  const kolom = [
    { label: 'Tanggal', nilai: (t) => fmtDate(t.date) },
    { label: 'Diproses', nilai: (t) => Number(t.total_processed || 0) },
    { label: 'Lolos QC', nilai: (t) => Number(t.total_passed || 0) },
    { label: 'Gagal QC', nilai: (t) => Number(t.total_failed || 0) },
    { label: 'Dikirim', nilai: (t) => Number(t.dispatched_qty || 0) },
  ];

  return (
    <div className="space-y-4">
      <BarisAlat loading={loading} onMuat={fetchData}
        kiri={(
          <SmartNativeSelect value={String(days)} onChange={(e) => setDays(parseInt(e.target.value, 10))} searchable={false}
            className="h-9 w-40" aria-label="Rentang hari" data-testid="trend-days-select">
            {[7, 14, 30, 60, 90].map((d) => <option key={d} value={String(d)}>{d} hari terakhir</option>)}
          </SmartNativeSelect>
        )}
        kanan={<TombolUnduh namaBerkas={`tren-produksi-${days}-hari`} namaLembar="Tren produksi" baris={trend} kolom={kolom} testId="trend-unduh" />} />

      {loading || !data ? <Memuat teks="Memuat tren…" /> : !adaIsi ? (
        <EmptyState title="Belum ada produksi atau pengiriman" description={`Tidak ada catatan dari ${fmtDate(data.start_date)} s.d. ${fmtDate(data.end_date)}.`} />
      ) : (
        <>
          <ChartCard title="Produksi harian" subtitle={`${fmtDate(data.start_date)} s.d. ${fmtDate(data.end_date)}`}>
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={trend}>
                <CartesianGrid strokeDasharray="3 4" stroke="var(--chart-grid)" vertical={false} />
                <XAxis dataKey="date" {...SUMBU} tickFormatter={tglPendek} />
                <YAxis {...SUMBU} width={40} />
                <Tooltip content={<GlassTooltip formatter={(v) => `${fmtNum(v)} pcs`} />} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line type="monotone" dataKey="total_processed" stroke={CHART_PALETTE[0]} name="Diproses" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="total_passed" stroke={CHART_PALETTE[1]} name="Lolos QC" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="total_failed" stroke="hsl(var(--destructive))" name="Gagal QC" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="dispatched_qty" stroke={CHART_PALETTE[2]} name="Dikirim" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </ChartCard>
          <ChartCard title="Volume produksi dan pengiriman" subtitle="14 hari terakhir dari rentang.">
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={trend.slice(-14)}>
                <CartesianGrid strokeDasharray="3 4" stroke="var(--chart-grid)" vertical={false} />
                <XAxis dataKey="date" {...SUMBU} tickFormatter={tglPendek} />
                <YAxis {...SUMBU} width={40} />
                <Tooltip content={<GlassTooltip formatter={(v) => `${fmtNum(v)} pcs`} />} cursor={{ fill: 'var(--glass-bg-hover)' }} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="total_processed" fill={CHART_PALETTE[0]} name="Diproses" radius={[4, 4, 0, 0]} />
                <Bar dataKey="dispatched_qty" fill={CHART_PALETTE[2]} name="Dikirim" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>
          <SourceTrace data={data} />
        </>
      )}
    </div>
  );
}

// ─── MODUL UTAMA ───────────────────────────────────────────────────────────────
export default function Phase7ReportingModule({ token }) {
  const headers = useMemo(() => ({
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
  }), [token]);

  const [tab, setTab] = useState('daily');

  return (
    <PageLayout testId="phase7-reporting-module" title="Laporan Maklon"
      subtitle="Produksi maklon dari PO produksi, job, penerimaan CMT, dan pengiriman.">
      <Tabs value={tab} onValueChange={setTab} className="space-y-4">
        <TabsList className="h-auto w-auto flex-wrap justify-start">
          <TabsTrigger data-testid="tab-daily" value="daily">Harian</TabsTrigger>
          <TabsTrigger data-testid="tab-monthly" value="monthly">Bulanan</TabsTrigger>
          <TabsTrigger data-testid="tab-per-po" value="per-po">Per PO</TabsTrigger>
          <TabsTrigger data-testid="tab-actual-vs-target" value="actual-target">Realisasi vs target</TabsTrigger>
          <TabsTrigger data-testid="tab-trend" value="trend">Tren</TabsTrigger>
        </TabsList>

        <TabsContent value="daily" className="mt-0"><DailyReportTab headers={headers} /></TabsContent>
        <TabsContent value="monthly" className="mt-0"><MonthlyReportTab headers={headers} /></TabsContent>
        <TabsContent value="per-po" className="mt-0"><PerPOReportTab headers={headers} /></TabsContent>
        <TabsContent value="actual-target" className="mt-0"><ActualVsTargetTab headers={headers} /></TabsContent>
        <TabsContent value="trend" className="mt-0"><ProductionTrendTab headers={headers} /></TabsContent>
      </Tabs>
    </PageLayout>
  );
}

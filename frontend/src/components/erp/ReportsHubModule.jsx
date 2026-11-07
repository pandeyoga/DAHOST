/**
 * Pusat Laporan (Reports Hub) — DIROMBAK 2026-08-06.
 *
 * KELUHAN OWNER: "pusat laporan saya malah tidak mengerti menu ini, yang ada malah direct ke portal lain."
 * SEKARANG: satu tempat untuk melihat data penting SETIAP PORTAL — kategori dipilih satu per satu, tiap kategori
 * menampilkan KPI ringkas + tabel data relevan dari SSOT, tautan modul sebagai TINDAK LANJUT, dan jejak sumber.
 * Kontraknya generik (backend: GET /api/rahaza/reports-hub/summary?category=…).
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout (kategori = pil penyaring, periode, muat ulang), kartu angka
 * StatTile (maks. 4 sebaris), tabel standar + unduh Excel/CSV (dulu CSV saja), judul kolom & nilai status dari server
 * ditampilkan dalam bahasa biasa (dulu HURUF BESAR / kode seperti "issued", "promoted"), tanggal "18 Nov 2026",
 * sumber data tanpa nama koleksi. Kartu angka diperiksa (lihat LAPORAN): "Total kuantitas stok" menjumlah semua
 * satuan (kg + yard + pcs …) → disembunyikan; keterangan "31 invoice" di piutang = semua faktur → diperjelas.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowRight, Loader2, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import FilterChips from '@/components/ui/filter-chips';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Skeleton } from '@/components/ui/skeleton';
import { ChartCard } from './dashboardAtoms';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatTile } from './moduleAtoms';
import { PeriodPicker, resolvePreset } from './PeriodPicker';
import { formatRupiah } from '@/lib/format';

const TONE_ACCENT = { success: 'success', warning: 'warning', danger: 'danger' };
const BULAN = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];

const fmtNum = (v) => Number(v || 0).toLocaleString('id-ID');
const fmtDate = (v) => {
  if (!v) return '—';
  const s = String(v);
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) {
    const [y, m, d] = s.slice(0, 10).split('-').map(Number);
    return `${String(d).padStart(2, '0')} ${BULAN[m - 1]} ${y}`;
  }
  const t = new Date(v);
  return Number.isNaN(t.getTime()) ? s : `${String(t.getDate()).padStart(2, '0')} ${BULAN[t.getMonth()]} ${t.getFullYear()}`;
};
const fmtShortIDR = (v) => {
  const n = Number(v || 0);
  if (n >= 1e9) return `Rp ${(n / 1e9).toLocaleString('id-ID', { maximumFractionDigits: 1 })} M`;
  if (n >= 1e6) return `Rp ${(n / 1e6).toLocaleString('id-ID', { maximumFractionDigits: 1 })} jt`;
  if (n >= 1e3) return `Rp ${(n / 1e3).toLocaleString('id-ID', { maximumFractionDigits: 0 })} rb`;
  return formatRupiah(n);
};

// Kode status/jenis dari server → label yang dipahami staf.
const KODE = {
  issued: 'Terbit', sent: 'Terkirim', paid: 'Lunas', partial_paid: 'Dibayar sebagian', partial: 'Sebagian',
  overdue: 'Lewat jatuh tempo', draft: 'Draf', cancelled: 'Dibatalkan', void: 'Dibatalkan',
  promoted: 'Naik produksi', approved_for_launch: 'Disetujui rilis', pending_owner_review: 'Menunggu tinjauan owner',
  internal_product: 'Produk internal', client_product: 'Produk klien', maklon: 'Maklon', internal: 'Internal',
  accessory: 'Aksesori', fabric: 'Kain', bahan_pembantu: 'Bahan pembantu', packaging: 'Kemasan',
  running: 'Berjalan', in_progress: 'Sedang dikerjakan', released: 'Dirilis', confirmed: 'Dikonfirmasi',
  completed: 'Selesai', closed: 'Ditutup', done: 'Selesai', pending: 'Menunggu', approved: 'Disetujui',
  rejected: 'Ditolak', received: 'Diterima', shipped: 'Dikirim', delivered: 'Terkirim', posted: 'Diposting',
  active: 'Aktif', inactive: 'Nonaktif', hadir: 'Hadir', izin: 'Izin', sakit: 'Sakit', alpa: 'Alpa', alfa: 'Alfa',
};
const kodeKeLabel = (v) => {
  const s = String(v);
  if (KODE[s]) return KODE[s];
  if (/^[a-z]+(_[a-z]+)+$/.test(s)) { const t = s.replace(/_/g, ' '); return t.charAt(0).toUpperCase() + t.slice(1); }
  return s;
};
// Judul kolom/KPI dari server (HURUF BESAR / campur Inggris) → kalimat biasa.
const ISTILAH = { 'no invoice': 'No. faktur', invoice: 'faktur', deadline: 'tenggat', reject: 'ditolak', order: 'pesanan', qty: 'qty', po: 'PO', mi: 'MI', sku: 'SKU', cmt: 'CMT', '%': '%' };
function kalimat(label) {
  let s = String(label || '').trim();
  if (!s) return s;
  s = s.toLowerCase();
  Object.entries(ISTILAH).forEach(([k, v]) => { s = s.replace(new RegExp(`\\b${k}\\b`, 'g'), v); });
  s = s.replace(/\bno (\w)/g, 'No. $1').replace(/\bpo\b/gi, 'PO').replace(/\bmi\b/gi, 'MI');
  return s.charAt(0).toUpperCase() + s.slice(1);
}
// Keterangan KPI dari server: kode status → label; "31 invoice" (= semua faktur) diperjelas.
function subKpi(k) {
  let s = String(k.sub ?? '');
  s = s.replace(/\b([a-z]+(?:_[a-z]+)+|promoted|issued|paid)\b/g, (m) => kodeKeLabel(m).toLowerCase());
  s = s.replace(/\b(\d+) invoice\b/, 'dari $1 faktur');
  return s;
}
// KPI yang menjumlah satuan berbeda (kg + yard + pcs …) tidak bermakna → disembunyikan (keputusan 9).
const KPI_TERSEMBUNYI = (k) => /total kuantitas stok/i.test(k.label);

const NAMA_SUMBER = {
  production_pos: 'PO produksi', production_jobs: 'Job produksi', production_job_items: 'Buku kuantitas job',
  cmt_receipts: 'Terima dari pelaksana', rahaza_ar_invoices: 'Faktur piutang', dewi_maklon_invoices: 'Tagihan maklon',
  rahaza_materials: 'Master material', rahaza_material_stock: 'Stok material', wh_positions: 'Posisi rak',
  rahaza_material_issues: 'Pengeluaran material', rahaza_employees: 'Karyawan', rahaza_attendance_events: 'Absensi',
  dewi_rnd_styles: 'Style RnD', dewi_rnd_sample_requests: 'Permintaan sample', marketing_orders: 'Order online',
};

const isAngka = (c) => ['number', 'currency'].includes(c.format);
const renderCell = (val, format) => {
  if (val === null || val === undefined || val === '' || val === '-') return '—';
  if (format === 'date') return fmtDate(val);
  if (format === 'currency') return formatRupiah(val);
  if (format === 'number') return fmtNum(val);
  return kodeKeLabel(val);
};
const nilaiUnduh = (val, format) => {
  if (val === null || val === undefined || val === '' || val === '-') return '';
  if (format === 'date') return fmtDate(val);
  if (isAngka({ format })) return Number(val);
  return kodeKeLabel(val);
};
const kpiValue = (k) => {
  if (k.format === 'currency') return fmtShortIDR(k.value);
  if (k.format === 'percent') return `${String(Number(k.value || 0)).replace('.', ',')}%`;
  if (k.format === 'number') return fmtNum(k.value);
  return String(k.value ?? '—');
};

export default function ReportsHubModule({ token, onNavigate }) {
  const [categories, setCategories] = useState([]);
  const [active, setActive] = useState('eksekutif');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [period, setPeriod] = useState({ preset: '30d', from: null, to: null });

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  const range = useMemo(() => {
    let { from, to } = period || {};
    // Preset dihitung SSOT PeriodPicker (WIB) — dulu disalin di sini dengan jam perangkat & tanpa 'Bulan Lalu'.
    if (!from || !to) ({ from, to } = resolvePreset(period?.preset || '30d'));
    return { from, to };
  }, [period]);

  useEffect(() => {
    let alive = true;
    fetch('/api/rahaza/reports-hub/categories', { headers })
      .then((r) => r.json())
      .then((d) => { if (alive) setCategories(d.items || []); })
      .catch(() => toast.error('Gagal memuat daftar kategori laporan'));
    return () => { alive = false; };
  }, [headers]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = `?category=${active}` +
        (range.from && range.to ? `&date_from=${range.from}&date_to=${range.to}` : '');
      const r = await fetch(`/api/rahaza/reports-hub/summary${qs}`, { headers });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `Permintaan gagal (kode ${r.status}).`);
      setData(d);
    } catch (e) {
      toast.error('Gagal memuat laporan', { description: e.message });
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [active, headers, range.from, range.to]);

  useEffect(() => { load(); }, [load]);

  const kpis = (data?.kpis || []).filter((k) => !KPI_TERSEMBUNYI(k));

  return (
    <PageLayout
      testId="reports-hub"
      headerTestId="reports-hub-header"
      title="Pusat Laporan"
      subtitle="Data penting setiap portal dalam satu tempat: pilih kategori, lihat angkanya, lalu tindak lanjuti."
      filters={(
        <>
          <FilterChips options={categories.map((c) => ({ key: c.id, label: String(c.label || '').replace(/\s*\/\s*HRIS/i, '') }))} value={active} onChange={setActive}
            hideWhenEmpty={false} ariaLabel="Kategori laporan" testId="reports-hub-cat" />
          <PeriodPicker value={period} onChange={setPeriod} compareEnabled={false} testId="reports-hub-period" />
        </>
      )}
      tools={(
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="reports-hub-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      )}
      summary={data ? (
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">
            <span className="font-medium text-foreground" data-testid="reports-hub-active-label">{data.label}</span>
            {' · '}{fmtDate(data.date_from)} – {fmtDate(data.date_to)}{data.description ? ` · ${data.description}` : ''}
          </p>
          {kpis.length > 0 && (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="reports-hub-kpis" data-konten-utama="">
              {kpis.slice(0, 4).map((k) => (
                <StatTile key={k.label} testId={`hub-kpi-${k.label}`} label={kalimat(k.label)} value={kpiValue(k)}
                  sub={subKpi(k) || undefined} accent={Number(k.value) ? (TONE_ACCENT[k.tone] || 'default') : 'default'} />
              ))}
            </div>
          )}
          {kpis.length > 4 && (
            <p className="text-sm text-muted-foreground" data-testid="reports-hub-kpi-lain">
              {kpis.slice(4).map((k) => `${kalimat(k.label)}: ${kpiValue(k)}${subKpi(k) ? ` (${subKpi(k)})` : ''}`).join(' · ')}
            </p>
          )}
        </div>
      ) : null}
    >
      {loading && !data ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-20 rounded-lg" />)}
          </div>
          <Skeleton className="h-64 rounded-lg" />
        </div>
      ) : !data ? (
        <EmptyState title="Laporan tidak dapat dimuat" description="Coba muat ulang." />
      ) : (
        <>
          {data.tables.map((t) => (
            <ChartCard key={t.id} testId={`hub-table-${t.id}`} title={t.title}
              subtitle={`${t.subtitle ? `${t.subtitle} · ` : ''}${fmtNum(t.rows.length)} baris`}
              actions={(
                <>
                  <TombolUnduh namaBerkas={`${active}-${t.id}-${range.from}_${range.to}`} namaLembar={t.title}
                    baris={t.rows} testId={`hub-csv-${t.id}`}
                    kolom={t.columns.map((c) => ({ label: kalimat(c.label), nilai: (r) => nilaiUnduh(r[c.key], c.format) }))} />
                  {t.module_id && onNavigate && (
                    <Button variant="link" size="sm" onClick={() => onNavigate(t.module_id)} data-testid={`hub-open-${t.id}`}>
                      {t.module_label || 'Buka modul'} <ArrowRight />
                    </Button>
                  )}
                </>
              )}>
              {t.rows.length === 0 ? (
                <p className="py-6 text-center text-sm text-muted-foreground" data-testid={`hub-empty-${t.id}`}>
                  {t.empty_hint || 'Belum ada data untuk periode ini.'}
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        {t.columns.map((c) => (
                          <TableHead key={c.key} className={isAngka(c) ? 'text-right' : ''}>{kalimat(c.label)}</TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {t.rows.map((row, idx) => (
                        <TableRow key={idx}>
                          {t.columns.map((c) => (
                            <TableCell key={c.key} className={isAngka(c) ? 'whitespace-nowrap text-right tabular-nums' : ''}>
                              {renderCell(row[c.key], c.format)}
                            </TableCell>
                          ))}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </ChartCard>
          ))}

          {data.sources?.length > 0 && (
            <p className="text-xs text-muted-foreground" data-testid="reports-hub-source-trace">
              Sumber data: {data.sources.map((s) => `${NAMA_SUMBER[s.collection] || 'Data lain'} ${fmtNum(s.count)}`).join(' · ')} dokumen.
            </p>
          )}

          {loading && (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Memuat ulang…
            </p>
          )}
        </>
      )}
    </PageLayout>
  );
}

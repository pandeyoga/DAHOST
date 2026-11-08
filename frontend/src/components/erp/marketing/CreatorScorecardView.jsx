/**
 * CreatorScorecardView — **SCORECARD KREATOR** (F7.4 · F8): target vs pencapaian.
 *
 * Kenapa layar ini ada: target kreator (`marketing_creator_targets`) sudah bisa
 * ditetapkan, dan angka pencapaiannya ada di tiga tempat berbeda — tetapi tidak ada
 * satu layar pun yang mempertemukannya. Akibatnya rapat kreator memakai angka yang
 * dipilih manual oleh siapa pun yang membuat slide.
 *
 * Yang WAJIB terlihat di layar (bukan hanya di API):
 *   · tiga sumber uang DIPISAH: omzet pesanan · omzet sesi live · GMV KPI konten;
 *   · BASIS penilaian tertulis pada setiap baris (kolom “Basis”);
 *   · kreator tanpa target ditandai “belum ada target”, bukan 0%.
 *
 * DILENGKAPI 2026-08-14 (F8) — **angka yang bisa DITELUSURI**. Scorecard menjawab
 * “berapa”, tetapi angka yang dibantah di rapat selalu menuntut “dari mana”. Klik
 * satu baris ⇒ dialog rincian: konten mana yang membawa GMV itu, pesanan mana yang
 * dihitung (termasuk yang TIDAK dihitung beserta sebabnya), sesi mana yang dicatat
 * staf. Total rincian dijamin sama dengan baris scorecard (gate `INV-MKTOPS`).
 * Ditambah paginasi 10/hal (standar RC-UI-03) dan unduh CSV untuk bahan rapat.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout (judul disembunyikan di hub); bulan = satu pilihan (dulu pilihan bulan +
 * ketik tahun); 4 StatTile berketerangan (dulu 5 kartu); tabel 8 kolom + unduh Excel/CSV (kolom lain di berkas
 * unduhan & popup rincian); tampilan Kartu diganti tabel; rincian = DetailPopup dengan pil penyaring + TabelData.
 */
import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Info, Target, AlertTriangle, Search, ShoppingCart, Video, Radio } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Progress } from '@/components/ui/progress';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup from '@/components/ui/detail-popup';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatRupiah, formatDateID } from '@/lib/format';
import { monthOptions } from '../finance/PeriodPicker';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';
import { MarketingAccountSelect } from './pickers/MarketingPickers';
import { rapikanCatatan } from './ContentPerformanceView';

const API = process.env.REACT_APP_BACKEND_URL;
const fmtRp = formatRupiah;
const fmtNum = (n) => new Intl.NumberFormat('id-ID').format(Math.round(n || 0));
const pct = (n) => `${String(n ?? 0).replace('.', ',')}%`;
const MONTHS = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus',
  'September', 'Oktober', 'November', 'Desember'];
const BASIS_LABEL = {
  orders: 'Pesanan (sumber uang resmi)', sessions: 'Sesi live (input staf)',
  gmv_kpi: 'GMV KPI konten (platform)', none: 'Belum ada angka',
};
const STATUS = {
  on_track: ['Sesuai target', 'success'], warning: ['Perlu dikejar', 'warning'],
  behind: ['Di bawah target', 'danger'], no_target: ['Belum ada target', 'muted'],
};
const StatusSkor = ({ s }) => <StatusBadge status={s} label={(STATUS[s] || [s])[0]} tone={(STATUS[s] || [])[1]} />;
const tgl = (v) => (v ? formatDateID(String(v).slice(0, 10)) : '—');
const STATUS_KONTEN = { draft: 'Draf', scheduled: 'Terjadwal', posted: 'Tayang', cancelled: 'Batal' };

export default function CreatorScorecardView({ token, onNavigate }) {
  const bulanPilihan = monthOptions(24);
  const [bulan, setBulan] = useState(() => bulanPilihan[0]?.value);
  const year = Number(String(bulan).slice(0, 4));
  const month = Number(String(bulan).slice(5, 7));
  const [accountId, setAccountId] = useState('');
  const [query, setQuery] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  // F8 — rincian satu kreator (dari mana angkanya)
  const [detailOf, setDetailOf] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailTab, setDetailTab] = useState('konten');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams({ year: String(year), month: String(month) });
      if (accountId) qs.set('account_id', accountId);
      const res = await fetch(`${API}/api/marketing/targets/creator/scorecard?${qs}`,
        { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
    } catch (e) {
      toast.error(`Gagal memuat scorecard kreator: ${e.message}`);
      setData(null);
    } finally { setLoading(false); }
  }, [year, month, accountId, token]);

  useEffect(() => { load(); }, [load]);

  const openDetail = async (row) => {
    setDetailOf(row);
    setDetail(null);
    setDetailTab('konten');
    setDetailLoading(true);
    try {
      const qs = new URLSearchParams({ year: String(year), month: String(month) });
      if (accountId) qs.set('account_id', accountId);
      const res = await fetch(
        `${API}/api/marketing/targets/creator/${row.creator_id}/detail?${qs}`,
        { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setDetail(await res.json());
    } catch (e) {
      toast.error(`Gagal memuat rincian kreator: ${e.message}`);
      setDetail({ error: e.message });
    } finally { setDetailLoading(false); }
  };

  const rowsAll = data?.rows || [];
  const t = data?.totals || {};
  const noTarget = data?.creators_without_target || [];
  const rows = rowsAll.filter((r) => {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return `${r.creator_name} ${r.creator_code}`.toLowerCase().includes(q);
  });
  const pg = useClientPagination(rows, 10);

  const gotoTarget = () => {
    if (typeof onNavigate === 'function') onNavigate('marketing-targets');
    else window.location.hash = 'marketing-targets';
  };

  /* Unduhan — bahan rapat. KETIGA angka uang sebagai kolom terpisah (tanpa kolom "total") supaya berkas ini
     tidak bisa dipakai menjumlahkan satu penjualan beberapa kali di spreadsheet. */
  const kolomUnduh = [
    { label: 'Kreator', nilai: (r) => r.creator_name },
    { label: 'Kode', nilai: (r) => r.creator_code || '' },
    { label: 'Target omzet', nilai: (r) => r.target.revenue ?? '' },
    { label: 'Basis penilaian', nilai: (r) => BASIS_LABEL[r.achievement.primary_basis] || '' },
    { label: 'Pencapaian %', nilai: (r) => r.achievement.primary_pct ?? '' },
    { label: 'Omzet pesanan (bruto)', nilai: (r) => r.actual.order_revenue },
    { label: 'Nilai retur', nilai: (r) => r.actual.order_revenue_returned },
    { label: 'Pesanan retur', nilai: (r) => r.actual.orders_returned },
    { label: 'Omzet pesanan setelah retur', nilai: (r) => r.actual.order_revenue_net_returns },
    { label: 'Omzet sesi live', nilai: (r) => r.actual.session_revenue },
    { label: 'GMV KPI konten', nilai: (r) => r.actual.gmv_kpi },
    { label: 'Konten', nilai: (r) => r.actual.contents },
    { label: 'Terbit', nilai: (r) => r.actual.posted },
    { label: 'Cakupan KPI %', nilai: (r) => r.actual.kpi_coverage_pct },
    { label: 'Tayangan', nilai: (r) => r.actual.views },
    { label: 'Interaksi', nilai: (r) => r.actual.engagement },
    { label: 'Sesi', nilai: (r) => r.actual.sessions },
    { label: 'Penonton', nilai: (r) => r.actual.viewers },
    { label: 'Status', nilai: (r) => (STATUS[r.achievement.status] || [r.achievement.status])[0] },
  ];

  const kolom = [
    { kunci: 'kreator', label: 'Kreator', hp: 'judul', isi: (r) => (
      <span className="font-medium">{r.creator_name}{r.creator_code ? <span className="block text-xs font-normal text-muted-foreground">{r.creator_code}</span> : null}</span>) },
    { kunci: 'target', label: 'Target omzet', rata: 'kanan', isi: (r) => (
      <span className="tabular-nums md:whitespace-nowrap">{r.target.revenue == null ? <span className="text-muted-foreground">—</span> : fmtRp(r.target.revenue)}</span>) },
    { kunci: 'capai', label: 'Pencapaian', isi: (r) => {
      const ach = r.achievement;
      return (
        <div className="min-w-[8rem] space-y-1">
          {ach.primary_pct == null ? <span className="text-muted-foreground">—</span> : <>
            <span className="text-sm font-medium tabular-nums">{pct(ach.primary_pct)}</span>
            <Progress value={Math.min(100, ach.primary_pct)} className="h-1.5" />
          </>}
          <p className="text-xs text-muted-foreground">{BASIS_LABEL[ach.primary_basis]}</p>
        </div>);
    } },
    { kunci: 'pesanan', label: 'Omzet pesanan', rata: 'kanan', isi: (r) => (
      <span className="tabular-nums md:whitespace-nowrap" data-testid={`scorecard-net-${r.creator_id}`}>{fmtRp(r.actual.order_revenue)}
        <span className="block text-xs text-muted-foreground">{(r.actual.orders_returned || 0) > 0
          ? `setelah retur ${fmtRp(r.actual.order_revenue_net_returns)}` : 'tanpa retur'}</span></span>) },
    { kunci: 'sesi', label: 'Omzet sesi live', rata: 'kanan', isi: (r) => <span className="tabular-nums md:whitespace-nowrap">{fmtRp(r.actual.session_revenue)}</span> },
    { kunci: 'gmv', label: 'GMV KPI konten', rata: 'kanan', isi: (r) => (
      <span className="tabular-nums md:whitespace-nowrap">{fmtRp(r.actual.gmv_kpi)}
        <span className="block text-xs text-muted-foreground">{fmtNum(r.actual.contents)} konten · KPI {pct(Number(r.actual.kpi_coverage_pct || 0).toFixed(0))}</span></span>) },
    { kunci: 'status', label: 'Status', isi: (r) => <StatusSkor s={r.achievement.status} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <Button size="sm" variant="outline" onClick={() => openDetail(r)} data-testid={`scorecard-detail-btn-${r.creator_id}`}>Lihat asalnya</Button>) },
  ];

  const kolomKonten = [
    { kunci: 'tgl', label: 'Tanggal', hp: 'keterangan', isi: (c) => <span className="tabular-nums md:whitespace-nowrap">{tgl(c.date)}</span> },
    { kunci: 'judul', label: 'Judul', hp: 'judul', isi: (c) => (c.published_url
      ? <a href={c.published_url} target="_blank" rel="noreferrer" className="text-primary hover:underline">{c.title}</a> : c.title) },
    { kunci: 'status', label: 'Status', isi: (c) => STATUS_KONTEN[c.status] || '—' },
    { kunci: 'kpi', label: 'KPI', isi: (c) => (c.has_kpi ? <StatusBadge status="ada" label="Ada" tone="success" /> : <StatusBadge status="belum" label="Belum" tone="muted" />) },
    { kunci: 'views', label: 'Tayangan', rata: 'kanan', isi: (c) => <span className="tabular-nums">{fmtNum(c.views)}</span> },
    { kunci: 'gmv', label: 'GMV KPI', rata: 'kanan', isi: (c) => <span className="tabular-nums md:whitespace-nowrap">{fmtRp(c.gmv_kpi)}</span> },
    { kunci: 'order', label: 'Pesanan (KPI)', rata: 'kanan', isi: (c) => <span className="tabular-nums">{fmtNum(c.orders)}</span> },
  ];
  const kolomPesanan = [
    { kunci: 'no', label: 'Nomor pesanan', hp: 'judul', isi: (o) => <span className="tabular-nums">{o.order_id}</span> },
    { kunci: 'tgl', label: 'Tanggal', hp: 'keterangan', isi: (o) => <span className="tabular-nums md:whitespace-nowrap">{tgl(o.order_date)}</span> },
    { kunci: 'toko', label: 'Toko', isi: (o) => o.account_name || '—' },
    { kunci: 'status', label: 'Status', isi: (o) => o.status || '—' },
    { kunci: 'omzet', label: 'Omzet produk', rata: 'kanan', isi: (o) => <span className="tabular-nums md:whitespace-nowrap">{fmtRp(o.revenue_product)}</span> },
    { kunci: 'hitung', label: 'Dihitung?', isi: (o) => (o.counted
      ? <span className="text-[hsl(var(--success-text))]">Ya{o.note ? <span className="text-[hsl(var(--warning-text))]"> · {o.note}</span> : null}</span>
      : <span className="text-muted-foreground">Tidak — {o.why_not_counted}</span>) },
  ];
  const kolomSesi = [
    { kunci: 'tgl', label: 'Tanggal', hp: 'keterangan', isi: (x) => <span className="tabular-nums md:whitespace-nowrap">{tgl(x.date)}</span> },
    { kunci: 'judul', label: 'Sesi', hp: 'judul', isi: (x) => x.title || '—' },
    { kunci: 'toko', label: 'Toko', isi: (x) => x.account_name || '—' },
    { kunci: 'omzet', label: 'Omzet sesi', rata: 'kanan', isi: (x) => <span className="tabular-nums md:whitespace-nowrap">{fmtRp(x.revenue)}</span> },
    { kunci: 'penonton', label: 'Penonton / puncak', rata: 'kanan', isi: (x) => <span className="tabular-nums">{fmtNum(x.viewers)} / {fmtNum(x.peak_viewers)}</span> },
    { kunci: 'order', label: 'Pesanan', rata: 'kanan', isi: (x) => <span className="tabular-nums">{fmtNum(x.orders)}</span> },
    { kunci: 'durasi', label: 'Durasi', rata: 'kanan', isi: (x) => (x.duration_minutes ? `${x.duration_minutes} menit` : '—') },
  ];

  const TAB_RINCIAN = detail && !detail.error ? [
    { key: 'konten', label: 'Konten', count: (detail.contents || []).length, icon: Video },
    { key: 'pesanan', label: 'Pesanan', count: (detail.orders || []).length, icon: ShoppingCart },
    { key: 'sesi', label: 'Sesi live', count: (detail.sessions || []).length, icon: Radio },
  ] : [];

  return (
    <PageLayout testId="creator-scorecard-view" title="Scorecard kreator"
      subtitle="Target vs pencapaian kreator per bulan, dari tiga sumber angka yang terpisah."
      filters={<>
        <SmartNativeSelect value={bulan} onChange={(e) => setBulan(e.target.value)} className="w-full" wrapperClassName="w-44 max-w-full" searchable={false}
          data-testid="scorecard-month">
          {bulanPilihan.map((b) => <option key={b.value} value={b.value}>{b.label}</option>)}
        </SmartNativeSelect>
        <MarketingAccountSelect token={token} value={accountId} onChange={setAccountId}
          includeAll allLabel="Semua toko" required={false} label="" testId="scorecard-account-select" className="w-52" />
        <div className="relative w-full sm:w-56">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Cari nama atau kode kreator"
            className="pl-8" data-testid="scorecard-search" />
        </div>
      </>}
      tools={<>
        <TombolUnduh namaBerkas={`scorecard-kreator-${bulan}`} namaLembar="Scorecard" baris={rows} kolom={kolomUnduh}
          testId="scorecard-export-csv" />
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="scorecard-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={data && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="scorecard-kpi">
          <StatTile label="Target omzet" value={fmtRp(t.revenue_target)} sub={`${rowsAll.length} kreator dinilai`}
            hint="Jumlah target omzet kreator yang ditetapkan untuk bulan ini." />
          <StatTile label="Omzet pesanan" value={fmtRp(t.order_revenue)} testId="scorecard-kpi-returns"
            sub={`${t.revenue_pct_orders == null ? 'tanpa target' : `${pct(t.revenue_pct_orders)} target`} · ${(t.orders_returned || 0) > 0
              ? `setelah retur ${fmtRp(t.order_revenue_net_returns)}` : 'tanpa retur'}`}
            hint="Dari pesanan nyata yang membawa kode kreator (sumber uang resmi)." />
          <StatTile label="Omzet sesi live" value={fmtRp(t.session_revenue)} hint="Dari sesi live yang dicatat staf — terpisah, jangan dijumlah dengan omzet pesanan." />
          <StatTile label="GMV KPI konten" value={fmtRp(t.gmv_kpi)}
            sub={`${fmtNum(t.contents)} konten · ${fmtNum(t.posted)} terbit · cakupan KPI ${pct(t.kpi_coverage_pct || 0)}`}
            hint="Dari KPI platform per konten — terpisah, jangan dijumlah dengan omzet pesanan." />
        </div>
      )}
      footer={rows.length > 10 && (
        <PaginationLite page={pg.page} totalPages={pg.totalPages} total={pg.total} pageSize={pg.pageSize} onPageChange={pg.setPage} />
      )}>
      {noTarget.length > 0 && (
        <Notice tone="warning" icon={AlertTriangle} testId="scorecard-no-target"
          title={`${noTarget.length} kreator belum punya target ${MONTHS[month - 1]} ${year}`}
          action={<Button size="sm" variant="outline" onClick={gotoTarget} data-testid="scorecard-goto-target"><Target />Tetapkan target</Button>}>
          {noTarget.slice(0, 8).join(' · ')}{noTarget.length > 8 ? ' …' : ''} — pencapaiannya ditandai "belum ada target", bukan 0%.
        </Notice>
      )}
      {loading && !data ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Menghitung pencapaian kreator…</p>
      ) : (
        <TabelData kolom={kolom} baris={pg.paged} kunci={(r) => r.creator_id} onKlikBaris={openDetail} testId="scorecard-table"
          kosong={<EmptyState testId="scorecard-empty" title={rowsAll.length === 0 ? 'Belum ada kreator yang bisa dinilai' : 'Tidak ada kreator yang cocok'}
            description={rowsAll.length === 0 ? 'Belum ada kreator aktif pada bulan ini.' : `Tidak ada kreator yang cocok dengan "${query}".`} />} />
      )}
      {(data?.data_notes || []).length > 0 && (
        <Notice tone="info" icon={Info} title="Catatan tentang data" testId="scorecard-notes">
          <ul className="list-disc space-y-0.5 pl-4">{(data.data_notes || []).map((n, i) => <li key={i}>{rapikanCatatan(n)}</li>)}</ul>
        </Notice>
      )}

      {/* ══════ RINCIAN: DARI MANA ANGKA SATU BARIS BERASAL ══════ */}
      {detailOf && (
        <DetailPopup open onClose={() => { setDetailOf(null); setDetail(null); }} testId="scorecard-detail-dialog"
          judul={`Rincian ${detailOf.creator_name} · ${MONTHS[month - 1]} ${year}`}
          status={<StatusSkor s={detailOf.achievement.status} />}
          keterangan="Tiga daftar di bawah adalah tiga sumber angka yang berbeda dan tidak dijumlah. Totalnya sama dengan baris di tabel.">
          {detailLoading ? (
            <p className="py-6 text-center text-sm text-muted-foreground">Menelusuri asal angka…</p>
          ) : detail?.error ? (
            <p className="py-6 text-center text-sm text-[hsl(var(--danger-text))]">{detail.error}</p>
          ) : detail ? (
            <>
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="scorecard-detail-totals">
                <StatTile label="Omzet pesanan" value={fmtRp(detail.totals?.order_revenue)} sub={`${detail.totals?.order_count || 0} pesanan dihitung`} />
                <StatTile label="Setelah retur" value={fmtRp(detail.totals?.order_revenue_net_returns)}
                  sub={`${detail.totals?.orders_returned_counted || 0} retur · ${fmtRp(detail.totals?.orders_returned_counted_revenue)}`} />
                <StatTile label="Omzet sesi live" value={fmtRp(detail.totals?.session_revenue)} sub={`${detail.totals?.sessions || 0} sesi`} />
                <StatTile label="GMV KPI konten" value={fmtRp(detail.totals?.gmv_kpi)}
                  sub={`${detail.totals?.with_kpi || 0}/${detail.totals?.contents || 0} konten ber-KPI · target ${detail.target?.revenue == null ? '—' : fmtRp(detail.target.revenue)}`} />
              </div>
              {(detail.data_notes || []).filter((n) => n.startsWith('PERLU KEPUTUSAN')).map((n, i) => (
                <Notice key={i} tone="warning" icon={AlertTriangle} testId="scorecard-detail-decision">{rapikanCatatan(n.replace(/^PERLU KEPUTUSAN/, 'Perlu keputusan'))}</Notice>
              ))}
              <div className="flex flex-wrap items-center gap-2">
                <div className="min-w-0 flex-1">
                  <FilterChips options={TAB_RINCIAN} value={detailTab} onChange={setDetailTab} hideWhenEmpty={false} testId="scorecard-detail-tab" />
                </div>
                <TombolUnduh namaBerkas={`rincian-${detailTab}-kreator-${bulan}`} namaLembar="Rincian" testId="scorecard-detail-unduh"
                  baris={detailTab === 'konten' ? (detail.contents || []) : detailTab === 'pesanan' ? (detail.orders || []) : (detail.sessions || [])}
                  kolom={detailTab === 'konten' ? [
                    { label: 'Tanggal', nilai: (c) => tgl(c.date) }, { label: 'Judul', nilai: (c) => c.title || '' },
                    { label: 'Status', nilai: (c) => STATUS_KONTEN[c.status] || '' }, { label: 'KPI', nilai: (c) => (c.has_kpi ? 'Ada' : 'Belum') },
                    { label: 'Tayangan', nilai: (c) => Number(c.views) || 0 }, { label: 'GMV KPI', nilai: (c) => Number(c.gmv_kpi) || 0 },
                    { label: 'Pesanan (KPI)', nilai: (c) => Number(c.orders) || 0 }, { label: 'Tautan', nilai: (c) => c.published_url || '' },
                  ] : detailTab === 'pesanan' ? [
                    { label: 'Nomor pesanan', nilai: (o) => o.order_id || '' }, { label: 'Tanggal', nilai: (o) => tgl(o.order_date) },
                    { label: 'Toko', nilai: (o) => o.account_name || '' }, { label: 'Status', nilai: (o) => o.status || '' },
                    { label: 'Omzet produk', nilai: (o) => Number(o.revenue_product) || 0 },
                    { label: 'Dihitung', nilai: (o) => (o.counted ? `Ya${o.note ? ` · ${o.note}` : ''}` : `Tidak — ${o.why_not_counted || ''}`) },
                  ] : [
                    { label: 'Tanggal', nilai: (x) => tgl(x.date) }, { label: 'Sesi', nilai: (x) => x.title || '' },
                    { label: 'Toko', nilai: (x) => x.account_name || '' }, { label: 'Omzet sesi', nilai: (x) => Number(x.revenue) || 0 },
                    { label: 'Penonton', nilai: (x) => Number(x.viewers) || 0 }, { label: 'Penonton puncak', nilai: (x) => Number(x.peak_viewers) || 0 },
                    { label: 'Pesanan', nilai: (x) => Number(x.orders) || 0 }, { label: 'Durasi (menit)', nilai: (x) => Number(x.duration_minutes) || 0 },
                  ]} />
              </div>
              {detailTab === 'konten' && (
                <TabelData kolom={kolomKonten} baris={detail.contents || []} testId="scorecard-detail-contents"
                  kosong={<EmptyState title="Tidak ada konten pada bulan ini" />} />
              )}
              {detailTab === 'pesanan' && (
                <TabelData kolom={kolomPesanan} baris={detail.orders || []} testId="scorecard-detail-orders"
                  kosong={<EmptyState title="Tidak ada pesanan yang membawa kreator ini pada bulan ini" />} />
              )}
              {detailTab === 'sesi' && (
                <TabelData kolom={kolomSesi} baris={detail.sessions || []} testId="scorecard-detail-sessions"
                  kosong={<EmptyState title="Tidak ada sesi live yang dicatat untuk kreator ini" />} />
              )}
              {detail.truncated && (
                <p className="text-sm text-[hsl(var(--warning-text))]">Daftar dipotong pada batas aman. Persempit dengan pilihan toko/bulan untuk melihat sisanya.</p>
              )}
              <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
                {(detail.data_notes || []).filter((n) => !n.startsWith('PERLU KEPUTUSAN')).map((n, i) => <li key={i}>{rapikanCatatan(n)}</li>)}
              </ul>
            </>
          ) : null}
        </DetailPopup>
      )}
    </PageLayout>
  );
}

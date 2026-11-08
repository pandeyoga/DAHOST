/**
 * ContentPerformanceView — PERFORMA KONTEN & KREATOR (F7.3/F7.4 · sesi #35).
 *
 * Kenapa layar ini ada: kalender konten menjawab "apa yang akan diposting", bukan
 * "konten mana yang menghasilkan". Tanpa layar ini, KPI konten yang sudah diisi tidak
 * pernah bisa dibaca per kreator untuk rapat mingguan.
 *
 * SESI #35 — pemilik minta KPI bisa dibaca **per konten / jenis / toko / KOL**. Mode
 * "Per Konten" adalah satuan paling kecil (satu baris = satu konten) dan sekaligus
 * DAFTAR KERJA: baris tanpa KPI tidak disembunyikan, malah ditandai supaya staf tahu
 * apa yang harus diisi. Pengisian KPI dilakukan MANUAL di layar ini juga (dialog),
 * karena angkanya tidak ada gunanya kalau harus pindah menu untuk memasukkannya.
 *
 * Dua angka omzet DIPISAH dengan sengaja: `GMV (KPI)` dari platform per konten, dan
 * `Omzet pesanan` dari pesanan nyata (`marketing_orders.creator_id`). Menjumlahkannya
 * berarti menghitung satu penjualan dua kali — jadi layar menaruhnya bersebelahan
 * beserta **cakupan KPI** supaya pembaca tahu berapa bagian yang benar-benar terukur.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout (judul disembunyikan di hub), periode = PeriodPicker (dulu dua input
 * tanggal bawaan peramban), 4 StatTile berketerangan (dulu 6 kartu), tabel + unduh Excel/CSV, rincian kelompok = popup,
 * label Indonesia. Tampilan Kartu untuk kelompok diganti tabel (HP: kartu ringkas). KPI yang belum diisi tampil
 * '—' (bukan 0) supaya tidak terbaca sebagai nol tayangan.
 */
import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Info, PencilLine, ExternalLink } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { formatRupiah, formatDateID } from '@/lib/format';
import PeriodPicker, { periodFromPreset } from '../finance/PeriodPicker';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';
import ContentKpiDialog from './ContentKpiDialog';

const API = process.env.REACT_APP_BACKEND_URL;
const fmtRp = formatRupiah;
const fmtNum = (n) => new Intl.NumberFormat('id-ID').format(Math.round(n || 0));
const pct = (n, d = 1) => `${Number(n || 0).toFixed(d).replace('.', ',')}%`;
const GROUPS = [
  { v: 'content', l: 'Per konten' },
  { v: 'creator', l: 'Per kreator (KOL)' },
  { v: 'content_type', l: 'Per jenis konten' },
  { v: 'account', l: 'Per toko' },
  { v: 'platform', l: 'Per platform' },
];
const KPI_STATES = [
  { v: 'all', l: 'Semua konten' },
  { v: 'missing', l: 'Belum ada KPI' },
  { v: 'filled', l: 'Sudah ada KPI' },
];
const SORTS = [
  { v: 'views', l: 'Tayangan terbanyak' },
  { v: 'gmv', l: 'GMV terbesar' },
  { v: 'engagement', l: 'Interaksi terbanyak' },
  { v: 'cvr', l: 'Konversi tertinggi' },
  { v: 'date', l: 'Terbaru' },
];
const STATUS = { draft: ['Draf', 'muted'], scheduled: ['Terjadwal', 'info'], posted: ['Tayang', 'success'], cancelled: ['Batal', 'danger'] };
/**
 * Catatan data dari server memuat istilah program & huruf besar penekanan (mis. "(`marketing_orders.creator_id`)",
 * "'no_target'", "link", "views", "BELUM"). Dirapikan di layar saja — isinya tidak diubah. Dipakai juga oleh
 * Scorecard kreator.
 */
const GANTI_ISTILAH = [
  [/\s*\(`?[a-z_]+\.[a-z_]+`?\)/g, ''], [/`/g, ''],
  [/'no_target'/g, '"belum ada target"'], [/'posted'/g, '"tayang"'],
  [/GMV\/view/g, 'GMV per tayangan'], [/\beng\. rate\b/g, 'tingkat interaksi'], [/\bCVR\b/g, 'konversi'],
  [/\bAOV\b/g, 'nilai rata-rata pesanan'], [/\bviews\b/g, 'tayangan'], [/\bview\b/g, 'tayangan'],
  [/\bengagement\b/g, 'interaksi'], [/\blink\b/g, 'tautan'], [/\bdi-assign\b/g, 'ditugaskan'],
  [/\bmeng-assign\b/g, 'menugaskan'], [/\bassign\b/g, 'penugasan'],
];
const SINGKATAN = new Set(['GMV', 'KPI', 'HPP', 'PPN', 'SKU', 'KOL', 'CSV']);
export function rapikanCatatan(teks) {
  let s = String(teks || '');
  GANTI_ISTILAH.forEach(([pola, ganti]) => { s = s.replace(pola, ganti); });
  // Huruf besar penekanan → huruf biasa (singkatan resmi tetap).
  s = s.replace(/\b[A-Z]{4,}\b/g, (w) => (SINGKATAN.has(w) ? w : w.toLowerCase()));
  return s.charAt(0).toUpperCase() + s.slice(1);
}

const StatusKonten = ({ s }) => <StatusBadge status={s} label={(STATUS[s] || [s || '—'])[0]} tone={(STATUS[s] || [])[1]} />;

export default function ContentPerformanceView({ token }) {
  // Bawaan "3 bulan" (bulan ini + 2 bulan lalu), bukan "awal bulan": dibuka tanggal 1, rentang awal-bulan
  // hanya memuat satu hari dan layar tampak kosong padahal data pekan lalu ada. (8 Nov 2026: dulu 30 hari
  // bergulir = mode "Pilih tanggal", yang memaksa dua kotak tanggal bawaan browser tampil sejak awal.)
  const [periode, setPeriode] = useState(() => periodFromPreset('3m'));
  const from = periode.from;
  const to = periode.to;
  const [groupBy, setGroupBy] = useState('content');
  const [kpiState, setKpiState] = useState('all');
  const [sort, setSort] = useState('views');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);
  const [rincian, setRincian] = useState(null);
  const perContent = groupBy === 'content';

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const url = perContent
        ? `${API}/api/marketing/content-calendar/performance/contents`
          + `?date_from=${from}&date_to=${to}&kpi_state=${kpiState}&sort=${sort}`
        : `${API}/api/marketing/content-calendar/performance`
          + `?group_by=${groupBy}&date_from=${from}&date_to=${to}`;
      const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
    } catch (e) {
      toast.error(`Gagal memuat performa konten: ${e.message}`);
      setData(null);
    } finally { setLoading(false); }
  }, [groupBy, perContent, from, to, kpiState, sort, token]);

  useEffect(() => { load(); }, [load]);

  const t = data?.totals || {};
  const rows = data?.rows || [];
  // KPI belum ada yang diisi → angka tayangan/GMV belum terukur, bukan nol.
  const terukur = Number(t.with_kpi || 0) > 0;
  const ukur = (v, f = fmtNum) => (terukur ? f(v) : '—');

  const kolomKonten = [
    { kunci: 'tanggal', label: 'Tanggal', hp: 'keterangan', isi: (r) => <span className="tabular-nums md:whitespace-nowrap">{r.date ? formatDateID(r.date) : '—'}</span> },
    { kunci: 'konten', label: 'Konten', hp: 'judul', isi: (r) => (
      <div className="min-w-0 md:max-w-[16rem]">
        <p className="truncate font-medium" title={r.title}>{r.title}</p>
        <p className="text-xs text-muted-foreground">{r.content_type_label || '—'} · {r.published_url ? (
          <a href={r.published_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}
            className="inline-flex items-center gap-0.5 text-primary" data-testid={`perf-content-link-${r.id}`}>
            <ExternalLink className="h-3 w-3" />buka</a>) : 'tanpa tautan terbit'}</p>
      </div>) },
    { kunci: 'toko', label: 'Toko / kreator', isi: (r) => (
      <span className="md:whitespace-nowrap">{r.account_name || '—'}<span className="block text-xs text-muted-foreground">{r.creator_name || 'tanpa kreator'}</span></span>) },
    { kunci: 'status', label: 'Status', isi: (r) => <StatusKonten s={r.status} /> },
    { kunci: 'views', label: 'Tayangan', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.kpi_filled ? fmtNum(r.kpi?.views) : '—'}</span> },
    { kunci: 'eng', label: 'Interaksi', rata: 'kanan', isi: (r) => (r.kpi_filled
      ? <span className="tabular-nums">{fmtNum(r.kpi_derived?.engagement)}<span className="block text-xs text-muted-foreground">{pct(r.kpi_derived?.engagement_rate, 2)}</span></span>
      : <span className="text-muted-foreground">—</span>) },
    { kunci: 'order', label: 'Pesanan', rata: 'kanan', isi: (r) => (r.kpi_filled
      ? <span className="tabular-nums">{fmtNum(r.kpi?.orders)}<span className="block text-xs text-muted-foreground">konversi {pct(r.kpi_derived?.cvr, 3)}</span></span>
      : <span className="text-muted-foreground">—</span>) },
    { kunci: 'gmv', label: 'GMV (KPI)', rata: 'kanan', isi: (r) => <span className="tabular-nums font-medium md:whitespace-nowrap">{r.kpi_filled ? fmtRp(r.kpi?.gmv) : '—'}</span> },
    { kunci: 'kpi', label: 'KPI', isi: (r) => (r.kpi_filled
      ? <StatusBadge status="terisi" label="Terisi" tone="success" />
      : <StatusBadge status="belum" label="Belum diisi" tone="warning" />) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <Button size="sm" variant="outline" onClick={() => setEditing(r)} data-testid={`perf-fill-kpi-${r.id}`}><PencilLine />Isi KPI</Button>) },
  ];
  const kolomKelompok = [
    { kunci: 'nama', label: 'Nama', hp: 'judul', isi: (r) => (
      <span className="font-medium">{r.label}{r.creator_code ? <span className="block text-xs font-normal text-muted-foreground">{r.creator_code}</span> : null}</span>) },
    { kunci: 'konten', label: 'Konten / terbit', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtNum(r.contents)} / {fmtNum(r.posted)}</span> },
    { kunci: 'cakupan', label: 'Cakupan KPI', rata: 'kanan', isi: (r) => (
      <span className={`tabular-nums ${r.kpi_coverage_pct >= 80 ? 'text-[hsl(var(--success-text))]' : 'text-[hsl(var(--warning-text))]'}`}>{pct(r.kpi_coverage_pct)}</span>) },
    { kunci: 'views', label: 'Tayangan', rata: 'kanan', isi: (r) => (r.with_kpi ? <span className="tabular-nums">{fmtNum(r.views)}</span> : <span className="text-muted-foreground">—</span>) },
    { kunci: 'eng', label: 'Interaksi', rata: 'kanan', isi: (r) => (r.with_kpi
      ? <span className="tabular-nums">{fmtNum(r.engagement)}<span className="block text-xs text-muted-foreground">{pct(r.engagement_rate, 2)}</span></span>
      : <span className="text-muted-foreground">—</span>) },
    { kunci: 'gmv', label: 'GMV (KPI)', rata: 'kanan', isi: (r) => <span className="tabular-nums font-medium md:whitespace-nowrap">{r.with_kpi ? fmtRp(r.gmv_kpi) : '—'}</span> },
    { kunci: 'omzet', label: 'Omzet pesanan', rata: 'kanan', isi: (r) => (
      <span className="tabular-nums md:whitespace-nowrap">{fmtRp(r.order_revenue)}<span className="block text-xs text-muted-foreground">{fmtNum(r.order_count)} pesanan</span></span>) },
  ];
  const unduhKonten = [
    { label: 'Tanggal', nilai: (r) => (r.date ? formatDateID(r.date) : '') },
    { label: 'Konten', nilai: (r) => r.title },
    { label: 'Jenis', nilai: (r) => r.content_type_label || '' },
    { label: 'Toko', nilai: (r) => r.account_name || '' },
    { label: 'Kreator', nilai: (r) => r.creator_name || '' },
    { label: 'Status', nilai: (r) => (STATUS[r.status] || [r.status || ''])[0] },
    { label: 'Tayangan', nilai: (r) => (r.kpi_filled ? Number(r.kpi?.views) || 0 : '') },
    { label: 'Interaksi', nilai: (r) => (r.kpi_filled ? Number(r.kpi_derived?.engagement) || 0 : '') },
    { label: 'Tingkat interaksi (%)', nilai: (r) => (r.kpi_filled ? Number(r.kpi_derived?.engagement_rate) || 0 : '') },
    { label: 'Konversi (%)', nilai: (r) => (r.kpi_filled ? Number(r.kpi_derived?.cvr) || 0 : '') },
    { label: 'Pesanan', nilai: (r) => (r.kpi_filled ? Number(r.kpi?.orders) || 0 : '') },
    { label: 'GMV (KPI)', nilai: (r) => (r.kpi_filled ? Number(r.kpi?.gmv) || 0 : '') },
    { label: 'KPI terisi', nilai: (r) => (r.kpi_filled ? 'Ya' : 'Belum') },
    { label: 'Tautan terbit', nilai: (r) => r.published_url || '' },
  ];
  const unduhKelompok = [
    { label: 'Nama', nilai: (r) => r.label },
    { label: 'Konten', nilai: (r) => Number(r.contents) || 0 },
    { label: 'Terbit', nilai: (r) => Number(r.posted) || 0 },
    { label: 'KPI terisi', nilai: (r) => Number(r.with_kpi) || 0 },
    { label: 'Cakupan KPI (%)', nilai: (r) => Number(r.kpi_coverage_pct) || 0 },
    { label: 'Tayangan', nilai: (r) => Number(r.views) || 0 },
    { label: 'Tayangan per konten', nilai: (r) => Number(r.views_per_content) || 0 },
    { label: 'Interaksi', nilai: (r) => Number(r.engagement) || 0 },
    { label: 'Tingkat interaksi (%)', nilai: (r) => Number(r.engagement_rate) || 0 },
    { label: 'Disimpan', nilai: (r) => Number(r.saves) || 0 },
    { label: 'Rata-rata rasio klik (%)', nilai: (r) => Number(r.ctr_avg) || 0 },
    { label: 'Pesanan (KPI)', nilai: (r) => Number(r.orders) || 0 },
    { label: 'GMV (KPI)', nilai: (r) => Number(r.gmv_kpi) || 0 },
    { label: 'GMV per konten', nilai: (r) => Number(r.gmv_per_content) || 0 },
    { label: 'Omzet pesanan', nilai: (r) => Number(r.order_revenue) || 0 },
    { label: 'Jumlah pesanan', nilai: (r) => Number(r.order_count) || 0 },
  ];

  const kosongPerforma = (
    <EmptyState testId="perf-empty" title={data?.scope_empty ? 'Belum ada toko untuk akun Anda' : 'Belum ada konten di periode ini'}
      description={data?.scope_empty
        ? 'Layar ini kosong karena kewenangan, bukan karena tidak ada konten. Minta admin menugaskan toko Anda.'
        : 'Ubah periode atau tambahkan konten di tab Kalender & rencana.'} />
  );

  return (
    <PageLayout testId="content-performance-view" title="Performa konten"
      subtitle="KPI konten per konten, kreator, jenis, toko, atau platform."
      filters={<>
        <PeriodPicker value={periode} onChange={setPeriode} testId="perf-period" />
        <SmartNativeSelect value={groupBy} onChange={(e) => setGroupBy(e.target.value)} className="w-full" wrapperClassName="w-44 max-w-full" searchable={false}
          data-testid="perf-group-by">
          {GROUPS.map((g) => <option key={g.v} value={g.v}>{g.l}</option>)}
        </SmartNativeSelect>
        {perContent && <>
          <SmartNativeSelect value={kpiState} onChange={(e) => setKpiState(e.target.value)} className="w-full" wrapperClassName="w-40 max-w-full" searchable={false}
            data-testid="perf-kpi-state">
            {KPI_STATES.map((x) => <option key={x.v} value={x.v}>{x.l}</option>)}
          </SmartNativeSelect>
          <SmartNativeSelect value={sort} onChange={(e) => setSort(e.target.value)} className="w-full" wrapperClassName="w-48 max-w-full" searchable={false}
            data-testid="perf-sort">
            {SORTS.map((x) => <option key={x.v} value={x.v}>{x.l}</option>)}
          </SmartNativeSelect>
        </>}
      </>}
      tools={<>
        <TombolUnduh namaBerkas={`performa-konten-${groupBy}`} namaLembar="Performa" baris={rows}
          kolom={perContent ? unduhKonten : unduhKelompok} testId="perf-unduh" />
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="perf-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={data && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="perf-kpi">
          <StatTile label="Konten" value={fmtNum(t.contents)} sub={`${fmtNum(t.posted)} sudah terbit`}
            hint="Konten di periode ini (semua toko yang bisa Anda lihat)." />
          <StatTile label="Cakupan KPI" value={pct(t.kpi_coverage_pct)} sub={`${fmtNum(t.with_kpi)} konten sudah ber-KPI`}
            accent={Number(t.kpi_coverage_pct || 0) >= 80 ? 'success' : 'warning'} hint="Bagian konten yang KPI-nya sudah diisi." />
          <StatTile label="Tayangan" value={ukur(t.views)} sub={terukur ? `${fmtNum(t.engagement)} interaksi` : 'Belum ada KPI yang diisi'}
            hint="Jumlah dari KPI konten yang sudah diisi." />
          <StatTile label="GMV (KPI platform)" value={ukur(t.gmv_kpi, fmtRp)}
            sub={perContent ? (terukur ? `${fmtNum(t.orders)} pesanan dari KPI konten` : 'Belum ada KPI yang diisi')
              : `Omzet pesanan ber-kreator ${fmtRp(t.order_revenue)}`}
            hint="GMV dari KPI platform per konten; omzet pesanan nyata dihitung terpisah agar tidak terhitung dua kali." />
        </div>
      )}>
      {data?.truncated && (
        <Notice tone="warning" title="Daftar terpotong">Hanya {fmtNum(data.limit)} konten pertama yang dimuat. Persempit periode.</Notice>
      )}
      {loading && !data ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Menghitung performa konten…</p>
      ) : perContent ? (
        <TabelData kolom={kolomKonten} baris={rows} onKlikBaris={setEditing} testId="perf-content-table" kosong={kosongPerforma} />
      ) : (
        <TabelData kolom={kolomKelompok} baris={rows} kunci={(r) => r.key} onKlikBaris={setRincian} testId="perf-table" kosong={kosongPerforma} />
      )}
      {(data?.data_notes || []).length > 0 && (
        <Notice tone="info" icon={Info} title="Catatan tentang data" testId="perf-notes">
          <ul className="list-disc space-y-0.5 pl-4">
            {(data.data_notes || []).map((n, i) => <li key={i}>{rapikanCatatan(n)}</li>)}
          </ul>
        </Notice>
      )}
      {rincian && (
        <DetailPopup open onClose={() => setRincian(null)} judul={rincian.label} testId="perf-detail"
          keterangan={`${formatDateID(from)} – ${formatDateID(to)}`}>
          <dl className="divide-y divide-[var(--glass-border)]">
            {unduhKelompok.slice(1).map((k) => (
              <BarisDetail key={k.label} label={k.label}>
                <span className="tabular-nums">{/(GMV|Omzet)/.test(k.label) ? fmtRp(k.nilai(rincian))
                  : /%/.test(k.label) ? pct(k.nilai(rincian), 2) : fmtNum(k.nilai(rincian))}</span>
              </BarisDetail>
            ))}
          </dl>
        </DetailPopup>
      )}
      <ContentKpiDialog open={!!editing} content={editing} token={token}
        onClose={() => setEditing(null)} onSaved={load} />
    </PageLayout>
  );
}

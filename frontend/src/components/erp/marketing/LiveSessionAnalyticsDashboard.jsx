/**
 * LiveSessionAnalyticsDashboard — Phase 3 P1
 *
 * Advanced analytics untuk Live Session (Shopee/TikTok/Instagram).
 * Fitur: KPI overview, platform share, session comparison, host leaderboard,
 *        revenue trend chart, account health.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout (judul disembunyikan di hub Live Selling), penyaring satu baris
 * (akun toko = pilihan biasa; dulu MarketingAccountSelect berlabel kosong), 4 kartu StatTile, tampilan dipilih
 * dengan pil (dulu deret <button> buatan sendiri = tab di dalam tab hub), semua <table> buatan sendiri → TabelData
 * + unduh untuk tabel yang tampil, label Indonesia (Revenue/Top Sessions/Account Health → Omzet/Sesi teratas/
 * Kesehatan akun), warna token. Kartu & angka diperiksa terhadap data (90 hari: 31 sesi, Rp926.634.924,
 * 5.867 pesanan, rata-rata penonton puncak 1.496 = rata-rata `peak_viewers`).
 * Koreksi label: "Avg Peak Viewers" = rata-rata penonton PUNCAK (benar, dipertahankan); "Revenue Harian" dulu
 * hanya 14 hari bersesi terakhir tanpa keterangan → kini tabel semua hari + keterangan; total produk terlaris
 * = jumlah produk di daftar (maks 20), bukan semua produk → diberi keterangan.
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import axios from 'axios';
import { RefreshCw, ChevronUp, ChevronDown, Package } from 'lucide-react';
import { Button } from '../../ui/button';
import SmartNativeSelect from '../../ui/smart-native-select';
import FilterChips from '../../ui/filter-chips';
import TabelData from '../../ui/tabel-data';
import TombolUnduh from '../../ui/tombol-unduh';
import { Progress } from '../../ui/progress';
import PaginationLite, { useClientPagination } from '../../ui/pagination-lite';
import { useToast } from '../../../hooks/use-toast';
import { useMarketingAccounts } from '../../../hooks/useMarketingAccounts';
import { formatDateID } from '../../../lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from '../moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL || '';

const FMT_IDR = (v) => `Rp ${Math.round(+v || 0).toLocaleString('id-ID')}`;
const FMT_NUM = (v) => (+v || 0).toLocaleString('id-ID');
const FMT_PCT = (v) => `${(+v || 0).toFixed(1).replace('.', ',')}%`;

const PLATFORM = { shopee: 'Shopee', tiktok: 'TikTok', instagram: 'Instagram', tokopedia: 'Tokopedia' };
const labelPlatform = (p) => PLATFORM[p] || (p ? p.charAt(0).toUpperCase() + p.slice(1) : '—');
const PLATFORMS_LIST = ['shopee', 'tiktok', 'instagram', 'tokopedia'];
const KESEHATAN = {
  excellent: { label: 'Sangat baik', tone: 'success' }, good: { label: 'Baik', tone: 'info' },
  fair: { label: 'Cukup', tone: 'warning' }, poor: { label: 'Kurang', tone: 'danger' },
};
// "2026-W33" → "Minggu 33 · 2026"
const labelMinggu = (p) => { const m = /^(\d{4})-W(\d{1,2})$/.exec(String(p || '')); return m ? `Minggu ${Number(m[2])} · ${m[1]}` : (p || '—'); };
const tgl = (v) => (v ? formatDateID(v) : '—');

function DeltaBadge({ pct }) {
  if (pct == null) return null;
  const pos = pct >= 0;
  return (
    <span className={`inline-flex items-center gap-0.5 text-sm font-medium tabular-nums ${
      pos ? 'text-[hsl(var(--success-text))]' : 'text-[hsl(var(--danger-text))]'
    }`}>
      {pos ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
      {String(Math.abs(pct)).replace('.', ',')}%
    </span>
  );
}

function MiniBarChart({ data, valueKey = 'revenue', labelKey = 'date', labelFn = (x) => x }) {
  if (!data || data.length === 0) return null;
  const max = Math.max(...data.map((d) => d[valueKey] || 0), 1);
  return (
    <div className="flex h-24 items-end gap-1 px-1" role="img" aria-label="Grafik omzet per periode">
      {data.slice(-14).map((d, i) => (
        <div key={i} className="group relative flex h-full flex-1 flex-col items-center justify-end" title={`${labelFn(d[labelKey])}: ${FMT_IDR(d[valueKey])}`}>
          <div className="w-full rounded-sm bg-[hsl(var(--primary))] opacity-70 transition-all hover:opacity-100"
            style={{ height: `${((d[valueKey] || 0) / max) * 100}%` }} />
        </div>
      ))}
    </div>
  );
}

const TAMPILAN = [
  { key: 'overview', label: 'Ringkasan' },
  { key: 'sessions', label: 'Sesi teratas' },
  { key: 'products', label: 'Produk terlaris' },
  { key: 'leaderboard', label: 'Peringkat host' },
  { key: 'trend', label: 'Tren omzet' },
  { key: 'health', label: 'Kesehatan akun' },
];

export default function LiveSessionAnalyticsDashboard({ user, headers }) {
  const [overview, setOverview] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [leaderboard, setLeaderboard] = useState([]);
  const [trend, setTrend] = useState([]);
  const [accountHealth, setAccountHealth] = useState([]);
  // F18#3 — panel "Produk Terlaris saat Live": endpoint sudah lama ada tetapi
  // TIDAK PUNYA LAYAR, dan sumber datanya pun belum bisa diisi. Keduanya beres.
  const [products, setProducts] = useState({ data: [], totals: {}, note: '' });
  const [accountId, setAccountId] = useState('');
  const [loading, setLoading] = useState(false);
  const [days, setDays] = useState('30');
  const [platform, setPlatform] = useState('all');
  const [activeTab, setActiveTab] = useState('overview');
  const { toast } = useToast();
  const authH = useMemo(() => headers || {}, [headers]);
  const { accounts } = useMarketingAccounts();

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const params = { days: parseInt(days) };
      if (platform && platform !== 'all') params.platform = platform;
      // F14 — filter toko dikirim ke SEMUA endpoint analitik yang menerimanya.
      if (accountId) params.account_id = accountId;

      const [ovRes, sessRes, lbRes, trendRes, healthRes, prodRes] = await Promise.all([
        axios.get(`${API}/api/marketing/live/analytics/overview`, { headers: authH, params }),
        axios.get(`${API}/api/marketing/live/analytics/sessions-comparison`, { headers: authH, params: { ...params, limit: 10 } }),
        axios.get(`${API}/api/marketing/live/analytics/host-leaderboard`, { headers: authH, params }),
        axios.get(`${API}/api/marketing/live/analytics/revenue-trend`, { headers: authH, params: { ...params, granularity: 'weekly' } }),
        axios.get(`${API}/api/marketing/live/analytics/account-health`, { headers: authH, params: { days: parseInt(days), ...(accountId ? { account_id: accountId } : {}) } }),
        axios.get(`${API}/api/marketing/live/analytics/product-performance`, { headers: authH, params: { ...params, limit: 20 } }),
      ]);

      setOverview(ovRes.data);
      setSessions(sessRes.data?.data || []);
      setLeaderboard(lbRes.data?.data || []);
      setTrend(trendRes.data?.data || []);
      setAccountHealth(healthRes.data?.data || []);
      setProducts({
        data: prodRes.data?.data || [],
        totals: prodRes.data?.totals || {},
        note: prodRes.data?.note || '',
        source: prodRes.data?.source,
      });
    } catch (e) {
      toast({ title: 'Gagal memuat analitik live', description: e.response?.data?.detail, variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  }, [days, platform, accountId, authH, toast]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const kpi = overview?.kpi || {};
  const platformShare = overview?.platform_share || [];
  const dailyTrend = useMemo(() => [...(overview?.daily_trend || [])].reverse(), [overview]);
  const harian = useClientPagination(dailyTrend, 10);
  const kosongPeriode = `Belum ada sesi live dalam ${days} hari terakhir.`;

  // ── kolom per tampilan (dipakai tabel & unduhan) ──
  const KOLOM = {
    overview: {
      nama: 'pangsa-platform-live', baris: platformShare,
      unduh: [{ label: 'Platform', nilai: (p) => labelPlatform(p.platform) }, { label: 'Sesi', nilai: (p) => p.sessions },
        { label: 'Pesanan', nilai: (p) => p.orders }, { label: 'Omzet', nilai: (p) => Number(p.revenue) || 0 }, { label: 'Pangsa omzet (%)', nilai: (p) => p.revenue_share_pct }],
    },
    sessions: {
      nama: 'sesi-live-teratas', baris: sessions,
      unduh: [{ label: 'Peringkat', nilai: (s) => s.rank }, { label: 'Tanggal', nilai: (s) => tgl(s.session_date) }, { label: 'Platform', nilai: (s) => labelPlatform(s.platform) },
        { label: 'Akun toko', nilai: (s) => s.account_name || '' }, { label: 'Host', nilai: (s) => s.host_name || '' }, { label: 'Omzet', nilai: (s) => Number(s.total_revenue) || 0 },
        { label: 'Pesanan', nilai: (s) => s.orders_count }, { label: 'Penonton puncak', nilai: (s) => s.peak_viewers }, { label: 'Konversi (%)', nilai: (s) => s.conversion_rate },
        { label: 'Selisih dari rata-rata (%)', nilai: (s) => s.vs_avg_pct ?? '' }],
    },
    products: {
      nama: 'produk-terlaris-live', baris: products.data,
      unduh: [{ label: 'Peringkat', nilai: (p) => p.rank }, { label: 'SKU', nilai: (p) => p.sku || '' }, { label: 'Produk', nilai: (p) => p.name || '' },
        { label: 'Kategori', nilai: (p) => p.category || '' }, { label: 'Akun toko', nilai: (p) => p.account_name || '' }, { label: 'Unit', nilai: (p) => p.total_units_sold },
        { label: 'Omzet', nilai: (p) => Number(p.total_revenue) || 0 }, { label: 'Pangsa (%)', nilai: (p) => p.revenue_share_pct }, { label: 'Sesi', nilai: (p) => p.sessions_featured },
        { label: 'Unit per sesi', nilai: (p) => p.units_per_session }, { label: 'Harga rata-rata', nilai: (p) => Number(p.avg_price) || 0 }, { label: 'Margin kotor', nilai: (p) => Number(p.gross_margin) || 0 }],
    },
    leaderboard: {
      nama: 'peringkat-host-live', baris: leaderboard,
      unduh: [{ label: 'Peringkat', nilai: (h) => h.rank }, { label: 'Host', nilai: (h) => h.host_name }, { label: 'Sesi', nilai: (h) => h.total_sessions },
        { label: 'Omzet', nilai: (h) => Number(h.total_revenue) || 0 }, { label: 'Rata-rata per sesi', nilai: (h) => Number(h.avg_revenue_per_session) || 0 },
        { label: 'Rata-rata penonton puncak', nilai: (h) => h.avg_viewers }, { label: 'Konversi (%)', nilai: (h) => h.avg_conversion_rate }],
    },
    trend: {
      nama: 'tren-omzet-live-mingguan', baris: trend,
      unduh: [{ label: 'Minggu', nilai: (t) => labelMinggu(t.period) }, { label: 'Omzet', nilai: (t) => Number(t.revenue) || 0 }, { label: 'Sesi', nilai: (t) => t.sessions },
        { label: 'Pesanan', nilai: (t) => t.orders }, { label: 'Rata-rata per sesi', nilai: (t) => Number(t.avg_revenue_per_session) || 0 }],
    },
    health: {
      nama: 'kesehatan-akun-live', baris: accountHealth,
      unduh: [{ label: 'Akun toko', nilai: (a) => a.account_name }, { label: 'Platform', nilai: (a) => labelPlatform(a.platform) }, { label: 'Sesi', nilai: (a) => a.sessions },
        { label: 'Omzet', nilai: (a) => Number(a.total_revenue) || 0 }, { label: 'Konversi (%)', nilai: (a) => a.avg_conversion_rate }, { label: 'Skor', nilai: (a) => a.health_score },
        { label: 'Status', nilai: (a) => KESEHATAN[a.health_status]?.label || a.health_status || '' }],
    },
  };
  const aktif = KOLOM[activeTab];
  const angka = (v) => <span className="tabular-nums">{v}</span>;

  return (
    <PageLayout testId="live-analytics" title="Analitik live" subtitle="Performa sesi live di semua platform."
      filters={<>
        <SmartNativeSelect value={accountId} onChange={(e) => setAccountId(e.target.value)} className="w-56" data-testid="sel-analytics-account">
          <option value="">Semua toko</option>
          {accounts.map((a) => <option key={a.id} value={a.id}>{`${a.account_name} · ${labelPlatform(a.platform)}`}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={platform} onChange={(e) => setPlatform(e.target.value)} className="w-40" searchable={false} data-testid="sel-platform">
          <option value="all">Semua platform</option>
          {PLATFORMS_LIST.map((p) => <option key={p} value={p}>{labelPlatform(p)}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={days} onChange={(e) => setDays(e.target.value)} className="w-40" searchable={false} data-testid="sel-days">
          <option value="7">7 hari terakhir</option>
          <option value="30">30 hari terakhir</option>
          <option value="90">90 hari terakhir</option>
        </SmartNativeSelect>
      </>}
      tools={<>
        {aktif && <TombolUnduh namaBerkas={`${aktif.nama}-${days}-hari`} namaLembar="Data" baris={aktif.baris} kolom={aktif.unduh} testId="live-analytics-unduh" />}
        <Button variant="outline" size="icon" onClick={fetchAll} disabled={loading} title="Muat ulang" aria-label="Muat ulang" data-testid="btn-refresh-analytics">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="live-analytics-kpi">
          <StatTile label="Jumlah sesi" value={loading ? '…' : FMT_NUM(kpi.total_sessions)} sub={`${days} hari terakhir`} />
          <StatTile label="Omzet live" value={loading ? '…' : FMT_IDR(kpi.total_revenue_rp)}
            sub={kpi.revenue_delta_vs_prev_period_pct != null
              ? <span className="inline-flex items-center gap-1"><DeltaBadge pct={kpi.revenue_delta_vs_prev_period_pct} /> dari {days} hari sebelumnya</span>
              : 'Tidak ada pembanding'}
            hint={`Dibanding ${days} hari tepat sebelum periode ini.`} />
          <StatTile label="Pesanan" value={loading ? '…' : FMT_NUM(kpi.total_orders)} sub={`Rata-rata ${FMT_IDR(kpi.avg_revenue_per_session)} per sesi`} />
          <StatTile label="Rata-rata penonton puncak" value={loading ? '…' : FMT_NUM(kpi.avg_viewers)}
            sub={`Konversi rata-rata ${FMT_PCT(kpi.avg_conversion_rate)}`} hint="Rata-rata jumlah penonton tertinggi per sesi. Konversi = pesanan ÷ penonton." />
        </div>
      }>
      <FilterChips options={TAMPILAN} value={activeTab} onChange={setActiveTab} hideWhenEmpty={false} testId="live-analytics-view" ariaLabel="Tampilan" />

      {activeTab === 'overview' && (
        <div className="grid gap-4 lg:grid-cols-2">
          <section className="space-y-2">
            <p className="text-base font-semibold">Pangsa omzet per platform</p>
            <TabelData baris={platformShare} kunci={(r) => r.platform} testId="live-platform-share" kolom={[
              { kunci: 'p', label: 'Platform', hp: 'judul', isi: (p) => <span className="font-medium">{labelPlatform(p.platform)}</span> },
              { kunci: 's', label: 'Sesi', rata: 'kanan', isi: (p) => angka(FMT_NUM(p.sessions)) },
              { kunci: 'o', label: 'Pesanan', rata: 'kanan', isi: (p) => angka(FMT_NUM(p.orders)) },
              { kunci: 'r', label: 'Omzet', rata: 'kanan', hp: 'nilai', isi: (p) => angka(FMT_IDR(p.revenue)) },
              { kunci: 'pct', label: 'Pangsa', isi: (p) => (
                <span className="flex items-center gap-2"><Progress value={p.revenue_share_pct} className="h-1.5 w-20" />{angka(FMT_PCT(p.revenue_share_pct))}</span>) },
            ]} kosong={<EmptyState title={kosongPeriode} />} />
            {kpi.top_platform && <p className="text-sm text-muted-foreground">Platform teratas: <span className="text-foreground">{labelPlatform(kpi.top_platform)}</span></p>}
          </section>
          <section className="space-y-2">
            <div className="flex items-center gap-2">
              <p className="flex-1 text-base font-semibold">Omzet per hari</p>
              <TombolUnduh namaBerkas={`omzet-live-harian-${days}-hari`} baris={dailyTrend} testId="live-unduh-harian"
                kolom={[{ label: 'Tanggal', nilai: (d) => tgl(d.date) }, { label: 'Sesi', nilai: (d) => d.sessions },
                  { label: 'Pesanan', nilai: (d) => d.orders }, { label: 'Omzet', nilai: (d) => Number(d.revenue) || 0 }]} />
            </div>
            <TabelData baris={harian.paged} kunci={(r) => r.date} testId="live-daily" kolom={[
              { kunci: 'd', label: 'Tanggal', hp: 'judul', isi: (d) => <span className="tabular-nums">{tgl(d.date)}</span> },
              { kunci: 's', label: 'Sesi', rata: 'kanan', isi: (d) => angka(FMT_NUM(d.sessions)) },
              { kunci: 'o', label: 'Pesanan', rata: 'kanan', isi: (d) => angka(FMT_NUM(d.orders)) },
              { kunci: 'r', label: 'Omzet', rata: 'kanan', hp: 'nilai', isi: (d) => angka(FMT_IDR(d.revenue)) },
            ]} kosong={<EmptyState title={kosongPeriode} />} />
            {dailyTrend.length > 10 && <PaginationLite page={harian.page} totalPages={harian.totalPages} total={harian.total} onPageChange={harian.setPage} />}
            <p className="text-xs text-muted-foreground">Hanya hari yang ada sesinya, terbaru di atas.</p>
          </section>
        </div>
      )}

      {activeTab === 'sessions' && (
        <TabelData baris={sessions} testId="live-top-sessions" kolom={[
          { kunci: 'rank', label: '#', isi: (s) => <span className="tabular-nums text-muted-foreground">{s.rank}</span> },
          { kunci: 'tgl', label: 'Tanggal', hp: 'keterangan', isi: (s) => <span className="tabular-nums md:whitespace-nowrap">{tgl(s.session_date)}</span> },
          { kunci: 'host', label: 'Host', hp: 'judul', isi: (s) => (
            <span><span className="font-medium">{s.host_name || '—'}</span><span className="block text-xs text-muted-foreground">{s.account_name || labelPlatform(s.platform)}</span></span>) },
          { kunci: 'platform', label: 'Platform', isi: (s) => labelPlatform(s.platform) },
          { kunci: 'omzet', label: 'Omzet', rata: 'kanan', hp: 'nilai', isi: (s) => <span className="font-medium tabular-nums">{FMT_IDR(s.total_revenue)}</span> },
          { kunci: 'order', label: 'Pesanan', rata: 'kanan', isi: (s) => angka(FMT_NUM(s.orders_count)) },
          { kunci: 'view', label: 'Penonton puncak', rata: 'kanan', isi: (s) => angka(FMT_NUM(s.peak_viewers)) },
          { kunci: 'conv', label: 'Konversi', rata: 'kanan', isi: (s) => angka(FMT_PCT(s.conversion_rate)) },
          { kunci: 'vs', label: 'Dibanding rata-rata', rata: 'kanan', isi: (s) => <DeltaBadge pct={s.vs_avg_pct} /> },
        ]} kosong={<EmptyState title={kosongPeriode} />} />
      )}

      {activeTab === 'products' && (
        <section className="space-y-2" data-testid="panel-live-products">
          <p className="text-sm text-muted-foreground">
            Barang yang paling laku saat live — dari rincian produk per sesi, bukan taksiran.
            {products.data.length > 0 && <> {FMT_NUM(products.totals.products)} produk teratas: {FMT_NUM(products.totals.units_sold)} unit · {FMT_IDR(products.totals.revenue)}. Pangsa dihitung di antara produk di daftar ini.</>}
          </p>
          <TabelData baris={products.data} kunci={(r) => r.rank} testId="live-products-table" kolom={[
            { kunci: 'rank', label: '#', isi: (p) => <span className="tabular-nums text-muted-foreground">{p.rank}</span> },
            { kunci: 'nama', label: 'Produk', hp: 'judul', isi: (p) => (
              <span><span className="font-medium">{p.name || '—'}</span>
                <span className="block text-xs text-muted-foreground">{[p.sku, p.category, !accountId && p.account_name].filter(Boolean).join(' · ')}</span></span>) },
            { kunci: 'unit', label: 'Unit', rata: 'kanan', isi: (p) => angka(FMT_NUM(p.total_units_sold)) },
            { kunci: 'omzet', label: 'Omzet', rata: 'kanan', hp: 'nilai', isi: (p) => <span className="font-medium tabular-nums">{FMT_IDR(p.total_revenue)}</span> },
            { kunci: 'pangsa', label: 'Pangsa', isi: (p) => (
              <span className="flex items-center gap-2"><Progress value={Math.min(p.revenue_share_pct, 100)} className="h-1.5 w-14" />{angka(FMT_PCT(p.revenue_share_pct))}</span>) },
            { kunci: 'sesi', label: 'Sesi', rata: 'kanan', isi: (p) => angka(FMT_NUM(p.sessions_featured)) },
            { kunci: 'ups', label: 'Unit per sesi', rata: 'kanan', isi: (p) => angka(String(p.units_per_session ?? '—').replace('.', ',')) },
            { kunci: 'harga', label: 'Harga rata-rata', rata: 'kanan', isi: (p) => angka(FMT_IDR(p.avg_price)) },
            { kunci: 'margin', label: 'Margin kotor', rata: 'kanan', isi: (p) => (
              <span className={`tabular-nums ${(p.gross_margin || 0) < 0 ? 'text-[hsl(var(--danger-text))]' : ''}`}>{FMT_IDR(p.gross_margin)}</span>) },
          ]} kosong={<EmptyState icon={Package} title="Belum ada rincian produk" description={products.note || 'Belum ada rincian produk pada sesi live.'} />} />
        </section>
      )}

      {activeTab === 'leaderboard' && (
        <TabelData baris={leaderboard} kunci={(r) => r.host_name} testId="live-host-ranking" kolom={[
          { kunci: 'rank', label: 'Peringkat', isi: (h) => <span className="font-semibold tabular-nums">#{h.rank}</span> },
          { kunci: 'host', label: 'Host', hp: 'judul', isi: (h) => <span className="font-medium">{h.host_name}</span> },
          { kunci: 'sesi', label: 'Sesi', rata: 'kanan', hp: 'keterangan', isi: (h) => angka(`${FMT_NUM(h.total_sessions)} sesi`) },
          { kunci: 'omzet', label: 'Omzet', rata: 'kanan', hp: 'nilai', isi: (h) => <span className="font-medium tabular-nums">{FMT_IDR(h.total_revenue)}</span> },
          { kunci: 'avg', label: 'Rata-rata per sesi', rata: 'kanan', isi: (h) => angka(FMT_IDR(h.avg_revenue_per_session)) },
          { kunci: 'view', label: 'Rata-rata penonton puncak', rata: 'kanan', isi: (h) => angka(FMT_NUM(h.avg_viewers)) },
          { kunci: 'conv', label: 'Konversi', rata: 'kanan', isi: (h) => angka(FMT_PCT(h.avg_conversion_rate)) },
        ]} kosong={<EmptyState title={kosongPeriode} />} />
      )}

      {activeTab === 'trend' && (
        <section className="space-y-2">
          <p className="text-sm text-muted-foreground">Omzet per minggu. Tinggi batang = omzet minggu itu (arahkan kursor untuk angkanya); angka lengkap di tabel.</p>
          <MiniBarChart data={trend} valueKey="revenue" labelKey="period" labelFn={labelMinggu} />
          <TabelData baris={trend} kunci={(r) => r.period} testId="live-trend" kolom={[
            { kunci: 'p', label: 'Minggu', hp: 'judul', isi: (t) => labelMinggu(t.period) },
            { kunci: 'r', label: 'Omzet', rata: 'kanan', hp: 'nilai', isi: (t) => <span className="font-medium tabular-nums">{FMT_IDR(t.revenue)}</span> },
            { kunci: 's', label: 'Sesi', rata: 'kanan', isi: (t) => angka(FMT_NUM(t.sessions)) },
            { kunci: 'o', label: 'Pesanan', rata: 'kanan', isi: (t) => angka(FMT_NUM(t.orders)) },
            { kunci: 'a', label: 'Rata-rata per sesi', rata: 'kanan', isi: (t) => angka(FMT_IDR(t.avg_revenue_per_session)) },
          ]} kosong={<EmptyState title={kosongPeriode} />} />
        </section>
      )}

      {activeTab === 'health' && (
        <section className="space-y-2">
          <p className="text-sm text-muted-foreground">
            Skor 0–100 dibanding akun lain: 50 dari omzet, 30 dari konversi, 20 dari jumlah sesi.
          </p>
          <TabelData baris={accountHealth} kunci={(r) => `${r.account_name}-${r.platform}`} testId="live-account-health" kolom={[
            { kunci: 'akun', label: 'Akun toko', hp: 'judul', isi: (a) => <span className="font-medium">{a.account_name}</span> },
            { kunci: 'platform', label: 'Platform', hp: 'keterangan', isi: (a) => labelPlatform(a.platform) },
            { kunci: 'sesi', label: 'Sesi', rata: 'kanan', isi: (a) => angka(FMT_NUM(a.sessions)) },
            { kunci: 'omzet', label: 'Omzet', rata: 'kanan', hp: 'nilai', isi: (a) => angka(FMT_IDR(a.total_revenue)) },
            { kunci: 'conv', label: 'Konversi', rata: 'kanan', isi: (a) => angka(FMT_PCT(a.avg_conversion_rate)) },
            { kunci: 'skor', label: 'Skor', rata: 'kanan', isi: (a) => (
              <span className="inline-flex items-center gap-2"><span className="font-semibold tabular-nums">{a.health_score}</span>
                <StatusBadge tone={KESEHATAN[a.health_status]?.tone || 'muted'} label={KESEHATAN[a.health_status]?.label || a.health_status} /></span>) },
          ]} kosong={<EmptyState title={kosongPeriode} />} />
        </section>
      )}
    </PageLayout>
  );
}

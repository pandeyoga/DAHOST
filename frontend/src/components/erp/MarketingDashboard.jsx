/**
 * Dashboard Marketing (Portal Marketing, menu pertama).
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, kartu siklus & periode = StatTile berketerangan (target/anggaran/biaya 0
 * → "—" + alasan, dulu "0,0%" merah), skor kesehatan tanpa data = "—" (dulu "0 / 100" merah), 7 kartu toko berulang
 * (omzet/pesanan selalu "-") → tabel toko dengan omzet periode dari data tren yang sama + unduh, warna token.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { Store, RefreshCw, Plus, Eye } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { formatTanggalID } from '@/components/ui/date-picker';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatTile } from './moduleAtoms';
import { PeriodSelector } from './PeriodSelector';
import { RevenueChart } from './RevenueChart';
import { HealthScoreGauge } from './HealthScoreGauge';
import { AccountDetailPage } from './marketing/AccountDetailPage';
import { MarketingCycleStrip } from './marketing/MarketingCycleStrip';
import { toast } from 'sonner';
import { formatRupiah } from '@/lib/format';
import { todayWIB, monthStartWIB, bulanMarketingWIB, bulanMarketingDari } from '@/lib/waktu';

const API_BASE = process.env.REACT_APP_BACKEND_URL;
const PLATFORM_LABEL = { shopee: 'Shopee', tiktok: 'TikTok Shop', tiktokshop: 'TikTok Shop', tokopedia: 'Tokopedia', lazada: 'Lazada' };
const labelPlatform = (p) => PLATFORM_LABEL[String(p || '').toLowerCase()] || p || '—';

const fmt = formatRupiah;

export default function MarketingDashboard({ token, onNavigate }) {
  const [loading, setLoading] = useState(true);
  const [overview, setOverview] = useState(null);
  const [accounts, setAccounts] = useState([]);
  const [perAccountTrend, setPerAccountTrend] = useState({}); // { accountId: [{date,total,live}] }
  // FASE D (2026-08-16) — bawaan periode = BULAN BERJALAN, bukan kosong/30 hari.
  // Target, anggaran, dan ROI marketing semuanya BULANAN. Dengan bawaan lama
  // (30 hari terakhir dari backend) rentangnya selalu menyerempet dua bulan,
  // sehingga omzet di layar tidak pernah bisa disandingkan dengan targetnya —
  // dan itulah yang terbaca sebagai "angka dashboard tidak nyambung".
  const [period, setPeriod] = useState(() => ({
    date_from: monthStartWIB(),
    date_to: todayWIB(),
  }));
  const [chartAccountFilter, setChartAccountFilter] = useState('all');
  const [detailAccount, setDetailAccount] = useState(null); // null = dashboard, object = detail view
  const headers = useMemo(
    () => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }),
    [token]
  );
  // Bulan yang dipakai untuk angka RESMI (target/anggaran/ROI) — diambil dari
  // tanggal akhir rentang supaya layar dan SSOT siklus bicara tentang bulan sama.
  const cyclePeriod = useMemo(
    () => (period.date_to ? bulanMarketingDari(period.date_to) : bulanMarketingWIB()),   // bulan Marketing 26–25
    [period.date_to]
  );

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (period.date_from) params.append('date_from', period.date_from);
      if (period.date_to) params.append('date_to', period.date_to);

      const [overviewRes, accountsRes] = await Promise.all([
        fetch(`${API_BASE}/api/marketing/dashboard/overview?${params.toString()}`, { headers }),
        fetch(`${API_BASE}/api/marketing/accounts?status=active`, { headers }),
      ]);

      let overviewData = null;
      if (overviewRes.ok) {
        overviewData = await overviewRes.json();
        setOverview(overviewData);
      }
      const accs = accountsRes.ok ? await accountsRes.json() : [];
      setAccounts(accs);

      // Tren omzet per toko (semua toko aktif — dulu dipotong 10 toko pertama tanpa keterangan)
      const accTrendMap = {};
      for (const acc of accs) {
        const r = await fetch(
          `${API_BASE}/api/marketing/accounts/${acc.id}/sales?${params.toString()}`,
          { headers }
        );
        if (r.ok) {
          const list = await r.json();
          const map = {};
          list.forEach(item => {
            if (!map[item.date]) map[item.date] = { date: item.date, total: 0, live: 0 };
            const rev = item.metrics?.revenue || 0;
            if (item.revenue_type === 'live') map[item.date].live += rev;
            else map[item.date].total += rev;
          });
          accTrendMap[acc.id] = Object.values(map).sort((a, b) => a.date.localeCompare(b.date));
        }
      }
      setPerAccountTrend(accTrendMap);
    } catch (e) {
      toast.error('Gagal memuat dashboard');
    } finally {
      setLoading(false);
    }
  }, [period, headers]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Computed trend data berdasarkan filter akun
  const trendData = useMemo(() => {
    if (chartAccountFilter === 'all') {
      // Agregat semua akun
      const merged = {};
      Object.values(perAccountTrend).forEach(rows => {
        rows.forEach(row => {
          if (!merged[row.date]) merged[row.date] = { date: row.date, total: 0, live: 0 };
          merged[row.date].total += row.total;
          merged[row.date].live += row.live;
        });
      });
      return Object.values(merged).sort((a, b) => a.date.localeCompare(b.date));
    }
    return perAccountTrend[chartAccountFilter] || [];
  }, [perAccountTrend, chartAccountFilter]);

  // Average health score across active accounts — exclude null (N/A)
  const avgHealthScore = useMemo(() => {
    if (!accounts || accounts.length === 0) return null;
    const scored = accounts.filter(a => a.health_score !== null && a.health_score !== undefined);
    if (scored.length === 0) return null;
    const total = scored.reduce((sum, a) => sum + a.health_score, 0);
    return Math.round(total / scored.length);
  }, [accounts]);
  const adaSkor = (a) => a.health_score !== null && a.health_score !== undefined;
  const sebaran = {
    baik: accounts.filter(a => adaSkor(a) && a.health_score >= 80).length,
    cukup: accounts.filter(a => adaSkor(a) && a.health_score >= 60 && a.health_score < 80).length,
    buruk: accounts.filter(a => adaSkor(a) && a.health_score < 60).length,
    kosong: accounts.filter(a => !adaSkor(a)).length,
  };
  // Omzet per toko pada rentang terpilih = jumlah input harian (data yang sama dengan grafik tren)
  const omzetToko = (id) => (perAccountTrend[id] || []).reduce((s, r) => s + (r.total || 0), 0);
  const omzetLive = (id) => (perAccountTrend[id] || []).reduce((s, r) => s + (r.live || 0), 0);
  const sm = overview?.summary || {};
  const rentang = `${formatTanggalID(period.date_from)} – ${formatTanggalID(period.date_to)}`;

  const kolomToko = [
    { kunci: 'toko', label: 'Toko', hp: 'judul', isi: (a) => (
      <div data-testid={`account-card-${a.account_code}`}><p className="font-medium">{a.account_name}</p><p className="text-xs text-muted-foreground">{a.account_code}</p></div>) },
    { kunci: 'platform', label: 'Platform', hp: 'keterangan', isi: (a) => labelPlatform(a.platform) },
    { kunci: 'omzet', label: 'Omzet periode', rata: 'kanan', isi: (a) => <span className="tabular-nums md:whitespace-nowrap">{fmt(omzetToko(a.id))}</span> },
    { kunci: 'live', label: 'Omzet live', rata: 'kanan', isi: (a) => <span className="tabular-nums md:whitespace-nowrap">{fmt(omzetLive(a.id))}</span> },
    { kunci: 'skor', label: 'Skor kesehatan', rata: 'kanan', isi: (a) => (adaSkor(a)
      ? <span className={`font-semibold tabular-nums ${a.health_score >= 80 ? 'text-[hsl(var(--success-text))]' : a.health_score >= 60 ? 'text-[hsl(var(--warning-text))]' : 'text-[hsl(var(--danger-text))]'}`}>{a.health_score}</span>
      : <span className="text-muted-foreground">Belum ada</span>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (a) => (
      <Button size="sm" variant="outline" onClick={() => setDetailAccount(a)} data-testid={`view-dashboard-${a.account_code}`}>
        <Eye />Lihat detail
      </Button>) },
  ];

  // ── Rincian satu toko (halaman detail yang sudah ada) ──
  if (detailAccount) {
    return (
      <div data-testid="marketing-dashboard">
        <AccountDetailPage account={detailAccount} token={token} onBack={() => setDetailAccount(null)} onNavigate={onNavigate} />
      </div>
    );
  }

  return (
    <PageLayout testId="marketing-dashboard" title="Dashboard marketing"
      subtitle="Target, omzet, anggaran, dan kesehatan tiap toko — angka resmi bulanan dari siklus marketing."
      actions={<>
        <Button onClick={() => onNavigate?.('marketing-task-hub')} variant="outline" data-testid="quick-tasks">Buka tugas</Button>
        <Button onClick={() => onNavigate?.('marketing-sales')} data-testid="quick-input-sales"><Plus />Input sales</Button>
      </>}
      filters={<PeriodSelector value={period} onChange={setPeriod} />}
      tools={(
        <Button onClick={fetchData} variant="outline" size="icon" disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="refresh-dashboard-btn">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      )}>
      {/* Angka RESMI satu bulan — dijumlah backend (SSOT siklus marketing) */}
      <MarketingCycleStrip token={token} period={cyclePeriod} />

      <section className="space-y-2">
        <p className="text-base font-semibold">Periode terpilih · {rentang}</p>
        {loading && !overview ? (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[1, 2, 3, 4].map(i => <Skeleton key={i} className="h-20" />)}</div>
        ) : overview && (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile testId="kpi-total-revenue" label="Omzet" value={fmt(sm.total_revenue)}
              sub={`Termasuk live ${fmt(sm.total_revenue_live)} · dari input harian`} />
            <StatTile testId="kpi-total-orders" label="Pesanan" value={Number(sm.total_orders || 0).toLocaleString('id-ID')}
              sub={sm.total_orders ? `Rata-rata ${fmt(sm.avg_order_value)} per pesanan` : 'Belum ada pesanan di periode ini'} />
            <StatTile testId="kpi-active-accounts" label="Toko aktif" value={sm.active_accounts || 0}
              sub={`Dari ${sm.total_accounts || 0} toko`} />
            <StatTile testId="kpi-top-account" label="Toko terbaik"
              value={overview.top_account ? overview.top_account.account_name : '—'}
              sub={overview.top_account ? `Omzet ${fmt(overview.top_account.revenue)}` : 'Belum ada omzet di periode ini'} />
          </div>
        )}
      </section>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <GlassCard className="space-y-3 p-4 lg:col-span-2" data-testid="revenue-trend-card">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-base font-semibold">Tren omzet</p>
              <p className="text-sm text-muted-foreground">Omzet total dan live per hari, dari input harian tiap toko.</p>
            </div>
            <SmartNativeSelect className="w-48" value={chartAccountFilter} onChange={(e) => setChartAccountFilter(e.target.value)}
              data-testid="chart-account-filter">
              <option value="all">Semua toko</option>
              {accounts.map(a => <option key={a.id} value={a.id}>{a.account_name}</option>)}
            </SmartNativeSelect>
          </div>
          <RevenueChart data={trendData} height={260} />
        </GlassCard>

        <GlassCard className="space-y-3 p-4" data-testid="health-score-card">
          <div>
            <p className="text-base font-semibold">Rata-rata skor kesehatan</p>
            <p className="text-sm text-muted-foreground">
              {avgHealthScore == null ? 'Belum ada toko yang punya skor — skor dihitung dari data 30 hari terakhir.' : `Rata-rata ${accounts.length - sebaran.kosong} toko yang sudah punya skor.`}
            </p>
          </div>
          <HealthScoreGauge score={avgHealthScore} size={120} label="" />
          <dl className="space-y-1 text-sm">
            <div className="flex justify-between"><dt className="text-muted-foreground">Sangat baik (≥ 80)</dt><dd className="tabular-nums">{sebaran.baik}</dd></div>
            <div className="flex justify-between"><dt className="text-muted-foreground">Cukup (60–79)</dt><dd className="tabular-nums">{sebaran.cukup}</dd></div>
            <div className="flex justify-between"><dt className="text-muted-foreground">Perlu perbaikan (&lt; 60)</dt><dd className="tabular-nums">{sebaran.buruk}</dd></div>
            <div className="flex justify-between"><dt className="text-muted-foreground">Belum ada skor</dt><dd className="tabular-nums">{sebaran.kosong}</dd></div>
          </dl>
        </GlassCard>
      </div>

      <section className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="text-base font-semibold">Toko</p>
            <p className="text-sm text-muted-foreground">Klik baris untuk dashboard satu toko.</p>
          </div>
          <div className="flex items-center gap-2">
            <TombolUnduh namaBerkas={`dashboard-toko-${period.date_from}-${period.date_to}`} namaLembar="Toko" baris={accounts} testId="dashboard-toko-unduh"
              kolom={[
                { label: 'Toko', nilai: (a) => a.account_name }, { label: 'Kode', nilai: (a) => a.account_code },
                { label: 'Platform', nilai: (a) => labelPlatform(a.platform) },
                { label: 'Omzet periode', nilai: (a) => omzetToko(a.id) }, { label: 'Omzet live', nilai: (a) => omzetLive(a.id) },
                { label: 'Skor kesehatan', nilai: (a) => (adaSkor(a) ? a.health_score : '') },
              ]} />
            <Button variant="outline" onClick={() => onNavigate?.('marketing-accounts')} data-testid="manage-accounts-btn">Kelola akun</Button>
          </div>
        </div>
        <TabelData kolom={kolomToko} baris={accounts} onKlikBaris={setDetailAccount} testId="dashboard-accounts-table"
          kosong={<EmptyState icon={Store} title="Belum ada toko aktif"
            action={<Button onClick={() => onNavigate?.('marketing-accounts')} data-testid="add-first-account"><Plus />Tambah akun pertama</Button>} />} />
      </section>
    </PageLayout>
  );
}

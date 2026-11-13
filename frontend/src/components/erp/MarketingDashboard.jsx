/**
 * Dashboard Marketing (Portal Marketing, menu pertama).
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, kartu siklus & periode = StatTile berketerangan (target/anggaran/biaya 0
 * → "—" + alasan, dulu "0,0%" merah), skor kesehatan tanpa data = "—" (dulu "0 / 100" merah), 7 kartu toko berulang
 * (omzet/pesanan selalu "-") → tabel toko dengan omzet periode dari data tren yang sama + unduh, warna token.
 *
 * 14 Nov 2026 (owner: "grafik hanya sales saja padahal bisa ada ads, anggaran realisasi dll."):
 *   • grafik baru: iklan (biaya, omzet iklan, ROAS), anggaran vs realisasi per kategori, pencapaian target per toko,
 *     live selling, KOL/kreator — masing-masing dari endpoint layar sumbernya (lihat `marketing/DashboardGrafik.jsx`);
 *   • periode = bulan Marketing 26–25 / minggu Senin (PeriodSelector), saringan TOKO di baris penyaring berlaku untuk
 *     seluruh layar (dulu hanya untuk grafik tren);
 *   • tren omzet, kolom omzet/omzet live tabel toko, dan kartu periode kini dari SATU jawaban `/dashboard/overview`
 *     (dulu layar memanggil `/accounts/{id}/sales` per toko lalu menjumlah sendiri, dan "omzet live" diambil dari
 *     rekap jenis live — catatan kerja, bukan omzet live resmi — sehingga grafik ≠ kartu "Termasuk live").
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { Store, RefreshCw, Plus, Eye, TrendingUp } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { formatTanggalID } from '@/components/ui/date-picker';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatTile } from './moduleAtoms';
import { PeriodSelector, rentangPreset } from './PeriodSelector';
import { HealthScoreGauge } from './HealthScoreGauge';
import { AccountDetailPage } from './marketing/AccountDetailPage';
import { MarketingCycleStrip } from './marketing/MarketingCycleStrip';
import {
  BagianAnggaran, BagianGrafik, BagianIklan, BagianKreator, BagianLive, BagianTarget, KotakGrafik, useAmbilJson,
} from './marketing/DashboardGrafik';
import { CATATAN_KELOMPOK, klasifikasiPeriode, pesanGagal, rapikanHarian, spec } from './marketing/dashboardGrafikData';
import { toast } from 'sonner';
import { formatRupiah } from '@/lib/format';
import { todayWIB } from '@/lib/waktu';

const API_BASE = process.env.REACT_APP_BACKEND_URL;
const PLATFORM_LABEL = { shopee: 'Shopee', tiktok: 'TikTok Shop', tiktokshop: 'TikTok Shop', tokopedia: 'Tokopedia', lazada: 'Lazada' };
const labelPlatform = (p) => PLATFORM_LABEL[String(p || '').toLowerCase()] || p || '—';

const fmt = formatRupiah;

export default function MarketingDashboard({ token, onNavigate }) {
  const [loading, setLoading] = useState(true);
  const [overview, setOverview] = useState(null);
  const [overviewGalat, setOverviewGalat] = useState(null);
  const [accounts, setAccounts] = useState([]);
  // Bawaan = BULAN MARKETING berjalan (26–25, owner 11 Nov 2026) s/d hari ini — target, anggaran, dan siklus
  // marketing semuanya per bulan Marketing; dengan bawaan tanggal 1 kalender, kartu periode tidak pernah bisa
  // disandingkan dengan angka siklus bulan yang sama.
  const [period, setPeriod] = useState(() => rentangPreset('bulan'));
  const [tokoId, setTokoId] = useState('');                 // '' = semua toko
  const [muatUlang, setMuatUlang] = useState(0);
  const [detailAccount, setDetailAccount] = useState(null); // null = dashboard, object = detail view
  const headers = useMemo(
    () => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }),
    [token]
  );
  // Jenis periode (bulan Marketing / minggu Senin / rentang) + bulan Marketing untuk angka RESMI
  // (target/anggaran/KOL) = bulan tempat tanggal akhir rentang berada.
  const info = useMemo(() => klasifikasiPeriode(period, todayWIB()), [period]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (period.date_from) params.append('date_from', period.date_from);
      if (period.date_to) params.append('date_to', period.date_to);
      if (tokoId) params.append('account_id', tokoId);

      const [overviewRes, accountsRes] = await Promise.all([
        fetch(`${API_BASE}/api/marketing/dashboard/overview?${params.toString()}`, { headers }),
        fetch(`${API_BASE}/api/marketing/accounts?status=active`, { headers }),
      ]);
      if (overviewRes.ok) {
        setOverview(await overviewRes.json());
        setOverviewGalat(null);
      } else {
        const body = await overviewRes.json().catch(() => ({}));
        setOverview(null);
        setOverviewGalat({ status: overviewRes.status, detail: body?.detail });
      }
      setAccounts(accountsRes.ok ? await accountsRes.json() : []);
    } catch (e) {
      toast.error('Gagal memuat dashboard');
    } finally {
      setLoading(false);
    }
  }, [period, tokoId, headers]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Angka siklus RESMI satu bulan — satu permintaan untuk kartu siklus, grafik anggaran, dan grafik target.
  const siklus = useAmbilJson(
    `${API_BASE}/api/marketing/cycle/overview?period=${info.bulan}${tokoId ? `&account_id=${encodeURIComponent(tokoId)}` : ''}`,
    token, muatUlang);
  const siklusGalat = siklus.galat
    ? pesanGagal(siklus.galat.status, 'modul "Target & Anggaran" (Portal Manajemen)', siklus.galat.detail) : '';

  const muatSemua = () => { fetchData(); setMuatUlang((n) => n + 1); };

  // Toko yang ditampilkan mengikuti saringan toko
  const tokoTampil = useMemo(
    () => (tokoId ? accounts.filter((a) => a.id === tokoId) : accounts),
    [accounts, tokoId]
  );

  // Average health score across active accounts — exclude null (N/A)
  const avgHealthScore = useMemo(() => {
    if (!tokoTampil || tokoTampil.length === 0) return null;
    const scored = tokoTampil.filter(a => a.health_score !== null && a.health_score !== undefined);
    if (scored.length === 0) return null;
    const total = scored.reduce((sum, a) => sum + a.health_score, 0);
    return Math.round(total / scored.length);
  }, [tokoTampil]);
  const adaSkor = (a) => a.health_score !== null && a.health_score !== undefined;
  const sebaran = {
    baik: tokoTampil.filter(a => adaSkor(a) && a.health_score >= 80).length,
    cukup: tokoTampil.filter(a => adaSkor(a) && a.health_score >= 60 && a.health_score < 80).length,
    buruk: tokoTampil.filter(a => adaSkor(a) && a.health_score < 60).length,
    kosong: tokoTampil.filter(a => !adaSkor(a)).length,
  };
  // Omzet per toko = `per_account` jawaban yang sama dengan kartu & grafik tren (satu sumber)
  const perToko = useMemo(
    () => Object.fromEntries((overview?.per_account || []).map((r) => [r.account_id, r])),
    [overview]
  );
  const omzetToko = (id) => perToko[id]?.revenue || 0;
  const omzetLive = (id) => perToko[id]?.revenue_live || 0;
  const sm = overview?.summary || {};
  const rentang = `${formatTanggalID(period.date_from)} – ${formatTanggalID(period.date_to)}`;
  const tren = rapikanHarian(overview?.daily, ['revenue', 'revenue_live']);
  const specTren = spec('garis', tren.baris, [{ kunci: 'revenue', nama: 'Omzet total' }, { kunci: 'revenue_live', nama: 'Omzet live' }],
    { catatan: CATATAN_KELOMPOK[tren.satuan] });
  const ovState = { data: overview, galat: overviewGalat, loading };

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
      subtitle="Omzet, iklan, anggaran, target, live, dan kreator per toko dalam satu periode."
      actions={<>
        <Button onClick={() => onNavigate?.('marketing-task-hub')} variant="outline" data-testid="quick-tasks">Buka tugas</Button>
        <Button onClick={() => onNavigate?.('marketing-sales')} data-testid="quick-input-sales"><Plus />Input sales</Button>
      </>}
      filters={<>
        <PeriodSelector value={period} onChange={setPeriod} />
        <SmartNativeSelect className="w-48" value={tokoId} onChange={(e) => setTokoId(e.target.value)} aria-label="Toko"
          data-testid="dashboard-toko-filter">
          <option value="">Semua toko</option>
          {accounts.map(a => <option key={a.id} value={a.id}>{a.account_name}</option>)}
        </SmartNativeSelect>
      </>}
      tools={(
        <Button onClick={muatSemua} variant="outline" size="icon" disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="refresh-dashboard-btn">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      )}>
      {/* Angka RESMI satu bulan — dijumlah backend (SSOT siklus marketing) */}
      <MarketingCycleStrip token={token} period={info.bulan} data={siklus.loading ? null : siklus.data}
        error={siklusGalat} />

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
        <BagianGrafik className="lg:col-span-2" testId="revenue-trend-card" judul="Tren omzet"
          keterangan="Omzet total dan omzet live per hari — angka yang sama dengan kartu Omzet di atas.">
          <KotakGrafik testId="revenue-chart" spesifikasi={specTren} loading={loading && !overview}
            galat={overviewGalat ? pesanGagal(overviewGalat.status, 'modul "Dashboard & Laporan Marketing"', overviewGalat.detail) : ''}
            kosong={<EmptyState icon={TrendingUp} title="Belum ada omzet pada periode ini"
              description="Omzet terbaca dari impor pesanan atau Input sales harian."
              action={<Button variant="outline" onClick={() => onNavigate?.('marketing-sales')}>Buka input sales</Button>} />} />
        </BagianGrafik>

        <GlassCard className="space-y-3 p-4" data-testid="health-score-card">
          <div>
            <p className="text-base font-semibold">Rata-rata skor kesehatan</p>
            <p className="text-sm text-muted-foreground">
              {avgHealthScore == null ? 'Belum ada toko yang punya skor — skor dihitung dari data 30 hari terakhir.' : `Rata-rata ${tokoTampil.length - sebaran.kosong} toko yang sudah punya skor.`}
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

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <BagianIklan token={token} periode={period} tokoId={tokoId} muatUlang={muatUlang} onNavigate={onNavigate} />
        <BagianLive overview={ovState} onNavigate={onNavigate} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <BagianAnggaran token={token} info={info} tokoId={tokoId} siklus={siklus} muatUlang={muatUlang} onNavigate={onNavigate} />
        <BagianTarget info={info} siklus={siklus} onNavigate={onNavigate} />
      </div>

      <BagianKreator token={token} info={info} tokoId={tokoId} muatUlang={muatUlang} onNavigate={onNavigate} />

      <section className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="text-base font-semibold">Toko</p>
            <p className="text-sm text-muted-foreground">Klik baris untuk dashboard satu toko.</p>
          </div>
          <div className="flex items-center gap-2">
            <TombolUnduh namaBerkas={`dashboard-toko-${period.date_from}-${period.date_to}`} namaLembar="Toko" baris={tokoTampil} testId="dashboard-toko-unduh"
              kolom={[
                { label: 'Toko', nilai: (a) => a.account_name }, { label: 'Kode', nilai: (a) => a.account_code },
                { label: 'Platform', nilai: (a) => labelPlatform(a.platform) },
                { label: 'Omzet periode', nilai: (a) => omzetToko(a.id) }, { label: 'Omzet live', nilai: (a) => omzetLive(a.id) },
                { label: 'Skor kesehatan', nilai: (a) => (adaSkor(a) ? a.health_score : '') },
              ]} />
            <Button variant="outline" onClick={() => onNavigate?.('marketing-accounts')} data-testid="manage-accounts-btn">Kelola akun</Button>
          </div>
        </div>
        <TabelData kolom={kolomToko} baris={tokoTampil} onKlikBaris={setDetailAccount} testId="dashboard-accounts-table"
          kosong={<EmptyState icon={Store} title="Belum ada toko aktif"
            action={<Button onClick={() => onNavigate?.('marketing-accounts')} data-testid="add-first-account"><Plus />Tambah akun pertama</Button>} />} />
      </section>
    </PageLayout>
  );
}

/**
 * Performa penjualan (tab di Laporan Marketing; juga modul mandiri).
 * Standar UI/UX v2 (8 Nov 2026): PageLayout (di dalam hub judulnya otomatis disembunyikan), penyaring satu baris
 * dengan pemilih periode standar (dulu dua input tanggal bawaan peramban di panel samping), StatTile dengan rentang
 * tanggal yang benar-benar dipakai server (tanpa tanggal = 30 hari terakhir), tabel + unduh Excel/CSV.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Package, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { formatTanggalID } from '@/components/ui/date-picker';
import { useToast } from '@/hooks/use-toast';
import { useActiveMarketingAccount } from '@/hooks/useActiveMarketingAccount';
import PageLayout from '../layout/PageLayout';
import PeriodPicker, { PERIOD_PRESETS } from '../finance/PeriodPicker';
import { EmptyState, StatTile } from '../moduleAtoms';
import axios from 'axios';

const API = process.env.REACT_APP_BACKEND_URL;

function fmt(n) { return new Intl.NumberFormat('id-ID').format(n || 0); }
function fmtRp(n) { return `Rp ${fmt(n)}`; }
const PLATFORM_LABEL = { shopee: 'Shopee', tiktok: 'TikTok', tiktokshop: 'TikTok', tokopedia: 'Tokopedia', lazada: 'Lazada' };
const labelPlatform = (p) => PLATFORM_LABEL[String(p || '').toLowerCase()] || p || '—';
// Tanpa tanggal, server memakai 30 hari terakhir — pilihan bawaan diberi nama itu (bukan "semua waktu").
const BAWAAN_30 = { key: 'all', label: '30 hari terakhir' };

export default function SalesPerformanceDashboard({ token }) {
  const { toast } = useToast();
  const [overview, setOverview] = useState(null);
  const [topProducts, setTopProducts] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [overviewLoading, setOverviewLoading] = useState(true);
  
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [platformFilter, setPlatformFilter] = useState('');
  const [accountFilter, setAccountFilter] = useState('');
  const [daysFilter, setDaysFilter] = useState(30);
  const [periode, setPeriode] = useState({ preset: 'all', from: '', to: '' });
  const [meta, setMeta] = useState(null);

  // Sync dengan active account context
  const { activeAccount } = useActiveMarketingAccount();
  
  const authH = { Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` };

  // Fetch daftar akun untuk dropdown
  useEffect(() => {
    axios.get(`${API}/api/marketing/accounts?status=active`, { headers: authH })
      .then(r => setAccounts(Array.isArray(r.data) ? r.data : []))
      .catch(() => {});
  }, [token]); // eslint-disable-line

  // Jika ada active account dari context, pre-fill filter
  useEffect(() => {
    if (activeAccount && !accountFilter) {
      setAccountFilter(activeAccount.id);
    }
  }, [activeAccount]); // eslint-disable-line
  
  const fetchOverview = useCallback(async () => {
    setOverviewLoading(true);
    try {
      const params = {};
      // Kirim tanggal kalender apa adanya ('YYYY-MM-DD'). Dulu diubah jadi instan
      // tengah malam UTC → backend tidak mengenalinya sebagai "tanggal saja", sehingga
      // seluruh hari tanggal akhir ikut terbuang dari rentang.
      if (startDate) params.start_date = startDate;
      if (endDate) params.end_date = endDate;
      if (platformFilter) params.platform = platformFilter;
      if (accountFilter) params.account_id = accountFilter;
      const res = await axios.get(`${API}/api/marketing/performance/overview`, { params, headers: authH });
      if (res.data.success) {
        setOverview(res.data.data);
        setMeta(res.data.metadata || null);
      }
    } catch (e) {
      toast({ title: 'Gagal memuat performa penjualan', variant: 'destructive' });
    } finally {
      setOverviewLoading(false);
    }
  }, [startDate, endDate, platformFilter, accountFilter, token]); // eslint-disable-line
  
  const fetchTopProducts = useCallback(async () => {
    setLoading(true);
    try {
      const params = { days: daysFilter, limit: 10 };
      if (accountFilter) params.account_id = accountFilter;
      if (platformFilter) params.platform = platformFilter;
      const res = await axios.get(`${API}/api/marketing/performance/top-products`, {
        params,
        headers: authH
      });
      if (res.data.success) {
        setTopProducts(res.data.data.products || []);
      }
    } catch (e) {
      toast({ title: 'Gagal memuat produk terlaris', variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  }, [daysFilter, accountFilter, platformFilter, token]); // eslint-disable-line
  
  useEffect(() => { fetchOverview(); }, [fetchOverview]);
  useEffect(() => { fetchTopProducts(); }, [fetchTopProducts]);
  
  const rentang = meta?.start_date ? `${formatTanggalID(meta.start_date)} – ${formatTanggalID(meta.end_date)}` : '';
  const nilai = (v) => (overviewLoading && !overview ? '…' : v);
  const perPlatform = Object.entries(overview?.by_platform || {}).map(([platform, d]) => ({ platform, ...d }));

  return (
    <PageLayout testId="sales-dashboard" title="Performa penjualan"
      subtitle="Omzet, pesanan, dan produk terlaris dari semua platform."
      filters={<>
        <SmartNativeSelect className="w-48" value={accountFilter} onChange={(e) => setAccountFilter(e.target.value)}
          data-testid="account-filter-select">
          <option value="">Semua akun</option>
          {accounts.map(a => <option key={a.id} value={a.id}>{a.account_name}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect className="w-40" value={platformFilter} onChange={(e) => setPlatformFilter(e.target.value)}
          data-testid="platform-filter-select">
          <option value="">Semua platform</option>
          <option value="shopee">Shopee</option>
          <option value="tiktok">TikTok</option>
          <option value="tokopedia">Tokopedia</option>
        </SmartNativeSelect>
        <PeriodPicker value={periode} presets={[BAWAAN_30, ...PERIOD_PRESETS]} testId="sales-period"
          onChange={(v) => { setPeriode(v); setStartDate(v.from || ''); setEndDate(v.to || ''); }} />
      </>}
      tools={(
        <Button variant="outline" size="icon" onClick={() => { fetchOverview(); fetchTopProducts(); }}
          title="Muat ulang" aria-label="Muat ulang" data-testid="sales-refresh">
          <RefreshCw className={overviewLoading || loading ? 'animate-spin' : ''} />
        </Button>
      )}
      summary={(
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Omzet" value={nilai(fmtRp(overview?.total_revenue))}
            sub={`${overview?.revenue_label || 'Sebelum potongan platform'}${rentang ? ` · ${rentang}` : ''}`} />
          <StatTile label="Pesanan" value={nilai(fmt(overview?.total_orders))} sub={rentang || 'Periode terpilih'} />
          <StatTile label="Rata-rata per pesanan" value={nilai(overview?.total_orders ? fmtRp(overview?.aov) : '—')}
            sub={overview?.total_orders ? 'Omzet ÷ jumlah pesanan' : 'Belum ada pesanan di periode ini'} />
          <StatTile label="Barang terjual" value={nilai(fmt(overview?.total_items))} sub="Jumlah pcs di periode terpilih" />
        </div>
      )}>
      <section className="space-y-2" data-testid="sales-top-products">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-base font-semibold">10 produk terlaris</p>
          <div className="flex items-center gap-2">
            <SmartNativeSelect className="w-32" value={String(daysFilter)} onChange={(e) => setDaysFilter(Number(e.target.value))}
              searchable={false} data-testid="top-products-days">
              <option value="7">7 hari</option>
              <option value="30">30 hari</option>
              <option value="60">60 hari</option>
              <option value="90">90 hari</option>
            </SmartNativeSelect>
            <TombolUnduh namaBerkas="produk-terlaris" namaLembar="Produk terlaris" baris={topProducts} testId="top-products-unduh"
              kolom={[
                { label: 'Peringkat', nilai: (p) => topProducts.indexOf(p) + 1 }, { label: 'Produk', nilai: (p) => p.product_name },
                { label: 'Terjual (pcs)', nilai: (p) => Number(p.total_qty || 0) }, { label: 'Omzet', nilai: (p) => Number(p.total_revenue || 0) },
                { label: 'Pesanan', nilai: (p) => Number(p.order_count || 0) },
              ]} />
          </div>
        </div>
        {loading && topProducts.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">Memuat produk…</p>
        ) : (
          <TabelData baris={topProducts} kunci={(p) => `${p.product_name}-${p.total_qty}`} testId="top-products-table"
            kosong={<EmptyState icon={Package} title="Belum ada produk terjual" description={`Tidak ada penjualan dalam ${daysFilter} hari terakhir.`} />}
            kolom={[
              { kunci: 'no', label: '#', isi: (p) => <span className="text-muted-foreground">{topProducts.indexOf(p) + 1}</span> },
              { kunci: 'produk', label: 'Produk', hp: 'judul', isi: (p) => <span className="block max-w-[20rem] truncate font-medium" title={p.product_name}>{p.product_name}</span> },
              { kunci: 'qty', label: 'Terjual', rata: 'kanan', isi: (p) => <span className="tabular-nums font-semibold">{fmt(p.total_qty)}</span> },
              { kunci: 'omzet', label: 'Omzet', rata: 'kanan', isi: (p) => <span className="tabular-nums">{fmtRp(p.total_revenue)}</span> },
              { kunci: 'order', label: 'Pesanan', rata: 'kanan', isi: (p) => <span className="tabular-nums">{fmt(p.order_count)}</span> },
            ]} />
        )}
      </section>

      {perPlatform.length > 0 && (
        <section className="space-y-2" data-testid="sales-per-platform">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-base font-semibold">Per platform</p>
            <TombolUnduh namaBerkas="performa-per-platform" namaLembar="Per platform" baris={perPlatform} testId="sales-platform-unduh"
              kolom={[
                { label: 'Platform', nilai: (r) => labelPlatform(r.platform) },
                { label: 'Omzet', nilai: (r) => Number(r.revenue || 0) }, { label: 'Pesanan', nilai: (r) => Number(r.orders || 0) },
              ]} />
          </div>
          <TabelData baris={perPlatform} kunci={(r) => r.platform} testId="sales-platform-table"
            kolom={[
              { kunci: 'platform', label: 'Platform', hp: 'judul', isi: (r) => <span className="font-medium">{labelPlatform(r.platform)}</span> },
              { kunci: 'omzet', label: 'Omzet', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtRp(r.revenue)}</span> },
              { kunci: 'order', label: 'Pesanan', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmt(r.orders)}</span> },
            ]} />
        </section>
      )}
    </PageLayout>
  );
}

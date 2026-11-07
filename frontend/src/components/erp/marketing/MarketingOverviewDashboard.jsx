/**
 * Ringkasan marketing (tab pertama Laporan Marketing; juga modul mandiri).
 * Standar UI/UX v2 (8 Nov 2026): 6 kartu modul berwarna + panel duplikat → satu tabel "per modul" (angka sama,
 * tiap baris membuka modulnya), pintasan → menu, peringatan → tabel + unduh, tanpa emoji/gradien.
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { RefreshCw, AlertTriangle, CheckCircle2, ArrowRight, Bell, ChevronDown } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatusBadge } from '../moduleAtoms';
import { useToast } from '@/hooks/use-toast';
import axios from 'axios';
import NoStoreScopeNotice from './NoStoreScopeNotice';

const API = process.env.REACT_APP_BACKEND_URL;

function fmtRp(n) {
  if (!n || n === 0) return 'Rp 0';
  if (n >= 1e9)  return `Rp ${(n/1e9).toFixed(1)}M`;
  if (n >= 1e6)  return `Rp ${(n/1e6).toFixed(1)}jt`;
  if (n >= 1e3)  return `Rp ${(n/1e3).toFixed(0)}rb`;
  return `Rp ${n}`;
}
function fmt(n) {
  // Nilai yang BELUM diketahui harus tampil sebagai '—'. `format('—')` memberi
  // "NaN" di kartu KPI — pembacanya menyimpulkan aplikasinya rusak.
  const v = Number(n);
  return Number.isFinite(v) ? new Intl.NumberFormat('id-ID').format(v) : '—';
}

// Tingkat peringatan → label & warna StatusBadge
const TINGKAT = {
  error: { label: 'Penting', tone: 'danger' },
  warning: { label: 'Perhatian', tone: 'warning' },
  info: { label: 'Info', tone: 'info' },
  success: { label: 'Baik', tone: 'success' },
};

export default function MarketingOverviewDashboard({ token, onNavigate }) {
  const { toast } = useToast();
  const authH = useMemo(() => ({ Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` }), [token]);

  const [loading,    setLoading]    = useState(true);
  const [alertsData, setAlertsData] = useState([]);
  const [alertsLoading, setAlertsLoading] = useState(false);

  // Module summaries
  const [orders,    setOrders]    = useState(null);
  const [complaints,setComplaints]= useState(null);
  const [health,    setHealth]    = useState(null);
  const [discounts, setDiscounts] = useState(null);
  const [launches,  setLaunches]  = useState(null);
  const [content,   setContent]   = useState(null);

  const nav = (moduleId) => { if (onNavigate) onNavigate(moduleId); };

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [r1, r2, r3, r4, r5, r6] = await Promise.allSettled([
        axios.get(`${API}/api/marketing/orders/summary`,      { headers: authH }),
        axios.get(`${API}/api/marketing/complaints/summary`,  { headers: authH }),
        axios.get(`${API}/api/marketing/health/summary`,      { headers: authH }),  // correct route
        axios.get(`${API}/api/marketing/discounts/summary`,   { headers: authH }),
        axios.get(`${API}/api/marketing/product-launches/summary`, { headers: authH }),
        axios.get(`${API}/api/marketing/content-calendar/summary`, { headers: authH }),
      ]);
      // Orders: flat response
      if (r1.status==='fulfilled') setOrders(r1.value.data);
      // Complaints: flat response
      if (r2.status==='fulfilled') setComplaints(r2.value.data);
      // Health: has data key
      if (r3.status==='fulfilled' && r3.value.data.success) setHealth(r3.value.data.data);
      // Discounts: has data key
      if (r4.status==='fulfilled' && r4.value.data.success) setDiscounts(r4.value.data.data);
      // Launches: has data key
      if (r5.status==='fulfilled' && r5.value.data.success) setLaunches(r5.value.data.data);
      // Content: has data key
      if (r6.status==='fulfilled' && r6.value.data.success) setContent(r6.value.data.data);
    } catch {}
    finally { setLoading(false); }
  }, [authH]);

  const fetchAlerts = useCallback(async () => {
    setAlertsLoading(true);
    try {
      const res = await axios.post(`${API}/api/marketing/alerts/preview`, {}, { headers: authH });
      if (res.data.success) setAlertsData(res.data.fired || []);
    } catch {}
    finally { setAlertsLoading(false); }
  }, [authH]);

  const triggerAlerts = async () => {
    try {
      const res = await axios.post(`${API}/api/marketing/alerts/evaluate`, {}, { headers: authH });
      toast({ title: `${res.data.total_fired} peringatan dikirim` });
      fetchAlerts();
    } catch { toast({ title: 'Gagal menjalankan pemeriksaan peringatan', variant: 'destructive' }); }
  };

  useEffect(() => { fetchAll(); fetchAlerts(); }, [fetchAll, fetchAlerts]);

  // Highlight counts for top banner
  const urgentCount = (
    (complaints?.overdue || 0) +
    (discounts?.expiring_soon || 0) +
    (launches?.ready || 0)
  );

  const urgentBannerParts = [
    complaints?.overdue > 0 && `${complaints.overdue} komplain lewat batas`,
    discounts?.expiring_soon > 0 && `${discounts.expiring_soon} kampanye akan habis`,
    launches?.ready > 0 && `${launches.ready} produk siap diluncurkan`,
  ].filter(Boolean);

  const rows = [
    {
      key: 'orders', modul: 'Pesanan', module: 'marketing-orders', total: orders?.total_orders,
      rincian: [['Perlu tindakan', fmt(orders?.need_action ?? '—'), (orders?.need_action || 0) > 0 ? 'warning' : ''],
        ['Aktif (baru + dikemas + dikirim)', fmt(orders ? (orders.by_status?.new || 0) + (orders.by_status?.packed || 0) + (orders.by_status?.shipped || 0) : '—')],
        ['Terkirim', fmt(orders?.by_status?.delivered ?? (orders ? 0 : '—'))],
        ['Omzet semua waktu', orders?.total_revenue ? fmtRp(orders.total_revenue) : (orders ? 'Rp 0' : '—')]],
      pintasan: 'Daftar ambil barang',
    },
    {
      key: 'complaints', modul: 'Komplain', module: 'marketing-complaints', total: complaints?.total,
      rincian: [['Terbuka', fmt(complaints?.by_status?.open ?? (complaints ? 0 : '—')), (complaints?.by_status?.open || 0) > 0 ? 'warning' : ''],
        ['Lewat batas', fmt(complaints?.overdue ?? '—'), (complaints?.overdue || 0) > 0 ? 'danger' : ''],
        ['Selesai', fmt(complaints?.resolved ?? '—')]],
      pintasan: 'Tambah komplain',
    },
    {
      key: 'health', modul: 'Kesehatan akun', module: 'marketing-health', total: health?.total_accounts,
      rincian: [['Sehat', fmt(health?.healthy ?? '—')], ['Perlu perhatian', fmt(health?.warning ?? '—'), (health?.warning || 0) > 0 ? 'warning' : ''],
        ['Kritis', fmt(health?.critical ?? '—'), (health?.critical || 0) > 0 ? 'danger' : '']],
    },
    {
      key: 'discounts', modul: 'Kampanye diskon', module: 'marketing-discounts', total: discounts?.total,
      rincian: [['Aktif', fmt(discounts?.active ?? '—')], ['Akan datang', fmt(discounts?.upcoming ?? '—')],
        ['Habis dalam 3 hari', fmt(discounts?.expiring_soon ?? '—'), (discounts?.expiring_soon || 0) > 0 ? 'warning' : '']],
      pintasan: 'Buat kampanye',
    },
    {
      key: 'launches', modul: 'Peluncuran produk', module: 'marketing-product-launches', total: launches?.total,
      rincian: [['Perencanaan', fmt(launches?.planning ?? '—')], ['Siap diluncurkan', fmt(launches?.ready ?? '—')],
        ['Sudah diluncurkan', fmt(launches?.launched ?? '—')], ['30 hari ke depan', fmt(launches?.upcoming_30 ?? '—')]],
      pintasan: 'Tambah produk',
    },
    {
      key: 'content', modul: 'Kalender konten', module: 'marketing-content-calendar', total: content?.total,
      rincian: [['Draf', fmt(content?.draft ?? '—')], ['Terjadwal', fmt(content?.scheduled ?? '—')], ['Tayang', fmt(content?.posted ?? '—')]],
      pintasan: 'Tambah konten hari ini',
    },
  ];
  const warna = { warning: 'text-[hsl(var(--warning-text))]', danger: 'text-[hsl(var(--danger-text))]' };

  const kolom = [
    { kunci: 'modul', label: 'Modul', hp: 'judul', isi: (r) => <span className="font-medium">{r.modul}</span> },
    { kunci: 'total', label: 'Total', rata: 'kanan', isi: (r) => <span className="tabular-nums font-semibold">{fmt(r.total ?? '—')}</span> },
    { kunci: 'rincian', label: 'Rincian', isi: (r) => (
      <p className="text-sm text-muted-foreground">
        {r.rincian.map(([l, v, t], i) => (
          <span key={l}>{i > 0 && ' · '}{l} <b className={warna[t] || 'text-foreground'}>{v}</b></span>
        ))}
      </p>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <Button size="sm" variant="outline" onClick={() => nav(r.module)} data-testid={`overview-open-${r.key}`}>
        Buka<ArrowRight />
      </Button>) },
  ];

  return (
    <PageLayout testId="marketing-overview-dashboard" title="Ringkasan marketing"
      subtitle="Angka utama semua modul Portal Marketing dan peringatan yang aktif."
      actions={<>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" data-testid="overview-shortcuts">Pintasan<ChevronDown /></Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-60">
            <DropdownMenuItem onSelect={() => nav('marketing-content-calendar')}>Tambah konten hari ini</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => nav('marketing-discounts')}>Buat kampanye diskon</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => nav('marketing-product-launches')}>Tambah produk peluncuran</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => nav('marketing-complaints')}>Cek komplain lewat batas</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => nav('marketing-performance')}>Performa penjualan</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => nav('marketing-import')}>Impor data baru</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => nav('marketing-orders')}>Daftar ambil barang</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <Button variant="outline" onClick={triggerAlerts} data-testid="overview-check-alerts"><Bell />Cek peringatan</Button>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="ringkasan-marketing" namaLembar="Ringkasan" baris={rows} testId="overview-unduh"
          kolom={[
            { label: 'Modul', nilai: (r) => r.modul }, { label: 'Total', nilai: (r) => (r.total ?? '') },
            { label: 'Rincian', nilai: (r) => r.rincian.map(([l, v]) => `${l} ${v}`).join(' · ') },
          ]} />
        <Button variant="outline" size="icon" onClick={() => { fetchAll(); fetchAlerts(); }} disabled={loading}
          title="Muat ulang" aria-label="Muat ulang" data-testid="overview-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}>
      {/* Staf berlingkup toko yang belum di-assign: nol yang MENJELASKAN dirinya */}
      <NoStoreScopeNotice token={token} what="Semua angka di ringkasan ini" />

      {urgentCount > 0 && (
        <p className="flex items-start gap-1.5 text-sm text-[hsl(var(--warning-text))]" data-testid="overview-urgent">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span><b>{urgentCount} hal perlu perhatian segera:</b> {urgentBannerParts.join(' · ')}.</span>
        </p>
      )}

      {loading && !orders ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat ringkasan…</p>
      ) : (
        <TabelData kolom={kolom} baris={rows} kunci={(r) => r.key} onKlikBaris={(r) => nav(r.module)} testId="overview-modules" />
      )}

      <section className="space-y-2" data-testid="overview-alerts">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-base font-semibold">Peringatan aktif{alertsData.length ? ` (${alertsData.length})` : ''}</p>
          <div className="flex items-center gap-2">
            <TombolUnduh namaBerkas="peringatan-marketing" namaLembar="Peringatan" baris={alertsData} testId="overview-alerts-unduh"
              kolom={[
                { label: 'Tingkat', nilai: (a) => (TINGKAT[a.severity] || TINGKAT.info).label },
                { label: 'Judul', nilai: (a) => a.title || '' }, { label: 'Pesan', nilai: (a) => a.message || '' },
              ]} />
            <Button variant="outline" size="icon" onClick={fetchAlerts} disabled={alertsLoading} title="Muat ulang peringatan"
              aria-label="Muat ulang peringatan">
              <RefreshCw className={alertsLoading ? 'animate-spin' : ''} />
            </Button>
          </div>
        </div>
        {alertsLoading && alertsData.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">Memuat peringatan…</p>
        ) : (
          <TabelData baris={alertsData} kunci={(a) => `${a.title}-${a.message}`} testId="overview-alerts-table"
            kosong={<EmptyState icon={CheckCircle2} title="Semua kondisi normal" description="Tidak ada peringatan aktif." />}
            kolom={[
              { kunci: 'tingkat', label: 'Tingkat', isi: (a) => {
                const t = TINGKAT[a.severity] || TINGKAT.info;
                return <StatusBadge status={a.severity} label={t.label} tone={t.tone} />;
              } },
              { kunci: 'judul', label: 'Peringatan', hp: 'judul', isi: (a) => (
                <div className="max-w-[36rem]"><p className="font-medium">{a.title}</p><p className="text-xs text-muted-foreground">{a.message}</p></div>) },
              { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (a) => (a.link_module
                ? <Button size="sm" variant="link" onClick={() => nav(a.link_module)}>Lihat<ArrowRight /></Button> : null) },
            ]} />
        )}
      </section>
    </PageLayout>
  );
}

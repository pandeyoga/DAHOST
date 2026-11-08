/**
 * AccessoriesReports — Portal Aksesoris › Laporan.
 *
 * Bagian: Stok · Pemakaian · Biaya (PanelTabs standar di baris penyaring; satu cetakan PageLayout).
 * Stok memakai /api/acc/items. Pemakaian & Biaya belum tersedia di server — ditampilkan apa adanya
 * (dulu berjudul "Coming Soon").
 *
 * Standar UI/UX v2 (8 Nov 2026): penyaring satu baris, tabel standar (kartu ringkas di HP), unduh Excel/CSV.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { AlertTriangle, BarChart3, Package, RefreshCw, Search, Wallet } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import PanelTabs from '@/components/ui/panel-tabs';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL || '';
const fmtNum = (n) => Number(n || 0).toLocaleString('id-ID');

const STATUS = {
  habis: { label: 'Habis', tone: 'danger' },
  menipis: { label: 'Menipis', tone: 'warning' },
  aman: { label: 'Aman', tone: 'success' },
};
const statusItem = (i) => {
  const qty = i.stock_qty ?? 0;
  const min = i.min_stock ?? 0;
  return qty <= 0 ? 'habis' : (min > 0 && qty <= min) ? 'menipis' : 'aman';
};

// ── Tab Stok (memakai /api/acc/items) ────────────────────────────────────────
function StockLevelTab({ token, tabs }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all');

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError('');
    try {
      const r = await fetch(`${API}/api/acc/items`, { headers: { Authorization: `Bearer ${token}` } });
      if (!r.ok) throw new Error(`Daftar stok gagal dimuat (kode ${r.status}).`);
      const data = await r.json();
      setItems(Array.isArray(data) ? data : []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => items.filter((i) => {
    const q = search.toLowerCase();
    const matchSearch = !search || i.name?.toLowerCase().includes(q) || i.code?.toLowerCase().includes(q);
    const st = statusItem(i);
    const matchFilter = filter === 'all' ? true : filter === 'low' ? st === 'menipis' : filter === 'out' ? st === 'habis' : true;
    return matchSearch && matchFilter;
  }), [items, search, filter]);

  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(filtered, 25);
  const kolom = [
    { kunci: 'code', label: 'Kode', hp: 'keterangan', isi: (i) => <span className="tabular-nums text-muted-foreground">{i.code || '—'}</span> },
    { kunci: 'name', label: 'Nama item', hp: 'judul', isi: (i) => <span className="font-medium text-foreground">{i.name}</span> },
    { kunci: 'category', label: 'Kategori', isi: (i) => <span className="text-muted-foreground">{i.category || '—'}</span> },
    { kunci: 'stock', label: 'Stok saat ini', rata: 'kanan', isi: (i) => <span className="font-semibold tabular-nums whitespace-nowrap">{fmtNum(i.stock_qty ?? 0)} {i.unit}</span> },
    { kunci: 'min', label: 'Min. stok', rata: 'kanan', isi: (i) => <span className="tabular-nums text-muted-foreground">{fmtNum(i.min_stock ?? 0)}</span> },
    { kunci: 'status', label: 'Status', isi: (i) => { const s = STATUS[statusItem(i)]; return <StatusBadge status={statusItem(i)} label={s.label} tone={s.tone} />; } },
  ];

  return (
    <PageLayout testId="acc-reports-stock" title="Laporan"
      subtitle="Laporan stok, pemakaian, dan biaya aksesoris."
      filters={<>
        {tabs}
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder="Cari nama atau kode" value={search} onChange={(e) => setSearch(e.target.value)}
            className="pl-8" data-testid="acc-reports-search" />
        </div>
        <SmartNativeSelect value={filter} onChange={(e) => setFilter(e.target.value)} searchable={false}
          className="h-9 w-48" wrapperClassName="w-48" aria-label="Status stok" data-testid="acc-reports-status">
          <option value="all">Semua status</option>
          <option value="low">Stok menipis</option>
          <option value="out">Stok habis</option>
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="laporan-stok-aksesoris" namaLembar="Stok" baris={filtered} testId="acc-reports-unduh"
          kolom={[
            { label: 'Kode', nilai: (i) => i.code || '' }, { label: 'Nama item', nilai: (i) => i.name || '' },
            { label: 'Kategori', nilai: (i) => i.category || '' }, { label: 'Stok saat ini', nilai: (i) => Number(i.stock_qty ?? 0) },
            { label: 'Satuan', nilai: (i) => i.unit || '' }, { label: 'Min. stok', nilai: (i) => Number(i.min_stock ?? 0) },
            { label: 'Status', nilai: (i) => STATUS[statusItem(i)].label },
          ]} />
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={<>
        {error && <Notice tone="danger" icon={AlertTriangle}>{error}</Notice>}
        {!loading && items.length > 0 && (
          <p className="text-sm text-muted-foreground" data-testid="acc-reports-ringkas">
            {fmtNum(filtered.length)} item ditampilkan dari {fmtNum(items.length)} item aktif.
          </p>
        )}
      </>}
      footer={filtered.length > pageSize && (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />
      )}>
      {loading ? (
        <div className="space-y-2">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
      ) : (
        <TabelData kolom={kolom} baris={paged} testId="acc-reports-table"
          kosong={<EmptyState icon={Package} title={items.length ? 'Tidak ada item yang cocok' : 'Tidak ada item aksesoris'}
            description={items.length ? 'Ubah saringan atau kata pencarian.' : 'Tambahkan item di menu Master Aksesoris.'} />} />
      )}
    </PageLayout>
  );
}

// ── Tab yang belum tersedia ──────────────────────────────────────────────────
function UsageTab({ tabs }) {
  return (
    <PageLayout testId="acc-reports-usage" title="Laporan" subtitle="Laporan stok, pemakaian, dan biaya aksesoris." filters={tabs}>
      <EmptyState icon={BarChart3} title="Laporan pemakaian belum tersedia"
        description="Nantinya berisi rekap pemakaian aksesoris per periode, divisi, dan item." />
    </PageLayout>
  );
}

function CostTab({ tabs }) {
  return (
    <PageLayout testId="acc-reports-cost" title="Laporan" subtitle="Laporan stok, pemakaian, dan biaya aksesoris." filters={tabs}>
      <EmptyState icon={Wallet} title="Analisis biaya belum tersedia"
        description="Nantinya berisi biaya aksesoris, termasuk HPP per unit produksi." />
    </PageLayout>
  );
}

const TABS = [
  { key: 'stock', label: 'Stok', Component: StockLevelTab },
  { key: 'usage', label: 'Pemakaian', Component: UsageTab },
  { key: 'cost', label: 'Biaya', Component: CostTab },
];

export default function AccessoriesReports({ token }) {
  const [tab, setTab] = useState('stock');
  const aktif = TABS.find((t) => t.key === tab) || TABS[0];
  const Isi = aktif.Component;
  const tabs = <PanelTabs tabs={TABS} value={tab} onChange={setTab} testId="acc-reports-tab" ariaLabel="Jenis laporan" />;
  return (
    <div data-testid="accessories-reports">
      <Isi token={token} tabs={tabs} />
    </div>
  );
}

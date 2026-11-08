/**
 * AccessoriesDashboard — Portal Aksesoris › Dashboard.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, 4 kartu angka (StatTile) yang sumbernya sama dengan
 * daftar, daftar stok = tabel (kartu ringkas di HP) yang bisa diurutkan, disaring, dan diunduh (Excel/CSV).
 *
 * Perbaikan angka (keputusan 9):
 *  • Panel lama "Item stok rendah / habis" membaca `low_stock_items` dari server — isinya hanya item MENIPIS
 *    (stok > 0) dan paling banyak 5, sehingga layar menulis "Semua item stok aman" walau 324 item habis.
 *    Panel itu diganti saringan "Habis" / "Menipis" di tabel yang membaca daftar stok lengkap.
 *  • Panel "Ringkasan pengadaan" mengulang angka kartu — angkanya kini di keterangan kartu.
 *  • Spanduk "n item belum punya HPP" → kartu "Belum dinilai" yang membuka saringannya (konten utama naik ke atas).
 *
 * Endpoint: GET /api/acc/dashboard (kartu) · GET /api/acc/stock (daftar).
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { AlertTriangle, ArrowUpDown, ClipboardCheck, Package, RefreshCw, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import ViewToggle from '@/components/ui/view-toggle';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { Skeleton } from '@/components/ui/skeleton';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { cn } from '@/lib/utils';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';

const ACC_VIEW_KEY = 'acc_stock_view';
const API = process.env.REACT_APP_BACKEND_URL || '';

const fmtNum = (n) => Number(n || 0).toLocaleString('id-ID');
const fmtRp = (n) => `Rp ${Number(n || 0).toLocaleString('id-ID')}`;

// Metode biaya ditampilkan dengan bahasa staf (dulu tampil kode program "moving_average").
const METODE_BIAYA = { moving_average: 'Rata-rata bergerak', manual: 'Manual' };
const labelMetode = (m) => METODE_BIAYA[m] || (m ? m : '—');

// Status stok — definisi sama dengan server (/api/acc/stock: out / low / ok).
const STATUS_STOK = {
  habis: { label: 'Habis', tone: 'danger' },
  menipis: { label: 'Menipis', tone: 'warning' },
  aman: { label: 'Aman', tone: 'success' },
};
function statusStok(it) {
  const q = Number(it.stock_qty || 0);
  const min = Number(it.min_stock || 0);
  if (q <= 0) return 'habis';
  if (min > 0 && q <= min) return 'menipis';
  return 'aman';
}

function KepalaUrut({ kunci, urut, onUrut, children }) {
  const aktif = urut.key === kunci;
  return (
    <Button type="button" variant="ghost" size="sm" onClick={() => onUrut(kunci)} data-testid={`acc-sort-${kunci}`}
      title="Urutkan" className="-ml-2 h-7 gap-1 px-2 text-xs font-medium text-muted-foreground">
      {children}
      <ArrowUpDown className={cn('!size-3', aktif ? 'text-primary' : 'opacity-40')} aria-hidden="true" />
    </Button>
  );
}

export default function AccessoriesDashboard({ token }) {
  const [dash, setDash] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  // F13-B: daftar stok lengkap — "aksesoris mana yang nilainya paling besar / belum dinilai?"
  const [stock, setStock] = useState([]);
  const [stockErr, setStockErr] = useState('');
  const [stockLoading, setStockLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [saring, setSaring] = useState('');
  const [view, setView] = useState(() => {
    try { return localStorage.getItem(ACC_VIEW_KEY) || 'table'; } catch { return 'table'; }
  });
  useEffect(() => {
    try { localStorage.setItem(ACC_VIEW_KEY, view); } catch { /* penyimpanan diblokir */ }
  }, [view]);
  const [sort, setSort] = useState({ key: 'stock_value', dir: 'desc' });
  const [rinci, setRinci] = useState(null);   // baris yang dibuka di popup rincian

  const loadDash = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError('');
    try {
      const r = await fetch(`${API}/api/acc/dashboard`, { headers: { Authorization: `Bearer ${token}` } });
      if (!r.ok) throw new Error(`Ringkasan gagal dimuat (kode ${r.status}).`);
      setDash(await r.json());
    } catch (e) {
      setError(e.message || 'Ringkasan gagal dimuat.');
    } finally {
      setLoading(false);
    }
  }, [token]);

  const loadStock = useCallback(async () => {
    if (!token) return;
    setStockErr('');
    setStockLoading(true);
    try {
      const r = await fetch(`${API}/api/acc/stock`, { headers: { Authorization: `Bearer ${token}` } });
      if (!r.ok) throw new Error(`Daftar stok gagal dimuat (kode ${r.status}).`);
      const d = await r.json();
      setStock(Array.isArray(d) ? d : (d.items || []));
    } catch (e) {
      setStock([]);
      setStockErr(e.message || 'Daftar stok gagal dimuat.');
    } finally {
      setStockLoading(false);
    }
  }, [token]);

  useEffect(() => { loadDash(); }, [loadDash]);
  useEffect(() => { loadStock(); }, [loadStock]);
  const muatUlang = () => { loadDash(); loadStock(); };

  const hitung = useMemo(() => {
    const c = { habis: 0, menipis: 0, aman: 0, belum: 0 };
    stock.forEach((it) => { c[statusStok(it)] += 1; if (!it.valued) c.belum += 1; });
    return c;
  }, [stock]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return stock.filter((it) => {
      if (saring === 'belum' ? it.valued : (saring && statusStok(it) !== saring)) return false;
      if (!q) return true;
      return String(it.code || '').toLowerCase().includes(q)
        || String(it.name || '').toLowerCase().includes(q)
        || String(it.category || '').toLowerCase().includes(q);
    });
  }, [stock, search, saring]);

  const rows = useMemo(() => {
    const list = [...filtered];
    const { key, dir } = sort;
    list.sort((a, b) => {
      const av = a?.[key];
      const bv = b?.[key];
      const num = typeof av === 'number' || typeof bv === 'number';
      const cmp = num ? (Number(av || 0) - Number(bv || 0)) : String(av ?? '').localeCompare(String(bv ?? ''), 'id');
      return dir === 'asc' ? cmp : -cmp;
    });
    return list;
  }, [filtered, sort]);
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(rows, 25);
  const toggleSort = (key) => setSort((s) => (s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'desc' }));

  const H = (kunci, label) => <KepalaUrut kunci={kunci} urut={sort} onUrut={toggleSort}>{label}</KepalaUrut>;
  const kolom = [
    { kunci: 'code', label: H('code', 'Kode'), hp: 'keterangan', isi: (it) => <span className="tabular-nums whitespace-nowrap">{it.code}</span> },
    { kunci: 'name', label: H('name', 'Nama'), hp: 'judul', isi: (it) => <span className="font-medium text-foreground">{it.name}</span> },
    { kunci: 'category', label: H('category', 'Kategori'), hp: false, isi: (it) => <span className="text-muted-foreground">{it.category || '—'}</span> },
    { kunci: 'stock_qty', label: H('stock_qty', 'Stok'), rata: 'kanan', isi: (it) => {
      const st = statusStok(it);
      return (
        <span className={cn('tabular-nums font-semibold whitespace-nowrap',
          st === 'habis' && 'text-[hsl(var(--danger-text))]', st === 'menipis' && 'text-[hsl(var(--warning-text))]')}>
          {fmtNum(it.stock_qty)} <span className="font-normal text-muted-foreground">{it.unit}</span>
        </span>
      );
    } },
    { kunci: 'min_stock', label: H('min_stock', 'Min. stok'), rata: 'kanan', hp: false, isi: (it) => <span className="tabular-nums text-muted-foreground">{fmtNum(it.min_stock)}</span> },
    { kunci: 'unit_cost', label: H('unit_cost', 'HPP satuan'), rata: 'kanan', hp: false, isi: (it) => <span className="tabular-nums whitespace-nowrap">{fmtRp(it.unit_cost)}</span> },
    { kunci: 'stock_value', label: H('stock_value', 'Nilai stok'), rata: 'kanan', isi: (it) => <span className="tabular-nums font-semibold whitespace-nowrap">{fmtRp(it.stock_value)}</span> },
    { kunci: 'valued', label: H('valued', 'Dinilai'), isi: (it) => (it.valued
      ? <StatusBadge status="ya" label="Sudah" tone="success" />
      : <StatusBadge status="belum" label="Belum" tone="warning" />) },
  ];

  const opsiSaring = [
    { key: '', label: 'Semua', count: stock.length },
    { key: 'habis', label: 'Habis', count: hitung.habis },
    { key: 'menipis', label: 'Menipis', count: hitung.menipis },
    { key: 'aman', label: 'Aman', count: hitung.aman },
    { key: 'belum', label: 'Belum dinilai', count: hitung.belum },
  ];

  return (
    <PageLayout testId="accessories-dashboard" title="Dashboard aksesoris"
      subtitle="Ringkasan stok aksesoris, permintaan yang menunggu, dan barang yang perlu diserahkan."
      filters={<>
        <FilterChips options={opsiSaring} value={saring} onChange={setSaring} hideWhenEmpty={false} testId="acc-stock-filter" />
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari kode, nama, kategori"
            className="pl-8" data-testid="acc-stock-search" />
        </div>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="stok-aksesoris" namaLembar="Stok aksesoris" baris={rows} testId="acc-export"
          kolom={[
            { label: 'Kode', nilai: (it) => it.code },
            { label: 'Nama', nilai: (it) => it.name },
            { label: 'Kategori', nilai: (it) => it.category || '' },
            { label: 'Satuan', nilai: (it) => it.unit || '' },
            { label: 'Stok', nilai: (it) => Number(it.stock_qty || 0) },
            { label: 'Min. stok', nilai: (it) => Number(it.min_stock || 0) },
            { label: 'Status stok', nilai: (it) => STATUS_STOK[statusStok(it)].label },
            { label: 'HPP satuan', nilai: (it) => Number(it.unit_cost || 0) },
            { label: 'Nilai stok', nilai: (it) => Number(it.stock_value || 0) },
            { label: 'Sudah dinilai', nilai: (it) => (it.valued ? 'Ya' : 'Belum') },
            { label: 'Metode biaya', nilai: (it) => labelMetode(it.cost_method) },
          ]} />
        <div className="hidden md:block"><ViewToggle value={view} onChange={setView} testId="acc-view" /></div>
        <Button variant="outline" size="icon" onClick={muatUlang} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="acc-dash-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={<>
        {error && <Notice tone="danger" icon={AlertTriangle}>{error}</Notice>}
        {loading && !dash ? (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-20 rounded-lg" />)}
          </div>
        ) : dash ? (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="acc-kpi">
            <StatTile label="Item aktif" value={fmtNum(dash.total_items)} testId="acc-kpi-total-item"
              sub={`Nilai stok ${fmtRp(dash.total_stock_value)}`} />
            <StatTile label="Stok habis" value={fmtNum(dash.out_of_stock)} accent={dash.out_of_stock ? 'danger' : 'default'}
              testId="acc-kpi-stok-habis" onClick={() => setSaring('habis')}
              hint={`Menipis: ${fmtNum(dash.low_stock)} item`} />
            {/* Dulu spanduk kuning terpisah; kini kartu yang bisa diklik (saringan Belum dinilai) */}
            <StatTile label="Belum dinilai (HPP kosong)" value={fmtNum(dash.unvalued_items)} testId="acc-kpi-belum-dinilai"
              accent={dash.unvalued_items ? 'warning' : 'default'} onClick={() => setSaring('belum')}
              hint="Lihat item" />
            <StatTile label="Permintaan menunggu" value={fmtNum(dash.pending_requests)} testId="acc-kpi-request-pending"
              sub={`Perlu diserahkan ${fmtNum(dash.ready_to_deliver)} · PR berjalan ${fmtNum(dash.pending_pr)}`} />
          </div>
        ) : null}
        {dash?.active_opname && (
          <Notice tone="info" icon={ClipboardCheck} title="Sesi stok opname sedang berjalan" testId="acc-active-opname">
            Nomor sesi {dash.active_opname}. Angka stok bisa berubah setelah opname ditutup.
          </Notice>
        )}
      </>}
      footer={rows.length > pageSize && (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />
      )}>
      {stockErr ? (
        <Notice tone="danger" icon={AlertTriangle}>{stockErr}</Notice>
      ) : stockLoading && stock.length === 0 ? (
        <div className="space-y-2">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
      ) : (
        <>
          {view === 'grid' && rows.length > 0 ? (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4" data-testid="acc-stock-grid">
              {paged.map((it) => {
                const st = STATUS_STOK[statusStok(it)];
                return (
                  <div key={it.id} className="cursor-pointer rounded-lg border border-[var(--glass-border)] bg-[var(--card-surface)] p-3"
                    onClick={() => setRinci(it)} data-testid={`acc-stock-card-${it.code}`}>
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-foreground" title={it.name}>{it.name}</p>
                        <p className="text-xs tabular-nums text-muted-foreground">{it.code}</p>
                      </div>
                      <StatusBadge status={statusStok(it)} label={st.label} tone={st.tone} />
                    </div>
                    <div className="mt-2 flex items-end justify-between text-sm">
                      <span className="tabular-nums">{fmtNum(it.stock_qty)} {it.unit}</span>
                      <span className="font-semibold tabular-nums">{fmtRp(it.stock_value)}</span>
                    </div>
                    {!it.valued && <p className="mt-1 text-xs text-[hsl(var(--warning-text))]">Belum dinilai</p>}
                  </div>
                );
              })}
            </div>
          ) : (
            <TabelData kolom={kolom} baris={paged} testId="acc-table" onKlikBaris={setRinci}
              kosong={<EmptyState icon={Package}
                title={stock.length ? 'Tidak ada item yang cocok' : 'Belum ada item aksesoris'}
                description={stock.length ? 'Ubah saringan atau kata pencarian.' : 'Item aksesoris ditambahkan di menu Master Aksesoris.'} />} />
          )}
        </>
      )}

      {rinci && (
        <DetailPopup open onClose={() => setRinci(null)} judul={rinci.name} keterangan={rinci.code} testId="acc-stock-detail"
          status={<StatusBadge status={statusStok(rinci)} label={STATUS_STOK[statusStok(rinci)].label} tone={STATUS_STOK[statusStok(rinci)].tone} />}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Kategori">{rinci.category || '—'}</BarisDetail>
            <BarisDetail label="Stok">{fmtNum(rinci.stock_qty)} {rinci.unit}</BarisDetail>
            <BarisDetail label="Min. stok">{fmtNum(rinci.min_stock)} {rinci.unit}</BarisDetail>
            <BarisDetail label="HPP satuan">{fmtRp(rinci.unit_cost)}{!rinci.valued && ' (belum dinilai)'}</BarisDetail>
            <BarisDetail label="Nilai stok">{fmtRp(rinci.stock_value)}</BarisDetail>
            <BarisDetail label="Metode biaya">{labelMetode(rinci.cost_method)}</BarisDetail>
          </dl>
        </DetailPopup>
      )}
    </PageLayout>
  );
}

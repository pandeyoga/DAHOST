/**
 * Daftar stok gudang (tab "Daftar stok" di hub Stok & Akurasi) — hanya baca.
 *
 * Tahap 9C (7 Nov 2026, keputusan owner):
 *   • Saringan **Kepemilikan** tepat dua pilihan: "Milik CV Dewi Aditya" (stok DA) dan "Titipan klien maklon"
 *     (barang jadi klien per artikel Katalog Buyer, pcs tanpa nilai) + sub-saringan klien.
 *   • "Tampilkan juga yang stoknya 0" mengikuti kepemilikan — dulu pilihan klien maklon + stok 0 menampilkan
 *     seluruh master DA.
 *   • Teks layar berbahasa Indonesia (tanpa kode program seperti raw_material).
 *   • Standar UI/UX v2 (8 Nov 2026): TabelData (kartu ringkas di HP), riwayat mutasi = popup (DetailPanel ber-onClose),
 *     unduh Excel/CSV semua baris hasil saringan, kartu jumlah lintas satuan dihapus (lihat ringkasan).
 *
 *   - daftar  : GET /api/wms/stock/unified?ownership=cv_da|titipan_klien&client_id=…
 *   - riwayat : GET /api/rahaza/material-movements?material_id=… (DA) · GET /api/wms/stock/titipan-klien/mutasi?stock_key=…
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { Package, Search, RefreshCw, History, AlertTriangle, X } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassInput } from '@/components/ui/glass';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Checkbox } from '@/components/ui/checkbox';
import PaginationLite from '@/components/ui/pagination-lite';
import { formatDateID } from '@/lib/format';
import { apiGet } from '../../lib/api';
import PageLayout, { DetailPanel } from './layout/PageLayout';
import { EmptyState, Notice, StatTile } from './moduleAtoms';

const PAGE_SIZE = 25;
const OWN_DA = 'cv_da';
const OWN_TITIPAN = 'titipan_klien';
const OWNERSHIP_OPTIONS = [
  { value: OWN_DA, label: 'Milik CV Dewi Aditya' },
  { value: OWN_TITIPAN, label: 'Titipan klien maklon' },
];
const TYPE_LABELS = { fg: 'Barang jadi', fabric: 'Kain', accessory: 'Aksesoris' };
const CATEGORY_LABELS = {
  raw_material: 'Bahan baku', wip_internal: 'Barang setengah jadi', fg_internal: 'Barang jadi',
  maklon_wip: 'Barang setengah jadi klien', maklon_fg: 'Barang jadi klien',
};
const DA_MOVE_LABELS = {
  receive: 'Terima', transfer: 'Pindah lokasi', adjust: 'Penyesuaian', ADJUST: 'Penyesuaian', issue: 'Keluar',
  opening: 'Saldo awal', opname: 'Opname', IN: 'Masuk', OUT: 'Keluar',
};

const fmtNum = (v) => Number(v || 0).toLocaleString('id-ID');
const fmtDate = (d) => (d ? formatDateID(d) : '—');
const jenisLabel = (item) => TYPE_LABELS[item.material_type] || CATEGORY_LABELS[item.inventory_category] || 'Lainnya';
const locCode = (item) => (item.no_stock_row ? 'Belum ada stok' : (item.location_code || item.location || '—'));
const locLabel = (item) => (item.no_stock_row
  ? 'Belum ada stok'
  : (item.location_code ? `${item.location_code}${item.location_name ? ` · ${item.location_name}` : ''}` : (item.location || '—')));

export default function UnifiedInventoryModule() {
  const [ownership, setOwnership] = useState(OWN_DA);
  const [clientId, setClientId] = useState('');
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [colorFilter, setColorFilter] = useState('');
  const [optionFilter, setOptionFilter] = useState('');
  // 2026-09-24 keputusan owner: daftar stok = SEMUA barang (qty 0 ikut tampil) secara bawaan
  const [includeZero, setIncludeZero] = useState(true);
  const [page, setPage] = useState(1);
  const [data, setData] = useState({ items: [], total: 0, total_pages: 0, totals: {}, facets: {} });
  const [loading, setLoading] = useState(true);   // dulu false → sebelum muatan pertama tampil 'Belum ada stok'
  const [error, setError] = useState('');
  const [detail, setDetail] = useState(null);
  const reqSeq = useRef(0);
  const titipan = ownership === OWN_TITIPAN;

  const buildQuery = useCallback((p, limit) => {
    const qs = new URLSearchParams({ page: String(p), limit: String(limit), ownership });
    if (titipan && clientId) qs.append('client_id', clientId);
    if (search.trim()) qs.append('search', search.trim());
    if (!titipan && typeFilter) qs.append('material_type', typeFilter);
    if (categoryFilter) qs.append('category', categoryFilter);
    if (colorFilter) qs.append('color', colorFilter);
    if (!titipan && optionFilter) qs.append('option', optionFilter);
    if (includeZero) qs.append('include_zero', '1');
    return qs.toString();
  }, [ownership, titipan, clientId, search, typeFilter, categoryFilter, colorFilter, optionFilter, includeZero]);

  const load = useCallback(async () => {
    const seq = ++reqSeq.current;          // jawaban lama yang datang belakangan tidak menimpa saringan baru
    setLoading(true);
    setError('');
    try {
      const res = await apiGet(`/wms/stock/unified?${buildQuery(page, PAGE_SIZE)}`);
      if (seq !== reqSeq.current) return;
      setData({ items: res?.items || [], total: res?.total || 0, total_pages: res?.total_pages || 0,
        totals: res?.totals || {}, facets: res?.facets || {} });
    } catch (e) {
      if (seq !== reqSeq.current) return;
      setError(e?.message || 'Gagal memuat daftar stok');
      setData((d) => ({ ...d, items: [], total: 0, total_pages: 0, totals: {} }));
    } finally {
      if (seq === reqSeq.current) setLoading(false);
    }
  }, [buildQuery, page]);

  useEffect(() => {
    const t = setTimeout(load, 300);
    return () => clearTimeout(t);
  }, [load]);

  // halaman kembali ke 1 dan rincian ditutup saat saringan berubah
  useEffect(() => { setPage(1); setDetail(null); },
    [ownership, clientId, search, typeFilter, categoryFilter, colorFilter, optionFilter, includeZero]);

  const changeOwnership = (v) => {
    setOwnership(v || OWN_DA);
    setClientId(''); setTypeFilter(''); setCategoryFilter(''); setColorFilter(''); setOptionFilter('');
  };
  const filtered = !!(search.trim() || typeFilter || categoryFilter || colorFilter || optionFilter || clientId);
  const resetFilters = () => {
    setSearch(''); setTypeFilter(''); setCategoryFilter(''); setColorFilter(''); setOptionFilter(''); setClientId('');
  };

  // Unduh SEMUA baris hasil saringan (bukan hanya halaman tampil): loop halaman @500 (batas server).
  const ambilSemua = async () => {
    const semua = [];
    for (let p = 1; p <= 100; p += 1) {
      const res = await apiGet(`/wms/stock/unified?${buildQuery(p, 500)}`);
      semua.push(...(res?.items || []));
      if (!res?.has_next) break;
    }
    return semua;
  };
  const kolomUnduh = titipan ? [
    { label: 'Klien', nilai: (i) => i.owner_client_name || '' },
    { label: 'Artikel', nilai: (i) => i.artikel_code || '' },
    { label: 'Kode barang', nilai: (i) => i.material_code || '' },
    { label: 'Nama barang', nilai: (i) => i.material_name || '' },
    { label: 'Warna', nilai: (i) => i.color_name || '' },
    { label: 'Ukuran', nilai: (i) => i.size_code || '' },
    { label: 'Jumlah (pcs)', nilai: (i) => Number(i.quantity || 0) },
    { label: 'Lokasi', nilai: (i) => locLabel(i) },
  ] : [
    { label: 'Kode barang', nilai: (i) => i.material_code || i.sku || '' },
    { label: 'Nama barang', nilai: (i) => i.material_name || '' },
    { label: 'Kategori', nilai: (i) => i.category_name || '' },
    { label: 'Warna', nilai: (i) => i.color_name || '' },
    { label: 'Opsi', nilai: (i) => i.option_name || '' },
    { label: 'Ukuran', nilai: (i) => i.size_code || '' },
    { label: 'Jenis', nilai: (i) => jenisLabel(i) },
    { label: 'Jumlah', nilai: (i) => Number(i.quantity || 0) },
    { label: 'Tersedia', nilai: (i) => Number(i.available_quantity || 0) },
    { label: 'Dicadangkan', nilai: (i) => Number(i.reserved_quantity || 0) },
    { label: 'Satuan', nilai: (i) => i.unit || '' },
    { label: 'Lokasi', nilai: (i) => locLabel(i) },
  ];

  const facets = data.facets || {};
  const clients = facets.clients || [];
  const totals = data.totals || {};
  const items = data.items || [];
  const isOpen = (item) => detail && (detail.stock_key || detail.material_id) === (item.stock_key || item.material_id)
    && (detail.location_id || '') === (item.location_id || '');

  const bisaRiwayat = (i) => (titipan ? !!i.movements : !i.no_stock_row);
  const bukaRiwayat = (i) => { if (bisaRiwayat(i)) setDetail(i); };
  const tombolRiwayat = (i, testId) => (
    <Button size="icon-sm" variant="ghost" disabled={!bisaRiwayat(i)} onClick={() => setDetail(i)}
      title="Riwayat mutasi" aria-label="Riwayat mutasi" data-testid={testId}><History /></Button>
  );
  const qtyCls = (v) => `tabular-nums md:whitespace-nowrap ${Number(v) < 0 ? 'text-[hsl(var(--danger-text))]' : ''}`;
  const kolomTitipan = [
    { kunci: 'artikel', label: 'Artikel', hp: 'judul', isi: (i) => (
      <div className={`min-w-0 ${isOpen(i) ? 'text-[hsl(var(--primary))]' : ''}`} data-testid={`inv-row-${i.material_code || i.stock_key}`}>
        <p className="font-medium md:whitespace-nowrap">{i.artikel_code || '—'}</p>
        {i.material_name && <p className="text-xs text-muted-foreground">{i.material_name}</p>}
      </div>) },
    { kunci: 'klien', label: 'Klien', hp: 'keterangan', isi: (i) => i.owner_client_name || '—' },
    { kunci: 'kode', label: 'Kode barang', hp: false, isi: (i) => <span className="md:whitespace-nowrap">{i.material_code || '—'}</span> },
    { kunci: 'varian', label: 'Warna · ukuran', isi: (i) => <span className="text-sm">{i.color_name || '—'}{i.size_code ? <span className="text-muted-foreground"> · {i.size_code}</span> : null}</span> },
    { kunci: 'qty', label: 'Jumlah (pcs)', rata: 'kanan', isi: (i) => <span className={qtyCls(i.quantity)}>{fmtNum(i.quantity)}</span> },
    { kunci: 'lokasi', label: 'Lokasi', isi: (i) => <span className="text-sm text-muted-foreground md:whitespace-nowrap" title={locLabel(i)}>{locCode(i)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (i) => tombolRiwayat(i, `inv-history-${i.material_code || i.stock_key}`) },
  ];
  const kolomDa = [
    { kunci: 'kode', label: 'Kode barang', hp: 'keterangan', isi: (i) => (
      <span className="md:whitespace-nowrap" data-testid={`inv-row-${i.material_code || i.material_id}`}>{i.material_code || i.sku || '—'}</span>) },
    { kunci: 'nama', label: 'Nama barang', hp: 'judul', isi: (i) => (
      <div className={`min-w-0 md:max-w-[20rem] ${isOpen(i) ? 'text-[hsl(var(--primary))]' : ''}`}>
        <p className="font-medium">{i.material_name || '—'}</p>
        {i.category_name && <p className="text-xs text-muted-foreground">{i.category_name}</p>}
      </div>) },
    { kunci: 'varian', label: 'Warna · ukuran · opsi', hp: false, isi: (i) => (
      <span className="text-sm">{i.color_name || '—'}{i.size_code ? <span className="text-muted-foreground"> · {i.size_code}</span> : null}{i.option_name ? <span className="text-muted-foreground"> · {i.option_name}</span> : null}</span>) },
    { kunci: 'jenis', label: 'Jenis', hp: false, isi: (i) => <span className="text-sm">{jenisLabel(i)}</span> },
    { kunci: 'qty', label: 'Jumlah', rata: 'kanan', isi: (i) => <span className={qtyCls(i.quantity)}>{fmtNum(i.quantity)} {i.unit}</span> },
    { kunci: 'tersedia', label: 'Tersedia', hp: false, rata: 'kanan', isi: (i) => <span className="tabular-nums md:whitespace-nowrap">{fmtNum(i.available_quantity)} {i.unit}</span> },
    { kunci: 'cadang', label: 'Dicadangkan', hp: false, rata: 'kanan', isi: (i) => <span className="tabular-nums">{fmtNum(i.reserved_quantity)}</span> },
    { kunci: 'lokasi', label: 'Lokasi', isi: (i) => <span className="text-sm text-muted-foreground md:whitespace-nowrap" title={locLabel(i)}>{locCode(i)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (i) => tombolRiwayat(i, `view-movements-${i.material_code || i.material_id}`) },
  ];

  return (
    <PageLayout
      testId="inv-stock-list"
      title="Daftar stok"
      subtitle="Stok per barang dan lokasi. Penyesuaian stok dilakukan di tab Penyesuaian."
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <GlassInput value={search} onChange={(e) => setSearch(e.target.value)} className="pl-8 h-9"
            placeholder={titipan ? 'Cari klien, artikel, kode barang…' : 'Cari kode barang, nama, warna, lokasi…'}
            data-testid="inv-search" aria-label="Cari" />
        </div>
        <SmartNativeSelect value={ownership} onChange={(e) => changeOwnership(e.target.value)} className="h-9 w-56 max-w-full" wrapperClassName="w-56 max-w-full"
          data-testid="inv-filter-ownership" aria-label="Kepemilikan" searchable={false}>
          {OWNERSHIP_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </SmartNativeSelect>
        {titipan && (
          <SmartNativeSelect value={clientId} onChange={(e) => setClientId(e.target.value)} className="h-9 w-64 max-w-full" wrapperClassName="w-64 max-w-full"
            data-testid="inv-filter-client" aria-label="Klien maklon">
            <option value="">Semua klien ({clients.length})</option>
            {clients.map((c) => <option key={c.id} value={c.id}>{c.name}{c.code ? ` (${c.code})` : ''}</option>)}
          </SmartNativeSelect>
        )}
        {!titipan && (
          <SmartNativeSelect value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} className="h-9 w-44 max-w-full" wrapperClassName="w-44 max-w-full"
            data-testid="inv-filter-type" aria-label="Jenis barang" searchable={false}>
            <option value="">Semua jenis</option>
            <option value="fg">Barang jadi</option>
            <option value="fabric">Kain</option>
            <option value="accessory">Aksesoris</option>
          </SmartNativeSelect>
        )}
        {(facets.categories || []).length > 0 && (
          <SmartNativeSelect value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)} className="h-9 w-48 max-w-full" wrapperClassName="w-48 max-w-full"
            data-testid="inv-filter-category" aria-label="Kategori">
            <option value="">Semua kategori</option>
            {facets.categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </SmartNativeSelect>
        )}
        {(facets.colors || []).length > 0 && (
          <SmartNativeSelect value={colorFilter} onChange={(e) => setColorFilter(e.target.value)} className="h-9 w-44 max-w-full" wrapperClassName="w-44 max-w-full"
            data-testid="inv-filter-color" aria-label="Warna">
            <option value="">Semua warna</option>
            {facets.colors.map((c) => <option key={c} value={c}>{c}</option>)}
          </SmartNativeSelect>
        )}
        {!titipan && (facets.options || []).length > 0 && (
          <SmartNativeSelect value={optionFilter} onChange={(e) => setOptionFilter(e.target.value)} className="h-9 w-44 max-w-full" wrapperClassName="w-44 max-w-full"
            data-testid="inv-filter-option" aria-label="Opsi varian">
            <option value="">Semua opsi</option>
            {facets.options.map((c) => <option key={c} value={c}>{c}</option>)}
          </SmartNativeSelect>
        )}
        <label className="inline-flex items-center gap-2 h-9 text-sm text-foreground/80 cursor-pointer select-none"
          title={titipan ? 'Varian Katalog Buyer klien yang belum punya stok ikut tampil dengan jumlah 0.'
            : 'Barang master CV Dewi Aditya yang belum punya stok ikut tampil dengan jumlah 0.'}>
          <Checkbox checked={includeZero} onCheckedChange={(v) => setIncludeZero(v === true)}
            data-testid="inv-show-zero-toggle" aria-label="Tampilkan juga yang stoknya 0" />
          Tampilkan juga yang stoknya 0
        </label>
        {filtered && (
          <Button variant="outline" onClick={resetFilters} data-testid="inv-clear-filters">
            <X className="h-3.5 w-3.5" />Reset filter
          </Button>
        )}
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <TombolUnduh namaBerkas={titipan ? 'stok-titipan-klien' : 'stok-barang'} namaLembar="Stok" baris={items}
            ambilSemua={ambilSemua} kolom={kolomUnduh} testId="inv-export" />
          <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={load} data-testid="inv-refresh">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
        </div>
      </>}
      summary={<>
        {error && <Notice tone="danger" icon={AlertTriangle} title="Gagal memuat data" testId="inv-error">{error}</Notice>}
        {titipan && (
          <Notice tone="info" title="Barang titipan klien maklon" testId="inv-titipan-note">
            Milik klien, bukan milik CV Dewi Aditya: dicatat per artikel Katalog Buyer dalam pcs, tanpa nilai dan tanpa jurnal.
            Masuk saat Terima &amp; QC dari CMT, keluar saat Kirim hasil ke klien.
          </Notice>
        )}
        {/* Verifikasi 8 Nov 2026: `totals` dari server = SEMUA baris hasil saringan (bukan halaman). "Jumlah stok",
            "Tersedia", "Dicadangkan" untuk stok DA DIHAPUS — menjumlah pcs + kg + m + pack jadi satu angka (−1 di DB uji)
            yang tidak berarti apa-apa. Titipan klien selalu pcs → jumlahnya tetap ditampilkan. */}
        {titipan && Number(totals.rows || 0) > 0 && (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile testId="inv-kpi-rows" label="Barang klien" value={fmtNum(totals.rows)} sub="Baris artikel × warna × ukuran sesuai saringan." />
            <StatTile testId="inv-kpi-qty" label="Jumlah titipan (pcs)" value={fmtNum(totals.quantity)} sub="Total pcs titipan sesuai saringan." />
            <StatTile testId="inv-kpi-clients" label="Klien" value={fmtNum(totals.clients)} sub="Klien maklon yang punya titipan." />
          </div>
        )}
        {!titipan && !loading && Number(totals.rows || 0) > 0 && (
          <p className="text-sm text-muted-foreground" data-testid="inv-ringkas">
            <span className="font-medium text-foreground tabular-nums">{fmtNum(totals.rows)}</span> baris sesuai saringan
            {includeZero ? ' (termasuk barang yang belum punya stok)' : ''}.
          </p>
        )}
        {!titipan && Number(totals.negative_rows || 0) > 0 && (
          <Notice tone="danger" icon={AlertTriangle} testId="inv-kpi-negative"
            title={`${fmtNum(totals.negative_rows)} baris stok minus`}>
            Stok tercatat kurang dari 0 — periksa di tab Stok minus lalu lakukan opname.
          </Notice>
        )}
      </>}
      detail={detail && <MovementsPanel item={detail} titipan={titipan} onClose={() => setDetail(null)} />}
      footer={data.total > PAGE_SIZE && (
        <div data-testid="inventory-pagination">
          <PaginationLite page={page} totalPages={data.total_pages} total={data.total} pageSize={PAGE_SIZE} onPageChange={setPage} />
        </div>
      )}
    >
      {loading && !items.length ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat stok…</p>
      ) : (
        <TabelData kolom={titipan ? kolomTitipan : kolomDa} baris={items} onKlikBaris={bukaRiwayat}
          kunci={(i) => (titipan ? i.stock_key : `${i.id || i.material_id || 'baris'}-${i.location_id || ''}`)}
          testId={titipan ? 'inv-table-titipan' : 'inv-table-da'}
          kosong={<div data-testid="inv-empty">
            {filtered ? (
              <EmptyState icon={Package} title="Tidak ada stok yang cocok dengan saringan"
                description="Ubah atau hapus penyaring untuk melihat barang lain."
                action={<Button variant="outline" onClick={resetFilters}>Tampilkan semua</Button>} />
            ) : titipan ? (
              <EmptyState icon={Package} title="Belum ada barang titipan klien"
                description="Barang jadi klien maklon tercatat di sini setelah Terima & QC dari CMT selesai." />
            ) : (
              <EmptyState icon={Package} title="Belum ada stok" description="Stok tercatat dari penerimaan barang, produksi, atau opname." />
            )}
          </div>} />
      )}
    </PageLayout>
  );
}

function MovementsPanel({ item, titipan, onClose }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [balance, setBalance] = useState(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      try {
        if (titipan) {
          const res = await apiGet(`/wms/stock/titipan-klien/mutasi?stock_key=${encodeURIComponent(item.stock_key)}&limit=50`);
          if (alive) { setRows(res?.items || []); setBalance(res?.balance); }
        } else {
          const res = await apiGet(`/rahaza/material-movements?material_id=${encodeURIComponent(item.material_id)}&limit=20`);
          const list = Array.isArray(res) ? res : (res?.items || res?.movements || []);
          if (alive) setRows(list.map((m) => ({
            id: m.id, created_at: m.created_at, jenis_label: DA_MOVE_LABELS[m.type || m.movement_type] || 'Mutasi',
            qty: m.qty ?? m.quantity, dokumen: m.ref_number || m.reference_no || '',
            dari_ke: [m.from_location_name, m.to_location_name].filter(Boolean).join(' → '), notes: m.notes || '',
          })));
        }
      } catch (e) {
        if (alive) { setRows([]); toast.error(`Gagal memuat riwayat: ${e?.message || e}`); }
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [item, titipan]);

  const title = `Riwayat ${item.material_code || item.artikel_code || ''}`.trim();
  const description = titipan
    ? `${item.owner_client_name || 'Klien maklon'} · ${item.material_name || ''} · saldo ${fmtNum(balance ?? item.quantity)} pcs`
    : `${item.material_name || ''} · ${locLabel(item)} · jumlah ${fmtNum(item.quantity)} ${item.unit || ''}`;
  return (
    <DetailPanel title={title} description={description} onClose={onClose} testId="inv-movements-panel"
      actions={rows.length > 0 ? (
        <TombolUnduh namaBerkas={`riwayat-${item.material_code || item.artikel_code || 'stok'}`} namaLembar="Riwayat" baris={rows}
          testId="inv-movements-unduh" kolom={[
            { label: 'Tanggal', nilai: (m) => fmtDate(m.created_at) },
            { label: 'Jenis', nilai: (m) => m.jenis_label || '' },
            { label: 'Jumlah', nilai: (m) => Number(m.qty || 0) },
            { label: 'Dokumen', nilai: (m) => m.dokumen || '' },
            { label: titipan ? 'PO' : 'Dari → ke', nilai: (m) => (titipan ? m.po_number : m.dari_ke) || '' },
            { label: 'Catatan', nilai: (m) => m.notes || '' },
          ]} />
      ) : null}>
      {loading ? (
        <div className="text-sm text-muted-foreground"><RefreshCw className="w-4 h-4 animate-spin inline mr-2" />Memuat riwayat…</div>
      ) : rows.length === 0 ? (
        <EmptyState icon={History} title="Belum ada riwayat mutasi" description="Mutasi tercatat saat barang masuk, keluar, atau disesuaikan." />
      ) : (
        <Table data-testid="inv-movements-table">
          <TableHeader><TableRow>
            <TableHead>Tanggal</TableHead><TableHead>Jenis</TableHead><TableHead className="text-right">Jumlah</TableHead>
            <TableHead>Dokumen</TableHead><TableHead>{titipan ? 'PO' : 'Dari → ke'}</TableHead><TableHead>Catatan</TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {rows.map((m, idx) => (
              <TableRow key={m.id || idx}>
                <TableCell className="whitespace-nowrap">{fmtDate(m.created_at)}</TableCell>
                <TableCell>{m.jenis_label}</TableCell>
                <TableCell className={`text-right tabular-nums ${Number(m.qty) < 0 ? 'text-[hsl(var(--destructive))]' : ''}`}>
                  {Number(m.qty) > 0 ? '+' : ''}{fmtNum(m.qty)}
                </TableCell>
                <TableCell className="whitespace-nowrap">{m.dokumen || '—'}</TableCell>
                <TableCell className="text-sm">{(titipan ? m.po_number : m.dari_ke) || '—'}</TableCell>
                <TableCell className="text-sm text-muted-foreground">{m.notes || '—'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </DetailPanel>
  );
}

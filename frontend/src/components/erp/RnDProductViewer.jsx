/**
 * RnDProductViewer — **Katalog produk final RnD + status SSOT** (sesi #34).
 *
 * Pemilik: "di portal ini tidak memperlihatkan viewer product internal … sesuai
 * dengan hasil final RND menjadi master data ini sama saja menjadi catalog …
 * perlihatkan juga apakah ini sudah di sync dengan catalog marketing … pastikan
 * SSOT master data ini tidak broken dan link ke produksinya juga benar."
 *
 * Layar ini TIDAK memperbaiki data; ia memperlihatkan apa adanya — termasuk yang
 * rusak. Tiap baris menyebut kekurangannya (BOM belum ada, belum masuk katalog
 * marketing, biaya jahit SPK belum diisi, HPP masih perkiraan BOM). Jadi viewer
 * ini sekaligus pemeriksa sambungan RnD → Produksi → Marketing.
 *
 * Standar UI/UX v2 (8 Nov 2026):
 *  • 615 produk dulu tampil sebagai kartu besar berulang (hanya 60 pertama) → tabel berhalaman, rincian = popup.
 *  • BUG ANGKA: ringkasan dulu dihitung server dari 60 baris yang dimuat saja, tetapi "Produk final" = 615
 *    (semua) — mis. "Sudah di katalog 8 · 52 belum" padahal yang belum ±600. Kini SEMUA halaman diambil
 *    (limit 200 + offset, API yang sama) dan ringkasan dihitung dari daftar yang sama dengan tabel,
 *    memakai rumus yang sama dengan server (`routes/rnd_product_viewer.py`). Urut margin juga dulu hanya
 *    berlaku per 60 baris; kini diurut atas semua baris.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Boxes, RefreshCw, Search } from 'lucide-react';
import { toast } from 'sonner';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { Skeleton } from '@/components/ui/skeleton';
import { formatRupiah } from '@/lib/format';
import { apiGet } from '@/lib/api';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';

const rp = formatRupiah;
const HALAMAN_API = 200;   // batas `limit` di server

const hppOf = (r) => r.hpp?.fifo_avg || r.hpp?.master || 0;
const bisaDihitung = (r) => !!(r.price?.selling && hppOf(r));
const SUMBER_HPP = {
  none: 'Belum ada batch masuk gudang',
  fifo_remaining: 'Rata-rata batch yang masih bersisa',
  fifo_last_batch_no_stock: 'Batch terakhir (stok sudah habis)',
};
const TEKS = {
  success: 'text-[hsl(var(--success-text))]', warning: 'text-[hsl(var(--warning-text))]',
  danger: 'text-[hsl(var(--danger-text))]',
};
const nadaMargin = (r) => (r.price.margin < 0 ? TEKS.danger
  : r.price.margin < 0.15 * r.price.selling ? TEKS.warning : TEKS.success);
const persenMargin = (r) => Math.round((r.price.margin / r.price.selling) * 100);

/** Ringkasan dengan rumus yang sama seperti `summary` di server, atas SEMUA baris. */
function ringkas(rows) {
  const priced = rows.filter(bisaDihitung);
  return {
    total: rows.length,
    synced: rows.filter((r) => r.marketing_sync?.synced).length,
    no_bom: rows.filter((r) => !r.production?.bom_ready).length,
    hpp_real: rows.filter((r) => (r.hpp?.layer_count || 0) > 0).length,
    ssot_ok: rows.filter((r) => r.ssot_ok).length,
    margin_measurable: priced.length,
    margin_unmeasurable: rows.length - priced.length,
    margin_negative: priced.filter((r) => r.price.margin < 0).length,
    margin_thin: priced.filter((r) => r.price.margin >= 0 && r.price.margin < 0.15 * r.price.selling).length,
    margin_avg_pct: priced.length
      ? Math.round((priced.reduce((s, r) => s + (r.price.margin_pct || 0), 0) / priced.length) * 10) / 10
      : null,
  };
}

/** Urut margin = `_key` di server: yang bisa dihitung dulu, lalu menurut margin rupiah. */
function urutkan(rows, sort) {
  if (sort !== 'margin_asc' && sort !== 'margin_desc') return rows;
  const arah = sort === 'margin_asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    const ka = bisaDihitung(a) ? 0 : 1;
    const kb = bisaDihitung(b) ? 0 : 1;
    if (ka !== kb) return ka - kb;
    if (ka === 1) return 0;
    return arah * (a.price.margin - b.price.margin);
  });
}

function Gambar({ src, alt, besar = false }) {
  const ukuran = besar ? 'h-24 w-24' : 'h-10 w-10';
  return (
    <div className={`${ukuran} shrink-0 overflow-hidden rounded-md border border-[var(--glass-border)] bg-[var(--card-surface)] flex items-center justify-center`}>
      {src ? <img src={src} alt={alt} className="h-full w-full object-cover" loading="lazy" />
        : <Boxes className="h-4 w-4 text-muted-foreground" aria-hidden="true" />}
    </div>
  );
}

function KolomMargin({ r }) {
  if (!r.price.selling) return <span className="text-muted-foreground">—</span>;
  if (!hppOf(r)) {
    // SESI #37 — HPP belum ada ⇒ katakan "belum bisa diukur", jangan kosong (dulu pembaca menyimpulkan sendiri).
    return (
      <span data-testid={`rnd-margin-unknown-${r.sku}`} title="HPP belum ada (BOM / biaya jahit belum tercatat)"
        className="text-xs text-[hsl(var(--warning-text))]">belum bisa diukur</span>
    );
  }
  return (
    <span className={`tabular-nums ${nadaMargin(r)}`} data-testid={`rnd-margin-${r.sku}`}>
      {rp(r.price.margin)} <span className="text-xs">({persenMargin(r)}%)</span>
    </span>
  );
}

function Seksi({ judul, alat, children }) {
  return (
    <section className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">{judul}</h3>
        {alat}
      </div>
      {children}
    </section>
  );
}

export default function RnDProductViewer() {
  const [rows, setRows] = useState([]);
  const [q, setQ] = useState('');
  const [onlyBroken, setOnlyBroken] = useState('');
  // SESI #34 — papan margin: produk paling tipis/merugi muncul lebih dulu.
  // Produk yang HPP atau harga jualnya belum ada TIDAK dihitung bermargin 0
  // (itu menutupi masalahnya) — jumlahnya disebut terpisah.
  const [sort, setSort] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [baris, setBaris] = useState(null);     // baris yang dibuka (ringkasan sudah ada)
  const [detail, setDetail] = useState(null);   // data lengkap dari server

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      // Ambil SEMUA halaman (server membatasi 200 per panggilan) supaya ringkasan & urutan benar.
      const semua = [];
      let total = Infinity;
      for (let offset = 0; offset < total && offset < 20000; offset += HALAMAN_API) {
        const d = await apiGet(`/rnd/product-viewer?limit=${HALAMAN_API}&offset=${offset}`);
        const data = d?.data || [];
        total = Number(d?.total ?? data.length);
        semua.push(...data);
        if (data.length < HALAMAN_API) break;
      }
      // Jaga-jaga: satu produk tidak boleh terhitung dua kali bila urutan server bergeser antarhalaman.
      setRows([...new Map(semua.map((r) => [r.material_id, r])).values()]);
    } catch (e) {
      setLoadError(e.message || 'Gagal memuat produk RnD');
      toast.error(e.message || 'Gagal memuat produk RnD');
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const openDetail = async (r) => {
    setBaris(r);
    setDetail({ loading: true });
    try {
      setDetail(await apiGet(`/rnd/product-viewer/${r.material_id}`));
    } catch (e) {
      toast.error(e.message); setBaris(null); setDetail(null);
    }
  };

  // Pencarian sama dengan server: SKU, nama, nama/kode model.
  const cocok = useMemo(() => {
    const k = q.trim().toLowerCase();
    if (!k) return rows;
    return rows.filter((r) => [r.sku, r.name, r.model_name, r.model_code]
      .some((v) => String(v || '').toLowerCase().includes(k)));
  }, [rows, q]);
  const s = useMemo(() => ringkas(cocok), [cocok]);
  const shown = useMemo(
    () => urutkan(onlyBroken ? cocok.filter((r) => !r.ssot_ok) : cocok, sort),
    [cocok, onlyBroken, sort],
  );
  const { page, setPage, totalPages, total, paged } = useClientPagination(shown, 25);

  const kolom = [
    { kunci: 'produk', label: 'Produk', hp: 'judul', isi: (r) => (
      <div className="flex min-w-0 items-center gap-3" data-testid={`rnd-product-${r.sku}`}>
        <Gambar src={r.images?.[0]} alt={r.name} />
        <div className="min-w-0">
          <p className="font-medium text-foreground md:max-w-[18rem] md:truncate" title={r.name}>{r.name}</p>
          <p className="text-xs text-muted-foreground md:truncate">
            <span className="font-mono">{r.sku}</span>
            {[r.category, r.color, r.size].filter(Boolean).length > 0 && ` · ${[r.category, r.color, r.size].filter(Boolean).join(' · ')}`}
          </p>
        </div>
      </div>) },
    { kunci: 'hpp', label: 'HPP', rata: 'kanan', isi: (r) => (
      <div>
        <p className="tabular-nums">{rp(hppOf(r))}</p>
        <p className="text-xs text-muted-foreground">{r.hpp.layer_count ? `${r.hpp.layer_count} batch` : 'perkiraan BOM'}</p>
      </div>) },
    { kunci: 'jual', label: 'Harga jual', rata: 'kanan', isi: (r) => (r.price.selling
      ? <span className="tabular-nums">{rp(r.price.selling)}</span> : <span className="text-muted-foreground">—</span>) },
    { kunci: 'margin', label: 'Margin', rata: 'kanan', isi: (r) => <KolomMargin r={r} /> },
    { kunci: 'katalog', label: 'Katalog', isi: (r) => (r.marketing_sync.synced
      ? <StatusBadge status="ok" tone="success" label={`${r.marketing_sync.item_count} toko`} />
      : <StatusBadge status="belum" tone="warning" label="Belum" />) },
    { kunci: 'produksi', label: 'Produksi', hp: false, isi: (r) => (r.production.qty_ordered
      ? <span className="tabular-nums">SPK {r.production.qty_ordered} pcs</span>
      : <span className="text-muted-foreground">Belum</span>) },
    { kunci: 'stok', label: 'Stok', rata: 'kanan', hp: false, isi: (r) => <span className="tabular-nums">{r.stock_qty}</span> },
    { kunci: 'lengkap', label: 'Kelengkapan', isi: (r) => (r.gaps.length
      ? <span data-testid={`rnd-gaps-${r.sku}`} title={r.gaps.join('\n')}>
          <StatusBadge status="kurang" tone="warning" label={`${r.gaps.length} kekurangan`} />
        </span>
      : <StatusBadge status="lengkap" tone="success" label="Lengkap" />) },
  ];

  const chips = [
    { key: '', label: 'Semua', count: cocok.length },
    { key: 'broken', label: 'Belum lengkap', count: cocok.length - s.ssot_ok },
  ];

  const det = detail && !detail.loading ? detail : null;
  const layers = (det?.hpp_layers?.layers || []).slice(0, 6);
  const katalog = det?.catalog_items || [];

  return (
    <PageLayout testId="rnd-product-viewer" title="Produk Final"
      subtitle="Barang jadi hasil RnD di master data, beserta sambungannya ke katalog marketing dan SPK produksi."
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input data-testid="rnd-viewer-search" value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="Cari SKU, nama, atau model" className="pl-8" />
        </div>
        <SmartNativeSelect data-testid="rnd-viewer-sort" value={sort} onChange={(e) => setSort(e.target.value)}
          className="w-56" aria-label="Urutan">
          <option value="">Urut nama model</option>
          <option value="margin_asc">Margin paling tipis dulu</option>
          <option value="margin_desc">Margin paling tebal dulu</option>
        </SmartNativeSelect>
        <FilterChips options={chips} value={onlyBroken} onChange={setOnlyBroken} hideWhenEmpty={false}
          testId="rnd-viewer-only-broken" ariaLabel="Kelengkapan" />
      </>}
      tools={<>
        <TombolUnduh namaBerkas="produk-final-rnd" namaLembar="Produk final" baris={shown} testId="rnd-viewer-unduh"
          kolom={[
            { label: 'SKU', nilai: (r) => r.sku },
            { label: 'Nama', nilai: (r) => r.name },
            { label: 'Model', nilai: (r) => r.model_name || '' },
            { label: 'Kategori', nilai: (r) => r.category || '' },
            { label: 'Warna', nilai: (r) => r.color || '' },
            { label: 'Ukuran', nilai: (r) => r.size || '' },
            { label: 'HPP (Rp)', nilai: (r) => Number(hppOf(r)) },
            { label: 'Sumber HPP', nilai: (r) => (r.hpp.layer_count ? `${r.hpp.layer_count} batch` : 'Perkiraan BOM') },
            { label: 'Harga jual (Rp)', nilai: (r) => Number(r.price.selling || 0) },
            { label: 'Margin (Rp)', nilai: (r) => (bisaDihitung(r) ? Number(r.price.margin) : '') },
            { label: 'Margin (%)', nilai: (r) => (bisaDihitung(r) ? persenMargin(r) : '') },
            { label: 'Toko katalog', nilai: (r) => r.marketing_sync.item_count || 0 },
            { label: 'Qty SPK', nilai: (r) => r.production.qty_ordered || 0 },
            { label: 'BOM', nilai: (r) => (r.production.bom_ready ? 'Ada' : 'Belum') },
            { label: 'Stok', nilai: (r) => r.stock_qty },
            { label: 'Kekurangan', nilai: (r) => r.gaps.join('; ') },
          ]} />
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="rnd-viewer-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={!loading && rows.length > 0 && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <StatTile testId="rnd-kpi-total" label="Produk final" value={s.total}
            sub={`${s.ssot_ok} lengkap semua sambungan${q ? ' · sesuai pencarian' : ''}`} />
          <StatTile testId="rnd-kpi-synced" label="Di katalog marketing" value={s.synced}
            accent={s.synced ? 'success' : 'default'} sub={`${s.total - s.synced} belum masuk katalog`} />
          <StatTile testId="rnd-kpi-hpp" label="HPP dari batch nyata" value={s.hpp_real}
            sub={`sisanya perkiraan BOM · ${s.no_bom} tanpa BOM`} />
          <StatTile testId="rnd-kpi-margin" label="Margin rata-rata"
            value={s.margin_avg_pct == null ? '—' : `${s.margin_avg_pct.toLocaleString('id-ID')}%`}
            accent={s.margin_avg_pct == null ? 'muted' : 'default'}
            sub={s.margin_measurable
              ? `dari ${s.margin_measurable} produk berharga & ber-HPP · ${s.margin_thin + s.margin_negative} tipis/minus`
              : `${s.margin_unmeasurable} produk belum punya HPP atau harga jual`} />
        </div>
      )}
      footer={shown.length > 25 && (
        <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />
      )}>
      {loadError && <Notice tone="danger" title="Produk gagal dimuat">{loadError}</Notice>}

      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <div className="space-y-2 p-4">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-12" />)}</div>
        ) : (
          <TabelData kolom={kolom} baris={paged} kunci={(r) => r.material_id} onKlikBaris={openDetail}
            testId="rnd-viewer-table"
            kosong={<EmptyState icon={Boxes} title={rows.length ? 'Tidak ada produk yang cocok' : 'Belum ada produk final'}
              description={rows.length ? 'Ubah kata pencarian atau penyaring.' : 'Produk final muncul setelah model RnD dijadikan barang jadi di Master Produk.'} />} />
        )}
      </GlassCard>

      {baris && (
        <DetailPopup open onClose={() => { setBaris(null); setDetail(null); }} testId="rnd-detail-modal"
          judul={baris.name}
          keterangan={[baris.sku, baris.category, baris.color, baris.size].filter(Boolean).join(' · ')}
          status={baris.gaps.length
            ? <StatusBadge status="kurang" tone="warning" label={`${baris.gaps.length} kekurangan`} />
            : <StatusBadge status="lengkap" tone="success" label="Lengkap" />}>
          {baris.gaps.length > 0 ? (
            <Notice tone="warning" title="Yang belum lengkap">
              <ul className="list-disc space-y-0.5 pl-4">{baris.gaps.map((g) => <li key={g}>{g}</li>)}</ul>
            </Notice>
          ) : (
            <Notice tone="success" title="Lengkap: BOM, HPP batch, katalog, dan produksi" />
          )}

          <div className="flex flex-col gap-4 sm:flex-row">
            {baris.images?.[0] && <Gambar src={baris.images[0]} alt={baris.name} besar />}
            <dl className="min-w-0 flex-1 divide-y divide-[var(--glass-border)]">
              <BarisDetail label="HPP">
                {rp(hppOf(baris))} <span className="text-muted-foreground">({baris.hpp.layer_count ? `${baris.hpp.layer_count} batch` : 'perkiraan BOM'})</span>
              </BarisDetail>
              <BarisDetail label="Harga jual">{baris.price.selling ? rp(baris.price.selling) : 'Belum diisi'}</BarisDetail>
              <BarisDetail label="Margin"><KolomMargin r={baris} /></BarisDetail>
              <BarisDetail label="Produksi">
                {baris.production.qty_ordered ? `SPK ${baris.production.qty_ordered} pcs` : 'Belum pernah masuk SPK'}
                {(baris.production.po_numbers || []).length > 0 && ` · ${baris.production.po_numbers.join(', ')}`}
              </BarisDetail>
              <BarisDetail label="Stok">{baris.stock_qty}</BarisDetail>
            </dl>
          </div>

          {detail?.loading ? (
            <div className="space-y-2">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-8" />)}</div>
          ) : det && (
            <>
              <Seksi judul="HPP batch" alat={layers.length > 0 && (
                <TombolUnduh namaBerkas={`hpp-batch-${baris.sku}`} namaLembar="HPP batch" baris={layers}
                  kolom={[
                    { label: 'Batch / PO', nilai: (l) => l.batch?.po_number || '' },
                    { label: 'Qty masuk', nilai: (l) => Number(l.qty_in || 0) },
                    { label: 'Sisa', nilai: (l) => Number(l.qty_remaining || 0) },
                    { label: 'Biaya per pcs (Rp)', nilai: (l) => Number(l.unit_cost || 0) },
                  ]} />
              )}>
                {layers.length > 0 ? (<>
                  <p className="text-sm text-muted-foreground">
                    {SUMBER_HPP[det.hpp_layers?.source] || 'Sumber tidak diketahui'} · rata-rata {rp(det.hpp_layers?.hpp_fifo_avg)}
                    {' '}· batch terakhir {rp(det.hpp_layers?.hpp_last_batch)}
                  </p>
                  <TabelData baris={layers} testId="rnd-detail-layers"
                    kolom={[
                      { kunci: 'po', label: 'Batch / PO', hp: 'judul', isi: (l) => l.batch?.po_number || '—' },
                      { kunci: 'sisa', label: 'Sisa / masuk', rata: 'kanan', isi: (l) => <span className="tabular-nums">{l.qty_remaining}/{l.qty_in} pcs</span> },
                      { kunci: 'biaya', label: 'Biaya per pcs', rata: 'kanan', isi: (l) => <span className="tabular-nums">{rp(l.unit_cost)}</span> },
                    ]} />
                </>) : (
                  <p className="text-sm text-[hsl(var(--warning-text))]">Belum ada batch masuk gudang — HPP yang terlihat masih perkiraan BOM.</p>
                )}
              </Seksi>

              <Seksi judul={`Katalog marketing (${katalog.length} item)`} alat={katalog.length > 0 && (
                <TombolUnduh namaBerkas={`katalog-${baris.sku}`} namaLembar="Katalog" baris={katalog}
                  kolom={[
                    { label: 'Nama', nilai: (c) => c.name || c.sku },
                    { label: 'Harga (Rp)', nilai: (c) => Number(c.harga_jual || c.unit_price || 0) },
                  ]} />
              )}>
                {katalog.length > 0 ? (
                  <TabelData baris={katalog} testId="rnd-detail-catalog"
                    kolom={[
                      { kunci: 'nama', label: 'Nama di katalog', hp: 'judul', isi: (c) => c.name || c.sku },
                      { kunci: 'harga', label: 'Harga', rata: 'kanan', isi: (c) => <span className="tabular-nums">{rp(c.harga_jual || c.unit_price)}</span> },
                    ]} />
                ) : (
                  <p className="text-sm text-[hsl(var(--warning-text))]">Belum pernah dimasukkan ke katalog toko mana pun.</p>
                )}
              </Seksi>

              <Seksi judul="BOM & model">
                <dl className="divide-y divide-[var(--glass-border)]">
                  <BarisDetail label="BOM">
                    {det.bom?.exists ? `Ada (${det.bom.line_count} baris bahan)`
                      : <span className="text-[hsl(var(--warning-text))]">Belum ada — HPP bahan tidak bisa dihitung</span>}
                  </BarisDetail>
                  <BarisDetail label="Model">{det.model?.name || '—'} ({det.model?.code || 'tanpa kode'})</BarisDetail>
                </dl>
              </Seksi>
            </>
          )}
        </DetailPopup>
      )}
    </PageLayout>
  );
}

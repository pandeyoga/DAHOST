/**
 * Analisa Merchandiser — Portal Manajemen (keputusan owner K-M1..K-M10, 12 Nov 2026).
 *
 * Masalah owner: bahan dibeli dan PO produksi dibuat untuk model yang barang jadinya tidak laku. Layar ini
 * menunjukkan per model: laju jual mingguan, stok perkiraan, WIP, minggu persediaan, kelas, dan saran. Baris
 * dibuka (RowDetail) → rincian per warna/ukuran untuk model itu.
 *
 * Semua angka dari GET /api/merchandiser/analisa (backend `core.merchandiser` — sumber yang sama dengan alat
 * Asisten AI). Layar TIDAK menghitung ulang: hanya menyaring (kelas, cari) dan menampilkan.
 */
import { Fragment, useMemo, useState } from 'react';
import { AlertCircle, AlertTriangle, PackageSearch } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import FilterChips from '@/components/ui/filter-chips';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import PageLayout, { RowDetail, RowToggle } from '../layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';
import { LoadingRows, RefreshButton, SearchBox, Section, useApi } from '../pantau/pantauShared';
import { formatDateID, formatNumber, formatPercent, formatRupiah } from '@/lib/format';

/** Kelas dari backend (`core.merchandiser.KELAS`) → label pendek pil + warna badge. */
export const KELAS_META = {
  mati: { label: 'Mati', tone: 'danger', accent: 'danger' },
  lambat: { label: 'Lambat', tone: 'danger', accent: 'danger' },
  awas: { label: 'Perlu awas', tone: 'warning', accent: 'warning' },
  laris: { label: 'Laris', tone: 'success', accent: 'success' },
  habis: { label: 'Habis', tone: 'success', accent: 'success' },
  sehat: { label: 'Sehat', tone: 'muted', accent: 'default' },
  kosong: { label: 'Tanpa stok & jual', tone: 'muted', accent: 'default' },
};
const URUT_PIL = ['mati', 'lambat', 'awas', 'laris', 'habis', 'sehat'];
const KARTU = ['mati', 'lambat', 'awas', 'laris'];
const PILIHAN_MINGGU = [4, 8, 12];
const TAK_HINGGA = 999; // backend: minggu persediaan "tak terhingga" (stok ada, laju 0)
const KOLOM = 11;

const des = (v) => formatNumber(v, { maximumFractionDigits: 1 });

/** Minggu persediaan: 999 (tak terhingga) dan angka di atas 99 → "> 99". */
export function teksMinggu(v) {
  const x = Number(v);
  if (!Number.isFinite(x)) return '—';
  return x > 99 ? '> 99' : des(x);
}

/** "Toko A (12), Toko B (5)" — toko dengan penjualan terbanyak untuk baris ini. */
export function teksToko(list) {
  return (list || []).map((t) => `${t.toko} (${des(t.pcs)})`).join(', ');
}

/** Arti tiap kelas dalam kalimat, memakai ambang dari server (bisa diubah owner). */
function artiKelas(k, amb, minggu) {
  const a = { laris: des(amb?.laris ?? 3), sehat: des(amb?.sehat ?? 8), awas: des(amb?.awas ?? 16) };
  return {
    mati: `Ada stok, tetapi tidak terjual dalam ${minggu} minggu terakhir.`,
    lambat: `Stok + WIP cukup untuk lebih dari ${a.awas} minggu penjualan.`,
    awas: `Stok + WIP cukup untuk ${a.sehat}–${a.awas} minggu penjualan.`,
    sehat: `Stok + WIP cukup untuk ${a.laris}–${a.sehat} minggu penjualan.`,
    laris: `Stok + WIP habis dalam kurang dari ${a.laris} minggu — perlu tambah stok.`,
    habis: 'Stok dan WIP habis, tetapi masih terjual.',
    kosong: 'Tanpa stok, WIP, dan penjualan.',
  }[k] || '';
}

/** Kolom unduhan yang sama untuk tabel per model dan per varian. */
function kolomMetrik(minggu) {
  return [
    { label: 'Kelas', nilai: (r) => r.kelas_label || KELAS_META[r.kelas]?.label || '' },
    { label: `Terjual ${minggu} minggu (pcs)`, nilai: (r) => Number(r.terjual) || 0 },
    { label: `Terjual ${minggu} minggu sebelumnya (pcs)`, nilai: (r) => Number(r.terjual_sebelumnya) || 0 },
    { label: 'Laju per minggu (pcs)', nilai: (r) => Number(r.laju_mingguan) || 0 },
    { label: 'Stok sistem (pcs)', nilai: (r) => Number(r.stok_sistem) || 0 },
    { label: 'Stok perkiraan (pcs)', nilai: (r) => Number(r.stok_perkiraan) || 0 },
    { label: 'WIP (pcs)', nilai: (r) => Number(r.wip) || 0 },
    { label: 'Minggu persediaan', nilai: (r) => (Number(r.minggu_persediaan) >= TAK_HINGGA ? '> 99' : Number(r.minggu_persediaan) || 0) },
    { label: 'Sell-through (%)', nilai: (r) => (r.sell_through_persen == null ? '' : Number(r.sell_through_persen)) },
    { label: 'Nilai stok HPP (Rp)', nilai: (r) => Number(r.nilai_stok_hpp) || 0 },
    { label: 'Toko terlaris', nilai: (r) => teksToko(r.toko_terlaris) },
    { label: 'Saran', nilai: (r) => r.saran || '' },
  ];
}

function BadgeKelas({ r }) {
  const meta = KELAS_META[r.kelas] || { label: r.kelas || '—', tone: 'muted' };
  return <StatusBadge label={r.kelas_label || meta.label} tone={meta.tone} testId="merch-kelas-badge" />;
}

/** Tujuh sel angka yang sama di tabel per model dan per varian. */
function SelMetrik({ r, minggu }) {
  const mp = Number(r.minggu_persediaan);
  return (
    <>
      <TableCell className="text-right tabular-nums" title={`Terjual ${des(r.terjual)} pcs dalam ${minggu} minggu; ${minggu} minggu sebelumnya ${des(r.terjual_sebelumnya)} pcs`}>
        {des(r.laju_mingguan)}
      </TableCell>
      <TableCell className="text-right tabular-nums" title={`Stok sistem ${des(r.stok_sistem)} pcs`}>{des(r.stok_perkiraan)}</TableCell>
      <TableCell className="text-right tabular-nums">{des(r.wip)}</TableCell>
      <TableCell className="text-right tabular-nums" data-testid="merch-minggu-persediaan"
        title={mp >= TAK_HINGGA ? 'Tidak ada penjualan dalam periode ini' : undefined}>
        {teksMinggu(mp)}
      </TableCell>
      <TableCell className="text-right tabular-nums">{formatPercent(r.sell_through_persen, 1)}</TableCell>
      <TableCell className="text-right tabular-nums">{formatNumber(r.nilai_stok_hpp)}</TableCell>
      <TableCell className="min-w-[10rem] whitespace-normal text-xs">{teksToko(r.toko_terlaris) || '—'}</TableCell>
    </>
  );
}

function KepalaMetrik() {
  return (
    <>
      <TableHead className="text-right">Laju/minggu</TableHead>
      <TableHead className="text-right">Stok perkiraan</TableHead>
      <TableHead className="text-right">WIP</TableHead>
      <TableHead className="text-right">Minggu persediaan</TableHead>
      <TableHead className="text-right" title="Terjual ÷ (terjual + stok perkiraan)">Sell-through</TableHead>
      <TableHead className="text-right">Nilai stok (Rp)</TableHead>
      <TableHead>Toko terlaris</TableHead>
    </>
  );
}

/** Rincian satu model per warna/ukuran — dibuka di bawah barisnya. */
function RincianVarian({ model, minggu, toko }) {
  const q = new URLSearchParams({ tingkat: 'varian', model_id: model.model_id, minggu: String(minggu) });
  if (toko) q.set('toko', toko);
  const { data, loading, error } = useApi(`/merchandiser/analisa?${q}`);
  const baris = data?.baris || [];
  const nama = model.kode || model.nama || 'model';
  return (
    <div className="space-y-3" data-testid="merch-rincian">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1 space-y-1 text-sm">
          {model.saran && <p data-testid="merch-saran"><span className="font-medium">Saran:</span> {model.saran}</p>}
          <p className="text-xs text-muted-foreground">
            Terjual {des(model.terjual)} pcs dalam {minggu} minggu terakhir · {des(model.terjual_sebelumnya)} pcs pada {minggu} minggu
            sebelumnya · stok sistem {des(model.stok_sistem)} pcs.
          </p>
        </div>
        <TombolUnduh namaBerkas={`merchandiser-${nama}`} namaLembar="Per warna dan ukuran" baris={baris}
          testId="merch-rincian-unduh"
          kolom={[
            { label: 'Kode model', nilai: () => model.kode || '' },
            { label: 'Nama model', nilai: () => model.nama || '' },
            { label: 'Warna', nilai: (r) => r.warna || '' },
            { label: 'Ukuran', nilai: (r) => r.ukuran || '' },
            { label: 'SKU', nilai: (r) => r.sku || '' },
            ...kolomMetrik(minggu),
          ]} />
      </div>
      {error && <Notice tone="danger" icon={AlertCircle}>{error}</Notice>}
      {loading && !data ? <LoadingRows rows={3} /> : (
        <Table data-testid="merch-varian-tabel" className="md:min-w-0">
          <TableHeader><TableRow>
            <TableHead>Warna</TableHead><TableHead>Ukuran</TableHead><TableHead>SKU</TableHead><TableHead>Kelas</TableHead>
            <KepalaMetrik />
          </TableRow></TableHeader>
          <TableBody>
            {baris.length === 0 && (
              <TableRow className="hover:bg-transparent">
                <TableCell colSpan={KOLOM} className="p-0 [&>div]:py-6">
                  <EmptyState icon={PackageSearch} title="Belum ada rincian warna dan ukuran"
                    description="Rincian muncul bila varian model ini punya stok, WIP, atau penjualan." />
                </TableCell>
              </TableRow>
            )}
            {baris.map((r, i) => (
              <TableRow key={`${r.sku}|${r.warna}|${r.ukuran}|${i}`} data-testid="merch-varian-baris">
                <TableCell className="whitespace-nowrap">{r.warna || '—'}</TableCell>
                <TableCell className="whitespace-nowrap">{r.ukuran || '—'}</TableCell>
                <TableCell className="whitespace-nowrap text-xs text-muted-foreground">{r.sku || '—'}</TableCell>
                <TableCell><BadgeKelas r={r} /></TableCell>
                <SelMetrik r={r} minggu={minggu} />
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

export default function MerchandiserModule({ onNavigate }) {
  const [kelas, setKelas] = useState('');
  const [minggu, setMinggu] = useState('');
  const [toko, setToko] = useState('');
  const [cari, setCari] = useState('');
  const [buka, setBuka] = useState('');
  const [versi, setVersi] = useState(0);

  const q = new URLSearchParams({ tingkat: 'model' });
  if (minggu) q.set('minggu', minggu);
  if (toko) q.set('toko', toko);
  const { data, loading, error, reload } = useApi(`/merchandiser/analisa?${q}`);
  const akun = useApi('/marketing/accounts');

  const daftarToko = useMemo(() => {
    const list = Array.isArray(akun.data) ? akun.data : (akun.data?.accounts || []);
    return list
      .filter((a) => a && a.id && a.status !== 'archived')
      .map((a) => ({ id: a.id, nama: a.account_name || a.name || a.code || a.id }))
      .sort((x, y) => String(x.nama).localeCompare(String(y.nama), 'id'));
  }, [akun.data]);

  const semua = useMemo(() => data?.baris || [], [data]);
  const ringkasan = data?.ringkasan || {};
  const cakupan = data?.cakupan || {};
  const periode = data?.periode || {};
  const nMinggu = Number(periode.minggu) || Number(minggu) || 4;
  const hitung = (k) => Number(ringkasan[k]?.baris ?? semua.filter((r) => r.kelas === k).length) || 0;

  const rows = useMemo(() => {
    const kata = cari.trim().toLowerCase();
    return semua.filter((r) => (!kelas || r.kelas === kelas)
      && (!kata || `${r.kode || ''} ${r.nama || ''}`.toLowerCase().includes(kata)));
  }, [semua, kelas, cari]);
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(rows, 25);

  const pilihanMinggu = PILIHAN_MINGGU.includes(nMinggu) ? PILIHAN_MINGGU : [...PILIHAN_MINGGU, nMinggu].sort((a, b) => a - b);
  const pil = [
    { key: '', label: 'Semua', count: semua.length },
    ...URUT_PIL.map((k) => ({ key: k, label: KELAS_META[k].label, count: hitung(k) })),
    ...(hitung('kosong') > 0 ? [{ key: 'kosong', label: KELAS_META.kosong.label, count: hitung('kosong') }] : []),
  ];
  const adaKartu = KARTU.some((k) => hitung(k) > 0);
  const catatan = cakupan.catatan || [];
  const pcsTanpaModel = Number(cakupan.pcs_tanpa_model) || 0;
  const skuTanpa = (cakupan.sku_tanpa_model || []).slice(0, 5);

  const gantiSaring = (fn) => (v) => { fn(v); setBuka(''); };
  const muatUlang = () => { reload(); setVersi((v) => v + 1); };
  const bukaJembatan = () => {
    if (onNavigate) onNavigate('sku-bridge');
    else window.dispatchEvent(new CustomEvent('erp:navigate-module', { detail: { moduleId: 'sku-bridge' } }));
  };

  return (
    <PageLayout
      testId="merch-page"
      title="Analisa Merchandiser"
      subtitle="Laju jual, stok, dan barang yang sedang dijahit per model — supaya bahan dan produksi hanya untuk model yang laku."
      filters={<>
        <SearchBox value={cari} onChange={setCari} placeholder="Cari kode atau nama model" testId="merch-cari" />
        <SmartNativeSelect value={toko} onChange={(e) => gantiSaring(setToko)(e.target.value)} className="h-9 w-full sm:w-56"
          aria-label="Toko" data-testid="merch-toko">
          <option value="">Semua toko</option>
          {daftarToko.map((t) => <option key={t.id} value={t.id}>{t.nama}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={String(minggu || nMinggu)} onChange={(e) => gantiSaring(setMinggu)(e.target.value)}
          searchable={false} className="h-9 w-40" aria-label="Periode laju jual" data-testid="merch-minggu">
          {pilihanMinggu.map((m) => <option key={m} value={String(m)}>{`Laju ${m} minggu`}</option>)}
        </SmartNativeSelect>
        <FilterChips value={kelas} onChange={gantiSaring(setKelas)} testId="merch-kelas" ariaLabel="Kelas model" options={pil} />
      </>}
      tools={<>
        <TombolUnduh namaBerkas="analisa-merchandiser" namaLembar="Per model" baris={rows} testId="merch-unduh"
          kolom={[
            { label: 'Kode', nilai: (r) => r.kode || '' },
            { label: 'Nama', nilai: (r) => r.nama || '' },
            { label: 'Jumlah varian', nilai: (r) => Number(r.varian) || 0 },
            ...kolomMetrik(nMinggu),
          ]} />
        <RefreshButton onClick={muatUlang} loading={loading} testId="merch-muat-ulang" />
      </>}
      summary={adaKartu && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="merch-ringkasan">
          {KARTU.map((k) => {
            const s = ringkasan[k] || {};
            return (
              <StatTile key={k} testId={`merch-kartu-${k}`} label={KELAS_META[k].label} value={formatNumber(hitung(k))}
                suffix="model" accent={KELAS_META[k].accent}
                sub={`${des(s.stok)} pcs stok · ${formatRupiah(s.nilai_stok_hpp)} (HPP)`}
                hint={`${artiKelas(k, data?.ambang, nMinggu)} Klik untuk menyaring.`}
                onClick={() => gantiSaring(setKelas)(kelas === k ? '' : k)} />
            );
          })}
        </div>
      )}
      footer={rows.length > pageSize && (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />
      )}
    >
      {error && <Notice tone="danger" icon={AlertCircle} testId="merch-galat">{error}</Notice>}
      {catatan.length > 0 && (
        <Notice tone="warning" icon={AlertTriangle} testId="merch-cakupan"
          action={pcsTanpaModel > 0 && (
            <Button variant="link" size="sm" className="h-auto p-0" onClick={bukaJembatan} data-testid="merch-buka-jembatan">
              Buka Jembatan SKU
            </Button>
          )}>
          <div className="space-y-1">
            {catatan.map((c) => <p key={c}>{c}</p>)}
            {pcsTanpaModel > 0 && skuTanpa.length > 0 && (
              <p className="text-xs">SKU terbanyak yang belum terhubung: {skuTanpa.map((s) => `${s.sku} (${des(s.pcs)} pcs)`).join(', ')}.</p>
            )}
          </div>
        </Notice>
      )}
      {data && (
        <p className="text-xs text-muted-foreground" data-testid="merch-sumber">
          Laju jual {nMinggu} minggu: {formatDateID(periode.dari)} – {formatDateID(periode.sampai)}, dibanding{' '}
          {formatDateID(periode.pembanding?.dari)} – {formatDateID(periode.pembanding?.sampai)}.
          {cakupan.persen_pcs_tertaut != null && ` ${formatPercent(cakupan.persen_pcs_tertaut, 1)} pcs penjualan sudah terhubung ke model.`}
          {data.sumber ? ` ${data.sumber}` : ''}
        </p>
      )}
      <Section testId="merch-bagian-tabel">
        {loading && !data ? <LoadingRows /> : (
          <Table data-testid="merch-tabel" className="md:min-w-0">
            <TableHeader><TableRow>
              <TableHead className="w-10" />
              <TableHead>Kode</TableHead><TableHead>Nama</TableHead><TableHead>Kelas</TableHead>
              <KepalaMetrik />
            </TableRow></TableHeader>
            <TableBody>
              {rows.length === 0 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={KOLOM} className="p-0 [&>div]:py-8">
                    {semua.length === 0
                      ? <EmptyState icon={PackageSearch} title="Belum ada model untuk dianalisa" testId="merch-kosong"
                          description="Model muncul setelah ada stok barang jadi, WIP, atau penjualan dalam periode ini." />
                      : <EmptyState icon={PackageSearch} title="Tidak ada model yang cocok" testId="merch-kosong"
                          description="Ubah pilihan kelas atau kata pencarian." />}
                  </TableCell>
                </TableRow>
              )}
              {paged.map((r) => {
                const id = r.kode || r.model_id;
                const isOpen = buka === r.model_id;
                return (
                  <Fragment key={r.model_id}>
                    <TableRow data-testid={`merch-baris-${id}`} className={isOpen ? 'bg-[hsl(var(--primary)/0.06)]' : ''}>
                      <TableCell>
                        <RowToggle open={isOpen} onClick={() => setBuka(isOpen ? '' : r.model_id)}
                          label="Lihat per warna dan ukuran" testId={`merch-buka-${id}`} />
                      </TableCell>
                      <TableCell className="font-medium whitespace-nowrap">{r.kode || '—'}</TableCell>
                      <TableCell className="min-w-[10rem] whitespace-normal">
                        {r.nama || '—'}
                        <div className="text-xs text-muted-foreground">{formatNumber(r.varian)} varian</div>
                      </TableCell>
                      <TableCell><BadgeKelas r={r} /></TableCell>
                      <SelMetrik r={r} minggu={nMinggu} />
                    </TableRow>
                    {isOpen && (
                      <RowDetail colSpan={KOLOM} testId={`merch-rincian-${id}`}>
                        <RincianVarian key={versi} model={r} minggu={nMinggu} toko={toko} />
                      </RowDetail>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        )}
      </Section>
    </PageLayout>
  );
}

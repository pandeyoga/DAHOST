/**
 * Pantau Produksi › Per produk — produk apa, warna/ukuran apa, di CMT mana, berapa pcs, sejak kapan
 * (permintaan owner 16 Nov 2026: pengganti lembar Google Sheet "SISA POTONGAN"). Baris utama = produk (model untuk
 * PO internal, artikel katalog klien untuk PO maklon); buka baris (RowDetail) → per warna × ukuran × CMT × kode
 * potongan. Pita umur sesuai SOP lembar: 0–7 hari hijau, 8–14 hari kuning, lebih dari 14 hari merah.
 * Sumber: /api/pantau/produk (core.pantau_produksi.per_produk — baris PO yang sama dengan tab Per vendor & Kejar CMT).
 */
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Fragment, useEffect, useMemo, useState } from 'react';
import { AlertCircle, AlertTriangle, Shirt } from 'lucide-react';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import FilterChips from '@/components/ui/filter-chips';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { RowDetail, RowToggle } from '../layout/PageLayout';
import { PageLayoutSatuBaris } from '../engine/DataTable';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';
import { formatDateID } from '@/lib/format';
import { LoadingRows, RefreshButton, SearchBox, Section, n, portalBusinessType, useApi } from './pantauShared';

/** Pita umur potongan di CMT (hari sejak kirim pertama) — kunci sama dengan backend `UMUR_BUCKETS`. */
const UMUR_META = {
  '0-7': { label: '0–7 hari', tone: 'success' },
  '8-14': { label: '8–14 hari', tone: 'warning' },
  lebih14: { label: 'Lebih dari 14 hari', tone: 'danger' },
};
const KEADAAN = [
  { key: 'di_cmt', label: 'Masih di CMT' },
  { key: 'selesai', label: 'Sudah selesai' },
  { key: 'semua', label: 'Semua' },
];

function useDebounced(value, ms = 350) {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}

function Umur({ days, bucket }) {
  if (days == null || !UMUR_META[bucket]) return <span className="text-muted-foreground">—</span>;
  return <StatusBadge label={`${n(days)} hari`} tone={UMUR_META[bucket].tone} />;
}

export default function PerProdukTab(props) {
  const bt = portalBusinessType(props);
  const maklon = bt === 'maklon';
  const [search, setSearch] = useState('');
  const q = useDebounced(search.trim());
  const [vendor, setVendor] = useState('');
  const [klien, setKlien] = useState('');
  const [umur, setUmur] = useState('');
  const [keadaan, setKeadaan] = useState('di_cmt');
  const [open, setOpen] = useState('');
  const path = `/pantau/produk?business_type=${bt}&keadaan=${keadaan}${umur ? `&umur=${umur}` : ''}`
    + `${vendor ? `&vendor_id=${encodeURIComponent(vendor)}` : ''}${maklon && klien ? `&klien_id=${encodeURIComponent(klien)}` : ''}`
    + `${q ? `&search=${encodeURIComponent(q)}` : ''}`;
  const { data, loading, error, reload } = useApi(path);
  const rows = useMemo(() => data?.rows || [], [data]);
  const s = data?.summary || {};
  const kc = data?.keadaan_counts || {};
  const uc = data?.umur_counts || {};
  const flat = useMemo(() => rows.flatMap((p) => p.rows || []), [rows]);
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(rows, 25);
  useEffect(() => { if (q && rows.length === 1) setOpen(rows[0].produk_key); }, [q, rows]);
  const COLS = 11;
  const kosong = keadaan === 'selesai'
    ? { title: 'Belum ada produk yang selesai di CMT', description: 'Baris yang seluruh potongannya sudah disetor dan selesai QC akan muncul di sini.' }
    : { title: 'Tidak ada potongan di CMT', description: 'Produk yang potongannya sudah dikirim ke CMT dan belum disetor akan muncul di sini.' };

  return (
    <PageLayoutSatuBaris
      testId="pantau-produk"
      title="Per produk"
      filters={<>
        <SearchBox value={search} onChange={setSearch} placeholder="Cari produk, kode potongan, SKU, atau PO…" testId="pantau-produk-search" />
        <SmartNativeSelect value={vendor} onChange={(e) => setVendor(e.target.value)} className="h-9 w-full sm:w-52" aria-label="Vendor CMT" data-testid="pantau-produk-vendor">
          <option value="">Semua CMT</option>
          {(data?.vendors || []).map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
        </SmartNativeSelect>
        {maklon && (
          <SmartNativeSelect value={klien} onChange={(e) => setKlien(e.target.value)} className="h-9 w-full sm:w-52" aria-label="Klien" data-testid="pantau-produk-klien">
            <option value="">Semua klien</option>
            {(data?.klien || []).map((k) => <option key={k.id} value={k.id}>{k.name}</option>)}
          </SmartNativeSelect>
        )}
        <FilterChips value={keadaan} onChange={setKeadaan} testId="pantau-produk-keadaan" ariaLabel="Keadaan potongan"
          options={KEADAAN.map((k) => ({ key: k.key, label: k.label, count: kc[k.key] || 0 }))} />
        <FilterChips value={umur} onChange={setUmur} testId="pantau-produk-umur" ariaLabel="Umur di CMT" hideWhenEmpty={!umur}
          options={[{ key: '', label: 'Semua umur', count: Object.values(uc).reduce((a, b) => a + b, 0) },
            ...Object.entries(UMUR_META).map(([k, m]) => ({ key: k, label: m.label, count: uc[k] || 0 }))]} />
      </>}
      tools={<><TombolUnduh namaBerkas="sisa-potongan-per-produk" namaLembar="Sisa potongan" baris={flat} kolom={[
          { label: 'Produk', nilai: (r) => r.produk_nama || '' }, { label: 'Kode produk', nilai: (r) => r.produk_kode || '' },
          ...(maklon ? [{ label: 'Klien', nilai: (r) => r.klien_nama || '' }] : []),
          { label: 'Kode potongan', nilai: (r) => r.serial_number || '' }, { label: 'PO', nilai: (r) => r.po_number || '' },
          { label: 'CMT', nilai: (r) => r.vendor_name || '' }, { label: 'Warna', nilai: (r) => r.color || '' },
          { label: 'Ukuran', nilai: (r) => r.size || '' }, { label: 'SKU', nilai: (r) => r.sku || '' },
          { label: 'Tanggal kirim', nilai: (r) => formatDateID(r.tanggal_kirim, { fallback: '' }) },
          { label: 'Dikirim', nilai: (r) => Number(r.dikirim) || 0 }, { label: 'Kiriman tambahan', nilai: (r) => Number(r.dikirim_tambahan) || 0 },
          { label: 'Setor lolos QC', nilai: (r) => Number(r.setor) || 0 }, { label: 'Ditolak QC', nilai: (r) => Number(r.reject) || 0 },
          { label: 'Sedang QC', nilai: (r) => Number(r.sedang_qc) || 0 }, { label: 'Sisa di CMT', nilai: (r) => Number(r.sisa) || 0 },
          { label: 'Umur (hari)', nilai: (r) => (r.umur_hari == null ? '' : Number(r.umur_hari)) },
          { label: 'Lebih setor', nilai: (r) => Number(r.lebih_setor) || 0 },
        ]} />
        <RefreshButton onClick={reload} loading={loading} testId="pantau-produk-refresh" /></>}
      summary={<>
        {error && <Notice tone="danger" icon={AlertCircle}>{error}</Notice>}
        {s.lebih_setor_baris > 0 && (
          <Notice tone="warning" icon={AlertTriangle} testId="pantau-produk-lebih-setor"
            title={`${n(s.lebih_setor_baris)} baris lebih setor (${n(s.lebih_setor_pcs)} pcs)`}>
            Setoran CMT melebihi potongan yang dikirim. Periksa kiriman dan penerimaannya{keadaan === 'di_cmt' ? ' — barisnya ada di pilihan "Sudah selesai".' : '.'}
          </Notice>
        )}
        {rows.length > 0 && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="pantau-produk-kpi">
            <StatTile label="Pcs di CMT" value={n(s.sisa)} sub="dikirim − setoran selesai QC − sedang QC" testId="kpi-produk-sisa" />
            <StatTile label="Produk" value={n(s.produk)} sub={`${n(s.batch)} batch kode potongan`} testId="kpi-produk-produk" />
            <StatTile label="CMT" value={n(s.cmt)} sub="vendor yang masih memegang potongan" testId="kpi-produk-cmt" />
            <StatTile label="Batch lebih dari 14 hari" value={n(s.batch_lama)} accent={s.batch_lama > 0 ? 'danger' : 'default'}
              sub="sejak kirim pertama, masih ada sisa" testId="kpi-produk-lama" />
          </div>
        )}
        {data && <p className="text-xs text-muted-foreground">Sisa di CMT sama dengan kolom Di CMT di tab Per vendor CMT dan Kejar CMT. Umur = hari sejak potongan pertama dikirim (saldo awal cutoff memakai tanggal surat jalannya).</p>}
      </>}
      footer={rows.length > pageSize && <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />}
    >
      <Section>
        {loading && !data ? <LoadingRows /> : (
          <Table data-testid="pantau-produk-table">
            <TableHeader><TableRow>
              <TableHead className="w-10" /><TableHead>Produk</TableHead><TableHead className="text-right">Sisa di CMT</TableHead>
              <TableHead className="text-right">CMT</TableHead><TableHead className="text-right">Batch</TableHead>
              <TableHead>Kirim tertua</TableHead><TableHead>Umur</TableHead>
              <TableHead className="text-right">Dikirim</TableHead><TableHead className="text-right">Setor lolos QC</TableHead>
              <TableHead className="text-right">Ditolak QC</TableHead><TableHead className="text-right">Sedang QC</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {rows.length === 0 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={COLS} className="p-0 [&>div]:py-8"><EmptyState icon={Shirt} title={kosong.title} description={kosong.description} /></TableCell>
                </TableRow>
              )}
              {paged.map((p) => {
                const isOpen = open === p.produk_key;
                const tid = p.produk_kode || p.produk_nama;
                return (
                  <Fragment key={p.produk_key}>
                    <TableRow data-testid={`pantau-produk-row-${tid}`}>
                      <TableCell><RowToggle open={isOpen} onClick={() => setOpen(isOpen ? '' : p.produk_key)} label="Lihat warna, ukuran, dan CMT" testId={`pantau-produk-toggle-${tid}`} /></TableCell>
                      <TableCell className="font-medium">{p.produk_nama}
                        {(p.produk_kode || p.klien?.length > 0) && (
                          <div className="text-xs text-muted-foreground">{[p.produk_kode, ...(p.klien || [])].filter(Boolean).join(' · ')}</div>
                        )}
                        {p.baris_lebih_setor > 0 && <StatusBadge label={`Lebih setor ${n(p.lebih_setor)} pcs`} tone="warning" />}
                      </TableCell>
                      <TableCell className="text-right tabular-nums font-semibold" data-testid="pantau-produk-sisa">{n(p.sisa)}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(p.cmt_count)}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(p.batch_count)}</TableCell>
                      <TableCell className="whitespace-nowrap">{p.tanggal_kirim_tertua ? formatDateID(p.tanggal_kirim_tertua) : '—'}</TableCell>
                      <TableCell><Umur days={p.umur_hari} bucket={p.umur} /></TableCell>
                      <TableCell className="text-right tabular-nums">{n(p.dikirim)}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(p.setor)}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(p.reject)}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(p.sedang_qc)}</TableCell>
                    </TableRow>
                    {isOpen && (
                      <RowDetail colSpan={COLS} testId={`pantau-produk-detail-${tid}`}>
                        <BarisProduk rows={p.rows || []} />
                      </RowDetail>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        )}
      </Section>
    </PageLayoutSatuBaris>
  );
}

/** Rincian satu produk: per warna × ukuran × CMT × kode potongan (satu baris PO). */
function BarisProduk({ rows }) {
  return (
    <Table data-testid="pantau-produk-rincian">
      <TableHeader><TableRow>
        <TableHead>Kode potongan</TableHead><TableHead>PO</TableHead><TableHead>CMT</TableHead>
        <TableHead>Warna</TableHead><TableHead>Ukuran</TableHead><TableHead>Tanggal kirim</TableHead>
        <TableHead className="text-right">Dikirim</TableHead><TableHead className="text-right">Setor lolos QC</TableHead>
        <TableHead className="text-right">Ditolak QC</TableHead><TableHead className="text-right">Sedang QC</TableHead>
        <TableHead className="text-right">Sisa di CMT</TableHead><TableHead>Umur</TableHead>
      </TableRow></TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.po_item_id} data-testid={`pantau-produk-baris-${r.serial_number || r.po_item_id}`}>
            <TableCell className="font-medium whitespace-nowrap">{r.serial_number || '—'}
              {r.sku ? <div className="text-xs text-muted-foreground">{r.sku}</div> : null}</TableCell>
            <TableCell className="whitespace-nowrap">{r.po_number || '—'}</TableCell>
            <TableCell>{r.vendor_name || '—'}</TableCell>
            <TableCell>{r.color || '—'}</TableCell>
            <TableCell>{r.size || '—'}</TableCell>
            <TableCell className="whitespace-nowrap">{r.tanggal_kirim ? formatDateID(r.tanggal_kirim) : '—'}</TableCell>
            <TableCell className="text-right tabular-nums">{n(r.dikirim)}
              {r.dikirim_tambahan > 0 && <div className="text-xs text-muted-foreground">+{n(r.dikirim_tambahan)} tambahan</div>}</TableCell>
            <TableCell className="text-right tabular-nums">{n(r.setor)}</TableCell>
            <TableCell className="text-right tabular-nums">{n(r.reject)}</TableCell>
            <TableCell className="text-right tabular-nums">{n(r.sedang_qc)}</TableCell>
            <TableCell className="text-right tabular-nums font-semibold">{n(r.sisa)}
              {r.lebih_setor > 0 && <div><StatusBadge label={`Lebih setor ${n(r.lebih_setor)}`} tone="warning" /></div>}
              {r.klaim_belum_sampai > 0 && <div className="text-xs text-muted-foreground">klaim CMT belum sampai {n(r.klaim_belum_sampai)}</div>}
            </TableCell>
            <TableCell><Umur days={r.umur_hari} bucket={r.umur} /></TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

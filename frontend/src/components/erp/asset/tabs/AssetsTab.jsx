/**
 * AssetsTab — daftar aset (cari, saring status, halaman server).
 *
 * Standar UI/UX v2 (8 Nov 2026): penyaring satu baris (cari 16 rem + status), tabel TabelData (kartu ringkas
 * di HP), klik baris → detail popup, unduh Excel/CSV SEMUA aset hasil saringan (bukan hanya halaman ini),
 * paginasi di kaki. Tombol "Cari" dihapus: daftar sudah dimuat ulang otomatis saat kata dicari/status diganti
 * (Enter dan ikon muat ulang tetap ada).
 */
import { Plus, RefreshCw, Search, MoreHorizontal, ScanLine, Upload, ShoppingCart, TrendingDown } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PaginationLite from '@/components/ui/pagination-lite';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import PageLayout from '../../layout/PageLayout';
import { EmptyState } from '../../moduleAtoms';
import { KALIMAT_PENYUSUTAN, STATUS_CONFIG, STATUS_FILTER_OPTIONS } from '../constants';
import { angka, ambilSemuaHalaman, fmtCurrency, useHP } from '../utils';
import { StatusBadge } from '../components/StatusBadge';

/**
 * Tombol halaman aset: 1 tombol utama "Tambah aset" + menu "Lainnya" (pindai, impor, permintaan pengadaan,
 * tautan penyusutan). Dulu enam tombol berderet di kepala halaman.
 * 2026-11-08 (keputusan owner): "Posting penyusutan massal" selalu ditolak server sejak K18 → diganti tautan ke
 * Keuangan › Aset Tetap. `onBukaPenyusutan` kosong (pengguna tanpa akses Portal Keuangan) = hanya keterangan.
 */
export function AksiAset({ onTambahAset, onScan, onImpor, onBuatPR, onBukaPenyusutan }) {
  return (
    <>
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" data-testid="asset-more-btn"><MoreHorizontal />Lainnya</Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={onScan} data-testid="scan-asset-btn">
            <ScanLine className="mr-2 h-4 w-4" />Pindai label aset
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={onImpor} data-testid="bulk-import-btn">
            <Upload className="mr-2 h-4 w-4" />Impor aset dari CSV/Excel
          </DropdownMenuItem>
          {onBuatPR && (
            <DropdownMenuItem onSelect={onBuatPR} data-testid="add-pr-btn">
              <ShoppingCart className="mr-2 h-4 w-4" />Buat permintaan pengadaan
            </DropdownMenuItem>
          )}
          <DropdownMenuItem onSelect={onBukaPenyusutan || undefined} disabled={!onBukaPenyusutan}
            className="items-start" data-testid="asset-depr-keuangan-btn">
            <TrendingDown className="mr-2 mt-0.5 h-4 w-4" />
            <span className="flex flex-col">
              <span>{onBukaPenyusutan ? 'Buka penyusutan di Keuangan' : 'Penyusutan diposting oleh Keuangan'}</span>
              <span className="text-xs text-muted-foreground">{KALIMAT_PENYUSUTAN}</span>
            </span>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <Button onClick={onTambahAset} data-testid="add-asset-btn"><Plus />Tambah aset</Button>
    </>
  );
}

const nilaiBuku = (a) => (a.purchase_cost || 0) - (a.accumulated_depreciation || 0);

export function AssetsTab({
  assetSearch, setAssetSearch,
  assetStatus, setAssetStatus,
  assets, loading, assetPagination,
  loadAssets, fetchAssetPage, onAssetClick,
  onTambahAset, onScan, onImpor, onBukaPenyusutan,
}) {
  const halaman = assetPagination?.page || 1;
  const hp = useHP();
  const kolomUnduh = [
    { label: 'No. aset', nilai: (a) => a.asset_number },
    { label: 'Nama', nilai: (a) => a.name },
    { label: 'Kategori', nilai: (a) => a.category_name || '' },
    { label: 'Harga beli', nilai: (a) => angka(a.purchase_cost) },
    { label: 'Akumulasi penyusutan', nilai: (a) => angka(a.accumulated_depreciation || 0) },
    { label: 'Nilai buku', nilai: (a) => angka(nilaiBuku(a)) },
    { label: 'Status', nilai: (a) => STATUS_CONFIG[a.status]?.label || a.status },
    { label: 'Ditugaskan ke', nilai: (a) => a.assigned_to_name || '' },
    { label: 'Lokasi', nilai: (a) => a.location || '' },
    { label: 'Departemen', nilai: (a) => a.department || '' },
  ];

  // Alat dibungkus satu kelompok supaya Unduh & muat ulang tidak terpisah baris di HP.
  const alat = (
    <div className="flex items-center gap-2">
      <TombolUnduh namaBerkas="daftar-aset" namaLembar="Aset" baris={assets} kolom={kolomUnduh} testId="asset-unduh"
        ambilSemua={() => ambilSemuaHalaman(fetchAssetPage)} />
      <Button variant="outline" size="icon" onClick={() => loadAssets(halaman)} disabled={loading}
        title="Muat ulang" aria-label="Muat ulang" data-testid="asset-search-btn">
        <RefreshCw className={loading ? 'animate-spin' : ''} />
      </Button>
    </div>
  );

  return (
    <PageLayout testId="asset-list" title="Aset" subtitle="Daftar aset perusahaan."
      actions={<AksiAset onTambahAset={onTambahAset} onScan={onScan} onImpor={onImpor} onBukaPenyusutan={onBukaPenyusutan} />}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder="Cari nama, nomor, no. seri" className="pl-8" value={assetSearch}
            onChange={e => setAssetSearch(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && loadAssets()}
            data-testid="asset-search-input" />
        </div>
        <SmartNativeSelect value={assetStatus} onChange={e => setAssetStatus(e.target.value)} searchable={false}
          className="w-44" aria-label="Status aset" data-testid="asset-status-select">
          {STATUS_FILTER_OPTIONS.map(o => <option key={o.value || 'semua'} value={o.value}>{o.label}</option>)}
        </SmartNativeSelect>
        {hp && alat}
      </>}
      tools={hp ? null : alat}
      footer={assetPagination?.total > 0 ? (
        <PaginationLite page={halaman} totalPages={assetPagination.total_pages} total={assetPagination.total}
          pageSize={assetPagination.page_size || 20} onPageChange={(p) => loadAssets(p)} />
      ) : null}>
      {loading && assets.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat aset…</p>
      ) : (
        <TabelData baris={assets} onKlikBaris={onAssetClick} testId="asset-table"
          kosong={<EmptyState
            title={assetSearch || assetStatus ? 'Tidak ada aset yang cocok' : 'Belum ada aset terdaftar'}
            description={assetSearch || assetStatus ? 'Ubah kata pencarian atau pilihan status.'
              : 'Daftarkan aset lewat tombol "Tambah aset", atau impor dari berkas CSV/Excel.'} />}
          kolom={[
            { kunci: 'no', label: 'No. aset', hp: 'keterangan', isi: (a) => <span className="tabular-nums text-muted-foreground">{a.asset_number}</span> },
            { kunci: 'nama', label: 'Nama', hp: 'judul', isi: (a) => <span className="font-medium">{a.name}</span> },
            { kunci: 'kategori', label: 'Kategori', isi: (a) => a.category_name || '—' },
            { kunci: 'harga', label: 'Harga beli', rata: 'kanan', isi: (a) => <span className="tabular-nums">{fmtCurrency(a.purchase_cost)}</span> },
            { kunci: 'nbv', label: 'Nilai buku', rata: 'kanan', isi: (a) => <span className="tabular-nums">{fmtCurrency(nilaiBuku(a))}</span> },
            { kunci: 'status', label: 'Status', isi: (a) => <StatusBadge status={a.status} configMap={STATUS_CONFIG} /> },
            { kunci: 'pemegang', label: 'Ditugaskan ke', isi: (a) => a.assigned_to_name || '—' },
          ]} />
      )}
    </PageLayout>
  );
}

/**
 * CategoriesTab — kategori aset: umur manfaat, metode penyusutan, akun di Bagan Akun.
 *
 * Standar UI/UX v2 (8 Nov 2026): tabel TabelData (kepala tidak lagi HURUF BESAR, kode akun tanpa warna
 * hijau/kuning), tombol "Ubah" per baris membuka popup form, unduh Excel/CSV. Dulu kalimat berisi istilah
 * "mapping ke Chart of Accounts (COA) untuk integrasi finance".
 */
import { Pencil, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PageLayout from '../../layout/PageLayout';
import { EmptyState } from '../../moduleAtoms';
import { DEPR_METHOD_LABEL } from '../constants';

const metode = (c) => DEPR_METHOD_LABEL[c.depr_method] || 'Saldo menurun';
const akun = (kode) => (kode
  ? <span className="tabular-nums">{kode}</span>
  : <span className="text-muted-foreground">Belum diatur</span>);

export function CategoriesTab({ categories, loading, onMuatUlang, onEditCategory }) {
  return (
    <PageLayout testId="asset-categories" title="Kategori"
      subtitle="Umur manfaat, metode penyusutan, dan akun Bagan Akun tiap kategori aset."
      tools={<>
        <TombolUnduh namaBerkas="kategori-aset" namaLembar="Kategori" baris={categories} testId="category-unduh"
          kolom={[
            { label: 'Kode', nilai: (c) => c.code || '' },
            { label: 'Nama', nilai: (c) => c.name },
            { label: 'Umur manfaat (tahun)', nilai: (c) => Number(c.useful_life_years) || 0 },
            { label: 'Metode penyusutan', nilai: metode },
            { label: 'Akun aset', nilai: (c) => c.coa_asset_account || 'Belum diatur' },
            { label: 'Akun akumulasi penyusutan', nilai: (c) => c.coa_depreciation_account || 'Belum diatur' },
          ]} />
        <Button variant="outline" size="icon" onClick={onMuatUlang} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={<p className="text-sm text-muted-foreground">
        Umur manfaat, metode penyusutan, dan akun di Bagan Akun untuk tiap kategori. Klik kategori untuk mengubahnya.
      </p>}>
      <TabelData baris={categories} onKlikBaris={onEditCategory} testId="category-table"
        kosong={<EmptyState title="Belum ada kategori aset" description="Kategori bawaan dibuat otomatis saat ringkasan aset dibuka." />}
        kolom={[
          { kunci: 'kode', label: 'Kode', hp: 'keterangan', isi: (c) => <span className="tabular-nums text-muted-foreground">{c.code || '—'}</span> },
          { kunci: 'nama', label: 'Nama', hp: 'judul', isi: (c) => <span className="font-medium">{c.name}</span> },
          { kunci: 'umur', label: 'Umur manfaat', isi: (c) => `${c.useful_life_years} tahun` },
          { kunci: 'metode', label: 'Metode penyusutan', isi: metode },
          { kunci: 'akun', label: 'Akun aset', isi: (c) => akun(c.coa_asset_account) },
          { kunci: 'akum', label: 'Akun akumulasi penyusutan', isi: (c) => akun(c.coa_depreciation_account) },
          { kunci: 'aksi', label: '', rata: 'kanan', hp: false, isi: (c) => (
            <Button size="sm" variant="outline" onClick={() => onEditCategory?.(c)} data-testid={`edit-cat-btn-${c.id}`}>
              <Pencil />Ubah
            </Button>) },
        ]} />
    </PageLayout>
  );
}

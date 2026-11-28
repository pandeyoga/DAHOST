/**
 * PilihBarangPembelian — pemilih barang bertingkat untuk form Pengadaan (Permintaan Pembelian & PO).
 *
 * Owner 28 Nov 2026: "saat menambahkan barang saat ini langsung ke semua master data, tolong dikategorikan dulu dan
 * ada filter agar lebih teratur". Dulu satu daftar berisi ±2.170 barang (termasuk 1.485 "Potongan / Kain Pola"
 * hasil cutting yang tidak pernah dibeli). Sekarang: Kategori → Jenis → Barang. Daftar barang yang bisa dibeli
 * datang dari `GET /api/rahaza/materials?exclude_type=fg&untuk_beli=true` (potongan & penanda kain belum
 * ditentukan sudah dikeluarkan di server).
 *
 * Props:
 *  - materials: daftar barang (sudah disaring untuk dibeli)
 *  - value / onChange(materialId)
 *  - kategoriAwal: kategori bawaan untuk baris baru (mis. kategori baris sebelumnya)
 *  - labelBebas: label pilihan "tanpa master" (kosong = tidak ada pilihan itu)
 *  - diutamakan: { [materialId]: true } barang yang tampil paling atas (mis. punya daftar harga supplier)
 *  - labelBarang(m): label opsi barang (bawaan `materialOptionLabel` + warna kain)
 *  - sebaris: true = Kategori, Jenis, Barang satu baris di layar lebar (form lebar); false = bertumpuk (popup sempit)
 *  - testId: awalan data-testid
 */
import { useEffect, useMemo, useState } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { materialOptionLabel } from '@/lib/materialFields';

const URUTAN_KATEGORI = ['Kain', 'Aksesoris', 'Benang jahit', 'Benang', 'Packaging', 'Interlining', 'Lainnya'];
const DARI_TIPE = { fabric: 'Kain', kain: 'Kain', accessory: 'Aksesoris', packaging: 'Packaging', yarn: 'Benang',
  benang: 'Benang', interlining: 'Interlining' };

const kalimat = (s) => {
  const t = String(s || '').trim();
  return t ? t.charAt(0).toUpperCase() + t.slice(1).toLowerCase() : '';
};

/** Kategori barang dalam kata staf: "Kain/Fabric" → "Kain", "Benang Jahit" → "Benang jahit". */
export function kategoriBarang(m) {
  const nama = String(m?.category_name || '').trim();
  if (/^kain/i.test(nama)) return 'Kain';
  if (nama) return kalimat(nama);
  return DARI_TIPE[String(m?.type || '').toLowerCase()] || 'Lainnya';
}

/** Jenis di dalam kategori: kain = nama kain (Rib Knit 24", Condru, …), lainnya = sub-kategori (kancing, rit, …). */
export function jenisBarang(m) {
  if (kategoriBarang(m) === 'Kain') return String(m?.name || '').trim() || 'Lainnya';
  return kalimat(m?.sub_category) || String(m?.name || '').trim() || 'Lainnya';
}

/** Label barang; kain: WARNA tepat sesudah kode (nama kain sama untuk semua warnanya, dan label panjang terpotong
 *  di tombol pilihan — warna harus tetap terlihat). */
export function labelBarangBeli(m) {
  const warna = String(m?.color || '').trim();
  if (!warna || String(m?.name || '').toLowerCase().includes(warna.toLowerCase())) return materialOptionLabel(m);
  const unit = m.unit || m.base_uom || '';
  const head = [m.code, warna, m.name].filter(Boolean).join(' · ');
  return unit ? `${head} (${unit})` : head;
}

const urutkan = (arr, urutan) => [...arr].sort((a, b) => {
  const ia = urutan ? urutan.indexOf(a) : -1;
  const ib = urutan ? urutan.indexOf(b) : -1;
  if (ia !== ib) return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  return a.localeCompare(b, 'id');
});

export default function PilihBarangPembelian({
  materials = [], value = '', onChange, kategoriAwal = '', labelBebas = '', diutamakan = null,
  labelBarang = labelBarangBeli, sebaris = true, testId = 'pilih-barang',
}) {
  const terpilih = useMemo(() => materials.find((m) => m.id === value) || null, [materials, value]);
  const [kategori, setKategori] = useState(() => (terpilih ? kategoriBarang(terpilih) : kategoriAwal));
  const [jenis, setJenis] = useState(() => (terpilih ? jenisBarang(terpilih) : ''));

  // Barang dipilih dari luar (baris lama / daftar dimuat belakangan) → kategori & jenis ikut barang itu.
  useEffect(() => {
    if (terpilih) {
      setKategori(kategoriBarang(terpilih));
      setJenis(jenisBarang(terpilih));
    }
  }, [terpilih]);

  const daftarKategori = useMemo(() => {
    const hitung = {};
    materials.forEach((m) => { const k = kategoriBarang(m); hitung[k] = (hitung[k] || 0) + 1; });
    return urutkan(Object.keys(hitung), URUTAN_KATEGORI).map((k) => ({ k, n: hitung[k] }));
  }, [materials]);

  const dalamKategori = useMemo(
    () => (kategori ? materials.filter((m) => kategoriBarang(m) === kategori) : materials),
    [materials, kategori]);

  const daftarJenis = useMemo(() => {
    const hitung = {};
    dalamKategori.forEach((m) => { const j = jenisBarang(m); hitung[j] = (hitung[j] || 0) + 1; });
    return urutkan(Object.keys(hitung)).map((j) => ({ j, n: hitung[j] }));
  }, [dalamKategori]);

  const barang = useMemo(() => {
    const list = jenis ? dalamKategori.filter((m) => jenisBarang(m) === jenis) : dalamKategori;
    const urut = [...list].sort((a, b) => String(a.code || '').localeCompare(String(b.code || ''), 'id'));
    if (!diutamakan) return { atas: [], lain: urut };
    return { atas: urut.filter((m) => diutamakan[m.id]), lain: urut.filter((m) => !diutamakan[m.id]) };
  }, [dalamKategori, jenis, diutamakan]);

  const gantiKategori = (k) => {
    setKategori(k);
    setJenis('');
    if (terpilih && kategoriBarang(terpilih) !== k) onChange?.('');
  };
  const gantiJenis = (j) => {
    setJenis(j);
    if (terpilih && j && jenisBarang(terpilih) !== j) onChange?.('');
  };

  return (
    <div data-testid={testId}
      className={`grid grid-cols-2 gap-1.5 ${sebaris ? 'sm:grid-cols-[minmax(0,11rem)_minmax(0,15rem)_minmax(0,1fr)]' : ''}`}>
      <SmartNativeSelect value={kategori} onChange={(e) => gantiKategori(e.target.value)} searchable={false}
        aria-label="Kategori barang" data-testid={`${testId}-kategori`}>
        <option value="">Semua kategori</option>
        {daftarKategori.map(({ k, n }) => <option key={k} value={k}>{`${k} (${n})`}</option>)}
      </SmartNativeSelect>
      <SmartNativeSelect value={jenis} onChange={(e) => gantiJenis(e.target.value)} disabled={!kategori}
        aria-label="Jenis barang" data-testid={`${testId}-jenis`}>
        <option value="">{kategori ? 'Semua jenis' : 'Pilih kategori dulu'}</option>
        {daftarJenis.map(({ j, n }) => <option key={j} value={j}>{`${j} (${n})`}</option>)}
      </SmartNativeSelect>
      <div className={sebaris ? 'col-span-2 sm:col-span-1' : 'col-span-2'}>
        <SmartNativeSelect value={value} onChange={(e) => onChange?.(e.target.value)} searchable
          searchPlaceholder="Cari kode, nama, atau warna…" aria-label="Barang" data-testid={`${testId}-barang`}>
          <option value="">{labelBebas || 'Pilih barang'}</option>
          {barang.atas.map((m) => <option key={m.id} value={m.id}>{labelBarang(m)}</option>)}
          {barang.atas.length > 0 && barang.lain.length > 0 && (
            <option value="__lain" disabled>Barang lain (tanpa daftar harga supplier ini)</option>
          )}
          {barang.lain.map((m) => <option key={m.id} value={m.id}>{labelBarang(m)}</option>)}
        </SmartNativeSelect>
      </div>
    </div>
  );
}

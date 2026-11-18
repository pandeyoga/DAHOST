// 18 Nov 2026 (owner: "tambah juga untuk aksesoris dan kain"): kain yang ditambah qty-nya menerbitkan gulungan.
// Isi tiap roll = daftar ketikan (harus sama dengan qty) atau dibagi rata; satuan roll sama dengan server.
import { isiGulungan, perGulungan, jenisOf, JENIS_BARANG } from '../TambahQtyForm';

test('isi roll dibagi rata, sisa pembulatan masuk roll terakhir', () => {
  expect(isiGulungan(100, 4, '').isi).toEqual([25, 25, 25, 25]);
  expect(isiGulungan(100, 3, '').isi).toEqual([33.33, 33.33, 33.34]);
  expect(isiGulungan(25, 1, '').isi).toEqual([25]);
});

test('isi roll ketikan harus berjumlah sama dengan qty', () => {
  expect(isiGulungan(74.5, 1, '25, 25, 24.5').isi).toEqual([25, 25, 24.5]);
  expect(isiGulungan(80, 1, '25, 25').galat).toMatch(/harus sama dengan qty tambah/);
  expect(isiGulungan(50, 1, '25, x').galat).toMatch(/angka lebih dari 0/);
  expect(isiGulungan(50, 0, '').galat).toMatch(/minimal 1/);
});

test('hanya kain/benang bersatuan roll yang dilacak per gulungan', () => {
  expect(perGulungan({ type: 'fabric', unit: 'yard' })).toBe(true);
  expect(perGulungan({ type: 'fabric', unit: 'KG' })).toBe(true);
  expect(perGulungan({ type: 'accessory', unit: 'pcs' })).toBe(false);
  expect(perGulungan({ type: 'fg', unit: 'meter' })).toBe(false);
  expect(perGulungan({ type: 'fabric', unit: 'yard', is_cut_panel: true })).toBe(false);
});

// 18 Nov 2026 (owner: "bedakan buat filternya … aksesoris bahan atau kain", "jangan disatuan"): jenis barang terpisah.
test('jenis barang dipisah: barang jadi, kain (bahan), aksesoris', () => {
  expect(JENIS_BARANG.map((j) => j.key)).toEqual(['fg', 'bahan', 'aksesoris']);
  expect(jenisOf({ type: 'fg' })).toBe('fg');
  expect(jenisOf({ type: 'fabric' })).toBe('bahan');
  expect(jenisOf({ type: 'yarn' })).toBe('bahan');
  expect(jenisOf({ type: 'accessory' })).toBe('aksesoris');
  expect(jenisOf({ type: 'packaging' })).toBe('aksesoris');
});

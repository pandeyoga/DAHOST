import { useEffect, useState } from 'react';
import MasterDataCRUD from './MasterDataCRUD';

// Peran gudang = SSOT `core/location_resolver` (STORAGE_ROLES + EXEMPT_ROLES).
// Peran inilah yang dibaca stok jual katalog (karantina DIKECUALIKAN), retur, dan cutting.
const ROLE_OPTIONS = [
  { value: 'bahan', label: 'Bahan / kain (penyimpanan)' },
  { value: 'aksesoris', label: 'Aksesoris (penyimpanan)' },
  { value: 'fg', label: 'Barang jadi — ikut stok jual' },
  { value: 'sample', label: 'Sampel (penyimpanan)' },
  { value: 'karantina', label: 'Karantina QC — tidak ikut stok jual' },
  { value: 'cutting', label: 'Area cutting (barang setengah jadi)' },
  { value: 'sewing', label: 'Area jahit (barang setengah jadi)' },
  { value: 'qc', label: 'Area QC (barang setengah jadi)' },
  { value: 'packing', label: 'Area packing (barang setengah jadi)' },
];
const ROLE_LABEL = Object.fromEntries(ROLE_OPTIONS.map((o) => [o.value, o.label]));
const JENIS_LOKASI = { gedung: 'Gedung', zona: 'Zona', gudang: 'Gudang', kantor: 'Kantor', produksi: 'Produksi' };

export default function RahazaLocationsModule({ token }) {
  const [locs, setLocs] = useState([]);
  useEffect(() => {
    fetch('/api/rahaza/locations', { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.ok ? r.json() : [])
      .then(setLocs).catch(() => {});
  }, [token]);

  const gedungOptions = locs.filter(l => l.type === 'gedung' && l.active).map(l => ({ value: l.id, label: l.name }));

  return (
    <MasterDataCRUD
      title="Lokasi gudang"
      description="Gedung dan zona penyimpanan beserta perannya; peran menentukan perilaku stok."
      endpoint="/api/rahaza/locations"
      token={token}
      testIdPrefix="rahaza-location"
      ieKey="locations"
      columns={[
        { key: 'code', label: 'Kode' },
        { key: 'name', label: 'Nama' },
        // Data nyata juga berisi jenis 'gudang' / 'kantor' / 'produksi' (hasil impor) — dulu semuanya tampil "Zona".
        { key: 'type', label: 'Jenis', render: v => JENIS_LOKASI[v] || 'Lainnya' },
        { key: 'storage_role', label: 'Peran gudang', render: v => (v ? (ROLE_LABEL[v] || v) : '—') },
        { key: 'parent_name', label: 'Induk (gedung)', render: v => v || '—' },
      ]}
      fields={[
        { key: 'code', label: 'Kode', required: true, placeholder: 'Contoh: GD-L1-RAK atau GD-L1-QC' },
        { key: 'name', label: 'Nama', required: true, placeholder: 'Contoh: Gudang Lantai 1 — Rak / Karantina QC' },
        { key: 'type', label: 'Jenis', type: 'select', required: true,
          options: [{ value: 'gedung', label: 'Gedung' }, { value: 'zona', label: 'Zona' }] },
        { key: 'storage_role', label: 'Peran gudang', type: 'select', options: ROLE_OPTIONS,
          help: "Barang jadi ikut stok jual katalog, Karantina QC dikecualikan, Bahan/kain menjadi sumber Portal Cutting. Kosongkan untuk kantor. Satu peran penyimpanan idealnya hanya dipegang satu lokasi aktif." },
        { key: 'parent_id', label: 'Induk gedung (khusus zona)', type: 'select',
          options: gedungOptions, help: 'Isi hanya bila jenisnya Zona.' },
      ]}
      defaultItem={{ code: '', name: '', type: 'zona', storage_role: '', parent_id: '' }}
    />
  );
}

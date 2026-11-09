/**
 * LokasiKerjaModule — Portal SDM › Lokasi kerja (keputusan owner 10 Nov 2026).
 *
 * Lokasi KANTOR (kantor pusat, ruang admin/HR/marketing) adalah lokasi kerja karyawan — dipilih di Data Karyawan dan
 * penyaring roster shift. Dulu ikut tampil di Gudang › Lokasi gudang dan membingungkan ("kenapa kantor dimasukkan ke
 * lokasi gudang"). Masternya TETAP satu (`/api/rahaza/locations`, koleksi `rahaza_locations`); layar ini hanya
 * menampilkan & membuat lokasi berjenis kantor, layar Lokasi gudang menampilkan gedung/zona/area produksi.
 */
import { useEffect, useState } from 'react';
import MasterDataCRUD from '../MasterDataCRUD';

export default function LokasiKerjaModule({ token }) {
  const [kantor, setKantor] = useState([]);
  useEffect(() => {
    fetch('/api/rahaza/locations', { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.json() : []))
      .then((d) => setKantor((Array.isArray(d) ? d : []).filter((l) => l.type === 'kantor' && l.active && !l.parent_id)))
      .catch(() => {});
  }, [token]);

  return (
    <MasterDataCRUD
      title="Lokasi kerja"
      description="Kantor dan ruang tempat karyawan bekerja; dipilih di Data Karyawan dan penyaring roster shift."
      endpoint="/api/rahaza/locations"
      token={token}
      testIdPrefix="hr-work-location"
      jenis="lokasi kerja"
      hapusPermanen
      saringBaris={(r) => r.type === 'kantor'}
      itemTetap={{ type: 'kantor', storage_role: '' }}
      columns={[
        { key: 'code', label: 'Kode' },
        { key: 'name', label: 'Nama' },
        { key: 'parent_name', label: 'Kantor induk', render: (v) => v || '—' },
      ]}
      fields={[
        { key: 'code', label: 'Kode', required: true, placeholder: 'Contoh: KTR-PST atau KTR-ADM' },
        { key: 'name', label: 'Nama', required: true, placeholder: 'Contoh: Kantor Pusat / Ruang Admin' },
        { key: 'parent_id', label: 'Kantor induk', type: 'select', options: kantor.map((k) => ({ value: k.id, label: k.name })),
          help: 'Isi bila ini ruang di dalam kantor lain (mis. Ruang Admin di Kantor Pusat).' },
      ]}
      defaultItem={{ code: '', name: '', parent_id: '' }}
    />
  );
}

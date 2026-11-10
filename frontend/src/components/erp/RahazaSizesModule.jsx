import MasterDataCRUD from './MasterDataCRUD';

export default function RahazaSizesModule({ token }) {
  return (
    <MasterDataCRUD
      title="Ukuran"
      description="Master ukuran produk. Urutan menentukan susunan ukuran di formulir & laporan."
      endpoint="/api/rahaza/sizes"
      token={token}
      testIdPrefix="rahaza-size"
      ieKey="sizes"
      // 10 Nov 2026 (owner "master data bisa dihapus"): DELETE /sizes/{id}?hard=true menghapus bila belum dipakai,
      // 409 bila sudah (dialog menawarkan Nonaktifkan).
      hapusPermanen
      jenis="ukuran"
      columns={[
        { key: 'code', label: 'Kode' },
        { key: 'name', label: 'Nama' },
        { key: 'order_seq', label: 'Urutan' },
      ]}
      fields={[
        { key: 'code', label: 'Kode', required: true, placeholder: 'Contoh: XS / M / XXL' },
        { key: 'name', label: 'Nama', placeholder: 'Opsional; kosong = sama dengan kode' },
        { key: 'order_seq', label: 'Urutan', type: 'number', placeholder: 'Contoh: 1 untuk S, 2 untuk M, dst' },
      ]}
      defaultItem={{ code: '', name: '', order_seq: 0 }}
    />
  );
}

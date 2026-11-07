/**
 * RahazaMaterialRequirementsModule — tautan lama `prod-material-requirements` ("Kebutuhan Material").
 *
 * Tahap 9 (7 Nov 2026): layarnya digantikan tab "Kebutuhan" di menu Bahan (`bahan-produksi`). Dulu layar
 * ini menghitung BOM × qty sendiri (mode PO + mode manual model × ukuran); kini satu hitungan di server
 * (`/api/rahaza/material-requirements/po/{id}`). Berkas ini tinggal meneruskan ke komponen yang SAMA supaya
 * tautan lama tetap terbuka tanpa tampilan kedua. Tampilannya: `<PageLayout>` di `bahan/KebutuhanBahan.jsx`.
 */
export { default } from './bahan/KebutuhanBahan';

/**
 * EmptyState — DIALIHKAN ke satu komponen bersama `moduleAtoms.EmptyState` (PANDUAN_UI G10, 4 Nov 2026).
 *
 * Dulu ada dua komponen tampilan kosong dengan ukuran ikon & judul berbeda (ikon 48 px ungu + judul besar
 * + animasi di sini; ikon kecil abu di moduleAtoms), sehingga layar kosong terlihat beda-beda. Impor lama
 * (`import { EmptyState } from '../EmptyState'`) tetap jalan dan sekarang menampilkan bentuk yang sama.
 */
import { EmptyState } from './moduleAtoms';

export { EmptyState };
export default EmptyState;

/** Teks bawaan yang umum (dipertahankan untuk impor lama). */
export const EmptyStatePresets = {
  noData: (entityName = 'data') => ({
    title: `Belum ada ${entityName}`,
    description: `${entityName} akan muncul di sini setelah Anda menambahkan item pertama.`,
  }),
  noResults: { title: 'Tidak ada hasil', description: 'Coba ubah penyaring atau kata kunci pencarian.' },
  noPermission: { title: 'Akses terbatas', description: 'Anda tidak punya izin melihat data ini. Hubungi administrator bila perlu akses.' },
  error: { title: 'Gagal memuat data', description: 'Terjadi kesalahan saat memuat data. Muat ulang halaman atau hubungi admin.' },
};

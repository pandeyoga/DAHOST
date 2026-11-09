/**
 * hapusMaster — satu alur "Hapus" untuk baris tabel master data (permintaan owner 10 Nov 2026).
 *
 *   const hasil = await hapusMaster({
 *     jenis: 'klien', nama: c.name,
 *     hapus: () => apiDelete(`/dewi/maklon/clients/${c.id}?hard=true`),
 *     nonaktifkan: isActive(c) ? () => apiPut(`/dewi/maklon/clients/${c.id}/toggle`, {}) : null,
 *   });
 *   if (hasil) await load();
 *
 * 1. confirmDialog merah "Hapus <jenis> <nama>?".
 * 2. Server menghapus permanen bila data belum dipakai. Bila sudah dipakai, server menjawab 409 dengan kalimat
 *    "… sudah dipakai di 3 PO maklon …" (backend `core/hapus_master.py`).
 * 3. Pada 409 dan `nonaktifkan` tersedia → dialog kedua menampilkan alasan itu dan menawarkan Nonaktifkan.
 *
 * Hasil: 'dihapus' | 'dinonaktifkan' | false (batal/gagal). Galat lain tampil sebagai toast.
 */
import { toast } from 'sonner';
import { confirmDialog } from '@/components/ui/confirm-dialog';

const awalBesar = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
// Galat dari lib/api (e.status) maupun axios (e.response.status / e.response.data.detail).
const statusDari = (e) => e?.status ?? e?.response?.status;
const pesanDari = (e, cadangan) => {
  const d = e?.response?.data?.detail;
  return (typeof d === 'string' && d) || e?.message || cadangan;
};

export async function hapusMaster({ jenis, nama, hapus, nonaktifkan = null, keterangan = '' }) {
  const label = nama ? `${jenis} "${nama}"` : jenis;
  const ok = await confirmDialog({
    title: `Hapus ${label}?`,
    body: keterangan || 'Data dihapus permanen. Bila sudah dipakai di transaksi atau dokumen lain, penghapusan ditolak'
      + (nonaktifkan ? ' dan Anda bisa menonaktifkannya saja.' : '.'),
    confirmLabel: 'Hapus', danger: true,
  });
  if (!ok) return false;
  try {
    await hapus();
    toast.success(`${awalBesar(label)} dihapus`);
    return 'dihapus';
  } catch (e) {
    if (statusDari(e) === 409 && nonaktifkan) {
      const lanjut = await confirmDialog({
        title: `${awalBesar(label)} tidak bisa dihapus`,
        body: pesanDari(e, 'Data sudah dipakai.'), confirmLabel: 'Nonaktifkan',
      });
      if (!lanjut) return false;
      try {
        await nonaktifkan();
        toast.success(`${awalBesar(label)} dinonaktifkan`);
        return 'dinonaktifkan';
      } catch (e2) {
        toast.error(pesanDari(e2, 'Gagal menonaktifkan'));
        return false;
      }
    }
    toast.error(pesanDari(e, 'Gagal menghapus'));
    return false;
  }
}

export default hapusMaster;

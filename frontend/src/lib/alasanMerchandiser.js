/**
 * Pengaman Merchandiser — alasan WAJIB (keputusan owner K-M2, 12 Nov 2026).
 *
 * Server menjawab HTTP 428 ("Pengaman Merchandiser: …") bila PO produksi internal, Permintaan Pengadaan, PO
 * pembelian, atau PR aksesoris menambah barang/bahan untuk model yang lambat atau tidak laku, dan alasan belum
 * diisi. Helper ini menampilkan angkanya, meminta alasan lewat dialog aplikasi, lalu mengirim ulang permintaan
 * yang sama dengan `alasan_merchandiser`. Model yang masih laku tidak memunculkan dialog.
 *
 *   const data = await denganAlasanMerchandiser((extra) => apiPost('/production-pos', { ...payload, ...extra }));
 *
 * `kirim(extra)` harus MELEMPAR galat bila server menolak, dengan `status` (atau `response.status` axios) dan
 * pesan dari `detail` — apiPost/apiPut (lib/api) dan axios sudah begitu.
 */
import { confirmDialog } from '@/components/ui/confirm-dialog';

export const STATUS_ALASAN = 428;
export const MIN_ALASAN = 10;
export const KUNCI_ALASAN = 'alasan_merchandiser';
const PENANDA = /Pengaman Merchandiser/i;

const statusDari = (err) => err?.status ?? err?.response?.status;
const pesanDari = (err) => {
  const d = err?.response?.data?.detail ?? err?.detail;
  return typeof d === 'string' ? d : (err?.message || '');
};

/** Galat ini penolakan pengaman Merchandiser (bukan 428 kelebihan qty)? */
export function perluAlasanMerchandiser(err) {
  return statusDari(err) === STATUS_ALASAN && PENANDA.test(pesanDari(err));
}

/** Galat untuk pemanggil berbasis `fetch` yang tidak melempar sendiri. */
export async function galatDariRespons(res, cadangan) {
  const data = await res.json().catch(() => ({}));
  const e = new Error(typeof data.detail === 'string' ? data.detail : (cadangan || `Permintaan gagal (kode ${res.status}).`));
  e.status = res.status;
  return e;
}

export async function denganAlasanMerchandiser(kirim) {
  try {
    return await kirim({});
  } catch (err) {
    if (!perluAlasanMerchandiser(err)) throw err;
    const isi = pesanDari(err).replace(/^Pengaman Merchandiser:\s*/i, '');
    const alasan = await confirmDialog({
      title: 'Barang ini lambat atau tidak laku',
      body: isi.charAt(0).toUpperCase() + isi.slice(1),
      confirmLabel: 'Tetap simpan dengan alasan',
      input: {
        label: 'Alasan tetap melanjutkan',
        placeholder: 'mis. pesanan khusus toko offline sudah dibayar',
        minLength: MIN_ALASAN,
      },
    });
    if (!alasan) {
      const e = new Error('Dibatalkan — alasan belum diisi, jadi data tidak disimpan.');
      e.dibatalkan = true;
      throw e;
    }
    return kirim({ [KUNCI_ALASAN]: String(alasan).trim() });
  }
}

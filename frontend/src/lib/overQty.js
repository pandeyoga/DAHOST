/**
 * Kelebihan qty — alasan WAJIB (Tahap 2, 6 Nov 2026, keputusan owner).
 *
 * Server menjawab HTTP 428 bila qty melebihi batas (pesanan / deklarasi vendor) dan alasan belum diisi.
 * Helper ini meminta alasan lewat dialog aplikasi lalu mengirim ulang permintaan yang sama dengan
 * `over_qty_reason`. Di bawah batas tidak ada dialog. Dipakai: kirim ke klien, deklarasi kirim CMT,
 * selesai QC terima dari CMT.
 *
 *   const data = await postWithOverQtyReason('/buyer-shipments', payload);
 */
import { apiFetch } from './api';
import { confirmDialog } from '@/components/ui/confirm-dialog';

export const OVER_QTY_STATUS = 428;
export const OVER_QTY_MIN_REASON = 5;

export async function postWithOverQtyReason(path, body = {}) {
  let payload = { ...(body || {}) };
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const res = await apiFetch(path, { method: 'POST', body: JSON.stringify(payload) });
    const data = await res.json().catch(() => ({}));
    if (res.ok) return data;
    if (res.status === OVER_QTY_STATUS && attempt === 0) {
      const reason = await confirmDialog({
        title: 'Qty melebihi batas',
        body: data.detail || 'Qty melebihi batas. Isi alasan kelebihan qty untuk melanjutkan.',
        confirmLabel: 'Simpan dengan alasan',
        input: { label: 'Alasan kelebihan qty', placeholder: 'mis. klien minta tambahan 5 pcs (WA 6 Nov)', minLength: OVER_QTY_MIN_REASON },
      });
      if (!reason) throw new Error('Dibatalkan — qty melebihi batas dan alasan belum diisi.');
      payload = { ...payload, over_qty_reason: reason };
      continue;
    }
    throw new Error(data.detail || `Permintaan gagal (${res.status})`);
  }
  throw new Error('Permintaan gagal.');
}

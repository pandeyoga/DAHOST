/**
 * batalSetuju — satu alur "Batalkan persetujuan" untuk semua layar (permintaan owner 24 Nov 2026).
 *
 *   import { batalkanPersetujuan } from '@/lib/batalSetuju';
 *   const r = await batalkanPersetujuan({ jenis: 'rnd-style', id: style.id });
 *   if (r) muatUlang();
 *
 * Alur: tanya server dulu (`/cek`) → bila tertahan langkah lanjutan, tampilkan kalimat penahannya (tidak ada
 * popup isian) → bila boleh, minta alasan (wajib, ≥ 10 huruf) → kirim → pesan sukses. Aturan & daftar jenis ada
 * di backend `core/batal_setuju.py` dan `core/batal_setuju_jenis.py`.
 */
import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { apiFetch, ApiError } from '@/lib/apiFetch';
import { confirmDialog } from '@/components/ui/confirm-dialog';

export const MIN_ALASAN_BATAL = 10;

// Jenis + hak pengguna ini, dimuat sekali per sesi halaman (tombol disembunyikan bila tidak boleh).
let _jenis = null;
export function muatJenisBatal() {
  if (!_jenis) {
    _jenis = apiFetch('/batal-setuju/jenis')
      .then((r) => Object.fromEntries((r?.data || []).map((j) => [j.kode, j])))
      .catch(() => { _jenis = null; return {}; });
  }
  return _jenis;
}

// ApiError hanya punya status/detail/body; detail bisa berupa daftar (galat isian 422) → pakai kalimat cadangan.
const pesanGalat = (e, cadangan) => (e instanceof ApiError && typeof e.detail === 'string' && e.detail) || cadangan;

export async function batalkanPersetujuan({ jenis, id }) {
  let cek;
  try {
    cek = await apiFetch(`/batal-setuju/${encodeURIComponent(jenis)}/${encodeURIComponent(id)}/cek`);
  } catch (e) {
    if (!(e instanceof ApiError) || e.status !== 401) toast.error(pesanGalat(e, 'Gagal memeriksa persetujuan'));
    return null;
  }
  const nama = [cek?.label, cek?.nama].filter(Boolean).join(' ');
  if (!cek?.boleh) {
    await confirmDialog({
      title: 'Persetujuan belum bisa dibatalkan',
      body: (cek?.hambatan || []).join(' ') || 'Dokumen ini sudah dipakai langkah berikutnya.',
      confirmLabel: 'Mengerti',
      cancelLabel: 'Tutup',
    });
    return null;
  }
  const alasan = await confirmDialog({
    title: `Batalkan persetujuan ${nama}?`,
    body: `Status kembali ${cek.label_kembali || 'menunggu persetujuan'}, lalu bisa diputus ulang. `
      + 'Keputusan lama tetap tercatat di riwayat, dan pemohon mendapat pemberitahuan.',
    input: { label: `Alasan pembatalan (wajib, minimal ${MIN_ALASAN_BATAL} huruf)`, minLength: MIN_ALASAN_BATAL,
      placeholder: 'Mis. salah tekan Setujui — seharusnya ditolak' },
    confirmLabel: 'Batalkan persetujuan',
    cancelLabel: 'Kembali',
    danger: true,
  });
  if (!alasan) return null;
  try {
    const r = await apiFetch(`/batal-setuju/${encodeURIComponent(jenis)}/${encodeURIComponent(id)}`,
      { method: 'POST', body: { alasan } });
    toast.success(r?.pesan || 'Persetujuan dibatalkan');
    return r;
  } catch (e) {
    if (!(e instanceof ApiError) || e.status !== 401) toast.error(pesanGalat(e, 'Gagal membatalkan persetujuan'));
    return null;
  }
}

/** true bila pengguna ini boleh membatalkan persetujuan `jenis` (untuk menu titik tiga). */
export function useBolehBatal(jenis) {
  const [boleh, setBoleh] = useState(false);
  useEffect(() => {
    let hidup = true;
    muatJenisBatal().then((m) => { if (hidup) setBoleh(Boolean(m?.[jenis]?.boleh)); });
    return () => { hidup = false; };
  }, [jenis]);
  return boleh;
}

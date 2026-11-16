/**
 * Pembagian satu pembayaran ke beberapa dokumen, terlama dulu (16 Nov 2026, owner) — cermin `backend/core/alokasi_bayar.py`
 * supaya usulan di layar sama dengan yang dihitung server bila pembagian tidak diubah. Keuangan boleh mengubah
 * pembagian sebelum menyimpan; server memeriksa ulang (batas per dokumen, jumlah = Σ pembagian).
 */
export const TOLERANSI = 0.5;

const num = (v) => {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
};
const r2 = (v) => Math.round(num(v) * 100) / 100;

/** Urutan terlama dulu: `urut` (tanggal acuan; kosong = paling akhir), lalu `nomor`. */
export function urutkan(baris) {
  const k = (b) => [String(b.urut || '9999-99-99'), String(b.nomor || ''), String(b.id || '')];
  return [...(baris || [])].sort((a, b) => {
    const ka = k(a);
    const kb = k(b);
    for (let i = 0; i < ka.length; i += 1) {
      const c = ka[i].localeCompare(kb[i]);
      if (c) return c;
    }
    return 0;
  });
}

/** Bagi `jumlah` ke baris {id, batas, urut, nomor} terlama dulu → { alokasi: {id: jumlah}, sisa }. */
export function alokasiTerlama(jumlah, baris) {
  let sisa = r2(jumlah);
  const alokasi = {};
  urutkan(baris).forEach((b) => {
    if (sisa <= 0.005) return;
    const batas = r2(b.batas);
    if (batas <= 0.005) return;
    const ambil = r2(Math.min(sisa, batas));
    alokasi[b.id] = ambil;
    sisa = r2(sisa - ambil);
  });
  return { alokasi, sisa: Math.max(0, sisa) };
}

/** Jumlah semua isian pembagian. */
export const jumlahAlokasi = (alokasi) => r2(Object.values(alokasi || {}).reduce((t, v) => t + num(v), 0));

/** Baris pembagian untuk dikirim ke server (baris nol dibuang). */
export const kirimAlokasi = (alokasi) => Object.entries(alokasi || {})
  .map(([id, v]) => ({ id, jumlah: r2(v) }))
  .filter((x) => x.jumlah > 0.005);

/** Baris yang melebihi batasnya → [{id, batas}]. */
export function lewatBatas(alokasi, batasPerId) {
  return Object.entries(alokasi || {})
    .filter(([id, v]) => num(v) > num(batasPerId[id]) + 0.01)
    .map(([id]) => ({ id, batas: num(batasPerId[id]) }));
}

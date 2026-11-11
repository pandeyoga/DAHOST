/**
 * Kanal penjualan Marketing — SATU daftar untuk semua layar (11 Nov 2026, keputusan owner).
 *
 * Sama dengan backend:
 *   - `core.marketing_import_schema.ORDER_CHANNEL_LABELS` (kanal pesanan, impor & manual)
 *   - `core.marketing_sales_shape.MANUAL_TRAFFIC_KEYS` (kanal yang boleh dirinci di Input Sales)
 *
 * Aturan gabung rincian (backend `merge_traffic`):
 *   - hari tanpa pesanan: rincian ⊆ omzet total, sisanya "Lainnya";
 *   - hari dengan pesanan impor: kanal dari pesanan tetap, rincian hanya membagi bagian
 *     "Lainnya" pesanan (pesanan tanpa kanal, mis. Shopee).
 */
export const KANAL_PESANAN = [
  ['live', 'Live'], ['video', 'Video'], ['product_card', 'Kartu produk'], ['affiliate', 'Afiliasi'],
  ['ads', 'Iklan'], ['campaign', 'Kampanye'], ['search', 'Pencarian'], ['other', 'Lainnya'],
];

/** Kanal yang boleh diketik sebagai rincian omzet ("Lainnya" = sisa, dihitung sistem). */
export const KANAL_RINCIAN = KANAL_PESANAN.filter(([k]) => k !== 'other');

/** Kanal yang ditampilkan sebagai kolom sendiri di laporan; sisanya digabung "Lainnya". */
export const KANAL_UTAMA = ['live', 'video', 'product_card', 'affiliate'];

export const LABEL_KANAL = { ...Object.fromEntries(KANAL_PESANAN), organic: 'Organik' };

export const labelKanal = (k) => LABEL_KANAL[k] || LABEL_KANAL.other;

const angka = (v) => {
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : 0;
};

/** Rincian ketikan → `{jumlah, sisa, lebih}` terhadap `batas` (omzet, atau bagian "Lainnya" pesanan). */
export function hitungRincian(rincian, batas) {
  const jumlah = KANAL_RINCIAN.reduce((s, [k]) => s + angka(rincian?.[k]), 0);
  const b = angka(batas);
  return { jumlah, sisa: Math.max(0, b - jumlah), lebih: jumlah > b + 1 };
}

/** Rincian untuk dikirim ke server: hanya kanal yang bernilai > 0. */
export function rincianBersih(rincian) {
  const out = {};
  KANAL_RINCIAN.forEach(([k]) => {
    const n = angka(rincian?.[k]);
    if (n > 0) out[k] = n;
  });
  return out;
}

/** Pecahan kanal satu rekap → nilai kanal utama + "Lainnya" (semua kanal sisanya). */
export function kanalUtama(traffic) {
  const t = traffic || {};
  const out = {};
  let lain = 0;
  Object.entries(t).forEach(([k, v]) => {
    if (KANAL_UTAMA.includes(k)) out[k] = angka(v);
    else lain += angka(v);
  });
  KANAL_UTAMA.forEach((k) => { if (!(k in out)) out[k] = 0; });
  out.other = lain;
  return out;
}

/** Apakah rekap ini punya pecahan kanal (bukan kosong / nol semua). */
export const adaPecahan = (traffic) => Object.values(traffic || {}).some((v) => angka(v) > 0);

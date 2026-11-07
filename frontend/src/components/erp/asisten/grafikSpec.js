/**
 * grafikSpec — pemeriksa & pemformat spesifikasi grafik Asisten AI (Kontrak B, alat `tampilkan_grafik`).
 * Logika murni tanpa Recharts supaya bisa diuji sendiri; dirender oleh `GrafikAsisten.jsx`.
 */
import { formatAngkaRingkas, formatNumber, formatPercent, formatRupiah } from '@/lib/format';
import { CHART_PALETTE } from '../dashboardAtoms';

export const JENIS_GRAFIK = ['batang', 'batang_horizontal', 'garis', 'area', 'pai'];
const MAKS_SERI = 4;
const MAKS_TITIK = 31;
const MAKS_IRISAN = 5; // pai: 5 warna token + "Lainnya" (abu) — warna tidak pernah diulang
const WARNA_LAINNYA = 'hsl(var(--muted-foreground) / 0.45)';

function toNum(v) {
  if (v === null || v === undefined || v === '') return null;
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  const s = String(v).trim();
  if (!/\d/.test(s)) return null; // "abc" bukan 0 (Number('') === 0)
  // "12.5" (titik desimal mesin) vs "142.300.000" / "17,5" (gaya Indonesia)
  const n = /^-?\d+(\.\d+)?$/.test(s) ? Number(s) : Number(s.replace(/[^\d,.-]/g, '').replace(/\./g, '').replace(',', '.'));
  return Number.isFinite(n) ? n : null;
}

/** Pemformat angka menurut satuan: `sumbu` (ringkas) dan `penuh` (tooltip/tabel). */
export function pemformatSatuan(satuan) {
  const s = String(satuan || '').trim();
  if (/^rp\.?$/i.test(s)) return { sumbu: formatAngkaRingkas, penuh: (v) => formatRupiah(v), label: 'Rp' };
  if (s === '%') return { sumbu: (v) => formatPercent(v, 1), penuh: (v) => formatPercent(v, 2), label: '%' };
  return {
    sumbu: formatAngkaRingkas,
    penuh: (v) => `${formatNumber(v, { maximumFractionDigits: 2 })}${s ? ` ${s}` : ''}`,
    label: s,
  };
}

/**
 * Periksa & rapikan spesifikasi. Mengembalikan `{ ok: true, … }` atau `{ ok: false, alasan }`.
 * Batas Kontrak B: ≤ 4 seri, ≤ 31 titik x, pai tepat 1 seri (seri lain diabaikan).
 */
export function validasiSpec(spec) {
  if (!spec || typeof spec !== 'object') return { ok: false, alasan: 'data grafik kosong' };
  let jenis = String(spec.jenis || '').trim().toLowerCase();
  if (!JENIS_GRAFIK.includes(jenis)) return { ok: false, alasan: 'jenis grafik tidak dikenal' };
  const x = Array.isArray(spec.x) ? spec.x.slice(0, MAKS_TITIK).map((v) => String(v ?? '')) : [];
  if (!x.length) return { ok: false, alasan: 'tidak ada kategori' };
  const seriMentah = Array.isArray(spec.seri) ? spec.seri.filter((s) => s && Array.isArray(s.nilai)) : [];
  if (!seriMentah.length) return { ok: false, alasan: 'tidak ada seri angka' };
  const seri = seriMentah.slice(0, jenis === 'pai' ? 1 : MAKS_SERI).map((s, i) => ({
    nama: String(s.nama || `Seri ${i + 1}`),
    nilai: x.map((_, j) => toNum(s.nilai[j])),
  }));
  if (seri.every((s) => s.nilai.every((v) => v === null))) return { ok: false, alasan: 'semua nilai kosong' };
  let catatanTambahan = '';
  if (jenis === 'pai' && seri[0].nilai.some((v) => v !== null && v < 0)) {
    jenis = 'batang'; // pai tidak bisa menampilkan nilai negatif
    catatanTambahan = 'Ditampilkan sebagai batang karena ada nilai negatif.';
  }
  if (Array.isArray(spec.seri) && spec.seri.length > seri.length && jenis !== 'pai') {
    catatanTambahan = `Hanya ${MAKS_SERI} seri pertama yang ditampilkan.`;
  }
  return {
    ok: true,
    jenis,
    judul: String(spec.judul || ''),
    satuan: String(spec.satuan || ''),
    catatan: [spec.catatan, catatanTambahan].filter(Boolean).join(' '),
    x,
    seri,
  };
}

/** Irisan pai: urut terbesar, maksimal 5 warna + "Lainnya". */
export function irisanPai(v) {
  const rows = v.x.map((nama, i) => ({ nama, nilai: v.seri[0].nilai[i] })).filter((r) => r.nilai !== null && r.nilai > 0)
    .sort((a, b) => b.nilai - a.nilai);
  if (rows.length <= MAKS_IRISAN + 1) return rows.map((r, i) => ({ ...r, warna: CHART_PALETTE[i] || WARNA_LAINNYA }));
  const atas = rows.slice(0, MAKS_IRISAN).map((r, i) => ({ ...r, warna: CHART_PALETTE[i] }));
  const sisa = rows.slice(MAKS_IRISAN).reduce((s, r) => s + r.nilai, 0);
  return [...atas, { nama: `Lainnya (${rows.length - MAKS_IRISAN})`, nilai: sisa, warna: WARNA_LAINNYA }];
}


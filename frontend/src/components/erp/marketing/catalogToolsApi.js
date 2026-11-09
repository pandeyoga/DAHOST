/**
 * Panggilan aksi cepat katalog (backend `routes/marketing_catalog_tools.py` + `bulk-transition`).
 * Semua aksi massal: pratinjau dulu → konfirmasi → jalankan → bisa dibatalkan (Riwayat aksi massal).
 */
const API = process.env.REACT_APP_BACKEND_URL || '';

export const alatUrl = (path) => `${API}/api/marketing/catalog-tools${path}`;
export const katalogUrl = (path) => `${API}/api/marketing/catalogs${path}`;

const kepala = (token, json = true) => {
  const h = { Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` };
  if (json) h['Content-Type'] = 'application/json';
  return h;
};

/** POST/GET JSON → isi jawaban; galat server dilempar sebagai Error berbahasa Indonesia dari `detail`. */
export async function panggil(token, url, { method = 'POST', body } = {}) {
  const r = await fetch(url, { method, headers: kepala(token), body: body ? JSON.stringify(body) : undefined });
  const b = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof b.detail === 'string' ? b.detail : 'Gagal menyimpan perubahan');
  return b;
}

/** Unggah berkas (multipart) ke `url` → isi jawaban. */
export async function unggah(token, url, file) {
  const fd = new FormData();
  fd.append('file', file);
  const r = await fetch(url, { method: 'POST', headers: kepala(token, false), body: fd });
  const b = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof b.detail === 'string' ? b.detail : 'Berkas gagal diproses');
  return b;
}

/** Unduh berkas dari `url` (butuh token) → simpan dengan nama dari server atau `cadangan`. */
export async function unduh(token, url, cadangan) {
  const r = await fetch(url, { headers: kepala(token, false) });
  if (!r.ok) {
    const b = await r.json().catch(() => ({}));
    throw new Error(typeof b.detail === 'string' ? b.detail : 'Berkas gagal diunduh');
  }
  const cd = r.headers.get('Content-Disposition') || '';
  const m = cd.match(/filename="?([^"]+)"?/);
  const blob = await r.blob();
  const href = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = href;
  a.download = (m && m[1]) || cadangan;
  a.click();
  URL.revokeObjectURL(href);
}

/** {alasan: jumlah} → "12 belum ada URL produk, 3 sudah tayang". */
export function ringkasLewati(ringkas) {
  return Object.entries(ringkas || {})
    .sort((a, b) => b[1] - a[1])
    .map(([why, n]) => `${Number(n).toLocaleString('id-ID')} ${why}`)
    .join(', ');
}

export const batalkanAksi = (token, runId) => panggil(token, alatUrl(`/runs/${runId}/undo`));

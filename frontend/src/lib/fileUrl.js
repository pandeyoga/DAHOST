/**
 * Alamat berkas unggahan yang membawa token login (2026-11-07).
 *
 * Berkas data pribadi (selfie absen, lampiran cuti, foto profil, dokumen karyawan) hanya bisa
 * dibuka dengan token. Tag <img src> / <a href> tidak bisa mengirim header Authorization, jadi
 * token ditempel sebagai `?auth=`. Daftar berkas yang dilindungi: backend/core/sensitive_files.py.
 *
 * Hanya alamat `/api/uploads/` dan `/api/files/` yang diubah; alamat lain (data:, blob:, tautan luar)
 * dikembalikan apa adanya.
 *
 *   <img src={withFileAuth(`${API}${rec.photo_selfie_url}`)} />
 */
const FILE_PATHS = ['/api/uploads/', '/api/files/'];

function readToken() {
  try {
    return window.localStorage.getItem('erp_token') || '';
  } catch {
    return '';
  }
}

export function withFileAuth(url) {
  if (!url || typeof url !== 'string') return url;
  if (!FILE_PATHS.some((p) => url.includes(p))) return url;
  const token = readToken();
  if (!token) return url;
  const hashAt = url.indexOf('#');
  const base = hashAt >= 0 ? url.slice(0, hashAt) : url;
  const hash = hashAt >= 0 ? url.slice(hashAt) : '';
  if (/[?&]auth=/.test(base)) return url;
  return `${base}${base.includes('?') ? '&' : '?'}auth=${encodeURIComponent(token)}${hash}`;
}

export default withFileAuth;

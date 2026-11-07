/**
 * asistenApi — panggilan Kontrak B Asisten AI (`/api/asisten-ai`, Tahap A, 8 Nov 2026).
 *
 * Satu tempat untuk alamat endpoint dan pengunduhan laporan (logika murni pesan/SSE: `peristiwaSse.js`), supaya komponen layar
 * (`AsistenAIModule`, `RiwayatPercakapan`, `UtasPesan`, `PesanAsisten`, `KomposerAsisten`) tidak menulis URL sendiri.
 */
import apiFetch, { ApiError, buildApiUrl } from '@/lib/apiFetch';
import { sseFetch } from '@/lib/sseFetch';
import { CV_HEADER, normalizeCv } from '@/lib/entitas';

const BASE = '/asisten-ai';

const asList = (d, ...keys) => {
  if (Array.isArray(d)) return d;
  for (const k of keys) if (Array.isArray(d?.[k])) return d[k];
  return [];
};

export const asistenApi = {
  status: () => apiFetch(`${BASE}/status`),
  saran: (peran) => apiFetch(`${BASE}/saran${peran ? `?peran=${encodeURIComponent(peran)}` : ''}`)
    .then((d) => asList(d, 'saran', 'items', 'data')),
  listSessions: () => apiFetch(`${BASE}/sessions`).then((d) => asList(d, 'sessions', 'items', 'data')),
  createSession: (judul) => apiFetch(`${BASE}/sessions`, { method: 'POST', body: judul ? { judul } : {} }),
  getSession: (id) => apiFetch(`${BASE}/sessions/${encodeURIComponent(id)}`),
  renameSession: (id, judul) => apiFetch(`${BASE}/sessions/${encodeURIComponent(id)}`, { method: 'PATCH', body: { judul } }),
  deleteSession: (id) => apiFetch(`${BASE}/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  /**
   * Kirim pertanyaan dan baca jawabannya sebagai aliran SSE. CV dikirim di badan (Kontrak B) DAN di header
   * `X-CV` (keputusan owner 8: pola yang sama dengan Portal Keuangan).
   */
  kirimPesan: (id, { teks, cv, periode }, { signal, onEvent } = {}) => {
    const c = normalizeCv(cv);
    return sseFetch(`${BASE}/sessions/${encodeURIComponent(id)}/messages`, {
      body: { teks, cv: c, ...(periode ? { periode } : {}) },
      headers: { [CV_HEADER]: c },
      signal,
      onEvent,
    });
  },
};

/** Alamat milik backend aplikasi ini (hanya ke sini token login boleh dikirim). */
function isOwnApi(url) {
  const u = String(url || '');
  if (u.startsWith('/api/')) return true;
  try {
    const full = new URL(buildApiUrl(u), window.location.origin);
    const backend = new URL(buildApiUrl('/api/'), window.location.origin);
    return full.origin === backend.origin && full.pathname.startsWith('/api/');
  } catch {
    return false;
  }
}

function fileNameFrom(res, fallback) {
  const cd = res.headers.get('content-disposition') || '';
  const star = /filename\*=UTF-8''([^;]+)/i.exec(cd);
  if (star) {
    try { return decodeURIComponent(star[1].replace(/"/g, '')); } catch { /* nama rusak → cadangan */ }
  }
  const plain = /filename="?([^";]+)"?/i.exec(cd);
  return plain ? plain[1] : fallback;
}

const safeName = (s) => String(s || 'laporan').replace(/[\\/:*?"<>|]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 80) || 'laporan';

/**
 * Unduh laporan (`laporan.url` = GET yang mengunduh dengan auth). Token hanya dikirim ke backend aplikasi ini;
 * alamat lain dibuka di tab baru tanpa token.
 */
export async function unduhLaporan({ url, judul, format }) {
  if (!url) throw new ApiError(0, 'Alamat laporan tidak tersedia.', null);
  if (!isOwnApi(url)) {
    window.open(url, '_blank', 'noopener,noreferrer');
    return;
  }
  const res = await apiFetch(url, { rawResponse: true, headers: { Accept: '*/*' } });
  if (!res.ok) {
    let detail = 'Laporan gagal diunduh.';
    try { const j = await res.json(); detail = j?.detail || j?.pesan || detail; } catch { /* bukan JSON */ }
    throw new ApiError(res.status, detail, null);
  }
  const blob = await res.blob();
  const ext = format === 'xlsx' ? 'xlsx' : 'pdf';
  const name = fileNameFrom(res, `${safeName(judul)}.${ext}`);
  const href = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = href;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

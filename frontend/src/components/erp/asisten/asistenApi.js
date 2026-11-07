/**
 * asistenApi — panggilan Kontrak B Asisten AI (`/api/asisten-ai`, Tahap A, 8 Nov 2026).
 * Tahap B: kartu tindakan. Tahap D: Ingatan AI + "Jalankan sekarang" proaktif (bentuk data: `adapterTahapCD.js`).
 *
 * Satu tempat untuk alamat endpoint dan pengunduhan laporan (logika murni pesan/SSE: `peristiwaSse.js`), supaya komponen layar
 * (`AsistenAIModule`, `RiwayatPercakapan`, `UtasPesan`, `PesanAsisten`, `KomposerAsisten`) tidak menulis URL sendiri.
 */
import apiFetch, { ApiError, buildApiUrl } from '@/lib/apiFetch';
import { sseFetch } from '@/lib/sseFetch';
import { CV_HEADER, normalizeCv } from '@/lib/entitas';

const BASE = '/asisten-ai';
/** sessionStorage: percakapan yang dibuka Asisten AI (dipakai juga halaman Tindakan AI untuk "Buka percakapan"). */
export const KUNCI_SESI_AKTIF = 'asisten_ai_sesi_aktif';

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

  // ── Tahap B (Kontrak E): kartu tindakan ──
  /**
   * Putuskan kartu tindakan (hanya pemilik percakapan, hanya selagi `menunggu`). Jawabannya aliran SSE:
   * `tindakan_status` (disetujui → dijalankan/gagal, atau dibatalkan), lalu — bila semua tindakan giliran itu
   * sudah diputuskan — lanjutan jawaban `mulai` … `selesai` seperti Kontrak B.
   */
  putuskan: (id, { keputusan, ubahan, alasan, cv }, { signal, onEvent } = {}) => {
    const c = normalizeCv(cv);
    const body = { keputusan, cv: c };
    if (ubahan && Object.keys(ubahan).length) body.ubahan = ubahan;
    if (alasan) body.alasan = alasan;
    return sseFetch(`${BASE}/tindakan/${encodeURIComponent(id)}/putuskan`, {
      body,
      headers: { [CV_HEADER]: c },
      signal,
      onEvent,
    });
  },
  daftarTindakan: (query) => apiFetch(`${BASE}/tindakan${query ? `?${query}` : ''}`),
  detailTindakan: (id) => apiFetch(`${BASE}/tindakan/${encodeURIComponent(id)}`),
  balikkanTindakan: (id, alasan) => apiFetch(`${BASE}/tindakan/${encodeURIComponent(id)}/balikkan`, {
    method: 'POST', body: alasan ? { alasan } : {},
  }),

  // ── Tahap D (D1): Ingatan AI — hanya milik sendiri. Bentuk jawaban dibaca `adapterTahapCD.js` (A1, A2). ──
  daftarIngatan: () => apiFetch(`${BASE}/ingatan`),
  tambahIngatan: ({ isi, kategori }) => apiFetch(`${BASE}/ingatan`, { method: 'POST', body: { isi, kategori } }),
  ubahIngatan: (id, { isi, kategori }) => apiFetch(`${BASE}/ingatan/${encodeURIComponent(id)}`, {
    method: 'PATCH', body: { isi, kategori },
  }),
  hapusIngatan: (id) => apiFetch(`${BASE}/ingatan/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  // ── Tahap D (D2): jalankan jadwal proaktif sekarang (owner/superadmin), A7 ──
  jalankanProaktif: (jenis) => apiFetch(`${BASE}/proaktif/${encodeURIComponent(jenis)}/jalankan-sekarang`, {
    method: 'POST', body: {},
  }),
  /** Jadwal berikutnya + riwayat jalan proaktif (A10; owner/superadmin, lainnya 403). */
  ringkasanProaktif: () => apiFetch(`${BASE}/proaktif`),
  /** Calon penerima briefing: pengguna aktif yang bisa membuka Portal Management (A9, endpoint yang sudah ada). */
  daftarPenggunaManajemen: () => apiFetch('/auth/users?portal=management&status=active&limit=500'),
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

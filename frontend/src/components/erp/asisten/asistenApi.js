/**
 * asistenApi — panggilan Kontrak B Asisten AI (`/api/asisten-ai`, Tahap A, 8 Nov 2026).
 * Tahap B: kartu tindakan. Tahap D: Ingatan AI + "Jalankan sekarang" proaktif (bentuk data: `adapterTahapCD.js`).
 * Tahap E: unggah/hapus lampiran (K2) dan unduh/pratinjau berkas buatan AI (K3) (logika murni: `lampiranAsisten.js`).
 *
 * Satu tempat untuk alamat endpoint dan pengunduhan laporan (logika murni pesan/SSE: `peristiwaSse.js`), supaya komponen layar
 * (`AsistenAIModule`, `RiwayatPercakapan`, `UtasPesan`, `PesanAsisten`, `KomposerAsisten`) tidak menulis URL sendiri.
 */
import apiFetch, { ApiError, buildApiUrl, notifyUnauthorized, resolveToken } from '@/lib/apiFetch';
import { sseFetch } from '@/lib/sseFetch';
import { CV_HEADER, normalizeCv } from '@/lib/entitas';
import { MAKS_UKURAN_MB, ekstensi } from './lampiranAsisten';

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
  kirimPesan: (id, { teks, cv, periode, lampiran }, { signal, onEvent } = {}) => {
    const c = normalizeCv(cv);
    // Tahap E (Kontrak K2): id lampiran yang sudah diunggah (≤ 5); tanpa lampiran → badan sama seperti dulu.
    const ids = (Array.isArray(lampiran) ? lampiran : []).map((l) => (l && typeof l === 'object' ? l.id : l)).filter(Boolean);
    return sseFetch(`${BASE}/sessions/${encodeURIComponent(id)}/messages`, {
      body: { teks, cv: c, ...(periode ? { periode } : {}), ...(ids.length ? { lampiran: ids } : {}) },
      headers: { [CV_HEADER]: c },
      signal,
      onEvent,
    });
  },

  // ── Tahap E (Kontrak K2): lampiran berkas ──
  /**
   * Unggah SATU berkas (multipart, field `berkas`) → `{id, nama, jenis, ukuran_kb, ringkas}`. Lewat XHR supaya
   * kemajuan unggah (`onProgress(persen)`) bisa ditampilkan; token, alamat, dan penanganan sesi habis memakai
   * cara yang sama dengan `apiFetch`. `signal` (AbortController) membatalkan unggahan.
   */
  unggahLampiran: (file, { onProgress, signal } = {}) => unggahXhr(`${BASE}/lampiran`, file, { onProgress, signal }),
  /** Hapus lampiran yang BELUM terkirim (hanya pemilik). */
  hapusLampiran: (id) => apiFetch(`${BASE}/lampiran/${encodeURIComponent(id)}`, { method: 'DELETE' }),

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

const safeName = (s, cadangan = 'laporan') => String(s || cadangan).replace(/[\\/:*?"<>|]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 80) || cadangan;

/** GET bertoken ke backend aplikasi ini → Response (galat → ApiError berpesan ramah dari server bila ada). */
async function ambilBertoken(url, pesanGagal) {
  const res = await apiFetch(url, { rawResponse: true, headers: { Accept: '*/*' } });
  if (!res.ok) {
    let detail = pesanGagal;
    try { const j = await res.json(); detail = (typeof j?.detail === 'string' && j.detail) || j?.pesan || detail; } catch { /* bukan JSON */ }
    throw new ApiError(res.status, detail, null);
  }
  return res;
}

/** Simpan blob sebagai unduhan peramban. */
function simpanBlob(blob, name) {
  const href = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = href;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

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
  const res = await ambilBertoken(url, 'Laporan gagal diunduh.');
  const blob = await res.blob();
  const ext = format === 'xlsx' ? 'xlsx' : 'pdf';
  simpanBlob(blob, fileNameFrom(res, `${safeName(judul)}.${ext}`));
}

// ── Tahap E (Kontrak K3): berkas keluaran AI (hasil hitung dengan kode) ──

const alamatBerkas = (b) => b?.url || (b?.id ? `/api/asisten-ai/berkas/${encodeURIComponent(b.id)}` : '');

/** Nama unduhan cadangan (bila server tidak memberi Content-Disposition): nama aman + ekstensi format. */
function namaUnduhan(nama, format) {
  const s = String(nama || '').trim();
  const ext = ekstensi(s) || String(format || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  const dasar = ext && s.toLowerCase().endsWith(`.${ext}`) ? s.slice(0, -(ext.length + 1)) : s;
  return `${safeName(dasar, 'berkas-asisten-ai')}${ext ? `.${ext}` : ''}`;
}

/** Unduh berkas buatan AI (`{id, nama, format, url}`) lewat fetch bertoken → blob. Alamat luar dibuka tanpa token. */
export async function unduhBerkas(berkas) {
  const url = alamatBerkas(berkas);
  if (!url) throw new ApiError(0, 'Alamat berkas tidak tersedia.', null);
  if (!isOwnApi(url)) {
    window.open(url, '_blank', 'noopener,noreferrer');
    return;
  }
  const res = await ambilBertoken(url, 'Berkas gagal diunduh.');
  const blob = await res.blob();
  simpanBlob(blob, fileNameFrom(res, namaUnduhan(berkas?.nama, berkas?.format)));
}

/**
 * Isi berkas gambar buatan AI untuk pratinjau kecil di kartu (Blob). Hanya dari backend aplikasi ini — alamat luar
 * tidak dimuat (`null`), supaya token dan data tidak pernah dikirim ke tempat lain.
 */
export async function ambilBlobBerkas(berkas) {
  const url = alamatBerkas(berkas);
  if (!url || !isOwnApi(url)) return null;
  const res = await ambilBertoken(url, 'Pratinjau gagal dimuat.');
  return res.blob();
}

// ── Tahap E (Kontrak K2): unggah lampiran dengan kemajuan ──

function pesanDariBadan(body, cadangan) {
  const d = body?.detail ?? body?.pesan;
  return typeof d === 'string' && d.trim() ? d : cadangan; // daftar galat validasi = istilah program → cadangan
}

const galatBatal = () => Object.assign(new ApiError(0, 'Unggahan dibatalkan.', null), { dibatalkan: true });

function unggahXhr(endpoint, file, { onProgress, signal } = {}) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(galatBatal()); return; }
    const xhr = new XMLHttpRequest();
    const batal = () => xhr.abort();
    const lepas = () => signal?.removeEventListener?.('abort', batal);
    xhr.open('POST', buildApiUrl(endpoint));
    const token = resolveToken();
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.setRequestHeader('Accept', 'application/json');
    if (onProgress && xhr.upload) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && e.total) onProgress(Math.min(100, Math.round((e.loaded / e.total) * 100)));
      };
    }
    xhr.onload = () => {
      lepas();
      let body = null;
      try { body = JSON.parse(xhr.responseText); } catch { /* bukan JSON (mis. halaman galat proxy) */ }
      if (xhr.status >= 200 && xhr.status < 300) { resolve(body || {}); return; }
      if (xhr.status === 401) {
        notifyUnauthorized();
        reject(new ApiError(401, pesanDariBadan(body, 'Sesi habis. Silakan login kembali.'), body));
        return;
      }
      const cadangan = {
        413: `Berkas lebih dari ${MAKS_UKURAN_MB} MB.`,
        400: 'Jenis berkas ini tidak bisa dilampirkan.',
        415: 'Jenis berkas ini tidak bisa dilampirkan.',
      }[xhr.status] || 'Berkas gagal diunggah. Coba lagi.';
      reject(new ApiError(xhr.status, pesanDariBadan(body, cadangan), body));
    };
    xhr.onerror = () => { lepas(); reject(new ApiError(0, 'Tidak dapat terhubung ke server. Periksa koneksi Anda.', null)); };
    xhr.onabort = () => { lepas(); reject(galatBatal()); };
    signal?.addEventListener?.('abort', batal, { once: true });
    const fd = new FormData();
    fd.append('berkas', file);
    xhr.send(fd);
  });
}

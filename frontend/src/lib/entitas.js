/**
 * entitas — pilihan CV pembukuan di Portal Keuangan (Tahap 8 fase 1, keputusan owner 7 Nov 2026).
 *
 * Satu aplikasi memegang DUA buku: CV Dewi Aditya (DA) dan CV Sukma (SMU). Portal Keuangan memakai
 * satu pilihan CV global: "CV Dewi Aditya" / "CV Sukma" / "Gabungan (lihat saja)".
 *
 * Supaya ±40 layar keuangan tidak perlu menyisipkan `?entity=` ke setiap panggilan API (pekerjaan
 * yang gampang terlewat satu-dua), pilihan dikirim lewat SATU header `X-CV` — pola yang sama dengan
 * header override CMT di `lib/api.js`. Backend membacanya di `core/entities.entity_from_request`
 * (urutan: query `entity` → body `entity` → header `X-CV` → bawaan DA).
 *
 * WAJIB dipasangkan: cangkang Portal Keuangan (`CvProvider`) menyetel CV aktif saat portal dibuka dan
 * MEMBERSIHKANNYA saat portal ditutup, sehingga portal lain tidak pernah mengirim header ini.
 * Pilihan disimpan per peramban (localStorage, selalu dalam try/catch).
 */
import axios from 'axios';
import { createContext, createElement, useContext, useEffect, useLayoutEffect, useMemo, useState } from 'react';

export const CV_DA = 'DA';
export const CV_SMU = 'SMU';
export const CV_ALL = 'ALL';
export const CV_DEFAULT = CV_DA;
export const CV_HEADER = 'X-CV';
const STORAGE_KEY = 'erp_keuangan_cv';
const BACKEND = process.env.REACT_APP_BACKEND_URL || '';

/** Cadangan statis — bila `/api/entities` gagal, pilihan tetap tampil. */
export const CV_OPTIONS_FALLBACK = [
  { code: CV_DA, label: 'CV Dewi Aditya', name: 'CV Dewi Aditya Official' },
  { code: CV_SMU, label: 'CV Sukma', name: 'CV Sukma Mitra Utama' },
  { code: CV_ALL, label: 'Gabungan (lihat saja)', name: 'Gabungan (lihat saja)', readOnly: true },
];

export const READONLY_HINT = 'Gabungan hanya untuk dilihat — pilih satu CV untuk menambah atau mengubah';

const VALID = new Set([CV_DA, CV_SMU, CV_ALL]);

export function normalizeCv(v, fallback = CV_DEFAULT) {
  const s = String(v || '').trim().toUpperCase();
  return VALID.has(s) ? s : fallback;
}

/** Label pendek CV untuk layar ("CV Dewi Aditya", "CV Sukma", "Gabungan (lihat saja)"). */
export function cvLabel(code, options = CV_OPTIONS_FALLBACK) {
  const c = normalizeCv(code);
  return (options.find((o) => o.code === c) || CV_OPTIONS_FALLBACK.find((o) => o.code === c) || {}).label || c;
}

/** Label pemilik dokumen/rekening: kosong = DA (data lama). */
export const ownerLabel = (code) => cvLabel(normalizeCv(code, CV_DA));

export function readStoredCv() {
  try {
    return normalizeCv(window.localStorage.getItem(STORAGE_KEY));
  } catch {
    return CV_DEFAULT;
  }
}

export function storeCv(code) {
  try {
    window.localStorage.setItem(STORAGE_KEY, normalizeCv(code));
  } catch {
    /* penyimpanan diblokir (mode privat) — pilihan berlaku sampai halaman dimuat ulang */
  }
}

// ─── CV aktif untuk header (hanya selama Portal Keuangan terbuka) ─────────────
let _activeCv = null;

export function setActiveCv(code) {
  _activeCv = code ? normalizeCv(code) : null;
}

export function clearActiveCv() {
  _activeCv = null;
}

export function getActiveCv() {
  return _activeCv;
}

function urlOf(input) {
  if (typeof input === 'string') return input;
  if (input && typeof input.url === 'string') return input.url;
  if (input && typeof input.href === 'string') return input.href;
  return '';
}

/** Permintaan ke API backend aplikasi ini (relatif `/api/…` atau `${BACKEND}/api/…` / origin sendiri). */
export function isBackendApiUrl(url) {
  const u = String(url || '');
  if (u.startsWith('/api/')) return true;
  if (BACKEND && u.startsWith(`${BACKEND}/api/`)) return true;
  try {
    if (typeof window !== 'undefined' && u.startsWith(`${window.location.origin}/api/`)) return true;
  } catch {
    /* lingkungan tanpa window.location */
  }
  return false;
}

function hasHeader(headers, name) {
  if (!headers) return false;
  const low = name.toLowerCase();
  if (typeof headers.has === 'function') return headers.has(name);
  if (Array.isArray(headers)) return headers.some(([k]) => String(k).toLowerCase() === low);
  return Object.keys(headers).some((k) => k.toLowerCase() === low);
}

/** Pasang penyisip header `X-CV` pada window.fetch dan axios (sekali). */
export function installCvHeader() {
  if (typeof window === 'undefined' || window.__cvHeaderInstalled) return;
  window.__cvHeaderInstalled = true;

  const origFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const cv = _activeCv;
    if (!cv || !isBackendApiUrl(urlOf(input))) return origFetch(input, init);
    const seed = init?.headers || (typeof Request !== 'undefined' && input instanceof Request ? input.headers : undefined);
    if (hasHeader(seed, CV_HEADER)) return origFetch(input, init);
    const headers = new Headers(seed || {});
    headers.set(CV_HEADER, cv);
    return origFetch(input, { ...(init || {}), headers });
  };

  axios.interceptors.request.use((config) => {
    const cv = _activeCv;
    if (!cv) return config;
    const url = config.url || '';
    const full = /^https?:/i.test(url) ? url : `${config.baseURL || ''}${url}`;
    if (!isBackendApiUrl(full) && !isBackendApiUrl(url)) return config;
    const h = config.headers || {};
    if (hasHeader(h, CV_HEADER)) return config;
    if (typeof h.set === 'function') h.set(CV_HEADER, cv);
    else config.headers = { ...h, [CV_HEADER]: cv };
    return config;
  });
}

/** Tambahkan `entity=<cv>` ke URL (untuk unduhan lewat window.open/href yang tidak membawa header). */
export function withCvParam(url, cv) {
  const c = cv || _activeCv;
  if (!c || /[?&]entity=/.test(url)) return url;
  return `${url}${url.includes('?') ? '&' : '?'}entity=${encodeURIComponent(c)}`;
}

/** `entity=<cv>` untuk pemilih akun: hanya DA/SMU (Gabungan = tanpa saringan). */
export function cvAccountParam(cv) {
  return cv === CV_DA || cv === CV_SMU ? `entity=${cv}` : '';
}

// ─── Konteks React ───────────────────────────────────────────────────────────
const CvContext = createContext(null);

/** `{cv, setCv, readOnly, options, label}` di Portal Keuangan; `null` di portal lain. */
export function useCv() {
  return useContext(CvContext);
}

/** CV yang berlaku di layar ini: CV terpilih di Portal Keuangan, atau `fallback` di luar keuangan. */
export function useCvOr(fallback = CV_DEFAULT) {
  const ctx = useContext(CvContext);
  return ctx ? ctx.cv : fallback;
}

let _optionsCache = null;

export function CvProvider({ children }) {
  const [cv, setCvState] = useState(() => readStoredCv());
  const [options, setOptions] = useState(_optionsCache || CV_OPTIONS_FALLBACK);

  // Disetel SAAT RENDER, bukan di effect: effect anak (fetch pertama layar) berjalan lebih dulu
  // daripada effect induk — tanpa ini permintaan pertama terkirim tanpa header CV.
  if (_activeCv !== cv) setActiveCv(cv);

  useLayoutEffect(() => {
    setActiveCv(cv);
    return () => clearActiveCv();
  }, [cv]);

  useEffect(() => {
    if (_optionsCache) return undefined;
    let off = false;
    let token = null;
    try { token = window.localStorage.getItem('erp_token'); } catch { token = null; }
    fetch(`${BACKEND}/api/entities`, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        const rows = Array.isArray(d?.entities) ? d.entities : null;
        if (!rows || off) return;
        // Tahap 8 fase 3: backend hanya mengirim CV yang DIIZINKAN untuk pengguna (`users.allowed_entities`;
        // kosong = kedua CV + Gabungan) — pilihan lain tidak ditampilkan.
        const merged = CV_OPTIONS_FALLBACK.filter((fb) => rows.some((x) => x.code === fb.code)).map((fb) => {
          const row = rows.find((x) => x.code === fb.code);
          return { ...fb, name: row.name || fb.name, label: fb.code === CV_ALL ? fb.label : (row.short || fb.label) };
        });
        if (!merged.length) return;
        _optionsCache = merged;
        setOptions(merged);
      })
      .catch(() => {});
    return () => { off = true; };
  }, []);

  // CV tersimpan yang tidak lagi diizinkan → pindah ke CV pertama yang diizinkan.
  useEffect(() => {
    if (options.length && !options.some((o) => o.code === cv)) {
      const next = options[0].code;
      storeCv(next);
      setActiveCv(next);
      setCvState(next);
    }
  }, [options, cv]);

  const value = useMemo(() => ({
    cv,
    readOnly: cv === CV_ALL,
    options,
    label: cvLabel(cv, options),
    setCv: (next) => {
      const n = normalizeCv(next);
      storeCv(n);
      setActiveCv(n);
      setCvState(n);
    },
  }), [cv, options]);

  return createElement(CvContext.Provider, { value }, children);
}

/** Isi layar dipasang ulang saat CV berganti → setiap layar memuat ulang datanya. */
export function CvKeyed({ children }) {
  const ctx = useContext(CvContext);
  return createElement('div', { key: ctx ? ctx.cv : 'none', className: 'contents', 'data-cv': ctx ? ctx.cv : undefined }, children);
}

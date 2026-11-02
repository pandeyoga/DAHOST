/**
 * scanCode.js — aturan kode scan di sisi layar (Paket 3a, 2026-11-02).
 *
 * CERMIN dari `backend/core/scan_resolver.normalize_code` — ubah keduanya bersamaan.
 * Dipakai komponen scanner bersama (UniversalScanner) sebelum `onScan` dipanggil,
 * dan oleh layar yang mencocokkan kode di daftar yang sudah dimuat (put-away,
 * pick list, material issue) supaya `da-2101-…`, `]C0DA-2101-…`, atau kode
 * berakhiran CR/TAB dari scanner tetap cocok.
 */

const AIM_PREFIX = /^\][A-Za-z][0-9A-Za-z]/;
// eslint-disable-next-line no-control-regex
const CTRL = /[\u0000-\u001f\u007f]/g;

export function normalizeScanCode(raw) {
  let s = String(raw ?? '').replace(/﻿/g, '').trim();
  s = s.replace(AIM_PREFIX, '');
  s = s.replace(CTRL, '').trim();
  if (s.length > 2 && s.startsWith('*') && s.endsWith('*')) s = s.slice(1, -1).trim();
  return s;
}

/** Kunci pembanding: dinormalisasi + huruf besar. */
export function scanKey(raw) {
  return normalizeScanCode(raw).toUpperCase();
}

/** Dua kode dianggap sama bila kuncinya sama (tanpa beda huruf besar/kecil). */
export function sameScanCode(a, b) {
  const ka = scanKey(a);
  return ka !== '' && ka === scanKey(b);
}

// ─── Umpan balik bunyi/getar ────────────────────────────────────────────────
let audioCtx = null;
function beep(freq, ms, volume = 0.08) {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    audioCtx = audioCtx || new Ctx();
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = 'square';
    osc.frequency.value = freq;
    gain.gain.value = volume;
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start();
    osc.stop(audioCtx.currentTime + ms / 1000);
  } catch (_) { /* perangkat tanpa audio — abaikan */ }
}

/**
 * scanFeedback('ok' | 'error' | 'dup') — bunyi + getar (bila didukung perangkat).
 * Layar scan memanggil 'ok'/'error' SETELAH server menjawab, supaya petugas tahu
 * scan benar-benar tercatat, bukan hanya terbaca.
 */
export function scanFeedback(kind = 'ok') {
  if (kind === 'error') {
    beep(220, 220, 0.12);
    try { navigator.vibrate?.([90, 60, 90]); } catch (_) { /* noop */ }
  } else if (kind === 'dup') {
    beep(440, 60, 0.05);
  } else {
    beep(1320, 70);
    try { navigator.vibrate?.(40); } catch (_) { /* noop */ }
  }
}

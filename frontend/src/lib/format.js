/**
 * format.js — Utilitas format ANGKA / RUPIAH / TANGGAL kanonik (locale id-ID).
 * =============================================================================
 * SATU SUMBER KEBENARAN untuk format Rupiah & angka di seluruh aplikasi.
 * Sebelumnya formatter Rupiah tersebar (fmtRp/fmtIDR/formatCurrency lokal) di
 * ~100+ file. Gunakan util ini untuk file baru & migrasi bertahap.
 *
 * Standar Rupiah: "Rp 1.500.000"  (spasi setelah "Rp", tanpa desimal,
 * pemisah ribuan titik ala Indonesia).
 *
 * Contoh:
 *   formatRupiah(1500000)                 -> "Rp 1.500.000"
 *   formatRupiah(null)                    -> "Rp 0"
 *   formatRupiah(null, { dash: true })    -> "—"
 *   formatRupiah(1500.5, { decimals: 2 }) -> "Rp 1.500,50"
 *   formatNumber(1234567)                 -> "1.234.567"
 *   formatNumber(1.2345, { maximumFractionDigits: 2 }) -> "1,23"
 *   formatRupiahShort(1500000)            -> "Rp 1,5 jt"
 *   formatDateID('2026-07-19')            -> "19 Jul 2026"
 *   formatDateTimeID('2026-07-19T08:30')  -> "19 Jul 2026, 08.30"
 *   (tanggal & jam selalu ditampilkan dalam WIB — keputusan owner No.54(a))
 *
 * Input uang (No.45: pengguna mengetik angka saja, titik ribuan muncul sendiri):
 *   moneyTyping('1500000')        -> { plain: '1500000', display: '1.500.000' }
 *   moneyTyping('12,5', { decimals: 2 }) -> { plain: '12.5', display: '12,5' }
 *   moneyDisplay(1500000)         -> '1.500.000'
 */

export const LOCALE = 'id-ID';

/** Konversi nilai apa pun ke number berhingga, atau null bila tak valid. */
function toFiniteNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

/**
 * Format angka murni (tanpa "Rp"). Default tanpa desimal, pemisah ribuan id-ID.
 * @param {number|string} value
 * @param {{ minimumFractionDigits?: number, maximumFractionDigits?: number, fallback?: string }} [opts]
 */
export function formatNumber(value, opts = {}) {
  const n = toFiniteNumber(value);
  if (n === null) return opts.fallback ?? '0';
  const {
    minimumFractionDigits = 0,
    maximumFractionDigits = Math.max(minimumFractionDigits, 0),
  } = opts;
  return n.toLocaleString(LOCALE, { minimumFractionDigits, maximumFractionDigits });
}

/**
 * Format Rupiah kanonik: "Rp 1.500.000".
 * @param {number|string} value
 * @param {{ decimals?: number, dash?: boolean, withSpace?: boolean }} [opts]
 *   - decimals: jumlah desimal (default 0)
 *   - dash: bila true, nilai kosong/tidak valid -> "—" (bukan "Rp 0")
 *   - withSpace: spasi setelah "Rp" (default true)
 */
export function formatRupiah(value, opts = {}) {
  const n = toFiniteNumber(value);
  const sep = opts.withSpace === false ? '' : ' ';
  if (n === null) return opts.dash ? '—' : `Rp${sep}0`;
  const decimals = opts.decimals ?? 0;
  const digits = formatNumber(n, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  return `Rp${sep}${digits}`;
}

/** Alias eksplisit — sebagian modul lama memakai nama ini. */
export const formatCurrency = formatRupiah;
export const formatIDR = formatRupiah;

/**
 * Format Rupiah ringkas untuk kartu/dashboard: "Rp 1,5 jt", "Rp 2,3 rb", "Rp 4 M".
 * @param {number|string} value
 */
export function formatRupiahShort(value) {
  const n = toFiniteNumber(value);
  if (n === null) return 'Rp 0';
  const abs = Math.abs(n);
  const sign = n < 0 ? '-' : '';
  const fmt = (x) => x.toLocaleString(LOCALE, { maximumFractionDigits: 1 });
  if (abs >= 1e12) return `${sign}Rp ${fmt(abs / 1e12)} T`;
  if (abs >= 1e9)  return `${sign}Rp ${fmt(abs / 1e9)} M`;
  if (abs >= 1e6)  return `${sign}Rp ${fmt(abs / 1e6)} jt`;
  if (abs >= 1e3)  return `${sign}Rp ${fmt(abs / 1e3)} rb`;
  return `${sign}Rp ${fmt(abs)}`;
}

/**
 * Persen gaya Indonesia: 24.19 → "24,19%" (2026-11-04, audit Keuangan: dulu "24.19%" bertitik).
 * @param {number|string} value  nilai persen (24.19 berarti 24,19%)
 * @param {number} [digits=2]    desimal maksimum
 */
export function formatPercent(value, digits = 2) {
  const n = toFiniteNumber(value);
  if (n === null) return '—';
  return `${n.toLocaleString(LOCALE, { maximumFractionDigits: digits })}%`;
}

/**
 * Format tanggal id-ID. Default: "19 Jul 2026".
 * @param {string|number|Date} value
 * @param {Intl.DateTimeFormatOptions & { fallback?: string }} [opts]
 */
export function formatDateID(value, opts = {}) {
  if (!value) return opts.fallback ?? '—';
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return opts.fallback ?? '—';
  const { fallback, ...rest } = opts;
  const options = Object.keys(rest).length ? rest : { day: '2-digit', month: 'short', year: 'numeric' };
  // No.54(a): tanggal selalu dibaca dalam WIB, apa pun zona waktu perangkat.
  return d.toLocaleDateString(LOCALE, { timeZone: 'Asia/Jakarta', ...options });
}

/**
 * Format tanggal + jam id-ID. Default: "19 Jul 2026, 08.30".
 * @param {string|number|Date} value
 * @param {{ fallback?: string }} [opts]
 */
export function formatDateTimeID(value, opts = {}) {
  if (!value) return opts.fallback ?? '—';
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return opts.fallback ?? '—';
  return d.toLocaleString(LOCALE, {
    timeZone: 'Asia/Jakarta',
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

/**
 * Parse string angka locale-ID -> number (atau null bila tak valid).
 * Kebalikan dari formatRupiah/formatNumber; dipakai untuk membaca input user
 * atau data impor. Locale ID: '.' = ribuan, ',' = desimal. Toleran currency,
 * gaya US, dan negatif via kurung "(1.000)".
 *   parseIDNumber("Rp 1.500.000") -> 1500000
 *   parseIDNumber("1.234.567,89") -> 1234567.89
 *   parseIDNumber("150,5")        -> 150.5
 *   parseIDNumber("(1.000)")      -> -1000
 * @param {string|number} value
 * @param {{ fallback?: number|null }} [opts]
 * @returns {number|null}
 */
export function parseIDNumber(value, opts = {}) {
  const fallback = opts.fallback ?? null;
  if (value === null || value === undefined) return fallback;
  if (typeof value === 'number') return Number.isFinite(value) ? value : fallback;
  let s = String(value).trim();
  if (s === '' || s.toLowerCase() === 'nan' || s.toLowerCase() === 'none') return fallback;

  let neg = false;
  if (s.startsWith('(') && s.endsWith(')')) { neg = true; s = s.slice(1, -1).trim(); }
  s = s.replace(/rp|idr/gi, '').replace(/\u00a0/g, ' ').trim();
  if (s.startsWith('-')) { neg = true; s = s.slice(1).trim(); }
  else if (s.startsWith('+')) { s = s.slice(1).trim(); }

  s = s.replace(/[^0-9.,]/g, '');
  if (s === '') return fallback;

  const hasDot = s.includes('.');
  const hasCom = s.includes(',');
  if (hasDot && hasCom) {
    if (s.lastIndexOf(',') > s.lastIndexOf('.')) s = s.replace(/\./g, '').replace(',', '.');
    else s = s.replace(/,/g, '');
  } else if (hasCom) {
    s = (s.split(',').length - 1) > 1 ? s.replace(/,/g, '') : s.replace(',', '.');
  } else if (hasDot) {
    if ((s.split('.').length - 1) > 1) s = s.replace(/\./g, '');
    else if (s.split('.')[1].length === 3) s = s.replace('.', '');
    // else: single dot with !=3 digits => decimal, keep
  }
  const n = Number(s);
  if (!Number.isFinite(n)) return fallback;
  return neg ? -n : n;
}

/** Alias — parse string Rupiah ke number. */
export const parseRupiah = parseIDNumber;

// ── Input uang dengan pemisah ribuan otomatis (keputusan owner No.45) ─────────
// Dipakai komponen `components/ui/money-input.jsx`. Nilai yang disimpan form tetap
// string angka POLOS bergaya JS ('1500000', '12.5'); yang dilihat pengguna bergaya
// id-ID ('1.500.000', '12,5').

const MAX_INT_DIGITS = 15; // batas aman Number.MAX_SAFE_INTEGER

function groupThousands(intDigits) {
  return intDigits.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
}

/**
 * Nilai polos (number atau string '1500000' / '12.5') → teks tampilan input ('1.500.000' / '12,5').
 * Kosong/tidak valid → ''.
 */
export function moneyDisplay(value, opts = {}) {
  const { decimals = 0 } = opts;
  if (value === null || value === undefined || value === '') return '';
  const n = typeof value === 'number' ? value : Number(String(value).trim());
  if (!Number.isFinite(n)) return '';
  const neg = n < 0;
  const abs = Math.abs(n);
  let [intPart, frac = ''] = (decimals > 0 ? String(Number(abs.toFixed(decimals))) : String(Math.round(abs))).split('.');
  if (intPart.includes('e')) return String(n); // angka sangat besar — biarkan apa adanya
  const out = groupThousands(intPart) + (frac ? `,${frac}` : '');
  return neg ? `-${out}` : out;
}

/**
 * Teks yang sedang DIKETIK pengguna → { plain, display }.
 *   - titik selalu dianggap pemisah ribuan (pengguna tidak perlu mengetiknya);
 *   - koma = desimal (hanya bila `decimals` > 0). Titik yang BARU DIKETIK di keyboard
 *     HP tanpa koma diubah jadi koma oleh komponen, bukan di sini — supaya menghapus
 *     satu digit dari '1.500' tetap menjadi '150', bukan '1,50';
 *   - nol di depan dibuang, desimal dipotong sesuai `decimals`;
 *   - minus hanya bila `allowNegative`.
 * `plain` = '' bila kosong; '-' / '0,' sementara tetap dipertahankan di `display`.
 */
export function moneyTyping(text, opts = {}) {
  const { decimals = 0, allowNegative = false } = opts;
  let s = String(text ?? '').replace(/\s|rp/gi, '');
  const neg = allowNegative && s.trim().startsWith('-');
  s = s.replace(/[^0-9.,]/g, '');

  let intRaw = s;
  let fracRaw = null;
  const ci = decimals > 0 ? s.indexOf(',') : -1;
  if (ci >= 0) {
    intRaw = s.slice(0, ci);
    fracRaw = s.slice(ci + 1);
  }
  let intDigits = intRaw.replace(/\D/g, '').replace(/^0+(?=\d)/, '').slice(0, MAX_INT_DIGITS);
  const fracDigits = fracRaw === null ? null : fracRaw.replace(/\D/g, '').slice(0, decimals);

  if (!intDigits && fracDigits !== null) intDigits = '0';
  if (!intDigits) return { plain: '', display: neg ? '-' : '' };

  const sign = neg ? '-' : '';
  const display = sign + groupThousands(intDigits) + (fracDigits !== null ? `,${fracDigits}` : '');
  const plain = sign + intDigits + (fracDigits ? `.${fracDigits}` : '');
  return { plain, display };
}

/**
 * Posisi kursor setelah format ulang: letakkan kursor setelah `count` karakter
 * bermakna (digit, koma, minus) — sehingga titik ribuan yang muncul/hilang tidak
 * membuat kursor melompat.
 */
export function moneyCaret(display, count) {
  if (count <= 0) return 0;
  let seen = 0;
  for (let i = 0; i < display.length; i += 1) {
    if (/[0-9,-]/.test(display[i])) seen += 1;
    if (seen >= count) return i + 1;
  }
  return display.length;
}

/** Jumlah karakter bermakna (digit, koma, minus) di kiri posisi `pos`. */
export function moneyMeaningfulBefore(text, pos) {
  return (String(text).slice(0, pos).match(/[0-9,-]/g) || []).length;
}

const formatUtils = {
  LOCALE,
  formatNumber,
  formatRupiah,
  formatCurrency,
  formatIDR,
  formatRupiahShort,
  formatDateID,
  formatDateTimeID,
  parseIDNumber,
  parseRupiah,
  moneyDisplay,
  moneyTyping,
};

export default formatUtils;

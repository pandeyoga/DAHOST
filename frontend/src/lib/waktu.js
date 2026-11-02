/**
 * waktu.js — SSOT tanggal kalender WIB (Asia/Jakarta) di frontend.
 * =============================================================================
 * Pasangan `backend/utils/waktu.py`. Keputusan owner No.54(a): semua tanggal
 * operasional = WIB, TIDAK bergantung zona waktu browser/perangkat.
 *
 * JANGAN pakai `new Date().toISOString().slice(0, 10)` untuk "hari ini": itu
 * tanggal UTC, sehingga pukul 00:00–06:59 WIB hasilnya = KEMARIN. Jangan pula
 * membangun tanggal lokal `new Date(y, m, 1)` lalu `toISOString()` — di browser
 * WIB hasilnya mundur sehari (1 Nov → 31 Okt).
 *
 * Semua fungsi mengembalikan string kalender murni:
 *   'YYYY-MM-DD' (nilai <input type="date">) atau 'YYYY-MM' (<input type="month">).
 * Aritmetika tanggal dikerjakan pada bagian (y, m, d) di UTC — bebas DST/zona.
 *
 * Contoh (sekarang = 2026-11-02 06:30 WIB = 2026-11-01T23:30Z):
 *   todayWIB()                 -> '2026-11-02'
 *   thisMonthWIB()             -> '2026-11'
 *   daysAgoWIB(30)             -> '2026-10-03'
 *   monthStartWIB()            -> '2026-11-01'
 *   monthEndISO('2026-02')     -> '2026-02-28'
 *   lastMonthPeriodWIB()       -> { from: '2026-10-01', to: '2026-10-31' }
 *   toWIBDate('2026-11-01T23:30:00Z') -> '2026-11-02'
 */

export const WIB_TZ = 'Asia/Jakarta';

const pad = (n) => String(n).padStart(2, '0');

const PARTS_FMT = new Intl.DateTimeFormat('en-CA', {
  timeZone: WIB_TZ, year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
});

function toDate(value) {
  if (value === null || value === undefined || value === '') return null;
  const d = value instanceof Date ? value : new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** Bagian waktu (y, m, d, hh, mm) menurut WIB untuk sebuah instan. */
export function wibDateParts(now = new Date()) {
  const d = toDate(now) || new Date();
  const parts = PARTS_FMT.formatToParts(d);
  const get = (t) => Number(parts.find((p) => p.type === t)?.value);
  return { y: get('year'), m: get('month'), d: get('day'), hh: get('hour'), mm: get('minute') };
}

/** 'YYYY-MM-DD' hari ini (WIB). */
export function todayWIB(now = new Date()) {
  const { y, m, d } = wibDateParts(now);
  return `${y}-${pad(m)}-${pad(d)}`;
}

/** 'YYYY-MM' bulan ini (WIB). */
export function thisMonthWIB(now = new Date()) {
  return todayWIB(now).slice(0, 7);
}

/** Tahun berjalan (WIB). */
export function thisYearWIB(now = new Date()) {
  return wibDateParts(now).y;
}

/**
 * Tanggal kalender WIB dari instan apa pun (Date / ISO string / epoch ms) → 'YYYY-MM-DD'.
 * String yang SUDAH 'YYYY-MM-DD' dikembalikan apa adanya (itu tanggal kalender, bukan instan).
 * Nilai kosong/tidak valid → ''.
 */
export function toWIBDate(value) {
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const d = toDate(value);
  return d ? todayWIB(d) : '';
}

/** 'YYYY-MM-DDTHH:mm' waktu WIB sekarang — nilai bawaan <input type="datetime-local">. */
export function nowWIBLocalInput(now = new Date()) {
  const { y, m, d, hh, mm } = wibDateParts(now);
  return `${y}-${pad(m)}-${pad(d)}T${pad(hh)}:${pad(mm)}`;
}

/** Nilai <input type="datetime-local"> untuk instan apa pun (ISO/Date), dibaca dalam WIB. Kosong → ''. */
export function toWIBLocalInput(value) {
  const d = toDate(value);
  return d ? nowWIBLocalInput(d) : '';
}

/**
 * Kebalikan `toWIBLocalInput`: 'YYYY-MM-DDTHH:mm' yang diketik pengguna (jam WIB) → ISO instan UTC
 * untuk dikirim ke API. Tidak bergantung zona perangkat (beda dengan `new Date(local).toISOString()`).
 * Kosong/tidak valid → null.
 */
export function fromWIBLocalInput(local) {
  if (!local) return null;
  const s = String(local).trim();
  const withSec = /T\d{2}:\d{2}$/.test(s) ? `${s}:00` : s;
  const d = new Date(`${withSec}+07:00`);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

// ── Aritmetika kalender murni (tanpa zona) ───────────────────────────────────
function splitISO(iso) {
  const [y, m, d] = String(iso).slice(0, 10).split('-').map(Number);
  return { y, m, d };
}

/** Geser tanggal 'YYYY-MM-DD' sebanyak `n` hari (boleh negatif). */
export function addDaysISO(iso, n) {
  const { y, m, d } = splitISO(iso);
  const t = new Date(Date.UTC(y, m - 1, d + Number(n || 0)));
  return `${t.getUTCFullYear()}-${pad(t.getUTCMonth() + 1)}-${pad(t.getUTCDate())}`;
}

/** Geser bulan 'YYYY-MM' sebanyak `n` bulan (boleh negatif). */
export function addMonthsYM(ym, n) {
  const [y, m] = String(ym).slice(0, 7).split('-').map(Number);
  const t = new Date(Date.UTC(y, m - 1 + Number(n || 0), 1));
  return `${t.getUTCFullYear()}-${pad(t.getUTCMonth() + 1)}`;
}

/** Hari terakhir bulan 'YYYY-MM' → 'YYYY-MM-DD'. */
export function monthEndISO(ym) {
  const [y, m] = String(ym).slice(0, 7).split('-').map(Number);
  const t = new Date(Date.UTC(y, m, 0));
  return `${t.getUTCFullYear()}-${pad(t.getUTCMonth() + 1)}-${pad(t.getUTCDate())}`;
}

/** Selisih hari kalender b − a (keduanya 'YYYY-MM-DD'). */
export function daysBetweenISO(a, b) {
  const p = splitISO(a); const q = splitISO(b);
  return Math.round((Date.UTC(q.y, q.m - 1, q.d) - Date.UTC(p.y, p.m - 1, p.d)) / 86400000);
}

// ── Pintasan yang sering dipakai form/filter ─────────────────────────────────
/** 'YYYY-MM-DD' n hari sebelum hari ini (WIB). */
export function daysAgoWIB(n, now = new Date()) {
  return addDaysISO(todayWIB(now), -Number(n || 0));
}

/** 'YYYY-MM-DD' n hari setelah hari ini (WIB) — mis. jatuh tempo bawaan. */
export function daysAheadWIB(n, now = new Date()) {
  return addDaysISO(todayWIB(now), Number(n || 0));
}

/** Tanggal 1 bulan ini (WIB). */
export function monthStartWIB(now = new Date()) {
  return `${thisMonthWIB(now)}-01`;
}

/** Hari terakhir bulan ini (WIB). */
export function monthEndWIB(now = new Date()) {
  return monthEndISO(thisMonthWIB(now));
}

/** 1 Januari tahun ini (WIB). */
export function yearStartWIB(now = new Date()) {
  return `${thisYearWIB(now)}-01-01`;
}

/** Periode bulan lalu penuh (WIB): { from: 'YYYY-MM-01', to: 'YYYY-MM-<akhir>' }. */
export function lastMonthPeriodWIB(now = new Date()) {
  const ym = addMonthsYM(thisMonthWIB(now), -1);
  return { from: `${ym}-01`, to: monthEndISO(ym) };
}

const waktu = {
  WIB_TZ, wibDateParts, todayWIB, thisMonthWIB, thisYearWIB, toWIBDate, nowWIBLocalInput,
  toWIBLocalInput, fromWIBLocalInput,
  addDaysISO, addMonthsYM, monthEndISO, daysBetweenISO,
  daysAgoWIB, daysAheadWIB, monthStartWIB, monthEndWIB, yearStartWIB, lastMonthPeriodWIB,
};

export default waktu;

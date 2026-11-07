/**
 * sseFetch — POST + `fetch` streaming reader untuk `text/event-stream` (Asisten AI, Tahap A, 8 Nov 2026).
 *
 * `EventSource` bawaan peramban hanya bisa GET dan tidak bisa mengirim header Authorization, jadi jawaban
 * Asisten AI dibaca lewat `fetch` + `ReadableStream`. Token dan alamat memakai cara yang SAMA dengan
 * `lib/apiFetch.js` (resolveToken / buildApiUrl / notifyUnauthorized) — tidak ada cara kedua.
 *
 *   const ctrl = new AbortController();
 *   const { aborted } = await sseFetch('/asisten-ai/sessions/abc/messages', {
 *     body: { teks, cv: 'DA' },
 *     headers: { 'X-CV': 'DA' },
 *     signal: ctrl.signal,
 *     onEvent: ({ event, data }) => { ... },   // data = JSON hasil parse (atau teks mentah bila bukan JSON)
 *   });
 *   ctrl.abort();   // tombol "Hentikan": fetch diputus, janji selesai dengan { aborted: true } (tidak melempar)
 *
 * Pengurai mengikuti aturan SSE (WHATWG): baris dipisah \n, \r\n, atau \r; `event:`/`data:`/`id:`; baris
 * berawalan ':' = komentar; baris kosong mengirim satu pesan; beberapa `data:` digabung dengan \n. Bingkai
 * yang terpotong di antara dua potongan jaringan (termasuk \r\n yang terbelah dan huruf UTF-8 multi-byte)
 * disambung dulu sebelum diurai.
 */
import { ApiError, buildApiUrl, notifyUnauthorized, resolveToken } from './apiFetch';

/**
 * Pengurai SSE bertahap. `push(teks)` untuk tiap potongan, `end()` saat aliran selesai.
 * Bingkai terakhir tanpa baris kosong penutup tetap dikirim saat `end()` (lebih toleran dari standar).
 */
export function createSseParser(onMessage) {
  let buf = '';
  let event = '';
  let data = [];
  let lastId = '';
  let first = true;

  const dispatch = () => {
    if (data.length) onMessage({ event: event || 'message', data: data.join('\n'), id: lastId });
    event = '';
    data = [];
  };

  const line = (ln) => {
    if (ln === '') { dispatch(); return; }
    if (ln[0] === ':') return; // komentar / detak jantung
    const at = ln.indexOf(':');
    const field = at < 0 ? ln : ln.slice(0, at);
    let value = at < 0 ? '' : ln.slice(at + 1);
    if (value[0] === ' ') value = value.slice(1);
    if (field === 'event') event = value;
    else if (field === 'data') data.push(value);
    else if (field === 'id' && !value.includes('\0')) lastId = value;
    // 'retry' & bidang lain diabaikan (tidak ada sambung ulang otomatis)
  };

  return {
    push(chunk) {
      if (!chunk) return;
      buf += chunk;
      if (first) {
        if (buf.charCodeAt(0) === 0xfeff) buf = buf.slice(1);
        first = false;
      }
      // \r di ujung bisa jadi separuh \r\n — tahan sampai potongan berikutnya.
      let hold = '';
      if (buf.endsWith('\r')) { hold = '\r'; buf = buf.slice(0, -1); }
      const lines = buf.split(/\r\n|\r|\n/);
      buf = lines.pop() + hold;
      lines.forEach(line);
    },
    end() {
      const rest = buf.replace(/\r$/, '');
      buf = '';
      if (rest) line(rest);
      dispatch();
    },
  };
}

function parseData(raw) {
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

const isAbort = (e) => e && (e.name === 'AbortError' || e.code === 20);

/**
 * Kirim permintaan dan baca aliran SSE sampai selesai.
 * @returns {Promise<{aborted: boolean, status: number}>}
 * @throws {ApiError} saat gagal terhubung atau server menjawab bukan 2xx (pesan `detail` dari server).
 */
export async function sseFetch(endpoint, options = {}) {
  const {
    method = 'POST',
    body,
    token: tokenOverride,
    headers: extraHeaders = {},
    signal,
    onEvent,
    onOpen,
    skipOnUnauthorized = false,
  } = options;

  const token = resolveToken(tokenOverride);
  const headers = { Accept: 'text/event-stream' };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  Object.assign(headers, extraHeaders);

  let res;
  try {
    res = await fetch(buildApiUrl(endpoint), {
      method,
      headers,
      body: body === undefined ? undefined : (typeof body === 'string' ? body : JSON.stringify(body)),
      signal,
      cache: 'no-store',
    });
  } catch (e) {
    if (isAbort(e)) return { aborted: true, status: 0 };
    throw new ApiError(0, 'Tidak dapat terhubung ke server. Periksa koneksi Anda.', null);
  }

  if (res.status === 401 && !skipOnUnauthorized) notifyUnauthorized();
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    let errBody = null;
    try {
      const text = await res.text();
      errBody = parseData(text);
      if (errBody && typeof errBody === 'object') detail = errBody.detail || errBody.pesan || errBody.message || detail;
      else if (text) detail = text.slice(0, 300);
    } catch { /* badan galat tidak terbaca */ }
    if (res.status === 401 && detail === `HTTP ${res.status}`) detail = 'Sesi habis. Silakan login kembali.';
    throw new ApiError(res.status, typeof detail === 'string' ? detail : `HTTP ${res.status}`, errBody);
  }

  if (onOpen) onOpen(res);
  const parser = createSseParser((m) => {
    if (onEvent) onEvent({ event: m.event, data: parseData(m.data), id: m.id });
  });

  try {
    if (!res.body || typeof res.body.getReader !== 'function') {
      // Peramban lama tanpa ReadableStream: baca sekaligus (tidak bertahap, tapi tetap benar).
      parser.push(await res.text());
      parser.end();
      return { aborted: false, status: res.status };
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder('utf-8');
    for (;;) {
      // eslint-disable-next-line no-await-in-loop
      const { value, done } = await reader.read();
      if (done) break;
      parser.push(decoder.decode(value, { stream: true }));
    }
    parser.push(decoder.decode());
    parser.end();
    return { aborted: false, status: res.status };
  } catch (e) {
    if (isAbort(e) || signal?.aborted) return { aborted: true, status: res.status };
    throw new ApiError(0, 'Sambungan ke server terputus saat jawaban sedang dikirim.', null);
  }
}

export default sseFetch;

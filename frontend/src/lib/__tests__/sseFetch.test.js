import { createSseParser, sseFetch } from '../sseFetch';

const kumpul = (chunks) => {
  const out = [];
  const p = createSseParser((m) => out.push(m));
  chunks.forEach((c) => p.push(c));
  p.end();
  return out;
};

describe('createSseParser', () => {
  test('bingkai utuh: event + data JSON', () => {
    const out = kumpul(['event: mulai\ndata: {"pesan_id":"p1"}\n\n']);
    expect(out).toEqual([{ event: 'mulai', data: '{"pesan_id":"p1"}', id: '' }]);
  });

  test('bingkai terpotong di tengah kata, baris, dan \\r\\n', () => {
    const body = 'event: teks\r\ndata: {"delta":"Halo"}\r\n\r\nevent: teks\r\ndata: {"delta":" dunia"}\r\n\r\n';
    // potong setiap 3 huruf → \r dan \n pasti terbelah di beberapa tempat
    const chunks = body.match(/[\s\S]{1,3}/g);
    const out = kumpul(chunks);
    expect(out.map((m) => JSON.parse(m.data).delta)).toEqual(['Halo', ' dunia']);
    expect(out.every((m) => m.event === 'teks')).toBe(true);
  });

  test('komentar diabaikan, data ganda digabung, tanpa event = message', () => {
    const out = kumpul([': detak\n', 'data: a\ndata: b\n\n']);
    expect(out).toEqual([{ event: 'message', data: 'a\nb', id: '' }]);
  });

  test('bingkai terakhir tanpa baris kosong tetap terkirim saat end()', () => {
    const out = kumpul(['event: selesai\ndata: {"pesan_id":"p1"}']);
    expect(out).toHaveLength(1);
    expect(out[0].event).toBe('selesai');
  });

  test('BOM di awal aliran dibuang', () => {
    const out = kumpul(['﻿event: status\ndata: {"teks":"x"}\n\n']);
    expect(out[0].event).toBe('status');
  });
});

describe('sseFetch', () => {
  const asli = global.fetch;
  afterEach(() => { global.fetch = asli; localStorage.clear(); });

  test('mengirim Authorization seperti apiFetch, membaca aliran, mem-parse JSON', async () => {
    localStorage.setItem('erp_token', 'tok-uji');
    let req = null;
    global.fetch = jest.fn(async (url, init) => {
      req = { url, init };
      return {
        ok: true, status: 200, body: null, headers: { get: () => 'text/event-stream' },
        text: async () => 'event: mulai\ndata: {"pesan_id":"p9"}\n\nevent: teks\ndata: {"delta":"**Halo**"}\n\n',
      };
    });
    const ev = [];
    const res = await sseFetch('/asisten-ai/sessions/s1/messages', { body: { teks: 'x', cv: 'DA' }, headers: { 'X-CV': 'DA' }, onEvent: (e) => ev.push(e) });
    expect(res).toEqual({ aborted: false, status: 200 });
    expect(req.url).toMatch(/\/api\/asisten-ai\/sessions\/s1\/messages$/);
    expect(req.init.method).toBe('POST');
    expect(req.init.headers.Authorization).toBe('Bearer tok-uji');
    expect(req.init.headers['X-CV']).toBe('DA');
    expect(JSON.parse(req.init.body)).toEqual({ teks: 'x', cv: 'DA' });
    expect(ev).toEqual([
      { event: 'mulai', data: { pesan_id: 'p9' }, id: '' },
      { event: 'teks', data: { delta: '**Halo**' }, id: '' },
    ]);
  });

  test('galat HTTP → ApiError dengan detail server', async () => {
    global.fetch = jest.fn(async () => ({ ok: false, status: 403, text: async () => '{"detail":"Tidak boleh"}' }));
    await expect(sseFetch('/asisten-ai/x', { body: {} })).rejects.toMatchObject({ status: 403, message: 'Tidak boleh' });
  });

  test('dibatalkan sebelum tersambung → { aborted: true }, tidak melempar', async () => {
    global.fetch = jest.fn(async () => { const e = new Error('aborted'); e.name = 'AbortError'; throw e; });
    await expect(sseFetch('/asisten-ai/x', { body: {} })).resolves.toEqual({ aborted: true, status: 0 });
  });
});

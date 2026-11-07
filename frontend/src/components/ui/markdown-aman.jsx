/**
 * MarkdownAman — SATU pengurai markdown aman untuk teks AI & pesan chat (8 Nov 2026, Asisten AI Tahap A).
 *
 * Aman = tidak ada `dangerouslySetInnerHTML` dan tidak ada HTML mentah: setiap potongan teks menjadi node teks
 * React (otomatis di-escape). Tautan hanya http(s)/mailto, dibuka di tab baru dengan rel="noopener noreferrer";
 * skema lain (javascript:, data:) ditampilkan sebagai teks biasa. Tanpa pustaka tambahan.
 *
 * Didukung:
 *   blok   — paragraf (baris baru tunggal = pindah baris), judul # … ######, daftar - * + (bertingkat lewat
 *            indentasi), daftar bernomor 1. / 1), kutipan >, garis ---, blok kode ``` dan tabel GFM sederhana
 *            (| a | b | + |---|:--:|, perataan kolom dihormati, tabel bisa digulir ke samping).
 *   inline — **tebal** / __tebal__, *miring* / _miring_ (bukan di tengah kata_seperti_ini), ~~coret~~, `kode`,
 *            [teks](https://…) dan alamat https://… polos.
 *
 * Dipakai: Asisten AI (`erp/asisten/PesanAsisten`), Asisten ERP (`erp/AIChatbotWidget`), Perkiraan Arus Kas
 * (`erp/finance/CashFlowAI`, dulu XSS lewat dangerouslySetInnerHTML), dan chat Pusat Komunikasi
 * (`erp/communication-hub/Markdown.jsx` meneruskan ke sini dengan `ringkas`).
 *
 *   <MarkdownAman text={md} />                 // jarak normal (jawaban AI)
 *   <MarkdownAman text={md} ringkas />         // rapat, untuk gelembung chat
 *   renderMarkdown(md, { ringkas: true })      // fragmen React (kompatibel dengan pemakai lama)
 */
import { Fragment } from 'react';
import { cn } from '@/lib/utils';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './table';

const SAFE_URL_RX = /^(https?:\/\/|mailto:)/i;

export function isSafeUrl(url) {
  return SAFE_URL_RX.test(String(url || '').trim());
}

// ─── inline ─────────────────────────────────────────────────────────────────
// Urutan penting: kode dulu (isinya tidak diurai), lalu tautan, lalu penekanan.
const INLINE_RULES = [
  { kind: 'code', rx: /`([^`\n]+)`/ },
  { kind: 'link', rx: /\[([^\]\n]+)\]\(\s*([^)\s]+)(?:\s+"[^"]*")?\s*\)/ },
  { kind: 'auto', rx: /\bhttps?:\/\/[^\s<>()]+[^\s<>().,;:!?'"]/ },
  { kind: 'strong', rx: /\*\*(?=\S)([\s\S]*?\S)\*\*|__(?=\S)([\s\S]*?\S)__(?!\w)/ },
  { kind: 'del', rx: /~~(?=\S)([\s\S]*?\S)~~/ },
  // _miring_ hanya bila diapit bukan-huruf (kode_seperti_ini tetap utuh). Tanpa lookbehind: Safari iOS < 16.4
  // gagal mengurai regex lookbehind dan seluruh berkas tidak termuat.
  { kind: 'em', rx: /\*(?=[^\s*])([^*\n]*?[^\s*])\*|(^|[^\w])_(?=[^\s_])([^_\n]*?[^\s_])_(?!\w)/ },
];

function earliest(str) {
  let best = null;
  for (const r of INLINE_RULES) {
    const m = r.rx.exec(str);
    if (!m) continue;
    // awalan pembatas pada _miring_ (grup 2) bukan bagian dari penekanan
    const start = m.index + (r.kind === 'em' && m[2] ? m[2].length : 0);
    if (best === null || start < best.start) best = { kind: r.kind, m, start };
  }
  return best;
}

function Link({ href, children }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer"
      className="text-primary underline underline-offset-2 break-words hover:opacity-80">
      {children}
    </a>
  );
}

export function renderInline(str, keyBase = 'i', depth = 0) {
  const s = String(str ?? '');
  if (!s) return null;
  if (depth > 6) return s; // jaga-jaga terhadap teks bersarang ekstrem
  const out = [];
  let rest = s;
  let n = 0;
  while (rest) {
    const hit = earliest(rest);
    if (!hit) { out.push(rest); break; }
    const { kind, m, start } = hit;
    if (start > 0) out.push(rest.slice(0, start));
    const key = `${keyBase}-${n++}`;
    if (kind === 'code') {
      out.push(<code key={key} className="rounded bg-muted px-1 py-0.5 text-[0.85em] font-mono">{m[1]}</code>);
    } else if (kind === 'link') {
      const href = m[2].trim();
      const label = renderInline(m[1], key, depth + 1);
      out.push(isSafeUrl(href) ? <Link key={key} href={href}>{label}</Link> : <Fragment key={key}>{label}</Fragment>);
    } else if (kind === 'auto') {
      out.push(<Link key={key} href={m[0]}>{m[0]}</Link>);
    } else if (kind === 'strong') {
      out.push(<strong key={key} className="font-semibold text-foreground">{renderInline(m[1] ?? m[2], key, depth + 1)}</strong>);
    } else if (kind === 'del') {
      out.push(<del key={key}>{renderInline(m[1], key, depth + 1)}</del>);
    } else {
      out.push(<em key={key}>{renderInline(m[1] ?? m[3], key, depth + 1)}</em>);
    }
    rest = rest.slice(m.index + m[0].length);
  }
  return out;
}

// ─── blok ───────────────────────────────────────────────────────────────────
const HEADING_RX = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
const HR_RX = /^\s{0,3}([-*_])(\s*\1){2,}\s*$/;
const FENCE_RX = /^\s{0,3}(```|~~~)\s*([\w+-]*)\s*$/;
const LIST_RX = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/;
const QUOTE_RX = /^\s{0,3}>\s?(.*)$/;
const TABLE_SEP_RX = /^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$/;

const isTableRow = (ln) => /\|/.test(ln) && ln.trim() !== '';

function splitRow(ln) {
  let t = ln.trim();
  if (t.startsWith('|')) t = t.slice(1);
  if (t.endsWith('|') && !t.endsWith('\\|')) t = t.slice(0, -1);
  const cells = [];
  let cur = '';
  for (let i = 0; i < t.length; i++) {
    if (t[i] === '\\' && t[i + 1] === '|') { cur += '|'; i++; continue; }
    if (t[i] === '|') { cells.push(cur.trim()); cur = ''; continue; }
    cur += t[i];
  }
  cells.push(cur.trim());
  return cells;
}

function alignOf(sepCell) {
  const c = sepCell.trim();
  const left = c.startsWith(':');
  const right = c.endsWith(':');
  if (left && right) return 'center';
  if (right) return 'right';
  return 'left';
}

const NUMERIC_RX = /^[-−+]?\s?(Rp\s?)?[\d.,]+\s?(%|jt|rb|M|T|pcs)?$/i;

function MdTable({ head, aligns, rows, k }) {
  return (
    <div className="my-2" key={k} data-testid="md-tabel">
      <Table className="text-sm">
        <TableHeader>
          <TableRow>
            {head.map((h, i) => (
              <TableHead key={i} style={{ textAlign: aligns[i] || 'left' }}>{renderInline(h, `${k}-h${i}`)}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r, ri) => (
            <TableRow key={ri}>
              {head.map((_, ci) => {
                const cell = r[ci] ?? '';
                const al = aligns[ci] && aligns[ci] !== 'left' ? aligns[ci] : (NUMERIC_RX.test(cell) ? 'right' : 'left');
                return (
                  <TableCell key={ci} className={cn(al === 'right' && 'tabular-nums')} style={{ textAlign: al }}>
                    {renderInline(cell, `${k}-${ri}-${ci}`)}
                  </TableCell>
                );
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

/** Daftar bertingkat dari baris-baris daftar berurutan (indentasi ≥ 2 spasi = satu tingkat lebih dalam). */
function buildList(items, k, ringkas) {
  // items: [{indent, ordered, start, text}]
  let i = 0;
  const level = (minIndent) => {
    const first = items[i];
    const ordered = first.ordered;
    const start = first.start;
    const lis = [];
    while (i < items.length && items[i].indent >= minIndent) {
      const it = items[i];
      if (it.indent > minIndent + 1 && lis.length) {
        // anak dari butir sebelumnya
        const child = level(it.indent);
        lis[lis.length - 1].children.push(child);
        continue;
      }
      lis.push({ text: it.text, children: [], key: `${k}-li${i}` });
      i++;
    }
    const Tag = ordered ? 'ol' : 'ul';
    return (
      <Tag key={`${k}-l${i}`} start={ordered && start !== 1 ? start : undefined}
        className={cn(ordered ? 'list-decimal' : 'list-disc', 'pl-5', ringkas ? 'my-0.5 space-y-0' : 'my-1.5 space-y-1')}>
        {lis.map((li) => (
          <li key={li.key} className="pl-0.5">
            {renderInline(li.text, li.key)}
            {li.children}
          </li>
        ))}
      </Tag>
    );
  };
  const out = [];
  while (i < items.length) out.push(level(items[i].indent));
  return out;
}

const HEADING_CLASS = {
  1: 'text-base font-semibold',
  2: 'text-base font-semibold',
  3: 'text-sm font-semibold',
  4: 'text-sm font-semibold',
  5: 'text-sm font-medium',
  6: 'text-sm font-medium',
};

export function renderMarkdown(text, opts = {}) {
  const { ringkas = false } = opts;
  if (text === null || text === undefined || text === '') return null;
  const lines = String(text).replace(/\r\n?/g, '\n').split('\n');
  const blocks = [];
  let para = [];
  let k = 0;
  const key = () => `b${k++}`;
  const gap = ringkas ? '' : 'my-1.5';

  const flushPara = () => {
    if (!para.length) return;
    const kk = key();
    const content = para.flatMap((ln, idx) => (idx === 0
      ? [<Fragment key={`${kk}-${idx}`}>{renderInline(ln, `${kk}-${idx}`)}</Fragment>]
      : [<br key={`${kk}-br${idx}`} />, <Fragment key={`${kk}-${idx}`}>{renderInline(ln, `${kk}-${idx}`)}</Fragment>]));
    blocks.push(ringkas
      ? <span key={kk} className="block">{content}</span>
      : <p key={kk} className={cn(gap, 'leading-relaxed')}>{content}</p>);
    para = [];
  };

  let i = 0;
  while (i < lines.length) {
    const ln = lines[i];

    // blok kode
    const fence = FENCE_RX.exec(ln);
    if (fence) {
      flushPara();
      const body = [];
      i++;
      while (i < lines.length && !new RegExp(`^\\s{0,3}${fence[1]}\\s*$`).test(lines[i])) { body.push(lines[i]); i++; }
      i++; // lewati penutup
      blocks.push(
        <pre key={key()} className="my-2 overflow-x-auto rounded-[var(--radius-sm)] bg-muted px-3 py-2 text-xs leading-relaxed">
          <code className="font-mono">{body.join('\n')}</code>
        </pre>,
      );
      continue;
    }

    if (ln.trim() === '') {
      flushPara();
      if (ringkas && blocks.length) blocks.push(<br key={key()} />);
      i++;
      continue;
    }

    const h = HEADING_RX.exec(ln);
    if (h) {
      flushPara();
      const lvl = h[1].length;
      const Tag = `h${Math.min(6, lvl + 2)}`; // # → h3: judul jawaban tidak menyaingi judul halaman
      blocks.push(<Tag key={key()} className={cn(HEADING_CLASS[lvl], 'text-foreground', ringkas ? '' : 'mt-3 mb-1 first:mt-0')}>{renderInline(h[2], `h${k}`)}</Tag>);
      i++;
      continue;
    }

    if (HR_RX.test(ln)) {
      flushPara();
      blocks.push(<hr key={key()} className="my-3 border-[var(--glass-border)]" />);
      i++;
      continue;
    }

    // tabel GFM: baris kepala + baris pemisah
    if (isTableRow(ln) && i + 1 < lines.length && TABLE_SEP_RX.test(lines[i + 1]) && lines[i + 1].includes('-')) {
      flushPara();
      const head = splitRow(ln);
      const aligns = splitRow(lines[i + 1]).map(alignOf);
      i += 2;
      const rows = [];
      while (i < lines.length && isTableRow(lines[i]) && !TABLE_SEP_RX.test(lines[i])) { rows.push(splitRow(lines[i])); i++; }
      blocks.push(<MdTable key={`t${k}`} k={key()} head={head} aligns={aligns} rows={rows} />);
      continue;
    }

    if (LIST_RX.test(ln)) {
      flushPara();
      const items = [];
      while (i < lines.length) {
        const m = LIST_RX.exec(lines[i]);
        if (m) {
          const marker = m[2];
          const ordered = /\d/.test(marker);
          items.push({ indent: m[1].replace(/\t/g, '    ').length, ordered, start: ordered ? parseInt(marker, 10) : 1, text: m[3] });
          i++;
        } else if (lines[i].trim() !== '' && /^\s{2,}\S/.test(lines[i]) && items.length) {
          items[items.length - 1].text += ` ${lines[i].trim()}`; // sambungan butir
          i++;
        } else break;
      }
      blocks.push(...buildList(items, key(), ringkas));
      continue;
    }

    const q = QUOTE_RX.exec(ln);
    if (q) {
      flushPara();
      const body = [];
      while (i < lines.length) {
        const qm = QUOTE_RX.exec(lines[i]);
        if (!qm) break;
        body.push(qm[1]);
        i++;
      }
      blocks.push(
        <blockquote key={key()} className="my-2 border-l-2 border-[hsl(var(--primary)/0.4)] pl-3 text-muted-foreground">
          {renderMarkdown(body.join('\n'), { ringkas: true })}
        </blockquote>,
      );
      continue;
    }

    para.push(ln);
    i++;
  }
  flushPara();
  return <>{blocks}</>;
}

export default function MarkdownAman({ text, ringkas = false, className, testId }) {
  if (text === null || text === undefined || text === '') return null;
  return (
    <div className={cn('min-w-0 break-words text-sm text-foreground/90 [&>*:first-child]:mt-0 [&>*:last-child]:mb-0', className)}
      data-testid={testId}>
      {renderMarkdown(text, { ringkas })}
    </div>
  );
}

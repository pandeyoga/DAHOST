/**
 * Markdown pesan chat Pusat Komunikasi — 2026-11-08: diteruskan ke pengurai bersama yang aman
 * (`@/components/ui/markdown-aman`, mode `ringkas`). Dulu pengurai kecil sendiri (tebal/miring/kode/coret/daftar);
 * kini satu pengurai untuk semua layar: judul, daftar bernomor, tautan (rel="noopener noreferrer"), tabel.
 * Pemakai lama (`renderMarkdown(text)`, `<Markdown text />`) tetap jalan tanpa perubahan.
 */
import { renderMarkdown as renderShared } from '@/components/ui/markdown-aman';

export default function Markdown({ text }) {
  return renderShared(text, { ringkas: true });
}

export function renderMarkdown(text) {
  return renderShared(text, { ringkas: true });
}

/**
 * TabelAsisten — tabel dari peristiwa/blok `tabel` (Kontrak B: `{judul, kolom: [str], baris: [[str|number]], catatan?}`).
 *
 * Format tabel standar (ui/table), angka rata kanan `tabular-nums` dengan pemisah ribuan Indonesia. Tabel lebar
 * digulir ke samping DI DALAM bingkainya (ui/table → ResponsiveTableWrapper), jadi halaman tidak ikut melebar di HP.
 * Unduh Excel + CSV lewat `TombolUnduh` (Standar UI/UX v2: semua tabel bisa diunduh) — seluruh baris, bukan 50 pertama.
 */
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { formatNumber } from '@/lib/format';
import { cn } from '@/lib/utils';

const BATAS_AWAL = 50;
const BATAS_MAKS = 500;

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const ANGKA_TEKS_RX = /^[-−+]?\s?(Rp\s?)?\d[\d.,]*\s?(%|jt|rb|M|T|pcs|kg|yard)?$/i;

function teksSel(v) {
  if (v === null || v === undefined || v === '') return '—';
  if (isNum(v)) return formatNumber(v, { maximumFractionDigits: 2 });
  return String(v);
}

function namaBerkas(judul) {
  return String(judul || 'tabel-asisten-ai').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60) || 'tabel-asisten-ai';
}

export default function TabelAsisten({ judul, kolom, baris, catatan, polos = false, testId = 'asisten-tabel' }) {
  const [semua, setSemua] = useState(false);
  const cols = Array.isArray(kolom) ? kolom.map((k) => String(k ?? '')) : [];
  const rows = Array.isArray(baris) ? baris.filter(Array.isArray).slice(0, BATAS_MAKS) : [];
  if (!cols.length) {
    return <p className="text-xs text-muted-foreground" data-testid={`${testId}-kosong`}>Tabel tidak bisa ditampilkan (tanpa kolom).</p>;
  }
  // kolom angka = semua sel terisi di kolom itu berupa angka
  const kolomAngka = cols.map((_, ci) => {
    const isi = rows.map((r) => r[ci]).filter((v) => v !== null && v !== undefined && v !== '' && v !== '—');
    return isi.length > 0 && isi.every((v) => isNum(v) || ANGKA_TEKS_RX.test(String(v).trim()));
  });
  const tampil = semua ? rows : rows.slice(0, BATAS_AWAL);

  const isi = (
    <Table className="text-sm" wrapperClassName="max-w-full">
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          {cols.map((c, ci) => (
            <TableHead key={ci}
              className={cn('h-9 whitespace-nowrap px-3', kolomAngka[ci] && 'text-right')}>
              {c}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {tampil.map((r, ri) => (
          <TableRow key={ri}>
            {cols.map((_, ci) => (
              <TableCell key={ci} className={cn('px-3 py-2.5', kolomAngka[ci] ? 'whitespace-nowrap text-right tabular-nums' : 'min-w-[8rem]')}>
                {teksSel(r[ci])}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );

  if (polos) return <div className="min-w-0" data-testid={testId}>{isi}</div>;

  return (
    <section className="min-w-0 space-y-2 rounded-[var(--radius-md)] border border-[var(--glass-border)] p-3" data-testid={testId}
      aria-label={judul || 'Tabel'}>
      <div className="flex items-start justify-between gap-2">
        <p className="min-w-0 text-sm font-semibold text-foreground">{judul || 'Tabel'}</p>
        <TombolUnduh namaBerkas={namaBerkas(judul)} namaLembar={judul || 'Tabel'} baris={rows} testId={`${testId}-csv`}
          kolom={cols.map((c, ci) => ({ label: c, nilai: (r) => r[ci] ?? '' }))} />
      </div>
      <div className="min-w-0 overflow-hidden" data-testid={`${testId}-gulir`}>{isi}</div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        {catatan ? <p className="text-xs text-muted-foreground">{catatan}</p> : <span />}
        {rows.length > BATAS_AWAL && (
          <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={() => setSemua((s) => !s)}>
            {semua ? 'Tampilkan lebih sedikit' : `Tampilkan semua (${rows.length} baris)`}
          </Button>
        )}
      </div>
    </section>
  );
}

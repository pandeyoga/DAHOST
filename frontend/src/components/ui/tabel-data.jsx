/**
 * TabelData — standar daftar data (Standar UI/UX v2, keputusan owner 8 Nov 2026 #5 & #11).
 *  • Layar lebar (≥ 768 px): tabel. Kolom pengenal di kiri, angka rata kanan, aksi di kanan.
 *  • HP: kartu ringkas per baris (judul, keterangan, pasangan label–nilai, aksi) — tanpa geser samping.
 *  • Klik baris → `onKlikBaris(baris)` (mis. membuka DetailPopup). Tombol aksi tidak ikut memicu klik baris.
 *
 * kolom: [{ kunci, label, isi?: (baris) => node, rata?: 'kanan'|'tengah', lebar?: 'w-32',
 *           hp?: 'judul' | 'keterangan' | 'nilai' | 'aksi' | false }]
 *   hp='judul'      → baris tebal di kartu HP      hp='keterangan' → baris kecil di bawah judul
 *   hp='nilai'      → pasangan "label: nilai"       hp='aksi'       → tombol di kaki kartu
 *   hp=false        → disembunyikan di HP           (bawaan: 'nilai')
 *
 * Kosong (keputusan owner 8 Nov 2026 malam): tabel TETAP tampil — kepala kolom tetap ada, dan `kosong`
 * (EmptyState; bawaan "Belum ada data") tampil sebagai satu baris di badan tabel. Di HP: dalam kotak berbingkai.
 *
 * Rincian di bawah baris (opsional, 14 Nov 2026): `rincian={(baris) => node | null}` — bila mengembalikan isi,
 * isi itu tampil TEPAT di bawah barisnya (`RowDetail`, PANDUAN_UI G13); di HP di dalam kartunya. Layar yang
 * memakainya menyimpan baris mana yang terbuka (biasanya dibuka/tutup lewat `onKlikBaris`).
 */
import { Fragment } from 'react';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { EmptyState } from '@/components/erp/moduleAtoms';
import { RowDetail } from '@/components/ui/row-detail';
import { cn } from '@/lib/utils';

const RATA = { kanan: 'text-right', tengah: 'text-center' };
const hentikan = (e) => e.stopPropagation();

export default function TabelData({ kolom, baris, kunci = (b) => b.id, onKlikBaris, kosong, rincian, testId = 'tabel-data' }) {
  const daftar = Array.isArray(baris) ? baris : [];
  const isi = (k, b) => (k.isi ? k.isi(b) : b[k.kunci]);
  const peran = (k) => (k.hp === undefined ? 'nilai' : k.hp);
  const isiKosong = kosong || <EmptyState title="Belum ada data" />;
  return (
    <div data-testid={testId}>
      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow>
              {kolom.map((k) => (
                <TableHead key={k.kunci} className={cn(RATA[k.rata], k.lebar)}>{k.label}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {daftar.length === 0 && (
              <TableRow data-testid={`${testId}-kosong`} className="hover:bg-transparent">
                <TableCell colSpan={kolom.length} className="p-0 [&>div]:py-8">{isiKosong}</TableCell>
              </TableRow>
            )}
            {daftar.map((b) => {
              const tambahan = rincian ? rincian(b) : null;
              return (
                <Fragment key={kunci(b)}>
                  <TableRow data-testid={`${testId}-baris`}
                    onClick={onKlikBaris ? () => onKlikBaris(b) : undefined}
                    aria-expanded={rincian ? !!tambahan : undefined}
                    className={cn(onKlikBaris && 'cursor-pointer', tambahan && 'border-b-0')}>
                    {kolom.map((k) => (
                      <TableCell key={k.kunci} className={cn('align-middle', RATA[k.rata], k.lebar)}
                        onClick={peran(k) === 'aksi' ? hentikan : undefined}>
                        {isi(k, b)}
                      </TableCell>
                    ))}
                  </TableRow>
                  {tambahan && (
                    <RowDetail colSpan={kolom.length} testId={`${testId}-rincian`}>
                      {/* w-0 min-w-full: isi rincian (mis. tabel di dalamnya) tidak ikut melebarkan tabel induk */}
                      <div className="w-0 min-w-full">{tambahan}</div>
                    </RowDetail>
                  )}
                </Fragment>
              );
            })}
          </TableBody>
        </Table>
      </div>
      <div className="space-y-2 md:hidden">
        {daftar.length === 0 && (
          <div data-testid={`${testId}-kosong-hp`}
            className="rounded-lg border border-[var(--glass-border)] bg-[var(--card-surface)] [&>div]:py-8">
            {isiKosong}
          </div>
        )}
        {daftar.map((b) => {
          const judul = kolom.filter((k) => peran(k) === 'judul');
          const ket = kolom.filter((k) => peran(k) === 'keterangan');
          const nilai = kolom.filter((k) => peran(k) === 'nilai');
          const aksi = kolom.filter((k) => peran(k) === 'aksi');
          const tambahan = rincian ? rincian(b) : null;
          return (
            <div key={kunci(b)} data-testid={`${testId}-kartu`}
              onClick={onKlikBaris ? () => onKlikBaris(b) : undefined}
              className={cn('rounded-lg border border-[var(--glass-border)] bg-[var(--card-surface)] p-3',
                onKlikBaris && 'cursor-pointer')}>
              {judul.map((k) => <div key={k.kunci} className="text-sm font-medium text-foreground">{isi(k, b)}</div>)}
              {ket.map((k) => <div key={k.kunci} className="mt-0.5 text-xs text-muted-foreground">{isi(k, b)}</div>)}
              {nilai.length > 0 && (
                <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1">
                  {nilai.map((k) => (
                    <div key={k.kunci} className="min-w-0">
                      <dt className="text-xs text-muted-foreground">{k.label}</dt>
                      <dd className="text-sm text-foreground">{isi(k, b)}</dd>
                    </div>
                  ))}
                </dl>
              )}
              {aksi.length > 0 && (
                <div className="mt-2 flex flex-wrap justify-end gap-2" onClick={hentikan}>
                  {aksi.map((k) => <div key={k.kunci}>{isi(k, b)}</div>)}
                </div>
              )}
              {tambahan && (
                <div className="mt-3 border-t border-[var(--glass-border)] pt-3" onClick={hentikan}
                  data-testid={`${testId}-rincian-hp`}>
                  {tambahan}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

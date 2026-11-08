/**
 * UtasPesan — utas percakapan Asisten AI: gelembung pengguna di kanan, jawaban asisten di kiri.
 * Menggulir sendiri ke bawah saat jawaban mengalir, KECUALI pengguna sedang menggulir ke atas membaca.
 * Tahap B: kartu tindakan di jawaban mana pun bisa diputuskan (`onPutuskan`); selama ada jawaban yang mengalir
 * (`mengalir`) tombol kartu ditahan supaya tidak ada dua aliran sekaligus.
 * Tahap D: permintaan yang ditulis sistem (`otomatis`, mis. briefing pagi) tampil sebagai gelembung redup
 * "Permintaan otomatis", bukan seolah-olah diketik pengguna.
 * Tahap E: berkas yang dilampirkan pada pertanyaan tampil sebagai chip di atas gelembungnya.
 */
import { memo, useEffect, useLayoutEffect, useRef } from 'react';
import { Bot } from 'lucide-react';
import { Skeleton } from '@/components/ui/skeleton';
import { ChipLampiran } from './BerkasAsisten';
import PesanAsisten from './PesanAsisten';

const GelembungPengguna = memo(({ teks, otomatis, lampiran }) => (
  <div className="flex flex-col items-end gap-1.5" data-testid="asisten-pesan-pengguna" data-otomatis={otomatis ? '1' : undefined}>
    {lampiran?.length > 0 && (
      <div className="flex max-w-[85%] flex-wrap justify-end gap-1.5" data-testid="asisten-pesan-lampiran">
        {lampiran.map((l, i) => (
          <ChipLampiran key={l.id || i} nama={l.nama} jenis={l.jenis} ukuranKb={l.ukuran_kb} testId="asisten-pesan-lampiran-chip" />
        ))}
      </div>
    )}
    {otomatis ? (
      <div className="max-w-[85%] rounded-2xl rounded-br-md border border-dashed border-[var(--glass-border)] px-4 py-2 text-xs text-muted-foreground"
        title={teks} data-testid="asisten-pesan-otomatis">
        <p className="flex items-center gap-1.5 font-medium text-foreground/70">
          <Bot className="h-3.5 w-3.5 shrink-0" aria-hidden="true" /> Permintaan otomatis
        </p>
        <p className="mt-0.5 line-clamp-2 whitespace-pre-wrap break-words">{teks}</p>
      </div>
    ) : (
      <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-[hsl(var(--primary)/0.12)] px-4 py-2.5 text-sm text-foreground">
        {teks}
      </div>
    )}
  </div>
));
GelembungPengguna.displayName = 'GelembungPengguna';

export default function UtasPesan({
  pesan, memuat, kosong, onCobaLagi, onPutuskan, onNavigate, mengalir = false, tindakanAktif = true,
}) {
  const ref = useRef(null);
  const nempel = useRef(true);

  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const onScroll = () => { nempel.current = el.scrollHeight - el.scrollTop - el.clientHeight < 96; };
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, []);

  // pesan baru dari pengguna → selalu ke bawah; isi yang mengalir → ke bawah bila memang sedang di bawah
  const jumlahPengguna = pesan.filter((p) => p.peran === 'user').length;
  useLayoutEffect(() => { nempel.current = true; }, [jumlahPengguna]);
  useLayoutEffect(() => {
    const el = ref.current;
    if (el && nempel.current) el.scrollTop = el.scrollHeight;
  });

  return (
    <div ref={ref} className="min-h-0 flex-1 overflow-y-auto overscroll-contain" role="log" aria-live="polite"
      aria-label="Percakapan" data-testid="asisten-utas">
      {memuat ? (
        <div className="space-y-4 p-4" data-testid="asisten-utas-memuat">
          <Skeleton className="ml-auto h-10 w-2/3 rounded-2xl" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="ml-auto h-10 w-1/2 rounded-2xl" />
        </div>
      ) : pesan.length === 0 ? (
        kosong
      ) : (
        <div className="space-y-5 px-3 py-4 sm:px-5">
          {pesan.map((p) => (p.peran === 'user'
            ? <GelembungPengguna key={p.kunci} teks={p.teks} otomatis={p.otomatis} lampiran={p.lampiran} />
            : <PesanAsisten key={p.kunci} pesan={p} onCobaLagi={p.keadaan === 'galat' ? onCobaLagi : undefined}
              onPutuskan={onPutuskan} onNavigate={onNavigate} sibukUtas={mengalir} tindakanAktif={tindakanAktif} />))}
        </div>
      )}
    </div>
  );
}

/**
 * UtasPesan — utas percakapan Asisten AI: gelembung pengguna di kanan, jawaban asisten di kiri.
 * Menggulir sendiri ke bawah saat jawaban mengalir, KECUALI pengguna sedang menggulir ke atas membaca.
 */
import { memo, useEffect, useLayoutEffect, useRef } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import PesanAsisten from './PesanAsisten';

const GelembungPengguna = memo(({ teks }) => (
  <div className="flex justify-end" data-testid="asisten-pesan-pengguna">
    <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-[hsl(var(--primary)/0.12)] px-4 py-2.5 text-sm text-foreground">
      {teks}
    </div>
  </div>
));
GelembungPengguna.displayName = 'GelembungPengguna';

export default function UtasPesan({ pesan, memuat, kosong, onCobaLagi }) {
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
            ? <GelembungPengguna key={p.kunci} teks={p.teks} />
            : <PesanAsisten key={p.kunci} pesan={p} onCobaLagi={p.keadaan === 'galat' ? onCobaLagi : undefined} />))}
        </div>
      )}
    </div>
  );
}

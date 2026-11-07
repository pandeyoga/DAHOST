/**
 * DatePicker — pemilih SATU tanggal yang seragam (Standar UI/UX v2, keputusan owner 8 Nov 2026 #7),
 * pengganti <input type="date"> bawaan peramban (format mm/dd/yyyy, terpotong, beda tiap peramban).
 *
 * Nilai = string "YYYY-MM-DD" (tanggal kalender WIB, tanpa jam) atau "" bila kosong.
 * Tampil "10 Nov 2026". Kalender bulan berbahasa Indonesia, Senin di kiri.
 */
import { useMemo, useState } from 'react';
import { CalendarDays, ChevronLeft, ChevronRight, X } from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

const BULAN_PENDEK = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
const BULAN = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September',
  'Oktober', 'November', 'Desember'];
const HARI = ['Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab', 'Min'];

const pad = (n) => String(n).padStart(2, '0');
export const keYmd = (y, m, d) => `${y}-${pad(m + 1)}-${pad(d)}`;

/** "2026-11-10" → "10 Nov 2026" (tanpa zona waktu: tanggal kalender apa adanya). */
export function formatTanggalID(ymd) {
  if (!ymd) return '';
  const [y, m, d] = String(ymd).slice(0, 10).split('-').map(Number);
  if (!y || !m || !d) return '';
  return `${d} ${BULAN_PENDEK[m - 1]} ${y}`;
}

/** Hari ini menurut WIB sebagai "YYYY-MM-DD". */
export function hariIniWIB() {
  const s = new Date(Date.now() + 7 * 3600 * 1000).toISOString();
  return s.slice(0, 10);
}

export default function DatePicker({
  value, onChange, placeholder = 'Pilih tanggal', min, max, disabled = false, bolehKosong = true,
  testId = 'date-picker', id,
}) {
  const [buka, setBuka] = useState(false);
  const awal = value || hariIniWIB();
  const [tampil, setTampil] = useState(() => ({ y: Number(awal.slice(0, 4)), m: Number(awal.slice(5, 7)) - 1 }));

  const sel = useMemo(() => {
    const pertama = new Date(Date.UTC(tampil.y, tampil.m, 1));
    const geser = (pertama.getUTCDay() + 6) % 7; // Senin = 0
    const jumlah = new Date(Date.UTC(tampil.y, tampil.m + 1, 0)).getUTCDate();
    const out = Array.from({ length: geser }, () => null);
    for (let d = 1; d <= jumlah; d += 1) out.push(keYmd(tampil.y, tampil.m, d));
    return out;
  }, [tampil]);

  const pindah = (n) => setTampil(({ y, m }) => {
    const t = m + n;
    return { y: y + Math.floor(t / 12), m: ((t % 12) + 12) % 12 };
  });
  const hariIni = hariIniWIB();
  const dilarang = (ymd) => (min && ymd < min) || (max && ymd > max);

  return (
    <Popover open={buka} onOpenChange={(o) => {
      setBuka(o);
      if (o) { const v = value || hariIni; setTampil({ y: Number(v.slice(0, 4)), m: Number(v.slice(5, 7)) - 1 }); }
    }}>
      <div className="relative">
        <PopoverTrigger asChild>
          <Button type="button" variant="outline" id={id} disabled={disabled} data-testid={testId}
            className={cn('w-full justify-start font-normal', !value && 'text-muted-foreground', value && bolehKosong && 'pr-9')}>
            <CalendarDays className="text-muted-foreground" />
            {value ? formatTanggalID(value) : placeholder}
          </Button>
        </PopoverTrigger>
        {value && bolehKosong && !disabled && (
          <button type="button" onClick={() => onChange('')} aria-label="Kosongkan tanggal" title="Kosongkan tanggal"
            data-testid={`${testId}-kosongkan`}
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground hover:bg-foreground/5 hover:text-foreground">
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      <PopoverContent className="w-72 p-3" align="start" data-testid={`${testId}-kalender`}>
        <div className="mb-2 flex items-center justify-between">
          <Button type="button" variant="ghost" size="icon-sm" onClick={() => pindah(-1)} aria-label="Bulan sebelumnya">
            <ChevronLeft />
          </Button>
          <span className="text-sm font-medium">{BULAN[tampil.m]} {tampil.y}</span>
          <Button type="button" variant="ghost" size="icon-sm" onClick={() => pindah(1)} aria-label="Bulan berikutnya">
            <ChevronRight />
          </Button>
        </div>
        <div className="grid grid-cols-7 gap-0.5 text-center">
          {HARI.map((h) => <span key={h} className="py-1 text-xs text-muted-foreground">{h}</span>)}
          {sel.map((ymd, i) => (ymd ? (
            <button key={ymd} type="button" disabled={dilarang(ymd)}
              onClick={() => { onChange(ymd); setBuka(false); }}
              data-testid={`${testId}-hari-${ymd}`}
              className={cn('h-8 rounded-md text-sm transition-colors hover:bg-foreground/5 disabled:opacity-30',
                ymd === hariIni && 'font-semibold text-primary',
                ymd === value && 'bg-primary text-primary-foreground hover:bg-primary/90')}>
              {Number(ymd.slice(8, 10))}
            </button>
          ) : <span key={`k${i}`} />))}
        </div>
        <div className="mt-2 flex justify-between">
          <Button type="button" variant="ghost" size="sm" onClick={() => { onChange(hariIni); setBuka(false); }}>Hari ini</Button>
          {bolehKosong && value && (
            <Button type="button" variant="ghost" size="sm" onClick={() => { onChange(''); setBuka(false); }}>Kosongkan</Button>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

/**
 * DatePicker — pemilih SATU tanggal yang seragam (Standar UI/UX v2, keputusan owner 8 Nov 2026 #7),
 * pengganti <input type="date"> bawaan peramban (format mm/dd/yyyy, terpotong, beda tiap peramban).
 *
 * Nilai = string "YYYY-MM-DD" (tanggal kalender WIB, tanpa jam) atau "" bila kosong.
 * Tampil "10 Nov 2026". Kalender bulan berbahasa Indonesia, Senin di kiri.
 *
 * 2026-11-11 (owner: "tanggal lahir di karyawan saya tidak bisa pilih langsung tahunnya … harus klik jauh") —
 * prop opsional `pilihTahun` untuk tanggal yang bisa jauh ke belakang/depan (tanggal lahir, mulai kontrak,
 * masuk kerja, tanggal beli aset, masa berlaku dokumen):
 *   - kepala kalender berisi pilihan BULAN dan TAHUN (tahun bisa dicari, mis. ketik "1995"),
 *   - kotak "ketik tanggal" (17/08/1995, 17081995, 17 Agu 1995, 1995-08-17) — Enter atau "Pakai".
 *   Nilai prop:
 *     'lahir'  → tahun ini −80 … tahun ini −14
 *     'lampau' → tahun ini −50 … tahun ini +1   (masuk kerja, mulai kontrak, tanggal beli)
 *     true     → tahun ini −50 … tahun ini +20  (umum, mis. berakhir kontrak / masa berlaku)
 *   `tahunDari` / `tahunSampai` menimpa batas itu; `min` / `max` tetap berlaku. Tahun nilai yang sudah tersimpan
 *   selalu ikut dalam daftar walau di luar rentang, supaya data lama tetap tampil dan bisa dibetulkan.
 *   Tanpa `pilihTahun` tampilan sama seperti sebelumnya (panah bulan saja).
 */
import { useMemo, useRef, useState } from 'react';
import { CalendarDays, ChevronLeft, ChevronRight, X } from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
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

// Nama bulan yang diterima saat mengetik (3 huruf pertama; Indonesia dan Inggris).
const BULAN_KETIK = {
  jan: 1, feb: 2, peb: 2, mar: 3, apr: 4, mei: 5, may: 5, jun: 6, jul: 7, agu: 8, agt: 8, ags: 8, aug: 8,
  sep: 9, okt: 10, oct: 10, nov: 11, des: 12, dec: 12,
};

/**
 * Teks ketikan → "YYYY-MM-DD", atau null bila bukan tanggal yang ada.
 * Diterima: 17/08/1995 · 17-8-1995 · 17.08.1995 · 17081995 · 17 Agu 1995 · 17 Agustus 1995 · 1995-08-17.
 */
export function bacaTanggalKetik(teks) {
  const s = String(teks || '').trim().toLowerCase();
  if (!s) return null;
  let r;
  let y;
  let m;
  let d;
  if ((r = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/))) {
    [y, m, d] = [r[1], r[2], r[3]].map(Number);
  } else if ((r = s.match(/^(\d{1,2})[/.\-\s]+(\d{1,2})[/.\-\s]+(\d{4})$/)) || (r = s.match(/^(\d{2})(\d{2})(\d{4})$/))) {
    [d, m, y] = [r[1], r[2], r[3]].map(Number);
  } else if ((r = s.match(/^(\d{1,2})[/.\-\s]*([a-z]{3,})\.?[/.\-\s]*(\d{4})$/))) {
    d = Number(r[1]);
    m = BULAN_KETIK[r[2].slice(0, 3)];
    y = Number(r[3]);
  } else {
    return null;
  }
  if (!m || m < 1 || m > 12 || d < 1 || y < 1000) return null;
  if (d > new Date(Date.UTC(y, m, 0)).getUTCDate()) return null; // 31/02 dsb.
  return keYmd(y, m - 1, d);
}

/** Rentang tahun pilihan untuk mode `pilihTahun`; null bila mode mati. */
export function rentangTahun(pilihTahun, { min, max, tahunDari, tahunSampai, nilai, tahunIni }) {
  if (!pilihTahun) return null;
  const t = tahunIni;
  let [dari, sampai] = pilihTahun === 'lahir' ? [t - 80, t - 14]
    : pilihTahun === 'lampau' ? [t - 50, t + 1] : [t - 50, t + 20];
  if (tahunDari) dari = tahunDari;
  if (tahunSampai) sampai = tahunSampai;
  if (min) dari = Math.max(dari, Number(String(min).slice(0, 4)));
  if (max) sampai = Math.min(sampai, Number(String(max).slice(0, 4)));
  sampai = Math.max(sampai, dari);
  const yNilai = nilai ? Number(String(nilai).slice(0, 4)) : 0;
  if (yNilai) { dari = Math.min(dari, yNilai); sampai = Math.max(sampai, yNilai); }
  return { dari, sampai };
}

/** "1995-08-17" → "17/08/1995" (isi awal kotak ketik). */
const keKetik = (ymd) => (ymd ? `${ymd.slice(8, 10)}/${ymd.slice(5, 7)}/${ymd.slice(0, 4)}` : '');

/** Saat mengetik angka saja, garis miring disisipkan otomatis: "1708" → "17/08". */
function rapikanKetik(baru, lama) {
  if (baru.length <= lama.length || !/^[\d/]*$/.test(baru)) return baru; // menghapus / ada huruf → biarkan
  const a = baru.replace(/\D/g, '').slice(0, 8);
  return [a.slice(0, 2), a.slice(2, 4), a.slice(4)].filter(Boolean).join('/')
    + (a.length === 2 || a.length === 4 ? '/' : '');
}

const pointerHalus = () => {
  try { return !!window.matchMedia?.('(pointer: fine)')?.matches; } catch { return false; }
};

export default function DatePicker({
  value, onChange, placeholder = 'Pilih tanggal', min, max, disabled = false, bolehKosong = true,
  testId = 'date-picker', id, pilihTahun = false, tahunDari, tahunSampai,
}) {
  const [buka, setBuka] = useState(false);
  const hariIni = hariIniWIB();
  const rentang = useMemo(
    () => rentangTahun(pilihTahun, { min, max, tahunDari, tahunSampai, nilai: value, tahunIni: Number(hariIni.slice(0, 4)) }),
    [pilihTahun, min, max, tahunDari, tahunSampai, value, hariIni],
  );
  const tampilAwal = () => {
    const v = value || hariIni;
    let y = Number(v.slice(0, 4));
    if (rentang) y = Math.min(Math.max(y, rentang.dari), rentang.sampai);
    return { y, m: Number(v.slice(5, 7)) - 1 };
  };
  const [tampil, setTampil] = useState(tampilAwal);
  const [ketik, setKetik] = useState('');
  const [galat, setGalat] = useState('');
  const ketikRef = useRef(null);

  const sel = useMemo(() => {
    const pertama = new Date(Date.UTC(tampil.y, tampil.m, 1));
    const geser = (pertama.getUTCDay() + 6) % 7; // Senin = 0
    const jumlah = new Date(Date.UTC(tampil.y, tampil.m + 1, 0)).getUTCDate();
    const out = Array.from({ length: geser }, () => null);
    for (let d = 1; d <= jumlah; d += 1) out.push(keYmd(tampil.y, tampil.m, d));
    return out;
  }, [tampil]);

  const daftarTahun = useMemo(() => {
    if (!rentang) return [];
    const out = [];
    for (let y = rentang.sampai; y >= rentang.dari; y -= 1) out.push(y); // terbaru di atas
    return out;
  }, [rentang]);

  const pindah = (n) => setTampil(({ y, m }) => {
    const t = m + n;
    const baru = { y: y + Math.floor(t / 12), m: ((t % 12) + 12) % 12 };
    if (rentang && (baru.y < rentang.dari || baru.y > rentang.sampai)) return { y, m };
    return baru;
  });
  const luarRentang = (ymd) => !!rentang && (Number(ymd.slice(0, 4)) < rentang.dari || Number(ymd.slice(0, 4)) > rentang.sampai);
  const dilarang = (ymd) => (min && ymd < min) || (max && ymd > max) || luarRentang(ymd);
  const awalRentang = !!rentang && tampil.y <= rentang.dari && tampil.m === 0;
  const akhirRentang = !!rentang && tampil.y >= rentang.sampai && tampil.m === 11;

  const pilih = (ymd) => { onChange(ymd); setBuka(false); };

  const pakaiKetik = () => {
    const ymd = bacaTanggalKetik(ketik);
    if (!ymd) { setGalat('Tanggal tidak dikenali. Contoh: 17/08/1995'); return; }
    if (min && ymd < min) { setGalat(`Tanggal paling awal ${formatTanggalID(min)}.`); return; }
    if (max && ymd > max) { setGalat(`Tanggal paling akhir ${formatTanggalID(max)}.`); return; }
    if (luarRentang(ymd)) { setGalat(`Tahun harus antara ${rentang.dari} dan ${rentang.sampai}.`); return; }
    pilih(ymd);
  };

  const ubahKetik = (e) => {
    const t = rapikanKetik(e.target.value, ketik);
    setKetik(t);
    setGalat('');
    const ymd = bacaTanggalKetik(t);
    if (ymd && !luarRentang(ymd)) setTampil({ y: Number(ymd.slice(0, 4)), m: Number(ymd.slice(5, 7)) - 1 }); // kalender ikut
  };

  return (
    <Popover open={buka} onOpenChange={(o) => {
      setBuka(o);
      if (o) { setTampil(tampilAwal()); setKetik(keKetik(value)); setGalat(''); }
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
      <PopoverContent className={cn('p-3', rentang ? 'w-80' : 'w-72')} align="start" data-testid={`${testId}-kalender`}
        onOpenAutoFocus={rentang ? (e) => {
          // Layar sentuh: jangan memunculkan papan ketik (menutupi kalender). Mouse/keyboard: langsung bisa mengetik.
          e.preventDefault();
          if (pointerHalus() && ketikRef.current) { ketikRef.current.focus(); ketikRef.current.select(); }
          else e.target?.focus?.();
        } : undefined}>
        {rentang && (
          <>
            <div className="mb-2 flex gap-2">
              <Input ref={ketikRef} value={ketik} onChange={ubahKetik} inputMode="numeric" autoComplete="off"
                placeholder="Ketik, mis. 17/08/1995" aria-label="Ketik tanggal (hari/bulan/tahun)"
                aria-invalid={galat ? true : undefined} data-testid={`${testId}-ketik`}
                className={cn('h-8', galat && 'border-destructive focus-visible:ring-destructive')}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); pakaiKetik(); } }} />
              <Button type="button" variant="outline" size="sm" onClick={pakaiKetik} data-testid={`${testId}-ketik-pakai`}>
                Pakai
              </Button>
            </div>
            {galat && <p className="-mt-1 mb-2 text-xs text-destructive" role="alert" data-testid={`${testId}-ketik-galat`}>{galat}</p>}
          </>
        )}
        <div className={cn('mb-2 flex items-center', rentang ? 'gap-1' : 'justify-between')}>
          <Button type="button" variant="ghost" size="icon-sm" onClick={() => pindah(-1)} aria-label="Bulan sebelumnya"
            disabled={awalRentang}>
            <ChevronLeft />
          </Button>
          {rentang ? (
            <div className="grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)_auto] gap-1">
              <SmartNativeSelect value={String(tampil.m)} searchable={false} aria-label="Pilih bulan"
                data-testid={`${testId}-bulan`} className="h-8 px-2"
                onChange={(e) => setTampil((t) => ({ ...t, m: Number(e.target.value) }))}>
                {BULAN.map((b, i) => <option key={b} value={String(i)}>{b}</option>)}
              </SmartNativeSelect>
              <SmartNativeSelect value={String(tampil.y)} searchPlaceholder="Cari tahun…" aria-label="Pilih tahun"
                data-testid={`${testId}-tahun`} className="h-8 w-[5.5rem] px-2" wrapperClassName="w-[5.5rem]"
                onChange={(e) => setTampil((t) => ({ ...t, y: Number(e.target.value) }))}>
                {daftarTahun.map((y) => <option key={y} value={String(y)}>{y}</option>)}
              </SmartNativeSelect>
            </div>
          ) : (
            <span className="text-sm font-medium">{BULAN[tampil.m]} {tampil.y}</span>
          )}
          <Button type="button" variant="ghost" size="icon-sm" onClick={() => pindah(1)} aria-label="Bulan berikutnya"
            disabled={akhirRentang}>
            <ChevronRight />
          </Button>
        </div>
        <div className="grid grid-cols-7 gap-0.5 text-center">
          {HARI.map((h) => <span key={h} className="py-1 text-xs text-muted-foreground">{h}</span>)}
          {sel.map((ymd, i) => (ymd ? (
            <button key={ymd} type="button" disabled={dilarang(ymd)}
              onClick={() => pilih(ymd)}
              data-testid={`${testId}-hari-${ymd}`}
              className={cn('h-8 rounded-md text-sm transition-colors hover:bg-foreground/5 disabled:opacity-30',
                ymd === hariIni && 'font-semibold text-primary',
                ymd === value && 'bg-primary text-primary-foreground hover:bg-primary/90')}>
              {Number(ymd.slice(8, 10))}
            </button>
          ) : <span key={`k${i}`} />))}
        </div>
        <div className="mt-2 flex justify-between">
          {/* "Hari ini" hanya bila hari ini memang boleh dipilih (tidak untuk tanggal lahir, atau bila di luar batas). */}
          {!dilarang(hariIni)
            ? <Button type="button" variant="ghost" size="sm" onClick={() => pilih(hariIni)}>Hari ini</Button>
            : <span />}
          {bolehKosong && value && (
            <Button type="button" variant="ghost" size="sm" onClick={() => pilih('')}>Kosongkan</Button>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

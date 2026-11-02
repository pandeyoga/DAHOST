/**
 * recapDates — util tanggal bersama untuk Rekap Harian & Rekap Mingguan CMT.
 *
 * KENAPA DIPISAH
 * --------------
 * Tiga layar (tab Harian, tab Mingguan, dan panel induknya) harus setuju tentang
 * satu hal: **hari ini menurut WIB**, bukan menurut zona browser. Sebelum berkas
 * ini ada, helper-nya disalin di dalam komponen — dan salinan itulah yang suatu
 * hari akan berbeda (mis. satu diperbaiki ke WIB, satu tertinggal memakai zona
 * lokal) sehingga tab Harian dan tab Mingguan menampilkan "hari ini" yang berbeda.
 *
 * Kalau memakai zona browser: staf yang laptopnya ter-set UTC akan membuka rekap
 * tanggal KEMARIN sepanjang pagi (00:00-07:00 WIB) lalu menyimpulkan "semua vendor
 * belum mengisi" — persis jam produksi mulai bekerja. Backend memakai
 * `utils/waktu.today_wib()`; padanannya di frontend = `@/lib/waktu` (SSOT).
 * Nama lama di bawah dipertahankan sebagai ALIAS supaya pemanggil tidak berubah —
 * tidak ada lagi aritmetika tanggal salinan di berkas ini.
 */
import { todayWIB, addDaysISO, daysBetweenISO } from '@/lib/waktu';

/** Tanggal HARI INI menurut WIB sebagai 'YYYY-MM-DD' (= todayWIB). */
export const isoToday = () => todayWIB();

/** Geser tanggal ISO sebanyak `delta` hari (= addDaysISO). */
export const shiftDay = (iso, delta) => addDaysISO(iso, delta);

/** '2026-08-10' -> 'Senin, 10 Agustus 2026' (nama hari ikut: briefing menyebut hari). */
export const dayLabel = (iso) => {
  try {
    return new Date(`${iso}T12:00:00Z`).toLocaleDateString('id-ID', {
      weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
    });
  } catch { return iso; }
};

/** '2026-08-10' -> '10 Agu' (untuk kepala kolom yang sempit). */
export const shortDate = (iso) => {
  try {
    return new Date(`${iso}T12:00:00Z`).toLocaleDateString('id-ID', {
      day: 'numeric', month: 'short',
    });
  } catch { return iso; }
};

/** Selisih hari (b - a) untuk dua tanggal ISO (= daysBetweenISO). */
export const daysBetween = (a, b) => daysBetweenISO(a, b);

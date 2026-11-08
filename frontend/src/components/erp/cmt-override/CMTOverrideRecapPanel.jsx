/**
 * CMTOverrideRecapPanel — pembungkus **tab Harian | Mingguan** di dalam pintu
 * "Input Vendor CMT".
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * KENAPA INDUKNYA YANG MEMEGANG TANGGAL
 * ═══════════════════════════════════════════════════════════════════════════
 * Permintaan owner: dari tab Mingguan, **klik satu kotak hari → langsung lihat
 * Rekap Harian tanggal itu**. Kalau masing-masing tab menyimpan tanggalnya
 * sendiri (seperti sebelum ini), klik kotak hari tidak punya cara memindahkan
 * tab Harian — paling jauh hanya bisa membuka tab Harian pada "hari ini", yang
 * justru menyembunyikan hari yang sedang diselidiki.
 *
 * Karena itu `day` hidup DI SINI dan diturunkan ke kedua tab:
 *   * tab Harian  → `day` = tanggal yang ditampilkan;
 *   * tab Mingguan → `day` = hari TERAKHIR jendela 7 hari bergulir.
 *
 * Konsekuensi yang disengaja: setelah menyelidiki satu hari lalu kembali ke tab
 * Mingguan, jendelanya = 7 hari yang BERAKHIR di hari itu. Itu memang pertanyaan
 * lanjutannya ("pekan sampai hari itu bagaimana?"), dan tombol "7 hari terakhir"
 * selalu tersedia untuk kembali ke hari ini.
 *
 * Tab Harian tetap tab PERTAMA (keputusan owner 4a sesi sebelumnya): yang dibuka
 * staf tiap pagi adalah "siapa yang belum diisi HARI INI".
 *
 * Tahap 9 (7 Nov 2026): panel ini kini tab "Rekap pengisian" di menu Input atas nama CMT — cetakan
 * PageLayout, dan pilihan Harian · Mingguan memakai penyaring standar (FilterChips), bukan tombol buatan.
 */
import { useCallback, useState } from 'react';
import FilterChips from '@/components/ui/filter-chips';
import PageLayout from '../layout/PageLayout';
import CMTOverrideDailyRecap from './CMTOverrideDailyRecap';
import CMTOverrideWeeklyRecap from './CMTOverrideWeeklyRecap';
import { isoToday, shiftDay } from './recapDates';

const VIEWS = [
  { key: 'harian', label: 'Harian' },
  { key: 'mingguan', label: 'Mingguan' },
];

export default function CMTOverrideRecapPanel({ onOpenVendor, canFill = true }) {
  const [tab, setTab] = useState('harian');
  const [day, setDay] = useState(isoToday);

  // Klik kotak hari di tab Mingguan → pindah ke tab Harian PADA TANGGAL ITU.
  const openDay = useCallback((iso) => {
    if (!iso) return;
    setDay(iso);
    setTab('harian');
  }, []);

  const viewSwitch = (
    <FilterChips value={tab} onChange={setTab} options={VIEWS} hideWhenEmpty={false}
      testId="cmt-recap-tab" ariaLabel="Pilih tampilan rekap" />
  );

  return (
    <PageLayout testId="cmt-recap-panel-wrap" title="Rekap pengisian"
      subtitle="Vendor mana yang belum diisi — per hari, atau yang sering bolong dalam 7 hari."
      >
      {/* Standar UI/UX v2 (8 Nov 2026): pil Harian/Mingguan masuk ke baris alat tiap tampilan (satu baris, bukan dua);
          tanggal bersama tetap satu (`day`) dan tampil di pemilih tanggal masing-masing tampilan. */}
      {tab === 'harian' ? (
        <CMTOverrideDailyRecap
          viewSwitch={viewSwitch}
          day={day}
          onDayChange={setDay}
          onOpenVendor={onOpenVendor}
          canFill={canFill}
        />
      ) : (
        <CMTOverrideWeeklyRecap
          viewSwitch={viewSwitch}
          endDay={day}
          onEndDayChange={setDay}
          onOpenDay={openDay}
          onOpenVendor={onOpenVendor}
          canFill={canFill}
          shiftDay={shiftDay}
        />
      )}
    </PageLayout>
  );
}

/**
 * PeriodPicker — satu pemilih periode untuk layar Keuangan (2026-11-04, audit Keuangan tahap 2).
 *
 * Dulu ada 5 bentuk pemilih (rentang tanggal, tahun, bulan+tahun, "Hari Ini/7/28 Hari/Bulan Ini/Semua",
 * "bulan atau rentang") dan tanggal harus diketik untuk pertanyaan sesederhana "laba bulan lalu".
 * Pilihan cepat sama di semua layar; "Pilih tanggal" membuka dua kotak tanggal.
 *
 *   const [period, setPeriod] = useState(() => periodFromPreset('3m'));
 *   <PeriodPicker value={period} onChange={setPeriod} />
 *   // period = { preset, from: 'YYYY-MM-DD', to: 'YYYY-MM-DD' }
 */
import DatePicker from '@/components/ui/date-picker';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { formatDateID } from '@/lib/format';
import { addMonthsYM, lastMonthPeriodWIB, monthEndISO, monthStartWIB, thisMonthWIB, todayWIB, yearStartWIB } from '@/lib/waktu';

export const PERIOD_PRESETS = [
  { key: 'month', label: 'Bulan ini' },
  { key: 'last_month', label: 'Bulan lalu' },
  { key: '3m', label: '3 bulan' },
  { key: 'ytd', label: 'Tahun ini' },
  { key: '12m', label: '12 bulan terakhir' },
  { key: 'custom', label: 'Pilih tanggal' },
];
/** Tambahan opsional untuk daftar yang bawaannya semua waktu (mis. rekening koran pelanggan):
 *  <PeriodPicker presets={[ALL_TIME, ...PERIOD_PRESETS]} /> → { preset: 'all', from: '', to: '' }. */
export const ALL_TIME = { key: 'all', label: 'Semua waktu' };

export function periodFromPreset(key, prev = {}) {
  const today = todayWIB();
  const ym = thisMonthWIB();
  switch (key) {
    case 'month': return { preset: key, from: monthStartWIB(), to: today };
    case 'last_month': return { preset: key, ...lastMonthPeriodWIB() };
    case '3m': return { preset: key, from: `${addMonthsYM(ym, -2)}-01`, to: today };
    case 'ytd': return { preset: key, from: yearStartWIB(), to: today };
    case '12m': return { preset: key, from: `${addMonthsYM(ym, -11)}-01`, to: today };
    case 'all': return { preset: key, from: '', to: '' };
    default: return { preset: 'custom', from: prev.from || monthStartWIB(), to: prev.to || monthEndISO(ym) };
  }
}

const BULAN = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'];
/** Pilihan bulan berlabel untuk formulir satu-bulan (pengganti input type="month"), terbaru di atas.
 *  `ahead` = jumlah bulan SESUDAH bulan berjalan yang ikut ditampilkan (mis. mulai potong gaji kasbon). */
export function monthOptions(n = 24, ahead = 0) {
  const [y, m] = thisMonthWIB().split('-').map(Number);
  return Array.from({ length: n + ahead }, (_, i) => {
    const d = new Date(Date.UTC(y, m - 1 + ahead - i, 1));
    const yy = d.getUTCFullYear(); const mm = d.getUTCMonth() + 1;
    return { value: `${yy}-${String(mm).padStart(2, '0')}`, label: `${BULAN[mm - 1]} ${yy}` };
  });
}

export default function PeriodPicker({ value, onChange, presets = PERIOD_PRESETS, testId = 'period-picker' }) {
  const cur = value || periodFromPreset('month');
  return (
    <div className="flex items-center gap-2 flex-wrap" data-testid={testId}>
      {/* 2026-11-04 (audit galeri): pilihan aplikasi yang sama dengan penyaring lain — dulu <select> bawaan
          browser, bentuknya beda dengan "Semua toko" di sebelahnya. */}
      <SmartNativeSelect
        value={cur.preset || 'custom'}
        onChange={(e) => onChange(periodFromPreset(e.target.value, cur))}
        searchable={false}
        className="h-9 w-40"
        aria-label="Periode"
        data-testid={`${testId}-preset`}
      >
        {presets.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
      </SmartNativeSelect>
      {cur.preset === 'custom' ? (
        <>
          {/* v2: satu pemilih tanggal aplikasi (dulu input tanggal bawaan peramban) */}
          <div className="w-40"><DatePicker value={cur.from} max={cur.to || undefined} bolehKosong={false}
            onChange={(v) => onChange({ ...cur, from: v })} testId={`${testId}-from`} /></div>
          <span className="text-xs text-muted-foreground">s/d</span>
          <div className="w-40"><DatePicker value={cur.to} min={cur.from || undefined} bolehKosong={false}
            onChange={(v) => onChange({ ...cur, to: v })} testId={`${testId}-to`} /></div>
        </>
      ) : cur.preset === 'all' ? null : (
        <span className="text-xs text-muted-foreground" data-testid={`${testId}-range`}>{formatDateID(cur.from)} – {formatDateID(cur.to)}</span>
      )}
    </div>
  );
}

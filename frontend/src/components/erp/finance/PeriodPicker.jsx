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
import { GlassInput } from '@/components/ui/glass';
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

export function periodFromPreset(key, prev = {}) {
  const today = todayWIB();
  const ym = thisMonthWIB();
  switch (key) {
    case 'month': return { preset: key, from: monthStartWIB(), to: today };
    case 'last_month': return { preset: key, ...lastMonthPeriodWIB() };
    case '3m': return { preset: key, from: `${addMonthsYM(ym, -2)}-01`, to: today };
    case 'ytd': return { preset: key, from: yearStartWIB(), to: today };
    case '12m': return { preset: key, from: `${addMonthsYM(ym, -11)}-01`, to: today };
    default: return { preset: 'custom', from: prev.from || monthStartWIB(), to: prev.to || monthEndISO(ym) };
  }
}

export default function PeriodPicker({ value, onChange, presets = PERIOD_PRESETS, testId = 'period-picker' }) {
  const cur = value || periodFromPreset('month');
  return (
    <div className="flex items-center gap-2 flex-wrap" data-testid={testId}>
      <select
        value={cur.preset || 'custom'}
        onChange={(e) => onChange(periodFromPreset(e.target.value, cur))}
        className="h-8 rounded-[var(--radius-sm)] bg-[var(--card-surface)] border border-[var(--glass-border)] px-2 text-xs text-foreground"
        aria-label="Periode"
        data-testid={`${testId}-preset`}
      >
        {presets.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
      </select>
      {cur.preset === 'custom' ? (
        <>
          <GlassInput type="date" value={cur.from} onChange={(e) => onChange({ ...cur, from: e.target.value })}
                      className="h-8 w-36" aria-label="Dari tanggal" data-testid={`${testId}-from`} />
          <span className="text-xs text-muted-foreground">s/d</span>
          <GlassInput type="date" value={cur.to} onChange={(e) => onChange({ ...cur, to: e.target.value })}
                      className="h-8 w-36" aria-label="Sampai tanggal" data-testid={`${testId}-to`} />
        </>
      ) : (
        <span className="text-xs text-muted-foreground" data-testid={`${testId}-range`}>{formatDateID(cur.from)} – {formatDateID(cur.to)}</span>
      )}
    </div>
  );
}

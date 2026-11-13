/**
 * PeriodSelector — pemilih rentang tanggal Dashboard Marketing. Nilai: { date_from, date_to } 'YYYY-MM-DD' (WIB).
 *
 * Standar UI/UX v2 (8 Nov 2026): dulu 5 tombol pil + popup berisi dua input tanggal bawaan peramban. Kini satu
 * pilihan (bentuk sama dengan PeriodPicker standar) + dua DatePicker untuk "Pilih tanggal".
 *
 * 14 Nov 2026 (owner: grafik iklan/anggaran/target di Dashboard Marketing) — periode mengikuti cara kerja Marketing:
 *   • "Bulan ini" / "Bulan lalu" = BULAN MARKETING tanggal 26–25 (`lib/waktu.rentangBulanMarketing`; dulu tanggal 1
 *     kalender, sehingga kartu periode tidak pernah sama dengan angka siklus/target bulan itu);
 *   • "Minggu ini" / "Minggu lalu" = minggu SENIN–Minggu (sama dengan anggaran mingguan).
 * Nilai yang dikirim tetap { date_from, date_to }.
 */
import { useState } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import DatePicker, { formatTanggalID } from '@/components/ui/date-picker';
import {
  todayWIB, daysAgoWIB, addDaysISO, addMonthsYM, bulanMarketingWIB, rentangBulanMarketing, seninDari,
} from '@/lib/waktu';

const PRESETS = [
  { key: 'bulan', label: 'Bulan ini' },
  { key: 'bulan-lalu', label: 'Bulan lalu' },
  { key: 'minggu', label: 'Minggu ini' },
  { key: 'minggu-lalu', label: 'Minggu lalu' },
  { key: '0', label: 'Hari ini' },
  { key: '7', label: '7 hari terakhir' },
  { key: '30', label: '30 hari terakhir' },
  { key: '90', label: '90 hari terakhir' },
  { key: 'custom', label: 'Pilih tanggal' },
];

/** Rentang satu pilihan cepat. `now` hanya untuk uji. */
export const rentangPreset = (key, now = new Date()) => {
  const to = todayWIB(now);
  if (key === 'bulan') return { date_from: rentangBulanMarketing(bulanMarketingWIB(now)).dari, date_to: to };
  if (key === 'bulan-lalu') {
    const r = rentangBulanMarketing(addMonthsYM(bulanMarketingWIB(now), -1));
    return { date_from: r.dari, date_to: r.sampai };
  }
  if (key === 'minggu') return { date_from: seninDari(to), date_to: to };
  if (key === 'minggu-lalu') {
    const senin = addDaysISO(seninDari(to), -7);
    return { date_from: senin, date_to: addDaysISO(senin, 6) };
  }
  const days = Number(key);
  // M-26 — "30 hari terakhir" = 30 hari termasuk hari ini (dulu 31 hari)
  return { date_from: days === 0 ? to : daysAgoWIB(days - 1, now), date_to: to };
};

const presetDari = (value) => {
  if (!value?.date_from || !value?.date_to) return 'custom';
  const hit = PRESETS.find((p) => p.key !== 'custom' && (() => {
    const r = rentangPreset(p.key);
    return r.date_from === value.date_from && r.date_to === value.date_to;
  })());
  return hit ? hit.key : 'custom';
};

export function PeriodSelector({ value, onChange }) {
  const [custom, setCustom] = useState(() => presetDari(value) === 'custom');
  const preset = custom ? 'custom' : presetDari(value);

  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="period-selector">
      <SmartNativeSelect className="w-44" value={preset} searchable={false} aria-label="Periode" data-testid="period-preset"
        onChange={(e) => {
          const k = e.target.value;
          if (k === 'custom') { setCustom(true); return; }
          setCustom(false);
          onChange(rentangPreset(k));
        }}>
        {PRESETS.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
      </SmartNativeSelect>
      {preset === 'custom' ? (
        <>
          <div className="w-40">
            <DatePicker value={value.date_from || ''} max={value.date_to || undefined} bolehKosong={false}
              onChange={(v) => onChange({ ...value, date_from: v })} testId="custom-date-from" />
          </div>
          <span className="text-sm text-muted-foreground">s/d</span>
          <div className="w-40">
            <DatePicker value={value.date_to || ''} min={value.date_from || undefined} bolehKosong={false}
              onChange={(v) => onChange({ ...value, date_to: v })} testId="custom-date-to" />
          </div>
        </>
      ) : (
        <span className="text-sm text-muted-foreground" data-testid="period-range">
          {formatTanggalID(value.date_from)} – {formatTanggalID(value.date_to)}
        </span>
      )}
    </div>
  );
}

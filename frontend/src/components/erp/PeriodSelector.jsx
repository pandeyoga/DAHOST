/**
 * PeriodSelector — pemilih rentang tanggal Dashboard Marketing. Nilai: { date_from, date_to } 'YYYY-MM-DD' (WIB).
 *
 * Standar UI/UX v2 (8 Nov 2026): dulu 5 tombol pil + popup berisi dua input tanggal bawaan peramban. Kini satu
 * pilihan (bentuk sama dengan PeriodPicker standar) + dua DatePicker untuk "Pilih tanggal". Pilihan cepat tetap
 * sama (Bulan ini, Hari ini, 7/30/90 hari) dan nilai yang dikirim tidak berubah.
 */
import { useState } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import DatePicker, { formatTanggalID } from '@/components/ui/date-picker';
import { todayWIB, daysAgoWIB, monthStartWIB } from '@/lib/waktu';

const PRESETS = [
  { key: 'month', label: 'Bulan ini' },
  { key: '0', label: 'Hari ini' },
  { key: '7', label: '7 hari terakhir' },
  { key: '30', label: '30 hari terakhir' },
  { key: '90', label: '90 hari terakhir' },
  { key: 'custom', label: 'Pilih tanggal' },
];

const rentangPreset = (key) => {
  const to = todayWIB();
  if (key === 'month') return { date_from: monthStartWIB(), date_to: to };
  const days = Number(key);
  // M-26 — "30 hari terakhir" = 30 hari termasuk hari ini (dulu 31 hari)
  return { date_from: days === 0 ? to : daysAgoWIB(days - 1), date_to: to };
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

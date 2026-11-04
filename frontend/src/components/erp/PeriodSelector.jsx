import { useState } from 'react';
import { Calendar } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { GlassInput } from '@/components/ui/glass';
import { todayWIB, daysAgoWIB, monthStartWIB, daysBetweenISO } from '@/lib/waktu';

// Semua tanggal preset = kalender WIB (lib/waktu), bukan tanggal UTC/perangkat.
// FASE D (2026-08-16) — "Bulan Ini" ada karena SEMUA target & anggaran marketing
// bersifat BULANAN. Tanpa preset ini, bawaan 30 hari terakhir selalu menyerempet dua
// bulan, jadi omzet di layar tidak pernah bisa dibandingkan dengan targetnya.

export function PeriodSelector({ value, onChange }) {
  const [isCustom, setIsCustom] = useState(false);
  const [customFrom, setCustomFrom] = useState(value.date_from || daysAgoWIB(30));
  const [customTo, setCustomTo] = useState(value.date_to || todayWIB());

  const presets = [
    { label: 'Bulan Ini', month: true },
    { label: 'Hari Ini', days: 0 },
    { label: '7 Hari', days: 7 },
    { label: '30 Hari', days: 30 },
    { label: '90 Hari', days: 90 },
  ];

  const handlePreset = (preset) => {
    const to = todayWIB();
    const from = preset.month ? monthStartWIB() : (preset.days === 0 ? to : daysAgoWIB(preset.days));
    onChange({ date_from: from, date_to: to });
    setIsCustom(false);
  };

  const handleCustomApply = () => {
    if (!customFrom || !customTo) return;
    if (new Date(customFrom) > new Date(customTo)) {
      toast.error('Tanggal mulai harus lebih kecil dari tanggal akhir');
      return;
    }
    onChange({ date_from: customFrom, date_to: customTo });
    setIsCustom(false);
  };

  const currentLabel = () => {
    if (!value.date_from || !value.date_to) return 'Pilih Periode';
    if (value.date_from === monthStartWIB() && value.date_to === todayWIB()) return 'Bulan Ini';
    const diffDays = daysBetweenISO(value.date_from, value.date_to);
    
    if (diffDays === 0) return 'Hari Ini';
    if (diffDays === 7) return '7 Hari Terakhir';
    if (diffDays === 30) return '30 Hari Terakhir';
    if (diffDays === 90) return '90 Hari Terakhir';
    return `${value.date_from} - ${value.date_to}`;
  };

  return (
    <Popover open={isCustom} onOpenChange={setIsCustom}>
      <div className="flex items-center gap-2" data-testid="period-selector">
        {presets.map(preset => (
          <Button
            key={preset.label}
            variant="outline"
            size="sm"
            onClick={() => handlePreset(preset)}
            data-testid={preset.month ? 'period-month' : `period-${preset.days}d`}
          >
            {preset.label}
          </Button>
        ))}
        <PopoverTrigger asChild>
          <Button variant="outline" size="sm" data-testid="period-custom">
            <Calendar className="w-4 h-4 mr-2" />
            {isCustom ? 'Custom' : currentLabel()}
          </Button>
        </PopoverTrigger>
      </div>

      <PopoverContent className="w-80 p-4">
        <div className="space-y-3">
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Tanggal Mulai</label>
            <GlassInput
              type="date"
              value={customFrom}
              onChange={e => setCustomFrom(e.target.value)}
              data-testid="custom-date-from"
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Tanggal Akhir</label>
            <GlassInput
              type="date"
              value={customTo}
              onChange={e => setCustomTo(e.target.value)}
              data-testid="custom-date-to"
            />
          </div>
          <Button onClick={handleCustomApply} className="w-full" size="sm" data-testid="apply-custom-period">
            Terapkan
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}

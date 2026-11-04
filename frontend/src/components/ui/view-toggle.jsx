/**
 * ViewToggle — pilihan BENTUK tampilan (Tabel / Kartu). PANDUAN_UI G6.
 *
 * Bukan penyaring: tampil sebagai dua tombol ikon kecil di sisi kanan toolbar (slot `tools` PageLayout),
 * supaya tidak tertukar dengan pil penyaring (`FilterChips`). Dulu "Tabel | Kartu" memakai pil penyaring
 * sehingga terlihat seperti filter (audit 4 Nov 2026).
 *
 *   <ViewToggle value={view} onChange={setView} />
 */
import { LayoutGrid, Table2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export const DEFAULT_VIEWS = [
  { key: 'table', label: 'Tampilan tabel', icon: Table2 },
  { key: 'grid', label: 'Tampilan kartu', icon: LayoutGrid },
];

export default function ViewToggle({ value, onChange, options = DEFAULT_VIEWS, testId = 'view-toggle' }) {
  return (
    <div role="group" aria-label="Bentuk tampilan" data-testid={testId} data-view-toggle=""
      className="inline-flex items-center gap-0.5 h-9 rounded-[var(--radius-sm)] border border-[var(--glass-border)] bg-[var(--card-surface)] p-0.5">
      {options.map((o) => {
        const Icon = o.icon;
        const on = value === o.key;
        return (
          <Button key={o.key} type="button" variant="ghost" size="icon-sm" aria-pressed={on} title={o.label} aria-label={o.label}
            onClick={() => onChange(o.key)} data-testid={`${testId}-${o.key}`}
            className={cn('h-7 w-7', on ? 'bg-foreground/10 text-foreground' : 'text-muted-foreground')}>
            <Icon className="w-4 h-4" />
          </Button>
        );
      })}
    </div>
  );
}

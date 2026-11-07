/**
 * ChipIngatan — tanda kecil di jawaban Asisten AI saat AI menyimpan atau melupakan ingatan (Tahap D, D1):
 *   [🧠 Diingat: target minimal tumbuh 8%]  [🧠 Dilupakan: …]   Ingatan AI ›
 * Sumbernya peristiwa SSE `ingatan` atau blok tersimpan {jenis: "ingatan"} (keduanya dinormalkan `blokIngatan`).
 * Tautan membuka halaman Ingatan AI (`asisten-ai-ingatan`) dan menyorot ingatan itu bila id-nya ada.
 * Teks dari server selalu teks biasa (React meng-escape).
 */
import { memo } from 'react';
import { ArrowUpRight, Brain } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { teksChipIngatan } from './adapterTahapCD';

function ChipIngatan({ item = [], onNavigate }) {
  if (!item.length) return null;
  const sorot = item.filter((b) => b.aksi !== 'dihapus' && b.id).slice(-1)[0];
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid="asisten-ingatan">
      {item.map((b, i) => {
        const t = teksChipIngatan(b);
        return (
          <span key={`${b.id || 'x'}-${i}`} title={t} data-testid="asisten-ingatan-chip" data-aksi={b.aksi}
            className={cn('inline-flex max-w-full items-center gap-1 rounded-full border px-2 py-0.5 text-xs sm:max-w-[22rem]',
              b.aksi === 'dihapus'
                ? 'border-[var(--glass-border)] text-muted-foreground'
                : 'border-[hsl(var(--primary)/0.3)] bg-[hsl(var(--primary)/0.06)] text-foreground/85')}>
            <Brain className="h-3 w-3 shrink-0 text-primary" aria-hidden="true" />
            <span className="truncate">{t}</span>
          </span>
        );
      })}
      {onNavigate && (
        <Button variant="link" size="sm" className="h-auto px-0 text-xs" data-testid="asisten-ingatan-tautan"
          onClick={() => onNavigate('asisten-ai-ingatan', sorot ? { ingatan: sorot.id } : {})}>
          Ingatan AI <ArrowUpRight className="h-3.5 w-3.5" />
        </Button>
      )}
    </div>
  );
}

export default memo(ChipIngatan);

import { TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { formatRupiah } from '@/lib/format';

/**
 * Component untuk display perbandingan HPP:
 * Estimasi | Aktual | Delta (+/-%) dengan color-coded
 */
export function HppComparisonInline({ estimated, actual, className = "" }) {
  const delta = actual - estimated;
  const deltaPct = estimated > 0 ? (delta / estimated) * 100 : 0;
  
  const isOverBudget = delta > 0;
  const isOnTarget = Math.abs(deltaPct) < 1;
  
  const deltaColor = isOnTarget 
    ? "text-[hsl(var(--primary))] border-[hsl(var(--primary)/0.2)] bg-[hsl(var(--primary)/0.1)]" 
    : isOverBudget 
      ? "text-[hsl(var(--destructive))] border-[hsl(var(--destructive)/0.2)] bg-[hsl(var(--destructive)/0.1)]"
      : "text-[hsl(var(--success))] border-[hsl(var(--success)/0.2)] bg-[hsl(var(--success)/0.1)]";
  
  const DeltaIcon = isOnTarget ? Minus : isOverBudget ? TrendingUp : TrendingDown;
  
  const fmt = formatRupiah;
  
  return (
    <div className={`flex flex-wrap items-center gap-2 text-sm ${className}`}>
      <span className="text-muted-foreground" data-testid="hpp-comparison-estimated">
        Estimasi: <span className="tabular-nums">{fmt(estimated)}</span>
      </span>
      <span className="text-foreground/70">|</span>
      <span className="text-foreground" data-testid="hpp-comparison-actual">
        Aktual: <span className="tabular-nums font-semibold">{fmt(actual)}</span>
      </span>
      <span className="text-foreground/70">|</span>
      <span 
        className={`inline-flex items-center rounded-md border px-2 py-0.5 tabular-nums text-xs ${deltaColor}`}
        data-testid="hpp-comparison-delta"
      >
        <DeltaIcon className="w-3 h-3 mr-1" />
        {deltaPct >= 0 ? '+' : ''}{deltaPct.toFixed(1)}%
      </span>
    </div>
  );
}
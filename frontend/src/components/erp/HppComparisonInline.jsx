import { TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { formatRupiah } from '@/lib/format';

const NO_DATA = 'belum ada data';
const hasValue = (v) => v !== null && v !== undefined && Number.isFinite(Number(v)) && Number(v) > 0;

/**
 * Component untuk display perbandingan HPP:
 * Estimasi | Aktual | Delta (+/-%) dengan color-coded
 *
 * Tahap 1 (6 Nov 2026): angka yang tidak ada sumbernya (estimasi kosong/0, aktual kosong) tampil
 * "belum ada data" dan selisihnya tidak dihitung — dulu layar mengarang estimasi (aktual × 0,95,
 * atau pendapatan) sehingga selisihnya selalu tampak bermakna.
 */
export function HppComparisonInline({ estimated, actual, className = "" }) {
  const fmt = formatRupiah;
  const showActual = actual !== null && actual !== undefined;
  const canCompare = hasValue(estimated) && showActual;
  const delta = canCompare ? Number(actual) - Number(estimated) : 0;
  const deltaPct = canCompare ? (delta / Number(estimated)) * 100 : 0;

  const isOverBudget = delta > 0;
  const isOnTarget = Math.abs(deltaPct) < 1;

  const deltaColor = isOnTarget
    ? "text-[hsl(var(--primary))] border-[hsl(var(--primary)/0.2)] bg-[hsl(var(--primary)/0.1)]"
    : isOverBudget
      ? "text-[hsl(var(--destructive))] border-[hsl(var(--destructive)/0.2)] bg-[hsl(var(--destructive)/0.1)]"
      : "text-[hsl(var(--success))] border-[hsl(var(--success)/0.2)] bg-[hsl(var(--success)/0.1)]";

  const DeltaIcon = isOnTarget ? Minus : isOverBudget ? TrendingUp : TrendingDown;

  return (
    <div className={`flex flex-wrap items-center gap-2 text-sm ${className}`}>
      <span className="text-muted-foreground" data-testid="hpp-comparison-estimated">
        Estimasi: <span className="tabular-nums">{hasValue(estimated) ? fmt(estimated) : NO_DATA}</span>
      </span>
      <span className="text-foreground/70">|</span>
      <span className="text-foreground" data-testid="hpp-comparison-actual">
        Aktual: <span className="tabular-nums font-semibold">{showActual ? fmt(actual) : NO_DATA}</span>
      </span>
      {canCompare && (
        <>
          <span className="text-foreground/70">|</span>
          <span
            className={`inline-flex items-center rounded-md border px-2 py-0.5 tabular-nums text-xs ${deltaColor}`}
            data-testid="hpp-comparison-delta"
          >
            <DeltaIcon className="w-3 h-3 mr-1" />
            {deltaPct >= 0 ? '+' : ''}{deltaPct.toLocaleString('id-ID', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%
          </span>
        </>
      )}
    </div>
  );
}

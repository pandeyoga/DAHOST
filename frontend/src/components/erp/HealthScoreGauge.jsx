/**
 * HealthScoreGauge — circular progress untuk display health score 0-100.
 * Pure SVG, no external deps.
 */
export function HealthScoreGauge({ score = 0, size = 120, strokeWidth = 10, label = 'Skor kesehatan' }) {
  // Standar UI/UX v2: skor yang belum ada (null) tampil "—", bukan 0 merah.
  const kosong = score === null || score === undefined || Number.isNaN(Number(score));
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const safe = kosong ? 0 : Math.min(100, Math.max(0, score));
  const offset = circumference - (safe / 100) * circumference;

  const colorFor = (s) => {
    if (kosong) return 'text-muted-foreground';
    if (s >= 80) return 'text-[hsl(var(--success-text))]';
    if (s >= 60) return 'text-[hsl(var(--warning-text))]';
    return 'text-[hsl(var(--danger-text))]';
  };

  const strokeColor = colorFor(safe);
  const ringColor = kosong ? 'transparent' : (safe >= 80) ? 'hsl(var(--success))' : (safe >= 60) ? 'hsl(var(--warning))' : 'hsl(var(--destructive))';

  return (
    <div className="flex flex-col items-center justify-center" data-testid="health-score-gauge">
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90" aria-hidden="true">
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            stroke="currentColor"
            strokeWidth={strokeWidth}
            fill="none"
            className="text-foreground/10"
          />
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            stroke={ringColor}
            strokeWidth={strokeWidth}
            fill="none"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            strokeLinecap="round"
            style={{ transition: 'stroke-dashoffset 600ms ease-out' }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <div className={`text-2xl font-bold tabular-nums ${strokeColor}`}>{kosong ? '—' : safe}</div>
          <div className="text-xs text-muted-foreground">{kosong ? 'belum ada' : 'dari 100'}</div>
        </div>
      </div>
      {label && <div className="text-xs text-muted-foreground mt-2">{label}</div>}
    </div>
  );
}

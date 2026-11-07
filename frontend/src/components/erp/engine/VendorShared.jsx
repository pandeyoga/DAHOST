import { StatTile } from '../moduleAtoms';
// Standar UI/UX v2 (8 Nov 2026): kartu angka vendor = StatTile (satu gaya kartu); dulu kartu berikon berwarna sendiri.
export function StatCard({ title, value, sub, alert }) {
  return <StatTile label={title} value={value} sub={sub} accent={alert ? 'danger' : 'default'} />;
}

export function MiniBar({ pct }) {
  const color = pct >= 100 ? 'bg-[hsl(var(--success))]' : pct >= 60 ? 'bg-[hsl(var(--primary))]' : pct >= 30 ? 'bg-[hsl(var(--warning))]' : 'bg-[hsl(var(--destructive))]';
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-muted rounded-full h-2">
        <div className={`h-2 rounded-full transition-all ${color}`} style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
      <span className="text-xs font-bold text-foreground/90 w-9 text-right">{pct}%</span>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────


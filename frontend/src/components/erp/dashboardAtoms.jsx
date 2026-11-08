/**
 * Dashboard Atoms — komponen dashboard bersama: StatCard, ChartCard, GlassTooltip, HeroCrystalCard, DonutProgress,
 * TrendDelta, CHART_PALETTE.
 *
 * Standar UI/UX v2 (keputusan owner 8 Nov 2026): SATU gaya kartu angka (sama dengan `StatTile`: putih/netral,
 * label 12 px, angka 20 px, ikon kecil abu — tanpa kotak ikon berwarna, tanpa HURUF BESAR), kartu grafik polos
 * (judul 16 px), dan kepala halaman TIPIS (tanpa cahaya/kristal/gradasi). Props tetap sama supaya layar lain yang
 * memakainya (mis. Dashboard Produksi) ikut seragam tanpa diubah.
 */
import { cn } from '@/lib/utils';
import { ArrowUp, ArrowDown, Minus } from 'lucide-react';

/* ───────────────────────────────────────────────────────────────────────── */
/*  TrendDelta — chip kecil menampilkan delta + arrow                        */
/* ───────────────────────────────────────────────────────────────────────── */
export function TrendDelta({ value, suffix = '%', neutralThreshold = 0.01 }) {
  if (value === null || value === undefined) return null;
  const v = Number(value);
  const neutral = Math.abs(v) < neutralThreshold;
  const positive = v > 0;
  const Icon = neutral ? Minus : positive ? ArrowUp : ArrowDown;
  const color = neutral
    ? 'text-muted-foreground'
    : positive
      ? 'text-[hsl(var(--success-text))]'
      : 'text-[hsl(var(--danger-text))]';
  return (
    <span className={cn('inline-flex items-center gap-0.5 text-xs font-semibold', color)}>
      <Icon className="w-3 h-3" strokeWidth={2.5} />
      {Math.abs(v).toLocaleString('id-ID', { maximumFractionDigits: 1 })}{suffix}
    </span>
  );
}

/* ───────────────────────────────────────────────────────────────────────── */
/*  StatCard — kartu angka, tampilan = StatTile (satu gaya kartu angka)       */
/* ───────────────────────────────────────────────────────────────────────── */
const ACCENT_TEXT = {
  primary: 'text-foreground',
  info: 'text-foreground',
  mint: 'text-foreground',
  success: 'text-[hsl(var(--success-text))]',
  warning: 'text-[hsl(var(--warning-text))]',
  danger: 'text-[hsl(var(--danger-text))]',
};

export function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  trend,
  accent = 'primary', // primary | success | warning | info | mint — hanya warna ANGKA untuk success/warning
  className,
  testId,
  onClick,
  hint,
}) {
  const Component = onClick ? 'button' : 'div';
  // nol selalu abu (PANDUAN_UI G5)
  const nol = /^(Rp\s?)?[-−]?0([.,]0+)?%?$/.test(String(value ?? '').trim());
  return (
    <Component
      onClick={onClick}
      type={onClick ? 'button' : undefined}
      title={onClick ? (hint || 'Klik untuk lihat detail') : hint}
      data-testid={testId}
      className={cn(
        'w-full rounded-[var(--radius-md)] border px-4 py-3 text-left flex flex-col h-full',
        'bg-[var(--card-surface)] border-[var(--glass-border)] backdrop-blur-[var(--glass-blur)]',
        onClick && 'cursor-pointer transition-[border-color,box-shadow] duration-150 hover:border-[hsl(var(--primary)/0.45)] hover:shadow-[var(--shadow-card)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))]',
        className
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        {Icon && <Icon className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={2} aria-hidden="true" />}
      </div>
      <p className={cn('mt-1 text-xl font-bold tracking-tight tabular-nums',
        nol ? 'text-muted-foreground' : (ACCENT_TEXT[accent] || 'text-foreground'))}>{value}</p>
      {sub && <p className="mt-1 text-xs text-muted-foreground line-clamp-2">{sub}</p>}
      {trend !== undefined && trend !== null && (
        <div className="mt-auto pt-2 flex items-center gap-2">
          <TrendDelta value={trend.value} suffix={trend.suffix || '%'} />
          {trend.label && <span className="text-xs text-muted-foreground">{trend.label}</span>}
        </div>
      )}
    </Component>
  );
}

/* ───────────────────────────────────────────────────────────────────────── */
/*  ChartCard — kartu standar untuk grafik/daftar dengan judul + aksi         */
/* ───────────────────────────────────────────────────────────────────────── */
export function ChartCard({ title, subtitle, actions, children, className, testId }) {
  return (
    <div
      data-testid={testId}
      className={cn(
        'min-w-0 rounded-[var(--radius-lg)] border p-4',
        'bg-[var(--card-surface)] border-[var(--glass-border)]',
        'backdrop-blur-[var(--glass-blur)]',
        className
      )}
    >
      {(title || subtitle || actions) && (
        <div className="flex flex-wrap items-start justify-between gap-2 mb-3">
          <div className="min-w-0">
            {title && <p className="text-base font-semibold text-foreground">{title}</p>}
            {subtitle && <p className="text-sm text-muted-foreground">{subtitle}</p>}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </div>
  );
}

/* ───────────────────────────────────────────────────────────────────────── */
/*  GlassTooltip — custom tooltip untuk Recharts                              */
/* ───────────────────────────────────────────────────────────────────────── */
export function GlassTooltip({ active, payload, label, formatter }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-[var(--radius-sm)] border border-[var(--glass-border)] bg-[var(--popover-surface)] backdrop-blur-[var(--glass-blur-strong)] shadow-[var(--shadow-soft)] px-3 py-2">
      {label && <p className="text-xs font-semibold text-foreground mb-1.5">{label}</p>}
      <div className="space-y-1">
        {payload.map((p, i) => (
          <div key={i} className="flex items-center gap-2 text-xs">
            <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: p.color || p.fill }} />
            <span className="text-muted-foreground">{p.name}:</span>
            <span className="font-semibold text-foreground tabular-nums">
              {formatter ? formatter(p.value) : (p.value ?? 0).toLocaleString('id-ID')}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ───────────────────────────────────────────────────────────────────────── */
/*  HeroCrystalCard — kepala halaman TIPIS (Standar UI/UX v2: tanpa cahaya,   */
/*  kristal, gradasi, atau eyebrow huruf besar). Props lama tetap diterima.   */
/* ───────────────────────────────────────────────────────────────────────── */
export function HeroCrystalCard({ eyebrow: _eyebrow, title, description, children, className, testId, actions }) {
  return (
    <div data-testid={testId} className={cn('space-y-3', className)}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          {title && <p className="text-xl font-bold leading-tight tracking-tight text-foreground sm:text-2xl">{title}</p>}
          {description && <p className="mt-1 hidden text-sm text-muted-foreground sm:block">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children && <div>{children}</div>}
    </div>
  );
}

/* ───────────────────────────────────────────────────────────────────────── */
/*  DonutProgress — ring chart pure SVG untuk single % value                 */
/* ───────────────────────────────────────────────────────────────────────── */
export function DonutProgress({ value = 0, size = 140, stroke = 12, label, sub, accent = 'primary' }) {
  const pct = Math.max(0, Math.min(100, Number(value) || 0));
  const r = (size - stroke) / 2;
  const C = 2 * Math.PI * r;
  const offset = C * (1 - pct / 100);
  const colorVar = accent === 'success' ? 'var(--success)' : accent === 'warning' ? 'var(--warning)' : 'var(--primary)';

  return (
    <div className="relative grid place-items-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="transform -rotate-90">
        <circle
          cx={size / 2} cy={size / 2} r={r}
          stroke="currentColor"
          strokeWidth={stroke}
          fill="none"
          className="text-[var(--glass-border)]"
        />
        <circle
          cx={size / 2} cy={size / 2} r={r}
          stroke={`hsl(${colorVar})`}
          strokeWidth={stroke}
          fill="none"
          strokeDasharray={C}
          strokeDashoffset={offset}
          strokeLinecap="round"
          style={{ transition: 'stroke-dashoffset 800ms cubic-bezier(0.16, 1, 0.3, 1)' }}
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center">
        <div>
          <p className="text-2xl font-bold text-foreground leading-none tracking-tight">{pct.toFixed(0)}<span className="text-base text-muted-foreground">%</span></p>
          {label && <p className="text-xs text-muted-foreground mt-1">{label}</p>}
          {sub && <p className="text-xs text-muted-foreground mt-0.5">{sub}</p>}
        </div>
      </div>
    </div>
  );
}

/* Shared chart colors (reference only — components should use CSS vars via style) */
export const CHART_PALETTE = [
  'hsl(var(--chart-1))',
  'hsl(var(--chart-2))',
  'hsl(var(--chart-3))',
  'hsl(var(--chart-4))',
  'hsl(var(--chart-5))',
];

import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { formatAngkaRingkas } from '@/lib/format';

// 2026-11-08: pemformat sumbu dipindah ke lib/format (dipakai juga grafik Asisten AI) — "1,5 jt", bukan "1.5jt".
const fmtCompact = formatAngkaRingkas;

const fmtFull = (n) => `Rp ${Number(n || 0).toLocaleString('id-ID')}`;
const fmtDateShort = (d) => {
  if (!d) return '';
  const date = new Date(`${String(d).slice(0, 10)}T00:00:00Z`);
  return date.toLocaleDateString('id-ID', { day: '2-digit', month: 'short', timeZone: 'UTC' });
};

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload || !payload.length) return null;
  return (
    <div className="rounded-lg bg-[var(--card-surface)] border border-[var(--glass-border)] p-3 shadow-lg">
      <div className="text-xs text-muted-foreground mb-2">
        {new Date(`${String(label).slice(0, 10)}T00:00:00Z`).toLocaleDateString('id-ID', { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' })}
      </div>
      {payload.map((p, i) => (
        <div key={i} className="flex items-center justify-between gap-3 text-xs">
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full" style={{ background: p.color }} />
            {p.name}
          </span>
          <span className="font-semibold">{fmtFull(p.value)}</span>
        </div>
      ))}
    </div>
  );
}

/**
 * RevenueChart — line chart untuk trend revenue total vs live.
 * Data shape: [{ date: 'YYYY-MM-DD', total: number, live: number }, ...]
 * Standar UI/UX v2 (8 Nov 2026): warna token (dulu hex), label Indonesia, kosong tanpa kotak abu.
 */
export function RevenueChart({ data = [], height = 280 }) {
  if (!data || data.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center text-sm text-muted-foreground" data-testid="revenue-chart-empty">
        Belum ada omzet pada periode ini
      </div>
    );
  }

  return (
    <div data-testid="revenue-chart" style={{ width: '100%', height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.4} />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }}
            tickFormatter={fmtDateShort}
          />
          <YAxis
            tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }}
            tickFormatter={fmtCompact}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend wrapperStyle={{ fontSize: 12, paddingTop: 10 }} />
          <Line
            type="monotone"
            dataKey="total"
            name="Omzet total"
            stroke="hsl(var(--primary))"
            strokeWidth={2.5}
            dot={{ r: 3 }}
            activeDot={{ r: 5 }}
          />
          <Line
            type="monotone"
            dataKey="live"
            name="Omzet live"
            stroke="hsl(var(--warning))"
            strokeWidth={2.5}
            dot={{ r: 3 }}
            activeDot={{ r: 5 }}
            strokeDasharray="5 3"
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

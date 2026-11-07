/**
 * StatementTable — tabel laporan keuangan (PANDUAN_UI G7, 2026-11-04).
 *
 * Dipakai Laba Rugi, Neraca, Arus Kas. Menggantikan tumpukan kartu per kelompok + "pil" subtotal
 * (audit layar: BARIS-JADI-KARTU). Satu kartu, satu tabel:
 *   · baris kelompok (bisa dilipat ▸) dengan total kelompok;
 *   · baris akun menjorok ke dalam (kode kecil + nama);
 *   · subtotal tebal bergaris atas; total akhir tebal bergaris ganda.
 *
 *   <StatementTable columns={[{ key: 'amount', label: '1 Jan – 4 Nov 2026' }]} rows={[
 *     { kind: 'group', id: 'revenue', label: 'Pendapatan', values: { amount: 7041289 },
 *       children: [{ code: '4-1110', label: 'Penjualan', values: { amount: 6120000 } }] },
 *     { kind: 'subtotal', label: 'Laba kotor', values: { amount: 7041289 } },
 *     { kind: 'total', label: 'Laba bersih', values: { amount: 6486289 } },
 *   ]} />
 *
 * Angka: rata kanan, tabular, minus = "−1.234" merah, nol = abu. `defaultOpen` membuka semua kelompok.
 */
import { Fragment, useState } from 'react';
import { ChevronRight } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { cn } from '@/lib/utils';

const fmtNum = (n) => {
  const v = Number(n || 0);
  const s = Math.abs(v).toLocaleString('id-ID', { maximumFractionDigits: 0 });
  return v < -0.5 ? `−${s}` : s;
};

function Cell({ v, strong, blankZero }) {
  const n = Number(v || 0);
  const zero = Math.abs(n) < 0.5;
  return (
    <td className={cn('text-right whitespace-nowrap tabular-nums',
      strong && 'font-semibold', n < -0.5 && 'text-[hsl(var(--destructive))]', zero && 'text-muted-foreground')}>
      {v === undefined || v === null || (zero && blankZero) ? '' : fmtNum(n)}
    </td>
  );
}

/**
 * Isi unduhan (Excel/CSV) untuk laporan yang sama — Standar UI/UX v2: semua tabel bisa diunduh.
 * Semua kelompok ikut terbuka (baris akun di bawah kelompoknya), subtotal & total ikut. Angka tetap angka.
 *   const u = unduhanLaporan(columns, rows);  <TombolUnduh namaBerkas="laba-rugi" kolom={u.kolom} baris={u.baris} />
 */
export function unduhanLaporan(columns, rows, labelHeader = 'Akun') {
  const baris = [];
  for (const r of rows || []) {
    if (r.kind === 'note') continue;
    baris.push({ jenis: r.kind === 'group' ? 'Kelompok' : r.kind === 'total' ? 'Total' : r.kind === 'subtotal' ? 'Subtotal' : '',
      kode: '', nama: r.label, values: r.values || {} });
    if (r.kind === 'group') {
      for (const k of r.children || []) baris.push({ jenis: 'Akun', kode: k.code || '', nama: k.label, values: k.values || {} });
    }
  }
  const kolom = [
    { label: 'Baris', nilai: (b) => b.jenis },
    { label: 'Kode', nilai: (b) => b.kode },
    { label: labelHeader, nilai: (b) => (typeof b.nama === 'string' ? b.nama : String(b.nama ?? '')) },
    ...columns.map((c) => ({ label: typeof c.label === 'string' ? c.label : c.key,
      nilai: (b) => (b.values[c.key] === undefined || b.values[c.key] === null ? '' : Math.round(Number(b.values[c.key]) || 0)) })),
  ];
  return { kolom, baris };
}

export default function StatementTable({ columns, rows, labelHeader = 'Akun', defaultOpen = false, testId, blankZeroChildren = false, className }) {
  const [open, setOpen] = useState(() => (defaultOpen ? new Set(rows.filter((r) => r.kind === 'group').map((r) => r.id)) : new Set()));
  const toggle = (id) => setOpen((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const colSpan = columns.length + 1;
  return (
    <GlassCard className={cn('p-0 overflow-hidden', className)} data-testid={testId}>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr>
              <th className="text-left">{labelHeader}</th>
              {columns.map((c) => <th key={c.key} className="text-right">{c.label}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              if (r.kind === 'group') {
                const kids = (r.children || []).filter((c) => !r.hideZeroChildren || columns.some((col) => Math.abs(Number(c.values?.[col.key] || 0)) >= 0.5));
                const isOpen = open.has(r.id);
                return (
                  <Fragment key={r.id || i}>
                    <tr className={cn(kids.length && 'cursor-pointer hover:bg-foreground/[0.03]')} onClick={() => kids.length && toggle(r.id)}
                        data-testid={testId ? `${testId}-${r.id}` : undefined}>
                      <td className="font-medium text-foreground">
                        <span className="inline-flex items-center gap-1.5">
                          <ChevronRight className={cn('w-3.5 h-3.5 text-muted-foreground transition-transform', isOpen && 'rotate-90', !kids.length && 'opacity-0')} />
                          {r.label}
                          {r.hint && <span className="text-xs text-muted-foreground font-normal">{r.hint}</span>}
                        </span>
                      </td>
                      {columns.map((c) => <Cell key={c.key} v={r.values?.[c.key]} strong />)}
                    </tr>
                    {isOpen && kids.map((k, j) => (
                      <tr key={`${r.id}-${k.code || j}`} data-testid={testId && k.code ? `${testId}-${r.id}-row-${k.code}` : undefined}>
                        <td className="!pl-10 text-foreground/80">
                          {k.code && <span className="text-xs text-muted-foreground mr-2">{k.code}</span>}{k.label}
                          {k.note && <span className="ml-2 text-xs text-muted-foreground">{k.note}</span>}
                        </td>
                        {columns.map((c) => <Cell key={c.key} v={k.values?.[c.key]} blankZero={blankZeroChildren} />)}
                      </tr>
                    ))}
                    {isOpen && !kids.length && (
                      <tr><td colSpan={colSpan} className="!pl-10 text-xs text-muted-foreground">Tidak ada saldo di periode ini.</td></tr>
                    )}
                  </Fragment>
                );
              }
              if (r.kind === 'note') {
                return <tr key={i}><td colSpan={colSpan} className="text-xs text-muted-foreground">{r.label}</td></tr>;
              }
              const isTotal = r.kind === 'total';
              return (
                <tr key={i} data-testid={r.testId}
                    className={cn(isTotal ? 'border-t-[3px] border-double border-[var(--glass-border)]' : r.kind === 'subtotal' ? 'border-t-2 border-[var(--glass-border)]' : '')}>
                  <td className={cn('text-foreground', r.kind !== 'line' && 'font-semibold', isTotal && 'text-base')}>{r.label}</td>
                  {columns.map((c) => <Cell key={c.key} v={r.values?.[c.key]} strong={r.kind !== 'line'} />)}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </GlassCard>
  );
}

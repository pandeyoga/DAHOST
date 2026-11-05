import { Wallet } from 'lucide-react';
import { formatDateID, formatRupiah as fmt } from '@/lib/format';
import { journalSourceLabel } from '@/lib/financeLabels';
import { EmptyState, Notice, StatusBadge } from '../../moduleAtoms';

// Hasil cek → label & nada StatusBadge (PANDUAN_UI G8: token, bukan palet langsung).
const STATUS = {
  ok: ['Sesuai', 'success'],
  no_gl: ['Belum dijurnal', 'danger'],
  gl_missing: ['Jurnal hilang', 'danger'],
  gl_voided: ['Jurnal dibatalkan', 'warning'],
  gl_outside_period: ['Beda periode', 'warning'],
  amount_mismatch: ['Nominal beda', 'danger'],
};

// H-05: mutasi kas internal (rahaza_cash_movements) harus 1:1 dengan jurnal akun bank.
// 2026-11-05: di dalam DetailPanel — kotak saldo = Notice, tanggal formatDateID, kosong = EmptyState.
export function InternalCheckPanel({ check }) {
  if (!check) return null;
  const diff = Math.round((check.card_balance - check.gl_balance_now) * 100) / 100;
  const synced = Math.abs(diff) < 0.01;
  return (
    <div className="space-y-3" data-testid="recon-internal-check">
      <Notice tone={synced ? 'success' : 'warning'} testId="recon-ic-balance" className="text-xs">
        <span className="tabular-nums">
          Saldo kartu kas <strong>{fmt(check.card_balance)}</strong> vs saldo buku besar akun bank saat ini <strong>{fmt(check.gl_balance_now)}</strong>
          {synced ? <span className="text-[hsl(var(--success))]"> · sinkron</span> : <span className="text-[hsl(var(--warning))]"> · selisih {fmt(diff)}</span>}
          {' '}· {check.issues.length} mutasi bermasalah · {check.gl_without_movement.length} jurnal bank tanpa mutasi kas
        </span>
      </Notice>
      {check.movements.length === 0 ? (
        <EmptyState icon={Wallet} testId="recon-ic-empty" title="Belum ada mutasi kas internal"
          description="Tidak ada mutasi kas internal di periode ini." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground border-b border-[var(--glass-border)]">
                <th className="px-3 py-2">Tanggal</th>
                <th className="px-3 py-2">Mutasi kas</th>
                <th className="px-3 py-2 text-right">Nominal</th>
                <th className="px-3 py-2">Jurnal</th>
                <th className="px-3 py-2">Cek</th>
              </tr>
            </thead>
            <tbody>
              {check.movements.map(m => {
                const [label, tone] = STATUS[m.status] || STATUS.ok;
                return (
                  <tr key={m.id} className="border-b border-[var(--glass-border)] last:border-0" data-testid={`recon-ic-${m.id}`}>
                    <td className="px-3 py-2 whitespace-nowrap">{formatDateID(m.date)}</td>
                    <td className="px-3 py-2">{m.ref_label || m.category} <span className="text-muted-foreground">· {journalSourceLabel(m.source_module)}</span></td>
                    <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap">{m.direction === 'in' ? '+' : '−'}{fmt(m.amount)}</td>
                    <td className="px-3 py-2 whitespace-nowrap">{m.gl_je_number || '—'}</td>
                    <td className="px-3 py-2">
                      <span title={m.note}><StatusBadge status={m.status} label={label} tone={tone} /></span>
                      {m.note && m.status !== 'ok' && <span className="text-xs text-muted-foreground ml-1">{m.note}</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {check.gl_without_movement.length > 0 && (
        <p className="text-xs text-muted-foreground" data-testid="recon-ic-gl-only">
          Jurnal bank tanpa mutasi kas (mis. pencairan marketplace, penyesuaian lama): {check.gl_without_movement.map(g => g.je_number).join(', ')}
        </p>
      )}
    </div>
  );
}

import { formatDateID, formatRupiah as fmt } from '@/lib/format';
import { Notice } from '../../moduleAtoms';

const tone = {
  success: 'text-[hsl(var(--success-text))]',
  warning: 'text-[hsl(var(--warning-text))]',
};

// Ringkasan: saldo buku besar akun bank vs saldo rekening koran, dijelaskan oleh item yang belum cocok.
// Pada sesi approved, `summary` = approved_summary (snapshot saat disetujui), bukan hitungan live.
// 2026-11-05 (PANDUAN_UI G5/G8): dirender di dalam DetailPanel — angka tanpa kartu (dulu Card shadcn di dalam
// kartu), kotak penjelasan = Notice, warna hanya token.
export function ReconSummary({ summary, approved }) {
  if (!summary) return null;
  const noticeTone = approved ? 'info' : summary.explained ? 'success' : 'warning';
  return (
    <div className="space-y-2" data-testid="recon-summary">
      {approved && (
        <div className="flex items-center gap-2 flex-wrap text-xs text-muted-foreground" data-testid="recon-approved-note">
          <span className="font-medium text-foreground">Ringkasan saat disetujui</span>
          {approved.at && <span>· {formatDateID(approved.at)}</span>}
          {approved.by && <span>· oleh {approved.by}</span>}
          {approved.withUnexplained && <span className={`${tone.warning} font-medium tabular-nums`} data-testid="recon-approved-unexplained-flag">· disetujui dengan selisih {fmt(summary.unexplained)}</span>}
        </div>
      )}
      <dl className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          ['Saldo buku besar akun bank (akhir periode)', summary.gl_balance_end, 'recon-sum-gl'],
          ['Saldo rekening koran', summary.statement_closing, 'recon-sum-statement'],
          ['Mutasi bank belum cocok', `${summary.unmatched_bank_count} · masuk ${fmt(summary.unmatched_bank_in)} / keluar ${fmt(summary.unmatched_bank_out)}`, 'recon-sum-unbank'],
          ['Jurnal belum cocok', `${summary.unmatched_gl_count} · masuk ${fmt(summary.unmatched_gl_in)} / keluar ${fmt(summary.unmatched_gl_out)}`, 'recon-sum-ungl'],
        ].map(([label, val, tid]) => (
          <div key={tid} className="min-w-0">
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="text-sm font-semibold tabular-nums mt-0.5" data-testid={tid}>{typeof val === 'number' ? fmt(val) : val}</dd>
          </div>
        ))}
      </dl>
      <Notice tone={noticeTone} testId="recon-sum-explained" className="text-xs">
        <span className="tabular-nums">
          Saldo buku besar {fmt(summary.gl_balance_end)} + mutasi bank belum dijurnal ({fmt(summary.unmatched_bank_in - summary.unmatched_bank_out)})
          − jurnal belum tampak di bank ({fmt(summary.unmatched_gl_in - summary.unmatched_gl_out)}) = <strong>{fmt(summary.adjusted_gl_balance)}</strong>
          {' '}vs rekening koran <strong>{fmt(summary.statement_closing)}</strong> →{' '}
          {summary.explained ? <strong className={tone.success}>selisih terjelaskan</strong>
            : <strong className={approved ? 'text-foreground' : tone.warning}>
                {approved ? 'selisih ' : 'selisih belum terjelaskan '}{fmt(summary.unexplained)}{approved ? ' (dicatat saat persetujuan)' : ''}
              </strong>}
        </span>
      </Notice>
    </div>
  );
}

import { BookOpen } from 'lucide-react';
import { formatDateID, formatRupiah as fmt } from '@/lib/format';
import { humanMemo, journalSourceLabel } from '@/lib/financeLabels';
import { EmptyState, StatusBadge } from '../../moduleAtoms';

// Baris jurnal pada akun bank sesi (posted, dalam periode). Sumber: rahaza_journal_entries.lines.
// 2026-11-05 (PANDUAN_UI G7/G8/G10): tanggal formatDateID, angka tabular-nums (bukan font-mono), kolom
// "Masuk (Dr)/Keluar (Cr)" → "Debit"/"Kredit", warna token, kosong = EmptyState.
export function GlLinesTable({ lines, glAccountCode }) {
  if (!lines?.length) {
    return (
      <EmptyState icon={BookOpen} testId="recon-gl-empty" title="Belum ada jurnal"
        description={`Belum ada jurnal pada akun ${glAccountCode} di periode ini.`} />
    );
  }
  return (
    <div className="overflow-x-auto" data-testid="recon-gl-table">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-muted-foreground border-b border-[var(--glass-border)]">
            <th className="px-3 py-2">Tanggal</th>
            <th className="px-3 py-2">No. jurnal</th>
            <th className="px-3 py-2">Keterangan / sumber</th>
            <th className="px-3 py-2 text-right">Debit</th>
            <th className="px-3 py-2 text-right">Kredit</th>
            <th className="px-3 py-2">Status</th>
          </tr>
        </thead>
        <tbody>
          {lines.map(g => (
            <tr key={g.key} className="border-b border-[var(--glass-border)] last:border-0" data-testid={`recon-gl-${g.key}`}>
              <td className="px-3 py-2 whitespace-nowrap">{formatDateID(g.date)}</td>
              <td className="px-3 py-2 whitespace-nowrap">{g.je_number}</td>
              <td className="px-3 py-2 max-w-[320px] truncate" title={g.memo}>{humanMemo(g.memo || g.description)} <span className="text-muted-foreground">· {journalSourceLabel(g.source_module)}</span></td>
              <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap">{g.debit > 0 ? fmt(g.debit) : ''}</td>
              <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap">{g.credit > 0 ? fmt(g.credit) : ''}</td>
              <td className="px-3 py-2">{g.is_matched ? <StatusBadge status="matched" label="Cocok" tone="success" />
                : <StatusBadge status="unmatched" label="Belum di bank" tone="muted" />}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

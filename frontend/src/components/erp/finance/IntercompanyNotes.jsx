/**
 * Catatan eliminasi antar CV untuk laporan GABUNGAN (Tahap 8 fase 3).
 *
 * Laporan Gabungan (Laba Rugi, Neraca, per bulan) dari backend membawa `intercompany`:
 *   { eliminated, rows: [{code, debit, credit}], notes: [{label, detail, amount}], unreconciled_total }
 * Komponen ini menampilkan satu kalimat "sudah dieliminasi" + setiap catatan
 * "Selisih antar CV yang belum tereliminasi: Rp X" (tidak disembunyikan). Kosong bila bukan Gabungan.
 */
import { Info } from 'lucide-react';
import { formatRupiah } from '@/lib/format';
import { Notice } from '../moduleAtoms';

export default function IntercompanyNotes({ data, testId = 'ic-notes' }) {
  const ic = data?.intercompany;
  if (!ic) return null;
  const rows = ic.rows || [];
  const total = rows.reduce((s, r) => s + Number(r.debit || 0), 0);
  return (
    <Notice tone="info" icon={Info} testId={testId}
      title={`Gabungan setelah eliminasi antar CV${total ? ` · ${formatRupiah(total)} dieliminasi di ${rows.length} akun` : ''}`}>
      {(ic.notes || []).length === 0
        ? <p className="text-xs">Semua hutang/piutang dan laba antar CV pada periode ini sudah tereliminasi.</p>
        : (
          <ul className="text-xs space-y-1" data-testid={`${testId}-list`}>
            {ic.notes.map((n, i) => <li key={i}><b>{n.label}</b> — {n.detail}</li>)}
          </ul>
        )}
    </Notice>
  );
}

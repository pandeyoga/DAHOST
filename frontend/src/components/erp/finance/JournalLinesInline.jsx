/**
 * JournalLinesInline — isi satu jurnal (akun, debit, kredit) untuk dibuka DI BAWAH barisnya (RowDetail).
 * PANDUAN_UI G13: detail dibuka di halaman, bukan popup.
 *
 *   {open && <RowDetail colSpan={7}><JournalLinesInline jeId={m.je_id} token={token} /></RowDetail>}
 */
import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { formatDateID, formatNumber } from '@/lib/format';
import { journalSourceLabel } from '@/lib/financeLabels';
import { StatusBadge } from '../moduleAtoms';

export default function JournalLinesInline({ jeId, token, testId = 'je-inline' }) {
  const [je, setJe] = useState(null);
  const [err, setErr] = useState('');
  useEffect(() => {
    let alive = true;
    setJe(null); setErr('');
    fetch(`/api/rahaza/journals/${jeId}`, { headers: { Authorization: `Bearer ${token}` } })
      .then(async (r) => {
        const d = await r.json().catch(() => ({}));
        if (!alive) return;
        if (!r.ok) setErr(d.detail || `Jurnal tidak bisa dimuat (HTTP ${r.status})`);
        else setJe(d);
      })
      .catch(() => alive && setErr('Jurnal tidak bisa dimuat.'));
    return () => { alive = false; };
  }, [jeId, token]);

  if (err) return <p className="text-sm text-[hsl(var(--destructive))]">{err}</p>;
  if (!je) return <p className="text-sm text-muted-foreground flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" />Memuat jurnal…</p>;
  const lines = je.lines || [];
  return (
    <div className="space-y-2" data-testid={testId}>
      <p className="text-sm text-muted-foreground">
        <span className="text-foreground font-medium">{je.je_number}</span> · {formatDateID(je.date)} · {journalSourceLabel(je.source_module)}
        {je.memo ? ` · ${je.memo}` : ''} <StatusBadge status={je.status} className="ml-1" />
      </p>
      <table className="w-full">
        <thead><tr><th className="text-left">Akun</th><th className="text-left">Keterangan</th><th className="text-right">Debit</th><th className="text-right">Kredit</th></tr></thead>
        <tbody>
          {lines.map((l, i) => (
            <tr key={l.id || i}>
              <td className="whitespace-nowrap"><span className="text-muted-foreground">{l.account_code}</span> {l.account_name || ''}</td>
              <td className="text-muted-foreground">{l.description || '—'}</td>
              <td className="text-right tabular-nums">{Number(l.debit) ? formatNumber(l.debit) : ''}</td>
              <td className="text-right tabular-nums">{Number(l.credit) ? formatNumber(l.credit) : ''}</td>
            </tr>
          ))}
          <tr className="font-semibold">
            <td colSpan={2}>Total</td>
            <td className="text-right tabular-nums">{formatNumber(je.total_debit)}</td>
            <td className="text-right tabular-nums">{formatNumber(je.total_credit)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

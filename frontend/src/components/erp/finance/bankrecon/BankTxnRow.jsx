import { useState, useEffect } from 'react';
import axios from 'axios';
import { Button } from '@/components/ui/button';
import { Link2, Unlink, Trash2, Wand2, Banknote, Loader2 } from 'lucide-react';
import { formatDateID, formatRupiah as fmt } from '@/lib/format';
import { cn } from '@/lib/utils';
import { humanMemo } from '@/lib/financeLabels';
import { StatusBadge } from '../../moduleAtoms';
import { SettlementLinkPicker } from '../SettlementLinkPicker';

const API = process.env.REACT_APP_BACKEND_URL;

function CandidatePicker({ sessionId, txn, headers, onPick }) {
  const [items, setItems] = useState(null);
  useEffect(() => {
    axios.get(`${API}/api/finance/bank-recon/sessions/${sessionId}/transactions/${txn.id}/candidates`, { headers })
      .then(r => setItems(r.data.items || [])).catch(() => setItems([]));
  }, [sessionId, txn.id, headers]);
  if (items === null) return <p className="text-xs text-muted-foreground flex items-center gap-2"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Memuat kandidat…</p>;
  if (!items.length) return <p className="text-xs text-muted-foreground" data-testid="recon-no-candidates">Tidak ada baris jurnal akun bank dengan arah yang sama di periode ini.</p>;
  return (
    <div className="max-h-56 overflow-y-auto space-y-1" data-testid="recon-candidates">
      {items.map(g => (
        <Button key={g.key} type="button" variant="outline" data-testid={`recon-cand-${g.key}`} onClick={() => onPick(g)}
          className={cn('w-full h-auto px-3 py-2 flex-col items-stretch gap-0.5 text-left text-xs font-normal whitespace-normal',
            g.within_rule && 'border-[hsl(var(--success)/0.5)]')}>
          <span className="flex justify-between gap-2">
            <span className="truncate min-w-0">{formatDateID(g.date)} · {g.je_number} · {humanMemo(g.memo || g.description)}</span>
            <span className="font-medium whitespace-nowrap tabular-nums">{fmt(g.amount)}</span>
          </span>
          <span className="text-muted-foreground tabular-nums">
            Selisih {fmt(Math.abs(g.amount_diff))} · {g.days_apart ?? '—'} hari {g.within_rule && <span className="text-[hsl(var(--success-text))]">· sesuai aturan</span>}
          </span>
        </Button>
      ))}
    </div>
  );
}

// Satu baris mutasi bank + aksi: cocokkan manual, tautkan pencairan, buat penyesuaian, lepas, hapus.
// 2026-11-05 (PANDUAN_UI G5/G8): baris daftar di dalam DetailPanel — bukan kartu per baris; warna hanya token,
// tanggal formatDateID.
export function BankTxnRow({ sessionId, txn, headers, readOnly, onMatch, onUnmatch, onAdjust, onDelete, onLinkSettlement }) {
  const [open, setOpen] = useState(null); // 'gl' | 'settlement' | 'adjust'
  const isIn = (txn.direction || (txn.type === 'debit' ? 'in' : 'out')) === 'in';
  return (
    <div className="border-b border-[var(--glass-border)] last:border-0 py-3" data-testid={`recon-txn-${txn.id}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground text-xs whitespace-nowrap">{formatDateID(txn.txn_date)}</span>
            <span className="truncate">{txn.description || '—'}</span>
            {txn.reference && <span className="text-xs text-muted-foreground">#{txn.reference}</span>}
          </div>
          {txn.is_matched && (
            <p className="text-xs text-[hsl(var(--success-text))] mt-1" data-testid={`recon-txn-matchref-${txn.id}`}>
              Cocok: {txn.match_ref} {txn.auto_matched ? '· otomatis' : ''} {Math.abs(txn.amount_diff || 0) > 0.01 ? `· selisih ${fmt(Math.abs(txn.amount_diff))}` : ''}
            </p>
          )}
        </div>
        <div className="text-right space-y-1">
          <p className={cn('font-semibold text-sm tabular-nums whitespace-nowrap', isIn ? 'text-[hsl(var(--success-text))]' : 'text-foreground')}>{isIn ? '+' : '−'}{fmt(txn.amount)}</p>
          <StatusBadge status={isIn ? 'in' : 'out'} label={isIn ? 'Masuk' : 'Keluar'} tone={isIn ? 'success' : 'muted'} />
        </div>
      </div>
      {!readOnly && (
        <div className="flex flex-wrap gap-1 mt-2">
          {txn.is_matched ? (
            <Button size="sm" variant="outline" data-testid={`recon-unmatch-${txn.id}`} onClick={() => onUnmatch(txn)}>
              <Unlink /> Lepas
            </Button>
          ) : (
            <>
              <Button size="sm" variant="outline" data-testid={`recon-match-open-${txn.id}`} onClick={() => setOpen(open === 'gl' ? null : 'gl')} aria-expanded={open === 'gl'}>
                <Link2 /> Cocokkan ke jurnal
              </Button>
              {isIn && (
                <Button size="sm" variant="outline" data-testid={`recon-settle-open-${txn.id}`} onClick={() => setOpen(open === 'settlement' ? null : 'settlement')} aria-expanded={open === 'settlement'}>
                  <Banknote /> Pencairan marketplace
                </Button>
              )}
              <Button size="sm" variant="outline" data-testid={`recon-adjust-open-${txn.id}`} onClick={() => setOpen(open === 'adjust' ? null : 'adjust')} aria-expanded={open === 'adjust'}>
                <Wand2 /> Penyesuaian
              </Button>
              <Button size="icon-sm" variant="ghost" data-testid={`recon-txn-delete-${txn.id}`} onClick={() => onDelete(txn)} title="Hapus mutasi" aria-label="Hapus mutasi">
                <Trash2 className="text-[hsl(var(--danger-text))]" />
              </Button>
            </>
          )}
        </div>
      )}
      {open === 'gl' && !txn.is_matched && (
        <div className="mt-2 pl-3 border-l-2 border-primary/30">
          <CandidatePicker sessionId={sessionId} txn={txn} headers={headers} onPick={(g) => { setOpen(null); onMatch(txn, g); }} />
        </div>
      )}
      {open === 'settlement' && !txn.is_matched && (
        <div className="mt-2 pl-3 border-l-2 border-primary/30">
          <SettlementLinkPicker sessionId={sessionId} txn={txn} headers={headers} onLink={(...a) => { setOpen(null); onLinkSettlement(...a); }} />
        </div>
      )}
      {open === 'adjust' && !txn.is_matched && (
        <div className="mt-2 pl-3 border-l-2 border-primary/30 flex flex-wrap gap-1 text-xs">
          <span className="text-muted-foreground self-center mr-1">Jurnal ke akun bank sesi ini:</span>
          {isIn
            ? <Button size="sm" data-testid={`recon-adjust-interest-${txn.id}`} onClick={() => onAdjust(txn, 'interest_income')}>Bunga bank</Button>
            : <>
                <Button size="sm" data-testid={`recon-adjust-charge-${txn.id}`} onClick={() => onAdjust(txn, 'bank_charge')}>Biaya admin bank</Button>
                <Button size="sm" variant="outline" data-testid={`recon-adjust-fee-${txn.id}`} onClick={() => onAdjust(txn, 'service_fee')}>Biaya layanan</Button>
              </>}
        </div>
      )}
    </div>
  );
}

import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { Button } from '@/components/ui/button';
import FilterChips from '@/components/ui/filter-chips';
import { Loader2, Sparkles, Upload, CheckCircle2, RefreshCw, ArrowRightLeft } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';
import { formatRupiah as fmt } from '@/lib/format';
import { MoneyInput } from '@/components/ui/money-input';
import { EmptyState } from '../../moduleAtoms';
import { DetailPanel } from '../../layout/PageLayout';
import { SessionStatusBadge, fmtPeriod } from './SessionList';
import { ReconSummary } from './ReconSummary';
import { ImportPanel } from './ImportPanel';
import { BankTxnRow } from './BankTxnRow';
import { GlLinesTable } from './GlLinesTable';
import { InternalCheckPanel } from './InternalCheckPanel';

const API = process.env.REACT_APP_BACKEND_URL;

/**
 * Satu sesi rekonsiliasi — DetailPanel di atas daftar sesi (PANDUAN_UI G13, 2026-11-05).
 * Dulu mengganti seluruh layar dengan tombol panah kembali; tab Radix di dalamnya (tab di dalam tab) dan deret
 * tombol "Semua/Belum cocok/Cocok" buatan sendiri → pil penyaring (G4). "Auto-match" → "Cocokkan otomatis".
 */
export function SessionDetail({ sessionId, headers, onBack, onChanged }) {
  const { toast } = useToast();
  const [session, setSession] = useState(null);
  const [txns, setTxns] = useState([]);
  const [check, setCheck] = useState(null);
  const [section, setSection] = useState('bank');
  const [filter, setFilter] = useState('all');
  const [showImport, setShowImport] = useState(false);
  const [busy, setBusy] = useState(false);
  const [closing, setClosing] = useState('');
  const base = `${API}/api/finance/bank-recon/sessions/${sessionId}`;
  const fail = useCallback((e) => toast({ title: 'Gagal', description: e?.response?.data?.detail || e.message, variant: 'destructive' }), [toast]);

  const load = useCallback(async () => {
    try {
      const [s, t, c] = await Promise.all([
        axios.get(base, { headers }),
        axios.get(`${base}/transactions`, { headers, params: { limit: 500 } }),
        axios.get(`${base}/internal-check`, { headers }),
      ]);
      setSession(s.data); setTxns(t.data.items || []); setCheck(c.data);
      setClosing(String(s.data.closing_balance ?? ''));
    } catch (e) { fail(e); }
  }, [base, headers, fail]);

  useEffect(() => { load(); }, [load]);

  const act = async (fn, okTitle) => {
    setBusy(true);
    try {
      const r = await fn();
      if (okTitle) toast({ title: okTitle, description: r?.data?.message || r?.data?.warning });
      await load();
      onChanged?.();
    }
    catch (e) { fail(e); } finally { setBusy(false); }
  };
  const autoMatch = () => act(() => axios.post(`${base}/auto-match`, {}, { headers }), 'Pencocokan otomatis');
  const approve = async () => {
    const sm = session.summary || {};
    if (!sm.explained) {
      const ok = await confirmDialog({
        title: 'Tetap setujui sesi ini?',
        body: `Selisih ${fmt(sm.unexplained || 0)} belum terjelaskan (buku besar disesuaikan ${fmt(sm.adjusted_gl_balance || 0)} vs rekening koran ${fmt(sm.statement_closing || 0)}). Selisih akan dicatat pada ringkasan persetujuan.`,
        confirmLabel: 'Tetap setujui',
      });
      if (!ok) return;
      return act(() => axios.post(`${base}/approve`, { confirm_unexplained: true }, { headers }), 'Sesi disetujui');
    }
    return act(() => axios.post(`${base}/approve`, {}, { headers }), 'Sesi disetujui');
  };
  const saveClosing = () => act(() => axios.put(base, { closing_balance: parseFloat(closing) || 0 }, { headers }), 'Saldo akhir disimpan');
  const onMatch = (txn, g) => act(() => axios.post(`${base}/match`, { txn_id: txn.id, target_key: g.key }, { headers }), 'Dicocokkan');
  const onUnmatch = (txn) => act(() => axios.post(`${base}/unmatch`, { txn_id: txn.id }, { headers }), 'Tautan dilepas');
  const onAdjust = (txn, type) => act(() => axios.post(`${base}/transactions/${txn.id}/adjust`, { adjustment_type: type }, { headers }), 'Penyesuaian dijurnal');
  const onDelete = async (txn) => (await confirmDialog({ title: 'Hapus mutasi ini?', confirmLabel: 'Hapus', danger: true }))
    && act(() => axios.delete(`${base}/transactions/${txn.id}`, { headers }), 'Mutasi dihapus');
  const onLinkSettlement = () => act(() => Promise.resolve({}), 'Pencairan ditautkan');

  if (!session) {
    return (
      <DetailPanel title="Sesi rekonsiliasi" description="Memuat…" onClose={onBack} testId="recon-session-detail">
        <div className="flex justify-center py-8"><Loader2 className="w-6 h-6 animate-spin" /></div>
      </DetailPanel>
    );
  }
  const readOnly = session.status === 'approved';
  const shown = txns.filter(t => filter === 'all' ? true : filter === 'matched' ? t.is_matched : !t.is_matched);
  const matchedCount = txns.filter(t => t.is_matched).length;

  return (
    <DetailPanel
      testId="recon-session-detail"
      title={`${fmtPeriod(session.period)} · ${session.account_name}`}
      description={(
        <span className="inline-flex items-center gap-2 flex-wrap">
          <SessionStatusBadge status={session.status} />
          <span>Akun {session.gl_account_code} · {session.total_bank_txns} mutasi · {session.matched_count} cocok · {session.unmatched_count} belum</span>
        </span>
      )}
      onClose={onBack}
      actions={<>
        <Button size="icon" variant="outline" data-testid="recon-refresh" onClick={load} title="Muat ulang" aria-label="Muat ulang"><RefreshCw className="w-4 h-4" /></Button>
        {!readOnly && <>
          <Button variant="outline" data-testid="recon-import-toggle" onClick={() => setShowImport(v => !v)} aria-expanded={showImport}><Upload className="w-4 h-4" /> Impor mutasi</Button>
          <Button variant="outline" data-testid="recon-approve"
            onClick={approve} disabled={busy || session.unmatched_count > 0 || !session.total_bank_txns}
            title={session.unmatched_count > 0 ? 'Cocokkan semua mutasi dulu' : 'Setujui sesi rekonsiliasi'}>
            <CheckCircle2 className="w-4 h-4" /> Setujui
          </Button>
          <Button data-testid="recon-auto-match" onClick={autoMatch} disabled={busy}>
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />} Cocokkan otomatis
          </Button>
        </>}
      </>}
    >
      {!readOnly && (
        <div className="flex items-center gap-2 text-sm flex-wrap">
          <span className="text-muted-foreground">Saldo akhir rekening koran</span>
          <MoneyInput glass decimals={2} allowNegative data-testid="recon-closing-input" className="h-9 w-44" value={closing} onChange={e => setClosing(e.target.value)} />
          <Button size="sm" variant="outline" data-testid="recon-closing-save" onClick={saveClosing} disabled={busy}>Simpan</Button>
        </div>
      )}
      <ReconSummary summary={readOnly && session.approved_summary ? session.approved_summary : session.summary}
        approved={readOnly ? { at: session.approved_at, by: session.approved_by_name, withUnexplained: session.approved_with_unexplained } : null} />
      {showImport && !readOnly && <ImportPanel sessionId={sessionId} headers={headers} onDone={() => { setShowImport(false); load(); onChanged?.(); }} />}

      <div className="flex items-center gap-2 flex-wrap">
        <FilterChips value={section} onChange={setSection} testId="recon-tab" ariaLabel="Bagian sesi" hideWhenEmpty={false}
          options={[
            { key: 'bank', label: 'Mutasi bank', count: txns.length },
            { key: 'gl', label: 'Jurnal akun bank', count: session.gl_lines?.length || 0 },
            { key: 'internal', label: check?.issues?.length ? `Kas internal vs jurnal · ${check.issues.length} bermasalah` : 'Kas internal vs jurnal' },
          ]} />
        {section === 'bank' && txns.length > 0 && (
          <>
            <span className="w-px h-5 bg-[var(--glass-border)]" aria-hidden />
            <FilterChips value={filter} onChange={setFilter} testId="recon-filter" ariaLabel="Saring mutasi" hideWhenEmpty={false}
              options={[
                { key: 'all', label: 'Semua', count: txns.length },
                { key: 'unmatched', label: 'Belum cocok', count: txns.length - matchedCount },
                { key: 'matched', label: 'Cocok', count: matchedCount },
              ]} />
          </>
        )}
      </div>

      {section === 'bank' && (
        <div className="space-y-2">
          {shown.length === 0 && (
            <EmptyState icon={ArrowRightLeft} testId="recon-txn-empty"
              title={txns.length ? 'Tidak ada mutasi untuk penyaring ini' : 'Belum ada mutasi'}
              description={txns.length ? 'Pilih penyaring lain.' : 'Impor rekening koran (CSV) atau tambah mutasi manual lewat “Impor mutasi”.'} />
          )}
          {shown.map(t => (
            <BankTxnRow key={t.id} sessionId={sessionId} txn={t} headers={headers} readOnly={readOnly}
              onMatch={onMatch} onUnmatch={onUnmatch} onAdjust={onAdjust} onDelete={onDelete} onLinkSettlement={onLinkSettlement} />
          ))}
          {txns.length > 0 && (
            <p className="text-xs text-muted-foreground text-right tabular-nums">Total masuk {fmt(session.in_total || 0)} · keluar {fmt(session.out_total || 0)}</p>
          )}
        </div>
      )}
      {section === 'gl' && <GlLinesTable lines={session.gl_lines} glAccountCode={session.gl_account_code} />}
      {section === 'internal' && <InternalCheckPanel check={check} />}
    </DetailPanel>
  );
}

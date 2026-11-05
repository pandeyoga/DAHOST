import { useState, useEffect, useCallback, useRef } from 'react';
import { Download, Upload, Lock, CheckCircle2, AlertTriangle, RefreshCw, FileSpreadsheet } from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { toast } from 'sonner';
import { StatTile, EmptyState } from '../moduleAtoms';
import PageLayout from '../layout/PageLayout';
import { formatDateID } from '@/lib/format';
import { fmt, fmtCell, authHeaders, downloadXlsx } from './reportShared';

const tdN = 'text-right tabular-nums';

function PostedJournal({ status, onVoided, token, role }) {
  const je = status.journal;
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const canVoid = ['superadmin', 'owner'].includes((role || '').toLowerCase());
  const doVoid = async () => {
    if (!reason.trim()) { toast.error('Alasan wajib diisi'); return; }
    setBusy(true);
    try {
      const r = await fetch(`/api/rahaza/journals/${je.id}/void`, { method: 'POST', headers: { ...authHeaders(token), 'Content-Type': 'application/json' }, body: JSON.stringify({ reason, force: true }) });
      const j = await r.json();
      if (!r.ok) { toast.error(j.detail || 'Gagal membatalkan'); return; }
      toast.success(`Jurnal ${je.je_number} dibatalkan — saldo awal bisa diunggah ulang`);
      onVoided();
    } finally { setBusy(false); }
  };
  return (
    <GlassCard className="p-4 space-y-3" data-testid="ob-posted">
      <div>
        <p className="inline-flex items-center gap-2 text-[hsl(var(--success))] font-semibold"><Lock className="w-4 h-4" />Saldo awal sudah diposting dan terkunci</p>
        <p className="text-xs text-muted-foreground mt-1">
          Jurnal <span className="text-foreground" data-testid="ob-je-number">{je.je_number}</span> · tanggal {formatDateID(je.date)} · {status.lines.length} baris ·
          debit Rp {fmt(je.total_debit)} = kredit Rp {fmt(je.total_credit)}{je.source_ref ? ` · berkas ${je.source_ref}` : ''}
        </p>
      </div>
      <div className="overflow-auto max-h-[50vh] -mx-4">
        <table className="w-full">
          <thead className="sticky top-0 bg-[var(--card-surface)]">
            <tr><th className="text-left">Kode</th><th className="text-left">Akun</th><th className="text-right">Debit</th><th className="text-right">Kredit</th></tr>
          </thead>
          <tbody>
            {status.lines.map((l) => (
              <tr key={l.line_id} data-testid={`ob-line-${l.account_code}`}>
                <td className="whitespace-nowrap">{l.account_code}</td><td>{l.account_name}</td>
                <td className={tdN}>{fmtCell(l.debit)}</td><td className={tdN}>{fmtCell(l.credit)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {canVoid && (
        <div className="border-t border-[var(--glass-border)] pt-3 space-y-2">
          <p className="text-xs text-muted-foreground">Salah isi? Superadmin dapat membatalkan jurnal ini (pembatalan paksa, tercatat di jejak audit) lalu mengunggah ulang.</p>
          <div className="flex gap-2 flex-wrap">
            <GlassInput value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Alasan pembatalan (wajib)" className="h-9 w-80 max-w-full" data-testid="ob-void-reason" />
            <Button variant="outline" onClick={doVoid} disabled={busy} className="text-[hsl(var(--destructive))]" data-testid="ob-void-btn">Batalkan jurnal saldo awal</Button>
          </div>
        </div>
      )}
    </GlassCard>
  );
}

function PreviewTable({ preview }) {
  const errRows = preview.rows.filter((r) => r.error);
  return (
    <div className="space-y-3" data-testid="ob-preview">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatTile label="Baris terisi" value={preview.rows.length} testId="ob-kpi-rows" />
        <StatTile label="Total debit" value={fmt(preview.totals.debit)} testId="ob-kpi-debit" />
        <StatTile label="Total kredit" value={fmt(preview.totals.credit)} testId="ob-kpi-credit" />
        <StatTile label={preview.ok ? 'Siap diposting' : `${preview.errors.length} masalah`} value={preview.ok ? '✓' : '✗'} accent={preview.ok ? 'success' : 'danger'} testId="ob-kpi-status" />
      </div>
      {preview.errors.length > 0 && (
        <div className="bg-[hsl(var(--destructive)/0.08)] border border-[hsl(var(--destructive)/0.3)] rounded-[var(--radius-md)] px-4 py-3" data-testid="ob-errors">
          <p className="inline-flex items-center gap-2 text-[hsl(var(--destructive))] font-semibold text-sm mb-2"><AlertTriangle className="w-4 h-4" />Perbaiki dulu di Excel, lalu unggah lagi</p>
          <ul className="text-xs space-y-1 list-disc pl-5">{preview.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>
        </div>
      )}
      {preview.balancing && (
        <p className="text-xs text-[hsl(var(--warning))]" data-testid="ob-balancing">
          Selisih Rp {fmt(Math.max(preview.balancing.debit, preview.balancing.credit))} ditutup otomatis ke {preview.balancing.account_code} {preview.balancing.account_name} ({preview.balancing.debit ? 'debit' : 'kredit'}).
        </p>
      )}
      {preview.relations?.length > 0 && (
        <GlassCard className="p-0 overflow-hidden">
          <p className="px-4 pt-3 text-xs font-semibold text-muted-foreground">Rincian per relasi dibanding akun kontrol</p>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead><tr><th className="text-left">Sheet</th><th className="text-left">Baris → akun kontrol</th><th className="text-right">Total rincian</th><th className="text-right">Saldo akun kontrol</th><th className="text-left">Hasil</th></tr></thead>
              <tbody>
                {preview.relations.map((r) => (
                  <tr key={r.sheet} data-testid={`ob-rel-${r.sheet}`}>
                    <td className="whitespace-nowrap">{r.sheet}</td>
                    <td className="text-muted-foreground">{r.rows} baris → {r.control_account}</td>
                    <td className={tdN}>{fmt(r.detail_total)}</td>
                    <td className={tdN}>{fmt(r.control_balance)}</td>
                    <td className={r.match ? 'text-[hsl(var(--success))]' : 'text-[hsl(var(--destructive))]'}>{r.match ? (r.rows ? 'Cocok' : 'Kosong') : 'Tidak cocok'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </GlassCard>
      )}
      <GlassCard className="p-0 overflow-hidden">
        {preview.rows.length === 0 ? (
          <EmptyState icon={FileSpreadsheet} title="Semua saldo 0" description="Tidak ada yang akan diposting dari berkas ini." />
        ) : (
          <div className="overflow-auto max-h-[45vh]">
            <table className="w-full" data-testid="ob-preview-table">
              <thead className="sticky top-0 bg-[var(--card-surface)]">
                <tr><th className="text-left">Baris</th><th className="text-left">Kode</th><th className="text-left">Akun</th><th className="text-right">Debit</th><th className="text-right">Kredit</th><th className="text-left">Status</th></tr>
              </thead>
              <tbody>
                {preview.rows.map((r) => (
                  <tr key={r.row} className={r.error ? 'bg-[hsl(var(--destructive)/0.08)]' : ''} data-testid={`ob-row-${r.code}`}>
                    <td className="tabular-nums text-muted-foreground">{r.row}</td>
                    <td className="whitespace-nowrap">{r.code}</td>
                    <td>{r.name}</td>
                    <td className={tdN}>{fmtCell(r.debit)}</td><td className={tdN}>{fmtCell(r.credit)}</td>
                    <td className={r.error ? 'text-[hsl(var(--destructive))]' : 'text-[hsl(var(--success))]'}>{r.error || 'Siap'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
      {errRows.length > 0 && <p className="text-[11px] text-muted-foreground">{errRows.length} baris bermasalah ditandai merah.</p>}
    </div>
  );
}

/**
 * Saldo awal (menu Pengaturan Keuangan › Saldo awal).
 * 2026-11-05 (PANDUAN_UI G1/G3): cetakan PageLayout; satu tombol utama (Posting saldo awal) — dulu dua tombol
 * utama berdampingan; angka tanpa huruf mesin ketik; warna hanya token.
 */
export default function RahazaOpeningBalanceModule({ token, user }) {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [file, setFile] = useState(null);
  const [obDate, setObDate] = useState(`${new Date().getFullYear()}-01-01`);
  const [toRetained, setToRetained] = useState(false);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef(null);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch('/api/rahaza/finance/opening-balance/status', { headers: authHeaders(token) });
      if (r.ok) setStatus(await r.json());
    } finally { setLoading(false); }
  }, [token]);
  useEffect(() => { fetchStatus(); }, [fetchStatus]);

  const form = () => { const fd = new FormData(); fd.append('file', file); fd.append('balance_to_retained', toRetained ? 'true' : 'false'); return fd; };

  const doPreview = useCallback(async () => {
    if (!file) return;
    setBusy(true);
    try {
      const r = await fetch('/api/rahaza/finance/opening-balance/preview', { method: 'POST', headers: authHeaders(token), body: form() });
      const j = await r.json();
      if (!r.ok) { toast.error(typeof j.detail === 'string' ? j.detail : 'Gagal membaca berkas'); setPreview(null); return; }
      setPreview(j);
    } finally { setBusy(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file, toRetained, token]);
  useEffect(() => { doPreview(); }, [doPreview]);

  const doApply = async () => {
    if (!preview?.ok) return;
    setBusy(true);
    try {
      const fd = form(); fd.append('ob_date', obDate);
      const r = await fetch('/api/rahaza/finance/opening-balance/apply', { method: 'POST', headers: authHeaders(token), body: fd });
      const j = await r.json();
      if (!r.ok) { toast.error(typeof j.detail === 'string' ? j.detail : j.detail?.message || 'Posting gagal'); return; }
      toast.success(`Saldo awal diposting: ${j.journal.je_number}`);
      setFile(null); setPreview(null); if (inputRef.current) inputRef.current.value = '';
      fetchStatus();
    } finally { setBusy(false); }
  };

  const dlTemplate = () => downloadXlsx('/api/rahaza/finance/opening-balance/template', token, 'SALDO_AWAL_GOLIVE.xlsx').catch((e) => toast.error(`Unduh gagal: ${e.message}`));

  return (
    <PageLayout
      testId="ob-page"
      title="Saldo awal"
      subtitle="Pindahkan neraca penutup pembukuan lama ke sistem sebagai satu jurnal pembuka yang terkunci."
      tools={<Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={fetchStatus} data-testid="ob-refresh"><RefreshCw className="w-4 h-4" /></Button>}
    >
      {loading ? <Skeleton className="h-40 rounded-xl" /> : status?.journal ? (
        <PostedJournal status={status} token={token} role={user?.role} onVoided={fetchStatus} />
      ) : (
        <>
          <div className="grid md:grid-cols-3 gap-4">
            <GlassCard className="p-4 space-y-3" data-testid="ob-step-1">
              <p className="text-xs text-muted-foreground font-semibold">Langkah 1</p>
              <h3 className="font-semibold text-sm">Unduh template</h3>
              <p className="text-xs text-muted-foreground">{status?.balance_accounts || 0} akun neraca aktif + sheet rincian {status?.relation_sheets?.map((s) => s.control_account).join(', ')}. Isi debit/kredit per akun dan rincian piutang/hutang per relasi.</p>
              <Button variant="outline" onClick={dlTemplate} className="w-full" data-testid="ob-download-template"><Download className="w-4 h-4" />Unduh template Excel</Button>
            </GlassCard>
            <GlassCard className="p-4 space-y-3" data-testid="ob-step-2">
              <p className="text-xs text-muted-foreground font-semibold">Langkah 2</p>
              <h3 className="font-semibold text-sm">Unggah berkas terisi</h3>
              <input ref={inputRef} type="file" accept=".xlsx" onChange={(e) => setFile(e.target.files?.[0] || null)} className="block w-full text-xs text-muted-foreground file:mr-3 file:rounded-md file:border-0 file:bg-primary/20 file:px-3 file:py-1.5 file:text-xs file:text-primary" data-testid="ob-file-input" />
              <label className="inline-flex items-center gap-2 text-xs text-foreground/80">
                <input type="checkbox" checked={toRetained} onChange={(e) => setToRetained(e.target.checked)} data-testid="ob-to-retained" />
                Tutup selisih debit ≠ kredit ke 3-2000 Laba Ditahan
              </label>
            </GlassCard>
            <GlassCard className="p-4 space-y-3" data-testid="ob-step-3">
              <p className="text-xs text-muted-foreground font-semibold">Langkah 3</p>
              <h3 className="font-semibold text-sm">Posting jurnal pembuka</h3>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">Per tanggal</span>
                <GlassInput type="date" value={obDate} onChange={(e) => setObDate(e.target.value)} className="h-9 w-40" data-testid="ob-date" />
              </div>
              <Button onClick={doApply} disabled={!preview?.ok || !preview.lines?.length || busy} className="w-full" data-testid="ob-apply">
                {preview?.ok ? <CheckCircle2 className="w-4 h-4" /> : <Upload className="w-4 h-4" />}Posting saldo awal
              </Button>
            </GlassCard>
          </div>
          {busy && !preview && <Skeleton className="h-24 rounded-xl" />}
          {preview ? <PreviewTable preview={preview} /> : (
            <GlassCard className="p-0">
              <EmptyState icon={FileSpreadsheet} testId="ob-empty" title="Belum ada berkas"
                description="Pratinjau muncul otomatis setelah berkas dipilih. Tidak ada yang tersimpan sebelum tombol Posting ditekan." />
            </GlassCard>
          )}
        </>
      )}
    </PageLayout>
  );
}

import { useState, useEffect, useCallback, useRef } from 'react';
import { Download, Upload, Lock, CheckCircle2, AlertTriangle, RefreshCw, FileSpreadsheet } from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { toast } from 'sonner';
import { StatTile, EmptyState, Notice } from '../moduleAtoms';
import { Checkbox } from '@/components/ui/checkbox';
import DatePicker from '@/components/ui/date-picker';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PageLayout from '../layout/PageLayout';
import { formatDateID } from '@/lib/format';
import { fmt, fmtCell, authHeaders, downloadXlsx } from './reportShared';

const tdN = 'text-right tabular-nums';
const KOLOM_BARIS = [
  { label: 'Kode', nilai: (l) => l.account_code || l.code },
  { label: 'Akun', nilai: (l) => l.account_name || l.name },
  { label: 'Debit', nilai: (l) => Number(l.debit) || 0 },
  { label: 'Kredit', nilai: (l) => Number(l.credit) || 0 },
];

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
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="inline-flex items-center gap-2 text-[hsl(var(--success-text))] font-semibold"><Lock className="w-4 h-4" />Saldo awal sudah diposting dan terkunci</p>
          <TombolUnduh namaBerkas={`saldo-awal-${je.je_number}`} namaLembar="Saldo awal" baris={status.lines} kolom={KOLOM_BARIS} testId="ob-posted-unduh" />
        </div>
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
            <GlassInput value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Alasan pembatalan (wajib)" className="h-9 w-full sm:w-80" data-testid="ob-void-reason" />
            <Button variant="destructive" onClick={doVoid} disabled={busy} data-testid="ob-void-btn">Batalkan jurnal saldo awal</Button>
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
        <StatTile label="Baris terisi" value={preview.rows.length} testId="ob-kpi-rows" sub="Baris berisi angka di berkas" />
        <StatTile label="Total debit" value={fmt(preview.totals.debit)} testId="ob-kpi-debit" sub="Jumlah kolom Debit" />
        <StatTile label="Total kredit" value={fmt(preview.totals.credit)} testId="ob-kpi-credit" sub="Jumlah kolom Kredit" />
        <StatTile label="Status berkas" value={preview.ok ? 'Siap diposting' : `${preview.errors.length} masalah`} accent={preview.ok ? 'success' : 'danger'} testId="ob-kpi-status" sub={preview.ok ? 'Debit = kredit, semua akun dikenali' : 'Perbaiki di Excel lalu unggah ulang'} />
      </div>
      {preview.errors.length > 0 && (
        <Notice tone="danger" icon={AlertTriangle} testId="ob-errors" title="Perbaiki dulu di Excel, lalu unggah lagi">
          <ul className="text-sm space-y-1 list-disc pl-5 text-foreground">{preview.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>
        </Notice>
      )}
      {preview.balancing && (
        <p className="text-sm text-[hsl(var(--warning-text))]" data-testid="ob-balancing">
          Selisih Rp {fmt(Math.max(preview.balancing.debit, preview.balancing.credit))} ditutup otomatis ke {preview.balancing.account_code} {preview.balancing.account_name} ({preview.balancing.debit ? 'debit' : 'kredit'}).
        </p>
      )}
      {preview.relations?.length > 0 && (
        <GlassCard className="p-0 overflow-hidden">
          <p className="px-4 pt-3 text-sm font-semibold text-foreground">Rincian per relasi dibanding akun kontrol</p>
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
                    <td className={r.match ? 'text-[hsl(var(--success-text))]' : 'text-[hsl(var(--danger-text))]'}>{r.match ? (r.rows ? 'Cocok' : 'Kosong') : 'Tidak cocok'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </GlassCard>
      )}
      <GlassCard className="p-0 overflow-hidden">
        {preview.rows.length > 0 && (
          <div className="flex items-center justify-between gap-2 px-4 pt-3 pb-2">
            <p className="text-sm font-semibold text-foreground">Pratinjau baris saldo awal</p>
            <TombolUnduh namaBerkas="pratinjau-saldo-awal" namaLembar="Pratinjau" baris={preview.rows} testId="ob-preview-unduh"
              kolom={[{ label: 'Baris', nilai: (r) => r.row }, ...KOLOM_BARIS, { label: 'Status', nilai: (r) => r.error || 'Siap' }]} />
          </div>
        )}
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
                    <td className={r.error ? 'text-[hsl(var(--danger-text))]' : 'text-[hsl(var(--success-text))]'}>{r.error || 'Siap'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
      {errRows.length > 0 && <p className="text-xs text-muted-foreground">{errRows.length} baris bermasalah ditandai merah.</p>}
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
              <p className="text-xs text-muted-foreground font-medium">Langkah 1</p>
              <p className="font-semibold text-base">Unduh format isian</p>
              <p className="text-xs text-muted-foreground">{status?.balance_accounts || 0} akun neraca aktif + sheet rincian {status?.relation_sheets?.map((s) => s.control_account).join(', ')}. Isi debit/kredit per akun dan rincian piutang/hutang per relasi.</p>
              <Button variant="outline" onClick={dlTemplate} className="w-full" data-testid="ob-download-template"><Download className="w-4 h-4" />Unduh format isian Excel</Button>
            </GlassCard>
            <GlassCard className="p-4 space-y-3" data-testid="ob-step-2">
              <p className="text-xs text-muted-foreground font-medium">Langkah 2</p>
              <p className="font-semibold text-base">Unggah berkas terisi</p>
              <input ref={inputRef} type="file" accept=".xlsx" onChange={(e) => setFile(e.target.files?.[0] || null)} className="hidden" data-testid="ob-file-input" />
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="outline" onClick={() => inputRef.current?.click()} data-testid="ob-pick-file">Pilih berkas .xlsx</Button>
                <span className="text-sm text-muted-foreground min-w-0 truncate">{file ? file.name : 'Belum ada berkas'}</span>
              </div>
              <label className="inline-flex items-center gap-2 text-sm text-foreground/80">
                <Checkbox checked={toRetained} onCheckedChange={(v) => setToRetained(!!v)} data-testid="ob-to-retained" />
                Tutup selisih debit ≠ kredit ke 3-2000 Laba Ditahan
              </label>
            </GlassCard>
            <GlassCard className="p-4 space-y-3" data-testid="ob-step-3">
              <p className="text-xs text-muted-foreground font-medium">Langkah 3</p>
              <p className="font-semibold text-base">Posting jurnal pembuka</p>
              <div className="flex items-center gap-2">
                <span className="text-sm text-muted-foreground">Per tanggal</span>
                <div className="w-44"><DatePicker value={obDate} onChange={(v) => v && setObDate(v)} bolehKosong={false} testId="ob-date" /></div>
              </div>
              <Button variant="success" onClick={doApply} disabled={!preview?.ok || !preview.lines?.length || busy} className="w-full" data-testid="ob-apply">
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

/**
 * RahazaJournalImportModule — Impor pencatatan/penjurnalan dari Excel.
 * Owner 2026-09-24: "data finance tidak bisa sepenuhnya detail dimasukkan ke sistem —
 * butuh format excel pencatatan yang bisa di-import". Template: MUTASI_KAS_BANK & JURNAL_UMUM.
 *
 * 2026-11-05 (PANDUAN_UI G1/G3/G5/G8): cetakan PageLayout; satu tombol utama (Pratinjau → Posting setelah
 * pratinjau lolos; dulu dua tombol utama, satu berwarna hijau mentah); kartu dari GlassCard; warna hanya token.
 */
import { useState } from 'react';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { Download, Upload, CheckCircle2, AlertTriangle, FileSpreadsheet } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import { toast } from 'sonner';
import { StatTile, EmptyState, Notice } from '../moduleAtoms';
import PageLayout from '../layout/PageLayout';
import { formatDateID } from '@/lib/format';
import { fmt, authHeaders, downloadXlsx } from './reportShared';

const API = '/api/rahaza/finance/journal-import';

export default function RahazaJournalImportModule({ token }) {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  const send = async (path) => {
    const fd = new FormData(); fd.append('file', file);
    const r = await fetch(`${API}/${path}`, { method: 'POST', headers: authHeaders(token), body: fd });
    const d = await r.json();
    if (!r.ok) throw new Error(d?.detail?.message || d?.detail || `HTTP ${r.status}`);
    return d;
  };

  const doPreview = async () => {
    if (!file) return toast.error('Pilih berkas .xlsx dulu');
    setBusy(true); setResult(null);
    try { setPreview(await send('preview')); } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };
  const doApply = async () => {
    if (!preview?.ok || !preview.journals?.length) return;
    const ok = await confirmDialog({
      title: `Posting ${preview.journals.length} jurnal senilai Rp ${fmt(preview.totals.amount)}?`,
      body: 'Jurnal langsung masuk buku besar.', confirmLabel: 'Posting',
    });
    if (!ok) return;
    setBusy(true);
    try {
      const d = await send('apply'); setResult(d);
      d.failed_count ? toast.warning(`${d.posted_count} terposting, ${d.failed_count} gagal`) : toast.success(`${d.posted_count} jurnal terposting`);
      setPreview(null); setFile(null);
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };

  const canApply = !!(preview?.ok && preview?.journals?.length);

  return (
    <PageLayout
      testId="journal-import-module"
      title="Impor Jurnal (Excel)"
      subtitle="Catat mutasi kas/bank & jurnal umum di Excel, unggah, pratinjau, lalu posting."
      actions={<Button variant="outline" data-testid="journal-import-template"
        onClick={() => downloadXlsx(`${API}/template`, token, 'IMPOR_JURNAL.xlsx').catch(e => toast.error(e.message))}>
        <Download className="w-4 h-4" /> Unduh template</Button>}
    >
      <GlassCard className="p-4 space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <FileSpreadsheet className="w-5 h-5 text-muted-foreground" />
          <input type="file" accept=".xlsx" data-testid="journal-import-file" className="text-sm" aria-label="Berkas Excel"
            onChange={e => { setFile(e.target.files?.[0] || null); setPreview(null); setResult(null); }} />
          <Button variant={canApply ? 'outline' : 'default'} onClick={doPreview} disabled={!file || busy} data-testid="journal-import-preview"><Upload className="w-4 h-4" /> Pratinjau</Button>
          <Button variant={canApply ? 'default' : 'outline'} onClick={doApply} disabled={!canApply || busy} data-testid="journal-import-apply"><CheckCircle2 className="w-4 h-4" /> Posting</Button>
        </div>
        <p className="text-xs text-muted-foreground">Berkas yang sama diunggah dua kali → baris yang sudah masuk dilewati.</p>
      </GlassCard>

      {preview && (
        <div className="space-y-4" data-testid="journal-import-result">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatTile label="Jurnal siap posting" value={preview.totals.journals} />
            <StatTile label="Total nilai" value={`Rp ${fmt(preview.totals.amount)}`} />
            <StatTile label="Sudah pernah diimpor (dilewati)" value={preview.skipped_existing} />
            <StatTile label="Kesalahan" value={preview.errors.length} accent={preview.errors.length ? 'danger' : 'default'} />
          </div>
          {preview.errors.length > 0 && (
            <Notice tone="danger" icon={AlertTriangle} testId="journal-import-errors" className="text-xs"
              title="Perbaiki dulu di Excel, lalu unggah ulang:">
              <div className="space-y-1">{preview.errors.map((e, i) => <div key={i}>• {e}</div>)}</div>
            </Notice>
          )}
          <GlassCard className="p-0 overflow-hidden">
            {preview.journals.length === 0 ? (
              <EmptyState icon={FileSpreadsheet} title="Tidak ada jurnal baru di berkas ini"
                description="Semua baris sudah pernah diimpor atau berkas masih kosong." />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead><tr>
                    <th className="text-left px-3 py-2">Lembar / baris</th><th className="text-left px-3 py-2">Tanggal</th>
                    <th className="text-left px-3 py-2">Keterangan</th><th className="text-left px-3 py-2">Baris jurnal</th>
                    <th className="text-right px-3 py-2">Nilai</th></tr></thead>
                  <tbody>
                    {preview.journals.map(j => (
                      <tr key={j.key} className="border-t border-border/60" data-testid={`journal-import-row-${j.row}`}>
                        <td className="px-3 py-1.5 whitespace-nowrap">{j.sheet === 'MUTASI_KAS_BANK' ? 'Mutasi' : 'Umum'} #{j.row}{j.no_jurnal ? ` · ${j.no_jurnal}` : ''}</td>
                        <td className="px-3 py-1.5 whitespace-nowrap">{formatDateID(j.date)}</td>
                        <td className="px-3 py-1.5">{j.memo}{j.reference ? <span className="text-muted-foreground"> [{j.reference}]</span> : null}</td>
                        <td className="px-3 py-1.5 text-[11px]">
                          {j.lines.map((l, i) => (
                            <div key={i}>
                              <span className="text-muted-foreground">{l.debit ? 'Debit' : 'Kredit'}</span> {l.account_code} {l.account_name} <span className="tabular-nums whitespace-nowrap">{fmt(l.debit || l.credit)}</span>
                            </div>
                          ))}
                        </td>
                        <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap font-semibold">{fmt(j.total)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </GlassCard>
        </div>
      )}

      {result && (
        <Notice tone="success" icon={CheckCircle2} testId="journal-import-posted" className="text-xs"
          title={`${result.posted_count} jurnal terposting${result.skipped_existing ? ` · ${result.skipped_existing} dilewati (sudah ada)` : ''}`}>
          <div className="space-y-0.5">
            {result.posted?.map(p => <div key={p.je_number}>{p.je_number} · {formatDateID(p.date)} · {p.memo} · <span className="tabular-nums">Rp {fmt(p.total)}</span></div>)}
            {result.failed?.map((f, i) => <div key={i} className="text-[hsl(var(--destructive))]">✗ {f.sheet} baris {f.row}: {f.error}</div>)}
          </div>
        </Notice>
      )}
    </PageLayout>
  );
}

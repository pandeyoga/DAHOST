/**
 * RahazaJournalImportModule — Impor pencatatan/penjurnalan dari Excel.
 * Owner 2026-09-24: "data finance tidak bisa sepenuhnya detail dimasukkan ke sistem —
 * butuh format excel pencatatan yang bisa di-import". Template: MUTASI_KAS_BANK & JURNAL_UMUM.
 */
import { useState } from 'react';
import { Download, Upload, CheckCircle2, AlertTriangle, FileSpreadsheet } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import { PageHeader, StatTile } from '../moduleAtoms';
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
    if (!window.confirm(`Posting ${preview.journals.length} jurnal senilai Rp ${fmt(preview.totals.amount)}?`)) return;
    setBusy(true);
    try {
      const d = await send('apply'); setResult(d);
      d.failed_count ? toast.warning(`${d.posted_count} terposting, ${d.failed_count} gagal`) : toast.success(`${d.posted_count} jurnal terposting`);
      setPreview(null); setFile(null);
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };

  return (
    <div className="space-y-4" data-testid="journal-import-module">
      <PageHeader eyebrow="Akuntansi" title="Impor Jurnal (Excel)"
        subtitle="Catat mutasi kas/bank & jurnal umum di Excel, unggah, pratinjau, lalu posting. Berkas yang sama diunggah dua kali → baris yang sudah masuk dilewati."
        actions={<Button variant="outline" data-testid="journal-import-template"
          onClick={() => downloadXlsx(`${API}/template`, token, 'IMPOR_JURNAL.xlsx').catch(e => toast.error(e.message))}>
          <Download className="w-4 h-4 mr-1" /> Unduh Template</Button>} />

      <div className="rounded-xl border border-border bg-card p-4 flex flex-wrap items-center gap-3">
        <FileSpreadsheet className="w-5 h-5 text-emerald-600" />
        <input type="file" accept=".xlsx" data-testid="journal-import-file" className="text-sm"
          onChange={e => { setFile(e.target.files?.[0] || null); setPreview(null); setResult(null); }} />
        <Button onClick={doPreview} disabled={!file || busy} data-testid="journal-import-preview"><Upload className="w-4 h-4 mr-1" /> Pratinjau</Button>
        <Button onClick={doApply} disabled={!preview?.ok || !preview?.journals?.length || busy} data-testid="journal-import-apply"
          className="bg-emerald-600 hover:bg-emerald-700 text-white"><CheckCircle2 className="w-4 h-4 mr-1" /> Posting</Button>
      </div>

      {preview && (
        <div className="space-y-3" data-testid="journal-import-result">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatTile label="Jurnal siap posting" value={preview.totals.journals} />
            <StatTile label="Total nilai" value={`Rp ${fmt(preview.totals.amount)}`} />
            <StatTile label="Sudah pernah diimpor (dilewati)" value={preview.skipped_existing} />
            <StatTile label="Kesalahan" value={preview.errors.length} accent={preview.errors.length ? 'danger' : 'success'} />
          </div>
          {preview.errors.length > 0 && (
            <div className="rounded-lg border border-red-300 bg-red-50 dark:bg-red-500/10 p-3 text-xs text-red-700 space-y-1" data-testid="journal-import-errors">
              <div className="font-semibold flex items-center gap-1"><AlertTriangle className="w-3.5 h-3.5" /> Perbaiki dulu di Excel, lalu unggah ulang:</div>
              {preview.errors.map((e, i) => <div key={i}>• {e}</div>)}
            </div>
          )}
          <div className="rounded-xl border border-border overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-muted/40"><tr>
                <th className="text-left px-3 py-2">Sheet/Baris</th><th className="text-left px-3 py-2">Tanggal</th>
                <th className="text-left px-3 py-2">Keterangan</th><th className="text-left px-3 py-2">Baris jurnal</th>
                <th className="text-right px-3 py-2">Nilai</th></tr></thead>
              <tbody>
                {preview.journals.map(j => (
                  <tr key={j.key} className="border-t border-border/60" data-testid={`journal-import-row-${j.row}`}>
                    <td className="px-3 py-1.5 font-mono">{j.sheet === 'MUTASI_KAS_BANK' ? 'Mutasi' : 'Umum'} #{j.row}{j.no_jurnal ? ` · ${j.no_jurnal}` : ''}</td>
                    <td className="px-3 py-1.5">{j.date}</td>
                    <td className="px-3 py-1.5">{j.memo}{j.reference ? <span className="text-muted-foreground"> [{j.reference}]</span> : null}</td>
                    <td className="px-3 py-1.5 font-mono text-[11px]">
                      {j.lines.map((l, i) => <div key={i}>{l.debit ? 'D' : 'K'} {l.account_code} {l.account_name} {fmt(l.debit || l.credit)}</div>)}
                    </td>
                    <td className="px-3 py-1.5 text-right font-semibold">{fmt(j.total)}</td>
                  </tr>
                ))}
                {preview.journals.length === 0 && <tr><td colSpan={5} className="px-3 py-4 text-center text-muted-foreground">Tidak ada jurnal baru di berkas ini.</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {result && (
        <div className="rounded-lg border border-emerald-300 bg-emerald-50 dark:bg-emerald-500/10 p-3 text-xs" data-testid="journal-import-posted">
          <div className="font-semibold text-emerald-800">{result.posted_count} jurnal terposting{result.skipped_existing ? ` · ${result.skipped_existing} dilewati (sudah ada)` : ''}</div>
          {result.posted?.map(p => <div key={p.je_number}>{p.je_number} · {p.date} · {p.memo} · Rp {fmt(p.total)}</div>)}
          {result.failed?.map((f, i) => <div key={i} className="text-red-700">✗ {f.sheet} baris {f.row}: {f.error}</div>)}
        </div>
      )}
    </div>
  );
}

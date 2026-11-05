/**
 * ScanResult — SATU bentuk umpan balik hasil scan, selalu TEPAT DI BAWAH kotak scan (2026-11-06).
 *
 * Keluhan audit layar scan Gudang: pesan hasil scan berbeda-beda letaknya — di Opname muncul di atas
 * halaman (di HP berada di luar layar, petugas tidak tahu scannya ditolak), di layar lain tidak ada sama
 * sekali. Komponen ini dipakai lewat prop `result` milik `UniversalScanner variant="inline"`, atau
 * langsung di bawah kotak scan buatan layar.
 *
 *   <ScanResult tone="ok" title="Tercatat: KM-001 · 2 pcs" detail="Kemeja Linen M" />
 *   tone: 'ok' (hijau) | 'error' (merah, dibacakan segera) | 'dup' (kuning, kode sama) | 'info'
 */
import { CheckCircle2, XCircle, AlertTriangle, Info } from 'lucide-react';
import { cn } from '@/lib/utils';

const TONE = {
  ok: { icon: CheckCircle2, cls: 'border-[hsl(var(--success)/0.4)] bg-[hsl(var(--success)/0.1)] text-[hsl(var(--success))]' },
  error: { icon: XCircle, cls: 'border-[hsl(var(--destructive)/0.4)] bg-[hsl(var(--destructive)/0.1)] text-[hsl(var(--destructive))]' },
  dup: { icon: AlertTriangle, cls: 'border-[hsl(var(--warning)/0.4)] bg-[hsl(var(--warning)/0.1)] text-[hsl(var(--warning))]' },
  info: { icon: Info, cls: 'border-[var(--glass-border)] bg-[var(--card-surface)] text-foreground' },
};

export default function ScanResult({ tone = 'ok', title, detail, className, testId = 'scan-result' }) {
  if (!title) return null;
  const t = TONE[tone] || TONE.info;
  const Icon = t.icon;
  return (
    <div
      role={tone === 'error' ? 'alert' : 'status'}
      aria-live={tone === 'error' ? 'assertive' : 'polite'}
      data-testid={testId}
      data-tone={tone}
      className={cn('mt-2 flex items-start gap-2 rounded-[var(--radius-md)] border px-3 py-2', t.cls, className)}
    >
      <Icon className="w-5 h-5 mt-0.5 shrink-0" aria-hidden="true" />
      <div className="min-w-0">
        <p className="text-sm font-semibold break-words">{title}</p>
        {detail && <p className="text-xs text-foreground/80 break-words">{detail}</p>}
      </div>
    </div>
  );
}

/** Ubah {tone:'green'|'red'|'amber', text} lama atau string galat menjadi props ScanResult. */
export function toScanResult(x) {
  if (!x) return null;
  if (typeof x === 'string') return { tone: 'error', title: x };
  const map = { green: 'ok', success: 'ok', ok: 'ok', red: 'error', error: 'error', danger: 'error',
                amber: 'dup', warning: 'dup', dup: 'dup', info: 'info' };
  return { tone: map[x.tone || x.type] || 'info', title: x.title || x.text || x.message, detail: x.detail };
}

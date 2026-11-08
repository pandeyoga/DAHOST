/**
 * DetailPopup — standar popup DETAIL (Standar UI/UX v2, keputusan owner 8 Nov 2026 #1: detail = popup).
 * Lebar 56rem; kepala berisi judul + status + tombol aksi; isi bergulir; di HP penuh layar.
 * Tutup: × atau Esc.
 */
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { cn } from '@/lib/utils';

export default function DetailPopup({ open, onClose, judul, keterangan, status, aksi, children, testId = 'detail-popup' }) {
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose?.(); }}>
      <DialogContent
        data-testid={testId}
        className={cn(
          'flex max-h-[90vh] flex-col gap-0 p-0 sm:max-w-4xl',
          'max-sm:left-0 max-sm:top-0 max-sm:h-[100dvh] max-sm:max-h-none max-sm:max-w-none',
          'max-sm:translate-x-0 max-sm:translate-y-0 max-sm:rounded-none',
        )}>
        <div className="flex flex-col gap-3 border-b border-[var(--glass-border)] px-5 py-4 pr-12 sm:flex-row sm:items-start">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <DialogTitle className="text-base font-semibold">{judul}</DialogTitle>
              {status}
            </div>
            {keterangan && <DialogDescription className="mt-1 text-sm text-muted-foreground">{keterangan}</DialogDescription>}
          </div>
          {aksi && <div className="flex flex-wrap items-center gap-2 sm:justify-end">{aksi}</div>}
        </div>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4" data-testid={`${testId}-isi`}>
          {children}
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** Baris "label : nilai" di dalam popup detail (dua kolom di layar lebar). */
export function BarisDetail({ label, children }) {
  return (
    <div className="grid grid-cols-1 gap-0.5 py-1.5 sm:grid-cols-[10rem_1fr] sm:gap-3">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-sm text-foreground">{children}</dd>
    </div>
  );
}

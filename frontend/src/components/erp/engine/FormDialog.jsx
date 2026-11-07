/**
 * FormDialog — popup formulir PENDEK (PANDUAN_UI G13: popup hanya untuk isian pendek & konfirmasi).
 *
 * Tahap 9: pengganti `engine/Modal` di layar proses (Terima & QC, Perbaikan, Kirim hasil, Bahan,
 * Tutup PO) — dibangun di atas `ui/dialog` (Radix: fokus terkunci, Esc menutup, label aksesibel).
 * Daftar, tabel, dan detail TIDAK memakai komponen ini; itu dibuka di halaman (DetailPanel/RowDetail).
 *
 *   <FormDialog open={!!x} onClose={() => setX(null)} title="Koreksi hasil QC" testId="koreksi-dialog"
 *     footer={<><Button variant="outline" onClick={…}>Batal</Button><Button onClick={…}>Simpan</Button></>}>
 *     …isian…
 *   </FormDialog>
 */
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { cn } from '@/lib/utils';

export default function FormDialog({ open = true, onClose, title, description, children, footer, testId, wide = false }) {
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose?.(); }}>
      {/* Standar UI/UX v2: tata letak sama dengan FormPopup (kepala · isi bergulir · kaki), layar penuh di HP */}
      <DialogContent data-testid={testId}
        className={cn('flex max-h-[90vh] flex-col gap-0 p-0', wide ? 'sm:max-w-3xl' : 'sm:max-w-lg',
          'max-sm:left-0 max-sm:top-0 max-sm:h-[100dvh] max-sm:max-h-none max-sm:max-w-none',
          'max-sm:translate-x-0 max-sm:translate-y-0 max-sm:rounded-none')}>
        <DialogHeader className="border-b border-[var(--glass-border)] px-5 py-4 pr-12 text-left">
          <DialogTitle className="text-base font-semibold">{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4 text-sm">{children}</div>
        {footer && (
          <DialogFooter className="gap-2 border-t border-[var(--glass-border)] px-5 py-3">{footer}</DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}

/** Label + isian bertumpuk (satu gaya untuk semua formulir pendek di layar proses). */
export function Field({ label, hint, children, className }) {
  return (
    <label className={cn('block', className)}>
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <div className="mt-1">{children}</div>
      {hint && <span className="mt-1 block text-xs text-muted-foreground">{hint}</span>}
    </label>
  );
}

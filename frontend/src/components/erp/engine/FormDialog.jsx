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
      <DialogContent data-testid={testId}
        className={cn('max-h-[90vh] overflow-y-auto', wide ? 'sm:max-w-2xl' : 'sm:max-w-lg')}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        <div className="space-y-3 text-sm">{children}</div>
        {footer && <DialogFooter className="gap-2">{footer}</DialogFooter>}
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
      {hint && <span className="mt-1 block text-[11px] text-muted-foreground">{hint}</span>}
    </label>
  );
}

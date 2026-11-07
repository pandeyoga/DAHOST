/**
 * ConfirmDialog (engine) — Standar UI/UX v2 (8 Nov 2026): tampil sama dengan `confirmDialog()` (ui/confirm-dialog):
 * dialog aplikasi Radix (Esc/Batal menutup), tombol Hapus merah, tombol Lanjutkan utama.
 * API lama tetap: <ConfirmDialog title message onConfirm onCancel type="danger|warning" confirmLabel? />
 * Layar baru memakai `await confirmDialog({...})` langsung.
 */
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { buttonVariants } from '@/components/ui/button';

export default function ConfirmDialog({ title, message, onConfirm, onCancel, type = 'danger', confirmLabel }) {
  const danger = type !== 'warning';
  return (
    <AlertDialog open onOpenChange={(o) => { if (!o) onCancel?.(); }}>
      <AlertDialogContent data-testid="engine-confirm-dialog">
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          {message && <AlertDialogDescription>{message}</AlertDialogDescription>}
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={() => onCancel?.()}>Batal</AlertDialogCancel>
          <AlertDialogAction onClick={() => onConfirm?.()}
            className={danger ? buttonVariants({ variant: 'destructive' }) : undefined}>
            {confirmLabel || (danger ? 'Hapus' : 'Lanjutkan')}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

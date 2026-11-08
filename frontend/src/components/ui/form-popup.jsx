/**
 * FormPopup — standar popup FORM (Standar UI/UX v2, keputusan owner 8 Nov 2026 #2: form SELALU popup).
 *
 * Dua ukuran yang konsisten:
 *   ukuran="pendek"  ± ≤ 8 isian   → lebar 32rem
 *   ukuran="panjang" banyak isian  → lebar 48rem, isi bergulir, kepala & kaki tetap terlihat
 * Di HP (< 640 px) keduanya penuh layar. Tutup: × , Esc, atau Batal.
 * Kaki: pesan galat (kiri) · Batal (garis) · Simpan (hijau, K3). Enter di isian = Simpan.
 * Form penolakan/penghapusan: `warnaSimpan="destructive"` (tombol simpan merah, mis. "Tolak").
 */
import { Loader2 } from 'lucide-react';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

const LEBAR = { pendek: 'sm:max-w-lg', panjang: 'sm:max-w-3xl' };

export default function FormPopup({
  open, onClose, judul, keterangan, ukuran = 'pendek', children, onSimpan, labelSimpan = 'Simpan',
  menyimpan = false, galat, bisaSimpan = true, aksiKiri, testId = 'form-popup', warnaSimpan = 'success',
  testIdSimpan, testIdBatal, // opsional: pertahankan penanda lama yang dipakai tes
}) {
  const kirim = (e) => {
    e.preventDefault();
    e.stopPropagation(); // popup di portal: submit tidak merambat ke <form> induk di halaman
    if (!menyimpan && bisaSimpan && onSimpan) onSimpan();
  };
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o && !menyimpan) onClose?.(); }}>
      <DialogContent
        data-testid={testId}
        className={cn(
          'flex max-h-[90vh] flex-col gap-0 p-0',
          LEBAR[ukuran] || LEBAR.pendek,
          'max-sm:left-0 max-sm:top-0 max-sm:h-[100dvh] max-sm:max-h-none max-sm:max-w-none',
          'max-sm:translate-x-0 max-sm:translate-y-0 max-sm:rounded-none',
        )}>
        <form onSubmit={kirim} className="flex min-h-0 flex-1 flex-col">
          <div className="border-b border-[var(--glass-border)] px-5 py-4 pr-12">
            <DialogTitle className="text-base font-semibold">{judul}</DialogTitle>
            {keterangan && <DialogDescription className="mt-1 text-sm text-muted-foreground">{keterangan}</DialogDescription>}
          </div>
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4" data-testid={`${testId}-isi`}>
            {children}
          </div>
          <div className="flex flex-wrap items-center gap-2 border-t border-[var(--glass-border)] px-5 py-3">
            <div className="min-w-0 flex-1 text-sm text-[hsl(var(--danger-text))]" role="alert" data-testid={`${testId}-galat`}>
              {galat || null}
            </div>
            {aksiKiri}
            <Button type="button" variant="outline" onClick={onClose} disabled={menyimpan}
              data-testid={testIdBatal || `${testId}-batal`}>Batal</Button>
            <Button type="submit" variant={warnaSimpan} disabled={menyimpan || !bisaSimpan}
              data-testid={testIdSimpan || `${testId}-simpan`}>
              {menyimpan && <Loader2 className="animate-spin" />}
              {menyimpan ? 'Menyimpan…' : labelSimpan}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Satu isian form: label + kontrol + petunjuk/galat di bawahnya (konsisten di semua form). */
export function Isian({ label, wajib = false, petunjuk, galat, htmlFor, children, className }) {
  return (
    <div className={cn('space-y-1.5', className)}>
      {label && (
        <label htmlFor={htmlFor} className="block text-sm font-medium text-foreground">
          {label}{wajib && <span className="ml-0.5 text-[hsl(var(--danger-text))]" aria-hidden="true">*</span>}
        </label>
      )}
      {children}
      {galat ? <p className="text-xs text-[hsl(var(--danger-text))]">{galat}</p>
        : petunjuk ? <p className="text-xs text-muted-foreground">{petunjuk}</p> : null}
    </div>
  );
}

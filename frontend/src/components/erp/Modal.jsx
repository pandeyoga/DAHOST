/**
 * TD-014 Modal Unification (Session #11.13):
 * This legacy <Modal /> component is now a thin facade over Radix UI Dialog
 * primitives. All 41+ consumers (RahazaWorkOrdersModule, InvoiceModule,
 * PaymentModule, etc.) continue to work without code changes, but now benefit
 * from full Radix a11y (focus trap, ESC-to-close, aria-labelledby /
 * aria-describedby, portal rendering, scroll lock, etc.).
 *
 * Visual styling (GlassCard, IconButton) is preserved for backward
 * compatibility — no UI changes for end users.
 *
 * Public API (unchanged):
 *   <Modal title="..." onClose={fn} size="sm|md|lg|xl|2xl">{children}</Modal>
 *
 * New optional props:
 *   description    — accessibility description (sr-only by default)
 *   open           — controlled open state (default: true while mounted)
 *   onOpenChange   — called with new open state from Radix (ESC / overlay click)
 *   disableOutsideClose — disable click-outside / ESC dismissal (default: false)
 */
import * as React from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { IconButton } from './IconButton';

const SIZE_CLASSES = {
  sm: 'max-w-md',
  md: 'max-w-lg',
  lg: 'max-w-2xl',
  xl: 'max-w-4xl',
  '2xl': 'max-w-5xl',
  // 2026-08-07: tabel lebar (matriks warna × ukuran, baris biaya HPP, BOM tech pack)
  // tidak terbaca di max-w-5xl — kolomnya terpotong. Tambahan, bukan perubahan.
  '3xl': 'max-w-7xl',
};

function Modal({
  title,
  children,
  onClose,
  size = 'md',
  description,
  open,
  onOpenChange,
  disableOutsideClose = false,
  ...rest
}) {
  // Forward caller-supplied data-testid to the rendered dialog surface so tests
  // can target the specific modal (legacy facade previously dropped this prop).
  const dataTestId = rest['data-testid'];
  // Backward-compat: legacy callers don't pass `open`/`onOpenChange` —
  // they unmount the element entirely. While mounted, treat as open=true.
  const isControlled = typeof open === 'boolean';
  const effectiveOpen = isControlled ? open : true;

  const handleOpenChange = React.useCallback(
    (next) => {
      // Surface Radix close events to legacy onClose contract
      if (!next && typeof onClose === 'function') onClose();
      if (typeof onOpenChange === 'function') onOpenChange(next);
    },
    [onClose, onOpenChange],
  );

  // Optional defensive prop: disable dismiss-on-overlay & ESC for critical flows
  const interactionProps = disableOutsideClose
    ? {
        onPointerDownOutside: (e) => e.preventDefault(),
        onEscapeKeyDown:      (e) => e.preventDefault(),
        onInteractOutside:    (e) => e.preventDefault(),
      }
    : {};

  const autoDescId = React.useId();
  const sizeClass = SIZE_CLASSES[size] || SIZE_CLASSES.md;

  return (
    <DialogPrimitive.Root open={effectiveOpen} onOpenChange={handleOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay
          className="fixed inset-0 z-50 bg-black/80
                     data-[state=open]:animate-in data-[state=closed]:animate-out
                     data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0"
        />
        <DialogPrimitive.Content
          className={`fixed left-[50%] top-[50%] z-50 flex w-[calc(100%-2rem)] ${sizeClass} max-h-[90vh] flex-col
                      translate-x-[-50%] translate-y-[-50%] overflow-hidden sm:rounded-lg
                      border bg-background shadow-lg outline-none
                      max-sm:left-0 max-sm:top-0 max-sm:h-[100dvh] max-sm:max-h-none max-sm:w-full max-sm:max-w-none
                      max-sm:translate-x-0 max-sm:translate-y-0 max-sm:rounded-none
                      data-[state=open]:animate-in data-[state=closed]:animate-out
                      data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0
                      data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95`}
          aria-describedby={autoDescId}
          data-testid={dataTestId}
          {...interactionProps}
        >
          {/* Standar UI/UX v2 (8 Nov 2026): tampilan sama dengan FormPopup — kepala tipis, isi bergulir,
              layar penuh di HP. Perilaku (buka/tutup, onClose, testid) tidak berubah. */}
          <div className="flex items-center justify-between gap-3 border-b px-5 py-3">
            <DialogPrimitive.Title asChild>
              <h2 className="min-w-0 text-base font-semibold text-foreground">{title}</h2>
            </DialogPrimitive.Title>
            <DialogPrimitive.Close asChild>
              <IconButton
                label="Tutup"
                className="shrink-0 text-muted-foreground transition-colors hover:text-foreground"
                data-testid="modal-close"
              >
                <X className="h-5 w-5" />
              </IconButton>
            </DialogPrimitive.Close>
          </div>
          {/* sr-only description for Radix a11y compliance */}
          <DialogPrimitive.Description id={autoDescId} className="sr-only">
            {description || `Dialog: ${title || 'content'}`}
          </DialogPrimitive.Description>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

export default Modal;

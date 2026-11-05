/**
 * UniversalScanner.jsx — SSOT untuk semua barcode/QR scanning di ERP
 * Sprint A.1 — Konsolidasi 5 scanner menjadi 1
 *
 * Variants:
 *   - 'inline'  → Input field + tombol kamera (keyboard wedge auto-detect)
 *   - 'modal'   → Modal penuh dengan tab Kamera + Manual
 *   - 'button'  → Tombol kamera kecil saja (buka modal)
 *
 * Props:
 *   onScan(code, source)  — dipanggil dengan kode hasil scan
 *   variant               — 'inline' | 'modal' | 'button'
 *   open                  — (modal) apakah modal terlihat
 *   onClose               — (modal/button) fungsi tutup
 *   title                 — (modal) judul modal
 *   placeholder           — teks placeholder
 *   label                 — label atas input (inline)
 *   disabled              — boolean
 *   autoFocus             — boolean (inline)
 *   inputClassName        — className tambahan untuk input
 *
 * 2026-11-02 (Paket 3a) — props tambahan, SEMUA opsional (pemakai lama tidak berubah):
 *   continuous            — kamera tetap menyala & bisa scan berkali-kali (anti-dobel
 *                           1,5 dtk untuk kode yang sama); modal tidak menutup sendiri.
 *   feedback              — bunyi/getar saat kode terbaca (bawaan: = continuous).
 *   keepFocus             — (inline) input kembali fokus setelah setiap scan.
 *   dedupeMs              — (inline) abaikan kode sama dari wedge dalam jeda ini (bawaan 0).
 * Kode SELALU dinormalisasi (`scanCode.normalizeScanCode`, cermin backend) sebelum onScan.
 * Layar scan keluar (K15) & opname (K9) memakai komponen ini — jangan buat scanner baru.
 */
import { useState, useRef, useCallback, useEffect, useId } from 'react';
import {
  Camera, Keyboard, AlertTriangle, Loader2, Scan, ScanLine, CheckCircle2
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import Modal from '../Modal';
import { useCameraScanner, useWedgeInput } from './useScanner';
import { normalizeScanCode, scanFeedback } from './scanCode';

// ─── Internal: Camera + Manual modal contents ─────────────────────────────────
function ScannerModalContent({ onScan, onClose, title = 'Scan Barcode', continuous = false, feedback }) {
  const uid = useId().replace(/:/g, '_');
  const elementId = `universal-qr-${uid}`;
  const [tab, setTab]           = useState('camera');
  const [manual, setManual]     = useState('');
  const [scanLoading, setScanLoading] = useState(false);
  const [reads, setReads]       = useState({ count: 0, last: '', at: 0 });
  const beepOn = feedback ?? continuous;

  const {
    cameraState, setCameraState, cameraError, startCamera, stopCamera
  } = useCameraScanner({ elementId, continuous });

  const handleDetected = useCallback(async (raw, source) => {
    const code = normalizeScanCode(raw);
    if (!code) return;
    if (continuous) {
      // Kamera tetap jalan; tampilkan bacaan terakhir + hitungan.
      if (beepOn) scanFeedback('ok');
      setReads((r) => ({ count: r.count + 1, last: code, at: Date.now() }));
      onScan?.(code, source);
      return;
    }
    setScanLoading(true);
    try {
      await stopCamera();
      if (beepOn) scanFeedback('ok');
      onScan?.(code, source);   // AssetScannerModal mengirim onScan=undefined saat loading
      onClose?.();
    } finally {
      setScanLoading(false);
    }
  }, [onScan, onClose, stopCamera, continuous, beepOn]);

  // Callback terbaru disimpan di ref: kamera TIDAK di-restart setiap kali induk
  // render ulang dengan fungsi onScan baru (dulu: restart per scan → anti-dobel
  // hilang & barcode yang masih di depan kamera terbaca dua kali).
  const detectRef = useRef(handleDetected);
  detectRef.current = handleDetected;

  // Auto-start camera when on camera tab
  useEffect(() => {
    if (tab !== 'camera') return;
    let cancelled = false;
    (async () => {
      if (cancelled) return;
      await startCamera((code, source) => detectRef.current(code, source));
    })();
    return () => { cancelled = true; };
  }, [tab, startCamera]);

  // Stop camera when switching away
  const switchTab = async (next) => {
    if (next === tab) return;
    if (tab === 'camera') await stopCamera();
    setManual('');
    setTab(next);
    if (next === 'camera') setCameraState('starting');
  };

  const onManualSubmit = async (e) => {
    e?.preventDefault();
    const code = manual.trim();
    if (!code) return;
    setManual('');
    await handleDetected(code, 'manual');
  };
  // Kilatan hijau 700 ms setiap kali kode terbaca (mode kontinu)
  const [justRead, setJustRead] = useState(false);
  useEffect(() => {
    if (!reads.at) return undefined;
    setJustRead(true);
    const t = setTimeout(() => setJustRead(false), 700);
    return () => clearTimeout(t);
  }, [reads.at]);

  return (
    <div className="space-y-3" data-testid="universal-scanner-content">
      {/* Tab switcher */}
      <div className="inline-flex rounded-lg border border-[var(--glass-border)] bg-[var(--glass-bg)] p-1 w-full">
        <button
          type="button"
          onClick={() => switchTab('camera')}
          className={`flex-1 inline-flex items-center justify-center gap-1.5 py-2 rounded-md text-xs font-semibold transition-colors ${
            tab === 'camera'
              ? 'bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))]'
              : 'text-muted-foreground hover:text-foreground'
          }`}
          data-testid="scanner-tab-camera"
        >
          <Camera className="w-3.5 h-3.5" /> Kamera
        </button>
        <button
          type="button"
          onClick={() => switchTab('manual')}
          className={`flex-1 inline-flex items-center justify-center gap-1.5 py-2 rounded-md text-xs font-semibold transition-colors ${
            tab === 'manual'
              ? 'bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))]'
              : 'text-muted-foreground hover:text-foreground'
          }`}
          data-testid="scanner-tab-manual"
        >
          <Keyboard className="w-3.5 h-3.5" /> Input Manual
        </button>
      </div>

      {/* Camera tab */}
      {tab === 'camera' && (
        <div className="space-y-2">
          <div className={`rounded-xl overflow-hidden border-2 transition-colors ${
            justRead ? 'border-[hsl(var(--success)/0.35)]' : 'border-[var(--glass-border)]'}`}>
            <div
              id={elementId}
              className="w-full aspect-square bg-black/85"
              data-testid="scanner-viewport"
            />
          </div>
          {continuous && (
            <div
              className={`flex items-center justify-between rounded-lg px-3 py-2 text-xs border ${
                justRead
                  ? 'bg-[hsl(var(--success)/0.1)]  border-[hsl(var(--success)/0.35)]  text-[hsl(var(--success))] '
                  : 'bg-[var(--glass-bg)] border-[var(--glass-border)] text-muted-foreground'}`}
              data-testid="scanner-continuous-status"
            >
              <span className="inline-flex items-center gap-1.5 tabular-nums truncate">
                <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                {reads.last || 'Siap — scan berkali-kali tanpa menutup kamera'}
              </span>
              <span className="font-semibold shrink-0 ml-2" data-testid="scanner-continuous-count">{reads.count} scan</span>
            </div>
          )}
          <div className="text-center text-[11px] text-muted-foreground">
            {cameraState === 'starting' && (
              <span className="inline-flex items-center gap-1">
                <Loader2 className="w-3 h-3 animate-spin" /> Memulai kamera...
              </span>
            )}
            {cameraState === 'scanning' && 'Arahkan kamera ke QR code / barcode.'}
            {scanLoading && (
              <span className="inline-flex items-center gap-1 text-[hsl(var(--primary))]">
                <Loader2 className="w-3 h-3 animate-spin" /> Memproses...
              </span>
            )}
          </div>
          {cameraError && (
            <div
              className="bg-[hsl(var(--destructive)/0.1)] border border-[hsl(var(--destructive)/0.2)] rounded-lg p-2.5 text-xs text-[hsl(var(--destructive))]  flex items-start gap-2"
              data-testid="scanner-camera-error"
            >
              <AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
              <span>
                {cameraError}
                <button
                  type="button"
                  onClick={() => switchTab('manual')}
                  className="ml-2 underline font-semibold"
                  data-testid="scanner-switch-manual-cta"
                >
                  Pakai input manual
                </button>
              </span>
            </div>
          )}
        </div>
      )}

      {/* Manual tab */}
      {tab === 'manual' && (
        <form onSubmit={onManualSubmit} className="space-y-2" data-testid="scanner-manual-form">
          <label className="block text-xs font-medium text-foreground/70">Nomor / Kode</label>
          <Input
            autoFocus
            value={manual}
            onChange={(e) => setManual(e.target.value)}
            placeholder="Ketik atau scan..."
            className="tabular-nums"
            data-testid="scanner-manual-input"
          />
          <Button
            type="submit"
            disabled={scanLoading || !manual.trim()}
            className="w-full h-11"
            data-testid="scanner-manual-submit"
          >
            {scanLoading ? (
              <span className="inline-flex items-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin" /> Memproses...
              </span>
            ) : 'Konfirmasi Kode'}
          </Button>
        </form>
      )}

      {continuous && onClose && (
        <Button type="button" variant="outline" className="w-full" onClick={onClose}
          data-testid="scanner-continuous-done">
          Selesai scan
        </Button>
      )}

      <div className="text-[10px] text-muted-foreground text-center">
        Tips: tekan{' '}
        <kbd className="px-1 py-0.5 border border-[var(--glass-border)] rounded bg-[var(--glass-bg)]">
          Input Manual
        </kbd>{' '}
        kalau kamera bermasalah.
      </div>
    </div>
  );
}

// ─── Modal Variant ────────────────────────────────────────────────────────────
function ScannerModal({ open, onClose, onScan, title = 'Scan Barcode', continuous = false, feedback }) {
  if (!open) return null;
  return (
    <Modal
      onClose={onClose}
      title={title}
      size="sm"
      data-testid="universal-scanner-modal"
    >
      <ScannerModalContent onScan={onScan} onClose={onClose} title={title}
        continuous={continuous} feedback={feedback} />
    </Modal>
  );
}

// ─── Inline Variant ───────────────────────────────────────────────────────────
// Input dengan tombol kamera. Keyboard wedge auto-detected (useWedgeInput).
function ScannerInline({
  onScan, placeholder = 'Scan atau ketik barcode...', label, disabled,
  autoFocus = false, inputClassName = '', 'data-testid': testId,
  continuous = false, keepFocus = false, feedback = false, dedupeMs = 0,
}) {
  const [value, setValue]       = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [flashAt, setFlashAt]   = useState(0);
  const inputRef                = useRef(null);

  const refocus = useCallback(() => {
    if (keepFocus) setTimeout(() => inputRef.current?.focus(), 0);
  }, [keepFocus]);

  const fireScan = useCallback((code, source, beep = true) => {
    setValue('');
    setFlashAt(Date.now());
    if (feedback && beep) scanFeedback('ok');
    onScan?.(code, source);
    refocus();
  }, [onScan, feedback, refocus]);

  const { handleKeyDown } = useWedgeInput({
    inputRef, dedupeMs, onCode: (code) => fireScan(code, 'inline'),
  });

  // Hapus kilatan hijau setelah 600 ms
  useEffect(() => {
    if (!flashAt) return undefined;
    const t = setTimeout(() => setFlashAt(0), 600);
    return () => clearTimeout(t);
  }, [flashAt]);

  // Camera modal onScan callback
  const handleModalScan = (code, source = 'camera') => {
    if (!continuous) setModalOpen(false);
    fireScan(normalizeScanCode(code), source, false);   // modal sudah berbunyi sendiri
  };

  return (
    <>
      {label && (
        <label className="block text-xs font-medium text-foreground/70 mb-1">{label}</label>
      )}
      <div className="relative flex items-center gap-1" data-testid={testId || 'universal-scanner-inline'}>
        <Input
          ref={inputRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          autoFocus={autoFocus}
          className={`tabular-nums pr-10 transition-shadow ${flashAt ? 'ring-2 ring-[hsl(var(--success)/0.35)]' : ''} ${inputClassName}`}
          data-testid="scanner-inline-input"
        />
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          disabled={disabled}
          title="Buka kamera scanner"
          className="absolute right-2 text-muted-foreground hover:text-[hsl(var(--primary))] transition-colors disabled:opacity-40"
          data-testid="scanner-camera-btn"
        >
          <ScanLine className="w-4 h-4" />
        </button>
      </div>
      <ScannerModal
        open={modalOpen}
        onClose={() => { setModalOpen(false); refocus(); }}
        onScan={handleModalScan}
        title="Scan Barcode"
        continuous={continuous}
        feedback={feedback || continuous}
      />
    </>
  );
}

// ─── Button Variant ───────────────────────────────────────────────────────────
// Hanya tombol yang membuka modal
function ScannerButton({
  onScan, title = 'Scan Barcode', label, disabled, size = 'sm', variant: btnVariant = 'outline',
  'data-testid': testId, className = '', continuous = false, feedback,
}) {
  const [open, setOpen] = useState(false);
  const handleScan = (code, source) => {
    if (!continuous) setOpen(false);
    onScan?.(code, source);
  };
  return (
    <>
      <Button
        type="button"
        variant={btnVariant}
        size={size}
        onClick={() => setOpen(true)}
        disabled={disabled}
        className={`gap-1.5 ${className}`}
        data-testid={testId || 'scanner-button'}
      >
        <Scan className="w-3.5 h-3.5" />
        {label || 'Scan'}
      </Button>
      <ScannerModal open={open} onClose={() => setOpen(false)} onScan={handleScan} title={title}
        continuous={continuous} feedback={feedback} />
    </>
  );
}

// ─── Main Export ──────────────────────────────────────────────────────────────
/**
 * UniversalScanner — SSOT scanner component
 *
 * @example inline:
 *   <UniversalScanner variant="inline" onScan={code => handleScan(code)} />
 *
 * @example modal:
 *   <UniversalScanner variant="modal" open={showScanner} onClose={() => setShowScanner(false)}
 *     onScan={code => { setShowScanner(false); process(code); }} />
 *
 * @example button:
 *   <UniversalScanner variant="button" onScan={code => fill(code)} label="Scan SKU" />
 */
export default function UniversalScanner({
  variant = 'inline',
  onScan,
  open,
  onClose,
  title,
  placeholder,
  label,
  disabled,
  autoFocus,
  inputClassName,
  size,
  btnVariant,
  className,
  continuous,
  feedback,
  keepFocus,
  dedupeMs,
  'data-testid': testId,
}) {
  if (variant === 'modal') {
    return (
      <ScannerModal
        open={open}
        onClose={onClose}
        onScan={onScan}
        title={title}
        continuous={continuous}
        feedback={feedback}
      />
    );
  }
  if (variant === 'button') {
    return (
      <ScannerButton
        onScan={onScan}
        title={title}
        label={label}
        disabled={disabled}
        size={size}
        variant={btnVariant}
        className={className}
        continuous={continuous}
        feedback={feedback}
        data-testid={testId}
      />
    );
  }
  // default: 'inline'
  return (
    <ScannerInline
      onScan={onScan}
      placeholder={placeholder}
      label={label}
      disabled={disabled}
      autoFocus={autoFocus}
      inputClassName={inputClassName}
      continuous={continuous}
      feedback={feedback}
      keepFocus={keepFocus}
      dedupeMs={dedupeMs}
      data-testid={testId}
    />
  );
}

// Named exports for convenience
export { ScannerModal, ScannerInline, ScannerButton, ScannerModalContent };

/**
 * useScanner.js — Universal Scanner Hook (Sprint A.1)
 * SSOT untuk semua scanner logic: camera lifecycle, keyboard wedge detection.
 *
 * 2026-11-02 (Paket 3a — fondasi scan keluar K15 & opname K9):
 *   - Kamera: mode `continuous` — kamera TIDAK berhenti setelah satu kali baca.
 *     Kode yang SAMA dalam `cooldownMs` (bawaan 1,5 dtk) diabaikan, karena kamera
 *     membaca barcode yang sama berkali-kali per detik; kode BERBEDA langsung
 *     diteruskan (dengan jeda minimum `minGapMs` untuk menyaring bacaan setengah).
 *     Tanpa `continuous` perilaku lama dipertahankan (berhenti setelah 1 baca).
 *   - Wedge: `useWedgeInput` adalah SATU-SATUNYA deteksi scanner keyboard
 *     (dulu ada dua salinan: `useKeyboardWedge` yang tidak dipakai siapa pun dan
 *     logika di dalam ScannerInline). Enter mengakhiri kode; tanpa Enter, kode
 *     yang diketik secepat scanner di-flush setelah jeda 150 ms; satu kode tidak
 *     pernah terkirim dua kali (timer dibatalkan saat Enter).
 */
import { useEffect, useRef, useState, useCallback } from 'react';
import { normalizeScanCode } from './scanCode';

// ─── Camera Hook ─────────────────────────────────────────────────────────────
export function useCameraScanner({ elementId, continuous = false, cooldownMs = 1500, minGapMs = 350 }) {
  const scannerRef = useRef(null);
  const lastRef = useRef({ code: '', at: 0 });
  const [cameraState, setCameraState] = useState('idle');
  // idle | starting | scanning | blocked | unsupported | stopping
  const [cameraError, setCameraError] = useState('');

  const stopCamera = useCallback(async () => {
    try {
      if (scannerRef.current) {
        const inst = scannerRef.current;
        scannerRef.current = null;
        if (inst.isScanning) {
          try { await inst.stop(); } catch (_) { /* noop */ }
        }
        try { await inst.clear(); } catch (_) { /* noop */ }
      }
    } catch (_) { /* noop */ }
    setCameraState('idle');
  }, []);

  const startCamera = useCallback(async (onDetected) => {
    setCameraError('');
    setCameraState('starting');
    try {
      const el = document.getElementById(elementId);
      if (!el) {
        setCameraState('unsupported');
        setCameraError('Scanner element tidak ditemukan.');
        return;
      }
      if (scannerRef.current) await stopCamera();

      // Dynamic import to avoid bundle bloat if not used
      const { Html5Qrcode } = await import('html5-qrcode');

      let cameras = [];
      try {
        cameras = await Html5Qrcode.getCameras();
      } catch {
        setCameraState('blocked');
        setCameraError('Kamera tidak dapat diakses. Pastikan izin kamera diberikan (perlu HTTPS).');
        return;
      }
      if (!cameras || cameras.length === 0) {
        setCameraState('unsupported');
        setCameraError('Tidak ada kamera terdeteksi di perangkat ini.');
        return;
      }

      // Prefer back camera
      const preferred =
        cameras.find((c) => /back|environment|rear/i.test(c.label)) ||
        cameras[cameras.length - 1] ||
        cameras[0];

      // BarcodeDetector bawaan browser (Chrome Android) jauh lebih andal untuk
      // barcode 1D (Code128 SKU) daripada dekoder JS; jatuh ke dekoder JS bila tidak ada.
      const instance = new Html5Qrcode(elementId, {
        verbose: false, experimentalFeatures: { useBarCodeDetectorIfSupported: true },
      });
      scannerRef.current = instance;

      const config = {
        fps: 10,
        // Kotak baca lebar-pendek: barcode 1D (Code128 SKU) panjang mendatar,
        // QR tetap terbaca di dalamnya.
        qrbox: (w, h) => {
          const width = Math.max(50, Math.floor(Math.min(w * 0.9, 480)));
          const height = Math.max(50, Math.floor(Math.min(h * 0.6, width)));
          return { width, height };
        },
        aspectRatio: 1.0,
      };

      let handled = false;
      lastRef.current = { code: '', at: 0 };
      await instance.start(
        preferred.id,
        config,
        async (decodedText) => {
          const code = normalizeScanCode(decodedText);
          if (!code) return;
          if (!continuous) {
            if (handled) return;
            handled = true;
            try { await instance.pause(true); } catch (_) { /* noop */ }
            onDetected(code, 'camera');
            return;
          }
          // Mode kontinu: anti-dobel
          const now = Date.now();
          const last = lastRef.current;
          if (now - last.at < minGapMs) return;
          if (code === last.code && now - last.at < cooldownMs) {
            lastRef.current = { code, at: now };   // barcode masih di depan kamera
            return;
          }
          lastRef.current = { code, at: now };
          onDetected(code, 'camera');
        },
        () => { /* ignore per-frame errors */ },
      );
      setCameraState('scanning');
    } catch (e) {
      setCameraState('blocked');
      setCameraError(e?.message || 'Tidak bisa memulai scanner. Cek izin kamera.');
    }
  }, [elementId, stopCamera, continuous, cooldownMs, minGapMs]);

  // Cleanup on unmount
  useEffect(() => () => { stopCamera(); }, [stopCamera]);

  return { cameraState, setCameraState, cameraError, startCamera, stopCamera };
}

// ─── Keyboard Wedge (scanner USB/Bluetooth sebagai keyboard) ─────────────────
// Scanner wedge mengetik < 30 ms per karakter lalu (biasanya) Enter.
export const WEDGE_INTERVAL_MS = 30;
export const WEDGE_FLUSH_MS = 150;
export const WEDGE_MIN_LEN = 3;

/**
 * useWedgeInput({ inputRef, onCode, dedupeMs }) → { handleKeyDown, flushNow }
 *   - Enter → kirim isi input (≥ 3 karakter), input dikosongkan oleh pemanggil.
 *   - Tanpa Enter: bila karakter masuk secepat scanner, flush otomatis 150 ms
 *     setelah karakter terakhir.
 *   - `dedupeMs` > 0 → kode yang sama dalam jeda itu diabaikan (bawaan 0: dua
 *     barang identik yang di-scan berurutan SAH dihitung dua kali).
 */
export function useWedgeInput({ inputRef, onCode, dedupeMs = 0 }) {
  const lastTsRef = useRef(0);
  const fastRef = useRef(false);
  const timerRef = useRef(null);
  const lastSentRef = useRef({ code: '', at: 0 });

  const clearTimer = () => {
    if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }
  };

  const send = useCallback((raw) => {
    clearTimer();
    fastRef.current = false;
    const code = normalizeScanCode(raw);
    if (code.length < WEDGE_MIN_LEN) return false;
    const now = Date.now();
    if (dedupeMs > 0 && code === lastSentRef.current.code && now - lastSentRef.current.at < dedupeMs) {
      return false;
    }
    lastSentRef.current = { code, at: now };
    onCode?.(code);
    return true;
  }, [onCode, dedupeMs]);

  const flushNow = useCallback(() => send(inputRef.current?.value || ''), [send, inputRef]);

  const handleKeyDown = useCallback((e) => {
    const now = Date.now();
    const interval = now - lastTsRef.current;
    lastTsRef.current = now;
    if (e.key === 'Enter') {
      if (normalizeScanCode(inputRef.current?.value || '').length >= WEDGE_MIN_LEN) {
        e.preventDefault();
        flushNow();
      }
      return;
    }
    if (e.key === 'Escape') { clearTimer(); fastRef.current = false; return; }
    if (e.key.length !== 1) return;
    if (interval < WEDGE_INTERVAL_MS) fastRef.current = true;
    if (fastRef.current) {
      clearTimer();
      timerRef.current = setTimeout(flushNow, WEDGE_FLUSH_MS);
    }
  }, [flushNow, inputRef]);

  useEffect(() => () => clearTimer(), []);

  return { handleKeyDown, flushNow };
}

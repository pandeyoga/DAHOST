/**
 * UniversalScanPortal.jsx
 *
 * Floating scan button yang bisa diakses dari mana saja di ERP.
 * Scan barcode/QR → resolve ke entity (Asset/Bundle/Material/WO/PO/Roll/DO)
 * Tampilkan result card dengan quick actions.
 *
 * Usage (di PortalShell):
 *   <UniversalScanPortal token={token} onNavigate={setModule} />
 */
import { useState, useCallback, useEffect } from 'react';
import {
  ScanLine, X, CheckCircle2, AlertTriangle, Loader2, Clock,
  Package, Box, Layers, ClipboardList, ShoppingCart, Columns, Truck, History, Shirt, MapPin,
} from 'lucide-react';
import { ScannerModalContent } from './UniversalScanner';
import axios from 'axios';

const API = process.env.REACT_APP_BACKEND_URL;

// ─── Entity type config ───────────────────────────────────────────────────────
// 2026-11-02 (Paket 3a): + `fg` (SKU barang jadi, Code128 & QR label) dan `bin`
// (posisi rak / lokasi) — resolver backend kini `core.scan_resolver`.
const ENTITY_CFG = {
  fg:             { icon: Shirt,         color: 'text-[hsl(var(--destructive))] ',    bg: 'bg-[hsl(var(--destructive)/0.1)] ',    border: 'border-[hsl(var(--destructive)/0.35)] ',    label: 'Barang Jadi (SKU)' },
  bin:            { icon: MapPin,        color: 'text-[hsl(var(--success))] ',    bg: 'bg-[hsl(var(--success)/0.1)] ',    border: 'border-[hsl(var(--success)/0.35)] ',    label: 'Lokasi / Bin' },
  asset:          { icon: Package,       color: 'text-[hsl(var(--primary))] ',    bg: 'bg-[hsl(var(--primary)/0.1)] ',    border: 'border-[hsl(var(--primary)/0.35)] ',    label: 'Aset' },
  bundle:         { icon: Box,           color: 'text-[hsl(var(--primary))] ',  bg: 'bg-[hsl(var(--primary)/0.1)] ',  border: 'border-[hsl(var(--primary)/0.35)] ',  label: 'Bundle Produksi' },
  material:       { icon: Layers,        color: 'text-[hsl(var(--success))] ', bg: 'bg-[hsl(var(--success)/0.1)] ', border: 'border-[hsl(var(--success)/0.35)] ', label: 'Material' },
  work_order:     { icon: ClipboardList, color: 'text-[hsl(var(--warning))] ',  bg: 'bg-[hsl(var(--warning)/0.1)] ',  border: 'border-[hsl(var(--warning)/0.35)] ',  label: 'Work Order' },
  purchase_order: { icon: ShoppingCart,  color: 'text-[hsl(var(--primary))] ',  bg: 'bg-[hsl(var(--primary)/0.1)] ',  border: 'border-[hsl(var(--primary)/0.35)] ',  label: 'Purchase Order' },
  fabric_roll:    { icon: Columns,       color: 'text-[hsl(var(--warning))] ',  bg: 'bg-[hsl(var(--warning)/0.1)] ',  border: 'border-[hsl(var(--warning)/0.35)] ',  label: 'Roll Kain' },
  delivery_order: { icon: Truck,         color: 'text-[hsl(var(--primary))] ',     bg: 'bg-[hsl(var(--primary)/0.1)] ',     border: 'border-[hsl(var(--primary)/0.35)] ',     label: 'Delivery Order' },
};

// ─── Status badge ─────────────────────────────────────────────────────────────
function StatusBadge({ status }) {
  if (!status) return null;
  const STATUS_COLOR = {
    active: 'bg-[hsl(var(--success)/0.1)]  text-[hsl(var(--success))] ', available: 'bg-[hsl(var(--success)/0.1)]  text-[hsl(var(--success))] ',
    in_use: 'bg-[hsl(var(--primary)/0.1)]  text-[hsl(var(--primary))] ',       in_stock: 'bg-[hsl(var(--success)/0.1)]  text-[hsl(var(--success))] ',
    draft: 'bg-muted text-foreground',         inactive: 'bg-muted text-foreground',
    maintenance: 'bg-[hsl(var(--warning)/0.1)]  text-[hsl(var(--warning))] ',
    completed: 'bg-[hsl(var(--primary)/0.1)]  text-[hsl(var(--primary))] ',       done: 'bg-[hsl(var(--primary)/0.1)]  text-[hsl(var(--primary))] ',
    rejected: 'bg-[hsl(var(--destructive)/0.1)]  text-[hsl(var(--destructive))] ',        cancelled: 'bg-[hsl(var(--destructive)/0.1)]  text-[hsl(var(--destructive))] ',
    in_progress: 'bg-[hsl(var(--warning)/0.1)]  text-[hsl(var(--warning))] ',
    approved: 'bg-[hsl(var(--success)/0.1)]  text-[hsl(var(--success))] ',
  };
  const cls = STATUS_COLOR[status] || 'bg-muted text-foreground';
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider ${cls}`}>
      {status.replace(/_/g, ' ')}
    </span>
  );
}

// ─── Scan Result Card ─────────────────────────────────────────────────────────
function ScanResultCard({ result, onAction, onScanAgain }) {
  const cfg = ENTITY_CFG[result.entity_type] || ENTITY_CFG.asset;
  const Icon = cfg.icon;

  return (
    <div className={`rounded-2xl border ${cfg.border} ${cfg.bg} p-4 space-y-3`} data-testid="scan-result-card">
      {/* Header */}
      <div className="flex items-start gap-3">
        <div className={`w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 ${cfg.bg} border ${cfg.border}`}>
          <Icon size={18} className={cfg.color} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-[10px] font-bold uppercase tracking-widest ${cfg.color}`}>
              {cfg.label}
            </span>
            <StatusBadge status={result.status} />
          </div>
          <p className="text-sm font-semibold text-foreground mt-0.5 truncate">{result.display_name}</p>
          <p className="text-xs text-muted-foreground tabular-nums">{result.entity_number}</p>
        </div>
      </div>

      {/* Meta */}
      {result.meta && Object.keys(result.meta).length > 0 && (
        <div className="grid grid-cols-3 gap-2">
          {Object.entries(result.meta).map(([k, v]) => (
            <div key={k} className="bg-black/20 rounded-lg px-2 py-1.5">
              <div className="text-[10px] text-muted-foreground">{k}</div>
              <div className="text-xs text-foreground font-medium truncate" title={v}>{v || '—'}</div>
            </div>
          ))}
        </div>
      )}

      {/* Quick Actions */}
      {result.quick_actions?.length > 0 && (
        <div className="flex gap-2 flex-wrap">
          {result.quick_actions.map((qa) => (
            <button
              key={qa.id}
              onClick={() => onAction(qa)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-xl border ${cfg.border} ${cfg.color} hover:${cfg.bg} transition-colors`}
              data-testid={`quick-action-${qa.id}`}
            >
              {qa.label}
            </button>
          ))}
        </div>
      )}

      <button
        onClick={onScanAgain}
        className="w-full py-2 text-xs font-medium text-muted-foreground hover:text-foreground border border-[var(--glass-border)] rounded-xl transition-colors"
        data-testid="scan-again-btn"
      >
        Scan Lagi
      </button>
    </div>
  );
}

// ─── Not Found Card ───────────────────────────────────────────────────────────
function NotFoundCard({ code, onScanAgain }) {
  return (
    <div className="rounded-2xl border border-[hsl(var(--destructive)/0.35)] bg-[hsl(var(--destructive)/0.1)]  p-4 space-y-3" data-testid="scan-not-found-card">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 bg-[hsl(var(--destructive)/0.1)] border border-[hsl(var(--destructive)/0.35)] ">
          <AlertTriangle size={18} className="text-[hsl(var(--destructive))] " />
        </div>
        <div>
          <p className="text-sm font-semibold text-foreground">Kode Tidak Ditemukan</p>
          <p className="text-xs text-muted-foreground tabular-nums mt-0.5">{code}</p>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        Kode ini tidak cocok dengan SKU barang jadi, bahan, lokasi/bin, roll kain, bundle, WO, PO, delivery order, atau aset yang terdaftar.
      </p>
      <button
        onClick={onScanAgain}
        className="w-full py-2 text-xs font-medium text-muted-foreground hover:text-foreground border border-[var(--glass-border)] rounded-xl transition-colors"
        data-testid="scan-again-btn-notfound"
      >
        Scan Lagi
      </button>
    </div>
  );
}

// ─── History Item ─────────────────────────────────────────────────────────────
function HistoryItem({ item }) {
  const cfg = ENTITY_CFG[item.entity_type];
  const Icon = cfg?.icon || Package;
  const time = new Date(item.scanned_at).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' });
  return (
    <div className="flex items-center gap-2.5 py-1.5 border-b border-foreground/5 last:border-0">
      {item.found ? (
        <div className={`w-6 h-6 rounded-md flex-shrink-0 flex items-center justify-center ${cfg?.bg || 'bg-foreground/5'}`}>
          <Icon size={11} className={cfg?.color || 'text-muted-foreground'} />
        </div>
      ) : (
        <div className="w-6 h-6 rounded-md flex-shrink-0 flex items-center justify-center bg-[hsl(var(--destructive)/0.1)] ">
          <X size={11} className="text-[hsl(var(--destructive))] " />
        </div>
      )}
      <div className="flex-1 min-w-0">
        <p className="text-xs text-foreground truncate">
          {item.display_name || item.raw_code}
        </p>
        {item.entity_number && item.entity_number !== item.display_name && (
          <p className="text-[10px] text-muted-foreground tabular-nums">{item.entity_number}</p>
        )}
      </div>
      <span className="text-[10px] text-muted-foreground flex-shrink-0">{time}</span>
    </div>
  );
}

// ─── Main Portal ──────────────────────────────────────────────────────────────
export default function UniversalScanPortal({ token, onNavigate }) {
  const [open, setOpen]               = useState(false);
  const [scanning, setScanning]       = useState(false);
  const [resolving, setResolving]     = useState(false);
  const [result, setResult]           = useState(null);     // null | {found, ...}
  const [history, setHistory]         = useState([]);
  const [showHistory, setShowHistory] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const headers = { Authorization: `Bearer ${token}` };

  const loadHistory = useCallback(async () => {
    if (!token) return;
    setHistoryLoading(true);
    try {
      const r = await axios.get(`${API}/api/scan/history?limit=20`, { headers });
      setHistory(r.data || []);
    } catch (_) { /* noop */ }
    finally { setHistoryLoading(false); }
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const onOpen = () => openPortal();
    window.addEventListener('erp-universal-scan', onOpen);
    return () => window.removeEventListener('erp-universal-scan', onOpen);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const openPortal = () => {
    setOpen(true);
    setResult(null);
    setScanning(true);
    setShowHistory(false);
    loadHistory();
  };

  const closePortal = () => {
    setOpen(false);
    setScanning(false);
    setResult(null);
    setShowHistory(false);
  };

  const handleScan = useCallback(async (code) => {
    if (!code.trim()) return;
    setScanning(false);
    setResolving(true);
    setResult(null);
    try {
      const r = await axios.post(`${API}/api/scan/resolve`, { code }, { headers });
      setResult(r.data);
      loadHistory();
    } catch (e) {
      setResult({ found: false, raw_code: code });
    } finally {
      setResolving(false);
    }
  }, [token, loadHistory]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleAction = (qa) => {
    if (qa.module && onNavigate) {
      onNavigate(qa.module);
      closePortal();
    }
  };

  const scanAgain = () => {
    setResult(null);
    setScanning(true);
  };

  // Keyboard shortcut: Ctrl+Shift+S
  useEffect(() => {
    const handler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'S') {
        e.preventDefault();
        if (open) closePortal();
        else openPortal();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      {/* 2026-11-06 — pemicu kini tombol di kepala halaman (TopBar, event `erp-universal-scan`),
          bukan bulatan mengambang yang menutupi isi halaman. Pintasan Ctrl+Shift+S tetap. */}

      {/* Portal modal */}
      {open && (
        <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4"
          onClick={(e) => e.target === e.currentTarget && closePortal()}
        >
          {/* Backdrop */}
          <div className="absolute inset-0 bg-foreground/40 backdrop-blur-sm" onClick={closePortal} />

          {/* Panel */}
          <div className="relative w-full sm:max-w-md bg-background border border-[var(--glass-border)] rounded-t-3xl sm:rounded-2xl shadow-2xl overflow-hidden"
            data-testid="universal-scan-portal"
          >
            {/* Header */}
            <div className="flex items-center justify-between px-5 pt-5 pb-3">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-xl bg-[hsl(var(--primary)/0.15)] border border-[hsl(var(--primary)/0.35)]  flex items-center justify-center">
                  <ScanLine size={15} className="text-[hsl(var(--primary))] " />
                </div>
                <div>
                  <p className="text-sm font-semibold text-foreground">Scan barcode</p>
                  <p className="text-[10px] text-muted-foreground">SKU • Bahan • Bin • Roll • Bundle • WO • PO • DO • Aset</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => { setShowHistory(!showHistory); if (!showHistory) loadHistory(); }}
                  className={`w-8 h-8 rounded-xl flex items-center justify-center transition-colors ${showHistory ? 'bg-[hsl(var(--primary)/0.15)]  text-[hsl(var(--primary))] ' : 'text-muted-foreground hover:text-foreground hover:bg-foreground/5'}`}
                  data-testid="scan-history-toggle"
                  title="Riwayat scan" aria-label="Riwayat scan"
                >
                  <History size={14} />
                </button>
                <button onClick={closePortal} aria-label="Tutup" title="Tutup" className="w-8 h-8 rounded-xl text-muted-foreground hover:text-foreground hover:bg-foreground/5 flex items-center justify-center">
                  <X size={14} />
                </button>
              </div>
            </div>

            <div className="px-5 pb-6 space-y-4 max-h-[80vh] overflow-y-auto">
              {/* History panel */}
              {showHistory && (
                <div className="bg-foreground/5 border border-[var(--glass-border)] rounded-xl p-3">
                  <p className="text-xs font-semibold text-foreground mb-2 flex items-center gap-1.5">
                    <History size={12} /> Riwayat Scan Terakhir
                  </p>
                  {historyLoading ? (
                    <div className="flex items-center gap-2 text-xs text-muted-foreground py-2">
                      <Loader2 size={12} className="animate-spin" /> Memuat...
                    </div>
                  ) : history.length === 0 ? (
                    <p className="text-xs text-muted-foreground py-2">Belum ada riwayat scan.</p>
                  ) : (
                    <div>
                      {history.map((h) => <HistoryItem key={h.id} item={h} />)}
                    </div>
                  )}
                </div>
              )}

              {/* Scanner (camera/manual) — inline content, no nested modal */}
              {scanning && !resolving && (
                <div data-testid="universal-scan-scanner-area">
                  {/* onClose=undefined: portal has its own close button; we don't want scanner to close the whole portal */}
                  <ScannerModalContent onScan={handleScan} onClose={undefined} title="Scan Barcode / QR Code" />
                </div>
              )}

              {/* Resolving state */}
              {resolving && (
                <div className="flex items-center justify-center gap-3 py-10" data-testid="scan-resolving">
                  <Loader2 size={20} className="animate-spin text-[hsl(var(--primary))] " />
                  <p className="text-sm text-foreground">Mengidentifikasi...</p>
                </div>
              )}

              {/* Result */}
              {!scanning && !resolving && result && (
                result.found
                  ? <ScanResultCard result={result} onAction={handleAction} onScanAgain={scanAgain} />
                  : <NotFoundCard code={result.raw_code} onScanAgain={scanAgain} />
              )}
            </div>

            {/* Keyboard hint */}
            <div className="px-5 pb-4 text-center">
              <p className="text-[10px] text-muted-foreground">
                Shortcut:{' '}
                <kbd className="px-1.5 py-0.5 bg-foreground/5 border border-[var(--glass-border)] rounded text-muted-foreground">Ctrl</kbd>
                {' + '}
                <kbd className="px-1.5 py-0.5 bg-foreground/5 border border-[var(--glass-border)] rounded text-muted-foreground">Shift</kbd>
                {' + '}
                <kbd className="px-1.5 py-0.5 bg-foreground/5 border border-[var(--glass-border)] rounded text-muted-foreground">S</kbd>
              </p>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

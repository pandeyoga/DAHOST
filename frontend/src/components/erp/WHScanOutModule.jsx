/**
 * WHScanOutModule — Gudang → OUTBOUND → "Scan Keluar Penjualan" (keputusan owner K15, 2026-11-02).
 *
 * Gudang men-scan setiap pcs barang jadi yang keluar untuk pembeli marketplace (tanpa nomor
 * pesanan). Setiap scan langsung memotong stok lokasi yang dipilih dan membekukan nilai WAC;
 * jurnal HPP lahir SATU per lembar saat "Tutup Hari" (atau otomatis 23:55 WIB).
 *
 * Layar ringkas untuk HP/tablet gudang (uji 375 px):
 *   Tab Scan          — pilih lokasi (wajib) + toko (opsional), scan terus-menerus (scanner
 *                       keyboard / kamera kontinu dari komponen scanner bersama), bunyi/getar
 *                       SETELAH server menjawab, daftar baris hari ini (merah = stok kurang /
 *                       tanpa WAC), batal baris, "Batal kirim", Tutup Hari (SPV).
 *   Tab Laporan       — per SKU / toko / petugas, nota Portal Penjualan & retur (pembanding),
 *                       pengecualian, unduh CSV.
 *   Tab Kontrol       — pcs pesanan impor (tanggal kirim) vs pcs scan, per hari + kumulatif.
 * Semua angka dihitung backend (`backend/core/scan_out.py`); layar ini tidak menghitung ulang.
 */
import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import {
  ScanLine, MapPin, Store, Lock, AlertTriangle, RefreshCw, Undo2, FileDown,
  ClipboardList, Scale, CheckCircle2, RotateCw,
} from 'lucide-react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { GlassCard } from '@/components/ui/glass';
import { formatRupiah, formatNumber } from '@/lib/format';
import { downloadCsv } from '@/lib/csv';
import { todayWIB, daysAgoWIB } from '@/lib/waktu';
import UniversalScanner from './scanner/UniversalScanner';
import { scanFeedback } from './scanner/scanCode';
import { toScanResult } from './scanner/ScanResult';
import PageLayout from './layout/PageLayout';
import { StatTile } from './moduleAtoms';

const API = '/api/wh/scan-out';
const LS_LOC = 'whScanOut.location';
const LS_STORE = 'whScanOut.store';
// 2026-11-06 (Tahap 2): scan yang belum sampai server (jaringan putus) disimpan juga di perangkat ini,
// supaya muat ulang layar tidak menghilangkannya. Scan yang SUDAH sampai server tetapi gagal diproses
// ada di antrean server (`retry_queue`) — bisa dikirim ulang dari perangkat mana pun.
const LS_UNSENT = 'whScanOut.unsent';
const loadUnsent = () => { try { return JSON.parse(localStorage.getItem(LS_UNSENT) || '[]') || []; } catch (_) { return []; } };
const saveUnsent = (list) => { try { localStorage.setItem(LS_UNSENT, JSON.stringify(list || [])); } catch (_) { /* noop */ } };
const MULTS = [1, 2, 6, 12];
const FLAG_LABEL = {
  stok_kurang: 'Stok sistem kurang',
  tanpa_wac: 'WAC 0 — tanpa nilai',
  batal_tanpa_scan: 'Batal kirim tanpa scan keluar 7 hari',
};

// Scan yang gagal terkirim dikirim ulang dengan id scan yang SAMA (server tidak menghitung dua kali).
// Scan ulang barangnya = id baru = stok terpotong dua kali — jadi petugas diarahkan ke "Kirim ulang".
const RESEND_HINT = 'Jangan scan ulang barangnya — tekan "Kirim ulang" di bawah. Scan ulang memotong stok dua kali.';
const rp = (v) => formatRupiah(v, { decimals: Math.abs(v || 0) % 1 ? 2 : 0 });
const num = (v) => formatNumber(v);
const newScanId = () => {
  try { if (window.crypto?.randomUUID) return window.crypto.randomUUID(); } catch (_) { /* noop */ }
  return `scan-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
};
const lsGet = (k) => { try { return localStorage.getItem(k) || ''; } catch (_) { return ''; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, v || ''); } catch (_) { /* noop */ } };
const fmtTime = (v) => {
  if (!v) return '';
  try { return new Date(v).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', second: '2-digit' }); }
  catch (_) { return ''; }
};

function Tab({ active, onClick, icon: Icon, children, testId }) {
  return (
    <button type="button" onClick={onClick} data-testid={testId}
      className={`flex-1 inline-flex items-center justify-center gap-1.5 py-2 rounded-md text-xs font-semibold transition-colors ${
        active ? 'bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))]' : 'text-muted-foreground hover:text-foreground'}`}>
      <Icon className="w-3.5 h-3.5" /> {children}
    </button>
  );
}

// Kartu angka = StatTile bersama (2026-11-06). Label & angka boleh turun baris — dulu dipotong
// ("PCS NETO …") di HP. `break-words` diwariskan ke angka sehingga "Rp 12.345.678" tidak meluber.
function Stat({ label, value, accent, className = '' }) {
  return <StatTile label={label} value={value} accent={accent} className={`px-3 py-2 min-w-0 break-words ${className}`} />;
}

// Lokasi asal: yang MENYIMPAN barang jadi tampil lebih dulu (dulu ruang aksesoris dll. di atas).
const fgFirst = (list) => [...list.filter((l) => Number(l.fg_qty) > 0), ...list.filter((l) => !(Number(l.fg_qty) > 0))];
const locLabel = (l) => `${l.code}${l.name ? ` · ${l.name}` : ''} · ${num(l.fg_qty)} pcs barang jadi`;

function Banner({ tone = 'red', children, testId }) {
  const cls = tone === 'red'
    ? 'bg-[hsl(var(--destructive)/0.1)]  border-[hsl(var(--destructive)/0.35)]  text-[hsl(var(--destructive))] '
    : tone === 'green'
      ? 'bg-[hsl(var(--success)/0.1)]  border-[hsl(var(--success)/0.35)]  text-[hsl(var(--success))] '
      : 'bg-[hsl(var(--warning)/0.1)]  border-[hsl(var(--warning)/0.35)]  text-[hsl(var(--warning))] ';
  return <div className={`rounded-lg border px-3 py-2 text-xs ${cls}`} data-testid={testId}>{children}</div>;
}

// ─── Tab Scan ────────────────────────────────────────────────────────────────
function ScanTab({ token }) {
  const authH = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);
  const jsonH = useMemo(() => ({ ...authH, 'Content-Type': 'application/json' }), [authH]);
  const [locations, setLocations] = useState([]);
  const [stores, setStores] = useState([]);
  const [loc, setLoc] = useState(lsGet(LS_LOC));
  const [store, setStore] = useState(lsGet(LS_STORE));
  const [mode, setMode] = useState('scan');          // 'scan' | 'batal_kirim'
  const [mult, setMult] = useState(1);
  const [data, setData] = useState(null);
  const [last, setLast] = useState(null);            // {tone, text}
  const [inflight, setInflight] = useState(0);
  const [failed, setFailed] = useState(loadUnsent);  // scan yang gagal terkirim (bisa dikirim ulang, id sama)
  const [busy, setBusy] = useState(false);
  const refreshT = useRef(null);

  const loadToday = useCallback(async () => {
    if (!loc) { setData(null); return; }
    try {
      const r = await fetch(`${API}/today?location_id=${encodeURIComponent(loc)}`, { headers: authH });
      if (r.ok) setData(await r.json());
    } catch (e) { console.error(e); }
  }, [loc, authH]);

  useEffect(() => {
    (async () => {
      try {
        const [a, b] = await Promise.all([
          fetch(`${API}/locations`, { headers: authH }), fetch(`${API}/stores`, { headers: authH })]);
        if (a.ok) setLocations(await a.json());
        if (b.ok) setStores(await b.json());
      } catch (e) { console.error(e); }
    })();
  }, [authH]);
  useEffect(() => { loadToday(); }, [loadToday]);
  useEffect(() => { saveUnsent(failed); }, [failed]);

  const scheduleRefresh = () => {
    clearTimeout(refreshT.current);
    refreshT.current = setTimeout(loadToday, 700);
  };
  useEffect(() => () => clearTimeout(refreshT.current), []);

  const send = async (payload) => {
    setInflight((n) => n + 1);
    try {
      let r;
      for (let attempt = 0; attempt < 2; attempt += 1) {
        try {
          r = await fetch(`${API}/scan`, { method: 'POST', headers: jsonH, body: JSON.stringify(payload) });
          break;
        } catch (netErr) {
          if (attempt === 1) throw netErr;
          await new Promise((res) => setTimeout(res, 800));   // kirim ulang dengan id yang SAMA
        }
      }
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        scanFeedback('error');
        setLast({ tone: 'red', text: d.detail || `Scan gagal (${r.status})`,
          detail: r.status >= 500 ? RESEND_HINT : undefined });
        if (r.status >= 500) setFailed((f) => [...f.filter((x) => x.client_scan_id !== payload.client_scan_id), payload]);
        return;
      }
      setFailed((f) => f.filter((x) => x.client_scan_id !== payload.client_scan_id));
      if (d.result === 'rejected') {
        scanFeedback('error');
        setLast({ tone: 'red', text: `Ditolak: ${d.reject?.reason || 'kode tidak dikenal'}`, detail: payload.code });
      } else if (d.result === 'processing') {
        scanFeedback('dup');
        setLast({ tone: 'amber', text: 'Scan yang sama sedang diproses — tidak dihitung dua kali.' });
      } else {
        const ln = d.line || {};
        const red = (ln.flags || []).length > 0;
        scanFeedback(red ? 'dup' : 'ok');
        const verb = ln.kind === 'batal_kirim' ? 'Batal kirim' : 'Keluar';
        setLast({
          tone: red ? 'red' : 'green',
          text: `${verb} ${ln.sku} ×${ln.qty}${d.duplicate ? ' (sudah tercatat)' : ''}`,
          detail: red ? `${(ln.flags || []).map((f) => FLAG_LABEL[f] || f).join(', ')} — tetap tercatat.` : undefined,
        });
      }
      scheduleRefresh();
    } catch (e) {
      scanFeedback('error');
      setLast({ tone: 'red', text: `Jaringan putus — ${payload.code} ×${payload.multiplier} belum pasti tercatat.`, detail: RESEND_HINT });
      setFailed((f) => [...f.filter((x) => x.client_scan_id !== payload.client_scan_id), payload]);
    } finally {
      setInflight((n) => Math.max(0, n - 1));
    }
  };

  const onScan = (code) => {
    if (!loc) { scanFeedback('error'); setLast({ tone: 'red', text: 'Pilih lokasi asal dulu.' }); return; }
    const payload = { location_id: loc, code, client_scan_id: newScanId(), multiplier: mult, kind: mode, account_id: store };
    setMult(1);                                       // pengali berlaku untuk SATU scan (karton)
    send(payload);
  };

  // Antrean server: kirim ulang / batalkan baris yang gagal diproses (id baris sama → tidak dobel).
  const retryServer = async (ln) => {
    setBusy(true);
    try {
      const r = await fetch(`${API}/lines/${ln.id}/retry`, { method: 'POST', headers: jsonH });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { scanFeedback('error'); setLast({ tone: 'red', text: d.detail || 'Kirim ulang gagal', detail: RESEND_HINT }); }
      else { scanFeedback('ok'); setLast({ tone: 'green', text: `${ln.sku} ×${ln.qty} berhasil diproses ulang.` }); }
      await loadToday();
    } finally { setBusy(false); }
  };
  const discardServer = async (ln) => {
    setBusy(true);
    try {
      const r = await fetch(`${API}/lines/${ln.id}/discard`, { method: 'POST', headers: jsonH,
        body: JSON.stringify({ reason: 'scan gagal dibatalkan' }) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { scanFeedback('error'); setLast({ tone: 'red', text: d.detail || 'Gagal membatalkan' }); }
      else { setLast({ tone: 'amber', text: `Scan gagal ${ln.sku} ×${ln.qty} dibatalkan — langkah yang sempat terjadi dibalik.` }); }
      await loadToday();
    } finally { setBusy(false); }
  };

  const voidLine = async (ln) => {
    const reason = window.prompt(`Batalkan ${ln.sku} ×${ln.qty}? Stok kembali ke lokasi. Alasan:`, 'salah scan');
    if (reason === null) return;
    setBusy(true);
    try {
      const r = await fetch(`${API}/lines/${ln.id}/void`, { method: 'POST', headers: jsonH, body: JSON.stringify({ reason }) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { scanFeedback('error'); setLast({ tone: 'red', text: d.detail || 'Gagal membatalkan' }); }
      else { setLast({ tone: 'amber', text: `Baris ${ln.sku} ×${ln.qty} dibatalkan — stok kembali.` }); }
      await loadToday();
    } finally { setBusy(false); }
  };

  const closeSheet = async (sheet) => {
    const t = sheet.id === data?.open_sheet?.id ? (data?.open_totals || {}) : null;
    if (!window.confirm(`Tutup Hari ${sheet.number}?\n${t ? `${t.pcs} pcs neto · HPP ${rp(t.value)}\n` : ''}`
      + 'Sesudah ditutup: jurnal HPP dibuat, baris tidak bisa dibatalkan, scan berikutnya masuk lembar baru.')) return;
    setBusy(true);
    try {
      const r = await fetch(`${API}/sheets/${sheet.id}/close`, { method: 'POST', headers: authH });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) setLast({ tone: 'red', text: d.detail || 'Tutup Hari gagal' });
      else setLast({ tone: 'green', text: `${d.sheet?.number} ditutup${d.je?.je_number ? ` — jurnal ${d.je.je_number}` : ' (nilai 0, tanpa jurnal)'}.` });
      await loadToday();
    } finally { setBusy(false); }
  };

  const open = data?.open_sheet;
  const tot = data?.totals || {};
  const lines = data?.lines || [];
  const redLines = lines.filter((l) => l.status === 'active' && (l.flags || []).length);
  const locObj = locations.find((l) => l.id === loc);
  const locOptions = useMemo(() => fgFirst(locations), [locations]);
  // Hasil scan terakhir → ScanResult TEPAT di bawah kotak scan (testid lama `scan-out-last` dipertahankan).
  const lastResult = last ? { ...toScanResult(last), testId: 'scan-out-last' } : null;

  return (
    <div className="space-y-3" data-testid="scan-out-tab-scan">
      <GlassCard className="p-3 space-y-2" hover={false}>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <label className="block text-xs">
            <span className="flex items-center gap-1 text-muted-foreground mb-1"><MapPin className="w-3 h-3" /> Lokasi asal (wajib)</span>
            <SmartNativeSelect value={loc} data-testid="scan-out-location"
              onChange={(e) => { setLoc(e.target.value); lsSet(LS_LOC, e.target.value); }}
              className="w-full h-10 rounded-md border border-[var(--glass-border)] bg-[var(--glass-bg)] px-2 text-sm">
              <option value="">— pilih lokasi —</option>
              {locOptions.map((l) => (
                <option key={l.id} value={l.id}>{locLabel(l)}</option>
              ))}
            </SmartNativeSelect>
          </label>
          <label className="block text-xs">
            <span className="flex items-center gap-1 text-muted-foreground mb-1"><Store className="w-3 h-3" /> Toko (opsional)</span>
            <SmartNativeSelect value={store} data-testid="scan-out-store"
              onChange={(e) => { setStore(e.target.value); lsSet(LS_STORE, e.target.value); }}
              className="w-full h-10 rounded-md border border-[var(--glass-border)] bg-[var(--glass-bg)] px-2 text-sm">
              <option value="">Tanpa toko</option>
              {stores.map((s) => <option key={s.id} value={s.id}>{s.account_name} {s.platform ? `· ${s.platform}` : ''}</option>)}
            </SmartNativeSelect>
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-lg border border-[var(--glass-border)] p-0.5" data-testid="scan-out-mode">
            <button type="button" onClick={() => setMode('scan')}
              className={`px-3 py-1.5 rounded-md text-xs font-semibold ${mode === 'scan' ? 'bg-[hsl(var(--success))] text-white' : 'text-muted-foreground'}`}>
              Keluar
            </button>
            <button type="button" onClick={() => setMode('batal_kirim')} data-testid="scan-out-mode-cancel"
              className={`px-3 py-1.5 rounded-md text-xs font-semibold ${mode === 'batal_kirim' ? 'bg-[hsl(var(--warning))] text-white' : 'text-muted-foreground'}`}>
              Batal kirim
            </button>
          </div>
          <div className="inline-flex items-center gap-1" data-testid="scan-out-mult">
            <span className="text-[11px] text-muted-foreground">Pengali</span>
            {MULTS.map((m) => (
              <button key={m} type="button" onClick={() => setMult(m)}
                className={`min-w-[34px] px-2 py-1 rounded-md border text-xs font-semibold ${
                  mult === m ? 'border-[hsl(var(--primary))] text-[hsl(var(--primary))]' : 'border-[var(--glass-border)] text-muted-foreground'}`}>
                ×{m}
              </button>
            ))}
            <Input type="number" min={1} max={500} value={mult} data-testid="scan-out-mult-input"
              onChange={(e) => setMult(Math.max(1, Math.min(500, parseInt(e.target.value, 10) || 1)))}
              className="w-16 h-8 text-xs" />
          </div>
        </div>
        <div className={mode === 'batal_kirim' ? 'rounded-lg ring-2 ring-[hsl(var(--warning)/0.35)] p-1' : ''}>
          <UniversalScanner variant="inline" onScan={onScan} continuous keepFocus autoFocus disabled={!loc}
            placeholder={loc ? (mode === 'batal_kirim' ? 'Scan paket yang batal dikirim…' : 'Scan SKU barang keluar…') : 'Pilih lokasi dulu'}
            data-testid="scan-out-input" inputClassName="h-12 text-base" result={lastResult} />
        </div>
        {/* Scan gagal terkirim: TEPAT di bawah hasil scan, satu tombol "Kirim ulang" per baris (id scan sama →
            tidak dobel). Dulu hanya tautan kecil "Kirim ulang" di bawah teks keterangan. */}
        {failed.length > 0 && (
          <Banner tone="amber" testId="scan-out-failed">
            <div className="font-semibold">{failed.length} scan belum terkirim — jangan scan ulang barangnya.</div>
            <div className="mb-1">Tekan "Kirim ulang": scan yang sama dikirim lagi dan tidak dihitung dua kali.</div>
            <div className="divide-y divide-[hsl(var(--warning)/0.25)]">
              {failed.map((p) => (
                <div key={p.client_scan_id} className="flex items-center justify-between gap-2 py-1" data-testid="scan-out-failed-line">
                  <span className="tabular-nums break-all text-foreground">
                    {p.kind === 'batal_kirim' ? 'Batal kirim · ' : ''}{p.code} ×{p.multiplier}
                  </span>
                  <Button size="sm" variant="outline" className="shrink-0" data-testid="scan-out-resend"
                    onClick={() => { setFailed((f) => f.filter((x) => x.client_scan_id !== p.client_scan_id)); send(p); }}>
                    <RotateCw className="w-4 h-4" /> Kirim ulang
                  </Button>
                </div>
              ))}
            </div>
            {failed.length > 1 && (
              <Button size="sm" variant="outline" className="mt-1" data-testid="scan-out-resend-all"
                onClick={() => { const f = failed; setFailed([]); f.forEach(send); }}>
                <RotateCw className="w-4 h-4" /> Kirim ulang semua ({failed.length})
              </Button>
            )}
          </Banner>
        )}
        {(data?.retry_queue || []).length > 0 && (
          <Banner tone="amber" testId="scan-out-retry-queue">
            <div className="font-semibold">{data.retry_queue.length} scan tersimpan di server tetapi gagal diproses.</div>
            <div className="mb-1">Kirim ulang (tidak dihitung dua kali) atau batalkan bila memang salah scan. Selama masih ada, opname lokasi ini ditahan.</div>
            <div className="divide-y divide-[hsl(var(--warning)/0.25)]">
              {data.retry_queue.map((ln) => (
                <div key={ln.id} className="flex items-center justify-between gap-2 py-1" data-testid="scan-out-retry-line">
                  <span className="tabular-nums break-all text-foreground">
                    {ln.kind === 'batal_kirim' ? 'Batal kirim · ' : ''}{ln.sku} ×{ln.qty} · {ln.date}{ln.operator_name ? ` · ${ln.operator_name}` : ''}
                  </span>
                  <span className="flex items-center gap-1 shrink-0">
                    <Button size="sm" variant="outline" disabled={busy} onClick={() => retryServer(ln)} data-testid="scan-out-retry">
                      <RotateCw className="w-4 h-4" /> Kirim ulang
                    </Button>
                    <Button size="sm" variant="outline" disabled={busy} onClick={() => discardServer(ln)} data-testid="scan-out-discard">
                      <Undo2 className="w-4 h-4" /> Batalkan
                    </Button>
                  </span>
                </div>
              ))}
            </div>
          </Banner>
        )}
        <div className="text-[11px] text-muted-foreground">
          Khusus penjualan <b>marketplace</b>. Barang nota Portal Penjualan <b>tidak</b> di-scan di sini.
          {mult > 1 && <span className="ml-1 font-semibold text-[hsl(var(--primary))]">Scan berikutnya dihitung ×{mult} pcs.</span>}
          {inflight > 0 && <span className="ml-1">Mengirim {inflight}…</span>}
        </div>
        {data?.langkah2?.enabled_in_db && (
          <Banner tone="red">Setelan "Langkah 2" tersimpan ON di database — {data.langkah2.message}</Banner>
        )}
      </GlassCard>

      {(data?.other_open_sheets || []).length > 0 && (
        <Banner tone="amber" testId="scan-out-other-open">
          <div className="font-semibold mb-1">Lembar lain belum ditutup:</div>
          {data.other_open_sheets.map((s) => (
            <div key={s.id} className="flex items-center justify-between gap-2 py-0.5">
              <span className="truncate">{s.number} · {s.date}{s.post_error ? ` — ${s.post_error}` : ''}</span>
              {data.can_supervise && (
                <Button size="sm" variant="outline" disabled={busy} onClick={() => closeSheet(s)}>Tutup</Button>
              )}
            </div>
          ))}
        </Banner>
      )}

      {loc && (
        <GlassCard className="p-3 space-y-3" hover={false}>
          {/* Judul lembar boleh turun baris; tombol muat ulang menempel di sebelahnya (dulu sendirian satu baris di HP). */}
          <div className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <div className="text-xs text-muted-foreground">{data?.date} · {locObj?.code || ''}</div>
              <div className="font-semibold break-words" data-testid="scan-out-sheet">
                {open ? `${open.number} — terbuka` : 'Belum ada scan hari ini (lembar dibuat otomatis saat scan pertama)'}
              </div>
              {open?.post_error && <div className="text-xs text-[hsl(var(--destructive))]">Tutup terakhir gagal: {open.post_error}</div>}
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <Button size="icon-sm" variant="outline" onClick={loadToday} title="Muat ulang" aria-label="Muat ulang"
                data-testid="scan-out-refresh">
                <RefreshCw className="w-4 h-4" />
              </Button>
              {open && data?.can_supervise && (
                <Button size="sm" disabled={busy} onClick={() => closeSheet(open)} data-testid="scan-out-close">
                  <Lock className="w-4 h-4 mr-1" /> Tutup hari
                </Button>
              )}
            </div>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            <Stat label="Pcs neto hari ini" value={num(tot.pcs)} accent="success" />
            <Stat label="Batal kirim" value={num(tot.pcs_cancel)} />
            <Stat label="HPP (WAC)" value={rp(tot.value)} className="col-span-2 sm:col-span-1" />
          </div>
          {(data?.per_sku || []).length > 0 && (
            <div className="flex flex-wrap gap-1.5" data-testid="scan-out-per-sku">
              {data.per_sku.slice(0, 12).map((s) => (
                <span key={s.sku} className="px-2 py-1 rounded-md bg-[var(--glass-bg)] border border-[var(--glass-border)] text-xs tabular-nums">
                  {s.sku} <b>{s.net}</b>
                </span>
              ))}
            </div>
          )}
        </GlassCard>
      )}

      {(redLines.length > 0 || (data?.rejects || []).length > 0) && (
        <GlassCard className="p-3 space-y-1" hover={false} data-testid="scan-out-red-list">
          <div className="text-xs font-semibold text-[hsl(var(--destructive))] flex items-center gap-1">
            <AlertTriangle className="w-3.5 h-3.5" /> Daftar merah hari ini
          </div>
          {redLines.map((l) => (
            <div key={l.id} className="text-xs flex justify-between gap-2">
              <span className="tabular-nums truncate">{l.sku} ×{l.qty}</span>
              <span className="text-[hsl(var(--destructive))] text-right">{(l.flags || []).map((f) => FLAG_LABEL[f] || f).join(', ')}</span>
            </div>
          ))}
          {(data?.rejects || []).map((j) => (
            <div key={j.id} className="text-xs flex justify-between gap-2">
              <span className="tabular-nums truncate">{j.code || '(kosong)'} </span>
              <span className="text-[hsl(var(--destructive))] text-right">{j.reason}</span>
            </div>
          ))}
        </GlassCard>
      )}

      {loc && (
        <GlassCard className="p-0 overflow-hidden" hover={false}>
          <div className="px-3 py-2 text-xs font-semibold border-b border-[var(--glass-border)]">Baris hari ini ({lines.length})</div>
          <div className="divide-y divide-[var(--glass-border)] max-h-[60vh] overflow-y-auto" data-testid="scan-out-lines">
            {lines.length === 0 && <div className="px-3 py-6 text-center text-xs text-muted-foreground">Belum ada scan.</div>}
            {lines.map((l) => {
              const voided = l.status !== 'active';
              const red = !voided && (l.flags || []).length > 0;
              const mayVoid = !voided && !l.locked && data?.can_scan
                && (data?.can_supervise || !l.operator_id || l.operator_id === data?.me?.id)
                && (data?.sheets || []).some((s) => s.id === l.sheet_id && s.status === 'open');
              return (
                <div key={l.id} data-testid="scan-out-line"
                  className={`px-3 py-2 flex items-center gap-2 text-xs ${red ? 'bg-[hsl(var(--destructive)/0.1)] ' : ''} ${voided ? 'opacity-50 line-through' : ''}`}>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      {l.kind === 'batal_kirim'
                        ? <span className="px-1.5 rounded bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]  font-semibold">BATAL</span>
                        : null}
                      <span className="tabular-nums font-semibold truncate">{l.sku}</span>
                      <span className="font-bold">×{l.qty}</span>
                    </div>
                    <div className="text-muted-foreground truncate">
                      {fmtTime(l.scanned_at)} · {l.operator_name || '-'}{l.store?.account_name ? ` · ${l.store.account_name}` : ''}
                      {l.status === 'active' ? ` · ${rp(l.value)}` : ` · dibatalkan (${l.void_reason || '-'})`}
                    </div>
                    {red && <div className="text-[hsl(var(--destructive))] ">{(l.flags || []).map((f) => FLAG_LABEL[f] || f).join(', ')}</div>}
                  </div>
                  {mayVoid && (
                    <Button size="sm" variant="ghost" disabled={busy} onClick={() => voidLine(l)} title="Batalkan baris"
                      data-testid="scan-out-void">
                      <Undo2 className="w-4 h-4" />
                    </Button>
                  )}
                  {l.locked && <Lock className="w-3.5 h-3.5 text-muted-foreground" title="Sudah ditutup" />}
                </div>
              );
            })}
          </div>
        </GlassCard>
      )}
    </div>
  );
}

// ─── Tab Laporan Harian ──────────────────────────────────────────────────────
function Table({ head, rows, testId, empty = 'Tidak ada data.' }) {
  return (
    <div className="overflow-x-auto" data-testid={testId}>
      <table className="w-full text-xs">
        <thead><tr className="text-left text-muted-foreground">{head.map((h) => <th key={h} className="px-2 py-1 font-medium whitespace-nowrap">{h}</th>)}</tr></thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={head.length} className="px-2 py-3 text-center text-muted-foreground">{empty}</td></tr>}
          {rows.map((r, i) => (
            <tr key={i} className={`border-t border-[var(--glass-border)] ${r.red ? 'text-[hsl(var(--destructive))] ' : ''}`}>
              {r.cells.map((c, j) => <td key={j} className="px-2 py-1 whitespace-nowrap">{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReportTab({ token }) {
  const authH = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);
  const [day, setDay] = useState(todayWIB);
  const [locations, setLocations] = useState([]);
  const [loc, setLoc] = useState('');
  const [rep, setRep] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch(`${API}/locations`, { headers: authH }).then((r) => (r.ok ? r.json() : [])).then(setLocations).catch(() => {});
  }, [authH]);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams({ date: day, ...(loc ? { location_id: loc } : {}) });
      const r = await fetch(`${API}/report?${qs}`, { headers: authH });
      setRep(r.ok ? await r.json() : null);
    } finally { setLoading(false); }
  }, [day, loc, authH]);
  useEffect(() => { load(); }, [load]);

  const s = rep?.summary || {};
  const ctl = rep?.control || {};
  return (
    <div className="space-y-3" data-testid="scan-out-tab-report">
      <div className="flex flex-wrap items-end gap-2">
        <Input type="date" value={day} onChange={(e) => setDay(e.target.value)} className="w-40 h-9" data-testid="scan-out-report-date" />
        <SmartNativeSelect value={loc} onChange={(e) => setLoc(e.target.value)}
          className="h-9 rounded-md border border-[var(--glass-border)] bg-[var(--glass-bg)] px-2 text-sm min-w-[160px]">
          <option value="">Semua lokasi</option>
          {locations.map((l) => <option key={l.id} value={l.id}>{l.code} {l.name ? `· ${l.name}` : ''}</option>)}
        </SmartNativeSelect>
        <Button size="sm" variant="outline" onClick={load} disabled={loading}><RefreshCw className="w-4 h-4" /></Button>
        <Button size="sm" variant="outline" disabled={!rep}
          onClick={() => downloadCsv(`scan-keluar-${day}`, ['SKU', 'Nama', 'Keluar', 'Batal kirim', 'Neto', 'HPP (WAC)'],
            (rep?.per_sku || []).map((r) => [r.sku, r.name, r.out, r.cancel, r.net, r.value]))}>
          <FileDown className="w-4 h-4 mr-1" /> CSV
        </Button>
      </div>
      {rep && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <Stat label="Pcs neto" value={num(s.pcs)} />
            <Stat label="HPP (WAC)" value={rp(s.value)} />
            <Stat label="SKU" value={num(s.skus)} />
            <Stat label="Impor vs scan" value={`${num(ctl.today?.import_pcs)} / ${num(ctl.today?.scan_pcs)}`}
              accent={ctl.today?.flag ? 'danger' : undefined} />
          </div>
          <GlassCard className="p-3 space-y-1" hover={false}>
            <div className="text-xs font-semibold">Lembar</div>
            {(rep.sheets || []).length === 0 && <div className="text-xs text-muted-foreground">Tidak ada lembar.</div>}
            {(rep.sheets || []).map((sh) => (
              <div key={sh.id} className="text-xs flex flex-wrap justify-between gap-2">
                <span className="tabular-nums">{sh.number}</span>
                <span>{sh.status === 'closed' ? `ditutup${sh.auto_closed ? ' otomatis' : ''} · ${sh.je_number || sh.je_note || '-'}` : 'TERBUKA'}</span>
              </div>
            ))}
          </GlassCard>
          <GlassCard className="p-3 space-y-2" hover={false}>
            <div className="text-xs font-semibold">Per SKU</div>
            <Table testId="scan-out-report-sku" head={['SKU', 'Keluar', 'Batal', 'Neto', 'HPP']}
              rows={(rep.per_sku || []).map((r) => ({ red: r.negative_lines > 0, cells: [r.sku, r.out, r.cancel, r.net, rp(r.value)] }))} />
          </GlassCard>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <GlassCard className="p-3 space-y-2" hover={false}>
              <div className="text-xs font-semibold">Per toko</div>
              <Table head={['Toko', 'Neto', 'HPP']} rows={(rep.per_store || []).map((r) => ({ cells: [r.account_name, r.net, rp(r.value)] }))} />
            </GlassCard>
            <GlassCard className="p-3 space-y-2" hover={false}>
              <div className="text-xs font-semibold">Per petugas</div>
              <Table head={['Petugas', 'Scan', 'Neto']} rows={(rep.per_operator || []).map((r) => ({ cells: [r.operator, r.scans, r.net] }))} />
            </GlassCard>
          </div>
          <GlassCard className="p-3 space-y-2" hover={false} data-testid="scan-out-report-nota">
            <div className="text-xs font-semibold">Keluar via nota Portal Penjualan (pembanding — tidak di-scan, tidak dijumlah)</div>
            <Table head={['SKU', 'Pcs', 'Nota']} empty="Tidak ada nota hari ini."
              rows={(rep.direct_sales?.per_sku || []).map((r) => ({ cells: [r.sku, r.pcs, (r.notes || []).join(', ')] }))} />
            {(rep.direct_sales?.overlap_with_scan || []).length > 0 && (
              <Banner tone="amber">SKU ini keluar lewat nota DAN ter-scan hari ini — pastikan barang nota tidak ikut di-scan:{' '}
                {rep.direct_sales.overlap_with_scan.map((r) => r.sku).join(', ')}</Banner>
            )}
          </GlassCard>
          <GlassCard className="p-3 space-y-2" hover={false}>
            <div className="text-xs font-semibold">Retur diputuskan gudang hari ini</div>
            <Table head={['Kode', 'SKU', 'Keputusan', 'Qty']} empty="Tidak ada retur."
              rows={(rep.returns_received || []).map((r) => ({ cells: [r.return_code, r.sku, r.action, r.restock_qty || r.qty] }))} />
          </GlassCard>
          <GlassCard className="p-3 space-y-2" hover={false}>
            <div className="text-xs font-semibold text-[hsl(var(--destructive))] ">Pengecualian</div>
            <Table head={['Jam', 'Kode/SKU', 'Keterangan']} empty="Tidak ada."
              rows={[
                ...(rep.rejects || []).map((j) => ({ red: true, cells: [fmtTime(j.at), j.code, `Ditolak: ${j.reason}`] })),
                ...(rep.flagged || []).map((l) => ({ red: true, cells: [fmtTime(l.scanned_at), `${l.sku} ×${l.qty}`, (l.flags || []).map((f) => FLAG_LABEL[f] || f).join(', ')] })),
                ...(rep.voided || []).map((l) => ({ cells: [fmtTime(l.voided_at), `${l.sku} ×${l.qty}`, `Dibatalkan oleh ${l.voided_by || '-'}: ${l.void_reason || '-'}`] })),
              ]} />
          </GlassCard>
        </>
      )}
    </div>
  );
}

// ─── Tab Kontrol vs Impor ────────────────────────────────────────────────────
function ControlTab({ token, canSupervise }) {
  const authH = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);
  const jsonH = useMemo(() => ({ ...authH, 'Content-Type': 'application/json' }), [authH]);
  const [day, setDay] = useState(() => daysAgoWIB(1));
  const [ctl, setCtl] = useState(null);
  const [cfg, setCfg] = useState(null);
  const [msg, setMsg] = useState('');

  const load = useCallback(async () => {
    const r = await fetch(`${API}/control?date=${day}`, { headers: authH });
    if (r.ok) { const d = await r.json(); setCtl(d); setCfg(d.settings); }
  }, [day, authH]);
  useEffect(() => { load(); }, [load]);

  const review = async (d) => {
    const note = window.prompt(`Tandai selisih ${d} sudah diperiksa. Catatan:`, '');
    if (note === null) return;
    const r = await fetch(`${API}/control/${d}/review`, { method: 'POST', headers: jsonH, body: JSON.stringify({ note }) });
    setMsg(r.ok ? `Selisih ${d} ditandai sudah diperiksa.` : 'Gagal menandai.');
    load();
  };
  const saveCfg = async () => {
    const r = await fetch(`${API}/settings`, { method: 'PUT', headers: jsonH, body: JSON.stringify(cfg) });
    const d = await r.json().catch(() => ({}));
    setMsg(r.ok ? 'Ambang disimpan.' : (d.detail || 'Gagal menyimpan ambang.'));
    load();
  };

  const cum = ctl?.cumulative || {};
  return (
    <div className="space-y-3" data-testid="scan-out-tab-control">
      <div className="flex flex-wrap items-end gap-2">
        <Input type="date" value={day} onChange={(e) => setDay(e.target.value)} className="w-40 h-9" data-testid="scan-out-control-date" />
        <Button size="sm" variant="outline" onClick={load}><RefreshCw className="w-4 h-4" /></Button>
      </div>
      {msg && <Banner tone="green">{msg}</Banner>}
      {ctl && (
        <>
          <div className="grid grid-cols-3 gap-2">
            <Stat label={`Impor ${ctl.days} hr`} value={num(cum.import_pcs)} />
            <Stat label={`Scan ${ctl.days} hr`} value={num(cum.scan_pcs)} />
            <Stat label="Selisih kumulatif" value={num(cum.gap)} accent={cum.flag ? 'danger' : undefined} />
          </div>
          <GlassCard className="p-3" hover={false}>
            <Table testId="scan-out-control-rows" head={['Tanggal', 'Impor', 'basis pesanan', 'Scan', 'Selisih', 'Kumulatif', '']}
              rows={(ctl.rows || []).map((r) => ({
                red: r.flag,
                cells: [r.date, r.import_pcs, r.import_pcs_order || '', r.scan_pcs, r.gap, r.cum_gap,
                  r.review?.status === 'reviewed'
                    ? <span className="inline-flex items-center gap-1 text-[hsl(var(--success))]"><CheckCircle2 className="w-3 h-3" />diperiksa</span>
                    : (r.flag && canSupervise
                      ? <button type="button" className="underline" onClick={() => review(r.date)}>Tandai diperiksa</button> : ''),
                ],
              }))} />
          </GlassCard>
          <GlassCard className="p-3 space-y-2" hover={false}>
            <div className="text-xs font-semibold">Per SKU {ctl.sku_day} (item impor tertaut master FG)</div>
            <Table head={['SKU', 'Impor', 'Scan', 'Selisih']} empty="Tidak ada."
              rows={(ctl.per_sku || []).map((r) => ({ red: r.gap !== 0, cells: [r.sku, r.import_pcs, r.scan_pcs, r.gap] }))} />
            {(ctl.rows || []).slice(-1)[0]?.unlinked_pcs > 0 && (
              <div className="text-xs text-muted-foreground">Tak tertaut master FG: {ctl.rows.slice(-1)[0].unlinked_pcs} pcs.</div>
            )}
          </GlassCard>
          <GlassCard className="p-3 space-y-1 text-[11px] text-muted-foreground" hover={false}>
            {(ctl.data_notes || []).map((n) => <div key={n}>• {n}</div>)}
          </GlassCard>
          {canSupervise && cfg && (
            <GlassCard className="p-3 flex flex-wrap items-end gap-2" hover={false}>
              <label className="text-xs">Ambang pcs
                <Input type="number" min={1} value={cfg.control_gap_pcs} className="w-24 h-8"
                  onChange={(e) => setCfg({ ...cfg, control_gap_pcs: e.target.value })} />
              </label>
              <label className="text-xs">Ambang %
                <Input type="number" min={0} max={100} value={cfg.control_gap_pct} className="w-24 h-8"
                  onChange={(e) => setCfg({ ...cfg, control_gap_pct: e.target.value })} />
              </label>
              <Button size="sm" variant="outline" onClick={saveCfg}><Scale className="w-4 h-4 mr-1" /> Simpan ambang</Button>
            </GlassCard>
          )}
        </>
      )}
    </div>
  );
}

export default function WHScanOutModule({ token, user, initialTab }) {
  const [tab, setTab] = useState(['scan', 'report', 'control'].includes(initialTab) ? initialTab : 'scan');
  const role = (user?.role || '').toLowerCase();
  const canSupervise = !['tim_packing', 'admin_aksesoris'].includes(role);
  return (
    <PageLayout testId="wh-scan-out-module" title="Scan keluar penjualan"
      subtitle="Barang marketplace keluar gudang: stok & HPP (WAC) dipotong per scan, jurnal saat tutup hari.">
      <div className="inline-flex rounded-lg border border-[var(--glass-border)] bg-[var(--glass-bg)] p-1 w-full">
        <Tab active={tab === 'scan'} onClick={() => setTab('scan')} icon={ScanLine} testId="scan-out-tabbtn-scan">Scan</Tab>
        <Tab active={tab === 'report'} onClick={() => setTab('report')} icon={ClipboardList} testId="scan-out-tabbtn-report">Laporan</Tab>
        <Tab active={tab === 'control'} onClick={() => setTab('control')} icon={Scale} testId="scan-out-tabbtn-control">Kontrol</Tab>
      </div>
      {tab === 'scan' && <ScanTab token={token} />}
      {tab === 'report' && <ReportTab token={token} />}
      {tab === 'control' && <ControlTab token={token} canSupervise={canSupervise} />}
    </PageLayout>
  );
}

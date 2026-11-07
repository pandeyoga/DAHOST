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
 *
 * Standar UI/UX v2 (8 Nov 2026): tab = HubTabs (dulu deret tombol buatan), tombol mode/pengali = Button,
 * konfirmasi & alasan = confirmDialog (dulu window.confirm/prompt), tanggal = DatePicker, semua tabel laporan =
 * TabelData + unduh Excel/CSV, kotak pemberitahuan = Notice. Daftar baris scan hari ini sengaja tetap baris
 * ringkas (bukan kartu) karena layar ini dipakai di HP sambil men-scan.
 */
import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import {
  MapPin, Store, Lock, AlertTriangle, RefreshCw, Undo2, Scale, CheckCircle2, RotateCw,
} from 'lucide-react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { GlassCard } from '@/components/ui/glass';
import { formatRupiah, formatNumber } from '@/lib/format';
import { todayWIB, daysAgoWIB } from '@/lib/waktu';
import UniversalScanner from './scanner/UniversalScanner';
import { scanFeedback } from './scanner/scanCode';
import { toScanResult } from './scanner/ScanResult';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile } from './moduleAtoms';
import HubTabs from './hubs/HubTabs';
import DatePicker from '@/components/ui/date-picker';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { confirmDialog } from '@/components/ui/confirm-dialog';

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

// Kartu angka = StatTile bersama (2026-11-06). Label & angka boleh turun baris — dulu dipotong
// ("PCS NETO …") di HP. `break-words` diwariskan ke angka sehingga "Rp 12.345.678" tidak meluber.
function Stat({ label, value, accent, className = '' }) {
  return <StatTile label={label} value={value} accent={accent} className={`px-3 py-2 min-w-0 break-words ${className}`} />;
}

// Lokasi asal: yang MENYIMPAN barang jadi tampil lebih dulu (dulu ruang aksesoris dll. di atas).
const fgFirst = (list) => [...list.filter((l) => Number(l.fg_qty) > 0), ...list.filter((l) => !(Number(l.fg_qty) > 0))];
const locLabel = (l) => `${l.code}${l.name ? ` · ${l.name}` : ''} · ${num(l.fg_qty)} pcs barang jadi`;

// Kotak pemberitahuan = Notice bersama (dulu kotak berwarna buatan sendiri).
function Banner({ tone = 'red', children, testId }) {
  const nada = tone === 'red' ? 'danger' : tone === 'green' ? 'success' : 'warning';
  return <Notice tone={nada} testId={testId}>{children}</Notice>;
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
    const reason = await confirmDialog({
      title: `Batalkan ${ln.sku} ×${ln.qty}?`, body: 'Stok kembali ke lokasi.', confirmLabel: 'Batalkan baris', danger: true,
      input: { label: 'Alasan', value: 'salah scan' },
    });
    if (reason === false || reason === null) return;
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
    const ok = await confirmDialog({
      title: `Tutup hari ${sheet.number}?`,
      body: `${t ? `${t.pcs} pcs neto · HPP ${rp(t.value)}. ` : ''}`
        + 'Sesudah ditutup: jurnal HPP dibuat, baris tidak bisa dibatalkan, scan berikutnya masuk lembar baru.',
      confirmLabel: 'Tutup hari',
    });
    if (!ok) return;
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
        <div className="flex flex-wrap gap-3">
          <label className="block w-full text-xs sm:w-80">
            <span className="mb-1 flex items-center gap-1 text-sm text-muted-foreground"><MapPin className="w-3 h-3" /> Lokasi asal (wajib)</span>
            <SmartNativeSelect value={loc} data-testid="scan-out-location"
              onChange={(e) => { setLoc(e.target.value); lsSet(LS_LOC, e.target.value); }}
              className="w-full h-10 rounded-md border border-[var(--glass-border)] bg-[var(--glass-bg)] px-2 text-sm">
              <option value="">Pilih lokasi</option>
              {locOptions.map((l) => (
                <option key={l.id} value={l.id}>{locLabel(l)}</option>
              ))}
            </SmartNativeSelect>
          </label>
          <label className="block w-full text-xs sm:w-72">
            <span className="mb-1 flex items-center gap-1 text-sm text-muted-foreground"><Store className="w-3 h-3" /> Toko (opsional)</span>
            <SmartNativeSelect value={store} data-testid="scan-out-store"
              onChange={(e) => { setStore(e.target.value); lsSet(LS_STORE, e.target.value); }}
              className="w-full h-10 rounded-md border border-[var(--glass-border)] bg-[var(--glass-bg)] px-2 text-sm">
              <option value="">Tanpa toko</option>
              {stores.map((s) => <option key={s.id} value={s.id}>{s.account_name} {s.platform ? `· ${s.platform}` : ''}</option>)}
            </SmartNativeSelect>
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex items-center gap-1" role="group" aria-label="Jenis scan" data-testid="scan-out-mode">
            <Button type="button" size="sm" variant={mode === 'scan' ? 'success' : 'outline'} aria-pressed={mode === 'scan'}
              onClick={() => setMode('scan')}>
              Keluar
            </Button>
            <Button type="button" size="sm" variant={mode === 'batal_kirim' ? 'default' : 'outline'} aria-pressed={mode === 'batal_kirim'}
              onClick={() => setMode('batal_kirim')} data-testid="scan-out-mode-cancel">
              Batal kirim
            </Button>
          </div>
          <div className="inline-flex flex-wrap items-center gap-1" role="group" aria-label="Pengali" data-testid="scan-out-mult">
            <span className="text-xs text-muted-foreground">Pengali</span>
            {MULTS.map((m) => (
              <Button key={m} type="button" size="sm" variant={mult === m ? 'default' : 'outline'} aria-pressed={mult === m}
                onClick={() => setMult(m)} className="min-w-[2.5rem] px-2">
                ×{m}
              </Button>
            ))}
            <Input type="number" min={1} max={500} value={mult} data-testid="scan-out-mult-input" aria-label="Pengali lain"
              onChange={(e) => setMult(Math.max(1, Math.min(500, parseInt(e.target.value, 10) || 1)))}
              className="h-8 w-16 text-sm" />
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
        <div className="text-xs text-muted-foreground">
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
          <div className="flex items-center gap-1 text-sm font-semibold text-[hsl(var(--danger-text))]">
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
          <div className="flex items-center justify-between gap-2 border-b border-[var(--glass-border)] px-3 py-2">
            <span className="text-sm font-semibold">Baris hari ini ({lines.length})</span>
            <TombolUnduh namaBerkas={`scan-keluar-baris-${data?.date || todayWIB()}`} namaLembar="Baris scan" baris={lines}
              testId="scan-out-lines-unduh" kolom={[
                { label: 'Jam', nilai: (l) => fmtTime(l.scanned_at) },
                { label: 'Jenis', nilai: (l) => (l.kind === 'batal_kirim' ? 'Batal kirim' : 'Keluar') },
                { label: 'SKU', nilai: (l) => l.sku },
                { label: 'Qty', nilai: (l) => Number(l.qty || 0) },
                { label: 'HPP (WAC)', nilai: (l) => Number(l.value || 0) },
                { label: 'Petugas', nilai: (l) => l.operator_name || '' },
                { label: 'Toko', nilai: (l) => l.store?.account_name || '' },
                { label: 'Status', nilai: (l) => (l.status === 'active' ? 'Aktif' : `Dibatalkan (${l.void_reason || '-'})`) },
                { label: 'Catatan', nilai: (l) => (l.flags || []).map((f) => FLAG_LABEL[f] || f).join(', ') },
              ]} />
          </div>
          <div className="divide-y divide-[var(--glass-border)] max-h-[60vh] overflow-y-auto" data-testid="scan-out-lines">
            {lines.length === 0 && <EmptyState className="py-6" title="Belum ada scan hari ini" description="Scan pertama membuat lembar hari ini otomatis." />}
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
                        ? <span className="rounded px-1.5 font-semibold bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning-text))]">Batal</span>
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
                    <Button size="icon-sm" variant="ghost" disabled={busy} onClick={() => voidLine(l)} title="Batalkan baris"
                      aria-label="Batalkan baris" data-testid="scan-out-void">
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
/**
 * Tabel laporan kecil = TabelData (kartu ringkas di HP) + unduh Excel/CSV di sebelah judulnya.
 * kolom: [{ label, nilai: (r) => nilai mentah untuk unduhan, isi?: (r) => tampilan, rata? }]
 */
function TabelLaporan({ judul, kolom, baris, namaBerkas, kosong = 'Tidak ada data.', testId, merah, judulCls = '' }) {
  const kol = kolom.map((k, i) => ({
    kunci: `k${i}`, label: k.label, rata: k.rata, hp: k.hp !== undefined ? k.hp : (i === 0 ? 'judul' : 'nilai'),
    isi: (r) => {
      const v = k.isi ? k.isi(r) : k.nilai(r);
      return merah && merah(r) && i === 0 ? <span className="text-[hsl(var(--danger-text))]">{v}</span> : v;
    },
  }));
  return (
    <GlassCard className="space-y-2 p-3" hover={false} data-testid={testId}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className={`text-sm font-semibold ${judulCls}`}>{judul}</div>
        <TombolUnduh namaBerkas={namaBerkas} namaLembar={String(judul).slice(0, 31)} baris={baris}
          kolom={kolom.map((k) => ({ label: k.label, nilai: k.nilai }))} testId={testId ? `${testId}-unduh` : undefined} />
      </div>
      <TabelData kolom={kol} baris={baris} kunci={(r) => r._k} testId={testId ? `${testId}-tabel` : undefined}
        kosong={<p className="py-3 text-center text-sm text-muted-foreground">{kosong}</p>} />
    </GlassCard>
  );
}
const berkunci = (list) => (list || []).map((r, i) => ({ ...r, _k: `${i}-${r.id || r.sku || r.date || ''}` }));

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
  const pengecualian = berkunci([
    ...(rep?.rejects || []).map((j) => ({ red: true, jam: fmtTime(j.at), kode: j.code, ket: `Ditolak: ${j.reason}` })),
    ...(rep?.flagged || []).map((l) => ({ red: true, jam: fmtTime(l.scanned_at), kode: `${l.sku} ×${l.qty}`, ket: (l.flags || []).map((f) => FLAG_LABEL[f] || f).join(', ') })),
    ...(rep?.voided || []).map((l) => ({ jam: fmtTime(l.voided_at), kode: `${l.sku} ×${l.qty}`, ket: `Dibatalkan oleh ${l.voided_by || '-'}: ${l.void_reason || '-'}` })),
  ]);
  return (
    <PageLayout testId="scan-out-tab-report" title="Laporan scan keluar"
      subtitle="Ringkasan per SKU, toko, dan petugas untuk satu hari."
      filters={<>
        <div className="w-full sm:w-44"><DatePicker value={day} onChange={(v) => setDay(v || todayWIB())} bolehKosong={false}
          testId="scan-out-report-date" /></div>
        <SmartNativeSelect value={loc} onChange={(e) => setLoc(e.target.value)} className="w-full" wrapperClassName="w-full sm:w-52" aria-label="Lokasi">
          <option value="">Semua lokasi</option>
          {locations.map((l) => <option key={l.id} value={l.id}>{l.code} {l.name ? `· ${l.name}` : ''}</option>)}
        </SmartNativeSelect>
      </>}
      tools={
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      }
      summary={rep ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Pcs neto" value={num(s.pcs)} />
          <Stat label="HPP (WAC)" value={rp(s.value)} />
          <Stat label="SKU" value={num(s.skus)} />
          <Stat label="Impor vs scan (pcs)" value={`${num(ctl.today?.import_pcs)} / ${num(ctl.today?.scan_pcs)}`}
            accent={ctl.today?.flag ? 'danger' : undefined} />
        </div>
      ) : null}>
      {!rep ? (
        <EmptyState title={loading ? 'Memuat laporan…' : 'Laporan belum tersedia'} description="Pilih tanggal lalu muat ulang." />
      ) : (
        <>
          <TabelLaporan judul="Lembar" namaBerkas={`scan-keluar-lembar-${day}`} kosong="Tidak ada lembar."
            baris={berkunci(rep.sheets)} kolom={[
              { label: 'Nomor', nilai: (sh) => sh.number },
              { label: 'Status', nilai: (sh) => (sh.status === 'closed' ? `Ditutup${sh.auto_closed ? ' otomatis' : ''}` : 'Terbuka') },
              { label: 'Jurnal', nilai: (sh) => (sh.status === 'closed' ? (sh.je_number || sh.je_note || '-') : '') },
            ]} />
          <TabelLaporan judul="Per SKU" testId="scan-out-report-sku" namaBerkas={`scan-keluar-${day}`}
            baris={berkunci(rep.per_sku)} merah={(r) => r.negative_lines > 0} kolom={[
              { label: 'SKU', nilai: (r) => r.sku },
              { label: 'Nama', nilai: (r) => r.name || '', hp: 'keterangan' },
              { label: 'Keluar', nilai: (r) => r.out, rata: 'kanan' },
              { label: 'Batal kirim', nilai: (r) => r.cancel, rata: 'kanan' },
              { label: 'Neto', nilai: (r) => r.net, rata: 'kanan' },
              { label: 'HPP (WAC)', nilai: (r) => Number(r.value || 0), isi: (r) => rp(r.value), rata: 'kanan' },
            ]} />
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <TabelLaporan judul="Per toko" namaBerkas={`scan-keluar-per-toko-${day}`} baris={berkunci(rep.per_store)} kolom={[
              { label: 'Toko', nilai: (r) => r.account_name },
              { label: 'Neto', nilai: (r) => r.net, rata: 'kanan' },
              { label: 'HPP', nilai: (r) => Number(r.value || 0), isi: (r) => rp(r.value), rata: 'kanan' },
            ]} />
            <TabelLaporan judul="Per petugas" namaBerkas={`scan-keluar-per-petugas-${day}`} baris={berkunci(rep.per_operator)} kolom={[
              { label: 'Petugas', nilai: (r) => r.operator },
              { label: 'Scan', nilai: (r) => r.scans, rata: 'kanan' },
              { label: 'Neto', nilai: (r) => r.net, rata: 'kanan' },
            ]} />
          </div>
          <TabelLaporan judul="Keluar via nota Portal Penjualan (pembanding — tidak di-scan, tidak dijumlah)"
            testId="scan-out-report-nota" namaBerkas={`scan-keluar-nota-${day}`} kosong="Tidak ada nota hari ini."
            baris={berkunci(rep.direct_sales?.per_sku)} kolom={[
              { label: 'SKU', nilai: (r) => r.sku },
              { label: 'Pcs', nilai: (r) => r.pcs, rata: 'kanan' },
              { label: 'Nota', nilai: (r) => (r.notes || []).join(', ') },
            ]} />
          {(rep.direct_sales?.overlap_with_scan || []).length > 0 && (
            <Banner tone="amber">SKU ini keluar lewat nota DAN ter-scan hari ini — pastikan barang nota tidak ikut di-scan:{' '}
              {rep.direct_sales.overlap_with_scan.map((r) => r.sku).join(', ')}</Banner>
          )}
          <TabelLaporan judul="Retur diputuskan gudang hari ini" namaBerkas={`scan-keluar-retur-${day}`} kosong="Tidak ada retur."
            baris={berkunci(rep.returns_received)} kolom={[
              { label: 'Kode', nilai: (r) => r.return_code },
              { label: 'SKU', nilai: (r) => r.sku },
              { label: 'Keputusan', nilai: (r) => r.action },
              { label: 'Qty', nilai: (r) => r.restock_qty || r.qty, rata: 'kanan' },
            ]} />
          <TabelLaporan judul="Pengecualian" judulCls="text-[hsl(var(--danger-text))]" namaBerkas={`scan-keluar-pengecualian-${day}`}
            kosong="Tidak ada." baris={pengecualian} merah={(r) => r.red} kolom={[
              { label: 'Jam', nilai: (r) => r.jam },
              { label: 'Kode/SKU', nilai: (r) => r.kode },
              { label: 'Keterangan', nilai: (r) => r.ket },
            ]} />
        </>
      )}
    </PageLayout>
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
    const note = await confirmDialog({
      title: `Tandai selisih ${d} sudah diperiksa?`, confirmLabel: 'Tandai diperiksa',
      input: { label: 'Catatan', value: 'Sudah diperiksa' },
    });
    if (note === false || note === null) return;
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
  const akhir = (ctl?.rows || []).slice(-1)[0];
  return (
    <PageLayout testId="scan-out-tab-control" title="Kontrol scan vs impor"
      subtitle="Pcs pesanan impor (tanggal kirim) dibanding pcs scan, per hari dan kumulatif."
      filters={<div className="w-full sm:w-44"><DatePicker value={day} onChange={(v) => setDay(v || daysAgoWIB(1))}
        bolehKosong={false} testId="scan-out-control-date" /></div>}
      tools={
        <Button variant="outline" size="icon" onClick={load} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw />
        </Button>
      }
      summary={<>
        {msg && <Banner tone="green">{msg}</Banner>}
        {ctl && (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label={`Impor ${ctl.days} hari (pcs)`} value={num(cum.import_pcs)} />
            <Stat label={`Scan ${ctl.days} hari (pcs)`} value={num(cum.scan_pcs)} />
            <Stat label="Selisih kumulatif" value={num(cum.gap)} accent={cum.flag ? 'danger' : undefined} />
          </div>
        )}
      </>}>
      {!ctl ? (
        <EmptyState title="Memuat kontrol…" description="Data kontrol impor vs scan sedang diambil." />
      ) : (
        <>
          <TabelLaporan judul="Per hari" testId="scan-out-control-rows" namaBerkas={`kontrol-scan-keluar-${day}`}
            baris={berkunci(ctl.rows)} merah={(r) => r.flag} kolom={[
              { label: 'Tanggal', nilai: (r) => r.date },
              { label: 'Impor', nilai: (r) => r.import_pcs, rata: 'kanan' },
              { label: 'Basis pesanan', nilai: (r) => r.import_pcs_order || '', rata: 'kanan', hp: false },
              { label: 'Scan', nilai: (r) => r.scan_pcs, rata: 'kanan' },
              { label: 'Selisih', nilai: (r) => r.gap, rata: 'kanan' },
              { label: 'Kumulatif', nilai: (r) => r.cum_gap, rata: 'kanan' },
              { label: 'Pemeriksaan', nilai: (r) => (r.review?.status === 'reviewed' ? 'Diperiksa' : ''),
                isi: (r) => (r.review?.status === 'reviewed'
                  ? <span className="inline-flex items-center gap-1 text-[hsl(var(--success-text))]"><CheckCircle2 className="w-3 h-3" />Diperiksa</span>
                  : (r.flag && canSupervise
                    ? <Button size="sm" variant="link" className="h-auto p-0" onClick={() => review(r.date)}>Tandai diperiksa</Button> : '')) },
            ]} />
          <TabelLaporan judul={`Per SKU ${ctl.sku_day || ''} (item impor tertaut master produk jadi)`}
            namaBerkas={`kontrol-scan-keluar-per-sku-${day}`} kosong="Tidak ada." baris={berkunci(ctl.per_sku)}
            merah={(r) => r.gap !== 0} kolom={[
              { label: 'SKU', nilai: (r) => r.sku },
              { label: 'Impor', nilai: (r) => r.import_pcs, rata: 'kanan' },
              { label: 'Scan', nilai: (r) => r.scan_pcs, rata: 'kanan' },
              { label: 'Selisih', nilai: (r) => r.gap, rata: 'kanan' },
            ]} />
          {akhir?.unlinked_pcs > 0 && (
            <p className="text-sm text-muted-foreground">Tak tertaut master produk jadi: {akhir.unlinked_pcs} pcs.</p>
          )}
          {(ctl.data_notes || []).length > 0 && (
            <Notice tone="info" title="Catatan data">
              <ul className="list-disc space-y-0.5 pl-4">{ctl.data_notes.map((n) => <li key={n}>{n}</li>)}</ul>
            </Notice>
          )}
          {canSupervise && cfg && (
            <GlassCard className="flex flex-wrap items-end gap-3 p-3" hover={false}>
              <label className="space-y-1 text-sm">
                <span className="block text-muted-foreground">Ambang pcs</span>
                <Input type="number" min={1} value={cfg.control_gap_pcs} className="h-9 w-24"
                  onChange={(e) => setCfg({ ...cfg, control_gap_pcs: e.target.value })} />
              </label>
              <label className="space-y-1 text-sm">
                <span className="block text-muted-foreground">Ambang %</span>
                <Input type="number" min={0} max={100} value={cfg.control_gap_pct} className="h-9 w-24"
                  onChange={(e) => setCfg({ ...cfg, control_gap_pct: e.target.value })} />
              </label>
              <Button variant="success" onClick={saveCfg}><Scale />Simpan ambang</Button>
            </GlassCard>
          )}
        </>
      )}
    </PageLayout>
  );
}

export default function WHScanOutModule({ token, user, initialTab }) {
  const [tab, setTab] = useState(['scan', 'report', 'control'].includes(initialTab) ? initialTab : 'scan');
  const role = (user?.role || '').toLowerCase();
  const canSupervise = !['tim_packing', 'admin_aksesoris'].includes(role);
  const tabs = useMemo(() => [
    { key: 'scan', label: 'Scan', Component: ScanTab },
    { key: 'report', label: 'Laporan', Component: ReportTab },
    { key: 'control', label: 'Kontrol', Component: ControlTab },
  ], []);
  return (
    <div data-testid="wh-scan-out-module">
      <HubTabs hubId="wh-scan-out" title="Scan keluar penjualan"
        subtitle="Barang marketplace keluar gudang: stok & HPP (WAC) dipotong per scan, jurnal saat tutup hari."
        tabs={tabs} value={tab} onValueChange={setTab} token={token} canSupervise={canSupervise} />
    </div>
  );
}

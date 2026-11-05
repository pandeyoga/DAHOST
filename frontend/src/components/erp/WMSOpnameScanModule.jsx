/**
 * WMSOpnameScanModule — layar "Sesi Opname" (mesin tunggal K9, `backend/core/opname_engine.py`).
 *
 * 2026-11-02 (keputusan owner K9): SATU layar untuk kain, aksesoris, dan barang jadi.
 *   - Gudang → Stok & Akurasi → Opname Stok (prop `kind` kosong);
 *   - Portal Aksesoris → Stok Opname (prop `kind="aksesoris"`, menu terpisah, mesin sama).
 * Alur: pilih LOKASI (wajib; opsional zona/rak/bin, jenis, daftar barang) → hitung BUTA (qty sistem
 * tidak tampil; baris belum dihitung ≠ 0) → ajukan (konfirmasi "anggap 0") → supervisor melihat
 * selisih (hitung − stok sistem saat dihitung, tanpa kunci) → approve: saldo ditimpa, penempatan
 * bin diperbarui, satu jurnal per sesi. Scan memakai scanner bersama (wedge + kamera kontinu).
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { IconButton } from './IconButton';
import {
  ScanLine, Plus, Check, X, ClipboardList, MapPin, AlertTriangle, PackageCheck, ArrowLeft,
  RefreshCw, ShieldCheck, ListChecks, Boxes, Printer, EyeOff, Archive, Minus,
} from 'lucide-react';
import useUomOptions from '@/hooks/useUomOptions';
import { UomSelect, UomConversionHint, baseUnitOf } from './uom/UomPicker';
import UniversalScanner from './scanner/UniversalScanner';
import { scanFeedback } from './scanner/scanCode';

const API = process.env.REACT_APP_BACKEND_URL || '';
const fmtNum = (v) => (v === null || v === undefined ? '—' : Number(v).toLocaleString('id-ID', { maximumFractionDigits: 4 }));
const fmtRp = (v) => 'Rp ' + Math.round(v || 0).toLocaleString('id-ID');
const STATUS_BADGE = {
  counting: 'bg-[hsl(var(--primary)/0.1)] text-[hsl(var(--primary))] border-[hsl(var(--primary)/0.2)]',
  submitted: 'bg-[hsl(var(--warning)/0.1)] text-[hsl(var(--warning))] border-[hsl(var(--warning)/0.2)]',
  approving: 'bg-[hsl(var(--warning)/0.1)] text-[hsl(var(--warning))] border-[hsl(var(--warning)/0.2)]',
  approved: 'bg-[hsl(var(--success)/0.1)] text-[hsl(var(--success))] border-[hsl(var(--success)/0.2)]',
  rejected: 'bg-[hsl(var(--destructive)/0.1)] text-[hsl(var(--destructive))] border-[hsl(var(--destructive)/0.2)]',
  cancelled: 'bg-muted text-muted-foreground border-[var(--glass-border)]',
};
const STATUS_LABEL = {
  counting: 'Menghitung', submitted: 'Menunggu Approval', approving: 'Diproses', approved: 'Disetujui',
  rejected: 'Ditolak', cancelled: 'Dibatalkan', open: 'Aktif (lama)', pending_approval: 'Menunggu (lama)',
};
const KIND_OPTS = [['bahan', 'Kain / Bahan'], ['aksesoris', 'Aksesoris'], ['fg', 'Barang Jadi']];
const LINE_STATUS = {
  belum: ['Belum dihitung', 'bg-muted text-muted-foreground border-[var(--glass-border)]'],
  dihitung: ['Dihitung', 'bg-[hsl(var(--success)/0.1)] text-[hsl(var(--success))] border-[hsl(var(--success)/0.2)]'],
  nol: ['Anggap 0', 'bg-[hsl(var(--warning)/0.1)] text-[hsl(var(--warning))] border-[hsl(var(--warning)/0.2)]'],
};
const selectCls = 'w-full border border-[var(--glass-border)] bg-[var(--input-surface)] rounded-lg px-3 py-2 text-sm text-foreground';

export default function WMSOpnameScanModule({ token, kind = '' }) {
  const [sessions, setSessions] = useState([]);
  const [locations, setLocations] = useState([]);
  const [view, setView] = useState(null);          // {session, lines, totals, blind, archived, result}
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);
  const [zeroList, setZeroList] = useState(null);  // daftar baris belum dihitung saat submit

  // form sesi baru
  const [showNew, setShowNew] = useState(false);
  const [locId, setLocId] = useState('');
  const [subType, setSubType] = useState('');
  const [subId, setSubId] = useState('');
  const [kinds, setKinds] = useState(kind ? [kind] : []);
  const [codes, setCodes] = useState('');

  // hitung
  const [ctxBin, setCtxBin] = useState({ id: '', label: '' });   // '' = lantai / belum dirak
  const [mode, setMode] = useState('add');                          // add = +qty per scan, set = ketik jumlah
  const [scanQty, setScanQty] = useState(1);
  const [scanUom, setScanUom] = useState('');
  const [lastScan, setLastScan] = useState(null);

  const authH = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);
  const jsonH = useMemo(() => ({ ...authH, 'Content-Type': 'application/json' }), [authH]);
  const flash = (type, text) => { setMessage({ type, text }); setTimeout(() => setMessage(null), 5000); };
  const errText = (d, fb) => (typeof d?.detail === 'string' ? d.detail : d?.detail?.message || fb);
  const focusItem = () => setTimeout(() => document.querySelector('[data-testid="opname-item-input"] input')?.focus(), 40);

  const loadSessions = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/wms/opname3/sessions${kind ? `?kind=${kind}` : ''}`, { headers: authH });
      if (r.ok) setSessions(await r.json());
    } catch (e) { console.error(e); }
  }, [authH, kind]);

  const loadLocations = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/wms/opname3/locations`, { headers: authH });
      if (r.ok) {
        const rows = await r.json();
        setLocations(rows);
        if (kind) { const pref = rows.find((l) => l.storage_role === kind && !l.quarantine); if (pref) setLocId(pref.id); }
      }
    } catch (e) { console.error(e); }
  }, [authH, kind]);

  const loadDetail = useCallback(async (id) => {
    try {
      const r = await fetch(`${API}/api/wms/opname3/sessions/${id}`, { headers: authH });
      const d = await r.json();
      if (r.ok) { setView(d); return d; }
      flash('error', errText(d, 'Gagal memuat sesi'));
    } catch (e) { console.error(e); }
    return null;
  }, [authH]);

  useEffect(() => {
    (async () => { setLoading(true); await Promise.all([loadSessions(), loadLocations()]); setLoading(false); })();
  }, [loadSessions, loadLocations]);

  const loc = locations.find((l) => l.id === locId);
  const subChoices = !loc ? [] : subType === 'zone' ? loc.zones.map((z) => [z.id, `${z.code} - ${z.name}`])
    : subType === 'rack' ? loc.racks.map((r) => [r.id, `${r.code} - ${r.name}`])
      : subType === 'bin' ? loc.bins.map((b) => [b.id, b.label]) : [];

  const sess = view?.session;
  const sessLoc = locations.find((l) => l.id === sess?.location_id);
  const isRak = sess?.level === 'rak';
  const ctxBins = useMemo(() => {
    if (!sessLoc) return [];
    const sub = sess?.sub_scope;
    return sessLoc.bins.filter((b) => !sub || (sub.type === 'zone' && b.zone_id === sub.id)
      || (sub.type === 'rack' && b.rack_id === sub.id) || (sub.type === 'bin' && b.id === sub.id));
  }, [sessLoc, sess]);

  const lastMatId = lastScan?.material_id;
  const { options: uomOpts } = useUomOptions(lastMatId ? [lastMatId] : []);
  const scanUomOpt = lastMatId ? uomOpts[lastMatId] : null;
  const scanBaseUnit = baseUnitOf(scanUomOpt, '');

  const printLocationLabel = async (id) => {
    try {
      const r = await fetch(`${API}/api/wms/locations/${id}/label-pdf`, { headers: authH });
      if (!r.ok) { const d = await r.json().catch(() => ({})); flash('error', errText(d, 'Gagal mencetak label')); return; }
      const url = URL.createObjectURL(await r.blob());
      window.open(url, '_blank');
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) { flash('error', e.message); }
  };

  const createSession = async () => {
    setBusy(true);
    try {
      const body = {
        location_id: locId, sub_scope_type: subType, sub_scope_id: subType ? subId : '', kinds,
        material_codes: codes.split(/[\s,;]+/).map((c) => c.trim()).filter(Boolean), source: kind || 'gudang',
      };
      const r = await fetch(`${API}/api/wms/opname3/sessions`, { method: 'POST', headers: jsonH, body: JSON.stringify(body) });
      const d = await r.json();
      if (r.ok) {
        setShowNew(false); setCodes(''); setSubType(''); setSubId('');
        await loadSessions(); await loadDetail(d.id); setCtxBin({ id: '', label: '' }); setLastScan(null);
        flash('success', `Sesi ${d.session_no} dibuat — ${d.lines} baris (${d.level === 'rak' ? 'hitung rak: penempatan saja' : 'hitung lokasi'}).`);
      } else flash('error', errText(d, 'Gagal membuat sesi'));
    } catch (e) { flash('error', e.message); } finally { setBusy(false); }
  };

  const openSession = async (s) => { await loadDetail(s.id); setCtxBin({ id: '', label: '' }); setLastScan(null); };
  const backToList = async () => { setView(null); setZeroList(null); await loadSessions(); };

  const pickBin = async (raw) => {
    const code = (raw || '').trim(); if (!code) return;
    try {
      const qs = new URLSearchParams({ barcode: code, session_id: sess.id });
      const r = await fetch(`${API}/api/wms/opname3/resolve-bin?${qs}`, { headers: authH });
      const d = await r.json();
      if (!r.ok) { scanFeedback('error'); flash('error', errText(d, `Kode "${code}" bukan bin/lokasi sesi ini`)); return; }
      scanFeedback('ok'); setCtxBin({ id: d.bin_id, label: d.label }); focusItem();
    } catch (e) { scanFeedback('error'); flash('error', e.message); }
  };

  const post = async (path, payload) => {
    const r = await fetch(`${API}/api/wms/opname3/${path}`, { method: 'POST', headers: jsonH, body: JSON.stringify(payload) });
    const d = await r.json().catch(() => ({}));
    return [r, d];
  };

  const doScan = async (raw) => {
    const code = (raw || '').trim(); if (!code) return;
    if (isRak && !ctxBin.id) { scanFeedback('error'); flash('error', 'Hitung rak: scan / pilih BIN dulu'); return; }
    const q = Number(scanQty) > 0 ? Number(scanQty) : (mode === 'set' ? 0 : 1);
    const payload = { session_id: sess.id, bin_id: ctxBin.id, qty: q };
    if (scanUom && scanUom !== scanBaseUnit) payload.input_uom = scanUom;
    try {
      const [r, d] = mode === 'set'
        ? await post('count', { ...payload, item_barcode: code })
        : await post('scan', { ...payload, item_barcode: code });
      if (r.ok) { scanFeedback('ok'); setLastScan(d); await loadDetail(sess.id); }
      else { scanFeedback('error'); flash('error', errText(d, 'Barang tidak dikenal')); }
    } catch (e) { scanFeedback('error'); flash('error', e.message); }
    focusItem();
  };

  const undoEntry = async (ln, ent) => {
    const [r, d] = await post('scan-undo', { session_id: sess.id, bin_id: ent.bin_id, item_material_id: ln.material_id, qty: 1 });
    if (r.ok) await loadDetail(sess.id); else flash('error', errText(d, 'Gagal mengurangi'));
  };

  const setLine = async (ln, patch) => {
    const [r, d] = await post('line', { session_id: sess.id, key: ln.key, ...patch });
    if (r.ok) await loadDetail(sess.id); else flash('error', errText(d, 'Gagal menyimpan baris'));
  };

  const doAction = async (action, extra = {}) => {
    let notes = '';
    if (action === 'reject') { notes = window.prompt('Alasan penolakan:') || ''; if (!notes) return; }
    setBusy(true);
    try {
      const [r, d] = await post(action, { session_id: sess.id, notes, ...extra });
      if (r.ok) {
        setZeroList(null);
        if (action === 'approve') {
          const s = d.session?.summary || {};
          flash('success', `Opname disetujui. ${s.stock_writes || 0} baris stok ditimpa, ${s.positions_updated || 0} bin diperbarui`
            + (s.je_number ? `, jurnal ${s.je_number}.` : s.je_error ? `. Jurnal GAGAL: ${s.je_error}` : '.'));
        } else if (action === 'submit') flash('success', 'Diajukan. Selisih kini terlihat oleh supervisor.');
        else flash('success', `Sesi ${action === 'cancel' ? 'dibatalkan' : 'ditolak'}.`);
        await loadDetail(sess.id);
      } else if (r.status === 409 && d?.detail?.code === 'belum_dihitung') {
        setZeroList(d.detail.belum_dihitung || []);
      } else flash('error', errText(d, `Gagal ${action}`));
    } catch (e) { flash('error', e.message); } finally { setBusy(false); }
  };

  // ── RENDER ─────────────────────────────────────────────────────────────
  if (loading) return <div className="flex items-center justify-center h-64"><div className="animate-spin rounded-full h-10 w-10 border-b-2 border-primary" /></div>;

  const banner = message && (
    <div data-testid="opname-message" className={`p-3 rounded-xl text-sm font-medium ${message.type === 'success' ? 'bg-[hsl(var(--success)/0.1)] text-[hsl(var(--success))] border border-[hsl(var(--success)/0.2)]' : 'bg-[hsl(var(--destructive)/0.1)] text-[hsl(var(--destructive))] border border-[hsl(var(--destructive)/0.2)]'}`}>{message.text}</div>
  );

  // ── DAFTAR ──
  if (!view) {
    return (
      <div className="space-y-6" data-testid="wms-opname-scan-module">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <h1 className="text-2xl font-bold text-foreground">{kind === 'aksesoris' ? 'Stok Opname Aksesoris' : 'Sesi Opname'}</h1>
            <p className="text-muted-foreground text-sm">Per lokasi (opsional zona/rak/bin). Hitung buta, tanpa kunci — transaksi tetap jalan; selisih = hitung − stok sistem saat dihitung. Satu jurnal per sesi saat disetujui.</p>
          </div>
          <div className="flex gap-2">
            <IconButton label="Refresh" onClick={loadSessions} data-testid="opname-refresh"><RefreshCw className="w-4 h-4 text-muted-foreground" /></IconButton>
            <Button onClick={() => setShowNew((v) => !v)} className="bg-primary text-primary-foreground hover:brightness-110" data-testid="opname-new-btn"><Plus className="w-4 h-4 mr-1" /> Opname Baru</Button>
          </div>
        </div>
        {banner}

        {showNew && (
          <GlassCard hover={false} className="p-5 space-y-3" data-testid="opname-new-panel">
            <h3 className="text-sm font-semibold text-foreground flex items-center gap-2"><ListChecks className="w-4 h-4 text-primary" /> Sesi Opname Baru</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Lokasi (wajib)</label>
                <div className="flex gap-2">
                  <SmartNativeSelect value={locId} onChange={(e) => { setLocId(e.target.value); setSubType(''); setSubId(''); }} className={selectCls} data-testid="opname-location">
                    <option value="">Pilih lokasi...</option>
                    {locations.map((l) => <option key={l.id} value={l.id} disabled={l.quarantine}>{l.code} - {l.name}{l.quarantine ? ' (karantina — dikelola dokumen karantina)' : ''}</option>)}
                  </SmartNativeSelect>
                  {locId && <IconButton label="Cetak label lokasi" onClick={() => printLocationLabel(locId)} data-testid="opname-print-location"><Printer className="w-4 h-4 text-muted-foreground" /></IconButton>}
                </div>
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Level</label>
                <SmartNativeSelect value={subType} onChange={(e) => { setSubType(e.target.value); setSubId(''); }} className={selectCls} disabled={!loc || !(loc.zones.length || loc.bins.length)} data-testid="opname-sub-type">
                  <option value="">Seluruh lokasi (stok + penempatan)</option>
                  <option value="zone">Per zona (penempatan saja)</option>
                  <option value="rack">Per rak (penempatan saja)</option>
                  <option value="bin">Per bin (penempatan saja)</option>
                </SmartNativeSelect>
              </div>
              {subType && (
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Pilih {subType === 'zone' ? 'zona' : subType === 'rack' ? 'rak' : 'bin'}</label>
                  <SmartNativeSelect value={subId} onChange={(e) => setSubId(e.target.value)} className={selectCls} data-testid="opname-sub-id">
                    <option value="">Pilih...</option>
                    {subChoices.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
                  </SmartNativeSelect>
                </div>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-4">
              <span className="text-xs text-muted-foreground">Jenis:</span>
              {KIND_OPTS.map(([k, label]) => (
                <label key={k} className="text-sm text-foreground flex items-center gap-1.5">
                  <input type="checkbox" checked={kinds.includes(k)} disabled={!!kind}
                    onChange={(e) => setKinds((v) => (e.target.checked ? [...v, k] : v.filter((x) => x !== k)))} data-testid={`opname-kind-${k}`} />
                  {label}
                </label>
              ))}
              <span className="text-[11px] text-muted-foreground">(kosong = semua jenis)</span>
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Cycle count — kode / SKU barang (opsional, pisah koma/baris; kosong = hitung semua barang di cakupan)</label>
              <textarea value={codes} onChange={(e) => setCodes(e.target.value)} rows={2} className={selectCls} data-testid="opname-codes" />
            </div>
            <Button onClick={createSession} disabled={busy || !locId || (subType && !subId)} className="bg-primary text-primary-foreground hover:brightness-110" data-testid="opname-create-btn"><Check className="w-4 h-4 mr-1" /> Mulai (ambil snapshot)</Button>
          </GlassCard>
        )}

        <GlassCard hover={false} className="p-5">
          <h3 className="text-sm font-semibold text-foreground mb-3">Riwayat Sesi Opname</h3>
          {sessions.length === 0 ? (
            <p className="text-xs text-muted-foreground text-center py-8">Belum ada sesi opname. Klik &ldquo;Opname Baru&rdquo; untuk memulai.</p>
          ) : (
            <div className="space-y-2">
              {sessions.map((s) => (
                <button key={s.id} onClick={() => openSession(s)} className="w-full text-left p-3 rounded-xl border border-[var(--glass-border)] bg-[var(--glass-bg)] hover:bg-[var(--glass-bg-hover)] transition-colors flex items-center justify-between gap-3" data-testid={`opname-session-${s.session_no}`}>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-foreground tabular-nums flex items-center gap-2">{s.session_no}
                      {s.archived && <span className="text-[10px] px-1.5 py-0.5 rounded border border-[var(--glass-border)] text-muted-foreground flex items-center gap-1"><Archive className="w-3 h-3" /> arsip</span>}
                      {s.level === 'rak' && <span className="text-[10px] px-1.5 py-0.5 rounded border border-[var(--glass-border)] text-muted-foreground">rak</span>}
                    </p>
                    <p className="text-xs text-muted-foreground truncate">{s.scope_label} · {s.created_at ? new Date(s.created_at).toLocaleString('id-ID') : '-'}{s.je_number ? ` · ${s.je_number}` : ''}</p>
                  </div>
                  <span className={`text-[11px] px-2 py-1 rounded-full border shrink-0 ${STATUS_BADGE[s.status] || ''}`}>{STATUS_LABEL[s.status] || s.status}</span>
                </button>
              ))}
            </div>
          )}
        </GlassCard>
      </div>
    );
  }

  const header = (
    <div className="flex items-center justify-between gap-3 flex-wrap">
      <div className="flex items-center gap-3">
        <IconButton label="Kembali" onClick={backToList} data-testid="opname-back"><ArrowLeft className="w-4 h-4 text-muted-foreground" /></IconButton>
        <div>
          <h1 className="text-xl font-bold text-foreground tabular-nums">{sess.session_no}</h1>
          <p className="text-muted-foreground text-xs">{sess.scope_label || '-'}{view.archived ? ' · ARSIP baca-saja (mesin lama)' : ''}</p>
        </div>
      </div>
      <span className={`text-xs px-3 py-1 rounded-full border ${STATUS_BADGE[sess.status] || ''}`} data-testid="opname-status">{STATUS_LABEL[sess.status] || sess.status}</span>
    </div>
  );

  // ── ARSIP (mesin lama) ──
  if (view.archived) {
    const rows = view.counts || view.session?.count_items || [];
    return (
      <div className="space-y-6" data-testid="wms-opname-scan-module">
        {header}
        <GlassCard hover={false} className="p-5" data-testid="opname-archive">
          <p className="text-xs text-muted-foreground mb-3">Sesi ini dibuat mesin opname lama (sebelum mesin tunggal K9). Hanya bisa dibaca; untuk menghitung ulang buat Sesi Opname baru.</p>
          <pre className="text-[11px] text-muted-foreground whitespace-pre-wrap">{JSON.stringify(sess.summary || {}, null, 1)}</pre>
          <div className="mt-3 space-y-1 max-h-[420px] overflow-y-auto">
            {rows.map((c, i) => (
              <div key={c.id || c.line_id || i} className="text-xs text-foreground flex justify-between border-b border-[var(--glass-border)]/50 py-1">
                <span>{c.material_code} {c.bin_label ? `@ ${c.bin_label}` : ''}</span>
                <span>{fmtNum(c.counted_qty)}{c.system_qty !== undefined ? ` / sistem ${fmtNum(c.system_qty)}` : ''}</span>
              </div>
            ))}
          </div>
        </GlassCard>
      </div>
    );
  }

  const lines = view.lines || [];
  const totals = view.totals || {};
  const status = sess.status;

  return (
    <div className="space-y-6" data-testid="wms-opname-scan-module">
      {header}
      {banner}

      {zeroList && (
        <GlassCard hover={false} className="p-5 border border-[hsl(var(--warning)/0.3)]" data-testid="opname-zero-confirm">
          <h3 className="text-sm font-semibold text-[hsl(var(--warning))] flex items-center gap-2 mb-2"><AlertTriangle className="w-4 h-4" /> {zeroList.length} baris BELUM dihitung</h3>
          <p className="text-xs text-muted-foreground mb-2">Belum dihitung ≠ 0. Hitung dulu, atau konfirmasi bahwa barang ini memang tidak ada (stok akan menjadi 0 saat disetujui).</p>
          <div className="max-h-48 overflow-y-auto text-xs text-foreground space-y-0.5 mb-3">
            {zeroList.map((z) => <div key={z.key}>{z.material_code} — {z.material_name}{z.bin_label ? ` @ ${z.bin_label}` : ''}</div>)}
          </div>
          <div className="flex gap-2">
            <Button onClick={() => doAction('submit', { confirm_zero: true })} disabled={busy} className="bg-[hsl(var(--warning))] text-white hover:brightness-110" data-testid="opname-confirm-zero">Anggap 0 &amp; Ajukan</Button>
            <Button onClick={() => setZeroList(null)} variant="ghost" className="text-muted-foreground">Kembali menghitung</Button>
          </div>
        </GlassCard>
      )}

      {status === 'counting' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <GlassCard hover={false} className="p-5 space-y-4">
            <h3 className="text-sm font-semibold text-foreground flex items-center gap-2"><ScanLine className="w-4 h-4 text-primary" /> Hitung <span className="text-[11px] text-muted-foreground font-normal flex items-center gap-1"><EyeOff className="w-3 h-3" /> buta — qty sistem disembunyikan</span></h3>
            <div className="space-y-2">
              <label className="text-xs font-medium text-muted-foreground flex items-center gap-1"><MapPin className="w-3 h-3" /> Konteks: scan label BIN atau label LOKASI {isRak ? '(wajib bin)' : '(opsional — tanpa bin = lantai / belum dirak)'}</label>
              <UniversalScanner variant="inline" onScan={pickBin} placeholder="Scan label bin / lokasi..." data-testid="opname-bin-barcode" />
              <SmartNativeSelect value={ctxBin.id} onChange={(e) => { const b = ctxBins.find((x) => x.id === e.target.value); setCtxBin(b ? { id: b.id, label: b.label } : { id: '', label: '' }); focusItem(); }} className={selectCls} data-testid="opname-bin-select">
                {!isRak && <option value="">Lantai / belum dirak ({sess.location_code})</option>}
                {isRak && <option value="">— pilih bin —</option>}
                {ctxBins.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}
              </SmartNativeSelect>
              <div className="p-2 rounded-lg bg-primary/10 border border-primary/20 text-xs text-foreground flex items-center gap-2" data-testid="opname-active-bin">
                <MapPin className="w-3 h-3 text-primary" /> {ctxBin.id ? ctxBin.label : `${sess.location_code} · lantai / belum dirak`}
              </div>
            </div>
            <div className="space-y-2">
              <div className="flex gap-2 text-xs">
                <button onClick={() => setMode('add')} className={`px-2 py-1 rounded border ${mode === 'add' ? 'border-primary text-primary' : 'border-[var(--glass-border)] text-muted-foreground'}`} data-testid="opname-mode-add">+ per scan</button>
                <button onClick={() => setMode('set')} className={`px-2 py-1 rounded border ${mode === 'set' ? 'border-primary text-primary' : 'border-[var(--glass-border)] text-muted-foreground'}`} data-testid="opname-mode-set">Ketik jumlah (set)</button>
              </div>
              <div className="flex gap-2">
                <GlassInput type="number" min={0} step="0.0001" value={scanQty} onChange={(e) => setScanQty(e.target.value)} className="w-28" data-testid="opname-scan-qty" />
                <UomSelect opt={scanUomOpt} value={scanUom || scanBaseUnit} onChange={(e) => setScanUom(e.target.value)} fallbackUnit={lastScan?.base_uom || ''} testId="opname-scan-uom" className="w-24 shrink-0" />
                <div className="flex-1"><UomConversionHint opt={scanUomOpt} qty={scanQty} unit={scanUom || scanBaseUnit} fallbackUnit={lastScan?.base_uom || ''} testId="opname-scan-uom-hint" /></div>
              </div>
              <label className="text-xs font-medium text-muted-foreground">{mode === 'set' ? 'Scan / ketik kode barang → jumlah di atas MENJADI hasil hitung di konteks ini.' : 'Scan barang terus-menerus (scanner atau kamera); tiap scan menambah jumlah di atas.'}</label>
              <UniversalScanner variant="inline" onScan={doScan} continuous keepFocus autoFocus placeholder="Scan / ketik kode barang lalu Enter..." disabled={isRak && !ctxBin.id} data-testid="opname-item-input" />
            </div>
            {lastScan && (
              <div className="p-3 rounded-xl border bg-[hsl(var(--success)/0.1)] border-[hsl(var(--success)/0.2)]" data-testid="opname-last-scan">
                <div className="flex items-center justify-between"><span className="text-sm font-medium text-foreground">{lastScan.material_code}</span><span className="text-lg font-bold text-foreground">{fmtNum(lastScan.counted_qty)} {lastScan.base_uom}</span></div>
                <p className="text-[11px] text-muted-foreground mt-1">{lastScan.material_name} · {lastScan.bin_label || 'lantai / belum dirak'}</p>
              </div>
            )}
          </GlassCard>

          <GlassCard hover={false} className="p-5">
            <div className="flex items-center justify-between mb-3 gap-2">
              <h3 className="text-sm font-semibold text-foreground flex items-center gap-2"><ClipboardList className="w-4 h-4 text-primary" /> Lembar Hitung <span className="text-xs text-muted-foreground font-normal">{totals.counted || 0}/{totals.lines || 0} dihitung</span></h3>
              <div className="flex gap-2">
                <Button onClick={() => doAction('cancel')} disabled={busy} variant="ghost" size="sm" className="text-muted-foreground" data-testid="opname-cancel-btn">Batalkan</Button>
                <Button onClick={() => doAction('submit')} disabled={busy} size="sm" className="bg-primary text-primary-foreground hover:brightness-110" data-testid="opname-submit-btn"><PackageCheck className="w-4 h-4 mr-1" /> Selesai &amp; Ajukan</Button>
              </div>
            </div>
            <div className="space-y-2 max-h-[520px] overflow-y-auto">
              {lines.length === 0 ? <p className="text-xs text-muted-foreground text-center py-8">Tidak ada barang di snapshot. Barang yang ditemukan akan ditambahkan saat di-scan.</p> : lines.map((ln) => (
                <div key={ln.key} className="p-2.5 rounded-lg border border-[var(--glass-border)] bg-[var(--glass-bg)]" data-testid={`opname-line-${ln.material_code}`}>
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-foreground truncate">{ln.material_code} <span className="text-muted-foreground font-normal">{ln.material_name}</span></p>
                      {ln.bin_label && <p className="text-[11px] text-muted-foreground">@ {ln.bin_label}</p>}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded border ${LINE_STATUS[ln.status]?.[1] || ''}`}>{LINE_STATUS[ln.status]?.[0] || ln.status}</span>
                      {ln.status !== 'belum' && <span className="text-sm font-bold text-foreground">{fmtNum(ln.counted_qty)} {ln.unit}</span>}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 mt-1">
                    {(ln.entries || []).map((e) => (
                      <span key={e.bin_id || 'lantai'} className="text-[11px] text-muted-foreground border border-[var(--glass-border)] rounded px-1.5 py-0.5 flex items-center gap-1">
                        {e.bin_label || 'lantai'}: {fmtNum(e.counted_qty)}
                        <button onClick={() => undoEntry(ln, e)} title="Kurangi 1" data-testid={`opname-undo-${ln.material_code}`}><Minus className="w-3 h-3" /></button>
                      </span>
                    ))}
                    <label className="text-[11px] text-muted-foreground flex items-center gap-1 ml-auto">
                      <input type="checkbox" checked={ln.reason === 'rusak'} onChange={(e) => setLine(ln, { reason: e.target.checked ? 'rusak' : '' })} data-testid={`opname-rusak-${ln.material_code}`} /> rusak
                    </label>
                    {isRak && !ln.in_snapshot && (
                      <SmartNativeSelect value={ln.resolution || 'pindah'} onChange={(e) => setLine(ln, { resolution: e.target.value })} className="border border-[var(--glass-border)] bg-[var(--input-surface)] rounded px-1.5 py-0.5 text-[11px] text-foreground" data-testid={`opname-resolution-${ln.material_code}`}>
                        <option value="pindah">pindah penempatan (stok tetap)</option>
                        <option value="lebih">barang lebih (selisih lewat hitung penuh lokasi)</option>
                      </SmartNativeSelect>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </GlassCard>
        </div>
      )}

      {status !== 'counting' && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <GlassCard hover={false} className="p-4"><p className="text-xs text-muted-foreground">Baris dihitung</p><p className="text-xl font-bold text-foreground">{totals.counted || 0}/{totals.lines || 0}</p></GlassCard>
            <GlassCard hover={false} className="p-4"><p className="text-xs text-muted-foreground">Baris berselisih</p><p className="text-xl font-bold text-foreground">{totals.with_variance || 0}</p></GlassCard>
            <GlassCard hover={false} className="p-4"><p className="text-xs text-muted-foreground">Nilai selisih (WAC snapshot)</p><p className={`text-xl font-bold ${totals.total_variance_value < 0 ? 'text-[hsl(var(--destructive))]' : totals.total_variance_value > 0 ? 'text-[hsl(var(--success))]' : 'text-foreground'}`}>{fmtRp(totals.total_variance_value)}</p></GlassCard>
            <GlassCard hover={false} className="p-4"><p className="text-xs text-muted-foreground">Tanpa WAC (tak berjurnal)</p><p className="text-xl font-bold text-[hsl(var(--warning))]">{totals.uncosted || 0}</p></GlassCard>
          </div>
          {isRak && <p className="text-xs text-muted-foreground">Hitung level rak hanya memperbaiki PENEMPATAN bin — stok dan jurnal tidak berubah.</p>}

          {status === 'submitted' && (
            <div className="flex flex-wrap gap-2" data-testid="opname-approval-actions">
              <Button onClick={() => doAction('approve')} disabled={busy} className="bg-[hsl(var(--success))] text-white hover:brightness-110" data-testid="opname-approve-btn"><ShieldCheck className="w-4 h-4 mr-1" /> Approve (Supervisor)</Button>
              <Button onClick={() => doAction('reject')} disabled={busy} variant="outline" className="border-[hsl(var(--destructive)/0.3)] text-[hsl(var(--destructive))]" data-testid="opname-reject-btn"><X className="w-4 h-4 mr-1" /> Tolak</Button>
              <Button onClick={() => doAction('cancel')} disabled={busy} variant="ghost" className="text-muted-foreground" data-testid="opname-cancel-btn">Batalkan</Button>
            </div>
          )}
          {status === 'approved' && (
            <div className="p-3 rounded-xl bg-[hsl(var(--success)/0.1)] border border-[hsl(var(--success)/0.2)] text-sm text-[hsl(var(--success))] flex items-center gap-2 flex-wrap" data-testid="opname-approved-banner">
              <PackageCheck className="w-4 h-4" /> Disetujui {sess.approved_by_name || ''}. {sess.summary?.stock_writes || 0} baris stok ditimpa · {sess.summary?.positions_updated || 0} bin diperbarui
              {sess.je_number ? ` · jurnal ${sess.je_number}` : ''}{sess.summary?.je_error ? ` · jurnal GAGAL: ${sess.summary.je_error}` : ''}
            </div>
          )}

          <GlassCard hover={false} className="p-5">
            <h3 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2"><Boxes className="w-4 h-4 text-primary" /> Selisih per Baris</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-muted-foreground border-b border-[var(--glass-border)]">
                    <th className="text-left py-2">Kode</th><th className="text-left">Nama</th>{isRak && <th className="text-left">Bin</th>}
                    <th className="text-right">{isRak ? 'Penempatan' : 'Snapshot'}</th>{!isRak && <th className="text-right">Mutasi s/d dihitung</th>}{!isRak && <th className="text-right">Sistem saat dihitung</th>}
                    <th className="text-right">Hitung</th><th className="text-right">Selisih</th>{!isRak && <th className="text-right">Nilai</th>}<th className="text-left pl-3">Catatan</th>
                  </tr>
                </thead>
                <tbody>
                  {lines.map((l) => (
                    <tr key={l.key} className={`border-b border-[var(--glass-border)]/50 ${l.variance_qty ? 'bg-[hsl(var(--warning)/0.05)]' : ''}`} data-testid={`opname-var-${l.material_code}`}>
                      <td className="py-2 tabular-nums text-foreground">{l.material_code}</td>
                      <td className="text-muted-foreground">{l.material_name}</td>
                      {isRak && <td className="text-muted-foreground text-xs">{l.bin_label}</td>}
                      <td className="text-right text-foreground">{fmtNum(l.snapshot_qty)}</td>
                      {!isRak && <td className="text-right text-muted-foreground">{fmtNum(l.mutation_qty)}</td>}
                      {!isRak && <td className="text-right text-foreground">{fmtNum(l.system_qty)}</td>}
                      <td className="text-right text-foreground">{fmtNum(l.counted_qty)}</td>
                      <td className={`text-right font-semibold ${l.variance_qty < 0 ? 'text-[hsl(var(--destructive))]' : l.variance_qty > 0 ? 'text-[hsl(var(--success))]' : 'text-muted-foreground'}`}>{l.variance_qty > 0 ? '+' : ''}{fmtNum(l.variance_qty)}</td>
                      {!isRak && <td className="text-right text-muted-foreground">{fmtRp(l.variance_value)}</td>}
                      <td className="pl-3 text-[11px] text-muted-foreground">
                        {LINE_STATUS[l.status]?.[0]}{l.reason === 'rusak' ? ' · rusak (6-4300)' : ''}{isRak && !l.in_snapshot ? ` · ${l.resolution === 'lebih' ? 'barang lebih' : 'pindah penempatan'}` : ''}
                        {status === 'submitted' && !isRak && l.variance_qty < 0 && (
                          <label className="ml-2 inline-flex items-center gap-1"><input type="checkbox" checked={l.reason === 'rusak'} onChange={(e) => setLine(l, { reason: e.target.checked ? 'rusak' : '' })} /> rusak</label>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </GlassCard>

          {(sess.summary?.findings || []).length > 0 && (
            <GlassCard hover={false} className="p-5">
              <h3 className="text-sm font-semibold text-[hsl(var(--warning))] mb-2 flex items-center gap-2"><AlertTriangle className="w-4 h-4" /> Temuan penempatan</h3>
              {sess.summary.findings.map((f, i) => (
                <p key={i} className="text-xs text-foreground">{f.jenis === 'barang_lebih' ? 'Barang lebih (belum masuk stok — hitung penuh lokasi)' : 'Bin sudah berisi barang lain (1 bin = 1 barang) — dianggap belum dirak'}: {lines.find((x) => x.material_id === f.material_id)?.material_code || f.material_id} × {fmtNum(f.qty)}</p>
              ))}
            </GlassCard>
          )}
        </div>
      )}
    </div>
  );
}

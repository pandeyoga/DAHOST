/**
 * RahazaMaterialReturnModule — Retur Material produksi → gudang. 2026-11-02, keputusan owner K10.
 *
 * Jalur koreksi bahan yang SUDAH keluar gudang (Material Issue / Surat Jalan "Kirim Material CMT").
 * Surat jalan yang bahannya sudah keluar TIDAK bisa dihapus; bahan dikembalikan lewat layar ini:
 *   pilih MI / Surat Jalan asal → qty retur ≤ sisa (keluar − sudah diretur − retur berjalan)
 *   → supervisor setuju → gudang terima di lokasi WAJIB → stok kembali + jurnal balik
 *   (Dr persediaan / Cr WIP atau biaya proyek, pada HPP saat keluar) + status retur MI.
 * Backend: /api/production/material-returns (routes/production_material_returns.py).
 *
 * Berbeda dari "Retur Produksi (barang dari buyer)" (`prod-buyer-returns`) dan Retur Fisik marketplace.
 */
import { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, PackageCheck, Plus, RefreshCw, Send, Undo2, XCircle } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import Modal from './Modal';
import { toast } from 'sonner';
import { apiGet, apiPost, fmtDate, fmtNum } from './procurement/procApi';

const BASE = '/api/production/material-returns';
const CONDITIONS = [
  { value: 'good', label: 'Baik — kembali ke stok' },
  { value: 'damaged', label: 'Rusak — tidak kembali ke stok' },
  { value: 'scrap', label: 'Scrap — dicatat saja' },
];
const STATUS_META = {
  draft: { label: 'Draft', cls: 'bg-muted text-muted-foreground border-border' },
  submitted: { label: 'Menunggu Supervisor', cls: 'bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-400/15 dark:text-amber-300 dark:border-amber-400/30' },
  approved: { label: 'Menunggu Gudang', cls: 'bg-sky-100 text-sky-800 border-sky-300 dark:bg-sky-400/15 dark:text-sky-300 dark:border-sky-400/30' },
  received: { label: 'Diterima Gudang', cls: 'bg-emerald-100 text-emerald-700 border-emerald-300 dark:bg-emerald-400/15 dark:text-emerald-300 dark:border-emerald-400/30' },
  rejected: { label: 'Ditolak', cls: 'bg-red-100 text-red-700 border-red-300 dark:bg-red-400/15 dark:text-red-300 dark:border-red-400/30' },
};
const inputCls = 'w-full border border-border rounded-lg px-3 py-2 text-sm bg-[var(--card-surface)]';

function StatusBadge({ status }) {
  const m = STATUS_META[status] || STATUS_META.draft;
  return <span className={`inline-flex text-[10px] font-semibold px-2 py-0.5 rounded-full border ${m.cls}`}>{m.label}</span>;
}

function CreateModal({ token, preset, onClose, onSaved }) {
  const [q, setQ] = useState(preset?.vendor_shipment_number || '');
  const [sources, setSources] = useState([]);
  const [src, setSrc] = useState(null);
  const [qty, setQty] = useState({});
  const [cond, setCond] = useState({});
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const loadSource = useCallback(async (params) => {
    setErr(''); setSrc(null); setQty({}); setCond({});
    try {
      const qs = new URLSearchParams(params).toString();
      const res = await apiGet(token, `${BASE}/source?${qs}`);
      setSrc(res?.data || null);
    } catch (e) { setErr(e.message); }
  }, [token]);

  useEffect(() => {
    apiGet(token, `${BASE}/sources?q=${encodeURIComponent(q)}`)
      .then((res) => setSources(res?.data || [])).catch((e) => setErr(e.message));
  }, [token, q]);
  useEffect(() => {
    if (preset?.material_issue_id) loadSource({ material_issue_id: preset.material_issue_id });
    else if (preset?.vendor_shipment_id) loadSource({ vendor_shipment_id: preset.vendor_shipment_id });
  }, [preset, loadSource]);

  const submit = async () => {
    if (!src) { setErr('Pilih MI / Surat Jalan asal'); return; }
    const items = [];
    for (const l of src.lines) {
      const v = parseFloat(qty[l.material_id]);
      if (!(v > 0)) continue;
      if (v - l.returnable > 1e-6) { setErr(`${l.material_code}: retur ${v} > sisa ${fmtNum(l.returnable)}`); return; }
      items.push({ material_id: l.material_id, material_code: l.material_code, material_name: l.material_name,
        qty_returned: v, unit: l.unit, condition: cond[l.material_id] || 'good', reason: 'sisa_produksi' });
    }
    if (!items.length) { setErr('Isi qty retur minimal satu bahan'); return; }
    setBusy(true); setErr('');
    try {
      const created = await apiPost(token, BASE, {
        material_issue_id: src.material_issue_id, return_reason: reason, notes: reason, items,
        work_order_id: src.work_order_id || '',
      });
      const doc = created?.data;
      await apiPost(token, `${BASE}/${doc.id}/submit`, {});
      toast.success(`Retur ${doc.ref_no} diajukan — menunggu persetujuan supervisor`);
      onSaved?.();
    } catch (e) { setErr(e.message); setBusy(false); }
  };

  return (
    <Modal title="Retur Material ke Gudang" onClose={onClose} size="xl">
      <div className="space-y-3 text-sm" data-testid="pmr-create-modal">
        <div className="grid gap-2 sm:grid-cols-2">
          <input value={q} onChange={(e) => setQ(e.target.value)} className={inputCls}
            placeholder="Cari no. MI / surat jalan / vendor" data-testid="pmr-source-search" />
          <SmartNativeSelect value={src?.material_issue_id || ''} className={inputCls} data-testid="pmr-source-select"
            onChange={(e) => e.target.value && loadSource({ material_issue_id: e.target.value })}>
            <option value="">— pilih MI / Surat Jalan asal —</option>
            {sources.map((s) => (
              <option key={s.id} value={s.id}>
                {s.mi_number}{s.vendor_shipment_number ? ` · SJ ${s.vendor_shipment_number}` : ''}{s.vendor_name ? ` · ${s.vendor_name}` : ''}{s.return_status === 'partial' ? ' · sebagian diretur' : ''}
              </option>
            ))}
          </SmartNativeSelect>
        </div>
        {src && (
          <GlassCard className="p-0 overflow-x-auto" hover={false}>
            <div className="px-3 py-2 text-xs text-muted-foreground border-b border-border">
              MI <span className="font-mono">{src.mi_number}</span>
              {src.vendor_shipment_number ? <> · Surat Jalan <span className="font-mono">{src.vendor_shipment_number}</span></> : null}
              {src.vendor_name ? ` · ${src.vendor_name}` : ''}
            </div>
            <table className="w-full text-sm min-w-[640px]" data-testid="pmr-source-lines">
              <thead className="text-xs text-muted-foreground border-b border-border">
                <tr>
                  <th className="text-left px-3 py-2">Bahan</th><th className="text-right px-3 py-2">Keluar</th>
                  <th className="text-right px-3 py-2">Sudah diretur</th><th className="text-right px-3 py-2">Sisa</th>
                  <th className="text-right px-3 py-2">Qty retur</th><th className="text-left px-3 py-2">Kondisi</th>
                </tr>
              </thead>
              <tbody>
                {src.lines.map((l) => (
                  <tr key={l.material_id} className="border-b border-border">
                    <td className="px-3 py-2 text-xs"><div className="font-mono">{l.material_code}</div>{l.material_name}</td>
                    <td className="px-3 py-2 text-right">{fmtNum(l.qty_issued)} {l.unit}</td>
                    <td className="px-3 py-2 text-right">{fmtNum(l.qty_returned)}</td>
                    <td className="px-3 py-2 text-right font-semibold">{fmtNum(l.returnable)}</td>
                    <td className="px-3 py-2 text-right">
                      <input type="number" min="0" step="any" max={l.returnable} disabled={!(l.returnable > 0)}
                        value={qty[l.material_id] ?? ''} onChange={(e) => setQty({ ...qty, [l.material_id]: e.target.value })}
                        className="w-24 border border-border rounded px-2 py-1 text-right bg-[var(--card-surface)]"
                        data-testid={`pmr-qty-${l.material_code}`} />
                    </td>
                    <td className="px-3 py-2">
                      <SmartNativeSelect value={cond[l.material_id] || 'good'} className="border border-border rounded px-2 py-1 text-xs bg-[var(--card-surface)]"
                        onChange={(e) => setCond({ ...cond, [l.material_id]: e.target.value })}>
                        {CONDITIONS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                      </SmartNativeSelect>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </GlassCard>
        )}
        <input value={reason} onChange={(e) => setReason(e.target.value)} className={inputCls}
          placeholder="Alasan retur (mis. surat jalan salah / sisa produksi)" data-testid="pmr-reason" />
        <p className="text-xs text-muted-foreground">
          Bahan kondisi baik kembali ke stok di lokasi yang dipilih gudang saat menerima, dengan jurnal balik pada HPP saat bahan keluar.
        </p>
        {err && <div className="text-sm text-red-700 dark:text-red-400" data-testid="pmr-create-error">{err}</div>}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Batal</Button>
          <Button onClick={submit} disabled={busy || !src} data-testid="pmr-create-submit">{busy ? 'Menyimpan…' : 'Ajukan Retur'}</Button>
        </div>
      </div>
    </Modal>
  );
}

function ReceiveModal({ token, doc, onClose, onDone }) {
  const [locs, setLocs] = useState([]);
  const [locId, setLocId] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  useEffect(() => { apiGet(token, '/api/rahaza/storage-locations').then((r) => setLocs(Array.isArray(r) ? r : [])).catch((e) => setErr(e.message)); }, [token]);
  const submit = async () => {
    if (!locId) { setErr('Lokasi penerima wajib dipilih'); return; }
    setBusy(true); setErr('');
    try {
      const out = await apiPost(token, `${BASE}/${doc.id}/receive`, { location_id: locId });
      const p = out?.posting || {};
      toast.success(`Retur ${doc.ref_no} diterima${p.je_number ? ` · jurnal ${p.je_number}` : ''}${p.ok === false ? ` · jurnal GAGAL: ${p.error}` : ''}`);
      onDone();
    } catch (e) { setErr(e.message); setBusy(false); }
  };
  return (
    <Modal title={`Terima Retur · ${doc.ref_no}`} onClose={onClose} size="sm">
      <div className="space-y-3 text-sm">
        <SmartNativeSelect value={locId} onChange={(e) => setLocId(e.target.value)} className={inputCls} data-testid="pmr-receive-location">
          <option value="">— lokasi penerima (wajib) —</option>
          {locs.map((l) => <option key={l.id} value={l.id}>{l.code ? `${l.code} · ` : ''}{l.name || l.code}</option>)}
        </SmartNativeSelect>
        {err && <div className="text-sm text-red-700 dark:text-red-400">{err}</div>}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Batal</Button>
          <Button onClick={submit} disabled={busy} data-testid="pmr-receive-submit">{busy ? 'Memproses…' : 'Terima ke Stok'}</Button>
        </div>
      </div>
    </Modal>
  );
}

export default function RahazaMaterialReturnModule({ token, deepLinkParams }) {
  const [rows, setRows] = useState([]);
  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [creating, setCreating] = useState(null);
  const [receiving, setReceiving] = useState(null);
  const [busy, setBusy] = useState('');

  const load = useCallback(async () => {
    setLoading(true); setErr('');
    try {
      const res = await apiGet(token, `${BASE}?limit=200${status ? `&status=${status}` : ''}`);
      setRows(res?.data || []);
    } catch (e) { setErr(e.message); }
    finally { setLoading(false); }
  }, [token, status]);
  useEffect(() => { load(); }, [load]);
  // deep-link dari "Kirim Material CMT" (hapus surat jalan ditolak → Retur Material)
  useEffect(() => {
    if (deepLinkParams?.vendor_shipment_id || deepLinkParams?.material_issue_id) setCreating({ ...deepLinkParams });
  }, [deepLinkParams]);

  const act = async (doc, path, msg) => {
    setBusy(doc.id);
    try {
      await apiPost(token, `${BASE}/${doc.id}/${path}`, { note: '' });
      toast.success(`${msg} ${doc.ref_no}`);
      load();
    } catch (e) { toast.error(e.message); }
    finally { setBusy(''); }
  };

  return (
    <div className="space-y-4" data-testid="material-return-module">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold flex items-center gap-2"><Undo2 className="w-5 h-5" /> Retur Material</h2>
          <p className="text-sm text-muted-foreground mt-1 max-w-3xl">
            Bahan yang sudah keluar lewat Pengeluaran Material / Kirim Material CMT dikembalikan ke gudang. Qty retur tidak boleh
            melebihi sisa; gudang memilih lokasi penerima; stok kembali dengan jurnal balik pada HPP saat bahan keluar.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={load}><RefreshCw className="w-4 h-4" /></Button>
          <Button onClick={() => setCreating({})} data-testid="pmr-new"><Plus className="w-4 h-4 mr-1" /> Retur Material</Button>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        {[['', 'Semua'], ['submitted', 'Menunggu Supervisor'], ['approved', 'Menunggu Gudang'], ['received', 'Diterima'], ['rejected', 'Ditolak']].map(([k, l]) => (
          <button key={k || 'all'} onClick={() => setStatus(k)}
            className={`px-3 py-1.5 rounded-full text-xs border ${status === k ? 'bg-primary/15 border-primary' : 'border-border'}`}
            data-testid={`pmr-filter-${k || 'all'}`}>{l}</button>
        ))}
      </div>
      {err && <div className="text-sm text-red-700 dark:text-red-400 bg-red-100 dark:bg-red-500/10 rounded-lg px-4 py-2">{err}</div>}
      <GlassCard className="overflow-x-auto p-0">
        <table className="w-full text-sm min-w-[860px]">
          <thead className="border-b border-border text-xs text-muted-foreground">
            <tr>
              <th className="text-left px-3 py-2">No. Retur</th><th className="text-left px-3 py-2">Asal (MI · Surat Jalan)</th>
              <th className="text-left px-3 py-2">Bahan</th><th className="text-center px-3 py-2">Status</th>
              <th className="text-left px-3 py-2">Jurnal</th><th className="text-right px-3 py-2">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan="6" className="px-3 py-6 text-center text-muted-foreground">Memuat…</td></tr>
            ) : rows.length === 0 ? (
              <tr><td colSpan="6" className="px-3 py-6 text-center text-muted-foreground">Belum ada Retur Material.</td></tr>
            ) : rows.map((r) => (
              <tr key={r.id} className="border-b border-border align-top" data-testid={`pmr-row-${r.ref_no}`}>
                <td className="px-3 py-2"><div className="font-mono text-xs">{r.ref_no}</div>
                  <div className="text-[11px] text-muted-foreground">{fmtDate(r.created_at)} · {r.submitted_by || '-'}</div></td>
                <td className="px-3 py-2 text-xs">{r.mi_number || '-'}<div className="text-muted-foreground">{r.vendor_shipment_number || r.work_order_code || ''}</div></td>
                <td className="px-3 py-2 text-xs">
                  {(r.items || []).map((it, i) => (
                    <div key={i}>{it.material_code} · {fmtNum(it.qty_returned)} {it.unit}{it.condition && it.condition !== 'good' ? ` (${it.condition})` : ''}</div>
                  ))}
                </td>
                <td className="px-3 py-2 text-center"><StatusBadge status={r.status} /></td>
                <td className="px-3 py-2 text-xs">{r.gl_je_number || (r.gl_error ? <span className="text-red-700 dark:text-red-400">{r.gl_error}</span> : '-')}</td>
                <td className="px-3 py-2">
                  <div className="flex justify-end gap-1 flex-wrap">
                    {r.status === 'draft' && (
                      <Button size="sm" disabled={busy === r.id} onClick={() => act(r, 'submit', 'Diajukan')}><Send className="w-3.5 h-3.5 mr-1" />Ajukan</Button>
                    )}
                    {r.status === 'submitted' && (<>
                      <Button size="sm" disabled={busy === r.id} onClick={() => act(r, 'approve', 'Disetujui')} data-testid={`pmr-approve-${r.ref_no}`}>
                        <CheckCircle2 className="w-3.5 h-3.5 mr-1" />Setujui</Button>
                      <Button size="sm" variant="outline" disabled={busy === r.id} onClick={() => act(r, 'reject', 'Ditolak')}>
                        <XCircle className="w-3.5 h-3.5 mr-1" />Tolak</Button>
                    </>)}
                    {r.status === 'approved' && (
                      <Button size="sm" disabled={busy === r.id} onClick={() => setReceiving(r)} data-testid={`pmr-receive-${r.ref_no}`}>
                        <PackageCheck className="w-3.5 h-3.5 mr-1" />Terima</Button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>
      {creating && <CreateModal token={token} preset={creating} onClose={() => setCreating(null)} onSaved={() => { setCreating(null); load(); }} />}
      {receiving && <ReceiveModal token={token} doc={receiving} onClose={() => setReceiving(null)} onDone={() => { setReceiving(null); load(); }} />}
    </div>
  );
}

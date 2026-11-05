/**
 * PurchaseReturnModule — Retur Pembelian (Portal Pengadaan). 2026-11-02, keputusan owner K11.
 *
 * Dokumen RTP-YYYYMM-NNNN milik Pengadaan: barang reject (Karantina) atau stok gudang dikembalikan
 * ke pemasok dengan pilihan penyelesaian — tukar barang, potong tagihan (nota debit), refund,
 * diterima dengan diskon, atau dimusnahkan. Harga = harga GR asal (GR WAJIB); selisih ke HPP
 * rata-rata → PPV. DA bukan PKP → tanpa PPN retur. Nota Debit & refund diselesaikan Keuangan
 * (layar Nota Debit). Backend: /api/rahaza/purchase-returns (routes/rahaza_purchase_returns.py).
 *
 * `PurchaseReturnCreateModal` dipakai juga oleh Karantina QC (tombol "Buat Retur Pembelian").
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { PackageCheck, Plus, RefreshCw, Send, Undo2, XCircle } from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import Modal from '../Modal';
import { toast } from 'sonner';
import { apiGet, apiPost, fmtDate, fmtNum, fmtRp } from './procApi';

export const SETTLEMENT_OPTIONS = [
  { value: 'exchange', label: 'Tukar barang', hint: 'Barang dikirim balik; pemasok mengirim pengganti.' },
  { value: 'debit_note', label: 'Potong tagihan (nota debit)', hint: 'Barang dikirim balik; Keuangan menerbitkan nota debit — hutang/GRNI berkurang.' },
  { value: 'refund', label: 'Refund uang', hint: 'Barang dikirim balik; pemasok mentransfer uang. Hanya untuk barang yang sudah ditagih/bernilai.' },
  { value: 'accept_discount', label: 'Diterima dengan diskon', hint: 'Barang TIDAK dikirim balik; Keuangan mengetik harga diskon lewat nota debit.' },
  { value: 'destroy', label: 'Dimusnahkan', hint: 'Barang dimusnahkan; pilih siapa yang menanggung.' },
];
const STATUS_META = {
  draft: { label: 'Draft', cls: 'bg-muted text-muted-foreground border-border' },
  awaiting_settlement: { label: 'Menunggu Penyelesaian', cls: 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))] border-[hsl(var(--warning)/0.35)]   ' },
  settled: { label: 'Selesai', cls: 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))] border-[hsl(var(--success)/0.35)]   ' },
  cancelled: { label: 'Batal', cls: 'bg-muted text-muted-foreground border-border line-through' },
};
const SHIPPING = ['exchange', 'debit_note', 'refund', 'destroy'];
const settlementLabel = (v) => (SETTLEMENT_OPTIONS.find((o) => o.value === v) || {}).label || v;

export function StatusBadge({ status }) {
  const m = STATUS_META[status] || STATUS_META.draft;
  return <span className={`inline-flex text-[10px] font-semibold px-2 py-0.5 rounded-full border ${m.cls}`}>{m.label}</span>;
}

/** Form buat Retur Pembelian — dari item karantina (`quarantineItem`) atau dari stok (pilih GR). */
export function PurchaseReturnCreateModal({ token, quarantineItem, onClose, onSaved }) {
  const fromQ = !!quarantineItem;
  const [settlement, setSettlement] = useState('debit_note');
  const [borne, setBorne] = useState('supplier');
  const [qty, setQty] = useState(fromQ ? quarantineItem.remaining_qty : '');
  const [reason, setReason] = useState('');
  const [notes, setNotes] = useState('');
  const [shipDate, setShipDate] = useState('');
  const [photos, setPhotos] = useState('');
  const [grs, setGrs] = useState([]);
  const [grId, setGrId] = useState('');
  const [lineId, setLineId] = useState('');
  const [locs, setLocs] = useState([]);
  const [locId, setLocId] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const needGr = !fromQ || !['goods_receipt', 'grn_inspection'].includes(quarantineItem?.source?.type);
  const unvalued = fromQ ? Math.max(0, Number(quarantineItem.remaining_qty || 0) - Number(quarantineItem.valued_remaining_qty || 0)) : 0;

  useEffect(() => {
    if (!needGr) return;
    (async () => {
      try {
        const rows = await apiGet(token, '/api/wms/legacy/receiving');
        setGrs((Array.isArray(rows) ? rows : []).filter((g) => ['received', 'completed', 'partial_received', 'accepted'].includes(g.status)));
      } catch (e) { setErr(e.message); }
      if (!fromQ) {
        try { setLocs(await apiGet(token, '/api/rahaza/storage-locations')); } catch { /* noop */ }
      }
    })();
  }, [token, needGr, fromQ]);

  const gr = useMemo(() => grs.find((g) => g.id === grId), [grs, grId]);
  const grLines = useMemo(() => (gr?.items || []).filter((li) => li.material_id
    && (!fromQ || li.material_id === quarantineItem.material_id)), [gr, fromQ, quarantineItem]);
  const line = grLines.find((li) => (li.id || li.po_item_id) === lineId);
  const price = Number(line?.unit_price || line?.unit_cost || quarantineItem?.unit_cost || 0);

  const submit = async () => {
    const q = parseFloat(qty);
    if (!(q > 0)) { setErr('Qty harus > 0'); return; }
    if (!reason.trim()) { setErr('Alasan retur wajib diisi'); return; }
    if (needGr && !grId) { setErr('GR asal wajib dipilih (harga & pemasok diambil dari penerimaan asal)'); return; }
    if (!fromQ && (!lineId || !locId)) { setErr('Pilih baris GR dan lokasi asal stok'); return; }
    if (settlement === 'refund' && unvalued > 1e-6) {
      setErr('Refund hanya untuk barang yang sudah bernilai/ditagih. Reject saat penerimaan belum ditagih — pilih tukar barang atau potong tagihan.');
      return;
    }
    setBusy(true); setErr('');
    try {
      const body = {
        settlement, destroy_borne_by: settlement === 'destroy' ? borne : undefined,
        gr_id: needGr ? grId : undefined, reason, notes, ship_date: shipDate || undefined,
        photos: photos.split(/\s+/).filter(Boolean),
        lines: fromQ
          ? [{ quarantine_item_id: quarantineItem.id, qty: q, gr_item_id: lineId || undefined }]
          : [{ material_id: line.material_id, location_id: locId, qty: q, gr_item_id: lineId }],
      };
      const doc = await apiPost(token, '/api/rahaza/purchase-returns', body);
      toast.success(`Retur Pembelian ${doc.rtp_number} dibuat (Draft)`);
      onSaved?.(doc);
    } catch (e) { setErr(e.message); setBusy(false); }
  };

  return (
    <Modal title="Buat Retur Pembelian" onClose={onClose} size="lg">
      <div className="space-y-3 text-sm" data-testid="rtp-create-modal">
        {fromQ && (
          <div className="rounded-lg border border-border px-3 py-2 text-xs">
            <div className="font-medium">{quarantineItem.material_code} · {quarantineItem.material_name}</div>
            <div className="text-muted-foreground">
              Karantina sisa {fmtNum(quarantineItem.remaining_qty)} {quarantineItem.unit}
              {quarantineItem.source?.number ? ` · ${quarantineItem.source.number}` : ''}
              {quarantineItem.source?.supplier_name ? ` · ${quarantineItem.source.supplier_name}` : ''}
              {unvalued > 0 ? ` · ${fmtNum(unvalued)} belum bernilai (reject GR, belum ditagih)` : ''}
            </div>
          </div>
        )}
        <div>
          <label className="text-xs text-muted-foreground block mb-1">Penyelesaian *</label>
          <SmartNativeSelect value={settlement} onChange={(e) => setSettlement(e.target.value)}
            className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-[var(--card-surface)]" data-testid="rtp-settlement">
            {SETTLEMENT_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </SmartNativeSelect>
          <p className="text-[11px] text-muted-foreground mt-1">{(SETTLEMENT_OPTIONS.find((o) => o.value === settlement) || {}).hint}</p>
        </div>
        {settlement === 'destroy' && (
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Ditanggung *</label>
            <SmartNativeSelect value={borne} onChange={(e) => setBorne(e.target.value)}
              className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-[var(--card-surface)]" data-testid="rtp-borne">
              <option value="supplier">Pemasok (tagihan dipotong lewat nota debit)</option>
              <option value="da">DA (dibebankan; reject GR menjadi bisa ditagih pemasok)</option>
            </SmartNativeSelect>
          </div>
        )}
        {needGr && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground block mb-1">GR asal * (harga & pemasok)</label>
              <SmartNativeSelect value={grId} onChange={(e) => { setGrId(e.target.value); setLineId(''); }}
                className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-[var(--card-surface)]" data-testid="rtp-gr">
                <option value="">— pilih GR —</option>
                {grs.map((g) => <option key={g.id} value={g.id}>{g.receipt_number} · {g.supplier_name || '-'}{g.po_number ? ` · ${g.po_number}` : ''}</option>)}
              </SmartNativeSelect>
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Baris GR *</label>
              <SmartNativeSelect value={lineId} onChange={(e) => setLineId(e.target.value)}
                className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-[var(--card-surface)]" data-testid="rtp-gr-line">
                <option value="">— pilih baris —</option>
                {grLines.map((li) => (
                  <option key={li.id || li.po_item_id} value={li.id || li.po_item_id}>
                    {li.sku || ''} {li.material_name || li.product_name} · @ {fmtRp(li.unit_price || li.unit_cost || 0)}
                  </option>
                ))}
              </SmartNativeSelect>
            </div>
          </div>
        )}
        {!fromQ && (
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Lokasi asal stok *</label>
            <SmartNativeSelect value={locId} onChange={(e) => setLocId(e.target.value)}
              className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-[var(--card-surface)]" data-testid="rtp-location">
              <option value="">— pilih lokasi —</option>
              {locs.map((l) => <option key={l.id} value={l.id}>{l.code ? `${l.code} · ` : ''}{l.name || l.code}</option>)}
            </SmartNativeSelect>
          </div>
        )}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Qty *</label>
            <GlassInput type="number" min="0" step="any" value={qty} onChange={(e) => setQty(e.target.value)} data-testid="rtp-qty" />
            {price > 0 && Number(qty) > 0 && (
              <p className="text-[11px] text-muted-foreground mt-1">Nilai pada harga GR: {fmtRp(Number(qty) * price)} (tanpa PPN — DA bukan PKP)</p>
            )}
          </div>
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Tanggal kirim</label>
            <GlassInput type="date" value={shipDate} onChange={(e) => setShipDate(e.target.value)} data-testid="rtp-ship-date" />
          </div>
        </div>
        <div>
          <label className="text-xs text-muted-foreground block mb-1">Alasan *</label>
          <GlassInput value={reason} onChange={(e) => setReason(e.target.value)} placeholder="mis. kain berlubang, salah warna" data-testid="rtp-reason" />
        </div>
        <div>
          <label className="text-xs text-muted-foreground block mb-1">Tautan foto bukti (pisahkan spasi)</label>
          <GlassInput value={photos} onChange={(e) => setPhotos(e.target.value)} placeholder="https://..." data-testid="rtp-photos" />
        </div>
        <div>
          <label className="text-xs text-muted-foreground block mb-1">Catatan</label>
          <GlassInput value={notes} onChange={(e) => setNotes(e.target.value)} data-testid="rtp-notes" />
        </div>
        {err && <div className="text-sm text-[hsl(var(--destructive))] bg-[hsl(var(--destructive)/0.15)]  rounded-lg px-3 py-2">{err}</div>}
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="outline" onClick={onClose}>Batal</Button>
          <Button onClick={submit} disabled={busy} data-testid="rtp-create-submit">{busy ? 'Menyimpan…' : 'Buat Retur (Draft)'}</Button>
        </div>
      </div>
    </Modal>
  );
}

function ReplacementModal({ token, rtp, onClose, onDone }) {
  const [locs, setLocs] = useState([]);
  const [locId, setLocId] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  useEffect(() => { apiGet(token, '/api/rahaza/storage-locations').then(setLocs).catch((e) => setErr(e.message)); }, [token]);
  const submit = async () => {
    if (!locId) { setErr('Pilih lokasi penerima'); return; }
    setBusy(true); setErr('');
    try {
      await apiPost(token, `/api/rahaza/purchase-returns/${rtp.id}/receive-replacement`, { location_id: locId });
      toast.success(`Pengganti ${rtp.rtp_number} diterima`);
      onDone();
    } catch (e) { setErr(e.message); setBusy(false); }
  };
  return (
    <Modal title={`Terima Barang Pengganti · ${rtp.rtp_number}`} onClose={onClose} size="sm">
      <div className="space-y-3 text-sm">
        <p className="text-xs text-muted-foreground">
          Barang pengganti masuk stok pada harga GR asal. Bagian yang dulu bernilai menutup klaim retur; bagian reject GR
          menjadi penerimaan susulan yang bisa ditagih pemasok.
        </p>
        <SmartNativeSelect value={locId} onChange={(e) => setLocId(e.target.value)}
          className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-[var(--card-surface)]" data-testid="rtp-replacement-location">
          <option value="">— lokasi penerima —</option>
          {locs.map((l) => <option key={l.id} value={l.id}>{l.code ? `${l.code} · ` : ''}{l.name || l.code}</option>)}
        </SmartNativeSelect>
        {err && <div className="text-sm text-[hsl(var(--destructive))] ">{err}</div>}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Batal</Button>
          <Button onClick={submit} disabled={busy}>{busy ? 'Memproses…' : 'Terima Pengganti'}</Button>
        </div>
      </div>
    </Modal>
  );
}

export default function PurchaseReturnModule({ token }) {
  const [rows, setRows] = useState([]);
  const [status, setStatus] = useState('all');
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [detail, setDetail] = useState(null);
  const [replacing, setReplacing] = useState(null);
  const [busy, setBusy] = useState('');

  const load = useCallback(async () => {
    setLoading(true); setErr('');
    try {
      const res = await apiGet(token, `/api/rahaza/purchase-returns?status=${status}`);
      setRows(res?.items || []);
    } catch (e) { setErr(e.message); }
    finally { setLoading(false); }
  }, [token, status]);
  useEffect(() => { load(); }, [load]);

  const act = async (rtp, path, msg) => {
    setBusy(rtp.id);
    try {
      const out = await apiPost(token, `/api/rahaza/purchase-returns/${rtp.id}/${path}`, {});
      const p = out?._posting;
      toast.success(`${msg} ${rtp.rtp_number}${p?.je_number ? ` · jurnal ${p.je_number}` : ''}${p && p.ok === false ? ` · jurnal GAGAL: ${p.error}` : ''}`);
      load();
    } catch (e) { toast.error(e.message); }
    finally { setBusy(''); }
  };

  return (
    <div className="space-y-4" data-testid="purchase-return-module">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold flex items-center gap-2"><Undo2 className="w-5 h-5" /> Retur Pembelian</h2>
          <p className="text-sm text-muted-foreground mt-1 max-w-3xl">
            Barang dikembalikan ke pemasok dengan penyelesaian yang jelas. Harga = harga GR asal; tanpa PPN (DA bukan PKP).
            Potong tagihan &amp; diterima dengan diskon diselesaikan Keuangan lewat <strong>Nota Debit</strong>; refund dicatat Keuangan saat uang masuk.
          </p>
        </div>
        <div className="flex gap-2">
          <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={load}><RefreshCw className="w-4 h-4" /></Button>
          <Button onClick={() => setShowCreate(true)} data-testid="rtp-new"><Plus className="w-4 h-4 mr-1" /> Retur dari Stok</Button>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        {[['all', 'Semua'], ['draft', 'Draft'], ['awaiting_settlement', 'Menunggu Penyelesaian'], ['settled', 'Selesai'], ['cancelled', 'Batal']].map(([k, l]) => (
          <button key={k} onClick={() => setStatus(k)}
            className={`px-3 py-1.5 rounded-full text-xs border ${status === k ? 'bg-primary/15 border-primary' : 'border-border'}`}
            data-testid={`rtp-filter-${k}`}>{l}</button>
        ))}
      </div>
      {err && <div className="text-sm text-[hsl(var(--destructive))] bg-[hsl(var(--destructive)/0.15)]  rounded-lg px-4 py-2">{err}</div>}
      <GlassCard className="overflow-x-auto p-0">
        <table className="w-full text-sm min-w-[900px]">
          <thead className="border-b border-border text-xs text-muted-foreground">
            <tr>
              <th className="text-left px-3 py-2">No. Retur</th><th className="text-left px-3 py-2">Pemasok · GR</th>
              <th className="text-left px-3 py-2">Penyelesaian</th><th className="text-right px-3 py-2">Qty</th>
              <th className="text-right px-3 py-2">Nilai (harga GR)</th><th className="text-center px-3 py-2">Status</th>
              <th className="text-center px-3 py-2">Umur</th><th className="text-right px-3 py-2">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan="8" className="px-3 py-6 text-center text-muted-foreground">Memuat…</td></tr>
            ) : rows.length === 0 ? (
              <tr><td colSpan="8" className="px-3 py-6 text-center text-muted-foreground">Belum ada Retur Pembelian.</td></tr>
            ) : rows.map((r) => (
              <tr key={r.id} className="border-b border-border" data-testid={`rtp-row-${r.id}`}>
                <td className="px-3 py-2"><button className="tabular-nums text-xs underline" onClick={() => setDetail(r)}>{r.rtp_number}</button>
                  <div className="text-[11px] text-muted-foreground">{fmtDate(r.created_at)}</div></td>
                <td className="px-3 py-2 text-xs">{r.supplier_name || '-'}<div className="text-muted-foreground">{r.gr_number}{r.po_number ? ` · ${r.po_number}` : ''}</div></td>
                <td className="px-3 py-2 text-xs">{settlementLabel(r.settlement)}{r.settlement === 'destroy' ? ` (${r.destroy_borne_by === 'da' ? 'DA' : 'pemasok'})` : ''}
                  {r.debit_note_number && <div className="text-muted-foreground">ND {r.debit_note_number}</div>}</td>
                <td className="px-3 py-2 text-right">{fmtNum(r.total_qty)}</td>
                <td className="px-3 py-2 text-right">{fmtRp(r.total_amount)}</td>
                <td className="px-3 py-2 text-center"><StatusBadge status={r.status} /></td>
                <td className="px-3 py-2 text-center text-xs">
                  <span className={r.status === 'awaiting_settlement' && r.age_days >= 14 ? 'text-[hsl(var(--destructive))]  font-semibold' : ''}>{r.age_days} hari</span>
                </td>
                <td className="px-3 py-2">
                  <div className="flex justify-end gap-1 flex-wrap">
                    {r.status === 'draft' && SHIPPING.includes(r.settlement) && (
                      <Button size="sm" disabled={busy === r.id} onClick={() => act(r, 'send', r.settlement === 'destroy' ? 'Dimusnahkan' : 'Dikirim')}
                        data-testid={`rtp-send-${r.id}`}><Send className="w-3.5 h-3.5 mr-1" />{r.settlement === 'destroy' ? 'Proses Musnah' : 'Kirim'}</Button>
                    )}
                    {r.status === 'draft' && (
                      <Button size="sm" variant="outline" disabled={busy === r.id} onClick={() => act(r, 'cancel', 'Dibatalkan')}
                        data-testid={`rtp-cancel-${r.id}`}><XCircle className="w-3.5 h-3.5" /></Button>
                    )}
                    {r.status === 'awaiting_settlement' && r.settlement === 'exchange' && (
                      <Button size="sm" onClick={() => setReplacing(r)} data-testid={`rtp-replace-${r.id}`}>
                        <PackageCheck className="w-3.5 h-3.5 mr-1" />Terima Pengganti</Button>
                    )}
                    {((r.status === 'awaiting_settlement' && ['debit_note', 'destroy', 'refund'].includes(r.settlement))
                      || (r.status === 'draft' && r.settlement === 'accept_discount')) && (
                      <span className="text-[11px] text-muted-foreground">Menunggu Keuangan ({r.settlement === 'refund' ? 'refund' : 'Nota Debit'})</span>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>

      {showCreate && (
        <PurchaseReturnCreateModal token={token} onClose={() => setShowCreate(false)}
          onSaved={() => { setShowCreate(false); load(); }} />
      )}
      {replacing && (
        <ReplacementModal token={token} rtp={replacing} onClose={() => setReplacing(null)}
          onDone={() => { setReplacing(null); load(); }} />
      )}
      {detail && (
        <Modal title={`Retur Pembelian ${detail.rtp_number}`} onClose={() => setDetail(null)} size="xl">
          <div className="space-y-3 text-sm" data-testid="rtp-detail">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
              <div><div className="text-muted-foreground">Pemasok</div>{detail.supplier_name}</div>
              <div><div className="text-muted-foreground">GR / PO</div>{detail.gr_number} {detail.po_number ? `· ${detail.po_number}` : ''}</div>
              <div><div className="text-muted-foreground">Penyelesaian</div>{settlementLabel(detail.settlement)}</div>
              <div><div className="text-muted-foreground">Status</div><StatusBadge status={detail.status} /></div>
            </div>
            <div className="text-xs"><span className="text-muted-foreground">Alasan:</span> {detail.reason}</div>
            <table className="w-full text-xs">
              <thead className="text-muted-foreground border-b border-border"><tr>
                <th className="text-left py-1">Material</th><th className="text-left py-1">Sumber</th><th className="text-right py-1">Qty</th>
                <th className="text-right py-1">Harga GR</th><th className="text-right py-1">Bernilai / belum</th><th className="text-right py-1">Klaim</th>
              </tr></thead>
              <tbody>
                {(detail.lines || []).map((ln) => (
                  <tr key={ln.id} className="border-b border-border">
                    <td className="py-1">{ln.material_code} · {ln.material_name}</td>
                    <td className="py-1">{ln.source === 'quarantine' ? 'Karantina' : 'Stok'}</td>
                    <td className="py-1 text-right">{fmtNum(ln.qty)} {ln.unit}</td>
                    <td className="py-1 text-right">{fmtRp(ln.gr_price)}</td>
                    <td className="py-1 text-right">{fmtNum(ln.valued_qty ?? ln.valued_qty_est)} / {fmtNum(ln.unvalued_qty ?? ln.unvalued_qty_est)}</td>
                    <td className="py-1 text-right">{fmtRp(ln.claim_amount || 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(detail.journals || []).length > 0 && (
              <div className="text-xs">
                <div className="font-medium mb-1">Jurnal</div>
                {detail.journals.map((j, i) => (
                  <div key={i}>{j.stage}: {j.je_number || (j.skipped ? 'tanpa jurnal' : `GAGAL — ${j.error || ''}`)}</div>
                ))}
              </div>
            )}
            <div className="text-xs">
              <div className="font-medium mb-1">Riwayat</div>
              {(detail.history || []).map((h, i) => (
                <div key={i} className="text-muted-foreground">{fmtDate(h.at)} · {h.by} · {h.action}{h.note ? ` — ${h.note}` : ''}</div>
              ))}
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

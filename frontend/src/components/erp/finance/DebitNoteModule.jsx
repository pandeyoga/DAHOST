/**
 * DebitNoteModule — Nota Debit (Portal Keuangan). 2026-11-02, keputusan owner K11.
 *
 * Keuangan menerbitkan Nota Debit atas Retur Pembelian (potong tagihan, diterima dengan diskon,
 * dimusnahkan atas tanggungan pemasok) dan mencatat refund. Jurnal (harga GR, selisih WAC → PPV):
 *   · sebelum faktur → Dr GRNI / Cr klaim (Tagihan dari GR otomatis lebih kecil);
 *   · sesudah faktur → Dr Hutang Usaha / Cr klaim (saldo hutang = faktur − nota debit).
 * DA bukan PKP → tanpa PPN retur. Cetak: tombol Cetak (cetak/simpan PDF dari browser).
 * Backend: /api/rahaza/debit-notes, /api/rahaza/purchase-returns/{id}/refund.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { FileMinus, Printer, RefreshCw, Wallet } from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import Modal from '../Modal';
import { toast } from 'sonner';
import { apiGet, apiPost, fmtDate, fmtNum, fmtRp } from '../procurement/procApi';
import { StatusBadge, SETTLEMENT_OPTIONS } from '../procurement/PurchaseReturnModule';
import { MoneyInput } from '@/components/ui/money-input';
import { todayWIB } from '@/lib/waktu';

const settlementLabel = (v) => (SETTLEMENT_OPTIONS.find((o) => o.value === v) || {}).label || v;
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function printDebitNote(dn) {
  const rows = (dn.lines || []).map((l) => `<tr><td>${esc(l.material_code)} ${esc(l.material_name)}</td>`
    + `<td style="text-align:right">${esc(fmtNum(l.qty))} ${esc(l.unit || '')}</td>`
    + `<td style="text-align:right">${esc(fmtRp(l.price))}</td>`
    + `<td style="text-align:right">${l.disc_price != null ? esc(fmtRp(l.disc_price)) : '-'}</td>`
    + `<td style="text-align:right">${esc(fmtRp(l.amount))}</td></tr>`).join('');
  const w = window.open('', '_blank', 'width=820,height=900');
  if (!w) { toast.error('Popup diblokir browser — izinkan popup untuk mencetak.'); return; }
  w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${esc(dn.dn_number)}</title>
    <style>body{font-family:Arial,sans-serif;font-size:12px;margin:32px;color:#111}h1{font-size:18px;margin:0}
    table{width:100%;border-collapse:collapse;margin-top:12px}td,th{border:1px solid #999;padding:6px}
    th{background:#eee;text-align:left}.meta td{border:none;padding:2px 8px 2px 0}</style></head><body>
    <h1>NOTA DEBIT</h1><div>CV. Dewi Aditya</div>
    <table class="meta"><tr><td>No.</td><td><b>${esc(dn.dn_number)}</b></td><td>Tanggal</td><td>${esc(dn.date)}</td></tr>
    <tr><td>Kepada</td><td>${esc(dn.supplier_name)}</td><td>Dasar retur</td><td>${esc(dn.rtp_number)} · GR ${esc(dn.gr_number)}${dn.po_number ? ` · ${esc(dn.po_number)}` : ''}</td></tr></table>
    <p>Tagihan Saudara kami kurangi sebagai berikut (${esc(settlementLabel(dn.settlement))}):</p>
    <table><tr><th>Barang</th><th>Qty</th><th>Harga GR</th><th>Harga diskon</th><th>Jumlah</th></tr>${rows}
    <tr><td colspan="4" style="text-align:right"><b>Total</b></td><td style="text-align:right"><b>${esc(fmtRp(dn.total_amount))}</b></td></tr>
    <tr><td colspan="4" style="text-align:right">PPN</td><td style="text-align:right">Rp 0 (${esc(dn.ppn_note || 'DA bukan PKP')})</td></tr></table>
    ${dn.notes ? `<p>Catatan: ${esc(dn.notes)}</p>` : ''}<p style="margin-top:48px">Keuangan,<br><br><br>${esc(dn.created_by_name || '')}</p>
    <script>window.onload=function(){window.print()}</script></body></html>`);
  w.document.close();
}

function IssueModal({ token, rtp, onClose, onDone }) {
  const [disc, setDisc] = useState('');
  const [date, setDate] = useState(todayWIB());
  const [notes, setNotes] = useState('');
  const [locs, setLocs] = useState([]);
  const [locId, setLocId] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const isDisc = rtp.settlement === 'accept_discount';
  const needLoc = isDisc && (rtp.lines || []).some((l) => l.source === 'quarantine');
  useEffect(() => {
    if (needLoc) apiGet(token, '/api/rahaza/storage-locations').then(setLocs).catch(() => {});
  }, [token, needLoc]);
  const preview = useMemo(() => (rtp.lines || []).reduce((s, l) => s + (isDisc
    ? Number(l.qty || 0) * (Number(l.gr_price || 0) - Number(disc || 0))
    : Number(l.qty || 0) * Number(l.gr_price || 0)), 0), [rtp, disc, isDisc]);
  const submit = async () => {
    if (isDisc && disc === '') { setErr('Harga setelah diskon wajib diisi'); return; }
    if (needLoc && !locId) { setErr('Pilih lokasi penyimpanan barang yang diterima'); return; }
    setBusy(true); setErr('');
    try {
      const dn = await apiPost(token, '/api/rahaza/debit-notes', {
        purchase_return_id: rtp.id, date, notes,
        disc_price: isDisc ? Number(disc) : undefined, to_location_id: needLoc ? locId : undefined,
      });
      toast.success(`Nota Debit ${dn.dn_number} terbit${dn.je_number ? ` · jurnal ${dn.je_number}` : ''}${dn.gl_error ? ` · jurnal GAGAL: ${dn.gl_error}` : ''}`);
      onDone(dn);
    } catch (e) { setErr(e.message); setBusy(false); }
  };
  return (
    <Modal title={`Terbitkan Nota Debit · ${rtp.rtp_number}`} onClose={onClose} size="md">
      <div className="space-y-3 text-sm" data-testid="dn-issue-modal">
        <div className="text-xs text-muted-foreground">
          {rtp.supplier_name} · GR {rtp.gr_number} · {settlementLabel(rtp.settlement)} · harga dasar = harga GR, tanpa PPN.
        </div>
        {isDisc && (
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Harga setelah diskon (per satuan) *</label>
            <MoneyInput decimals={2} glass value={disc} onChange={(e) => setDisc(e.target.value)} data-testid="dn-disc-price" />
          </div>
        )}
        {needLoc && (
          <SmartNativeSelect value={locId} onChange={(e) => setLocId(e.target.value)}
            className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-[var(--card-surface)]" data-testid="dn-location">
            <option value="">— lokasi penyimpanan barang yang diterima —</option>
            {locs.map((l) => <option key={l.id} value={l.id}>{l.code ? `${l.code} · ` : ''}{l.name || l.code}</option>)}
          </SmartNativeSelect>
        )}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Tanggal</label>
            <GlassInput type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </div>
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Nilai nota</label>
            <div className="h-9 flex items-center font-semibold">{fmtRp(preview)}</div>
          </div>
        </div>
        <GlassInput value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Catatan" />
        {err && <div className="text-sm text-red-700 dark:text-red-400">{err}</div>}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Batal</Button>
          <Button onClick={submit} disabled={busy} data-testid="dn-issue-submit">{busy ? 'Memproses…' : 'Terbitkan'}</Button>
        </div>
      </div>
    </Modal>
  );
}

function RefundModal({ token, rtp, onClose, onDone }) {
  const [accs, setAccs] = useState([]);
  const [accId, setAccId] = useState('');
  const [date, setDate] = useState(todayWIB());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  useEffect(() => { apiGet(token, '/api/rahaza/cash-accounts').then((r) => setAccs(Array.isArray(r) ? r : [])).catch(() => {}); }, [token]);
  const submit = async () => {
    if (!accId) { setErr('Pilih rekening penerima'); return; }
    setBusy(true); setErr('');
    try {
      await apiPost(token, `/api/rahaza/purchase-returns/${rtp.id}/refund`, { cash_account_id: accId, date });
      toast.success(`Refund ${rtp.rtp_number} dicatat`);
      onDone();
    } catch (e) { setErr(e.message); setBusy(false); }
  };
  return (
    <Modal title={`Catat Refund · ${rtp.rtp_number}`} onClose={onClose} size="sm">
      <div className="space-y-3 text-sm">
        <div className="text-xs text-muted-foreground">Klaim {fmtRp(rtp.total_claim_amount)} — Dr rekening / Cr klaim retur pemasok.</div>
        <SmartNativeSelect value={accId} onChange={(e) => setAccId(e.target.value)}
          className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-[var(--card-surface)]" data-testid="refund-account">
          <option value="">— rekening penerima —</option>
          {accs.map((a) => <option key={a.id} value={a.id}>{a.code ? `${a.code} · ` : ''}{a.name}</option>)}
        </SmartNativeSelect>
        <GlassInput type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        {err && <div className="text-sm text-red-700 dark:text-red-400">{err}</div>}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Batal</Button>
          <Button onClick={submit} disabled={busy}>{busy ? 'Memproses…' : 'Catat Refund'}</Button>
        </div>
      </div>
    </Modal>
  );
}

export default function DebitNoteModule({ token }) {
  const [tab, setTab] = useState('todo');
  const [rtps, setRtps] = useState([]);
  const [dns, setDns] = useState([]);
  const [bal, setBal] = useState({ items: [], total_net_payable: 0 });
  const [err, setErr] = useState('');
  const [issuing, setIssuing] = useState(null);
  const [refunding, setRefunding] = useState(null);

  const load = useCallback(async () => {
    setErr('');
    try {
      const [r, d, b] = await Promise.all([
        apiGet(token, '/api/rahaza/purchase-returns?status=all&limit=1000'),
        apiGet(token, '/api/rahaza/debit-notes?limit=1000'),
        apiGet(token, '/api/rahaza/debit-notes/supplier-balances'),
      ]);
      setRtps(r?.items || []); setDns(d?.items || []); setBal(b || { items: [] });
    } catch (e) { setErr(e.message); }
  }, [token]);
  useEffect(() => { load(); }, [load]);

  const todo = useMemo(() => rtps.filter((r) => (r.status === 'awaiting_settlement'
    && (r.settlement === 'debit_note' || r.settlement === 'refund' || (r.settlement === 'destroy' && r.destroy_borne_by === 'supplier')))
    || (r.status === 'draft' && r.settlement === 'accept_discount')), [rtps]);

  return (
    <div className="space-y-4" data-testid="debit-note-module">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold flex items-center gap-2"><FileMinus className="w-5 h-5" /> Nota Debit</h2>
          <p className="text-sm text-muted-foreground mt-1 max-w-3xl">
            Penyelesaian Retur Pembelian oleh Keuangan. Nota debit sebelum faktur mengurangi Hutang Belum Ditagih (GRNI) —
            Tagihan dari GR otomatis lebih kecil; sesudah faktur mengurangi Hutang Usaha. Tanpa PPN (DA bukan PKP).
          </p>
        </div>
        <Button variant="outline" onClick={load}><RefreshCw className="w-4 h-4" /></Button>
      </div>
      <div className="flex gap-2">
        {[['todo', `Perlu Diselesaikan (${todo.length})`], ['list', 'Nota Debit'], ['balance', 'Saldo Hutang per Pemasok']].map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)} className={`px-3 py-1.5 rounded-full text-xs border ${tab === k ? 'bg-primary/15 border-primary' : 'border-border'}`}
            data-testid={`dn-tab-${k}`}>{l}</button>
        ))}
      </div>
      {err && <div className="text-sm text-red-700 dark:text-red-400 bg-red-100 dark:bg-red-500/10 rounded-lg px-4 py-2">{err}</div>}

      {tab === 'todo' && (
        <GlassCard className="overflow-x-auto p-0">
          <table className="w-full text-sm min-w-[800px]">
            <thead className="border-b border-border text-xs text-muted-foreground"><tr>
              <th className="text-left px-3 py-2">Retur</th><th className="text-left px-3 py-2">Pemasok · GR</th>
              <th className="text-left px-3 py-2">Penyelesaian</th><th className="text-right px-3 py-2">Nilai</th>
              <th className="text-center px-3 py-2">Status</th><th className="text-center px-3 py-2">Umur</th><th className="text-right px-3 py-2">Aksi</th>
            </tr></thead>
            <tbody>
              {todo.length === 0 ? (
                <tr><td colSpan="7" className="px-3 py-6 text-center text-muted-foreground">Tidak ada retur yang menunggu Keuangan.</td></tr>
              ) : todo.map((r) => (
                <tr key={r.id} className="border-b border-border" data-testid={`dn-todo-${r.id}`}>
                  <td className="px-3 py-2 font-mono text-xs">{r.rtp_number}</td>
                  <td className="px-3 py-2 text-xs">{r.supplier_name}<div className="text-muted-foreground">{r.gr_number}</div></td>
                  <td className="px-3 py-2 text-xs">{settlementLabel(r.settlement)}</td>
                  <td className="px-3 py-2 text-right">{fmtRp(r.total_amount)}</td>
                  <td className="px-3 py-2 text-center"><StatusBadge status={r.status} /></td>
                  <td className="px-3 py-2 text-center text-xs">{r.age_days} hari</td>
                  <td className="px-3 py-2 text-right">
                    {r.settlement === 'refund' ? (
                      <Button size="sm" onClick={() => setRefunding(r)} data-testid={`dn-refund-${r.id}`}><Wallet className="w-3.5 h-3.5 mr-1" />Catat Refund</Button>
                    ) : (
                      <Button size="sm" onClick={() => setIssuing(r)} data-testid={`dn-issue-${r.id}`}><FileMinus className="w-3.5 h-3.5 mr-1" />Terbitkan Nota Debit</Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </GlassCard>
      )}

      {tab === 'list' && (
        <GlassCard className="overflow-x-auto p-0">
          <table className="w-full text-sm min-w-[800px]">
            <thead className="border-b border-border text-xs text-muted-foreground"><tr>
              <th className="text-left px-3 py-2">No. Nota</th><th className="text-left px-3 py-2">Tanggal</th>
              <th className="text-left px-3 py-2">Pemasok</th><th className="text-left px-3 py-2">Dasar</th>
              <th className="text-right px-3 py-2">Nilai</th><th className="text-right px-3 py-2">Kurangi Hutang</th>
              <th className="text-right px-3 py-2">Kurangi GRNI</th><th className="text-left px-3 py-2">Jurnal</th><th />
            </tr></thead>
            <tbody>
              {dns.length === 0 ? (
                <tr><td colSpan="9" className="px-3 py-6 text-center text-muted-foreground">Belum ada Nota Debit.</td></tr>
              ) : dns.map((d) => (
                <tr key={d.id} className="border-b border-border">
                  <td className="px-3 py-2 font-mono text-xs">{d.dn_number}</td>
                  <td className="px-3 py-2 text-xs">{d.date || fmtDate(d.created_at)}</td>
                  <td className="px-3 py-2 text-xs">{d.supplier_name}</td>
                  <td className="px-3 py-2 text-xs">{d.rtp_number} · {settlementLabel(d.settlement)}</td>
                  <td className="px-3 py-2 text-right">{fmtRp(d.total_amount)}</td>
                  <td className="px-3 py-2 text-right">{fmtRp(d.ap_amount)}</td>
                  <td className="px-3 py-2 text-right">{fmtRp(d.grni_amount)}</td>
                  <td className="px-3 py-2 text-xs">{d.je_number || (d.gl_error ? `GAGAL: ${d.gl_error}` : '—')}</td>
                  <td className="px-3 py-2 text-right"><Button size="sm" variant="outline" onClick={() => printDebitNote(d)}><Printer className="w-3.5 h-3.5" /></Button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </GlassCard>
      )}

      {tab === 'balance' && (
        <GlassCard className="overflow-x-auto p-0">
          <table className="w-full text-sm min-w-[700px]">
            <thead className="border-b border-border text-xs text-muted-foreground"><tr>
              <th className="text-left px-3 py-2">Pemasok</th><th className="text-right px-3 py-2">Sisa Faktur</th>
              <th className="text-right px-3 py-2">Nota Debit (hutang)</th><th className="text-right px-3 py-2">Saldo Hutang</th>
            </tr></thead>
            <tbody>
              {(bal.items || []).map((s) => (
                <tr key={`${s.supplier_id}-${s.supplier_name}`} className="border-b border-border">
                  <td className="px-3 py-2">{s.supplier_name || '-'}</td>
                  <td className="px-3 py-2 text-right">{fmtRp(s.invoice_balance)} <span className="text-[11px] text-muted-foreground">({s.invoice_count})</span></td>
                  <td className="px-3 py-2 text-right">{fmtRp(s.debit_note_ap)} <span className="text-[11px] text-muted-foreground">({s.debit_note_count})</span></td>
                  <td className={`px-3 py-2 text-right font-semibold ${s.net_payable < 0 ? 'text-emerald-700 dark:text-emerald-400' : ''}`}>{fmtRp(s.net_payable)}</td>
                </tr>
              ))}
              <tr><td className="px-3 py-2 font-semibold" colSpan="3">Total</td><td className="px-3 py-2 text-right font-bold">{fmtRp(bal.total_net_payable)}</td></tr>
            </tbody>
          </table>
          <p className="text-[11px] text-muted-foreground px-3 py-2">Saldo negatif = pemasok berutang ke DA (faktur sudah dibayar lalu terkena nota debit).</p>
        </GlassCard>
      )}

      {issuing && <IssueModal token={token} rtp={issuing} onClose={() => setIssuing(null)} onDone={() => { setIssuing(null); setTab('list'); load(); }} />}
      {refunding && <RefundModal token={token} rtp={refunding} onClose={() => setRefunding(null)} onDone={() => { setRefunding(null); load(); }} />}
    </div>
  );
}

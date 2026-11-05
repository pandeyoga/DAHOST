/**
 * DebitNoteModule — Nota Debit (Portal Keuangan). 2026-11-02, keputusan owner K11.
 *
 * Keuangan menerbitkan Nota Debit atas Retur Pembelian (potong tagihan, diterima dengan diskon,
 * dimusnahkan atas tanggungan pemasok) dan mencatat refund. Jurnal (harga GR, selisih WAC → PPV):
 *   · sebelum faktur → Dr GRNI / Cr klaim (Tagihan dari GR otomatis lebih kecil);
 *   · sesudah faktur → Dr Hutang Usaha / Cr klaim (saldo hutang = faktur − nota debit).
 * DA bukan PKP → tanpa PPN retur. Cetak: tombol Cetak (cetak/simpan PDF dari browser).
 * Backend: /api/rahaza/debit-notes, /api/rahaza/purchase-returns/{id}/refund.
 *
 * 2026-11-05 (PANDUAN_UI G1/G3/G10): cetakan PageLayout — pil penyaring di toolbar kiri, muat ulang di kanan;
 * tombol di baris tabel bergaris (dulu tombol utama berulang); tampilan kosong memakai EmptyState.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { EmptyState, Notice } from '../moduleAtoms';
import PageLayout from '../layout/PageLayout';
import FilterChips from '@/components/ui/filter-chips';
import { AlertCircle, FileMinus, Printer, RefreshCw, Scale, Undo2, Wallet } from 'lucide-react';
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
    <style>body{font-family:Arial,sans-serif;font-size:12px;margin:32px;color:#111}.doc-title{font-size:18px;font-weight:bold;margin:0}
    table{width:100%;border-collapse:collapse;margin-top:12px}td,th{border:1px solid #999;padding:6px}
    th{background:#eee;text-align:left}.meta td{border:none;padding:2px 8px 2px 0}</style></head><body>
    <div class="doc-title">NOTA DEBIT</div><div>CV. Dewi Aditya</div>
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
    <Modal title={`Terbitkan nota debit · ${rtp.rtp_number}`} onClose={onClose} size="md">
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
        {err && <div className="text-sm text-[hsl(var(--destructive))]">{err}</div>}
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
    <Modal title={`Catat refund · ${rtp.rtp_number}`} onClose={onClose} size="sm">
      <div className="space-y-3 text-sm">
        <div className="text-xs text-muted-foreground">Klaim {fmtRp(rtp.total_claim_amount)} — Dr rekening / Cr klaim retur pemasok.</div>
        <SmartNativeSelect value={accId} onChange={(e) => setAccId(e.target.value)}
          className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-[var(--card-surface)]" data-testid="refund-account">
          <option value="">— rekening penerima —</option>
          {accs.map((a) => <option key={a.id} value={a.id}>{a.code ? `${a.code} · ` : ''}{a.name}</option>)}
        </SmartNativeSelect>
        <GlassInput type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        {err && <div className="text-sm text-[hsl(var(--destructive))]">{err}</div>}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Batal</Button>
          <Button onClick={submit} disabled={busy}>{busy ? 'Memproses…' : 'Catat refund'}</Button>
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
  const balItems = bal.items || [];

  return (
    <PageLayout
      testId="debit-note-module"
      title="Nota Debit (Retur)"
      subtitle="Penyelesaian retur pembelian: mengurangi hutang ke pemasok (sebelum faktur: hutang belum ditagih)."
      filters={
        <FilterChips value={tab} onChange={setTab} testId="dn-tab" ariaLabel="Tampilan" hideWhenEmpty={false}
          options={[
            { key: 'todo', label: 'Perlu diselesaikan', count: todo.length },
            { key: 'list', label: 'Sudah terbit', count: dns.length },
            { key: 'balance', label: 'Saldo per pemasok', count: balItems.length },
          ]} />
      }
      tools={<Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={load}><RefreshCw className="w-4 h-4" /></Button>}
      summary={err && <Notice tone="danger" icon={AlertCircle}>{err}</Notice>}
    >
      {tab === 'todo' && (
        <GlassCard className="overflow-x-auto p-0">
          {todo.length === 0 ? (
            <EmptyState icon={Undo2} title="Tidak ada retur yang menunggu Keuangan"
              description="Retur pembelian yang perlu nota debit atau refund akan muncul di sini." />
          ) : (
            <table className="w-full text-sm min-w-[800px]">
              <thead className="border-b border-border text-xs text-muted-foreground"><tr>
                <th className="text-left px-3 py-2">Retur</th><th className="text-left px-3 py-2">Pemasok · GR</th>
                <th className="text-left px-3 py-2">Penyelesaian</th><th className="text-right px-3 py-2">Nilai</th>
                <th className="text-center px-3 py-2">Status</th><th className="text-right px-3 py-2">Umur</th><th className="text-right px-3 py-2">Aksi</th>
              </tr></thead>
              <tbody>
                {todo.map((r) => (
                  <tr key={r.id} className="border-b border-border" data-testid={`dn-todo-${r.id}`}>
                    <td className="px-3 py-2 text-xs whitespace-nowrap">{r.rtp_number}</td>
                    <td className="px-3 py-2 text-xs">{r.supplier_name}<div className="text-muted-foreground whitespace-nowrap">{r.gr_number}</div></td>
                    <td className="px-3 py-2 text-xs">{settlementLabel(r.settlement)}</td>
                    <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap">{fmtRp(r.total_amount)}</td>
                    <td className="px-3 py-2 text-center"><StatusBadge status={r.status} /></td>
                    <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap text-xs">{r.age_days} hari</td>
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      {r.settlement === 'refund' ? (
                        <Button size="sm" variant="outline" onClick={() => setRefunding(r)} data-testid={`dn-refund-${r.id}`}><Wallet className="w-3.5 h-3.5" />Catat refund</Button>
                      ) : (
                        <Button size="sm" variant="outline" onClick={() => setIssuing(r)} data-testid={`dn-issue-${r.id}`}><FileMinus className="w-3.5 h-3.5" />Terbitkan nota debit</Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </GlassCard>
      )}

      {tab === 'list' && (
        <GlassCard className="overflow-x-auto p-0">
          {dns.length === 0 ? (
            <EmptyState icon={FileMinus} title="Belum ada nota debit"
              description="Nota debit muncul setelah diterbitkan dari daftar Perlu diselesaikan." />
          ) : (
            <table className="w-full text-sm min-w-[800px]">
              <thead className="border-b border-border text-xs text-muted-foreground"><tr>
                <th className="text-left px-3 py-2">No. nota</th><th className="text-left px-3 py-2">Tanggal</th>
                <th className="text-left px-3 py-2">Pemasok</th><th className="text-left px-3 py-2">Dasar</th>
                <th className="text-right px-3 py-2">Nilai</th><th className="text-right px-3 py-2">Kurangi hutang</th>
                <th className="text-right px-3 py-2">Kurangi hutang belum ditagih</th><th className="text-left px-3 py-2">Jurnal</th><th />
              </tr></thead>
              <tbody>
                {dns.map((d) => (
                  <tr key={d.id} className="border-b border-border">
                    <td className="px-3 py-2 text-xs whitespace-nowrap">{d.dn_number}</td>
                    <td className="px-3 py-2 text-xs whitespace-nowrap">{fmtDate(d.date || d.created_at)}</td>
                    <td className="px-3 py-2 text-xs">{d.supplier_name}</td>
                    <td className="px-3 py-2 text-xs">{d.rtp_number} · {settlementLabel(d.settlement)}</td>
                    <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap">{fmtRp(d.total_amount)}</td>
                    <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap">{fmtRp(d.ap_amount)}</td>
                    <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap">{fmtRp(d.grni_amount)}</td>
                    <td className="px-3 py-2 text-xs">{d.je_number
                      ? <span className="whitespace-nowrap">{d.je_number}</span>
                      : (d.gl_error ? <span className="text-[hsl(var(--destructive))]">Gagal: {d.gl_error}</span> : '—')}</td>
                    <td className="px-3 py-2 text-right">
                      <Button size="icon-sm" variant="ghost" onClick={() => printDebitNote(d)} title="Cetak nota debit" aria-label="Cetak nota debit"><Printer className="w-3.5 h-3.5" /></Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </GlassCard>
      )}

      {tab === 'balance' && (
        <GlassCard className="overflow-x-auto p-0">
          {balItems.length === 0 ? (
            <EmptyState icon={Scale} title="Belum ada saldo pemasok"
              description="Saldo hutang per pemasok setelah dikurangi nota debit akan tampil di sini." />
          ) : (
            <>
              <table className="w-full text-sm min-w-[700px]">
                <thead className="border-b border-border text-xs text-muted-foreground"><tr>
                  <th className="text-left px-3 py-2">Pemasok</th><th className="text-right px-3 py-2">Sisa faktur</th>
                  <th className="text-right px-3 py-2">Nota debit (hutang)</th><th className="text-right px-3 py-2">Saldo hutang</th>
                </tr></thead>
                <tbody>
                  {balItems.map((s) => (
                    <tr key={`${s.supplier_id}-${s.supplier_name}`} className="border-b border-border">
                      <td className="px-3 py-2">{s.supplier_name || '-'}</td>
                      <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap">{fmtRp(s.invoice_balance)} <span className="text-[11px] text-muted-foreground">({s.invoice_count})</span></td>
                      <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap">{fmtRp(s.debit_note_ap)} <span className="text-[11px] text-muted-foreground">({s.debit_note_count})</span></td>
                      <td className={`px-3 py-2 text-right tabular-nums whitespace-nowrap font-semibold ${s.net_payable < 0 ? 'text-[hsl(var(--success))]' : ''}`}>{fmtRp(s.net_payable)}</td>
                    </tr>
                  ))}
                  <tr><td className="px-3 py-2 font-semibold" colSpan="3">Total</td><td className="px-3 py-2 text-right tabular-nums whitespace-nowrap font-bold">{fmtRp(bal.total_net_payable)}</td></tr>
                </tbody>
              </table>
              <p className="text-[11px] text-muted-foreground px-3 py-2">Saldo negatif = pemasok berutang ke DA (faktur sudah dibayar lalu terkena nota debit).</p>
            </>
          )}
        </GlassCard>
      )}

      {issuing && <IssueModal token={token} rtp={issuing} onClose={() => setIssuing(null)} onDone={() => { setIssuing(null); setTab('list'); load(); }} />}
      {refunding && <RefundModal token={token} rtp={refunding} onClose={() => setRefunding(null)} onDone={() => { setRefunding(null); load(); }} />}
    </PageLayout>
  );
}

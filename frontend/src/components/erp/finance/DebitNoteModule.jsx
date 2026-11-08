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
 * 2026-11-08 (Standar UI/UX v2): form terbitkan nota debit & catat refund = FormPopup pendek + DatePicker; ketiga
 * tabel bisa diunduh Excel/CSV; ukuran huruf & warna standar. (Halaman cetak nota memakai gaya cetak sendiri.)
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { EmptyState, Notice } from '../moduleAtoms';
import PageLayout from '../layout/PageLayout';
import FilterChips from '@/components/ui/filter-chips';
import { AlertCircle, FileMinus, Printer, RefreshCw, Scale, Undo2, Wallet } from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import TombolUnduh from '@/components/ui/tombol-unduh';
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
    <FormPopup open onClose={onClose} ukuran="pendek" testId="dn-issue-modal"
      judul={`Terbitkan nota debit · ${rtp.rtp_number}`}
      keterangan={`${rtp.supplier_name} · GR ${rtp.gr_number} · ${settlementLabel(rtp.settlement)} · harga dasar = harga GR, tanpa PPN.`}
      onSimpan={submit} menyimpan={busy} galat={err} labelSimpan="Terbitkan">
      {isDisc && (
        <Isian label="Harga setelah diskon (per satuan)" wajib>
          <MoneyInput decimals={2} glass value={disc} onChange={(e) => setDisc(e.target.value)} data-testid="dn-disc-price" />
        </Isian>
      )}
      {needLoc && (
        <Isian label="Lokasi penyimpanan barang yang diterima" wajib>
          <SmartNativeSelect value={locId} onChange={(e) => setLocId(e.target.value)} className="h-9 w-full" data-testid="dn-location">
            <option value="">— pilih lokasi —</option>
            {locs.map((l) => <option key={l.id} value={l.id}>{l.code ? `${l.code} · ` : ''}{l.name || l.code}</option>)}
          </SmartNativeSelect>
        </Isian>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Isian label="Tanggal">
          <DatePicker value={date} onChange={(v) => setDate(v || todayWIB())} bolehKosong={false} testId="dn-date" />
        </Isian>
        <Isian label="Nilai nota">
          <div className="h-9 flex items-center font-semibold tabular-nums">{fmtRp(preview)}</div>
        </Isian>
      </div>
      <Isian label="Catatan">
        <GlassInput value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Opsional" />
      </Isian>
    </FormPopup>
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
    <FormPopup open onClose={onClose} ukuran="pendek" testId="dn-refund-modal"
      judul={`Catat refund · ${rtp.rtp_number}`} keterangan={`Klaim ${fmtRp(rtp.total_claim_amount)} — Dr rekening / Cr klaim retur pemasok.`}
      onSimpan={submit} menyimpan={busy} galat={err} labelSimpan="Catat refund">
      <Isian label="Rekening penerima" wajib>
        <SmartNativeSelect value={accId} onChange={(e) => setAccId(e.target.value)} className="h-9 w-full" data-testid="refund-account">
          <option value="">— pilih rekening —</option>
          {accs.map((a) => <option key={a.id} value={a.id}>{a.code ? `${a.code} · ` : ''}{a.name}</option>)}
        </SmartNativeSelect>
      </Isian>
      <Isian label="Tanggal">
        <DatePicker value={date} onChange={(v) => setDate(v || todayWIB())} bolehKosong={false} testId="refund-date" />
      </Isian>
    </FormPopup>
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
      tools={<>
        {tab === 'todo' && (
          <TombolUnduh namaBerkas="retur-perlu-diselesaikan" namaLembar="Perlu diselesaikan" baris={todo} testId="dn-unduh"
            kolom={[
              { label: 'Retur', nilai: (r) => r.rtp_number },
              { label: 'Pemasok', nilai: (r) => r.supplier_name },
              { label: 'GR', nilai: (r) => r.gr_number || '' },
              { label: 'Penyelesaian', nilai: (r) => settlementLabel(r.settlement) },
              { label: 'Nilai', nilai: (r) => Number(r.total_amount) || 0 },
              { label: 'Umur (hari)', nilai: (r) => Number(r.age_days) || 0 },
            ]} />
        )}
        {tab === 'list' && (
          <TombolUnduh namaBerkas="nota-debit" namaLembar="Nota debit" baris={dns} testId="dn-unduh"
            kolom={[
              { label: 'No. nota', nilai: (d) => d.dn_number },
              { label: 'Tanggal', nilai: (d) => fmtDate(d.date || d.created_at) },
              { label: 'Pemasok', nilai: (d) => d.supplier_name },
              { label: 'Retur', nilai: (d) => d.rtp_number },
              { label: 'Penyelesaian', nilai: (d) => settlementLabel(d.settlement) },
              { label: 'Nilai', nilai: (d) => Number(d.total_amount) || 0 },
              { label: 'Kurangi hutang', nilai: (d) => Number(d.ap_amount) || 0 },
              { label: 'Kurangi hutang belum ditagih', nilai: (d) => Number(d.grni_amount) || 0 },
              { label: 'Jurnal', nilai: (d) => d.je_number || (d.gl_error ? `Gagal: ${d.gl_error}` : '') },
            ]} />
        )}
        {tab === 'balance' && (
          <TombolUnduh namaBerkas="saldo-hutang-per-pemasok" namaLembar="Saldo pemasok" baris={balItems} testId="dn-unduh"
            kolom={[
              { label: 'Pemasok', nilai: (x) => x.supplier_name || '' },
              { label: 'Sisa faktur', nilai: (x) => Number(x.invoice_balance) || 0 },
              { label: 'Jumlah faktur', nilai: (x) => Number(x.invoice_count) || 0 },
              { label: 'Nota debit (hutang)', nilai: (x) => Number(x.debit_note_ap) || 0 },
              { label: 'Jumlah nota debit', nilai: (x) => Number(x.debit_note_count) || 0 },
              { label: 'Saldo hutang', nilai: (x) => Number(x.net_payable) || 0 },
            ]} />
        )}
        <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={load}><RefreshCw className="w-4 h-4" /></Button>
      </>}
      summary={err && <Notice tone="danger" icon={AlertCircle}>{err}</Notice>}
    >
      {tab === 'todo' && (
        <GlassCard className="overflow-x-auto p-0">
          {todo.length === 0 ? (
            <EmptyState icon={Undo2} title="Tidak ada retur yang menunggu Keuangan"
              description="Retur pembelian yang perlu nota debit atau refund akan muncul di sini." />
          ) : (
            <table className="w-full text-sm min-w-[800px]">
              <thead><tr>
                <th className="text-left">Retur</th><th className="text-left">Pemasok · GR</th>
                <th className="text-left">Penyelesaian</th><th className="text-right">Nilai</th>
                <th className="text-center">Status</th><th className="text-right">Umur</th><th className="text-right">Aksi</th>
              </tr></thead>
              <tbody>
                {todo.map((r) => (
                  <tr key={r.id} className="border-b border-border" data-testid={`dn-todo-${r.id}`}>
                    <td className="whitespace-nowrap">{r.rtp_number}</td>
                    <td>{r.supplier_name}<div className="text-muted-foreground whitespace-nowrap">{r.gr_number}</div></td>
                    <td>{settlementLabel(r.settlement)}</td>
                    <td className="text-right tabular-nums whitespace-nowrap">{fmtRp(r.total_amount)}</td>
                    <td className="text-center"><StatusBadge status={r.status} /></td>
                    <td className="text-right tabular-nums whitespace-nowrap">{r.age_days} hari</td>
                    <td className="text-right whitespace-nowrap">
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
              <thead><tr>
                <th className="text-left">No. nota</th><th className="text-left">Tanggal</th>
                <th className="text-left">Pemasok</th><th className="text-left">Dasar</th>
                <th className="text-right">Nilai</th><th className="text-right">Kurangi hutang</th>
                <th className="text-right">Kurangi hutang belum ditagih</th><th className="text-left">Jurnal</th><th />
              </tr></thead>
              <tbody>
                {dns.map((d) => (
                  <tr key={d.id} className="border-b border-border">
                    <td className="whitespace-nowrap">{d.dn_number}</td>
                    <td className="whitespace-nowrap">{fmtDate(d.date || d.created_at)}</td>
                    <td>{d.supplier_name}</td>
                    <td>{d.rtp_number} · {settlementLabel(d.settlement)}</td>
                    <td className="text-right tabular-nums whitespace-nowrap">{fmtRp(d.total_amount)}</td>
                    <td className="text-right tabular-nums whitespace-nowrap">{fmtRp(d.ap_amount)}</td>
                    <td className="text-right tabular-nums whitespace-nowrap">{fmtRp(d.grni_amount)}</td>
                    <td>{d.je_number
                      ? <span className="whitespace-nowrap">{d.je_number}</span>
                      : (d.gl_error ? <span className="text-[hsl(var(--danger-text))]">Gagal: {d.gl_error}</span> : '—')}</td>
                    <td className="text-right">
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
                <thead><tr>
                  <th className="text-left">Pemasok</th><th className="text-right">Sisa faktur</th>
                  <th className="text-right">Nota debit (hutang)</th><th className="text-right">Saldo hutang</th>
                </tr></thead>
                <tbody>
                  {balItems.map((s) => (
                    <tr key={`${s.supplier_id}-${s.supplier_name}`} className="border-b border-border">
                      <td>{s.supplier_name || '-'}</td>
                      <td className="text-right tabular-nums whitespace-nowrap">{fmtRp(s.invoice_balance)} <span className="text-xs text-muted-foreground">({s.invoice_count})</span></td>
                      <td className="text-right tabular-nums whitespace-nowrap">{fmtRp(s.debit_note_ap)} <span className="text-xs text-muted-foreground">({s.debit_note_count})</span></td>
                      <td className={`text-right tabular-nums whitespace-nowrap font-semibold ${s.net_payable < 0 ? 'text-[hsl(var(--success-text))]' : ''}`}>{fmtRp(s.net_payable)}</td>
                    </tr>
                  ))}
                  <tr><td className="font-semibold" colSpan="3">Total</td><td className="text-right tabular-nums whitespace-nowrap font-bold">{fmtRp(bal.total_net_payable)}</td></tr>
                </tbody>
              </table>
              <p className="text-xs text-muted-foreground px-3 py-2">Saldo negatif = pemasok berutang ke DA (faktur sudah dibayar lalu terkena nota debit).</p>
            </>
          )}
        </GlassCard>
      )}

      {issuing && <IssueModal token={token} rtp={issuing} onClose={() => setIssuing(null)} onDone={() => { setIssuing(null); setTab('list'); load(); }} />}
      {refunding && <RefundModal token={token} rtp={refunding} onClose={() => setRefunding(null)} onDone={() => { setRefunding(null); load(); }} />}
    </PageLayout>
  );
}

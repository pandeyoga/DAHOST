/**
 * Faktur Penjualan (menu Keuangan › Penjualan & Penerimaan) — daftar faktur piutang (AR) kanonik.
 *
 * 2026-11-04 (keputusan owner): faktur DIBUAT di Portal Penjualan (Nota Penjualan — stok FG keluar
 * + HPP + faktur) dan di Maklon. Layar ini untuk Keuangan: menerbitkan draf, mencatat pembayaran,
 * melihat riwayat & statement pelanggan. Form "Invoice Baru" (teks bebas, tanpa stok/HPP) dilepas
 * supaya penjualan reseller tidak bisa tercatat tanpa stok keluar. Endpoint POST /ar-invoices tetap.
 *
 * 2026-11-05 (PANDUAN_UI G1/G13): cetakan PageLayout. Rekening koran pelanggan dibuka DI HALAMAN di atas
 * tabel, riwayat pembayaran di bawah baris fakturnya — dulu keduanya popup. Sel uang/tanggal tidak turun baris.
 */
import { Fragment, useState, useEffect, useCallback, useReducer, useMemo } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { AlertCircle, RefreshCw, FileText, DollarSign, Calendar, Users, Store, History } from 'lucide-react';
import { PaymentHistoryList } from './PaymentHistoryModal';
import CashAccountSelect, { usePaymentCashAccounts } from './SdmCashAccountSelect';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { StatusBadge, EmptyState, Notice } from './moduleAtoms';
import PageLayout, { DetailPanel, RowDetail } from './layout/PageLayout';
import PeriodPicker, { periodFromPreset } from './finance/PeriodPicker';
import Modal from './Modal';
import { toast } from 'sonner';
import { Skeleton } from '@/components/ui/skeleton';
import { formatRupiah, formatDateID } from '@/lib/format';
import { MoneyInput } from '@/components/ui/money-input';
import { todayWIB } from '@/lib/waktu';

const fmt = formatRupiah;

// Nama status untuk pengguna (server memakai kode Inggris). `issued`/`sent` = sudah terbit, belum lunas.
const AR_STATUS = {
  draft:        { label: 'Draf',              tone: 'muted' },
  // 2026-11-06 (Tahap 2): piutang maklon terjadwal — PO dikonfirmasi, barang belum (semua) dikirim
  scheduled:    { label: 'Terjadwal',         tone: 'info' },
  sent:         { label: 'Terbit',            tone: 'info' },
  issued:       { label: 'Terbit',            tone: 'info' },
  overdue:      { label: 'Lewat jatuh tempo', tone: 'danger' },
  partial_paid: { label: 'Dibayar sebagian',  tone: 'warning' },
  paid:         { label: 'Lunas',             tone: 'success' },
  cancelled:    { label: 'Dibatalkan',        tone: 'muted' },
  void:         { label: 'Dibatalkan',        tone: 'muted' },
  written_off:  { label: 'Dihapusbukukan',    tone: 'danger' },
};
function ArStatusBadge({ status }) {
  const m = AR_STATUS[(status || '').toLowerCase()];
  return m ? <StatusBadge status={m.label} tone={m.tone} /> : <StatusBadge status={status} />;
}

const _INIT = { invoices: [], customers: [], channels: [], loading: true };
function _reducer(s, a) {
  if (a.type === 'loaded') return { ...s, ...a.data, loading: false };
  if (a.type === 'loading') return { ...s, loading: true };
  return s;
}

// PANDUAN_UI G8 (2026-11-05): label saluran netral — dulu warna per platform (oranye/merah muda/hijau/biru)
// yang bertabrakan dengan arti warna status (hijau = lunas, merah = masalah). Nama saluran sudah tertulis.
function ChannelBadge({ channel, channels }) {
  if (!channel) return null;
  const ch = channels.find(c => c.channel_key === channel);
  if (!ch) return <span className="text-xs text-muted-foreground">{channel}</span>;
  return (
    <span className="inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full border bg-[var(--glass-bg)] text-foreground/70 border-[var(--glass-border)] whitespace-nowrap">
      <Store size={9} />
      {ch.channel_label}
    </span>
  );
}

export default function RahazaARInvoicesModule({ token }) {
  const [{ invoices, customers, channels, loading }, dispatch] = useReducer(_reducer, _INIT);
  // rekening kas/bank aktif — pemilih bersama yang sama dengan bayar hutang, gaji, kasbon (SSOT)
  const { accounts, loaded: accountsLoaded } = usePaymentCashAccounts(token);
  const [paying, setPaying] = useState(null);
  const [historyInv, setHistoryInv] = useState(null);
  const [showStatement, setShowStatement] = useState(false);
  const [error, setError] = useState('');
  const [tick, setTick] = useState(0);

  const hdrs = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);
  const refresh = useCallback(() => setTick(t => t + 1), []);

  useEffect(() => {
    let x = false;
    dispatch({ type: 'loading' });
    const h = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
    Promise.all([
      fetch('/api/rahaza/ar-invoices', { headers: h }).then(r => r.json()),
      fetch('/api/rahaza/customers', { headers: h }).then(r => r.json()),
      fetch('/api/rahaza/channel-gl-mapping', { headers: h }).then(r => r.json()),
    ]).then(([inv, cs, chs]) => {
      if (x) return;
      dispatch({ type: 'loaded', data: {
        invoices: Array.isArray(inv) ? inv : [],
        customers: Array.isArray(cs) ? cs : [],
        channels: Array.isArray(chs) ? chs : [],
      }});
    }).catch(() => { if (!x) dispatch({ type: 'loaded', data: {} }); });
    return () => { x = true; };
  }, [token, tick]);

  const changeStatus = useCallback(async (id, status) => {
    const r = await fetch(`/api/rahaza/ar-invoices/${id}/status`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    });
    if (!r.ok) { const d = await r.json().catch(() => ({})); setError(d.detail || `Gagal mengubah status faktur (HTTP ${r.status})`); }
    setTick(t => t + 1);
  }, [token]);

  const sendInvoice = useCallback(async (id) => {
    setError('');
    const r = await fetch(`/api/rahaza/ar-invoices/${id}/send`, { method: 'POST', headers: hdrs });
    if (!r.ok) { setError(`Gagal menerbitkan faktur (HTTP ${r.status})`); return; }
    const data = await r.json();
    if (data._posting_result && !data._posting_result.ok) {
      setError(`Faktur terbit, tetapi pencatatan jurnal gagal: ${data._posting_result.error}`);
    }
    setTick(t => t + 1);
  }, [hdrs]);

  const recordPayment = useCallback(async (id, payload) => {
    const r = await fetch(`/api/rahaza/ar-invoices/${id}/payment`, {
      method: 'POST', headers: hdrs, body: JSON.stringify(payload),
    });
    if (r.ok) {
      const d = await r.json().catch(() => ({}));
      setPaying(null); setTick(t => t + 1);
      if (d._posting_result && !d._posting_result.ok) toast.error(`Pembayaran tercatat, tetapi jurnal GAGAL: ${d._posting_result.error}`);
      else toast.success(`Pembayaran dicatat${d._posting_result?.je_number ? ` · JE ${d._posting_result.je_number}` : ''}.`);
    }
    else {
      const d = await r.json().catch(() => ({}));
      setError(d.detail || `Gagal catat pembayaran (HTTP ${r.status})`);
    }
  }, [hdrs]);

  const unpaidInvoices = invoices.filter(i => i.status !== 'paid' && i.balance > 0);
  const totalOutstanding = unpaidInvoices.reduce((s, i) => s + (i.balance || 0), 0);
  // 2026-11-04: semua uang yang sudah diterima, termasuk cicilan (dulu hanya total faktur yang LUNAS)
  const totalPaid = invoices.reduce((s, i) => s + Number(i.paid_amount || 0), 0);

  return (
    <PageLayout
      testId="rahaza-ar-invoices-page"
      title="Faktur Penjualan"
      subtitle="Faktur reseller & maklon. Dibuat dari Nota Penjualan atau Maklon; di sini diterbitkan dan dicatat pembayarannya."
      actions={<Button variant="outline" onClick={() => setShowStatement(v => !v)} aria-expanded={showStatement} data-testid="ar-open-statement"><Users className="w-4 h-4" />Rekening koran</Button>}
      tools={<Button size="icon" variant="outline" onClick={refresh} title="Muat ulang" aria-label="Muat ulang"><RefreshCw className="w-4 h-4" /></Button>}
      summary={(error || invoices.length > 0) && <>
        {error && (
          <Notice tone="danger" icon={AlertCircle}
            action={<Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={() => setError('')}>Tutup</Button>}>
            {error}
          </Notice>
        )}
        {/* PANDUAN_UI G5 (2026-11-04): ringkasan satu baris — dulu 4 kartu 4 warna yang mengulang tab Umur piutang */}
        {invoices.length > 0 && (
          <p className="text-sm text-muted-foreground" data-testid="ar-summary">
            {invoices.length} faktur · <b className="text-foreground">{unpaidInvoices.length}</b> belum lunas, sisa <b className="text-foreground tabular-nums">{fmt(totalOutstanding)}</b> · sudah diterima <b className="text-foreground tabular-nums">{fmt(totalPaid)}</b>
          </p>
        )}
      </>}
      detail={showStatement && <CustomerStatementPanel token={token} customers={customers} onClose={() => setShowStatement(false)} />}
    >
      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <div className="space-y-2 p-4">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-12 rounded-lg" />)}</div>
        ) : invoices.length === 0 ? (
          <EmptyState icon={FileText} title="Belum ada faktur" description="Faktur muncul di sini setelah dibuat dari Portal Penjualan › Nota Penjualan atau dari Maklon." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-[var(--glass-bg)]">
                <tr className="text-left text-[10px] uppercase tracking-wider text-foreground/50">
                  <th className="px-4 py-3">No. faktur</th>
                  <th className="px-3 py-3">Saluran</th>
                  <th className="px-3 py-3">Pelanggan</th>
                  <th className="px-3 py-3">Terbit</th>
                  <th className="px-3 py-3">Status</th>
                  <th className="px-3 py-3 text-right">Total</th>
                  <th className="px-3 py-3 text-right">Sisa</th>
                  <th className="px-3 py-3 text-right">Aksi</th>
                </tr>
              </thead>
              <tbody>
                {invoices.map((inv, idx) => {
                  const histOpen = historyInv?.id === inv.id;
                  return (
                    <Fragment key={inv.id}>
                      <tr className={`border-t border-[var(--glass-border)] hover:bg-[var(--glass-bg-hover)] transition-colors ${histOpen ? 'bg-[hsl(var(--primary)/0.06)]' : idx % 2 === 0 ? '' : 'bg-[var(--glass-bg)]/20'}`}
                        data-testid={`ar-row-${inv.invoice_number}`}>
                        <td className="px-4 py-2 whitespace-nowrap">
                          <div className="text-xs font-semibold text-foreground">{inv.invoice_number}</div>
                          <div className="text-[10px] text-muted-foreground">
                            {inv.schedule_mode === 'v2'
                              ? `PO ${inv.linked_maklon_po_number || '—'} · nilai PO ${fmt(inv.scheduled_total)} · tertagih ${fmt(inv.billed_total)}`
                              : (inv.shipment_number || '—')}
                          </div>
                        </td>
                        <td className="px-3 py-2"><ChannelBadge channel={inv.sales_channel} channels={channels} /></td>
                        <td className="px-3 py-2 text-xs text-foreground">{inv.customer_name}</td>
                        <td className="px-3 py-2 text-xs text-foreground/70 whitespace-nowrap">{formatDateID(inv.issue_date)}</td>
                        <td className="px-3 py-2"><ArStatusBadge status={inv.status} /></td>
                        <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap text-xs text-foreground">{fmt(inv.total)}</td>
                        <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap text-xs">
                          {inv.balance > 0
                            ? <span className="text-[hsl(var(--warning))] font-semibold">{fmt(inv.balance)}</span>
                            : <span className="text-[hsl(var(--success))]">Lunas</span>}
                        </td>
                        <td className="px-3 py-2">
                          <div className="flex items-center justify-end gap-1">
                            {/* Riwayat pembayaran + nomor jurnal — dibuka di bawah baris ini */}
                            {(Number(inv.paid_amount) > 0 || inv.status === 'paid' || inv.status === 'partial_paid') && (
                              <Button variant="outline" size="sm" aria-expanded={histOpen}
                                onClick={() => setHistoryInv(histOpen ? null : inv)}
                                data-testid={`ar-history-${inv.id}`}
                                title="Riwayat pembayaran & nomor jurnal"
                              >
                                <History className="w-3.5 h-3.5" />{histOpen ? 'Tutup riwayat' : 'Riwayat'}
                              </Button>
                            )}
                            {inv.status === 'draft' && (
                              <Button variant="outline" size="sm" onClick={() => sendInvoice(inv.id)} data-testid={`ar-send-${inv.id}`} title="Terbitkan faktur dan catat ke buku besar">Terbitkan</Button>
                            )}
                            {/* 2026-11-07: server menyimpan status terbit sebagai `issued` (H-01) — dulu tombol hanya untuk `sent` sehingga tidak pernah tampil */}
                            {['sent', 'issued'].includes(inv.status) && inv.schedule_mode !== 'v2' && (
                              <Button variant="outline" size="sm" onClick={() => changeStatus(inv.id, 'overdue')} title="Tandai lewat jatuh tempo">Jatuh tempo</Button>
                            )}
                            {/* Bayar — form terisi sisa tagihan; rekening wajib dipilih. 2026-11-04: tombol ⚡ "Lunas"
                                sekali-klik dilepas karena diam-diam memakai rekening pertama (Kas Kecil). */}
                            {inv.status !== 'draft' && inv.status !== 'cancelled' && (inv.status !== 'paid' || inv.schedule_mode === 'v2') && arPayCap(inv) > 0 && (
                              <Button variant="outline" size="sm"
                                onClick={() => setPaying(inv)}
                                data-testid={`ar-pay-form-${inv.id}`}
                                title="Catat pembayaran"
                              >
                                Bayar
                              </Button>
                            )}
                          </div>
                        </td>
                      </tr>
                      {histOpen && (
                        <RowDetail colSpan={8} testId={`ar-history-detail-${inv.id}`}>
                          <p className="text-sm text-muted-foreground mb-2">
                            Riwayat pembayaran <span className="text-foreground font-medium">{inv.invoice_number}</span> · total <span className="tabular-nums">{fmt(inv.total)}</span> · sisa <span className="tabular-nums">{fmt(inv.balance)}</span>
                          </p>
                          <PaymentHistoryList token={token} kind="ar" invoiceId={inv.id} />
                        </RowDetail>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>

      {/* Catat pembayaran — formulir isian pendek (boleh popup, G13) */}
      {paying && (
        <PaymentModal
          invoice={paying}
          accounts={accounts}
          accountsLoaded={accountsLoaded}
          onClose={() => setPaying(null)}
          onPay={(payload) => recordPayment(paying.id, payload)}
        />
      )}
    </PageLayout>
  );
}

/** Batas bayar satu faktur. Piutang maklon terjadwal (`schedule_mode` v2) boleh menerima uang muka sampai
 *  sisa nilai PO (server: max(nilai jadwal, tertagih) − dibayar, core.maklon_ledger) — bukan hanya piutang
 *  yang sudah jatuh (`balance`). Dulu layar membatasi ke `balance`, sehingga uang muka klien maklon ditolak
 *  di layar padahal server menerimanya, dan PO yang belum dikirim (balance 0) tidak punya tombol Bayar. */
export function arPayCap(inv) {
  if (inv?.schedule_mode === 'v2') {
    const out = inv.outstanding_total;
    if (out !== undefined && out !== null) return Math.max(0, Number(out) || 0);
    return Math.max(0, Math.max(Number(inv.scheduled_total || 0), Number(inv.billed_total || 0)) - Number(inv.amount_paid ?? inv.paid_amount ?? 0));
  }
  return Math.max(0, Number(inv?.balance || 0));
}

function PaymentModal({ invoice, accounts, accountsLoaded, onClose, onPay }) {
  const due = Number(invoice.balance || 0);
  const balance = arPayCap(invoice);
  const isSchedule = invoice.schedule_mode === 'v2';
  const [amount, setAmount] = useState(isSchedule ? (due > 0 ? due : balance) : balance);
  // 2026-11-04: tanpa rekening bawaan (dulu rekening pertama = Kas Kecil) dan tanpa pilihan
  // "tidak link ke rekening" — uang dari pelanggan harus masuk ke rekening yang nyata.
  const [account_id, setAccount] = useState('');
  const [date, setDate] = useState(todayWIB);
  const [notes, setNotes] = useState('');
  const problem = !account_id ? 'Pilih rekening penerima.'
    : !(Number(amount) > 0) ? 'Jumlah harus lebih dari 0.'
      : Number(amount) > balance + 0.5 ? `Jumlah melebihi ${isSchedule ? 'sisa nilai PO' : 'sisa tagihan'} (${fmt(balance)}).`
        : '';
  return (
    <Modal onClose={onClose} title="Catat pembayaran" size="sm" description={`${invoice.invoice_number} · ${invoice.customer_name}`}>
      <p className="text-xs text-muted-foreground mb-3" data-testid="ar-pay-cap">
        {invoice.invoice_number} · {invoice.customer_name} · {isSchedule
          ? `Piutang jatuh ${fmt(due)} · bisa diterima sampai ${fmt(balance)} (sisa nilai PO; kelebihan dicatat sebagai uang muka)`
          : `Sisa: ${fmt(balance)}`}
      </p>
      <div className="space-y-3">
        <div><label className="text-xs text-muted-foreground" htmlFor="ar-pay-amount">Jumlah diterima</label><MoneyInput glass id="ar-pay-amount" value={amount} onChange={e => setAmount(Number(e.target.value))} data-testid="ar-pay-amount" /></div>
        <div><label className="text-xs text-muted-foreground">Masuk ke rekening</label><CashAccountSelect accounts={accounts} loaded={accountsLoaded} value={account_id} onChange={setAccount} testId="ar-pay-account" /></div>
        <div><label className="text-xs text-muted-foreground" htmlFor="ar-pay-date">Tanggal</label><GlassInput id="ar-pay-date" type="date" value={date} onChange={e => setDate(e.target.value)} /></div>
        <div><label className="text-xs text-muted-foreground" htmlFor="ar-pay-notes">Catatan</label><GlassInput id="ar-pay-notes" value={notes} onChange={e => setNotes(e.target.value)} placeholder="opsional, mis. no. referensi transfer" /></div>
      </div>
      {problem && account_id && <div className="text-xs text-[hsl(var(--destructive))] border border-[hsl(var(--destructive)/0.3)] rounded-lg px-3 py-2 mt-3" data-testid="ar-pay-error">{problem}</div>}
      <div className="flex gap-2 mt-4 justify-end">
        <Button variant="outline" onClick={onClose}>Batal</Button>
        <Button onClick={() => onPay({ amount, account_id, date, notes })} disabled={!!problem} data-testid="ar-pay-submit"><DollarSign className="w-4 h-4" />Simpan</Button>
      </div>
    </Modal>
  );
}

// 2026-11-05 (PANDUAN_UI G13): rekening koran pelanggan dibuka DI HALAMAN di atas daftar faktur — dulu popup.
// Periode memakai PeriodPicker (G6); bawaan Bulan ini (= dulu awal bulan s/d hari ini).
function CustomerStatementPanel({ token, customers, onClose }) {
  const [customer_id, setCustomerId] = useState(customers[0]?.id || '');
  const [period, setPeriod] = useState(() => periodFromPreset('month'));
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');
  const fmt2 = (n) => `Rp ${Number(n || 0).toLocaleString('id-ID')}`;

  const load = async () => {
    if (!customer_id) { setErr('Pilih pelanggan dulu'); return; }
    setErr(''); setLoading(true); setData(null);
    try {
      const url = `/api/rahaza/customer-statement/${customer_id}?date_from=${period.from}&date_to=${period.to}`;
      const r = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
      if (!r.ok) { setErr(`Gagal memuat (HTTP ${r.status})`); return; }
      setData(await r.json());
    } finally { setLoading(false); }
  };

  return (
    <DetailPanel title="Rekening koran pelanggan" description="Ringkasan tagihan dan pembayaran satu pelanggan dalam satu periode."
      onClose={onClose} testId="ar-statement-panel">
      <div className="flex flex-wrap items-center gap-2">
        <SmartNativeSelect value={customer_id} onChange={e => setCustomerId(e.target.value)} className="h-9 w-72 max-w-full" aria-label="Pelanggan" data-testid="stmt-customer">
          <option value="">— Pilih pelanggan —</option>
          {customers.map(c => <option key={c.id} value={c.id}>{`${c.code} · ${c.name}`}</option>)}
        </SmartNativeSelect>
        <PeriodPicker value={period} onChange={setPeriod} testId="stmt-period" />
        <Button onClick={load} disabled={loading} data-testid="stmt-load"><Calendar className="w-4 h-4" />{loading ? 'Memuat…' : 'Tampilkan'}</Button>
      </div>
      {err && <Notice tone="danger" icon={AlertCircle}>{err}</Notice>}
      {data && (
        <p className="text-sm text-muted-foreground" data-testid="stmt-summary">
          <b className="text-foreground tabular-nums">{data.summary.count}</b> faktur · tagihan <b className="text-foreground tabular-nums">{fmt2(data.summary.total_billed)}</b>
          {' · '}dibayar <b className="text-[hsl(var(--success))] tabular-nums">{fmt2(data.summary.total_paid)}</b>
          {' · '}sisa <b className="text-[hsl(var(--warning))] tabular-nums">{fmt2(data.summary.outstanding)}</b>
        </p>
      )}
    </DetailPanel>
  );
}

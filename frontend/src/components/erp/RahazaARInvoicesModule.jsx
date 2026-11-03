/**
 * Faktur Penjualan (menu Keuangan › Penjualan & Penerimaan) — daftar faktur piutang (AR) kanonik.
 *
 * 2026-11-04 (keputusan owner): faktur DIBUAT di Portal Penjualan (Nota Penjualan — stok FG keluar
 * + HPP + faktur) dan di Maklon. Layar ini untuk Keuangan: menerbitkan draf, mencatat pembayaran,
 * melihat riwayat & statement pelanggan. Form "Invoice Baru" (teks bebas, tanpa stok/HPP) dilepas
 * supaya penjualan reseller tidak bisa tercatat tanpa stok keluar. Endpoint POST /ar-invoices tetap.
 */
import { useState, useEffect, useCallback, useReducer, useMemo } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { RefreshCw, FileText, DollarSign, Calendar, Users, Store, History } from 'lucide-react';
import PaymentHistoryModal from './PaymentHistoryModal';
import CashAccountSelect, { usePaymentCashAccounts } from './SdmCashAccountSelect';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { PageHeader, StatusBadge, EmptyState } from './moduleAtoms';
import { toast } from 'sonner';
import { Skeleton } from '@/components/ui/skeleton';
import { formatRupiah } from '@/lib/format';
import { MoneyInput } from '@/components/ui/money-input';
import { todayWIB, monthStartWIB } from '@/lib/waktu';

const fmt = formatRupiah;

// Nama status untuk pengguna (server memakai kode Inggris). `issued`/`sent` = sudah terbit, belum lunas.
const AR_STATUS = {
  draft:        { label: 'Draf',              tone: 'muted' },
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

// Color per platform
const PLATFORM_COLORS = {
  shopee:    'bg-orange-500/15 text-orange-400 border-orange-500/30',
  tiktok:    'bg-pink-500/15 text-pink-400 border-pink-500/30',
  tokopedia: 'bg-green-500/15 text-green-400 border-green-500/30',
  maklon:    'bg-blue-500/15 text-blue-400 border-blue-500/30',
  other:     'bg-muted/15 text-muted-foreground border-border/30',
};

function ChannelBadge({ channel, channels }) {
  if (!channel) return null;
  const ch = channels.find(c => c.channel_key === channel);
  if (!ch) return <span className="text-xs text-muted-foreground">{channel}</span>;
  const cls = PLATFORM_COLORS[ch.platform] || PLATFORM_COLORS.other;
  return (
    <span className={`inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full border ${cls}`}>
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
    await fetch(`/api/rahaza/ar-invoices/${id}/status`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    });
    setTick(t => t + 1);
  }, [token]);

  const sendInvoice = useCallback(async (id) => {
    setError('');
    const r = await fetch(`/api/rahaza/ar-invoices/${id}/send`, { method: 'POST', headers: hdrs });
    if (!r.ok) { setError(`Gagal mengirim invoice (HTTP ${r.status})`); return; }
    const data = await r.json();
    if (data._posting_result && !data._posting_result.ok) {
      setError(`Invoice terkirim tapi posting JE gagal: ${data._posting_result.error}`);
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
    <div className="space-y-5" data-testid="rahaza-ar-invoices-page">
      <PageHeader
        icon={FileText}
        title="Faktur Penjualan"
        subtitle="Faktur piutang reseller dan maklon. Faktur dibuat dari Portal Penjualan › Nota Penjualan atau dari Maklon; di sini draf diterbitkan dan pembayaran dicatat."
        actions={
          <>
            <Button variant="ghost" onClick={() => setShowStatement(true)} className="h-9 border border-[var(--glass-border)] gap-1.5"><Users className="w-3.5 h-3.5" />Statement</Button>
            <Button variant="ghost" onClick={refresh} className="h-9 border border-[var(--glass-border)]" title="Muat ulang"><RefreshCw className="w-3.5 h-3.5" /></Button>
          </>
        }
      />

      {error && <div className="bg-[hsl(var(--destructive)/0.12)] border border-[hsl(var(--destructive)/0.22)] rounded-lg p-3 text-sm text-[hsl(var(--destructive))]">{error}<button onClick={() => setError('')} className="ml-2 text-xs underline">Tutup</button></div>}

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <ARStatTile label="Total faktur" value={invoices.length} accent="primary" />
        <ARStatTile label="Belum lunas" value={unpaidInvoices.length} accent="warning" />
        <ARStatTile label="Sisa piutang" value={fmt(totalOutstanding)} accent="danger" />
        <ARStatTile label="Sudah diterima" value={fmt(totalPaid)} accent="success" />
      </div>

      {/* Invoice table */}
      <GlassCard className="p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-[var(--glass-bg)]">
              <tr className="text-left text-[10px] uppercase tracking-wider text-foreground/50">
                <th className="px-4 py-3">Invoice</th>
                <th className="px-3 py-3">Channel</th>
                <th className="px-3 py-3">Pelanggan</th>
                <th className="px-3 py-3">Terbit</th>
                <th className="px-3 py-3">Status</th>
                <th className="px-3 py-3 text-right">Total</th>
                <th className="px-3 py-3 text-right">Balance</th>
                <th className="px-3 py-3 text-center">Aksi</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={8} className="py-8"><div className="space-y-2">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-12 rounded-lg mx-4" />)}</div></td></tr>
              ) : invoices.length === 0 ? (
                <tr><td colSpan={8} className="py-8"><EmptyState icon={FileText} title="Belum ada faktur" description="Faktur muncul di sini setelah dibuat dari Portal Penjualan › Nota Penjualan atau dari Maklon." /></td></tr>
              ) : invoices.map((inv, idx) => (
                <tr key={inv.id} className={`border-t border-[var(--glass-border)] hover:bg-[var(--glass-bg-hover)] transition-colors ${idx % 2 === 0 ? '' : 'bg-[var(--glass-bg)]/20'}`}
                  data-testid={`ar-row-${inv.invoice_number}`}>
                  <td className="px-4 py-2">
                    <div className="font-mono text-xs font-semibold text-foreground">{inv.invoice_number}</div>
                    <div className="text-[10px] text-muted-foreground">{inv.shipment_number || '—'}</div>
                  </td>
                  <td className="px-3 py-2"><ChannelBadge channel={inv.sales_channel} channels={channels} /></td>
                  <td className="px-3 py-2 text-xs text-foreground">{inv.customer_name}</td>
                  <td className="px-3 py-2 text-xs text-foreground/70">{inv.issue_date}</td>
                  <td className="px-3 py-2"><ArStatusBadge status={inv.status} /></td>
                  <td className="px-3 py-2 text-right font-mono text-xs text-foreground">{fmt(inv.total)}</td>
                  <td className="px-3 py-2 text-right font-mono text-xs">
                    {inv.balance > 0
                      ? <span className="text-amber-400 font-semibold">{fmt(inv.balance)}</span>
                      : <span className="text-emerald-400">Lunas</span>}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center justify-center gap-1">
                      {/* Riwayat pembayaran + nomor jurnal */}
                      {(Number(inv.paid_amount) > 0 || inv.status === 'paid' || inv.status === 'partial_paid') && (
                        <button
                          onClick={() => setHistoryInv(inv)}
                          className="h-7 px-2 rounded border border-[var(--glass-border)] bg-[var(--glass-bg)] text-foreground/70 hover:bg-[var(--glass-bg-hover)] transition-colors flex items-center gap-1 text-[10px] whitespace-nowrap"
                          data-testid={`ar-history-${inv.id}`}
                          title="Riwayat pembayaran & nomor jurnal"
                        >
                          <History className="w-3 h-3" />Riwayat
                        </button>
                      )}
                      {/* Status controls */}
                      {inv.status === 'draft' && (
                        <button onClick={() => sendInvoice(inv.id)} className="text-[10px] px-2 py-0.5 rounded border border-primary/30 bg-primary/10 text-primary hover:bg-primary/20 transition-colors whitespace-nowrap" data-testid={`ar-send-${inv.id}`} title="Terbitkan faktur dan catat ke buku besar">Terbitkan</button>
                      )}
                      {inv.status === 'sent' && (
                        <button onClick={() => changeStatus(inv.id, 'overdue')} className="text-[10px] px-2 py-0.5 rounded border border-amber-400/30 bg-amber-400/10 text-amber-400 hover:bg-amber-400/20 transition-colors whitespace-nowrap">Jatuh Tempo</button>
                      )}
                      {/* Bayar — form terisi sisa tagihan; rekening wajib dipilih. 2026-11-04: tombol ⚡ "Lunas"
                          sekali-klik dilepas karena diam-diam memakai rekening pertama (Kas Kecil). */}
                      {inv.status !== 'draft' && inv.status !== 'paid' && inv.balance > 0 && (
                        <button
                          onClick={() => setPaying(inv)}
                          className="text-[10px] px-2 py-0.5 rounded border border-[var(--glass-border)] bg-[var(--glass-bg)] text-foreground/70 hover:bg-[var(--glass-bg-hover)] transition-colors whitespace-nowrap"
                          data-testid={`ar-pay-form-${inv.id}`}
                          title="Catat pembayaran"
                        >
                          Bayar
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassCard>

      {/* Payment Modal */}
      {paying && (
        <PaymentModal
          invoice={paying}
          accounts={accounts}
          accountsLoaded={accountsLoaded}
          onClose={() => setPaying(null)}
          onPay={(payload) => recordPayment(paying.id, payload)}
        />
      )}

      {/* Statement Modal */}
      {showStatement && <CustomerStatementModal token={token} customers={customers} onClose={() => setShowStatement(false)} />}

      {/* Payment history */}
      {historyInv && <PaymentHistoryModal token={token} kind="ar" invoice={historyInv} onClose={() => setHistoryInv(null)} />}
    </div>
  );
}

function ARStatTile({ label, value, accent }) {
  const accents = {
    primary: 'border-[hsl(var(--primary)/0.25)] bg-[hsl(var(--primary)/0.08)] text-[hsl(var(--primary))]',
    warning: 'border-[hsl(var(--warning)/0.25)] bg-[hsl(var(--warning)/0.08)] text-[hsl(var(--warning))]',
    danger:  'border-[hsl(var(--destructive)/0.25)] bg-[hsl(var(--destructive)/0.08)] text-[hsl(var(--destructive))]',
    success: 'border-[hsl(var(--success)/0.25)] bg-[hsl(var(--success)/0.08)] text-[hsl(var(--success))]',
  };
  return (
    <div className={`rounded-[var(--radius-lg)] border p-3 ${accents[accent] || 'border-[var(--glass-border)] bg-[var(--glass-bg)]'}`}>
      <p className="text-[10px] uppercase tracking-wider text-foreground/50">{label}</p>
      <p className="text-lg font-bold mt-0.5 font-mono">{value}</p>
    </div>
  );
}

function PaymentModal({ invoice, accounts, accountsLoaded, onClose, onPay }) {
  const balance = Number(invoice.balance || 0);
  const [amount, setAmount] = useState(balance);
  // 2026-11-04: tanpa rekening bawaan (dulu rekening pertama = Kas Kecil) dan tanpa pilihan
  // "tidak link ke rekening" — uang dari pelanggan harus masuk ke rekening yang nyata.
  const [account_id, setAccount] = useState('');
  const [date, setDate] = useState(todayWIB);
  const [notes, setNotes] = useState('');
  const problem = !account_id ? 'Pilih rekening penerima.'
    : !(Number(amount) > 0) ? 'Jumlah harus lebih dari 0.'
      : Number(amount) > balance + 0.5 ? `Jumlah melebihi sisa tagihan (${fmt(balance)}).`
        : '';
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <GlassCard className="p-6 max-w-md w-full" onClick={e => e.stopPropagation()}>
        <h2 className="text-xl font-bold text-foreground mb-2">Catat Pembayaran</h2>
        <p className="text-xs text-muted-foreground mb-4">{invoice.invoice_number} · {invoice.customer_name} · Sisa: {fmt(balance)}</p>
        <div className="space-y-3">
          <div><label className="text-xs text-muted-foreground" htmlFor="ar-pay-amount">Jumlah diterima</label><MoneyInput glass id="ar-pay-amount" value={amount} onChange={e => setAmount(Number(e.target.value))} data-testid="ar-pay-amount" /></div>
          <div><label className="text-xs text-muted-foreground">Masuk ke rekening</label><CashAccountSelect accounts={accounts} loaded={accountsLoaded} value={account_id} onChange={setAccount} testId="ar-pay-account" /></div>
          <div><label className="text-xs text-muted-foreground" htmlFor="ar-pay-date">Tanggal</label><GlassInput id="ar-pay-date" type="date" value={date} onChange={e => setDate(e.target.value)} /></div>
          <div><label className="text-xs text-muted-foreground" htmlFor="ar-pay-notes">Catatan</label><GlassInput id="ar-pay-notes" value={notes} onChange={e => setNotes(e.target.value)} placeholder="opsional, mis. no. referensi transfer" /></div>
        </div>
        {problem && account_id && <div className="text-xs text-red-400 border border-red-400/30 rounded-lg px-3 py-2 mt-3" data-testid="ar-pay-error">{problem}</div>}
        <div className="flex gap-2 mt-6 justify-end"><Button variant="ghost" onClick={onClose} className="border border-[var(--glass-border)]">Batal</Button><Button onClick={() => onPay({ amount, account_id, date, notes })} disabled={!!problem} data-testid="ar-pay-submit"><DollarSign className="w-4 h-4 mr-1.5" />Simpan</Button></div>
      </GlassCard>
    </div>
  );
}

function CustomerStatementModal({ token, customers, onClose }) {
  const today = todayWIB();
  const firstOfMonth = monthStartWIB();
  const [customer_id, setCustomerId] = useState(customers[0]?.id || '');
  const [date_from, setFrom] = useState(firstOfMonth);
  const [date_to, setTo] = useState(today);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');
  const fmt2 = (n) => `Rp ${Number(n || 0).toLocaleString('id-ID')}`;

  const load = async () => {
    if (!customer_id) { setErr('Pilih pelanggan dulu'); return; }
    setErr(''); setLoading(true); setData(null);
    try {
      const url = `/api/rahaza/customer-statement/${customer_id}?date_from=${date_from}&date_to=${date_to}`;
      const r = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
      if (!r.ok) { setErr(`Gagal memuat (HTTP ${r.status})`); return; }
      setData(await r.json());
    } finally { setLoading(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <GlassCard className="p-6 max-w-3xl w-full max-h-[92vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <div className="flex items-start justify-between mb-4">
          <h2 className="text-xl font-bold text-foreground flex items-center gap-2"><Users className="w-5 h-5 text-primary" /> Statement Pelanggan</h2>
          <button onClick={onClose} className="text-foreground/60 hover:text-foreground">✕</button>
        </div>
        <div className="grid grid-cols-4 gap-2 mb-3">
          <div className="col-span-2">
            <label className="text-xs uppercase text-muted-foreground mb-1 block">Pelanggan</label>
            <SmartNativeSelect value={customer_id} onChange={e => setCustomerId(e.target.value)} className="w-full h-10 px-3 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-sm text-foreground" data-testid="stmt-customer">
              <option value="">— Pilih —</option>
              {customers.map(c => <option key={c.id} value={c.id}>{`${c.code} · ${c.name}`}</option>)}
            </SmartNativeSelect>
          </div>
          <div><label className="text-xs uppercase text-muted-foreground mb-1 block">Dari</label><GlassInput type="date" value={date_from} onChange={e => setFrom(e.target.value)} /></div>
          <div><label className="text-xs uppercase text-muted-foreground mb-1 block">Sampai</label><GlassInput type="date" value={date_to} onChange={e => setTo(e.target.value)} /></div>
        </div>
        <div className="flex justify-end mb-3">
          <Button onClick={load} disabled={loading} data-testid="stmt-load"><Calendar className="w-4 h-4 mr-1.5" /> {loading ? 'Memuat...' : 'Tampilkan'}</Button>
        </div>
        {err && <div className="bg-[hsl(var(--destructive)/0.12)] border border-[hsl(var(--destructive)/0.22)] rounded-lg p-3 text-sm text-[hsl(var(--destructive))] mb-3">{err}</div>}
        {data && (
          <div className="space-y-3">
            <div className="grid grid-cols-4 gap-2">
              <div className="rounded-lg border border-[var(--glass-border)] bg-[var(--glass-bg)] p-3"><p className="text-[10px] uppercase text-muted-foreground">Invoice</p><p className="text-lg font-bold font-mono">{data.summary.count}</p></div>
              <div className="rounded-lg border border-[var(--glass-border)] bg-[var(--glass-bg)] p-3"><p className="text-[10px] uppercase text-muted-foreground">Total Tagihan</p><p className="text-sm font-bold font-mono">{fmt2(data.summary.total_billed)}</p></div>
              <div className="rounded-lg border border-emerald-400/20 bg-emerald-400/8 p-3"><p className="text-[10px] uppercase text-muted-foreground">Dibayar</p><p className="text-sm font-bold font-mono text-emerald-400">{fmt2(data.summary.total_paid)}</p></div>
              <div className="rounded-lg border border-amber-400/20 bg-amber-400/8 p-3"><p className="text-[10px] uppercase text-muted-foreground">Outstanding</p><p className="text-sm font-bold font-mono text-amber-400">{fmt2(data.summary.outstanding)}</p></div>
            </div>
          </div>
        )}
        <div className="flex justify-end mt-6">
          <Button variant="ghost" onClick={onClose} className="border border-[var(--glass-border)]">Tutup</Button>
        </div>
      </GlassCard>
    </div>
  );
}

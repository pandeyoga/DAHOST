import { useState, useEffect, useCallback, useMemo } from 'react';
import { Banknote, RefreshCw, FileText, Eye, CreditCard, X, AlertCircle } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { toast } from 'sonner';
import SalesTaxFields from './SalesTaxFields';
import { useTaxProfile } from '../../lib/taxProfile';
import { motion } from 'framer-motion';
import { PageHeader, EmptyState, Notice } from './moduleAtoms';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { fetchMaklonOrders, posToLegacyOrders } from '@/lib/maklonOrderAdapter';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import OnwardCTA from './OnwardCTA';
import { formatRupiah } from '@/lib/format';
import { todayWIB } from '@/lib/waktu';
import DocNumberField, { useDocNumberPolicy, docNumberPayload } from './docnum/DocNumberField';

const STATUS_CONFIG = {
  draft:        { label: 'Draf',         color: 'bg-muted text-foreground border-border dark:bg-slate-500/15 dark:text-foreground/70 dark:border-slate-400/30' },
  issued:       { label: 'Diterbitkan',  color: 'bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))] border-[hsl(var(--primary)/0.35)]   ' },
  partial_paid: { label: 'Dibayar sebagian', color: 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))] border-[hsl(var(--warning)/0.35)]   ' },
  paid:         { label: 'Lunas',        color: 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))] border-[hsl(var(--success)/0.35)]   ' },
  overdue:      { label: 'Lewat jatuh tempo', color: 'bg-[hsl(var(--destructive)/0.15)] text-[hsl(var(--destructive))] border-[hsl(var(--destructive)/0.35)]   ' },
  cancelled:    { label: 'Dibatalkan',   color: 'bg-muted text-muted-foreground border-border dark:bg-slate-500/15 dark:text-muted-foreground dark:border-slate-400/30' },
};

function StatusBadge({ status }) {
  const c = STATUS_CONFIG[status] || STATUS_CONFIG.draft;
  return <span className={`inline-flex text-[10px] font-semibold px-2 py-0.5 rounded-full border ${c.color}`}>{c.label}</span>;
}

const fmt = formatRupiah;
const AGING_LABELS = { current: 'Belum jatuh tempo', '1_30': '1-30 hari', '31_60': '31-60 hari', '61_90': '61-90 hari', over_90: '> 90 hari' };

export default function MaklonBillingModule({ token, onNavigate }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);

  const [invoices, setInvoices] = useState([]);
  const [eligibleOrders, setEligibleOrders] = useState([]);
  const [summary, setSummary] = useState({});
  const [aging, setAging] = useState({ buckets: {}, rows: [] });
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState('invoices');
  const [generateDialog, setGenerateDialog] = useState(false);
  const [viewDialog, setViewDialog] = useState(null);
  const [payDialog, setPayDialog] = useState(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [inv, elig, sum, ag] = await Promise.all([
        fetch('/api/dewi/maklon/invoices', { headers }),
        fetch('/api/dewi/maklon/invoices/eligible', { headers }),
        fetch('/api/dewi/maklon/reports/billing-summary', { headers }),
        fetch('/api/dewi/maklon/reports/aging', { headers }),
      ]);
      if (inv.ok) setInvoices(await inv.json());
      // SATU SUMBER: daftar PO yang bisa ditagih + pratinjau qty/nilai dihitung server
      // (rumus yang sama dengan dokumen yang terbit) — bukan ditebak di browser.
      if (elig.ok) setEligibleOrders(await elig.json());
      if (sum.ok) setSummary(await sum.json());
      if (ag.ok) setAging(await ag.json());
    } catch (e) { toast.error('Gagal memuat data billing'); }
    finally { setLoading(false); }
  }, [headers]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const cancelInvoice = async (inv) => {
    if (!(await confirmDialog({ title: `Batalkan faktur ${inv.invoice_number}?`, body: 'Faktur yang dibatalkan tidak bisa ditagih lagi.', confirmLabel: 'Batalkan faktur', danger: true }))) return;
    const r = await fetch(`/api/dewi/maklon/invoices/${inv.id}/cancel`, { method: 'POST', headers });
    if (r.ok) { toast.success('Invoice dibatalkan'); fetchAll(); }
    else toast.error((await r.json()).detail || 'Gagal');
  };

  const printInvoicePdf = async (inv) => {
    try {
      const res = await fetch(`/api/dewi/maklon/invoices/${inv.id}/pdf`, { headers: { Authorization: headers.Authorization } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = `Invoice_${inv.invoice_number || inv.id}.pdf`;
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast.success('PDF invoice berhasil diunduh');
    } catch (e) { toast.error('Gagal mengunduh PDF invoice'); }
  };

  const stats = [
    { label: 'Total Invoice',   value: summary.total_invoices || 0,          color: 'text-[hsl(var(--primary))]  bg-[hsl(var(--primary)/0.1)]  border-[hsl(var(--primary)/0.2)]' },
    { label: 'Total Tagihan',   value: fmt(summary.total_billed),             color: 'text-[hsl(var(--primary))]  bg-[hsl(var(--primary)/0.1)]  border-[hsl(var(--primary)/0.2)]' },
    { label: 'Sudah Dibayar',   value: fmt(summary.total_paid),               color: 'text-[hsl(var(--success))]  bg-[hsl(var(--success)/0.1)]  border-[hsl(var(--success)/0.35)] ' },
    { label: 'Sisa tagihan',    value: fmt(summary.total_outstanding),        color: 'text-[hsl(var(--warning))]  bg-[hsl(var(--warning)/0.1)]  border-[hsl(var(--warning)/0.2)]' },
    { label: 'Lewat jatuh tempo', value: `${summary.overdue_count || 0} (${fmt(summary.overdue_amount)})`, color: 'text-[hsl(var(--destructive))]  bg-[hsl(var(--destructive)/0.1)]  border-[hsl(var(--destructive)/0.35)] ' },
  ];

  const { page, setPage, totalPages, total, paged } = useClientPagination(invoices, 10);
  return (
    <div className="space-y-4" data-testid="maklon-billing">
      <PageHeader
        title="Invoice & Billing Maklon"
        subtitle="Generate invoice dari order, kelola payment, laporan aging"
        icon={Banknote}
        actions={
          <div className="flex gap-2">
            <Button size="icon" variant="outline" onClick={fetchAll} title="Muat ulang" aria-label="Muat ulang" data-testid="billing-refresh-btn">
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </Button>
            <Button size="sm" onClick={() => setGenerateDialog(true)} className="gap-1.5" data-testid="billing-generate-btn">
              <FileText className="w-3.5 h-3.5" /> Terbitkan faktur
            </Button>
          </div>
        }
      />

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {stats.map((s, i) => (
          <motion.div key={s.label} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.04 * i }}>
            <GlassCard className={`p-4 border ${s.color.split(' ')[2]}`}>
              <div className="text-xs text-foreground/50">{s.label}</div>
              <div className={`text-lg font-bold mt-1 ${s.color.split(' ')[0]}`}>{s.value}</div>
            </GlassCard>
          </motion.div>
        ))}
      </div>

      {/* RC-FLOW-UX: onward — Maklon Invoice → Piutang (AR) / PO 360 (Alur 10) */}
      <OnwardCTA
        onNavigate={onNavigate}
        title="Langkah Berikutnya"
        actions={[
          { module: 'fin-ar-invoices', label: 'Piutang / AR Invoice', icon: Banknote, primary: true, hint: 'Kelola tagihan & pembayaran di Keuangan' },
          { module: 'maklon-po-360', label: 'Lihat PO 360°', icon: FileText, hint: 'Status menyeluruh PO maklon' },
        ]}
      />

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="mb-4">
          <TabsTrigger value="invoices">Faktur</TabsTrigger>
          <TabsTrigger value="aging">Umur piutang</TabsTrigger>
        </TabsList>

        <TabsContent value="invoices">
          <GlassCard className="p-5">
            {loading ? (
              <div className="text-center py-6 text-foreground/40 text-sm">Memuat...</div>
            ) : invoices.length === 0 ? (
              <EmptyState icon={FileText} title="Belum ada faktur"
                description="Terbitkan faktur dari PO yang sudah dikirim lewat tombol Terbitkan faktur." />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm" data-testid="invoices-table">
                  <thead><tr className="border-b border-foreground/5 text-xs text-foreground/50">
                    <th className="pb-2 text-left">No. faktur</th>
                    <th className="pb-2 text-left">Klien</th>
                    <th className="pb-2 text-left">Order</th>
                    <th className="pb-2 text-left">Terbit</th>
                    <th className="pb-2 text-left">Jatuh tempo</th>
                    <th className="pb-2 text-right">Total</th>
                    <th className="pb-2 text-right">Dibayar</th>
                    <th className="pb-2 text-right">Sisa</th>
                    <th className="pb-2 text-left">Status</th>
                    <th className="pb-2 text-center">Aksi</th>
                  </tr></thead>
                  <tbody className="divide-y divide-white/5">
                    {paged.map(i => (
                      <tr key={i.id} className="hover:bg-foreground/[0.03]">
                        <td className="py-2.5 pr-3 tabular-nums text-xs text-foreground/80">{i.invoice_number}</td>
                        <td className="py-2.5 pr-3 text-foreground">{i.client_name}</td>
                        <td className="py-2.5 pr-3 tabular-nums text-xs text-foreground/60">{i.order_code}</td>
                        <td className="py-2.5 pr-3 text-xs text-foreground/60">{i.issue_date}</td>
                        <td className="py-2.5 pr-3 text-xs text-foreground/60">{i.due_date}</td>
                        <td className="py-2.5 pr-3 text-right">{fmt(i.total_amount)}</td>
                        <td className="py-2.5 pr-3 text-right text-[hsl(var(--success))] ">{fmt(i.paid_amount)}</td>
                        <td className="py-2.5 pr-3 text-right text-[hsl(var(--warning))] font-semibold">{fmt(i.balance_amount)}</td>
                        <td className="py-2.5 pr-3"><StatusBadge status={i.status} /></td>
                        <td className="py-2.5">
                          <div className="flex gap-1 justify-center">
                            <Button size="icon-sm" variant="ghost" onClick={() => setViewDialog(i)} title="Detail" aria-label="Detail"><Eye className="w-3.5 h-3.5" /></Button>
                            <Button size="icon-sm" variant="ghost" className="text-[hsl(var(--primary))]" onClick={() => printInvoicePdf(i)} title="Cetak PDF faktur" aria-label="Cetak PDF faktur" data-testid={`maklon-invoice-print-${i.id}`}><FileText className="w-3.5 h-3.5" /></Button>
                            {['issued','partial_paid','overdue'].includes(i.status) && (
                              <Button size="icon-sm" variant="ghost" className="text-[hsl(var(--success))]" onClick={() => setPayDialog(i)} title="Bayar" aria-label="Bayar"><CreditCard className="w-3.5 h-3.5" /></Button>
                            )}
                            {i.status !== 'cancelled' && i.paid_amount === 0 && (
                              <Button size="icon-sm" variant="ghost" className="text-[hsl(var(--destructive))]" onClick={() => cancelInvoice(i)} title="Batalkan faktur" aria-label="Batalkan faktur"><X className="w-3.5 h-3.5" /></Button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} className="px-1" />
              </div>
            )}
          </GlassCard>
        </TabsContent>

        <TabsContent value="aging">
          <div className="grid grid-cols-1 md:grid-cols-5 gap-3 mb-4">
            {['current','1_30','31_60','61_90','over_90'].map(k => {
              const labels = AGING_LABELS;
              const colors = {current:'text-[hsl(var(--success))] ',1_30:'text-[hsl(var(--warning))] ',31_60:'text-[hsl(var(--warning))]',61_90:'text-[hsl(var(--destructive))] ',over_90:'text-[hsl(var(--destructive))] '};
              return (
                <GlassCard key={k} className="p-4">
                  <div className="text-xs text-foreground/50">{labels[k]}</div>
                  <div className={`text-lg font-bold mt-1 ${colors[k]}`}>{fmt(aging.buckets?.[k])}</div>
                </GlassCard>
              );
            })}
          </div>
          <GlassCard className="p-5">
            <h3 className="text-sm font-semibold text-foreground/80 mb-3">Faktur belum lunas</h3>
            {(aging.rows || []).length === 0 ? (
              <EmptyState icon={Banknote} title="Semua faktur sudah lunas"
                description="Faktur yang belum dibayar penuh akan muncul di sini." />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead><tr className="border-b border-foreground/5 text-xs text-foreground/50">
                    <th className="pb-2 text-left">Faktur</th><th className="pb-2 text-left">Klien</th>
                    <th className="pb-2 text-left">Jatuh tempo</th><th className="pb-2 text-right">Sisa</th>
                    <th className="pb-2 text-center">Lewat (hari)</th><th className="pb-2 text-left">Kelompok umur</th>
                  </tr></thead>
                  <tbody className="divide-y divide-white/5">
                    {(aging.rows || []).map((r, i) => (
                      <tr key={i}>
                        <td className="py-2 tabular-nums text-xs text-foreground/80">{r.invoice_number}</td>
                        <td className="py-2">{r.client_name}</td>
                        <td className="py-2 text-xs text-foreground/60">{r.due_date}</td>
                        <td className="py-2 text-right font-semibold">{fmt(r.balance_amount)}</td>
                        <td className="py-2 text-center text-xs">{r.days_overdue > 0 ? `${r.days_overdue} hari` : '-'}</td>
                        <td className="py-2 text-xs"><span className={`font-semibold ${r.bucket === 'current' ? 'text-[hsl(var(--success))] ' : 'text-[hsl(var(--destructive))] '}`}>{AGING_LABELS[r.bucket] || r.bucket}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </GlassCard>
        </TabsContent>
      </Tabs>

      {generateDialog && (
        <GenerateDialog orders={eligibleOrders} headers={headers}
          onClose={() => setGenerateDialog(false)}
          onSuccess={() => { setGenerateDialog(false); fetchAll(); }}
        />
      )}
      {viewDialog && <ViewInvoiceDialog invoice={viewDialog} headers={headers} onClose={() => setViewDialog(null)} />}
      {payDialog && (
        <PaymentDialog invoice={payDialog} headers={headers}
          onClose={() => setPayDialog(null)}
          onSuccess={() => { setPayDialog(null); fetchAll(); }}
        />
      )}
    </div>
  );
}

function GenerateDialog({ orders, headers, onClose, onSuccess }) {
  const [orderId, setOrderId] = useState('');
  // 2026-11-03: PPN mengikuti saklar Status Pajak (dulu "PPN % opsional", kosong = 11% dari config)
  const { profile: taxProfile } = useTaxProfile();
  const [taxF, setTaxF] = useState({ kena_ppn: true, faktur_number: '', faktur_date: '' });
  const [terms, setTerms] = useState('');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  // SESI #27 — nomor invoice maklon mengikuti kebijakan Otomatis/Manual milik owner
  // (ditegakkan sejak sesi #18, tetapi kolomnya belum pernah ada di layar ini).
  const numPolicy = useDocNumberPolicy('dewi_maklon_invoices.invoice_number',
                                       localStorage.getItem('erp_token'));
  const [invNumber, setInvNumber] = useState('');
  const selected = orders.find(o => o.id === orderId);

  const gen = async () => {
    if (!orderId) { toast.error('Pilih PO'); return; }
    setSaving(true);
    const payload = { order_id: orderId };
    payload.kena_ppn = !!taxProfile.pkp && taxF.kena_ppn !== false;
    if (payload.kena_ppn) Object.assign(payload, { faktur_number: taxF.faktur_number, faktur_date: taxF.faktur_date });
    if (terms) payload.payment_terms = terms;
    if (notes) payload.notes = notes;
    if (selected?.source !== 'engine_ar') Object.assign(payload, docNumberPayload(numPolicy, 'invoice_number', invNumber));
    const r = await fetch('/api/dewi/maklon/invoices/generate', { method: 'POST', headers, body: JSON.stringify(payload) });
    setSaving(false);
    if (r.ok) {
      const inv = await r.json();
      toast.success(`Invoice ${inv.invoice_number} dibuat`);
      onSuccess();
    } else {
      toast.error((await r.json()).detail || 'Gagal');
    }
  };

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent className="max-w-lg" data-testid="generate-invoice-dialog">
        <DialogHeader><DialogTitle>Terbitkan faktur</DialogTitle></DialogHeader>
        <div className="space-y-3 py-2">
          {orders.length === 0 ? (
            <Notice tone="warning" icon={AlertCircle}>
              Tidak ada order yang bisa difakturkan. Order harus sudah dikonfirmasi dan belum punya faktur.
            </Notice>
          ) : (
            <>
              <div className="space-y-1">
                <Label>Order *</Label>
                <Select value={orderId} onValueChange={setOrderId}>
                  <SelectTrigger data-testid="gen-order-select"><SelectValue placeholder="Pilih PO..." /></SelectTrigger>
                  <SelectContent>
                    {orders.map(o => (
                      <SelectItem key={o.id} value={o.id} disabled={!o.billable}>
                        {o.po_number} — {o.client_name} · terkirim {o.total_received}/{o.total_ordered} pcs · Rp {Number(o.subtotal || 0).toLocaleString('id-ID')}
                        {!o.billable ? ' (belum ada kiriman)' : ''}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {selected?.source === 'engine_ar' && (
                  <p className="text-xs text-muted-foreground" data-testid="gen-engine-ar-note">
                    Menerbitkan AR otomatis <b>{selected.ar_invoice_number}</b>: {selected.line_count} baris,
                    qty = yang diterima klien × harga jasa (selling price). Nomor mengikuti AR — tidak dibuat nomor baru.
                  </p>
                )}
              </div>
              <SalesTaxFields profile={taxProfile} value={taxF} onChange={setTaxF} compact testIdPrefix="maklon-gen-tax" />
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label>Termin pembayaran</Label>
                  <Select value={terms} onValueChange={setTerms}>
                    <SelectTrigger><SelectValue placeholder="Bawaan pengaturan" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="net_7">Net 7</SelectItem>
                      <SelectItem value="net_14">Net 14</SelectItem>
                      <SelectItem value="net_30">Net 30</SelectItem>
                      <SelectItem value="net_60">Net 60</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="space-y-1"><Label>Catatan</Label><Textarea rows={2} value={notes} onChange={e => setNotes(e.target.value)} /></div>
              {selected?.source !== 'engine_ar' && (
                <DocNumberField
                  policy={numPolicy} value={invNumber} onChange={setInvNumber}
                  testId="maklon-inv-docnum" label="Nomor Invoice" />
              )}
            </>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Batal</Button>
          <Button onClick={gen} disabled={saving || orders.length === 0} data-testid="gen-save-btn">{saving ? 'Menerbitkan...' : 'Terbitkan'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PaymentDialog({ invoice, headers, onClose, onSuccess }) {
  const [amount, setAmount] = useState(invoice.balance_amount || 0);
  const [method, setMethod] = useState('transfer');
  const [ref, setRef] = useState('');
  const [date, setDate] = useState(todayWIB);
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [cashAccounts, setCashAccounts] = useState([]);
  const [cashAccountId, setCashAccountId] = useState('');
  useEffect(() => {
    fetch('/api/rahaza/cash-accounts', { headers })
      .then(r => (r.ok ? r.json() : []))
      .then(d => setCashAccounts(Array.isArray(d) ? d : []))
      .catch(() => {});
  }, [headers]);

  const save = async () => {
    if (!amount || Number(amount) <= 0) { toast.error('Jumlah pembayaran wajib'); return; }
    setSaving(true);
    const r = await fetch('/api/dewi/maklon/payments', { method: 'POST', headers, body: JSON.stringify({
      invoice_id: invoice.id, amount: Number(amount), method, reference_no: ref, payment_date: date, notes,
      cash_account_id: cashAccountId || null,
    })});
    setSaving(false);
    if (r.ok) {
      const d = await r.json();
      if (d.gl_error) toast.warning(`Pembayaran dicatat, jurnal GL gagal: ${d.gl_error}`);
      else toast.success(`Pembayaran dicatat${d.gl_je_number ? ` · Jurnal ${d.gl_je_number}` : ''}`);
      onSuccess();
    }
    else toast.error((await r.json()).detail || 'Gagal');
  };

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent className="max-w-lg" data-testid="payment-dialog">
        <DialogHeader><DialogTitle>Catat Pembayaran — {invoice.invoice_number}</DialogTitle></DialogHeader>
        <div className="space-y-3 py-2">
          <div className="bg-foreground/5 rounded p-3 text-sm grid grid-cols-2 gap-2">
            <div>Total: <span className="font-semibold">{fmt(invoice.total_amount)}</span></div>
            <div>Dibayar: <span className="font-semibold text-[hsl(var(--success))] ">{fmt(invoice.paid_amount)}</span></div>
            <div className="col-span-2 text-[hsl(var(--warning))] ">Sisa: <span className="font-semibold">{fmt(invoice.balance_amount)}</span></div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1"><Label>Jumlah *</Label><MoneyInput value={amount} onChange={e => setAmount(e.target.value)} data-testid="pay-amount-input" /></div>
            <div className="space-y-1">
              <Label>Metode</Label>
              <Select value={method} onValueChange={setMethod}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="transfer">Transfer</SelectItem>
                  <SelectItem value="cash">Cash</SelectItem>
                  <SelectItem value="check">Cek</SelectItem>
                  <SelectItem value="giro">Giro</SelectItem>
                  <SelectItem value="other">Lainnya</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1"><Label>Tgl Bayar</Label><Input type="date" value={date} onChange={e => setDate(e.target.value)} /></div>
            <div className="space-y-1"><Label>No. Referensi</Label><Input value={ref} onChange={e => setRef(e.target.value)} placeholder="TF-001" /></div>
            <div className="space-y-1 col-span-2">
              <Label>Rekening Kas/Bank Penerima</Label>
              <Select value={cashAccountId} onValueChange={setCashAccountId}>
                <SelectTrigger data-testid="pay-cash-account-select"><SelectValue placeholder="Default profil (Bank BCA) — pilih untuk mutasi kas" /></SelectTrigger>
                <SelectContent>
                  {cashAccounts.map(a => (
                    <SelectItem key={a.id} value={a.id}>{a.name}{a.gl_account_code ? ` · ${a.gl_account_code}` : ''}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1 col-span-2"><Label>Catatan</Label><Textarea rows={2} value={notes} onChange={e => setNotes(e.target.value)} /></div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Batal</Button>
          <Button onClick={save} disabled={saving} data-testid="pay-save-btn">{saving ? 'Menyimpan...' : 'Catat'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ViewInvoiceDialog({ invoice, headers, onClose }) {
  const [detail, setDetail] = useState(invoice);
  const [downloading, setDownloading] = useState(false);
  useEffect(() => {
    fetch(`/api/dewi/maklon/invoices/${invoice.id}`, { headers })
      .then(r => r.ok && r.json())
      .then(d => d && setDetail(d))
      .catch(() => {});
  }, [invoice.id, headers]);

  const downloadPdf = async () => {
    setDownloading(true);
    try {
      const res = await fetch(`/api/dewi/maklon/invoices/${invoice.id}/pdf`, {
        headers: { Authorization: headers.Authorization },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `Invoice_${detail.invoice_number || invoice.id}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast.success('PDF invoice berhasil diunduh');
    } catch (e) {
      toast.error('Gagal mengunduh PDF invoice');
    } finally {
      setDownloading(false);
    }
  };

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader><DialogTitle>Detail faktur — {detail.invoice_number}</DialogTitle></DialogHeader>
        <div className="space-y-3 py-2 text-sm">
          <div className="grid grid-cols-2 gap-3">
            <div><span className="text-foreground/50">Klien:</span> <span className="font-semibold">{detail.client_name}</span></div>
            <div><span className="text-foreground/50">Order:</span> <span className="tabular-nums text-xs">{detail.order_code}</span></div>
            <div><span className="text-foreground/50">Tgl Terbit:</span> {detail.issue_date}</div>
            <div><span className="text-foreground/50">Jatuh Tempo:</span> {detail.due_date}</div>
            <div><span className="text-foreground/50">Termin:</span> {detail.payment_terms}</div>
            <div><span className="text-foreground/50">PPN:</span> {detail.tax_pct}%</div>
          </div>

          <GlassCard className="p-4">
            <div className="text-xs font-semibold text-foreground/60 mb-2">Rincian baris</div>
            <table className="w-full text-xs">
              <thead><tr className="text-foreground/50"><th className="text-left pb-1">Deskripsi</th><th className="text-right pb-1">Qty</th><th className="text-right pb-1">Harga</th><th className="text-right pb-1">Subtotal</th></tr></thead>
              <tbody>{(detail.lines || []).map((l, i) => (
                <tr key={i}><td className="py-1">{l.description}</td><td className="text-right">{l.qty} {l.unit}</td><td className="text-right">{fmt(l.unit_price)}</td><td className="text-right font-semibold">{fmt(l.line_total)}</td></tr>
              ))}</tbody>
            </table>
          </GlassCard>

          <div className="border-t border-foreground/10 pt-3 space-y-1 text-right">
            <div>Subtotal: <span className="font-semibold">{fmt(detail.subtotal)}</span></div>
            {detail.discount_amount > 0 && <div>Diskon: <span className="text-[hsl(var(--destructive))] ">- {fmt(detail.discount_amount)}</span></div>}
            <div>PPN ({detail.tax_pct}%): <span>{fmt(detail.tax_amount)}</span></div>
            <div className="text-base font-bold">Total: {fmt(detail.total_amount)}</div>
            <div className="text-[hsl(var(--success))] ">Dibayar: {fmt(detail.paid_amount)}</div>
            <div className="text-[hsl(var(--warning))] font-semibold">Saldo: {fmt(detail.balance_amount)}</div>
            <div>Status: <StatusBadge status={detail.status} /></div>
          </div>

          {detail.payments && detail.payments.length > 0 && (
            <div className="pt-3 border-t border-foreground/10">
              <div className="text-xs font-semibold text-foreground/60 mb-2">Riwayat Pembayaran</div>
              <div className="space-y-1 text-xs">
                {detail.payments.map(p => (
                  <div key={p.id} className="flex justify-between bg-foreground/5 rounded px-2 py-1">
                    <span>{p.payment_date} · {p.method}{p.reference_no ? ` · ${p.reference_no}` : ''}</span>
                    <span className="font-semibold text-[hsl(var(--success))] ">{fmt(p.amount)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Tutup</Button>
          <Button onClick={downloadPdf} disabled={downloading} data-testid="maklon-invoice-print-pdf" className="gap-2">
            <FileText className="w-4 h-4" />
            {downloading ? 'Menyiapkan…' : 'Cetak PDF faktur'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

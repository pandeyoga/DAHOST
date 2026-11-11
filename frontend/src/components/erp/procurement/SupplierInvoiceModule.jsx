/**
 * SupplierInvoiceModule — Faktur Supplier (AP dari Penerimaan)
 *
 * Menutup langkah terakhir siklus pengadaan (P2P) di dalam satu portal:
 *   PO → Penerimaan (GR) → **Faktur Supplier** → Persetujuan → Bayar.
 *
 * Nilai faktur memakai qty NET (diterima − ditolak) × harga per satuan DASAR
 * (INV-UOM-1), tetapi ditampilkan juga dalam satuan beli PO supaya cocok dengan
 * dokumen fisik dari supplier.
 *
 * 2026-11-03 (uji tugas): pembayaran hutang dipindah KE SINI (satu-satunya pintu). Dulu hanya ada di
 * Penyesuaian › "Diskon Pembelian", yang meminta UUID rekening, selalu mengirim diskon 2% (angka tetap
 * di kode untuk semua pemasok) walau tidak dipilih, dan hanya memuat faktur `sent` sehingga sisa
 * faktur yang dicicil tidak bisa dibayar. Potongan dari pemasok kini diisi manual, bawaan 0.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import FilterChips from '@/components/ui/filter-chips';
import {
  AlertTriangle, CheckCircle2, FileText,
  HandCoins, RefreshCw, Search, Send,
} from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { MoneyInput } from '@/components/ui/money-input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FormPopup from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Textarea } from '@/components/ui/textarea';
import { toast } from 'sonner';
import { EP, apiGet, apiPost, fmtDate, fmtNum, fmtRp } from './procApi';
import { PaymentHistoryList } from '../PaymentHistoryModal';
import CashAccountSelect, { usePaymentCashAccounts } from '../SdmCashAccountSelect';
import { currentRole } from '../portalAccess';
import { isFinanceRole } from '../../../lib/financeRoles';
import { useTaxProfile } from '../../../lib/taxProfile';
import { todayWIB } from '../../../lib/waktu';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';
import PageLayout, { DetailPanel } from '../layout/PageLayout';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';

export const AP_STATUS_META = {
  draft: { label: 'Draf', tone: 'muted' },
  sent: { label: 'Terkirim', tone: 'info' },
  // 2026-11-03: kunci status server = partial_paid (dulu `partially_paid` → badge jatuh ke "Draft")
  partial_paid: { label: 'Dibayar sebagian', tone: 'warning' },
  paid: { label: 'Lunas', tone: 'success' },
  cancelled: { label: 'Dibatalkan', tone: 'muted' },
  // status tagihan CMT (dewi_cmt_payments) — 2026-11-04 satu daftar dengan tagihan pemasok
  submitted: { label: 'Diajukan', tone: 'muted' },
  pending: { label: 'Menunggu', tone: 'muted' },
  unposted: { label: 'Belum dijurnal', tone: 'warning' },
  approved: { label: 'Disetujui · belum dijurnal', tone: 'warning' },
  posted: { label: 'Terjurnal', tone: 'info' },
};

// 2026-11-08 (Standar UI/UX v2): status = StatusBadge bersama (dulu pil warna palet langsung, huruf 10 px).
export function ApBadge({ status }) {
  const m = AP_STATUS_META[status] || { label: status || '—', tone: 'muted' };
  return <StatusBadge status={status} label={m.label} tone={m.tone} />;
}

/**
 * 2026-11-06 (Tahap 2): faktur dibuat DI HALAMAN (PANDUAN_UI G13) dan mencatat angka faktur pemasok yang
 * SEBENARNYA — qty & harga per baris, ongkos kirim, potongan. Selisihnya dengan penerimaan masuk HPP bahan
 * saat faktur dijurnal (bagian yang barangnya masih ada; sisanya 5-1900).
 */
export function CreateInvoicePanel({ token, gr, onClose, onCreated }) {
  const [taxPct, setTaxPct] = useState(0);
  const { profile: taxProfile } = useTaxProfile(token);
  const [invNo, setInvNo] = useState('');
  const [dueDate, setDueDate] = useState('');
  const [notes, setNotes] = useState('');
  const [freight, setFreight] = useState('');
  const [discount, setDiscount] = useState('');
  const [lines, setLines] = useState(() => (gr?.billable_lines || []).map((b) => ({
    key: b.key, name: b.material_name || b.key, unit: b.unit || '', maxQty: Number(b.qty || 0),
    grPrice: Number(b.price || 0), qty: String(Number(b.qty || 0)), price: String(Number(b.price || 0)),
  })));
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const setLine = (key, patch) => setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...patch } : l)));

  const billed = lines.filter((l) => Number(l.qty) > 0);
  const subtotal = billed.reduce((s, l) => s + Number(l.qty) * Number(l.price || 0), 0);
  const grValue = billed.reduce((s, l) => s + Number(l.qty) * l.grPrice, 0);
  const disc = Number(discount || 0);
  const frt = Number(freight || 0);
  const tax = Math.round((subtotal - disc) * Number(taxPct || 0)) / 100;
  const total = subtotal - disc + frt + tax;
  const diff = total - grValue - (taxProfile.pkp ? tax : 0);
  const overQty = lines.find((l) => Number(l.qty) - l.maxQty > 1e-6);
  // 2026-11-07 (audit form Tahap 5): qty/harga negatif & PPN di luar 0–100 dulu lolos ke server
  const negLine = lines.find((l) => Number(l.qty) < 0 || Number(l.price) < 0);
  const taxBad = !(Number(taxPct || 0) >= 0 && Number(taxPct || 0) <= 100);
  const problem = negLine ? `Qty dan harga ${negLine.name} tidak boleh negatif.`
    : !billed.length ? 'Isi qty faktur minimal satu baris.'
      : overQty ? `Qty ${overQty.name} melebihi yang belum ditagih (${fmtNum(overQty.maxQty)}).`
        : taxBad ? 'PPN harus antara 0 dan 100%.'
          : disc - subtotal > 0.5 ? 'Potongan tidak boleh melebihi nilai barang.' : '';

  const submit = async () => {
    if (problem) { setErr(problem); return; }
    setErr('');
    setSaving(true);
    try {
      const out = await apiPost(token, EP.apFromGr, {
        gr_ids: [gr.id],
        tax_pct: Number(taxPct || 0),
        supplier_faktur_number: invNo || undefined,   // 2026-11-03: dulu isian ini tidak ikut dikirim
        due_date: dueDate || undefined,
        notes: notes || undefined,
        freight_amount: frt,
        invoice_discount: disc,
        items_override: billed.map((l) => ({ gr_item_id: l.key, invoiced_qty: Number(l.qty), unit_price: Number(l.price || 0) })),
      });
      toast.success(`Faktur ${out?.invoice_number} dibuat dari ${gr.receipt_number}`);
      onCreated?.(out);
      onClose();
    } catch (e) {
      setErr(e.message);
      toast.error(e.message);
    } finally { setSaving(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" testId="ap-create-panel"
      judul={`Buat faktur dari ${gr.receipt_number}`} keterangan={gr.supplier_name}
      onSimpan={submit} menyimpan={saving} bisaSimpan={!problem} galat={err} labelSimpan="Buat faktur">
      <div className="space-y-4" data-testid="ap-create-modal">
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <div className="text-xs text-muted-foreground">Supplier</div>
            <div className="font-medium">{gr.supplier_name}</div>
            {gr.supplier_code && <div className="text-xs text-muted-foreground">{gr.supplier_code}</div>}
          </div>
          <div>
            <div className="text-xs text-muted-foreground">Referensi PO</div>
            <div>{gr.po_number || '—'}</div>
          </div>
        </div>

        <div className="border-y border-[var(--glass-border)] py-2 text-sm space-y-1">
          <div className="flex justify-between">
            <span className="text-muted-foreground">Qty diterima</span>
            <span className="tabular-nums">{fmtNum(gr.total_received)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Qty ditolak (tidak difakturkan)</span>
            <span className="tabular-nums text-[hsl(var(--danger-text))]">−{fmtNum(gr.total_rejected)}</span>
          </div>
          <div className="flex justify-between font-medium border-t border-[var(--glass-border)] pt-1">
            <span>Qty bersih difakturkan</span>
            <span className="tabular-nums">{fmtNum(gr.total_net)}</span>
          </div>
        </div>

        {/* 2026-11-06 (Tahap 2): angka di FAKTUR PEMASOK (bawaan = angka penerimaan) */}
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="ap-form-lines">
            <thead className="border-b border-[var(--glass-border)]">
              <tr className="text-left text-muted-foreground text-xs">
                <th className="pb-2">Barang</th>
                <th className="pb-2 text-right">Harga penerimaan</th>
                <th className="pb-2 text-right">Qty di faktur</th>
                <th className="pb-2 text-right">Harga di faktur</th>
                <th className="pb-2 text-right">Jumlah</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((l) => (
                <tr key={l.key} className="border-b border-[var(--glass-border)]">
                  <td className="py-1.5">{l.name}<div className="text-xs text-muted-foreground">sisa ditagih {fmtNum(l.maxQty)} {l.unit}</div></td>
                  <td className="py-1.5 text-right text-xs tabular-nums">{fmtRp(l.grPrice)}</td>
                  <td className="py-1.5 text-right">
                    <GlassInput type="number" min="0" step="any" value={l.qty} className="h-8 w-24 ml-auto text-right text-xs"
                      onChange={(e) => setLine(l.key, { qty: e.target.value })} data-testid={`ap-form-qty-${l.key}`} />
                  </td>
                  <td className="py-1.5 text-right">
                    <GlassInput type="number" min="0" step="any" value={l.price} className="h-8 w-28 ml-auto text-right text-xs"
                      onChange={(e) => setLine(l.key, { price: e.target.value })} data-testid={`ap-form-price-${l.key}`} />
                  </td>
                  <td className="py-1.5 text-right text-xs tabular-nums">{fmtRp(Number(l.qty || 0) * Number(l.price || 0))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium mb-1.5" htmlFor="ap-form-freight">Ongkos kirim di faktur</label>
            <MoneyInput glass id="ap-form-freight" value={freight} onChange={(e) => setFreight(e.target.value)}
                        placeholder="0" className="text-right" data-testid="ap-form-freight" />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1.5" htmlFor="ap-form-discount">Potongan di faktur</label>
            <MoneyInput glass id="ap-form-discount" value={discount} onChange={(e) => setDiscount(e.target.value)}
                        placeholder="0" className="text-right" data-testid="ap-form-discount" />
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            <label className="block text-sm font-medium mb-1.5">No. faktur pemasok</label>
            <GlassInput value={invNo} onChange={(e) => setInvNo(e.target.value)}
                        placeholder="opsional" data-testid="ap-form-supplier-invno" />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1.5">PPN dari supplier (%)</label>
            <GlassInput type="number" min="0" max="100" value={taxPct}
                        onChange={(e) => setTaxPct(e.target.value)} className="text-right"
                        data-testid="ap-form-tax" />
            <p className="text-xs text-muted-foreground mt-1" data-testid="ap-form-tax-note">{taxProfile.pkp ? 'PKP: PPN ini dikreditkan sebagai PPN Masukan — isi No. Faktur supplier.' : 'Non-PKP: PPN dari supplier tidak dapat dikreditkan, dicatat sebagai bagian harga beli.'}</p>
          </div>
          <div>
            <label className="block text-sm font-medium mb-1.5">Jatuh tempo</label>
            <DatePicker value={dueDate} onChange={setDueDate} testId="ap-form-duedate" />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium mb-1.5">Catatan</label>
          <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} data-testid="ap-form-notes" />
        </div>

        <div className="border-y border-[var(--glass-border)] py-2 text-sm space-y-1">
          <div className="flex justify-between">
            <span className="text-muted-foreground">Subtotal</span>
            <span className="tabular-nums" data-testid="ap-form-subtotal">{fmtRp(subtotal)}</span>
          </div>
          {disc > 0 && (
            <div className="flex justify-between">
              <span className="text-muted-foreground">Potongan</span>
              <span className="tabular-nums">−{fmtRp(disc)}</span>
            </div>
          )}
          {frt > 0 && (
            <div className="flex justify-between">
              <span className="text-muted-foreground">Ongkos kirim</span>
              <span className="tabular-nums">{fmtRp(frt)}</span>
            </div>
          )}
          <div className="flex justify-between">
            <span className="text-muted-foreground">PPN {taxPct || 0}%</span>
            <span className="tabular-nums">{fmtRp(tax)}</span>
          </div>
          <div className="flex justify-between font-bold border-t border-[var(--glass-border)] pt-1">
            <span>Total</span>
            <span className="tabular-nums" data-testid="ap-form-total">{fmtRp(total)}</span>
          </div>
        </div>
        {Math.abs(diff) >= 1 && (
          <p className="text-xs text-muted-foreground" data-testid="ap-form-diff-note">
            Selisih dengan nilai penerimaan {diff > 0 ? '+' : '−'}{fmtRp(Math.abs(diff))}
            {taxProfile.pkp ? '' : ' (termasuk PPN yang tidak dapat dikreditkan)'} — masuk HPP bahan untuk barang yang
            masih ada di gudang; bagian barang yang sudah terpakai dicatat sebagai selisih harga beli.
          </p>
        )}
        {problem && <Notice tone="warning" icon={AlertTriangle}>{problem}</Notice>}
      </div>
    </FormPopup>
  );
}

const PAYABLE = ['sent', 'partial_paid'];
export const canPay = (inv) => PAYABLE.includes(inv?.status) && Number(inv?.balance ?? inv?.total ?? 0) > 0;

export function PayInvoiceModal({ token, inv, onClose, onPaid }) {
  const isCmtBill = inv.kind === 'cmt';
  // 2026-11-07 (audit form Tahap 5): tagihan CMT hanya bisa dibayar sampai "bisa dibayar" (server
  // dewi_maklon_finance.pay_cmt_payment → core.maklon_ledger.cmt_bill_payable). Dulu bawaan & batasnya = sisa
  // tagihan, sehingga tagihan bertahan (selisih lebih tagih) selalu ditolak server "Bisa dibayar Rp X dari Rp Y".
  const balance = isCmtBill ? cmtPayable(inv) : Number(inv.balance ?? inv.total ?? 0);
  const { accounts, loaded } = usePaymentCashAccounts(token);
  const [accountId, setAccountId] = useState('');
  const [date, setDate] = useState(todayWIB());
  const [amount, setAmount] = useState(String(Math.round(balance)));
  const [discount, setDiscount] = useState('');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  // Tahap 8 fase 2: hutang ANTAR CV (tagihan tim jahit CV Sukma / nota aksesoris CV Dewi Aditya) — rekening CV lain yang
  // MENERIMA uangnya ikut dipilih; penerimaan di buku CV lain dibuat otomatis dengan nilai yang sama.
  const isIc = !!inv.intercompany;
  const otherCv = isCmtBill ? 'SMU' : (inv.entity === 'SMU' ? 'DA' : 'SMU');
  const { accounts: counterAccounts, loaded: counterLoaded } = usePaymentCashAccounts(token, otherCv);
  const [counterId, setCounterId] = useState('');

  const cash = Number(amount || 0);
  const disc = Number(discount || 0);
  const reduced = cash + disc;
  const left = balance - reduced;
  const problem = isCmtBill && balance <= 0 ? 'Belum ada yang bisa dibayar — seluruh sisa tagihan tertahan selisih; selesaikan dulu di Tagihan Vendor CMT.'
    : !accountId ? 'Pilih rekening pembayaran.'
    : isIc && !counterId ? `Pilih rekening ${otherCv === 'SMU' ? 'CV Sukma' : 'CV Dewi Aditya'} yang menerima.`
    : isIc && disc > 0 ? 'Hutang antar CV tidak memakai potongan pembayaran.'
    : cash <= 0 ? 'Jumlah dibayar harus lebih dari 0.'
      : left < -0.5 ? (isCmtBill
        ? `Melebihi yang bisa dibayar (${fmtRp(balance)}).`
        : `Jumlah bayar + potongan melebihi sisa hutang (${fmtRp(balance)}).`)
        : '';

  const submit = async () => {
    if (problem) { setErr(problem); return; }
    setErr('');
    setSaving(true);
    try {
      const isCmt = inv.kind === 'cmt';
      const out = isCmt
        ? await apiPost(token, `/api/dewi/maklon/finance/cmt-payments/${inv.id}/pay`, {
          cash_account_id: accountId, amount: cash, payment_date: date, notes: notes || undefined,
          ...(isIc ? { counter_cash_account_id: counterId } : {}),
        })
        : await apiPost(token, `/api/rahaza/ap-invoices/${inv.id}/payment`, {
          amount: cash, discount_amount: disc, account_id: accountId, date, notes: notes || undefined,
          ...(isIc ? { counter_cash_account_id: counterId } : {}),
        });
      const posting = isCmt
        ? { ok: !out?.post_error, je_number: out?.gl_je_number, error: out?.post_error }
        : out?._posting_result;
      if (posting?.ok) {
        toast.success(`Pembayaran ${fmtRp(cash)} untuk ${inv.invoice_number} tercatat · ${posting.je_number}`);
      } else {
        toast.warning(
          `Pembayaran tercatat, tetapi BELUM masuk buku besar: ${posting?.error || 'hasil posting tidak diketahui'}.`,
          { duration: 10000 },
        );
      }
      onPaid?.(out);
      onClose();
    } catch (e) {
      setErr(e.message);
      toast.error(e.message);
    } finally { setSaving(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="ap-pay-form"
      judul={`Bayar ${inv.invoice_number}`} keterangan={inv.vendor_name}
      onSimpan={submit} menyimpan={saving} bisaSimpan={!problem} labelSimpan="Bayar & catat ke buku besar"
      galat={err || (problem && (accountId || (isCmtBill && balance <= 0)) ? problem : undefined)}>
      <div className="space-y-4" data-testid="ap-pay-modal">
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div><div className="text-xs text-muted-foreground">Supplier</div><div className="font-medium">{inv.vendor_name}</div></div>
          <div><div className="text-xs text-muted-foreground">{isCmtBill ? 'Bisa dibayar' : 'Sisa hutang'}</div><div className="font-semibold tabular-nums" data-testid="ap-pay-cap">{fmtRp(balance)}</div></div>
        </div>
        {isCmtBill && (
          <p className="text-xs text-muted-foreground" data-testid="ap-pay-cmt-payable">
            Bisa dibayar {fmtRp(balance)} dari {fmtRp(inv.total)} (dibayar {fmtRp(inv.paid_amount || 0)}
            {Number(inv.blocked_amount || 0) > 0 ? `, tertahan ${fmtRp(inv.blocked_amount)} karena selisih tagihan — selesaikan di Tagihan Vendor CMT` : ''}).
          </p>
        )}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium mb-1.5">Bayar dari rekening</label>
            <CashAccountSelect accounts={accounts} loaded={loaded} value={accountId} onChange={setAccountId}
                               testId="ap-pay-account" />
          </div>
          {isIc && (
            <div data-testid="ap-pay-counter">
              <label className="block text-sm font-medium mb-1.5">Diterima di rekening {otherCv === 'SMU' ? 'CV Sukma' : 'CV Dewi Aditya'} (antar CV)</label>
              <CashAccountSelect accounts={counterAccounts} loaded={counterLoaded} value={counterId} onChange={setCounterId}
                                 testId="ap-pay-counter-account" />
            </div>
          )}
          <div>
            <label className="block text-sm font-medium mb-1.5" htmlFor="ap-pay-date">Tanggal bayar</label>
            <DatePicker id="ap-pay-date" value={date} onChange={(v) => setDate(v || todayWIB())} bolehKosong={false} testId="ap-pay-date" />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1.5" htmlFor="ap-pay-amount">Jumlah dibayar (keluar dari bank)</label>
            <MoneyInput glass id="ap-pay-amount" value={amount} onChange={(e) => setAmount(e.target.value)}
                        className="text-right" data-testid="ap-pay-amount" />
          </div>
          {inv.kind !== 'cmt' && (
            <div>
              <label className="block text-sm font-medium mb-1.5" htmlFor="ap-pay-discount">Potongan dari pemasok (opsional)</label>
              <MoneyInput glass id="ap-pay-discount" value={discount} onChange={(e) => setDiscount(e.target.value)}
                          placeholder="0" className="text-right" data-testid="ap-pay-discount" />
            </div>
          )}
        </div>
        {inv.kind !== 'cmt' && (
          <p className="text-xs text-muted-foreground">
            Isi potongan hanya bila pemasok memberi potongan tertulis (mis. bayar lebih cepat). Potongan mengurangi hutang
            tanpa uang keluar dan dicatat sebagai Potongan Pembelian.
          </p>
        )}
        <div>
          <label className="block text-sm font-medium mb-1.5" htmlFor="ap-pay-notes">Catatan</label>
          <GlassInput id="ap-pay-notes" value={notes} onChange={(e) => setNotes(e.target.value)}
                      placeholder="opsional, mis. no. referensi transfer" data-testid="ap-pay-notes" />
        </div>
        <div className="border-y border-[var(--glass-border)] py-2 text-sm space-y-1">
          <div className="flex justify-between"><span className="text-muted-foreground">Hutang berkurang</span>
            <span className="tabular-nums" data-testid="ap-pay-reduced">{fmtRp(reduced)}</span></div>
          <div className="flex justify-between font-medium border-t border-[var(--glass-border)] pt-1"><span>Sisa setelah dibayar</span>
            <span className="tabular-nums" data-testid="ap-pay-left">{fmtRp(Math.max(left, 0))}</span></div>
        </div>
      </div>
    </FormPopup>
  );
}

// 2026-11-04 (PANDUAN_UI G13): rincian faktur dibuka DI HALAMAN di atas daftar — dulu popup.
export function InvoiceDetail({ inv, onClose, onSend, sending, token, onPay }) {
  return (
    <DetailPanel title={`Faktur ${inv.invoice_number}`} description={inv.vendor_name} onClose={onClose} testId="ap-detail-panel"
      actions={<>
        {onPay && canPay(inv) && (
          <Button variant="success" onClick={() => onPay(inv)} data-testid="ap-detail-pay">
            <HandCoins className="w-4 h-4" /> Bayar
          </Button>
        )}
        {inv.status === 'draft' && (
          <Button variant="success" onClick={() => onSend(inv)} disabled={sending} data-testid="ap-detail-approve">
            <Send className="w-4 h-4" />
            {sending ? 'Memproses…' : 'Setujui & catat ke buku besar'}
          </Button>
        )}
      </>}>
      <div className="space-y-4" data-testid="ap-detail">
        <div className="flex items-center gap-2 flex-wrap">
          <ApBadge status={inv.status} />
          {inv.supplier_code && (
            <span className="text-xs px-2 py-0.5 rounded-full border border-[var(--glass-border)] bg-[var(--input-surface)]">
              {inv.supplier_code}
            </span>
          )}
          {(inv.po_numbers || []).map((p) => (
            <span key={p} className="text-xs px-2 py-0.5 rounded-full border border-[var(--glass-border)] bg-[var(--input-surface)]">
              PO {p}
            </span>
          ))}
          {(inv.gr_numbers || []).map((g) => (
            <span key={g} className="text-xs px-2 py-0.5 rounded-full border border-[var(--glass-border)] bg-[var(--input-surface)]">
              GR {g}
            </span>
          ))}
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
          <div><div className="text-xs text-muted-foreground">Supplier</div><div className="font-medium">{inv.vendor_name}</div></div>
          <div><div className="text-xs text-muted-foreground">Tanggal</div><div>{fmtDate(inv.issue_date)}</div></div>
          <div><div className="text-xs text-muted-foreground">Jatuh tempo</div><div>{fmtDate(inv.due_date)}</div></div>
          <div><div className="text-xs text-muted-foreground">Sisa</div><div className="font-semibold tabular-nums">{fmtRp(inv.balance)}</div></div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-[var(--glass-border)]">
              <tr className="text-left text-muted-foreground text-xs">
                <th className="pb-2">Item</th>
                <th className="pb-2 text-right">Qty (dasar)</th>
                <th className="pb-2 text-right">Qty (satuan beli)</th>
                <th className="pb-2 text-right">Harga / dasar</th>
                <th className="pb-2 text-right">Jumlah</th>
              </tr>
            </thead>
            <tbody data-testid="ap-detail-items">
              {(inv.items || []).map((it) => (
                <tr key={it.id} className="border-b border-[var(--glass-border)]">
                  <td className="py-2">
                    <div className="font-medium">{it.description || it.material_name}</div>
                    <div className="text-xs text-muted-foreground">GR {it.gr_number}</div>
                  </td>
                  <td className="py-2 text-right tabular-nums whitespace-nowrap">{fmtNum(it.qty)} {it.unit}</td>
                  <td className="py-2 text-right tabular-nums whitespace-nowrap">
                    {it.po_uom && it.po_uom !== it.unit
                      ? `${fmtNum(it.qty_input)} ${it.po_uom}`
                      : '—'}
                  </td>
                  <td className="py-2 text-right tabular-nums whitespace-nowrap">{fmtRp(it.price)}</td>
                  <td className="py-2 text-right tabular-nums whitespace-nowrap">{fmtRp(it.amount)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot className="font-semibold">
              <tr><td colSpan="4" className="py-1 text-right text-xs text-muted-foreground">Subtotal</td>
                  <td className="py-1 text-right tabular-nums whitespace-nowrap">{fmtRp(inv.subtotal)}</td></tr>
              {Number(inv.invoice_discount || 0) > 0 && (
                <tr><td colSpan="4" className="py-1 text-right text-xs text-muted-foreground">Potongan</td>
                    <td className="py-1 text-right text-xs tabular-nums">−{fmtRp(inv.invoice_discount)}</td></tr>
              )}
              {Number(inv.freight_amount || 0) > 0 && (
                <tr><td colSpan="4" className="py-1 text-right text-xs text-muted-foreground">Ongkos kirim</td>
                    <td className="py-1 text-right text-xs tabular-nums">{fmtRp(inv.freight_amount)}</td></tr>
              )}
              <tr><td colSpan="4" className="py-1 text-right text-xs text-muted-foreground">PPN {inv.tax_pct || 0}%</td>
                  <td className="py-1 text-right tabular-nums whitespace-nowrap">{fmtRp(inv.tax_amount)}</td></tr>
              <tr className="border-t-2 border-[var(--glass-border)]">
                <td colSpan="4" className="py-2 text-right text-xs">Total</td>
                <td className="py-2 text-right tabular-nums whitespace-nowrap">{fmtRp(inv.total)}</td></tr>
            </tfoot>
          </table>
        </div>

        {inv.notes && (
          <p className="text-xs text-muted-foreground"><span className="font-medium text-foreground">Catatan:</span> {inv.notes}</p>
        )}
        {/* 2026-11-06 (Tahap 2): ke mana selisih harga faktur vs penerimaan dicatat */}
        {(inv.gl_hpp_inventory !== undefined || inv.gl_ppv_posted !== undefined) && (
          <p className="text-xs text-muted-foreground" data-testid="ap-detail-hpp-note">
            Selisih harga masuk HPP bahan {fmtRp(inv.gl_hpp_inventory || 0)} · selisih harga beli
            (barang sudah terpakai / tanpa master) {fmtRp(inv.gl_ppv_posted || 0)}
          </p>
        )}

        {inv.status !== 'draft' && (
          <div className="pt-2 border-t border-[var(--glass-border)]" data-testid="ap-payment-history">
            <div className="text-sm font-medium text-foreground mb-2">
              Riwayat pembayaran · dibayar {fmtRp(inv.paid_amount || 0)}
              {inv.gl_je_number && <span className="ml-2 font-normal text-muted-foreground">jurnal faktur: {inv.gl_je_number}</span>}
            </div>
            <PaymentHistoryList token={token} kind="ap" invoiceId={inv.id} />
          </div>
        )}
      </div>
    </DetailPanel>
  );
}

export const CMT_PAYABLE = ['unposted', 'approved', 'posted', 'partial_paid', 'submitted', 'pending'];
/** "Bisa dibayar" tagihan CMT dari server; data lama tanpa angka itu → sisa tagihan. */
export const cmtPayable = (r) => Math.max(0, Number(r.payable_amount ?? r.balance ?? 0));

// tagihan CMT (`/api/production/cmt-billing`) → bentuk baris yang sama dengan faktur pemasok (Keuangan › Hutang)
export const cmtToRow = (p) => ({
  kind: 'cmt', id: p.id, invoice_number: p.payment_code, vendor_name: p.cmt_name || p.vendor_name,
  po_numbers: p.po_number ? [p.po_number] : [], issue_date: p.issue_date || p.period_end || p.created_at,
  total: p.amount, balance: p.outstanding_amount, paid_amount: p.paid_amount,
  payable_amount: p.payable_amount, blocked_amount: p.blocked_amount,
  // tagihan CMT lahir 'draft' lalu langsung dijurnal; draft = jurnalnya gagal → hutang nyata yang belum dijurnal
  status: (p.status || '').toLowerCase() === 'draft' ? 'unposted' : (p.status || '').toLowerCase(), gl_posted: p.gl_posted,
  due_date: p.due_date, total_pcs: p.total_pcs, business_type: p.business_type,
  // Tahap 8 fase 2: tagihan tim jahit CV Sukma = hutang antar CV (bayar → penerimaan CV Sukma otomatis)
  // 11 Nov 2026: CV dari server (tagihan PO maklon = CV Sukma); dulu semua tagihan CMT dicap 'DA'.
  intercompany: !!p.intercompany, entity: p.entity || (p.business_type === 'maklon' ? 'SMU' : 'DA'),
});

/**
 * Portal Pengadaan › Faktur Supplier: penerimaan siap difakturkan + daftar faktur pemasok.
 * 11 Nov 2026 (owner "tagihan tidak usah beda tab"): mode Keuangan (`financeMode`: tab Tagihan berisi faktur pemasok +
 * tagihan CMT) pindah ke SATU daftar Keuangan › Hutang (`finance/HutangModule`) yang memakai panel-panel di atas.
 */
export default function SupplierInvoiceModule({ token }) {
  const [tab, setTab] = useState('pending');
  const [grs, setGrs] = useState([]);
  const [invoices, setInvoices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [createGr, setCreateGr] = useState(null);
  const [detail, setDetail] = useState(null);
  const [paying, setPaying] = useState(null);
  const [sending, setSending] = useState(false);
  // Faktur Supplier juga dibuka dari portal Pengadaan; tombol bayar hanya untuk peran keuangan (FIN-02).
  const finance = isFinanceRole(currentRole());

  const load = useCallback(async () => {
    setLoading(true);
    setErr('');
    try {
      const [g, inv] = await Promise.all([
        apiGet(token, EP.grsForInvoice).catch(() => ({ items: [] })),
        apiGet(token, '/api/rahaza/ap-invoices?limit=5000').catch(() => []),
      ]);
      setGrs(g?.items || []);
      const ap = (Array.isArray(inv) ? inv : inv?.items || []).map((i) => ({ ...i, kind: 'ap' }));
      setInvoices(ap.sort((a, b) => String(b.issue_date || '').localeCompare(String(a.issue_date || ''))));
    } catch (e) {
      setErr(e.message);
      toast.error(`Gagal memuat faktur supplier: ${e.message}`);
    } finally { setLoading(false); }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const approve = async (inv) => {
    setSending(true);
    try {
      const out = await apiPost(token, `/api/rahaza/ap-invoices/${inv.id}/send`, {});
      // 2026-11-02 (audit Tambahan B): "dicatat ke buku besar" hanya bila posting GL benar-benar sukses.
      const posting = out?._posting_result;
      if (posting?.ok) {
        toast.success(`Faktur ${inv.invoice_number} disetujui & dicatat ke buku besar`);
      } else {
        toast.warning(
          `Faktur ${inv.invoice_number} disetujui, tetapi BELUM tercatat ke buku besar: `
          + `${posting?.error || 'hasil posting tidak diketahui'}. Perbaiki penyebabnya lalu posting ulang.`,
          { duration: 10000 },
        );
      }
      setDetail(null);
      await load();
    } catch (e) {
      toast.error(e.message);
    } finally { setSending(false); }
  };

  const filteredInv = useMemo(() => {
    const s = search.trim().toLowerCase();
    return invoices.filter((i) => {
      if (statusFilter && i.status !== statusFilter) return false;
      if (!s) return true;
      return [i.invoice_number, i.vendor_name, i.supplier_code, ...(i.po_numbers || [])]
        .filter(Boolean).some((v) => String(v).toLowerCase().includes(s));
    });
  }, [invoices, search, statusFilter]);
  const { page, setPage, totalPages, paged } = useClientPagination(filteredInv, 25);

  // PANDUAN_UI G1/G6 (2026-11-04): cetakan PageLayout — pil, cari, dan pilihan satu baris di kiri; muat ulang di
  // kanan. Dulu tombol muat ulang sendirian di satu baris, lalu pil di baris kedua, cari di baris ketiga.
  const filters = (
    <>
      <FilterChips value={tab} onChange={setTab} testId="ap-tab" ariaLabel="Tampilan" hideWhenEmpty={false}
        options={[{ key: 'pending', label: 'Siap difakturkan', count: grs.length }, { key: 'invoices', label: 'Faktur', count: invoices.length }]} />
      {tab === 'invoices' && (
        <>
          <div className="relative w-full sm:w-64">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <GlassInput className="pl-9 h-9" placeholder="Cari no. faktur, pemasok, PO…"
                        value={search} onChange={(e) => setSearch(e.target.value)}
                        data-testid="ap-search" />
          </div>
          <SmartNativeSelect value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
            className="h-9 w-44"
            data-testid="ap-filter-status">
            <option value="">Semua status</option>
            {Object.entries(AP_STATUS_META).map(([v, m]) => <option key={v} value={v}>{m.label}</option>)}
          </SmartNativeSelect>
          {(search || statusFilter) && (
            <span className="text-xs text-muted-foreground">{filteredInv.length} cocok</span>
          )}
        </>
      )}
    </>
  );

  return (
    <PageLayout
      testId="supplier-invoice-page"
      title="Faktur Supplier"
      subtitle="Faktur hutang dari penerimaan barang. Qty yang ditolak QC tidak ikut difakturkan."
      filters={filters}
      tools={<>
        {tab === 'pending' ? (
          <TombolUnduh namaBerkas="penerimaan-belum-difakturkan" namaLembar="Penerimaan" baris={grs} testId="ap-unduh"
            kolom={[
              { label: 'No. GR', nilai: (g) => g.receipt_number },
              { label: 'Pemasok', nilai: (g) => g.supplier_name },
              { label: 'Kode pemasok', nilai: (g) => g.supplier_code || '' },
              { label: 'PO', nilai: (g) => g.po_number || '' },
              { label: 'Qty bersih', nilai: (g) => Number(g.total_net) || 0 },
              { label: 'Nilai', nilai: (g) => Number(g.receivable_amount) || 0 },
            ]} />
        ) : (
          <TombolUnduh namaBerkas="faktur-pemasok" namaLembar="Faktur" baris={filteredInv} testId="ap-unduh"
            kolom={[
              { label: 'No. faktur', nilai: (i) => i.invoice_number },
              { label: 'Pemasok', nilai: (i) => i.vendor_name },
              { label: 'Referensi', nilai: (i) => (i.po_numbers || []).join(', ') || (i.gr_numbers || []).join(', ') },
              { label: 'Tanggal', nilai: (i) => fmtDate(i.issue_date) },
              { label: 'Jatuh tempo', nilai: (i) => (i.due_date ? fmtDate(i.due_date) : '') },
              { label: 'Total', nilai: (i) => Number(i.total) || 0 },
              { label: 'Sisa', nilai: (i) => Number(i.balance ?? i.total) || 0 },
              { label: 'Status', nilai: (i) => (AP_STATUS_META[i.status] || { label: i.status }).label },
            ]} />
        )}
        <Button size="icon" variant="outline" onClick={load} data-testid="ap-refresh" title="Muat ulang" aria-label="Muat ulang"><RefreshCw className="w-4 h-4" /></Button>
      </>}
      summary={err && <Notice tone="danger" icon={AlertTriangle}>{err}</Notice>}
      detail={createGr ? (
        <CreateInvoicePanel key={createGr.id} token={token} gr={createGr}
                            onClose={() => setCreateGr(null)}
                            onCreated={() => { load(); setTab('invoices'); }} />
      ) : detail && (
        <InvoiceDetail inv={detail} onClose={() => setDetail(null)} onSend={approve} sending={sending} token={token}
                       onPay={finance ? (inv) => { setDetail(null); setPaying(inv); } : null} />
      )}
    >
      {loading ? (
        <div className="flex items-center justify-center h-48">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[hsl(var(--primary))]" />
        </div>
      ) : tab === 'pending' ? (
        <GlassCard className="p-0 overflow-hidden">
          {grs.length === 0 ? (
            <EmptyState icon={CheckCircle2} title="Tidak ada penerimaan yang menunggu faktur" description="Penerimaan barang yang belum difakturkan akan muncul di sini." />
          ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-[var(--glass-border)]">
                <tr className="text-left">
                  <th>No. GR</th>
                  <th>Pemasok</th>
                  <th>PO</th>
                  <th className="text-right">Qty bersih</th>
                  <th className="text-right">Nilai</th>
                  <th className="text-right">Aksi</th>
                </tr>
              </thead>
              <tbody data-testid="ap-pending-body">
                {grs.map((g, idx) => (
                  <tr key={g.id} className="border-b border-[var(--glass-border)]"
                      data-testid={`ap-pending-row-${g.id}`}>
                    <td className="whitespace-nowrap">{g.receipt_number}</td>
                    <td>
                      <div className="font-medium">{g.supplier_name}</div>
                      {g.supplier_code && <div className="text-xs text-muted-foreground">{g.supplier_code}</div>}
                      {!g.supplier_id && (
                        <div className="text-xs text-[hsl(var(--warning-text))] flex items-center gap-1">
                          <AlertTriangle className="w-3 h-3" /> belum tertaut master
                        </div>
                      )}
                    </td>
                    <td className="whitespace-nowrap">{g.po_number || '—'}</td>
                    <td className="text-right tabular-nums">{fmtNum(g.total_net)}</td>
                    <td className="text-right tabular-nums">{fmtRp(g.receivable_amount)}</td>
                    <td className="text-right">
                      <Button size="sm" variant="outline" onClick={() => { setDetail(null); setCreateGr(g); }} data-testid={`ap-create-${g.id}`}>
                        Buat faktur
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          )}
        </GlassCard>
      ) : (
          <GlassCard className="p-0 overflow-hidden">
            {filteredInv.length === 0 ? (
              <EmptyState icon={FileText} title={invoices.length ? 'Tidak ada tagihan yang cocok' : 'Belum ada tagihan'}
                description={invoices.length ? 'Ubah pencarian atau penyaring.' : 'Faktur muncul setelah dibuat dari penerimaan barang.'} />
            ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-[var(--glass-border)]">
                  <tr className="text-left">
                    <th>No. faktur</th>
                    <th>Pemasok</th>
                    <th>Referensi</th>
                    <th>Tanggal</th>
                    <th className="text-right">Total</th>
                    <th className="text-right">Sisa</th>
                    <th>Status</th>
                    <th className="text-right">Aksi</th>
                  </tr>
                </thead>
                <tbody data-testid="ap-invoice-body">
                  {paged.map((i, idx) => (
                    <tr key={`${i.kind}-${i.id}`} className={`border-b border-[var(--glass-border)] ${detail?.id === i.id ? 'bg-[hsl(var(--primary)/0.06)]' : ''}`}
                        data-testid={`ap-invoice-row-${i.id}`}>
                      <td className="whitespace-nowrap">
                        <Button variant="link" size="sm" className="h-auto p-0" onClick={() => { setCreateGr(null); setDetail(detail?.id === i.id ? null : i); }} data-testid={`ap-view-${i.id}`}>{i.invoice_number}</Button>
                      </td>
                      <td>{i.vendor_name}{i.intercompany && <span className="block text-xs text-[hsl(var(--primary))]" data-testid={`ap-ic-${i.invoice_number}`}>Antar CV</span>}</td>
                      <td className="text-xs text-muted-foreground">
                        {(i.po_numbers || []).join(', ') || (i.gr_numbers || []).join(', ') || '—'}
                      </td>
                      <td className="whitespace-nowrap">{fmtDate(i.issue_date)}</td>
                      <td className="text-right tabular-nums">{fmtRp(i.total)}</td>
                      <td className="text-right tabular-nums">{fmtRp(i.balance ?? i.total)}</td>
                      <td><ApBadge status={i.status} /></td>
                      <td className="text-right whitespace-nowrap">
                        {finance && canPay(i) && (
                          <Button size="sm" variant="success" onClick={() => setPaying(i)}
                                  data-testid={`ap-pay-${i.id}`}>
                            Bayar
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            )}
            {totalPages > 1 && <div className="px-4 py-2"><PaginationLite page={page} totalPages={totalPages} total={filteredInv.length} pageSize={25} onPageChange={setPage} /></div>}
          </GlassCard>
      )}

      {paying && (
        <PayInvoiceModal token={token} inv={paying} onClose={() => setPaying(null)} onPaid={() => load()} />
      )}
    </PageLayout>
  );
}

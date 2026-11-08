/**
 * Nota Penjualan (Portal Penjualan) — penjualan langsung dari stok barang jadi.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout · pil status · tabel standar (kartu ringkas di HP) yang bisa diunduh ·
 * klik baris = rincian (popup) · nota baru, terima pembayaran, dan retur = form popup standar · tanggal memakai
 * DatePicker (dulu kotak tanggal bawaan peramban). Isian, validasi, dan panggilan server tidak berubah.
 */
import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Plus, Printer, ReceiptText, RefreshCw, Trash2, Undo2, Wallet, XCircle } from 'lucide-react';
import { toast } from 'sonner';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import { Button } from '@/components/ui/button';
import DatePicker from '@/components/ui/date-picker';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup from '@/components/ui/detail-popup';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { todayWIB } from '@/lib/waktu';
import { formatDateID } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatusBadge } from '../moduleAtoms';
import { apiGet, apiPost, apiFetch } from '../../../lib/api';
import SalesTaxFields from '../SalesTaxFields';
import { useTaxProfile, previewOutputTax } from '../../../lib/taxProfile';

const fmt = (n) => Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 0 });
const tgl = (ymd) => (ymd ? formatDateID(ymd) : '—');
const STATUS = {
  draft: { label: 'Draf', tone: 'muted' }, confirmed: { label: 'Belum lunas', tone: 'info' },
  paid: { label: 'Lunas', tone: 'success' }, cancelled: { label: 'Batal', tone: 'danger' },
  confirming: { label: 'Memproses', tone: 'warning' },
};
const statusLabel = (s) => (STATUS[s] || { label: s }).label;
// 2026-11-07 (audit form Tahap 5): rekening kas/bank tidak lagi terisi otomatis rekening PERTAMA (Kas Kecil).
const acctLabel = (a) => (a.gl_account_code ? `${a.name} · ${a.gl_account_code}` : a.name);
function CashSelect({ accounts, value, onChange, testId, className = 'w-full h-9' }) {
  return (
    <SmartNativeSelect value={value || ''} onChange={(e) => onChange(e.target.value)} className={className}
      searchPlaceholder="Cari rekening…" aria-label="Rekening kas/bank" data-testid={testId}>
      <option value="">— Pilih rekening —</option>
      {accounts.map((a) => <option key={a.id} value={a.id}>{acctLabel(a)}</option>)}
    </SmartNativeSelect>
  );
}

function Badge({ s }) {
  const m = STATUS[s] || { label: s, tone: 'default' };
  return <StatusBadge status={s} label={m.label} tone={m.tone} testId={`sale-status-${s}`} />;
}

/** Keterangan HPP per nota: perkiraan HPP master / tanpa biaya (dulu teks kecil kuning). */
function CatatanHpp({ r }) {
  return <>
    {r.cogs_basis && !['wac', 'fifo_batch', 'mixed'].includes(r.cogs_basis) && (
      <span className="block text-xs text-[hsl(var(--warning-text))]">{r.cogs_basis === 'hpp_master' ? 'Perkiraan HPP master' : 'Sebagian perkiraan'}</span>
    )}
    {r.uncosted_qty > 0 && !r.cogs_estimated && <span className="block text-xs text-[hsl(var(--warning-text))]">{r.uncosted_qty} pcs tanpa biaya</span>}
  </>;
}

async function openPdf(id, number) {
  const r = await apiFetch(`/sales/direct-sales/${id}/pdf`);
  if (!r.ok) return toast.error('Gagal membuat PDF');
  const url = URL.createObjectURL(await r.blob());
  window.open(url, '_blank') || (() => { const a = document.createElement('a'); a.href = url; a.download = `Nota_${number}.pdf`; a.click(); })();
}

export default function DirectSalesModule() {
  const [rows, setRows] = useState([]);
  const [filter, setFilter] = useState('');
  const [creating, setCreating] = useState(false);
  const [detail, setDetail] = useState(null);
  const [memuat, setMemuat] = useState(false);

  const load = async () => {
    setMemuat(true);
    try { setRows(await apiGet(`/sales/direct-sales${filter ? `?status=${filter}` : ''}`)); } catch (e) { toast.error(e.message); }
    finally { setMemuat(false); }
  };
  useEffect(() => { load(); }, [filter]); // eslint-disable-line react-hooks/exhaustive-deps

  const openDetail = async (id) => { try { setDetail(await apiGet(`/sales/direct-sales/${id}`)); } catch (e) { toast.error(e.message); } };
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(rows, 25);

  const kolom = [
    { kunci: 'nota', label: 'No. nota', hp: 'judul', isi: (r) => (
      <div data-testid={`sale-row-${r.note_number}`}>
        <p className="font-medium tabular-nums">{r.note_number}</p>
        {r.invoice_number && <p className="text-xs tabular-nums text-muted-foreground">{r.invoice_number}</p>}
      </div>) },
    { kunci: 'tanggal', label: 'Tanggal', isi: (r) => <span className="whitespace-nowrap">{tgl(r.sale_date)}</span> },
    { kunci: 'pelanggan', label: 'Pelanggan', hp: 'keterangan', isi: (r) => r.customer_name },
    { kunci: 'bayar', label: 'Bayar', isi: (r) => (r.payment_type === 'cash' ? 'Tunai' : `Tempo · jatuh tempo ${tgl(r.due_date)}`) },
    { kunci: 'total', label: 'Total', rata: 'kanan', isi: (r) => <span className="font-semibold tabular-nums whitespace-nowrap">Rp {fmt(r.total)}</span> },
    { kunci: 'hpp', label: 'HPP', rata: 'kanan', hp: false, isi: (r) => (
      <span className="tabular-nums whitespace-nowrap">{r.cogs_total != null ? `Rp ${fmt(r.cogs_total)}` : '—'}<CatatanHpp r={r} /></span>) },
    { kunci: 'status', label: 'Status', isi: (r) => <Badge s={r.status} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <Button size="icon-sm" variant="ghost" onClick={() => openPdf(r.id, r.note_number)} title="Cetak nota" aria-label="Cetak nota"
        data-testid={`sale-pdf-${r.note_number}`}><Printer /></Button>) },
  ];

  return (
    <PageLayout testId="direct-sales-page" title="Nota Penjualan"
      subtitle="Draf lalu konfirmasi: stok barang jadi keluar (FIFO), HPP dibukukan, piutang terbit; tunai langsung lunas."
      actions={<Button onClick={() => setCreating(true)} data-testid="sales-new"><Plus />Nota baru</Button>}
      filters={<SmartNativeSelect className="h-9 w-44" wrapperClassName="w-44" searchable={false} value={filter} onChange={(e) => setFilter(e.target.value)}
        aria-label="Status" data-testid="sales-filter">
        <option value="">Semua status</option><option value="draft">Draf</option><option value="confirmed">Belum lunas</option>
        <option value="paid">Lunas</option><option value="cancelled">Batal</option>
      </SmartNativeSelect>}
      tools={<>
        <TombolUnduh namaBerkas="nota-penjualan" namaLembar="Nota penjualan" baris={rows} testId="sales-unduh"
          kolom={[
            { label: 'No. nota', nilai: (r) => r.note_number }, { label: 'No. invoice', nilai: (r) => r.invoice_number || '' },
            { label: 'Tanggal', nilai: (r) => tgl(r.sale_date) }, { label: 'Pelanggan', nilai: (r) => r.customer_name || '' },
            { label: 'Bayar', nilai: (r) => (r.payment_type === 'cash' ? 'Tunai' : 'Tempo') },
            { label: 'Jatuh tempo', nilai: (r) => (r.payment_type === 'cash' ? '' : tgl(r.due_date)) },
            { label: 'Total', nilai: (r) => Number(r.total || 0) }, { label: 'HPP', nilai: (r) => (r.cogs_total != null ? Number(r.cogs_total) : '') },
            { label: 'Status', nilai: (r) => statusLabel(r.status) },
          ]} />
        <Button variant="outline" size="icon" onClick={load} disabled={memuat} title="Muat ulang" aria-label="Muat ulang" data-testid="sales-refresh">
          <RefreshCw className={memuat ? 'animate-spin' : ''} />
        </Button>
      </>}
      footer={rows.length > pageSize && (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />
      )}>
      <TabelData kolom={kolom} baris={paged} onKlikBaris={(r) => openDetail(r.id)} testId="sales-table"
        kosong={<EmptyState icon={ReceiptText} testId="sales-empty" title={filter ? 'Tidak ada nota dengan status ini' : 'Belum ada nota penjualan'}
          description={filter ? 'Pilih status lain.' : 'Klik Nota baru untuk membuat nota pertama.'} />} />
      {creating && <CreateSaleModal onClose={() => setCreating(false)} onSaved={(n) => { setCreating(false); load(); openDetail(n.id); }} />}
      {detail && <SaleDetailModal note={detail} onClose={() => setDetail(null)} onChanged={(n) => { setDetail(n); load(); }} />}
    </PageLayout>
  );
}

function CreateSaleModal({ onClose, onSaved }) {
  const [customers, setCustomers] = useState([]);
  const [stock, setStock] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [f, setF] = useState({ customer_id: '', payment_type: 'cash', cash_account_id: '', sale_date: todayWIB(), due_date: '', discount_amount: 0, notes: '' });
  // 2026-11-03: PPN mengikuti saklar Status Pajak (dulu pilihan bebas 0/11/12% atas DPP penuh)
  const { profile: taxProfile } = useTaxProfile();
  const [taxF, setTaxF] = useState({ kena_ppn: true, faktur_number: '', faktur_date: '' });
  const kenaPpn = !!taxProfile.pkp && taxF.kena_ppn !== false;
  const [items, setItems] = useState([{ material_id: '', qty: 1, price: 0 }]);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    Promise.all([apiGet('/sales/customers'), apiGet('/sales/fg-stock'), apiGet('/sales/cash-accounts')])
      .then(([c, s, a]) => { setCustomers(c); setStock(s); setAccounts(a); })
      .catch((e) => toast.error(e.message));
  }, []);
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }));
  const setItem = (i, k, v) => setItems((arr) => arr.map((it, idx) => {
    if (idx !== i) return it;
    const n = { ...it, [k]: v };
    if (k === 'material_id') { const s = stock.find((x) => x.material_id === v); n.price = s?.default_price || n.price || 0; }
    return n;
  }));
  const subtotal = items.reduce((s, it) => s + (Number(it.qty) || 0) * (Number(it.price) || 0), 0);
  const disc = Number(f.discount_amount) || 0;
  const tax = previewOutputTax(taxProfile, subtotal - disc, kenaPpn);
  const total = subtotal - disc + tax;
  const cust = customers.find((c) => c.id === f.customer_id);

  const submit = async () => {
    if (!f.customer_id) return toast.error('Pilih pelanggan.');
    if (f.payment_type === 'cash' && !f.cash_account_id) return toast.error('Pilih rekening kas/bank penerima.');
    const clean = items.filter((it) => it.material_id);
    if (!clean.length) return toast.error('Tambahkan minimal satu item.');
    // qty = bilangan bulat pcs (server membulatkan ke bawah diam-diam: 1,5 → 1)
    const bad = clean.find((it) => !(Number(it.qty) > 0) || !Number.isInteger(Number(it.qty)) || Number(it.price) < 0);
    if (bad) return toast.error(`${stock.find((x) => x.material_id === bad.material_id)?.sku || 'Item'}: qty harus bilangan bulat lebih dari 0 dan harga tidak boleh negatif.`);
    const over = clean.find((it) => { const s = stock.find((x) => x.material_id === it.material_id); return s && Number(it.qty) > Number(s.available_qty); });
    if (over) { const s = stock.find((x) => x.material_id === over.material_id); return toast.error(`Stok ${s.sku} tidak cukup (tersedia ${s.available_qty}).`); }
    setBusy(true);
    try {
      const n = await apiPost('/sales/direct-sales', { ...f, items: clean.map((it) => ({ material_id: it.material_id, qty: Number(it.qty), price: Number(it.price) || 0 })),
                                                        discount_amount: Number(f.discount_amount) || 0, due_date: f.due_date || undefined, kena_ppn: kenaPpn,
                                                        ...(kenaPpn ? { faktur_number: taxF.faktur_number, faktur_date: taxF.faktur_date } : {}) });
      toast.success(`Draf ${n.note_number} tersimpan`); onSaved(n);
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" judul="Nota penjualan baru" onSimpan={submit} menyimpan={busy}
      labelSimpan="Simpan draf" keterangan="Draf belum mengurangi stok — stok keluar saat nota dikonfirmasi." testId="sale-form">
      <div className="grid gap-4 sm:grid-cols-3">
        <Isian label="Pelanggan" wajib petunjuk={cust ? `Termin: ${cust.payment_terms}` : undefined}>
          <SmartNativeSelect className="h-9 w-full" value={f.customer_id} onChange={(e) => set('customer_id', e.target.value)} searchPlaceholder="Cari kode atau nama pelanggan…"
            aria-label="Pelanggan" data-testid="sale-form-customer">
            <option value="">— Pilih pelanggan —</option>{customers.map((c) => <option key={c.id} value={c.id}>{`${c.code} · ${c.name}`}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Tanggal"><DatePicker value={f.sale_date} onChange={(v) => set('sale_date', v)} bolehKosong={false} testId="sale-form-date" /></Isian>
        <Isian label="Pembayaran">
          <SmartNativeSelect className="h-9 w-full" searchable={false} value={f.payment_type} onChange={(e) => set('payment_type', e.target.value)}
            aria-label="Pembayaran" data-testid="sale-form-payment"><option value="cash">Tunai (langsung lunas)</option><option value="credit">Tempo (piutang)</option></SmartNativeSelect>
        </Isian>
        {f.payment_type === 'cash' ? (
          <Isian label="Masuk ke kas/bank" wajib>
            <CashSelect accounts={accounts} value={f.cash_account_id} onChange={(v) => set('cash_account_id', v)} testId="sale-form-cash-account" />
          </Isian>
        ) : (
          <Isian label="Jatuh tempo" petunjuk="Kosong = mengikuti termin pelanggan.">
            <DatePicker value={f.due_date} onChange={(v) => set('due_date', v)} placeholder="Ikut termin" min={f.sale_date || undefined} testId="sale-form-due" />
          </Isian>
        )}
        <Isian label="PPN"><SalesTaxFields profile={taxProfile} value={taxF} onChange={setTaxF} compact testIdPrefix="sale-form-tax" /></Isian>
        <Isian label="Diskon (Rp)"><MoneyInput value={f.discount_amount} onChange={(e) => set('discount_amount', e.target.value)} data-testid="sale-form-discount" /></Isian>
      </div>
      <div className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-medium text-foreground">Item (stok barang jadi tersedia: {stock.length} SKU)</p>
          <Button type="button" size="sm" variant="outline" onClick={() => setItems((a) => [...a, { material_id: '', qty: 1, price: 0 }])} data-testid="sale-form-add-item"><Plus />Tambah baris</Button>
        </div>
        {/* 2026-11-07: di HP baris item digulir menyamping (dulu kotak qty menciut & tombol hapus terpotong) */}
        <div className="overflow-x-auto">
          <Table className="min-w-[640px]">
            <TableHeader><TableRow>
              <TableHead>SKU</TableHead><TableHead className="w-20 text-right">Stok</TableHead><TableHead className="w-24">Qty</TableHead>
              <TableHead className="w-36">Harga</TableHead><TableHead className="w-32 text-right">Jumlah</TableHead><TableHead className="w-10" />
            </TableRow></TableHeader>
            <TableBody>{items.map((it, i) => { const s = stock.find((x) => x.material_id === it.material_id); return (
              <TableRow key={i}>
                <TableCell className="py-1.5"><SmartNativeSelect className="h-9 w-full" value={it.material_id} onChange={(e) => setItem(i, 'material_id', e.target.value)} searchPlaceholder="Cari SKU / nama…"
                  aria-label="SKU" data-testid={`sale-item-${i}-sku`}><option value="">— Pilih SKU —</option>{stock.map((x) => <option key={x.material_id} value={x.material_id}>{`${x.sku} · ${x.name} (stok ${x.available_qty})`}</option>)}</SmartNativeSelect></TableCell>
                <TableCell className="py-1.5 text-right tabular-nums">{s ? s.available_qty : '—'}{s?.hpp > 0 && <span className="block text-xs text-muted-foreground">HPP {fmt(s.hpp)}</span>}</TableCell>
                <TableCell className="py-1.5"><Input type="number" min="1" step="1" value={it.qty} onChange={(e) => setItem(i, 'qty', e.target.value)} className="h-9" aria-label="Qty" data-testid={`sale-item-${i}-qty`} /></TableCell>
                <TableCell className="py-1.5"><MoneyInput value={it.price} onChange={(e) => setItem(i, 'price', e.target.value)} className="h-9" data-testid={`sale-item-${i}-price`} /></TableCell>
                <TableCell className="py-1.5 text-right font-semibold tabular-nums">{fmt((Number(it.qty) || 0) * (Number(it.price) || 0))}</TableCell>
                <TableCell className="py-1.5"><Button type="button" size="icon-sm" variant="ghost" onClick={() => setItems((a) => a.filter((_, idx) => idx !== i))}
                  title="Hapus baris" aria-label="Hapus baris"><Trash2 /></Button></TableCell>
              </TableRow>); })}</TableBody>
          </Table>
        </div>
      </div>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <Isian label="Catatan" htmlFor="sale-notes" className="min-w-[200px] flex-1">
          <Input id="sale-notes" value={f.notes} onChange={(e) => set('notes', e.target.value)} data-testid="sale-form-notes" />
        </Isian>
        <div className="space-y-0.5 text-right text-sm" data-testid="sale-form-totals">
          <p>Subtotal <b className="tabular-nums">Rp {fmt(subtotal)}</b></p>
          {tax > 0 && <p>PPN 12% × DPP 11/12 <b className="tabular-nums">Rp {fmt(tax)}</b></p>}
          {Number(f.discount_amount) > 0 && <p>Diskon <b className="tabular-nums">- Rp {fmt(f.discount_amount)}</b></p>}
          <p className="text-base">Total <b className="tabular-nums">Rp {fmt(total)}</b></p>
        </div>
      </div>
    </FormPopup>
  );
}

function SaleDetailModal({ note, onClose, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [pay, setPay] = useState(null);
  const [ret, setRet] = useState(null);
  const [accounts, setAccounts] = useState([]);
  useEffect(() => { apiGet('/sales/cash-accounts').then(setAccounts).catch(() => {}); }, []);
  const inv = note.invoice;
  const balance = inv ? Number(inv.balance || 0) : 0;
  const returnedQty = (mid) => (note.returns || []).reduce((s, r) => s + r.items.filter((i) => i.material_id === mid).reduce((a, i) => a + i.qty, 0), 0);
  const canReturn = ['confirmed', 'paid'].includes(note.status) && note.items.some((it) => it.qty - returnedQty(it.material_id) > 0);
  const act = async (fn, ok) => { setBusy(true); try { const n = await fn(); toast.success(ok); onChanged(n.note || n); } catch (e) { toast.error(e.message); } finally { setBusy(false); } };
  const confirm = async () => (await confirmDialog({ title: `Konfirmasi ${note.note_number}?`, body: 'Stok barang jadi dikurangi dan jurnal dibuat.', confirmLabel: 'Konfirmasi' }))
    && act(() => apiPost(`/sales/direct-sales/${note.id}/confirm`, {}), 'Nota dikonfirmasi');
  const cancel = async () => (await confirmDialog({ title: `Batalkan draf ${note.note_number}?`, confirmLabel: 'Batalkan draf', cancelLabel: 'Kembali', danger: true }))
    && act(() => apiPost(`/sales/direct-sales/${note.id}/cancel`, {}), 'Draf dibatalkan');
  const doPay = () => {
    if (!pay.cash_account_id) return toast.error('Pilih rekening kas/bank penerima.');
    if (!(Number(pay.amount) > 0)) return toast.error('Jumlah harus lebih dari 0.');
    if (Number(pay.amount) > balance + 0.5) return toast.error(`Jumlah melebihi sisa tagihan (Rp ${fmt(balance)}).`);
    return act(async () => { await apiPost(`/sales/direct-sales/${note.id}/payment`, { ...pay, amount: Number(pay.amount) }); setPay(null); return apiGet(`/sales/direct-sales/${note.id}`); }, 'Pembayaran dicatat');
  };
  const openReturn = () => setRet({ items: note.items.map((it) => ({ material_id: it.material_id, sku: it.sku, max: it.qty - returnedQty(it.material_id), qty: 0, condition: 'good' })), reason: '', refund_method: balance > 0 ? 'credit' : 'cash', cash_account_id: '' });
  const doReturn = async () => {
    const items = ret.items.filter((i) => Number(i.qty) > 0).map((i) => ({ material_id: i.material_id, qty: Number(i.qty), condition: i.condition }));
    if (!items.length) return toast.error('Isi qty retur minimal satu item.');
    const over = ret.items.find((i) => Number(i.qty) > i.max);
    if (over) return toast.error(`${over.sku}: maksimal retur ${over.max} pcs.`);
    if (ret.refund_method === 'cash' && !ret.cash_account_id) return toast.error('Pilih rekening kas/bank untuk refund tunai.');
    if (!(await confirmDialog({ title: 'Proses retur?', body: 'Stok kembali, nota kredit & jurnal balik dibuat.', confirmLabel: 'Proses retur' }))) return;
    act(async () => { const r = await apiPost(`/sales/direct-sales/${note.id}/returns`, { ...ret, items }); setRet(null); toast.info(`Nota kredit ${r.cn_number}${r.refund_amount ? ` · refund Rp ${fmt(r.refund_amount)}` : ''}${r.customer_credit ? ` · saldo kredit pelanggan Rp ${fmt(r.customer_credit)}` : ''}`); return apiGet(`/sales/direct-sales/${note.id}`); }, 'Retur diproses');
  };
  const gl = useMemo(() => [
    inv?.gl_je_number && `Invoice: ${inv.gl_je_number}`, note.cogs_je_number && `HPP: ${note.cogs_je_number}`,
    note.cogs_post_error && `HPP gagal: ${note.cogs_post_error}`, note.ar_post_error && `Invoice gagal: ${note.ar_post_error}`, note.payment_error && `Kas gagal: ${note.payment_error}`,
  ].filter(Boolean), [inv, note]);

  return (
    <>
      <DetailPopup open={!pay && !ret} onClose={onClose} judul={`Nota ${note.note_number}`} testId="sale-detail"
        keterangan={`${tgl(note.sale_date)} · ${note.customer_name} · ${note.payment_type === 'cash' ? 'Tunai' : `Tempo, jatuh tempo ${tgl(note.due_date)}`}${note.invoice_number ? ` · Invoice ${note.invoice_number}` : ''}`}
        status={<Badge s={note.status} />}
        aksi={<>
          <Button size="sm" variant="outline" onClick={() => openPdf(note.id, note.note_number)} data-testid="sale-detail-pdf"><Printer />Cetak nota</Button>
          {canReturn && <Button size="sm" variant="outline" onClick={openReturn} disabled={busy} data-testid="sale-detail-return"><Undo2 />Retur</Button>}
          {note.status === 'draft' && <Button size="sm" variant="destructive" onClick={cancel} disabled={busy} data-testid="sale-detail-cancel"><XCircle />Batalkan</Button>}
          {note.status === 'draft' && <Button size="sm" variant="success" onClick={confirm} disabled={busy} data-testid="sale-detail-confirm"><CheckCircle2 />Konfirmasi</Button>}
          {note.status === 'confirmed' && balance > 0 && <Button size="sm" onClick={() => setPay({ amount: balance, cash_account_id: '', date: todayWIB() })} disabled={busy} data-testid="sale-detail-pay"><Wallet />Terima pembayaran</Button>}
        </>}>
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-medium text-foreground">Item</p>
            <TombolUnduh namaBerkas={`nota-${note.note_number}`} namaLembar="Item" baris={note.items} testId="sale-detail-unduh"
              kolom={[
                { label: 'SKU', nilai: (it) => it.sku }, { label: 'Nama', nilai: (it) => it.name || '' },
                { label: 'Qty', nilai: (it) => Number(it.qty || 0) }, { label: 'Harga', nilai: (it) => Number(it.price || 0) },
                { label: 'Jumlah', nilai: (it) => Number(it.amount || 0) }, { label: 'HPP FIFO', nilai: (it) => (it.fg_cogs != null ? Number(it.fg_cogs) : '') },
              ]} />
          </div>
          <div className="overflow-x-auto">
            <Table data-testid="sale-detail-items">
              <TableHeader><TableRow>
                <TableHead>SKU</TableHead><TableHead className="text-right">Qty</TableHead><TableHead className="text-right">Harga</TableHead>
                <TableHead className="text-right">Jumlah</TableHead><TableHead className="text-right">HPP FIFO</TableHead>
              </TableRow></TableHeader>
              <TableBody>{note.items.map((it, i) => (
                <TableRow key={i}>
                  <TableCell><span className="tabular-nums">{it.sku}</span> <span className="text-muted-foreground">{it.name}</span></TableCell>
                  <TableCell className="text-right tabular-nums">{it.qty}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmt(it.price)}</TableCell>
                  <TableCell className="text-right font-semibold tabular-nums">{fmt(it.amount)}</TableCell>
                  <TableCell className="text-right tabular-nums">{it.fg_cogs != null ? fmt(it.fg_cogs) : '—'}
                    {it.fg_cogs_estimated > 0 && <span className="block text-xs text-[hsl(var(--warning-text))]">+ {fmt(it.fg_cogs_estimated)} perkiraan HPP master ({it.fg_cogs_uncosted_qty} pcs)</span>}
                    {it.fg_cogs_uncosted_qty > 0 && !it.fg_cogs_estimated && <span className="block text-xs text-[hsl(var(--warning-text))]">{it.fg_cogs_uncosted_qty} tanpa biaya</span>}</TableCell>
                </TableRow>))}</TableBody>
            </Table>
          </div>
        </div>
        <div className="flex flex-wrap justify-between gap-3 text-sm">
          <div className="space-y-1">
            {gl.map((g, i) => <p key={i} className={`text-xs tabular-nums ${g.includes('gagal') ? 'text-[hsl(var(--danger-text))]' : 'text-muted-foreground'}`} data-testid="sale-detail-gl">Jurnal {g}</p>)}
            {note.uncosted_qty > 0 && !note.cogs_estimated && <p className="flex items-center gap-1 text-[hsl(var(--warning-text))]"><AlertTriangle className="h-4 w-4" />{note.uncosted_qty} pcs keluar tanpa lapisan biaya — HPP lebih rendah dari kenyataan.</p>}
            {note.cogs_estimated > 0 && <p className="flex items-center gap-1 text-[hsl(var(--warning-text))]"><AlertTriangle className="h-4 w-4" />Rp {fmt(note.cogs_estimated)} HPP memakai perkiraan HPP master ({note.uncosted_qty} pcs tanpa lapisan biaya batch).</p>}
            {inv && <p>Piutang: dibayar Rp {fmt(inv.paid_amount)} · sisa <b data-testid="sale-detail-balance">Rp {fmt(inv.balance)}</b> · status invoice <StatusBadge status={inv.status} /></p>}
          </div>
          <div className="space-y-0.5 text-right">
            <p>Subtotal Rp {fmt(note.subtotal)}</p>
            {note.tax_amount > 0 && <p>PPN {note.tax_pct}% Rp {fmt(note.tax_amount)}</p>}
            {note.discount_amount > 0 && <p>Diskon - Rp {fmt(note.discount_amount)}</p>}
            <p className="text-base">Total <b>Rp {fmt(note.total)}</b></p>
            {note.cogs_total != null && <p className="text-muted-foreground">HPP Rp {fmt(note.cogs_total)} · Laba kotor Rp {fmt(note.subtotal - note.discount_amount - note.cogs_total)}</p>}
          </div>
        </div>
        {note.returns?.length > 0 && (
          <div className="space-y-2" data-testid="sale-returns-list">
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-medium text-foreground">Riwayat retur</p>
              <TombolUnduh namaBerkas={`retur-${note.note_number}`} namaLembar="Retur" baris={note.returns} testId="sale-returns-unduh"
                kolom={[
                  { label: 'No. retur', nilai: (r) => r.return_number }, { label: 'Tanggal', nilai: (r) => tgl(r.return_date) },
                  { label: 'Item', nilai: (r) => r.items.map((i) => `${i.sku} ×${i.qty}`).join(', ') },
                  { label: 'Kredit', nilai: (r) => Number(r.total || 0) }, { label: 'Nota kredit', nilai: (r) => r.cn_number || '' },
                  { label: 'Refund', nilai: (r) => Number(r.refund_amount || 0) }, { label: 'Kredit pelanggan', nilai: (r) => Number(r.customer_credit || 0) },
                  { label: 'Alasan', nilai: (r) => r.reason || '' },
                ]} />
            </div>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader><TableRow>
                  <TableHead>No. retur</TableHead><TableHead>Tanggal</TableHead><TableHead>Item</TableHead>
                  <TableHead className="text-right">Kredit</TableHead><TableHead>Nota kredit & jurnal</TableHead><TableHead>Keterangan</TableHead>
                </TableRow></TableHeader>
                <TableBody>{note.returns.map((r) => (
                  <TableRow key={r.id} data-testid={`sale-return-row-${r.return_number}`}>
                    <TableCell className="tabular-nums">{r.return_number}</TableCell>
                    <TableCell className="whitespace-nowrap">{tgl(r.return_date)}</TableCell>
                    <TableCell>{r.items.map((i) => `${i.sku} ×${i.qty}`).join(', ')}</TableCell>
                    <TableCell className="text-right font-semibold tabular-nums whitespace-nowrap">Rp {fmt(r.total)}</TableCell>
                    <TableCell className="text-muted-foreground">{r.cn_number}{r.cn_je_number ? ` · ${r.cn_je_number}` : ''}{r.cogs_je_number ? ` · HPP ${r.cogs_je_number}` : ''}</TableCell>
                    <TableCell>
                      {r.refund_amount > 0 && <span className="block text-[hsl(var(--success-text))]">Refund Rp {fmt(r.refund_amount)}</span>}
                      {r.customer_credit > 0 && <span className="block text-[hsl(var(--warning-text))]">Kredit pelanggan Rp {fmt(r.customer_credit)}</span>}
                      {r.reason && <span className="block text-muted-foreground">“{r.reason}”</span>}
                    </TableCell>
                  </TableRow>))}</TableBody>
              </Table>
            </div>
          </div>
        )}
      </DetailPopup>

      <FormPopup open={!!pay} onClose={() => setPay(null)} ukuran="pendek" judul={`Terima pembayaran · ${note.note_number}`}
        keterangan={`Sisa tagihan Rp ${fmt(balance)}.`} onSimpan={doPay} menyimpan={busy} labelSimpan="Simpan pembayaran" testId="sale-pay-form">
        {pay && <>
          <Isian label="Jumlah" wajib><MoneyInput value={pay.amount} onChange={(e) => setPay((p) => ({ ...p, amount: e.target.value }))} data-testid="sale-pay-amount" /></Isian>
          <Isian label="Kas/bank" wajib><CashSelect accounts={accounts} value={pay.cash_account_id} onChange={(v) => setPay((p) => ({ ...p, cash_account_id: v }))} testId="sale-pay-account" /></Isian>
          <Isian label="Tanggal"><DatePicker value={pay.date} onChange={(v) => setPay((p) => ({ ...p, date: v }))} bolehKosong={false} testId="sale-pay-date" /></Isian>
        </>}
      </FormPopup>

      <FormPopup open={!!ret} onClose={() => setRet(null)} ukuran="panjang" judul={`Retur penjualan · ${note.note_number}`}
        keterangan="Pilih qty retur per item. Stok kembali (bila baik), nota kredit & jurnal balik dibuat." onSimpan={doReturn} menyimpan={busy}
        labelSimpan="Proses retur" testId="sale-return-form">
        {ret && <>
          <div className="overflow-x-auto">
            <Table className="min-w-[520px]">
              <TableHeader><TableRow>
                <TableHead>SKU</TableHead><TableHead className="text-right">Bisa diretur</TableHead><TableHead className="w-24">Qty retur</TableHead><TableHead className="w-56">Kondisi</TableHead>
              </TableRow></TableHeader>
              <TableBody>{ret.items.map((it, i) => (
                <TableRow key={it.material_id}>
                  <TableCell className="tabular-nums">{it.sku}</TableCell>
                  <TableCell className="text-right tabular-nums">{it.max}</TableCell>
                  <TableCell><Input type="number" min="0" max={it.max} value={it.qty} disabled={it.max <= 0} aria-label="Qty retur"
                    onChange={(e) => setRet((r) => ({ ...r, items: r.items.map((x, idx) => (idx === i ? { ...x, qty: e.target.value } : x)) }))} className="h-9" data-testid={`sale-return-qty-${i}`} /></TableCell>
                  <TableCell><SmartNativeSelect className="h-9 w-full" searchable={false} value={it.condition} aria-label="Kondisi"
                    onChange={(e) => setRet((r) => ({ ...r, items: r.items.map((x, idx) => (idx === i ? { ...x, condition: e.target.value } : x)) }))}
                    data-testid={`sale-return-cond-${i}`}><option value="good">Baik (kembali ke stok)</option><option value="damaged">Rusak (tidak ke stok)</option></SmartNativeSelect></TableCell>
                </TableRow>
              ))}</TableBody>
            </Table>
          </div>
          <Isian label="Alasan" htmlFor="sale-return-reason"><Input id="sale-return-reason" value={ret.reason} onChange={(e) => setRet((r) => ({ ...r, reason: e.target.value }))} data-testid="sale-return-reason" /></Isian>
          <div className="grid gap-4 sm:grid-cols-2">
            <Isian label="Kelebihan kredit">
              <SmartNativeSelect className="h-9 w-full" searchable={false} value={ret.refund_method} onChange={(e) => setRet((r) => ({ ...r, refund_method: e.target.value }))}
                aria-label="Kelebihan kredit" data-testid="sale-return-refund"><option value="credit">Potong tagihan / simpan sebagai kredit pelanggan</option><option value="cash">Refund tunai dari kas</option></SmartNativeSelect>
            </Isian>
            {ret.refund_method === 'cash' && (
              <Isian label="Kas/bank" wajib><CashSelect accounts={accounts} value={ret.cash_account_id} onChange={(v) => setRet((r) => ({ ...r, cash_account_id: v }))} testId="sale-return-account" /></Isian>
            )}
          </div>
        </>}
      </FormPopup>
    </>
  );
}

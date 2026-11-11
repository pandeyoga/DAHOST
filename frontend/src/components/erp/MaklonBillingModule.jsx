/**
 * Piutang klien maklon (menu Maklon › Piutang klien) — 2026-11-06, Tahap 2 (keputusan owner).
 *
 * Tidak ada lagi langkah "Terbitkan faktur". Begitu PO maklon dikonfirmasi lahir piutang TERJADWAL
 * (qty pesan × harga jasa); pendapatan dicatat otomatis setiap barang dikirim ke klien; pembayaran klien
 * dicatat terhadap piutang PO (sebelum barang dikirim = uang muka, otomatis dipakai saat pendapatan
 * dicatat). Faktur hanya DOKUMEN CETAK — per kiriman atau per PO, berapa pun jumlahnya.
 *
 * Sumber data: /api/dewi/maklon/receivables (satu dokumen piutang per PO di rahaza_ar_invoices).
 * PANDUAN_UI: PageLayout · rincian PO = popup (DetailPanel) · isi kiriman di bawah barisnya (RowDetail).
 * Standar UI/UX v2 (8 Nov 2026): semua tabel bisa diunduh (Excel/CSV), form pembayaran = FormPopup + DatePicker,
 * cari ± 16 rem, warna status token. Selama form pembayaran terbuka, popup rincian disembunyikan (tidak bertumpuk).
 */
import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import { AlertCircle, Banknote, CreditCard, FileText, RefreshCw, Search } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import { Input } from '@/components/ui/input';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import FilterChips from '@/components/ui/filter-chips';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { MoneyInput } from '@/components/ui/money-input';
import { Skeleton } from '@/components/ui/skeleton';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import PageLayout, { DetailPanel, RowDetail, RowToggle } from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';
import { formatDateID, formatRupiah } from '@/lib/format';
import { todayWIB } from '@/lib/waktu';
import { filterCashAccountsByCv } from './SdmCashAccountSelect';

const fmt = formatRupiah;
const STATUS = {
  scheduled:    { label: 'Terjadwal',          tone: 'info' },
  issued:       { label: 'Belum dibayar',      tone: 'warning' },
  partial_paid: { label: 'Dibayar sebagian',   tone: 'warning' },
  overdue:      { label: 'Lewat jatuh tempo',  tone: 'danger' },
  paid:         { label: 'Lunas',              tone: 'success' },
  cancelled:    { label: 'Dibatalkan',         tone: 'muted' },
  draft:        { label: 'Draf',               tone: 'muted' },
};
const ArStatus = ({ status }) => {
  const s = STATUS[status] || { label: status || '—', tone: 'default' };
  return <StatusBadge status={s.label} tone={s.tone} />;
};

async function apiJson(path, headers, opts = {}) {
  const r = await fetch(path, { headers, ...opts });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || `Permintaan gagal (HTTP ${r.status})`);
  return d;
}

async function openPdf(path, headers, filename) {
  const r = await fetch(path, { headers: { Authorization: headers.Authorization } });
  if (!r.ok) { toast.error('Faktur gagal dibuat'); return; }
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export default function MaklonBillingModule({ token }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);
  const [data, setData] = useState({ items: [], counts: {}, summary: {} });
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState('');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      setData(await apiJson('/api/dewi/maklon/receivables', headers));
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, [headers]);
  useEffect(() => { load(); }, [load]);

  const rows = useMemo(() => {
    const s = search.trim().toLowerCase();
    return (data.items || []).filter((r) => {
      if (status === 'terjadwal' && r.status !== 'scheduled') return false;
      if (status === 'belum_lunas' && !(r.amount_due > 0.005)) return false;
      if (status === 'lunas' && r.status !== 'paid') return false;
      if (!s) return true;
      return [r.po_number, r.client_name, r.invoice_number].some((v) => (v || '').toLowerCase().includes(s));
    });
  }, [data.items, status, search]);
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(rows, 25);
  const c = data.counts || {};
  const sm = data.summary || {};

  return (
    <PageLayout
      testId="maklon-billing"
      title="Piutang klien"
      subtitle="Piutang klien maklon per PO: terjadwal saat dikonfirmasi, tertagih saat barang dikirim, lalu dibayar klien."
      filters={(data.items || []).length > 0 && <>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="pl-8" placeholder="Cari PO, klien, nomor piutang" value={search}
            onChange={(e) => setSearch(e.target.value)} data-testid="mkl-ar-search" />
        </div>
        <FilterChips value={status} onChange={setStatus} testId="mkl-ar-status" ariaLabel="Status piutang"
          options={[{ key: '', label: 'Semua', count: (data.items || []).length },
            { key: 'terjadwal', label: 'Terjadwal', count: c.terjadwal || 0 },
            { key: 'belum_lunas', label: 'Belum lunas', count: c.belum_lunas || 0 },
            { key: 'lunas', label: 'Lunas', count: c.lunas || 0 }]} />
      </>}
      tools={<>
        <TombolUnduh namaBerkas="piutang-klien-maklon" namaLembar="Piutang klien" baris={rows} testId="mkl-ar-unduh"
          kolom={[
            { label: 'PO', nilai: (r) => r.po_number || '' }, { label: 'Nomor piutang', nilai: (r) => r.invoice_number || '' },
            { label: 'Klien', nilai: (r) => r.client_name || '' }, { label: 'Status', nilai: (r) => (STATUS[r.status] || { label: r.status }).label },
            { label: 'Nilai PO', nilai: (r) => Number(r.scheduled_total || 0) }, { label: 'Tertagih', nilai: (r) => Number(r.billed_total || 0) },
            { label: 'Dibayar', nilai: (r) => Number(r.paid_total || 0) }, { label: 'Sisa tertagih', nilai: (r) => Number(r.amount_due || 0) },
            { label: 'Jatuh tempo', nilai: (r) => (r.due_date ? formatDateID(r.due_date) : '') },
          ]} />
        <Button variant="outline" size="icon" onClick={load} title="Muat ulang" aria-label="Muat ulang" data-testid="billing-refresh-btn">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </>}
      summary={<>
        {error && <Notice tone="danger" icon={AlertCircle}>{error}</Notice>}
        {(data.items || []).length > 0 && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="mkl-ar-summary">
            <StatTile label="Terjadwal (belum jatuh tempo)" value={fmt(sm.scheduled_remaining)} sub="barang belum dikirim" />
            <StatTile label="Tertagih belum dibayar" value={fmt(sm.amount_due)} accent={sm.amount_due > 0 ? 'warning' : 'muted'} />
            <StatTile label="Uang muka belum terpakai" value={fmt(sm.advance_balance)} sub="dipakai otomatis saat barang dikirim" />
            <StatTile label="Lewat jatuh tempo" value={fmt(sm.overdue)} accent={sm.overdue > 0 ? 'danger' : 'muted'} />
          </div>
        )}
      </>}
      detail={selected && (
        <ReceivableDetail key={selected} arId={selected} headers={headers} token={token}
          onClose={() => setSelected(null)} onChanged={load} />
      )}
      footer={rows.length > pageSize && (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />
      )}
    >
      <GlassCard className="p-0 overflow-hidden">
        {loading && !(data.items || []).length ? (
          <div className="space-y-2 p-4">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-11 rounded-lg" />)}</div>
        ) : (
          <Table data-testid="mkl-ar-table">
            <TableHeader>
              <TableRow>
                <TableHead>PO</TableHead>
                <TableHead>Klien</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Nilai PO</TableHead>
                <TableHead className="text-right">Tertagih</TableHead>
                <TableHead className="text-right">Dibayar</TableHead>
                <TableHead className="text-right">Sisa tertagih</TableHead>
                <TableHead>Jatuh tempo</TableHead>
                <TableHead className="text-right">Aksi</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.length === 0 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={9} className="p-0 [&>div]:py-8">
                    <EmptyState icon={Banknote} title="Belum ada piutang klien"
                      description="Piutang muncul begitu PO maklon dikonfirmasi (menu PO Maklon)." />
                  </TableCell>
                </TableRow>
              )}
              {paged.map((r) => (
                <TableRow key={r.id} data-testid={`mkl-ar-row-${r.po_number}`}
                  className={selected === r.id ? 'bg-[hsl(var(--primary)/0.06)]' : ''}>
                  <TableCell className="whitespace-nowrap">
                    <Button variant="link" size="sm" className="h-auto p-0 font-semibold" onClick={() => setSelected(r.id)}>
                      {r.po_number || '—'}
                    </Button>
                    <div className="text-xs text-muted-foreground">{r.invoice_number}{r.mode === 'lama' ? ' · faktur lama' : ''}</div>
                  </TableCell>
                  <TableCell>{r.client_name}</TableCell>
                  <TableCell><ArStatus status={r.status} />{r.post_error && <div className="mt-1 text-xs text-[hsl(var(--danger-text))]">Jurnal tertunda</div>}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">{fmt(r.scheduled_total)}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">{fmt(r.billed_total)}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">{fmt(r.paid_total)}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">
                    {r.amount_due > 0.005 ? <span className="font-semibold text-[hsl(var(--warning-text))]">{fmt(r.amount_due)}</span> : fmt(0)}
                  </TableCell>
                  <TableCell className="whitespace-nowrap">{r.due_date ? formatDateID(r.due_date) : '—'}</TableCell>
                  <TableCell className="text-right">
                    <Button variant="outline" size="sm" onClick={() => setSelected(r.id)} data-testid={`mkl-ar-open-${r.po_number}`}>Rincian</Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </GlassCard>
    </PageLayout>
  );
}

export function ReceivableDetail({ arId, headers, token, onClose, onChanged }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  const [openShip, setOpenShip] = useState(null);
  const [paying, setPaying] = useState(false);
  const load = useCallback(async () => {
    try { setD(await apiJson(`/api/dewi/maklon/receivables/${arId}`, headers)); }
    catch (e) { setErr(e.message); }
  }, [arId, headers]);
  useEffect(() => { load(); }, [load]);
  const refresh = () => { load(); onChanged(); };
  const v2 = d?.mode === 'terjadwal';
  const canPay = v2 && d && d.status !== 'cancelled' && d.outstanding_total > 0.005;

  const printPo = () => openPdf(`/api/dewi/maklon/receivables/${arId}/invoice.pdf`, headers, `Faktur_${d.invoice_number}.pdf`);
  const printShip = (g) => openPdf(
    `/api/dewi/maklon/receivables/${arId}/invoice.pdf?shipment_id=${encodeURIComponent(g.shipment_id)}&dispatch_seq=${g.dispatch_seq}`,
    headers, `Faktur_${d.invoice_number}_${g.seq_no}.pdf`);

  // Form pembayaran menggantikan popup rincian sementara (tidak ada popup bertumpuk); Batal → rincian lagi.
  if (paying && d) {
    return (
      <PaymentForm receivable={d} headers={headers} token={token}
        onClose={() => setPaying(false)} onDone={() => { setPaying(false); refresh(); }} />
    );
  }

  return (
    <DetailPanel testId="mkl-ar-detail" onClose={onClose}
      title={d ? `${d.po_number} · ${d.client_name}` : 'Memuat…'}
      description={d && (v2
        ? `Piutang ${d.invoice_number}. Nilai PO ${fmt(d.scheduled_total)} · tertagih ${fmt(d.billed_total)} · dibayar ${fmt(d.paid_total)} · sisa PO ${fmt(d.outstanding_total)}.`
        : `Faktur lama ${d.invoice_number} — dikelola dengan alur lama (Keuangan › Piutang).`)}
      actions={d && <>
        <Button variant="outline" onClick={printPo} data-testid="mkl-ar-print-po"><FileText className="w-4 h-4" />Cetak faktur PO</Button>
        {canPay && <Button onClick={() => setPaying(true)} data-testid="mkl-ar-pay"><CreditCard className="w-4 h-4" />Catat pembayaran</Button>}
      </>}>
      {err && <Notice tone="danger" icon={AlertCircle}>{err}</Notice>}
      {!d ? <Skeleton className="h-24 rounded-lg" /> : <>
        {d.post_error && <Notice tone="warning" icon={AlertCircle} title="Jurnal belum tercatat">{d.post_error}</Notice>}
        {(d.held || []).length > 0 && (
          <Notice tone="warning" icon={AlertCircle} title="Kelebihan kirim belum ditagih">
            {d.held.map((h) => `${h.qty} pcs`).join(', ')} dikirim melebihi pesanan tanpa alasan — isi alasan lewat koreksi kiriman supaya bisa ditagih.
          </Notice>
        )}
        {d.advance_balance > 0.005 && (
          <p className="text-sm text-muted-foreground">Uang muka klien <b className="text-foreground tabular-nums">{fmt(d.advance_balance)}</b> belum terpakai — otomatis menutup piutang saat barang berikutnya dikirim.</p>
        )}

        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-semibold text-foreground">Per ukuran</p>
          <TombolUnduh namaBerkas={`piutang-${d.po_number}-per-ukuran`} namaLembar="Per ukuran" baris={d.lines || []} testId="mkl-ar-lines-unduh"
            kolom={[
              { label: 'Barang', nilai: (ln) => `${ln.sku || ln.description || ''}${ln.size ? ` · ${ln.size}` : ''}` },
              { label: 'Dipesan', nilai: (ln) => Number(ln.qty_ordered ?? ln.qty ?? 0) }, { label: 'Dikirim', nilai: (ln) => ln.qty_dispatched ?? '' },
              { label: 'Tertagih', nilai: (ln) => ln.qty_billed ?? '' }, { label: 'Harga jasa', nilai: (ln) => Number(ln.unit_price || 0) },
              { label: 'Nilai terjadwal', nilai: (ln) => Number(ln.subtotal || 0) },
            ]} />
        </div>
        <Table>
          <TableHeader><TableRow>
            <TableHead>Barang</TableHead><TableHead className="text-right">Dipesan</TableHead>
            <TableHead className="text-right">Dikirim</TableHead><TableHead className="text-right">Tertagih</TableHead>
            <TableHead className="text-right">Harga jasa</TableHead><TableHead className="text-right">Nilai terjadwal</TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {(d.lines || []).map((ln) => (
              <TableRow key={ln.line_id || ln.item_id}>
                <TableCell>{ln.sku || ln.description} {ln.size ? <span className="text-muted-foreground">· {ln.size}</span> : null}</TableCell>
                <TableCell className="text-right tabular-nums">{ln.qty_ordered ?? ln.qty}</TableCell>
                <TableCell className="text-right tabular-nums">{ln.qty_dispatched ?? '—'}</TableCell>
                <TableCell className="text-right tabular-nums">{ln.qty_billed ?? '—'}</TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap">{fmt(ln.unit_price)}</TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap">{fmt(ln.subtotal)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>

        {v2 && <>
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-foreground">Kiriman yang sudah ditagih</p>
            <TombolUnduh namaBerkas={`piutang-${d.po_number}-kiriman`} namaLembar="Kiriman" baris={d.dispatches || []} testId="mkl-ar-dispatch-unduh"
              kolom={[
                { label: 'Surat jalan', nilai: (g) => `${g.shipment_number || ''} · kirim ke-${g.dispatch_seq}` },
                { label: 'Tanggal', nilai: (g) => (g.date ? formatDateID(g.date) : '') }, { label: 'Nilai', nilai: (g) => Number(g.total || 0) },
                { label: 'Dibayar', nilai: (g) => Number(g.paid || 0) }, { label: 'Sisa', nilai: (g) => Number(g.balance || 0) },
              ]} />
          </div>
          <Table data-testid="mkl-ar-dispatches">
            <TableHeader><TableRow>
              <TableHead className="w-10" /><TableHead>Surat jalan</TableHead><TableHead>Tanggal</TableHead>
              <TableHead className="text-right">Nilai</TableHead><TableHead className="text-right">Dibayar</TableHead>
              <TableHead className="text-right">Sisa</TableHead><TableHead className="text-right">Faktur</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {(d.dispatches || []).length === 0 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={7} className="p-0 [&>div]:py-8">
                    <EmptyState icon={FileText} title="Belum ada kiriman ke klien"
                      description="Pendapatan dicatat otomatis saat barang dikirim lewat Kirim ke Buyer." />
                  </TableCell>
                </TableRow>
              )}
              {(d.dispatches || []).map((g) => {
                const key = `${g.shipment_id}:${g.dispatch_seq}`;
                const open = openShip === key;
                return (
                  <Fragment key={key}>
                    <TableRow>
                      <TableCell><RowToggle open={open} onClick={() => setOpenShip(open ? null : key)} /></TableCell>
                      <TableCell className="whitespace-nowrap">{g.shipment_number || '—'} · kirim ke-{g.dispatch_seq}</TableCell>
                      <TableCell className="whitespace-nowrap">{g.date ? formatDateID(g.date) : '—'}</TableCell>
                      <TableCell className="text-right tabular-nums whitespace-nowrap">{fmt(g.total)}</TableCell>
                      <TableCell className="text-right tabular-nums whitespace-nowrap">{fmt(g.paid)}</TableCell>
                      <TableCell className="text-right tabular-nums whitespace-nowrap">{fmt(g.balance)}</TableCell>
                      <TableCell className="text-right">
                        <Button variant="outline" size="sm" onClick={() => printShip(g)} data-testid={`mkl-ar-print-${g.seq_no}`}>
                          <FileText className="w-3.5 h-3.5" />Cetak
                        </Button>
                      </TableCell>
                    </TableRow>
                    {open && (
                      <RowDetail colSpan={7}>
                        <div className="text-sm space-y-1">
                          {g.lines.map((ln) => (
                            <div key={ln.po_item_id} className="flex justify-between gap-3">
                              <span>{ln.sku} {ln.size ? `· ${ln.size}` : ''} — {ln.qty} pcs × {fmt(ln.unit_price)}</span>
                              <span className="tabular-nums">{fmt(ln.amount)}</span>
                            </div>
                          ))}
                          <div className="text-xs text-muted-foreground">
                            Jurnal: {g.journals.map((j) => `${j.je_number}${j.reverse ? ' (koreksi)' : ''}`).join(', ')}
                          </div>
                        </div>
                      </RowDetail>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        </>}

        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-semibold text-foreground">Pembayaran klien</p>
          <TombolUnduh namaBerkas={`piutang-${d.po_number}-pembayaran`} namaLembar="Pembayaran" baris={d.payments || []} testId="mkl-ar-pay-unduh"
            kolom={[
              { label: 'Tanggal', nilai: (p) => (p.date ? formatDateID(p.date) : '') }, { label: 'Status', nilai: (p) => (p.status === 'voided' ? 'Dibatalkan' : 'Berlaku') },
              { label: 'Rekening', nilai: (p) => p.account_name || '' }, { label: 'Referensi', nilai: (p) => p.reference_no || '' },
              { label: 'Jumlah', nilai: (p) => Number(p.amount || 0) }, { label: 'Menutup piutang', nilai: (p) => Number(p.ar_portion || 0) },
              { label: 'Uang muka', nilai: (p) => Number(p.advance_portion || 0) }, { label: 'Jurnal', nilai: (p) => p.je_number || '' },
            ]} />
        </div>
        <Table data-testid="mkl-ar-payments">
          <TableHeader><TableRow>
            <TableHead>Tanggal</TableHead><TableHead>Rekening</TableHead><TableHead className="text-right">Jumlah</TableHead>
            <TableHead className="text-right">Menutup piutang</TableHead><TableHead className="text-right">Uang muka</TableHead>
            <TableHead>Jurnal</TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {(d.payments || []).length === 0 && (
              <TableRow className="hover:bg-transparent">
                <TableCell colSpan={6} className="p-0 [&>div]:py-8">
                  <EmptyState title="Klien belum membayar untuk PO ini" />
                </TableCell>
              </TableRow>
            )}
            {(d.payments || []).map((p) => (
              <TableRow key={p.id} className={p.status === 'voided' ? 'opacity-50' : ''}>
                <TableCell className="whitespace-nowrap">{p.date ? formatDateID(p.date) : '—'}{p.status === 'voided' ? ' · dibatalkan' : ''}</TableCell>
                <TableCell>{p.account_name || '—'}{p.reference_no ? ` · ${p.reference_no}` : ''}</TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap">{fmt(p.amount)}</TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap">{fmt(p.ar_portion)}</TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap">{fmt(p.advance_portion)}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{p.je_number || '—'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </>}
    </DetailPanel>
  );
}

export function PaymentForm({ receivable, headers, token, onClose, onDone }) {
  // rekening kas/bank AKTIF (SSOT yang sama dengan pemilih rekening Keuangan/SDM)
  const [accounts, setAccounts] = useState([]);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    fetch('/api/rahaza/payment-cash-accounts', { headers: { Authorization: `Bearer ${token}` } })
      // Tahap 8: uang klien maklon masuk ke rekening CV Sukma (buku SMU) — rekening CV lain disembunyikan.
      .then((r) => (r.ok ? r.json() : [])).then((d) => setAccounts(filterCashAccountsByCv(Array.isArray(d) ? d : [], 'SMU')))
      .catch(() => setAccounts([])).finally(() => setLoaded(true));
  }, [token]);
  const limit = Number(receivable.outstanding_total || 0);
  const due = Number(receivable.amount_due || 0);
  const [amount, setAmount] = useState(due > 0 ? due : limit);
  const [account, setAccount] = useState('');
  const [date, setDate] = useState(todayWIB);
  const [ref, setRef] = useState('');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const n = Number(amount || 0);
  const problem = !account ? 'Pilih rekening penerima.'
    : !(n > 0) ? 'Jumlah harus lebih dari 0.'
      : n > limit + 0.5 ? `Jumlah melebihi sisa PO (${fmt(limit)}).` : '';
  const toAdvance = Math.max(0, n - due);
  const save = async () => {
    setSaving(true);
    try {
      const out = await apiJson(`/api/dewi/maklon/receivables/${receivable.id}/payments`, headers, {
        method: 'POST',
        body: JSON.stringify({ amount: n, cash_account_id: account, payment_date: date, reference_no: ref, notes }),
      });
      toast.success(`Pembayaran tercatat${out.gl_je_number ? ` · ${out.gl_je_number}` : ''}`);
      onDone();
    } catch (e) { toast.error(e.message); }
    finally { setSaving(false); }
  };
  return (
    <FormPopup open onClose={onClose} ukuran="pendek" judul="Catat pembayaran klien" testId="mkl-pay-form"
      keterangan={`${receivable.po_number} · ${receivable.client_name}. Tertagih belum dibayar ${fmt(due)} · sisa PO ${fmt(limit)}; kelebihan di atas tagihan dicatat sebagai uang muka.`}
      onSimpan={save} menyimpan={saving} bisaSimpan={!problem} labelSimpan="Simpan"
      galat={problem && account ? problem : null}>
      <Isian label="Jumlah diterima" wajib htmlFor="mkl-pay-amount">
        <MoneyInput id="mkl-pay-amount" value={amount} onChange={(e) => setAmount(e.target.value)} data-testid="mkl-pay-amount" />
      </Isian>
      <Isian label="Masuk ke rekening" wajib>
        <SmartNativeSelect value={account} onChange={(e) => setAccount(e.target.value)} className="h-9 w-full" aria-label="Rekening" data-testid="mkl-pay-account">
          <option value="">{loaded ? '— Pilih rekening —' : 'Memuat rekening…'}</option>
          {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}{a.gl_account_code ? ` · ${a.gl_account_code}` : ''}</option>)}
        </SmartNativeSelect>
      </Isian>
      <Isian label="Tanggal">
        <DatePicker value={date} onChange={setDate} bolehKosong={false} testId="mkl-pay-date" />
      </Isian>
      <Isian label="No. referensi" htmlFor="mkl-pay-ref">
        <Input id="mkl-pay-ref" value={ref} onChange={(e) => setRef(e.target.value)} placeholder="Mis. nomor transfer" />
      </Isian>
      <Isian label="Catatan" htmlFor="mkl-pay-notes">
        <Input id="mkl-pay-notes" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Opsional" />
      </Isian>
      {n > 0 && !problem && toAdvance > 0.5 && (
        <p className="text-sm text-muted-foreground">{fmt(Math.min(n, due))} menutup piutang · {fmt(toAdvance)} menjadi uang muka.</p>
      )}
    </FormPopup>
  );
}

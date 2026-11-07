/**
 * ThreeWayMatchModule — Rekonsiliasi PO (PO ↔ Penerimaan barang ↔ Faktur supplier)
 * Phase 27 — P2P Flow Completion
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, penyaring satu baris, daftar = tabel (kartu ringkas di HP),
 * detail satu PO = popup (dulu menggantikan seluruh halaman dengan tombol "Kembali"), form cadangan
 * "faktur dari penerimaan" = FormPopup, tabel bisa diunduh Excel/CSV, label bahasa Indonesia.
 * Data, endpoint, dan aturan pencocokan tidak berubah.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { Plus, RefreshCw, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import DatePicker from '@/components/ui/date-picker';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { toast } from 'sonner';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from './moduleAtoms';
import { useTaxProfile } from '../../lib/taxProfile';
import { formatDateID, formatRupiah } from '@/lib/format';
import { finStatus } from '@/lib/financeLabels';

const API = process.env.REACT_APP_BACKEND_URL;

// ─── Helpers ───────────────────────────────────────────────────────────────
function fmtRp(v) {
  if (v === null || v === undefined || v === '') return '—';
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return formatRupiah(n);
}
function fmtNum(v) { return Number(v || 0).toLocaleString('id-ID'); }
const fmtDate = (v) => formatDateID(v);
const fmtPct = (v) => `${Number(v) > 0 ? '+' : ''}${Number(v || 0).toLocaleString('id-ID', { maximumFractionDigits: 2 })}%`;

const STATUS_META = {
  matched:  { label: 'Cocok',            tone: 'success' },
  pending:  { label: 'Belum ada faktur', tone: 'muted' },
  over:     { label: 'Lebih tagih',      tone: 'danger' },
  under:    { label: 'Kurang tagih',     tone: 'warning' },
  variance: { label: 'Selisih',          tone: 'warning' },
};
const statusLabel = (s) => (STATUS_META[s] || STATUS_META.pending).label;

function MatchBadge({ status }) {
  const m = STATUS_META[status] || STATUS_META.pending;
  return <StatusBadge status={status} label={m.label} tone={m.tone} />;
}

const GR_STATUS = {
  draft: { label: 'Draf', tone: 'muted' },
  received: { label: 'Diterima', tone: 'success' },
  completed: { label: 'Selesai', tone: 'success' },
  partial_received: { label: 'Diterima sebagian', tone: 'warning' },
};
function GrBadge({ status }) {
  const m = GR_STATUS[status] || { label: status || '—', tone: 'default' };
  return <StatusBadge status={status} label={m.label} tone={m.tone} />;
}
function InvBadge({ status }) {
  const m = finStatus(status);
  return <StatusBadge status={status} label={m.label} tone={m.tone} />;
}

/** Warna selisih: lebih tagih = merah, kurang tagih = kuning, nol = abu. */
const toneSelisih = (v, ambang = 0) => (
  v > ambang ? 'text-[hsl(var(--danger-text))]' : v < -ambang ? 'text-[hsl(var(--warning-text))]' : 'text-muted-foreground'
);

// ─── Form cadangan: faktur supplier dari penerimaan barang ─────────────────
function CreateAPFromGRDialog({ open, onClose, headers, onSuccess }) {
  const [grs, setGrs] = useState([]);
  const [selectedIds, setSelectedIds] = useState(new Set());
  // 2026-11-03: bawaan 0 (dulu 11) — isi sesuai PPN yang DITAGIH supplier di fakturnya.
  const [taxPct, setTaxPct] = useState('0');
  const [supplierFaktur, setSupplierFaktur] = useState('');
  const { profile: taxProfile } = useTaxProfile();
  const [notes, setNotes] = useState('');
  const [dueDate, setDueDate] = useState('');
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/rahaza/grs/available-for-invoice`, { headers });
      if (r.ok) {
        const data = await r.json();
        setGrs(data.items || []);
      }
    } catch (e) {
      toast.error('Gagal memuat penerimaan barang');
    } finally {
      setLoading(false);
    }
  }, [headers]);

  useEffect(() => {
    if (open) {
      load();
      setSelectedIds(new Set());
    }
  }, [open, load]);

  const toggle = (id) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  // Satu faktur hanya untuk satu supplier
  const groupedBySupplier = useMemo(() => {
    const map = {};
    grs.forEach(g => {
      const k = g.supplier_name || '(Tanpa supplier)';
      if (!map[k]) map[k] = [];
      map[k].push(g);
    });
    return map;
  }, [grs]);

  const selectedSupplier = useMemo(() => {
    const sel = grs.filter(g => selectedIds.has(g.id));
    if (sel.length === 0) return null;
    return sel[0].supplier_name;
  }, [grs, selectedIds]);

  const totalSelected = useMemo(() => {
    return grs.filter(g => selectedIds.has(g.id)).reduce((s, g) => s + (g.receivable_amount || 0), 0);
  }, [grs, selectedIds]);

  const handleCreate = async () => {
    if (selectedIds.size === 0) {
      toast.error('Pilih minimal 1 penerimaan barang');
      return;
    }
    setCreating(true);
    try {
      const r = await fetch(`${API}/api/rahaza/ap-invoices/from-gr`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          gr_ids: Array.from(selectedIds),
          tax_pct: parseFloat(taxPct) || 0,
          supplier_faktur_number: supplierFaktur || undefined,
          due_date: dueDate || undefined,
          notes: notes || undefined,
        }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || 'Gagal membuat faktur');
      toast.success(`Faktur supplier ${data.invoice_number} dibuat`);
      onSuccess?.(data);
      onClose();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setCreating(false);
    }
  };

  return (
    <FormPopup open={open} onClose={() => { if (!creating) onClose(); }} ukuran="panjang" testId="ap-from-gr-form"
      judul="Buat faktur supplier dari penerimaan barang"
      keterangan="Pilih penerimaan barang yang sudah diterima. Satu faktur hanya untuk penerimaan dari satu supplier."
      onSimpan={handleCreate} menyimpan={creating} bisaSimpan={selectedIds.size > 0}
      labelSimpan={`Buat faktur (${selectedIds.size} penerimaan)`}>
      {loading ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat penerimaan barang…</p>
      ) : Object.keys(groupedBySupplier).length === 0 ? (
        <EmptyState title="Tidak ada penerimaan yang siap ditagihkan"
          description="Penerimaan harus sudah berstatus diterima atau selesai dan belum dibuatkan faktur." />
      ) : (
        Object.entries(groupedBySupplier).map(([supplier, items]) => {
          const disabled = !!selectedSupplier && selectedSupplier !== supplier;
          return (
            <div key={supplier} className="space-y-1.5">
              <p className="text-sm font-medium text-foreground">
                {supplier}
                {disabled && <span className="ml-2 text-xs font-normal text-[hsl(var(--warning-text))]">tidak bisa dipilih — supplier berbeda</span>}
              </p>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-10"><span className="sr-only">Pilih</span></TableHead>
                      <TableHead>No. penerimaan</TableHead>
                      <TableHead>Tanggal</TableHead>
                      <TableHead className="text-right">Item</TableHead>
                      <TableHead className="text-right">Net (pcs)</TableHead>
                      <TableHead className="text-right">Nilai</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {items.map(g => {
                      const checked = selectedIds.has(g.id);
                      const off = disabled && !checked;
                      return (
                        <TableRow key={g.id} className={off ? 'opacity-50' : 'cursor-pointer'}
                          onClick={() => { if (!off) toggle(g.id); }}>
                          <TableCell onClick={(e) => e.stopPropagation()}>
                            <Checkbox checked={checked} disabled={off} onCheckedChange={() => toggle(g.id)}
                              aria-label={`Pilih ${g.receipt_number}`} data-testid={`gr-pick-${g.id}`} />
                          </TableCell>
                          <TableCell>
                            <span className="font-medium">{g.receipt_number}</span>
                            {g.po_number && <span className="ml-1 text-xs text-muted-foreground">dari {g.po_number}</span>}
                          </TableCell>
                          <TableCell className="whitespace-nowrap">{fmtDate(g.received_at)}</TableCell>
                          <TableCell className="text-right tabular-nums">{fmtNum(g.items_count)}</TableCell>
                          <TableCell className="text-right tabular-nums">{fmtNum(g.total_net)}</TableCell>
                          <TableCell className="text-right tabular-nums">{fmtRp(g.receivable_amount)}</TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            </div>
          );
        })
      )}

      <div className="grid gap-4 sm:grid-cols-3">
        <Isian label="PPN dari supplier (%)" htmlFor="ap-tax-pct"
          petunjuk={<span data-testid="ap-tax-note">{taxProfile.pkp ? 'PKP: PPN ini dikreditkan sebagai PPN Masukan — isi no. faktur supplier.' : 'Non-PKP: PPN dari supplier tidak dapat dikreditkan, dicatat sebagai bagian harga beli.'}</span>}>
          <Input id="ap-tax-pct" type="number" inputMode="decimal" value={taxPct} onChange={e => setTaxPct(e.target.value)}
            data-testid="ap-tax-pct" />
        </Isian>
        <Isian label="No. faktur supplier" htmlFor="ap-supplier-faktur" petunjuk="Opsional.">
          <Input id="ap-supplier-faktur" value={supplierFaktur} onChange={e => setSupplierFaktur(e.target.value)}
            data-testid="ap-supplier-faktur" />
        </Isian>
        <Isian label="Jatuh tempo">
          <DatePicker value={dueDate} onChange={setDueDate} placeholder="Pilih tanggal" testId="ap-due-date" />
        </Isian>
      </div>
      <Isian label="Catatan" htmlFor="ap-notes">
        <Textarea id="ap-notes" value={notes} onChange={e => setNotes(e.target.value)} rows={2}
          placeholder="Catatan opsional" data-testid="ap-notes" />
      </Isian>
      <p className="text-right text-sm text-muted-foreground">
        Total sebelum pajak: <span className="font-semibold tabular-nums text-foreground">{fmtRp(totalSelected)}</span>
      </p>
    </FormPopup>
  );
}

// ─── Detail satu PO (popup) ───────────────────────────────────────────────
const KOLOM_BARIS_UNDUH = [
  { label: 'Kode material', nilai: (l) => l.material_code || '' },
  { label: 'Material', nilai: (l) => l.material_name },
  { label: 'Satuan', nilai: (l) => l.unit },
  { label: 'Qty PO', nilai: (l) => Number(l.po_qty || 0) },
  { label: 'Nilai PO (Rp)', nilai: (l) => Number(l.po_subtotal || 0) },
  { label: 'Qty diterima bersih', nilai: (l) => Number(l.net_qty || 0) },
  { label: 'Nilai diterima (Rp)', nilai: (l) => Number(l.received_value || 0) },
  { label: 'Qty ditagih', nilai: (l) => Number(l.invoiced_qty || 0) },
  { label: 'Nilai ditagih (Rp)', nilai: (l) => Number(l.invoiced_amount || 0) },
  { label: 'Selisih (%)', nilai: (l) => Number(l.variance_pct || 0) },
  { label: 'Status', nilai: (l) => statusLabel(l.match_status) },
];

function PODetailPopup({ poId, headers, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let active = true;
    (async () => {
      setLoading(true);
      try {
        const r = await fetch(`${API}/api/rahaza/3way-match/${poId}`, { headers });
        if (r.ok && active) setData(await r.json());
        else if (active) toast.error('Gagal memuat detail');
      } catch (e) {
        if (active) toast.error('Gagal terhubung ke server');
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, [poId, headers]);

  const po = data?.po || {};
  const grs = data?.grs || [];
  const invoices = data?.invoices || [];
  const lines = data?.lines || [];

  return (
    <DetailPopup open onClose={onClose} testId="threeway-detail"
      judul={po.po_number ? `PO ${po.po_number}` : 'Detail rekonsiliasi'}
      keterangan={po.po_number ? `${po.vendor_name || '—'} · ${fmtDate(po.po_date)}` : undefined}
      aksi={lines.length > 0 && (
        <TombolUnduh namaBerkas={`rekonsiliasi-${po.po_number || 'po'}`} namaLembar="Per item" baris={lines}
          kolom={KOLOM_BARIS_UNDUH} testId="threeway-detail-unduh" />
      )}>
      {loading || !data ? (
        <p className="py-8 text-center text-sm text-muted-foreground">Memuat detail rekonsiliasi…</p>
      ) : (
        <>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Pemasok">{po.vendor_name || '—'}</BarisDetail>
            <BarisDetail label="Tanggal PO">{fmtDate(po.po_date)}</BarisDetail>
            <BarisDetail label={`Penerimaan barang (${grs.length})`}>
              {grs.length === 0 ? <span className="text-muted-foreground">Barang belum diterima.</span> : (
                <ul className="space-y-1">
                  {grs.map(gr => (
                    <li key={gr.id} className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{gr.receipt_number}</span>
                      <GrBadge status={gr.status} />
                      <span className="text-xs text-muted-foreground">{fmtDate(gr.created_at)} · {(gr.items || []).length} item</span>
                    </li>
                  ))}
                </ul>
              )}
            </BarisDetail>
            <BarisDetail label={`Faktur supplier (${invoices.length})`}>
              {invoices.length === 0 ? <span className="text-muted-foreground">Belum ditagih supplier.</span> : (
                <ul className="space-y-1">
                  {invoices.map(inv => (
                    <li key={inv.id} className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{inv.invoice_number}</span>
                      <InvBadge status={inv.status} />
                      <span className="text-xs text-muted-foreground">{fmtDate(inv.issue_date)}</span>
                      <span className="ml-auto tabular-nums">{fmtRp(inv.total)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </BarisDetail>
          </dl>

          <div>
            <p className="mb-2 text-sm font-semibold text-foreground">Rekonsiliasi per item ({lines.length})</p>
            {lines.length === 0 ? (
              <p className="text-sm text-muted-foreground">PO ini tidak punya baris item.</p>
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Material</TableHead>
                      <TableHead className="text-right">Qty PO</TableHead>
                      <TableHead className="text-right">Nilai PO</TableHead>
                      <TableHead className="text-right">Diterima bersih</TableHead>
                      <TableHead className="text-right">Nilai diterima</TableHead>
                      <TableHead className="text-right">Qty ditagih</TableHead>
                      <TableHead className="text-right">Nilai ditagih</TableHead>
                      <TableHead className="text-right">Selisih</TableHead>
                      <TableHead>Status</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {lines.map((l, idx) => (
                      <TableRow key={l.po_item_id || idx}>
                        <TableCell>
                          <div className="font-medium">{l.material_name}</div>
                          {l.material_code && <div className="text-xs text-muted-foreground">{l.material_code}</div>}
                        </TableCell>
                        <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtNum(l.po_qty)} {l.unit}</TableCell>
                        <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtRp(l.po_subtotal)}</TableCell>
                        <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtNum(l.net_qty)} {l.unit}</TableCell>
                        <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtRp(l.received_value)}</TableCell>
                        <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtNum(l.invoiced_qty)} {l.unit}</TableCell>
                        <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtRp(l.invoiced_amount)}</TableCell>
                        <TableCell className={`text-right tabular-nums whitespace-nowrap ${toneSelisih(l.variance_pct)}`}>
                          {fmtPct(l.variance_pct)}
                        </TableCell>
                        <TableCell><MatchBadge status={l.match_status} /></TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </div>
        </>
      )}
    </DetailPopup>
  );
}

// ─── Halaman ──────────────────────────────────────────────────────────────
const SARING = [
  { key: 'all', label: 'Semua' },
  { key: 'matched', label: 'Cocok' },
  { key: 'pending', label: 'Belum ada faktur' },
  { key: 'over', label: 'Lebih tagih' },
  { key: 'under', label: 'Kurang tagih' },
];

export default function ThreeWayMatchModule({ token, onNavigate }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [selectedPoId, setSelectedPoId] = useState(null);
  const [showCreateAP, setShowCreateAP] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const q = statusFilter === 'all' ? '' : `?status=${statusFilter}`;
      const r = await fetch(`${API}/api/rahaza/3way-match${q}`, { headers });
      if (!r.ok) {
        const e = await r.json().catch(() => ({}));
        toast.error(e.detail || 'Gagal memuat rekonsiliasi');
        return;
      }
      setData(await r.json());
    } catch (e) {
      toast.error('Gagal terhubung ke server: ' + e.message);
    } finally {
      setLoading(false);
    }
  }, [headers, statusFilter]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const filtered = useMemo(() => {
    if (!data) return [];
    let list = data.rows || [];
    if (search) {
      const q = search.toLowerCase();
      list = list.filter(r =>
        (r.po_number || '').toLowerCase().includes(q) ||
        (r.vendor_name || '').toLowerCase().includes(q)
      );
    }
    return list;
  }, [data, search]);

  const kpis = data?.kpis || {};
  const tol = data?.tolerance_pct ?? 0.5;
  const adaData = (kpis.total_pos || 0) > 0;
  const saringanAktif = statusFilter !== 'all';

  const kolom = [
    { kunci: 'po', label: 'No. PO', hp: 'judul', isi: (r) => (
      <span className="inline-flex flex-wrap items-center gap-1.5" data-testid={`3way-row-${r.po_id}`}>
        <span className="font-medium">{r.po_number}</span>
        {/* 2026-11-06 (Tahap 2): PO batal tetap tampil — barang/faktur atasnya tetap dicocokkan */}
        {r.po_status === 'cancelled' && (
          <StatusBadge status="cancelled" label="PO dibatalkan" tone="muted" testId={`3way-cancelled-${r.po_id}`} />
        )}
      </span>) },
    { kunci: 'vendor', label: 'Pemasok', hp: 'keterangan', isi: (r) => (
      <span className="block max-w-[14rem] truncate" title={r.vendor_name}>{r.vendor_name}</span>) },
    { kunci: 'tgl', label: 'Tanggal', isi: (r) => <span className="whitespace-nowrap">{fmtDate(r.po_date)}</span> },
    { kunci: 'pesan', label: 'Dipesan', rata: 'kanan', isi: (r) => <span className="tabular-nums whitespace-nowrap">{fmtRp(r.total_ordered_value)}</span> },
    { kunci: 'terima', label: 'Diterima', rata: 'kanan', isi: (r) => <span className="tabular-nums whitespace-nowrap">{fmtRp(r.total_received_value)}</span> },
    { kunci: 'tagih', label: 'Ditagih', rata: 'kanan', isi: (r) => <span className="tabular-nums whitespace-nowrap">{fmtRp(r.total_invoiced_value)}</span> },
    { kunci: 'selisih', label: 'Selisih', rata: 'kanan', isi: (r) => (
      <span className={`tabular-nums whitespace-nowrap ${toneSelisih(r.value_variance)}`}>
        {fmtRp(r.value_variance)} <span className="text-xs">({fmtPct(r.variance_pct)})</span>
      </span>) },
    { kunci: 'status', label: 'Status', isi: (r) => <MatchBadge status={r.match_status} /> },
  ];

  return (
    <PageLayout testId="threeway-module" title="Rekonsiliasi PO"
      subtitle="Cocokkan PO, penerimaan barang, dan faktur supplier dalam satuan dasar sebelum pembayaran disetujui."
      actions={
        // 2026-11-06 (Tahap 2): faktur dibuat di Faktur Supplier — satu-satunya layar yang mencatat
        // qty & harga faktur pemasok yang sebenarnya, ongkir, dan potongan. Form lama hanya cadangan.
        <Button onClick={() => (onNavigate ? onNavigate('proc-ap-invoices') : setShowCreateAP(true))}
          data-testid="create-ap-from-gr-btn">
          <Plus />Buat faktur supplier
        </Button>
      }
      filters={<>
        <FilterChips options={SARING} value={statusFilter} onChange={setStatusFilter} hideWhenEmpty={false}
          testId="3way-tab" ariaLabel="Saring status pencocokan" />
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder="Cari nomor PO atau pemasok" value={search} onChange={e => setSearch(e.target.value)}
            className="pl-8" data-testid="3way-search" />
        </div>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="rekonsiliasi-po" namaLembar="Rekonsiliasi PO" baris={filtered} testId="threeway-unduh"
          kolom={[
            { label: 'No. PO', nilai: (r) => r.po_number },
            { label: 'Status PO', nilai: (r) => (r.po_status === 'cancelled' ? 'Dibatalkan' : '') },
            { label: 'Pemasok', nilai: (r) => r.vendor_name },
            { label: 'Tanggal', nilai: (r) => fmtDate(r.po_date) },
            { label: 'Dipesan (Rp)', nilai: (r) => Number(r.total_ordered_value || 0) },
            { label: 'Diterima (Rp)', nilai: (r) => Number(r.total_received_value || 0) },
            { label: 'Ditagih (Rp)', nilai: (r) => Number(r.total_invoiced_value || 0) },
            { label: 'Dibayar (Rp)', nilai: (r) => Number(r.total_paid || 0) },
            { label: 'Selisih (Rp)', nilai: (r) => Number(r.value_variance || 0) },
            { label: 'Selisih (%)', nilai: (r) => Number(r.variance_pct || 0) },
            { label: 'Status', nilai: (r) => statusLabel(r.match_status) },
          ]} />
        <Button variant="outline" size="icon" onClick={fetchData} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="threeway-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={adaData && (
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatTile label="PO dalam daftar" value={fmtNum(kpis.total_pos)}
              hint="PO disetujui, diterima, atau dibatalkan — paling banyak 100 PO terbaru, sesuai saringan status." />
            <StatTile label="Cocok" value={fmtNum(kpis.matched)} accent="success"
              hint={`Selisih nilai tagihan dan barang diterima paling banyak ${String(tol).replace('.', ',')}%.`} />
            <StatTile label="Belum ada faktur" value={fmtNum(kpis.pending)}
              hint="PO yang belum punya faktur supplier." />
            <StatTile label="Ada selisih" value={fmtNum(kpis.variance)} accent="warning"
              sub={`${fmtNum(kpis.over)} lebih tagih · ${fmtNum(kpis.under)} kurang tagih`}
              hint="Faktur menagih lebih atau kurang dari nilai barang yang diterima." />
          </div>
          <p className="text-sm text-muted-foreground" data-testid="threeway-nilai">
            {saringanAktif ? 'Nilai PO pada saringan ini: ' : 'Nilai semua PO di daftar: '}
            dipesan <span className="font-medium text-foreground tabular-nums">{fmtRp(kpis.total_ordered_value)}</span>
            {' · '}diterima <span className="font-medium text-foreground tabular-nums">{fmtRp(kpis.total_received_value)}</span>
            {' · '}ditagih <span className="font-medium text-foreground tabular-nums">{fmtRp(kpis.total_invoiced_value)}</span>
            {' · '}dibayar <span className="font-medium text-foreground tabular-nums">{fmtRp(kpis.total_paid)}</span>
          </p>
        </div>
      )}>
      {loading && !data ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat rekonsiliasi…</p>
      ) : (
        <TabelData kolom={kolom} baris={filtered} kunci={(r) => r.po_id} onKlikBaris={(r) => setSelectedPoId(r.po_id)}
          testId="3way-table"
          kosong={<EmptyState
            title={adaData || saringanAktif || search ? 'Tidak ada PO yang cocok dengan saringan' : 'Belum ada PO untuk dicocokkan'}
            description={adaData || saringanAktif || search
              ? 'Ubah saringan status atau kata pencarian.'
              : 'PO muncul di sini setelah disetujui. Barang yang diterima dan faktur supplier akan dicocokkan otomatis.'} />} />
      )}

      {selectedPoId && (
        <PODetailPopup poId={selectedPoId} headers={headers} onClose={() => setSelectedPoId(null)} />
      )}

      <CreateAPFromGRDialog
        open={showCreateAP}
        onClose={() => setShowCreateAP(false)}
        headers={headers}
        onSuccess={() => fetchData()}
      />
    </PageLayout>
  );
}

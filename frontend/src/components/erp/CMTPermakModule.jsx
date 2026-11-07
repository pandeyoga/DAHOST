/**
 * CMTPermakModule — "Perbaikan" (permak barang cacat), satu layar untuk Portal Produksi & Maklon.
 *
 * Barang cacat dari QC (cmt_receipt_lines.reject_qty) atau barang jadi yang perlu diperbaiki dikirim ke
 * PERMAK. Permak terbuka/dikerjakan MENGURANGI barang jadi. Hasil: berhasil (qty_fixed + qty_scrap) atau
 * gagal dibuang (semua scrap).
 *
 * Tahap 9 (7 Nov 2026):
 *   • Keputusan 2 — tampilan identik di dua portal; daftar, ringkasan, dan pilihan PO disaring per
 *     portal (`?business_type=`).
 *   • Keputusan 12 — menu Perbaikan tinggal berisi Permak (Komponen Kurang pindah ke Kirim ke CMT).
 *   • Cetakan PageLayout: tabel + rincian di bawah barisnya; formulir "Buat permak" dibuka di halaman
 *     (DetailPanel); popup hanya untuk ubah status (isian pendek) dan konfirmasi hapus.
 *
 * API: /api/dewi/cmt-permak/* (routes/dewi_cmt_permak.py)
 */
import { Fragment, useEffect, useMemo, useState, useCallback } from 'react';
import {
  Wrench, RefreshCw, Search, Plus, Play, CheckCircle2, XCircle, Trash2, Loader2, AlertTriangle, MoreHorizontal,
} from 'lucide-react';
import { toast } from 'sonner';
import { apiGet, apiPost, apiDelete } from '../../lib/api';
import { MoneyInput } from '@/components/ui/money-input';
import { Button } from '@/components/ui/button';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Textarea } from '@/components/ui/textarea';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PageLayout, { DetailPanel, RowDetail, RowToggle } from './layout/PageLayout';
import { PageLayoutSatuBaris } from './engine/DataTable';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';
import { Field } from './engine/FormDialog';
import FormPopup from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Input } from '@/components/ui/input';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { portalBusinessType, portalQuery } from '@/lib/portalScope';
import DocNumberField, { useDocNumberPolicy, docNumberPayload } from './docnum/DocNumberField';
import { formatDateID } from '@/lib/format';

const STATUS_META = {
  open: { label: 'Menunggu', tone: 'muted' },
  in_progress: { label: 'Dikerjakan', tone: 'primary' },
  selesai_berhasil: { label: 'Selesai (berhasil)', tone: 'success' },
  gagal_buang: { label: 'Gagal (dibuang)', tone: 'muted' },
};
const TYPE_LABEL = { permak_sendiri: 'Permak sendiri', retur_ke_cmt: 'Retur ke CMT' };
const SOURCE_LABEL = { reject: 'Dari ditolak QC', good: 'Dari barang jadi' };
const PROBLEM_OPTS = [
  ['jahitan', 'Jahitan'], ['noda', 'Noda'], ['ukuran', 'Ukuran'], ['bahan', 'Bahan'],
  ['aksesoris', 'Aksesoris'], ['lainnya', 'Lainnya'],
];
// Tahap 6 (PR1) — penanda tetap workshop sendiri; sama dengan WORKSHOP_DA_ID di routes/dewi_cmt_permak.py
const WORKSHOP_DA_ID = 'workshop_da';
const fmt = (n) => Number(n || 0).toLocaleString('id-ID');
const fmtRp = (n) => `Rp ${Number(n || 0).toLocaleString('id-ID')}`;
const fmtDate = (iso) => (iso ? formatDateID(iso) : '—');

export default function CMTPermakModule({ portalId }) {
  const businessType = portalBusinessType(portalId);
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState('all');
  const [search, setSearch] = useState('');
  const [openRow, setOpenRow] = useState(null);
  const [creating, setCreating] = useState(false);
  const [statusTarget, setStatusTarget] = useState(null);   // { record, action }

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [list, sum] = await Promise.all([
        apiGet(`/dewi/cmt-permak${portalQuery(businessType, { limit: 300, status: tab !== 'all' ? tab : '' })}`),
        apiGet(`/dewi/cmt-permak/summary${portalQuery(businessType)}`),
      ]);
      setRows(Array.isArray(list.items) ? list.items : []);
      setSummary(sum);
    } catch (e) {
      toast.error(`Gagal memuat permak: ${e.message || e}`);
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [tab, businessType]);
  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) => [r.permak_number, r.sku, r.product_name, r.po_number, r.vendor_name]
      .some((v) => String(v || '').toLowerCase().includes(q)));
  }, [rows, search]);
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(filtered, 25);

  const doDelete = async (rec) => {
    if (!(await confirmDialog({ title: `Hapus ${rec.permak_number}?`, body: 'Hanya permak berstatus Menunggu yang bisa dihapus.',
      confirmLabel: 'Hapus permak', danger: true }))) return;
    try {
      await apiDelete(`/dewi/cmt-permak/${rec.id}`);
      toast.success('Permak dihapus');
      load();
    } catch (e) {
      toast.error(`Gagal hapus: ${e.message || e}`);
    }
  };

  const s = summary || {};
  const anyKpi = Number(s.total_records || 0) > 0;
  const tabs = [
    { key: 'all', label: 'Semua', count: s.total_records },
    { key: 'open', label: 'Menunggu', count: s.open },
    { key: 'in_progress', label: 'Dikerjakan', count: s.in_progress },
    { key: 'selesai_berhasil', label: 'Selesai', count: s.selesai_berhasil },
    { key: 'gagal_buang', label: 'Dibuang', count: s.gagal_buang },
  ];

  return (
    <PageLayoutSatuBaris
      testId="cmt-permak-module"
      title="Perbaikan (permak)"
      subtitle="Perbaikan barang cacat dari CMT. Permak yang belum selesai mengurangi stok barang jadi."
      actions={<Button onClick={() => setCreating(true)} data-testid="btn-open-create-permak"><Plus className="w-4 h-4" />Buat permak</Button>}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari permak, SKU, produk, PO"
            data-testid="input-search-permak" className="pl-8" />
        </div>
        <FilterChips value={tab} onChange={setTab} testId="tab-permak" ariaLabel="Penyaring status permak"
          hideWhenEmpty={false} options={tabs.map((t) => ({ ...t, count: summary ? Number(t.count || 0) : undefined }))} />
      </>}
      tools={<>
        <TombolUnduh namaBerkas="perbaikan-permak" namaLembar="Permak" baris={filtered} testId="permak-unduh" kolom={[
          { label: 'No. permak', nilai: (r) => r.permak_number || '' }, { label: 'Produk', nilai: (r) => r.product_name || '' },
          { label: 'SKU', nilai: (r) => r.sku || '' }, { label: 'PO', nilai: (r) => r.po_number || '' },
          { label: 'Jenis', nilai: (r) => (r.permak_type === 'retur_ke_cmt' ? 'Retur ke CMT' : 'Permak sendiri') },
          { label: 'Qty', nilai: (r) => Number(r.qty) || 0 }, { label: 'Diperbaiki', nilai: (r) => Number(r.qty_fixed) || 0 },
          { label: 'Dibuang', nilai: (r) => Number(r.qty_scrap) || 0 }, { label: 'Biaya (Rp)', nilai: (r) => Number(r.total_cost) || 0 },
          { label: 'Status', nilai: (r) => r.status || '' }, { label: 'Dibuat', nilai: (r) => formatDateID(r.created_at, { fallback: '' }) },
        ]} />
        <Button variant="outline" size="icon" onClick={load} title="Muat ulang" aria-label="Muat ulang" data-testid="btn-refresh-permak">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </>}
      summary={anyKpi ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <StatTile testId="permak-kpi-open" label="Menunggu" value={fmt(s.open)} accent="warning" sub={`${fmt(s.qty_open)} pcs`} />
          <StatTile testId="permak-kpi-progress" label="Dikerjakan" value={fmt(s.in_progress)} accent="primary"
            sub={`${fmt(s.qty_in_progress)} pcs${s.h3_alert ? ` · ${fmt(s.h3_alert)} lewat batas waktu` : ''}`}
            subTone={s.h3_alert ? 'danger' : undefined} />
          <StatTile testId="permak-kpi-done" label="Selesai" value={fmt(Number(s.selesai_berhasil || 0) + Number(s.gagal_buang || 0))} accent="success"
            sub={`${fmt(s.qty_fixed)} pcs diperbaiki · ${fmt(s.qty_scrap)} pcs dibuang`} />
          <StatTile testId="permak-kpi-cost" label="Biaya permak" value={fmtRp(s.total_cost)}
            sub={`sendiri ${fmt(s.permak_sendiri)} · retur ${fmt(s.retur_ke_cmt)} · ${fmt(s.distinct_pos)} PO`} />
        </div>
      ) : null}
      detail={creating && (
        <CreatePermakPanel businessType={businessType} onClose={() => setCreating(false)}
          onCreated={() => { setCreating(false); load(); }} />
      )}
      footer={filtered.length > pageSize && (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />
      )}
    >
      <GlassCard className="p-0 overflow-x-auto">
        {loading && !rows.length ? (
          <div className="p-4 text-sm text-muted-foreground"><Loader2 className="w-4 h-4 animate-spin inline mr-2" />Memuat…</div>
        ) : filtered.length === 0 ? (
          <EmptyState icon={Wrench} title="Belum ada permak"
            description="Buat permak baru, atau kirim barang ditolak dari layar Terima & QC." />
        ) : (
          <Table>
            <TableHeader><TableRow>
              <TableHead className="w-10" />
              <TableHead>No. permak</TableHead><TableHead>Produk / SKU</TableHead><TableHead>PO</TableHead>
              <TableHead>Jenis</TableHead><TableHead className="text-right">Qty</TableHead>
              <TableHead className="text-right">Diperbaiki / dibuang</TableHead><TableHead className="text-right">Biaya</TableHead>
              <TableHead>Status</TableHead><TableHead className="text-right">Aksi</TableHead>
            </TableRow></TableHeader>
            <TableBody data-testid="permak-table-body">
              {paged.map((r) => {
                const terminal = r.status === 'selesai_berhasil' || r.status === 'gagal_buang';
                const meta = STATUS_META[r.status] || { label: r.status, tone: 'muted' };
                const open = openRow === r.id;
                return (
                  <Fragment key={r.id}>
                    <TableRow data-testid={`permak-row-${r.id}`}>
                      <TableCell><RowToggle open={open} onClick={() => setOpenRow(open ? null : r.id)} testId={`permak-expand-${r.id}`} /></TableCell>
                      <TableCell className="whitespace-nowrap font-medium">{r.permak_number}</TableCell>
                      <TableCell>
                        {r.product_name || r.sku || '—'}
                        <span className="block text-xs text-muted-foreground">{[r.sku, r.color, r.size].filter(Boolean).join(' · ')}</span>
                      </TableCell>
                      <TableCell className="whitespace-nowrap">{r.po_number || '—'}</TableCell>
                      <TableCell>
                        {TYPE_LABEL[r.permak_type] || SOURCE_LABEL[r.source] || '—'}
                        {r.h3_flag && (
                          <span className="block text-xs text-[hsl(var(--danger-text))]" title={`Lewat batas waktu ${Math.abs(r.days_to_deadline || 0)} hari`}>
                            <AlertTriangle className="w-3 h-3 inline mr-0.5" />Perlu tindakan
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{fmt(r.qty)}</TableCell>
                      <TableCell className="text-right tabular-nums">{terminal ? `${fmt(r.qty_fixed)} / ${fmt(r.qty_scrap)}` : '—'}</TableCell>
                      <TableCell className="text-right tabular-nums whitespace-nowrap">{r.total_cost ? fmtRp(r.total_cost) : '—'}</TableCell>
                      <TableCell><StatusBadge status={r.status} label={meta.label} tone={meta.tone} /></TableCell>
                      <TableCell className="text-right">
                        {/* Standar UI/UX v2: aksi utama tampil (Mulai / Selesai); Gagal-buang & Hapus di menu Lainnya. */}
                        <div className="flex items-center justify-end gap-1">
                          {r.status === 'open' && (
                            <Button variant="ghost" size="icon-sm" onClick={() => setStatusTarget({ record: r, action: 'in_progress' })}
                              data-testid={`btn-start-${r.id}`} title="Mulai kerjakan" aria-label="Mulai kerjakan"><Play className="w-4 h-4" /></Button>
                          )}
                          {!terminal && (
                            <Button variant="ghost" size="icon-sm" onClick={() => setStatusTarget({ record: r, action: 'selesai_berhasil' })}
                              data-testid={`btn-complete-${r.id}`} title="Selesai (berhasil)" aria-label="Selesai (berhasil)"><CheckCircle2 className="w-4 h-4" /></Button>
                          )}
                          {!terminal && (
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <Button variant="ghost" size="icon-sm" title="Aksi lainnya" aria-label="Aksi lainnya"><MoreHorizontal className="w-4 h-4" /></Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end">
                                <DropdownMenuItem onSelect={() => setStatusTarget({ record: r, action: 'gagal_buang' })} data-testid={`btn-scrap-${r.id}`}>
                                  <XCircle className="mr-2 h-4 w-4" />Gagal / buang</DropdownMenuItem>
                                {r.status === 'open' && (
                                  <DropdownMenuItem onSelect={() => doDelete(r)} data-testid={`btn-delete-${r.id}`}
                                    className="text-[hsl(var(--danger-text))] focus:text-[hsl(var(--danger-text))]"><Trash2 className="mr-2 h-4 w-4" />Hapus</DropdownMenuItem>
                                )}
                              </DropdownMenuContent>
                            </DropdownMenu>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                    {open && (
                      <RowDetail colSpan={10} testId={`permak-detail-${r.id}`}>
                        <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
                          <div><dt className="text-xs text-muted-foreground">Vendor CMT</dt><dd>{r.vendor_name || '—'}</dd></div>
                          <div><dt className="text-xs text-muted-foreground">Dikerjakan oleh</dt>
                            <dd data-testid={`permak-workshop-${r.id}`}>{r.vendor_permak_name || r.vendor_permak || '—'}</dd></div>
                          <div><dt className="text-xs text-muted-foreground">Surat jalan perbaikan</dt>
                            <dd>{r.rework_shipment_number || (r.permak_type === 'retur_ke_cmt'
                              ? <span className="text-[hsl(var(--danger-text))]">Belum terbentuk</span> : '—')}</dd></div>
                          <div><dt className="text-xs text-muted-foreground">Asal barang</dt><dd>{SOURCE_LABEL[r.source] || '—'}</dd></div>
                          <div><dt className="text-xs text-muted-foreground">Target kembali</dt><dd>{fmtDate(r.return_deadline)}</dd></div>
                          <div><dt className="text-xs text-muted-foreground">Ongkos per pcs</dt><dd className="tabular-nums">{r.cost_per_pcs ? fmtRp(r.cost_per_pcs) : '—'}</dd></div>
                          <div><dt className="text-xs text-muted-foreground">Dibuat</dt><dd>{fmtDate(r.created_at)}</dd></div>
                          <div className="sm:col-span-2 lg:col-span-1"><dt className="text-xs text-muted-foreground">Alasan</dt><dd>{r.reason || r.problem_type || '—'}</dd></div>
                        </dl>
                      </RowDetail>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        )}
      </GlassCard>

      {statusTarget && (
        <StatusDialog target={statusTarget} onClose={() => setStatusTarget(null)}
          onDone={() => { setStatusTarget(null); load(); }} />
      )}
    </PageLayoutSatuBaris>
  );
}

/* ─── Formulir "Buat permak" — di halaman (DetailPanel) ─────────────────── */
function CreatePermakPanel({ businessType, onClose, onCreated }) {
  const [pos, setPos] = useState([]);
  const [poId, setPoId] = useState('');
  const [items, setItems] = useState([]);
  const [itemId, setItemId] = useState('');
  const [qty, setQty] = useState('');
  const [source, setSource] = useState('good');
  const [permakType, setPermakType] = useState('permak_sendiri');
  const [problemType, setProblemType] = useState('jahitan');
  const [costPerPcs, setCostPerPcs] = useState('');
  const [returnDeadline, setReturnDeadline] = useState('');
  // Tahap 6 (PR1): vendor/workshop permak DARI MASTER Vendor CMT + pilihan tetap "Workshop DA sendiri".
  const [workshopId, setWorkshopId] = useState(WORKSHOP_DA_ID);
  const [vendors, setVendors] = useState([]);
  const [reason, setReason] = useState('');
  const [loadingItems, setLoadingItems] = useState(false);
  const [saving, setSaving] = useState(false);
  // SESI #27 — kebijakan penomoran Permak (Otomatis/Manual) milik owner.
  const numPolicy = useDocNumberPolicy('dewi_cmt_permak.permak_number', localStorage.getItem('erp_token'));
  const [permakNumber, setPermakNumber] = useState('');

  useEffect(() => {
    (async () => {
      try {
        // Tahap 9 (keputusan 2): pilihan PO hanya PO portal ini.
        const data = await apiGet(`/dewi/cmt-permak/po-options${portalQuery(businessType)}`);
        setPos(Array.isArray(data) ? data : []);
      } catch (e) { toast.error(`Gagal memuat PO: ${e.message || e}`); }
    })();
    (async () => {
      try {
        const data = await apiGet('/garments');
        setVendors((Array.isArray(data) ? data : []).filter((v) => v.status !== 'inactive'));
      } catch { setVendors([]); }
    })();
  }, [businessType]);

  const changePermakType = (t) => {
    setPermakType(t);
    setWorkshopId((w) => (t === 'retur_ke_cmt' && w === WORKSHOP_DA_ID ? '' : t === 'permak_sendiri' && !w ? WORKSHOP_DA_ID : w));
  };

  useEffect(() => {
    setItemId('');
    if (!poId) { setItems([]); return; }
    (async () => {
      setLoadingItems(true);
      try {
        const prog = await apiGet(`/dewi/cmt-permak/po-options/${poId}/items`);
        setItems(Array.isArray(prog.items) ? prog.items : []);
      } catch (e) {
        toast.error(`Gagal memuat item PO: ${e.message || e}`);
        setItems([]);
      } finally { setLoadingItems(false); }
    })();
  }, [poId]);

  const selectedItem = items.find((i) => i.po_item_id === itemId);

  const submit = async () => {
    if (!poId || !itemId) { toast.error('Pilih PO & item terlebih dahulu'); return; }
    const n = Number(qty);
    if (!n || n <= 0) { toast.error('Qty harus lebih dari 0'); return; }
    setSaving(true);
    try {
      await apiPost('/dewi/cmt-permak', {
        po_id: poId, po_item_id: itemId, qty: n, source,
        permak_type: permakType, problem_type: problemType,
        cost_per_pcs: Number(costPerPcs || 0), return_deadline: returnDeadline || null,
        vendor_permak_id: workshopId, reason,
        ...docNumberPayload(numPolicy, 'permak_number', permakNumber),
      });
      toast.success('Permak dibuat');
      onCreated();
    } catch (e) {
      toast.error(`Gagal membuat permak: ${e.message || e}`);
    } finally { setSaving(false); }
  };

  return (
    // Standar UI/UX v2 (8 Nov 2026): form = FormPopup panjang (dulu panel di atas tabel, label pilihan terpotong).
    <FormPopup open onClose={onClose} ukuran="panjang" testId="create-permak-dialog" judul="Buat permak"
      keterangan="Barang yang dipermak mengurangi stok barang jadi sampai permaknya selesai."
      onSimpan={submit} menyimpan={saving} labelSimpan="Simpan">
      <div className="grid gap-4 md:grid-cols-2">
        <Field label="PO *">
          <SmartNativeSelect value={poId} onChange={(e) => setPoId(e.target.value)} className="w-full h-9" data-testid="select-permak-po" aria-label="PO">
            <option value="">— Pilih PO —</option>
            {pos.map((p) => (
              <option key={p.po_id} value={p.po_id}>
                {[p.po_number, p.customer_name, p.status].filter(Boolean).join(' · ')}
              </option>
            ))}
          </SmartNativeSelect>
        </Field>
        <Field label="Item / SKU *">
          <SmartNativeSelect value={itemId} onChange={(e) => setItemId(e.target.value)} disabled={!poId || loadingItems}
            className="w-full h-9" data-testid="select-permak-item" aria-label="Item / SKU">
            <option value="">{loadingItems ? 'Memuat item…' : '— Pilih item —'}</option>
            {items.map((i) => (
              <option key={i.po_item_id} value={i.po_item_id}>
                {`${i.product_name || i.sku} · ${i.color || '-'} · ${i.size || '-'} · ${i.sku || '-'} — bagus ${fmt(i.qty_good)} / ditolak ${fmt(i.qty_reject_qc)}`}
              </option>
            ))}
          </SmartNativeSelect>
        </Field>
      </div>
      {selectedItem && (
        <p className="text-sm text-muted-foreground" data-testid="permak-item-position">
          Barang jadi <b className="text-foreground tabular-nums">{fmt(selectedItem.qty_good)}</b> · ditolak QC{' '}
          <b className="text-foreground tabular-nums">{fmt(selectedItem.qty_reject_qc)}</b> · sedang dipermak{' '}
          <b className="text-foreground tabular-nums">{fmt(selectedItem.qty_rework_open)}</b>
        </p>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Asal barang">
          <SmartNativeSelect value={source} onChange={(e) => setSource(e.target.value)} className="w-full h-9" data-testid="select-permak-source" aria-label="Asal barang">
            <option value="good">Dari barang jadi (mengurangi stok)</option>
            <option value="reject">Dari ditolak QC</option>
          </SmartNativeSelect>
        </Field>
        <Field label="Qty *">
          <GlassInput type="number" min="1" value={qty} onChange={(e) => setQty(e.target.value)} className="h-9" data-testid="input-permak-qty" />
        </Field>
        <Field label="Jenis permak">
          <SmartNativeSelect value={permakType} onChange={(e) => changePermakType(e.target.value)} className="w-full h-9" data-testid="select-permak-type" aria-label="Jenis permak">
            <option value="permak_sendiri">Permak sendiri (workshop DA)</option>
            <option value="retur_ke_cmt">Retur ke CMT (dikembalikan)</option>
          </SmartNativeSelect>
        </Field>
        <Field label="Jenis masalah">
          <SmartNativeSelect value={problemType} onChange={(e) => setProblemType(e.target.value)} className="w-full h-9" data-testid="select-permak-problem" aria-label="Jenis masalah">
            {PROBLEM_OPTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </SmartNativeSelect>
        </Field>
        <Field label="Ongkos permak per pcs (Rp)"
          hint={Number(costPerPcs) > 0 && Number(qty) > 0 ? `Total ${fmtRp(Number(costPerPcs) * Number(qty))}` : undefined}>
          <MoneyInput glass value={costPerPcs} onChange={(e) => setCostPerPcs(e.target.value)} placeholder="0" className="h-9" data-testid="input-permak-cost" />
        </Field>
        <Field label="Target kembali">
          <DatePicker value={returnDeadline} onChange={setReturnDeadline} placeholder="Belum diisi" testId="input-permak-deadline" />
        </Field>
        <Field label="Vendor / workshop permak" className="sm:col-span-2"
          hint="Dari master Vendor CMT. Vendor baru ditambahkan di menu Vendor CMT.">
          <SmartNativeSelect value={workshopId} onChange={(e) => setWorkshopId(e.target.value)} className="w-full h-9"
            aria-label="Vendor / workshop permak" data-testid="select-permak-workshop">
            <option value="">— Belum ditentukan —</option>
            <option value={WORKSHOP_DA_ID}>Workshop DA sendiri</option>
            {vendors.map((v) => (
              <option key={v.id} value={v.id}>{`${v.garment_code ? `${v.garment_code} · ` : ''}${v.garment_name || v.name}`}</option>
            ))}
          </SmartNativeSelect>
        </Field>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <DocNumberField policy={numPolicy} value={permakNumber} onChange={setPermakNumber} testId="permak-docnum" label="Nomor permak" />
        <Field label="Alasan / catatan">
          <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Contoh: jahitan lepas, noda, salah ukuran…"
            data-testid="input-permak-reason" />
        </Field>
      </div>
      {numPolicy?.mode === 'manual' && (
        <Notice tone="warning" icon={AlertTriangle} testId="permak-docnum-warn">
          Bila qty harus dipecah ke beberapa baris ditolak, satu pengajuan bisa menghasilkan lebih dari satu dokumen permak —
          nomor ketikan hanya bisa dipakai untuk pengajuan yang menghasilkan satu dokumen.
        </Notice>
      )}
    </FormPopup>
  );
}

/* ─── Ubah status (isian pendek) ─────────────────────────────────────────── */
function StatusDialog({ target, onClose, onDone }) {
  const { record, action } = target;
  const qty = Number(record.qty || 0);
  const [qtyFixed, setQtyFixed] = useState(qty);
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);
  const qtyScrap = Math.max(0, qty - Number(qtyFixed || 0));
  const titles = {
    in_progress: 'Mulai kerjakan permak',
    selesai_berhasil: 'Selesaikan permak (berhasil)',
    gagal_buang: 'Tandai gagal / buang',
  };

  const submit = async () => {
    setSaving(true);
    try {
      const body = { status: action, note };
      if (action === 'selesai_berhasil') {
        const qf = Number(qtyFixed || 0);
        if (qf < 0 || qf > qty) { setSaving(false); toast.error(`Qty diperbaiki harus 0–${qty}`); return; }
        body.qty_fixed = qf;
        body.qty_scrap = qty - qf;
      }
      await apiPost(`/dewi/cmt-permak/${record.id}/status`, body);
      toast.success('Status permak diperbarui');
      onDone();
    } catch (e) {
      toast.error(`Gagal ubah status: ${e.message || e}`);
    } finally { setSaving(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="permak-status-dialog" judul={titles[action] || 'Ubah status'}
      keterangan={`${record.permak_number} — ${record.product_name || record.sku} (${fmt(qty)} pcs)`}
      onSimpan={submit} menyimpan={saving} labelSimpan="Konfirmasi">
      {action === 'selesai_berhasil' && (
        <Field label="Qty berhasil diperbaiki"
          hint={`Diperbaiki ${fmt(qtyFixed)} + dibuang ${fmt(qtyScrap)} = ${fmt(qty)}. Yang diperbaiki menambah stok barang jadi.`}>
          <GlassInput type="number" min="0" max={qty} value={qtyFixed} onChange={(e) => setQtyFixed(e.target.value)}
            className="h-9" data-testid="input-status-qty-fixed" />
        </Field>
      )}
      {action === 'gagal_buang' && (
        <Notice tone="warning" icon={AlertTriangle}>Seluruh {fmt(qty)} pcs ditandai dibuang (permanen).</Notice>
      )}
      <Field label="Catatan (opsional)">
        <GlassInput value={note} onChange={(e) => setNote(e.target.value)} className="h-9" data-testid="input-status-note" />
      </Field>
    </FormPopup>
  );
}

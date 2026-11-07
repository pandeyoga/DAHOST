/**
 * DAReceiveFromCMTModule — "Terima & QC" (dulu "Terima FG dari CMT").
 * ─────────────────────────────────────────────────────────────────────────────
 * Alur (FASE 1+4, audit 2026-07-31): penerimaan muncul otomatis dari deklarasi kirim vendor →
 * hitung fisik per baris (lolos / ditolak) → Selesaikan QC (stok barang jadi naik, ditolak masuk
 * karantina, tagihan CMT matang). Dua status saja: Sedang QC → Selesai QC.
 *
 * Tahap 9 (7 Nov 2026):
 *   • Keputusan 2 — tampilan IDENTIK di Portal Produksi & Maklon, data disaring per portal
 *     (`?business_type=` di daftar penerimaan, ringkasan, antrean ditolak, selisih kirim).
 *   • Cetakan PageLayout: tabel + rincian baris di bawah barisnya (RowDetail); antrean ditolak dan
 *     barang belum sampai jadi penyaring tampilan (bukan kartu bertumpuk); popup hanya formulir pendek.
 *   • Keputusan 11 — alat "Hitung sampel AQL" (dulu menu Analitik Produksi) ada di layar ini, dan bisa
 *     dibuka per penerimaan dengan jumlah barang terisi otomatis.
 *
 * SSOT backend: `/api/prod/cmt-receipts*`, `/api/prod/cmt-reject-queue`, `/api/prod/short-shipments`
 *   (routes/dewi_cmt_packing.py, core/production_qty_ledger.py), permak/retur dari baris penerimaan
 *   `/api/dewi/cmt-permak/from-receipt-line`.
 */
import { Fragment, useEffect, useMemo, useState, useCallback } from 'react';
import {
  ClipboardCheck, RefreshCw, Search, CheckCircle2, Info, Loader2, Wrench, Undo2, Ban,
  Pencil, FileWarning, FileText, Calculator, PackageSearch, Package,
} from 'lucide-react';
import { toast } from 'sonner';
import StaffEntryBadge from './StaffEntryBadge';
import AqlSamplingTool from './AqlSamplingTool';
import FormDialog, { Field } from './FormDialog';
import { PdfColumnPicker } from '../pdf/PdfColumnPicker';
import { apiGet, apiPost, apiPut, apiFetch } from '../../../lib/api';
import { postWithOverQtyReason } from '../../../lib/overQty';
import { MoneyInput } from '../../ui/money-input';
import { Button } from '@/components/ui/button';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Textarea } from '@/components/ui/textarea';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PageLayout, { DetailPanel, RowDetail, RowToggle } from '../layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';
import { formatDateID } from '@/lib/format';
import { portalBusinessType, portalQuery } from '@/lib/portalScope';

// W5 — kolom yang tercentang saat dialog pertama kali dibuka: VERSI KIRIM MURNI.
const SJ_DEFAULT_COLS = ['no', 'serial', 'sku', 'product', 'size', 'color', 'qty_sent'];

// Penyelesaian selisih kirim (SSOT: core/short_shipment.CMT_RESOLUTIONS)
const SHORT_RESOLUTIONS = [
  { id: 'dikirim_ulang', label: 'Barang ditemukan & sudah dikirim ulang' },
  { id: 'hilang_tanggungan_vendor', label: 'Dinyatakan hilang — ditanggung vendor CMT' },
  { id: 'hilang_tanggungan_da', label: 'Dinyatakan hilang — ditanggung DA' },
  { id: 'salah_input_dikoreksi', label: 'Ternyata salah input — batalkan selisih' },
];
const STATUS_TONE = { on_qc: 'warning', completed_qc: 'success', cancelled: 'muted' };
const STATUS_LABEL = { on_qc: 'Sedang QC', completed_qc: 'Selesai QC', cancelled: 'Dibatalkan' };

const fmtNum = (n) => Number(n || 0).toLocaleString('id-ID');
const fmtDate = (iso) => (iso ? formatDateID(iso) : '—');
const pct = (v) => String(v ?? 0).replace('.', ',');

export default function DAReceiveFromCMTModule({ portalId }) {
  const businessType = portalBusinessType(portalId);
  const [receipts, setReceipts] = useState([]);
  const [rejectQueue, setRejectQueue] = useState({ items: [], total_qty_undecided: 0 });
  const [summary, setSummary] = useState(null);
  const [shorts, setShorts] = useState({ items: [], total_qty_open: 0 });
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState('receipts');          // receipts | rejects | shorts
  const [tab, setTab] = useState('on_qc');                // status penerimaan
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState({});
  const [draft, setDraft] = useState({});                 // {line_id: {qty_actual, reject_qty, reject_reason}}
  const [savingLine, setSavingLine] = useState({});
  const [finishing, setFinishing] = useState({});
  const [aql, setAql] = useState(null);                   // {lot, label} — panel di halaman

  // formulir pendek
  const [rework, setRework] = useState(null);             // {line, receipt}
  const [rwQty, setRwQty] = useState('');
  const [rwType, setRwType] = useState('permak_sendiri');
  const [rwCost, setRwCost] = useState('');
  const [rwDeadline, setRwDeadline] = useState('');
  const [rwReason, setRwReason] = useState('');
  const [rwSaving, setRwSaving] = useState(false);
  const [koreksi, setKoreksi] = useState(null);           // {mode:'qc'|'deklarasi', line, receipt}
  const [korQty, setKorQty] = useState('');
  const [korReject, setKorReject] = useState('');
  const [korReason, setKorReason] = useState('');
  const [korSaving, setKorSaving] = useState(false);
  const [resolveShort, setResolveShort] = useState(null);
  const [resType, setResType] = useState('hilang_tanggungan_vendor');
  const [resNotes, setResNotes] = useState('');
  const [resSaving, setResSaving] = useState(false);
  const [sjReceipt, setSjReceipt] = useState(null);

  const qs = useCallback((extra = {}) => portalQuery(businessType, extra), [businessType]);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      // Kartu angka dari `summary` (semua status) supaya tidak ikut berubah saat penyaring status diganti.
      const [list, rq, sum, sh] = await Promise.all([
        apiGet(`/prod/cmt-receipts${qs({ status: tab !== 'all' ? tab : '' })}`),
        apiGet(`/prod/cmt-reject-queue${qs()}`),
        apiGet(`/prod/cmt-receipts/summary${qs()}`).catch(() => null),
        apiGet(`/prod/short-shipments${qs({ status: 'open' })}`).catch(() => null),
      ]);
      setReceipts(Array.isArray(list) ? list : []);
      setRejectQueue(rq && typeof rq === 'object' ? rq : { items: [] });
      setSummary(sum && typeof sum === 'object' ? sum : null);
      setShorts(sh && typeof sh === 'object' ? sh : { items: [], total_qty_open: 0 });
    } catch (e) {
      toast.error(`Gagal memuat penerimaan: ${e.message || e}`);
      setReceipts([]);
    } finally {
      setLoading(false);
    }
  }, [qs, tab]);
  useEffect(() => { fetchAll(); }, [fetchAll]);

  const q = search.trim().toLowerCase();
  const match = (vals) => !q || vals.some((v) => String(v || '').toLowerCase().includes(q));
  const filtered = useMemo(() => receipts.filter((r) => match([r.receipt_code, r.cmt_name, r.po_number, r.delivery_note])),
    [receipts, q]); // eslint-disable-line react-hooks/exhaustive-deps
  const rejectRows = useMemo(() => (rejectQueue.items || []).filter((r) => match([r.receipt_code, r.po_number, r.vendor_name, r.sku])),
    [rejectQueue, q]); // eslint-disable-line react-hooks/exhaustive-deps
  const shortRows = useMemo(() => (shorts.items || []).filter((s) => match([s.short_number, s.po_number, s.vendor_name, s.sku, s.receipt_code])),
    [shorts, q]); // eslint-disable-line react-hooks/exhaustive-deps
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(filtered, 25);

  const kpi = {
    on_qc: Number(summary?.on_qc || 0),
    uncounted: Number(summary?.uncounted_lines || 0),
    accepted: Number(summary?.pcs_accepted_total || 0),
    reject: Number(summary?.pcs_reject_total || 0),
    undecided: Number(rejectQueue.total_qty_undecided || summary?.reject_pending_decision || 0),
    short_open: Number(shorts.total_qty_open || 0),
  };
  const anyKpi = kpi.on_qc || kpi.accepted || kpi.reject || kpi.undecided || kpi.short_open;

  const openAql = (lot, label) => setAql({ lot, label, key: Date.now() });

  // ── QC per baris ─────────────────────────────────────────────────────────
  const lineValue = (line, field) => {
    const d = draft[line.id];
    return d && d[field] !== undefined ? d[field] : line[field];
  };
  const setLineDraft = (line, field, val) => setDraft((p) => ({ ...p, [line.id]: { ...(p[line.id] || {}), [field]: val } }));

  const saveLine = async (receipt, line) => {
    const d = draft[line.id];
    if (!d) return;
    const declared = Number(line.qty_shipped_by_cmt || 0);
    const qa = d.qty_actual !== undefined ? Number(d.qty_actual || 0) : Number(line.qty_actual || 0);
    const rj = d.reject_qty !== undefined ? Number(d.reject_qty || 0) : Number(line.reject_qty || 0);
    if (declared && qa + rj > declared) {
      toast.error(`Lolos (${qa}) + ditolak (${rj}) melebihi kiriman vendor (${declared})`);
      return;
    }
    setSavingLine((p) => ({ ...p, [line.id]: true }));
    try {
      await apiPut(`/prod/cmt-receipts/${receipt.id}/lines/${line.id}`, {
        qty_actual: qa, reject_qty: rj,
        reject_reason: d.reject_reason !== undefined ? d.reject_reason : (line.reject_reason || ''),
      });
      setDraft((p) => { const n = { ...p }; delete n[line.id]; return n; });
      await fetchAll();
      toast.success('Angka QC disimpan');
    } catch (e) {
      toast.error(`Gagal simpan: ${e.message || e}`);
    } finally {
      setSavingLine((p) => ({ ...p, [line.id]: false }));
    }
  };

  const completeQcSummary = (receipt, res) => {
    const led = res?.qty_ledger;
    const shortPcs = Number(led?.short || 0);
    const parts = [`QC selesai. Stok barang jadi +${fmtNum(receipt.total_qty_actual)} pcs`];
    if (led?.quarantined) parts.push(`${fmtNum(led.quarantined)} pcs ditolak masuk karantina`);
    if (shortPcs > 0) {
      parts.push(`${fmtNum(shortPcs)} pcs belum sampai → dokumen selisih ${(led.shorts || []).map((s) => s.short_number).join(', ')} dibuka & vendor diberi tahu`);
    }
    if (Number(led?.short_resolved || 0) > 0) parts.push(`${fmtNum(led.short_resolved)} pcs selisih lama tertutup (kirim ulang)`);
    if (res?.ap_mature?.payment_code) parts.push(`Tagihan CMT ${res.ap_mature.payment_code}`);
    if (res?.ap_mature?.own_team) parts.push(res.ap_mature.message || 'Dijahit tim sendiri — tanpa tagihan CMT');
    return parts.join(' · ');
  };

  const completeQc = async (receipt) => {
    setFinishing((p) => ({ ...p, [receipt.id]: true }));
    try {
      const res = await postWithOverQtyReason(`/prod/cmt-receipts/${receipt.id}/complete-qc`, {});
      toast.success(completeQcSummary(receipt, res), { duration: 9000 });
      if (res?.qty_ledger?.errors?.length) toast.warning(res.qty_ledger.errors[0], { duration: 9000 });
      await fetchAll();
    } catch (e) {
      toast.error(`Gagal menyelesaikan QC: ${e.message || e}`);
    } finally {
      setFinishing((p) => ({ ...p, [receipt.id]: false }));
    }
  };

  const cancelReceipt = async (receipt) => {
    if (!(await confirmDialog({ title: `Batalkan penerimaan ${receipt.receipt_code}?`, body: 'Dipakai bila penerimaan salah input.', confirmLabel: 'Batalkan penerimaan', danger: true }))) return;
    try {
      await apiPost(`/prod/cmt-receipts/${receipt.id}/reject`, { reason: 'Dibatalkan oleh admin' });
      toast.success('Penerimaan dibatalkan');
      await fetchAll();
    } catch (e) {
      toast.error(`Gagal batalkan: ${e.message || e}`);
    }
  };

  // ── Koreksi resmi setelah QC selesai ─────────────────────────────────────
  const openKoreksi = (mode, line, receipt) => {
    setKoreksi({ mode, line, receipt });
    setKorQty(String(mode === 'qc' ? Number(line.qty_actual || 0) : Number(line.qty_claimed_by_cmt || line.qty_shipped_by_cmt || 0)));
    setKorReject(String(Number(line.reject_qty || 0)));
    setKorReason('');
  };
  const submitKoreksi = async () => {
    if (!koreksi) return;
    if (!korReason.trim()) { toast.error('Alasan koreksi wajib diisi'); return; }
    setKorSaving(true);
    try {
      const { mode, line, receipt } = koreksi;
      if (mode === 'qc') {
        const res = await apiPost(`/prod/cmt-receipts/${receipt.id}/lines/${line.id}/koreksi-hasil-qc`,
          { qty_actual: Number(korQty || 0), reject_qty: Number(korReject || 0), reason: korReason });
        const d = res?.stock?.delta;
        toast.success('Koreksi hasil QC tersimpan'
          + (d ? ` · stok barang jadi ${d > 0 ? '+' : ''}${d} pcs` : '')
          + (res?.short ? ` · selisih ${res.short.short_number} = ${res.short.qty_short} pcs` : ' · tidak ada selisih'), { duration: 8000 });
      } else {
        const res = await apiPost(`/prod/cmt-receipts/${receipt.id}/lines/${line.id}/koreksi-deklarasi`,
          { qty_claimed: Number(korQty || 0), reason: korReason });
        toast.success('Klaim vendor dikoreksi & dokumen deklarasi diperbarui'
          + (res?.short ? ` · selisih ${res.short.short_number} = ${res.short.qty_short} pcs` : ' · selisih dibatalkan'), { duration: 8000 });
      }
      setKoreksi(null);
      await fetchAll();
    } catch (e) {
      toast.error(`Gagal koreksi: ${e.message || e}`);
    } finally {
      setKorSaving(false);
    }
  };

  // ── Selisih kirim ────────────────────────────────────────────────────────
  const submitResolveShort = async () => {
    if (!resolveShort) return;
    setResSaving(true);
    try {
      await apiPost(`/prod/short-shipments/${resolveShort.id}/resolve`, { resolution: resType, notes: resNotes });
      toast.success(`Selisih ${resolveShort.short_number} diselesaikan`, { duration: 6000 });
      setResolveShort(null); setResNotes('');
      await fetchAll();
    } catch (e) {
      toast.error(`Gagal menyelesaikan selisih: ${e.message || e}`);
    } finally {
      setResSaving(false);
    }
  };

  // ── Permak sendiri / retur ke CMT dari baris ditolak ─────────────────────
  const openRework = (line, receipt, defaultType = 'permak_sendiri') => {
    const undecided = (rejectQueue.items || []).find((x) => x.receipt_line_id === line.id);
    setRework({ line, receipt });
    setRwQty(String(undecided ? undecided.qty_undecided : Number(line.reject_qty || 0)));
    setRwType(defaultType);
    setRwCost(''); setRwDeadline(''); setRwReason(line.reject_reason || '');
  };
  const submitRework = async () => {
    if (!rework) return;
    const n = Number(rwQty);
    if (!n || n <= 0) { toast.error('Qty harus lebih dari 0'); return; }
    setRwSaving(true);
    try {
      const res = await apiPost('/dewi/cmt-permak/from-receipt-line', {
        receipt_line_id: rework.line.id, qty: n, permak_type: rwType,
        cost_per_pcs: Number(rwCost || 0), return_deadline: rwDeadline || null, reason: rwReason,
      });
      if (rwType === 'retur_ke_cmt') {
        const sj = res?.rework?.shipment_number;
        toast.success(sj ? `Retur ke CMT dibuat. Surat jalan perbaikan ${sj} muncul di Portal Vendor.` : 'Retur ke CMT dibuat.', { duration: 8000 });
        if (res?.rework && res.rework.ok === false) toast.warning(res.rework.error || 'Surat jalan perbaikan gagal dibuat', { duration: 9000 });
      } else {
        toast.success(`Permak sendiri ${n} pcs dibuat (${res?.permak_number || ''}). Saat berhasil, stok barang jadi & qty diterima PO bertambah otomatis.`, { duration: 8000 });
      }
      setRework(null);
      await fetchAll();
    } catch (e) {
      toast.error(`Gagal: ${e.message || e}`);
    } finally {
      setRwSaving(false);
    }
  };

  const downloadSuratJalan = async (receipt, cols) => {
    try {
      const qcols = cols?.length ? `&cols=${encodeURIComponent(cols.join(','))}` : '';
      const res = await apiFetch(`/export-pdf?type=cmt-delivery-note&id=${receipt.id}${qcols}`);
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        toast.error(`Gagal membuat surat jalan: ${d.detail || d.error || res.status}`);
        return;
      }
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement('a');
      a.href = url;
      a.download = `SJ-CMT-${receipt.receipt_code}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success(`Surat jalan ${receipt.receipt_code} diunduh`);
    } catch (e) {
      toast.error(`Gagal membuat surat jalan: ${e.message || e}`);
    }
  };

  const viewOptions = [
    { key: 'receipts', label: 'Penerimaan', count: summary ? Number(summary.total || 0) : receipts.length },
    { key: 'rejects', label: 'Ditolak belum diputuskan', count: (rejectQueue.items || []).length },
    { key: 'shorts', label: 'Belum sampai', count: (shorts.items || []).length },
  ];
  const statusOptions = [
    { key: 'on_qc', label: 'Sedang QC', count: summary ? Number(summary.on_qc || 0) : undefined },
    { key: 'completed_qc', label: 'Selesai QC', count: summary ? Number(summary.completed_qc || 0) : undefined },
    { key: 'all', label: 'Semua' },
  ];

  return (
    <PageLayout
      testId="da-receive-cmt-module"
      title="Terima & QC"
      subtitle="Barang jadi dari CMT: hitung fisik, catat lolos dan ditolak, lalu selesaikan QC."
      filters={<>
        <div className="relative w-72 max-w-full">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <GlassInput value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari kode / CMT / PO / SKU…"
            data-testid="receipt-search" className="pl-9 h-9" />
        </div>
        <FilterChips value={view} onChange={setView} testId="receipt-view" ariaLabel="Tampilan" hideWhenEmpty={false}
          options={viewOptions.filter((o) => o.key === 'receipts' || o.count > 0 || view === o.key)} />
        {view === 'receipts' && (
          <FilterChips value={tab} onChange={setTab} testId="receipt-tab" ariaLabel="Penyaring status penerimaan"
            hideWhenEmpty={false} options={statusOptions} />
        )}
      </>}
      tools={<>
        <Button variant="outline" onClick={() => openAql(undefined, '')} data-testid="receipt-aql-open">
          <Calculator className="w-4 h-4" />Hitung sampel AQL
        </Button>
        <Button size="icon" variant="outline" onClick={fetchAll} disabled={loading} data-testid="receipt-refresh"
          title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </>}
      summary={anyKpi ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <StatTile testId="receipt-kpi-on_qc" label="Sedang QC" value={fmtNum(kpi.on_qc)} accent="warning"
            sub={`${fmtNum(kpi.uncounted)} baris belum dihitung`} />
          <StatTile testId="receipt-kpi-accepted" label="Lolos QC (pcs)" value={fmtNum(kpi.accepted)} accent="success"
            sub={`ditolak ${fmtNum(kpi.reject)} pcs (karantina)`} />
          <StatTile testId="receipt-kpi-undecided" label="Ditolak belum diputuskan" value={fmtNum(kpi.undecided)} accent="warning"
            sub="perlu permak atau retur ke CMT" onClick={kpi.undecided ? () => setView('rejects') : undefined} />
          <StatTile testId="receipt-kpi-short" label="Belum sampai (pcs)" value={fmtNum(kpi.short_open)} accent="danger"
            sub="kewajiban vendor — kirim ulang" onClick={kpi.short_open ? () => setView('shorts') : undefined} />
        </div>
      ) : null}
      detail={aql && (
        <DetailPanel key={aql.key} title="Hitung sampel AQL" onClose={() => setAql(null)} testId="receipt-aql-panel"
          description="Berapa pcs yang diperiksa dan batas cacat untuk menerima atau menolak kiriman.">
          <AqlSamplingTool initialLot={aql.lot} contextLabel={aql.label} testId="aql-tool" />
        </DetailPanel>
      )}
      footer={view === 'receipts' && filtered.length > pageSize && (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />
      )}
    >
      <GlassCard className="p-0 overflow-hidden">
        {view === 'rejects' ? (
          <RejectTable rows={rejectRows} onRework={openRework} />
        ) : view === 'shorts' ? (
          <ShortTable rows={shortRows} onResolve={(s) => { setResolveShort(s); setResType('hilang_tanggungan_vendor'); setResNotes(''); }} />
        ) : loading && !receipts.length ? (
          <div className="p-4 text-sm text-muted-foreground"><Loader2 className="w-4 h-4 animate-spin inline mr-2" />Memuat…</div>
        ) : filtered.length === 0 ? (
          <EmptyState icon={ClipboardCheck} title="Belum ada penerimaan pada penyaring ini"
            description="Penerimaan muncul otomatis setelah vendor CMT mendeklarasikan kiriman." />
        ) : (
          <Table data-testid="receipt-table">
            <TableHeader><TableRow>
              <TableHead className="w-10" />
              <TableHead>Kode / tanggal</TableHead><TableHead>Vendor CMT</TableHead><TableHead>PO</TableHead>
              <TableHead className="text-right">Klaim vendor</TableHead><TableHead className="text-right">Lolos QC</TableHead>
              <TableHead className="text-right">Ditolak</TableHead><TableHead className="text-right">Belum sampai</TableHead>
              <TableHead>Status</TableHead><TableHead className="text-right">Aksi</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {paged.map((r) => {
                const open = !!expanded[r.id];
                const editable = r.status === 'on_qc';
                const shortOpen = Number(r.total_qty_short_open ?? r.total_qty_short ?? 0);
                const undecided = Number(r.total_reject_undecided || 0);
                return (
                  <Fragment key={r.id}>
                    <TableRow data-testid={`receipt-row-${r.receipt_code}`}>
                      <TableCell>
                        <RowToggle open={open} onClick={() => setExpanded((p) => ({ ...p, [r.id]: !p[r.id] }))}
                          label="Lihat baris barang" testId={`receipt-expand-${r.receipt_code}`} />
                      </TableCell>
                      <TableCell className="whitespace-nowrap">
                        <span className="font-medium">{r.receipt_code}</span>
                        <span className="block text-xs text-muted-foreground">{fmtDate(r.receipt_date || r.created_at)}</span>
                      </TableCell>
                      <TableCell>
                        {r.cmt_name || '—'}
                        {r.declaration_entered_by_staff && (
                          <span className="mt-1 block">
                            <StaffEntryBadge source="staff" by={r.declaration_entered_by} compact testId={`da-receive-entry-badge-${r.receipt_code}`} />
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="whitespace-nowrap">{r.po_number || '—'}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmtNum(r.total_claimed_by_cmt ?? r.total_shipped_by_cmt)}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmtNum(r.total_qty_actual)}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {Number(r.total_qty_reject || 0) > 0 ? <span className="text-[hsl(var(--destructive))]">{fmtNum(r.total_qty_reject)}</span> : fmtNum(0)}
                        {undecided > 0 && <span className="block text-[11px] text-[hsl(var(--warning))]">{fmtNum(undecided)} belum diputuskan</span>}
                      </TableCell>
                      <TableCell className="text-right tabular-nums" data-testid={`receipt-short-${r.receipt_code}`}>
                        {shortOpen > 0 ? <span className="font-medium text-[hsl(var(--destructive))]">{fmtNum(shortOpen)}</span> : fmtNum(0)}
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={r.status} label={r.status_label || STATUS_LABEL[r.status] || r.status} tone={STATUS_TONE[r.status] || 'muted'} />
                        {!editable && r.pass_rate != null && (
                          <span className="block text-[11px] text-muted-foreground whitespace-nowrap">lolos {pct(r.pass_rate)}%</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1.5 flex-wrap">
                          <Button size="sm" variant="outline" onClick={() => setSjReceipt(r)} title="Cetak surat jalan CMT ke DA (pilih kolom)"
                            data-testid={`receipt-surat-jalan-${r.receipt_code}`}><FileText className="w-3.5 h-3.5" />Surat jalan</Button>
                          {editable && (
                            <>
                              <Button size="sm" variant="outline" onClick={() => completeQc(r)} disabled={!r.can_complete_qc || finishing[r.id]}
                                title={r.can_complete_qc ? 'Selesaikan QC' : 'Isi qty lolos semua baris dulu'} data-testid={`receipt-complete-${r.receipt_code}`}>
                                {finishing[r.id] ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}Selesaikan QC
                              </Button>
                              <Button size="icon-sm" variant="ghost" onClick={() => cancelReceipt(r)} data-testid={`receipt-cancel-${r.receipt_code}`}
                                title="Batalkan penerimaan" aria-label="Batalkan penerimaan"><Ban className="w-4 h-4" /></Button>
                            </>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                    {open && (
                      <RowDetail colSpan={10} testId={`receipt-lines-${r.receipt_code}`}>
                        <ReceiptLines receipt={r} editable={editable} draft={draft} savingLine={savingLine}
                          lineValue={lineValue} setLineDraft={setLineDraft} onSave={saveLine}
                          onKoreksi={openKoreksi} onRework={openRework}
                          onAql={() => openAql(Number(r.total_claimed_by_cmt ?? r.total_shipped_by_cmt ?? 0),
                            `Penerimaan ${r.receipt_code} · ${r.cmt_name || ''} · ${r.po_number || ''}`)} />
                      </RowDetail>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        )}
      </GlassCard>

      {/* ── Formulir pendek: permak sendiri / retur ke CMT ─────────────────── */}
      {rework && (
        <FormDialog onClose={() => setRework(null)} testId="rework-dialog"
          title={rwType === 'retur_ke_cmt' ? 'Retur barang ditolak ke vendor CMT' : 'Permak sendiri'}
          description={`Penerimaan ${rework.receipt.receipt_code} · ditolak tercatat ${fmtNum(rework.line.reject_qty)} pcs`}
          footer={<>
            <Button variant="outline" onClick={() => setRework(null)}>Batal</Button>
            <Button onClick={submitRework} disabled={rwSaving} data-testid="rework-submit">
              {rwSaving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wrench className="w-4 h-4" />}Proses
            </Button>
          </>}>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Field label="Jenis penanganan">
              <SmartNativeSelect value={rwType} onChange={(e) => setRwType(e.target.value)} data-testid="rework-type" className="w-full h-9">
                <option value="permak_sendiri">Permak sendiri (diperbaiki di DA)</option>
                <option value="retur_ke_cmt">Retur ke CMT (vendor kerjakan ulang)</option>
              </SmartNativeSelect>
            </Field>
            <Field label="Qty">
              <GlassInput type="number" min={1} value={rwQty} onChange={(e) => setRwQty(e.target.value)} data-testid="rework-qty" className="h-9" />
            </Field>
            <Field label="Ongkos per pcs (Rp)">
              <MoneyInput glass value={rwCost} onChange={(e) => setRwCost(e.target.value)} className="h-9" />
            </Field>
            <Field label="Target kembali">
              <GlassInput type="date" value={rwDeadline} onChange={(e) => setRwDeadline(e.target.value)} className="h-9" />
            </Field>
          </div>
          <Field label="Alasan / instruksi">
            <Textarea value={rwReason} onChange={(e) => setRwReason(e.target.value)} rows={2} />
          </Field>
          <Notice tone="info" icon={Info}>
            {rwType === 'retur_ke_cmt'
              ? 'Barang keluar dari karantina dan dikirim balik ke vendor lewat surat jalan perbaikan. Qty diterima PO bertambah saat kiriman ulangnya selesai QC.'
              : 'Barang tetap di DA (karantina). Saat permak berhasil, stok barang jadi dan qty diterima PO bertambah otomatis.'}
          </Notice>
        </FormDialog>
      )}

      {/* ── Formulir pendek: koreksi resmi ─────────────────────────────────── */}
      {koreksi && (
        <FormDialog onClose={() => setKoreksi(null)} testId="koreksi-dialog"
          title={koreksi.mode === 'qc' ? 'Koreksi hasil QC' : 'Koreksi klaim kirim vendor'}
          description={`${koreksi.receipt.receipt_code} · ${koreksi.line.sku_code || '—'} · klaim ${fmtNum(koreksi.line.qty_claimed_by_cmt || koreksi.line.qty_shipped_by_cmt)} · lolos ${fmtNum(koreksi.line.qty_actual)} · ditolak ${fmtNum(koreksi.line.reject_qty)}`}
          footer={<>
            <Button variant="outline" onClick={() => setKoreksi(null)}>Batal</Button>
            <Button onClick={submitKoreksi} disabled={korSaving} data-testid="koreksi-submit">
              {korSaving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Pencil className="w-4 h-4" />}Simpan koreksi
            </Button>
          </>}>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Field label={koreksi.mode === 'qc' ? 'Qty lolos QC yang benar' : 'Qty klaim vendor yang benar'}>
              <GlassInput type="number" min={0} value={korQty} onChange={(e) => setKorQty(e.target.value)} data-testid="koreksi-qty" className="h-9" />
            </Field>
            {koreksi.mode === 'qc' && (
              <Field label="Qty ditolak" hint="Barang ditolak yang sudah masuk karantina/permak tidak bisa diubah.">
                <GlassInput type="number" min={0} value={korReject} onChange={(e) => setKorReject(e.target.value)} data-testid="koreksi-reject" className="h-9" />
              </Field>
            )}
          </div>
          <Field label="Alasan koreksi (wajib)">
            <Textarea value={korReason} onChange={(e) => setKorReason(e.target.value)} rows={2} data-testid="koreksi-reason"
              placeholder={koreksi.mode === 'qc' ? 'mis. salah hitung, aktual 100 pcs' : 'mis. surat jalan vendor tertulis 100, seharusnya 90'} />
          </Field>
          <Notice tone="info" icon={Info}>
            {koreksi.mode === 'qc'
              ? 'Stok barang jadi dikoreksi sebesar selisihnya, buku kuantitas dihitung ulang dari dokumen, dan dokumen selisih kirim diperbarui. Semua tercatat di jejak audit.'
              : 'Klaim vendor diperbarui di dokumen deklarasi kirim vendor (dengan jejak audit) dan vendor mendapat pemberitahuan berisi angka baru.'}
          </Notice>
        </FormDialog>
      )}

      {/* ── Formulir pendek: penyelesaian selisih kirim ─────────────────────── */}
      {resolveShort && (
        <FormDialog onClose={() => setResolveShort(null)} testId="short-resolve-dialog"
          title={`Selesaikan selisih ${resolveShort.short_number}`}
          description={`${resolveShort.po_number || '—'} · ${resolveShort.vendor_name || '—'} · ${resolveShort.sku || '—'} · klaim ${fmtNum(resolveShort.qty_claimed)} · sampai ${fmtNum(resolveShort.qty_arrived)} · belum sampai ${fmtNum(resolveShort.qty_open ?? resolveShort.qty_short)} pcs`}
          footer={<>
            <Button variant="outline" onClick={() => setResolveShort(null)}>Batal</Button>
            <Button onClick={submitResolveShort} disabled={resSaving} data-testid="short-resolve-submit">
              {resSaving ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}Simpan keputusan
            </Button>
          </>}>
          <Field label="Keputusan">
            <SmartNativeSelect value={resType} onChange={(e) => setResType(e.target.value)} data-testid="short-resolve-type" className="w-full h-9">
              {SHORT_RESOLUTIONS.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
            </SmartNativeSelect>
          </Field>
          <Field label="Catatan">
            <Textarea value={resNotes} onChange={(e) => setResNotes(e.target.value)} rows={2} data-testid="short-resolve-notes"
              placeholder="mis. barang tidak ditemukan setelah dicari 3 hari — dibebankan ke vendor" />
          </Field>
          <Notice tone="info" icon={Info}>
            Tidak ada pemotongan tagihan otomatis: keputusan hanya dicatat dan vendor diberi tahu, lalu Keuangan
            memprosesnya di Tagihan CMT. Selisih boleh tetap terbuka sampai barang ditemukan.
          </Notice>
        </FormDialog>
      )}

      {sjReceipt && (
        <PdfColumnPicker
          docType="cmt-delivery-note" open={!!sjReceipt}
          onOpenChange={(v) => { if (!v) setSjReceipt(null); }}
          defaultKeys={SJ_DEFAULT_COLS}
          title={`Surat jalan CMT → DA — ${sjReceipt.receipt_code}`}
          confirmLabel="Cetak surat jalan"
          hint="Centang kolom yang ingin dicetak. Kolom hasil QC (qty terima / qty ditolak) hanya perlu dicentang bila surat jalan dicetak sesudah pemeriksaan."
          onConfirm={async (cols) => { const receipt = sjReceipt; setSjReceipt(null); await downloadSuratJalan(receipt, cols); }}
        />
      )}
    </PageLayout>
  );
}

/* ── Baris barang satu penerimaan (di bawah barisnya) ───────────────────── */
function ReceiptLines({ receipt: r, editable, draft, savingLine, lineValue, setLineDraft, onSave, onKoreksi, onRework, onAql }) {
  const lines = r.lines || [];
  return (
    <div className="space-y-2">
      {lines.length === 0 ? (
        <EmptyState icon={Package} title="Penerimaan ini belum berisi barang"
          description="Deklarasi kirim vendor mungkin kosong — minta vendor melengkapi deklarasinya." />
      ) : (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader><TableRow>
              <TableHead>SKU / produk</TableHead><TableHead>Warna · ukuran</TableHead>
              <TableHead className="text-right">Klaim vendor</TableHead><TableHead className="text-right">Lolos QC</TableHead>
              <TableHead className="text-right">Ditolak</TableHead><TableHead className="text-right">Belum sampai</TableHead>
              <TableHead>Alasan ditolak</TableHead><TableHead className="text-right">Aksi</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {lines.map((line) => {
                const dirty = !!draft[line.id];
                const claimed = Number(line.qty_claimed_by_cmt || line.qty_shipped_by_cmt || 0);
                const declared = Number(line.qty_shipped_by_cmt || 0);
                const shortQty = Math.max(0, Number(line.qty_short || 0) - Number(line.qty_short_resolved || 0));
                const shortOpen = line.short_status === 'open' ? shortQty : 0;
                const val = (f) => { const v = lineValue(line, f); return v === null || v === undefined ? '' : v; };
                return (
                  <TableRow key={line.id}>
                    <TableCell>
                      <span className="font-medium">{line.sku_code || '—'}</span>
                      <span className="block text-xs text-muted-foreground">{line.product_name || ''}</span>
                    </TableCell>
                    <TableCell className="whitespace-nowrap">{[line.color, line.size].filter(Boolean).join(' · ') || '—'}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {fmtNum(claimed)}
                      {!editable && claimed !== declared && (
                        <span className="block text-[11px] text-[hsl(var(--destructive))]">dokumen: {fmtNum(declared)}</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <GlassInput type="number" min={0} max={claimed || undefined} value={val('qty_actual')} disabled={!editable}
                        onChange={(e) => setLineDraft(line, 'qty_actual', e.target.value)} data-testid={`line-qty-${line.id}`}
                        className="w-20 h-8 text-right ml-auto" aria-label="Qty lolos QC" />
                    </TableCell>
                    <TableCell className="text-right">
                      <GlassInput type="number" min={0} max={claimed || undefined} value={val('reject_qty')} disabled={!editable}
                        onChange={(e) => setLineDraft(line, 'reject_qty', e.target.value)} data-testid={`line-reject-${line.id}`}
                        className="w-20 h-8 text-right ml-auto" aria-label="Qty ditolak" />
                    </TableCell>
                    <TableCell className="text-right tabular-nums" data-testid={`line-short-${line.id}`}>
                      {shortOpen > 0 ? <span className="font-medium text-[hsl(var(--destructive))]">{fmtNum(shortOpen)}</span> : fmtNum(0)}
                    </TableCell>
                    <TableCell>
                      <GlassInput value={val('reject_reason')} disabled={!editable} placeholder="mis. jahitan lepas"
                        onChange={(e) => setLineDraft(line, 'reject_reason', e.target.value)} data-testid={`line-reason-${line.id}`}
                        className="w-44 h-8" aria-label="Alasan ditolak" />
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1.5 flex-wrap">
                        {editable && (
                          <Button size="sm" variant="outline" onClick={() => onSave(r, line)} disabled={!dirty || savingLine[line.id]} data-testid={`line-save-${line.id}`}>
                            {savingLine[line.id] && <Loader2 className="w-3.5 h-3.5 animate-spin" />}Simpan
                          </Button>
                        )}
                        {!editable && (
                          <>
                            <Button size="icon-sm" variant="ghost" onClick={() => onKoreksi('qc', line, r)} data-testid={`line-koreksi-qc-${line.id}`}
                              title="Koreksi hasil QC (stok barang jadi ikut dikoreksi)" aria-label="Koreksi hasil QC"><Pencil className="w-4 h-4" /></Button>
                            <Button size="icon-sm" variant="ghost" onClick={() => onKoreksi('deklarasi', line, r)} data-testid={`line-koreksi-deklarasi-${line.id}`}
                              title="Koreksi klaim vendor (dokumen deklarasi diperbarui, vendor diberi tahu)" aria-label="Koreksi klaim vendor"><FileWarning className="w-4 h-4" /></Button>
                          </>
                        )}
                        {!editable && Number(line.reject_qty || 0) > 0 && (
                          <>
                            <Button size="sm" variant="outline" onClick={() => onRework(line, r, 'permak_sendiri')} data-testid={`line-permak-${line.id}`}>
                              <Wrench className="w-3.5 h-3.5" />Permak
                            </Button>
                            <Button size="sm" variant="outline" onClick={() => onRework(line, r, 'retur_ke_cmt')} data-testid={`line-retur-${line.id}`}>
                              <Undo2 className="w-3.5 h-3.5" />Retur CMT
                            </Button>
                          </>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="text-xs text-muted-foreground max-w-3xl">
          {editable
            ? 'Isi lolos dan ditolak lalu simpan per baris. Setelah semua baris terisi, Selesaikan QC aktif: stok barang jadi naik, barang ditolak masuk karantina, tagihan CMT dibuat. Bila lolos + ditolak kurang dari klaim vendor, sisanya dicatat sebagai barang belum sampai dan vendor diberi tahu.'
            : 'QC sudah selesai — angka tidak bisa diubah langsung. Pakai koreksi hasil QC atau koreksi klaim vendor; semua koreksi wajib beralasan dan tercatat.'}
        </p>
        <Button size="sm" variant="outline" onClick={onAql} data-testid={`receipt-aql-${r.receipt_code}`}>
          <Calculator className="w-3.5 h-3.5" />Hitung sampel AQL
        </Button>
      </div>
      {r.cmt_bill_note && <p className="text-xs font-medium" data-testid={`cmt-receipt-bill-note-${r.receipt_code}`}>{r.cmt_bill_note}</p>}
    </div>
  );
}

/* ── Antrean ditolak (supaya barang ditolak tidak pernah hilang dari layar) ─ */
function RejectTable({ rows, onRework }) {
  if (!rows.length) {
    return <EmptyState icon={Wrench} title="Tidak ada barang ditolak yang menunggu keputusan"
      description="Barang ditolak saat QC muncul di sini sampai dipermak atau diretur ke CMT." />;
  }
  return (
    <Table data-testid="reject-queue-panel">
      <TableHeader><TableRow>
        <TableHead>Penerimaan</TableHead><TableHead>PO / vendor</TableHead><TableHead>SKU</TableHead>
        <TableHead className="text-right">Ditolak</TableHead><TableHead className="text-right">Belum diputuskan</TableHead>
        <TableHead>Alasan</TableHead><TableHead className="text-right">Aksi</TableHead>
      </TableRow></TableHeader>
      <TableBody>
        {rows.map((r) => {
          const line = { id: r.receipt_line_id, reject_qty: r.qty_reject, reject_reason: r.reject_reason };
          const rc = { id: r.receipt_id, receipt_code: r.receipt_code };
          return (
            <TableRow key={r.receipt_line_id} data-testid={`rq-row-${r.receipt_line_id}`}>
              <TableCell className="whitespace-nowrap font-medium">{r.receipt_code}</TableCell>
              <TableCell>{r.po_number || '—'}<span className="block text-xs text-muted-foreground">{r.vendor_name || '—'}</span></TableCell>
              <TableCell className="whitespace-nowrap">{r.sku || '—'}</TableCell>
              <TableCell className="text-right tabular-nums text-[hsl(var(--destructive))]">{fmtNum(r.qty_reject)}</TableCell>
              <TableCell className="text-right tabular-nums font-medium text-[hsl(var(--warning))]">{fmtNum(r.qty_undecided)}</TableCell>
              <TableCell className="text-muted-foreground">{r.reject_reason || '—'}</TableCell>
              <TableCell className="text-right">
                <div className="flex items-center justify-end gap-1.5 flex-wrap">
                  <Button size="sm" variant="outline" data-testid={`rq-permak-${r.receipt_line_id}`} onClick={() => onRework(line, rc, 'permak_sendiri')}>
                    <Wrench className="w-3.5 h-3.5" />Permak sendiri
                  </Button>
                  <Button size="sm" variant="outline" data-testid={`rq-retur-${r.receipt_line_id}`} onClick={() => onRework(line, rc, 'retur_ke_cmt')}>
                    <Undo2 className="w-3.5 h-3.5" />Retur ke CMT
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

/* ── Selisih kirim: barang belum sampai (kewajiban vendor) ───────────────── */
function ShortTable({ rows, onResolve }) {
  if (!rows.length) {
    return <EmptyState icon={PackageSearch} title="Tidak ada barang yang belum sampai"
      description="Selisih antara klaim vendor dan barang yang sampai muncul di sini setelah QC selesai." />;
  }
  return (
    <div data-testid="short-shipment-panel">
      <Table>
        <TableHeader><TableRow>
          <TableHead>No. selisih</TableHead><TableHead>PO / vendor</TableHead><TableHead>SKU</TableHead>
          <TableHead className="text-right">Klaim</TableHead><TableHead className="text-right">Sampai</TableHead>
          <TableHead className="text-right">Belum sampai</TableHead><TableHead>Penerimaan</TableHead><TableHead className="text-right">Aksi</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {rows.map((s) => (
            <TableRow key={s.id} data-testid={`short-row-${s.short_number}`}>
              <TableCell className="whitespace-nowrap font-medium">{s.short_number}</TableCell>
              <TableCell>{s.po_number || '—'}<span className="block text-xs text-muted-foreground">{s.vendor_name || '—'}</span></TableCell>
              <TableCell className="whitespace-nowrap">{s.sku || '—'}</TableCell>
              <TableCell className="text-right tabular-nums">{fmtNum(s.qty_claimed)}</TableCell>
              <TableCell className="text-right tabular-nums">{fmtNum(s.qty_arrived)}</TableCell>
              <TableCell className="text-right tabular-nums font-medium text-[hsl(var(--destructive))]">{fmtNum(s.qty_open ?? s.qty_short)}</TableCell>
              <TableCell className="whitespace-nowrap text-muted-foreground">{s.receipt_code || '—'}</TableCell>
              <TableCell className="text-right">
                <Button size="sm" variant="outline" data-testid={`short-resolve-${s.short_number}`} onClick={() => onResolve(s)}>Selesaikan</Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="px-4 py-3 text-xs text-muted-foreground border-t border-[var(--glass-border)]">
        Jalur normal: vendor menemukan barangnya lalu mengirim ulang — selisih tertutup otomatis saat penerimaan kiriman ulang
        selesai QC. Selesaikan dipakai bila barang dinyatakan hilang atau ternyata salah input.
      </p>
    </div>
  );
}

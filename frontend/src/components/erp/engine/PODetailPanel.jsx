/**
 * PODetailPanel — rincian SATU PO di halaman, di bawah kepala tabel PO (Tahap 9, keputusan 8–10).
 *
 * Satu rincian untuk PO Internal dan PO Maklon (owner: "tampilan juga harus identik"). Menggantikan popup
 * Detail PO lama dan menu "Detail PO" maklon. Tab: Ringkasan · Barang · Bahan & aksesoris · Kirim & terima ·
 * Tagihan & HPP · Sampel (maklon) · Riwayat. Semua angka dari data PO utama:
 *   - GET /production-pos/{id}                      kepala, baris, status berikutnya
 *   - GET /production-pos/{id}/detail               kiriman, penerimaan & QC, permak, tagihan, sampel, BOM
 *   - GET /production-pos/{id}/quantity-summary     angka per baris (SSOT K17)
 *   - GET /production-pos/{id}/accessory-requirements  stok & permintaan pembelian aksesoris
 *   - GET /production-pos/{id}/timeline             riwayat
 * Sampel belum disetujui = peringatan saja (keputusan 10), tidak memblokir kiriman.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle, Clipboard, Edit2, FileDown, History, Layers, Package, Pencil, Plus, RefreshCw, RotateCcw,
  Send, CheckCircle2, Trash2, Truck, Wallet, XCircle, Zap, MoreHorizontal,
} from 'lucide-react';
import { toast } from 'sonner';
import { apiDelete, apiFetch, apiGet, apiPost, apiPut } from '../../../lib/api';
import { formatDateID, formatDateTimeID, formatRupiah } from '@/lib/format';
import { Button } from '@/components/ui/button';
import { GlassInput } from '@/components/ui/glass';
import { Textarea } from '@/components/ui/textarea';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import TombolUnduh from '@/components/ui/tombol-unduh';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import PanelTabs from '@/components/ui/panel-tabs';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { DetailPanel, RowDetail, RowToggle } from '../layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';
import POWorkflowIndicator from './POWorkflowIndicator';
import ProgressBreakdownBar from './ProgressBreakdownBar';
import FileAttachmentPanel from './FileAttachmentPanel';
import { PdfColumnPicker } from '../pdf/PdfColumnPicker';
import DocNumberField, { useDocNumberPolicy, docNumberPayload } from '../docnum/DocNumberField';

// ── Label tampilan (status PO disimpan dalam bahasa Inggris di server) ─────────────────────────────────
export const PO_STATUS_LABEL = {
  Draft: 'Draf', Confirmed: 'Dikonfirmasi', Distributed: 'Didistribusikan', 'In Production': 'Sedang produksi',
  'Production Complete': 'Produksi selesai', 'Variance Review': 'Tinjau selisih', 'Return Review': 'Tinjau retur',
  'Ready to Close': 'Siap ditutup', Closed: 'Ditutup', Completed: 'Selesai', 'Closed Short': 'Ditutup kurang',
  Cancelled: 'Dibatalkan',
};
const PO_STATUS_TONE = {
  Draft: 'muted', Confirmed: 'info', Distributed: 'info', 'In Production': 'warning', 'Production Complete': 'success',
  'Ready to Close': 'primary', Closed: 'muted', Completed: 'success', 'Closed Short': 'warning', Cancelled: 'danger',
};
const NEXT_LABEL = {
  Confirmed: 'Konfirmasi PO', Distributed: 'Tandai didistribusikan', 'In Production': 'Mulai produksi',
  'Production Complete': 'Tandai produksi selesai', 'Variance Review': 'Tinjau selisih',
  'Return Review': 'Tinjau retur', 'Ready to Close': 'Tandai siap ditutup', Closed: 'Tutup PO',
  'Closed Short': 'Tutup kurang',
};
const CLOSE_REASON_LABEL = {
  deadline_expired: 'Batas waktu terlewati', buyer_material_shortage: 'Bahan dari klien kurang',
  cmt_quality_reject_final: 'Reject kualitas CMT (final)', mutual_agreement: 'Kesepakatan bersama',
  full_fulfillment: 'Semua ukuran terpenuhi',
};
const CLOSED = ['Closed', 'Completed', 'Closed Short'];
const SAMPLE_TONE = { draft: 'muted', in_progress: 'info', submitted: 'warning', approved: 'success',
  rejected: 'danger', revision_requested: 'warning' };
const ACC_STATUS = { ok: ['Cukup', 'success'], shortage: ['Kurang', 'danger'], unlinked: ['Belum tertaut', 'warning'],
  client: ['Disediakan klien', 'muted'] };

const n = (v) => Number(v || 0).toLocaleString('id-ID');
const rp = (v) => formatRupiah(Number(v) || 0);
const dt = (v) => formatDateID(v, { fallback: '—' });

export function POStatusBadge({ status, testId }) {
  return <StatusBadge status={status} label={PO_STATUS_LABEL[status] || status} tone={PO_STATUS_TONE[status] || 'default'} testId={testId} />;
}

// Standar UI/UX v2: tiap tabel di rincian bisa diunduh (Excel + CSV) — `unduh={{ namaBerkas, kolom, baris }}`.
function Section({ title, aside, unduh, children, testId }) {
  const adaUnduh = unduh && (unduh.baris || []).length > 0;
  return (
    <section className="space-y-2" data-testid={testId}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold text-foreground">{title}</p>
        {(aside || adaUnduh) && (
          <div className="flex flex-wrap items-center gap-2">
            {aside}
            {adaUnduh && (
              <TombolUnduh namaBerkas={unduh.namaBerkas} namaLembar={unduh.namaLembar} kolom={unduh.kolom}
                baris={unduh.baris} testId={`${testId}-unduh`} />
            )}
          </div>
        )}
      </div>
      {children}
    </section>
  );
}

function Empty({ icon, title, description, testId }) {
  return <EmptyState icon={icon} title={title} description={description} className="py-6" testId={testId} />;
}

function Facts({ items }) {
  return (
    <dl className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-2 text-sm" data-testid="po-detail-facts">
      {items.map(([label, value]) => (
        <div key={label} className="min-w-0">
          <dt className="text-xs text-muted-foreground">{label}</dt>
          <dd className="font-medium text-foreground break-words">{value || '—'}</dd>
        </div>
      ))}
    </dl>
  );
}

// Angka ringkas di dalam rincian — tanpa kartu (rincian sudah satu kartu; G5: tidak ada kartu di dalam kartu).
function Figures({ items, testId }) {
  return (
    <dl className="grid grid-cols-2 lg:grid-cols-4 gap-x-4 gap-y-3 border-y border-[var(--glass-border)] py-3" data-testid={testId}>
      {items.map(({ label, value, sub, tone, testId: tid }) => (
        <div key={label} className="min-w-0" data-testid={tid}>
          <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
          <dd className="text-lg font-semibold tabular-nums text-foreground">{value}</dd>
          {sub && <dd className={`text-xs ${tone === 'warning' ? 'text-[hsl(var(--warning-text))]' : 'text-muted-foreground'}`}>{sub}</dd>}
        </div>
      ))}
    </dl>
  );
}

const Num = ({ children, className = '' }) => <TableCell className={`text-right tabular-nums ${className}`}>{children}</TableCell>;
const HeadNum = ({ children }) => <TableHead className="text-right">{children}</TableHead>;

// ══════════════════════════════════════════════════════════════════════════════════════════════════════
export default function PODetailPanel({
  poId, businessType, canEdit, userRole, initialTab, reloadKey = 0, onClose, onChanged, onEdit, onClosePO,
  onQuickComplete, onNavigate,
}) {
  const isInternal = businessType !== 'maklon';
  const [tab, setTab] = useState(initialTab || 'ringkasan');
  const [po, setPo] = useState(null);
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [qty, setQty] = useState(null);
  const [accReq, setAccReq] = useState(null);
  const [costCheck, setCostCheck] = useState(null);
  const [timeline, setTimeline] = useState(null);
  const [sppOpen, setSppOpen] = useState(false);
  const [busy, setBusy] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [p, d] = await Promise.all([apiGet(`/production-pos/${poId}`), apiGet(`/production-pos/${poId}/detail`)]);
      setPo(p); setDetail(d);
    } catch (e) {
      toast.error(e.message || 'Gagal memuat rincian PO');
    } finally { setLoading(false); }
  }, [poId]);

  const loadQty = useCallback(() => apiGet(`/production-pos/${poId}/quantity-summary`).then(setQty).catch(() => setQty({ items: [], totals: {} })), [poId]);
  const loadAcc = useCallback(() => apiGet(`/production-pos/${poId}/accessory-requirements`).then(setAccReq)
    .catch((e) => setAccReq({ error: e.message || 'Gagal memuat kebutuhan aksesoris', requirements: [] })), [poId]);
  const loadTimeline = useCallback(() => apiGet(`/production-pos/${poId}/timeline`).then(setTimeline)
    .catch(() => setTimeline({ events: [] })), [poId]);

  useEffect(() => { setTab(initialTab || 'ringkasan'); }, [poId, initialTab]);
  // reloadKey naik saat PO diubah/ditutup/diselesaikan dari layar induk → semua bagian dimuat ulang
  useEffect(() => { setQty(null); setAccReq(null); setTimeline(null); load(); }, [load, reloadKey]);
  useEffect(() => {
    if (isInternal) apiGet(`/production-pos/${poId}/cost-check`).then(setCostCheck).catch(() => setCostCheck(null));
  }, [poId, isInternal, reloadKey]);
  useEffect(() => {
    if (tab === 'barang' && !qty) loadQty();
    if (tab === 'bahan' && !accReq) loadAcc();
    if (tab === 'riwayat' && !timeline) loadTimeline();
  }, [tab, qty, accReq, timeline, loadQty, loadAcc, loadTimeline]);

  const refreshAll = async () => {
    await load();
    if (qty) loadQty();
    if (accReq) loadAcc();
    if (timeline) loadTimeline();
    onChanged?.();
  };

  const transition = async (next) => {
    const ok = await confirmDialog({
      title: `${NEXT_LABEL[next] || 'Ubah status'} ${po?.po_number || ''}?`,
      body: `Status PO berubah dari ${PO_STATUS_LABEL[po?.status] || po?.status} menjadi ${PO_STATUS_LABEL[next] || next}.`,
      confirmLabel: NEXT_LABEL[next] || 'Ubah status',
    });
    if (!ok) return;
    setBusy(`status-${next}`);
    try {
      await apiPost(`/production-pos/${poId}/status`, { status: next });
      toast.success(`Status PO menjadi ${PO_STATUS_LABEL[next] || next}`);
      await refreshAll();
    } catch (e) { toast.error(e.message || 'Perubahan status ditolak server'); }
    finally { setBusy(''); }
  };

  const samples = detail?.samples || [];
  const tabs = useMemo(() => [
    { key: 'ringkasan', label: 'Ringkasan' },
    { key: 'barang', label: 'Barang' },
    { key: 'bahan', label: 'Bahan & aksesoris' },
    { key: 'kirim', label: 'Kirim & terima' },
    { key: 'tagihan', label: 'Tagihan & HPP' },
    ...(isInternal ? [] : [{ key: 'sampel', label: 'Sampel', count: samples.length }]),
    { key: 'riwayat', label: 'Riwayat' },
  ], [isInternal, samples.length]);

  const closed = CLOSED.includes(po?.status);
  const title = po ? `PO ${po.po_number}` : 'Rincian PO';
  const description = po
    ? [po.customer_name, po.vendor_name ? `CMT ${po.vendor_name}` : 'CMT belum dipilih', PO_STATUS_LABEL[po.status] || po.status].filter(Boolean).join(' · ')
    : 'Memuat…';

  return (
    <DetailPanel
      title={title}
      description={description}
      onClose={onClose}
      testId="po-detail-panel"
      actions={po && (
        <>
          {!closed && detail?.sample_flag?.warning && (
            <StatusBadge status="warning" tone="warning" label="Sampel belum disetujui" testId="po-detail-sample-badge" className="hidden sm:inline-flex" />
          )}
          <Button type="button" variant="outline" size="icon" onClick={refreshAll} title="Muat ulang" aria-label="Muat ulang" data-testid="po-detail-refresh">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </Button>
          <Button type="button" variant="outline" onClick={() => setSppOpen(true)} data-testid="spp-export-pdf-btn" title="Unduh SPP (PDF)" aria-label="Unduh SPP">
            <FileDown className="w-4 h-4" /> <span className="hidden sm:inline">Unduh SPP</span>
          </Button>
          {canEdit && !closed && (
            <Button type="button" variant="outline" size="icon" onClick={() => onEdit?.(po)} title="Ubah PO" aria-label="Ubah PO" data-testid="po-detail-edit">
              <Pencil className="w-4 h-4" />
            </Button>
          )}
        </>
      )}
    >
      <PanelTabs tabs={tabs} value={tab} onChange={setTab} testId="po-detail-tab" ariaLabel="Bagian rincian PO" />
      {loading && !po ? (
        <p className="text-sm text-muted-foreground py-4">Memuat rincian PO…</p>
      ) : !po || !detail ? (
        <Empty icon={AlertTriangle} title="Rincian PO tidak bisa dimuat" description="Muat ulang, atau buka lagi dari daftar PO." />
      ) : (
        <div className="space-y-4" data-testid={`po-detail-body-${tab}`}>
          {tab === 'ringkasan' && (
            <SummaryTab po={po} detail={detail} isInternal={isInternal} canEdit={canEdit} closed={closed}
              costCheck={costCheck} busy={busy} onTransition={transition} onClosePO={onClosePO}
              onQuickComplete={onQuickComplete} userRole={userRole} onGoSamples={() => setTab('sampel')} />
          )}
          {tab === 'barang' && <ItemsTab qty={qty} isInternal={isInternal} />}
          {tab === 'bahan' && (
            <MaterialsTab poId={poId} po={po} detail={detail} isInternal={isInternal} canEdit={canEdit && !closed}
              accReq={accReq} onReloadAcc={loadAcc} onReload={refreshAll} />
          )}
          {tab === 'kirim' && <ShipTab detail={detail} isInternal={isInternal} />}
          {tab === 'tagihan' && (
            <BillingTab po={po} detail={detail} isInternal={isInternal} costCheck={costCheck} onNavigate={onNavigate} />
          )}
          {tab === 'sampel' && !isInternal && (
            <SamplesTab po={po} detail={detail} canEdit={canEdit} onReload={refreshAll} />
          )}
          {tab === 'riwayat' && <TimelineTab timeline={timeline} />}
        </div>
      )}
      {po && (
        <PdfColumnPicker
          docType="production-po"
          open={sppOpen}
          onOpenChange={setSppOpen}
          title={`Kolom PDF — SPP ${po.po_number || ''}`}
          hint="Centang kolom yang ingin tercetak pada tabel item SPP (mis. nomor seri)."
          onConfirm={async (cols) => {
            try {
              const q = cols?.length ? `&cols=${encodeURIComponent(cols.join(','))}` : '';
              const res = await apiFetch(`/export-pdf?type=production-po&id=${po.id}${q}`);
              if (!res.ok) { toast.error('Gagal mengunduh PDF'); return; }
              const blob = await res.blob();
              const url = URL.createObjectURL(blob);
              const a = document.createElement('a');
              a.href = url; a.download = `SPP-${po.po_number}.pdf`; a.click();
              URL.revokeObjectURL(url);
            } catch (e) { toast.error('Gagal mengunduh PDF: ' + e.message); }
          }}
        />
      )}
    </DetailPanel>
  );
}

// ── Ringkasan ─────────────────────────────────────────────────────────────────────────────────────────
function SummaryTab({ po, detail, isInternal, canEdit, closed, costCheck, busy, onTransition, onClosePO, onQuickComplete, userRole, onGoSamples }) {
  const t = detail.totals || {};
  const flag = detail.sample_flag;
  const next = Array.isArray(po.allowed_next) ? po.allowed_next : [];
  return (
    <>
      <div className="flex flex-wrap items-center gap-3" data-testid="po-detail-status">
        <POStatusBadge status={po.status} testId="po-detail-status-badge" />
        <div className="min-w-[220px] flex-1"><POWorkflowIndicator status={po.status} /></div>
      </div>
      {canEdit && (next.length > 0 || po.can_close || !closed) && (
        <div className="flex flex-wrap items-center gap-2" data-testid="po-detail-actions">
          {next.map(ns => (
            <Button type="button" key={ns} variant="outline" size="sm" disabled={!!busy} onClick={() => onTransition(ns)}
              data-testid={`po-action-${ns.toLowerCase().replace(/\s+/g, '-')}`}>{NEXT_LABEL[ns] || PO_STATUS_LABEL[ns] || ns}</Button>
          ))}
          {po.can_close && (
            <Button type="button" variant="outline" size="sm" onClick={() => onClosePO?.(po)} data-testid="po-action-close">Tutup PO</Button>
          )}
          {!closed && (
            <Button type="button" variant="outline" size="sm" onClick={() => onQuickComplete?.(po)} data-testid="detail-quick-complete-btn">
              <Zap className="w-3.5 h-3.5" /> Selesaikan cepat
            </Button>
          )}
        </div>
      )}
      {!isInternal && flag?.warning && (
        <Notice tone="warning" icon={AlertTriangle} testId="po-detail-sample-warning"
          action={<Button type="button" variant="link" size="sm" onClick={onGoSamples}>Buka tab Sampel</Button>}>
          Sampel belum disetujui klien{flag.count ? ` (${flag.count} sampel, terakhir: ${flag.latest_label.toLowerCase()})` : ' — belum ada sampel'}.
          Hanya peringatan: kiriman ke CMT tetap bisa dibuat.
        </Notice>
      )}
      {po.close_reason && (
        <Notice tone="warning" icon={AlertTriangle} testId="po-detail-close-reason">
          Alasan penutupan: {CLOSE_REASON_LABEL[po.close_reason] || po.close_reason}
          {po.close_notes ? ` — ${po.close_notes}` : ''}. Ditutup oleh {po.closed_by || '—'} pada {dt(po.closed_at)}.
        </Notice>
      )}
      {isInternal && costCheck?.items_with_issues > 0 && (
        <Notice tone="warning" icon={AlertTriangle} testId="po-cost-warning">
          Harga bahan atau upah belum lengkap pada {costCheck.items_with_issues} baris — nilai barang jadi akan terlalu rendah.
          {' '}{(costCheck.items || []).filter(i => (i.issues || []).length).slice(0, 4).map(i => `${i.sku || i.product_name}: ${i.issues.join('; ')}`).join(' · ')}
        </Notice>
      )}
      <Facts items={[
        ['No. PO', po.po_number],
        [isInternal ? 'Tujuan barang jadi' : 'Klien', po.customer_name],
        ['Penjahit (CMT)', po.vendor_name || 'Belum dipilih'],
        ['Tanggal PO', dt(po.po_date)],
        ['Tenggat produksi', dt(po.deadline)],
        ['Tenggat kirim', dt(po.delivery_deadline)],
        ['Dibuat oleh', po.created_by],
        ['Catatan', po.notes],
      ]} />
      <Figures testId="po-detail-kpis" items={[
        { label: 'Dipesan', value: `${n(t.ordered)} pcs`, testId: 'po-kpi-ordered' },
        { label: 'Dikirim ke CMT', value: `${n(t.sent_to_cmt)} pcs`, testId: 'po-kpi-sent' },
        { label: 'Lolos QC', value: `${n(t.accepted)} pcs`, testId: 'po-kpi-accepted',
          sub: `tolak ${n(t.reject)} · permak terbuka ${n(t.rework_open)}`, tone: t.reject ? 'warning' : undefined },
        { label: isInternal ? 'Diserahkan ke gudang' : 'Dikirim ke klien', value: `${n(t.dispatched)} pcs`,
          testId: 'po-kpi-dispatched', sub: `sisa ${n(t.remaining_to_ship)} pcs` },
      ]} />
      {detail.progress?.breakdown && (
        <Section title="Kemajuan (lolos · tolak · permak)" testId="po-detail-progress">
          <ProgressBreakdownBar breakdown={detail.progress.breakdown} />
        </Section>
      )}
      <FileAttachmentPanel entityType="production_po" entityId={po.id} userRole={userRole} />
    </>
  );
}

// ── Barang ────────────────────────────────────────────────────────────────────────────────────────────
function ItemsTab({ qty, isInternal }) {
  if (!qty) return <p className="text-sm text-muted-foreground">Memuat angka per baris…</p>;
  const items = qty.items || [];
  if (!items.length) return <Empty icon={Package} title="PO ini belum punya baris" description="Tambahkan baris lewat tombol Ubah PO." />;
  const sum = (k) => items.reduce((s, i) => s + (Number(i[k]) || 0), 0);
  return (
    <Section title="Barang per baris" testId="po-detail-items" unduh={{ namaBerkas: 'po-barang-per-baris', baris: items, kolom: [
      { label: 'Produk', nilai: (i) => i.product_name }, { label: 'SKU', nilai: (i) => i.sku || '' },
      { label: 'No. seri', nilai: (i) => i.serial_number || '' }, { label: 'Ukuran', nilai: (i) => i.size || '' },
      { label: 'Warna', nilai: (i) => i.color || '' }, { label: 'Dipesan', nilai: (i) => Number(i.ordered_qty) || 0 },
      { label: 'Bahan di CMT', nilai: (i) => Number(i.received_qty) || 0 }, { label: 'Diproduksi', nilai: (i) => Number(i.produced_qty) || 0 },
      { label: 'Diterima (lolos QC)', nilai: (i) => Number(i.accepted_total_qty ?? i.accepted_qty) || 0 },
      { label: isInternal ? 'Diserahkan' : 'Dikirim ke klien', nilai: (i) => Number(i.shipped_qty) || 0 },
    ] }}>
      <Table data-testid="po-detail-items-table">
        <TableHeader><TableRow>
          <TableHead>Produk / SKU</TableHead><TableHead>No. seri</TableHead><TableHead>Ukuran / warna</TableHead>
          <HeadNum>Dipesan</HeadNum><HeadNum>Bahan di CMT</HeadNum><HeadNum>Diproduksi</HeadNum>
          <HeadNum>Diterima (lolos QC)</HeadNum><HeadNum>{isInternal ? 'Diserahkan' : 'Dikirim ke klien'}</HeadNum>
        </TableRow></TableHeader>
        <TableBody>{items.map(it => (
          <TableRow key={it.id} data-testid={`po-detail-line-${it.sku || it.id}`}>
            <TableCell><div className="font-medium">{it.product_name}</div><div className="text-xs text-muted-foreground tabular-nums">{it.sku || '—'}</div></TableCell>
            <TableCell className="tabular-nums text-xs">{it.serial_number || '—'}</TableCell>
            <TableCell className="text-xs">{it.size || '—'} / {it.color || '—'}</TableCell>
            <Num>{n(it.ordered_qty)}</Num><Num>{n(it.received_qty)}</Num><Num>{n(it.produced_qty)}</Num>
            <Num>{n(it.accepted_total_qty ?? it.accepted_qty)}</Num><Num>{n(it.shipped_qty)}</Num>
          </TableRow>
        ))}</TableBody>
        <TableFooter><TableRow>
          <TableCell colSpan={3} className="font-semibold">Total</TableCell>
          <Num className="font-semibold">{n(sum('ordered_qty'))}</Num><Num className="font-semibold">{n(sum('received_qty'))}</Num>
          <Num className="font-semibold">{n(sum('produced_qty'))}</Num>
          <Num className="font-semibold">{n(items.reduce((s, i) => s + (Number(i.accepted_total_qty ?? i.accepted_qty) || 0), 0))}</Num>
          <Num className="font-semibold" >{n(sum('shipped_qty'))}</Num>
        </TableRow></TableFooter>
      </Table>
      <p className="text-xs text-muted-foreground">Bahan di CMT = kiriman yang sudah diterima CMT. Diterima = lolos QC di Terima & QC.</p>
    </Section>
  );
}

// ── Bahan & aksesoris ─────────────────────────────────────────────────────────────────────────────────
function MaterialsTab({ poId, po, detail, isInternal, canEdit, accReq, onReloadAcc, onReload }) {
  const bom = detail.bom || { lines: [] };
  const plan = detail.accessory_plan || [];
  const [syncing, setSyncing] = useState(false);
  const [templates, setTemplates] = useState(null);
  const [creating, setCreating] = useState(false);

  const syncBom = async (templateId = null) => {
    setSyncing(true);
    try {
      const r = await apiPost(`/dewi/maklon/pos/${poId}/bom-sync`, { template_id: templateId, force: true });
      toast.success(`BOM tersinkron: ${r?.materials || 0} bahan, ${r?.accessory_rows || 0} aksesoris masuk rencana PO`);
      setTemplates(null);
      await onReload();
    } catch (e) { toast.error(e.message || 'Gagal menyinkronkan BOM'); }
    finally { setSyncing(false); }
  };
  const openTemplates = async () => {
    const ids = [...new Set((po.items || []).map(i => i.catalog_item_id).filter(Boolean))];
    const all = [];
    for (const cid of ids) {
      try {
        const d = await apiGet(`/dewi/maklon/bom-templates?buyer_catalog_id=${cid}`);
        all.push(...(Array.isArray(d) ? d : (d?.templates || d?.items || [])));
      } catch { /* artikel tanpa template */ }
    }
    setTemplates(all);
  };
  const createRequest = async () => {
    setCreating(true);
    try {
      const res = await apiFetch(`/production-pos/${poId}/accessory-requirements/create-request`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ only_shortage: true }),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d?.detail || 'Gagal mengajukan pembelian aksesoris');
      toast.success(d.message || 'Permintaan pembelian aksesoris yang kurang dibuat.');
      onReloadAcc();
    } catch (e) { toast.error(e.message); }
    finally { setCreating(false); }
  };

  const reqs = accReq?.requirements || [];
  return (
    <>
      <Section title={isInternal ? 'BOM (kebutuhan dari model)' : 'BOM PO'} testId="po-detail-bom"
        unduh={{ namaBerkas: `bom-po-${po.po_number}`, baris: bom.lines || [], kolom: [
          { label: 'Bahan', nilai: (l) => l.name }, { label: 'Kode', nilai: (l) => l.code || '' },
          { label: 'Jenis', nilai: (l) => l.type_label || '' },
          ...(isInternal ? [] : [{ label: 'Per pcs', nilai: (l) => Number(l.qty_per_pcs) || 0 }]),
          { label: 'Perkiraan total', nilai: (l) => Number(l.qty_total) || 0 }, { label: 'Satuan', nilai: (l) => l.unit || '' },
          { label: 'Disediakan', nilai: (l) => l.supplied_by || '' },
        ] }}
        aside={!isInternal && canEdit && (
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => syncBom(null)} disabled={syncing} data-testid="po-bom-sync">
              <RefreshCw className={`w-3.5 h-3.5 ${syncing ? 'animate-spin' : ''}`} /> Sinkronkan dari template aktif
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={openTemplates} disabled={syncing} data-testid="po-bom-pick-version">
              <Layers className="w-3.5 h-3.5" /> Pilih versi template
            </Button>
          </div>
        )}>
        {!isInternal && (
          <p className="text-xs text-muted-foreground">
            {bom.source_templates?.length ? `Sumber: ${bom.source_templates.map(t => `versi ${t.version}${t.label ? ` (${t.label})` : ''}`).join(', ')}` : 'Sumber template belum tercatat'}
            {bom.locked ? ' · versi dipilih manual, tidak ditimpa saat PO diubah' : ''}
            {bom.total_qty ? ` · dasar ${n(bom.total_qty)} pcs` : ''}
          </p>
        )}
        {templates && (
          <Table data-testid="po-bom-template-picker">
            <TableHeader><TableRow><TableHead>Versi template</TableHead><TableHead>Artikel</TableHead><HeadNum>Bahan</HeadNum><TableHead /></TableRow></TableHeader>
            <TableBody>
              {templates.length === 0 ? (
                <TableRow><TableCell colSpan={4}><Empty icon={Layers} title="Belum ada template BOM" description="Buat template BOM di Katalog Buyer untuk artikel pada PO ini." /></TableCell></TableRow>
              ) : templates.map(t => (
                <TableRow key={t.id}>
                  <TableCell>Versi {t.version}{t.version_label ? ` · ${t.version_label}` : ''}{t.is_active ? ' (aktif)' : ''}</TableCell>
                  <TableCell className="tabular-nums text-xs">{t.buyer_catalog_code || '—'}</TableCell>
                  <Num>{n((t.materials || []).length)}</Num>
                  <TableCell className="text-right"><Button type="button" variant="outline" size="sm" disabled={syncing} onClick={() => syncBom(t.id)}>Terapkan</Button></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        {(bom.warnings || []).length > 0 && (
          <Notice tone="warning" icon={AlertTriangle} testId="po-bom-warnings">{bom.warnings.slice(0, 6).join(' · ')}</Notice>
        )}
        {(bom.lines || []).length === 0 ? (
          <Empty icon={Layers} title="Belum ada BOM untuk PO ini"
            description={isInternal ? 'Pastikan model setiap baris punya BOM aktif di Master Produk.' : 'Sinkronkan dari template aktif artikel Katalog Buyer.'} />
        ) : (
          <Table data-testid="po-detail-bom-table">
            <TableHeader><TableRow>
              <TableHead>Bahan</TableHead><TableHead>Jenis</TableHead>{!isInternal && <HeadNum>Per pcs</HeadNum>}
              <HeadNum>Perkiraan total</HeadNum><TableHead>Satuan</TableHead><TableHead>Disediakan</TableHead>
            </TableRow></TableHeader>
            <TableBody>{bom.lines.map((l, i) => (
              <TableRow key={`${l.code || l.name}-${i}`}>
                <TableCell><div className="font-medium">{l.name}</div>{l.code && <div className="text-xs text-muted-foreground tabular-nums">{l.code}</div>}</TableCell>
                <TableCell className="text-xs">{l.type_label}</TableCell>
                {!isInternal && <Num>{n(l.qty_per_pcs)}</Num>}
                <Num>{n(l.qty_total)}</Num><TableCell className="text-xs">{l.unit || '—'}</TableCell>
                <TableCell className="text-xs">{l.supplied_by}</TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
        )}
      </Section>

      <Section title="Rencana aksesoris" testId="po-detail-acc-plan"
        unduh={{ namaBerkas: `rencana-aksesoris-${po.po_number}`, baris: plan, kolom: [
          { label: 'Aksesoris', nilai: (a) => a.name }, { label: 'Kode', nilai: (a) => a.code || '' },
          { label: 'Sumber', nilai: (a) => a.source_label || '' }, { label: 'Kebutuhan BOM', nilai: (a) => Number(a.bom_qty_base) || 0 },
          { label: 'Satuan pakai', nilai: (a) => a.usage_unit || '' },
          { label: 'Satuan serah', nilai: (a) => (a.has_handover ? `${a.handover_uom} isi ${a.handover_factor} ${a.usage_unit}` : '') },
          { label: 'Rencana serah', nilai: (a) => (a.has_handover && a.plan_qty_handover !== null ? Number(a.plan_qty_handover) || 0 : Number(a.bom_qty_base) || 0) },
          { label: 'Satuan rencana', nilai: (a) => (a.has_handover && a.plan_qty_handover !== null ? a.handover_uom : a.usage_unit) || '' },
        ] }}
        aside={<span className="text-xs text-muted-foreground">Angka BOM = perkiraan; jumlah serah final diatur di form PO.</span>}>
        {plan.length === 0 ? (
          <Empty icon={Clipboard} title="Belum ada rencana aksesoris" description="Aksesoris dari BOM dan tambahan diatur lewat tombol Ubah PO." />
        ) : (
          <Table data-testid="po-detail-acc-plan-table">
            <TableHeader><TableRow>
              <TableHead>Aksesoris</TableHead><TableHead>Sumber</TableHead><HeadNum>Kebutuhan BOM</HeadNum>
              <TableHead>Satuan serah</TableHead><HeadNum>Rencana serah</HeadNum>
            </TableRow></TableHeader>
            <TableBody>{plan.map((a, i) => (
              <TableRow key={a.id || i} data-testid={`po-acc-plan-row-${i}`}>
                <TableCell><div className="font-medium">{a.name}</div>{a.code && <div className="text-xs text-muted-foreground tabular-nums">{a.code}</div>}</TableCell>
                <TableCell className="text-xs">{a.source_label}</TableCell>
                <Num>{n(a.bom_qty_base)} {a.usage_unit}</Num>
                <TableCell className="text-xs">{a.has_handover ? `${a.handover_uom} isi ${n(a.handover_factor)} ${a.usage_unit}` : '—'}</TableCell>
                <Num>{a.has_handover && a.plan_qty_handover !== null ? `${n(a.plan_qty_handover)} ${a.handover_uom}` : `${n(a.bom_qty_base)} ${a.usage_unit}`}</Num>
              </TableRow>
            ))}</TableBody>
          </Table>
        )}
      </Section>

      <Section title="Stok & pembelian aksesoris" testId="po-accessory-requirements"
        unduh={{ namaBerkas: `stok-aksesoris-${po.po_number}`, baris: reqs, kolom: [
          { label: 'Aksesoris', nilai: (a) => a.material_name || a.accessory_name || '' },
          { label: 'Kode', nilai: (a) => a.material_code || a.accessory_code || '' },
          { label: 'Dibutuhkan', nilai: (a) => Number(a.qty_needed) || 0 }, { label: 'Satuan', nilai: (a) => a.unit || '' },
          { label: 'Sudah keluar', nilai: (a) => (a.linked ? Number(a.issued) || 0 : '') },
          { label: 'Tersedia', nilai: (a) => (a.linked ? Number(a.available) || 0 : '') },
          { label: 'Kurang', nilai: (a) => (a.linked ? Number(a.shortage) || 0 : '') },
          { label: 'Status', nilai: (a) => (ACC_STATUS[a.status] || [a.status || ''])[0] },
        ] }}
        aside={canEdit && accReq?.summary?.shortage_lines > 0 && (
          <Button type="button" variant="outline" size="sm" onClick={createRequest} disabled={creating} data-testid="po-acc-create-request-btn">
            {creating ? 'Mengajukan…' : `Ajukan pembelian (${accReq.summary.shortage_lines} kurang)`}
          </Button>
        )}>
        {!accReq ? <p className="text-sm text-muted-foreground">Memuat stok aksesoris…</p>
          : accReq.error ? <Notice tone="danger" icon={AlertTriangle}>{accReq.error}</Notice>
          : reqs.length === 0 ? (
            <Empty icon={Clipboard} title="Tidak ada kebutuhan aksesoris" description="Kebutuhan dihitung dari BOM aktif dan rencana aksesoris PO." />
          ) : (
            <>
              {accReq.summary?.unlinked_lines > 0 && (
                <Notice tone="warning" icon={AlertTriangle}>{accReq.summary.unlinked_lines} baris belum tertaut ke master bahan — stoknya tidak bisa dicek.</Notice>
              )}
              <Table data-testid="po-acc-req-table">
                <TableHeader><TableRow>
                  <TableHead>Aksesoris</TableHead><HeadNum>Dibutuhkan</HeadNum><HeadNum>Sudah keluar</HeadNum>
                  <HeadNum>Tersedia</HeadNum><HeadNum>Kurang</HeadNum><TableHead>Status</TableHead>
                </TableRow></TableHeader>
                <TableBody>{reqs.map((a, i) => {
                  const [lbl, tone] = ACC_STATUS[a.status] || [a.status || '—', 'default'];
                  return (
                    <TableRow key={a.id || i} data-testid={`po-acc-req-row-${i}`}>
                      <TableCell><div className="font-medium">{a.material_name || a.accessory_name}</div><div className="text-xs text-muted-foreground tabular-nums">{a.material_code || a.accessory_code || '—'}</div></TableCell>
                      <Num>{n(a.qty_needed)} {a.unit}</Num>
                      <Num>{a.linked ? n(a.issued) : '—'}</Num><Num>{a.linked ? n(a.available) : '—'}</Num>
                      <Num className={a.shortage > 0 ? 'text-[hsl(var(--danger-text))] font-semibold' : ''}>{a.linked ? n(a.shortage) : '—'}</Num>
                      <TableCell><StatusBadge status={a.status} label={lbl} tone={tone} /></TableCell>
                    </TableRow>
                  );
                })}</TableBody>
              </Table>
              {(accReq.existing_requests || []).length > 0 && (
                <p className="text-xs text-muted-foreground" data-testid="po-acc-existing-requests">
                  Permintaan pembelian untuk PO ini: {accReq.existing_requests.map(r => `${r.request_code} (${r.status})`).join(', ')}
                </p>
              )}
            </>
          )}
      </Section>
    </>
  );
}

// ── Kirim & terima ────────────────────────────────────────────────────────────────────────────────────
function ShipTab({ detail, isInternal }) {
  const vs = detail.vendor_shipments || [];
  const rc = detail.receipts || [];
  const pm = detail.permak || [];
  const rs = detail.result_shipments || [];
  return (
    <>
      <Section title={`Kiriman ke CMT (${vs.length})`} testId="po-detail-vendor-shipments" unduh={{ namaBerkas: 'po-kiriman-ke-cmt', baris: vs, kolom: [
        { label: 'No. kiriman', nilai: (s) => s.number }, { label: 'Tanggal', nilai: (s) => dt(s.date) },
        { label: 'CMT', nilai: (s) => s.vendor_name || '' }, { label: 'Jenis', nilai: (s) => s.type_label || '' },
        { label: 'Qty', nilai: (s) => Number(s.qty) || 0 }, { label: 'Status', nilai: (s) => s.status_label || '' },
      ] }}>
        {vs.length === 0 ? <Empty icon={Truck} title="Belum ada kiriman ke CMT" description="Kiriman dibuat di menu Kirim ke CMT." /> : (
          <Table>
            <TableHeader><TableRow><TableHead>No. kiriman</TableHead><TableHead>Tanggal</TableHead><TableHead>CMT</TableHead><TableHead>Jenis</TableHead><HeadNum>Qty</HeadNum><TableHead>Status</TableHead></TableRow></TableHeader>
            <TableBody>{vs.map(s => (
              <TableRow key={s.id}><TableCell className="tabular-nums">{s.number}</TableCell><TableCell>{dt(s.date)}</TableCell>
                <TableCell>{s.vendor_name || '—'}</TableCell><TableCell className="text-xs">{s.type_label}</TableCell><Num>{n(s.qty)}</Num>
                <TableCell><StatusBadge status={s.status} label={s.status_label} tone={s.status === 'Received' ? 'success' : 'info'} /></TableCell></TableRow>
            ))}</TableBody>
          </Table>
        )}
      </Section>
      <Section title={`Penerimaan & QC (${rc.length})`} testId="po-detail-receipts" unduh={{ namaBerkas: 'po-penerimaan-qc', baris: rc, kolom: [
        { label: 'No. terima', nilai: (r) => r.number }, { label: 'Tanggal', nilai: (r) => dt(r.date) },
        { label: 'CMT', nilai: (r) => r.vendor_name || '' }, { label: 'Dikirim CMT', nilai: (r) => Number(r.qty_claimed) || 0 },
        { label: 'Lolos', nilai: (r) => Number(r.qty_good) || 0 }, { label: 'Tolak', nilai: (r) => Number(r.qty_reject) || 0 },
        { label: 'Status', nilai: (r) => r.status_label || '' },
      ] }}>
        {rc.length === 0 ? <Empty icon={CheckCircle2} title="Belum ada penerimaan dari CMT" description="Penerimaan dan QC dicatat di menu Terima & QC." /> : (
          <Table>
            <TableHeader><TableRow><TableHead>No. terima</TableHead><TableHead>Tanggal</TableHead><TableHead>CMT</TableHead><HeadNum>Dikirim CMT</HeadNum><HeadNum>Lolos</HeadNum><HeadNum>Tolak</HeadNum><TableHead>Status</TableHead></TableRow></TableHeader>
            <TableBody>{rc.map(r => (
              <TableRow key={r.id}><TableCell className="tabular-nums">{r.number}</TableCell><TableCell>{dt(r.date)}</TableCell>
                <TableCell>{r.vendor_name || '—'}</TableCell><Num>{n(r.qty_claimed)}</Num><Num>{n(r.qty_good)}</Num>
                <Num className={r.qty_reject ? 'text-[hsl(var(--danger-text))]' : ''}>{n(r.qty_reject)}</Num>
                <TableCell><StatusBadge status={r.status} label={r.status_label} tone={r.status === 'completed_qc' ? 'success' : r.status === 'cancelled' ? 'danger' : 'warning'} /></TableCell></TableRow>
            ))}</TableBody>
          </Table>
        )}
      </Section>
      <Section title={`Permak (${pm.length})`} testId="po-detail-permak" unduh={{ namaBerkas: 'po-permak', baris: pm, kolom: [
        { label: 'No. permak', nilai: (x) => x.number || '' }, { label: 'SKU', nilai: (x) => `${x.sku || ''} ${x.size || ''}`.trim() },
        { label: 'Tempat', nilai: (x) => x.where_label || '' }, { label: 'Qty', nilai: (x) => Number(x.qty) || 0 },
        { label: 'Berhasil', nilai: (x) => Number(x.qty_fixed) || 0 }, { label: 'Dibuang', nilai: (x) => Number(x.qty_scrap) || 0 },
        { label: 'Status', nilai: (x) => x.status_label || '' },
      ] }}>
        {pm.length === 0 ? <Empty icon={RotateCcw} title="Tidak ada permak" description="Barang tolak yang dipermak tercatat di menu Perbaikan." /> : (
          <Table>
            <TableHeader><TableRow><TableHead>No. permak</TableHead><TableHead>SKU</TableHead><TableHead>Tempat</TableHead><HeadNum>Qty</HeadNum><HeadNum>Berhasil</HeadNum><HeadNum>Dibuang</HeadNum><TableHead>Status</TableHead></TableRow></TableHeader>
            <TableBody>{pm.map(p => (
              <TableRow key={p.id}><TableCell className="tabular-nums">{p.number || '—'}</TableCell><TableCell className="tabular-nums text-xs">{p.sku} {p.size}</TableCell>
                <TableCell className="text-xs">{p.where_label}</TableCell><Num>{n(p.qty)}</Num><Num>{n(p.qty_fixed)}</Num><Num>{n(p.qty_scrap)}</Num>
                <TableCell><StatusBadge status={p.status} label={p.status_label} tone={p.status === 'selesai_berhasil' ? 'success' : p.status === 'gagal_buang' ? 'danger' : 'warning'} /></TableCell></TableRow>
            ))}</TableBody>
          </Table>
        )}
      </Section>
      <Section title={`${isInternal ? 'Serah ke gudang DA' : 'Kiriman ke klien'} (${rs.length})`} testId="po-detail-result-shipments"
        unduh={{ namaBerkas: 'po-kiriman-hasil', baris: rs, kolom: [
          { label: 'No. surat jalan', nilai: (x) => x.number }, { label: 'Tanggal', nilai: (x) => dt(x.date) },
          { label: 'Qty', nilai: (x) => Number(x.qty) || 0 }, { label: 'Status', nilai: (x) => x.status_label || '' },
        ] }}>
        {rs.length === 0 ? <Empty icon={Send} title="Belum ada kiriman hasil" description="Kiriman hasil dibuat di menu Kirim hasil." /> : (
          <Table>
            <TableHeader><TableRow><TableHead>No. surat jalan</TableHead><TableHead>Tanggal</TableHead><HeadNum>Qty</HeadNum><TableHead>Status</TableHead></TableRow></TableHeader>
            <TableBody>{rs.map(s => (
              <TableRow key={s.id}><TableCell className="tabular-nums">{s.number}</TableCell><TableCell>{dt(s.date)}</TableCell><Num>{n(s.qty)}</Num>
                <TableCell><StatusBadge status={s.status} label={s.status_label} tone="info" /></TableCell></TableRow>
            ))}</TableBody>
          </Table>
        )}
      </Section>
    </>
  );
}

// ── Tagihan & HPP ─────────────────────────────────────────────────────────────────────────────────────
function BillingTab({ po, detail, isInternal, costCheck, onNavigate }) {
  const items = po.items || [];
  const bills = detail.cmt_bills || [];
  const bt = detail.cmt_bill_totals || {};
  const ar = detail.client_ar;
  const tot = (f) => items.reduce((s, i) => s + (Number(i.qty) || 0) * (Number(f(i)) || 0), 0);
  const totalRate = tot(i => i.cmt_price_snapshot);
  const totalSell = tot(i => i.selling_price_snapshot);
  return (
    <>
      <Section title="Nilai per baris" testId="po-detail-values" unduh={{ namaBerkas: `nilai-po-${po.po_number}`, baris: items, kolom: [
        { label: 'Produk', nilai: (i) => i.product_name }, { label: 'SKU', nilai: (i) => i.sku || '' },
        { label: 'Qty', nilai: (i) => Number(i.qty) || 0 }, { label: 'Upah jahit / pcs', nilai: (i) => Number(i.cmt_price_snapshot) || 0 },
        { label: 'Total upah', nilai: (i) => (Number(i.qty) || 0) * (Number(i.cmt_price_snapshot) || 0) },
        ...(isInternal ? [] : [
          { label: 'Harga jasa / pcs', nilai: (i) => Number(i.selling_price_snapshot) || 0 },
          { label: 'Selisih / pcs', nilai: (i) => (Number(i.selling_price_snapshot) || 0) - (Number(i.cmt_price_snapshot) || 0) },
        ]),
      ] }}>
        <Table data-testid="po-detail-values-table">
          <TableHeader><TableRow>
            <TableHead>Produk / SKU</TableHead><HeadNum>Qty</HeadNum><HeadNum>Upah jahit / pcs</HeadNum><HeadNum>Total upah</HeadNum>
            {!isInternal && <HeadNum>Harga jasa / pcs</HeadNum>}{!isInternal && <HeadNum>Selisih / pcs</HeadNum>}
          </TableRow></TableHeader>
          <TableBody>{items.map(it => {
            const m = (Number(it.selling_price_snapshot) || 0) - (Number(it.cmt_price_snapshot) || 0);
            return (
              <TableRow key={it.id}>
                <TableCell><div className="font-medium">{it.product_name}</div><div className="text-xs text-muted-foreground tabular-nums">{it.sku || '—'}</div></TableCell>
                <Num>{n(it.qty)}</Num><Num>{rp(it.cmt_price_snapshot)}</Num><Num>{rp((it.qty || 0) * (it.cmt_price_snapshot || 0))}</Num>
                {!isInternal && <Num>{rp(it.selling_price_snapshot)}</Num>}
                {!isInternal && <Num className={m < 0 ? 'text-[hsl(var(--danger-text))]' : ''}>{rp(m)}</Num>}
              </TableRow>
            );
          })}</TableBody>
          <TableFooter><TableRow>
            <TableCell className="font-semibold">Total</TableCell><Num className="font-semibold">{n(items.reduce((s, i) => s + (Number(i.qty) || 0), 0))}</Num>
            <TableCell /><Num className="font-semibold" >{rp(totalRate)}</Num>
            {!isInternal && <Num className="font-semibold">{rp(totalSell)}</Num>}
            {!isInternal && <Num className="font-semibold">{rp(totalSell - totalRate)}</Num>}
          </TableRow></TableFooter>
        </Table>
      </Section>
      <Figures testId="po-detail-hpp-tiles" items={isInternal ? [
        { label: 'Bahan (BOM warna varian)', sub: 'Harga bahan × qty',
          value: rp((costCheck?.items || []).reduce((s, i) => s + (i.material_cost || 0) * (Number(i.qty) || 0), 0)) },
        { label: 'Upah jahit', sub: 'Upah per pcs × qty', value: rp(totalRate) },
        { label: 'Perkiraan HPP batch', sub: 'Angka aktual ada di HPP per PO', value: costCheck ? rp(costCheck.estimated_batch_value) : '…' },
      ] : [
        { label: 'Total harga jasa', sub: 'Harga jasa × qty pesanan', value: rp(totalSell) },
        { label: 'Total upah jahit', sub: 'Upah per pcs × qty pesanan', value: rp(totalRate) },
        { label: 'Selisih rencana', sub: 'Margin aktual ada di HPP per PO', value: rp(totalSell - totalRate) },
      ]} />
      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" variant="link" size="sm" className="px-0" data-testid="po-detail-open-hpp"
          onClick={() => onNavigate?.(isInternal ? 'fin-hpp' : 'maklon-hpp', { po_id: po.id })}>Buka HPP per PO</Button>
        {!isInternal && (
          <Button type="button" variant="link" size="sm" className="px-0" data-testid="po-detail-open-ar"
            onClick={() => onNavigate?.('maklon-billing', { po_id: po.id })}>Buka Piutang Klien</Button>
        )}
        <Button type="button" variant="link" size="sm" className="px-0" onClick={() => onNavigate?.('prod-cmt-billing', { po_id: po.id })}>Buka Tagihan CMT</Button>
      </div>
      <Section title={`Tagihan CMT (${bills.length})`} testId="po-detail-cmt-bills" unduh={{ namaBerkas: `tagihan-cmt-${po.po_number}`, baris: bills, kolom: [
        { label: 'No. tagihan', nilai: (b) => b.number || '' }, { label: 'CMT', nilai: (b) => b.vendor_name || '' },
        { label: 'Dari penerimaan', nilai: (b) => b.receipt_code || '' }, { label: 'Nilai', nilai: (b) => Number(b.amount) || 0 },
        { label: 'Dibayar', nilai: (b) => Number(b.paid) || 0 }, { label: 'Sisa', nilai: (b) => Number(b.outstanding) || 0 },
        { label: 'Status', nilai: (b) => b.status_label || '' },
      ] }}>
        {bills.length === 0 ? <Empty icon={Wallet} title="Belum ada tagihan CMT" description="Tagihan CMT terbentuk setelah barang lolos QC di Terima & QC." /> : (
          <Table>
            <TableHeader><TableRow><TableHead>No. tagihan</TableHead><TableHead>CMT</TableHead><TableHead>Dari penerimaan</TableHead><HeadNum>Nilai</HeadNum><HeadNum>Dibayar</HeadNum><HeadNum>Sisa</HeadNum><TableHead>Status</TableHead></TableRow></TableHeader>
            <TableBody>{bills.map(b => (
              <TableRow key={b.id}><TableCell className="tabular-nums">{b.number || '—'}</TableCell><TableCell>{b.vendor_name || '—'}</TableCell>
                <TableCell className="tabular-nums text-xs">{b.receipt_code || '—'}</TableCell><Num>{rp(b.amount)}</Num><Num>{rp(b.paid)}</Num><Num>{rp(b.outstanding)}</Num>
                <TableCell><StatusBadge status={b.status} label={b.status_label} tone={b.status === 'paid' ? 'success' : b.status === 'cancelled' ? 'danger' : 'info'} /></TableCell></TableRow>
            ))}</TableBody>
            <TableFooter><TableRow><TableCell colSpan={3} className="font-semibold">Total</TableCell>
              <Num className="font-semibold">{rp(bt.amount)}</Num><Num className="font-semibold">{rp(bt.paid)}</Num><Num className="font-semibold">{rp(bt.outstanding)}</Num><TableCell /></TableRow></TableFooter>
          </Table>
        )}
      </Section>
      {!isInternal && (
        <Section title="Piutang klien" testId="po-detail-client-ar">
          {!ar ? <Empty icon={Wallet} title="Piutang klien belum terbentuk" description="Piutang terjadwal dibuat saat PO dikonfirmasi." /> : (
            <Table>
              <TableHeader><TableRow><TableHead>No. piutang</TableHead><HeadNum>Terjadwal</HeadNum><HeadNum>Tertagih</HeadNum><HeadNum>Dibayar</HeadNum><HeadNum>Sisa</HeadNum></TableRow></TableHeader>
              <TableBody><TableRow>
                <TableCell className="tabular-nums">{ar.number || '—'}</TableCell><Num>{rp(ar.scheduled_total)}</Num><Num>{rp(ar.billed_total)}</Num>
                <Num>{rp(ar.paid_total)}</Num><Num>{rp(ar.amount_due)}</Num>
              </TableRow></TableBody>
            </Table>
          )}
        </Section>
      )}
    </>
  );
}

// ── Sampel (maklon) ───────────────────────────────────────────────────────────────────────────────────
function SamplesTab({ po, detail, canEdit, onReload }) {
  const samples = detail.samples || [];
  const [open, setOpen] = useState({});
  const [form, setForm] = useState(null);       // null | {} (baru) | sampel (ubah)
  const [reason, setReason] = useState(null);   // { kind: 'revision'|'reject', sample }
  const act = async (fn, okMsg) => {
    try { await fn(); toast.success(okMsg); await onReload(); }
    catch (e) { toast.error(e.message || 'Aksi sampel gagal'); }
  };
  const approve = async (s) => {
    if (!(await confirmDialog({ title: `Setujui sampel ${s.sample_code}?`, body: 'Gunakan bila klien sudah menyetujui (mis. lewat telepon). Sampel yang disetujui tidak bisa diubah lagi.', confirmLabel: 'Setujui' }))) return;
    act(() => apiPost(`/dewi/maklon/samples/${s.id}/approve`, {}), 'Sampel disetujui');
  };
  const submit = async (s) => {
    if (!(await confirmDialog({ title: `Kirim sampel ${s.sample_code} ke klien?`, body: 'Klien mendapat pemberitahuan dan bisa menyetujui atau meminta revisi di Portal Klien.', confirmLabel: 'Kirim ke klien' }))) return;
    act(() => apiPost(`/dewi/maklon/samples/${s.id}/submit`, {}), 'Sampel dikirim ke klien');
  };
  const remove = async (s) => {
    if (!(await confirmDialog({ title: `Hapus sampel ${s.sample_code}?`, body: 'Sampel dan riwayat revisinya terhapus.', confirmLabel: 'Hapus', danger: true }))) return;
    act(() => apiDelete(`/dewi/maklon/samples/${s.id}`), 'Sampel dihapus');
  };
  return (
    <Section title={`Sampel (${samples.length})`} testId="po-detail-samples"
      unduh={{ namaBerkas: `sampel-${po.po_number}`, baris: samples, kolom: [
        { label: 'Kode', nilai: (x) => x.sample_code }, { label: 'Produk', nilai: (x) => x.product_name || '' },
        { label: 'Ukuran', nilai: (x) => x.target_size || '' }, { label: 'Qty', nilai: (x) => Number(x.sample_qty) || 0 },
        { label: 'Revisi', nilai: (x) => Number(x.revision_number) || 0 }, { label: 'Status', nilai: (x) => x.status_label || '' },
        { label: 'Diperbarui', nilai: (x) => dt(x.updated_at || x.created_at) },
      ] }}
      aside={canEdit && (
        <Button type="button" variant="outline" size="sm" onClick={() => setForm({})} data-testid="sample-create-btn"><Plus className="w-3.5 h-3.5" /> Buat sampel</Button>
      )}>
      <p className="text-xs text-muted-foreground">Sampel dibuat sesudah PO ada. Riwayatnya juga tampil di artikel Katalog Buyer. Sampel belum disetujui hanya peringatan — kiriman tetap jalan.</p>
      {samples.length === 0 ? (
        <Empty icon={Clipboard} title="Belum ada sampel untuk PO ini" description="Klik Buat sampel, lalu kirim ke klien untuk disetujui." testId="samples-empty" />
      ) : (
        <Table data-testid="samples-table">
          <TableHeader><TableRow>
            <TableHead className="w-10" /><TableHead>Kode</TableHead><TableHead>Produk</TableHead><TableHead>Ukuran · qty</TableHead>
            <HeadNum>Revisi</HeadNum><TableHead>Status</TableHead><TableHead>Diperbarui</TableHead><TableHead className="text-right">Aksi</TableHead>
          </TableRow></TableHeader>
          <TableBody>{samples.map(s => [
            <TableRow key={s.id} data-testid={`sample-row-${s.sample_code}`}>
              <TableCell><RowToggle open={!!open[s.id]} onClick={() => setOpen(o => ({ ...o, [s.id]: !o[s.id] }))} testId={`sample-toggle-${s.sample_code}`} /></TableCell>
              <TableCell className="tabular-nums">{s.sample_code}</TableCell>
              <TableCell><div className="font-medium">{s.product_name}</div>{s.buyer_catalog_snapshot?.artikel_code && <div className="text-xs text-muted-foreground tabular-nums">{s.buyer_catalog_snapshot.artikel_code}</div>}</TableCell>
              <TableCell className="text-xs">{s.target_size || '—'} · {n(s.sample_qty)} pcs</TableCell>
              <Num>{n(s.revision_number)}</Num>
              <TableCell><StatusBadge status={s.status} label={s.status_label} tone={SAMPLE_TONE[s.status] || 'default'} testId={`sample-status-${s.sample_code}`} /></TableCell>
              <TableCell className="text-xs">{dt(s.updated_at || s.created_at)}</TableCell>
              <TableCell>
                {canEdit && (
                  <div className="flex justify-end gap-1">
                    {s.can?.edit && <Button type="button" size="icon-sm" variant="ghost" onClick={() => setForm(s)} title="Ubah sampel" aria-label="Ubah sampel" data-testid={`sample-edit-${s.sample_code}`}><Edit2 className="w-3.5 h-3.5" /></Button>}
                    {s.can?.submit && <Button type="button" size="icon-sm" variant="ghost" onClick={() => submit(s)} title="Kirim ke klien" aria-label="Kirim ke klien" data-testid={`sample-submit-${s.sample_code}`}><Send className="w-3.5 h-3.5" /></Button>}
                    {(s.can?.approve || s.can?.revision || s.can?.reject || s.can?.delete) && (
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button type="button" size="icon-sm" variant="ghost" title="Aksi lainnya" aria-label="Aksi lainnya" data-testid={`sample-more-${s.sample_code}`}><MoreHorizontal className="w-3.5 h-3.5" /></Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          {s.can?.approve && <DropdownMenuItem onSelect={() => approve(s)} data-testid={`sample-approve-${s.sample_code}`}><CheckCircle2 className="mr-2 h-4 w-4" />Setujui</DropdownMenuItem>}
                          {s.can?.revision && <DropdownMenuItem onSelect={() => setReason({ kind: 'revision', sample: s })} data-testid={`sample-revise-${s.sample_code}`}><RotateCcw className="mr-2 h-4 w-4" />Minta revisi</DropdownMenuItem>}
                          {s.can?.reject && <DropdownMenuItem onSelect={() => setReason({ kind: 'reject', sample: s })} data-testid={`sample-reject-${s.sample_code}`}><XCircle className="mr-2 h-4 w-4" />Tolak</DropdownMenuItem>}
                          {s.can?.delete && (
                            <>
                              <DropdownMenuSeparator />
                              <DropdownMenuItem onSelect={() => remove(s)} data-testid={`sample-delete-${s.sample_code}`}
                                className="text-[hsl(var(--danger-text))] focus:text-[hsl(var(--danger-text))]"><Trash2 className="mr-2 h-4 w-4" />Hapus sampel</DropdownMenuItem>
                            </>
                          )}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    )}
                  </div>
                )}
              </TableCell>
            </TableRow>,
            open[s.id] && (
              <RowDetail key={`${s.id}-d`} colSpan={8} testId={`sample-detail-${s.sample_code}`}>
                <div className="space-y-3">
                  <Facts items={[
                    ['Kain', s.fabric_used], ['Warna', s.color_used], ['Deskripsi', s.description], ['Catatan', s.notes],
                    ['Dikirim ke klien', s.submitted_at ? formatDateTimeID(s.submitted_at) : ''],
                    ['Disetujui', s.approved_at ? `${s.approved_by_name || ''} · ${dt(s.approved_at)}${s.approval_feedback ? ` — ${s.approval_feedback}` : ''}` : ''],
                    ['Ditolak', s.rejected_at ? `${s.rejected_by_name || ''} · ${s.rejection_reason || ''}` : ''],
                    ['Dibuat oleh', s.created_by],
                  ]} />
                  {(s.revisions || []).length > 0 && (
                    <Table>
                      <TableHeader><TableRow><TableHead>Revisi</TableHead><TableHead>Tanggal</TableHead><TableHead>Alasan</TableHead><TableHead>Perubahan</TableHead><TableHead>Diminta oleh</TableHead></TableRow></TableHeader>
                      <TableBody>{s.revisions.map(r => (
                        <TableRow key={r.id}><TableCell>#{r.revision_number}</TableCell><TableCell>{dt(r.created_at)}</TableCell><TableCell>{r.reason}</TableCell>
                          <TableCell>{r.changes_required || '—'}</TableCell><TableCell>{r.requested_by_role === 'client' ? `Klien · ${r.requested_by || ''}` : (r.requested_by || '—')}</TableCell></TableRow>
                      ))}</TableBody>
                    </Table>
                  )}
                  <FileAttachmentPanel entityType="maklon_sample" entityId={s.id} />
                </div>
              </RowDetail>
            ),
          ])}</TableBody>
        </Table>
      )}
      {form && <SampleFormDialog po={po} sample={form.id ? form : null} onClose={() => setForm(null)} onSaved={async () => { setForm(null); await onReload(); }} />}
      {reason && (
        <ReasonDialog kind={reason.kind} sample={reason.sample} onClose={() => setReason(null)}
          onDone={async () => { setReason(null); await onReload(); }} />
      )}
    </Section>
  );
}

function SampleFormDialog({ po, sample, onClose, onSaved }) {
  const isEdit = !!sample;
  const [f, setF] = useState(() => ({
    product_name: sample?.product_name || '', buyer_catalog_id: sample?.buyer_catalog_id || '',
    target_size: sample?.target_size || 'M', sample_qty: sample?.sample_qty || 1, fabric_used: sample?.fabric_used || '',
    color_used: sample?.color_used || '', description: sample?.description || '', notes: sample?.notes || '',
  }));
  const [catalogs, setCatalogs] = useState([]);
  const [code, setCode] = useState('');
  const [saving, setSaving] = useState(false);
  const policy = useDocNumberPolicy(isEdit ? null : 'dewi_maklon_samples.sample_code', localStorage.getItem('erp_token'), { ORDER: po.po_number });
  const set = (k, v) => setF(p => ({ ...p, [k]: v }));
  useEffect(() => {
    if (!po.buyer_id) return;
    apiGet(`/dewi/maklon/buyer-catalog?client_id=${po.buyer_id}&status=active`)
      .then(d => setCatalogs(Array.isArray(d) ? d : (d?.items || []))).catch(() => setCatalogs([]));
  }, [po.buyer_id]);
  // artikel yang dipakai PO ini ditaruh paling atas
  const poCats = new Set((po.items || []).map(i => i.catalog_item_id).filter(Boolean));
  const sorted = [...catalogs].sort((a, b) => Number(poCats.has(b.id)) - Number(poCats.has(a.id)));
  const pickCatalog = (id) => {
    const c = catalogs.find(x => x.id === id);
    setF(p => ({ ...p, buyer_catalog_id: id,
      product_name: p.product_name?.trim() || c?.product_name || c?.artikel_code || '',
      color_used: p.color_used?.trim() || c?.color_options?.[0] || '' }));
  };
  const save = async () => {
    if (!f.product_name.trim() && !f.buyer_catalog_id) { toast.error('Isi nama produk sampel atau pilih artikel katalog.'); return; }
    setSaving(true);
    const payload = { ...f, buyer_catalog_id: f.buyer_catalog_id || null, sample_qty: Number(f.sample_qty) || 1 };
    try {
      if (isEdit) await apiPut(`/dewi/maklon/samples/${sample.id}`, payload);
      else await apiPost('/dewi/maklon/samples', { ...payload, po_id: po.id, ...docNumberPayload(policy, 'sample_code', code) });
      toast.success(isEdit ? 'Sampel diperbarui' : 'Sampel dibuat');
      onSaved();
    } catch (e) { toast.error(e.message || 'Gagal menyimpan sampel'); }
    finally { setSaving(false); }
  };
  return (
    <FormPopup open onClose={onClose} ukuran="panjang" testId="sample-dialog" onSimpan={save} menyimpan={saving}
      judul={isEdit ? `Ubah sampel ${sample.sample_code}` : `Sampel baru · PO ${po.po_number}`}
      keterangan="Foto sampel diunggah dari rincian baris sampel (Lampiran) setelah disimpan."
      labelSimpan={isEdit ? 'Simpan' : 'Buat sampel'}>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Isian label="Artikel katalog buyer (opsional)" htmlFor="sample-catalog" className="sm:col-span-2">
          <SmartNativeSelect id="sample-catalog" className="w-full" value={f.buyer_catalog_id} onChange={e => pickCatalog(e.target.value)} data-testid="sample-catalog-select">
            <option value="">Tanpa tautan katalog</option>
            {sorted.map(c => <option key={c.id} value={c.id}>{c.artikel_code} — {c.product_name}{poCats.has(c.id) ? ' (di PO ini)' : ''}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Nama produk sampel" wajib className="sm:col-span-2"><GlassInput value={f.product_name} onChange={e => set('product_name', e.target.value)} data-testid="sample-product-name-input" /></Isian>
        <Isian label="Ukuran"><GlassInput value={f.target_size} onChange={e => set('target_size', e.target.value)} data-testid="sample-size-input" /></Isian>
        <Isian label="Qty sampel"><GlassInput type="number" min="1" value={f.sample_qty} onChange={e => set('sample_qty', e.target.value)} data-testid="sample-qty-input" /></Isian>
        <Isian label="Kain"><GlassInput value={f.fabric_used} onChange={e => set('fabric_used', e.target.value)} placeholder="Contoh: rayon" /></Isian>
        <Isian label="Warna"><GlassInput value={f.color_used} onChange={e => set('color_used', e.target.value)} placeholder="Contoh: navy" /></Isian>
        <Isian label="Deskripsi" className="sm:col-span-2"><Textarea rows={2} value={f.description} onChange={e => set('description', e.target.value)} /></Isian>
        <Isian label="Catatan" className="sm:col-span-2"><Textarea rows={2} value={f.notes} onChange={e => set('notes', e.target.value)} data-testid="sample-notes-input" /></Isian>
        {!isEdit && <div className="sm:col-span-2"><DocNumberField policy={policy} value={code} onChange={setCode} testId="sample-docnum" label="Kode sampel" /></div>}
      </div>
    </FormPopup>
  );
}

function ReasonDialog({ kind, sample, onClose, onDone }) {
  const [reason, setReason] = useState('');
  const [changes, setChanges] = useState('');
  const [saving, setSaving] = useState(false);
  const isRev = kind === 'revision';
  const submit = async () => {
    if (!reason.trim()) { toast.error(isRev ? 'Alasan revisi wajib diisi' : 'Alasan penolakan wajib diisi'); return; }
    setSaving(true);
    try {
      await apiPost(`/dewi/maklon/samples/${sample.id}/${isRev ? 'revision' : 'reject'}`, { reason, changes_required: changes });
      toast.success(isRev ? 'Permintaan revisi dicatat' : 'Sampel ditolak');
      onDone();
    } catch (e) { toast.error(e.message || 'Gagal'); }
    finally { setSaving(false); }
  };
  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId={`sample-${kind}-dialog`} onSimpan={submit} menyimpan={saving}
      judul={isRev ? `Minta revisi ${sample.sample_code}` : `Tolak sampel ${sample.sample_code}`}
      labelSimpan={isRev ? 'Minta revisi' : 'Tolak sampel'} warnaSimpan={isRev ? 'success' : 'destructive'}>
      <Isian label={isRev ? 'Alasan revisi' : 'Alasan penolakan'} wajib>
        <Textarea rows={2} value={reason} onChange={e => setReason(e.target.value)} data-testid="sample-reason-input" />
      </Isian>
      <Isian label="Perubahan yang diminta">
        <Textarea rows={3} value={changes} onChange={e => setChanges(e.target.value)} />
      </Isian>
    </FormPopup>
  );
}

// ── Riwayat ───────────────────────────────────────────────────────────────────────────────────────────
function TimelineTab({ timeline }) {
  const events = timeline?.events || [];
  const pg = useClientPagination(events, 25);
  if (!timeline) return <p className="text-sm text-muted-foreground">Memuat riwayat…</p>;
  if (!events.length) return <Empty icon={History} title="Belum ada riwayat untuk PO ini" description="Perubahan PO, kiriman, penerimaan, dan sampel tercatat di sini." />;
  return (
    <Section title={`Riwayat (${events.length} kejadian)`} testId="po-detail-timeline" unduh={{ namaBerkas: 'riwayat-po', baris: events, kolom: [
      { label: 'Waktu', nilai: (e) => formatDateTimeID(e.when) }, { label: 'Kejadian', nilai: (e) => e.label || '' },
      { label: 'Nilai', nilai: (e) => (e.amount ? Number(e.amount) : '') }, { label: 'Oleh', nilai: (e) => e.actor || '' },
      { label: 'Keterangan', nilai: (e) => e.note || '' },
    ] }}>
      <Table data-testid="po-detail-timeline-table">
        <TableHeader><TableRow><TableHead>Waktu</TableHead><TableHead>Kejadian</TableHead><TableHead>Oleh</TableHead><TableHead>Keterangan</TableHead></TableRow></TableHeader>
        <TableBody>{pg.paged.map((e, i) => (
          <TableRow key={`${e.when}-${i}`}>
            <TableCell className="text-xs whitespace-nowrap">{formatDateTimeID(e.when)}</TableCell>
            <TableCell>{e.label}{e.amount ? ` · ${rp(e.amount)}` : ''}</TableCell>
            <TableCell className="text-xs">{e.actor || '—'}</TableCell>
            <TableCell className="text-xs text-muted-foreground">{e.note || '—'}</TableCell>
          </TableRow>
        ))}</TableBody>
      </Table>
      {pg.total > pg.pageSize && <PaginationLite page={pg.page} totalPages={pg.totalPages} total={pg.total} pageSize={pg.pageSize} onPageChange={pg.setPage} />}
    </Section>
  );
}

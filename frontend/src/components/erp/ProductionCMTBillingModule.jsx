/**
 * ProductionCMTBillingModule — "Tagihan vendor CMT" (Portal Produksi / Maklon).
 *
 * Alur uang keluar ke vendor CMT: Terima FG dari CMT (lolos QC) → tagihan matang di `dewi_cmt_payments`
 * → jurnal `cmt_ap_invoice` (Dr biaya CMT / Cr hutang vendor) → dibayar dari rekening kas/bank.
 *
 * 2026-11-06 (Tahap 2, keputusan owner):
 *   • Hutang CMT TERJADWAL sejak PO maklon dikonfirmasi (qty × upah CMT per vendor) — tampilan
 *     "Jadwal hutang per PO".
 *   • Tagihan hanya bisa dibayar sampai nilai lolos QC − sudah dibayar: "bisa dibayar Rp X dari Rp Y".
 *   • Bagian selisih yang ditandai (lebih tagih) DITAHAN sampai Keuangan memutuskan: potong dari tagihan
 *     atau bayar penuh (`/resolve-variance`).
 *   • PANDUAN_UI: PageLayout · detail tagihan dibuka di halaman (DetailPanel), bukan popup.
 *
 *   - baca    : GET /api/production/cmt-billing[/summary|/vendors|/schedules|/{id}]
 *   - posting : POST /api/dewi/maklon/finance/cmt-payments/{id}/post-ap
 *   - bayar   : POST /api/dewi/maklon/finance/cmt-payments/{id}/pay
 *   - selisih : POST /api/dewi/maklon/finance/cmt-payments/{id}/resolve-variance
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { RefreshCw, Search, Receipt, AlertTriangle, CheckCircle2, Landmark, X } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Input } from '@/components/ui/input';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DatePicker from '@/components/ui/date-picker';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import { apiFetch, apiGet, apiPost } from '../../lib/api';
import StaffEntryBadge from './engine/StaffEntryBadge';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { MoneyInput } from '@/components/ui/money-input';
import { todayWIB } from '@/lib/waktu';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PageLayout, { DetailPanel } from './layout/PageLayout';
import { PageLayoutSatuBaris } from './engine/DataTable';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';
import { formatDateID } from '@/lib/format';
import { checkPerm } from '@/lib/rbac';

const fmtRp = (v) => `Rp ${Number(v || 0).toLocaleString('id-ID')}`;
const fmtNum = (v) => Number(v || 0).toLocaleString('id-ID');
const fmtDate = (d) => (d ? formatDateID(d) : '—');
const STATUS = {
  draft: ['Draf', 'muted'], submitted: ['Diajukan', 'info'], approved: ['Disetujui', 'info'],
  posted: ['Terjurnal', 'info'], partial_paid: ['Dibayar sebagian', 'warning'], paid: ['Lunas', 'success'],
  cancelled: ['Dibatalkan', 'muted'], terjadwal: ['Terjadwal', 'info'], berjalan: ['Berjalan', 'warning'],
  lunas: ['Lunas', 'success'],
};
const StatusPill = ({ status }) => {
  const [label, tone] = STATUS[(status || '').toLowerCase()] || [status || 'Draf', 'default'];
  return <StatusBadge status={label} tone={tone} />;
};
const FIN_ROLES = ['superadmin', 'admin', 'owner', 'accounting', 'staff_keuangan', 'manager_keuangan'];

export default function ProductionCMTBillingModule({ portalId, userRole, user }) {
  const businessType = portalId === 'maklon' ? 'maklon' : portalId === 'production' ? 'internal' : null;
  const [view, setView] = useState('bills');           // bills | schedules
  const [rows, setRows] = useState([]);
  const [schedules, setSchedules] = useState({ items: [], totals: {} });
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [partnerId, setPartnerId] = useState('');
  const [vendorOpts, setVendorOpts] = useState([]);
  const [detail, setDetail] = useState(null);
  const [posting, setPosting] = useState('');
  // 2026-11-08: + izin finance.manage (sama dengan server: selisih tagihan CMT `FINANCE_BOOK_PERMS`).
  const canPost = checkPerm({ user, role: userRole, roles: FIN_ROLES, keys: ['finance.manage'] });

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const qs = new URLSearchParams();
      if (businessType) qs.append('business_type', businessType);
      if (status) qs.append('status', status);
      if (search.trim()) qs.append('search', search.trim());
      if (partnerId) qs.append('partner_id', partnerId);
      const sq = new URLSearchParams();
      if (partnerId) sq.append('partner_id', partnerId);
      const [list, sum, sch] = await Promise.all([
        apiGet(`/production/cmt-billing?${qs}`),
        apiGet(`/production/cmt-billing/summary?${qs}`),
        businessType === 'internal' ? Promise.resolve({ items: [], totals: {} }) : apiGet(`/production/cmt-billing/schedules?${sq}`),
      ]);
      setRows(Array.isArray(list?.items) ? list.items : []);
      setSummary(sum);
      setSchedules(sch || { items: [], totals: {} });
    } catch (e) {
      setError(e?.message || 'Gagal memuat tagihan CMT');
      setRows([]); setSummary(null);
    } finally {
      setLoading(false);
    }
  }, [businessType, status, search, partnerId]);

  const loadVendors = useCallback(async () => {
    try {
      const qs = new URLSearchParams();
      if (businessType) qs.append('business_type', businessType);
      const res = await apiGet(`/production/cmt-billing/vendors?${qs}`);
      setVendorOpts(Array.isArray(res?.vendors) ? res.vendors : []);
    } catch { setVendorOpts([]); }
  }, [businessType]);

  useEffect(() => { load(); }, [businessType, status, partnerId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { loadVendors(); }, [loadVendors]);

  const openDetail = useCallback(async (id) => {
    setDetail({ loading: true, id });
    try { setDetail(await apiGet(`/production/cmt-billing/${id}`)); }
    catch (e) { toast.error(`Gagal memuat detail: ${e?.message || e}`); setDetail(null); }
  }, []);

  const postToGl = async (id) => {
    setPosting(id);
    try {
      const r = await apiPost(`/dewi/maklon/finance/cmt-payments/${id}/post-ap`, {});
      toast.success(r?.already_posted ? `Sudah pernah dijurnal (${r?.je_number || '-'})` : `Jurnal ${r?.je_number || ''} tercatat`);
      await load();
      if (detail?.bill?.id === id) await openDetail(id);
    } catch (e) { toast.error(`Jurnal gagal: ${e?.message || e}`); }
    finally { setPosting(''); }
  };

  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(rows, 25);
  const totals = useMemo(() => rows.reduce((t, r) => ({
    payable: t.payable + Number(r.payable_amount || 0),
    blocked: t.blocked + Number(r.blocked_amount || 0),
  }), { payable: 0, blocked: 0 }), [rows]);
  const resetFilters = () => { setPartnerId(''); setStatus(''); setSearch(''); };
  const filtered = partnerId || status || search.trim();

  return (
    <PageLayoutSatuBaris
      testId="prod-cmt-billing"
      title="Tagihan CMT"
      subtitle="Hutang jasa jahit ke vendor CMT: terjadwal sejak PO dikonfirmasi, matang saat barang lolos QC, lalu dibayar."
      filters={<>
        {businessType !== 'internal' && (
          <FilterChips value={view} onChange={setView} testId="cmt-billing-view" ariaLabel="Tampilan" hideWhenEmpty={false}
            options={[{ key: 'bills', label: 'Tagihan', count: rows.length },
              { key: 'schedules', label: 'Jadwal hutang per PO', count: (schedules.items || []).length }]} />
        )}
        <div className="relative w-full sm:w-64">
          <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') load(); }} placeholder="Cari tagihan, vendor, PO (Enter)"
            className="pl-8" data-testid="cmt-billing-search" />
        </div>
        <SmartNativeSelect value={status} onChange={(e) => setStatus(e.target.value)} className="w-44" data-testid="cmt-billing-status-filter" aria-label="Status">
          <option value="">Semua status</option>
          <option value="draft">Draf</option>
          <option value="posted">Terjurnal</option>
          <option value="partial_paid">Dibayar sebagian</option>
          <option value="paid">Lunas</option>
          <option value="cancelled">Dibatalkan</option>
        </SmartNativeSelect>
        {vendorOpts.length > 0 && (
          <SmartNativeSelect value={partnerId} onChange={(e) => setPartnerId(e.target.value)} className="w-56"
            data-testid="cmt-billing-vendor-filter" aria-label="Vendor CMT">
            <option value="">Semua vendor CMT ({vendorOpts.length})</option>
            {vendorOpts.map((v) => (
              <option key={v.vendor_id || v.vendor_name} value={v.vendor_id}>
                {v.vendor_name}{v.vendor_code ? ` (${v.vendor_code})` : ''} — {v.bills} tagihan{v.outstanding > 0 ? ` · sisa ${fmtRp(v.outstanding)}` : ' · lunas'}
              </option>
            ))}
          </SmartNativeSelect>
        )}
        {filtered && (
          <Button type="button" variant="outline" onClick={resetFilters} data-testid="cmt-billing-reset"><X className="h-3.5 w-3.5" />Reset filter</Button>
        )}
      </>}
      tools={<>
        {/* Standar UI/UX v2: unduh Excel/CSV tampilan aktif (semua baris hasil saringan dari server). */}
        {view === 'schedules' ? (
          <TombolUnduh namaBerkas="jadwal-hutang-cmt" baris={schedules.items || []} testId="cmt-billing-unduh" kolom={[
            { label: 'PO', nilai: (s) => s.po_number || '' }, { label: 'Vendor CMT', nilai: (s) => s.vendor_name || '' },
            { label: 'Jadwal (Rp)', nilai: (s) => Number(s.scheduled_amount) || 0 }, { label: 'Jadwal (pcs)', nilai: (s) => Number(s.scheduled_qty) || 0 },
            { label: 'Lolos QC (Rp)', nilai: (s) => Number(s.matured_amount) || 0 }, { label: 'Dibayar (Rp)', nilai: (s) => Number(s.paid_amount) || 0 },
            { label: 'Tertahan (Rp)', nilai: (s) => Number(s.blocked_amount) || 0 }, { label: 'Bisa dibayar (Rp)', nilai: (s) => Number(s.payable_amount) || 0 },
            { label: 'Status', nilai: (s) => s.status_label || s.status || '' },
          ]} />
        ) : (
          <TombolUnduh namaBerkas="tagihan-cmt" baris={rows} testId="cmt-billing-unduh" kolom={[
            { label: 'Kode', nilai: (r) => r.payment_code || '' }, { label: 'Vendor CMT', nilai: (r) => r.cmt_name || '' },
            { label: 'PO', nilai: (r) => r.po_number || r.source_receipt_code || '' }, { label: 'Pcs', nilai: (r) => Number(r.total_pcs) || 0 },
            { label: 'Nilai (Rp)', nilai: (r) => Number(r.amount) || 0 }, { label: 'Bisa dibayar (Rp)', nilai: (r) => Number(r.payable_amount) || 0 },
            { label: 'Tertahan (Rp)', nilai: (r) => Number(r.blocked_amount) || 0 },
            { label: 'Selisih belum selesai (pcs)', nilai: (r) => Number(r.variance_unresolved_qty) || 0 },
            { label: 'Status', nilai: (r) => r.status || '' }, { label: 'Jurnal', nilai: (r) => (r.gl_posted ? (r.gl_je_number || 'terjurnal') : 'Belum dijurnal') },
          ]} />
        )}
        <Button type="button" title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={load} data-testid="cmt-billing-refresh">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </>}
      summary={<>
        {error && <Notice tone="danger" icon={AlertTriangle} title="Gagal memuat data" testId="cmt-billing-error">{error}</Notice>}
        {(summary?.total_bills > 0) && (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <StatTile testId="cmt-kpi-nilai" label="Nilai tagihan (lolos QC)" value={fmtRp(summary?.total_amount)} sub={`${fmtNum(summary?.total_bills)} tagihan · ${fmtNum(summary?.total_pcs)} pcs`} />
            <StatTile testId="cmt-kpi-outstanding" label="Belum dibayar" value={fmtRp(summary?.outstanding_amount)} accent="warning" sub={`dibayar ${fmtRp(summary?.paid_amount)}`} />
            <StatTile testId="cmt-kpi-payable" label="Bisa dibayar sekarang" value={fmtRp(totals.payable)} sub="nilai lolos QC − dibayar − tertahan" />
            <StatTile testId="cmt-kpi-blocked" label="Tertahan (selisih)" value={fmtRp(totals.blocked)} accent={totals.blocked > 0 ? 'danger' : 'muted'} sub="menunggu keputusan Keuangan" />
          </div>
        )}
      </>}
      detail={detail && (
        <BillDetail detail={detail} canPost={canPost} posting={posting} onClose={() => setDetail(null)}
          onPost={postToGl} onChanged={async () => { await load(); await openDetail(detail.bill?.id || detail.id); }} />
      )}
      footer={view === 'bills' && rows.length > pageSize && (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />
      )}
    >
      <GlassCard className="p-0 overflow-x-auto">
        {view === 'schedules' ? (
          <>
            {/* Tahap 8 fase 2: PO maklon yang dijahit tim CV Sukma sendiri — tanpa tagihan & jadwal hutang CMT */}
            {(schedules.own_team_pos || []).length > 0 && (
              <div className="px-4 pt-3 text-sm space-y-1" data-testid="cmt-own-team-pos">
                {schedules.own_team_pos.map((o) => (
                  <p key={o.po_id}><b>{o.po_number}</b> · {o.vendor_name}: {o.message}</p>
                ))}
              </div>
            )}
            <ScheduleTable items={schedules.items || []} loading={loading} />
          </>
        ) : loading && !rows.length ? (
          <div className="p-4 text-sm text-muted-foreground"><RefreshCw className="w-4 h-4 animate-spin inline mr-2" />Memuat tagihan…</div>
        ) : (
          <Table>
            <TableHeader><TableRow>
              <TableHead>Kode</TableHead><TableHead>Vendor CMT</TableHead><TableHead>PO</TableHead>
              <TableHead className="text-right">Pcs</TableHead><TableHead className="text-right">Nilai</TableHead>
              <TableHead className="text-right">Bisa dibayar</TableHead><TableHead>Selisih</TableHead>
              <TableHead>Status</TableHead><TableHead>Jurnal</TableHead><TableHead className="text-right">Aksi</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {paged.length === 0 && (
                <TableRow data-testid="cmt-billing-empty" className="hover:bg-transparent">
                  <TableCell colSpan={10} className="p-0 [&>div]:py-8">
                    {filtered ? (
                      <EmptyState icon={Receipt} title="Tidak ada tagihan yang cocok dengan filter"
                        description="Ubah atau hapus penyaring untuk melihat tagihan lain."
                        action={<Button type="button" variant="outline" size="sm" onClick={resetFilters} data-testid="cmt-billing-empty-reset">Tampilkan semua tagihan</Button>} />
                    ) : (
                      <EmptyState icon={Receipt} title="Belum ada tagihan CMT"
                        description="Tagihan terbit otomatis setelah Terima FG dari CMT selesai QC." />
                    )}
                  </TableCell>
                </TableRow>
              )}
              {paged.map((r) => (
                <TableRow key={r.id} data-testid={`cmt-billing-row-${r.payment_code}`}
                  className={detail?.bill?.id === r.id ? 'bg-[hsl(var(--primary)/0.06)]' : ''}>
                  <TableCell className="whitespace-nowrap">
                    <Button type="button" variant="link" size="sm" className="h-auto p-0 font-semibold" onClick={() => openDetail(r.id)}
                      data-testid={`cmt-billing-detail-${r.payment_code}`}>{r.payment_code || r.id?.slice(0, 8)}</Button>
                  </TableCell>
                  <TableCell>
                    <span className="block">{r.cmt_name || '—'}</span>
                    {r.intercompany && <StatusBadge status="antar-cv" label="Antar CV" tone="info" testId={`cmt-billing-ic-${r.payment_code}`} />}
                    <StaffEntryBadge source={r.progress_entry_source} by={r.staff_entered_by} qty={r.staff_entered_progress_qty}
                      compact testId={`cmt-billing-entry-badge-${r.payment_code}`} />
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{r.po_number || r.source_receipt_code || '—'}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNum(r.total_pcs)}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtRp(r.amount)}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtRp(r.payable_amount)}</TableCell>
                  <TableCell className="text-xs" data-testid={`cmt-billing-variance-${r.payment_code}`}>
                    {Number(r.blocked_amount || 0) > 0 ? (
                      <span className="text-[hsl(var(--danger-text))]">tertahan {fmtRp(r.blocked_amount)}</span>
                    ) : Number(r.variance_unresolved_qty || 0) > 0 ? (
                      <span className="text-[hsl(var(--warning-text))]">{fmtNum(r.variance_unresolved_qty)} pcs belum selesai</span>
                    ) : r.variance_flagged && !r.variance_resolution ? (
                      <span className="text-[hsl(var(--warning-text))]">ditandai</span>
                    ) : <span className="text-muted-foreground">—</span>}
                  </TableCell>
                  <TableCell><StatusPill status={r.status} /></TableCell>
                  <TableCell className="text-xs">
                    {r.gl_posted ? <span className="text-[hsl(var(--success-text))]">{r.gl_je_number || 'terjurnal'}</span>
                      : <span className="text-[hsl(var(--warning-text))]">Belum dijurnal</span>}
                  </TableCell>
                  <TableCell className="text-right">
                    {!r.gl_posted && (r.status || '').toLowerCase() !== 'cancelled' && canPost ? (
                      <Button type="button" size="sm" variant="outline" disabled={posting === r.id} onClick={() => postToGl(r.id)} data-testid={`cmt-billing-post-${r.payment_code}`}>
                        <Landmark className="w-3.5 h-3.5" />Jurnalkan
                      </Button>
                    ) : (
                      <Button type="button" size="sm" variant="outline" onClick={() => openDetail(r.id)}>Rincian</Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </GlassCard>
    </PageLayoutSatuBaris>
  );
}

function ScheduleTable({ items, loading }) {
  if (loading && !items.length) return <div className="p-4 text-sm text-muted-foreground">Memuat jadwal…</div>;
  return (
    <Table data-testid="cmt-ap-schedules">
      <TableHeader><TableRow>
        <TableHead>PO</TableHead><TableHead>Vendor CMT</TableHead><TableHead className="text-right">Jadwal (qty × upah)</TableHead>
        <TableHead className="text-right">Lolos QC</TableHead><TableHead className="text-right">Dibayar</TableHead>
        <TableHead className="text-right">Tertahan</TableHead><TableHead>Bisa dibayar</TableHead><TableHead>Status</TableHead>
      </TableRow></TableHeader>
      <TableBody>
        {items.length === 0 && (
          <TableRow className="hover:bg-transparent">
            <TableCell colSpan={8} className="p-0 [&>div]:py-8">
              <EmptyState icon={Receipt} title="Belum ada jadwal hutang CMT"
                description="Jadwal lahir saat PO maklon dikonfirmasi: qty × upah CMT per vendor." />
            </TableCell>
          </TableRow>
        )}
        {items.map((s) => (
          <TableRow key={s.id}>
            <TableCell className="font-medium whitespace-nowrap">{s.po_number}</TableCell>
            <TableCell>{s.vendor_name || 'Vendor belum ditentukan'}</TableCell>
            <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtRp(s.scheduled_amount)} <span className="text-xs text-muted-foreground">· {fmtNum(s.scheduled_qty)} pcs</span></TableCell>
            <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtRp(s.matured_amount)}</TableCell>
            <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtRp(s.paid_amount)}</TableCell>
            <TableCell className="text-right tabular-nums whitespace-nowrap">
              {Number(s.blocked_amount || 0) > 0 ? <span className="text-[hsl(var(--danger-text))]">{fmtRp(s.blocked_amount)}</span> : fmtRp(0)}
            </TableCell>
            <TableCell className="whitespace-nowrap text-sm" data-testid={`cmt-ap-payable-${s.po_number}`}>
              Bisa dibayar <b className="tabular-nums">{fmtRp(s.payable_amount)}</b> dari <span className="tabular-nums">{fmtRp(Math.max(Number(s.scheduled_amount || 0), Number(s.matured_amount || 0)))}</span>
            </TableCell>
            <TableCell><StatusPill status={s.status} /></TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function BillDetail({ detail, canPost, posting, onClose, onPost, onChanged }) {
  const bill = detail.bill || {};
  const [cashAccounts, setCashAccounts] = useState([]);
  const [disbursements, setDisbursements] = useState([]);
  const [payForm, setPayForm] = useState({ cash_account_id: '', counter_cash_account_id: '', amount: '', payment_date: todayWIB(), reference_no: '' });
  const [busy, setBusy] = useState(false);
  // Tahap 8 (dua CV): tagihan CMT PO maklon dibayar dari rekening CV Sukma, PO internal dari rekening CV Dewi Aditya.
  const billCv = bill.business_type === 'maklon' ? 'SMU' : 'DA';
  // Tahap 8 fase 2: tagihan tim jahit CV Sukma = pembayaran ANTAR CV — rekening CV Sukma yang menerima ikut dipilih;
  // penerimaan di buku CV Sukma dibuat otomatis dengan nilai yang sama.
  const isIc = !!bill.intercompany;
  const [counterAccounts, setCounterAccounts] = useState([]);
  useEffect(() => {
    apiGet(`/rahaza/cash-accounts?entity=${billCv}`).then((d) => setCashAccounts(Array.isArray(d) ? d : [])).catch(() => {});
  }, [billCv]);
  useEffect(() => {
    if (!isIc) { setCounterAccounts([]); return; }
    apiGet('/rahaza/cash-accounts?entity=SMU').then((d) => setCounterAccounts(Array.isArray(d) ? d : [])).catch(() => {});
  }, [isIc]);
  const openIcPdf = async () => {
    try {
      const r = await apiFetch(`/rahaza/intercompany/documents/${bill.ic_ar_invoice_id}/pdf`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const url = URL.createObjectURL(await r.blob());
      window.open(url, '_blank', 'noopener');
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) { toast.error(`PDF gagal dibuka: ${e.message}`); }
  };
  useEffect(() => {
    if (!bill.id) { setDisbursements([]); return; }
    apiGet(`/dewi/maklon/finance/cmt-payments/${bill.id}/disbursements`).then((d) => setDisbursements(Array.isArray(d) ? d : [])).catch(() => {});
  }, [bill.id, bill.paid_amount]);
  if (detail.loading) {
    return <DetailPanel title="Memuat…" onClose={onClose} testId="cmt-billing-detail-dialog"><p className="text-sm text-muted-foreground">Memuat…</p></DetailPanel>;
  }
  const payable = Number(bill.payable_amount || 0);
  const blocked = Number(bill.blocked_amount || 0);
  const sched = detail.schedule;

  const pay = async () => {
    if (!payForm.cash_account_id) { toast.error('Pilih rekening kas/bank'); return; }
    if (isIc && !payForm.counter_cash_account_id) { toast.error('Pilih rekening CV Sukma yang menerima'); return; }
    setBusy(true);
    try {
      const r = await apiPost(`/dewi/maklon/finance/cmt-payments/${bill.id}/pay`, {
        cash_account_id: payForm.cash_account_id, amount: payForm.amount ? Number(payForm.amount) : null,
        payment_date: payForm.payment_date, reference_no: payForm.reference_no,
        ...(isIc ? { counter_cash_account_id: payForm.counter_cash_account_id } : {}),
      });
      if (r?.post_error) toast.warning(`Pembayaran dicatat, jurnal gagal: ${r.post_error}`);
      else if (r?.intercompany) toast.success(`Pembayaran antar CV dicatat · ${r?.gl_je_number || '-'} (CV Dewi Aditya) + ${r.intercompany.mirror?.je_number || '-'} (CV Sukma)`);
      else toast.success(`Pembayaran dicatat · ${r?.gl_je_number || '-'}`);
      setPayForm((f) => ({ ...f, amount: '', reference_no: '' }));
      await onChanged();
    } catch (e) { toast.error(e?.message || 'Pembayaran gagal'); }
    finally { setBusy(false); }
  };
  const resolve = async (decision) => {
    const notes = await confirmDialog({
      title: decision === 'potong' ? `Potong ${fmtRp(bill.overbilled_amount)} dari tagihan?` : 'Bayar tagihan ini penuh?',
      body: decision === 'potong'
        ? 'Nilai lebih tagih dikurangi dari tagihan dengan jurnal penyesuaian (jurnal lama tidak diubah).'
        : 'Selisih diterima — bagian yang tertahan boleh dibayar.',
      confirmLabel: decision === 'potong' ? 'Potong tagihan' : 'Bayar penuh',
      input: { label: 'Catatan keputusan', placeholder: 'mis. reject final, vendor setuju dipotong', minLength: 3 },
    });
    if (!notes) return;
    setBusy(true);
    try {
      await apiPost(`/dewi/maklon/finance/cmt-payments/${bill.id}/resolve-variance`, { decision, notes });
      toast.success('Selisih tagihan diselesaikan');
      await onChanged();
    } catch (e) { toast.error(e?.message || 'Gagal'); }
    finally { setBusy(false); }
  };
  const voidDisbursement = async (did) => {
    if (!(await confirmDialog({ title: 'Batalkan pembayaran ini?', body: 'Jurnal pembayaran ikut dibatalkan.',
      confirmLabel: 'Batalkan pembayaran', cancelLabel: 'Kembali', danger: true }))) return;
    try {
      await apiPost(`/dewi/maklon/finance/cmt-payments/${bill.id}/disbursements/${did}/void`, {});
      toast.success('Pembayaran dibatalkan, jurnal di-void');
      await onChanged();
    } catch (e) { toast.error(`Batal gagal: ${e?.message || e}`); }
  };

  return (
    <DetailPanel testId="cmt-billing-detail-dialog" closeTestId="cmt-billing-detail-close" onClose={onClose}
      title={`${bill.payment_code || 'Tagihan'} · ${bill.cmt_name || '—'}`}
      description={`PO ${bill.po_number || '—'} · ${fmtNum(bill.total_pcs)} pcs lolos QC · ditolak ${fmtNum(bill.total_rejected)} · nilai ${fmtRp(bill.amount)}`}
      actions={!bill.gl_posted && canPost && (bill.status || '').toLowerCase() !== 'cancelled' && (
        <Button type="button" variant="outline" onClick={() => onPost(bill.id)} disabled={posting === bill.id} data-testid="cmt-billing-detail-post">
          <Landmark className="w-4 h-4" />Jurnalkan
        </Button>
      )}>
      {isIc && (
        <Notice tone="info" icon={Landmark} testId="cmt-bill-ic"
          title="Tagihan antar CV — tim jahit CV Sukma"
          action={bill.ic_ar_invoice_id && <Button type="button" size="sm" variant="outline" onClick={openIcPdf} data-testid="cmt-bill-ic-pdf">Tagihan jasa jahit (PDF)</Button>}>
          Hutang CV Dewi Aditya ke CV Sukma. Piutang pasangannya di buku CV Sukma: {bill.ic_ar_invoice_number || 'belum dibuat'}.
          Pembayaran di sini otomatis dicatat sebagai penerimaan di rekening CV Sukma yang dipilih.
        </Notice>
      )}
      <p className="text-sm" data-testid="cmt-bill-payable">
        Bisa dibayar <b className="tabular-nums">{fmtRp(payable)}</b> dari <span className="tabular-nums">{fmtRp(bill.amount)}</span>
        {' '}(dibayar {fmtRp(bill.paid_amount)}{blocked > 0 ? `, tertahan ${fmtRp(blocked)}` : ''})
        {sched && <span className="text-muted-foreground"> · jadwal hutang PO ini ke vendor: {fmtRp(sched.scheduled_amount)}, bisa dibayar {fmtRp(sched.payable_amount)}</span>}
      </p>
      {bill.variance_flagged && (
        <Notice tone={blocked > 0 ? 'danger' : 'warning'} icon={AlertTriangle} testId="cmt-bill-variance-alert"
          title={bill.variance_resolution ? 'Selisih sudah diputuskan Keuangan' : blocked > 0 ? `Rp ${fmtNum(blocked)} tertahan — selisih perlu diputuskan Keuangan` : 'Ada selisih qty pada penerimaan'}
          action={canPost && !bill.variance_resolution && Number(bill.overbilled_amount || 0) > 0 && (
            <span className="flex gap-2">
              <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => resolve('potong')} data-testid="cmt-resolve-potong">Potong dari tagihan</Button>
              <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => resolve('bayar')} data-testid="cmt-resolve-bayar">Bayar penuh</Button>
            </span>
          )}>
          {(bill.variance_reasons || []).length > 0
            ? <ul className="text-xs list-disc pl-4">{bill.variance_reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
            : bill.variance_reason}
          {bill.variance_resolution && (
            <p className="text-xs mt-1">Keputusan: {bill.variance_resolution.decision === 'potong' ? 'dipotong' : 'dibayar penuh'} · {bill.variance_resolution.notes} · {bill.variance_resolution.by}</p>
          )}
        </Notice>
      )}
      {(bill.breakdown || []).length > 0 && (
        <Table>
          <TableHeader><TableRow><TableHead>Barang</TableHead><TableHead className="text-right">Diterima</TableHead>
            <TableHead className="text-right">Ditagih</TableHead><TableHead className="text-right">Upah</TableHead><TableHead className="text-right">Nilai</TableHead></TableRow></TableHeader>
          <TableBody>
            {bill.breakdown.map((b, i) => (
              <TableRow key={i}>
                <TableCell>{b.product_name || b.sku_code || b.sku || '—'}</TableCell>
                <TableCell className="text-right tabular-nums">{fmtNum(b.qty_actual)}</TableCell>
                <TableCell className="text-right tabular-nums">{fmtNum(b.qty_billed ?? b.qty_actual)}</TableCell>
                <TableCell className="text-right tabular-nums">{fmtRp(b.cmt_rate_per_pcs)}</TableCell>
                <TableCell className="text-right tabular-nums">{fmtRp(b.line_amount)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {detail.journal && (
        <p className="text-xs text-muted-foreground">
          Jurnal {detail.journal.je_number} · {fmtDate(detail.journal.date)} · {(detail.journal.lines || []).map((l) => `${l.account_code} ${l.debit ? 'D' : 'K'} ${fmtNum(l.debit || l.credit)}`).join(' · ')}
        </p>
      )}
      {!bill.gl_posted && bill.post_error && <Notice tone="danger" icon={AlertTriangle}>Jurnal belum tercatat: {bill.post_error}</Notice>}
      {disbursements.length > 0 && (
        <div className="space-y-1" data-testid="cmt-disbursements">
          {disbursements.map((d) => (
            <div key={d.id} className="flex items-center justify-between gap-2 text-sm" data-testid={`cmt-disb-${d.id}`}>
              <span>{fmtDate(d.payment_date)} · {d.cash_account_name} · <span className="tabular-nums">{fmtRp(d.amount)}</span>{d.gl_je_number ? ` · ${d.gl_je_number}` : ''}</span>
              {canPost && <Button type="button" size="sm" variant="outline" onClick={() => voidDisbursement(d.id)} data-testid={`cmt-disb-void-${d.id}`}>Batalkan</Button>}
            </div>
          ))}
        </div>
      )}
      {canPost && (bill.status || '').toLowerCase() !== 'cancelled' && payable > 0 && (
        <div className="flex flex-wrap items-end gap-2" data-testid="cmt-pay-panel">
          <SmartNativeSelect value={payForm.cash_account_id} onChange={(e) => setPayForm((f) => ({ ...f, cash_account_id: e.target.value }))}
            className="h-9 w-64" aria-label="Rekening" data-testid="cmt-pay-cash-account">
            <option value="">— Rekening kas/bank —</option>
            {cashAccounts.map((a) => <option key={a.id} value={a.id}>{a.name}{a.gl_account_code ? ` · ${a.gl_account_code}` : ''}</option>)}
          </SmartNativeSelect>
          {isIc && (
            <SmartNativeSelect value={payForm.counter_cash_account_id} onChange={(e) => setPayForm((f) => ({ ...f, counter_cash_account_id: e.target.value }))}
              className="h-9 w-64" aria-label="Rekening CV Sukma penerima" data-testid="cmt-pay-counter-account">
              <option value="">— Rekening CV Sukma penerima —</option>
              {counterAccounts.map((a) => <option key={a.id} value={a.id}>{a.name}{a.gl_account_code ? ` · ${a.gl_account_code}` : ''}</option>)}
            </SmartNativeSelect>
          )}
          <MoneyInput glass placeholder={`maks. ${fmtNum(payable)}`} value={payForm.amount} onChange={(e) => setPayForm((f) => ({ ...f, amount: e.target.value }))}
            className="h-9 w-40" data-testid="cmt-pay-amount" />
          <div className="w-44"><DatePicker value={payForm.payment_date} onChange={(v) => setPayForm((f) => ({ ...f, payment_date: v }))} placeholder="Tanggal bayar" testId="cmt-pay-date" /></div>
          <GlassInput placeholder="No. referensi" value={payForm.reference_no} onChange={(e) => setPayForm((f) => ({ ...f, reference_no: e.target.value }))} className="h-9 w-40" data-testid="cmt-pay-ref" />
          <Button type="button" variant="success" onClick={pay} disabled={busy} data-testid="cmt-pay-submit"><CheckCircle2 className="w-4 h-4" />Bayar vendor</Button>
        </div>
      )}
      {bill.notes && <p className="text-xs text-muted-foreground">{bill.notes}</p>}
    </DetailPanel>
  );
}

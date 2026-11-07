import { useState, useEffect } from 'react';
import { CheckCircle, XCircle, FileText, RefreshCw, ArrowRight, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Textarea } from '@/components/ui/textarea';
import { EmptyState, StatusBadge } from './moduleAtoms';
import PageLayout, { DetailPanel } from './layout/PageLayout';
import FilterChips from '@/components/ui/filter-chips';
import { toast } from 'sonner';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatRupiah } from '@/lib/format';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

/*
 * Persetujuan Perubahan Faktur (menu Keuangan).
 * 2026-11-05 (PANDUAN_UI G1/G8/G10/G13): cetakan PageLayout; status berbahasa Indonesia lewat StatusBadge (dulu
 * "Pending/Approved/Rejected" berwarna palet langsung); rincian permintaan dibuka DI HALAMAN di atas daftar
 * (dulu popup); tampilan kosong di kartu daftar (dulu teks berjarak besar di luar kartu → pita kosong 80 px).
 * 2026-11-08 (Standar UI/UX v2): rincian = popup (DetailPanel ber-onClose); daftar = TabelData (kartu ringkas di
 * HP) + unduh Excel/CSV; Setujui hijau / Tolak merah; item faktur sebelum/sesudah = tabel kecil, bukan kartu per item.
 */
const STATUS_META = {
  Pending: { label: 'Menunggu', tone: 'warning' },
  Approved: { label: 'Disetujui', tone: 'success' },
  Rejected: { label: 'Ditolak', tone: 'danger' },
};
const CATEGORY_LABEL = { VENDOR: 'Pemasok', CUSTOMER: 'Pelanggan' };

const fmt = formatRupiah;
const fmtDate = (d) => d ? new Date(d).toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '-';

function ReqStatus({ status }) {
  const m = STATUS_META[status];
  return <StatusBadge status={status} label={m?.label || status} tone={m?.tone || 'default'} />;
}

/** Satu pasang nilai sebelum → sesudah (netral; warna tidak dipakai sebagai hiasan — G8). */
function BeforeAfter({ label, before, after, big }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      <div className="rounded-[var(--radius-md)] border border-[var(--glass-border)] p-3">
        <p className="text-xs text-muted-foreground font-medium mb-1">Sebelum · {label}</p>
        <p className={`text-muted-foreground ${big ? 'text-lg font-semibold tabular-nums' : 'text-sm'}`}>{before}</p>
      </div>
      <div className="rounded-[var(--radius-md)] border border-[hsl(var(--primary)/0.4)] p-3">
        <p className="text-xs text-[hsl(var(--primary))] font-medium mb-1">Sesudah · {label}</p>
        <p className={`text-foreground ${big ? 'text-lg font-semibold tabular-nums' : 'text-sm'}`}>{after}</p>
      </div>
    </div>
  );
}

function ItemList({ title, items, tint }) {
  return (
    <div className={`rounded-[var(--radius-md)] border p-3 ${tint ? 'border-[hsl(var(--primary)/0.4)]' : 'border-[var(--glass-border)]'}`}>
      <p className={`text-xs font-medium mb-1 ${tint ? 'text-[hsl(var(--primary))]' : 'text-muted-foreground'}`}>{title} · {(items || []).length} item</p>
      <Table>
        <TableHeader><TableRow>
          <TableHead className="text-xs">Produk</TableHead>
          <TableHead className="text-xs text-right">Qty</TableHead>
          <TableHead className="text-xs text-right">Subtotal</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {(items || []).map((item, idx) => (
            <TableRow key={idx}>
              <TableCell>
                <p className="font-medium text-foreground">{item.product_name}</p>
                <p className="text-xs text-muted-foreground">{item.sku} · {item.size}/{item.color}</p>
              </TableCell>
              <TableCell className="text-right tabular-nums">{item.invoice_qty}</TableCell>
              <TableCell className="text-right tabular-nums whitespace-nowrap">{fmt(item.subtotal || 0)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export default function ApprovalModule({ token, userRole }) {
  const [requests, setRequests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState('Pending');
  const [searchQuery, setSearchQuery] = useState('');
  const [showDetail, setShowDetail] = useState(false);
  const [selectedRequest, setSelectedRequest] = useState(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [approvalNotes, setApprovalNotes] = useState('');

  const canApprove = ['superadmin', 'admin'].includes(userRole);

  useEffect(() => {
    fetchRequests();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterStatus]);

  const fetchRequests = async () => {
    setLoading(true);
    try {
      let url = '/api/invoice-edit-requests?';
      const params = [];
      if (filterStatus) params.push(`status=${filterStatus}`);
      if (searchQuery) params.push(`q=${encodeURIComponent(searchQuery)}`);
      const res = await fetch(url + params.join('&'), {
        headers: { Authorization: `Bearer ${token}` }
      });
      const data = await res.json();
      setRequests(Array.isArray(data) ? data : []);
    } catch (e) {
      console.error('Error fetching requests:', e);
      setRequests([]);
    } finally {
      setLoading(false);
    }
  };

  const openDetail = async (req) => {
    if (showDetail && selectedRequest?.id === req.id) { setShowDetail(false); return; }
    setSelectedRequest(req);
    setApprovalNotes('');
    setShowDetail(true);
  };

  const handleApprove = async () => {
    if (!selectedRequest) return;
    if (!(await confirmDialog(`Setujui perubahan faktur ${selectedRequest.invoice_number}?`))) return;
    setActionLoading(true);
    try {
      const res = await fetch(`/api/invoice-edit-requests/${selectedRequest.id}/approve`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ approval_notes: approvalNotes })
      });
      const data = await res.json();
      if (!res.ok) {
        toast.error(data.detail || data.error || data.message || 'Gagal menyetujui permintaan');
      } else {
        toast.success('Perubahan disetujui; faktur sudah diperbarui.');
        setShowDetail(false);
        fetchRequests();
      }
    } catch (e) {
      toast.error('Gagal: ' + e.message);
    } finally {
      setActionLoading(false);
    }
  };

  const handleReject = async () => {
    if (!selectedRequest) return;
    if (!approvalNotes.trim()) {
      toast.error('Alasan penolakan wajib diisi');
      return;
    }
    if (!(await confirmDialog(`Tolak perubahan faktur ${selectedRequest.invoice_number}?`))) return;
    setActionLoading(true);
    try {
      const res = await fetch(`/api/invoice-edit-requests/${selectedRequest.id}/reject`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ approval_notes: approvalNotes })
      });
      const data = await res.json();
      if (!res.ok) {
        toast.error(data.detail || data.error || data.message || 'Gagal menolak permintaan');
      } else {
        toast.success('Permintaan ditolak.');
        setShowDetail(false);
        fetchRequests();
      }
    } catch (e) {
      toast.error('Gagal: ' + e.message);
    } finally {
      setActionLoading(false);
    }
  };

  const compareField = (field, before, after) => {
    const beforeVal = before?.[field];
    const afterVal = after?.[field];
    if (JSON.stringify(beforeVal) === JSON.stringify(afterVal)) {
      return null; // No change
    }
    return { before: beforeVal, after: afterVal };
  };

  const renderComparison = () => {
    if (!selectedRequest) return null;
    const before = selectedRequest.before_snapshot || {};
    const after = selectedRequest.after_snapshot || {};

    const changes = [];

    const discountChange = compareField('discount', before, after);
    if (discountChange) {
      changes.push(<BeforeAfter key="discount" label="Diskon" before={fmt(discountChange.before)} after={fmt(discountChange.after)} />);
    }

    const notesChange = compareField('notes', before, after);
    if (notesChange) {
      changes.push(<BeforeAfter key="notes" label="Catatan" before={notesChange.before || '-'} after={notesChange.after || '-'} />);
    }

    const totalChange = compareField('total_amount', before, after);
    if (totalChange) {
      changes.push(<BeforeAfter key="total" label="Total" big before={fmt(totalChange.before)} after={fmt(totalChange.after)} />);
    }

    const itemsChange = compareField('invoice_items', before, after);
    if (itemsChange) {
      changes.push(
        <div key="items" className="space-y-3">
          <p className="font-semibold text-foreground">Perubahan item faktur</p>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <ItemList title="Sebelum" items={itemsChange.before} />
            <ItemList title="Sesudah" items={itemsChange.after} tint />
          </div>
        </div>
      );
    }

    return changes.length > 0 ? changes : <p className="text-muted-foreground text-sm text-center py-4">Tidak ada perubahan terdeteksi</p>;
  };

  const filtered = requests;

  const { page, setPage, totalPages, total, paged } = useClientPagination(filtered, 10);

  const detail = showDetail && selectedRequest && (
    <DetailPanel
      title={`Permintaan ubah faktur ${selectedRequest.invoice_number}`}
      description={selectedRequest.change_summary}
      onClose={() => setShowDetail(false)}
      testId="approval-detail-modal"
      actions={
        <Button
          variant="link"
          size="sm"
          onClick={() => {
            setShowDetail(false);
            toast.info(`Buka faktur ${selectedRequest.invoice_number} di menu Faktur untuk melihat isinya.`);
          }}
          data-testid="view-invoice-link"
        >
          <FileText className="w-3.5 h-3.5" /> Lihat faktur
        </Button>
      }
    >
      <div className="space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
          <div>
            <p className="text-xs text-muted-foreground">Status</p>
            <div className="mt-1"><ReqStatus status={selectedRequest.status} /></div>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Diajukan oleh</p>
            <p className="font-medium mt-0.5">{selectedRequest.requested_by_name}</p>
            <p className="text-xs text-muted-foreground">{selectedRequest.requested_by}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Waktu pengajuan</p>
            <p className="font-medium mt-0.5 whitespace-nowrap">{fmtDate(selectedRequest.requested_at)}</p>
          </div>
        </div>

        <div>
          <p className="font-semibold text-foreground mb-3 flex items-center gap-2">
            <ArrowRight className="w-4 h-4 text-muted-foreground" />
            Perbandingan sebelum &amp; sesudah
          </p>
          <div className="space-y-4">
            {renderComparison()}
          </div>
        </div>

        {/* Catatan keputusan (bila sudah disetujui/ditolak) */}
        {selectedRequest.status !== 'Pending' && selectedRequest.approval_notes && (
          <div className="text-sm">
            <p className="text-xs text-muted-foreground font-semibold mb-1">Catatan keputusan</p>
            <p className="text-foreground">{selectedRequest.approval_notes}</p>
            <p className="text-xs text-muted-foreground mt-1">
              Oleh: {selectedRequest.approved_by_name} pada {fmtDate(selectedRequest.approved_at)}
            </p>
          </div>
        )}

        {/* Setujui/Tolak (hanya untuk yang menunggu) */}
        {selectedRequest.status === 'Pending' && canApprove && (
          <div className="border-t border-[var(--glass-border)] pt-4 space-y-3 max-w-2xl">
            <label className="block text-sm font-medium text-foreground" htmlFor="approval-notes">Catatan (opsional untuk menyetujui, wajib untuk menolak)</label>
            <Textarea
              id="approval-notes"
              rows={3}
              value={approvalNotes}
              onChange={(e) => setApprovalNotes(e.target.value)}
              placeholder="Contoh: disetujui sesuai kesepakatan dengan pelanggan…"
              data-testid="approval-notes-textarea"
            />
            <div className="flex gap-2">
              <Button variant="success" onClick={handleApprove} disabled={actionLoading} data-testid="approve-button">
                <CheckCircle className="w-4 h-4" />
                {actionLoading ? 'Memproses…' : 'Setujui'}
              </Button>
              <Button variant="destructive" onClick={handleReject} disabled={actionLoading} data-testid="reject-button">
                <XCircle className="w-4 h-4" />
                {actionLoading ? 'Memproses…' : 'Tolak'}
              </Button>
            </div>
          </div>
        )}
      </div>
    </DetailPanel>
  );

  return (
    <PageLayout
      testId="approval-module"
      title="Persetujuan perubahan faktur"
      subtitle="Perubahan faktur yang diajukan admin; superadmin/admin menyetujui atau menolak."
      filters={<>
        <FilterChips value={filterStatus} onChange={setFilterStatus} testId="filter-status" ariaLabel="Status permintaan" hideWhenEmpty={false}
          options={[{ key: 'Pending', label: 'Menunggu' }, { key: 'Approved', label: 'Disetujui' }, { key: 'Rejected', label: 'Ditolak' }, { key: '', label: 'Semua' }]} />
        <div className="relative w-full sm:w-64">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <GlassInput
            type="text"
            placeholder="Cari no. faktur atau pengaju, lalu Enter"
            aria-label="Cari"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && fetchRequests()}
            className="h-9 pl-9"
            data-testid="approval-search-input"
          />
        </div>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="persetujuan-perubahan-faktur" namaLembar="Permintaan" baris={filtered} testId="approval-unduh"
          kolom={[
            { label: 'Status', nilai: (r) => STATUS_META[r.status]?.label || r.status },
            { label: 'No. faktur', nilai: (r) => r.invoice_number },
            { label: 'No. PO', nilai: (r) => r.po_number || '' },
            { label: 'Kategori', nilai: (r) => CATEGORY_LABEL[r.invoice_category] || r.invoice_category || '' },
            { label: 'Ringkasan perubahan', nilai: (r) => r.change_summary || '' },
            { label: 'Diajukan oleh', nilai: (r) => r.requested_by_name || r.requested_by || '' },
            { label: 'Waktu pengajuan', nilai: (r) => fmtDate(r.requested_at) },
            { label: 'Catatan keputusan', nilai: (r) => r.approval_notes || '' },
          ]} />
        <Button variant="outline" size="icon" onClick={fetchRequests} title="Muat ulang" aria-label="Muat ulang" data-testid="approval-refresh-button"><RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /></Button>
      </>}
      detail={detail}
    >
      {loading ? (
        <div className="flex items-center justify-center h-48" data-testid="approval-loading">
          <RefreshCw className="w-6 h-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <GlassCard className="p-0 overflow-hidden" data-testid="approval-list">
          {filtered.length === 0 ? (
            <EmptyState icon={FileText} testId="approval-empty"
              title={filterStatus === 'Pending' ? 'Tidak ada perubahan faktur yang menunggu' : 'Tidak ada permintaan perubahan faktur di sini'}
              description={searchQuery ? 'Ubah atau kosongkan pencarian.' : 'Permintaan muncul di sini setelah admin mengajukan perubahan faktur.'} />
          ) : (
            <>
              <TabelData baris={paged} kunci={(r) => r.id} onKlikBaris={openDetail} testId="approval-table"
                kolom={[
                  { kunci: 'status', label: 'Status', hp: 'nilai', isi: (r) => <ReqStatus status={r.status} /> },
                  { kunci: 'faktur', label: 'No. faktur', hp: 'judul', isi: (r) => <span className="whitespace-nowrap font-semibold" data-testid="approval-request-row">{r.invoice_number}</span> },
                  { kunci: 'po', label: 'No. PO', isi: (r) => <span className="whitespace-nowrap text-muted-foreground">{r.po_number || '—'}</span> },
                  { kunci: 'kategori', label: 'Kategori', isi: (r) => CATEGORY_LABEL[r.invoice_category] || r.invoice_category },
                  { kunci: 'ringkasan', label: 'Ringkasan perubahan', hp: 'keterangan', isi: (r) => <div className="md:max-w-xs md:truncate" title={r.change_summary}>{r.change_summary}</div> },
                  { kunci: 'pengaju', label: 'Diajukan oleh', isi: (r) => <span>{r.requested_by_name}<span className="block text-xs text-muted-foreground">{r.requested_by}</span></span> },
                  { kunci: 'waktu', label: 'Waktu pengajuan', isi: (r) => <span className="whitespace-nowrap text-muted-foreground">{fmtDate(r.requested_at)}</span> },
                  { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
                    <Button variant="outline" size="sm" onClick={() => openDetail(r)} data-testid="approval-view-detail-button">Rincian</Button>) },
                ]} />
              <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} className="px-3" />
            </>
          )}
        </GlassCard>
      )}
    </PageLayout>
  );
}

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

/*
 * Persetujuan Perubahan Faktur (menu Keuangan).
 * 2026-11-05 (PANDUAN_UI G1/G8/G10/G13): cetakan PageLayout; status berbahasa Indonesia lewat StatusBadge (dulu
 * "Pending/Approved/Rejected" berwarna palet langsung); rincian permintaan dibuka DI HALAMAN di atas daftar
 * (dulu popup); tampilan kosong di kartu daftar (dulu teks berjarak besar di luar kartu → pita kosong 80 px).
 */
const STATUS_META = {
  Pending: { label: 'Menunggu', tone: 'warning' },
  Approved: { label: 'Disetujui', tone: 'success' },
  Rejected: { label: 'Ditolak', tone: 'danger' },
};
const CATEGORY_LABEL = { VENDOR: 'Pemasok', CUSTOMER: 'Pelanggan' };
const COLUMNS = ['Status', 'No. faktur', 'No. PO', 'Kategori', 'Ringkasan perubahan', 'Diajukan oleh', 'Waktu pengajuan', 'Aksi'];

const fmt = formatRupiah;
const fmtDate = (d) => d ? new Date(d).toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '-';

function ReqStatus({ status }) {
  const m = STATUS_META[status];
  return <StatusBadge status={status} label={m?.label || status} tone={m?.tone || 'default'} />;
}

/** Satu pasang nilai sebelum → sesudah (netral; warna tidak dipakai sebagai hiasan — G8). */
function BeforeAfter({ label, before, after, big }) {
  return (
    <div className="grid grid-cols-2 gap-4">
      <div className="rounded-[var(--radius-md)] bg-foreground/[0.03] p-3">
        <p className="text-xs text-muted-foreground font-medium mb-1">Sebelum · {label}</p>
        <p className={`text-foreground/70 ${big ? 'text-lg font-bold tabular-nums' : 'text-sm'}`}>{before}</p>
      </div>
      <div className="rounded-[var(--radius-md)] bg-[hsl(var(--primary)/0.06)] p-3">
        <p className="text-xs text-muted-foreground font-medium mb-1">Sesudah · {label}</p>
        <p className={`text-foreground ${big ? 'text-lg font-bold tabular-nums' : 'text-sm'}`}>{after}</p>
      </div>
    </div>
  );
}

function ItemList({ title, items, tint }) {
  return (
    <div className={`rounded-[var(--radius-md)] p-3 ${tint ? 'bg-[hsl(var(--primary)/0.06)]' : 'bg-foreground/[0.03]'}`}>
      <p className="text-xs text-muted-foreground font-medium mb-2">{title}</p>
      <div className="space-y-1.5">
        {(items || []).map((item, idx) => (
          <div key={idx} className="bg-[var(--card-surface)] rounded p-2 text-xs border border-[var(--glass-border)]">
            <p className="font-medium text-foreground">{item.product_name}</p>
            <p className="text-muted-foreground">{item.sku} · {item.size}/{item.color}</p>
            <div className="flex justify-between mt-1 tabular-nums">
              <span>Qty: <strong>{item.invoice_qty}</strong></span>
              <span>Subtotal: <strong>{fmt(item.subtotal || 0)}</strong></span>
            </div>
          </div>
        ))}
      </div>
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
          <div className="grid grid-cols-2 gap-4">
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
        <div className="grid grid-cols-3 gap-3 text-sm">
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
              <Button onClick={handleApprove} disabled={actionLoading} data-testid="approve-button">
                <CheckCircle className="w-4 h-4" />
                {actionLoading ? 'Memproses…' : 'Setujui'}
              </Button>
              <Button variant="outline" onClick={handleReject} disabled={actionLoading} data-testid="reject-button">
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
        <div className="relative w-72 max-w-full">
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
      tools={<Button variant="outline" size="icon" onClick={fetchRequests} title="Muat ulang" aria-label="Muat ulang" data-testid="approval-refresh-button"><RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /></Button>}
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
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-[var(--glass-bg)] border-b">
                    <tr>
                      {COLUMNS.map(h => (
                        <th key={h} className="text-left px-3 py-3 text-xs font-semibold text-muted-foreground uppercase whitespace-nowrap">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {paged.map(req => {
                      const open = showDetail && selectedRequest?.id === req.id;
                      return (
                        <tr key={req.id} className={`hover:bg-[var(--glass-bg)] ${open ? 'bg-[hsl(var(--primary)/0.06)]' : ''}`} data-testid="approval-request-row">
                          <td className="px-3 py-3"><ReqStatus status={req.status} /></td>
                          <td className="px-3 py-3 whitespace-nowrap font-semibold">{req.invoice_number}</td>
                          <td className="px-3 py-3 text-xs text-muted-foreground whitespace-nowrap">{req.po_number || '-'}</td>
                          <td className="px-3 py-3 text-xs whitespace-nowrap">{CATEGORY_LABEL[req.invoice_category] || req.invoice_category}</td>
                          <td className="px-3 py-3 text-foreground max-w-xs">
                            <div className="truncate" title={req.change_summary}>{req.change_summary}</div>
                          </td>
                          <td className="px-3 py-3 text-muted-foreground">
                            <p className="font-medium">{req.requested_by_name}</p>
                            <p className="text-xs text-muted-foreground">{req.requested_by}</p>
                          </td>
                          <td className="px-3 py-3 text-muted-foreground text-xs whitespace-nowrap">{fmtDate(req.requested_at)}</td>
                          <td className="px-3 py-3 whitespace-nowrap">
                            <Button variant="outline" size="sm" onClick={() => openDetail(req)} data-testid="approval-view-detail-button">
                              {open ? 'Tutup' : 'Rincian'}
                            </Button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} className="px-3" />
            </>
          )}
        </GlassCard>
      )}
    </PageLayout>
  );
}

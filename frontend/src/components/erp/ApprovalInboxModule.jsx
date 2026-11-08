/**
 * Menunggu persetujuan (tab di Manajemen Tugas, Portal Toko) — tugas yang dikirim staf untuk disetujui.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout (judul disembunyikan di hub), daftar = tabel (dulu kartu per tugas)
 * + unduh, form tolak = FormPopup pendek, rincian = TaskDetailDrawer (popup). Tombol Setujui hijau / Tolak merah.
 * Perbaikan angka: dulu hanya 20 tugas pertama yang dimuat dan jumlahnya ditulis sebagai total; kini dimuat sampai
 * 100 (batas server) dan jumlah memakai total dari server.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { RefreshCw, CheckCircle, XCircle, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { formatDateTimeID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatusBadge } from './moduleAtoms';
import { TaskDetailDrawer } from './TaskDetailDrawer';
import { PRIORITAS } from './TaskCard';

function RejectDialog({ open, onOpenChange, onConfirm, judul }) {
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [galat, setGalat] = useState('');

  useEffect(() => {
    if (!open) { setReason(''); setGalat(''); }
  }, [open]);

  const handleConfirm = async () => {
    if (!reason.trim()) {
      setGalat('Alasan penolakan wajib diisi.');
      return;
    }
    setSubmitting(true);
    await onConfirm(reason.trim());
    setSubmitting(false);
  };

  return (
    <FormPopup open={open} onClose={() => onOpenChange(false)} ukuran="pendek" testId="reject-dialog"
      judul={judul ? `Tolak tugas "${judul}"` : 'Tolak tugas'}
      keterangan="Tugas dikembalikan ke status Sedang dikerjakan dengan catatan ini."
      onSimpan={handleConfirm} menyimpan={submitting} galat={galat} labelSimpan="Tolak tugas">
      <Isian label="Alasan" wajib htmlFor="reject-reason">
        <Textarea id="reject-reason" value={reason} onChange={e => setReason(e.target.value)} rows={3}
          placeholder="Contoh: Data omzet tidak sesuai dengan Shopee Seller Center." data-testid="reject-reason-input" />
      </Isian>
    </FormPopup>
  );
}

export default function ApprovalInboxModule({ token }) {
  const [loading, setLoading] = useState(true);
  const [tasks, setTasks] = useState([]);
  const [total, setTotal] = useState(null);
  const [actioning, setActioning] = useState(null);
  const [rejectTarget, setRejectTarget] = useState(null);
  const [detailTaskId, setDetailTaskId] = useState(null);

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);

  const fetchPending = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/marketing/tasks?status=pending_approval&limit=100', { headers });
      if (res.ok) {
        const data = await res.json();
        // API returns paginated {tasks: [], pagination: {}} — extract the array
        const list = data?.tasks || (Array.isArray(data) ? data : []);
        setTasks(list);
        setTotal(data?.pagination?.total ?? list.length);
      }
    } catch (e) {
      toast.error('Gagal memuat tugas yang menunggu persetujuan');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    fetchPending();
  }, [fetchPending]);

  const handleApprove = async (task) => {
    setActioning(task.id);
    try {
      const res = await fetch(`/api/marketing/tasks/${task.id}/approve`, {
        method: 'POST',
        headers,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Gagal menyetujui');
      }
      toast.success(`Tugas "${task.title}" disetujui.`);
      fetchPending();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setActioning(null);
    }
  };

  const handleReject = async (reason) => {
    if (!rejectTarget) return;
    try {
      const res = await fetch(`/api/marketing/tasks/${rejectTarget.id}/reject?reason=${encodeURIComponent(reason)}`, {
        method: 'POST',
        headers,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Gagal menolak');
      }
      toast.success(`Tugas "${rejectTarget.title}" ditolak.`);
      setRejectTarget(null);
      fetchPending();
    } catch (e) {
      toast.error(e.message);
    }
  };

  const fmtDate = (d) => (d ? formatDateTimeID(d) : '—');
  const terlambat = (t) => t.due_date && new Date(t.due_date) < new Date();
  const kolom = [
    { kunci: 'tugas', label: 'Tugas', hp: 'judul', isi: (t) => (
      <div className="min-w-0 md:max-w-[24rem]" data-testid={`approval-row-${t.task_code}`}>
        <p className="truncate font-medium" data-testid={`approval-title-${t.task_code}`} title={t.title}>{t.title}</p>
        <p className="truncate text-xs text-muted-foreground">{t.task_code}{t.completion_notes ? ` · catatan: ${t.completion_notes}` : ''}</p>
      </div>) },
    { kunci: 'prioritas', label: 'Prioritas', isi: (t) => (
      <StatusBadge status={t.priority} label={(PRIORITAS[t.priority] || [t.priority || '—'])[0]} tone={(PRIORITAS[t.priority] || [])[1]} />) },
    { kunci: 'tenggat', label: 'Tenggat', hp: 'keterangan', isi: (t) => (
      <span className={`tabular-nums md:whitespace-nowrap ${terlambat(t) ? 'text-[hsl(var(--danger-text))]' : ''}`}>{fmtDate(t.due_date)}{terlambat(t) ? ' · terlambat' : ''}</span>) },
    { kunci: 'pj', label: 'Penanggung jawab', isi: (t) => t.assigned_to_name || (t.assigned_to ? 'Staf' : '—') },
    { kunci: 'periksa', label: 'Daftar periksa', rata: 'kanan', isi: (t) => (t.checklist?.length
      ? <span className="tabular-nums">{t.checklist.filter(c => c.completed).length}/{t.checklist.length}</span> : '—') },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (t) => (
      <div className="flex justify-end gap-1">
        <Button size="sm" variant="success" onClick={() => handleApprove(t)} disabled={actioning === t.id} data-testid={`approve-btn-${t.task_code}`}>
          {actioning === t.id ? <Loader2 className="animate-spin" /> : <CheckCircle />}Setujui
        </Button>
        <Button size="sm" variant="destructive" onClick={() => setRejectTarget(t)} disabled={actioning === t.id} data-testid={`reject-btn-${t.task_code}`}>
          <XCircle />Tolak
        </Button>
      </div>) },
  ];

  return (
    <PageLayout testId="approval-inbox-module" title="Menunggu persetujuan"
      subtitle="Tinjau tugas yang sudah dikirim staf marketing."
      tools={<>
        <TombolUnduh namaBerkas="tugas-menunggu-persetujuan" namaLembar="Persetujuan" baris={tasks} testId="approval-unduh"
          kolom={[
            { label: 'Kode', nilai: (t) => t.task_code || '' },
            { label: 'Tugas', nilai: (t) => t.title || '' },
            { label: 'Prioritas', nilai: (t) => (PRIORITAS[t.priority] || [t.priority || ''])[0] },
            { label: 'Tenggat', nilai: (t) => (t.due_date ? fmtDate(t.due_date) : '') },
            { label: 'Penanggung jawab', nilai: (t) => t.assigned_to_name || '' },
            { label: 'Daftar periksa', nilai: (t) => (t.checklist?.length ? `${t.checklist.filter(c => c.completed).length}/${t.checklist.length}` : '') },
            { label: 'Catatan', nilai: (t) => t.completion_notes || '' },
          ]} />
        <Button onClick={fetchPending} variant="outline" size="icon" title="Muat ulang" aria-label="Muat ulang" data-testid="refresh-approvals-btn">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={!loading && (
        <p className="text-sm text-muted-foreground">
          <span className="font-semibold text-foreground tabular-nums" data-testid="pending-count">{total ?? tasks.length}</span> tugas menunggu persetujuan
          {total != null && total > tasks.length ? ` · ${tasks.length} pertama ditampilkan` : ''}.
        </p>
      )}>
      {loading && tasks.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat tugas…</p>
      ) : (
        <TabelData kolom={kolom} baris={tasks} onKlikBaris={(t) => setDetailTaskId(t.id)} testId="approval-table"
          kosong={<EmptyState title="Tidak ada tugas yang menunggu persetujuan" description="Tugas yang dikirim staf untuk disetujui muncul di sini." />} />
      )}

      <RejectDialog open={!!rejectTarget} judul={rejectTarget?.title}
        onOpenChange={(o) => !o && setRejectTarget(null)} onConfirm={handleReject} />

      <TaskDetailDrawer
        taskId={detailTaskId}
        open={!!detailTaskId}
        onOpenChange={(o) => !o && setDetailTaskId(null)}
        onUpdated={fetchPending}
        token={token}
      />
    </PageLayout>
  );
}

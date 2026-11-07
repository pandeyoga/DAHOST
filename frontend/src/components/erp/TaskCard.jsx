import { useState } from 'react';
import { Clock, User, CheckCircle, AlertCircle, MoreVertical, ExternalLink, Zap } from 'lucide-react';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { AccountBadge } from './marketing/AccountBadge';
import { StatusBadge } from './moduleAtoms';
import { toast } from 'sonner';

/** Label bersama layar tugas (Standar UI/UX v2 — bahasa staf, bukan kode). */
export const PRIORITAS = { high: ['Tinggi', 'danger'], medium: ['Sedang', 'warning'], low: ['Rendah', 'muted'] };
export const JENIS_TUGAS = {
  data_entry: 'Input data',
  review: 'Tinjauan',
  analysis: 'Analisis',
  reporting: 'Pelaporan',
  operational: 'Operasional',
};
export const STATUS_TUGAS = {
  to_do: ['Akan dikerjakan', 'muted'], in_progress: ['Sedang dikerjakan', 'info'],
  pending_approval: ['Menunggu persetujuan', 'warning'], done: ['Selesai', 'success'], cancelled: ['Dibatalkan', 'danger'],
};
export const STATUS_PERSETUJUAN = { pending: 'Menunggu', approved: 'Disetujui', rejected: 'Ditolak' };
const taskTypeLabels = JENIS_TUGAS;

export function TaskCard({ task, isDragging, onRefresh, token, accounts = [], onViewDetail }) {
  const [loading, setLoading] = useState(false);
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  // Resolve akun dari ID
  const account = task.account_id ? accounts.find(a => a.id === task.account_id) : null;

  // Apakah task ini action-based (bukan sekadar reminder)
  const isActionable = task.action_type && task.action_type !== 'manual_check';
  const actionExecuted = !!task.action_executed_at;

  const handleApprove = async () => {
    if (!(await confirmDialog({ title: 'Setujui tugas ini?', confirmLabel: 'Setujui' }))) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/marketing/tasks/${task.id}/approve`, {
        method: 'POST',
        headers
      });
      if (res.ok) {
        toast.success('Tugas disetujui.');
        if (onRefresh) onRefresh();
      }
    } catch (e) {
      toast.error('Gagal menyetujui tugas');
    } finally {
      setLoading(false);
    }
  };

  const handleReject = async () => {
    const reason = await confirmDialog({ title: 'Tolak tugas ini?', confirmLabel: 'Tolak', danger: true, input: { label: 'Alasan penolakan' } });
    if (!reason) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/marketing/tasks/${task.id}/reject?reason=${encodeURIComponent(reason)}`, {
        method: 'POST',
        headers
      });
      if (res.ok) {
        toast.success('Tugas ditolak.');
        if (onRefresh) onRefresh();
      }
    } catch (e) {
      toast.error('Gagal menolak tugas');
    } finally {
      setLoading(false);
    }
  };

  const isOverdue = task.due_date && new Date(task.due_date) < new Date() && task.status !== 'done';

  return (
    <GlassCard
      className={`p-3 cursor-grab active:cursor-grabbing transition-all ${
        isDragging ? 'shadow-lg rotate-2 scale-105' : ''
      } ${isOverdue ? 'border-[hsl(var(--destructive)/0.5)]' : ''} ${
        isActionable && !actionExecuted ? 'border-[hsl(var(--primary)/0.4)]' : ''
      }`}
      data-testid={`task-card-${task.task_code}`}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 mb-1 flex-wrap">
            <span className="text-xs tabular-nums text-muted-foreground">{task.task_code}</span>
            {isOverdue && <AlertCircle className="w-3 h-3 text-[hsl(var(--danger-text))] shrink-0" />}
            {/* ⚡ Actionable indicator */}
            {isActionable && (
              <span className={`inline-flex items-center gap-0.5 text-xs font-medium px-1.5 py-0.5 rounded-full ${
                actionExecuted
                  ? 'bg-[hsl(var(--success)/0.1)] text-[hsl(var(--success-text))]'
                  : 'bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))] border border-[hsl(var(--primary)/0.3)]'
              }`}>
                <Zap size={9} />
                {actionExecuted ? 'Aksi selesai' : 'Ada aksi'}
              </span>
            )}
          </div>
          <p className="text-sm font-semibold text-foreground line-clamp-2">{task.title}</p>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" className="shrink-0" title="Lainnya" aria-label="Lainnya"
              onClick={(e) => e.stopPropagation()}>
              <MoreVertical className="w-3.5 h-3.5" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => onViewDetail?.(task.id)}>
              <ExternalLink className="w-3 h-3 mr-2" />
              Rincian
            </DropdownMenuItem>
            {task.status === 'pending_approval' && (
              <>
                <DropdownMenuItem onClick={handleApprove} disabled={loading}>
                  <CheckCircle className="w-3 h-3 mr-2 text-[hsl(var(--success-text))]" />
                  Setujui
                </DropdownMenuItem>
                <DropdownMenuItem onClick={handleReject} disabled={loading}>
                  <AlertCircle className="w-3 h-3 mr-2 text-[hsl(var(--danger-text))]" />
                  Tolak
                </DropdownMenuItem>
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* Description */}
      {task.description && (
        <p className="text-xs text-muted-foreground mb-2 line-clamp-2">{task.description}</p>
      )}

      {/* Account Badge */}
      {account && (
        <div className="mb-2">
          <AccountBadge account={account} size="xs" />
        </div>
      )}

      {/* Badges */}
      <div className="flex flex-wrap items-center gap-1 mb-2">
        <StatusBadge status={task.priority} label={(PRIORITAS[task.priority] || [task.priority || '—'])[0]} tone={(PRIORITAS[task.priority] || [])[1]} />
        <StatusBadge status={task.task_type} label={taskTypeLabels[task.task_type] || 'Lainnya'} tone="muted" />
      </div>

      {/* Checklist Progress */}
      {task.checklist && task.checklist.length > 0 && (
        <div className="mb-2">
          <div className="flex items-center justify-between text-xs text-muted-foreground mb-1">
            <span>Daftar periksa</span>
            <span>
              {task.checklist.filter(c => c.completed).length}/{task.checklist.length}
            </span>
          </div>
          <div className="h-1 bg-[var(--glass-bg)] rounded-full overflow-hidden">
            <div
              className="h-full bg-primary transition-all"
              style={{
                width: `${(task.checklist.filter(c => c.completed).length / task.checklist.length) * 100}%`
              }}
            />
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between text-xs text-muted-foreground pt-2 border-t border-[var(--glass-border)]">
        <div className="flex items-center gap-1">
          {task.due_date && (
            <div className={`flex items-center gap-1 ${isOverdue ? 'text-[hsl(var(--danger-text))]' : ''}`}>
              <Clock className="w-3 h-3" />
              {new Date(task.due_date).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' })}
            </div>
          )}
        </div>
        {task.assigned_to && (
          <div className="flex items-center gap-1">
            <User className="w-3 h-3" />
            {/* MK1 (7 Nov 2026): tugas dari template membawa nama PIC toko */}
            <span className="truncate max-w-[80px]">{task.assigned_to_name || task.assigned_to.slice(0, 8)}</span>
          </div>
        )}
      </div>

      {/* Approval Status */}
      {task.approval_status && (
        <div className="mt-2 pt-2 border-t border-[var(--glass-border)]">
          <span className="text-xs text-muted-foreground">
            Persetujuan: <span className="font-semibold">{STATUS_PERSETUJUAN[task.approval_status] || task.approval_status}</span>
          </span>
        </div>
      )}
    </GlassCard>
  );
}

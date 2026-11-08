/**
 * Papan tugas (tab di Manajemen Tugas, Portal Toko) — kanban tugas marketing + tampilan tabel.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout (judul disembunyikan di hub), penyaring satu baris (dulu panel
 * Filter yang dibuka-tutup), ViewToggle Papan/Tabel, unduh Excel/CSV semua tugas, label Indonesia.
 * Perbaikan angka: kartu dulu menghitung hanya 20 tugas di halaman ini dan diberi label "Total" (70 tugas tampil 20);
 * kini jumlah per status diambil dari server (penyaring yang sama), kolom papan menulis "x dari y".
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { DragDropContext, Droppable, Draggable } from 'react-beautiful-dnd';
import { Plus, RefreshCw, Zap, AlertTriangle, Columns3, Table2 } from 'lucide-react';
import { Button, buttonVariants } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import ViewToggle from '@/components/ui/view-toggle';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import {
  AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle,
  AlertDialogDescription, AlertDialogFooter, AlertDialogCancel, AlertDialogAction,
} from '@/components/ui/alert-dialog';
import { formatDateID } from '@/lib/format';
import { cn } from '@/lib/utils';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from './moduleAtoms';
import PaginationBar from './PaginationBar';
import { TaskCard, PRIORITAS, JENIS_TUGAS, STATUS_TUGAS } from './TaskCard';
import { CreateTaskDialog } from './CreateTaskDialog';
import { TaskDetailDrawer } from './TaskDetailDrawer';
import { toast } from 'sonner';

const COLUMNS = [
  { id: 'to_do', title: 'Akan dikerjakan' },
  { id: 'in_progress', title: 'Sedang dikerjakan' },
  { id: 'pending_approval', title: 'Menunggu persetujuan' },
  { id: 'done', title: 'Selesai' },
];
const VIEWS = [
  { key: 'board', label: 'Tampilan papan', icon: Columns3 },
  { key: 'table', label: 'Tampilan tabel', icon: Table2 },
];
const tgl = (v) => (v ? formatDateID(v) : '—');
const Lencana = ({ peta, nilai }) => (nilai
  ? <StatusBadge status={nilai} label={(peta[nilai] || [nilai])[0]} tone={(peta[nilai] || [])[1]} />
  : <span className="text-muted-foreground">—</span>);

export default function TaskManagementModule({ token }) {
  const [loading, setLoading] = useState(true);
  const [taskPage, setTaskPage] = useState(1);
  const [taskPagination, setTaskPagination] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [columns, setColumns] = useState({});
  const [accounts, setAccounts] = useState([]);
  const [filter, setFilter] = useState({ priority: 'all', account_id: 'all' });
  const [createOpen, setCreateOpen] = useState(false);
  const [detailTaskId, setDetailTaskId] = useState(null);
  const [view, setView] = useState('board');
  const [jumlah, setJumlah] = useState({});
  // Guard: bypass dialog untuk drag actionable task ke done tanpa eksekusi
  const [bypassConfirm, setBypassConfirm] = useState(null); // { task, newStatus }

  const headers = useMemo(
    () => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }),
    [token]
  );

  const fetchAccounts = useCallback(async () => {
    try {
      const res = await fetch('/api/marketing/accounts?status=active', { headers });
      if (res.ok) {
        setAccounts(await res.json());
      }
    } catch (e) {
      // silent fail
    }
  }, [headers]);

  const paramSaring = useCallback(() => {
    const params = new URLSearchParams();
    if (filter.priority !== 'all') params.append('priority', filter.priority);
    if (filter.account_id !== 'all') params.append('account_id', filter.account_id);
    return params;
  }, [filter]);

  /** Jumlah per status dari server (penyaring sama) — bukan hanya tugas di halaman ini. */
  const fetchJumlah = useCallback(async () => {
    try {
      const hasil = await Promise.all(COLUMNS.map(async (c) => {
        const p = paramSaring(); p.append('status', c.id); p.append('limit', '1');
        const r = await fetch(`/api/marketing/tasks?${p.toString()}`, { headers });
        const d = r.ok ? await r.json() : null;
        return [c.id, d?.pagination?.total ?? null];
      }));
      setJumlah(Object.fromEntries(hasil));
    } catch { setJumlah({}); }
  }, [headers, paramSaring]);

  const fetchTasks = useCallback(async () => {
    setLoading(true);
    try {
      const params = paramSaring();
      params.append('page', String(taskPage));
      params.append('limit', '20');
      const res = await fetch(`/api/marketing/tasks?${params.toString()}`, { headers });
      if (res.ok) {
        const data = await res.json();
        // Handle paginated or legacy response
        const taskList = data?.tasks || (Array.isArray(data) ? data : []);
        setTasks(taskList);
        setTaskPagination(data?.pagination || null);
        const grouped = COLUMNS.reduce((acc, col) => {
          acc[col.id] = taskList.filter(t => t.status === col.id);
          return acc;
        }, {});
        setColumns(grouped);
      }
    } catch (e) {
      toast.error('Gagal memuat tugas');
    } finally {
      setLoading(false);
    }
    fetchJumlah();
  }, [headers, paramSaring, taskPage, fetchJumlah]);

  useEffect(() => {
    fetchAccounts();
    fetchTasks();
  }, [fetchAccounts, fetchTasks]);

  const handleDragEnd = async (result) => {
    const { source, destination, draggableId } = result;
    if (!destination) return;
    if (source.droppableId === destination.droppableId && source.index === destination.index) return;

    const newStatus = destination.droppableId;
    const taskId    = draggableId;

    // Cari task object
    const task = tasks.find(t => t.id === taskId);

    // Guard: jika drag ke 'done' dan task adalah actionable + belum dieksekusi → tanya konfirmasi
    if (
      newStatus === 'done' &&
      task?.action_type && task.action_type !== 'manual_check' &&
      !task.action_executed_at
    ) {
      setBypassConfirm({ task, newStatus });
      return; // Batalkan drag, kembalikan ke posisi semula
    }

    await _applyStatusChange(taskId, newStatus, source, destination);
  };

  const _applyStatusChange = async (taskId, newStatus, source, destination) => {
    // Optimistic update
    const newColumns = { ...columns };
    const sourceColId = source?.droppableId || Object.keys(newColumns).find(k => newColumns[k].some(t => t.id === taskId));
    const destColId   = newStatus;
    const sourceCol = [...(newColumns[sourceColId] || [])];
    const destCol   = sourceColId === destColId ? sourceCol : [...(newColumns[destColId] || [])];
    const srcIdx    = source?.index ?? sourceCol.findIndex(t => t.id === taskId);
    const destIdx   = destination?.index ?? destCol.length;
    const [movedTask] = sourceCol.splice(srcIdx, 1);
    movedTask.status = newStatus;
    destCol.splice(destIdx, 0, movedTask);
    if (sourceColId !== destColId) {
      newColumns[sourceColId] = sourceCol;
    }
    newColumns[destColId] = destCol;
    setColumns(newColumns);

    try {
      const res = await fetch(`/api/marketing/tasks/${taskId}`, {
        method: 'PUT',
        headers,
        body: JSON.stringify({ status: newStatus }),
      });
      if (!res.ok) throw new Error('Update failed');
      const label =
        newStatus === 'pending_approval' ? 'Tugas dikirim untuk persetujuan.' :
        newStatus === 'done'             ? 'Tugas selesai.' : 'Status tugas disimpan.';
      toast.success(label);
      fetchJumlah();
    } catch (e) {
      toast.error('Gagal mengubah tugas');
      fetchTasks();
    }
  };

  const namaAkun = (id) => accounts.find((a) => a.id === id)?.account_name || '—';
  /** Unduh: semua tugas sesuai penyaring (bukan hanya 20 di halaman ini). */
  const ambilSemua = async () => {
    const semua = [];
    for (let p = 1; p <= 100; p += 1) {
      const params = paramSaring(); params.append('page', String(p)); params.append('limit', '100');
      const r = await fetch(`/api/marketing/tasks?${params.toString()}`, { headers });
      const d = r.ok ? await r.json() : {};
      semua.push(...(d?.tasks || []));
      if (!d?.pagination?.has_next) break;
    }
    return semua;
  };
  const kolomUnduh = [
    { label: 'Kode', nilai: (t) => t.task_code || '' },
    { label: 'Tugas', nilai: (t) => t.title || '' },
    { label: 'Jenis', nilai: (t) => JENIS_TUGAS[t.task_type] || 'Lainnya' },
    { label: 'Toko', nilai: (t) => (t.account_id ? namaAkun(t.account_id) : '') },
    { label: 'Prioritas', nilai: (t) => (PRIORITAS[t.priority] || [t.priority || ''])[0] },
    { label: 'Status', nilai: (t) => (STATUS_TUGAS[t.status] || [t.status || ''])[0] },
    { label: 'Tenggat', nilai: (t) => (t.due_date ? tgl(t.due_date) : '') },
    { label: 'Penanggung jawab', nilai: (t) => t.assigned_to_name || '' },
    { label: 'Daftar periksa', nilai: (t) => ((t.checklist || []).length ? `${(t.checklist || []).filter((c) => c.completed).length}/${t.checklist.length}` : '') },
  ];
  const terlambat = (t) => t.due_date && new Date(t.due_date) < new Date() && t.status !== 'done' && t.status !== 'cancelled';
  const kolom = [
    { kunci: 'tugas', label: 'Tugas', hp: 'judul', isi: (t) => (
      <div className="min-w-0 md:max-w-[22rem]"><p className="truncate font-medium" title={t.title}>{t.title}</p>
        <p className="text-xs text-muted-foreground">{t.task_code} · {JENIS_TUGAS[t.task_type] || 'Lainnya'}</p></div>) },
    { kunci: 'toko', label: 'Toko', isi: (t) => (t.account_id ? namaAkun(t.account_id) : '—') },
    { kunci: 'prioritas', label: 'Prioritas', isi: (t) => <Lencana peta={PRIORITAS} nilai={t.priority} /> },
    { kunci: 'tenggat', label: 'Tenggat', hp: 'keterangan', isi: (t) => (
      <span className={cn('tabular-nums md:whitespace-nowrap', terlambat(t) && 'text-[hsl(var(--danger-text))]')}>
        {tgl(t.due_date)}{terlambat(t) ? ' · terlambat' : ''}</span>) },
    { kunci: 'status', label: 'Status', isi: (t) => <Lencana peta={STATUS_TUGAS} nilai={t.status} /> },
    { kunci: 'pj', label: 'Penanggung jawab', isi: (t) => t.assigned_to_name || '—' },
  ];
  const adaSaring = filter.priority !== 'all' || filter.account_id !== 'all';
  const angka = (id) => (jumlah[id] == null ? '—' : jumlah[id]);

  return (
    <PageLayout testId="task-management-page" title="Papan tugas"
      subtitle="Tugas harian, mingguan, dan bulanan dengan alur persetujuan."
      actions={<Button onClick={() => setCreateOpen(true)} data-testid="create-task-button"><Plus />Buat tugas</Button>}
      filters={<>
        <SmartNativeSelect value={filter.priority} onChange={(e) => { setFilter(f => ({ ...f, priority: e.target.value })); setTaskPage(1); }}
          className="w-full" wrapperClassName="w-40 max-w-full" searchable={false} data-testid="filter-priority">
          <option value="all">Semua prioritas</option>
          {Object.entries(PRIORITAS).map(([k, v]) => <option key={k} value={k}>{v[0]}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={filter.account_id} onChange={(e) => { setFilter(f => ({ ...f, account_id: e.target.value })); setTaskPage(1); }}
          className="w-full" wrapperClassName="w-56 max-w-full" data-testid="filter-account">
          <option value="all">Semua toko</option>
          {accounts.map(acc => <option key={acc.id} value={acc.id}>{acc.account_name}</option>)}
        </SmartNativeSelect>
      </>}
      tools={<>
        <ViewToggle value={view} onChange={setView} options={VIEWS} testId="task-view" />
        <TombolUnduh label={<span className="max-sm:sr-only">Unduh</span>} namaBerkas="tugas-marketing" namaLembar="Tugas" baris={tasks} ambilSemua={ambilSemua} kolom={kolomUnduh} testId="task-unduh" />
        <Button onClick={fetchTasks} variant="outline" size="icon" title="Muat ulang" aria-label="Muat ulang" data-testid="refresh-tasks-btn">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={view === 'table' && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="task-stats">
          {COLUMNS.map((c) => (
            <StatTile key={c.id} label={c.title} value={angka(c.id)}
              accent={c.id === 'pending_approval' ? 'warning' : c.id === 'done' ? 'success' : 'default'}
              hint={adaSaring ? 'Semua tugas yang cocok dengan penyaring (bukan hanya halaman ini).' : 'Semua tugas (bukan hanya halaman ini).'} />
          ))}
        </div>
      )}
      footer={taskPagination && (
        <PaginationBar pagination={taskPagination} onPageChange={(p) => setTaskPage(p)} />
      )}>
      {loading && tasks.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat tugas…</p>
      ) : view === 'table' ? (
        <TabelData kolom={kolom} baris={tasks} onKlikBaris={(t) => setDetailTaskId(t.id)} testId="task-table"
          kosong={<EmptyState title={adaSaring ? 'Tidak ada tugas yang cocok' : 'Belum ada tugas'}
            description={adaSaring ? 'Ubah penyaring.' : 'Buat tugas pertama atau aktifkan templat tugas berulang.'} />} />
      ) : (
        <DragDropContext onDragEnd={handleDragEnd}>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
            {COLUMNS.map(column => (
              <div key={column.id} data-testid={`column-${column.id}`}>
                <div className="mb-2 flex items-center justify-between gap-2 border-b border-[var(--glass-border)] pb-2">
                  <span className="text-sm font-semibold">{column.title}</span>
                  <span className="text-xs tabular-nums text-muted-foreground"
                    title="Tugas di halaman ini dari seluruh tugas berstatus ini">
                    {columns[column.id]?.length || 0}{jumlah[column.id] != null ? ` dari ${jumlah[column.id]}` : ''}
                  </span>
                </div>
                <Droppable droppableId={column.id} isDropDisabled={false} isCombineEnabled={false} ignoreContainerClipping={false}>
                  {(provided, snapshot) => (
                    <div
                      ref={provided.innerRef}
                      {...provided.droppableProps}
                      className={cn('min-h-[12rem] space-y-2 rounded-[var(--radius-md)] p-1 transition-colors',
                        snapshot.isDraggingOver ? 'border border-[hsl(var(--primary)/0.3)] bg-primary/5' : 'border border-transparent')}
                    >
                      {columns[column.id]?.length === 0 && (
                        <p className="py-6 text-center text-xs text-muted-foreground">
                          {snapshot.isDraggingOver ? 'Lepas di sini…' : 'Tidak ada tugas'}
                        </p>
                      )}
                      {columns[column.id]?.map((task, index) => (
                        <Draggable key={task.id} draggableId={task.id} index={index}>
                          {(provided, snapshot) => (
                            <div
                              ref={provided.innerRef}
                              {...provided.draggableProps}
                              {...provided.dragHandleProps}
                              style={provided.draggableProps.style}
                              onClick={() => {
                                if (!snapshot.isDragging) setDetailTaskId(task.id);
                              }}
                            >
                              <TaskCard
                                task={task}
                                isDragging={snapshot.isDragging}
                                onRefresh={fetchTasks}
                                token={token}
                                accounts={accounts}
                                onViewDetail={(id) => setDetailTaskId(id)}
                              />
                            </div>
                          )}
                        </Draggable>
                      ))}
                      {provided.placeholder}
                    </div>
                  )}
                </Droppable>
              </div>
            ))}
          </div>
        </DragDropContext>
      )}

      <CreateTaskDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={fetchTasks}
        token={token}
        accounts={accounts}
      />

      <TaskDetailDrawer
        taskId={detailTaskId}
        open={!!detailTaskId}
        onOpenChange={(o) => !o && setDetailTaskId(null)}
        onUpdated={fetchTasks}
        token={token}
      />

      {/* Guard: konfirmasi saat drag tugas beraksi ke Selesai tanpa eksekusi */}
      <AlertDialog open={!!bypassConfirm} onOpenChange={(o) => !o && setBypassConfirm(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-[hsl(var(--warning-text))]" />
              Aksi tugas belum dijalankan
            </AlertDialogTitle>
            <AlertDialogDescription>
              "{bypassConfirm?.task?.title}" punya aksi sistem yang belum dijalankan. Bila ditandai selesai tanpa
              menjalankannya, datanya tidak tersimpan ke sistem. Pilih tindakan:
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className="flex-col gap-2 sm:flex-row">
            <AlertDialogCancel onClick={() => setBypassConfirm(null)}>Batal</AlertDialogCancel>
            <AlertDialogAction
              className={buttonVariants({ variant: 'outline' })}
              onClick={async () => {
                const t = bypassConfirm;
                setBypassConfirm(null);
                await _applyStatusChange(t.task.id, t.newStatus, null, null);
              }}
            >
              Tandai selesai manual
            </AlertDialogAction>
            <AlertDialogAction
              onClick={() => {
                // Buka rincian supaya aksi bisa dijalankan
                setDetailTaskId(bypassConfirm.task.id);
                setBypassConfirm(null);
              }}
            >
              <Zap className="h-4 w-4" />Jalankan sekarang
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageLayout>
  );
}

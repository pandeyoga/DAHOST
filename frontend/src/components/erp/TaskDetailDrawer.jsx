/**
 * TaskDetailDrawer — rincian & ubah satu tugas marketing (dipakai Papan tugas dan Menunggu persetujuan).
 *
 * Standar UI/UX v2 (8 Nov 2026): dulu panel samping (Sheet); kini FormPopup panjang (detail/form = popup), isian di
 * `Isian`, pilihan = SmartNativeSelect, tenggat = DatePicker + jam (dulu datetime-local), tanggal aksi = DatePicker,
 * label Indonesia. Nama komponen & props tetap supaya pemakai lama tidak berubah. Aksi dan isi yang dikirim tidak berubah.
 */
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { useState, useEffect, useMemo } from 'react';
import { Loader2, Trash2, CheckCircle, AlertCircle, Send, Zap } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { MoneyInput } from '@/components/ui/money-input';
import { Checkbox } from '@/components/ui/checkbox';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import DatePicker from '@/components/ui/date-picker';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { toWIBLocalInput, fromWIBLocalInput } from '@/lib/waktu';
import { Notice, StatusBadge } from './moduleAtoms';
import { STATUS_TUGAS, STATUS_PERSETUJUAN } from './TaskCard';

const API = process.env.REACT_APP_BACKEND_URL;

const PRIORITIES = [
  { value: 'high', label: 'Tinggi' },
  { value: 'medium', label: 'Sedang' },
  { value: 'low', label: 'Rendah' },
];

const STATUSES = [
  { value: 'to_do', label: 'Akan dikerjakan' },
  { value: 'in_progress', label: 'Sedang dikerjakan' },
  { value: 'pending_approval', label: 'Menunggu persetujuan' },
  { value: 'done', label: 'Selesai' },
  { value: 'cancelled', label: 'Dibatalkan' },
];
const AKSI_LABEL = {
  sales_data: 'Isi data penjualan', return: 'Setujui / tolak retur', review: 'Balas ulasan', manual_check: 'Pemeriksaan manual',
};

export function TaskDetailDrawer({ taskId, open, onOpenChange, onUpdated, token }) {
  const [task, setTask] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState(null);
  const [actionData, setActionData] = useState({});
  const [actionExecuting, setActionExecuting] = useState(false);
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);

  useEffect(() => {
    if (open && taskId) {
      fetchTask();
    } else {
      setTask(null);
      setForm(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, taskId]);

  const fetchTask = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/marketing/tasks/${taskId}`, { headers });
      if (!res.ok) throw new Error('Tugas tidak ditemukan');
      const data = await res.json();
      setTask(data);
      // Pre-fill actionData from related_form_data if exists
      setActionData(data.related_form_data || {});
      setForm({
        title: data.title || '',
        description: data.description || '',
        priority: data.priority || 'medium',
        status: data.status || 'to_do',
        // Instan → nilai datetime-local dalam jam WIB (dulu jam UTC: tiap simpan mundur 7 jam).
        due_date: toWIBLocalInput(data.due_date),
        completion_notes: data.completion_notes || '',
        checklist: data.checklist || [],
      });
    } catch (e) {
      toast.error(e.message);
    } finally {
      setLoading(false);
    }
  };

  // ── Execute task action ──
  const handleExecuteAction = async () => {
    if (!task) return;
    const actionType = task.action_type;
    const related = task.related_entity;

    // Validation per action_type
    if (actionType === 'submit_form' && related === 'sales_data') {
      if (!actionData.revenue && actionData.revenue !== 0) {
        toast.error('Omzet wajib diisi'); return;
      }
    }
    if (actionType === 'approve_reject' && !actionData.decision) {
      toast.error('Pilih setujui atau tolak dulu'); return;
    }
    if (actionType === 'review_content' && !actionData.response_text) {
      toast.error('Tulis balasan dulu'); return;
    }

    setActionExecuting(true);
    try {
      const res = await fetch(`${API}/api/marketing/tasks/${taskId}/complete-action`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          action_data: actionData,
          completion_notes: form?.completion_notes || '',
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Aksi gagal dijalankan');
      toast.success(data.message || 'Aksi dijalankan.');
      if (onUpdated) onUpdated();
      fetchTask();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setActionExecuting(false);
    }
  };

  const toggleChecklist = (idx) => {
    setForm(f => ({
      ...f,
      checklist: f.checklist.map((c, i) => i === idx ? { ...c, completed: !c.completed } : c),
    }));
  };

  const handleSave = async () => {
    if (!form) return;
    setSaving(true);
    try {
      const payload = {
        title: form.title,
        description: form.description,
        priority: form.priority,
        status: form.status,
        due_date: fromWIBLocalInput(form.due_date),
        completion_notes: form.completion_notes,
        checklist: form.checklist,
      };
      const res = await fetch(`${API}/api/marketing/tasks/${taskId}`, {
        method: 'PUT',
        headers,
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error('Gagal menyimpan');
      toast.success('Tugas disimpan.');
      if (onUpdated) onUpdated();
      fetchTask();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  };

  const handleSubmitForApproval = async () => {
    setSaving(true);
    try {
      const res = await fetch(`${API}/api/marketing/tasks/${taskId}`, {
        method: 'PUT',
        headers,
        body: JSON.stringify({ status: 'pending_approval' }),
      });
      if (!res.ok) throw new Error('Gagal mengirim untuk persetujuan');
      toast.success('Tugas dikirim untuk persetujuan.');
      if (onUpdated) onUpdated();
      fetchTask();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!(await confirmDialog({ title: 'Batalkan tugas ini?', body: 'Tugas ditandai dibatalkan.', confirmLabel: 'Batalkan tugas', danger: true }))) return;
    setSaving(true);
    try {
      const res = await fetch(`${API}/api/marketing/tasks/${taskId}`, {
        method: 'DELETE',
        headers,
      });
      if (!res.ok) throw new Error('Gagal menghapus');
      toast.success('Tugas dibatalkan.');
      if (onUpdated) onUpdated();
      onOpenChange(false);
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  };

  const tglTenggat = (form?.due_date || '').slice(0, 10);
  const jamTenggat = (form?.due_date || '').slice(11, 16);
  const aturTenggat = (ymd, jam) => setForm(f => ({ ...f, due_date: ymd ? `${ymd}T${jam || '23:59'}` : '' }));
  const st = (v) => (STATUS_TUGAS[v] || [v || '—', 'muted']);
  const bisaKirim = form && form.status !== 'pending_approval' && form.status !== 'done' && form.status !== 'cancelled';

  return (
    <FormPopup open={open} onClose={() => onOpenChange(false)} ukuran="panjang" testId="task-detail-drawer"
      judul={task?.task_code ? `Rincian tugas ${task.task_code}` : 'Rincian tugas'}
      keterangan={task ? [st(task.status)[0], task.approval_status ? `persetujuan: ${(STATUS_PERSETUJUAN[task.approval_status] || task.approval_status).toLowerCase()}` : '',
        task.related_entity ? `aksi: ${(AKSI_LABEL[task.related_entity] || 'lainnya').toLowerCase()}` : ''].filter(Boolean).join(' · ') : undefined}
      onSimpan={handleSave} menyimpan={saving} bisaSimpan={!!form} labelSimpan="Simpan"
      aksiKiri={form && <>
        {bisaKirim && (
          <Button type="button" onClick={handleSubmitForApproval} disabled={saving} variant="outline" data-testid="detail-submit-approval-btn">
            <Send />Kirim untuk persetujuan
          </Button>
        )}
        <Button type="button" onClick={handleDelete} disabled={saving} variant="destructive" data-testid="detail-cancel-btn">
          <Trash2 />Batalkan tugas
        </Button>
      </>}>
      {loading ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat tugas…</p>
      ) : !form ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Tugas tidak tersedia.</p>
      ) : (
        <>
          {/* ── AKSI DALAM SISTEM ── */}
          {task?.action_type && task.status !== 'done' && task.status !== 'cancelled' && (
            <div className="space-y-3 rounded-[var(--radius-md)] border border-[hsl(var(--primary)/0.3)] p-3" data-testid="task-action-panel">
              <p className="flex items-center gap-2 text-sm font-semibold"><Zap className="h-4 w-4 text-primary" />Aksi dalam sistem</p>

              {task.action_type === 'submit_form' && task.related_entity === 'sales_data' && (
                <>
                  <p className="text-sm text-muted-foreground">Isi data penjualan akun terkait. Saat dijalankan, data tersimpan dan skor kesehatan toko diperbarui.</p>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Isian label="Omzet (Rp)" wajib>
                      <MoneyInput value={actionData.revenue ?? ''} placeholder="0" data-testid="action-revenue-input"
                        onChange={e => setActionData(d => ({ ...d, revenue: parseFloat(e.target.value) || 0 }))} />
                    </Isian>
                    <Isian label="Pesanan" htmlFor="act-orders">
                      <Input id="act-orders" type="number" min={0} value={actionData.orders ?? ''} placeholder="0"
                        onChange={e => setActionData(d => ({ ...d, orders: parseInt(e.target.value) || 0 }))} />
                    </Isian>
                    <Isian label="Pengunjung" htmlFor="act-visitors">
                      <Input id="act-visitors" type="number" min={0} value={actionData.visitors ?? ''} placeholder="0"
                        onChange={e => setActionData(d => ({ ...d, visitors: parseInt(e.target.value) || 0 }))} />
                    </Isian>
                    <Isian label="Tanggal">
                      <DatePicker value={actionData.date || ''} onChange={(v) => setActionData(d => ({ ...d, date: v }))} testId="action-date" />
                    </Isian>
                  </div>
                </>
              )}

              {task.action_type === 'approve_reject' && task.related_entity === 'return' && (
                <>
                  <p className="text-sm text-muted-foreground">Putuskan apakah permintaan retur ini disetujui atau ditolak.</p>
                  <div className="flex gap-2">
                    <Button type="button" size="sm" variant={actionData.decision === 'approve' ? 'success' : 'outline'}
                      onClick={() => setActionData(d => ({ ...d, decision: 'approve' }))} data-testid="action-approve-btn">
                      <CheckCircle />Setujui
                    </Button>
                    <Button type="button" size="sm" variant={actionData.decision === 'reject' ? 'destructive' : 'outline'}
                      onClick={() => setActionData(d => ({ ...d, decision: 'reject' }))} data-testid="action-reject-btn">
                      <AlertCircle />Tolak
                    </Button>
                  </div>
                  <Isian label="Alasan" petunjuk="Opsional." htmlFor="act-reason">
                    <Textarea id="act-reason" rows={2} value={actionData.reason || ''} placeholder="Tulis alasan keputusan"
                      onChange={e => setActionData(d => ({ ...d, reason: e.target.value }))} />
                  </Isian>
                </>
              )}

              {task.action_type === 'review_content' && task.related_entity === 'review' && (
                <Isian label="Balasan ulasan" wajib htmlFor="act-reply">
                  <Textarea id="act-reply" rows={3} value={actionData.response_text || ''} placeholder="Terima kasih atas ulasannya…"
                    onChange={e => setActionData(d => ({ ...d, response_text: e.target.value }))} data-testid="action-review-reply" />
                </Isian>
              )}

              {task.action_type === 'manual_check' && (
                <p className="text-sm text-muted-foreground">Tandai tugas selesai setelah pemeriksaan manual beres.</p>
              )}

              <Button type="button" onClick={handleExecuteAction} disabled={actionExecuting} data-testid="action-execute-btn">
                {actionExecuting ? <Loader2 className="animate-spin" /> : <Zap />}Jalankan & tandai selesai
              </Button>
            </div>
          )}

          {task?.action_executed_at && task.action_result && (
            <Notice tone="success" icon={CheckCircle} title="Aksi sudah dijalankan">{task.action_result.message}</Notice>
          )}

          <Isian label="Judul" htmlFor="detail-title">
            <Input id="detail-title" value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))} data-testid="detail-title-input" />
          </Isian>
          <Isian label="Deskripsi" htmlFor="detail-desc">
            <Textarea id="detail-desc" rows={3} value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
              data-testid="detail-desc-input" />
          </Isian>
          <div className="grid gap-4 sm:grid-cols-2">
            <Isian label="Status" htmlFor="detail-status">
              <SmartNativeSelect id="detail-status" value={form.status} searchable={false}
                onChange={(e) => setForm(f => ({ ...f, status: e.target.value }))} data-testid="detail-status-select">
                {STATUSES.map(x => <option key={x.value} value={x.value}>{x.label}</option>)}
              </SmartNativeSelect>
            </Isian>
            <Isian label="Prioritas" htmlFor="detail-priority">
              <SmartNativeSelect id="detail-priority" value={form.priority} searchable={false}
                onChange={(e) => setForm(f => ({ ...f, priority: e.target.value }))} data-testid="detail-priority-select">
                {PRIORITIES.map(x => <option key={x.value} value={x.value}>{x.label}</option>)}
              </SmartNativeSelect>
            </Isian>
          </div>
          <Isian label="Tenggat" petunjuk="Tanpa jam = sampai 23.59 WIB.">
            <div className="flex gap-2">
              <div className="min-w-0 flex-1">
                <DatePicker value={tglTenggat} onChange={(v) => aturTenggat(v, jamTenggat)} placeholder="Tanpa tenggat" testId="detail-due-input" />
              </div>
              <Input type="time" className="w-28" value={jamTenggat} disabled={!tglTenggat} aria-label="Jam tenggat"
                onChange={(e) => aturTenggat(tglTenggat, e.target.value)} data-testid="detail-due-time" />
            </div>
          </Isian>
          {form.checklist && form.checklist.length > 0 && (
            <Isian label={`Daftar periksa (${form.checklist.filter(c => c.completed).length}/${form.checklist.length})`}>
              <ul className="space-y-1">
                {form.checklist.map((c, i) => (
                  <li key={i} className="flex items-center gap-2 border-b border-[var(--glass-border)] py-1.5">
                    <Checkbox checked={c.completed} onCheckedChange={() => toggleChecklist(i)} data-testid={`detail-checklist-${i}`} />
                    <span className={`flex-1 text-sm ${c.completed ? 'text-muted-foreground line-through' : ''}`}>{c.item}</span>
                  </li>
                ))}
              </ul>
            </Isian>
          )}
          <Isian label="Catatan penyelesaian" htmlFor="detail-notes">
            <Textarea id="detail-notes" rows={2} value={form.completion_notes} placeholder="Catatan saat tugas selesai"
              onChange={e => setForm(f => ({ ...f, completion_notes: e.target.value }))} data-testid="detail-notes-input" />
          </Isian>
          {task?.approval_status && (
            <p className="text-sm text-muted-foreground">Persetujuan:{' '}
              <StatusBadge status={task.approval_status} label={STATUS_PERSETUJUAN[task.approval_status] || task.approval_status}
                tone={task.approval_status === 'approved' ? 'success' : task.approval_status === 'rejected' ? 'danger' : 'warning'} /></p>
          )}
        </>
      )}
    </FormPopup>
  );
}

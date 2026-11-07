/**
 * HROnboardingModule — Onboarding Karyawan
 * Fitur:
 *  - Aktivitas kustom: tambah/hapus tugas di checklist yang berjalan
 *  - Pembuat template: buat/ubah/hapus template beserta daftar tugasnya
 *  - Selesaikan tugas dengan catatan
 *  - Status checklist (tunda/lanjutkan/tandai selesai)
 *
 * Standar UI/UX v2 (8 Nov 2026): tab halaman (HubTabs) + cetakan PageLayout, checklist & template = tabel
 * + unduh Excel/CSV (dulu kartu besar berulang), detail checklist = DetailPopup, semua form = FormPopup,
 * tenggat = DatePicker (dulu input tanggal bawaan), kartu angka StatTile, warna token, bahasa Indonesia.
 * Daftar checklist dulu diam-diam 50 pertama — kini semua halaman.
 */
import { useState, useEffect, useMemo, useCallback } from 'react';
import {
  Check, ChevronDown, ChevronRight, Pencil, PauseCircle, PlayCircle, Plus, RefreshCw, Search,
  SquareCheckBig, Trash2, X,
} from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import DatePicker from '@/components/ui/date-picker';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { cn } from '@/lib/utils';
import { formatDateID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import HubTabs from './hubs/HubTabs';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';
import { EmployeeSelect, useActiveEmployees } from './hr/hrPickers';

const BASE = process.env.REACT_APP_BACKEND_URL;
const api = (path, opts = {}) =>
  fetch(`${BASE}/api/dewi/onboarding${path}`, { cache: 'no-store', ...opts });

const fmtDate = (d) => (d ? formatDateID(d) : '—');

const STATUS_CFG = {
  active:      { label: 'Aktif',    tone: 'info' },
  completed:   { label: 'Selesai',  tone: 'success' },
  paused:      { label: 'Ditunda',  tone: 'warning' },
  in_progress: { label: 'Berjalan', tone: 'info' },
};
const labelStatus = (s) => (STATUS_CFG[s] || STATUS_CFG.active).label;
function Status({ status }) {
  const c = STATUS_CFG[status] || STATUS_CFG.active;
  return <StatusBadge status={status} label={c.label} tone={c.tone} />;
}

const CATEGORIES = ['HR', 'IT', 'Legal', 'Keselamatan', 'Training', 'Administrasi', 'Kustom', 'Umum'];

function ProgressBar({ pct }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 min-w-16 flex-1 overflow-hidden rounded-full bg-[var(--glass-border)]">
        <div className={cn('h-full rounded-full transition-all duration-500', pct >= 100 ? 'bg-[hsl(var(--success))]' : 'bg-primary')}
          style={{ width: `${pct || 0}%` }} />
      </div>
      <span className="w-10 text-right text-sm font-medium tabular-nums">{pct || 0}%</span>
    </div>
  );
}

/** Ambil semua checklist (server membatasi 200 per halaman). */
async function ambilSemuaChecklist(headers) {
  const semua = [];
  for (let page = 1; page <= 50; page += 1) {
    const r = await api(`/checklists?limit=200&page=${page}`, { headers });
    const d = await r.json();
    const rows = d.checklists || [];
    semua.push(...rows);
    if (rows.length < 200 || (d.total != null && semua.length >= d.total)) break;
  }
  return semua;
}

// ────────────────────────────────────────────────────────────────────────────
// SELESAIKAN TUGAS (form popup)
// ────────────────────────────────────────────────────────────────────────────
function TaskNoteModal({ task, checklistId, headers, onSuccess, onClose }) {
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);

  const handleComplete = async () => {
    setSaving(true);
    try {
      const r = await api(`/checklists/${checklistId}/tasks/${task.task_id}`, {
        method: 'PUT', headers, body: JSON.stringify({ status: 'done', notes }),
      });
      const d = await r.json().catch(() => ({}));
      if (d.ok) { toast.success('Tugas diselesaikan'); onSuccess(d.checklist); }
      else toast.error(typeof d.detail === 'string' ? d.detail : 'Gagal');  // 2026-11-06 (pola P6): dulu diam
    } catch { toast.error('Gagal'); }
    finally { setSaving(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="pendek" onSimpan={handleComplete} menyimpan={saving}
      judul="Selesaikan tugas" labelSimpan="Selesai" testId="onb-task-done"
      keterangan={`${task.title} · ${task.category || 'Umum'}${task.assigned_to ? ` · PIC: ${task.assigned_to}` : ''}`}>
      <Isian label="Catatan penyelesaian (opsional)" htmlFor="onb-catatan">
        <Textarea id="onb-catatan" rows={3} value={notes} onChange={e => setNotes(e.target.value)}
          placeholder="Apa yang dilakukan, temuan, atau kendala" />
      </Isian>
    </FormPopup>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// TAMBAH AKTIVITAS KUSTOM (form popup)
// ────────────────────────────────────────────────────────────────────────────
function AddTaskModal({ checklistId, headers, onSuccess, onClose }) {
  const [form, setForm] = useState({ title: '', description: '', category: 'Kustom', assigned_to: '', day: 0, due_date: '' });
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    if (!form.title.trim()) { toast.error('Judul tugas diperlukan'); return; }
    setSaving(true);
    try {
      const payload = { ...form };
      if (!payload.due_date) delete payload.due_date;
      const r = await api(`/checklists/${checklistId}/tasks`, {
        method: 'POST', headers, body: JSON.stringify(payload),
      });
      const d = await r.json().catch(() => ({}));
      if (d.ok) { toast.success('Aktivitas ditambahkan'); onSuccess(d.checklist); }
      else toast.error(typeof d.detail === 'string' ? d.detail : 'Gagal menambah aktivitas');  // 2026-11-06 (pola P6): dulu diam
    } catch (_e) { toast.error('Gagal menambah aktivitas'); }
    finally { setSaving(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="pendek" onSimpan={handleSave} menyimpan={saving} bisaSimpan={!!form.title.trim()}
      judul="Tambah aktivitas kustom" labelSimpan="Tambah aktivitas" testId="onb-add-task">
      <Isian label="Nama aktivitas" wajib htmlFor="onb-akt-nama">
        <Input id="onb-akt-nama" autoFocus value={form.title} onChange={e => setForm(p => ({ ...p, title: e.target.value }))}
          placeholder="Contoh: Perkenalan dengan tim keuangan" />
      </Isian>
      <Isian label="Deskripsi" htmlFor="onb-akt-desk">
        <Textarea id="onb-akt-desk" rows={2} value={form.description} onChange={e => setForm(p => ({ ...p, description: e.target.value }))}
          placeholder="Penjelasan aktivitas" />
      </Isian>
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Kategori">
          <SmartNativeSelect searchable={false} value={form.category} onChange={e => setForm(p => ({ ...p, category: e.target.value }))}>
            {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Hari ke-" htmlFor="onb-akt-hari">
          <Input id="onb-akt-hari" type="number" min={0} value={form.day} onChange={e => setForm(p => ({ ...p, day: +e.target.value }))} />
        </Isian>
        <Isian label="Penanggung jawab" htmlFor="onb-akt-pic">
          <Input id="onb-akt-pic" value={form.assigned_to} onChange={e => setForm(p => ({ ...p, assigned_to: e.target.value }))}
            placeholder="SDM / IT / atasan / nama" />
        </Isian>
        <Isian label="Tenggat" petunjuk="Kosong = mengikuti hari ke-.">
          <DatePicker value={form.due_date} onChange={v => setForm(p => ({ ...p, due_date: v }))} placeholder="Tanpa tenggat" testId="onb-akt-tenggat" />
        </Isian>
      </div>
    </FormPopup>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// DETAIL CHECKLIST (popup)
// ────────────────────────────────────────────────────────────────────────────
function ChecklistDetail({ cl: initCl, headers, onUpdate, onClose }) {
  const [cl, setCl] = useState(initCl);
  const [expandedTask, setExpandedTask] = useState(null);
  const [completingTask, setCompletingTask] = useState(null);
  const [addingTask, setAddingTask] = useState(false);
  const [savingStatus, setSavingStatus] = useState(false);

  const handleUpdate = (updated) => {
    setCl(updated);
    onUpdate(updated);
  };

  const handleToggleTask = async (task) => {
    if (task.status === 'pending' || task.status === 'skipped') {
      // Show notes modal before completing
      setCompletingTask(task);
    } else {
      // Toggle back to pending directly
      try {
        const r = await api(`/checklists/${cl.checklist_id}/tasks/${task.task_id}`, {
          method: 'PUT', headers, body: JSON.stringify({ status: 'pending' }),
        });
        const d = await r.json();
        if (d.ok) handleUpdate(d.checklist);
      } catch { toast.error('Gagal'); }
    }
  };

  const handleDeleteTask = async (task) => {
    if (!(await confirmDialog({ title: `Hapus aktivitas "${task.title}"?`, confirmLabel: 'Hapus', danger: true }))) return;
    try {
      const r = await api(`/checklists/${cl.checklist_id}/tasks/${task.task_id}`, { method: 'DELETE', headers });
      const d = await r.json().catch(() => ({}));
      if (d.ok) { handleUpdate(d.checklist); toast.success('Aktivitas dihapus'); }
      else toast.error(typeof d.detail === 'string' ? d.detail : 'Gagal menghapus');  // 2026-11-06 (pola P6): dulu diam
    } catch { toast.error('Gagal menghapus'); }
  };

  const handleStatusChange = async (newStatus) => {
    setSavingStatus(true);
    try {
      const r = await api(`/checklists/${cl.checklist_id}`, {
        method: 'PUT', headers, body: JSON.stringify({ status: newStatus }),
      });
      const d = await r.json().catch(() => ({}));
      if (d.ok) { handleUpdate(d.checklist); toast.success(`Status diubah ke: ${STATUS_CFG[newStatus]?.label}`); }
      else toast.error(typeof d.detail === 'string' ? d.detail : 'Gagal mengubah status');  // 2026-11-06 (pola P6): dulu diam
    } catch { toast.error('Gagal mengubah status'); }
    finally { setSavingStatus(false); }
  };

  const byCategory = useMemo(() => {
    const acc = {};
    (cl.tasks || []).forEach(t => {
      const cat = t.category || 'Umum';
      if (!acc[cat]) acc[cat] = [];
      acc[cat].push(t);
    });
    return acc;
  }, [cl.tasks]);

  const doneTasks = (cl.tasks || []).filter(t => t.status === 'done').length;
  const totalTasks = (cl.tasks || []).length;

  return (
    <DetailPopup open onClose={onClose} testId="onb-detail" judul={cl.employee_name || 'Onboarding'}
      keterangan={[cl.employee_position, cl.employee_dept].filter(Boolean).join(' · ')}
      status={<Status status={cl.status} />}
      aksi={<>
        {cl.status === 'active' || cl.status === 'in_progress' ? (
          <Button size="sm" variant="outline" onClick={() => handleStatusChange('paused')} disabled={savingStatus}>
            <PauseCircle />Tunda
          </Button>
        ) : cl.status === 'paused' ? (
          <Button size="sm" variant="outline" onClick={() => handleStatusChange('active')} disabled={savingStatus}>
            <PlayCircle />Lanjutkan
          </Button>
        ) : null}
        {cl.status !== 'completed' && cl.progress_pct === 100 && (
          <Button size="sm" variant="success" onClick={() => handleStatusChange('completed')} disabled={savingStatus}>
            <SquareCheckBig />Tandai selesai
          </Button>
        )}
        <Button size="sm" onClick={() => setAddingTask(true)} data-testid="onb-add-task-btn"><Plus />Tambah aktivitas</Button>
      </>}>
      <ProgressBar pct={cl.progress_pct} />
      <dl className="divide-y divide-[var(--glass-border)]">
        <BarisDetail label="Tugas selesai">{doneTasks} dari {totalTasks}</BarisDetail>
        <BarisDetail label="Buddy">{cl.buddy || '—'}</BarisDetail>
        {cl.supervisor && <BarisDetail label="Supervisor">{cl.supervisor}</BarisDetail>}
        <BarisDetail label="Mulai">{fmtDate(cl.start_date)}</BarisDetail>
        <BarisDetail label="Target selesai">{fmtDate(cl.target_completion)}</BarisDetail>
      </dl>

      {/* Tugas per kategori */}
      {Object.entries(byCategory).map(([cat, tasks]) => (
        <div key={cat} className="space-y-1.5">
          <p className="text-sm font-medium text-foreground">
            {cat} <span className="font-normal text-muted-foreground">({tasks.filter(t => t.status === 'done').length}/{tasks.length})</span>
          </p>
          <ul className="divide-y divide-[var(--glass-border)] rounded-lg border border-[var(--glass-border)]">
            {tasks.map(t => {
              const isExpanded = expandedTask === t.task_id;
              const selesai = t.status === 'done';
              const lewat = !selesai && t.due_date && new Date(t.due_date) < new Date();
              return (
                <li key={t.task_id} data-testid={`onb-task-${t.task_id}`}>
                  <div className="flex items-center gap-2 px-2 py-2">
                    <Button variant="ghost" size="icon-sm" onClick={() => handleToggleTask(t)}
                      aria-label={selesai ? 'Tandai belum selesai' : 'Tandai selesai'} title={selesai ? 'Tandai belum selesai' : 'Tandai selesai'}
                      className={cn('rounded-full border-2', selesai ? 'border-[hsl(var(--success))] text-[hsl(var(--success-text))]' : 'border-[var(--glass-border)]')}>
                      {selesai && <Check />}
                    </Button>
                    <div className="min-w-0 flex-1">
                      <p className={cn('text-sm', selesai ? 'text-muted-foreground line-through' : 'text-foreground')}>{t.title}</p>
                      <p className="flex flex-wrap gap-x-2 text-xs text-muted-foreground">
                        <span>Hari ke-{t.day}</span>
                        {t.assigned_to && <span>PIC: {t.assigned_to}</span>}
                        {t.due_date && <span className={lewat ? 'font-medium text-[hsl(var(--danger-text))]' : ''}>Tenggat {fmtDate(t.due_date)}</span>}
                        {t.is_custom && <span>Kustom</span>}
                        {selesai && t.completed_at && <span className="text-[hsl(var(--success-text))]">Selesai {fmtDate(t.completed_at)}</span>}
                      </p>
                    </div>
                    {(t.description || t.notes || t.completed_by) && (
                      <Button variant="ghost" size="icon-sm" onClick={() => setExpandedTask(isExpanded ? null : t.task_id)}
                        aria-label={isExpanded ? 'Tutup rincian' : 'Lihat rincian'} title={isExpanded ? 'Tutup rincian' : 'Lihat rincian'}>
                        {isExpanded ? <ChevronDown /> : <ChevronRight />}
                      </Button>
                    )}
                    {t.is_custom && (
                      <Button variant="ghost" size="icon-sm" onClick={() => handleDeleteTask(t)} className="text-[hsl(var(--danger-text))]"
                        aria-label="Hapus aktivitas" title="Hapus aktivitas">
                        <Trash2 />
                      </Button>
                    )}
                  </div>
                  {isExpanded && (
                    <div className="space-y-1 px-12 pb-2 text-sm">
                      {t.description && <p className="text-muted-foreground">{t.description}</p>}
                      {t.notes && <p><span className="font-medium text-[hsl(var(--success-text))]">Catatan: </span>{t.notes}</p>}
                      {t.completed_by && <p className="text-xs text-muted-foreground">Diselesaikan oleh: {t.completed_by}</p>}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      ))}
      {totalTasks === 0 && <p className="text-sm text-muted-foreground">Checklist ini belum punya tugas. Klik "Tambah aktivitas".</p>}

      {completingTask && (
        <TaskNoteModal
          task={completingTask} checklistId={cl.checklist_id} headers={headers}
          onSuccess={(updated) => { setCompletingTask(null); handleUpdate(updated); }}
          onClose={() => setCompletingTask(null)}
        />
      )}
      {addingTask && (
        <AddTaskModal
          checklistId={cl.checklist_id} headers={headers}
          onSuccess={(updated) => { setAddingTask(false); handleUpdate(updated); }}
          onClose={() => setAddingTask(false)}
        />
      )}
    </DetailPopup>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// BARIS TUGAS TEMPLATE
// ────────────────────────────────────────────────────────────────────────────
function TemplateTaskRow({ task, onDelete, onEdit, index }) {
  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState({ day: task.day, assigned_to: task.assigned_to || '' });

  const handleSave = () => {
    onEdit(task.task_id || String(index), editForm);
    setEditing(false);
  };

  if (editing) {
    return (
      <li className="space-y-2 px-3 py-2">
        <p className="truncate text-sm font-medium text-foreground">{task.title}</p>
        <div className="grid grid-cols-2 gap-2">
          <Isian label="Hari ke-">
            <Input type="number" min={0} value={editForm.day} onChange={e => setEditForm(p => ({ ...p, day: +e.target.value }))} />
          </Isian>
          <Isian label="Penanggung jawab">
            <Input value={editForm.assigned_to} onChange={e => setEditForm(p => ({ ...p, assigned_to: e.target.value }))} placeholder="SDM / IT / karyawan" />
          </Isian>
        </div>
        <div className="flex justify-end gap-2">
          <Button type="button" size="sm" variant="outline" onClick={() => setEditing(false)}>Batal</Button>
          <Button type="button" size="sm" variant="success" onClick={handleSave}>Simpan</Button>
        </div>
      </li>
    );
  }

  return (
    <li className="flex items-center gap-2 px-3 py-2">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-foreground">{task.title}</p>
        <p className="text-xs text-muted-foreground">
          {task.category} · hari ke-{task.day}{task.assigned_to ? ` · PIC: ${task.assigned_to}` : ''}
        </p>
      </div>
      <Button type="button" variant="ghost" size="icon-sm" title="Ubah hari & penanggung jawab" aria-label="Ubah hari & penanggung jawab"
        onClick={() => { setEditForm({ day: task.day, assigned_to: task.assigned_to || '' }); setEditing(true); }}>
        <Pencil />
      </Button>
      <Button type="button" variant="ghost" size="icon-sm" className="text-[hsl(var(--danger-text))]" title="Hapus dari templat"
        aria-label="Hapus dari templat" onClick={() => onDelete(task.task_id || index)}>
        <X />
      </Button>
    </li>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// EDITOR TEMPLATE (form popup panjang)
// ────────────────────────────────────────────────────────────────────────────
function TemplateEditorModal({ template, headers, onSuccess, onClose, onDelete }) {
  const isNew = !template?.template_id;
  const [meta, setMeta] = useState({
    name: template?.name || '',
    dept: template?.dept || 'Semua',
    description: template?.description || '',
    duration_days: template?.duration_days || 30,
    is_default: template?.is_default || false,
  });
  const [tasks, setTasks] = useState(template?.tasks?.map((t, i) => ({ task_id: t.task_id || `tmp-${i}`, ...t })) || []);
  const [addTaskForm, setAddTaskForm] = useState({ title: '', category: 'HR', assigned_to: 'HR', day: 1, description: '' });
  const [showAddTask, setShowAddTask] = useState(false);
  const [saving, setSaving] = useState(false);

  const handleAddTask = () => {
    if (!addTaskForm.title.trim()) return;
    const newTask = { task_id: `tmp-${Date.now()}`, ...addTaskForm };
    setTasks(p => [...p, newTask].sort((a, b) => a.day - b.day));
    setAddTaskForm({ title: '', category: 'HR', assigned_to: 'HR', day: 1, description: '' });
    setShowAddTask(false);
  };

  const handleDeleteTask = (taskId) => {
    setTasks(p => p.filter(t => t.task_id !== taskId && t !== taskId));
  };

  const handleEditTask = (taskId, updates) => {
    setTasks(p => p.map(t => t.task_id === taskId ? { ...t, ...updates } : t));
  };

  const handleSave = async () => {
    if (!meta.name.trim()) { toast.error('Nama templat diperlukan'); return; }
    setSaving(true);
    try {
      const body = { ...meta, tasks };
      let r;
      if (isNew) {
        r = await api(`/templates`, { method: 'POST', headers, body: JSON.stringify(body) });
      } else {
        r = await api(`/templates/${template.template_id}`, { method: 'PUT', headers, body: JSON.stringify(body) });
      }
      const d = await r.json();
      if (d.ok) {
        toast.success(isNew ? 'Templat dibuat' : 'Templat disimpan');
        onSuccess();
      } else {
        toast.error(typeof d.detail === 'string' ? d.detail : 'Gagal menyimpan');
      }
    } catch { toast.error('Gagal menyimpan'); }
    finally { setSaving(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" onSimpan={handleSave} menyimpan={saving} bisaSimpan={!!meta.name.trim()}
      judul={isNew ? 'Buat templat baru' : `Ubah templat: ${template.name}`}
      labelSimpan={isNew ? 'Buat templat' : 'Simpan perubahan'} testId="onb-template-form"
      aksiKiri={!isNew && !template.is_default && onDelete ? (
        <Button type="button" variant="destructive" onClick={() => onDelete(template)} data-testid="onb-template-delete">
          <Trash2 />Hapus templat
        </Button>) : null}>
      <Isian label="Nama templat" wajib htmlFor="onb-tpl-nama">
        <Input id="onb-tpl-nama" value={meta.name} onChange={e => setMeta(p => ({ ...p, name: e.target.value }))}
          placeholder="Contoh: Onboarding operator produksi" />
      </Isian>
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Departemen" htmlFor="onb-tpl-dept">
          <Input id="onb-tpl-dept" value={meta.dept} onChange={e => setMeta(p => ({ ...p, dept: e.target.value }))} placeholder="Semua / Produksi / SDM" />
        </Isian>
        <Isian label="Durasi (hari)" htmlFor="onb-tpl-durasi">
          <Input id="onb-tpl-durasi" type="number" min={1} value={meta.duration_days} onChange={e => setMeta(p => ({ ...p, duration_days: +e.target.value }))} />
        </Isian>
      </div>
      <Isian label="Deskripsi" htmlFor="onb-tpl-desk">
        <Textarea id="onb-tpl-desk" rows={2} value={meta.description} onChange={e => setMeta(p => ({ ...p, description: e.target.value }))} />
      </Isian>
      <label className="flex items-center gap-3 text-sm" htmlFor="onb-tpl-bawaan">
        <Switch id="onb-tpl-bawaan" checked={meta.is_default} onCheckedChange={v => setMeta(p => ({ ...p, is_default: v }))} />
        <span>Jadikan templat bawaan (dipakai otomatis saat pelamar diterima)</span>
      </label>

      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="text-sm font-medium text-foreground">Daftar aktivitas</p>
            <p className="text-xs text-muted-foreground">{tasks.length} aktivitas · diurutkan menurut hari</p>
          </div>
          <Button type="button" size="sm" variant="outline" onClick={() => setShowAddTask(!showAddTask)}>
            <Plus />Tambah aktivitas
          </Button>
        </div>

        {showAddTask && (
          <div className="space-y-2 rounded-lg border border-[var(--glass-border)] p-3">
            <Input autoFocus value={addTaskForm.title} onChange={e => setAddTaskForm(p => ({ ...p, title: e.target.value }))} placeholder="Nama aktivitas" />
            <div className="grid gap-2 sm:grid-cols-2">
              <SmartNativeSelect searchable={false} value={addTaskForm.category} onChange={e => setAddTaskForm(p => ({ ...p, category: e.target.value }))}>
                {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
              </SmartNativeSelect>
              <Input value={addTaskForm.assigned_to} onChange={e => setAddTaskForm(p => ({ ...p, assigned_to: e.target.value }))} placeholder="Penanggung jawab (SDM/IT/karyawan)" />
              <div className="flex items-center gap-2">
                <span className="whitespace-nowrap text-sm text-muted-foreground">Hari ke-</span>
                <Input type="number" min={0} value={addTaskForm.day} onChange={e => setAddTaskForm(p => ({ ...p, day: +e.target.value }))} />
              </div>
              <Input value={addTaskForm.description} onChange={e => setAddTaskForm(p => ({ ...p, description: e.target.value }))} placeholder="Deskripsi (opsional)" />
            </div>
            <div className="flex justify-end gap-2">
              <Button type="button" size="sm" variant="outline" onClick={() => setShowAddTask(false)}>Batal</Button>
              <Button type="button" size="sm" onClick={handleAddTask} disabled={!addTaskForm.title.trim()}>Tambah</Button>
            </div>
          </div>
        )}

        {tasks.length === 0 ? (
          <p className="rounded-lg border border-dashed border-[var(--glass-border)] py-6 text-center text-sm text-muted-foreground">
            Templat ini belum punya aktivitas. Klik "Tambah aktivitas" untuk mulai.
          </p>
        ) : (
          <ul className="divide-y divide-[var(--glass-border)] rounded-lg border border-[var(--glass-border)]">
            {tasks.map((t, i) => <TemplateTaskRow key={t.task_id || i} task={t} index={i} onDelete={handleDeleteTask} onEdit={handleEditTask} />)}
          </ul>
        )}
      </div>
    </FormPopup>
  );
}

/** Isi satu tab: cetakan PageLayout di dalam hub. */
function IsiTab({ actions, filters, tools, summary, children }) {
  return <PageLayout actions={actions} filters={filters} tools={tools} summary={summary}>{children}</PageLayout>;
}

const ringkasKategori = (tasks = []) => Object.entries(tasks.reduce((acc, task) => {
  const cat = task.category || 'Umum';
  acc[cat] = (acc[cat] || 0) + 1;
  return acc;
}, {})).map(([cat, n]) => `${cat} ${n}`).join(' · ');

// ────────────────────────────────────────────────────────────────────────────
// MAIN MODULE
// ────────────────────────────────────────────────────────────────────────────
export default function HROnboardingModule({ token }) {
  const [tab, setTab] = useState('checklists');
  const [checklists, setChecklists] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const [editTemplate, setEditTemplate] = useState(undefined);  // undefined=closed, null=new, obj=edit
  const [form, setForm] = useState({ employee_id: '', employee_name: '', employee_dept: '', employee_position: '', template_id: '', buddy: '', supervisor: '', notes: '' });
  const [saving, setSaving] = useState(false);
  const [q, setQ] = useState('');
  const [filterStatus, setFilterStatus] = useState('');

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);
  // Tahap 5 (2026-11-07): karyawan baru, buddy, dan supervisor DIPILIH dari data karyawan (dulu nama diketik
  // bebas dan employee_id selalu kosong — checklist tidak terhubung ke karyawannya).
  const { employees } = useActiveEmployees(token);
  const pickNewEmployee = (id) => {
    const e = employees.find(x => x.id === id);
    setForm(p => ({ ...p, employee_id: id, employee_name: e?.name || '', employee_dept: e?.department || '', employee_position: e?.job_title || '' }));
  };
  const empIdByName = (name) => (employees.find(e => e.name === name) || {}).id || '';
  const nameOf = (id) => (employees.find(e => e.id === id) || {}).name || '';

  const refreshAll = useCallback(async () => {
    try {
      const [cl, tRes, aRes] = await Promise.all([
        ambilSemuaChecklist(headers),
        api(`/templates`, { headers }),
        api(`/analytics`, { headers }),
      ]);
      const [tpl, an] = await Promise.all([tRes.json(), aRes.json()]);
      setChecklists(cl);
      setTemplates(tpl.templates || []);
      setAnalytics(an);
      setError(null);
    } catch (e) { setError(e.message); }
  }, [headers]);

  // ── Effects
  useEffect(() => {
    (async () => {
      setLoading(true);
      await refreshAll();
      setLoading(false);
    })();
  }, [refreshAll]);

  const handleSeed = async () => {
    // Tahap 5: data contoh hanya untuk onboarding yang masih kosong (server menolak bila sudah ada data)
    if (!(await confirmDialog({ title: 'Muat data contoh onboarding?', body: 'Hanya bisa bila belum ada templat dan checklist.', confirmLabel: 'Muat contoh' }))) return;
    setSeeding(true);
    try {
      const r = await api(`/seed`, { method: 'POST', headers });
      if (!r.ok) { const d = await r.json().catch(() => ({})); toast.error(typeof d.detail === 'string' ? d.detail : 'Gagal memuat contoh'); return; }
      await refreshAll();
      toast.success('Data contoh dimuat');
    } catch { toast.error('Gagal'); }
    finally { setSeeding(false); }
  };

  const handleSave = async () => {
    if (!form.employee_id) { toast.error('Pilih karyawan dulu'); return; }
    setSaving(true);
    try {
      const r = await api(`/checklists`, { method: 'POST', headers, body: JSON.stringify(form) });
      if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(typeof d.detail === 'string' ? d.detail : `HTTP ${r.status}`); }  // 2026-11-06 (pola P6): sukses hanya bila server menerima
      setShowForm(false);
      await refreshAll();
      toast.success('Checklist onboarding dibuat');
    } catch (e) { toast.error(`Gagal membuat checklist${e?.message && !e.message.startsWith('HTTP') ? `: ${e.message}` : ''}`); } finally { setSaving(false); }
  };

  const handleUpdateChecklist = (updated) => {
    setChecklists(prev => prev.map(c => c.checklist_id === updated.checklist_id ? updated : c));
    setSelected(updated);
  };

  const handleDeleteTemplate = async (tplId, name) => {
    if (!(await confirmDialog({ title: `Hapus templat "${name}"?`, confirmLabel: 'Hapus', danger: true }))) return false;
    try {
      const r = await api(`/templates/${tplId}`, { method: 'DELETE', headers });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);  // 2026-11-06 (pola P6): sukses hanya bila server menerima
      await refreshAll();
      toast.success('Templat dihapus');
      return true;
    } catch { toast.error('Gagal menghapus'); return false; }
  };

  const filtered = useMemo(() =>
    checklists.filter(c => {
      if (filterStatus && c.status !== filterStatus) return false;
      if (q && !c.employee_name?.toLowerCase().includes(q.toLowerCase())) return false;
      return true;
    }),
  [checklists, q, filterStatus]);

  const s = analytics?.summary || {};
  const ringkasan = analytics && (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <StatTile label="Sedang berjalan" value={s.active ?? 0} sub={`Dari ${s.total ?? 0} checklist, status aktif.`} />
      <StatTile label="Selesai" value={s.completed ?? 0} sub="Semua tugas sudah dikerjakan." />
      <StatTile label="Lewat target" value={s.overdue ?? 0} accent={s.overdue ? 'danger' : 'default'}
        sub="Masih aktif tetapi tanggal target sudah lewat." />
      <StatTile label="Rata-rata kemajuan" value={`${s.avg_progress || 0}%`} sub="Rata-rata semua checklist." />
    </div>
  );
  const muatUlang = (
    <Button variant="outline" size="icon" onClick={refreshAll} title="Muat ulang" aria-label="Muat ulang"><RefreshCw /></Button>
  );
  const galat = error && <Notice tone="danger" title="Gagal memuat data onboarding">{error}</Notice>;
  const memuat = <p className="py-10 text-center text-sm text-muted-foreground">Memuat onboarding…</p>;

  const kolomChecklist = [
    { kunci: 'karyawan', label: 'Karyawan', hp: 'judul', isi: (c) => (
      <div className="min-w-0" data-testid={`checklist-card-${c.checklist_id}`}>
        <p className="font-medium text-foreground">{c.employee_name}</p>
        <p className="text-xs text-muted-foreground">{[c.employee_position, c.employee_dept].filter(Boolean).join(' · ') || '—'}</p>
      </div>) },
    { kunci: 'status', label: 'Status', isi: (c) => <Status status={c.status} /> },
    { kunci: 'kemajuan', label: 'Kemajuan', isi: (c) => (
      <div className="w-40 max-w-full">
        <ProgressBar pct={c.progress_pct} />
        <p className="text-xs text-muted-foreground">{c.completed_tasks ?? 0}/{c.total_tasks ?? 0} tugas selesai</p>
      </div>) },
    { kunci: 'target', label: 'Target', isi: (c) => <span className="text-sm md:whitespace-nowrap">{fmtDate(c.target_completion)}</span> },
    { kunci: 'buddy', label: 'Buddy', isi: (c) => <span className="text-sm">{c.buddy || '—'}</span> },
  ];
  const kolomTemplate = [
    { kunci: 'nama', label: 'Templat', hp: 'judul', isi: (t) => (
      <div className="min-w-0 md:max-w-[24rem]">
        <p className="font-medium text-foreground">
          {t.name}
          {t.is_default && <StatusBadge className="ml-2 align-middle" status="default" label="Bawaan" tone="primary" />}
        </p>
        {t.description && <p className="truncate text-xs text-muted-foreground" title={t.description}>{t.description}</p>}
      </div>) },
    { kunci: 'dept', label: 'Departemen', isi: (t) => <span className="text-sm">{t.dept || '—'}</span> },
    { kunci: 'durasi', label: 'Durasi', rata: 'kanan', isi: (t) => <span className="tabular-nums">{t.duration_days} hari</span> },
    { kunci: 'tugas', label: 'Tugas', rata: 'kanan', isi: (t) => <span className="tabular-nums">{(t.tasks || []).length}</span> },
    { kunci: 'kategori', label: 'Kategori', isi: (t) => <span className="text-sm text-muted-foreground">{ringkasKategori(t.tasks) || '—'}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (t) => (
      <Button size="sm" variant="outline" onClick={() => setEditTemplate(t)} data-testid={`onb-template-edit-${t.template_id}`}><Pencil />Ubah</Button>) },
  ];

  return (
    <div data-testid="hr-onboarding-module">
      <HubTabs hubId="hr-onboarding" title="Onboarding"
        subtitle="Daftar tugas karyawan baru dari hari pertama sampai masa orientasi selesai."
        value={tab} onValueChange={setTab}
        tabs={[
          { key: 'checklists', label: `Checklist (${checklists.length})`, Component: IsiTab, props: {
            actions: <>
              <Button variant="outline" onClick={handleSeed} disabled={seeding}>{seeding ? 'Memuat…' : 'Muat contoh'}</Button>
              <Button onClick={() => setShowForm(true)} data-testid="onboarding-add-btn"><Plus />Onboarding baru</Button>
            </>,
            filters: <>
              <div className="relative w-full sm:w-64">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input value={q} onChange={e => setQ(e.target.value)} placeholder="Cari karyawan" className="pl-8" data-testid="onb-search" />
              </div>
              <SmartNativeSelect searchable={false} value={filterStatus} onChange={e => setFilterStatus(e.target.value)} className="w-40">
                <option value="">Semua status</option>
                <option value="active">Aktif</option>
                <option value="in_progress">Berjalan</option>
                <option value="completed">Selesai</option>
                <option value="paused">Ditunda</option>
              </SmartNativeSelect>
            </>,
            tools: <>
              <TombolUnduh namaBerkas="checklist-onboarding" namaLembar="Checklist" baris={filtered} testId="onb-unduh"
                kolom={[
                  { label: 'Karyawan', nilai: (c) => c.employee_name || '' },
                  { label: 'Jabatan', nilai: (c) => c.employee_position || '' },
                  { label: 'Departemen', nilai: (c) => c.employee_dept || '' },
                  { label: 'Status', nilai: (c) => labelStatus(c.status) },
                  { label: 'Kemajuan (%)', nilai: (c) => c.progress_pct || 0 },
                  { label: 'Tugas selesai', nilai: (c) => c.completed_tasks ?? 0 },
                  { label: 'Total tugas', nilai: (c) => c.total_tasks ?? 0 },
                  { label: 'Mulai', nilai: (c) => fmtDate(c.start_date) },
                  { label: 'Target', nilai: (c) => fmtDate(c.target_completion) },
                  { label: 'Buddy', nilai: (c) => c.buddy || '' },
                  { label: 'Supervisor', nilai: (c) => c.supervisor || '' },
                ]} />
              {muatUlang}
            </>,
            summary: ringkasan,
            children: <>
              {galat}
              {loading ? memuat : (
                <TabelData kolom={kolomChecklist} baris={filtered} kunci={(c) => c.checklist_id} onKlikBaris={setSelected} testId="onb-checklists"
                  kosong={<EmptyState title={checklists.length ? 'Tidak ada checklist yang cocok' : 'Belum ada checklist onboarding'}
                    description={checklists.length ? 'Ubah saringan atau kata pencarian.' : 'Buat checklist untuk karyawan baru, atau muat contoh.'}
                    action={!checklists.length && <Button onClick={() => setShowForm(true)}><Plus />Onboarding baru</Button>} />} />
              )}
            </>,
          } },
          { key: 'templates', label: `Templat (${templates.length})`, Component: IsiTab, props: {
            actions: <Button onClick={() => setEditTemplate(null)} data-testid="onb-template-add"><Plus />Templat baru</Button>,
            tools: <>
              <TombolUnduh namaBerkas="templat-onboarding" namaLembar="Templat" baris={templates} testId="onb-unduh-template"
                kolom={[
                  { label: 'Templat', nilai: (t) => t.name }, { label: 'Deskripsi', nilai: (t) => t.description || '' },
                  { label: 'Departemen', nilai: (t) => t.dept || '' }, { label: 'Durasi (hari)', nilai: (t) => t.duration_days },
                  { label: 'Jumlah tugas', nilai: (t) => (t.tasks || []).length }, { label: 'Kategori', nilai: (t) => ringkasKategori(t.tasks) },
                  { label: 'Bawaan', nilai: (t) => (t.is_default ? 'Ya' : 'Tidak') },
                ]} />
              {muatUlang}
            </>,
            children: loading ? memuat : (
              <TabelData kolom={kolomTemplate} baris={templates} kunci={(t) => t.template_id} onKlikBaris={setEditTemplate} testId="onb-templates"
                kosong={<EmptyState title="Belum ada templat" description="Templat berisi daftar tugas standar untuk karyawan baru."
                  action={<Button onClick={() => setEditTemplate(null)}><Plus />Buat templat pertama</Button>} />} />
            ),
          } },
          { key: 'analytics', label: 'Terbaru', Component: IsiTab, props: {
            tools: muatUlang, summary: ringkasan,
            children: (
              <TabelData kolom={kolomChecklist} baris={analytics?.recent || []} kunci={(c) => c.checklist_id} testId="onb-recent"
                onKlikBaris={(c) => { setTab('checklists'); setSelected(c); }}
                kosong={<EmptyState title="Belum ada onboarding" description="Lima checklist yang terakhir dibuat tampil di sini." />} />
            ),
          } },
        ]} />

      {/* DETAIL CHECKLIST */}
      {selected && (
        <ChecklistDetail cl={selected} headers={headers} onUpdate={handleUpdateChecklist} onClose={() => setSelected(null)} />
      )}

      {/* BUAT CHECKLIST */}
      <FormPopup open={showForm} onClose={() => setShowForm(false)} ukuran="pendek" onSimpan={handleSave} menyimpan={saving}
        bisaSimpan={!!form.employee_id} judul="Buat onboarding baru" labelSimpan="Buat checklist" testId="onb-form">
        <Isian label="Karyawan" wajib>
          <EmployeeSelect employees={employees} value={form.employee_id} onChange={pickNewEmployee} testId="onb-employee" className="w-full" />
        </Isian>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Jabatan">
            <p className="flex h-9 items-center text-sm text-muted-foreground" data-testid="onb-position">{form.employee_position || '— (dari data karyawan)'}</p>
          </Isian>
          <Isian label="Departemen">
            <p className="flex h-9 items-center text-sm text-muted-foreground" data-testid="onb-dept">{form.employee_dept || '— (dari data karyawan)'}</p>
          </Isian>
          <Isian label="Buddy">
            <EmployeeSelect employees={employees} value={empIdByName(form.buddy)} exclude={[form.employee_id]} placeholder="— Tanpa buddy —"
              onChange={v => setForm(p => ({ ...p, buddy: nameOf(v) }))} testId="onb-buddy" className="w-full" />
          </Isian>
          <Isian label="Supervisor">
            <EmployeeSelect employees={employees} value={empIdByName(form.supervisor)} exclude={[form.employee_id]} placeholder="— Tanpa supervisor —"
              onChange={v => setForm(p => ({ ...p, supervisor: nameOf(v) }))} testId="onb-supervisor" className="w-full" />
          </Isian>
        </div>
        <Isian label="Templat">
          <SmartNativeSelect value={form.template_id} onChange={e => setForm(p => ({ ...p, template_id: e.target.value }))}>
            <option value="">Pakai templat bawaan</option>
            {templates.map(t => <option key={t.template_id} value={t.template_id}>{t.name}{t.is_default ? ' (bawaan)' : ''}</option>)}
          </SmartNativeSelect>
        </Isian>
      </FormPopup>

      {/* EDITOR TEMPLATE */}
      {editTemplate !== undefined && (
        <TemplateEditorModal
          template={editTemplate}
          headers={headers}
          onSuccess={() => { setEditTemplate(undefined); refreshAll(); }}
          onClose={() => setEditTemplate(undefined)}
          onDelete={async (t) => { if (await handleDeleteTemplate(t.template_id, t.name)) setEditTemplate(undefined); }}
        />
      )}
    </div>
  );
}

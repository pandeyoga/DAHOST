/**
 * Templat tugas (tab di Manajemen Tugas, Portal Toko) — templat tugas berulang yang dibuat otomatis oleh penjadwal.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout (judul disembunyikan di hub), daftar = tabel (dulu kartu per templat)
 * + unduh, form = FormPopup panjang, pilihan = SmartNativeSelect, label Indonesia. Isi yang dikirim tidak berubah.
 * 10 Nov 2026: kolom Aksi = Ubah · Nonaktifkan/Aktifkan · Hapus (hapus permanen hanya bila templat belum pernah
 * menerbitkan tugas; bila sudah, layar menawarkan Nonaktifkan).
 */
import { useState, useEffect, useCallback } from 'react';
import { Plus, RefreshCw, Pencil, Power, PowerOff, Trash2, X } from 'lucide-react';
import { toast } from 'sonner';
import { hapusMaster } from '@/lib/hapusMaster';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { useMarketingAccounts } from '@/hooks/useMarketingAccounts';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatusBadge } from './moduleAtoms';
import { PRIORITAS, JENIS_TUGAS } from './TaskCard';

// 2026-11-07 (Tahap 6, MK1 — keputusan owner): tugas dari template diberikan ke PIC TOKO template itu
// (Kelola Akun). Isian lama "peran bawaan" (staff/pic) bukan peran yang ada dan membuat tugas otomatis
// tanpa penanggung jawab — diganti pilihan toko + keterangan penanggung jawab.
const ASSIGNEE_PIC_TOKO = 'pic_toko';

/** Kalimat penanggung jawab untuk toko terpilih (dipakai di form & daftar template). */
function assigneeText(acc) {
  if (!acc) return 'Belum ada toko — tugas dibuat tanpa penanggung jawab';
  return acc.pic_user_name
    ? `PIC toko: ${acc.pic_user_name}`
    : 'Toko ini belum punya PIC — tugas dibuat tanpa penanggung jawab';
}

const FREQUENCIES = [
  { value: 'daily', label: 'Setiap hari' },
  { value: 'weekly', label: 'Mingguan' },
  { value: 'monthly', label: 'Bulanan' },
  { value: 'one-time', label: 'Sekali' },
];

const TASK_TYPES = [
  { value: 'data_entry', label: 'Input data' },
  { value: 'review', label: 'Tinjauan' },
  { value: 'analysis', label: 'Analisis' },
  { value: 'reporting', label: 'Pelaporan' },
  { value: 'operational', label: 'Operasional' },
];

const PRIORITIES = [
  { value: 'high', label: 'Tinggi' },
  { value: 'medium', label: 'Sedang' },
  { value: 'low', label: 'Rendah' },
];

const DAYS = [
  { value: 'monday', label: 'Sen' },
  { value: 'tuesday', label: 'Sel' },
  { value: 'wednesday', label: 'Rab' },
  { value: 'thursday', label: 'Kam' },
  { value: 'friday', label: 'Jum' },
  { value: 'saturday', label: 'Sab' },
  { value: 'sunday', label: 'Min' },
];

function TemplateFormDialog({ open, onOpenChange, template, onSaved, token, accounts = [], byId = {} }) {
  const isEdit = !!template;
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState({
    template_name: '',
    title: '',
    description: '',
    task_type: 'data_entry',
    priority: 'medium',
    recurrence: 'daily',
    time: '09:00',
    days_of_week: [],
    day_of_month: 1,
    auto_create: true,
    account_id: '',
    is_active: true,
    checklist_template: [],
  });
  const [newChecklistItem, setNewChecklistItem] = useState('');
  const [galat, setGalat] = useState('');
  const storeOptions = accounts.filter(a => a.status === 'active' || a.id === form.account_id);
  const selectedStore = form.account_id ? byId[form.account_id] : null;

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  useEffect(() => {
    if (open) setGalat('');
    if (open && template) {
      const cfg = template.recurrence_config || {};
      setForm({
        template_name: template.template_name || '',
        title: template.title || '',
        description: template.description || '',
        task_type: template.task_type || 'data_entry',
        priority: template.priority || 'medium',
        recurrence: template.recurrence || 'daily',
        time: cfg.time || '09:00',
        days_of_week: cfg.days_of_week || [],
        day_of_month: cfg.day_of_month || 1,
        auto_create: cfg.auto_create !== false,
        account_id: template.account_id || '',
        is_active: template.is_active !== false,
        checklist_template: template.checklist_template || [],
      });
    } else if (open && !template) {
      setForm({
        template_name: '',
        title: '',
        description: '',
        task_type: 'data_entry',
        priority: 'medium',
        recurrence: 'daily',
        time: '09:00',
        days_of_week: [],
        day_of_month: 1,
        auto_create: true,
        account_id: '',
        is_active: true,
        checklist_template: [],
      });
      setNewChecklistItem('');
    }
  }, [open, template]);

  const toggleDay = (day) => {
    setForm(f => ({
      ...f,
      days_of_week: f.days_of_week.includes(day)
        ? f.days_of_week.filter(d => d !== day)
        : [...f.days_of_week, day],
    }));
  };

  const addChecklist = () => {
    if (!newChecklistItem.trim()) return;
    setForm(f => ({ ...f, checklist_template: [...f.checklist_template, newChecklistItem.trim()] }));
    setNewChecklistItem('');
  };

  const removeChecklist = (idx) => {
    setForm(f => ({ ...f, checklist_template: f.checklist_template.filter((_, i) => i !== idx) }));
  };

  const handleSubmit = async (e) => {
    e?.preventDefault?.();
    setGalat('');
    if (!form.template_name.trim()) {
      setGalat('Nama templat wajib diisi.');
      return;
    }
    if (!form.title.trim()) {
      setGalat('Judul tugas wajib diisi.');
      return;
    }

    setSubmitting(true);
    try {
      const recurrence_config = {
        frequency: form.recurrence,
        time: form.time,
        auto_create: form.auto_create,
      };
      if (form.recurrence === 'weekly') {
        recurrence_config.days_of_week = form.days_of_week;
      } else if (form.recurrence === 'monthly') {
        recurrence_config.day_of_month = parseInt(form.day_of_month, 10);
      }

      const payload = {
        template_name: form.template_name.trim(),
        title: form.title.trim(),
        description: form.description.trim() || null,
        task_type: form.task_type,
        priority: form.priority,
        recurrence: form.recurrence,
        recurrence_config,
        default_assigned_role: ASSIGNEE_PIC_TOKO,
        account_id: form.account_id || null,
        is_active: form.is_active,
        checklist_template: form.checklist_template,
      };

      const url = isEdit
        ? `/api/marketing/task-templates/${template.id}`
        : '/api/marketing/task-templates';
      const method = isEdit ? 'PUT' : 'POST';

      const res = await fetch(url, { method, headers, body: JSON.stringify(payload) });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Gagal menyimpan templat');
      }

      toast.success(isEdit ? 'Templat disimpan.' : 'Templat dibuat.');
      onOpenChange(false);
      if (onSaved) onSaved();
    } catch (err) {
      setGalat(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <FormPopup open={open} onClose={() => onOpenChange(false)} ukuran="panjang" testId="template-form"
      judul={isEdit ? 'Ubah templat tugas' : 'Buat templat tugas'} keterangan="Templat untuk membuat tugas otomatis berulang sesuai jadwal."
      onSimpan={handleSubmit} menyimpan={submitting} galat={galat} labelSimpan={isEdit ? 'Simpan' : 'Buat templat'}>
      <Isian label="Nama templat" wajib htmlFor="tpl-name">
        <Input id="tpl-name" value={form.template_name} onChange={e => setForm(f => ({ ...f, template_name: e.target.value }))}
          placeholder="Input penjualan harian Shopee" data-testid="tpl-name-input" />
      </Isian>
      <Isian label="Judul tugas" wajib htmlFor="tpl-title">
        <Input id="tpl-title" value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
          placeholder="Input penjualan harian - Shopee Official Store" data-testid="tpl-title-input" />
      </Isian>
      <Isian label="Deskripsi" htmlFor="tpl-desc">
        <Textarea id="tpl-desc" value={form.description} rows={2} onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
          data-testid="tpl-desc-input" />
      </Isian>
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Jenis" htmlFor="tpl-type">
          <SmartNativeSelect id="tpl-type" value={form.task_type} searchable={false}
            onChange={(e) => setForm(f => ({ ...f, task_type: e.target.value }))} data-testid="tpl-type-select">
            {TASK_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Prioritas" htmlFor="tpl-priority">
          <SmartNativeSelect id="tpl-priority" value={form.priority} searchable={false}
            onChange={(e) => setForm(f => ({ ...f, priority: e.target.value }))} data-testid="tpl-priority-select">
            {PRIORITIES.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Pengulangan" htmlFor="tpl-recurrence">
          <SmartNativeSelect id="tpl-recurrence" value={form.recurrence} searchable={false}
            onChange={(e) => setForm(f => ({ ...f, recurrence: e.target.value }))} data-testid="tpl-recurrence-select">
            {FREQUENCIES.map(fr => <option key={fr.value} value={fr.value}>{fr.label}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Jam" htmlFor="tpl-time">
          <Input id="tpl-time" type="time" value={form.time} onChange={e => setForm(f => ({ ...f, time: e.target.value }))}
            data-testid="tpl-time-input" />
        </Isian>
      </div>
      {form.recurrence === 'weekly' && (
        <Isian label="Hari" petunjuk="Boleh lebih dari satu.">
          <div className="flex flex-wrap gap-1.5">
            {DAYS.map(d => (
              <Button key={d.value} type="button" size="sm" variant={form.days_of_week.includes(d.value) ? 'default' : 'outline'}
                aria-pressed={form.days_of_week.includes(d.value)} onClick={() => toggleDay(d.value)} data-testid={`day-toggle-${d.value}`}>
                {d.label}
              </Button>
            ))}
          </div>
        </Isian>
      )}
      {form.recurrence === 'monthly' && (
        <Isian label="Tanggal dalam bulan (1–31)" htmlFor="tpl-day-of-month">
          <Input id="tpl-day-of-month" type="number" min="1" max="31" value={form.day_of_month} className="w-28"
            onChange={e => setForm(f => ({ ...f, day_of_month: e.target.value }))} data-testid="tpl-day-month-input" />
        </Isian>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Toko" htmlFor="tpl-store">
          <SmartNativeSelect id="tpl-store" value={form.account_id} onChange={e => setForm(f => ({ ...f, account_id: e.target.value }))}
            className="w-full" data-testid="tpl-store-select">
            <option value="">Tanpa toko</option>
            {storeOptions.map(a => (
              <option key={a.id} value={a.id}>{`${a.account_code ? `${a.account_code} · ` : ''}${a.account_name}`}</option>
            ))}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Penanggung jawab">
          <p className="flex h-9 items-center text-sm text-foreground" data-testid="tpl-assignee-text">{assigneeText(selectedStore)}</p>
        </Isian>
      </div>
      <div className="flex flex-wrap gap-6">
        <label className="flex items-center gap-2 text-sm">
          <Switch checked={form.auto_create} onCheckedChange={(v) => setForm(f => ({ ...f, auto_create: v }))} data-testid="tpl-auto-switch" />
          Buat tugas otomatis
        </label>
        <label className="flex items-center gap-2 text-sm">
          <Switch checked={form.is_active} onCheckedChange={(v) => setForm(f => ({ ...f, is_active: v }))} data-testid="tpl-active-switch" />
          Aktif
        </label>
      </div>
      <Isian label="Daftar periksa templat" htmlFor="tpl-checklist">
        <div className="flex gap-2">
          <Input id="tpl-checklist" value={newChecklistItem} onChange={e => setNewChecklistItem(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addChecklist(); } }}
            placeholder="Tambah butir daftar periksa" data-testid="tpl-checklist-input" />
          <Button type="button" onClick={addChecklist} size="icon" variant="outline" title="Tambah butir" aria-label="Tambah butir"><Plus /></Button>
        </div>
        {form.checklist_template.length > 0 && (
          <ul className="max-h-32 space-y-1 overflow-auto">
            {form.checklist_template.map((c, i) => (
              <li key={i} className="flex items-center justify-between gap-2 border-b border-[var(--glass-border)] py-1.5">
                <span className="flex-1 truncate text-sm">{c}</span>
                <Button type="button" variant="ghost" size="icon-sm" onClick={() => removeChecklist(i)} title="Hapus butir" aria-label="Hapus butir"><X /></Button>
              </li>
            ))}
          </ul>
        )}
      </Isian>
    </FormPopup>
  );
}

export default function TaskTemplatesModule({ token }) {
  const [loading, setLoading] = useState(true);
  const [templates, setTemplates] = useState([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editTpl, setEditTpl] = useState(null);
  const { accounts, byId } = useMarketingAccounts(token, { status: 'all' });

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchTemplates = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/marketing/task-templates', { headers });
      if (res.ok) {
        setTemplates(await res.json());
      }
    } catch (e) {
      toast.error('Gagal memuat templat');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    fetchTemplates();
  }, [fetchTemplates]);

  const toggleActive = async (tpl) => {
    try {
      // For deactivate use DELETE; for activate, PUT with is_active=true
      if (tpl.is_active) {
        const res = await fetch(`/api/marketing/task-templates/${tpl.id}`, {
          method: 'DELETE', headers,
        });
        if (!res.ok) throw new Error('Gagal menonaktifkan');
        toast.success('Templat dinonaktifkan.');
      } else {
        const payload = {
          template_name: tpl.template_name,
          title: tpl.title,
          description: tpl.description,
          task_type: tpl.task_type,
          recurrence: tpl.recurrence,
          recurrence_config: tpl.recurrence_config,
          default_assigned_role: ASSIGNEE_PIC_TOKO,
          account_id: tpl.account_id || null,
          priority: tpl.priority,
          checklist_template: tpl.checklist_template || [],
          is_active: true,
        };
        const res = await fetch(`/api/marketing/task-templates/${tpl.id}`, {
          method: 'PUT', headers, body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error('Gagal mengaktifkan');
        toast.success('Templat diaktifkan.');
      }
      fetchTemplates();
    } catch (e) {
      toast.error(e.message);
    }
  };

  // 10 Nov 2026 — Hapus permanen hanya bila templat belum pernah menerbitkan tugas; bila sudah (409) tawarkan
  // Nonaktifkan (DELETE tanpa `hard` = perilaku lama: is_active=false).
  const hapusTemplat = async (tpl) => {
    const kirim = async (hard) => {
      const res = await fetch(`/api/marketing/task-templates/${tpl.id}${hard ? '?hard=true' : ''}`, { method: 'DELETE', headers });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        const e = new Error((typeof d.detail === 'string' && d.detail) || (hard ? 'Gagal menghapus templat' : 'Gagal menonaktifkan'));
        e.status = res.status;
        throw e;
      }
    };
    const hasil = await hapusMaster({
      jenis: 'templat', nama: tpl.template_name,
      keterangan: 'Templat dihapus permanen. Bila templat sudah pernah menerbitkan tugas, penghapusan ditolak'
        + (tpl.is_active ? ' dan Anda bisa menonaktifkannya saja (tugas tidak dibuat lagi).' : '.'),
      hapus: () => kirim(true),
      nonaktifkan: tpl.is_active ? () => kirim(false) : null,
    });
    if (hasil) fetchTemplates();
  };

  const recurrenceLabel = (tpl) => {
    const cfg = tpl.recurrence_config || {};
    const hari = (cfg.days_of_week || []).map((d) => DAYS.find((x) => x.value === d)?.label || d).join(', ');
    if (tpl.recurrence === 'daily') return `Harian, pukul ${cfg.time || '09:00'}`;
    if (tpl.recurrence === 'weekly') return `Mingguan (${hari || '-'}), pukul ${cfg.time || '09:00'}`;
    if (tpl.recurrence === 'monthly') return `Bulanan tgl ${cfg.day_of_month || 1}, pukul ${cfg.time || '09:00'}`;
    return 'Sekali';
  };

  const bukaBaru = () => { setEditTpl(null); setDialogOpen(true); };
  const namaToko = (tpl) => (tpl.account_id && byId[tpl.account_id] ? byId[tpl.account_id].account_name : '—');
  const kolom = [
    { kunci: 'nama', label: 'Templat', hp: 'judul', isi: (tpl) => (
      <div className="min-w-0 md:max-w-[20rem]" data-testid={`template-row-${tpl.id}`}>
        <p className="truncate font-medium">{tpl.template_name}</p>
        <p className="truncate text-xs text-muted-foreground">{tpl.title}</p>
      </div>) },
    { kunci: 'jadwal', label: 'Jadwal', hp: 'keterangan', isi: (tpl) => <span className="md:whitespace-nowrap">{recurrenceLabel(tpl)}</span> },
    { kunci: 'jenis', label: 'Jenis / prioritas', isi: (tpl) => (
      <span className="flex flex-wrap gap-1">
        <StatusBadge status={tpl.task_type} label={JENIS_TUGAS[tpl.task_type] || 'Lainnya'} tone="muted" />
        <StatusBadge status={tpl.priority} label={(PRIORITAS[tpl.priority] || [tpl.priority || '—'])[0]} tone={(PRIORITAS[tpl.priority] || [])[1]} />
      </span>) },
    { kunci: 'pj', label: 'Toko · penanggung jawab', isi: (tpl) => (
      <span className="text-sm" data-testid={`tpl-assignee-${tpl.id}`}>
        {tpl.account_id && byId[tpl.account_id] ? `${byId[tpl.account_id].account_name} · ` : ''}
        {assigneeText(tpl.account_id ? byId[tpl.account_id] : null)}
      </span>) },
    { kunci: 'status', label: 'Status', isi: (tpl) => (tpl.is_active
      ? <StatusBadge status="aktif" label="Aktif" tone="success" /> : <StatusBadge status="nonaktif" label="Nonaktif" tone="muted" />) },
    { kunci: 'aksi', label: 'Aksi', rata: 'kanan', hp: 'aksi', isi: (tpl) => (
      <div className="flex justify-end gap-1">
        <Button size="icon-sm" variant="ghost" onClick={() => { setEditTpl(tpl); setDialogOpen(true); }}
          title="Ubah templat" aria-label="Ubah templat" data-testid={`edit-tpl-${tpl.id}`}><Pencil /></Button>
        <Button size="icon-sm" variant="ghost" onClick={() => toggleActive(tpl)} data-testid={`toggle-tpl-${tpl.id}`}
          title={tpl.is_active ? 'Nonaktifkan templat' : 'Aktifkan templat'} aria-label={tpl.is_active ? 'Nonaktifkan templat' : 'Aktifkan templat'}>
          {tpl.is_active ? <PowerOff /> : <Power />}
        </Button>
        <Button size="icon-sm" variant="ghost" className="text-[hsl(var(--danger-text))]" onClick={() => hapusTemplat(tpl)}
          title="Hapus templat" aria-label="Hapus templat" data-testid={`delete-tpl-${tpl.id}`}><Trash2 /></Button>
      </div>) },
  ];

  return (
    <PageLayout testId="task-templates-module" title="Templat tugas"
      subtitle="Templat tugas berulang (harian/mingguan/bulanan) yang dibuat otomatis oleh penjadwal."
      actions={<Button onClick={bukaBaru} data-testid="create-template-btn"><Plus />Buat templat</Button>}
      tools={<>
        <TombolUnduh namaBerkas="templat-tugas" namaLembar="Templat" baris={templates} testId="template-unduh"
          kolom={[
            { label: 'Nama templat', nilai: (tpl) => tpl.template_name },
            { label: 'Judul tugas', nilai: (tpl) => tpl.title },
            { label: 'Jadwal', nilai: recurrenceLabel },
            { label: 'Jenis', nilai: (tpl) => JENIS_TUGAS[tpl.task_type] || 'Lainnya' },
            { label: 'Prioritas', nilai: (tpl) => (PRIORITAS[tpl.priority] || [tpl.priority || ''])[0] },
            { label: 'Toko', nilai: namaToko },
            { label: 'Penanggung jawab', nilai: (tpl) => assigneeText(tpl.account_id ? byId[tpl.account_id] : null) },
            { label: 'Daftar periksa', nilai: (tpl) => (tpl.checklist_template || []).length },
            { label: 'Status', nilai: (tpl) => (tpl.is_active ? 'Aktif' : 'Nonaktif') },
          ]} />
        <Button onClick={fetchTemplates} variant="outline" size="icon" title="Muat ulang" aria-label="Muat ulang" data-testid="refresh-templates-btn">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}>
      {loading && templates.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat templat…</p>
      ) : (
        <TabelData kolom={kolom} baris={templates} onKlikBaris={(tpl) => { setEditTpl(tpl); setDialogOpen(true); }} testId="template-table"
          kosong={<EmptyState title="Belum ada templat tugas" description="Buat templat untuk tugas yang berulang setiap hari, pekan, atau bulan."
            action={<Button onClick={bukaBaru} data-testid="create-first-template-btn"><Plus />Buat templat pertama</Button>} />} />
      )}

      <TemplateFormDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        template={editTpl}
        onSaved={fetchTemplates}
        token={token}
        accounts={accounts}
        byId={byId}
      />
    </PageLayout>
  );
}

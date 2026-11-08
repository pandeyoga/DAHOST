/**
 * CreateTaskDialog — form buat tugas marketing (dipakai Papan tugas).
 *
 * Standar UI/UX v2 (8 Nov 2026): FormPopup panjang (dulu Dialog buatan sendiri), isian di `Isian`, pilihan =
 * SmartNativeSelect, tenggat = DatePicker + jam (dulu input datetime-local bawaan peramban), galat di kaki form,
 * label Indonesia tanpa emoji. Isi yang dikirim (`payload`) tidak berubah.
 */
import { useState, useEffect, useMemo, useCallback } from 'react';
import { Plus, X, Zap } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import DatePicker from '@/components/ui/date-picker';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { todayWIB, fromWIBLocalInput } from '@/lib/waktu';

const API = process.env.REACT_APP_BACKEND_URL;

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

// Roles yang relevan untuk Marketing portal (untuk filter staff dropdown)
const MARKETING_ROLES = [
  'admin', 'owner', 'superadmin',
  'manager_marketing', 'manager_toko',
  'pic_marketing', 'pic_toko',
  'staff_marketing', 'marketing_kol', 'cs_staff',
];

const NAMA_PLATFORM = { shopee: 'Shopee', tiktok: 'TikTok', tokopedia: 'Tokopedia', instagram: 'Instagram', lazada: 'Lazada' };

export function CreateTaskDialog({ open, onOpenChange, onCreated, token, accounts = [] }) {
  const [submitting, setSubmitting] = useState(false);
  const [staffList, setStaffList] = useState([]);
  const [staffLoading, setStaffLoading] = useState(false);
  const [form, setForm] = useState({
    title: '',
    description: '',
    task_type: 'data_entry',
    priority: 'medium',
    assigned_to: '',
    account_id: '',
    due_date: '',
    checklist: [],
    // Actionable task fields
    related_entity: '',  // '' | sales_data | return | review | manual_check
    action_type: '',     // '' | submit_form | approve_reject | review_content | manual_check
    related_entity_id: '',  // optional UUID
  });
  const [newChecklistItem, setNewChecklistItem] = useState('');
  const [galat, setGalat] = useState('');

  const headers = useMemo(
    () => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }),
    [token]
  );

  // Fetch staff list for assignment dropdown
  const fetchStaff = useCallback(async () => {
    setStaffLoading(true);
    try {
      const params = new URLSearchParams();
      params.append('role', MARKETING_ROLES.join(','));
      params.append('status', 'active');
      const res = await fetch(`${API}/api/auth/users?${params.toString()}`, { headers });
      if (res.ok) {
        const data = await res.json();
        setStaffList(Array.isArray(data) ? data : []);
      }
    } catch (e) {
      // silent — fallback to empty list
    } finally {
      setStaffLoading(false);
    }
  }, [headers]);

  useEffect(() => {
    if (open) {
      fetchStaff();
    } else {
      // reset on close
      setForm({
        title: '',
        description: '',
        task_type: 'data_entry',
        priority: 'medium',
        assigned_to: '',
        account_id: '',
        due_date: '',
        checklist: [],
        related_entity: '',
        action_type: '',
        related_entity_id: '',
      });
      setNewChecklistItem('');
      setGalat('');
    }
  }, [open, fetchStaff]);

  const addChecklist = () => {
    if (!newChecklistItem.trim()) return;
    setForm(f => ({ ...f, checklist: [...f.checklist, { item: newChecklistItem.trim(), completed: false }] }));
    setNewChecklistItem('');
  };

  const removeChecklist = (idx) => {
    setForm(f => ({ ...f, checklist: f.checklist.filter((_, i) => i !== idx) }));
  };

  const handleSubmit = async (e) => {
    e?.preventDefault?.();
    setGalat('');
    if (!form.title.trim()) {
      setGalat('Judul tugas wajib diisi.');
      return;
    }

    // Validation: data_entry tasks should have account
    if (form.task_type === 'data_entry' && !form.account_id) {
      setGalat('Tugas jenis "Input data" wajib memilih akun toko.');
      return;
    }

    setSubmitting(true);
    try {
      // Auto-determine action_type from related_entity if not set
      let action_type = form.action_type;
      if (!action_type && form.related_entity) {
        const mapping = {
          'sales_data': 'submit_form',
          'return': 'approve_reject',
          'review': 'review_content',
          'manual_check': 'manual_check',
        };
        action_type = mapping[form.related_entity] || 'manual_check';
      }

      // Build related_form_data for pre-fill
      let related_form_data = null;
      if (form.related_entity === 'sales_data' && form.account_id) {
        related_form_data = {
          account_id: form.account_id,
          date: todayWIB(),
        };
      }

      const payload = {
        title: form.title.trim(),
        description: form.description.trim() || null,
        task_type: form.task_type,
        priority: form.priority,
        assigned_to: form.assigned_to || null,
        account_id: form.account_id || null,
        due_date: fromWIBLocalInput(form.due_date),
        checklist: form.checklist,
        recurrence: 'one-time',
        related_entity: form.related_entity || null,
        related_entity_id: form.related_entity_id || null,
        related_form_data,
        action_type: action_type || null,
      };

      const res = await fetch(`${API}/api/marketing/tasks`, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Gagal membuat tugas');
      }

      toast.success('Tugas dibuat.');
      onOpenChange(false);
      if (onCreated) onCreated();
    } catch (err) {
      setGalat(err.message || 'Gagal membuat tugas');
    } finally {
      setSubmitting(false);
    }
  };

  // Tenggat: tanggal (DatePicker) + jam; disimpan dalam format lama "YYYY-MM-DDTHH:mm" untuk fromWIBLocalInput.
  const tglTenggat = (form.due_date || '').slice(0, 10);
  const jamTenggat = (form.due_date || '').slice(11, 16);
  const aturTenggat = (ymd, jam) => setForm(f => ({ ...f, due_date: ymd ? `${ymd}T${jam || '23:59'}` : '' }));

  return (
    <FormPopup open={open} onClose={() => onOpenChange(false)} ukuran="panjang" judul="Buat tugas baru"
      keterangan="Tugas masuk ke kolom Akan dikerjakan." onSimpan={handleSubmit} menyimpan={submitting}
      galat={galat} labelSimpan="Buat tugas" testId="create-task-dialog">
      <Isian label="Judul tugas" wajib htmlFor="task-title">
        <Input id="task-title" value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
          placeholder="Contoh: Input penjualan Shopee Official" data-testid="task-title-input" />
      </Isian>
      <Isian label="Deskripsi" htmlFor="task-desc">
        <Textarea id="task-desc" value={form.description} rows={3} placeholder="Langkah-langkah atau catatan"
          onChange={e => setForm(f => ({ ...f, description: e.target.value }))} data-testid="task-desc-input" />
      </Isian>
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Jenis" htmlFor="task-type">
          <SmartNativeSelect id="task-type" value={form.task_type} searchable={false}
            onChange={(e) => setForm(f => ({ ...f, task_type: e.target.value }))} data-testid="task-type-select">
            {TASK_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Prioritas" htmlFor="task-priority">
          <SmartNativeSelect id="task-priority" value={form.priority} searchable={false}
            onChange={(e) => setForm(f => ({ ...f, priority: e.target.value }))} data-testid="task-priority-select">
            {PRIORITIES.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Penanggung jawab" htmlFor="task-assigned"
          petunjuk={staffList.length === 0 && !staffLoading ? 'Belum ada staf marketing aktif.' : undefined}>
          <SmartNativeSelect id="task-assigned" value={form.assigned_to || ''}
            onChange={(e) => setForm(f => ({ ...f, assigned_to: e.target.value }))} data-testid="task-assigned-select">
            <option value="">{staffLoading ? 'Memuat…' : 'Belum ditugaskan'}</option>
            {staffList.map(staff => <option key={staff.id} value={staff.id}>{staff.name || staff.email}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Tenggat" petunjuk="Tanpa jam = sampai 23.59 WIB.">
          <div className="flex gap-2">
            <div className="min-w-0 flex-1">
              <DatePicker value={tglTenggat} onChange={(v) => aturTenggat(v, jamTenggat)} placeholder="Tanpa tenggat" testId="task-due-input" />
            </div>
            <Input type="time" className="w-32" value={jamTenggat} disabled={!tglTenggat} aria-label="Jam tenggat"
              onChange={(e) => aturTenggat(tglTenggat, e.target.value)} data-testid="task-due-time" />
          </div>
        </Isian>
      <Isian label="Akun / toko marketplace" wajib={form.task_type === 'data_entry'} htmlFor="task-account"
        galat={form.task_type === 'data_entry' && !form.account_id ? 'Tugas jenis Input data wajib memilih akun toko.' : undefined}>
        <SmartNativeSelect id="task-account" value={form.account_id || ''}
          onChange={(e) => setForm(f => ({ ...f, account_id: e.target.value }))} data-testid="task-account-select">
          <option value="">{accounts.length === 0 ? 'Belum ada akun aktif' : 'Tidak terkait akun'}</option>
          {accounts.map(acc => <option key={acc.id} value={acc.id}>{`${acc.account_name} · ${NAMA_PLATFORM[acc.platform] || acc.platform}`}</option>)}
        </SmartNativeSelect>
      </Isian>
      </div>

      {/* ── AKSI DALAM SISTEM (opsional) ── */}
      <div className="space-y-3 border-t border-[var(--glass-border)] pt-3">
        <Isian label="Aksi dalam sistem (opsional)" htmlFor="task-action" className="sm:w-1/2 sm:pr-2"
          petunjuk="Pilih bila tugas perlu menjalankan aksi langsung dari papan, bukan sekadar pengingat.">
          <SmartNativeSelect id="task-action" value={form.related_entity || ''} searchable={false}
            onChange={(e) => setForm(f => ({ ...f, related_entity: e.target.value }))} data-testid="task-action-entity-select">
            <option value="">Tanpa aksi (hanya pengingat)</option>
            <option value="sales_data">Isi data penjualan</option>
            <option value="return">Setujui / tolak retur</option>
            <option value="review">Balas ulasan</option>
            <option value="manual_check">Pemeriksaan manual</option>
          </SmartNativeSelect>
        </Isian>
        {(form.related_entity === 'return' || form.related_entity === 'review') && (
          <Isian label={`Nomor ${form.related_entity === 'return' ? 'retur' : 'ulasan'}`} wajib htmlFor="task-entity"
            petunjuk={`Salin dari menu ${form.related_entity === 'return' ? 'Komplain & Retur' : 'Rating & Ulasan'}.`}>
            <Input id="task-entity" value={form.related_entity_id} placeholder="Nomor data yang akan diproses"
              onChange={e => setForm(f => ({ ...f, related_entity_id: e.target.value }))} data-testid="task-entity-id-input" />
          </Isian>
        )}
        {form.related_entity === 'sales_data' && form.account_id && (
          <p className="flex items-center gap-1.5 text-sm text-[hsl(var(--success-text))]">
            <Zap className="h-4 w-4" />Akun terpilih jadi isian awal form penjualan. Staf cukup mengisi omzet/pesanan di papan.
          </p>
        )}
      </div>

      <Isian label="Daftar periksa" htmlFor="checklist-input">
        <div className="flex gap-2">
          <Input id="checklist-input" value={newChecklistItem} onChange={e => setNewChecklistItem(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addChecklist(); } }}
            placeholder="Tambah butir daftar periksa" data-testid="checklist-input" />
          <Button type="button" onClick={addChecklist} size="icon" variant="outline" data-testid="checklist-add-btn"
            title="Tambah butir" aria-label="Tambah butir"><Plus /></Button>
        </div>
        {form.checklist.length > 0 && (
          <ul className="max-h-32 space-y-1 overflow-auto">
            {form.checklist.map((c, i) => (
              <li key={i} className="flex items-center justify-between gap-2 border-b border-[var(--glass-border)] py-1.5">
                <span className="flex-1 truncate text-sm">{c.item}</span>
                <Button type="button" variant="ghost" size="icon-sm" onClick={() => removeChecklist(i)}
                  title="Hapus butir" aria-label="Hapus butir" data-testid={`checklist-remove-${i}`}><X /></Button>
              </li>
            ))}
          </ul>
        )}
      </Isian>
    </FormPopup>
  );
}

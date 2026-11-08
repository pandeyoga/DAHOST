/**
 * HRShiftManagementModule — Portal SDM › Shift: daftar shift dan penugasan shift ke karyawan.
 *
 * Standar UI/UX v2 (keputusan owner 8 Nov 2026; owner menunjuk layar ini: ruang kosong, kartu boros tempat):
 *  • cetakan PageLayout tanpa kepala ganda / kotak abu; di hub Shift, "Daftar shift" dan "Penugasan shift"
 *    kini tab hub sendiri (`bagian`), bukan tab di dalam tab. Tanpa `bagian` (menu lama) → pil penyaring.
 *  • kartu shift berulang → TabelData (kartu ringkas di HP) + unduh Excel/CSV; aksi baris Ubah + "Lainnya".
 *  • 4 kartu angka (salah satunya teks tetap "Fallback Default: Aktif", satu lagi "-") → satu kalimat ringkasan
 *    dari /api/hr/shifts/summary yang sama.
 *  • form shift & penugasan = FormPopup (dulu form di halaman), tanggal = DatePicker.
 * Data yang dikirim ke server tidak berubah. Daftar penugasan memuat sampai 500 (dulu batas bawaan API 100).
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import axios from 'axios';
import { Plus, RefreshCw, Pencil, Power, MoreHorizontal } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker, { formatTanggalID } from '@/components/ui/date-picker';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { todayWIB } from '@/lib/waktu';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatusBadge } from './moduleAtoms';
import { EmployeeSelect, useActiveEmployees, employeeLabel } from './hr/hrPickers';

const API = process.env.REACT_APP_BACKEND_URL;
const DAYS_ID = { Mon: 'Sen', Tue: 'Sel', Wed: 'Rab', Thu: 'Kam', Fri: 'Jum', Sat: 'Sab', Sun: 'Min' };
const ALL_DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const STATUS_PENUGASAN = { active: { label: 'Aktif', tone: 'success' }, inactive: { label: 'Nonaktif', tone: 'muted' }, ended: { label: 'Berakhir', tone: 'muted' } };

/** "Sen–Sab" bila berurutan, selain itu "Sen, Rab, Jum". */
function labelHari(days = []) {
  const idx = ALL_DAYS.map((d, i) => (days.includes(d) ? i : -1)).filter((i) => i >= 0);
  if (!idx.length) return '—';
  const urut = idx.every((v, i) => i === 0 || v === idx[i - 1] + 1);
  if (urut && idx.length > 2) return `${DAYS_ID[ALL_DAYS[idx[0]]]}–${DAYS_ID[ALL_DAYS[idx[idx.length - 1]]]}`;
  return idx.map((i) => DAYS_ID[ALL_DAYS[i]]).join(', ');
}

/** Kode shift dengan titik warna shift (warna adalah data shift, bukan hiasan layar). */
function ShiftKode({ code, color }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-sm font-medium text-foreground">
      <span className="h-2.5 w-2.5 shrink-0 rounded-full border border-[var(--glass-border)] bg-muted-foreground"
        style={color ? { backgroundColor: color } : undefined} aria-hidden="true" />
      {code || '—'}
    </span>
  );
}

function ShiftForm({ open, initial, onSave, onClose }) {
  const kosong = {
    shift_code: '', shift_name: '', start_time: '08:00', end_time: '17:00',
    break_duration_minutes: 60, days_active: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'], // pola P5 (2026-11-06): 6 hari kerja
    is_overnight: false, color: '#3b82f6', description: '',
  };
  const [form, setForm] = useState(initial || kosong);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { if (open) { setForm(initial || kosong); setError(''); } }, [open, initial]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleDay = (d) => setForm(p => ({
    ...p,
    days_active: p.days_active.includes(d) ? p.days_active.filter(x => x !== d) : [...p.days_active, d],
  }));

  const calcHours = () => {
    const [sh, sm] = (form.start_time || '08:00').split(':').map(Number);
    const [eh, em] = (form.end_time || '17:00').split(':').map(Number);
    let totalMin = (eh * 60 + em) - (sh * 60 + sm);
    if (form.is_overnight || totalMin <= 0) totalMin += 24 * 60;
    return Math.max(0, ((totalMin - (form.break_duration_minutes || 60)) / 60).toFixed(1));
  };

  const handleSubmit = async () => {
    if (!form.shift_code || !form.shift_name || !form.start_time || !form.end_time) {
      setError('Kode shift, nama, jam mulai, dan jam selesai wajib diisi.'); return;
    }
    setSaving(true); setError('');
    try {
      await onSave({ ...form, break_duration_minutes: parseInt(form.break_duration_minutes) });
    } catch (e) {
      setError(e.response?.data?.detail || 'Gagal menyimpan');
    } finally { setSaving(false); }
  };

  return (
    <FormPopup open={open} onClose={onClose} ukuran="panjang" testId="shift-form"
      judul={initial ? `Ubah shift ${initial.shift_code || ''}`.trim() : 'Buat shift baru'}
      keterangan="Shift dipakai absensi untuk menentukan jam masuk, jam pulang, dan istirahat."
      onSimpan={handleSubmit} menyimpan={saving} galat={error} labelSimpan={initial ? 'Simpan perubahan' : 'Buat shift'}>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Isian label="Kode shift" wajib htmlFor="shift-code">
          <Input id="shift-code" value={form.shift_code} onChange={e => setForm(p => ({ ...p, shift_code: e.target.value.toUpperCase() }))}
            placeholder="PAGI" />
        </Isian>
        <Isian label="Nama shift" wajib htmlFor="shift-name">
          <Input id="shift-name" value={form.shift_name} onChange={e => setForm(p => ({ ...p, shift_name: e.target.value }))}
            placeholder="Shift pagi" />
        </Isian>
        <Isian label="Jam mulai" wajib htmlFor="shift-start">
          <Input id="shift-start" type="time" value={form.start_time} onChange={e => setForm(p => ({ ...p, start_time: e.target.value }))} />
        </Isian>
        <Isian label="Jam selesai" wajib htmlFor="shift-end">
          <Input id="shift-end" type="time" value={form.end_time} onChange={e => setForm(p => ({ ...p, end_time: e.target.value }))} />
        </Isian>
        <Isian label="Istirahat (menit)" htmlFor="shift-break">
          <Input id="shift-break" type="number" min={0} value={form.break_duration_minutes}
            onChange={e => setForm(p => ({ ...p, break_duration_minutes: e.target.value }))} />
        </Isian>
        <Isian label="Warna penanda" htmlFor="shift-color" petunjuk="Titik warna di daftar dan jadwal shift.">
          <div className="flex items-center gap-2">
            <input id="shift-color" type="color" value={form.color} onChange={e => setForm(p => ({ ...p, color: e.target.value }))}
              className="h-9 w-12 shrink-0 cursor-pointer rounded-md border border-[var(--glass-border)] bg-transparent" aria-label="Pilih warna" />
            <Input value={form.color} onChange={e => setForm(p => ({ ...p, color: e.target.value }))} aria-label="Kode warna" />
          </div>
        </Isian>
      </div>

      <Isian label="Hari aktif">
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Hari aktif">
          {ALL_DAYS.map(d => {
            const on = form.days_active.includes(d);
            return (
              <Button key={d} type="button" size="sm" variant={on ? 'default' : 'outline'} aria-pressed={on}
                onClick={() => toggleDay(d)} className="w-12">{DAYS_ID[d]}</Button>
            );
          })}
        </div>
      </Isian>

      <label className="flex cursor-pointer items-center gap-2 text-sm text-foreground">
        <Checkbox checked={form.is_overnight} onCheckedChange={v => setForm(p => ({ ...p, is_overnight: !!v }))} />
        Shift melewati tengah malam
      </label>

      <p className="text-sm text-muted-foreground">
        Jam kerja efektif: <span className="font-semibold text-foreground">{calcHours()} jam</span>
      </p>

      <Isian label="Keterangan" htmlFor="shift-desc">
        <Textarea id="shift-desc" value={form.description} onChange={e => setForm(p => ({ ...p, description: e.target.value }))}
          rows={2} placeholder="Keterangan shift" />
      </Isian>
    </FormPopup>
  );
}

// Tahap 5 (2026-11-07): karyawan DIPILIH dari master (dulu kotak "ID Karyawan" diketik bebas, mis. "emp-001",
// tanpa pemeriksaan — penugasan bisa menunjuk karyawan yang tidak ada). Departemen mengikuti data karyawan.
function AssignmentForm({ open, shifts, employees = [], onSave, onClose }) {
  const kosong = () => ({ employee_id: '', shift_id: '', effective_from: todayWIB(), effective_until: '', department: '', notes: '' });
  const [form, setForm] = useState(kosong);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { if (open) { setForm(kosong()); setError(''); } }, [open]);
  const pickEmployee = (id) => {
    const emp = employees.find(e => e.id === id);
    setForm(p => ({ ...p, employee_id: id, department: emp?.department || '' }));
  };

  const handleSubmit = async () => {
    if (!form.employee_id || !form.shift_id || !form.effective_from) {
      setError('Karyawan, shift, dan tanggal mulai wajib diisi.'); return;
    }
    if (form.effective_until && form.effective_until < form.effective_from) {
      setError('Tanggal berakhir tidak boleh sebelum tanggal mulai.'); return;
    }
    setSaving(true); setError('');
    try {
      await onSave({ ...form, effective_until: form.effective_until || null });
    } catch (e) {
      setError(e.response?.data?.detail || 'Gagal menugaskan shift');
    } finally { setSaving(false); }
  };

  return (
    <FormPopup open={open} onClose={onClose} ukuran="pendek" testId="shift-assign-form"
      judul="Tugaskan shift ke karyawan" keterangan="Penugasan menggantikan shift utama karyawan selama masa berlakunya."
      onSimpan={handleSubmit} menyimpan={saving} galat={error} labelSimpan="Tugaskan">
      <Isian label="Karyawan" wajib>
        <EmployeeSelect employees={employees} value={form.employee_id} onChange={pickEmployee} testId="assign-employee" className="w-full" />
      </Isian>
      <Isian label="Shift" wajib>
        <SmartNativeSelect value={form.shift_id} onChange={e => setForm(p => ({ ...p, shift_id: e.target.value }))} data-testid="assign-shift" className="w-full">
          <option value="">— Pilih shift —</option>
          {shifts.filter(s => !s.is_default).map(s => (
            <option key={s.id} value={s.id}>{`${s.shift_code} — ${s.shift_name} (${s.start_time}–${s.end_time})`}</option>
          ))}
        </SmartNativeSelect>
      </Isian>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Isian label="Berlaku mulai" wajib>
          <DatePicker value={form.effective_from} onChange={v => setForm(p => ({ ...p, effective_from: v }))} bolehKosong={false} testId="assign-from" />
        </Isian>
        <Isian label="Berlaku hingga" petunjuk="Kosong = sampai dicabut.">
          <DatePicker value={form.effective_until} min={form.effective_from || undefined} placeholder="Sampai dicabut"
            onChange={v => setForm(p => ({ ...p, effective_until: v }))} testId="assign-until" />
        </Isian>
      </div>
      <Isian label="Departemen" petunjuk="Mengikuti data karyawan.">
        <div className="flex h-9 items-center text-sm text-muted-foreground" data-testid="assign-department">{form.department || '—'}</div>
      </Isian>
      <Isian label="Catatan" htmlFor="assign-notes">
        <Input id="assign-notes" value={form.notes} onChange={e => setForm(p => ({ ...p, notes: e.target.value }))} />
      </Isian>
    </FormPopup>
  );
}

/**
 * @param bagian  'shifts' | 'assignments' — dipakai hub Shift (satu tab hub per bagian).
 *                Tanpa nilai (menu lama "hr-shift-management") → kedua bagian dengan pil penyaring.
 */
export default function HRShiftManagementModule({ user, bagian }) {
  const [shifts, setShifts] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tabSendiri, setTabSendiri] = useState('shifts');
  const tab = bagian || tabSendiri;
  const [shiftForm, setShiftForm] = useState(null);   // null | {} (baru) | shift (ubah)
  const [assignOpen, setAssignOpen] = useState(false);
  const [assignCounts, setAssignCounts] = useState({});
  const token = localStorage.getItem('erp_token');
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);
  const isAdmin = ['superadmin', 'admin', 'owner', 'hr'].includes((user?.role || '').toLowerCase());
  const { employees } = useActiveEmployees(token);
  const empById = useMemo(() => Object.fromEntries(employees.map(e => [e.id, e])), [employees]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [shiftRes, assignRes, sumRes] = await Promise.all([
        axios.get(`${API}/api/hr/shifts`, { headers }),
        axios.get(`${API}/api/hr/shifts/assignments?limit=500`, { headers }),
        axios.get(`${API}/api/hr/shifts/summary`, { headers }),
      ]);
      setShifts(shiftRes.data?.data || []);
      setAssignments(assignRes.data?.data || []);
      setSummary(sumRes.data?.data || null);
      // Build assign count map
      const counts = {};
      for (const a of assignRes.data?.data || []) {
        counts[a.shift_id] = (counts[a.shift_id] || 0) + 1;
      }
      setAssignCounts(counts);
    } catch (e) { toast.error('Gagal memuat data shift'); }
    finally { setLoading(false); }
  }, [headers]);

  useEffect(() => { load(); }, [load]);

  const handleCreateShift = async (data) => {
    await axios.post(`${API}/api/hr/shifts`, data, { headers });
    toast.success('Shift dibuat');
    setShiftForm(null);
    load();
  };

  const handleUpdateShift = async (data) => {
    await axios.put(`${API}/api/hr/shifts/${shiftForm.id}`, data, { headers });
    toast.success('Shift disimpan');
    setShiftForm(null);
    load();
  };

  const handleDeleteShift = async (s) => {
    if (!(await confirmDialog({
      title: `Nonaktifkan shift ${s.shift_code}?`, body: 'Shift tidak bisa dipilih lagi untuk penugasan baru.',
      confirmLabel: 'Nonaktifkan', danger: true,
    }))) return;
    try {
      await axios.delete(`${API}/api/hr/shifts/${s.id}`, { headers });
      toast.success('Shift dinonaktifkan');
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Gagal menonaktifkan shift'); }
  };

  const handleAssign = async (data) => {
    await axios.post(`${API}/api/hr/shifts/assignments`, data, { headers });
    toast.success('Shift ditugaskan');
    setAssignOpen(false);
    load();
  };

  const handleSeedDefaults = async () => {
    try {
      await axios.post(`${API}/api/hr/shifts/seed-defaults`, {}, { headers });
      toast.success('Shift bawaan diisi');
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Gagal mengisi shift bawaan'); }
  };

  const nonDefaultShifts = shifts.filter(s => !s.is_default);
  const { page, setPage, totalPages, total, paged } = useClientPagination(assignments, 10);
  const namaKaryawan = (a) => (a.employee_name ? `${a.employee_code || ''} · ${a.employee_name}`.replace(/^ · /, '')
    : (empById[a.employee_id] ? employeeLabel(empById[a.employee_id]) : 'Karyawan tidak ditemukan'));

  // ─── Tabel shift ─────────────────────────────────────────────────────────────
  const kolomShift = [
    { kunci: 'kode', label: 'Kode', isi: (s) => <ShiftKode code={s.shift_code} color={s.color} /> },
    { kunci: 'nama', label: 'Nama shift', hp: 'judul', isi: (s) => (
      <div className="min-w-0">
        <p className="font-medium text-foreground">{s.shift_name}</p>
        {s.description && <p className="hidden truncate text-xs text-muted-foreground md:block md:max-w-[18rem]">{s.description}</p>}
      </div>) },
    { kunci: 'jam', label: 'Jam', hp: 'keterangan', isi: (s) => (
      <span className="tabular-nums md:whitespace-nowrap">{s.start_time}–{s.end_time}{s.is_overnight ? ' (lewat tengah malam)' : ''}</span>) },
    { kunci: 'efektif', label: 'Jam efektif', rata: 'kanan', isi: (s) => <span className="tabular-nums">{s.effective_hours ?? '—'} jam</span> },
    { kunci: 'hari', label: 'Hari aktif', isi: (s) => labelHari(s.days_active) },
    { kunci: 'tugas', label: 'Penugasan aktif', rata: 'kanan', isi: (s) => <span className="tabular-nums">{assignCounts[s.id] || 0}</span> },
    { kunci: 'jenis', label: 'Jenis', isi: (s) => (s.is_default
      ? <StatusBadge status="bawaan" label="Bawaan" tone="muted" />
      : <StatusBadge status="active" label="Aktif" tone="success" />) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (s) => (s.is_default ? null : (
      <div className="flex items-center justify-end gap-1">
        <Button size="sm" variant="outline" onClick={() => setShiftForm(s)} data-testid={`shift-edit-${s.id}`}><Pencil />Ubah</Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="icon-sm" variant="ghost" aria-label="Lainnya" title="Lainnya"><MoreHorizontal /></Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => handleDeleteShift(s)} className="text-[hsl(var(--danger-text))]">
              <Power className="mr-2 h-4 w-4" />Nonaktifkan
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>)) },
  ];
  const unduhShift = [
    { label: 'Kode', nilai: (s) => s.shift_code },
    { label: 'Nama shift', nilai: (s) => s.shift_name },
    { label: 'Jam mulai', nilai: (s) => s.start_time },
    { label: 'Jam selesai', nilai: (s) => s.end_time },
    { label: 'Istirahat (menit)', nilai: (s) => Number(s.break_duration_minutes ?? 0) },
    { label: 'Jam efektif', nilai: (s) => Number(s.effective_hours ?? 0) },
    { label: 'Hari aktif', nilai: (s) => (s.days_active || []).map(d => DAYS_ID[d]).join(', ') },
    { label: 'Lewat tengah malam', nilai: (s) => (s.is_overnight ? 'Ya' : 'Tidak') },
    { label: 'Penugasan aktif', nilai: (s) => assignCounts[s.id] || 0 },
    { label: 'Jenis', nilai: (s) => (s.is_default ? 'Bawaan' : 'Aktif') },
  ];

  // ─── Tabel penugasan ─────────────────────────────────────────────────────────
  const statusPenugasan = (a) => STATUS_PENUGASAN[a.status] || { label: 'Lainnya', tone: 'default' };
  const kolomTugas = [
    { kunci: 'karyawan', label: 'Karyawan', hp: 'judul', isi: (a) => <span className="font-medium text-foreground">{namaKaryawan(a)}</span> },
    { kunci: 'shift', label: 'Shift', isi: (a) => <ShiftKode code={a.shift_code} color={a.shift_color} /> },
    { kunci: 'dept', label: 'Departemen', hp: 'keterangan', isi: (a) => a.department || '—' },
    { kunci: 'mulai', label: 'Berlaku mulai', isi: (a) => formatTanggalID(a.effective_from) || '—' },
    { kunci: 'hingga', label: 'Berlaku hingga', isi: (a) => (a.effective_until ? formatTanggalID(a.effective_until) : 'Sampai dicabut') },
    { kunci: 'status', label: 'Status', isi: (a) => { const s = statusPenugasan(a); return <StatusBadge status={a.status} label={s.label} tone={s.tone} />; } },
  ];
  const unduhTugas = [
    { label: 'Karyawan', nilai: namaKaryawan },
    { label: 'Shift', nilai: (a) => a.shift_code || '' },
    { label: 'Nama shift', nilai: (a) => a.shift_name || '' },
    { label: 'Departemen', nilai: (a) => a.department || '' },
    { label: 'Berlaku mulai', nilai: (a) => formatTanggalID(a.effective_from) },
    { label: 'Berlaku hingga', nilai: (a) => (a.effective_until ? formatTanggalID(a.effective_until) : 'Sampai dicabut') },
    { label: 'Status', nilai: (a) => statusPenugasan(a).label },
    { label: 'Catatan', nilai: (a) => a.notes || '' },
  ];

  const ringkasan = summary && (
    <p className="text-sm text-muted-foreground" data-testid="shift-summary">
      <span className="font-medium text-foreground">{summary.total_shifts}</span> shift aktif tersimpan
      {shifts.some(s => s.id === 'default') ? ' (ditambah 1 shift cadangan sistem 08:00–17:00)' : ''}
      {' · '}<span className="font-medium text-foreground">{summary.total_assigned_employees}</span> penugasan aktif
      {summary.by_shift?.[0] ? <> · paling banyak dipakai: <span className="font-medium text-foreground">{summary.by_shift[0].shift_name}</span> ({summary.by_shift[0].count})</> : null}
      . Karyawan tanpa penugasan memakai shift utamanya di Data Karyawan atau shift cadangan.
    </p>
  );

  const pil = !bagian && (
    <FilterChips value={tabSendiri} onChange={setTabSendiri} hideWhenEmpty={false} testId="shift-bagian"
      options={[{ key: 'shifts', label: 'Daftar shift', count: shifts.length }, { key: 'assignments', label: 'Penugasan', count: assignments.length }]} />
  );

  const muatUlang = (
    <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
      <RefreshCw className={loading ? 'animate-spin' : ''} />
    </Button>
  );

  return (
    <PageLayout testId="hr-shift-management" title="Shift"
      subtitle="Daftar shift kerja dan penugasannya ke karyawan."
      actions={isAdmin && (tab === 'shifts' ? (<>
        {nonDefaultShifts.length === 0 && !loading && (
          <Button variant="outline" onClick={handleSeedDefaults} data-testid="shift-seed">Isi shift bawaan</Button>
        )}
        <Button onClick={() => setShiftForm({})} data-testid="shift-add"><Plus />Shift baru</Button>
      </>) : (
        <Button onClick={() => setAssignOpen(true)} data-testid="shift-assign-add"><Plus />Tugaskan shift</Button>
      ))}
      filters={pil}
      tools={<>
        {tab === 'shifts'
          ? <TombolUnduh namaBerkas="daftar-shift" namaLembar="Shift" baris={shifts} kolom={unduhShift} testId="shift-unduh" />
          : <TombolUnduh namaBerkas="penugasan-shift" namaLembar="Penugasan shift" baris={assignments} kolom={unduhTugas} testId="shift-assign-unduh" />}
        {muatUlang}
      </>}
      summary={tab === 'shifts' ? ringkasan : null}
      footer={tab === 'assignments' && assignments.length > 0
        ? <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} /> : null}>

      {loading && shifts.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat data shift…</p>
      ) : tab === 'shifts' ? (
        <TabelData kolom={kolomShift} baris={shifts} testId="shift-table"
          onKlikBaris={(s) => { if (!s.is_default) setShiftForm(s); }}
          kosong={<EmptyState title="Belum ada shift"
            description="Isi 5 shift bawaan (pagi, siang, malam, normal, fleksibel), lalu ubah sesuai kebutuhan."
            action={isAdmin && <Button variant="outline" onClick={handleSeedDefaults}>Isi shift bawaan</Button>} />} />
      ) : (
        <TabelData kolom={kolomTugas} baris={paged} testId="shift-assign-table"
          kosong={<EmptyState title="Belum ada penugasan shift"
            description="Karyawan tanpa penugasan memakai shift utamanya di Data Karyawan atau shift bawaan 08:00–17:00." />} />
      )}

      <ShiftForm open={shiftForm !== null} initial={shiftForm?.id ? shiftForm : null}
        onSave={shiftForm?.id ? handleUpdateShift : handleCreateShift} onClose={() => setShiftForm(null)} />
      <AssignmentForm open={assignOpen} shifts={shifts} employees={employees} onSave={handleAssign} onClose={() => setAssignOpen(false)} />
    </PageLayout>
  );
}

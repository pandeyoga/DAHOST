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
 * Tahap C audit HR (9 Nov 2026): toleransi terlambat & jam mulai istirahat per shift; "Hari aktif" → "Hari kerja"
 * (dipakai roster); Penugasan = daftar SEMUA karyawan aktif + shift hari ini + asalnya, pilih baris → penugasan massal.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import axios from 'axios';
import { Plus, RefreshCw, Pencil, Power, MoreHorizontal, Trash2 } from 'lucide-react';
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
import { EmployeeSelect, useActiveEmployees, useDepartmentFilterOptions, useHrMasters } from './hr/hrPickers';
import { checkPerm } from '@/lib/rbac';
import { hapusMaster } from '@/lib/hapusMaster';

const API = process.env.REACT_APP_BACKEND_URL;
const DAYS_ID = { Mon: 'Sen', Tue: 'Sel', Wed: 'Rab', Thu: 'Kam', Fri: 'Jum', Sat: 'Sab', Sun: 'Min' };
const ALL_DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
// Baris shift cadangan dibuat server (id "default", tidak tersimpan di master) — namanya diterjemahkan di layar.
const CADANGAN = 'default';
const namaShift = (s) => (s.id === CADANGAN ? `Shift cadangan sistem (${s.start_time}–${s.end_time})` : s.shift_name);
const kodeShift = (s) => (s.id === CADANGAN ? 'Cadangan' : s.shift_code);

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
    is_overnight: false, color: '#3b82f6', description: '', toleransi_menit: '', istirahat_mulai: '',
  };
  const dariAwal = (i) => (i ? { ...i, toleransi_menit: i.toleransi_menit ?? '', istirahat_mulai: i.istirahat_mulai || '' } : kosong);
  const [form, setForm] = useState(() => dariAwal(initial));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { if (open) { setForm(dariAwal(initial)); setError(''); } }, [open, initial]); // eslint-disable-line react-hooks/exhaustive-deps

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
    const tol = String(form.toleransi_menit ?? '').trim();
    if (tol !== '' && !(Number(tol) >= 0 && Number(tol) <= 240)) { setError('Toleransi terlambat 0–240 menit, atau kosongkan.'); return; }
    setSaving(true); setError('');
    try {
      // Tahap C audit HR: toleransi kosong = ikut setelan umum (dikirim null); jam istirahat kosong = dihapus.
      await onSave({ ...form, break_duration_minutes: parseInt(form.break_duration_minutes, 10) || 0,
        toleransi_menit: tol === '' ? null : parseInt(tol, 10), istirahat_mulai: form.istirahat_mulai || null });
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
        <Isian label="Jam mulai istirahat" htmlFor="shift-break-start" petunjuk="Acuan jam masuk cuti setengah hari pagi.">
          <Input id="shift-break-start" type="time" value={form.istirahat_mulai || ''}
            onChange={e => setForm(p => ({ ...p, istirahat_mulai: e.target.value }))} data-testid="shift-istirahat-mulai" />
        </Isian>
        <Isian label="Toleransi terlambat (menit)" htmlFor="shift-grace" petunjuk="Kosong = ikut setelan umum absensi.">
          <Input id="shift-grace" type="number" min={0} max={240} value={form.toleransi_menit ?? ''} placeholder="Setelan umum"
            onChange={e => setForm(p => ({ ...p, toleransi_menit: e.target.value }))} data-testid="shift-toleransi" />
        </Isian>
        <Isian label="Warna penanda" htmlFor="shift-color" petunjuk="Titik warna di daftar dan jadwal shift.">
          <div className="flex items-center gap-2">
            <input id="shift-color" type="color" value={form.color} onChange={e => setForm(p => ({ ...p, color: e.target.value }))}
              className="h-9 w-12 shrink-0 cursor-pointer rounded-md border border-[var(--glass-border)] bg-transparent" aria-label="Pilih warna" />
            <Input value={form.color} onChange={e => setForm(p => ({ ...p, color: e.target.value }))} aria-label="Kode warna" />
          </div>
        </Isian>
      </div>

      <Isian label="Hari kerja" petunjuk="Hari di luar hari kerja menjadi libur saat roster disusun dari shift ini.">
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Hari kerja">
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


// Tahap C audit HR (9 Nov 2026): PENUGASAN MASSAL. Dulu satu karyawan per formulir (25 karyawan = 25 kali buka
// formulir). Sekarang: baris karyawan terpilih ATAU semua karyawan aktif satu departemen/lokasi ATAU satu karyawan.
// Server: POST /api/hr/shifts/assignments/massal (aturan penugasan tunggal: hanya bagian penugasan lama yang
// beririsan yang ditutup — penugasan sementara tidak menghapus penugasan tetap).
function PenugasanForm({ open, shifts, employees = [], terpilih = [], deptOpsi = [], lokasi = [], onSave, onClose }) {
  const kosong = () => ({ lingkup: terpilih.length ? 'pilihan' : 'satu', employee_id: '', department: '', location_id: '',
    shift_id: '', effective_from: todayWIB(), effective_until: '', notes: '' });
  const [form, setForm] = useState(kosong);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { if (open) { setForm(kosong()); setError(''); } }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  const ubah = (k, v) => setForm((p) => ({ ...p, [k]: v }));

  const handleSubmit = async () => {
    if (!form.shift_id || !form.effective_from) { setError('Shift dan tanggal mulai wajib diisi.'); return; }
    if (form.effective_until && form.effective_until < form.effective_from) { setError('Tanggal berakhir tidak boleh sebelum tanggal mulai.'); return; }
    const body = { shift_id: form.shift_id, effective_from: form.effective_from, effective_until: form.effective_until || null, notes: form.notes };
    if (form.lingkup === 'pilihan') body.employee_ids = terpilih;
    else if (form.lingkup === 'satu') {
      if (!form.employee_id) { setError('Pilih karyawan.'); return; }
      body.employee_ids = [form.employee_id];
    } else if (form.lingkup === 'departemen') {
      if (!form.department) { setError('Pilih departemen.'); return; }
      body.department = form.department;
    } else {
      if (!form.location_id) { setError('Pilih lokasi.'); return; }
      body.location_id = form.location_id;
    }
    setSaving(true); setError('');
    try { await onSave(body); } catch (e) { setError(e.response?.data?.detail || 'Gagal menugaskan shift'); } finally { setSaving(false); }
  };

  return (
    <FormPopup open={open} onClose={onClose} ukuran="pendek" testId="shift-assign-form"
      judul="Tugaskan shift" keterangan="Penugasan menggantikan shift utama karyawan selama masa berlakunya; penugasan dengan tanggal akhir tidak menghapus penugasan tetap."
      onSimpan={handleSubmit} menyimpan={saving} galat={error} labelSimpan="Tugaskan">
      <Isian label="Untuk" wajib>
        <SmartNativeSelect value={form.lingkup} onChange={(e) => ubah('lingkup', e.target.value)} searchable={false} className="w-full" data-testid="assign-lingkup">
          {terpilih.length > 0 && <option value="pilihan">{`Baris terpilih (${terpilih.length} karyawan)`}</option>}
          <option value="satu">Satu karyawan</option>
          <option value="departemen">Semua karyawan satu departemen</option>
          {lokasi.length > 0 && <option value="lokasi">Semua karyawan satu lokasi</option>}
        </SmartNativeSelect>
      </Isian>
      {form.lingkup === 'satu' && (
        <Isian label="Karyawan" wajib>
          <EmployeeSelect employees={employees} value={form.employee_id} onChange={(v) => ubah('employee_id', v)} testId="assign-employee" className="w-full" />
        </Isian>
      )}
      {form.lingkup === 'departemen' && (
        <Isian label="Departemen" wajib>
          <SmartNativeSelect value={form.department} onChange={(e) => ubah('department', e.target.value)} className="w-full" data-testid="assign-department">
            <option value="">— Pilih departemen —</option>
            {deptOpsi.map((d) => <option key={d.value} value={d.value}>{d.legacy ? d.value : d.label}</option>)}
          </SmartNativeSelect>
        </Isian>
      )}
      {form.lingkup === 'lokasi' && (
        <Isian label="Lokasi" wajib>
          <SmartNativeSelect value={form.location_id} onChange={(e) => ubah('location_id', e.target.value)} className="w-full">
            <option value="">— Pilih lokasi —</option>
            {lokasi.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </SmartNativeSelect>
        </Isian>
      )}
      <Isian label="Shift" wajib>
        <SmartNativeSelect value={form.shift_id} onChange={(e) => ubah('shift_id', e.target.value)} data-testid="assign-shift" className="w-full">
          <option value="">— Pilih shift —</option>
          {shifts.filter((s) => !s.is_default).map((s) => (
            <option key={s.id} value={s.id}>{`${s.shift_code} — ${s.shift_name} (${s.start_time}–${s.end_time})`}</option>
          ))}
        </SmartNativeSelect>
      </Isian>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Isian label="Berlaku mulai" wajib>
          <DatePicker value={form.effective_from} onChange={(v) => ubah('effective_from', v)} bolehKosong={false} testId="assign-from" />
        </Isian>
        <Isian label="Berlaku hingga" petunjuk="Kosong = sampai dicabut.">
          <DatePicker value={form.effective_until} min={form.effective_from || undefined} placeholder="Sampai dicabut"
            onChange={(v) => ubah('effective_until', v)} testId="assign-until" />
        </Isian>
      </div>
      <Isian label="Catatan" htmlFor="assign-notes">
        <Input id="assign-notes" value={form.notes} onChange={(e) => ubah('notes', e.target.value)} />
      </Isian>
    </FormPopup>
  );
}

const SUMBER = { jadwal: 'Jadwal terbit', penugasan: 'Penugasan', karyawan: 'Shift utama' };

/**
 * @param bagian  'shifts' | 'assignments' — dipakai hub Shift (satu tab hub per bagian).
 *                Tanpa nilai (menu lama "hr-shift-management") → kedua bagian dengan pil penyaring.
 */
export default function HRShiftManagementModule({ user, bagian }) {
  const [shifts, setShifts] = useState([]);
  const [rows, setRows] = useState([]);              // penugasan per karyawan (Tahap C)
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tabSendiri, setTabSendiri] = useState('shifts');
  const tab = bagian || tabSendiri;
  const [shiftForm, setShiftForm] = useState(null);   // null | {} (baru) | shift (ubah)
  const [assignOpen, setAssignOpen] = useState(false);
  const [assignCounts, setAssignCounts] = useState({});
  const [cari, setCari] = useState('');
  const [dept, setDept] = useState('');
  const [lok, setLok] = useState('');
  const [terpilih, setTerpilih] = useState(() => new Set());
  const [lokasi, setLokasi] = useState([]);
  const token = localStorage.getItem('erp_token');
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);
  // 2026-11-08: kode peran lama ATAU izin Shift & Penjadwalan (hr.attendance.manage / hr.manage) — izin yang sama
  // dengan server `_require_shift_writer` (routes/hr_shifts.py), supaya peran buatan owner melihat tombolnya.
  const isAdmin = checkPerm({ user, roles: ['superadmin', 'admin', 'owner', 'hr'], keys: ['hr.attendance.manage', 'hr.manage'] });
  const { employees } = useActiveEmployees(token);
  const { units } = useHrMasters(token, { positions: false, shifts: false });
  const deptOpsi = useDepartmentFilterOptions(units, employees);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [shiftRes, sumRes, assignRes] = await Promise.all([
        axios.get(`${API}/api/hr/shifts`, { headers }),
        axios.get(`${API}/api/hr/shifts/summary`, { headers }),
        axios.get(`${API}/api/hr/shifts/assignments?limit=500`, { headers }).catch(() => ({ data: { data: [] } })),
      ]);
      setShifts(shiftRes.data?.data || []);
      setSummary(sumRes.data?.data || null);
      const counts = {};
      for (const a of assignRes.data?.data || []) counts[a.shift_id] = (counts[a.shift_id] || 0) + 1;
      setAssignCounts(counts);
    } catch (e) { toast.error('Gagal memuat data shift'); }
    finally { setLoading(false); }
  }, [headers]);

  const loadRows = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/api/hr/shifts/penugasan-karyawan`, {
        headers, params: { department: dept || undefined, location_id: lok || undefined, q: cari || undefined } });
      setRows(r.data?.data || []);
    } catch (e) { toast.error(e.response?.data?.detail || 'Gagal memuat penugasan karyawan'); }
  }, [headers, dept, lok, cari]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (tab === 'assignments') loadRows(); }, [tab, loadRows]);
  useEffect(() => {
    if (tab !== 'assignments') return;
    axios.get(`${API}/api/rahaza/locations`, { headers }).then((r) => setLokasi(Array.isArray(r.data) ? r.data : (r.data?.items || []))).catch(() => setLokasi([]));
  }, [tab, headers]);

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

  // 10 Nov 2026 (owner: "master data bisa dihapus"): hapus permanen bila shift belum dipakai karyawan, penugasan,
  // jadwal, pola, atau absensi; bila sudah dipakai server menjawab 409 dan dialog kedua menawarkan Nonaktifkan.
  const hapusShift = async (s) => {
    const hasil = await hapusMaster({
      jenis: 'shift', nama: namaShift(s),
      hapus: () => axios.delete(`${API}/api/hr/shifts/${s.id}?hard=true`, { headers }),
      nonaktifkan: s.status === 'inactive' || s.active === false ? null : () => axios.delete(`${API}/api/hr/shifts/${s.id}`, { headers }),
    });
    if (hasil) load();
  };

  const handleAssign = async (body) => {
    const r = await axios.post(`${API}/api/hr/shifts/assignments/massal`, body, { headers });
    const gagal = r.data?.data?.gagal || [];
    if (gagal.length) toast.warning(`${r.data?.message} ${gagal.slice(0, 3).map((g) => `${g.karyawan}: ${g.pesan}`).join('; ')}`);
    else toast.success(r.data?.message || 'Shift ditugaskan');
    setAssignOpen(false);
    setTerpilih(new Set());
    load(); loadRows();
  };

  const cabut = async (row) => {
    if (!row.penugasan?.id) return;
    if (!(await confirmDialog({ title: `Cabut penugasan ${row.name}?`, body: 'Karyawan kembali memakai shift utamanya di Data Karyawan.', confirmLabel: 'Cabut', danger: true }))) return;
    try {
      await axios.delete(`${API}/api/hr/shifts/assignments/${row.penugasan.id}`, { headers });
      toast.success('Penugasan dicabut');
      loadRows(); load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Gagal mencabut penugasan'); }
  };

  const handleSeedDefaults = async () => {
    try {
      await axios.post(`${API}/api/hr/shifts/seed-defaults`, {}, { headers });
      toast.success('Shift bawaan diisi');
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Gagal mengisi shift bawaan'); }
  };

  const nonDefaultShifts = shifts.filter(s => !s.is_default);
  const { page, setPage, totalPages, total, paged } = useClientPagination(rows, 25);
  const toggle = (id) => setTerpilih((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const semua = rows.length > 0 && rows.every((r) => terpilih.has(r.employee_id));

  // ─── Tabel shift ─────────────────────────────────────────────────────────────
  const kolomShift = [
    { kunci: 'kode', label: 'Kode', isi: (s) => <ShiftKode code={kodeShift(s)} color={s.color} /> },
    { kunci: 'nama', label: 'Nama shift', hp: 'judul', isi: (s) => (
      <div className="min-w-0">
        <p className="font-medium text-foreground">{namaShift(s)}</p>
        {s.description && <p className="hidden truncate text-xs text-muted-foreground md:block md:max-w-[18rem]">{s.description}</p>}
      </div>) },
    { kunci: 'jam', label: 'Jam', hp: 'keterangan', isi: (s) => (
      <span className="tabular-nums md:whitespace-nowrap">{s.start_time}–{s.end_time}{s.is_overnight ? ' (lewat tengah malam)' : ''}</span>) },
    { kunci: 'efektif', label: 'Jam efektif', rata: 'kanan', isi: (s) => <span className="tabular-nums">{s.effective_hours ?? '—'} jam</span> },
    { kunci: 'hari', label: 'Hari kerja', isi: (s) => labelHari(s.days_active) },
    { kunci: 'tol', label: 'Toleransi', isi: (s) => (s.toleransi_menit != null && s.toleransi_menit !== '' ? `${s.toleransi_menit} menit` : 'Setelan umum') },
    { kunci: 'tugas', label: 'Penugasan aktif', rata: 'kanan', isi: (s) => <span className="tabular-nums">{assignCounts[s.id] || 0}</span> },
    { kunci: 'jenis', label: 'Jenis', isi: (s) => (s.is_default
      ? <StatusBadge status="bawaan" label="Bawaan" tone="muted" />
      : <StatusBadge status="active" label="Aktif" tone="success" />) },
    { kunci: 'aksi', label: 'Aksi', rata: 'kanan', hp: 'aksi', isi: (s) => (s.is_default ? null : (
      <div className="flex items-center justify-end gap-1">
        <Button size="sm" variant="outline" onClick={() => setShiftForm(s)} data-testid={`shift-edit-${s.id}`}><Pencil />Ubah</Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="icon-sm" variant="ghost" aria-label="Lainnya" title="Lainnya"><MoreHorizontal /></Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => handleDeleteShift(s)} className="text-[hsl(var(--danger-text))]"
              data-testid={`shift-deactivate-${s.id}`}>
              <Power className="mr-2 h-4 w-4" />Nonaktifkan
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => hapusShift(s)} className="text-[hsl(var(--danger-text))]"
              data-testid={`shift-delete-${s.id}`}>
              <Trash2 className="mr-2 h-4 w-4" />Hapus
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>)) },
  ];
  const unduhShift = [
    { label: 'Kode', nilai: kodeShift },
    { label: 'Nama shift', nilai: namaShift },
    { label: 'Jam mulai', nilai: (s) => s.start_time },
    { label: 'Jam selesai', nilai: (s) => s.end_time },
    { label: 'Istirahat (menit)', nilai: (s) => Number(s.break_duration_minutes ?? 0) },
    { label: 'Mulai istirahat', nilai: (s) => s.istirahat_mulai || '' },
    { label: 'Jam efektif', nilai: (s) => Number(s.effective_hours ?? 0) },
    { label: 'Hari kerja', nilai: (s) => (s.days_active || []).map(d => DAYS_ID[d]).join(', ') },
    { label: 'Toleransi terlambat (menit)', nilai: (s) => (s.toleransi_menit != null && s.toleransi_menit !== '' ? Number(s.toleransi_menit) : 'Setelan umum') },
    { label: 'Lewat tengah malam', nilai: (s) => (s.is_overnight ? 'Ya' : 'Tidak') },
    { label: 'Penugasan aktif', nilai: (s) => assignCounts[s.id] || 0 },
    { label: 'Jenis', nilai: (s) => (s.is_default ? 'Bawaan' : 'Aktif') },
  ];

  // ─── Tabel penugasan per karyawan (pilih baris → penugasan massal) ─────────────
  const berlakuHingga = (r) => (r.penugasan ? (r.penugasan.effective_until ? formatTanggalID(r.penugasan.effective_until) : 'Sampai dicabut') : '—');
  const kolomTugas = [
    { kunci: 'pilih', label: (
      <Checkbox checked={semua} aria-label="Pilih semua karyawan" data-testid="assign-pilih-semua"
        onCheckedChange={(v) => setTerpilih(v ? new Set(rows.map((r) => r.employee_id)) : new Set())} />), hp: 'aksi', lebar: 'w-10',
      isi: (r) => <Checkbox checked={terpilih.has(r.employee_id)} onCheckedChange={() => toggle(r.employee_id)} aria-label={`Pilih ${r.name}`} data-testid="assign-pilih" /> },
    { kunci: 'karyawan', label: 'Karyawan', hp: 'judul', isi: (r) => (
      <span className="font-medium text-foreground">{[r.employee_code, r.name].filter(Boolean).join(' · ')}</span>) },
    { kunci: 'dept', label: 'Departemen', hp: 'keterangan', isi: (r) => r.department || '—' },
    { kunci: 'lokasi', label: 'Lokasi', isi: (r) => r.location_name || '—' },
    { kunci: 'shift', label: 'Shift hari ini', isi: (r) => (r.shift ? <ShiftKode code={`${r.shift.kode} ${r.shift.mulai}–${r.shift.selesai}`} color={r.shift.warna} /> : 'Belum ada shift') },
    { kunci: 'asal', label: 'Asal', isi: (r) => SUMBER[r.sumber] || '—' },
    { kunci: 'hingga', label: 'Penugasan berlaku hingga', isi: berlakuHingga },
    { kunci: 'nanti', label: 'Berikutnya', isi: (r) => (r.berikutnya?.length
      ? r.berikutnya.map((b) => `${b.shift_code} mulai ${formatTanggalID(b.effective_from)}`).join('; ') : '—') },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (isAdmin && r.penugasan?.id ? (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="icon-sm" variant="ghost" aria-label="Lainnya" title="Lainnya"><MoreHorizontal /></Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={() => cabut(r)} className="text-[hsl(var(--danger-text))]">
            <Power className="mr-2 h-4 w-4" />Cabut penugasan
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>) : null) },
  ];
  const unduhTugas = [
    { label: 'Kode', nilai: (r) => r.employee_code },
    { label: 'Karyawan', nilai: (r) => r.name },
    { label: 'Departemen', nilai: (r) => r.department || '' },
    { label: 'Lokasi', nilai: (r) => r.location_name || '' },
    { label: 'Shift hari ini', nilai: (r) => (r.shift ? `${r.shift.kode} ${r.shift.mulai}–${r.shift.selesai}` : '') },
    { label: 'Asal', nilai: (r) => SUMBER[r.sumber] || '' },
    { label: 'Penugasan berlaku hingga', nilai: berlakuHingga },
  ];

  const ringkasan = tab === 'shifts' ? (summary && (
    <p className="text-sm text-muted-foreground" data-testid="shift-summary">
      <span className="font-medium text-foreground">{summary.total_shifts}</span> shift aktif tersimpan
      {shifts.some(s => s.id === CADANGAN) ? ' + 1 shift cadangan sistem' : ''}
      {' · '}<span className="font-medium text-foreground">{summary.total_assigned_employees}</span> penugasan aktif
      {summary.by_shift?.[0] ? <> · paling banyak dipakai: <span className="font-medium text-foreground">{summary.by_shift[0].shift_name}</span> ({summary.by_shift[0].count})</> : null}
.<span className="hidden sm:inline"> Karyawan tanpa penugasan memakai shift utamanya di Data Karyawan atau shift cadangan.</span>
    </p>
  )) : (
    <p className="text-sm text-muted-foreground" data-testid="assign-summary">
      <span className="font-medium text-foreground">{rows.length}</span> karyawan aktif
      {' · '}<span className="font-medium text-foreground">{rows.filter((r) => !r.shift).length}</span> belum punya shift
      {terpilih.size > 0 && <> · <span className="font-medium text-foreground">{terpilih.size}</span> dipilih</>}.
      <span className="hidden sm:inline"> Centang beberapa baris lalu Tugaskan shift untuk menugaskan sekaligus.</span>
    </p>
  );

  const pil = !bagian && (
    <FilterChips value={tabSendiri} onChange={setTabSendiri} hideWhenEmpty={false} testId="shift-bagian"
      options={[{ key: 'shifts', label: 'Daftar shift', count: shifts.length }, { key: 'assignments', label: 'Penugasan', count: rows.length }]} />
  );
  const penyaringTugas = tab === 'assignments' && (<>
    <Input value={cari} onChange={(e) => setCari(e.target.value)} placeholder="Cari karyawan" className="h-9 w-48" aria-label="Cari karyawan" />
    <SmartNativeSelect value={dept} onChange={(e) => setDept(e.target.value)} className="h-9 w-44" aria-label="Departemen">
      <option value="">Semua departemen</option>
      {deptOpsi.map((d) => <option key={d.value} value={d.value}>{d.legacy ? d.value : d.label}</option>)}
    </SmartNativeSelect>
    {lokasi.length > 1 && (
      <SmartNativeSelect value={lok} onChange={(e) => setLok(e.target.value)} className="h-9 w-40" aria-label="Lokasi">
        <option value="">Semua lokasi</option>
        {lokasi.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
      </SmartNativeSelect>
    )}
  </>);

  const muatUlang = (
    <Button variant="outline" size="icon" onClick={() => { load(); if (tab === 'assignments') loadRows(); }} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
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
        <Button onClick={() => setAssignOpen(true)} data-testid="shift-assign-add"><Plus />Tugaskan shift{terpilih.size ? ` (${terpilih.size})` : ''}</Button>
      ))}
      filters={<>{pil}{penyaringTugas}</>}
      tools={<>
        {tab === 'shifts'
          ? <TombolUnduh namaBerkas="daftar-shift" namaLembar="Shift" baris={shifts} kolom={unduhShift} testId="shift-unduh" />
          : <TombolUnduh namaBerkas="penugasan-shift" namaLembar="Penugasan shift" baris={rows} kolom={unduhTugas} testId="shift-assign-unduh" />}
        {muatUlang}
      </>}
      summary={ringkasan}
      footer={tab === 'assignments' && rows.length > 25
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
        <TabelData kolom={kolomTugas} baris={paged} kunci={(r) => r.employee_id} testId="shift-assign-table"
          kosong={<EmptyState title="Belum ada karyawan aktif"
            description="Karyawan tanpa penugasan memakai shift utamanya di Data Karyawan atau shift bawaan 08:00–17:00." />} />
      )}

      <ShiftForm open={shiftForm !== null} initial={shiftForm?.id ? shiftForm : null}
        onSave={shiftForm?.id ? handleUpdateShift : handleCreateShift} onClose={() => setShiftForm(null)} />
      <PenugasanForm open={assignOpen} shifts={shifts} employees={employees} terpilih={[...terpilih]} deptOpsi={deptOpsi}
        lokasi={lokasi} onSave={handleAssign} onClose={() => setAssignOpen(false)} />
    </PageLayout>
  );
}

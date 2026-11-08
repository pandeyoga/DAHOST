/**
 * HREmployeeModule — Portal SDM › Data Karyawan.
 *
 * Standar UI/UX v2 (keputusan owner 8 Nov 2026): cetakan PageLayout (kepala tipis, penyaring satu baris),
 * daftar = TabelData (kartu ringkas di HP) + unduh Excel/CSV, klik baris → popup detail (dengan rincian
 * kelengkapan data), aksi baris = Ubah + "Lainnya" (tautkan akun, nonaktifkan), form karyawan = FormPopup
 * panjang dengan pemilih tanggal seragam, tautkan akun = FormPopup pendek dengan pilihan yang bisa dicari.
 * Data yang dikirim ke server, validasi, dan alur tidak berubah.
 */
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import axios from 'axios';
import {
  Plus, Pencil, Search, RefreshCw, UploadCloud, Trash2, Camera, Power, Link2, MoreHorizontal, FileText,
} from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { Checkbox } from '@/components/ui/checkbox';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import DatePicker, { formatTanggalID } from '@/components/ui/date-picker';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { todayWIB, toWIBDate, daysBetweenISO } from '@/lib/waktu';
import { withFileAuth } from '@/lib/fileUrl';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';
import {
  EmployeeSelect, useHrMasters, departmentOptions, positionOptions, unitByName, shiftLabel,
  useDepartmentFilterOptions, EMERGENCY_RELATIONS,
} from './hr/hrPickers';

const API = process.env.REACT_APP_BACKEND_URL;

// 2026-11-07 (Tahap 5): departemen & jabatan TIDAK lagi daftar tetap di kode — diambil dari master
// Struktur Organisasi (unit & posisi), jabatan mengikuti departemen yang dipilih. Nilai lama hasil impor
// yang belum ada di master tetap tampil (ditandai) supaya tidak hilang saat formulir dibuka.
// 2026-11-06 (Tahap 2): skema & tarif gaji TIDAK lagi diisi di sini — satu sumber = Profil Gaji (Penggajian).
// Layar ini hanya menampilkannya (baca saja).
const PAY_SCHEME_LABEL = { monthly: 'Bulanan', weekly: 'Mingguan', hourly: 'Borongan per jam', pcs: 'Borongan per pcs' };
const CONTRACT_TYPES = [
  { value: 'PKWT',   label: 'PKWT (kontrak waktu tertentu)' },
  { value: 'PKWTT',  label: 'PKWTT (kontrak tidak tertentu)' },
  { value: 'Magang', label: 'Magang / percobaan' },
  { value: 'Tetap',  label: 'Karyawan tetap' },
];
const CONTRACT_TONE = { PKWTT: 'success', Tetap: 'success', PKWT: 'warning', Magang: 'info' };
const EDUCATION_LEVELS = ['Tidak Sekolah', 'SD', 'SMP', 'SMA/SMK', 'D1-D3', 'S1', 'S2', 'S3'];
const MARITAL_STATUS = [
  { value: 'single',   label: 'Belum menikah' },
  { value: 'married',  label: 'Menikah' },
  { value: 'divorced', label: 'Cerai hidup' },
  { value: 'widowed',  label: 'Cerai mati' },
];
const RELIGIONS = ['Islam', 'Kristen Protestan', 'Katolik', 'Hindu', 'Buddha', 'Konghucu', 'Kepercayaan'];
const TAX_PTKP = [
  { value: 'TK/0', label: 'TK/0 — tidak kawin, tanpa tanggungan' },
  { value: 'TK/1', label: 'TK/1 — tidak kawin, 1 tanggungan' },
  { value: 'TK/2', label: 'TK/2 — tidak kawin, 2 tanggungan' },
  { value: 'TK/3', label: 'TK/3 — tidak kawin, 3 tanggungan' },
  { value: 'K/0',  label: 'K/0 — kawin, tanpa tanggungan' },
  { value: 'K/1',  label: 'K/1 — kawin, 1 tanggungan' },
  { value: 'K/2',  label: 'K/2 — kawin, 2 tanggungan' },
  { value: 'K/3',  label: 'K/3 — kawin, 3 tanggungan' },
];
// Bank di luar daftar: pilih "Bank lain" lalu ketik namanya (dulu "Lainnya" tersimpan apa adanya → nama bank hilang).
const BANKS = ['BCA', 'BRI', 'Mandiri', 'BNI', 'BSI', 'CIMB Niaga', 'Permata', 'Danamon', 'BTN', 'Mega', 'Panin', 'Jago'];
const BANK_OTHER = '__lain';
const RELATIONS = EMERGENCY_RELATIONS;   // satu daftar dengan Portal Saya › Profil (HR1, 2026-11-07)
const DOC_CATEGORIES = ['Kontrak Kerja', 'KTP', 'NPWP', 'Ijazah', 'SKCK', 'Sertifikat', 'Surat Pengalaman', 'BPJS', 'KK (Kartu Keluarga)', 'Pas Foto', 'Lainnya'];

const defaultEmployee = {
  employee_code: '', name: '', department: '', job_title: '', shift_id: '',
  location_id: '', phone: '', email: '', contract_type: 'PKWT', contract_start_date: '',
  contract_end_date: '', join_date: '', resign_date: '',
  manager_id: '',
  gender: 'L', birth_date: '', birth_place: '', marital_status: 'single', religion: 'Islam',
  nationality: 'Indonesia', ktp_address: '', current_address: '',
  education_level: 'SMA/SMK', education_institution: '', education_major: '', photo_url: '',
  ktp_number: '', npwp_number: '', tax_ptkp: 'TK/0',
  bpjs_kesehatan_number: '', bpjs_ketenagakerjaan_number: '',
  bank_name: '', bank_account_number: '', bank_account_holder: '',
  emergency_contact_name: '', emergency_phone: '', emergency_relation: 'Orang Tua',
};

// 2026-11-02 (K23): kepesertaan BPJS per program. Cermin backend resolve_bpjs_programs().
const BPJS_PROGRAMS = [['kes', 'BPJS Kesehatan'], ['jht', 'JHT'], ['jp', 'JP'], ['jkk_jkm', 'JKK & JKM']];
function bpjsProgramsOf(emp) {
  if (emp?.bpjs_programs && typeof emp.bpjs_programs === 'object') return emp.bpjs_programs;
  const kes = !!String(emp?.bpjs_kesehatan_number || '').trim();
  const tk = !!String(emp?.bpjs_ketenagakerjaan_number || '').trim();
  return { kes, jht: tk, jp: tk, jkk_jkm: tk };
}

/** Tanggal tersimpan (YYYY-MM-DD atau ISO) → "30 Apr 2027" (tanggal kalender WIB). */
const tgl = (v) => (v ? formatTanggalID(toWIBDate(v)) : '');
const ymdOf = (v) => (v ? String(v).slice(0, 10) : '');
const PERAN = { owner: 'Owner', superadmin: 'Super admin', admin: 'Admin', manager: 'Manajer', hr: 'HR' };
const labelPeran = (r) => {
  const s = String(r || '').trim().toLowerCase();
  if (!s) return '';
  if (PERAN[s]) return PERAN[s];
  const t = s.replace(/[_-]+/g, ' ');
  return t.charAt(0).toUpperCase() + t.slice(1);
};

/**
 * Kelengkapan data: 8 isian penting (sama dengan rumus lama). Rinciannya ditampilkan di popup detail supaya
 * persentase bisa dijelaskan. Catatan: PTKP bawaan formulir = TK/0, jadi TK/0 dihitung "belum diatur".
 */
function kelengkapan(emp) {
  const items = [
    { label: 'NIK KTP 16 digit', ok: !!emp.ktp_number && emp.ktp_number.length === 16 },
    { label: 'Nomor rekening bank', ok: !!emp.bank_account_number },
    { label: 'Nomor telepon', ok: !!emp.phone },
    { label: 'Tipe kontrak', ok: !!emp.contract_type },
    { label: 'Tanggal lahir', ok: !!emp.birth_date },
    { label: 'Kontak darurat', ok: !!emp.emergency_contact_name },
    { label: 'No. BPJS Kesehatan', ok: !!emp.bpjs_kesehatan_number },
    { label: 'Status PTKP diatur (selain bawaan TK/0)', ok: !!emp.tax_ptkp && emp.tax_ptkp !== 'TK/0' },
  ];
  const pct = Math.round(items.filter((i) => i.ok).length / items.length * 100);
  return { items, pct };
}

function sisaKontrak(emp) {
  // sisa hari kalender WIB (kontrak berakhir hari ini = 0, bukan sudah lewat sejak 07:00 WIB)
  const days = emp.contract_end_date ? daysBetweenISO(todayWIB(), toWIBDate(emp.contract_end_date)) : null;
  return { days, expiring: days !== null && days >= 0 && days <= 30 };
}

function Avatar({ emp }) {
  if (emp.photo_url) {
    return <img src={withFileAuth(`${API}${emp.photo_url}`)} alt={emp.name}
      className="h-8 w-8 shrink-0 rounded-full border border-[var(--glass-border)] object-cover" />;
  }
  return (
    <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full border border-[var(--glass-border)] bg-[var(--card-surface)] text-xs font-semibold text-foreground">
      {(emp.name || '?').slice(0, 2).toUpperCase()}
    </div>
  );
}

function KontrakBadge({ type }) {
  if (!type) return <span className="text-muted-foreground">—</span>;
  return <StatusBadge status={type} label={type} tone={CONTRACT_TONE[type] || 'default'} />;
}

function Kelengkapan({ pct }) {
  const warna = pct >= 80 ? 'bg-[hsl(var(--success))]' : pct >= 50 ? 'bg-[hsl(var(--warning))]' : 'bg-[hsl(var(--destructive))]';
  return (
    <div className="flex items-center gap-2" title={`Kelengkapan data ${pct}%`}>
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-foreground/10">
        <div className={`h-full ${warna}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums text-foreground">{pct}%</span>
    </div>
  );
}

export default function HREmployeeModule({ token }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);
  const [employees, setEmployees] = useState([]);
  const [locations, setLocations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [deptFilter, setDeptFilter] = useState('');
  const [activeOnly, setActiveOnly] = useState(true);
  const [editing, setEditing] = useState(null);
  const [detail, setDetail] = useState(null);
  // Tautkan akun login
  const [linkTarget, setLinkTarget] = useState(null); // employee object
  const [users, setUsers] = useState([]);
  const [linking, setLinking] = useState(false);
  const masters = useHrMasters(token);
  const deptFilterOptions = useDepartmentFilterOptions(masters.units, employees);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [r1, r2] = await Promise.all([
        axios.get(`${API}/api/rahaza/employees?active_only=${activeOnly}&limit=500`, { headers }),
        axios.get(`${API}/api/rahaza/locations`, { headers }).catch(() => ({ data: [] })),
      ]);
      setEmployees(Array.isArray(r1.data) ? r1.data : (r1.data.items || r1.data.rows || []));
      setLocations(r2.data || []);
    } catch (e) {
      toast.error('Gagal memuat data karyawan');
    } finally { setLoading(false); }
  }, [headers, activeOnly]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    (async () => {
      try {
        const [r1, r2] = await Promise.all([
          axios.get(`${API}/api/rahaza/employees?active_only=${activeOnly}&limit=500`, { headers }),
          axios.get(`${API}/api/rahaza/locations`, { headers }).catch(() => ({ data: [] })),
        ]);
        if (!active) return;
        setEmployees(Array.isArray(r1.data) ? r1.data : (r1.data.items || r1.data.rows || []));
        setLocations(r2.data || []);
      } catch {
        if (active) toast.error('Gagal memuat data karyawan');
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [headers, activeOnly]);

  const filtered = employees.filter(e => {
    if (deptFilter && e.department !== deptFilter) return false;
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      e.name?.toLowerCase().includes(q) ||
      e.employee_code?.toLowerCase().includes(q) ||
      e.phone?.includes(q) ||
      e.ktp_number?.includes(q) ||
      e.email?.toLowerCase().includes(q)
    );
  });
  const lokasiNama = useMemo(() => Object.fromEntries(locations.map(l => [l.id, `${l.code} · ${l.name}`])), [locations]);

  const handleDelete = async (emp) => {
    if (!(await confirmDialog({
      title: `Nonaktifkan ${emp.name} (${emp.employee_code})?`,
      body: 'Karyawan tidak muncul lagi di pilihan absensi dan penggajian. Datanya tetap tersimpan.',
      confirmLabel: 'Nonaktifkan', danger: true,
    }))) return;
    try {
      await axios.delete(`${API}/api/rahaza/employees/${emp.id}`, { headers });
      toast.success('Karyawan dinonaktifkan');
      setDetail(null);
      load();
    } catch { toast.error('Gagal menonaktifkan karyawan'); }
  };

  const handleSave = async (form) => {
    const isEdit = !!form.id;
    const url = isEdit
      ? `${API}/api/rahaza/employees/${form.id}`
      : `${API}/api/rahaza/employees`;
    await axios[isEdit ? 'put' : 'post'](url, form, { headers });
    toast.success(isEdit ? 'Data karyawan disimpan' : 'Karyawan ditambahkan');
    setEditing(null);
    load();
  };

  const openLinkUser = async (emp) => {
    setDetail(null);
    setLinkTarget(emp);
    if (users.length === 0) {
      try {
        const r = await axios.get(`${API}/api/auth/users?limit=200`, { headers });
        setUsers(Array.isArray(r.data) ? r.data : []);
      } catch { /* noop */ }
    }
  };

  const handleLinkUser = async (userId) => {
    if (!linkTarget) return;
    setLinking(true);
    try {
      await axios.post(`${API}/api/rahaza/employees/${linkTarget.id}/link-user`,
        { user_id: userId }, { headers });
      toast.success(userId ? `Akun ditautkan ke ${linkTarget.name}` : 'Tautan akun dihapus');
      setLinkTarget(null);
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Gagal menautkan akun');
    } finally { setLinking(false); }
  };

  const ubah = (e) => { setDetail(null); setEditing(e); };

  const { page, setPage, totalPages, total, paged } = useClientPagination(filtered, 10);

  const kolom = [
    { kunci: 'nama', label: 'Karyawan', hp: 'judul', isi: (e) => (
      <div className="flex min-w-0 items-center gap-3">
        <Avatar emp={e} />
        <div className="min-w-0">
          <p className="truncate font-medium text-foreground">{e.name}</p>
          <p className="text-xs text-muted-foreground">{e.employee_code}</p>
        </div>
      </div>) },
    { kunci: 'jabatan', label: 'Departemen & jabatan', hp: 'keterangan', isi: (e) => (
      <div className="min-w-0">
        <p className="text-sm text-foreground">{e.job_title || '—'}</p>
        <p className="text-xs text-muted-foreground">{e.department || '—'}{e.manager_name ? ` · atasan ${e.manager_name}` : ''}</p>
      </div>) },
    { kunci: 'kontrak', label: 'Kontrak', isi: (e) => {
      const s = sisaKontrak(e);
      return (
        <div className="space-y-1">
          <KontrakBadge type={e.contract_type} />
          {e.contract_end_date && (
            <p className={`text-xs ${s.expiring ? 'font-medium text-[hsl(var(--danger-text))]' : 'text-muted-foreground'}`}>
              s/d {tgl(e.contract_end_date)}{s.expiring && ` (${s.days} hari lagi)`}
            </p>
          )}
        </div>
      );
    } },
    { kunci: 'kontak', label: 'Telepon', isi: (e) => <span className="text-sm tabular-nums">{e.phone || '—'}</span> },
    { kunci: 'lengkap', label: 'Kelengkapan', isi: (e) => <Kelengkapan pct={kelengkapan(e).pct} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (e) => (
      <div className="flex items-center justify-end gap-1">
        <Button size="sm" variant="outline" onClick={() => ubah(e)} data-testid={`employee-edit-${e.id}`}>
          <Pencil />Ubah
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="icon-sm" variant="ghost" aria-label="Lainnya" title="Lainnya" data-testid={`employee-more-${e.id}`}>
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => openLinkUser(e)} data-testid={`employee-link-${e.id}`}>
              <Link2 className="mr-2 h-4 w-4" />{e.user_id ? 'Ganti tautan akun login' : 'Tautkan akun login'}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => handleDelete(e)} className="text-[hsl(var(--danger-text))]">
              <Power className="mr-2 h-4 w-4" />Nonaktifkan
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>) },
  ];

  const kolomUnduh = [
    { label: 'Kode', nilai: (e) => e.employee_code },
    { label: 'Nama', nilai: (e) => e.name },
    { label: 'Departemen', nilai: (e) => e.department || '' },
    { label: 'Jabatan', nilai: (e) => e.job_title || '' },
    { label: 'Atasan', nilai: (e) => e.manager_name || '' },
    { label: 'Tipe kontrak', nilai: (e) => e.contract_type || '' },
    { label: 'Mulai kontrak', nilai: (e) => tgl(e.contract_start_date) },
    { label: 'Berakhir kontrak', nilai: (e) => tgl(e.contract_end_date) },
    { label: 'Tanggal masuk', nilai: (e) => tgl(e.join_date) },
    { label: 'Lokasi', nilai: (e) => lokasiNama[e.location_id] || e.location_name || '' },
    { label: 'Telepon', nilai: (e) => e.phone || '' },
    { label: 'Email', nilai: (e) => e.email || '' },
    { label: 'Akun login', nilai: (e) => e.user_email || '' },
    { label: 'Status', nilai: (e) => (e.active === false ? 'Nonaktif' : 'Aktif') },
    { label: 'Kelengkapan (%)', nilai: (e) => kelengkapan(e).pct },
  ];

  return (
    <PageLayout testId="hr-employees-page" title="Data Karyawan"
      subtitle="Kontrak, data pribadi, pajak & BPJS, rekening, dan dokumen tiap karyawan."
      actions={<Button onClick={() => setEditing({ ...defaultEmployee })} data-testid="employees-add"><Plus />Tambah karyawan</Button>}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={e => { setSearch(e.target.value); setPage(1); }}
            placeholder="Cari nama, kode, NIK, email, HP" className="pl-8" data-testid="employees-search" />
        </div>
        <SmartNativeSelect value={deptFilter} onChange={e => { setDeptFilter(e.target.value); setPage(1); }}
          wrapperClassName="w-full sm:w-56" className="w-full" aria-label="Departemen" data-testid="employees-dept-filter">
          <option value="">Semua departemen</option>
          {deptFilterOptions.map(d => <option key={d.value} value={d.value}>{d.legacy ? d.value : d.label}</option>)}
        </SmartNativeSelect>
        <label htmlFor="active-only" className="flex h-9 cursor-pointer items-center gap-2 text-sm text-foreground">
          <Switch checked={activeOnly} onCheckedChange={(v) => { setActiveOnly(v); setPage(1); }} id="active-only" />
          Aktif saja
        </label>
        {/* Alat ditaruh di ujung baris penyaring (bukan slot `tools`): di HP slot `tools` menyempitkan penyaring
            ke separuh lebar layar (lihat laporan, permintaan komponen bersama). Di layar lebar tetap rata kanan. */}
        <div className="ml-auto flex items-center gap-2">
          <TombolUnduh namaBerkas="data-karyawan" namaLembar="Karyawan" baris={filtered} kolom={kolomUnduh}
            testId="employees-unduh" />
          <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
            data-testid="employees-refresh">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
        </div>
      </>}
      footer={<PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />}>
      {loading && employees.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat data karyawan…</p>
      ) : (
        <TabelData kolom={kolom} baris={paged} onKlikBaris={setDetail} testId="employees-table"
          kosong={<EmptyState
            title={employees.length ? 'Tidak ada karyawan yang cocok' : 'Belum ada karyawan'}
            description={employees.length ? 'Ubah kata pencarian atau pilihan departemen.' : 'Tambahkan karyawan pertama dengan tombol Tambah karyawan.'} />} />
      )}

      {detail && (
        <DetailKaryawan emp={detail} lokasi={lokasiNama[detail.location_id] || detail.location_name}
          onClose={() => setDetail(null)} onUbah={() => ubah(detail)}
          onTautkan={() => openLinkUser(detail)} onNonaktifkan={() => handleDelete(detail)} />
      )}

      {editing && (
        <EmployeeDialog
          initial={editing}
          locations={locations}
          employees={employees}
          masters={masters}
          headers={headers}
          onSave={handleSave}
          onClose={() => setEditing(null)}
        />
      )}

      {linkTarget && (
        <TautkanAkun target={linkTarget} users={users} linking={linking}
          onPilih={handleLinkUser} onClose={() => setLinkTarget(null)} />
      )}
    </PageLayout>
  );
}

// ─── Detail (popup) ───────────────────────────────────────────────────────────
function DetailKaryawan({ emp, lokasi, onClose, onUbah, onTautkan, onNonaktifkan }) {
  const k = kelengkapan(emp);
  const s = sisaKontrak(emp);
  const kurang = k.items.filter((i) => !i.ok);
  return (
    <DetailPopup open onClose={onClose} judul={emp.name} keterangan={emp.employee_code} testId="employee-detail"
      status={<><KontrakBadge type={emp.contract_type} />
        {emp.active === false && <StatusBadge status="nonaktif" label="Nonaktif" tone="muted" />}</>}
      aksi={<>
        <Button size="sm" variant="outline" onClick={onUbah}><Pencil />Ubah</Button>
        <Button size="sm" variant="outline" onClick={onTautkan}><Link2 />{emp.user_id ? 'Ganti akun login' : 'Tautkan akun login'}</Button>
        {emp.active !== false && (
          <Button size="sm" variant="destructive" onClick={onNonaktifkan}><Power />Nonaktifkan</Button>
        )}
      </>}>
      <div className="flex items-start gap-4">
        {emp.photo_url && (
          <img src={withFileAuth(`${API}${emp.photo_url}`)} alt={emp.name}
            className="h-20 w-20 shrink-0 rounded-lg border border-[var(--glass-border)] object-cover" />
        )}
        <dl className="min-w-0 flex-1 divide-y divide-[var(--glass-border)]">
          <BarisDetail label="Departemen">{emp.department || '—'}</BarisDetail>
          <BarisDetail label="Jabatan">{emp.job_title || '—'}</BarisDetail>
          <BarisDetail label="Atasan">{emp.manager_name || '—'}</BarisDetail>
          <BarisDetail label="Lokasi utama">{lokasi || '—'}</BarisDetail>
          <BarisDetail label="Shift utama">{emp.shift_code || '—'}</BarisDetail>
          <BarisDetail label="Kontrak">
            {emp.contract_type || '—'}
            {(emp.contract_start_date || emp.contract_end_date) && ` · ${tgl(emp.contract_start_date) || '…'} s/d ${tgl(emp.contract_end_date) || '…'}`}
            {s.expiring && <span className="ml-1 font-medium text-[hsl(var(--danger-text))]">({s.days} hari lagi)</span>}
          </BarisDetail>
          <BarisDetail label="Tanggal masuk">{tgl(emp.join_date) || '—'}</BarisDetail>
          {emp.resign_date && <BarisDetail label="Tanggal keluar">{tgl(emp.resign_date)}</BarisDetail>}
          <BarisDetail label="Telepon">{emp.phone || '—'}</BarisDetail>
          <BarisDetail label="Email">{emp.email || '—'}</BarisDetail>
          <BarisDetail label="Akun login">{emp.user_email || (emp.user_id ? 'Tertaut' : 'Belum ditautkan')}</BarisDetail>
        </dl>
      </div>
      <div>
        <p className="mb-2 text-sm font-medium text-foreground">Kelengkapan data {k.pct}%</p>
        {kurang.length === 0 ? (
          <p className="text-sm text-muted-foreground">Delapan isian penting sudah terisi.</p>
        ) : (
          <p className="text-sm text-muted-foreground">
            Belum terisi: {kurang.map((i) => i.label).join(', ')}.
          </p>
        )}
      </div>
    </DetailPopup>
  );
}

// ─── Tautkan akun login (popup pendek) ─────────────────────────────────────────
function TautkanAkun({ target, users, linking, onPilih, onClose }) {
  const [pilih, setPilih] = useState(target.user_id || '');
  const pilihan = users.filter(u => u.role !== 'superadmin');
  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="link-user-dialog"
      judul={`Tautkan akun login — ${target.name}`}
      keterangan="Setelah ditautkan, karyawan bisa membuka Portal Saya (slip gaji, cuti, dan lainnya)."
      onSimpan={() => onPilih(pilih)} menyimpan={linking} bisaSimpan={!!pilih && pilih !== target.user_id}
      labelSimpan="Tautkan"
      aksiKiri={target.user_id ? (
        <Button type="button" variant="outline" onClick={() => onPilih('')} disabled={linking}
          className="text-[hsl(var(--danger-text))]" data-testid="link-user-hapus">
          Hapus tautan
        </Button>
      ) : null}>
      {target.user_id && (
        <p className="text-sm text-muted-foreground">Saat ini tertaut ke <span className="text-foreground">{target.user_email || target.user_id}</span>.</p>
      )}
      <Isian label="Akun pengguna" htmlFor="link-user-pilih"
        petunjuk={users.length === 0 ? 'Memuat daftar pengguna…' : `${pilihan.length} akun bisa dipilih.`}>
        <SmartNativeSelect id="link-user-pilih" value={pilih} onChange={(e) => setPilih(e.target.value)}
          searchable className="w-full" data-testid="link-user-select">
          <option value="">— Pilih akun —</option>
          {pilihan.map(u => (
            <option key={u.id} value={u.id}>{`${u.name || u.email} · ${u.email}${u.role ? ` · ${labelPeran(u.role)}` : ''}`}</option>
          ))}
        </SmartNativeSelect>
      </Isian>
    </FormPopup>
  );
}

// ─── Form karyawan (popup panjang) ─────────────────────────────────────────────
function EmployeeDialog({ initial, locations, employees = [], masters = {}, headers, onSave, onClose }) {
  const [form, setForm] = useState(initial);
  const [bankOther, setBankOther] = useState(() => !!initial.bank_name && !BANKS.includes(initial.bank_name));
  const deptOpts = departmentOptions(masters.units, form.department);
  const selectedUnit = unitByName(masters.units, form.department);
  const posOpts = positionOptions(masters.positions, selectedUnit, form.job_title);
  const activeShifts = masters.shifts || [];
  // Departemen berganti → jabatan yang tidak dimiliki departemen baru dikosongkan (jabatan bergantung departemen).
  // Departemen tanpa jabatan di master → jabatan lama dibiarkan (tidak ada pilihan pengganti).
  const changeDepartment = (v) => setForm(f => {
    const unit = unitByName(masters.units, v);
    const opts = positionOptions(masters.positions, unit, '');
    const keep = !opts.length || opts.some(o => o.value === f.job_title);
    return { ...f, department: v, job_title: keep ? f.job_title : '' };
  });
  const [saving, setSaving] = useState(false);
  const [galat, setGalat] = useState('');
  const [documents, setDocuments] = useState([]);
  const [docCategory, setDocCategory] = useState(DOC_CATEGORIES[0]);
  const docInput = useRef(null);
  const photoInput = useRef(null);
  const [tab, setTab] = useState('dasar');
  const [salaryProfile, setSalaryProfile] = useState(null);
  const isEdit = !!form.id;

  // Profil Gaji (baca saja) — 2026-11-06 (Tahap 2). Peran tanpa akses payroll melihat "—".
  useEffect(() => {
    if (!form.id) return undefined;
    let active = true;
    (async () => {
      try {
        const { data } = await axios.get(`${API}/api/rahaza/payroll-profiles?employee_id=${form.id}`, { headers });
        if (active) setSalaryProfile(Array.isArray(data) && data.length ? data[0] : false);
      } catch { if (active) setSalaryProfile(false); }
    })();
    return () => { active = false; };
  }, [form.id, headers]);

  const loadDocs = useCallback(async () => {
    if (!form.id) return;
    try {
      const { data } = await axios.get(`${API}/api/rahaza/employees/${form.id}/documents`, { headers });
      setDocuments(data.documents || []);
    } catch { /* ignore: docs are optional */ }
  }, [form.id, headers]);

  useEffect(() => {
    if (!form.id) return undefined;
    let active = true;
    (async () => {
      try {
        const { data } = await axios.get(`${API}/api/rahaza/employees/${form.id}/documents`, { headers });
        if (active) setDocuments(data.documents || []);
      } catch { /* ignore: docs are optional */ }
    })();
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.id, headers]);

  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e?.target ? e.target.value : e }));
  const tolak = (pesan, keTab) => { setGalat(pesan); if (keTab) setTab(keTab); };

  const submit = async () => {
    setGalat('');
    if (!form.employee_code || !form.name) { tolak('Kode dan nama wajib diisi.', 'dasar'); return; }
    if (form.ktp_number && form.ktp_number.length !== 16) { tolak('NIK KTP harus 16 digit.', 'pajak'); return; }
    // 2026-11-06 (Tahap 2): NPWP 15 digit (lama) atau 16 digit (NIK = NPWP sejak 2024) diterima.
    if (form.npwp_number && ![15, 16].includes(form.npwp_number.replace(/[^0-9]/g, '').length)) { tolak('NPWP harus 15 atau 16 digit.', 'pajak'); return; }
    if (form.join_date && form.resign_date && form.resign_date < form.join_date) { tolak('Tanggal keluar tidak boleh sebelum tanggal masuk.', 'kontrak'); return; }
    if (form.contract_start_date && form.contract_end_date && form.contract_end_date < form.contract_start_date) { tolak('Tanggal berakhir kontrak tidak boleh sebelum tanggal mulai.', 'kontrak'); return; }
    if (!isEdit && ['PKWT', 'Magang'].includes(form.contract_type) && !form.contract_end_date) { tolak('Tanggal berakhir kontrak wajib untuk PKWT/Magang.', 'kontrak'); return; }
    if (bankOther && !String(form.bank_name || '').trim()) { tolak('Ketik nama bank.', 'bank'); return; }
    const payload = { ...form };
    delete payload.base_rate;      // gaji hanya di Profil Gaji
    delete payload.wage_scheme;
    delete payload.location_name;  // nama turunan daftar — dulu ikut tersimpan (basi) saat lokasi diganti
    const sh = activeShifts.find(s => s.id === form.shift_id);
    payload.shift_id = form.shift_id || null;
    payload.shift_code = sh ? sh.code : (form.shift_id ? form.shift_code : null);
    setSaving(true);
    try {
      await onSave(payload);
    } catch (e) {
      setGalat(e.response?.data?.detail || 'Gagal menyimpan data karyawan.');
    } finally {
      setSaving(false);
    }
  };

  const uploadFile = async (file, onUrl, category = '') => {
    const fd = new FormData();
    fd.append('file', file);
    try {
      const { data } = await axios.post(
        `${API}/api/upload?entity_type=employee&entity_id=${form.id || 'new'}`,
        fd, { headers: { ...headers, 'Content-Type': 'multipart/form-data' } }
      );
      // storage_path → build public URL
      const url = data.storage_path ? `/api/files/${data.storage_path}` : '';
      onUrl(url, data);
      if (form.id && category) {
        // Save category
        try {
          await axios.put(`${API}/api/attachments/${data.id}/meta`, { category }, { headers });
        } catch { /* ignore: category metadata is best-effort */ }
      }
      return data;
    } catch (e) {
      toast.error('Unggah gagal: ' + (e.response?.data?.detail || e.message));
      return null;
    }
  };

  const onPhotoChange = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 3 * 1024 * 1024) { toast.error('Foto maksimal 3 MB'); return; }
    const data = await uploadFile(file, (url) => setForm(f => ({ ...f, photo_url: url })));
    if (data && form.id) {
      // Update photo_url on employee record
      await axios.post(`${API}/api/rahaza/employees/${form.id}/photo`,
        { photo_url: `/api/files/${data.storage_path}` }, { headers });
    }
  };

  const onDocUpload = async (e, category) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const up = await uploadFile(file, () => {}, category);
    e.target.value = '';
    if (!up) return;  // 2026-11-06 (pola P6): uploadFile sudah menampilkan error; dulu lalu tetap "diunggah"
    toast.success(`Dokumen ${category} diunggah`);
    loadDocs();
  };

  const deleteDoc = async (attId) => {
    if (!(await confirmDialog({ title: 'Hapus dokumen ini?', body: 'Berkas dihapus dari data karyawan.', confirmLabel: 'Hapus', danger: true }))) return;
    try {
      await axios.delete(`${API}/api/attachments/${attId}`, { headers });
      toast.success('Dokumen dihapus');
      loadDocs();
    } catch { toast.error('Gagal menghapus dokumen'); }
  };

  const kolomDok = [
    { kunci: 'nama', label: 'Nama berkas', hp: 'judul', isi: (d) => (
      <a href={withFileAuth(`${API}/api/files/${d.storage_path}`)} target="_blank" rel="noreferrer"
        className="inline-flex items-center gap-1 text-primary hover:underline">
        <FileText className="h-3.5 w-3.5" />{d.original_filename}
      </a>) },
    { kunci: 'kategori', label: 'Kategori', isi: (d) => d.category || '—' },
    { kunci: 'ukuran', label: 'Ukuran', rata: 'kanan', isi: (d) => <span className="tabular-nums">{d.size ? `${(d.size / 1024).toFixed(1)} KB` : '—'}</span> },
    { kunci: 'tgl', label: 'Diunggah', isi: (d) => tgl(d.created_at) || '—' },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (d) => (
      <Button type="button" size="icon-sm" variant="ghost" onClick={() => deleteDoc(d.id)}
        aria-label="Hapus dokumen" title="Hapus dokumen">
        <Trash2 />
      </Button>) },
  ];

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" onSimpan={submit} menyimpan={saving} galat={galat}
      judul={isEdit ? `Ubah data ${form.name}` : 'Tambah karyawan'}
      keterangan="Data dasar, pribadi, pajak & BPJS, rekening, dan dokumen karyawan."
      labelSimpan={isEdit ? 'Simpan perubahan' : 'Simpan karyawan'} testId="employee-form">
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="h-auto max-w-full justify-start gap-1 max-sm:flex-nowrap max-sm:overflow-x-auto sm:flex-wrap">
          <TabsTrigger value="dasar" className="shrink-0">Data dasar</TabsTrigger>
          <TabsTrigger value="kontrak" className="shrink-0">Kontrak</TabsTrigger>
          <TabsTrigger value="personal" className="shrink-0">Pribadi</TabsTrigger>
          <TabsTrigger value="pajak" className="shrink-0">Pajak & BPJS</TabsTrigger>
          <TabsTrigger value="bank" className="shrink-0">Rekening & kontak darurat</TabsTrigger>
          <TabsTrigger value="dokumen" disabled={!isEdit} className="shrink-0"
            title={isEdit ? undefined : 'Simpan karyawan dulu, lalu unggah dokumen'}>Dokumen</TabsTrigger>
        </TabsList>

        {/* Tab 1: Data dasar */}
        <TabsContent value="dasar" className="mt-4">
          <div className="grid grid-cols-1 items-start gap-4 sm:grid-cols-2">
            <Isian label="Kode karyawan" wajib htmlFor="emp-code-input">
              <Input id="emp-code-input" value={form.employee_code} onChange={set('employee_code')} placeholder="EMP-001" data-testid="emp-code" />
            </Isian>
            <Isian label="Nama lengkap" wajib htmlFor="emp-name-input">
              <Input id="emp-name-input" value={form.name} onChange={set('name')} data-testid="emp-name" />
            </Isian>
            <Isian label="Departemen"
              petunjuk={masters.loaded && !(masters.units || []).length ? 'Belum ada unit — tambahkan di menu Struktur Organisasi.' : 'Dari Struktur Organisasi.'}>
              <Sel value={form.department} onChange={changeDepartment} testId="emp-department"
                options={[{ value: '', label: '— Pilih departemen —' }, ...deptOpts]} />
            </Isian>
            <Isian label="Jabatan" petunjuk={selectedUnit ? `Jabatan di ${selectedUnit.name}.` : 'Pilih departemen dulu untuk menyaring jabatan.'}>
              <Sel value={form.job_title} onChange={set('job_title')} testId="emp-job-title"
                options={[{ value: '', label: posOpts.length ? '— Pilih jabatan —' : '— Belum ada jabatan di Struktur Organisasi —' }, ...posOpts]} />
            </Isian>
            <Isian label="Atasan" petunjuk="Atasan yang menyetujui usulan kenaikan gaji.">
              <EmployeeSelect
                employees={employees.filter(e => e.active !== false)}
                exclude={[form.id]}
                value={form.manager_id || ''}
                onChange={set('manager_id')}
                placeholder="— Tidak ada atasan —"
                testId="emp-manager"
              />
            </Isian>
            <Isian label="Lokasi utama">
              <Sel value={form.location_id || ''} onChange={set('location_id')} testId="emp-location"
                options={[{ value: '', label: '— Pilih —' }, ...locations.filter(l => l.active !== false).map(l => ({ value: l.id, label: `${l.code} · ${l.name}` }))]} />
            </Isian>
            <Isian label="Shift utama" petunjuk="Dipakai absensi bila tidak ada jadwal atau penugasan shift.">
              <Sel value={form.shift_id || ''} onChange={set('shift_id')} testId="emp-shift"
                options={[{ value: '', label: '— Tanpa shift tetap —' },
                  ...activeShifts.map(s => ({ value: s.id, label: shiftLabel(s) })),
                  ...(form.shift_id && !activeShifts.some(s => s.id === form.shift_id) ? [{ value: form.shift_id, label: `${form.shift_code || 'Shift'} (nonaktif)` }] : [])]} />
            </Isian>
            <Isian label="No. telepon" htmlFor="emp-phone">
              <Input id="emp-phone" value={form.phone} onChange={set('phone')} placeholder="08xxxxxxxxxx" />
            </Isian>
            <Isian label="Email" htmlFor="emp-email">
              <Input id="emp-email" type="email" value={form.email} onChange={set('email')} placeholder="nama@contoh.com" />
            </Isian>
          </div>
        </TabsContent>

        {/* Tab 2: Kontrak & masa kerja (dulu satu tab dengan data dasar — terlalu panjang, tombol simpan jauh di bawah) */}
        <TabsContent value="kontrak" className="mt-4">
          <div className="grid grid-cols-1 items-start gap-4 sm:grid-cols-2">
            <Isian label="Tipe kontrak">
              <Sel value={form.contract_type || ''} onChange={set('contract_type')} options={CONTRACT_TYPES} testId="emp-contract-type" />
            </Isian>
            <Isian label="Mulai kontrak">
              <DatePicker value={ymdOf(form.contract_start_date)} onChange={set('contract_start_date')} testId="emp-contract-start" />
            </Isian>
            <Isian label="Berakhir kontrak" petunjuk="Wajib untuk PKWT dan magang.">
              <DatePicker value={ymdOf(form.contract_end_date)} onChange={set('contract_end_date')}
                min={ymdOf(form.contract_start_date) || undefined} testId="emp-contract-end" />
            </Isian>
            <Isian label="Tanggal masuk kerja" petunjuk="Dipakai penggajian untuk gaji prorata di bulan pertama.">
              <DatePicker value={ymdOf(form.join_date)} onChange={set('join_date')} testId="emp-join-date" />
            </Isian>
            <Isian label="Tanggal keluar" petunjuk="Diisi saat karyawan berhenti — gaji bulan terakhir prorata.">
              <DatePicker value={ymdOf(form.resign_date)} onChange={set('resign_date')}
                min={ymdOf(form.join_date) || undefined} placeholder="Belum keluar" testId="emp-resign-date" />
            </Isian>
            <Isian label="Gaji" petunjuk="Diatur di Penggajian › Profil Gaji (satu sumber gaji).">
              <div className="flex h-9 items-center text-sm text-muted-foreground" data-testid="emp-salary-readonly">
                {salaryProfile
                  ? `${PAY_SCHEME_LABEL[salaryProfile.pay_scheme] || 'Skema lain'} · Rp ${Number(salaryProfile.base_rate || 0).toLocaleString('id-ID')}`
                  : (isEdit && salaryProfile === false ? 'Belum ada Profil Gaji' : '—')}
              </div>
            </Isian>
          </div>
        </TabsContent>

        {/* Tab 2: Pribadi */}
        <TabsContent value="personal" className="mt-4 space-y-4">
          <div className="grid grid-cols-1 items-start gap-4 sm:grid-cols-[7rem_1fr]">
            <div className="space-y-2">
              {form.photo_url ? (
                <img src={withFileAuth(`${API}${form.photo_url}`)} alt={form.name}
                  className="h-28 w-28 rounded-lg border border-[var(--glass-border)] object-cover" />
              ) : (
                <div className="flex h-28 w-28 flex-col items-center justify-center rounded-lg border border-dashed border-[var(--glass-border)] text-muted-foreground">
                  <Camera className="mb-1 h-6 w-6" />
                  <span className="text-xs">Foto</span>
                </div>
              )}
              <input ref={photoInput} type="file" accept="image/*" className="hidden" onChange={onPhotoChange} disabled={!isEdit} />
              <Button size="sm" variant="outline" type="button" className="w-28" disabled={!isEdit}
                title={isEdit ? undefined : 'Simpan karyawan dulu, lalu unggah foto'}
                onClick={() => photoInput.current?.click()}>
                <UploadCloud />{form.photo_url ? 'Ganti foto' : 'Unggah foto'}
              </Button>
              {!isEdit && <p className="w-28 text-xs text-muted-foreground">Simpan dulu untuk mengunggah.</p>}
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Isian label="Jenis kelamin">
                <Sel value={form.gender} onChange={set('gender')} options={[{ value: 'L', label: 'Laki-laki' }, { value: 'P', label: 'Perempuan' }]} />
              </Isian>
              <Isian label="Status pernikahan">
                <Sel value={form.marital_status} onChange={set('marital_status')} options={MARITAL_STATUS} />
              </Isian>
              <Isian label="Tempat lahir" htmlFor="emp-birth-place">
                <Input id="emp-birth-place" value={form.birth_place} onChange={set('birth_place')} placeholder="Kota kelahiran" />
              </Isian>
              <Isian label="Tanggal lahir">
                <DatePicker value={ymdOf(form.birth_date)} onChange={set('birth_date')} testId="emp-birth-date" />
              </Isian>
              <Isian label="Agama">
                <Sel value={form.religion} onChange={set('religion')} options={RELIGIONS.map(r => ({ value: r, label: r }))} />
              </Isian>
              <Isian label="Kewarganegaraan" htmlFor="emp-nationality">
                <Input id="emp-nationality" value={form.nationality} onChange={set('nationality')} />
              </Isian>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <Isian label="Alamat KTP" htmlFor="emp-ktp-address">
              <Textarea id="emp-ktp-address" value={form.ktp_address} onChange={set('ktp_address')} rows={2}
                placeholder="Sesuai KTP (RT/RW, kelurahan, kecamatan, kota)" />
            </Isian>
            <Isian label="Alamat tinggal saat ini" htmlFor="emp-current-address">
              <Textarea id="emp-current-address" value={form.current_address} onChange={set('current_address')} rows={2}
                placeholder="Alamat domisili sekarang" />
            </Isian>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Isian label="Pendidikan terakhir">
              <Sel value={form.education_level} onChange={set('education_level')} options={EDUCATION_LEVELS.map(e => ({ value: e, label: e }))} />
            </Isian>
            <Isian label="Sekolah / universitas" htmlFor="emp-edu-inst">
              <Input id="emp-edu-inst" value={form.education_institution} onChange={set('education_institution')} placeholder="Nama institusi" />
            </Isian>
            <Isian label="Jurusan" htmlFor="emp-edu-major">
              <Input id="emp-edu-major" value={form.education_major} onChange={set('education_major')} placeholder="Jurusan / program" />
            </Isian>
          </div>
        </TabsContent>

        {/* Tab 3: Pajak & BPJS */}
        <TabsContent value="pajak" className="mt-4 space-y-4">
          <Notice tone="warning" title="Dipakai untuk menghitung PPh 21 dan BPJS di penggajian.">
            Pastikan nomor dan status pajak sesuai dokumen.
          </Notice>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Isian label="NIK KTP (16 digit)" wajib htmlFor="emp-ktp"
              galat={form.ktp_number && form.ktp_number.length !== 16 ? `NIK harus tepat 16 digit (${form.ktp_number.length}/16).` : undefined}
              petunjuk="Nomor Induk Kependudukan — wajib untuk BPJS dan pajak.">
              <Input id="emp-ktp" value={form.ktp_number} onChange={set('ktp_number')}
                maxLength={16} placeholder="3310xxxxxxxxxxxx" inputMode="numeric" />
            </Isian>
            <Isian label="NPWP (15 atau 16 digit)" htmlFor="emp-npwp" petunjuk="Sejak 2024 NIK 16 digit berlaku sebagai NPWP.">
              <Input id="emp-npwp" value={form.npwp_number} onChange={set('npwp_number')} placeholder="xx.xxx.xxx.x-xxx.xxx" />
            </Isian>
            <Isian label="Status PTKP" petunjuk="Menentukan penghasilan tidak kena pajak untuk PPh 21.">
              <Sel value={form.tax_ptkp} onChange={set('tax_ptkp')} options={TAX_PTKP} />
            </Isian>
            <div className="hidden sm:block" />
            <Isian label="No. BPJS Kesehatan" htmlFor="emp-bpjs-kes">
              <Input id="emp-bpjs-kes" value={form.bpjs_kesehatan_number} onChange={set('bpjs_kesehatan_number')} placeholder="13 digit" />
            </Isian>
            <Isian label="No. BPJS Ketenagakerjaan" htmlFor="emp-bpjs-tk">
              <Input id="emp-bpjs-tk" value={form.bpjs_ketenagakerjaan_number} onChange={set('bpjs_ketenagakerjaan_number')} placeholder="11 digit" />
            </Isian>
            {/* 2026-11-02 (K23): kepesertaan per program — potongan payroll HANYA untuk program yang dicentang.
                Belum pernah dicentang → diturunkan dari nomor kartu (Kes ← no. Kes; JHT/JP/JKK-JKM ← no. TK). */}
            <Isian label="Kepesertaan BPJS" className="sm:col-span-2"
              petunjuk={!form.bpjs_programs
                ? 'Belum diatur — sementara mengikuti nomor kartu di atas. Centang atau hapus centang untuk menetapkan.'
                : 'Potongan dan iuran hanya dihitung untuk program yang dicentang.'}>
              <div className="flex flex-wrap gap-4" data-testid="emp-bpjs-programs">
                {BPJS_PROGRAMS.map(([k, label]) => {
                  const progs = bpjsProgramsOf(form);
                  return (
                    <label key={k} className="flex cursor-pointer items-center gap-2 text-sm text-foreground">
                      <Checkbox checked={!!progs[k]} data-testid={`emp-bpjs-${k}`}
                        onCheckedChange={() => setForm(f => ({ ...f, bpjs_programs: { ...bpjsProgramsOf(f), [k]: !bpjsProgramsOf(f)[k] } }))} />
                      {label}
                    </label>
                  );
                })}
              </div>
            </Isian>
          </div>
        </TabsContent>

        {/* Tab 4: Rekening & kontak darurat */}
        <TabsContent value="bank" className="mt-4 space-y-4">
          <p className="text-base font-semibold text-foreground">Rekening bank (untuk transfer gaji)</p>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Isian label="Nama bank">
              <Sel value={bankOther ? BANK_OTHER : (form.bank_name || '')} testId="emp-bank"
                onChange={v => {
                  if (v === BANK_OTHER) { setBankOther(true); setForm(f => ({ ...f, bank_name: BANKS.includes(f.bank_name) ? '' : f.bank_name })); }
                  else { setBankOther(false); setForm(f => ({ ...f, bank_name: v })); }
                }}
                options={[{ value: '', label: '— Pilih bank —' }, ...BANKS.map(b => ({ value: b, label: b })), { value: BANK_OTHER, label: 'Bank lain (ketik nama)' }]} />
              {bankOther && (
                <Input className="mt-2" value={form.bank_name || ''} onChange={set('bank_name')} placeholder="Nama bank" data-testid="emp-bank-other" />
              )}
            </Isian>
            <Isian label="No. rekening" htmlFor="emp-bank-no">
              <Input id="emp-bank-no" value={form.bank_account_number} onChange={set('bank_account_number')} placeholder="xxxxxxxxxx" />
            </Isian>
            <Isian label="Atas nama" htmlFor="emp-bank-holder" petunjuk="Biasanya sama dengan nama karyawan.">
              <Input id="emp-bank-holder" value={form.bank_account_holder || form.name} onChange={set('bank_account_holder')} />
            </Isian>
          </div>

          <p className="text-base font-semibold text-foreground">Kontak darurat</p>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Isian label="Nama kontak darurat" htmlFor="emp-em-name">
              <Input id="emp-em-name" value={form.emergency_contact_name} onChange={set('emergency_contact_name')} placeholder="Nama keluarga" />
            </Isian>
            <Isian label="No. HP kontak darurat" htmlFor="emp-em-phone">
              <Input id="emp-em-phone" value={form.emergency_phone} onChange={set('emergency_phone')} placeholder="08xxxxxxxxxx" />
            </Isian>
            <Isian label="Hubungan">
              <Sel value={form.emergency_relation} onChange={set('emergency_relation')} options={RELATIONS.map(r => ({ value: r, label: r }))} />
            </Isian>
          </div>
        </TabsContent>

        {/* Tab 5: Dokumen */}
        <TabsContent value="dokumen" className="mt-4 space-y-4">
          <Notice tone="info" icon={FileText}>
            Unggah dokumen karyawan seperti KTP, NPWP, ijazah, kontrak kerja, atau sertifikat. Maksimal 10 MB per berkas.
          </Notice>
          <div className="flex flex-wrap items-end gap-2">
            <Isian label="Kategori dokumen" className="w-full sm:w-64">
              <SmartNativeSelect value={docCategory} onChange={(e) => setDocCategory(e.target.value)} className="w-full"
                data-testid="emp-doc-category">
                {DOC_CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
              </SmartNativeSelect>
            </Isian>
            <input ref={docInput} type="file" className="hidden" onChange={(e) => onDocUpload(e, docCategory)} />
            <Button type="button" variant="outline" onClick={() => docInput.current?.click()} data-testid="emp-doc-upload">
              <UploadCloud />Pilih berkas & unggah
            </Button>
          </div>

          {documents.length === 0 ? (
            <EmptyState title="Belum ada dokumen" description="Pilih kategori, lalu unggah berkasnya." className="py-6" />
          ) : (
            <div className="space-y-2">
              <div className="flex justify-end">
                <TombolUnduh namaBerkas={`dokumen-${form.employee_code || 'karyawan'}`} namaLembar="Dokumen" baris={documents}
                  kolom={[
                    { label: 'Nama berkas', nilai: (d) => d.original_filename },
                    { label: 'Kategori', nilai: (d) => d.category || '' },
                    { label: 'Ukuran (KB)', nilai: (d) => (d.size ? Number((d.size / 1024).toFixed(1)) : '') },
                    { label: 'Diunggah', nilai: (d) => tgl(d.created_at) },
                  ]} testId="emp-doc-unduh" />
              </div>
              <TabelData kolom={kolomDok} baris={documents} testId="emp-doc-table" />
            </div>
          )}
        </TabsContent>
      </Tabs>
    </FormPopup>
  );
}

// 2026-11-07 (Tahap 5): dulu Select Radix dengan nilai kosong diganti '_' → memilih "— Tidak ada atasan —" mengirim
// manager_id '_' (ditolak server) dan lokasi '_' tersimpan. Kini SmartNativeSelect (nilai kosong tetap kosong, bisa dicari).
function Sel({ value, onChange, options, testId }) {
  return (
    <SmartNativeSelect value={value || ''} onChange={e => onChange(e.target.value)} data-testid={testId} className="w-full">
      {options.map(o => <option key={o.value || '_kosong'} value={o.value}>{o.label}</option>)}
    </SmartNativeSelect>
  );
}

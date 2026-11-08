/**
 * HRAdminModule — Portal SDM › Pengaturan SDM: golongan gaji, pengunduran diri, lokasi kantor untuk absen,
 * dan data contoh.
 *
 * Standar UI/UX v2 (keputusan owner 8 Nov 2026): cetakan PageLayout (tab di baris penyaring, satu tombol utama
 * per tab), tabel = TabelData + unduh Excel/CSV, form = FormPopup (lokasi kantor dulu form di halaman → kini
 * ringkasan + tombol Ubah), proses pengunduran diri = popup dengan daftar periksa berbahasa Indonesia
 * (dulu kunci program seperti "asset returned"), konfirmasi lewat confirmDialog (dulu window.confirm).
 * Data yang dikirim ke server tidak berubah.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import axios from 'axios';
import { Plus, Pencil, Power, MoreHorizontal, MapPin, FileText, RefreshCw, Sparkles, AlertTriangle } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';
import { GlassCard } from '@/components/ui/glass';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { formatTanggalID } from '@/components/ui/date-picker';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatRupiah } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;
const fmtIDR = formatRupiah;
const tgl = (v) => (v ? formatTanggalID(String(v).slice(0, 10)) : '');

const CLEARANCE = [
  ['asset_returned', 'Aset perusahaan sudah dikembalikan'],
  ['final_payslip_issued', 'Slip gaji terakhir sudah diterbitkan'],
  ['bpjs_transferred', 'Kepesertaan BPJS sudah diurus'],
  ['handover_done', 'Serah terima pekerjaan selesai'],
  ['account_disabled', 'Akun login sudah dinonaktifkan'],
  ['id_card_returned', 'Kartu identitas karyawan sudah dikembalikan'],
];
const STATUS_KELUAR = {
  resigned: { label: 'Sudah keluar', tone: 'danger' },
  resigning: { label: 'Dalam proses', tone: 'warning' },
};
const statusKeluar = (s) => STATUS_KELUAR[s] || { label: 'Dalam proses', tone: 'warning' };

export default function HRAdminModule({ token }) {
  const [tab, setTab] = useState('grades');
  const [aksi, setAksi] = useState({});   // aksi & alat milik tab aktif (diisi tab lewat `pasang`)
  const pasang = useCallback((key, isi) => setAksi((a) => ({ ...a, [key]: isi })), []);
  const cur = aksi[tab] || {};

  return (
    <Tabs value={tab} onValueChange={setTab}>
      <PageLayout testId="hr-admin-page" title="Pengaturan SDM"
        subtitle="Golongan gaji, pengunduran diri, lokasi kantor untuk absen, dan data contoh."
        actions={<>{cur.alat}{cur.utama}</>}
        filters={
          <TabsList className="h-auto max-w-full justify-start max-sm:flex-nowrap max-sm:overflow-x-auto">
            <TabsTrigger value="grades" className="shrink-0" data-testid="hr-admin-tab-grades">Golongan gaji</TabsTrigger>
            <TabsTrigger value="resignations" className="shrink-0" data-testid="hr-admin-tab-resign">Pengunduran diri</TabsTrigger>
            <TabsTrigger value="office" className="shrink-0" data-testid="hr-admin-tab-office">Lokasi kantor</TabsTrigger>
            <TabsTrigger value="seed" className="shrink-0" data-testid="hr-admin-tab-seed">Data contoh</TabsTrigger>
          </TabsList>
        }>
        <TabsContent value="grades" className="mt-0 space-y-4"><SalaryGradesTab token={token} pasang={pasang} /></TabsContent>
        <TabsContent value="resignations" className="mt-0 space-y-4"><ResignationsTab token={token} pasang={pasang} /></TabsContent>
        <TabsContent value="office" className="mt-0 space-y-4"><OfficeLocationTab token={token} pasang={pasang} /></TabsContent>
        <TabsContent value="seed" className="mt-0 space-y-4"><SeedTab token={token} /></TabsContent>
      </PageLayout>
    </Tabs>
  );
}

function MuatUlang({ onClick, loading }) {
  return (
    <Button variant="outline" size="icon" onClick={onClick} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
      <RefreshCw className={loading ? 'animate-spin' : ''} />
    </Button>
  );
}

// ════════════════════════════════════════════════════════════════════════
function SalaryGradesTab({ token, pasang }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);
  const [grades, setGrades] = useState([]);
  const [audit, setAudit] = useState({ violations: [], total_graded: 0 });
  const [editing, setEditing] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [r1, r2] = await Promise.all([
        axios.get(`${API}/api/rahaza/salary-grades`, { headers }),
        axios.get(`${API}/api/rahaza/salary-grades/audit`, { headers }).catch(() => ({ data: {} })),
      ]);
      setGrades(r1.data.grades || []);
      setAudit(r2.data || {});
    } catch { toast.error('Gagal memuat golongan gaji'); } finally { setLoading(false); }
  }, [headers]);

  useEffect(() => { load(); }, [load]);

  const save = async (form) => {
    if (form.id) {
      await axios.put(`${API}/api/rahaza/salary-grades/${form.id}`, form, { headers });
    } else {
      await axios.post(`${API}/api/rahaza/salary-grades`, form, { headers });
    }
    toast.success('Golongan gaji tersimpan');
    setEditing(null); load();
  };

  const del = async (g) => {
    if (!(await confirmDialog({ title: `Nonaktifkan golongan ${g.grade_code}?`, body: 'Golongan tidak bisa dipilih lagi untuk jabatan.', confirmLabel: 'Nonaktifkan', danger: true }))) return;
    try {
      await axios.delete(`${API}/api/rahaza/salary-grades/${g.id}`, { headers });
      toast.success('Golongan dinonaktifkan'); load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Gagal menonaktifkan golongan'); }
  };

  const kolomUnduh = [
    { label: 'Kode', nilai: (g) => g.grade_code },
    { label: 'Nama', nilai: (g) => g.grade_name },
    { label: 'Tingkat', nilai: (g) => Number(g.level ?? 0) },
    { label: 'Gaji minimum', nilai: (g) => Number(g.min_salary || 0) },
    { label: 'Gaji tengah', nilai: (g) => Number(g.mid_salary || 0) },
    { label: 'Gaji maksimum', nilai: (g) => Number(g.max_salary || 0) },
    { label: 'Keterangan', nilai: (g) => g.description || '' },
  ];

  useEffect(() => {
    pasang('grades', {
      alat: <><MuatUlang onClick={load} loading={loading} />
        <TombolUnduh namaBerkas="golongan-gaji" namaLembar="Golongan gaji" baris={grades} kolom={kolomUnduh} testId="grade-unduh" /></>,
      utama: <Button onClick={() => setEditing({})} data-testid="grade-add"><Plus />Tambah golongan</Button>,
    });
  }, [grades, loading]); // eslint-disable-line react-hooks/exhaustive-deps

  const { page, setPage, totalPages, total, paged } = useClientPagination(grades, 10);
  const pelanggaran = audit.violations || [];

  const kolom = [
    { kunci: 'kode', label: 'Kode', isi: (g) => <span className="font-medium text-foreground">{g.grade_code}</span> },
    { kunci: 'nama', label: 'Nama golongan', hp: 'judul', isi: (g) => g.grade_name },
    { kunci: 'tingkat', label: 'Tingkat', rata: 'kanan', isi: (g) => <span className="tabular-nums">{g.level ?? '—'}</span> },
    { kunci: 'min', label: 'Gaji minimum', rata: 'kanan', isi: (g) => <span className="tabular-nums">{fmtIDR(g.min_salary)}</span> },
    { kunci: 'mid', label: 'Gaji tengah', rata: 'kanan', isi: (g) => <span className="tabular-nums">{fmtIDR(g.mid_salary)}</span> },
    { kunci: 'max', label: 'Gaji maksimum', rata: 'kanan', isi: (g) => <span className="tabular-nums">{fmtIDR(g.max_salary)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (g) => (
      <div className="flex items-center justify-end gap-1">
        <Button size="sm" variant="outline" onClick={() => setEditing(g)}><Pencil />Ubah</Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="icon-sm" variant="ghost" aria-label="Lainnya" title="Lainnya"><MoreHorizontal /></Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => del(g)} className="text-[hsl(var(--danger-text))]"><Power className="mr-2 h-4 w-4" />Nonaktifkan</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>) },
  ];

  const kolomLanggar = [
    { kunci: 'nama', label: 'Karyawan', hp: 'judul', isi: (v) => `${v.name} (${v.employee_code})` },
    { kunci: 'gol', label: 'Golongan', isi: (v) => v.grade },
    { kunci: 'gaji', label: 'Gaji pokok', rata: 'kanan', isi: (v) => <span className="tabular-nums">{fmtIDR(v.base_rate)}</span> },
    { kunci: 'rentang', label: 'Rentang golongan', isi: (v) => `${fmtIDR(v.grade_min)} – ${fmtIDR(v.grade_max)}` },
    { kunci: 'status', label: 'Keadaan', isi: (v) => <StatusBadge status={v.status} label={v.status === 'below' ? 'Di bawah rentang' : 'Di atas rentang'} tone={v.status === 'below' ? 'warning' : 'danger'} /> },
  ];

  return (
    <>
      <p className="text-sm text-muted-foreground" data-testid="grade-summary">
        <span className="font-medium text-foreground">{audit.total_graded || 0}</span> karyawan sudah punya golongan
        {' · '}<span className="font-medium text-foreground">{pelanggaran.length}</span> di luar rentang gaji golongannya.
        {' '}Golongan dipakai di Struktur Organisasi › Jabatan.
      </p>
      {loading && grades.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat golongan gaji…</p>
      ) : (
        <TabelData kolom={kolom} baris={paged} testId="grade-table" onKlikBaris={setEditing}
          kosong={<EmptyState title="Belum ada golongan gaji" description="Tambahkan golongan pertama, lalu pilih golongan untuk tiap jabatan."
            action={<Button onClick={() => setEditing({})}><Plus />Tambah golongan</Button>} />} />
      )}
      {grades.length > 0 && <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />}

      {pelanggaran.length > 0 && (
        <div className="space-y-2">
          <Notice tone="warning" icon={AlertTriangle} title={`${pelanggaran.length} karyawan bergaji di luar rentang golongannya`}
            action={<TombolUnduh namaBerkas="gaji-di-luar-rentang" namaLembar="Di luar rentang" baris={pelanggaran} testId="grade-violation-unduh"
              kolom={[
                { label: 'Karyawan', nilai: (v) => v.name }, { label: 'Kode', nilai: (v) => v.employee_code },
                { label: 'Golongan', nilai: (v) => v.grade }, { label: 'Gaji pokok', nilai: (v) => Number(v.base_rate || 0) },
                { label: 'Rentang minimum', nilai: (v) => Number(v.grade_min || 0) }, { label: 'Rentang maksimum', nilai: (v) => Number(v.grade_max || 0) },
                { label: 'Keadaan', nilai: (v) => (v.status === 'below' ? 'Di bawah rentang' : 'Di atas rentang') },
              ]} />}>
            Sesuaikan lewat Penggajian › Penyesuaian atau ubah rentang golongan.
          </Notice>
          <TabelData kolom={kolomLanggar} baris={pelanggaran} kunci={(v) => `${v.employee_code}-${v.grade}`} testId="grade-violation-table" />
        </div>
      )}

      <GradeDialog open={editing !== null} initial={editing || {}} onSave={save} onClose={() => setEditing(null)} />
    </>
  );
}

function GradeDialog({ open, initial, onSave, onClose }) {
  const kosong = { grade_code: '', grade_name: '', level: 1, min_salary: 0, mid_salary: 0, max_salary: 0, department: '', description: '', is_active: true };
  const [form, setForm] = useState({ ...kosong, ...initial });
  const [saving, setSaving] = useState(false);
  const [galat, setGalat] = useState('');
  useEffect(() => { if (open) { setForm({ ...kosong, ...initial }); setGalat(''); } }, [open, initial]); // eslint-disable-line react-hooks/exhaustive-deps

  const simpan = async () => {
    setSaving(true); setGalat('');
    try { await onSave(form); } catch (e) { setGalat(e.response?.data?.detail || 'Gagal menyimpan golongan'); } finally { setSaving(false); }
  };

  return (
    <FormPopup open={open} onClose={onClose} ukuran="pendek" testId="grade-form"
      judul={form.id ? `Ubah golongan ${form.grade_code}` : 'Tambah golongan gaji'}
      keterangan="Rentang gaji dipakai untuk memeriksa gaji pokok karyawan per golongan."
      onSimpan={simpan} menyimpan={saving} galat={galat} bisaSimpan={!!form.grade_code && !!form.grade_name}>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Isian label="Kode" wajib htmlFor="grade-code">
          <Input id="grade-code" value={form.grade_code} onChange={e => setForm(f => ({ ...f, grade_code: e.target.value.toUpperCase() }))} placeholder="G1" />
        </Isian>
        <Isian label="Tingkat" wajib htmlFor="grade-level">
          <Input id="grade-level" type="number" min={1} value={form.level} onChange={e => setForm(f => ({ ...f, level: +e.target.value }))} />
        </Isian>
      </div>
      <Isian label="Nama golongan" wajib htmlFor="grade-name">
        <Input id="grade-name" value={form.grade_name} onChange={e => setForm(f => ({ ...f, grade_name: e.target.value }))} placeholder="Tingkat 1 — Staf" />
      </Isian>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Isian label="Gaji minimum (Rp)"><MoneyInput value={form.min_salary} onChange={e => setForm(f => ({ ...f, min_salary: +e.target.value }))} /></Isian>
        <Isian label="Gaji tengah (Rp)"><MoneyInput value={form.mid_salary} onChange={e => setForm(f => ({ ...f, mid_salary: +e.target.value }))} /></Isian>
        <Isian label="Gaji maksimum (Rp)"><MoneyInput value={form.max_salary} onChange={e => setForm(f => ({ ...f, max_salary: +e.target.value }))} /></Isian>
      </div>
      <Isian label="Keterangan" htmlFor="grade-desc">
        <Textarea id="grade-desc" rows={2} value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} />
      </Isian>
    </FormPopup>
  );
}

// ════════════════════════════════════════════════════════════════════════
function ResignationsTab({ token, pasang }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/api/rahaza/resignation/list`, { headers });
      setItems(r.data.items || []);
    } catch { toast.error('Gagal memuat daftar pengunduran diri'); } finally { setLoading(false); }
  }, [headers]);

  useEffect(() => { load(); }, [load]);

  const kolomUnduh = [
    { label: 'Karyawan', nilai: (i) => i.name }, { label: 'Kode', nilai: (i) => i.employee_code },
    { label: 'Departemen', nilai: (i) => i.department || '' }, { label: 'Status', nilai: (i) => statusKeluar(i.employee_status).label },
    { label: 'Tanggal keluar', nilai: (i) => tgl(i.resignation_date) }, { label: 'Alasan', nilai: (i) => i.reason_for_leaving || '' },
  ];
  useEffect(() => {
    pasang('resignations', {
      alat: <><MuatUlang onClick={load} loading={loading} />
        <TombolUnduh namaBerkas="pengunduran-diri" namaLembar="Pengunduran diri" baris={items} kolom={kolomUnduh} testId="resign-unduh" /></>,
    });
  }, [items, loading]); // eslint-disable-line react-hooks/exhaustive-deps

  const kolom = [
    { kunci: 'nama', label: 'Karyawan', hp: 'judul', isi: (i) => (
      <div><p className="font-medium text-foreground">{i.name}</p><p className="text-xs text-muted-foreground">{i.employee_code}</p></div>) },
    { kunci: 'dept', label: 'Departemen', isi: (i) => i.department || '—' },
    { kunci: 'status', label: 'Status', isi: (i) => { const s = statusKeluar(i.employee_status); return <StatusBadge status={i.employee_status} label={s.label} tone={s.tone} />; } },
    { kunci: 'tgl', label: 'Tanggal keluar', isi: (i) => tgl(i.resignation_date) || '—' },
    { kunci: 'alasan', label: 'Alasan', isi: (i) => <span className="block truncate md:max-w-xs" title={i.reason_for_leaving}>{i.reason_for_leaving || '—'}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (i) => (
      <Button size="sm" variant="outline" onClick={() => setEditing(i)}><FileText />Proses</Button>) },
  ];

  return (
    <>
      <p className="text-sm text-muted-foreground">
        <span className="font-medium text-foreground">{items.length}</span> karyawan sedang atau sudah mengundurkan diri.
        {' '}Pengajuan baru masuk lewat Portal Saya dan Kotak Persetujuan SDM.
      </p>
      {loading && items.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat…</p>
      ) : (
        <TabelData kolom={kolom} baris={items} testId="resign-table" onKlikBaris={setEditing}
          kosong={<EmptyState title="Tidak ada pengunduran diri" description="Pengunduran diri yang sedang diproses atau sudah selesai muncul di sini." />} />
      )}
      {editing && <ResignationProcessDialog emp={editing} headers={headers} onReload={load} onClose={() => setEditing(null)} />}
    </>
  );
}

function ResignationProcessDialog({ emp, headers, onReload, onClose }) {
  const [tab, setTab] = useState('clearance');
  const [clearance, setClearance] = useState(emp.clearance || {});
  const [interview, setInterview] = useState({ nps_score: 0, notes: '', positive_feedback: '', improvement_areas: '', would_recommend: false });
  const [menyimpan, setMenyimpan] = useState(false);
  const st = statusKeluar(emp.employee_status);

  const saveClearance = async () => {
    setMenyimpan(true);
    try {
      await axios.put(`${API}/api/rahaza/resignation/clearance/${emp.id}`, clearance, { headers });
      toast.success('Daftar periksa disimpan'); onReload();
    } catch { toast.error('Gagal menyimpan daftar periksa'); } finally { setMenyimpan(false); }
  };
  const saveInterview = async () => {
    setMenyimpan(true);
    try {
      await axios.post(`${API}/api/rahaza/resignation/exit-interview/${emp.id}`, interview, { headers });
      toast.success('Wawancara keluar disimpan'); onReload();
    } catch { toast.error('Gagal menyimpan wawancara keluar'); } finally { setMenyimpan(false); }
  };
  const accept = async () => {
    if (!(await confirmDialog({ title: `Terima pengunduran diri ${emp.name}?`, body: 'Karyawan akan dinonaktifkan.', confirmLabel: 'Terima', danger: true }))) return;
    try {
      await axios.post(`${API}/api/rahaza/resignation/accept/${emp.id}`, { rehire_eligible: true }, { headers });
      toast.success('Pengunduran diri diterima'); onReload(); onClose();
    } catch { toast.error('Gagal menerima pengunduran diri'); }
  };

  return (
    <DetailPopup open onClose={onClose} testId="resign-process"
      judul={`Proses pengunduran diri — ${emp.name}`}
      keterangan={[emp.employee_code, emp.department].filter(Boolean).join(' · ')}
      status={<StatusBadge status={emp.employee_status} label={st.label} tone={st.tone} />}
      aksi={emp.employee_status !== 'resigned' && (
        <Button size="sm" variant="destructive" onClick={accept}>Terima pengunduran diri</Button>
      )}>
      <dl className="divide-y divide-[var(--glass-border)]">
        <BarisDetail label="Tanggal keluar">{tgl(emp.resignation_date) || '—'}</BarisDetail>
        <BarisDetail label="Alasan">{emp.reason_for_leaving || '—'}</BarisDetail>
      </dl>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="h-auto max-w-full justify-start">
          <TabsTrigger value="clearance">Daftar periksa keluar</TabsTrigger>
          <TabsTrigger value="interview">Wawancara keluar</TabsTrigger>
        </TabsList>
        <TabsContent value="clearance" className="mt-4 space-y-3">
          <div className="space-y-2">
            {CLEARANCE.map(([k, label]) => (
              <label key={k} className="flex cursor-pointer items-center gap-2 text-sm text-foreground">
                <Checkbox checked={!!clearance[k]} onCheckedChange={v => setClearance(c => ({ ...c, [k]: !!v }))} />
                {label}
              </label>
            ))}
          </div>
          <Isian label="Catatan" htmlFor="clr-notes">
            <Textarea id="clr-notes" placeholder="Catatan tambahan" value={clearance.notes || ''} onChange={e => setClearance(c => ({ ...c, notes: e.target.value }))} rows={2} />
          </Isian>
          <div className="flex justify-end">
            <Button variant="success" onClick={saveClearance} disabled={menyimpan}>Simpan daftar periksa</Button>
          </div>
        </TabsContent>
        <TabsContent value="interview" className="mt-4 space-y-3">
          <Isian label="Skor rekomendasi (0–10)" htmlFor="exit-nps" petunjuk="Seberapa besar karyawan akan merekomendasikan bekerja di sini.">
            <Input id="exit-nps" type="number" min={0} max={10} value={interview.nps_score} onChange={e => setInterview(i => ({ ...i, nps_score: +e.target.value }))} className="w-32" />
          </Isian>
          <Isian label="Pengalaman positif" htmlFor="exit-pos"><Textarea id="exit-pos" rows={2} value={interview.positive_feedback} onChange={e => setInterview(i => ({ ...i, positive_feedback: e.target.value }))} /></Isian>
          <Isian label="Hal yang bisa diperbaiki" htmlFor="exit-imp"><Textarea id="exit-imp" rows={2} value={interview.improvement_areas} onChange={e => setInterview(i => ({ ...i, improvement_areas: e.target.value }))} /></Isian>
          <Isian label="Catatan SDM" htmlFor="exit-notes"><Textarea id="exit-notes" rows={2} value={interview.notes} onChange={e => setInterview(i => ({ ...i, notes: e.target.value }))} /></Isian>
          <label className="flex cursor-pointer items-center gap-2 text-sm text-foreground">
            <Checkbox checked={interview.would_recommend} onCheckedChange={v => setInterview(i => ({ ...i, would_recommend: !!v }))} />
            Bersedia merekomendasikan perusahaan ke kerabat
          </label>
          <div className="flex justify-end">
            <Button variant="success" onClick={saveInterview} disabled={menyimpan}>Simpan wawancara keluar</Button>
          </div>
        </TabsContent>
      </Tabs>
    </DetailPopup>
  );
}

// ════════════════════════════════════════════════════════════════════════
function OfficeLocationTab({ token, pasang }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);
  const [office, setOffice] = useState({ name: 'Kantor Utama', lat: '', lng: '', address: '', geofence_radius_m: 300 });
  const [draft, setDraft] = useState(null);   // null = popup tertutup
  const [menyimpan, setMenyimpan] = useState(false);

  useEffect(() => {
    axios.get(`${API}/api/rahaza/attendance/office-location`, { headers })
      .then(r => setOffice(o => ({ ...o, ...r.data }))).catch(() => toast.error('Gagal memuat lokasi kantor'));
  }, [headers]);

  useEffect(() => {
    pasang('office', { utama: <Button onClick={() => setDraft({ ...office })} data-testid="office-edit"><Pencil />Ubah lokasi</Button> });
  }, [office]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    setMenyimpan(true);
    try {
      await axios.put(`${API}/api/rahaza/attendance/office-location`, draft, { headers });
      setOffice(draft);
      setDraft(null);
      toast.success('Lokasi kantor disimpan');
    } catch { toast.error('Gagal menyimpan lokasi kantor'); } finally { setMenyimpan(false); }
  };

  const useCurrent = () => {
    if (!navigator.geolocation) { toast.error('Peramban tidak mendukung pembacaan lokasi'); return; }
    navigator.geolocation.getCurrentPosition(
      p => { setDraft(o => ({ ...o, lat: p.coords.latitude, lng: p.coords.longitude })); toast.success('Koordinat lokasi saat ini dipakai'); },
      () => toast.error('Gagal membaca lokasi')
    );
  };

  const adaKoordinat = office.lat !== null && office.lat !== '' && office.lat !== undefined
    && office.lng !== null && office.lng !== '' && office.lng !== undefined;

  return (
    <>
      <GlassCard hover={false} className="p-4" data-testid="office-summary">
        <p className="mb-1 text-base font-semibold text-foreground">Lokasi kantor untuk absen</p>
        <p className="mb-3 text-sm text-muted-foreground">Absen yang dicatat di luar radius ditandai "di luar jangkauan".</p>
        <dl className="divide-y divide-[var(--glass-border)]">
          <BarisDetail label="Nama kantor">{office.name || '—'}</BarisDetail>
          <BarisDetail label="Alamat">{office.address || '—'}</BarisDetail>
          <BarisDetail label="Koordinat">{adaKoordinat ? `${office.lat}, ${office.lng}` : 'Belum diatur'}</BarisDetail>
          <BarisDetail label="Radius">{office.geofence_radius_m || 300} meter</BarisDetail>
        </dl>
      </GlassCard>

      {draft && (
        <FormPopup open onClose={() => setDraft(null)} ukuran="pendek" testId="office-form"
          judul="Ubah lokasi kantor" keterangan="Dipakai untuk memeriksa lokasi saat karyawan absen lewat HP."
          onSimpan={save} menyimpan={menyimpan}
          aksiKiri={<Button type="button" variant="outline" onClick={useCurrent}><MapPin />Pakai lokasi saat ini</Button>}>
          <Isian label="Nama kantor" htmlFor="office-name">
            <Input id="office-name" value={draft.name} onChange={e => setDraft(o => ({ ...o, name: e.target.value }))} />
          </Isian>
          <Isian label="Alamat" htmlFor="office-address">
            <Input id="office-address" value={draft.address || ''} onChange={e => setDraft(o => ({ ...o, address: e.target.value }))} placeholder="Bandung, Jawa Barat" />
          </Isian>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Isian label="Lintang" htmlFor="office-lat">
              <Input id="office-lat" type="number" step="0.0001" value={draft.lat ?? ''} onChange={e => setDraft(o => ({ ...o, lat: e.target.value }))} placeholder="-6.9147" />
            </Isian>
            <Isian label="Bujur" htmlFor="office-lng">
              <Input id="office-lng" type="number" step="0.0001" value={draft.lng ?? ''} onChange={e => setDraft(o => ({ ...o, lng: e.target.value }))} placeholder="107.6098" />
            </Isian>
            <Isian label="Radius (meter)" htmlFor="office-radius">
              <Input id="office-radius" type="number" value={draft.geofence_radius_m || 300} onChange={e => setDraft(o => ({ ...o, geofence_radius_m: +e.target.value }))} />
            </Isian>
          </div>
        </FormPopup>
      )}
    </>
  );
}

// ════════════════════════════════════════════════════════════════════════
function SeedTab({ token }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);

  const run = async (force) => {
    if (force && !(await confirmDialog({
      title: 'Isi ulang paksa data contoh?',
      body: 'Golongan gaji, jenis cuti, daftar tugas orientasi, dan kursus pelatihan yang sudah ada akan DITIMPA.',
      confirmLabel: 'Timpa data', danger: true,
    }))) return;
    setRunning(true);
    try {
      const { data } = await axios.post(`${API}/api/rahaza/hr-seed/run`, { force }, { headers });
      setResult(data.summary);
      toast.success('Data contoh diisi');
    } catch (e) { toast.error(e.response?.data?.detail || 'Gagal mengisi data contoh'); }
    setRunning(false);
  };

  return (
    <>
      <GlassCard hover={false} className="space-y-3 p-4">
        <div>
          <p className="text-base font-semibold text-foreground">Data contoh SDM</p>
          <p className="text-sm text-muted-foreground">
            Membuat 12 karyawan aktif, 7 golongan gaji, 5 jenis cuti, 3 kursus pelatihan, dan 1 daftar tugas orientasi
            karyawan baru. Data yang sudah ada dilewati, kecuali memakai isi ulang paksa.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => run(false)} disabled={running} data-testid="seed-run">
            <Sparkles />{running ? 'Mengisi…' : 'Isi data contoh'}
          </Button>
          <Button variant="destructive" onClick={() => run(true)} disabled={running}>
            <RefreshCw />Isi ulang paksa
          </Button>
        </div>
      </GlassCard>
      {result && (
        <Notice tone="success" title="Data contoh selesai diisi">
          <ul className="list-disc space-y-0.5 pl-5">
            <li>Karyawan: {result.employees?.created ?? 0} baru, {result.employees?.skipped ?? 0} sudah ada</li>
            <li>Golongan gaji: {result.grades?.created ?? 0} baru, {result.grades?.skipped ?? 0} sudah ada</li>
            <li>Jenis cuti: {result.leave_types?.created ?? 0} baru</li>
            <li>Daftar tugas orientasi: {result.onboarding_template === 'created' ? 'dibuat' : result.onboarding_template === 'skipped' ? 'sudah ada' : '—'}</li>
            <li>Kursus pelatihan: {result.courses?.created ?? 0} baru</li>
          </ul>
        </Notice>
      )}
    </>
  );
}

/**
 * RahazaOvertimeModule — pengajuan lembur (Portal SDM › Cuti & Lembur › Lembur, juga menu lama `hr-overtime`).
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout (dulu kepala buatan sendiri "Request Lembur (Overtime)"),
 * tab status Radix → pil penyaring, tabel standar + unduh Excel/CSV, form = FormPopup, tanggal = DatePicker,
 * tolak = konfirmasi merah dengan alasan wajib (sama seperti dulu). Panggilan API tidak berubah.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import axios from 'axios';
import { Check, Clock, MoreHorizontal, Plus, RefreshCw, X, XCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker, { formatTanggalID } from '@/components/ui/date-picker';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { toast } from 'sonner';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { todayWIB } from '@/lib/waktu';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatusBadge } from './moduleAtoms';
import { EmployeeSelect } from './hr/hrPickers';

const API = process.env.REACT_APP_BACKEND_URL;

const STATUS_CFG = {
  pending:   { label: 'Menunggu',   tone: 'warning' },
  approved:  { label: 'Disetujui',  tone: 'success' },
  rejected:  { label: 'Ditolak',    tone: 'danger' },
  cancelled: { label: 'Dibatalkan', tone: 'muted' },
};
const statusCfg = (s) => STATUS_CFG[s] || STATUS_CFG.pending;

export default function RahazaOvertimeModule({ token, user }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);
  const [items, setItems] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [tab, setTab] = useState('pending');
  const [loading, setLoading] = useState(false);
  const [dialog, setDialog] = useState(null);

  const isApprover = ['superadmin', 'admin', 'owner', 'hr', 'manager'].includes(user?.role);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const statusParam = tab === 'all' ? '' : `?status=${tab}`;
      const [r1, r2] = await Promise.all([
        axios.get(`${API}/api/rahaza/overtime${statusParam}`, { headers }),
        isApprover
          ? axios.get(`${API}/api/rahaza/employees?active_only=true&limit=500`, { headers }).catch(() => ({ data: [] }))
          : Promise.resolve({ data: [] }),
      ]);
      setItems(r1.data.overtime || []);
      setEmployees(Array.isArray(r2.data) ? r2.data : (r2.data.items || r2.data.rows || []));
    } finally { setLoading(false); }
  }, [headers, tab, isApprover]);

  useEffect(() => { load(); }, [load]);

  const handleSave = async (form) => {
    try {
      await axios.post(`${API}/api/rahaza/overtime`, form, { headers });
      toast.success('Pengajuan lembur terkirim, menunggu persetujuan');
      setDialog(null);
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Gagal mengirim'); }
  };

  const handleApprove = async (id) => {
    try {
      await axios.put(`${API}/api/rahaza/overtime/${id}/approve`, {}, { headers });
      toast.success('Lembur disetujui');
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Gagal menyetujui'); }
  };

  const handleReject = async (id, reason) => {
    try {
      await axios.put(`${API}/api/rahaza/overtime/${id}/reject`, { reason }, { headers });
      toast.success('Lembur ditolak');
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Gagal menolak'); }
  };

  const tolak = async (it) => {
    const reason = await confirmDialog({
      title: 'Tolak pengajuan lembur?',
      body: `${it.employee?.name || ''} · ${formatTanggalID(it.date)} · ${it.hours} jam · ${it.reason || ''}`,
      confirmLabel: 'Tolak', danger: true,
      input: { label: 'Alasan penolakan', placeholder: 'Contoh: produksi sudah selesai di jam reguler' },
    });
    if (!reason) return;
    handleReject(it.id, reason);
  };

  const handleCancel = async (id) => {
    if (!(await confirmDialog({ title: 'Batalkan pengajuan lembur ini?', confirmLabel: 'Batalkan pengajuan', cancelLabel: 'Kembali', danger: true }))) return;
    try {
      await axios.delete(`${API}/api/rahaza/overtime/${id}`, { headers });
      toast.success('Pengajuan dibatalkan');
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Gagal membatalkan'); }
  };

  const { page, setPage, totalPages, total, paged } = useClientPagination(items, 10);

  const kolom = [
    { kunci: 'karyawan', label: 'Karyawan', hp: 'judul', isi: (it) => (
      <div className="min-w-0">
        <p className="font-medium text-foreground">{it.employee?.name || '—'}</p>
        <p className="text-xs text-muted-foreground">{it.employee?.employee_code}</p>
      </div>) },
    { kunci: 'tanggal', label: 'Tanggal', isi: (it) => <span className="whitespace-nowrap">{formatTanggalID(it.date) || it.date}</span> },
    { kunci: 'jam', label: 'Jam', isi: (it) => <span className="whitespace-nowrap tabular-nums">{it.start_time} – {it.end_time}</span> },
    { kunci: 'durasi', label: 'Durasi', rata: 'kanan', isi: (it) => (
      <span className="whitespace-nowrap tabular-nums">
        {it.hours} jam{it.rate_multiplier !== 1 && it.rate_multiplier != null && <span className="text-muted-foreground"> ×{it.rate_multiplier}</span>}
      </span>) },
    { kunci: 'alasan', label: 'Alasan', isi: (it) => <span className="block max-w-[18rem] truncate" title={it.reason || ''}>{it.reason || '—'}</span> },
    { kunci: 'status', label: 'Status', isi: (it) => (
      <div>
        <StatusBadge status={it.status} label={statusCfg(it.status).label} tone={statusCfg(it.status).tone} />
        {it.status === 'rejected' && it.rejected_reason && (
          <p className="mt-0.5 text-xs text-[hsl(var(--danger-text))]">{it.rejected_reason}</p>
        )}
      </div>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (it) => (it.status !== 'pending' ? null : (
      <div className="flex items-center justify-end gap-1">
        {isApprover ? (<>
          <Button size="sm" variant="success" onClick={() => handleApprove(it.id)} data-testid={`overtime-approve-${it.id}`}>
            <Check />Setujui
          </Button>
          <Button size="sm" variant="destructive" onClick={() => tolak(it)} data-testid={`overtime-reject-${it.id}`}>
            <X />Tolak
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="icon-sm" variant="ghost" aria-label="Lainnya" title="Lainnya"><MoreHorizontal /></Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => handleCancel(it.id)}>
                <XCircle className="mr-2 h-4 w-4" />Batalkan pengajuan
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </>) : (
          <Button size="sm" variant="outline" onClick={() => handleCancel(it.id)}>
            <XCircle />Batalkan
          </Button>
        )}
      </div>)) },
  ];

  return (
    <PageLayout testId="overtime-page" title="Pengajuan lembur"
      subtitle={isApprover
        ? 'Kelola pengajuan lembur karyawan. Hanya lembur yang disetujui masuk ke penggajian.'
        : 'Ajukan lembur lalu tunggu persetujuan atasan.'}
      actions={<Button onClick={() => setDialog({})} data-testid="overtime-create"><Plus />Ajukan lembur</Button>}
      filters={<>
        <FilterChips hideWhenEmpty={false} value={tab} onChange={setTab} testId="overtime-status" ariaLabel="Status"
          options={[
            { key: 'pending', label: 'Menunggu' },
            { key: 'approved', label: 'Disetujui' },
            { key: 'rejected', label: 'Ditolak' },
            { key: 'cancelled', label: 'Dibatalkan' },
            { key: 'all', label: 'Semua' },
          ]} />
        {/* Unduh & muat ulang di ujung kanan; di HP turun ke baris sendiri (tidak menimpa penyaring) */}
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <TombolUnduh namaBerkas={`lembur-${tab}`} namaLembar="Lembur" baris={items} testId="overtime-unduh"
            kolom={[
              { label: 'Kode karyawan', nilai: (it) => it.employee?.employee_code || '' },
              { label: 'Nama karyawan', nilai: (it) => it.employee?.name || '' },
              { label: 'Tanggal', nilai: (it) => formatTanggalID(it.date) || it.date },
              { label: 'Mulai', nilai: (it) => it.start_time },
              { label: 'Selesai', nilai: (it) => it.end_time },
              { label: 'Durasi (jam)', nilai: (it) => Number(it.hours) || 0 },
              { label: 'Pengali', nilai: (it) => (it.rate_multiplier != null ? Number(it.rate_multiplier) : '') },
              { label: 'Alasan', nilai: (it) => it.reason || '' },
              { label: 'Status', nilai: (it) => statusCfg(it.status).label },
              { label: 'Alasan ditolak', nilai: (it) => it.rejected_reason || '' },
            ]} />
          <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang" data-testid="overtime-refresh">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
        </div>
      </>}
      footer={items.length > 0 && <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />}>
      {loading && items.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat pengajuan lembur…</p>
      ) : (
        <TabelData kolom={kolom} baris={paged} testId="overtime-table"
          kosong={<EmptyState icon={Clock} title="Tidak ada pengajuan lembur"
            description={tab === 'all' ? 'Pengajuan lembur karyawan akan tampil di sini.' : 'Tidak ada pengajuan dengan status ini. Pilih status lain.'} />} />
      )}

      {dialog && (
        <OvertimeDialog
          employees={employees}
          isApprover={isApprover}
          currentUser={user}
          onSave={handleSave}
          onClose={() => setDialog(null)}
        />
      )}
    </PageLayout>
  );
}

function OvertimeDialog({ employees, isApprover, currentUser, onSave, onClose }) {
  const [form, setForm] = useState({
    employee_id: currentUser?.employee_id || '',
    date: todayWIB(),
    start_time: '17:00',
    end_time: '19:00',
    reason: '',
  });
  const [saving, setSaving] = useState(false);

  const hours = useMemo(() => {
    try {
      const [h1, m1] = form.start_time.split(':').map(Number);
      const [h2, m2] = form.end_time.split(':').map(Number);
      const s = h1 * 60 + m1;
      let e = h2 * 60 + m2;
      if (e < s) e += 24 * 60;
      return ((e - s) / 60).toFixed(2);
    } catch { return 0; }
  }, [form.start_time, form.end_time]);

  const submit = async () => {
    if (isApprover && !form.employee_id) { toast.error('Pilih karyawan'); return; }
    if (!form.date) { toast.error('Pilih tanggal'); return; }
    if (!(Number(hours) > 0)) { toast.error('Isi jam mulai dan selesai'); return; }
    if (!form.reason?.trim()) { toast.error('Alasan wajib diisi'); return; }
    setSaving(true);
    await onSave({ ...form, hours: parseFloat(hours) });
    setSaving(false);
  };

  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="overtime-form" judul="Ajukan lembur"
      keterangan="Pengali upah lembur mengikuti Pengaturan gaji." onSimpan={submit} menyimpan={saving}
      labelSimpan="Ajukan">
      <div className="grid gap-4 sm:grid-cols-2">
        {isApprover && (
          <Isian label="Karyawan" wajib>
            {/* Tahap 5 (2026-11-07): dulu Select tanpa kotak cari & hanya 100 karyawan pertama */}
            <EmployeeSelect employees={employees} value={form.employee_id}
              onChange={v => setForm(f => ({ ...f, employee_id: v }))} testId="overtime-employee" />
          </Isian>
        )}
        <Isian label="Tanggal" wajib>
          <DatePicker value={form.date} onChange={v => setForm(f => ({ ...f, date: v }))} bolehKosong={false} testId="overtime-date" />
        </Isian>
      </div>
      {/* Jam: belum ada pemilih jam bersama — isian jam bawaan peramban dipertahankan */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Isian label="Mulai" htmlFor="ot-start">
          <Input id="ot-start" type="time" value={form.start_time} onChange={e => setForm(f => ({ ...f, start_time: e.target.value }))} />
        </Isian>
        <Isian label="Selesai" htmlFor="ot-end">
          <Input id="ot-end" type="time" value={form.end_time} onChange={e => setForm(f => ({ ...f, end_time: e.target.value }))} />
        </Isian>
        <Isian label="Durasi" className="col-span-2 sm:col-span-1">
          <p className="flex h-9 items-center text-sm tabular-nums">{hours} jam</p>
        </Isian>
      </div>
      <Isian label="Alasan" wajib htmlFor="ot-reason">
        <Textarea id="ot-reason" value={form.reason} rows={3} data-testid="overtime-reason"
          onChange={e => setForm(f => ({ ...f, reason: e.target.value }))}
          placeholder="Contoh: menyelesaikan batch produksi mendesak untuk klien A" />
      </Isian>
    </FormPopup>
  );
}

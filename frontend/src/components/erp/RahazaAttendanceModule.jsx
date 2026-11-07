/**
 * RahazaAttendanceModule — Absensi harian (tab hub Absensi): isian cepat kehadiran semua karyawan aktif.
 *
 * Standar UI/UX v2 (8 Nov 2026): pemilih tanggal seragam (DatePicker, dulu isian tanggal bawaan peramban),
 * deret "set cepat" berwarna → menu "Isi semua", tabel standar + unduh Excel/CSV, kartu angka 4 buah.
 * Kartu angka kini dihitung dari absen yang SUDAH TERSIMPAN (dulu dari isian layar: karyawan tanpa catatan
 * tampil "Hadir" karena isian bawaannya Hadir — 24 "Hadir" padahal belum ada satu pun absen tercatat).
 * Logika simpan (hanya kolom yang diubah HR, validasi Hadir, Tandai hadir & simpan) tidak berubah.
 */
import { Fragment, useState, useEffect, useCallback } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import {
  Save, RefreshCw, Clock as ClockIcon, ChevronLeft, ChevronRight, Copy, CheckCircle2, Lock, ListChecks,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import DatePicker, { formatTanggalID } from '@/components/ui/date-picker';
import TombolUnduh from '@/components/ui/tombol-unduh';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';
import PageLayout, { RowDetail, RowToggle } from './layout/PageLayout';
import { toast } from 'sonner';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { todayWIB, addDaysISO, parseServerTime } from '@/lib/waktu';

const STATUS_OPTS = [
  { code: 'hadir', label: 'Hadir' },
  { code: 'izin',  label: 'Izin' },
  { code: 'sakit', label: 'Sakit' },
  // Tahap 2: status kontrak payroll 'alpa' (data lama 'alfa' ditampilkan sebagai Alpa)
  { code: 'alpa',  label: 'Alpa' },
  { code: 'cuti',  label: 'Cuti' },
  { code: 'libur', label: 'Libur' },
];
const LABEL_STATUS = Object.fromEntries(STATUS_OPTS.map((s) => [s.code, s.label]));

const normRow = (row) => ({ ...row, status: row.status === 'alfa' ? 'alpa' : row.status });
const AUDIT_SOURCE = {
  grid: 'Grid HR', manual: 'Input HR', persetujuan_selfie: 'Pemeriksaan selfie', lembur_dibayar: 'Tanda lembur',
  koreksi: 'Koreksi absen', cuti: 'Cuti disetujui', batal_cuti: 'Cuti dibatalkan', impor_mesin: 'Mesin sidik jari',
};
const AUDIT_FIELD = {
  status: 'Status', clock_in: 'Masuk', clock_out: 'Pulang', hours_worked: 'Jam kerja', overtime_hours: 'Lembur',
  overtime_paid: 'Lembur dibayar', shift_id: 'Shift', notes: 'Catatan', late_minutes: 'Terlambat',
  leave_request_id: 'Pengajuan cuti', half_day: 'Setengah hari', paid_leave: 'Cuti dibayar', approval_status: 'Pemeriksaan',
};
const auditVal = (k, v) => {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'boolean') return v ? 'ya' : 'tidak';
  if ((k === 'clock_in' || k === 'clock_out') && typeof v === 'string') {
    // jam server tanpa zona = UTC (parseServerTime); dulu dibaca sebagai jam lokal → mundur 7 jam di WIB
    try { return parseServerTime(v).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Jakarta' }); } catch { return v; }
  }
  if (k === 'leave_request_id') return 'ada';
  return String(v);
};
const jam = (n) => (Math.round((Number(n) || 0) * 10) / 10).toLocaleString('id-ID');

export default function RahazaAttendanceModule({ token }) {
  const today = todayWIB();
  const [date, setDate] = useState(today);
  const [rows, setRows] = useState([]);
  // Nilai grid seperti dimuat dari server — dasar "kolom apa yang diubah HR" saat menyimpan.
  const [savedRows, setSavedRows] = useState({});
  const [shifts, setShifts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [copying, setCopying] = useState(false);
  // Tahap 2: jejak perubahan per baris (siapa, kapan, sebelum → sesudah)
  const [auditOpen, setAuditOpen] = useState(null);
  const [auditRows, setAuditRows] = useState([]);

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchGrid = useCallback(async (d = date) => {
    setLoading(true);
    try {
      const r = await fetch(`/api/rahaza/attendance/grid?date=${d}`, { headers });
      if (r.ok) {
        const data = await r.json();
        const loaded = (data.rows || []).map(normRow);
        setRows(loaded);
        setSavedRows(Object.fromEntries(loaded.map(row => [row.employee_id, row])));
        setShifts(data.shifts || []);
      }
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [date, token]);

  useEffect(() => { fetchGrid(); }, [fetchGrid]);

  const changeDate = (newDate) => {
    if (!newDate) return;            // DatePicker "Kosongkan" tidak berlaku: absensi selalu per tanggal
    setDate(newDate);
  };

  const DEFAULT_HOURS = 8;
  // Tahap 5 (2026-11-07): shift bawaan = shift karyawan pada tanggal itu (jadwal → penugasan → shift karyawan,
  // dihitung server `default_shift_id`); baru jatuh ke shift pertama bila tidak diketahui. Dulu SELALU shift pertama.
  const defaultShiftId = (r) => {
    const own = r?.default_shift_id;
    if (own && shifts.some(s => String(s.id) === String(own))) return own;
    return shifts[0]?.id || '';
  };

  const update = (empId, patch) => setRows(prev => prev.map(r => {
    if (r.employee_id !== empId) return r;
    const next = { ...r, ...patch };
    if ('status' in patch) {
      if (patch.status === 'hadir') {
        if (!next.shift_id) next.shift_id = defaultShiftId(r);
        if (!(Number(next.hours_worked) > 0)) next.hours_worked = DEFAULT_HOURS;
      } else {
        // Tidak bekerja → kosongkan jam, lembur, dan shift
        next.hours_worked = 0;
        next.overtime_hours = 0;
        next.shift_id = '';
      }
    }
    return next;
  }));

  const setAll = (status) => setRows(prev => prev.map(r => (
    status === 'hadir'
      ? { ...r, status, shift_id: r.shift_id || defaultShiftId(r), hours_worked: Number(r.hours_worked) > 0 ? r.hours_worked : DEFAULT_HOURS }
      : { ...r, status, hours_worked: 0, overtime_hours: 0, shift_id: '' }
  )));

  /* Salin Kemarin — load yesterday's grid and pre-populate today's */
  const salinKemarin = async () => {
    const yesterday = addDaysISO(date, -1);
    setCopying(true);
    try {
      const r = await fetch(`/api/rahaza/attendance/grid?date=${yesterday}`, { headers });
      if (!r.ok) { toast.error('Gagal memuat absensi kemarin.'); return; }
      const data = await r.json();
      const yesterdayMap = {};
      (data.rows || []).forEach(row => { yesterdayMap[row.employee_id] = row; });
      setRows(prev => prev.map(row => {
        const y = yesterdayMap[row.employee_id];
        if (!y) return row;
        if (row.locked) return row;
        return { ...row, status: normRow(y).status || 'hadir', shift_id: y.shift_id || '', hours_worked: y.hours_worked || 0, overtime_hours: y.overtime_hours || 0 };
      }));
      const copied = Object.keys(yesterdayMap).length;
      toast.success(`${copied} absensi dari ${formatTanggalID(yesterday)} disalin sebagai contoh. Simpan untuk mengonfirmasi.`);
    } finally { setCopying(false); }
  };

  const saveAll = async (rowsArg) => {
    // Tombol "Simpan semua" memanggil saveAll(event) — hanya array yang dianggap daftar baris.
    const rowsToSave = Array.isArray(rowsArg) ? rowsArg : rows;
    // Baris yang SUDAH tercatat (absen selfie/mesin, cuti, alfa) hanya mengirim kolom yang diubah HR,
    // supaya jam masuk/pulang dan menit terlambatnya tidak ikut tertimpa. Baris baru dikirim lengkap.
    const entries = [];
    const toValidate = [];
    rowsToSave.forEach(r => {
      const full = {
        status: r.status || 'hadir',
        shift_id: r.shift_id || null,
        hours_worked: Number(r.hours_worked) || 0,
        overtime_hours: Number(r.overtime_hours) || 0,
        notes: r.notes || '',
      };
      const saved = r.existing_id ? savedRows[r.employee_id] : null;
      if (!saved) {
        entries.push({ employee_id: r.employee_id, ...full });
        toValidate.push(r);
        return;
      }
      const before = {
        status: saved.status || 'hadir',
        shift_id: saved.shift_id || null,
        hours_worked: Number(saved.hours_worked) || 0,
        overtime_hours: Number(saved.overtime_hours) || 0,
        notes: saved.notes || '',
      };
      const changed = Object.keys(full).filter(k => full[k] !== before[k]);
      if (changed.length === 0) return;
      entries.push({ employee_id: r.employee_id, ...Object.fromEntries(changed.map(k => [k, full[k]])) });
      if (changed.some(k => ['status', 'shift_id', 'hours_worked'].includes(k))) toValidate.push(r);
    });
    // Validasi: status Hadir wajib punya Shift + Jam Kerja > 0
    const invalid = toValidate.filter(r => (r.status || 'hadir') === 'hadir' && (!r.shift_id || !(Number(r.hours_worked) > 0)));
    if (invalid.length > 0) {
      toast.error(`${invalid.length} karyawan berstatus "Hadir" belum lengkap shift/jam kerjanya. Lengkapi dulu atau pakai tombol "Tandai hadir & simpan".`);
      return;
    }
    if (entries.length === 0) {
      toast.info('Tidak ada perubahan untuk disimpan.');
      return;
    }
    setSaving(true);
    try {
      const res = await fetch('/api/rahaza/attendance/bulk', {
        method: 'POST', headers, body: JSON.stringify({ date, entries }),
      });
      if (res.ok) {
        toast.success(`Absensi ${formatTanggalID(date)} disimpan (${entries.length} karyawan).`);
        fetchGrid();
      } else {
        const err = await res.json().catch(() => ({}));
        toast.error(err.detail || 'Gagal menyimpan absensi.');
      }
    } finally { setSaving(false); }
  };

  /* Isi Hadir (auto-isi shift + jam) lalu simpan — HANYA untuk karyawan yang belum punya catatan hari itu.
     Catatan yang sudah ada (cuti, izin, sakit, alfa, absen selfie/mesin) dan status lain yang dipilih HR
     di baris baru tidak ditimpa. */
  const markAllHadirAndSave = () => {
    const filled = rows.map(r => ((r.existing_id || (r.status || 'hadir') !== 'hadir') ? r : {
      ...r, status: 'hadir',
      shift_id: r.shift_id || defaultShiftId(r),
      hours_worked: Number(r.hours_worked) > 0 ? r.hours_worked : DEFAULT_HOURS,
    }));
    setRows(filled);
    saveAll(filled);
  };

  /* Tahap 2 (2026-11-06): lembur tanpa pengajuan disetujui tidak otomatis dibayar — HR menandainya di sini. */
  const markOvertimePaid = async (r, paid) => {
    const res = await fetch(`/api/rahaza/attendance/events/${r.existing_id}/overtime-paid`, {
      method: 'POST', headers, body: JSON.stringify({ paid }),
    });
    if (res.ok) {
      toast.success(paid ? 'Lembur ditandai dibayar.' : 'Lembur ditandai tidak dibayar.');
      fetchGrid();
    } else {
      const err = await res.json().catch(() => ({}));
      toast.error(err.detail || 'Gagal menandai lembur.');
    }
  };

  const toggleAudit = async (r) => {
    if (auditOpen === r.employee_id) { setAuditOpen(null); return; }
    setAuditOpen(r.employee_id);
    setAuditRows([]);
    const res = await fetch(`/api/rahaza/attendance/audit?employee_id=${r.employee_id}&date=${date}`, { headers });
    if (res.ok) setAuditRows((await res.json()).items || []);
  };

  // Kartu angka = absen yang SUDAH TERSIMPAN di server untuk tanggal ini (bukan isian layar yang belum disimpan).
  const tersimpan = Object.values(savedRows).filter((r) => r.existing_id);
  const hitungSimpan = tersimpan.reduce((a, r) => { a[r.status] = (a[r.status] || 0) + 1; return a; }, {});
  const tidakHadir = tersimpan.length - (hitungSimpan.hadir || 0);
  const rincianTidakHadir = STATUS_OPTS.filter((s) => s.code !== 'hadir' && hitungSimpan[s.code])
    .map((s) => `${s.label} ${hitungSimpan[s.code]}`).join(' · ');
  const jamSimpan = tersimpan.reduce((s, r) => s + (Number(r.hours_worked) || 0), 0);
  const lemburSimpan = tersimpan.reduce((s, r) => s + (Number(r.overtime_hours) || 0), 0);
  const lockedCount = rows.filter(r => r.locked).length;
  const isToday = date === today;
  const shiftLabel = (id) => {
    const s = shifts.find((x) => String(x.id) === String(id));
    return s ? `${s.code} · ${s.name}` : '';
  };

  const { page, setPage, totalPages, total, paged } = useClientPagination(rows, 10);
  return (
    <PageLayout
        testId="rahaza-attendance-page"
        headerTestId="attendance-header"
        title="Absensi harian"
        subtitle="Isian cepat kehadiran semua karyawan aktif. Perubahan HR tercatat di riwayat tiap baris."
        actions={<>
          <Button variant="success" onClick={saveAll} disabled={saving || rows.length === 0} data-testid="attendance-save">
            {saving ? <><RefreshCw className="animate-spin" />Menyimpan…</> : <><Save />Simpan semua</>}
          </Button>
        </>}
        filters={<>
          <div className="flex items-center gap-1">
            <Button variant="outline" size="icon" onClick={() => changeDate(addDaysISO(date, -1))}
              title="Hari sebelumnya" aria-label="Hari sebelumnya" data-testid="att-prev-day">
              <ChevronLeft />
            </Button>
            <div className="w-44">
              <DatePicker value={date} onChange={changeDate} max={today} bolehKosong={false} testId="att-date" />
            </div>
            <Button variant="outline" size="icon" onClick={() => changeDate(addDaysISO(date, 1))} disabled={date >= today}
              title="Hari berikutnya" aria-label="Hari berikutnya" data-testid="att-next-day">
              <ChevronRight />
            </Button>
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" disabled={rows.length === 0 || loading} data-testid="att-setall">
                <ListChecks />Isi cepat
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">Isi status semua baris (belum disimpan)</DropdownMenuLabel>
              {STATUS_OPTS.map(s => (
                <DropdownMenuItem key={s.code} onSelect={() => setAll(s.code)} data-testid={`att-setall-${s.code}`}>
                  Semua {s.label.toLowerCase()}
                </DropdownMenuItem>
              ))}
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={salinKemarin} disabled={copying || loading} data-testid="att-copy-yesterday">
                <Copy className="mr-2 h-4 w-4" />{copying ? 'Menyalin…' : 'Salin dari kemarin'}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <Button variant="outline" onClick={markAllHadirAndSave} disabled={saving || rows.length === 0}
            data-testid="att-setall-hadir-save"
            title="Isi Hadir (shift otomatis + 8 jam) untuk karyawan yang belum tercatat, lalu simpan. Cuti, izin, sakit, alpa, dan absen selfie tidak ditimpa.">
            <CheckCircle2 />Tandai hadir & simpan
          </Button>
          {/* Unduh & muat ulang di ujung kanan baris yang sama; di HP turun ke baris sendiri (tidak menimpa tanggal) */}
          <div className="ml-auto flex shrink-0 items-center gap-2">
            <TombolUnduh namaBerkas={`absensi-harian-${date}`} namaLembar="Absensi harian" baris={rows} testId="att-unduh"
              kolom={[
                { label: 'Tanggal', nilai: () => formatTanggalID(date) },
                { label: 'Kode karyawan', nilai: (r) => r.employee_code },
                { label: 'Nama karyawan', nilai: (r) => r.employee_name },
                { label: 'Status', nilai: (r) => LABEL_STATUS[r.status || 'hadir'] || r.status },
                { label: 'Tercatat', nilai: (r) => (r.existing_id ? 'Sudah' : 'Belum') },
                { label: 'Shift', nilai: (r) => shiftLabel(r.shift_id) },
                { label: 'Jam kerja', nilai: (r) => Number(r.hours_worked) || 0 },
                { label: 'Lembur (jam)', nilai: (r) => Number(r.overtime_hours) || 0 },
                { label: 'Catatan', nilai: (r) => r.notes || '' },
                { label: 'Terkunci gaji final', nilai: (r) => (r.locked ? 'Ya' : '') },
              ]} />
            <Button variant="outline" size="icon" onClick={() => fetchGrid()} title="Muat ulang" aria-label="Muat ulang" data-testid="att-refresh">
              <RefreshCw className={loading ? 'animate-spin' : ''} />
            </Button>
          </div>
        </>}
        summary={<>
          {/* Tanggal lampau: perubahan menimpa data yang ada */}
          {!isToday && (
            <Notice tone="warning" testId="att-history-note"
              action={<Button size="sm" variant="outline" onClick={() => changeDate(today)}>Kembali ke hari ini</Button>}>
              Menampilkan absensi {formatTanggalID(date)}. Perubahan akan menimpa data yang sudah ada.
            </Notice>
          )}
          {/* Tahap 2: tanggal yang sudah masuk gaji final tidak bisa diubah */}
          {lockedCount > 0 && (
            <p className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="att-locked-note">
              <Lock className="h-4 w-4" />
              {lockedCount} karyawan sudah masuk penggajian final untuk tanggal ini — barisnya dikunci. Koreksi lewat pengajuan koreksi absen.
            </p>
          )}
          {/* Ringkasan = absen yang SUDAH TERSIMPAN untuk tanggal ini (bukan isian layar yang belum disimpan). */}
          {rows.length > 0 && (
            <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground" data-testid="att-summary">
              <span data-testid="att-count-total"><b className="font-semibold text-foreground tabular-nums">{rows.length}</b> karyawan aktif</span>
              <span data-testid="att-count-recorded"><b className="font-semibold text-foreground tabular-nums">{tersimpan.length}</b> sudah dicatat · {rows.length - tersimpan.length} belum</span>
              <span data-testid="att-count-hadir">Hadir <b className="font-semibold text-[hsl(var(--success-text))] tabular-nums">{hitungSimpan.hadir || 0}</b></span>
              <span data-testid="att-count-absent">Tidak hadir <b className={`font-semibold tabular-nums ${hitungSimpan.alpa ? 'text-[hsl(var(--danger-text))]' : 'text-foreground'}`}>{tidakHadir}</b>{rincianTidakHadir ? ` (${rincianTidakHadir})` : ''}</span>
              {tersimpan.length > 0 && <span>{jam(jamSimpan)} jam kerja · {jam(lemburSimpan)} jam lembur tersimpan</span>}
            </p>
          )}
        </>}
        footer={rows.length > 0 && <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />}
      >
      {loading && rows.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat absensi…</p>
      ) : rows.length === 0 ? (
        <EmptyState icon={ClockIcon} title="Belum ada karyawan aktif" description="Tambahkan data karyawan terlebih dahulu untuk mengisi absensi." />
      ) : (
        <Table data-testid="att-table">
          <TableHeader>
            <TableRow>
              <TableHead>Karyawan</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Shift</TableHead>
              <TableHead className="text-right">Jam kerja</TableHead>
              <TableHead className="text-right">Lembur</TableHead>
              <TableHead>Catatan</TableHead>
              <TableHead className="text-right">Riwayat</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {paged.map(r => (
              <Fragment key={r.employee_id}>
              <TableRow data-testid={`att-row-${r.employee_code}`}>
                <TableCell className="min-w-[11rem]">
                  <p className="font-medium text-foreground">{r.employee_name}</p>
                  <p className="text-xs text-muted-foreground tabular-nums">{r.employee_code}{!r.existing_id && ' · belum dicatat'}</p>
                  {(r.locked || r.leave_request_id) && (
                    <div className="mt-0.5 flex flex-wrap gap-1">
                      {r.locked && <StatusBadge status="locked" label="Terkunci gaji final" tone="muted" testId={`att-locked-${r.employee_code}`} />}
                      {r.leave_request_id && <StatusBadge status="cuti" label={r.half_day ? 'Cuti ½ hari disetujui' : 'Cuti disetujui'} tone="info" />}
                    </div>
                  )}
                </TableCell>
                <TableCell>
                  <SmartNativeSelect disabled={r.locked} value={r.status || 'hadir'} onChange={e => update(r.employee_id, { status: e.target.value })} searchable={false}
                    data-testid={`att-status-${r.employee_code}`} aria-label={`Status ${r.employee_name}`} className="h-8 w-28">
                    {STATUS_OPTS.map(s => <option key={s.code} value={s.code}>{s.label}</option>)}
                  </SmartNativeSelect>
                </TableCell>
                <TableCell>
                  <SmartNativeSelect disabled={r.locked} value={r.shift_id || ''} onChange={e => update(r.employee_id, { shift_id: e.target.value })}
                    data-testid={`att-shift-${r.employee_code}`} aria-label={`Shift ${r.employee_name}`} className="h-8 w-48">
                    <option value="">—</option>
                    {shifts.map(s => <option key={s.id} value={s.id}>{`${s.code} · ${s.name}${s.start_time ? ` (${s.start_time}–${s.end_time || '?'})` : ''}`}</option>)}
                  </SmartNativeSelect>
                </TableCell>
                <TableCell className="text-right">
                  <Input type="number" min={0} step="0.5" disabled={r.locked} value={r.hours_worked || 0}
                    onChange={e => update(r.employee_id, { hours_worked: e.target.value })} aria-label={`Jam kerja ${r.employee_name}`}
                    className="ml-auto h-8 w-20 text-right tabular-nums" />
                </TableCell>
                <TableCell className="text-right">
                  <Input type="number" min={0} step="0.5" disabled={r.locked} value={r.overtime_hours || 0}
                    onChange={e => update(r.employee_id, { overtime_hours: e.target.value })} aria-label={`Lembur ${r.employee_name}`}
                    className="ml-auto h-8 w-20 text-right tabular-nums" />
                  {Number(r.overtime_request_hours) > 0 ? (
                    <p className="mt-0.5 text-xs text-muted-foreground">Pengajuan disetujui {r.overtime_request_hours} jam</p>
                  ) : r.existing_id && Number(savedRows[r.employee_id]?.overtime_hours) > 0 ? (
                    <label className="mt-0.5 flex items-center justify-end gap-1.5 text-xs text-muted-foreground"
                      title="Lembur tanpa pengajuan disetujui hanya dibayar bila ditandai HR">
                      <Checkbox checked={Boolean(r.overtime_paid)} disabled={r.locked}
                        onCheckedChange={(v) => markOvertimePaid(r, v === true)} data-testid={`att-ot-paid-${r.employee_code}`} />
                      Lembur dibayar
                    </label>
                  ) : null}
                </TableCell>
                <TableCell className="min-w-[10rem]">
                  <Input disabled={r.locked} value={r.notes || ''} onChange={e => update(r.employee_id, { notes: e.target.value })}
                    placeholder="—" aria-label={`Catatan ${r.employee_name}`} className="h-8" />
                </TableCell>
                <TableCell className="text-right">
                  {r.existing_id && (
                    <RowToggle open={auditOpen === r.employee_id} onClick={() => toggleAudit(r)} label="Riwayat perubahan"
                      testId={`att-audit-toggle-${r.employee_code}`} />
                  )}
                </TableCell>
              </TableRow>
              {auditOpen === r.employee_id && (
                <RowDetail colSpan={7} testId={`att-audit-${r.employee_code}`}>
                  {auditRows.length === 0 ? (
                    <p className="text-sm text-muted-foreground">HR belum mengubah baris ini pada tanggal ini.</p>
                  ) : (
                    <ul className="space-y-1 text-sm">
                      {auditRows.map(a => (
                        <li key={a.id}>
                          <span className="font-medium">{a.changed_by_name || '-'}</span>
                          {' · '}{parseServerTime(a.changed_at)?.toLocaleString('id-ID', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Jakarta' }) || '—'}
                          {' · '}{AUDIT_SOURCE[a.source] || a.source}:{' '}
                          {Object.keys(a.after || {}).map(k => `${AUDIT_FIELD[k] || k} ${auditVal(k, (a.before || {})[k])} → ${auditVal(k, a.after[k])}`).join('; ')}
                          {a.note ? ` — ${a.note}` : ''}
                        </li>
                      ))}
                    </ul>
                  )}
                </RowDetail>
              )}
              </Fragment>
            ))}
          </TableBody>
        </Table>
      )}
    </PageLayout>
  );
}

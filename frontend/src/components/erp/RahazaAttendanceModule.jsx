import { Fragment, useState, useEffect, useCallback } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Save, RefreshCw, Clock as ClockIcon, ChevronLeft, ChevronRight, Copy, CheckCircle2, Lock } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { StatTile, EmptyState, StatusBadge } from './moduleAtoms';
import PageLayout, { RowDetail, RowToggle } from './layout/PageLayout';
import { toast } from 'sonner';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { todayWIB, addDaysISO } from '@/lib/waktu';

const STATUS_OPTS = [
  { code: 'hadir', label: 'Hadir',  color: 'text-emerald-600 dark:text-emerald-400' },
  { code: 'izin',  label: 'Izin',   color: 'text-amber-700 dark:text-amber-400' },
  { code: 'sakit', label: 'Sakit',  color: 'text-orange-600 dark:text-orange-400' },
  // Tahap 2: status kontrak payroll 'alpa' (data lama 'alfa' ditampilkan sebagai Alpa)
  { code: 'alpa',  label: 'Alpa',   color: 'text-[hsl(var(--destructive))]' },
  { code: 'cuti',  label: 'Cuti',   color: 'text-blue-600 dark:text-blue-400' },
  { code: 'libur', label: 'Libur',  color: 'text-muted-foreground' },
];

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
    try { return new Date(v).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Jakarta' }); } catch { return v; }
  }
  if (k === 'leave_request_id') return 'ada';
  return String(v);
};

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
    setDate(newDate);
  };

  const DEFAULT_HOURS = 8;
  const defaultShiftId = () => (shifts[0]?.id || '');

  const update = (empId, patch) => setRows(prev => prev.map(r => {
    if (r.employee_id !== empId) return r;
    const next = { ...r, ...patch };
    if ('status' in patch) {
      if (patch.status === 'hadir') {
        if (!next.shift_id) next.shift_id = defaultShiftId();
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
      ? { ...r, status, shift_id: r.shift_id || defaultShiftId(), hours_worked: Number(r.hours_worked) > 0 ? r.hours_worked : DEFAULT_HOURS }
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
      toast.success(`${copied} absensi dari ${yesterday} berhasil disalin sebagai template. Simpan untuk konfirmasi.`);
    } finally { setCopying(false); }
  };

  const saveAll = async (rowsArg) => {
    // Tombol "Simpan Semua" memanggil saveAll(event) — hanya array yang dianggap daftar baris.
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
      toast.error(`${invalid.length} karyawan berstatus "Hadir" belum lengkap Shift/Jam Kerja. Lengkapi dulu atau gunakan tombol "Tandai Hadir & Simpan".`);
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
        toast.success(`Absensi ${date} berhasil disimpan (${entries.length} karyawan).`);
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
      shift_id: r.shift_id || defaultShiftId(),
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

  const counts = rows.reduce((a, r) => { a[r.status] = (a[r.status] || 0) + 1; return a; }, {});
  const lockedCount = rows.filter(r => r.locked).length;
  const totalHours = rows.reduce((s, r) => s + (Number(r.hours_worked) || 0), 0);
  const totalOT = rows.reduce((s, r) => s + (Number(r.overtime_hours) || 0), 0);
  const isToday = date === today;

  const { page, setPage, totalPages, total, paged } = useClientPagination(rows, 10);
  return (
    <PageLayout
        testId="rahaza-attendance-page"
        headerTestId="attendance-header"
        title="Absensi harian"
        subtitle="Input cepat kehadiran semua pegawai aktif. Perubahan HR tercatat di riwayat tiap baris."
        actions={
          <>
            {/* ─── Navigasi Harian: ← tanggal → ─── */}
            <div className="flex items-center gap-1 border border-[var(--glass-border)] rounded-lg overflow-hidden bg-[var(--glass-bg)]">
              <button
                onClick={() => changeDate(addDaysISO(date, -1))}
                className="h-9 w-9 grid place-items-center text-foreground/60 hover:text-foreground hover:bg-[var(--glass-bg-hover)] transition-colors"
                title="Hari sebelumnya"
                data-testid="att-prev-day"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <GlassInput
                type="date"
                value={date}
                onChange={e => changeDate(e.target.value)}
                className="h-9 w-40 border-0 rounded-none bg-transparent"
                data-testid="att-date"
              />
              <button
                onClick={() => changeDate(addDaysISO(date, 1))}
                disabled={date >= today}
                className="h-9 w-9 grid place-items-center text-foreground/60 hover:text-foreground hover:bg-[var(--glass-bg-hover)] transition-colors disabled:opacity-40"
                title="Hari berikutnya"
                data-testid="att-next-day"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>

            {/* Salin Kemarin */}
            <Button
              variant="ghost"
              className="h-9 border border-[var(--glass-border)] gap-1.5"
              onClick={salinKemarin}
              disabled={copying || loading}
              title="Salin absensi dari hari sebelumnya sebagai template"
              data-testid="att-copy-yesterday"
            >
              <Copy className="w-3.5 h-3.5" />
              {copying ? 'Menyalin...' : 'Salin Kemarin'}
            </Button>

            <Button variant="outline" size="icon" onClick={() => fetchGrid()} title="Muat ulang" aria-label="Muat ulang" data-testid="att-refresh">
              <RefreshCw className="w-4 h-4" />
            </Button>
            <Button onClick={saveAll} disabled={saving || rows.length === 0} className="h-9 gap-1.5" data-testid="attendance-save">
              {saving ? <><RefreshCw className="w-3.5 h-3.5 animate-spin" />Menyimpan...</> : <><Save className="w-3.5 h-3.5" />Simpan Semua</>}
            </Button>
          </>
        }
      >

      {/* Tahap 2: tanggal yang sudah masuk gaji final tidak bisa diubah */}
      {lockedCount > 0 && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground" data-testid="att-locked-note">
          <Lock className="w-3.5 h-3.5" />
          {lockedCount} karyawan sudah masuk penggajian final untuk tanggal ini — barisnya dikunci. Koreksi lewat pengajuan koreksi absen.
        </div>
      )}

      {/* Today badge */}
      {!isToday && (
        <div className="flex items-center justify-between bg-amber-50 dark:bg-amber-400/10 border border-amber-300 dark:border-amber-400/20 rounded-lg px-4 py-2">
          <span className="text-xs text-amber-700 dark:text-amber-400">Menampilkan absensi historis untuk <strong>{date}</strong>. Perubahan akan menimpa data yang sudah ada.</span>
          <button onClick={() => changeDate(today)} className="text-xs text-amber-700 dark:text-amber-400 underline hover:no-underline">Kembali ke hari ini</button>
        </div>
      )}

      {/* Status counters */}
      <div className="grid grid-cols-3 md:grid-cols-6 gap-2">
        {STATUS_OPTS.map(s => (
          <StatTile key={s.code} label={s.label} value={counts[s.code] || 0} accent={
            s.code === 'hadir' ? 'success' : s.code === 'alpa' ? 'danger' : s.code === 'libur' ? 'muted' : 'primary'
          } testId={`att-count-${s.code}`} />
        ))}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        <StatTile label="Total Karyawan" value={rows.length} accent="primary" />
        <StatTile label="Total Jam Kerja" value={totalHours.toFixed(1)} suffix="jam" accent="default" />
        <StatTile label="Total Lembur" value={totalOT.toFixed(1)} suffix="jam" accent="warning" />
        <StatTile label="Tanggal" value={date} accent="muted" />
      </div>

      {/* Quick-set chips */}
      <GlassCard className="p-3" hover={false}>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs text-foreground/60 font-medium">Set cepat semua →</span>
          {STATUS_OPTS.map(s => (
            <button key={s.code}
              onClick={() => setAll(s.code)}
              className={`px-3 py-1 rounded-full text-[11px] font-semibold border border-[var(--glass-border)] bg-[var(--glass-bg)] hover:bg-[var(--glass-bg-hover)] ${s.color} transition-colors duration-150`}
              data-testid={`att-setall-${s.code}`}
            >{s.label}</button>
          ))}
          <div className="w-px h-4 bg-[var(--glass-border)] mx-1" />
          <button
            onClick={markAllHadirAndSave}
            className="px-3 py-1 rounded-full text-[11px] font-semibold border border-emerald-400 dark:border-emerald-400/30 bg-emerald-50 dark:bg-emerald-400/10 text-emerald-600 dark:text-emerald-400 hover:bg-emerald-50 dark:bg-emerald-400/20 transition-colors duration-150 flex items-center gap-1"
            data-testid="att-setall-hadir-save"
            title="Isi Hadir (shift otomatis + 8 jam) untuk karyawan yang belum tercatat, lalu simpan. Cuti, izin, sakit, alfa, dan absen selfie tidak ditimpa."
          >
            <CheckCircle2 className="w-3 h-3" /> Tandai Hadir & Simpan
          </button>
        </div>
      </GlassCard>

      {loading ? (
        <div className="flex items-center justify-center h-48"><div className="animate-spin rounded-full h-9 w-9 border-b-2 border-[hsl(var(--primary))]" /></div>
      ) : rows.length === 0 ? (
        <GlassCard hover={false} className="p-0"><EmptyState icon={ClockIcon} title="Belum ada karyawan aktif" description="Tambahkan master karyawan terlebih dahulu untuk input absensi." /></GlassCard>
      ) : (
        <GlassCard className="p-0 overflow-hidden" hover={false}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-[var(--glass-bg)]">
                <tr className="text-left text-[10px] uppercase tracking-wider text-foreground/50">
                  <th className="px-4 py-3">Karyawan</th>
                  <th className="px-3 py-3">Status</th>
                  <th className="px-3 py-3">Shift</th>
                  <th className="px-3 py-3 text-right">Jam Kerja</th>
                  <th className="px-3 py-3 text-right">Lembur</th>
                  <th className="px-3 py-3">Catatan</th>
                  <th className="px-3 py-3 text-right">Riwayat</th>
                </tr>
              </thead>
              <tbody>
                {paged.map(r => (
                  <Fragment key={r.employee_id}>
                  <tr className="border-t border-[var(--glass-border)] hover:bg-[var(--glass-bg-hover)] transition-colors" data-testid={`att-row-${r.employee_code}`}>
                    <td className="px-4 py-2">
                      <div className="font-mono text-xs text-foreground">{r.employee_code}</div>
                      <div className="text-xs text-foreground/60">{r.employee_name}</div>
                      <div className="flex flex-wrap gap-1 mt-0.5">
                        {r.locked && <StatusBadge status="locked" label="Terkunci gaji final" tone="muted" testId={`att-locked-${r.employee_code}`} />}
                        {r.leave_request_id && <StatusBadge status="cuti" label={r.half_day ? 'Cuti ½ hari disetujui' : 'Cuti disetujui'} tone="info" />}
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <select disabled={r.locked} value={r.status || 'hadir'} onChange={e => update(r.employee_id, { status: e.target.value })} className="h-8 px-2 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-xs text-foreground">
                        {STATUS_OPTS.map(s => <option key={s.code} value={s.code}>{s.label}</option>)}
                      </select>
                    </td>
                    <td className="px-3 py-2">
                      <SmartNativeSelect disabled={r.locked} value={r.shift_id || ''} onChange={e => update(r.employee_id, { shift_id: e.target.value })} className="h-8 px-2 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-xs text-foreground">
                        <option value="">—</option>
                        {shifts.map(s => <option key={s.id} value={s.id}>{s.code}</option>)}
                      </SmartNativeSelect>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <input type="number" min={0} step="0.5" disabled={r.locked} value={r.hours_worked || 0} onChange={e => update(r.employee_id, { hours_worked: e.target.value })} className="w-20 h-8 px-2 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-xs text-foreground text-right font-mono" />
                    </td>
                    <td className="px-3 py-2 text-right">
                      <input type="number" min={0} step="0.5" disabled={r.locked} value={r.overtime_hours || 0} onChange={e => update(r.employee_id, { overtime_hours: e.target.value })} className="w-20 h-8 px-2 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-xs text-foreground text-right font-mono" />
                      {Number(r.overtime_request_hours) > 0 ? (
                        <div className="text-[10px] text-muted-foreground mt-0.5">Pengajuan disetujui {r.overtime_request_hours} jam</div>
                      ) : r.existing_id && Number(savedRows[r.employee_id]?.overtime_hours) > 0 ? (
                        <label className="flex items-center justify-end gap-1 text-[10px] text-muted-foreground mt-0.5"
                          title="Lembur tanpa pengajuan disetujui hanya dibayar bila ditandai HR">
                          <input type="checkbox" checked={Boolean(r.overtime_paid)} disabled={r.locked}
                            onChange={e => markOvertimePaid(r, e.target.checked)} data-testid={`att-ot-paid-${r.employee_code}`} />
                          Lembur dibayar
                        </label>
                      ) : null}
                    </td>
                    <td className="px-3 py-2">
                      <input disabled={r.locked} value={r.notes || ''} onChange={e => update(r.employee_id, { notes: e.target.value })} placeholder="—" className="w-full h-8 px-2 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-xs text-foreground" />
                    </td>
                    <td className="px-3 py-2 text-right">
                      {r.existing_id && (
                        <RowToggle open={auditOpen === r.employee_id} onClick={() => toggleAudit(r)} label="Riwayat perubahan"
                          testId={`att-audit-toggle-${r.employee_code}`} />
                      )}
                    </td>
                  </tr>
                  {auditOpen === r.employee_id && (
                    <RowDetail colSpan={7} testId={`att-audit-${r.employee_code}`}>
                      {auditRows.length === 0 ? (
                        <p className="text-xs text-muted-foreground">HR belum mengubah baris ini pada tanggal ini.</p>
                      ) : (
                        <ul className="space-y-1 text-xs">
                          {auditRows.map(a => (
                            <li key={a.id}>
                              <span className="font-medium">{a.changed_by_name || '-'}</span>
                              {' · '}{new Date(a.changed_at).toLocaleString('id-ID', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Jakarta' })}
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
              </tbody>
            </table>
            <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} className="px-1" />
          </div>
        </GlassCard>
      )}
    </PageLayout>
  );
}

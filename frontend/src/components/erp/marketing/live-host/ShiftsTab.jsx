/**
 * Shift host live (Live Selling › Host live › Shift).
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, penyaring satu baris (periode = PeriodPicker, dulu dua input tanggal),
 * tabel + unduh, label Indonesia (dulu Clock In/Clock Out/Record, Scheduled/On Time…). Aksi & permintaan ke server sama.
 */
import { useState, useEffect, useCallback } from 'react';
import { Clock, Plus, RefreshCw, ChevronLeft, ChevronRight, UserCheck, UserX, BarChart3 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { toast } from 'sonner';
import { formatDateID } from '@/lib/format';
import PageLayout from '../../layout/PageLayout';
import PeriodPicker, { ALL_TIME, PERIOD_PRESETS } from '../../finance/PeriodPicker';
import { EmptyState } from '../../moduleAtoms';
import { API, fmtRp } from './utils';
import { AttendanceBadge, LABEL_KEHADIRAN } from './Badges';
import AddShiftModal from './AddShiftModal';
import RecordPerformanceModal from './RecordPerformanceModal';

export default function ShiftsTab({ authH }) {
  const [shifts, setShifts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [pagination, setPagination] = useState({ page: 1, total: 0, limit: 50 });
  const [filters, setFilters] = useState({
    host_id: 'all',
    account_id: '',
    date_from: '',
    date_to: '',
    attendance_status: 'all',
  });
  const [hosts, setHosts] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [showAddShiftModal, setShowAddShiftModal] = useState(false);
  const [showPerformanceModal, setShowPerformanceModal] = useState(false);
  const [selectedShift, setSelectedShift] = useState(null);
  const [periode, setPeriode] = useState({ preset: 'all', from: '', to: '' });

  const fetchShifts = useCallback(
    async (page = 1) => {
      setLoading(true);
      try {
        const params = new URLSearchParams({ page, limit: 50 });
        Object.entries(filters).forEach(([key, val]) => {
          if (val && val !== 'all') params.append(key, val);
        });

        const res = await fetch(`${API}/api/marketing/livehost/shifts?${params}`, { headers: authH });
        if (res.ok) {
          const data = await res.json();
          setShifts(data.shifts || []);
          setPagination(data.pagination || { page: 1, total: 0, limit: 50 });
        }
      } catch (e) {
        toast.error('Gagal memuat data shift');
      } finally {
        setLoading(false);
      }
    },
    [authH, filters]
  );

  const fetchHosts = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/marketing/livehost?status=active`, { headers: authH });
      if (res.ok) {
        const data = await res.json();
        setHosts(data);
      }
    } catch (e) {}
  }, [authH]);

  const fetchAccounts = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/marketing/accounts?status=active`, { headers: authH });
      if (res.ok) {
        const data = await res.json();
        setAccounts(data);
      }
    } catch (e) {}
  }, [authH]);

  useEffect(() => {
    fetchShifts();
    fetchHosts();
    fetchAccounts();
  }, [fetchShifts, fetchHosts, fetchAccounts]);

  const handleClockAction = async (shift, action) => {
    try {
      const res = await fetch(`${API}/api/marketing/livehost/clock`, {
        method: 'POST',
        headers: { ...authH, 'Content-Type': 'application/json' },
        body: JSON.stringify({ shift_id: shift.id, action }),
      });

      if (res.ok) {
        const data = await res.json();
        toast.success(data.message);
        fetchShifts(pagination.page);
      } else {
        const err = await res.json();
        toast.error(err.detail || (action === 'clock_in' ? 'Gagal memulai shift' : 'Gagal mengakhiri shift'));
      }
    } catch (e) {
      toast.error(action === 'clock_in' ? 'Gagal memulai shift' : 'Gagal mengakhiri shift');
    }
  };

  const { page, setPage, totalPages, total, paged } = useClientPagination(shifts, 10);
  const SHIFT = { morning: 'Pagi', afternoon: 'Siang', evening: 'Sore', night: 'Malam', custom: 'Atur sendiri' };
  const tgl = (v) => (v ? formatDateID(v) : '—');

  const aksiShift = (shift) => (
    <div className="flex justify-end gap-1">
      {shift.attendance_status === 'scheduled' && (
        <Button variant="outline" size="sm" onClick={() => handleClockAction(shift, 'clock_in')} data-testid={`clock-in-${shift.id}`}><UserCheck />Mulai shift</Button>
      )}
      {(shift.attendance_status === 'on_time' || shift.attendance_status === 'late') && !shift.clock_out_time && (
        <Button variant="outline" size="sm" onClick={() => handleClockAction(shift, 'clock_out')} data-testid={`clock-out-${shift.id}`}><UserX />Akhiri shift</Button>
      )}
      {shift.attendance_status === 'completed' && shift.revenue === 0 && (
        <Button variant="outline" size="sm" onClick={() => { setSelectedShift(shift); setShowPerformanceModal(true); }}
          data-testid={`record-performance-${shift.id}`}><BarChart3 />Catat performa</Button>
      )}
    </div>
  );
  const kolom = [
    { kunci: 'tgl', label: 'Tanggal', hp: 'keterangan', isi: (s) => <span className="tabular-nums md:whitespace-nowrap">{tgl(s.date)}</span> },
    { kunci: 'host', label: 'Host live', hp: 'judul', isi: (s) => <span className="font-medium">{s.host_name}</span> },
    { kunci: 'shift', label: 'Shift', isi: (s) => <span>{SHIFT[s.shift_type] || s.shift_type}<span className="block text-xs tabular-nums text-muted-foreground">{s.shift_start_time} – {s.shift_end_time}</span></span> },
    { kunci: 'status', label: 'Kehadiran', isi: (s) => <AttendanceBadge status={s.attendance_status} /> },
    { kunci: 'perf', label: 'Performa', rata: 'kanan', isi: (s) => (s.revenue > 0
      ? <span className="tabular-nums">{fmtRp(s.revenue)}<span className="block text-xs text-muted-foreground">{s.orders} pesanan</span></span>
      : <span className="text-muted-foreground">—</span>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: aksiShift },
  ];

  return (
    <PageLayout testId="shifts-tab" title="Shift host live" subtitle="Jadwal shift, kehadiran, dan performa tiap shift."
      actions={<Button onClick={() => setShowAddShiftModal(true)} data-testid="add-shift-btn"><Plus />Tambah shift</Button>}
      filters={<>
        <SmartNativeSelect value={filters.host_id} onChange={(e) => setFilters((f) => ({ ...f, host_id: e.target.value }))} className="w-48" data-testid="filter-host">
          <option value="all">Semua host</option>
          {hosts.map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
        </SmartNativeSelect>
        <PeriodPicker value={periode} presets={[ALL_TIME, ...PERIOD_PRESETS]} testId="filter-shift-period"
          onChange={(v) => { setPeriode(v); setFilters((f) => ({ ...f, date_from: v.from || '', date_to: v.to || '' })); }} />
        <SmartNativeSelect value={filters.attendance_status} onChange={(e) => setFilters((f) => ({ ...f, attendance_status: e.target.value }))}
          className="w-44" searchable={false} data-testid="filter-attendance">
          <option value="all">Semua kehadiran</option>
          {Object.entries(LABEL_KEHADIRAN).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="shift-host-live" namaLembar="Shift" baris={shifts} testId="shift-unduh"
          kolom={[
            { label: 'Tanggal', nilai: (s) => tgl(s.date) }, { label: 'Host live', nilai: (s) => s.host_name || '' },
            { label: 'Shift', nilai: (s) => SHIFT[s.shift_type] || s.shift_type || '' }, { label: 'Jam', nilai: (s) => `${s.shift_start_time || ''} – ${s.shift_end_time || ''}` },
            { label: 'Kehadiran', nilai: (s) => LABEL_KEHADIRAN[s.attendance_status] || '' }, { label: 'Omzet', nilai: (s) => Number(s.revenue) || 0 },
            { label: 'Pesanan', nilai: (s) => Number(s.orders) || 0 },
          ]} />
        <Button variant="outline" size="icon" onClick={() => fetchShifts(pagination.page)} data-testid="refresh-shifts" title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      footer={<>
        {shifts.length > 10 && <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />}
        {pagination.total_pages > 1 && (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-muted-foreground">Menampilkan {shifts.length} dari {pagination.total} shift</p>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="icon-sm" onClick={() => fetchShifts(pagination.page - 1)} disabled={!pagination.has_prev}
                title="Halaman sebelumnya" aria-label="Halaman sebelumnya"><ChevronLeft /></Button>
              <span className="text-sm">Halaman {pagination.page} dari {pagination.total_pages}</span>
              <Button variant="outline" size="icon-sm" onClick={() => fetchShifts(pagination.page + 1)} disabled={!pagination.has_next}
                title="Halaman berikutnya" aria-label="Halaman berikutnya"><ChevronRight /></Button>
            </div>
          </div>
        )}
      </>}>
      {loading && shifts.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat shift…</p>
      ) : (
        <TabelData kolom={kolom} baris={paged} testId="shifts-table"
          kosong={<EmptyState icon={Clock} title="Belum ada shift" description="Tambahkan jadwal shift host live."
            action={<Button onClick={() => setShowAddShiftModal(true)}><Plus />Tambah shift</Button>} />} />
      )}

      {showAddShiftModal && (
        <AddShiftModal hosts={hosts} accounts={accounts} authH={authH}
          onClose={() => setShowAddShiftModal(false)}
          onSuccess={() => { setShowAddShiftModal(false); fetchShifts(pagination.page); }} />
      )}

      {showPerformanceModal && selectedShift && (
        <RecordPerformanceModal shift={selectedShift} authH={authH}
          onClose={() => { setShowPerformanceModal(false); setSelectedShift(null); }}
          onSuccess={() => { setShowPerformanceModal(false); setSelectedShift(null); fetchShifts(pagination.page); }} />
      )}
    </PageLayout>
  );
}

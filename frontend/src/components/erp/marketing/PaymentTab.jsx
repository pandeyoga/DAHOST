/**
 * Rekap host live (Live Selling › Host live › Pembayaran).
 *
 * Keputusan pemilik 8 Nov 2026: host live digaji BULANAN lewat payroll SDM (keputusan 23 Agu 2026), jadi layar
 * ini tidak lagi menghitung atau memfinalkan pembayaran. Isinya kini rekap kerja per host untuk bulan yang dipilih
 * — sesi live, jam live, omzet (dari Sesi live) dan shift selesai (dari Shift) — dengan unduhan Excel/CSV dan
 * tombol ke SDM › Penggajian. Tombol lama "Tandai gaji bulanan" dan "Finalkan rekap" dihapus dari layar
 * (endpoint server tetap ada). Sumber: `GET /api/marketing/livehost/payment/recap?month=YYYY-MM` (hanya membaca).
 */
import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, ChevronLeft, ChevronRight, Info, Users, Banknote } from 'lucide-react';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { toast } from 'sonner';
import { thisMonthWIB, addMonthsYM } from '@/lib/waktu';
import PageLayout from '../layout/PageLayout';
import { monthOptions } from '../finance/PeriodPicker';
import { canAccessPortal } from '../portalAccess';
import { EmptyState, Notice, StatTile } from '../moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;
const fmt = (n) => new Intl.NumberFormat('id-ID').format(n || 0);
const fmtRp = (n) => `Rp ${fmt(n)}`;
const fmtJam = (n) => (Number(n) || 0).toLocaleString('id-ID', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const BULAN = monthOptions(24, 1);

export default function PaymentTab({ authH, user, onNavigate }) {
  const [month, setMonth] = useState(() => thisMonthWIB());
  const [rekap, setRekap] = useState(null);
  const [loading, setLoading] = useState(true);
  const labelBulan = BULAN.find((b) => b.value === month)?.label || month;

  const fetchRekap = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/marketing/livehost/payment/recap?month=${month}`, { headers: authH });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Gagal memuat rekap host');
      setRekap(data);
    } catch (e) {
      toast.error(e.message || 'Gagal memuat rekap host');
      setRekap(null);
    } finally {
      setLoading(false);
    }
  }, [authH, month]);

  useEffect(() => {
    fetchRekap();
  }, [fetchRekap]);

  // Aritmetika bulan murni (lib/waktu) — `new Date(y, m, 1).toISOString()` di browser
  // WIB mundur ke bulan sebelumnya.
  const changeMonth = (offset) => setMonth(addMonthsYM(month, offset));
  const hosts = rekap?.hosts || [];
  const t = rekap?.totals;
  const { page, setPage, totalPages, total, paged } = useClientPagination(hosts, 10);
  const bolehPayroll = typeof onNavigate === 'function' && canAccessPortal(user?.role, 'hr');

  const kolom = [
    { kunci: 'nama', label: 'Host live', hp: 'judul', isi: (h) => <span className="font-medium">{h.host_name}</span> },
    { kunci: 'karyawan', label: 'Karyawan SDM', hp: 'keterangan', isi: (h) => (h.employee_id
      ? <span className="text-sm">{h.employee_name || 'Tertaut'}</span>
      : <span className="text-sm text-[hsl(var(--warning-text))]">Belum ditautkan</span>) },
    { kunci: 'sesi', label: 'Sesi live', rata: 'kanan', isi: (h) => <span className="tabular-nums">{fmt(h.sessions)}</span> },
    { kunci: 'jam', label: 'Jam live', rata: 'kanan', isi: (h) => <span className="tabular-nums">{fmtJam(h.live_hours)}</span> },
    { kunci: 'omzet', label: 'Omzet', rata: 'kanan', isi: (h) => <span className="font-medium tabular-nums">{fmtRp(h.revenue)}</span> },
    { kunci: 'shift', label: 'Shift selesai', rata: 'kanan', isi: (h) => <span className="tabular-nums">{fmt(h.shifts_completed)}</span> },
    { kunci: 'jamshift', label: 'Jam shift', rata: 'kanan', isi: (h) => <span className="tabular-nums">{fmtJam(h.shift_hours)}</span> },
  ];

  return (
    <PageLayout testId="livehost-payment" title="Rekap host live"
      subtitle="Sesi live, jam live, dan omzet per host dalam satu bulan — bahan pengecekan gaji di SDM."
      actions={bolehPayroll && (
        <Button variant="outline" onClick={() => onNavigate('hr-payroll-hub', { tab: 'run' })} data-testid="livehost-ke-payroll">
          <Banknote />Buka SDM › Penggajian
        </Button>
      )}
      filters={
        <div className="flex items-center gap-1">
          <Button variant="outline" size="icon" onClick={() => changeMonth(-1)} title="Bulan sebelumnya" aria-label="Bulan sebelumnya"><ChevronLeft /></Button>
          <SmartNativeSelect value={month} onChange={(e) => setMonth(e.target.value)} className="w-full" wrapperClassName="w-44 max-w-full" searchable={false} data-testid="payment-month-selector">
            {!BULAN.some((b) => b.value === month) && <option value={month}>{month}</option>}
            {BULAN.map((b) => <option key={b.value} value={b.value}>{b.label}</option>)}
          </SmartNativeSelect>
          <Button variant="outline" size="icon" onClick={() => changeMonth(1)} title="Bulan berikutnya" aria-label="Bulan berikutnya"><ChevronRight /></Button>
        </div>
      }
      tools={<>
        <TombolUnduh namaBerkas={`rekap-host-live-${month}`} namaLembar="Rekap host" baris={hosts} testId="livehost-rekap-unduh"
          kolom={[
            { label: 'Host live', nilai: (h) => h.host_name || '' },
            { label: 'Karyawan SDM', nilai: (h) => (h.employee_id ? (h.employee_name || 'Tertaut') : 'Belum ditautkan') },
            { label: 'Sesi live', nilai: (h) => Number(h.sessions) || 0 },
            { label: 'Jam live', nilai: (h) => Number(h.live_hours) || 0 },
            { label: 'Omzet', nilai: (h) => Number(h.revenue) || 0 },
            { label: 'Pesanan', nilai: (h) => Number(h.orders) || 0 },
            { label: 'Shift selesai', nilai: (h) => Number(h.shifts_completed) || 0 },
            { label: 'Jam shift', nilai: (h) => Number(h.shift_hours) || 0 },
          ]} />
        <Button variant="outline" size="icon" onClick={fetchRekap} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={t && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="payment-summary">
          <StatTile label="Host" value={fmt(t.hosts)} sub={t.unlinked ? `${fmt(t.unlinked)} belum ditautkan ke karyawan SDM` : 'Semua tertaut ke karyawan SDM'}
            testId="rekap-host" />
          <StatTile label="Sesi live" value={fmt(t.sessions)} sub={labelBulan} testId="rekap-sesi" />
          <StatTile label="Jam live" value={fmtJam(t.live_hours)} suffix="jam" sub="Dari durasi sesi live" testId="rekap-jam" />
          <StatTile label="Omzet live" value={fmtRp(t.revenue)} sub={`${fmt(t.orders)} pesanan`} testId="rekap-omzet" />
        </div>
      )}
      footer={hosts.length > 10 && <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />}>
      <Notice tone="info" icon={Info} title="Host live digaji bulanan lewat payroll SDM" testId="payment-info">
        Layar ini hanya rekap kerja; tidak ada upah per sesi dan tidak ada yang dicatat ke Keuangan.
        Sesi, jam live, dan omzet dari menu Sesi live; shift selesai dari tab Shift.
      </Notice>
      {loading && !rekap ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat rekap host…</p>
      ) : !rekap ? (
        <EmptyState icon={Users} title="Rekap host tidak tersedia" action={<Button variant="outline" onClick={fetchRekap}>Coba lagi</Button>} />
      ) : (
        <TabelData kolom={kolom} baris={paged} kunci={(r) => r.host_id} testId="livehost-rekap-table"
          kosong={<EmptyState icon={Users} title={`Belum ada host atau sesi live di ${labelBulan}`}
            description="Rekap muncul setelah sesi live dicatat atau shift host selesai." />} />
      )}
    </PageLayout>
  );
}

/**
 * Analitik host live (Live Selling › Host live › Analitik) — performa host & shift per bulan.
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, bulan = pilihan berlabel (dulu input type="month"), tabel + unduh,
 * dua daftar kartu (per jenis shift / per hari) → tabel, label Indonesia (dulu "Host Performance", "avg/shift").
 * Perbaikan tampilan: peringkat dulu dihitung ulang per halaman (halaman 2 kembali 🥇) → kini dari urutan seluruh daftar.
 */
import { useState, useEffect, useCallback } from 'react';
import { BarChart3, RefreshCw, ChevronLeft, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { toast } from 'sonner';
import { addMonthsYM, thisMonthWIB } from '@/lib/waktu';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import PageLayout from '../layout/PageLayout';
import { monthOptions } from '../finance/PeriodPicker';
import { EmptyState } from '../moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;
const fmt = (n) => new Intl.NumberFormat('id-ID').format(n || 0);
const fmtRp = (n) => `Rp ${fmt(n)}`;
const SHIFT = { morning: 'Pagi', afternoon: 'Siang', evening: 'Sore', night: 'Malam', custom: 'Atur sendiri' };
const HARI = { Monday: 'Senin', Tuesday: 'Selasa', Wednesday: 'Rabu', Thursday: 'Kamis', Friday: 'Jumat', Saturday: 'Sabtu', Sunday: 'Minggu' };
const BULAN = monthOptions(24, 1);

export default function AnalyticsTab({ authH }) {
  const [month, setMonth] = useState(() => thisMonthWIB());
  const [hostPerformance, setHostPerformance] = useState([]);
  const [shiftAnalysis, setShiftAnalysis] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchAnalytics = useCallback(async () => {
    setLoading(true);
    try {
      const [perfRes, shiftRes] = await Promise.all([
        fetch(`${API}/api/marketing/livehost/analytics/host-performance?month=${month}`, { headers: authH }),
        fetch(`${API}/api/marketing/livehost/analytics/shift-analysis?month=${month}`, { headers: authH }),
      ]);

      if (perfRes.ok) {
        const perfData = await perfRes.json();
        setHostPerformance(perfData.performance || []);
      }

      if (shiftRes.ok) {
        const shiftData = await shiftRes.json();
        setShiftAnalysis(shiftData);
      }
    } catch (e) {
      toast.error('Gagal memuat analitik host live');
    } finally {
      setLoading(false);
    }
  }, [authH, month]);

  useEffect(() => {
    fetchAnalytics();
  }, [fetchAnalytics]);

  // Aritmetika bulan murni (lib/waktu) — `new Date(y, m, 1).toISOString()` di browser
  // WIB mundur ke bulan sebelumnya.
  const changeMonth = (offset) => setMonth(addMonthsYM(month, offset));
  const labelBulan = BULAN.find((b) => b.value === month)?.label || month;

  const { page, setPage, totalPages, total, paged } = useClientPagination(hostPerformance, 10);
  const peringkat = (h) => hostPerformance.indexOf(h) + 1;
  const perShift = shiftAnalysis?.by_shift_type || [];
  const perHari = shiftAnalysis?.by_day_of_week || [];

  const kolomHost = [
    { kunci: 'rank', label: 'Peringkat', isi: (h) => { const r = peringkat(h); return r <= 3 ? <span className="text-lg">{['🥇', '🥈', '🥉'][r - 1]}</span> : <span className="tabular-nums text-muted-foreground">#{r}</span>; } },
    { kunci: 'nama', label: 'Host live', hp: 'judul', isi: (h) => <span className="font-medium">{h.host_name}</span> },
    { kunci: 'shift', label: 'Shift', rata: 'kanan', isi: (h) => <span className="tabular-nums">{fmt(h.total_shifts)}</span> },
    { kunci: 'jam', label: 'Jam', rata: 'kanan', isi: (h) => <span className="tabular-nums">{(Number(h.total_hours) || 0).toFixed(1).replace('.', ',')}</span> },
    { kunci: 'omzet', label: 'Omzet', rata: 'kanan', hp: 'nilai', isi: (h) => <span className="font-medium tabular-nums">{fmtRp(h.total_revenue)}</span> },
    { kunci: 'pesanan', label: 'Pesanan', rata: 'kanan', isi: (h) => <span className="tabular-nums">{fmt(h.total_orders)}</span> },
    { kunci: 'penonton', label: 'Penonton', rata: 'kanan', isi: (h) => <span className="tabular-nums">{fmt(h.total_viewers)}</span> },
    { kunci: 'rata', label: 'Rata-rata omzet per shift', rata: 'kanan', isi: (h) => <span className="tabular-nums">{fmtRp(h.avg_revenue_per_shift)}</span> },
  ];
  const kolomRingkas = (labelPertama, isiPertama) => [
    { kunci: 'nama', label: labelPertama, hp: 'judul', isi: isiPertama },
    { kunci: 'n', label: 'Jumlah shift', rata: 'kanan', isi: (x) => <span className="tabular-nums">{fmt(x.count)}</span> },
    { kunci: 'avg', label: 'Rata-rata omzet per shift', rata: 'kanan', hp: 'nilai', isi: (x) => <span className="tabular-nums">{fmtRp(x.avg_revenue)}</span> },
  ];

  return (
    <PageLayout testId="livehost-analytics" title="Analitik host live" subtitle="Performa host dan shift dalam satu bulan."
      filters={
        <div className="flex items-center gap-1">
          <Button variant="outline" size="icon" onClick={() => changeMonth(-1)} title="Bulan sebelumnya" aria-label="Bulan sebelumnya"><ChevronLeft /></Button>
          <SmartNativeSelect value={month} onChange={(e) => setMonth(e.target.value)} className="w-44" searchable={false} data-testid="analytics-month-selector">
            {!BULAN.some((b) => b.value === month) && <option value={month}>{month}</option>}
            {BULAN.map((b) => <option key={b.value} value={b.value}>{b.label}</option>)}
          </SmartNativeSelect>
          <Button variant="outline" size="icon" onClick={() => changeMonth(1)} title="Bulan berikutnya" aria-label="Bulan berikutnya"><ChevronRight /></Button>
        </div>
      }
      tools={<>
        <TombolUnduh namaBerkas={`performa-host-live-${month}`} namaLembar="Performa host" baris={hostPerformance} testId="analytics-unduh"
          kolom={[
            { label: 'Peringkat', nilai: peringkat }, { label: 'Host live', nilai: (h) => h.host_name || '' },
            { label: 'Shift', nilai: (h) => Number(h.total_shifts) || 0 }, { label: 'Jam', nilai: (h) => Number(h.total_hours) || 0 },
            { label: 'Omzet', nilai: (h) => Number(h.total_revenue) || 0 }, { label: 'Pesanan', nilai: (h) => Number(h.total_orders) || 0 },
            { label: 'Penonton', nilai: (h) => Number(h.total_viewers) || 0 }, { label: 'Rata-rata omzet per shift', nilai: (h) => Number(h.avg_revenue_per_shift) || 0 },
          ]} />
        <Button variant="outline" size="icon" onClick={fetchAnalytics} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}>
      {loading && !shiftAnalysis ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat analitik…</p>
      ) : (
        <>
          <section className="space-y-2">
            <p className="text-base font-semibold">Performa host · {labelBulan}</p>
            <TabelData kolom={kolomHost} baris={paged} kunci="host_id" testId="host-performance-table"
              kosong={<EmptyState icon={BarChart3} title="Belum ada data performa bulan ini"
                description="Performa muncul setelah shift selesai dan performanya dicatat di tab Shift." />} />
            {hostPerformance.length > 10 && <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />}
          </section>

          <div className="grid gap-4 lg:grid-cols-2">
            <section className="space-y-2">
              <div className="flex items-center gap-2">
                <p className="flex-1 text-base font-semibold">Per jenis shift</p>
                <TombolUnduh namaBerkas={`shift-per-jenis-${month}`} baris={perShift} testId="analytics-unduh-jenis"
                  kolom={[{ label: 'Jenis shift', nilai: (x) => SHIFT[x.shift_type] || x.shift_type }, { label: 'Jumlah shift', nilai: (x) => x.count },
                    { label: 'Rata-rata omzet per shift', nilai: (x) => Number(x.avg_revenue) || 0 }]} />
              </div>
              <TabelData kolom={kolomRingkas('Jenis shift', (x) => SHIFT[x.shift_type] || x.shift_type)} baris={perShift} kunci="shift_type"
                testId="analytics-per-shift" kosong={<EmptyState title="Belum ada shift bulan ini" />} />
            </section>
            <section className="space-y-2">
              <div className="flex items-center gap-2">
                <p className="flex-1 text-base font-semibold">Per hari</p>
                <TombolUnduh namaBerkas={`shift-per-hari-${month}`} baris={perHari} testId="analytics-unduh-hari"
                  kolom={[{ label: 'Hari', nilai: (x) => HARI[x.day] || x.day }, { label: 'Jumlah shift', nilai: (x) => x.count },
                    { label: 'Rata-rata omzet per shift', nilai: (x) => Number(x.avg_revenue) || 0 }]} />
              </div>
              <TabelData kolom={kolomRingkas('Hari', (x) => HARI[x.day] || x.day)} baris={perHari} kunci="day"
                testId="analytics-per-day" kosong={<EmptyState title="Belum ada shift bulan ini" />} />
            </section>
          </div>
        </>
      )}
    </PageLayout>
  );
}

/**
 * Pembayaran host live (Live Selling › Host live › Pembayaran).
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, bulan = pilihan berlabel (dulu input type="month"), label Indonesia.
 *
 * Koreksi isi layar (keputusan 9 brief — angka/teks menyesatkan):
 *  - Kartu "Payment Calculation Formula" (jam × tarif + bonus 10% − denda telat) DIHAPUS: server sudah tidak menghitung
 *    upah per sesi sejak keputusan pemilik 23 Agu 2026 (host digaji bulanan lewat payroll SDM). Diganti penjelasan.
 *  - Tombol "Calculate Payment" sebenarnya menolkan upah per sesi & menandai shift sebagai gaji bulanan → label
 *    "Tandai gaji bulanan". "Sync to Finance" tidak menulis apa pun ke Keuangan (hanya menandai final + memberi tahu
 *    host) → label "Finalkan rekap".
 *  - Kartu "Total Shifts"/"Total Amount" dihapus: server tidak menghitung shift berstatus gaji bulanan, jadi
 *    angkanya tidak sama dengan jumlah shift selesai. Tiga kartu tahap tetap (angka langsung dari server).
 * Permintaan ke server & konfirmasi sama.
 */
import { useState, useEffect, useCallback } from 'react';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { RefreshCw, ChevronLeft, ChevronRight, Loader2, CheckCircle, Info, Wallet } from 'lucide-react';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { toast } from 'sonner';
import { thisMonthWIB, addMonthsYM } from '@/lib/waktu';
import PageLayout from '../layout/PageLayout';
import { monthOptions } from '../finance/PeriodPicker';
import { EmptyState, Notice, StatTile } from '../moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;
const fmt = (n) => new Intl.NumberFormat('id-ID').format(n || 0);
const fmtRp = (n) => `Rp ${fmt(n)}`;
const BULAN = monthOptions(24, 1);

export default function PaymentTab({ authH }) {
  const [month, setMonth] = useState(() => thisMonthWIB());
  const [paymentStatus, setPaymentStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [calculating, setCalculating] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const labelBulan = BULAN.find((b) => b.value === month)?.label || month;

  const fetchPaymentStatus = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/marketing/livehost/payment/status?month=${month}`, { headers: authH });
      if (res.ok) {
        const data = await res.json();
        setPaymentStatus(data);
      }
    } catch (e) {
      toast.error('Gagal memuat status pembayaran');
    } finally {
      setLoading(false);
    }
  }, [authH, month]);

  useEffect(() => {
    fetchPaymentStatus();
  }, [fetchPaymentStatus]);

  const handleCalculate = async () => {
    if (!(await confirmDialog({
      title: `Tandai shift ${labelBulan} sebagai gaji bulanan?`,
      body: 'Upah per sesi pada shift bulan ini dinolkan (nilai lama tetap disimpan). Gaji host dibayar lewat payroll SDM.',
      confirmLabel: 'Tandai',
    }))) return;
    setCalculating(true);
    try {
      const res = await fetch(`${API}/api/marketing/livehost/payment/calculate?month=${month}`, {
        method: 'POST',
        headers: authH,
      });

      if (res.ok) {
        const data = await res.json();
        toast.success(data.message);
        fetchPaymentStatus();
      } else {
        const err = await res.json();
        toast.error(err.detail || 'Gagal menandai shift');
      }
    } catch (e) {
      toast.error('Gagal menandai shift');
    } finally {
      setCalculating(false);
    }
  };

  const handleSync = async () => {
    if (!(await confirmDialog({
      title: `Finalkan rekap ${labelBulan}?`,
      body: 'Shift yang sudah dihitung ditandai final dan host mendapat pemberitahuan. Tidak ada jurnal atau payroll yang dibuat di Keuangan.',
      confirmLabel: 'Finalkan',
    }))) return;
    setSyncing(true);
    try {
      const res = await fetch(`${API}/api/marketing/livehost/payment/sync-to-finance?month=${month}`, {
        method: 'POST',
        headers: authH,
      });

      if (res.ok) {
        const data = await res.json();
        toast.success(data.message);
        fetchPaymentStatus();
      } else {
        const err = await res.json();
        toast.error(err.detail || 'Gagal memfinalkan rekap');
      }
    } catch (e) {
      toast.error('Gagal memfinalkan rekap');
    } finally {
      setSyncing(false);
    }
  };

  // Aritmetika bulan murni (lib/waktu) — `new Date(y, m, 1).toISOString()` di browser
  // WIB mundur ke bulan sebelumnya.
  const changeMonth = (offset) => setMonth(addMonthsYM(month, offset));
  const ss = paymentStatus?.status_summary;

  return (
    <PageLayout testId="livehost-payment" title="Pembayaran host live" subtitle="Status rekap shift host live per bulan."
      actions={<>
        <Button variant="outline" onClick={handleCalculate} disabled={calculating} data-testid="calculate-payment-btn">
          {calculating ? <Loader2 className="animate-spin" /> : <Wallet />}Tandai gaji bulanan
        </Button>
        <Button onClick={handleSync} disabled={syncing} data-testid="sync-to-finance-btn">
          {syncing ? <Loader2 className="animate-spin" /> : <CheckCircle />}Finalkan rekap
        </Button>
      </>}
      filters={
        <div className="flex items-center gap-1">
          <Button variant="outline" size="icon" onClick={() => changeMonth(-1)} title="Bulan sebelumnya" aria-label="Bulan sebelumnya"><ChevronLeft /></Button>
          <SmartNativeSelect value={month} onChange={(e) => setMonth(e.target.value)} className="w-44" searchable={false} data-testid="payment-month-selector">
            {!BULAN.some((b) => b.value === month) && <option value={month}>{month}</option>}
            {BULAN.map((b) => <option key={b.value} value={b.value}>{b.label}</option>)}
          </SmartNativeSelect>
          <Button variant="outline" size="icon" onClick={() => changeMonth(1)} title="Bulan berikutnya" aria-label="Bulan berikutnya"><ChevronRight /></Button>
        </div>
      }
      tools={
        <Button variant="outline" size="icon" onClick={fetchPaymentStatus} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      }
      summary={ss && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3" data-testid="payment-summary">
          <StatTile label="Belum diproses" value={fmt(ss.pending?.count)} suffix="shift" sub={fmtRp(ss.pending?.total_pay)}
            hint="Shift selesai yang belum ditandai." testId="payment-pending" />
          <StatTile label="Sudah dihitung" value={fmt(ss.calculated?.count)} suffix="shift" sub={fmtRp(ss.calculated?.total_pay)}
            hint="Shift yang dihitung dengan cara lama (upah per sesi), siap difinalkan." testId="payment-calculated" />
          <StatTile label="Sudah final" value={fmt(ss.synced_to_finance?.count)} suffix="shift" sub={fmtRp(ss.synced_to_finance?.total_pay)}
            hint="Rekap yang sudah difinalkan." testId="payment-synced" />
        </div>
      )}>
      <Notice tone="info" icon={Info} title="Host live digaji bulanan lewat payroll SDM" testId="payment-info">
        Tidak ada upah per sesi. Data shift (jam tayang, omzet, penonton) tetap dicatat untuk penilaian kinerja.
        Shift yang sudah ditandai gaji bulanan tidak dihitung di kartu di atas.
      </Notice>
      {loading && !paymentStatus ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat status pembayaran…</p>
      ) : !paymentStatus && (
        <EmptyState icon={Wallet} title="Data pembayaran tidak tersedia" action={<Button variant="outline" onClick={fetchPaymentStatus}>Coba lagi</Button>} />
      )}
    </PageLayout>
  );
}

/**
 * Hapus buku piutang macet (Piutang Reseller › Hapus buku).
 *
 * 2026-11-05 (PANDUAN_UI G1/G3/G11): cetakan PageLayout — pilihan "Terlambat minimal" di toolbar kiri, muat
 * ulang di kanan. Tombol merah di tiap baris → tombol garis; warna merah hanya di dialog konfirmasi. Kelompok
 * umur dari server ("31-60 days") ditampilkan dalam bahasa Indonesia; legenda warna dilepas (label sudah tertulis).
 */
import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, ShieldAlert, AlertTriangle, FileText } from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Skeleton } from '@/components/ui/skeleton';
import { StatTile, StatusBadge, EmptyState, Notice } from './moduleAtoms';
import PageLayout from './layout/PageLayout';
import Modal from './Modal';
import { useToast } from '@/hooks/use-toast';
import { formatRupiah, formatDateID } from '@/lib/format';
import { todayWIB } from '@/lib/waktu';

const fmt = formatRupiah;

// Kode kelompok umur dari server → label & nada StatusBadge (G8: kuning = perhatian, merah = masalah).
const AGING_BUCKETS = {
  '0-30 days': { label: '0-30 hari', tone: 'warning' },
  '31-60 days': { label: '31-60 hari', tone: 'warning' },
  '61-90 days': { label: '61-90 hari', tone: 'danger' },
  '91-180 days': { label: '91-180 hari', tone: 'danger' },
  '>180 days (bad debt candidate)': { label: '> 180 hari · calon macet', tone: 'danger' },
};
function BucketBadge({ bucket }) {
  const m = AGING_BUCKETS[bucket];
  return <StatusBadge status={bucket} label={m?.label || String(bucket || '—').replace(/ days?/, ' hari')} tone={m?.tone || 'default'} />;
}

export default function BadDebtWriteOffModule({ token }) {
  const [overdueData, setOverdueData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [minDays, setMinDays] = useState(30);
  const [writeOffTarget, setWriteOffTarget] = useState(null);
  const { toast } = useToast();
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchOverdueReport = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`/api/rahaza/ar-invoices/overdue-report?days=${minDays}`, { headers });
      if (r.ok) {
        setOverdueData(await r.json());
      }
    } catch (e) {
      toast({ title: 'Gagal', description: 'Gagal memuat daftar piutang lewat jatuh tempo', variant: 'destructive' });
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, minDays]);

  useEffect(() => { fetchOverdueReport(); }, [fetchOverdueReport]);

  const writeOff = async (invoice) => {
    if (!writeOffTarget) return;
    if (!writeOffTarget.reason || writeOffTarget.reason.trim().length < 10) {
      toast({ title: 'Gagal', description: 'Alasan hapus buku minimal 10 karakter untuk jejak audit', variant: 'destructive' });
      return;
    }
    try {
      const r = await fetch(`/api/rahaza/ar-invoices/${invoice.id}/write-off-bad-debt`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          reason: writeOffTarget.reason,
          write_off_date: writeOffTarget.write_off_date || todayWIB()
        })
      });
      if (r.ok) {
        toast({ title: 'Berhasil', description: `Faktur ${invoice.invoice_number} dihapusbukukan` });
        setWriteOffTarget(null);
        fetchOverdueReport();
      } else {
        const err = await r.json();
        toast({ title: 'Gagal', description: err.detail || 'Gagal menghapus buku faktur', variant: 'destructive' });
      }
    } catch (e) {
      toast({ title: 'Gagal', description: 'Gagal menghapus buku faktur', variant: 'destructive' });
    }
  };

  const summary = overdueData?.summary || {};
  const invoices = overdueData?.invoices || [];

  return (
    <PageLayout
      testId="bad-debt-page"
      title="Hapus Buku Piutang Macet"
      subtitle="Piutang lewat jatuh tempo dan penghapusan piutang tak tertagih. Jurnal beban piutang tak tertagih dibuat otomatis."
      filters={
        <SmartNativeSelect
          value={String(minDays)}
          onChange={e => setMinDays(Number(e.target.value))}
          searchable={false}
          className="h-9 w-48"
          aria-label="Terlambat minimal"
          data-testid="bd-min-days"
        >
          <option value="0">Semua yang terlambat</option>
          <option value="30">Terlambat 30+ hari</option>
          <option value="60">Terlambat 60+ hari</option>
          <option value="90">Terlambat 90+ hari</option>
          <option value="180">Terlambat 180+ hari</option>
        </SmartNativeSelect>
      }
      tools={
        <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={fetchOverdueReport} data-testid="bd-refresh">
          <RefreshCw className="w-4 h-4" />
        </Button>
      }
      summary={Number(summary.total_overdue_invoices) > 0 && ( // G10: kartu angka hanya bila ada yang terlambat
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatTile label="Faktur lewat jatuh tempo" value={summary.total_overdue_invoices || 0} />
          <StatTile label="Nilai lewat jatuh tempo" value={fmt(summary.total_overdue_amount)} accent="warning" />
          <StatTile label="Berisiko (>180 hari)" value={summary.high_risk_count || 0} accent="danger" />
          <StatTile label="Nilai berisiko" value={fmt(summary.high_risk_amount)} accent="danger" />
        </div>
      )}
    >
      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <div className="space-y-2 p-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
        ) : invoices.length === 0 ? (
          <EmptyState icon={FileText} title="Tidak ada faktur lewat jatuh tempo"
            description={minDays > 0 ? `Tidak ada faktur yang terlambat ${minDays} hari atau lebih.` : 'Semua faktur penjualan masih dalam jatuh tempo atau sudah lunas.'} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="bd-invoice-table">
              <thead>
                <tr className="text-left text-xs text-muted-foreground border-b border-[var(--glass-border)]">
                  <th className="px-4 py-2">No. faktur</th>
                  <th className="px-3 py-2">Jatuh tempo</th>
                  <th className="px-3 py-2 text-right">Terlambat</th>
                  <th className="px-3 py-2">Kelompok umur</th>
                  <th className="px-3 py-2 text-right">Sisa</th>
                  <th className="px-4 py-2 text-right">Aksi</th>
                </tr>
              </thead>
              <tbody>
                {invoices.map(inv => (
                  <tr
                    key={inv.id}
                    className={`border-b border-[var(--glass-border)] hover:bg-[var(--glass-border)]/30 ${inv.overdue_days > 180 ? 'bg-[hsl(var(--destructive)/0.05)]' : ''}`}
                    data-testid={`bd-row-${inv.id}`}
                  >
                    <td className="px-4 py-3 text-xs whitespace-nowrap">{inv.invoice_number}</td>
                    <td className="px-3 py-3 text-xs whitespace-nowrap">{formatDateID(inv.due_date)}</td>
                    <td className="px-3 py-3 text-right tabular-nums whitespace-nowrap">
                      <span className="text-[hsl(var(--destructive))] font-semibold">{inv.overdue_days} hari</span>
                    </td>
                    <td className="px-3 py-3"><BucketBadge bucket={inv.aging_bucket} /></td>
                    <td className="px-3 py-3 text-right tabular-nums whitespace-nowrap">{fmt(inv.balance)}</td>
                    <td className="px-4 py-3 text-right">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setWriteOffTarget({ ...inv, reason: '', write_off_date: '' })}
                        data-testid={`bd-writeoff-${inv.id}`}
                      >
                        <ShieldAlert className="w-3.5 h-3.5" />
                        Hapus buku
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>

      {/* Konfirmasi + isian pendek (alasan, tanggal) — boleh popup (G13) */}
      {writeOffTarget && (
        <Modal onClose={() => setWriteOffTarget(null)} title="Hapus buku piutang macet" size="md" data-testid="bd-writeoff-dialog"
          description="Konfirmasi penghapusan buku piutang">
          <Notice tone="danger" icon={AlertTriangle} className="mb-4"
            title="Piutang faktur ini dihapus dari buku dan jurnal beban piutang tak tertagih dicatat otomatis.">
            <div className="space-y-1 mt-2">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Faktur</span>
                <span className="font-semibold">{writeOffTarget.invoice_number}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Terlambat</span>
                <span className="text-[hsl(var(--destructive))] font-semibold tabular-nums">{writeOffTarget.overdue_days} hari</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Jumlah</span>
                <span className="text-lg font-bold tabular-nums text-[hsl(var(--destructive))]">{fmt(writeOffTarget.balance)}</span>
              </div>
            </div>
          </Notice>
          <div className="space-y-3">
            <div>
              <label className="text-xs text-muted-foreground block mb-1" htmlFor="bd-writeoff-date">Tanggal hapus buku</label>
              <GlassInput
                id="bd-writeoff-date"
                type="date"
                value={writeOffTarget.write_off_date}
                onChange={e => setWriteOffTarget(w => ({ ...w, write_off_date: e.target.value }))}
                data-testid="bd-writeoff-date"
              />
              <div className="text-xs text-muted-foreground mt-1">Kosong = hari ini.</div>
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1" htmlFor="bd-writeoff-reason">
                Alasan <span className="text-[hsl(var(--destructive))]">*</span>
              </label>
              <textarea
                id="bd-writeoff-reason"
                value={writeOffTarget.reason}
                onChange={e => setWriteOffTarget(w => ({ ...w, reason: e.target.value }))}
                className="w-full px-3 py-2 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-sm text-foreground"
                rows={4}
                placeholder="Contoh: pelanggan bangkrut, tidak tertagih setelah 6 bulan penagihan"
                data-testid="bd-writeoff-reason"
              />
              <div className="text-xs text-muted-foreground mt-1">
                Minimal 10 karakter untuk jejak audit. Saat ini: {writeOffTarget.reason.length} karakter
              </div>
            </div>
          </div>
          <div className="flex gap-2 mt-4 justify-end">
            <Button variant="outline" onClick={() => setWriteOffTarget(null)} data-testid="bd-cancel">
              Batal
            </Button>
            <Button
              variant="destructive"
              onClick={() => writeOff(writeOffTarget)}
              disabled={!writeOffTarget.reason || writeOffTarget.reason.length < 10}
              data-testid="bd-confirm-writeoff"
            >
              <ShieldAlert className="w-4 h-4" />
              Hapus buku
            </Button>
          </div>
        </Modal>
      )}
    </PageLayout>
  );
}

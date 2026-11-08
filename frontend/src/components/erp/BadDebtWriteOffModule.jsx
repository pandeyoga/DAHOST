/**
 * Hapus buku piutang macet (Piutang Reseller › Hapus buku).
 *
 * 2026-11-05 (PANDUAN_UI G1/G3/G11): cetakan PageLayout — pilihan "Terlambat minimal" di toolbar kiri, muat
 * ulang di kanan. Tombol merah di tiap baris → tombol garis; warna merah hanya di dialog konfirmasi. Kelompok
 * umur dari server ("31-60 days") ditampilkan dalam bahasa Indonesia; legenda warna dilepas (label sudah tertulis).
 */
import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, ShieldAlert, AlertTriangle, FileText } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Skeleton } from '@/components/ui/skeleton';
import { StatTile, StatusBadge, EmptyState, Notice } from './moduleAtoms';
import PageLayout from './layout/PageLayout';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Textarea } from '@/components/ui/textarea';
import { useToast } from '@/hooks/use-toast';
import { formatRupiah, formatDateID } from '@/lib/format';
import { todayWIB } from '@/lib/waktu';

const fmt = formatRupiah;

// Kode kelompok umur dari server → label & nada StatusBadge (G8: kuning = perhatian, merah = masalah).
const AGING_BUCKETS = {
  // kode server tetap '0-30 days'; sejak 8 Nov 2026 server hanya mengirim faktur terlambat ≥ 1 hari
  '0-30 days': { label: '1-30 hari', tone: 'warning' },
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

  // ringkasan server (overdueData.summary) tidak dipakai untuk kartu — lihat catatan di bawah
  const invoices = overdueData?.invoices || [];

  // 2026-11-08 (Standar UI/UX v2, verifikasi kartu): laporan server dulu ikut menghitung faktur yang jatuh tempo HARI
  // INI (terlambat 0 hari). Server kini sudah memperbaikinya di sumber (keputusan owner 8 Nov); saringan ≥ 1 hari di
  // bawah tetap sebagai pengaman — kartu dihitung dari daftar yang sama dengan tabel.
  const telat = invoices.filter((i) => Number(i.overdue_days) > 0);
  const berisiko = invoices.filter((i) => Number(i.overdue_days) > 180);
  const jumlah = (xs) => xs.reduce((s, i) => s + (Number(i.balance) || 0), 0);

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
      tools={<>
        <TombolUnduh namaBerkas="piutang-lewat-jatuh-tempo" namaLembar="Piutang terlambat" baris={invoices} testId="bd-unduh"
          kolom={[
            { label: 'No. faktur', nilai: (i) => i.invoice_number },
            { label: 'Pelanggan', nilai: (i) => i.customer_name || '' },
            { label: 'Jatuh tempo', nilai: (i) => formatDateID(i.due_date) },
            { label: 'Terlambat (hari)', nilai: (i) => Number(i.overdue_days) || 0 },
            { label: 'Kelompok umur', nilai: (i) => AGING_BUCKETS[i.aging_bucket]?.label || String(i.aging_bucket || '').replace(/ days?/, ' hari') },
            { label: 'Sisa', nilai: (i) => Number(i.balance) || 0 },
          ]} />
        <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={fetchOverdueReport} data-testid="bd-refresh">
          <RefreshCw className="w-4 h-4" />
        </Button>
      </>}
      summary={telat.length > 0 && ( // G10: kartu angka hanya bila ada yang terlambat
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatTile label="Faktur lewat jatuh tempo" value={telat.length} sub="Terlambat 1 hari atau lebih" />
          <StatTile label="Nilai lewat jatuh tempo" value={fmt(jumlah(telat))} accent="warning" sub="Sisa faktur yang terlambat" />
          <StatTile label="Berisiko (> 180 hari)" value={berisiko.length} accent="danger" sub="Kandidat hapus buku" />
          <StatTile label="Nilai berisiko" value={fmt(jumlah(berisiko))} accent="danger" sub="Sisa faktur > 180 hari" />
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
                <tr className="text-left">
                  <th>No. faktur</th>
                  <th>Jatuh tempo</th>
                  <th className="text-right">Terlambat</th>
                  <th className="hidden md:table-cell">Kelompok umur</th>
                  <th className="text-right">Sisa</th>
                  <th className="text-right">Aksi</th>
                </tr>
              </thead>
              <tbody>
                {invoices.map(inv => (
                  <tr
                    key={inv.id}
                    className={`border-b border-[var(--glass-border)] hover:bg-[var(--glass-border)]/30 ${inv.overdue_days > 180 ? 'bg-[hsl(var(--destructive)/0.05)]' : ''}`}
                    data-testid={`bd-row-${inv.id}`}
                  >
                    <td className="whitespace-nowrap">{inv.invoice_number}</td>
                    <td className="whitespace-nowrap">{formatDateID(inv.due_date)}</td>
                    <td className="text-right tabular-nums whitespace-nowrap">
                      <span className={Number(inv.overdue_days) > 0 ? 'text-[hsl(var(--danger-text))] font-semibold' : 'text-muted-foreground'}>{Number(inv.overdue_days) > 0 ? `${inv.overdue_days} hari` : 'jatuh tempo hari ini'}</span>
                    </td>
                    <td className="hidden md:table-cell"><BucketBadge bucket={inv.aging_bucket} /></td>
                    <td className="text-right tabular-nums whitespace-nowrap">{fmt(inv.balance)}</td>
                    <td className="text-right">
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

      {/* Isian pendek (alasan, tanggal) — popup form standar (FormPopup pendek) */}
      {writeOffTarget && (
        <FormPopup open onClose={() => setWriteOffTarget(null)} ukuran="pendek" testId="bd-writeoff-dialog"
          judul="Hapus buku piutang macet" keterangan="Jurnal beban piutang tak tertagih dicatat otomatis."
          onSimpan={() => writeOff(writeOffTarget)} labelSimpan="Hapus buku" warnaSimpan="destructive"
          bisaSimpan={!!writeOffTarget.reason && writeOffTarget.reason.length >= 10}>
          <Notice tone="danger" icon={AlertTriangle}
            title="Piutang faktur ini dihapus dari buku.">
            <dl className="space-y-1 mt-2 text-foreground">
              <div className="flex justify-between gap-3"><dt className="text-muted-foreground">Faktur</dt><dd className="font-semibold">{writeOffTarget.invoice_number}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-muted-foreground">Terlambat</dt><dd className="font-semibold tabular-nums">{writeOffTarget.overdue_days} hari</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-muted-foreground">Jumlah</dt><dd className="font-semibold tabular-nums">{fmt(writeOffTarget.balance)}</dd></div>
            </dl>
          </Notice>
          <Isian label="Tanggal hapus buku" petunjuk="Kosong = hari ini.">
            <DatePicker id="bd-writeoff-date" value={writeOffTarget.write_off_date} placeholder="Hari ini"
              onChange={(v) => setWriteOffTarget(w => ({ ...w, write_off_date: v }))} testId="bd-writeoff-date" />
          </Isian>
          <Isian label="Alasan" wajib htmlFor="bd-writeoff-reason"
            petunjuk={`Minimal 10 karakter untuk jejak audit. Saat ini: ${writeOffTarget.reason.length} karakter.`}>
            <Textarea id="bd-writeoff-reason" rows={4} value={writeOffTarget.reason}
              onChange={e => setWriteOffTarget(w => ({ ...w, reason: e.target.value }))}
              placeholder="Contoh: pelanggan bangkrut, tidak tertagih setelah 6 bulan penagihan" data-testid="bd-writeoff-reason" />
          </Isian>
        </FormPopup>
      )}
    </PageLayout>
  );
}

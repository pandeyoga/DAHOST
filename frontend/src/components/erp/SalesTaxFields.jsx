/**
 * SalesTaxFields — isian PPN untuk dokumen PENJUALAN (AR manual, Penjualan Langsung, tagihan maklon).
 * Mengikuti saklar Status Pajak (lib/taxProfile.js ↔ backend core/tax_status.py):
 *   non-PKP → hanya keterangan "Tanpa PPN" (tidak ada isian);
 *   PKP     → centang "Kena PPN" + nomor & tanggal faktur (boleh diisi setelah faktur terbit di Coretax).
 * value = { kena_ppn, faktur_number, faktur_date }   (faktur_date tetap "YYYY-MM-DD")
 *
 * Standar UI/UX v2 (8 Nov 2026): tanggal faktur memakai DatePicker standar (dulu kotak tanggal bawaan peramban),
 * centang memakai Checkbox standar. Props & nilai tidak berubah.
 */
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import DatePicker from '@/components/ui/date-picker';

export default function SalesTaxFields({ profile, value, onChange, compact = false, testIdPrefix = 'tax' }) {
  const v = value || {};
  const set = (k, val) => onChange({ ...v, [k]: val });
  if (!profile?.pkp) {
    return (
      <div className="rounded-md border border-dashed border-[var(--glass-border)] px-3 py-2 text-xs text-muted-foreground"
           data-testid={`${testIdPrefix}-non-pkp`}>
        Tanpa PPN — perusahaan <b>non-PKP</b> (ubah di Pengaturan Perusahaan › Status Pajak).
      </div>
    );
  }
  return (
    <div className={`space-y-2 rounded-md border border-[var(--glass-border)] px-3 py-2 ${compact ? 'text-xs' : 'text-sm'}`}>
      <label className="flex items-center gap-2" htmlFor={`${testIdPrefix}-kena-ppn`}>
        <Checkbox id={`${testIdPrefix}-kena-ppn`} checked={v.kena_ppn !== false} onCheckedChange={(c) => set('kena_ppn', !!c)}
          data-testid={`${testIdPrefix}-kena-ppn`} />
        <span>Kena PPN <span className="text-muted-foreground">(12% × DPP 11/12 = efektif {profile.effective_pct || 11}%, kode {profile.kode_transaksi || '04'})</span></span>
      </label>
      {v.kena_ppn !== false && (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <label className="space-y-1">
            <span className="text-xs text-muted-foreground">No. faktur pajak (opsional)</span>
            <Input className="h-9" value={v.faktur_number || ''} onChange={(e) => set('faktur_number', e.target.value)}
              placeholder="Diisi setelah terbit di Coretax" data-testid={`${testIdPrefix}-faktur-number`} />
          </label>
          <div className="space-y-1">
            <span className="text-xs text-muted-foreground">Tanggal faktur</span>
            <DatePicker value={v.faktur_date || ''} onChange={(ymd) => set('faktur_date', ymd)} placeholder="Belum ada"
              testId={`${testIdPrefix}-faktur-date`} />
          </div>
        </div>
      )}
    </div>
  );
}

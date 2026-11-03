/**
 * SalesTaxFields — isian PPN untuk dokumen PENJUALAN (AR manual, Penjualan Langsung, tagihan maklon).
 * Mengikuti saklar Status Pajak (lib/taxProfile.js ↔ backend core/tax_status.py):
 *   non-PKP → hanya keterangan "Tanpa PPN" (tidak ada isian);
 *   PKP     → centang "Kena PPN" + nomor & tanggal faktur (boleh diisi setelah faktur terbit di Coretax).
 * value = { kena_ppn, faktur_number, faktur_date }
 */
export default function SalesTaxFields({ profile, value, onChange, compact = false, testIdPrefix = 'tax' }) {
  const v = value || {};
  const set = (k, val) => onChange({ ...v, [k]: val });
  if (!profile?.pkp) {
    return (
      <div className="text-xs text-muted-foreground rounded-md border border-dashed border-[var(--glass-border)] px-3 py-2"
           data-testid={`${testIdPrefix}-non-pkp`}>
        Tanpa PPN — perusahaan <b>non-PKP</b> (ubah di Pengaturan Perusahaan › Status Pajak).
      </div>
    );
  }
  const input = 'h-9 w-full rounded-md border border-[var(--glass-border)] bg-[var(--input-surface)] px-2 text-sm';
  return (
    <div className={`rounded-md border border-[var(--glass-border)] px-3 py-2 space-y-2 ${compact ? 'text-xs' : 'text-sm'}`}>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={v.kena_ppn !== false} onChange={(e) => set('kena_ppn', e.target.checked)}
               data-testid={`${testIdPrefix}-kena-ppn`} />
        <span>Kena PPN <span className="text-muted-foreground">(12% × DPP 11/12 = efektif {profile.effective_pct || 11}%, kode {profile.kode_transaksi || '04'})</span></span>
      </label>
      {v.kena_ppn !== false && (
        <div className="grid grid-cols-2 gap-2">
          <label className="space-y-1">
            <span className="text-xs text-muted-foreground">No. faktur pajak (opsional)</span>
            <input className={input} value={v.faktur_number || ''} onChange={(e) => set('faktur_number', e.target.value)}
                   placeholder="diisi setelah terbit di Coretax" data-testid={`${testIdPrefix}-faktur-number`} />
          </label>
          <label className="space-y-1">
            <span className="text-xs text-muted-foreground">Tanggal faktur</span>
            <input type="date" className={input} value={v.faktur_date || ''} onChange={(e) => set('faktur_date', e.target.value)}
                   data-testid={`${testIdPrefix}-faktur-date`} />
          </label>
        </div>
      )}
    </div>
  );
}

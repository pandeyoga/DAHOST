/**
 * SettlementImportPanel — hasil baca laporan pencairan (Shopee/TikTok) yang MENGISI form,
 * bukan menyimpan. Setiap kolom angka bisa DIARAHKAN ke field tujuan (atau diabaikan);
 * saat pencairan disimpan, pemetaan ini diingat per toko + sidik format header, sehingga
 * impor berikutnya dengan format sama tidak perlu diperiksa ulang (aturan BD-2: pemetaan
 * terlihat & dikonfirmasi manusia, bukan ditebak diam-diam).
 * 2026-11-08 (Standar UI/UX v2): tampil DI DALAM popup form dana dilepas; tanpa huruf kapital, warna token,
 * tombol tutup = Button.
 */
import { FileSpreadsheet, X, AlertTriangle, BookmarkCheck, Wand2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Badge } from '@/components/ui/badge';
import { formatRupiah as rp } from '@/lib/format';
import { Notice } from '@/components/erp/moduleAtoms';

export const FIELD_LABELS = {
  gross_sales: 'Omzet bruto', refunds: 'Refund / retur', seller_discount: 'Diskon penjual',
  shipping_subsidy: 'Subsidi ongkir', platform_commission: 'Komisi platform',
  platform_service_fee: 'Fee layanan', affiliate_commission: 'Komisi afiliasi',
  ads_deduction: 'Potongan iklan', other_deductions: 'Potongan lain',
  adjustments: 'Penyesuaian', net_payout: 'Nominal dicairkan',
};

// Sama persis dengan `compute_values` di backend/core/settlement_import.py.
export function computeValues(mapping, columnTotals) {
  const out = {};
  Object.keys(FIELD_LABELS).forEach((f) => {
    const total = (mapping[f] || []).reduce((t, c) => t + (parseFloat(columnTotals[c]) || 0), 0);
    out[f] = Math.round((f === 'adjustments' ? total : Math.abs(total)) * 100) / 100;
  });
  return out;
}

function fieldOf(mapping, col) {
  return Object.keys(mapping).find((f) => (mapping[f] || []).includes(col)) || '';
}

export function SettlementImportPanel({ result, onClose, onMappingChange }) {
  if (!result) return null;
  const mapping = result.mapping || {};
  const cols = result.numeric_columns || [];
  const unmapped = cols.filter((c) => !fieldOf(mapping, c));
  const saved = result.mapping_source === 'saved';

  const retarget = (col, field) => {
    const next = {};
    Object.entries(mapping).forEach(([f, cs]) => {
      const rest = cs.filter((c) => c !== col);
      if (rest.length) next[f] = rest;
    });
    if (field) next[field] = [...(next[field] || []), col];
    onMappingChange?.(next);
  };

  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--glass-border)] p-3 space-y-2" data-testid="fin-settlement-import-panel">
      <div className="flex items-center justify-between gap-2">
        <p className="font-medium text-sm flex items-center gap-2 flex-wrap">
          <FileSpreadsheet className="w-4 h-4" /> Hasil baca “{result.filename}”
          <span className="text-xs text-muted-foreground">
            {result.row_count} baris · {result.platform_guess || 'platform tidak terdeteksi'}
          </span>
          {saved ? (
            <Badge variant="outline" className="text-xs text-[hsl(var(--success-text))] border-[hsl(var(--success)/0.4)]"
              data-testid="fin-settlement-import-saved-badge">
              <BookmarkCheck className="w-3 h-3 mr-1" /> pemetaan tersimpan
            </Badge>
          ) : (
            <Badge variant="outline" className="text-xs text-[hsl(var(--warning-text))] border-[hsl(var(--warning)/0.4)]"
              data-testid="fin-settlement-import-auto-badge">
              <Wand2 className="w-3 h-3 mr-1" /> tebakan otomatis — periksa
            </Badge>
          )}
        </p>
        <Button type="button" variant="ghost" size="icon-sm" data-testid="fin-settlement-import-close" onClick={onClose}
          title="Tutup hasil baca" aria-label="Tutup hasil baca"><X className="w-4 h-4" /></Button>
      </div>
      <p className="text-xs text-muted-foreground">
        {saved
          ? 'Format laporan ini sudah pernah dikonfirmasi untuk toko ini — kolom dipetakan sesuai pilihan sebelumnya. Anda tetap bisa mengubahnya.'
          : 'Arahkan tiap kolom angka ke field tujuan. Saat pencairan disimpan, pemetaan ini diingat untuk toko & format laporan yang sama.'}
        {' '}Tidak ada yang tersimpan sebelum Anda menekan Simpan.
      </p>

      {/* 2026-11-06 (Tahap 2) — berkas yang kolomnya belum dikenali tetap sampai di sini,
          dengan peringatan; catatan menyebut sheet yang dibaca & baris yang dilewati. */}
      {(result.warnings || []).length > 0 ? (
        <Notice tone="warning" icon={AlertTriangle} title="Kolom uang belum dikenali"
          testId="fin-settlement-import-warnings">
          {result.warnings.join(' ')}
        </Notice>
      ) : null}
      {(result.notes || []).length > 0 ? (
        <ul className="text-xs text-muted-foreground list-disc pl-4 space-y-0.5" data-testid="fin-settlement-import-notes">
          {result.notes.map((n) => <li key={n}>{n}</li>)}
        </ul>
      ) : null}

      <div className="overflow-x-auto">
        <table className="w-full text-xs" data-testid="fin-settlement-import-mapping">
          <thead>
            <tr className="text-muted-foreground border-b border-[var(--glass-border)]">
              <th className="text-left py-1.5 pr-2">Kolom di laporan</th>
              <th className="text-right py-1.5 px-2">Total</th>
              <th className="text-left py-1.5 pl-2">Masuk ke field</th>
            </tr>
          </thead>
          <tbody>
            {cols.map((c) => {
              const f = fieldOf(mapping, c);
              return (
                <tr key={c} className={`border-b border-[var(--glass-border)] ${f ? '' : 'bg-[hsl(var(--warning)/0.06)]'}`}
                  data-testid={`fin-settlement-import-col-${c.replace(/[^a-zA-Z0-9]+/g, '-')}`}>
                  <td className="py-1.5 pr-2">{c}</td>
                  <td className="py-1.5 px-2 text-right tabular-nums">{rp(result.column_totals?.[c] || 0)}</td>
                  <td className="py-1.5 pl-2">
                    {/* 2026-11-07 (audit form Tahap 5): pilihan aplikasi (dulu pilihan polos peramban) */}
                    <SmartNativeSelect value={f} onChange={(e) => retarget(c, e.target.value)} searchable={false}
                      data-testid={`fin-settlement-import-target-${c.replace(/[^a-zA-Z0-9]+/g, '-')}`}
                      className={`h-8 w-48 text-sm ${f ? '' : 'border-[hsl(var(--warning))]'}`}>
                      <option value="">— Abaikan —</option>
                      {Object.entries(FIELD_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                    </SmartNativeSelect>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {unmapped.length > 0 ? (
        <Notice tone="warning" icon={AlertTriangle} testId="fin-settlement-import-unmapped">
          {unmapped.length} kolom angka diabaikan: {unmapped.join(', ')} — pastikan tidak ada potongan yang terlewat.
        </Notice>
      ) : null}
    </div>
  );
}

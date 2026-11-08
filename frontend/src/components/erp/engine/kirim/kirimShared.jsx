/**
 * Bagian bersama layar Kirim ke CMT (Tahap 9, 7 Nov 2026) — tabel POTONGAN dan AKSESORIS (satuan serah).
 *
 * Angka di tabel ini berasal dari satu hitungan server (`core.kirim_cmt`): pratinjau form = yang disimpan =
 * yang memotong stok = yang tercetak di surat jalan & SPP.
 *   • Potongan: pcs per SKU dari BOM, pas, tidak bisa diubah. Stok kurang → kiriman diblokir.
 *   • Aksesoris: perkiraan BOM hanya acuan; jumlah FINAL diisi user dalam satuan serah. Stok berkurang
 *     qty serah × isi kemasan.
 */
import { AlertTriangle } from 'lucide-react';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { GlassInput } from '@/components/ui/glass';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { formatDateID } from '@/lib/format';
import { StatusBadge } from '../../moduleAtoms';

export const fmtNum = (v, max = 2) => Number(v || 0).toLocaleString('id-ID', { maximumFractionDigits: max });
export const fmtRp = (v) => `Rp ${Number(v || 0).toLocaleString('id-ID', { maximumFractionDigits: 0 })}`;
export const fmtDate = (d) => (d ? formatDateID(d) : '—');

export const SHIP_TYPE = {
  NORMAL: { label: 'Kiriman', tone: 'default' },
  ADDITIONAL: { label: 'Tambahan', tone: 'warning' },
  REPLACEMENT: { label: 'Pengganti', tone: 'danger' },
  REWORK: { label: 'Permak', tone: 'info' },
};
export function ShipTypeBadge({ type, testId }) {
  const t = SHIP_TYPE[(type || 'NORMAL').toUpperCase()] || SHIP_TYPE.NORMAL;
  return <StatusBadge status={type || 'NORMAL'} label={t.label} tone={t.tone} testId={testId} />;
}
export function ShipStatusBadge({ status, testId }) {
  const s = (status || 'Sent').toLowerCase();
  return <StatusBadge status={s} label={s === 'received' ? 'Diterima CMT' : 'Dikirim'}
    tone={s === 'received' ? 'success' : 'info'} testId={testId} />;
}

/** Tabel potongan (dikunci). `rows` = calc.potongan atau isi kiriman tersimpan. */
export function PotonganTable({ rows, withStock = false, testId = 'kirim-potongan' }) {
  return (
    <Table data-testid={testId}>
      <TableHeader><TableRow>
        <TableHead>SKU</TableHead><TableHead>Ukuran / warna</TableHead><TableHead>Potongan</TableHead>
        <TableHead className="text-right">Qty (pcs)</TableHead>
        {withStock && <TableHead className="text-right">Stok tersedia</TableHead>}
        <TableHead className="text-right">Nilai</TableHead>
      </TableRow></TableHeader>
      <TableBody>
        {rows.map((p, i) => (
          <TableRow key={`${p.po_item_id || ''}-${p.material_id}-${i}`} data-testid={`${testId}-row-${p.code}`}
            className={p.blocking ? 'bg-[hsl(var(--destructive)/0.06)]' : ''}>
            <TableCell className="whitespace-nowrap">{p.sku || '—'}</TableCell>
            <TableCell className="text-xs text-muted-foreground">{[p.size, p.color].filter(Boolean).join(' / ') || '—'}</TableCell>
            <TableCell>
              <span className="block">{p.name}</span>
              <span className="text-xs text-muted-foreground tabular-nums">{p.code}</span>
              {p.problem && <span className="block text-xs text-[hsl(var(--danger-text))]">{p.problem}</span>}
            </TableCell>
            <TableCell className="text-right tabular-nums font-semibold">{fmtNum(p.qty)}</TableCell>
            {withStock && <TableCell className={`text-right tabular-nums ${p.blocking ? 'text-[hsl(var(--danger-text))]' : ''}`}>{fmtNum(p.available)}</TableCell>}
            <TableCell className="text-right tabular-nums whitespace-nowrap">{p.value ? fmtRp(p.value) : <span className="text-muted-foreground">Rp 0</span>}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/**
 * Tabel aksesoris dalam SATUAN SERAH.
 * mode 'form'   : kolom "Diserahkan" bisa diisi (values[key] = {qty, uom}); perkiraan BOM & sisa rencana tampil.
 * mode 'detail' : yang sudah diserahkan (qty serah + label satuan + qty dasar).
 */
export function AksesorisTable({ rows, mode = 'form', values = {}, onChange, testId = 'kirim-aksesoris' }) {
  const form = mode === 'form';
  return (
    <Table data-testid={testId}>
      <TableHeader><TableRow>
        <TableHead>Aksesoris</TableHead>
        {form && <TableHead className="text-right">Perkiraan BOM</TableHead>}
        {form && <TableHead className="text-right">Sisa rencana PO</TableHead>}
        <TableHead>Satuan serah</TableHead>
        <TableHead className="text-right">{form ? 'Diserahkan (final)' : 'Diserahkan'}</TableHead>
        <TableHead className="text-right">= Satuan dasar</TableHead>
        {form && <TableHead className="text-right">Stok</TableHead>}
      </TableRow></TableHeader>
      <TableBody>
        {rows.map((a) => {
          const v = values[a.key] || {};
          const qty = v.qty ?? a.qty_handover;
          const uom = v.uom || a.handover_uom;
          const opt = (a.options || []).find((o) => o.uom === uom);
          const factor = opt ? opt.factor : a.handover_factor;
          const label = opt ? opt.label : a.handover_label;
          const base = Number(qty || 0) * Number(factor || 1);
          return (
            <TableRow key={a.key || a.material_id || a.code} data-testid={`${testId}-row-${a.code || a.name}`}
              className={a.blocking ? 'bg-[hsl(var(--destructive)/0.06)]' : a.negative ? 'bg-[hsl(var(--warning)/0.06)]' : ''}>
              <TableCell>
                <span className="block">{a.name}</span>
                <span className="text-xs text-muted-foreground tabular-nums">{a.code}</span>
                {a.source === 'tambahan' && <span className="ml-2 text-xs text-muted-foreground">tambahan di luar BOM</span>}
                {a.problem && (
                  <span className={`flex items-center gap-1 text-xs ${a.blocking ? 'text-[hsl(var(--danger-text))]' : 'text-[hsl(var(--warning-text))]'}`}>
                    <AlertTriangle className="w-3 h-3" />{a.problem}
                  </span>
                )}
              </TableCell>
              {form && (
                <TableCell className="text-right tabular-nums whitespace-nowrap text-muted-foreground">
                  {fmtNum(a.estimate_base)} {a.usage_unit}
                  <span className="block text-xs">≈ {fmtNum(a.estimate_handover)} {a.handover_uom}</span>
                </TableCell>
              )}
              {form && (
                <TableCell className="text-right tabular-nums whitespace-nowrap text-muted-foreground">
                  {a.remaining_handover === null || a.remaining_handover === undefined ? '—' : `${fmtNum(a.remaining_handover)} ${a.handover_uom}`}
                </TableCell>
              )}
              <TableCell className="text-sm">
                {form && onChange && (a.options || []).length > 1 ? (
                  <SmartNativeSelect value={uom} aria-label={`Satuan serah ${a.name}`} className="h-8 w-52"
                    data-testid={`${testId}-uom-${a.code}`}
                    onChange={(e) => onChange(a.key, { qty, uom: e.target.value })}>
                    {(a.options || []).map((o) => <option key={o.uom} value={o.uom}>{o.label}</option>)}
                  </SmartNativeSelect>
                ) : <span>{label}</span>}
              </TableCell>
              <TableCell className="text-right">
                {form && onChange ? (
                  <GlassInput type="number" min="0" step="any" className="h-8 w-24 text-right ml-auto"
                    aria-label={`Jumlah serah ${a.name}`} value={qty ?? ''}
                    onChange={(e) => onChange(a.key, { qty: e.target.value, uom })}
                    data-testid={`${testId}-qty-${a.code}`} />
                ) : <span className="tabular-nums font-semibold">{fmtNum(qty, 4)}</span>}
              </TableCell>
              <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtNum(form ? base : a.qty_base, 4)} {a.usage_unit}</TableCell>
              {form && (
                <TableCell className={`text-right tabular-nums whitespace-nowrap ${a.blocking ? 'text-[hsl(var(--danger-text))]' : 'text-muted-foreground'}`}>
                  {fmtNum(a.available)} {a.usage_unit}
                </TableCell>
              )}
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

/** Pilihan satuan serah dari daftar satuan material (sama dengan aturan server `core.satuan_serah`). */
export function handoverOptions(m) {
  const base = String(m?.base_uom || m?.unit || 'pcs').toLowerCase();
  const rows = (Array.isArray(m?.uoms) && m.uoms.length ? m.uoms : [{ code: base, factor: 1 }])
    .map((u) => ({ code: String(u.code || '').toLowerCase(), name: u.name || u.code, factor: Number(u.factor) || 1 }))
    .filter((u) => u.code && u.factor >= 1);
  if (!rows.some((u) => u.code === base)) rows.unshift({ code: base, name: base, factor: 1 });
  rows.sort((a, b) => a.factor - b.factor);
  const packs = rows.filter((u) => u.factor > 1);
  const issue = String(m?.issue_uom || '').toLowerCase();
  const def = packs.find((u) => u.code === issue) || packs[0] || rows[0];
  const label = (u) => (u.factor === 1 ? u.code : `${String(u.name || u.code).toLowerCase()} isi ${u.factor.toLocaleString('id-ID')} ${base}`);
  return { options: rows.map((u) => ({ uom: u.code, factor: u.factor, label: label(u) })), default: def.code, base };
}

/** Judul bagian kecil di dalam panel (bukan judul halaman). */
export function SectionLabel({ children, aside, testId }) {
  return (
    <div className="flex items-center justify-between gap-2 flex-wrap" data-testid={testId}>
      <p className="text-sm font-semibold text-foreground">{children}</p>
      {aside}
    </div>
  );
}

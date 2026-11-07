/**
 * Bagian "Aksesoris" di form PO (internal & maklon — tampilan sama). Tahap 9, keputusan owner no. 3 (7 Nov 2026).
 *
 * Aksesoris diatur di PO dengan SATUAN SERAH:
 *   • dari BOM: perkiraan BOM (satuan pakai, baca saja) + satuan serah (kemasan dari daftar satuan material) +
 *     RENCANA SERAH yang diisi user (bawaan = perkiraan dibulatkan ke atas);
 *   • tambahan di luar BOM: satuan mengikuti material (bukan selalu "pcs"), jumlah dalam satuan serah.
 * Pratinjau = `POST /kirim-cmt/accessory-plan/preview` — rumus yang sama dengan yang ditulis server saat PO disimpan.
 * Baris yang dikirim ke server: {source:'bom'|'tambahan', accessory_id, plan_qty_handover, handover_uom, notes}.
 */
import { useEffect, useState } from 'react';
import { AlertTriangle, Loader2, Plus, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { GlassInput } from '@/components/ui/glass';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { apiPost } from '../../../../lib/api';
import { Notice } from '../../moduleAtoms';
import { fmtNum, handoverOptions } from './kirimShared';

const keyOf = (r) => String(r.accessory_id || r.accessory_code || r.accessory_name || '').toLowerCase();

export default function RencanaAksesorisPO({ businessType, items, rows = [], onChange, accessories = [], active = true }) {
  const maklon = businessType === 'maklon';
  const [preview, setPreview] = useState({ rows: [], warnings: [], total_pcs: 0, loading: false });
  const sig = JSON.stringify((items || []).map((it) => (maklon ? [it.catalog_item_id, Number(it.qty) || 0]
    : [it.model_id, it.size_id, it.rahaza_variant_id, it.color, it.color_code, Number(it.qty) || 0])));

  useEffect(() => {
    if (!active) return undefined;
    const payload = (items || []).filter((it) => Number(it.qty) > 0 && (maklon ? it.catalog_item_id : (it.rahaza_variant_id || it.model_id)))
      .map((it) => (maklon ? { catalog_item_id: it.catalog_item_id, qty: Number(it.qty), label: it.product_name || it.sku || '' }
        : { model_id: it.model_id, size_id: it.size_id, rahaza_variant_id: it.rahaza_variant_id, color: it.color,
          color_code: it.color_code, sku: it.sku, qty: Number(it.qty) }));
    if (!payload.length) { setPreview({ rows: [], warnings: [], total_pcs: 0, loading: false }); return undefined; }
    setPreview((p) => ({ ...p, loading: true }));
    const t = setTimeout(async () => {
      try {
        const res = await apiPost('/kirim-cmt/accessory-plan/preview', { business_type: maklon ? 'maklon' : 'internal', items: payload });
        setPreview({ rows: res?.rows || [], warnings: res?.warnings || [], total_pcs: res?.total_pcs || 0, loading: false });
      } catch (e) {
        setPreview({ rows: [], total_pcs: 0, loading: false, warnings: [`Rencana aksesoris belum bisa dihitung: ${e.message || 'kesalahan jaringan'}`] });
      }
    }, 400);
    return () => clearTimeout(t);
  }, [sig, active, maklon]); // eslint-disable-line react-hooks/exhaustive-deps

  const bomOverride = Object.fromEntries(rows.filter((r) => r.source === 'bom').map((r) => [keyOf(r), r]));
  const extras = rows.map((r, idx) => ({ r, idx })).filter(({ r }) => r.source !== 'bom');
  const matById = Object.fromEntries((accessories || []).map((m) => [m.id, m]));

  const setBom = (b, patch) => {
    const k = keyOf(b);
    const cur = bomOverride[k];
    const next = { ...(cur || { source: 'bom', accessory_id: b.accessory_id, accessory_name: b.accessory_name,
      accessory_code: b.accessory_code, handover_uom: b.handover_uom }), ...patch, plan_edited: true };
    onChange(cur ? rows.map((r) => (r === cur ? next : r)) : [...rows, next]);
  };
  const setExtra = (idx, patch) => onChange(rows.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  const addExtra = () => onChange([...rows, { source: 'tambahan', accessory_id: '', accessory_name: '', accessory_code: '',
    plan_qty_handover: '', handover_uom: '', notes: '' }]);

  return (
    <div className="space-y-2" data-testid="po-acc-plan">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <p className="text-xs font-medium text-muted-foreground flex items-center gap-2">
          Dari BOM — perkiraan dari BOM, rencana serah boleh diubah
          {preview.loading && <span className="inline-flex items-center gap-1"><Loader2 className="w-3.5 h-3.5 animate-spin" /> menghitung…</span>}
        </p>
        <Button type="button" variant="outline" size="sm" onClick={addExtra} data-testid="po-add-accessory">
          <Plus className="w-3.5 h-3.5" /> Tambah aksesoris
        </Button>
      </div>
      {preview.rows.length === 0 ? (
        <p className="text-xs text-muted-foreground border border-dashed border-border rounded-lg px-3 py-2" data-testid="po-bom-acc-empty">
          {preview.loading ? 'Menghitung rencana aksesoris dari BOM…'
            : (maklon ? 'Pilih artikel katalog dan isi qty — aksesoris muncul otomatis bila artikelnya punya BOM aktif.'
              : 'Pilih varian dan isi qty — aksesoris muncul otomatis dari BOM warna varian itu.')}
        </p>
      ) : (
        <Table data-testid="po-bom-accessories-panel">
          <TableHeader><TableRow>
            <TableHead>Aksesoris</TableHead>
            {maklon && <TableHead>Disediakan</TableHead>}
            <TableHead className="text-right">Perkiraan BOM</TableHead>
            <TableHead>Satuan serah</TableHead>
            <TableHead className="text-right">Rencana serah</TableHead>
            <TableHead className="text-right">= Satuan dasar</TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {preview.rows.map((b, i) => {
              const o = bomOverride[keyOf(b)] || {};
              const mat = matById[b.accessory_id];
              const ho = handoverOptions(mat || { unit: b.usage_unit });
              const uom = o.handover_uom || b.handover_uom;
              const opt = ho.options.find((x) => x.uom === uom);
              const factor = opt ? opt.factor : b.handover_factor;
              const planned = o.plan_edited || o.plan_qty_handover !== undefined
                ? (o.plan_qty_handover ?? '') : b.plan_qty_handover;
              const client = maklon && (b.ownership || 'client_provided') === 'client_provided';
              return (
                <TableRow key={`${keyOf(b)}-${i}`} data-testid={`po-bom-acc-row-${i}`}>
                  <TableCell>
                    <span className="block">{b.accessory_name}</span>
                    <span className="text-xs text-muted-foreground tabular-nums">{b.accessory_code || '—'}</span>
                    {b.unlinked && <span className="ml-1.5 text-[hsl(var(--danger-text))] text-xs font-semibold">belum tertaut master</span>}
                    {b.handover_status && !['ok', 'dasar'].includes(b.handover_status) && (
                      <span className="block text-xs text-[hsl(var(--warning-text))]">Satuan serah perlu dicek gudang</span>
                    )}
                  </TableCell>
                  {maklon && <TableCell className="text-xs">{client ? 'Klien' : 'CV DA'}</TableCell>}
                  <TableCell className="text-right tabular-nums whitespace-nowrap text-muted-foreground">
                    {fmtNum(b.bom_qty_base, 4)} {b.usage_unit}
                    <span className="block text-xs">≈ {fmtNum(b.bom_qty_handover)} {b.handover_uom}</span>
                  </TableCell>
                  <TableCell>
                    {client ? <span className="text-xs text-muted-foreground">—</span> : ho.options.length > 1 ? (
                      <SmartNativeSelect value={uom} className="h-8 w-52" aria-label={`Satuan serah ${b.accessory_name}`}
                        onChange={(e) => setBom(b, { handover_uom: e.target.value, plan_qty_handover: planned })}>
                        {ho.options.map((x) => <option key={x.uom} value={x.uom}>{x.label}</option>)}
                      </SmartNativeSelect>
                    ) : <span className="text-sm">{b.handover_label}</span>}
                  </TableCell>
                  <TableCell className="text-right">
                    {client ? <span className="text-xs text-muted-foreground">dari klien</span> : (
                      <GlassInput type="number" min="0" step="any" className="h-8 w-24 text-right ml-auto" value={planned ?? ''}
                        aria-label={`Rencana serah ${b.accessory_name}`} data-testid={`po-bom-acc-plan-${i}`}
                        onChange={(e) => setBom(b, { plan_qty_handover: e.target.value, handover_uom: uom })} />
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">
                    {client ? '—' : `${fmtNum(Number(planned || 0) * Number(factor || 1), 4)} ${b.usage_unit}`}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
      {preview.rows.length > 0 && (
        <p className="text-xs text-muted-foreground">Untuk {fmtNum(preview.total_pcs)} pcs. Baris BOM ditulis sistem saat PO disimpan;
          rencana serah yang diubah ikut tersimpan dan dipakai sebagai jumlah bawaan saat Kirim ke CMT.</p>
      )}
      {(preview.warnings || []).length > 0 && (
        <Notice tone="warning" icon={AlertTriangle} testId="po-bom-acc-warning">
          <div className="space-y-0.5">{preview.warnings.slice(0, 6).map((w, i) => <p key={i} className="text-xs">{w}</p>)}</div>
        </Notice>
      )}
      <p className="text-xs font-medium text-muted-foreground">Tambahan di luar BOM (opsional)</p>
      {extras.length === 0 && (
        <p className="text-xs text-muted-foreground border border-dashed border-border rounded-lg px-3 py-2">Klik "Tambah aksesoris" bila perlu aksesoris di luar BOM.</p>
      )}
      {extras.map(({ r, idx }) => {
        const mat = matById[r.accessory_id];
        const ho = handoverOptions(mat || { unit: r.usage_unit || r.unit || 'pcs', uoms: [] });
        const uom = r.handover_uom || ho.default;
        const opt = ho.options.find((x) => x.uom === uom) || ho.options[0];
        const plan = r.plan_qty_handover ?? (r.qty_needed && opt ? Number(r.qty_needed) / (opt.factor || 1) : '');
        return (
          <div key={r.id || idx} className="grid grid-cols-1 sm:grid-cols-[1fr_7rem_14rem_9rem_auto] items-center gap-2" data-testid={`po-acc-row-${idx}`}>
            <SmartNativeSelect value={r.accessory_id || ''} aria-label="Aksesoris tambahan" className="h-9 w-full"
              onChange={(e) => {
                const m = matById[e.target.value];
                setExtra(idx, { accessory_id: e.target.value, accessory_name: m?.name || m?.accessory_name || '',
                  accessory_code: m?.code || m?.accessory_code || '', unit: m?.base_uom || m?.unit || '',
                  handover_uom: handoverOptions(m).default });
              }}>
              <option value="">Pilih aksesoris</option>
              {(accessories || []).map((m) => <option key={m.id} value={m.id}>{m.name || m.accessory_name} · {m.code || m.accessory_code}</option>)}
            </SmartNativeSelect>
            <GlassInput type="number" min="0" step="any" value={plan} placeholder="Qty" className="h-9 text-right"
              aria-label="Qty serah tambahan" data-testid={`po-acc-qty-${idx}`}
              onChange={(e) => setExtra(idx, { plan_qty_handover: e.target.value, handover_uom: uom })} />
            <SmartNativeSelect value={uom} aria-label="Satuan serah tambahan" className="h-9 w-full" data-testid={`po-acc-uom-${idx}`}
              onChange={(e) => setExtra(idx, { handover_uom: e.target.value })}>
              {ho.options.map((x) => <option key={x.uom} value={x.uom}>{x.label}</option>)}
            </SmartNativeSelect>
            <GlassInput value={r.notes || ''} onChange={(e) => setExtra(idx, { notes: e.target.value })} placeholder="Catatan" className="h-9" />
            <Button type="button" variant="outline" size="icon" title="Hapus aksesoris" aria-label="Hapus aksesoris"
              onClick={() => onChange(rows.filter((_, i) => i !== idx))}><X className="w-4 h-4" /></Button>
          </div>
        );
      })}
    </div>
  );
}

/** Baris `po_accessories` tersimpan → baris form (dipakai saat PO dibuka untuk diubah). */
export function planRowsFromPo(list) {
  return (list || []).map((a) => {
    const bom = ['bom', 'bom_auto', 'bom_maklon_auto'].includes(a.source) || !!a.bom_origin;
    return {
      id: a.id, source: bom ? 'bom' : 'tambahan', accessory_id: a.accessory_id || '', accessory_name: a.accessory_name || '',
      accessory_code: a.accessory_code || '', unit: a.usage_unit || a.unit || '', notes: a.notes || '',
      handover_uom: a.handover_uom || '', plan_qty_handover: a.plan_qty_handover ?? undefined, qty_needed: a.qty_needed,
      plan_edited: bom ? !!a.plan_edited : undefined,
    };
  }).map((r) => (r.source === 'bom' && !r.plan_edited ? { ...r, plan_qty_handover: undefined } : r));
}

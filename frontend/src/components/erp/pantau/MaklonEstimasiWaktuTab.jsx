/**
 * Dashboard Maklon › Estimasi waktu — perkiraan lama produksi order maklon dari jenis garmen, jumlah,
 * kerumitan, dan beban order aktif. Sumber: POST /api/maklon/sla/lead-time/estimate (hanya menghitung).
 * (Estimasi AI harga maklon pindah ke Katalog Buyer — keputusan 7 Nov; ini bukan estimasi AI.)
 */
import { useState } from 'react';
import { AlertTriangle, Calculator } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Table, TableBody, TableCell, TableRow } from '@/components/ui/table';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice } from '../moduleAtoms';
import apiFetch from '@/lib/apiFetch';
import { formatDateID } from '@/lib/format';
import { n } from './pantauShared';

const GARMENTS = [
  ['shirt', 'Kemeja'], ['blouse', 'Blus'], ['dress', 'Gaun'], ['pants', 'Celana'], ['skirt', 'Rok'], ['jacket', 'Jaket'],
  ['coat', 'Mantel'], ['uniform', 'Seragam'], ['casual', 'Pakaian santai'], ['formal', 'Pakaian formal'], ['other', 'Lainnya'],
];
const COMPLEXITY = [['simple', 'Sederhana (jahitan dasar)'], ['medium', 'Sedang (standar)'], ['complex', 'Rumit (detail tinggi)']];
const OPTIONS = [['has_embroidery', 'Ada bordir/sulam'], ['has_special_material', 'Bahan khusus/impor'], ['rush_order', 'Order dipercepat']];

export default function MaklonEstimasiWaktuTab() {
  const [form, setForm] = useState({ garment_type: 'blouse', quantity: 100, complexity: 'medium', has_embroidery: false, has_special_material: false, rush_order: false });
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const set = (k, v) => setForm((p) => ({ ...p, [k]: v }));
  const run = async () => {
    if (!(Number(form.quantity) > 0)) { toast.error('Isi jumlah lebih dari 0'); return; }
    setLoading(true);
    try {
      const res = await apiFetch('/maklon/sla/lead-time/estimate', { method: 'POST', body: { ...form, quantity: parseInt(form.quantity, 10) } });
      setResult(res.data);
    } catch (e) { toast.error(`Estimasi gagal: ${e.message}`); }
    finally { setLoading(false); }
  };
  const b = result?.breakdown || {};
  const rows = result ? [
    ['Hari dasar', n(b.base_days)], ['Pengali kerumitan', `×${b.complexity_mult}`], ['Tambahan karena jumlah', `+${n(b.qty_factor_pct)}%`],
    ['Tambahan karena beban order', `+${n(b.workload_factor_pct)}%`], ['Order aktif saat ini', n(b.active_orders_now)],
    ...(b.embroidery_days > 0 ? [['Bordir', `+${n(b.embroidery_days)} hari`]] : []),
    ...(b.special_material_days > 0 ? [['Bahan khusus', `+${n(b.special_material_days)} hari`]] : []),
    ...(b.rush_discount_days > 0 ? [['Dipercepat', `−${n(b.rush_discount_days)} hari`]] : []),
  ] : [];

  return (
    <PageLayout testId="maklon-estimasi-waktu" title="Estimasi waktu produksi">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <GlassCard className="p-4 space-y-3" data-testid="leadtime-form">
          <p className="text-sm font-semibold">Data order</p>
          <div className="grid grid-cols-2 gap-3">
            <div><label className="text-xs text-muted-foreground">Jenis garmen</label>
              <SmartNativeSelect value={form.garment_type} onChange={(e) => set('garment_type', e.target.value)} className="h-9 w-full" aria-label="Jenis garmen">
                {GARMENTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </SmartNativeSelect></div>
            <div><label className="text-xs text-muted-foreground" htmlFor="lt-qty">Jumlah (pcs)</label>
              <GlassInput id="lt-qty" type="number" min="1" className="h-9" value={form.quantity} onChange={(e) => set('quantity', e.target.value)} /></div>
          </div>
          <div><label className="text-xs text-muted-foreground">Kerumitan</label>
            <SmartNativeSelect value={form.complexity} onChange={(e) => set('complexity', e.target.value)} searchable={false} className="h-9 w-full" aria-label="Kerumitan">
              {COMPLEXITY.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </SmartNativeSelect></div>
          <div className="space-y-2">
            {OPTIONS.map(([k, l]) => (
              <label key={k} className="flex items-center gap-2 text-sm cursor-pointer" htmlFor={`lt-${k}`}>
                <Checkbox id={`lt-${k}`} checked={form[k]} onCheckedChange={(v) => set(k, !!v)} />{l}
              </label>
            ))}
          </div>
          <Button onClick={run} disabled={loading} data-testid="btn-estimate-leadtime"><Calculator className="w-4 h-4" />{loading ? 'Menghitung…' : 'Hitung estimasi'}</Button>
        </GlassCard>
        <GlassCard className="p-4 space-y-3" data-testid="leadtime-result">
          <p className="text-sm font-semibold">Hasil estimasi</p>
          {!result ? (
            <EmptyState icon={Calculator} title="Belum ada estimasi" description="Isi data order lalu tekan Hitung estimasi." />
          ) : <>
            <p className="text-3xl font-bold text-[hsl(var(--primary))] tabular-nums">{n(result.estimated_days)} hari</p>
            <p className="text-sm text-muted-foreground">Target selesai {result.target_delivery_date ? formatDateID(result.target_delivery_date) : '—'}</p>
            {result.recommendation && <Notice tone="warning" icon={AlertTriangle}>{result.recommendation}</Notice>}
            <Table>
              <TableBody>
                {rows.map(([l, v]) => <TableRow key={l}><TableCell className="text-muted-foreground">{l}</TableCell><TableCell className="text-right tabular-nums">{v}</TableCell></TableRow>)}
              </TableBody>
            </Table>
            {result.historical_avg_days && (
              <p className="text-xs text-muted-foreground">Rata-rata historis {n(result.historical_avg_days)} hari dari {n(result.historical_sample_size)} order.</p>
            )}
          </>}
        </GlassCard>
      </div>
    </PageLayout>
  );
}

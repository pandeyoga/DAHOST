/**
 * Dashboard Maklon › Estimasi waktu — perkiraan lama produksi order maklon dari jenis garmen, jumlah,
 * kerumitan, dan beban order aktif. Sumber: POST /api/maklon/sla/lead-time/estimate (hanya menghitung).
 * (Estimasi AI harga maklon pindah ke Katalog Buyer — keputusan 7 Nov; ini bukan estimasi AI.)
 *
 * Standar UI/UX v2 (8 Nov 2026): isian data order dibuka sebagai FormPopup ("form selalu popup"); halaman berisi
 * hasil estimasi + rinciannya (tabel standar yang bisa diunduh). Isian & perhitungan tidak berubah.
 */
import { useState } from 'react';
import { AlertTriangle, Calculator } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { GlassCard } from '@/components/ui/glass';
import { Table, TableBody, TableCell, TableRow } from '@/components/ui/table';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatTile } from '../moduleAtoms';
import apiFetch from '@/lib/apiFetch';
import { formatDateID } from '@/lib/format';
import { n } from './pantauShared';

const GARMENTS = [
  ['shirt', 'Kemeja'], ['blouse', 'Blus'], ['dress', 'Gaun'], ['pants', 'Celana'], ['skirt', 'Rok'], ['jacket', 'Jaket'],
  ['coat', 'Mantel'], ['uniform', 'Seragam'], ['casual', 'Pakaian santai'], ['formal', 'Pakaian formal'], ['other', 'Lainnya'],
];
const COMPLEXITY = [['simple', 'Sederhana (jahitan dasar)'], ['medium', 'Sedang (standar)'], ['complex', 'Rumit (detail tinggi)']];
const OPTIONS = [['has_embroidery', 'Ada bordir/sulam'], ['has_special_material', 'Bahan khusus/impor'], ['rush_order', 'Order dipercepat']];
const label = (list, v) => (list.find(([k]) => k === v) || [v, v])[1];

export default function MaklonEstimasiWaktuTab() {
  const [form, setForm] = useState({ garment_type: 'blouse', quantity: 100, complexity: 'medium', has_embroidery: false, has_special_material: false, rush_order: false });
  const [result, setResult] = useState(null);
  const [dipakai, setDipakai] = useState(null);   // data order yang dipakai untuk hasil terakhir
  const [loading, setLoading] = useState(false);
  const [buka, setBuka] = useState(false);
  const set = (k, v) => setForm((p) => ({ ...p, [k]: v }));
  const run = async () => {
    if (!(Number(form.quantity) > 0)) { toast.error('Isi jumlah lebih dari 0'); return; }
    setLoading(true);
    try {
      const res = await apiFetch('/maklon/sla/lead-time/estimate', { method: 'POST', body: { ...form, quantity: parseInt(form.quantity, 10) } });
      setResult(res.data);
      setDipakai({ ...form });
      setBuka(false);
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
    <PageLayout testId="maklon-estimasi-waktu" title="Estimasi waktu produksi"
      actions={<Button onClick={() => setBuka(true)} data-testid="btn-open-leadtime"><Calculator />{result ? 'Hitung ulang' : 'Hitung estimasi'}</Button>}
      tools={result && (
        <TombolUnduh namaBerkas="estimasi-waktu-maklon" namaLembar="Estimasi" baris={rows.map(([l, v]) => ({ l, v }))} testId="leadtime-unduh"
          kolom={[{ label: 'Komponen', nilai: (r) => r.l }, { label: 'Nilai', nilai: (r) => r.v }]} />
      )}
      summary={result && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="leadtime-result">
          <StatTile label="Perkiraan lama produksi" value={`${n(result.estimated_days)} hari`} accent="primary"
            sub={`${label(GARMENTS, dipakai?.garment_type)} · ${n(dipakai?.quantity)} pcs · ${label(COMPLEXITY, dipakai?.complexity).split(' (')[0]}`} />
          <StatTile label="Target selesai" value={result.target_delivery_date ? formatDateID(result.target_delivery_date) : '—'}
            sub="Dihitung dari hari ini" />
          <StatTile label="Rata-rata historis" value={result.historical_avg_days ? `${n(result.historical_avg_days)} hari` : '—'}
            sub={result.historical_avg_days ? `Dari ${n(result.historical_sample_size)} order` : 'Belum ada order selesai sejenis'} />
          <StatTile label="Order aktif saat ini" value={n(b.active_orders_now)} sub="Ikut menambah lama produksi" />
        </div>
      )}>
      {!result ? (
        <EmptyState icon={Calculator} title="Belum ada estimasi" description="Isi data order (jenis, jumlah, kerumitan) untuk melihat perkiraan lama produksi."
          action={<Button onClick={() => setBuka(true)} data-testid="btn-estimate-leadtime-empty"><Calculator />Hitung estimasi</Button>} />
      ) : (
        <GlassCard className="space-y-3 p-4">
          {result.recommendation && <Notice tone="warning" icon={AlertTriangle}>{result.recommendation}</Notice>}
          <p className="text-sm font-semibold text-foreground">Rincian perhitungan</p>
          <Table>
            <TableBody>
              {rows.map(([l, v]) => <TableRow key={l}><TableCell className="text-muted-foreground">{l}</TableCell><TableCell className="text-right tabular-nums">{v}</TableCell></TableRow>)}
            </TableBody>
          </Table>
        </GlassCard>
      )}

      <FormPopup open={buka} onClose={() => setBuka(false)} ukuran="pendek" judul="Data order" testId="leadtime-form"
        keterangan="Hanya menghitung — tidak ada data yang disimpan." onSimpan={run} menyimpan={loading} labelSimpan="Hitung estimasi">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Isian label="Jenis garmen">
            <SmartNativeSelect value={form.garment_type} onChange={(e) => set('garment_type', e.target.value)} className="h-9 w-full" aria-label="Jenis garmen">
              {GARMENTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Jumlah (pcs)" wajib htmlFor="lt-qty">
            <Input id="lt-qty" type="number" min="1" value={form.quantity} onChange={(e) => set('quantity', e.target.value)} />
          </Isian>
        </div>
        <Isian label="Kerumitan">
          <SmartNativeSelect value={form.complexity} onChange={(e) => set('complexity', e.target.value)} searchable={false} className="h-9 w-full" aria-label="Kerumitan">
            {COMPLEXITY.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </SmartNativeSelect>
        </Isian>
        <div className="space-y-2">
          {OPTIONS.map(([k, l]) => (
            <label key={k} className="flex cursor-pointer items-center gap-2 text-sm" htmlFor={`lt-${k}`}>
              <Checkbox id={`lt-${k}`} checked={form[k]} onCheckedChange={(v) => set(k, !!v)} />{l}
            </label>
          ))}
        </div>
      </FormPopup>
    </PageLayout>
  );
}

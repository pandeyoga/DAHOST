import { useState } from 'react';
import { Copy, PackagePlus, Calculator, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import FormPopup from '@/components/ui/form-popup';
import { GlassInput } from '@/components/ui/glass';
import { toast } from 'sonner';
import { InlineMaterialPicker } from './InlineMaterialPicker';

const post = (url, headers, body) => fetch(url, { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })
  .then(async (r) => { const j = await r.json(); if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : j.detail?.message || `HTTP ${r.status}`); return j; });

// Jalan pintas pengisian BOM (owner 2026-09-12): salin ke varian tanpa BOM · aksesoris massal · HPP standar
export function BomShortcuts({ headers, token, selectedModelId, modelLabel, categories, onDone }) {
  const [busy, setBusy] = useState('');
  const [accOpen, setAccOpen] = useState(false);
  const [lines, setLines] = useState([]);

  const copyMissing = async (all) => {
    setBusy('copy');
    try {
      const r = await post('/api/rahaza/master/bom/copy-missing', headers, all ? {} : { model_id: selectedModelId });
      toast.success(`${r.created} BOM dibuat untuk varian tanpa BOM${r.skipped?.length ? ` · ${r.skipped.length} dilewati (model belum punya BOM)` : ''}`);
      onDone && onDone();
    } catch (e) { toast.error(e.message); } finally { setBusy(''); }
  };
  const recalc = async () => {
    setBusy('hpp');
    try {
      const r = await post('/api/rahaza/master/recalc-hpp', headers, {});
      toast.success(`HPP standar: ${r.panels_standard_costed} potongan dinilai · HPP ${r.models_hpp_applied} model diterapkan`);
      onDone && onDone();
    } catch (e) { toast.error(e.message); } finally { setBusy(''); }
  };
  const addAccessories = async () => {
    if (!lines.length) return;
    setBusy('acc');
    try {
      const r = await post('/api/rahaza/master/bom/add-lines', headers, { model_id: selectedModelId, lines: lines.map((l) => ({ material_id: l.id, code: l.code, name: l.name, material_type: l.type, qty: Number(l.qty) || 1, unit: l.unit })) });
      toast.success(`${r.lines_appended} baris aksesoris ditambahkan ke ${r.boms_touched}/${r.boms_total} BOM ${modelLabel}`);
      setAccOpen(false); setLines([]); onDone && onDone();
    } catch (e) { toast.error(e.message); } finally { setBusy(''); }
  };

  return (
    <div className="flex items-center gap-2 flex-wrap" data-testid="bom-shortcuts">
      <Button type="button" size="sm" variant="outline" disabled={!selectedModelId || !!busy} onClick={() => copyMissing(false)} title="Buat BOM untuk semua varian model ini yang belum punya BOM — potongan & kain otomatis mengikuti warna/ukuran tujuan, aksesoris disalin" data-testid="bom-copy-missing-model">
        <Copy className="w-3.5 h-3.5 mr-1" />{busy === 'copy' ? 'Menyalin…' : 'Salin ke varian tanpa BOM'}
      </Button>
      <Button type="button" size="sm" variant="outline" disabled={!!busy} onClick={() => copyMissing(true)} title="Buat BOM untuk varian yang belum punya BOM di semua model sekaligus" data-testid="bom-copy-missing-all">Salin untuk semua model</Button>
      <Button type="button" size="sm" variant="outline" disabled={!selectedModelId || !!busy} onClick={() => setAccOpen(true)} title="Tambah aksesoris yang sama ke SEMUA BOM aktif model ini" data-testid="bom-add-acc-bulk">
        <PackagePlus className="w-3.5 h-3.5 mr-1" />Aksesoris massal
      </Button>
      <Button type="button" size="sm" variant="outline" disabled={!!busy} onClick={recalc} title="Nilai potongan = qty kain × harga kain (standar, sampai cutting nyata), lalu HPP semua model diterapkan ke barang jadi & katalog" data-testid="bom-recalc-hpp">
        <Calculator className="w-3.5 h-3.5 mr-1" />{busy === 'hpp' ? 'Menghitung…' : 'Hitung HPP standar'}
      </Button>
      <FormPopup open={accOpen} onClose={() => setAccOpen(false)} ukuran="panjang" testId="bom-acc-bulk-dialog"
        judul={`Tambah aksesoris ke semua BOM · ${modelLabel}`}
        keterangan="Baris ditambahkan ke setiap BOM aktif model ini (semua warna & ukuran). Yang sudah ada dilewati."
        onSimpan={addAccessories} menyimpan={busy === 'acc'} bisaSimpan={lines.length > 0} labelSimpan={`Tambahkan ${lines.length} baris`}>
          <div className="space-y-2">
            {lines.map((l, i) => (
              <div key={l.id} className="flex items-center gap-2 text-sm" data-testid={`bom-acc-bulk-line-${l.code}`}>
                <span className="tabular-nums text-xs w-28 truncate">{l.code}</span><span className="flex-1 truncate">{l.name}</span>
                <GlassInput type="number" min="0" step="0.01" value={l.qty} onChange={(e) => setLines((xs) => xs.map((x, j) => (j === i ? { ...x, qty: e.target.value } : x)))} className="h-8 w-24" data-testid={`bom-acc-bulk-qty-${l.code}`} />
                <span className="text-xs text-muted-foreground w-10">{l.unit}</span>
                <Button type="button" variant="ghost" size="icon-sm" onClick={() => setLines((xs) => xs.filter((_, j) => j !== i))} title="Hapus baris" aria-label="Hapus baris"><X className="w-4 h-4" /></Button>
              </div>
            ))}
            <InlineMaterialPicker type="accessory" categories={categories} token={token} onSelect={(m) => setLines((xs) => (xs.some((x) => x.id === m.id) ? xs : [...xs, { id: m.id, code: m.code, name: m.name, type: m.type, unit: m.unit, qty: 1 }]))}>
              <Button type="button" size="sm" variant="outline" data-testid="bom-acc-bulk-pick"><PackagePlus className="w-3.5 h-3.5 mr-1" />Pilih aksesoris</Button>
            </InlineMaterialPicker>
          </div>
      </FormPopup>
    </div>
  );
}

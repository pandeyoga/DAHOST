/**
 * ResepKainEditor — RESEP KAIN baris potongan BOM (keputusan owner 18 Nov 2026: produk lebih dari satu kain).
 *
 * Potongan tetap SATU per baju (satu set semua bagian). Resep = kain apa saja yang dipotong untuk set itu, perannya
 * (Utama, Kombinasi, Kerah, …), dan PERKIRAAN kebutuhan per pcs (boleh kosong). Order Cutting memakai resep ini untuk
 * mengisi baris kain + gulungan otomatis dan menolak potongan yang kainnya belum lengkap; HPP tetap dari kain yang
 * benar-benar dipotong. Penyimpanan & validasi master: `backend/core/resep_kain.py`.
 */
import { Plus, Search, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { MoneyInput } from '@/components/ui/money-input';  // 19 Nov 2026 (kendala R&D): kotak angka menerima koma (1,3789) — MoneyInput, bukan input number peramban
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { InlineMaterialPicker } from './InlineMaterialPicker';

export const PERAN_KAIN = ['Utama', 'Kombinasi', 'Kerah', 'Lengan', 'Furing', 'Kain keras'];

const selCls = 'w-full h-9 px-2 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-sm text-foreground';

/** Baris resep dari server → isian layar (angka jadi teks supaya bisa dikosongkan). */
export const resepKeIsian = (rows) => (rows || []).map((r) => ({
  material_id: r.material_id || null, code: r.code || '', name: r.name || '', role: r.role || 'Utama',
  qty_per_pcs: r.qty_per_pcs == null ? '' : String(r.qty_per_pcs), unit: r.unit || '',
}));

/** Isian layar → payload server (kosong = perkiraan belum diisi). */
export const isianKeResep = (rows) => (rows || []).filter((r) => r.material_id || r.code).map((r) => ({
  material_id: r.material_id || null, code: (r.code || '').toUpperCase(), name: r.name || '', role: r.role || '',
  qty_per_pcs: r.qty_per_pcs === '' || r.qty_per_pcs == null ? null : Number(r.qty_per_pcs), unit: r.unit || '',
}));

/** Ringkasan satu baris teks ("Rib Salur (Utama) 0,35 kg/pcs · Knit 24 (Kerah)"). */
export const ringkasResep = (rows) => (rows || []).map((r) => `${r.code || r.name} (${r.role || 'Utama'})`
  + (Number(r.qty_per_pcs) > 0 ? ` ${Number(r.qty_per_pcs).toLocaleString('id-ID', { maximumFractionDigits: 4 })} ${r.unit}/pcs` : ''))
  .join(' · ');

export function ResepKainEditor({ value, onChange, token, categories = [], testId = 'bom-resep-kain' }) {
  const rows = value || [];
  const set = (idx, patch) => onChange(rows.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  const add = (mat) => {
    if (rows.some((r) => r.material_id === mat.id)) return;
    onChange([...rows, { material_id: mat.id, code: mat.code || '', name: mat.name || '',
      role: rows.length ? 'Kombinasi' : 'Utama', qty_per_pcs: '', unit: mat.unit || '' }]);
  };
  return (
    <div className="space-y-2" data-testid={testId}>
      <p className="text-xs text-muted-foreground">
        Resep kain potongan ini — isi bila satu baju dipotong dari lebih dari satu kain (mis. badan + kerah). Order
        Cutting otomatis menambah semua kain ini; perkiraan per pcs boleh dikosongkan.
      </p>
      {rows.map((r, idx) => (
        <div key={r.material_id || idx} className="grid grid-cols-1 items-center gap-2 sm:grid-cols-[minmax(0,320px)_140px_130px_36px]"
          data-testid={`${testId}-row-${idx}`}>
          <div className="min-w-0 text-sm">
            <span className="tabular-nums">{r.code}</span>
            <span className="text-muted-foreground"> · {r.name}</span>
          </div>
          <SmartNativeSelect className={selCls} value={r.role || 'Utama'} onChange={(e) => set(idx, { role: e.target.value })}
            aria-label="Peran kain" data-testid={`${testId}-role-${idx}`}>
            {[...new Set([...PERAN_KAIN, r.role].filter(Boolean))].map((p) => <option key={p} value={p}>{p}</option>)}
          </SmartNativeSelect>
          <div className="flex items-center gap-1">
            <MoneyInput glass decimals={4} value={r.qty_per_pcs} placeholder="per pcs"
              onChange={(e) => set(idx, { qty_per_pcs: e.target.value })} aria-label="Perkiraan per pcs"
              data-testid={`${testId}-qty-${idx}`} />
            <span className="text-xs text-muted-foreground">{r.unit}</span>
          </div>
          <Button type="button" variant="ghost" size="icon-sm" title="Hapus kain" aria-label="Hapus kain"
            onClick={() => onChange(rows.filter((_, i) => i !== idx))} data-testid={`${testId}-remove-${idx}`}>
            <X className="h-4 w-4" />
          </Button>
        </div>
      ))}
      <InlineMaterialPicker type="fabric" token={token} categories={categories} onSelect={add}>
        <Button type="button" variant="outline" size="sm" data-testid={`${testId}-add`}>
          <Plus className="mr-1 h-4 w-4" /><Search className="mr-1 h-3.5 w-3.5" /> Tambah kain
        </Button>
      </InlineMaterialPicker>
    </div>
  );
}

export default ResepKainEditor;

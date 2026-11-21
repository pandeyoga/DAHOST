import SmartNativeSelect from '@/components/ui/smart-native-select';

// Satuan yang dikenal konverter server (core/bom_uom.py). Satuan "kemasan"
// (rol/pak/karton/bal) hanya bisa dikonversi bila faktornya diisi di master
// material — server akan menandai barisnya bila belum.
export const RND_UNITS = [
  'm', 'cm', 'yard', 'inch',
  'kg', 'gram', 'ons', 'ton',
  'pcs', 'lusin', 'kodi', 'gross', 'pasang', 'lembar', 'set',
  'liter', 'ml',
  // 2026-11-06 (pola P8): roll/pack = ejaan master material
  'roll', 'pack', 'karton', 'bal', 'ikat',
];

export const UOM_STATUS = {
  base: { label: 'satuan dasar', warn: false },
  uom: { label: 'kemasan master', warn: false },
  global: { label: 'konversi otomatis', warn: false },
  fabric: { label: 'via gramasi & lebar', warn: false },
  mismatch: { label: 'satuan tidak bisa dikonversi', warn: true },
  unlinked: { label: 'belum tertaut master material', warn: true },
};

/** `units` (21 Nov 2026): daftar satuan SAH dari master material (`/material-options` → `units`). Bila dikirim,
 *  hanya satuan itu yang bisa dipilih; daftar kosong = bahan belum dipilih. Tanpa `units` → daftar umum. */
export default function RnDUnitSelect({ value, onChange, className = '', testId, units }) {
  const terikat = Array.isArray(units);
  const list = terikat ? units : RND_UNITS;
  const lepas = terikat && value && !units.includes(value);
  return (
    <SmartNativeSelect
      value={value || ''}
      onChange={onChange}
      data-testid={testId}
      searchable
      searchPlaceholder="Cari satuan..."
      className={`w-full text-sm ${className}`}
    >
      <option value="">{terikat && !units.length ? 'Pilih bahan dulu' : 'Satuan…'}</option>
      {lepas && <option value={value}>{`${value} (tidak sah untuk bahan ini)`}</option>}
      {list.map((u) => <option key={u} value={u}>{u}</option>)}
    </SmartNativeSelect>
  );
}

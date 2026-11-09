/**
 * cuttingLines — bentuk baris order cutting di layar (keputusan owner 10 Nov 2026):
 * satu order = beberapa KAIN (masing-masing beberapa gulungan) × beberapa HASIL (model · varian · target pcs).
 * HPP potongan per pcs = total biaya kain ÷ total pcs hasil semua baris (sama untuk semua baris) — cermin
 * `backend/core/cutting_lines.py`. Tautan gulungan → hasil = ketelusuran, bukan dasar HPP.
 */

let seq = 0;
/** Kunci baris di layar (bukan id server). */
export const lineKey = () => `b${Date.now().toString(36)}${(seq += 1)}`;

export const newInputLine = () => ({ key: lineKey(), input_material_id: '', planned_input_qty: '', roll_ids: [] });

export const newOutputLine = (rollIds = []) => ({
  key: lineKey(), model_id: '', variant_id: '', size_id: '', po_item_id: '', output_color: '',
  planned_output_qty: '', roll_ids: [...rollIds],
});

/** Sisa satu gulungan (dari `/cutting/rolls`). */
export const rollRemaining = (r) =>
  Number(r?.remaining ?? (r?.uom === 'kg' ? r?.remaining_kg : r?.remaining_m) ?? 0);

/** Label varian yang bisa dibedakan: warna · ukuran · SKU. */
export const variantLabel = (v) =>
  [v?.color_name || v?.color || '-', v?.size_code || v?.size || '-', v?.sku].filter(Boolean).join(' · ');

/** "Model · warna · ukuran · SKU" — sama dengan `cutting_lines.output_label` di server. */
export const outputLabel = (o) =>
  [o?.style_name || o?.model_name || o?.model_code || 'Hasil', o?.output_color, o?.output_size, o?.variant_sku]
    .filter(Boolean).join(' · ');

/** Ringkasan varian per model ({model_id: "M/XL · 22 warna"}) — supaya dua model bernama sama bisa dibedakan. */
export function summarizeVariantsByModel(rows) {
  const acc = {};
  (rows || []).forEach((v) => {
    if (!v?.model_id || v.active === false) return;
    const a = acc[v.model_id] || (acc[v.model_id] = { sizes: new Set(), colors: new Set() });
    if (v.size_code) a.sizes.add(v.size_code);
    if (v.color_id || v.color_name) a.colors.add(v.color_id || v.color_name);
  });
  const out = {};
  Object.entries(acc).forEach(([mid, a]) => {
    out[mid] = [[...a.sizes].join('/'), a.colors.size ? `${a.colors.size} warna` : ''].filter(Boolean).join(' · ');
  });
  return out;
}

/**
 * Perkiraan HPP order dari rencana: Σ(rencana kain × harga kain) ÷ Σ target pcs.
 * `priceOf(input)` → harga satuan kain (0 = belum ada harga dari pembelian).
 */
export function estimateHpp(inputs, outputs, priceOf) {
  let total = 0;
  const missing = [];
  (inputs || []).forEach((i) => {
    const q = Number(i.planned_input_qty || 0);
    const p = Number(priceOf(i) || 0);
    if (q > 0 && p <= 0) missing.push(i);
    total += q * p;
  });
  const pcs = (outputs || []).reduce((s, o) => s + Number(o.planned_output_qty || 0), 0);
  return { total, pcs, perPcs: pcs > 0 ? total / pcs : 0, missing };
}

/** Kain per satuan ("24 kg · 10 m") — kg, yard, meter tidak dijumlah jadi satu angka. */
export function qtyPerUnit(rows, key, fmt) {
  const acc = {};
  (rows || []).forEach((r) => {
    const u = String(r.input_unit || r.unit || '').toLowerCase() || '-';
    acc[u] = (acc[u] || 0) + Number(r[key] || 0);
  });
  return Object.entries(acc).map(([u, q]) => `${fmt(q)} ${u}`).join(' · ');
}

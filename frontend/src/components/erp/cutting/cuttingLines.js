/**
 * cuttingLines — bentuk baris order cutting di layar (keputusan owner 10 Nov 2026):
 * satu order = beberapa KAIN (masing-masing beberapa gulungan) × beberapa HASIL (model · varian · target pcs).
 * HPP potongan per pcs = total biaya kain ÷ total pcs hasil semua baris (sama untuk semua baris; sejak 19 Nov produk
 * ber-resep kain: nilai tiap kain dibagi ke hasil yang memakainya, lihat `bagiNilaiPerKain`) — cermin
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

/**
 * 18 Nov 2026 (owner: produk lebih dari satu kain) — Σ kebutuhan kain resep BOM semua baris hasil.
 * `recipes` = resep tiap baris hasil (`fabric_recipe` dari `/cutting/bom-requirement`). Hasil:
 * [{material_id, code, name, unit, roles, qty, unknown}] — `unknown` = ada hasil yang perkiraan/pcs-nya belum diisi.
 */
export function kebutuhanResep(recipes) {
  const acc = new Map();
  (recipes || []).forEach((rows) => (rows || []).forEach((r) => {
    if (!r?.material_id) return;
    const a = acc.get(r.material_id) || {
      material_id: r.material_id, code: r.code, name: r.name, unit: r.unit, roles: [], qty: 0, unknown: false };
    if (r.role && !a.roles.includes(r.role)) a.roles.push(r.role);
    if (Number(r.qty_total) > 0) a.qty = Math.round((a.qty + Number(r.qty_total)) * 10000) / 10000;
    else a.unknown = true;
    acc.set(r.material_id, a);
  }));
  return [...acc.values()];
}

/** Baris hasil memakai kain ini? (hasil tanpa resep = kainnya tidak diketahui → dianggap memakai). */
export const pakaiKain = (recipe, materialId) =>
  !(recipe || []).length || recipe.some((r) => r.material_id === materialId);

/** Gulungan FIFO (urut nomor roll dari server) sampai sisa terpilih ≥ kebutuhan. Kebutuhan 0 = tidak memilih. */
export function pilihGulunganFifo(items, need) {
  const want = Number(need || 0);
  if (!(want > 0)) return [];
  const out = [];
  let sum = 0;
  (items || []).forEach((r) => {
    if (sum + 0.0001 >= want) return;
    const left = rollRemaining(r);
    if (left <= 0) return;
    out.push(r.id);
    sum += left;
  });
  return out;
}

/**
 * Cermin `backend/core/resep_kain.py::alokasi_nilai` (19 Nov 2026): nilai tiap kain dibagi ke baris hasil yang
 * memakainya menurut resep kain. Baris tanpa resep ikut semua kain; kain di luar resep mana pun dibagi ke semua baris;
 * bobot = pcs × perkiraan/pcs bila semua yang berhak punya perkiraan untuk kain itu, selain itu pcs.
 * `nilaiKain` = {material_id: nilai}, `baris` = [{qty}], `resep` = resep tiap baris (sejajar). Hasil: nilai per baris.
 */
export function bagiNilaiPerKain(nilaiKain, baris, resep) {
  const n = (baris || []).length;
  const out = Array(n).fill(0);
  const byLine = Array.from({ length: n }, (_, i) => new Map(((resep || [])[i] || [])
    .filter((r) => r?.material_id).map((r) => [r.material_id, r])));
  const live = [...Array(n).keys()].filter((i) => Number(baris[i]?.qty || 0) > 0);
  Object.entries(nilaiKain || {}).forEach(([fid, v]) => {
    const value = Number(v || 0);
    if (!(value > 0) || !live.length) return;
    let hak = live.filter((i) => byLine[i].size === 0 || byLine[i].has(fid));
    if (!hak.length) hak = live;
    const pakaiQty = hak.every((i) => byLine[i].has(fid) && Number(byLine[i].get(fid).qty_per_pcs) > 0);
    const w = hak.map((i) => Number(baris[i].qty) * (pakaiQty ? Number(byLine[i].get(fid).qty_per_pcs) : 1));
    const tw = w.reduce((s, x) => s + x, 0);
    if (!(tw > 0)) return;
    hak.forEach((i, k) => { out[i] += (value * w[k]) / tw; });
  });
  return out;
}

/** HPP/pcs per baris hasil dari nilai kain (resep kain) — `null` bila tidak ada baris ber-resep (aturan lama: rata). */
export function hppPerBaris(nilaiKain, baris, resep) {
  if (!(resep || []).some((r) => (r || []).length)) return null;
  const nilai = bagiNilaiPerKain(nilaiKain, baris, resep);
  return nilai.map((v, i) => (Number(baris[i]?.qty) > 0 ? v / Number(baris[i].qty) : 0));
}

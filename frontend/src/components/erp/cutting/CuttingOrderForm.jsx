/**
 * CuttingOrderForm — popup "Buat order cutting" / "Ubah order cutting" (keputusan owner 10 Nov 2026:
 * "cutting bisa lebih dari satu", "roll kain juga bisa lebih dari satu, model lebih dari satu").
 *
 *   1. Kain & gulungan — beberapa kain dari master, tiap kain beberapa gulungan (centang), sisa tiap gulungan,
 *      rencana pemakaian per kain (bisa diisi dari BOM hasil potongannya).
 *   2. Hasil potongan — tabel baris: model, varian (warna · ukuran · SKU), target pcs, baris PO (opsional), dan
 *      "Gulungan dipakai" (gulungan mana dipakai untuk hasil ini — ketelusuran, bukan dasar HPP).
 *   3. Ringkasan — total pcs & perkiraan HPP potongan per pcs = total biaya kain ÷ total pcs (sama untuk semua baris).
 *
 * Aturan lama tetap: kain wajib dari master; gulungan wajib untuk kain yang dilacak per gulungan (boleh ditunjuk
 * saat lapor progres); peringatan stok kosong; model wajib dari Master Produk; ukuran wajib.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Plus, Trash2, AlertCircle, Scissors } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { EmptyState, Notice } from '../moduleAtoms';
import { cuttingApi, fmtNum, fmtRp } from './cuttingApi';
import { fmtQty } from '../warehouse/rollLines';
import {
  newInputLine, newOutputLine, rollRemaining, variantLabel, summarizeVariantsByModel, estimateHpp,
} from './cuttingLines';

/** Angka pemakaian bahan tanpa nol berekor ("6" bukan "6,0000"). */
const fmtQtyTrim = (v) => Number(v || 0).toLocaleString('id-ID', { maximumFractionDigits: 4 });

const EMPTY_ROLLS = { items: [], roll_required: false, total_remaining: 0, uom: '' };

const matLabel = (m) => `${m.code} · ${m.name}`
  + (m.color && !String(m.name || '').toLowerCase().includes(String(m.color).toLowerCase()) ? ` · ${m.color}` : '')
  + ` — stok ${fmtNum(m.stock_qty, 2)} ${m.unit || ''}`
  + (m.best_location_name ? ` @ ${m.best_location_name}` : ' (belum ada stok)');

const stockAt = (m, locId) => Number(((m?.stock_locations || []).find((l) => l.location_id === locId) || {}).qty || 0);

export default function CuttingOrderForm({ open, onClose, token, order = null, onSaved, onNavigate }) {
  const editing = !!order;
  const [materials, setMaterials] = useState([]);
  const [locations, setLocations] = useState([]);
  const [models, setModels] = useState([]);
  // {model_id: "XL · 22 warna"} — label model memuat ukuran & jumlah warna (dua model bisa bernama sama).
  const [modelSummary, setModelSummary] = useState({});
  const [sizes, setSizes] = useState([]);
  const [onlyInStock, setOnlyInStock] = useState(true);
  const [form, setForm] = useState({ location_id: '', notes: '', inputs: [newInputLine()], outputs: [newOutputLine()] });
  const [rollsByMat, setRollsByMat] = useState({});
  const [variantsByModel, setVariantsByModel] = useState({});
  const [poLinesByModel, setPoLinesByModel] = useState({});
  // Kebutuhan bahan menurut BOM per baris hasil (model + ukuran) — rencana kain tidak ditebak.
  const [bomByKey, setBomByKey] = useState({});
  const bomSig = useRef({});
  const [saving, setSaving] = useState(false);
  // Model baru (Master Produk) untuk satu baris hasil — menggantikan form ini sementara.
  const [newModelFor, setNewModelFor] = useState(null);
  const [newModel, setNewModel] = useState({ code: '', name: '', category_id: '' });
  const [categories, setCategories] = useState([]);
  const [savingModel, setSavingModel] = useState(false);

  const authHdr = useCallback(
    () => ({ Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` }), [token]);

  const loadRolls = useCallback(async (mid) => {
    if (!mid) return;
    try {
      // FASE H-6: respons = {items, roll_required, total_remaining, uom} — layar tahu gulungan WAJIB atau tidak.
      const res = await cuttingApi('GET', `/rolls?material_id=${mid}`, token);
      const items = Array.isArray(res) ? res : (res?.items || []);
      setRollsByMat((m) => ({ ...m, [mid]: {
        items, roll_required: !!res?.roll_required, total_remaining: Number(res?.total_remaining || 0),
        uom: res?.uom || items[0]?.uom || '' } }));
    } catch {
      setRollsByMat((m) => ({ ...m, [mid]: EMPTY_ROLLS }));
    }
  }, [token]);

  const loadModelData = useCallback(async (id) => {
    if (!id) return;
    cuttingApi('GET', `/po-lines?model_id=${id}`, token)
      .then((d) => setPoLinesByModel((m) => ({ ...m, [id]: Array.isArray(d) ? d : [] })))
      .catch(() => setPoLinesByModel((m) => ({ ...m, [id]: [] })));
    try {
      const r = await fetch(`/api/rahaza/models/${id}/variants`, { headers: authHdr() });
      const d = await r.json();
      // 2026-11-06 (pola P1): server membalas {model, variants, count}; saringan model_id = pengaman kedua.
      const list = (Array.isArray(d) ? d : (d?.variants || []))
        .filter((v) => v.active !== false && (!v.model_id || v.model_id === id));
      setVariantsByModel((m) => ({ ...m, [id]: list }));
    } catch {
      setVariantsByModel((m) => ({ ...m, [id]: [] }));
    }
  }, [token, authHdr]);

  const loadModels = useCallback(async () => {
    try {
      const [r, rv] = await Promise.all([
        fetch('/api/rahaza/models', { headers: authHdr() }),
        // ringkasan ukuran & warna per model untuk label pilihan model (gagal ⇒ label kode · nama saja)
        fetch('/api/rahaza/variants', { headers: authHdr() }).catch(() => null),
      ]);
      const d = await r.json();
      setModels((Array.isArray(d) ? d : ((d && d.items) || [])).filter((m) => m.active !== false));
      if (rv && rv.ok) {
        const dv = await rv.json();
        setModelSummary(summarizeVariantsByModel(Array.isArray(dv) ? dv : (dv?.variants || (dv && dv.items) || [])));
      }
    } catch {
      setModels([]);
    }
  }, [authHdr]);

  // ── Buka form: isi dari order (ubah) atau kosong (buat) ──
  useEffect(() => {
    if (!open) return undefined;
    let alive = true;
    const ins = order?.inputs?.length
      ? order.inputs.map((i) => ({ ...newInputLine(), input_material_id: i.input_material_id || '',
        planned_input_qty: String(i.planned_input_qty ?? ''), roll_ids: (i.roll_ids || []).map((r) => r.roll_id) }))
      : [newInputLine()];
    const outs = order?.outputs?.length
      ? order.outputs.map((o) => ({ ...newOutputLine(o.roll_ids || []), model_id: o.model_id || '',
        variant_id: o.variant_id || '', size_id: o.size_id || '', po_item_id: o.po_item_id || '',
        output_color: o.output_color || '', planned_output_qty: String(o.planned_output_qty ?? '') }))
      : [newOutputLine()];
    setForm({ location_id: order?.location_id || '', notes: order?.notes || '', inputs: ins, outputs: outs });
    setOnlyInStock(!order);
    setBomByKey({});
    bomSig.current = {};
    (async () => {
      try {
        const [mats, locs] = await Promise.all([
          cuttingApi('GET', '/input-materials', token), cuttingApi('GET', '/locations', token)]);
        if (!alive) return;
        setMaterials(mats);
        setLocations(locs);
      } catch (e) {
        toast.error(`Gagal memuat master kain: ${e.message}`);
      }
      loadModels();
      ins.forEach((i) => loadRolls(i.input_material_id));
      [...new Set(outs.map((o) => o.model_id).filter(Boolean))].forEach((mid) => loadModelData(mid));
      try {
        const r = await fetch('/api/rahaza/sizes', { headers: authHdr() });
        const d = await r.json();
        if (alive) setSizes((Array.isArray(d) ? d : ((d && d.items) || [])).filter((s) => s.active !== false));
      } catch { if (alive) setSizes([]); }
    })();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, order?.id]);

  const matById = useMemo(() => Object.fromEntries(materials.map((m) => [m.id, m])), [materials]);
  // Stok disimpan PER GUDANG — pilihan kain menampilkan gudang yang benar-benar memegang stok.
  const materialOptions = useMemo(
    () => (onlyInStock ? materials.filter((m) => Number(m.stock_qty || 0) > 0) : materials), [materials, onlyInStock]);

  const setInput = (key, patch) => setForm((f) => ({
    ...f, inputs: f.inputs.map((i) => (i.key === key ? { ...i, ...patch } : i)) }));
  const setOutput = (key, patch) => setForm((f) => ({
    ...f, outputs: f.outputs.map((o) => (o.key === key ? { ...o, ...patch } : o)) }));

  // Semua gulungan yang dicentang di bagian kain — pilihan "Gulungan dipakai" tiap baris hasil.
  const pickedRolls = useMemo(() => form.inputs.flatMap((i) => {
    const m = matById[i.input_material_id];
    return ((rollsByMat[i.input_material_id] || EMPTY_ROLLS).items || [])
      .filter((r) => i.roll_ids.includes(r.id)).map((r) => ({ ...r, material_code: m?.code || '' }));
  }), [form.inputs, rollsByMat, matById]);

  const onPickMaterial = (key, id) => {
    const m = matById[id];
    setForm((f) => {
      const dropped = (f.inputs.find((i) => i.key === key) || {}).roll_ids || [];
      return {
        ...f,
        location_id: f.location_id || m?.best_location_id || '',
        inputs: f.inputs.map((i) => (i.key === key ? { ...i, input_material_id: id, roll_ids: [] } : i)),
        outputs: f.outputs.map((o) => ({ ...o, roll_ids: o.roll_ids.filter((r) => !dropped.includes(r)) })),
      };
    });
    loadRolls(id);
  };

  // Gulungan baru dicentang ⇒ bawaannya dipakai semua baris hasil (hapus centang di baris yang tidak memakainya).
  const toggleRoll = (key, rid) => setForm((f) => {
    const has = (f.inputs.find((i) => i.key === key) || {}).roll_ids?.includes(rid);
    return {
      ...f,
      inputs: f.inputs.map((i) => (i.key !== key ? i
        : { ...i, roll_ids: has ? i.roll_ids.filter((x) => x !== rid) : [...i.roll_ids, rid] })),
      outputs: f.outputs.map((o) => ({
        ...o, roll_ids: has ? o.roll_ids.filter((x) => x !== rid) : [...new Set([...o.roll_ids, rid])] })),
    };
  });

  const toggleOutRoll = (key, rid) => setForm((f) => ({
    ...f,
    outputs: f.outputs.map((o) => (o.key !== key ? o
      : { ...o, roll_ids: o.roll_ids.includes(rid) ? o.roll_ids.filter((x) => x !== rid) : [...o.roll_ids, rid] })),
  }));

  const addInput = () => setForm((f) => ({ ...f, inputs: [...f.inputs, newInputLine()] }));
  const removeInput = (key) => setForm((f) => {
    const dropped = (f.inputs.find((i) => i.key === key) || {}).roll_ids || [];
    return {
      ...f,
      inputs: f.inputs.filter((i) => i.key !== key),
      outputs: f.outputs.map((o) => ({ ...o, roll_ids: o.roll_ids.filter((r) => !dropped.includes(r)) })),
    };
  });
  const addOutput = () => setForm((f) => ({
    ...f, outputs: [...f.outputs, newOutputLine(f.inputs.flatMap((i) => i.roll_ids))] }));
  const removeOutput = (key) => setForm((f) => ({ ...f, outputs: f.outputs.filter((o) => o.key !== key) }));

  // 2026-11-07: ganti model = varian, ukuran, DAN baris PO ikut dikosongkan.
  const onPickModel = (key, id) => {
    setOutput(key, { model_id: id, variant_id: '', size_id: '', po_item_id: '', output_color: '' });
    if (id) loadModelData(id);
  };

  const onPickVariant = (o, vid) => {
    const v = (variantsByModel[o.model_id] || []).find((x) => x.id === vid);
    // Baris PO berukuran lain dari varian yang dipilih ⇒ tautan PO dilepas (server menolak campuran itu).
    const ln = (poLinesByModel[o.model_id] || []).find((x) => x.id === o.po_item_id);
    const dropPo = !!(v && ln && ln.size_id && v.size_id && ln.size_id !== v.size_id);
    setOutput(o.key, { variant_id: vid, size_id: v?.size_id || '', output_color: v?.color_name || v?.color || '',
      po_item_id: dropPo ? '' : o.po_item_id });
  };

  // Baris PO dipilih → ukuran (dan varian bila ada) mengikuti baris PO itu.
  const pickPoLine = (o, pid) => {
    const ln = (poLinesByModel[o.model_id] || []).find((x) => x.id === pid);
    const vs = variantsByModel[o.model_id] || [];
    if (!ln) { setOutput(o.key, { po_item_id: pid }); return; }
    const pv = ln.rahaza_variant_id ? vs.find((v) => v.id === ln.rahaza_variant_id) : null;
    if (pv) {
      setOutput(o.key, { po_item_id: pid, variant_id: pv.id, size_id: pv.size_id || '',
        output_color: pv.color_name || pv.color || '' });
      return;
    }
    const cur = vs.find((v) => v.id === o.variant_id);
    const dropV = !!(cur && cur.size_id && ln.size_id && cur.size_id !== ln.size_id);
    setOutput(o.key, { po_item_id: pid, size_id: ln.size_id || o.size_id,
      ...(dropV ? { variant_id: '', output_color: ln.color || '' } : {}) });
  };

  // ── Kebutuhan menurut BOM per baris hasil (dimuat ulang hanya bila model/ukuran/target barisnya berubah) ──
  useEffect(() => {
    if (!open) return undefined;
    const t = setTimeout(() => {
      const single = form.inputs.length === 1 ? form.inputs[0].input_material_id : '';
      form.outputs.forEach((o) => {
        const v = (variantsByModel[o.model_id] || []).find((x) => x.id === o.variant_id);
        const sid = v?.size_id || o.size_id || '';
        if (!o.model_id || !sid) return;
        const p = new URLSearchParams({ model_id: o.model_id, size_id: sid });
        if (o.variant_id) p.set('variant_id', o.variant_id);
        if (Number(o.planned_output_qty) > 0) p.set('qty_pcs', String(o.planned_output_qty));
        if (single) p.set('input_material_id', single);
        const sig = p.toString();
        if (bomSig.current[o.key] === sig) return;
        bomSig.current[o.key] = sig;
        cuttingApi('GET', `/bom-requirement?${sig}`, token)
          .then((d) => { if (bomSig.current[o.key] === sig) setBomByKey((m) => ({ ...m, [o.key]: d })); })
          .catch(() => setBomByKey((m) => ({ ...m, [o.key]: null })));
      });
    }, 300);
    return () => clearTimeout(t);
  }, [open, form.inputs, form.outputs, variantsByModel, token]);

  /** Σ kebutuhan kain menurut BOM semua baris hasil untuk satu kain. */
  const bomNeedFor = (i) => {
    let q = 0;
    let unit = '';
    form.outputs.forEach((o) => {
      const f = bomByKey[o.key]?.fabric;
      if (f && f.material_id === i.input_material_id && Number(f.qty_total) > 0) {
        q += Number(f.qty_total);
        unit = f.unit || unit;
      }
    });
    return { q: Math.round(q * 10000) / 10000, unit };
  };

  // Gudang: yang memegang stok kain terpilih dulu, lalu gudang lain (stok 0).
  const chosenMats = useMemo(
    () => form.inputs.map((i) => matById[i.input_material_id]).filter(Boolean), [form.inputs, matById]);
  const locationOptions = useMemo(() => {
    const names = {};
    chosenMats.forEach((m) => (m.stock_locations || []).forEach((l) => { names[l.location_id] = l.location_name; }));
    locations.forEach((l) => { if (!names[l.id]) names[l.id] = l.name; });
    const ids = Object.keys(names).sort((a, b) => {
      const sa = chosenMats.reduce((s, m) => s + stockAt(m, a), 0);
      const sb = chosenMats.reduce((s, m) => s + stockAt(m, b), 0);
      return sb - sa;
    });
    return ids.map((id) => ({
      id,
      label: `${names[id]}${chosenMats.length
        ? ` — ${chosenMats.map((m) => `${m.code} ${fmtNum(stockAt(m, id), 2)} ${m.unit || ''}`).join(' · ')}` : ''}`,
    }));
  }, [locations, chosenMats]);

  const est = useMemo(
    () => estimateHpp(form.inputs.filter((i) => i.input_material_id), form.outputs,
      (i) => matById[i.input_material_id]?.unit_cost), [form.inputs, form.outputs, matById]);
  const unlinked = form.outputs.length > 1
    ? pickedRolls.filter((r) => !form.outputs.some((o) => o.roll_ids.includes(r.id))) : [];

  const submit = async () => {
    if (!form.location_id) { toast.error('Pilih gudang sumber kain dulu.'); return; }
    const ins = form.inputs.filter((i) => i.input_material_id);
    if (!ins.length) { toast.error('Pilih material kain dulu.'); return; }
    if (ins.some((i) => !(Number(i.planned_input_qty) > 0))) {
      toast.error('Rencana pemakaian tiap kain harus > 0.');
      return;
    }
    const bad = form.outputs.map((o, n) => {
      const pre = form.outputs.length > 1 ? `Hasil baris ${n + 1}: ` : '';
      if (!o.model_id) return `${pre}pilih model dari Master Produk dulu.`;
      // 2026-11-06 (Tahap 2): ukuran WAJIB — tanpa ukuran potongan tidak dipakai BOM mana pun.
      if (!o.variant_id && !o.size_id && !o.po_item_id) return `${pre}pilih ukuran dulu (lewat varian, ukuran, atau baris PO).`;
      if (!(Number(o.planned_output_qty) > 0)) return `${pre}target potongan harus > 0.`;
      return '';
    }).find(Boolean);
    if (bad) { toast.error(bad); return; }
    setSaving(true);
    try {
      const body = {
        location_id: form.location_id,
        notes: form.notes,
        inputs: ins.map((i) => ({ input_material_id: i.input_material_id,
          planned_input_qty: Number(i.planned_input_qty), roll_ids: i.roll_ids })),
        outputs: form.outputs.map((o) => ({ model_id: o.model_id, variant_id: o.variant_id, size_id: o.size_id,
          po_item_id: o.po_item_id, output_color: o.output_color,
          planned_output_qty: Number(o.planned_output_qty), roll_ids: o.roll_ids })),
      };
      const saved = editing
        ? await cuttingApi('PUT', `/orders/${order.id}`, token, body)
        : await cuttingApi('POST', '/orders', token, body);
      toast.success(editing ? `Cutting ${saved.number} diubah.` : `Cutting ${saved.number} dibuat (draf).`);
      onSaved?.(saved);
    } catch (e) {
      toast.error(e.message, { duration: 9000 });
    } finally {
      setSaving(false);
    }
  };

  const openNewModel = async (key) => {
    setNewModelFor(key);
    if (categories.length) return;
    try {
      const r = await fetch('/api/rahaza/product-categories', { headers: authHdr() });
      const d = await r.json();
      setCategories((Array.isArray(d) ? d : (d?.categories || [])).filter((c) => c.active !== false));
    } catch { setCategories([]); }
  };

  const createModel = async () => {
    if (!newModel.name.trim()) { toast.error('Nama model wajib diisi.'); return; }
    if (!newModel.code.trim() && !newModel.category_id) {
      toast.error('Pilih kategori produk (kode model dibuat dari kategori), atau isi kode model sendiri.');
      return;
    }
    setSavingModel(true);
    try {
      const r = await fetch('/api/rahaza/models', {
        method: 'POST',
        headers: { ...authHdr(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newModel.name.trim(), code: newModel.code.trim(),
          ...(newModel.category_id ? { category_id: newModel.category_id } : {}) }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || d.error || `HTTP ${r.status}`);
      toast.success(`Model ${d.code || d.name} ditambahkan ke master.`);
      const key = newModelFor;
      setNewModelFor(null);
      setNewModel({ code: '', name: '', category_id: '' });
      await loadModels();
      setModels((prev) => (prev.some((x) => x.id === d.id) ? prev : [...prev, d]));
      if (key) onPickModel(key, d.id);
    } catch (e) {
      toast.error(`Gagal membuat model: ${e.message}`);
    } finally {
      setSavingModel(false);
    }
  };

  // ── Bagian 1: satu baris kain (fungsi render biasa, bukan komponen — isian tidak kehilangan fokus) ──
  const renderInput = (i, n) => {
    const m = matById[i.input_material_id];
    const rm = rollsByMat[i.input_material_id] || EMPTY_ROLLS;
    const others = form.inputs.filter((x) => x.key !== i.key).map((x) => x.input_material_id);
    const opts = materialOptions.filter((x) => !others.includes(x.id));
    if (m && !opts.some((x) => x.id === m.id)) opts.unshift(m);
    const picked = rm.items.filter((r) => i.roll_ids.includes(r.id));
    const pickedSum = picked.reduce((s, r) => s + rollRemaining(r), 0);
    const short = picked.length > 0 && pickedSum + 0.0001 < Number(i.planned_input_qty || 0);
    const need = bomNeedFor(i);
    return (
      <div key={i.key} className="space-y-3 rounded-lg border border-[var(--glass-border)] p-3"
        data-testid={`cutting-input-row-${n}`}>
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs font-medium text-muted-foreground">Kain {n + 1}</p>
          {form.inputs.length > 1 && (
            <Button type="button" size="icon-sm" variant="ghost" onClick={() => removeInput(i.key)}
              title="Hapus kain ini" aria-label="Hapus kain ini" data-testid={`cutting-input-remove-${n}`}><Trash2 /></Button>
          )}
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Isian label="Material kain" wajib
            petunjuk={m
              ? `Total stok ${fmtNum(m.stock_qty, 2)} ${m.unit} · ${m.roll_count} roll aktif`
                + (form.location_id ? ` · di gudang terpilih ${fmtNum(stockAt(m, form.location_id), 2)} ${m.unit}` : '')
              : 'Kain diambil dari master material Gudang.'}>
            <SmartNativeSelect value={i.input_material_id} onChange={(e) => onPickMaterial(i.key, e.target.value)}
              className="h-9 w-full" searchable searchPlaceholder="Cari kode, nama, atau warna kain…"
              data-testid={`cutting-input-material-${n}`}>
              <option value="">— Pilih kain —</option>
              {opts.map((x) => <option key={x.id} value={x.id}>{matLabel(x)}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label={`Rencana pemakaian (${m?.unit || 'satuan'})`} wajib
            petunjuk={need.q > 0 ? `Kebutuhan menurut BOM hasil potongan: ${fmtQtyTrim(need.q)} ${need.unit}.` : undefined}>
            <div className="flex gap-2">
              <Input type="number" step="0.01" min="0" value={i.planned_input_qty}
                onChange={(e) => setInput(i.key, { planned_input_qty: e.target.value })}
                data-testid={`cutting-planned-input-${n}`} />
              {need.q > 0 && (
                <Button type="button" variant="outline" className="shrink-0"
                  onClick={() => setInput(i.key, { planned_input_qty: String(need.q) })}
                  data-testid={`cutting-use-bom-qty-${n}`}>Pakai angka BOM</Button>
              )}
            </div>
          </Isian>
        </div>
        {m && Number(m.stock_qty || 0) <= 0 && (
          <Notice tone="warning" icon={AlertCircle}>
            Kain ini belum punya stok di gudang mana pun. Order bisa disimpan sebagai draf, tetapi tidak bisa dimulai
            sebelum penerimaan barang dicatat di Portal Gudang.
          </Notice>
        )}
        {m && rm.roll_required && rm.items.length === 0 && (
          <Notice tone="danger" icon={AlertCircle} testId={`cutting-no-rolls-warning-${n}`}>
            Kain ini <b>belum punya gulungan</b> di sistem, jadi order tidak bisa disimpan — tidak akan bisa dibuktikan
            gulungan mana yang dipotong. Terbitkan gulungannya dulu di <b>Gudang › Roll Kain › tab “Penerimaan tanpa roll”</b>,
            atau isi Rincian Roll saat Penerimaan Barang.
          </Notice>
        )}
        {m && rm.roll_required && rm.items.length > 0 && (
          <Isian label={`Gulungan (${rm.items.length} tersedia · sisa ${fmtQty(rm.total_remaining)} ${rm.uom})`}
            petunjuk="Centang gulungan yang akan dipotong. Boleh juga dipilih saat lapor progres — progres tidak bisa dicatat tanpa menunjuk gulungan.">
            <div className="max-h-40 divide-y divide-[var(--glass-border)] overflow-y-auto rounded-lg border border-[var(--glass-border)]"
              data-testid={`cutting-roll-picker-${n}`}>
              {rm.items.map((r) => {
                const checked = i.roll_ids.includes(r.id);
                return (
                  <label key={r.id} className="flex cursor-pointer items-center gap-2 px-3 py-2 text-sm hover:bg-foreground/5"
                    data-testid={`cutting-roll-option-${r.roll_no}`}>
                    <Checkbox checked={checked} onCheckedChange={() => toggleRoll(i.key, r.id)} />
                    <span className="tabular-nums text-foreground">{r.roll_no}</span>
                    <span className="text-xs text-muted-foreground">
                      sisa {fmtQty(rollRemaining(r))} {r.uom}
                      {(r.color_lot || r.color) ? ` · lot ${r.color_lot || r.color}` : ''}
                      {r.location_name ? ` · ${r.location_name}` : ''}
                      {r.source_receipt_number ? ` · dari ${r.source_receipt_number}` : ''}
                    </span>
                  </label>
                );
              })}
            </div>
            {picked.length > 0 && (
              <p className={`mt-1 text-xs ${short ? 'text-[hsl(var(--warning-text))]' : 'text-muted-foreground'}`}
                data-testid={`cutting-roll-picked-summary-${n}`}>
                {picked.length} gulungan dipilih · sisa terpilih {fmtQty(pickedSum)} {rm.uom}
                {Number(i.planned_input_qty) > 0 && ` · rencana pakai ${fmtQty(i.planned_input_qty)} ${m.unit}`}
                {short && ' — sisa gulungan kurang dari rencana; tambah gulungan atau turunkan rencana.'}
              </p>
            )}
          </Isian>
        )}
      </div>
    );
  };

  const bomInfo = (bom) => {
    if (!bom) return null;
    if (bom.fabric) {
      return (
        <p className="mt-1 text-xs text-muted-foreground">
          BOM: {bom.fabric.code || bom.fabric.name} {fmtQtyTrim(bom.fabric.qty_per_pcs)} {bom.fabric.unit}/pcs
          {Number(bom.fabric.qty_total) > 0 && ` = ${fmtQtyTrim(bom.fabric.qty_total)} ${bom.fabric.unit}`}
        </p>
      );
    }
    if (bom.panel) {
      return <p className="mt-1 text-xs text-muted-foreground">Potongan BOM: {bom.panel.code}</p>;
    }
    const g = (bom.gaps || [])[0];
    return g ? (
      <p className="mt-1 text-xs text-[hsl(var(--warning-text))]">
        {g.message}
        {g.target && g.target !== 'cutting-orders' && onNavigate && (
          <Button type="button" variant="link" size="sm" className="ml-1 h-auto p-0 text-xs"
            onClick={() => onNavigate(g.target)}>{g.action || 'Perbaiki'}</Button>
        )}
      </p>
    ) : null;
  };

  const renderOutRolls = (o) => {
    if (!pickedRolls.length) return <span className="text-xs text-muted-foreground">Centang gulungan di bagian kain</span>;
    if (form.outputs.length === 1) {
      return <span className="text-xs text-muted-foreground">Semua gulungan ({pickedRolls.map((r) => r.roll_no).join(', ')})</span>;
    }
    return (
      <div className="flex flex-col gap-1">
        {pickedRolls.map((r) => (
          <label key={r.id} className="inline-flex cursor-pointer items-center gap-1.5 text-xs">
            <Checkbox checked={o.roll_ids.includes(r.id)} onCheckedChange={() => toggleOutRoll(o.key, r.id)}
              data-testid={`cutting-output-roll-${r.roll_no}`} />
            <span className="tabular-nums text-foreground">{r.roll_no}</span>
            <span className="text-muted-foreground">{r.material_code}</span>
          </label>
        ))}
      </div>
    );
  };

  // ── Bagian 2: satu baris hasil ──
  const renderOutput = (o, n) => {
    const vs = variantsByModel[o.model_id] || [];
    const pls = poLinesByModel[o.model_id] || [];
    const pl = pls.find((x) => x.id === o.po_item_id);
    const vopts = pl?.size_id ? vs.filter((v) => !v.size_id || v.size_id === pl.size_id) : vs;
    const bom = bomByKey[o.key];
    const bomSizes = new Set((bom?.other_sizes_with_bom || []).map((s) => s.size_id));
    return (
      <TableRow key={o.key} data-testid={`cutting-output-row-${n}`}>
        <TableCell className="align-top tabular-nums text-muted-foreground">{n + 1}</TableCell>
        <TableCell className="align-top">
          <div className="flex gap-1.5">
            <SmartNativeSelect value={o.model_id} onChange={(e) => onPickModel(o.key, e.target.value)}
              className="h-9 w-full" wrapperClassName="min-w-0 flex-1" searchable
              searchPlaceholder="Cari kode atau nama model…" data-testid={`cutting-model-select-${n}`}>
              <option value="">— pilih model —</option>
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {`${m.code ? `${m.code} · ` : ''}${m.name || ''}`
                    + (modelSummary[m.id] ? ` — ${modelSummary[m.id]}` : ' — belum ada varian')}
                </option>
              ))}
            </SmartNativeSelect>
            <Button type="button" size="icon" variant="outline" onClick={() => openNewModel(o.key)}
              title="Model baru" aria-label="Model baru" data-testid={`cutting-new-model-btn-${n}`}><Plus /></Button>
          </div>
          {bomInfo(bom)}
        </TableCell>
        <TableCell className="align-top">
          {o.model_id && !vs.length ? (
            <SmartNativeSelect value={o.size_id} onChange={(e) => setOutput(o.key, { size_id: e.target.value })}
              className="h-9 w-full" data-testid={`cutting-size-select-${n}`}>
              <option value="">— pilih ukuran —</option>
              {sizes.map((s) => (
                <option key={s.id} value={s.id}>
                  {`${s.code}${s.name && s.name !== s.code ? ` (${s.name})` : ''}${bomSizes.has(s.id) ? ' · ada BOM' : ''}`}
                </option>
              ))}
            </SmartNativeSelect>
          ) : (
            <SmartNativeSelect value={o.variant_id} onChange={(e) => onPickVariant(o, e.target.value)}
              disabled={!o.model_id} className="h-9 w-full" searchable searchPlaceholder="Cari warna, ukuran, atau SKU…"
              data-testid={`cutting-variant-select-${n}`}>
              <option value="">{o.model_id ? '— pilih warna · ukuran —' : '— pilih model dulu —'}</option>
              {vopts.map((v) => <option key={v.id} value={v.id}>{variantLabel(v)}</option>)}
            </SmartNativeSelect>
          )}
          {o.model_id && !vs.length && (
            <p className="mt-1 text-xs text-muted-foreground">Model ini belum punya varian — pilih ukurannya.</p>
          )}
        </TableCell>
        <TableCell className="align-top">
          <Input type="number" step="1" min="0" value={o.planned_output_qty} className="text-right tabular-nums"
            onChange={(e) => setOutput(o.key, { planned_output_qty: e.target.value })}
            data-testid={`cutting-planned-output-${n}`} />
        </TableCell>
        <TableCell className="align-top">
          {pls.length ? (
            <SmartNativeSelect value={o.po_item_id} onChange={(e) => pickPoLine(o, e.target.value)}
              className="h-9 w-full" data-testid={`cutting-po-line-select-${n}`}>
              <option value="">— tanpa baris PO —</option>
              {pls.map((ln) => (
                <option key={ln.id} value={ln.id}>
                  {`${ln.po_number} · ${ln.size || '-'}${ln.color ? ` · ${ln.color}` : ''}${ln.sku ? ` · ${ln.sku}` : ''} · ${fmtNum(ln.qty, 0)} pcs`}
                </option>
              ))}
            </SmartNativeSelect>
          ) : <span className="text-xs text-muted-foreground">{o.model_id ? 'Tidak ada PO terbuka' : '—'}</span>}
        </TableCell>
        <TableCell className="align-top" data-testid={`cutting-output-rolls-${n}`}>{renderOutRolls(o)}</TableCell>
        <TableCell className="align-top text-right">
          {form.outputs.length > 1 && (
            <Button type="button" size="icon-sm" variant="ghost" onClick={() => removeOutput(o.key)}
              title="Hapus baris" aria-label="Hapus baris" data-testid={`cutting-output-remove-${n}`}><Trash2 /></Button>
          )}
        </TableCell>
      </TableRow>
    );
  };

  const planText = form.inputs.filter((i) => i.input_material_id && Number(i.planned_input_qty) > 0)
    .map((i) => `${matById[i.input_material_id]?.code || ''} ${fmtQtyTrim(i.planned_input_qty)} ${matById[i.input_material_id]?.unit || ''}`)
    .join(' · ');

  return (
    <>
      <FormPopup open={open && !newModelFor} onClose={onClose} ukuran="panjang"
        judul={editing ? `Ubah order cutting ${order.number}` : 'Buat order cutting'}
        onSimpan={submit} menyimpan={saving} labelSimpan={editing ? 'Simpan perubahan' : 'Simpan draf'}
        keterangan="Satu order boleh memakai beberapa kain dan gulungan, dan menghasilkan beberapa model. Master potongan dibuat otomatis saat cutting dimulai."
        testId="cutting-create-form">
        <Isian label="Gudang sumber kain" wajib
          petunjuk="Semua kain order ini dipotong dari gudang ini, jadi gulungannya juga harus di sini.">
          <SmartNativeSelect value={form.location_id} onChange={(e) => setForm((f) => ({ ...f, location_id: e.target.value }))}
            className="h-9 w-full" data-testid="cutting-location-select">
            <option value="">— Pilih gudang —</option>
            {locationOptions.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
          </SmartNativeSelect>
        </Isian>

        {/* ── 1 · KAIN & GULUNGAN ── */}
        <div className="space-y-3" data-testid="cutting-inputs-section">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold text-foreground">Kain & gulungan</p>
            <label className="inline-flex cursor-pointer items-center gap-2 text-xs text-muted-foreground" htmlFor="cutting-only-instock">
              <Checkbox id="cutting-only-instock" checked={onlyInStock} onCheckedChange={(v) => setOnlyInStock(!!v)}
                data-testid="cutting-only-instock" />
              Tampilkan hanya kain yang ada stoknya ({materialOptions.length} dari {materials.length})
            </label>
          </div>
          {form.inputs.map((i, n) => renderInput(i, n))}
          <Button type="button" variant="outline" size="sm" onClick={addInput} data-testid="cutting-add-input">
            <Plus />Tambah kain
          </Button>
        </div>

        {/* ── 2 · HASIL POTONGAN ── */}
        <div className="space-y-3" data-testid="cutting-outputs-section">
          <p className="text-sm font-semibold text-foreground">Hasil potongan</p>
          <div className="overflow-x-auto">
            <Table data-testid="cutting-outputs-table">
              <TableHeader><TableRow>
                <TableHead>No</TableHead>
                <TableHead className="min-w-[14rem]">Model</TableHead>
                <TableHead className="min-w-[13rem]">Varian (warna · ukuran · SKU)</TableHead>
                <TableHead className="min-w-[7rem] text-right">Target (pcs)</TableHead>
                <TableHead className="min-w-[12rem]">Baris PO (opsional)</TableHead>
                <TableHead className="min-w-[9rem]">Gulungan dipakai</TableHead>
                <TableHead />
              </TableRow></TableHeader>
              <TableBody>
                {form.outputs.length === 0 ? (
                  <TableRow><TableCell colSpan={7}>
                    <EmptyState icon={Scissors} title="Belum ada baris hasil"
                      description="Tekan Tambah baris untuk menambah model yang dipotong." />
                  </TableCell></TableRow>
                ) : form.outputs.map((o, n) => renderOutput(o, n))}
              </TableBody>
            </Table>
          </div>
          <Button type="button" variant="outline" size="sm" onClick={addOutput} data-testid="cutting-add-output">
            <Plus />Tambah baris
          </Button>
        </div>

        {/* ── 3 · RINGKASAN: total pcs & perkiraan HPP (total biaya kain ÷ total pcs) ── */}
        <div className="space-y-1 rounded-lg border border-[var(--glass-border)] p-3 text-sm" data-testid="cutting-hpp-estimate">
          <p className="text-foreground">
            Total target <b className="tabular-nums">{fmtNum(est.pcs)} pcs</b> dari {form.outputs.length} baris hasil
            {planText && <> · rencana kain {planText}</>}
          </p>
          <p className="text-muted-foreground">
            Perkiraan biaya kain {fmtRp(Math.round(est.total))} ÷ {fmtNum(est.pcs)} pcs ≈{' '}
            <b className="tabular-nums text-foreground">{fmtRp(Math.round(est.perPcs))}/pcs</b> — HPP potongan sama untuk
            semua baris; angka pasti dihitung dari kain yang benar-benar terpakai saat lapor progres.
          </p>
          {est.missing.length > 0 && (
            <p className="text-xs text-[hsl(var(--warning-text))]">
              Kain {est.missing.map((i) => matById[i.input_material_id]?.code || '').join(', ')} belum punya harga dari
              pembelian — belum ikut perkiraan.
            </p>
          )}
          {unlinked.length > 0 && (
            <p className="text-xs text-[hsl(var(--warning-text))]" data-testid="cutting-unlinked-rolls">
              Gulungan {unlinked.map((r) => r.roll_no).join(', ')} belum ditautkan ke hasil potongan mana pun — centang di
              kolom Gulungan dipakai.
            </p>
          )}
        </div>

        <Isian label="Catatan">
          <Textarea value={form.notes} rows={2} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
            data-testid="cutting-notes" />
        </Isian>
      </FormPopup>

      {/* ── FORM MODEL BARU (master produk) — menggantikan form cutting sementara ── */}
      <FormPopup open={!!newModelFor} onClose={() => setNewModelFor(null)} ukuran="pendek"
        judul="Model / style baru" keterangan="Model ini tersimpan di Master Produk sehingga BOM & produksi bisa memakainya."
        onSimpan={createModel} menyimpan={savingModel} labelSimpan="Simpan model" testId="cutting-new-model-modal">
        <Isian label="Nama model / style" wajib>
          <Input value={newModel.name} autoFocus onChange={(e) => setNewModel((x) => ({ ...x, name: e.target.value }))}
            placeholder="mis. Dress Jemina" data-testid="new-model-name" />
        </Isian>
        <Isian label="Kategori produk" wajib={!newModel.code.trim()} petunjuk="Kode model dibuat otomatis dari kategori ini (mis. CLN-0001).">
          <SmartNativeSelect value={newModel.category_id}
            onChange={(e) => setNewModel((x) => ({ ...x, category_id: e.target.value }))}
            className="h-9 w-full" data-testid="new-model-category">
            <option value="">— pilih kategori —</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>{`${c.name}${c.sku_prefix ? ` (${c.sku_prefix})` : ''}`}</option>
            ))}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Kode model (opsional)" petunjuk="Kosongkan supaya dibuat otomatis dari kategori.">
          <Input value={newModel.code} onChange={(e) => setNewModel((x) => ({ ...x, code: e.target.value }))}
            placeholder="mis. DRS-JMN" data-testid="new-model-code" />
        </Isian>
      </FormPopup>
    </>
  );
}

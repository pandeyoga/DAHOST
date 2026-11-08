/**
 * CuttingOrdersModule — pintu utama Portal Cutting.
 *
 * Satu layar, tiga pekerjaan:
 *   1. Daftar order cutting + filter status/pencarian
 *   2. Buat cutting (pilih kain dari master material, opsional pilih roll fisik)
 *   3. Detail: input progres berulang, selesaikan, batalkan
 *
 * Semua mutasi stok terjadi di backend lewat SSOT gudang — UI hanya melaporkan
 * hasilnya (stok kain turun, stok potongan naik) supaya user melihat efeknya.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Plus, RefreshCw, Search, PlayCircle, CheckCircle2, XCircle,
  Trash2, Package, ArrowRight, Layers, AlertCircle, Loader2, History, Scissors, PencilLine,
} from 'lucide-react';
import { toast } from 'sonner';
import { GlassCard } from '@/components/ui/glass';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup from '@/components/ui/detail-popup';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';
import { cuttingApi, StatusPill, STATUS_META, fmtNum, fmtRp, fmtDateTime } from './cuttingApi';
import useUomOptions from '../../../hooks/useUomOptions';
import { UomSelect, UomConversionHint, toBaseQty } from '../uom/UomPicker';
import SmartNativeSelect from '@/components/ui/smart-native-select';
// FASE H-6 — gulungan WAJIB ditunjuk saat memotong kain yang punya gulungan.
import { previewAllocation, fmtQty } from '../warehouse/rollLines';

const EMPTY_FORM = {
  input_material_id: '',
  location_id: '',
  planned_input_qty: '',
  planned_output_qty: '',
  // Identitas produk DARI MASTER — `style_name`/`style_sku` hanya cerminan model
  // yang dipilih (tidak lagi diketik pemakai).
  model_id: '',
  variant_id: '',
  size_id: '',
  style_name: '',
  style_sku: '',
  output_color: '',
  output_size: '',
  notes: '',
  roll_ids: [],
  // 2026-11-06 (Tahap 2): tautan OPSIONAL ke baris PO (ukuran) — BOM per ukuran ikut PO.
  po_item_id: '',
};

// 2026-11-06 (Tahap 2): progres = kain diambil, sisa kain yang KEMBALI ke stok, limbah (bersatuan).
const EMPTY_PROG = {
  input_consumed: '', output_qty: '', waste_qty: '', waste_uom: '', leftover_qty: '',
  note: '', roll_id: '', input_uom: '', roll_ids: [],
};

/** Isian form standar (label · kontrol · petunjuk) — dulu label buatan sendiri. */
function Field({ label, children, hint, required }) {
  return <Isian label={label} wajib={!!required} petunjuk={hint || undefined}>{children}</Isian>;
}

/** Angka pemakaian bahan: tampilkan apa adanya tanpa nol berekor ("6" bukan "6,0000"). */
const fmtQtyTrim = (v) =>
  Number(v || 0).toLocaleString('id-ID', { maximumFractionDigits: 4 });

/** Label varian yang bisa dibedakan: warna · ukuran · SKU (2026-11-07, keluhan owner Order Cutting). */
const variantLabel = (v) =>
  [v?.color_name || v?.color || '-', v?.size_code || v?.size || '-', v?.sku].filter(Boolean).join(' · ');

/** Ringkasan varian per model ({model_id: "M/XL · 22 warna"}) — supaya dua model bernama sama bisa dibedakan. */
function summarizeVariantsByModel(rows) {
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

export default function CuttingOrdersModule({ token, onNavigate }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState('');
  const [q, setQ] = useState('');
  const [err, setErr] = useState('');

  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [materials, setMaterials] = useState([]);
  const [locations, setLocations] = useState([]);
  const [onlyInStock, setOnlyInStock] = useState(true);
  const [rolls, setRolls] = useState([]);
  const [rollMeta, setRollMeta] = useState({ roll_required: false, total_remaining: 0, uom: '' });
  const [saving, setSaving] = useState(false);
  // Master produk (model + varian) — sumber identitas potongan.
  const [models, setModels] = useState([]);
  const [variants, setVariants] = useState([]);
  // {model_id: "XL · 22 warna"} — label model memuat ukuran & jumlah warna (dua model bisa bernama sama).
  const [modelSummary, setModelSummary] = useState({});
  // Varian yang datang terlambat untuk model yang SUDAH diganti tidak boleh menimpa daftar model baru.
  const modelReq = useRef(0);
  const [showNewModel, setShowNewModel] = useState(false);
  const [newModel, setNewModel] = useState({ code: '', name: '', category_id: '' });
  // Kategori produk menentukan kode model otomatis (VST-0001) — tanpa kategori & tanpa kode server menolak.
  const [categories, setCategories] = useState([]);
  const [savingModel, setSavingModel] = useState(false);
  // 2026-08-23 — KEBUTUHAN BAHAN DARI BOM. Sebelum ini "Rencana Pemakaian Kain"
  // diketik manual (ditebak) walau BOM per model+size sudah menyimpan kebutuhan
  // per pcs. Kartu ini membacanya dari BOM dan menyediakan tombol "Pakai angka
  // BOM"; kalau BOM/satuan/kain-nya tidak cocok, alasannya DIKATAKAN.
  const [bomReq, setBomReq] = useState(null);
  const [bomLoading, setBomLoading] = useState(false);
  // Ukuran untuk model yang BOM-nya sudah ada tetapi variannya belum didaftarkan
  // (kalau tidak disediakan, ukuran itu mustahil dipilih ⇒ BOM tidak terpakai).
  const [sizes, setSizes] = useState([]);
  const [sizeId, setSizeId] = useState('');
  const [poLines, setPoLines] = useState([]);

  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [prog, setProg] = useState({ ...EMPTY_PROG });
  const [acting, setActing] = useState(false);
  // Standar UI/UX v2: form progres = popup sendiri (dulu form di dalam popup detail); detail disembunyikan sementara.
  const [progOpen, setProgOpen] = useState(false);
  // FASE H-6: gulungan yang masih bersisa untuk kain order ini (dimuat saat detail
  // dibuka). `rollRequired` datang dari server — layar tidak menebak sendiri.
  const [detailRolls, setDetailRolls] = useState({ items: [], roll_required: false, total_remaining: 0, uom: '' });

  // ── FASE H-6b (2026-08-17) — progres yang kainnya sudah keluar tetapi BELUM
  // punya dokumen "Pengeluaran Material". Ini keadaan data LAMA (sebelum H-6b)
  // atau sisa kegagalan penerbitan dokumen. Ditampilkan supaya tidak ada arus
  // keluar yang hilang dari daftar gudang, dan bisa diterbitkan sekali klik.
  const [miMissing, setMiMissing] = useState({ items: [], count: 0 });
  const [miFixing, setMiFixing] = useState(false);

  // ROADMAP P1 (2026-08-05) — operator lantai boleh mencatat pemakaian kain
  // dalam satuan lain (rol/gram/yard); server menerjemahkan ke satuan order.
  const { options: uomOpts } = useUomOptions(detail?.input_material_id ? [detail.input_material_id] : []);
  const progUomOpt = detail?.input_material_id ? uomOpts[detail.input_material_id] : null;
  const orderUnit = String(detail?.input_unit || '').toLowerCase();
  const effProgUom = prog.input_uom || orderUnit;

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setErr('');
    try {
      const qs = new URLSearchParams();
      if (status) qs.set('status', status);
      if (q) qs.set('q', q);
      setRows(await cuttingApi('GET', `/orders${qs.toString() ? `?${qs}` : ''}`, token));
    } catch (e) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }, [token, status, q]);

  useEffect(() => { load(); }, [load]);

  // FASE H-6b — dimuat bersamaan dengan daftar order.
  const loadMiMissing = useCallback(async () => {
    if (!token) return;
    try {
      setMiMissing(await cuttingApi('GET', '/issue-docs/missing?limit=200', token));
    } catch {
      setMiMissing({ items: [], count: 0 });
    }
  }, [token]);

  useEffect(() => { loadMiMissing(); }, [loadMiMissing]);

  const backfillMiDocs = async () => {
    setMiFixing(true);
    try {
      const res = await cuttingApi('POST', '/issue-docs/backfill', token, { limit: 500 });
      const n = res?.created || 0;
      if (n > 0) {
        toast.success(`${n} dokumen Pengeluaran Material diterbitkan — arus keluar kain kini tampil di layar Gudang.`);
      } else {
        toast.info('Tidak ada progres yang perlu dokumen baru.');
      }
      if ((res?.failed || []).length) {
        toast.error(`${res.failed.length} progres gagal: ${res.failed[0]?.error || ''}`);
      }
      await loadMiMissing();
      await load();
    } catch (e) {
      toast.error(`Gagal menerbitkan dokumen: ${e.message}`);
    } finally {
      setMiFixing(false);
    }
  };

  const openCreate = async () => {
    setForm(EMPTY_FORM);
    setRolls([]);
    setVariants([]);
    setSizeId('');
    setBomReq(null);
    setShowCreate(true);
    try {
      const [mats, locs] = await Promise.all([
        cuttingApi('GET', '/input-materials', token),
        cuttingApi('GET', '/locations', token),
      ]);
      setMaterials(mats);
      setLocations(locs);
    } catch (e) {
      toast.error(`Gagal memuat master kain: ${e.message}`);
    }
    await loadModels();
  };

  const authHdr = () => ({ Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` });

  const loadModels = async () => {
    try {
      const [r, rv] = await Promise.all([
        fetch('/api/rahaza/models', { headers: authHdr() }),
        // ringkasan ukuran & warna per model untuk label pilihan model (gagal ⇒ label kode · nama saja)
        fetch('/api/rahaza/variants', { headers: authHdr() }).catch(() => null),
      ]);
      const d = await r.json();
      const list = Array.isArray(d) ? d : (d?.items || []);
      setModels(list.filter((m) => m.active !== false));
      if (rv && rv.ok) {
        const dv = await rv.json();
        setModelSummary(summarizeVariantsByModel(Array.isArray(dv) ? dv : (dv?.variants || dv?.items || [])));
      }
    } catch {
      setModels([]);
    }
  };

  const onPickModel = async (id, picked = null) => {
    // `picked` = model yang baru dibuat (belum ada di `models` milik closure ini)
    const m = models.find((x) => x.id === id) || picked;
    const req = ++modelReq.current;
    // 2026-11-07: ganti model = varian, ukuran, DAN baris PO ikut dikosongkan (dulu baris PO model
    // lama tertinggal di form ⇒ simpan ditolak "Baris PO yang dipilih untuk model lain").
    setForm((f) => ({
      ...f,
      model_id: id,
      variant_id: '',
      size_id: '',
      po_item_id: '',
      style_name: m?.name || '',
      style_sku: m?.code || '',
      output_color: '',
      output_size: '',
    }));
    setVariants([]);
    setSizeId('');
    setPoLines([]);
    if (!id) return;
    cuttingApi('GET', `/po-lines?model_id=${id}`, token)
      .then((d) => { if (req === modelReq.current) setPoLines(Array.isArray(d) ? d : []); })
      .catch(() => { if (req === modelReq.current) setPoLines([]); });
    try {
      const r = await fetch(`/api/rahaza/models/${id}/variants`, { headers: authHdr() });
      const d = await r.json();
      if (req !== modelReq.current) return;  // model sudah diganti lagi — jawaban lama dibuang
      // 2026-11-06 (pola P1): server membalas {model, variants, count} — dulu dibaca `d.items`
      // sehingga pilihan varian di form Order Cutting selalu kosong.
      // Saringan model_id di layar = pengaman kedua: hanya varian milik model terpilih yang tampil.
      setVariants((Array.isArray(d) ? d : (d?.variants || []))
        .filter((v) => v.active !== false && (!v.model_id || v.model_id === id)));
    } catch {
      if (req === modelReq.current) setVariants([]);
    }
  };

  const onPickVariant = (vid) => {
    const v = variants.find((x) => x.id === vid) || null;
    setForm((f) => {
      // Baris PO berukuran lain dari varian yang dipilih ⇒ tautan PO dilepas (server menolak campuran itu).
      const ln = poLines.find((x) => x.id === f.po_item_id);
      const dropPo = !!(v && ln && ln.size_id && v.size_id && ln.size_id !== v.size_id);
      return {
        ...f,
        variant_id: vid,
        output_color: v?.color_name || v?.color || '',
        output_size: v?.size_code || v?.size || '',
        po_item_id: dropPo ? '' : f.po_item_id,
      };
    });
  };

  // ── Kebutuhan bahan menurut BOM (model + ukuran) ─────────────────────────
  // Dimuat ulang setiap kali model/varian/kain/target pcs berubah supaya angka
  // yang ditawarkan selalu milik kombinasi yang sedang dipilih.
  useEffect(() => {
    if (!showCreate || !form.model_id) { setBomReq(null); return; }
    const variant = variants.find((x) => x.id === form.variant_id) || null;
    const effSizeId = variant?.size_id || sizeId || '';
    let alive = true;
    const t = setTimeout(async () => {
      setBomLoading(true);
      try {
        const p = new URLSearchParams({ model_id: form.model_id });
        if (effSizeId) p.set('size_id', effSizeId);
        if (form.variant_id) p.set('variant_id', form.variant_id);
        if (form.planned_output_qty) p.set('qty_pcs', String(form.planned_output_qty));
        if (form.input_material_id) p.set('input_material_id', form.input_material_id);
        const d = await cuttingApi('GET', `/bom-requirement?${p}`, token);
        if (alive) setBomReq(d);
      } catch {
        if (alive) setBomReq(null);
      } finally {
        if (alive) setBomLoading(false);
      }
    }, 250);
    return () => { alive = false; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showCreate, form.model_id, form.variant_id, form.planned_output_qty,
      form.input_material_id, variants, sizeId, token]);

  // Master ukuran (dipakai saat model belum punya varian).
  useEffect(() => {
    if (!showCreate || sizes.length) return;
    (async () => {
      try {
        const r = await fetch('/api/rahaza/sizes', {
          headers: { Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` },
        });
        const d = await r.json();
        setSizes((Array.isArray(d) ? d : (d?.items || [])).filter((s) => s.active !== false));
      } catch { setSizes([]); }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showCreate]);

  const pickSize = (sid) => {
    setSizeId(sid);
    const s = sizes.find((x) => x.id === sid);
    setForm((f) => ({ ...f, size_id: sid, output_size: s?.code || '' }));
  };

  // Baris PO dipilih → ukuran (dan varian bila ada) mengikuti baris PO itu.
  const pickPoLine = (pid) => {
    const ln = poLines.find((x) => x.id === pid) || null;
    setForm((f) => ({ ...f, po_item_id: pid }));
    if (!ln) return;
    if (ln.rahaza_variant_id && variants.some((v) => v.id === ln.rahaza_variant_id)) {
      onPickVariant(ln.rahaza_variant_id);
    } else if (ln.size_id) {
      // 2026-11-07: varian terpilih yang ukurannya BEDA dari baris PO dilepas — dulu tertinggal dan
      // server menolak simpan ("Ukuran yang dipilih berbeda dengan ukuran baris PO").
      setForm((f) => {
        const cur = variants.find((v) => v.id === f.variant_id);
        return cur && cur.size_id && cur.size_id !== ln.size_id
          ? { ...f, variant_id: '', output_color: ln.color || '' } : f;
      });
      pickSize(ln.size_id);
    }
  };

  // Pilihan varian = varian MILIK model terpilih; bila baris PO dipilih, hanya ukuran baris PO itu.
  const poLinePicked = useMemo(() => poLines.find((x) => x.id === form.po_item_id) || null,
    [poLines, form.po_item_id]);
  const variantOptions = useMemo(() => (poLinePicked?.size_id
    ? variants.filter((v) => !v.size_id || v.size_id === poLinePicked.size_id)
    : variants), [variants, poLinePicked]);

  // SESI #32 — ukuran mana yang SUDAH punya BOM, ditandai LANGSUNG di daftar
  // pilihan. Sebelumnya keterangan itu hanya muncul sebagai kalimat di bawah
  // kartu ("Ukuran yang SUDAH punya BOM: ALLSIZE"), jadi admin cutting tetap
  // memilih ukuran secara buta lalu baru tahu BOM-nya kosong sesudah memilih.
  const sizesWithBom = useMemo(() => {
    const s = new Set();
    (bomReq?.other_sizes_with_bom || []).forEach((x) => {
      if (x?.size_id) s.add(x.size_id);
    });
    if (bomReq?.has_bom && (bomReq?.size_id || sizeId)) s.add(bomReq?.size_id || sizeId);
    return s;
  }, [bomReq, sizeId]);

  const useBomQty = () => {
    const q = Number(bomReq?.fabric?.qty_total || 0);
    if (!(q > 0)) {
      toast.error('Angka BOM belum bisa dipakai — isi target potongan (pcs) dulu.');
      return;
    }
    setForm((f) => ({ ...f, planned_input_qty: String(q) }));
    toast.success(`Rencana pemakaian kain diisi dari BOM: ${fmtQtyTrim(q)} ${bomReq.fabric.unit}.`);
  };

  const openNewModel = async () => {
    setShowNewModel(true);
    if (categories.length) return;
    try {
      const r = await fetch('/api/rahaza/product-categories', { headers: authHdr() });
      const d = await r.json();
      setCategories((Array.isArray(d) ? d : (d?.categories || [])).filter((c) => c.active !== false));
    } catch { setCategories([]); }
  };

  const createModel = async () => {
    if (!newModel.name.trim()) return toast.error('Nama model wajib diisi.');
    if (!newModel.code.trim() && !newModel.category_id) {
      return toast.error('Pilih kategori produk (kode model dibuat dari kategori), atau isi kode model sendiri.');
    }
    setSavingModel(true);
    try {
      const r = await fetch('/api/rahaza/models', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token || localStorage.getItem('erp_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          name: newModel.name.trim(), code: newModel.code.trim(),
          ...(newModel.category_id ? { category_id: newModel.category_id } : {}),
        }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || d.error || `HTTP ${r.status}`);
      toast.success(`Model ${d.code || d.name} ditambahkan ke master.`);
      setShowNewModel(false);
      setNewModel({ code: '', name: '', category_id: '' });
      await loadModels();
      setModels((prev) => (prev.some((x) => x.id === d.id) ? prev : [...prev, d]));
      await onPickModel(d.id, d);
    } catch (e) {
      toast.error(`Gagal membuat model: ${e.message}`);
    } finally {
      setSavingModel(false);
    }
  };

  const selectedMaterial = useMemo(
    () => materials.find((m) => m.id === form.input_material_id) || null,
    [materials, form.input_material_id],
  );

  // Stok disimpan PER GUDANG. Dropdown kain menampilkan lokasi yang benar-benar
  // memegang stok agar user tidak membuat cutting di gudang yang kosong
  // (penyebab kegagalan "stok tidak cukup" saat input progres).
  const materialOptions = useMemo(() => {
    const list = onlyInStock ? materials.filter((m) => Number(m.stock_qty || 0) > 0) : materials;
    return list;
  }, [materials, onlyInStock]);

  const onPickMaterial = async (id) => {
    const m = materials.find((x) => x.id === id);
    setForm((f) => ({
      ...f,
      input_material_id: id,
      location_id: m?.best_location_id || '',
      roll_ids: [],
    }));
    setRolls([]);
    setRollMeta({ roll_required: false, total_remaining: 0, uom: '' });
    if (!id) return;
    try {
      // FASE H-6: respons kini objek ({items, roll_required, total_remaining, uom})
      // supaya layar tahu apakah gulungan WAJIB dan berapa sisa totalnya.
      const res = await cuttingApi('GET', `/rolls?material_id=${id}`, token);
      const items = Array.isArray(res) ? res : (res?.items || []);
      setRolls(items);
      setRollMeta({
        roll_required: !!res?.roll_required,
        total_remaining: Number(res?.total_remaining || 0),
        uom: res?.uom || items[0]?.uom || '',
      });
    } catch {
      setRolls([]);
      setRollMeta({ roll_required: false, total_remaining: 0, uom: '' });
    }
  };

  const stockAtLocation = useMemo(() => {
    if (!selectedMaterial) return null;
    const loc = (selectedMaterial.stock_locations || []).find((l) => l.location_id === form.location_id);
    return loc ? loc.qty : 0;
  }, [selectedMaterial, form.location_id]);

  const submitCreate = async (e) => {
    e?.preventDefault?.();
    if (!form.input_material_id) return toast.error('Pilih material kain dulu.');
    if (!form.model_id) return toast.error('Pilih Model/Style dari Master Produk dulu.');
    // 2026-11-02 — No.18(a): backend tidak lagi menebak gudang bila kosong.
    if (!form.location_id) return toast.error('Pilih Gudang Sumber Kain dulu.');
    // 2026-11-06 (Tahap 2): ukuran WAJIB — tanpa ukuran potongan tidak dipakai BOM mana pun.
    if (!form.variant_id && !form.size_id && !form.po_item_id) {
      return toast.error('Pilih ukuran dulu (lewat varian warna·ukuran, ukuran BOM, atau baris PO).');
    }
    if (!(Number(form.planned_input_qty) > 0)) return toast.error('Rencana pemakaian kain harus > 0.');
    if (!(Number(form.planned_output_qty) > 0)) return toast.error('Target potongan harus > 0.');
    setSaving(true);
    try {
      const created = await cuttingApi('POST', '/orders', token, {
        ...form,
        planned_input_qty: Number(form.planned_input_qty),
        planned_output_qty: Number(form.planned_output_qty),
      });
      toast.success(`Cutting ${created.number} dibuat (draft).`);
      setShowCreate(false);
      await load();
      openDetail(created.id);
    } catch (e2) {
      toast.error(e2.message);
    } finally {
      setSaving(false);
    }
  };

  const openDetail = async (id) => {
    setDetailLoading(true);
    setProgOpen(false);
    setProg({ ...EMPTY_PROG });
    setDetailRolls({ items: [], roll_required: false, total_remaining: 0, uom: '' });
    try {
      const d = await cuttingApi('GET', `/orders/${id}`, token);
      setDetail(d);
      await loadDetailRolls(d);
    } catch (e) {
      toast.error(e.message);
    } finally {
      setDetailLoading(false);
    }
  };

  // FASE H-6: gulungan yang bisa dipotong untuk order ini. Dimuat setiap kali
  // detail dibuka/diperbarui supaya sisa tiap gulungan yang tampil = sisa nyata.
  const loadDetailRolls = useCallback(async (order) => {
    if (!order?.input_material_id) return;
    try {
      const locQs = order.location_id ? `&location_id=${encodeURIComponent(order.location_id)}` : '';
      const res = await cuttingApi('GET', `/rolls?material_id=${order.input_material_id}${locQs}`, token);
      const items = Array.isArray(res) ? res : (res?.items || []);
      setDetailRolls({
        other_location_count: Number(res?.other_location_count || 0),
        items,
        roll_required: !!res?.roll_required,
        total_remaining: Number(res?.total_remaining || 0),
        uom: res?.uom || items[0]?.uom || '',
      });
    } catch {
      setDetailRolls({ items: [], roll_required: false, total_remaining: 0, uom: '' });
    }
  }, [token]);

  const refreshDetail = async (id) => {
    try {
      const d = await cuttingApi('GET', `/orders/${id}`, token);
      setDetail(d);
      await loadDetailRolls(d);
    } catch { /* ignore */ }
    load();
  };

  const doAction = async (path, body, okMsg) => {
    if (!detail) return;
    setActing(true);
    try {
      const res = await cuttingApi('POST', `/orders/${detail.id}${path}`, token, body);
      toast.success(okMsg);
      if (res?.notice) toast.info(res.notice, { duration: 6000 });
      // SESI #32 — kain SUDAH terpotong tetapi nilainya belum bisa dihitung
      // (harga kain 0). Ini bukan info biasa: nilai persediaan potongan akan
      // 0 sampai harga kainnya lahir dari pembelian, jadi ditampilkan sebagai
      // PERINGATAN yang bertahan lebih lama.
      if (res?.value_warning) toast.warning(res.value_warning, { duration: 12000 });
      await refreshDetail(detail.id);
    } catch (e) {
      toast.error(e.message, { duration: 8000 });
    } finally {
      setActing(false);
    }
  };

  // FASE H-6: rencana pemakaian gulungan (FIFO) dihitung di layar supaya operator
  // melihat "gulungan mana dipakai berapa" SEBELUM menekan Catat — cermin dari
  // `fabric_roll_engine.allocate()` di server.
  const pickedRolls = useMemo(
    () => detailRolls.items.filter((r) => (prog.roll_ids || []).includes(r.id)),
    [detailRolls.items, prog.roll_ids],
  );
  // 2026-11-06 (Tahap 2): pratinjau gulungan memakai angka yang SUDAH dikonversi ke satuan order
  // (dulu angka gram dibandingkan dengan sisa gulungan kg ⇒ tombol Catat terkunci) dan dikurangi
  // sisa kain yang kembali ke stok (yang benar-benar dipotong dari gulungan = diambil − sisa).
  const toOrderUnit = useCallback((qty, unit) => {
    const q = Number(qty || 0);
    if (!q) return 0;
    if (!progUomOpt || !unit || unit === orderUnit) return q;
    const inBase = toBaseQty(progUomOpt, q, unit);
    const orderBase = toBaseQty(progUomOpt, 1, orderUnit);
    return inBase != null && orderBase ? Math.round((inBase / orderBase) * 10000) / 10000 : q;
  }, [progUomOpt, orderUnit]);
  const consumedInOrderUnit = useMemo(() => {
    const taken = toOrderUnit(prog.input_consumed, effProgUom);
    const left = toOrderUnit(prog.leftover_qty, effProgUom);
    return Math.max(0, Math.round((taken - left) * 10000) / 10000);
  }, [prog.input_consumed, prog.leftover_qty, effProgUom, toOrderUnit]);
  const allocPreview = useMemo(
    () => previewAllocation(pickedRolls, consumedInOrderUnit),
    [pickedRolls, consumedInOrderUnit],
  );
  const rollBlocking = detailRolls.roll_required && (prog.roll_ids || []).length === 0;

  const toggleProgRoll = (id) => setProg((p) => {
    const has = (p.roll_ids || []).includes(id);
    return { ...p, roll_ids: has ? p.roll_ids.filter((x) => x !== id) : [...(p.roll_ids || []), id] };
  });

  const submitProgress = async (e) => {
    e?.preventDefault?.();
    if (!(Number(prog.input_consumed) > 0)) return toast.error('Kain terpakai harus > 0.');
    if (!(consumedInOrderUnit > 0)) return toast.error('Sisa kain tidak boleh sama dengan atau melebihi kain yang diambil.');
    if (!(Number(prog.output_qty) > 0)) return toast.error('Jumlah potongan jadi harus > 0.');
    if (rollBlocking) {
      return toast.error(
        'Pilih gulungan yang dipotong dulu — tanpa itu sisa gulungan di sistem akan menyimpang '
        + 'dari kenyataan dan lot kain tidak bisa dipertanggungjawabkan ke buyer.',
        { duration: 8000 });
    }
    setActing(true);
    try {
      const res = await cuttingApi('POST', `/orders/${detail.id}/progress`, token, {
        input_consumed: Number(prog.input_consumed),
        output_qty: Number(prog.output_qty),
        waste_qty: Number(prog.waste_qty || 0),
        waste_uom: prog.waste_uom || undefined,
        leftover_qty: Number(prog.leftover_qty || 0),
        note: prog.note,
        roll_ids: (prog.roll_ids || []).length ? prog.roll_ids : undefined,
        roll_id: prog.roll_id || undefined,
        input_uom: (effProgUom && effProgUom !== orderUnit) ? effProgUom : undefined,
      });
      toast.success('Progres tercatat — stok gudang sudah diperbarui.');
      // FASE H-6b — beri tahu nomor dokumen arus keluarnya (atau peringatkan kalau
      // dokumen gagal terbit; stok TETAP sudah berkurang, jadi ini harus terlihat).
      const miNo = res?.last_progress?.material_issue_number;
      if (miNo) {
        toast.info(`Dokumen Pengeluaran Material ${miNo} diterbitkan — arus keluar kain tampil di layar Gudang.`,
          { duration: 8000 });
      } else if (res?.mi_warning) {
        toast.error(res.mi_warning, { duration: 12000 });
      }
      const used = res?.last_progress?.roll_consumption || [];
      if (used.length) {
        toast.info(
          'Gulungan dipakai: ' + used.map((u) => `${u.roll_no} −${fmtQty(u.qty)} (sisa ${fmtQty(u.remaining_after)})`).join(' · '),
          { duration: 9000 });
      }
      // SESI #32 — NILAI yang berpindah dari kain ke potongan. Kalau kainnya
      // belum bernilai, ini jadi PERINGATAN (bukan info) karena nilai persediaan
      // potongan akan 0 sampai harga kainnya lahir dari pembelian.
      const lp = res?.last_progress || {};
      if (lp.value_status === 'valued' && Number(lp.value_out) > 0) {
        toast.info(
          `Nilai kain keluar ${fmtRp(lp.value_out)} → HPP potongan ${fmtRp(lp.panel_unit_cost_after)}/pcs`
          + (Number(lp.panel_unit_cost_before) > 0
            ? ` (dari ${fmtRp(lp.panel_unit_cost_before)}, rata-rata bergerak)` : ''),
          { duration: 9000 });
      } else if (res?.value_warning) {
        toast.warning(res.value_warning, { duration: 12000 });
      }
      setProg({ ...EMPTY_PROG });
      setProgOpen(false);
      await refreshDetail(detail.id);
      await loadMiMissing();
    } catch (e2) {
      toast.error(e2.message, { duration: 9000 });
    } finally {
      setActing(false);
    }
  };

  const removeDraft = async (row) => {
    if (!(await confirmDialog({ title: `Hapus draft ${row.number}?`, confirmLabel: 'Hapus', danger: true }))) return;
    try {
      await cuttingApi('DELETE', `/orders/${row.id}`, token);
      toast.success('Draft dihapus.');
      if (detail?.id === row.id) setDetail(null);
      load();
    } catch (e) {
      toast.error(e.message);
    }
  };

  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(rows, 25);
  const stLabel = (s) => (STATUS_META[s] || STATUS_META.draft).label;
  const kolom = [
    { kunci: 'nomor', label: 'Nomor', hp: 'judul', isi: (r) => <span className="font-medium tabular-nums whitespace-nowrap">{r.number}</span> },
    { kunci: 'style', label: 'Style / potongan', hp: 'keterangan', isi: (r) => (
      <div className="min-w-0">
        <p className="text-foreground">{r.style_name || '—'}</p>
        <p className="text-xs tabular-nums text-muted-foreground">{r.output_material_code || 'Kode dibuat saat mulai'}</p>
      </div>) },
    { kunci: 'kain', label: 'Kain (input)', isi: (r) => (
      <div className="min-w-0 md:max-w-[14rem]">
        <p className="truncate text-sm" title={r.input_material_name}>{r.input_material_name}</p>
        <p className="text-xs tabular-nums text-muted-foreground">{r.input_material_code}</p>
      </div>) },
    { kunci: 'pakai', label: 'Kain terpakai', rata: 'kanan', isi: (r) => (
      <span className="tabular-nums whitespace-nowrap">{fmtNum(r.consumed_input_qty, 2)} / {fmtNum(r.planned_input_qty, 2)} {r.input_unit}</span>) },
    { kunci: 'jadi', label: 'Potongan jadi', rata: 'kanan', isi: (r) => (
      <div className="tabular-nums whitespace-nowrap">
        <span className="font-medium text-foreground">{fmtNum(r.produced_qty)}</span>
        <span className="text-muted-foreground"> / {fmtNum(r.planned_output_qty)} pcs</span>
        <div className="mt-1 h-1 overflow-hidden rounded-full bg-foreground/10">
          <div className="h-full bg-primary" style={{ width: `${Math.min(r.progress_pct || 0, 100)}%` }} />
        </div>
      </div>) },
    { kunci: 'status', label: 'Status', isi: (r) => <StatusPill status={r.status} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <div className="flex justify-end gap-1.5">
        <Button size="sm" variant="outline" onClick={() => openDetail(r.id)} data-testid={`cutting-detail-${r.number}`}>Rincian</Button>
        {r.status === 'draft' && (
          <Button size="icon-sm" variant="ghost" onClick={() => removeDraft(r)} title="Hapus draf" aria-label="Hapus draf"
            data-testid={`cutting-delete-${r.number}`}>
            <Trash2 />
          </Button>
        )}
      </div>) },
  ];

  return (
    <PageLayout testId="cutting-orders-module" title="Order Cutting"
      subtitle="Ubah roll kain menjadi kain pola (potongan) yang jadi material untuk BOM produksi."
      actions={<Button onClick={openCreate} data-testid="cutting-create-btn"><Plus />Buat cutting</Button>}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari nomor, style, kain, kode potongan"
            className="pl-8" data-testid="cutting-search-input" />
        </div>
        <SmartNativeSelect value={status} onChange={(e) => setStatus(e.target.value)} searchable={false}
          className="h-9 w-44" wrapperClassName="w-44" aria-label="Status" data-testid="cutting-status-filter">
          <option value="">Semua status</option>
          <option value="draft">Draf</option>
          <option value="in_progress">Berjalan</option>
          <option value="completed">Selesai</option>
          <option value="cancelled">Dibatalkan</option>
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="order-cutting" namaLembar="Order cutting" baris={rows} testId="cutting-unduh"
          kolom={[
            { label: 'Nomor', nilai: (r) => r.number }, { label: 'Style', nilai: (r) => r.style_name || '' },
            { label: 'Kode potongan', nilai: (r) => r.output_material_code || '' },
            { label: 'Kain', nilai: (r) => r.input_material_name || '' }, { label: 'Kode kain', nilai: (r) => r.input_material_code || '' },
            { label: 'Kain terpakai', nilai: (r) => Number(r.consumed_input_qty || 0) },
            { label: 'Rencana kain', nilai: (r) => Number(r.planned_input_qty || 0) }, { label: 'Satuan kain', nilai: (r) => r.input_unit || '' },
            { label: 'Potongan jadi (pcs)', nilai: (r) => Number(r.produced_qty || 0) },
            { label: 'Target (pcs)', nilai: (r) => Number(r.planned_output_qty || 0) },
            { label: 'Status', nilai: (r) => stLabel(r.status) }, { label: 'Dibuat', nilai: (r) => fmtDateTime(r.created_at) },
          ]} />
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="cutting-refresh-btn">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={<>
        {err && <Notice tone="danger" icon={AlertCircle}>{err}</Notice>}
        {/* FASE H-6b — progres yang kainnya sudah keluar tetapi belum punya dokumen Pengeluaran Material.
            Menerbitkan dokumen TIDAK memotong stok lagi. */}
        {miMissing.count > 0 && (
          <Notice tone="warning" icon={AlertCircle} testId="cutting-mi-missing-panel"
            title={`${miMissing.count} laporan progres belum punya dokumen Pengeluaran Material`}
            action={<div className="flex flex-wrap gap-2">
              <TombolUnduh namaBerkas="progres-tanpa-dokumen" namaLembar="Progres" baris={miMissing.items || []} testId="cutting-mi-unduh"
                kolom={[
                  { label: 'Order', nilai: (m) => m.cutting_number || '' }, { label: 'Kode kain', nilai: (m) => m.material_code || '' },
                  { label: 'Kain', nilai: (m) => m.material_name || '' }, { label: 'Kain keluar', nilai: (m) => Number(m.input_consumed || 0) },
                  { label: 'Satuan', nilai: (m) => m.unit || '' }, { label: 'Gudang', nilai: (m) => m.location_name || '' },
                  { label: 'Gulungan', nilai: (m) => (m.roll_numbers || []).join(', ') }, { label: 'Waktu', nilai: (m) => fmtDateTime(m.created_at) },
                ]} />
              <Button size="sm" onClick={backfillMiDocs} disabled={miFixing} data-testid="cutting-mi-backfill-btn">
                {miFixing ? <Loader2 className="animate-spin" /> : <History />}
                {miFixing ? 'Menerbitkan…' : 'Terbitkan dokumen'}
              </Button>
            </div>}>
            <p>Kain dan gulungannya sudah berkurang, tetapi arus keluarnya belum tampil di Gudang › Pengeluaran Material.
              Menerbitkan dokumen hanya membuat bukti — <b>stok tidak dipotong lagi</b>.</p>
            <div className="mt-2 overflow-x-auto">
              <Table data-testid="cutting-mi-missing-table">
                <TableHeader><TableRow>
                  <TableHead>Order</TableHead><TableHead>Kain</TableHead><TableHead className="text-right">Kain keluar</TableHead>
                  <TableHead>Gudang</TableHead><TableHead>Gulungan</TableHead><TableHead>Waktu</TableHead>
                </TableRow></TableHeader>
                <TableBody>
                  {(miMissing.items || []).slice(0, 8).map((m) => (
                    <TableRow key={m.progress_id} data-testid={`cutting-mi-missing-row-${m.progress_id}`}>
                      <TableCell className="tabular-nums">{m.cutting_number || '—'}</TableCell>
                      <TableCell><span className="tabular-nums">{m.material_code || '—'}</span>
                        <span className="text-muted-foreground"> · {m.material_name || ''}</span></TableCell>
                      <TableCell className="text-right tabular-nums">{fmtNum(m.input_consumed, 2)} {m.unit || ''}</TableCell>
                      <TableCell>{m.location_name || '—'}</TableCell>
                      <TableCell className="tabular-nums">{(m.roll_numbers || []).join(', ') || '—'}</TableCell>
                      <TableCell className="whitespace-nowrap">{fmtDateTime(m.created_at)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            {miMissing.count > 8 && (
              <p className="mt-1.5 text-xs text-muted-foreground">…dan {miMissing.count - 8} lagi. Tombol Terbitkan dokumen menerbitkan semuanya.</p>
            )}
          </Notice>
        )}
      </>}
      footer={rows.length > pageSize && (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />
      )}>
      {loading && rows.length === 0 ? (
        <div className="space-y-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
      ) : (
        <TabelData kolom={kolom} baris={paged} onKlikBaris={(r) => openDetail(r.id)} testId="cutting-orders-table"
          kosong={<EmptyState icon={Scissors} testId="cutting-empty-state"
            title={q || status ? 'Tidak ada order yang cocok' : 'Belum ada order cutting'}
            description={q || status ? 'Ubah kata pencarian atau status.' : 'Mulai dengan memilih kain dari master material Gudang.'}
            action={!q && !status && <Button onClick={openCreate}><Plus />Buat cutting</Button>} />} />
      )}

      {/* ── FORM BUAT CUTTING (popup panjang) ───────────────────────────── */}
      <FormPopup open={showCreate && !showNewModel} onClose={() => setShowCreate(false)} ukuran="panjang"
        judul="Buat order cutting" onSimpan={submitCreate} menyimpan={saving} labelSimpan="Simpan draf"
        keterangan="Kain diambil dari master material Gudang. Item potongan (satuan pcs) dibuat otomatis saat cutting dimulai."
        testId="cutting-create-form">
        {/* Kain & gudang berdampingan (dulu satu pilihan selebar popup) */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Material kain (input)" required
          hint={selectedMaterial
            ? `Total stok ${fmtNum(selectedMaterial.stock_qty, 2)} ${selectedMaterial.unit} · ${selectedMaterial.roll_count} roll aktif`
            : 'Stok kain disimpan per gudang — pilih kain dulu untuk melihat sebarannya.'}>
          <label className="mb-1.5 inline-flex cursor-pointer items-center gap-2 text-xs text-muted-foreground" htmlFor="cutting-only-instock">
            <Checkbox id="cutting-only-instock" checked={onlyInStock} onCheckedChange={(v) => setOnlyInStock(!!v)}
              data-testid="cutting-only-instock" />
            Tampilkan hanya kain yang ada stoknya ({materialOptions.length} dari {materials.length})
          </label>
          <SmartNativeSelect value={form.input_material_id} onChange={(e) => onPickMaterial(e.target.value)}
            className="h-9 w-full" searchable searchPlaceholder="Cari kode, nama, atau warna kain…"
            data-testid="cutting-input-material-select">
            <option value="">— Pilih kain —</option>
            {materialOptions.map((m) => (
              <option key={m.id} value={m.id}>
                {`${m.code} · ${m.name}`
                  + (m.color && !String(m.name || '').toLowerCase().includes(String(m.color).toLowerCase()) ? ` · ${m.color}` : '')
                  + ` — stok ${fmtNum(m.stock_qty, 2)} ${m.unit || ''}`
                  + (m.best_location_name ? ` @ ${m.best_location_name}` : ' (belum ada stok)')}
              </option>
            ))}
          </SmartNativeSelect>
        </Field>

        {selectedMaterial && (
          <Field label="Gudang sumber kain" required
            hint={stockAtLocation !== null
              ? `Stok di gudang ini: ${fmtNum(stockAtLocation, 2)} ${selectedMaterial.unit}. Pemotongan stok saat input progres diambil dari gudang ini.`
              : ''}>
            <SmartNativeSelect value={form.location_id}
              onChange={(e) => setForm((f) => ({ ...f, location_id: e.target.value }))}
              className="h-9 w-full" data-testid="cutting-location-select">
              <option value="">— Pilih gudang —</option>
              {(selectedMaterial.stock_locations || []).map((l) => (
                <option key={l.location_id} value={l.location_id}>
                  {l.location_name} — stok {fmtNum(l.qty, 2)} {selectedMaterial.unit}
                </option>
              ))}
              {(selectedMaterial.stock_locations || []).length === 0 &&
                locations.map((l) => (
                  <option key={l.id} value={l.id}>{l.name} (stok 0)</option>
                ))}
            </SmartNativeSelect>
          </Field>
        )}
        </div>

        {selectedMaterial && Number(selectedMaterial.stock_qty || 0) <= 0 && (
          <Notice tone="warning" icon={AlertCircle}>
            Kain ini belum punya stok di gudang mana pun. Cutting bisa disimpan sebagai draf, tetapi tidak bisa dimulai
            sebelum penerimaan barang dicatat di Portal Gudang.
          </Notice>
        )}

        {/* ── FASE H-6: gulungan WAJIB untuk kain yang dilacak per gulungan ── */}
        {selectedMaterial && rollMeta.roll_required && rolls.length > 0 && (
          <Field label={`Gulungan kain (${rolls.length} tersedia · sisa ${fmtQty(rollMeta.total_remaining)} ${rollMeta.uom})`}
            hint="Centang gulungan yang akan dipotong. Boleh dipilih sekarang atau saat lapor progres — progres tidak bisa dicatat tanpa menunjuk gulungan.">
            <div className="max-h-40 divide-y divide-[var(--glass-border)] overflow-y-auto rounded-lg border border-[var(--glass-border)]"
              data-testid="cutting-roll-picker">
              {rolls.map((r) => {
                const checked = form.roll_ids.includes(r.id);
                const remaining = Number(r.remaining ?? (r.uom === 'kg' ? r.remaining_kg : r.remaining_m) ?? 0);
                return (
                  <label key={r.id} className="flex cursor-pointer items-center gap-2 px-3 py-2 text-sm hover:bg-foreground/5"
                    data-testid={`cutting-roll-option-${r.roll_no}`}>
                    <Checkbox checked={checked}
                      onCheckedChange={() => setForm((f) => ({
                        ...f,
                        roll_ids: checked ? f.roll_ids.filter((x) => x !== r.id) : [...f.roll_ids, r.id],
                      }))} />
                    <span className="tabular-nums text-foreground">{r.roll_no}</span>
                    <span className="text-xs text-muted-foreground">
                      sisa {fmtQty(remaining)} {r.uom} · {r.color || r.color_lot || '—'}
                      {r.source_receipt_number ? ` · dari ${r.source_receipt_number}` : ''}
                    </span>
                  </label>
                );
              })}
            </div>
            {form.roll_ids.length > 0 && (
              <p className="mt-1 text-xs text-muted-foreground" data-testid="cutting-roll-picked-summary">
                {form.roll_ids.length} gulungan dipilih · sisa terpilih{' '}
                {fmtQty(rolls.filter((r) => form.roll_ids.includes(r.id))
                  .reduce((s, r) => s + Number(r.remaining ?? (r.uom === 'kg' ? r.remaining_kg : r.remaining_m) ?? 0), 0))} {rollMeta.uom}
                {Number(form.planned_input_qty) > 0 && ` · rencana pakai ${fmtQty(form.planned_input_qty)} ${selectedMaterial.unit}`}
              </p>
            )}
          </Field>
        )}

        {selectedMaterial && rollMeta.roll_required && rolls.length === 0 && (
          <Notice tone="danger" icon={AlertCircle} testId="cutting-no-rolls-warning">
            Kain ini <b>belum punya gulungan</b> di sistem, jadi order tidak bisa disimpan — tidak akan bisa dibuktikan
            gulungan mana yang dipotong. Terbitkan gulungannya dulu di <b>Gudang › Roll Kain › tab “Penerimaan tanpa roll”</b>,
            atau isi Rincian Roll saat Penerimaan Barang.
          </Notice>
        )}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label={`Rencana pemakaian kain (${selectedMaterial?.unit || 'satuan'})`} required>
            <Input type="number" step="0.01" min="0" value={form.planned_input_qty}
              onChange={(e) => setForm((f) => ({ ...f, planned_input_qty: e.target.value }))}
              data-testid="cutting-planned-input" required />
          </Field>
          <Field label="Target potongan (pcs)" required>
            <Input type="number" step="1" min="0" value={form.planned_output_qty}
              onChange={(e) => setForm((f) => ({ ...f, planned_output_qty: e.target.value }))}
              data-testid="cutting-planned-output" required />
          </Field>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {/* Style/produk DARI MASTER (2026-08-21): BOM (per model+size) & produksi harus tahu potongan milik produk mana. */}
          <Field label="Model / style (dari Master Produk)" required
            hint="Wajib dipilih dari master supaya BOM & produksi mengenali produknya.">
            {/* 2026-11-07: bisa dicari (kode/nama); label memuat ukuran + jumlah warna variannya. */}
            <div className="flex gap-2">
              <SmartNativeSelect value={form.model_id}
                onChange={(e) => onPickModel(e.target.value)}
                className="h-9 w-full" wrapperClassName="flex-1 min-w-0" searchable
                searchPlaceholder="Cari kode atau nama model…"
                data-testid="cutting-model-select">
                <option value="">— pilih model —</option>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {`${m.code ? `${m.code} · ` : ''}${m.name || ''}`
                      + (modelSummary[m.id] ? ` — ${modelSummary[m.id]}` : ' — belum ada varian')}
                  </option>
                ))}
              </SmartNativeSelect>
              <Button type="button" variant="outline" onClick={openNewModel}
                className="shrink-0" data-testid="cutting-new-model-btn"><Plus />Model baru</Button>
            </div>
          </Field>
          <Field label="Varian (warna · ukuran · SKU)"
            hint={form.model_id
              ? (variants.length
                ? `${variantOptions.length} varian milik model ini${poLinePicked?.size_id ? ` (ukuran baris PO ${poLinePicked.size || ''})` : ''}.`
                : 'Model ini belum punya varian — pilih ukuran di bagian BOM di bawah.')
              : 'Pilih model dulu.'}>
            <SmartNativeSelect value={form.variant_id}
              onChange={(e) => onPickVariant(e.target.value)}
              disabled={!form.model_id || !variants.length}
              className="h-9 w-full" searchable searchPlaceholder="Cari warna, ukuran, atau SKU…"
              data-testid="cutting-variant-select">
              <option value="">{!form.model_id ? '— pilih model dulu —' : (variants.length ? '— pilih warna · ukuran —' : '(model belum punya varian)')}</option>
              {variantOptions.map((v) => (
                <option key={v.id} value={v.id}>{variantLabel(v)}</option>
              ))}
            </SmartNativeSelect>
          </Field>
        </div>

        {form.model_id && poLines.length > 0 && (
          <Field label="Baris PO (opsional)"
            hint="Tautkan ke baris PO produksi supaya ukuran & BOM per ukuran mengikuti PO, dan kain terpakai mengurangi kebutuhan material PO itu.">
            <SmartNativeSelect value={form.po_item_id} onChange={(e) => pickPoLine(e.target.value)}
              className="h-9 w-full" data-testid="cutting-po-line-select">
              <option value="">— tanpa baris PO —</option>
              {poLines.map((ln) => (
                <option key={ln.id} value={ln.id}>
                  {`${ln.po_number} · ${ln.size || '-'}${ln.color ? ` · ${ln.color}` : ''}${ln.sku ? ` · ${ln.sku}` : ''} · ${fmtNum(ln.qty, 0)} pcs`}
                </option>
              ))}
            </SmartNativeSelect>
          </Field>
        )}

        {form.model_id && (
          <p className="text-xs text-muted-foreground" data-testid="cutting-style-preview">
            Potongan akan tercatat sebagai <strong className="text-foreground">
              {form.style_name}{form.output_color ? ` · ${form.output_color}` : ''}{form.output_size ? ` · ${form.output_size}` : ''}
            </strong>{form.style_sku ? ` (kode master ${form.style_sku})` : ''}
          </p>
        )}

        {/* ── KEBUTUHAN MENURUT BOM (2026-08-23): angka dari BOM model+ukuran; bila tidak cocok, alasannya ditulis. */}
        {form.model_id && (
          <GlassCard className="space-y-2 p-3" data-testid="cutting-bom-card">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="inline-flex items-center gap-1.5 text-sm font-semibold text-foreground">
                <Layers className="h-4 w-4 text-primary" />
                Kebutuhan menurut BOM
                {bomLoading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                {bomReq?.has_bom && (
                  <span className="font-normal text-muted-foreground">
                    · BOM versi {bomReq.bom_version} ukuran {bomReq.size_code || '—'}
                  </span>
                )}
              </p>
              {bomReq?.fabric?.qty_total > 0 && (
                <Button type="button" size="sm" onClick={useBomQty} data-testid="cutting-use-bom-qty">
                  Pakai angka BOM ({fmtQtyTrim(bomReq.fabric.qty_total)} {bomReq.fabric.unit})
                </Button>
              )}
            </div>

            {/* Ukuran cadangan: model yang BOM-nya ada tapi variannya belum didaftarkan tetap bisa memakai BOM-nya. */}
            {!variants.length && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-muted-foreground">Model ini belum punya varian — pilih ukuran untuk membaca BOM-nya:</span>
                <SmartNativeSelect value={sizeId} onChange={(e) => pickSize(e.target.value)}
                  className="h-8 w-48" wrapperClassName="w-48" data-testid="cutting-bom-size-select">
                  <option value="">— pilih ukuran —</option>
                  {sizes.map((s) => (
                    <option key={s.id} value={s.id}>
                      {`${s.code}${s.name && s.name !== s.code ? ` (${s.name})` : ''}${sizesWithBom.has(s.id) ? ' · ada BOM' : ''}`}
                    </option>
                  ))}
                </SmartNativeSelect>
              </div>
            )}

            {bomReq?.has_bom && bomReq.panel && !bomReq.fabric && (
              <div className="space-y-1 text-xs text-foreground/90" data-testid="cutting-bom-panel">
                <p>
                  Potongan yang dihasilkan: <strong>{bomReq.panel.code}</strong>
                  {Number(bomReq.panel.unit_cost) > 0
                    ? <span className="text-muted-foreground"> · biaya saat ini {fmtRp(bomReq.panel.unit_cost)}/pcs (rata-rata)</span>
                    : <span className="text-muted-foreground"> · belum berbiaya — lahir dari kain yang dipotong ÷ pcs jadi</span>}
                </p>
                <p className="text-muted-foreground">
                  BOM memakai potongan (bukan kg kain). Isi <strong>rencana kain</strong> manual; yang menjadi
                  biaya adalah kain yang <em>benar-benar</em> terpakai saat lapor progres.
                </p>
                {bomReq.accessories?.length > 0 && (
                  <p className="text-muted-foreground" data-testid="cutting-bom-accessories">
                    Aksesoris yang ikut dibutuhkan:{' '}
                    {bomReq.accessories.map((a) => (
                      <span key={a.material_id || a.code} className="mr-2 text-foreground/80">
                        {a.code || a.name} {fmtQtyTrim(a.qty_per_pcs)} {a.unit}/pcs
                      </span>
                    ))}
                  </p>
                )}
              </div>
            )}

            {bomReq?.has_bom && bomReq.fabric ? (
              <div className="space-y-1 text-xs text-foreground/90">
                <p data-testid="cutting-bom-fabric">
                  Kain <strong>{bomReq.fabric.code || bomReq.fabric.name}</strong>:{' '}
                  <strong>{fmtQtyTrim(bomReq.fabric.qty_per_pcs)} {bomReq.fabric.unit}</strong>/pcs
                  {Number(form.planned_output_qty) > 0 ? (
                    <> × {fmtNum(form.planned_output_qty, 0)} pcs ={' '}
                      <strong className="text-primary">{fmtQtyTrim(bomReq.fabric.qty_total)} {bomReq.fabric.unit}</strong>
                      {bomReq.fabric.unit_cost > 0 && (
                        <span className="text-muted-foreground"> · nilai {fmtRp(bomReq.fabric.amount_total)}</span>
                      )}
                    </>
                  ) : (
                    <span className="text-muted-foreground"> — isi target potongan (pcs) untuk melihat totalnya</span>
                  )}
                </p>
                {Number(form.planned_input_qty) > 0 && bomReq.fabric.qty_total > 0 &&
                  Math.abs(Number(form.planned_input_qty) - bomReq.fabric.qty_total) / bomReq.fabric.qty_total > 0.1 && (
                  <p className="inline-flex items-start gap-1 text-[hsl(var(--warning-text))]" data-testid="cutting-bom-deviation">
                    <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />
                    Rencana manual {fmtQtyTrim(form.planned_input_qty)} {bomReq.fabric.unit} berbeda
                    lebih dari 10% dari kebutuhan BOM {fmtQtyTrim(bomReq.fabric.qty_total)} {bomReq.fabric.unit}
                    {' '}— pastikan memang disengaja (mis. ada penyusutan/marker khusus).
                  </p>
                )}
                {bomReq.accessories?.length > 0 && (
                  <p className="text-muted-foreground" data-testid="cutting-bom-accessories">
                    Aksesoris yang ikut dibutuhkan:{' '}
                    {bomReq.accessories.map((a) => (
                      <span key={a.material_id || a.code} className="mr-2 text-foreground/80">
                        {a.code || a.name} {fmtQtyTrim(a.qty_per_pcs)} {a.unit}/pcs
                        {Number(form.planned_output_qty) > 0 && ` (total ${fmtQtyTrim(a.qty_total)} ${a.unit})`}
                      </span>
                    ))}
                  </p>
                )}
              </div>
            ) : !bomLoading && !bomReq?.panel && (
              <p className="text-xs text-muted-foreground">
                {bomReq?.gaps?.length ? null : 'Pilih varian (warna · ukuran) untuk membaca BOM ukuran itu.'}
              </p>
            )}

            {bomReq?.gaps?.length > 0 && (
              <ul className="space-y-1" data-testid="cutting-bom-gaps">
                {bomReq.gaps.map((g, i) => (
                  <li key={i} className="flex items-start gap-1 text-xs text-[hsl(var(--warning-text))]">
                    <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />
                    <span>
                      {g.message}
                      {g.target && g.target !== 'cutting-orders' && (
                        <Button type="button" variant="link" size="sm" className="ml-1 h-auto p-0 text-xs"
                          onClick={() => (typeof onNavigate === 'function'
                            ? onNavigate(g.target)
                            : (window.location.hash = g.target))}
                          data-testid={`cutting-bom-fix-${g.code}`}>
                          {g.action || 'Perbaiki'}
                        </Button>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            )}

            {bomReq?.has_bom === false && bomReq?.other_sizes_with_bom?.length > 0 && (
              <p className="text-xs text-muted-foreground">
                Ukuran yang sudah punya BOM untuk model ini:{' '}
                {bomReq.other_sizes_with_bom.map((s) => s.size_code || s.size_id).join(', ')}
              </p>
            )}
          </GlassCard>
        )}

        <Field label="Catatan">
          <Textarea value={form.notes} rows={2}
            onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
            data-testid="cutting-notes" />
        </Field>
      </FormPopup>

      {/* ── FORM MODEL BARU (master produk) — menggantikan form cutting sementara ── */}
      <FormPopup open={showNewModel} onClose={() => setShowNewModel(false)} ukuran="pendek"
        judul="Model / style baru" keterangan="Model ini tersimpan di Master Produk sehingga BOM & produksi bisa memakainya."
        onSimpan={createModel} menyimpan={savingModel} labelSimpan="Simpan model" testId="cutting-new-model-modal">
        <Field label="Nama model / style" required>
          <Input value={newModel.name} autoFocus
            onChange={(e) => setNewModel((n) => ({ ...n, name: e.target.value }))}
            placeholder="mis. Dress Jemina" data-testid="new-model-name" />
        </Field>
        <Field label="Kategori produk" required={!newModel.code.trim()}
          hint="Kode model dibuat otomatis dari kategori ini (mis. CLN-0001).">
          <SmartNativeSelect value={newModel.category_id}
            onChange={(e) => setNewModel((n) => ({ ...n, category_id: e.target.value }))}
            className="h-9 w-full" data-testid="new-model-category">
            <option value="">— pilih kategori —</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>{`${c.name}${c.sku_prefix ? ` (${c.sku_prefix})` : ''}`}</option>
            ))}
          </SmartNativeSelect>
        </Field>
        <Field label="Kode model (opsional)" hint="Kosongkan supaya dibuat otomatis dari kategori.">
          <Input value={newModel.code}
            onChange={(e) => setNewModel((n) => ({ ...n, code: e.target.value }))}
            placeholder="mis. DRS-JMN" data-testid="new-model-code" />
        </Field>
      </FormPopup>

      {/* ── RINCIAN ORDER (popup) ─────────────────────────────────────── */}
      {detail && (
        <DetailPopup open={!progOpen} onClose={() => setDetail(null)} judul={`Cutting ${detail.number}`} testId="cutting-detail-panel"
          keterangan={`Dibuat ${fmtDateTime(detail.created_at)} oleh ${detail.created_by_name || '—'}`}
          status={<StatusPill status={detail.status} />}
          aksi={<>
            {detail.status === 'draft' && (
              <Button size="sm" onClick={() => doAction('/start', {}, 'Cutting dimulai — master potongan dibuat.')}
                disabled={acting} data-testid="cutting-start-btn"><PlayCircle />Mulai cutting</Button>
            )}
            {detail.status === 'in_progress' && (
              <Button size="sm" onClick={() => setProgOpen(true)} disabled={acting} data-testid="cutting-progress-open">
                <PencilLine />Catat progres
              </Button>
            )}
            {detail.status === 'in_progress' && (
              <Button size="sm" variant="success" onClick={() => doAction('/complete', {}, 'Cutting selesai — HPP potongan dihitung.')}
                disabled={acting} data-testid="cutting-complete-btn"><CheckCircle2 />Selesaikan</Button>
            )}
            {(detail.status === 'draft' || detail.status === 'in_progress') && (
              <Button size="sm" variant="destructive" onClick={() => doAction('/cancel', { reason: 'dibatalkan user' }, 'Cutting dibatalkan.')}
                disabled={acting} data-testid="cutting-cancel-btn"><XCircle />Batalkan</Button>
            )}
            {detail.status === 'completed' && detail.output_material_code && (
              <Button size="sm" variant="outline" onClick={() => onNavigate?.('cutting-panels')} data-testid="cutting-goto-panels">
                <Package />Lihat master potongan
              </Button>
            )}
          </>}>
          {detailLoading && <div className="h-1 animate-pulse rounded bg-primary" />}

          <div className="grid grid-cols-1 items-stretch gap-3 md:grid-cols-[1fr_auto_1fr]">
            <GlassCard className="p-3">
              <p className="text-xs text-muted-foreground">Kain (input)</p>
              <p className="mt-0.5 text-sm font-medium text-foreground">{detail.input_material_name}</p>
              <p className="text-xs tabular-nums text-muted-foreground">{detail.input_material_code}</p>
              <p className="mt-2 text-sm text-foreground">
                Terpakai <b>{fmtNum(detail.consumed_input_qty, 2)}</b> / {fmtNum(detail.planned_input_qty, 2)} {detail.input_unit}
              </p>
              <p className="text-xs text-muted-foreground">Stok gudang saat ini: {fmtNum(detail.input_stock, 2)} {detail.input_unit}</p>
              <p className="text-xs text-muted-foreground">Gudang sumber: <b className="text-foreground">{detail.location_name || '—'}</b></p>
              {detailRolls.roll_required && (
                <p className="mt-1.5 text-xs text-primary" data-testid="cutting-roll-summary">
                  {detailRolls.items.length} gulungan bersisa · total {fmtQty(detailRolls.total_remaining)} {detailRolls.uom}
                </p>
              )}
              {detailRolls.other_location_count > 0 && (
                <p className="mt-1 text-xs text-[hsl(var(--warning-text))]" data-testid="cutting-roll-other-location">
                  {detailRolls.other_location_count} gulungan kain ini ada di gudang lain — tidak bisa dipakai untuk order di gudang ini.
                </p>
              )}
              {(detail.roll_ids || []).some((r) => Number(r.consumed_qty || 0) > 0) && (
                <p className="mt-1 text-xs text-muted-foreground">
                  Sudah dipakai:{' '}
                  {(detail.roll_ids || []).filter((r) => Number(r.consumed_qty || 0) > 0)
                    .map((r) => `${r.roll_no} (${fmtQty(r.consumed_qty)})`).join(', ')}
                </p>
              )}
            </GlassCard>
            <div className="hidden items-center justify-center md:flex">
              <ArrowRight className="h-5 w-5 text-muted-foreground" />
            </div>
            <GlassCard className="p-3">
              <p className="text-xs text-muted-foreground">Potongan (output)</p>
              <p className="mt-0.5 text-sm font-medium text-foreground">
                {detail.output_material_name || `${detail.style_name} ${detail.output_color} ${detail.output_size}`}
              </p>
              <p className="text-xs tabular-nums text-muted-foreground">{detail.output_material_code || 'Kode dibuat saat mulai'}</p>
              <p className="mt-2 text-sm text-foreground">
                Jadi <b>{fmtNum(detail.produced_qty)}</b> / {fmtNum(detail.planned_output_qty)} pcs
              </p>
              <p className="text-xs text-muted-foreground">
                Stok potongan: {fmtNum(detail.output_stock)} pcs
                {detail.output_unit_cost > 0 && ` · HPP ${fmtRp(detail.output_unit_cost)}/pcs`}
              </p>
            </GlassCard>
          </div>

          {/* Riwayat progres */}
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <p className="inline-flex items-center gap-2 text-sm font-semibold text-foreground">
                <History className="h-4 w-4 text-muted-foreground" />Riwayat progres ({(detail.progress || []).length})
              </p>
              <div className="ml-auto flex flex-wrap gap-2">
                {/* FASE H-6b — pintu ke daftar arus keluar gudang (dokumen MI). */}
                {onNavigate && (detail.progress || []).length > 0 && (
                  <Button size="sm" variant="outline" onClick={() => { setDetail(null); onNavigate('wh-material-issue'); }}
                    data-testid="cutting-open-material-issue"><Package />Lihat di Pengeluaran Material</Button>
                )}
                <TombolUnduh namaBerkas={`progres-${detail.number}`} namaLembar="Progres" baris={detail.progress || []}
                  testId="cutting-progress-unduh"
                  kolom={[
                    { label: 'Waktu', nilai: (p) => fmtDateTime(p.created_at) },
                    { label: `Kain (${detail.input_unit || 'satuan'})`, nilai: (p) => Number(p.input_consumed || 0) },
                    { label: 'Potongan (pcs)', nilai: (p) => Number(p.output_qty || 0) },
                    { label: 'Sisa ke stok', nilai: (p) => Number(p.leftover_qty || 0) },
                    { label: 'Limbah', nilai: (p) => Number(p.waste_qty || 0) },
                    { label: 'Nilai kain keluar', nilai: (p) => Number(p.value_out || 0) },
                    { label: 'HPP potongan / pcs', nilai: (p) => Number(p.panel_unit_cost_after || 0) },
                    { label: 'Gulungan dipakai', nilai: (p) => (p.roll_consumption || []).map((rc) => `${rc.roll_no} −${fmtQty(rc.qty)}`).join(', ') },
                    { label: 'Dokumen keluar', nilai: (p) => p.material_issue_number || 'Belum ada' },
                    { label: 'Catatan', nilai: (p) => p.note || '' }, { label: 'Oleh', nilai: (p) => p.created_by_name || '' },
                  ]} />
              </div>
            </div>
            {(detail.progress || []).length === 0 ? (
              <p className="py-4 text-center text-sm text-muted-foreground">Belum ada progres dicatat.</p>
            ) : (
              <div className="overflow-x-auto">
                <Table data-testid="cutting-progress-table">
                  <TableHeader><TableRow>
                    <TableHead>Waktu</TableHead><TableHead className="text-right">Kain</TableHead>
                    <TableHead className="text-right">Potongan</TableHead><TableHead className="text-right">Sisa ke stok</TableHead>
                    <TableHead className="text-right">Limbah</TableHead>
                    {/* SESI #32 — nilai yang BERPINDAH dari kain ke potongan */}
                    <TableHead className="text-right">Nilai kain keluar</TableHead><TableHead className="text-right">HPP potongan</TableHead>
                    <TableHead>Gulungan dipakai</TableHead><TableHead>Dokumen keluar</TableHead>
                    <TableHead>Catatan</TableHead><TableHead>Oleh</TableHead>
                  </TableRow></TableHeader>
                  <TableBody>
                    {(detail.progress || []).map((p) => (
                      <TableRow key={p.id}>
                        <TableCell className="whitespace-nowrap text-muted-foreground">{fmtDateTime(p.created_at)}</TableCell>
                        <TableCell className="text-right tabular-nums">{fmtNum(p.input_consumed, 2)}</TableCell>
                        <TableCell className="text-right tabular-nums">{fmtNum(p.output_qty)}</TableCell>
                        <TableCell className="text-right tabular-nums text-muted-foreground">{fmtNum(p.leftover_qty || 0, 2)}</TableCell>
                        <TableCell className="text-right tabular-nums text-muted-foreground">{fmtNum(p.waste_qty, 2)}</TableCell>
                        {/* Kalau kainnya belum bernilai, alasannya DITULIS (bukan "-"). */}
                        <TableCell className="text-right" data-testid={`cutting-progress-value-${p.id}`}>
                          {Number(p.value_out || 0) > 0 ? (
                            <>
                              <span className="font-medium tabular-nums text-foreground">{fmtRp(p.value_out)}</span>
                              <span className="block text-xs text-muted-foreground">{fmtRp(p.fabric_unit_cost)}/{detail.input_unit || 'satuan'}</span>
                            </>
                          ) : (
                            <span className="text-xs text-[hsl(var(--warning-text))]">Belum bernilai</span>
                          )}
                        </TableCell>
                        <TableCell className="text-right">
                          {Number(p.panel_unit_cost_after || 0) > 0 ? (
                            <>
                              <span className="font-medium tabular-nums text-foreground">{fmtRp(p.panel_unit_cost_after)}/pcs</span>
                              {Number(p.panel_unit_cost_before || 0) > 0
                                && Number(p.panel_unit_cost_before) !== Number(p.panel_unit_cost_after) && (
                                <span className="block text-xs text-muted-foreground">dari {fmtRp(p.panel_unit_cost_before)} (rata-rata bergerak)</span>
                              )}
                            </>
                          ) : <span className="text-muted-foreground">—</span>}
                        </TableCell>
                        <TableCell data-testid={`cutting-progress-rolls-${p.id}`}>
                          {(p.roll_consumption || []).length ? (
                            <div className="flex flex-wrap gap-1">
                              {p.roll_consumption.map((rc) => (
                                <span key={rc.roll_id} title={`sisa setelah dipakai: ${fmtQty(rc.remaining_after)}`}>
                                  <StatusBadge status="" label={`${rc.roll_no} −${fmtQty(rc.qty)}`} tone="primary" className="tabular-nums" />
                                </span>
                              ))}
                            </div>
                          ) : (
                            <span className="text-muted-foreground">{p.roll_id ? 'Tercatat' : '—'}</span>
                          )}
                        </TableCell>
                        {/* FASE H-6b — nomor dokumen "Pengeluaran Material" per progres; kosong HARUS terlihat. */}
                        <TableCell data-testid={`cutting-progress-mi-${p.id}`}>
                          {p.material_issue_number
                            ? <span title="Dokumen Pengeluaran Material yang mencatat arus keluar kain ini">
                                <StatusBadge status="" label={p.material_issue_number} tone="success" className="tabular-nums" /></span>
                            : <StatusBadge status="" label="Belum ada" tone="warning" />}
                        </TableCell>
                        <TableCell className="text-muted-foreground">{p.note || '—'}</TableCell>
                        <TableCell className="text-muted-foreground">{p.created_by_name || '—'}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </div>

          {detail.notes && <p className="text-sm text-muted-foreground">Catatan: {detail.notes}</p>}
        </DetailPopup>
      )}

      {/* ── FORM CATAT PROGRES (popup panjang; rincian disembunyikan sementara) ── */}
      {detail && detail.status === 'in_progress' && (
        <FormPopup open={progOpen} onClose={() => setProgOpen(false)} ukuran="panjang" testId="cutting-progress-form"
          judul={`Catat progres potong · ${detail.number}`}
          keterangan={`Setiap catatan langsung memotong stok kain, menambah stok potongan, dan mengurangi sisa gulungan yang ditunjuk${detailRolls.roll_required ? ' — untuk kain yang dilacak per gulungan, gulungan wajib dipilih.' : '.'}`}
          onSimpan={submitProgress} menyimpan={acting} labelSimpan="Catat"
          bisaSimpan={!rollBlocking && !(allocPreview.shortage > 0)}>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label={`Kain terpakai (${effProgUom || detail.input_unit})`} required>
              <div className="flex gap-2">
                <Input type="number" step="0.0001" min="0" value={prog.input_consumed}
                  onChange={(e) => setProg((p) => ({ ...p, input_consumed: e.target.value }))}
                  data-testid="cutting-progress-input" required />
                <UomSelect opt={progUomOpt} value={effProgUom} fallbackUnit={detail.input_unit}
                  onChange={(e) => setProg((p) => ({ ...p, input_uom: e.target.value }))}
                  testId="cutting-progress-uom" className="w-24 shrink-0" />
              </div>
              <UomConversionHint opt={progUomOpt} qty={prog.input_consumed} unit={effProgUom}
                fallbackUnit={detail.input_unit} className="mt-1" testId="cutting-progress-uom-hint" />
            </Field>
            <Field label="Potongan jadi (pcs)" required>
              <Input type="number" step="1" min="0" value={prog.output_qty}
                onChange={(e) => setProg((p) => ({ ...p, output_qty: e.target.value }))}
                data-testid="cutting-progress-output" required />
            </Field>
            <Field label={`Sisa kain kembali ke stok (${effProgUom || detail.input_unit})`}
              hint="Potongan kain yang masih bisa dipakai — kembali ke stok kain pada harga kain, tidak ikut nilai potongan.">
              <Input type="number" step="0.0001" min="0" value={prog.leftover_qty}
                onChange={(e) => setProg((p) => ({ ...p, leftover_qty: e.target.value }))}
                data-testid="cutting-progress-leftover" />
            </Field>
            <Field label="Limbah" hint="Kain terbuang (bagian dari kain terpakai) — nilainya ikut biaya potongan.">
              <div className="flex gap-2">
                <Input type="number" step="0.0001" min="0" value={prog.waste_qty}
                  onChange={(e) => setProg((p) => ({ ...p, waste_qty: e.target.value }))}
                  data-testid="cutting-progress-waste" />
                <UomSelect opt={progUomOpt} value={prog.waste_uom || effProgUom} fallbackUnit={detail.input_unit}
                  onChange={(e) => setProg((p) => ({ ...p, waste_uom: e.target.value }))}
                  testId="cutting-progress-waste-uom" className="w-24 shrink-0" />
              </div>
            </Field>
          </div>
          {(detailRolls.roll_required || (detail.roll_ids || []).length > 0) && (
            <Field
              label={detailRolls.roll_required ? 'Gulungan yang dipotong (wajib)' : 'Gulungan yang dipotong'}
              required={detailRolls.roll_required}
              hint={detailRolls.items.length
                ? 'Centang gulungan yang benar-benar dipotong. Pemakaian dibagi otomatis FIFO (gulungan tertua dulu) dan sisanya langsung berkurang.'
                : ''}>
              {detailRolls.items.length === 0 ? (
                <Notice tone="danger" icon={AlertCircle} testId="cutting-progress-no-rolls"
                  action={onNavigate && (
                    <Button type="button" size="sm" variant="outline" onClick={() => onNavigate('wms-fabric-rolls')} data-testid="cutting-goto-rolls">
                      Buka sekarang
                    </Button>
                  )}>
                  Kain ini tidak punya gulungan bersisa. Terbitkan gulungan di <b>Gudang › Roll Kain › “Penerimaan tanpa roll”</b>.
                </Notice>
              ) : (
                <>
                  <div className="max-h-48 divide-y divide-[var(--glass-border)] overflow-y-auto rounded-lg border border-[var(--glass-border)]"
                    data-testid="cutting-progress-roll-picker">
                    {detailRolls.items.map((r) => {
                      const checked = (prog.roll_ids || []).includes(r.id);
                      const remaining = Number(r.remaining ?? (r.uom === 'kg' ? r.remaining_kg : r.remaining_m) ?? 0);
                      const inPlan = allocPreview.plan.find((p) => p.roll_id === r.id);
                      return (
                        <label key={r.id}
                          className={`flex cursor-pointer items-center gap-2 px-3 py-2 text-sm hover:bg-foreground/5 ${checked ? 'bg-primary/5' : ''}`}
                          data-testid={`cutting-progress-roll-${r.roll_no}`}>
                          <Checkbox checked={checked} onCheckedChange={() => toggleProgRoll(r.id)}
                            data-testid={`cutting-progress-roll-cb-${r.roll_no}`} />
                          <span className="tabular-nums text-foreground">{r.roll_no}</span>
                          <span className="text-xs text-muted-foreground">
                            sisa {fmtQty(remaining)} {r.uom}
                            {r.color_lot ? ` · lot ${r.color_lot}` : ''}
                            {r.source_receipt_number ? ` · dari ${r.source_receipt_number}` : ''}
                          </span>
                          {inPlan && (
                            <span className="ml-auto text-xs font-semibold text-primary">
                              pakai {fmtQty(inPlan.qty)} → sisa {fmtQty(inPlan.remaining_after)}
                            </span>
                          )}
                        </label>
                      );
                    })}
                  </div>
                  {/* Pratinjau alokasi FIFO — supaya tidak ada kejutan setelah ditekan */}
                  {(prog.roll_ids || []).length > 0 && Number(prog.input_consumed) > 0 && (
                    <p className={`mt-1.5 text-xs ${allocPreview.shortage > 0 ? 'text-[hsl(var(--danger-text))]' : 'text-[hsl(var(--success-text))]'}`}
                      data-testid="cutting-alloc-preview">
                      {allocPreview.shortage > 0 ? (
                        <>Sisa gulungan terpilih kurang {fmtQty(allocPreview.shortage, 3)} {detailRolls.uom} —
                          tersedia {fmtQty(allocPreview.available)} untuk {fmtQty(prog.input_consumed)}.
                          Pilih gulungan tambahan atau kurangi jumlah pemakaian.</>
                      ) : (
                        <>Rencana: {allocPreview.plan.map((p) => `${p.roll_no} −${fmtQty(p.qty)}`).join(' · ')}</>
                      )}
                    </p>
                  )}
                  {rollBlocking && (
                    <p className="mt-1.5 text-xs text-[hsl(var(--warning-text))]" data-testid="cutting-roll-required-hint">
                      Pilih minimal satu gulungan — progres tidak bisa dicatat tanpa itu.
                    </p>
                  )}
                </>
              )}
            </Field>
          )}
          <Field label="Catatan">
            <Input value={prog.note} onChange={(e) => setProg((p) => ({ ...p, note: e.target.value }))}
              placeholder="mis. shift pagi" data-testid="cutting-progress-note" />
          </Field>
        </FormPopup>
      )}
    </PageLayout>
  );
}

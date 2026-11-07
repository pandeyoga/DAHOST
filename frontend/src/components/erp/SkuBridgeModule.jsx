/**
 * SkuBridgeModule — **Jembatan SKU: Marketing ⇄ Gudang** (Sesi #20)
 * ═══════════════════════════════════════════════════════════════════════════
 * MASALAH YANG DITUTUP LAYAR INI (diukur, bukan ditebak)
 * ───────────────────────────────────────────────────────────────────────────
 * Keluhan pemilik: "list barang dari marketing untuk dikirimkan oleh tim gudang
 * tidak ada yang sama, id-nya antara gudang dan marketing tidak sinkron".
 *
 * Terukur pada data hidup: **0 dari 601** baris pesanan marketing menunjuk
 * master gudang, dan **83 SKU platform** tidak dikenal master. Penyebabnya dua
 * semesta identitas — marketing memakai `platform_sku_id` (angka milik
 * TikTok/Shopee), gudang memakai UUID + kode FG.
 *
 * Tiga aksi yang mengikuti keadaan master (bukan satu tombol "cocokkan" yang menebak):
 *   · **Tautkan**            — varian (model+warna+ukuran) SUDAH ada di master.
 *   · **Buat Varian**        — modelnya ada, warna/ukuran ini belum.
 *   · **Buat Master**        — belum ada yang mirip; model + varian baru dibuat.
 *
 * Backend: `/api/sku-bridge/*` (core/sku_bridge.py). Semua penulisan tautan
 * lewat SSOT itu; layar ini tidak pernah menulis dokumen sendiri.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout (dulu kepala besar 3 baris + ikon, 5 kartu KPI berwarna,
 * kartu kemajuan dengan angka 30 px, tab bar di dalam kartu); bagian dipilih lewat pil; 4 StatTile berketerangan
 * (disembunyikan bila belum ada pesanan); semua tabel TabelData + unduhan Excel/CSV; buat master = FormPopup,
 * pilih barang manual = popup daftar pilihan; Dipakai juga di Portal Toko (props sama: `onNavigate`).
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Link2, Search, RefreshCw, Loader2, CheckCircle2, Plus,
  Wand2, Trash2, Eye, Sparkles, ArrowRight,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import { Checkbox } from '@/components/ui/checkbox';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup from '@/components/ui/detail-popup';
import { toast } from 'sonner';
import { apiGet, apiPost, apiDelete } from '@/lib/api';
import { ColorSelect, SizeSelect, ModelSelect } from './masters/MasterSelects';
// Sesi #28 — onboarding PER PRODUK + master Opsi (dimensi ke-3).
import { ProductOnboardingTab, VariantOptionsTab } from './VariantOnboardingPanel';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';

const fmt = (v) => Number(v || 0).toLocaleString('id-ID');
const rp = (v) => `Rp ${fmt(Math.round(Number(v || 0)))}`;

const ACTION_META = {
  map: { label: 'Tautkan', tone: 'success', icon: Link2, hint: 'Varian sudah ada di master — cukup ditautkan' },
  create_variant: { label: 'Buat varian', tone: 'primary', icon: Plus, hint: 'Model sudah ada, warna/ukuran ini belum' },
  create_master: { label: 'Buat master', tone: 'warning', icon: Sparkles, hint: 'Belum ada master yang mirip — buat model + varian baru' },
};
const METHOD_LABEL = { manual: 'Manual', auto: 'Otomatis', create_master: 'Buat master', product_onboarding: 'Produk baru (per produk)' };

/** Baris alat satu bagian: kiri penyaring/teks, kanan alat (turun ke baris sendiri di HP). */
function BarisAlat({ kiri, kanan }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {kiri}
      <div className="ml-auto flex shrink-0 flex-wrap items-center gap-2">{kanan}</div>
    </div>
  );
}
function KotakCari({ value, onChange, placeholder, testId }) {
  return (
    <div className="relative w-full sm:w-64">
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
      <Input value={value} onChange={(e) => onChange(e.target.value)} className="pl-8" placeholder={placeholder} data-testid={testId} />
    </div>
  );
}

/* ─── Popup: pilih sasaran manual (daftar pilihan, satu klik = tautkan) ───── */
function ManualPickDialog({ row, onClose, onDone }) {
  const [q, setQ] = useState('');
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await apiGet(`/sku-bridge/targets?q=${encodeURIComponent(q)}&limit=60`);
      setRows(d.rows || []);
    } catch (e) { toast.error(e.message); } finally { setLoading(false); }
  }, [q]);

  useEffect(() => { const t = setTimeout(load, 300); return () => clearTimeout(t); }, [load]);

  const pick = async (c) => {
    setSaving(c.target_id);
    try {
      const body = {
        platform_sku_id: row.platform_sku_id,
        account_id: row.account_id,
        product_name: row.product_name,
        variation: row.variation,
      };
      if (c.kind === 'catalog_item') body.catalog_item_id = c.target_id;
      else body.variant_id = c.target_id;
      const res = await apiPost('/sku-bridge/map', body);
      toast.success(res.message || 'SKU ditautkan');
      onDone();
    } catch (e) { toast.error(e.message); } finally { setSaving(''); }
  };

  const kolom = [
    { kunci: 'nama', label: 'Barang gudang', hp: 'judul', isi: (c) => <span className="font-medium">{c.label || '(tanpa nama)'}</span> },
    { kunci: 'sku', label: 'SKU', hp: 'keterangan', isi: (c) => <span className="tabular-nums">{c.sku || '—'}</span> },
    { kunci: 'jenis', label: 'Jenis', hp: false, isi: (c) => (c.kind === 'catalog_item' ? 'Item katalog jual' : 'Varian model internal') },
    { kunci: 'stok', label: 'Stok', rata: 'kanan', isi: (c) => (c.stock != null ? <span className="tabular-nums">{fmt(c.stock)}</span> : '—') },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (c) => (
      <Button size="sm" disabled={saving === c.target_id} onClick={() => pick(c)} data-testid={`manual-pick-${c.sku || c.target_id}`}>
        {saving === c.target_id ? <Loader2 className="animate-spin" /> : <Link2 />}Tautkan
      </Button>) },
  ];

  return (
    <DetailPopup open onClose={onClose} testId="manual-pick-dialog" judul="Pilih barang gudang untuk SKU ini"
      keterangan={`${row.product_name || '(tanpa nama)'} · variasi ${row.variation || '—'} · ${fmt(row.pcs)} pcs di ${fmt(row.orders)} pesanan`}>
      <KotakCari value={q} onChange={setQ} placeholder="Cari nama produk / SKU master" testId="manual-pick-search" />
      {loading && rows.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Mencari…</p>
      ) : (
        <TabelData kolom={kolom} baris={rows} kunci={(c) => `${c.kind}-${c.target_id}`} testId="manual-pick-table"
          kosong={<EmptyState title="Tidak ada master yang cocok" description='Ubah kata pencarian, atau pakai tombol "Buat master" di daftar utama.' />} />
      )}
    </DetailPopup>
  );
}

/* ─── Popup form: buat master / varian dari SKU ────────────────────────────── */
function CreateMasterDialog({ row, onClose, onDone }) {
  const mm = row.model_match || {};
  const suggestedModelId = row.recommended_action === 'create_variant' ? (mm.model_id || '') : '';
  // Nama model TIDAK diketik: kalau produknya sudah ada, model dipilih dari master;
  // kalau benar-benar baru, namanya DITURUNKAN server dari judul platform dan hanya ditampilkan (gate INV-F14).
  const [form, setForm] = useState({
    model_id: suggestedModelId,
    color_name: row.parsed?.color || '',
    size_code: row.parsed?.size || '',
    retail_price: '',
    hpp: '',
  });
  const [plan, setPlan] = useState(null);
  const [busy, setBusy] = useState(false);
  const useExistingModel = Boolean(form.model_id);

  const payload = (apply) => ({
    platform_sku_id: row.platform_sku_id,
    product_name: row.product_name,
    variation: row.variation,
    account_id: row.account_id,
    model_id: form.model_id || undefined,
    color_name: form.color_name || undefined,
    size_code: form.size_code || undefined,
    retail_price: Number(form.retail_price || 0),
    hpp: Number(form.hpp || 0),
    apply,
  });

  const preview = async () => {
    setBusy(true);
    try { setPlan(await apiPost('/sku-bridge/create-master', payload(false))); }
    catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };

  useEffect(() => { preview(); /* eslint-disable-next-line */ }, [form.model_id, form.color_name, form.size_code]);

  const submit = async () => {
    setBusy(true);
    try {
      const res = await apiPost('/sku-bridge/create-master', payload(true));
      toast.success(res.message || 'Master dibuat & SKU ditautkan');
      onDone();
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" testId="create-master-dialog"
      judul={useExistingModel ? 'Buat varian baru & tautkan' : 'Buat master produk & tautkan'}
      keterangan={`Rantai yang dibuat: ${useExistingModel ? '' : 'model → '}varian → master FG → item katalog toko → pemetaan SKU → pesanan lama ikut tertaut.`}
      onSimpan={submit} menyimpan={busy} labelSimpan="Buat & tautkan"
      aksiKiri={(
        <Button type="button" variant="outline" onClick={preview} disabled={busy} data-testid="cm-preview">
          <Eye />Pratinjau ulang
        </Button>
      )}>
      <p className="text-sm text-muted-foreground">
        Judul dari platform: <span className="font-medium text-foreground">{row.product_name || '(tanpa nama)'}</span>
        {' '}· variasi <b>{row.variation || '—'}</b> · SKU platform <span className="tabular-nums">{row.platform_sku_id}</span>
        {' '}· {fmt(row.pcs)} pcs di {fmt(row.orders)} pesanan
      </p>
      <Isian label="Model produk di master"
        petunjuk={useExistingModel
          ? 'Hanya variannya yang dibuat — model tidak digandakan.'
          : 'Kosong = buat model BARU; namanya diambil dari judul platform (lihat pratinjau) dan bisa diubah nanti di Master Produk.'}>
        <ModelSelect value={form.model_id} onChange={(v) => setForm({ ...form, model_id: v })} label={null} testId="cm-model-select" />
      </Isian>
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Warna" petunjuk="Terbaca dari variasi platform bila cocok dengan master.">
          <ColorSelect value={form.color_name} onChange={(v) => setForm({ ...form, color_name: v })} label={null} testId="cm-color-select" />
        </Isian>
        <Isian label="Ukuran" petunjuk="Kosong = dipakai ALLSIZE.">
          <SizeSelect value={form.size_code} onChange={(v) => setForm({ ...form, size_code: v })} label={null} testId="cm-size-select" />
        </Isian>
        {!useExistingModel && (
          <>
            <Isian label="Harga jual resmi (opsional)" htmlFor="cm-harga">
              <MoneyInput id="cm-harga" value={form.retail_price} onChange={(e) => setForm({ ...form, retail_price: e.target.value })}
                placeholder="0" data-testid="cm-price" />
            </Isian>
            <Isian label="HPP (opsional)" htmlFor="cm-hpp">
              <MoneyInput id="cm-hpp" value={form.hpp} onChange={(e) => setForm({ ...form, hpp: e.target.value })}
                placeholder="0" data-testid="cm-hpp" />
            </Isian>
          </>
        )}
      </div>
      {plan?.plan && (
        <Notice tone="info" icon={Eye} testId="cm-plan" title="Pratinjau">{plan.message}</Notice>
      )}
    </FormPopup>
  );
}

/* ─── Bagian: penyelesaian massal ──────────────────────────────────────────── */
function BulkPanel({ onDone }) {
  const [actions, setActions] = useState({ map: true, create_variant: true, create_master: false });
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);

  const run = async (apply) => {
    const chosen = Object.entries(actions).filter(([, v]) => v).map(([k]) => k);
    if (!chosen.length) { toast.error('Pilih minimal satu jenis aksi.'); return; }
    setBusy(true);
    try {
      const d = await apiPost('/sku-bridge/bulk-resolve', { actions: chosen, limit: 300, apply });
      setRes(d);
      if (apply) { toast.success(d.message); onDone(); }
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };

  const boxes = [
    { key: 'map', title: 'Tautkan yang sudah ada', desc: 'Varian model+warna+ukuran sudah ada di master. Paling aman.' },
    { key: 'create_variant', title: 'Buat varian di model yang cocok', desc: 'Model dikenali, hanya warna/ukuran ini yang belum ada.' },
    { key: 'create_master', title: 'Buat model produk BARU', desc: 'Menambah master produk baru. Pilih sadar — periksa pratinjaunya.' },
  ];
  const hasil = res ? [
    ...(res.applied || []).map((a) => ({ ...a, _kelompok: 'Akan dikerjakan' })),
    ...(res.skipped || []).map((s) => ({ ...s, _kelompok: 'Disisakan untuk Anda' })),
  ] : [];
  const kolomHasil = [
    { kunci: 'kelompok', label: 'Kelompok', hp: 'keterangan', isi: (r) => r._kelompok },
    { kunci: 'barang', label: 'SKU / barang', hp: 'judul', isi: (r) => <span className="font-medium">{r.will_create || r.target_sku || r.product_name || r.platform_sku_id}</span> },
    { kunci: 'aksi', label: 'Aksi', isi: (r) => (r.action
      ? <StatusBadge tone={ACTION_META[r.action]?.tone} label={ACTION_META[r.action]?.label || r.action} />
      : <span className="text-muted-foreground">—</span>) },
    { kunci: 'pcs', label: 'Pcs', hp: false, rata: 'kanan', isi: (r) => (r.pcs != null ? <span className="tabular-nums">{fmt(r.pcs)}</span> : '—') },
    { kunci: 'alasan', label: 'Alasan disisakan', isi: (r) => <span className="text-sm text-muted-foreground">{r.reason || '—'}</span> },
  ];

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Mesin memeriksa setiap SKU yang belum dikenal lalu mengerjakan aksi yang sesuai keadaan masternya. Yang keyakinannya
        kurang tidak dikerjakan otomatis — dikembalikan ke daftar supaya Anda yang memutuskan. Jalankan <b>Pratinjau</b> dulu:
        pratinjau tidak menulis apa pun.
      </p>
      <fieldset className="space-y-2">
        <legend className="sr-only">Jenis aksi yang dikerjakan</legend>
        {boxes.map((b) => (
          <label key={b.key} htmlFor={`bulk-${b.key}`} className="flex cursor-pointer items-start gap-3 text-sm">
            <Checkbox id={`bulk-${b.key}`} checked={!!actions[b.key]} className="mt-0.5"
              onCheckedChange={(v) => setActions({ ...actions, [b.key]: v === true })} data-testid={`bulk-toggle-${b.key}`} />
            <span>
              <span className="font-medium text-foreground">{b.title}</span>
              <span className="block text-xs text-muted-foreground">{b.desc}</span>
            </span>
          </label>
        ))}
      </fieldset>
      <BarisAlat
        kiri={(
          <>
            <Button variant="outline" onClick={() => run(false)} disabled={busy} data-testid="bulk-preview">
              {busy ? <Loader2 className="animate-spin" /> : <Eye />}Pratinjau
            </Button>
            <Button onClick={() => run(true)} disabled={busy || !res} data-testid="bulk-apply">
              <Wand2 />Terapkan
            </Button>
            {!res && <span className="text-sm text-muted-foreground">Pratinjau dulu sebelum menerapkan.</span>}
          </>
        )}
        kanan={res ? (
          <TombolUnduh namaBerkas="sku-selesaikan-massal" namaLembar="Hasil" baris={hasil} testId="bulk-unduh"
            kolom={[
              { label: 'Kelompok', nilai: (r) => r._kelompok },
              { label: 'SKU platform', nilai: (r) => r.platform_sku_id || '' },
              { label: 'SKU / barang', nilai: (r) => r.will_create || r.target_sku || r.product_name || '' },
              { label: 'Aksi', nilai: (r) => ACTION_META[r.action]?.label || r.action || '' },
              { label: 'Pcs', nilai: (r) => (r.pcs != null ? Number(r.pcs) : '') },
              { label: 'Alasan disisakan', nilai: (r) => r.reason || '' },
            ]} />
        ) : null} />

      {res && (
        <div className="space-y-3" data-testid="bulk-result">
          <Notice tone="success" icon={CheckCircle2} title={res.message}>
            Akan dikerjakan {fmt(res.applied_count)} · disisakan untuk Anda {fmt(res.skipped_count)}
            {!res.dry_run && (
              <span className="mt-0.5 block">
                Model baru {fmt(res.created_models)} · varian baru {fmt(res.created_variants)} · pesanan tertaut {fmt(res.orders_updated)}
              </span>
            )}
          </Notice>
          <TabelData kolom={kolomHasil} baris={hasil} kunci={(r) => `${r._kelompok}-${r.platform_sku_id || r.target_sku || r.will_create}`}
            testId="bulk-result-table" kosong={<EmptyState title="Tidak ada SKU yang perlu dikerjakan" />} />
        </div>
      )}
    </div>
  );
}

/* ─── Bagian: pemetaan yang sudah ada ──────────────────────────────────────── */
function MappedPanel({ reloadKey, onChanged }) {
  const [rows, setRows] = useState([]);
  const [q, setQ] = useState('');
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await apiGet(`/sku-bridge/mappings?limit=300${q ? `&q=${encodeURIComponent(q)}` : ''}`);
      setRows(d.rows || []);
    } catch (e) { toast.error(e.message); } finally { setLoading(false); }
  }, [q]);

  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t); }, [load, reloadKey]);

  const unmap = async (psid) => {
    try {
      const res = await apiDelete(`/sku-bridge/mappings/${psid}`);
      toast.success(res.message || 'Pemetaan dilepas');
      load(); onChanged();
    } catch (e) { toast.error(e.message); }
  };

  const kolom = [
    { kunci: 'psku', label: 'SKU platform', hp: 'keterangan', isi: (r) => <span className="tabular-nums">{r.platform_sku_id}</span> },
    { kunci: 'barang', label: 'Barang gudang', hp: 'judul', isi: (r) => (
      <div className="min-w-0 md:max-w-[22rem]">
        <p className="truncate">{r.target_name || '—'}</p>
        <p className="hidden truncate text-xs text-muted-foreground md:block">{r.product_name_sample}</p>
      </div>) },
    { kunci: 'fg', label: 'Kode FG', hp: false, isi: (r) => <span className="tabular-nums">{r.fg_code || '—'}</span> },
    { kunci: 'pesanan', label: 'Pesanan', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmt(r.orders_using)}</span> },
    { kunci: 'cara', label: 'Cara', hp: false, isi: (r) => <StatusBadge tone="default" label={METHOD_LABEL[r.method || 'manual'] || r.method} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <Button size="icon-sm" variant="ghost" onClick={() => unmap(r.platform_sku_id)} aria-label={`Lepas pemetaan ${r.platform_sku_id}`}
        title="Lepas pemetaan" data-testid={`unmap-${r.platform_sku_id}`}>
        <Trash2 className="text-[hsl(var(--danger-text))]" />
      </Button>) },
  ];

  return (
    <div className="space-y-3">
      <BarisAlat
        kiri={<KotakCari value={q} onChange={setQ} placeholder="Cari SKU platform / nama master" testId="mapped-search" />}
        kanan={(
          <TombolUnduh namaBerkas="sku-sudah-dipetakan" namaLembar="Pemetaan" baris={rows} testId="mapped-unduh"
            kolom={[
              { label: 'SKU platform', nilai: (r) => r.platform_sku_id },
              { label: 'Barang gudang', nilai: (r) => r.target_name || '' },
              { label: 'Judul platform', nilai: (r) => r.product_name_sample || '' },
              { label: 'Kode FG', nilai: (r) => r.fg_code || '' },
              { label: 'Pesanan', nilai: (r) => Number(r.orders_using || 0) },
              { label: 'Cara', nilai: (r) => METHOD_LABEL[r.method || 'manual'] || r.method || '' },
            ]} />
        )} />
      {loading && rows.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat…</p>
      ) : (
        <TabelData kolom={kolom} baris={rows} kunci={(r) => r.platform_sku_id} testId="mapped-table"
          kosong={<EmptyState icon={Link2} testId="mapped-empty" title="Belum ada pemetaan"
            description='Tautkan SKU di bagian "Belum tertaut".' />} />
      )}
    </div>
  );
}

/* ─── Modul utama ──────────────────────────────────────────────────────────── */
export default function SkuBridgeModule({ onNavigate }) {
  const [health, setHealth] = useState(null);
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState('');
  const [tab, setTab] = useState('onboarding');
  const [loading, setLoading] = useState(true);
  const [busyRow, setBusyRow] = useState('');
  const [manualRow, setManualRow] = useState(null);
  const [createRow, setCreateRow] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);

  const loadHealth = useCallback(async () => {
    try { setHealth(await apiGet('/sku-bridge/health')); }
    catch (e) { toast.error(`Gagal memuat kesehatan tautan: ${e.message}`); }
  }, []);

  const loadUnmapped = useCallback(async () => {
    setLoading(true);
    try {
      const d = await apiGet(`/sku-bridge/unmapped?limit=120&with_suggestion=true${q ? `&q=${encodeURIComponent(q)}` : ''}`);
      setRows(d.rows || []); setTotal(d.total || 0);
    } catch (e) { toast.error(e.message); } finally { setLoading(false); }
  }, [q]);

  useEffect(() => { loadHealth(); }, [loadHealth, reloadKey]);
  useEffect(() => {
    if (tab !== 'unmapped') return undefined;
    const t = setTimeout(loadUnmapped, 250);
    return () => clearTimeout(t);
  }, [loadUnmapped, tab, reloadKey]);

  const refreshAll = () => setReloadKey((k) => k + 1);

  const quickAction = async (row) => {
    const act = row.recommended_action;
    if (act === 'create_master' || act === 'create_variant') { setCreateRow(row); return; }
    const mm = row.model_match || {};
    if (!mm.variant_id) { setManualRow(row); return; }
    setBusyRow(row.platform_sku_id);
    try {
      const res = await apiPost('/sku-bridge/map', {
        platform_sku_id: row.platform_sku_id,
        variant_id: mm.variant_id,
        account_id: row.account_id,
        product_name: row.product_name,
        variation: row.variation,
        confidence: mm.match_confidence,
      });
      toast.success(res.message || 'SKU ditautkan');
      refreshAll();
    } catch (e) { toast.error(e.message); } finally { setBusyRow(''); }
  };

  // Kesiapan: persen baris pesanan yang sudah menunjuk barang gudang (core/sku_bridge.health).
  // Tanpa baris pesanan, persen tidak bisa dihitung → "—" (dulu "0%").
  const adaPesanan = Number(health?.orders || 0) > 0;
  const pct = Number(health?.lines_linked_pct || 0);

  const kolomUnmapped = [
    { kunci: 'barang', label: 'Barang dipesan pembeli', hp: 'judul', isi: (r) => (
      <div className="min-w-0 md:max-w-[24rem]">
        <p className="truncate font-medium">{r.product_name || '(tanpa nama)'}</p>
        <p className="text-xs text-muted-foreground">{r.account_name || '—'} · <span className="tabular-nums">{r.platform_sku_id}</span></p>
      </div>) },
    { kunci: 'varian', label: 'Warna / ukuran', hp: 'keterangan', isi: (r) => (
      <div>
        <span className="text-sm">{r.parsed?.color || 'warna?'} / {r.parsed?.size || 'ukuran?'}</span>
        <p className="max-w-[12rem] truncate text-xs text-muted-foreground">{r.variation || '—'}</p>
      </div>) },
    { kunci: 'pcs', label: 'Pcs', rata: 'kanan', isi: (r) => <span className="font-medium tabular-nums">{fmt(r.pcs)}</span> },
    { kunci: 'nilai', label: 'Nilai', hp: false, rata: 'kanan', isi: (r) => <span className="tabular-nums">{rp(r.value)}</span> },
    { kunci: 'keadaan', label: 'Keadaan master', isi: (r) => {
      const meta = ACTION_META[r.recommended_action] || ACTION_META.create_master;
      return (
        <div className="md:max-w-[18rem]">
          <StatusBadge tone={meta.tone} label={meta.label} />
          <p className="mt-1 text-xs text-muted-foreground">{r.action_reason || meta.hint}</p>
        </div>
      );
    } },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => {
      const meta = ACTION_META[r.recommended_action] || ACTION_META.create_master;
      const Icon = meta.icon;
      return (
        <div className="flex items-center justify-end gap-1.5 whitespace-nowrap">
          <Button size="sm" onClick={() => quickAction(r)} disabled={busyRow === r.platform_sku_id} data-testid={`act-${r.platform_sku_id}`}>
            {busyRow === r.platform_sku_id ? <Loader2 className="animate-spin" /> : <Icon />}{meta.label}
          </Button>
          <Button size="sm" variant="outline" onClick={() => setManualRow(r)} data-testid={`manual-${r.platform_sku_id}`}>
            Pilih manual
          </Button>
        </div>
      );
    } },
  ];

  const BAGIAN = [
    { key: 'onboarding', label: 'Produk belum dikenal' },
    { key: 'unmapped', label: 'Belum tertaut', count: total || undefined },
    { key: 'mapped', label: 'Sudah dipetakan' },
    { key: 'bulk', label: 'Selesaikan massal' },
    { key: 'options', label: 'Opsi varian' },
  ];

  return (
    <PageLayout testId="sku-bridge-module" title="Jembatan SKU"
      subtitle="Samakan SKU marketplace dengan barang gudang supaya pesanan bisa dialokasikan."
      filters={<>
        <FilterChips className="w-full sm:w-auto" options={BAGIAN} value={tab} onChange={setTab} hideWhenEmpty={false} testId="tab" />
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <Button variant="outline" size="icon" onClick={refreshAll} title="Muat ulang" aria-label="Muat ulang" data-testid="refresh-bridge">
            <RefreshCw className={loading && tab === 'unmapped' ? 'animate-spin' : ''} />
          </Button>
        </div>
      </>}
      summary={health ? (adaPesanan ? (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile label="Pesanan marketing" value={fmt(health.orders)} testId="kpi-orders"
              sub={`${fmt(health.lines)} baris pesanan · ${fmt(health.bridge_mappings)} pemetaan aktif`} />
            <StatTile label="Siap dikerjakan gudang" value={fmt(health.orders_ready)} accent="success" testId="kpi-ready"
              sub={`Semua barisnya tertaut · ${fmt(health.orders_partial)} pesanan baru sebagian`} />
            <StatTile label="Belum bisa dikerjakan" value={fmt(health.orders_blocked)} accent="danger" testId="kpi-blocked"
              sub="Tidak satu pun barisnya tertaut ke barang gudang" />
            <StatTile label="SKU belum dikenal" value={fmt(health.unmapped_sku_count)} accent="warning" testId="kpi-unmapped"
              sub="SKU platform di pesanan yang belum punya pasangan master" />
          </div>
          <div data-testid="linkage-progress">
            <p className="text-sm">
              Kesiapan: <b className="tabular-nums">{fmt(health.lines_linked)}</b> dari <b className="tabular-nums">{fmt(health.lines)}</b> baris
              pesanan sudah menunjuk barang gudang (<b className="tabular-nums">{String(pct).replace('.', ',')}%</b>). Baris yang belum tertaut tidak bisa dialokasikan.
            </p>
            <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-foreground/10" role="progressbar"
              aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Persen baris pesanan tertaut">
              <div className={`h-full rounded-full ${pct >= 90 ? 'bg-[hsl(var(--success))]' : pct >= 50 ? 'bg-[hsl(var(--warning))]' : 'bg-[hsl(var(--destructive))]'}`}
                style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
            </div>
          </div>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground" data-testid="linkage-progress">
          Kesiapan: — · belum ada pesanan marketing, jadi persen baris yang tertaut belum bisa dihitung.
          {Number(health.bridge_mappings || 0) > 0 ? ` ${fmt(health.bridge_mappings)} pemetaan aktif.` : ''}
        </p>
      )) : null}
      footer={onNavigate ? (
        <p className="flex flex-wrap items-center gap-x-1 text-sm text-muted-foreground">
          Lanjut ke:
          <Button variant="link" size="sm" className="h-auto px-1" onClick={() => onNavigate('fulfillment')} data-testid="goto-fulfillment">
            Antrean gudang<ArrowRight />
          </Button>
          <Button variant="link" size="sm" className="h-auto px-1" onClick={() => onNavigate('sync-audit')} data-testid="goto-sync-audit">
            Kesehatan sinkronisasi<ArrowRight />
          </Button>
          <Button variant="link" size="sm" className="h-auto px-1" onClick={() => onNavigate('marketing-catalog')} data-testid="goto-catalog">
            Manajemen katalog<ArrowRight />
          </Button>
        </p>
      ) : null}>
      {tab === 'unmapped' && (
        <div className="space-y-3">
          <BarisAlat
            kiri={(
              <>
                <KotakCari value={q} onChange={setQ} placeholder="Cari nama produk / SKU platform" testId="unmapped-search" />
                {total > rows.length && <span className="text-sm text-muted-foreground">Menampilkan {fmt(rows.length)} dari {fmt(total)} SKU</span>}
              </>
            )}
            kanan={(
              // Daftar ini dipakai untuk membagi pekerjaan ke staf & dibawa ke rapat (kontrak INV-F10 A-3).
              <TombolUnduh namaBerkas="sku-belum-tertaut" namaLembar="SKU belum tertaut" baris={rows} testId="unmapped-export"
                kolom={[
                  { label: 'SKU platform', nilai: (r) => r.platform_sku_id },
                  { label: 'Toko', nilai: (r) => r.account_name || '' },
                  { label: 'Nama produk', nilai: (r) => r.product_name || '' },
                  { label: 'Variasi', nilai: (r) => r.variation || '' },
                  { label: 'Warna', nilai: (r) => r.parsed?.color || '' },
                  { label: 'Ukuran', nilai: (r) => r.parsed?.size || '' },
                  { label: 'Pcs', nilai: (r) => Number(r.pcs || 0) },
                  { label: 'Pesanan', nilai: (r) => Number(r.orders || 0) },
                  { label: 'Nilai (Rp)', nilai: (r) => Number(r.value || 0) },
                  { label: 'Aksi disarankan', nilai: (r) => ACTION_META[r.recommended_action]?.label || r.recommended_action || '' },
                  { label: 'Model terdekat', nilai: (r) => r.model_match?.model_name || '' },
                  { label: 'Alasan', nilai: (r) => r.action_reason || '' },
                ]} />
            )} />
          {loading && rows.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">Memeriksa pesanan &amp; master…</p>
          ) : (
            <TabelData kolom={kolomUnmapped} baris={rows} kunci={(r) => r.platform_sku_id} testId="unmapped-table"
              kosong={<EmptyState icon={CheckCircle2} testId="unmapped-empty" title="Semua SKU marketing sudah dikenal gudang"
                description="Tidak ada barang yang menggantung tanpa identitas." />} />
          )}
        </div>
      )}

      {tab === 'mapped' && <MappedPanel reloadKey={reloadKey} onChanged={refreshAll} />}
      {tab === 'bulk' && <BulkPanel onDone={refreshAll} />}
      {tab === 'onboarding' && <ProductOnboardingTab onDone={refreshAll} />}
      {tab === 'options' && <VariantOptionsTab />}

      {manualRow && (
        <ManualPickDialog row={manualRow} onClose={() => setManualRow(null)}
          onDone={() => { setManualRow(null); refreshAll(); }} />
      )}
      {createRow && (
        <CreateMasterDialog row={createRow} onClose={() => setCreateRow(null)}
          onDone={() => { setCreateRow(null); refreshAll(); }} />
      )}
    </PageLayout>
  );
}

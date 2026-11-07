/**
 * VariantOnboardingPanel — **Onboarding Produk Platform → Master** (Sesi #28)
 * ═══════════════════════════════════════════════════════════════════════════
 * MASALAH YANG DITUTUP LAYAR INI (diukur, bukan ditebak)
 * ───────────────────────────────────────────────────────────────────────────
 * Sesi #20 membangun Jembatan SKU dan gate-nya hijau — tetapi **tidak satu
 * barang pun pernah dijembatani**. Laporan audit sistem sendiri berkata MERAH:
 *
 *   A1 CRITICAL  NOL dari 601 baris pesanan menunjuk master gudang
 *   A5 HIGH      553 pesanan di antrean gudang, TIDAK SATU PUN siap dialokasikan
 *   A3 HIGH      83 SKU platform dipesan pembeli tetapi belum dikenal master
 *
 * Kenapa layar ini bekerja PER PRODUK, bukan per SKU: 83 baris satu per satu
 * adalah cara paling pasti membuat fitur sinkronisasi tidak dipakai. Per produk
 * = 8 keputusan.
 *
 * Aturan yang dijaga layar ini:
 *  · **Pratinjau dulu, selalu.** Tidak ada tombol yang menulis tanpa pemilik
 *    melihat lebih dulu daftar varian + SKU yang akan lahir.
 *  · **Nama model tidak diketik** (gate INV-F14). Ia diturunkan server dari
 *    judul platform dan hanya DITAMPILKAN; kalau produknya sudah ada di master,
 *    pemilik MENUNJUKNYA dari pemilih model.
 *  · Backend: `/api/variant-onboarding/*` (core/variant_identity.py). Layar ini
 *    tidak pernah menulis dokumen sendiri.
 *
 * Standar UI/UX v2 (8 Nov 2026): daftar produk = tabel (dulu grid kartu besar per produk), unduh Excel + CSV,
 * rencana onboarding & opsi varian = FormPopup, chip warna-warni → StatusBadge / kalimat ringkas, kotak abu
 * penjelasan → satu kalimat. Isian, API, dan aturan tidak berubah.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Sparkles, Eye, CheckCircle2, AlertTriangle, RefreshCw, Plus, Pencil, Ban,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { toast } from 'sonner';
import { apiGet, apiPost, apiDelete } from '@/lib/api';
import { CategorySelect, ModelSelect } from './masters/MasterSelects';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';

const fmt = (v) => Number(v || 0).toLocaleString('id-ID');
const rp = (v) => `Rp ${fmt(Math.round(Number(v || 0)))}`;

/** Baris alat sebuah bagian: penyaring/teks di kiri, alat di kanan (turun ke baris sendiri di HP). */
function BarisAlat({ kiri, kanan }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {kiri}
      <div className="ml-auto flex shrink-0 flex-wrap items-center gap-2">{kanan}</div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Popup: RENCANA onboarding satu produk
   ═══════════════════════════════════════════════════════════════════════════ */
function PlanDialog({ product, onClose, onDone }) {
  const [modelId, setModelId] = useState('');
  const [categoryCode, setCategoryCode] = useState('');
  const [plan, setPlan] = useState(null);
  const [busy, setBusy] = useState(false);
  const [applied, setApplied] = useState(null);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const qs = new URLSearchParams({ product_key: product.product_key });
      if (modelId) qs.set('model_id', modelId);
      if (categoryCode) qs.set('category_code', categoryCode);
      setPlan(await apiGet(`/variant-onboarding/plan?${qs.toString()}`));
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  }, [product.product_key, modelId, categoryCode]);

  useEffect(() => { load(); }, [load]);

  const apply = async () => {
    setBusy(true);
    try {
      const res = await apiPost('/variant-onboarding/apply', {
        product_key: product.product_key,
        model_id: modelId || undefined,
        category_code: categoryCode || undefined,
      });
      setApplied(res);
      if (res.failures?.length) toast.warning(res.message);
      else toast.success(res.message);
      await load();
      onDone?.();
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };

  const t = plan?.totals || {};
  const newColors = (plan?.colors || []).filter((c) => !c.exists);
  const newSizes = (plan?.sizes || []).filter((s) => !s.exists);

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" testId="onboarding-plan-dialog"
      judul={`Rencana produk baru — ${plan?.model?.name || product.proposed_model_name}`}
      keterangan="Rantai yang dibangun: model → warna/ukuran/opsi → varian → master FG → item katalog toko → pemetaan SKU → pesanan lama ikut tertaut. Belum ada yang ditulis sampai Anda menekan Terapkan."
      onSimpan={apply} menyimpan={busy} bisaSimpan={!!plan} labelSimpan="Terapkan"
      aksiKiri={(
        <Button type="button" variant="outline" onClick={load} disabled={busy} data-testid="onb-refresh-plan">
          <Eye />Susun ulang
        </Button>
      )}>
      <p className="text-sm text-muted-foreground">
        Judul dari platform: <span className="font-medium text-foreground">{product.product_name || '(tanpa nama)'}</span>
        {' '}· toko {product.account_name || '—'} · {fmt(product.sku_count)} SKU · {fmt(product.pcs)} pcs · {rp(product.value)}
      </p>

      {/* Pilihan pemilik — TANPA kolom ketik nama model (gate INV-F14) */}
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Tautkan ke model master yang sudah ada (opsional)"
          petunjuk="Kosong = buat model BARU; namanya diturunkan dari judul platform. Nama model sengaja tidak bisa diketik supaya model kembar tidak lahir.">
          <ModelSelect value={modelId} onChange={setModelId} label={null} testId="onb-model-select" />
        </Isian>
        <Isian label="Kategori produk" petunjuk="Kategori menentukan awalan kode model. Kosong = pakai usulan sistem.">
          <CategorySelect value={categoryCode} onChange={setCategoryCode} label={null} testId="onb-category-select" />
        </Isian>
      </div>

      {busy && !plan ? <p className="py-6 text-center text-sm text-muted-foreground">Menyusun rencana…</p> : null}

      {plan ? (
        <>
          <section className="space-y-2" data-testid="onb-plan-summary">
            <p className="text-sm font-medium">Pratinjau</p>
            <p className="text-sm text-foreground">{plan.message}</p>
            <div className="flex flex-wrap gap-1.5">
              <span data-testid="onb-chip-model">
                <StatusBadge tone={plan.model.exists ? 'success' : 'primary'}
                  label={`Model ${plan.model.exists ? 'sudah ada' : 'baru'}: ${plan.model.name} (${plan.model.code})`} />
              </span>
              <StatusBadge tone="default" label={`Kategori: ${plan.model.category_name}`} />
              <span data-testid="onb-chip-variants">
                <StatusBadge tone="primary" label={`${fmt(t.variants_new)} varian baru · ${fmt(t.variants_existing)} sudah ada`} />
              </span>
              <StatusBadge tone={newColors.length ? 'warning' : 'default'} label={`${fmt(t.colors_new)} warna baru`} />
              <StatusBadge tone={newSizes.length ? 'warning' : 'default'} label={`${fmt(t.sizes_new)} ukuran baru`} />
              <StatusBadge tone="default" label={`${fmt((plan.options || []).length)} opsi dipakai`} />
              <span data-testid="onb-chip-skus"><StatusBadge tone="success" label={`${fmt(t.skus_to_map)} SKU akan ditautkan`} /></span>
              <StatusBadge tone="success" label={`± ${fmt(t.order_lines_to_link)} baris pesanan`} />
              <span data-testid="onb-chip-collisions">
                <StatusBadge tone={t.collisions ? 'danger' : 'success'}
                  label={t.collisions ? `${fmt(t.collisions)} tabrakan identitas` : 'Tanpa tabrakan identitas'} />
              </span>
            </div>
          </section>

          {(newColors.length || newSizes.length) ? (
            <Notice tone="warning" testId="onb-new-masters"
              title="Master baru yang akan dibuat (disalin apa adanya dari variasi platform — tidak ditebak)">
              {[...newColors.map((c) => `${c.name} → ${c.code}`), ...newSizes.map((s) => s.code)].join(' · ')}
            </Notice>
          ) : null}

          {plan.warnings?.length ? (
            <Notice tone="danger" icon={AlertTriangle} testId="onb-warnings"
              title={`${plan.warnings.length} variasi punya bagian yang tidak dikenali`}>
              {plan.warnings.slice(0, 5).map((w) => (
                <span key={w.platform_sku_id} className="block">
                  <span className="tabular-nums">{w.platform_sku_id}</span> — {w.variation} → <b>{(w.unreadable || []).join(', ')}</b>
                </span>
              ))}
            </Notice>
          ) : null}

          <div className="max-h-[38vh] overflow-auto" data-testid="onb-variants-table">
            <Table className="min-w-[44rem]">
              <TableHeader>
                <TableRow>
                  <TableHead>SKU yang akan lahir</TableHead><TableHead>Warna</TableHead><TableHead>Ukuran</TableHead>
                  <TableHead>Opsi (dimensi ke-3)</TableHead><TableHead className="text-right">Pcs</TableHead>
                  <TableHead className="text-right">SKU platform</TableHead><TableHead>Variasi asli</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(plan.variants || []).map((v) => (
                  <TableRow key={v.identity_key}>
                    <TableCell className="font-medium tabular-nums">{v.sku}</TableCell>
                    <TableCell>{v.color_name}</TableCell>
                    <TableCell>{v.size_code}</TableCell>
                    <TableCell><StatusBadge tone={v.option_code === 'NA' ? 'default' : 'primary'} label={v.option_name} /></TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(v.pcs)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(v.sku_count)}</TableCell>
                    <TableCell className="max-w-[18rem] truncate text-muted-foreground" title={(v.variations || []).join(' | ')}>
                      {(v.variations || []).join(' | ')}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {applied ? (
            <Notice tone={applied.failures?.length ? 'warning' : 'success'} icon={CheckCircle2} testId="onb-apply-result"
              title={`Hasil penerapan: ${applied.message}`}>
              Varian dibuat <b>{fmt(applied.created?.variants)}</b> · warna baru <b>{fmt(applied.created?.colors)}</b> ·
              {' '}SKU ditautkan <b>{fmt(applied.skus_mapped)}</b> · baris pesanan tertaut <b>{fmt(applied.order_lines_linked)}</b>
              {applied.failures?.length ? (
                <span className="mt-1 block">
                  {applied.failures.length} gagal: {applied.failures.slice(0, 3).map((f) => `${f.platform_sku_id} (${f.message})`).join('; ')}
                </span>
              ) : null}
            </Notice>
          ) : null}
        </>
      ) : null}
    </FormPopup>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   BAGIAN: produk platform yang belum dikenal gudang (per produk)
   ═══════════════════════════════════════════════════════════════════════════ */
export function ProductOnboardingTab({ onDone }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [picked, setPicked] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try { setData(await apiGet('/variant-onboarding/products')); }
    catch (e) { toast.error(e.message); } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const products = data?.products || [];
  const kolom = [
    { kunci: 'model', label: 'Usulan model', hp: 'judul', isi: (p) => (
      <div className="min-w-0 md:max-w-[22rem]" data-testid={`onb-card-${p.product_key}`}>
        <p className="truncate font-medium" title={p.proposed_model_name}>{p.proposed_model_name}</p>
        <p className="hidden truncate text-xs text-muted-foreground md:block" title={p.product_name}>{p.product_name}</p>
      </div>) },
    { kunci: 'kategori', label: 'Kategori', hp: 'keterangan', isi: (p) => p.proposed_category_name || '—' },
    { kunci: 'sku', label: 'SKU', rata: 'kanan', isi: (p) => <span className="tabular-nums">{fmt(p.sku_count)}</span> },
    { kunci: 'pcs', label: 'Pcs dipesan', rata: 'kanan', isi: (p) => <span className="tabular-nums">{fmt(p.pcs)}</span> },
    { kunci: 'varian', label: 'Varian', rata: 'kanan', isi: (p) => <span className="tabular-nums">{fmt(p.identity_count)}</span> },
    { kunci: 'nilai', label: 'Nilai pesanan', rata: 'kanan', isi: (p) => <span className="tabular-nums">{rp(p.value)}</span> },
    { kunci: 'ket', label: 'Keterangan', isi: (p) => (
      <div className="flex flex-wrap gap-1">
        <StatusBadge tone="default" label={`${(p.colors || []).length} warna · ${(p.sizes || []).join(' · ') || '—'}`} />
        {(p.options || []).length > 1 ? <StatusBadge tone="primary" label={`${(p.options || []).length} opsi`} /> : null}
        {p.model_exists ? <StatusBadge tone="success" label="Model sudah ada" /> : null}
        {p.collisions ? <StatusBadge tone="danger" label={`${p.collisions} tabrakan`} /> : null}
        {(p.unreadable || []).length ? <StatusBadge tone="warning" label={`${p.unreadable.length} tak terbaca`} /> : null}
      </div>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (p) => (
      <Button size="sm" onClick={() => setPicked(p)} data-testid={`onb-plan-${p.product_key}`}>
        <Sparkles />Susun rencana
      </Button>) },
  ];

  return (
    <div className="space-y-3" data-testid="onboarding-tab">
      <p className="text-sm text-muted-foreground">
        Satu keputusan per produk membuat seluruh variannya (warna × ukuran × opsi) lahir sekaligus, lalu SKU dan baris
        pesanan lamanya ikut tertaut. Setiap tombol menampilkan rencana lebih dulu.
      </p>
      <BarisAlat
        kiri={(
          <p className="text-sm" data-testid="onb-stats">
            <span data-testid="onb-stat-products"><b className="tabular-nums">{fmt(data?.total_products)}</b> produk belum dikenal</span>
            {' · '}<span data-testid="onb-stat-skus"><b className="tabular-nums">{fmt(data?.total_skus)}</b> SKU</span>
            {' · '}<b className="tabular-nums">{fmt(data?.pcs_total)}</b> pcs
            {' · '}<span data-testid="onb-stat-collisions" className={data?.collisions_total ? 'font-medium text-[hsl(var(--danger-text))]' : ''}>
              {fmt(data?.collisions_total)} tabrakan identitas
            </span>
          </p>
        )}
        kanan={(
          <>
            <TombolUnduh namaBerkas="produk-belum-dikenal-gudang" namaLembar="Produk" baris={products} testId="onb-export"
              kolom={[
                { label: 'Produk', nilai: (p) => p.product_name },
                { label: 'Toko', nilai: (p) => p.account_name },
                { label: 'Usulan model', nilai: (p) => p.proposed_model_name },
                { label: 'Kategori', nilai: (p) => p.proposed_category_name },
                { label: 'SKU', nilai: (p) => Number(p.sku_count || 0) },
                { label: 'Pcs', nilai: (p) => Number(p.pcs || 0) },
                { label: 'Nilai (Rp)', nilai: (p) => Number(p.value || 0) },
                { label: 'Varian', nilai: (p) => Number(p.identity_count || 0) },
                { label: 'Warna', nilai: (p) => (p.colors || []).join(' / ') },
                { label: 'Ukuran', nilai: (p) => (p.sizes || []).join(' / ') },
                { label: 'Opsi', nilai: (p) => (p.options || []).join(' / ') },
                { label: 'Tabrakan', nilai: (p) => Number(p.collisions || 0) },
              ]} />
            <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
              data-testid="onb-reload">
              <RefreshCw className={loading ? 'animate-spin' : ''} />
            </Button>
          </>
        )} />

      {loading && !data ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat produk…</p>
      ) : (
        <TabelData kolom={kolom} baris={products} kunci={(p) => p.product_key} testId="onb-product-grid"
          kosong={<EmptyState icon={CheckCircle2} testId="onb-empty" title="Semua produk sudah dikenal gudang"
            description="Tidak ada SKU platform yang belum tertaut master. Antrean gudang bisa bekerja." />} />
      )}

      {picked ? (
        <PlanDialog product={picked} onClose={() => setPicked(null)} onDone={() => { load(); onDone?.(); }} />
      ) : null}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   BAGIAN: master OPSI VARIAN (dimensi ke-3)
   ═══════════════════════════════════════════════════════════════════════════ */
function OptionDialog({ option, onClose, onDone }) {
  const isNew = !option?.code;
  const [form, setForm] = useState({
    code: option?.code || '', name: option?.name || '',
    order_seq: option?.order_seq ?? 50, notes: option?.notes || '',
    active: option?.active !== false,
  });
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!form.code.trim() || !form.name.trim()) {
      toast.error('Kode dan nama opsi wajib diisi.');
      return;
    }
    setBusy(true);
    try {
      const res = await apiPost('/variant-onboarding/options', {
        code: form.code.trim().toUpperCase(), name: form.name.trim(),
        order_seq: Number(form.order_seq || 50), notes: form.notes,
        active: Boolean(form.active),
      });
      toast.success(res.message);
      onDone();
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="option-dialog"
      judul={isNew ? 'Tambah opsi varian' : `Ubah opsi ${option.code}`}
      keterangan="Opsi = dimensi ke-3 identitas barang (setelah warna & ukuran); kodenya masuk ke akhir SKU, mis. BLS-0001-PBL-XL-KRT. Kode NA = judul produk tidak menyebut opsi, tidak menambah akhiran SKU."
      onSimpan={submit} menyimpan={busy} labelSimpan="Simpan">
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Kode (maks 8 huruf)" wajib htmlFor="opt-kode">
          <Input id="opt-kode" value={form.code} disabled={!isNew} maxLength={8}
            onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })} placeholder="KRT" data-testid="opt-code" />
        </Isian>
        <Isian label="Urutan tampil" htmlFor="opt-urut">
          <Input id="opt-urut" type="number" value={form.order_seq}
            onChange={(e) => setForm({ ...form, order_seq: e.target.value })} data-testid="opt-order" />
        </Isian>
      </div>
      <Isian label="Nama opsi" wajib htmlFor="opt-nama">
        <Input id="opt-nama" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
          placeholder="Pakai Karet" data-testid="opt-name" />
      </Isian>
      <Isian label="Keterangan (opsional)" htmlFor="opt-ket">
        <Input id="opt-ket" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })}
          placeholder="Pinggang/lengan memakai karet." data-testid="opt-notes" />
      </Isian>
      <label className="flex items-center gap-3 text-sm" htmlFor="opt-aktif">
        <Switch id="opt-aktif" checked={form.active} onCheckedChange={(v) => setForm({ ...form, active: v })} data-testid="opt-active" />
        <span>Aktif (bisa dipakai varian baru)</span>
      </label>
    </FormPopup>
  );
}

export function VariantOptionsTab() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [edit, setEdit] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await apiGet('/variant-onboarding/options?include_inactive=true');
      setRows(d.rows || []);
    } catch (e) { toast.error(e.message); } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const deactivate = async (code) => {
    try {
      const res = await apiDelete(`/variant-onboarding/options/${code}`);
      toast.success(res.message); load();
    } catch (e) { toast.error(e.message); }
  };

  const totalVariants = useMemo(
    () => rows.reduce((a, r) => a + Number(r.variant_count || 0), 0), [rows]);

  const kolom = [
    { kunci: 'kode', label: 'Kode', hp: 'judul', isi: (r) => <span className="font-medium tabular-nums" data-testid={`option-row-${r.code}`}>{r.code}</span> },
    { kunci: 'nama', label: 'Nama', hp: 'keterangan', isi: (r) => r.name },
    { kunci: 'ket', label: 'Keterangan', isi: (r) => <span className="text-sm text-muted-foreground md:block md:max-w-[26rem]">{r.notes || '—'}</span> },
    { kunci: 'dipakai', label: 'Dipakai varian', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmt(r.variant_count)}</span> },
    { kunci: 'status', label: 'Status', isi: (r) => (
      <span className="inline-flex flex-wrap gap-1">
        <StatusBadge tone={r.active === false ? 'muted' : 'success'} label={r.active === false ? 'Nonaktif' : 'Aktif'} />
        {r.is_default ? <StatusBadge tone="primary" label="Bawaan" /> : null}
      </span>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <div className="flex items-center justify-end gap-1">
        <Button variant="ghost" size="icon-sm" onClick={() => setEdit(r)} aria-label={`Ubah opsi ${r.code}`} title="Ubah opsi"
          data-testid={`option-edit-${r.code}`}>
          <Pencil />
        </Button>
        {r.code !== 'NA' && r.active !== false ? (
          <Button variant="ghost" size="icon-sm" onClick={() => deactivate(r.code)} aria-label={`Nonaktifkan opsi ${r.code}`}
            title="Nonaktifkan opsi" data-testid={`option-off-${r.code}`}>
            <Ban className="text-[hsl(var(--danger-text))]" />
          </Button>
        ) : null}
      </div>) },
  ];

  return (
    <div className="space-y-3" data-testid="variant-options-tab">
      <p className="text-sm text-muted-foreground">
        Opsi adalah dimensi ke-3 identitas barang setelah warna × ukuran, supaya mis. <span className="tabular-nums">BLACK, XL, PAKAI KARET</span> dan
        {' '}<span className="tabular-nums">BLACK, XL, TANPA KARET</span> punya SKU sendiri (<span className="tabular-nums">…-XL-KRT</span> dan
        {' '}<span className="tabular-nums">…-XL-NOK</span>).
      </p>
      <BarisAlat
        kiri={<p className="text-sm text-muted-foreground">{rows.length} opsi · {fmt(totalVariants)} varian memakainya</p>}
        kanan={(
          <>
            <TombolUnduh namaBerkas="opsi-varian" namaLembar="Opsi varian" baris={rows} testId="opt-unduh"
              kolom={[
                { label: 'Kode', nilai: (r) => r.code },
                { label: 'Nama', nilai: (r) => r.name },
                { label: 'Keterangan', nilai: (r) => r.notes || '' },
                { label: 'Urutan', nilai: (r) => Number(r.order_seq || 0) },
                { label: 'Dipakai varian', nilai: (r) => Number(r.variant_count || 0) },
                { label: 'Status', nilai: (r) => (r.active === false ? 'Nonaktif' : 'Aktif') },
                { label: 'Bawaan', nilai: (r) => (r.is_default ? 'Ya' : '') },
              ]} />
            <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
              data-testid="opt-reload">
              <RefreshCw className={loading ? 'animate-spin' : ''} />
            </Button>
            <Button onClick={() => setEdit({})} data-testid="opt-add"><Plus />Tambah opsi</Button>
          </>
        )} />

      {loading && rows.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat opsi…</p>
      ) : (
        <TabelData kolom={kolom} baris={rows} kunci={(r) => r.code} testId="options-table"
          kosong={<EmptyState title="Opsi varian masih kosong" description='Tambahkan opsi dengan tombol "Tambah opsi".' />} />
      )}

      {edit ? (
        <OptionDialog option={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); load(); }} />
      ) : null}
    </div>
  );
}

/**
 * KatalogArtikelDetail — rincian satu artikel Katalog Buyer (DetailPanel; sejak Standar UI/UX v2 tampil sebagai popup).
 *
 * Standar UI/UX v2 (8 Nov 2026): tiap tabel bagian bisa diunduh (Excel/CSV); editor templat BOM = FormPopup panjang
 * (dulu form di dalam panel); "Hentikan artikel" bertombol merah; ukuran huruf & warna status token.
 *
 * Tahap 9 (7 Nov 2026, PANDUAN_UI G13): pengganti dialog "Detail" (MaklonBuyerCatalogDetailDialog) yang dulu
 * punya 4 tab di dalam popup. Isinya tetap: ringkasan + sampel terkait (riwayat sampel artikel ini, keputusan 9),
 * varian SKU, riwayat harga, dan templat BOM (versi + editor). Bagian disusun berurutan di panel — tanpa tab di
 * dalam tab hub.
 *
 *   GET  /api/dewi/maklon/buyer-catalog/{id} · /samples · /price-history
 *   POST /api/dewi/maklon/buyer-catalog/{id}/variants/generate · PUT …/variants/{vid}
 *   GET/POST/PUT/DELETE /api/dewi/maklon/bom-templates[/{tid}[/activate]]
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { BookOpen, Boxes, ClipboardCheck, FlaskConical, History, Pencil, Plus, Power, Save, Search, Sparkles, Trash2, X } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { MoneyInput } from '@/components/ui/money-input';
import { Textarea } from '@/components/ui/textarea';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { apiDelete, apiGet, apiPost, apiPut, getToken } from '../../../lib/api';
import { formatDateID, formatDateTimeID, formatRupiah } from '@/lib/format';
import { DetailPanel } from '../layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';
import { InlineMaterialPicker } from '../bom/InlineMaterialPicker';
import RnDUnitSelect, { RND_UNITS } from '../RnDUnitSelect';
import { ARTIKEL_STATUS } from './KatalogArtikelForm';

const fmtRp = (v) => formatRupiah(v || 0);
const fmtPct = (v) => `${v > 0 ? '+' : ''}${Number(v || 0).toLocaleString('id-ID', { maximumFractionDigits: 1 })}%`;
const STATUS_TONE = { active: 'success', inactive: 'warning', discontinued: 'danger' };
const SAMPLE_STATUS = { approved: ['Disetujui', 'success'], rejected: ['Ditolak', 'danger'], draft: ['Draf', 'muted'],
  in_progress: ['Dikerjakan', 'warning'], submitted: ['Diajukan', 'info'] };
const PRICE_EVENT = { initial: 'Harga awal', master_update: 'Ubah di katalog', po_create: 'PO dibuat', po_update: 'PO diubah' };

export const ArtikelStatusBadge = ({ status }) => (
  <StatusBadge status={status} label={ARTIKEL_STATUS[status] || status || '—'} tone={STATUS_TONE[status] || 'default'} />
);

function Section({ title, hint, actions, children, testId }) {
  return (
    <section className="space-y-2 border-t border-[var(--glass-border)] pt-3" data-testid={testId}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-foreground">{title}</p>
          {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
        </div>
        {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
      </div>
      {children}
    </section>
  );
}

function Info({ label, value, className = '' }) {
  return (
    <div className={`min-w-0 ${className}`}>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm text-foreground break-words">{value || value === 0 ? value : '—'}</p>
    </div>
  );
}

// ── Sampel terkait ────────────────────────────────────────────────────────────
function SamplesSection({ catalogId }) {
  const [data, setData] = useState({ samples: [], summary: {} });
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    apiGet(`/dewi/maklon/buyer-catalog/${catalogId}/samples`).then((d) => { if (alive) setData(d || { samples: [] }); })
      .catch(() => {}).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [catalogId]);
  const sum = data.summary || {};
  const rows = data.samples || [];
  return (
    <Section title="Riwayat sampel" testId="bc-samples"
      actions={rows.length > 0 && <TombolUnduh namaBerkas="riwayat-sampel-artikel" namaLembar="Sampel" baris={rows} testId="bc-samples-unduh"
        kolom={[{ label: 'Kode sampel', nilai: (x) => x.sample_code || '' }, { label: 'Ukuran', nilai: (x) => x.target_size || '' },
          { label: 'Warna', nilai: (x) => x.color_used || '' }, { label: 'Tanggal', nilai: (x) => (x.created_at ? formatDateID(x.created_at) : '') },
          { label: 'Status', nilai: (x) => (SAMPLE_STATUS[x.status] || [x.status])[0] }]} />}
      hint={rows.length ? `${sum.approved || 0} disetujui · ${sum.in_progress || 0} berjalan · ${sum.rejected || 0} ditolak` : 'Sampel dibuat dari rincian PO maklon dan tercatat di artikel ini.'}>
      {loading ? <p className="text-sm text-muted-foreground">Memuat sampel…</p> : !rows.length ? (
        <EmptyState icon={FlaskConical} title="Belum ada sampel untuk artikel ini" className="py-6" testId="bc-samples-empty"
          description="Sampel dibuat dari rincian PO maklon; hasilnya tercatat di sini." />
      ) : (
        <Table>
          <TableHeader><TableRow><TableHead>Kode sampel</TableHead><TableHead>Ukuran</TableHead><TableHead>Warna</TableHead>
            <TableHead>Tanggal</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
          <TableBody>
            {rows.map((s) => {
              const [label, tone] = SAMPLE_STATUS[s.status] || [s.status || '—', 'default'];
              return (
                <TableRow key={s.id} data-testid={`bc-linked-sample-${s.id}`}>
                  <TableCell className="font-medium">{s.sample_code || '—'}</TableCell>
                  <TableCell>{s.target_size || '—'}</TableCell>
                  <TableCell>{s.color_used || '—'}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{s.created_at ? formatDateID(s.created_at) : '—'}</TableCell>
                  <TableCell><StatusBadge status={s.status} label={label} tone={tone} /></TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
    </Section>
  );
}

// ── Varian SKU ────────────────────────────────────────────────────────────────
function VariantsSection({ catalog }) {
  const [variants, setVariants] = useState(catalog.variants || []);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [refDraft, setRefDraft] = useState('');
  const canGenerate = (catalog.color_options || []).length > 0 && (catalog.size_options || []).length > 0;

  const reload = useCallback(async () => {
    setLoading(true);
    try { const d = await apiGet(`/dewi/maklon/buyer-catalog/${catalog.id}`); setVariants(d?.variants || []); }
    catch { /* tetap tampilkan varian yang ada */ }
    finally { setLoading(false); }
  }, [catalog.id]);
  useEffect(() => { reload(); }, [reload]);

  const generate = async () => {
    setBusy(true);
    try {
      const d = await apiPost(`/dewi/maklon/buyer-catalog/${catalog.id}/variants/generate`, {});
      toast.success(`Varian: total ${d?.total || 0}, baru ${d?.created || 0}`);
      setVariants(d?.variants || []);
    } catch (e) { toast.error(e.message || 'Gagal membuat varian'); }
    finally { setBusy(false); }
  };
  const saveRef = async (v) => {
    setBusy(true);
    try {
      await apiPut(`/dewi/maklon/buyer-catalog/${catalog.id}/variants/${v.id}`, { buyer_ref_code: refDraft });
      toast.success('Kode buyer varian disimpan');
      setEditingId(null); await reload();
    } catch (e) { toast.error(e.message || 'Gagal menyimpan'); }
    finally { setBusy(false); }
  };
  const toggle = async (v) => {
    const off = v.active !== false;
    if (off && !(await confirmDialog({ title: `Nonaktifkan varian ${v.sku}?`, body: 'Varian nonaktif tidak bisa dipilih di PO baru.',
      confirmLabel: 'Nonaktifkan', danger: true }))) return;
    setBusy(true);
    try { await apiPut(`/dewi/maklon/buyer-catalog/${catalog.id}/variants/${v.id}`, { active: !off }); await reload(); }
    catch (e) { toast.error(e.message || 'Gagal mengubah status'); }
    finally { setBusy(false); }
  };

  return (
    <Section title={`Varian SKU (${variants.length})`} testId="bc-variants-tab"
      hint={`Kombinasi warna × ukuran. Format SKU: ${catalog.artikel_code}-WARNA-UKURAN.`}
      actions={<>
        {variants.length > 0 && <TombolUnduh namaBerkas={`varian-${catalog.artikel_code}`} namaLembar="Varian" baris={variants} testId="bc-variants-unduh"
          kolom={[{ label: 'SKU', nilai: (v) => v.sku }, { label: 'Warna', nilai: (v) => v.color || '' }, { label: 'Kode warna', nilai: (v) => v.color_code || '' },
            { label: 'Ukuran', nilai: (v) => v.size || '' }, { label: 'Kode buyer', nilai: (v) => v.buyer_ref_code || '' },
            { label: 'Status', nilai: (v) => (v.active === false ? 'Nonaktif' : 'Aktif') }]} />}
        <Button size="sm" variant="outline" onClick={generate} disabled={!canGenerate || busy} data-testid="bc-variant-generate-btn">
          <Sparkles className="w-3.5 h-3.5" />Buat varian
        </Button>
      </>}>
      {!canGenerate && <Notice tone="warning">Lengkapi pilihan warna & ukuran (Ubah artikel) sebelum membuat varian.</Notice>}
      {loading && !variants.length ? <p className="text-sm text-muted-foreground">Memuat varian…</p> : !variants.length ? (
        <EmptyState icon={Boxes} title="Belum ada varian SKU" className="py-6" description="Klik Buat varian untuk membuat matriks SKU warna × ukuran." />
      ) : (
        <Table>
          <TableHeader><TableRow><TableHead>SKU</TableHead><TableHead>Warna</TableHead><TableHead>Ukuran</TableHead>
            <TableHead>Kode buyer</TableHead><TableHead>Status</TableHead><TableHead className="text-right">Aksi</TableHead></TableRow></TableHeader>
          <TableBody>
            {variants.map((v) => (
              <TableRow key={v.id} data-testid={`bc-variant-row-${v.sku}`}>
                <TableCell className="text-xs font-medium text-[hsl(var(--primary))]">{v.sku}</TableCell>
                <TableCell>{v.color} <span className="text-xs text-muted-foreground">({v.color_code})</span></TableCell>
                <TableCell className="tabular-nums">{v.size}</TableCell>
                <TableCell>
                  {editingId === v.id ? (
                    <span className="flex items-center gap-1">
                      <Input value={refDraft} onChange={(e) => setRefDraft(e.target.value)} className="h-8 w-36 text-xs" placeholder="Kode buyer"
                        data-testid={`bc-variant-ref-input-${v.sku}`} />
                      <Button size="icon-sm" variant="ghost" onClick={() => saveRef(v)} disabled={busy} title="Simpan" aria-label="Simpan"
                        data-testid={`bc-variant-ref-save-${v.sku}`}><Save className="w-3.5 h-3.5" /></Button>
                      <Button size="icon-sm" variant="ghost" onClick={() => setEditingId(null)} title="Batal" aria-label="Batal"><X className="w-3.5 h-3.5" /></Button>
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1">
                      <span className={v.buyer_ref_code ? '' : 'text-muted-foreground'}>{v.buyer_ref_code || '—'}</span>
                      <Button size="icon-sm" variant="ghost" onClick={() => { setEditingId(v.id); setRefDraft(v.buyer_ref_code || ''); }}
                        title="Ubah kode buyer" aria-label="Ubah kode buyer" data-testid={`bc-variant-ref-edit-${v.sku}`}><Pencil className="w-3.5 h-3.5" /></Button>
                    </span>
                  )}
                </TableCell>
                <TableCell><StatusBadge status={v.active === false ? 'nonaktif' : 'aktif'} label={v.active === false ? 'Nonaktif' : 'Aktif'}
                  tone={v.active === false ? 'muted' : 'success'} /></TableCell>
                <TableCell className="text-right">
                  <Button size="sm" variant="outline" onClick={() => toggle(v)} disabled={busy} data-testid={`bc-variant-toggle-${v.sku}`}>
                    {v.active === false ? 'Aktifkan' : 'Nonaktifkan'}
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Section>
  );
}

// ── Riwayat harga ─────────────────────────────────────────────────────────────
function PriceHistorySection({ catalogId }) {
  const [data, setData] = useState({ price_history: [], thresholds: {} });
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    apiGet(`/dewi/maklon/buyer-catalog/${catalogId}/price-history`).then((d) => { if (alive) setData(d || {}); })
      .catch(() => {}).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [catalogId]);
  const rows = data.price_history || [];
  const t = data.thresholds || {};
  return (
    <Section title="Riwayat harga upah CMT" testId="bc-price-history"
      actions={rows.length > 0 && <TombolUnduh namaBerkas="riwayat-harga-cmt" namaLembar="Riwayat harga" baris={rows} testId="bc-price-unduh"
        kolom={[{ label: 'Waktu', nilai: (h) => (h.timestamp ? formatDateTimeID(h.timestamp) : '') },
          { label: 'Sumber', nilai: (h) => PRICE_EVENT[h.event_type] || h.event_type || '' }, { label: 'PO', nilai: (h) => h.po_number || '' },
          { label: 'Sebelum', nilai: (h) => Number(h.old_cmt_price || 0) }, { label: 'Sesudah', nilai: (h) => Number(h.new_cmt_price || 0) },
          { label: 'Oleh', nilai: (h) => h.changed_by_name || '' }, { label: 'Catatan', nilai: (h) => h.note || '' }]} />}
      hint={`Setiap perubahan dari katalog atau PO. Peringatan bila naik/turun ≥${t.warn_pct || 10}%, ditolak ≥${t.block_pct || 25}%.`}>
      {loading ? <p className="text-sm text-muted-foreground">Memuat riwayat…</p> : !rows.length ? (
        <EmptyState icon={History} title="Belum ada perubahan harga" className="py-6" description="Perubahan upah CMT dari katalog atau PO tercatat di sini." />
      ) : (
        <Table>
          <TableHeader><TableRow><TableHead>Waktu</TableHead><TableHead>Sumber</TableHead><TableHead className="text-right">Sebelum</TableHead>
            <TableHead className="text-right">Sesudah</TableHead><TableHead className="text-right">Perubahan</TableHead><TableHead>Oleh</TableHead></TableRow></TableHeader>
          <TableBody>
            {rows.map((h, i) => {
              const delta = (h.new_cmt_price || 0) - (h.old_cmt_price || 0);
              const pct = h.old_cmt_price > 0 ? (delta / h.old_cmt_price) * 100 : 0;
              return (
                <TableRow key={h.id || i} data-testid={`bc-price-history-${h.id || i}`}>
                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">{h.timestamp ? formatDateTimeID(h.timestamp) : '—'}</TableCell>
                  <TableCell className="text-sm">{PRICE_EVENT[h.event_type] || h.event_type || '—'}{h.po_number ? <span className="block text-xs text-muted-foreground">{h.po_number}</span> : null}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtRp(h.old_cmt_price)}</TableCell>
                  <TableCell className="text-right tabular-nums font-medium">{fmtRp(h.new_cmt_price)}</TableCell>
                  <TableCell className={`text-right tabular-nums ${delta > 0 ? 'text-[hsl(var(--warning-text))]' : delta < 0 ? 'text-[hsl(var(--success-text))]' : 'text-muted-foreground'}`}>{fmtPct(pct)}</TableCell>
                  <TableCell className="text-xs">{h.changed_by_name || '—'}{h.note ? <span className="block text-muted-foreground">{h.note}</span> : null}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
    </Section>
  );
}

// ── Templat BOM ───────────────────────────────────────────────────────────────
// 2026-11-05 (owner): tiap baris DIPILIH dari master material; ketikan bebas hanya untuk bahan milik klien.
const EMPTY_BOM_LINE = { material_id: null, material_code: '', material_name: '', category: '', unit: 'pcs',
  qty_per_pcs: 0, cost_per_unit: 0, supplier: '', notes: '', ownership: 'client_provided' };
const OWNERSHIP_LABEL = { client_provided: 'Disediakan klien', cv_da_stock: 'Stok DA' };
// 2026-11-07 (Tahap 5): kategori bahan milik klien = daftar tetap yang dikenali pengelompok server.
const BOM_CATEGORIES = ['Kain', 'Benang', 'Aksesoris', 'Kemasan', 'Lainnya'];

function BomEditor({ mode, data, catalog, onClose, onSaved }) {
  const token = getToken() || '';
  const [form, setForm] = useState({
    version_label: data?.version_label || '',
    materials: data?.materials?.length ? data.materials.map((m) => ({ ...m })) : [{ ...EMPTY_BOM_LINE }],
    notes: data?.notes || '', set_active: data ? !!data.is_active : true,
  });
  const [saving, setSaving] = useState(false);
  const totalCost = useMemo(() => form.materials.reduce((s, m) => s + (Number(m.qty_per_pcs) || 0) * (Number(m.cost_per_unit) || 0), 0), [form.materials]);
  const updateMat = (idx, field, val) => setForm((f) => ({ ...f, materials: f.materials.map((m, i) => (i === idx ? { ...m, [field]: val } : m)) }));
  const pickMaster = (idx, mat) => setForm((f) => ({ ...f, materials: f.materials.map((m, i) => (i !== idx ? m : {
    ...m, material_id: mat.id, material_code: mat.code || '', material_name: mat.name || m.material_name,
    unit: mat.unit || mat.base_unit || m.unit || 'pcs', category: mat.category_name || mat.category || mat.type || m.category,
    cost_per_unit: Number(m.cost_per_unit) ? m.cost_per_unit : (mat.unit_cost || mat.avg_cost || 0),
  })) }));

  const save = async () => {
    if (!form.materials.length) { toast.error('Minimal 1 material'); return; }
    if (form.materials.some((m) => !String(m.material_name || '').trim())) { toast.error('Pilih material dari master (atau ketik bahan milik klien) di setiap baris'); return; }
    const daTanpaMaster = form.materials.find((m) => m.ownership === 'cv_da_stock' && !m.material_id);
    if (daTanpaMaster) { toast.error(`"${daTanpaMaster.material_name}" disediakan dari stok DA — pilih dari master material supaya stoknya bisa dipotong`); return; }
    setSaving(true);
    try {
      if (mode === 'edit') await apiPut(`/dewi/maklon/bom-templates/${data.id}`, { version_label: form.version_label, materials: form.materials, notes: form.notes });
      else await apiPost('/dewi/maklon/bom-templates', { buyer_catalog_id: catalog.id, version_label: form.version_label, materials: form.materials, notes: form.notes, set_active: form.set_active });
      toast.success(mode === 'edit' ? 'Templat BOM diperbarui' : 'Versi templat BOM dibuat');
      onSaved();
    } catch (e) { toast.error(e.message || 'Gagal menyimpan'); }
    finally { setSaving(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" testId="bom-template-editor" onSimpan={save} menyimpan={saving}
      judul={mode === 'edit' ? `Ubah templat BOM v${data.version}` : 'Versi templat BOM baru'}
      keterangan={`${catalog.artikel_code} — ${catalog.product_name}. Material per pcs; pilih dari master, ketik hanya untuk bahan milik klien.`}
      labelSimpan={mode === 'edit' ? 'Simpan templat' : 'Buat versi'}>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Isian label={mode === 'edit' ? `Label versi v${data.version}` : 'Label versi'} htmlFor="bom-editor-version-label">
          <Input id="bom-editor-version-label" value={form.version_label} onChange={(e) => setForm({ ...form, version_label: e.target.value })} placeholder="mis. Bahan awal / Revisi Q3"
            data-testid="bom-editor-version-label" />
        </Isian>
        {mode === 'create' && (
          <label className="inline-flex cursor-pointer items-end gap-2 text-sm">
            <Checkbox checked={form.set_active} onCheckedChange={(v) => setForm({ ...form, set_active: !!v })} data-testid="bom-editor-set-active" />
            Jadikan versi aktif (versi lain dinonaktifkan)
          </label>
        )}
      </div>
      <div className="overflow-x-auto">
      <Table className="min-w-[900px]">
        <TableHeader><TableRow>
          <TableHead>Material (dari master) *</TableHead><TableHead>Disediakan</TableHead><TableHead>Kategori</TableHead>
          <TableHead>Satuan</TableHead><TableHead className="text-right">Qty/pcs</TableHead><TableHead className="text-right">Biaya/satuan</TableHead>
          <TableHead>Pemasok</TableHead><TableHead />
        </TableRow></TableHeader>
        <TableBody>
          {form.materials.map((m, idx) => (
            <TableRow key={idx}>
              <TableCell className="min-w-[220px]">
                <InlineMaterialPicker token={token} onSelect={(mat) => pickMaster(idx, mat)}>
                  <Button type="button" variant="outline" size="sm" className="w-full justify-start text-xs" data-testid={`bom-mat-${idx}-pick`}>
                    {m.material_id ? <><span className="tabular-nums text-muted-foreground mr-1">{m.material_code}</span><span className="truncate">{m.material_name}</span></>
                      : <><Search className="w-3 h-3" />Pilih dari master material</>}
                  </Button>
                </InlineMaterialPicker>
                {!m.material_id && m.ownership !== 'cv_da_stock' && (
                  <Input value={m.material_name} onChange={(e) => updateMat(idx, 'material_name', e.target.value)} placeholder="atau ketik bahan milik klien"
                    className="h-8 mt-1 text-xs" data-testid={`bom-mat-${idx}-name`} />
                )}
                {m.material_id && (
                  <Button type="button" variant="link" size="sm" className="h-auto p-0 text-xs" onClick={() => setForm((f) => ({ ...f, materials: f.materials.map((x, i) => (i !== idx ? x : { ...x, material_id: null, material_code: '' })) }))}>
                    Lepas tautan master (bahan milik klien)
                  </Button>
                )}
                {!m.material_id && m.material_name && <p className="text-xs text-[hsl(var(--warning-text))]">Belum tertaut master — stok tidak bisa dicek</p>}
              </TableCell>
              <TableCell>
                <SmartNativeSelect value={m.ownership || 'client_provided'} onChange={(e) => updateMat(idx, 'ownership', e.target.value)} searchable={false}
                  className="w-36 text-xs" data-testid={`bom-mat-${idx}-ownership`} aria-label="Disediakan oleh">
                  {Object.entries(OWNERSHIP_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </SmartNativeSelect>
              </TableCell>
              <TableCell>
                {m.material_id ? <span className="text-xs text-muted-foreground" data-testid={`bom-mat-${idx}-category`}>{m.category || '—'}</span> : (
                  <SmartNativeSelect value={m.category || ''} onChange={(e) => updateMat(idx, 'category', e.target.value)} searchable={false}
                    className="w-28 text-xs" data-testid={`bom-mat-${idx}-category`} aria-label="Kategori">
                    <option value="">— Kategori —</option>
                    {m.category && !BOM_CATEGORIES.includes(m.category) && <option value={m.category}>{m.category}</option>}
                    {BOM_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                  </SmartNativeSelect>
                )}
              </TableCell>
              <TableCell>
                {m.material_id ? <span className="text-xs tabular-nums" data-testid={`bom-mat-${idx}-unit`}>{m.unit || '—'}</span> : (
                  <div className="w-24"><RnDUnitSelect value={m.unit} onChange={(e) => updateMat(idx, 'unit', e.target.value)}
                    units={m.unit && !RND_UNITS.includes(m.unit) ? [m.unit, ...RND_UNITS] : undefined} testId={`bom-mat-${idx}-unit`} /></div>
                )}
              </TableCell>
              <TableCell className="text-right">
                <Input type="number" step="0.01" value={m.qty_per_pcs} onChange={(e) => updateMat(idx, 'qty_per_pcs', e.target.value)} className="h-8 w-20 text-xs text-right" />
              </TableCell>
              <TableCell className="text-right">
                <MoneyInput decimals={2} value={m.cost_per_unit} onChange={(e) => updateMat(idx, 'cost_per_unit', e.target.value)} className="h-8 w-24 text-xs text-right" />
              </TableCell>
              <TableCell><Input value={m.supplier} onChange={(e) => updateMat(idx, 'supplier', e.target.value)} placeholder="Pemasok" className="h-8 w-28 text-xs" /></TableCell>
              <TableCell>
                <Button type="button" size="icon-sm" variant="ghost" onClick={() => setForm((f) => ({ ...f, materials: f.materials.filter((_, i) => i !== idx) }))}
                  title="Hapus baris" aria-label="Hapus baris"><X className="w-3.5 h-3.5" /></Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button type="button" size="sm" variant="outline" onClick={() => setForm((f) => ({ ...f, materials: [...f.materials, { ...EMPTY_BOM_LINE }] }))}>
          <Plus className="w-3.5 h-3.5" />Tambah material
        </Button>
        <p className="text-sm">Biaya per pcs: <span className="font-semibold tabular-nums">{fmtRp(totalCost)}</span></p>
      </div>
      <Isian label="Catatan versi" htmlFor="bom-editor-notes">
        <Textarea id="bom-editor-notes" rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="Apa yang berubah di versi ini?" />
      </Isian>
    </FormPopup>
  );
}

function BomTemplatesSection({ catalog }) {
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editor, setEditor] = useState(null);
  const load = useCallback(async () => {
    setLoading(true);
    try { const d = await apiGet(`/dewi/maklon/bom-templates?buyer_catalog_id=${catalog.id}`); setTemplates(Array.isArray(d) ? d : []); }
    catch { setTemplates([]); }
    finally { setLoading(false); }
  }, [catalog.id]);
  useEffect(() => { load(); }, [load]);

  const activate = async (t) => {
    try { await apiPost(`/dewi/maklon/bom-templates/${t.id}/activate`, {}); toast.success(`v${t.version} sekarang aktif`); load(); }
    catch (e) { toast.error(e.message || 'Gagal mengaktifkan'); }
  };
  const remove = async (t) => {
    if (!(await confirmDialog({ title: `Hapus templat BOM v${t.version}?`, body: 'Templat dihapus permanen dan tidak bisa dibatalkan.',
      confirmLabel: 'Hapus templat', danger: true }))) return;
    try { await apiDelete(`/dewi/maklon/bom-templates/${t.id}`); toast.success('Templat dihapus'); load(); }
    catch (e) { toast.error(e.message || 'Gagal menghapus'); }
  };

  return (
    <Section title="Templat BOM" testId="bc-bom-templates"
      hint="Resep material per pcs, bisa beberapa versi; hanya satu versi aktif yang dipakai saat membuat PO."
      actions={<>
        {templates.length > 0 && <TombolUnduh namaBerkas={`templat-bom-${catalog.artikel_code}`} namaLembar="Templat BOM" baris={templates} testId="bom-template-unduh"
          kolom={[{ label: 'Versi', nilai: (t) => `v${t.version}` }, { label: 'Label', nilai: (t) => t.version_label || '' },
            { label: 'Material', nilai: (t) => Number(t.material_count ?? (t.materials || []).length) },
            { label: 'Biaya/pcs', nilai: (t) => Number(t.total_cost_per_pcs || 0) },
            { label: 'Diperbarui', nilai: (t) => (t.updated_at ? formatDateID(t.updated_at) : '') },
            { label: 'Status', nilai: (t) => (t.is_active ? 'Aktif' : 'Tidak aktif') }, { label: 'Catatan', nilai: (t) => t.notes || '' }]} />}
        <Button size="sm" variant="outline" onClick={() => setEditor({ mode: 'create' })} data-testid="bom-template-add-btn">
          <Plus className="w-3.5 h-3.5" />Versi baru
        </Button>
      </>}>
      {editor && (
        <BomEditor mode={editor.mode} data={editor.data} catalog={catalog} onClose={() => setEditor(null)} onSaved={() => { setEditor(null); load(); }} />
      )}
      {loading ? <p className="text-sm text-muted-foreground">Memuat templat…</p> : !templates.length ? (
        <EmptyState icon={ClipboardCheck} title="Belum ada templat BOM" description="Klik Versi baru untuk membuat resep material pertama." className="py-6" />
      ) : (
        <Table>
          <TableHeader><TableRow><TableHead>Versi</TableHead><TableHead>Label</TableHead><TableHead className="text-right">Material</TableHead>
            <TableHead className="text-right">Biaya/pcs</TableHead><TableHead>Diperbarui</TableHead><TableHead>Status</TableHead><TableHead className="text-right">Aksi</TableHead></TableRow></TableHeader>
          <TableBody>
            {templates.map((t) => (
              <TableRow key={t.id} data-testid={`bom-template-${t.id}`}>
                <TableCell className="font-semibold text-[hsl(var(--primary))]">v{t.version}</TableCell>
                <TableCell className="text-sm">{t.version_label || '—'}{t.notes ? <span className="block text-xs text-muted-foreground">{t.notes}</span> : null}</TableCell>
                <TableCell className="text-right tabular-nums">{t.material_count ?? (t.materials || []).length}</TableCell>
                <TableCell className="text-right tabular-nums">{fmtRp(t.total_cost_per_pcs)}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{t.updated_at ? formatDateID(t.updated_at) : '—'}</TableCell>
                <TableCell>{t.is_active ? <StatusBadge status="aktif" label="Aktif" tone="success" /> : <StatusBadge status="arsip" label="Tidak aktif" tone="muted" />}</TableCell>
                <TableCell className="text-right whitespace-nowrap">
                  {!t.is_active && <Button size="sm" variant="outline" onClick={() => activate(t)} data-testid={`bom-template-activate-${t.id}`}>Aktifkan</Button>}
                  <Button size="icon-sm" variant="ghost" onClick={() => setEditor({ mode: 'edit', data: t })} title="Ubah templat" aria-label="Ubah templat"
                    data-testid={`bom-template-edit-${t.id}`}><Pencil className="w-3.5 h-3.5" /></Button>
                  <Button size="icon-sm" variant="ghost" onClick={() => remove(t)} title="Hapus templat" aria-label="Hapus templat"
                    data-testid={`bom-template-delete-${t.id}`}><Trash2 className="w-3.5 h-3.5" /></Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Section>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
export default function KatalogArtikelDetail({ catalog, onClose, onEdit, onSop, onChanged }) {
  const [busy, setBusy] = useState(false);
  const toggle = async () => {
    const off = catalog.status === 'active';
    if (!(await confirmDialog({ title: off ? `Nonaktifkan artikel ${catalog.artikel_code}?` : `Aktifkan lagi artikel ${catalog.artikel_code}?`,
      body: off ? 'Artikel nonaktif tidak muncul di pilihan PO baru. Bisa diaktifkan lagi kapan saja.' : 'Artikel bisa dipilih lagi di PO baru.',
      confirmLabel: off ? 'Nonaktifkan' : 'Aktifkan', danger: off }))) return;
    setBusy(true);
    try { await apiPut(`/dewi/maklon/buyer-catalog/${catalog.id}/toggle`, {}); toast.success('Status artikel diubah'); await onChanged(catalog.id); }
    catch (e) { toast.error(e.message || 'Gagal mengubah status'); }
    finally { setBusy(false); }
  };
  const discontinue = async () => {
    if (!(await confirmDialog({ title: `Hentikan artikel ${catalog.artikel_code}?`, body: 'Artikel yang dihentikan tidak bisa dipakai untuk order baru. Riwayatnya tetap ada.',
      confirmLabel: 'Hentikan artikel', danger: true }))) return;
    setBusy(true);
    try { await apiDelete(`/dewi/maklon/buyer-catalog/${catalog.id}`); toast.success('Artikel dihentikan'); await onChanged(catalog.id); }
    catch (e) { toast.error(e.message || 'Gagal menghentikan artikel'); }
    finally { setBusy(false); }
  };

  return (
    <DetailPanel testId="bc-detail-dialog" closeTestId="bc-detail-close" onClose={onClose}
      title={<span className="inline-flex items-center gap-2 flex-wrap">{catalog.product_name} <ArtikelStatusBadge status={catalog.status} /></span>}
      description={`${catalog.artikel_code}${catalog.buyer_ref_code ? ` · kode buyer ${catalog.buyer_ref_code}` : ''} · ${catalog.client_name || '—'}`}
      actions={<>
        <Button variant="outline" onClick={onEdit} disabled={busy} data-testid={`buyer-catalog-edit-${catalog.id}`}><Pencil className="w-4 h-4" />Ubah</Button>
        <Button variant="outline" onClick={onSop} disabled={busy} data-testid={`buyer-catalog-sop-${catalog.id}`}><BookOpen className="w-4 h-4" />Panduan produksi</Button>
        {catalog.status !== 'discontinued' && (
          <Button variant="outline" onClick={toggle} disabled={busy} data-testid={`buyer-catalog-toggle-${catalog.id}`}>
            <Power className="w-4 h-4" />{catalog.status === 'active' ? 'Nonaktifkan' : 'Aktifkan'}
          </Button>
        )}
        {catalog.status !== 'discontinued' && (
          <Button variant="destructive" size="icon" onClick={discontinue} disabled={busy} title="Hentikan artikel" aria-label="Hentikan artikel"
            data-testid={`buyer-catalog-discontinue-${catalog.id}`}><Trash2 className="w-4 h-4" /></Button>
        )}
      </>}>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3" data-testid="bc-detail-summary">
        <Info label="Kategori" value={catalog.category} />
        <Info label="Musim / gender" value={`${catalog.season || '—'} / ${catalog.gender || '—'}`} />
        <Info label="Upah jahit CMT (bawaan)" value={fmtRp(catalog.default_cmt_price)} />
        <Info label="Harga jasa ke klien (bawaan)" value={fmtRp(catalog.default_selling_price)} />
        <Info label="Warna" value={(catalog.color_options || []).join(', ')} className="col-span-2" />
        <Info label="Ukuran" value={(catalog.size_options || []).join(', ')} className="col-span-2" />
        <Info label="Total produksi" value={`${Number(catalog.total_qty_produced || 0).toLocaleString('id-ID')} pcs`} />
        <Info label="Total pendapatan" value={fmtRp(catalog.total_revenue)} />
        <Info label="Terakhir dipakai" value={catalog.last_used_at ? formatDateID(catalog.last_used_at) : 'Belum pernah'} />
        <Info label="Deskripsi" value={catalog.description} className="col-span-2 lg:col-span-4" />
      </div>
      <SamplesSection catalogId={catalog.id} />
      <VariantsSection catalog={catalog} />
      <PriceHistorySection catalogId={catalog.id} />
      <BomTemplatesSection catalog={catalog} />
    </DetailPanel>
  );
}

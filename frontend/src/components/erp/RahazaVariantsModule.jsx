import { useState, useEffect, useCallback, useMemo } from 'react';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Plus, Trash2, Wand2, Package, Pencil } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import PaginationLite from '@/components/ui/pagination-lite';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import FormPopup from '@/components/ui/form-popup';
import { Checkbox } from '@/components/ui/checkbox';
import {
  PRODUCT_STATUS_OPTIONS, PRODUCT_STATUS_UNSET, PRODUCT_STATUS_MIXED, productStatusLabel, productStatusTone,
} from '@/lib/productStatus';
import { toast } from 'sonner';
import PageLayout from './layout/PageLayout';
import { PageLayoutSatuBaris } from './engine/DataTable';
import { apiDelete } from '../../lib/api';
import { hapusMaster } from '../../lib/hapusMaster';
import { EmptyState, StatusBadge } from './moduleAtoms';

const PAGE_SIZE = 25;
const ALL_MODELS = '';

function ProductStatusCell({ code, testId }) {
  if (!code) return <span className="text-xs text-muted-foreground" data-testid={testId}>Belum diisi</span>;
  return <StatusBadge status={code} label={productStatusLabel(code)} tone={productStatusTone(code)} testId={testId} />;
}

/* Varian Produk (Fase 2) — kombinasi Warna × Size dengan SKU unik otomatis.
   SKU = KODE-WARNA-SIZE. Generate matriks dari warna & size terpilih.
   2026-11-06: status produk per SKU (Baru · Best Seller · Slow · Dead · Stop) — kolom, penyaring, dan
   formulir ubah. Stop = tidak direncanakan cutting; varian TIDAK dinonaktifkan. */
export function RahazaVariantsModule({ token }) {
  const [models, setModels] = useState([]);
  const [colors, setColors] = useState([]);
  const [sizes, setSizes] = useState([]);
  const [selectedModelId, setSelectedModelId] = useState(null); // null = master belum dimuat
  const [variants, setVariants] = useState([]);
  const [modelSummary, setModelSummary] = useState(null);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState('');
  const [page, setPage] = useState(1);

  // Generate dialog state
  const [genOpen, setGenOpen] = useState(false);
  const [genColorIds, setGenColorIds] = useState([]);
  const [genSizeIds, setGenSizeIds] = useState([]);
  const [generating, setGenerating] = useState(false);

  // Edit dialog state (formulir pendek: status produk · barcode · catatan)
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ product_status: '', barcode: '', notes: '' });
  const [saving, setSaving] = useState(false);

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);

  const loadBase = useCallback(async () => {
    const h = { Authorization: `Bearer ${token}` };
    const [mRes, cRes, sRes] = await Promise.all([
      fetch('/api/rahaza/models', { headers: h }).then(r => r.ok ? r.json() : []),
      fetch('/api/rahaza/colors', { headers: h }).then(r => r.ok ? r.json() : []),
      fetch('/api/rahaza/sizes', { headers: h }).then(r => r.ok ? r.json() : []),
    ]);
    const activeModels = (mRes || []).filter(m => m.active !== false);
    setModels(activeModels);
    setColors((cRes || []).filter(c => c.active !== false));
    setSizes((sRes || []).filter(s => s.active !== false));
    setSelectedModelId((cur) => (cur !== null ? cur : (activeModels[0]?.id || ALL_MODELS)));
  }, [token]);

  const loadVariants = useCallback(async () => {
    if (selectedModelId === null) return;
    setLoading(true);
    try {
      if (selectedModelId === ALL_MODELS) {
        const r = await fetch('/api/rahaza/variants', { headers });
        setVariants(r.ok ? (await r.json()) || [] : []);
        setModelSummary(null);
      } else {
        const r = await fetch(`/api/rahaza/models/${selectedModelId}/variants`, { headers });
        const data = r.ok ? await r.json() : {};
        setVariants(data.variants || []);
        setModelSummary(data.model?.product_status_summary || null);
      }
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedModelId, token]);

  useEffect(() => { loadBase(); }, [loadBase]);
  useEffect(() => { loadVariants(); }, [loadVariants]);
  useEffect(() => { setPage(1); }, [selectedModelId, statusFilter]);

  const counts = useMemo(() => {
    const c = { [PRODUCT_STATUS_UNSET]: 0 };
    variants.forEach((v) => {
      const k = v.product_status || PRODUCT_STATUS_UNSET;
      c[k] = (c[k] || 0) + 1;
    });
    return c;
  }, [variants]);

  const statusChips = useMemo(() => [
    { key: '', label: 'Semua', count: variants.length },
    ...PRODUCT_STATUS_OPTIONS.map(o => ({ key: o.value, label: o.label, count: counts[o.value] || 0 })),
    { key: PRODUCT_STATUS_UNSET, label: 'Belum diisi', count: counts[PRODUCT_STATUS_UNSET] || 0 },
  ].filter(o => o.key === '' || o.count > 0 || o.key === statusFilter), [variants.length, counts, statusFilter]);

  const shown = useMemo(() => (statusFilter
    ? variants.filter(v => (v.product_status || PRODUCT_STATUS_UNSET) === statusFilter)
    : variants), [variants, statusFilter]);
  const totalPages = Math.max(1, Math.ceil(shown.length / PAGE_SIZE));
  const pageRows = shown.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const openGenerate = () => {
    setGenColorIds([]);
    setGenSizeIds(sizes.map(s => s.id)); // default: semua size
    setGenOpen(true);
  };

  const toggleColor = (id) => setGenColorIds(ids => ids.includes(id) ? ids.filter(x => x !== id) : [...ids, id]);
  const toggleSize = (id) => setGenSizeIds(ids => ids.includes(id) ? ids.filter(x => x !== id) : [...ids, id]);

  const runGenerate = async () => {
    if (!genColorIds.length) { toast.error('Pilih minimal 1 warna'); return; }
    if (!genSizeIds.length) { toast.error('Pilih minimal 1 ukuran'); return; }
    setGenerating(true);
    try {
      const r = await fetch(`/api/rahaza/models/${selectedModelId}/variants/generate`, {
        method: 'POST', headers,
        body: JSON.stringify({ color_ids: genColorIds, size_ids: genSizeIds }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        toast.error(err.detail || `Gagal membuat varian (HTTP ${r.status})`);
        return;
      }
      const data = await r.json();
      toast.success(`Varian dibuat: ${data.created_count} · Dilewati (sudah ada): ${data.skipped_count}`);
      setGenOpen(false);
      loadVariants();
    } finally { setGenerating(false); }
  };

  const openEdit = (v) => {
    setForm({ product_status: v.product_status || '', barcode: v.barcode || '', notes: v.notes || '' });
    setEditing(v);
  };

  const saveEdit = async () => {
    if (!editing) return;
    setSaving(true);
    try {
      const r = await fetch(`/api/rahaza/variants/${editing.id}`, {
        method: 'PUT', headers,
        body: JSON.stringify({ product_status: form.product_status || null, barcode: form.barcode, notes: form.notes }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        toast.error(err.detail || `Gagal menyimpan varian (HTTP ${r.status})`);
        return;
      }
      toast.success(`Varian ${editing.sku} disimpan · status ${productStatusLabel(form.product_status).toLowerCase()}`);
      setEditing(null);
      loadVariants();
    } finally { setSaving(false); }
  };

  // 10 Nov 2026 (owner "master data bisa dihapus"): dulu tombol "Hapus varian" hanya menonaktifkan. Sekarang hapus
  // permanen bila SKU belum dipakai; bila sudah (409) dialog kedua menampilkan alasannya dan menawarkan Nonaktifkan
  // (item katalog yang menawarkan SKU ini ikut dinonaktifkan).
  const handleDelete = async (v) => {
    const hasil = await hapusMaster({
      jenis: 'varian', nama: v.sku,
      keterangan: 'Varian dan barang jadinya (bila belum punya stok) dihapus permanen. Bila SKU sudah dipakai PO, '
        + 'cutting, katalog, pesanan, atau stok, penghapusan ditolak dan Anda bisa menonaktifkannya saja.',
      hapus: () => apiDelete(`/rahaza/variants/${v.id}?hard=true`),
      nonaktifkan: v.active !== false ? () => apiDelete(`/rahaza/variants/${v.id}`) : null,
    });
    if (hasil) loadVariants();
  };

  const selectedModel = models.find(m => m.id === selectedModelId);
  const allModels = selectedModelId === ALL_MODELS;

  return (
    <PageLayoutSatuBaris
      testId="rahaza-variants-module"
      title="Varian produk (SKU)"
      subtitle="Warna × ukuran dengan SKU otomatis KODE-WARNA-UKURAN; status Stop tidak direncanakan cutting."
      actions={(
        <Button type="button" onClick={openGenerate} disabled={!selectedModelId} data-testid="variant-generate-btn">
          <Wand2 className="w-4 h-4" /> Buat varian
        </Button>
      )}
      filters={(
        <>
          <SmartNativeSelect value={selectedModelId || ALL_MODELS} onChange={(e) => setSelectedModelId(e.target.value)}
            className="w-56" aria-label="Model" data-testid="variant-model-selector">
            <option value={ALL_MODELS}>Semua model</option>
            {models.map(m => (
              <option key={m.id} value={m.id}>{m.code} · {m.name}</option>
            ))}
          </SmartNativeSelect>
          <FilterChips value={statusFilter} onChange={setStatusFilter} options={statusChips}
            ariaLabel="Status produk" testId="variant-status-filter" />
        </>
      )}
      tools={<TombolUnduh namaBerkas="varian-produk" namaLembar="Varian" baris={shown} testId="variant-unduh" kolom={[
        { label: 'SKU', nilai: (v) => v.sku || '' }, { label: 'Model', nilai: (v) => v.model_code || selectedModel?.code || '' },
        { label: 'Warna', nilai: (v) => v.color_name || '' }, { label: 'Kode warna', nilai: (v) => v.color_code || '' },
        { label: 'Ukuran', nilai: (v) => v.size_code || '' }, { label: 'Status produk', nilai: (v) => productStatusLabel(v.product_status) || '' },
        { label: 'Barcode', nilai: (v) => v.barcode || '' },
      ]} />}
      footer={shown.length > PAGE_SIZE ? (
        <PaginationLite page={page} totalPages={totalPages} total={shown.length} pageSize={PAGE_SIZE} onPageChange={setPage} />
      ) : null}
    >
      <GlassCard className="p-0 overflow-x-auto">
        <div className="px-4 py-3 border-b border-[var(--glass-border)] flex items-center justify-between gap-3 flex-wrap">
          <div className="text-sm flex items-center gap-2 flex-wrap" data-testid="variant-model-summary">
            {allModels ? (
              <span className="font-semibold text-foreground">Semua model</span>
            ) : (
              <>
                <span className="font-semibold text-foreground">{selectedModel?.code}</span>
                <span className="text-muted-foreground">· {selectedModel?.name}</span>
                {modelSummary && (
                  <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                    · Status model
                    <ProductStatusCell code={modelSummary.code} testId="variant-model-status" />
                    {modelSummary.code === PRODUCT_STATUS_MIXED && modelSummary.dominant && (
                      <span className="text-xs">terbanyak {productStatusLabel(modelSummary.dominant)}</span>
                    )}
                  </span>
                )}
              </>
            )}
          </div>
          <Badge variant="outline">{shown.length} varian</Badge>
        </div>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>SKU</TableHead>
                <TableHead className="w-16">Warna</TableHead>
                <TableHead>Nama warna</TableHead>
                <TableHead>Ukuran</TableHead>
                <TableHead>Status produk</TableHead>
                <TableHead className="text-right">Aksi</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow><TableCell colSpan={6} className="text-center text-muted-foreground">Memuat…</TableCell></TableRow>
              ) : shown.length === 0 ? (
                <TableRow><TableCell colSpan={6}>
                  <EmptyState icon={Package} testId="variant-empty"
                    title={variants.length ? 'Tidak ada varian dengan status ini' : 'Belum ada varian'}
                    description={variants.length ? 'Pilih status lain atau "Semua".' : 'Klik Buat varian untuk membuat matriks warna × ukuran.'} />
                </TableCell></TableRow>
              ) : pageRows.map(v => (
                <TableRow key={v.id} data-testid={`variant-row-${v.sku}`}>
                  <TableCell className="tabular-nums font-semibold text-foreground">{v.sku}</TableCell>
                  <TableCell>
                    <span className="inline-block w-6 h-6 rounded-md border border-[var(--glass-border)]"
                      style={{ backgroundColor: v.color_hex || '#ccc' }} title={v.color_hex} />
                  </TableCell>
                  <TableCell className="text-foreground">{v.color_name} <span className="text-muted-foreground text-xs">({v.color_code})</span></TableCell>
                  <TableCell><Badge variant="secondary">{v.size_code}</Badge></TableCell>
                  <TableCell><ProductStatusCell code={v.product_status} testId={`variant-status-${v.sku}`} /></TableCell>
                  <TableCell className="text-right whitespace-nowrap">
                    <Button type="button" variant="ghost" size="icon-sm" onClick={() => openEdit(v)}
                      title="Ubah varian" aria-label={`Ubah varian ${v.sku}`} data-testid={`variant-edit-${v.sku}`}>
                      <Pencil className="w-3.5 h-3.5" />
                    </Button>
                    <Button type="button" variant="ghost" size="icon-sm" onClick={() => handleDelete(v)}
                      title="Hapus" aria-label={`Hapus varian ${v.sku}`} data-testid={`variant-delete-${v.sku}`}>
                      <Trash2 className="w-3.5 h-3.5" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </GlassCard>

      {/* Ubah varian — formulir pendek (PANDUAN_UI G13: popup hanya untuk isian pendek) */}
      {/* Standar UI/UX v2: FormPopup pendek (kaki Batal · Simpan hijau) */}
      <FormPopup open={!!editing} onClose={() => setEditing(null)} ukuran="pendek" testId="variant-edit-dialog"
        judul={`Ubah varian ${editing?.sku || ''}`} onSimpan={saveEdit} menyimpan={saving}>
          <div className="space-y-4">
            <div className="space-y-1">
              <Label htmlFor="variant-edit-status">Status produk</Label>
              <SmartNativeSelect id="variant-edit-status" value={form.product_status} searchable={false} className="h-9"
                onChange={(e) => setForm(f => ({ ...f, product_status: e.target.value }))} data-testid="variant-edit-status">
                <option value="">Belum diisi</option>
                {PRODUCT_STATUS_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </SmartNativeSelect>
              {form.product_status === 'stop' && (
                <p className="text-xs text-muted-foreground" data-testid="variant-edit-stop-hint">
                  Varian tetap aktif dan tetap bisa dijual; hanya tidak direncanakan cutting dan tidak diusulkan restock.
                </p>
              )}
            </div>
            <div className="space-y-1">
              <Label htmlFor="variant-edit-barcode">Barcode</Label>
              <Input id="variant-edit-barcode" value={form.barcode} data-testid="variant-edit-barcode"
                onChange={(e) => setForm(f => ({ ...f, barcode: e.target.value }))} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="variant-edit-notes">Catatan</Label>
              <Input id="variant-edit-notes" value={form.notes} data-testid="variant-edit-notes"
                onChange={(e) => setForm(f => ({ ...f, notes: e.target.value }))} />
            </div>
          </div>
      </FormPopup>

      {/* Generate Dialog */}
      <FormPopup open={genOpen} onClose={() => setGenOpen(false)} ukuran="panjang" testId="variant-generate-dialog"
        judul={`Buat varian ${selectedModel?.code || ''}`} keterangan="Kombinasi yang sudah ada dilewati otomatis."
        onSimpan={runGenerate} menyimpan={generating} labelSimpan="Buat varian">
          <div className="space-y-4">
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-semibold text-foreground">Pilih warna</span>
                <Button type="button" variant="link" size="sm"
                  onClick={() => setGenColorIds(genColorIds.length === colors.length ? [] : colors.map(c => c.id))}
                  data-testid="variant-gen-toggle-all-colors">
                  {genColorIds.length === colors.length ? 'Kosongkan' : 'Pilih semua'}
                </Button>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 max-h-48 overflow-y-auto">
                {colors.map(c => {
                  const checked = genColorIds.includes(c.id);
                  return (
                    <label key={c.id}
                      className={`flex items-center gap-2 border rounded-lg px-2.5 py-2 cursor-pointer text-sm transition-colors ${
                        checked ? 'bg-primary/10 border-primary/40 text-foreground' : 'border-[var(--glass-border)] text-foreground hover:bg-[var(--glass-bg-hover)]'
                      }`}
                      data-testid={`variant-gen-color-${c.code}`}>
                      <Checkbox checked={checked} onCheckedChange={() => toggleColor(c.id)} />
                      <span className="inline-block w-4 h-4 rounded border border-[var(--glass-border)]" style={{ backgroundColor: c.hex }} />
                      <span className="truncate">{c.name}</span>
                    </label>
                  );
                })}
              </div>
            </div>
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-semibold text-foreground">Pilih ukuran</span>
                <Button type="button" variant="link" size="sm"
                  onClick={() => setGenSizeIds(genSizeIds.length === sizes.length ? [] : sizes.map(s => s.id))}
                  data-testid="variant-gen-toggle-all-sizes">
                  {genSizeIds.length === sizes.length ? 'Kosongkan' : 'Pilih semua'}
                </Button>
              </div>
              <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
                {sizes.map(s => {
                  const checked = genSizeIds.includes(s.id);
                  return (
                    <label key={s.id}
                      className={`flex items-center justify-center gap-1.5 border rounded-lg px-2 py-2 cursor-pointer text-sm tabular-nums transition-colors ${
                        checked ? 'bg-primary/10 border-primary/40 text-foreground' : 'border-[var(--glass-border)] text-foreground hover:bg-[var(--glass-bg-hover)]'
                      }`}
                      data-testid={`variant-gen-size-${s.code}`}>
                      <Checkbox checked={checked} onCheckedChange={() => toggleSize(s.id)} />
                      {s.code}
                    </label>
                  );
                })}
              </div>
            </div>
            <p className="text-sm text-muted-foreground" data-testid="variant-gen-run-btn">
              Akan dibuat <b className="text-foreground">{genColorIds.length * genSizeIds.length}</b> kombinasi SKU.
            </p>
          </div>
      </FormPopup>
    </PageLayoutSatuBaris>
  );
}

export default RahazaVariantsModule;

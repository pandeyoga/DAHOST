import { useState, useEffect, useCallback, useRef } from 'react';
import PageLayout from './layout/PageLayout';
import FormPopup from '@/components/ui/form-popup';
import { Checkbox } from '@/components/ui/checkbox';
import { Plus, Edit2, Pencil, Trash2, X, Copy, Package, Scale, Save, FileText, Search, Layers, Link2, Unlink, Wrench } from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { toast } from 'sonner';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { EmptyState, Notice } from './moduleAtoms';
import { InlineMaterialPicker } from './bom/InlineMaterialPicker';
import { VersionRail } from './bom/VersionRail';
import { RequirementsPreviewCard } from './bom/RequirementsPreviewCard';
import { BomShortcuts } from './bom/BomShortcuts';
import { typeToCategory, categoryToStoredType, isKgLike } from '@/lib/itemTaxonomy';
import { readField, readNumber, FIELD } from '@/lib/materialFields';  // FASE 6.6-B
import { apiDelete } from '../../lib/api';
import { hapusMaster } from '../../lib/hapusMaster';

/* ─── PT Rahaza · BOM Multi-Version (Phase 7A Fase 1 — unified materials[]) ─────
   - Satu daftar materials[] generik (bukan lagi yarn/accessory terpisah)
   - Tiap baris: pilih dari master + kategori + qty + unit + tipe
   - Matrix view, multi-version (create/edit/activate), preview kebutuhan, copy-to-sizes
────────────────────────────────────────────────────────────────────────────── */

// 2026-11-06 (pola P8): ejaan satuan sama dengan master material (roll/pack, bukan rol/pak)
const UNIT_OPTIONS = ['kg', 'gram', 'm', 'yard', 'pcs', 'lusin', 'set', 'pair', 'roll', 'karton', 'pack'];
// 3 kategori bisnis; komponen BOM hanya Bahan & Aksesoris (FG bukan komponen).
const TYPE_OPTIONS = [
  { value: 'bahan', label: 'Bahan' },
  { value: 'aksesoris', label: 'Aksesoris' },
];
const KGLIKE_TYPES = new Set(['yarn', 'fabric', 'kain', 'benang', 'interlining']);

const blankMaterial = () => ({
  material_id: null, code: '', name: '',
  material_type: 'fabric', category: '', category_name: '',
  qty: '', unit: 'kg', notes: '',
});

const materialsFromVersion = (v) => (v?.materials || []).map(m => ({
  material_id: m.material_id || null,
  code: m.code || '',
  name: m.name || '',
  material_type: m.material_type || 'other',
  category: m.category || '',
  category_name: m.category_name || '',
  qty: String(m.qty ?? ''),
  unit: m.unit || 'pcs',
  notes: m.notes || '',
}));

const selCls = 'w-full h-9 px-2 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-sm text-foreground';

// ACC-2 — baris BOM bertipe aksesoris WAJIB tertaut ke master material
// (memory/PRODUKSI_E9_AKSESORIS.md §ACC-2). Tanpa `material_id`, kebutuhan
// aksesoris tidak bisa dipotong dari stok yang benar & nama/kode gampang drift.
const ACC_TYPES = new Set(['accessory', 'aksesoris', 'packaging', 'kemasan']);
const isAccessoryLine = (m) => ACC_TYPES.has(String(m?.material_type || '').toLowerCase());

export default function RahazaBOMModuleV2({ token }) {
  const [models, setModels] = useState([]);
  const [sizes, setSizes]   = useState([]);
  const [categories, setCategories] = useState([]);
  const [matrix, setMatrix] = useState(null);
  const [selectedModelId, setSelectedModelId] = useState('');
  const [selectedSizeId, setSelectedSizeId] = useState('');
  const [loading, setLoading] = useState(false);

  const [activeTab, setActiveTab] = useState('matrix');

  const [versions, setVersions] = useState([]);
  const [selectedVersion, setSelectedVersion] = useState(null);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const pendingVersionRef = useRef(null); // 2026-09-12: BOM (warna) yang diklik di matriks

  const [editor, setEditor] = useState(null); // { mode:'edit'|'create', versionId?, form }
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState('');
  const [isDirty, setIsDirty] = useState(false);

  const [copyModal, setCopyModal] = useState(null);

  // ACC-2 — kesehatan kopling BOM ↔ master material
  const [linkHealth, setLinkHealth] = useState(null);
  const [relinking, setRelinking] = useState(false);

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const loadLinkHealth = useCallback(async () => {
    try {
      const res = await fetch('/api/rahaza/boms/link-health', { headers: { Authorization: `Bearer ${token}` } });
      setLinkHealth(res.ok ? await res.json() : null);
    } catch { /* noop */ }
  }, [token]);

  const runRelink = async () => {
    setRelinking(true);
    try {
      const res = await fetch('/api/rahaza/boms/relink-materials', {
        method: 'POST', headers, body: JSON.stringify({ dry_run: false }),
      });
      if (!res.ok) throw new Error(`Gagal relink (HTTP ${res.status})`);
      const d = await res.json();
      toast.success(`${d.lines_linked} baris berhasil ditautkan ke master` +
        (d.lines_still_unlinked ? ` · ${d.lines_still_unlinked} baris masih perlu diperbaiki manual` : ''));
      loadLinkHealth();
      loadMatrix();
    } catch (err) {
      toast.error(err.message || 'Gagal menautkan otomatis');
    } finally { setRelinking(false); }
  };

  const loadBase = useCallback(async () => {
    const h = { Authorization: `Bearer ${token}` };
    const [mRes, sRes, cRes] = await Promise.all([
      fetch('/api/rahaza/models', { headers: h }).then(r => r.ok ? r.json() : []),
      fetch('/api/rahaza/sizes',  { headers: h }).then(r => r.ok ? r.json() : []),
      fetch('/api/rahaza/material-categories', { headers: h }).then(r => r.ok ? r.json() : []),
    ]);
    const activeModels = (mRes || []).filter(m => m.active);
    setModels(activeModels);
    setSizes((sRes || []).filter(s => s.active));
    setCategories(cRes || []);
    let storedModel = localStorage.getItem('bom_selected_model');
    const jump = sessionStorage.getItem('bom_jump_model');  // dari Papan Kelengkapan Data (Dashboard RnD)
    if (jump && activeModels.find(m => m.id === jump)) { storedModel = jump; localStorage.setItem('bom_selected_model', jump); sessionStorage.removeItem('bom_jump_model'); }
    if (storedModel && activeModels.find(m => m.id === storedModel)) {
      setSelectedModelId(storedModel);
    } else if (!selectedModelId && activeModels.length) {
      setSelectedModelId(activeModels[0].id);
    }
  }, [token, selectedModelId]);

  const loadMatrix = useCallback(async () => {
    if (!selectedModelId) { setMatrix(null); return; }
    setLoading(true);
    try {
      const res = await fetch(`/api/rahaza/models/${selectedModelId}/bom`, { headers });
      setMatrix(res.ok ? await res.json() : null);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedModelId, token]);

  const loadVersions = useCallback(async () => {
    if (!selectedModelId || !selectedSizeId) {
      setVersions([]); setSelectedVersion(null); return;
    }
    setVersionsLoading(true);
    try {
      const res = await fetch(
        `/api/rahaza/boms/versions?model_id=${selectedModelId}&size_id=${selectedSizeId}`,
        { headers }
      );
      if (res.ok) {
        const data = await res.json();
        setVersions(data || []);
        // 2026-09-12: baris matriks per WARNA → buka versi (BOM) warna yang diklik
        const wanted = pendingVersionRef.current && (data || []).find(v => v.id === pendingVersionRef.current);
        pendingVersionRef.current = null;
        const active = wanted || (data || []).find(v => v.is_active);
        if (active) setSelectedVersion(active);
        else if ((data || []).length > 0) setSelectedVersion(data[0]);
        else setSelectedVersion(null);
      } else {
        setVersions([]); setSelectedVersion(null);
      }
    } finally {
      setVersionsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedModelId, selectedSizeId, token]);

  useEffect(() => { loadBase(); }, [loadBase]);
  useEffect(() => { loadMatrix(); }, [loadMatrix]);
  useEffect(() => { loadLinkHealth(); }, [loadLinkHealth]);
  useEffect(() => { loadVersions(); }, [loadVersions]);
  useEffect(() => {
    if (selectedModelId) localStorage.setItem('bom_selected_model', selectedModelId);
  }, [selectedModelId]);

  const openEditorForSize = (sizeId, bomId = null) => {
    pendingVersionRef.current = bomId;
    if (bomId && sizeId === selectedSizeId) {
      const v = versions.find(x => x.id === bomId);
      if (v) { setSelectedVersion(v); pendingVersionRef.current = null; }
    }
    setSelectedSizeId(sizeId);
    setEditor(null);
    setActiveTab('editor');
  };

  const startCreateVersion = () => {
    const template = selectedVersion ? {
      color: selectedVersion.color || '',
      materials: materialsFromVersion(selectedVersion),
      notes: '',
    } : {
      color: '',
      materials: [blankMaterial()],
      notes: '',
    };
    if (!template.materials.length) template.materials = [blankMaterial()];
    setEditor({ mode: 'create', form: template });
    setIsDirty(false);
    setFormError('');
  };

  const startEditVersion = () => {
    if (!selectedVersion) { toast.error('Pilih versi untuk diedit'); return; }
    setEditor({
      mode: 'edit',
      versionId: selectedVersion.id,
      form: {
        color: selectedVersion.color || '',
        materials: materialsFromVersion(selectedVersion),
        notes: selectedVersion.notes || '',
      },
    });
    setIsDirty(false);
    setFormError('');
  };

  // ── Unified material row handlers ──────────────────────────────────────────
  const updateMaterial = (idx, patch) => {
    setEditor(e => ({
      ...e,
      form: { ...e.form, materials: e.form.materials.map((m, i) => i === idx ? { ...m, ...patch } : m) },
    }));
    setIsDirty(true);
  };

  const addMaterial = () => {
    setEditor(e => ({ ...e, form: { ...e.form, materials: [...e.form.materials, blankMaterial()] } }));
    setIsDirty(true);
  };

  const removeMaterial = (idx) => {
    setEditor(e => ({ ...e, form: { ...e.form, materials: e.form.materials.filter((_, i) => i !== idx) } }));
    setIsDirty(true);
  };

  const selectMaterialFromMaster = (idx, mat) => {
    updateMaterial(idx, {
      material_id: mat.id,
      code: mat.code || '',
      name: mat.name || '',
      material_type: mat.type || 'other',
      category: mat.category || '',
      category_name: mat.category_name || '',
      unit: mat.unit || 'pcs',
    });
    toast.success(`Material ${mat.code} dipilih`);
  };

  const onCategoryChange = (idx, code) => {
    const cat = categories.find(c => c.code === code);
    updateMaterial(idx, { category: code, category_name: cat ? cat.name : '' });
  };

  const saveBOM = async () => {
    if (!editor || !selectedModelId || !selectedSizeId) return;
    setSaving(true);
    setFormError('');
    try {
      const materials = editor.form.materials
        .filter(m => m.name && Number(m.qty) > 0)
        .map(m => ({
          material_id: m.material_id || null,
          code: (m.code || '').toUpperCase(),
          name: m.name,
          material_type: m.material_type || '',
          category: m.category || '',
          category_name: m.category_name || '',
          qty: Number(m.qty),
          unit: m.unit || 'pcs',
          notes: m.notes || '',
        }));

      if (materials.length === 0) {
        throw new Error('Tambahkan minimal 1 material (dengan nama & qty > 0).');
      }

      // ACC-2 — cegah baris aksesoris "lepas" dari master SEBELUM kirim ke server,
      // supaya user langsung tahu baris mana yang harus dipilih dari master.
      const looseAcc = materials
        .map((m, i) => ({ ...m, _row: i + 1 }))
        .filter(m => isAccessoryLine(m) && !m.material_id);
      if (looseAcc.length) {
        throw new Error(
          `Baris aksesoris wajib dipilih dari master material (klik ikon 🔍 di kolom pertama). ` +
          `Belum tertaut: ${looseAcc.map(m => `baris ${m._row} "${m.name}"`).join(', ')}.`
        );
      }

      const payload = {
        model_id: selectedModelId,
        size_id: selectedSizeId,
        color: editor.form.color || '',
        materials,
        notes: editor.form.notes || '',
      };

      let res;
      if (editor.mode === 'edit' && editor.versionId) {
        res = await fetch(`/api/rahaza/boms/${editor.versionId}`, {
          method: 'PUT', headers, body: JSON.stringify(payload),
        });
      } else {
        res = await fetch('/api/rahaza/boms', {
          method: 'POST', headers, body: JSON.stringify(payload),
        });
      }

      if (!res.ok) {
        const errorText = await res.text();
        throw new Error(errorText || `Gagal menyimpan (HTTP ${res.status})`);
      }

      toast.success(editor.mode === 'edit' ? 'Perubahan berhasil disimpan' : 'Versi baru berhasil dibuat');
      setEditor(null);
      setIsDirty(false);
      loadMatrix();
      loadVersions();
    } catch (err) {
      setFormError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleActivateVersion = async (versionId) => {
    try {
      const res = await fetch(`/api/rahaza/boms/${versionId}/activate`, { method: 'POST', headers });
      if (!res.ok) throw new Error('Gagal mengaktifkan versi');
      toast.success('Versi berhasil diaktifkan');
      loadMatrix();
      loadVersions();
    } catch (err) {
      toast.error(err.message || 'Gagal mengaktifkan versi');
    }
  };

  const handleSelectVersion = (versionId) => {
    const version = versions.find(v => v.id === versionId);
    if (version) setSelectedVersion(version);
  };

  // 10 Nov 2026 (owner "master data bisa dihapus"): hapus permanen versi BOM baris ini bila belum menjadi dasar
  // HPP; bila sudah (409) dialog kedua menawarkan Nonaktifkan (perilaku lama DELETE tanpa `hard`).
  const handleHapus = async (row) => {
    if (!row.bom_id) return;
    const hasil = await hapusMaster({
      jenis: 'BOM', nama: [matrix?.model?.code, row.size_code, row.color_code || row.color, row.version ? `v${row.version}` : '']
        .filter(Boolean).join(' '),
      keterangan: 'Versi BOM ini dihapus permanen; versi lain ukuran & warna yang sama tidak disentuh. Bila sudah '
        + 'menjadi dasar HPP, penghapusan ditolak dan Anda bisa menonaktifkannya saja.',
      hapus: () => apiDelete(`/rahaza/boms/${row.bom_id}?hard=true`),
      nonaktifkan: () => apiDelete(`/rahaza/boms/${row.bom_id}`),
    });
    if (hasil) { loadMatrix(); loadVersions(); }
  };

  const openCopy = (row) => {
    if (!row.bom_id) return;
    setCopyModal({ bom_id: row.bom_id, source_size_code: row.size_code, target_ids: [], overwrite: false });
  };

  const runCopy = async () => {
    if (!copyModal) return;
    if (!copyModal.target_ids.length) { toast.error('Pilih minimal 1 size target.'); return; }
    try {
      const res = await fetch(`/api/rahaza/boms/${copyModal.bom_id}/copy-to-sizes`, {
        method: 'POST', headers,
        body: JSON.stringify({ target_size_ids: copyModal.target_ids, overwrite: copyModal.overwrite }),
      });
      if (!res.ok) throw new Error(`Gagal copy (HTTP ${res.status})`);
      const data = await res.json();
      setCopyModal(null);
      loadMatrix();
      toast.success(`Copy selesai. Dibuat: ${data.created.length} · Overwrite: ${data.overwritten.length} · Dilewati: ${data.skipped.length}`);
    } catch (err) {
      toast.error(err.message || 'Gagal copy BOM');
    }
  };

  const selectedModel = matrix?.model;
  const selectedSize = sizes.find(s => s.id === selectedSizeId);
  const activeVersion = versions.find(v => v.is_active);
  const viewerMaterials = selectedVersion?.materials || [];

  return (
    // Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout (dulu judul h1 sendiri); pilih model di baris penyaring.
    <PageLayout testId="rahaza-bom-page" title="Bill of Materials (BOM)"
      subtitle="Resep per model + ukuran + warna: 1 pcs potongan (biaya kain roll ÷ pcs jadi, dari Portal Cutting) + aksesoris."
      filters={(
          <Select
            value={selectedModelId}
            onValueChange={val => { setSelectedModelId(val); setSelectedSizeId(''); setEditor(null); setActiveTab('matrix'); }}
            data-testid="bom-model-selector"
          >
            <SelectTrigger className="w-56" aria-label="Model">
              <SelectValue placeholder="Pilih model" />
            </SelectTrigger>
            <SelectContent>
              {models.map(m => (
                <SelectItem key={m.id} value={m.id}>{m.code} · {m.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
      )}>
      <div className="flex items-center gap-3 flex-wrap" data-testid="bom-shortcuts-card">
        <span className="text-sm font-medium text-foreground">Jalan pintas</span>
        <BomShortcuts headers={headers} token={token} selectedModelId={selectedModelId}
          modelLabel={(models.find(m => m.id === selectedModelId) || {}).code || ''} categories={categories}
          onDone={() => { loadMatrix(); }} />
      </div>

      {/* ACC-2 — kesehatan kopling BOM ↔ master material.
          Banner SELALU tampil bila data kesehatan sudah dimuat: kondisi BURUK
          (amber, ada baris lepas) maupun SEHAT (emerald). Sebelumnya banner
          hilang total saat sehat sehingga user tak pernah dapat konfirmasi
          bahwa rantai BOM→kebutuhan→stok memang utuh. */}
      {linkHealth && (linkHealth.unlinked_lines > 0 ? (
        <Notice tone="warning" testId="bom-link-health-banner"
          title={<>
            {linkHealth.unlinked_lines} baris BOM belum tertaut ke master material
            {linkHealth.unlinked_accessory_lines > 0 && (
              <> — termasuk {linkHealth.unlinked_accessory_lines} baris aksesoris</>
            )}.
          </>}
          action={
            <Button type="button" size="sm" variant="outline" onClick={runRelink} disabled={relinking}
              data-testid="bom-relink-btn">
              <Wrench className="w-3.5 h-3.5" />
              {relinking ? 'Menautkan...' : 'Perbaiki Otomatis'}
            </Button>
          }>
          <p className="text-xs">
            Baris yang tidak tertaut membuat kebutuhan material tidak bisa dipotong dari stok yang benar
            (nama/kode gampang beda dengan master). Perbaikan otomatis akan menautkan baris yang
            <strong> kodenya cocok</strong> dengan master; sisanya perlu dipilih manual di editor.
          </p>
        </Notice>
      ) : (
        <Notice tone="success" testId="bom-link-health-banner" title="Kaitan BOM sehat"
          action={
            <Button type="button" size="sm" variant="outline" onClick={runRelink} disabled={relinking}
              data-testid="bom-relink-btn">
              <Wrench className="w-3.5 h-3.5" />
              {relinking ? 'Memeriksa…' : 'Periksa ulang'}
            </Button>
          }>
          <p>
            {linkHealth.total_lines} baris material ({linkHealth.accessory_lines} aksesoris) di{' '}
            {linkHealth.total_boms} BOM sudah tertaut ke master material.
          </p>
          <p className="text-xs mt-1">
            Rantai BOM → kebutuhan material → stok tersambung, jadi kebutuhan tiap PO bisa
            dibandingkan dengan stok nyata.
          </p>
        </Notice>
      ))}

      {!selectedModelId ? (
        <GlassCard>
          <EmptyState icon={Package} title="Belum ada model yang dipilih"
            description="Pilih model terlebih dahulu untuk mulai mengisi BOM." />
        </GlassCard>
      ) : (        <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
          <TabsList>
            <TabsTrigger value="matrix" data-testid="bom-tab-matrix">Matriks BOM</TabsTrigger>
            <TabsTrigger value="editor" disabled={!selectedSizeId} data-testid="bom-tab-editor">
              Editor {selectedSize ? `· ${selectedSize.code}` : ''}
            </TabsTrigger>
            <TabsTrigger value="preview" disabled={!selectedVersion} data-testid="bom-tab-preview">
              Pratinjau kebutuhan
            </TabsTrigger>
          </TabsList>

          {/* Matrix Tab */}
          <TabsContent value="matrix" className="space-y-4">
            {loading ? (
              <div className="flex items-center justify-center h-48">
                <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-primary" />
              </div>
            ) : !matrix ? (
              <GlassCard className="p-4 text-center text-muted-foreground">
                Tidak dapat memuat data BOM.
              </GlassCard>
            ) : (
              <GlassCard className="p-0 overflow-hidden">
                <div className="px-4 py-3 border-b border-[var(--glass-border)] bg-[var(--glass-bg)]">
                  <div className="flex items-center gap-2 text-sm">
                    <Package className="w-4 h-4 text-primary" />
                    <span className="font-semibold text-foreground">{selectedModel?.code}</span>
                    <span className="text-muted-foreground">· {selectedModel?.name}</span>
                    {typeof matrix.bom_count === 'number' && (
                      <span className="ml-auto text-xs text-muted-foreground" data-testid="bom-matrix-summary">
                        {matrix.bom_count} resep · {matrix.size_count} ukuran · {matrix.color_count} warna
                      </span>
                    )}
                  </div>
                </div>
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Ukuran</TableHead>
                        <TableHead>Warna</TableHead>
                        <TableHead>Versi aktif</TableHead>
                        <TableHead><Scale className="w-3 h-3 inline mr-1" /> Bahan utama /pcs</TableHead>
                        <TableHead>Material</TableHead>
                        <TableHead>Terakhir diubah</TableHead>
                        <TableHead className="text-right">Aksi</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(matrix.matrix || []).map(row => (
                        <TableRow
                          key={row.bom_id || row.size_id}
                          className="hover:bg-[var(--glass-bg-hover)]"
                          data-testid={`bom-row-${row.size_code}${row.color_code ? `-${row.color_code}` : ''}`}
                        >
                          <TableCell className="font-semibold text-foreground">{row.size_code}</TableCell>
                          <TableCell className="text-sm">
                            {row.color_code || row.color
                              ? <span className="inline-flex items-center gap-1.5"><span className="tabular-nums text-xs px-1.5 py-0.5 rounded bg-foreground/[0.06]">{row.color_code || '—'}</span><span className="text-foreground/80">{row.color}</span></span>
                              : <span className="text-xs text-muted-foreground">—</span>}
                          </TableCell>
                          <TableCell>
                            {row.bom_id ? (
                              <Badge variant="default" className="text-xs">v{row.version}</Badge>
                            ) : (
                              <span className="text-xs text-muted-foreground">Belum ada</span>
                            )}
                          </TableCell>
                          <TableCell className="tabular-nums text-foreground">
                            {row.panel_code ? (
                              <span data-testid={`bom-panel-${row.panel_code}`} title={row.panel_source_fabric ? `Kain asal: ${row.panel_source_fabric}` : ''}>
                                1 pcs <span className="text-[hsl(var(--primary))]">{row.panel_code}</span>
                              </span>
                            ) : (
                              <>{readNumber(row, FIELD.totalMaterialKgPerPcs) ? readNumber(row, FIELD.totalMaterialKgPerPcs).toFixed(3) : '—'} kg</>
                            )}
                          </TableCell>
                          <TableCell className="text-muted-foreground text-xs">
                            {row.material_count || 0} material
                            {row.material_count ? (row.panel_code
                              ? ` (potongan · ${row.accessory_count} aksesoris)`
                              : ` (${readNumber(row, FIELD.bulkLineCount)} bahan · ${row.accessory_count} aksesoris)`) : ''}
                          </TableCell>
                          <TableCell className="text-muted-foreground text-xs">
                            {row.updated_at ? new Date(row.updated_at).toLocaleDateString('id-ID') : '—'}
                          </TableCell>
                          <TableCell className="text-right">
                            <div className="inline-flex items-center gap-1">
                              <Button type="button"
                                variant="ghost" size="icon-sm"
                                title={row.bom_id ? 'Ubah BOM' : 'Buat BOM'} aria-label={row.bom_id ? 'Ubah BOM' : 'Buat BOM'}
                                onClick={() => openEditorForSize(row.size_id, row.bom_id)}
                                data-testid={`bom-open-${row.size_code}${row.color_code ? `-${row.color_code}` : ''}`}
                              >
                                {row.bom_id ? <Pencil className="w-3.5 h-3.5" /> : <Plus className="w-3.5 h-3.5" />}
                              </Button>
                              {row.bom_id && (
                                <Button type="button"
                                  variant="ghost" size="icon-sm"
                                  title="Salin ke size lain" aria-label="Salin ke size lain"
                                  onClick={() => openCopy(row)}
                                  data-testid={`bom-copy-${row.size_code}${row.color_code ? `-${row.color_code}` : ''}`}
                                >
                                  <Copy className="w-3.5 h-3.5" />
                                </Button>
                              )}
                              {row.bom_id && (
                                <Button type="button"
                                  variant="ghost" size="icon-sm"
                                  title="Hapus" aria-label={`Hapus BOM ukuran ${row.size_code}${row.color_code ? ` warna ${row.color_code}` : ''}`}
                                  onClick={() => handleHapus(row)}
                                  data-testid={`bom-delete-${row.size_code}${row.color_code ? `-${row.color_code}` : ''}`}
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </Button>
                              )}
                            </div>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </GlassCard>
            )}
          </TabsContent>

          {/* Editor Tab */}
          <TabsContent value="editor" className="space-y-4">
            {!selectedSizeId ? (
              <GlassCard>
                <EmptyState icon={Layers} title="Belum ada size yang dipilih"
                  description="Pilih size dari matriks untuk mulai edit BOM." />
              </GlassCard>
            ) : (
              <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
                <div className="lg:col-span-8 space-y-4">
                  {editor ? (
                    <GlassCard className="p-5 space-y-5" data-testid="bom-editor-form">
                      <div className="flex items-center justify-between">
                        <div>
                          <p className="text-base font-semibold text-foreground">
                            {editor.mode === 'edit' ? 'Edit Versi' : 'Buat Versi Baru'}
                          </p>
                          <p className="text-sm text-muted-foreground">
                            {selectedModel?.code} · {selectedSize?.code}
                            {editor.mode === 'edit' && selectedVersion ? ` · v${selectedVersion.version}` : ''}
                          </p>
                        </div>
                        {isDirty && (
                          <Badge variant="outline" className="text-warning border-warning">Belum disimpan</Badge>
                        )}
                      </div>

                      {formError && (
                        <div
                          data-testid="bom-form-error"
                          className="bg-[hsl(var(--destructive)/0.15)] border border-[hsl(var(--destructive)/0.35)]  rounded-lg p-3 text-sm text-[hsl(var(--danger-text))] "
                        >
                          {formError}
                        </div>
                      )}

                      {/* Unified Materials */}
                      <div>
                        <div className="flex items-center justify-between mb-3">
                          <div className="flex items-center gap-2">
                            <Layers className="w-4 h-4 text-primary" />
                            <span className="text-sm font-semibold text-foreground">Daftar Material</span>
                            <span className="text-xs text-muted-foreground">qty per pcs</span>
                          </div>
                          <Button type="button" variant="outline" size="sm" onClick={addMaterial} data-testid="bom-add-material-btn">
                            <Plus className="w-4 h-4 mr-1" /> Tambah Material
                          </Button>
                        </div>
                        <div className="border border-[var(--glass-border)] rounded-lg overflow-x-auto">
                          <Table>
                            <TableHeader>
                              <TableRow>
                                <TableHead className="w-[36px]"></TableHead>
                                <TableHead className="min-w-[180px]">Nama</TableHead>
                                <TableHead className="min-w-[120px]">Kode</TableHead>
                                <TableHead className="min-w-[150px]">Kategori</TableHead>
                                <TableHead className="min-w-[120px]">Tipe</TableHead>
                                <TableHead className="w-24">Qty</TableHead>
                                <TableHead className="w-28">Unit</TableHead>
                                <TableHead className="w-10"></TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {editor.form.materials.map((m, idx) => (
                                <TableRow key={idx}>
                                  <TableCell>
                                    <div className="flex items-center gap-1">
                                      <InlineMaterialPicker
                                        token={token}
                                        categories={categories}
                                        onSelect={mat => selectMaterialFromMaster(idx, mat)}
                                      >
                                        <Button type="button" variant="ghost" size="icon-sm" title="Pilih dari master" aria-label="Pilih dari master">
                                          <Search className="w-3.5 h-3.5" />
                                        </Button>
                                      </InlineMaterialPicker>
                                      {/* ACC-2 — indikator kopling ke master material */}
                                      {m.material_id ? (
                                        <span title="Tertaut ke master material" data-testid={`bom-mat-${idx}-linked`}>
                                          <Link2 className="w-3.5 h-3.5 text-[hsl(var(--success-text))] " />
                                        </span>
                                      ) : (
                                        <span
                                          title={isAccessoryLine(m)
                                            ? 'WAJIB: baris aksesoris harus dipilih dari master material'
                                            : 'Belum tertaut ke master material (disarankan pilih dari master)'}
                                          data-testid={`bom-mat-${idx}-unlinked`}
                                        >
                                          <Unlink className={`w-3.5 h-3.5 ${isAccessoryLine(m)
                                            ? 'text-[hsl(var(--danger-text))] '
                                            : 'text-[hsl(var(--warning-text))] '}`} />
                                        </span>
                                      )}
                                    </div>
                                  </TableCell>
                                  <TableCell>
                                    <GlassInput
                                      value={m.name}
                                      onChange={e => updateMaterial(idx, { name: e.target.value })}
                                      placeholder="Kain Katun 30s"
                                      data-testid={`bom-mat-${idx}-name`}
                                    />
                                  </TableCell>
                                  <TableCell>
                                    <GlassInput
                                      value={m.code}
                                      onChange={e => updateMaterial(idx, { code: e.target.value.toUpperCase() })}
                                      placeholder="YRN-ACR28"
                                      data-testid={`bom-mat-${idx}-code`}
                                    />
                                  </TableCell>
                                  <TableCell>
                                    <SmartNativeSelect
                                      className={selCls}
                                      value={m.category || ''}
                                      onChange={e => onCategoryChange(idx, e.target.value)}
                                      data-testid={`bom-mat-${idx}-category`}
                                    >
                                      <option value="">— Kategori —</option>
                                      {categories.map(c => <option key={c.code} value={c.code}>{c.name}</option>)}
                                    </SmartNativeSelect>
                                  </TableCell>
                                  <TableCell>
                                    <SmartNativeSelect
                                      className={selCls}
                                      value={typeToCategory(m.material_type)}
                                      onChange={e => {
                                        const st = categoryToStoredType(e.target.value);
                                        const patch = { material_type: st };
                                        if (isKgLike(st) && !KGLIKE_TYPES.has(m.material_type)) patch.unit = 'kg';
                                        updateMaterial(idx, patch);
                                      }}
                                      data-testid={`bom-mat-${idx}-type`}
                                    >
                                      {TYPE_OPTIONS.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                                    </SmartNativeSelect>
                                  </TableCell>
                                  <TableCell>
                                    <GlassInput
                                      type="number"
                                      step="0.001"
                                      value={m.qty}
                                      onChange={e => updateMaterial(idx, { qty: e.target.value })}
                                      placeholder="0.300"
                                      data-testid={`bom-mat-${idx}-qty`}
                                    />
                                  </TableCell>
                                  <TableCell>
                                    <SmartNativeSelect
                                      className={selCls}
                                      value={m.unit || 'pcs'}
                                      onChange={e => updateMaterial(idx, { unit: e.target.value })}
                                      data-testid={`bom-mat-${idx}-unit`}
                                    >
                                      {UNIT_OPTIONS.map(u => <option key={u} value={u}>{u}</option>)}
                                    </SmartNativeSelect>
                                  </TableCell>
                                  <TableCell>
                                    <Button type="button"
                                      variant="ghost" size="icon-sm"
                                      className="hover:bg-[hsl(var(--destructive)/0.1)] hover:text-[hsl(var(--danger-text))]"
                                      title="Hapus baris" aria-label="Hapus baris"
                                      onClick={() => removeMaterial(idx)}
                                      data-testid={`bom-mat-${idx}-remove`}
                                    >
                                      <X className="w-4 h-4" />
                                    </Button>
                                  </TableCell>
                                </TableRow>
                              ))}
                              {editor.form.materials.length === 0 && (
                                <TableRow>
                                  <TableCell colSpan={8} className="text-center py-6 text-xs text-muted-foreground">
                                    Belum ada material. Klik "Tambah Material" untuk mulai.
                                  </TableCell>
                                </TableRow>
                              )}
                            </TableBody>
                          </Table>
                        </div>
                      </div>

                      {/* Notes */}
                      <div>
                        <label className="block text-xs font-medium text-foreground/70 mb-1">
                          Catatan BOM (opsional)
                        </label>
                        <GlassInput
                          value={editor.form.notes}
                          onChange={e => { setEditor(ed => ({ ...ed, form: { ...ed.form, notes: e.target.value } })); setIsDirty(true); }}
                          placeholder="cth: sample awal, revisi #2, dsb"
                          data-testid="bom-notes-input"
                        />
                      </div>

                      {/* Actions */}
                      <div className="flex items-center justify-end gap-2 pt-2 border-t border-[var(--glass-border)]">
                        <Button type="button"
                          variant="ghost"
                          onClick={async () => {
                            if (isDirty && !(await confirmDialog({
                              title: 'Batalkan perubahan?',
                              body: 'Ada perubahan belum disimpan. Perubahan itu akan hilang.',
                              confirmLabel: 'Batalkan perubahan',
                              cancelLabel: 'Kembali',
                              danger: true,
                            }))) return;
                            setEditor(null); setIsDirty(false); setFormError('');
                          }}
                          disabled={saving}
                        >
                          Batal
                        </Button>
                        <Button type="button" onClick={saveBOM} disabled={saving} data-testid="bom-save-btn">
                          <Save className="w-4 h-4 mr-2" />
                          {saving ? 'Menyimpan...' : (editor.mode === 'edit' ? 'Simpan Perubahan' : 'Simpan Versi Baru')}
                        </Button>
                      </div>
                    </GlassCard>
                  ) : (
                    // Version Viewer
                    <GlassCard className="p-5">
                      {selectedVersion ? (
                        <div className="space-y-4">
                          <div className="flex items-center justify-between">
                            <div>
                              <p className="text-base font-semibold text-foreground flex items-center gap-2">
                                <FileText className="w-5 h-5 text-primary" />
                                BOM v{selectedVersion.version}
                                {selectedVersion.is_active && (<Badge variant="default" className="ml-2">Aktif</Badge>)}
                              </p>
                              <p className="text-sm text-muted-foreground mt-1">
                                {selectedModel?.code} · {selectedSize?.code}
                                {' · '}{selectedVersion.material_count || viewerMaterials.length} material
                                {readNumber(selectedVersion, FIELD.totalMaterialKgPerPcs) ? ` · ${readNumber(selectedVersion, FIELD.totalMaterialKgPerPcs).toFixed(3)} kg/pcs` : ''}
                              </p>
                            </div>
                            <div className="flex gap-2">
                              <Button type="button" variant="outline" size="sm" onClick={startCreateVersion} data-testid="bom-create-new-version-btn">
                                <Plus className="w-4 h-4 mr-2" /> Versi Baru
                              </Button>
                              <Button type="button" variant="default" size="sm" onClick={startEditVersion} data-testid="bom-edit-version-btn">
                                <Edit2 className="w-4 h-4 mr-2" /> Edit
                              </Button>
                            </div>
                          </div>

                          {viewerMaterials.length > 0 ? (
                            <div>
                              <h4 className="text-sm font-semibold text-foreground mb-2 flex items-center gap-2">
                                <Layers className="w-4 h-4 text-primary" />
                                Material ({viewerMaterials.length})
                              </h4>
                              <div className="border border-[var(--glass-border)] rounded-lg overflow-x-auto">
                                <Table data-testid="bom-viewer-materials-table">
                                  <TableHeader>
                                    <TableRow>
                                      <TableHead className="w-10" title="Tertaut ke master material?">Taut</TableHead>
                                      <TableHead>Kode</TableHead>
                                      <TableHead>Nama</TableHead>
                                      <TableHead>Kategori</TableHead>
                                      <TableHead>Tipe</TableHead>
                                      <TableHead className="text-right">Qty</TableHead>
                                      <TableHead>Unit</TableHead>
                                    </TableRow>
                                  </TableHeader>
                                  <TableBody>
                                    {viewerMaterials.map((m, idx) => (
                                      <TableRow key={idx} data-testid={`bom-viewer-row-${idx}`}>
                                        {/* ACC-2 — status kopling ke master material terlihat TANPA
                                            harus masuk mode Edit (baris lepas = rantai stok putus). */}
                                        <TableCell>
                                          {m.material_id ? (
                                            <span title="Tertaut ke master material"
                                              data-testid={`bom-viewer-mat-${idx}-linked`}>
                                              <Link2 className="w-3.5 h-3.5 text-[hsl(var(--success-text))] " />
                                            </span>
                                          ) : (
                                            <span
                                              title={isAccessoryLine(m)
                                                ? 'WAJIB: baris aksesoris harus dipilih dari master material'
                                                : 'Belum tertaut ke master material (disarankan pilih dari master)'}
                                              data-testid={`bom-viewer-mat-${idx}-unlinked`}>
                                              <Unlink className={`w-3.5 h-3.5 ${isAccessoryLine(m)
                                                ? 'text-[hsl(var(--danger-text))] '
                                                : 'text-[hsl(var(--warning-text))] '}`} />
                                            </span>
                                          )}
                                        </TableCell>
                                        <TableCell className="tabular-nums text-xs">{m.code || '—'}</TableCell>
                                        <TableCell>{m.name}</TableCell>
                                        <TableCell className="text-xs text-muted-foreground">{m.category_name || '—'}</TableCell>
                                        <TableCell className="text-xs text-muted-foreground">
                                          {(TYPE_OPTIONS.find(t => t.value === m.material_type) || {}).label || m.material_type}
                                        </TableCell>
                                        <TableCell className="text-right tabular-nums">{m.qty}</TableCell>
                                        <TableCell className="text-xs">{m.unit}</TableCell>
                                      </TableRow>
                                    ))}
                                  </TableBody>
                                </Table>
                              </div>
                            </div>
                          ) : (
                            <div className="text-center py-6 text-sm text-muted-foreground">
                              Versi ini belum memiliki material. Klik "Edit" untuk menambah.
                            </div>
                          )}

                          {selectedVersion.notes && (
                            <div className="p-3 bg-[var(--glass-bg)] rounded-lg border border-[var(--glass-border)]">
                              <div className="text-xs font-medium text-muted-foreground mb-1">Catatan</div>
                              <div className="text-sm text-foreground">{selectedVersion.notes}</div>
                            </div>
                          )}
                        </div>
                      ) : (
                        <EmptyState icon={FileText} title="Belum ada versi BOM untuk size ini"
                          description="Buat versi pertama untuk mulai mencatat material size ini."
                          action={
                            <Button type="button"
                              variant="outline" size="sm"
                              onClick={() => { setEditor({ mode: 'create', form: { color: '', materials: [blankMaterial()], notes: '' } }); setIsDirty(false); setFormError(''); }}
                              data-testid="bom-create-first-version-btn"
                            >
                              <Plus className="w-4 h-4" /> Buat versi pertama
                            </Button>
                          } />
                      )}
                    </GlassCard>
                  )}
                </div>

                {/* Version Rail */}
                <div className="lg:col-span-4">
                  <VersionRail
                    versions={versions}
                    activeVersionId={activeVersion?.id}
                    selectedVersionId={selectedVersion?.id}
                    onSelectVersion={handleSelectVersion}
                    onCreateVersion={startCreateVersion}
                    onActivateVersion={handleActivateVersion}
                    loading={versionsLoading}
                  />
                </div>
              </div>
            )}
          </TabsContent>

          {/* Preview Tab */}
          <TabsContent value="preview">
            {selectedVersion ? (
              <RequirementsPreviewCard bom={selectedVersion} token={token} />
            ) : (
              <GlassCard>
                <EmptyState icon={FileText} title="Belum ada versi BOM yang dipilih"
                  description="Pilih versi BOM untuk melihat preview kebutuhan material." />
              </GlassCard>
            )}
          </TabsContent>
        </Tabs>
      )}

      {/* Copy Modal */}
      {copyModal && (
        <FormPopup open onClose={() => setCopyModal(null)} ukuran="pendek" testId="bom-copy-modal"
          judul={`Salin BOM dari ukuran ${copyModal.source_size_code}`} onSimpan={runCopy} labelSimpan="Salin">
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Pilih size tujuan. Material akan disalin sesuai versi aktif.
              </p>
              <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
                {(matrix?.matrix || [])
                  .filter(r => r.size_code !== copyModal.source_size_code)
                  .map(r => {
                    const checked = copyModal.target_ids.includes(r.size_id);
                    return (
                      <label
                        key={r.size_id}
                        className={`border border-[var(--glass-border)] rounded-lg px-3 py-2 cursor-pointer text-sm flex items-center gap-2 transition-colors ${
                          checked ? 'bg-primary/10 border-primary/40 text-foreground'
                                  : 'text-foreground hover:bg-[var(--glass-bg-hover)]'
                        }`}
                      >
                        <Checkbox
                          checked={checked}
                          onCheckedChange={v =>
                            setCopyModal(c => ({
                              ...c,
                              target_ids: v
                                ? [...c.target_ids, r.size_id]
                                : c.target_ids.filter(x => x !== r.size_id),
                            }))
                          }
                          data-testid={`bom-copy-target-${r.size_code}`}
                        />
                        <span className="tabular-nums">{r.size_code}</span>
                        {r.bom_id && <span className="text-xs text-[hsl(var(--warning-text))]">(ada)</span>}
                      </label>
                    );
                  })}
              </div>
              <label className="flex items-center gap-2 text-sm text-foreground cursor-pointer">
                <Checkbox
                  checked={copyModal.overwrite}
                  onCheckedChange={v => setCopyModal(c => ({ ...c, overwrite: !!v }))}
                  data-testid="bom-copy-overwrite"
                />
                Timpa BOM yang sudah ada
              </label>
            </div>
        </FormPopup>
      )}
    </PageLayout>
  );
}

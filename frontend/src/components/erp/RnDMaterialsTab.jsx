/**
 * RnDMaterialsTab — Riset Material (Portal RnD; juga tab di RnDModule lama).
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, cari ± 16 rem (dulu selebar layar), tabel + unduh, rincian =
 * DetailPopup, form = FormPopup panjang (isian sama, dulu overlay buatan sendiri dengan <input>/<button>
 * polos), ikon aksi ber-aria-label, warna token. Endpoint & isi payload tidak berubah.
 */
import { useState, useEffect } from 'react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Input } from '@/components/ui/input';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { Skeleton } from '@/components/ui/skeleton';
import { Beaker, Pencil, Plus, RefreshCw, Search, Trash2 } from 'lucide-react';
import { toast } from '../ui/sonner';
import { apiFetch, ApiError } from '@/lib/apiFetch';
import { hapusMaster } from '@/lib/hapusMaster';
import { MoneyInput } from '@/components/ui/money-input';
import RnDUnitSelect from './RnDUnitSelect';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { ColorMultiSelect, useColorOptions } from './RnDColorPicker';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatusBadge } from './moduleAtoms';

const FORM_KOSONG = {
  material_code: '',
  material_name: '',
  category: '',
  category_code: '',
  vendor: '',
  vendor_id: '',
  vendor_is_prospect: false,
  composition: '',
  weight: 0,
  price_per_unit: 0,
  price_unit: 'm',
  min_order_qty: 0,
  colors: [],
  test_results: '',
  notes: '',
  status: 'active',
};

const hargaOf = (m) => m.price_per_unit ?? m.price_per_meter ?? 0;
const fmtHarga = (m) => `Rp ${Number(hargaOf(m)).toLocaleString('id-ID')} / ${m.price_unit || 'm'}`;
const STATUS_MAT = { active: { label: 'Aktif', tone: 'success' }, inactive: { label: 'Nonaktif', tone: 'muted' } };

function ChipWarna({ warna }) {
  if (!warna?.length) return <span className="text-muted-foreground">—</span>;
  return (
    <div className="flex flex-wrap items-center gap-1">
      {warna.map((c) => (
        <span key={c.color_id || c.code} title={`${c.name} (${c.code})`}
          className="inline-flex items-center gap-1 rounded-full border border-[var(--glass-border)] bg-[var(--card-surface)] py-0.5 pl-1 pr-1.5 text-xs">
          {/* warna bahan = data (hex dari master warna), bukan hiasan */}
          <span className="h-2.5 w-2.5 rounded-full border border-[var(--glass-border)]" style={{ backgroundColor: c.hex }} />
          <span className="font-mono text-muted-foreground">{c.code}</span>
        </span>
      ))}
    </div>
  );
}

export default function RnDMaterialsTab({ token }) {
  const { colors: colorOpts, addColor } = useColorOptions();
  const [materials, setMaterials] = useState([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null);
  const [saving, setSaving] = useState(false);
  const [detail, setDetail] = useState(null);
  const [form, setForm] = useState({ ...FORM_KOSONG });

  useEffect(() => {
    fetchMaterials();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  // 2026-11-07 (Tahap 6, PR6): Kategori = daftar tetap dari server (kategori Master Material); Vendor = master
  // supplier (id + nama) dengan cadangan eksplisit "Calon supplier" untuk vendor yang belum jadi supplier.
  // Dulu keduanya teks bebas. Nilai lama tetap tampil (ditandai "lama").
  const [formOpts, setFormOpts] = useState({ categories: [], suppliers: [] });
  useEffect(() => {
    if (!showForm) return;
    apiFetch('/dewi/rnd/material-form-options')
      .then(d => setFormOpts({ categories: d?.categories || [], suppliers: d?.suppliers || [] }))
      .catch(() => setFormOpts({ categories: [], suppliers: [] }));
  }, [showForm]);
  const LEGACY = '__lama__';
  const PROSPECT = '__calon__';
  const categoryValue = form.category_code || (form.category ? LEGACY : '');
  const vendorValue = form.vendor_id || (form.vendor_is_prospect ? PROSPECT : (form.vendor ? LEGACY : ''));
  const pickCategory = (v) => {
    if (v === LEGACY) return;
    const c = formOpts.categories.find(x => x.code === v);
    setForm(p => ({ ...p, category_code: v, category: c?.name || '' }));
  };
  const pickVendor = (v) => {
    if (v === LEGACY) return;
    if (v === PROSPECT) { setForm(p => ({ ...p, vendor_id: '', vendor_is_prospect: true, vendor: p.vendor_id ? '' : p.vendor })); return; }
    const sup = formOpts.suppliers.find(x => x.id === v);
    setForm(p => ({ ...p, vendor_id: v, vendor_is_prospect: false, vendor: sup?.name || '' }));
  };

  const fetchMaterials = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (search) params.set('search', search);
      const qs = params.toString();
      const data = await apiFetch(`/dewi/rnd/materials${qs ? '?' + qs : ''}`);
      setMaterials(Array.isArray(data) ? data : []);
    } catch (e) {
      if (e instanceof ApiError && !e.isUnauthorized) {
        toast.error(e.userMessage || 'Gagal memuat data material');
      }
    } finally {
      setLoading(false);
    }
  };

  const openCreate = () => {
    setEditing(null);
    setForm({ ...FORM_KOSONG });
    setShowForm(true);
  };

  const openEdit = (material) => {
    setDetail(null);
    setEditing(material);
    // Dokumen lama hanya punya `price_per_meter` → dibaca sebagai harga per meter.
    setForm({
      ...material,
      price_per_unit: material.price_per_unit ?? material.price_per_meter ?? 0,
      price_unit: material.price_unit || 'm',
      category_code: material.category_code || '',
      vendor_id: material.vendor_id || '',
      vendor_is_prospect: !!material.vendor_is_prospect,
      colors: Array.isArray(material.colors) ? material.colors : [],
    });
    setShowForm(true);
  };

  const handleSave = async () => {
    if (!form.material_code.trim() || !form.material_name.trim()) {
      toast.error('Kode material dan nama material wajib diisi');
      return;
    }
    if (form.vendor_is_prospect && !String(form.vendor || '').trim()) {
      toast.error('Ketik nama calon supplier, atau pilih supplier dari master');
      return;
    }

    setSaving(true);
    try {
      const path = editing
        ? `/dewi/rnd/materials/${editing.id}`
        : '/dewi/rnd/materials';
      const method = editing ? 'PUT' : 'POST';
      await apiFetch(path, { method, body: form });
      toast.success(editing ? 'Material berhasil disimpan' : 'Material berhasil dibuat');
      setShowForm(false);
      fetchMaterials();
    } catch (e) {
      if (e instanceof ApiError && !e.isUnauthorized) {
        toast.error(e.userMessage || 'Gagal menyimpan material');
      }
    } finally {
      setSaving(false);
    }
  };

  // 10 Nov 2026 (owner "master data bisa dihapus"): server menolak (409) bahan yang masih dipakai HPP, costing
  // sampel, atau tech pack; dialog kedua menawarkan Nonaktifkan (status nonaktif).
  const handleDelete = async (m) => {
    const hasil = await hapusMaster({
      jenis: 'bahan', nama: [m.material_code, m.material_name].filter(Boolean).join(' '),
      hapus: () => apiFetch(`/dewi/rnd/materials/${m.id}`, { method: 'DELETE' }),
      nonaktifkan: m.status !== 'inactive'
        ? () => apiFetch(`/dewi/rnd/materials/${m.id}`, { method: 'PUT', body: { status: 'inactive' } })
        : null,
    });
    if (!hasil) return;
    setDetail(null);
    fetchMaterials();
  };

  const { page, setPage, totalPages, total, paged } = useClientPagination(materials, 25);

  const AksiBaris = ({ m }) => (
    <div className="flex items-center justify-end gap-1">
      <Button variant="ghost" size="icon-sm" onClick={() => openEdit(m)} aria-label="Ubah material" title="Ubah material"
        data-testid={`edit-material-${m.id}`}>
        <Pencil />
      </Button>
      <Button variant="ghost" size="icon-sm" onClick={() => handleDelete(m)} aria-label={`Hapus bahan ${m.material_code || ''}`} title="Hapus"
        className="text-[hsl(var(--danger-text))]" data-testid={`delete-material-${m.id}`}>
        <Trash2 />
      </Button>
    </div>
  );

  const kolom = [
    { kunci: 'kode', label: 'Kode', hp: 'judul', isi: (m) => <span className="font-mono text-sm font-semibold">{m.material_code}</span> },
    { kunci: 'nama', label: 'Nama material', hp: 'keterangan', isi: (m) => m.material_name },
    { kunci: 'kategori', label: 'Kategori', isi: (m) => m.category || <span className="text-muted-foreground">—</span> },
    { kunci: 'vendor', label: 'Vendor', isi: (m) => (
      <span>{m.vendor || <span className="text-muted-foreground">—</span>}
        {m.vendor_is_prospect && <span className="ml-1 text-xs text-muted-foreground">(calon)</span>}</span>) },
    { kunci: 'warna', label: 'Warna', isi: (m) => <div data-testid={`material-colors-${m.id}`}><ChipWarna warna={m.colors} /></div> },
    { kunci: 'harga', label: 'Harga/satuan', rata: 'kanan', isi: (m) => (
      <span className="tabular-nums md:whitespace-nowrap" data-testid={`material-price-${m.id}`}>
        Rp {Number(hargaOf(m)).toLocaleString('id-ID')}<span className="text-muted-foreground"> / {m.price_unit || 'm'}</span>
      </span>) },
    { kunci: 'aksi', label: 'Aksi', rata: 'kanan', hp: 'aksi', isi: (m) => <AksiBaris m={m} /> },
  ];

  return (
    <PageLayout testId="rnd-materials-tab" title="Riset Material"
      subtitle="Bahan hasil riset: vendor, harga per satuan, dan warna tersedia — dipakai di HPP dan biaya sample."
      actions={<Button onClick={openCreate} data-testid="create-material-btn"><Plus />Tambah material</Button>}
      filters={
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder="Cari material" value={search} onChange={(e) => setSearch(e.target.value)}
            className="pl-8" data-testid="material-search" />
        </div>
      }
      tools={<>
        <TombolUnduh namaBerkas="riset-material" namaLembar="Riset material" baris={materials} testId="material-unduh"
          kolom={[
            { label: 'Kode', nilai: (m) => m.material_code },
            { label: 'Nama material', nilai: (m) => m.material_name },
            { label: 'Kategori', nilai: (m) => m.category || '' },
            { label: 'Vendor', nilai: (m) => `${m.vendor || ''}${m.vendor_is_prospect ? ' (calon)' : ''}` },
            { label: 'Warna', nilai: (m) => (m.colors || []).map((c) => c.name || c.code).join(', ') },
            { label: 'Harga per satuan (Rp)', nilai: (m) => Number(hargaOf(m)) },
            { label: 'Satuan harga', nilai: (m) => m.price_unit || 'm' },
            { label: 'Min. order', nilai: (m) => Number(m.min_order_qty || 0) },
            { label: 'Status', nilai: (m) => (STATUS_MAT[m.status] || {}).label || m.status || '' },
          ]} />
        <Button variant="outline" size="icon" onClick={fetchMaterials} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      footer={materials.length > 25 && (
        <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />
      )}>
      <GlassCard className="p-0 overflow-hidden">
        {loading && materials.length === 0 ? (
          <div className="space-y-2 p-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-10" />)}</div>
        ) : (
          <TabelData kolom={kolom} baris={paged} onKlikBaris={setDetail} testId="material-table"
            kosong={<EmptyState icon={Beaker} title={search ? 'Tidak ada material yang cocok' : 'Belum ada material riset'}
              description={search ? 'Ubah kata pencarian.' : 'Catat bahan yang sedang diriset beserta vendor, harga, dan warnanya.'}
              action={!search && <Button onClick={openCreate}><Plus />Tambah material</Button>} />} />
        )}
      </GlassCard>

      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} testId="material-detail"
          judul={detail.material_name} keterangan={detail.material_code}
          status={STATUS_MAT[detail.status] && <StatusBadge status={detail.status} tone={STATUS_MAT[detail.status].tone} label={STATUS_MAT[detail.status].label} />}
          aksi={<>
            <Button size="sm" variant="outline" onClick={() => openEdit(detail)}><Pencil />Ubah</Button>
            <Button size="sm" variant="destructive" onClick={() => handleDelete(detail)}><Trash2 />Hapus</Button>
          </>}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Kategori">{detail.category || '—'}</BarisDetail>
            <BarisDetail label="Vendor">{detail.vendor || '—'}{detail.vendor_is_prospect ? ' (calon supplier)' : ''}</BarisDetail>
            <BarisDetail label="Harga">{fmtHarga(detail)}</BarisDetail>
            <BarisDetail label="Min. order">{Number(detail.min_order_qty || 0).toLocaleString('id-ID')}</BarisDetail>
            <BarisDetail label="Warna tersedia"><ChipWarna warna={detail.colors} /></BarisDetail>
            {detail.composition && <BarisDetail label="Komposisi">{detail.composition}</BarisDetail>}
            {Number(detail.weight) > 0 && <BarisDetail label="Berat">{Number(detail.weight).toLocaleString('id-ID')}</BarisDetail>}
            {detail.test_results && <BarisDetail label="Hasil uji">{detail.test_results}</BarisDetail>}
            {detail.notes && <BarisDetail label="Catatan">{detail.notes}</BarisDetail>}
          </dl>
        </DetailPopup>
      )}

      <FormPopup open={showForm} onClose={() => setShowForm(false)} ukuran="panjang"
        judul={editing ? 'Ubah material' : 'Tambah material'}
        keterangan="Harga ini dipakai HPP & biaya sample; qty BOM dikonversi ke satuan harga."
        onSimpan={handleSave} menyimpan={saving} testId="material-form">
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Kode material" wajib htmlFor="mat-kode">
            <Input id="mat-kode" value={form.material_code}
              onChange={(e) => setForm({ ...form, material_code: e.target.value.toUpperCase() })} />
          </Isian>
          <Isian label="Nama material" wajib htmlFor="mat-nama">
            <Input id="mat-nama" value={form.material_name} onChange={(e) => setForm({ ...form, material_name: e.target.value })} />
          </Isian>
          <Isian label="Kategori" htmlFor="mat-kategori">
            <SmartNativeSelect id="mat-kategori" value={categoryValue} onChange={(e) => pickCategory(e.target.value)}
              aria-label="Kategori" data-testid="material-category-select">
              <option value="">Pilih kategori</option>
              {categoryValue === LEGACY && <option value={LEGACY}>{`${form.category} (lama, belum ada di daftar)`}</option>}
              {formOpts.categories.map(c => <option key={c.code} value={c.code}>{c.name}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Vendor" htmlFor="mat-vendor" petunjuk="Dari Master Supplier (Pengadaan).">
            <SmartNativeSelect id="mat-vendor" value={vendorValue} onChange={(e) => pickVendor(e.target.value)}
              aria-label="Vendor" data-testid="material-vendor-select">
              <option value="">Belum ada vendor</option>
              <option value={PROSPECT}>Calon supplier (belum di master) — ketik nama</option>
              {vendorValue === LEGACY && <option value={LEGACY}>{`${form.vendor} (lama, belum di master)`}</option>}
              {formOpts.suppliers.map(sup => <option key={sup.id} value={sup.id}>{`${sup.code ? `${sup.code} · ` : ''}${sup.name}`}</option>)}
            </SmartNativeSelect>
            {form.vendor_is_prospect && (
              <Input className="mt-1.5" value={form.vendor} placeholder="Nama calon supplier"
                onChange={(e) => setForm({ ...form, vendor: e.target.value })} data-testid="material-vendor-prospect" />
            )}
          </Isian>
          <Isian label="Harga per satuan (Rp)" htmlFor="mat-harga">
            <MoneyInput id="mat-harga" decimals={2} value={form.price_per_unit}
              onChange={(e) => setForm({ ...form, price_per_unit: parseFloat(e.target.value) || 0 })}
              data-testid="material-price-input" />
          </Isian>
          <Isian label="Satuan harga">
            <RnDUnitSelect value={form.price_unit} onChange={(e) => setForm({ ...form, price_unit: e.target.value })}
              testId="material-price-unit" />
          </Isian>
          <Isian label="Minimal order" htmlFor="mat-moq">
            <Input id="mat-moq" type="number" inputMode="decimal" value={form.min_order_qty}
              onChange={(e) => setForm({ ...form, min_order_qty: parseFloat(e.target.value) })} />
          </Isian>
        </div>
        {/* Warna bahan — dari MASTER warna yang sama dengan produksi/gudang. Baris kain & BOM Tech Pack nanti
            hanya bisa memilih warna yang memang tersedia untuk bahan ini. */}
        <Isian label="Warna yang tersedia untuk bahan ini" petunjuk="Mis. Fleece → Navy / Hitam / Abu — dari master warna.">
          <ColorMultiSelect colors={colorOpts} addColor={addColor} value={form.colors || []}
            onChange={(v) => setForm({ ...form, colors: v })} testId="material-colors" label="Tambah warna bahan" />
        </Isian>
      </FormPopup>
    </PageLayout>
  );
}

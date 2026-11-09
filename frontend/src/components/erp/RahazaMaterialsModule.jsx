/**
 * Master bahan & aksesoris (Portal Gudang › Master Item › tab "Bahan & aksesoris").
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout (di dalam hub judulnya tersembunyi → tidak ada lagi kepala
 * ganda "Master Item" + "Master Material"), penyaring satu baris (cari 16 rem, jenis, pil "Stok menipis"),
 * tabel → kartu ringkas di HP, unduh Excel/CSV semua baris hasil saringan, form = FormPopup panjang,
 * nonaktifkan lewat confirmDialog. Field, validasi, dan panggilan API tidak berubah.
 *
 * Angka: dulu spanduk "n material di bawah ambang" menghitung baris HALAMAN yang tampil saja (dan selalu 0 di
 * mode biasa karena barisnya tidak membawa tanda rendah). Kini jumlah di pil = `pagination.total` dari
 * /api/rahaza/materials?low_stock=true (definisi rendah satu sumber: core/stock_thresholds).
 */
import { useState, useEffect, useCallback } from 'react';
import { Plus, Pencil, Ban, Trash2, AlertTriangle, Search, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { MoneyInput } from '@/components/ui/money-input';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatusBadge } from './moduleAtoms';
import PaginationBar from './PaginationBar';
import ImportExportToolbar from './ImportExportToolbar';
import { CATEGORY_OPTIONS, categoryToStoredType, typeToCategory, isKgLike } from '@/lib/itemTaxonomy';
import UomEditor from './UomEditor';
import { resolveUoms, sanitizeUoms, purchaseUomOf, issueUomOf, displayUomOf, MATERIAL_UNITS } from '@/lib/uom';
import { readField, FIELD } from '@/lib/materialFields';  // FASE 6.6-B
import { hapusMaster } from '@/lib/hapusMaster';

// Tampilan per 3 kategori bisnis (Bahan/Aksesoris/Produk jadi). Semua tipe lama dipetakan ke kategori yang sama.
const JENIS_LABEL = {
  yarn: 'Bahan', fabric: 'Bahan', kain: 'Bahan', interlining: 'Bahan',
  accessory: 'Aksesoris', packaging: 'Aksesoris', fg: 'Produk jadi', other: 'Lainnya',
};
const jenisLabel = (t) => JENIS_LABEL[t] || 'Lainnya';

const FORM_KOSONG = {
  code: '', name: '', type: 'fabric', unit: 'kg', category: '', category_name: '', composition: '', color: '', notes: '',
  min_stock: 0, min_stock_qty: '', min_stock_percentage: '', reorder_point: '', active: true,
  unit_cost: 0, gsm: '', width_cm: '',
  // Satuan berjenjang (SSOT: lib/uom.js). `pack_*` tetap ada sebagai cermin supaya dokumen & konsumen lama tidak pecah.
  uoms: [], purchase_uom: '', issue_uom: '', display_uom: '',
  pack_unit: 'pack', pack_size: 1, display_in_packs: false,
};

const minStokTeks = (r) => {
  if (r.min_stock_qty) return `${Number(r.min_stock_qty).toLocaleString('id-ID')} ${r.unit || ''}`.trim();
  if (r.min_stock) return Number(r.min_stock).toLocaleString('id-ID');
  return '';
};

export default function RahazaMaterialsModule({ token }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [filterType, setFilterType] = useState('');
  const [filterLowStock, setFilterLowStock] = useState(false);
  const [search, setSearch] = useState('');
  const [cari, setCari] = useState('');
  const [form, setForm] = useState(FORM_KOSONG);
  const [categories, setCategories] = useState([]);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState('');
  const [jumlah, setJumlah] = useState({ semua: null, menipis: null });

  // Pagination
  const [page, setPage] = useState(1);
  const [pagination, setPagination] = useState(null);

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  // Ketikan pencarian diteruskan setelah jeda singkat (dulu tiap huruf memicu permintaan).
  useEffect(() => {
    const t = setTimeout(() => setSearch(cari.trim()), 300);
    return () => clearTimeout(t);
  }, [cari]);

  const paramsDasar = useCallback(() => {
    const params = new URLSearchParams();
    if (filterType) params.set('type', filterType);
    else params.set('exclude_type', 'fg'); // tab "Bahan & aksesoris" tidak menampilkan Produk jadi (FG punya tab sendiri)
    if (search) params.set('search', search);
    return params;
  }, [filterType, search]);

  const fetchRows = useCallback(async (targetPage = 1) => {
    setLoading(true);
    try {
      const params = paramsDasar();
      params.set('page', targetPage);
      params.set('limit', 50);
      if (filterLowStock) params.set('low_stock', 'true');
      const r = await fetch(`/api/rahaza/materials?${params}`, { headers });
      if (r.ok) {
        const data = await r.json();
        if (data && data.items && data.pagination) {
          setRows(data.items);
          setPagination(data.pagination);
        } else {
          setRows(Array.isArray(data) ? data : []);
          setPagination(null);
        }
      }
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, paramsDasar, filterLowStock]);

  // Jumlah untuk pil penyaring: total semua & total stok menipis (sesuai jenis + pencarian).
  const fetchJumlah = useCallback(async () => {
    const hitung = async (low) => {
      const p = paramsDasar();
      p.set('page', 1); p.set('limit', 1);
      if (low) p.set('low_stock', 'true');
      try {
        const r = await fetch(`/api/rahaza/materials?${p}`, { headers });
        if (!r.ok) return null;
        const d = await r.json();
        return d?.pagination?.total ?? null;
      } catch { return null; }
    };
    const [semua, menipis] = await Promise.all([hitung(false), hitung(true)]);
    setJumlah({ semua, menipis });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, paramsDasar]);

  useEffect(() => { setPage(1); fetchRows(1); }, [filterType, filterLowStock, search]); // eslint-disable-line
  useEffect(() => { fetchRows(page); }, [page]); // eslint-disable-line
  useEffect(() => { fetchJumlah(); }, [fetchJumlah]);
  useEffect(() => {
    (async () => {
      try {
        const r = await fetch('/api/rahaza/material-categories', { headers });
        if (r.ok) setCategories(await r.json());
      } catch { /* ignore */ }
    })();
  }, []); // eslint-disable-line

  const muatUlang = () => { fetchRows(page); fetchJumlah(); };

  // Unduh: SEMUA baris hasil saringan (bukan hanya halaman yang tampil) — loop halaman API yang sama.
  const ambilSemua = async () => {
    const semua = [];
    for (let pg = 1; pg <= 200; pg += 1) {
      const p = paramsDasar();
      p.set('page', pg); p.set('limit', 200);
      if (filterLowStock) p.set('low_stock', 'true');
      const r = await fetch(`/api/rahaza/materials?${p}`, { headers });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      const items = Array.isArray(d) ? d : (d.items || []);
      semua.push(...items);
      if (Array.isArray(d) || !d.pagination || pg >= d.pagination.total_pages) break;
    }
    return semua;
  };

  const openCreate = () => {
    setEditing(null);
    setForm(FORM_KOSONG);
    setFormError(''); setModalOpen(true);
  };
  const openEdit = (r) => {
    setEditing(r);
    setForm({ ...r, composition: readField(r, FIELD.composition), min_stock_qty: r.min_stock_qty || '', min_stock_percentage: r.min_stock_percentage || '', reorder_point: r.reorder_point || '', unit_cost: r.unit_cost || 0,
      gsm: r.gsm ?? '', width_cm: r.width_cm ?? '',
      uoms: resolveUoms(r), purchase_uom: purchaseUomOf(r), issue_uom: issueUomOf(r), display_uom: displayUomOf(r),
      pack_unit: r.pack_unit || 'pack', pack_size: r.pack_size || 1, display_in_packs: r.display_in_packs || false });
    setFormError(''); setModalOpen(true);
  };
  const save = async () => {
    setSaving(true); setFormError('');
    try {
      if (!form.code || !form.name) throw new Error('Kode & nama wajib diisi.');
      const url = editing ? `/api/rahaza/materials/${editing.id}` : '/api/rahaza/materials';
      const method = editing ? 'PUT' : 'POST';
      const payload = {
        ...form,
        min_stock: Number(form.min_stock) || 0,
        min_stock_qty: form.min_stock_qty !== '' ? Number(form.min_stock_qty) : null,
        min_stock_percentage: form.min_stock_percentage !== '' ? Number(form.min_stock_percentage) : null,
        reorder_point: form.reorder_point !== '' ? Number(form.reorder_point) : 0,
        // Harga hanya dikirim saat MEMBUAT (harga awal). Saat mengedit, harga
        // tidak boleh datang dari layar master — ia lahir dari harga pembelian.
        ...(editing ? {} : { unit_cost: Number(form.unit_cost) || 0 }),
        gsm: form.gsm !== '' && form.gsm != null ? Number(form.gsm) : null,
        width_cm: form.width_cm !== '' && form.width_cm != null ? Number(form.width_cm) : null,
        // Satuan: kirim daftar UOM yang sudah dibersihkan. Backend (core/uom)
        // memvalidasi ulang dan menulis cermin pack_unit/pack_size sendiri.
        uoms: sanitizeUoms(form.uoms, form.unit),
      };
      if (editing) delete payload.unit_cost;   // harga tidak diedit dari master
      const res = await fetch(url, { method, headers, body: JSON.stringify(payload) });
      if (!res.ok) {
        const STATUS_MSG = { 400: 'Data tidak valid.', 403: 'Tidak ada akses.', 409: 'Kode sudah terpakai.' };
        throw new Error(STATUS_MSG[res.status] || `Gagal simpan (HTTP ${res.status})`);
      }
      setModalOpen(false); fetchRows(); fetchJumlah();
    } catch (e) { setFormError(e.message); }
    finally { setSaving(false); }
  };
  const remove = async (r) => {
    const ok = await confirmDialog({
      title: `Nonaktifkan material ${r.code}?`,
      body: `"${r.name}" tidak lagi muncul di daftar dan pilihan material.`,
      confirmLabel: 'Nonaktifkan', danger: true,
    });
    if (!ok) return;
    const res = await fetch(`/api/rahaza/materials/${r.id}`, { method: 'DELETE', headers });
    if (res.ok) toast.success(`Material ${r.code} dinonaktifkan.`);
    else toast.error(`Gagal menonaktifkan (HTTP ${res.status}).`);
    fetchRows(); fetchJumlah();
  };
  // 10 Nov 2026 (permintaan owner): Hapus sungguhan. Server menolak (409) bila material sudah dipakai stok, BOM,
  // atau dokumen pengadaan/gudang → dialog kedua menawarkan Nonaktifkan (lib/hapusMaster).
  const deleteReq = async (r, hard) => {
    const res = await fetch(`/api/rahaza/materials/${r.id}${hard ? '?hard=true' : ''}`, { method: 'DELETE', headers });
    if (!res.ok) {
      let msg = `Gagal (HTTP ${res.status})`;
      try { const d = await res.clone().json(); if (d && typeof d.detail === 'string') msg = d.detail; } catch { /* body tak terbaca */ }
      const e = new Error(msg); e.status = res.status; throw e;
    }
  };
  const hapus = async (r) => {
    const hasil = await hapusMaster({ jenis: 'material', nama: r.name || r.code,
      hapus: () => deleteReq(r, true), nonaktifkan: r.active ? () => deleteReq(r, false) : null });
    if (hasil) { fetchRows(page); fetchJumlah(); }
  };

  const kolom = [
    { kunci: 'code', label: 'Kode', hp: 'judul', isi: (r) => {
      const isLow = r.is_low_stock || r.below_min;
      return (
        <span className="inline-flex items-center gap-1.5 tabular-nums" data-testid={`mat-row-${r.code}`}>
          {r.code}
          {isLow && <AlertTriangle className="h-3.5 w-3.5 text-[hsl(var(--warning-text))]" aria-label="Stok menipis"
            title={r.low_stock_reason || 'Stok menipis'} data-testid={`mat-low-badge-${r.code}`} />}
        </span>
      );
    } },
    { kunci: 'hp-ket', label: '', hp: 'keterangan', lebar: 'hidden', isi: (r) => [r.name, jenisLabel(r.type), r.unit].filter(Boolean).join(' · ') },
    { kunci: 'name', label: 'Nama', hp: false, isi: (r) => <span className="text-foreground">{r.name}</span> },
    { kunci: 'type', label: 'Jenis', hp: false, isi: (r) => jenisLabel(r.type) },
    { kunci: 'unit', label: 'Satuan', hp: false, isi: (r) => <span className="text-muted-foreground">{r.unit}</span> },
    { kunci: 'min', label: 'Min stok', hp: false, rata: 'kanan', isi: (r) => (
      <span className="tabular-nums text-muted-foreground">
        {minStokTeks(r) || '—'}
        {r.min_stock_percentage ? <span className="ml-1 text-xs">({r.min_stock_percentage}%)</span> : null}
      </span>
    ) },
    { kunci: 'color', label: 'Warna / komposisi', hp: false, isi: (r) => <span className="text-muted-foreground">{r.color || readField(r, FIELD.composition) || '—'}</span> },
    { kunci: 'active', label: 'Status', hp: false, isi: (r) => (r.active
      ? <StatusBadge status="aktif" label="Aktif" tone="success" />
      : <StatusBadge status="nonaktif" label="Nonaktif" tone="muted" />) },
    { kunci: 'aksi', label: 'Aksi', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <div className="inline-flex items-center gap-1">
        <Button variant="ghost" size="icon-sm" onClick={() => openEdit(r)} title="Ubah" aria-label={`Ubah ${r.code}`}
          data-testid={`mat-edit-${r.code}`}><Pencil /></Button>
        {r.active && (
          <Button variant="ghost" size="icon-sm" onClick={() => remove(r)} title="Nonaktifkan" aria-label={`Nonaktifkan ${r.code}`}
            data-testid={`mat-deactivate-${r.code}`}><Ban /></Button>
        )}
        <Button variant="ghost" size="icon-sm" onClick={() => hapus(r)} title="Hapus" aria-label={`Hapus ${r.code}`}
          data-testid={`mat-delete-${r.code}`}><Trash2 /></Button>
      </div>
    ) },
  ];

  const opsiSaring = [
    { key: '', label: 'Semua', count: jumlah.semua == null ? undefined : Number(jumlah.semua).toLocaleString('id-ID') },
    { key: 'menipis', label: 'Stok menipis', count: jumlah.menipis == null ? undefined : Number(jumlah.menipis).toLocaleString('id-ID') },
  ];

  return (
    <PageLayout testId="rahaza-materials-page" title="Bahan & aksesoris"
      subtitle="Master bahan dan aksesoris yang dipakai di stok, pengeluaran material, dan WO."
      actions={<>
        <ImportExportToolbar collectionKey="materials" label="Bahan / Material" onImported={muatUlang} size="default" caption="master" />
        <Button onClick={openCreate} data-testid="mat-add-btn"><Plus />Material baru</Button>
      </>}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={cari} onChange={(e) => setCari(e.target.value)} placeholder="Cari kode atau nama"
            className="pl-8" data-testid="mat-search" />
        </div>
        <SmartNativeSelect value={filterType} onChange={(e) => setFilterType(e.target.value)} className="w-full" wrapperClassName="w-full sm:w-48"
          searchable={false} aria-label="Jenis" data-testid="mat-filter-type">
          <option value="">Bahan &amp; aksesoris</option>
          <option value="bahan">Bahan</option>
          <option value="aksesoris">Aksesoris</option>
        </SmartNativeSelect>
        <FilterChips options={opsiSaring} value={filterLowStock ? 'menipis' : ''} hideWhenEmpty={false}
          onChange={(k) => setFilterLowStock(k === 'menipis')} testId="mat-filter-low-stock" ariaLabel="Penyaring stok" className="w-full sm:w-auto" />
        <div className="ml-auto flex shrink-0 items-center gap-2">
        <TombolUnduh namaBerkas={filterLowStock ? 'bahan-aksesoris-stok-menipis' : 'bahan-aksesoris'} namaLembar="Bahan & aksesoris"
          baris={rows} ambilSemua={ambilSemua} testId="mat-unduh"
          kolom={[
            { label: 'Kode', nilai: (r) => r.code },
            { label: 'Nama', nilai: (r) => r.name },
            { label: 'Jenis', nilai: (r) => jenisLabel(r.type) },
            { label: 'Kategori', nilai: (r) => r.category_name || '' },
            { label: 'Satuan', nilai: (r) => r.unit },
            { label: 'Min stok', nilai: (r) => (r.min_stock_qty ? Number(r.min_stock_qty) : (r.min_stock ? Number(r.min_stock) : '')) },
            { label: 'Titik pesan ulang', nilai: (r) => (r.reorder_point ? Number(r.reorder_point) : '') },
            { label: 'Warna / komposisi', nilai: (r) => r.color || readField(r, FIELD.composition) || '' },
            { label: 'Status', nilai: (r) => (r.active ? 'Aktif' : 'Nonaktif') },
          ]} />
        <Button variant="outline" size="icon" onClick={muatUlang} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
        </div>
      </>}
      footer={pagination && pagination.total_pages > 1 ? <PaginationBar pagination={pagination} onPageChange={setPage} /> : null}>
      {loading && rows.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat material…</p>
      ) : (
        <TabelData kolom={kolom} baris={rows} testId="mat-table"
          kosong={<EmptyState title={filterLowStock ? 'Tidak ada material yang stoknya menipis' : 'Belum ada material'}
            description={filterLowStock ? 'Semua material berambang masih di atas ambangnya.' : 'Klik "Material baru" untuk menambah.'} />} />
      )}

      <FormPopup open={modalOpen} onClose={() => setModalOpen(false)} ukuran="panjang" onSimpan={save} menyimpan={saving}
        judul={editing ? `Ubah ${editing.code}` : 'Material baru'} galat={formError} testId="mat-form"
        keterangan="Kode, jenis, satuan, dan ambang stok bahan atau aksesoris."
        labelSimpan={editing ? 'Simpan perubahan' : 'Simpan'}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Kode" wajib htmlFor="mat-kode">
            <Input id="mat-kode" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })}
              placeholder="BHN-KTN30S" data-testid="mat-field-code" />
          </Isian>
          <Isian label="Jenis" wajib>
            <SmartNativeSelect value={typeToCategory(form.type)} searchable={false}
              onChange={(e) => { const st = categoryToStoredType(e.target.value); setForm({ ...form, type: st, unit: isKgLike(st) ? 'kg' : 'pcs' }); }}
              className="w-full" data-testid="mat-field-type">
              {CATEGORY_OPTIONS.filter((o) => o.value !== 'fg').map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </SmartNativeSelect>
          </Isian>
        </div>
        <Isian label="Kategori material">
          <SmartNativeSelect value={form.category} className="w-full" data-testid="mat-field-category"
            onChange={(e) => {
              const cat = categories.find((c) => c.code === e.target.value);
              setForm({ ...form, category: e.target.value, category_name: cat ? cat.name : '' });
            }}>
            <option value="">Pilih kategori</option>
            {categories.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Nama" wajib htmlFor="mat-nama">
          <Input id="mat-nama" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="Kain Katun 30s" data-testid="mat-field-name" />
        </Isian>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Satuan">
            <SmartNativeSelect value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} className="w-full"
              data-testid="mat-field-unit">
              {MATERIAL_UNITS.map((u) => <option key={u} value={u}>{u}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Min stok (lama)" htmlFor="mat-min-lama" petunjuk="Isian lama; ambang yang dipakai alert ada di bawah.">
            <Input id="mat-min-lama" type="number" step="0.1" value={form.min_stock} onChange={(e) => setForm({ ...form, min_stock: e.target.value })} />
          </Isian>
        </div>

        {/* HARGA SATUAN (HPP) — sejak 2026-08-21 harganya LAHIR DARI PEMBELIAN (PO → Penerimaan Barang,
            rata-rata bergerak), bukan ketikan master. Saat membuat barang baru masih boleh diisi sebagai
            HARGA AWAL karena belum ada pembeliannya. */}
        {editing ? (
          <Isian label="Harga satuan / HPP"
            petunjuk="Harga tidak diketik di sini. Ia terbentuk otomatis dari harga pembelian di PO saat barang diterima. Koreksi manual (bila salah harga) lewat Valuasi HPP agar ada jejak audit.">
            <div data-testid="mat-cost-derived">
              <p className="text-base font-semibold tabular-nums text-foreground" data-testid="mat-cost-value">
                Rp {Number(form.unit_cost || 0).toLocaleString('id-ID')}
                <span className="text-sm font-normal text-muted-foreground"> / {form.unit}</span>
              </p>
              <p className="text-xs text-muted-foreground">
                Sumber: {
                  form.cost_method === 'wac' ? 'rata-rata pembelian (PO → penerimaan)'
                    : form.cost_method === 'manual' ? 'koreksi manual (Valuasi HPP)'
                      : form.cost_method === 'opening' ? 'harga awal saat barang didaftarkan'
                        : 'belum ada pembelian bernilai'
                }
                {form.last_receipt_unit_cost > 0 && (
                  <> · harga beli terakhir Rp {Number(form.last_receipt_unit_cost).toLocaleString('id-ID')}</>
                )}
              </p>
            </div>
          </Isian>
        ) : (
          <Isian label="Harga awal (Rp), opsional"
            petunjuk="Hanya untuk barang yang sudah ada di gudang sebelum sistem ini. Setelah ada pembelian (PO → penerimaan), harga otomatis mengikuti harga beli.">
            <MoneyInput value={form.unit_cost} onChange={(e) => setForm({ ...form, unit_cost: e.target.value })}
              placeholder="Cth: 25.000" data-testid="mat-field-unit-cost" />
          </Isian>
        )}

        {/* 2026-08-02 · Kain: gramasi & lebar → konversi meter ⇄ kg */}
        {['fabric', 'kain', 'yarn', 'interlining'].includes(form.type) && (
          <div className="space-y-3 border-t border-[var(--glass-border)] pt-4">
            <p className="text-sm font-medium text-foreground">Data kain: konversi meter ⇄ kg</p>
            <div className="grid gap-4 sm:grid-cols-2">
              <Isian label="Gramasi / GSM (g/m²)" htmlFor="mat-gsm">
                <Input id="mat-gsm" type="number" step="1" min="0" value={form.gsm ?? ''}
                  onChange={(e) => setForm({ ...form, gsm: e.target.value })} placeholder="Cth: 240" data-testid="mat-field-gsm" />
              </Isian>
              <Isian label="Lebar kain (cm)" htmlFor="mat-lebar">
                <Input id="mat-lebar" type="number" step="0.5" min="0" value={form.width_cm ?? ''}
                  onChange={(e) => setForm({ ...form, width_cm: e.target.value })} placeholder="Cth: 160" data-testid="mat-field-width" />
              </Isian>
            </div>
            <p className="text-xs text-muted-foreground" data-testid="mat-fabric-conv-hint">
              {Number(form.gsm) > 0 && Number(form.width_cm) > 0 ? (
                <>1 meter ≈ <strong>{((Number(form.gsm) * (Number(form.width_cm) / 100)) / 1000).toFixed(4)} kg</strong>
                  {' '}· 1 kg ≈ <strong>{(1 / ((Number(form.gsm) * (Number(form.width_cm) / 100)) / 1000)).toFixed(3)} meter</strong>
                  {' '}— dipakai BOM, RnD/HPP &amp; costing untuk mengubah meter ke kg.</>
              ) : (
                <>Isi keduanya agar sistem bisa mengubah pemakaian <strong>meter</strong> menjadi <strong>kg</strong> (kain dibeli per kg).</>
              )}
            </p>
          </div>
        )}

        {/* Satuan & kemasan berjenjang (maks 3 tingkat) — SSOT lib/uom.js */}
        <UomEditor
          baseUnit={form.unit}
          uoms={form.uoms}
          purchaseUom={form.purchase_uom}
          issueUom={form.issue_uom}
          displayUom={form.display_uom}
          resetKey={editing?.id || 'new'}
          materialId={editing?.id || null}
          token={token}
          onRebased={() => { setModalOpen(false); fetchRows(); }}
          onChange={(patch) => setForm((f) => ({ ...f, ...patch }))}
        />

        {/* Sprint 3.4: ambang stok menipis per material */}
        <div className="space-y-3 border-t border-[var(--glass-border)] pt-4">
          <p className="text-sm font-medium text-foreground">Ambang stok menipis</p>
          <div className="grid gap-4 sm:grid-cols-3">
            <Isian label={`Min qty tetap (${form.unit})`} htmlFor="mat-min-qty">
              <Input id="mat-min-qty" type="number" step="0.01" min="0" value={form.min_stock_qty}
                onChange={(e) => setForm({ ...form, min_stock_qty: e.target.value })} placeholder="Cth: 50" data-testid="mat-field-min-qty" />
            </Isian>
            <Isian label={`Titik pesan ulang (${form.unit})`} htmlFor="mat-rp">
              <Input id="mat-rp" type="number" step="0.01" min="0" value={form.reorder_point}
                onChange={(e) => setForm({ ...form, reorder_point: e.target.value })} placeholder="Cth: 80" data-testid="mat-field-reorder-point" />
            </Isian>
            <Isian label="Min % dari stok tertinggi" htmlFor="mat-min-pct">
              <Input id="mat-min-pct" type="number" step="1" min="0" max="100" value={form.min_stock_percentage}
                onChange={(e) => setForm({ ...form, min_stock_percentage: e.target.value })} placeholder="Cth: 20" data-testid="mat-field-min-pct" />
            </Isian>
          </div>
          <p className="text-xs text-muted-foreground">
            Min qty = stok kritis (di bawah ini → peringatan merah). Titik pesan ulang = saatnya pesan lagi (peringatan kuning).
            Untuk mengisi banyak material sekaligus beserta usulannya, pakai tab Ambang stok.
          </p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Jenis / komposisi" htmlFor="mat-komposisi">
            <Input id="mat-komposisi" value={form.composition || ''} onChange={(e) => setForm({ ...form, composition: e.target.value })}
              placeholder="Acrylic 100%" data-testid="mat-field-composition" />
          </Isian>
          <Isian label="Warna" htmlFor="mat-warna">
            <Input id="mat-warna" value={form.color || ''} onChange={(e) => setForm({ ...form, color: e.target.value })} placeholder="Navy" />
          </Isian>
        </div>
        <Isian label="Catatan" htmlFor="mat-catatan">
          <Input id="mat-catatan" value={form.notes || ''} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="Opsional" />
        </Isian>
      </FormPopup>
    </PageLayout>
  );
}

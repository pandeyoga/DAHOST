/**
 * SupplierMasterModule — MASTER SUPPLIER (SSOT Pengadaan)
 *
 * Sebelum modul ini, PO memakai `vendor_name` TEKS BEBAS sehingga:
 *   · satu supplier dengan dua ejaan memecah penilaian supplier,
 *   · termin bayar / rekening / NPWP harus diketik ulang tiap PO,
 *   · tidak ada daftar harga sehingga harga PO ditebak manual.
 *
 * Modul ini menyediakan: CRUD lengkap, kontak/PIC ganda, rekening bank ganda,
 * kategori barang, lead time, daftar harga per SATUAN BELI (dengan konversi
 * otomatis ke satuan dasar), scorecard, dan tarik-data supplier dari dokumen lama.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, penyaring satu baris (dulu cari & dua pilihan
 * selebar layar, bertumpuk tiga baris), daftar = TabelData (kartu ringkas di HP), aksi baris ≤ 2 + "Lainnya",
 * form = FormPopup, detail = DetailPopup, tambah harga = FormPopup, konfirmasi = confirmDialog.
 * Unduh tabel utama tetap lewat Unduh/Impor Data Transfer (keputusan T4 6 Nov: satu pintu ekspor).
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Ban, Building2, CheckCircle2, Contact, Eye, Landmark, MoreHorizontal, Pencil, Plus, RefreshCw,
  Search, Star, Trash2, Truck,
} from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { MoneyInput } from '@/components/ui/money-input';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PaginationLite from '@/components/ui/pagination-lite';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { materialOptionLabel } from '@/lib/materialFields';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';
import ImportExportToolbar from '../ImportExportToolbar';
import { toast } from 'sonner';
import {
  CATEGORY_LABEL, EP, PAYMENT_TERM_LABEL, apiDelete, apiGet, apiPost, apiPut,
  fmtDate, fmtNum, fmtRp,
} from './procApi';

const EMPTY_FORM = {
  name: '', code: '', npwp: '', tax_name: '', tax_type: 'ppn',
  address: '', city: '', province: '', postal_code: '', country: 'Indonesia',
  phone: '', email: '', website: '',
  payment_terms: 'net30', currency: 'IDR',
  lead_time_days: 0, min_order_value: 0,
  categories: [], material_types: [],
  contacts: [], bank_accounts: [],
  rating_manual: '', notes: '', is_active: true,
};

// Status PO (kode server) → label Indonesia untuk rekap per supplier.
const PO_STATUS_LABEL = {
  draft: 'Draf', pending_approval: 'Menunggu persetujuan', approved: 'Disetujui', sent: 'Terkirim',
  partially_received: 'Diterima sebagian', fully_received: 'Diterima penuh', received: 'Diterima',
  completed: 'Selesai', closed: 'Ditutup', rejected: 'Ditolak', cancelled: 'Dibatalkan',
};
const labelStatusPO = (s) => PO_STATUS_LABEL[s]
  || String(s || '-').replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());

const GRADE_TONE = { 'A+': 'success', A: 'success', B: 'info', C: 'warning', D: 'danger' };
function GradeBadge({ grade }) {
  if (!grade || grade === '-') return <span className="text-sm text-muted-foreground">—</span>;
  return <StatusBadge status={`grade-${grade}`} label={`Grade ${grade}`} tone={GRADE_TONE[grade] || 'muted'} />;
}

function ActiveBadge({ active }) {
  return active !== false
    ? <StatusBadge status="aktif" label="Aktif" tone="success" />
    : <StatusBadge status="nonaktif" label="Nonaktif" tone="muted" />;
}

const kategoriTeks = (cats) => (cats || []).map((c) => CATEGORY_LABEL[c] || c).join(', ');

// ── Form supplier (popup panjang) ────────────────────────────────────────────
function SupplierForm({ token, meta, initial, onClose, onSaved }) {
  const isEdit = !!initial?.id;
  const [f, setF] = useState(() => ({ ...EMPTY_FORM, ...(initial || {}) }));
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));
  const toggleCat = (c) => setF((p) => ({
    ...p,
    categories: p.categories?.includes(c)
      ? p.categories.filter((x) => x !== c)
      : [...(p.categories || []), c],
  }));

  const addContact = () => setF((p) => ({
    ...p,
    contacts: [...(p.contacts || []), { name: '', position: '', phone: '', email: '', is_primary: !(p.contacts || []).length }],
  }));
  const setContact = (i, k, v) => setF((p) => ({
    ...p, contacts: p.contacts.map((c, idx) => (idx === i ? { ...c, [k]: v } : c)),
  }));
  const rmContact = (i) => setF((p) => ({ ...p, contacts: p.contacts.filter((_, idx) => idx !== i) }));

  const addBank = () => setF((p) => ({
    ...p,
    bank_accounts: [...(p.bank_accounts || []), { bank_name: '', account_number: '', account_holder: '', branch: '', is_primary: !(p.bank_accounts || []).length }],
  }));
  const setBank = (i, k, v) => setF((p) => ({
    ...p, bank_accounts: p.bank_accounts.map((b, idx) => (idx === i ? { ...b, [k]: v } : b)),
  }));
  const rmBank = (i) => setF((p) => ({ ...p, bank_accounts: p.bank_accounts.filter((_, idx) => idx !== i) }));

  const save = async () => {
    setErr('');
    if (!f.name?.trim()) { setErr('Nama supplier wajib diisi.'); return; }
    setSaving(true);
    try {
      const payload = {
        ...f,
        lead_time_days: Number(f.lead_time_days || 0),
        min_order_value: Number(f.min_order_value || 0),
        rating_manual: f.rating_manual === '' ? null : Number(f.rating_manual),
      };
      if (isEdit) delete payload.code;
      const out = isEdit
        ? await apiPut(token, EP.supplier(initial.id), payload)
        : await apiPost(token, EP.suppliers(), payload);
      toast.success(isEdit ? 'Supplier disimpan' : `Supplier ${out?.code || ''} dibuat`);
      onSaved?.(out);
      onClose();
    } catch (e) {
      setErr(e.message);
      toast.error(e.message);
    } finally { setSaving(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" onSimpan={save} menyimpan={saving} galat={err}
      judul={isEdit ? `Ubah supplier ${initial.code}` : 'Tambah supplier'}
      keterangan="Data ini dipakai otomatis di PO, penerimaan, dan faktur supplier."
      labelSimpan={isEdit ? 'Simpan perubahan' : 'Simpan supplier'} testId="supplier-form">
      <Isian label="Nama supplier" wajib htmlFor="sup-nama">
        <Input id="sup-nama" value={f.name} onChange={(e) => set('name', e.target.value)}
          placeholder="PT Benang Jaya Abadi" data-testid="supplier-form-name" />
      </Isian>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Isian label="NPWP" htmlFor="sup-npwp">
          <Input id="sup-npwp" value={f.npwp} onChange={(e) => set('npwp', e.target.value)}
            placeholder="01.234.567.8-901.000" data-testid="supplier-form-npwp" />
        </Isian>
        <Isian label="Nama wajib pajak" htmlFor="sup-taxname">
          <Input id="sup-taxname" value={f.tax_name} onChange={(e) => set('tax_name', e.target.value)}
            placeholder="Sesuai NPWP" data-testid="supplier-form-taxname" />
        </Isian>
        <Isian label="Status pajak">
          <SmartNativeSelect value={f.tax_type} onChange={(e) => set('tax_type', e.target.value)}
            className="w-full" data-testid="supplier-form-taxtype">
            {(meta?.tax_types || [{ value: 'ppn', label: 'PKP (kena PPN)' }, { value: 'non_ppn', label: 'Non-PKP' }])
              .map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Termin bayar">
          <SmartNativeSelect value={f.payment_terms} onChange={(e) => set('payment_terms', e.target.value)}
            className="w-full" data-testid="supplier-form-terms">
            {(meta?.payment_terms || []).map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Mata uang">
          <SmartNativeSelect value={f.currency} onChange={(e) => set('currency', e.target.value)}
            className="w-full" data-testid="supplier-form-currency">
            {(meta?.currencies || ['IDR']).map((c) => <option key={c} value={c}>{c}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Lead time (hari)" htmlFor="sup-lead">
          <Input id="sup-lead" type="number" min="0" value={f.lead_time_days}
            onChange={(e) => set('lead_time_days', e.target.value)} data-testid="supplier-form-leadtime" />
        </Isian>
        <Isian label="Minimum order (Rp)" htmlFor="sup-minorder">
          <MoneyInput id="sup-minorder" value={f.min_order_value}
            onChange={(e) => set('min_order_value', e.target.value)} data-testid="supplier-form-minorder" />
        </Isian>
        <Isian label="Rating manual (1–5)" htmlFor="sup-rating">
          <Input id="sup-rating" type="number" min="1" max="5" value={f.rating_manual ?? ''}
            onChange={(e) => set('rating_manual', e.target.value)} data-testid="supplier-form-rating" />
        </Isian>
      </div>

      <Isian label="Kategori barang / jasa yang disuplai">
        <div className="flex flex-wrap gap-1.5">
          {(meta?.categories || Object.entries(CATEGORY_LABEL).map(([value, label]) => ({ value, label })))
            .map((c) => {
              const on = f.categories?.includes(c.value);
              return (
                <Button key={c.value} type="button" size="sm" variant={on ? 'default' : 'outline'} aria-pressed={on}
                  onClick={() => toggleCat(c.value)} data-testid={`supplier-form-cat-${c.value}`}>
                  {c.label}
                </Button>
              );
            })}
        </div>
      </Isian>

      <Isian label="Alamat" htmlFor="sup-alamat">
        <Textarea id="sup-alamat" value={f.address} onChange={(e) => set('address', e.target.value)} rows={2}
          placeholder="Jl. Industri Raya No. 12" data-testid="supplier-form-address" />
      </Isian>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Isian label="Kota" htmlFor="sup-kota">
          <Input id="sup-kota" value={f.city} onChange={(e) => set('city', e.target.value)} data-testid="supplier-form-city" />
        </Isian>
        <Isian label="Provinsi" htmlFor="sup-prov">
          <Input id="sup-prov" value={f.province} onChange={(e) => set('province', e.target.value)} />
        </Isian>
        <Isian label="Kode pos" htmlFor="sup-pos">
          <Input id="sup-pos" value={f.postal_code} onChange={(e) => set('postal_code', e.target.value)} />
        </Isian>
        <Isian label="Telepon" htmlFor="sup-telp">
          <Input id="sup-telp" value={f.phone} onChange={(e) => set('phone', e.target.value)}
            placeholder="022-1234567" data-testid="supplier-form-phone" />
        </Isian>
        <Isian label="Email" htmlFor="sup-email">
          <Input id="sup-email" type="email" value={f.email} onChange={(e) => set('email', e.target.value)}
            placeholder="sales@supplier.co.id" data-testid="supplier-form-email" />
        </Isian>
        <Isian label="Situs web" htmlFor="sup-web">
          <Input id="sup-web" value={f.website} onChange={(e) => set('website', e.target.value)} />
        </Isian>
      </div>

      {/* Kontak / PIC */}
      <div className="space-y-2 border-t border-[var(--glass-border)] pt-3">
        <div className="flex items-center justify-between gap-2">
          <p className="flex items-center gap-1.5 text-sm font-medium"><Contact className="h-4 w-4" /> Kontak / PIC</p>
          <Button type="button" size="sm" variant="outline" onClick={addContact} data-testid="supplier-form-add-contact">
            <Plus /> Tambah kontak
          </Button>
        </div>
        {!f.contacts?.length && <p className="text-sm text-muted-foreground">Kontak belum diisi — klik Tambah kontak.</p>}
        {(f.contacts || []).map((c, i) => (
          <div key={i} className="grid grid-cols-2 items-center gap-2 sm:grid-cols-12">
            <Input className="sm:col-span-3" placeholder="Nama" aria-label="Nama kontak" value={c.name}
              onChange={(e) => setContact(i, 'name', e.target.value)} data-testid={`supplier-contact-name-${i}`} />
            <Input className="sm:col-span-3" placeholder="Jabatan" aria-label="Jabatan" value={c.position}
              onChange={(e) => setContact(i, 'position', e.target.value)} />
            <Input className="sm:col-span-2" placeholder="Telepon" aria-label="Telepon kontak" value={c.phone}
              onChange={(e) => setContact(i, 'phone', e.target.value)} />
            <Input className="sm:col-span-3" placeholder="Email" aria-label="Email kontak" value={c.email}
              onChange={(e) => setContact(i, 'email', e.target.value)} />
            <Button type="button" variant="ghost" size="icon" className="justify-self-end sm:col-span-1"
              onClick={() => rmContact(i)} title="Hapus kontak" aria-label="Hapus kontak"
              data-testid={`supplier-contact-remove-${i}`}>
              <Trash2 className="text-[hsl(var(--danger-text))]" />
            </Button>
          </div>
        ))}
      </div>

      {/* Rekening bank */}
      <div className="space-y-2 border-t border-[var(--glass-border)] pt-3">
        <div className="flex items-center justify-between gap-2">
          <p className="flex items-center gap-1.5 text-sm font-medium"><Landmark className="h-4 w-4" /> Rekening bank</p>
          <Button type="button" size="sm" variant="outline" onClick={addBank} data-testid="supplier-form-add-bank">
            <Plus /> Tambah rekening
          </Button>
        </div>
        {!f.bank_accounts?.length && <p className="text-sm text-muted-foreground">Rekening belum diisi — klik Tambah rekening.</p>}
        {(f.bank_accounts || []).map((b, i) => (
          <div key={i} className="grid grid-cols-2 items-center gap-2 sm:grid-cols-12">
            <Input className="sm:col-span-3" placeholder="Bank" aria-label="Nama bank" value={b.bank_name}
              onChange={(e) => setBank(i, 'bank_name', e.target.value)} data-testid={`supplier-bank-name-${i}`} />
            <Input className="sm:col-span-3" placeholder="No. rekening" aria-label="Nomor rekening" value={b.account_number}
              onChange={(e) => setBank(i, 'account_number', e.target.value)} data-testid={`supplier-bank-account-${i}`} />
            <Input className="sm:col-span-3" placeholder="Nama pemilik" aria-label="Nama pemilik rekening" value={b.account_holder}
              onChange={(e) => setBank(i, 'account_holder', e.target.value)} />
            <Input className="sm:col-span-2" placeholder="Cabang" aria-label="Cabang" value={b.branch}
              onChange={(e) => setBank(i, 'branch', e.target.value)} />
            <Button type="button" variant="ghost" size="icon" className="justify-self-end sm:col-span-1"
              onClick={() => rmBank(i)} title="Hapus rekening" aria-label="Hapus rekening">
              <Trash2 className="text-[hsl(var(--danger-text))]" />
            </Button>
          </div>
        ))}
      </div>

      <Isian label="Catatan" htmlFor="sup-catatan">
        <Textarea id="sup-catatan" value={f.notes} onChange={(e) => set('notes', e.target.value)} rows={2}
          data-testid="supplier-form-notes" />
      </Isian>
    </FormPopup>
  );
}

// ── Tambah harga (popup pendek, dibuka dari detail supplier) ─────────────────
const KOSONG_HARGA = { material_id: '', uom: '', price: '', moq: '', lead_time_days: '', notes: '' };

function PriceForm({ token, supplierId, materials, onClose, onSaved }) {
  const [priceForm, setPriceForm] = useState(KOSONG_HARGA);
  const [uomOpts, setUomOpts] = useState(null);
  const [savingPrice, setSavingPrice] = useState(false);
  const [priceErr, setPriceErr] = useState('');

  // Ambil daftar satuan sah untuk material terpilih (server yang menentukan)
  useEffect(() => {
    if (!priceForm.material_id) { setUomOpts(null); return; }
    let alive = true;
    apiGet(token, EP.uomOptions(priceForm.material_id))
      .then((r) => {
        if (!alive) return;
        const o = (r?.options || {})[priceForm.material_id] || null;
        setUomOpts(o);
        setPriceForm((p) => ({ ...p, uom: p.uom || o?.base_unit || '' }));
      })
      .catch(() => setUomOpts(null));
    return () => { alive = false; };
  }, [token, priceForm.material_id]);

  const factor = useMemo(() => {
    if (!uomOpts) return 1;
    const row = (uomOpts.units || []).find((u) => u.unit === priceForm.uom);
    return row ? Number(row.factor_to_base) : 1;
  }, [uomOpts, priceForm.uom]);

  const addPrice = async () => {
    setPriceErr('');
    if (!priceForm.material_id) { setPriceErr('Pilih material dulu.'); return; }
    if (!(Number(priceForm.price) > 0)) { setPriceErr('Harga harus lebih dari 0.'); return; }
    setSavingPrice(true);
    try {
      await apiPost(token, EP.priceList(supplierId), {
        material_id: priceForm.material_id,
        uom: priceForm.uom || undefined,
        price: Number(priceForm.price),
        moq: Number(priceForm.moq || 0),
        lead_time_days: Number(priceForm.lead_time_days || 0),
        notes: priceForm.notes,
      });
      toast.success('Harga supplier disimpan');
      await onSaved?.();
      onClose();
    } catch (e) {
      setPriceErr(e.message);
      toast.error(e.message);
    } finally { setSavingPrice(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="pendek" onSimpan={addPrice} menyimpan={savingPrice} galat={priceErr}
      judul="Tambah harga" keterangan="Harga per satuan beli; sistem menghitung harga per satuan dasar."
      labelSimpan="Simpan harga" testId="price-form">
      <Isian label="Material" wajib>
        <SmartNativeSelect value={priceForm.material_id}
          onChange={(e) => setPriceForm((p) => ({ ...p, material_id: e.target.value, uom: '' }))}
          className="w-full" data-testid="price-form-material">
          <option value="">Pilih material</option>
          {materials.map((m) => <option key={m.id} value={m.id}>{materialOptionLabel(m)}</option>)}
        </SmartNativeSelect>
      </Isian>
      <div className="grid grid-cols-2 gap-4">
        <Isian label="Satuan beli">
          <SmartNativeSelect value={priceForm.uom}
            onChange={(e) => setPriceForm((p) => ({ ...p, uom: e.target.value }))}
            disabled={!uomOpts} className="w-full" data-testid="price-form-uom">
            {(uomOpts?.units || []).map((u) => (
              <option key={u.unit} value={u.unit}>{u.label || u.unit}</option>
            ))}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Harga per satuan" wajib htmlFor="price-harga">
          <MoneyInput id="price-harga" decimals={2} value={priceForm.price}
            onChange={(e) => setPriceForm((p) => ({ ...p, price: e.target.value }))}
            className="text-right" data-testid="price-form-price" />
        </Isian>
        <Isian label="Minimum order (MOQ)" htmlFor="price-moq">
          <Input id="price-moq" type="number" min="0" value={priceForm.moq}
            onChange={(e) => setPriceForm((p) => ({ ...p, moq: e.target.value }))}
            className="text-right" data-testid="price-form-moq" />
        </Isian>
        <Isian label="Lead time (hari)" htmlFor="price-lead">
          <Input id="price-lead" type="number" min="0" value={priceForm.lead_time_days}
            onChange={(e) => setPriceForm((p) => ({ ...p, lead_time_days: e.target.value }))}
            className="text-right" />
        </Isian>
      </div>
      {uomOpts && priceForm.uom && Number(priceForm.price) > 0 && (
        <p className="text-sm text-muted-foreground" data-testid="price-form-preview">
          1 {priceForm.uom} = {fmtNum(factor)} {uomOpts.base_unit}, jadi harga per satuan dasar{' '}
          <span className="font-semibold text-foreground">{fmtRp(Number(priceForm.price) / (factor || 1))}</span>{' '}
          / {uomOpts.base_unit}
        </p>
      )}
    </FormPopup>
  );
}

// ── Detail + daftar harga + scorecard (popup) ───────────────────────────────
function SupplierDetail({ token, supplierId, materials, onClose, onChanged, onEdit }) {
  const [sup, setSup] = useState(null);
  const [card, setCard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('info');
  const [priceOpen, setPriceOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, c] = await Promise.all([
        apiGet(token, EP.supplier(supplierId)),
        apiGet(token, EP.supplierScorecard(supplierId)).catch(() => null),
      ]);
      setSup(s);
      setCard(c);
    } catch (e) {
      toast.error(`Gagal memuat supplier: ${e.message}`);
    } finally { setLoading(false); }
  }, [token, supplierId]);

  useEffect(() => { load(); }, [load]);

  // 2026-11-07 (Tahap 5): konfirmasi aplikasi (dulu window.confirm)
  const delPrice = async (rowId) => {
    const ok = await confirmDialog({
      title: 'Hapus baris harga?', body: 'Baris harga ini dihapus dari daftar harga supplier.',
      confirmLabel: 'Hapus', danger: true,
    });
    if (!ok) return;
    try {
      await apiDelete(token, EP.priceRow(supplierId, rowId));
      toast.success('Baris harga dihapus');
      await load();
    } catch (e) { toast.error(e.message); }
  };

  if (loading && !sup) {
    return (
      <DetailPopup open onClose={onClose} judul="Memuat supplier…" testId="supplier-detail-memuat">
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat data supplier…</p>
      </DetailPopup>
    );
  }
  if (!sup) return null;

  const sc = card?.scorecard || {};
  const adaPeriksa = Number(sc.total_grns || 0) > 0;
  const priceList = sup.price_list || [];
  const poByStatus = Object.entries(card?.po_by_status || {});
  const TABS = [
    { key: 'info', label: 'Informasi' },
    { key: 'price', label: 'Daftar harga', count: priceList.length },
    { key: 'score', label: 'Penilaian' },
  ];

  return (
    <DetailPopup open onClose={onClose} judul={`${sup.code} — ${sup.name}`} testId="supplier-detail"
      status={<>
        <ActiveBadge active={sup.is_active} />
        {sup.source === 'migrated' && <StatusBadge status="migrated" label="Dari data lama" tone="warning" />}
      </>}
      aksi={onEdit && (
        <Button size="sm" variant="outline" onClick={() => onEdit(sup)} data-testid="supplier-detail-edit">
          <Pencil /> Ubah
        </Button>
      )}>
      <FilterChips options={TABS} value={tab} onChange={setTab} hideWhenEmpty={false} testId="supplier-tab" />

      {tab === 'info' && (
        <dl className="divide-y divide-[var(--glass-border)]">
          <BarisDetail label="Termin bayar">{PAYMENT_TERM_LABEL[sup.payment_terms] || sup.payment_terms} · {sup.currency}</BarisDetail>
          <BarisDetail label="Kategori">{kategoriTeks(sup.categories) || '—'}</BarisDetail>
          <BarisDetail label="Alamat">{[sup.address, sup.city, sup.province, sup.postal_code].filter(Boolean).join(', ') || '—'}</BarisDetail>
          <BarisDetail label="NPWP">{sup.npwp || '—'}{sup.tax_name ? ` · ${sup.tax_name}` : ''}</BarisDetail>
          <BarisDetail label="Telepon / email">{sup.phone || '—'} · {sup.email || '—'}</BarisDetail>
          <BarisDetail label="Lead time / minimum order">{sup.lead_time_days || 0} hari · {fmtRp(sup.min_order_value)}</BarisDetail>
          <BarisDetail label="Kontak">
            {(sup.contacts || []).length === 0 ? '—' : (
              <ul className="space-y-1">
                {sup.contacts.map((c) => (
                  <li key={c.id || c.name}>
                    <span className="font-medium">{c.name}</span>
                    {c.position && <span className="text-muted-foreground"> · {c.position}</span>}
                    {c.phone && <span className="text-muted-foreground"> · {c.phone}</span>}
                    {c.is_primary && <span className="ml-1 text-[hsl(var(--primary))]">(utama)</span>}
                  </li>
                ))}
              </ul>
            )}
          </BarisDetail>
          <BarisDetail label="Rekening">
            {(sup.bank_accounts || []).length === 0 ? '—' : (
              <ul className="space-y-1">
                {sup.bank_accounts.map((b) => (
                  <li key={b.id || b.account_number}>{b.bank_name} {b.account_number} — {b.account_holder}</li>
                ))}
              </ul>
            )}
          </BarisDetail>
          <BarisDetail label="Rekap PO">
            {Object.keys(sup.po_stats || {}).length === 0 ? 'Belum ada PO' : (
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(sup.po_stats).map(([st, n]) => (
                  <StatusBadge key={st} status={st} label={`${labelStatusPO(st)}: ${n}`} />
                ))}
              </div>
            )}
          </BarisDetail>
          {sup.notes && <BarisDetail label="Catatan">{sup.notes}</BarisDetail>}
        </dl>
      )}

      {tab === 'price' && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-end gap-2">
            <TombolUnduh namaBerkas={`daftar-harga-${sup.code}`} namaLembar="Daftar harga" baris={priceList}
              testId="supplier-price-unduh"
              kolom={[
                { label: 'Kode material', nilai: (r) => r.material_code },
                { label: 'Material', nilai: (r) => r.material_name },
                { label: 'Harga per satuan beli', nilai: (r) => Number(r.price || 0) },
                { label: 'Satuan beli', nilai: (r) => r.uom },
                { label: 'Harga per satuan dasar', nilai: (r) => Number(r.price_base || 0) },
                { label: 'Satuan dasar', nilai: (r) => r.base_uom },
                { label: 'MOQ', nilai: (r) => Number(r.moq || 0) },
                { label: 'Berlaku', nilai: (r) => `${fmtDate(r.valid_from)}${r.valid_to ? ` – ${fmtDate(r.valid_to)}` : ''}` },
                { label: 'Status', nilai: (r) => (r.is_active === false ? 'Riwayat' : 'Berlaku') },
              ]} />
            <Button onClick={() => setPriceOpen(true)} data-testid="price-form-open">
              <Plus /> Tambah harga
            </Button>
          </div>
          {priceList.length === 0 ? (
            <EmptyState title="Belum ada daftar harga"
              description="Tambahkan harga supaya harga PO terisi otomatis." />
          ) : (
            <Table data-testid="supplier-price-list">
              <TableHeader>
                <TableRow>
                  <TableHead>Material</TableHead>
                  <TableHead className="text-right">Harga per satuan beli</TableHead>
                  <TableHead className="text-right">Per satuan dasar</TableHead>
                  <TableHead className="text-right">MOQ</TableHead>
                  <TableHead>Berlaku</TableHead>
                  <TableHead className="text-right"><span className="sr-only">Aksi</span></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {priceList.map((r) => (
                  <TableRow key={r.id} className={r.is_active === false ? 'opacity-60' : ''}>
                    <TableCell>
                      <div className="font-medium">{r.material_code}</div>
                      <div className="text-xs text-muted-foreground">{r.material_name}</div>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {fmtRp(r.price)} <span className="text-muted-foreground">/ {r.uom}</span>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {fmtRp(r.price_base)} <span className="text-muted-foreground">/ {r.base_uom}</span>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{r.moq ? `${fmtNum(r.moq)} ${r.uom}` : '—'}</TableCell>
                    <TableCell>
                      {fmtDate(r.valid_from)}{r.valid_to ? ` – ${fmtDate(r.valid_to)}` : ''}
                      {r.is_active === false && <span className="ml-1 text-xs text-muted-foreground">(riwayat)</span>}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="icon-sm" onClick={() => delPrice(r.id)} title="Hapus baris harga"
                        aria-label="Hapus baris harga" data-testid={`price-delete-${r.id}`}>
                        <Trash2 className="text-[hsl(var(--danger-text))]" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
      )}

      {tab === 'score' && (
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Hasil pemeriksaan QC penerimaan {card?.period_days ? `${card.period_days} hari terakhir` : ''}.
          </p>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatTile label="Penerimaan diperiksa" value={fmtNum(sc.total_grns ?? 0)}
              hint="Jumlah penerimaan barang dari supplier ini yang sudah diperiksa QC." />
            <StatTile label="Tingkat diterima" value={adaPeriksa ? `${fmtNum(sc.accept_rate ?? 0, 2)}%` : '—'}
              sub={adaPeriksa ? 'Qty diterima baik ÷ qty diperiksa' : 'Belum ada penerimaan diperiksa'} />
            <StatTile label="Tingkat cacat" value={adaPeriksa ? `${fmtNum(sc.defect_rate ?? 0, 2)}%` : '—'}
              sub={adaPeriksa ? 'Qty ditolak ÷ qty diperiksa' : 'Belum ada penerimaan diperiksa'} />
            <StatTile label="Tepat waktu" value={sc.on_time_rate == null ? '—' : `${fmtNum(sc.on_time_rate, 2)}%`}
              sub={sc.on_time_rate == null ? 'Belum ada data tanggal terima' : `${fmtNum(sc.on_time_samples ?? 0)} penerimaan dinilai`} />
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted-foreground">Grade kualitas:</span>
            <GradeBadge grade={sc.quality_grade} />
            {sup.rating_manual && (
              <span className="inline-flex items-center gap-1 text-[hsl(var(--warning-text))]">
                <Star className="h-4 w-4" /> Rating manual {sup.rating_manual}/5
              </span>
            )}
          </div>
          {adaPeriksa && (
            <p className="text-sm text-muted-foreground">
              Total diterima {fmtNum(sc.total_received ?? 0)} · diterima baik {fmtNum(sc.total_accepted ?? 0)} ·
              ditolak {fmtNum(sc.total_rejected ?? 0)} (satuan dasar material).
            </p>
          )}
          {poByStatus.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-medium">PO per status</p>
                <TombolUnduh namaBerkas={`po-per-status-${sup.code}`} namaLembar="PO per status" baris={poByStatus}
                  testId="supplier-po-status-unduh"
                  kolom={[
                    { label: 'Status PO', nilai: ([st]) => labelStatusPO(st) },
                    { label: 'Jumlah', nilai: ([, v]) => Number(v.count || 0) },
                    { label: 'Nilai (Rp)', nilai: ([, v]) => Number(v.value || 0) },
                  ]} />
              </div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Status PO</TableHead>
                    <TableHead className="text-right">Jumlah</TableHead>
                    <TableHead className="text-right">Nilai</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {poByStatus.map(([st, v]) => (
                    <TableRow key={st}>
                      <TableCell>{labelStatusPO(st)}</TableCell>
                      <TableCell className="text-right tabular-nums">{v.count}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmtRp(v.value)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </div>
      )}

      {priceOpen && (
        <PriceForm token={token} supplierId={supplierId} materials={materials}
          onClose={() => setPriceOpen(false)}
          onSaved={async () => { await load(); onChanged?.(); }} />
      )}
    </DetailPopup>
  );
}

// ── Popup tarik data supplier dari dokumen lama ─────────────────────────────
function MigrateModal({ token, onClose, onDone }) {
  const [prev, setPrev] = useState(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    apiGet(token, EP.migratePreview)
      .then(setPrev)
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));
  }, [token]);

  const run = async () => {
    setRunning(true);
    try {
      const r = await apiPost(token, EP.migrate, {});
      const bf = Object.entries(r.backfilled || {})
        .filter(([, n]) => n > 0)
        .map(([c, n]) => `${c}: ${n}`)
        .join(', ');
      toast.success(`${r.created_count} supplier dibuat. Dokumen ditautkan → ${bf || 'tidak ada'}`);
      onDone?.();
      onClose();
    } catch (e) {
      toast.error(e.message);
    } finally { setRunning(false); }
  };

  const baru = prev?.to_create || [];
  return (
    <FormPopup open onClose={onClose} ukuran="panjang" onSimpan={run} menyimpan={running} bisaSimpan={!loading}
      judul="Tarik supplier dari dokumen lama" labelSimpan="Jalankan sekarang" testId="supplier-migrate-modal"
      keterangan="Nama supplier teks bebas di PO, QC penerimaan, penerimaan gudang, PR aksesoris, dan faktur hutang dijadikan master; ejaan berbeda digabung, nama asli tidak dihapus.">
      {loading ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memindai dokumen lama…</p>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-3">
            <StatTile label="Nama ditemukan" value={fmtNum(prev?.summary?.legacy_names ?? 0)}
              hint="Nama supplier berbeda di dokumen lama" />
            <StatTile label="Akan dibuat" value={fmtNum(prev?.summary?.to_create ?? 0)}
              hint="Master supplier baru yang akan dibuat" />
            <StatTile label="Sudah cocok" value={fmtNum(prev?.summary?.already_matched ?? 0)}
              hint="Sudah tertaut ke master" />
          </div>
          {baru.length > 0 ? (
            <div className="space-y-2">
              <div className="flex justify-end">
                <TombolUnduh namaBerkas="tarik-supplier-pratinjau" namaLembar="Akan dibuat" baris={baru}
                  testId="migrate-preview-unduh"
                  kolom={[
                    { label: 'Nama supplier baru', nilai: (r) => r.name },
                    { label: 'Ejaan ditemukan', nilai: (r) => (r.variants || []).join(' · ') },
                    { label: 'Jumlah sumber', nilai: (r) => (r.sources || []).length },
                  ]} />
              </div>
              <Table data-testid="migrate-preview-list">
                <TableHeader>
                  <TableRow>
                    <TableHead>Nama supplier baru</TableHead>
                    <TableHead>Ejaan ditemukan</TableHead>
                    <TableHead className="text-right">Sumber</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {baru.map((r) => (
                    <TableRow key={r.name_key}>
                      <TableCell className="font-medium">{r.name}</TableCell>
                      <TableCell className="text-muted-foreground">{(r.variants || []).join(' · ')}</TableCell>
                      <TableCell className="text-right tabular-nums">{(r.sources || []).length} jenis dokumen</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <Notice tone="success" icon={CheckCircle2}>
              Semua nama supplier lama sudah punya master. Menjalankan ulang tetap aman.
            </Notice>
          )}
        </>
      )}
    </FormPopup>
  );
}

// ── Modul utama ─────────────────────────────────────────────────────────────
export default function SupplierMasterModule({ token }) {
  const [rows, setRows] = useState([]);
  const [pagination, setPagination] = useState({ page: 1, total: 0, total_pages: 1 });
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('');
  const [activeFilter, setActiveFilter] = useState('');
  const [meta, setMeta] = useState(null);
  const [materials, setMaterials] = useState([]);
  const [scoreMap, setScoreMap] = useState({});
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [detailId, setDetailId] = useState(null);
  const [migrateOpen, setMigrateOpen] = useState(false);
  const [err, setErr] = useState('');

  const PAGE_SIZE = 50;
  const load = useCallback(async (page = 1) => {
    setLoading(true);
    setErr('');
    try {
      const qs = new URLSearchParams({ page: String(page), limit: String(PAGE_SIZE), with_stats: 'true' });
      if (search) qs.set('search', search);
      if (category) qs.set('category', category);
      if (activeFilter) qs.set('is_active', activeFilter);
      const r = await apiGet(token, EP.suppliers(`?${qs.toString()}`));
      setRows(r?.items || []);
      setPagination(r?.pagination || { page, total: 0, total_pages: 1 });
    } catch (e) {
      setErr(e.message);
      toast.error(`Gagal memuat supplier: ${e.message}`);
    } finally { setLoading(false); }
  }, [token, search, category, activeFilter]);

  useEffect(() => { load(1); }, [load]);

  useEffect(() => {
    apiGet(token, EP.supplierMeta).then(setMeta).catch(() => {});
    apiGet(token, `${EP.materials}?include_inactive=false`)
      .then((m) => setMaterials((Array.isArray(m) ? m : m?.items || []).filter((x) => x.active !== false)))
      .catch(() => {});
    apiGet(token, EP.scorecard(365))
      .then((s) => {
        const map = {};
        (s?.items || []).forEach((x) => { if (x.supplier_id) map[x.supplier_id] = x; });
        setScoreMap(map);
      })
      .catch(() => {});
  }, [token]);

  const deactivate = async (s) => {
    const ok = await confirmDialog({
      title: `Nonaktifkan supplier ${s.name}?`,
      body: 'Supplier tidak bisa dipilih lagi di PO/PR baru; riwayatnya tetap ada.',
      confirmLabel: 'Nonaktifkan', danger: true,
    });
    if (!ok) return;
    try {
      await apiDelete(token, EP.supplier(s.id));
      toast.success('Supplier dinonaktifkan');
      load(pagination.page);
    } catch (e) { toast.error(e.message); }
  };

  const activate = async (s) => {
    try {
      await apiPost(token, EP.supplierActivate(s.id), {});
      toast.success('Supplier diaktifkan');
      load(pagination.page);
    } catch (e) { toast.error(e.message); }
  };

  const bukaUbah = (s) => { setEditing(s); setFormOpen(true); };

  // 2026-11-06 (T4): ekspor CSV halaman ini (hanya 50 baris halaman aktif) diganti Unduh/Impor Data Transfer
  // (semua supplier, format template impor) — satu pintu, tidak dua tombol ekspor.

  const kolom = [
    { kunci: 'kode', label: 'Kode', hp: 'keterangan', isi: (s) => (
      <span className="whitespace-nowrap tabular-nums">{s.code}{s.city ? <span className="md:hidden"> · {s.city}</span> : null}</span>) },
    { kunci: 'supplier', label: 'Supplier', hp: 'judul', isi: (s) => (
      <div className="min-w-0 md:max-w-[18rem]">
        <p className="truncate font-medium text-foreground" title={s.name}>{s.name}</p>
        {[s.city, s.phone].filter(Boolean).length > 0 && (
          <p className="hidden truncate text-xs text-muted-foreground md:block">{[s.city, s.phone].filter(Boolean).join(' · ')}</p>
        )}
      </div>) },
    { kunci: 'kategori', label: 'Kategori', isi: (s) => (
      <span className="text-sm">{kategoriTeks(s.categories) || <span className="text-muted-foreground">—</span>}</span>) },
    { kunci: 'termin', label: 'Termin', isi: (s) => PAYMENT_TERM_LABEL[s.payment_terms] || s.payment_terms },
    { kunci: 'lead', label: 'Lead time', rata: 'kanan', isi: (s) => <span className="tabular-nums">{s.lead_time_days || 0} hari</span> },
    { kunci: 'po', label: 'PO', rata: 'kanan', isi: (s) => <span className="tabular-nums">{fmtNum(s.po_count ?? 0)}</span> },
    { kunci: 'harga', label: 'Baris harga', rata: 'kanan', isi: (s) => <span className="tabular-nums">{fmtNum(s.price_list_count ?? 0)}</span> },
    { kunci: 'qc', label: 'Nilai QC', isi: (s) => {
      const sc = scoreMap[s.id];
      return sc && Number(sc.total_grns || 0) > 0 ? (
        <span className="inline-flex items-center gap-1.5">
          <GradeBadge grade={sc.quality_grade} />
          <span className="text-xs tabular-nums text-muted-foreground">{fmtNum(sc.accept_rate, 1)}%</span>
        </span>
      ) : <span className="text-muted-foreground">—</span>;
    } },
    { kunci: 'status', label: 'Status', isi: (s) => <ActiveBadge active={s.is_active} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (s) => (
      <div className="flex items-center justify-end gap-1">
        <Button variant="outline" size="icon-sm" onClick={() => bukaUbah(s)} title="Ubah supplier"
          aria-label={`Ubah ${s.name}`} data-testid={`supplier-edit-${s.id}`}>
          <Pencil />
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" title="Lainnya" aria-label={`Aksi lain ${s.name}`}
              data-testid={`supplier-more-${s.id}`}>
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => setDetailId(s.id)} data-testid={`supplier-view-${s.id}`}>
              <Eye className="mr-2 h-4 w-4" /> Lihat detail & daftar harga
            </DropdownMenuItem>
            {s.is_active === false ? (
              <DropdownMenuItem onSelect={() => activate(s)} data-testid={`supplier-activate-${s.id}`}>
                <CheckCircle2 className="mr-2 h-4 w-4" /> Aktifkan
              </DropdownMenuItem>
            ) : (
              <DropdownMenuItem onSelect={() => deactivate(s)} data-testid={`supplier-deactivate-${s.id}`}
                className="text-[hsl(var(--danger-text))]">
                <Ban className="mr-2 h-4 w-4" /> Nonaktifkan
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>) },
  ];

  const disaring = !!(search || category || activeFilter);

  return (
    <PageLayout testId="supplier-master-page" title="Master Supplier"
      subtitle="Data supplier: kontak, NPWP, termin bayar, rekening, dan daftar harga per satuan beli."
      actions={
        // Banyak tombol data → dibungkus supaya tetap berbaris di HP (tidak keluar layar).
        <div className="flex flex-wrap items-center gap-2 max-sm:max-w-[calc(100vw-2rem)]">
          <Button variant="outline" onClick={() => setMigrateOpen(true)} data-testid="supplier-migrate-btn">
            <Truck /> Tarik data lama
          </Button>
          <ImportExportToolbar collectionKey="suppliers" label="Master Supplier" size="default" onImported={() => load(1)} />
          <ImportExportToolbar collectionKey="supplier_prices" label="Daftar Harga Supplier" caption="harga" size="default"
            onImported={() => load(pagination.page)} />
          <Button onClick={() => { setEditing(null); setFormOpen(true); }} data-testid="supplier-create-btn">
            <Plus /> Tambah supplier
          </Button>
        </div>
      }
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="pl-8" placeholder="Cari nama, kode, NPWP, kota"
            value={search} onChange={(e) => setSearch(e.target.value)} data-testid="supplier-search" />
        </div>
        <SmartNativeSelect value={category} onChange={(e) => setCategory(e.target.value)}
          className="w-44" data-testid="supplier-filter-category">
          <option value="">Semua kategori</option>
          {Object.entries(CATEGORY_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={activeFilter} onChange={(e) => setActiveFilter(e.target.value)}
          className="w-40" data-testid="supplier-filter-active">
          <option value="">Semua status</option>
          <option value="true">Aktif</option>
          <option value="false">Nonaktif</option>
        </SmartNativeSelect>
      </>}
      tools={
        <Button variant="outline" size="icon" onClick={() => load(pagination.page)} disabled={loading}
          title="Muat ulang" aria-label="Muat ulang" data-testid="supplier-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      }
      footer={pagination.total_pages > 1 && (
        <PaginationLite page={pagination.page} totalPages={pagination.total_pages} total={pagination.total}
          pageSize={PAGE_SIZE} onPageChange={(p) => load(p)} />
      )}>
      {err && <Notice tone="danger">{err}</Notice>}

      {loading && rows.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat supplier…</p>
      ) : (
        <TabelData kolom={kolom} baris={rows} onKlikBaris={(s) => setDetailId(s.id)} testId="supplier-table"
          kosong={<EmptyState icon={Building2}
            title={disaring ? 'Tidak ada supplier yang cocok' : 'Belum ada supplier di master'}
            description={disaring ? 'Ubah kata pencarian atau saringan.'
              : 'Klik "Tarik data lama" untuk membuat master dari nama supplier di dokumen yang sudah ada.'} />} />
      )}

      {formOpen && (
        <SupplierForm token={token} meta={meta} initial={editing}
          onClose={() => { setFormOpen(false); setEditing(null); }}
          onSaved={() => load(pagination.page)} />
      )}
      {detailId && (
        <SupplierDetail token={token} supplierId={detailId} materials={materials}
          onClose={() => setDetailId(null)}
          onChanged={() => load(pagination.page)}
          // Ubah memakai baris daftar (bukan objek detail yang membawa daftar harga/rekap) — sama dengan tombol Ubah di tabel.
          onEdit={(s) => { const baris = rows.find((r) => r.id === s.id); if (!baris) return; setDetailId(null); bukaUbah(baris); }} />
      )}
      {migrateOpen && (
        <MigrateModal token={token} onClose={() => setMigrateOpen(false)}
          onDone={() => load(1)} />
      )}
    </PageLayout>
  );
}

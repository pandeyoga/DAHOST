/**
 * CreateAssetDialog — daftarkan aset baru (termasuk garansi & asuransi).
 *
 * Standar UI/UX v2 (8 Nov 2026): popup form standar ukuran panjang (FormPopup + Isian), pemilih tanggal
 * seragam (DatePicker, dulu isian tanggal bawaan peramban), tanpa emoji, pesan galat di kaki form, Simpan hijau.
 * Isian, aturan, dan data yang dikirim tidak berubah.
 */
import { useEffect, useState } from 'react';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import DatePicker from '@/components/ui/date-picker';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { todayWIB } from '@/lib/waktu';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { toast } from 'sonner';
import { apicall } from '../utils';
import DocNumberField, { useDocNumberPolicy, docNumberPayload } from '../../docnum/DocNumberField';
import { DepartmentSelect } from '../../hr/hrPickers';

const KOSONG = () => ({
  name: '', category_id: '', purchase_date: todayWIB(),
  purchase_cost: '', residual_value: '', useful_life_months: '',
  serial_number: '', brand: '', model: '', location: '', department: '', notes: '',
  // Warranty
  warranty_expiry_date: '', warranty_provider: '', warranty_terms: '',
  // Insurance
  insurance_policy_number: '', insurance_provider: '', insurance_expiry_date: '', insurance_value: '',
});

const Judul = ({ children }) => <p className="border-t border-[var(--glass-border)] pt-3 text-sm font-semibold text-foreground">{children}</p>;

export function CreateAssetDialog({ open, onClose, token, categories, onCreated }) {
  const [form, setForm] = useState(KOSONG);
  const [loading, setLoading] = useState(false);
  const [galat, setGalat] = useState('');
  const set = (k, v) => setForm(p => ({ ...p, [k]: v }));
  // 2026-11-02 (K18): registri induk = Keuangan › Aset Tetap. Portal Aset menaut aset Keuangan
  // (nilai buku & penyusutan diambil dari sana) dan TIDAK lagi membuat jurnal.
  const [finAssets, setFinAssets] = useState([]);
  const [fixedAssetId, setFixedAssetId] = useState('');
  useEffect(() => {
    if (!open) return;
    setGalat('');
    apicall('GET', '/api/assets/finance-registry', token).then(d => setFinAssets(Array.isArray(d) ? d : [])).catch(() => setFinAssets([]));
  }, [open, token]);
  const pickFinance = (id) => {
    setFixedAssetId(id);
    const f = finAssets.find(x => x.id === id);
    if (f) setForm(p => ({ ...p, name: p.name || f.name, purchase_cost: String(f.purchase_cost || ''), purchase_date: f.purchase_date || p.purchase_date }));
  };
  // SESI #27 — kebijakan penomoran Nomor Aset Inventaris. `KATEGORI` mengikuti
  // kategori terpilih supaya pratinjau nomor = nomor yang benar-benar akan lahir.
  const catCode = (categories || []).find(c => c.id === form.category_id)?.code || '';
  const numPolicy = useDocNumberPolicy('dewi_assets.asset_number', token,
                                       { KATEGORI: catCode });
  const [assetNo, setAssetNo] = useState('');

  const submit = async () => {
    if (!form.name.trim()) { setGalat('Nama aset wajib diisi.'); return; }
    if (!form.purchase_cost || Number(form.purchase_cost) <= 0) { setGalat('Harga beli harus lebih dari 0.'); return; }
    setGalat('');
    setLoading(true);
    try {
      const data = await apicall('POST', '/api/assets', token, {
        ...form,
        ...docNumberPayload(numPolicy, 'asset_number', assetNo),
        fixed_asset_id: fixedAssetId || undefined,
        purchase_cost: Number(form.purchase_cost),
        residual_value: form.residual_value ? Number(form.residual_value) : undefined,
        useful_life_months: form.useful_life_months ? Number(form.useful_life_months) : undefined,
      });
      if (data.id) {
        toast.success(`Aset ${data.asset_number} berhasil didaftarkan`);
        onCreated(data); onClose();
      } else {
        setGalat(data.detail || 'Gagal mendaftarkan aset.');
      }
    } catch (e) { setGalat(e.message || 'Gagal mendaftarkan aset.'); }
    finally { setLoading(false); }
  };

  return (
    <FormPopup open={open} onClose={onClose} ukuran="panjang" testId="create-asset-form"
      judul="Daftarkan aset baru"
      keterangan="Isi data aset: nama, kategori, harga beli; garansi & asuransi boleh dikosongkan."
      onSimpan={submit} labelSimpan="Daftarkan aset" menyimpan={loading} galat={galat}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Tautkan ke aset tetap Keuangan" htmlFor="asset-finance-link"
          petunjuk="Harga, penyusutan & nilai buku diambil dari registri Keuangan. Aset baru didaftarkan dulu di Keuangan › Aset Tetap (atau lewat penerimaan barang).">
          {/* 2026-11-07 (audit form Tahap 5): pilihan aplikasi yang bisa dicari (dulu pilihan polos peramban) */}
          <SmartNativeSelect id="asset-finance-link" value={fixedAssetId} onChange={e => pickFinance(e.target.value)} data-testid="asset-finance-link"
            className="h-9 w-full" searchPlaceholder="Cari kode atau nama aset…">
            <option value="">— Belum ditaut (catatan operasional saja) —</option>
            {finAssets.map(f => <option key={f.id} value={f.id}>{`${f.code} · ${f.name} · nilai buku Rp ${Number(f.book_value || 0).toLocaleString('id-ID')}`}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Nama aset" wajib htmlFor="asset-name">
          <Input id="asset-name" placeholder="Contoh: Mesin jahit Juki DDL-8700" value={form.name}
            onChange={e => set('name', e.target.value)} data-testid="asset-name-input" />
        </Isian>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Kategori" htmlFor="asset-category">
          <SmartNativeSelect id="asset-category" value={form.category_id} onChange={e => set('category_id', e.target.value)}
            className="h-9 w-full" data-testid="asset-category">
            <option value="">Pilih kategori…</option>
            {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Tanggal beli" wajib>
          <DatePicker value={form.purchase_date} onChange={v => set('purchase_date', v)} bolehKosong={false}
            pilihTahun="lampau" testId="asset-purchase-date" />
        </Isian>
        <Isian label="Harga beli (Rp)" wajib htmlFor="asset-cost">
          <MoneyInput id="asset-cost" placeholder="5.000.000" value={form.purchase_cost}
            onChange={e => set('purchase_cost', e.target.value)} data-testid="asset-cost-input" />
        </Isian>
        <Isian label="Nilai residu (Rp)" petunjuk="Kosong = otomatis 5% harga beli." htmlFor="asset-residual">
          <MoneyInput id="asset-residual" placeholder="Otomatis 5%" value={form.residual_value}
            onChange={e => set('residual_value', e.target.value)} />
        </Isian>
        <Isian label="Umur manfaat (bulan)" petunjuk="Kosong = mengikuti kategori." htmlFor="asset-life">
          <Input id="asset-life" type="number" inputMode="numeric" placeholder="Dari kategori" value={form.useful_life_months}
            onChange={e => set('useful_life_months', e.target.value)} />
        </Isian>
        <Isian label="No. seri" htmlFor="asset-serial">
          <Input id="asset-serial" placeholder="SN-XXXX" value={form.serial_number}
            onChange={e => set('serial_number', e.target.value)} />
        </Isian>
        <Isian label="Merek" htmlFor="asset-brand">
          <Input id="asset-brand" placeholder="Juki, Brother, Dell" value={form.brand}
            onChange={e => set('brand', e.target.value)} />
        </Isian>
        <Isian label="Model" htmlFor="asset-model">
          <Input id="asset-model" placeholder="DDL-8700" value={form.model}
            onChange={e => set('model', e.target.value)} />
        </Isian>
        <Isian label="Lokasi" htmlFor="asset-location">
          <Input id="asset-location" placeholder="Ruang IT, lantai 2" value={form.location}
            onChange={e => set('location', e.target.value)} />
        </Isian>
        <Isian label="Departemen">
          {/* 2026-11-07 (OR1): dari Struktur Organisasi; Lokasi (ruang fisik) tetap isian bebas */}
          <DepartmentSelect token={token} value={form.department} testId="asset-department"
            placeholder="— Tanpa departemen —" onChange={v => set('department', v)} />
        </Isian>
      </div>
      <Isian label="Catatan" htmlFor="asset-notes">
        <Input id="asset-notes" placeholder="Catatan tambahan…" value={form.notes}
          onChange={e => set('notes', e.target.value)} />
      </Isian>

      <Judul>Garansi (boleh kosong)</Judul>
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Garansi berakhir">
          <DatePicker value={form.warranty_expiry_date} onChange={v => set('warranty_expiry_date', v)}
            placeholder="Tanpa garansi" pilihTahun testId="asset-warranty-date" />
        </Isian>
        <Isian label="Penyedia garansi" htmlFor="asset-warranty-provider">
          <Input id="asset-warranty-provider" placeholder="Dealer resmi, toko" value={form.warranty_provider}
            onChange={e => set('warranty_provider', e.target.value)} />
        </Isian>
      </div>
      <Isian label="Syarat garansi" htmlFor="asset-warranty-terms">
        <Input id="asset-warranty-terms" placeholder="Servis di tempat 3 tahun, suku cadang gratis" value={form.warranty_terms}
          onChange={e => set('warranty_terms', e.target.value)} />
      </Isian>

      <Judul>Asuransi (boleh kosong)</Judul>
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Nomor polis" htmlFor="asset-policy">
          <Input id="asset-policy" placeholder="POL-2026-XXXX" value={form.insurance_policy_number}
            onChange={e => set('insurance_policy_number', e.target.value)} />
        </Isian>
        <Isian label="Penyedia asuransi" htmlFor="asset-insurer">
          <Input id="asset-insurer" placeholder="Jasindo, Asuransi Jaya" value={form.insurance_provider}
            onChange={e => set('insurance_provider', e.target.value)} />
        </Isian>
        <Isian label="Asuransi berakhir">
          <DatePicker value={form.insurance_expiry_date} onChange={v => set('insurance_expiry_date', v)}
            placeholder="Tanpa asuransi" pilihTahun testId="asset-insurance-date" />
        </Isian>
        <Isian label="Nilai pertanggungan (Rp)" htmlFor="asset-insured-value">
          <MoneyInput id="asset-insured-value" placeholder="50.000.000" value={form.insurance_value}
            onChange={e => set('insurance_value', e.target.value)} />
        </Isian>
      </div>

      <DocNumberField
        policy={numPolicy} value={assetNo} onChange={setAssetNo}
        testId="asset-inv-docnum" label="Nomor aset" />
      <p className="text-xs text-muted-foreground">
        Portal Aset tidak membuat jurnal. Jurnal perolehan, penyusutan & pelepasan hanya dari registri Keuangan.
      </p>
    </FormPopup>
  );
}

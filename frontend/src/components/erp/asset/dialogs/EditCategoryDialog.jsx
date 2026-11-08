/**
 * EditCategoryDialog — Edit asset category & COA mapping.
 * Extracted from AssetManagementPortal.jsx (Phase 2 refactor)
 *
 * 2026-11-07 (audit form Tahap 5): akun aset & akumulasi penyusutan DIPILIH dari Bagan Akun (kode · nama,
 * bisa dicari) — dulu kotak teks bebas "1500 - Aset Tetap", sehingga yang tersimpan bukan kode akun dan
 * pemeriksa keterikatan akun (core/coa_bindings, "rujukan id ATAU kode") tidak bisa menautkannya. Yang disimpan
 * kini KODE akun. Nilai lama yang bukan kode akun tetap tampil (bertanda) sampai diganti.
 *
 * Standar UI/UX v2 (8 Nov 2026): popup form standar pendek (FormPopup + Isian), galat di kaki form.
 */
import { useState, useEffect } from 'react';
import { toast } from 'sonner';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { apicall } from '../utils';

export function EditCategoryDialog({ open, onClose, token, category, onUpdated }) {
  const [form, setForm] = useState({
    name: '', code: '', useful_life_years: 5, depr_method: 'straight_line',
    coa_asset_account: '', coa_depreciation_account: '',
  });
  const [loading, setLoading] = useState(false);
  const [galat, setGalat] = useState('');
  const [accounts, setAccounts] = useState([]);

  useEffect(() => {
    if (category) {
      setGalat('');
      setForm({
        name: category.name || '',
        code: category.code || '',
        useful_life_years: category.useful_life_years || 5,
        depr_method: category.depr_method || 'straight_line',
        coa_asset_account: category.coa_asset_account || '',
        coa_depreciation_account: category.coa_depreciation_account || '',
      });
    }
  }, [category]);

  // akun Aset rinci & aktif (akun aset tetap dan akumulasi penyusutan = tipe Aset)
  useEffect(() => {
    if (!open) return;
    apicall('GET', '/api/rahaza/coa/accounts?type=ASSET', token)
      .then((d) => setAccounts((Array.isArray(d) ? d : []).filter((a) => !a.is_group && a.active !== false)))
      .catch(() => setAccounts([]));
  }, [open, token]);

  const set = (k, v) => setForm(p => ({ ...p, [k]: v }));

  const submit = async () => {
    if (!form.name.trim()) { setGalat('Nama kategori wajib diisi.'); return; }
    if (!(Number(form.useful_life_years) > 0)) { setGalat('Umur manfaat harus lebih dari 0 tahun.'); return; }
    setGalat('');
    setLoading(true);
    try {
      // nama/kode hanya dikirim bila diubah — server memeriksa ulang keunikan nama setiap kali `name` dikirim,
      // sehingga kategori yang namanya kembar (data lama) dulu tidak bisa disimpan sama sekali walau hanya akunnya diubah.
      const body = { ...form, useful_life_years: Number(form.useful_life_years) };
      if (form.name.trim() === (category.name || '')) delete body.name;
      if ((form.code || '') === (category.code || '')) delete body.code;
      const data = await apicall('PUT', `/api/assets/categories/${category.id}`, token, body);
      if (data.ok) {
        toast.success('Kategori disimpan');
        onUpdated();
        onClose();
      } else {
        setGalat(data.detail || 'Gagal menyimpan kategori.');
      }
    } catch (e) { setGalat(e.message || 'Gagal menyimpan kategori.'); }
    finally { setLoading(false); }
  };

  const accountSelect = (field, testId, placeholder) => {
    const cur = form[field];
    const known = !cur || accounts.some((a) => a.code === cur);
    return (
      <SmartNativeSelect value={cur} onChange={(e) => set(field, e.target.value)} className="h-9 w-full"
        searchPlaceholder="Cari kode atau nama akun…" data-testid={testId}>
        <option value="">{placeholder}</option>
        {!known && <option value={cur}>{`${cur} — bukan kode akun di Bagan Akun, pilih ulang`}</option>}
        {accounts.map((a) => <option key={a.code} value={a.code}>{`${a.code} · ${a.name}`}</option>)}
      </SmartNativeSelect>
    );
  };

  return (
    <FormPopup open={open} onClose={onClose} ukuran="pendek" testId="edit-category-form"
      judul="Ubah kategori aset" keterangan={category ? `${category.code || ''} ${category.name || ''}`.trim() : undefined}
      onSimpan={submit} menyimpan={loading} galat={galat}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Nama kategori" wajib htmlFor="cat-name">
          <Input id="cat-name" placeholder="Peralatan IT" value={form.name}
            onChange={e => set('name', e.target.value)} data-testid="cat-name-input" />
        </Isian>
        <Isian label="Kode" htmlFor="cat-code">
          <Input id="cat-code" placeholder="IT" value={form.code}
            onChange={e => set('code', e.target.value)} data-testid="cat-code-input" />
        </Isian>
        <Isian label="Umur manfaat (tahun)" htmlFor="cat-life">
          <Input id="cat-life" type="number" min="1" inputMode="numeric" value={form.useful_life_years}
            onChange={e => set('useful_life_years', e.target.value)} data-testid="cat-life-input" />
        </Isian>
        <Isian label="Metode penyusutan">
          <SmartNativeSelect value={form.depr_method} onChange={e => set('depr_method', e.target.value)} searchable={false}
            className="h-9 w-full" data-testid="cat-depr-method">
            <option value="straight_line">Garis lurus</option>
            <option value="double_declining">Saldo menurun ganda</option>
          </SmartNativeSelect>
        </Isian>
      </div>
      <Isian label="Akun aset" petunjuk="Akun Bagan Akun untuk mencatat pembelian aset kategori ini.">
        {accountSelect('coa_asset_account', 'cat-coa-asset', '— Belum diatur —')}
      </Isian>
      <Isian label="Akun akumulasi penyusutan" petunjuk="Akun Bagan Akun untuk mencatat akumulasi penyusutan.">
        {accountSelect('coa_depreciation_account', 'cat-coa-depr', '— Belum diatur —')}
      </Isian>
    </FormPopup>
  );
}

/**
 * KatalogArtikelForm — artikel Katalog Buyer baru / ubah, DI HALAMAN (DetailPanel).
 *
 * Tahap 9 (7 Nov 2026): dulu dialog besar (BuyerCatalogDialog) dengan Select Radix dan tombol pil buatan
 * sendiri. Isi & aturannya sama: warna & ukuran HANYA dari master (Tahap 6 PR5), buyer tidak bisa diubah
 * setelah artikel dibuat, dan varian SKU bisa langsung dibuat setelah simpan.
 *
 *   POST /api/dewi/maklon/buyer-catalog · PUT /api/dewi/maklon/buyer-catalog/{id}
 *   POST /api/dewi/maklon/buyer-catalog/{id}/variants/generate
 */
import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassInput } from '@/components/ui/glass';
import { MoneyInput } from '@/components/ui/money-input';
import { Textarea } from '@/components/ui/textarea';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { apiGet, apiPost, apiPut } from '../../../lib/api';
import { DetailPanel } from '../layout/PageLayout';
import { Notice } from '../moduleAtoms';

export const CATEGORIES = ['Dress', 'Blouse', 'Rok', 'Celana', 'Set/Setelan', 'Baju Anak', 'Hijab', 'Aksesoris', 'Lainnya'];
export const ARTIKEL_STATUS = { active: 'Aktif', inactive: 'Nonaktif', discontinued: 'Dihentikan' };

function Field({ label, children, hint, className = '' }) {
  return (
    <label className={`block space-y-1 ${className}`}>
      <span className="text-xs text-muted-foreground">{label}</span>
      {children}
      {hint && <span className="block text-[11px] text-muted-foreground">{hint}</span>}
    </label>
  );
}

export default function KatalogArtikelForm({ data, clients, onCancel, onSaved, onOpenRnd }) {
  const isEdit = !!data;
  const [form, setForm] = useState({
    client_id: data?.client_id || '', artikel_code: data?.artikel_code || '', buyer_ref_code: data?.buyer_ref_code || '',
    product_name: data?.product_name || '', category: data?.category || '', season: data?.season || '', gender: data?.gender || '',
    default_cmt_price: data?.default_cmt_price ?? 0, default_selling_price: data?.default_selling_price ?? 0,
    color_options: Array.isArray(data?.color_options) ? data.color_options : [],
    size_options: Array.isArray(data?.size_options) ? data.size_options : [],
    description: data?.description || '', hero_image_url: data?.hero_image_url || '', status: data?.status || 'active',
  });
  const [saving, setSaving] = useState(false);
  const [palette, setPalette] = useState([]);
  const [sizeMaster, setSizeMaster] = useState([]);
  const [autoGen, setAutoGen] = useState(!isEdit);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  useEffect(() => {
    let alive = true;
    Promise.all([apiGet('/rahaza/colors').catch(() => []), apiGet('/rahaza/sizes').catch(() => [])]).then(([c, s]) => {
      if (!alive) return;
      setPalette((Array.isArray(c) ? c : []).filter((x) => x.active !== false));
      setSizeMaster((Array.isArray(s) ? s : []).filter((x) => x.active !== false));
    });
    return () => { alive = false; };
  }, []);

  const colorCodeFor = (name) => {
    const p = palette.find((c) => (c.name || '').toLowerCase() === String(name).trim().toLowerCase());
    if (p) return p.code;
    return String(name).replace(/[^A-Za-z0-9]/g, '').toUpperCase().slice(0, 3) || 'X';
  };
  const sizeCodeFor = (s) => String(s).replace(/[^A-Za-z0-9]/g, '').toUpperCase();
  const toggleIn = (key, v) => setForm((f) => ({ ...f, [key]: f[key].includes(v) ? f[key].filter((x) => x !== v) : [...f[key], v] }));
  const skuCount = form.color_options.length * form.size_options.length;
  const exampleSku = form.artikel_code && form.color_options[0] && form.size_options[0]
    ? [form.artikel_code.trim().toUpperCase(), colorCodeFor(form.color_options[0]), sizeCodeFor(form.size_options[0])].join('-') : null;
  const legacyColors = form.color_options.filter((n) => !palette.some((p) => p.name === n));
  const legacySizes = form.size_options.filter((c) => !sizeMaster.some((s) => s.code === c));

  const save = async () => {
    if (!form.client_id) { toast.error('Pilih buyer terlebih dahulu'); return; }
    if (!form.artikel_code.trim()) { toast.error('Kode artikel wajib diisi'); return; }
    if (!form.product_name.trim()) { toast.error('Nama produk wajib diisi'); return; }
    setSaving(true);
    try {
      const payload = {
        ...form, artikel_code: form.artikel_code.trim(), buyer_ref_code: form.buyer_ref_code.trim(),
        product_name: form.product_name.trim(), default_cmt_price: Number(form.default_cmt_price) || 0,
        default_selling_price: Number(form.default_selling_price) || 0,
      };
      if (isEdit) delete payload.client_id; // buyer tidak bisa diubah (kunci unik gabungan)
      const saved = isEdit ? await apiPut(`/dewi/maklon/buyer-catalog/${data.id}`, payload) : await apiPost('/dewi/maklon/buyer-catalog', payload);
      const catalogId = isEdit ? data.id : (saved?.id || saved?.item?.id);
      const what = isEdit ? 'Artikel diperbarui' : 'Artikel dibuat';
      if (autoGen && catalogId && form.color_options.length && form.size_options.length) {
        try {
          const gd = await apiPost(`/dewi/maklon/buyer-catalog/${catalogId}/variants/generate`, {});
          toast.success(`${what} · ${gd?.total || 0} varian SKU siap`);
        } catch (e) {
          // 2026-11-06 (pola P6): artikel tersimpan tetapi varian gagal — beri tahu, jangan diam-diam "berhasil".
          toast.warning(`${what}, tetapi varian SKU gagal dibuat: ${e.message}. Buat varian dari rincian artikel.`);
        }
      } else toast.success(what);
      onSaved(catalogId);
    } catch (e) { toast.error(e.message || 'Gagal menyimpan'); }
    finally { setSaving(false); }
  };

  return (
    <DetailPanel testId="buyer-catalog-dialog" onClose={onCancel}
      title={isEdit ? `Ubah artikel · ${data.artikel_code}` : 'Artikel buyer baru'}
      description={isEdit ? 'Buyer tidak bisa diubah setelah artikel dibuat.' : 'Spesifikasi & harga bawaan dari klien maklon.'}>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <Field label="Buyer (klien) *" className="lg:col-span-2">
          <SmartNativeSelect value={form.client_id} onChange={set('client_id')} disabled={isEdit} className="w-full h-9"
            data-testid="bc-form-client" aria-label="Buyer">
            <option value="">— Pilih buyer —</option>
            {clients.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.code})</option>)}
          </SmartNativeSelect>
        </Field>
        <Field label="Status">
          <SmartNativeSelect value={form.status} onChange={set('status')} className="w-full h-9" searchable={false}
            data-testid="bc-form-status" aria-label="Status artikel">
            {Object.entries(ARTIKEL_STATUS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </SmartNativeSelect>
        </Field>
        <Field label="Kategori">
          <SmartNativeSelect value={form.category} onChange={set('category')} className="w-full h-9" searchable={false}
            data-testid="bc-form-category" aria-label="Kategori">
            <option value="">— Pilih kategori —</option>
            {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </SmartNativeSelect>
        </Field>
        <Field label="Kode artikel (internal) *"><GlassInput value={form.artikel_code} onChange={set('artikel_code')} placeholder="mis. MAK-KLN-001" data-testid="bc-form-artikel-code" /></Field>
        <Field label="Kode buyer (referensi)"><GlassInput value={form.buyer_ref_code} onChange={set('buyer_ref_code')} data-testid="bc-form-buyer-ref" /></Field>
        <Field label="Nama produk *" className="lg:col-span-2"><GlassInput value={form.product_name} onChange={set('product_name')} data-testid="bc-form-product-name" /></Field>
        <Field label="Musim"><GlassInput value={form.season} onChange={set('season')} placeholder="mis. SS24" /></Field>
        <Field label="Gender"><GlassInput value={form.gender} onChange={set('gender')} placeholder="Wanita / Pria / Unisex" /></Field>
        <Field label="Upah jahit CMT (bawaan) *" hint="Bisa diubah saat membuat PO.">
          <MoneyInput glass value={form.default_cmt_price} onChange={set('default_cmt_price')} data-testid="bc-form-default-cmt-price" />
        </Field>
        <Field label="Harga jasa ke klien (bawaan)">
          <MoneyInput glass value={form.default_selling_price} onChange={set('default_selling_price')} data-testid="bc-form-default-selling-price" />
        </Field>
      </div>

      <div className="space-y-2" data-testid="bc-form-variants">
        <p className="text-sm font-semibold text-foreground">Varian & SKU</p>
        <div>
          <p className="text-xs text-muted-foreground mb-1">Warna (dari master warna)</p>
          <div className="flex flex-wrap gap-x-4 gap-y-1.5" data-testid="bc-form-color-palette">
            {palette.map((c) => (
              <label key={c.id} className="inline-flex items-center gap-1.5 text-sm cursor-pointer" data-testid={`bc-color-chip-${c.code}`}>
                <input type="checkbox" checked={form.color_options.includes(c.name)} onChange={() => toggleIn('color_options', c.name)}
                  className="h-4 w-4 accent-[hsl(var(--primary))]" />
                <span className="w-3 h-3 rounded-full border border-[var(--glass-border)]" style={{ backgroundColor: c.hex }} />
                {c.name} <span className="text-[10px] text-muted-foreground tabular-nums">{c.code}</span>
              </label>
            ))}
            {legacyColors.map((n) => (
              <label key={n} className="inline-flex items-center gap-1.5 text-sm text-[hsl(var(--warning))] cursor-pointer" title="Opsi lama — belum ada di master warna">
                <input type="checkbox" checked onChange={() => toggleIn('color_options', n)} className="h-4 w-4" />{n} (lama)
              </label>
            ))}
          </div>
        </div>
        <div>
          <p className="text-xs text-muted-foreground mb-1">Ukuran (dari master ukuran)</p>
          <div className="flex flex-wrap gap-x-4 gap-y-1.5" data-testid="bc-form-size-palette">
            {sizeMaster.map((s) => (
              <label key={s.id} className="inline-flex items-center gap-1.5 text-sm tabular-nums cursor-pointer" data-testid={`bc-size-chip-${s.code}`}>
                <input type="checkbox" checked={form.size_options.includes(s.code)} onChange={() => toggleIn('size_options', s.code)}
                  className="h-4 w-4 accent-[hsl(var(--primary))]" />{s.code}
              </label>
            ))}
            {legacySizes.map((c) => (
              <label key={c} className="inline-flex items-center gap-1.5 text-sm text-[hsl(var(--warning))] cursor-pointer" title="Opsi lama — belum ada di master ukuran">
                <input type="checkbox" checked onChange={() => toggleIn('size_options', c)} className="h-4 w-4" />{c} (lama)
              </label>
            ))}
          </div>
        </div>
        <p className="text-[11px] text-muted-foreground" data-testid="bc-form-master-hint">
          Warna atau ukuran belum ada? Tambahkan dulu di Portal RnD › Master Produk › Warna / Ukuran.{' '}
          {onOpenRnd && <Button type="button" variant="link" size="sm" className="h-auto p-0 text-[11px]" onClick={onOpenRnd} data-testid="bc-form-master-link">Buka Master Produk</Button>}
        </p>
        <Notice tone="info" testId="bc-form-sku-preview"
          title={`Akan terbentuk ${skuCount} varian SKU (warna × ukuran)${exampleSku ? ` · contoh ${exampleSku}` : ''}`}>
          <label className="inline-flex items-center gap-2 text-xs cursor-pointer">
            <input type="checkbox" checked={autoGen} onChange={(e) => setAutoGen(e.target.checked)} className="h-4 w-4 accent-[hsl(var(--primary))]"
              data-testid="bc-form-autogen" />
            Langsung buat varian SKU setelah simpan. Kode buyer per varian bisa diisi nanti di rincian artikel.
          </label>
        </Notice>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <Field label="Foto utama (alamat gambar)"><GlassInput value={form.hero_image_url} onChange={set('hero_image_url')} placeholder="https://…" /></Field>
        <Field label="Deskripsi / spesifikasi dari buyer">
          <Textarea rows={3} value={form.description} onChange={set('description')} placeholder="Bahan, finishing, kemasan, dll." data-testid="bc-form-description" />
        </Field>
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={onCancel} disabled={saving} data-testid="bc-form-cancel">Batal</Button>
        <Button onClick={save} disabled={saving} data-testid="bc-form-save">{isEdit ? 'Simpan perubahan' : 'Simpan artikel'}</Button>
      </div>
    </DetailPanel>
  );
}

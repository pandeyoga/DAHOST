/**
 * KatalogArtikelForm — artikel Katalog Buyer baru / ubah.
 *
 * Standar UI/UX v2 (8 Nov 2026): FormPopup panjang (form selalu popup; dulu panel di halaman). Isian, aturan, dan
 * panggilan server sama; centang memakai Checkbox standar, ukuran huruf standar.
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
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { MoneyInput } from '@/components/ui/money-input';
import { Textarea } from '@/components/ui/textarea';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { apiGet, apiPost, apiPut } from '../../../lib/api';
import { Notice } from '../moduleAtoms';

export const CATEGORIES = ['Dress', 'Blouse', 'Rok', 'Celana', 'Set/Setelan', 'Baju Anak', 'Hijab', 'Aksesoris', 'Lainnya'];
export const ARTIKEL_STATUS = { active: 'Aktif', inactive: 'Nonaktif', discontinued: 'Dihentikan' };

/** Isian standar; tanda * di label lama → `wajib`. */
function Field({ label, children, hint, className = '' }) {
  const wajib = /\*\s*$/.test(label);
  return <Isian label={label.replace(/\s*\*\s*$/, '')} wajib={wajib} petunjuk={hint} className={className}>{children}</Isian>;
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
    <FormPopup open onClose={onCancel} ukuran="panjang" testId="buyer-catalog-dialog" onSimpan={save} menyimpan={saving}
      judul={isEdit ? `Ubah artikel · ${data.artikel_code}` : 'Artikel buyer baru'}
      keterangan={isEdit ? 'Buyer tidak bisa diubah setelah artikel dibuat.' : 'Spesifikasi & harga bawaan dari klien maklon.'}
      labelSimpan={isEdit ? 'Simpan perubahan' : 'Simpan artikel'}>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Buyer (klien) *" className="sm:col-span-2">
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
        <Field label="Kode artikel (internal) *"><Input value={form.artikel_code} onChange={set('artikel_code')} placeholder="mis. MAK-KLN-001" data-testid="bc-form-artikel-code" /></Field>
        <Field label="Kode buyer (referensi)"><Input value={form.buyer_ref_code} onChange={set('buyer_ref_code')} data-testid="bc-form-buyer-ref" /></Field>
        <Field label="Nama produk *" className="sm:col-span-2"><Input value={form.product_name} onChange={set('product_name')} data-testid="bc-form-product-name" /></Field>
        <Field label="Musim"><Input value={form.season} onChange={set('season')} placeholder="mis. SS24" /></Field>
        <Field label="Gender"><Input value={form.gender} onChange={set('gender')} placeholder="Wanita / Pria / Unisex" /></Field>
        <Field label="Upah jahit CMT (bawaan) *" hint="Bisa diubah saat membuat PO.">
          <MoneyInput value={form.default_cmt_price} onChange={set('default_cmt_price')} data-testid="bc-form-default-cmt-price" />
        </Field>
        <Field label="Harga jasa ke klien (bawaan)">
          <MoneyInput value={form.default_selling_price} onChange={set('default_selling_price')} data-testid="bc-form-default-selling-price" />
        </Field>
      </div>

      <div className="space-y-2" data-testid="bc-form-variants">
        <p className="text-sm font-semibold text-foreground">Varian & SKU</p>
        <div>
          <p className="mb-1 text-sm text-muted-foreground">Warna (dari master warna)</p>
          <div className="flex flex-wrap gap-x-4 gap-y-1.5" data-testid="bc-form-color-palette">
            {palette.map((c) => (
              <label key={c.id} className="inline-flex cursor-pointer items-center gap-1.5 text-sm" data-testid={`bc-color-chip-${c.code}`}>
                <Checkbox checked={form.color_options.includes(c.name)} onCheckedChange={() => toggleIn('color_options', c.name)} />
                {/* warna contoh dari master warna (data), bukan warna tampilan */}
                <span className="h-3 w-3 rounded-full border border-[var(--glass-border)]" style={{ backgroundColor: c.hex }} />
                {c.name} <span className="text-xs tabular-nums text-muted-foreground">{c.code}</span>
              </label>
            ))}
            {legacyColors.map((n) => (
              <label key={n} className="inline-flex cursor-pointer items-center gap-1.5 text-sm text-[hsl(var(--warning-text))]" title="Opsi lama — belum ada di master warna">
                <Checkbox checked onCheckedChange={() => toggleIn('color_options', n)} />{n} (lama)
              </label>
            ))}
          </div>
        </div>
        <div>
          <p className="mb-1 text-sm text-muted-foreground">Ukuran (dari master ukuran)</p>
          <div className="flex flex-wrap gap-x-4 gap-y-1.5" data-testid="bc-form-size-palette">
            {sizeMaster.map((s) => (
              <label key={s.id} className="inline-flex cursor-pointer items-center gap-1.5 text-sm tabular-nums" data-testid={`bc-size-chip-${s.code}`}>
                <Checkbox checked={form.size_options.includes(s.code)} onCheckedChange={() => toggleIn('size_options', s.code)} />{s.code}
              </label>
            ))}
            {legacySizes.map((c) => (
              <label key={c} className="inline-flex cursor-pointer items-center gap-1.5 text-sm text-[hsl(var(--warning-text))]" title="Opsi lama — belum ada di master ukuran">
                <Checkbox checked onCheckedChange={() => toggleIn('size_options', c)} />{c} (lama)
              </label>
            ))}
          </div>
        </div>
        <p className="text-xs text-muted-foreground" data-testid="bc-form-master-hint">
          Warna atau ukuran belum ada? Tambahkan dulu di Portal RnD › Master Produk › Warna / Ukuran.{' '}
          {onOpenRnd && <Button type="button" variant="link" size="sm" className="h-auto p-0 text-xs" onClick={onOpenRnd} data-testid="bc-form-master-link">Buka Master Produk</Button>}
        </p>
        <Notice tone="info" testId="bc-form-sku-preview"
          title={`Akan terbentuk ${skuCount} varian SKU (warna × ukuran)${exampleSku ? ` · contoh ${exampleSku}` : ''}`}>
          <label className="inline-flex cursor-pointer items-center gap-2 text-sm">
            <Checkbox checked={autoGen} onCheckedChange={(v) => setAutoGen(!!v)} data-testid="bc-form-autogen" />
            Langsung buat varian SKU setelah simpan. Kode buyer per varian bisa diisi nanti di rincian artikel.
          </label>
        </Notice>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Foto utama (alamat gambar)"><Input value={form.hero_image_url} onChange={set('hero_image_url')} placeholder="https://…" /></Field>
        <Field label="Deskripsi / spesifikasi dari buyer">
          <Textarea rows={3} value={form.description} onChange={set('description')} placeholder="Bahan, finishing, kemasan, dll." data-testid="bc-form-description" />
        </Field>
      </div>
    </FormPopup>
  );
}

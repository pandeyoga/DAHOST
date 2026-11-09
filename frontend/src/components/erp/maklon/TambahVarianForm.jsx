/**
 * TambahVarianForm — "Tambah varian" langsung dari daftar Katalog Buyer (10 Nov 2026, permintaan owner:
 * "bagaimana cara saya bisa menambah varian? harusnya di list ada tambah variannya").
 *
 * Pilih warna (master warna) dan ukuran (master ukuran) → server membuat varian SKU untuk setiap kombinasi
 * warna × ukuran yang belum ada, dan menambahkan warna/ukuran itu ke pilihan artikel. Kombinasi yang sudah ada
 * dilewati; varian nonaktif dengan kombinasi itu diaktifkan lagi.
 *
 *   POST /api/dewi/maklon/buyer-catalog/{id}/variants  { colors, sizes, buyer_ref_code }
 */
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { Search } from 'lucide-react';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { apiGet, apiPost } from '../../../lib/api';
import { Notice } from '../moduleAtoms';

const norm = (v) => String(v || '').trim().toLowerCase();

export default function TambahVarianForm({ catalog, onClose, onSaved }) {
  const [palette, setPalette] = useState([]);
  const [sizeMaster, setSizeMaster] = useState([]);
  const [colors, setColors] = useState([]);
  const [sizes, setSizes] = useState([]);
  const [ref, setRef] = useState(catalog.buyer_ref_code || '');
  const [cariWarna, setCariWarna] = useState('');   // master warna bisa >100 — wajib bisa dicari
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    Promise.all([apiGet('/rahaza/colors').catch(() => []), apiGet('/rahaza/sizes').catch(() => [])]).then(([c, s]) => {
      if (!alive) return;
      setPalette((Array.isArray(c) ? c : []).filter((x) => x.active !== false));
      setSizeMaster((Array.isArray(s) ? s : []).filter((x) => x.active !== false));
    });
    return () => { alive = false; };
  }, []);

  const existing = useMemo(() => new Map((catalog.variants || []).map((v) => [`${norm(v.color)}|${norm(v.size)}`, v])), [catalog.variants]);
  const preview = useMemo(() => {
    let baru = 0; let ada = 0; let aktifLagi = 0;
    colors.forEach((c) => sizes.forEach((s) => {
      const v = existing.get(`${norm(c)}|${norm(s)}`);
      if (!v) baru += 1; else if (v.active === false) aktifLagi += 1; else ada += 1;
    }));
    return { baru, ada, aktifLagi };
  }, [colors, sizes, existing]);
  const toggle = (setter) => (v) => setter((arr) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]));
  const paletteTampil = useMemo(() => {
    const kata = norm(cariWarna).split(/\s+/).filter(Boolean);
    if (!kata.length) return palette;
    return palette.filter((c) => kata.every((k) => `${norm(c.name)} ${norm(c.code)}`.includes(k)));
  }, [palette, cariWarna]);

  const save = async () => {
    if (!colors.length || !sizes.length) { toast.error('Pilih minimal 1 warna dan 1 ukuran'); return; }
    setSaving(true);
    try {
      const d = await apiPost(`/dewi/maklon/buyer-catalog/${catalog.id}/variants`, { colors, sizes, buyer_ref_code: ref });
      const parts = [`${(d?.created || []).length} varian baru`];
      if ((d?.reactivated || []).length) parts.push(`${d.reactivated.length} diaktifkan lagi`);
      if ((d?.skipped || []).length) parts.push(`${d.skipped.length} sudah ada`);
      toast.success(`${catalog.artikel_code}: ${parts.join(' · ')}`);
      onSaved();
    } catch (e) { toast.error(e.message || 'Gagal menambah varian'); }
    finally { setSaving(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="bc-variant-add-form" onSimpan={save} menyimpan={saving}
      judul={`Tambah varian · ${catalog.artikel_code}`} labelSimpan="Tambah varian"
      keterangan={`${catalog.product_name} — varian dibuat untuk setiap warna × ukuran yang dipilih.`}>
      <Isian label="Warna (dari master warna)" wajib
        petunjuk={colors.length ? `Dipilih: ${colors.join(', ')}` : 'Cari lalu centang satu atau beberapa warna.'}>
        <div className="relative mb-2 w-full sm:w-72">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={cariWarna} onChange={(e) => setCariWarna(e.target.value)} placeholder="Cari nama atau kode warna"
            className="pl-8" data-testid="bc-variant-add-color-search" aria-label="Cari warna" />
        </div>
        <div className="flex max-h-48 flex-wrap gap-x-4 gap-y-1.5 overflow-y-auto" data-testid="bc-variant-add-colors">
          {palette.length > 0 && !paletteTampil.length && <span className="text-sm text-muted-foreground">Tidak ada warna yang cocok.</span>}
          {paletteTampil.map((c) => (
            <label key={c.id} className="inline-flex cursor-pointer items-center gap-1.5 text-sm" data-testid={`bc-variant-add-color-${c.code}`}>
              <Checkbox checked={colors.includes(c.name)} onCheckedChange={() => toggle(setColors)(c.name)} />
              {/* warna contoh dari master warna (data), bukan warna tampilan */}
              <span className="h-3 w-3 rounded-full border border-[var(--glass-border)]" style={{ backgroundColor: c.hex }} />
              {c.name}
            </label>
          ))}
          {!palette.length && <span className="text-sm text-muted-foreground">Memuat master warna…</span>}
        </div>
      </Isian>
      <Isian label="Ukuran (dari master ukuran)" wajib>
        <div className="flex flex-wrap gap-x-4 gap-y-1.5" data-testid="bc-variant-add-sizes">
          {sizeMaster.map((s) => (
            <label key={s.id} className="inline-flex cursor-pointer items-center gap-1.5 text-sm tabular-nums" data-testid={`bc-variant-add-size-${s.code}`}>
              <Checkbox checked={sizes.includes(s.code)} onCheckedChange={() => toggle(setSizes)(s.code)} />{s.code}
            </label>
          ))}
          {!sizeMaster.length && <span className="text-sm text-muted-foreground">Memuat master ukuran…</span>}
        </div>
      </Isian>
      <Isian label="Kode buyer untuk varian baru" htmlFor="bc-variant-add-ref" petunjuk="Bisa diubah per varian nanti.">
        <Input id="bc-variant-add-ref" value={ref} onChange={(e) => setRef(e.target.value)} data-testid="bc-variant-add-ref" />
      </Isian>
      {(colors.length > 0 && sizes.length > 0) && (
        <Notice tone="info" testId="bc-variant-add-preview"
          title={`${preview.baru} varian baru${preview.aktifLagi ? ` · ${preview.aktifLagi} diaktifkan lagi` : ''}${preview.ada ? ` · ${preview.ada} sudah ada (dilewati)` : ''}`} />
      )}
      <p className="text-xs text-muted-foreground">Warna atau ukuran belum ada? Tambahkan dulu di Portal RnD › Master Produk › Warna / Ukuran.</p>
    </FormPopup>
  );
}

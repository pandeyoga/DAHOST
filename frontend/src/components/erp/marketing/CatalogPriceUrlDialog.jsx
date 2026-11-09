/**
 * CatalogPriceUrlDialog — UNGGAH HARGA & URL DARI EXCEL (klarifikasi owner 9 Nov 2026 §D4).
 *
 * Jalur paling praktis untuk 1.300+ item: unduh daftar (katalog ini atau semua katalog yang boleh dilihat) → isi
 * Harga jual / Harga coret / URL produk per SKU per toko → unggah → PRATINJAU (berapa berubah, baris bermasalah)
 * → Terapkan. Sel kosong = tidak diubah. Item dengan URL sah bisa langsung ditandai tayang (bukti = URL item itu
 * sendiri). Hasilnya tercatat di Riwayat aksi massal dan bisa dibatalkan.
 */
import { useState } from 'react';
import { Download, FileSpreadsheet } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { EmptyState, Notice } from '../moduleAtoms';
import { alatUrl, unduh, unggah } from './catalogToolsApi';
import { toast } from 'sonner';

const rp = (n) => `Rp ${Number(n || 0).toLocaleString('id-ID')}`;
const angka = (n) => Number(n || 0).toLocaleString('id-ID');
const ubahHarga = (p) => (p ? `${rp(p[0])} → ${rp(p[1])}` : '—');

export default function CatalogPriceUrlDialog({ open, catalog, token, onClose, onDone }) {
  const [lingkup, setLingkup] = useState('katalog');   // katalog | semua
  const [berkas, setBerkas] = useState(null);
  const [tayang, setTayang] = useState(true);
  const [pratinjau, setPratinjau] = useState(null);
  const [sibuk, setSibuk] = useState(false);
  const [galat, setGalat] = useState('');

  const qs = (apply) => {
    const p = new URLSearchParams();
    if (lingkup === 'katalog' && catalog?.id) p.set('catalog_id', catalog.id);
    p.set('apply', apply ? 'true' : 'false');
    p.set('publish', tayang ? 'true' : 'false');
    return p.toString();
  };

  const unduhDaftar = async () => {
    const p = lingkup === 'katalog' && catalog?.id ? `?catalog_id=${catalog.id}` : '';
    try {
      await unduh(token, alatUrl(`/price-url/template${p}`), 'harga-url-katalog.xlsx');
    } catch (e) { toast.error(e.message, { duration: 9000 }); }
  };

  const simpan = async () => {
    if (!berkas) { setGalat('Pilih berkas Excel hasil "Unduh daftar" dulu.'); return; }
    setSibuk(true);
    setGalat('');
    try {
      if (!pratinjau) {
        setPratinjau(await unggah(token, alatUrl(`/price-url/upload?${qs(false)}`), berkas));
      } else {
        const b = await unggah(token, alatUrl(`/price-url/upload?${qs(true)}`), berkas);
        if (!b.summary?.changes) toast.info(b.message);
        onDone?.(b);
      }
    } catch (e) { setGalat(e.message); } finally { setSibuk(false); }
  };

  const ganti = (fn) => (...a) => { setPratinjau(null); setGalat(''); fn(...a); };
  const s = pratinjau?.summary || {};
  const bisa = !!berkas && (!pratinjau || s.changes > 0);
  const label = !pratinjau ? 'Periksa berkas' : `Terapkan ${angka(s.changes)} perubahan`;

  return (
    <FormPopup open={open} onClose={onClose} ukuran="panjang" onSimpan={simpan} menyimpan={sibuk} galat={galat}
      bisaSimpan={bisa} labelSimpan={label} judul="Unggah harga & URL dari Excel" testId="price-url-dialog"
      keterangan="Unduh daftar, isi kolom berwarna (harga jual, harga coret, URL produk), lalu unggah. Sel kosong tidak diubah.">
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Daftar yang diunduh" htmlFor="pu-lingkup">
          <SmartNativeSelect id="pu-lingkup" className="w-full" value={lingkup} data-testid="price-url-scope"
            onChange={ganti((e) => setLingkup(e.target.value))}>
            <option value="katalog">{`Katalog ini (${catalog?.name || '—'})`}</option>
            <option value="semua">Semua katalog toko yang boleh saya ubah</option>
          </SmartNativeSelect>
        </Isian>
        <Isian label="Langkah 1">
          <Button type="button" variant="outline" className="w-full" onClick={unduhDaftar} data-testid="price-url-download">
            <Download />Unduh daftar
          </Button>
        </Isian>
      </div>
      <Isian label="Langkah 2 — berkas yang sudah diisi" htmlFor="pu-berkas" wajib
        petunjuk="Excel (.xlsx) dari Unduh daftar. Baris dicocokkan lewat kolom ID item; tanpa ID: Toko + SKU.">
        <Input id="pu-berkas" type="file" accept=".xlsx" data-testid="price-url-file"
          onChange={ganti((e) => setBerkas(e.target.files?.[0] || null))} />
      </Isian>
      <label className="flex items-start gap-2 text-sm" htmlFor="pu-tayang">
        <Checkbox id="pu-tayang" checked={tayang} onCheckedChange={ganti((v) => setTayang(!!v))} data-testid="price-url-publish" />
        <span>Tandai tayang item yang URL produknya sah (item yang diarsipkan atau nonaktif tidak ditayangkan).</span>
      </label>

      {pratinjau && (
        <section className="space-y-3" data-testid="price-url-preview">
          <Notice tone={s.changes ? 'info' : 'warning'} icon={FileSpreadsheet} title={pratinjau.message}>
            {angka(s.price)} harga jual · {angka(s.coret)} harga coret · {angka(s.url)} URL · {angka(s.publish)} ditandai tayang.
            Bisa dibatalkan sesudahnya dari Riwayat aksi massal.
          </Notice>
          {(pratinjau.errors || []).length > 0 && (
            <div className="space-y-1" data-testid="price-url-errors">
              <p className="text-sm font-medium text-[hsl(var(--danger-text))]">{angka(s.errors)} baris tidak dipakai:</p>
              <ul className="max-h-32 list-disc space-y-0.5 overflow-y-auto pl-5 text-sm text-muted-foreground">
                {pratinjau.errors.slice(0, 30).map((e) => <li key={e}>{e}</li>)}
              </ul>
            </div>
          )}
          <TabelData baris={pratinjau.sample || []} kunci={(r) => `${r.row}-${r.sku}`} testId="price-url-sample"
            kolom={[
              { kunci: 'sku', label: 'SKU', hp: 'judul', isi: (r) => (
                <div className="min-w-0"><p className="font-medium">{r.sku}</p><p className="text-xs text-muted-foreground">{r.katalog}</p></div>) },
              { kunci: 'jual', label: 'Harga jual', rata: 'kanan', isi: (r) => <span className="tabular-nums">{ubahHarga(r.harga_jual)}</span> },
              { kunci: 'coret', label: 'Harga coret', rata: 'kanan', isi: (r) => <span className="tabular-nums">{ubahHarga(r.harga_coret)}</span> },
              { kunci: 'url', label: 'URL', isi: (r) => (r.url ? <span className="break-all text-xs">{r.url}</span> : '—') },
              { kunci: 'tayang', label: 'Tayang', isi: (r) => (r.tayang ? 'Ya' : '—') },
            ]}
            kosong={<EmptyState title="Tidak ada perubahan" description="Semua baris sama dengan data sekarang atau bermasalah." />} />
          {s.changes > (pratinjau.sample || []).length && (
            <p className="text-xs text-muted-foreground">Menampilkan {angka((pratinjau.sample || []).length)} contoh dari {angka(s.changes)} perubahan.</p>
          )}
        </section>
      )}
    </FormPopup>
  );
}

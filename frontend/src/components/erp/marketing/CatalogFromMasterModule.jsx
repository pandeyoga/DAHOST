/**
 * CatalogFromMasterModule — ISI KATALOG TOKO DARI MASTER PRODUK INTERNAL (tab di Manajemen Katalog).
 *
 * KENAPA LAYAR INI ADA
 * --------------------
 * Jalur lama hanya bisa menambah **satu varian ke satu katalog** per aksi. Untuk banyak toko × puluhan varian itu
 * ratusan klik — yang terjadi di lapangan: **katalog dibiarkan kosong**, sehingga item pesanan hasil impor
 * tidak bisa ditautkan ke master dan **HPP / marjin per pesanan tidak bisa dihitung**.
 *
 * 11 Nov 2026 (owner: "saya tidak bisa lihat apa yang sudah ada di toko mana yang belum") — MATRIKS PRODUK × TOKO:
 *  • satu kolom per toko aktif: ✓ n/n (semua varian yang dijual sudah ada), n/t (sebagian), — (belum ada);
 *    varian berstatus produk Stop/Dead tidak dihitung (memang tidak ditambahkan, keputusan D7);
 *  • toko tujuan dicentang langsung di kepala kolomnya (di HP lewat tombol "Toko tujuan");
 *  • penyaring Belum lengkap / Lengkap / Semua dihitung terhadap toko tujuan (tanpa tujuan: semua toko);
 *  • centang beberapa produk/varian → satu tombol; hanya pasangan varian–toko yang belum ada yang dikirim,
 *    per toko dan bertahap (kemajuan tampil di tombol popup);
 *  • semua model dimuat (dulu 60 pertama saja) dan unduhan berisi matriks lengkap.
 * Sumber "sudah ada" = `GET /master-products?coverage=true` (aturan yang sama dengan pemeriksaan kembar di server).
 *
 * Alur: centang toko tujuan → centang produk/varian → "Tambahkan ke katalog" (popup: harga awal + batas
 * peringatan stok). HPP, kategori, berat, dan harga resmi SELALU dibawa dari master.
 */
import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import { Check, CheckCircle2, PackagePlus, RefreshCw, Search, Store } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { Skeleton } from '@/components/ui/skeleton';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import {
  DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { Toolbar, RowDetail, RowToggle } from '../layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';
import { productStatusLabel, productStatusTone } from '@/lib/productStatus';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';

const API = process.env.REACT_APP_BACKEND_URL || '';
const rp = (n) => `Rp ${Number(n || 0).toLocaleString('id-ID')}`;
const angka = (n) => Number(n || 0).toLocaleString('id-ID');
const PLATFORM_LABEL = { shopee: 'Shopee', tiktok: 'TikTok', tokopedia: 'Tokopedia', lazada: 'Lazada', blibli: 'Blibli' };
const labelPlatform = (p) => PLATFORM_LABEL[String(p || '').toLowerCase()] || p || '';
const STOP_DEAD = ['stop', 'dead'];
const dijual = (v) => !STOP_DEAD.includes(v.product_status);
const TANPA_KATEGORI = '__tanpa__';
const PER_KIRIM = 300;          // varian per permintaan (satu toko bisa ratusan varian — dikirim bertahap)
const KOLOM_TETAP = 5;          // panah · centang · produk · kategori · varian
const SEL_TUJUAN = 'bg-primary/[0.07]';

// "Shopee GHS" → "GHS" (nama platform sudah tampil di baris bawahnya)
const namaPendek = (a) => {
  const nama = String(a.account_name || a.account_code || '').trim();
  const pf = labelPlatform(a.platform);
  return pf && nama.toLowerCase().startsWith(`${pf.toLowerCase()} `) ? nama.slice(pf.length + 1) : nama;
};
const pesanGalat = (d, cadangan) => (typeof d === 'string' && d ? d : cadangan);

/** Siapkan data sekali setelah dimuat: himpunan toko per varian + jumlah varian dijual yang sudah ada per toko. */
const siapkan = (products) => products.map((p) => {
  const variants = (p.variants || []).map((v) => ({
    ...v, model_id: p.model_id, ada: new Set(v.in_accounts || []), lama: new Set(v.hidden_accounts || []),
  }));
  const ada = {};
  variants.filter(dijual).forEach((v) => v.ada.forEach((a) => { ada[a] = (ada[a] || 0) + 1; }));
  const cari = [p.name, p.code, p.category_name, ...variants.map((v) => `${v.code} ${v.color} ${v.size_code}`)]
    .join(' ').toLowerCase();
  return { ...p, variants, jual: variants.filter(dijual).length, ada, cari };
});

/** Isi satu sel toko: ✓ n/n hijau · n/t kuning · — abu. */
function Cakupan({ n, t, total, testId }) {
  if (t === 0) {
    return (
      <span className="text-muted-foreground" data-testid={testId}
        title={total ? 'Semua varian berstatus Stop/Dead' : 'Belum punya varian barang jadi'}>·</span>
    );
  }
  if (n >= t) {
    return (
      <span className="inline-flex items-center gap-0.5 font-medium tabular-nums text-[hsl(var(--success-text))]"
        title="Semua varian yang dijual sudah ada" data-testid={testId}>
        <Check className="h-3.5 w-3.5" aria-hidden="true" />{n}/{t}
      </span>
    );
  }
  if (!n) return <span className="text-muted-foreground" title="Belum ada" data-testid={testId}>—</span>;
  return (
    <span className="font-medium tabular-nums text-[hsl(var(--warning-text))]" title={`${n} dari ${t} varian sudah ada`}
      data-testid={testId}>{n}/{t}</span>
  );
}

export default function CatalogFromMasterModule({ token, onAssigned }) {
  const [q, setQ] = useState('');
  const [kategori, setKategori] = useState('');
  const [saring, setSaring] = useState('belum');          // 'belum' | 'lengkap' | '' (semua)
  const [products, setProducts] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [lebihBanyak, setLebihBanyak] = useState(false);
  const [loading, setLoading] = useState(true);
  const [target, setTarget] = useState({});              // account_id → true (toko tujuan)
  const [picked, setPicked] = useState({});              // fg_material_id → true
  const [open, setOpen] = useState({});                  // model_id → terbuka
  const [busy, setBusy] = useState(false);
  const [kemajuan, setKemajuan] = useState(null);        // { ke, dari } saat mengirim per toko
  const [result, setResult] = useState(null);
  const [priceMode, setPriceMode] = useState('master');  // 'master' | 'kosong'
  const [alertQty, setAlertQty] = useState('10');
  const [ikutStopDead, setIkutStopDead] = useState(false);   // D7 — bawaan: SKU Stop/Dead dilewati
  const [formBuka, setFormBuka] = useState(false);
  const [galat, setGalat] = useState('');

  const headers = useMemo(
    () => ({ Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` }), [token]);
  const jsonHeaders = useMemo(
    () => ({ ...headers, 'Content-Type': 'application/json' }), [headers]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/marketing/catalogs/master-products?coverage=true&limit=1000`, { headers });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(pesanGalat(b.detail, 'Gagal memuat master produk'));
      setProducts(siapkan(b.products || []));
      setAccounts(b.accounts || []);
      setLebihBanyak(!!b.more);
    } catch (e) {
      toast.error(e.message, { duration: 9000 });
      setProducts([]);
    } finally { setLoading(false); }
  }, [headers]);

  useEffect(() => { load(); }, [load]);

  // ── toko tujuan & cakupan ──────────────────────────────────────────────────────────────────────────
  const tujuan = useMemo(() => accounts.filter((a) => target[a.id]), [accounts, target]);
  // Toko yang dinilai untuk "lengkap/belum": toko tujuan, atau semua toko bila belum ada tujuan.
  const dinilai = useMemo(() => (tujuan.length ? tujuan : accounts).map((a) => a.id), [tujuan, accounts]);
  const statusProduk = useCallback((p) => {
    if (!p.jual || !dinilai.length) return 'lain';
    return dinilai.every((a) => (p.ada[a] || 0) >= p.jual) ? 'lengkap' : 'belum';
  }, [dinilai]);
  const kurangDi = useCallback((v) => dinilai.some((a) => !v.ada.has(a)), [dinilai]);
  // Varian yang ikut tercentang saat produknya dicentang: dijual (bukan Stop/Dead) dan belum ada di salah satu toko.
  const layak = useCallback((p) => p.variants.filter((v) => dijual(v) && kurangDi(v)), [kurangDi]);

  const totalToko = useMemo(() => {
    const t = { jual: 0 };
    products.forEach((p) => {
      t.jual += p.jual;
      Object.entries(p.ada).forEach(([a, n]) => { t[a] = (t[a] || 0) + n; });
    });
    return t;
  }, [products]);

  // ── penyaring ─────────────────────────────────────────────────────────────────────────────────────
  const daftarKategori = useMemo(
    () => [...new Set(products.map((p) => p.category_name).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'id')),
    [products]);
  const adaTanpaKategori = products.some((p) => !p.category_name);
  const dasar = useMemo(() => {
    const kata = q.trim().toLowerCase().split(/\s+/).filter(Boolean);
    return products.filter((p) => (!kategori || (kategori === TANPA_KATEGORI ? !p.category_name : p.category_name === kategori))
      && kata.every((w) => p.cari.includes(w)));
  }, [products, q, kategori]);
  const hitung = useMemo(() => {
    const c = { belum: 0, lengkap: 0 };
    dasar.forEach((p) => { const s = statusProduk(p); if (s in c) c[s] += 1; });
    return c;
  }, [dasar, statusProduk]);
  const saringAktif = accounts.length ? saring : '';
  const tampil = useMemo(
    () => (saringAktif ? dasar.filter((p) => statusProduk(p) === saringAktif) : dasar), [dasar, saringAktif, statusProduk]);
  const pg = useClientPagination(tampil, 25);

  // ── pilihan varian ────────────────────────────────────────────────────────────────────────────────
  const varianById = useMemo(() => {
    const m = {};
    products.forEach((p) => p.variants.forEach((v) => { m[v.fg_material_id] = v; }));
    return m;
  }, [products]);
  const dipilih = useMemo(
    () => Object.keys(picked).filter((k) => picked[k] && varianById[k]).map((k) => varianById[k]), [picked, varianById]);
  const produkDipilih = new Set(dipilih.map((v) => v.model_id)).size;
  const dipilihStopDead = dipilih.filter((v) => !dijual(v)).length;
  const itemBaru = tujuan.reduce(
    (t, a) => t + dipilih.filter((v) => !v.ada.has(a.id) && (ikutStopDead || dijual(v))).length, 0);

  const adaYangDipilih = (p) => p.variants.some((v) => picked[v.fg_material_id]);
  const centangProduk = (p) => {
    const l = layak(p);
    if (l.length && l.every((v) => picked[v.fg_material_id])) return true;
    return adaYangDipilih(p) ? 'indeterminate' : false;
  };
  const ubahProduk = (daftar, on) => setPicked((prev) => {
    const n = { ...prev };
    daftar.forEach((p) => {
      if (on) layak(p).forEach((v) => { n[v.fg_material_id] = true; });
      else p.variants.forEach((v) => { delete n[v.fg_material_id]; });
    });
    return n;
  });
  const semuaLayak = useMemo(() => tampil.flatMap(layak), [tampil, layak]);
  const centangSemua = semuaLayak.length && semuaLayak.every((v) => picked[v.fg_material_id])
    ? true : (tampil.some(adaYangDipilih) ? 'indeterminate' : false);
  const ubahVarian = (v, on) => setPicked((pf) => {
    const n = { ...pf };
    if (on) n[v.fg_material_id] = true; else delete n[v.fg_material_id];
    return n;
  });
  const ubahTujuan = (id, on) => setTarget((t) => ({ ...t, [id]: !!on }));

  // ── simpan ────────────────────────────────────────────────────────────────────────────────────────
  const bukaForm = () => {
    if (!tujuan.length) { toast.error('Centang dulu toko tujuannya di kepala kolom toko'); return; }
    if (!dipilih.length) { toast.error('Centang dulu produk atau varian yang akan ditambahkan'); return; }
    if (!itemBaru && !dipilihStopDead) { toast.info('Semua varian yang dicentang sudah ada di toko tujuan'); return; }
    setGalat('');
    setFormBuka(true);
  };

  const submit = async () => {
    setBusy(true);
    setGalat('');
    setResult(null);
    const hasil = [];
    let gagal = '';
    try {
      for (let i = 0; i < tujuan.length; i += 1) {
        const a = tujuan[i];
        setKemajuan({ ke: i + 1, dari: tujuan.length });
        // Hanya yang BELUM ada di toko ini yang dikirim; server tetap memeriksa ulang (idempoten).
        const kurang = dipilih.filter((v) => !v.ada.has(a.id)).map((v) => v.fg_material_id);
        const baris = {
          account_id: a.id, account_name: a.account_name, catalog_created: false,
          created: 0, skipped: dipilih.length - kurang.length, rejected: 0, skipped_status: 0, ditolak: [],
        };
        for (let j = 0; j < kurang.length; j += PER_KIRIM) {
          const r = await fetch(`${API}/api/marketing/catalogs/assign-from-master`, {
            method: 'POST',
            headers: jsonHeaders,
            body: JSON.stringify({
              account_ids: [a.id],
              fg_material_ids: kurang.slice(j, j + PER_KIRIM),
              price_mode: priceMode,
              stock_alert_threshold: Number(alertQty) >= 0 ? Number(alertQty) : 10,
              include_stop_dead: ikutStopDead,
            }),
          });
          const b = await r.json().catch(() => ({}));
          if (!r.ok) throw new Error(`${a.account_name}: ${pesanGalat(b.detail, 'gagal mengisi katalog')}`);
          const x = (b.results || [])[0] || {};
          baris.catalog_created = baris.catalog_created || !!x.catalog_created;
          baris.created += Number(x.created || 0);
          baris.skipped += Number(x.skipped || 0);
          baris.rejected += Number(x.rejected || 0);
          baris.skipped_status += Number(x.skipped_status || 0);
          baris.ditolak.push(...(x.notes || []).filter((n) => n.action === 'ditolak').map((n) => n.why));
        }
        hasil.push(baris);
      }
    } catch (e) {
      gagal = e.message;
    }
    setKemajuan(null);
    if (hasil.length) {
      const jml = (k) => hasil.reduce((t, r) => t + r[k], 0);
      const pesan = `${angka(jml('created'))} item katalog dibuat di ${hasil.length} toko`
        + (jml('skipped') ? `, ${angka(jml('skipped'))} sudah ada` : '')
        + (jml('rejected') ? `, ${angka(jml('rejected'))} ditolak` : '')
        + (jml('skipped_status') ? `, ${angka(jml('skipped_status'))} dilewati karena Stop/Dead` : '')
        + '. HPP & harga resmi diambil dari master.';
      setResult({ message: pesan, rows: hasil });
      if (!gagal) toast.success(pesan, { duration: 10000 });
      load();
      onAssigned?.();
    }
    if (gagal) {
      setGalat(`${gagal}.${hasil.length ? ' Toko sebelumnya sudah terisi — tekan Tambahkan lagi untuk sisanya.' : ''}`);
    } else {
      setPicked({});
      setFormBuka(false);
    }
    setBusy(false);
  };

  const ditolak = (result?.rows || []).flatMap((r) => r.ditolak.map((why) => `${r.account_name}: ${why}`));
  const dilewatiStatus = (result?.rows || []).reduce((t, r) => t + r.skipped_status, 0);
  const jumlahKolom = KOLOM_TETAP + accounts.length + 1;
  const ringkasTujuan = tujuan.map((a) => `${namaPendek(a)} (${labelPlatform(a.platform)})`).join(', ');

  const pemilihTokoHp = (
    <div className="w-full sm:w-auto md:hidden">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" className="w-full justify-start sm:w-56" data-testid="cfm-stores">
            <Store />
            <span className="truncate">{tujuan.length ? `Toko tujuan: ${tujuan.length} dipilih` : 'Toko tujuan'}</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-72">
          <DropdownMenuLabel>Toko tujuan</DropdownMenuLabel>
          <DropdownMenuItem onSelect={(e) => { e.preventDefault(); setTarget(Object.fromEntries(accounts.map((a) => [a.id, true]))); }}
            data-testid="cfm-all-stores">Pilih semua toko</DropdownMenuItem>
          <DropdownMenuItem onSelect={(e) => { e.preventDefault(); setTarget({}); }}>Kosongkan pilihan</DropdownMenuItem>
          <DropdownMenuSeparator />
          {accounts.length === 0 && <DropdownMenuItem disabled>Belum ada toko aktif</DropdownMenuItem>}
          {accounts.map((a) => (
            <DropdownMenuCheckboxItem key={a.id} checked={!!target[a.id]}
              onSelect={(e) => e.preventDefault()} onCheckedChange={(v) => ubahTujuan(a.id, v)}
              data-testid={`cfm-store-${a.account_code}`}>
              {a.account_name}
              <span className="ml-auto pl-2 text-xs tabular-nums text-muted-foreground">
                {angka(totalToko[a.id])}/{angka(totalToko.jual)}
              </span>
            </DropdownMenuCheckboxItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );

  return (
    <div className="space-y-4" data-testid="catalog-from-master-module">
      <Toolbar
        filters={<>
          <div className="relative w-full sm:w-56">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} className="pl-8"
              placeholder="Cari kode, nama, warna" data-testid="cfm-search" />
          </div>
          <SmartNativeSelect value={kategori} onChange={(e) => setKategori(e.target.value)}
            className="w-full" wrapperClassName="w-full sm:w-40" aria-label="Kategori" data-testid="cfm-category">
            <option value="">Semua kategori</option>
            {daftarKategori.map((k) => <option key={k} value={k}>{k}</option>)}
            {adaTanpaKategori && <option value={TANPA_KATEGORI}>Tanpa kategori</option>}
          </SmartNativeSelect>
          {pemilihTokoHp}
          {accounts.length > 0 && (
            <FilterChips value={saring} onChange={setSaring} testId="cfm-filter" ariaLabel="Kelengkapan di toko"
              hideWhenEmpty={false}
              options={[
                { key: 'belum', label: 'Belum lengkap', count: hitung.belum },
                { key: 'lengkap', label: 'Lengkap', count: hitung.lengkap },
                { key: '', label: 'Semua', count: dasar.length },
              ]} />
          )}
        </>}
        tools={<>
          <TombolUnduh namaBerkas="isi-katalog-per-toko" namaLembar="Produk per toko" testId="cfm-unduh"
            baris={tampil} ambilSemua={async () => tampil.flatMap((p) => (p.variants.length ? p.variants : [null])
              .map((v) => ({ p, v })))}
            kolom={[
              { label: 'Kode model', nilai: ({ p }) => p.code },
              { label: 'Nama', nilai: ({ p }) => p.name },
              { label: 'Kategori', nilai: ({ p }) => p.category_name || '' },
              { label: 'Kode varian', nilai: ({ v }) => v?.code || '' },
              { label: 'Warna', nilai: ({ v }) => v?.color || '' },
              { label: 'Ukuran', nilai: ({ v }) => v?.size_code || '' },
              { label: 'Status produk', nilai: ({ v }) => (v?.product_status ? productStatusLabel(v.product_status) : '') },
              { label: 'Stok jual', nilai: ({ v }) => (v ? Number(v.sellable_stock || 0) : '') },
              { label: 'HPP varian', nilai: ({ v }) => (v ? Number(v.hpp || 0) : '') },
              { label: 'Harga resmi SKU', nilai: ({ v }) => (v ? Number(v.retail_price_master || 0) : '') },
              ...accounts.map((a) => ({
                label: a.account_name,
                nilai: ({ v }) => (!v ? '' : !v.ada.has(a.id) ? 'Belum' : v.lama.has(a.id) ? 'Ada (item lama)' : 'Ada'),
              })),
            ]} />
          <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
            data-testid="cfm-refresh">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
          <Button onClick={bukaForm} disabled={busy || !dipilih.length || !tujuan.length} data-testid="cfm-submit">
            <PackagePlus />Tambahkan ke katalog
          </Button>
        </>} />

      <p className="text-sm text-muted-foreground" data-testid="cfm-selection-summary">
        {!accounts.length ? 'Belum ada toko aktif yang bisa Anda isi katalognya.'
          : !tujuan.length ? (<>
            <span className="md:hidden">Pilih toko lewat tombol "Toko tujuan". Kolom Lengkap = jumlah toko yang sudah memuat semua varian yang dijual.</span>
            <span className="hidden md:inline">Centang toko di kepala kolom untuk memilih toko tujuan. Angka toko = varian yang sudah ada dari varian yang dijual (tanpa Stop/Dead).</span>
          </>)
            : (<>
              Toko tujuan: <b className="text-foreground">{ringkasTujuan}</b>
              {' · '}<b className="text-foreground">{angka(produkDipilih)}</b> produk (<b className="text-foreground">{angka(dipilih.length)}</b> varian) dicentang
              {dipilih.length
                ? <> → <b className="text-foreground" data-testid="cfm-new-count">{angka(itemBaru)}</b> item baru; yang sudah ada dilewati.</>
                : '.'}
            </>)}
      </p>

      {lebihBanyak && (
        <Notice tone="warning" title="Daftar dibatasi 1.000 produk pertama">
          Persempit dengan pencarian atau kategori supaya produk lainnya tampil.
        </Notice>
      )}

      {result && (
        <section className="space-y-2" data-testid="cfm-result">
          <Notice tone="success" icon={CheckCircle2} title={result.message}
            action={(
              <TombolUnduh namaBerkas="hasil-isi-katalog" namaLembar="Hasil" baris={result.rows} testId="cfm-result-unduh"
                kolom={[
                  { label: 'Toko', nilai: (r) => r.account_name },
                  { label: 'Katalog baru dibuat', nilai: (r) => (r.catalog_created ? 'Ya' : 'Tidak') },
                  { label: 'Baru', nilai: (r) => r.created }, { label: 'Sudah ada', nilai: (r) => r.skipped },
                  { label: 'Ditolak', nilai: (r) => r.rejected },
                  { label: 'Dilewati (Stop/Dead)', nilai: (r) => r.skipped_status },
                ]} />
            )} />
          <TabelData baris={result.rows} kunci={(r) => r.account_id} testId="cfm-result-table"
            kolom={[
              { kunci: 'toko', label: 'Toko', hp: 'judul', isi: (r) => (
                <span>{r.account_name}{r.catalog_created && <> <StatusBadge status="baru" label="Katalog baru dibuat" tone="info" /></>}</span>) },
              { kunci: 'baru', label: 'Baru', rata: 'kanan', isi: (r) => <span className="tabular-nums">{angka(r.created)}</span> },
              { kunci: 'ada', label: 'Sudah ada', rata: 'kanan', isi: (r) => <span className="tabular-nums">{angka(r.skipped)}</span> },
              { kunci: 'tolak', label: 'Ditolak', rata: 'kanan', isi: (r) => (
                <span className={`tabular-nums ${r.rejected ? 'font-medium text-[hsl(var(--danger-text))]' : ''}`}>{angka(r.rejected)}</span>) },
              { kunci: 'status', label: 'Dilewati (Stop/Dead)', rata: 'kanan', isi: (r) => <span className="tabular-nums">{angka(r.skipped_status)}</span> },
            ]} />
          {dilewatiStatus > 0 && (
            <p className="text-sm text-muted-foreground" data-testid="cfm-skipped-status">
              {angka(dilewatiStatus)} varian tidak ditambahkan karena status produknya Stop/Dead. Centang "Tetap tambahkan" di popup bila memang dijual.
            </p>
          )}
          {ditolak.length > 0 && (
            <ul className="space-y-0.5 text-sm text-[hsl(var(--danger-text))]">
              {ditolak.slice(0, 50).map((t, i) => <li key={i}>{t}</li>)}
            </ul>
          )}
        </section>
      )}

      {loading && !products.length ? (
        <div className="space-y-2">{[1, 2, 3].map((i) => <Skeleton key={i} className="h-12" />)}</div>
      ) : (
        <div data-testid="cfm-product-list">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8" />
                <TableHead className="w-8">
                  <Checkbox checked={centangSemua} disabled={!semuaLayak.length && centangSemua === false}
                    onCheckedChange={(v) => ubahProduk(tampil, v === true)}
                    aria-label="Centang semua produk yang tampil (semua halaman)" title="Centang semua produk yang tampil (semua halaman)"
                    data-testid="cfm-select-all" />
                </TableHead>
                <TableHead>Produk</TableHead>
                <TableHead className="hidden xl:table-cell">Kategori</TableHead>
                <TableHead className="hidden text-right sm:table-cell">Varian</TableHead>
                {accounts.map((a) => (
                  <TableHead key={a.id} className={cn('hidden w-24 px-1 text-center align-bottom md:table-cell', target[a.id] && SEL_TUJUAN)}>
                    <label className="flex cursor-pointer flex-col items-center gap-0.5 py-1" title={`${a.account_name} — centang untuk dijadikan toko tujuan`}>
                      <Checkbox checked={!!target[a.id]} onCheckedChange={(v) => ubahTujuan(a.id, v)}
                        aria-label={`Jadikan ${a.account_name} toko tujuan`} data-testid={`cfm-target-${a.account_code}`} />
                      <span className="leading-tight text-foreground">{namaPendek(a)}</span>
                      <span className="font-normal leading-tight">{labelPlatform(a.platform)}</span>
                      <span className="font-normal tabular-nums leading-tight" data-testid={`cfm-store-total-${a.account_code}`}>
                        {angka(totalToko[a.id])}/{angka(totalToko.jual)}
                      </span>
                    </label>
                  </TableHead>
                ))}
                <TableHead className="text-right md:hidden">Lengkap</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tampil.length === 0 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={jumlahKolom} className="p-0 [&>div]:py-8">
                    {products.length > 0 && saringAktif === 'belum' && !q && !kategori ? (
                      <EmptyState icon={CheckCircle2} testId="cfm-empty"
                        title={tujuan.length ? 'Semua produk sudah lengkap di toko tujuan' : 'Semua produk sudah lengkap di semua toko'}
                        description='Pilih "Semua" untuk melihat seluruh produk.' />
                    ) : (
                      <EmptyState icon={PackagePlus} title="Belum ada produk master yang cocok" testId="cfm-empty"
                        description="Master produk (model + varian barang jadi) dibuat di R&D / Master Produk — katalog toko hanya menempelkan produk yang sudah ada di sana." />
                    )}
                  </TableCell>
                </TableRow>
              )}
              {pg.paged.map((p) => {
                const expanded = !!open[p.model_id];
                const centang = centangProduk(p);
                const lengkapDi = dinilai.filter((a) => p.jual && (p.ada[a] || 0) >= p.jual).length;
                return (
                  <Fragment key={p.model_id}>
                    <TableRow data-testid={`cfm-row-${p.code}`}>
                      <TableCell>
                        <RowToggle open={expanded} onClick={() => setOpen((o) => ({ ...o, [p.model_id]: !expanded }))}
                          label="Lihat varian" testId={`cfm-toggle-${p.code}`} />
                      </TableCell>
                      <TableCell>
                        <Checkbox checked={centang} disabled={!layak(p).length && centang === false}
                          aria-label={`Centang varian ${p.name} yang belum ada`}
                          onCheckedChange={(v) => ubahProduk([p], v === true)} data-testid={`cfm-model-${p.code}`} />
                      </TableCell>
                      <TableCell>
                        <p className="font-medium">{p.name}</p>
                        <p className="text-xs text-muted-foreground">
                          {p.code}<span className="hidden sm:inline xl:hidden"> · {p.category_name || 'tanpa kategori'}</span>
                          <span className="sm:hidden"> · {angka(p.variant_count)} varian</span>
                          {p.hpp === 0 && <> <StatusBadge status="belum" label="HPP belum ada" tone="warning" /></>}
                        </p>
                      </TableCell>
                      <TableCell className="hidden xl:table-cell">{p.category_name || <span className="text-muted-foreground">Tanpa kategori</span>}</TableCell>
                      <TableCell className="hidden text-right tabular-nums sm:table-cell">
                        {angka(p.variant_count)}
                        {p.variant_count > p.jual && (
                          <span className="block text-xs text-muted-foreground">{angka(p.variant_count - p.jual)} Stop/Dead</span>
                        )}
                      </TableCell>
                      {accounts.map((a) => (
                        <TableCell key={a.id} className={cn('hidden px-1 text-center md:table-cell', target[a.id] && SEL_TUJUAN)}>
                          <Cakupan n={p.ada[a.id] || 0} t={p.jual} total={p.variants.length}
                            testId={`cfm-cov-${p.code}-${a.account_code}`} />
                        </TableCell>
                      ))}
                      <TableCell className="text-right text-sm md:hidden">
                        {!p.jual ? <span className="text-muted-foreground">{p.variants.length ? 'Stop/Dead' : '—'}</span>
                          : (
                            <span title={`Lengkap di ${lengkapDi} dari ${dinilai.length} toko`}
                              className={cn('tabular-nums', lengkapDi === dinilai.length ? 'text-[hsl(var(--success-text))]'
                                : lengkapDi ? 'text-[hsl(var(--warning-text))]' : 'text-muted-foreground')}>
                              {lengkapDi}/{dinilai.length}
                            </span>
                          )}
                      </TableCell>
                    </TableRow>
                    {expanded && (
                      <RowDetail colSpan={jumlahKolom} testId={`cfm-variants-${p.code}`}>
                        {p.variants.length === 0 ? (
                          <p className="text-sm text-muted-foreground">Model ini belum punya varian barang jadi.</p>
                        ) : (
                          <Table>
                            <TableHeader>
                              <TableRow>
                                <TableHead className="w-8" />
                                <TableHead>Varian</TableHead>
                                <TableHead>Status produk</TableHead>
                                <TableHead className="hidden text-right sm:table-cell">Stok jual</TableHead>
                                <TableHead className="hidden text-right lg:table-cell">HPP</TableHead>
                                <TableHead className="hidden text-right lg:table-cell">Harga resmi</TableHead>
                                {accounts.map((a) => (
                                  <TableHead key={a.id} className={cn('hidden px-1 text-center md:table-cell', target[a.id] && SEL_TUJUAN)}
                                    title={a.account_name}>{namaPendek(a)}</TableHead>
                                ))}
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {p.variants.map((v) => (
                                <TableRow key={v.fg_material_id}>
                                  <TableCell>
                                    <Checkbox checked={!!picked[v.fg_material_id]}
                                      disabled={!kurangDi(v) && !picked[v.fg_material_id]}
                                      aria-label={`Centang ${v.code}`} onCheckedChange={(c) => ubahVarian(v, !!c)}
                                      data-testid={`cfm-variant-${v.code}`} />
                                  </TableCell>
                                  <TableCell>
                                    <p>{v.code}</p>
                                    <p className="text-xs text-muted-foreground">{[v.color, v.size_code].filter(Boolean).join(' · ') || '—'}</p>
                                  </TableCell>
                                  <TableCell data-testid={`cfm-status-${v.code}`}>
                                    {v.product_status
                                      ? <StatusBadge status={v.product_status} label={productStatusLabel(v.product_status)} tone={productStatusTone(v.product_status)} />
                                      : <span className="text-muted-foreground">Belum diisi</span>}
                                  </TableCell>
                                  <TableCell className="hidden text-right tabular-nums sm:table-cell">
                                    {v.sellable_stock > 0 ? angka(v.sellable_stock)
                                      : <span className="text-[hsl(var(--warning-text))]">0 (habis)</span>}
                                  </TableCell>
                                  <TableCell className="hidden text-right tabular-nums lg:table-cell">{rp(v.hpp)}</TableCell>
                                  <TableCell className="hidden text-right tabular-nums lg:table-cell" data-testid={`cfm-price-${v.code}`}>
                                    {v.retail_price_master ? rp(v.retail_price_master) : <span className="text-muted-foreground">belum ada</span>}
                                    {v.retail_price_source === 'model' && <span className="block text-xs text-muted-foreground">harga model</span>}
                                  </TableCell>
                                  {accounts.map((a) => (
                                    <TableCell key={a.id} className={cn('hidden px-1 text-center md:table-cell', target[a.id] && SEL_TUJUAN)}
                                      data-testid={`cfm-vcov-${v.code}-${a.account_code}`}>
                                      {!v.ada.has(a.id) ? <span className="text-muted-foreground" title="Belum ada">—</span>
                                        : v.lama.has(a.id) ? (
                                          <span className="inline-flex text-[hsl(var(--warning-text))]"
                                            title="Ada sebagai item impor lama tanpa katalog — rapikan lewat Alat katalog › Rapikan item tersembunyi">
                                            <Check className="h-4 w-4" aria-label="Ada (item lama)" />
                                          </span>
                                        ) : (
                                          <span className="inline-flex text-[hsl(var(--success-text))]" title="Sudah ada di katalog toko ini">
                                            <Check className="h-4 w-4" aria-label="Sudah ada" />
                                          </span>
                                        )}
                                    </TableCell>
                                  ))}
                                </TableRow>
                              ))}
                            </TableBody>
                          </Table>
                        )}
                      </RowDetail>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
          <PaginationLite page={pg.page} totalPages={pg.totalPages} total={pg.total} onPageChange={pg.setPage} pageSize={25} />
        </div>
      )}

      {/* Harga jual awal & batas peringatan stok — keduanya diterima backend. Ditanyakan di popup supaya
          tidak ada keputusan diam-diam: toko yang harganya beda per kanal bisa mulai dari 0 lalu diisi per toko. */}
      <FormPopup open={formBuka} onClose={() => setFormBuka(false)} ukuran="pendek" onSimpan={submit} menyimpan={busy}
        galat={galat} judul="Tambahkan ke katalog toko" testId="cfm-form" labelSimpan="Tambahkan"
        keterangan={kemajuan
          ? `Menambahkan ke toko ${kemajuan.ke} dari ${kemajuan.dari}… jangan tutup halaman ini.`
          : `${angka(dipilih.length)} varian dicentang × ${tujuan.length} toko → ${angka(itemBaru)} item baru. Yang sudah ada di toko itu dilewati.`}>
        <Isian label="Toko tujuan">
          <p className="text-sm">{ringkasTujuan || '—'}</p>
        </Isian>
        <Isian label="Harga jual awal" htmlFor="cfm-price-mode">
          <SmartNativeSelect id="cfm-price-mode" className="w-full" value={priceMode}
            onChange={(e) => setPriceMode(e.target.value)} data-testid="cfm-price-mode">
            <option value="master">Harga resmi master (per SKU, cadangan harga model)</option>
            <option value="kosong">Kosongkan (isi per toko nanti)</option>
          </SmartNativeSelect>
        </Isian>
        <Isian label="Peringatan stok di bawah (pcs)" htmlFor="cfm-alert-qty">
          <Input id="cfm-alert-qty" type="number" min="0" step="1" value={alertQty}
            onChange={(e) => setAlertQty(e.target.value)} className="w-32" data-testid="cfm-alert-qty" />
        </Isian>
        {dipilihStopDead > 0 && (
          <label className="flex items-start gap-2 text-sm" htmlFor="cfm-stop-dead">
            <Checkbox id="cfm-stop-dead" checked={ikutStopDead} onCheckedChange={(v) => setIkutStopDead(!!v)} data-testid="cfm-include-stop-dead" />
            <span>Tetap tambahkan {angka(dipilihStopDead)} varian berstatus produk Stop/Dead yang ikut dicentang (bawaan: dilewati).</span>
          </label>
        )}
      </FormPopup>
    </div>
  );
}

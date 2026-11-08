/**
 * CatalogFromMasterModule — ISI KATALOG TOKO DARI MASTER PRODUK INTERNAL (tab di Manajemen Katalog).
 *
 * KENAPA LAYAR INI ADA
 * --------------------
 * Jalur lama hanya bisa menambah **satu varian ke satu katalog** per aksi. Untuk 9 toko × puluhan varian itu
 * ratusan klik — yang terjadi di lapangan: **katalog dibiarkan kosong**, sehingga item pesanan hasil impor
 * tidak bisa ditautkan ke master dan **HPP / marjin per pesanan tidak bisa dihitung**.
 *
 * Alur: pilih toko tujuan → centang produk/varian master → "Tambahkan ke katalog" (popup: harga awal + batas
 * peringatan stok). HPP, kategori, berat, dan harga resmi SELALU dibawa dari master.
 *
 * Standar UI/UX v2 (8 Nov 2026): penyaring satu baris (cari + pilihan toko), daftar produk = tabel dengan varian
 * di bawah barisnya (RowDetail), isian harga/batas stok di FormPopup, hasil = tabel yang bisa diunduh.
 */
import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import { PackagePlus, RefreshCw, Search, Store, CheckCircle2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { Skeleton } from '@/components/ui/skeleton';
import SmartNativeSelect from '@/components/ui/smart-native-select';
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
import { toast } from 'sonner';

const API = process.env.REACT_APP_BACKEND_URL || '';
const rp = (n) => `Rp ${Number(n || 0).toLocaleString('id-ID')}`;
const angka = (n) => Number(n || 0).toLocaleString('id-ID');
const PLATFORM_LABEL = { shopee: 'Shopee', tiktok: 'TikTok', tokopedia: 'Tokopedia', lazada: 'Lazada', blibli: 'Blibli' };
const labelPlatform = (p) => PLATFORM_LABEL[String(p || '').toLowerCase()] || p || '';

export default function CatalogFromMasterModule({ token, onAssigned }) {
  const [q, setQ] = useState('');
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [accounts, setAccounts] = useState([]);
  const [pickedFg, setPickedFg] = useState({});      // fg_material_id → true
  const [pickedAcc, setPickedAcc] = useState({});    // account_id → true
  const [open, setOpen] = useState({});              // model_id → expanded
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [priceMode, setPriceMode] = useState('master');   // 'master' | 'kosong'
  const [alertQty, setAlertQty] = useState('10');
  const [formBuka, setFormBuka] = useState(false);
  const [galat, setGalat] = useState('');
  const pg = useClientPagination(products, 25);

  const headers = useMemo(
    () => ({ Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` }), [token]);
  const jsonHeaders = useMemo(
    () => ({ ...headers, 'Content-Type': 'application/json' }), [headers]);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${API}/api/marketing/accounts?status=active`, { headers });
        const b = await r.json().catch(() => ({}));
        setAccounts(Array.isArray(b) ? b : (b.accounts || b.data || []));
      } catch { setAccounts([]); }
    })();
  }, [headers]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      if (q.trim()) qs.set('q', q.trim());
      const only = Object.keys(pickedAcc).filter((k) => pickedAcc[k]);
      if (only.length === 1) qs.set('account_id', only[0]);
      const r = await fetch(`${API}/api/marketing/catalogs/master-products?${qs}`, { headers });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(b.detail || 'Gagal memuat master produk');
      setProducts(b.products || []);
    } catch (e) {
      toast.error(e.message, { duration: 9000 });
      setProducts([]);
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [headers, q, JSON.stringify(pickedAcc)]);

  useEffect(() => { load(); }, [load]);

  const fgCount = Object.values(pickedFg).filter(Boolean).length;
  const accCount = Object.values(pickedAcc).filter(Boolean).length;
  const accNames = accounts.filter((a) => pickedAcc[a.id]).map((a) => a.account_name);

  const toggleModel = (p, on) => {
    setPickedFg((prev) => {
      const next = { ...prev };
      p.variants.forEach((v) => {
        if (on && !v.in_catalog) next[v.fg_material_id] = true;
        if (!on) delete next[v.fg_material_id];
      });
      return next;
    });
  };

  const bukaForm = () => {
    if (!accCount) { toast.error('Pilih dulu toko tujuannya'); return; }
    if (!fgCount) { toast.error('Pilih dulu produk/varian yang dijual'); return; }
    setGalat('');
    setFormBuka(true);
  };

  const submit = async () => {
    setBusy(true);
    setGalat('');
    setResult(null);
    try {
      const r = await fetch(`${API}/api/marketing/catalogs/assign-from-master`, {
        method: 'POST',
        headers: jsonHeaders,
        body: JSON.stringify({
          account_ids: Object.keys(pickedAcc).filter((k) => pickedAcc[k]),
          fg_material_ids: Object.keys(pickedFg).filter((k) => pickedFg[k]),
          price_mode: priceMode,
          stock_alert_threshold: Number(alertQty) >= 0 ? Number(alertQty) : 10,
        }),
      });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(b.detail || 'Gagal mengisi katalog');
      setResult(b);
      toast.success(b.message, { duration: 10000 });
      setPickedFg({});
      setFormBuka(false);
      load();
      onAssigned?.();
    } catch (e) {
      setGalat(e.message);
    } finally { setBusy(false); }
  };

  const ditolak = (result?.results || []).flatMap((r) => (r.notes || [])
    .filter((n) => n.action === 'ditolak').map((n) => `${r.account_name}: ${n.why}`));

  return (
    <div className="space-y-4" data-testid="catalog-from-master-module">
      <Toolbar
        filters={<>
          <div className="relative w-full sm:w-64">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} className="pl-8"
              placeholder="Cari kode, nama, kategori" data-testid="cfm-search" />
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" className="w-full justify-start sm:w-56" data-testid="cfm-stores">
                <Store />
                <span className="truncate">{accCount ? `Toko tujuan: ${accCount} dipilih` : 'Pilih toko tujuan'}</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-72">
              <DropdownMenuLabel>Toko tujuan</DropdownMenuLabel>
              <DropdownMenuItem onSelect={(e) => { e.preventDefault(); setPickedAcc(Object.fromEntries(accounts.map((a) => [a.id, true]))); }}
                data-testid="cfm-all-stores">Pilih semua toko</DropdownMenuItem>
              <DropdownMenuItem onSelect={(e) => { e.preventDefault(); setPickedAcc({}); }}>Kosongkan pilihan</DropdownMenuItem>
              <DropdownMenuSeparator />
              {accounts.length === 0 && <DropdownMenuItem disabled>Belum ada toko aktif</DropdownMenuItem>}
              {accounts.map((a) => (
                <DropdownMenuCheckboxItem key={a.id} checked={!!pickedAcc[a.id]}
                  onSelect={(e) => e.preventDefault()}
                  onCheckedChange={(v) => setPickedAcc((p) => ({ ...p, [a.id]: !!v }))}
                  data-testid={`cfm-store-${a.account_code}`}>
                  {a.account_name}<span className="ml-auto pl-2 text-xs text-muted-foreground">{labelPlatform(a.platform)}</span>
                </DropdownMenuCheckboxItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </>}
        tools={<>
          <TombolUnduh namaBerkas="master-produk-untuk-katalog" namaLembar="Master produk" testId="cfm-unduh"
            baris={products} ambilSemua={async () => products.flatMap((p) => (p.variants.length ? p.variants : [null])
              .map((v) => ({ p, v })))}
            kolom={[
              { label: 'Kode model', nilai: ({ p }) => p.code },
              { label: 'Nama', nilai: ({ p }) => p.name },
              { label: 'Kategori', nilai: ({ p }) => p.category_name || '' },
              { label: 'HPP model', nilai: ({ p }) => Number(p.hpp || 0) },
              { label: 'Harga resmi', nilai: ({ p }) => Number(p.retail_price_master || 0) },
              { label: 'Kode varian', nilai: ({ v }) => v?.code || '' },
              { label: 'Warna', nilai: ({ v }) => v?.color || '' },
              { label: 'Ukuran', nilai: ({ v }) => v?.size_code || '' },
              { label: 'HPP varian', nilai: ({ v }) => (v ? Number(v.hpp || 0) : '') },
              { label: 'Stok jual', nilai: ({ v }) => (v ? Number(v.sellable_stock || 0) : '') },
              { label: 'Sudah di katalog', nilai: ({ v }) => (v ? (v.in_catalog ? 'Ya' : 'Belum') : '') },
            ]} />
          <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
            data-testid="cfm-refresh">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
          <Button onClick={bukaForm} disabled={busy || !fgCount || !accCount} data-testid="cfm-submit">
            <PackagePlus />Tambahkan ke katalog{fgCount ? ` (${fgCount})` : ''}
          </Button>
        </>} />

      <p className="text-sm text-muted-foreground" data-testid="cfm-selection-summary">
        <b className="text-foreground">{fgCount}</b> varian × <b className="text-foreground">{accCount}</b> toko
        {fgCount && accCount ? ` = ${angka(fgCount * accCount)} item katalog akan dibuat` : ''}.
        {' '}Varian yang sudah ada di katalog dilewati. HPP, kategori, berat, dan harga resmi selalu diambil dari master.
      </p>

      {result && (
        <section className="space-y-2" data-testid="cfm-result">
          <Notice tone="success" icon={CheckCircle2} title={result.message}
            action={(
              <TombolUnduh namaBerkas="hasil-isi-katalog" namaLembar="Hasil" baris={result.results || []} testId="cfm-result-unduh"
                kolom={[
                  { label: 'Toko', nilai: (r) => r.account_name }, { label: 'Katalog', nilai: (r) => r.catalog_name },
                  { label: 'Katalog baru dibuat', nilai: (r) => (r.catalog_created ? 'Ya' : 'Tidak') },
                  { label: 'Baru', nilai: (r) => r.created || 0 }, { label: 'Sudah ada', nilai: (r) => r.skipped || 0 },
                  { label: 'Ditolak', nilai: (r) => r.rejected || 0 },
                ]} />
            )} />
          <TabelData baris={result.results || []} kunci={(r) => r.account_id} testId="cfm-result-table"
            kolom={[
              { kunci: 'toko', label: 'Toko', hp: 'judul', isi: (r) => r.account_name },
              { kunci: 'katalog', label: 'Katalog', isi: (r) => (
                <span>{r.catalog_name}{r.catalog_created && <> <StatusBadge status="baru" label="Baru dibuat" tone="info" /></>}</span>) },
              { kunci: 'baru', label: 'Baru', rata: 'kanan', isi: (r) => <span className="tabular-nums">{angka(r.created)}</span> },
              { kunci: 'ada', label: 'Sudah ada', rata: 'kanan', isi: (r) => <span className="tabular-nums">{angka(r.skipped)}</span> },
              { kunci: 'tolak', label: 'Ditolak', rata: 'kanan', isi: (r) => (
                <span className={`tabular-nums ${r.rejected ? 'font-medium text-[hsl(var(--danger-text))]' : ''}`}>{angka(r.rejected)}</span>) },
            ]} />
          {ditolak.length > 0 && (
            <ul className="space-y-0.5 text-sm text-[hsl(var(--danger-text))]">
              {ditolak.map((t, i) => <li key={i}>{t}</li>)}
            </ul>
          )}
        </section>
      )}

      {loading ? (
        <div className="space-y-2">{[1, 2, 3].map((i) => <Skeleton key={i} className="h-12" />)}</div>
      ) : products.length === 0 ? (
        <EmptyState icon={PackagePlus} title="Belum ada produk master yang cocok" testId="cfm-empty"
          description="Master produk (model + varian FG) dibuat di R&D / Master Produk — katalog toko hanya menempelkan produk yang sudah ada di sana." />
      ) : (
        <div data-testid="cfm-product-list">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8" />
                <TableHead className="w-8" />
                <TableHead>Produk</TableHead>
                <TableHead className="hidden md:table-cell">Kategori</TableHead>
                <TableHead className="text-right">HPP</TableHead>
                <TableHead className="hidden text-right md:table-cell">Harga resmi</TableHead>
                <TableHead className="text-right">Varian</TableHead>
                <TableHead className="hidden md:table-cell">Di katalog</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pg.paged.map((p) => {
                const expanded = !!open[p.model_id];
                const selectable = p.variants.filter((v) => !v.in_catalog);
                const allPicked = selectable.length > 0 && selectable.every((v) => pickedFg[v.fg_material_id]);
                return (
                  <Fragment key={p.model_id}>
                    <TableRow>
                      <TableCell>
                        <RowToggle open={expanded} onClick={() => setOpen((o) => ({ ...o, [p.model_id]: !expanded }))}
                          label="Lihat varian" testId={`cfm-toggle-${p.code}`} />
                      </TableCell>
                      <TableCell>
                        <Checkbox checked={allPicked} disabled={selectable.length === 0} aria-label={`Pilih semua varian ${p.name}`}
                          onCheckedChange={(v) => toggleModel(p, !!v)} data-testid={`cfm-model-${p.code}`} />
                      </TableCell>
                      <TableCell>
                        <p className="font-medium">{p.name}</p>
                        <p className="text-xs text-muted-foreground">{p.code}<span className="md:hidden"> · {p.category_name || 'tanpa kategori'}</span></p>
                      </TableCell>
                      <TableCell className="hidden md:table-cell">{p.category_name || <span className="text-muted-foreground">Tanpa kategori</span>}</TableCell>
                      <TableCell className="text-right">
                        {p.hpp === 0
                          ? <StatusBadge status="belum" label="HPP belum ada" tone="warning" />
                          : <span className="tabular-nums">{rp(p.hpp)}</span>}
                      </TableCell>
                      <TableCell className="hidden text-right tabular-nums md:table-cell">{p.retail_price_master ? rp(p.retail_price_master) : '—'}</TableCell>
                      <TableCell className="text-right tabular-nums">{angka(p.variant_count)}</TableCell>
                      <TableCell className="hidden md:table-cell">
                        {p.in_catalog_count > 0 ? `${angka(p.in_catalog_count)} varian` : <span className="text-muted-foreground">Belum</span>}
                      </TableCell>
                    </TableRow>
                    {expanded && (
                      <RowDetail colSpan={8} testId={`cfm-variants-${p.code}`}>
                        {p.variants.length === 0 ? (
                          <p className="text-sm text-muted-foreground">Model ini belum punya varian barang jadi.</p>
                        ) : (
                          <Table>
                            <TableHeader>
                              <TableRow>
                                <TableHead className="w-8" />
                                <TableHead>Kode varian</TableHead>
                                <TableHead>Warna</TableHead>
                                <TableHead>Ukuran</TableHead>
                                <TableHead className="text-right">HPP</TableHead>
                                <TableHead className="text-right">Stok jual</TableHead>
                                <TableHead>Status</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {p.variants.map((v) => (
                                <TableRow key={v.fg_material_id}>
                                  <TableCell>
                                    <Checkbox checked={!!pickedFg[v.fg_material_id]} disabled={v.in_catalog} aria-label={`Pilih ${v.code}`}
                                      onCheckedChange={(c) => setPickedFg((pf) => {
                                        const n = { ...pf };
                                        if (c) n[v.fg_material_id] = true; else delete n[v.fg_material_id];
                                        return n;
                                      })}
                                      data-testid={`cfm-variant-${v.code}`} />
                                  </TableCell>
                                  <TableCell>{v.code}</TableCell>
                                  <TableCell>{v.color || '—'}</TableCell>
                                  <TableCell>{v.size_code || '—'}</TableCell>
                                  <TableCell className="text-right tabular-nums">{rp(v.hpp)}</TableCell>
                                  <TableCell className="text-right tabular-nums">
                                    {v.sellable_stock > 0 ? angka(v.sellable_stock)
                                      : <span className="text-[hsl(var(--warning-text))]">0 (habis)</span>}
                                  </TableCell>
                                  <TableCell>
                                    {v.in_catalog
                                      ? <StatusBadge status="ada" label="Sudah di katalog" tone="success" />
                                      : <span className="text-muted-foreground">Belum</span>}
                                  </TableCell>
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
        galat={galat} labelSimpan="Tambahkan" judul="Tambahkan ke katalog toko" testId="cfm-form"
        keterangan={`${fgCount} varian × ${accCount} toko = ${angka(fgCount * accCount)} item katalog. Varian yang sudah ada dilewati.`}>
        <Isian label="Toko tujuan">
          <p className="text-sm">{accNames.join(', ') || '—'}</p>
        </Isian>
        <Isian label="Harga jual awal" htmlFor="cfm-price-mode">
          <SmartNativeSelect id="cfm-price-mode" className="w-full" value={priceMode}
            onChange={(e) => setPriceMode(e.target.value)} data-testid="cfm-price-mode">
            <option value="master">Harga resmi dari master produk</option>
            <option value="kosong">Kosongkan (isi per toko nanti)</option>
          </SmartNativeSelect>
        </Isian>
        <Isian label="Peringatan stok di bawah (pcs)" htmlFor="cfm-alert-qty">
          <Input id="cfm-alert-qty" type="number" min="0" step="1" value={alertQty}
            onChange={(e) => setAlertQty(e.target.value)} className="w-32" data-testid="cfm-alert-qty" />
        </Isian>
      </FormPopup>
    </div>
  );
}

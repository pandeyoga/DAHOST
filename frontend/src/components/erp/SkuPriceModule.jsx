/**
 * SkuPriceModule — HARGA JUAL RESMI PER SKU (Master Produk, klarifikasi owner 9 Nov 2026 §B2).
 *
 * Harga resmi per SKU (`rahaza_materials.retail_price_master`, 583 SKU terisi dari Excel) dulu TIDAK punya layar —
 * hanya bisa lewat impor berkas. Layar ini: tabel per model (buka baris → isian harga per SKU), "isi sama untuk
 * semua SKU" atau "untuk semua ukuran warna ini", lalu satu tombol Simpan untuk semua perubahan.
 *
 * Harga resmi = nilai AWAL harga jual di katalog toko (item baru) dan kolom pembanding "harga resmi master".
 * Mengubahnya TIDAK mengubah harga jual toko yang sudah ada — itu lewat Manajemen katalog › Isi harga dari master.
 * SKU tanpa harga per SKU memakai harga model (Model DA) sebagai cadangan.
 */
import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import { RefreshCw, Save, Search, Tags } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { productStatusLabel, productStatusTone } from '@/lib/productStatus';
import { RowDetail, RowToggle } from './layout/PageLayout';
import { PageLayoutSatuBaris } from './engine/DataTable';
import { EmptyState, StatusBadge } from './moduleAtoms';
import { toast } from 'sonner';

const API = process.env.REACT_APP_BACKEND_URL || '';
const rp = (n) => `Rp ${Number(n || 0).toLocaleString('id-ID')}`;
const angka = (n) => Number(n || 0).toLocaleString('id-ID');
const KOLOM = 7;

function rentang(m) {
  if (!m.priced_count) return <span className="text-muted-foreground">Belum ada</span>;
  return m.price_min === m.price_max ? rp(m.price_max) : `${rp(m.price_min)} – ${rp(m.price_max)}`;
}

export default function SkuPriceModule({ token }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token || localStorage.getItem('erp_token')}`,
    'Content-Type': 'application/json' }), [token]);
  const [models, setModels] = useState([]);
  const [totals, setTotals] = useState(null);
  const [memuat, setMemuat] = useState(true);
  const [q, setQ] = useState('');
  const [harga, setHarga] = useState('');
  const [status, setStatus] = useState('');
  const [buka, setBuka] = useState({});        // model_id → terbuka
  const [isian, setIsian] = useState({});      // fg_id → harga baru (string angka polos)
  const [isiModel, setIsiModel] = useState({}); // model_id / model_id|warna → harga "isi sama"
  const [menyimpan, setMenyimpan] = useState(false);
  const pg = useClientPagination(models, 25);

  const muat = useCallback(async () => {
    setMemuat(true);
    try {
      const p = new URLSearchParams();
      if (q.trim()) p.set('q', q.trim());
      if (harga) p.set('harga', harga);
      if (status) p.set('product_status', status);
      const r = await fetch(`${API}/api/rahaza/sku-prices?${p}`, { headers });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(b.detail || 'Gagal memuat harga per SKU');
      setModels(b.models || []);
      setTotals(b.totals || null);
    } catch (e) { toast.error(e.message, { duration: 9000 }); setModels([]); } finally { setMemuat(false); }
  }, [headers, q, harga, status]);

  useEffect(() => { const t = setTimeout(muat, 250); return () => clearTimeout(t); }, [muat]);

  const semuaVarian = useMemo(() => Object.fromEntries(models.flatMap((m) => m.variants.map((v) => [v.fg_id, v]))), [models]);
  const perubahan = useMemo(() => Object.entries(isian)
    .filter(([fid, val]) => semuaVarian[fid] && val !== '' && val !== undefined
      && Number(val) !== Number(semuaVarian[fid].retail_price_master || 0))
    .map(([fid, val]) => ({ fg_id: fid, harga: Number(val) })), [isian, semuaVarian]);
  const nilai = (v) => (isian[v.fg_id] !== undefined ? isian[v.fg_id] : (v.retail_price_master || ''));
  const isiBanyak = (vs, val) => {
    if (val === '' || val === undefined) return;
    setIsian((s) => ({ ...s, ...Object.fromEntries(vs.map((v) => [v.fg_id, val])) }));
  };

  const simpan = async () => {
    if (!perubahan.length) return;
    const nol = perubahan.filter((c) => !c.harga).length;
    const ok = await confirmDialog({
      title: `Simpan ${angka(perubahan.length)} harga SKU?`,
      body: `Harga resmi per SKU diperbarui${nol ? ` (${angka(nol)} dikosongkan — katalog memakai harga model)` : ''}. `
        + 'Harga jual toko yang sudah ada TIDAK berubah; pakai "Isi harga dari master" di Manajemen katalog. Riwayat tercatat.',
      confirmLabel: 'Simpan harga',
    });
    if (!ok) return;
    setMenyimpan(true);
    try {
      const r = await fetch(`${API}/api/rahaza/sku-prices`, { method: 'POST', headers, body: JSON.stringify({ changes: perubahan }) });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(b.detail || 'Gagal menyimpan harga');
      toast.success(b.message, { duration: 9000 });
      setIsian({});
      muat();
    } catch (e) { toast.error(e.message, { duration: 9000 }); } finally { setMenyimpan(false); }
  };

  const baris = useMemo(() => models.flatMap((m) => m.variants.map((v) => ({ m, v }))), [models]);

  return (
    <PageLayoutSatuBaris testId="sku-price-module" title="Harga jual per SKU"
      subtitle="Harga resmi tiap SKU — nilai awal harga jual di katalog toko; SKU kosong memakai harga model."
      actions={(
        <Button onClick={simpan} disabled={!perubahan.length || menyimpan} data-testid="sku-price-save">
          <Save />{menyimpan ? 'Menyimpan…' : `Simpan harga${perubahan.length ? ` (${angka(perubahan.length)})` : ''}`}
        </Button>
      )}
      filters={<>
        <div className="relative w-full sm:w-60">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="pl-8" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari model atau SKU"
            data-testid="sku-price-search" />
        </div>
        <SmartNativeSelect className="w-44" value={harga} onChange={(e) => setHarga(e.target.value)} data-testid="sku-price-filter">
          <option value="">Semua SKU</option>
          <option value="kosong">Belum berharga</option>
          <option value="terisi">Sudah berharga</option>
        </SmartNativeSelect>
        <SmartNativeSelect className="w-44" value={status} onChange={(e) => setStatus(e.target.value)} data-testid="sku-price-status">
          <option value="">Semua status produk</option>
          <option value="new">Baru</option>
          <option value="best_seller">Best Seller</option>
          <option value="slow">Slow</option>
          <option value="dead">Dead</option>
          <option value="stop">Stop</option>
          <option value="belum_diisi">Status belum diisi</option>
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="harga-jual-per-sku" namaLembar="Harga per SKU" baris={baris} testId="sku-price-unduh"
          kolom={[
            { label: 'Kode model', nilai: ({ m }) => m.code }, { label: 'Model', nilai: ({ m }) => m.name },
            { label: 'SKU', nilai: ({ v }) => v.sku }, { label: 'Warna', nilai: ({ v }) => v.color },
            { label: 'Ukuran', nilai: ({ v }) => v.size_code },
            { label: 'Status produk', nilai: ({ v }) => (v.product_status ? productStatusLabel(v.product_status) : '') },
            { label: 'Harga resmi SKU', nilai: ({ v }) => Number(v.retail_price_master || 0) },
            { label: 'Harga model (cadangan)', nilai: ({ m }) => Number(m.model_retail_price || 0) },
          ]} />
        <Button variant="outline" size="icon" onClick={muat} disabled={memuat} title="Muat ulang" aria-label="Muat ulang"
          data-testid="sku-price-refresh">
          <RefreshCw className={memuat ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={totals && (
        <p className="text-sm text-muted-foreground" data-testid="sku-price-summary">
          <b className="text-foreground">{angka(totals.skus)}</b> SKU di {angka(totals.models)} model ·{' '}
          <b className="text-foreground">{angka(totals.priced)}</b> sudah berharga ·{' '}
          <b className={totals.empty ? 'text-[hsl(var(--warning-text))]' : 'text-foreground'}>{angka(totals.empty)}</b> belum.
          {perubahan.length > 0 && <> · <b className="text-foreground">{angka(perubahan.length)}</b> perubahan belum disimpan.</>}
        </p>
      )}
      footer={<PaginationLite page={pg.page} totalPages={pg.totalPages} total={pg.total} onPageChange={pg.setPage} pageSize={25} />}>
      <Table data-testid="sku-price-table">
        <TableHeader>
          <TableRow>
            <TableHead className="w-8" />
            <TableHead>Model</TableHead>
            <TableHead className="hidden md:table-cell">Kategori</TableHead>
            <TableHead className="text-right">SKU</TableHead>
            <TableHead className="text-right">Berharga</TableHead>
            <TableHead className="text-right">Harga resmi SKU</TableHead>
            <TableHead className="hidden text-right md:table-cell">Harga model</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {!memuat && models.length === 0 && (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={KOLOM} className="p-0 [&>div]:py-8">
                <EmptyState icon={Tags} title="Tidak ada SKU yang cocok" testId="sku-price-empty"
                  description="Kosongkan penyaring, atau buat varian/SKU di tab Varian / SKU." />
              </TableCell>
            </TableRow>
          )}
          {pg.paged.map((m) => {
            const terbuka = !!buka[m.model_id];
            const warna = [...new Set(m.variants.map((v) => v.color || '—'))];
            return (
              <Fragment key={m.model_id}>
                <TableRow data-testid={`sku-price-model-${m.code}`}>
                  <TableCell>
                    <RowToggle open={terbuka} onClick={() => setBuka((s) => ({ ...s, [m.model_id]: !terbuka }))}
                      label="Ubah harga per SKU" testId={`sku-price-toggle-${m.code}`} />
                  </TableCell>
                  <TableCell>
                    <p className="font-medium">{m.name}</p>
                    <p className="text-xs text-muted-foreground">{m.code}</p>
                  </TableCell>
                  <TableCell className="hidden md:table-cell">{m.category_name || '—'}</TableCell>
                  <TableCell className="text-right tabular-nums">{angka(m.sku_count)}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    <span className={m.priced_count < m.sku_count ? 'text-[hsl(var(--warning-text))]' : ''}>{angka(m.priced_count)}</span>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{rentang(m)}</TableCell>
                  <TableCell className="hidden text-right tabular-nums md:table-cell">{m.model_retail_price ? rp(m.model_retail_price) : '—'}</TableCell>
                </TableRow>
                {terbuka && (
                  <RowDetail colSpan={KOLOM} testId={`sku-price-detail-${m.code}`}>
                    <div className="space-y-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm">Isi sama untuk semua {angka(m.sku_count)} SKU:</span>
                        <MoneyInput className="w-36" value={isiModel[m.model_id] ?? ''} placeholder="Harga"
                          onChange={(e) => setIsiModel((s) => ({ ...s, [m.model_id]: e.target.value }))}
                          data-testid={`sku-price-fill-all-${m.code}`} aria-label={`Harga semua SKU ${m.name}`} />
                        <Button size="sm" variant="outline" onClick={() => isiBanyak(m.variants, isiModel[m.model_id])}
                          disabled={!isiModel[m.model_id]} data-testid={`sku-price-fill-all-apply-${m.code}`}>Terapkan ke semua</Button>
                      </div>
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>SKU</TableHead>
                            <TableHead>Warna</TableHead>
                            <TableHead>Ukuran</TableHead>
                            <TableHead>Status produk</TableHead>
                            <TableHead className="text-right">Harga resmi</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {warna.map((w) => {
                            const vs = m.variants.filter((v) => (v.color || '—') === w);
                            const kunci = `${m.model_id}|${w}`;
                            return (
                              <Fragment key={kunci}>
                                {warna.length > 1 && vs.length > 1 && (
                                  <TableRow className="hover:bg-transparent">
                                    <TableCell colSpan={5}>
                                      <div className="flex flex-wrap items-center gap-2">
                                        <span className="text-xs font-medium">{w} — isi sama untuk {angka(vs.length)} ukuran:</span>
                                        <MoneyInput className="h-8 w-32" value={isiModel[kunci] ?? ''} placeholder="Harga"
                                          onChange={(e) => setIsiModel((s) => ({ ...s, [kunci]: e.target.value }))}
                                          aria-label={`Harga semua ukuran ${w}`} data-testid={`sku-price-fill-color-${m.code}-${w}`} />
                                        <Button size="sm" variant="link" className="px-0" disabled={!isiModel[kunci]}
                                          onClick={() => isiBanyak(vs, isiModel[kunci])}>Terapkan</Button>
                                      </div>
                                    </TableCell>
                                  </TableRow>
                                )}
                                {vs.map((v) => {
                                  const berubah = isian[v.fg_id] !== undefined && Number(isian[v.fg_id] || 0) !== Number(v.retail_price_master || 0);
                                  return (
                                    <TableRow key={v.fg_id} data-testid={`sku-price-row-${v.sku}`}>
                                      <TableCell className="text-sm">{v.sku}</TableCell>
                                      <TableCell>{v.color || '—'}</TableCell>
                                      <TableCell>{v.size_code || '—'}</TableCell>
                                      <TableCell>
                                        {v.product_status
                                          ? <StatusBadge status={v.product_status} label={productStatusLabel(v.product_status)} tone={productStatusTone(v.product_status)} />
                                          : <span className="text-xs text-muted-foreground">Belum diisi</span>}
                                      </TableCell>
                                      <TableCell className="text-right">
                                        <MoneyInput className={`ml-auto w-36 text-right ${berubah ? 'border-[hsl(var(--primary))]' : ''}`}
                                          value={nilai(v)} placeholder={m.model_retail_price ? `model ${angka(m.model_retail_price)}` : 'Belum ada'}
                                          onChange={(e) => setIsian((s) => ({ ...s, [v.fg_id]: e.target.value }))}
                                          aria-label={`Harga ${v.sku}`} data-testid={`sku-price-input-${v.sku}`} />
                                      </TableCell>
                                    </TableRow>
                                  );
                                })}
                              </Fragment>
                            );
                          })}
                        </TableBody>
                      </Table>
                    </div>
                  </RowDetail>
                )}
              </Fragment>
            );
          })}
        </TableBody>
      </Table>
    </PageLayoutSatuBaris>
  );
}

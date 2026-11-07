/**
 * RahazaModelsAndBOMModule — Master Produk, dua wajah (keputusan owner 2026-09-12):
 *   variant="production" → Portal Produksi: HANYA tab Model DA (HPP, SOP, bundle).
 *   variant="rnd"        → Portal RnD → Master Produk (SSOT): Kategori · Varian/SKU · BOM ·
 *                          Ukuran · Warna — satu-satunya penyunting `rahaza_boms`,
 *                          `rahaza_product_categories`, `rahaza_sizes`, `rahaza_colors`.
 * Satu kepala halaman, tab pil berikon + jumlah data, penjelasan singkat per tab.
 */
import { useState, useEffect } from 'react';
import { Shirt, ListTree, Ruler, Boxes, Palette, Tags, FlaskConical, ArrowUpRight, RefreshCw, FileSpreadsheet } from 'lucide-react';
import { apiGet, apiPost } from '@/lib/api';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import PageLayout from './layout/PageLayout';
import HubTabs from './hubs/HubTabs';
import RahazaModelsModule from './RahazaModelsModule';
import RahazaBOMModuleV2 from './RahazaBOMModuleV2';
import RahazaSizesModule from './RahazaSizesModule';
import RahazaVariantsModule from './RahazaVariantsModule';
import RahazaColorsModule from './RahazaColorsModule';
import RahazaProductCategoriesModule from './RahazaProductCategoriesModule';
import RahazaMasterFillModule from './finance/RahazaMasterFillModule';

const ALL_TABS = [
  { key: 'models', label: 'Model DA', icon: Shirt, count: 'models',
    hint: 'Model produksi internal: HPP, harga jual resmi, berat, bundle, Panduan Produksi (SOP · foto · video) yang dibaca Vendor CMT.' },
  { key: 'categories', label: 'Kategori', icon: Tags, count: 'categories',
    hint: 'Kelompok produk & awalan SKU. Dipakai grouping katalog marketing dan filter laporan.' },
  { key: 'variants', label: 'Varian / SKU', icon: Boxes, count: 'variants',
    hint: 'Kombinasi model × warna × ukuran yang menjadi SKU barang jadi.' },
  { key: 'bom', label: 'BOM', icon: ListTree, count: null,
    hint: 'Resep per model + ukuran + warna: 1 pcs potongan (biaya dari kain roll yang benar-benar dipotong) + aksesoris. Dasar HPP produk.' },
  { key: 'fill', label: 'Isi Massal (Excel)', icon: FileSpreadsheet, count: null,
    hint: 'Satu template Excel: harga & satuan beli material, aksesoris/bahan BOM per model, berat model, rekening bank & rekening pencairan toko — unggah, HPP standar dihitung otomatis.' },
  { key: 'sizes', label: 'Ukuran', icon: Ruler, count: 'sizes',
    hint: 'Master ukuran (S · M · L · ALLSIZE …) beserta urutannya.' },
  { key: 'colors', label: 'Warna', icon: Palette, count: 'colors',
    hint: 'Palet warna master (kode 3 huruf) — dipakai varian, BOM per warna, dan potongan cutting.' },
];

const VARIANTS = {
  production: {
    tabs: ['models'],
    eyebrow: 'Portal Produksi · Master Data',
    title: 'Master Produk',
    subtitle: 'Model DA — HPP, harga jual resmi, berat, bundle, dan Panduan Produksi yang dibaca Vendor CMT.',
    icon: Shirt,
    crossLink: { module: 'rnd-master-product-hub', label: 'Kategori · Varian · BOM · Ukuran · Warna kini disunting di Portal RnD → Master Produk' },
  },
  rnd: {
    tabs: ['categories', 'variants', 'bom', 'fill', 'sizes', 'colors'],
    eyebrow: 'Portal RnD · Master Data (SSOT)',
    title: 'Master Produk',
    subtitle: 'Sumber tunggal resep produk CV. Dewi Aditya — kategori, varian/SKU, BOM potongan, ukuran, dan warna. Dipakai Cutting, HPP, dan katalog.',
    icon: FlaskConical,
    crossLink: { module: 'prod-master-product-hub', label: 'Model DA (HPP · SOP · bundle) tetap di Portal Produksi → Master Produk' },
  },
};

const COUNT_ENDPOINTS = {
  models: '/rahaza/models',
  categories: '/rahaza/product-categories',
  variants: '/rahaza/variants',
  sizes: '/rahaza/sizes',
  colors: '/rahaza/colors',
};

const countOf = (d) => (Array.isArray(d) ? d.length : (d?.total ?? d?.pagination?.total ?? (Array.isArray(d?.items) ? d.items.length : null)));

// Tahap 9 (7 Nov 2026): `renderPage` (dari hubs/ProductionMasterProductHub) — Portal Produksi memakai cetakan
// PageLayout milik halaman; kepala buatan sendiri di bawah hanya untuk varian RnD.
export default function RahazaModelsAndBOMModule({ token, user, headers, userRole, hasPerm, onNavigate, variant = 'production', renderPage = null }) {
  const V = VARIANTS[variant] || VARIANTS.production;
  const TABS = ALL_TABS.filter((t) => V.tabs.includes(t.key));
  const storageKey = variant === 'rnd' ? 'hub_tab_rnd-master-product-hub' : 'models_bom_tab';
  const getInitialTab = () => {
    const stored = sessionStorage.getItem(storageKey);
    if (stored && TABS.some((t) => t.key === stored)) {
      sessionStorage.removeItem(storageKey);
      return stored;
    }
    return TABS[0].key;
  };
  const [activeTab, setActiveTab] = useState(getInitialTab);
  const [counts, setCounts] = useState({});
  const [syncing, setSyncing] = useState(false);
  const runMasterSync = async () => {
    setSyncing(true);
    try {
      const r = await apiPost('/rahaza/master/sync', {});
      const v = r.variants || {}; const rd = r.rnd || {};
      toast.success(`Sinkron master selesai · ${v.total} varian (${v.created_from_bom + v.created_from_fg} baru) · ${rd.styles_created} style RnD baru · ${v.variants_without_bom} varian tanpa BOM`);
      setCounts({});
    } catch (e) { toast.error(e?.message || 'Sinkron master gagal'); }
    finally { setSyncing(false); }
  };

  useEffect(() => {
    let alive = true;
    Promise.all(Object.entries(COUNT_ENDPOINTS).filter(([k]) => V.tabs.includes(k)).map(async ([k, ep]) => {
      try { return [k, countOf(await apiGet(ep))]; } catch (e) { return [k, null]; }
    })).then((pairs) => { if (alive) setCounts(Object.fromEntries(pairs)); });
    return () => { alive = false; };
  }, [token, variant]); // eslint-disable-line react-hooks/exhaustive-deps

  const current = TABS.find((t) => t.key === activeTab) || TABS[0];
  const shared = { token, user, headers, userRole, hasPerm, onNavigate };
  if (renderPage && variant === 'production') return <RahazaModelsModule {...shared} renderPage={renderPage} />;

  // Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout + tab standar HubTabs (dulu kepala bercahaya dengan ikon,
  // eyebrow, dan deret tombol buatan yang berlagak tab). Tab & isi sama; angka tiap tab tetap tampil di labelnya.
  const COMP = {
    models: (p) => <RahazaModelsModule {...p} embedded />,
    categories: () => <RahazaProductCategoriesModule token={token} />,
    variants: () => <RahazaVariantsModule token={token} />,
    bom: (p) => <RahazaBOMModuleV2 {...p} />,
    fill: (p) => <RahazaMasterFillModule {...p} />,
    sizes: (p) => <RahazaSizesModule {...p} />,
    colors: () => <RahazaColorsModule token={token} />,
  };
  const hubTabs = TABS.map((t) => {
    const n = t.count ? counts[t.count] : null;
    return { key: t.key, label: n !== null && n !== undefined ? `${t.label} (${n})` : t.label, Component: COMP[t.key], props: shared };
  });
  return (
    <PageLayout testId={`models-bom-module-${variant}`} title={V.title} subtitle={V.subtitle}
      actions={variant === 'rnd' && (
        <Button type="button" variant="outline" onClick={runMasterSync} disabled={syncing} data-testid="master-sync-btn"
          title="Samakan varian SSOT dengan BOM & barang jadi, buat style RnD untuk tiap model, tautkan karyawan↔user">
          <RefreshCw className={`w-4 h-4 ${syncing ? 'animate-spin' : ''}`} />{syncing ? 'Menyinkron…' : 'Sinkron master'}
        </Button>
      )}
      summary={<p className="text-sm text-muted-foreground" data-testid="models-bom-tab-hint">
        {current.hint}
        {V.crossLink && (<>
          {' '}<Button type="button" variant="link" size="sm" className="h-auto p-0" onClick={() => onNavigate && onNavigate(V.crossLink.module)}
            data-testid={`master-produk-crosslink-${variant}`}>{V.crossLink.label} <ArrowUpRight className="w-3.5 h-3.5" /></Button>
        </>)}
      </p>}>
      <HubTabs hubId={`models-bom-${variant}`} tabs={hubTabs} value={current.key} onValueChange={setActiveTab} />
    </PageLayout>
  );
}

import React, { Suspense } from 'react';
import { ArrowUpRight } from 'lucide-react';

import { lazyRetry } from '../../../lib/lazyRetry';
import { Button } from '@/components/ui/button';
import PageLayout from '../layout/PageLayout';
import { PageLayoutSatuBaris } from '../engine/DataTable';
// 2026-09-12 (keputusan owner): tab "Lokasi Kerja" & "Operator & Skill" dihapus dari
// Master Produk Produksi — tidak relevan di sini. Master Lokasi pindah ke
// Gudang → Master Item → tab "Lokasi Gudang"; Operator/karyawan tetap di Portal HR.
// Tahap 9 (7 Nov 2026, "tampilan dua portal identik"): halaman ini memakai cetakan PageLayout. Dulu
// RahazaModelsAndBOMModule menggambar kepala sendiri (kartu bercahaya + eyebrow + tab pil satu-satunya).
// Kategori · Varian · BOM · Ukuran · Warna tetap disunting di Portal RnD › Master Produk. Modulnya tetap
// RahazaModelsAndBOMModule (varian production → tab Model DA); slot halaman diisi lewat `renderPage`.
const RahazaModelsAndBOMModule = lazyRetry(() => import('../RahazaModelsAndBOMModule'));

const Spinner = () => (
  <div className="flex items-center justify-center h-40">
    <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-[hsl(var(--primary))]" />
  </div>
);

export default function ProductionMasterProductHub(props) {
  const { onNavigate } = props;
  return (
    <Suspense fallback={<Spinner />}>
      <RahazaModelsAndBOMModule {...props} variant="production" renderPage={(slots, body) => (
        <PageLayoutSatuBaris testId="prod-master-product-hub" title="Master produk"
          subtitle="Model DA: HPP, harga jual resmi, berat, dan panduan produksi yang dibaca vendor CMT."
          filters={slots.filters} tools={slots.tools} actions={slots.actions}
          summary={<>
            {slots.summary}
            {onNavigate && (
              <p className="text-sm text-muted-foreground" data-testid="master-produk-crosslink-production">
                Kategori, varian/SKU, BOM, ukuran, dan warna disunting di Portal RnD.{' '}
                <Button variant="link" size="sm" className="h-auto p-0" onClick={() => onNavigate('rnd-master-product-hub')}>
                  Buka Master Produk RnD <ArrowUpRight className="w-3.5 h-3.5" />
                </Button>
              </p>
            )}
          </>}>
          {body}
        </PageLayoutSatuBaris>
      )} />
    </Suspense>
  );
}

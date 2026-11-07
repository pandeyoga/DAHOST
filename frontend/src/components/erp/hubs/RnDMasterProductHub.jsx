import React, { Suspense } from 'react';

import { lazyRetry } from '../../../lib/lazyRetry';
import { Skeleton } from '@/components/ui/skeleton';
// 2026-09-12 (keputusan owner): Kategori · Varian/SKU · BOM · Ukuran · Warna PINDAH dari
// Portal Produksi ke Portal RnD sebagai Master Produk (SSOT). Model DA tetap di Produksi.
// Isi layar = RahazaModelsAndBOMModule (berkas milik kelompok produksi); pembungkus ini hanya memuatnya.
const RahazaModelsAndBOMModule = lazyRetry(() => import('../RahazaModelsAndBOMModule'));

// Standar UI/UX v2: memuat = Skeleton sesuai bentuk isi (dulu pemutar buatan sendiri).
const Memuat = () => (
  <div className="space-y-3" aria-busy="true" aria-label="Memuat master produk">
    <Skeleton className="h-8 w-64" />
    <Skeleton className="h-9 w-full max-w-xl" />
    <Skeleton className="h-64 w-full" />
  </div>
);

export default function RnDMasterProductHub(props) {
  return (
    <div data-testid="rnd-master-product-hub">
      <Suspense fallback={<Memuat />}>
        <RahazaModelsAndBOMModule {...props} variant="rnd" />
      </Suspense>
    </div>
  );
}

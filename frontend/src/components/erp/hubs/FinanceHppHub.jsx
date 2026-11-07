import React from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// 2026-11-04 (owner): dua menu HPP ("HPP" dan "HPP per Potong") menjadi satu menu bertab.
// Tahap 9 (keputusan owner 7 Nov 2026 No. 13): SATU menu HPP, tampilan sama di Portal Produksi, Maklon, Keuangan.
//   • "HPP per PO"             — HPP aktual dari data nyata, disaring per portal (Produksi = internal, Maklon = maklon).
//   • "HPP standar per potong" — BOM × harga (simulasi/standar).
//   • "Tarif standar"          — tarif per tahap (dulu di Master Proses).
// Portal Maklon hanya memuat tab HPP per PO (HPP standar & tarif tahap = produk DA). Menu lama "HPP Jahit"
// (maklon-hpp) dan "Biaya Jahit" (prod-sewing-cost) membuka hub ini. Kunci tab 'actual'/'unit' dipertahankan
// supaya tautan lama (fin-hpp-produk → 'unit') tetap jalan.
const RahazaHPPModule      = lazyRetry(() => import('../RahazaHPPModule'));
const ProductCostingModule = lazyRetry(() => import('../costing/ProductCostingModule'));
const StandardRateModule   = lazyRetry(() => import('../costing/StandardRateModule'));

export const HPP_TABS = [
  { key: 'actual', label: 'HPP per PO', Component: RahazaHPPModule },
  { key: 'unit', label: 'HPP standar per potong', Component: ProductCostingModule },
  { key: 'rates', label: 'Tarif standar', Component: StandardRateModule },
];

/** Tab HPP untuk satu portal: Maklon hanya HPP per PO. */
export function hppTabsFor(portalId) {
  return portalId === 'maklon' ? HPP_TABS.slice(0, 1) : HPP_TABS;
}

export default function FinanceHppHub(props) {
  return (
    <HubTabs
      hubId="fin-hpp"
      title="HPP"
      compactHeaders
      tabs={hppTabsFor(props.portalId)}
      {...props}
    />
  );
}

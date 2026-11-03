import React from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// 2026-11-04 (owner): semua urusan aset di satu menu. Dulu penyusutan & pelepasan ada di
// Penyesuaian Akhir Periode, terpisah dari daftar asetnya.
const FixedAssetsModule       = lazyRetry(() => import('../FixedAssetsModule'));
const AssetDepreciationModule = lazyRetry(() => import('../AssetDepreciationModule'));
const AssetDisposalModule     = lazyRetry(() => import('../AssetDisposalModule'));

export default function FinanceAssetsHub(props) {
  return (
    <HubTabs
      hubId="fin-fixed-assets"
      title="Aset Tetap"
      compactHeaders
      tabs={[
        { key: 'assets', label: 'Daftar aset', Component: FixedAssetsModule },
        { key: 'depreciation', label: 'Penyusutan', Component: AssetDepreciationModule },
        { key: 'disposal', label: 'Pelepasan', Component: AssetDisposalModule },
      ]}
      {...props}
    />
  );
}

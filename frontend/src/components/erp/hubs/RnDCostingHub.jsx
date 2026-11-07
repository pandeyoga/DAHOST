import React from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// T3.9 — rnd-costing + rnd-hpp → 1 hub
// Standar UI/UX v2 (8 Nov 2026): judul hub = label menu, nama tab bahasa Indonesia (kunci tab tetap).
const RnDCostingTab = lazyRetry(() => import('../RnDCostingTab'));
const RnDHPPCalculatorModule = lazyRetry(() => import('../RnDHPPCalculatorModule'));

export default function RnDCostingHub(props) {
  return (
    <HubTabs
      hubId="rnd-costing-hub"
      title="Costing & HPP"
      subtitle="Biaya sample dan perhitungan HPP per style sebelum harga jual ditetapkan."
      tabs={[
        { key: 'costing', label: 'Biaya sample', Component: RnDCostingTab },
        { key: 'hpp', label: 'Kalkulator HPP', Component: RnDHPPCalculatorModule },
      ]}
      {...props}
    />
  );
}

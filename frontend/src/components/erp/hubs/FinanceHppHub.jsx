import React from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// 2026-11-04 (owner): dua menu HPP ("HPP" dan "HPP per Potong") menjadi satu menu bertab.
const RahazaHPPModule      = lazyRetry(() => import('../RahazaHPPModule'));
const ProductCostingModule = lazyRetry(() => import('../costing/ProductCostingModule'));

export default function FinanceHppHub(props) {
  return (
    <HubTabs
      hubId="fin-hpp"
      title="HPP"
      compactHeaders
      tabs={[
        { key: 'actual', label: 'HPP aktual (work order & maklon)', Component: RahazaHPPModule },
        { key: 'unit', label: 'HPP per potong', Component: ProductCostingModule },
      ]}
      {...props}
    />
  );
}

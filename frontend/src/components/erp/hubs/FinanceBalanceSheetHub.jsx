import React from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// 2026-11-04 (owner): Neraca satu menu — "per tanggal" atau "akhir tiap bulan" (dulu tab Neraca 12 Bln).
const RahazaBalanceSheetModule        = lazyRetry(() => import('../RahazaBalanceSheetModule'));
const RahazaBalanceSheetMonthlyModule = lazyRetry(() => import('../finance/RahazaBalanceSheetMonthlyModule'));

export default function FinanceBalanceSheetHub(props) {
  return (
    <HubTabs
      hubId="fin-bs"
      title="Neraca"
      compactHeaders
      tabs={[
        { key: 'date', label: 'Per tanggal', Component: RahazaBalanceSheetModule },
        { key: 'monthly', label: 'Akhir tiap bulan', Component: RahazaBalanceSheetMonthlyModule },
      ]}
      {...props}
    />
  );
}

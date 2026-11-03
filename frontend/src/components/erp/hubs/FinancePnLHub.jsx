import React from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// 2026-11-04 (owner): satu laporan per pertanyaan — "per bulan" adalah pilihan tampilan, bukan menu/tab
// laporan kedua. Dulu: tab "Laba Rugi" dan "Laba Rugi 12 Bln" di hub Laporan Keuangan (10 tab).
const RahazaPnLModule        = lazyRetry(() => import('../RahazaPnLModule'));
const RahazaPnLMonthlyModule = lazyRetry(() => import('../finance/RahazaPnLMonthlyModule'));

export default function FinancePnLHub(props) {
  return (
    <HubTabs
      hubId="fin-pnl"
      title="Laba Rugi"
      compactHeaders
      tabs={[
        { key: 'total', label: 'Total periode', Component: RahazaPnLModule },
        { key: 'monthly', label: 'Per bulan', Component: RahazaPnLMonthlyModule },
      ]}
      {...props}
    />
  );
}

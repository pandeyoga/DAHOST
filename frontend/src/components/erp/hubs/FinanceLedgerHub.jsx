import React from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// 2026-11-04 (owner): Neraca Saldo, Neraca Lajur, dan Buku Besar adalah tiga cara melihat data yang
// sama → satu menu "Buku Besar". Dibuka di saldo semua akun.
const RahazaTrialBalanceModule  = lazyRetry(() => import('../RahazaTrialBalanceModule'));
const RahazaWorksheetModule     = lazyRetry(() => import('../finance/RahazaWorksheetModule'));
const RahazaGeneralLedgerModule = lazyRetry(() => import('../RahazaGeneralLedgerModule'));

export default function FinanceLedgerHub(props) {
  return (
    <HubTabs
      hubId="fin-gl"
      title="Buku Besar"
      compactHeaders
      tabs={[
        { key: 'tb', label: 'Saldo semua akun', Component: RahazaTrialBalanceModule },
        { key: 'worksheet', label: 'Neraca lajur', Component: RahazaWorksheetModule },
        { key: 'ledger', label: 'Mutasi per akun', Component: RahazaGeneralLedgerModule },
      ]}
      {...props}
    />
  );
}

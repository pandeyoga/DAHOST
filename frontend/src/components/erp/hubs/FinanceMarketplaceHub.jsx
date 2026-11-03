import React from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// 2026-11-04 (owner, audit Keuangan tahap 3): "Saldo & Pencairan Marketplace" (satu halaman ±7 layar
// berisi 4 fungsi) dipecah menjadi 3 tab dengan satu modul yang sama (prop `view`). Pengaturan rekening
// pencairan per toko pindah ke Pengaturan Keuangan › Rekening toko.
const FinanceSettlementModule = lazyRetry(() => import('../finance/FinanceSettlementModule'));

export default function FinanceMarketplaceHub(props) {
  return (
    <HubTabs
      hubId="fin-marketplace-settlement"
      title="Marketplace"
      compactHeaders
      tabs={[
        { key: 'balances', label: 'Saldo per toko', Component: FinanceSettlementModule, props: { view: 'balances' } },
        { key: 'settlements', label: 'Dana dilepas', Component: FinanceSettlementModule, props: { view: 'settlements' } },
        { key: 'withdrawals', label: 'Penarikan ke bank', Component: FinanceSettlementModule, props: { view: 'withdrawals' } },
      ]}
      {...props}
    />
  );
}

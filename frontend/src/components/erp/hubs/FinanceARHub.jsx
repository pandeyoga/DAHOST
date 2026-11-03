import React from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// 2026-11-04 (owner, audit Keuangan tahap 3): satu menu untuk satu jenis dokumen — faktur piutang.
// Dulu: Faktur Penjualan tak ada di menu, Aging Piutang menu sendiri, hapus buku di Penyesuaian.
const RahazaARInvoicesModule = lazyRetry(() => import('../RahazaARInvoicesModule'));
const ARLifecycleModule      = lazyRetry(() => import('../ARLifecycleModule'));
const BadDebtWriteOffModule  = lazyRetry(() => import('../BadDebtWriteOffModule'));

export default function FinanceARHub(props) {
  return (
    <HubTabs
      hubId="fin-ar-hub"
      title="Piutang Reseller"
      compactHeaders
      tabs={[
        { key: 'invoices', label: 'Faktur', Component: RahazaARInvoicesModule },
        { key: 'aging', label: 'Umur piutang', Component: ARLifecycleModule },
        { key: 'writeoff', label: 'Hapus buku', Component: BadDebtWriteOffModule },
      ]}
      {...props}
    />
  );
}

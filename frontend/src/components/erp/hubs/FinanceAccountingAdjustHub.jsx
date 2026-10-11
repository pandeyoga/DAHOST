import React, { lazy } from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// PHASE B (6.1.4 #4) — 5 menu jurnal-otomatis Finance (Operasi Khusus) → 1 hub "Penyesuaian Akuntansi".
const AccrualsModule         = lazyRetry(() => import('../AccrualsModule'));
const AssetDepreciationModule = lazyRetry(() => import('../AssetDepreciationModule'));
const BadDebtWriteOffModule  = lazyRetry(() => import('../BadDebtWriteOffModule'));
const AssetDisposalModule    = lazyRetry(() => import('../AssetDisposalModule'));
const PurchaseDiscountModule = lazyRetry(() => import('../PurchaseDiscountModule'));

export default function FinanceAccountingAdjustHub(props) {
  return (
    <HubTabs
      hubId="fin-acctg-adjust-hub"
      title="Penyesuaian Akuntansi"
      subtitle="Akrual, depresiasi aset, hapus buku piutang, pelepasan aset, dan diskon pembelian — semua jurnal otomatis dalam satu pintu."
      tabs={[
        { key: 'accruals', label: 'Pencatatan Akrual', Component: AccrualsModule },
        { key: 'depreciation', label: 'Depresiasi Aset (Batch)', Component: AssetDepreciationModule },
        { key: 'baddebt', label: 'Hapus Buku Piutang Macet', Component: BadDebtWriteOffModule },
        { key: 'disposal', label: 'Pelepasan Aset Tetap', Component: AssetDisposalModule },
        { key: 'discount', label: 'Diskon Pembelian (AP)', Component: PurchaseDiscountModule },
      ]}
      {...props}
    />
  );
}

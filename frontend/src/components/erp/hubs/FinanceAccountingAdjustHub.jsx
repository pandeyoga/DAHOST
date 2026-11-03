import React, { lazy } from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// PHASE B (6.1.4 #4) — 5 menu jurnal-otomatis Finance (Operasi Khusus) → 1 hub "Penyesuaian Akuntansi".
// 2026-11-03: tab "Diskon Pembelian (AP)" dilepas — itu sebenarnya layar BAYAR hutang kedua. Pembayaran
// (dengan potongan pemasok yang diisi manual) kini satu pintu di Faktur Supplier (proc-ap-invoices).
const AccrualsModule         = lazyRetry(() => import('../AccrualsModule'));
const AssetDepreciationModule = lazyRetry(() => import('../AssetDepreciationModule'));
const BadDebtWriteOffModule  = lazyRetry(() => import('../BadDebtWriteOffModule'));
const AssetDisposalModule    = lazyRetry(() => import('../AssetDisposalModule'));

export default function FinanceAccountingAdjustHub(props) {
  return (
    <HubTabs
      hubId="fin-acctg-adjust-hub"
      title="Penyesuaian Akuntansi"
      subtitle="Akrual, depresiasi aset, hapus buku piutang, dan pelepasan aset — semua jurnal otomatis dalam satu pintu."
      tabs={[
        { key: 'accruals', label: 'Pencatatan Akrual', Component: AccrualsModule },
        { key: 'depreciation', label: 'Depresiasi Aset (Batch)', Component: AssetDepreciationModule },
        { key: 'baddebt', label: 'Hapus Buku Piutang Macet', Component: BadDebtWriteOffModule },
        { key: 'disposal', label: 'Pelepasan Aset Tetap', Component: AssetDisposalModule },
      ]}
      {...props}
    />
  );
}

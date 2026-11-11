import React from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// PHASE B (6.1.4 #4) — dulu 5 menu jurnal-otomatis → 1 hub "Penyesuaian Akuntansi".
// 2026-11-03: tab "Diskon Pembelian (AP)" dilepas — bayar hutang (+ potongan pemasok) satu pintu di Faktur Supplier.
// 2026-11-04 (owner, audit tahap 3): hub ini menjadi "Akrual & Tutup Buku". Penyusutan & pelepasan aset
// pindah ke menu Aset Tetap, hapus buku piutang ke menu Piutang; Periode (tutup buku) masuk ke sini
// dari Master Akuntansi.
const AccrualsModule      = lazyRetry(() => import('../AccrualsModule'));
const RahazaPeriodsModule = lazyRetry(() => import('../RahazaPeriodsModule'));

export default function FinanceAccountingAdjustHub(props) {
  return (
    <HubTabs
      hubId="fin-acctg-adjust-hub"
      title="Akrual & Tutup Buku"
      compactHeaders
      tabs={[
        { key: 'accruals', label: 'Akrual', Component: AccrualsModule },
        { key: 'periods', label: 'Tutup buku', Component: RahazaPeriodsModule },
      ]}
      {...props}
    />
  );
}

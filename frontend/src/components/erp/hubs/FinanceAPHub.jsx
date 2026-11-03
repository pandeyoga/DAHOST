import React from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// 2026-11-04 (owner): satu menu hutang — tagihan pemasok bahan DAN tagihan CMT dalam satu daftar
// (penyaring jenis), bayar dari satu pintu, dan umur hutang. Dulu tersebar: Faktur Supplier (Bahan),
// Invoice Vendor CMT, Aging Hutang (+ tab ganda di Laporan Keuangan).
const SupplierInvoiceModule = lazyRetry(() => import('../procurement/SupplierInvoiceModule'));
const RahazaAPAgingModule   = lazyRetry(() => import('../RahazaAPAgingModule'));

export default function FinanceAPHub(props) {
  return (
    <HubTabs
      hubId="fin-ap-hub"
      title="Hutang Pemasok & CMT"
      compactHeaders
      tabs={[
        { key: 'bills', label: 'Tagihan', Component: SupplierInvoiceModule, props: { financeMode: true } },
        { key: 'aging', label: 'Umur hutang', Component: RahazaAPAgingModule },
      ]}
      {...props}
    />
  );
}

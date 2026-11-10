import React from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// 2026-11-04 (owner): satu menu hutang — tagihan pemasok bahan DAN tagihan CMT dalam satu daftar
// (penyaring jenis), bayar dari satu pintu, dan umur hutang. Dulu tersebar: Faktur Supplier (Bahan),
// Invoice Vendor CMT, Aging Hutang (+ tab ganda di Laporan Keuangan).
const SupplierInvoiceModule = lazyRetry(() => import('../procurement/SupplierInvoiceModule'));
const RahazaAPAgingModule   = lazyRetry(() => import('../RahazaAPAgingModule'));
// 11 Nov 2026 (owner "kenapa tidak ada hutang CMT"): upah jahit barang yang masih di penjahit — belum jatuh tempo,
// terpisah dari tagihan nyata. CV Sukma = jadwal PO maklon; CV Dewi Aditya = perkiraan PO DA.
const HutangCmtTerjadwal    = lazyRetry(() => import('../finance/HutangCmtTerjadwal'));

export default function FinanceAPHub(props) {
  return (
    <HubTabs
      hubId="fin-ap-hub"
      title="Hutang Pemasok & CMT"
      compactHeaders
      tabs={[
        { key: 'bills', label: 'Tagihan', Component: SupplierInvoiceModule, props: { financeMode: true } },
        { key: 'cmt-terjadwal', label: 'Hutang CMT terjadwal', Component: HutangCmtTerjadwal },
        { key: 'aging', label: 'Umur hutang', Component: RahazaAPAgingModule },
      ]}
      {...props}
    />
  );
}

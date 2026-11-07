/**
 * Laporan Selisih — OTOMATIS per baris PO, sama di Portal Produksi dan Portal Maklon (Tahap 9, 7 Nov 2026).
 *
 * Menggantikan dua laporan berbeda yang memakai label sama: Laporan Variance produksi (`prod-variance`, hanya
 * laporan yang diisi vendor) dan laporan terima buyer maklon (`prod-variance-report`, baris yang belum
 * dikonfirmasi dianggap diterima penuh). Rantai per baris PO: dipesan → bahan diterima CMT → diproduksi →
 * masuk stok barang jadi (internal) / diterima klien (maklon), lengkap dengan alasan yang sudah tercatat.
 * Selisih jumlah TIDAK dijurnal dari sini (jurnal OVER/UNDER lama dipensiunkan — lihat backend exceptions).
 */
import { lazyRetry } from '../../../lib/lazyRetry';
import { useState } from 'react';
import HubTabs from '../hubs/HubTabs';
import { portalBusinessType, primeHubTab } from './pantauShared';
import { SelisihFilterProvider } from './selisihShared';

const SelisihBarisTab = lazyRetry(() => import('./SelisihBarisTab'));
const SelisihVendorTab = lazyRetry(() => import('./SelisihVendorTab'));
const SelisihKlienTab = lazyRetry(() => import('./SelisihKlienTab'));

const TABS = [
  { key: 'baris', label: 'Per baris PO', Component: SelisihBarisTab },
  { key: 'vendor', label: 'Laporan vendor', Component: SelisihVendorTab },
  { key: 'klien', label: 'Terima klien', Component: SelisihKlienTab },
];

export default function LaporanSelisihModule(props) {
  const businessType = portalBusinessType(props);
  useState(() => primeHubTab('laporan-selisih', props.initialTab || props.defaultTab, TABS.map((t) => t.key)));
  return (
    <SelisihFilterProvider key={businessType} businessType={businessType}>
      <HubTabs
        hubId="laporan-selisih"
        title="Laporan Selisih"
        subtitle="Dihitung otomatis per baris PO: dipesan, bahan diterima CMT, diproduksi, sampai hasil akhirnya."
        compactHeaders
        tabs={TABS}
        {...props}
      />
    </SelisihFilterProvider>
  );
}

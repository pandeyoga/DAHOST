/**
 * Pantau Produksi — SATU layar untuk Portal Produksi dan Portal Maklon (Tahap 9, keputusan owner no. 7 & 11).
 *
 * Menggantikan lima layar yang menghitung sendiri-sendiri: Production Jobs (`prod-work-orders`), Tracking
 * Produksi/Vendor (`prod-monitoring`), Tracking Order (`maklon-tracking`), Monitoring CMT (`cmt-monitor`),
 * dan Pusat Kendali (`prod-control-tower`), plus Kapasitas dari Analitik Produksi.
 *
 * Disaring per portal (Produksi = PO internal, Maklon = PO maklon); semua angka dari /api/pantau/*
 * (`core.pantau_produksi`, satu sumber per baris PO). Tidak ada input di layar ini — input tahap manual
 * Tracking Order dan tab Rekonsiliasi dihapus (keputusan 7).
 */
import { useState } from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from '../hubs/HubTabs';
import { portalBusinessType, primeHubTab } from './pantauShared';

const RingkasanTab = lazyRetry(() => import('./RingkasanTab'));
const PerVendorTab = lazyRetry(() => import('./PerVendorTab'));
const PerPOTab = lazyRetry(() => import('./PerPOTab'));
const KejarCMTTab = lazyRetry(() => import('./KejarCMTTab'));
const KirimanCMTTab = lazyRetry(() => import('./KirimanCMTTab'));
const KapasitasCMTTab = lazyRetry(() => import('./KapasitasCMTTab'));

const TABS = [
  { key: 'ringkasan', label: 'Ringkasan', Component: RingkasanTab },
  { key: 'vendor', label: 'Per vendor CMT', Component: PerVendorTab },
  { key: 'po', label: 'Per PO', Component: PerPOTab },
  { key: 'kejar', label: 'Kejar CMT', Component: KejarCMTTab },
  { key: 'kiriman', label: 'Kiriman ke CMT', Component: KirimanCMTTab },
  { key: 'kapasitas', label: 'Kapasitas CMT', Component: KapasitasCMTTab },
];

export default function PantauProduksiModule(props) {
  const businessType = portalBusinessType(props);
  // tab awal dari tautan lama (mis. Monitoring CMT → tab Kejar CMT) — dibaca HubTabs saat dipasang
  useState(() => primeHubTab('pantau-produksi', props.initialTab || props.defaultTab, TABS.map((t) => t.key)));
  return (
    <HubTabs
      key={businessType}
      hubId="pantau-produksi"
      title="Pantau Produksi"
      subtitle={businessType === 'maklon'
        ? 'Perjalanan barang PO maklon: bahan ke CMT, jahit, QC, sampai diterima klien.'
        : 'Perjalanan barang PO internal: bahan ke CMT, jahit, QC, sampai masuk stok barang jadi.'}
      compactHeaders
      tabs={TABS}
      {...props}
      businessType={businessType}
    />
  );
}

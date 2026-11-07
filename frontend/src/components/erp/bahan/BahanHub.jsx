/**
 * BahanHub — menu "Bahan" (Tahap 9, 7 Nov 2026), SAMA di Portal Produksi dan Portal Maklon.
 *
 * Tab: Kebutuhan · Retur. Menggantikan dua menu lama "Kebutuhan Material" (`prod-material-requirements`)
 * dan "Retur Material" (`prod-material-returns`). Isi tiap tab disaring per portal (`portalId` diteruskan
 * HubTabs ke modul tab). Portal Gudang tetap membuka modul Retur yang SAMA lewat id lamanya.
 *
 * Id modul: `bahan-produksi` (moduleRegistry, blok "Tahap 9 (proses)").
 */
import { useState } from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from '../hubs/HubTabs';

const KebutuhanBahan = lazyRetry(() => import('./KebutuhanBahan'));
const RahazaMaterialReturnModule = lazyRetry(() => import('../RahazaMaterialReturnModule'));

export const BAHAN_HUB_ID = 'bahan-produksi';

export default function BahanHub(props) {
  // Tautan "Buka Retur Material" dari Kirim ke CMT membawa surat jalan/MI → langsung ke tab Retur.
  useState(() => {
    const p = props.deepLinkParams || {};
    if (p.vendor_shipment_id || p.material_issue_id || props.initialTab === 'retur') {
      try { sessionStorage.setItem(`hub_tab_${BAHAN_HUB_ID}`, 'retur'); } catch (e) { /* sessionStorage tidak tersedia */ }
    }
    return null;
  });
  return (
    <HubTabs
      hubId={BAHAN_HUB_ID}
      title="Bahan"
      subtitle="Kebutuhan bahan dan aksesoris per PO, dan retur bahan yang sudah keluar ke gudang."
      compactHeaders
      tabs={[
        { key: 'kebutuhan', label: 'Kebutuhan', Component: KebutuhanBahan },
        { key: 'retur', label: 'Retur', Component: RahazaMaterialReturnModule },
      ]}
      {...props}
    />
  );
}

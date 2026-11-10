/**
 * Kirim ke CMT — satu layar untuk Portal Produksi dan Portal Maklon (Tahap 9, 7 Nov 2026; menu id lama
 * `prod-shipments-vendor` tetap). Tab:
 *   • Kiriman             — daftar kiriman + form kiriman baru (potongan dikunci, aksesoris dalam satuan serah);
 *   • Permintaan tambahan — permintaan vendor + input staf (dulu "Komponen Kurang"); disetujui = kiriman tambahan
 *                           yang mengurangi stok (keputusan owner 12).
 *   • Nota aksesoris      — 11 Nov 2026: nota per penyerahan aksesoris ke CMT + cetak rekap per CMT per periode.
 * Data disaring per portal (`portalId`). Deep link tab: sessionStorage `hub_tab_prod-shipments-vendor`.
 */
import { useState } from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from '../hubs/HubTabs';

const KirimanTab = lazyRetry(() => import('./kirim/KirimanTab'));
const PermintaanTab = lazyRetry(() => import('./kirim/PermintaanTab'));
const NotaTab = lazyRetry(() => import('./kirim/NotaTab'));

export const KIRIM_HUB_ID = 'prod-shipments-vendor';
export const KIRIM_TITLE = 'Kirim ke CMT';
export const KIRIM_SUBTITLE = 'Potongan dan aksesoris keluar gudang saat dikirim; angkanya sama dengan surat jalan dan SPP.';
export const KIRIM_TABS = [
  { key: 'kiriman', label: 'Kiriman', Component: KirimanTab },
  { key: 'permintaan', label: 'Permintaan tambahan', Component: PermintaanTab },
  { key: 'nota', label: 'Nota aksesoris', Component: NotaTab },
];

export function setKirimTab(tab) {
  try { sessionStorage.setItem(`hub_tab_${KIRIM_HUB_ID}`, tab); } catch { /* sessionStorage tidak tersedia */ }
}

export default function VendorShipmentModule({ initialTab, ...props }) {
  useState(() => { if (initialTab) setKirimTab(initialTab); return null; });   // sekali, sebelum HubTabs dipasang
  return <HubTabs hubId={KIRIM_HUB_ID} title={KIRIM_TITLE} subtitle={KIRIM_SUBTITLE} compactHeaders tabs={KIRIM_TABS} {...props} />;
}

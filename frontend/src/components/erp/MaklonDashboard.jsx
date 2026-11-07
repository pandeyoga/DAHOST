/**
 * Dashboard Maklon (menu `maklon-dashboard`).
 *
 * Tahap 9 (7 Nov 2026, keputusan owner no. 2 & 7): bentuknya SAMA dengan Dashboard Produksi — tab pertama
 * adalah alur barang yang sama persis (`pantau/DashboardAlurModule`, PO maklon), ditampilkan langsung. Tab
 * tambahan khusus maklon (Ringkasan klien · SLA per klien · Estimasi waktu) memakai gaya tab standar (HubTabs),
 * masing-masing di cetakan PageLayout.
 *
 * Dulu "Alur Produksi" adalah tab kedua yang merender komponen dashboard produksi, dan `maklon-alur-produksi`
 * membuka layar yang sama di tab lain (dua pintu). Kini alur = tab pertama; tautan lama `defaultTab='alur'`
 * mendarat di sana, dan petunjuk tab lama (`maklon_dashboard_tab`, mis. dari `maklon-sla-dashboard`) tetap dibaca.
 */
import { useState } from 'react';
import { lazyRetry } from '../../lib/lazyRetry';
import HubTabs from './hubs/HubTabs';
import { primeHubTab } from './pantau/pantauShared';

const DashboardAlurModule = lazyRetry(() => import('./pantau/DashboardAlurModule'));
const MaklonRingkasanKlienTab = lazyRetry(() => import('./pantau/MaklonRingkasanKlienTab'));
const MaklonSlaTab = lazyRetry(() => import('./pantau/MaklonSlaTab'));
const MaklonEstimasiWaktuTab = lazyRetry(() => import('./pantau/MaklonEstimasiWaktuTab'));

const TABS = [
  { key: 'alur', label: 'Alur produksi', Component: DashboardAlurModule, props: { businessType: 'maklon' } },
  { key: 'klien', label: 'Ringkasan klien', Component: MaklonRingkasanKlienTab },
  { key: 'sla', label: 'SLA per klien', Component: MaklonSlaTab },
  { key: 'leadtime', label: 'Estimasi waktu', Component: MaklonEstimasiWaktuTab },
];
// kunci tab lama → tab baru
const LEGACY_TAB = { overview: 'klien', alur: 'alur', sla: 'sla', leadtime: 'leadtime' };

export default function MaklonDashboard(props) {
  useState(() => {
    let hint = props.defaultTab || props.initialTab;
    try {
      const saved = sessionStorage.getItem('maklon_dashboard_tab');
      if (saved) { hint = saved; sessionStorage.removeItem('maklon_dashboard_tab'); }
    } catch (e) { /* sessionStorage tidak tersedia */ }
    primeHubTab('maklon-dashboard', LEGACY_TAB[hint] || hint, TABS.map((t) => t.key));
    return null;
  });
  return (
    <HubTabs
      hubId="maklon-dashboard"
      title="Dashboard Maklon"
      subtitle="Alur barang PO maklon, klien, ketepatan waktu, dan estimasi lama produksi."
      compactHeaders
      tabs={TABS}
      {...props}
    />
  );
}

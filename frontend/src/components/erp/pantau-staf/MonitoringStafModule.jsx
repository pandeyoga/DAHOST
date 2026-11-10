/**
 * Monitoring Staf ERP — Portal Manajemen (keputusan owner 10 Nov 2026; usulan
 * private/audit/usulan_monitoring_staf_2026-11-10.md).
 *
 * "Setiap akun melakukan apa dan SEHARUSNYA melakukan apa": aktivitas dicatat otomatis, kewajiban dihitung dari
 * data dokumen (bukan centang), dan yang terlambat ditandai "menunggu siapa sejak kapan".
 * Hanya owner & admin (K3). Aturan diubah di menu Aturan Kewajiban.
 */
import { useState } from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from '../hubs/HubTabs';
import { primeHubTab } from '../pantau/pantauShared';

const PerStafTab = lazyRetry(() => import('./PerStafTab'));
const MacetTab = lazyRetry(() => import('./MacetTab'));
const PerAlurTab = lazyRetry(() => import('./PerAlurTab'));

const TABS = [
  { key: 'staf', label: 'Per staf', Component: PerStafTab },
  { key: 'macet', label: 'Macet sekarang', Component: MacetTab },
  { key: 'alur', label: 'Per alur', Component: PerAlurTab },
];

export default function MonitoringStafModule(props) {
  useState(() => primeHubTab('pantau-staf', props.initialTab || props.defaultTab, TABS.map((t) => t.key)));
  return (
    <HubTabs hubId="pantau-staf" title="Monitoring staf"
      subtitle="Siapa memakai sistem, kewajiban yang terlambat, dan siapa yang sedang ditunggu."
      compactHeaders tabs={TABS} {...props} />
  );
}

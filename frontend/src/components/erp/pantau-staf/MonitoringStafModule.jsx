/**
 * Pemantauan staf ERP — Portal Manajemen (keputusan owner 10 Nov 2026; alur kerja harian 14 Nov 2026).
 *
 * "Setiap akun melakukan apa dan SEHARUSNYA melakukan apa": pekerjaan dibaca dari dokumen (bukan centang), dikelompokkan
 * per alur bisnis dan diurutkan per langkah; yang tertahan ditandai "macet di langkah N"; kewajiban yang terlambat
 * ditandai "menunggu siapa sejak kapan". Hanya owner & admin (K3). Penanggung jawab diatur di menu Aturan kewajiban.
 *
 * Tab: Alur kerja (per alur, per langkah, satu hari) · Aktivitas staf (pekerjaan tiap staf, satu hari) ·
 *      Kepatuhan (skor kewajiban per periode) · Kewajiban terlambat.
 */
import { useState } from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from '../hubs/HubTabs';
import { primeHubTab } from '../pantau/pantauShared';

const AlurKerjaTab = lazyRetry(() => import('./AlurKerjaTab'));
const AktivitasStafTab = lazyRetry(() => import('./AktivitasStafTab'));
const PerStafTab = lazyRetry(() => import('./PerStafTab'));
const MacetTab = lazyRetry(() => import('./MacetTab'));

const TABS = [
  { key: 'alur', label: 'Alur kerja', Component: AlurKerjaTab },
  { key: 'aktivitas', label: 'Aktivitas staf', Component: AktivitasStafTab },
  { key: 'staf', label: 'Kepatuhan', Component: PerStafTab },
  { key: 'macet', label: 'Kewajiban terlambat', Component: MacetTab },
];

export default function MonitoringStafModule(props) {
  useState(() => primeHubTab('pantau-staf', props.initialTab || props.defaultTab, TABS.map((t) => t.key)));
  return (
    <HubTabs hubId="pantau-staf" title="Pemantauan staf"
      subtitle="Pekerjaan tiap alur langkah demi langkah: siapa mengerjakan, apa yang menunggu, dan di mana macet."
      compactHeaders tabs={TABS} {...props} />
  );
}

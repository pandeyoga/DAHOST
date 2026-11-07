/**
 * HRPerformanceHub.jsx — Manajemen Kinerja: KPI bulanan + penilaian tahunan + umpan balik 360°.
 * Consolidation #14 (hr-kpi + hr-performance + hr-360-feedback → satu menu).
 *
 * Standar UI/UX v2 (8 Nov 2026): kepala & tab dari HubTabs (dulu kepala buatan sendiri berlatar abu + tab kedua
 * yang mengulang judul modul). Modul di dalam tab tidak mengulang judulnya; aksinya pindah ke baris tab.
 */
import HubTabs from './hubs/HubTabs';
import HRKPIModule          from './HRKPIModule';
import HRPerformanceModule  from './HRPerformanceModule';
import HR360FeedbackModule  from './HR360FeedbackModule';

export default function HRPerformanceHub({ token, user }) {
  return (
    <HubTabs
      hubId="hr-performance-hub"
      title="Manajemen kinerja"
      subtitle="KPI operasional bulanan, penilaian kinerja tahunan, dan umpan balik 360° karyawan."
      tabs={[
        { key: 'kpi', label: 'KPI bulanan', Component: HRKPIModule },
        { key: 'review', label: 'Penilaian tahunan', Component: HRPerformanceModule },
        { key: 'feedback', label: 'Umpan balik 360°', Component: HR360FeedbackModule },
      ]}
      token={token}
      user={user}
    />
  );
}

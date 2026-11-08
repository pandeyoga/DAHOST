/**
 * LiveHost Management Module — Thin Shell (Orchestrator)
 *
 * Refactored from monolithic 2328-LOC file (Session #11) into 11 sub-components in
 * `./live-host/*`. This shell only:
 *   - Holds the active tab state
 *   - Builds the Authorization header (memoized)
 *   - Routes tabs to extracted sub-components or pre-existing tab modules
 *
 * External API (preserved):
 *   - Default export `LiveHostModule`
 *   - Props: { token }
 *
 * Sub-components live in `./live-host/`:
 *   - LiveHostsTab.jsx + AddEditHostModal.jsx
 *   - ShiftsTab.jsx + AddShiftModal.jsx + RecordPerformanceModal.jsx
 *   - CalendarTab.jsx (placeholder)
 *   - ScriptsTab.jsx + ScriptModal.jsx
 *   - TrainingTab.jsx + TrainingModal.jsx + AssignTrainingModal.jsx
 *   - utils.js, Badges.jsx (shared)
 *
 * Pre-existing tabs (UNCHANGED):
 *   - AnalyticsTab (./AnalyticsTab)
 *   - PaymentTab (./PaymentTab)
 *
 * Standar UI/UX v2 (8 Nov 2026): tampilan dipilih dengan pil penyaring (dulu deret tombol tab buatan sendiri =
 * tab di dalam tab hub); tanpa kepala sendiri (judul hub Live Selling sudah tampil); label Indonesia.
 */

import { useState, useMemo } from 'react';
import { Users, Clock, Calendar, Video, TrendingUp, BarChart3, DollarSign } from 'lucide-react';
import FilterChips from '@/components/ui/filter-chips';
import PageLayout from '../layout/PageLayout';
import AnalyticsTab from './AnalyticsTab';
import PaymentTab from './PaymentTab';
import LiveHostsTab from './live-host/LiveHostsTab';
import ShiftsTab from './live-host/ShiftsTab';
import CalendarTab from './live-host/CalendarTab';
import ScriptsTab from './live-host/ScriptsTab';
import TrainingTab from './live-host/TrainingTab';

const TAMPILAN = [
  { key: 'hosts', label: 'Host live', icon: Users },
  { key: 'shifts', label: 'Shift', icon: Clock },
  { key: 'calendar', label: 'Kalender', icon: Calendar },
  { key: 'scripts', label: 'Naskah', icon: Video },
  { key: 'training', label: 'Pelatihan', icon: TrendingUp },
  { key: 'analytics', label: 'Analitik', icon: BarChart3 },
  { key: 'payment', label: 'Pembayaran', icon: DollarSign },
];

export default function LiveHostModule({ token }) {
  const [activeTab, setActiveTab] = useState('hosts'); // hosts | shifts | calendar | scripts | training | analytics | payment
  const authH = useMemo(
    () => ({ Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` }),
    [token]
  );

  return (
    <PageLayout testId="livehost-module" title="Host live"
      filters={<FilterChips options={TAMPILAN} value={activeTab} onChange={setActiveTab} hideWhenEmpty={false} testId="livehost-view" ariaLabel="Tampilan" />}>
      {activeTab === 'hosts' && <LiveHostsTab authH={authH} />}
      {activeTab === 'shifts' && <ShiftsTab authH={authH} />}
      {activeTab === 'calendar' && <CalendarTab authH={authH} />}
      {activeTab === 'scripts' && <ScriptsTab authH={authH} />}
      {activeTab === 'training' && <TrainingTab authH={authH} />}
      {activeTab === 'analytics' && <AnalyticsTab authH={authH} />}
      {activeTab === 'payment' && <PaymentTab authH={authH} />}
    </PageLayout>
  );
}

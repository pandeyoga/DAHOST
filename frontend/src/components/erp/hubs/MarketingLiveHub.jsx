import React, { lazy } from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// T3.6 — 3 modul Marketing Live → 1 hub
const LiveSessionModule = lazyRetry(() => import('../marketing/LiveSessionModule'));
const LiveSessionAnalyticsDashboard = lazyRetry(() => import('../marketing/LiveSessionAnalyticsDashboard'));
const LiveHostModule = lazyRetry(() => import('../marketing/LiveHostModule'));

export default function MarketingLiveHub(props) {
  return (
    <HubTabs
      hubId="marketing-live-hub"
      title="Live Selling"
      subtitle="Sesi live, analitik live, dan pengelolaan host live."
      tabs={[
        { key: 'sessions', label: 'Sesi live', Component: LiveSessionModule },
        { key: 'analytics', label: 'Analitik', Component: LiveSessionAnalyticsDashboard },
        { key: 'livehost', label: 'Host live', Component: LiveHostModule },
      ]}
      {...props}
    />
  );
}

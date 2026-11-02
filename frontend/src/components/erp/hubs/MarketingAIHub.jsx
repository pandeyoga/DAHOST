import React, { lazy } from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// T3.4 — modul Marketing AI → 1 hub
// 2026-11-02 (keputusan owner No.61a): tab "Image Generator" DIHAPUS beserta
// endpoint backend-nya. Deep-link lama `marketing-ai-image` jatuh ke tab pertama.
const MarketingAIInsightsDashboard = lazyRetry(() => import('../marketing/MarketingAIInsightsDashboard'));
const AdvancedAIModule = lazyRetry(() => import('../marketing/AdvancedAIModule'));
const AIContentGeneratorModule = lazyRetry(() => import('../marketing/AIContentGeneratorModule'));

export default function MarketingAIHub(props) {
  return (
    <HubTabs
      hubId="marketing-ai-hub"
      tabs={[
        { key: 'insights', label: 'AI Insights', Component: MarketingAIInsightsDashboard },
        { key: 'advanced', label: 'Advanced AI', Component: AdvancedAIModule },
        { key: 'content', label: 'Content Generator', Component: AIContentGeneratorModule },
      ]}
      {...props}
    />
  );
}

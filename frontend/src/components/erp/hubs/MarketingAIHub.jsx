import React, { lazy } from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// T3.4 — 4 modul Marketing AI → 1 hub
const MarketingAIInsightsDashboard = lazyRetry(() => import('../marketing/MarketingAIInsightsDashboard'));
const AdvancedAIModule = lazyRetry(() => import('../marketing/AdvancedAIModule'));
const AIContentGeneratorModule = lazyRetry(() => import('../marketing/AIContentGeneratorModule'));
const AIImageGeneratorModule = lazyRetry(() => import('../marketing/AIImageGeneratorModule'));

export default function MarketingAIHub(props) {
  return (
    <HubTabs
      hubId="marketing-ai-hub"
      tabs={[
        { key: 'insights', label: 'AI Insights', Component: MarketingAIInsightsDashboard },
        { key: 'advanced', label: 'Advanced AI', Component: AdvancedAIModule },
        { key: 'content', label: 'Content Generator', Component: AIContentGeneratorModule },
        { key: 'image', label: 'Image Generator', Component: AIImageGeneratorModule },
      ]}
      {...props}
    />
  );
}

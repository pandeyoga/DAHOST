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
      title="AI Marketing"
      subtitle="Wawasan AI dari data penjualan, analisis lanjutan, dan pembuat konten."
      tabs={[
        { key: 'insights', label: 'Wawasan AI', Component: MarketingAIInsightsDashboard },
        { key: 'advanced', label: 'AI lanjutan', Component: AdvancedAIModule },
        { key: 'content', label: 'Pembuat konten', Component: AIContentGeneratorModule },
      ]}
      {...props}
    />
  );
}

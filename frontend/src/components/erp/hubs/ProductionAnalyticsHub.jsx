import React, { lazy } from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// IA v2.1 — konsolidasi analitik kualitas + performa Produksi -> 1 hub bertab.
// FASE 5: Pareto/FPY (qc engine lama) diarsip.
const RahazaAQLCalculatorModule = lazyRetry(() => import('../RahazaAQLCalculatorModule'));
const RahazaDowntimeModule     = lazyRetry(() => import('../RahazaDowntimeModule'));
const CapacityPlanningModule   = lazyRetry(() => import('../CapacityPlanningModule'));

export default function ProductionAnalyticsHub(props) {
  return (
    <HubTabs
      hubId="prod-analytics-hub"
      title="Analitik Produksi"
      subtitle="Satu pintu analitik kualitas & performa: AQL, Downtime, Kapasitas."
      tabs={[
        { key: 'aql', label: 'AQL Sampling', Component: RahazaAQLCalculatorModule },
        { key: 'downtime', label: 'Downtime', Component: RahazaDowntimeModule },
        { key: 'capacity', label: 'Kapasitas', Component: CapacityPlanningModule },
      ]}
      {...props}
    />
  );
}

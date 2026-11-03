import React from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// 2026-11-04 (owner): Arus Kas satu menu — yang sudah terjadi (buku besar) dan perkiraan ke depan
// (dulu menu "Prediksi Kas" sendiri di Kas & Bank).
const RahazaCashFlowModule = lazyRetry(() => import('../RahazaCashFlowModule'));
const CashFlowAI           = lazyRetry(() => import('../finance/CashFlowAI'));

export default function FinanceCashFlowHub(props) {
  return (
    <HubTabs
      hubId="fin-cashflow"
      title="Arus Kas"
      compactHeaders
      tabs={[
        { key: 'actual', label: 'Sudah terjadi', Component: RahazaCashFlowModule },
        { key: 'forecast', label: 'Perkiraan', Component: CashFlowAI },
      ]}
      {...props}
    />
  );
}

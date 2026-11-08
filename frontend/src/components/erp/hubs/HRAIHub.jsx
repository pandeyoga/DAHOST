import React from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// T3.5 — 5 modul HR AI → 1 hub
// Standar UI/UX v2 (8 Nov 2026): judul hub = nama menu, nama tab berbahasa Indonesia (kunci tab tetap — dipakai
// tautan lama makeRedirect('hr-ai-hub', …)).
const RahazaAIModule = lazyRetry(() => import('../RahazaAIModule'));
const HRAttritionModule = lazyRetry(() => import('../hr/HRAttritionModule'));
const HRSkillGapModule = lazyRetry(() => import('../hr/HRSkillGapModule'));
const HRCoachingModule = lazyRetry(() => import('../hr/HRCoachingModule'));
const AIActionsModule = lazyRetry(() => import('../AIActionsModule'));

export default function HRAIHub(props) {
  return (
    <HubTabs
      hubId="hr-ai-hub"
      title="AI SDM"
      subtitle="Wawasan, prediksi karyawan keluar, kesenjangan keahlian, dan coaching berbasis AI."
      tabs={[
        { key: 'insights', label: 'Wawasan AI', Component: RahazaAIModule },
        { key: 'attrition', label: 'Prediksi keluar', Component: HRAttritionModule },
        { key: 'skill-gap', label: 'Kesenjangan keahlian', Component: HRSkillGapModule },
        { key: 'coaching', label: 'Coaching AI', Component: HRCoachingModule },
        { key: 'actions', label: 'Tindak lanjut', Component: AIActionsModule },
      ]}
      {...props}
    />
  );
}

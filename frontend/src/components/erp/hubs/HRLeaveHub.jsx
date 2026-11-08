import React from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// IA v2.1 fase-2 — konsolidasi cuti & lembur SDM -> 1 hub bertab.
// Standar UI/UX v2 (8 Nov 2026): "Jenis cuti" (dulu tab di dalam tab Cuti) dinaikkan jadi tab hub.
const RahazaOvertimeModule  = lazyRetry(() => import('../RahazaOvertimeModule'));
const RahazaLeaveModule     = lazyRetry(() => import('../RahazaLeaveModule'));
const HRLeaveBalancesModule = lazyRetry(() => import('../HRLeaveBalancesModule'));

export default function HRLeaveHub(props) {
  return (
    <HubTabs
      hubId="hr-leave-hub"
      title="Cuti & Lembur"
      subtitle="Pengajuan lembur dan cuti karyawan, jenis cuti, serta saldo cuti per tahun."
      tabs={[
        { key: 'overtime', label: 'Lembur', Component: RahazaOvertimeModule },
        { key: 'leave', label: 'Cuti', Component: RahazaLeaveModule, props: { bagian: 'pengajuan' } },
        { key: 'types', label: 'Jenis cuti', Component: RahazaLeaveModule, props: { bagian: 'jenis' } },
        { key: 'balances', label: 'Saldo cuti', Component: HRLeaveBalancesModule },
      ]}
      {...props}
    />
  );
}

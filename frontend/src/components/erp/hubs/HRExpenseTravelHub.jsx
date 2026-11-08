import React from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// PHASE B (6.1.4 #2) — 5 menu klaim biaya/perjalanan dinas SDM → 1 hub "Klaim Dinas".
// Standar UI/UX v2 (8 Nov 2026): judul = label menu, nama tab bahasa Indonesia huruf besar hanya di awal.
const EmployeeExpenseModule          = lazyRetry(() => import('../EmployeeExpenseModule'));
const EmployeeTravelModule           = lazyRetry(() => import('../EmployeeTravelModule'));
const EmployeeTravelSettlementModule = lazyRetry(() => import('../EmployeeTravelSettlementModule'));
const EmployeeExpenseApprovalModule  = lazyRetry(() => import('../EmployeeExpenseApprovalModule'));
const EmployeePerDiemAdminModule     = lazyRetry(() => import('../EmployeePerDiemAdminModule'));

export default function HRExpenseTravelHub(props) {
  return (
    <HubTabs
      hubId="hr-expense-hub"
      title="Klaim Dinas"
      subtitle="Klaim biaya, perjalanan dinas, penyelesaian, persetujuan, dan tarif uang harian dalam satu menu."
      tabs={[
        { key: 'claims', label: 'Klaim biaya', Component: EmployeeExpenseModule },
        { key: 'travel', label: 'Perjalanan dinas', Component: EmployeeTravelModule },
        { key: 'settlement', label: 'Penyelesaian perjalanan', Component: EmployeeTravelSettlementModule },
        { key: 'approval', label: 'Persetujuan', Component: EmployeeExpenseApprovalModule },
        { key: 'perdiem', label: 'Tarif uang harian', Component: EmployeePerDiemAdminModule },
      ]}
      {...props}
    />
  );
}

import React, { lazy } from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// PHASE B (6.1.4 #2) — 5 menu HR expense/travel → 1 hub "Expense & Perjalanan Dinas".
const EmployeeExpenseModule          = lazyRetry(() => import('../EmployeeExpenseModule'));
const EmployeeTravelModule           = lazyRetry(() => import('../EmployeeTravelModule'));
const EmployeeTravelSettlementModule = lazyRetry(() => import('../EmployeeTravelSettlementModule'));
const EmployeeExpenseApprovalModule  = lazyRetry(() => import('../EmployeeExpenseApprovalModule'));
const EmployeePerDiemAdminModule     = lazyRetry(() => import('../EmployeePerDiemAdminModule'));

export default function HRExpenseTravelHub(props) {
  return (
    <HubTabs
      hubId="hr-expense-hub"
      title="Expense & Perjalanan Dinas"
      subtitle="Klaim biaya, perjalanan dinas, settlement, approval, dan konfigurasi per-diem — satu pintu."
      tabs={[
        { key: 'claims', label: 'Klaim Biaya Saya', Component: EmployeeExpenseModule },
        { key: 'travel', label: 'Perjalanan Dinas Saya', Component: EmployeeTravelModule },
        { key: 'settlement', label: 'Settlement Perjalanan', Component: EmployeeTravelSettlementModule },
        { key: 'approval', label: 'Approval Klaim & Dinas', Component: EmployeeExpenseApprovalModule },
        { key: 'perdiem', label: 'Konfigurasi Per Diem', Component: EmployeePerDiemAdminModule },
      ]}
      {...props}
    />
  );
}

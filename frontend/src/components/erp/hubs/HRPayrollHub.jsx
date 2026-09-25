import React, { lazy } from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// IA v2.1 fase-2 — konsolidasi penggajian SDM -> 1 hub bertab.
const PayrollDashboardModule       = lazyRetry(() => import('../PayrollDashboardModule'));
const RahazaPayrollProfilesModule  = lazyRetry(() => import('../RahazaPayrollProfilesModule'));
const RahazaPayrollAllowancesModule = lazyRetry(() => import('../RahazaPayrollAllowancesModule'));
const RahazaSalaryAdjustmentModule = lazyRetry(() => import('../RahazaSalaryAdjustmentModule'));
const RahazaPayrollRunModule       = lazyRetry(() => import('../RahazaPayrollRunModule'));

export default function HRPayrollHub(props) {
  return (
    <HubTabs
      hubId="hr-payroll-hub"
      title="Penggajian"
      subtitle="Satu pintu payroll: Dashboard, Profil Gaji, Tunjangan, Penyesuaian, Proses Gaji."
      tabs={[
        { key: 'dashboard', label: 'Dashboard', Component: PayrollDashboardModule },
        { key: 'profiles', label: 'Profil Gaji', Component: RahazaPayrollProfilesModule },
        { key: 'allowances', label: 'Tunjangan', Component: RahazaPayrollAllowancesModule },
        { key: 'adjustments', label: 'Penyesuaian', Component: RahazaSalaryAdjustmentModule },
        { key: 'run', label: 'Proses Gaji', Component: RahazaPayrollRunModule },
      ]}
      {...props}
    />
  );
}

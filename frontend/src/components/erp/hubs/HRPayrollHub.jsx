import React from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// IA v2.1 fase-2 — konsolidasi penggajian SDM -> 1 hub bertab.
// Standar UI/UX v2 (8 Nov 2026): judul = nama menu, nama tab huruf besar hanya di awal.
const PayrollDashboardModule       = lazyRetry(() => import('../PayrollDashboardModule'));
const RahazaPayrollProfilesModule  = lazyRetry(() => import('../RahazaPayrollProfilesModule'));
const RahazaPayrollAllowancesModule = lazyRetry(() => import('../RahazaPayrollAllowancesModule'));
const RahazaSalaryAdjustmentModule = lazyRetry(() => import('../RahazaSalaryAdjustmentModule'));
const RahazaPayrollRunModule       = lazyRetry(() => import('../RahazaPayrollRunModule'));
// 2026-11-02 (K22/K24/K25): SATU layar untuk seluruh rahaza_payroll_settings (API sudah ada, dulu tanpa UI).
const RahazaPayrollSettingsModule  = lazyRetry(() => import('../RahazaPayrollSettingsModule'));

export default function HRPayrollHub(props) {
  return (
    <HubTabs
      hubId="hr-payroll-hub"
      title="Penggajian"
      subtitle="Profil gaji, tunjangan, kenaikan gaji, proses gaji per periode, dan aturannya."
      tabs={[
        { key: 'dashboard', label: 'Dasbor', Component: PayrollDashboardModule },
        { key: 'profiles', label: 'Profil gaji', Component: RahazaPayrollProfilesModule },
        { key: 'allowances', label: 'Tunjangan', Component: RahazaPayrollAllowancesModule },
        { key: 'adjustments', label: 'Penyesuaian gaji', Component: RahazaSalaryAdjustmentModule },
        { key: 'run', label: 'Proses gaji', Component: RahazaPayrollRunModule },
        // 2026-11-08 (keputusan owner): dulu "Pengaturan Payroll"; dikunci uji test_w2e_sdm_payroll_config.
        { key: 'settings', label: 'Pengaturan gaji', Component: RahazaPayrollSettingsModule },
      ]}
      {...props}
    />
  );
}

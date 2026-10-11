import React, { lazy } from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// IA v2.1 — konsolidasi master akuntansi -> 1 hub bertab.
const RahazaCOAModule             = lazyRetry(() => import('../RahazaCOAModule'));
const RahazaPostingProfilesModule = lazyRetry(() => import('../RahazaPostingProfilesModule'));
const EmployeeExpenseGLMappingModule = lazyRetry(() => import('../EmployeeExpenseGLMappingModule'));
const EmployeeExpenseCategoryMasterModule = lazyRetry(() => import('../EmployeeExpenseCategoryMasterModule'));
const RahazaPeriodsModule         = lazyRetry(() => import('../RahazaPeriodsModule'));
const AdminSetupPanelModule       = lazyRetry(() => import('../AdminSetupPanelModule'));
const RahazaCoaAutoModule         = lazyRetry(() => import('../RahazaCoaAutoModule'));
const RahazaOpeningBalanceModule  = lazyRetry(() => import('../finance/RahazaOpeningBalanceModule'));
const RahazaMasterFillModule      = lazyRetry(() => import('../finance/RahazaMasterFillModule'));

export default function FinanceAccountingMasterHub(props) {
  return (
    <HubTabs
      hubId="fin-accounting-master-hub"
      title="Master Akuntansi"
      subtitle="Konfigurasi akuntansi: Bagan Akun, Saldo Awal Go-Live, Profil Posting, Pemetaan GL, Kategori Expense, Periode, Setup."
      tabs={[
        { key: 'coa', label: 'Bagan Akun', Component: RahazaCOAModule },
        { key: 'opening', label: 'Saldo Awal', Component: RahazaOpeningBalanceModule },
        { key: 'fill', label: 'Impor Harga · Rekening · BOM', Component: RahazaMasterFillModule },
        { key: 'posting', label: 'Profil Posting', Component: RahazaPostingProfilesModule },
        { key: 'coa-auto', label: 'Auto Akun (Subledger)', Component: RahazaCoaAutoModule },
        { key: 'glmap', label: 'Pemetaan GL', Component: EmployeeExpenseGLMappingModule },
        { key: 'expcat', label: 'Kategori Expense', Component: EmployeeExpenseCategoryMasterModule },
        { key: 'periods', label: 'Periode', Component: RahazaPeriodsModule },
        { key: 'setup', label: 'Setup Akuntansi', Component: AdminSetupPanelModule },
      ]}
      {...props}
    />
  );
}

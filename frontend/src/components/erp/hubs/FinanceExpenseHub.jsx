import React from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

/**
 * RC-FLOW-UX (de-dup pintu, keputusan user 3b) — Konsolidasi 2 pintu expense di
 * Portal Keuangan menjadi SATU pintu ber-tab:
 *   - "Pengeluaran"     → RahazaExpensesModule       (pengeluaran perusahaan)
 *   - "Klaim karyawan"  → EmployeeExpenseApprovalModule (approve + cairkan klaim karyawan → JE GL)
 *
 * Deep-link lama `fin-expense-settlement` tetap aman: di moduleRegistry ia dipetakan
 * ke makeRedirect('fin-expenses','settlement') sehingga membuka tab settlement.
 * 2026-11-04 (audit Keuangan): judul tidak bertumpuk (compactHeaders), label tab Bahasa Indonesia.
 */
const RahazaExpensesModule          = lazyRetry(() => import('../RahazaExpensesModule'));
const EmployeeExpenseApprovalModule = lazyRetry(() => import('../EmployeeExpenseApprovalModule'));

export default function FinanceExpenseHub(props) {
  return (
    <HubTabs
      hubId="fin-expenses"
      title="Pengeluaran & Klaim"
      compactHeaders
      tabs={[
        { key: 'pengeluaran', label: 'Pengeluaran', Component: RahazaExpensesModule },
        { key: 'settlement', label: 'Klaim karyawan', Component: EmployeeExpenseApprovalModule },
      ]}
      {...props}
    />
  );
}

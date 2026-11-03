import React from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// 2026-11-04 (owner, audit Keuangan): Kasbon (gaji dimuka, lunas lewat potong gaji) dan Uang Muka
// (uang operasional, dipertanggungjawabkan dengan nota — dulu di layar Kas Kecil) satu menu.
const FinanceKasbonModule    = lazyRetry(() => import('../FinanceKasbonModule'));
const EmployeeAdvancesModule = lazyRetry(() => import('../finance/EmployeeAdvancesModule'));

export default function FinanceKasbonHub(props) {
  return (
    <HubTabs
      hubId="fin-kasbon"
      title="Kasbon & Uang Muka"
      compactHeaders
      tabs={[
        { key: 'kasbon', label: 'Kasbon & pinjaman', Component: FinanceKasbonModule },
        { key: 'advances', label: 'Uang muka', Component: EmployeeAdvancesModule },
      ]}
      {...props}
    />
  );
}

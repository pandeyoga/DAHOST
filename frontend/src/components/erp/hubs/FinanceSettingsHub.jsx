import React from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// 2026-11-04 (owner, audit Keuangan tahap 3): semua pengaturan yang jarang disentuh di satu menu,
// terpisah dari halaman kerja. Menggantikan "Master Akuntansi" (9 tab) + menu "Pusat Biaya" +
// pengaturan rekening toko yang dulu ada di tengah halaman Pencairan.
//   · Periode (tutup buku) → Akuntansi › Akrual & Tutup Buku
//   · Setup Akuntansi (seed COA/profil) → Adm. Sistem › Perawatan Data Keuangan
//   · Profil Posting + Auto Akun + Pemetaan GL klaim → satu tab "Pemetaan akun otomatis"
const RahazaCOAModule                     = lazyRetry(() => import('../RahazaCOAModule'));
const RahazaOpeningBalanceModule          = lazyRetry(() => import('../finance/RahazaOpeningBalanceModule'));
const RahazaMasterFillModule              = lazyRetry(() => import('../finance/RahazaMasterFillModule'));
const AccountMappingModule                = lazyRetry(() => import('../finance/AccountMappingModule'));
const StorePayoutLinksModule              = lazyRetry(() => import('../finance/StorePayoutLinksModule'));
const EmployeeExpenseCategoryMasterModule = lazyRetry(() => import('../EmployeeExpenseCategoryMasterModule'));
const RahazaCostCentersModule             = lazyRetry(() => import('../RahazaCostCentersModule'));

export default function FinanceSettingsHub(props) {
  return (
    <HubTabs
      hubId="fin-settings-hub"
      title="Pengaturan Keuangan"
      compactHeaders
      tabs={[
        { key: 'coa', label: 'Bagan akun', Component: RahazaCOAModule },
        { key: 'opening', label: 'Saldo awal', Component: RahazaOpeningBalanceModule },
        { key: 'fill', label: 'Impor go-live', Component: RahazaMasterFillModule },
        { key: 'mapping', label: 'Pemetaan akun otomatis', Component: AccountMappingModule },
        { key: 'storebank', label: 'Rekening toko', Component: StorePayoutLinksModule },
        { key: 'expcat', label: 'Kategori klaim', Component: EmployeeExpenseCategoryMasterModule },
        { key: 'costcenter', label: 'Pusat biaya', Component: RahazaCostCentersModule },
      ]}
      {...props}
    />
  );
}

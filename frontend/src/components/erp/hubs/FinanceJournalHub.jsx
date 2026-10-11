import React, { lazy } from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// T3.3 — fin-journal-entry + fin-journal-list → 1 modul 2 tab
const RahazaJournalEntryModule = lazyRetry(() => import('../RahazaJournalEntryModule'));
const RahazaJournalListModule = lazyRetry(() => import('../RahazaJournalListModule'));
const RahazaJournalImportModule = lazyRetry(() => import('../finance/RahazaJournalImportModule'));  // 2026-09-24 impor Excel

export default function FinanceJournalHub(props) {
  return (
    <HubTabs
      hubId="fin-journal-hub"
      tabs={[
        { key: 'entry', label: 'Jurnal Umum', Component: RahazaJournalEntryModule },
        { key: 'list', label: 'Daftar Jurnal', Component: RahazaJournalListModule },
        { key: 'import', label: 'Impor Jurnal (Excel)', Component: RahazaJournalImportModule },
      ]}
      {...props}
    />
  );
}

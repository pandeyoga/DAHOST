import React from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// T3.3 — fin-journal-entry + fin-journal-list → 1 modul.
// 2026-11-04 (audit Keuangan): dua daftar jurnal yang sama ("Jurnal Umum" & "Daftar Jurnal") menjadi SATU
// daftar berpaginasi (RahazaJournalEntryModule, + Jurnal baru di halaman yang sama). Kunci tab 'list'
// dipertahankan untuk deep-link lama; 'entry' dialihkan ke 'list' di moduleRegistry.
const RahazaJournalEntryModule  = lazyRetry(() => import('../RahazaJournalEntryModule'));
const RahazaJournalImportModule = lazyRetry(() => import('../finance/RahazaJournalImportModule'));  // 2026-09-24 impor Excel

export default function FinanceJournalHub(props) {
  return (
    <HubTabs
      hubId="fin-journal-hub"
      title="Jurnal"
      compactHeaders
      tabs={[
        { key: 'list', label: 'Daftar jurnal', Component: RahazaJournalEntryModule },
        { key: 'import', label: 'Impor dari Excel', Component: RahazaJournalImportModule },
      ]}
      {...props}
    />
  );
}

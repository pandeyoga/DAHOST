import React from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// IA v2.1 fase-2 — konsolidasi manajemen shift SDM -> 1 hub bertab.
// Standar UI/UX v2 (8 Nov 2026): tab di dalam modul (Template/Assignment, Jadwal/Template) dinaikkan jadi tab hub
// supaya tidak ada tab di dalam tab; modul yang sama dipakai dengan prop `bagian`.
// Tahap C audit HR (9 Nov 2026): "Jadwal otomatis" (tidak pernah bisa jalan) → Roster kalender; "Pola jadwal"
// (master shift kedua) → Pola rotasi yang memakai Daftar shift; + Permintaan ganti/tukar shift dari Portal Saya.
// Kunci tab lama `schedule` & `pattern` dipakai lagi supaya tautan lama tetap mendarat di tempat yang benar.
const HRShiftManagementModule = lazyRetry(() => import('../HRShiftManagementModule'));
const ShiftRosterModule       = lazyRetry(() => import('../hr/ShiftRosterModule'));
const ShiftPolaModule         = lazyRetry(() => import('../hr/ShiftPolaModule'));
const ShiftPermintaanModule   = lazyRetry(() => import('../hr/ShiftPermintaanModule'));

export default function HRShiftHub(props) {
  return (
    <HubTabs
      hubId="hr-shift-hub"
      title="Shift"
      subtitle="Roster shift karyawan, daftar shift, penugasan, pola rotasi, dan permintaan tukar shift."
      tabs={[
        { key: 'schedule', label: 'Roster', Component: ShiftRosterModule },
        { key: 'manage', label: 'Daftar shift', Component: HRShiftManagementModule, props: { bagian: 'shifts' } },
        { key: 'assign', label: 'Penugasan shift', Component: HRShiftManagementModule, props: { bagian: 'assignments' } },
        { key: 'pattern', label: 'Pola rotasi', Component: ShiftPolaModule },
        { key: 'request', label: 'Permintaan shift', Component: ShiftPermintaanModule },
      ]}
      {...props}
    />
  );
}

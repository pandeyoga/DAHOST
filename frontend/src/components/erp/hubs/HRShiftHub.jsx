import React from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// IA v2.1 fase-2 — konsolidasi manajemen shift SDM -> 1 hub bertab.
// Standar UI/UX v2 (8 Nov 2026): tab di dalam modul (Template/Assignment, Jadwal/Template) dinaikkan jadi tab hub
// supaya tidak ada tab di dalam tab; modul yang sama dipakai dengan prop `bagian`.
const HRShiftManagementModule = lazyRetry(() => import('../HRShiftManagementModule'));
const ShiftSchedulerModule    = lazyRetry(() => import('../hr/ShiftSchedulerModule'));

export default function HRShiftHub(props) {
  return (
    <HubTabs
      hubId="hr-shift-hub"
      title="Shift"
      subtitle="Daftar shift kerja, penugasan ke karyawan, dan jadwal shift otomatis."
      tabs={[
        { key: 'manage', label: 'Daftar shift', Component: HRShiftManagementModule, props: { bagian: 'shifts' } },
        { key: 'assign', label: 'Penugasan shift', Component: HRShiftManagementModule, props: { bagian: 'assignments' } },
        { key: 'schedule', label: 'Jadwal otomatis', Component: ShiftSchedulerModule, props: { bagian: 'schedules' } },
        { key: 'pattern', label: 'Pola jadwal', Component: ShiftSchedulerModule, props: { bagian: 'templates' } },
      ]}
      {...props}
    />
  );
}

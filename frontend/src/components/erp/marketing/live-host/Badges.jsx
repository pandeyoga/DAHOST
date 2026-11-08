/**
 * Shared status badges for LiveHost Management module.
 */

import { StatusBadge as Lencana } from '../../moduleAtoms';

// Standar UI/UX v2 (8 Nov 2026): satu bentuk lencana (StatusBadge) + label Indonesia.
export const LABEL_STATUS_HOST = { active: 'Aktif', inactive: 'Nonaktif', on_leave: 'Cuti' };
export const LABEL_KEHADIRAN = { scheduled: 'Terjadwal', on_time: 'Tepat waktu', late: 'Terlambat', no_show: 'Tidak hadir', completed: 'Selesai' };
export const LABEL_JENIS_KERJA = { full_time: 'Penuh waktu', part_time: 'Paruh waktu', freelance: 'Lepas', contract: 'Kontrak' };

export const StatusBadge = ({ status }) => {
  const tone = { active: 'success', inactive: 'muted', on_leave: 'warning' }[status] || 'muted';
  return <Lencana status={status} label={LABEL_STATUS_HOST[status] || LABEL_STATUS_HOST.inactive} tone={tone} />;
};

export const AttendanceBadge = ({ status }) => {
  const tone = { scheduled: 'info', on_time: 'success', late: 'warning', no_show: 'danger', completed: 'success' }[status] || 'info';
  return <Lencana status={status} label={LABEL_KEHADIRAN[status] || LABEL_KEHADIRAN.scheduled} tone={tone} />;
};

export const EmploymentTypeBadge = ({ type }) => (
  <Lencana status={type} label={LABEL_JENIS_KERJA[type] || LABEL_JENIS_KERJA.part_time} tone={type === 'contract' ? 'warning' : 'muted'} />
);

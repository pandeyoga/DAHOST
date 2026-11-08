import { Calendar } from 'lucide-react';
import { EmptyState } from '../../moduleAtoms';

/** Kalender shift — belum dibuat (Standar UI/UX v2: tampilan kosong standar, bahasa Indonesia). */
export default function CalendarTab() {
  return (
    <EmptyState icon={Calendar} title="Kalender shift segera hadir"
      description="Tampilan kalender mingguan/bulanan untuk shift akan dibuat pada tahap berikutnya. Sementara itu, lihat tab Shift." />
  );
}

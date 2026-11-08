/**
 * ActivityFeed.jsx — aliran aktivitas terbaru Portal Kolaborasi (daftar kursus, materi selesai, tugas, dokumen).
 *
 * Standar UI/UX v2 (8 Nov 2026): kartu standar, pilihan rentang hari = FilterChips, jenis = StatusBadge (token
 * warna; dulu kelas green/blue/amber), tanpa emoji hiasan & ukuran huruf 10 px. Sumber & perilaku klik sama.
 */
import { useState, useEffect, useCallback } from 'react';
import { formatDistanceToNow } from 'date-fns';
import { id as localeId } from 'date-fns/locale';
import { Activity, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import FilterChips from '@/components/ui/filter-chips';
import apiFetch from '@/lib/apiFetch';
import { EmptyState, StatusBadge } from '../../moduleAtoms';

function timeAgo(ts) {
  if (!ts) return '';
  try {
    return formatDistanceToNow(new Date(ts), { addSuffix: true, locale: localeId });
  } catch {
    return '';
  }
}

const TYPE_META = {
  course_enroll: ['Daftar kursus', 'success'],
  material_complete_video: ['Video', 'info'],
  material_complete_text: ['Teks', 'info'],
  material_complete_pdf: ['PDF', 'warning'],
  material_complete_quiz: ['Kuis', 'warning'],
  material_complete_assignment: ['Tugas', 'warning'],
  assignment_submit: ['Tugas', 'warning'],
  document_update: ['Dokumen', 'muted'],
  message: ['Pesan', 'primary'],
};

export default function ActivityFeed({ onNavigate }) {
  const [activities, setActivities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(7);

  const fetchFeed = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch(`/collab/activity-feed?limit=20&days=${days}`);
      setActivities(data.activities || []);
    } catch {
      // diam — aliran aktivitas opsional
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => { fetchFeed(); }, [fetchFeed]);

  const handleActivityClick = (activity) => {
    if (!onNavigate) return;
    if (activity.subject_type === 'course') onNavigate('course-detail', { courseId: activity.subject_id });
    else if (activity.subject_type === 'document') onNavigate('workspace');
  };

  return (
    <GlassCard className="space-y-3 p-4" data-testid="activity-feed">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-base font-semibold text-foreground">Aktivitas terkini</p>
        <div className="flex items-center gap-2">
          <FilterChips value={String(days)} onChange={(v) => setDays(Number(v))} hideWhenEmpty={false} ariaLabel="Rentang hari"
            options={[3, 7, 14].map((d) => ({ key: String(d), label: `${d} hari` }))} />
          <Button variant="ghost" size="icon-sm" onClick={fetchFeed} title="Perbarui" aria-label="Perbarui aktivitas">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
        </div>
      </div>
      {loading ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat aktivitas…</p>
      ) : activities.length === 0 ? (
        <EmptyState icon={Activity} className="py-8" title={`Belum ada aktivitas dalam ${days} hari terakhir`} />
      ) : (
        <div className="max-h-80 divide-y divide-[var(--glass-border)] overflow-y-auto pr-1">
          {activities.map((activity) => {
            const [label, tone] = TYPE_META[activity.type] || [activity.type, 'default'];
            return (
              <Button key={activity.id} type="button" variant="ghost" onClick={() => handleActivityClick(activity)}
                data-testid={`activity-item-${activity.type}`}
                className="h-auto w-full items-start justify-start gap-3 whitespace-normal rounded-none px-2 py-2 text-left font-normal">
                <span className="mt-0.5 shrink-0 text-base" aria-hidden="true">{activity.icon}</span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm">
                    <span className="font-medium">{activity.actor_name}</span>{' '}
                    <span className="text-muted-foreground">{activity.action}</span>{' '}
                    <span className="font-medium">{activity.subject}</span>
                  </span>
                  <span className="mt-0.5 flex items-center gap-2">
                    <StatusBadge status={activity.type} label={label} tone={tone} />
                    <span className="text-xs text-muted-foreground">{timeAgo(activity.timestamp)}</span>
                  </span>
                </span>
              </Button>
            );
          })}
        </div>
      )}
    </GlassCard>
  );
}

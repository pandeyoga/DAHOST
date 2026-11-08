/**
 * AnnouncementBoard — papan pengumuman di halaman pilih portal.
 *
 * 2026-11-08 (uji ketajaman UI/UX):
 *  • Hanya pengumuman untuk portal yang BISA dibuka orang itu (`portalIds`) atau untuk semua portal.
 *    Dulu "Tampil untuk" di form tidak berpengaruh: semua orang melihat semua pengumuman.
 *  • Warna memakai token; label Indonesia; "Tutup" diingat per peramban sampai pengumuman berubah.
 */
import { useState, useEffect } from 'react';
import { X, Info, CheckCircle2, AlertTriangle, AlertCircle, ChevronDown, ChevronUp } from 'lucide-react';
import { cn } from '@/lib/utils';

const API = process.env.REACT_APP_BACKEND_URL;
const KUNCI_TUTUP = 'papan_pengumuman_ditutup';

export const JENIS_PENGUMUMAN = {
  info: { label: 'Informasi', icon: Info, tone: 'info',
    kelas: 'border-[hsl(var(--info)/0.35)] bg-[hsl(var(--info)/0.08)] text-foreground', ikon: 'text-[hsl(var(--info))]' },
  success: { label: 'Kabar baik', icon: CheckCircle2, tone: 'success',
    kelas: 'border-[hsl(var(--success)/0.35)] bg-[hsl(var(--success)/0.08)] text-foreground', ikon: 'text-[hsl(var(--success))]' },
  warning: { label: 'Peringatan', icon: AlertTriangle, tone: 'warning',
    kelas: 'border-[hsl(var(--warning)/0.4)] bg-[hsl(var(--warning)/0.10)] text-foreground', ikon: 'text-[hsl(var(--warning))]' },
  urgent: { label: 'Penting', icon: AlertCircle, tone: 'danger',
    kelas: 'border-[hsl(var(--destructive)/0.4)] bg-[hsl(var(--destructive)/0.08)] text-foreground', ikon: 'text-[hsl(var(--destructive))]' },
};

const bacaTutup = () => {
  try { return new Set(JSON.parse(localStorage.getItem(KUNCI_TUTUP) || '[]')); } catch { return new Set(); }
};
const simpanTutup = (s) => {
  try { localStorage.setItem(KUNCI_TUTUP, JSON.stringify([...s].slice(-200))); } catch { /* abaikan */ }
};
// kunci tutup ikut versi pengumuman: bila diubah, tampil lagi
const kunciTutup = (a) => `${a.id}:${a.updated_at || a.created_at || ''}`;

/** Satu pengumuman seperti tampil di papan (dipakai juga untuk pratinjau di Portal SDM). */
export function AnnouncementItem({ announcement, onDismiss }) {
  const [expanded, setExpanded] = useState(false);
  const j = JENIS_PENGUMUMAN[announcement.type] || JENIS_PENGUMUMAN.info;
  const Icon = j.icon;
  const panjang = (announcement.content || '').length > 160;
  const isi = expanded || !panjang ? announcement.content : `${announcement.content.slice(0, 160)}…`;
  return (
    <div className={cn('rounded-lg border p-4', j.kelas)} data-testid={`papan-pengumuman-${announcement.id}`}>
      <div className="flex items-start gap-3">
        <Icon size={20} className={cn('mt-0.5 shrink-0', j.ikon)} />
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex items-start justify-between gap-2">
            <h4 className="text-sm font-semibold leading-tight">{announcement.title}</h4>
            {onDismiss && (
              <button type="button" onClick={() => onDismiss(announcement)} aria-label="Tutup pengumuman"
                title="Tutup pengumuman" className="shrink-0 text-muted-foreground transition hover:text-foreground">
                <X size={16} />
              </button>
            )}
          </div>
          <p className="whitespace-pre-line text-sm leading-relaxed text-foreground/85">{isi}</p>
          {panjang && (
            <button type="button" onClick={() => setExpanded(!expanded)}
              className="flex items-center gap-1 text-xs font-medium text-primary hover:underline">
              {expanded ? <>Tampilkan lebih sedikit <ChevronUp size={14} /></> : <>Selengkapnya <ChevronDown size={14} /></>}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default function AnnouncementBoard({ portalIds }) {
  const [announcements, setAnnouncements] = useState([]);
  const [ditutup, setDitutup] = useState(bacaTutup);

  useEffect(() => {
    const token = localStorage.getItem('erp_token');
    if (!token) return;
    fetch(`${API}/api/announcements/active`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => setAnnouncements((Array.isArray(data) ? data : []).sort((a, b) => b.priority - a.priority)))
      .catch(() => setAnnouncements([]));
  }, []);

  const bolehLihat = (a) => {
    const t = a.target_portals || ['all'];
    if (t.includes('all') || !Array.isArray(portalIds)) return true;
    return t.some((p) => portalIds.includes(p));
  };
  const tampil = announcements.filter((a) => bolehLihat(a) && !ditutup.has(kunciTutup(a)));
  if (tampil.length === 0) return null;

  const tutup = (a) => {
    const s = new Set(ditutup);
    s.add(kunciTutup(a));
    setDitutup(s);
    simpanTutup(s);
  };
  return (
    <div className="mx-auto mb-8 w-full max-w-3xl space-y-3" data-testid="papan-pengumuman">
      {tampil.map((a) => <AnnouncementItem key={a.id} announcement={a} onDismiss={tutup} />)}
    </div>
  );
}

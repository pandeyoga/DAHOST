/**
 * PageHeader \u2014 Tahap 3 Module Polish atom.
 * Hero kecil untuk CRUD modules: title + subtitle (optional) + actions.
 * Konsisten di seluruh modul, dual-theme aware.
 */
import { createContext, isValidElement, useContext } from 'react';
import { Button } from '@/components/ui/button';
import { createPortal } from 'react-dom';
import { cn } from '@/lib/utils';

/**
 * 2026-11-04 (audit Keuangan "judul bertumpuk"): modul yang dirender sebagai tab di dalam hub yang
 * meminta `compactHeaders` tidak mengulang judul/penjelasan — judul hub + nama tab sudah menjelaskan.
 * PageHeader lalu hanya menampilkan tombol aksinya. Modul dengan header buatan sendiri dapat membaca
 * konteks ini lewat `useInCompactHub()`.
 */
export const CompactHubContext = createContext(false);
export const useInCompactHub = () => useContext(CompactHubContext);
/** Wadah DOM di baris tab hub (sisi kanan) — tempat aksi modul yang dibuka sebagai tab (PANDUAN_UI G2). */
export const HubActionsContext = createContext(null);

/**
 * HubActions — aksi modul. Di dalam hub (`compactHeaders`) dipindah ke baris tab hub supaya tidak ada
 * baris yang hanya berisi tombol; di luar hub tampil di tempatnya.
 */
export function HubActions({ children, className }) {
  const compact = useContext(CompactHubContext);
  const slot = useContext(HubActionsContext);
  if (!children) return null;
  if (compact && slot) return createPortal(<>{children}</>, slot);
  return <div className={cn('flex items-center justify-end gap-2 flex-wrap', className)}>{children}</div>;
}

export function PageHeader({ title, subtitle, actions, className, testId }) {
  // PANDUAN_UI G2 (2026-11-04): kepala halaman POLOS — judul 24 px + satu baris penjelasan + aksi di kanan.
  // Dulu berbentuk kartu bercahaya dengan ikon & "eyebrow" (prop `icon`/`eyebrow` kini diabaikan).
  const compact = useContext(CompactHubContext);
  if (compact) return actions ? <HubActions className={className}>{actions}</HubActions> : null;
  return (
    <div data-testid={testId} className={cn('flex items-start justify-between gap-4 flex-wrap', className)}>
      <div className="min-w-0 flex-1">
        {/* Standar UI/UX v2: kepala tipis — di HP judul lebih kecil & keterangan disembunyikan. */}
        <h1 className="text-xl sm:text-2xl font-bold text-foreground tracking-tight leading-tight">{title}</h1>
        {subtitle && <p className="hidden sm:block text-sm text-muted-foreground mt-1 leading-relaxed max-w-3xl">{subtitle}</p>}
      </div>
      {/* v2: di HP tombol kepala turun ke baris sendiri dan boleh membungkus (dulu terdorong keluar layar) */}
      {actions && <div className="flex items-center gap-2 flex-wrap max-sm:w-full sm:shrink-0">{actions}</div>}
    </div>
  );
}

/**
 * StatTile — smaller KPI tile untuk summary di atas tabel (Tahap 3).
 * Lebih ringan dari StatCard, tanpa icon box.
 *
 * Phase 12.4 — Drill-down: bila `onClick` prop diberikan, tile jadi button
 * dengan hover/focus states supaya user bisa klik untuk navigasi detail.
 */
export function StatTile({ label, value, accent = 'default', className, testId, suffix, onClick, hint, sub, subTone }) {
  const colors = {
    default: 'text-foreground',
    primary: 'text-[hsl(var(--primary))]',
    success: 'text-[hsl(var(--success))]',
    warning: 'text-[hsl(var(--warning))]',
    danger:  'text-[hsl(var(--destructive))]',
    muted:   'text-foreground/60',
  };
  const isClickable = !!onClick;
  const Tag = isClickable ? 'button' : 'div';
  // PANDUAN_UI G5/G8: angka nol tidak diberi warna (dulu "Rp 0" bisa merah/hijau)
  if (/^(Rp\s?)?[-−]?0([.,]0+)?$/.test(String(value ?? '').trim())) accent = 'muted';
  return (
    <Tag
      data-testid={testId}
      onClick={onClick}
      type={isClickable ? 'button' : undefined}
      title={hint || (isClickable ? 'Klik untuk lihat detail' : undefined)}
      className={cn(
        'rounded-[var(--radius-md)] border px-4 py-3 text-left w-full',
        'bg-[var(--card-surface)] border-[var(--glass-border)]',
        'backdrop-blur-[var(--glass-blur)]',
        isClickable && 'cursor-pointer transition-[transform,border-color,box-shadow] duration-150 ease-out hover:border-[hsl(var(--primary)/0.45)] hover:-translate-y-[1px] hover:shadow-[var(--shadow-card)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))] active:scale-[0.98]',
        className
      )}
    >
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <p className={cn('text-xl font-bold tracking-tight mt-1 tabular-nums', colors[accent] || colors.default)}>
        {value}{suffix && <span className="text-sm text-foreground/50 ml-1">{suffix}</span>}
      </p>
      {/* 2026-11-04: baris keterangan kecil di bawah angka (mis. "Rp 2 jt lewat jatuh tempo") — tanpa kartu buatan */}
      {sub && <p className={cn('text-xs mt-1 line-clamp-2', subTone ? colors[subTone] : 'text-muted-foreground')}>{sub}</p>}
      {/* v2 (keputusan 9): keterangan arti angka selalu tampil — dulu hanya bila kartu bisa diklik */}
      {hint && !sub && (
        <p className="mt-1 truncate text-xs text-muted-foreground">{hint}{isClickable ? ' →' : ''}</p>
      )}
    </Tag>
  );
}

/**
 * Notice \u2014 SATU bentuk kotak pemberitahuan (peringatan / galat / berhasil / info) \u2014 2026-11-04.
 * Pengganti <div className="\u2026 bg-amber-\u2026 border-amber-\u2026"> buatan sendiri di tiap layar (KARTU-BUATAN).
 *   <Notice tone="warning" icon={AlertTriangle} title="3 tagihan belum dijurnal">Perbaiki di \u2026</Notice>
 */
const NOTICE_TONE = {
  warning: 'border-[hsl(var(--warning)/0.35)] bg-[hsl(var(--warning)/0.08)] text-[hsl(var(--warning))]',
  danger: 'border-[hsl(var(--destructive)/0.35)] bg-[hsl(var(--destructive)/0.08)] text-[hsl(var(--destructive))]',
  success: 'border-[hsl(var(--success)/0.35)] bg-[hsl(var(--success)/0.08)] text-[hsl(var(--success))]',
  info: 'border-[var(--glass-border)] bg-[var(--card-surface)] text-foreground',
};
export function Notice({ tone = 'warning', icon: Icon, title, children, action, className, testId }) {
  return (
    <div role={tone === 'danger' ? 'alert' : 'status'} data-testid={testId}
      className={cn('rounded-[var(--radius-md)] border px-4 py-3 text-sm flex items-start gap-2', NOTICE_TONE[tone] || NOTICE_TONE.info, className)}>
      {Icon && <Icon className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" />}
      <div className="min-w-0 flex-1">
        {title && <p className="font-medium">{title}</p>}
        {children && <div className={cn(title && 'mt-0.5', 'text-foreground/80')}>{children}</div>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

/**
 * StatusBadge \u2014 pill badge untuk status lifecycle (draft/sent/paid/finalized/etc).
 * Auto-map common statuses to colors; accepts custom tone override.
 */
// 2026-11-04 (audit Keuangan tahap 2): kode status yang maknanya sama di semua portal ditampilkan
// dalam bahasa Indonesia. Kode bermakna ganda ('sent' = terbit/terkirim, 'issued') TIDAK diterjemahkan
// di sini — layar yang memakainya mengirim `label` sendiri (mis. `finStatus()` di lib/financeLabels).
const STATUS_LABEL_ID = {
  draft: 'Draf', approved: 'Disetujui', rejected: 'Ditolak', pending: 'Menunggu', posted: 'Terposting',
  paid: 'Lunas', partial_paid: 'Dibayar sebagian', overdue: 'Lewat jatuh tempo', cancelled: 'Dibatalkan',
  voided: 'Dibatalkan', void: 'Dibatalkan', completed: 'Selesai', written_off: 'Dihapusbukukan',
  closed: 'Ditutup', locked: 'Dikunci', open: 'Terbuka',
};

export function StatusBadge({ status, label, tone, className, testId }) {
  const s = (status || '').toLowerCase();
  const autoTone =
    s === 'draft' ? 'muted' :
    s === 'sent' || s === 'released' || s === 'in_production' || s === 'confirmed' ? 'info' :
    s === 'partial_paid' || s === 'partial' ? 'warning' :
    s === 'paid' || s === 'finalized' || s === 'completed' || s === 'issued' ? 'success' :
    s === 'overdue' || s === 'cancelled' || s === 'rejected' ? 'danger' :
    s === 'hadir' ? 'success' :
    s === 'izin' || s === 'sakit' || s === 'cuti' || s === 'libur' ? 'info' :
    s === 'alfa' || s === 'alpa' ? 'danger' :   // 'alpa' = status kontrak payroll (Tahap 2)
    'default';
  const final = tone || autoTone;
  const toneClass = {
    default: 'bg-[var(--glass-bg)] text-foreground/70 border-[var(--glass-border)]',
    muted:   'bg-[var(--glass-bg)] text-muted-foreground border-[var(--glass-border)]',
    // Standar UI/UX v2: teks memakai token --*-text (kontras ≥ 4.5 di semua tema); latar tetap tipis.
    info:    'bg-[hsl(var(--info)/0.12)] text-[hsl(var(--info-text))] border-[hsl(var(--info)/0.3)]',
    success: 'bg-[hsl(var(--success)/0.12)] text-[hsl(var(--success-text))] border-[hsl(var(--success)/0.3)]',
    warning: 'bg-[hsl(var(--warning)/0.14)] text-[hsl(var(--warning-text))] border-[hsl(var(--warning)/0.35)]',
    danger:  'bg-[hsl(var(--destructive)/0.10)] text-[hsl(var(--danger-text))] border-[hsl(var(--destructive)/0.3)]',
    primary: 'bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))] border-[hsl(var(--primary)/0.25)]',
  }[final] || 'bg-[var(--glass-bg)] text-foreground/70';
  return (
    <span
      data-testid={testId}
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium border whitespace-nowrap',
        toneClass,
        className
      )}
    >
      {label || STATUS_LABEL_ID[s] || status || '-'}
    </span>
  );
}

/**
 * EmptyState \u2014 konsisten empty state untuk semua modul.
 */
export function EmptyState({ icon: Icon, title, description, action, className, testId }) {
  return (
    <div
      data-testid={testId}
      className={cn(
        'flex flex-col items-center justify-center py-16 px-6 text-center',
        className
      )}
    >
      {Icon && (
        <div className="mb-4 w-14 h-14 rounded-2xl bg-[var(--glass-bg)] border border-[var(--glass-border)] grid place-items-center">
          <Icon className="w-6 h-6 text-foreground/40" strokeWidth={1.5} />
        </div>
      )}
      <p className="text-sm font-semibold text-foreground">{title}</p>
      {description && <p className="text-xs text-foreground/50 mt-1 max-w-sm">{description}</p>}
      {/* `action` boleh elemen ATAU { label, onClick } (sama dengan EmptyState.jsx) — 2026-11-04 */}
      {action && <div className="mt-4">{isValidElement(action) || typeof action !== 'object'
        ? action
        : <Button onClick={action.onClick} variant={action.variant || 'default'} data-testid={action.testId || 'empty-state-action'}>
            {action.icon && <action.icon className="w-4 h-4" />}{action.label}
          </Button>}</div>}
    </div>
  );
}

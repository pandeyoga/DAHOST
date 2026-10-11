// Ringkasan izin granular untuk menu yang sedang dibuka (hanya muncul bila owner
// sudah mengatur izin per modul untuk portal ini dan aksesnya tidak penuh).
import { ShieldCheck } from 'lucide-react';
import { moduleActions } from '../portalAccess';

const LABELS = { view: 'Lihat', create: 'Tambah', edit: 'Ubah', delete: 'Hapus', approve: 'Approve', export: 'Export' };
const WRITE = ['create', 'edit', 'delete', 'approve'];

export default function ModuleAccessBadge({ moduleId }) {
  const acts = moduleActions(moduleId);
  if (!acts || !acts.includes('view') || WRITE.every((a) => acts.includes(a))) return null;
  const readOnly = !WRITE.some((a) => acts.includes(a));
  return (
    <div
      className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-[var(--glass-border)] bg-[var(--card-surface)] px-3 py-2 text-xs text-foreground/70"
      data-testid="module-access-badge"
    >
      <ShieldCheck className="h-3.5 w-3.5 text-[hsl(var(--primary))]" />
      <span className="font-medium text-foreground" data-testid="module-access-mode">
        {readOnly ? 'Mode lihat saja' : 'Akses terbatas'}
      </span>
      <span className="text-foreground/50">· izin Anda:</span>
      {acts.map((a) => (
        <span key={a} className="rounded border border-[var(--glass-border)] px-1.5 py-0.5 text-[10px]"
              data-testid={`module-access-action-${a}`}>
          {LABELS[a] || a}
        </span>
      ))}
    </div>
  );
}

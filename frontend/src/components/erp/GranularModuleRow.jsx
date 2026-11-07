// Baris matriks izin granular per modul: Lihat / Tambah / Ubah / Hapus / Setujui / Unduh.
// Standar UI/UX v2 (8 Nov 2026): ukuran huruf 12 px (dulu 10–11 px), warna token, label Indonesia.
import { Check } from 'lucide-react';

const ACTION_ORDER = ['view', 'create', 'edit', 'delete', 'approve', 'export'];
const ACTION_LABEL = { view: 'Lihat', create: 'Tambah', edit: 'Ubah', delete: 'Hapus', approve: 'Setujui', export: 'Unduh' };

export default function GranularModuleRow({ mod, permSet, canEdit, onToggle, levelControl }) {
  const byAction = Object.fromEntries(
    mod.permissions.filter((p) => p.key.startsWith('mod.')).map((p) => [p.action, p]),
  );
  const extras = mod.permissions.filter((p) => !p.key.startsWith('mod.'));
  return (
    <div className="rounded-lg border border-[var(--glass-border)] p-2.5" data-testid={`perm-module-${mod.id}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <span className="text-sm font-medium text-foreground">{mod.label}</span>
          {mod.lookup && (
            <span className="ml-2 text-xs text-muted-foreground" title="Data acuan: daftar tetap terbaca untuk dropdown lintas portal">
              · data acuan
            </span>
          )}
        </div>
        {levelControl}
      </div>
      <div className="mt-2 grid grid-cols-3 gap-1.5 sm:grid-cols-6">
        {ACTION_ORDER.map((a) => {
          const p = byAction[a];
          if (!p) {
            return <span key={a} className="rounded-md border border-dashed border-[var(--glass-border)] px-2 py-1 text-center text-xs text-muted-foreground">—</span>;
          }
          const on = permSet.has(p.key);
          return (
            <button
              key={a} type="button" disabled={!canEdit} onClick={() => onToggle(p.key)}
              title={p.description} aria-pressed={on} data-testid={`perm-${p.key}`}
              className={`inline-flex items-center justify-center gap-1 rounded-md border px-2 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60 ${
                on ? 'border-primary bg-primary/15 text-primary'
                  : 'border-[var(--glass-border)] text-muted-foreground hover:border-[hsl(var(--primary)/0.4)] hover:text-foreground'
              }`}
            >
              {on && <Check className="h-3 w-3" />}
              {ACTION_LABEL[a]}
            </button>
          );
        })}
      </div>
      {extras.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {extras.map((p) => {
            const on = permSet.has(p.key);
            return (
              <button
                key={p.key} type="button" disabled={!canEdit} onClick={() => onToggle(p.key)}
                title={p.description} aria-pressed={on} data-testid={`perm-${p.key}`}
                className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs transition-colors disabled:opacity-60 ${
                  on ? 'border-primary bg-primary/15 text-primary' : 'border-[var(--glass-border)] text-muted-foreground hover:text-foreground'
                }`}
              >
                {on && <Check className="h-3 w-3" />}
                {p.description}
                <span className="opacity-60">· khusus</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

/**
 * OrgNode — satu cabang bagan Struktur Organisasi (Portal SDM).
 *
 * Standar UI/UX v2 (8 Nov 2026): dulu tiap unit berupa kotak berwarna sendiri-sendiri (warna hex per tipe),
 * kini baris rapat bertingkat di dalam satu kartu: panah buka/tutup, nama, tipe, kode, kepala unit, dan
 * jumlah karyawan terisi/target. Klik baris → popup detail unit (`onPilih`).
 * Pohon diratakan dulu (tanpa rekursi komponen), dua tingkat teratas terbuka saat pertama tampil.
 */
import { useState } from 'react';
import { ChevronRight, ChevronDown } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { StatusBadge } from './moduleAtoms';

export const TYPE_LABEL = {
  company: 'Perusahaan', division: 'Divisi', department: 'Departemen', team: 'Tim', section: 'Seksi',
};

export function TypeBadge({ type }) {
  return <StatusBadge status={type} label={TYPE_LABEL[type] || 'Unit'} tone="default" />;
}

/** Keadaan jumlah karyawan satu unit terhadap targetnya. */
export function statusTarget(actual, target) {
  const a = Number(actual || 0);
  const t = Number(target || 0);
  if (!t) return { label: 'Tanpa target', tone: 'muted' };
  if (a === t) return { label: 'Sesuai target', tone: 'success' };
  if (a < t) return { label: `Kurang ${t - a}`, tone: 'warning' };
  return { label: `Lebih ${a - t}`, tone: 'info' };
}

function flattenTree(node, depth = 0, parentId = null, result = []) {
  if (!node) return result;
  const kids = node.children || [];
  result.push({ ...node, depth, parentId, hasChildren: kids.length > 0 });
  kids.forEach((child) => flattenTree(child, depth + 1, node.unit_id, result));
  return result;
}

export function OrgNode({ node, onPilih }) {
  const flat = flattenTree(node);
  const [expanded, setExpanded] = useState(
    () => new Set(flat.filter((n) => n.depth < 2 && n.hasChildren).map((n) => n.unit_id)),
  );
  const toggle = (id) => setExpanded((s) => {
    const next = new Set(s);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  // Baris tampil bila semua leluhurnya terbuka.
  const visible = new Set();
  const rows = flat.filter((n) => {
    const ok = n.depth === 0 || (visible.has(n.parentId) && expanded.has(n.parentId));
    if (ok) visible.add(n.unit_id);
    return ok;
  });

  return rows.map((n) => {
    const open = expanded.has(n.unit_id);
    const st = statusTarget(n.headcount_actual, n.headcount_target);
    return (
      <div key={n.unit_id} role="button" tabIndex={0} data-testid={`org-node-${n.unit_id}`}
        onClick={() => onPilih?.(n)} onKeyDown={(e) => { if (e.key === 'Enter') onPilih?.(n); }}
        className="flex cursor-pointer items-center gap-3 px-3 py-2.5 hover:bg-foreground/[0.03]">
        <div className="flex min-w-0 flex-1 items-center gap-2" style={{ paddingLeft: `${n.depth * 1.5}rem` }}>
          {n.hasChildren ? (
            <Button variant="ghost" size="icon-sm" aria-expanded={open}
              aria-label={open ? 'Tutup cabang' : 'Buka cabang'} title={open ? 'Tutup cabang' : 'Buka cabang'}
              onClick={(e) => { e.stopPropagation(); toggle(n.unit_id); }}>
              {open ? <ChevronDown /> : <ChevronRight />}
            </Button>
          ) : <span className="w-8 shrink-0" aria-hidden="true" />}
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <p className="truncate text-sm font-semibold text-foreground">{n.name}</p>
              <TypeBadge type={n.type} />
              {n.code && <span className="hidden text-xs text-muted-foreground sm:inline">{n.code}</span>}
            </div>
            <p className="truncate text-xs text-muted-foreground">
              {n.head_employee_name ? `Kepala: ${n.head_employee_name}` : 'Kepala belum ditentukan'}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2 text-right">
          <span className="text-sm tabular-nums text-foreground" title="Karyawan terisi / target">
            {n.headcount_actual || 0}
            {n.headcount_target > 0 && <span className="text-muted-foreground"> / {n.headcount_target}</span>}
          </span>
          <span className="hidden sm:inline"><StatusBadge status="target" label={st.label} tone={st.tone} /></span>
        </div>
      </div>
    );
  });
}

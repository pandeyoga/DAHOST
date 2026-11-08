import { Edit2, Trash2, Lock, Archive, RotateCcw, Link2, ChevronRight, ChevronDown } from 'lucide-react';
import { Button } from '@/components/ui/button';

// 2026-11-02 (S2-H) — atom layar Bagan Akun: label Indonesia, lencana keterikatan, pohon dengan
// aksi yang SELALU terlihat (dulu hanya muncul saat hover → tidak bisa dipakai di layar sentuh).

export const TYPE_LABELS = {
  ASSET: 'Aset', LIABILITY: 'Liabilitas', EQUITY: 'Ekuitas', REVENUE: 'Pendapatan',
  COGS: 'HPP', EXPENSE: 'Beban', OTHER_INCOME: 'Pendapatan Lain', OTHER_EXPENSE: 'Beban Lain',
};
export const TYPE_ORDER = ['ASSET', 'LIABILITY', 'EQUITY', 'REVENUE', 'COGS', 'EXPENSE', 'OTHER_INCOME', 'OTHER_EXPENSE'];
export const NB_LABELS = { DEBIT: 'Debit', CREDIT: 'Kredit' };

// 2026-11-08 (Standar UI/UX v2): tipe akun = label netral (dulu 8 warna palet langsung — warna bukan hiasan).
const TYPE_COLORS = {};

export function TypeBadge({ type, className = '' }) {
  const cls = TYPE_COLORS[type] || 'text-muted-foreground bg-transparent border-[var(--glass-border)]';
  return (
    <span className={`text-xs font-medium px-1.5 py-0.5 rounded border whitespace-nowrap ${cls} ${className}`}>
      {TYPE_LABELS[type] || type}
    </span>
  );
}

export const LEVEL_META = {
  SISTEM: { label: 'Terhubung', cls: 'text-[hsl(var(--danger-text))] bg-[hsl(var(--destructive)/0.08)] border-[hsl(var(--destructive)/0.35)]' },
  STRUKTUR: { label: 'Struktur', cls: 'text-[hsl(var(--warning-text))] bg-[hsl(var(--warning)/0.08)] border-[hsl(var(--warning)/0.35)]' },
  SEED: { label: 'Bawaan', cls: 'text-muted-foreground bg-muted/40 border-[var(--glass-border)]' },
  BEBAS: { label: 'Bebas', cls: 'text-muted-foreground bg-transparent border-dashed border-[var(--glass-border)]' },
};

/** Lencana "Terhubung · N" — merah = sistem, kuning = struktur/laporan, abu = bawaan, garis putus = bebas. */
export function UsageBadge({ usage, onClick, testId }) {
  if (!usage) return null;
  const meta = LEVEL_META[usage.level] || LEVEL_META.BEBAS;
  const showCount = usage.level === 'SISTEM' || usage.level === 'STRUKTUR';
  const text = showCount ? `${meta.label} · ${usage.count}` : meta.label;
  const tip = (usage.labels || []).join('\n') || (usage.level === 'BEBAS' ? 'Tidak terhubung ke apa pun — aman dihapus' : 'Akun bawaan sistem — bisa dinonaktifkan');
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      onClick={onClick}
      title={tip}
      aria-label={`Keterikatan akun: ${text}. Buka rincian.`}
      className={`h-auto gap-1 text-xs font-medium px-1.5 py-0.5 rounded-full border whitespace-nowrap hover:opacity-80 ${meta.cls}`}
      data-testid={testId}
    >
      {showCount && <Link2 className="w-3 h-3" aria-hidden="true" />}
      {showCount ? (<><span className="hidden sm:inline">{meta.label} · </span>{usage.count}</>) : text}
    </Button>
  );
}

/** Tombol aksi baris — selalu terlihat & cukup besar untuk disentuh (h-8 w-8). */
export function RowActions({ acc, onEdit, onDelete, onReactivate, code }) {
  const u = acc.usage || {};
  const inactive = acc.active === false;
  let DelIcon = Trash2;
  let delLabel = 'Hapus permanen';
  let delCls = 'text-[hsl(var(--danger-text))] hover:bg-[hsl(var(--destructive)/0.08)]';
  if (!u.can_delete) {
    if (u.can_deactivate) { DelIcon = Archive; delLabel = 'Nonaktifkan'; delCls = 'text-[hsl(var(--warning-text))] hover:bg-[hsl(var(--warning)/0.08)]'; }
    else { DelIcon = Lock; delLabel = 'Terkunci — lihat alasan'; delCls = 'text-muted-foreground hover:bg-foreground/5'; }
  }
  // 2026-11-08 (Standar UI/UX v2): tombol ikon = Button (dulu tombol buatan sendiri berwarna palet langsung).
  return (
    <div className="flex items-center gap-0.5 shrink-0">
      <Button type="button" variant="ghost" size="icon-sm" onClick={() => onEdit(acc)} className="text-primary"
        title="Ubah akun" aria-label={`Ubah akun ${code}`} data-testid={`coa-edit-${code}`}>
        <Edit2 className="w-4 h-4" />
      </Button>
      {inactive ? (
        <Button type="button" variant="ghost" size="icon-sm" onClick={() => onReactivate(acc)} className="text-[hsl(var(--success-text))]"
          title="Aktifkan lagi" aria-label={`Aktifkan lagi akun ${code}`} data-testid={`coa-reactivate-${code}`}>
          <RotateCcw className="w-4 h-4" />
        </Button>
      ) : (
        <Button type="button" variant="ghost" size="icon-sm" onClick={() => onDelete(acc)} className={delCls}
          title={delLabel} aria-label={`${delLabel}: akun ${code}`} data-testid={`coa-delete-${code}`}>
          <DelIcon className="w-4 h-4" />
        </Button>
      )}
    </div>
  );
}

/** Bangun pohon dari daftar datar (parent_code). Induk hilang / siklus → akar (semua akun tetap tampil). */
export function buildTree(list) {
  const by = new Map(list.map((a) => [a.code, { ...a, children: [] }]));
  const roots = [];
  for (const a of list) {
    const node = by.get(a.code);
    const p = a.parent_code && a.parent_code !== a.code ? by.get(a.parent_code) : null;
    if (p) p.children.push(node); else roots.push(node);
  }
  const seen = new Set();
  const mark = (n) => {
    const st = [n];
    while (st.length) { const x = st.pop(); if (seen.has(x.code)) continue; seen.add(x.code); st.push(...x.children); }
  };
  roots.forEach(mark);
  for (const a of list) {
    if (seen.has(a.code)) continue;
    const node = by.get(a.code);
    const p = by.get(a.parent_code);
    if (p) p.children = p.children.filter((c) => c !== node);
    roots.push(node);
    mark(node);
  }
  return roots;
}

/** Flatten a tree into [{ node, depth, hasChildren }] based on an `open` set (codes). */
export function flattenTree(nodes, openSet, depth, visible) {
  const out = [];
  const d = depth || 0;
  for (const n of nodes) {
    if (visible && !visible.has(n.code)) continue;
    const kids = visible ? (n.children || []).filter((c) => visible.has(c.code)) : (n.children || []);
    const hasChildren = kids.length > 0;
    out.push({ node: n, depth: d, hasChildren });
    if (hasChildren && openSet.has(n.code)) {
      for (const r of flattenTree(kids, openSet, d + 1, visible)) out.push(r);
    }
  }
  return out;
}

function Highlight({ text, q }) {
  if (!q) return text;
  const i = (text || '').toLowerCase().indexOf(q.toLowerCase());
  if (i < 0) return text;
  return (<>{text.slice(0, i)}<mark className="bg-yellow-300/60 dark:bg-yellow-500/40 text-foreground rounded-sm">{text.slice(i, i + q.length)}</mark>{text.slice(i + q.length)}</>);
}

function TreeRow({ row, onToggle, isOpen, matched, q, onEdit, onDelete, onReactivate, onUsage }) {
  const { node, depth, hasChildren } = row;
  const inactive = node.active === false;
  const indent = Math.min(depth, 5) * 12;
  // Layar sempit (375px): dua baris — [buka/tutup · kode · lencana · aksi] lalu nama di bawahnya.
  // Mulai `sm`: satu baris. Tidak ada gulir horizontal (kode/nama dipotong rapi, nama lengkap di title).
  return (
    <div
      className={`flex flex-wrap sm:flex-nowrap items-center gap-x-1.5 sm:gap-x-2 gap-y-0.5 py-1 pr-1 rounded hover:bg-foreground/5 min-w-0 border-b border-[var(--glass-border)] sm:border-0 ${inactive ? 'opacity-60' : ''} ${matched === false ? 'opacity-70' : ''}`}
      style={{ paddingLeft: `${indent + 2}px` }}
      data-testid={`coa-row-${node.code}`}
    >
      {hasChildren ? (
        <Button type="button" variant="ghost" size="icon-sm" onClick={() => onToggle(node.code)}
          className="shrink-0 text-muted-foreground hover:text-foreground"
          aria-expanded={isOpen} aria-label={`${isOpen ? 'Tutup' : 'Buka'} anak akun ${node.code}`}
          title={`${isOpen ? 'Tutup' : 'Buka'} anak akun`}
          data-testid={`coa-toggle-${node.code}`}>
          {isOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        </Button>
      ) : (<span className="w-8 shrink-0" aria-hidden="true" />)}
      <span className="text-xs text-muted-foreground tabular-nums flex-1 basis-16 min-w-0 sm:flex-none sm:basis-auto sm:shrink-0 sm:min-w-[5.5rem] sm:max-w-[9rem] truncate" title={node.code}>
        <Highlight text={node.code} q={q} />
      </span>
      <span className={`order-last basis-full pl-9 sm:order-none sm:basis-auto sm:pl-0 min-w-0 sm:flex-1 truncate text-sm ${node.is_group ? 'font-semibold text-foreground' : 'text-foreground/85'}`} title={node.name}>
        <Highlight text={node.name} q={q} />
      </span>
      <span className="hidden sm:inline-flex items-center gap-1 shrink-0">
        <TypeBadge type={node.type} />
        {node.is_group && <span className="text-xs text-muted-foreground">grup</span>}
      </span>
      {inactive && <span className="text-xs px-1.5 py-0.5 rounded border border-[var(--glass-border)] text-muted-foreground shrink-0">nonaktif</span>}
      <span className="shrink-0"><UsageBadge usage={node.usage} onClick={() => onUsage(node)} testId={`coa-usage-${node.code}`} /></span>
      <RowActions acc={node} code={node.code} onEdit={onEdit} onDelete={onDelete} onReactivate={onReactivate} />
    </div>
  );
}

/** Pohon akun. `open`/`setOpen` dikendalikan induk (buka/tutup semua, pencarian membuka leluhur). */
export function CoaTreeView({ tree, open, setOpen, visible, matched, q, onEdit, onDelete, onReactivate, onUsage }) {
  const toggle = (code) => setOpen((prev) => {
    const next = new Set(prev);
    if (next.has(code)) next.delete(code); else next.add(code);
    return next;
  });
  const rows = flattenTree(tree, open, 0, visible);
  if (!rows.length) return <div className="py-8 text-center text-sm text-muted-foreground">Tidak ada akun yang cocok.</div>;
  return (
    <div className="overflow-x-hidden" data-testid="coa-tree">
      {rows.map((row) => (
        <TreeRow key={row.node.code} row={row} onToggle={toggle} isOpen={open.has(row.node.code)}
          matched={matched ? matched.has(row.node.code) : undefined} q={q}
          onEdit={onEdit} onDelete={onDelete} onReactivate={onReactivate} onUsage={onUsage} />
      ))}
    </div>
  );
}

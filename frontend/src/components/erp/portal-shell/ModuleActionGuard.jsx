// Sembunyikan tombol Tambah/Ubah/Hapus/Approve/Export di layar modul bila izin granular
// peran tidak memuat aksinya (tampilan saja — penjaga sungguhan tetap di backend).
import { useEffect, useRef } from 'react';
import { moduleActions } from '../portalAccess';

const RULES = [
  ['delete', /\b(hapus|delete|remove|buang)\b/, /(trash|delete|remove|hapus)/, /lucide-trash/],
  ['approve', /\b(approve|setujui|tolak|reject)\b/, /(approve|reject|setujui|tolak)/, null],
  ['export', /\b(export|ekspor|unduh|download|cetak|print)\b/, /(export|download|unduh|print|cetak)/, /lucide-(download|printer|file-down|file-spreadsheet)/],
  ['create', /^\+?\s*(tambah|buat|baru|new|add|create)\b/, /(^|-)(add|create|new|tambah)(-|$)/, /lucide-(plus|circle-plus|square-plus)\b/],
  ['edit', /^(ubah|edit|perbarui|update|sinkron|sync|impor|import)\b/, /(^|-)(edit|ubah|update)(-|$)/, /lucide-(pencil|pen|square-pen|edit)/],
];

export function classifyAction(el) {
  const text = (el.textContent || '').trim().toLowerCase();
  const label = `${el.getAttribute('aria-label') || ''} ${el.getAttribute('title') || ''}`.toLowerCase();
  const tid = (el.getAttribute('data-testid') || '').toLowerCase();
  const icon = el.querySelector('svg')?.getAttribute('class') || '';
  for (const [act, txtRe, tidRe, iconRe] of RULES) {
    if ((text.length < 40 && txtRe.test(text)) || txtRe.test(label.trim())) return act;
    if (tid && tidRe.test(tid)) return act;
    if (!text && iconRe && iconRe.test(icon)) return act;
  }
  return null;
}

export default function ModuleActionGuard({ moduleId, children }) {
  const ref = useRef(null);
  const acts = moduleActions(moduleId);
  const key = acts ? acts.join(',') : '';

  useEffect(() => {
    const root = ref.current;
    if (!root || !acts) return undefined;
    const allowed = new Set(acts);
    // Dialog/sheet/menu Radix dirender di <body> (portal) -> ikut dipindai.
    const scan = () => {
      const roots = [root, ...document.querySelectorAll('[role="dialog"], [role="menu"], [data-radix-popper-content-wrapper]')];
      roots.flatMap((r) => Array.from(r.querySelectorAll('button:not([role="tab"]), a[role="button"], [role="menuitem"]'))).forEach((el) => {
        const act = classifyAction(el);
        const deny = act && !allowed.has(act);
        if (deny && el.dataset.rbacHidden !== '1') {
          el.dataset.rbacHidden = '1';
          el.style.display = 'none';
        } else if (!deny && el.dataset.rbacHidden === '1') {
          delete el.dataset.rbacHidden;
          el.style.display = '';
        }
      });
    };
    scan();
    let raf = 0;
    const obs = new MutationObserver(() => {
      if (!raf) raf = requestAnimationFrame(() => { raf = 0; scan(); });
    });
    obs.observe(document.body, { childList: true, subtree: true });
    return () => { obs.disconnect(); cancelAnimationFrame(raf); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [moduleId, key]);

  return <div ref={ref} data-testid="module-action-guard">{children}</div>;
}

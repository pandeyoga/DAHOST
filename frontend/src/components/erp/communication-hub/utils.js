/**
 * Communication Hub — shared utilities (no React imports).
 * Used by every sub-component in this folder.
 */

export const API = process.env.REACT_APP_BACKEND_URL || '';

/** Authenticated fetch returning parsed JSON. Errors caught by callers via .catch(). */
export function apicall(method, path, token, body) {
  const opts = {
    method,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
  };
  if (body !== undefined) opts.body = JSON.stringify(body);
  return fetch(`${API}${path}`, opts).then((r) => r.json());
}

/** Friendly relative timestamp (today → HH:MM, yesterday → "Kemarin", older → short date). */
export function formatTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const now = new Date();
  const diffDays = Math.floor((now - d) / 86400000);
  if (diffDays === 0) return d.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' });
  if (diffDays === 1) return 'Kemarin';
  return d.toLocaleDateString('id-ID', { day: '2-digit', month: 'short' });
}

/** Two-letter initials from a name (e.g. "Super Admin" → "SA"). */
export function initials(name) {
  if (!name) return '?';
  return name.split(' ').map((w) => w[0]).join('').toUpperCase().slice(0, 2);
}

/** Warna latar avatar tetap per pengguna — Standar UI/UX v2: dari token warna (dulu violet/blue/emerald/… 500). */
export function avatarColor(id) {
  const colors = [
    'bg-primary/20', 'bg-[hsl(var(--info)/0.2)]', 'bg-[hsl(var(--success)/0.2)]', 'bg-[hsl(var(--warning)/0.2)]',
    'bg-[hsl(var(--destructive)/0.15)]', 'bg-primary/10', 'bg-[hsl(var(--info)/0.12)]', 'bg-[hsl(var(--success)/0.12)]',
  ];
  let h = 0;
  const s = id || '';
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) & 0xffff;
  return colors[h % colors.length];
}

export const EMOJI_LIST = ['👍', '❤️', '😂', '😮', '😢', '🔥', '✅', '👏', '🙏', '💯'];

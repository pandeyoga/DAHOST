/**
 * NotificationBell — SATU kotak masuk di TopBar (revisi owner 2026-07-27, 2026-11-02).
 *
 * 2026-11-02 (K30) — bel + ikon "Approval Inbox" terpisah DILEBUR jadi satu panel
 * dengan dua tab:
 *   · Perlu Tindakan — lencana merah = notifikasi action TERBUKA + pekerjaan yang
 *     dihitung langsung dari dokumen (Approval Badge lama), tanpa hitung dobel
 *     (backend: /api/notifications/categories → `action_open`). Item punya tombol
 *     aksi yang membuka layar terkait (+ record_id/tab bila ada). Action yang sudah
 *     selesai tertutup otomatis dan pindah ke "Riwayat".
 *   · Pemberitahuan — kabar biasa; titik biru di bel bila ada yang belum dibaca.
 * Kategori portal tetap ada sebagai filter sekunder di Pemberitahuan.
 *
 * 2026-11-02 — perbaikan sebelumnya tetap: klik item = tandai dibaca → tutup panel →
 * buka layar terkait (event `erp:navigate-module` → App.handleNavigate: pindah portal +
 * tab hub + deepLinkParams); Escape/klik di luar menutup panel; waktu UTC → WIB;
 * panel selebar layar di ponsel.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Bell, X, CheckCheck, ArrowRight, Loader2, BellOff, Settings2, ChevronDown,
  ClipboardList, History, CheckCircle2,
} from 'lucide-react';
import Modal from './Modal';
import NotificationPrefsDialog from './NotificationPrefsDialog';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const PAGE_SIZE = 30;
const DROPDOWN_COUNT = 6;

export const INBOX_TABS = [
  { key: 'action', label: 'Perlu Tindakan' },
  { key: 'info', label: 'Pemberitahuan' },
  { key: 'history', label: 'Riwayat' },
];

const CAT_TONE = {
  // "Untuk Saya" = notifikasi yang dialamatkan langsung ke pengguna ini
  personal: 'bg-indigo-50 text-indigo-700 border-indigo-200',
  warehouse: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  production: 'bg-sky-50 text-sky-700 border-sky-200',
  cutting: 'bg-orange-50 text-orange-700 border-orange-200',
  maklon: 'bg-violet-50 text-violet-700 border-violet-200',
  finance: 'bg-teal-50 text-teal-700 border-teal-200',
  hr: 'bg-amber-50 text-amber-700 border-amber-200',
  toko: 'bg-pink-50 text-pink-700 border-pink-200',
  accessories: 'bg-cyan-50 text-cyan-700 border-cyan-200',
  assets: 'bg-yellow-50 text-yellow-700 border-yellow-200',
  rnd: 'bg-purple-50 text-purple-700 border-purple-200',
  sysadmin: 'bg-slate-100 text-slate-700 border-slate-300',
};

// ── Waktu (dipakai juga oleh PortalSayaNotifikasi) ──────────────────────────
// Server menyimpan UTC. Stempel lama/berkas lain bisa datang TANPA zona
// ("2026-11-01T21:33:43.861000") — `new Date()` membacanya sebagai jam LOKAL,
// jadi di WIB semuanya bergeser 7 jam. Tanpa zona = UTC.
export function parseServerTime(iso) {
  if (!iso) return null;
  let s = String(iso).trim();
  s = s.replace(/(\.\d{3})\d+/, '$1');            // mikrodetik Python → milidetik
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(s)) s += 'Z';
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function timeAgo(iso) {
  const t = parseServerTime(iso);
  if (!t) return '';
  const d = (Date.now() - t.getTime()) / 1000;
  if (d < 60) return 'baru saja';                   // termasuk selisih jam kecil (nilai negatif)
  if (d < 3600) return `${Math.floor(d / 60)} menit lalu`;
  if (d < 86400) return `${Math.floor(d / 3600)} jam lalu`;
  return `${Math.floor(d / 86400)} hari lalu`;
}

export function formatWIB(iso) {
  const t = parseServerTime(iso);
  if (!t) return '';
  return `${t.toLocaleString('id-ID', {
    timeZone: 'Asia/Jakarta', day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })} WIB`;
}

// Parameter navigasi dari sebuah notifikasi: id rekaman + link_params + tab hub.
export function notifNavParams(n) {
  const params = { ...(n?.link_params || {}) };
  const rid = n?.action?.record_id || n?.link_id || n?.source_id;
  if (rid) {
    params.record_id = params.record_id || rid;
    params.link_id = rid;
  }
  if (!params.tab && n?.meta?.hub_tab) params.tab = n.meta.hub_tab;
  if (n?.id) params.from_notification = n.id;
  return params;
}

// Navigasi bersama bel & Portal Saya. Mengembalikan false bila tujuan tidak dikenal.
// Item action: backend sudah mengisi `link_module` = action.target_menu (disesuaikan
// portal penerima, K37) dan `link_params` = action.filter.
export function navigateToNotification(n, fallback) {
  const moduleId = n?.action?.target_menu || n?.link_module;
  if (!moduleId) return false;
  const detail = { moduleId, params: notifNavParams(n), handled: undefined };
  try { window.dispatchEvent(new CustomEvent('erp:navigate-module', { detail })); } catch (e) { /* noop */ }
  if (detail.handled === undefined && typeof fallback === 'function') {
    fallback(moduleId, detail.params);          // tidak ada pendengar (mis. uji terisolasi)
    return true;
  }
  return detail.handled === true;
}

// Grup "Perlu Tindakan" dari dokumen (PR, AP, SDM, kasbon, retur, ...) → layar antreannya.
export function navigateToGroup(g, fallback) {
  return navigateToNotification({
    link_module: g?.module_id,
    link_params: g?.tab ? { tab: g.tab } : {},
  }, fallback);
}

function CatChip({ cat, label, count, active, onClick }) {
  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[11px] font-medium
        ${active ? 'ring-2 ring-[hsl(var(--primary)/0.35)]' : ''} ${CAT_TONE[cat] || CAT_TONE.sysadmin}`}
      data-testid={`notif-cat-${cat}`}
    >
      {label}
      <span className="tabular-nums font-semibold">{count}</span>
    </button>
  );
}

export function TabButton({ active, label, count, tone = 'neutral', onClick, testId }) {
  const badge = tone === 'action'
    ? 'bg-red-500 text-white'
    : 'bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))]';
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`flex-1 inline-flex items-center justify-center gap-1.5 h-9 px-2 text-xs font-medium border-b-2 transition-colors
        ${active ? 'border-[hsl(var(--primary))] text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground'}`}
      data-testid={testId}
    >
      {label}
      {count > 0 && (
        <span className={`min-w-[18px] h-[18px] px-1 rounded-full text-[10px] font-bold grid place-items-center tabular-nums ${badge}`}>
          {count > 99 ? '99+' : count}
        </span>
      )}
    </button>
  );
}

// Satu baris grup pekerjaan dari dokumen (pengganti dropdown Approval Inbox lama).
export function GroupRow({ g, onOpen }) {
  return (
    <div className="flex items-center gap-3 px-3 py-2.5" data-testid={`inbox-group-${g.key}`}>
      <span className="shrink-0 grid place-items-center w-7 h-7 rounded-md bg-amber-50 text-amber-700 border border-amber-200">
        <ClipboardList className="w-3.5 h-3.5" />
      </span>
      <span className="min-w-0 flex-1 text-xs font-medium text-foreground">{g.label}</span>
      <span className="shrink-0 min-w-[20px] h-5 px-1.5 rounded-full bg-amber-500 text-white text-[10px] font-bold grid place-items-center tabular-nums">
        {g.count}
      </span>
      <button type="button" onClick={() => onOpen(g)}
              className="shrink-0 inline-flex items-center gap-1 h-7 px-2.5 rounded-md bg-[hsl(var(--primary))] text-white text-[11px] font-medium hover:opacity-90"
              data-testid={`inbox-group-open-${g.key}`}>
        Buka <ArrowRight className="w-3 h-3" />
      </button>
    </div>
  );
}

// Satu baris notifikasi (action / info / riwayat). `compact` = dropdown.
export function InboxRow({ n, compact = false, expanded = false, onActivate, onAction, onMarkRead }) {
  const text = n.message || n.body;
  const isAction = n.kind === 'action' && !n.resolved_at;
  const isHistory = n.kind === 'action' && !!n.resolved_at;
  const unreadTone = !n.read && !isHistory ? 'bg-[hsl(var(--primary)/0.04)]' : '';
  return (
    <div className={`flex items-start gap-2 px-3 py-2.5 ${unreadTone} ${expanded ? 'ring-1 ring-inset ring-[hsl(var(--primary)/0.35)]' : ''}`}
         data-testid={isAction ? 'inbox-action-row' : isHistory ? 'inbox-history-row' : 'notif-row'}>
      <button type="button" onClick={() => onActivate?.(n)}
              className="min-w-0 flex-1 text-left focus:outline-none focus-visible:underline"
              aria-expanded={n.link_module ? undefined : expanded}>
        <span className="flex items-center gap-1.5">
          {n.category_label && (
            <span className={`shrink-0 px-1.5 py-0.5 rounded border text-[9px] font-semibold ${CAT_TONE[n.category] || CAT_TONE.sysadmin}`}>
              {n.category_label}
            </span>
          )}
          <span className={`block ${compact ? 'text-xs line-clamp-2' : 'text-sm'} ${n.read && !isAction ? 'text-muted-foreground' : 'text-foreground font-medium'}`}>
            {n.title || text}
          </span>
        </span>
        {text && !compact && (
          <span className={`block text-xs text-muted-foreground mt-0.5 whitespace-pre-line ${expanded ? '' : 'line-clamp-2'}`}>{text}</span>
        )}
        <span className="block text-[10px] text-muted-foreground mt-1" title={formatWIB(n.created_at)}>
          {timeAgo(n.created_at)}{compact ? '' : ` · ${formatWIB(n.created_at)}`}
          {isHistory && (
            <span className="ml-1 inline-flex items-center gap-0.5 text-emerald-700">
              · <CheckCircle2 className="w-3 h-3" /> {n.resolved_label || 'Selesai'}
              {n.resolved_at ? ` (${formatWIB(n.resolved_at)})` : ''}
            </span>
          )}
          {!isAction && !isHistory && n.link_module && <span className="ml-1 text-[hsl(var(--primary))]">· Buka</span>}
        </span>
      </button>
      {isAction && n.action && (
        <button type="button" onClick={() => onAction?.(n)}
                className="shrink-0 self-center inline-flex items-center gap-1 h-7 px-2.5 rounded-md bg-[hsl(var(--primary))] text-white text-[11px] font-medium hover:opacity-90"
                data-testid="inbox-action-btn">
          {n.action.label || 'Buka'} <ArrowRight className="w-3 h-3" />
        </button>
      )}
      {!isAction && !isHistory && !n.read && onMarkRead && !compact && (
        <button type="button" onClick={() => onMarkRead(n.id)}
                className="shrink-0 self-center text-[11px] text-muted-foreground hover:text-foreground"
                data-testid="notif-mark-one">
          Tandai dibaca
        </button>
      )}
      {!isAction && !isHistory && !n.link_module && !compact && (
        <ChevronDown className={`shrink-0 self-center w-3.5 h-3.5 text-muted-foreground transition-transform ${expanded ? 'rotate-180' : ''}`} />
      )}
    </div>
  );
}

const EMPTY_TEXT = {
  action: 'Tidak ada yang perlu ditindaklanjuti.',
  info: 'Belum ada pemberitahuan.',
  history: 'Belum ada tindakan yang selesai.',
};

export function NotificationBell({ token, onNavigateModule }) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState('action');
  const [centerOpen, setCenterOpen] = useState(false);
  const [centerTab, setCenterTab] = useState('action');
  const [prefsOpen, setPrefsOpen] = useState(false);
  const [sum, setSum] = useState({ categories: [], action_open: 0, info_unread: 0, total: 0 });
  const [box, setBox] = useState({ items: [], groups: [], total: 0, hasMore: false });
  const [filter, setFilter] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [expandedId, setExpandedId] = useState(null);
  const [notice, setNotice] = useState('');
  const wrapRef = useRef(null);
  const btnRef = useRef(null);

  const h = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const loadSummary = useCallback(async () => {
    if (!token) return;
    try {
      const r = await fetch(`${BACKEND_URL}/api/notifications/categories?latest=1`, { headers: h });
      if (r.ok) setSum(await r.json());
    } catch { /* diam: bel tidak boleh merusak halaman */ }

  }, [token]);

  const loadBox = useCallback(async (t, { cat = '', append = false, skip = 0, limit = PAGE_SIZE } = {}) => {
    if (!token) return;
    if (append) setLoadingMore(true); else setLoading(true);
    try {
      const qs = new URLSearchParams({ tab: t, limit: String(limit), skip: String(skip) });
      if (cat) qs.set('category', cat);
      const r = await fetch(`${BACKEND_URL}/api/notifications/inbox?${qs}`, { headers: h });
      if (r.ok) {
        const j = await r.json();
        setBox((b) => ({
          items: append ? [...b.items, ...(j.items || [])] : (j.items || []),
          groups: append ? b.groups : (j.groups || []),
          total: j.total ?? 0,
          hasMore: !!j.has_more,
        }));
      } else if (!append) {
        setBox({ items: [], groups: [], total: 0, hasMore: false });
      }
    } catch { /* diam */ } finally {
      if (append) setLoadingMore(false); else setLoading(false);
    }

  }, [token]);

  useEffect(() => {
    loadSummary();
    const t = setInterval(() => {
      if (typeof document !== 'undefined' && document.hidden) return;   // tab tersembunyi: jangan polling
      loadSummary();
    }, 60000);
    return () => clearInterval(t);
  }, [loadSummary]);

  // Escape & klik di luar menutup dropdown; perpindahan halaman menutup semuanya.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') { setOpen(false); btnRef.current?.focus(); }
    };
    const onDown = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onDown);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onDown);
    };
  }, [open]);
  useEffect(() => {
    const closeAll = () => { setOpen(false); setCenterOpen(false); };
    window.addEventListener('hashchange', closeAll);
    return () => window.removeEventListener('hashchange', closeAll);
  }, []);

  const markRead = async (id) => {
    try {
      await fetch(`${BACKEND_URL}/api/notifications/unified/${id}/mark-read`, { method: 'POST', headers: h });
      setBox((b) => ({ ...b, items: b.items.map((x) => (x.id === id ? { ...x, read: true } : x)) }));
      loadSummary();
    } catch { /* ignore */ }
  };

  const markAll = async () => {
    try {
      await fetch(`${BACKEND_URL}/api/notifications/unified/mark-all-read`, { method: 'POST', headers: h });
      setBox((b) => ({ ...b, items: b.items.map((x) => ({ ...x, read: true })) }));
      loadSummary();
    } catch { /* ignore */ }
  };

  const toggleOpen = () => {
    if (open) { setOpen(false); return; }
    // Buka di tab yang berisi: Perlu Tindakan dulu, kecuali kosong.
    const first = (sum.action_open || 0) > 0 || !(sum.info_unread > 0) ? 'action' : 'info';
    setTab(first);
    setFilter('');
    setOpen(true);
    loadBox(first, { limit: DROPDOWN_COUNT });
    loadSummary();
  };

  const switchTab = (t) => { setTab(t); loadBox(t, { limit: DROPDOWN_COUNT }); };

  const openCenter = (t = 'action', focusId = null) => {
    setOpen(false);
    setCenterOpen(true);
    setCenterTab(t);
    setFilter('');
    setExpandedId(focusId);
    setNotice('');
    loadBox(t);
  };

  const switchCenterTab = (t) => {
    setCenterTab(t); setFilter(''); setExpandedId(null); setNotice(''); loadBox(t);
  };

  const go = (n) => {
    setOpen(false);
    setCenterOpen(false);
    const ok = navigateToNotification(n, onNavigateModule);
    if (!ok) {
      // Tujuan tidak dikenal frontend — jangan diam: tampilkan detailnya.
      setNotice('Layar tujuan notifikasi ini tidak tersedia. Detailnya ditampilkan di bawah.');
      setCenterOpen(true);
      setExpandedId(n.id);
      loadBox(centerTab);
    }
  };

  // Satu perilaku klik untuk dropdown & kotak masuk lengkap.
  const activate = (n, from) => {
    if (!n.read) markRead(n.id);
    if (n.link_module || n.action?.target_menu) { go(n); return; }
    if (from === 'dropdown') openCenter(n.kind === 'action' ? (n.resolved_at ? 'history' : 'action') : 'info', n.id);
    else setExpandedId((cur) => (cur === n.id ? null : n.id));
  };

  const openGroup = (g) => {
    setOpen(false);
    setCenterOpen(false);
    navigateToGroup(g, onNavigateModule);
  };

  const actionCount = sum.action_open || 0;
  const infoUnread = sum.info_unread || 0;
  const cats = (sum.categories || []).filter((c) => (c.total - (c.action || 0)) > 0);
  const ariaLabel = `Kotak masuk: ${actionCount} perlu tindakan, ${infoUnread} pemberitahuan belum dibaca`;

  const renderList = (t, { compact }) => {
    if (loading) {
      return <div className="py-10 text-center"><Loader2 className="w-5 h-5 animate-spin mx-auto text-muted-foreground" /></div>;
    }
    const groups = t === 'action' && !filter ? (box.groups || []) : [];
    if (groups.length === 0 && box.items.length === 0) {
      return (
        <div className="px-3 py-8 text-center">
          {t === 'history' ? <History className="w-6 h-6 mx-auto text-muted-foreground/40" />
            : <BellOff className="w-6 h-6 mx-auto text-muted-foreground/40" />}
          <p className="text-xs text-muted-foreground mt-2">{EMPTY_TEXT[t]}</p>
        </div>
      );
    }
    return (
      <div className="divide-y divide-[var(--glass-border)]">
        {groups.map((g) => <GroupRow key={g.key} g={g} onOpen={openGroup} />)}
        {box.items.map((n) => (
          <InboxRow key={n.id} n={n} compact={compact} expanded={expandedId === n.id}
                    onActivate={(x) => activate(x, compact ? 'dropdown' : 'center')}
                    onAction={(x) => { if (!x.read) markRead(x.id); go(x); }}
                    onMarkRead={markRead} />
        ))}
      </div>
    );
  };

  return (
    <>
      <div className="relative" ref={wrapRef}>
        <button
          ref={btnRef}
          onClick={toggleOpen}
          className="relative grid place-items-center h-9 w-9 rounded-full border border-[var(--glass-border)] bg-[var(--card-surface)] text-foreground/60 hover:text-foreground hover:bg-[var(--nav-pill-active)] transition-colors"
          data-testid="notification-bell-btn"
          aria-label={ariaLabel}
          title={ariaLabel}
          aria-haspopup="dialog"
          aria-expanded={open}
        >
          <Bell className="w-4 h-4" />
          {actionCount > 0 ? (
            <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-white text-[10px] font-bold grid place-items-center"
                  data-testid="notification-action-badge">
              {actionCount > 99 ? '99+' : actionCount}
            </span>
          ) : infoUnread > 0 ? (
            <span className="absolute top-0 right-0 w-2.5 h-2.5 rounded-full bg-[hsl(var(--primary))] ring-2 ring-[var(--card-surface)]"
                  data-testid="notification-info-dot" />
          ) : null}
        </button>

        {open && (
          <div
            role="dialog"
            aria-label="Kotak masuk"
            className="fixed left-2 right-2 top-16 sm:absolute sm:left-auto sm:right-0 sm:top-full sm:mt-2 sm:w-[380px] z-50 rounded-xl border border-[var(--glass-border)] bg-[var(--popover-surface)] shadow-[var(--shadow-soft)] overflow-hidden"
            data-testid="notification-dropdown"
          >
            <div className="flex items-center justify-between px-3 pt-2.5 pb-1">
              <div>
                <p className="text-sm font-semibold text-foreground">Kotak Masuk</p>
                <p className="text-[11px] text-muted-foreground tabular-nums">
                  {actionCount} perlu tindakan · {infoUnread} pemberitahuan belum dibaca
                </p>
              </div>
              <div className="flex items-center gap-1">
                <button onClick={() => { setOpen(false); setPrefsOpen(true); }}
                        className="p-1.5 rounded-lg hover:bg-[var(--nav-pill-active)]"
                        title="Atur notifikasi saya" aria-label="Atur notifikasi saya"
                        data-testid="notification-prefs-btn">
                  <Settings2 className="w-3.5 h-3.5 text-foreground/50" />
                </button>
                <button onClick={() => setOpen(false)} className="p-1 rounded-lg hover:bg-[var(--nav-pill-active)]" aria-label="Tutup">
                  <X className="w-3.5 h-3.5 text-foreground/50" />
                </button>
              </div>
            </div>

            <div role="tablist" aria-label="Jenis kotak masuk" className="flex border-b border-[var(--glass-border)] px-1">
              <TabButton active={tab === 'action'} label="Perlu Tindakan" count={actionCount} tone="action"
                         onClick={() => switchTab('action')} testId="inbox-tab-action" />
              <TabButton active={tab === 'info'} label="Pemberitahuan" count={infoUnread}
                         onClick={() => switchTab('info')} testId="inbox-tab-info" />
            </div>

            <div className="max-h-[min(360px,calc(100vh-16rem))] overflow-y-auto">
              {renderList(tab, { compact: true })}
            </div>

            <div className="flex border-t border-[var(--glass-border)]">
              <button onClick={() => openCenter(tab)}
                className="flex-1 py-2.5 text-xs font-medium text-[hsl(var(--primary))] hover:bg-[var(--nav-pill-active)] inline-flex items-center justify-center gap-1"
                data-testid="notification-see-all">
                Lihat semua <ArrowRight className="w-3.5 h-3.5" />
              </button>
              {tab === 'action' && (
                <button onClick={() => openCenter('history')}
                  className="flex-1 py-2.5 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-[var(--nav-pill-active)] inline-flex items-center justify-center gap-1 border-l border-[var(--glass-border)]"
                  data-testid="notification-history">
                  <History className="w-3.5 h-3.5" /> Riwayat tindakan
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      {centerOpen && (
        <Modal title="Kotak Masuk" size="xl" onClose={() => setCenterOpen(false)}>
          <div className="space-y-3" data-testid="notification-detail-modal">
            <div role="tablist" aria-label="Jenis kotak masuk" className="flex border-b border-[var(--glass-border)]">
              {INBOX_TABS.map((t) => (
                <TabButton key={t.key} active={centerTab === t.key} label={t.label}
                           count={t.key === 'action' ? actionCount : t.key === 'info' ? infoUnread : 0}
                           tone={t.key === 'action' ? 'action' : 'neutral'}
                           onClick={() => switchCenterTab(t.key)} testId={`inbox-center-tab-${t.key}`} />
              ))}
            </div>

            {centerTab === 'info' && (
              <div className="flex flex-wrap items-center gap-1.5">
                <button onClick={() => { setFilter(''); setExpandedId(null); loadBox('info'); }}
                  className={`px-2.5 py-1 rounded-full border text-[11px] font-medium ${!filter ? 'bg-[hsl(var(--primary))] text-white border-transparent' : 'bg-[var(--card-surface)] border-[var(--glass-border)] text-foreground/70'}`}
                  data-testid="notif-filter-all">
                  Semua ({sum.info_total || 0})
                </button>
                {cats.map((c) => (
                  <CatChip key={c.key} cat={c.key} label={c.label} count={c.total - (c.action || 0)} active={filter === c.key}
                           onClick={() => { setFilter(c.key); setExpandedId(null); loadBox('info', { cat: c.key }); }} />
                ))}
                <div className="flex-1" />
                <button onClick={() => setPrefsOpen(true)}
                  className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg border border-[var(--glass-border)] bg-[var(--card-surface)] text-xs text-foreground hover:bg-[var(--nav-pill-active)]"
                  data-testid="notif-open-prefs">
                  <Settings2 className="w-3.5 h-3.5" /> Notifikasi saya
                </button>
                <button onClick={markAll}
                  className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg border border-[var(--glass-border)] bg-[var(--card-surface)] text-xs text-foreground hover:bg-[var(--nav-pill-active)]"
                  data-testid="notif-mark-all">
                  <CheckCheck className="w-3.5 h-3.5" /> Tandai semua dibaca
                </button>
              </div>
            )}
            {centerTab === 'action' && (
              <p className="text-xs text-muted-foreground">
                Item di sini tertutup sendiri begitu tindakannya selesai (mis. PR disetujui/ditolak,
                stok kembali normal, cuti diputuskan) lalu pindah ke <b>Riwayat</b>.
              </p>
            )}

            {notice && (
              <p className="text-xs rounded-lg border border-amber-200 bg-amber-50 text-amber-800 px-3 py-2" role="status">{notice}</p>
            )}

            <div className="max-h-[60vh] overflow-y-auto rounded-lg border border-[var(--glass-border)] bg-[var(--card-surface)]">
              {renderList(centerTab, { compact: false })}
              {!loading && box.hasMore && (
                <div className="p-2 text-center border-t border-[var(--glass-border)]">
                  <button onClick={() => loadBox(centerTab, { cat: filter, append: true, skip: box.items.length })}
                          disabled={loadingMore}
                          className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg border border-[var(--glass-border)] bg-[var(--card-surface)] text-xs text-foreground hover:bg-[var(--nav-pill-active)] disabled:opacity-60"
                          data-testid="notif-load-more">
                    {loadingMore ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
                    Muat lebih banyak ({box.items.length} dari {box.total})
                  </button>
                </div>
              )}
            </div>
          </div>
        </Modal>
      )}
      {prefsOpen && (
        <NotificationPrefsDialog
          token={token}
          onClose={() => setPrefsOpen(false)}
          onSaved={() => { loadSummary(); if (centerOpen) loadBox(centerTab, { cat: filter }); }}
        />
      )}
    </>
  );
}

export default NotificationBell;

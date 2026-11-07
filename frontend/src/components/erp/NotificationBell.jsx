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
import { Button } from '@/components/ui/button';
import FilterChips from '@/components/ui/filter-chips';
import DetailPopup from '@/components/ui/detail-popup';
import { Notice } from './moduleAtoms';
import NotificationPrefsDialog from './NotificationPrefsDialog';
import { parseServerTime } from '@/lib/waktu';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const PAGE_SIZE = 30;
const DROPDOWN_COUNT = 6;

export const INBOX_TABS = [
  { key: 'action', label: 'Perlu Tindakan' },
  { key: 'info', label: 'Pemberitahuan' },
  { key: 'history', label: 'Riwayat' },
];

// Standar UI/UX v2 (8 Nov 2026): kategori memakai SATU gaya netral (dulu 12 warna palet mentah, kontras rendah).
const CAT_NETRAL = 'bg-[var(--glass-bg)] text-foreground/80 border-[var(--glass-border)]';
const CAT_TONE = new Proxy({}, { get: () => CAT_NETRAL });

// ── Waktu (dipakai juga oleh PortalSayaNotifikasi) ──────────────────────────
// Server menyimpan UTC; stempel TANPA zona = UTC. Definisinya dipindah ke SSOT `@/lib/waktu`
// (Tahap 7, 2026-11-07) supaya layar absen juga memakainya; ekspor lama tetap ada.
export { parseServerTime };

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

// ── Asisten AI (layar2) — Tahap D, 8 Nov 2026 ──────────────────────────────────
// Notifikasi yang membawa TAUTAN berbentuk alamat aplikasi (`source_url`/`link`, mis.
// "/?portal=management&module=asisten-ai&sesi=<id>" dari briefing pagi) dibuka lewat mesin navigasi
// yang SAMA dengan `link_module`: `module` → layar tujuan, parameter lain (mis. `sesi`) → deepLinkParams.
// Tautan hash lama ("#wh-accessory") dan alamat situs lain tidak diubah (tetap dibuka sebagai rincian).
export function tujuanDariTautan(url) {
  const u = String(url || '').trim();
  if (!u || u.startsWith('#')) return null;
  let parsed;
  try { parsed = new URL(u, window.location.origin); } catch (e) { return null; }
  if (parsed.origin !== window.location.origin) return null;
  const moduleId = parsed.searchParams.get('module') || '';
  if (!/^[a-z0-9][a-z0-9-]{0,80}$/.test(moduleId)) return null;
  const params = {};
  parsed.searchParams.forEach((v, k) => { if (k !== 'module' && k !== 'portal') params[k] = v; });
  return { moduleId, params };
}
const tautanNotif = (n) => tujuanDariTautan(n?.source_url || n?.link || n?.url);
/** Notifikasi ini punya layar tujuan (action, link_module, atau tautan alamat aplikasi). */
export const punyaTujuan = (n) => !!(n?.action?.target_menu || n?.link_module || tautanNotif(n));
// ── akhir Asisten AI (layar2) ──

// Navigasi bersama bel & Portal Saya. Mengembalikan false bila tujuan tidak dikenal.
// Item action: backend sudah mengisi `link_module` = action.target_menu (disesuaikan
// portal penerima, K37) dan `link_params` = action.filter.
export function navigateToNotification(n, fallback) {
  const dariTautan = !n?.action?.target_menu && !n?.link_module ? tautanNotif(n) : null;  // Asisten AI (layar2)
  const moduleId = n?.action?.target_menu || n?.link_module || dariTautan?.moduleId;
  if (!moduleId) return false;
  // Asisten AI (layar2): `tujuan_modul` menandai untuk layar mana parameter ini dibuat. App menyimpan deepLinkParams
  // terakhir sampai navigasi berikutnya, jadi layar yang dibuka kemudian lewat menu samping bisa menerima parameter
  // notifikasi layar LAIN; Asisten AI hanya membaca `link_id` sebagai id percakapan bila tujuannya memang asisten-ai.
  const detail = {
    moduleId,
    params: { ...(dariTautan?.params || {}), ...notifNavParams(n), tujuan_modul: moduleId },
    handled: undefined,
  };
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

export function TabButton({ active, label, count, tone = 'neutral', onClick, testId }) {
  const badge = tone === 'action'
    ? 'bg-[hsl(var(--destructive-strong))] text-white'
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
        <span className={`min-w-[18px] h-[18px] px-1 rounded-full text-xs font-semibold grid place-items-center tabular-nums ${badge}`}>
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
      <span className="shrink-0 grid place-items-center w-7 h-7 rounded-md bg-[hsl(var(--warning)/0.12)] text-[hsl(var(--warning-text))] border border-[hsl(var(--warning)/0.35)]">
        <ClipboardList className="w-3.5 h-3.5" />
      </span>
      <span className="min-w-0 flex-1 text-sm font-medium text-foreground">{g.label}</span>
      <span className="shrink-0 min-w-[20px] h-5 px-1.5 rounded-full bg-[hsl(var(--warning)/0.18)] text-[hsl(var(--warning-text))] text-xs font-semibold grid place-items-center tabular-nums">
        {g.count}
      </span>
      <Button type="button" size="sm" onClick={() => onOpen(g)} className="shrink-0" data-testid={`inbox-group-open-${g.key}`}>
        Buka <ArrowRight />
      </Button>
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
              aria-expanded={punyaTujuan(n) ? undefined : expanded}>
        <span className="flex items-center gap-1.5">
          {n.category_label && (
            <span className={`shrink-0 px-1.5 py-0.5 rounded border text-xs font-medium ${CAT_TONE[n.category] || CAT_TONE.sysadmin}`}>
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
        <span className="block text-xs text-muted-foreground mt-1" title={formatWIB(n.created_at)}>
          {timeAgo(n.created_at)}{compact ? '' : ` · ${formatWIB(n.created_at)}`}
          {isHistory && (
            <span className="ml-1 inline-flex items-center gap-0.5 text-[hsl(var(--success-text))]">
              · <CheckCircle2 className="w-3 h-3" /> {n.resolved_label || 'Selesai'}
              {n.resolved_at ? ` (${formatWIB(n.resolved_at)})` : ''}
            </span>
          )}
          {!isAction && !isHistory && punyaTujuan(n) && <span className="ml-1 text-[hsl(var(--primary))]">· Buka</span>}
        </span>
      </button>
      {isAction && n.action && (
        <Button type="button" size="sm" onClick={() => onAction?.(n)} className="shrink-0 self-center"
                data-testid="inbox-action-btn">
          {n.action.label || 'Buka'} <ArrowRight />
        </Button>
      )}
      {!isAction && !isHistory && !n.read && onMarkRead && !compact && (
        <Button type="button" variant="link" size="sm" onClick={() => onMarkRead(n.id)}
                className="shrink-0 self-center h-auto px-1 text-muted-foreground"
                data-testid="notif-mark-one">
          Tandai dibaca
        </Button>
      )}
      {!isAction && !isHistory && !punyaTujuan(n) && !compact && (
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
    if (punyaTujuan(n)) { go(n); return; }
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
      <ul className="divide-y divide-[var(--glass-border)]">
        {groups.map((g) => <li key={g.key}><GroupRow g={g} onOpen={openGroup} /></li>)}
        {box.items.map((n) => (
          <li key={n.id}>
            <InboxRow n={n} compact={compact} expanded={expandedId === n.id}
                      onActivate={(x) => activate(x, compact ? 'dropdown' : 'center')}
                      onAction={(x) => { if (!x.read) markRead(x.id); go(x); }}
                      onMarkRead={markRead} />
          </li>
        ))}
      </ul>
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
            <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full bg-[hsl(var(--destructive-strong))] text-white text-xs font-semibold grid place-items-center"
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
                <p className="text-sm font-semibold text-foreground">Kotak masuk</p>
                <p className="text-xs text-muted-foreground tabular-nums">
                  {actionCount} perlu tindakan · {infoUnread} pemberitahuan belum dibaca
                </p>
              </div>
              <div className="flex items-center gap-1">
                <Button variant="ghost" size="icon-sm" onClick={() => { setOpen(false); setPrefsOpen(true); }}
                        title="Atur notifikasi saya" aria-label="Atur notifikasi saya"
                        data-testid="notification-prefs-btn">
                  <Settings2 />
                </Button>
                <Button variant="ghost" size="icon-sm" onClick={() => setOpen(false)} title="Tutup" aria-label="Tutup">
                  <X />
                </Button>
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
              <Button variant="ghost" onClick={() => openCenter(tab)} className="h-10 flex-1 rounded-none text-[hsl(var(--primary))]"
                data-testid="notification-see-all">
                Lihat semua <ArrowRight />
              </Button>
              {tab === 'action' && (
                <Button variant="ghost" onClick={() => openCenter('history')}
                  className="h-10 flex-1 rounded-none border-l border-[var(--glass-border)] text-muted-foreground"
                  data-testid="notification-history">
                  <History /> Riwayat tindakan
                </Button>
              )}
            </div>
          </div>
        )}
      </div>

      {centerOpen && (
        <DetailPopup open onClose={() => setCenterOpen(false)} judul="Kotak masuk" testId="notification-center"
          keterangan="Perlu tindakan, pemberitahuan, dan riwayat tindakan Anda."
          aksi={centerTab === 'info' && (<>
            <Button variant="outline" size="sm" onClick={() => setPrefsOpen(true)} data-testid="notif-open-prefs">
              <Settings2 /> Notifikasi saya
            </Button>
            <Button variant="outline" size="sm" onClick={markAll} data-testid="notif-mark-all">
              <CheckCheck /> Tandai semua dibaca
            </Button>
          </>)}>
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
              <FilterChips value={filter} hideWhenEmpty={false} testId="notif-filter" ariaLabel="Kategori notifikasi"
                onChange={(k) => { setFilter(k); setExpandedId(null); loadBox('info', k ? { cat: k } : undefined); }}
                options={[
                  { key: '', label: 'Semua', count: sum.info_total || 0 },
                  ...cats.map((c) => ({ key: c.key, label: c.label, count: c.total - (c.action || 0) })),
                ]} />
            )}
            {centerTab === 'action' && (
              <p className="text-sm text-muted-foreground">
                Item di sini tertutup sendiri begitu tindakannya selesai (mis. PR disetujui/ditolak,
                stok kembali normal, cuti diputuskan) lalu pindah ke <b>Riwayat</b>.
              </p>
            )}

            {notice && <Notice tone="warning">{notice}</Notice>}

            <div className="rounded-lg border border-[var(--glass-border)] bg-[var(--card-surface)]">
              {renderList(centerTab, { compact: false })}
              {!loading && box.hasMore && (
                <div className="p-2 text-center border-t border-[var(--glass-border)]">
                  <Button variant="outline" size="sm" onClick={() => loadBox(centerTab, { cat: filter, append: true, skip: box.items.length })}
                          disabled={loadingMore} data-testid="notif-load-more">
                    {loadingMore ? <Loader2 className="animate-spin" /> : null}
                    Muat lebih banyak ({box.items.length} dari {box.total})
                  </Button>
                </div>
              )}
            </div>
          </div>
        </DetailPopup>
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

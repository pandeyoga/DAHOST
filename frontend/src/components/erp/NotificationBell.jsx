/**
 * NotificationBell — versi ringkas + popup detail (revisi owner 2026-07-27).
 *
 * MASALAH LAMA: bel langsung menumpahkan seluruh daftar notifikasi tanpa
 * kategori, sehingga user tidak tahu notifikasi itu datang dari portal mana dan
 * dropdown-nya jadi panjang.
 *
 * SEKARANG:
 *   · Dropdown bel = RINGKAS — hitungan per kategori (portal sumber) + 5 notifikasi terbaru.
 *   · Tombol "Lihat Semua" membuka POPUP penuh: filter kategori, tandai dibaca,
 *     muat lebih banyak, dan lompat ke modul terkait.
 *   · Kategori & hak terima diatur backend (/api/notifications/categories),
 *     mengikuti konfigurasi admin (matriks kategori × role) + pembisuan per user.
 *
 * 2026-11-02 — perbaikan dari uji browser owner & audit notifikasi:
 *   · klik item (dropdown & Pusat Notifikasi) = tandai dibaca → tutup panel →
 *     buka layar terkait; tanpa tautan → buka detailnya. Dulu baris dropdown
 *     tidak bisa diklik sama sekali.
 *   · id rekaman (`link_id`), `link_params`, dan tab hub ikut diteruskan lewat
 *     event `erp:navigate-module` (App.handleNavigate: pindah portal + deepLinkParams).
 *   · Escape / klik di luar / perpindahan halaman menutup panel. Overlay
 *     `fixed inset-0` lama terkurung di header (backdrop-filter membuat header
 *     jadi containing block), jadi klik di luar header tidak menutup panel.
 *   · waktu: stempel server tanpa zona dibaca sebagai UTC (dulu "7 jam lalu"
 *     untuk notifikasi 1 menit), ditambah jam WIB absolut.
 *   · ponsel 375 px: panel `fixed` selebar layar (dulu 340 px berjangkar kanan
 *     → keluar layar di sisi kiri).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { Bell, X, CheckCheck, ArrowRight, Loader2, BellOff, Settings2, ChevronDown } from 'lucide-react';
import Modal from './Modal';
import NotificationPrefsDialog from './NotificationPrefsDialog';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const PAGE_SIZE = 30;
const LATEST_COUNT = 5;

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
  const rid = n?.link_id || n?.source_id;
  if (rid) {
    params.record_id = params.record_id || rid;
    params.link_id = rid;
  }
  if (!params.tab && n?.meta?.hub_tab) params.tab = n.meta.hub_tab;
  params.from_notification = n?.id;
  return params;
}

// Navigasi bersama bel & Portal Saya. Mengembalikan false bila tujuan tidak dikenal.
export function navigateToNotification(n, fallback) {
  const moduleId = n?.link_module;
  if (!moduleId) return false;
  const detail = { moduleId, params: notifNavParams(n), handled: undefined };
  try { window.dispatchEvent(new CustomEvent('erp:navigate-module', { detail })); } catch (e) { /* noop */ }
  if (detail.handled === undefined && typeof fallback === 'function') {
    fallback(moduleId, detail.params);          // tidak ada pendengar (mis. uji terisolasi)
    return true;
  }
  return detail.handled === true;
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

export function NotificationBell({ token, onNavigateModule }) {
  const [open, setOpen] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [prefsOpen, setPrefsOpen] = useState(false);
  const [sum, setSum] = useState({ categories: [], latest: [], total_unread: 0, total: 0 });
  const [items, setItems] = useState([]);
  const [page, setPage] = useState({ total: 0, hasMore: false });
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
      const r = await fetch(`${BACKEND_URL}/api/notifications/categories?latest=${LATEST_COUNT}`, { headers: h });
      if (r.ok) setSum(await r.json());
    } catch { /* diam: bel tidak boleh merusak halaman */ }

  }, [token]);

  const loadItems = useCallback(async (cat, { append = false, skip = 0 } = {}) => {
    if (append) setLoadingMore(true); else setLoading(true);
    try {
      const qs = new URLSearchParams({ limit: String(PAGE_SIZE), skip: String(skip) });
      if (cat) qs.set('category', cat);
      const r = await fetch(`${BACKEND_URL}/api/notifications/categorized?${qs}`, { headers: h });
      if (r.ok) {
        const j = await r.json();
        setItems((xs) => (append ? [...xs, ...(j.items || [])] : (j.items || [])));
        setPage({ total: j.total ?? (j.items || []).length, hasMore: !!j.has_more });
      } else if (!append) {
        setItems([]);
        setPage({ total: 0, hasMore: false });
      }
    } catch { /* diam */ } finally {
      if (append) setLoadingMore(false); else setLoading(false);
    }

  }, [token]);

  useEffect(() => {
    loadSummary();
    const t = setInterval(loadSummary, 60000);
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
    const closeAll = () => { setOpen(false); setDetailOpen(false); };
    window.addEventListener('hashchange', closeAll);
    return () => window.removeEventListener('hashchange', closeAll);
  }, []);

  const markRead = async (id) => {
    try {
      await fetch(`${BACKEND_URL}/api/notifications/unified/${id}/mark-read`, { method: 'POST', headers: h });
      setItems((xs) => xs.map((x) => (x.id === id ? { ...x, read: true } : x)));
      loadSummary();
    } catch { /* ignore */ }
  };

  const markAll = async () => {
    try {
      await fetch(`${BACKEND_URL}/api/notifications/unified/mark-all-read`, { method: 'POST', headers: h });
      setItems((xs) => xs.map((x) => ({ ...x, read: true })));
      loadSummary();
    } catch { /* ignore */ }
  };

  const openDetail = (cat = '', focusId = null) => {
    setOpen(false);
    setDetailOpen(true);
    setFilter(cat);
    setExpandedId(focusId);
    setNotice('');
    loadItems(cat);
  };

  // Satu perilaku klik untuk dropdown & Pusat Notifikasi.
  const activate = (n, from) => {
    if (!n.read) markRead(n.id);
    if (n.link_module) {
      setOpen(false);
      setDetailOpen(false);
      const ok = navigateToNotification(n, onNavigateModule);
      if (!ok) {
        // Tujuan tidak dikenal frontend — jangan diam: tampilkan detailnya.
        setNotice('Layar tujuan notifikasi ini tidak tersedia. Detailnya ditampilkan di bawah.');
        setDetailOpen(true);
        setExpandedId(n.id);
        loadItems(filter);
      }
      return;
    }
    if (from === 'dropdown') openDetail('', n.id);
    else setExpandedId((cur) => (cur === n.id ? null : n.id));
  };

  const unread = sum.total_unread || 0;
  const cats = (sum.categories || []).filter((c) => c.total > 0);

  return (
    <>
      <div className="relative" ref={wrapRef}>
        <button
          ref={btnRef}
          onClick={() => { setOpen((o) => !o); loadSummary(); }}
          className="relative grid place-items-center h-9 w-9 rounded-full border border-[var(--glass-border)] bg-[var(--card-surface)] text-foreground/60 hover:text-foreground hover:bg-[var(--nav-pill-active)] transition-colors"
          data-testid="notification-bell-btn"
          aria-label={unread > 0 ? `Notifikasi, ${unread} belum dibaca` : 'Notifikasi'}
          aria-haspopup="dialog"
          aria-expanded={open}
        >
          <Bell className="w-4 h-4" />
          {unread > 0 && (
            <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-white text-[10px] font-bold grid place-items-center"
                  data-testid="notification-unread-badge" title={`${unread} belum dibaca`}>
              {unread > 99 ? '99+' : unread}
            </span>
          )}
        </button>

        {open && (
          <div
            role="dialog"
            aria-label="Notifikasi"
            className="fixed left-2 right-2 top-16 sm:absolute sm:left-auto sm:right-0 sm:top-full sm:mt-2 sm:w-[360px] z-50 rounded-xl border border-[var(--glass-border)] bg-[var(--popover-surface)] shadow-[var(--shadow-soft)] overflow-hidden"
            data-testid="notification-dropdown"
          >
            <div className="flex items-center justify-between px-3 py-2.5 border-b border-[var(--glass-border)]">
              <div>
                <p className="text-sm font-semibold text-foreground">Notifikasi</p>
                <p className="text-[11px] text-muted-foreground tabular-nums">
                  {unread} belum dibaca dari {sum.total || 0} total
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

            <div className="px-3 py-2.5 border-b border-[var(--glass-border)]">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">
                Per Portal
              </p>
              {cats.length === 0 ? (
                <p className="text-xs text-muted-foreground">Tidak ada notifikasi.</p>
              ) : (
                <div className="flex flex-wrap gap-1.5" data-testid="notif-category-chips">
                  {cats.map((c) => (
                    <CatChip key={c.key} cat={c.key} label={c.label} count={c.unread || c.total}
                             onClick={() => openDetail(c.key)} />
                  ))}
                </div>
              )}
            </div>

            <div className="max-h-[min(300px,calc(100vh-16rem))] overflow-y-auto">
              {(sum.latest || []).length === 0 ? (
                <div className="px-3 py-8 text-center">
                  <BellOff className="w-6 h-6 mx-auto text-muted-foreground/40" />
                  <p className="text-xs text-muted-foreground mt-2">Belum ada notifikasi.</p>
                </div>
              ) : (
                (sum.latest || []).map((n) => (
                  <button
                    key={n.id}
                    type="button"
                    onClick={() => activate(n, 'dropdown')}
                    className={`w-full text-left px-3 py-2 border-b border-[var(--glass-border)] last:border-0 hover:bg-[var(--nav-pill-active)] focus:outline-none focus-visible:bg-[var(--nav-pill-active)] ${n.read ? '' : 'bg-[hsl(var(--primary)/0.04)]'}`}
                    data-testid="notif-latest-item"
                  >
                    <div className="flex items-start gap-2">
                      <span className={`mt-0.5 shrink-0 px-1.5 py-0.5 rounded border text-[9px] font-semibold ${CAT_TONE[n.category] || CAT_TONE.sysadmin}`}>
                        {n.category_label || (sum.categories.find((c) => c.key === n.category) || {}).label || n.category}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className={`text-xs line-clamp-2 ${n.read ? 'text-muted-foreground' : 'text-foreground font-medium'}`}>{n.title || n.message}</p>
                        <p className="text-[10px] text-muted-foreground" title={formatWIB(n.created_at)}>
                          {timeAgo(n.created_at)}
                          {n.link_module ? <span className="ml-1 text-[hsl(var(--primary))]">· Buka</span> : null}
                        </p>
                      </div>
                    </div>
                  </button>
                ))
              )}
            </div>

            <button onClick={() => openDetail('')}
              className="w-full py-2.5 text-xs font-medium text-[hsl(var(--primary))] hover:bg-[var(--nav-pill-active)] border-t border-[var(--glass-border)] inline-flex items-center justify-center gap-1"
              data-testid="notification-see-all">
              Lihat Semua <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
      </div>

      {detailOpen && (
        <Modal title="Pusat Notifikasi" size="xl" onClose={() => setDetailOpen(false)}>
          <div className="space-y-3" data-testid="notification-detail-modal">
            <div className="flex flex-wrap items-center gap-1.5">
              <button onClick={() => { setFilter(''); setExpandedId(null); loadItems(''); }}
                className={`px-2.5 py-1 rounded-full border text-[11px] font-medium ${!filter ? 'bg-[hsl(var(--primary))] text-white border-transparent' : 'bg-[var(--card-surface)] border-[var(--glass-border)] text-foreground/70'}`}
                data-testid="notif-filter-all">
                Semua ({sum.total || 0})
              </button>
              {(sum.categories || []).map((c) => (
                <CatChip key={c.key} cat={c.key} label={c.label} count={c.total} active={filter === c.key}
                         onClick={() => { setFilter(c.key); setExpandedId(null); loadItems(c.key); }} />
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

            {notice && (
              <p className="text-xs rounded-lg border border-amber-200 bg-amber-50 text-amber-800 px-3 py-2" role="status">{notice}</p>
            )}

            <div className="max-h-[60vh] overflow-y-auto rounded-lg border border-[var(--glass-border)] divide-y divide-[var(--glass-border)] bg-[var(--card-surface)]">
              {loading ? (
                <div className="py-12 text-center"><Loader2 className="w-5 h-5 animate-spin mx-auto text-muted-foreground" /></div>
              ) : items.length === 0 ? (
                <div className="py-12 text-center">
                  <BellOff className="w-7 h-7 mx-auto text-muted-foreground/40" />
                  <p className="text-sm text-muted-foreground mt-2">Tidak ada notifikasi pada kategori ini.</p>
                </div>
              ) : (
                <>
                  {items.map((n) => {
                    const expanded = expandedId === n.id;
                    const text = n.message || n.body;
                    return (
                      <div key={n.id}
                           className={`flex items-start gap-3 ${n.read ? '' : 'bg-[hsl(var(--primary)/0.04)]'} ${expanded ? 'ring-1 ring-inset ring-[hsl(var(--primary)/0.35)]' : ''}`}
                           data-testid="notif-row">
                        <button type="button" onClick={() => activate(n, 'detail')}
                                className="min-w-0 flex-1 text-left px-3 py-2.5 flex items-start gap-3 hover:bg-[var(--nav-pill-active)] focus:outline-none focus-visible:bg-[var(--nav-pill-active)]"
                                aria-expanded={n.link_module ? undefined : expanded}>
                          <span className={`mt-0.5 shrink-0 px-1.5 py-0.5 rounded border text-[10px] font-semibold ${CAT_TONE[n.category] || CAT_TONE.sysadmin}`}>
                            {n.category_label || n.category}
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className={`block text-sm ${n.read ? 'text-muted-foreground' : 'text-foreground font-medium'}`}>{n.title || text}</span>
                            {text && (
                              <span className={`block text-xs text-muted-foreground mt-0.5 whitespace-pre-line ${expanded ? '' : 'line-clamp-2'}`}>{text}</span>
                            )}
                            <span className="block text-[10px] text-muted-foreground mt-1">
                              {timeAgo(n.created_at)} · {formatWIB(n.created_at)}
                            </span>
                          </span>
                          {n.link_module ? (
                            <span className="shrink-0 self-center text-[11px] text-[hsl(var(--primary))]">Buka</span>
                          ) : (
                            <ChevronDown className={`shrink-0 self-center w-3.5 h-3.5 text-muted-foreground transition-transform ${expanded ? 'rotate-180' : ''}`} />
                          )}
                        </button>
                        {!n.read && (
                          <button onClick={() => markRead(n.id)}
                                  className="shrink-0 self-center mr-3 text-[11px] text-muted-foreground hover:text-foreground"
                                  data-testid="notif-mark-one">
                            Tandai dibaca
                          </button>
                        )}
                      </div>
                    );
                  })}
                  {page.hasMore && (
                    <div className="p-2 text-center">
                      <button onClick={() => loadItems(filter, { append: true, skip: items.length })}
                              disabled={loadingMore}
                              className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg border border-[var(--glass-border)] bg-[var(--card-surface)] text-xs text-foreground hover:bg-[var(--nav-pill-active)] disabled:opacity-60"
                              data-testid="notif-load-more">
                        {loadingMore ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
                        Muat lebih banyak ({items.length} dari {page.total})
                      </button>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </Modal>
      )}
      {prefsOpen && (
        <NotificationPrefsDialog
          token={token}
          onClose={() => setPrefsOpen(false)}
          onSaved={() => { loadSummary(); if (detailOpen) loadItems(filter); }}
        />
      )}
    </>
  );
}

export default NotificationBell;

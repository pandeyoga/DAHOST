import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Loader2, Bell, BellOff, CheckCheck, AlertCircle, History } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';
import {
  INBOX_TABS, GroupRow, InboxRow, TabButton, navigateToGroup, navigateToNotification,
} from './NotificationBell';

const API = process.env.REACT_APP_BACKEND_URL;
const PAGE_SIZE = 30;

/**
 * Portal Saya › Notifikasi.
 *
 * 2026-11-02 — perbaikan audit notifikasi:
 *   · lencana "Belum Dibaca" membaca `unread`; dulu `total_unread` yang tidak ada;
 *   · waktu tampil relatif + jam WIB (dulu `created_at.slice(0,16)` = jam UTC mentah);
 *   · perilaku klik sama dengan bel: tandai dibaca lalu buka layar terkait;
 *   · gagal memuat tampil sebagai pesan galat, bukan "Tidak ada notifikasi".
 *
 * 2026-11-02 (K30) — layar ini memakai kotak masuk yang SAMA dengan bel
 * (`/api/notifications/inbox`): tab Perlu Tindakan · Pemberitahuan · Riwayat,
 * komponen baris dipakai bersama (NotificationBell.jsx), tanpa daftar kedua.
 */
export default function PortalSayaNotifikasi({ headers, onNavigate }) {
  const { toast } = useToast();
  const [tab, setTab] = useState('action');
  const [box, setBox] = useState({ items: [], groups: [], total: 0, hasMore: false });
  const [counts, setCounts] = useState({ action: 0, info: 0 });
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');
  const [expandedId, setExpandedId] = useState(null);

  const loadCounts = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/api/notifications/categories?latest=1`, { headers });
      setCounts({ action: r.data.action_open || 0, info: r.data.info_unread || 0 });
    } catch (e) { /* hitungan opsional */ }
  }, [headers]);

  const load = useCallback(async (t, { append = false, skip = 0 } = {}) => {
    if (append) setLoadingMore(true); else setLoading(true);
    try {
      const r = await axios.get(`${API}/api/notifications/inbox?tab=${t}&limit=${PAGE_SIZE}&skip=${skip}`, { headers });
      const got = r.data.items || [];
      setBox((b) => ({
        items: append ? [...b.items, ...got] : got,
        groups: append ? b.groups : (r.data.groups || []),
        total: r.data.total || 0,
        hasMore: !!r.data.has_more,
      }));
      setError('');
    } catch (e) {
      setError('Notifikasi gagal dimuat. Coba muat ulang halaman.');
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [headers]);

  useEffect(() => { load(tab); loadCounts(); }, [load, loadCounts, tab]);

  const markRead = async (id) => {
    try {
      await axios.post(`${API}/api/notifications/unified/${id}/mark-read`, {}, { headers });
      setBox((b) => ({ ...b, items: b.items.map((n) => (n.id === id ? { ...n, read: true } : n)) }));
      loadCounts();
    } catch (e) {
      toast({ title: 'Gagal menandai.', variant: 'destructive' });
    }
  };

  const markAll = async () => {
    try {
      await axios.post(`${API}/api/notifications/unified/mark-all-read`, {}, { headers });
      setBox((b) => ({ ...b, items: b.items.map((n) => ({ ...n, read: true })) }));
      loadCounts();
    } catch (e) {
      toast({ title: 'Gagal menandai semua.', variant: 'destructive' });
    }
  };

  const go = (n) => {
    const ok = navigateToNotification(n, (moduleId, params) => onNavigate?.(moduleId, params));
    if (!ok) {
      toast({ title: 'Layar tujuan notifikasi ini tidak tersedia.' });
      setExpandedId(n.id);
    }
  };

  const activate = (n) => {
    if (!n.read) markRead(n.id);
    if (n.link_module || n.action?.target_menu) { go(n); return; }
    setExpandedId((cur) => (cur === n.id ? null : n.id));
  };

  const empty = !error && !loading && box.items.length === 0 && (box.groups || []).length === 0;

  return (
    <div className="p-4 sm:p-6 max-w-2xl mx-auto space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-bold flex items-center gap-2">
          <Bell className="w-5 h-5" /> Notifikasi Saya
        </h2>
        <div className="flex items-center gap-2">
          {counts.info > 0 && (
            <Badge className="bg-red-100 text-red-700 border-red-200" data-testid="portal-notif-unread">{counts.info} Belum Dibaca</Badge>
          )}
          {tab === 'info' && counts.info > 0 && (
            <Button variant="outline" size="sm" onClick={markAll} data-testid="portal-notif-mark-all">
              <CheckCheck className="w-4 h-4 mr-1" /> Tandai semua dibaca
            </Button>
          )}
        </div>
      </div>

      <div role="tablist" aria-label="Jenis notifikasi" className="flex border-b">
        {INBOX_TABS.map((t) => (
          <TabButton key={t.key} active={tab === t.key} label={t.label}
                     count={t.key === 'action' ? counts.action : t.key === 'info' ? counts.info : 0}
                     tone={t.key === 'action' ? 'action' : 'neutral'}
                     onClick={() => { setExpandedId(null); setTab(t.key); }}
                     testId={`portal-notif-tab-${t.key}`} />
        ))}
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 text-red-700 text-sm px-3 py-2" role="alert">
          <AlertCircle className="w-4 h-4 shrink-0" /> {error}
        </div>
      )}

      {loading && (
        <div className="flex items-center justify-center py-16"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>
      )}

      {empty && (
        <div className="text-center py-16 text-muted-foreground">
          {tab === 'history' ? <History className="w-12 h-12 mx-auto mb-3 opacity-30" />
            : <BellOff className="w-12 h-12 mx-auto mb-3 opacity-30" />}
          <p>{tab === 'action' ? 'Tidak ada yang perlu ditindaklanjuti.'
            : tab === 'history' ? 'Belum ada tindakan yang selesai.' : 'Tidak ada notifikasi saat ini.'}</p>
        </div>
      )}

      {!loading && !empty && (
        <Card className="overflow-hidden divide-y">
          {tab === 'action' && (box.groups || []).map((g) => (
            <GroupRow key={g.key} g={g} onOpen={(x) => navigateToGroup(x, (moduleId, params) => onNavigate?.(moduleId, params))} />
          ))}
          {box.items.map((n) => (
            <InboxRow key={n.id} n={n} expanded={expandedId === n.id}
                      onActivate={activate}
                      onAction={(x) => { if (!x.read) markRead(x.id); go(x); }}
                      onMarkRead={markRead} />
          ))}
        </Card>
      )}

      {box.hasMore && !loading && (
        <div className="text-center">
          <Button variant="outline" size="sm" disabled={loadingMore}
                  onClick={() => load(tab, { append: true, skip: box.items.length })} data-testid="portal-notif-more">
            {loadingMore && <Loader2 className="w-4 h-4 mr-1 animate-spin" />} Muat lebih banyak
          </Button>
        </div>
      )}
    </div>
  );
}

import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Loader2, Bell, BellOff, Check, CheckCheck, ArrowRight, AlertCircle } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';
import { formatWIB, timeAgo, navigateToNotification } from './NotificationBell';

const API = process.env.REACT_APP_BACKEND_URL;
const PAGE_SIZE = 30;

/**
 * Portal Saya › Notifikasi.
 *
 * 2026-11-02 — perbaikan audit notifikasi:
 *   · lencana "Belum Dibaca" membaca `unread` (API /unified/stats); dulu membaca
 *     `total_unread` yang tidak ada ⇒ lencana tidak pernah tampil;
 *   · waktu tampil relatif + jam WIB (dulu `created_at.slice(0,16)` = jam UTC mentah);
 *   · perilaku klik sama dengan bel: tandai dibaca lalu buka layar terkait
 *     (dengan id rekaman), tanpa tautan → buka detail; "Muat lebih banyak";
 *   · gagal memuat tampil sebagai pesan galat, bukan "Tidak ada notifikasi".
 */
export default function PortalSayaNotifikasi({ headers, onNavigate }) {
  const { toast } = useToast();
  const [items, setItems] = useState([]);
  const [unread, setUnread] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');
  const [expandedId, setExpandedId] = useState(null);

  const load = useCallback(async ({ append = false, skip = 0 } = {}) => {
    if (append) setLoadingMore(true);
    try {
      const [listRes, statsRes] = await Promise.all([
        axios.get(`${API}/api/notifications/unified?limit=${PAGE_SIZE}&skip=${skip}`, { headers }),
        axios.get(`${API}/api/notifications/unified/stats`, { headers }),
      ]);
      const got = listRes.data.items || [];
      setItems((xs) => (append ? [...xs, ...got] : got));
      setHasMore(!!listRes.data.has_more);
      setUnread(statsRes.data.unread || 0);
      setError('');
    } catch (e) {
      setError('Notifikasi gagal dimuat. Coba muat ulang halaman.');
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [headers]);

  useEffect(() => { load(); }, [load]);

  const markRead = async (id) => {
    try {
      await axios.post(`${API}/api/notifications/unified/${id}/mark-read`, {}, { headers });
      setItems((xs) => xs.map((n) => (n.id === id ? { ...n, read: true } : n)));
      setUnread((u) => Math.max(0, u - 1));
    } catch (e) {
      toast({ title: 'Gagal menandai.', variant: 'destructive' });
    }
  };

  const markAll = async () => {
    try {
      await axios.post(`${API}/api/notifications/unified/mark-all-read`, {}, { headers });
      setItems((xs) => xs.map((n) => ({ ...n, read: true })));
      setUnread(0);
    } catch (e) {
      toast({ title: 'Gagal menandai semua.', variant: 'destructive' });
    }
  };

  const activate = (n) => {
    if (!n.read) markRead(n.id);
    if (n.link_module) {
      const ok = navigateToNotification(n, (moduleId, params) => onNavigate?.(moduleId, params));
      if (!ok) {
        toast({ title: 'Layar tujuan notifikasi ini tidak tersedia.' });
        setExpandedId(n.id);
      }
      return;
    }
    setExpandedId((cur) => (cur === n.id ? null : n.id));
  };

  if (loading) return (
    <div className="flex items-center justify-center py-24"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>
  );

  return (
    <div className="p-4 sm:p-6 max-w-2xl mx-auto space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-bold flex items-center gap-2">
          <Bell className="w-5 h-5" /> Notifikasi Saya
        </h2>
        <div className="flex items-center gap-2">
          {unread > 0 && (
            <Badge className="bg-red-100 text-red-700 border-red-200" data-testid="portal-notif-unread">{unread} Belum Dibaca</Badge>
          )}
          {unread > 0 && (
            <Button variant="outline" size="sm" onClick={markAll} data-testid="portal-notif-mark-all">
              <CheckCheck className="w-4 h-4 mr-1" /> Tandai semua dibaca
            </Button>
          )}
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 text-red-700 text-sm px-3 py-2" role="alert">
          <AlertCircle className="w-4 h-4 shrink-0" /> {error}
        </div>
      )}

      {!error && items.length === 0 && (
        <div className="text-center py-16 text-muted-foreground">
          <BellOff className="w-12 h-12 mx-auto mb-3 opacity-30" />
          <p>Tidak ada notifikasi saat ini.</p>
        </div>
      )}

      <div className="space-y-2">
        {items.map((n) => {
          const expanded = expandedId === n.id;
          return (
            <Card
              key={n.id}
              data-testid={`notif-${n.id}`}
              className={`transition-all ${!n.read ? 'border-primary/30 bg-primary/5' : 'opacity-80'} ${expanded ? 'ring-1 ring-primary/40' : ''}`}
            >
              <CardContent className="pt-4 pb-3 flex items-start gap-3">
                <div className={`w-2 h-2 rounded-full mt-1.5 flex-shrink-0 ${!n.read ? 'bg-primary' : 'bg-muted'}`} />
                <button type="button" className="flex-1 min-w-0 text-left" onClick={() => activate(n)}
                        aria-expanded={n.link_module ? undefined : expanded}>
                  <p className={`text-sm ${!n.read ? 'font-semibold' : 'font-medium'}`}>{n.title || n.body}</p>
                  {n.body && (
                    <p className={`text-xs text-muted-foreground mt-0.5 whitespace-pre-line ${expanded ? '' : 'line-clamp-2'}`}>{n.body}</p>
                  )}
                  <p className="text-xs text-muted-foreground mt-1">
                    {timeAgo(n.created_at)} · {formatWIB(n.created_at)}
                    {n.link_module && (
                      <span className="ml-2 inline-flex items-center gap-0.5 text-primary">Buka <ArrowRight className="w-3 h-3" /></span>
                    )}
                  </p>
                </button>
                {!n.read && (
                  <Button
                    data-testid={`btn-read-${n.id}`}
                    variant="ghost" size="icon" className="h-7 w-7 text-primary"
                    aria-label="Tandai dibaca" title="Tandai dibaca"
                    onClick={() => markRead(n.id)}
                  >
                    <Check className="w-4 h-4" />
                  </Button>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>

      {hasMore && (
        <div className="text-center">
          <Button variant="outline" size="sm" disabled={loadingMore}
                  onClick={() => load({ append: true, skip: items.length })} data-testid="portal-notif-more">
            {loadingMore && <Loader2 className="w-4 h-4 mr-1 animate-spin" />} Muat lebih banyak
          </Button>
        </div>
      )}
    </div>
  );
}

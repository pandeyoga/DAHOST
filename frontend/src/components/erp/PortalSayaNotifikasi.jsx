import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import FilterChips from '@/components/ui/filter-chips';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { CheckCheck, Loader2, RefreshCw } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice } from './moduleAtoms';
import {
  INBOX_TABS, GroupRow, InboxRow, formatWIB, navigateToGroup, navigateToNotification, punyaTujuan,
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
    if (punyaTujuan(n)) { go(n); return; }  // Asisten AI (layar2): juga tautan alamat aplikasi
    setExpandedId((cur) => (cur === n.id ? null : n.id));
  };

  const empty = !error && !loading && box.items.length === 0 && (box.groups || []).length === 0;

  const LABEL_TAB = { action: 'Perlu tindakan', info: 'Pemberitahuan', history: 'Riwayat' };
  const status = (n) => (n.kind === 'action' ? (n.resolved_at ? 'Selesai' : 'Perlu tindakan') : (n.read ? 'Dibaca' : 'Belum dibaca'));

  return (
    <PageLayout testId="portal-notifikasi" title="Notifikasi"
      subtitle="Hal yang perlu Anda tindak lanjuti, pemberitahuan, dan riwayat tindakan."
      filters={(
        <FilterChips className="w-full min-w-0 sm:w-auto" value={tab} hideWhenEmpty={false} testId="portal-notif-tab" ariaLabel="Jenis notifikasi"
          onChange={(k) => { setExpandedId(null); setTab(k || 'action'); }}
          options={INBOX_TABS.map((t) => ({
            key: t.key, label: LABEL_TAB[t.key] || t.label,
            count: t.key === 'action' ? counts.action : t.key === 'info' ? counts.info : undefined,
          }))} />
      )}
      tools={<>
        {tab === 'info' && counts.info > 0 && (
          <Button variant="outline" onClick={markAll} data-testid="portal-notif-mark-all">
            <CheckCheck /> Tandai semua dibaca
          </Button>
        )}
        <TombolUnduh namaBerkas={`notifikasi-${tab}`} namaLembar="Notifikasi" baris={box.items} testId="portal-notif-unduh" kolom={[
          { label: 'Waktu', nilai: (n) => formatWIB(n.created_at) }, { label: 'Kategori', nilai: (n) => n.category_label || '' },
          { label: 'Judul', nilai: (n) => n.title || '' }, { label: 'Isi', nilai: (n) => n.message || n.body || '' },
          { label: 'Status', nilai: (n) => status(n) },
        ]} />
        <Button variant="outline" size="icon" onClick={() => { load(tab); loadCounts(); }} disabled={loading}
          title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}>
      {counts.info > 0 && (
        <p className="text-sm text-muted-foreground" data-testid="portal-notif-unread">{counts.info} pemberitahuan belum dibaca.</p>
      )}

      {error && <Notice tone="danger">{error}</Notice>}

      {loading && <p className="py-6 text-center text-sm text-muted-foreground">Memuat notifikasi…</p>}

      {empty && (
        <EmptyState title={tab === 'action' ? 'Tidak ada yang perlu ditindaklanjuti.'
          : tab === 'history' ? 'Belum ada tindakan yang selesai.' : 'Tidak ada notifikasi saat ini.'} />
      )}

      {!loading && !empty && (
        <GlassCard className="overflow-hidden p-0">
          <ul className="divide-y divide-[var(--glass-border)]" data-testid="portal-notif-list">
            {tab === 'action' && (box.groups || []).map((g) => (
              <li key={g.key}>
                <GroupRow g={g} onOpen={(x) => navigateToGroup(x, (moduleId, params) => onNavigate?.(moduleId, params))} />
              </li>
            ))}
            {box.items.map((n) => (
              <li key={n.id}>
                <InboxRow n={n} expanded={expandedId === n.id}
                          onActivate={activate}
                          onAction={(x) => { if (!x.read) markRead(x.id); go(x); }}
                          onMarkRead={markRead} />
              </li>
            ))}
          </ul>
        </GlassCard>
      )}

      {box.hasMore && !loading && (
        <div className="text-center">
          <Button variant="outline" size="sm" disabled={loadingMore}
                  onClick={() => load(tab, { append: true, skip: box.items.length })} data-testid="portal-notif-more">
            {loadingMore && <Loader2 className="animate-spin" />} Muat lebih banyak
          </Button>
        </div>
      )}
    </PageLayout>
  );
}

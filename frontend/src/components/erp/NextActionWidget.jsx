import { useState, useEffect, useCallback } from 'react';
import {
  RefreshCw, AlertTriangle, AlertCircle, Info, CheckCircle2, ArrowRight, X, ChevronRight, Lightbulb,
} from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { StatusBadge } from './moduleAtoms';

/* ─── PT Rahaza ERP · NextActionWidget (Phase 16.2) ───────────────────────────
   Menampilkan "apa yang harus dikerjakan selanjutnya" berdasarkan hasil rule engine backend
   (/api/rahaza/next-actions).

   Props:
     - token: JWT
     - portal: 'production' | 'management' | 'warehouse' | 'finance' | 'hr'
     - onNavigate(moduleId, params?): navigate ke modul saat CTA ditekan
     - onOpenSetupWizard: callback untuk action id='setup-empty' (cta_module='__setup_wizard__')
     - autoRefreshMs: default 60000 (1 menit)
     - maxCards: default 5

   Standar UI/UX v2 (8 Nov 2026): satu kartu berisi daftar baris (bukan kartu berwarna per butir), tingkat
   kepentingan memakai StatusBadge, tombol aksi standar, tanpa label HURUF BESAR / huruf 9–11 px.
   Fitur tetap: sembunyikan 4 jam per butir (localStorage), "Kenapa ini penting?", muat ulang, muat otomatis.
───────────────────────────────────────────────────────────────────────────── */

const SEVERITY_META = {
  error: { icon: AlertCircle, tone: 'danger', label: 'Kritis', iconColor: 'text-[hsl(var(--danger-text))]' },
  warning: { icon: AlertTriangle, tone: 'warning', label: 'Perlu perhatian', iconColor: 'text-[hsl(var(--warning-text))]' },
  info: { icon: Info, tone: 'info', label: 'Saran', iconColor: 'text-[hsl(var(--info-text))]' },
  success: { icon: CheckCircle2, tone: 'success', label: 'Beres', iconColor: 'text-[hsl(var(--success-text))]' },
};

const SNOOZE_MS = 4 * 60 * 60 * 1000; // 4 jam

function getSnoozedIds() {
  try {
    const raw = localStorage.getItem('rahaza_nae_snooze') || '{}';
    const obj = JSON.parse(raw);
    const now = Date.now();
    const fresh = {};
    Object.entries(obj).forEach(([id, ts]) => {
      if (now - ts < SNOOZE_MS) fresh[id] = ts;
    });
    localStorage.setItem('rahaza_nae_snooze', JSON.stringify(fresh));
    return new Set(Object.keys(fresh));
  } catch {
    return new Set();
  }
}

function snoozeId(id) {
  try {
    const raw = localStorage.getItem('rahaza_nae_snooze') || '{}';
    const obj = JSON.parse(raw);
    obj[id] = Date.now();
    localStorage.setItem('rahaza_nae_snooze', JSON.stringify(obj));
  } catch {
    /* ignore */
  }
}

export function NextActionWidget({
  token,
  portal = 'production',
  onNavigate,
  onOpenSetupWizard,
  autoRefreshMs = 60_000,
  maxCards = 5,
}) {
  const [actions, setActions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState('');
  // eslint-disable-next-line no-unused-vars
  const [snoozedTick, setSnoozedTick] = useState(0);
  const [expanded, setExpanded] = useState(null); // butir yang sedang dibuka "kenapa"

  const fetchActions = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/rahaza/next-actions?portal=${portal}&limit=12`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setActions(data.actions || []);
        setLastUpdated(new Date().toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' }));
      }
    } catch (e) {
      /* fail silent */
    } finally {
      setLoading(false);
    }
  }, [token, portal]);

  useEffect(() => {
    fetchActions();
  }, [fetchActions]);

  useEffect(() => {
    if (!autoRefreshMs) return undefined;
    const id = setInterval(fetchActions, autoRefreshMs);
    return () => clearInterval(id);
  }, [fetchActions, autoRefreshMs]);

  const snoozedIds = getSnoozedIds();
  const visibleActions = actions
    .filter((a) => !snoozedIds.has(a.id))
    .slice(0, maxCards);

  const handleCTA = (card) => {
    if (card.cta_module === '__setup_wizard__') {
      onOpenSetupWizard?.();
      return;
    }
    if (onNavigate && card.cta_module) {
      onNavigate(card.cta_module, card.cta_params);
    }
  };

  const handleSnooze = (id) => {
    snoozeId(id);
    setSnoozedTick((x) => x + 1);
  };

  const tombolMuat = (testId) => (
    <Button variant="ghost" size="icon-sm" onClick={fetchActions} disabled={loading}
      title="Muat ulang tindakan" aria-label="Muat ulang tindakan" data-testid={testId}>
      <RefreshCw className={loading ? 'animate-spin' : ''} />
    </Button>
  );

  // Tidak ada yang perlu dikerjakan → satu baris ringkas
  if (!loading && visibleActions.length === 0) {
    return (
      <GlassCard className="flex items-center gap-3 px-4 py-3" data-testid="next-action-widget-empty">
        <CheckCircle2 className="h-4 w-4 shrink-0 text-[hsl(var(--success-text))]" aria-hidden="true" />
        <p className="min-w-0 flex-1 text-sm text-foreground">
          <span className="font-medium">Semua terkendali.</span>{' '}
          <span className="text-muted-foreground">Tidak ada tindakan mendesak saat ini.</span>
        </p>
        {tombolMuat('next-action-refresh-empty')}
      </GlassCard>
    );
  }

  return (
    <GlassCard className="p-0" data-testid="next-action-widget">
      <div className="flex items-center justify-between gap-2 border-b border-[var(--glass-border)] px-4 py-2">
        <p className="text-sm font-semibold text-foreground">
          Yang perlu ditindaklanjuti{visibleActions.length > 0 ? ` (${visibleActions.length})` : ''}
        </p>
        <div className="flex items-center gap-1">
          {lastUpdated && <span className="text-xs text-muted-foreground">Diperbarui {lastUpdated}</span>}
          {tombolMuat('next-action-refresh')}
        </div>
      </div>

      {loading && visibleActions.length === 0 && (
        <div className="space-y-2 p-4">
          {[1, 2].map((i) => <div key={i} className="h-10 animate-pulse rounded-md bg-[var(--glass-bg)]" />)}
        </div>
      )}

      <ul className="divide-y divide-[var(--glass-border)]">
        {visibleActions.map((a) => {
          const meta = SEVERITY_META[a.severity] || SEVERITY_META.info;
          const Icon = meta.icon;
          const isExpanded = expanded === a.id;
          return (
            <li key={a.id} className="flex flex-wrap items-start gap-3 px-4 py-3" data-testid={`nae-card-${a.id}`}>
              <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', meta.iconColor)} aria-hidden="true" />
              <div className="min-w-[12rem] flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-foreground">{a.title}</span>
                  <StatusBadge status={a.severity} label={meta.label} tone={meta.tone} />
                </div>
                {a.description && <p className="mt-0.5 text-sm text-muted-foreground">{a.description}</p>}
                {a.why && (
                  <Button variant="link" size="sm" className="h-auto gap-1 px-0 text-xs"
                    onClick={() => setExpanded(isExpanded ? null : a.id)} aria-expanded={isExpanded}
                    data-testid={`nae-why-${a.id}`}>
                    <Lightbulb />
                    {isExpanded ? 'Tutup penjelasan' : 'Kenapa ini penting?'}
                    <ChevronRight className={cn('transition-transform', isExpanded && 'rotate-90')} />
                  </Button>
                )}
                {isExpanded && a.why && (
                  <p className="mt-1 border-l-2 border-[var(--glass-border)] pl-2 text-sm text-muted-foreground">{a.why}</p>
                )}
              </div>
              <div className="ml-7 flex items-center gap-1 sm:ml-auto">
                <Button size="sm" variant="outline" onClick={() => handleCTA(a)} data-testid={`nae-cta-${a.id}`}>
                  {a.cta_label || 'Buka'}<ArrowRight />
                </Button>
                <Button variant="ghost" size="icon-sm" onClick={() => handleSnooze(a.id)}
                  title="Sembunyikan 4 jam" aria-label="Sembunyikan 4 jam" data-testid={`nae-snooze-${a.id}`}>
                  <X />
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
    </GlassCard>
  );
}

export default NextActionWidget;

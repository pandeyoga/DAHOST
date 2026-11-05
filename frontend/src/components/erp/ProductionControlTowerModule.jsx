/**
 * ProductionControlTowerModule — Daily Operations Production Dashboard
 * Phase 28 — P2 Workflow Consolidation #3
 *
 * Single dashboard for Production Manager / Supervisor:
 *  - KPI strip: Active WOs, Today's output, On Track / At Risk / Overdue counts
 *  - Progress bars: overall + maklon
 *  - Critical alerts: Overdue + At-Risk WO lists
 *  - Maklon PO progress cards
 *  - WO status breakdown chart
 *  - Upcoming deadline table
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Factory, RefreshCw, AlertTriangle, CheckCircle2, Clock, Package, Truck,
  Activity, TrendingUp, Calendar, Users, Bell, AlertCircle, ChevronRight,
  Layers, Zap, Target, BarChart3,
} from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { toast } from 'sonner';
import { motion } from 'framer-motion';
import { PageHeader, EmptyState } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;

// ─── Helpers ───────────────────────────────────────────────────────────────
function fmtNum(v) { return Number(v || 0).toLocaleString('id-ID'); }
function fmtDate(v) {
  if (!v) return '—';
  try {
    const d = new Date(v);
    if (isNaN(d.getTime())) return v;
    return d.toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' });
  } catch { return v; }
}

const RISK_META = {
  on_track:  { label: 'On Track',  color: 'text-[hsl(var(--success))]  bg-[hsl(var(--success)/0.15)]  border-[hsl(var(--success)/0.35)] ', icon: CheckCircle2 },
  at_risk:   { label: 'At Risk',   color: 'text-[hsl(var(--warning))]  bg-[hsl(var(--warning)/0.15)]  border-[hsl(var(--warning)/0.35)] ', icon: AlertTriangle },
  overdue:   { label: 'OVERDUE',   color: 'text-[hsl(var(--destructive))]  bg-[hsl(var(--destructive)/0.15)]  border-[hsl(var(--destructive)/0.35)] ',       icon: AlertCircle },
  unknown:   { label: 'No DL',     color: 'text-foreground/70 bg-muted dark:bg-slate-500/15 border-border dark:border-slate-400/30', icon: Clock },
  completed: { label: 'Completed', color: 'text-[hsl(var(--success))]  bg-[hsl(var(--success)/0.15)]  border-[hsl(var(--success)/0.35)] ', icon: CheckCircle2 },
};

function RiskBadge({ risk }) {
  const m = RISK_META[risk] || RISK_META.unknown;
  const Icon = m.icon;
  return (
    <span className={`inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full border ${m.color}`}>
      <Icon className="w-3 h-3" /> {m.label}
    </span>
  );
}

// ─── KPI Cards ─────────────────────────────────────────────────────────────
function KPICell({ label, value, icon: Icon, tone = 'slate', big = false }) {
  const toneMap = {
    slate:   'text-foreground/70 bg-foreground/[0.03]',
    green:   'text-[hsl(var(--success))]  bg-[hsl(var(--success)/0.15)] ',
    amber:   'text-[hsl(var(--warning))]  bg-[hsl(var(--warning)/0.15)] ',
    red:     'text-[hsl(var(--destructive))]  bg-[hsl(var(--destructive)/0.15)] ',
    violet:  'text-[hsl(var(--primary))]  bg-[hsl(var(--primary)/0.15)] ',
    blue:    'text-[hsl(var(--primary))]  bg-[hsl(var(--primary)/0.15)] ',
    emerald: 'text-[hsl(var(--success))]  bg-[hsl(var(--success)/0.15)] ',
  };
  const klass = toneMap[tone] || toneMap.slate;
  return (
    <div className={`p-3 rounded-lg border border-foreground/[0.08] ${klass}`}>
      <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground uppercase tracking-wider mb-1">
        {Icon && <Icon className="w-3 h-3" />} {label}
      </div>
      <div className={`${big ? 'text-2xl' : 'text-xl'} font-bold ${klass.split(' ')[0]}`}>{value}</div>
    </div>
  );
}

// ─── Progress Bar ──────────────────────────────────────────────────────────
function ProgressBar({ pct, gradient = 'from-[hsl(var(--primary)/0.1)] to-[hsl(var(--success)/0.1)]' }) {
  const safePct = Math.max(0, Math.min(100, Number(pct) || 0));
  return (
    <div className="h-2 rounded-full bg-foreground/10 overflow-hidden">
      <motion.div
        className={`h-full rounded-full bg-gradient-to-r ${gradient}`}
        initial={{ width: 0 }}
        animate={{ width: `${safePct}%` }}
        transition={{ duration: 0.6 }}
      />
    </div>
  );
}

// ─── WO Row Card ──────────────────────────────────────────────────────────
function WORowCard({ wo, onClick }) {
  const dl = wo.deadline ? fmtDate(wo.deadline) : '—';
  const dayLabel = wo.days_to_deadline === null
    ? ''
    : wo.days_to_deadline < 0
      ? `${Math.abs(wo.days_to_deadline)} hari terlewat`
      : wo.days_to_deadline === 0
        ? 'Hari ini'
        : `${wo.days_to_deadline} hari lagi`;

  return (
    <motion.button
      data-testid={`pct-wo-row-${wo.id}`}
      initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
      onClick={() => onClick?.(wo)}
      className="w-full text-left p-3 rounded-lg bg-foreground/[0.03] border border-foreground/[0.08] hover:bg-foreground/[0.06] hover:border-[hsl(var(--primary)/0.35)] transition group"
    >
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm tabular-nums font-bold text-foreground truncate max-w-[280px]" title={wo.wo_number}>{wo.wo_number}</span>
            <RiskBadge risk={wo.risk_status} />
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-foreground/10 text-foreground/70">{wo.status}</span>
          </div>
          <div className="flex items-center gap-3 text-xs text-muted-foreground mt-0.5 flex-wrap">
            <span>{wo.artikel || wo.product_name_snapshot || '—'}</span>
            {wo.color && <span>· {wo.color}/{wo.size}</span>}
            {wo.client_name && <span className="flex items-center gap-1"><Users className="w-3 h-3" /> {wo.client_name}</span>}
            <span className="flex items-center gap-1"><Calendar className="w-3 h-3" /> {dl} {dayLabel && <span className={wo.days_to_deadline < 0 ? 'text-[hsl(var(--destructive))]  ml-1' : wo.days_to_deadline <= 5 ? 'text-[hsl(var(--warning))]  ml-1' : ''}>({dayLabel})</span>}</span>
          </div>
        </div>
        <div className="text-right min-w-[140px]">
          <div className="text-xs text-muted-foreground">{fmtNum(wo.qty_produced || 0)} / {fmtNum(wo.qty || 0)} pcs</div>
          <div className="flex items-center gap-2 mt-0.5">
            <div className="flex-1">
              <ProgressBar pct={wo.progress_pct} />
            </div>
            <span className="text-xs font-semibold text-foreground w-10 text-right">{wo.progress_pct}%</span>
          </div>
        </div>
        <ChevronRight className="w-4 h-4 text-muted-foreground/50 group-hover:text-[hsl(var(--primary))] transition" />
      </div>
    </motion.button>
  );
}

// ─── Maklon PO Progress Card ──────────────────────────────────────────────
function MaklonPOCard({ po, onClick }) {
  const dl = po.deadline ? fmtDate(po.deadline) : '—';
  return (
    <motion.button
      data-testid={`pct-makpo-${po.id}`}
      initial={{ opacity: 0 }} animate={{ opacity: 1 }}
      onClick={() => onClick?.(po)}
      className="w-full text-left p-3 rounded-lg bg-foreground/[0.03] border border-foreground/[0.08] hover:border-[hsl(var(--primary)/0.35)] transition group"
    >
      <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-sm tabular-nums font-bold text-foreground">{po.po_number}</span>
            <RiskBadge risk={po.risk_status} />
          </div>
          <div className="text-xs text-muted-foreground mt-0.5 flex items-center gap-2 flex-wrap">
            <Users className="w-3 h-3" /> {po.client_name}
            <span>·</span>
            <Calendar className="w-3 h-3" /> {dl}
            {po.days_to_deadline !== null && po.days_to_deadline !== undefined && (
              <span className={po.days_to_deadline < 0 ? 'text-[hsl(var(--destructive))] ' : po.days_to_deadline <= 5 ? 'text-[hsl(var(--warning))] ' : 'text-muted-foreground/60'}>
                ({po.days_to_deadline < 0 ? `${Math.abs(po.days_to_deadline)} hari terlewat` : `${po.days_to_deadline} hari lagi`})
              </span>
            )}
          </div>
        </div>
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-foreground/10 text-foreground/70 capitalize">{po.status}</span>
      </div>
      <div className="flex items-center gap-3">
        <div className="flex-1">
          <ProgressBar pct={po.progress_pct} />
        </div>
        <div className="text-right">
          <div className="text-xs font-bold text-foreground">{po.progress_pct}%</div>
          <div className="text-[10px] text-muted-foreground">{fmtNum(po.qty_produced)} / {fmtNum(po.total_qty)}</div>
        </div>
      </div>
    </motion.button>
  );
}

// ─── Main Component ────────────────────────────────────────────────────────
export default function ProductionControlTowerModule({ token, onNavigate }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [woTab, setWoTab] = useState('overdue');
  const [autoRefresh, setAutoRefresh] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/prod/control-tower?days_window=7`, { headers });
      if (!r.ok) {
        const e = await r.json().catch(() => ({}));
        toast.error(e.detail || 'Gagal memuat data');
        return;
      }
      setData(await r.json());
    } catch (e) {
      toast.error('Network error: ' + e.message);
    } finally {
      setLoading(false);
    }
  }, [headers]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Auto-refresh every 30s when enabled
  useEffect(() => {
    if (!autoRefresh) return undefined;
    const id = setInterval(() => fetchData(), 30000);
    return () => clearInterval(id);
  }, [autoRefresh, fetchData]);

  const handleWOClick = (wo) => {
    if (wo.maklon_po_id && onNavigate) {
      onNavigate('maklon-po-360', { po_id: wo.maklon_po_id });
    } else if (onNavigate) {
      // WO di Pusat Kendali = job produksi internal → buka daftar Production Jobs
      onNavigate('prod-work-orders', { job_id: wo.id, po_id: wo.po_id, search: wo.wo_number });
    } else {
      toast.info(`WO ${wo.wo_number} — drill-down belum tersedia`);
    }
  };

  const handlePOClick = (po) => {
    if (onNavigate) onNavigate('maklon-po-360', { po_id: po.id });
  };

  if (loading && !data) {
    return (
      <GlassCard className="p-4 py-8 text-center text-muted-foreground">
        <RefreshCw className="w-8 h-8 mx-auto mb-3 animate-spin text-[hsl(var(--primary))] " />
        Memuat Production Control Tower…
      </GlassCard>
    );
  }

  if (!data) {
    return (
      <GlassCard className="p-4">
        <EmptyState icon={AlertCircle} title="Gagal memuat data"
          description="Periksa koneksi lalu coba muat lagi."
          action={<Button onClick={fetchData} variant="outline">Coba lagi</Button>} />
      </GlassCard>
    );
  }

  const k = data.kpis || {};
  const woTabData = woTab === 'overdue' ? (data.overdue_wos || [])
    : woTab === 'at_risk' ? (data.at_risk_wos || [])
    : (data.all_active_wos || []);
  const woEmptyLabel = woTab === 'overdue' ? 'WO yang lewat tenggat' : woTab === 'at_risk' ? 'WO yang berisiko' : 'WO aktif';

  return (
    <div className="space-y-4">
      <PageHeader
        title="Production Control Tower"
        subtitle="Daily operations dashboard untuk Production Manager — semua KPI, alerts, dan progress dalam satu layar."
        icon={Factory}
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant={autoRefresh ? 'default' : 'outline'}
              size="sm"
              onClick={() => setAutoRefresh(v => !v)}
              data-testid="pct-auto-refresh"
              className={autoRefresh ? 'bg-[hsl(var(--success))] hover:bg-[hsl(var(--success)/0.9)] text-foreground' : 'border-foreground/10 text-foreground/70'}
            >
              <Zap className="w-3.5 h-3.5 mr-1.5" /> {autoRefresh ? 'Live' : 'Manual'}
            </Button>
            <Button variant="outline" size="icon" onClick={fetchData} disabled={loading} title="Muat ulang" aria-label="Muat ulang" data-testid="pct-refresh">
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </Button>
          </div>
        }
      />

      {/* KPI Strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
        <KPICell label="Active WOs" value={fmtNum(k.active_wos)} icon={Activity} tone="violet" big />
        <KPICell label="Completed Today" value={fmtNum(k.today_completed_wos)} icon={CheckCircle2} tone="green" big />
        <KPICell label="On Track" value={fmtNum(k.on_track)} icon={CheckCircle2} tone="green" />
        <KPICell label="At Risk" value={fmtNum(k.at_risk)} icon={AlertTriangle} tone="amber" />
        <KPICell label="OVERDUE" value={fmtNum(k.overdue)} icon={AlertCircle} tone="red" big />
        <KPICell label="Tanpa Deadline" value={fmtNum(k.unknown_deadline)} icon={Clock} tone="slate" />
        <KPICell label="CMT Pending QC" value={fmtNum(k.cmt_pending_review)} icon={Truck} tone="blue" />
      </div>

      {/* Deep-link Bar: Open Full View buttons to dedicated modules (FORENSIC_09 #7 spec) */}
      <GlassCard className="p-3" data-testid="pct-deeplink-bar">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <p className="text-[11px] text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
            <Layers className="w-3.5 h-3.5" />
            Buka Tampilan Lengkap
          </p>
          <div className="flex items-center flex-wrap gap-2">
            <Button
              variant="outline" size="sm"
              className="border-[hsl(var(--primary)/0.35)] text-[hsl(var(--primary))] hover:bg-[hsl(var(--primary)/0.15)]"
              onClick={() => onNavigate && onNavigate('prod-line-board')}
              data-testid="pct-link-line-board"
            >
              <Activity className="w-3 h-3 mr-1" /> Live Line Board
            </Button>
            <Button
              variant="outline" size="sm"
              className="border-[hsl(var(--destructive)/0.35)] text-[hsl(var(--destructive))] hover:bg-[hsl(var(--destructive)/0.15)]"
              onClick={() => onNavigate && onNavigate('prod-andon-board')}
              data-testid="pct-link-andon-board"
            >
              <Bell className="w-3 h-3 mr-1" /> Andon Alerts
            </Button>
            <Button
              variant="outline" size="sm"
              className="border-[hsl(var(--primary)/0.35)] text-[hsl(var(--primary))] hover:bg-[hsl(var(--primary)/0.15)]"
              onClick={() => onNavigate && onNavigate('prod-shift-handover')}
              data-testid="pct-link-shift-handover"
            >
              <Users className="w-3 h-3 mr-1" /> Shift Handover
            </Button>
            <Button
              variant="outline" size="sm"
              className="border-[hsl(var(--warning)/0.35)] text-[hsl(var(--warning))] hover:bg-[hsl(var(--warning)/0.15)]"
              onClick={() => onNavigate && onNavigate('prod-backlog')}
              data-testid="pct-link-backlog"
            >
              <TrendingUp className="w-3 h-3 mr-1" /> Backlog &amp; Forecast
            </Button>
          </div>
        </div>
      </GlassCard>

      {/* Output snapshot */}
      <GlassCard className="p-5">
        <div className="flex items-center justify-between mb-3 flex-wrap gap-3">
          <div>
            <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
              <Target className="w-4 h-4 text-[hsl(var(--primary))] " /> Output Snapshot
            </h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              {k.window_completed_wos || 0} WO completed in last {k.window_days || 7} days · {fmtNum(k.bundles_pending_print)} bundles pending print
            </p>
          </div>
          <div className="flex items-center gap-3 flex-wrap">
            <div className="text-right">
              <div className="text-[10px] text-muted-foreground uppercase tracking-wider">Target Total</div>
              <div className="text-lg font-bold text-foreground">{fmtNum(k.total_target_qty)} pcs</div>
            </div>
            <div className="text-right">
              <div className="text-[10px] text-muted-foreground uppercase tracking-wider">Diproduksi</div>
              <div className="text-lg font-bold text-[hsl(var(--success))] ">{fmtNum(k.total_produced_qty)} pcs</div>
            </div>
            <div className="text-right min-w-[80px]">
              <div className="text-[10px] text-muted-foreground uppercase tracking-wider">Progress</div>
              <div className="text-lg font-bold text-[hsl(var(--primary))] ">{k.overall_progress_pct || 0}%</div>
            </div>
          </div>
        </div>
        <ProgressBar pct={k.overall_progress_pct} gradient="from-[hsl(var(--primary)/0.1)] via-[hsl(var(--primary)/0.1)] to-[hsl(var(--success)/0.1)]" />
        <div className="flex justify-between text-[10px] text-muted-foreground/60 mt-1">
          <span>0</span>
          <span>{fmtNum(k.total_target_qty)} pcs</span>
        </div>
      </GlassCard>

      {/* Critical Alerts Section */}
      <GlassCard className="p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
            <Bell className="w-4 h-4 text-[hsl(var(--destructive))] " /> Critical Alerts
            {(k.overdue + k.at_risk) > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-[hsl(var(--destructive)/0.15)] text-[hsl(var(--destructive))]  border border-[hsl(var(--destructive)/0.35)] ">
                {fmtNum(k.overdue + k.at_risk)} aktif
              </span>
            )}
          </h3>
        </div>
        <Tabs value={woTab} onValueChange={setWoTab}>
          <TabsList className="bg-foreground/5 mb-3">
            <TabsTrigger value="overdue" data-testid="pct-tab-overdue" className="data-[state=active]:bg-[hsl(var(--destructive))] data-[state=active]:text-foreground">
              <AlertCircle className="w-3 h-3 mr-1" /> Overdue ({k.overdue || 0})
            </TabsTrigger>
            <TabsTrigger value="at_risk" data-testid="pct-tab-at-risk" className="data-[state=active]:bg-[hsl(var(--warning))] data-[state=active]:text-foreground">
              <AlertTriangle className="w-3 h-3 mr-1" /> At Risk ({k.at_risk || 0})
            </TabsTrigger>
            <TabsTrigger value="all" data-testid="pct-tab-all" className="data-[state=active]:bg-[hsl(var(--primary))] data-[state=active]:text-foreground">
              <Activity className="w-3 h-3 mr-1" /> Semua WO ({k.active_wos || 0})
            </TabsTrigger>
          </TabsList>
        </Tabs>
        {woTabData.length === 0 ? (
          <EmptyState icon={CheckCircle2} className="py-6" title={`Tidak ada ${woEmptyLabel}`}
            description="Pilih tab lain untuk melihat WO dengan status berbeda." />
        ) : (
          <div className="space-y-2 max-h-[400px] overflow-y-auto pr-1">
            {woTabData.map(wo => (
              <WORowCard key={wo.id} wo={wo} onClick={handleWOClick} />
            ))}
          </div>
        )}
      </GlassCard>

      {/* Maklon Progress */}
      <GlassCard className="p-5">
        <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
          <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
            <Package className="w-4 h-4 text-[hsl(var(--primary))] " /> Maklon PO Progress ({k.maklon_active_pos || 0} aktif)
          </h3>
          <div className="flex items-center gap-3 text-xs">
            <span className="text-muted-foreground">Target {fmtNum(k.maklon_target_qty)} pcs</span>
            <span>·</span>
            <span className="text-[hsl(var(--success))] ">{fmtNum(k.maklon_produced_qty)} produced</span>
            <span>·</span>
            <span className="text-[hsl(var(--primary))] font-bold">{k.maklon_progress_pct || 0}%</span>
          </div>
        </div>
        {(data.maklon_progress || []).length === 0 ? (
          <EmptyState icon={Package} className="py-6" title="Belum ada PO Maklon yang aktif"
            description="PO Maklon yang sudah dikonfirmasi akan tampil di sini beserta progresnya." />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {(data.maklon_progress || []).map(po => (
              <MaklonPOCard key={po.id} po={po} onClick={handlePOClick} />
            ))}
          </div>
        )}
      </GlassCard>

      {/* WO Status Breakdown */}
      <GlassCard className="p-5">
        <h3 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
          <BarChart3 className="w-4 h-4 text-[hsl(var(--primary))] " /> WO Status Breakdown
        </h3>
        {Object.keys(data.wo_status_breakdown || {}).length === 0 ? (
          <EmptyState icon={BarChart3} className="py-6" title="Belum ada WO aktif"
            description="Rincian status muncul setelah ada WO yang berjalan." />
        ) : (
          <div className="space-y-2">
            {Object.entries(data.wo_status_breakdown || {})
              .sort((a, b) => b[1] - a[1])
              .map(([status, count]) => {
                const pct = k.active_wos > 0 ? (count / k.active_wos) * 100 : 0;
                return (
                  <div key={status} className="flex items-center gap-3">
                    <span className="text-xs text-foreground/70 w-32 truncate capitalize">{status.replace(/_/g, ' ')}</span>
                    <div className="flex-1 h-6 rounded bg-foreground/5 overflow-hidden relative">
                      <motion.div
                        className="absolute inset-y-0 left-0 bg-gradient-to-r from-[hsl(var(--primary)/0.4)] to-[hsl(var(--primary)/0.2)] border-r border-[hsl(var(--primary)/0.35)] "
                        initial={{ width: 0 }} animate={{ width: `${pct}%` }} transition={{ duration: 0.5 }}
                      />
                      <span className="absolute inset-0 flex items-center px-2 text-xs text-foreground tabular-nums">
                        {count} ({pct.toFixed(0)}%)
                      </span>
                    </div>
                  </div>
                );
              })}
          </div>
        )}
      </GlassCard>

      {/* Upcoming Deadlines */}
      {(data.upcoming_deadlines || []).length > 0 && (
        <GlassCard className="p-5">
          <h3 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
            <Calendar className="w-4 h-4 text-[hsl(var(--warning))] " /> Deadline Dekat (≤14 hari)
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {(data.upcoming_deadlines || []).map(po => (
              <MaklonPOCard key={po.id} po={po} onClick={handlePOClick} />
            ))}
          </div>
        </GlassCard>
      )}

      <div className="text-[10px] text-muted-foreground/60 text-right">
        Last update: {new Date(data.as_of).toLocaleString('id-ID')} {autoRefresh && '· auto-refresh setiap 30s'}
      </div>
    </div>
  );
}

/**
 * AccountDetailPage
 * Halaman detail per platform account di Portal Marketing.
 * Menampilkan: KPI, Revenue Trend, Sales History, KOL Creator, LiveHost yang di-assign.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  ArrowLeft, TrendingUp, ShoppingBag, Users, Radio, RefreshCw,
  Star, Activity, Calendar, BarChart3, Loader2, Target,
  MessageCircle, RotateCcw, AlertTriangle,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { GlassCard, GlassPanel } from '@/components/ui/glass';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PageLayout from '../layout/PageLayout';
import { StatTile } from '../moduleAtoms';
import { RevenueChart } from '../RevenueChart';
import { AccountBadge, getPlatformConfig } from './AccountBadge';
import { useActiveMarketingAccount } from '@/hooks/useActiveMarketingAccount';
import { toast } from 'sonner';
import { formatRupiah } from '@/lib/format';
import { bulanMarketingDari, bulanMarketingWIB, rentangBulanMarketing, labelRentangBulanMarketing } from '@/lib/waktu';

const API = process.env.REACT_APP_BACKEND_URL;

const fmt = formatRupiah;
const fmtCompact = (n) => {
  if (!n) return 'Rp 0';
  if (n >= 1_000_000_000) return `Rp ${(n / 1_000_000_000).toFixed(1)}M`;
  if (n >= 1_000_000) return `Rp ${(n / 1_000_000).toFixed(1)}jt`;
  if (n >= 1_000) return `Rp ${(n / 1_000).toFixed(0)}rb`;
  return `Rp ${n.toLocaleString('id-ID')}`;
};
const fmtNum = (n) => Number(n || 0).toLocaleString('id-ID');
const pct = (n) => n != null ? `${(n * 100).toFixed(1)}%` : '-';

// ─── Target Progress Bar ──────────────────────────────────────────────────────
/** Tanggal WIB: awal bulan berjalan dan awal riwayat (60 hari, minimal awal bulan). */
function rentangDetail() {
  const hariIni = new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Jakarta' });
  // awal bulan Marketing berjalan (tanggal 26 bulan lalu — owner 11 Nov 2026), sama dengan periode target
  const awalBulan = rentangBulanMarketing(bulanMarketingDari(hariIni)).dari;
  const d60 = new Date(`${hariIni}T00:00:00Z`);
  d60.setUTCDate(d60.getUTCDate() - 59);
  const dari60 = d60.toISOString().slice(0, 10);
  return { hariIni, awalBulan, dari: dari60 < awalBulan ? dari60 : awalBulan };
}

function TargetBar({ label, actual, target, fmtFn = fmtCompact }) {
  if (target == null || target === 0) return null;
  const p = Math.min(Math.round((actual / target) * 100), 100);
  const over = actual > target;
  const color = p >= 90 ? 'bg-[hsl(var(--success))]' : p >= 70 ? 'bg-[hsl(var(--warning))]' : 'bg-[hsl(var(--destructive))]';
  const textColor = p >= 90 ? 'text-[hsl(var(--success-text))]' : p >= 70 ? 'text-[hsl(var(--warning-text))]' : 'text-[hsl(var(--danger-text))]';
  return (
    <div className="space-y-1" data-testid={`target-bar-${label.toLowerCase()}`}>
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className={`font-semibold tabular-nums ${textColor}`}>
          {fmtFn(actual)} / {fmtFn(target)}
          <span className="ml-1.5 font-bold">{p}%</span>
          {over && <span className="ml-1 text-[hsl(var(--success-text))]">(tercapai)</span>}
        </span>
      </div>
      <div className="h-2 bg-muted rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${p}%` }} />
      </div>
    </div>
  );
}

// ─── KPI Card ─────────────────────────────────────────────────────────────────
function KpiCard({ label, value, sub, icon: Icon, color = 'text-primary' }) {
  return (
    <GlassPanel className="p-4" data-testid={`kpi-${label.toLowerCase().replace(/\s+/g, '-')}`}>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-xs text-muted-foreground">{label}</span>
        {Icon && <Icon size={14} className={color} />}
      </div>
      <div className="text-xl font-bold tabular-nums">{value}</div>
      {sub && <div className="text-xs text-muted-foreground mt-0.5">{sub}</div>}
    </GlassPanel>
  );
}

// ─── Sales History Table ──────────────────────────────────────────────────────
function SalesTable({ data }) {
  if (!data.length) return (
    <div className="py-10 text-center text-muted-foreground text-sm">
      <Calendar size={32} className="mx-auto mb-2 opacity-30" />
      Belum ada data sales untuk akun ini
    </div>
  );

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs" data-testid="sales-history-table">
        <thead>
          <tr className="text-left text-muted-foreground border-b">
            <th className="py-2 px-3">Tanggal</th>
            <th className="py-2 px-3">Jenis</th>
            <th className="py-2 px-3 text-right">Omzet</th>
            <th className="py-2 px-3 text-right">Pesanan</th>
            <th className="py-2 px-3 text-right">AOV</th>
            <th className="py-2 px-3 text-right">Konversi</th>
            <th className="py-2 px-3 text-right">Rating</th>
          </tr>
        </thead>
        <tbody>
          {data.map((row, i) => (
            <tr key={row.id || i} className="border-b last:border-0 hover:bg-muted/20" data-testid={`sales-row-${i}`}>
              <td className="py-2 px-3">{row.date}</td>
              <td className="py-2 px-3">
                <Badge variant="outline" className={
                  row.revenue_type === 'live'
                    ? 'bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))] border-[hsl(var(--primary)/0.25)] text-xs'
                    : 'bg-[hsl(var(--info)/0.12)] text-[hsl(var(--info-text))] border-[hsl(var(--info)/0.3)] text-xs'
                }>
                  {row.revenue_type === 'live' ? 'Live' : 'Total'}
                </Badge>
              </td>
              <td className="py-2 px-3 text-right tabular-nums font-medium">{fmt(row.metrics?.revenue)}</td>
              <td className="py-2 px-3 text-right tabular-nums">{fmtNum(row.metrics?.orders)}</td>
              <td className="py-2 px-3 text-right tabular-nums">{fmt(row.metrics?.aov)}</td>
              <td className="py-2 px-3 text-right tabular-nums">{pct(row.metrics?.conversion_rate)}</td>
              <td className="py-2 px-3 text-right tabular-nums">
                {row.metrics?.rating ? (
                  <span className="flex items-center justify-end gap-0.5">
                    <Star size={10} className="text-[hsl(var(--warning))] fill-[hsl(var(--warning))]" />
                    {Number(row.metrics.rating).toFixed(1)}
                  </span>
                ) : '-'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Creators Tab ─────────────────────────────────────────────────────────────
function CreatorsTab({ creators, loading, creatorTargets = {} }) {
  if (loading) return <div className="py-10 flex justify-center"><Loader2 className="animate-spin" /></div>;
  if (!creators.length) return (
    <div className="py-10 text-center text-muted-foreground text-sm">
      <Users size={32} className="mx-auto mb-2 opacity-30" />
      Tidak ada KOL/Creator yang di-assign ke akun ini
    </div>
  );

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {creators.map(c => {
        const mt = creatorTargets[c.id];
        const revTgt  = mt?.revenue_target  || 0;
        const sessTgt = mt?.sessions_target || 0;
        const hasTarget = revTgt > 0 || sessTgt > 0;

        const revPct  = revTgt  > 0 ? Math.min(100, Math.round(((c.this_month?.revenue  || 0) / revTgt)  * 100)) : null;
        const sessPct = sessTgt > 0 ? Math.min(100, Math.round(((c.this_month?.sessions || 0) / sessTgt) * 100)) : null;
        const pctColor = (p) => p >= 90 ? 'bg-[hsl(var(--success))]' : p >= 60 ? 'bg-[hsl(var(--warning))]' : 'bg-[hsl(var(--destructive))]';

        return (
          <div key={c.id} className="rounded-lg border bg-card p-3" data-testid={`creator-card-${c.id}`}>
            <div className="flex items-center gap-2 mb-2">
              <div className="w-8 h-8 rounded-full bg-[hsl(var(--primary)/0.15)] flex items-center justify-center text-foreground text-xs font-bold shrink-0">
                {c.name?.charAt(0).toUpperCase()}
              </div>
              <div className="min-w-0">
                <div className="text-sm font-semibold truncate">{c.name}</div>
                <div className="text-xs text-muted-foreground">{c.creator_code}</div>
              </div>
              <div className={`text-xs ml-auto shrink-0 px-1.5 py-0.5 rounded-full border font-medium ${
                c.status === 'active' ? 'bg-[hsl(var(--success)/0.12)] text-[hsl(var(--success-text))] border-[hsl(var(--success)/0.3)]' : 'bg-[var(--glass-bg)] text-muted-foreground border-[var(--glass-border)]'
              }`}>{c.status}</div>
            </div>

            {/* Actual stats */}
            <div className="grid grid-cols-3 gap-1 text-center text-xs mb-2">
              <div className="rounded bg-muted/30 p-1.5">
                <div className="text-muted-foreground">Sesi</div>
                <div className="font-bold">{c.this_month?.sessions || 0}</div>
              </div>
              <div className="rounded bg-muted/30 p-1.5">
                <div className="text-muted-foreground">Omzet</div>
                <div className="font-bold text-[hsl(var(--success-text))]">{fmtCompact(c.this_month?.revenue || 0)}</div>
              </div>
              <div className="rounded bg-muted/30 p-1.5">
                <div className="text-muted-foreground">Viewers</div>
                <div className="font-bold">{fmtNum(c.this_month?.viewers || 0)}</div>
              </div>
            </div>

            {/* Per-month target progress */}
            {hasTarget && (
              <div className="space-y-1.5 pt-2 border-t border-border">
                {revTgt > 0 && (
                  <div>
                    <div className="flex justify-between text-xs mb-0.5">
                      <span className="text-muted-foreground">Omzet</span>
                      <span className={revPct >= 90 ? 'text-[hsl(var(--success-text))]' : revPct >= 60 ? 'text-[hsl(var(--warning-text))]' : 'text-[hsl(var(--danger-text))]'}>
                        {fmtCompact(c.this_month?.revenue || 0)} / {fmtCompact(revTgt)} ({revPct}%)
                      </span>
                    </div>
                    <div className="h-1 bg-muted rounded-full overflow-hidden">
                      <div className={`h-full ${pctColor(revPct)}`} style={{ width: `${revPct}%` }} />
                    </div>
                  </div>
                )}
                {sessTgt > 0 && (
                  <div>
                    <div className="flex justify-between text-xs mb-0.5">
                      <span className="text-muted-foreground">Sesi</span>
                      <span className={sessPct >= 90 ? 'text-[hsl(var(--success-text))]' : sessPct >= 60 ? 'text-[hsl(var(--warning-text))]' : 'text-[hsl(var(--danger-text))]'}>
                        {c.this_month?.sessions || 0} / {sessTgt} ({sessPct}%)
                      </span>
                    </div>
                    <div className="h-1 bg-muted rounded-full overflow-hidden">
                      <div className={`h-full ${pctColor(sessPct)}`} style={{ width: `${sessPct}%` }} />
                    </div>
                  </div>
                )}
                <p className="text-xs text-muted-foreground text-right">target {new Date().toLocaleString('id-ID',{month:'short',year:'numeric'})}</p>
              </div>
            )}
            {!hasTarget && (
              <p className="text-[9px] text-muted-foreground text-center pt-1 italic">Belum ada target bulan ini</p>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── LiveHosts Tab ────────────────────────────────────────────────────────────
function LiveHostsTab({ hosts, loading }) {
  if (loading) return <div className="py-10 flex justify-center"><Loader2 className="animate-spin" /></div>;
  if (!hosts.length) return (
    <div className="py-10 text-center text-muted-foreground text-sm">
      <Radio size={32} className="mx-auto mb-2 opacity-30" />
      Tidak ada LiveHost yang di-assign ke akun ini
    </div>
  );

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {hosts.map(h => (
        <div key={h.id} className="rounded-lg border bg-card p-3" data-testid={`host-card-${h.id}`}>
          <div className="flex items-center justify-between mb-2">
            <div>
              <div className="text-sm font-semibold">{h.name}</div>
              <div className="text-xs text-muted-foreground">{h.email}</div>
            </div>
            <Badge variant="outline" className={`text-xs ${
              h.status === 'active' ? 'bg-[hsl(var(--success)/0.12)] text-[hsl(var(--success-text))] border-[hsl(var(--success)/0.3)]' : 'bg-[var(--glass-bg)] text-muted-foreground border-[var(--glass-border)]'
            }`}>{h.status}</Badge>
          </div>
          <div className="text-xs text-muted-foreground">
            {h.employment_type} · Rp {fmtNum(h.hourly_rate)}/jam
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Orders Tab ───────────────────────────────────────────────────────────────
function OrdersTab({ orders, loading }) {
  if (loading) return <div className="py-10 flex justify-center"><Loader2 className="animate-spin" /></div>;
  if (!orders.length) return (
    <div className="py-10 text-center text-muted-foreground text-sm">
      <ShoppingBag size={32} className="mx-auto mb-2 opacity-30" />
      Belum ada data order untuk akun ini
    </div>
  );
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs" data-testid="account-orders-table">
        <thead><tr className="border-b text-muted-foreground">
          <th className="py-2 px-3 text-left">Order ID</th>
          <th className="py-2 px-3 text-left">Produk</th>
          <th className="py-2 px-3 text-right">Total</th>
          <th className="py-2 px-3 text-center">Status</th>
          <th className="py-2 px-3">Tanggal</th>
        </tr></thead>
        <tbody>
          {orders.slice(0, 50).map((o, i) => (
            <tr key={o.id || i} className="border-b last:border-0 hover:bg-muted/20">
              <td className="py-2 px-3">{o.order_id || o.id}</td>
              <td className="py-2 px-3 max-w-[160px] truncate">{o.product_name || o.items?.[0]?.name || '—'}</td>
              <td className="py-2 px-3 text-right tabular-nums">{fmtCompact(o.total_payment || o.revenue || 0)}</td>
              <td className="py-2 px-3 text-center">
                <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                  o.status === 'delivered' ? 'bg-[hsl(var(--success)/0.12)] text-[hsl(var(--success-text))]' :
                  o.status === 'cancelled' ? 'bg-[hsl(var(--destructive)/0.10)] text-[hsl(var(--danger-text))]' : 'bg-[hsl(var(--info)/0.12)] text-[hsl(var(--info-text))]'
                }`}>{o.status}</span>
              </td>
              <td className="py-2 px-3 text-muted-foreground">{o.order_date?.slice(0, 10) || o.date || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Complaints Tab ───────────────────────────────────────────────────────────
function ComplaintsTab({ complaints, loading }) {
  if (loading) return <div className="py-10 flex justify-center"><Loader2 className="animate-spin" /></div>;
  if (!complaints.length) return (
    <div className="py-10 text-center text-muted-foreground text-sm">
      <MessageCircle size={32} className="mx-auto mb-2 opacity-30" />
      Belum ada komplain untuk akun ini
    </div>
  );
  return (
    <div className="space-y-2" data-testid="account-complaints-list">
      {complaints.map((c, i) => (
        <div key={c.id || i} className="rounded-lg border bg-card p-3">
          <div className="flex items-start justify-between gap-2 mb-1">
            <div className="text-xs text-muted-foreground">{c.complaint_number || c.id?.slice(0,8)}</div>
            <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${
              c.status === 'resolved' ? 'bg-[hsl(var(--success)/0.12)] text-[hsl(var(--success-text))]' :
              c.status === 'open' ? 'bg-[hsl(var(--destructive)/0.10)] text-[hsl(var(--danger-text))]' : 'bg-[hsl(var(--warning)/0.14)] text-[hsl(var(--warning-text))]'
            }`}>{c.status}</span>
          </div>
          <p className="text-sm font-medium truncate">{c.complaint_text || c.title || '—'}</p>
          <p className="text-xs text-muted-foreground mt-1">{c.product_name && `${c.product_name} · `}{c.complaint_date?.slice(0,10) || c.date || ''}</p>
        </div>
      ))}
    </div>
  );
}

// ─── Reviews Tab ─────────────────────────────────────────────────────────────
function ReviewsTab({ reviews, loading }) {
  if (loading) return <div className="py-10 flex justify-center"><Loader2 className="animate-spin" /></div>;
  if (!reviews.length) return (
    <div className="py-10 text-center text-muted-foreground text-sm">
      <Star size={32} className="mx-auto mb-2 opacity-30" />
      Belum ada review untuk akun ini
    </div>
  );
  return (
    <div className="space-y-2" data-testid="account-reviews-list">
      {reviews.map((r, i) => (
        <div key={r.id || i} className="rounded-lg border bg-card p-3">
          <div className="flex items-center gap-2 mb-1">
            <div className="flex">
              {[1,2,3,4,5].map(s => (
                <Star key={s} size={11} className={s <= (r.rating || 0) ? 'text-[hsl(var(--warning))] fill-[hsl(var(--warning))]' : 'text-muted-foreground'} />
              ))}
            </div>
            <span className={`text-xs px-1.5 py-0.5 rounded font-medium ml-auto ${
              r.status === 'responded' ? 'bg-[hsl(var(--success)/0.12)] text-[hsl(var(--success-text))]' : 'bg-[hsl(var(--warning)/0.14)] text-[hsl(var(--warning-text))]'
            }`}>{r.status || 'pending'}</span>
          </div>
          <p className="text-sm truncate">{r.review_text || '—'}</p>
          <p className="text-xs text-muted-foreground mt-1">{r.product && `${r.product} · `}{r.date || ''}</p>
        </div>
      ))}
    </div>
  );
}

// ─── MAIN COMPONENT ───────────────────────────────────────────────────────────
const PLATFORM_LABEL_DETAIL = { shopee: 'Shopee', tiktok: 'TikTok Shop', tiktokshop: 'TikTok Shop', tokopedia: 'Tokopedia', lazada: 'Lazada' };
const labelPlatformDetail = (p) => PLATFORM_LABEL_DETAIL[String(p || '').toLowerCase()] || p || '';

/** Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout (judul = nama toko, tombol Kembali di kepala), 6 kartu → 4 StatTile,
 *  tab standar tanpa ikon, unduh Excel/CSV untuk riwayat sales & pesanan, warna token. */
export function AccountDetailPage({ account, token, onBack, onNavigate }) {
  const { setActiveAccount } = useActiveMarketingAccount();
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);
  const cfg = getPlatformConfig(account.platform);

  const [salesData, setSalesData] = useState([]);
  const [creators, setCreators] = useState([]);
  const [hosts, setHosts] = useState([]);
  const [orders, setOrders] = useState([]);
  const [complaints, setComplaints] = useState([]);
  const [reviews, setReviews] = useState([]);
  const [target, setTarget] = useState(null);
  const [creatorTargets, setCreatorTargets] = useState({});
  const [loading, setLoading] = useState(true);
  const [creatorsLoading, setCreatorsLoading] = useState(true);
  const [hostsLoading, setHostsLoading] = useState(true);
  const [ordersLoading, setOrdersLoading] = useState(true);
  const [complaintsLoading, setComplaintsLoading] = useState(true);
  const [reviewsLoading, setReviewsLoading] = useState(true);
  const [tab, setTab] = useState('sales');

  // Fetch sales data
  const fetchSales = useCallback(async () => {
    setLoading(true);
    try {
      // M-08 (audit 9 Nov 2026) — dulu SEMUA riwayat diambil lalu dijumlah lalu dibandingkan
      // dengan target BULAN INI. Sekarang 60 hari terakhir (untuk riwayat & grafik) dan KPI
      // hanya menjumlah bulan berjalan (WIB).
      const { dari } = rentangDetail();
      const res = await fetch(`${API}/api/marketing/accounts/${account.id}/sales?revenue_type=total&date_from=${dari}&limit=500`, { headers });
      if (res.ok) {
        const data = await res.json();
        setSalesData(Array.isArray(data) ? data.sort((a, b) => b.date.localeCompare(a.date)) : []);
      }
    } catch { toast.error('Gagal memuat data sales'); }
    finally { setLoading(false); }
  }, [account.id, headers]);

  // Fetch assigned KOL creators + their per-month targets
  const fetchCreators = useCallback(async () => {
    setCreatorsLoading(true);
    try {
      const [crRes, tgRes] = await Promise.all([
        fetch(`${API}/api/marketing/kol/creators?account_id=${account.id}&limit=50`, { headers }),
        fetch(`${API}/api/marketing/targets/creator?year=${bulanMarketingWIB().slice(0, 4)}&month=${Number(bulanMarketingWIB().slice(5, 7))}`, { headers }),
      ]);
      if (crRes.ok) {
        const data = await crRes.json();
        setCreators(data?.creators || (Array.isArray(data) ? data : []));
      }
      if (tgRes.ok) {
        const tgts = await tgRes.json();
        const map = {};
        if (Array.isArray(tgts)) tgts.forEach(t => { map[t.creator_id] = t; });
        setCreatorTargets(map);
      }
    } catch { /* noop */ }
    finally { setCreatorsLoading(false); }
  }, [account.id, headers]); // eslint-disable-line

  // Fetch assigned LiveHosts (client-side filter)
  const fetchHosts = useCallback(async () => {
    setHostsLoading(true);
    try {
      const res = await fetch(`${API}/api/marketing/livehost`, { headers });
      if (res.ok) {
        const data = await res.json();
        const filtered = (Array.isArray(data) ? data : []).filter(h =>
          (h.assigned_accounts || []).some(a => a.id === account.id)
        );
        setHosts(filtered);
      }
    } catch { /* noop */ }
    finally { setHostsLoading(false); }
  }, [account.id, headers]);

  useEffect(() => {
    fetchSales();
    fetchCreators();
    fetchHosts();
    // Fetch target bulan ini
    fetch(`${API}/api/marketing/targets?account_id=${account.id}&year=${bulanMarketingWIB().slice(0, 4)}&month=${Number(bulanMarketingWIB().slice(5, 7))}`, { headers })
      .then(r => r.ok ? r.json() : [])
      .then(data => setTarget(Array.isArray(data) && data.length > 0 ? data[0] : null))
      .catch(() => {});
    // Fetch orders (by account_name since orders use string-based matching)
    setOrdersLoading(true);
    fetch(`${API}/api/marketing/orders?account_name=${encodeURIComponent(account.account_name)}&limit=50`, { headers })
      .then(r => r.ok ? r.json() : { orders: [] })
      .then(d => setOrders(Array.isArray(d) ? d : (d.orders || [])))
      .catch(() => {})
      .finally(() => setOrdersLoading(false));
    // Fetch complaints by account_id
    setComplaintsLoading(true);
    fetch(`${API}/api/marketing/complaints?account_id=${account.id}&page_size=50`, { headers })
      .then(r => r.ok ? r.json() : { complaints: [] })
      .then(d => setComplaints(d.complaints || []))
      .catch(() => {})
      .finally(() => setComplaintsLoading(false));
    // Fetch reviews by account_id
    setReviewsLoading(true);
    fetch(`${API}/api/marketing/reviews?account_id=${account.id}&page_size=50`, { headers })
      .then(r => r.ok ? r.json() : { data: [] })
      .then(d => setReviews(d.data || []))
      .catch(() => {})
      .finally(() => setReviewsLoading(false));
  }, [fetchSales, fetchCreators, fetchHosts]); // eslint-disable-line

  // Compute revenue trend from sales data
  // Q-2 — omzet live resmi = pesanan berkanal LIVE di rekap total (`traffic.live`).
  const trendData = useMemo(() => {
    const map = {};
    salesData.forEach(row => {
      if (row.revenue_type === 'live') return;
      if (!map[row.date]) map[row.date] = { date: row.date, total: 0, live: 0 };
      map[row.date].total += row.metrics?.revenue || 0;
      map[row.date].live += row.traffic?.live || 0;
    });
    return Object.values(map).sort((a, b) => a.date.localeCompare(b.date));
  }, [salesData]);

  // KPI = bulan berjalan (WIB), sama dengan periode target di bawahnya (M-08)
  const kpi = useMemo(() => {
    const { awalBulan } = rentangDetail();
    const totalRows = salesData.filter(r => r.revenue_type === 'total' && r.date >= awalBulan);
    const rev = totalRows.reduce((s, r) => s + (r.metrics?.revenue || 0), 0);
    const revLive = totalRows.reduce((s, r) => s + (r.traffic?.live || 0), 0);
    const orders = totalRows.reduce((s, r) => s + (r.metrics?.orders || 0), 0);
    const aov = orders > 0 ? rev / orders : 0;
    const ratings = totalRows.map(r => r.metrics?.rating).filter(Boolean);
    const avgRating = ratings.length ? (ratings.reduce((s, r) => s + r, 0) / ratings.length) : null;
    return { rev, revLive, orders, aov, avgRating, days: totalRows.length };
  }, [salesData]);

  const healthColor = account.health_score >= 80 ? 'success'
    : account.health_score >= 60 ? 'warning'
    : account.health_score != null ? 'danger' : 'default';
  const [_bmY, _bmM] = bulanMarketingWIB().split('-').map(Number);
  const bulanIni = new Date(Date.UTC(_bmY, _bmM - 1, 1)).toLocaleString('id-ID', { month: 'long', year: 'numeric', timeZone: 'UTC' });
  const rentangBulanIni = labelRentangBulanMarketing(_bmY, _bmM);
  const tombolUnduh = (tab === 'sales' && salesData.length > 0) ? (
    <TombolUnduh namaBerkas={`riwayat-sales-${account.account_code}`} namaLembar="Riwayat sales" baris={salesData} testId="detail-sales-unduh"
      kolom={[
        { label: 'Tanggal', nilai: (r) => r.date }, { label: 'Jenis', nilai: (r) => (r.revenue_type === 'live' ? 'Live' : 'Total') },
        { label: 'Omzet', nilai: (r) => Number(r.metrics?.revenue || 0) }, { label: 'Pesanan', nilai: (r) => Number(r.metrics?.orders || 0) },
        { label: 'Rating', nilai: (r) => r.metrics?.rating ?? '' },
      ]} />
  ) : (tab === 'orders' && orders.length > 0) ? (
    <TombolUnduh namaBerkas={`pesanan-${account.account_code}`} namaLembar="Pesanan" baris={orders} testId="detail-orders-unduh"
      kolom={[
        { label: 'Nomor pesanan', nilai: (o) => o.order_id || o.id }, { label: 'Produk', nilai: (o) => o.product_name || '' },
        { label: 'Total', nilai: (o) => Number(o.total_payment || o.total || 0) }, { label: 'Status', nilai: (o) => o.status || '' },
        { label: 'Tanggal', nilai: (o) => String(o.order_date || '').slice(0, 10) },
      ]} />
  ) : null;

  return (
    <PageLayout testId="account-detail-page" title={account.account_name}
      subtitle={[account.account_code, labelPlatformDetail(account.platform), account.username ? `@${account.username}` : null,
        account.status === 'active' ? 'Aktif' : (account.status || null)].filter(Boolean).join(' · ')}
      actions={<>
        <Button variant="outline" onClick={onBack} data-testid="back-to-dashboard"><ArrowLeft />Kembali</Button>
        <Button variant="outline" onClick={() => { setActiveAccount(account); toast.success(`Akun aktif: ${account.account_name}`); }}
          data-testid="set-active-account">Jadikan akun aktif</Button>
        <Button onClick={() => { setActiveAccount(account); onNavigate?.('marketing-sales'); }} data-testid="goto-input-sales">
          <TrendingUp />Input sales
        </Button>
      </>}
      summary={(
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label={`Omzet ${bulanIni}`} value={fmtCompact(kpi.rev)} sub={`Dari live ${fmtCompact(kpi.revLive)} · ${kpi.days} hari berdata`} testId="kpi-total-revenue" />
          <StatTile label="Pesanan" value={fmtNum(kpi.orders)} sub={kpi.orders ? `Rata-rata ${fmtCompact(kpi.aov)} per pesanan` : 'Belum ada pesanan'} testId="kpi-total-orders" />
          <StatTile label="Skor kesehatan" value={account.health_score != null ? account.health_score : '—'} accent={healthColor}
            sub={account.health_score >= 80 ? 'Sangat baik' : account.health_score >= 60 ? 'Baik' : account.health_score != null ? 'Perlu perhatian' : 'Belum ada data 30 hari terakhir'}
            testId="kpi-health-score" />
          <StatTile label="Kreator & host live" value={`${creators.length} · ${hosts.length}`} sub="Kreator KOL · host live yang ditugaskan" testId="kpi-kol" />
        </div>
      )}>
      {/* Target bulan ini */}
      <section className="space-y-2" data-testid="account-target-section">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-base font-semibold">Target {bulanIni} <span className="text-sm font-normal text-muted-foreground">({rentangBulanIni})</span></p>
          <Button size="sm" variant="outline" onClick={() => onNavigate?.('marketing-targets')} data-testid="goto-set-target">
            <Target />{target ? 'Ubah target' : 'Isi target'}
          </Button>
        </div>
        {target ? (
          <div className="space-y-3">
            <TargetBar label="Omzet" actual={kpi.rev} target={target.revenue_target} fmtFn={fmtCompact} />
            <TargetBar label="Pesanan" actual={kpi.orders} target={target.orders_target} fmtFn={(n) => fmtNum(n)} />
            {target.notes && <p className="text-sm text-muted-foreground">Catatan: {target.notes}</p>}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Belum ada target untuk bulan ini.</p>
        )}
      </section>

      {/* Tren omzet */}
      <GlassCard className="space-y-3 p-4" data-testid="account-revenue-chart">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="text-base font-semibold">Tren omzet</p>
            <p className="text-sm text-muted-foreground">Omzet total dan live per hari.</p>
          </div>
          <Button variant="outline" size="icon" onClick={fetchSales} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
        </div>
        {loading ? (
          <p className="py-10 text-center text-sm text-muted-foreground">Memuat data…</p>
        ) : (
          <RevenueChart data={trendData} height={220} />
        )}
      </GlassCard>

      {/* Sales · Kreator · Host live · Pesanan · Komplain · Ulasan */}
      <Tabs value={tab} onValueChange={setTab}>
        <div className="flex flex-wrap items-center gap-3">
          <TabsList data-testid="account-detail-tabs" className="h-auto max-w-full justify-start gap-1 max-sm:flex-nowrap max-sm:overflow-x-auto sm:flex-wrap">
            <TabsTrigger value="sales" className="shrink-0" data-testid="tab-sales">Riwayat sales</TabsTrigger>
            <TabsTrigger value="creators" className="shrink-0" data-testid="tab-creators">Kreator ({creators.length})</TabsTrigger>
            <TabsTrigger value="hosts" className="shrink-0" data-testid="tab-hosts">Host live ({hosts.length})</TabsTrigger>
            <TabsTrigger value="orders" className="shrink-0" data-testid="tab-orders">Pesanan ({orders.length})</TabsTrigger>
            <TabsTrigger value="complaints" className="shrink-0" data-testid="tab-complaints">Komplain ({complaints.length})</TabsTrigger>
            <TabsTrigger value="reviews" className="shrink-0" data-testid="tab-reviews">Ulasan ({reviews.length})</TabsTrigger>
          </TabsList>
          {tombolUnduh && <div className="ml-auto">{tombolUnduh}</div>}
        </div>

        <TabsContent value="sales" className="mt-4">
          {loading ? <p className="py-10 text-center text-sm text-muted-foreground">Memuat…</p> : <SalesTable data={salesData} />}
        </TabsContent>
        <TabsContent value="creators" className="mt-4">
          <CreatorsTab creators={creators} loading={creatorsLoading} creatorTargets={creatorTargets} />
        </TabsContent>
        <TabsContent value="hosts" className="mt-4">
          <LiveHostsTab hosts={hosts} loading={hostsLoading} />
        </TabsContent>
        <TabsContent value="orders" className="mt-4">
          <OrdersTab orders={orders} loading={ordersLoading} />
        </TabsContent>
        <TabsContent value="complaints" className="mt-4">
          <ComplaintsTab complaints={complaints} loading={complaintsLoading} />
        </TabsContent>
        <TabsContent value="reviews" className="mt-4">
          <ReviewsTab reviews={reviews} loading={reviewsLoading} />
        </TabsContent>
      </Tabs>
    </PageLayout>
  );
}

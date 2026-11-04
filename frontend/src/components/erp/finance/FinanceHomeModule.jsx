/**
 * Beranda Keuangan — menu pertama Portal Keuangan (2026-11-04, keputusan owner, audit Keuangan tahap 4).
 *
 * Menggantikan Dashboard Keuangan (tautan + kartu dari sumber berbeda) dan Rekap Keuangan (rumus
 * hutang/piutang sendiri). Semua angka dari `GET /api/finance/home`, yang meminjam rumus laporan:
 * kas dari buku besar, hutang = pemasok + CMT, laba = rumus Laba Rugi. Setiap kartu dan baris
 * "Perlu ditindaklanjuti" membuka menu tempat pekerjaannya diselesaikan.
 */
import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, ArrowRight, Landmark, RefreshCw, ScrollText, Store, ReceiptText, CheckCircle2 } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { toast } from 'sonner';
import { formatRupiah, formatDateID, formatPercent } from '@/lib/format';

const API = process.env.REACT_APP_BACKEND_URL || '';
const fmt = formatRupiah;
const LEVEL_CLS = {
  danger: 'border-l-red-500',
  warning: 'border-l-amber-500',
  info: 'border-l-sky-500',
};

function go(onNavigate, module, tab) {
  if (tab) {
    try { sessionStorage.setItem(`hub_tab_${module}`, tab); } catch { /* penyimpanan diblokir */ }
  }
  onNavigate?.(module);
}

function Kpi({ icon: Icon, label, value, sub, subTone, onClick, testId }) {
  return (
    <button type="button" onClick={onClick} data-testid={testId}
      className="text-left rounded-xl border border-[var(--glass-border)] bg-[var(--card-surface)] p-4 hover:border-[hsl(var(--primary))]/50 transition-colors">
      <div className="flex items-center gap-2 text-xs text-muted-foreground"><Icon className="w-3.5 h-3.5" />{label}</div>
      <div className="mt-1 text-2xl font-bold tabular-nums text-foreground">{value}</div>
      {sub && <div className={`mt-0.5 text-xs ${subTone || 'text-muted-foreground'}`}>{sub}</div>}
    </button>
  );
}

export default function FinanceHomeModule({ token, onNavigate }) {
  const [d, setD] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/finance/home`, { headers: { Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` } });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) { toast.error(j.detail || `Gagal memuat Beranda (HTTP ${r.status})`); return; }
      setD(j);
    } finally { setLoading(false); }
  }, [token]);
  useEffect(() => { load(); }, [load]);

  if (loading && !d) {
    return (
      <div className="space-y-4" data-testid="finance-home">
        <Skeleton className="h-8 w-64" />
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">{[0, 1, 2, 3].map(i => <Skeleton key={i} className="h-28 rounded-xl" />)}</div>
        <Skeleton className="h-64 rounded-xl" />
      </div>
    );
  }
  if (!d) return null;
  const { cash, stores, receivables: ar, payables: ap, profit, marketplace: mp, todo } = d;
  const cur = profit.this_month;
  const prev = profit.last_month;

  return (
    <div className="space-y-5" data-testid="finance-home">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Beranda Keuangan</h1>
          <p className="text-sm text-muted-foreground">{formatDateID(d.today, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}</p>
        </div>
        <Button size="icon" variant="outline" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Kpi icon={Landmark} label="Kas & bank" value={fmt(cash.balance)} testId="home-kpi-cash"
          sub={`Bulan ini masuk ${fmt(cash.cash_in)} · keluar ${fmt(cash.cash_out)}`}
          onClick={() => go(onNavigate, 'fin-cash')} />
        <Kpi icon={Store} label="Saldo di toko marketplace" value={fmt(stores.total)} testId="home-kpi-stores"
          sub={`${stores.stores.length} toko bersaldo · belum ditarik ke bank`}
          onClick={() => go(onNavigate, 'fin-marketplace-settlement', 'balances')} />
        <Kpi icon={ScrollText} label="Piutang reseller" value={fmt(ar.total)} testId="home-kpi-ar"
          sub={ar.overdue ? `${fmt(ar.overdue)} lewat jatuh tempo` : `${ar.count} faktur belum lunas`}
          subTone={ar.overdue ? 'text-red-600 dark:text-red-400' : undefined}
          onClick={() => go(onNavigate, 'fin-ar-hub', 'aging')} />
        <Kpi icon={ReceiptText} label="Hutang pemasok & CMT" value={fmt(ap.total)} testId="home-kpi-ap"
          sub={ap.overdue ? `${fmt(ap.overdue)} lewat jatuh tempo` : `${ap.count} tagihan terbuka`}
          subTone={ap.overdue ? 'text-red-600 dark:text-red-400' : undefined}
          onClick={() => go(onNavigate, 'fin-ap-hub', 'aging')} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <GlassCard className="p-4 lg:col-span-2" data-testid="home-todo">
          <h2 className="text-sm font-semibold text-foreground mb-3">Perlu ditindaklanjuti</h2>
          {todo.length === 0 ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground py-6 justify-center">
              <CheckCircle2 className="w-4 h-4 text-emerald-500" /> Tidak ada pekerjaan tertunda.
            </div>
          ) : (
            <ul className="space-y-2">
              {todo.map(t => (
                <li key={t.key} className={`flex items-center gap-3 rounded-lg border border-[var(--glass-border)] border-l-4 ${LEVEL_CLS[t.level] || ''} px-3 py-2`} data-testid={`home-todo-${t.key}`}>
                  <span className="text-lg font-bold tabular-nums w-10 text-right text-foreground">{t.count}</span>
                  <span className="text-sm text-foreground flex-1">{t.label}{t.amount ? <span className="text-muted-foreground"> · {fmt(t.amount)}</span> : null}</span>
                  <Button size="sm" variant="outline" onClick={() => go(onNavigate, t.module, t.tab)}>
                    Buka <ArrowRight className="w-3.5 h-3.5 ml-1" />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </GlassCard>

        <div className="space-y-4">
          <GlassCard className="p-4" data-testid="home-profit">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-sm font-semibold text-foreground">Laba bulan ini</h2>
              <button type="button" className="text-xs text-primary hover:underline" onClick={() => go(onNavigate, 'fin-pnl')}>Laba Rugi</button>
            </div>
            <div className="text-2xl font-bold tabular-nums text-foreground">{fmt(cur.net_income)}</div>
            <p className="text-xs text-muted-foreground mb-3">
              laba bersih {formatDateID(profit.this_month_from)} – {formatDateID(d.today)}
            </p>
            <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
              <dt className="text-muted-foreground">Pendapatan</dt><dd className="text-right tabular-nums">{fmt(cur.revenue)}</dd>
              <dt className="text-muted-foreground">Laba kotor</dt><dd className="text-right tabular-nums">{fmt(cur.gross_profit)}</dd>
              <dt className="text-muted-foreground">Beban</dt><dd className="text-right tabular-nums">{fmt(cur.expense)}</dd>
              {/* bulan berjalan belum penuh → tanpa persen naik/turun (menyesatkan di awal bulan) */}
              <dt className="text-muted-foreground border-t border-[var(--glass-border)] pt-1 mt-1">Laba bersih bulan lalu (sebulan penuh)</dt><dd className="text-right tabular-nums border-t border-[var(--glass-border)] pt-1 mt-1">{fmt(prev.net_income)}</dd>
            </dl>
          </GlassCard>

          <GlassCard className="p-4" data-testid="home-marketplace">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-sm font-semibold text-foreground">Dana marketplace bulan ini</h2>
              <button type="button" className="text-xs text-primary hover:underline" onClick={() => go(onNavigate, 'fin-marketplace-settlement', 'settlements')}>Marketplace</button>
            </div>
            {mp.count === 0 ? (
              <p className="text-xs text-muted-foreground">Belum ada laporan dana dilepas bulan ini.</p>
            ) : (
              <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                <dt className="text-muted-foreground">Penjualan kotor</dt><dd className="text-right tabular-nums">{fmt(mp.gross_sales)}</dd>
                <dt className="text-muted-foreground">Potongan</dt><dd className="text-right tabular-nums">{fmt(mp.deductions)} ({formatPercent(mp.deduction_pct, 1)})</dd>
                <dt className="text-muted-foreground">Dana bersih</dt><dd className="text-right tabular-nums font-medium">{fmt(mp.net_payout)}</dd>
                <dt className="text-muted-foreground">Laporan</dt><dd className="text-right tabular-nums">{mp.count}</dd>
              </dl>
            )}
          </GlassCard>
        </div>
      </div>

      {stores.stores.length > 0 && (
        <GlassCard className="p-4" data-testid="home-stores">
          <h2 className="text-sm font-semibold text-foreground mb-2">Saldo per toko</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-1">
            {stores.stores.slice(0, 12).map(s => (
              <div key={s.code} className="flex justify-between text-xs py-1 border-b border-[var(--glass-border)]">
                <span className="text-foreground truncate pr-2" title={s.code}>{s.name}</span>
                <span className={`tabular-nums ${s.balance < 0 ? 'text-red-600 dark:text-red-400' : ''}`}>{fmt(s.balance)}</span>
              </div>
            ))}
          </div>
          {stores.stores.length > 12 && <p className="text-[11px] text-muted-foreground mt-2">+ {stores.stores.length - 12} toko lain</p>}
        </GlassCard>
      )}

      {ap.unposted_cmt > 0 && (
        <p className="text-xs text-muted-foreground flex items-center gap-1.5">
          <AlertTriangle className="w-3.5 h-3.5 text-amber-500" />
          Hutang di atas belum memuat {fmt(ap.unposted_cmt)} tagihan CMT yang belum dijurnal.
        </p>
      )}
    </div>
  );
}

/**
 * Beranda Keuangan — menu pertama Portal Keuangan (2026-11-04, keputusan owner, audit Keuangan tahap 4).
 *
 * Menggantikan Dashboard Keuangan (tautan + kartu dari sumber berbeda) dan Rekap Keuangan (rumus
 * hutang/piutang sendiri). Semua angka dari `GET /api/finance/home`, yang meminjam rumus laporan:
 * kas dari buku besar, hutang = pemasok + CMT, laba = rumus Laba Rugi. Setiap kartu dan baris
 * "Perlu ditindaklanjuti" membuka menu tempat pekerjaannya diselesaikan.
 *
 * 2026-11-05 (PANDUAN_UI G1/G8/G10): memakai cetakan PageLayout (kepala + muat ulang dari cetakan, kartu
 * angka di slot `summary`); warna hanya token; kosong = EmptyState; bulan "2026-10" ditulis "Oktober 2026".
 * Kartu angka = StatTile (keterangan `sub`, merah bila ada yang lewat jatuh tempo) — dulu tombol-kartu buatan sendiri.
 */
import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, ArrowRight, RefreshCw, Store, CheckCircle2 } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { toast } from 'sonner';
import { formatRupiah, formatDateID, formatPercent } from '@/lib/format';
import { EmptyState, StatTile } from '../moduleAtoms';
import PageLayout from '../layout/PageLayout';

const API = process.env.REACT_APP_BACKEND_URL || '';
const fmt = formatRupiah;
const LEVEL_CLS = {
  danger: 'border-l-[hsl(var(--destructive))]',
  warning: 'border-l-[hsl(var(--warning))]',
  info: 'border-l-[hsl(var(--primary))]',
};
const DANGER_TEXT = 'text-[hsl(var(--destructive))]';
// Label tugas dari server bisa memuat bulan mentah ("… untuk 2026-10") — tampilkan "Oktober 2026".
const humanMonths = (s) => String(s || '').replace(/\b(20\d{2})-(0[1-9]|1[0-2])\b/g,
  (_, y, m) => formatDateID(`${y}-${m}-15`, { month: 'long', year: 'numeric' }));

function go(onNavigate, module, tab) {
  if (tab) {
    try { sessionStorage.setItem(`hub_tab_${module}`, tab); } catch { /* penyimpanan diblokir */ }
  }
  onNavigate?.(module);
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

  const refreshBtn = (
    <Button size="icon" variant="outline" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang" data-testid="home-refresh">
      <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
    </Button>
  );

  if (loading && !d) {
    return (
      <PageLayout testId="finance-home" title="Beranda Keuangan" tools={refreshBtn}
        summary={<div className="grid grid-cols-2 lg:grid-cols-4 gap-3">{[0, 1, 2, 3].map(i => <Skeleton key={i} className="h-28 rounded-xl" />)}</div>}>
        <Skeleton className="h-64 rounded-xl" />
      </PageLayout>
    );
  }
  if (!d) return null;
  const { cash, stores, receivables: ar, payables: ap, profit, marketplace: mp, todo } = d;
  const cur = profit.this_month;
  const prev = profit.last_month;

  return (
    <PageLayout
      testId="finance-home"
      title="Beranda Keuangan"
      subtitle={formatDateID(d.today, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}
      tools={refreshBtn}
      summary={
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <StatTile label="Kas & bank" value={fmt(cash.balance)} testId="home-kpi-cash"
            sub={`Bulan ini masuk ${fmt(cash.cash_in)} · keluar ${fmt(cash.cash_out)}`}
            onClick={() => go(onNavigate, 'fin-cash')} />
          <StatTile label="Saldo di toko marketplace" value={fmt(stores.total)} testId="home-kpi-stores"
            sub={`${stores.stores.length} toko bersaldo · belum ditarik ke bank`}
            onClick={() => go(onNavigate, 'fin-marketplace-settlement', 'balances')} />
          <StatTile label="Piutang reseller" value={fmt(ar.total)} testId="home-kpi-ar"
            sub={ar.overdue ? `${fmt(ar.overdue)} lewat jatuh tempo` : `${ar.count} faktur belum lunas`}
            subTone={ar.overdue ? 'danger' : undefined}
            onClick={() => go(onNavigate, 'fin-ar-hub', 'aging')} />
          <StatTile label="Hutang pemasok & CMT" value={fmt(ap.total)} testId="home-kpi-ap"
            sub={ap.overdue ? `${fmt(ap.overdue)} lewat jatuh tempo` : `${ap.count} tagihan terbuka`}
            subTone={ap.overdue ? 'danger' : undefined}
            onClick={() => go(onNavigate, 'fin-ap-hub', 'aging')} />
        </div>
      }
      footer={ap.unposted_cmt > 0 && (
        <p className="text-xs text-muted-foreground flex items-center gap-1.5" data-testid="home-unposted-cmt">
          <AlertTriangle className="w-3.5 h-3.5 text-[hsl(var(--warning))]" />
          Hutang di atas belum memuat {fmt(ap.unposted_cmt)} tagihan CMT yang belum dijurnal.
        </p>
      )}
    >
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <GlassCard className="p-4 lg:col-span-2" data-testid="home-todo">
          <h2 className="text-sm font-semibold text-foreground mb-3">Perlu ditindaklanjuti</h2>
          {todo.length === 0 ? (
            <EmptyState icon={CheckCircle2} className="py-8" title="Tidak ada pekerjaan tertunda"
              description="Pekerjaan yang perlu ditindaklanjuti akan muncul di sini." />
          ) : (
            <ul className="space-y-2">
              {todo.map(t => (
                <li key={t.key} className={`flex items-center gap-3 rounded-lg border border-[var(--glass-border)] border-l-4 ${LEVEL_CLS[t.level] || ''} px-3 py-2`} data-testid={`home-todo-${t.key}`}>
                  <span className="text-lg font-bold tabular-nums w-10 text-right text-foreground">{t.count}</span>
                  <span className="text-sm text-foreground flex-1">{humanMonths(t.label)}{t.amount ? <span className="text-muted-foreground tabular-nums"> · {fmt(t.amount)}</span> : null}</span>
                  <Button size="sm" variant="outline" onClick={() => go(onNavigate, t.module, t.tab)}>
                    Buka <ArrowRight className="w-3.5 h-3.5" />
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
              <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={() => go(onNavigate, 'fin-pnl')}>Laba Rugi</Button>
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
              <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={() => go(onNavigate, 'fin-marketplace-settlement', 'settlements')}>Marketplace</Button>
            </div>
            {mp.count === 0 ? (
              <EmptyState icon={Store} className="py-4" title="Belum ada dana dilepas bulan ini"
                description="Laporan dana dilepas dicatat di Marketplace › Dana dilepas." />
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
                <span className={`tabular-nums whitespace-nowrap ${s.balance < 0 ? DANGER_TEXT : ''}`}>{fmt(s.balance)}</span>
              </div>
            ))}
          </div>
          {stores.stores.length > 12 && <p className="text-[11px] text-muted-foreground mt-2">+ {stores.stores.length - 12} toko lain</p>}
        </GlassCard>
      )}
    </PageLayout>
  );
}

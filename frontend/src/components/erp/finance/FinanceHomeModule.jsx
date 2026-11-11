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
 * 2026-11-08 (Standar UI/UX v2): saldo per toko = tabel (bisa diunduh Excel/CSV), judul bagian tanpa <h2>,
 * keterangan kartu diringkas (Rp 62 jt) supaya keempat kartu sama tinggi; tiap kartu diberi `hint` sumbernya.
 */
import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, ArrowRight, RefreshCw, Store, CheckCircle2 } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { toast } from 'sonner';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { formatRupiah, formatRupiahShort, formatDateID, formatPercent } from '@/lib/format';
import { EmptyState, StatTile } from '../moduleAtoms';
import PageLayout from '../layout/PageLayout';

const API = process.env.REACT_APP_BACKEND_URL || '';
const fmt = formatRupiah;
const LEVEL_CLS = {
  danger: 'border-l-[hsl(var(--destructive))]',
  warning: 'border-l-[hsl(var(--warning))]',
  info: 'border-l-[hsl(var(--primary))]',
};
const DANGER_TEXT = 'text-[hsl(var(--danger-text))]';
// Angka kartu: penuh di layar lebar, ringkas di HP (dulu "Rp 3.394.525.736" patah dua baris di kartu selebar 170 px).
const nilaiKartu = (n) => (<><span className="sm:hidden">{formatRupiahShort(n)}</span><span className="hidden sm:inline">{fmt(n)}</span></>);
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
          <StatTile label="Kas & bank" value={nilaiKartu(cash.balance)} testId="home-kpi-cash"
            sub={`Bulan ini masuk ${formatRupiahShort(cash.cash_in)} · keluar ${formatRupiahShort(cash.cash_out)}`}
            hint="Buka rekening"
            onClick={() => go(onNavigate, 'fin-cash')} />
          <StatTile label="Saldo di toko marketplace" value={nilaiKartu(stores.total)} testId="home-kpi-stores"
            sub={`${stores.stores.length} toko · belum ditarik ke bank`}
            hint="Buka saldo toko"
            onClick={() => go(onNavigate, 'fin-marketplace-settlement', 'balances')} />
          <StatTile label="Piutang reseller" value={nilaiKartu(ar.total)} testId="home-kpi-ar"
            sub={ar.overdue ? `${formatRupiahShort(ar.overdue)} lewat jatuh tempo` : `${ar.count} faktur belum lunas`}
            hint="Buka piutang"
            subTone={ar.overdue ? 'danger' : undefined}
            onClick={() => go(onNavigate, 'fin-ar-hub', 'aging')} />
          <StatTile label="Hutang pemasok & CMT" value={nilaiKartu(ap.total)} testId="home-kpi-ap"
            sub={ap.overdue ? `${formatRupiahShort(ap.overdue)} lewat jatuh tempo` : `${ap.count} tagihan terbuka`}
            hint="Buka hutang"
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
          <p className="text-base font-semibold text-foreground mb-3">Perlu ditindaklanjuti</p>
          {todo.length === 0 ? (
            <EmptyState icon={CheckCircle2} className="py-8" title="Tidak ada pekerjaan tertunda"
              description="Pekerjaan yang perlu ditindaklanjuti akan muncul di sini." />
          ) : (
            <ul className="space-y-2">
              {todo.map(t => (
                <li key={t.key} className={`flex items-center gap-3 rounded-lg border border-[var(--glass-border)] border-l-4 ${LEVEL_CLS[t.level] || ''} px-3 py-2`} data-testid={`home-todo-${t.key}`}>
                  <span className="text-base font-bold tabular-nums w-10 text-right text-foreground">{t.count}</span>
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
              <p className="text-base font-semibold text-foreground">Laba bulan ini</p>
              <Button variant="link" size="sm" className="h-auto p-0" onClick={() => go(onNavigate, 'fin-pnl')}>Laba Rugi</Button>
            </div>
            <div className="text-xl font-bold tabular-nums text-foreground">{fmt(cur.net_income)}</div>
            <p className="text-xs text-muted-foreground mb-3">
              laba bersih {formatDateID(profit.this_month_from)} – {formatDateID(d.today)}
            </p>
            <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
              <dt className="text-muted-foreground">Pendapatan</dt><dd className="text-right tabular-nums">{fmt(cur.revenue)}</dd>
              <dt className="text-muted-foreground">Laba kotor</dt><dd className="text-right tabular-nums">{fmt(cur.gross_profit)}</dd>
              <dt className="text-muted-foreground">Beban</dt><dd className="text-right tabular-nums">{fmt(cur.expense)}</dd>
              {/* bulan berjalan belum penuh → tanpa persen naik/turun (menyesatkan di awal bulan) */}
              <dt className="text-muted-foreground border-t border-[var(--glass-border)] pt-1 mt-1">Laba bersih bulan lalu (sebulan penuh)</dt><dd className="text-right tabular-nums border-t border-[var(--glass-border)] pt-1 mt-1">{fmt(prev.net_income)}</dd>
            </dl>
          </GlassCard>

          <GlassCard className="p-4" data-testid="home-marketplace">
            <div className="flex items-center justify-between mb-2">
              <p className="text-base font-semibold text-foreground">Dana marketplace bulan ini</p>
              <Button variant="link" size="sm" className="h-auto p-0" onClick={() => go(onNavigate, 'fin-marketplace-settlement', 'settlements')}>Marketplace</Button>
            </div>
            {mp.count === 0 ? (
              <EmptyState icon={Store} className="py-4" title="Belum ada dana dilepas bulan ini"
                description="Laporan dana dilepas dicatat di Marketplace › Dana dilepas." />
            ) : (
              <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
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
        <GlassCard className="p-4 space-y-2" data-testid="home-stores">
          <div className="flex items-center justify-between gap-2">
            <p className="text-base font-semibold text-foreground">Saldo per toko</p>
            <TombolUnduh namaBerkas="saldo-per-toko" namaLembar="Saldo toko" baris={stores.stores} testId="home-stores-unduh"
              kolom={[
                { label: 'Toko', nilai: (s) => s.name },
                { label: 'Akun', nilai: (s) => s.code },
                { label: 'Saldo', nilai: (s) => Number(s.balance) || 0 },
              ]} />
          </div>
          <TabelData kunci={(s) => s.code} baris={stores.stores} testId="home-stores-table"
            onKlikBaris={() => go(onNavigate, 'fin-marketplace-settlement', 'balances')}
            kolom={[
              { kunci: 'name', label: 'Toko', hp: 'judul', isi: (s) => <span className="text-foreground">{s.name}</span> },
              { kunci: 'code', label: 'Akun buku besar', hp: 'keterangan', isi: (s) => <span className="text-muted-foreground">{s.code}</span> },
              { kunci: 'balance', label: 'Saldo', rata: 'kanan',
                isi: (s) => <span className={`tabular-nums whitespace-nowrap ${s.balance < 0 ? DANGER_TEXT : ''}`}>{fmt(s.balance)}</span> },
            ]} />
        </GlassCard>
      )}
    </PageLayout>
  );
}

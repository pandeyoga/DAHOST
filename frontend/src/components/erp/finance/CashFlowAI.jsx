/**
 * AI Cash Flow Prediction — CV. Dewi Aditya ERP
 * Finance portal feature powered by Claude (Anthropic) lewat services.ai backend (2026-11-02).
 *
 * 2026-11-05 (PANDUAN_UI G1/G5/G7/G8): tab Arus Kas › Perkiraan memakai cetakan PageLayout — tombol
 * "Buat perkiraan" di slot `actions` (di hub pindah ke baris tab), angka konteks di `summary`. Dulu
 * pembungkus sendiri (p-6 max-w-4xl mx-auto), kartu shadcn bercampur kartu buatan, tombol "Refresh"
 * kedua, warna palet langsung, label kode umur ("d30", "current"), dan desimal bertitik ("Rp 3.39 M").
 * Angka konteks = StatTile (dengan `sub`) — dulu kartu buatan sendiri.
 */
import { useState, useCallback } from 'react';
import axios from 'axios';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Loader2, Brain, BarChart3 } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';
import MarkdownAman from '@/components/ui/markdown-aman';
import { EmptyState, StatTile } from '../moduleAtoms';
import PageLayout from '../layout/PageLayout';

const API = process.env.REACT_APP_BACKEND_URL;

const num = (v, d) => v.toLocaleString('id-ID', { maximumFractionDigits: d });
const fmtIDR = (n) => {
  const v = Number(n || 0);
  if (v >= 1e9) return `Rp ${num(v / 1e9, 2)} M`;
  if (v >= 1e6) return `Rp ${num(v / 1e6, 1)} jt`;
  if (v >= 1e3) return `Rp ${num(v / 1e3, 0)} rb`;
  return `Rp ${v.toLocaleString('id-ID')}`;
};

// Kode kelompok umur dari server → label & warna token (merah = makin lama lewat jatuh tempo).
const AGING = {
  current: ['Belum jatuh tempo', 'hsl(var(--success))'],
  '1-30': ['1–30 hari', 'hsl(var(--warning))'],
  '31-60': ['31–60 hari', 'hsl(var(--warning))'],
  '61-90': ['61–90 hari', 'hsl(var(--destructive) / 0.75)'],
  '90+': ['Lebih dari 90 hari', 'hsl(var(--destructive))'],
  d30: ['1–30 hari', 'hsl(var(--warning))'],
  d60: ['31–60 hari', 'hsl(var(--warning))'],
  d90: ['61–90 hari', 'hsl(var(--destructive) / 0.75)'],
  d90plus: ['Lebih dari 90 hari', 'hsl(var(--destructive))'],
};

// AR Aging mini chart
function AgingBars({ data, label }) {
  if (!data) return null;
  const keys = Object.keys(data);
  const total = Object.values(data).reduce((s, v) => s + v, 0);
  return (
    <div className="space-y-1.5">
      <p className="text-xs font-semibold text-muted-foreground">{label} — total {fmtIDR(total)}</p>
      {keys.map(k => {
        const v = data[k] || 0;
        if (v === 0) return null;
        const pct = total > 0 ? Math.round(v / total * 100) : 0;
        const [name, color] = AGING[k] || [k, 'hsl(var(--muted-foreground))'];
        return (
          <div key={k} className="flex items-center gap-2 text-xs">
            <div className="w-32 text-muted-foreground shrink-0">{name}</div>
            <div className="flex-1 bg-muted/40 rounded-full h-2.5 overflow-hidden">
              <div className="h-2.5 rounded-full" style={{ width: `${pct}%`, backgroundColor: color }} />
            </div>
            <div className="w-20 text-right font-medium tabular-nums whitespace-nowrap">{fmtIDR(v)}</div>
          </div>
        );
      })}
    </div>
  );
}

// 2026-11-08 (Asisten AI Tahap A): teks AI dirender lewat pengurai markdown aman bersama. Dulu `**…**` diganti
// jadi HTML lalu dipasang dengan dangerouslySetInnerHTML — teks AI berisi <img onerror=…> bisa menjalankan skrip (XSS).
// Butir "• " dari model diubah jadi "- " supaya tampil sebagai daftar.
function AnalysisText({ text }) {
  if (!text) return null;
  return <MarkdownAman text={String(text).replace(/^(\s*)•\s+/gm, '$1- ')} className="text-muted-foreground" testId="cf-ai-analysis-text" />;
}

function UpcomingList({ title, rows, nameKey, fallback }) {
  return (
    <div>
      <p className="text-xs font-semibold text-muted-foreground mb-2">{title}</p>
      {rows?.length > 0 ? rows.map((inv, i) => (
        <div key={i} className="flex justify-between text-xs py-1 border-b border-dashed border-[var(--glass-border)] last:border-0">
          <span className="text-muted-foreground truncate">{inv[nameKey] || fallback}</span>
          <span className="font-medium ml-2 shrink-0 tabular-nums">{fmtIDR(inv.balance)}</span>
        </div>
      )) : <p className="text-xs text-muted-foreground">Tidak ada</p>}
    </div>
  );
}

export default function CashFlowAIModule({ token }) {
  const { toast } = useToast();
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [showContext, setShowContext] = useState(false);
  const headers = { Authorization: `Bearer ${token}` };

  const fetchPrediction = useCallback(async () => {
    setLoading(true);
    setResult(null);
    try {
      const { data } = await axios.get(`${API}/api/finance/ai-cashflow`, { headers });
      setResult(data);
    } catch (e) {
      const msg = e.response?.data?.detail || 'Gagal mengambil prediksi AI.';
      toast({ title: msg, variant: 'destructive' });
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const ctx = result?.context;
  const netFlow = ctx ? ctx.cash_in_60 - ctx.cash_out_60 : null;

  // Angka konteks — 2026-11-04: saldo & arus kas dari buku besar, hutang = pemasok + CMT
  const ctxTiles = ctx ? [
    { l: 'Saldo kas & bank', v: fmtIDR(ctx.cash_balance), sub: 'buku besar hari ini', t: 'cf-ctx-cash' },
    { l: 'Piutang belum dibayar', v: fmtIDR(ctx.total_ar), sub: `${fmtIDR(ctx.overdue_ar)} lewat jatuh tempo`, subTone: ctx.overdue_ar > 0 ? 'danger' : undefined, t: 'cf-ctx-ar' },
    { l: 'Hutang belum dibayar', v: fmtIDR(ctx.total_ap), sub: ctx.ap_unposted ? `+ ${fmtIDR(ctx.ap_unposted)} tagihan CMT belum dijurnal` : 'pemasok + CMT', t: 'cf-ctx-ap' },
    { l: 'Arus kas bersih 60 hari', v: `${netFlow < 0 ? '−' : ''}${fmtIDR(Math.abs(netFlow))}`, sub: `masuk ${fmtIDR(ctx.cash_in_60)} · keluar ${fmtIDR(ctx.cash_out_60)}`, t: 'cf-ctx-net', accent: netFlow < 0 ? 'danger' : 'success' },
  ] : [];

  return (
    <PageLayout
      testId="cashflow-ai-page"
      title="Perkiraan Arus Kas"
      subtitle="Perkiraan 30/60/90 hari dari saldo kas, piutang, dan hutang (pemasok + CMT), dianalisis AI."
      actions={
        <Button data-testid="btn-run-ai-cashflow" onClick={fetchPrediction} disabled={loading}>
          {loading
            ? <><Loader2 className="w-4 h-4 animate-spin" /> Menganalisis…</>
            : <><Brain className="w-4 h-4" /> {result ? 'Hitung ulang' : 'Buat perkiraan'}</>}
        </Button>
      }
      summary={ctx && (<>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {ctxTiles.map((c) => (
            <StatTile key={c.t} testId={c.t} label={c.l} value={c.v} accent={c.accent} sub={c.sub} subTone={c.subTone} />
          ))}
        </div>
        {ctx.active_orders > 0 && <p className="text-xs text-muted-foreground">{ctx.active_orders} order produksi masih berjalan (kebutuhan kas ke depan).</p>}
      </>)}
    >
      {/* Belum dihitung */}
      {!result && !loading && (
        <GlassCard>
          <EmptyState icon={Brain} title="Belum ada perkiraan" testId="cf-ai-empty"
            description="Tekan “Buat perkiraan” — AI membaca saldo kas, umur piutang, umur hutang, dan arus kas 60 hari terakhir." />
        </GlassCard>
      )}

      {/* Sedang dihitung */}
      {loading && (
        <GlassCard className="py-8 text-center" data-testid="cf-ai-loading">
          <div className="flex flex-col items-center gap-3">
            <div className="relative">
              <Brain className="w-12 h-12 text-primary/40" />
              <Loader2 className="w-6 h-6 text-primary animate-spin absolute -bottom-1 -right-1" />
            </div>
            <p className="font-medium">AI sedang menganalisis data keuangan…</p>
            <p className="text-xs text-muted-foreground">Biasanya 10–20 detik</p>
          </div>
        </GlassCard>
      )}

      {/* Hasil analisis */}
      {result?.analysis && (
        <GlassCard className="p-4 space-y-3" data-testid="ai-cashflow-result">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <Brain className="w-4 h-4 text-primary" />
              Analisis AI — {new Date().toLocaleDateString('id-ID', { day: 'numeric', month: 'long', year: 'numeric' })}
            </h3>
            <span className="text-xs text-muted-foreground">dianalisis Claude AI</span>
          </div>
          <div className="prose prose-sm max-w-none">
            <AnalysisText text={result.analysis} />
          </div>
        </GlassCard>
      )}

      {/* Rincian umur piutang & hutang */}
      {ctx && (
        <GlassCard className="p-4 space-y-4" data-testid="cf-aging-detail">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <BarChart3 className="w-4 h-4 text-muted-foreground" />
              Rincian umur piutang & hutang
            </h3>
            <Button variant="link" size="sm" className="h-auto p-0" onClick={() => setShowContext(v => !v)}
              aria-expanded={showContext} data-testid="cf-aging-toggle">
              {showContext ? 'Sembunyikan rincian' : 'Lihat rincian'}
            </Button>
          </div>
          {showContext && (<>
            <AgingBars data={ctx.ar_aging} label="Umur piutang" />
            <div className="border-t border-[var(--glass-border)] pt-4">
              <AgingBars data={ctx.ap_aging} label="Umur hutang (pemasok + CMT)" />
            </div>
            <div className="border-t border-[var(--glass-border)] pt-4 grid grid-cols-2 gap-4 text-sm">
              <UpcomingList title="Piutang jatuh tempo 30 hari ke depan" rows={ctx.upcoming_ar} nameKey="buyer_name" fallback="Pelanggan" />
              <UpcomingList title="Hutang jatuh tempo 30 hari ke depan" rows={ctx.upcoming_ap} nameKey="vendor_name" fallback="Pemasok" />
            </div>
          </>)}
        </GlassCard>
      )}
    </PageLayout>
  );
}

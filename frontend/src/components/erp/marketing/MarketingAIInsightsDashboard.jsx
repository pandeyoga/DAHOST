/**
 * Wawasan AI (tab di AI Marketing, Portal Toko) — ringkasan data, prakiraan penjualan, sentimen, daftar tindakan.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout (judul disembunyikan di hub); empat tampilan dipilih dengan pil (dulu deret
 * tombol buatan sendiri); kartu ringkasan berlogo emoji jadi 4 StatTile berketerangan + 2 tabel kecil; prakiraan harian,
 * tema/isu sentimen, dan daftar tindakan = tabel + unduh (dulu kartu berulang); label Indonesia.
 * Perbaikan angka: kartu "Komplain (30 hari)" dulu menampilkan jumlah lewat batas & kategori yang sebenarnya semua waktu.
 * Panggilan AI hanya terjadi bila tombol ditekan (tidak berubah).
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Brain, TrendingUp, Minus, BarChart3, MessageSquare, Zap, AlertTriangle, CheckCircle2, RefreshCw, Loader2, Sparkles } from 'lucide-react';
import axios from 'axios';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { useToast } from '@/hooks/use-toast';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;

function fmt(n) { return new Intl.NumberFormat('id-ID').format(n || 0); }
function fmtRp(n) { return `Rp ${fmt(n)}`; }

const MODULE_LABEL = {
  complaints: 'Komplain', orders: 'Pesanan', content: 'Konten', discounts: 'Diskon',
  health: 'Kesehatan akun', ads: 'Iklan', launches: 'Peluncuran', general: 'Umum',
};
const KATEGORI = {
  missing_item: 'Produk kurang', wrong_item: 'Produk salah', quality_defect: 'Cacat/rusak', size_mismatch: 'Ukuran salah',
  late_delivery: 'Pengiriman lambat', packaging_damage: 'Kemasan rusak', seller_unresponsive: 'Penjual tidak merespons',
  description_mismatch: 'Tidak sesuai deskripsi', other: 'Lainnya',
};
const YAKIN = { high: 'Tinggi', medium: 'Sedang', low: 'Rendah' };
const DAMPAK = { high: 'Tinggi', medium: 'Sedang', low: 'Rendah' };
const KESEHATAN = { healthy: 'Sehat', warning: 'Perlu perhatian', critical: 'Kritis' };

const URGENCY_CONFIG = {
  urgent: { label: 'Segera', color: 'bg-[hsl(var(--destructive)/0.12)] text-[hsl(var(--danger-text))] ', dot: 'bg-[hsl(var(--destructive-strong))]' },
  high:   { label: 'Tinggi', color: 'bg-[hsl(var(--warning)/0.12)] text-[hsl(var(--warning-text))] ', dot: 'bg-[hsl(var(--warning))]' },
  medium: { label: 'Sedang', color: 'bg-[hsl(var(--warning)/0.12)] text-[hsl(var(--warning-text))] ', dot: 'bg-[hsl(var(--warning))]' },
  low:    { label: 'Rendah', color: 'bg-muted text-muted-foreground dark:text-foreground/70', dot: 'bg-muted' }
};

const SENTIMENT_CONFIG = {
  positive: { label: 'Positif', color: 'text-[hsl(var(--success-text))]', bg: 'bg-[hsl(var(--success)/0.08)] ', icon: CheckCircle2 },
  neutral:  { label: 'Netral',  color: 'text-[hsl(var(--warning-text))]',   bg: 'bg-[hsl(var(--warning)/0.08)] ',   icon: Minus },
  negative: { label: 'Negatif', color: 'text-[hsl(var(--danger-text))]',     bg: 'bg-[hsl(var(--destructive)/0.08)] ',       icon: AlertTriangle }
};

function UrgencyBadge({ urgency }) {
  const cfg = URGENCY_CONFIG[urgency] || URGENCY_CONFIG.medium;
  const tone = urgency === 'urgent' ? 'danger' : urgency === 'low' ? 'muted' : 'warning';
  return <StatusBadge status={urgency} label={cfg.label} tone={tone} />;
}

export default function MarketingAIInsightsDashboard({ token }) {
  const { toast } = useToast();
  const [overview, setOverview] = useState(null);
  const [forecast, setForecast] = useState(null);
  const [sentiment, setSentiment] = useState(null);
  const [recommendations, setRecommendations] = useState(null);
  const [loading, setLoading] = useState({ overview: true, forecast: false, sentiment: false, recommendations: false });
  const [activeTab, setActiveTab] = useState('overview');

  const authH = { Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` };

  const fetchOverview = useCallback(async () => {
    setLoading(l => ({ ...l, overview: true }));
    try {
      const res = await axios.get(`${API}/api/marketing/ai-insights/overview`, { headers: authH });
      if (res.data.success) setOverview(res.data.data);
    } catch (e) {
      toast({ title: 'Gagal memuat ringkasan', variant: 'destructive' });
    } finally {
      setLoading(l => ({ ...l, overview: false }));
    }
  }, [token]); // eslint-disable-line

  const runForecast = async () => {
    setLoading(l => ({ ...l, forecast: true }));
    try {
      const res = await axios.post(`${API}/api/marketing/ai-insights/forecast`, {}, { headers: authH });
      if (res.data.success) setForecast(res.data.data);
    } catch (e) {
      toast({ title: 'Prakiraan gagal', description: e.response?.data?.detail, variant: 'destructive' });
    } finally {
      setLoading(l => ({ ...l, forecast: false }));
    }
  };

  const runSentiment = async () => {
    setLoading(l => ({ ...l, sentiment: true }));
    try {
      const res = await axios.post(`${API}/api/marketing/ai-insights/sentiment`, {}, { headers: authH });
      if (res.data.success) setSentiment(res.data.data);
    } catch (e) {
      toast({ title: 'Analisis sentimen gagal', description: e.response?.data?.detail, variant: 'destructive' });
    } finally {
      setLoading(l => ({ ...l, sentiment: false }));
    }
  };

  const runRecommendations = async () => {
    setLoading(l => ({ ...l, recommendations: true }));
    try {
      const res = await axios.post(`${API}/api/marketing/ai-insights/recommendations`, {}, { headers: authH });
      if (res.data.success) setRecommendations(res.data.data);
    } catch (e) {
      toast({ title: 'Rekomendasi gagal', description: e.response?.data?.detail, variant: 'destructive' });
    } finally {
      setLoading(l => ({ ...l, recommendations: false }));
    }
  };

  useEffect(() => { fetchOverview(); }, [fetchOverview]);

  const TAMPILAN = [
    { key: 'overview', label: 'Ringkasan data', icon: BarChart3 },
    { key: 'forecast', label: 'Prakiraan penjualan', icon: TrendingUp },
    { key: 'sentiment', label: 'Sentimen pelanggan', icon: MessageSquare },
    { key: 'recommendations', label: 'Daftar tindakan', icon: Zap },
  ];
  const o = overview || {};
  const totalUlasan = o.reviews?.total || 0;
  const barisKategori = Object.entries(o.complaints?.categories || {}).map(([k, n]) => ({ id: k, k, n })).sort((a, b) => b.n - a.n);
  const barisBintang = Object.entries(o.reviews?.rating_distribution || {}).map(([r, n]) => ({ id: r, r: Number(r), n })).sort((a, b) => b.r - a.r);
  const tglPanjang = (v) => { try { return new Date(v).toLocaleDateString('id-ID', { weekday: 'short', day: '2-digit', month: 'short' }); } catch { return v; } };
  const pct = (n) => `${Number(n || 0).toFixed(0)}%`;

  const tombolJalankan = {
    forecast: <Button onClick={runForecast} disabled={loading.forecast} data-testid="ai-run-forecast"><Sparkles />{forecast ? 'Prakirakan ulang' : 'Jalankan prakiraan'}</Button>,
    sentiment: <Button onClick={runSentiment} disabled={loading.sentiment} data-testid="ai-run-sentiment"><Sparkles />{sentiment ? 'Analisis ulang' : 'Analisis sekarang'}</Button>,
    recommendations: <Button onClick={runRecommendations} disabled={loading.recommendations} data-testid="ai-run-reco"><Sparkles />{recommendations ? 'Susun ulang' : 'Susun daftar tindakan'}</Button>,
  }[activeTab];
  const sedangAI = (teks) => <p className="py-10 text-center text-sm text-muted-foreground"><Loader2 className="mx-auto mb-2 h-6 w-6 animate-spin text-primary" />{teks}</p>;
  const belum = (Icon, judul, ket) => <EmptyState icon={Icon} title={judul} description={ket} action={tombolJalankan} />;

  const unduh = activeTab === 'overview'
    ? null
    : activeTab === 'forecast' ? { nama: 'prakiraan-penjualan', baris: forecast?.forecast || [], kolom: [
      { label: 'Tanggal', nilai: (d) => tglPanjang(d.date) }, { label: 'Prakiraan pesanan', nilai: (d) => Number(d.predicted_orders) || 0 },
      { label: 'Prakiraan omzet', nilai: (d) => Number(d.predicted_revenue) || 0 }, { label: 'Keyakinan', nilai: (d) => YAKIN[d.confidence] || d.confidence || '' }] }
      : activeTab === 'sentiment' ? { nama: 'sentimen-isu', baris: sentiment?.top_issues || [], kolom: [
        { label: 'Isu', nilai: (x) => x.issue }, { label: 'Jumlah', nilai: (x) => Number(x.count) || 0 },
        { label: 'Urgensi', nilai: (x) => (URGENCY_CONFIG[x.urgency] || URGENCY_CONFIG.medium).label }] }
        : { nama: 'daftar-tindakan-ai', baris: recommendations?.action_items || [], kolom: [
          { label: 'Prioritas', nilai: (x) => x.priority }, { label: 'Tindakan', nilai: (x) => x.title }, { label: 'Uraian', nilai: (x) => x.description },
          { label: 'Urgensi', nilai: (x) => (URGENCY_CONFIG[x.urgency] || URGENCY_CONFIG.medium).label }, { label: 'Bagian', nilai: (x) => MODULE_LABEL[x.module] || 'Umum' },
          { label: 'Perkiraan dampak', nilai: (x) => x.estimated_impact || '' }] };

  return (
    <PageLayout testId="ai-insights-dashboard" title="Wawasan AI"
      subtitle="Prakiraan penjualan, analisis sentimen, dan daftar tindakan dari AI."
      actions={tombolJalankan}
      filters={<FilterChips options={TAMPILAN} value={activeTab} onChange={setActiveTab} hideWhenEmpty={false} testId="ai-insights-view" ariaLabel="Tampilan" />}
      tools={<>
        {unduh && <TombolUnduh namaBerkas={unduh.nama} namaLembar="Data" baris={unduh.baris} kolom={unduh.kolom} testId="ai-insights-unduh" />}
        <Button variant="outline" size="icon" onClick={fetchOverview} disabled={loading.overview} title="Muat ulang data" aria-label="Muat ulang data">
          <RefreshCw className={loading.overview ? 'animate-spin' : ''} />
        </Button>
      </>}>

      {/* ── Ringkasan data ── */}
      {activeTab === 'overview' && (loading.overview && !overview ? sedangAI('Memuat ringkasan…') : overview ? (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="ai-overview-kpi">
            <StatTile label="Pesanan 30 hari" value={fmt(o.orders?.recent_30d)} sub={`Omzet ${fmtRp(o.orders?.revenue_30d)}`}
              hint="Dari rekap penjualan harian; pesanan batal & belum dibayar tidak dihitung." />
            <StatTile label="Komplain 30 hari" value={fmt(o.complaints?.recent_30d)}
              sub={`${fmt(o.complaints?.total)} komplain seluruhnya · ${fmt(o.complaints?.overdue)} lewat batas`}
              subTone={(o.complaints?.overdue || 0) > 0 ? 'danger' : undefined} hint="Angka lewat batas & kategori = semua waktu, bukan 30 hari." />
            <StatTile label="Rata-rata bintang" value={o.reviews?.avg_rating != null ? String(o.reviews.avg_rating.toFixed(2)).replace('.', ',') : '—'}
              suffix="/ 5" sub={`${fmt(totalUlasan)} ulasan`} hint="Semua ulasan yang tercatat." />
            <StatTile label="Kampanye diskon aktif" value={fmt(o.discounts?.active)}
              sub={(o.discounts?.expiring_soon || 0) > 0 ? `${o.discounts.expiring_soon} berakhir ≤ 3 hari` : 'Tidak ada yang segera berakhir'} />
          </div>
          {((o.health?.critical_count || 0) > 0 || (o.health?.warning_count || 0) > 0) && (
            <Notice tone={(o.health?.critical_count || 0) > 0 ? 'danger' : 'warning'} icon={AlertTriangle}
              title={`Kesehatan akun: ${o.health?.critical_count || 0} kritis, ${o.health?.warning_count || 0} perlu perhatian`}>
              Dari {(o.health?.accounts || []).length} akun toko yang dipantau.
            </Notice>
          )}
          <div className="grid gap-4 lg:grid-cols-2">
            <section className="space-y-2">
              <div className="flex items-center gap-2">
                <p className="flex-1 text-base font-semibold">Kategori komplain (semua waktu)</p>
                <TombolUnduh namaBerkas="kategori-komplain" baris={barisKategori} testId="ai-unduh-kategori"
                  kolom={[{ label: 'Kategori', nilai: (x) => KATEGORI[x.k] || 'Lainnya' }, { label: 'Jumlah', nilai: (x) => x.n }]} />
              </div>
              <TabelData baris={barisKategori} testId="ai-kategori-table" kolom={[
                { kunci: 'k', label: 'Kategori', hp: 'judul', isi: (x) => KATEGORI[x.k] || 'Lainnya' },
                { kunci: 'n', label: 'Jumlah', rata: 'kanan', isi: (x) => <span className="tabular-nums">{x.n}</span> },
                { kunci: 'p', label: 'Bagian', rata: 'kanan', isi: (x) => <span className="tabular-nums text-muted-foreground">{pct(o.complaints?.total ? (x.n / o.complaints.total) * 100 : 0)}</span> },
              ]} kosong={<EmptyState title="Belum ada komplain" />} />
            </section>
            <section className="space-y-2">
              <div className="flex items-center gap-2">
                <p className="flex-1 text-base font-semibold">Sebaran bintang ulasan</p>
                <TombolUnduh namaBerkas="sebaran-bintang" baris={barisBintang} testId="ai-unduh-bintang"
                  kolom={[{ label: 'Bintang', nilai: (x) => x.r }, { label: 'Jumlah', nilai: (x) => x.n }]} />
              </div>
              <TabelData baris={barisBintang} testId="ai-bintang-table" kolom={[
                { kunci: 'r', label: 'Bintang', hp: 'judul', isi: (x) => `${x.r} bintang` },
                { kunci: 'bar', label: 'Bagian', hp: false, isi: (x) => <Progress value={totalUlasan ? (x.n / totalUlasan) * 100 : 0} className="h-1.5 w-40" /> },
                { kunci: 'n', label: 'Jumlah', rata: 'kanan', isi: (x) => <span className="tabular-nums">{x.n} · {pct(totalUlasan ? (x.n / totalUlasan) * 100 : 0)}</span> },
              ]} kosong={<EmptyState title="Belum ada ulasan" />} />
            </section>
          </div>
        </>
      ) : (
        <EmptyState icon={Brain} title="Data ringkasan gagal dimuat" action={<Button variant="outline" onClick={fetchOverview}>Coba lagi</Button>} />
      ))}

      {/* ── Prakiraan ── */}
      {activeTab === 'forecast' && (loading.forecast ? sedangAI('AI sedang menganalisis data…')
        : !forecast ? belum(TrendingUp, 'Prakiraan penjualan 7 hari', 'AI membaca tren penjualan lalu memprakirakan 7 hari ke depan.') : (
          <>
            <Notice tone="info" icon={Brain} title={forecast.summary}>
              <span className="flex flex-wrap items-center gap-2">
                <StatusBadge status={forecast.trend} tone={forecast.trend === 'upward' ? 'success' : forecast.trend === 'downward' ? 'danger' : 'warning'}
                  label={`Tren ${forecast.trend === 'upward' ? 'naik' : forecast.trend === 'downward' ? 'turun' : 'stabil'}`} />
                <StatusBadge status="yakin" tone="muted" label={`Keyakinan ${(YAKIN[forecast.confidence] || forecast.confidence || '—').toLowerCase()}`} />
                {(forecast.key_factors || []).map((f, i) => <StatusBadge key={i} status="faktor" tone="primary" label={f} />)}
              </span>
            </Notice>
            <TabelData baris={forecast.forecast || []} kunci={(d) => d.date} testId="ai-forecast-table" kolom={[
              { kunci: 'tgl', label: 'Tanggal', hp: 'judul', isi: (d) => tglPanjang(d.date) },
              { kunci: 'pesanan', label: 'Prakiraan pesanan', rata: 'kanan', isi: (d) => <span className="tabular-nums font-medium">{fmt(d.predicted_orders)}</span> },
              { kunci: 'omzet', label: 'Prakiraan omzet', rata: 'kanan', isi: (d) => <span className="tabular-nums">{fmtRp(d.predicted_revenue)}</span> },
              { kunci: 'yakin', label: 'Keyakinan', isi: (d) => YAKIN[d.confidence] || d.confidence || '—' },
            ]} kosong={<EmptyState title="AI tidak mengembalikan prakiraan harian" />} />
          </>
        ))}

      {/* ── Sentimen ── */}
      {activeTab === 'sentiment' && (loading.sentiment ? sedangAI('AI sedang menganalisis sentimen…')
        : !sentiment ? belum(MessageSquare, 'Analisis sentimen pelanggan', 'AI membaca teks komplain dan ulasan untuk melihat kecenderungan sentimen.') : (() => {
          const sc = SENTIMENT_CONFIG[sentiment.overall_sentiment] || SENTIMENT_CONFIG.neutral;
          return (
            <>
              <Notice tone={sentiment.overall_sentiment === 'positive' ? 'success' : sentiment.overall_sentiment === 'negative' ? 'danger' : 'warning'} icon={sc.icon}
                title={`Sentimen ${sc.label.toLowerCase()} · skor ${Number((sentiment.sentiment_score || 0) * 100).toFixed(0)}%`}>
                {sentiment.summary}
              </Notice>
              <div className="grid gap-4 lg:grid-cols-2">
                <section className="space-y-2">
                  <p className="text-base font-semibold">Tema utama</p>
                  <TabelData baris={sentiment.themes || []} kunci={(t) => t.theme} testId="ai-themes-table" kolom={[
                    { kunci: 'tema', label: 'Tema', hp: 'judul', isi: (t) => t.theme },
                    { kunci: 'sent', label: 'Sentimen', isi: (t) => <StatusBadge status={t.sentiment} label={(SENTIMENT_CONFIG[t.sentiment] || SENTIMENT_CONFIG.neutral).label}
                      tone={t.sentiment === 'positive' ? 'success' : t.sentiment === 'negative' ? 'danger' : 'warning'} /> },
                    { kunci: 'frek', label: 'Frekuensi', rata: 'kanan', isi: (t) => `${t.frequency}×` },
                    { kunci: 'dampak', label: 'Dampak', isi: (t) => DAMPAK[t.impact] || t.impact || '—' },
                  ]} kosong={<EmptyState title="Tidak ada tema" />} />
                </section>
                <section className="space-y-2">
                  <p className="text-base font-semibold">Isu paling sering</p>
                  <TabelData baris={sentiment.top_issues || []} kunci={(x) => x.issue} testId="ai-issues-table" kolom={[
                    { kunci: 'isu', label: 'Isu', hp: 'judul', isi: (x) => x.issue },
                    { kunci: 'n', label: 'Jumlah', rata: 'kanan', isi: (x) => `${x.count}×` },
                    { kunci: 'urg', label: 'Urgensi', isi: (x) => <UrgencyBadge urgency={x.urgency} /> },
                  ]} kosong={<EmptyState title="Tidak ada isu" />} />
                </section>
              </div>
              {(sentiment.recommendations || []).length > 0 && (
                <Notice tone="info" icon={Zap} title="Rekomendasi AI">
                  <ul className="list-disc space-y-0.5 pl-4">{sentiment.recommendations.map((r, i) => <li key={i}>{r}</li>)}</ul>
                </Notice>
              )}
            </>
          );
        })())}

      {/* ── Daftar tindakan ── */}
      {activeTab === 'recommendations' && (loading.recommendations ? sedangAI('AI sedang menyusun rekomendasi…')
        : !recommendations ? belum(Zap, 'Daftar tindakan dari AI', 'AI membaca seluruh data marketing lalu menyusun prioritas tindakan hari ini.') : (
          <>
            <Notice tone={recommendations.overall_health === 'healthy' ? 'success' : recommendations.overall_health === 'critical' ? 'danger' : 'warning'} icon={Brain}
              title={`Kesehatan keseluruhan: ${(KESEHATAN[recommendations.overall_health] || recommendations.overall_health || '—').toLowerCase()}`}>
              {recommendations.summary}
            </Notice>
            <TabelData baris={recommendations.action_items || []} kunci={(x) => `${x.priority}-${x.title}`} testId="ai-actions-table" kolom={[
              { kunci: 'pri', label: 'Prioritas', rata: 'tengah', isi: (x) => <span className="font-semibold tabular-nums">{x.priority}</span> },
              { kunci: 'judul', label: 'Tindakan', hp: 'judul', isi: (x) => (
                <div className="min-w-0 md:max-w-[28rem]"><p className="font-medium">{x.title}</p><p className="text-sm text-muted-foreground">{x.description}</p></div>) },
              { kunci: 'urg', label: 'Urgensi', isi: (x) => <UrgencyBadge urgency={x.urgency} /> },
              { kunci: 'mod', label: 'Bagian', isi: (x) => MODULE_LABEL[x.module] || 'Umum' },
              { kunci: 'dampak', label: 'Perkiraan dampak', isi: (x) => <span className="text-sm">{x.estimated_impact || '—'}</span> },
            ]} kosong={<EmptyState title="AI tidak mengembalikan tindakan" />} />
          </>
        ))}
    </PageLayout>
  );
}

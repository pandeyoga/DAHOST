/**
 * Monitor AI (Portal Manajemen) — biaya & pemakaian AI per fitur, status AI, galat terakhir, anggaran, pengaturan.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout (muat ulang di `tools`), tab rata kiri, kartu angka StatTile (angka
 * dicek terhadap /api/ai/usage/* dan koleksi rahaza_ai_usage_logs), semua tabel bisa diunduh Excel/CSV, nama fitur
 * tampil sebagai label (bukan kode program), status pakai StatusBadge, pengaturan diubah lewat popup form panjang
 * (tab Pengaturan menampilkan ringkasan yang tersimpan). Fitur, API, dan aturan simpan tidak berubah.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Switch } from '@/components/ui/switch';
import { MoneyInput } from '@/components/ui/money-input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { BarisDetail } from '@/components/ui/detail-popup';
import { formatDateTimeID } from '@/lib/format';
import { toast } from 'sonner';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';
// Asisten AI (layar2) — Tahap D: bagian "Asisten AI proaktif" (ingatan, briefing, peringatan, laporan mingguan).
import PengaturanProaktif from './asisten/PengaturanProaktif';
import { bacaPengaturanProaktif, susunPengaturanProaktif } from './asisten/adapterTahapCD';
// Asisten AI per pengguna (10 Nov 2026): tabel saklar + batas per akun di tab Pengaturan.
import AsistenPerPengguna from './asisten/AsistenPerPengguna';
import {
  AlertTriangle, RefreshCw, Loader2, Power, Settings, Sparkles, ClipboardCheck, Users,
} from 'lucide-react';

// Status kesehatan AI → label + nada StatusBadge (dulu kotak berwarna mentah).
const HEALTH = {
  healthy: { label: 'Sehat', tone: 'success' },
  monitor: { label: 'Pantau', tone: 'info' },
  warning: { label: 'Peringatan', tone: 'warning' },
  critical: { label: 'Kritis', tone: 'danger' },
  offline: { label: 'AI mati', tone: 'muted' },
  disabled: { label: 'Dimatikan admin', tone: 'muted' },
  error: { label: 'Banyak galat', tone: 'danger' },
};
const TIER_LABEL = { executive: 'Eksekutif', standard: 'Standar', light: 'Ringan' };
const PERIODE = [1, 7, 14, 30, 90];

function fmtUSD(v) {
  if (v == null) return '$0.0000';
  return `$${Number(v).toFixed(4)}`;
}

function fmtNum(v) {
  if (v == null) return '0';
  return Number(v).toLocaleString('id-ID');
}

const waktuLog = (v) => (v ? formatDateTimeID(new Date(v)) : '—');

// 2026-11-08 (Asisten AI Tahap A): token prompt caching & pencarian web dicatat backend (`cache_read_tokens`,
// `cache_write_tokens`, `web_search_requests`). Ditampilkan hanya bila ringkasan membawanya (data lama tanpa field).
const CACHE_FIELDS = ['cache_read_tokens', 'cache_write_tokens', 'web_search_requests'];
const adaCache = (d) => !!d && CACHE_FIELDS.some((k) => d[k] !== undefined && d[k] !== null);

// 2026-11-08 (Asisten AI Tahap B, Kontrak E): saklar "Tindakan AI aktif" + batas tindakan per pengguna per hari,
// disimpan lewat PUT /api/ai/usage/settings yang sama. Server lama tanpa kunci ini → bawaan (aktif, 30).
const BATAS_TINDAKAN_BAWAAN = 30;
const BATAS_TINDAKAN_MAKS = 1000;
function bacaBatasTindakan(v) {
  const s = String(v ?? '').trim();
  if (!/^\d+$/.test(s)) return null;
  const n = Number(s);
  return n <= BATAS_TINDAKAN_MAKS ? n : null;
}

/** Rincian cache & pencarian web sebagai keterangan kartu Token (dulu 3 kartu tambahan). */
function subCache(d) {
  if (!adaCache(d)) return undefined;
  return `${fmtNum(d.cache_read_tokens)} dibaca dari cache · ${fmtNum(d.cache_write_tokens)} ditulis ke cache · ${fmtNum(d.web_search_requests)} pencarian web`;
}

/** Judul bagian + tombol unduh di kanan (tabel di dalam tab). */
function KepalaBagian({ judul, keterangan, children }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div className="min-w-0">
        <p className="text-base font-semibold text-foreground">{judul}</p>
        {keterangan && <p className="text-sm text-muted-foreground">{keterangan}</p>}
      </div>
      {children && <div className="flex items-center gap-2">{children}</div>}
    </div>
  );
}

export default function AIUsageMonitorModule({ token, user, onNavigate }) {
  const [activeTab, setActiveTab] = useState('today');
  const [today, setToday] = useState(null);
  const [summary, setSummary] = useState(null);
  const [logs, setLogs] = useState([]);
  const [budgets, setBudgets] = useState(null);
  const [settings, setSettings] = useState(null);
  const [form, setForm] = useState(null);
  const [savingSettings, setSavingSettings] = useState(false);
  const [versiSetelan, setVersiSetelan] = useState(0); // naik tiap simpan → daftar Asisten AI per pengguna dimuat ulang
  const [galatProaktif, setGalatProaktif] = useState({}); // Asisten AI (layar2): {kunci jam: kalimat}
  const [period, setPeriod] = useState(7);
  const [loading, setLoading] = useState(false);
  const [logFilter, setLogFilter] = useState('');

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);
  const BASE = process.env.REACT_APP_BACKEND_URL;

  const fetchToday = useCallback(async () => {
    try {
      const r = await fetch(`${BASE}/api/ai/usage/today`, { headers });
      const data = await r.json();
      setToday(data?.data || null);
    } catch (e) { console.error(e); }
  }, [BASE, headers]);

  const fetchSummary = useCallback(async () => {
    try {
      const r = await fetch(`${BASE}/api/ai/usage/summary?days=${period}`, { headers });
      const data = await r.json();
      setSummary(data?.data || null);
    } catch (e) { console.error(e); }
  }, [BASE, headers, period]);

  const fetchLogs = useCallback(async () => {
    try {
      const qs = new URLSearchParams({ limit: '100' });
      if (logFilter) qs.append('feature', logFilter);
      const r = await fetch(`${BASE}/api/ai/usage/logs?${qs}`, { headers });
      const data = await r.json();
      setLogs(data?.data || []);
    } catch (e) { console.error(e); }
  }, [BASE, headers, logFilter]);

  const fetchBudgets = useCallback(async () => {
    try {
      const r = await fetch(`${BASE}/api/ai/usage/budgets`, { headers });
      const data = await r.json();
      setBudgets(data?.data || null);
    } catch (e) { console.error(e); }
  }, [BASE, headers]);

  const fetchSettings = useCallback(async () => {
    try {
      const r = await fetch(`${BASE}/api/ai/usage/settings`, { headers });
      const data = await r.json();
      const d = data?.data;
      if (d) {
        setSettings(d);
        setForm({
          ai_enabled: !!d.ai_enabled,
          daily_budget_usd: d.daily_budget_usd,
          monthly_budget_usd: d.monthly_budget_usd,
          per_feature_daily_usd: d.per_feature_daily_usd,
          default_tier: d.default_tier,
          disabled_features: Array.isArray(d.disabled_features) ? [...d.disabled_features] : [],
          asisten_tindakan_aktif: d.asisten_tindakan_aktif !== false,
          asisten_batas_tindakan_harian: d.asisten_batas_tindakan_harian ?? BATAS_TINDAKAN_BAWAAN,
          // Asisten AI per pengguna (10 Nov 2026): bawaan akun yang belum diatur + batas pertanyaan bawaan (0 = tanpa batas)
          asisten_pengguna_bawaan_aktif: d.asisten_pengguna_bawaan_aktif === true,
          asisten_batas_pertanyaan_harian: d.asisten_batas_pertanyaan_harian ?? 0,
          // Asisten AI (layar2) — Tahap D: 8 kunci asisten_* (server lama → bawaan, lihat adapterTahapCD A6)
          ...bacaPengaturanProaktif(d),
        });
        setGalatProaktif({});
      }
    } catch (e) { console.error(e); }
  }, [BASE, headers]);

  const setField = (k, v) => setForm(f => ({ ...f, [k]: v }));
  const toggleFeature = (key, enabled) => setForm(f => ({
    ...f,
    disabled_features: enabled
      ? f.disabled_features.filter(x => x !== key)
      : Array.from(new Set([...f.disabled_features, key])),
  }));

  const saveSettings = useCallback(async () => {
    if (!form) return false;
    const batasTindakan = bacaBatasTindakan(form.asisten_batas_tindakan_harian);
    if (batasTindakan === null) {
      toast.error(`Batas tindakan per hari harus angka bulat 0–${BATAS_TINDAKAN_MAKS}.`);
      return false;
    }
    const batasPertanyaan = bacaBatasTindakan(form.asisten_batas_pertanyaan_harian);
    if (batasPertanyaan === null) {
      toast.error(`Batas pertanyaan per hari harus angka bulat 0–${BATAS_TINDAKAN_MAKS} (0 = tanpa batas).`);
      return false;
    }
    // Asisten AI (layar2) — Tahap D: jam JJ:MM wajib sah sebelum PUT
    const proaktif = susunPengaturanProaktif(form);
    setGalatProaktif(proaktif.galat);
    if (!proaktif.ok) {
      toast.error(proaktif.pesan);
      return false;
    }
    setSavingSettings(true);
    try {
      const r = await fetch(`${BASE}/api/ai/usage/settings`, {
        method: 'PUT',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ai_enabled: form.ai_enabled,
          daily_budget_usd: Number(form.daily_budget_usd),
          monthly_budget_usd: Number(form.monthly_budget_usd),
          per_feature_daily_usd: Number(form.per_feature_daily_usd),
          default_tier: form.default_tier,
          disabled_features: form.disabled_features,
          asisten_tindakan_aktif: !!form.asisten_tindakan_aktif,
          asisten_batas_tindakan_harian: batasTindakan,
          asisten_pengguna_bawaan_aktif: !!form.asisten_pengguna_bawaan_aktif,
          asisten_batas_pertanyaan_harian: batasPertanyaan,
          ...proaktif.nilai, // Asisten AI (layar2) — Tahap D
        }),
      });
      const data = await r.json();
      if (r.ok && data?.success) {
        toast.success('Pengaturan AI disimpan.');
        setVersiSetelan((v) => v + 1);
        await Promise.all([fetchSettings(), fetchToday()]);
        return true;
      } else {
        toast.error(data?.detail || 'Pengaturan AI gagal disimpan.');
      }
    } catch (e) {
      toast.error('Pengaturan AI gagal disimpan.');
    } finally {
      setSavingSettings(false);
    }
    return false;
  }, [BASE, headers, form, fetchSettings, fetchToday]);

  const refreshAll = useCallback(() => {
    setLoading(true);
    Promise.all([fetchToday(), fetchSummary(), fetchLogs(), fetchBudgets(), fetchSettings()])
      .finally(() => setLoading(false));
  }, [fetchToday, fetchSummary, fetchLogs, fetchBudgets, fetchSettings]);

  useEffect(() => { refreshAll(); }, [refreshAll]);

  // Nama fitur → label manusia (kode program seperti "rahaza-daily-summary" hanya di keterangan arahkan-kursor).
  const grupFitur = useMemo(() => {
    const m = new Map();
    (summary?.by_feature || []).forEach((f) => { if (f.feature && f.group) m.set(f.feature, f.group); });
    logs.forEach((l) => { if (l.feature && l.feature_group) m.set(l.feature, l.feature_group); });
    return m;
  }, [summary, logs]);
  const labelFitur = useCallback((feature, group) => {
    const grup = settings?.feature_groups || [];
    const g = group || grupFitur.get(feature);
    const cocok = grup.find((x) => x.key === feature) || grup.find((x) => x.key === g)
      || grup.find((x) => String(feature || '').startsWith(`${x.key}-`));
    return cocok?.label || feature || '—';
  }, [settings, grupFitur]);

  const bolehAturPengguna = ['owner', 'superadmin'].includes(String(user?.role || '').toLowerCase());
  const [bukaSetelan, setBukaSetelan] = useState(false);
  const simpanSetelan = async () => { if (await saveSettings()) setBukaSetelan(false); };
  const batalSetelan = () => { setBukaSetelan(false); fetchSettings(); };

  const pilihanFitur = Array.from(new Set(logs.map((l) => l.feature).concat(summary?.by_feature?.map((f) => f.feature) || []))).filter(Boolean);
  const kesehatan = HEALTH[today?.health] || { label: today?.health || '—', tone: 'muted' };
  const fiturMati = (settings?.disabled_features || []).map((k) => labelFitur(k));
  const maxHari = Math.max(...(summary?.by_day || []).map((x) => x.cost_usd), 0.0001);

  return (
    <PageLayout
      testId="ai-usage-monitor"
      title="Monitor AI"
      subtitle="Biaya dan pemakaian AI per fitur, status AI, galat terakhir, dan anggaran."
      tools={(
        <Button variant="outline" size="icon" onClick={refreshAll} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="ai-usage-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      )}
    >
      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
        <TabsList className="h-auto w-auto flex-wrap justify-start">
          <TabsTrigger value="today" data-testid="ai-usage-tab-today">Hari ini</TabsTrigger>
          <TabsTrigger value="summary" data-testid="ai-usage-tab-summary">Ringkasan periode</TabsTrigger>
          <TabsTrigger value="logs" data-testid="ai-usage-tab-logs">Catatan panggilan</TabsTrigger>
          <TabsTrigger value="settings" data-testid="ai-usage-tab-settings">Pengaturan</TabsTrigger>
        </TabsList>

        <TabsContent value="today" className="mt-0 space-y-4">
          {!today ? (
            <p className="py-6 text-center text-sm text-muted-foreground"><Loader2 className="mr-2 inline h-4 w-4 animate-spin" />Memuat…</p>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="ai-usage-today-tiles" data-konten-utama="">
                <StatTile label="Panggilan AI" value={fmtNum(today.total_calls)} sub={`Biaya ${fmtUSD(today.total_cost_usd)}`}
                  testId="ai-usage-today-calls" />
                <StatTile label="Berhasil" value={fmtNum(today.successful_calls)} accent="success" sub="Dijawab AI" />
                <StatTile label="Gagal" value={fmtNum(today.failed_calls)} accent={today.failed_calls > 0 ? 'warning' : 'default'}
                  sub="Ditolak atau galat (mis. kunci API kosong)" />
                <StatTile label="Token" value={fmtNum(today.total_tokens)} sub={subCache(today) || 'Token masuk + keluar'}
                  testId="ai-usage-today-cache" />
              </div>

              <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              <GlassCard className="space-y-3 p-4 lg:col-span-2">
                <KepalaBagian judul="Fitur terbanyak hari ini" keterangan="Biaya per fitur dan porsinya dari biaya hari ini.">
                  <TombolUnduh namaBerkas="ai-fitur-hari-ini" namaLembar="Fitur hari ini" baris={today.top_features || []}
                    testId="ai-usage-top-unduh"
                    kolom={[
                      { label: 'Fitur', nilai: (f) => labelFitur(f.feature) },
                      { label: 'Panggilan', nilai: (f) => f.calls },
                      { label: 'Biaya (USD)', nilai: (f) => f.cost_usd },
                    ]} />
                </KepalaBagian>
                <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Fitur</TableHead>
                        <TableHead className="text-right">Panggilan</TableHead>
                        <TableHead className="text-right">Biaya</TableHead>
                        <TableHead className="hidden w-48 sm:table-cell">Porsi biaya</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {!(today.top_features?.length > 0) && (
                        <TableRow className="hover:bg-transparent">
                          <TableCell colSpan={4} className="p-0 [&>div]:py-8">
                            <EmptyState icon={Sparkles} title="Belum ada panggilan AI hari ini"
                              description="Statistik muncul setelah fitur AI (Asisten AI, ringkasan harian, dll.) dipakai." />
                          </TableCell>
                        </TableRow>
                      )}
                      {(today.top_features || []).map((f) => {
                        const pct = today.total_cost_usd > 0 ? (f.cost_usd / today.total_cost_usd * 100) : 0;
                        return (
                          <TableRow key={f.feature}>
                            <TableCell className="font-medium" title={f.feature}>{labelFitur(f.feature)}</TableCell>
                            <TableCell className="text-right tabular-nums">{fmtNum(f.calls)}</TableCell>
                            <TableCell className="text-right tabular-nums">{fmtUSD(f.cost_usd)}</TableCell>
                            <TableCell className="hidden sm:table-cell"><Progress value={pct} className="h-1.5" /></TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                </Table>
              </GlassCard>
              <GlassCard className="space-y-3 p-4" data-testid="ai-usage-status">
                <KepalaBagian judul="Status & anggaran" keterangan={`Hari ini, ${today.date}`}>
                  <StatusBadge status={today.health} label={kesehatan.label} tone={kesehatan.tone} testId="ai-usage-health" />
                </KepalaBagian>
                <div className="space-y-1">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Anggaran harian {fmtUSD(today.daily_budget_usd)}</span>
                    <span className="font-medium tabular-nums">{String(today.budget_used_pct).replace('.', ',')}% terpakai</span>
                  </div>
                  <Progress value={Math.min(today.budget_used_pct, 100)} className="h-2" />
                </div>
                {/* K29 (2026-11-02): batas bulanan dari tab Pengaturan ikut dipantau */}
                {today.monthly_budget_usd != null && (
                  <div className="space-y-1" data-testid="ai-usage-monthly">
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">Anggaran bulanan {fmtUSD(today.month_cost_usd)} dari {fmtUSD(today.monthly_budget_usd)}</span>
                      <span className="font-medium tabular-nums">{String(today.monthly_used_pct).replace('.', ',')}% terpakai</span>
                    </div>
                    <Progress value={Math.min(today.monthly_used_pct || 0, 100)} className="h-2" />
                  </div>
                )}
                {today.ai_available === false && (
                  <Notice tone="info" icon={Power} testId="ai-usage-offline">{today.ai_status?.message || 'Fitur AI belum aktif.'}</Notice>
                )}
                {today.health === 'critical' && (
                  <Notice tone="danger" icon={AlertTriangle}>
                    Anggaran harian/bulanan terlampaui. Fitur AI menolak panggilan baru. Naikkan batas di tab Pengaturan.
                  </Notice>
                )}
                {today.recent_error_count > 0 && (
                  <Notice tone="warning" icon={AlertTriangle} testId="ai-usage-recent-errors"
                    title={`${today.recent_error_count} galat AI dalam 24 jam terakhir`}>
                    <ul className="space-y-0.5">
                      {(today.recent_errors || []).slice(0, 5).map((e) => (
                        <li key={e.code}>{e.count}× — {e.message || 'Galat tanpa keterangan'}</li>
                      ))}
                    </ul>
                  </Notice>
                )}
              </GlassCard>


              </div>
            </>
          )}
        </TabsContent>

        <TabsContent value="summary" className="mt-0 space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <SmartNativeSelect value={String(period)} onChange={(e) => setPeriod(Number(e.target.value))} searchable={false}
              className="h-9 w-40" aria-label="Periode" data-testid="ai-usage-period">
              {PERIODE.map((d) => <option key={d} value={String(d)}>{d} hari terakhir</option>)}
            </SmartNativeSelect>
            {budgets && (
              <span className="text-sm text-muted-foreground">
                Anggaran harian {fmtUSD(budgets.daily_usd)} · bulan ini {budgets.month_cost_usd != null ? `${fmtUSD(budgets.month_cost_usd)} dari ` : ''}{fmtUSD(budgets.monthly_usd)}
              </span>
            )}
          </div>

          {!summary ? (
            <p className="py-6 text-center text-sm text-muted-foreground"><Loader2 className="mr-2 inline h-4 w-4 animate-spin" />Memuat…</p>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-konten-utama="">
                <StatTile label="Total biaya" value={fmtUSD(summary.overall.total_cost_usd)} sub={`${summary.from_date} s.d. ${summary.to_date}`} />
                <StatTile label="Panggilan AI" value={fmtNum(summary.overall.total_calls)}
                  sub={`${fmtNum(summary.overall.successful_calls)} berhasil · ${fmtNum(summary.overall.failed_calls)} gagal`} />
                <StatTile label="Token" value={fmtNum(summary.overall.total_tokens)} sub={subCache(summary.overall) || 'Token masuk + keluar'}
                  testId="ai-usage-summary-cache" />
                <StatTile label="Rata-rata waktu respons" value={`${fmtNum(summary.overall.avg_latency_ms)} md`} sub="Milidetik per panggilan" />
              </div>

              <GlassCard className="space-y-3 p-4">
                <KepalaBagian judul="Biaya per fitur" keterangan={`${summary.period_days} hari terakhir.`}>
                  <TombolUnduh namaBerkas="ai-biaya-per-fitur" namaLembar="Biaya per fitur" baris={summary.by_feature || []}
                    testId="ai-usage-fitur-unduh"
                    kolom={[
                      { label: 'Fitur', nilai: (f) => labelFitur(f.feature, f.group) },
                      { label: 'Panggilan', nilai: (f) => f.calls },
                      { label: 'Berhasil', nilai: (f) => f.successful },
                      { label: 'Gagal', nilai: (f) => f.failed },
                      { label: 'Token', nilai: (f) => f.tokens },
                      { label: 'Rata-rata waktu respons (md)', nilai: (f) => f.avg_latency_ms },
                      { label: 'Biaya (USD)', nilai: (f) => f.cost_usd },
                    ]} />
                </KepalaBagian>
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Fitur</TableHead>
                        <TableHead className="text-right">Panggilan</TableHead>
                        <TableHead className="text-right">Berhasil</TableHead>
                        <TableHead className="text-right">Gagal</TableHead>
                        <TableHead className="hidden text-right md:table-cell">Token</TableHead>
                        <TableHead className="hidden text-right md:table-cell">Waktu respons</TableHead>
                        <TableHead className="text-right">Biaya</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {!(summary.by_feature?.length > 0) && (
                        <TableRow className="hover:bg-transparent">
                          <TableCell colSpan={7} className="p-0 [&>div]:py-8">
                            <EmptyState title="Belum ada panggilan AI pada periode ini" />
                          </TableCell>
                        </TableRow>
                      )}
                      {(summary.by_feature || []).map((f) => (
                        <TableRow key={f.feature}>
                          <TableCell className="font-medium" title={f.feature}>{labelFitur(f.feature, f.group)}</TableCell>
                          <TableCell className="text-right tabular-nums">{fmtNum(f.calls)}</TableCell>
                          <TableCell className="text-right tabular-nums">{fmtNum(f.successful)}</TableCell>
                          <TableCell className={`text-right tabular-nums ${f.failed > 0 ? 'text-[hsl(var(--danger-text))]' : ''}`}>{fmtNum(f.failed)}</TableCell>
                          <TableCell className="hidden text-right tabular-nums text-muted-foreground md:table-cell">{fmtNum(f.tokens)}</TableCell>
                          <TableCell className="hidden text-right tabular-nums text-muted-foreground md:table-cell">{fmtNum(f.avg_latency_ms)} md</TableCell>
                          <TableCell className="text-right font-medium tabular-nums">{fmtUSD(f.cost_usd)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </GlassCard>

              {summary.by_day?.length > 0 && (
                <GlassCard className="space-y-3 p-4">
                  <KepalaBagian judul="Biaya per hari" keterangan="Panjang batang = biaya hari itu dibanding hari termahal di periode ini.">
                    <TombolUnduh namaBerkas="ai-biaya-per-hari" namaLembar="Biaya per hari" baris={summary.by_day}
                      testId="ai-usage-hari-unduh"
                      kolom={[
                        { label: 'Tanggal', nilai: (d) => d.date },
                        { label: 'Panggilan', nilai: (d) => d.calls },
                        { label: 'Token', nilai: (d) => d.tokens },
                        { label: 'Biaya (USD)', nilai: (d) => d.cost_usd },
                      ]} />
                  </KepalaBagian>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-28">Tanggal</TableHead>
                        <TableHead className="hidden sm:table-cell">Biaya relatif</TableHead>
                        <TableHead className="text-right">Panggilan</TableHead>
                        <TableHead className="text-right">Biaya</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {summary.by_day.map((d) => (
                        <TableRow key={d.date}>
                          <TableCell className="whitespace-nowrap">{d.date}</TableCell>
                          <TableCell className="hidden sm:table-cell"><Progress value={(d.cost_usd / maxHari) * 100} className="h-1.5" /></TableCell>
                          <TableCell className="text-right tabular-nums">{fmtNum(d.calls)}</TableCell>
                          <TableCell className="text-right tabular-nums">{fmtUSD(d.cost_usd)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </GlassCard>
              )}
            </>
          )}
        </TabsContent>

        <TabsContent value="logs" className="mt-0 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <SmartNativeSelect value={logFilter} onChange={(e) => setLogFilter(e.target.value)} className="h-9 w-56"
              aria-label="Saring fitur" data-testid="ai-usage-log-filter">
              <option value="">Semua fitur</option>
              {pilihanFitur.map((f) => <option key={f} value={f}>{labelFitur(f)}</option>)}
            </SmartNativeSelect>
            <span className="text-sm text-muted-foreground">{fmtNum(logs.length)} catatan terakhir (maks. 100)</span>
            <div className="ml-auto flex items-center gap-2">
              <TombolUnduh namaBerkas="ai-catatan-panggilan" namaLembar="Catatan panggilan" baris={logs} testId="ai-usage-log-unduh"
                kolom={[
                  { label: 'Waktu', nilai: (l) => waktuLog(l.created_at) },
                  { label: 'Fitur', nilai: (l) => labelFitur(l.feature, l.feature_group) },
                  { label: 'Model', nilai: (l) => l.model_name || '' },
                  { label: 'Token', nilai: (l) => l.tokens_total },
                  { label: 'Waktu respons (md)', nilai: (l) => l.latency_ms },
                  { label: 'Biaya (USD)', nilai: (l) => l.cost_usd },
                  { label: 'Status', nilai: (l) => (l.success ? 'Berhasil' : 'Gagal') },
                  { label: 'Galat', nilai: (l) => l.error || '' },
                ]} />
              <Button variant="outline" size="icon" onClick={fetchLogs} title="Muat ulang catatan" aria-label="Muat ulang catatan">
                <RefreshCw />
              </Button>
            </div>
          </div>

          {logs.length === 0 ? (
            <EmptyState title="Belum ada catatan panggilan" description="Catatan muncul setelah fitur AI dipakai." />
          ) : (
            <GlassCard className="overflow-x-auto p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Waktu</TableHead>
                    <TableHead>Fitur</TableHead>
                    <TableHead className="hidden md:table-cell">Model</TableHead>
                    <TableHead className="hidden text-right sm:table-cell">Token</TableHead>
                    <TableHead className="hidden text-right md:table-cell">Waktu respons</TableHead>
                    <TableHead className="text-right">Biaya</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {logs.map((l) => (
                    <TableRow key={l.id}>
                      <TableCell className="whitespace-nowrap text-muted-foreground">{waktuLog(l.created_at)}</TableCell>
                      <TableCell className="font-medium" title={l.feature}>{labelFitur(l.feature, l.feature_group)}</TableCell>
                      <TableCell className="hidden text-muted-foreground md:table-cell">{l.model_name}</TableCell>
                      <TableCell className="hidden text-right tabular-nums sm:table-cell">{fmtNum(l.tokens_total)}</TableCell>
                      <TableCell className="hidden text-right tabular-nums md:table-cell">{fmtNum(l.latency_ms)} md</TableCell>
                      <TableCell className="text-right tabular-nums">{fmtUSD(l.cost_usd)}</TableCell>
                      <TableCell title={l.error || ''}>
                        <StatusBadge status={l.success ? 'berhasil' : 'gagal'} label={l.success ? 'Berhasil' : 'Gagal'} tone={l.success ? 'success' : 'danger'} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </GlassCard>
          )}
        </TabsContent>

        <TabsContent value="settings" className="mt-0 space-y-4">
          {!form ? (
            <p className="py-6 text-center text-sm text-muted-foreground"><Loader2 className="mr-2 inline h-4 w-4 animate-spin" />Memuat…</p>
          ) : (
            <GlassCard className="space-y-3 p-4" data-testid="ai-set-ringkas">
              <KepalaBagian judul="Pengaturan yang berlaku" keterangan="Ubah lewat tombol di kanan; perubahan berlaku setelah disimpan.">
                <Button onClick={() => setBukaSetelan(true)} data-testid="ai-set-buka"><Settings />Ubah pengaturan</Button>
              </KepalaBagian>
              <dl className="divide-y divide-[var(--glass-border)]">
                <BarisDetail label="Fitur AI">
                  <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <StatusBadge status={settings?.ai_enabled ? 'aktif' : 'mati'} label={settings?.ai_enabled ? 'Dinyalakan' : 'Dimatikan'}
                      tone={settings?.ai_enabled ? 'success' : 'muted'} />
                    {settings?.ai_status?.message && settings?.ai_status?.available === false && (
                      <span className="text-muted-foreground">{settings.ai_status.message}</span>
                    )}
                  </span>
                </BarisDetail>
                <BarisDetail label="Tindakan Asisten AI">
                  {settings?.asisten_tindakan_aktif !== false ? 'Aktif' : 'Dimatikan'} · paling banyak {fmtNum(settings?.asisten_batas_tindakan_harian ?? BATAS_TINDAKAN_BAWAAN)} per pengguna per hari
                </BarisDetail>
                <BarisDetail label="Asisten AI untuk akun yang belum diatur">
                  {settings?.asisten_pengguna_bawaan_aktif === true ? 'Aktif' : 'Mati'}
                  {' · '}pertanyaan {Number(settings?.asisten_batas_pertanyaan_harian) > 0 ? `paling banyak ${fmtNum(settings.asisten_batas_pertanyaan_harian)} per pengguna per hari` : 'tanpa batas'}
                  {' · '}owner dan superadmin selalu aktif
                </BarisDetail>
                <BarisDetail label="Anggaran">
                  Harian {fmtUSD(settings?.daily_budget_usd)} · bulanan {fmtUSD(settings?.monthly_budget_usd)} · per fitur per hari {fmtUSD(settings?.per_feature_daily_usd)}
                </BarisDetail>
                <BarisDetail label="Tingkat model bawaan">{TIER_LABEL[settings?.default_tier] || settings?.default_tier || '—'}</BarisDetail>
                <BarisDetail label="Fitur dimatikan">{fiturMati.length ? fiturMati.join(', ') : 'Tidak ada — semua fitur AI aktif'}</BarisDetail>
                <BarisDetail label="Asisten AI proaktif">
                  Ingatan {settings?.asisten_ingatan_aktif !== false ? 'aktif' : 'mati'}
                  {' · '}briefing pagi {settings?.asisten_briefing_aktif !== false ? `pukul ${settings?.asisten_briefing_jam || '—'}` : 'mati'}
                  {' · '}peringatan harian {settings?.asisten_peringatan_aktif !== false ? `pukul ${settings?.asisten_peringatan_jam || '—'}` : 'mati'}
                  {' · '}laporan mingguan {settings?.asisten_laporan_mingguan_aktif !== false ? `pukul ${settings?.asisten_laporan_mingguan_jam || '—'}` : 'mati'}
                </BarisDetail>
              </dl>
            </GlassCard>
          )}
          {/* Asisten AI per pengguna (10 Nov 2026): dimuat ulang setelah pengaturan bawaan disimpan */}
          <AsistenPerPengguna key={versiSetelan} token={token} />
        </TabsContent>
      </Tabs>

      {form && (
        <FormPopup open={bukaSetelan} onClose={batalSetelan} ukuran="panjang" judul="Ubah pengaturan AI"
          keterangan="Saklar, anggaran, tingkat model, fitur, dan Asisten AI proaktif. Bila anggaran terlampaui, panggilan AI ditolak otomatis."
          onSimpan={simpanSetelan} menyimpan={savingSettings} labelSimpan="Simpan pengaturan" testId="ai-set-form">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm font-medium text-foreground">Saklar utama AI</p>
              <p className="text-xs text-muted-foreground">Matikan untuk menghentikan SEMUA fitur AI sekaligus.</p>
            </div>
            <Switch checked={form.ai_enabled} onCheckedChange={(v) => setField('ai_enabled', v)} aria-label="Saklar utama AI" data-testid="ai-set-master" />
          </div>

          {/* Asisten AI Tahap B — tindakan lewat kartu konfirmasi */}
          <div className="space-y-3 border-t border-[var(--glass-border)] pt-4" data-testid="ai-set-tindakan">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-start gap-2">
                <ClipboardCheck className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                <div>
                  <p className="text-sm font-medium text-foreground">Tindakan Asisten AI aktif</p>
                  <p className="text-xs text-muted-foreground">Bila dimatikan, Asisten AI hanya menjawab; usulan perubahan yang menunggu tidak bisa disetujui.</p>
                </div>
              </div>
              <Switch checked={!!form.asisten_tindakan_aktif} onCheckedChange={(v) => setField('asisten_tindakan_aktif', v)}
                aria-label="Tindakan Asisten AI aktif" data-testid="ai-set-tindakan-aktif" />
            </div>
            <Isian label="Batas tindakan per pengguna per hari" htmlFor="ai-set-batas-tindakan" className="max-w-xs"
              petunjuk={`Perubahan yang dijalankan Asisten AI untuk satu pengguna dalam sehari. Bawaan ${BATAS_TINDAKAN_BAWAAN}.`}>
              <MoneyInput id="ai-set-batas-tindakan" decimals={0} value={form.asisten_batas_tindakan_harian}
                onChange={(e) => setField('asisten_batas_tindakan_harian', e.target.value)} data-testid="ai-set-batas-tindakan" />
            </Isian>
          </div>

          {/* Asisten AI per pengguna (10 Nov 2026): bawaan akun yang belum diatur — hanya owner/superadmin yang mengubah */}
          <div className="space-y-3 border-t border-[var(--glass-border)] pt-4" data-testid="ai-set-per-pengguna">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-start gap-2">
                <Users className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                <div>
                  <p className="text-sm font-medium text-foreground">Asisten AI aktif untuk akun yang belum diatur</p>
                  <p className="text-xs text-muted-foreground">
                    Berlaku untuk akun yang tidak diatur sendiri di daftar Asisten AI per pengguna. Owner dan superadmin selalu aktif.
                    {!bolehAturPengguna && ' Hanya owner atau superadmin yang bisa mengubah bagian ini.'}
                  </p>
                </div>
              </div>
              <Switch checked={!!form.asisten_pengguna_bawaan_aktif} disabled={!bolehAturPengguna}
                onCheckedChange={(v) => setField('asisten_pengguna_bawaan_aktif', v)}
                aria-label="Asisten AI aktif untuk akun yang belum diatur" data-testid="ai-set-bawaan-pengguna" />
            </div>
            <Isian label="Batas pertanyaan per pengguna per hari" htmlFor="ai-set-batas-pertanyaan" className="max-w-xs"
              petunjuk="Pertanyaan yang boleh dikirim satu akun dalam sehari. 0 = tanpa batas.">
              <MoneyInput id="ai-set-batas-pertanyaan" decimals={0} value={form.asisten_batas_pertanyaan_harian} disabled={!bolehAturPengguna}
                onChange={(e) => setField('asisten_batas_pertanyaan_harian', e.target.value)} data-testid="ai-set-batas-pertanyaan" />
            </Isian>
          </div>

          {/* Budgets */}
          <div className="space-y-3 border-t border-[var(--glass-border)] pt-4">
            <p className="text-sm font-medium text-foreground">Anggaran (USD)</p>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <Isian label="Harian">
                <MoneyInput decimals={2} value={form.daily_budget_usd}
                  onChange={(e) => setField('daily_budget_usd', e.target.value)} data-testid="ai-set-daily" />
              </Isian>
              <Isian label="Bulanan">
                <MoneyInput decimals={2} value={form.monthly_budget_usd}
                  onChange={(e) => setField('monthly_budget_usd', e.target.value)} data-testid="ai-set-monthly" />
              </Isian>
              <Isian label="Per fitur per hari">
                <MoneyInput decimals={2} value={form.per_feature_daily_usd}
                  onChange={(e) => setField('per_feature_daily_usd', e.target.value)} data-testid="ai-set-perfeature" />
              </Isian>
            </div>
            {settings?.env_defaults && (
              <p className="text-xs text-muted-foreground">
                Bawaan server: harian ${settings.env_defaults.daily_budget_usd} · bulanan ${settings.env_defaults.monthly_budget_usd}.
              </p>
            )}
          </div>

          {/* Default tier */}
          <div className="border-t border-[var(--glass-border)] pt-4">
            <Isian label="Tingkat model bawaan" htmlFor="ai-set-tier"
              petunjuk="Standar = umum, Ringan = klasifikasi/asisten (usaha rendah). Eksekutif dipakai KHUSUS narasi Laporan Eksekutif dan tidak bisa dijadikan bawaan.">
              <SmartNativeSelect id="ai-set-tier" value={form.default_tier} onChange={(e) => setField('default_tier', e.target.value)}
                searchable={false} className="h-9 w-full sm:w-80" data-testid="ai-set-tier">
                {(settings?.tiers || []).map((t) => (
                  <option key={t} value={t}>{TIER_LABEL[t] || t} — {String(settings?.tier_models?.[t] || '').replace(/^anthropic\//, '')}</option>
                ))}
              </SmartNativeSelect>
            </Isian>
          </div>

          {/* Feature toggles */}
          <div className="space-y-2 border-t border-[var(--glass-border)] pt-4">
            <p className="text-sm font-medium text-foreground">Aktif / nonaktif per fitur AI</p>
            <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
              {(settings?.feature_groups || []).map((g) => {
                const enabled = !form.disabled_features.includes(g.key);
                return (
                  <label key={g.key} className="flex items-center justify-between gap-3 border-b border-[var(--glass-border)] py-2 text-sm text-foreground">
                    <span className="min-w-0">{g.label}</span>
                    <Switch checked={enabled} onCheckedChange={(v) => toggleFeature(g.key, v)} aria-label={g.label} data-testid={`ai-set-feat-${g.key}`} />
                  </label>
                );
              })}
            </div>
          </div>

          {/* Asisten AI (layar2) — Tahap D: ingatan + briefing/peringatan/laporan mingguan */}
          <PengaturanProaktif form={form} setField={setField} galat={galatProaktif} tersimpan={settings}
            user={user} onNavigate={onNavigate} />
        </FormPopup>
      )}
    </PageLayout>
  );
}

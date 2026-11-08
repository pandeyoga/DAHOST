/**
 * AI lanjutan (tab di AI Marketing, Portal Toko) — harga dinamis, prediksi pelanggan berhenti, uji A/B.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout (judul disembunyikan di hub); tiga tampilan dipilih dengan pil (dulu deret
 * tombol buatan sendiri); kartu warna jadi kalimat ringkas/Notice; usulan harga, riwayat, pelanggan, eksperimen =
 * tabel + unduh (eksperimen dulu kartu besar berisi grid varian → kini rincian popup); form = FormPopup; label Indonesia
 * tanpa emoji. Panggilan API & isi yang dikirim tidak berubah; panggilan AI hanya saat tombol ditekan.
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Brain, DollarSign, Settings, Power, PowerOff, Zap, RefreshCw, Loader2, CheckCircle2, XCircle, AlertTriangle, Clock,
  FlaskConical, Users, Sparkles, Plus, Pencil, Info, Shield, History, Play, Pause, Trophy, ArrowUp, ArrowDown, Target,
} from 'lucide-react';
import axios from 'axios';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { useToast } from '@/hooks/use-toast';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';
import { CatalogSkuMultiSelect } from './pickers/MarketingPickers';

const API = process.env.REACT_APP_BACKEND_URL;
function fmt(n) { return new Intl.NumberFormat('id-ID').format(n || 0); }
function fmtRp(n) { return `Rp ${fmt(n)}`; }
function fmtPct(n) { return `${(n || 0).toFixed(1)}%`; }

const RISK_CONFIG = {
  critical: { label: 'Kritis',  color: 'bg-[hsl(var(--destructive)/0.12)] text-[hsl(var(--danger-text))] ',       dot: 'bg-[hsl(var(--destructive-strong))]',    icon: AlertTriangle },
  high:     { label: 'Tinggi',  color: 'bg-[hsl(var(--warning)/0.12)] text-[hsl(var(--warning-text))] ', dot: 'bg-[hsl(var(--warning))]', icon: AlertTriangle },
  medium:   { label: 'Sedang',  color: 'bg-[hsl(var(--warning)/0.12)] text-[hsl(var(--warning-text))] ',   dot: 'bg-[hsl(var(--warning))]',  icon: Clock },
  low:      { label: 'Rendah',  color: 'bg-[hsl(var(--success)/0.12)] text-[hsl(var(--success-text))] ', dot: 'bg-[hsl(var(--success-strong))]', icon: CheckCircle2 }
};

const DIR_CONFIG = {
  increase: { icon: ArrowUp,   color: 'text-[hsl(var(--success-text))]', bg: 'bg-[hsl(var(--success)/0.08)] ' },
  decrease: { icon: ArrowDown, color: 'text-[hsl(var(--danger-text))]',     bg: 'bg-[hsl(var(--destructive)/0.08)] ' },
  hold:     { icon: Target,    color: 'text-muted-foreground',   bg: 'bg-muted ' }
};

const STATUS_CONFIG = {
  pending:  { label: 'Menunggu', color: 'bg-[hsl(var(--warning)/0.12)] text-[hsl(var(--warning-text))] ' },
  approved: { label: 'Disetujui', color: 'bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))] ' },
  applied:  { label: 'Diterapkan', color: 'bg-[hsl(var(--success)/0.12)] text-[hsl(var(--success-text))] ' },
  rejected: { label: 'Ditolak', color: 'bg-[hsl(var(--destructive)/0.12)] text-[hsl(var(--danger-text))] ' }
};

const AB_STATUS = {
  draft:     { label: 'Draf',    color: 'bg-muted text-muted-foreground dark:text-foreground/70' },
  running:   { label: 'Berjalan',  color: 'bg-[hsl(var(--success)/0.12)] text-[hsl(var(--success-text))] ' },
  paused:    { label: 'Dijeda',   color: 'bg-[hsl(var(--warning)/0.12)] text-[hsl(var(--warning-text))] ' },
  concluded: { label: 'Selesai',  color: 'bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))] ' }
};


// ─────────────────────────────────────────────────────────────────
// TAB 1: DYNAMIC PRICING
// ─────────────────────────────────────────────────────────────────
function DynamicPricingTab({ authH }) {
  const { toast } = useToast();
  const [settings, setSettings] = useState(null);
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [savingSettings, setSavingSettings] = useState(false);
  const [running, setRunning] = useState(false);
  const [suggestions, setSuggestions] = useState([]);
  const [sugMeta, setSugMeta] = useState(null);
  const [sugFilter, setSugFilter] = useState('pending');
  const [sugLoading, setSugLoading] = useState(false);
  const [events, setEvents] = useState([]);
  const [showEvents, setShowEvents] = useState(false);
  const [actionLoading, setActionLoading] = useState({});
  const [showSettings, setShowSettings] = useState(false);

  // Local edit of settings
  const [draft, setDraft] = useState(null);

  const fetchSettings = useCallback(async () => {
    setSettingsLoading(true);
    try {
      const res = await axios.get(`${API}/api/marketing/advanced-ai/pricing/settings`, { headers: authH });
      if (res.data.success) { setSettings(res.data.data); setDraft(res.data.data); }
    } catch (e) { toast({ title: 'Gagal memuat pengaturan', variant: 'destructive' }); }
    finally { setSettingsLoading(false); }
  }, [authH]); // eslint-disable-line

  const saveSettings = async () => {
    setSavingSettings(true);
    try {
      const res = await axios.put(`${API}/api/marketing/advanced-ai/pricing/settings`, draft, { headers: authH });
      if (res.data.success) { setSettings(res.data.data); toast({ title: 'Pengaturan disimpan.' }); setShowSettings(false); }
    } catch (e) { toast({ title: 'Gagal menyimpan', variant: 'destructive' }); }
    finally { setSavingSettings(false); }
  };

  const toggleEnabled = async (val) => {
    const updated = { ...settings, enabled: val };
    try {
      const res = await axios.put(`${API}/api/marketing/advanced-ai/pricing/settings`, { enabled: val }, { headers: authH });
      if (res.data.success) { setSettings(updated); setDraft(updated); }
      toast({ title: val ? 'Harga dinamis aktif.' : 'Harga dinamis nonaktif.' });
    } catch (e) { toast({ title: 'Gagal mengubah status', variant: 'destructive' }); }
  };

  const runSuggestions = async () => {
    setRunning(true);
    try {
      const res = await axios.post(`${API}/api/marketing/advanced-ai/pricing/run`, {}, { headers: authH });
      if (res.data.success) {
        toast({ title: `${res.data.metadata?.count || 0} usulan harga dibuat.` });
        fetchSuggestions();
      }
    } catch (e) {
      toast({ title: 'Gagal membuat usulan', description: e.response?.data?.detail || e.message, variant: 'destructive' });
    } finally { setRunning(false); }
  };

  const fetchSuggestions = useCallback(async () => {
    setSugLoading(true);
    try {
      const params = sugFilter !== 'all' ? { status: sugFilter } : {};
      const res = await axios.get(`${API}/api/marketing/advanced-ai/pricing/suggestions`, { params, headers: authH });
      if (res.data.success) { setSuggestions(res.data.data?.suggestions || []); setSugMeta(res.data.metadata); }
    } catch (e) {}
    finally { setSugLoading(false); }
  }, [authH, sugFilter]); // eslint-disable-line

  const doAction = async (id, action, reason = null) => {
    setActionLoading(l => ({ ...l, [id + action]: true }));
    try {
      let url = `${API}/api/marketing/advanced-ai/pricing/suggestions/${id}/${action}`;
      if (reason) url += `?reason=${encodeURIComponent(reason)}`;
      const res = await axios.post(url, {}, { headers: authH });
      if (res.data.success) {
        toast({ title: `Usulan ${action === 'approve' ? 'disetujui' : action === 'reject' ? 'ditolak' : 'diterapkan'}.` });
        fetchSuggestions();
      }
    } catch (e) {
      // K28 (2026-11-02): Apply menulis harga katalog sungguhan; 409 = produk belum
      // terpetakan ke SKU/item katalog, guardrail/margin terlampaui (status tidak diubah).
      const notConnected = action === 'apply' && e.response?.status === 409;
      toast({
        title: notConnected ? 'Harga katalog tidak diubah' : 'Gagal',
        description: e.response?.data?.detail,
        variant: notConnected ? undefined : 'destructive',
      });
    }
    finally { setActionLoading(l => ({ ...l, [id + action]: false })); }
  };

  const fetchEvents = async () => {
    try {
      const res = await axios.get(`${API}/api/marketing/advanced-ai/pricing/events`, { headers: authH });
      if (res.data.success) setEvents(res.data.data?.events || []);
    } catch (e) {}
  };

  useEffect(() => { fetchSettings(); }, [fetchSettings]);
  useEffect(() => { fetchSuggestions(); }, [fetchSuggestions]);

  if (settingsLoading) return <p className="py-6 text-center text-sm text-muted-foreground">Memuat pengaturan harga dinamis…</p>;

  const isEnabled = settings?.enabled;
  const YAKIN = { high: ['Tinggi', 'success'], medium: ['Sedang', 'warning'], low: ['Rendah', 'muted'] };
  const EVENT = { apply: ['Diterapkan', 'success'], approve: ['Disetujui', 'info'], reject: ['Ditolak', 'danger'], run: ['Usulan dibuat', 'muted'] };
  const perubahan = (s) => `${s.direction === 'increase' ? '+' : s.direction === 'decrease' ? '−' : ''}${Math.abs(s.change_pct || 0).toFixed(1).replace('.', ',')}%`;
  const waktuEv = (v) => { try { return new Date(v).toLocaleString('id-ID', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }); } catch { return v || '—'; } };
  const kolom = [
    { kunci: 'produk', label: 'Produk', hp: 'judul', isi: (s) => <p className="truncate font-medium md:max-w-[14rem]" title={s.product}>{s.product}</p> },
    { kunci: 'kini', label: 'Harga kini', rata: 'kanan', isi: (s) => <span className="tabular-nums">{fmtRp(s.current_price_rp)}</span> },
    { kunci: 'saran', label: 'Harga saran', rata: 'kanan', isi: (s) => (
      <span className="tabular-nums font-semibold md:whitespace-nowrap">{fmtRp(s.suggested_price_rp)}
        <span className={`block text-xs ${(DIR_CONFIG[s.direction] || DIR_CONFIG.hold).color}`}>{perubahan(s)}</span></span>) },
    { kunci: 'yakin', label: 'Keyakinan', isi: (s) => <StatusBadge status={s.confidence} label={(YAKIN[s.confidence] || [s.confidence || '—'])[0]} tone={(YAKIN[s.confidence] || [])[1]} /> },
    { kunci: 'alasan', label: 'Alasan utama', isi: (s) => <p className="truncate text-sm text-muted-foreground md:max-w-[16rem]" title={s.primary_reason}>{s.primary_reason}</p> },
    { kunci: 'status', label: 'Status', isi: (s) => <StatusBadge status={s.status} label={(STATUS_CONFIG[s.status] || STATUS_CONFIG.pending).label} tone={{ pending: 'warning', approved: 'info', applied: 'success', rejected: 'danger' }[s.status]} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (s) => (
      <div className="flex justify-end gap-1">
        {s.status === 'pending' && <>
          <Button size="sm" variant="success" onClick={() => doAction(s.id, 'approve')} disabled={actionLoading[s.id + 'approve']}>
            {actionLoading[s.id + 'approve'] ? <Loader2 className="animate-spin" /> : <CheckCircle2 />}Setujui
          </Button>
          {/* 2026-11-02: tombol Terapkan TIDAK ada di baris menunggu — hanya untuk usulan yang sudah disetujui. */}
          <Button size="sm" variant="destructive" onClick={() => doAction(s.id, 'reject')} disabled={actionLoading[s.id + 'reject']}>
            {actionLoading[s.id + 'reject'] ? <Loader2 className="animate-spin" /> : <XCircle />}Tolak
          </Button>
        </>}
        {s.status === 'approved' && (
          <Button size="sm" onClick={() => doAction(s.id, 'apply')} disabled={actionLoading[s.id + 'apply']}>
            {actionLoading[s.id + 'apply'] ? <Loader2 className="animate-spin" /> : null}Terapkan
          </Button>
        )}
      </div>) },
  ];
  const kolomEvent = [
    { kunci: 'w', label: 'Waktu', hp: 'keterangan', isi: (ev) => <span className="tabular-nums">{waktuEv(ev.created_at)}</span> },
    { kunci: 'e', label: 'Kejadian', isi: (ev) => <StatusBadge status={ev.event_type} label={(EVENT[ev.event_type] || ['Lainnya'])[0]} tone={(EVENT[ev.event_type] || [])[1]} /> },
    { kunci: 'p', label: 'Produk', hp: 'judul', isi: (ev) => ev.product || '—' },
    { kunci: 'd', label: 'Rincian', isi: (ev) => <span className="text-muted-foreground">{ev.event_type === 'apply' && ev.old_price_rp
      ? `${fmtRp(ev.old_price_rp)} → ${fmtRp(ev.new_price_rp)}` : ev.reason ? `Alasan: ${ev.reason}` : `${ev.suggestions_count || ''} usulan`}</span> },
    { kunci: 'a', label: 'Oleh', isi: (ev) => ev.actor || '—' },
  ];

  return (
    <div className="space-y-4">
      <Notice tone={isEnabled ? 'success' : 'info'} icon={isEnabled ? Power : PowerOff}
        title={<span className="flex flex-wrap items-center gap-2">Harga dinamis
          <Switch checked={isEnabled || false} onCheckedChange={toggleEnabled} data-testid="pricing-toggle" aria-label="Aktifkan harga dinamis" />
          <StatusBadge status={isEnabled ? 'aktif' : 'nonaktif'} label={isEnabled ? 'Aktif' : 'Nonaktif'} tone={isEnabled ? 'success' : 'muted'} /></span>}
        action={<div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={() => setShowSettings(true)} data-testid="pricing-settings-btn"><Settings />Konfigurasi</Button>
          <Button size="sm" onClick={runSuggestions} disabled={!isEnabled || running} data-testid="run-pricing-btn">
            {running ? <Loader2 className="animate-spin" /> : <Zap />}{running ? 'Menganalisis…' : 'Buat usulan harga'}
          </Button>
        </div>}>
        Mode: wajib disetujui manual · margin minimum {settings?.min_margin_pct_global}% · perubahan maks. naik {settings?.max_price_increase_pct_per_run}% / turun {settings?.max_price_decrease_pct_per_run}% per putaran · pembulatan Rp {fmt(settings?.rounding_rule)}.
      </Notice>

      <section className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <p className="flex-1 text-base font-semibold">Usulan harga{sugMeta?.total ? ` · ${sugMeta.total}` : ''}</p>
          <SmartNativeSelect value={sugFilter} onChange={(e) => setSugFilter(e.target.value)} className="w-40" searchable={false} data-testid="pricing-filter">
            <option value="all">Semua status</option>
            <option value="pending">Menunggu</option>
            <option value="approved">Disetujui</option>
            <option value="applied">Diterapkan</option>
            <option value="rejected">Ditolak</option>
          </SmartNativeSelect>
          <TombolUnduh namaBerkas="usulan-harga" namaLembar="Usulan" baris={suggestions} testId="pricing-unduh"
            kolom={[
              { label: 'Produk', nilai: (s) => s.product }, { label: 'Harga kini', nilai: (s) => Number(s.current_price_rp) || 0 },
              { label: 'Harga saran', nilai: (s) => Number(s.suggested_price_rp) || 0 }, { label: 'Perubahan (%)', nilai: (s) => Number(s.change_pct) || 0 },
              { label: 'Keyakinan', nilai: (s) => (YAKIN[s.confidence] || [s.confidence || ''])[0] }, { label: 'Alasan utama', nilai: (s) => s.primary_reason || '' },
              { label: 'Status', nilai: (s) => (STATUS_CONFIG[s.status] || STATUS_CONFIG.pending).label },
            ]} />
          <Button variant="outline" size="icon" onClick={fetchSuggestions} title="Muat ulang usulan" aria-label="Muat ulang usulan">
            <RefreshCw className={sugLoading ? 'animate-spin' : ''} />
          </Button>
        </div>
        {sugLoading && suggestions.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">Memuat usulan…</p>
        ) : (
          <TabelData kolom={kolom} baris={suggestions} testId="pricing-table"
            kosong={<EmptyState icon={DollarSign} title="Belum ada usulan harga"
              description={isEnabled ? 'Klik "Buat usulan harga" untuk memulai.' : 'Aktifkan harga dinamis untuk membuat usulan.'} />} />
        )}
      </section>

      <section className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => { setShowEvents(v => !v); if (!showEvents) fetchEvents(); }}>
            <History />{showEvents ? 'Sembunyikan' : 'Lihat'} riwayat perubahan
          </Button>
          {showEvents && events.length > 0 && (
            <TombolUnduh namaBerkas="riwayat-harga-dinamis" namaLembar="Riwayat" baris={events} testId="pricing-events-unduh"
              kolom={[
                { label: 'Waktu', nilai: (ev) => waktuEv(ev.created_at) }, { label: 'Kejadian', nilai: (ev) => (EVENT[ev.event_type] || ['Lainnya'])[0] },
                { label: 'Produk', nilai: (ev) => ev.product || '' }, { label: 'Harga lama', nilai: (ev) => ev.old_price_rp ?? '' },
                { label: 'Harga baru', nilai: (ev) => ev.new_price_rp ?? '' }, { label: 'Alasan', nilai: (ev) => ev.reason || '' }, { label: 'Oleh', nilai: (ev) => ev.actor || '' },
              ]} />
          )}
        </div>
        {showEvents && (
          <TabelData kolom={kolomEvent} baris={events} testId="pricing-events-table" kosong={<EmptyState title="Belum ada riwayat" />} />
        )}
      </section>

      <FormPopup open={showSettings} onClose={() => setShowSettings(false)} ukuran="panjang" onSimpan={saveSettings} menyimpan={savingSettings}
        judul="Konfigurasi harga dinamis" keterangan="Atur batas pengaman dan mode. Perubahan berlaku langsung." testId="pricing-settings-form">
        {draft && (
          <>
            <Isian label="Mode operasional" htmlFor="pr-mode">
              {/* K28 (2026-11-02): harga dinamis WAJIB disetujui — opsi terapkan otomatis dicabut. */}
              <SmartNativeSelect id="pr-mode" value={draft.mode || 'suggest_only'} searchable={false} onChange={(e) => setDraft(d => ({ ...d, mode: e.target.value }))}>
                <option value="suggest_only">Hanya usulan (wajib disetujui manual)</option>
              </SmartNativeSelect>
            </Isian>
            <p className="flex items-center gap-1 border-t border-[var(--glass-border)] pt-3 text-sm font-medium"><Shield className="h-4 w-4" />Batas pengaman</p>
            <div className="grid gap-4 sm:grid-cols-2">
              <Isian label="Margin minimum (%)" petunjuk="Margin yang tidak boleh dilanggar." htmlFor="pr-margin">
                <Input id="pr-margin" type="number" step="1" value={draft.min_margin_pct_global || ''}
                  onChange={e => setDraft(d => ({ ...d, min_margin_pct_global: Number(e.target.value) }))} />
              </Isian>
              <Isian label="Pembulatan harga" htmlFor="pr-round">
                <SmartNativeSelect id="pr-round" value={String(draft.rounding_rule || 500)} searchable={false}
                  onChange={(e) => setDraft(d => ({ ...d, rounding_rule: Number(e.target.value) }))}>
                  {[100, 500, 1000, 5000].map((v) => <option key={v} value={String(v)}>{`Rp ${fmt(v)}`}</option>)}
                </SmartNativeSelect>
              </Isian>
              <Isian label="Kenaikan maks. per putaran (%)" htmlFor="pr-up">
                <Input id="pr-up" type="number" step="1" value={draft.max_price_increase_pct_per_run || ''}
                  onChange={e => setDraft(d => ({ ...d, max_price_increase_pct_per_run: Number(e.target.value) }))} />
              </Isian>
              <Isian label="Penurunan maks. per putaran (%)" htmlFor="pr-down">
                <Input id="pr-down" type="number" step="1" value={draft.max_price_decrease_pct_per_run || ''}
                  onChange={e => setDraft(d => ({ ...d, max_price_decrease_pct_per_run: Number(e.target.value) }))} />
              </Isian>
              <Isian label="Jeda antar putaran (menit)" htmlFor="pr-cool">
                <Input id="pr-cool" type="number" step="5" value={draft.run_cooldown_minutes || ''}
                  onChange={e => setDraft(d => ({ ...d, run_cooldown_minutes: Number(e.target.value) }))} />
              </Isian>
            </div>
            <Isian label="SKU yang dikecualikan (dari katalog)">
              <CatalogSkuMultiSelect value={draft.exclude_skus || []} testId="ai-exclude-skus" onChange={v => setDraft(d => ({ ...d, exclude_skus: v }))} />
            </Isian>
            <Notice tone="warning" icon={Info}>Perubahan harga belum dikirim otomatis ke marketplace; saat ini hanya usulan internal.</Notice>
          </>
        )}
      </FormPopup>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// TAB 2: CHURN PREDICTION
// ─────────────────────────────────────────────────────────────────
function ChurnPredictionTab({ authH }) {
  const { toast } = useToast();
  const [result, setResult] = useState(null);
  const [savedScores, setSavedScores] = useState([]);
  const [scoresLoading, setScoresLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [riskFilter, setRiskFilter] = useState('all');
  const [expandedCustomer, setExpandedCustomer] = useState(null);

  const fetchSavedScores = useCallback(async () => {
    setScoresLoading(true);
    try {
      const params = riskFilter !== 'all' ? { risk: riskFilter } : {};
      const res = await axios.get(`${API}/api/marketing/advanced-ai/churn/scores`, { params, headers: authH });
      if (res.data.success) setSavedScores(res.data.data?.customers || []);
    } catch (e) {}
    finally { setScoresLoading(false); }
  }, [authH, riskFilter]); // eslint-disable-line

  const runAnalysis = async () => {
    setAnalyzing(true);
    try {
      const res = await axios.post(`${API}/api/marketing/advanced-ai/churn/run`, {}, { headers: authH });
      if (res.data.success) {
        setResult(res.data.data);
        // 2026-11-02: tanpa data order → hasil kosong yang jujur (dulu 15 pelanggan fiktif).
        toast({ title: res.data.data.summary?.no_data
          ? (res.data.metadata?.message || 'Belum ada data order pelanggan untuk dianalisis.')
          : `Analisis selesai: ${res.data.data.customers?.length || 0} pelanggan dianalisis.` });
        fetchSavedScores();
      }
    } catch (e) {
      toast({ title: 'Analisis gagal', description: e.response?.data?.detail, variant: 'destructive' });
    } finally { setAnalyzing(false); }
  };

  useEffect(() => { fetchSavedScores(); }, [fetchSavedScores]);

  const customers = result?.customers || savedScores;
  const summary = result?.summary;
  const filtered = riskFilter === 'all' ? customers : customers.filter(c => c.churn_risk === riskFilter);
  const RISK_TONE = { critical: 'danger', high: 'warning', medium: 'warning', low: 'success' };
  const rfm = (c) => `${c.r_score ?? '—'}-${c.f_score ?? '—'}-${c.m_score ?? '—'}`;
  const opsiRisiko = [
    { key: 'all', label: 'Semua', count: summary ? Object.values(summary.segments || {}).reduce((a, b) => a + b, 0) : undefined },
    ...['critical', 'high', 'medium', 'low'].map((k) => ({ key: k, label: RISK_CONFIG[k].label, count: summary ? (summary.segments || {})[k] || 0 : undefined })),
  ];
  const kolom = [
    { kunci: 'c', label: 'Pelanggan', hp: 'judul', isi: (c) => <span className="font-medium">{c.customer}</span> },
    { kunci: 'r', label: 'Risiko berhenti', isi: (c) => <StatusBadge status={c.churn_risk} label={(RISK_CONFIG[c.churn_risk] || RISK_CONFIG.low).label} tone={RISK_TONE[c.churn_risk]} /> },
    { kunci: 'rec', label: 'Terakhir belanja', rata: 'kanan', isi: (c) => <span className="tabular-nums">{c.recency_days} hari lalu</span> },
    { kunci: 'o', label: 'Pesanan', rata: 'kanan', isi: (c) => <span className="tabular-nums">{c.order_count}<span className="block text-xs text-muted-foreground">{String(c.freq_per_month ?? '—').replace('.', ',')}× / bulan</span></span> },
    { kunci: 'b', label: 'Total belanja', rata: 'kanan', isi: (c) => <span className="tabular-nums md:whitespace-nowrap">{fmtRp(c.total_spent_rp)}</span> },
    { kunci: 'rfm', label: 'Skor RFM', rata: 'tengah', isi: (c) => <span className="tabular-nums" title="Skor kebaruan-frekuensi-nilai (1–5)">{rfm(c)}</span> },
    { kunci: 'ai', label: 'Saran AI', isi: (c) => <p className="truncate text-sm text-muted-foreground md:max-w-[18rem]" title={c.ai_action}>{c.ai_action || '—'}</p> },
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <FilterChips options={opsiRisiko} value={riskFilter} onChange={setRiskFilter} hideWhenEmpty={false} testId="churn-filter" ariaLabel="Risiko" />
        <p className="flex-1 text-sm text-muted-foreground">Pelanggan berisiko berhenti belanja dari skor RFM + penjelasan AI.</p>
        <TombolUnduh namaBerkas="risiko-pelanggan" namaLembar="Pelanggan" baris={filtered} testId="churn-unduh"
          kolom={[
            { label: 'Pelanggan', nilai: (c) => c.customer }, { label: 'Risiko', nilai: (c) => (RISK_CONFIG[c.churn_risk] || RISK_CONFIG.low).label },
            { label: 'Terakhir belanja (hari)', nilai: (c) => Number(c.recency_days) || 0 }, { label: 'Pesanan', nilai: (c) => Number(c.order_count) || 0 },
            { label: 'Total belanja', nilai: (c) => Number(c.total_spent_rp) || 0 }, { label: 'Skor RFM', nilai: rfm },
            { label: 'Frekuensi per bulan', nilai: (c) => Number(c.freq_per_month) || 0 }, { label: 'Saran AI', nilai: (c) => c.ai_action || '' },
            { label: 'Templat pesan', nilai: (c) => c.ai_template || '' },
          ]} />
        <Button onClick={runAnalysis} disabled={analyzing} data-testid="run-churn-btn">
          {analyzing ? <Loader2 className="animate-spin" /> : <Sparkles />}{analyzing ? 'Menganalisis…' : result ? 'Analisis ulang' : 'Jalankan analisis'}
        </Button>
      </div>
      {summary?.general_strategy && (
        <Notice tone="info" icon={Brain} title={summary.general_strategy}>
          {summary.quick_wins?.length > 0 && <ul className="list-disc space-y-0.5 pl-4">{summary.quick_wins.map((w, i) => <li key={i}>{w}</li>)}</ul>}
        </Notice>
      )}
      {(scoresLoading || analyzing) && customers.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat…</p>
      ) : (
        <TabelData kolom={kolom} baris={filtered} kunci={(c) => c.customer} onKlikBaris={(c) => setExpandedCustomer(c.customer)} testId="churn-table"
          kosong={<EmptyState icon={Users} title={customers.length === 0 ? 'Belum ada hasil analisis' : 'Tidak ada pelanggan di penyaring ini'}
            description={customers.length === 0 ? 'Klik "Jalankan analisis" untuk memulai.' : 'Pilih tingkat risiko lain.'} />} />
      )}
      {(() => {
        const c = customers.find((x) => x.customer === expandedCustomer);
        if (!c) return null;
        return (
          <DetailPopup open onClose={() => setExpandedCustomer(null)} judul={c.customer} testId="churn-detail"
            status={<StatusBadge status={c.churn_risk} label={(RISK_CONFIG[c.churn_risk] || RISK_CONFIG.low).label} tone={RISK_TONE[c.churn_risk]} />}>
            <dl className="divide-y divide-[var(--glass-border)]">
              <BarisDetail label="Terakhir belanja">{c.recency_days} hari lalu</BarisDetail>
              <BarisDetail label="Pesanan">{c.order_count} ({String(c.freq_per_month ?? '—').replace('.', ',')}× per bulan)</BarisDetail>
              <BarisDetail label="Total belanja">{fmtRp(c.total_spent_rp)}</BarisDetail>
              <BarisDetail label="Skor RFM">{rfm(c)}</BarisDetail>
              <BarisDetail label="Saran AI">{c.ai_action || '—'}</BarisDetail>
              {c.ai_template && <BarisDetail label={`Templat pesan (${c.ai_channel || 'WA'})`}><span className="whitespace-pre-wrap italic text-muted-foreground">{c.ai_template}</span></BarisDetail>}
            </dl>
          </DetailPopup>
        );
      })()}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// TAB 3: A/B TESTING
// ─────────────────────────────────────────────────────────────────
function ABTestingTab({ authH }) {
  const { toast } = useToast();
  const [experiments, setExperiments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [showRecord, setShowRecord] = useState(null);   // experiment
  const [concluding, setConcluding] = useState({});
  const [statusLoading, setStatusLoading] = useState({});
  const [filterStatus, setFilterStatus] = useState('all');

  // Create form
  const [form, setForm] = useState({
    name: '', hypothesis: '', test_type: 'content_hook', platform: 'tiktok',
    goal_metric: 'conversion', duration_days: 7,
    variantA: '', variantB: '', variantC: ''
  });
  const [creating, setCreating] = useState(false);

  // Record results form
  const [recordData, setRecordData] = useState({});
  const [recording, setRecording] = useState(false);

  const fetchExperiments = useCallback(async () => {
    setLoading(true);
    try {
      const params = filterStatus !== 'all' ? { status: filterStatus } : {};
      const res = await axios.get(`${API}/api/marketing/advanced-ai/ab-tests`, { params, headers: authH });
      if (res.data.success) setExperiments(res.data.data?.experiments || []);
    } catch (e) {}
    finally { setLoading(false); }
  }, [authH, filterStatus]); // eslint-disable-line

  useEffect(() => { fetchExperiments(); }, [fetchExperiments]);

  const createExperiment = async () => {
    if (!form.name || !form.hypothesis) {
      toast({ title: 'Nama dan hipotesis wajib diisi', variant: 'destructive' }); return;
    }
    setCreating(true);
    const variants = [
      form.variantA && { label: 'Variant A', content: form.variantA },
      form.variantB && { label: 'Variant B', content: form.variantB },
      form.variantC && { label: 'Variant C', content: form.variantC }
    ].filter(Boolean);
    try {
      const res = await axios.post(`${API}/api/marketing/advanced-ai/ab-tests`, {
        name: form.name, hypothesis: form.hypothesis, test_type: form.test_type,
        platform: form.platform, goal_metric: form.goal_metric,
        duration_days: form.duration_days, variants
      }, { headers: authH });
      if (res.data.success) {
        toast({ title: 'Eksperimen dibuat.' });
        setShowCreate(false);
        setForm({ name: '', hypothesis: '', test_type: 'content_hook', platform: 'tiktok', goal_metric: 'conversion', duration_days: 7, variantA: '', variantB: '', variantC: '' });
        fetchExperiments();
      }
    } catch (e) { toast({ title: 'Gagal membuat eksperimen', description: e.response?.data?.detail, variant: 'destructive' }); }
    finally { setCreating(false); }
  };

  const changeStatus = async (exp, newStatus) => {
    setStatusLoading(l => ({ ...l, [exp.id]: true }));
    try {
      await axios.patch(`${API}/api/marketing/advanced-ai/ab-tests/${exp.id}/status?new_status=${newStatus}`, {}, { headers: authH });
      toast({ title: `Status diubah: ${(AB_STATUS[newStatus] || {}).label || newStatus}` });
      fetchExperiments();
    } catch (e) { toast({ title: 'Gagal', description: e.response?.data?.detail, variant: 'destructive' }); }
    finally { setStatusLoading(l => ({ ...l, [exp.id]: false })); }
  };

  const concludeExp = async (exp) => {
    setConcluding(l => ({ ...l, [exp.id]: true }));
    try {
      const res = await axios.post(`${API}/api/marketing/advanced-ai/ab-tests/${exp.id}/conclude`, {}, { headers: authH });
      if (res.data.success) {
        toast({ title: `Pemenang: ${res.data.data?.winner_label}` });
        fetchExperiments();
      }
    } catch (e) { toast({ title: 'Gagal menentukan pemenang', description: e.response?.data?.detail, variant: 'destructive' }); }
    finally { setConcluding(l => ({ ...l, [exp.id]: false })); }
  };

  const openRecord = (exp) => {
    const init = {};
    exp.variants.forEach(v => { init[v.id] = { views: v.views || 0, clicks: v.clicks || 0, orders: v.orders || 0, revenue_rp: v.revenue_rp || 0, engagement: v.engagement || 0 }; });
    setRecordData(init);
    setShowRecord(exp);
  };

  const saveRecord = async () => {
    if (!showRecord) return;
    setRecording(true);
    try {
      for (const [variantId, data] of Object.entries(recordData)) {
        await axios.post(`${API}/api/marketing/advanced-ai/ab-tests/${showRecord.id}/record`, { variant_id: variantId, ...data }, { headers: authH });
      }
      toast({ title: 'Hasil disimpan.' });
      setShowRecord(null);
      fetchExperiments();
    } catch (e) { toast({ title: 'Gagal menyimpan hasil', variant: 'destructive' }); }
    finally { setRecording(false); }
  };

  const TIPE_UJI = { content_hook: 'Hook konten', product_title: 'Judul produk', pricing: 'Harga', discount: 'Diskon' };
  const PLAT = { tiktok: 'TikTok', shopee: 'Shopee', tokopedia: 'Tokopedia', instagram: 'Instagram' };
  const TUJUAN = { conversion: 'Tingkat konversi', ctr: 'Rasio klik (CTR)', engagement: 'Interaksi' };
  const AB_TONE = { draft: 'muted', running: 'success', paused: 'warning', concluded: 'info' };
  const opsiStatus = [{ key: 'all', label: 'Semua' }, ...['draft', 'running', 'paused', 'concluded'].map((k) => ({ key: k, label: AB_STATUS[k].label }))];
  const [rincian, setRincian] = useState(null);
  const aksiEksperimen = (exp) => {
    const hasData = exp.variants?.some(v => v.views > 0);
    return (
      <div className="flex flex-wrap justify-end gap-1">
        {exp.status === 'draft' && (
          <Button size="sm" variant="outline" onClick={() => changeStatus(exp, 'running')} disabled={statusLoading[exp.id]}>
            {statusLoading[exp.id] ? <Loader2 className="animate-spin" /> : <Play />}Mulai
          </Button>
        )}
        {exp.status === 'running' && <>
          <Button size="sm" variant="outline" onClick={() => changeStatus(exp, 'paused')} disabled={statusLoading[exp.id]}><Pause />Jeda</Button>
          <Button size="sm" variant="outline" onClick={() => openRecord(exp)}><Pencil />Isi hasil</Button>
          {hasData && (
            <Button size="sm" onClick={() => concludeExp(exp)} disabled={concluding[exp.id]}>
              {concluding[exp.id] ? <Loader2 className="animate-spin" /> : <Trophy />}Tentukan pemenang
            </Button>
          )}
        </>}
        {exp.status === 'paused' && <>
          <Button size="sm" variant="outline" onClick={() => changeStatus(exp, 'running')} disabled={statusLoading[exp.id]}><Play />Lanjutkan</Button>
          <Button size="sm" variant="outline" onClick={() => openRecord(exp)}><Pencil />Isi hasil</Button>
        </>}
      </div>
    );
  };
  const kolom = [
    { kunci: 'nama', label: 'Eksperimen', hp: 'judul', isi: (e) => (
      <div className="min-w-0 md:max-w-[22rem]"><p className="font-medium">{e.name}</p><p className="line-clamp-2 text-xs text-muted-foreground">{e.hypothesis}</p></div>) },
    { kunci: 'tipe', label: 'Jenis · platform', isi: (e) => <span className="text-sm">{TIPE_UJI[e.test_type] || 'Lainnya'} · {PLAT[e.platform] || e.platform}</span> },
    { kunci: 'varian', label: 'Varian', rata: 'kanan', isi: (e) => <span className="tabular-nums">{(e.variants || []).length}</span> },
    { kunci: 'menang', label: 'Pemenang', isi: (e) => (e.status === 'concluded' && e.winner_label
      ? <span className="flex items-center gap-1"><Trophy className="h-3.5 w-3.5 text-primary" />{e.winner_label}</span> : <span className="text-muted-foreground">—</span>) },
    { kunci: 'status', label: 'Status', isi: (e) => <StatusBadge status={e.status} label={(AB_STATUS[e.status] || AB_STATUS.draft).label} tone={AB_TONE[e.status]} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: aksiEksperimen },
  ];
  const kolomVarian = (exp) => [
    { kunci: 'l', label: 'Varian', hp: 'judul', isi: (v) => (
      <span className="font-medium">{v.label}{exp.status === 'concluded' && exp.winner_variant_id === v.id ? ' (pemenang)' : ''}
        {v.content && <span className="block text-xs font-normal text-muted-foreground">{v.content}</span>}</span>) },
    { kunci: 'v', label: 'Tayangan', rata: 'kanan', isi: (v) => fmt(v.views) },
    { kunci: 'c', label: 'Klik', rata: 'kanan', isi: (v) => fmt(v.clicks) },
    { kunci: 'o', label: 'Pesanan', rata: 'kanan', isi: (v) => fmt(v.orders) },
    { kunci: 'ctr', label: 'CTR', rata: 'kanan', isi: (v) => fmtPct(v.ctr).replace('.', ',') },
    { kunci: 'cv', label: 'Konversi', rata: 'kanan', isi: (v) => fmtPct(v.conversion_rate).replace('.', ',') },
    { kunci: 'r', label: 'Omzet', rata: 'kanan', isi: (v) => <span className="tabular-nums md:whitespace-nowrap">{fmtRp(v.revenue_rp)}</span> },
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <FilterChips options={opsiStatus} value={filterStatus} onChange={setFilterStatus} hideWhenEmpty={false} testId="ab-filter" ariaLabel="Status eksperimen" />
        <p className="flex-1 text-sm text-muted-foreground">Uji konten & materi iklan untuk menemukan kombinasi terbaik.</p>
        <TombolUnduh namaBerkas="eksperimen-ab" namaLembar="Eksperimen" baris={experiments} testId="ab-unduh"
          kolom={[
            { label: 'Eksperimen', nilai: (e) => e.name }, { label: 'Hipotesis', nilai: (e) => e.hypothesis || '' },
            { label: 'Jenis', nilai: (e) => TIPE_UJI[e.test_type] || '' }, { label: 'Platform', nilai: (e) => PLAT[e.platform] || e.platform || '' },
            { label: 'Tujuan', nilai: (e) => TUJUAN[e.goal_metric] || '' }, { label: 'Durasi (hari)', nilai: (e) => e.duration_days || '' },
            { label: 'Jumlah varian', nilai: (e) => (e.variants || []).length }, { label: 'Pemenang', nilai: (e) => e.winner_label || '' },
            { label: 'Status', nilai: (e) => (AB_STATUS[e.status] || AB_STATUS.draft).label },
          ]} />
        <Button onClick={() => setShowCreate(true)} data-testid="create-ab-btn"><Plus />Buat eksperimen</Button>
      </div>

      {loading && experiments.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat eksperimen…</p>
      ) : (
        <TabelData kolom={kolom} baris={experiments} onKlikBaris={setRincian} testId="ab-table"
          kosong={<EmptyState icon={FlaskConical} title="Belum ada eksperimen" description="Buat eksperimen pertama untuk mulai mengoptimalkan konten."
            action={<Button onClick={() => setShowCreate(true)}><Plus />Buat sekarang</Button>} />} />
      )}

      {rincian && (() => {
        const exp = experiments.find((x) => x.id === rincian.id) || rincian;
        return (
          <DetailPopup open onClose={() => setRincian(null)} judul={exp.name} testId="ab-detail"
            status={<StatusBadge status={exp.status} label={(AB_STATUS[exp.status] || AB_STATUS.draft).label} tone={AB_TONE[exp.status]} />}
            keterangan={`${TIPE_UJI[exp.test_type] || 'Lainnya'} · ${PLAT[exp.platform] || exp.platform} · tujuan ${(TUJUAN[exp.goal_metric] || '').toLowerCase()}`}
            aksi={aksiEksperimen(exp)}>
            <p className="text-sm">{exp.hypothesis}</p>
            {exp.status === 'concluded' && exp.winner_label && (
              <Notice tone="success" icon={Trophy} title={`Pemenang: ${exp.winner_label}${exp.improvement_pct ? ` (${exp.improvement_pct}% lebih baik)` : ''}`}>
                {exp.winner_reason}{exp.recommendation ? ` Rekomendasi: ${exp.recommendation}` : ''}
              </Notice>
            )}
            <div className="flex justify-end">
              <TombolUnduh namaBerkas="varian-eksperimen-ab" namaLembar="Varian" baris={exp.variants || []} testId="ab-variants-unduh"
                kolom={[{ label: 'Varian', nilai: (v) => v.label || '' }, { label: 'Isi', nilai: (v) => v.content || '' },
                  { label: 'Tayangan', nilai: (v) => Number(v.views) || 0 }, { label: 'Klik', nilai: (v) => Number(v.clicks) || 0 },
                  { label: 'Pesanan', nilai: (v) => Number(v.orders) || 0 }, { label: 'CTR (%)', nilai: (v) => Number(v.ctr) || 0 },
                  { label: 'Konversi (%)', nilai: (v) => Number(v.conversion_rate) || 0 }, { label: 'Omzet', nilai: (v) => Number(v.revenue_rp) || 0 }]} />
            </div>
            <TabelData kolom={kolomVarian(exp)} baris={exp.variants || []} testId="ab-variants-table" />
          </DetailPopup>
        );
      })()}

      <FormPopup open={showCreate} onClose={() => setShowCreate(false)} ukuran="panjang" onSimpan={createExperiment} menyimpan={creating}
        judul="Buat eksperimen A/B" keterangan="Tentukan hipotesis, varian, dan ukuran keberhasilan." labelSimpan="Buat eksperimen" testId="ab-form">
        <Isian label="Nama eksperimen" wajib htmlFor="ab-name">
          <Input id="ab-name" placeholder="cth: Hook Ramadan vs umum" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
        </Isian>
        <Isian label="Hipotesis" wajib htmlFor="ab-hyp">
          <Textarea id="ab-hyp" rows={2} placeholder="cth: Hook yang menyebut hari raya menaikkan CTR 20% dibanding hook umum"
            value={form.hypothesis} onChange={e => setForm(f => ({ ...f, hypothesis: e.target.value }))} />
        </Isian>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Jenis uji" htmlFor="ab-type">
            <SmartNativeSelect id="ab-type" value={form.test_type} searchable={false} onChange={(e) => setForm(f => ({ ...f, test_type: e.target.value }))}>
              {Object.entries(TIPE_UJI).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Platform" htmlFor="ab-plat">
            <SmartNativeSelect id="ab-plat" value={form.platform} searchable={false} onChange={(e) => setForm(f => ({ ...f, platform: e.target.value }))}>
              {Object.entries(PLAT).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Ukuran keberhasilan" htmlFor="ab-goal">
            <SmartNativeSelect id="ab-goal" value={form.goal_metric} searchable={false} onChange={(e) => setForm(f => ({ ...f, goal_metric: e.target.value }))}>
              {Object.entries(TUJUAN).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Durasi (hari)" htmlFor="ab-dur">
            <Input id="ab-dur" type="number" min={1} max={30} value={form.duration_days} onChange={e => setForm(f => ({ ...f, duration_days: Number(e.target.value) }))} />
          </Isian>
        </div>
        {['A', 'B', 'C'].map((l, i) => (
          <Isian key={l} label={`Varian ${l}`} wajib={i < 2} petunjuk={i >= 2 ? 'Opsional.' : undefined} htmlFor={`ab-var-${l}`}>
            <Textarea id={`ab-var-${l}`} rows={2} placeholder={`Isi konten / hook / judul varian ${l}`}
              value={form[`variant${l}`]} onChange={e => setForm(f => ({ ...f, [`variant${l}`]: e.target.value }))} />
          </Isian>
        ))}
      </FormPopup>

      <FormPopup open={!!showRecord} onClose={() => setShowRecord(null)} ukuran="panjang" onSimpan={saveRecord} menyimpan={recording}
        judul="Isi hasil eksperimen" keterangan={showRecord?.name} labelSimpan="Simpan hasil" testId="ab-record-form">
        {showRecord && showRecord.variants.map(v => (
          <div key={v.id} className="space-y-2 border-b border-[var(--glass-border)] pb-3">
            <p className="text-sm font-medium">{v.label}{v.content ? <span className="block text-xs font-normal italic text-muted-foreground">{v.content}</span> : null}</p>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {ISIAN_HASIL_AB.map(([key, lbl]) => (
                <Isian key={key} label={lbl} htmlFor={`rec-${v.id}-${key}`}>
                  <Input id={`rec-${v.id}-${key}`} type="number" min={0} value={recordData[v.id]?.[key] ?? ''}
                    onChange={e => setRecordData(d => ({ ...d, [v.id]: { ...d[v.id], [key]: Number(e.target.value) } }))} />
                </Isian>
              ))}
            </div>
          </div>
        ))}
      </FormPopup>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// MAIN MODULE
// ─────────────────────────────────────────────────────────────────
const ISIAN_HASIL_AB = [['views', 'Tayangan'], ['clicks', 'Klik'], ['orders', 'Pesanan'], ['revenue_rp', 'Omzet (Rp)'], ['engagement', 'Interaksi']];

export default function AdvancedAIModule({ token }) {
  const [activeTab, setActiveTab] = useState('pricing');
  const authH = useMemo(() => ({ Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` }), [token]);
  const TAMPILAN = [
    { key: 'pricing', label: 'Harga dinamis', icon: DollarSign },
    { key: 'churn', label: 'Pelanggan berisiko berhenti', icon: Users },
    { key: 'abtest', label: 'Uji A/B', icon: FlaskConical },
  ];
  return (
    <PageLayout testId="advanced-ai-module" title="AI lanjutan"
      subtitle="Harga dinamis, prediksi pelanggan berhenti, dan uji A/B konten."
      filters={<FilterChips options={TAMPILAN} value={activeTab} onChange={setActiveTab} hideWhenEmpty={false} testId="advanced-ai-view" ariaLabel="Tampilan" />}>
      {activeTab === 'pricing' && <DynamicPricingTab authH={authH} />}
      {activeTab === 'churn' && <ChurnPredictionTab authH={authH} />}
      {activeTab === 'abtest' && <ABTestingTab authH={authH} />}
    </PageLayout>
  );
}

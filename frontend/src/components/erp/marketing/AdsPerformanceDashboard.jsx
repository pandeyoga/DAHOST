import { confirmDialog } from '@/components/ui/confirm-dialog';
/**
 * Performa iklan (tab di Laporan Marketing; juga modul mandiri).
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, penyaring satu baris, StatTile berketerangan, tabel + unduh Excel/CSV,
 * rekomendasi AI = tabel (dulu kartu bergradien berulang), bahasa Indonesia, tanpa emoji.
 * Kartu ringkasan TIDAK menghitung data contoh (backend); tabel kampanye masih memuatnya → kini ditandai
 * "Data contoh" + catatan (dulu kartu Rp 0 di atas tabel berisi 25 kampanye tanpa penjelasan).
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Eye, RefreshCw, Loader2, Brain, Sparkles, Plus, Pencil, Trash2, Info } from 'lucide-react';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PaginationLite from '@/components/ui/pagination-lite';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';
import { useToast } from '@/hooks/use-toast';
import { useActiveMarketingAccount } from '@/hooks/useActiveMarketingAccount';
import { ActiveAccountBar } from './ActiveAccountBar';
import { useMarketingAccounts } from '@/hooks/useMarketingAccounts';
import axios from 'axios';
import AdsEntryDialog from './AdsEntryDialog';

const API = process.env.REACT_APP_BACKEND_URL;

function fmt(n) { return new Intl.NumberFormat('id-ID').format(n || 0); }
function fmtRp(n) { return `Rp ${fmt(n)}`; }

const PLATFORM_LABEL = {
  meta: 'Meta', meta_ads: 'Meta', google: 'Google', google_ads: 'Google', tiktok: 'TikTok', tiktok_ads: 'TikTok',
  shopee: 'Shopee', tokopedia: 'Tokopedia',
};
const labelPlatform = (p) => PLATFORM_LABEL[String(p || '').toLowerCase()] || p || '—';
const STATUS_IKLAN = { active: 'Aktif', paused: 'Dijeda', ended: 'Selesai' };

const REC_TYPE_CONFIG = {
  pause:            { label: 'Jeda',               tone: 'danger' },
  scale_up:         { label: 'Naikkan anggaran',   tone: 'success' },
  optimize:         { label: 'Optimalkan',         tone: 'warning' },
  budget_shift:     { label: 'Pindahkan anggaran', tone: 'info' },
  creative_refresh: { label: 'Ganti materi iklan', tone: 'primary' },
};

const PRIORITY_CONFIG = {
  urgent: { tone: 'danger', label: 'Mendesak' },
  high:   { tone: 'warning', label: 'Tinggi' },
  medium: { tone: 'default', label: 'Sedang' },
  low:    { tone: 'muted', label: 'Rendah' },
};

export default function AdsPerformanceDashboard({ token }) {
  const { toast } = useToast();
  const { activeAccount, setActiveAccount } = useActiveMarketingAccount();
  const { accounts: masterAccounts } = useMarketingAccounts(token);
  const [summary, setSummary] = useState(null);
  const [campaigns, setCampaigns] = useState([]);
  const [pagination, setPagination] = useState(null);
  const [loading, setLoading] = useState(true);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [aiRecs, setAiRecs] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('campaigns');
  // F16 — dialog input/ubah biaya iklan
  const [adsDialogOpen, setAdsDialogOpen] = useState(false);
  const [adsEditing, setAdsEditing] = useState(null);

  const [platformFilter, setPlatformFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [page, setPage] = useState(1);
  
  const authH = { Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` };
  
  const fetchSummary = useCallback(async () => {
    setSummaryLoading(true);
    try {
      // F14 — ringkasan iklan dilingkupi toko yang sama dengan tabelnya.
      const res = await axios.get(`${API}/api/marketing/ads/summary`, {
        headers: authH,
        params: activeAccount?.id ? { account_id: activeAccount.id } : {},
      });
      if (res.data.success) {
        setSummary(res.data.data);
      }
    } catch (e) {
      toast({ title: 'Gagal memuat ringkasan iklan', variant: 'destructive' });
    } finally {
      setSummaryLoading(false);
    }
  }, [token, activeAccount]); // eslint-disable-line

  const fetchCampaigns = useCallback(async () => {
    setLoading(true);
    try {
      const params = { page, page_size: 20 };
      if (platformFilter) params.platform = platformFilter;
      if (statusFilter) params.status = statusFilter;
      if (activeAccount?.id) params.account_id = activeAccount.id;
      const res = await axios.get(`${API}/api/marketing/ads/campaigns`, { params, headers: authH });
      if (res.data.success) {
        setCampaigns(res.data.data.campaigns || []);
        setPagination(res.data.pagination);
      }
    } catch (e) {
      toast({ title: 'Gagal memuat kampanye', variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  }, [page, platformFilter, statusFilter, token, activeAccount]); // eslint-disable-line
  
  useEffect(() => { fetchSummary(); }, [fetchSummary]);
  useEffect(() => { fetchCampaigns(); }, [fetchCampaigns]);

  const runAiRecommendations = async () => {
    setAiLoading(true);
    setActiveTab('ai');
    try {
      const res = await axios.post(`${API}/api/marketing/ads/ai-recommendations`, {}, { headers: authH });
      if (res.data.success) setAiRecs(res.data.data);
    } catch (e) {
      toast({ title: 'Rekomendasi AI gagal', description: e.response?.data?.detail || e.message, variant: 'destructive' });
    } finally {
      setAiLoading(false);
    }
  };
  
  const adaContoh = campaigns.some((c) => c._seed_origin);
  const nilai = (v) => (summaryLoading && !summary ? '…' : v);
  const perPlatform = Object.entries(summary?.by_platform || {}).map(([platform, d]) => ({ platform, ...d }));
  const hapus = async (c) => {
    const ok = await confirmDialog({ title: `Hapus data iklan "${c.campaign_name}"?`, body: 'Data kampanye ini dihapus.', confirmLabel: 'Hapus', danger: true });
    if (!ok) return;
    try {
      await axios.delete(`${API}/api/marketing/ads/campaigns/${c.id}`, { headers: authH });
      toast({ title: 'Data iklan dihapus' });
      fetchCampaigns(); fetchSummary();
    } catch (e) {
      toast({ title: 'Gagal menghapus', description: e.response?.data?.detail, variant: 'destructive' });
    }
  };

  const kolom = [
    { kunci: 'nama', label: 'Kampanye', hp: 'judul', isi: (c) => (
      <div className="min-w-0 md:max-w-[16rem]">
        <p className="truncate font-medium" title={c.campaign_name}>{c.campaign_name}</p>
        {c._seed_origin && <StatusBadge status="contoh" label="Data contoh" tone="muted" />}
      </div>) },
    { kunci: 'toko', label: 'Toko', hp: 'keterangan', isi: (c) => (
      <span className="block max-w-[10rem] truncate" title={c.account_name}>{c.account_name || '—'}</span>) },
    { kunci: 'platform', label: 'Platform', isi: (c) => labelPlatform(c.platform) },
    { kunci: 'spend', label: 'Biaya iklan', rata: 'kanan', isi: (c) => <span className="tabular-nums md:whitespace-nowrap">{fmtRp(c.spend)}</span> },
    { kunci: 'rev', label: 'Omzet iklan', rata: 'kanan', isi: (c) => <span className="tabular-nums md:whitespace-nowrap">{fmtRp(c.revenue)}</span> },
    { kunci: 'roas', label: 'ROAS', rata: 'kanan', isi: (c) => <span className="tabular-nums font-semibold">{c.roas}×</span> },
    { kunci: 'cpa', label: 'CPA', rata: 'kanan', isi: (c) => <span className="tabular-nums md:whitespace-nowrap">{fmtRp(c.cpa)}</span> },
    { kunci: 'ctr', label: 'CTR', rata: 'kanan', isi: (c) => <span className="tabular-nums">{c.ctr}%</span> },
    { kunci: 'konv', label: 'Konversi', rata: 'kanan', isi: (c) => <span className="tabular-nums">{fmt(c.conversions)}</span> },
    { kunci: 'status', label: 'Status', isi: (c) => (
      <StatusBadge status={c.status} label={STATUS_IKLAN[c.status] || c.status} tone={c.status === 'active' ? 'success' : 'muted'} />) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (c) => (
      <div className="flex items-center justify-end gap-1">
        <Button size="icon-sm" variant="ghost" data-testid={`ads-edit-${c.id}`} title="Ubah data iklan" aria-label="Ubah data iklan"
          onClick={() => { setAdsEditing(c); setAdsDialogOpen(true); }}>
          <Pencil />
        </Button>
        <Button size="icon-sm" variant="ghost" className="text-[hsl(var(--danger-text))]" data-testid={`ads-delete-${c.id}`}
          title="Hapus data iklan" aria-label="Hapus data iklan" onClick={() => hapus(c)}>
          <Trash2 />
        </Button>
      </div>) },
  ];

  const kolomUnduh = [
    { label: 'Kampanye', nilai: (c) => c.campaign_name }, { label: 'Toko', nilai: (c) => c.account_name || '' },
    { label: 'Platform', nilai: (c) => labelPlatform(c.platform) }, { label: 'Biaya iklan', nilai: (c) => Number(c.spend || 0) },
    { label: 'Omzet iklan', nilai: (c) => Number(c.revenue || 0) }, { label: 'ROAS', nilai: (c) => Number(c.roas || 0) },
    { label: 'CPA', nilai: (c) => Number(c.cpa || 0) }, { label: 'CTR (%)', nilai: (c) => Number(c.ctr || 0) },
    { label: 'Konversi', nilai: (c) => Number(c.conversions || 0) }, { label: 'Status', nilai: (c) => STATUS_IKLAN[c.status] || c.status },
    { label: 'Data contoh', nilai: (c) => (c._seed_origin ? 'Ya' : 'Tidak') },
  ];
  const ambilSemua = async () => {
    const out = [];
    for (let p = 1; p <= 100; p += 1) {
      const params = { page: p, page_size: 100 };
      if (platformFilter) params.platform = platformFilter;
      if (statusFilter) params.status = statusFilter;
      if (activeAccount?.id) params.account_id = activeAccount.id;
      const res = await axios.get(`${API}/api/marketing/ads/campaigns`, { params, headers: authH });
      out.push(...(res.data?.data?.campaigns || []));
      if (p >= (res.data?.pagination?.total_pages || 1)) break;
    }
    return out;
  };

  const recs = aiRecs?.recommendations || [];

  return (
    <PageLayout testId="ads-dashboard" title="Performa iklan"
      subtitle="Biaya dan hasil kampanye iklan Meta, TikTok, dan Google per toko."
      actions={<>
        <Button variant="outline" onClick={runAiRecommendations} disabled={aiLoading} data-testid="ai-recs-btn">
          {aiLoading ? <Loader2 className="animate-spin" /> : <Brain />}Rekomendasi AI
        </Button>
        {/* F16 — biaya iklan bisa DIINPUT dari layar (dulu hanya GET dari data demo) */}
        <Button data-testid="ads-add-btn" onClick={() => { setAdsEditing(null); setAdsDialogOpen(true); }}>
          <Plus />Input biaya iklan
        </Button>
      </>}
      filters={<>
        <ActiveAccountBar accounts={masterAccounts} activeAccount={activeAccount} onAccountChange={setActiveAccount}
          hint="Akun untuk data iklan" />
        <FilterChips value={activeTab} onChange={setActiveTab} hideWhenEmpty={false} testId="ads-view"
          options={[{ key: 'campaigns', label: 'Kampanye' }, { key: 'ai', label: 'Rekomendasi AI' }]} />
        {activeTab === 'campaigns' && (<>
          <SmartNativeSelect className="w-40" value={platformFilter} searchable={false} data-testid="ads-filter-platform"
            onChange={(e) => { setPlatformFilter(e.target.value); setPage(1); }}>
            <option value="">Semua platform</option>
            <option value="meta">Meta</option>
            <option value="tiktok">TikTok</option>
            <option value="google">Google</option>
          </SmartNativeSelect>
          <SmartNativeSelect className="w-36" value={statusFilter} searchable={false} data-testid="ads-filter-status"
            onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}>
            <option value="">Semua status</option>
            <option value="active">Aktif</option>
            <option value="paused">Dijeda</option>
          </SmartNativeSelect>
        </>)}
      </>}
      tools={<>
        {activeTab === 'campaigns'
          ? <TombolUnduh namaBerkas="kampanye-iklan" namaLembar="Kampanye" baris={campaigns} ambilSemua={ambilSemua}
              kolom={kolomUnduh} testId="ads-unduh" />
          : <TombolUnduh namaBerkas="rekomendasi-iklan-ai" namaLembar="Rekomendasi" baris={recs} testId="ads-ai-unduh"
              kolom={[
                { label: 'Jenis', nilai: (r) => (REC_TYPE_CONFIG[r.type] || REC_TYPE_CONFIG.optimize).label },
                { label: 'Kampanye', nilai: (r) => r.campaign || '' }, { label: 'Platform', nilai: (r) => labelPlatform(r.platform) },
                { label: 'Prioritas', nilai: (r) => (PRIORITY_CONFIG[r.priority] || PRIORITY_CONFIG.medium).label },
                { label: 'Tindakan', nilai: (r) => r.action || '' }, { label: 'Alasan', nilai: (r) => r.reason || '' },
                { label: 'Dampak', nilai: (r) => r.expected_impact || '' },
              ]} />}
        <Button variant="outline" size="icon" onClick={() => { fetchSummary(); fetchCampaigns(); }} disabled={loading}
          title="Muat ulang" aria-label="Muat ulang" data-testid="ads-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={(
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="ads-kpi">
          <StatTile label="Biaya iklan" value={nilai(fmtRp(summary?.total_spend))}
            sub={`${fmt(summary?.total_campaigns)} baris kampanye · semua periode`} />
          <StatTile label="Omzet dari iklan" value={nilai(fmtRp(summary?.total_revenue))}
            sub={summary?.total_spend ? `ROAS ${summary?.overall_roas || 0}× (omzet ÷ biaya)` : 'ROAS — belum ada biaya iklan'} />
          <StatTile label="Konversi" value={nilai(fmt(summary?.total_conversions))}
            sub={summary?.total_conversions ? `CPA ${fmtRp(summary?.overall_cpa)} per konversi` : 'CPA — belum ada konversi'} />
          <StatTile label="CTR" value={nilai(summary?.overall_ctr ? `${summary.overall_ctr}%` : '—')}
            sub={summary?.overall_ctr ? 'Klik ÷ tayangan' : 'Belum ada tayangan iklan'} />
        </div>
      )}
      footer={activeTab === 'campaigns' && pagination && pagination.total > 0 && (
        <PaginationLite page={page} totalPages={pagination.total_pages || 1} total={pagination.total || 0} pageSize={20} onPageChange={setPage} />
      )}>
      {adaContoh && (
        <Notice tone="info" icon={Info} testId="ads-sample-note">
          Kampanye bertanda "Data contoh" adalah data contoh bawaan: tetap tampil di tabel, tetapi tidak dihitung di kartu
          ringkasan di atas. Hapus bila tidak diperlukan.
        </Notice>
      )}

      {perPlatform.length > 0 && activeTab === 'campaigns' && (
        <TabelData baris={perPlatform} kunci={(r) => r.platform} testId="ads-per-platform"
          kolom={[
            { kunci: 'platform', label: 'Platform iklan', hp: 'judul', isi: (r) => <span className="font-medium">{labelPlatform(r.platform)}</span> },
            { kunci: 'spend', label: 'Biaya', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtRp(r.spend)}</span> },
            { kunci: 'rev', label: 'Omzet', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtRp(r.revenue)}</span> },
            { kunci: 'roas', label: 'ROAS', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.roas}×</span> },
            { kunci: 'n', label: 'Kampanye', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmt(r.campaigns)}</span> },
          ]} />
      )}

      {/* Kampanye */}
      {activeTab === 'campaigns' && (
        loading && campaigns.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">Memuat kampanye…</p>
        ) : (
          <TabelData kolom={kolom} baris={campaigns} testId="ads-table"
            kosong={<EmptyState icon={Eye} title="Belum ada kampanye" description="Input biaya iklan untuk mulai melihat ROAS dan CPA." />} />
        )
      )}

      {/* Rekomendasi AI */}
      {activeTab === 'ai' && (
        aiLoading ? (
          <p className="py-10 text-center text-sm text-muted-foreground">AI sedang menganalisis kampanye…</p>
        ) : !aiRecs ? (
          <EmptyState icon={Brain} title="Rekomendasi kampanye dari AI"
            description="AI menganalisis ROAS, CTR, dan CPA semua kampanye lalu memberi saran konkret."
            action={<Button onClick={runAiRecommendations}><Sparkles />Analisis kampanye</Button>} />
        ) : (
          <>
            <Notice tone="info" icon={Brain} title={aiRecs.summary}>
              {[aiRecs.best_platform && `Terbaik: ${aiRecs.best_platform}`, aiRecs.worst_platform && `Terlemah: ${aiRecs.worst_platform}`,
                aiRecs.overall_roas && `ROAS keseluruhan ${aiRecs.overall_roas}×`].filter(Boolean).join(' · ')}
              {aiRecs.budget_advice && <p className="mt-1">{aiRecs.budget_advice}</p>}
            </Notice>
            <TabelData baris={recs} kunci={(r) => `${r.campaign}-${r.type}-${r.action}`} testId="ads-ai-table"
              kolom={[
                { kunci: 'jenis', label: 'Jenis', isi: (r) => {
                  const t = REC_TYPE_CONFIG[r.type] || REC_TYPE_CONFIG.optimize;
                  return <StatusBadge status={r.type} label={t.label} tone={t.tone} />;
                } },
                { kunci: 'kampanye', label: 'Kampanye', hp: 'judul', isi: (r) => (
                  <div><p className="font-medium">{r.campaign}</p>{r.platform && <p className="text-xs text-muted-foreground">{labelPlatform(r.platform)}</p>}</div>) },
                { kunci: 'prio', label: 'Prioritas', isi: (r) => {
                  const pr = PRIORITY_CONFIG[r.priority] || PRIORITY_CONFIG.medium;
                  return <StatusBadge status={r.priority} label={pr.label} tone={pr.tone} />;
                } },
                { kunci: 'aksi', label: 'Tindakan', isi: (r) => (
                  <div className="max-w-[28rem]"><p className="text-sm">{r.action}</p><p className="text-xs text-muted-foreground">{r.reason}</p></div>) },
                { kunci: 'dampak', label: 'Dampak', isi: (r) => <span className="text-sm">{r.expected_impact || '—'}</span> },
              ]} />
          </>
        )
      )}
      <AdsEntryDialog
        open={adsDialogOpen}
        entry={adsEditing}
        token={token}
        onClose={() => { setAdsDialogOpen(false); setAdsEditing(null); }}
        onSaved={() => { fetchCampaigns(); fetchSummary(); }}
      />
    </PageLayout>
  );
}

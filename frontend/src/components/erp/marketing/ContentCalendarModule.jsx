/**
 * Kalender konten (Portal Toko) — rencana konten multi-platform, performa, scorecard kreator, KPI platform.
 *
 * Standar UI/UX v2 (8 Nov 2026): empat tampilan memakai HubTabs (dulu deret tombol buatan sendiri); tab Kalender
 * memakai PageLayout: penyaring satu baris, ViewToggle Kalender/Daftar di alat, 4 StatTile berketerangan, daftar =
 * tabel + unduh Excel/CSV semua baris (kalender: unduh isi bulan itu), detail popup, form = FormPopup + DatePicker.
 * Emoji platform dan label Inggris ("Draft", "Content Calendar", "AI Hook") diganti. Panggilan API tidak berubah.
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import ContentPerformanceView from './ContentPerformanceView';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import CreatorScorecardView from './CreatorScorecardView';
import PlatformKpiView from './PlatformKpiView';
import { Plus, Pencil, Trash2, Sparkles, ChevronLeft, ChevronRight, Loader2, RefreshCw, Search, CalendarDays, List } from 'lucide-react';
import axios from 'axios';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { GlassCard } from '@/components/ui/glass';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import DatePicker from '@/components/ui/date-picker';
import ViewToggle from '@/components/ui/view-toggle';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import PaginationLite from '@/components/ui/pagination-lite';
import { useToast } from '@/hooks/use-toast';
import { useMarketingAccounts } from '@/hooks/useMarketingAccounts';
import { formatDateID } from '@/lib/format';
import { cn } from '@/lib/utils';
import HubTabs from '../hubs/HubTabs';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from '../moduleAtoms';
import { MarketingAccountSelect } from './pickers/MarketingPickers';

const API = process.env.REACT_APP_BACKEND_URL;

const PLATFORM_LABEL = { shopee: 'Shopee', tiktok: 'TikTok', tokopedia: 'Tokopedia', instagram: 'Instagram', facebook: 'Facebook' };
const labelPlatform = (p) => PLATFORM_LABEL[p] || (p ? p.charAt(0).toUpperCase() + p.slice(1) : '—');
const STATUS_CONFIG = {
  draft: { label: 'Draf', tone: 'muted' },
  scheduled: { label: 'Terjadwal', tone: 'info' },
  posted: { label: 'Tayang', tone: 'success' },
  cancelled: { label: 'Batal', tone: 'danger' },
};
const StatusKonten = ({ status }) => {
  const c = STATUS_CONFIG[status] || STATUS_CONFIG.draft;
  return <StatusBadge status={status} label={c.label} tone={c.tone} />;
};
const CHIP = {
  posted: 'bg-[hsl(var(--success)/0.12)] text-[hsl(var(--success-text))]',
  scheduled: 'bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))]',
  cancelled: 'bg-[hsl(var(--destructive)/0.12)] text-[hsl(var(--danger-text))]',
  draft: 'bg-foreground/5 text-muted-foreground',
};
const VIEWS = [
  { key: 'calendar', label: 'Tampilan kalender', icon: CalendarDays },
  { key: 'list', label: 'Tampilan daftar', icon: List },
];
const MONTHS_ID = ['Januari','Februari','Maret','April','Mei','Juni','Juli','Agustus','September','Oktober','November','Desember'];
const DAYS_ID   = ['Min','Sen','Sel','Rab','Kam','Jum','Sab'];
const tgl = (v) => (v ? formatDateID(String(v).slice(0, 10)) : '—');

const EMPTY_FORM = {
  account_id: '', account_name: '', platform: 'shopee', date: '', content_type: 'foto_produk',
  title: '', description: '', cta: '', post_time: '', reference_link: '', status: 'draft',
  published_url: '',
};

function ContentCalendarBase({ token }) {
  const { toast } = useToast();
  const authH = useMemo(() => ({ Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` }), [token]);
  const { accounts: masterAccounts, byId: accountById } = useMarketingAccounts(token);

  const now = new Date();
  const [year,  setYear]  = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [view,  setView]  = useState('calendar'); // 'calendar' | 'list'

  const [summary,      setSummary]      = useState(null);
  const [calendarData, setCalendarData] = useState([]);
  const [listData,     setListData]     = useState([]);
  const [pagination,   setPagination]   = useState(null);
  const [contentTypes, setContentTypes] = useState([]);
  const [accounts,     setAccounts]     = useState([]);

  const [loading,    setLoading]    = useState(true);
  const [aiLoading,  setAiLoading]  = useState('');

  const [filterStatus,  setFilterStatus]  = useState('');
  const [filterPlatform,setFilterPlatform]= useState('');
  // F14 — filter per TOKO memakai account_id (SSOT), bukan mencocokkan nama toko.
  const [filterAccountId, setFilterAccountId] = useState('');
  const [filterType,    setFilterType]    = useState('');
  const [listPage,      setListPage]      = useState(1);
  // F10 (sesi #10) — daftar konten bisa panjang; "cari judul" adalah cara paling
  // cepat menemukan satu konten (dulu hanya ada penyaring status/jenis/platform).
  const [listSearch,    setListSearch]    = useState('');

  const [showForm,   setShowForm]   = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [form,       setForm]       = useState(EMPTY_FORM);
  const [formLoading,setFormLoading]= useState(false);

  const [showDetail, setShowDetail] = useState(null);
  const [galatForm, setGalatForm] = useState('');

  const fetchTypes = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/api/marketing/content-calendar/types`, { headers: authH });
      setContentTypes(res.data.types || []);
    } catch {}
  }, [authH]);

  const fetchSummary = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/api/marketing/content-calendar/summary`, { headers: authH });
      if (res.data.success) setSummary(res.data.data);
    } catch {}
  }, [authH]);

  const fetchMonthly = useCallback(async () => {
    setLoading(true);
    try {
      const params = { year, month };
      if (filterPlatform) params.platform = filterPlatform;
      if (filterAccountId) params.account_id = filterAccountId;
      const res = await axios.get(`${API}/api/marketing/content-calendar/monthly`, { params, headers: authH });
      if (res.data.success) setCalendarData(res.data.data || []);
    } catch { toast({ title: 'Gagal memuat kalender', variant: 'destructive' }); }
    finally { setLoading(false); }
  }, [year, month, filterPlatform, filterAccountId, authH, toast]);

  const needle = listSearch.trim().toLowerCase();
  const visibleList = needle
    ? (listData || []).filter((e) => [e.title, e.cta, e.account_name, e.platform,
      e.content_type_label, e.published_url]
      .some((v) => String(v || '').toLowerCase().includes(needle)))
    : (listData || []);

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const params = { page: listPage, page_size: 20 };
      if (filterStatus)   params.status = filterStatus;
      if (filterPlatform) params.platform = filterPlatform;
      if (filterAccountId) params.account_id = filterAccountId;
      if (filterType)     params.content_type = filterType;
      const res = await axios.get(`${API}/api/marketing/content-calendar`, { params, headers: authH });
      if (res.data.success) {
        setListData(res.data.data || []);
        setPagination(res.data.pagination);
        // Build unique account list
        const accs = [...new Set((res.data.data || []).map(e => e.account_name))].filter(Boolean);
        if (accs.length) setAccounts(accs);
      }
    } catch { toast({ title: 'Gagal memuat konten', variant: 'destructive' }); }
    finally { setLoading(false); }
  }, [listPage, filterStatus, filterPlatform, filterType, filterAccountId, authH, toast]);

  useEffect(() => { fetchTypes(); fetchSummary(); }, [fetchTypes, fetchSummary]);
  useEffect(() => { if (view === 'calendar') fetchMonthly(); else fetchList(); }, [view, fetchMonthly, fetchList]);

  // Build calendar grid
  const buildGrid = () => {
    const firstDay = new Date(year, month - 1, 1).getDay();
    const daysInMonth = new Date(year, month, 0).getDate();
    const cells = [];
    for (let i = 0; i < firstDay; i++) cells.push(null);
    for (let d = 1; d <= daysInMonth; d++) cells.push(d);
    return cells;
  };

  const getEntriesForDay = (day) => {
    if (!day) return [];
    const dateStr = `${year}-${String(month).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
    return calendarData.filter(e => e.date === dateStr);
  };

  const prevMonth = () => { if (month === 1) { setYear(y => y - 1); setMonth(12); } else setMonth(m => m - 1); };
  const nextMonth = () => { if (month === 12) { setYear(y => y + 1); setMonth(1); } else setMonth(m => m + 1); };

  const openCreate = (dateStr) => {
    setEditTarget(null);
    setForm({ ...EMPTY_FORM, date: dateStr || '' });
    setGalatForm('');
    setShowForm(true);
  };

  const openEdit = (entry) => {
    setEditTarget(entry);
    setForm({
      account_id: entry.account_id || '',
      account_name: entry.account_name || '', platform: entry.platform || 'shopee',
      date: entry.date || '', content_type: entry.content_type || 'foto_produk',
      title: entry.title || '', description: entry.description || '',
      cta: entry.cta || '', post_time: entry.post_time || '',
      reference_link: entry.reference_link || '', status: entry.status || 'draft',
      published_url: entry.published_url || '',
    });
    setGalatForm('');
    setShowForm(true);
  };

  // When account_id changes, auto-fill account_name & platform from master
  const handleAccountChange = (accountId) => {
    const acc = accountById[accountId];
    setForm(f => ({
      ...f,
      account_id: accountId,
      account_name: acc?.account_name || acc?.name || '',
      platform: acc?.platform || f.platform,
    }));
  };

  const handleSave = async () => {
    if (!form.account_id || !form.date || !form.title) {
      setGalatForm('Pilih akun, isi tanggal, dan judul/hook.'); return;
    }
    // 2026-11-07 (Tahap 5) — server menolak status Tayang tanpa link terbit; dulu form tidak
    // punya isian link terbit sama sekali sehingga konten tidak pernah bisa disimpan "Tayang".
    if (form.status === 'posted' && !/^https?:\/\/\S+$/i.test((form.published_url || '').trim())) {
      setGalatForm('Status Tayang wajib diisi tautan terbit (https://…).'); return;
    }
    setGalatForm('');
    setFormLoading(true);
    try {
      if (editTarget) {
        await axios.put(`${API}/api/marketing/content-calendar/${editTarget.id}`, form, { headers: authH });
        toast({ title: 'Konten disimpan.' });
      } else {
        await axios.post(`${API}/api/marketing/content-calendar`, form, { headers: authH });
        toast({ title: 'Konten ditambahkan.' });
      }
      setShowForm(false);
      fetchSummary();
      if (view === 'calendar') fetchMonthly(); else fetchList();
    } catch (e) {
      const d = e?.response?.data?.detail;
      setGalatForm(typeof d === 'string' ? d : 'Gagal menyimpan.');
    }
    finally { setFormLoading(false); }
  };

  const handleDelete = async (id) => {
    if (!(await confirmDialog({ title: 'Hapus konten ini?', body: 'Rencana konten dihapus dari kalender.', confirmLabel: 'Hapus', danger: true }))) return;
    try {
      await axios.delete(`${API}/api/marketing/content-calendar/${id}`, { headers: authH });
      toast({ title: 'Konten dihapus.' });
      if (showDetail?.id === id) setShowDetail(null);
      fetchSummary();
      if (view === 'calendar') fetchMonthly(); else fetchList();
    } catch { toast({ title: 'Gagal menghapus', variant: 'destructive' }); }
  };

  const handleAIHook = async (entryId) => {
    setAiLoading(entryId);
    try {
      const res = await axios.post(`${API}/api/marketing/content-calendar/${entryId}/ai-hook`, {}, { headers: authH });
      if (res.data.success) {
        toast({ title: 'Hook dari AI dipasang', description: res.data.applied_hook });
        if (view === 'calendar') fetchMonthly(); else fetchList();
      }
    } catch { toast({ title: 'Hook AI gagal dibuat', variant: 'destructive' }); }
    finally { setAiLoading(''); }
  };

  const handleStatusChange = async (entryId, newStatus) => {
    try {
      await axios.post(`${API}/api/marketing/content-calendar/${entryId}/status`, { status: newStatus }, { headers: authH });
      toast({ title: `Status diubah: ${STATUS_CONFIG[newStatus]?.label}` });
      fetchSummary();
      if (view === 'calendar') fetchMonthly(); else fetchList();
    } catch (e) {
      // mis. "Tayang" tanpa link terbit — alasan dari server ditampilkan apa adanya
      const d = e?.response?.data?.detail;
      toast({ title: typeof d === 'string' ? d : 'Gagal mengubah status', variant: 'destructive' });
    }
  };

  const grid = buildGrid();
  const todayStr = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
  const muatUlang = () => { fetchSummary(); if (view === 'calendar') fetchMonthly(); else fetchList(); };
  const jenis = (e) => e.content_type_label || contentTypes.find((t) => t.value === e.content_type)?.label || '—';

  /** Unduh daftar: semua konten hasil saringan (dulu hanya 20 baris halaman ini). Kalender: isi bulan yang tampil. */
  const ambilSemua = async () => {
    if (view === 'calendar') return calendarData;
    const semua = [];
    for (let p = 1; p <= 200; p += 1) {
      const params = { page: p, page_size: 100 };
      if (filterStatus)   params.status = filterStatus;
      if (filterPlatform) params.platform = filterPlatform;
      if (filterAccountId) params.account_id = filterAccountId;
      if (filterType)     params.content_type = filterType;
      const res = await axios.get(`${API}/api/marketing/content-calendar`, { params, headers: authH });
      semua.push(...(res.data.data || []));
      if (p >= (res.data.pagination?.total_pages || 1)) break;
    }
    return needle ? semua.filter((e) => [e.title, e.cta, e.account_name, e.platform, e.content_type_label, e.published_url]
      .some((v) => String(v || '').toLowerCase().includes(needle))) : semua;
  };

  const kolom = [
    { kunci: 'tanggal', label: 'Tanggal', hp: 'keterangan', isi: (e) => <span className="tabular-nums md:whitespace-nowrap">{tgl(e.date)}{e.post_time ? ` · ${e.post_time}` : ''}</span> },
    { kunci: 'toko', label: 'Toko', isi: (e) => (
      <span className="md:whitespace-nowrap">{e.account_name || '—'}<span className="block text-xs text-muted-foreground">{labelPlatform(e.platform)}</span></span>) },
    { kunci: 'jenis', label: 'Jenis', isi: (e) => <span className="md:whitespace-nowrap">{jenis(e)}</span> },
    { kunci: 'judul', label: 'Judul / hook', hp: 'judul', isi: (e) => (
      <div className="min-w-0 md:max-w-[18rem]"><p className="truncate font-medium" title={e.title}>{e.title}</p>
        {e.cta && <p className="truncate text-xs text-muted-foreground">{e.cta}</p>}</div>) },
    { kunci: 'status', label: 'Status', isi: (e) => <StatusKonten status={e.status} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (e) => (
      <div className="flex justify-end gap-1">
        <Button size="icon-sm" variant="ghost" onClick={() => handleAIHook(e.id)} disabled={aiLoading === e.id}
          title="Buat hook dengan AI" aria-label="Buat hook dengan AI">
          {aiLoading === e.id ? <Loader2 className="animate-spin" /> : <Sparkles />}
        </Button>
        <Button size="icon-sm" variant="ghost" onClick={() => openEdit(e)} title="Ubah konten" aria-label="Ubah konten"><Pencil /></Button>
      </div>) },
  ];

  return (
    <PageLayout testId="content-calendar-dashboard" title="Kalender konten"
      subtitle="Jadwal konten semua platform, dengan bantuan AI untuk hook."
      actions={<Button onClick={() => openCreate('')} data-testid="btn-add-content"><Plus />Tambah konten</Button>}
      filters={<>
        {view === 'list' && (
          <div className="relative w-full sm:w-56">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input className="pl-8" placeholder="Cari judul, hook, toko" value={listSearch}
              onChange={(e) => setListSearch(e.target.value)} data-testid="content-search" />
          </div>
        )}
        <MarketingAccountSelect token={token} value={filterAccountId} className="w-52"
          onChange={setFilterAccountId} label="" includeAll allLabel="Semua toko"
          required={false} testId="content-filter-account" />
        <SmartNativeSelect value={filterPlatform} onChange={(e) => setFilterPlatform(e.target.value)} className="w-40" searchable={false}>
          <option value="">Semua platform</option>
          {Object.entries(PLATFORM_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </SmartNativeSelect>
        {view === 'list' && <>
          <SmartNativeSelect value={filterStatus} onChange={(e) => { setFilterStatus(e.target.value); setListPage(1); }} className="w-36" searchable={false}>
            <option value="">Semua status</option>
            {Object.entries(STATUS_CONFIG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </SmartNativeSelect>
          <SmartNativeSelect value={filterType} onChange={(e) => { setFilterType(e.target.value); setListPage(1); }} className="w-44">
            <option value="">Semua jenis</option>
            {contentTypes.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </SmartNativeSelect>
        </>}
      </>}
      tools={<>
        <ViewToggle value={view} onChange={setView} options={VIEWS} testId="content-view" />
        <TombolUnduh namaBerkas={view === 'calendar' ? `kalender-konten-${year}-${String(month).padStart(2, '0')}` : 'kalender-konten'}
          namaLembar="Konten" baris={view === 'calendar' ? calendarData : visibleList} ambilSemua={ambilSemua} testId="content-export-csv"
          kolom={[
            { label: 'Tanggal', nilai: (e) => tgl(e.date) },
            { label: 'Platform', nilai: (e) => labelPlatform(e.platform) },
            { label: 'Toko', nilai: (e) => e.account_name || '' },
            { label: 'Jenis', nilai: jenis },
            { label: 'Judul', nilai: (e) => e.title || '' },
            { label: 'CTA / hook', nilai: (e) => e.cta || '' },
            { label: 'Jam', nilai: (e) => e.post_time || '' },
            { label: 'Status', nilai: (e) => STATUS_CONFIG[e.status]?.label || e.status || '' },
            { label: 'Tautan terbit', nilai: (e) => e.published_url || '' },
            { label: 'Tayangan', nilai: (e) => e.kpi?.views ?? '' },
            { label: 'Suka', nilai: (e) => e.kpi?.likes ?? '' },
            { label: 'Komentar', nilai: (e) => e.kpi?.comments ?? '' },
            { label: 'Pesanan', nilai: (e) => e.kpi?.orders ?? '' },
            { label: 'GMV', nilai: (e) => e.kpi?.gmv ?? '' },
          ]} />
        <Button variant="outline" size="icon" onClick={muatUlang} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={(summary?.total || 0) > 0 && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="content-kpi">
          <StatTile label="Total konten" value={summary?.total ?? '—'} sub={`${summary?.this_month ?? 0} bulan ini`}
            hint="Semua toko; tidak ikut penyaring." />
          <StatTile label="Terjadwal" value={summary?.scheduled ?? '—'} accent="primary" hint="Menunggu diposting." />
          <StatTile label="Sudah tayang" value={summary?.posted ?? '—'} accent="success" hint="Konten berstatus tayang." />
          <StatTile label="Draf" value={summary?.draft ?? '—'} accent="warning" hint="Perlu dirampungkan." />
        </div>
      )}
      footer={view === 'list' && pagination && pagination.total_pages > 1 && (
        <PaginationLite page={listPage} totalPages={pagination.total_pages} total={pagination.total} pageSize={20} onPageChange={setListPage} />
      )}>
      {view === 'calendar' ? (
        <GlassCard className="p-3" data-testid="content-calendar-grid">
          <div className="mb-2 flex items-center justify-between">
            <Button variant="ghost" size="icon" onClick={prevMonth} title="Bulan sebelumnya" aria-label="Bulan sebelumnya"><ChevronLeft /></Button>
            <p className="text-base font-semibold">{MONTHS_ID[month - 1]} {year}</p>
            <Button variant="ghost" size="icon" onClick={nextMonth} title="Bulan berikutnya" aria-label="Bulan berikutnya"><ChevronRight /></Button>
          </div>
          {loading ? (
            <div className="flex justify-center py-6"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
          ) : (
            <>
              <div className="mb-1 grid grid-cols-7">
                {DAYS_ID.map(d => <div key={d} className="py-1 text-center text-xs font-medium text-muted-foreground">{d}</div>)}
              </div>
              <div className="grid grid-cols-7 gap-1">
                {grid.map((day, idx) => {
                  const entries = day ? getEntriesForDay(day) : [];
                  const dateStr = day ? `${year}-${String(month).padStart(2,'0')}-${String(day).padStart(2,'0')}` : '';
                  const isToday = dateStr === todayStr;
                  return (
                    <div key={idx} onClick={() => day && openCreate(dateStr)} title={day ? 'Klik untuk menambah konten di tanggal ini' : undefined}
                      className={cn('min-h-[4.5rem] rounded-[var(--radius-sm)] border p-1 transition-colors sm:min-h-[5rem]',
                        !day ? 'border-transparent' : isToday ? 'border-primary bg-primary/5' : 'cursor-pointer border-[var(--glass-border)] hover:border-[hsl(var(--primary)/0.4)]')}>
                      {day && (
                        <>
                          <div className={cn('mb-1 text-right text-xs font-medium', isToday ? 'text-primary' : 'text-muted-foreground')}>{day}</div>
                          <div className="space-y-0.5">
                            {entries.slice(0, 3).map(e => (
                              <div key={e.id} title={e.title} onClick={(ev) => { ev.stopPropagation(); setShowDetail(e); }}
                                className={cn('cursor-pointer truncate rounded px-1 py-0.5 text-xs hover:opacity-80', CHIP[e.status] || CHIP.draft)}>
                                {e.title}
                              </div>
                            ))}
                            {entries.length > 3 && <div className="text-center text-xs text-muted-foreground">+{entries.length - 3} lagi</div>}
                          </div>
                        </>
                      )}
                    </div>
                  );
                })}
              </div>
              {calendarData.length === 0 && (
                <p className="mt-2 text-center text-sm text-muted-foreground">Belum ada konten di bulan ini. Klik tanggal untuk menambah.</p>
              )}
            </>
          )}
        </GlassCard>
      ) : loading && visibleList.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat konten…</p>
      ) : (
        <TabelData kolom={kolom} baris={visibleList} onKlikBaris={setShowDetail} testId="content-table"
          kosong={<EmptyState title="Belum ada konten" description="Tambahkan rencana konten atau ubah saringan."
            action={<Button onClick={() => openCreate('')}><Plus />Tambah konten</Button>} />} />
      )}

      {showDetail && (
        <DetailPopup open onClose={() => setShowDetail(null)} judul={showDetail.title} testId="content-detail"
          status={<StatusKonten status={showDetail.status} />}
          keterangan={`${showDetail.account_name || '—'} · ${labelPlatform(showDetail.platform)} · ${tgl(showDetail.date)}${showDetail.post_time ? ` ${showDetail.post_time}` : ''}`}
          aksi={<>
            <Button variant="outline" size="sm" onClick={() => { handleAIHook(showDetail.id); setShowDetail(null); }} disabled={aiLoading === showDetail.id}>
              <Sparkles />Hook AI
            </Button>
            <Button variant="outline" size="sm" onClick={() => { const e = showDetail; setShowDetail(null); openEdit(e); }}><Pencil />Ubah</Button>
            <Button variant="destructive" size="sm" onClick={() => handleDelete(showDetail.id)}><Trash2 />Hapus</Button>
          </>}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Jenis">{jenis(showDetail)}</BarisDetail>
            {showDetail.description && <BarisDetail label="Deskripsi">{showDetail.description}</BarisDetail>}
            {showDetail.cta && <BarisDetail label="CTA">{showDetail.cta}</BarisDetail>}
            {showDetail.reference_link && (
              <BarisDetail label="Tautan referensi">
                <a href={showDetail.reference_link} target="_blank" rel="noopener noreferrer" data-testid="content-reference-link-view"
                  className="break-all text-primary underline hover:opacity-80">{showDetail.reference_link}</a>
              </BarisDetail>
            )}
            {showDetail.published_url && (
              <BarisDetail label="Tautan terbit">
                <a href={showDetail.published_url} target="_blank" rel="noopener noreferrer" className="break-all text-primary underline">{showDetail.published_url}</a>
              </BarisDetail>
            )}
          </dl>
          <div className="flex flex-wrap items-center gap-2 border-t border-[var(--glass-border)] pt-3">
            <span className="text-sm text-muted-foreground">Ubah status:</span>
            {Object.keys(STATUS_CONFIG).filter((s) => s !== showDetail.status).map(s => (
              <Button key={s} size="sm" variant="outline"
                onClick={() => { handleStatusChange(showDetail.id, s); setShowDetail(null); }}>{STATUS_CONFIG[s].label}</Button>
            ))}
          </div>
        </DetailPopup>
      )}

      <FormPopup open={showForm} onClose={() => setShowForm(false)} ukuran="panjang" onSimpan={handleSave} menyimpan={formLoading}
        judul={editTarget ? 'Ubah konten' : 'Tambah konten'} galat={galatForm} testId="content-form"
        labelSimpan={editTarget ? 'Simpan perubahan' : 'Tambah konten'}>
        <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Akun / toko marketplace" wajib htmlFor="cc-account"
          petunjuk={form.account_id ? `Platform: ${labelPlatform(form.platform)} (otomatis dari akun terpilih)` : undefined}>
          <SmartNativeSelect id="cc-account" value={form.account_id || ''} onChange={(e) => handleAccountChange(e.target.value)}
            data-testid="content-account-select">
            <option value="">{masterAccounts.length === 0 ? 'Belum ada akun aktif' : 'Pilih akun'}</option>
            {masterAccounts.map(acc => <option key={acc.id} value={acc.id}>{`${acc.account_name} · ${labelPlatform(acc.platform)}`}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Jenis konten" wajib htmlFor="cc-type">
          <SmartNativeSelect id="cc-type" value={form.content_type} onChange={(e) => setForm(f => ({...f, content_type: e.target.value}))}>
            {contentTypes.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </SmartNativeSelect>
        </Isian>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Tanggal" wajib>
            <DatePicker value={form.date || ''} onChange={(v) => setForm(f => ({...f, date: v}))} testId="content-date" />
          </Isian>
          <Isian label="Status" htmlFor="cc-status">
            <SmartNativeSelect id="cc-status" value={form.status} searchable={false} onChange={(e) => setForm(f => ({...f, status: e.target.value}))}>
              {Object.entries(STATUS_CONFIG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </SmartNativeSelect>
          </Isian>
        </div>
        <Isian label="Judul / hook" wajib htmlFor="cc-title">
          <Input id="cc-title" value={form.title} placeholder="Hook atau judul konten yang menarik"
            onChange={e => setForm(f => ({...f, title: e.target.value}))} />
        </Isian>
        <Isian label="Deskripsi" htmlFor="cc-desc">
          <Textarea id="cc-desc" value={form.description} rows={2} placeholder="Rincian konten"
            onChange={e => setForm(f => ({...f, description: e.target.value}))} />
        </Isian>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="CTA" htmlFor="cc-cta">
            <Input id="cc-cta" value={form.cta} placeholder="Klik di bio!" onChange={e => setForm(f => ({...f, cta: e.target.value}))} />
          </Isian>
          <Isian label="Jam posting" htmlFor="cc-time">
            <Input id="cc-time" type="time" value={form.post_time} onChange={e => setForm(f => ({...f, post_time: e.target.value}))} />
          </Isian>
        </div>
        <Isian label="Tautan referensi / Google Drive" htmlFor="cc-ref"
          petunjuk="Tautan aset konten (Drive/Canva/Figma) — bisa dibuka langsung dari detail konten.">
          <Input id="cc-ref" type="url" value={form.reference_link} data-testid="content-reference-link-input"
            onChange={e => setForm(f => ({...f, reference_link: e.target.value}))}
            placeholder="https://drive.google.com/... (materi foto/video/brief)" />
        </Isian>
        {/* 2026-11-07 (Tahap 5) — status Tayang wajib tautan terbit. */}
        {form.status === 'posted' && (
          <Isian label="Tautan terbit" wajib htmlFor="cc-pub" petunjuk="Wajib untuk status Tayang — bukti konten benar-benar terbit.">
            <Input id="cc-pub" type="url" value={form.published_url} data-testid="content-published-url-input"
              onChange={e => setForm(f => ({...f, published_url: e.target.value}))}
              placeholder="https://… (tautan unggahan yang sudah tayang)" />
          </Isian>
        )}
      </FormPopup>
    </PageLayout>
  );
}

/**
 * F7.4 — kalender konten punya EMPAT sisi dalam satu pintu: "Kalender & rencana", "Performa konten" (KPI per
 * kreator), "Scorecard kreator" (target vs pencapaian), dan "KPI platform" (hasil impor ekspor Seller Center).
 * Dibungkus di sini (bukan menyalin modul) supaya tidak lahir pintu kembar: satu pintu, beberapa tampilan, satu sumber angka.
 * Standar UI/UX v2: tab halaman = HubTabs (judul hub tampil sekali; judul tiap tampilan disembunyikan).
 */
export default function ContentCalendarModule(props) {
  return (
    <div data-testid="content-tabs">
      <HubTabs hubId="marketing-content-calendar" title="Kalender konten"
        subtitle="Rencana konten, performa, scorecard kreator, dan KPI platform."
        tabs={[
          { key: 'kalender', label: 'Kalender & rencana', Component: ContentCalendarBase, props },
          { key: 'performa', label: 'Performa konten', Component: ContentPerformanceView, props: { token: props.token } },
          { key: 'scorecard', label: 'Scorecard kreator', Component: CreatorScorecardView, props: { token: props.token, onNavigate: props.onNavigate } },
          { key: 'kpi', label: 'KPI platform', Component: PlatformKpiView, props: { token: props.token, onNavigate: props.onNavigate } },
        ]} />
    </div>
  );
}

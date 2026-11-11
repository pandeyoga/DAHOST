/**
 * AccountTargetsModule — LAYAR SIKLUS + Target Bulanan per Akun & KOL/Creator.
 *
 * F5 (2026-08-13): tab pertama **Siklus** menyatukan target → anggaran → omzet → marjin → ROI dalam satu layar
 * (satu permintaan ke `/api/marketing/cycle/overview`). Tab lama (Platform Akun / KOL / Anggaran) DIPERTAHANKAN.
 * Modul yang SAMA dipakai dua portal (`marketing-targets` & `mgmt-marketing-cycle`) lewat prop `scope`.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout (navigasi bulan di `filters`, muat ulang di `tools`), tab standar,
 * kartu angka StatTile (dulu kartu berlatar hijau/kuning/merah), tabel standar + unduh Excel/CSV, form target =
 * FormPopup pendek (isian & simpan sama), warna lewat token, label berbahasa Indonesia.
 */
import { useState, useEffect, useCallback } from 'react';
import { Target, RefreshCw, ChevronLeft, ChevronRight, Loader2, FileDown } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import { bulanMarketingWIB, labelRentangBulanMarketing } from '@/lib/waktu';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { GlassCard } from '@/components/ui/glass';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from '../moduleAtoms';
import { AccountBadge } from './AccountBadge';
import BudgetAllocationTab from './BudgetAllocationTab';
import CycleView from './CycleView';
import { toast } from 'sonner';
import { formatRupiah } from '@/lib/format';

const API = process.env.REACT_APP_BACKEND_URL;
const fmtRp = formatRupiah;
const fmtNum = (n) => new Intl.NumberFormat('id-ID').format(n || 0);
const MONTH_NAMES = ['Jan','Feb','Mar','Apr','Mei','Jun','Jul','Agu','Sep','Okt','Nov','Des'];

// ─── Komponen bantu ────────────────────────────────────────────────────────────
const WARNA_BATANG = {
  on_track: 'bg-[hsl(var(--success))]', warning: 'bg-[hsl(var(--warning))]', behind: 'bg-[hsl(var(--destructive))]', no_target: 'bg-muted',
};
function ProgressBar({ pct, status }) {
  return (
    <div className="ml-auto mt-1 h-1.5 w-full max-w-[8rem] overflow-hidden rounded-full bg-[var(--glass-bg)]">
      <div className={`h-full transition-all ${WARNA_BATANG[status] || 'bg-primary'}`} style={{ width: `${Math.min(pct || 0, 100)}%` }} />
    </div>
  );
}

function CapaianBadge({ status, pct }) {
  if (status === 'no_target' || pct === null || pct === undefined) return <StatusBadge status="no_target" label="Belum ada target" tone="muted" />;
  const tone = { on_track: 'success', warning: 'warning', behind: 'danger' }[status] || 'default';
  return <StatusBadge status={status} label={`${pct}%`} tone={tone} />;
}

// ─── Form target akun (popup pendek) ───────────────────────────────────────────
function TargetFormDialog({ open, onOpenChange, account, year, month, existingTarget, onSaved, token }) {
  const [form, setForm] = useState({ revenue_target:'', orders_target:'', health_score_target:80, notes:'', reason:'' });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    // M-14 (audit 9 Nov 2026) — ringkasan bulanan mengirim target sebagai
    // {revenue, orders, health_score}; dulu form membaca revenue_target dkk. sehingga
    // terbuka kosong dan "Simpan" menimpa target menjadi 0.
    if (open) setForm({
      revenue_target:      existingTarget?.revenue ?? existingTarget?.revenue_target ?? '',
      orders_target:       existingTarget?.orders ?? existingTarget?.orders_target ?? '',
      health_score_target: existingTarget?.health_score ?? existingTarget?.health_score_target ?? 80,
      notes:               existingTarget?.notes               || '',
      reason:              '',
    });
  }, [open, existingTarget]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const res = await fetch(`${API}/api/marketing/targets`, {
        method: 'POST',
        headers: { Authorization:`Bearer ${token}`, 'Content-Type':'application/json' },
        body: JSON.stringify({
          account_id: account.id, year, month,
          revenue_target: parseFloat(form.revenue_target) || 0,
          orders_target:  parseInt(form.orders_target)    || 0,
          health_score_target: parseInt(form.health_score_target) || 80,
          notes: form.notes || null,
          reason: form.reason || null,
        }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || 'Gagal simpan');
      toast.success(`Target ${account.account_name} ${MONTH_NAMES[month-1]} disimpan`);
      onSaved(); onOpenChange(false);
    } catch (e) { toast.error(e.message); }
    finally { setSaving(false); }
  };

  return (
    <FormPopup open={open} onClose={() => onOpenChange(false)} judul={`Target ${account?.account_name || ''}`}
      keterangan={`${MONTH_NAMES[month-1]} ${year}`} onSimpan={handleSave} menyimpan={saving} labelSimpan="Simpan target"
      testId="target-form">
      {account && <AccountBadge account={account} size="sm" />}
      <Isian label="Target omzet (Rp)">
        <MoneyInput value={form.revenue_target} onChange={e=>setForm(f=>({...f,revenue_target:e.target.value}))} placeholder="50.000.000" data-testid="target-revenue-input" />
      </Isian>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Isian label="Target pesanan">
          <Input type="number" min={0} value={form.orders_target} onChange={e=>setForm(f=>({...f,orders_target:e.target.value}))} placeholder="500" data-testid="target-orders-input" />
        </Isian>
        <Isian label="Target skor kesehatan" petunjuk="0–100">
          <Input type="number" min={0} max={100} value={form.health_score_target} onChange={e=>setForm(f=>({...f,health_score_target:e.target.value}))} data-testid="target-health-input" />
        </Isian>
      </div>
      <Isian label="Catatan" petunjuk="Opsional.">
        <Input value={form.notes} onChange={e=>setForm(f=>({...f,notes:e.target.value}))} placeholder="Strategi bulan ini…" />
      </Isian>
      <Isian label="Alasan perubahan" petunjuk="Opsional. Tampil di Jejak Marketing bersama nilai lama → baru.">
        <Input value={form.reason} onChange={e=>setForm(f=>({...f,reason:e.target.value}))}
          placeholder="Mis. target dinaikkan setelah kampanye 8.8 disetujui" data-testid="target-reason-input" />
      </Isian>
    </FormPopup>
  );
}

// ─── Form target KOL / kreator (popup pendek) ──────────────────────────────────
function CreatorTargetFormDialog({ open, onOpenChange, creator, year, month, existingTarget, onSaved, token }) {
  const [form, setForm] = useState({ revenue_target:'', sessions_target:'', viewers_target:'', notes:'' });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) setForm({
      revenue_target:  existingTarget?.revenue  || '',
      sessions_target: existingTarget?.sessions || '',
      viewers_target:  existingTarget?.viewers  || '',
      notes:           existingTarget?.notes    || '',
    });
  }, [open, existingTarget]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const res = await fetch(`${API}/api/marketing/targets/creator`, {
        method: 'POST',
        headers: { Authorization:`Bearer ${token}`, 'Content-Type':'application/json' },
        body: JSON.stringify({
          creator_id: creator.id, year, month,
          revenue_target:  parseFloat(form.revenue_target)  || 0,
          sessions_target: parseInt(form.sessions_target)   || 0,
          viewers_target:  parseInt(form.viewers_target)    || 0,
          notes: form.notes || null,
        }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || 'Gagal simpan');
      toast.success(`Target ${creator.name} ${MONTH_NAMES[month-1]} disimpan`);
      onSaved(); onOpenChange(false);
    } catch (e) { toast.error(e.message); }
    finally { setSaving(false); }
  };

  return (
    <FormPopup open={open} onClose={() => onOpenChange(false)} judul={`Target KOL ${creator?.name || ''}`}
      keterangan={`${MONTH_NAMES[month-1]} ${year}`} onSimpan={handleSave} menyimpan={saving} labelSimpan="Simpan target"
      testId="creator-target-dialog">
      <Isian label="Target omzet (Rp)">
        <MoneyInput value={form.revenue_target} onChange={e=>setForm(f=>({...f,revenue_target:e.target.value}))} placeholder="50.000.000" data-testid="creator-target-revenue" />
      </Isian>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Isian label="Target sesi live" petunjuk="Jumlah live">
          <Input type="number" min={0} value={form.sessions_target} onChange={e=>setForm(f=>({...f,sessions_target:e.target.value}))} placeholder="12" data-testid="creator-target-sessions" />
        </Isian>
        <Isian label="Target penonton" petunjuk="Total">
          <Input type="number" min={0} value={form.viewers_target} onChange={e=>setForm(f=>({...f,viewers_target:e.target.value}))} placeholder="80000" data-testid="creator-target-viewers" />
        </Isian>
      </div>
      <Isian label="Catatan" petunjuk="Opsional.">
        <Input value={form.notes} onChange={e=>setForm(f=>({...f,notes:e.target.value}))} placeholder="Strategi bulan ini…" />
      </Isian>
    </FormPopup>
  );
}

export default function AccountTargetsModule({ token, scope = 'marketing', moduleId }) {
  // Bulan Marketing berjalan (WIB): tanggal 26 bulan lalu s/d 25 — owner 11 Nov 2026.
  const [year, setYear]   = useState(() => Number(bulanMarketingWIB().slice(0, 4)));
  const [month, setMonth] = useState(() => Number(bulanMarketingWIB().slice(5, 7)));
  // Tab awal ditentukan dari PROP (bukan sessionStorage): pelajaran sesi #5 —
  // petunjuk tab lewat sessionStorage bergantung urutan mount, sehingga deep-link
  // mendarat di tab pertama dan layar yang diminta seolah tidak ada.
  const [activeTab, setActiveTab] = useState('cycle');

  // Account targets
  const [summary, setSummary]     = useState(null);
  const [accounts, setAccounts]   = useState([]);
  const [loading, setLoading]     = useState(true);
  const [editAccount, setEditAccount]   = useState(null);
  const [editTarget, setEditTarget]     = useState(null);
  const [dialogOpen, setDialogOpen]     = useState(false);

  // Creator targets
  const [creatorSummary, setCreatorSummary]   = useState(null);
  const [creators, setCreators]               = useState([]);
  const [loadingCreator, setLoadingCreator]   = useState(true);
  const [editCreator, setEditCreator]         = useState(null);
  const [editCreatorTarget, setEditCreatorTarget] = useState(null);
  const [creatorDialogOpen, setCreatorDialogOpen] = useState(false);
  const [exportingCreator, setExportingCreator]   = useState(false);
  // Penyaring toko di tab Target KOL (owner 11 Nov: "ditugaskan ke akun tiktok mana belum ada infonya")
  const [tokoKol, setTokoKol] = useState('');

  const authH = { Authorization: `Bearer ${token}` };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [sumRes, accRes] = await Promise.all([
        fetch(`${API}/api/marketing/targets/monthly-summary?year=${year}&month=${month}`, { headers: authH }),
        fetch(`${API}/api/marketing/accounts?status=active`, { headers: authH }),
      ]);
      if (sumRes.ok) setSummary(await sumRes.json());
      if (accRes.ok) setAccounts(await accRes.json());
    } catch { toast.error('Gagal memuat data akun'); }
    finally { setLoading(false); }
  }, [year, month, token]); // eslint-disable-line

  const loadCreators = useCallback(async () => {
    setLoadingCreator(true);
    try {
      const [sumRes, crRes] = await Promise.all([
        fetch(`${API}/api/marketing/targets/creator/monthly-summary?year=${year}&month=${month}`, { headers: authH }),
        fetch(`${API}/api/marketing/kol/creators?limit=100`, { headers: authH }),
      ]);
      if (sumRes.ok) setCreatorSummary(await sumRes.json());
      if (crRes.ok) {
        const data = await crRes.json();
        setCreators(Array.isArray(data) ? data : (data.creators || []));
      }
    } catch { toast.error('Gagal memuat data creator'); }
    finally { setLoadingCreator(false); }
  }, [year, month, token]); // eslint-disable-line

  useEffect(() => { load(); loadCreators(); }, [load, loadCreators]);

  const prevMonth = () => { if (month === 1) { setMonth(12); setYear(y => y-1); } else setMonth(m => m-1); };
  const nextMonth = () => { if (month === 12) { setMonth(1); setYear(y => y+1); } else setMonth(m => m+1); };

  const openEdit = (row) => {
    setEditAccount(accounts.find(a => a.id === row.account_id) || row);
    setEditTarget(row.target.revenue != null ? row : null);
    setDialogOpen(true);
  };

  const openEditCreator = (row) => {
    setEditCreator(creators.find(c => c.id === row.creator_id) || { id: row.creator_id, name: row.creator_name });
    setEditCreatorTarget(row.target.revenue != null ? row.target : null);
    setCreatorDialogOpen(true);
  };

  const handleExportCreatorPDF = async () => {
    setExportingCreator(true);
    try {
      const res = await fetch(
        `${API}/api/marketing/targets/creator/export-pdf?year=${year}&month=${month}`,
        { headers: authH }
      );
      if (!res.ok) throw new Error('Gagal generate PDF');
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href     = url;
      a.download = `target-creator-${MONTH_NAMES[month-1].toLowerCase()}-${year}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success('PDF target kreator diunduh');
    } catch (e) { toast.error(e.message); }
    finally { setExportingCreator(false); }
  };

  const s  = summary?.summary || {};
  const cs = creatorSummary?.summary || {};
  const periodeLabel = `${MONTH_NAMES[month - 1]} ${year}`;
  const rentangLabel = labelRentangBulanMarketing(year, month);
  const semuaKreator = creatorSummary?.creators || [];
  const tokoKolPilihan = [...new Map(semuaKreator.flatMap((c) => c.accounts || []).map((a) => [a.id, a])).values()]
    .sort((a, b) => (a.code || '').localeCompare(b.code || ''));
  const kreatorTampil = !tokoKol ? semuaKreator
    : tokoKol === '-' ? semuaKreator.filter((c) => !(c.accounts || []).length)
      : semuaKreator.filter((c) => (c.accounts || []).some((a) => a.id === tokoKol));
  const nadaPct = (p) => (p == null ? 'default' : p >= 90 ? 'success' : p >= 70 ? 'warning' : 'danger');

  return (
    <PageLayout
      testId="account-targets-module"
      title="Target & anggaran"
      subtitle="Target, anggaran, omzet, marjin, dan ROI per toko dalam satu layar."
      filters={(
        <div className="flex items-center gap-1">
          <Button variant="outline" size="icon" onClick={prevMonth} data-testid="cycle-prev-month" title="Bulan sebelumnya" aria-label="Bulan sebelumnya"><ChevronLeft /></Button>
          <span className="min-w-[96px] text-center leading-tight" data-testid="cycle-period-label">
            <span className="block text-sm font-semibold">{periodeLabel}</span>
            <span className="block text-xs text-muted-foreground" data-testid="cycle-period-range">{rentangLabel}</span>
          </span>
          <Button variant="outline" size="icon" onClick={nextMonth} data-testid="cycle-next-month" title="Bulan berikutnya" aria-label="Bulan berikutnya"><ChevronRight /></Button>
          {activeTab === 'creators' && (
            <SmartNativeSelect value={tokoKol} onChange={(e) => setTokoKol(e.target.value)} searchable={false}
              className="ml-2 h-9 w-56" aria-label="Toko KOL" data-testid="creator-toko-filter">
              <option value="">Semua toko</option>
              {tokoKolPilihan.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              {semuaKreator.some((c) => !(c.accounts || []).length) && <option value="-">Belum ditugaskan</option>}
            </SmartNativeSelect>
          )}
        </div>
      )}
      tools={(
        <Button variant="outline" size="icon" onClick={() => { load(); loadCreators(); }} data-testid="cycle-reload-all" title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw />
        </Button>
      )}
    >
      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
        <TabsList className="h-auto w-auto flex-wrap justify-start">
          <TabsTrigger value="cycle" data-testid="tab-cycle">Siklus</TabsTrigger>
          <TabsTrigger value="accounts" data-testid="tab-accounts">Target akun</TabsTrigger>
          <TabsTrigger value="creators" data-testid="tab-creators">Target KOL</TabsTrigger>
          <TabsTrigger value="budget" data-testid="tab-budget">Anggaran</TabsTrigger>
        </TabsList>

        {/* ── TAB SIKLUS (F5) ── */}
        <TabsContent value="cycle" className="mt-0">
          <CycleView token={token} scope={scope} moduleId={moduleId}
            period={`${year}-${String(month).padStart(2, '0')}`} monthLabel={`${periodeLabel} · ${rentangLabel}`} />
        </TabsContent>

        {/* ── TAB AKUN ── */}
        <TabsContent value="accounts" className="mt-0 space-y-4">
          {s.total_accounts > 0 && (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-konten-utama="">
              <StatTile label="Total akun" value={fmtNum(s.total_accounts)} sub="Akun platform aktif" />
              <StatTile label="Omzet aktual" value={fmtRp(s.rev_actual)} sub={s.rev_target > 0 ? `dari target ${fmtRp(s.rev_target)}` : 'Target belum diisi'} />
              <StatTile label="Pesanan aktual" value={fmtNum(s.ord_actual)} sub={s.ord_target > 0 ? `dari target ${fmtNum(s.ord_target)}` : 'Target belum diisi'} />
              <StatTile label="Pencapaian omzet" value={s.rev_pct != null ? `${s.rev_pct}%` : '—'} accent={nadaPct(s.rev_pct)}
                sub={s.rev_pct == null ? 'Belum ada target omzet'
                  : `${periodeLabel}${s.accounts_without_target ? ` · ${s.accounts_with_target} toko bertarget` : ''}`} />
            </div>
          )}
          <GlassCard className="space-y-3 p-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <p className="text-base font-semibold text-foreground">Target vs aktual per akun</p>
              <TombolUnduh namaBerkas={`target-akun-${year}-${month}`} namaLembar="Target per akun" baris={summary?.accounts || []} testId="targets-unduh"
                kolom={[
                  { label: 'Akun', nilai: (r) => r.account_name || r.account_code },
                  { label: 'Kode', nilai: (r) => r.account_code },
                  { label: 'Omzet aktual (Rp)', nilai: (r) => r.actual?.revenue ?? 0 },
                  { label: 'Target omzet (Rp)', nilai: (r) => r.target?.revenue ?? '' },
                  { label: 'Pencapaian omzet (%)', nilai: (r) => r.achievement?.revenue_pct ?? '' },
                  { label: 'Pesanan aktual', nilai: (r) => r.actual?.orders ?? 0 },
                  { label: 'Target pesanan', nilai: (r) => r.target?.orders ?? '' },
                  { label: 'Skor kesehatan', nilai: (r) => r.health_score ?? '' },
                  { label: 'Tugas selesai', nilai: (r) => r.task_stats?.done ?? 0 },
                  { label: 'Total tugas', nilai: (r) => r.task_stats?.total ?? 0 },
                ]} />
            </div>
            {loading ? <p className="py-8 text-center text-sm text-muted-foreground"><Loader2 className="mr-2 inline h-4 w-4 animate-spin" />Memuat…</p>
            : (
              <div className="overflow-x-auto">
                <Table data-testid="targets-table">
                  <TableHeader>
                    <TableRow>
                      <TableHead>Akun</TableHead>
                      <TableHead className="text-right">Omzet</TableHead>
                      <TableHead className="text-right">Pesanan</TableHead>
                      <TableHead className="hidden text-right md:table-cell">Kesehatan</TableHead>
                      <TableHead className="hidden text-right md:table-cell">Tugas</TableHead>
                      <TableHead className="text-right"><span className="sr-only">Aksi</span></TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {!summary?.accounts?.length && (
                      <TableRow className="hover:bg-transparent">
                        <TableCell colSpan={6} className="p-0 [&>div]:py-8"><EmptyState title="Belum ada akun aktif" /></TableCell>
                      </TableRow>
                    )}
                    {(summary?.accounts || []).map((row) => (
                      <TableRow key={row.account_id} data-testid={`target-row-${row.account_code}`}>
                        <TableCell><AccountBadge account={row} size="xs" /></TableCell>
                        <TableCell className="text-right">
                          <div className="font-medium tabular-nums">{fmtRp(row.actual.revenue)}</div>
                          {row.target.revenue != null && <><div className="text-xs text-muted-foreground tabular-nums">dari {fmtRp(row.target.revenue)}</div><ProgressBar pct={row.achievement.revenue_pct} status={row.achievement.revenue_status} /></>}
                          <CapaianBadge status={row.achievement.revenue_status} pct={row.achievement.revenue_pct} />
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="font-medium tabular-nums">{fmtNum(row.actual.orders)}</div>
                          {row.target.orders != null && <><div className="text-xs text-muted-foreground tabular-nums">dari {fmtNum(row.target.orders)}</div><ProgressBar pct={row.achievement.orders_pct} status={row.achievement.orders_status} /></>}
                          <CapaianBadge status={row.achievement.orders_status} pct={row.achievement.orders_pct} />
                        </TableCell>
                        <TableCell className="hidden text-right tabular-nums md:table-cell">
                          <span className={row.health_score == null ? 'text-muted-foreground' : row.health_score >= 80 ? 'text-[hsl(var(--success-text))]' : row.health_score >= 60 ? 'text-[hsl(var(--warning-text))]' : 'text-[hsl(var(--danger-text))]'}>
                            {row.health_score ?? '—'}
                          </span>
                        </TableCell>
                        <TableCell className="hidden text-right tabular-nums md:table-cell">
                          {row.task_stats.done}<span className="text-muted-foreground"> / {row.task_stats.total}</span>
                        </TableCell>
                        <TableCell className="text-right">
                          <Button size="sm" variant="outline" onClick={() => openEdit(row)} data-testid={`set-target-${row.account_code}`}>
                            <Target />{row.target.revenue != null ? 'Ubah' : 'Isi target'}
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </GlassCard>
        </TabsContent>

        {/* ── TAB KOL / KREATOR ── */}
        <TabsContent value="creators" className="mt-0 space-y-4">
          {cs.total_creators > 0 && (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-konten-utama="">
              <StatTile label="Total kreator" value={fmtNum(cs.total_creators)} />
              <StatTile label="Omzet aktual" value={fmtRp(cs.rev_actual)} sub={cs.rev_target > 0 ? `dari target ${fmtRp(cs.rev_target)}` : 'Target belum diisi'} />
              <StatTile label="Pencapaian omzet" value={cs.rev_pct != null ? `${cs.rev_pct}%` : '—'} accent={nadaPct(cs.rev_pct)}
                sub={cs.rev_pct == null ? 'Belum ada target omzet' : periodeLabel} />
              <StatTile label="Total sesi live" value={fmtNum(creatorSummary?.creators?.reduce((t, c) => t + (c.actual?.sessions || 0), 0) || 0)}
                sub="Jumlah dari semua kreator di daftar" />
            </div>
          )}
          <GlassCard className="space-y-3 p-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <p className="text-base font-semibold text-foreground">Target vs aktual per KOL / kreator</p>
              <div className="flex flex-wrap items-center gap-2">
                <TombolUnduh namaBerkas={`target-kreator-${year}-${month}`} namaLembar="Target per kreator" baris={kreatorTampil}
                  testId="creator-targets-unduh"
                  kolom={[
                    { label: 'Kreator', nilai: (r) => r.creator_name },
                    { label: 'Kode', nilai: (r) => r.creator_code },
                    { label: 'Toko', nilai: (r) => (r.accounts || []).map((a) => a.name).join(', ') },
                    { label: 'Omzet aktual (Rp)', nilai: (r) => r.actual?.revenue ?? 0 },
                    { label: 'Target omzet (Rp)', nilai: (r) => r.target?.revenue ?? '' },
                    { label: 'Pencapaian omzet (%)', nilai: (r) => r.achievement?.revenue_pct ?? '' },
                    { label: 'Sesi live', nilai: (r) => r.actual?.sessions ?? 0 },
                    { label: 'Target sesi', nilai: (r) => r.target?.sessions ?? '' },
                    { label: 'Penonton', nilai: (r) => r.actual?.viewers ?? 0 },
                    { label: 'Target penonton', nilai: (r) => r.target?.viewers ?? '' },
                  ]} />
                <Button variant="outline" onClick={handleExportCreatorPDF} disabled={exportingCreator || loadingCreator}
                  data-testid="export-creator-pdf-btn">
                  {exportingCreator ? <Loader2 className="animate-spin" /> : <FileDown />}PDF
                </Button>
              </div>
            </div>
            {loadingCreator ? <p className="py-8 text-center text-sm text-muted-foreground"><Loader2 className="mr-2 inline h-4 w-4 animate-spin" />Memuat…</p>
            : (
              <div className="overflow-x-auto">
                <Table data-testid="creator-targets-table">
                  <TableHeader>
                    <TableRow>
                      <TableHead>Kreator</TableHead>
                      <TableHead className="hidden md:table-cell">Toko</TableHead>
                      <TableHead className="text-right">Omzet</TableHead>
                      <TableHead className="text-right">Sesi live</TableHead>
                      <TableHead className="hidden text-right md:table-cell">Penonton</TableHead>
                      <TableHead className="text-right"><span className="sr-only">Aksi</span></TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {!kreatorTampil.length && (
                      <TableRow className="hover:bg-transparent">
                        <TableCell colSpan={6} className="p-0 [&>div]:py-8">
                          <EmptyState title={semuaKreator.length ? 'Tidak ada kreator di toko ini' : 'Belum ada kreator aktif'} />
                        </TableCell>
                      </TableRow>
                    )}
                    {kreatorTampil.map((row) => (
                      <TableRow key={row.creator_id} data-testid={`creator-target-row-${row.creator_code}`}>
                        <TableCell>
                          <div className="font-medium">{row.creator_name}</div>
                          <div className="text-xs text-muted-foreground">{row.creator_code}</div>
                          <div className="text-xs text-muted-foreground md:hidden" data-testid={`creator-target-toko-hp-${row.creator_code}`}>
                            {(row.accounts || []).map((a) => a.name).join(', ') || 'Belum ditugaskan ke toko'}
                          </div>
                        </TableCell>
                        <TableCell className="hidden md:table-cell" data-testid={`creator-target-toko-${row.creator_code}`}>
                          {(row.accounts || []).length
                            ? (row.accounts || []).map((a) => (
                              <div key={a.id}><span className="font-medium">{a.name}</span> <span className="text-xs text-muted-foreground">{a.code}</span></div>
                            ))
                            : <StatusBadge status="belum" label="Belum ditugaskan" tone="warning" />}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="font-medium tabular-nums">{fmtRp(row.actual.revenue)}</div>
                          {row.target.revenue != null && <><div className="text-xs text-muted-foreground tabular-nums">dari {fmtRp(row.target.revenue)}</div><ProgressBar pct={row.achievement.revenue_pct} status={row.achievement.revenue_status} /></>}
                          <CapaianBadge status={row.achievement.revenue_status} pct={row.achievement.revenue_pct} />
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          <div className="font-medium">{row.actual.sessions}</div>
                          {row.target.sessions != null && <div className="text-xs text-muted-foreground">dari {row.target.sessions}</div>}
                          {row.achievement.sessions_pct != null && <span className="text-xs text-muted-foreground">{row.achievement.sessions_pct}%</span>}
                        </TableCell>
                        <TableCell className="hidden text-right tabular-nums md:table-cell">
                          <div className="font-medium">{fmtNum(row.actual.viewers)}</div>
                          {row.target.viewers != null && <div className="text-xs text-muted-foreground">dari {fmtNum(row.target.viewers)}</div>}
                        </TableCell>
                        <TableCell className="text-right">
                          <Button size="sm" variant="outline" onClick={() => openEditCreator(row)} data-testid={`set-creator-target-${row.creator_code}`}>
                            <Target />{row.target.revenue != null ? 'Ubah' : 'Isi target'}
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </GlassCard>
        </TabsContent>

        {/* ── TAB ANGGARAN & ALOKASI ── */}
        <TabsContent value="budget" className="mt-0">
          <BudgetAllocationTab token={token} accounts={accounts}
            period={`${year}-${String(month).padStart(2, '0')}`} monthLabel={`${periodeLabel} · ${rentangLabel}`} />
        </TabsContent>
      </Tabs>

      {editAccount && (
        <TargetFormDialog open={dialogOpen} onOpenChange={setDialogOpen}
          account={editAccount} year={year} month={month}
          existingTarget={editTarget?.target} onSaved={load} token={token} />
      )}
      {editCreator && (
        <CreatorTargetFormDialog open={creatorDialogOpen} onOpenChange={setCreatorDialogOpen}
          creator={editCreator} year={year} month={month}
          existingTarget={editCreatorTarget} onSaved={loadCreators} token={token} />
      )}
    </PageLayout>
  );
}

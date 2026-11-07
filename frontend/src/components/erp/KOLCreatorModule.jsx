/**
 * Kelola KOL (tab di KOL & Kreator, Portal Toko) — daftar kreator, performa live, permintaan produk, peringkat,
 * rapor mingguan.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout (judul disembunyikan di hub); lima tampilan dipilih dengan pil penyaring
 * (dulu deret tab buatan sendiri = tab di dalam tab); daftar kreator = tabel (dulu kartu besar per kreator) + rincian
 * popup; form kreator & sesi = FormPopup (dulu jendela buatan sendiri); tolak permintaan = confirmDialog berisi alasan
 * (dulu prompt peramban); bulan peringkat = pilihan bulan (dulu input bulan bawaan); setiap tabel bisa diunduh.
 * Panggilan API, isian, dan isi yang dikirim tidak berubah.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { Users, Video, ShoppingBag, Trophy, BarChart2, Plus, Pencil, Trash2, Check, X, Target, Package, Search, UserPlus } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Progress } from '@/components/ui/progress';
import { MoneyInput } from '@/components/ui/money-input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import DatePicker from '@/components/ui/date-picker';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { todayWIB, thisMonthWIB } from '@/lib/waktu';
import { formatDateID } from '@/lib/format';
import { useActiveMarketingAccount } from '@/hooks/useActiveMarketingAccount';
import PaginationBar from './PaginationBar';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';
import { monthOptions } from './finance/PeriodPicker';
import CreatorIncentivePanel from './marketing/CreatorIncentivePanel';
import CreatorWeeklyReportPanel from './marketing/CreatorWeeklyReportPanel';
import { getPlatformConfig } from './marketing/AccountBadge';

const API = process.env.REACT_APP_BACKEND_URL;

// ─── pembantu ───────────────────────────────────────────────────────────────
const fmt = (n) => new Intl.NumberFormat('id-ID').format(n || 0);
const fmtRp = (n) => `Rp ${fmt(n)}`;
const tgl = (v) => (v ? formatDateID(String(v).slice(0, 10)) : '—');
const STATUS = {
  active: ['Aktif', 'success'], inactive: ['Nonaktif', 'muted'],
  pending: ['Menunggu', 'warning'], approved: ['Disetujui', 'success'], rejected: ['Ditolak', 'danger'],
};
const Lencana = ({ s }) => <StatusBadge status={s} label={(STATUS[s] || [s || '—'])[0]} tone={(STATUS[s] || [])[1]} />;
const TIPE = { new: 'Kreator baru', kontrak: 'Kreator kontrak', continue: 'Kreator lanjutan' };
const labelPlatform = (p) => (getPlatformConfig(p).label !== 'Platform' ? getPlatformConfig(p).label : (p ? p.charAt(0).toUpperCase() + p.slice(1) : '—'));

function KPIBar({ label, value, target, unit = '' }) {
  const pct = target ? Math.min(100, Math.round((value / target) * 100)) : 0;
  return (
    <div className="space-y-1">
      <div className="flex justify-between gap-2 text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-medium tabular-nums">{unit}{fmt(value)} / {unit}{fmt(target)} ({pct}%)</span>
      </div>
      <Progress value={pct} className="h-1.5" />
    </div>
  );
}

// ─── Form kreator ───────────────────────────────────────────────────────────
function CreatorFormModal({ token, accounts, onClose, onSaved, editCreator }) {
  const isEdit = !!editCreator;
  const [form, setForm] = useState({
    name: editCreator?.name || '',
    creator_code: editCreator?.creator_code || '',
    login_email: editCreator?.login_email || '',
    login_password: '',
    // SESI #34 — tipe kreator & domisili. Kreator tipe `new` BELUM punya akun portal (input manual dari portal
    // marketing), jadi email/password boleh kosong untuk tipe ini.
    creator_type: editCreator?.creator_type || 'new',
    domicile: editCreator?.domicile || '',
    domicile_detail: editCreator?.domicile_detail || '',
    phone: editCreator?.phone || '',
    platforms: editCreator?.platforms || {},
    assigned_account_ids: editCreator?.assigned_account_ids || [],
    kpi_targets: editCreator?.kpi_targets || { monthly_revenue: 0, monthly_sessions: 0, monthly_viewers: 0 },
    notes: editCreator?.notes || '',
  });
  const [saving, setSaving] = useState(false);
  const [galat, setGalat] = useState('');

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));
  const setKpi = (k, v) => setForm(f => ({ ...f, kpi_targets: { ...f.kpi_targets, [k]: Number(v) } }));
  const setPlatform = (k, v) => setForm(f => ({ ...f, platforms: { ...f.platforms, [k]: v } }));
  const toggleAccount = (id) => {
    const ids = form.assigned_account_ids.includes(id)
      ? form.assigned_account_ids.filter(x => x !== id)
      : [...form.assigned_account_ids, id];
    set('assigned_account_ids', ids);
  };

  async function handleSubmit() {
    setGalat('');
    if (!form.name || !form.creator_code) { setGalat('Nama dan kode kreator wajib diisi.'); return; }
    // Akun portal hanya wajib untuk kreator kontrak/lanjutan; bila email diisi, sandi harus ada.
    if (form.creator_type !== 'new' && !form.login_email) { setGalat('Kreator kontrak/lanjutan butuh email login untuk akses portal.'); return; }
    if (!isEdit && form.login_email && !form.login_password) { setGalat('Email diisi — sandi wajib minimal 6 karakter.'); return; }
    setSaving(true);
    try {
      const url = isEdit ? `${API}/api/marketing/kol/creators/${editCreator.id}` : `${API}/api/marketing/kol/creators`;
      const method = isEdit ? 'PUT' : 'POST';
      const body = { ...form };
      if (isEdit && !body.login_password) delete body.login_password;
      const r = await fetch(url, { method, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Gagal menyimpan');
      toast.success(isEdit ? 'Kreator disimpan.' : 'Kreator dibuat.');
      onSaved();
    } catch (err) { setGalat(err.message); }
    finally { setSaving(false); }
  }

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" judul={isEdit ? 'Ubah kreator' : 'Tambah kreator baru'}
      onSimpan={handleSubmit} menyimpan={saving} galat={galat} labelSimpan={isEdit ? 'Simpan perubahan' : 'Buat kreator'}
      testId="creator-form">
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Nama kreator" wajib htmlFor="cr-name">
          <Input id="cr-name" data-testid="creator-name-input" value={form.name} onChange={e => set('name', e.target.value)} placeholder="Nama lengkap" />
        </Isian>
        <Isian label="Kode kreator" wajib htmlFor="cr-code">
          <Input id="cr-code" data-testid="creator-code-input" value={form.creator_code} onChange={e => set('creator_code', e.target.value)} placeholder="KOL-001" />
        </Isian>
        <Isian label="Tipe kreator" wajib htmlFor="cr-type">
          <SmartNativeSelect id="cr-type" data-testid="creator-type-select" value={form.creator_type} searchable={false}
            onChange={e => set('creator_type', e.target.value)}>
            <option value="new">Kreator baru (tanpa akun portal)</option>
            <option value="kontrak">Kreator kontrak (dapat insentif)</option>
            <option value="continue">Kreator lanjutan (dapat insentif)</option>
          </SmartNativeSelect>
        </Isian>
        <Isian label="Domisili (kota/kab.)" htmlFor="cr-dom">
          <Input id="cr-dom" data-testid="creator-domicile-input" value={form.domicile} onChange={e => set('domicile', e.target.value)} placeholder="Bandung" />
        </Isian>
      </div>
      <Isian label="Alamat domisili" htmlFor="cr-dom-det">
        <Input id="cr-dom-det" data-testid="creator-domicile-detail-input" value={form.domicile_detail}
          onChange={e => set('domicile_detail', e.target.value)} placeholder="Kec. Coblong, Jl. ..." />
      </Isian>
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Email login" wajib={form.creator_type !== 'new'} petunjuk={form.creator_type === 'new' ? 'Opsional untuk kreator baru.' : undefined} htmlFor="cr-email">
          <Input id="cr-email" data-testid="creator-email-input" type="email" value={form.login_email} onChange={e => set('login_email', e.target.value)} placeholder="kreator@email.com" />
        </Isian>
        <Isian label={isEdit ? 'Sandi baru' : 'Sandi'} wajib={!isEdit && !!form.login_email}
          petunjuk={isEdit ? 'Kosongkan bila tidak diubah.' : 'Minimal 6 karakter.'} htmlFor="cr-pass">
          <Input id="cr-pass" data-testid="creator-password-input" type="password" value={form.login_password} onChange={e => set('login_password', e.target.value)} />
        </Isian>
        <Isian label="Nomor HP" htmlFor="cr-phone">
          <Input id="cr-phone" value={form.phone} onChange={e => set('phone', e.target.value)} placeholder="08…" />
        </Isian>
        <Isian label="Akun TikTok" htmlFor="cr-tt">
          <Input id="cr-tt" value={form.platforms?.tiktok || ''} onChange={e => setPlatform('tiktok', e.target.value)} placeholder="@nama" />
        </Isian>
        <Isian label="Akun Shopee" htmlFor="cr-sp">
          <Input id="cr-sp" value={form.platforms?.shopee || ''} onChange={e => setPlatform('shopee', e.target.value)} placeholder="@nama" />
        </Isian>
      </div>
      <p className="border-t border-[var(--glass-border)] pt-3 text-sm font-medium">Target KPI bulanan</p>
      <div className="grid gap-4 sm:grid-cols-3">
        <Isian label="Omzet (Rp)">
          <MoneyInput value={form.kpi_targets.monthly_revenue} onChange={e => setKpi('monthly_revenue', e.target.value)} />
        </Isian>
        <Isian label="Sesi live" htmlFor="cr-kpi-s">
          <Input id="cr-kpi-s" type="number" value={form.kpi_targets.monthly_sessions} onChange={e => setKpi('monthly_sessions', e.target.value)} />
        </Isian>
        <Isian label="Total penonton" htmlFor="cr-kpi-v">
          <Input id="cr-kpi-v" type="number" value={form.kpi_targets.monthly_viewers} onChange={e => setKpi('monthly_viewers', e.target.value)} />
        </Isian>
      </div>
      <Isian label="Toko yang ditugaskan">
        <div className="flex flex-wrap gap-1.5">
          {accounts.map(acc => {
            const aktif = form.assigned_account_ids.includes(acc.id);
            return (
              <Button key={acc.id} type="button" size="sm" variant={aktif ? 'default' : 'outline'} aria-pressed={aktif}
                onClick={() => toggleAccount(acc.id)}>{acc.account_name}</Button>
            );
          })}
        </div>
      </Isian>
      <Isian label="Catatan" htmlFor="cr-notes">
        <Textarea id="cr-notes" value={form.notes} onChange={e => set('notes', e.target.value)} rows={2} />
      </Isian>
    </FormPopup>
  );
}

// ─── Form sesi live ─────────────────────────────────────────────────────────
function SessionFormModal({ token, creators, accounts, onClose, onSaved }) {
  const [form, setForm] = useState({
    creator_id: '', account_id: '', date: todayWIB(),
    platform: 'tiktokshop', session_name: '', duration_minutes: 90,
    viewers: 0, peak_viewers: 0, revenue: 0, orders: 0, notes: '',
  });
  const [saving, setSaving] = useState(false);
  const [galat, setGalat] = useState('');
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  // Akun hanya yang ditugaskan ke kreator terpilih
  const selectedCreator = creators.find(c => c.id === form.creator_id);
  const assignedIds = selectedCreator?.assigned_account_ids || [];
  const availableAccounts = assignedIds.length > 0 ? accounts.filter(a => assignedIds.includes(a.id)) : accounts;

  useEffect(() => {
    if (form.account_id && availableAccounts.length > 0 && !availableAccounts.find(a => a.id === form.account_id)) {
      set('account_id', '');
    }
  }, [form.creator_id]); // eslint-disable-line

  async function handleSubmit() {
    setGalat('');
    if (!form.creator_id || !form.account_id) { setGalat('Pilih kreator dan akun toko.'); return; }
    setSaving(true);
    try {
      const r = await fetch(`${API}/api/marketing/kol/sessions`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...form, viewers: Number(form.viewers), peak_viewers: Number(form.peak_viewers), revenue: Number(form.revenue), orders: Number(form.orders), duration_minutes: Number(form.duration_minutes) }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Gagal menyimpan');
      toast.success('Sesi live dicatat.');
      onSaved();
    } catch (err) { setGalat(err.message); }
    finally { setSaving(false); }
  }

  const akunTerpilih = accounts.find(x => x.id === form.account_id);
  return (
    <FormPopup open onClose={onClose} ukuran="panjang" judul="Catat sesi live" onSimpan={handleSubmit} menyimpan={saving}
      galat={galat} labelSimpan="Catat sesi" testId="session-form">
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Kreator" wajib htmlFor="ss-creator">
          <SmartNativeSelect id="ss-creator" value={form.creator_id} onChange={e => set('creator_id', e.target.value)}>
            <option value="">Pilih kreator</option>
            {creators.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Akun toko" wajib htmlFor="ss-acc"
          petunjuk={form.creator_id && assignedIds.length === 0 ? 'Kreator belum ditugaskan ke toko mana pun.' : akunTerpilih ? `Dicatat ke: ${akunTerpilih.account_name}` : undefined}>
          <SmartNativeSelect id="ss-acc" value={form.account_id} onChange={e => set('account_id', e.target.value)}>
            <option value="">Pilih akun</option>
            {availableAccounts.map(a => <option key={a.id} value={a.id}>{`${a.account_name} (${labelPlatform(a.platform)})`}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Tanggal">
          <DatePicker value={form.date} onChange={(v) => set('date', v)} testId="session-date" />
        </Isian>
        <Isian label="Platform">
          <p className="flex h-9 items-center text-sm text-muted-foreground" data-testid="session-platform-readonly">
            {akunTerpilih ? labelPlatform(akunTerpilih.platform) : 'Otomatis dari akun'}
          </p>
        </Isian>
        <Isian label="Durasi (menit)" htmlFor="ss-dur">
          <Input id="ss-dur" type="number" value={form.duration_minutes} onChange={e => set('duration_minutes', e.target.value)} />
        </Isian>
        <Isian label="Nama sesi" htmlFor="ss-name">
          <Input id="ss-name" value={form.session_name} onChange={e => set('session_name', e.target.value)} placeholder="Live flash sale" />
        </Isian>
        <Isian label="Omzet (Rp)">
          <MoneyInput value={form.revenue} onChange={e => set('revenue', e.target.value)} />
        </Isian>
        <Isian label="Pesanan" htmlFor="ss-ord">
          <Input id="ss-ord" type="number" value={form.orders} onChange={e => set('orders', e.target.value)} />
        </Isian>
        <Isian label="Penonton" htmlFor="ss-view">
          <Input id="ss-view" type="number" value={form.viewers} onChange={e => set('viewers', e.target.value)} />
        </Isian>
        <Isian label="Penonton puncak" htmlFor="ss-peak">
          <Input id="ss-peak" type="number" value={form.peak_viewers} onChange={e => set('peak_viewers', e.target.value)} />
        </Isian>
      </div>
    </FormPopup>
  );
}

// ─── Modul ──────────────────────────────────────────────────────────────────
export default function KOLCreatorModule({ token }) {
  const [tab, setTab] = useState('creators');
  const [creators, setCreators] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [requests, setRequests] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [leaderboard, setLeaderboard] = useState([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const { activeAccount: activeAccountCtx, setActiveAccount: setActiveAccountCtx } = useActiveMarketingAccount();
  const filterAccountId = activeAccountCtx?.id || '';
  const setFilterAccountId = (id) => {
    const acc = accounts.find(a => a.id === id);
    setActiveAccountCtx(acc || null);
  };
  const [showCreatorForm, setShowCreatorForm] = useState(false);
  const [editCreator, setEditCreator] = useState(null);
  const [detailCreator, setDetailCreator] = useState(null);
  // SESI #34 — insentif per kreator (konfigurasi + tracker pcs) & pembuatan akun portal.
  const [incentiveCreator, setIncentiveCreator] = useState(null);
  const [showSessionForm, setShowSessionForm] = useState(false);
  const [leaderMonth, setLeaderMonth] = useState(() => thisMonthWIB());
  const [creatorTargets, setCreatorTargets] = useState({});
  const [creatorPage, setCreatorPage] = useState(1);
  const [creatorPagination, setCreatorPagination] = useState(null);
  const [requestPage, setRequestPage] = useState(1);
  const [requestPagination, setRequestPagination] = useState(null);
  const ITEMS_PER_PAGE = 10;

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  const load = useCallback(async () => {
    setLoading(true);
    const [cy, cm] = thisMonthWIB().split('-').map(Number);
    try {
      const [crRes, ac, sess, reqs, lb, tgtsRaw] = await Promise.all([
        fetch(`${API}/api/marketing/kol/creators?page=${creatorPage}&limit=${ITEMS_PER_PAGE}`, { headers }).then(r => r.json()),
        fetch(`${API}/api/marketing/accounts`, { headers }).then(r => r.json()),
        fetch(`${API}/api/marketing/kol/sessions`, { headers }).then(r => r.json()),
        fetch(`${API}/api/marketing/kol/requests?page=${requestPage}&limit=${ITEMS_PER_PAGE}`, { headers }).then(r => r.json()),
        fetch(`${API}/api/marketing/kol/leaderboard?month=${leaderMonth}`, { headers }).then(r => r.json()),
        fetch(`${API}/api/marketing/targets/creator?year=${cy}&month=${cm}`, { headers }).then(r => r.ok ? r.json() : []),
      ]);
      if (crRes?.creators) {
        setCreators(crRes.creators);
        setCreatorPagination(crRes.pagination || null);
      } else {
        setCreators(Array.isArray(crRes) ? crRes : []);
        setCreatorPagination(null);
      }
      if (reqs?.requests) {
        setRequests(reqs.requests);
        setRequestPagination(reqs.pagination || null);
      } else {
        setRequests(Array.isArray(reqs) ? reqs : []);
        setRequestPagination(null);
      }
      setAccounts(Array.isArray(ac) ? ac.filter(a => a.status === 'active') : []);
      setSessions(Array.isArray(sess) ? sess : []);
      setLeaderboard(lb?.leaderboard || []);
      const tMap = {};
      if (Array.isArray(tgtsRaw)) tgtsRaw.forEach(t => { tMap[t.creator_id] = t; });
      setCreatorTargets(tMap);
    } catch (err) { toast.error('Gagal memuat data'); }
    finally { setLoading(false); }
  }, [headers, leaderMonth, creatorPage, requestPage]);

  useEffect(() => { load(); }, [load]);

  async function handleApproveRequest(id) {
    try {
      const r = await fetch(`${API}/api/marketing/kol/requests/${id}/approve`, { method: 'POST', headers });
      if (!r.ok) throw new Error((await r.json()).detail);
      toast.success('Permintaan disetujui.');
      load();
    } catch (err) { toast.error(err.message); }
  }
  async function handleRejectRequest(id) {
    const reason = await confirmDialog({ title: 'Tolak permintaan ini?', confirmLabel: 'Tolak', danger: true, input: { label: 'Alasan penolakan' } });
    if (!reason) return;
    try {
      const r = await fetch(`${API}/api/marketing/kol/requests/${id}/reject?reason=${encodeURIComponent(reason)}`, { method: 'POST', headers });
      if (!r.ok) throw new Error((await r.json()).detail);
      toast.success('Permintaan ditolak.');
      load();
    } catch (err) { toast.error(err.message); }
  }
  async function handleDeleteSession(id) {
    if (!(await confirmDialog({ title: 'Hapus sesi ini?', body: 'Catatan sesi live dihapus.', confirmLabel: 'Hapus', danger: true }))) return;
    try {
      const r = await fetch(`${API}/api/marketing/kol/sessions/${id}`, { method: 'DELETE', headers });
      if (!r.ok) throw new Error((await r.json()).detail);
      toast.success('Sesi dihapus.');
      load();
    } catch (err) { toast.error(err.message); }
  }
  async function handleDeactivateCreator(id) {
    if (!(await confirmDialog({ title: 'Nonaktifkan kreator ini?', body: 'Kreator tidak tampil lagi di daftar aktif.', confirmLabel: 'Nonaktifkan', danger: true }))) return;
    try {
      const r = await fetch(`${API}/api/marketing/kol/creators/${id}`, { method: 'DELETE', headers });
      if (!r.ok) throw new Error((await r.json()).detail);
      toast.success('Kreator dinonaktifkan.');
      setDetailCreator(null);
      load();
    } catch (err) { toast.error(err.message); }
  }

  const filteredCreators = creators.filter(c => {
    const matchSearch = !search || c.name.toLowerCase().includes(search.toLowerCase()) || c.creator_code.toLowerCase().includes(search.toLowerCase());
    const matchStatus = !filterStatus || c.status === filterStatus;
    const matchAccount = !filterAccountId || (c.assigned_account_ids || []).includes(filterAccountId);
    return matchSearch && matchStatus && matchAccount;
  });
  const pendingRequests = requests.filter(r => r.status === 'pending');
  const { page, setPage, totalPages, total, paged } = useClientPagination(sessions, 10);
  const namaAkun = (id) => accounts.find(a => a.id === id)?.account_name;
  const targetDari = (c) => {
    const mt = creatorTargets[c.id];
    return {
      rev: mt?.revenue_target || c.kpi_targets?.monthly_revenue || 0,
      sess: mt?.sessions_target || c.kpi_targets?.monthly_sessions || 0,
      view: mt?.viewers_target || 0,
      bulanan: !!mt,
    };
  };
  const adaAktivitas = leaderboard.some((e) => (e.total_revenue || 0) > 0 || (e.total_sessions || 0) > 0);

  const TAMPILAN = [
    { key: 'creators', label: 'Daftar kreator', icon: Users },
    { key: 'performance', label: 'Performa live', icon: Video },
    { key: 'catalog', label: pendingRequests.length ? `Permintaan produk (${pendingRequests.length})` : 'Permintaan produk', icon: ShoppingBag },
    { key: 'leaderboard', label: 'Peringkat', icon: Trophy },
    { key: 'weekly', label: 'Rapor mingguan', icon: BarChart2 },
  ];

  const kolomKreator = [
    { kunci: 'nama', label: 'Kreator', hp: 'judul', isi: (c) => (
      <span data-testid="creator-card"><span className="font-medium">{c.name}</span>
        <span className="block text-xs text-muted-foreground">{c.creator_code} · {TIPE[c.creator_type || 'new'] || 'Kreator'}</span></span>) },
    { kunci: 'toko', label: 'Toko', isi: (c) => (
      <span className="text-sm">{(c.assigned_account_ids || []).map(namaAkun).filter(Boolean).join(', ') || <span className="text-muted-foreground">Belum ditugaskan</span>}</span>) },
    { kunci: 'sesi', label: 'Sesi bulan ini', rata: 'kanan', isi: (c) => <span className="tabular-nums">{fmt(c.this_month?.sessions)}</span> },
    { kunci: 'omzet', label: 'Omzet bulan ini', rata: 'kanan', isi: (c) => <span className="tabular-nums md:whitespace-nowrap">{fmtRp(c.this_month?.revenue)}</span> },
    { kunci: 'target', label: 'Target omzet', isi: (c) => {
      const t = targetDari(c);
      if (!t.rev) return <span className="text-muted-foreground">—</span>;
      const pct = Math.min(100, Math.round(((c.this_month?.revenue || 0) / t.rev) * 100));
      return <div className="min-w-[7rem] space-y-1"><span className="text-xs tabular-nums">{pct}% dari {fmtRp(t.rev)}</span><Progress value={pct} className="h-1.5" /></div>;
    } },
    { kunci: 'portal', label: 'Akun portal', isi: (c) => (c.login_email
      ? <StatusBadge status="siap" label="Siap" tone="success" />
      : <span data-testid={`creator-no-portal-${c.creator_code}`}><StatusBadge status="belum" label="Belum ada" tone="warning" /></span>) },
    { kunci: 'status', label: 'Status', isi: (c) => <Lencana s={c.status} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (c) => (
      <div className="flex justify-end gap-1">
        <Button size="icon-sm" variant="ghost" data-testid="edit-creator-btn" title="Ubah kreator" aria-label="Ubah kreator"
          onClick={() => { setEditCreator(c); setShowCreatorForm(true); }}><Pencil /></Button>
        <Button size="sm" variant="outline" data-testid={`creator-incentive-btn-${c.creator_code}`} onClick={() => setIncentiveCreator(c)}><Target />Insentif</Button>
      </div>) },
  ];
  const kolomSesi = [
    { kunci: 'tgl', label: 'Tanggal', hp: 'keterangan', isi: (s) => <span className="tabular-nums md:whitespace-nowrap" data-testid="session-row">{tgl(s.date)}</span> },
    { kunci: 'kreator', label: 'Kreator', hp: 'judul', isi: (s) => <span className="font-medium">{s.creator_name}</span> },
    { kunci: 'akun', label: 'Toko', isi: (s) => s.account_name || '—' },
    { kunci: 'durasi', label: 'Durasi', rata: 'kanan', isi: (s) => `${fmt(s.duration_minutes)} menit` },
    { kunci: 'penonton', label: 'Penonton', rata: 'kanan', isi: (s) => <span className="tabular-nums">{fmt(s.viewers)}</span> },
    { kunci: 'omzet', label: 'Omzet', rata: 'kanan', isi: (s) => <span className="tabular-nums font-medium md:whitespace-nowrap">{fmtRp(s.revenue)}</span> },
    { kunci: 'pesanan', label: 'Pesanan', rata: 'kanan', isi: (s) => <span className="tabular-nums">{fmt(s.orders)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (s) => (
      <Button size="icon-sm" variant="ghost" className="text-[hsl(var(--danger-text))]" onClick={() => handleDeleteSession(s.id)} title="Hapus sesi" aria-label="Hapus sesi"><Trash2 /></Button>) },
  ];
  const kolomPermintaan = [
    { kunci: 'kreator', label: 'Kreator', hp: 'judul', isi: (r) => <span className="font-medium" data-testid="request-row">{r.creator_name}</span> },
    { kunci: 'produk', label: 'Produk', isi: (r) => <span>{r.product_name}<span className="block text-xs text-muted-foreground">{r.sku}</span></span> },
    { kunci: 'qty', label: 'Qty', rata: 'kanan', isi: (r) => `${fmt(r.quantity_requested)} pcs` },
    { kunci: 'stok', label: 'Stok sekarang', rata: 'kanan', isi: (r) => (
      <span className={r.current_stock >= r.quantity_requested ? '' : 'text-[hsl(var(--danger-text))]'}>{fmt(r.current_stock)} pcs
        <span className="block text-xs text-muted-foreground">saat diminta {fmt(r.stock_at_request)}</span></span>) },
    { kunci: 'tujuan', label: 'Tujuan', isi: (r) => <span className="text-sm text-muted-foreground">{r.purpose || '—'}</span> },
    { kunci: 'status', label: 'Status', isi: (r) => <Lencana s={r.status} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (r.status === 'pending' ? (
      <div className="flex justify-end gap-1">
        <Button size="sm" variant="success" data-testid="approve-request-btn" onClick={() => handleApproveRequest(r.id)}><Check />Setujui</Button>
        <Button size="sm" variant="destructive" data-testid="reject-request-btn" onClick={() => handleRejectRequest(r.id)}><X />Tolak</Button>
      </div>) : <span className="text-xs text-muted-foreground">{r.reviewed_by ? `oleh ${r.reviewed_by}` : ''}</span>) },
  ];
  const kolomPeringkat = [
    { kunci: 'rank', label: 'Peringkat', rata: 'tengah', isi: (e) => <span className="font-semibold tabular-nums" data-testid="leaderboard-row">{adaAktivitas ? e.rank : '—'}</span> },
    { kunci: 'nama', label: 'Kreator', hp: 'judul', isi: (e) => <span className="font-medium">{e.name}<span className="block text-xs font-normal text-muted-foreground">{e.creator_code}</span></span> },
    { kunci: 'sesi', label: 'Sesi', rata: 'kanan', isi: (e) => <span className="tabular-nums">{fmt(e.total_sessions)}</span> },
    { kunci: 'penonton', label: 'Penonton', rata: 'kanan', isi: (e) => <span className="tabular-nums">{fmt(e.total_viewers)}</span> },
    { kunci: 'pesanan', label: 'Pesanan', rata: 'kanan', isi: (e) => <span className="tabular-nums">{fmt(e.total_orders)}</span> },
    { kunci: 'omzet', label: 'Omzet', rata: 'kanan', isi: (e) => <span className="tabular-nums font-medium md:whitespace-nowrap">{fmtRp(e.total_revenue)}</span> },
    { kunci: 'target', label: 'Dari target', rata: 'kanan', isi: (e) => (e.kpi_revenue_pct === null || e.kpi_revenue_pct === undefined
      ? <span className="text-muted-foreground">—</span>
      : <span className={`tabular-nums ${e.kpi_revenue_pct >= 100 ? 'text-[hsl(var(--success-text))]' : e.kpi_revenue_pct >= 50 ? 'text-[hsl(var(--warning-text))]' : 'text-[hsl(var(--danger-text))]'}`}>{e.kpi_revenue_pct}%</span>) },
  ];

  const unduh = {
    creators: { nama: 'kreator-kol', baris: filteredCreators, kolom: [
      { label: 'Nama', nilai: (c) => c.name }, { label: 'Kode', nilai: (c) => c.creator_code },
      { label: 'Tipe', nilai: (c) => TIPE[c.creator_type || 'new'] || '' }, { label: 'Domisili', nilai: (c) => c.domicile || '' },
      { label: 'Nomor HP', nilai: (c) => c.phone || '' }, { label: 'Email login', nilai: (c) => c.login_email || '' },
      { label: 'Toko', nilai: (c) => (c.assigned_account_ids || []).map(namaAkun).filter(Boolean).join(', ') },
      { label: 'Sesi bulan ini', nilai: (c) => c.this_month?.sessions || 0 }, { label: 'Omzet bulan ini', nilai: (c) => c.this_month?.revenue || 0 },
      { label: 'Penonton bulan ini', nilai: (c) => c.this_month?.viewers || 0 }, { label: 'Target omzet', nilai: (c) => targetDari(c).rev || '' },
      { label: 'Status', nilai: (c) => (STATUS[c.status] || [c.status])[0] }] },
    performance: { nama: 'sesi-live-kreator', baris: sessions, kolom: [
      { label: 'Tanggal', nilai: (s) => tgl(s.date) }, { label: 'Kreator', nilai: (s) => s.creator_name }, { label: 'Toko', nilai: (s) => s.account_name || '' },
      { label: 'Durasi (menit)', nilai: (s) => Number(s.duration_minutes) || 0 }, { label: 'Penonton', nilai: (s) => Number(s.viewers) || 0 },
      { label: 'Penonton puncak', nilai: (s) => Number(s.peak_viewers) || 0 }, { label: 'Omzet', nilai: (s) => Number(s.revenue) || 0 },
      { label: 'Pesanan', nilai: (s) => Number(s.orders) || 0 }] },
    catalog: { nama: 'permintaan-produk-kreator', baris: requests, kolom: [
      { label: 'Kreator', nilai: (r) => r.creator_name }, { label: 'Produk', nilai: (r) => r.product_name }, { label: 'SKU', nilai: (r) => r.sku || '' },
      { label: 'Qty', nilai: (r) => Number(r.quantity_requested) || 0 }, { label: 'Stok saat diminta', nilai: (r) => Number(r.stock_at_request) || 0 },
      { label: 'Stok sekarang', nilai: (r) => Number(r.current_stock) || 0 }, { label: 'Tujuan', nilai: (r) => r.purpose || '' },
      { label: 'Status', nilai: (r) => (STATUS[r.status] || [r.status])[0] }, { label: 'Ditinjau oleh', nilai: (r) => r.reviewed_by || '' }] },
    leaderboard: { nama: `peringkat-kreator-${leaderMonth}`, baris: leaderboard, kolom: [
      { label: 'Peringkat', nilai: (e) => (adaAktivitas ? e.rank : '') }, { label: 'Kreator', nilai: (e) => e.name }, { label: 'Kode', nilai: (e) => e.creator_code },
      { label: 'Sesi', nilai: (e) => e.total_sessions || 0 }, { label: 'Penonton', nilai: (e) => e.total_viewers || 0 },
      { label: 'Pesanan', nilai: (e) => e.total_orders || 0 }, { label: 'Omzet', nilai: (e) => e.total_revenue || 0 },
      { label: 'Persen target', nilai: (e) => e.kpi_revenue_pct ?? '' }] },
  }[tab];

  return (
    <PageLayout testId="kol-creator-module" title="Kelola KOL"
      subtitle="Kreator, performa live, permintaan produk, peringkat, dan rapor mingguan."
      actions={tab === 'creators'
        ? <Button data-testid="add-creator-btn" onClick={() => { setEditCreator(null); setShowCreatorForm(true); }}><UserPlus />Tambah kreator</Button>
        : tab === 'performance'
          ? <Button data-testid="add-session-btn" onClick={() => setShowSessionForm(true)}><Plus />Catat sesi</Button>
          : null}
      filters={<>
        <FilterChips options={TAMPILAN} value={tab} onChange={setTab} hideWhenEmpty={false} testId="kol-view" ariaLabel="Tampilan" />
        {tab === 'creators' && <>
          <div className="relative w-full sm:w-56">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input data-testid="creator-search" value={search} onChange={e => setSearch(e.target.value)} className="pl-8" placeholder="Cari kreator" />
          </div>
          <SmartNativeSelect value={filterAccountId} onChange={(e) => setFilterAccountId(e.target.value)} className="w-48" data-testid="creator-account-filter">
            <option value="">Semua toko</option>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
          </SmartNativeSelect>
          <SmartNativeSelect value={filterStatus} onChange={e => setFilterStatus(e.target.value)} className="w-36" searchable={false}>
            <option value="">Semua status</option>
            <option value="active">Aktif</option>
            <option value="inactive">Nonaktif</option>
          </SmartNativeSelect>
        </>}
        {tab === 'leaderboard' && (
          <SmartNativeSelect value={leaderMonth} onChange={(e) => setLeaderMonth(e.target.value)} className="w-44" searchable={false} data-testid="leader-month">
            {monthOptions(24).map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </SmartNativeSelect>
        )}
      </>}
      tools={unduh && (
        <TombolUnduh namaBerkas={unduh.nama} namaLembar="Data" baris={unduh.baris} kolom={unduh.kolom} testId={`kol-unduh-${tab}`} />
      )}>
      {loading && <p className="py-6 text-center text-sm text-muted-foreground">Memuat data…</p>}

      {/* ═══ DAFTAR KREATOR ═══ */}
      {!loading && tab === 'creators' && (
        <>
          <TabelData kolom={kolomKreator} baris={filteredCreators} onKlikBaris={setDetailCreator} testId="creator-table"
            kosong={<EmptyState icon={Users} title="Belum ada kreator" description='Klik "Tambah kreator" untuk memulai, atau ubah penyaring.' />} />
          {creatorPagination && <PaginationBar pagination={creatorPagination} onPageChange={(p) => setCreatorPage(p)} />}
        </>
      )}

      {/* ═══ PERFORMA LIVE ═══ */}
      {!loading && tab === 'performance' && (
        <>
          <TabelData kolom={kolomSesi} baris={paged} testId="session-table"
            kosong={<EmptyState icon={Video} title="Belum ada sesi live" description='Klik "Catat sesi" untuk mulai.' />} />
          {sessions.length > 10 && <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />}
        </>
      )}

      {/* ═══ PERMINTAAN PRODUK ═══ */}
      {!loading && tab === 'catalog' && (
        <>
          <p className="text-base font-semibold">Semua permintaan · {requestPagination ? requestPagination.total : requests.length}
            {pendingRequests.length > 0 && <span className="ml-2 text-sm font-normal text-[hsl(var(--warning-text))]">{pendingRequests.length} menunggu persetujuan di halaman ini</span>}
          </p>
          <TabelData kolom={kolomPermintaan} baris={requests} testId="request-table"
            kosong={<EmptyState icon={ShoppingBag} title="Belum ada permintaan dari kreator" />} />
          {requestPagination && <PaginationBar pagination={requestPagination} onPageChange={(p) => setRequestPage(p)} />}
          {/* Katalog — satu sumber (keputusan owner 4 Nov 2026) */}
          <div data-testid="kol-catalog-one-door">
            <Notice tone="info" icon={Package} title="Produk untuk kreator"
              action={<Button size="sm" variant="outline" onClick={() => { window.location.hash = '#marketing-catalog'; }}>Buka Manajemen Katalog</Button>}>
              Kreator melihat katalog toko yang ditugaskan kepadanya. Tambah, ubah, atau nonaktifkan produk di Manajemen Katalog.
            </Notice>
          </div>
        </>
      )}

      {/* ═══ RAPOR MINGGUAN ═══ */}
      {!loading && tab === 'weekly' && <CreatorWeeklyReportPanel token={token} />}

      {/* ═══ PERINGKAT ═══ */}
      {!loading && tab === 'leaderboard' && (
        <>
          {leaderboard.length > 0 && !adaAktivitas && (
            <Notice tone="info" title="Belum ada aktivitas bulan ini">Semua kreator masih 0 sesi dan 0 omzet, jadi urutan peringkat belum bermakna.</Notice>
          )}
          <TabelData kolom={kolomPeringkat} baris={leaderboard} kunci={(e) => e.creator_id} testId="leaderboard-table"
            kosong={<EmptyState icon={Trophy} title="Belum ada data performa untuk periode ini" />} />
        </>
      )}

      {/* Rincian kreator */}
      {detailCreator && (() => {
        const c = detailCreator;
        const t = targetDari(c);
        return (
          <DetailPopup open onClose={() => setDetailCreator(null)} judul={c.name} testId="creator-detail"
            status={<><Lencana s={c.status} /><span data-testid={`creator-type-badge-${c.creator_code}`}><StatusBadge status="tipe" label={TIPE[c.creator_type || 'new'] || 'Kreator'} tone="muted" /></span></>}
            keterangan={c.creator_code}
            aksi={<>
              <Button size="sm" variant="outline" onClick={() => { setDetailCreator(null); setEditCreator(c); setShowCreatorForm(true); }}><Pencil />Ubah</Button>
              <Button size="sm" variant="outline" onClick={() => { setDetailCreator(null); setIncentiveCreator(c); }}><Target />Insentif</Button>
              <Button size="sm" variant="destructive" onClick={() => handleDeactivateCreator(c.id)}><Trash2 />Nonaktifkan</Button>
            </>}>
            <dl className="divide-y divide-[var(--glass-border)]">
              <BarisDetail label="Toko">{(c.assigned_account_ids || []).map(namaAkun).filter(Boolean).join(', ') || 'Belum ditugaskan ke toko'}</BarisDetail>
              <BarisDetail label="Akun platform">{Object.entries(c.platforms || {}).filter(([, v]) => v).map(([k, v]) => `${labelPlatform(k)}: ${v}`).join(' · ') || '—'}</BarisDetail>
              <BarisDetail label="Domisili">{[c.domicile, c.domicile_detail].filter(Boolean).join(' — ') || '—'}</BarisDetail>
              <BarisDetail label="Nomor HP">{c.phone || '—'}</BarisDetail>
              <BarisDetail label="Akun portal">{c.login_email ? `Siap (${c.login_email})` : 'Belum ada akun portal'}</BarisDetail>
              <BarisDetail label="Bulan ini">{fmt(c.this_month?.sessions)} sesi · {fmtRp(c.this_month?.revenue)} · {fmt(c.this_month?.viewers)} penonton</BarisDetail>
            </dl>
            {(t.rev > 0 || t.sess > 0 || t.view > 0) && (
              <div className="space-y-2">
                <p className="text-sm font-medium">Target {t.bulanan ? 'bulanan' : 'umum'}</p>
                {t.rev > 0 && <KPIBar label="Omzet" value={c.this_month?.revenue || 0} target={t.rev} unit="Rp " />}
                {t.sess > 0 && <KPIBar label="Sesi" value={c.this_month?.sessions || 0} target={t.sess} />}
                {t.view > 0 && <KPIBar label="Penonton" value={c.this_month?.viewers || 0} target={t.view} />}
              </div>
            )}
          </DetailPopup>
        );
      })()}

      {incentiveCreator && (
        <CreatorIncentivePanel token={token} creator={incentiveCreator}
          onClose={() => { setIncentiveCreator(null); load(); }} />
      )}
      {showCreatorForm && (
        <CreatorFormModal token={token} accounts={accounts} editCreator={editCreator}
          onClose={() => { setShowCreatorForm(false); setEditCreator(null); }}
          onSaved={() => { setShowCreatorForm(false); setEditCreator(null); load(); }} />
      )}
      {showSessionForm && (
        <SessionFormModal token={token} creators={creators.filter(c => c.status === 'active')} accounts={accounts}
          onClose={() => setShowSessionForm(false)}
          onSaved={() => { setShowSessionForm(false); load(); }} />
      )}
    </PageLayout>
  );
}

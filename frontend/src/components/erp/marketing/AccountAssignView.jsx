/**
 * AccountAssignView — **ASSIGN TOKO (SPV)**: siapa memegang toko yang mana (F6.4 · F8).
 *
 * Kenapa layar ini ada: F6 sudah membatasi visibilitas per toko, tetapi kolom
 * `assigned_staff` sebelumnya HANYA bisa diubah lewat skrip seed. Artinya aturan
 * yang benar di kode tidak bisa dipakai di lapangan: staf baru tidak pernah bisa
 * diberi toko, dan staf yang pindah tugas tidak pernah bisa dicabut aksesnya.
 *
 * DILENGKAPI 2026-08-14 (F8) — tiga hal yang membuat layar ini bisa DIPAKAI, bukan
 * hanya ada:
 *
 *  1. **Tiga sudut pandang.** “Per Toko” menjawab *siapa pegang toko ini*;
 *     **“Per Staf”** menjawab *Rina pegang toko apa saja* (pertanyaan yang benar-benar
 *     diajukan saat rotasi shift) dan MENAMPILKAN staf yang memegang 0 toko — orang
 *     yang membuka aplikasi lalu melihat layar kosong tanpa penjelasan;
 *     **“Riwayat”** menjawab *apa yang berubah minggu ini* tanpa membuka 9 dialog.
 *  2. **Alasan WAJIB.** Tombol Simpan terkunci sampai alasan diisi. Alasan itulah
 *     satu-satunya yang menjawab “kenapa akses toko saya dicabut?” enam bulan lagi.
 *  3. **Akibat yang MENETAP di layar** (bukan toast 5 detik): staf yang dicabut
 *     langsung kehilangan akses, staf berakun NONAKTIF tidak bisa login sehingga
 *     tokonya praktis tidak dipegang siapa pun.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  RefreshCw, Users, History, Store, Info, UserPlus, Search, AlertTriangle, UserX, CheckCircle2,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup from '@/components/ui/detail-popup';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatDateTimeID } from '@/lib/format';
import { parseServerTime } from '@/lib/waktu';
import { Toolbar } from '../layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';
import { toast } from 'sonner';

const API = process.env.REACT_APP_BACKEND_URL;
const ROLE_LABEL = {
  staff_marketing: 'Staf Marketing', pic_toko: 'PIC Toko',
  host_live: 'Host Live', cs_staff: 'CS',
};
const MIN_REASON = 4;      // sama dengan penjaga backend (MIN_REASON)
const TABS = [['toko', 'Per toko'], ['staf', 'Per staf'], ['riwayat', 'Riwayat']];
const PLATFORM_LABEL = { shopee: 'Shopee', tiktok: 'TikTok Shop', tiktokshop: 'TikTok Shop', tokopedia: 'Tokopedia', lazada: 'Lazada' };
const labelPlatform = (p) => PLATFORM_LABEL[String(p || '').toLowerCase()] || p || '—';

// Stempel server tanpa zona = UTC → tampil WIB
const fmtWhen = (v) => formatDateTimeID(parseServerTime(v));

/**
 * Standar UI/UX v2 (8 Nov 2026): `view` ('toko' | 'staf' | 'riwayat') dikirim induk (Kelola akun) sebagai
 * tab halaman — dulu tab buatan sendiri di dalam tab "Assign Staf" (tab di dalam tab).
 */
export default function AccountAssignView({ token, view: viewProp }) {
  const [ownTab, setTab] = useState('toko');
  const tab = viewProp || ownTab;
  const [rows, setRows] = useState([]);
  const [options, setOptions] = useState([]);
  const [canEdit, setCanEdit] = useState(false);
  const [notes, setNotes] = useState([]);
  const [summary, setSummary] = useState({ unassigned: 0, stale: 0 });
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [onlyUnassigned, setOnlyUnassigned] = useState(false);

  const [editTarget, setEditTarget] = useState(null);     // toko yang sedang diubah
  const [picked, setPicked] = useState([]);
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [lastEffect, setLastEffect] = useState(null);     // {message, warnings[], note}

  const [historyFor, setHistoryFor] = useState(null);
  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  const [staffRows, setStaffRows] = useState([]);
  const [staffMeta, setStaffMeta] = useState({ without_account: [], ghost: [] });
  const [allHistory, setAllHistory] = useState([]);
  const [allHistoryPage, setAllHistoryPage] = useState(1);
  const [allHistoryTotal, setAllHistoryTotal] = useState(0);

  const headers = useMemo(
    () => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }),
    [token]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ov, op] = await Promise.all([
        fetch(`${API}/api/marketing/account-assign/overview`, { headers }),
        fetch(`${API}/api/marketing/account-assign/staff-options`, { headers }),
      ]);
      if (!ov.ok) throw new Error(`HTTP ${ov.status}`);
      const ovj = await ov.json();
      setRows(ovj.rows || []);
      setNotes(ovj.data_notes || []);
      setCanEdit(Boolean(ovj.can_edit));
      setSummary({ unassigned: ovj.unassigned_count || 0, stale: ovj.stale_count || 0 });
      if (op.ok) setOptions(((await op.json())?.options) || []);
    } catch (e) {
      toast.error(`Gagal memuat daftar pemegang toko: ${e.message}`);
      setRows([]);
    } finally { setLoading(false); }
  }, [headers]);

  const loadStaff = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/marketing/account-assign/by-staff`, { headers });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = await r.json();
      setStaffRows(j.rows || []);
      setStaffMeta({ without_account: j.without_account || [],
        ghost: j.ghost_staff_ids || [] });
    } catch (e) { toast.error(`Gagal memuat daftar per staf: ${e.message}`); }
  }, [headers]);

  const loadAllHistory = useCallback(async (page = 1) => {
    try {
      const r = await fetch(
        `${API}/api/marketing/account-assign/history?page=${page}&page_size=10`,
        { headers });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = await r.json();
      setAllHistory(j.rows || []);
      setAllHistoryTotal(j.pagination?.total || 0);
      setAllHistoryPage(j.pagination?.page || page);
    } catch (e) { toast.error(`Gagal memuat riwayat: ${e.message}`); }
  }, [headers]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (tab === 'staf') loadStaff(); }, [tab, loadStaff]);
  useEffect(() => { if (tab === 'riwayat') loadAllHistory(1); }, [tab, loadAllHistory]);

  const openEdit = (acc) => {
    setEditTarget(acc);
    setPicked((acc.assigned_staff || []).map((s) => s.id));
    setReason('');
  };

  const toggle = (id) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));

  const reasonOk = reason.trim().length >= MIN_REASON;

  const save = async () => {
    if (!editTarget || !reasonOk) return;
    setSaving(true);
    try {
      const res = await fetch(`${API}/api/marketing/account-assign/${editTarget.id}`, {
        method: 'POST', headers,
        body: JSON.stringify({ staff_ids: picked, reason: reason.trim() }),
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(j?.detail || `HTTP ${res.status}`);
      // Akibat perubahan DITAHAN di layar. Peringatan seperti "akun staf ini
      // NONAKTIF" atau "toko ini sekarang tidak dipegang siapa pun" adalah
      // pekerjaan lanjutan — mustahil dikerjakan dari toast yang hilang 5 detik.
      setLastEffect({
        account: editTarget.account_name,
        message: j.message || 'Pemegang toko diperbarui',
        warnings: j.warnings || [],
        note: j.effect_note || '',
        reason: j.reason || reason.trim(),
      });
      toast.success(j.message || 'Pemegang toko diperbarui');
      setEditTarget(null);
      load();
      if (tab === 'staf') loadStaff();
      if (tab === 'riwayat') loadAllHistory(1);
    } catch (e) {
      toast.error(`Gagal menyimpan: ${e.message}`);
    } finally { setSaving(false); }
  };

  const openHistory = async (acc) => {
    setHistoryFor(acc);
    setHistoryLoading(true);
    try {
      const res = await fetch(`${API}/api/marketing/account-assign/${acc.id}/history`, { headers });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setHistory(((await res.json())?.rows) || []);
    } catch (e) {
      toast.error(`Gagal memuat riwayat: ${e.message}`);
      setHistory([]);
    } finally { setHistoryLoading(false); }
  };

  /* ── daftar toko yang tampil: pencarian + filter + paginasi 10/hal ── */
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter((r) => {
      if (onlyUnassigned && (r.active_count ?? r.assigned_count) > 0) return false;
      if (!q) return true;
      const hay = `${r.account_name} ${r.account_code} ${r.platform} `
        + `${(r.assigned_staff || []).map((s) => s.name).join(' ')} ${r.pic?.name || ''}`;
      return hay.toLowerCase().includes(q);
    });
  }, [rows, query, onlyUnassigned]);

  const pg = useClientPagination(filtered, 10);
  const pgStaff = useClientPagination(staffRows, 10);

  const peran = (r) => ROLE_LABEL[r] || r || '—';
  const kolomToko = [
    { kunci: 'toko', label: 'Toko', hp: 'judul', isi: (r) => (
      <div className="min-w-0" data-testid={`assign-row-${r.id}`}>
        <p className="font-medium text-foreground">{r.account_name}</p>
        {r.account_code ? <p className="text-xs text-muted-foreground">{r.account_code}</p> : null}
      </div>) },
    { kunci: 'platform', label: 'Platform', hp: 'keterangan', isi: (r) => labelPlatform(r.platform) },
    { kunci: 'status', label: 'Status', isi: (r) => (
      <StatusBadge status={r.status} label={r.status === 'active' ? 'Aktif' : 'Nonaktif'} tone={r.status === 'active' ? 'success' : 'muted'} />) },
    { kunci: 'pic', label: 'PIC', isi: (r) => r.pic?.name || <span className="text-muted-foreground">—</span> },
    { kunci: 'staf', label: 'Staf pemegang', isi: (r) => ((r.assigned_staff || []).length === 0
      ? <span className="text-[hsl(var(--warning-text))]">Belum ada</span>
      : (
        <div className="flex flex-wrap gap-1">
          {r.assigned_staff.map((s) => (
            <span key={s.id} data-testid={`assign-staff-${r.id}-${s.id}`}>
              <StatusBadge status={s.inactive ? 'nonaktif' : 'aktif'} tone={s.inactive ? 'danger' : 'default'}
                label={`${s.name}${s.role ? ` · ${peran(s.role)}` : ''}${s.inactive ? ' · akun nonaktif' : ''}`} />
            </span>
          ))}
        </div>
      )) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <div className="flex items-center justify-end gap-1">
        <Button size="sm" variant="outline" disabled={!canEdit} onClick={() => openEdit(r)}
          data-testid={`assign-edit-btn-${r.id}`}>
          <UserPlus />Atur staf
        </Button>
        <Button size="sm" variant="ghost" onClick={() => openHistory(r)} data-testid={`assign-history-btn-${r.id}`}>
          <History />Riwayat
        </Button>
      </div>) },
  ];
  const kolomStaf = [
    { kunci: 'staf', label: 'Staf', hp: 'judul', isi: (s) => (
      <div className="min-w-0" data-testid={`assign-staff-row-${s.id}`}>
        <p className="font-medium text-foreground">{s.name}</p>
        <p className="text-xs text-muted-foreground">{s.email}</p>
      </div>) },
    { kunci: 'peran', label: 'Peran', isi: (s) => peran(s.role) },
    { kunci: 'akun', label: 'Akun login', isi: (s) => (
      <StatusBadge status={s.inactive ? 'nonaktif' : 'aktif'} label={s.inactive ? 'Nonaktif' : 'Aktif'} tone={s.inactive ? 'danger' : 'success'} />) },
    { kunci: 'jumlah', label: 'Jumlah toko', rata: 'kanan', isi: (s) => <span className="tabular-nums font-medium">{s.accounts_count}</span> },
    { kunci: 'toko', label: 'Toko yang dipegang', isi: (s) => (s.accounts_count === 0
      ? <span className="text-[hsl(var(--warning-text))]">Belum memegang toko — tidak melihat data apa pun</span>
      : <span className="text-sm">{s.accounts.map((a) => `${a.account_name}${a.as_pic ? ' (PIC)' : ''}`).join(', ')}</span>) },
  ];
  const kolomRiwayat = [
    { kunci: 'waktu', label: 'Waktu', isi: (h) => <span className="md:whitespace-nowrap" data-testid={`assign-allhistory-row-${h.id}`}>{fmtWhen(h.at)}</span> },
    { kunci: 'toko', label: 'Toko', hp: 'judul', isi: (h) => <span className="font-medium text-foreground">{h.account_name}</span> },
    { kunci: 'pelaku', label: 'Pelaku', isi: (h) => <span>{h.actor_name} <span className="text-muted-foreground">({h.actor_role})</span></span> },
    { kunci: 'tambah', label: 'Ditambah', isi: (h) => <span className="text-[hsl(var(--success-text))]">{(h.added_names || []).join(', ') || '—'}</span> },
    { kunci: 'cabut', label: 'Dicabut', isi: (h) => <span className="text-[hsl(var(--danger-text))]">{(h.removed_names || []).join(', ') || '—'}</span> },
    { kunci: 'alasan', label: 'Alasan', isi: (h) => <span className="text-muted-foreground">{h.reason || '—'}</span> },
  ];

  const ambilSemuaRiwayat = async () => {
    const out = [];
    for (let page = 1; page <= 50; page += 1) {
      const r = await fetch(`${API}/api/marketing/account-assign/history?page=${page}&page_size=100`, { headers });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = await r.json();
      out.push(...(j.rows || []));
      if (!(j.rows || []).length || out.length >= (j.pagination?.total || 0)) break;
    }
    return out;
  };

  const tombolMuat = (
    <Button variant="outline" size="icon" onClick={() => { load(); if (tab === 'staf') loadStaff(); if (tab === 'riwayat') loadAllHistory(1); }}
      disabled={loading} title="Muat ulang" aria-label="Muat ulang" data-testid="assign-refresh">
      <RefreshCw className={loading ? 'animate-spin' : ''} />
    </Button>
  );
  const lencanaBaca = !canEdit && (
    <span data-testid="assign-readonly-badge">
      <StatusBadge status="baca" label="Hanya lihat (butuh SPV/Manager)" tone="muted" />
    </span>
  );

  return (
    <div className="space-y-4" data-testid="account-assign-view">
      {/* Tanpa `view` dari induk: tiga sudut pandang sebagai tab di sini (kompat lama) */}
      {!viewProp && (
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList className="h-auto justify-start gap-1" data-testid="assign-tabs">
            {TABS.map(([v, l]) => <TabsTrigger key={v} value={v} data-testid={`assign-tab-${v}`}>{l}</TabsTrigger>)}
          </TabsList>
        </Tabs>
      )}

      {/* ════════════════ PER TOKO ════════════════ */}
      {tab === 'toko' && (
        <Toolbar
          filters={<>
            <div className="relative w-full sm:w-64">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={query} onChange={(e) => setQuery(e.target.value)} className="pl-8"
                placeholder="Cari toko, kode, platform, staf" data-testid="assign-search" />
            </div>
            <FilterChips value={onlyUnassigned ? 'belum' : ''} onChange={(v) => setOnlyUnassigned(v === 'belum')}
              hideWhenEmpty={false} testId="assign-filter"
              options={[
                { key: '', label: 'Semua toko', count: rows.length },
                { key: 'belum', label: 'Belum terpegang', count: rows.filter((r) => !((r.active_count ?? r.assigned_count) > 0)).length },
              ]} />
            {lencanaBaca}
          </>}
          tools={<>
            <TombolUnduh namaBerkas="pemegang-toko" namaLembar="Per toko" baris={filtered} testId="assign-unduh-toko"
              kolom={[
                { label: 'Toko', nilai: (r) => r.account_name }, { label: 'Kode', nilai: (r) => r.account_code || '' },
                { label: 'Platform', nilai: (r) => labelPlatform(r.platform) },
                { label: 'Status', nilai: (r) => (r.status === 'active' ? 'Aktif' : 'Nonaktif') },
                { label: 'PIC', nilai: (r) => r.pic?.name || '' },
                { label: 'Staf pemegang', nilai: (r) => (r.assigned_staff || []).map((s) => `${s.name}${s.inactive ? ' (akun nonaktif)' : ''}`).join(', ') },
              ]} />
            {tombolMuat}
          </>} />
      )}
      {tab === 'staf' && (
        <Toolbar
          filters={<>
            <p className="text-sm text-muted-foreground">Toko yang dipegang tiap staf (staf marketing, PIC toko, host live, CS).</p>
            {lencanaBaca}
          </>}
          tools={<>
            <TombolUnduh namaBerkas="pemegang-per-staf" namaLembar="Per staf" baris={staffRows} testId="assign-unduh-staf"
              kolom={[
                { label: 'Staf', nilai: (s) => s.name }, { label: 'Email', nilai: (s) => s.email || '' },
                { label: 'Peran', nilai: (s) => peran(s.role) },
                { label: 'Akun login', nilai: (s) => (s.inactive ? 'Nonaktif' : 'Aktif') },
                { label: 'Jumlah toko', nilai: (s) => s.accounts_count || 0 },
                { label: 'Toko yang dipegang', nilai: (s) => (s.accounts || []).map((a) => `${a.account_name}${a.as_pic ? ' (PIC)' : ''}`).join(', ') },
              ]} />
            {tombolMuat}
          </>} />
      )}
      {tab === 'riwayat' && (
        <Toolbar
          filters={<p className="text-sm text-muted-foreground">Setiap perubahan pemegang toko, lengkap dengan pelaku dan alasannya.</p>}
          tools={<>
            <TombolUnduh namaBerkas="riwayat-pemegang-toko" namaLembar="Riwayat" baris={allHistory} ambilSemua={ambilSemuaRiwayat}
              testId="assign-unduh-riwayat"
              kolom={[
                { label: 'Waktu', nilai: (h) => fmtWhen(h.at) }, { label: 'Toko', nilai: (h) => h.account_name },
                { label: 'Pelaku', nilai: (h) => `${h.actor_name || ''} (${h.actor_role || ''})` },
                { label: 'Ditambah', nilai: (h) => (h.added_names || []).join(', ') },
                { label: 'Dicabut', nilai: (h) => (h.removed_names || []).join(', ') },
                { label: 'Alasan', nilai: (h) => h.reason || '' },
              ]} />
            {tombolMuat}
          </>} />
      )}

      {/* akibat perubahan terakhir — MENETAP */}
      {lastEffect && (
        <Notice tone="success" icon={CheckCircle2} testId="assign-effect"
          title={`${lastEffect.account}: ${lastEffect.message}`}
          action={<Button size="sm" variant="ghost" onClick={() => setLastEffect(null)} data-testid="assign-effect-close">Tutup</Button>}>
          {lastEffect.reason ? <p>Alasan tercatat: “{lastEffect.reason}”</p> : null}
          {lastEffect.note ? <p>{lastEffect.note}</p> : null}
          {(lastEffect.warnings || []).map((w, i) => (
            <p key={i} className="flex items-start gap-1 text-[hsl(var(--warning-text))]" data-testid={`assign-effect-warning-${i}`}>
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {w}
            </p>
          ))}
        </Notice>
      )}

      {(summary.unassigned > 0 || summary.stale > 0) && !loading && tab === 'toko' && (
        <p className="flex items-start gap-1.5 text-sm text-[hsl(var(--warning-text))]" data-testid="assign-warning"
          title="Toko tanpa staf tetap terlihat oleh SPV/Manager, tetapi tidak ada staf yang bisa mengisi data hariannya. Toko yang pemegangnya nonaktif tampak sudah dipegang, padahal tidak ada yang bisa login.">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            {summary.unassigned} toko belum punya staf pemegang{summary.stale > 0 ? ` · ${summary.stale} toko pemegangnya berakun nonaktif` : ''}
            {' '}— tidak ada staf yang bisa mengisi data hariannya.
          </span>
        </p>
      )}

      {/* ════════════════ PER TOKO ════════════════ */}
      {tab === 'toko' && (
        loading && rows.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">Memuat pemegang toko…</p>
        ) : (
          <>
            <TabelData kolom={kolomToko} baris={pg.paged} testId="assign-table"
              kosong={<EmptyState icon={Store} testId="assign-empty"
                title={rows.length === 0 ? 'Tidak ada toko yang bisa Anda kelola' : 'Tidak ada toko yang cocok'}
                description={rows.length === 0 ? 'Toko dibuat di tab Daftar toko.' : 'Ubah pencarian atau saringan.'} />} />
            <PaginationLite page={pg.page} totalPages={pg.totalPages} total={pg.total}
              pageSize={pg.pageSize} onPageChange={pg.setPage} />
          </>
        )
      )}

      {/* ════════════════ PER STAF ════════════════ */}
      {tab === 'staf' && (
        <>
          {staffMeta.without_account.length > 0 && (
            <p className="flex items-start gap-1.5 text-sm text-[hsl(var(--warning-text))]" data-testid="assign-staff-without-account"
              title={staffMeta.without_account.join(' · ')}>
              <UserX className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{staffMeta.without_account.length} staf belum memegang toko — mereka melihat layar kosong sampai SPV menetapkan tokonya.</span>
            </p>
          )}
          <TabelData kolom={kolomStaf} baris={pgStaff.paged} testId="assign-staff-table"
            kosong={<EmptyState icon={Users} testId="assign-staff-empty" title="Belum ada staf toko"
              description="Belum ada pemakai berperan Staf Marketing, PIC Toko, Host Live, atau CS." />} />
          <PaginationLite page={pgStaff.page} totalPages={pgStaff.totalPages}
            total={pgStaff.total} pageSize={pgStaff.pageSize} onPageChange={pgStaff.setPage} />
        </>
      )}

      {/* ════════════════ RIWAYAT (SEMUA TOKO) ════════════════ */}
      {tab === 'riwayat' && (
        <>
          <TabelData kolom={kolomRiwayat} baris={allHistory} testId="assign-allhistory-table"
            kosong={<EmptyState icon={History} testId="assign-allhistory-empty" title="Belum ada perubahan pemegang toko"
              description="Perubahan staf pemegang tercatat di sini beserta alasannya." />} />
          <PaginationLite page={allHistoryPage}
            totalPages={Math.max(1, Math.ceil(allHistoryTotal / 10))}
            total={allHistoryTotal} pageSize={10}
            onPageChange={(p) => loadAllHistory(p)} />
        </>
      )}

      {notes.length > 0 && (
        <Notice tone="info" icon={Info} title="Catatan" testId="assign-notes">
          <ul className="list-disc space-y-0.5 pl-4">
            {notes.map((n, i) => <li key={i}>{n}</li>)}
          </ul>
        </Notice>
      )}

      {/* ── Popup: atur staf ─────────────────────────────────────────────── */}
      <FormPopup open={Boolean(editTarget)} onClose={() => setEditTarget(null)} ukuran="pendek"
        onSimpan={save} menyimpan={saving} bisaSimpan={reasonOk} testId="assign-dialog"
        judul={`Staf pemegang ${editTarget?.account_name || ''}`}
        keterangan="Centang staf yang bertanggung jawab atas toko ini. Staf yang tidak dicentang langsung kehilangan akses ke data toko ini.">
        <div className="max-h-72 space-y-1 overflow-y-auto">
          {options.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Belum ada pemakai berperan staf toko (Staf Marketing / PIC Toko / Host Live / CS).
              Buat dulu akunnya di Manajemen Pengguna.
            </p>
          ) : options.map((o) => {
            const off = String(o.status || 'active').toLowerCase() !== 'active';
            return (
              <label key={o.id} className="flex cursor-pointer items-start gap-2 rounded-md px-2 py-1.5 hover:bg-foreground/5"
                data-testid={`assign-option-${o.id}`}>
                <Checkbox checked={picked.includes(o.id)} onCheckedChange={() => toggle(o.id)}
                  data-testid={`assign-checkbox-${o.id}`} className="mt-0.5" />
                <span className="text-sm">
                  <span className="font-medium text-foreground">{o.name}</span>
                  <span className="text-muted-foreground"> · {peran(o.role)}</span>
                  {off && <> <StatusBadge status="nonaktif" label="Akun nonaktif" tone="danger" /></>}
                  <span className="block text-xs text-muted-foreground">
                    {o.email} · memegang {o.accounts_assigned} toko
                  </span>
                </span>
              </label>
            );
          })}
        </div>
        <Isian label="Alasan perubahan (masuk riwayat)" wajib htmlFor="assign-reason"
          galat={reason && !reasonOk ? `Minimal ${MIN_REASON} huruf.` : undefined}
          petunjuk={reasonOk ? 'Alasan ini yang akan dibaca orang lain di Riwayat.'
            : `Wajib diisi (minimal ${MIN_REASON} huruf) — alasan inilah yang menjawab "kenapa akses toko saya dicabut?".`}>
          <Input id="assign-reason" value={reason} onChange={(e) => setReason(e.target.value)}
            placeholder="Contoh: rotasi shift Agustus / staf berhenti" data-testid="assign-reason-input" />
        </Isian>
      </FormPopup>

      {/* ── Popup: riwayat per toko ──────────────────────────────────────── */}
      <DetailPopup open={Boolean(historyFor)} onClose={() => setHistoryFor(null)} testId="assign-history-dialog"
        judul={`Riwayat pemegang ${historyFor?.account_name || ''}`}
        keterangan="Setiap perubahan menyimpan daftar lama dan baru beserta pelakunya."
        aksi={history.length > 0 && (
          <TombolUnduh namaBerkas={`riwayat-pemegang-${historyFor?.account_name || 'toko'}`} namaLembar="Riwayat" baris={history}
            testId="assign-history-unduh"
            kolom={[
              { label: 'Waktu', nilai: (h) => fmtWhen(h.at) },
              { label: 'Jenis', nilai: (h) => (h.action === 'assign_staff' ? 'Perubahan' : 'Tanpa perubahan') },
              { label: 'Pelaku', nilai: (h) => `${h.actor_name || ''} (${h.actor_role || ''})` },
              { label: 'Sebelum', nilai: (h) => (h.before_names || []).join(', ') },
              { label: 'Sesudah', nilai: (h) => (h.after_names || []).join(', ') },
              { label: 'Alasan', nilai: (h) => h.reason || '' },
            ]} />
        )}>
        {historyLoading ? (
          <p className="py-8 text-center text-sm text-muted-foreground">Memuat riwayat…</p>
        ) : (
          <TabelData baris={history} testId="assign-history-table"
            kosong={<EmptyState title="Belum ada perubahan pemegang toko ini" testId="assign-history-empty" />}
            kolom={[
              { kunci: 'waktu', label: 'Waktu', hp: 'judul', isi: (h) => <span data-testid={`assign-history-row-${h.id}`}>{fmtWhen(h.at)}</span> },
              { kunci: 'jenis', label: 'Jenis', isi: (h) => (h.action === 'assign_staff' ? 'Perubahan' : 'Tanpa perubahan') },
              { kunci: 'pelaku', label: 'Pelaku', isi: (h) => `${h.actor_name || ''} (${h.actor_role || ''})` },
              { kunci: 'sebelum', label: 'Sebelum', isi: (h) => (h.before_names || []).join(', ') || '—' },
              { kunci: 'sesudah', label: 'Sesudah', isi: (h) => (h.after_names || []).join(', ') || '—' },
              { kunci: 'alasan', label: 'Alasan', isi: (h) => h.reason || '—' },
            ]} />
        )}
      </DetailPopup>
    </div>
  );
}

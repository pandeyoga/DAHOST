/**
 * MarketingChangeLogModule — LAYAR "SIAPA MENGUBAH APA" (F6.5).
 *
 * KENAPA LAYAR INI ADA
 * --------------------
 * `marketing_change_log` sudah menyimpan setiap perubahan angka & kewenangan
 * marketing sejak F5 — tetapi sebelum layar ini, jejak itu hanya bisa dibaca dari
 * dua sudut sempit: panel kecil di dialog Siklus (satu toko × satu bulan, 20 baris)
 * dan tab Riwayat di layar Assign (hanya pemegang toko). Pertanyaan yang paling
 * sering muncul di rapat — *"siapa mengubah angka bulan lalu, kapan, dari berapa
 * ke berapa, dan kenapa?"* — tetap tidak bisa dijawab untuk SEMUA toko sekaligus.
 * Jejak yang ada tetapi tidak bisa dicari sama saja dengan tidak ada.
 *
 * YANG WAJIB TETAP TERLIHAT (jangan dihapus saat merapikan tampilan):
 *  · nilai LAMA → BARU per field (bukan dua blob JSON yang harus dibandingkan mata);
 *  · nama & PERAN pelaku + waktu + ALASAN — tanpa alasan, "kenapa akses toko saya
 *    dicabut?" tetap tak terjawab walau riwayatnya lengkap;
 *  · pembeda **kewenangan** vs **angka** (dua pertanyaan yang berbeda);
 *  · catatan kejujuran data: staf berlingkup hanya melihat tokonya, dan itu
 *    DIKATAKAN — bukan dibiarkan tampak seperti "tidak ada perubahan".
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, penyaring satu baris (periode lewat PeriodPicker — dulu dua
 * <input type="date">), 4 kartu StatTile, tabel standar, unduh Excel + CSV (dulu CSV saja) berisi SELURUH hasil
 * saringan, label jenis/peran berbahasa biasa, catatan kejujuran data dalam Notice.
 *
 * Semua penyaringan & paginasi dilakukan BACKEND (`/api/marketing/change-log`)
 * supaya jumlah "total" di layar tidak pernah berarti "20 baris pertama".
 */
import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Loader2, Search, Info } from 'lucide-react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { GlassCard } from '@/components/ui/glass';
import FilterChips from '@/components/ui/filter-chips';
import PaginationLite from '@/components/ui/pagination-lite';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { toast } from 'sonner';
import { formatRupiah } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';
import PeriodPicker, { ALL_TIME, PERIOD_PRESETS } from '../finance/PeriodPicker';
import { MarketingAccountSelect } from './pickers/MarketingPickers';
import NoStoreScopeNotice from './NoStoreScopeNotice';

const API = process.env.REACT_APP_BACKEND_URL;
const fmtNum = (n) => new Intl.NumberFormat('id-ID').format(Math.round(n || 0));
const JENIS = {
  kewenangan: { label: 'Kewenangan', tone: 'warning' },
  angka: { label: 'Angka', tone: 'info' },
};
const BLN = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
/** "2026-11-05T06:53:50" → "05 Nov 2026 06.53" (tampilan saja). */
const waktu = (v) => {
  const s = String(v || '');
  if (!/^\d{4}-\d{2}-\d{2}/.test(s)) return s || '—';
  const [y, m, d] = s.slice(0, 10).split('-').map(Number);
  const jam = s.slice(11, 16);
  return `${String(d).padStart(2, '0')} ${BLN[m - 1]} ${y}${jam ? ` ${jam.replace(':', '.')}` : ''}`;
};
const peran = (r) => { const t = String(r || '').replace(/_/g, ' ').trim(); return t ? t.charAt(0).toUpperCase() + t.slice(1) : ''; };

/* Nilai bisa berupa angka uang, daftar nama, boolean, atau kosong. Menampilkan "null" apa adanya membuat
   pembacanya menebak; "belum ada" menjawabnya. */
function Val({ v, money }) {
  if (v === null || v === undefined || v === '') {
    return <span className="italic text-muted-foreground">belum ada</span>;
  }
  if (Array.isArray(v)) {
    return v.length ? <span>{v.join(', ')}</span> : <span className="italic text-muted-foreground">kosong</span>;
  }
  if (typeof v === 'boolean') return <span>{v ? 'ya' : 'tidak'}</span>;
  if (money && typeof v === 'number') return <span>{formatRupiah(v)}</span>;
  if (typeof v === 'number') return <span>{fmtNum(v)}</span>;
  return <span>{String(v)}</span>;
}

export default function MarketingChangeLogModule({ token, scope = 'marketing' }) {
  const [rows, setRows] = useState([]);
  const [meta, setMeta] = useState({ total: 0, page: 1, page_size: 20, total_pages: 1 });
  const [filters, setFilters] = useState({ entities: [], actions: [], actors: [] });
  const [notes, setNotes] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  // filter state
  const [accountId, setAccountId] = useState('');
  const [entity, setEntity] = useState('');
  const [action, setAction] = useState('');
  const [actorId, setActorId] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [q, setQ] = useState('');
  const [onlyPerm, setOnlyPerm] = useState(false);
  const [page, setPage] = useState(1);
  const [periode, setPeriode] = useState({ preset: 'all', from: '', to: '' });

  const params = useCallback((extra = {}) => {
    const p = new URLSearchParams({ page: String(page), page_size: '20', ...extra });
    if (accountId) p.set('account_id', accountId);
    if (entity) p.set('entity', entity);
    if (action) p.set('action', action);
    if (actorId) p.set('actor_id', actorId);
    if (dateFrom) p.set('date_from', dateFrom);
    if (dateTo) p.set('date_to', dateTo);
    if (q.trim()) p.set('q', q.trim());
    if (onlyPerm) p.set('only_permissions', 'true');
    return p;
  }, [page, accountId, entity, action, actorId, dateFrom, dateTo, q, onlyPerm]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/marketing/change-log?${params()}`,
        { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const j = await res.json();
      setRows(j.rows || []);
      setMeta({ total: j.total || 0, page: j.page || 1, page_size: j.page_size || 20,
        total_pages: j.total_pages || 1 });
      setFilters(j.filters || { entities: [], actions: [], actors: [] });
      setNotes(j.data_notes || []);
    } catch (e) {
      toast.error(`Gagal memuat jejak perubahan: ${e.message}`);
      setRows([]);
    } finally { setLoading(false); }
  }, [params, token]);

  const loadStats = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/marketing/change-log/stats?days=30`,
        { headers: { Authorization: `Bearer ${token}` } });
      setStats(res.ok ? await res.json() : null);
    } catch { setStats(null); }
  }, [token]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadStats(); }, [loadStats]);
  // Ganti filter ⇒ balik ke halaman 1 (kalau tidak, "tidak ada data" bisa muncul
  // hanya karena halaman 3 dari hasil baru tidak ada).
  useEffect(() => { setPage(1); },
    [accountId, entity, action, actorId, dateFrom, dateTo, q, onlyPerm]);

  const resetFilters = () => {
    setAccountId(''); setEntity(''); setAction(''); setActorId('');
    setDateFrom(''); setDateTo(''); setQ(''); setOnlyPerm(false); setPage(1);
  };
  const hasFilter = Boolean(accountId || entity || action || actorId || dateFrom
    || dateTo || q.trim() || onlyPerm);

  /* Unduh (Excel/CSV) — bahan audit. Mengambil ulang dengan page_size besar supaya berkas memuat SELURUH hasil
     saringan, bukan hanya halaman yang terlihat (batas 500 perubahan per unduhan, disebut di toast). */
  const ambilSemua = async () => {
    const res = await fetch(`${API}/api/marketing/change-log?${params({ page: '1', page_size: '500' })}`,
      { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) throw new Error(`kode ${res.status}`);
    const j = await res.json();
    const out = [];
    (j.rows || []).forEach((r) => {
      if (!r.changes?.length) out.push({ r, c: null });
      r.changes?.forEach((c) => out.push({ r, c }));
    });
    if (j.total > (j.rows?.length || 0)) toast.info(`Unduhan berisi ${j.rows?.length || 0} dari ${j.total} perubahan (batas 500 per unduhan).`);
    return out;
  };
  const nilaiTeks = (v) => (Array.isArray(v) ? v.join(' | ') : (v ?? ''));

  const gantiPeriode = (p) => { setPeriode(p); setDateFrom(p.from || ''); setDateTo(p.to || ''); };
  const bersihkan = () => { resetFilters(); setPeriode({ preset: 'all', from: '', to: '' }); };

  return (
    <PageLayout
      testId="marketing-changelog"
      title={scope === 'management' ? 'Jejak Marketing' : 'Jejak perubahan marketing'}
      subtitle={`Siapa mengubah apa — target, rencana anggaran, kunci periode, dan kewenangan toko. Hanya bisa dibaca${scope === 'management' ? ' (Portal Manajemen)' : ''}.`}
      filters={(
        <>
          <div className="relative w-full sm:w-64">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input className="h-9 pl-8" placeholder="Cari alasan, pelaku, jenis" aria-label="Cari"
              value={q} onChange={(e) => setQ(e.target.value)} data-testid="changelog-search" />
          </div>
          <MarketingAccountSelect token={token} value={accountId} onChange={setAccountId} required={false} includeAll
            allLabel="Semua toko" label="" className="w-48" testId="changelog-account-select" />
          <SmartNativeSelect className="h-9 w-44" value={entity} onChange={(e) => setEntity(e.target.value)}
            aria-label="Yang diubah" data-testid="changelog-entity-select">
            <option value="">Semua jenis</option>
            {filters.entities.map((e) => <option key={e.value} value={e.value}>{e.label}</option>)}
          </SmartNativeSelect>
          <SmartNativeSelect className="h-9 w-40" value={action} onChange={(e) => setAction(e.target.value)}
            aria-label="Aksi" data-testid="changelog-action-select">
            <option value="">Semua aksi</option>
            {filters.actions.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
          </SmartNativeSelect>
          <SmartNativeSelect className="h-9 w-48" value={actorId} onChange={(e) => setActorId(e.target.value)}
            aria-label="Pelaku" data-testid="changelog-actor-select">
            <option value="">Semua orang</option>
            {filters.actors.map((a) => (
              <option key={a.id} value={a.id}>{a.name}{a.role ? ` (${peran(a.role)})` : ''} — {a.count}×</option>
            ))}
          </SmartNativeSelect>
          <PeriodPicker value={periode} onChange={gantiPeriode} presets={[ALL_TIME, ...PERIOD_PRESETS]} testId="changelog-period" />
          <FilterChips testId="changelog-only-permissions" hideWhenEmpty={false} value={onlyPerm ? 'kewenangan' : ''}
            onChange={(k) => setOnlyPerm(k === 'kewenangan')} ariaLabel="Jenis perubahan"
            options={[{ key: '', label: 'Semua perubahan' }, { key: 'kewenangan', label: 'Hanya kewenangan' }]} />
          {hasFilter && (
            <Button variant="link" size="sm" onClick={bersihkan} data-testid="changelog-reset">Hapus saringan</Button>
          )}
        </>
      )}
      tools={(
        <>
          <TombolUnduh namaBerkas="jejak-perubahan-marketing" namaLembar="Jejak perubahan" baris={rows} ambilSemua={ambilSemua}
            testId="changelog-export-csv"
            kolom={[
              { label: 'Waktu', nilai: (x) => waktu(x.r.at) }, { label: 'Toko', nilai: (x) => x.r.account_name || '' },
              { label: 'Kode toko', nilai: (x) => x.r.account_code || '' }, { label: 'Jenis', nilai: (x) => JENIS[x.r.kind]?.label || x.r.kind || '' },
              { label: 'Yang diubah', nilai: (x) => x.r.entity_label || '' }, { label: 'Aksi', nilai: (x) => x.r.action_label || '' },
              { label: 'Periode', nilai: (x) => x.r.period || '' }, { label: 'Pelaku', nilai: (x) => x.r.actor_name || '' },
              { label: 'Peran', nilai: (x) => peran(x.r.actor_role) }, { label: 'Alasan', nilai: (x) => x.r.reason || '' },
              { label: 'Isian', nilai: (x) => x.c?.field_label || '' }, { label: 'Nilai lama', nilai: (x) => (x.c ? nilaiTeks(x.c.before) : '') },
              { label: 'Nilai baru', nilai: (x) => (x.c ? nilaiTeks(x.c.after) : '') },
            ]} />
          <Button variant="outline" size="icon" onClick={() => { load(); loadStats(); }} disabled={loading}
            title="Muat ulang" aria-label="Muat ulang" data-testid="changelog-refresh">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
        </>
      )}
      summary={(
        <div className="space-y-3">
          <NoStoreScopeNotice token={token} what="Jejak & angka di layar ini" />
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="changelog-stats">
            <StatTile label="Perubahan 30 hari" value={fmtNum(stats?.total)} sub={`${fmtNum(stats?.without_reason)} tanpa alasan`} />
            <StatTile label="Perubahan angka" value={fmtNum(stats?.number_changes)} sub="Target, anggaran, kunci periode" />
            <StatTile label="Perubahan kewenangan" value={fmtNum(stats?.permission_changes)} sub="Siapa pemegang toko" />
            <StatTile label="Pelaku" value={fmtNum(stats?.actors)} sub={`${fmtNum(stats?.accounts_touched)} toko tersentuh`} />
          </div>
        </div>
      )}
      footer={!loading && rows.length > 0 && meta.total_pages > 1 ? (
        <PaginationLite page={meta.page} totalPages={meta.total_pages} total={meta.total} pageSize={meta.page_size} onPageChange={setPage} />
      ) : null}
    >
      <GlassCard className="p-0" data-testid="changelog-filters">
        <div className="border-b border-[var(--glass-border)] px-4 py-2 text-sm text-muted-foreground">
          {fmtNum(meta.total)} perubahan cocok
        </div>
        {loading ? (
          <p className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />Membaca jejak perubahan…
          </p>
        ) : !rows.length ? (
          <EmptyState className="py-6" testId="changelog-empty"
            title={hasFilter ? 'Tidak ada perubahan yang cocok' : 'Belum ada perubahan tercatat'}
            description={hasFilter ? 'Longgarkan saringannya.' : 'Jejak lahir saat target, anggaran, kunci periode, atau pemegang toko diubah.'} />
        ) : (
          <div className="overflow-x-auto">
            <Table data-testid="changelog-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Waktu</TableHead>
                  <TableHead>Toko</TableHead>
                  <TableHead>Perubahan</TableHead>
                  <TableHead className="min-w-[240px]">Nilai lama → baru</TableHead>
                  <TableHead className="hidden md:table-cell">Pelaku</TableHead>
                  <TableHead className="hidden lg:table-cell">Alasan</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r) => (
                  <TableRow key={r.id} data-testid={`changelog-row-${r.id}`} className="align-top">
                    <TableCell className="whitespace-nowrap">
                      {waktu(r.at)}
                      <div className="text-xs text-muted-foreground">{r.period ? `Periode ${r.period}` : 'Tanpa periode'}</div>
                    </TableCell>
                    <TableCell>
                      <div className="font-medium text-foreground">{r.account_name}</div>
                      {r.account_code ? <div className="text-xs text-muted-foreground">{r.account_code}</div> : null}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="font-medium">{r.action_label}</span>
                        <StatusBadge status={r.kind} label={JENIS[r.kind]?.label || r.kind} tone={JENIS[r.kind]?.tone || 'default'} />
                      </div>
                      <div className="text-xs text-muted-foreground">{r.entity_label}</div>
                      <div className="text-xs text-muted-foreground md:hidden">oleh {r.actor_name}</div>
                    </TableCell>
                    <TableCell className="whitespace-normal">
                      {r.changes?.length ? (
                        <ul className="space-y-0.5">
                          {r.changes.map((c, i) => (
                            <li key={i}>
                              <span className="text-muted-foreground">{c.field_label}: </span>
                              <Val v={c.before} money={c.is_money} />
                              <span className="text-muted-foreground"> → </span>
                              <span className="font-medium"><Val v={c.after} money={c.is_money} /></span>
                            </li>
                          ))}
                        </ul>
                      ) : <span className="italic text-muted-foreground">tidak ada nilai yang berubah</span>}
                    </TableCell>
                    <TableCell className="hidden whitespace-nowrap md:table-cell">
                      {r.actor_name}
                      {r.actor_role ? <div className="text-xs text-muted-foreground">{peran(r.actor_role)}</div> : null}
                    </TableCell>
                    <TableCell className="hidden max-w-[240px] whitespace-normal lg:table-cell">
                      {r.reason ? r.reason : <span className="italic text-muted-foreground">tidak diisi</span>}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </GlassCard>

      {notes.length > 0 && (
        <Notice tone="info" icon={Info} title="Catatan kejujuran data" testId="changelog-notes">
          <ul className="list-disc space-y-0.5 pl-4">{notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
        </Notice>
      )}
    </PageLayout>
  );
}

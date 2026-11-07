/**
 * AccountBulkReviewModule.jsx — KOREKSI MASSAL DATA TOKO (BD-5)
 *
 * Kenapa layar ini ada: 9 toko nyata dibuat dari bagan akun (COA) sehingga nama,
 * username, PIC, dan rekening pencairannya masih perlu dikoreksi owner. Mengedit
 * satu-satu lewat dialog = 9 kali buka-tutup. Layar ini menaruh semuanya dalam
 * SATU tabel yang bisa diisi langsung, lalu disimpan sekali.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, penyaring pil, tabel isian standar, unduh Excel/CSV.
 *
 * Aturan: tidak ada data yang dikarang. Kolom yang belum diisi tetap kosong dan
 * tandanya "perlu ditinjau" hanya hilang kalau owner sendiri yang mencentangnya.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { RefreshCw, Save, Loader2, CheckCircle2, Store } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PageLayout from '../layout/PageLayout';
import { StatTile, EmptyState, StatusBadge } from '../moduleAtoms';
import { toast } from 'sonner';

const API = process.env.REACT_APP_BACKEND_URL || '';

export default function AccountBulkReviewModule({ token }) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [accounts, setAccounts] = useState([]);
  const [users, setUsers] = useState([]);
  const [coa, setCoa] = useState({});
  const [draft, setDraft] = useState({});      // id → perubahan
  const [onlyReview, setOnlyReview] = useState(true);

  const headers = useMemo(
    () => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }),
    [token],
  );

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [ra, ru, rc] = await Promise.all([
        fetch(`${API}/api/marketing/accounts`, { headers }),
        fetch(`${API}/api/auth/users?portal=toko&limit=500`, { headers }),   // MK3: hanya pengguna Portal Toko
        fetch(`${API}/api/marketing/accounts/coa-options`, { headers }),
      ]);
      const accs = ra.ok ? await ra.json() : [];
      setAccounts(Array.isArray(accs) ? accs : []);
      if (ru.ok) {
        const u = await ru.json();
        setUsers(Array.isArray(u) ? u : (u.items || u.users || []));
      }
      if (rc.ok) setCoa(await rc.json());
      setDraft({});
    } catch (e) {
      toast.error('Gagal memuat data toko');
    } finally {
      setLoading(false);
    }
  }, [headers]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const coaName = useMemo(() => {
    const m = {};
    [...(coa.revenue || []), ...(coa.cash || []), ...(coa.receivable || [])]
      .forEach(o => { m[o.code] = o.name; });
    return m;
  }, [coa]);

  const rows = useMemo(() => (
    onlyReview ? accounts.filter(a => a.needs_owner_review) : accounts
  ), [accounts, onlyReview]);

  const val = (acc, field) => {
    const d = draft[acc.id] || {};
    return field in d ? d[field] : (acc[field] ?? '');
  };
  const setVal = (acc, field, value) => {
    setDraft(prev => ({ ...prev, [acc.id]: { ...(prev[acc.id] || {}), [field]: value } }));
  };
  const dirtyIds = Object.keys(draft).filter(id => Object.keys(draft[id] || {}).length > 0);

  const saveAll = async () => {
    if (!dirtyIds.length) {
      toast.info('Belum ada perubahan untuk disimpan');
      return;
    }
    setSaving(true);
    let okCount = 0;
    const failed = [];
    for (const id of dirtyIds) {
      const acc = accounts.find(a => a.id === id);
      const patch = { ...draft[id] };
      if (patch.pic_user_id === 'none') patch.pic_user_id = null;
      try {
        const res = await fetch(`${API}/api/marketing/accounts/${id}`, {
          method: 'PUT', headers, body: JSON.stringify(patch),
        });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(body.detail || 'gagal');
        okCount += 1;
      } catch (e) {
        failed.push(`${acc?.account_code || id}: ${e.message}`);
      }
    }
    setSaving(false);
    if (okCount) toast.success(`${okCount} toko tersimpan`);
    if (failed.length) toast.error(`Gagal: ${failed.join(' · ')}`, { duration: 8000 });
    fetchAll();
  };

  const markAllReviewed = () => {
    setDraft(prev => {
      const next = { ...prev };
      rows.forEach(a => {
        next[a.id] = { ...(next[a.id] || {}), needs_owner_review: false };
      });
      return next;
    });
    toast.info('Semua baris ditandai sudah ditinjau — tekan "Simpan semua" untuk menyimpan');
  };

  const stats = useMemo(() => ({
    total: accounts.length,
    review: accounts.filter(a => a.needs_owner_review).length,
    noPic: accounts.filter(a => !a.pic_user_name).length,
    noUser: accounts.filter(a => !a.username).length,
  }), [accounts]);

  const PLATFORM = { shopee: 'Shopee', tiktok: 'TikTok Shop', tiktokshop: 'TikTok Shop', tokopedia: 'Tokopedia' };
  const labelPlatform = (p) => PLATFORM[String(p || '').toLowerCase()] || p || '—';
  const sudahDitinjau = (acc) => val(acc, 'needs_owner_review') === false
    || (!('needs_owner_review' in (draft[acc.id] || {})) && !acc.needs_owner_review);

  const kolom = [
    { kunci: 'kode', label: 'Toko', hp: 'judul', isi: (acc) => (
      <div data-testid={`bulk-row-${acc.account_code}`}>
        <p className="font-medium text-foreground">{acc.account_code}</p>
        <p className="text-xs text-muted-foreground">{labelPlatform(acc.platform)}</p>
      </div>) },
    { kunci: 'nama', label: 'Nama toko (final)', isi: (acc) => (
      <Input className="min-w-[12rem]" value={val(acc, 'account_name')} aria-label={`Nama toko ${acc.account_code}`}
        onChange={e => setVal(acc, 'account_name', e.target.value)} data-testid={`bulk-name-${acc.account_code}`} />) },
    { kunci: 'username', label: 'Username platform', isi: (acc) => (
      <Input className="min-w-[10rem]" placeholder="Username di platform" value={val(acc, 'username')}
        aria-label={`Username ${acc.account_code}`}
        onChange={e => setVal(acc, 'username', e.target.value)} data-testid={`bulk-username-${acc.account_code}`} />) },
    { kunci: 'pic', label: 'PIC', isi: (acc) => (
      <div className="min-w-[11rem]">
        <Select value={val(acc, 'pic_user_id') || 'none'} onValueChange={v => setVal(acc, 'pic_user_id', v)}>
          <SelectTrigger data-testid={`bulk-pic-${acc.account_code}`}><SelectValue placeholder="Pilih PIC…" /></SelectTrigger>
          <SelectContent className="max-h-72">
            <SelectItem value="none">Tidak ada PIC</SelectItem>
            {users.map(u => (
              <SelectItem key={u.id} value={u.id}>
                {u.name || u.email}
                <span className="text-muted-foreground text-xs ml-1">({u.role})</span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {acc.pic_user_name && !(draft[acc.id] || {}).pic_user_id && (
          <p className="mt-1 text-xs text-muted-foreground">Sekarang: {acc.pic_user_name}</p>
        )}
      </div>) },
    { kunci: 'cash', label: 'Rekening pencairan', isi: (acc) => (
      <div data-testid={`bulk-cash-${acc.account_code}`}>
        <p className="text-sm">{acc.coa_cash_code || '—'}</p>
        <p className="text-xs text-muted-foreground">{coaName[acc.coa_cash_code] || 'Diatur di Portal Keuangan'}</p>
      </div>) },
    { kunci: 'rev', label: 'Akun pendapatan', isi: (acc) => (
      <div>
        <p className="text-sm">{acc.coa_revenue_code || '—'}</p>
        <p className="max-w-[12rem] truncate text-xs text-muted-foreground" title={coaName[acc.coa_revenue_code] || ''}>
          {coaName[acc.coa_revenue_code] || ''}
        </p>
      </div>) },
    { kunci: 'tinjau', label: 'Sudah ditinjau', rata: 'tengah', isi: (acc) => (
      <Checkbox checked={sudahDitinjau(acc)} onCheckedChange={v => setVal(acc, 'needs_owner_review', !v)}
        aria-label={`Sudah ditinjau ${acc.account_code}`} data-testid={`bulk-reviewed-${acc.account_code}`} />) },
  ];

  return (
    <PageLayout testId="account-bulk-review-module" title="Koreksi data toko"
      subtitle="Isi nama final, username, PIC, dan rekening pencairan semua toko dalam satu tabel, lalu tandai sudah ditinjau."
      actions={<>
        <Button onClick={markAllReviewed} variant="outline" data-testid="bulk-mark-all-btn">
          <CheckCircle2 />Tandai semua ditinjau
        </Button>
        <Button onClick={saveAll} variant="success" disabled={saving || !dirtyIds.length} data-testid="bulk-save-btn">
          {saving ? <Loader2 className="animate-spin" /> : <Save />}
          Simpan semua{dirtyIds.length ? ` (${dirtyIds.length})` : ''}
        </Button>
      </>}
      filters={<>
        <FilterChips value={onlyReview ? 'tinjau' : ''} onChange={(v) => setOnlyReview(v === 'tinjau')} hideWhenEmpty={false}
          testId="bulk-filter-review"
          options={[
            { key: 'tinjau', label: 'Perlu ditinjau', count: stats.review },
            { key: '', label: 'Semua toko', count: stats.total },
          ]} />
        {dirtyIds.length > 0 && <StatusBadge status="draf" label={`${dirtyIds.length} baris belum disimpan`} tone="warning" />}
      </>}
      tools={<>
        <TombolUnduh namaBerkas="koreksi-data-toko" namaLembar="Data toko" baris={rows} testId="bulk-unduh"
          kolom={[
            { label: 'Kode', nilai: (a) => a.account_code }, { label: 'Platform', nilai: (a) => labelPlatform(a.platform) },
            { label: 'Nama toko', nilai: (a) => a.account_name || '' }, { label: 'Username', nilai: (a) => a.username || '' },
            { label: 'PIC', nilai: (a) => a.pic_user_name || '' },
            { label: 'Rekening pencairan', nilai: (a) => a.coa_cash_code || '' },
            { label: 'Akun pendapatan', nilai: (a) => a.coa_revenue_code || '' },
            { label: 'Sudah ditinjau', nilai: (a) => (a.needs_owner_review ? 'Belum' : 'Sudah') },
          ]} />
        <Button onClick={fetchAll} variant="outline" size="icon" disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="bulk-refresh-btn">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={(
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatTile label="Toko" value={stats.total} testId="bulk-stat-total" sub="Semua toko yang boleh Anda lihat" />
          <StatTile label="Perlu ditinjau" value={stats.review} accent={stats.review ? 'warning' : 'default'}
            testId="bulk-stat-review" sub="Data seed belum dikoreksi owner" />
          <StatTile label="Tanpa PIC" value={stats.noPic} accent={stats.noPic ? 'warning' : 'default'}
            testId="bulk-stat-nopic" sub="Belum ada penanggung jawab" />
          <StatTile label="Tanpa username" value={stats.noUser} accent={stats.noUser ? 'warning' : 'default'}
            testId="bulk-stat-nouser" sub="Username platform kosong" />
        </div>
      )}>
      {loading ? (
        <div className="space-y-2">{[1, 2, 3, 4, 5].map(i => <Skeleton key={i} className="h-14" />)}</div>
      ) : (
        <TabelData kolom={kolom} baris={rows} testId="bulk-review-table"
          kosong={<EmptyState icon={Store} testId="bulk-empty"
            title={stats.review === 0 && onlyReview ? 'Semua toko sudah ditinjau' : 'Tidak ada toko pada saringan ini'}
            description={stats.review === 0 && onlyReview
              ? 'Data master toko sudah dikoreksi owner. Perubahan lanjutan bisa dilakukan di Kelola Akun, atau pilih "Semua toko".'
              : 'Pilih "Semua toko" untuk melihat seluruh toko.'} />} />
      )}
      <p className="text-sm text-muted-foreground">
        Nama, username, PIC, dan rekening pencairan tidak diisi otomatis oleh sistem — hanya owner yang tahu datanya.
        Akun pendapatan sudah tertaut dari bagan akun; ubah lewat Kelola Akun bila perlu.
      </p>
    </PageLayout>
  );
}

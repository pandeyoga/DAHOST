/**
 * AccountManagementModule.jsx — Manajemen Akun Toko (Portal Marketing)
 *
 * F0.7 (2026-08-12): layar ini sekarang MENGISI & MENAMPILKAN tautan Finance
 * per toko yang sebelumnya hanya ada di backend:
 *   · coa_revenue_code        — akun pendapatan toko (4-111…4-131)
 *   · coa_cash_code           — rekening penerima pencairan (1-131 / 1-154 …)
 *   · ar_account_code         — akun SALDO PLATFORM / piutang toko (subledger otomatis,
 *                               anak 1-1303). Saldo akun ini = dana yang masih di
 *                               platform dan bisa ditarik ke bank. Dua tahap pencairan:
 *                               dana dilepas → Dr akun ini / Cr pendapatan; penarikan →
 *                               Dr rekening pencairan / Cr akun ini.
 *   · coa_receivable_code     — (warisan) disamakan otomatis dengan ar_account_code;
 *                               tidak ditampilkan lagi karena duplikat.
 *   · revenue_basis           — basis omzet (produk setelah diskon / order amount)
 *   · platform_warehouse_name — nama gudang di ekspor Seller Center
 *   · platform_shop_id        — id toko di platform
 *   · pic_user_id/name        — PIC toko (boleh diisi sejak pembuatan)
 *   · needs_owner_review      — penanda BD-5 (owner wajib mengoreksi data seed)
 *
 * Aturan UI repo (plan.md): setiap daftar record = TABEL (default) + KARTU (alternatif).
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout; tabel berisi kolom penting (15 → 8), kolom lain + semua aksi
 * di popup rincian; form = FormPopup; arsip/hapus lewat confirmDialog; unduh Excel/CSV (dulu CSV dengan
 * kolom grup/shop id/piutang/gudang yang selalu kosong karena nama field salah).
 */
import { Fragment, useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  Store, Plus, RefreshCw, Pencil, Archive, Loader2, Search, BadgeCheck, AlertTriangle,
  X, Star, Calculator, ClipboardCheck, Trash2, Eye, MoreHorizontal,
} from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import AccountAssignView from './marketing/AccountAssignView';
import { isStoreScopedUser, NO_STORE_HINT, canManageStores, canDeleteStores } from './marketing/NoStoreScopeNotice';
import { usePlatformBalances } from './finance/PlatformBalanceCards';
import { formatRupiah } from '@/lib/format';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue, SelectGroup, SelectLabel,
} from '@/components/ui/select';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import ViewToggle from '@/components/ui/view-toggle';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import PageLayout, { Toolbar } from './layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';
import { toast } from 'sonner';
// F10 (sesi #10) — master toko dipakai lintas divisi (Finance/Gudang) ⇒ bisa diunduh (Excel + CSV).
import TombolUnduh from '@/components/ui/tombol-unduh';

const API = process.env.REACT_APP_BACKEND_URL || '';

const PLATFORMS = [
  { value: 'shopee', label: 'Shopee' },
  { value: 'tiktokshop', label: 'TikTok Shop' },
  { value: 'tokopedia', label: 'Tokopedia' },
];

const GROUPS = [
  { value: 'official_store', label: 'Official Store' },
  { value: 'reseller', label: 'Reseller' },
  { value: 'distributor', label: 'Distributor' },
  { value: 'other', label: 'Lainnya' },
];

const STATUSES = [
  { value: 'active', label: 'Aktif' },
  { value: 'inactive', label: 'Nonaktif' },
  { value: 'suspended', label: 'Ditangguhkan' },
];

/** Label pendek basis omzet untuk kolom tabel (label panjang dipakai di form). */
const BASIS_SHORT = {
  produk_setelah_diskon: 'Produk (setelah diskon)',
  order_amount: 'Nilai pesanan',
};

// 2026-11-02 (No.10b) — nilai pemilih "buat akun pendapatan sendiri untuk toko ini".
const AUTO_REVENUE = '__auto__';

const statusLabel = (s) => (STATUSES.find(x => x.value === s)?.label || s || '—');
const groupLabel = (g) => (GROUPS.find(x => x.value === g)?.label || (g || '—'));
// 2026-11-02 (No.10) — 3 toko seed tersimpan `tiktok`; platform yang sama dengan `tiktokshop`.
const platformLabel = (p) => (PLATFORMS.find(x => x.value === p)?.label
  || (p === 'tiktok' ? 'TikTok Shop' : p) || '—');

/** Sel tabel untuk kode akun keuangan: kode + nama akun kecil di bawahnya. */
function CoaCell({ code, name, testId, fallback }) {
  if (!code) {
    return (
      <span className="text-sm text-[hsl(var(--warning-text))] md:whitespace-nowrap" data-testid={testId}>
        Belum ditautkan
      </span>
    );
  }
  return (
    <div className="min-w-0" data-testid={testId}>
      <div className="flex items-center gap-1 text-sm text-foreground">
        {code}
        {fallback && (
          <span title="Memakai akun penampung platform — ganti ke akun khusus toko bila sudah ada">
            <StatusBadge status="penampung" label="Penampung" tone="warning" />
          </span>
        )}
      </div>
      {name && <div className="max-w-[14rem] truncate text-xs text-muted-foreground" title={name}>{name}</div>}
    </div>
  );
}

/**
 * Skor sehat akun — SKALA 1–5 (keputusan owner 2026-08-12).
 * Skor internal 0–100 tetap dipakai mesin; yang dilihat staf adalah bintang +
 * label + rincian per pilar (kenapa skornya segitu) lewat tooltip.
 * Toko tanpa data 30 hari terakhir = "Belum ada data" — BUKAN 1, supaya toko yang
 * datanya belum masuk tidak tampak seperti toko bermasalah.
 */
function HealthStars({ score, grade, label, breakdown, testId }) {
  const has = grade !== null && grade !== undefined;
  const detail = breakdown && Object.keys(breakdown).length
    ? Object.values(breakdown).map(b => `\u2022 ${b.label}: ${b.score}/${b.max}`).join('\n')
    : 'Belum ada data penjualan 30 hari terakhir';
  const title = has
    ? `${label} — skor ${score}/100\n${detail}`
    : 'Belum ada data penjualan 30 hari terakhir — impor pesanan atau isi rekap harian dulu';
  return (
    <div className="min-w-[6.5rem]" data-testid={testId} title={title}>
      <div className="flex items-center gap-0.5">
        {[1, 2, 3, 4, 5].map(i => (
          <Star key={i} size={12}
            className={has && i <= grade ? 'fill-[hsl(var(--warning))] text-[hsl(var(--warning))]' : 'text-muted-foreground/40'} />
        ))}
        {has && <span className="ml-1 text-xs font-semibold tabular-nums">{grade}</span>}
      </div>
      <div className="truncate text-xs text-muted-foreground">
        {has ? label : 'Belum ada data'}
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// FORM BUAT / EDIT AKUN
// ════════════════════════════════════════════════════════════════════════════
function AccountFormDialog({ open, onOpenChange, account, onSaved, token, coa, users }) {
  const isEdit = !!account;
  const [submitting, setSubmitting] = useState(false);
  const [galat, setGalat] = useState('');
  const [form, setForm] = useState({
    account_code: '',
    account_name: '',
    platform: 'shopee',
    username: '',
    group: 'other',
    status: 'active',
    has_api_integration: false,
    pic_user_id: '',
    coa_revenue_code: '',
    coa_cash_code: '',
    revenue_basis: 'produk_setelah_diskon',
    platform_warehouse_name: '',
    platform_shop_id: '',
  });

  const headers = useMemo(
    () => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }),
    [token],
  );

  const channelOf = (platform) => (coa.platform_channel_map || {})[platform] || '';
  const fallbackRevenue = (platform) => (coa.fallback_revenue_by_platform || {})[platform] || '';

  useEffect(() => {
    if (!open) return;
    setGalat('');
    if (account) {
      setForm({
        account_code: account.account_code || '',
        account_name: account.account_name || '',
        platform: account.platform || 'shopee',
        username: account.username || '',
        group: account.group || 'other',
        status: account.status || 'active',
        has_api_integration: !!account?.credentials?.has_api_integration,
        pic_user_id: account.pic_user_id || '',
        // Akun lama yang belum ditautkan → sarankan akun penampung platform-nya
        coa_revenue_code: account.coa_revenue_code || fallbackRevenue(account.platform) || '',
        coa_cash_code: account.coa_cash_code || '',
        revenue_basis: account.revenue_basis || 'produk_setelah_diskon',
        platform_warehouse_name: account.platform_warehouse_name || '',
        platform_shop_id: account.platform_shop_id || '',
      });
    } else {
      setForm({
        account_code: '',
        account_name: '',
        platform: 'shopee',
        username: '',
        group: 'other',
        status: 'active',
        has_api_integration: false,
        pic_user_id: '',
        // 2026-11-02 (No.10b) — toko baru otomatis dibuatkan akun pendapatan SENDIRI
        // (bukan lagi diusulkan akun penampung "Lain-lain").
        coa_revenue_code: AUTO_REVENUE,
        coa_cash_code: coa.default_cash || '',
        revenue_basis: 'produk_setelah_diskon',
        platform_warehouse_name: '',
        platform_shop_id: '',
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, account, coa]);

  /** Ganti platform saat buat baru → sarankan akun pendapatan platform tsb. */
  const handlePlatformChange = (v) => {
    setForm(f => {
      // 2026-11-02 (No.10b) — mode otomatis tetap otomatis; akun pilihan lain
      // dikembalikan ke otomatis karena belum tentu milik platform baru.
      const keepManual = f.coa_revenue_code && f.coa_revenue_code !== AUTO_REVENUE
        && f.coa_revenue_code !== fallbackRevenue(f.platform);
      return {
        ...f,
        platform: v,
        coa_revenue_code: keepManual ? f.coa_revenue_code : AUTO_REVENUE,
      };
    });
  };

  const revenueOptions = coa.revenue || [];
  const cashOptions = coa.cash || [];
  const basisOptions = coa.revenue_basis_options || [
    { value: 'produk_setelah_diskon', label: 'Omzet produk (setelah diskon penjual)' },
    { value: 'order_amount', label: 'Order Amount (dibayar pembeli)' },
  ];
  const ch = channelOf(form.platform);
  const revRecommended = revenueOptions.filter(o => ch && o.channel === ch);
  const revOthers = revenueOptions.filter(o => !ch || o.channel !== ch);
  const selectedRevName = (revenueOptions.find(o => o.code === form.coa_revenue_code) || {}).name || '';
  const revenueIsCatchAll = /lain[\s-]*lain/i.test(selectedRevName);

  const handleSubmit = async () => {
    if (!form.account_name.trim()) {
      setGalat('Nama akun wajib diisi.');
      return;
    }
    if (!isEdit && !form.account_code.trim()) {
      setGalat('Kode akun wajib diisi.');
      return;
    }
    if (!form.coa_revenue_code) {
      setGalat('Akun pendapatan wajib dipilih — supaya omzet toko punya alamat jurnal.');
      return;
    }

    setGalat('');
    setSubmitting(true);
    try {
      const shared = {
        account_name: form.account_name.trim(),
        username: form.username.trim() || null,
        group: form.group,
        has_api_integration: form.has_api_integration,
        pic_user_id: form.pic_user_id || null,
        // AUTO_REVENUE ⇒ kosong ⇒ server membuat akun "Penjualan – <nama toko>".
        coa_revenue_code: form.coa_revenue_code === AUTO_REVENUE ? null : form.coa_revenue_code,
        // coa_receivable_code tidak dikirim: akun piutang toko dibuat & diatur server (anak 1-1303).
        revenue_basis: form.revenue_basis,
        platform_warehouse_name: form.platform_warehouse_name.trim(),
        platform_shop_id: form.platform_shop_id.trim(),
      };
      let res;
      if (isEdit) {
        res = await fetch(`${API}/api/marketing/accounts/${account.id}`, {
          method: 'PUT',
          headers,
          body: JSON.stringify({ ...shared, status: form.status }),
        });
      } else {
        res = await fetch(`${API}/api/marketing/accounts`, {
          method: 'POST',
          headers,
          body: JSON.stringify({
            ...shared,
            account_code: form.account_code.trim().toUpperCase(),
            platform: form.platform,
          }),
        });
      }

      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || 'Gagal menyimpan akun');

      const saved = body.account || {};
      if (!isEdit && (saved.ar_account_code || saved.coa_revenue_code)) {
        toast.success(
          `Akun dibuat · piutang toko: ${saved.ar_account_code || '—'}`
          + (saved.coa_revenue_source === 'auto_store'
            ? ` · akun pendapatan toko baru: ${saved.coa_revenue_code}` : ''),
          { duration: 6000 },
        );
      } else {
        toast.success(isEdit ? 'Perubahan akun tersimpan' : 'Akun berhasil dibuat');
      }
      onOpenChange(false);
      if (onSaved) onSaved();
    } catch (err) {
      setGalat(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const judulBagian = 'pt-1 text-sm font-semibold text-foreground';
  return (
    <FormPopup open={open} onClose={() => onOpenChange(false)} ukuran="panjang" onSimpan={handleSubmit}
      menyimpan={submitting} galat={galat} testId="account-form-dialog"
      labelSimpan={isEdit ? 'Simpan perubahan' : 'Buat akun'}
      judul={isEdit ? `Ubah akun — ${account?.account_name || ''}` : 'Tambah akun toko'}
      keterangan={isEdit
        ? 'Identitas toko, PIC, dan tautan Keuangan (akun pendapatan, rekening pencairan, piutang).'
        : 'Daftarkan toko marketplace. Akun piutang dan akun pendapatan khusus toko ini dibuat otomatis.'}>
      {/* ── Identitas toko ─────────────────────────────────────────── */}
      <p className={judulBagian}>Identitas toko</p>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {!isEdit && (
          <Isian label="Kode akun" wajib htmlFor="acc-code" petunjuk="Kode unik (otomatis huruf besar)">
            <Input id="acc-code" value={form.account_code}
              onChange={e => setForm(f => ({ ...f, account_code: e.target.value.toUpperCase() }))}
              placeholder="TIKTOK-OUTFIT" data-testid="acc-code-input" />
          </Isian>
        )}
        <Isian label="Nama akun" wajib htmlFor="acc-name">
          <Input id="acc-name" value={form.account_name}
            onChange={e => setForm(f => ({ ...f, account_name: e.target.value }))}
            placeholder="TikTok Outfit Boutique" data-testid="acc-name-input" />
        </Isian>
        {!isEdit && (
          <Isian label="Platform" wajib>
            <Select value={form.platform} onValueChange={handlePlatformChange}>
              <SelectTrigger data-testid="acc-platform-select"><SelectValue /></SelectTrigger>
              <SelectContent>
                {PLATFORMS.map(p => <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </Isian>
        )}
        <Isian label="Grup">
          <Select value={form.group} onValueChange={v => setForm(f => ({ ...f, group: v }))}>
            <SelectTrigger data-testid="acc-group-select"><SelectValue /></SelectTrigger>
            <SelectContent>
              {GROUPS.map(g => <SelectItem key={g.value} value={g.value}>{g.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </Isian>
        <Isian label="Username platform" htmlFor="acc-username">
          <Input id="acc-username" value={form.username}
            onChange={e => setForm(f => ({ ...f, username: e.target.value }))}
            placeholder="outfit.boutique" data-testid="acc-username-input" />
        </Isian>
        {isEdit && (
          <Isian label="Status">
            <Select value={form.status} onValueChange={v => setForm(f => ({ ...f, status: v }))}>
              <SelectTrigger data-testid="acc-status-select"><SelectValue /></SelectTrigger>
              <SelectContent>
                {STATUSES.map(s => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </Isian>
        )}
        <Isian label="PIC (penanggung jawab)"
          petunjuk="Hanya pengguna Portal Toko. Tugas otomatis (input sales, peringatan kesehatan toko) diberikan ke PIC ini.">
          <Select
            value={form.pic_user_id || 'none'}
            onValueChange={v => setForm(f => ({ ...f, pic_user_id: v === 'none' ? '' : v }))}
          >
            <SelectTrigger data-testid="acc-pic-select" className="h-auto min-h-9 whitespace-normal text-left [&>span]:line-clamp-2"><SelectValue placeholder="Pilih PIC…" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="none">Tidak ada PIC</SelectItem>
              {form.pic_user_id && !users.some(u => u.id === form.pic_user_id) && (
                <SelectItem value={form.pic_user_id}>
                  {account?.pic_user_name || 'PIC tersimpan'}
                  <span className="text-muted-foreground text-xs ml-1">(tanpa akses Portal Toko)</span>
                </SelectItem>
              )}
              {users.map(u => (
                <SelectItem key={u.id} value={u.id}>
                  {u.name || u.email}
                  <span className="text-muted-foreground text-xs ml-1">({u.role})</span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Isian>
      </div>

      {/* ── Tautan Keuangan (F0.7) ──────────────────────────────────── */}
      <p className={`${judulBagian} border-t border-[var(--glass-border)] pt-4`}>Tautan Keuangan — alamat jurnal toko</p>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Isian label="Akun pendapatan" wajib
          petunjuk={form.coa_revenue_code === AUTO_REVENUE
            ? `Akun pendapatan khusus toko ini dibuat otomatis di kelompok ${platformLabel(form.platform)} saat disimpan.`
            : 'Omzet toko ini dibukukan ke akun tersebut (mis. 4-1122 TikTok Outfit Boutique).'}>
          <Select
            value={form.coa_revenue_code || undefined}
            onValueChange={v => setForm(f => ({ ...f, coa_revenue_code: v }))}
          >
            <SelectTrigger data-testid="acc-coa-revenue-select" className="h-auto min-h-9 whitespace-normal text-left [&>span]:line-clamp-2">
              <SelectValue placeholder="Pilih akun pendapatan…" />
            </SelectTrigger>
            <SelectContent className="max-h-72">
              {!isEdit && (
                <SelectGroup>
                  <SelectLabel>Otomatis (disarankan)</SelectLabel>
                  <SelectItem value={AUTO_REVENUE} data-testid="acc-coa-revenue-auto">
                    Akun baru otomatis: Penjualan – {form.account_name.trim() || 'nama toko'}
                  </SelectItem>
                </SelectGroup>
              )}
              {revRecommended.length > 0 && (
                <SelectGroup>
                  <SelectLabel>Disarankan untuk {platformLabel(form.platform)}</SelectLabel>
                  {revRecommended.map(o => (
                    <SelectItem key={o.code} value={o.code}>{o.code} · {o.name}</SelectItem>
                  ))}
                </SelectGroup>
              )}
              {revOthers.length > 0 && (
                <SelectGroup>
                  <SelectLabel>Akun penjualan lain</SelectLabel>
                  {revOthers.map(o => (
                    <SelectItem key={o.code} value={o.code}>{o.code} · {o.name}</SelectItem>
                  ))}
                </SelectGroup>
              )}
            </SelectContent>
          </Select>
        </Isian>
        <Isian label="Basis omzet" petunjuk="Angka yang dihitung sebagai omzet toko saat impor pesanan.">
          <Select value={form.revenue_basis} onValueChange={v => setForm(f => ({ ...f, revenue_basis: v }))}>
            <SelectTrigger data-testid="acc-revenue-basis-select" className="h-auto min-h-9 whitespace-normal text-left [&>span]:line-clamp-2"><SelectValue /></SelectTrigger>
            <SelectContent>
              {basisOptions.map(o => (
                <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Isian>
      </div>
      {revenueIsCatchAll && (
        <Notice tone="warning" icon={AlertTriangle} testId="acc-coa-revenue-catchall-hint">
          Ini <b>akun penampung</b> bersama, bukan akun khusus toko ini. Ganti bila akun toko sudah dibuat di
          Portal Keuangan › Bagan akun.
        </Notice>
      )}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Isian label="Rekening pencairan" petunjuk="Diatur Keuangan di Portal Keuangan › Saldo & pencairan marketplace.">
          <div className="flex min-h-9 items-center rounded-md border border-[var(--glass-border)] px-3 py-1.5 text-sm"
            data-testid="acc-coa-cash-readonly">
            {form.coa_cash_code
              ? <span>{form.coa_cash_code} · {(cashOptions.find(o => o.code === form.coa_cash_code) || {}).name || ''}</span>
              : <span className="text-[hsl(var(--warning-text))]">Belum ditautkan</span>}
          </div>
        </Isian>
        <Isian label="Akun saldo platform (piutang toko)"
          petunjuk="Dibuat otomatis sebagai anak 1-1303. Dana yang dilepas platform masuk ke akun ini dan berkurang saat ditarik ke rekening pencairan. Saldonya = uang toko yang masih di platform.">
          <p className="text-sm">
            {account?.ar_account_code
              ? <span className="text-foreground" data-testid="acc-ar-account-code">{account.ar_account_code}</span>
              : <span className="text-muted-foreground">Terbentuk saat toko disimpan</span>}
          </p>
        </Isian>
      </div>

      {/* ── Data platform ──────────────────────────────────────────── */}
      <p className={`${judulBagian} border-t border-[var(--glass-border)] pt-4`}>Data platform (untuk impor Seller Center)</p>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Isian label="Nama gudang di platform" htmlFor="acc-warehouse"
          petunjuk='Persis seperti kolom "Warehouse Name" pada ekspor pesanan.'>
          <Input id="acc-warehouse" value={form.platform_warehouse_name}
            onChange={e => setForm(f => ({ ...f, platform_warehouse_name: e.target.value }))}
            placeholder="Outfit Boutique" data-testid="acc-warehouse-input" />
        </Isian>
        <Isian label="Shop ID platform" htmlFor="acc-shopid">
          <Input id="acc-shopid" value={form.platform_shop_id}
            onChange={e => setForm(f => ({ ...f, platform_shop_id: e.target.value }))}
            placeholder="7495123456789" data-testid="acc-shopid-input" />
        </Isian>
      </div>
      <label className="flex items-center justify-between gap-3 text-sm" htmlFor="acc-api">
        <span>
          <span className="block text-foreground">Integrasi API platform</span>
          <span className="block text-xs text-muted-foreground">Aktifkan bila toko ini sudah tersambung API resmi.</span>
        </span>
        <Switch id="acc-api" checked={form.has_api_integration}
          onCheckedChange={v => setForm(f => ({ ...f, has_api_integration: v }))} data-testid="acc-api-switch" />
      </label>
    </FormPopup>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// MODUL UTAMA
// ════════════════════════════════════════════════════════════════════════════
function AccountManagementBase({ token, onAksi, onScoring }) {
  const [loading, setLoading] = useState(true);
  const [accounts, setAccounts] = useState([]);
  const [coa, setCoa] = useState({});
  const [users, setUsers] = useState([]);
  const [filter, setFilter] = useState({ platform: 'all', status: 'all', group: 'all' });
  const [search, setSearch] = useState('');
  const [onlyReview, setOnlyReview] = useState(false);
  const [onlyNoPic, setOnlyNoPic] = useState(false);
  const [viewMode, setViewMode] = useState('table');   // 'table' (default) | 'cards'
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editAccount, setEditAccount] = useState(null);
  const [detail, setDetail] = useState(null);
  const [reviewingId, setReviewingId] = useState(null);
  const [scoring, setScoring] = useState(false);

  const headers = useMemo(
    () => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }),
    [token],
  );

  const fetchAccounts = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filter.platform !== 'all') params.append('platform', filter.platform);
      if (filter.status !== 'all') params.append('status', filter.status);
      if (filter.group !== 'all') params.append('group', filter.group);
      const res = await fetch(`${API}/api/marketing/accounts?${params.toString()}`, { headers });
      if (!res.ok) throw new Error('Gagal memuat akun');
      const data = await res.json();
      setAccounts(Array.isArray(data) ? data : []);
    } catch (e) {
      toast.error(e.message || 'Gagal memuat akun');
    } finally {
      setLoading(false);
    }
  }, [filter, headers]);

  /** Opsi COA + daftar user (dropdown form) — sekali saja saat modul dibuka. */
  const fetchRefs = useCallback(async () => {
    try {
      const [rc, ru] = await Promise.all([
        fetch(`${API}/api/marketing/accounts/coa-options`, { headers }),
        // MK3 (7 Nov 2026): calon PIC = pengguna yang punya akses Portal Toko (aturan akses yang sama dengan menu)
        fetch(`${API}/api/auth/users?portal=toko&limit=500`, { headers }),
      ]);
      if (rc.ok) setCoa(await rc.json());
      if (ru.ok) {
        const u = await ru.json();
        setUsers(Array.isArray(u) ? u : (u.items || u.users || []));
      }
    } catch {
      toast.error('Gagal memuat daftar akun COA / pengguna');
    }
  }, [headers]);

  useEffect(() => { fetchAccounts(); }, [fetchAccounts]);
  useEffect(() => { fetchRefs(); }, [fetchRefs]);

  const { data: balanceData } = usePlatformBalances(accounts.length);
  const balanceMap = useMemo(() => {
    const m = {};
    (balanceData?.data || []).forEach(b => { m[b.account_id] = b; });
    return m;
  }, [balanceData]);

  /** code → nama akun COA (untuk kolom tabel & kartu). */
  const coaNameMap = useMemo(() => {
    const m = {};
    [...(coa.revenue || []), ...(coa.cash || []), ...(coa.receivable || [])]
      .forEach(o => { m[o.code] = o.name; });
    return m;
  }, [coa]);

  /**
   * Akun "penampung" = akun pendapatan bersama (mis. 4-114 Shopee Lain-lain),
   * BUKAN akun milik toko itu sendiri. 4-131 Tokopedia dipakai sebagai default
   * platform tetapi memang akun toko tersebut ⇒ jangan diberi label penampung.
   */
  const isCatchAll = useCallback(
    (code) => /lain[\s-]*lain/i.test(coaNameMap[code] || ''),
    [coaNameMap],
  );
  const basisLabel = useCallback((v) => {
    if (!v) return '—';
    return BASIS_SHORT[v] || v;
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return accounts.filter(a => {
      if (onlyReview && !a.needs_owner_review) return false;
      if (onlyNoPic && a.pic_user_name) return false;
      if (!q) return true;
      return [
        a.account_code, a.account_name, a.username, a.pic_user_name,
        a.coa_revenue_code, a.coa_cash_code, a.ar_account_code,
        a.platform_warehouse_name, a.platform_shop_id,
      ].some(v => (v || '').toString().toLowerCase().includes(q));
    });
  }, [accounts, search, onlyReview, onlyNoPic]);

  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(filtered, 25);

  const stats = useMemo(() => ({
    total: accounts.length,
    active: accounts.filter(a => a.status === 'active').length,
    noPic: accounts.filter(a => !a.pic_user_name).length,
    review: accounts.filter(a => a.needs_owner_review).length,
    noCoa: accounts.filter(a => !a.coa_revenue_code).length,
  }), [accounts]);

  const handleEdit = (acc) => { setEditAccount(acc); setDialogOpen(true); };
  const handleCreate = () => { setEditAccount(null); setDialogOpen(true); };

  // Tombol kepala halaman (Tambah akun, Hitung ulang skor) ada di cetakan induk — handler diteruskan lewat ref
  // supaya identitasnya stabil (tidak memicu render berulang).
  const aksiRef = useRef({});
  useEffect(() => { onScoring?.(scoring); }, [scoring, onScoring]);
  useEffect(() => {
    onAksi?.({ create: () => aksiRef.current.create?.(), recompute: () => aksiRef.current.recompute?.() });
  }, [onAksi]);

  const handleArchive = async (acc) => {
    const ok = await confirmDialog({
      title: 'Arsipkan akun?',
      body: `${acc.account_name} menjadi nonaktif. Data akun, riwayat penjualan, dan tautan akun keuangan tidak dihapus.`,
      confirmLabel: 'Arsipkan', danger: true,
    });
    if (!ok) return;
    try {
      const res = await fetch(`${API}/api/marketing/accounts/${acc.id}`, {
        method: 'DELETE', headers,
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || 'Gagal mengarsipkan akun');
      toast.success('Akun diarsipkan (status nonaktif)');
      setDetail(null);
      fetchAccounts();
    } catch (e) {
      toast.error(e.message);
    }
  };

  /** Hapus permanen — server menolak (409) bila toko sudah punya data; alasannya ditampilkan apa adanya. */
  const handleDeletePermanent = async (acc) => {
    const ok = await confirmDialog({
      title: 'Hapus toko permanen?',
      body: `${acc.account_code} · ${acc.account_name} dihapus dan tidak bisa dikembalikan. Hanya bisa untuk toko yang belum `
        + 'punya data (pesanan, katalog, sales, jurnal, dan lainnya); bila sudah ada, sistem menolak dan menyebut datanya. '
        + 'Akun penjualan dan piutang yang dibuat otomatis untuk toko ini ikut dinonaktifkan di Bagan Akun.',
      confirmLabel: 'Hapus permanen', danger: true,
    });
    if (!ok) return;
    try {
      const res = await fetch(`${API}/api/marketing/accounts/${acc.id}/permanent`, {
        method: 'DELETE', headers,
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || 'Gagal menghapus toko');
      toast.success(body.message || 'Toko dihapus permanen');
      setDetail(null);
      fetchAccounts();
    } catch (e) {
      toast.error(e.message, { duration: 10000 });
    }
  };

  /** BD-5 — owner sudah mengoreksi nama/PIC/rekening toko hasil seed. */
  const markReviewed = async (acc) => {
    setReviewingId(acc.id);
    try {
      const res = await fetch(`${API}/api/marketing/accounts/${acc.id}`, {
        method: 'PUT', headers, body: JSON.stringify({ needs_owner_review: false }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || 'Gagal menandai akun');
      toast.success(`${acc.account_name} ditandai sudah ditinjau`);
      fetchAccounts();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setReviewingId(null);
    }
  };

  /** Skor sehat 1–5 dihitung dari data 30 hari terakhir seluruh toko. */
  const recomputeHealth = async () => {
    setScoring(true);
    try {
      const res = await fetch(`${API}/api/marketing/accounts/health/recompute-all`, {
        method: 'POST', headers,
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || 'Gagal menghitung skor');
      toast.success(body.message || 'Skor sehat diperbarui', { duration: 6000 });
      fetchAccounts();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setScoring(false);
    }
  };

  aksiRef.current = { create: handleCreate, recompute: recomputeHealth };

  const resetFilters = () => {
    setFilter({ platform: 'all', status: 'all', group: 'all' });
    setSearch('');
    setOnlyReview(false);
    setOnlyNoPic(false);
  };

  const serverFilterAktif = filter.platform !== 'all' || filter.status !== 'all' || filter.group !== 'all';
  const activeFilterCount =
    (filter.platform !== 'all' ? 1 : 0) + (filter.status !== 'all' ? 1 : 0) +
    (filter.group !== 'all' ? 1 : 0) + (search ? 1 : 0) + (onlyReview ? 1 : 0) + (onlyNoPic ? 1 : 0);

  const saldo = (acc) => (acc.ar_account_code ? Number(balanceMap[acc.id]?.balance || 0) : null);

  // ── semua aksi satu toko (menu "Lainnya" di baris & tombol di popup detail) ──
  const aksiToko = (acc) => {
    if (!canManageStores()) return [];
    const out = [];
    out.push({ key: 'edit', label: 'Ubah akun', icon: Pencil, testId: `edit-acc-${acc.account_code}`, run: () => handleEdit(acc) });
    if (acc.needs_owner_review) {
      out.push({ key: 'review', label: 'Tandai sudah ditinjau', icon: BadgeCheck, testId: `mark-reviewed-${acc.account_code}`,
        disabled: reviewingId === acc.id, run: () => markReviewed(acc) });
    }
    out.push({ key: 'archive', label: 'Arsipkan akun', icon: Archive, testId: `archive-acc-${acc.account_code}`, bahaya: true,
      run: () => handleArchive(acc) });
    if (canDeleteStores()) {
      out.push({ key: 'delete', label: 'Hapus permanen', icon: Trash2, testId: `delete-acc-${acc.account_code}`, bahaya: true,
        run: () => handleDeletePermanent(acc) });
    }
    return out;
  };

  const menuAksi = (acc, kecuali = []) => {
    const daftar = aksiToko(acc).filter(a => !kecuali.includes(a.key));
    if (!daftar.length) return null;
    return (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="icon-sm" variant="ghost" aria-label="Aksi lain" title="Aksi lain" data-testid={`acc-more-${acc.account_code}`}>
            <MoreHorizontal />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {daftar.map((a, i) => (
            <Fragment key={a.key}>
              {a.bahaya && !daftar[i - 1]?.bahaya && <DropdownMenuSeparator />}
              <DropdownMenuItem onSelect={() => a.run()} disabled={a.disabled} data-testid={a.testId}
                className={a.bahaya ? 'text-[hsl(var(--danger-text))]' : undefined}>
                <a.icon className="mr-2 h-4 w-4" />{a.label}
              </DropdownMenuItem>
            </Fragment>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    );
  };

  const kolom = [
    { kunci: 'toko', label: 'Toko', hp: 'judul', isi: (acc) => (
      <div className="min-w-0 md:max-w-[16rem]" data-testid={`acc-row-${acc.account_code}`}>
        <p className="truncate font-medium text-foreground" title={acc.account_name}>{acc.account_name}</p>
        <p className="text-xs text-muted-foreground">
          {acc.account_code}
          {acc.is_demo ? ' · contoh' : ''}
        </p>
      </div>) },
    { kunci: 'platform', label: 'Platform', hp: 'keterangan', isi: (acc) => platformLabel(acc.platform) },
    { kunci: 'status', label: 'Status', isi: (acc) => (
      <div className="flex flex-wrap gap-1">
        <StatusBadge status={acc.status} label={statusLabel(acc.status)}
          tone={acc.status === 'active' ? 'success' : acc.status === 'suspended' ? 'danger' : 'muted'} />
        {acc.needs_owner_review && (
          <span title="Data hasil seed — owner perlu mengoreksi nama/PIC/rekening" data-testid={`acc-review-badge-${acc.account_code}`}>
            <StatusBadge status="tinjau" label="Perlu ditinjau" tone="warning" />
          </span>
        )}
      </div>) },
    { kunci: 'pic', label: 'PIC', isi: (acc) => (acc.pic_user_name
      ? <span className="text-sm">{acc.pic_user_name}</span>
      : <span className="text-sm text-[hsl(var(--warning-text))]">Belum ada PIC</span>) },
    { kunci: 'pendapatan', label: 'Akun pendapatan', isi: (acc) => (
      <CoaCell code={acc.coa_revenue_code} name={coaNameMap[acc.coa_revenue_code]}
        fallback={isCatchAll(acc.coa_revenue_code)} testId={`acc-coa-rev-${acc.account_code}`} />) },
    { kunci: 'saldo', label: 'Saldo platform', rata: 'kanan', isi: (acc) => (acc.ar_account_code
      ? <span className="tabular-nums md:whitespace-nowrap" data-testid={`acc-platform-balance-${acc.account_code}`}
          title={`Akun piutang toko ${acc.ar_account_code}`}>{formatRupiah(saldo(acc))}</span>
      : <span className="text-sm text-[hsl(var(--warning-text))]">Belum terbentuk</span>) },
    { kunci: 'skor', label: 'Skor', isi: (acc) => (
      <HealthStars score={acc.health_score} grade={acc.health_grade} label={acc.health_label}
        breakdown={acc.health_breakdown} testId={`acc-health-${acc.account_code}`} />) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (acc) => (
      <div className="flex items-center justify-end gap-1">
        <Button size="sm" variant="outline" onClick={() => setDetail(acc)} data-testid={`acc-detail-${acc.account_code}`}>
          <Eye />Rincian
        </Button>
        {menuAksi(acc)}
      </div>) },
  ];

  const unduhKolom = [
    { label: 'Kode', nilai: (a) => a.account_code },
    { label: 'Nama akun', nilai: (a) => a.account_name },
    { label: 'Platform', nilai: (a) => platformLabel(a.platform) },
    { label: 'Grup', nilai: (a) => groupLabel(a.group) },
    { label: 'Username', nilai: (a) => a.username || '' },
    { label: 'Status', nilai: (a) => statusLabel(a.status) },
    { label: 'Perlu ditinjau', nilai: (a) => (a.needs_owner_review ? 'Ya' : 'Tidak') },
    { label: 'PIC', nilai: (a) => a.pic_user_name || '' },
    { label: 'Akun pendapatan', nilai: (a) => a.coa_revenue_code || '' },
    { label: 'Nama akun pendapatan', nilai: (a) => coaNameMap[a.coa_revenue_code] || '' },
    { label: 'Rekening pencairan', nilai: (a) => a.coa_cash_code || '' },
    { label: 'Akun piutang toko', nilai: (a) => a.ar_account_code || '' },
    { label: 'Saldo platform', nilai: (a) => (saldo(a) === null ? '' : saldo(a)) },
    { label: 'Basis omzet', nilai: (a) => basisLabel(a.revenue_basis) },
    { label: 'Gudang platform', nilai: (a) => a.platform_warehouse_name || '' },
    { label: 'Shop ID', nilai: (a) => a.platform_shop_id || '' },
    { label: 'Skor sehat (1–5)', nilai: (a) => (a.health_grade ?? '') },
  ];

  // ── Kartu (tampilan alternatif) ───────────────────────────────────────────
  const renderCard = (acc) => (
    <GlassCard key={acc.id} className="space-y-3 p-4" data-testid={`acc-card-${acc.account_code}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-foreground" title={acc.account_name}>{acc.account_name}</p>
          <p className="text-xs text-muted-foreground">{acc.account_code} · {platformLabel(acc.platform)}</p>
        </div>
        <HealthStars score={acc.health_score} grade={acc.health_grade} label={acc.health_label} breakdown={acc.health_breakdown} />
      </div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
        <dt className="text-muted-foreground">Status</dt><dd>{statusLabel(acc.status)}</dd>
        <dt className="text-muted-foreground">PIC</dt>
        <dd className={acc.pic_user_name ? '' : 'text-[hsl(var(--warning-text))]'}>{acc.pic_user_name || 'Belum ada PIC'}</dd>
        <dt className="text-muted-foreground">Pendapatan</dt><dd>{acc.coa_revenue_code || '—'}</dd>
        <dt className="text-muted-foreground">Saldo platform</dt>
        <dd className="tabular-nums">{acc.ar_account_code ? formatRupiah(saldo(acc)) : '—'}</dd>
      </dl>
      <div className="flex items-center justify-between gap-2 border-t border-[var(--glass-border)] pt-3">
        <Button size="sm" variant="outline" onClick={() => setDetail(acc)} data-testid={`edit-acc-card-${acc.account_code}`}>
          <Eye />Rincian
        </Button>
        {menuAksi(acc)}
      </div>
    </GlassCard>
  );

  const kosong = (
    // 2026-11-05: staf berlingkup toko yang belum memegang toko diberi tahu SEBAB & jalan keluarnya.
    <EmptyState
      icon={Store}
      title={accounts.length === 0
        ? (isStoreScopedUser() ? 'Belum ada toko yang Anda pegang' : 'Belum ada akun toko')
        : 'Tidak ada akun yang cocok dengan saringan'}
      description={accounts.length === 0
        ? (isStoreScopedUser() ? NO_STORE_HINT : 'Tambahkan toko marketplace pertama beserta tautan Keuangannya.')
        : 'Ubah kata pencarian atau bersihkan saringan untuk melihat toko lain.'}
      testId="accounts-empty-state"
      action={accounts.length === 0 && isStoreScopedUser() ? null : accounts.length === 0 ? (
        canManageStores() && (
          <Button onClick={handleCreate} data-testid="create-first-account-btn"><Plus />Tambah akun pertama</Button>
        )
      ) : (
        <Button variant="outline" onClick={resetFilters}>Bersihkan saringan</Button>
      )}
    />
  );

  return (
    <>
      <Toolbar
        filters={<>
          <div className="relative w-full sm:w-64">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input className="pl-8" placeholder="Kode, nama, username, akun, shop ID" value={search}
              onChange={e => setSearch(e.target.value)} data-testid="acc-search-input" />
          </div>
          <SmartNativeSelect className="w-40" value={filter.platform} data-testid="filter-platform"
            onChange={e => setFilter(f => ({ ...f, platform: e.target.value }))}>
            <option value="all">Semua platform</option>
            {PLATFORMS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
          </SmartNativeSelect>
          <SmartNativeSelect className="w-40" value={filter.status} data-testid="filter-status"
            onChange={e => setFilter(f => ({ ...f, status: e.target.value }))}>
            <option value="all">Semua status</option>
            {STATUSES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
          </SmartNativeSelect>
          <SmartNativeSelect className="w-40" value={filter.group} data-testid="filter-group"
            onChange={e => setFilter(f => ({ ...f, group: e.target.value }))}>
            <option value="all">Semua grup</option>
            {GROUPS.map(g => <option key={g.value} value={g.value}>{g.label}</option>)}
          </SmartNativeSelect>
          {activeFilterCount > 0 && (
            <Button variant="link" size="sm" onClick={resetFilters} data-testid="reset-filters-btn">
              <X />Bersihkan ({activeFilterCount})
            </Button>
          )}
        </>}
        tools={<>
          <TombolUnduh namaBerkas="master-toko-marketing" namaLembar="Toko" baris={filtered} kolom={unduhKolom}
            testId="accounts-export-csv" />
          <ViewToggle value={viewMode === 'cards' ? 'grid' : 'table'} onChange={(v) => setViewMode(v === 'grid' ? 'cards' : 'table')}
            testId="view-mode" />
          <Button variant="outline" size="icon" onClick={fetchAccounts} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
            data-testid="refresh-accounts-btn">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
        </>} />

      {/* Ringkasan satu kalimat — dihitung dari daftar toko yang dimuat (ikut saringan platform/status/grup bila
          dipakai). Dulu 5 kartu; dua di antaranya tombol saring — kini tautan di kalimat ini. */}
      <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-sm text-muted-foreground" data-testid="acc-ringkasan">
        <span data-testid="stat-total-accounts"><b className="text-foreground">{stats.total}</b> toko{serverFilterAktif ? ' (sesuai saringan)' : ''}</span>
        <span>· <b className="text-foreground">{stats.active}</b> aktif ·</span>
        <Button variant="link" size="sm" className="h-auto p-0" data-testid="stat-nopic-accounts" aria-pressed={onlyNoPic}
          onClick={() => { setOnlyNoPic(v => !v); setOnlyReview(false); }}
          title={onlyNoPic ? 'Klik lagi untuk melihat semua' : 'Tampilkan toko tanpa penanggung jawab'}>
          <span className={stats.noPic ? 'text-[hsl(var(--warning-text))]' : ''}>{stats.noPic} tanpa PIC</span>
        </Button>
        <span>·</span>
        <Button variant="link" size="sm" className="h-auto p-0" data-testid="stat-review-accounts" aria-pressed={onlyReview}
          onClick={() => { setOnlyReview(v => !v); setOnlyNoPic(false); }}
          title={onlyReview ? 'Klik lagi untuk melihat semua' : 'Data seed yang belum dikoreksi owner'}>
          <span className={stats.review ? 'text-[hsl(var(--warning-text))]' : ''}>{stats.review} perlu ditinjau</span>
        </Button>
        <span>·</span>
        <span data-testid="stat-nocoa-accounts" title="Omzetnya belum punya alamat jurnal"
          className={stats.noCoa ? 'text-[hsl(var(--danger-text))]' : ''}>{stats.noCoa} tanpa akun pendapatan</span>
        {(onlyReview || onlyNoPic) && (
          <span className="flex flex-wrap items-center gap-1.5" data-testid="acc-quick-filter">
            <span>— menampilkan {filtered.length} dari {accounts.length} toko</span>
            {onlyReview && <StatusBadge status="tinjau" label="Hanya perlu ditinjau" tone="warning" />}
            {onlyNoPic && <StatusBadge status="nopic" label="Hanya tanpa PIC" tone="warning" />}
            <Button variant="link" size="sm" className="h-auto p-0" onClick={() => { setOnlyReview(false); setOnlyNoPic(false); }}>
              Tampilkan semua
            </Button>
          </span>
        )}
      </p>

      {/* Daftar */}
      {loading && accounts.length === 0 ? (
        <div className="space-y-2" data-testid="accounts-loading">
          {[1, 2, 3, 4, 5, 6].map(i => <Skeleton key={i} className="h-12" />)}
        </div>
      ) : viewMode === 'table' ? (
        <div data-testid="accounts-table-wrap">
          <TabelData kolom={kolom} baris={paged} onKlikBaris={setDetail} testId="accounts-table" kosong={kosong} />
        </div>
      ) : filtered.length === 0 ? kosong : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3" data-testid="accounts-cards">
          {paged.map(acc => renderCard(acc))}
        </div>
      )}
      <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />

      {/* Rincian satu toko (popup) — semua kolom & aksi */}
      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} judul={detail.account_name} testId="account-detail"
          keterangan={`${detail.account_code} · ${platformLabel(detail.platform)} · grup ${groupLabel(detail.group)}`}
          status={<>
            <StatusBadge status={detail.status} label={statusLabel(detail.status)}
              tone={detail.status === 'active' ? 'success' : detail.status === 'suspended' ? 'danger' : 'muted'} />
            {detail.needs_owner_review && <StatusBadge status="tinjau" label="Perlu ditinjau" tone="warning" />}
          </>}
          aksi={canManageStores() ? <>
            <Button size="sm" variant="outline" onClick={() => { const a = detail; setDetail(null); handleEdit(a); }}
              data-testid="account-detail-edit"><Pencil />Ubah</Button>
            {detail.needs_owner_review && (
              <Button size="sm" variant="success" onClick={() => markReviewed(detail)} disabled={reviewingId === detail.id}
                data-testid="account-detail-reviewed">
                {reviewingId === detail.id ? <Loader2 className="animate-spin" /> : <BadgeCheck />}Tandai sudah ditinjau
              </Button>
            )}
            {menuAksi(detail, ['edit', 'review'])}
          </> : null}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Username platform">{detail.username || '—'}</BarisDetail>
            <BarisDetail label="PIC">{detail.pic_user_name || <span className="text-[hsl(var(--warning-text))]">Belum ada PIC</span>}</BarisDetail>
            <BarisDetail label="Akun pendapatan">
              <CoaCell code={detail.coa_revenue_code} name={coaNameMap[detail.coa_revenue_code]} fallback={isCatchAll(detail.coa_revenue_code)} />
            </BarisDetail>
            <BarisDetail label="Rekening pencairan">
              <CoaCell code={detail.coa_cash_code} name={coaNameMap[detail.coa_cash_code]} />
            </BarisDetail>
            <BarisDetail label="Saldo platform (piutang toko)">
              {detail.ar_account_code
                ? <span><span data-testid={`acc-ar-${detail.account_code}`}>{detail.ar_account_code}</span> · <span className="tabular-nums">{formatRupiah(saldo(detail))}</span></span>
                : <span className="text-[hsl(var(--warning-text))]">Belum terbentuk</span>}
            </BarisDetail>
            <BarisDetail label="Basis omzet">{basisLabel(detail.revenue_basis)}</BarisDetail>
            <BarisDetail label="Gudang di platform">{detail.platform_warehouse_name || '—'}</BarisDetail>
            <BarisDetail label="Shop ID platform">{detail.platform_shop_id || '—'}</BarisDetail>
            <BarisDetail label="Integrasi API">{detail.credentials?.has_api_integration ? 'Tersambung' : 'Belum'}</BarisDetail>
            <BarisDetail label="Skor sehat">
              <HealthStars score={detail.health_score} grade={detail.health_grade} label={detail.health_label} breakdown={detail.health_breakdown} />
              {detail.health_breakdown && Object.keys(detail.health_breakdown).length > 0 && (
                <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
                  {Object.values(detail.health_breakdown).map((b) => <li key={b.label}>{b.label}: {b.score}/{b.max}</li>)}
                </ul>
              )}
            </BarisDetail>
          </dl>
        </DetailPopup>
      )}

      <AccountFormDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        account={editAccount}
        onSaved={fetchAccounts}
        token={token}
        coa={coa}
        users={users}
      />
    </>
  );
}


// ════════════════════════════════════════════════════════════════════════════
// F6.4 (2026-08-13) — SATU PINTU: "Daftar toko" + pemegang toko (per toko · per staf · riwayat).
// Dibungkus di sini, BUKAN sebagai menu baru (pintu kembar ditolak guardrail `check_nav_map`).
// Standar UI/UX v2: satu baris tab (dulu tombol buatan + tab kedua di dalamnya), cetakan PageLayout.
// ════════════════════════════════════════════════════════════════════════════
const TAB_AKUN = [
  { key: 'daftar', label: 'Daftar toko' },
  { key: 'toko', label: 'Pemegang per toko' },
  { key: 'staf', label: 'Pemegang per staf' },
  { key: 'riwayat', label: 'Riwayat pemegang' },
];

export default function AccountManagementModule(props) {
  const [tab, setTab] = useState('daftar');
  const [scoring, setScoring] = useState(false);
  const [aksi, setAksi] = useState(null);   // {create, recompute} dari daftar toko
  const { onNavigate } = props;
  const actions = tab === 'daftar' && canManageStores() && aksi ? (<>
    {/* 2026-11-05: menambah/mengubah toko hanya owner/admin/SPV/manager */}
    <Button onClick={aksi.recompute} variant="outline" disabled={scoring} data-testid="recompute-health-btn"
      title="Hitung ulang skor sehat 1–5 dari data 30 hari terakhir">
      {scoring ? <Loader2 className="animate-spin" /> : <Calculator />}Hitung ulang skor
    </Button>
    <Button variant="outline" data-testid="open-bulk-review-btn"
      onClick={() => (onNavigate ? onNavigate('marketing-account-review') : (window.location.hash = 'marketing-account-review'))}>
      <ClipboardCheck />Koreksi data toko
    </Button>
    <Button onClick={aksi.create} data-testid="create-account-btn"><Plus />Tambah akun</Button>
  </>) : null;
  return (
    <PageLayout testId="account-management-module" title="Kelola akun"
      subtitle="Toko Shopee, TikTok Shop, dan Tokopedia beserta PIC, pemegang, dan tautan Keuangannya."
      actions={actions}>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="h-auto max-w-full justify-start gap-1 max-sm:flex-nowrap max-sm:overflow-x-auto sm:flex-wrap"
          data-testid="accounts-tabs">
          {TAB_AKUN.map(t => (
            <TabsTrigger key={t.key} value={t.key} className="shrink-0" data-testid={`accounts-tab-${t.key === 'daftar' ? 'daftar' : `assign-${t.key}`}`}>
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      {tab === 'daftar'
        ? <AccountManagementBase {...props} onAksi={setAksi} onScoring={setScoring} />
        : <AccountAssignView token={props.token} view={tab} />}
    </PageLayout>
  );
}

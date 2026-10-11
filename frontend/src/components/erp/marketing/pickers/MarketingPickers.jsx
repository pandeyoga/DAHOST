/**
 * MarketingPickers — pemilih MASTER untuk seluruh form marketing.
 *
 * KENAPA BERKAS INI ADA
 * ---------------------
 * Audit 2026-08-11 menemukan 57 field yang seharusnya menunjuk baris di tabel
 * lain tapi diisi sebagai TEKS BEBAS: nama produk diketik ulang, username
 * kreator diketik ulang, nama toko diketik ulang, ukuran & warna diketik ulang.
 * Akibatnya satu barang/orang/toko bisa punya beberapa ejaan, dan laporan
 * memecahnya menjadi beberapa baris tanpa ada yang tahu mana yang benar.
 *
 * Empat pemilih di bawah menggantikan pola itu, dan sengaja dikumpulkan dalam
 * SATU berkas supaya semua layar marketing memakai perilaku yang sama:
 *   · daftar diambil dari server (bukan disalin ke kode layar),
 *   · kreator/host DISARING per toko oleh SERVER (`/data-import/context-options`),
 *     jadi layar yang lupa menyaring tidak mungkin melahirkan pembebanan salah,
 *   · keadaan kosong menjelaskan APA yang harus dilakukan, bukan hanya "no data".
 */
import React, { useEffect, useState, useMemo, useCallback } from 'react';
import { Store, Users, Video, Package, AlertCircle, Loader2 } from 'lucide-react';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import axios from 'axios';
import { currentRole } from '../../portalAccess';

const API = process.env.REACT_APP_BACKEND_URL;

const PLATFORM_ICON = {
  shopee: '🛍️', tiktok: '🎵', tiktokshop: '🎵', tokopedia: '🟢',
  instagram: '📷', lazada: '🔵', blibli: '🔷', website: '🌐',
};
export const platformIcon = (p) => PLATFORM_ICON[String(p || '').toLowerCase()] || '🛒';

function authHeader(token) {
  return { Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` };
}

/** Pesan kosong yang bisa ditindaklanjuti — bukan "tidak ada data". */
// Sama dengan `core.marketing_account_scope.SCOPED_ROLES` (backend = SSOT).
const SCOPED_ROLES = ['staff_marketing', 'pic_toko', 'host_live', 'cs_staff'];

function EmptyHint({ children }) {
  return (
    <div className="flex items-start gap-1.5 mt-1 text-[11px] text-amber-700 dark:text-amber-400">
      <AlertCircle className="w-3.5 h-3.5 mt-px shrink-0" />
      <span>{children}</span>
    </div>
  );
}

function FieldLabel({ icon: Icon, children, required }) {
  // Layar yang sudah punya label sendiri memanggil pemilih dengan `label=""`.
  // Tanpa penjagaan ini, baris label kosong tetap dirender dan menyisakan ikon +
  // tanda bintang yang menggantung di bawah label asli — tampak seperti cacat.
  const hasText = children !== undefined && children !== null
    && String(children).trim() !== '';
  if (!hasText) return null;
  return (
    <label className="flex items-center gap-1.5 text-xs font-medium text-foreground/80 mb-1">
      {Icon && <Icon className="w-3.5 h-3.5" />}
      {children}
      {required && <span className="text-red-500">*</span>}
    </label>
  );
}

/* ─────────────────────────── AKUN / TOKO ─────────────────────────── */
export function MarketingAccountSelect({
  token, value, onChange, label = 'Toko / Akun', required = true,
  includeAll = false, allLabel = 'Semua Toko', testId = 'account-select',
  disabled = false, className = '',
}) {
  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await axios.get(`${API}/api/marketing/accounts`, {
          headers: authHeader(token), params: { status: 'active' },
        });
        const list = Array.isArray(res.data) ? res.data
          : (res.data?.accounts || res.data?.data || []);
        if (alive) setAccounts(list);
      } catch (e) {
        if (alive) setAccounts([]);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [token]);

  const selected = useMemo(
    () => accounts.find((a) => a.id === value) || null, [accounts, value]);

  return (
    <div className={className}>
      <FieldLabel icon={Store} required={required && !includeAll}>{label}</FieldLabel>
      <Select
        value={value || (includeAll ? '__all__' : '')}
        onValueChange={(v) => onChange(v === '__all__' ? '' : v)}
        disabled={disabled || loading}
      >
        <SelectTrigger data-testid={testId} className="h-9">
          <SelectValue placeholder={loading ? 'Memuat toko…' : 'Pilih toko…'} />
        </SelectTrigger>
        <SelectContent>
          {includeAll && <SelectItem value="__all__">{allLabel}</SelectItem>}
          {accounts.map((a) => (
            <SelectItem key={a.id} value={a.id}>
              {platformIcon(a.platform)} {a.account_name || a.name}
              <span className="text-muted-foreground ml-1 text-xs">({a.platform})</span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {!loading && accounts.length === 0 && (
        SCOPED_ROLES.includes(currentRole()) ? (
          /* Staf berlingkup toko TIDAK bisa membuat toko. Menyuruhnya "buat dulu di
             Kelola Akun" adalah jalan buntu yang menyalahkan pemakai untuk keadaan
             yang hanya bisa diubah SPV — dan menyembunyikan sebab sebenarnya. */
          <EmptyHint>Belum ada toko yang <b>di-assign kepada Anda</b>. Minta
            <b> SPV Marketing</b> meng-assign toko Anda (Manajemen Akun → tab
            <b> Assign Staf</b>). Toko lain memang tidak akan muncul di sini.</EmptyHint>
        ) : (
          <EmptyHint>Belum ada akun toko. Buat dulu di <b>Kelola Akun</b> — semua data
            marketing harus menempel pada satu toko.</EmptyHint>
        )
      )}
      {selected && (
        <p className="text-[11px] text-muted-foreground mt-1">
          Platform: <b>{selected.platform}</b>
          {selected.account_code ? <> · Kode: <b>{selected.account_code}</b></> : null}
        </p>
      )}
    </div>
  );
}

/* ────────── KONTEKS PER TOKO (kreator / host / katalog) ────────── */
/**
 * Satu panggilan server memberi kreator, host, dan katalog yang SAH untuk toko
 * terpilih. Penyaringan dikerjakan server (`context-options`) — bukan di browser —
 * supaya tidak ada layar yang bisa "lupa menyaring".
 */
export function useAccountContext(token, sourceType, accountId) {
  const [data, setData] = useState({ creators: [], hosts: [], catalogs: [] });
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!accountId) { setData({ creators: [], hosts: [], catalogs: [] }); return; }
    setLoading(true);
    try {
      const res = await axios.get(`${API}/api/marketing/data-import/context-options`, {
        headers: authHeader(token),
        params: { source_type: sourceType, account_id: accountId },
      });
      setData({
        creators: res.data?.creators || [],
        hosts: res.data?.hosts || [],
        catalogs: res.data?.catalogs || [],
      });
    } catch (e) {
      setData({ creators: [], hosts: [], catalogs: [] });
    } finally {
      setLoading(false);
    }
  }, [token, sourceType, accountId]);

  useEffect(() => { load(); }, [load]);
  return { ...data, loading, reload: load };
}

export function MarketingCreatorSelect({
  token, accountId, value, onChange, label = 'Kreator / KOL', required = true,
  testId = 'creator-select', className = '', includeAll = false,
}) {
  const { creators, loading } = useAccountContext(token, 'samples', accountId);
  return (
    <div className={className}>
      <FieldLabel icon={Users} required={required && !includeAll}>{label}</FieldLabel>
      <Select
        value={value || (includeAll ? '__all__' : '')}
        onValueChange={(v) => onChange(v === '__all__' ? '' : v)}
        disabled={!accountId || loading}
      >
        <SelectTrigger data-testid={testId} className="h-9">
          <SelectValue placeholder={
            !accountId ? 'Pilih toko dulu' : loading ? 'Memuat…' : 'Pilih kreator…'} />
        </SelectTrigger>
        <SelectContent>
          {includeAll && <SelectItem value="__all__">Semua Kreator</SelectItem>}
          {creators.map((c) => (
            <SelectItem key={c.id} value={c.id}>
              {c.name}
              {c.platforms?.tiktok ? <span className="text-muted-foreground ml-1 text-xs">{c.platforms.tiktok}</span> : null}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {accountId && !loading && creators.length === 0 && (
        <EmptyHint>Belum ada kreator yang di-assign ke toko ini. Assign dulu di
          <b> KOL &amp; Kreator</b> — kalau tidak, biaya sample akan menempel pada
          toko yang tidak memakainya.</EmptyHint>
      )}
    </div>
  );
}

export function MarketingHostSelect({
  token, accountId, value, onChange, label = 'Host Live', required = true,
  testId = 'host-select', className = '', includeAll = false,
}) {
  const { hosts, loading } = useAccountContext(token, 'live_sessions', accountId);
  return (
    <div className={className}>
      <FieldLabel icon={Video} required={required && !includeAll}>{label}</FieldLabel>
      <Select
        value={value || (includeAll ? '__all__' : '')}
        onValueChange={(v) => onChange(v === '__all__' ? '' : v)}
        disabled={!accountId || loading}
      >
        <SelectTrigger data-testid={testId} className="h-9">
          <SelectValue placeholder={
            !accountId ? 'Pilih toko dulu' : loading ? 'Memuat…' : 'Pilih host…'} />
        </SelectTrigger>
        <SelectContent>
          {includeAll && <SelectItem value="__all__">Semua Host</SelectItem>}
          {hosts.map((h) => (
            <SelectItem key={h.id} value={h.id}>
              {h.name}
              {h.employment_type ? <span className="text-muted-foreground ml-1 text-xs">({h.employment_type})</span> : null}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {accountId && !loading && hosts.length === 0 && (
        <EmptyHint>Belum ada host yang di-assign ke toko ini. Assign dulu di
          <b> Live Selling → LiveHost</b> — jam kerja &amp; bayaran host harus jatuh
          pada toko yang benar.</EmptyHint>
      )}
    </div>
  );
}

/* ─────────────────────── ITEM KATALOG (produk) ─────────────────────── */
/**
 * Memilih PRODUK dari katalog toko, bukan mengetik namanya. Saat dipilih,
 * `onChange` menerima seluruh dokumen item sehingga pemanggil bisa mengisi
 * SKU / HPP / harga jual dari MASTER — inilah yang menghentikan HPP diketik
 * manual (sumber "biaya sample Rp 0" pada laporan).
 */
export function CatalogItemSelect({
  token, accountId, value, onChange, label = 'Produk (dari katalog toko)',
  required = true, testId = 'catalog-item-select', className = '',
}) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      if (!accountId) { setItems([]); return; }
      setLoading(true);
      try {
        const cats = await axios.get(`${API}/api/marketing/catalogs`, {
          headers: authHeader(token), params: { account_id: accountId },
        });
        const list = cats.data?.catalogs || cats.data?.data || [];
        const all = [];
        for (const c of list) {
          const r = await axios.get(`${API}/api/marketing/catalogs/${c.id}/items`, {
            headers: authHeader(token), params: { page_size: 200 },
          });
          const its = r.data?.items || r.data?.data || [];
          all.push(...its.map((i) => ({ ...i, catalog_name: c.name })));
        }
        if (alive) setItems(all);
      } catch (e) {
        if (alive) setItems([]);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [token, accountId]);

  const selected = items.find((i) => i.id === value);

  return (
    <div className={className}>
      <FieldLabel icon={Package} required={required}>{label}</FieldLabel>
      <Select
        value={value || ''}
        onValueChange={(v) => onChange(items.find((i) => i.id === v) || null)}
        disabled={!accountId || loading}
      >
        <SelectTrigger data-testid={testId} className="h-9">
          <SelectValue placeholder={
            !accountId ? 'Pilih toko dulu'
              : loading ? <span className="flex items-center gap-1"><Loader2 className="w-3 h-3 animate-spin" />Memuat katalog…</span>
                : 'Pilih produk…'} />
        </SelectTrigger>
        <SelectContent className="max-h-72">
          {items.map((i) => (
            <SelectItem key={i.id} value={i.id}>
              <span className="font-mono text-[11px] text-muted-foreground mr-1.5">{i.sku}</span>
              {i.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {accountId && !loading && items.length === 0 && (
        <EmptyHint>Katalog toko ini masih kosong. Isi dulu di
          <b> Manajemen Katalog</b> — supaya SKU, HPP, dan harga jual tidak perlu
          diketik ulang di setiap form.</EmptyHint>
      )}
      {selected && (
        <p className="text-[11px] text-muted-foreground mt-1">
          HPP master: <b>Rp {Number(selected.hpp || 0).toLocaleString('id-ID')}</b>
          {' · '}Harga jual: <b>Rp {Number(selected.harga_jual || selected.price || 0).toLocaleString('id-ID')}</b>
          {selected.stock_quantity != null ? <> · Stok: <b>{selected.stock_quantity}</b></> : null}
        </p>
      )}
    </div>
  );
}

/* ─────────── MASTER WARNA / UKURAN / MODEL (Produksi & R&D) ─────────── */
export function useMasterList(path, token) {
  const [rows, setRows] = useState([]);
  useEffect(() => {
    let alive = true;
    axios.get(`${API}${path}`, { headers: authHeader(token) })
      .then((r) => { if (alive) setRows(Array.isArray(r.data) ? r.data : (r.data?.data || r.data?.items || [])); })
      .catch(() => { if (alive) setRows([]); });
    return () => { alive = false; };
  }, [path, token]);
  return rows.filter((r) => r.active !== false);
}

/** Pilih banyak nilai dari master (mis. warna/ukuran). `value` = array nama. */
export function MasterChipsSelect({ token, path, value = [], onChange, testId, emptyText }) {
  const rows = useMasterList(path, token);
  const toggle = (name) => onChange(value.includes(name) ? value.filter((v) => v !== name) : [...value, name]);
  return (
    <div className="flex flex-wrap gap-1.5 mt-1 max-h-32 overflow-auto p-1 rounded-md border border-input" data-testid={testId}>
      {rows.length === 0 && <span className="text-[11px] text-muted-foreground px-1">{emptyText || 'Master kosong'}</span>}
      {rows.map((r) => {
        const name = r.name || r.code;
        const on = value.includes(name);
        return (
          <button type="button" key={r.id || name} onClick={() => toggle(name)}
            data-testid={`${testId}-${r.code || name}`}
            className={`px-2 py-0.5 rounded text-[11px] border transition-colors ${on
              ? 'bg-primary text-primary-foreground border-primary'
              : 'border-foreground/15 text-foreground/70 hover:border-foreground/30'}`}>
            {r.hex && <span className="inline-block w-2 h-2 rounded-full mr-1 align-middle" style={{ background: r.hex }} />}
            {name}
          </button>
        );
      })}
    </div>
  );
}

/** Platform yang benar-benar dipakai toko aktif (Kelola Akun) — bukan daftar ketikan. */
export function useStorePlatforms(token) {
  const [list, setList] = useState([]);
  useEffect(() => {
    let alive = true;
    axios.get(`${API}/api/marketing/accounts`, { headers: authHeader(token), params: { status: 'active' } })
      .then((r) => {
        const rows = Array.isArray(r.data) ? r.data : (r.data?.accounts || r.data?.data || []);
        const norm = (p) => { const v = String(p || '').toLowerCase(); return v === 'tiktokshop' ? 'tiktok' : v; };
        if (alive) setList([...new Set(rows.map((a) => norm(a.platform)).filter(Boolean))]);
      })
      .catch(() => { if (alive) setList([]); });
    return () => { alive = false; };
  }, [token]);
  return list;
}

/** Pilih banyak SKU dari katalog (cari lintas toko). `value` = array SKU. */
export function CatalogSkuMultiSelect({ token, value = [], onChange, testId = 'catalog-sku-multi' }) {
  const [q, setQ] = useState('');
  const [hits, setHits] = useState([]);
  useEffect(() => {
    if (!q.trim()) { setHits([]); return undefined; }
    const t = setTimeout(() => {
      axios.get(`${API}/api/marketing/catalog-items/search`, { headers: authHeader(token), params: { q, limit: 15 } })
        .then((r) => setHits(r.data?.items || r.data?.data || []))
        .catch(() => setHits([]));
    }, 300);
    return () => clearTimeout(t);
  }, [q, token]);
  const add = (sku) => { if (sku && !value.includes(sku)) onChange([...value, sku]); setQ(''); setHits([]); };
  return (
    <div className="relative mt-1" data-testid={testId}>
      <div className="flex flex-wrap gap-1 mb-1">
        {value.map((s) => (
          <span key={s} className="px-2 py-0.5 rounded bg-muted text-[11px] font-mono flex items-center gap-1">
            {s}
            <button type="button" onClick={() => onChange(value.filter((x) => x !== s))} data-testid={`${testId}-remove-${s}`}>×</button>
          </span>
        ))}
      </div>
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari SKU / nama produk di katalog…"
        data-testid={`${testId}-search`}
        className="w-full h-9 border border-input bg-background rounded-md px-3 text-sm" />
      {hits.length > 0 && (
        <div className="absolute z-20 left-0 right-0 mt-1 max-h-48 overflow-auto rounded-md border border-input bg-popover shadow">
          {hits.map((i) => (
            <button type="button" key={i.id} onClick={() => add(i.sku)}
              className="w-full text-left px-3 py-1.5 text-xs hover:bg-muted" data-testid={`${testId}-hit-${i.sku}`}>
              <span className="font-mono mr-2">{i.sku}</span>{i.name}
              <span className="text-muted-foreground ml-1">{i.account_name || ''}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

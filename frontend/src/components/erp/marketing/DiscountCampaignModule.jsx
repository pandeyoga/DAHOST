/**
 * Kampanye diskon (Portal Toko) — kampanye promo multi-platform.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, penyaring satu baris, 4 StatTile berketerangan, tabel + unduh
 * Excel/CSV semua baris (dulu CSV halaman ini saja), detail popup, form = FormPopup + DatePicker, label Indonesia
 * (dulu kode mentah "semua_produk", "Upcoming", "Expired"). Panggilan API & isian tidak berubah.
 */
import { confirmDialog } from '@/components/ui/confirm-dialog';
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Plus, Pencil, Trash2, RefreshCw, AlertTriangle, Search } from 'lucide-react';
import axios from 'axios';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import { Textarea } from '@/components/ui/textarea';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import DatePicker from '@/components/ui/date-picker';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import PaginationLite from '@/components/ui/pagination-lite';
import { useToast } from '@/hooks/use-toast';
import { useMarketingAccounts } from '@/hooks/useMarketingAccounts';
import { formatRupiah, formatDateID } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';
import { getPlatformConfig } from './AccountBadge';
import { MarketingAccountSelect } from './pickers/MarketingPickers';

const API = process.env.REACT_APP_BACKEND_URL;

const PLATFORM_LABEL = { shopee: 'Shopee', tiktok: 'TikTok', tokopedia: 'Tokopedia', instagram: 'Instagram', semua_platform: 'Semua platform' };
const labelPlatform = (p) => PLATFORM_LABEL[p] || (getPlatformConfig(p).label !== 'Platform' ? getPlatformConfig(p).label : (p || '—'));
const STATUS_CONFIG = {
  active: { label: 'Aktif', tone: 'success' },
  upcoming: { label: 'Akan datang', tone: 'info' },
  expired: { label: 'Berakhir', tone: 'muted' },
  draft: { label: 'Draf', tone: 'warning' },
};
const StatusKampanye = ({ status }) => {
  const c = STATUS_CONFIG[status] || STATUS_CONFIG.draft;
  return <StatusBadge status={status} label={c.label} tone={c.tone} />;
};
const UNIT_LABEL = { persen: 'Persen (%)', nominal: 'Nominal (Rp)', unit: 'Unit' };
const labelCakupan = (v) => (v ? String(v).replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase()) : '—');
const tgl = (v) => (v ? formatDateID(String(v).slice(0, 10)) : '—');
const fmtRp = (n) => n ? formatRupiah(n) : '-';
function fmt(n)   { return new Intl.NumberFormat('id-ID').format(n || 0); }
const nilaiDiskon = (item) => (item.discount_value > 0
  ? (item.discount_unit === 'persen' ? `${String(item.discount_value).replace('.', ',')}%`
    : item.discount_unit === 'nominal' ? fmtRp(item.discount_value) : `${item.discount_value} unit`)
  : '—');
const sisaHari = (item) => {
  const d = item.days_remaining;
  if (d === null || d === undefined) return '';
  return d >= 0 ? `${d} hari lagi` : `berakhir ${Math.abs(d)} hari lalu`;
};

const EMPTY_FORM = {
  account_id: '', account_name: '', platform: 'shopee', name: '', discount_type: 'flash_sale',
  discount_value: '', discount_unit: 'persen', min_purchase: '', max_discount: '',
  start_date: '', end_date: '', description: '', product_scope: 'semua_produk'
};

const DISCOUNT_TYPE_LABELS = {
  flash_sale: 'Flash sale', voucher: 'Voucher / kupon', bundling: 'Bundling produk',
  buy_x_get_y: 'Beli X gratis Y', free_shipping: 'Gratis ongkir',
  diskon_persen: 'Diskon %', cashback: 'Cashback', giveaway: 'Giveaway',
};

export default function DiscountCampaignModule({ token }) {
  const { toast } = useToast();
  const authH = useMemo(() => ({ Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` }), [token]);
  const { accounts, byId: accountById } = useMarketingAccounts(token);

  const [summary, setSummary]     = useState(null);
  const [items,   setItems]       = useState([]);
  const [pagination, setPagination] = useState(null);
  const [loading, setLoading]     = useState(true);

  const [filterStatus,  setFilterStatus]  = useState('');
  const [filterPlatform,setFilterPlatform]= useState('');
  // F14 — filter per TOKO memakai account_id (SSOT), bukan mencocokkan nama toko.
  const [filterAccountId, setFilterAccountId] = useState('');
  const [filterType,    setFilterType]    = useState('');
  const [search,        setSearch]        = useState('');
  const [page,          setPage]          = useState(1);

  const [showForm,    setShowForm]    = useState(false);
  const [detail,      setDetail]      = useState(null);
  const [editTarget,  setEditTarget]  = useState(null);
  const [form,        setForm]        = useState(EMPTY_FORM);
  const [formLoading, setFormLoading] = useState(false);
  const [galatForm, setGalatForm] = useState('');

  const fetchSummary = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/api/marketing/discounts/summary`, { headers: authH });
      if (res.data.success) setSummary(res.data.data);
    } catch {}
  }, [authH]);

  const fetchItems = useCallback(async () => {
    setLoading(true);
    try {
      const params = { page, page_size: 20 };
      if (filterStatus)   params.status = filterStatus;
      if (filterPlatform) params.platform = filterPlatform;
      if (filterAccountId) params.account_id = filterAccountId;
      if (filterType)     params.discount_type = filterType;
      if (search)         params.search = search;
      const res = await axios.get(`${API}/api/marketing/discounts`, { params, headers: authH });
      if (res.data.success) {
        setItems(res.data.data || []);
        setPagination(res.data.pagination);
      }
    } catch { toast({ title: 'Gagal memuat kampanye', variant: 'destructive' }); }
    finally { setLoading(false); }
  }, [page, filterStatus, filterPlatform, filterType, filterAccountId, search, authH, toast]);

  useEffect(() => { fetchSummary(); }, [fetchSummary]);
  useEffect(() => { fetchItems(); },   [fetchItems]);

  const openCreate = () => { setEditTarget(null); setForm(EMPTY_FORM); setGalatForm(''); setShowForm(true); };
  const openEdit   = (item) => {
    setEditTarget(item);
    setForm({
      account_id: item.account_id || '',
      account_name: item.account_name || '', platform: item.platform || 'shopee',
      name: item.name || '', discount_type: item.discount_type || 'flash_sale',
      discount_value: item.discount_value ?? '', discount_unit: item.discount_unit || 'persen',
      min_purchase: item.min_purchase ?? '', max_discount: item.max_discount ?? '',
      start_date: item.start_date || '', end_date: item.end_date || '',
      description: item.description || '', product_scope: item.product_scope || 'semua_produk',
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
    if (!form.account_id || !form.name || !form.start_date || !form.end_date) {
      setGalatForm('Pilih akun, isi nama kampanye, dan tanggal mulai & berakhir.'); return;
    }
    setGalatForm('');
    setFormLoading(true);
    try {
      const payload = {
        ...form,
        discount_value: parseFloat(form.discount_value) || 0,
        min_purchase:   parseFloat(form.min_purchase)   || 0,
        max_discount:   parseFloat(form.max_discount)   || 0,
      };
      if (editTarget) {
        await axios.put(`${API}/api/marketing/discounts/${editTarget.id}`, payload, { headers: authH });
        toast({ title: 'Kampanye disimpan.' });
      } else {
        await axios.post(`${API}/api/marketing/discounts`, payload, { headers: authH });
        toast({ title: 'Kampanye ditambahkan.' });
      }
      setShowForm(false);
      fetchSummary();
      fetchItems();
    } catch (e) { setGalatForm(e?.response?.data?.detail || 'Gagal menyimpan kampanye.'); }
    finally { setFormLoading(false); }
  };

  const handleDelete = async (id) => {
    if (!(await confirmDialog({ title: 'Hapus kampanye ini?', body: 'Kampanye dihapus dari daftar.', confirmLabel: 'Hapus', danger: true }))) return;
    setDetail(null);
    try {
      await axios.delete(`${API}/api/marketing/discounts/${id}`, { headers: authH });
      toast({ title: 'Kampanye dihapus.' });
      fetchSummary();
      fetchItems();
    } catch { toast({ title: 'Gagal menghapus kampanye', variant: 'destructive' }); }
  };

  const jenis = (item) => DISCOUNT_TYPE_LABELS[item.discount_type] || item.discount_type_label || item.discount_type;
  const paramSaring = () => {
    const params = {};
    if (filterStatus)   params.status = filterStatus;
    if (filterPlatform) params.platform = filterPlatform;
    if (filterAccountId) params.account_id = filterAccountId;
    if (filterType)     params.discount_type = filterType;
    if (search)         params.search = search;
    return params;
  };
  /** Unduh semua kampanye hasil saringan (dulu hanya 20 baris halaman ini). */
  const ambilSemua = async () => {
    const semua = [];
    for (let p = 1; p <= 200; p += 1) {
      const res = await axios.get(`${API}/api/marketing/discounts`, { params: { page: p, page_size: 100, ...paramSaring() }, headers: authH });
      semua.push(...(res.data.data || []));
      if (p >= (res.data.pagination?.total_pages || 1)) break;
    }
    return semua;
  };
  const adaSaring = !!(filterStatus || filterPlatform || filterType || filterAccountId || search);

  const kolom = [
    { kunci: 'nama', label: 'Nama kampanye', hp: 'judul', isi: (item) => (
      <div className="min-w-0 md:max-w-[16rem]"><p className="truncate font-medium" title={item.name}>{item.name}</p>
        <p className="text-xs text-muted-foreground">{labelCakupan(item.product_scope)}</p></div>) },
    { kunci: 'toko', label: 'Toko', isi: (item) => (
      <span className="md:whitespace-nowrap">{item.account_name || '—'}<span className="block text-xs text-muted-foreground">{labelPlatform(item.platform)}</span></span>) },
    { kunci: 'jenis', label: 'Jenis', isi: (item) => <span className="md:whitespace-nowrap">{jenis(item)}</span> },
    { kunci: 'nilai', label: 'Nilai', rata: 'kanan', isi: (item) => (
      <span className="tabular-nums md:whitespace-nowrap"><span className="font-medium">{nilaiDiskon(item)}</span>
        {item.min_purchase > 0 && <span className="block text-xs text-muted-foreground">min. {fmtRp(item.min_purchase)}</span>}</span>) },
    { kunci: 'periode', label: 'Periode', hp: 'keterangan', isi: (item) => (
      <span className="tabular-nums md:whitespace-nowrap">{tgl(item.start_date)} – {tgl(item.end_date)}
        {sisaHari(item) && <span className={`block text-xs ${item.days_remaining >= 0 && item.days_remaining <= 3 ? 'text-[hsl(var(--danger-text))]' : 'text-muted-foreground'}`}>{sisaHari(item)}</span>}</span>) },
    { kunci: 'status', label: 'Status', isi: (item) => <StatusKampanye status={item.status} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (item) => (
      <div className="flex justify-end gap-1">
        <Button size="icon-sm" variant="ghost" onClick={() => openEdit(item)} title="Ubah kampanye" aria-label="Ubah kampanye"><Pencil /></Button>
        <Button size="icon-sm" variant="ghost" className="text-[hsl(var(--danger-text))]" onClick={() => handleDelete(item.id)}
          title="Hapus kampanye" aria-label="Hapus kampanye"><Trash2 /></Button>
      </div>) },
  ];

  return (
    <PageLayout testId="discount-campaign-dashboard" title="Kampanye diskon"
      subtitle="Kampanye promo semua platform: flash sale, voucher, bundling, gratis ongkir."
      actions={<Button onClick={openCreate} data-testid="btn-add-discount"><Plus />Buat kampanye</Button>}
      filters={<>
        <div className="relative w-full sm:w-44">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="pl-8" placeholder="Cari nama kampanye" value={search}
            onChange={e => { setSearch(e.target.value); setPage(1); }} data-testid="discount-search" />
        </div>
        <MarketingAccountSelect token={token} value={filterAccountId} className="w-44"
          onChange={(v) => { setFilterAccountId(v); setPage(1); }} label=""
          includeAll allLabel="Semua toko" required={false} testId="discount-filter-account" />
        <SmartNativeSelect value={filterStatus} onChange={(e) => { setFilterStatus(e.target.value); setPage(1); }} className="w-full" wrapperClassName="w-36 max-w-full" searchable={false}>
          <option value="">Semua status</option>
          {Object.entries(STATUS_CONFIG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={filterPlatform} onChange={(e) => { setFilterPlatform(e.target.value); setPage(1); }} className="w-full" wrapperClassName="w-40 max-w-full" searchable={false}>
          <option value="">Semua platform</option>
          {Object.entries(PLATFORM_LABEL).filter(([k]) => k !== 'semua_platform').map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          <option value="semua_platform">Kampanye lintas platform</option>
        </SmartNativeSelect>
        <SmartNativeSelect value={filterType} onChange={(e) => { setFilterType(e.target.value); setPage(1); }} className="w-full" wrapperClassName="w-40 max-w-full" searchable={false}>
          <option value="">Semua jenis</option>
          {Object.entries(DISCOUNT_TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="kampanye-diskon" namaLembar="Kampanye" baris={items} ambilSemua={ambilSemua} testId="discount-export-csv"
          kolom={[
            { label: 'Nama kampanye', nilai: (it) => it.name },
            { label: 'Platform', nilai: (it) => labelPlatform(it.platform) },
            { label: 'Toko', nilai: (it) => it.account_name || '' },
            { label: 'Jenis', nilai: jenis },
            { label: 'Nilai', nilai: (it) => Number(it.discount_value) || 0 },
            { label: 'Satuan', nilai: (it) => UNIT_LABEL[it.discount_unit] || it.discount_unit || '' },
            { label: 'Min. belanja', nilai: (it) => Number(it.min_purchase) || 0 },
            { label: 'Maks. diskon', nilai: (it) => Number(it.max_discount) || 0 },
            { label: 'Cakupan produk', nilai: (it) => labelCakupan(it.product_scope) },
            { label: 'Mulai', nilai: (it) => tgl(it.start_date) },
            { label: 'Selesai', nilai: (it) => tgl(it.end_date) },
            { label: 'Sisa hari', nilai: (it) => (it.days_remaining ?? '') },
            { label: 'Status', nilai: (it) => STATUS_CONFIG[it.status]?.label || it.status || '' },
          ]} />
        <Button variant="outline" size="icon" onClick={() => { fetchSummary(); fetchItems(); }} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={<>
        {(summary?.total || 0) > 0 && (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="discount-kpi">
            <StatTile label="Total kampanye" value={fmt(summary?.total)} sub={`${fmt(summary?.expired)} sudah berakhir`}
              hint="Semua toko; tidak ikut penyaring." />
            <StatTile label="Aktif sekarang" value={fmt(summary?.active)} accent="success" hint="Kampanye yang sedang berjalan hari ini." />
            <StatTile label="Akan datang" value={fmt(summary?.upcoming)} accent="primary" hint="Kampanye yang belum mulai." />
            <StatTile label="Berakhir ≤ 3 hari" value={fmt(summary?.expiring_soon)} accent="warning" hint="Kampanye aktif yang berakhir dalam 3 hari." />
          </div>
        )}
        {summary?.expiring_soon > 0 && (
          <Notice tone="warning" icon={AlertTriangle} title={`${summary.expiring_soon} kampanye berakhir dalam 3 hari`}>
            Perpanjang atau siapkan kampanye pengganti.
          </Notice>
        )}
      </>}
      footer={pagination && pagination.total_pages > 1 && (
        <PaginationLite page={page} totalPages={pagination.total_pages} total={pagination.total} pageSize={20} onPageChange={setPage} />
      )}>
      {loading && items.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat kampanye…</p>
      ) : (
        <TabelData kolom={kolom} baris={items} onKlikBaris={setDetail} testId="discount-table"
          kosong={<EmptyState title={adaSaring ? 'Tidak ada kampanye yang cocok' : 'Belum ada kampanye'}
            description={adaSaring ? 'Ubah saringan atau kata pencarian.' : 'Buat kampanye diskon pertama untuk toko Anda.'}
            action={!adaSaring && <Button onClick={openCreate}><Plus />Buat kampanye</Button>} />} />
      )}

      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} judul={detail.name} testId="discount-detail"
          status={<StatusKampanye status={detail.status} />}
          keterangan={`${detail.account_name || '—'} · ${labelPlatform(detail.platform)}`}
          aksi={<>
            <Button size="sm" variant="outline" onClick={() => { const it = detail; setDetail(null); openEdit(it); }}><Pencil />Ubah</Button>
            <Button size="sm" variant="destructive" onClick={() => handleDelete(detail.id)}><Trash2 />Hapus</Button>
          </>}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Jenis">{jenis(detail)}</BarisDetail>
            <BarisDetail label="Nilai diskon">{nilaiDiskon(detail)}</BarisDetail>
            <BarisDetail label="Min. belanja">{fmtRp(detail.min_purchase)}</BarisDetail>
            <BarisDetail label="Maks. diskon">{fmtRp(detail.max_discount)}</BarisDetail>
            <BarisDetail label="Cakupan produk">{labelCakupan(detail.product_scope)}</BarisDetail>
            <BarisDetail label="Periode">{tgl(detail.start_date)} – {tgl(detail.end_date)}{sisaHari(detail) ? ` · ${sisaHari(detail)}` : ''}</BarisDetail>
            {detail.description && <BarisDetail label="Deskripsi">{detail.description}</BarisDetail>}
          </dl>
        </DetailPopup>
      )}

      <FormPopup open={showForm} onClose={() => setShowForm(false)} ukuran="panjang" onSimpan={handleSave} menyimpan={formLoading}
        judul={editTarget ? 'Ubah kampanye' : 'Buat kampanye baru'} galat={galatForm} testId="discount-form"
        labelSimpan={editTarget ? 'Simpan perubahan' : 'Buat kampanye'}>
        <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Nama kampanye" wajib htmlFor="dsc-name">
          <Input id="dsc-name" value={form.name} onChange={e => setForm(f => ({...f, name: e.target.value}))}
            placeholder="Contoh: Flash sale Harbolnas 12.12" />
        </Isian>
        <Isian label="Akun / toko marketplace" wajib htmlFor="dsc-account"
          petunjuk={form.account_id ? `Platform: ${labelPlatform(form.platform)} (otomatis dari akun terpilih)` : undefined}>
          <SmartNativeSelect id="dsc-account" value={form.account_id || ''} onChange={(e) => handleAccountChange(e.target.value)}
            data-testid="campaign-account-select">
            <option value="">{accounts.length === 0 ? 'Belum ada akun aktif' : 'Pilih akun'}</option>
            {accounts.map(acc => <option key={acc.id} value={acc.id}>{`${acc.account_name} · ${labelPlatform(acc.platform)}`}</option>)}
          </SmartNativeSelect>
        </Isian>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Jenis diskon" htmlFor="dsc-type">
            <SmartNativeSelect id="dsc-type" value={form.discount_type} searchable={false} onChange={(e) => setForm(f => ({...f, discount_type: e.target.value}))}>
              {Object.entries(DISCOUNT_TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Satuan nilai" htmlFor="dsc-unit">
            <SmartNativeSelect id="dsc-unit" value={form.discount_unit} searchable={false} onChange={(e) => setForm(f => ({...f, discount_unit: e.target.value}))}>
              {Object.entries(UNIT_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Nilai diskon" htmlFor="dsc-value">
            {/* Satuan "Nominal (Rp)" = uang → MoneyInput; persen/unit tetap angka biasa. */}
            {form.discount_unit === 'nominal' ? (
              <MoneyInput value={form.discount_value} onChange={e => setForm(f => ({...f, discount_value: e.target.value}))} placeholder="0" />
            ) : (
              <Input id="dsc-value" type="number" min="0" value={form.discount_value} placeholder="0"
                onChange={e => setForm(f => ({...f, discount_value: e.target.value}))} />
            )}
          </Isian>
          <Isian label="Min. pembelian (Rp)">
            <MoneyInput value={form.min_purchase} onChange={e => setForm(f => ({...f, min_purchase: e.target.value}))} placeholder="0" />
          </Isian>
          <Isian label="Tanggal mulai" wajib>
            <DatePicker value={form.start_date || ''} onChange={(v) => setForm(f => ({...f, start_date: v}))} testId="dsc-start" />
          </Isian>
          <Isian label="Tanggal berakhir" wajib>
            <DatePicker value={form.end_date || ''} min={form.start_date || undefined}
              onChange={(v) => setForm(f => ({...f, end_date: v}))} testId="dsc-end" />
          </Isian>
        </div>
        <Isian label="Deskripsi" htmlFor="dsc-desc">
          <Textarea id="dsc-desc" value={form.description} rows={2} placeholder="Rincian kampanye"
            onChange={e => setForm(f => ({...f, description: e.target.value}))} />
        </Isian>
      </FormPopup>
    </PageLayout>
  );
}

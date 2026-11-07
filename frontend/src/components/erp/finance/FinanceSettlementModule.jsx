/**
 * FinanceSettlementModule — **Saldo & Pencairan Marketplace** di Portal Keuangan.
 *
 * DUA TAHAP (keputusan pemilik): omzet input Marketing TIDAK pernah masuk Finance.
 * Yang masuk Finance hanya:
 *  1. DANA DILEPAS platform ke saldo toko (laporan Penghasilan Shopee / Settlement
 *     TikTok) → Dr Piutang Toko 1-1303-xxx / Dr potongan / Cr Pendapatan toko (bruto).
 *     Saldo 1-1303-xxx = saldo yang masih bisa dicairkan.
 *  2. PENARIKAN saldo ke rekening bank → Dr Rekening Pencairan / Cr Piutang Toko.
 *     Dokumen inilah yang dicocokkan ke mutasi bank.
 *
 * Form ada di FINANCE (sesi #37): Marketing hanya melihat (`MarketingSettlementsView`).
 * `net_payout` tahap 1 DIISI TANGAN dari laporan platform — server menghitung
 * "seharusnya berapa" lalu menampilkan SELISIH-nya; selisih ≠ 0 ⇒ jurnal ditolak.
 *
 * 2026-11-04 (owner, audit Keuangan tahap 3): satu menu "Marketplace" dengan 3 tab — prop `view`:
 *   'balances' (saldo per toko + potongan per toko), 'settlements' (dana dilepas), 'withdrawals'
 *   (penarikan). Dulu keempatnya menumpuk di satu halaman ±7 layar. Tautan rekening per toko pindah
 *   ke Pengaturan Keuangan › Rekening toko. Daftar dana dilepas berpaginasi server (dulu berhenti di
 *   50 baris dan kartu menulis "50 laporan").
 * 2026-11-05 (PANDUAN_UI G1, keluhan owner): memakai cetakan PageLayout — "Semua toko" + periode mulai dari
 *   KIRI, muat ulang di kanan (dulu seluruh baris menempel di kanan dengan sisi kiri kosong). Tombol impor &
 *   catat di slot `actions` (di hub pindah ke baris tab). Hasil "Cocokkan" dibuka di DetailPanel di atas
 *   tabel. Tab Penarikan memakai cetakan yang sama lewat PlatformWithdrawalsPanel (periode tidak tampil di
 *   sana karena daftar penarikan tidak disaring per periode).
 * 2026-11-08 (Standar UI/UX v2): form dana dilepas = FormPopup panjang (hasil baca impor ikut di dalamnya) dengan
 *   DatePicker; hasil Cocokkan = popup tanpa kotak abu/kapital; aksi baris paling banyak 2 terlihat (Jurnal/Posting +
 *   "Lainnya"); daftar bisa diunduh Excel/CSV semua halaman; platform ditulis Shopee/TikTok; kartu angka berketerangan.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import {
  Banknote, RefreshCw, AlertTriangle, Loader2,
  Plus, Scale, BookCheck, Send, Trash2, Pencil, Upload, MoreHorizontal,
} from 'lucide-react';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Badge } from '@/components/ui/badge';
import { toast } from 'sonner';
import { formatRupiah, formatDateID, formatPercent } from '@/lib/format';
import { finStatus } from '@/lib/financeLabels';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import PeriodPicker, { periodFromPreset } from './PeriodPicker';
import { MoneyInput } from '@/components/ui/money-input';

import { SettlementImportPanel, computeValues } from './SettlementImportPanel';
import { SettlementByStoreCards } from './SettlementByStoreCards';
import { PlatformBalanceCards, usePlatformBalances, namaPlatform } from './PlatformBalanceCards';
import { PlatformWithdrawalsPanel } from './PlatformWithdrawalsPanel';
import { useBankOptions } from './PayoutBankLinks';
import PaginationBar from '@/components/ui/PaginationBar';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';
import PageLayout, { DetailPanel } from '../layout/PageLayout';

const API = process.env.REACT_APP_BACKEND_URL;
const BASE = `${API}/api/marketing/settlements`;
const rp = formatRupiah;
const pct = (v) => formatPercent(v, 2);
const MONTHS_ID = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
const fmtMonthID = (ym) => { const [y, m] = String(ym).split('-'); return `${MONTHS_ID[Number(m) - 1] || m} ${y}`; };

function token() { return localStorage.getItem('erp_token'); }

async function call(path, opts = {}) {
  const r = await fetch(`${BASE}${path}`, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token()}`,
      ...(opts.headers || {}),
    },
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || d.message || `Gagal (HTTP ${r.status})`);
  return d;
}

// Field uang + arahnya terhadap net payout — DISAMAKAN dengan `MONEY_FIELDS`
// di backend. Tandanya ikut ditampilkan supaya staf tahu mana yang menambah dan
// mana yang mengurangi TANPA harus menebak dari namanya.
const MONEY_FIELDS = [
  ['gross_sales', 'Omzet bruto', +1],
  ['refunds', 'Refund / retur', -1],
  ['seller_discount', 'Diskon penjual', -1],
  ['shipping_subsidy', 'Subsidi ongkir platform', +1],
  ['platform_commission', 'Komisi platform', -1],
  ['platform_service_fee', 'Fee layanan platform', -1],
  ['affiliate_commission', 'Komisi afiliasi', -1],
  ['ads_deduction', 'Potongan iklan', -1],
  ['other_deductions', 'Potongan lain', -1],
  ['adjustments', 'Penyesuaian (boleh minus)', +1],
];

const EMPTY = {
  account_id: '', platform: '', settlement_id: '', settlement_date: '',
  period_from: '', period_to: '',
  gross_sales: '', refunds: '', seller_discount: '', shipping_subsidy: '',
  platform_commission: '', platform_service_fee: '', affiliate_commission: '',
  ads_deduction: '', other_deductions: '', adjustments: '',
  net_payout: '', notes: '', other_deductions_note: '',
};

const PAGE = 25;

export default function FinanceSettlementModule({ view = 'settlements' }) {
  const [accounts, setAccounts] = useState([]);
  const [skip, setSkip] = useState(0);
  const [total, setTotal] = useState(0);
  const formRef = useRef(null);
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState(null);
  const [accountId, setAccountId] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');

  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [editId, setEditId] = useState('');

  const [recon, setRecon] = useState(null);
  const [reconFor, setReconFor] = useState('');

  const [importRes, setImportRes] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const fileRef = useRef(null);

  // PANDUAN_UI G6 (2026-11-04): satu pemilih periode, bawaan "Bulan ini" — dulu kotak bulan ATAU rentang
  // tanggal dengan bawaan kosong (= semua periode) dan kotak bulan kosong tampil "--------- ----".
  const [period, setPeriod] = useState(() => periodFromPreset('month'));
  const range = useMemo(() => ({ from: period.from, to: period.to }), [period]);
  const monthOfPeriod = ['month', 'last_month'].includes(period.preset) ? period.from.slice(0, 7) : '';
  // periode selalu tertulis di kartu (audit: 24,19% vs 24,16% tampak beda karena periodenya tak tertulis)
  const periodLabel = monthOfPeriod ? fmtMonthID(monthOfPeriod) : `${formatDateID(range.from)} – ${formatDateID(range.to)}`;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams({ page_size: String(PAGE), page: String(Math.floor(skip / PAGE) + 1) });
      if (accountId) qs.set('account_id', accountId);
      if (range.from) qs.set('date_from', range.from);
      if (range.to) qs.set('date_to', range.to);
      const d = await call(`?${qs}`);
      setRows(d.data || []);
      setTotal(d.pagination?.total ?? (d.data || []).length);
      setSummary(d.summary || null);
      setRefreshKey((k) => k + 1);
    } catch (e) {
      toast.error(e.message);
    } finally {
      setLoading(false);
    }
  }, [accountId, range.from, range.to, skip]);

  useEffect(() => { setSkip(0); }, [accountId, range.from, range.to]);
  useEffect(() => { load(); }, [load]);
  // Formulir dibuka → langsung terlihat (dulu muncul ±3.500 px di bawah tombolnya tanpa digulir).
  useEffect(() => {
    if (formOpen) formRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [formOpen, editId]);

  const loadAccounts = useCallback(() => {
    fetch(`${API}/api/marketing/accounts?limit=200`,
      { headers: { Authorization: `Bearer ${token()}` } })
      .then((r) => r.json())
      .then((d) => setAccounts(Array.isArray(d) ? d : (d?.accounts || d?.data || [])))
      .catch(() => {});
  }, []);
  useEffect(() => { loadAccounts(); }, [loadAccounts]);
  const banks = useBankOptions();

  const accName = (id) => (accounts.find((a) => a.id === id)?.account_name) || id || '—';
  const accOf = (id) => accounts.find((a) => a.id === id) || {};
  const { data: balances } = usePlatformBalances(refreshKey);

  // Angka "seharusnya" dihitung ULANG DI LAYAR saat staf mengetik — bukan supaya
  // menggantikan server, tetapi supaya selisihnya terlihat SEBELUM disimpan.
  // Menunggu server untuk tahu ada selisih berarti staf harus menyimpan dulu
  // angka yang sudah dia tahu salah.
  const expected = useMemo(() => MONEY_FIELDS.reduce(
    (t, [f, , sign]) => t + sign * (parseFloat(form[f]) || 0), 0), [form]);
  const diff = useMemo(
    () => Math.round(((parseFloat(form.net_payout) || 0) - expected) * 100) / 100,
    [form.net_payout, expected]);

  const openCreate = () => { setForm(EMPTY); setEditId(''); setFormOpen(true); };

  const previewCall = async (file, acc) => {
    const fd = new FormData();
    fd.append('file', file);
    if (acc) fd.append('account_id', acc);
    const r = await fetch(`${BASE}/import/preview`, {
      method: 'POST', headers: { Authorization: `Bearer ${token()}` }, body: fd,
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || `Gagal membaca berkas (HTTP ${r.status})`);
    return d;
  };

  const applyImport = (d, account_id) => {
    const f = { ...EMPTY, account_id };
    MONEY_FIELDS.forEach(([k]) => { f[k] = d.values?.[k] ? String(d.values[k]) : ''; });
    f.net_payout = d.values?.net_payout ? String(d.values.net_payout) : '';
    f.settlement_id = d.settlement_id || '';
    f.settlement_date = d.settlement_date || '';
    f.period_from = d.period_from || '';
    f.period_to = d.period_to || '';
    f.notes = `Diimpor dari ${d.filename} (${d.row_count} baris)`;
    setForm(f); setEditId(''); setFormOpen(true); setImportRes(d);
  };

  const importFile = async (file) => {
    if (!file) return;
    setBusy('import');
    try {
      const hint = accountId || form.account_id || '';
      let d = await previewCall(file, hint);
      const guess = d.platform_guess || '';
      const fits = (id) => id && (!guess || accOf(id).platform === guess);
      // Toko dipilih ULANG tiap impor dari platform yang terdeteksi — jangan mewarisi
      // pilihan impor sebelumnya, karena laporan TikTok bisa diam-diam tersimpan ke toko Shopee.
      let account_id = '';
      if (fits(accountId)) account_id = accountId;
      else if (fits(form.account_id)) account_id = form.account_id;
      else if (guess) {
        const cand = accounts.filter((a) => a.platform === guess);
        if (cand.length === 1) account_id = cand[0].id;
      }
      // Pemetaan tersimpan milik TOKO; bila toko akhirnya berbeda dari petunjuk awal, baca ulang.
      if (account_id && account_id !== hint) d = await previewCall(file, account_id);
      applyImport(d, account_id);
      if (!account_id) toast.warning(`Toko belum dipilih — laporan terdeteksi ${guess || 'tanpa platform'}; pilih toko yang benar sebelum menyimpan.`);
      if ((d.warnings || []).length) toast.warning(d.warnings[0]);
      else toast.success(d.mapping_source === 'saved'
        ? 'Format laporan dikenali — pemetaan tersimpan dipakai. Periksa sekilas lalu simpan.'
        : `${Object.keys(d.mapping || {}).length} field terisi dari tebakan otomatis — periksa pemetaan kolom lalu simpan.`);
    } catch (e) {
      toast.error(e.message);
    } finally {
      setBusy('');
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  // Staf mengubah tujuan kolom → angka form dihitung ulang dengan rumus yang sama seperti server.
  const changeMapping = (mapping) => {
    if (!importRes) return;
    const values = computeValues(mapping, importRes.column_totals || {});
    setImportRes({ ...importRes, mapping, values, mapping_source: 'edited' });
    setForm((prev) => {
      const f = { ...prev };
      MONEY_FIELDS.forEach(([k]) => { f[k] = values[k] ? String(values[k]) : ''; });
      f.net_payout = values.net_payout ? String(values.net_payout) : '';
      return f;
    });
  };

  const rememberMapping = async (account_id) => {
    if (!importRes?.mapping) return;
    try {
      await call('/import/mapping', {
        method: 'POST',
        body: JSON.stringify({
          account_id, headers: importRes.headers || importRes.numeric_columns || [], mapping: importRes.mapping,
          meta_columns: importRes.meta_columns || {}, filename: importRes.filename || '',
        }),
      });
      toast.message('Pemetaan kolom diingat untuk toko & format laporan ini.');
    } catch (e) {
      toast.warning(`Laporan tersimpan, tetapi pemetaan kolom gagal diingat: ${e.message}`);
    }
  };
  const openEdit = (r) => {
    const f = { ...EMPTY };
    Object.keys(EMPTY).forEach((k) => { f[k] = r[k] ?? ''; });
    setForm(f); setEditId(r.id); setFormOpen(true);
  };

  const save = async (postAfter = false) => {
    if (!form.account_id) { toast.error('Pilih toko dulu.'); return; }
    if (!form.settlement_id.trim()) { toast.error('Nomor pencairan wajib diisi.'); return; }
    if (!form.settlement_date) { toast.error('Tanggal uang masuk wajib diisi.'); return; }
    if (importRes?.platform_guess && accOf(form.account_id).platform
        && accOf(form.account_id).platform !== importRes.platform_guess) {
      toast.error(`Laporan terdeteksi ${importRes.platform_guess}, tetapi toko yang dipilih ada di ${accOf(form.account_id).platform}. Pilih toko yang sesuai.`);
      return;
    }
    const body = { ...form, platform: accOf(form.account_id).platform || form.platform || '' };
    MONEY_FIELDS.forEach(([f]) => { body[f] = parseFloat(form[f]) || 0; });
    body.net_payout = parseFloat(form.net_payout) || 0;
    setBusy('save');
    try {
      const d = editId
        ? await call(`/${editId}`, { method: 'PUT', body: JSON.stringify(body) })
        : await call('', { method: 'POST', body: JSON.stringify(body) });
      const saved = d.data || {};
      if (postAfter && saved.math_verified && saved.id && !saved.je_id) {
        // "Simpan & posting": dokumen yang seimbang langsung dijurnal + diposting (dulu 3 kali simpan).
        await call(`/${saved.id}/journal`, { method: 'POST' });
        const p = await call(`/${saved.id}/post`, { method: 'POST' });
        toast.success(`Dana dilepas tersimpan & diposting${p.je_number ? ` · ${p.je_number}` : ''} — saldo toko di buku besar bertambah.`);
      } else {
        toast.success(saved.math_verified
          ? 'Dana dilepas tersimpan (draf) — saldo toko di buku besar bertambah setelah jurnalnya diposting.'
          : `Tersimpan, tetapi masih ada selisih ${rp(saved.net_payout_diff || 0)} — beri nama dulu sebelum dijurnal.`);
      }
      setFormOpen(false);
      if (!editId && importRes) await rememberMapping(form.account_id);
      setImportRes(null);
      await load();
    } catch (e) {
      toast.error(e.message);
    } finally { setBusy(''); }
  };

  const act = async (r, kind) => {
    setBusy(`${kind}:${r.id}`);
    try {
      if (kind === 'journal') {
        const d = await call(`/${r.id}/journal`, { method: 'POST' });
        toast.success(d.message || `Jurnal ${d.je_number} dibuat.`);
      } else if (kind === 'post') {
        const d = await call(`/${r.id}/post`, { method: 'POST' });
        toast.success(d.message || `Jurnal ${d.je_number} diposting.`);
      } else if (kind === 'delete') {
        await call(`/${r.id}`, { method: 'DELETE' });
        toast.success('Laporan dana dilepas dihapus.');
      }
      await load();
    } catch (e) {
      toast.error(e.message);
    } finally { setBusy(''); }
  };

  const reconcile = async (r) => {
    setBusy(`recon:${r.id}`);
    try {
      // 2026-11-02 — pakai id dokumen (nomor platform bisa sama di toko lain, K-1).
      const d = await call(`/reconcile?settlement_id=${encodeURIComponent(r.id)}`);
      setRecon(d); setReconFor(r.settlement_id);
    } catch (e) {
      toast.error(e.message);
    } finally { setBusy(''); }
  };

  // Unduh: SEMUA laporan dana dilepas sesuai saringan (bukan hanya 25 di halaman ini).
  const ambilSemua = async () => {
    const out = [];
    for (let page = 1; page <= 100; page += 1) {
      const qs = new URLSearchParams({ page_size: '200', page: String(page) });
      if (accountId) qs.set('account_id', accountId);
      if (range.from) qs.set('date_from', range.from);
      if (range.to) qs.set('date_to', range.to);
      const d = await call(`?${qs}`);
      out.push(...(d.data || []));
      if (!(d.data || []).length || out.length >= (d.pagination?.total ?? out.length)) break;
    }
    return out;
  };
  const KOLOM_UNDUH = [
    { label: 'Tanggal dana dilepas', nilai: (r) => formatDateID(r.settlement_date) },
    { label: 'No. laporan', nilai: (r) => r.settlement_id },
    { label: 'Toko', nilai: (r) => accName(r.account_id) },
    { label: 'Platform', nilai: (r) => namaPlatform(r.platform) },
    { label: 'Periode pesanan dari', nilai: (r) => (r.period_from ? formatDateID(r.period_from) : '') },
    { label: 'Periode pesanan sampai', nilai: (r) => (r.period_to ? formatDateID(r.period_to) : '') },
    { label: 'Omzet bruto', nilai: (r) => Number(r.gross_sales) || 0 },
    { label: 'Potongan', nilai: (r) => Number(r.total_deductions) || 0 },
    { label: 'Potongan %', nilai: (r) => Number(r.deduction_pct) || 0 },
    { label: 'Masuk saldo', nilai: (r) => Number(r.net_payout) || 0 },
    { label: 'Status', nilai: (r) => (r.math_verified ? 'Seimbang' : `Selisih ${Number(r.net_payout_diff) || 0}`) },
    { label: 'Jurnal', nilai: (r) => (r.je_number ? `${r.je_number} (${finStatus(r.je_status).label.toLowerCase()})` : 'belum') },
  ];

  // ── Slot cetakan (PANDUAN_UI G1/G6): penyaring di kiri, muat ulang di kanan ──
  const storeFilter = (
    <SmartNativeSelect data-testid="fin-settlement-account-filter" value={accountId}
      onChange={(e) => setAccountId(e.target.value)} className="h-9 w-56" aria-label="Toko">
      <option value="">Semua toko</option>
      {accounts.map((a) => (
        <option key={a.id} value={a.id}>{a.account_name} · {namaPlatform(a.platform)}</option>
      ))}
    </SmartNativeSelect>
  );

  if (view === 'withdrawals') {
    return (
      <PlatformWithdrawalsPanel testId="finance-settlement-module" filters={storeFilter}
        accounts={accounts} accountId={accountId} banks={banks}
        balances={balances?.data} onChanged={() => setRefreshKey((k) => k + 1)} />
    );
  }

  // Kartu angka disembunyikan bila semuanya 0 (PANDUAN_UI G5/G10) — tabel/kartu toko menjelaskan kosongnya.
  const hasKpi = !!(summary && (summary.net_payout || summary.gross_sales || summary.total_deductions));
  const summaryNode = (<>
    {hasKpi ? (
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <StatTile testId="fin-settlement-kpi-net" label={`Masuk saldo platform · ${periodLabel}`}
          value={rp(summary.net_payout || 0)} sub={`${total} laporan dana dilepas${accountId ? ' · toko terpilih' : ' · semua toko'}`} />
        <StatTile testId="fin-settlement-kpi-gross" label={`Omzet bruto · ${periodLabel}`}
          value={rp(summary.gross_sales || 0)} sub="Menurut laporan platform" />
        <StatTile testId="fin-settlement-kpi-ded" label={`Potongan platform · ${periodLabel}`}
          value={rp(summary.total_deductions || 0)} sub={`${pct(summary.deduction_pct)} dari omzet bruto`} />
      </div>
    ) : null}
    {/* pemeriksaan teknis hanya muncul bila ada masalah (dulu kartu "Belum seimbang 0 dokumen" selalu tampil) */}
    {(summary?.unverified_count || 0) > 0 ? (
      <Notice tone="danger" icon={AlertTriangle} testId="fin-settlement-kpi-unverified">
        {summary.unverified_count} laporan dana dilepas masih ada selisih — beri nama selisihnya sebelum dijurnal.
      </Notice>
    ) : null}
  </>);

  const inputCls = 'h-9';
  const humanize = (s) => String(s || '').replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());

  // ── HASIL COCOK: detail satu laporan, di halaman di atas tabel (PANDUAN_UI G13) ──
  const reconPanel = view === 'settlements' && recon ? (
    <DetailPanel testId="fin-settlement-recon" onClose={() => setRecon(null)}
      title={<span className="flex items-center gap-2"><Scale className="w-4 h-4" /> Pencocokan {reconFor}</span>}
      description={`Periode pesanan ${formatDateID(recon.period?.from)} – ${formatDateID(recon.period?.to)}`}>
      <div className="grid md:grid-cols-3 gap-3 text-sm">
        <div className="rounded-[var(--radius-md)] border border-[var(--glass-border)] p-3 tabular-nums">
          <div className="text-xs font-medium text-muted-foreground">Dana dilepas</div>
          <div className="mt-1">bruto <b>{rp(recon.settlement?.gross_sales || 0)}</b></div>
          <div>masuk saldo <b>{rp(recon.settlement?.net_payout || 0)}</b></div>
          <div>potongan <b>{rp(recon.settlement?.total_deductions || 0)}</b>{' '}
            ({pct(recon.settlement?.deduction_pct || 0)})</div>
        </div>
        <div className="rounded-[var(--radius-md)] border border-[var(--glass-border)] p-3 tabular-nums">
          <div className="text-xs font-medium text-muted-foreground">
            Omzet pesanan periode ({recon.marketing?.order_count || 0} pesanan)
          </div>
          <div className="mt-1">bruto <b>{rp(recon.marketing?.revenue_gross || 0)}</b></div>
          <div>setelah diskon <b>{rp(recon.marketing?.revenue_product || 0)}</b></div>
          <div>dibayar pembeli <b>{rp(recon.marketing?.order_amount || 0)}</b></div>
        </div>
        <div className="rounded-[var(--radius-md)] border border-[var(--glass-border)] p-3 tabular-nums" data-testid="fin-settlement-recon-primary">
          {/* 2026-11-02 (K5) — pembanding utama keputusan owner */}
          <div className="text-xs font-medium text-muted-foreground">Selisih (setelah diskon penjual)</div>
          <div className="mt-1 text-lg font-semibold">
            {rp(recon.primary?.gap ?? recon.gap?.gross_vs_revenue_gross ?? 0)}
          </div>
          <div className="text-xs text-muted-foreground">
            (bruto {rp(recon.primary?.settlement_gross || 0)} − diskon penjual{' '}
            {rp(recon.primary?.settlement_seller_discount || 0)}) vs omzet setelah diskon{' '}
            {rp(recon.primary?.omzet_after_discount || 0)}
          </div>
          <div className="text-xs text-muted-foreground">
            {recon.gap?.cancelled_orders_excluded || 0} pesanan batal dikecualikan · selisih bruto vs bruto{' '}
            {rp(recon.gap?.gross_vs_revenue_gross || 0)}
          </div>
        </div>
      </div>
      <ul className="space-y-1.5" data-testid="fin-settlement-recon-named">
        {(recon.gap?.named || []).map((g) => (
          <li key={g.name} className="text-sm rounded-[var(--radius-md)] border border-[var(--glass-border)] px-3 py-2">
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="text-xs">{humanize(g.name)}</Badge>
              {g.amount ? <b className="tabular-nums">{rp(g.amount)}</b> : null}
            </div>
            <div className="mt-0.5 text-foreground">{g.label}</div>
            <div className="text-xs text-muted-foreground">{g.action}</div>
          </li>
        ))}
      </ul>
    </DetailPanel>
  ) : null;

  return (
    <PageLayout
      testId="finance-settlement-module"
      title="Marketplace"
      subtitle={view === 'balances'
        ? 'Saldo tiap toko yang masih di platform dan potongan platform per toko.'
        : 'Laporan dana dilepas platform ke saldo toko, dari laporan penghasilan Shopee / TikTok.'}
      actions={view === 'settlements' ? (<>
        <Button variant="outline" data-testid="fin-settlement-import" disabled={busy === 'import'}
          onClick={() => fileRef.current?.click()}
          title="Unggah laporan Penghasilan (Shopee) / Settlement (TikTok) untuk mengisi formulir">
          {busy === 'import' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
          Impor laporan
        </Button>
        <Button data-testid="fin-settlement-new" onClick={openCreate}>
          <Plus className="w-4 h-4" /> Catat dana dilepas
        </Button>
      </>) : null}
      filters={<>
        {storeFilter}
        <PeriodPicker value={period} onChange={setPeriod} testId="fin-settlement-period-filter" />
      </>}
      tools={<>
        {view === 'settlements' && (
          <TombolUnduh namaBerkas={`dana-dilepas-${range.from}-${range.to}`} namaLembar="Dana dilepas" baris={rows}
            ambilSemua={ambilSemua} kolom={KOLOM_UNDUH} testId="fin-settlement-unduh" />
        )}
        <Button variant="outline" size="icon" data-testid="fin-settlement-refresh" onClick={load} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className="w-4 h-4" />
        </Button>
      </>}
      summary={summaryNode}
      detail={reconPanel}
    >
      {view === 'balances' ? (<>
        <PlatformBalanceCards refreshKey={refreshKey} />
        <SettlementByStoreCards refreshKey={refreshKey} month={monthOfPeriod} />
      </>) : null}

      {view === 'settlements' ? (<>
      <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls,.tsv" className="hidden"
        data-testid="fin-settlement-import-file"
        onChange={(e) => importFile(e.target.files?.[0])} />

      {/* ── FORM (popup standar, panjang) — hasil baca impor ikut di dalamnya ── */}
      {formOpen ? (
        <FormPopup open onClose={() => { setFormOpen(false); setImportRes(null); }} ukuran="panjang" testId="fin-settlement-form"
          judul={editId ? 'Koreksi laporan dana dilepas' : 'Catat dana dilepas ke saldo toko'}
          keterangan="Isi dari laporan Penghasilan (Shopee) / Settlement (TikTok). Selisih harus 0 sebelum dijurnal."
          onSimpan={() => save(true)} menyimpan={busy === 'save'} bisaSimpan={Math.abs(diff) < 0.01}
          labelSimpan="Simpan & posting"
          aksiKiri={<Button type="button" variant="outline" data-testid="fin-settlement-save" disabled={busy === 'save'} onClick={() => save(false)}>Simpan draf</Button>}>
          <div ref={formRef} />
          <SettlementImportPanel result={importRes} onClose={() => setImportRes(null)}
            onMappingChange={changeMapping} />
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <Isian label="Toko" wajib>
              <SmartNativeSelect data-testid="fin-settlement-input-account" value={form.account_id}
                onChange={(e) => setForm({ ...form, account_id: e.target.value })}
                className="h-9 w-full">
                <option value="">— pilih toko —</option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>{a.account_name} · {namaPlatform(a.platform)}</option>
                ))}
              </SmartNativeSelect>
            </Isian>
            <Isian label="No. laporan (dari platform)" wajib>
              <GlassInput data-testid="fin-settlement-input-settlement-id" value={form.settlement_id}
                onChange={(e) => setForm({ ...form, settlement_id: e.target.value })}
                placeholder="mis. 2026081512345" className={inputCls} />
            </Isian>
            <Isian label="Tanggal dana dilepas" wajib>
              <DatePicker testId="fin-settlement-input-date" value={form.settlement_date}
                onChange={(v) => setForm({ ...form, settlement_date: v })} />
            </Isian>
            <div className="hidden lg:block" />
            <Isian label="Periode pesanan dari" petunjuk="Wajib untuk Cocokkan.">
              <DatePicker testId="fin-settlement-input-period-from" value={form.period_from}
                onChange={(v) => setForm({ ...form, period_from: v })} />
            </Isian>
            <Isian label="Periode pesanan sampai" petunjuk="Wajib untuk Cocokkan.">
              <DatePicker testId="fin-settlement-input-period-to" value={form.period_to} min={form.period_from || undefined}
                onChange={(v) => setForm({ ...form, period_to: v })} />
            </Isian>
          </div>
          <p className="text-sm font-medium text-foreground">Rincian laporan</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {MONEY_FIELDS.map(([f, label, sign]) => (
              <Isian key={f} label={<>{label} <span className={sign > 0 ? 'text-[hsl(var(--success-text))]' : 'text-[hsl(var(--danger-text))]'}>({sign > 0 ? '+' : '−'})</span></>}>
                <MoneyInput glass allowNegative={f === 'adjustments'} data-testid={`fin-settlement-input-${f}`}
                  value={form[f]} onChange={(e) => setForm({ ...form, [f]: e.target.value })}
                  className="h-9 text-right tabular-nums" />
              </Isian>
            ))}
          </div>
          <div className="grid sm:grid-cols-3 gap-4">
            <Isian label="Dana bersih masuk saldo (menurut laporan platform)" wajib>
              <MoneyInput glass data-testid="fin-settlement-input-net-payout"
                value={form.net_payout}
                onChange={(e) => setForm({ ...form, net_payout: e.target.value })}
                className="h-9 text-right tabular-nums font-semibold" />
            </Isian>
            <Isian label="Keterangan potongan lain" petunjuk="Wajib bila ada potongan lain.">
              <GlassInput data-testid="fin-settlement-input-other-note" value={form.other_deductions_note}
                onChange={(e) => setForm({ ...form, other_deductions_note: e.target.value })} className={inputCls} />
            </Isian>
            <Isian label="Catatan">
              <GlassInput data-testid="fin-settlement-input-notes" value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })} className={inputCls} />
            </Isian>
          </div>
          <Notice tone={Math.abs(diff) < 0.01 ? 'success' : 'danger'} className="tabular-nums" testId="fin-settlement-diff">
            Hasil hitung dari rincian: <b>{rp(expected)}</b> · yang diisi:{' '}
            <b>{rp(parseFloat(form.net_payout) || 0)}</b> · selisih: <b>{rp(diff)}</b>
            {Math.abs(diff) < 0.01
              ? ' — seimbang, boleh dijurnal.'
              : ' — beri nama dulu di "Potongan lain" atau "Penyesuaian"; jurnal akan ditolak selama masih ada selisih. "Simpan draf" tetap bisa.'}
          </Notice>
        </FormPopup>
      ) : null}

      {/* ── DAFTAR ── */}
      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <div className="py-8 text-center text-sm text-muted-foreground flex items-center justify-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin" /> memuat dana dilepas…
          </div>
        ) : rows.length === 0 ? (
          <EmptyState icon={Banknote} testId="fin-settlement-empty"
            title={`Belum ada laporan dana dilepas${accountId ? ' untuk toko ini' : ''}${range.from || range.to ? ' pada periode ini' : ''}`}
            description="Buka laporan Penghasilan (Shopee) / Settlement (TikTok), lalu tekan “Catat dana dilepas” atau “Impor laporan”." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="fin-settlement-table">
              <thead>
                <tr className="border-b border-[var(--glass-border)]">
                  <th className="text-left">Tanggal</th>
                  <th className="text-left">No. laporan</th>
                  <th className="text-left">Toko / platform</th>
                  <th className="text-right">Bruto</th>
                  <th className="text-right">Potongan</th>
                  <th className="text-right">Masuk saldo</th>
                  <th className="text-left">Status</th>
                  <th className="text-left">Jurnal</th>
                  <th className="text-right">Aksi</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className={`border-b border-[var(--glass-border)] ${recon && reconFor === r.settlement_id ? 'bg-[hsl(var(--primary)/0.06)]' : ''}`}
                    data-testid={`fin-settlement-row-${r.settlement_id}`}>
                    <td className="whitespace-nowrap">{formatDateID(r.settlement_date)}</td>
                    <td className="whitespace-nowrap">{r.settlement_id}</td>
                    <td>
                      {accName(r.account_id)}
                      <span className="block text-xs text-muted-foreground">{namaPlatform(r.platform)}</span>
                    </td>
                    <td className="text-right tabular-nums whitespace-nowrap">{rp(r.gross_sales || 0)}</td>
                    <td className="text-right tabular-nums whitespace-nowrap">
                      {rp(r.total_deductions || 0)}
                      {r.deduction_pct ? (
                        <span className="text-xs text-muted-foreground"> ({pct(r.deduction_pct)})</span>
                      ) : null}
                    </td>
                    <td className="text-right tabular-nums whitespace-nowrap font-medium">
                      {rp(r.net_payout || 0)}
                    </td>
                    <td className="whitespace-nowrap">
                      {r.math_verified
                        ? <StatusBadge tone="success" label="Seimbang" />
                        : <StatusBadge tone="danger" label={`Selisih ${rp(r.net_payout_diff || 0)}`} />}
                    </td>
                    <td className="whitespace-nowrap">
                      {r.je_number
                        ? <>{r.je_number} <span className="text-muted-foreground">({finStatus(r.je_status).label.toLowerCase()})</span></>
                        : <span className="text-muted-foreground">belum</span>}
                    </td>
                    <td>
                      <div className="flex items-center justify-end gap-1">
                        {!r.je_id && r.math_verified ? (
                          <Button variant="outline" size="sm" title="Buat jurnal draf"
                            data-testid={`fin-settlement-journal-${r.settlement_id}`}
                            disabled={busy === `journal:${r.id}`} onClick={() => act(r, 'journal')}>
                            <BookCheck className="w-3.5 h-3.5" /> Jurnal
                          </Button>
                        ) : null}
                        {r.je_status === 'draft' ? (
                          <Button variant="success" size="sm" title="Posting jurnal ke buku besar"
                            data-testid={`fin-settlement-post-${r.settlement_id}`}
                            disabled={busy === `post:${r.id}`} onClick={() => act(r, 'post')}>
                            <Send className="w-3.5 h-3.5" /> Posting
                          </Button>
                        ) : null}
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="icon-sm" title="Lainnya" aria-label="Lainnya" data-testid={`fin-settlement-more-${r.settlement_id}`}>
                              <MoreHorizontal className="w-4 h-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem data-testid={`fin-settlement-reconcile-${r.settlement_id}`}
                              disabled={busy === `recon:${r.id}`} onClick={() => reconcile(r)}>
                              <Scale className="w-4 h-4 mr-2" />Cocokkan dengan omzet periode
                            </DropdownMenuItem>
                            {!r.je_id ? (
                              <>
                                <DropdownMenuItem data-testid={`fin-settlement-edit-${r.settlement_id}`} onClick={() => openEdit(r)}>
                                  <Pencil className="w-4 h-4 mr-2" />Koreksi angka
                                </DropdownMenuItem>
                                <DropdownMenuItem data-testid={`fin-settlement-delete-${r.settlement_id}`}
                                  disabled={busy === `delete:${r.id}`} className="text-[hsl(var(--danger-text))]"
                                  onClick={async () => { if (await confirmDialog({ title: `Hapus laporan dana dilepas ${r.settlement_id}?`, confirmLabel: 'Hapus', danger: true })) act(r, 'delete'); }}>
                                  <Trash2 className="w-4 h-4 mr-2" />Hapus
                                </DropdownMenuItem>
                              </>
                            ) : null}
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {total > PAGE && <PaginationBar total={total} skip={skip} limit={PAGE} onPageChange={setSkip} className="px-3 py-2" />}
      </GlassCard>
      </>) : null}
    </PageLayout>
  );
}

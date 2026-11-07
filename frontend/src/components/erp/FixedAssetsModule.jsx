import { useState, useEffect, useCallback } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { StatTile, StatusBadge, EmptyState, Notice } from './moduleAtoms';
import PageLayout, { DetailPanel } from './layout/PageLayout';
import {
  Plus, Trash2, Eye, RefreshCw, Package, AlertTriangle, Printer
} from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table';
import PaginationLite from '@/components/ui/pagination-lite';
import { toast } from 'sonner';
import { formatRupiah, formatDateID } from '@/lib/format';
import { MoneyInput } from '@/components/ui/money-input';
import DocNumberField, { useDocNumberPolicy, docNumberPayload } from './docnum/DocNumberField';
import CashAccountSelect, { usePaymentCashAccounts } from './SdmCashAccountSelect';
import { todayWIB, thisMonthWIB } from '../../lib/waktu';
import { cvAccountParam, useCv } from '@/lib/entitas';

// 2026-11-02 (K18): form wajib memilih jenis perolehan. Pembelian baru → sumber dana → jurnal
// perolehan otomatis ke akun kategori; Aset lama → akumulasi per go-live, tanpa jurnal perolehan.
const ACQ_TYPES = [
  { value: 'purchase', label: 'Pembelian baru', hint: 'Jurnal perolehan otomatis: debit akun aset kategori, kredit sumber dana.' },
  { value: 'opening', label: 'Aset lama (saldo awal)', hint: 'Tanpa jurnal perolehan (nilai sudah di jurnal Saldo Awal). Penyusutan mulai bulan go-live.' },
];
const FUNDING = [
  { value: 'cash', label: 'Rekening kas/bank (dibayar tunai/transfer)' },
  { value: 'payable', label: 'Hutang pemasok — faktur menyusul (Hutang Belum Ditagih)' },
  { value: 'ap_invoice', label: 'Faktur pemasok yang sudah dicatat' },
];
const ACC_FIELDS = ['account_id_asset', 'account_id_accum_depr', 'account_id_depr_expense'];

const CATEGORIES = ['tanah','bangunan','mesin','kendaraan','peralatan','it','furnitur','lain-lain'];
// 2026-11-07 (audit form Tahap 5): pilihan disamakan dengan server (routes/rahaza_fixed_assets.DEPR_METHODS):
// "Tidak disusutkan" (`none`, mis. tanah) dulu tidak ada di layar — tanah terpaksa diberi umur & disusutkan.
const DEPR_METHODS = [
  { value: 'straight_line', label: 'Garis lurus' },
  { value: 'double_declining', label: 'Saldo menurun ganda' },
  { value: 'none', label: 'Tidak disusutkan (mis. tanah)' },
];
const DEPRECIATING = ['straight_line', 'double_declining'];
// Akun per peran dibatasi tipenya (dulu ketiga pilihan memuat seluruh bagan akun — beban, hutang, modal…):
// aset & akumulasi penyusutan = Aset (akumulasi = akun kontra aset); beban penyusutan = beban / HPP (overhead).
const ACC_TYPES = {
  account_id_asset: ['ASSET'],
  account_id_accum_depr: ['ASSET'],
  account_id_depr_expense: ['EXPENSE', 'COGS', 'OTHER_EXPENSE'],
};
const CAT_LABELS = {
  tanah: 'Tanah', bangunan: 'Bangunan', mesin: 'Mesin', kendaraan: 'Kendaraan',
  peralatan: 'Peralatan', it: 'IT', furnitur: 'Furnitur', 'lain-lain': 'Lain-lain'
};
const STATUS_META = {
  active: { label: 'Aktif', tone: 'success' },
  disposed: { label: 'Dilepas', tone: 'muted' },
  fully_depreciated: { label: 'Habis disusutkan', tone: 'warning' },
};
const BULAN = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'];
const periodLabel = (code) => { const [y, m] = String(code || '').split('-'); return BULAN[Number(m) - 1] ? `${BULAN[Number(m) - 1]} ${y}` : (code || '—'); };
const fmtRp = formatRupiah;
const metodeLabel = (m) => DEPR_METHODS.find((x) => x.value === m)?.label || (m === 'double_declining' ? 'Saldo menurun ganda' : 'Garis lurus');

/**
 * Daftar aset (menu Aset Tetap › Daftar aset).
 * 2026-11-05 (PANDUAN_UI G1/G13): cetakan PageLayout. Rincian & jadwal penyusutan satu aset dibuka DI HALAMAN
 * di atas tabel (dulu layar daftar diganti layar rincian dengan tombol "← Daftar Aset").
 * 2026-11-08 (Standar UI/UX v2): rincian = popup (tabel jadwal pakai ui/table + bisa diunduh); form aset baru =
 * FormPopup panjang, form pelepasan = FormPopup pendek; tanggal = DatePicker; daftar aset bisa diunduh Excel/CSV
 * (semua halaman); kotak kuning buatan sendiri → Notice; kartu angka berketerangan.
 */
export default function FixedAssetsModule({ token }) {
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
  const coaCv = cvAccountParam(useCv()?.cv);  // Tahap 8: akun aset/beban CV terpilih saja
  const [assets, setAssets] = useState([]);
  const [summary, setSummary] = useState(null);
  const [selected, setSelected] = useState(null);
  const [schedule, setSchedule] = useState([]);
  const [deprDue, setDeprDue] = useState([]);
  const [loading, setLoading] = useState(false);
  const [pagination, setPagination] = useState(null);
  const [page, setPage] = useState(1);
  const [filterCat, setFilterCat] = useState('');
  const [filterStatus, setFilterStatus] = useState('active');
  const [coa, setCoa] = useState([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [disposeOpen, setDisposeOpen] = useState(false);
  const [disposeForm, setDisposeForm] = useState({ disposal_date: '', disposal_value: '', notes: '' });

  const BLANK_FORM = {
    code: '', name: '', category: 'peralatan', purchase_date: '', purchase_cost: '',
    residual_value: '', useful_life_months: '60', depreciation_method: 'straight_line',
    account_id_asset: '', account_id_accum_depr: '', account_id_depr_expense: '',
    location: '', supplier: '', supplier_id: '', serial_number: '', notes: '',
    acquisition_type: '', funding_source: '', cash_account_id: '', ap_invoice_id: '',
    golive_date: '', opening_accumulated_depr: '',
  };
  const [form, setForm] = useState(BLANK_FORM);
  const [acqOpts, setAcqOpts] = useState(null);
  const [apInvoices, setApInvoices] = useState([]);
  const { accounts: cashAccounts, loaded: cashLoaded } = usePaymentCashAccounts(token);
  const maxDate = acqOpts?.today_wib || todayWIB();

  // Akun bawaan kategori → isi dropdown akun (bisa diganti per aset)
  const applyCategoryDefaults = (cat, opts = acqOpts) => {
    const def = opts?.category_accounts?.[cat] || {};
    // tanah tidak disusutkan (kategori tanah di server tanpa akun akumulasi/beban penyusutan)
    setForm(v => ({
      ...v, category: cat, ...Object.fromEntries(ACC_FIELDS.map(f => [f, def[f]?.id || ''])),
      ...(cat === 'tanah' ? { depreciation_method: 'none' }
        : (v.category === 'tanah' && v.depreciation_method === 'none' ? { depreciation_method: 'straight_line' } : {})),
    }));
  };
  const openCreate = async () => {
    setForm(BLANK_FORM); setModalOpen(true); fetchCoa();
    const r = await fetch('/api/rahaza/finance/fixed-assets/acquisition-options', { headers });
    if (r.ok) {
      const o = await r.json(); setAcqOpts(o);
      setForm(v => ({ ...v, golive_date: o.golive_default || '' }));
      applyCategoryDefaults('peralatan', o);
    }
  };
  // Pemasok dari master pemasok (id · kode · nama), dikirim server lewat acquisition-options (bisa dibaca staf
  // Keuangan tanpa akses Pengadaan). 2026-11-07 (Tahap 6, KU2): sumber dana "Hutang pemasok — faktur menyusul"
  // WAJIB memilih dari master (id + nama disimpan); sumber dana lain tetap teks bebas dengan saran.
  const suppliers = acqOpts?.suppliers || [];
  const creditPurchase = form.acquisition_type === 'purchase' && form.funding_source === 'payable';
  const loadApInvoices = async () => {
    const r = await fetch('/api/rahaza/ap-invoices', { headers });
    if (r.ok) setApInvoices((await r.json()).filter(i => !['draft', 'cancelled', 'void'].includes((i.status || '').toLowerCase())));
  };
  // SESI #27 — kebijakan penomoran Kode Aset Tetap (Otomatis/Manual) milik owner.
  const numPolicy = useDocNumberPolicy('rahaza_fixed_assets.code',
                                       localStorage.getItem('erp_token'));

  const fetchAssets = useCallback(async (p = 1) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: p, limit: 20 });
      if (filterCat) params.set('category', filterCat);
      if (filterStatus) params.set('status', filterStatus);
      const r = await fetch(`/api/rahaza/finance/fixed-assets?${params}`, { headers });
      const data = await r.json();
      if (data.items && data.pagination) {
        setAssets(data.items); setPagination(data.pagination);
      } else {
        setAssets(Array.isArray(data) ? data : []); setPagination(null);
      }
    } finally { setLoading(false); }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, filterCat, filterStatus]);

  const fetchSummary = useCallback(async () => {
    const r = await fetch('/api/rahaza/finance/fixed-assets-summary', { headers });
    if (r.ok) setSummary(await r.json());
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const fetchDeprDue = useCallback(async () => {
    const r = await fetch('/api/rahaza/finance/fixed-assets/depreciation-due', { headers });
    if (r.ok) setDeprDue(await r.json());
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => { setPage(1); fetchAssets(1); }, [filterCat, filterStatus]); // eslint-disable-line
  useEffect(() => { fetchAssets(page); }, [page]); // eslint-disable-line
  useEffect(() => { fetchSummary(); fetchDeprDue(); }, []); // eslint-disable-line

  const fetchCoa = async () => {
    // K18: hanya akun aktif & bukan header (dulu seluruh COA termasuk nonaktif/grup)
    const r = await fetch(`/api/rahaza/coa/accounts${coaCv ? `?${coaCv}` : ''}`, { headers });
    if (r.ok) setCoa((await r.json()).filter(a => a.active !== false && !a.is_group));
  };

  const openDetail = async (asset) => {
    setSelected(asset);
    setSchedule([]);
    const r = await fetch(`/api/rahaza/finance/fixed-assets/${asset.id}/schedule`, { headers });
    if (r.ok) setSchedule(await r.json());
  };
  const toggleDetail = (asset) => (selected?.id === asset.id ? setSelected(null) : openDetail(asset));

  const createAsset = async () => {
    // K18 — validasi sama dengan server: jenis perolehan wajib, harga > 0, umur > 0, tanggal ≤ hari ini (WIB)
    if (!form.acquisition_type) { toast.error('Pilih jenis perolehan: Pembelian baru atau Aset lama (saldo awal)'); return; }
    if (!(parseFloat(form.purchase_cost) > 0)) { toast.error('Harga perolehan harus lebih dari 0'); return; }
    if (DEPRECIATING.includes(form.depreciation_method) && !(parseInt(form.useful_life_months, 10) > 0)) { toast.error('Masa manfaat (bulan) harus lebih dari 0'); return; }
    if (form.purchase_date && form.purchase_date > maxDate) { toast.error(`Tanggal pembelian melewati hari ini (${formatDateID(maxDate)})`); return; }
    if (form.acquisition_type === 'purchase' && !form.funding_source) { toast.error('Pilih sumber dana pembelian'); return; }
    if (creditPurchase && !form.supplier_id) { toast.error('Pilih pemasok dari Master Pemasok untuk pembelian kredit (faktur menyusul)'); return; }
    if (form.acquisition_type === 'opening' && !form.golive_date) { toast.error('Isi tanggal go-live untuk aset lama'); return; }
    // SESI #27 — `code` DIBUANG dari payload saat mode OTOMATIS: mengirimnya akan
    // ditolak backend ("nomor tidak boleh diketik manual").
    const { code: _formCode, ...rest } = form;
    const r = await fetch('/api/rahaza/finance/fixed-assets', {
      method: 'POST', headers,
      body: JSON.stringify({
        ...rest,
        ...docNumberPayload(numPolicy, 'code', form.code),
        supplier_id: creditPurchase ? form.supplier_id : undefined,
        purchase_cost: parseFloat(form.purchase_cost) || 0,
        residual_value: parseFloat(form.residual_value) || 0,
        useful_life_months: parseInt(form.useful_life_months, 10) || 0,
        opening_accumulated_depr: parseFloat(form.opening_accumulated_depr) || 0,
      }),
    });
    if (r.ok) {
      const d = await r.json();
      const je = d._posting_result?.je_number;
      toast.success(je ? `Aset ${d.code} didaftarkan · jurnal perolehan ${je}` : `Aset ${d.code} didaftarkan (tanpa jurnal perolehan) · ${d._schedule_periods || 0} periode penyusutan`);
      setModalOpen(false); setForm(BLANK_FORM);
      fetchAssets(1); fetchSummary(); fetchDeprDue();
    } else { const e = await r.json().catch(() => ({})); toast.error(e.detail || 'Gagal'); }
  };

  const postDepr = async (assetId, period) => {
    const r = await fetch(`/api/rahaza/finance/fixed-assets/${assetId}/post-depr/${period}`, {
      method: 'POST', headers, body: JSON.stringify({})
    });
    if (r.ok) {
      const res = await r.json();
      toast.success(`Penyusutan ${periodLabel(period)} dicatat: ${fmtRp(res.depr_amount || 0)}`);
      fetchDeprDue(); fetchSummary();
      if (selected) {
        const sr = await fetch(`/api/rahaza/finance/fixed-assets/${selected.id}/schedule`, { headers });
        if (sr.ok) setSchedule(await sr.json());
      }
    } else { const e = await r.json(); toast.error(e.detail || 'Gagal mencatat penyusutan'); }
  };

  const disposeAsset = async () => {
    if (!selected) return;
    const r = await fetch(`/api/rahaza/finance/fixed-assets/${selected.id}/dispose`, {
      method: 'POST', headers,
      body: JSON.stringify({
        ...disposeForm,
        disposal_value: parseFloat(disposeForm.disposal_value) || 0,
      }),
    });
    if (r.ok) {
      const res = await r.json();
      toast.success(`Aset dilepas. Laba/rugi pelepasan: ${fmtRp(res.gain_loss || 0)}`);
      setDisposeOpen(false);
      const updated = await fetch(`/api/rahaza/finance/fixed-assets/${selected.id}`, { headers });
      if (updated.ok) setSelected(await updated.json());
      fetchAssets(page); fetchSummary();
    } else { const e = await r.json(); toast.error(e.detail || 'Gagal'); }
  };

  const printLabel = async () => {
    try {
      const r = await fetch(`/api/rahaza/finance/fixed-assets/${selected.id}/label-pdf`, { headers: { Authorization: headers.Authorization } });
      if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || `HTTP ${r.status}`); }
      const url = URL.createObjectURL(await r.blob());
      window.open(url, '_blank');
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) { toast.error(e.message); }
  };

  // Unduh: semua aset sesuai saringan (server berhalaman 20) — dibaca per 200.
  const ambilSemuaAset = async () => {
    const out = [];
    for (let p = 1; p <= 100; p += 1) {
      const params = new URLSearchParams({ page: p, limit: 200 });
      if (filterCat) params.set('category', filterCat);
      if (filterStatus) params.set('status', filterStatus);
      const r = await fetch(`/api/rahaza/finance/fixed-assets?${params}`, { headers });
      if (!r.ok) throw new Error('gagal');
      const d = await r.json();
      const items = d.items || (Array.isArray(d) ? d : []);
      out.push(...items);
      if (!d.pagination || !d.pagination.has_next || !items.length) break;
    }
    return out;
  };
  const KOLOM_ASET = [
    { label: 'Kode', nilai: (a) => a.code },
    { label: 'Nama', nilai: (a) => a.name },
    { label: 'Kategori', nilai: (a) => CAT_LABELS[a.category] || a.category },
    { label: 'Tanggal beli', nilai: (a) => formatDateID(a.purchase_date) },
    { label: 'Harga perolehan', nilai: (a) => Number(a.purchase_cost) || 0 },
    { label: 'Akumulasi penyusutan', nilai: (a) => Number(a.accumulated_depreciation) || 0 },
    { label: 'Nilai buku', nilai: (a) => Number(a.book_value_current) || 0 },
    { label: 'Metode', nilai: (a) => metodeLabel(a.depreciation_method) },
    { label: 'Status', nilai: (a) => (STATUS_META[a.status] || { label: a.status }).label },
    { label: 'Lokasi', nilai: (a) => a.location || '' },
  ];

  const curPeriod = thisMonthWIB();
  const accountsFor = (fld) => coa.filter(a => ACC_TYPES[fld].includes(a.type) || a.id === form[fld]);
  const refreshAll = () => { fetchAssets(1); fetchSummary(); fetchDeprDue(); };

  // ── RINCIAN SATU ASET (di halaman, di atas tabel)
  let detail = null;
  if (selected) {
    const pctDepr = selected.purchase_cost > 0
      ? Math.min(100, Math.round((selected.accumulated_depreciation / selected.purchase_cost) * 100))
      : 0;
    const descr = [
      selected.code,
      CAT_LABELS[selected.category] || selected.category,
      selected.acquisition_type === 'opening' && `Aset lama (go-live ${formatDateID(selected.golive_date)}, akumulasi awal ${fmtRp(selected.opening_accumulated_depr)})`,
      selected.acquisition_type === 'purchase' && `Pembelian baru${selected.gl_je_number ? ` · jurnal ${selected.gl_je_number}` : ''}`,
    ].filter(Boolean).join(' · ');
    detail = (
      <DetailPanel
        title={selected.name}
        description={descr}
        onClose={() => setSelected(null)}
        testId="fixed-asset-detail-page"
        actions={selected.status === 'active' && (
          <>
            {/* 2026-11-02 (registri aset tunggal): label aset dari registri induk — generator sama dgn Portal Aset */}
            <Button variant="outline" data-testid="fa-print-label" onClick={printLabel}>
              <Printer className="w-4 h-4" /> Label
            </Button>
            <Button variant="destructive" onClick={() => { setDisposeOpen(true); setDisposeForm({ disposal_date: todayWIB(), disposal_value: '', notes: '' }); }}>
              <Trash2 className="w-4 h-4" /> Lepaskan
            </Button>
          </>
        )}
      >
        <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
          {[
            { label: 'Harga perolehan', value: fmtRp(selected.purchase_cost) },
            { label: 'Akumulasi penyusutan', value: fmtRp(selected.accumulated_depreciation) },
            { label: 'Nilai buku', value: fmtRp(selected.book_value_current) },
            { label: 'Sudah disusutkan', value: `${pctDepr}%` },
          ].map(c => (
            <div key={c.label}>
              <dt className="text-xs text-muted-foreground">{c.label}</dt>
              <dd className="font-semibold text-foreground tabular-nums">{c.value}</dd>
            </div>
          ))}
        </dl>
        <div className="h-2 bg-secondary rounded-full overflow-hidden" title={`Sudah disusutkan ${pctDepr}%`}>
          <div className="h-full bg-[hsl(var(--primary))] rounded-full" style={{ width: `${pctDepr}%` }} />
        </div>
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-medium text-foreground">Jadwal penyusutan · {schedule.length} periode</p>
          <TombolUnduh namaBerkas={`jadwal-penyusutan-${selected.code}`} namaLembar="Jadwal penyusutan" baris={schedule} testId="fa-schedule-unduh"
            kolom={[
              { label: 'Periode', nilai: (x) => periodLabel(x.period) },
              { label: 'Nilai buku awal', nilai: (x) => Number(x.book_value_start) || 0 },
              { label: 'Penyusutan', nilai: (x) => Number(x.depr_amount) || 0 },
              { label: 'Akumulasi', nilai: (x) => Number(x.accumulated_depr) || 0 },
              { label: 'Nilai buku akhir', nilai: (x) => Number(x.book_value_end) || 0 },
              { label: 'Status', nilai: (x) => (x.cancelled ? 'Dibatalkan' : x.posted ? 'Tercatat' : 'Belum dicatat') },
            ]} />
        </div>
        <Table className="md:min-w-0" data-testid="fa-schedule-table">
          <TableHeader>
            <TableRow>
              <TableHead>Periode</TableHead>
              <TableHead className="text-right">Nilai buku awal</TableHead>
              <TableHead className="text-right">Penyusutan</TableHead>
              <TableHead className="text-right">Akumulasi</TableHead>
              <TableHead className="text-right">Nilai buku akhir</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Aksi</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {schedule.map(x => (
              <TableRow key={x.id} className={x.cancelled ? 'opacity-40' : ''}>
                <TableCell className="whitespace-nowrap font-medium">{periodLabel(x.period)}</TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtRp(x.book_value_start)}</TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtRp(x.depr_amount)}</TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtRp(x.accumulated_depr)}</TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtRp(x.book_value_end)}</TableCell>
                <TableCell>
                  {x.cancelled ? <StatusBadge tone="muted" label="Dibatalkan" />
                    : x.posted ? <StatusBadge tone="success" label="Tercatat" />
                      : <StatusBadge tone="default" label="Belum dicatat" />}
                </TableCell>
                <TableCell className="text-right">
                  {!x.posted && !x.cancelled && x.period <= curPeriod && (
                    <Button size="sm" variant="success" onClick={() => postDepr(selected.id, x.period)}>
                      Catat
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </DetailPanel>
    );
  }

  return (
    <PageLayout
      testId="fixed-assets-list-page"
      title="Daftar aset"
      subtitle="Daftarkan aset, pantau nilai buku, dan catat penyusutannya."
      actions={
        <Button onClick={openCreate} data-testid="btn-new-asset">
          <Plus className="w-4 h-4" /> Aset baru
        </Button>
      }
      filters={<>
        <SmartNativeSelect value={filterCat} onChange={e => setFilterCat(e.target.value)} className="h-9 w-44" aria-label="Kategori" data-testid="fa-filter-category">
          <option value="">Semua kategori</option>
          {CATEGORIES.map(c => <option key={c} value={c}>{CAT_LABELS[c]}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={filterStatus} onChange={e => setFilterStatus(e.target.value)} searchable={false} className="h-9 w-40" aria-label="Status" data-testid="fa-filter-status">
          <option value="active">Aktif</option>
          <option value="disposed">Dilepas</option>
          <option value="">Semua status</option>
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="daftar-aset-tetap" namaLembar="Aset tetap" baris={assets} ambilSemua={ambilSemuaAset} kolom={KOLOM_ASET} testId="fa-unduh" />
        <Button size="icon" variant="outline" onClick={refreshAll} disabled={loading} title="Muat ulang" aria-label="Muat ulang" data-testid="fa-refresh">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </>}
      summary={<>
        {/* Summary KPIs — PANDUAN_UI G5 (2026-11-04): StatTile netral, tidak tampil bila belum ada aset */}
        {summary && Number(summary.total_assets) > 0 && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatTile label="Jumlah aset" value={`${summary.total_assets} aset`} sub="Semua aset, tanpa saringan" />
            <StatTile label="Harga perolehan" value={fmtRp(summary.total_cost)} sub="Total semua aset" />
            <StatTile label="Nilai buku" value={fmtRp(summary.total_nbv)} sub="Perolehan − akumulasi penyusutan" />
            <StatTile label="Penyusutan bulan ini" value={summary.depr_due_this_month ? `${summary.depr_due_this_month} aset` : 'Tidak ada'} accent={summary.depr_due_this_month > 0 ? 'warning' : 'muted'} sub="Jatuh tempo, belum dicatat" />
          </div>
        )}
        {deprDue.length > 0 && (
          <Notice tone="warning" icon={AlertTriangle} testId="fa-depr-due" title={`${deprDue.length} aset perlu dicatat penyusutannya bulan ini`}>
            <div className="flex flex-wrap gap-2 mt-1">
              {deprDue.slice(0, 5).map(d => (
                <Button key={d.id} size="sm" variant="outline" onClick={() => postDepr(d.asset_id, d.period)}>
                  Catat {d.asset_name} · {periodLabel(d.period)}
                </Button>
              ))}
              {deprDue.length > 5 && <span className="text-xs text-muted-foreground self-center">+{deprDue.length - 5} lainnya</span>}
            </div>
          </Notice>
        )}
      </>}
      detail={detail}
      footer={pagination && pagination.total_pages > 1 && (
        <PaginationLite page={pagination.page || page} totalPages={pagination.total_pages} total={pagination.total}
          pageSize={pagination.limit || 20} onPageChange={setPage} />
      )}
    >
      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <Skeleton className="h-40 m-4" />
        ) : assets.length === 0 ? (
          <EmptyState icon={Package} title="Belum ada aset tetap"
            description={filterCat || filterStatus !== 'active' ? 'Tidak ada aset yang cocok dengan penyaring.' : 'Daftarkan aset pertama lewat tombol Aset baru.'} />
        ) : (
          <div className="overflow-x-auto">
            <Table className="w-full md:min-w-0" data-testid="fa-table">
              <TableHeader>
                <TableRow>
                  <TableHead className="text-left">Kode</TableHead>
                  <TableHead className="text-left">Nama</TableHead>
                  <TableHead className="text-left">Kategori</TableHead>
                  <TableHead className="text-left">Tgl beli</TableHead>
                  <TableHead className="text-right">Harga perolehan</TableHead>
                  <TableHead className="text-right">Nilai buku</TableHead>
                  <TableHead className="text-left">Metode</TableHead>
                  <TableHead className="text-left">Status</TableHead>
                  <TableHead className="text-right">Aksi</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {assets.map(a => {
                  const st = STATUS_META[a.status] || { label: a.status, tone: 'default' };
                  const open = selected?.id === a.id;
                  return (
                    <TableRow key={a.id} className={open ? 'bg-[hsl(var(--primary)/0.06)]' : ''}>
                      <TableCell className="whitespace-nowrap">
                        <Button variant="link" size="sm" className="h-auto p-0" onClick={() => toggleDetail(a)}>{a.code}</Button>
                      </TableCell>
                      <TableCell className="font-medium">{a.name}</TableCell>
                      <TableCell>{CAT_LABELS[a.category] || a.category}</TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">{formatDateID(a.purchase_date)}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmtRp(a.purchase_cost)}</TableCell>
                      <TableCell className="text-right tabular-nums font-medium">{fmtRp(a.book_value_current)}</TableCell>
                      <TableCell className="whitespace-nowrap">{metodeLabel(a.depreciation_method)}</TableCell>
                      <TableCell><StatusBadge tone={st.tone} label={st.label} /></TableCell>
                      <TableCell className="text-right">
                        <Button variant="ghost" size="icon-sm" onClick={() => toggleDetail(a)} title={open ? 'Tutup rincian' : 'Rincian & jadwal'} aria-label={open ? 'Tutup rincian' : 'Rincian & jadwal'}>
                          <Eye className="w-4 h-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </GlassCard>

      {/* Formulir pelepasan — popup form standar (pendek) */}
      {disposeOpen && selected && (
        <FormPopup open onClose={() => setDisposeOpen(false)} ukuran="pendek" testId="fa-dispose-form"
          judul={`Lepaskan aset ${selected.code}`} keterangan="Jurnal pelepasan dibuat otomatis; laba/rugi pelepasan dihitung dari nilai buku."
          onSimpan={disposeAsset} labelSimpan="Lepaskan aset" bisaSimpan={!!disposeForm.disposal_date}>
          <Isian label="Tanggal pelepasan" wajib>
            <DatePicker value={disposeForm.disposal_date} onChange={v => setDisposeForm(f => ({ ...f, disposal_date: v }))} testId="fa-dispose-date" />
          </Isian>
          <Isian label="Nilai jual (Rp)">
            <MoneyInput glass placeholder="0" value={disposeForm.disposal_value} onChange={e => setDisposeForm(f => ({...f, disposal_value: e.target.value}))} />
          </Isian>
          <Isian label="Keterangan">
            <GlassInput placeholder="Alasan pelepasan" value={disposeForm.notes} onChange={e => setDisposeForm(f => ({...f, notes: e.target.value}))} />
          </Isian>
        </FormPopup>
      )}

      {/* Create Asset Modal */}
      {modalOpen && (
        <FormPopup open onClose={() => setModalOpen(false)} ukuran="panjang" testId="fa-create-form"
          judul="Daftarkan aset tetap baru" keterangan="Jurnal perolehan, penyusutan, dan pelepasan memakai akun di bawah."
          onSimpan={createAsset} labelSimpan="Daftarkan aset">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* K18 (2026-11-02) — jenis perolehan WAJIB dipilih */}
            <div className="sm:col-span-2" data-testid="asset-acq-type">
              <p className="mb-1.5 text-sm font-medium text-foreground">Jenis perolehan<span className="ml-0.5 text-[hsl(var(--danger-text))]">*</span></p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {ACQ_TYPES.map(t => (
                  <Button key={t.value} type="button" variant="outline" onClick={() => setForm(v => ({ ...v, acquisition_type: t.value }))}
                    data-testid={`asset-acq-${t.value}`} aria-pressed={form.acquisition_type === t.value}
                    className={`h-auto flex-col items-start justify-start whitespace-normal text-left py-2 ${form.acquisition_type === t.value ? 'border-primary bg-primary/10' : ''}`}>
                    <span className="font-medium">{t.label}</span>
                    <span className="text-xs font-normal text-muted-foreground">{t.hint}</span>
                  </Button>
                ))}
              </div>
            </div>
            {form.acquisition_type === 'purchase' && (
              <>
                <div className="sm:col-span-2"><label className="block text-sm font-medium text-foreground mb-1.5">Sumber dana *</label>
                  <SmartNativeSelect value={form.funding_source} data-testid="asset-funding" searchable={false} className="h-9 w-full"
                    onChange={e => { const v = e.target.value; setForm(f => ({ ...f, funding_source: v, ...(v === 'payable' ? {} : { supplier_id: '' }) })); if (v === 'ap_invoice') loadApInvoices(); }}>
                    <option value="">Pilih sumber dana</option>
                    {FUNDING.map(f => <option key={f.value} value={f.value}>{f.label}</option>)}
                  </SmartNativeSelect>
                </div>
                {form.funding_source === 'payable' && (
                  <div className="sm:col-span-2"><label className="block text-sm font-medium text-foreground mb-1.5">Pemasok (Master Pemasok) *</label>
                    <SmartNativeSelect value={form.supplier_id} data-testid="asset-supplier-master" className="h-9 w-full"
                      searchPlaceholder="Cari kode atau nama pemasok…"
                      onChange={e => { const id = e.target.value; const s = suppliers.find(x => x.id === id); setForm(f => ({ ...f, supplier_id: id, supplier: s?.name || '' })); }}>
                      <option value="">{suppliers.length ? 'Pilih pemasok' : 'Master Pemasok masih kosong'}</option>
                      {suppliers.map(s => <option key={s.id} value={s.id}>{s.code ? `${s.name} · ${s.code}` : s.name}</option>)}
                    </SmartNativeSelect>
                    <p className="text-xs text-muted-foreground mt-1">Hutang dicatat ke Hutang Belum Ditagih atas nama pemasok ini; faktur pemasoknya dicatat saat datang. Pemasok baru didaftarkan dulu di Master Pemasok.</p>
                  </div>
                )}
                {form.funding_source === 'cash' && (
                  <div className="sm:col-span-2"><label className="block text-sm font-medium text-foreground mb-1.5">Rekening kas/bank *</label>
                    <CashAccountSelect accounts={cashAccounts} loaded={cashLoaded} value={form.cash_account_id}
                      onChange={v => setForm(f => ({ ...f, cash_account_id: v }))} testId="asset-cash-account" />
                  </div>
                )}
                {form.funding_source === 'ap_invoice' && (
                  <div className="sm:col-span-2"><label className="block text-sm font-medium text-foreground mb-1.5">Faktur pemasok *</label>
                    <SmartNativeSelect value={form.ap_invoice_id} onChange={e => { const id = e.target.value; const inv = apInvoices.find(i => i.id === id); setForm(f => ({ ...f, ap_invoice_id: id, supplier: inv?.vendor_name || f.supplier })); }}
                      data-testid="asset-ap-invoice" className="h-9 w-full">
                      <option value="">Pilih faktur pemasok</option>
                      {apInvoices.map(i => <option key={i.id} value={i.id}>{i.invoice_number} · {i.vendor_name} · DPP {fmtRp(i.subtotal || i.total)}</option>)}
                    </SmartNativeSelect>
                    <p className="text-xs text-muted-foreground mt-1">Hutang sudah dicatat faktur; jurnal perolehan memindah akun debit faktur ke akun aset (hutang tidak dobel).</p>
                  </div>
                )}
              </>
            )}
            {form.acquisition_type === 'opening' && (
              <>
                <Isian label="Tanggal go-live" wajib>
                  <DatePicker max={maxDate} value={form.golive_date} onChange={v => setForm(f => ({ ...f, golive_date: v }))} testId="asset-golive" />
                </Isian>
                <div><label className="block text-sm font-medium text-foreground mb-1.5">Akumulasi penyusutan per go-live (Rp)</label>
                  <MoneyInput glass placeholder="0" value={form.opening_accumulated_depr} onChange={e => setForm(v => ({ ...v, opening_accumulated_depr: e.target.value }))} data-testid="asset-opening-accum" />
                  <p className="text-xs text-muted-foreground mt-1">Sama dengan angka akumulasi di jurnal Saldo Awal (belum termasuk bulan go-live).</p>
                </div>
              </>
            )}
            {/* SESI #27 — kolom Kode Aset diganti komponen kebijakan penomoran:
                mode OTOMATIS memperlihatkan nomor berikutnya (terkunci), mode MANUAL
                mewajibkan kode berpola. Dulu kolom ini bebas diketik tanpa aturan. */}
            <div className="sm:col-span-2">
              <DocNumberField
                policy={numPolicy} value={form.code}
                onChange={v => setForm(p => ({ ...p, code: v }))}
                testId="asset-docnum" label="Kode aset" />
            </div>
            <div><label className="block text-sm font-medium text-foreground mb-1.5">Nama aset *</label>
              <GlassInput placeholder="mis. Mesin Jahit Singer" value={form.name} onChange={e => setForm(v => ({...v, name: e.target.value}))} data-testid="asset-name" />
            </div>
            <div><label className="block text-sm font-medium text-foreground mb-1.5">Kategori *</label>
              <SmartNativeSelect value={form.category} onChange={e => applyCategoryDefaults(e.target.value)} searchable={false} className="h-9 w-full" data-testid="asset-category">
                {CATEGORIES.map(c => <option key={c} value={c}>{CAT_LABELS[c]}</option>)}
              </SmartNativeSelect>
            </div>
            <Isian label="Tanggal pembelian" wajib>
              <DatePicker max={maxDate} value={form.purchase_date} onChange={v => setForm(f => ({ ...f, purchase_date: v }))} testId="asset-purchase-date" />
            </Isian>
            <div><label className="block text-sm font-medium text-foreground mb-1.5">Harga perolehan (Rp) *</label>
              <MoneyInput glass placeholder="0" value={form.purchase_cost} onChange={e => setForm(v => ({...v, purchase_cost: e.target.value}))} data-testid="asset-cost" />
            </div>
            <div><label className="block text-sm font-medium text-foreground mb-1.5">Nilai sisa (Rp)</label>
              <MoneyInput glass placeholder="0" value={form.residual_value} onChange={e => setForm(v => ({...v, residual_value: e.target.value}))} />
            </div>
            <div><label className="block text-sm font-medium text-foreground mb-1.5">Masa manfaat (bulan) *</label>
              <GlassInput type="number" min="0" placeholder="60" value={form.depreciation_method === 'none' ? '' : form.useful_life_months} disabled={form.depreciation_method === 'none'}
                onChange={e => setForm(v => ({...v, useful_life_months: e.target.value}))} data-testid="asset-life" />
            </div>
            <div><label className="block text-sm font-medium text-foreground mb-1.5">Metode penyusutan *</label>
              <SmartNativeSelect value={form.depreciation_method} onChange={e => setForm(v => ({...v, depreciation_method: e.target.value}))} searchable={false} className="h-9 w-full" data-testid="asset-method">
                {DEPR_METHODS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
              </SmartNativeSelect>
            </div>
            <p className="sm:col-span-2 text-xs text-muted-foreground">Akun di bawah terisi otomatis dari kategori; jurnal perolehan, penyusutan, dan pelepasan memakai akun ini.</p>
            <div><label className="block text-sm font-medium text-foreground mb-1.5">Akun aset</label>
              <SmartNativeSelect value={form.account_id_asset} onChange={e => setForm(v => ({...v, account_id_asset: e.target.value}))} className="h-9 w-full" data-testid="asset-acc-asset">
                <option value="">Pilih (opsional)</option>
                {accountsFor('account_id_asset').map(a => <option key={a.id} value={a.id}>{`${a.code} · ${a.name}`}</option>)}
              </SmartNativeSelect>
            </div>
            <div><label className="block text-sm font-medium text-foreground mb-1.5">Akun akumulasi penyusutan</label>
              <SmartNativeSelect value={form.account_id_accum_depr} onChange={e => setForm(v => ({...v, account_id_accum_depr: e.target.value}))} className="h-9 w-full" data-testid="asset-acc-accum">
                <option value="">Pilih (opsional)</option>
                {accountsFor('account_id_accum_depr').map(a => <option key={a.id} value={a.id}>{`${a.code} · ${a.name}`}</option>)}
              </SmartNativeSelect>
            </div>
            <div><label className="block text-sm font-medium text-foreground mb-1.5">Akun beban penyusutan</label>
              <SmartNativeSelect value={form.account_id_depr_expense} onChange={e => setForm(v => ({...v, account_id_depr_expense: e.target.value}))} className="h-9 w-full" data-testid="asset-acc-expense">
                <option value="">Pilih (opsional)</option>
                {accountsFor('account_id_depr_expense').map(a => <option key={a.id} value={a.id}>{`${a.code} · ${a.name}`}</option>)}
              </SmartNativeSelect>
            </div>
            {[{l:'Lokasi', k:'location'},{l:'Pemasok', k:'supplier', list: 'fa-supplier-list'},{l:'No. seri', k:'serial_number'}].map(f => (
              <div key={f.k}><label className="block text-sm font-medium text-foreground mb-1.5">{f.l}</label>
                <GlassInput value={form[f.k]} onChange={e => setForm(v => ({...v, [f.k]: e.target.value}))} list={f.list}
                  disabled={f.k === 'supplier' && creditPurchase} title={f.k === 'supplier' && creditPurchase ? 'Mengikuti pemasok yang dipilih di atas' : undefined}
                  placeholder={f.k === 'supplier' ? (creditPurchase ? 'Pilih pemasok di atas' : 'Ketik / pilih dari master pemasok') : undefined} data-testid={`asset-${f.k}`} />
              </div>
            ))}
            <datalist id="fa-supplier-list">
              {suppliers.map(x => <option key={x.id} value={x.name}>{x.code}</option>)}
            </datalist>
          </div>
        </FormPopup>
      )}
    </PageLayout>
  );
}

import { useState, useEffect, useCallback } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { StatTile } from './moduleAtoms';
import {
  Plus, Edit2, Trash2, Eye, RefreshCw, ChevronDown,
  Package, Calendar, AlertTriangle, CheckCircle, Upload, TrendingDown, Printer
} from 'lucide-react';
import { GlassCard, GlassPanel, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import Modal from './Modal';
import PaginationBar from './PaginationBar';
import { toast } from 'sonner';
import { formatRupiah } from '@/lib/format';
import { MoneyInput } from '@/components/ui/money-input';
import DocNumberField, { useDocNumberPolicy, docNumberPayload } from './docnum/DocNumberField';
import CashAccountSelect, { usePaymentCashAccounts } from './SdmCashAccountSelect';
import { todayWIB, thisMonthWIB } from '../../lib/waktu';

// 2026-11-02 (K18): form wajib memilih jenis perolehan. Pembelian baru → sumber dana → jurnal
// perolehan otomatis ke akun kategori; Aset lama → akumulasi per go-live, tanpa jurnal perolehan.
const ACQ_TYPES = [
  { value: 'purchase', label: 'Pembelian baru', hint: 'Jurnal perolehan otomatis: Dr akun aset kategori / Cr sumber dana.' },
  { value: 'opening', label: 'Aset lama (saldo awal)', hint: 'Tanpa jurnal perolehan (nilai sudah di jurnal Saldo Awal). Penyusutan mulai bulan go-live.' },
];
const FUNDING = [
  { value: 'cash', label: 'Rekening kas/bank (dibayar tunai/transfer)' },
  { value: 'payable', label: 'Hutang pemasok — faktur menyusul (Hutang Belum Ditagih)' },
  { value: 'ap_invoice', label: 'Faktur pemasok yang sudah dicatat' },
];
const ACC_FIELDS = ['account_id_asset', 'account_id_accum_depr', 'account_id_depr_expense'];

const CATEGORIES = ['tanah','bangunan','mesin','kendaraan','peralatan','it','furnitur','lain-lain'];
const DEPR_METHODS = [
  { value: 'straight_line', label: 'Garis Lurus (Straight-Line)' },
  { value: 'double_declining', label: 'Saldo Menurun Ganda (Double-Declining)' },
];
const CAT_LABELS = {
  tanah: 'Tanah', bangunan: 'Bangunan', mesin: 'Mesin', kendaraan: 'Kendaraan',
  peralatan: 'Peralatan', it: 'IT', furnitur: 'Furnitur', 'lain-lain': 'Lain-lain'
};
const STATUS_COLORS = {
  active: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300',
  disposed: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',
  fully_depreciated: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
};

export default function FixedAssetsModule({ token }) {
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
  const [view, setView] = useState('list'); // list | detail | schedule
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
  const [postingPeriod, setPostingPeriod] = useState('');

  const BLANK_FORM = {
    code: '', name: '', category: 'peralatan', purchase_date: '', purchase_cost: '',
    residual_value: '', useful_life_months: '60', depreciation_method: 'straight_line',
    account_id_asset: '', account_id_accum_depr: '', account_id_depr_expense: '',
    location: '', supplier: '', serial_number: '', notes: '',
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
    setForm(v => ({ ...v, category: cat, ...Object.fromEntries(ACC_FIELDS.map(f => [f, def[f]?.id || ''])) }));
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
    const r = await fetch('/api/rahaza/coa/accounts', { headers });
    if (r.ok) setCoa((await r.json()).filter(a => a.active !== false && !a.is_group));
  };

  const openDetail = async (asset) => {
    setSelected(asset);
    setView('detail');
    const r = await fetch(`/api/rahaza/finance/fixed-assets/${asset.id}/schedule`, { headers });
    if (r.ok) setSchedule(await r.json());
  };

  const createAsset = async () => {
    // K18 — validasi sama dengan server: jenis perolehan wajib, harga > 0, umur > 0, tanggal ≤ hari ini (WIB)
    if (!form.acquisition_type) { toast.error('Pilih jenis perolehan: Pembelian baru atau Aset lama (saldo awal)'); return; }
    if (!(parseFloat(form.purchase_cost) > 0)) { toast.error('Harga perolehan harus lebih dari 0'); return; }
    if (!(parseInt(form.useful_life_months, 10) > 0)) { toast.error('Masa manfaat (bulan) harus lebih dari 0'); return; }
    if (form.purchase_date && form.purchase_date > maxDate) { toast.error(`Tanggal pembelian melewati hari ini (${maxDate})`); return; }
    if (form.acquisition_type === 'purchase' && !form.funding_source) { toast.error('Pilih sumber dana pembelian'); return; }
    if (form.acquisition_type === 'opening' && !form.golive_date) { toast.error('Isi tanggal go-live untuk aset lama'); return; }
    // SESI #27 — `code` DIBUANG dari payload saat mode OTOMATIS: mengirimnya akan
    // ditolak backend ("nomor tidak boleh diketik manual").
    const { code: _formCode, ...rest } = form;
    const r = await fetch('/api/rahaza/finance/fixed-assets', {
      method: 'POST', headers,
      body: JSON.stringify({
        ...rest,
        ...docNumberPayload(numPolicy, 'code', form.code),
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
      toast.success(`Depresiasi ${period} diposting: Rp ${Number(res.depr_amount || 0).toLocaleString('id-ID')}`);
      fetchDeprDue(); fetchSummary();
      if (selected) {
        const sr = await fetch(`/api/rahaza/finance/fixed-assets/${selected.id}/schedule`, { headers });
        if (sr.ok) setSchedule(await sr.json());
      }
    } else { const e = await r.json(); toast.error(e.detail || 'Gagal posting'); }
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
      toast.success(`Aset di-dispose. Gain/Loss: Rp ${Number(res.gain_loss || 0).toLocaleString('id-ID')}`);
      setDisposeOpen(false);
      const updated = await fetch(`/api/rahaza/finance/fixed-assets/${selected.id}`, { headers });
      if (updated.ok) setSelected(await updated.json());
      fetchAssets(page); fetchSummary();
    } else { const e = await r.json(); toast.error(e.detail || 'Gagal'); }
  };

  const fmtRp = formatRupiah;
  const curPeriod = thisMonthWIB();

  // ── DETAIL VIEW
  if (view === 'detail' && selected) {
    const pctDepr = selected.purchase_cost > 0
      ? Math.min(100, Math.round((selected.accumulated_depreciation / selected.purchase_cost) * 100))
      : 0;
    return (
      <div className="space-y-5" data-testid="fixed-asset-detail-page">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="sm" onClick={() => setView('list')}>&larr; Daftar Aset</Button>
            <div>
              <h2 className="text-lg font-semibold">{selected.name}</h2>
              <span className="text-xs text-muted-foreground">{selected.code} · {CAT_LABELS[selected.category] || selected.category}
                {selected.acquisition_type === 'opening' && ` · Aset lama (go-live ${selected.golive_date}, akumulasi awal ${fmtRp(selected.opening_accumulated_depr)})`}
                {selected.acquisition_type === 'purchase' && ` · Pembelian baru${selected.gl_je_number ? ` · jurnal ${selected.gl_je_number}` : ''}`}
              </span>
            </div>
          </div>
          {selected.status === 'active' && (
            <div className="flex gap-2">
              {/* 2026-11-02 (registri aset tunggal): label aset dari registri induk — generator sama dgn Portal Aset */}
              <Button size="sm" variant="outline" data-testid="fa-print-label" onClick={async () => {
                try {
                  const r = await fetch(`/api/rahaza/finance/fixed-assets/${selected.id}/label-pdf`, { headers: { Authorization: headers.Authorization } });
                  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || `HTTP ${r.status}`); }
                  const url = URL.createObjectURL(await r.blob());
                  window.open(url, '_blank');
                  setTimeout(() => URL.revokeObjectURL(url), 60000);
                } catch (e) { toast.error(e.message); }
              }}>
                <Printer className="w-3.5 h-3.5 mr-1" /> Label
              </Button>
              <Button size="sm" variant="outline" onClick={() => { setDisposeOpen(true); setDisposeForm({ disposal_date: todayWIB(), disposal_value: '', notes: '' }); }}>
                <Trash2 className="w-3.5 h-3.5 mr-1" /> Dispose
              </Button>
            </div>
          )}
        </div>

        {/* Stats */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {[
            { label: 'Harga Perolehan', value: fmtRp(selected.purchase_cost) },
            { label: 'Akum. Depresiasi', value: fmtRp(selected.accumulated_depreciation), color: 'text-amber-700 dark:text-amber-500' },
            { label: 'Nilai Buku (NBV)', value: fmtRp(selected.book_value_current), color: 'text-emerald-500' },
            { label: '% Depresiasi', value: `${pctDepr}%`, color: pctDepr > 80 ? 'text-red-700 dark:text-red-400' : 'text-blue-600 dark:text-blue-400' },
          ].map(c => (
            <GlassCard key={c.label} className="p-4">
              <div className="text-xs text-muted-foreground mb-1">{c.label}</div>
              <div className={`text-sm font-semibold ${c.color || 'text-foreground'}`}>{c.value}</div>
            </GlassCard>
          ))}
        </div>

        {/* Depreciation progress bar */}
        <GlassCard className="p-4">
          <div className="flex items-center justify-between text-xs text-muted-foreground mb-2">
            <span>Progress Depresiasi</span><span>{pctDepr}%</span>
          </div>
          <div className="h-2 bg-secondary rounded-full overflow-hidden">
            <div className="h-full bg-amber-400 rounded-full transition-all" style={{ width: `${pctDepr}%` }} />
          </div>
        </GlassCard>

        {/* Depreciation Schedule Table */}
        <GlassCard className="overflow-x-auto">
          <div className="px-4 py-3 border-b border-border flex items-center justify-between">
            <h3 className="font-medium text-sm">Jadwal Depresiasi</h3>
            <span className="text-xs text-muted-foreground">{schedule.length} periode</span>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-[var(--glass-bg)] text-xs uppercase text-muted-foreground">
              <tr>{['Periode','Nilai Buku Awal','Depresiasi','Akumulasi','Nilai Buku Akhir','Status','Aksi'].map(h => (
                <th key={h} className="px-3 py-2.5 text-left whitespace-nowrap">{h}</th>
              ))}</tr>
            </thead>
            <tbody className="divide-y divide-border">
              {schedule.map(s => (
                <tr key={s.id} className={`hover:bg-[var(--glass-bg)] ${s.cancelled ? 'opacity-40' : ''}`}>
                  <td className="px-3 py-2 font-medium">{s.period}</td>
                  <td className="px-3 py-2 text-right">{fmtRp(s.book_value_start)}</td>
                  <td className="px-3 py-2 text-right text-amber-700 dark:text-amber-500">{fmtRp(s.depr_amount)}</td>
                  <td className="px-3 py-2 text-right">{fmtRp(s.accumulated_depr)}</td>
                  <td className="px-3 py-2 text-right text-emerald-500">{fmtRp(s.book_value_end)}</td>
                  <td className="px-3 py-2">
                    {s.cancelled ? (
                      <span className="text-xs text-muted-foreground">Dibatalkan</span>
                    ) : s.posted ? (
                      <span className="px-1.5 py-0.5 rounded-full text-xs bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300">Posted</span>
                    ) : (
                      <span className="px-1.5 py-0.5 rounded-full text-xs bg-secondary text-muted-foreground">Pending</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {!s.posted && !s.cancelled && s.period <= curPeriod && (
                      <Button size="sm" variant="outline" className="text-xs h-7 px-2" onClick={() => postDepr(selected.id, s.period)}>
                        Posting
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </GlassCard>

        {/* Dispose Modal */}
        {disposeOpen && (
          <Modal title="Disposal Aset" onClose={() => setDisposeOpen(false)} size="sm">
            <div className="space-y-3">
              <div><label className="block text-xs text-muted-foreground mb-1">Tanggal Disposal *</label>
                <GlassInput type="date" value={disposeForm.disposal_date} onChange={e => setDisposeForm(f => ({...f, disposal_date: e.target.value}))} />
              </div>
              <div><label className="block text-xs text-muted-foreground mb-1">Nilai Jual (Rp)</label>
                <MoneyInput glass placeholder="0" value={disposeForm.disposal_value} onChange={e => setDisposeForm(f => ({...f, disposal_value: e.target.value}))} />
              </div>
              <div><label className="block text-xs text-muted-foreground mb-1">Keterangan</label>
                <GlassInput placeholder="Alasan disposal" value={disposeForm.notes} onChange={e => setDisposeForm(f => ({...f, notes: e.target.value}))} />
              </div>
              <div className="flex gap-2 pt-1">
                <Button onClick={disposeAsset} className="flex-1 bg-red-600 hover:bg-red-700 text-foreground">Dispose</Button>
                <Button variant="outline" onClick={() => setDisposeOpen(false)} className="flex-1">Batal</Button>
              </div>
            </div>
          </Modal>
        )}
      </div>
    );
  }

  // ── LIST VIEW
  return (
    <div className="space-y-5" data-testid="fixed-assets-list-page">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-lg font-semibold">Aset Tetap</h2>
          <p className="text-xs text-muted-foreground">Daftarkan aset, kelola depresiasi, dan posting jurnal</p>
        </div>
        <Button onClick={openCreate} data-testid="btn-new-asset">
          <Plus className="w-4 h-4" /> Aset baru
        </Button>
      </div>

      {/* Summary KPIs — PANDUAN_UI G5 (2026-11-04): StatTile netral, tidak tampil bila belum ada aset */}
      {summary && Number(summary.total_assets) > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatTile label="Jumlah aset" value={`${summary.total_assets} aset`} />
          <StatTile label="Harga perolehan" value={fmtRp(summary.total_cost)} />
          <StatTile label="Nilai buku" value={fmtRp(summary.total_nbv)} />
          <StatTile label="Penyusutan bulan ini" value={summary.depr_due_this_month ? `${summary.depr_due_this_month} aset jatuh tempo` : 'Tidak ada'} accent={summary.depr_due_this_month > 0 ? 'warning' : 'muted'} />
        </div>
      )}

      {/* Depreciation Due Alert */}
      {deprDue.length > 0 && (
        <GlassCard className="p-3 border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/10">
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle className="w-4 h-4 text-amber-700 dark:text-amber-500" />
            <span className="text-sm font-medium text-amber-700 dark:text-amber-400">{deprDue.length} aset perlu posting depresiasi bulan ini</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {deprDue.slice(0, 5).map(d => (
              <Button key={d.id} size="sm" variant="outline" className="h-7 text-xs border-amber-300"
                onClick={() => postDepr(d.asset_id, d.period)}>
                Post {d.asset_name} ({d.period})
              </Button>
            ))}
            {deprDue.length > 5 && <span className="text-xs text-muted-foreground self-center">+{deprDue.length - 5} lainnya</span>}
          </div>
        </GlassCard>
      )}

      {/* Filters */}
      <GlassCard className="p-3">
        <div className="flex flex-wrap gap-3">
          <select value={filterCat} onChange={e => setFilterCat(e.target.value)}
            className="border border-border rounded px-2 py-1 text-sm bg-[var(--card-surface)]">
            <option value="">Semua Kategori</option>
            {CATEGORIES.map(c => <option key={c} value={c}>{CAT_LABELS[c]}</option>)}
          </select>
          <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)}
            className="border border-border rounded px-2 py-1 text-sm bg-[var(--card-surface)]">
            <option value="active">Aktif</option>
            <option value="disposed">Disposed</option>
            <option value="">Semua</option>
          </select>
          <Button size="sm" variant="ghost" onClick={() => { fetchAssets(1); fetchSummary(); fetchDeprDue(); }} disabled={loading}>
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </Button>
        </div>
      </GlassCard>

      {/* Assets Table */}
      <GlassCard className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-[var(--glass-bg)] text-xs uppercase text-muted-foreground">
            <tr>{['Kode','Nama','Kategori','Tgl Beli','Harga Perolehan','NBV','Metode','Status','Aksi'].map(h => (
              <th key={h} className="px-3 py-3 text-left whitespace-nowrap">{h}</th>
            ))}</tr>
          </thead>
          <tbody className="divide-y divide-border">
            {loading && <tr><td colSpan={9} className="text-center py-8"><RefreshCw className="w-5 h-5 animate-spin mx-auto text-muted-foreground" /></td></tr>}
            {!loading && assets.length === 0 && <tr><td colSpan={9} className="text-center py-8 text-muted-foreground">Belum ada aset tetap terdaftar.</td></tr>}
            {!loading && assets.map(a => (
              <tr key={a.id} className="hover:bg-[var(--glass-bg)]">
                <td className="px-3 py-2.5 font-mono text-xs">{a.code}</td>
                <td className="px-3 py-2.5 font-medium">{a.name}</td>
                <td className="px-3 py-2.5">{CAT_LABELS[a.category] || a.category}</td>
                <td className="px-3 py-2.5 text-muted-foreground">{a.purchase_date}</td>
                <td className="px-3 py-2.5">{fmtRp(a.purchase_cost)}</td>
                <td className="px-3 py-2.5 text-emerald-600 dark:text-emerald-400 font-medium">{fmtRp(a.book_value_current)}</td>
                <td className="px-3 py-2.5 text-xs">{a.depreciation_method === 'straight_line' ? 'Garis Lurus' : 'Saldo Menurun'}</td>
                <td className="px-3 py-2.5">
                  <span className={`px-2 py-0.5 rounded-full text-xs ${STATUS_COLORS[a.status] || 'bg-secondary text-muted-foreground'}`}>
                    {a.status === 'active' ? 'Aktif' : a.status === 'disposed' ? 'Disposed' : a.status}
                  </span>
                </td>
                <td className="px-3 py-2.5">
                  <button onClick={() => openDetail(a)} className="p-1 rounded hover:bg-primary/10" title="Detail & Jadwal">
                    <Eye className="w-3.5 h-3.5 text-primary" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {pagination && pagination.total_pages > 1 && (
          <div className="px-4 py-3 border-t border-border">
            <PaginationBar pagination={pagination} onPageChange={setPage} />
          </div>
        )}
      </GlassCard>

      {/* Create Asset Modal */}
      {modalOpen && (
        <Modal title="Daftarkan Aset Tetap Baru" onClose={() => setModalOpen(false)} size="lg">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {/* K18 (2026-11-02) — jenis perolehan WAJIB dipilih */}
            <div className="sm:col-span-2" data-testid="asset-acq-type">
              <label className="block text-xs text-muted-foreground mb-1">Jenis Perolehan *</label>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {ACQ_TYPES.map(t => (
                  <button key={t.value} type="button" onClick={() => setForm(v => ({ ...v, acquisition_type: t.value }))}
                    data-testid={`asset-acq-${t.value}`}
                    className={`text-left rounded border px-3 py-2 text-sm ${form.acquisition_type === t.value ? 'border-primary bg-primary/10' : 'border-border'}`}>
                    <div className="font-medium">{t.label}</div>
                    <div className="text-[11px] text-muted-foreground">{t.hint}</div>
                  </button>
                ))}
              </div>
            </div>
            {form.acquisition_type === 'purchase' && (
              <>
                <div className="sm:col-span-2"><label className="block text-xs text-muted-foreground mb-1">Sumber Dana *</label>
                  <select value={form.funding_source} data-testid="asset-funding"
                    onChange={e => { const v = e.target.value; setForm(f => ({ ...f, funding_source: v })); if (v === 'ap_invoice') loadApInvoices(); }}
                    className="w-full border border-border rounded px-2.5 py-1.5 text-sm bg-[var(--card-surface)]">
                    <option value="">— Pilih sumber dana —</option>
                    {FUNDING.map(f => <option key={f.value} value={f.value}>{f.label}</option>)}
                  </select>
                </div>
                {form.funding_source === 'cash' && (
                  <div className="sm:col-span-2"><label className="block text-xs text-muted-foreground mb-1">Rekening Kas/Bank *</label>
                    <CashAccountSelect accounts={cashAccounts} loaded={cashLoaded} value={form.cash_account_id}
                      onChange={v => setForm(f => ({ ...f, cash_account_id: v }))} testId="asset-cash-account" />
                  </div>
                )}
                {form.funding_source === 'ap_invoice' && (
                  <div className="sm:col-span-2"><label className="block text-xs text-muted-foreground mb-1">Faktur Pemasok *</label>
                    <select value={form.ap_invoice_id} onChange={e => setForm(f => ({ ...f, ap_invoice_id: e.target.value }))}
                      data-testid="asset-ap-invoice" className="w-full border border-border rounded px-2.5 py-1.5 text-sm bg-[var(--card-surface)]">
                      <option value="">— Pilih faktur pemasok —</option>
                      {apInvoices.map(i => <option key={i.id} value={i.id}>{i.invoice_number} · {i.vendor_name} · DPP {fmtRp(i.subtotal || i.total)}</option>)}
                    </select>
                    <p className="text-[11px] text-muted-foreground mt-1">Hutang sudah dicatat faktur; jurnal perolehan mereklas akun debit faktur ke akun aset (hutang tidak dobel).</p>
                  </div>
                )}
              </>
            )}
            {form.acquisition_type === 'opening' && (
              <>
                <div><label className="block text-xs text-muted-foreground mb-1">Tanggal Go-Live *</label>
                  <GlassInput type="date" max={maxDate} value={form.golive_date} onChange={e => setForm(v => ({ ...v, golive_date: e.target.value }))} data-testid="asset-golive" />
                </div>
                <div><label className="block text-xs text-muted-foreground mb-1">Akumulasi Penyusutan per Go-Live (Rp)</label>
                  <MoneyInput glass placeholder="0" value={form.opening_accumulated_depr} onChange={e => setForm(v => ({ ...v, opening_accumulated_depr: e.target.value }))} data-testid="asset-opening-accum" />
                  <p className="text-[11px] text-muted-foreground mt-1">Sama dengan angka akumulasi di jurnal Saldo Awal (belum termasuk bulan go-live).</p>
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
                testId="asset-docnum" label="Kode Aset" />
            </div>
            {[{l:'Nama Aset *', k:'name', ph:'mis. Mesin Jahit Singer'}].map(f => (
              <div key={f.k}><label className="block text-xs text-muted-foreground mb-1">{f.l}</label>
                <GlassInput placeholder={f.ph} value={form[f.k]} onChange={e => setForm(v => ({...v, [f.k]: e.target.value}))} data-testid={`asset-${f.k}`} />
              </div>
            ))}
            <div><label className="block text-xs text-muted-foreground mb-1">Kategori *</label>
              <select value={form.category} onChange={e => applyCategoryDefaults(e.target.value)}
                className="w-full border border-border rounded px-2.5 py-1.5 text-sm bg-[var(--card-surface)]">
                {CATEGORIES.map(c => <option key={c} value={c}>{CAT_LABELS[c]}</option>)}
              </select>
            </div>
            <div><label className="block text-xs text-muted-foreground mb-1">Tanggal Pembelian *</label>
              <GlassInput type="date" max={maxDate} value={form.purchase_date} onChange={e => setForm(v => ({...v, purchase_date: e.target.value}))} data-testid="asset-purchase-date" />
            </div>
            <div><label className="block text-xs text-muted-foreground mb-1">Harga Perolehan (Rp) *</label>
              <MoneyInput glass placeholder="0" value={form.purchase_cost} onChange={e => setForm(v => ({...v, purchase_cost: e.target.value}))} data-testid="asset-cost" />
            </div>
            <div><label className="block text-xs text-muted-foreground mb-1">Nilai Sisa (Rp)</label>
              <MoneyInput glass placeholder="0" value={form.residual_value} onChange={e => setForm(v => ({...v, residual_value: e.target.value}))} />
            </div>
            <div><label className="block text-xs text-muted-foreground mb-1">Masa Manfaat (bulan) *</label>
              <GlassInput type="number" placeholder="60" value={form.useful_life_months} onChange={e => setForm(v => ({...v, useful_life_months: e.target.value}))} />
            </div>
            <div><label className="block text-xs text-muted-foreground mb-1">Metode Depresiasi *</label>
              <select value={form.depreciation_method} onChange={e => setForm(v => ({...v, depreciation_method: e.target.value}))}
                className="w-full border border-border rounded px-2.5 py-1.5 text-sm bg-[var(--card-surface)]">
                {DEPR_METHODS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
            </div>
            <div className="sm:col-span-2 text-[11px] text-muted-foreground">Akun di bawah terisi otomatis dari kategori; jurnal perolehan, penyusutan, dan pelepasan memakai akun ini.</div>
            <div><label className="block text-xs text-muted-foreground mb-1">Akun Aset (COA)</label>
              <SmartNativeSelect value={form.account_id_asset} onChange={e => setForm(v => ({...v, account_id_asset: e.target.value}))}
                className="w-full border border-border rounded px-2.5 py-1.5 text-sm bg-[var(--card-surface)]">
                <option value="">-- Pilih (opsional) --</option>
                {coa.map(a => <option key={a.id} value={a.id}>{a.code} — {a.name}</option>)}
              </SmartNativeSelect>
            </div>
            <div><label className="block text-xs text-muted-foreground mb-1">Akun Akumulasi Depresiasi</label>
              <SmartNativeSelect value={form.account_id_accum_depr} onChange={e => setForm(v => ({...v, account_id_accum_depr: e.target.value}))}
                className="w-full border border-border rounded px-2.5 py-1.5 text-sm bg-[var(--card-surface)]">
                <option value="">-- Pilih (opsional) --</option>
                {coa.map(a => <option key={a.id} value={a.id}>{a.code} — {a.name}</option>)}
              </SmartNativeSelect>
            </div>
            <div><label className="block text-xs text-muted-foreground mb-1">Akun Beban Depresiasi</label>
              <SmartNativeSelect value={form.account_id_depr_expense} onChange={e => setForm(v => ({...v, account_id_depr_expense: e.target.value}))}
                className="w-full border border-border rounded px-2.5 py-1.5 text-sm bg-[var(--card-surface)]">
                <option value="">-- Pilih (opsional) --</option>
                {coa.map(a => <option key={a.id} value={a.id}>{a.code} — {a.name}</option>)}
              </SmartNativeSelect>
            </div>
            {[{l:'Lokasi', k:'location'},{l:'Supplier', k:'supplier'},{l:'No. Seri', k:'serial_number'}].map(f => (
              <div key={f.k}><label className="block text-xs text-muted-foreground mb-1">{f.l}</label>
                <GlassInput value={form[f.k]} onChange={e => setForm(v => ({...v, [f.k]: e.target.value}))} />
              </div>
            ))}
            <div className="sm:col-span-2 flex gap-2 pt-2">
              <Button onClick={createAsset} className="flex-1" data-testid="btn-submit-asset">Daftarkan Aset</Button>
              <Button variant="outline" onClick={() => setModalOpen(false)} className="flex-1">Batal</Button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

import { Fragment, useState, useEffect, useCallback, useRef } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { StatusBadge, EmptyState } from './moduleAtoms';
import PageLayout, { DetailPanel } from './layout/PageLayout';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import {
  Plus, Trash2, CheckCircle, Lock, Unlock, Upload,
  BarChart2, RefreshCw, FileText, Eye, ListTree
} from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import Modal from './Modal';
import PaginationLite from '@/components/ui/pagination-lite';
import { toast } from 'sonner';
import { formatRupiah, formatPercent } from '@/lib/format';
import { MoneyInput } from '@/components/ui/money-input';
import { thisYearWIB } from '@/lib/waktu';

const STATUS_MAP = {
  draft:    { label: 'Draf',      tone: 'muted' },
  approved: { label: 'Disetujui', tone: 'info' },
  locked:   { label: 'Terkunci',  tone: 'success' },
};
const PERIOD_TYPE_LABEL = { monthly: 'Bulanan', quarterly: 'Kuartalan', annual: 'Tahunan' };

// 2026-11-02: status variance dari backend — pendapatan (above/below_target) vs biaya (under/over)
const BUDGET_STATUS_LABEL = {
  over: 'Melebihi anggaran', under: 'Di bawah anggaran', on_target: 'Sesuai anggaran',
  above_target: 'Di atas target', below_target: 'Di bawah target',
};
const varianceTone = (s) => ((s === 'over' || s === 'below_target') ? 'danger' : (s === 'under' || s === 'above_target') ? 'success' : 'muted');
const signClass = (n) => (Number(n) < 0 ? 'text-[hsl(var(--destructive))]' : Number(n) > 0 ? 'text-[hsl(var(--success))]' : 'text-muted-foreground');

const MONTHS = [
  '01','02','03','04','05','06','07','08','09','10','11','12'
];
const BULAN = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'];
const periodLabel = (code) => { const [y, m] = String(code || '').split('-'); return BULAN[Number(m) - 1] ? `${BULAN[Number(m) - 1]} ${y}` : (code || '—'); };
const fmtRp = formatRupiah;

/**
 * Anggaran (menu Akuntansi › Anggaran).
 * 2026-11-05 (PANDUAN_UI G1/G13): cetakan PageLayout. Rincian satu anggaran dan "Anggaran vs realisasi" dibuka
 * DI HALAMAN di atas daftar (dulu layar daftar diganti layar rincian, lalu layar ketiga untuk realisasi).
 */
export default function BudgetModule({ token }) {
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
  const [panelView, setPanelView] = useState('items'); // 'items' | 'variance'
  const [budgets, setBudgets] = useState([]);
  const [selected, setSelected] = useState(null);
  const [items, setItems] = useState([]);
  const [variance, setVariance] = useState(null);
  const [loading, setLoading] = useState(false);
  const [varLoading, setVarLoading] = useState(false);
  const [pagination, setPagination] = useState(null);
  const [page, setPage] = useState(1);
  const [filterYear, setFilterYear] = useState(thisYearWIB());
  const [filterStatus, setFilterStatus] = useState('');
  const importRef = useRef(null);

  // Modals
  const [modalBudget, setModalBudget] = useState(false);
  const [modalItem, setModalItem] = useState(false);
  const [costCenters, setCostCenters] = useState([]);
  const [coa, setCoa] = useState([]);

  // Forms
  const [budgetForm, setBudgetForm] = useState({ name: '', year: thisYearWIB(), period_type: 'monthly', cost_center_id: '', department: '', notes: '' });
  const [itemForm, setItemForm] = useState({ account_id: '', month: '', amount_budgeted: '', notes: '' });

  const thisYear = Number(thisYearWIB());
  const yearOptions = [];
  for (let y = Math.min(2023, thisYear - 3); y <= thisYear + 1; y++) yearOptions.push(y);

  const fetchBudgets = useCallback(async (p = 1) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: p, limit: 20, year: filterYear });
      if (filterStatus) params.set('status', filterStatus);
      const r = await fetch(`/api/rahaza/finance/budgets?${params}`, { headers });
      const data = await r.json();
      if (data.items && data.pagination) {
        setBudgets(data.items); setPagination(data.pagination);
      } else {
        setBudgets(Array.isArray(data) ? data : []);
        setPagination(null);
      }
    } finally { setLoading(false); }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, filterYear, filterStatus]);

  useEffect(() => { setPage(1); fetchBudgets(1); }, [filterYear, filterStatus]); // eslint-disable-line
  useEffect(() => { fetchBudgets(page); }, [page]); // eslint-disable-line

  const fetchMeta = async () => {
    const [ccRes, coaRes] = await Promise.all([
      fetch('/api/rahaza/cost-centers', { headers }),
      fetch('/api/rahaza/coa/accounts?active_only=false', { headers }),
    ]);
    if (ccRes.ok) setCostCenters(await ccRes.json());
    if (coaRes.ok) setCoa(await coaRes.json());
  };

  const fetchItems = async (bid) => {
    const r = await fetch(`/api/rahaza/finance/budgets/${bid}/items`, { headers });
    if (r.ok) setItems(await r.json());
  };

  const openDetail = async (budget) => {
    setSelected(budget);
    setPanelView('items');
    setVariance(null);
    setItems([]);
    await fetchItems(budget.id);
    await fetchMeta();
  };
  const closeDetail = () => { setSelected(null); setVariance(null); setPanelView('items'); };
  const toggleDetail = (b) => (selected?.id === b.id ? closeDetail() : openDetail(b));

  const fetchVariance = async (bid) => {
    setVarLoading(true);
    const r = await fetch(`/api/rahaza/finance/budgets/${bid}/variance`, { headers });
    if (r.ok) {
      setVariance(await r.json());
      setPanelView('variance');
    }
    setVarLoading(false);
  };

  const createBudget = async () => {
    const r = await fetch('/api/rahaza/finance/budgets', {
      method: 'POST', headers, body: JSON.stringify(budgetForm),
    });
    if (r.ok) {
      toast.success('Anggaran dibuat');
      setModalBudget(false);
      fetchBudgets(1);
      setBudgetForm({ name: '', year: thisYearWIB(), period_type: 'monthly', cost_center_id: '', department: '', notes: '' });
    } else {
      const e = await r.json();
      toast.error(e.detail || 'Gagal membuat anggaran');
    }
  };

  const deleteBudget = async (bid) => {
    if (!(await confirmDialog({ title: 'Hapus anggaran ini?', confirmLabel: 'Hapus', danger: true }))) return;
    const r = await fetch(`/api/rahaza/finance/budgets/${bid}`, { method: 'DELETE', headers });
    if (r.ok) { toast.success('Anggaran dihapus'); if (selected?.id === bid) closeDetail(); fetchBudgets(page); }
    else { const e = await r.json(); toast.error(e.detail || 'Gagal menghapus'); }
  };

  const changeStatus = async (bid, action) => {
    const r = await fetch(`/api/rahaza/finance/budgets/${bid}/${action}`, { method: 'POST', headers });
    if (r.ok) {
      toast.success(({ approve: 'Anggaran disetujui', lock: 'Anggaran dikunci', unlock: 'Kunci anggaran dibuka' })[action] || 'Status anggaran diperbarui');
      const updated = await fetch(`/api/rahaza/finance/budgets/${bid}`, { headers });
      if (updated.ok) setSelected(await updated.json());
      fetchBudgets(page);
    } else {
      const e = await r.json(); toast.error(e.detail || 'Gagal');
    }
  };

  const addItem = async () => {
    if (!selected) return;
    const r = await fetch(`/api/rahaza/finance/budgets/${selected.id}/items`, {
      method: 'POST', headers,
      body: JSON.stringify({
        ...itemForm,
        amount_budgeted: parseFloat(itemForm.amount_budgeted) || 0,
      }),
    });
    if (r.ok) {
      toast.success('Item anggaran ditambahkan');
      setModalItem(false);
      setItemForm({ account_id: '', month: '', amount_budgeted: '', notes: '' });
      await fetchItems(selected.id);
      const upd = await fetch(`/api/rahaza/finance/budgets/${selected.id}`, { headers });
      if (upd.ok) setSelected(await upd.json());
    } else {
      const e = await r.json(); toast.error(e.detail || 'Gagal');
    }
  };

  const deleteItem = async (iid) => {
    if (!selected) return;
    const r = await fetch(`/api/rahaza/finance/budgets/${selected.id}/items/${iid}`, { method: 'DELETE', headers });
    if (r.ok) { toast.success('Item dihapus'); await fetchItems(selected.id); }
    else { const e = await r.json(); toast.error(e.detail || 'Gagal'); }
  };

  const handleImport = async (e) => {
    const file = e.target.files[0];
    if (!file || !selected) return;
    const fd = new FormData();
    fd.append('file', file);
    const r = await fetch(`/api/rahaza/finance/budgets/${selected.id}/import-excel`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: fd,
    });
    if (r.ok) {
      const res = await r.json();
      toast.success(`Impor berhasil: ${res.imported} item, ${res.skipped?.length || 0} dilewati`);
      await fetchItems(selected.id);
    } else { const err = await r.json(); toast.error(err.detail || 'Gagal mengimpor'); }
    e.target.value = '';
  };

  // ── Group items by month for the detail view
  const itemsByMonth = items.reduce((acc, it) => {
    const m = it.month || '?';
    if (!acc[m]) acc[m] = [];
    acc[m].push(it);
    return acc;
  }, {});

  // ── RINCIAN SATU ANGGARAN (di halaman, di atas daftar)
  let detail = null;
  if (selected) {
    const st = STATUS_MAP[selected.status] || STATUS_MAP.draft;
    const editable = selected.status !== 'locked';
    const showVar = panelView === 'variance' && variance;
    detail = (
      <DetailPanel
        testId="budget-detail-page"
        title={showVar ? `Anggaran vs realisasi — ${selected.name}` : selected.name}
        description={<>
          <StatusBadge tone={st.tone} label={st.label} className="mr-2 align-middle" />
          Tahun {selected.year} · {PERIOD_TYPE_LABEL[selected.period_type] || selected.period_type} · departemen {selected.department || '—'} · total anggaran <b className="text-foreground tabular-nums">{fmtRp(selected.total_budgeted)}</b>
        </>}
        onClose={closeDetail}
        actions={showVar ? (
          <Button variant="outline" onClick={() => setPanelView('items')} data-testid="budget-back-items"><ListTree className="w-4 h-4" />Rincian anggaran</Button>
        ) : (
          <>
            {selected.status === 'draft' && <Button variant="outline" onClick={() => changeStatus(selected.id, 'approve')}><CheckCircle className="w-4 h-4" />Setujui</Button>}
            {selected.status === 'approved' && <Button variant="outline" onClick={() => changeStatus(selected.id, 'lock')}><Lock className="w-4 h-4" />Kunci</Button>}
            {(selected.status === 'approved' || selected.status === 'locked') && <Button variant="outline" onClick={() => changeStatus(selected.id, 'reopen')}><Unlock className="w-4 h-4" />Buka lagi</Button>}
            {editable && <Button variant="outline" onClick={() => importRef.current?.click()}><Upload className="w-4 h-4" />Impor Excel</Button>}
            {editable && <Button variant="outline" onClick={() => setModalItem(true)}><Plus className="w-4 h-4" />Tambah item</Button>}
            <Button variant="outline" onClick={() => fetchVariance(selected.id)} disabled={varLoading}><BarChart2 className="w-4 h-4" />Anggaran vs realisasi</Button>
          </>
        )}
      >
        <input ref={importRef} type="file" accept=".xlsx,.xls" className="hidden" id="import-budget" onChange={handleImport} />
        {showVar ? (
          <VarianceView variance={variance} />
        ) : items.length === 0 ? (
          <EmptyState icon={FileText} title="Belum ada item anggaran" description="Tambah item satu per satu atau impor dari Excel." />
        ) : (
          <div className="overflow-x-auto -mx-4">
            <table className="w-full" data-testid="budget-items-table">
              <thead>
                <tr><th className="text-left">Akun</th><th className="text-right">Anggaran</th><th className="text-left">Catatan</th><th className="w-10" /></tr>
              </thead>
              <tbody>
                {Object.keys(itemsByMonth).sort().map(month => (
                  <Fragment key={month}>
                    <tr className="bg-foreground/[0.03]">
                      <td className="font-semibold whitespace-nowrap">{periodLabel(month)}</td>
                      <td className="text-right tabular-nums font-semibold">{fmtRp(itemsByMonth[month].reduce((s, i) => s + Number(i.amount_budgeted || 0), 0))}</td>
                      <td colSpan={2} />
                    </tr>
                    {itemsByMonth[month].map(it => (
                      <tr key={it.id}>
                        <td className="pl-6">{it.account_code} <span className="text-muted-foreground">{it.account_name}</span></td>
                        <td className="text-right tabular-nums">{fmtRp(it.amount_budgeted)}</td>
                        <td className="text-muted-foreground">{it.notes || '—'}</td>
                        <td className="text-right">
                          {editable && (
                            <Button variant="ghost" size="icon-sm" onClick={() => deleteItem(it.id)} title="Hapus item" aria-label="Hapus item" className="text-[hsl(var(--destructive))]">
                              <Trash2 className="w-4 h-4" />
                            </Button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </DetailPanel>
    );
  }

  // ── DAFTAR ANGGARAN
  return (
    <PageLayout
      testId="budget-list-page"
      title="Anggaran"
      subtitle="Anggaran per tahun, departemen, dan pusat biaya, dibandingkan dengan realisasinya."
      actions={
        <Button onClick={() => { setModalBudget(true); fetchMeta(); }} data-testid="btn-new-budget">
          <Plus className="w-4 h-4" /> Anggaran baru
        </Button>
      }
      filters={<>
        <SmartNativeSelect value={String(filterYear)} onChange={e => setFilterYear(+e.target.value)} searchable={false}
          className="h-9 w-28" aria-label="Tahun" data-testid="budget-filter-year">
          {yearOptions.map(y => <option key={y} value={String(y)}>{y}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={filterStatus} onChange={e => setFilterStatus(e.target.value)} searchable={false}
          className="h-9 w-40" aria-label="Status" data-testid="budget-filter-status">
          <option value="">Semua status</option>
          <option value="draft">Draf</option>
          <option value="approved">Disetujui</option>
          <option value="locked">Terkunci</option>
        </SmartNativeSelect>
      </>}
      tools={
        <Button size="icon" variant="outline" onClick={() => fetchBudgets(1)} disabled={loading} title="Muat ulang" aria-label="Muat ulang" data-testid="budget-refresh">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      }
      detail={detail}
      footer={pagination && pagination.total_pages > 1 && (
        <PaginationLite page={pagination.page || page} totalPages={pagination.total_pages} total={pagination.total}
          pageSize={pagination.limit || 20} onPageChange={setPage} />
      )}
    >
      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <Skeleton className="h-40 m-4" />
        ) : budgets.length === 0 ? (
          <EmptyState icon={BarChart2} title={`Belum ada anggaran ${filterYear}`}
            description="Buat anggaran pertama lewat tombol Anggaran baru." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full" data-testid="budget-table">
              <thead>
                <tr>
                  <th className="text-left">Nama anggaran</th>
                  <th className="text-left">Tahun</th>
                  <th className="text-left">Tipe</th>
                  <th className="text-left">Departemen</th>
                  <th className="text-right">Total anggaran</th>
                  <th className="text-left">Status</th>
                  <th className="text-right">Aksi</th>
                </tr>
              </thead>
              <tbody>
                {budgets.map(b => {
                  const st = STATUS_MAP[b.status] || STATUS_MAP.draft;
                  const open = selected?.id === b.id;
                  return (
                    <tr key={b.id} className={open ? 'bg-[hsl(var(--primary)/0.06)]' : ''}>
                      <td className="font-medium">
                        <Button variant="link" size="sm" className="h-auto p-0 text-foreground" onClick={() => toggleDetail(b)}>{b.name}</Button>
                      </td>
                      <td className="whitespace-nowrap">{b.year}</td>
                      <td>{PERIOD_TYPE_LABEL[b.period_type] || b.period_type}</td>
                      <td className="text-muted-foreground">{b.department || '—'}</td>
                      <td className="text-right tabular-nums font-medium">{fmtRp(b.total_budgeted)}</td>
                      <td><StatusBadge tone={st.tone} label={st.label} /></td>
                      <td className="text-right">
                        <div className="flex gap-1 justify-end">
                          <Button variant="ghost" size="icon-sm" onClick={() => toggleDetail(b)} title={open ? 'Tutup rincian' : 'Rincian'} aria-label={open ? 'Tutup rincian' : 'Rincian'}><Eye className="w-4 h-4" /></Button>
                          {b.status === 'draft' && (
                            <Button variant="ghost" size="icon-sm" onClick={() => deleteBudget(b.id)} title="Hapus" aria-label="Hapus" className="text-[hsl(var(--destructive))]"><Trash2 className="w-4 h-4" /></Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>

      {/* Tambah item — dialog isian pendek */}
      {modalItem && selected && (
        <Modal title="Tambah item anggaran" onClose={() => setModalItem(false)} size="sm">
          <div className="space-y-3">
            <div>
              <label className="block text-xs text-muted-foreground mb-1">Akun *</label>
              <SmartNativeSelect value={itemForm.account_id} onChange={e => setItemForm(f => ({...f, account_id: e.target.value}))} className="h-9 w-full">
                <option value="">Pilih akun</option>
                {coa.map(a => <option key={a.id} value={a.id}>{a.code} — {a.name}</option>)}
              </SmartNativeSelect>
            </div>
            <div>
              <label className="block text-xs text-muted-foreground mb-1">Bulan *</label>
              <SmartNativeSelect value={itemForm.month} onChange={e => setItemForm(f => ({...f, month: e.target.value}))} className="h-9 w-full">
                <option value="">Pilih bulan</option>
                {/* 2026-11-02 (audit No.53): nilai bulan dulu memakai tahun form "Budget baru" (tahun berjalan) → item tersimpan ke tahun yang salah */}
                {MONTHS.map(m => <option key={m} value={`${selected.year}-${m}`}>{periodLabel(`${selected.year}-${m}`)}</option>)}
              </SmartNativeSelect>
            </div>
            <div>
              <label className="block text-xs text-muted-foreground mb-1">Jumlah anggaran (Rp) *</label>
              <MoneyInput glass placeholder="0" value={itemForm.amount_budgeted} onChange={e => setItemForm(f => ({...f, amount_budgeted: e.target.value}))} />
            </div>
            <div>
              <label className="block text-xs text-muted-foreground mb-1">Catatan</label>
              <GlassInput placeholder="Opsional" value={itemForm.notes} onChange={e => setItemForm(f => ({...f, notes: e.target.value}))} />
            </div>
            <div className="flex gap-2 pt-1 justify-end">
              <Button variant="outline" onClick={() => setModalItem(false)}>Batal</Button>
              <Button onClick={addItem}>Simpan</Button>
            </div>
          </div>
        </Modal>
      )}

      {/* Anggaran baru — dialog isian pendek */}
      {modalBudget && (
        <Modal title="Anggaran baru" onClose={() => setModalBudget(false)} size="sm">
          <div className="space-y-3">
            <div>
              <label className="block text-xs text-muted-foreground mb-1">Nama anggaran *</label>
              <GlassInput placeholder="mis. Anggaran Operasional 2026" value={budgetForm.name} onChange={e => setBudgetForm(f => ({...f, name: e.target.value}))} data-testid="budget-name" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Tahun *</label>
                <GlassInput type="number" value={budgetForm.year} onChange={e => setBudgetForm(f => ({...f, year: +e.target.value}))} />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Tipe periode</label>
                <SmartNativeSelect value={budgetForm.period_type} onChange={e => setBudgetForm(f => ({...f, period_type: e.target.value}))} searchable={false} className="h-9 w-full">
                  <option value="monthly">Bulanan</option>
                  <option value="quarterly">Kuartalan</option>
                  <option value="annual">Tahunan</option>
                </SmartNativeSelect>
              </div>
            </div>
            <div>
              <label className="block text-xs text-muted-foreground mb-1">Departemen</label>
              <GlassInput placeholder="mis. Produksi, Keuangan" value={budgetForm.department} onChange={e => setBudgetForm(f => ({...f, department: e.target.value}))} />
            </div>
            <div>
              <label className="block text-xs text-muted-foreground mb-1">Pusat biaya</label>
              <SmartNativeSelect value={budgetForm.cost_center_id} onChange={e => setBudgetForm(f => ({...f, cost_center_id: e.target.value}))} className="h-9 w-full">
                <option value="">Pilih (opsional)</option>
                {costCenters.map(c => <option key={c.id} value={c.id}>{c.code} — {c.name}</option>)}
              </SmartNativeSelect>
            </div>
            <div>
              <label className="block text-xs text-muted-foreground mb-1">Catatan</label>
              <GlassInput placeholder="Opsional" value={budgetForm.notes} onChange={e => setBudgetForm(f => ({...f, notes: e.target.value}))} />
            </div>
            <div className="flex gap-2 pt-1 justify-end">
              <Button variant="outline" onClick={() => setModalBudget(false)}>Batal</Button>
              <Button onClick={createBudget} data-testid="btn-submit-budget">Simpan anggaran</Button>
            </div>
          </div>
        </Modal>
      )}
    </PageLayout>
  );
}

/** Anggaran vs realisasi — isi panel rincian (dulu layar terpisah). */
function VarianceView({ variance }) {
  const { rows: vrows = [], summary = {} } = variance || {};
  return (
    <div className="space-y-3" data-testid="budget-variance-page">
      <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
        {[
          { label: 'Total anggaran', value: fmtRp(summary.total_budgeted) },
          { label: 'Total realisasi', value: fmtRp(summary.total_actual) },
          { label: 'Selisih', value: fmtRp(summary.total_variance), cls: signClass(summary.total_variance) },
          { label: '% selisih', value: formatPercent(summary.total_variance_pct, 1) },
        ].map(c => (
          <div key={c.label}>
            <dt className="text-xs text-muted-foreground">{c.label}</dt>
            <dd className={`font-semibold tabular-nums ${c.cls || 'text-foreground'}`}>{c.value}</dd>
          </div>
        ))}
      </dl>
      {vrows.length === 0 ? (
        <EmptyState icon={BarChart2} title="Belum ada realisasi untuk dibandingkan" description="Realisasi muncul setelah ada jurnal pada akun yang dianggarkan." />
      ) : (
        <div className="overflow-x-auto -mx-4">
          <table className="w-full" data-testid="budget-variance-table">
            <thead>
              <tr>
                <th className="text-left">Bulan</th><th className="text-left">Akun</th><th className="text-right">Anggaran</th>
                <th className="text-right">Realisasi</th><th className="text-right">Selisih</th><th className="text-right">%</th><th className="text-left">Status</th>
              </tr>
            </thead>
            <tbody>
              {vrows.map((r, i) => (
                <tr key={i}>
                  <td className="whitespace-nowrap">{periodLabel(r.month)}</td>
                  <td>{r.account_code} <span className="text-muted-foreground">{r.account_name}</span></td>
                  <td className="text-right tabular-nums">{fmtRp(r.amount_budgeted)}</td>
                  <td className="text-right tabular-nums">{fmtRp(r.amount_actual)}</td>
                  <td className={`text-right tabular-nums font-medium ${signClass(r.variance)}`}>{fmtRp(r.variance)}</td>
                  <td className={`text-right tabular-nums ${signClass(r.variance)}`}>{formatPercent(r.variance_pct, 1)}</td>
                  {/* 2026-11-02 (audit No.53): baris pendapatan memakai label target (di atas = baik) */}
                  <td><StatusBadge tone={varianceTone(r.status)} label={BUDGET_STATUS_LABEL[r.status] || 'Sesuai anggaran'} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

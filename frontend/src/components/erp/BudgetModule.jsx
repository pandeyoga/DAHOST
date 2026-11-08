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
import FormPopup, { Isian } from '@/components/ui/form-popup';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table';
import PaginationLite from '@/components/ui/pagination-lite';
import { toast } from 'sonner';
import { formatRupiah, formatPercent } from '@/lib/format';
import { MoneyInput } from '@/components/ui/money-input';
import { thisYearWIB } from '@/lib/waktu';
import { DepartmentSelect } from './hr/hrPickers';
import { cvAccountParam, useCv } from '@/lib/entitas';

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
const signClass = (n) => (Number(n) < 0 ? 'text-[hsl(var(--danger-text))]' : Number(n) > 0 ? 'text-[hsl(var(--success-text))]' : 'text-muted-foreground');

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
 * 2026-11-08 (Standar UI/UX v2): rincian = popup (tabel ui/table + unduh Excel/CSV untuk rincian & realisasi);
 * form anggaran baru & tambah item = FormPopup pendek; daftar anggaran bisa diunduh (semua halaman); Setujui hijau.
 */
export default function BudgetModule({ token }) {
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
  const coaCv = cvAccountParam(useCv()?.cv);  // Tahap 8: akun CV terpilih saja
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
      fetch(`/api/rahaza/coa/accounts?active_only=false${coaCv ? `&${coaCv}` : ''}`, { headers }),
    ]);
    if (ccRes.ok) setCostCenters(await ccRes.json());
    // 2026-11-07 (audit form Tahap 5): item anggaran hanya ke akun AKTIF dan BUKAN grup — realisasi dibaca dari
    // baris jurnal (akun rinci), jadi anggaran di akun grup/nonaktif selalu "realisasi 0". Dulu daftar memuat
    // seluruh bagan akun (termasuk grup & nonaktif).
    if (coaRes.ok) setCoa((await coaRes.json()).filter(a => a.active !== false && !a.is_group));
  };
  // Pusat biaya & akun dimuat saat layar dibuka — dulu hanya saat rincian anggaran dibuka, sehingga pilihan
  // "Pusat biaya" di form "Anggaran baru" kosong.
  useEffect(() => { fetchMeta(); }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

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
          <>
            <Button variant="outline" onClick={() => setPanelView('items')} data-testid="budget-back-items"><ListTree className="w-4 h-4" />Rincian anggaran</Button>
            <TombolUnduh namaBerkas={`anggaran-vs-realisasi-${selected.name}`} namaLembar="Anggaran vs realisasi" baris={variance?.rows || []} testId="budget-variance-unduh"
              kolom={[
                { label: 'Bulan', nilai: (r) => periodLabel(r.month) },
                { label: 'Kode akun', nilai: (r) => r.account_code },
                { label: 'Akun', nilai: (r) => r.account_name || '' },
                { label: 'Anggaran', nilai: (r) => Number(r.amount_budgeted) || 0 },
                { label: 'Realisasi', nilai: (r) => Number(r.amount_actual) || 0 },
                { label: 'Selisih', nilai: (r) => Number(r.variance) || 0 },
                { label: '% selisih', nilai: (r) => Number(r.variance_pct) || 0 },
                { label: 'Status', nilai: (r) => BUDGET_STATUS_LABEL[r.status] || 'Sesuai anggaran' },
              ]} />
          </>
        ) : (
          <>
            {selected.status === 'draft' && <Button variant="success" onClick={() => changeStatus(selected.id, 'approve')}><CheckCircle className="w-4 h-4" />Setujui</Button>}
            {selected.status === 'approved' && <Button variant="outline" onClick={() => changeStatus(selected.id, 'lock')}><Lock className="w-4 h-4" />Kunci</Button>}
            {(selected.status === 'approved' || selected.status === 'locked') && <Button variant="outline" onClick={() => changeStatus(selected.id, 'reopen')}><Unlock className="w-4 h-4" />Buka lagi</Button>}
            {editable && <Button variant="outline" onClick={() => importRef.current?.click()}><Upload className="w-4 h-4" />Impor Excel</Button>}
            {editable && <Button variant="outline" onClick={() => setModalItem(true)}><Plus className="w-4 h-4" />Tambah item</Button>}
            <Button variant="outline" onClick={() => fetchVariance(selected.id)} disabled={varLoading}><BarChart2 className="w-4 h-4" />Anggaran vs realisasi</Button>
            <TombolUnduh namaBerkas={`rincian-anggaran-${selected.name}`} namaLembar="Rincian anggaran" baris={items} testId="budget-items-unduh"
              kolom={[
                { label: 'Bulan', nilai: (it) => periodLabel(it.month) },
                { label: 'Kode akun', nilai: (it) => it.account_code },
                { label: 'Akun', nilai: (it) => it.account_name || '' },
                { label: 'Anggaran', nilai: (it) => Number(it.amount_budgeted) || 0 },
                { label: 'Catatan', nilai: (it) => it.notes || '' },
              ]} />
          </>
        )}
      >
        <input ref={importRef} type="file" accept=".xlsx,.xls" className="hidden" id="import-budget" onChange={handleImport} />
        {showVar ? (
          <VarianceView variance={variance} />
        ) : (
          <Table className="md:min-w-0" data-testid="budget-items-table">
            <TableHeader>
              <TableRow><TableHead>Akun</TableHead><TableHead className="text-right">Anggaran</TableHead><TableHead>Catatan</TableHead><TableHead className="w-10" /></TableRow>
            </TableHeader>
            <TableBody>
              {items.length === 0 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={4} className="p-0 [&>div]:py-8">
                    <EmptyState icon={FileText} title="Belum ada item anggaran" description="Tambah item satu per satu atau impor dari Excel." />
                  </TableCell>
                </TableRow>
              )}
              {Object.keys(itemsByMonth).sort().map(month => (
                <Fragment key={month}>
                  <TableRow className="bg-muted/40">
                    <TableCell className="font-semibold whitespace-nowrap">{periodLabel(month)}</TableCell>
                    <TableCell className="text-right tabular-nums font-semibold whitespace-nowrap">{fmtRp(itemsByMonth[month].reduce((s, i) => s + Number(i.amount_budgeted || 0), 0))}</TableCell>
                    <TableCell colSpan={2} />
                  </TableRow>
                  {itemsByMonth[month].map(it => (
                    <TableRow key={it.id}>
                      <TableCell className="pl-6">{it.account_code} <span className="text-muted-foreground">{it.account_name}</span></TableCell>
                      <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtRp(it.amount_budgeted)}</TableCell>
                      <TableCell className="text-muted-foreground">{it.notes || '—'}</TableCell>
                      <TableCell className="text-right">
                        {editable && (
                          <Button variant="ghost" size="icon-sm" onClick={() => deleteItem(it.id)} title="Hapus item" aria-label="Hapus item" className="text-[hsl(var(--danger-text))]">
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </Fragment>
              ))}
            </TableBody>
          </Table>
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
          className="h-9 w-32" aria-label="Tahun" data-testid="budget-filter-year">
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
      tools={<>
        <TombolUnduh namaBerkas={`anggaran-${filterYear}`} namaLembar={`Anggaran ${filterYear}`} baris={budgets} testId="budget-unduh"
          ambilSemua={async () => {
            const out = [];
            for (let p = 1; p <= 50; p += 1) {
              const params = new URLSearchParams({ page: p, limit: 200, year: filterYear });
              if (filterStatus) params.set('status', filterStatus);
              const r = await fetch(`/api/rahaza/finance/budgets?${params}`, { headers });
              if (!r.ok) throw new Error('gagal');
              const d = await r.json();
              const list = d.items || (Array.isArray(d) ? d : []);
              out.push(...list);
              if (!d.pagination || !d.pagination.has_next || !list.length) break;
            }
            return out;
          }}
          kolom={[
            { label: 'Nama anggaran', nilai: (b) => b.name },
            { label: 'Tahun', nilai: (b) => b.year },
            { label: 'Tipe', nilai: (b) => PERIOD_TYPE_LABEL[b.period_type] || b.period_type },
            { label: 'Departemen', nilai: (b) => b.department || '' },
            { label: 'Total anggaran', nilai: (b) => Number(b.total_budgeted) || 0 },
            { label: 'Status', nilai: (b) => (STATUS_MAP[b.status] || STATUS_MAP.draft).label },
          ]} />
        <Button size="icon" variant="outline" onClick={() => fetchBudgets(1)} disabled={loading} title="Muat ulang" aria-label="Muat ulang" data-testid="budget-refresh">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
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
        ) : (
          <div className="overflow-x-auto">
            <Table className="w-full md:min-w-0" data-testid="budget-table">
              <TableHeader>
                <TableRow>
                  <TableHead className="text-left">Nama anggaran</TableHead>
                  <TableHead className="text-left">Tahun</TableHead>
                  <TableHead className="text-left">Tipe</TableHead>
                  <TableHead className="text-left">Departemen</TableHead>
                  <TableHead className="text-right">Total anggaran</TableHead>
                  <TableHead className="text-left">Status</TableHead>
                  <TableHead className="text-right">Aksi</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {budgets.length === 0 && (
                  <TableRow className="hover:bg-transparent">
                    <TableCell colSpan={7} className="p-0 [&>div]:py-8">
                      <EmptyState icon={BarChart2} title={`Belum ada anggaran ${filterYear}`}
                        description="Buat anggaran pertama lewat tombol Anggaran baru." />
                    </TableCell>
                  </TableRow>
                )}
                {budgets.map(b => {
                  const st = STATUS_MAP[b.status] || STATUS_MAP.draft;
                  const open = selected?.id === b.id;
                  return (
                    <TableRow key={b.id} className={open ? 'bg-[hsl(var(--primary)/0.06)]' : ''}>
                      <TableCell className="font-medium">
                        <Button variant="link" size="sm" className="h-auto p-0 text-foreground" onClick={() => toggleDetail(b)}>{b.name}</Button>
                      </TableCell>
                      <TableCell className="whitespace-nowrap">{b.year}</TableCell>
                      <TableCell>{PERIOD_TYPE_LABEL[b.period_type] || b.period_type}</TableCell>
                      <TableCell className="text-muted-foreground">{b.department || '—'}</TableCell>
                      <TableCell className="text-right tabular-nums font-medium">{fmtRp(b.total_budgeted)}</TableCell>
                      <TableCell><StatusBadge tone={st.tone} label={st.label} /></TableCell>
                      <TableCell className="text-right">
                        <div className="flex gap-1 justify-end">
                          <Button variant="ghost" size="icon-sm" onClick={() => toggleDetail(b)} title={open ? 'Tutup rincian' : 'Rincian'} aria-label={open ? 'Tutup rincian' : 'Rincian'}><Eye className="w-4 h-4" /></Button>
                          {b.status === 'draft' && (
                            <Button variant="ghost" size="icon-sm" onClick={() => deleteBudget(b.id)} title="Hapus" aria-label="Hapus" className="text-[hsl(var(--danger-text))]"><Trash2 className="w-4 h-4" /></Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </GlassCard>

      {/* Tambah item — popup form standar (pendek) */}
      {modalItem && selected && (
        <FormPopup open onClose={() => setModalItem(false)} ukuran="pendek" testId="budget-item-form"
          judul="Tambah item anggaran" keterangan={selected.name}
          onSimpan={addItem} bisaSimpan={!!itemForm.account_id && !!itemForm.month}>
          <Isian label="Akun" wajib>
            <SmartNativeSelect value={itemForm.account_id} onChange={e => setItemForm(f => ({...f, account_id: e.target.value}))} className="h-9 w-full"
              searchPlaceholder="Cari kode atau nama akun…" data-testid="budget-item-account">
              <option value="">Pilih akun</option>
              {coa.map(a => <option key={a.id} value={a.id}>{`${a.code} · ${a.name}`}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Bulan" wajib>
            <SmartNativeSelect value={itemForm.month} onChange={e => setItemForm(f => ({...f, month: e.target.value}))} className="h-9 w-full" data-testid="budget-item-month">
              <option value="">Pilih bulan</option>
              {/* 2026-11-02 (audit No.53): nilai bulan dulu memakai tahun form "Budget baru" (tahun berjalan) → item tersimpan ke tahun yang salah */}
              {MONTHS.map(m => <option key={m} value={`${selected.year}-${m}`}>{periodLabel(`${selected.year}-${m}`)}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Jumlah anggaran (Rp)" wajib>
            <MoneyInput glass placeholder="0" value={itemForm.amount_budgeted} onChange={e => setItemForm(f => ({...f, amount_budgeted: e.target.value}))} />
          </Isian>
          <Isian label="Catatan">
            <GlassInput placeholder="Opsional" value={itemForm.notes} onChange={e => setItemForm(f => ({...f, notes: e.target.value}))} />
          </Isian>
        </FormPopup>
      )}

      {/* Anggaran baru — popup form standar (pendek) */}
      {modalBudget && (
        <FormPopup open onClose={() => setModalBudget(false)} ukuran="pendek" testId="budget-form"
          judul="Anggaran baru" onSimpan={createBudget} bisaSimpan={!!budgetForm.name.trim()} labelSimpan="Simpan anggaran">
          <Isian label="Nama anggaran" wajib>
            <GlassInput placeholder="mis. Anggaran Operasional 2026" value={budgetForm.name} onChange={e => setBudgetForm(f => ({...f, name: e.target.value}))} data-testid="budget-name" />
          </Isian>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Isian label="Tahun" wajib>
              <GlassInput type="number" value={budgetForm.year} onChange={e => setBudgetForm(f => ({...f, year: +e.target.value}))} />
            </Isian>
            <Isian label="Tipe periode">
              <SmartNativeSelect value={budgetForm.period_type} onChange={e => setBudgetForm(f => ({...f, period_type: e.target.value}))} searchable={false} className="h-9 w-full">
                <option value="monthly">Bulanan</option>
                <option value="quarterly">Kuartalan</option>
                <option value="annual">Tahunan</option>
              </SmartNativeSelect>
            </Isian>
          </div>
          <Isian label="Departemen">
            {/* 2026-11-07 (OR1): departemen dari Struktur Organisasi (satu daftar untuk semua formulir) */}
            <DepartmentSelect token={token} value={budgetForm.department} className="h-9 w-full" testId="budget-department"
              placeholder="— Tanpa departemen —" onChange={v => setBudgetForm(f => ({ ...f, department: v }))} />
          </Isian>
          <Isian label="Pusat biaya">
            <SmartNativeSelect value={budgetForm.cost_center_id} onChange={e => setBudgetForm(f => ({...f, cost_center_id: e.target.value}))} className="h-9 w-full" data-testid="budget-cost-center">
              <option value="">Pilih (opsional)</option>
              {costCenters.map(c => <option key={c.id} value={c.id}>{c.code} — {c.name}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Catatan">
            <GlassInput placeholder="Opsional" value={budgetForm.notes} onChange={e => setBudgetForm(f => ({...f, notes: e.target.value}))} />
          </Isian>
        </FormPopup>
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
      <Table className="md:min-w-0" data-testid="budget-variance-table">
        <TableHeader>
          <TableRow>
            <TableHead>Bulan</TableHead><TableHead>Akun</TableHead><TableHead className="text-right">Anggaran</TableHead>
            <TableHead className="text-right">Realisasi</TableHead><TableHead className="text-right">Selisih</TableHead><TableHead className="text-right">%</TableHead><TableHead>Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {vrows.length === 0 && (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={7} className="p-0 [&>div]:py-8">
                <EmptyState icon={BarChart2} title="Belum ada realisasi untuk dibandingkan" description="Realisasi muncul setelah ada jurnal pada akun yang dianggarkan." />
              </TableCell>
            </TableRow>
          )}
          {vrows.map((r, i) => (
            <TableRow key={i}>
              <TableCell className="whitespace-nowrap">{periodLabel(r.month)}</TableCell>
              <TableCell>{r.account_code} <span className="text-muted-foreground">{r.account_name}</span></TableCell>
              <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtRp(r.amount_budgeted)}</TableCell>
              <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtRp(r.amount_actual)}</TableCell>
              <TableCell className={`text-right tabular-nums whitespace-nowrap font-medium ${signClass(r.variance)}`}>{fmtRp(r.variance)}</TableCell>
              <TableCell className={`text-right tabular-nums ${signClass(r.variance)}`}>{formatPercent(r.variance_pct, 1)}</TableCell>
              {/* 2026-11-02 (audit No.53): baris pendapatan memakai label target (di atas = baik) */}
              <TableCell><StatusBadge tone={varianceTone(r.status)} label={BUDGET_STATUS_LABEL[r.status] || 'Sesuai anggaran'} /></TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

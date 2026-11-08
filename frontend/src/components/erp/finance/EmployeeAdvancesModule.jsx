/**
 * Uang Muka Karyawan — tab di menu Keuangan › Kasbon & Uang Muka.
 *
 * 2026-11-04 (keputusan owner, audit Keuangan): Kas Kecil disatukan ke Rekening & Mutasi; uang muka
 * karyawan (dulu di layar dana Kas Kecil) pindah ke sini dan dibayar dari REKENING mana saja.
 * Backend tetap satu pintu: `/api/finance/petty-cash/advances` (jurnal Dr 1-1610 Uang Muka Karyawan /
 * Cr rekening; pertanggungjawaban: Dr beban per nota + Dr rekening untuk sisa uang / Cr 1-1610).
 * Beda dengan Kasbon: kasbon = gaji dimuka (lunas lewat potong gaji); uang muka = uang operasional
 * yang dipertanggungjawabkan dengan nota.
 * 2026-11-08 (Standar UI/UX v2): form uang muka & pertanggungjawaban = FormPopup + DatePicker; daftar bisa diunduh
 * Excel/CSV; ukuran huruf standar; paginasi di kaki halaman.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import FilterChips from '@/components/ui/filter-chips';
import { Plus, RefreshCw, Loader2, Search, HandCoins } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { GlassCard } from '@/components/ui/glass';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { toast } from 'sonner';
import { MoneyInput } from '@/components/ui/money-input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatRupiah, formatDateID } from '@/lib/format';
import CashAccountSelect, { usePaymentCashAccounts } from '../SdmCashAccountSelect';
import { todayWIB } from '../../../lib/waktu';
import { EmptyState, StatusBadge } from '../moduleAtoms';
import PageLayout from '../layout/PageLayout';

const API = process.env.REACT_APP_BACKEND_URL || '';
const BASE = `${API}/api/finance/petty-cash`;
const fmt = formatRupiah;
const tok = () => localStorage.getItem('erp_token');
const authH = () => ({ Authorization: `Bearer ${tok()}`, 'Content-Type': 'application/json' });
const STATUS = { open: 'Terbuka', partial: 'Sebagian', settled: 'Selesai' };
const STATUS_TONE = { open: 'default', partial: 'info', settled: 'success' };

/* karyawan + kategori nota + pemetaan kategori→akun + akun beban (sama dengan form kas kecil lama) */
function useAdvanceRefs(open) {
  const [refs, setRefs] = useState({ employees: [], categories: [], mapped: {}, expenseAccounts: [] });
  useEffect(() => {
    if (!open) return undefined;
    let off = false;
    const get = (url) => fetch(url, { headers: authH() }).then(r => (r.ok ? r.json() : null)).catch(() => null);
    Promise.all([
      get(`${API}/api/rahaza/employees?active_only=true&limit=1000`),
      get(`${API}/api/hr/expenses/master-categories`),
      get(`${API}/api/hr/expenses/gl-mappings?is_active=true`),
      get(`${API}/api/rahaza/coa/accounts?active_only=true&type=EXPENSE&entity=DA`),  // Tahap 8: uang muka staf DA
    ]).then(([emps, cats, maps, accs]) => {
      if (off) return;
      const list = (x) => (Array.isArray(x) ? x : (x?.items || x?.employees || []));
      setRefs({
        employees: list(emps).filter(e => e.active !== false),
        categories: list(cats),
        mapped: Object.fromEntries(list(maps).map(m => [m.category, m.gl_account_code])),
        expenseAccounts: list(accs).filter(a => !a.is_group),
      });
    });
    return () => { off = true; };
  }, [open]);
  return refs;
}

function ExpenseAccountPicker({ category, value, onChange, refs, testId }) {
  const mappedCode = category ? refs.mapped[category] : null;
  if (mappedCode) return <p className="text-xs text-muted-foreground">Akun beban dari pemetaan kategori: <strong>{mappedCode}</strong></p>;
  return (
    <Isian label="Akun beban" wajib petunjuk="Kategori ini belum dipetakan ke akun beban.">
      <SmartNativeSelect value={value || ''} onChange={e => onChange(e.target.value)} data-testid={testId} className="w-full h-9">
        <option value="">— Pilih akun beban —</option>
        {refs.expenseAccounts.map(a => <option key={a.code} value={a.code}>{a.code} — {a.name}</option>)}
      </SmartNativeSelect>
    </Isian>
  );
}

function NewAdvanceDialog({ open, onClose, onDone }) {
  const refs = useAdvanceRefs(open);
  const { accounts, loaded } = usePaymentCashAccounts(undefined, 'DA');  // Tahap 8: uang muka staf DA
  const [f, setF] = useState({});
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  useEffect(() => {
    if (open) { setF({ employee_id: '', cash_account_id: '', amount: '', txn_date: todayWIB(), settle_days: '', memo: '' }); setErr(''); }
  }, [open]);
  const set = (k, v) => setF(x => ({ ...x, [k]: v }));
  const save = async () => {
    if (!f.employee_id) return setErr('Pilih karyawan penerima.');
    if (!f.cash_account_id) return setErr('Pilih rekening asal uang.');
    if (!(Number(f.amount) > 0)) return setErr('Jumlah harus lebih dari 0.');
    setSaving(true); setErr('');
    try {
      const r = await fetch(`${BASE}/advances`, {
        method: 'POST', headers: authH(),
        body: JSON.stringify({ ...f, amount: Number(f.amount), settle_days: Number(f.settle_days || 0) }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || `Gagal menyimpan (HTTP ${r.status})`);
      toast.success(`Uang muka tercatat · ${d.gl_posting?.je_number || ''}`);
      onDone(); onClose();
    } catch (e) { setErr(e.message); } finally { setSaving(false); }
  };
  return (
    <FormPopup open={open} onClose={onClose} ukuran="pendek" testId="advance-new-dialog"
      judul="Uang muka baru" keterangan="Dicatat sebagai Uang Muka Karyawan; dibebankan saat nota dipertanggungjawabkan."
      onSimpan={save} menyimpan={saving} galat={err}>
      <Isian label="Karyawan" wajib>
        <SmartNativeSelect value={f.employee_id || ''} onChange={e => set('employee_id', e.target.value)} data-testid="advance-employee" className="w-full h-9">
          <option value="">— Pilih karyawan —</option>
          {refs.employees.map(e => <option key={e.id} value={e.id}>{e.employee_code ? `${e.employee_code} · ` : ''}{e.name}</option>)}
        </SmartNativeSelect>
      </Isian>
      <Isian label="Dibayar dari rekening" wajib>
        <CashAccountSelect accounts={accounts} loaded={loaded} value={f.cash_account_id} onChange={v => set('cash_account_id', v)} testId="advance-cash-account" />
      </Isian>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Isian label="Jumlah" wajib>
          <MoneyInput value={f.amount || ''} onChange={e => set('amount', e.target.value)} data-testid="advance-amount" />
        </Isian>
        <Isian label="Tanggal">
          <DatePicker value={f.txn_date || ''} onChange={v => set('txn_date', v)} bolehKosong={false} testId="advance-date" />
        </Isian>
        <Isian label="Batas nota (hari)" htmlFor="advance-settle-days" petunjuk="0 = tanpa batas.">
          <Input id="advance-settle-days" type="number" min="0" placeholder="0" value={f.settle_days || ''} onChange={e => set('settle_days', e.target.value)} />
        </Isian>
        <Isian label="Keperluan" htmlFor="advance-memo">
          <Input id="advance-memo" value={f.memo || ''} onChange={e => set('memo', e.target.value)} placeholder="mis. belanja bahan pembantu" />
        </Isian>
      </div>
    </FormPopup>
  );
}

function SettleDialog({ advance, onClose, onDone }) {
  const open = !!advance;
  const refs = useAdvanceRefs(open);
  const { accounts, loaded } = usePaymentCashAccounts(undefined, 'DA');  // Tahap 8: uang muka staf DA
  const [items, setItems] = useState([]);
  const [returned, setReturned] = useState('');
  const [returnAcc, setReturnAcc] = useState('');
  const [date, setDate] = useState(todayWIB());
  const [memo, setMemo] = useState('');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  useEffect(() => {
    if (open) {
      setItems([{ category: '', account_code: '', amount: '' }]); setReturned('');
      setReturnAcc(advance.cash_account_id || ''); setDate(todayWIB()); setMemo(''); setErr('');
    }
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  const total = items.reduce((s, it) => s + (Number(it.amount) || 0), 0) + (Number(returned) || 0);
  const setItem = (i, patch) => setItems(xs => xs.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  const save = async () => {
    const rows = items.filter(it => Number(it.amount) > 0);
    if (rows.some(it => !(it.category && refs.mapped[it.category]) && !it.account_code)) {
      return setErr('Ada nota dengan kategori yang belum dipetakan — pilih akun bebannya.');
    }
    if (total <= 0) return setErr('Isi minimal satu nota atau sisa uang yang dikembalikan.');
    if (total > (advance.open_amount || 0) + 0.01) return setErr(`Total ${fmt(total)} melebihi sisa uang muka ${fmt(advance.open_amount)}.`);
    if (Number(returned) > 0 && !returnAcc && advance.source === 'rekening') return setErr('Pilih rekening penerima sisa uang.');
    setSaving(true); setErr('');
    try {
      const r = await fetch(`${BASE}/advances/${advance.id}/settle`, {
        method: 'POST', headers: authH(),
        body: JSON.stringify({
          items: rows.map(it => ({ ...it, amount: Number(it.amount) })), returned_amount: Number(returned) || 0,
          settle_date: date, memo, return_cash_account_id: Number(returned) > 0 ? (returnAcc || undefined) : undefined,
        }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || `Gagal menyimpan (HTTP ${r.status})`);
      toast.success(`Pertanggungjawaban tercatat · ${d.gl_posting?.je_number || ''}`);
      onDone(); onClose();
    } catch (e) { setErr(e.message); } finally { setSaving(false); }
  };
  return (
    <FormPopup open={open} onClose={onClose} ukuran="panjang" testId="settle-advance-dialog"
      judul="Pertanggungjawaban uang muka"
      keterangan={`${advance?.employee_name || ''} · uang muka ${fmt(advance?.amount)} · sisa ${fmt(advance?.open_amount)}`}
      onSimpan={save} menyimpan={saving} galat={err}>
      <p className="text-sm font-medium text-foreground">Nota</p>
      {items.map((it, i) => (
        <div key={i} className="rounded-[var(--radius-md)] border border-[var(--glass-border)] p-3 space-y-2">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <SmartNativeSelect value={it.category} onChange={e => setItem(i, { category: e.target.value })}
              className="h-9 w-full" aria-label={`Kategori nota ${i + 1}`} data-testid={`settle-cat-${i}`}>
              <option value="">— Kategori nota —</option>
              {refs.categories.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
            </SmartNativeSelect>
            <MoneyInput placeholder="Nominal nota" value={it.amount} onChange={e => setItem(i, { amount: e.target.value })} aria-label={`Nominal nota ${i + 1}`} data-testid={`settle-amount-${i}`} />
          </div>
          <ExpenseAccountPicker category={it.category} value={it.account_code} refs={refs} testId={`settle-account-${i}`}
            onChange={v => setItem(i, { account_code: v })} />
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" onClick={() => setItems(xs => [...xs, { category: '', account_code: '', amount: '' }])}><Plus className="w-4 h-4" />Tambah nota</Button>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Isian label="Sisa uang dikembalikan">
          <MoneyInput value={returned} onChange={e => setReturned(e.target.value)} data-testid="settle-returned" />
        </Isian>
        <Isian label="Tanggal">
          <DatePicker value={date} onChange={v => setDate(v || todayWIB())} bolehKosong={false} testId="settle-date" />
        </Isian>
      </div>
      {Number(returned) > 0 && (
        <Isian label="Sisa uang masuk ke rekening">
          <CashAccountSelect accounts={accounts} loaded={loaded} value={returnAcc} onChange={setReturnAcc} testId="settle-return-account" />
        </Isian>
      )}
      <Isian label="Keterangan" htmlFor="settle-memo">
        <Input id="settle-memo" placeholder="Opsional" value={memo} onChange={e => setMemo(e.target.value)} />
      </Isian>
      <p className="text-sm text-muted-foreground">Nota + sisa: <strong className="text-foreground tabular-nums">{fmt(total)}</strong> · boleh bertahap, paling banyak {fmt(advance?.open_amount)}</p>
    </FormPopup>
  );
}

export default function EmployeeAdvancesModule() {
  const [status, setStatus] = useState('open');
  const [data, setData] = useState({ items: [], by_employee: [], total_open: 0 });
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [adding, setAdding] = useState(false);
  const [settling, setSettling] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${BASE}/advances?status=${status}`, { headers: authH() });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { toast.error(d.detail || `Gagal memuat uang muka (HTTP ${r.status})`); return; }
      setData(d);
    } finally { setLoading(false); }
  }, [status]);
  useEffect(() => { load(); }, [load]);

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return [...(data.items || [])].reverse()
      .filter(a => !q || `${a.employee_name} ${a.employee_code} ${a.memo}`.toLowerCase().includes(q));
  }, [data.items, search]);
  const pg = useClientPagination(rows, 25);
  const overdue = (data.items || []).filter(a => a.overdue && a.open_amount > 0);

  // 2026-11-05 (PANDUAN_UI G1/G10): cetakan PageLayout — tombol utama di kepala (di hub: baris tab), pil + cari di
  // kiri, muat ulang di kanan; tampilan kosong = EmptyState di kartu tabel (dulu teks polos berjarak besar).
  return (
    <PageLayout
      testId="employee-advances"
      title="Uang muka karyawan"
      subtitle="Uang operasional karyawan yang dipertanggungjawabkan dengan nota."
      actions={<Button onClick={() => setAdding(true)} data-testid="advance-add"><Plus className="w-4 h-4" />Uang muka baru</Button>}
      filters={<>
        <FilterChips value={status} onChange={setStatus} testId="advance-status" ariaLabel="Status uang muka" hideWhenEmpty={false}
          options={[{ key: 'open', label: 'Belum selesai' }, { key: 'all', label: 'Semua' }]} />
        <div className="relative w-full sm:w-64">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input className="pl-9 h-9" placeholder="Cari karyawan / keperluan" aria-label="Cari" value={search} onChange={e => setSearch(e.target.value)} />
        </div>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="uang-muka-karyawan" namaLembar="Uang muka" baris={rows} testId="advance-unduh"
          kolom={[
            { label: 'Tanggal', nilai: (a) => formatDateID(a.txn_date) },
            { label: 'Karyawan', nilai: (a) => a.employee_name },
            { label: 'Kode karyawan', nilai: (a) => a.employee_code || '' },
            { label: 'Keperluan', nilai: (a) => a.memo || '' },
            { label: 'Rekening', nilai: (a) => a.cash_account_name || (a.source === 'kas_kecil' ? 'Kas Kecil (dana lama)' : '') },
            { label: 'Uang muka', nilai: (a) => Number(a.amount) || 0 },
            { label: 'Sisa', nilai: (a) => Number(a.open_amount) || 0 },
            { label: 'Batas nota', nilai: (a) => (a.due_date ? formatDateID(a.due_date) : '') },
            { label: 'Status', nilai: (a) => STATUS[a.advance_status] || a.advance_status },
          ]} />
        <Button size="icon" variant="outline" onClick={load} title="Muat ulang" aria-label="Muat ulang"><RefreshCw className="w-4 h-4" /></Button>
      </>}
      footer={pg.totalPages > 1 && <PaginationLite page={pg.page} totalPages={pg.totalPages} total={pg.total} pageSize={pg.pageSize} onPageChange={pg.setPage} />}
      summary={status === 'open' && data.total_open > 0 && (
        <p className="text-sm text-muted-foreground" data-testid="advance-summary">
          Belum dipertanggungjawabkan: <strong className="text-foreground tabular-nums">{fmt(data.total_open)}</strong> · {data.by_employee.length} karyawan
          {overdue.length > 0 && <span className="text-[hsl(var(--warning-text))]"> · {overdue.length} lewat batas nota</span>}
        </p>
      )}
    >
      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <div className="h-32 flex items-center justify-center"><Loader2 className="w-5 h-5 animate-spin text-muted-foreground" /></div>
        ) : rows.length === 0 ? (
          <EmptyState icon={HandCoins} testId="advance-empty"
            title={search ? 'Tidak ada uang muka yang cocok' : status === 'open' ? 'Semua uang muka sudah dipertanggungjawabkan' : 'Belum ada uang muka'}
            description={search ? 'Ubah atau kosongkan pencarian.' : 'Tekan "Uang muka baru" untuk mencatat uang yang diberikan ke karyawan.'} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="text-left">
                  <th>Tanggal</th><th>Karyawan</th><th>Keperluan</th>
                  <th className="hidden md:table-cell">Rekening</th><th className="text-right">Uang muka</th><th className="text-right">Sisa</th>
                  <th className="hidden md:table-cell">Batas nota</th><th>Status</th><th />
                </tr>
              </thead>
              <tbody>
                {pg.paged.map(a => (
                  <tr key={a.id} className={`border-b border-[var(--glass-border)] ${a.overdue && a.open_amount > 0 ? 'bg-[hsl(var(--warning)/0.08)]' : ''}`}>
                    <td className="whitespace-nowrap">{formatDateID(a.txn_date)}</td>
                    <td>{a.employee_name}{a.employee_code && <span className="text-muted-foreground"> · {a.employee_code}</span>}</td>
                    <td>{a.memo || '—'}</td>
                    <td className="hidden md:table-cell">{a.cash_account_name || (a.source === 'kas_kecil' ? 'Kas Kecil (dana lama)' : '—')}</td>
                    <td className="text-right tabular-nums whitespace-nowrap">{fmt(a.amount)}</td>
                    <td className="text-right tabular-nums whitespace-nowrap font-medium">{fmt(a.open_amount)}</td>
                    <td className="whitespace-nowrap hidden md:table-cell">{a.due_date ? `${formatDateID(a.due_date)}${a.overdue && a.open_amount > 0 ? ' · lewat' : ''}` : '—'}</td>
                    <td><StatusBadge status={a.advance_status} label={STATUS[a.advance_status] || a.advance_status} tone={STATUS_TONE[a.advance_status]} /></td>
                    <td className="text-right whitespace-nowrap">
                      {a.open_amount > 0.009 && (
                        <Button size="sm" variant="outline" onClick={() => setSettling(a)} data-testid={`settle-btn-${a.id}`}>
                          Pertanggungjawaban
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>

      <NewAdvanceDialog open={adding} onClose={() => setAdding(false)} onDone={load} />
      <SettleDialog advance={settling} onClose={() => setSettling(null)} onDone={load} />
    </PageLayout>
  );
}

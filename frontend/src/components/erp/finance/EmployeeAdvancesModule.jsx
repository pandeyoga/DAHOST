/**
 * Uang Muka Karyawan — tab di menu Keuangan › Kasbon & Uang Muka.
 *
 * 2026-11-04 (keputusan owner, audit Keuangan): Kas Kecil disatukan ke Rekening & Mutasi; uang muka
 * karyawan (dulu di layar dana Kas Kecil) pindah ke sini dan dibayar dari REKENING mana saja.
 * Backend tetap satu pintu: `/api/finance/petty-cash/advances` (jurnal Dr 1-1610 Uang Muka Karyawan /
 * Cr rekening; pertanggungjawaban: Dr beban per nota + Dr rekening untuk sisa uang / Cr 1-1610).
 * Beda dengan Kasbon: kasbon = gaji dimuka (lunas lewat potong gaji); uang muka = uang operasional
 * yang dipertanggungjawabkan dengan nota.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Plus, RefreshCw, Loader2, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { GlassCard } from '@/components/ui/glass';
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog';
import { toast } from 'sonner';
import { MoneyInput } from '@/components/ui/money-input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatRupiah, formatDateID } from '@/lib/format';
import CashAccountSelect, { usePaymentCashAccounts } from '../SdmCashAccountSelect';
import { todayWIB } from '../../../lib/waktu';

const API = process.env.REACT_APP_BACKEND_URL || '';
const BASE = `${API}/api/finance/petty-cash`;
const fmt = formatRupiah;
const tok = () => localStorage.getItem('erp_token');
const authH = () => ({ Authorization: `Bearer ${tok()}`, 'Content-Type': 'application/json' });
const STATUS = { open: 'Terbuka', partial: 'Sebagian', settled: 'Selesai' };

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
      get(`${API}/api/rahaza/coa/accounts?active_only=true&type=EXPENSE`),
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
  if (mappedCode) return <p className="text-[11px] text-muted-foreground">Akun beban dari pemetaan kategori: <strong>{mappedCode}</strong></p>;
  return (
    <div className="space-y-1">
      <Label>Akun beban * <span className="text-[10px] text-muted-foreground">(kategori belum dipetakan)</span></Label>
      <SmartNativeSelect value={value || ''} onChange={e => onChange(e.target.value)} data-testid={testId}
        className="w-full h-9 px-2 rounded-md border border-input bg-background text-sm">
        <option value="">— Pilih akun beban —</option>
        {refs.expenseAccounts.map(a => <option key={a.code} value={a.code}>{a.code} — {a.name}</option>)}
      </SmartNativeSelect>
    </div>
  );
}

function NewAdvanceDialog({ open, onClose, onDone }) {
  const refs = useAdvanceRefs(open);
  const { accounts, loaded } = usePaymentCashAccounts();
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
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-md" data-testid="advance-new-dialog">
        <DialogHeader>
          <DialogTitle>Uang muka baru</DialogTitle>
          <DialogDescription>Dicatat sebagai Uang Muka Karyawan; dibebankan saat nota dipertanggungjawabkan.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3 py-1">
          {err && <div className="text-destructive text-sm bg-destructive/10 rounded px-3 py-2">{err}</div>}
          <div className="space-y-1">
            <Label>Karyawan *</Label>
            <SmartNativeSelect value={f.employee_id || ''} onChange={e => set('employee_id', e.target.value)} data-testid="advance-employee"
              className="w-full h-9 px-2 rounded-md border border-input bg-background text-sm">
              <option value="">— Pilih karyawan —</option>
              {refs.employees.map(e => <option key={e.id} value={e.id}>{e.employee_code ? `${e.employee_code} · ` : ''}{e.name}</option>)}
            </SmartNativeSelect>
          </div>
          <div className="space-y-1">
            <Label>Dibayar dari rekening *</Label>
            <CashAccountSelect accounts={accounts} loaded={loaded} value={f.cash_account_id} onChange={v => set('cash_account_id', v)} testId="advance-cash-account" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Jumlah *</Label>
              <MoneyInput value={f.amount || ''} onChange={e => set('amount', e.target.value)} data-testid="advance-amount" />
            </div>
            <div className="space-y-1">
              <Label>Tanggal</Label>
              <Input type="date" value={f.txn_date || ''} onChange={e => set('txn_date', e.target.value)} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Batas nota (hari)</Label>
              <Input type="number" min="0" placeholder="0 = tanpa batas" value={f.settle_days || ''} onChange={e => set('settle_days', e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>Keperluan</Label>
              <Input value={f.memo || ''} onChange={e => set('memo', e.target.value)} placeholder="mis. belanja bahan pembantu" />
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>Batal</Button>
          <Button onClick={save} disabled={saving} data-testid="advance-save">
            {saving && <Loader2 size={13} className="mr-1 animate-spin" />} Simpan
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SettleDialog({ advance, onClose, onDone }) {
  const open = !!advance;
  const refs = useAdvanceRefs(open);
  const { accounts, loaded } = usePaymentCashAccounts();
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
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-lg" data-testid="settle-advance-dialog">
        <DialogHeader>
          <DialogTitle>Pertanggungjawaban uang muka</DialogTitle>
          <DialogDescription>
            {advance?.employee_name} · uang muka {fmt(advance?.amount)} · sisa <strong>{fmt(advance?.open_amount)}</strong>
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 py-1">
          {err && <div className="text-destructive text-sm bg-destructive/10 rounded px-3 py-2">{err}</div>}
          {items.map((it, i) => (
            <div key={i} className="rounded-lg border border-border p-2 space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <SmartNativeSelect value={it.category} onChange={e => setItem(i, { category: e.target.value })}
                  className="h-9 px-2 rounded-md border border-input bg-background text-sm" data-testid={`settle-cat-${i}`}>
                  <option value="">— Kategori nota —</option>
                  {refs.categories.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
                </SmartNativeSelect>
                <MoneyInput placeholder="Nominal nota" value={it.amount} onChange={e => setItem(i, { amount: e.target.value })} data-testid={`settle-amount-${i}`} />
              </div>
              <ExpenseAccountPicker category={it.category} value={it.account_code} refs={refs} testId={`settle-account-${i}`}
                onChange={v => setItem(i, { account_code: v })} />
            </div>
          ))}
          <Button variant="outline" size="sm" onClick={() => setItems(xs => [...xs, { category: '', account_code: '', amount: '' }])}>+ Nota</Button>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Sisa uang dikembalikan</Label>
              <MoneyInput value={returned} onChange={e => setReturned(e.target.value)} data-testid="settle-returned" />
            </div>
            <div className="space-y-1">
              <Label>Tanggal</Label>
              <Input type="date" value={date} onChange={e => setDate(e.target.value)} />
            </div>
          </div>
          {Number(returned) > 0 && (
            <div className="space-y-1">
              <Label>Sisa uang masuk ke rekening</Label>
              <CashAccountSelect accounts={accounts} loaded={loaded} value={returnAcc} onChange={setReturnAcc} testId="settle-return-account" />
            </div>
          )}
          <Input placeholder="Keterangan" value={memo} onChange={e => setMemo(e.target.value)} />
          <p className="text-xs text-muted-foreground">Nota + sisa: <strong>{fmt(total)}</strong> · boleh bertahap, paling banyak {fmt(advance?.open_amount)}</p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>Batal</Button>
          <Button onClick={save} disabled={saving} data-testid="settle-save">
            {saving && <Loader2 size={13} className="mr-1 animate-spin" />} Simpan
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
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

  return (
    <div className="space-y-4" data-testid="employee-advances">
      <div className="flex items-center gap-2 flex-wrap">
        <div className="inline-flex rounded-lg border border-[var(--glass-border)] p-0.5">
          {[['open', 'Belum selesai'], ['all', 'Semua']].map(([k, l]) => (
            <button key={k} type="button" onClick={() => setStatus(k)} data-testid={`advance-status-${k}`}
              className={`px-3 py-1.5 rounded-md text-xs font-medium ${status === k ? 'bg-[var(--nav-pill-active)] text-foreground' : 'text-muted-foreground hover:text-foreground'}`}>{l}</button>
          ))}
        </div>
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input className="pl-9 h-9" placeholder="Cari karyawan / keperluan" value={search} onChange={e => setSearch(e.target.value)} />
        </div>
        <Button variant="ghost" className="h-9 border border-[var(--glass-border)]" onClick={load} title="Muat ulang" aria-label="Muat ulang"><RefreshCw className="w-4 h-4" /></Button>
        <Button className="h-9" onClick={() => setAdding(true)} data-testid="advance-add"><Plus className="w-4 h-4 mr-1" />Uang muka baru</Button>
      </div>

      {status === 'open' && data.total_open > 0 && (
        <p className="text-sm text-muted-foreground" data-testid="advance-summary">
          Belum dipertanggungjawabkan: <strong className="text-foreground">{fmt(data.total_open)}</strong> · {data.by_employee.length} karyawan
          {overdue.length > 0 && <span className="text-amber-600 dark:text-amber-400"> · {overdue.length} lewat batas nota</span>}
        </p>
      )}

      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <div className="p-10 flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-muted-foreground" /></div>
        ) : rows.length === 0 ? (
          <div className="p-10 text-center text-sm text-muted-foreground">
            {status === 'open' ? 'Tidak ada uang muka yang belum dipertanggungjawabkan.' : 'Belum ada uang muka.'}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-[var(--glass-border)]">
                <tr className="text-left text-xs text-muted-foreground">
                  <th className="px-4 py-2">Tanggal</th><th className="py-2">Karyawan</th><th className="py-2">Keperluan</th>
                  <th className="py-2">Rekening</th><th className="py-2 text-right">Uang muka</th><th className="py-2 text-right">Sisa</th>
                  <th className="py-2">Batas nota</th><th className="py-2">Status</th><th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody>
                {pg.paged.map(a => (
                  <tr key={a.id} className={`border-b border-[var(--glass-border)] ${a.overdue && a.open_amount > 0 ? 'bg-amber-50 dark:bg-amber-400/10' : ''}`}>
                    <td className="px-4 py-2 text-xs whitespace-nowrap">{formatDateID(a.txn_date)}</td>
                    <td className="py-2 text-xs">{a.employee_name}{a.employee_code && <span className="text-muted-foreground"> · {a.employee_code}</span>}</td>
                    <td className="py-2 text-xs">{a.memo || '—'}</td>
                    <td className="py-2 text-xs">{a.cash_account_name || (a.source === 'kas_kecil' ? 'Kas Kecil (dana lama)' : '—')}</td>
                    <td className="py-2 text-xs text-right tabular-nums">{fmt(a.amount)}</td>
                    <td className="py-2 text-xs text-right tabular-nums font-medium">{fmt(a.open_amount)}</td>
                    <td className="py-2 text-xs whitespace-nowrap">{a.due_date ? `${formatDateID(a.due_date)}${a.overdue && a.open_amount > 0 ? ' · lewat' : ''}` : '—'}</td>
                    <td className="py-2 text-xs">{STATUS[a.advance_status] || a.advance_status}</td>
                    <td className="px-4 py-2 text-right">
                      {a.open_amount > 0.009 && (
                        <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => setSettling(a)} data-testid={`settle-btn-${a.id}`}>
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
        {pg.totalPages > 1 && <div className="px-4 py-2"><PaginationLite page={pg.page} totalPages={pg.totalPages} total={pg.total} pageSize={pg.pageSize} onPageChange={pg.setPage} /></div>}
      </GlassCard>

      <NewAdvanceDialog open={adding} onClose={() => setAdding(false)} onDone={load} />
      <SettleDialog advance={settling} onClose={() => setSettling(null)} onDone={load} />
    </div>
  );
}

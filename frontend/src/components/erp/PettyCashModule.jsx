/**
 * PettyCashModule — Kas Kecil / Petty Cash
 * CV. Dewi Aditya — Phase 6B
 *
 * Fitur:
 *  - Daftar dana (fund) + saldo real-time
 *  - Buat dana baru + replenish + close
 *  - Input transaksi: expense / advance / return
 *  - History transaksi per fund + GL posting status
 *  - Retry posting jika gagal
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { FINANCE_ROLES } from '../../lib/financeRoles'; // FIN-02
import {
  Wallet, Plus, RefreshCw, ChevronRight, AlertCircle,
  CheckCircle2, XCircle, Loader2, ArrowUpCircle, ArrowDownCircle,
  RotateCcw, Receipt, Banknote, Eye
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { toast } from 'sonner';
import { formatRupiah } from '@/lib/format';
// 2026-11-02: rekening sumber dari master Kas & Bank (bukan daftar hard-code yang memuat
// 'Bank BRI (1-1203)' — tidak ada di bagan akun — dan 'Kas (1-1101)' = kas kecil itu sendiri).
import CashAccountSelect, { usePaymentCashAccounts, todayWIB } from './SdmCashAccountSelect';

const API = process.env.REACT_APP_BACKEND_URL;
const BASE = `${API}/api/finance/petty-cash`;

const fmt = formatRupiah;
const fmtDate = (s) => s ? new Date(s).toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' }) : '-';

function token() { return localStorage.getItem('erp_token'); }
function userRole() {
  try { return JSON.parse(localStorage.getItem('erp_user') || '{}').role; } catch { return null; }
}

// ── Warna berdasarkan tipe transaksi ──────────────────────────────────────────
const TXN_CONFIG = {
  expense:   { label: 'Pengeluaran',     color: 'text-rose-500',    icon: ArrowUpCircle,   sign: '-' },
  advance:   { label: 'Uang Muka',       color: 'text-orange-500',  icon: ArrowUpCircle,   sign: '-' },
  return:    { label: 'Pengembalian',    color: 'text-emerald-500', icon: ArrowDownCircle, sign: '+' },
  replenish: { label: 'Replenishment',   color: 'text-blue-500',    icon: ArrowDownCircle, sign: '+' },
  opening:   { label: 'Saldo Awal',      color: 'text-blue-400',    icon: ArrowDownCircle, sign: '+' },
  advance_settlement: { label: 'Pertanggungjawaban', color: 'text-emerald-600', icon: ArrowDownCircle, sign: '' },
};

/* 2026-11-02 (K26): data acuan form kas kecil — karyawan (uang muka WAJIB atas nama karyawan), kategori
   + pemetaan GL (akun beban dari pemetaan; kategori belum terpetakan → akun WAJIB dipilih, tidak ada lagi
   bawaan 6-2400 ATK), dan daftar akun beban. */
function usePettyRefs(open) {
  const [refs, setRefs] = useState({ employees: [], categories: [], mapped: {}, expenseAccounts: [] });
  useEffect(() => {
    if (!open) return undefined;
    let off = false;
    const h = { headers: { Authorization: `Bearer ${token()}` } };
    const get = (url) => fetch(url, h).then(r => (r.ok ? r.json() : null)).catch(() => null);
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
      <Label>Akun Beban * <span className="text-[10px] text-muted-foreground">(kategori belum dipetakan)</span></Label>
      <select value={value || ''} onChange={e => onChange(e.target.value)} data-testid={testId}
        className="w-full h-9 px-2 rounded-md border border-input bg-background text-sm">
        <option value="">— Pilih akun beban —</option>
        {refs.expenseAccounts.map(a => <option key={a.code} value={a.code}>{a.code} — {a.name}</option>)}
      </select>
    </div>
  );
}

// ── Create Fund Dialog ─────────────────────────────────────────────────────────
function CreateFundDialog({ open, onClose, onCreated, accounts, accountsLoaded }) {
  const [form, setForm] = useState({ name: '', custodian_name: '', opening_balance: '', bank_account_code: '' });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    if (open) { setForm({ name: '', custodian_name: '', opening_balance: '', bank_account_code: '' }); setErr(''); }
  }, [open]);

  const save = async () => {
    if (!form.name.trim()) return setErr('Nama dana wajib diisi.');
    if (!form.bank_account_code) return setErr('Rekening sumber wajib dipilih.');
    setSaving(true); setErr('');
    try {
      const res = await fetch(`${BASE}/funds`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}` },
        body: JSON.stringify({ ...form, opening_balance: parseFloat(form.opening_balance || 0) }),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || 'Gagal membuat dana');
      toast.success(`Dana "${d.name}" berhasil dibuat.`);
      onCreated();
      onClose();
    } catch (e) { setErr(e.message); } finally { setSaving(false); }
  };

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Buat Dana Kas Kecil</DialogTitle>
          <DialogDescription>Dana baru untuk pengeluaran operasional kecil.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3 py-2">
          {err && <div className="text-destructive text-sm bg-destructive/10 rounded px-3 py-2">{err}</div>}
          <div className="space-y-1">
            <Label>Nama Dana *</Label>
            <Input data-testid="fund-name" placeholder="mis. Kas Kecil Operasional" value={form.name} onChange={e => setForm(p => ({ ...p, name: e.target.value }))} />
          </div>
          <div className="space-y-1">
            <Label>Nama Kasir / Pengelola</Label>
            <Input data-testid="fund-custodian" placeholder="mis. Budi Santoso" value={form.custodian_name} onChange={e => setForm(p => ({ ...p, custodian_name: e.target.value }))} />
          </div>
          <div className="space-y-1">
            <Label>Saldo Awal (IDR)</Label>
            <Input data-testid="fund-opening" type="number" min="0" placeholder="0" value={form.opening_balance} onChange={e => setForm(p => ({ ...p, opening_balance: e.target.value }))} />
          </div>
          <div className="space-y-1">
            <Label>Rekening Sumber *</Label>
            <CashAccountSelect
              accounts={accounts} loaded={accountsLoaded} valueKey="gl_account_code"
              value={form.bank_account_code} onChange={v => setForm(p => ({ ...p, bank_account_code: v }))}
              testId="fund-source-account"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>Batal</Button>
          <Button data-testid="fund-save" onClick={save} disabled={saving || !form.bank_account_code}>
            {saving && <Loader2 size={13} className="mr-1 animate-spin" />}
            Buat Dana
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Replenish Dialog ───────────────────────────────────────────────────────────
function ReplenishDialog({ open, fund, onClose, onDone, accounts, accountsLoaded }) {
  const [amount, setAmount] = useState('');
  const [memo, setMemo]   = useState('');
  const [bankCode, setBankCode] = useState('');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => { if (open) { setAmount(''); setMemo(''); setErr(''); } }, [open]);
  useEffect(() => {
    // bawaan = rekening sumber dana ini, bila masih rekening kas/bank aktif
    if (!open) return;
    const own = fund?.bank_account_code;
    setBankCode(accounts.some(a => a.gl_account_code === own) ? own : '');
  }, [open, fund?.bank_account_code, accounts]);

  const save = async () => {
    if (!amount || parseFloat(amount) <= 0) return setErr('Jumlah harus > 0.');
    if (!bankCode) return setErr('Rekening sumber wajib dipilih.');
    setSaving(true); setErr('');
    try {
      const res = await fetch(`${BASE}/funds/${fund.id}/replenish`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}` },
        body: JSON.stringify({ amount: parseFloat(amount), bank_account_code: bankCode, memo }),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || 'Gagal replenish');
      toast.success(`Replenishment ${fmt(d.new_balance)} dicatat + GL dipost.`);
      onDone();
      onClose();
    } catch (e) { setErr(e.message); } finally { setSaving(false); }
  };

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Replenishment Kas Kecil</DialogTitle>
          <DialogDescription>Isi ulang dana <strong>{fund?.name}</strong>.<br/>Saldo saat ini: <strong>{fmt(fund?.current_balance)}</strong></DialogDescription>
        </DialogHeader>
        <div className="space-y-3 py-2">
          {err && <div className="text-destructive text-sm bg-destructive/10 rounded px-3 py-2">{err}</div>}
          <div className="space-y-1">
            <Label>Jumlah Replenishment (IDR) *</Label>
            <Input data-testid="replenish-amount" type="number" min="1" placeholder="500000" value={amount} onChange={e => setAmount(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label>Rekening Sumber *</Label>
            <CashAccountSelect
              accounts={accounts} loaded={accountsLoaded} valueKey="gl_account_code"
              value={bankCode} onChange={setBankCode} testId="replenish-source-account"
            />
          </div>
          <div className="space-y-1">
            <Label>Keterangan</Label>
            <Input placeholder="opsional" value={memo} onChange={e => setMemo(e.target.value)} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>Batal</Button>
          <Button data-testid="replenish-confirm" onClick={save} disabled={saving || !bankCode}>
            {saving && <Loader2 size={13} className="mr-1 animate-spin" />}
            Replenish
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Add Expense Dialog ────────────────────────────────────────────────────────
function AddTxnDialog({ open, fund, onClose, onDone }) {
  const empty = { txn_type: 'expense', amount: '', category: '', payee: '', memo: '', txn_date: '', employee_id: '', account_code: '' };
  const [form, setForm] = useState(empty);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const refs = usePettyRefs(open);
  const categories = refs.categories;

  useEffect(() => {
    if (open) {
      setForm({ ...empty, txn_type: 'expense', txn_date: todayWIB() }); // 2026-11-02: tanggal WIB, bukan UTC
      setErr('');
    }
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    if (!form.amount || parseFloat(form.amount) <= 0) return setErr('Jumlah harus > 0.');
    // 2026-11-02 (K26)
    if (form.txn_type === 'advance' && !form.employee_id) return setErr('Uang muka wajib memilih karyawan penerima.');
    if (form.txn_type === 'expense' && !(form.category && refs.mapped[form.category]) && !form.account_code) {
      return setErr('Kategori belum dipetakan ke akun beban — pilih akun beban.');
    }
    setSaving(true); setErr('');
    try {
      const res = await fetch(`${BASE}/transactions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}` },
        body: JSON.stringify({ ...form, fund_id: fund.id, amount: parseFloat(form.amount) }),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || 'Gagal simpan');
      const glOk = d.gl_posting?.ok;
      toast.success(`Transaksi dicatat. GL: ${glOk ? 'Terposting ✅' : 'Gagal post ⚠️'}`);
      if (!glOk) toast.error(`GL Error: ${d.gl_posting?.error || 'Unknown'}`);
      onDone();
      onClose();
    } catch (e) { setErr(e.message); } finally { setSaving(false); }
  };

  const TXN_TYPES = [
    { value: 'expense', label: 'Pengeluaran (Expense)' },
    { value: 'advance', label: 'Uang Muka Karyawan (Advance)' },
    // 2026-11-02 (K26): sisa uang muka KARYAWAN dikembalikan lewat "Pertanggungjawaban";
    // 'return' hanya untuk uang muka lama (sebelum 2 Nov 2026, tanpa karyawan).
    { value: 'return',  label: 'Pengembalian uang muka LAMA' },
  ];

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Catat Transaksi Kas Kecil</DialogTitle>
          <DialogDescription>Dana: <strong>{fund?.name}</strong> | Saldo: <strong>{fmt(fund?.current_balance)}</strong></DialogDescription>
        </DialogHeader>
        <div className="space-y-3 py-2">
          {err && <div className="text-destructive text-sm bg-destructive/10 rounded px-3 py-2">{err}</div>}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Tipe Transaksi *</Label>
              <Select value={form.txn_type} onValueChange={v => setForm(p => ({ ...p, txn_type: v }))}>
                <SelectTrigger data-testid="txn-type"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {TXN_TYPES.map(t => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label>Tanggal *</Label>
              <Input type="date" value={form.txn_date} onChange={e => setForm(p => ({ ...p, txn_date: e.target.value }))} />
            </div>
          </div>
          <div className="space-y-1">
            <Label>Jumlah (IDR) *</Label>
            <Input data-testid="txn-amount" type="number" min="1" placeholder="150000" value={form.amount} onChange={e => setForm(p => ({ ...p, amount: e.target.value }))} />
          </div>
          {form.txn_type === 'advance' ? (
            <div className="space-y-1">
              <Label>Karyawan Penerima *</Label>
              <select value={form.employee_id} onChange={e => setForm(p => ({ ...p, employee_id: e.target.value }))}
                data-testid="txn-employee" className="w-full h-9 px-2 rounded-md border border-input bg-background text-sm">
                <option value="">— Pilih karyawan —</option>
                {refs.employees.map(e => <option key={e.id} value={e.id}>{e.employee_code ? `${e.employee_code} · ` : ''}{e.name}</option>)}
              </select>
              <p className="text-[11px] text-muted-foreground">Dicatat Dr 1-1610 Uang Muka Karyawan; dibebankan saat Pertanggungjawaban.</p>
            </div>
          ) : (
            <>
              <div className="space-y-1">
                <Label>Kategori Biaya</Label>
                <Select value={form.category} onValueChange={v => setForm(p => ({ ...p, category: v }))}>
                  <SelectTrigger data-testid="txn-category"><SelectValue placeholder="Pilih kategori..." /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="">-- Tanpa Kategori --</SelectItem>
                    {categories.map(c => <SelectItem key={c.name} value={c.name}>{c.code ? `${c.code} - ${c.name}` : c.name}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              {form.txn_type === 'expense' && (
                <ExpenseAccountPicker category={form.category} value={form.account_code} refs={refs} testId="txn-account"
                  onChange={v => setForm(p => ({ ...p, account_code: v }))} />
              )}
              <div className="space-y-1">
                <Label>Dibayarkan Ke (Payee)</Label>
                <Input data-testid="txn-payee" placeholder="Nama toko / vendor" value={form.payee} onChange={e => setForm(p => ({ ...p, payee: e.target.value }))} />
              </div>
            </>
          )}
          <div className="space-y-1">
            <Label>Keterangan</Label>
            <Input data-testid="txn-memo" placeholder="Deskripsi singkat transaksi" value={form.memo} onChange={e => setForm(p => ({ ...p, memo: e.target.value }))} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>Batal</Button>
          <Button data-testid="txn-save" onClick={save} disabled={saving}>
            {saving && <Loader2 size={13} className="mr-1 animate-spin" />}
            Simpan & Post GL
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Pertanggungjawaban uang muka (K26, 2026-11-02) ───────────────────────────
// Nota per kategori → Dr beban (pemetaan / akun dipilih); sisa uang kembali → Dr kas kecil; Cr 1-1610.
function SettleAdvanceDialog({ advance, onClose, onDone }) {
  const open = !!advance;
  const refs = usePettyRefs(open);
  const [items, setItems] = useState([]);
  const [returned, setReturned] = useState('');
  const [date, setDate] = useState(todayWIB());
  const [memo, setMemo] = useState('');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  useEffect(() => {
    if (open) { setItems([{ category: '', account_code: '', amount: '', memo: '' }]); setReturned(''); setDate(todayWIB()); setMemo(''); setErr(''); }
  }, [open]);
  const total = items.reduce((s, it) => s + (parseFloat(it.amount) || 0), 0) + (parseFloat(returned) || 0);
  const setItem = (i, patch) => setItems(xs => xs.map((x, j) => (j === i ? { ...x, ...patch } : x)));

  const save = async () => {
    const rows = items.filter(it => parseFloat(it.amount) > 0);
    if (rows.some(it => !(it.category && refs.mapped[it.category]) && !it.account_code)) {
      return setErr('Ada nota dengan kategori yang belum dipetakan — pilih akun bebannya.');
    }
    if (total <= 0) return setErr('Isi minimal satu nota atau sisa uang yang dikembalikan.');
    if (total > (advance.open_amount || 0) + 0.01) return setErr(`Total ${fmt(total)} melebihi uang muka terbuka ${fmt(advance.open_amount)}.`);
    setSaving(true); setErr('');
    try {
      const r = await fetch(`${BASE}/advances/${advance.id}/settle`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}` },
        body: JSON.stringify({ items: rows.map(it => ({ ...it, amount: parseFloat(it.amount) })),
                               returned_amount: parseFloat(returned) || 0, settle_date: date, memo }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Gagal menyimpan');
      toast.success(`Pertanggungjawaban tercatat. JE ${d.gl_posting?.je_number || ''}`);
      onDone(); onClose();
    } catch (e) { setErr(e.message); } finally { setSaving(false); }
  };

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-lg" data-testid="settle-advance-dialog">
        <DialogHeader>
          <DialogTitle>Pertanggungjawaban Uang Muka</DialogTitle>
          <DialogDescription>
            {advance?.employee_name} · uang muka {fmt(advance?.amount)} · terbuka <strong>{fmt(advance?.open_amount)}</strong>
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 py-1">
          {err && <div className="text-destructive text-sm bg-destructive/10 rounded px-3 py-2">{err}</div>}
          {items.map((it, i) => (
            <div key={i} className="rounded-lg border border-border p-2 space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <select value={it.category} onChange={e => setItem(i, { category: e.target.value })}
                  className="h-9 px-2 rounded-md border border-input bg-background text-sm" data-testid={`settle-cat-${i}`}>
                  <option value="">— Kategori nota —</option>
                  {refs.categories.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
                </select>
                <Input type="number" min="1" placeholder="Nominal nota" value={it.amount}
                  onChange={e => setItem(i, { amount: e.target.value })} data-testid={`settle-amount-${i}`} />
              </div>
              <ExpenseAccountPicker category={it.category} value={it.account_code} refs={refs} testId={`settle-account-${i}`}
                onChange={v => setItem(i, { account_code: v })} />
            </div>
          ))}
          <Button variant="outline" size="sm" onClick={() => setItems(xs => [...xs, { category: '', account_code: '', amount: '', memo: '' }])}>+ Nota</Button>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Sisa uang dikembalikan (Rp)</Label>
              <Input type="number" min="0" value={returned} onChange={e => setReturned(e.target.value)} data-testid="settle-returned" />
            </div>
            <div className="space-y-1">
              <Label>Tanggal</Label>
              <Input type="date" value={date} onChange={e => setDate(e.target.value)} />
            </div>
          </div>
          <Input placeholder="Keterangan" value={memo} onChange={e => setMemo(e.target.value)} />
          <p className="text-xs text-muted-foreground">Total nota + sisa: <strong>{fmt(total)}</strong> (boleh bertahap; maks {fmt(advance?.open_amount)})</p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>Batal</Button>
          <Button onClick={save} disabled={saving} data-testid="settle-save">
            {saving && <Loader2 size={13} className="mr-1 animate-spin" />} Simpan & Post GL
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function OpenAdvancesCard({ fund, refreshKey, onSettle }) {
  const [data, setData] = useState({ items: [], by_employee: [], total_open: 0 });
  useEffect(() => {
    if (!fund?.id) return undefined;
    let off = false;
    fetch(`${BASE}/advances?status=open&fund_id=${fund.id}`, { headers: { Authorization: `Bearer ${token()}` } })
      .then(r => (r.ok ? r.json() : null)).then(d => { if (!off && d) setData(d); }).catch(() => {});
    return () => { off = true; };
  }, [fund?.id, refreshKey]);
  if (!data.items.length) return null;
  return (
    <Card className="shadow-[var(--shadow-card)]" data-testid="open-advances">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Uang Muka Terbuka — {fmt(data.total_open)}</CardTitle>
        <CardDescription>
          Per karyawan: {data.by_employee.map(g => `${g.employee_name} ${fmt(g.total_open)}${g.overdue_count ? ` (${g.overdue_count} terlambat)` : ''}`).join(' · ')}
          {!fund.advance_settle_days && ' · Batas hari pertanggungjawaban belum diatur.'}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/30">
              <TableHead className="text-xs">Tanggal</TableHead>
              <TableHead className="text-xs">Karyawan</TableHead>
              <TableHead className="text-xs text-right">Terbuka</TableHead>
              <TableHead className="text-xs">Batas</TableHead>
              <TableHead className="w-28" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.items.map(a => (
              <TableRow key={a.id} className={a.overdue ? 'bg-rose-50 dark:bg-rose-500/10' : ''}>
                <TableCell className="text-xs">{fmtDate(a.txn_date)} <span className="text-muted-foreground">({a.age_days} hr)</span></TableCell>
                <TableCell className="text-xs">{a.employee_name}</TableCell>
                <TableCell className="text-xs text-right font-mono">{fmt(a.open_amount)}</TableCell>
                <TableCell className="text-xs">{a.due_date ? `${fmtDate(a.due_date)}${a.overdue ? ' · TERLAMBAT' : ''}` : '—'}</TableCell>
                <TableCell>
                  <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => onSettle(a)} data-testid={`settle-btn-${a.id}`}>
                    Pertanggungjawaban
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

// ── Fund Card ─────────────────────────────────────────────────────────────────
function FundCard({ fund, onSelect, isActive }) {
  const pct = fund.opening_balance > 0
    ? Math.min(100, (fund.current_balance / fund.opening_balance) * 100)
    : 100;
  const isLow = pct < 25;
  return (
    <Card
      data-testid={`fund-card-${fund.id}`}
      className={`cursor-pointer transition-all shadow-[var(--shadow-card)] ${
        isActive ? 'ring-2 ring-[hsl(var(--primary))]' : 'hover:shadow-md'
      }`}
      onClick={() => onSelect(fund)}
    >
      <CardContent className="p-4">
        <div className="flex items-start justify-between mb-2">
          <div>
            <p className="font-semibold text-sm text-foreground">{fund.name}</p>
            {fund.custodian_name && (
              <p className="text-xs text-muted-foreground">{fund.custodian_name}</p>
            )}
          </div>
          <Badge variant="outline" className={fund.status === 'active' ? 'border-emerald-500/30 text-emerald-600' : 'text-muted-foreground'}>
            {fund.status === 'active' ? 'Aktif' : 'Tutup'}
          </Badge>
        </div>
        <p className={`text-xl font-bold ${isLow ? 'text-rose-500' : 'text-foreground'}`}>
          {fmt(fund.current_balance)}
        </p>
        {isLow && (
          <p className="text-xs text-rose-500 mt-1 flex items-center gap-1">
            <AlertCircle size={11} /> Saldo rendah — perlu replenishment
          </p>
        )}
        <div className="mt-2 h-1.5 bg-muted rounded-full">
          <div
            className={`h-full rounded-full transition-all ${
              isLow ? 'bg-rose-500' : pct < 50 ? 'bg-amber-500' : 'bg-emerald-500'
            }`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </CardContent>
    </Card>
  );
}

// ── Transaction Row ────────────────────────────────────────────────────────────
function TxnRow({ txn, canRetry, onRetry }) {
  const cfg = TXN_CONFIG[txn.txn_type] || TXN_CONFIG.expense;
  const Icon = cfg.icon;
  return (
    <TableRow data-testid={`txn-row-${txn.id}`}>
      <TableCell className="w-8">
        <Icon size={14} className={cfg.color} />
      </TableCell>
      <TableCell className="text-xs text-muted-foreground">{fmtDate(txn.txn_date)}</TableCell>
      <TableCell>
        <Badge variant="outline" className="text-xs">{cfg.label}</Badge>
      </TableCell>
      <TableCell className="text-sm max-w-[160px] truncate">
        {txn.payee || txn.memo || txn.category || '—'}
      </TableCell>
      <TableCell className="text-right">
        <span className={`font-semibold text-sm ${cfg.color}`}>
          {cfg.sign}{fmt(txn.amount)}
        </span>
      </TableCell>
      <TableCell>
        {txn.gl_posted ? (
          <Badge variant="outline" className="border-emerald-500/30 bg-emerald-500/10 text-emerald-600 text-xs gap-1">
            <CheckCircle2 size={10} /> Posted
          </Badge>
        ) : (
          <Badge variant="outline" className="border-rose-500/30 bg-rose-500/10 text-rose-600 text-xs gap-1">
            <XCircle size={10} /> Unposted
          </Badge>
        )}
      </TableCell>
      {canRetry && (
        <TableCell>
          {!txn.gl_posted && (
            <Button variant="ghost" size="sm" className="h-7 gap-1 text-xs" onClick={() => onRetry(txn)}>
              <RotateCcw size={11} /> Retry
            </Button>
          )}
        </TableCell>
      )}
    </TableRow>
  );
}

// ── Main Module ────────────────────────────────────────────────────────────────
export default function PettyCashModule() {
  const [funds, setFunds] = useState([]);
  const [txns, setTxns]   = useState([]);
  const [activeFund, setActiveFund] = useState(null);
  const [loading, setLoading] = useState(true);
  const [txnLoading, setTxnLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [replenishOpen, setReplenishOpen] = useState(false);
  const [addTxnOpen, setAddTxnOpen] = useState(false);
  // 2026-11-02 (K26): uang muka terbuka + pertanggungjawaban + batas hari per dana
  const [settleAdv, setSettleAdv] = useState(null);
  const [advKey, setAdvKey] = useState(0);
  const [settleDays, setSettleDays] = useState('');

  const role = userRole();
  const canManage = FINANCE_ROLES.includes(role);
  // 2026-11-02: rekening sumber = rekening kas/bank aktif nyata, TANPA akun dana kas kecil itu sendiri
  const { accounts: cashAccounts, loaded: cashLoaded } = usePaymentCashAccounts();
  const [pettyCode, setPettyCode] = useState('');
  const sourceAccounts = useMemo(
    () => cashAccounts.filter(a => a.gl_account_code !== pettyCode), [cashAccounts, pettyCode]);

  const fetchFunds = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${BASE}/funds`, { headers: { Authorization: `Bearer ${token()}` } });
      const d = await r.json();
      const list = d.items || [];
      setPettyCode(d.petty_cash_account_code || '');
      setFunds(list);
      setActiveFund(prev => {
        if (!prev) return list.length > 0 ? list[0] : null;
        const refreshed = list.find(f => f.id === prev.id);
        return refreshed || prev;
      });
    } catch { toast.error('Gagal memuat dana kas kecil'); }
    finally { setLoading(false); }
  }, []);

  const fetchTxns = useCallback(async (fundId) => {
    if (!fundId) return;
    setTxnLoading(true);
    try {
      const r = await fetch(`${BASE}/transactions?fund_id=${fundId}&limit=50`, {
        headers: { Authorization: `Bearer ${token()}` },
      });
      const d = await r.json();
      setTxns(d.items || []);
    } catch { toast.error('Gagal memuat transaksi'); }
    finally { setTxnLoading(false); }
  }, []);

  useEffect(() => { fetchFunds(); }, [fetchFunds]);
  useEffect(() => { if (activeFund?.id) fetchTxns(activeFund.id); }, [activeFund?.id, fetchTxns]);

  const handleRetryPosting = async (txn) => {
    try {
      const r = await fetch(`${BASE}/transactions/${txn.id}/retry-posting`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token()}` },
      });
      const d = await r.json();
      if (d.ok) { toast.success('Retry berhasil — JE terposting.'); fetchTxns(activeFund.id); }
      else toast.error(`Retry gagal: ${d.error}`);
    } catch { toast.error('Koneksi bermasalah'); }
  };

  const handleCloseFund = async () => {
    if (!activeFund || !window.confirm(`Tutup dana "${activeFund.name}"? Sisa saldo akan dikembalikan ke bank.`)) return;
    try {
      const r = await fetch(`${BASE}/funds/${activeFund.id}/close`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token()}` },
      });
      const d = await r.json();
      if (d.ok) { toast.success('Dana ditutup.'); setActiveFund(null); fetchFunds(); }
      else toast.error(d.detail || 'Gagal menutup dana');
    } catch { toast.error('Koneksi bermasalah'); }
  };

  const afterAction = () => { fetchFunds(); if (activeFund) fetchTxns(activeFund.id); setAdvKey(k => k + 1); };

  useEffect(() => { setSettleDays(activeFund?.advance_settle_days ?? 0); }, [activeFund?.id, activeFund?.advance_settle_days]);
  const saveSettleDays = async () => {
    try {
      const r = await fetch(`${BASE}/funds/${activeFund.id}/settings`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}` },
        body: JSON.stringify({ advance_settle_days: Number(settleDays) || 0 }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Gagal');
      toast.success('Batas hari pertanggungjawaban disimpan.');
      afterAction();
    } catch (e) { toast.error(e.message); }
  };

  const totalBalance = funds.filter(f => f.status === 'active').reduce((s, f) => s + (f.current_balance || 0), 0);
  const unpostedCount = txns.filter(t => !t.gl_posted).length;

  return (
    <div className="space-y-4 p-4">
      {/* Header */}
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-bold text-foreground">Kas Kecil</h1>
          <p className="text-sm text-muted-foreground">Imprest fund management dengan auto-posting GL.</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={fetchFunds} disabled={loading}>
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </Button>
          {canManage && (
            <Button size="sm" data-testid="create-fund-btn" onClick={() => setCreateOpen(true)} className="gap-2">
              <Plus size={14} /> Buat Dana Baru
            </Button>
          )}
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-3">
        <Card className="shadow-[var(--shadow-card)]">
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">Total Saldo Aktif</p>
            <p className="text-lg font-bold text-foreground">{fmt(totalBalance)}</p>
          </CardContent>
        </Card>
        <Card className="shadow-[var(--shadow-card)]">
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">Jumlah Dana</p>
            <p className="text-lg font-bold">{funds.filter(f => f.status === 'active').length}</p>
          </CardContent>
        </Card>
        <Card className="shadow-[var(--shadow-card)]">
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">Transaksi Unposted</p>
            <p className={`text-lg font-bold ${unpostedCount > 0 ? 'text-rose-500' : 'text-emerald-500'}`}>
              {unpostedCount}
            </p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
        {/* Fund List */}
        <div className="space-y-3">
          <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Dana Tersedia</p>
          {loading ? (
            <div className="flex justify-center py-8"><Loader2 className="animate-spin text-muted-foreground" /></div>
          ) : funds.length === 0 ? (
            <Card className="shadow-[var(--shadow-card)]">
              <CardContent className="pt-6 text-center">
                <Wallet size={32} className="mx-auto opacity-20 mb-2" />
                <p className="text-sm text-muted-foreground">Belum ada dana kas kecil.</p>
                {canManage && (
                  <Button size="sm" className="mt-3" onClick={() => setCreateOpen(true)}>Buat Dana</Button>
                )}
              </CardContent>
            </Card>
          ) : (
            funds.map(f => (
              <FundCard key={f.id} fund={f} isActive={activeFund?.id === f.id} onSelect={setActiveFund} />
            ))
          )}
        </div>

        {/* Fund Detail + Txns */}
        <div className="space-y-4">
          {activeFund ? (
            <>
              {/* Fund Actions */}
              <Card className="shadow-[var(--shadow-card)]">
                <CardContent className="pt-4 pb-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <h2 className="font-semibold text-foreground">{activeFund.name}</h2>
                      <p className="text-sm text-muted-foreground">Saldo: <strong>{fmt(activeFund.current_balance)}</strong></p>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        size="sm"
                        data-testid="add-txn-btn"
                        onClick={() => setAddTxnOpen(true)}
                        disabled={activeFund.status !== 'active'}
                        className="gap-2"
                      >
                        <Receipt size={13} /> Catat Transaksi
                      </Button>
                      {canManage && (
                        <>
                          <Button
                            variant="outline"
                            size="sm"
                            data-testid="replenish-btn"
                            onClick={() => setReplenishOpen(true)}
                            disabled={activeFund.status !== 'active'}
                          >
                            <Banknote size={13} className="mr-1" /> Replenish
                          </Button>
                          {activeFund.status === 'active' && (
                            <Button variant="ghost" size="sm" className="text-destructive" onClick={handleCloseFund}>
                              Tutup Dana
                            </Button>
                          )}
                        </>
                      )}
                    </div>
                  </div>
                  {canManage && (
                    <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
                      <span>Batas pertanggungjawaban uang muka:</span>
                      <Input type="number" min="0" max="365" value={settleDays} onChange={e => setSettleDays(e.target.value)}
                        className="h-7 w-20 text-xs" data-testid="fund-settle-days" />
                      <span>hari (0 = belum diatur)</span>
                      <Button size="sm" variant="outline" className="h-7 text-xs" onClick={saveSettleDays}>Simpan</Button>
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* 2026-11-02 (K26): uang muka karyawan yang belum dipertanggungjawabkan */}
              <OpenAdvancesCard fund={activeFund} refreshKey={advKey} onSettle={setSettleAdv} />

              {/* Transaction History */}
              <Card className="shadow-[var(--shadow-card)]">
                <CardHeader className="pb-2">
                  <CardTitle className="text-base flex items-center gap-2">
                    <Receipt size={15} /> Riwayat Transaksi
                  </CardTitle>
                  {unpostedCount > 0 && (
                    <CardDescription className="flex items-center gap-1 text-rose-500">
                      <AlertCircle size={12} /> {unpostedCount} transaksi belum terposting ke GL
                    </CardDescription>
                  )}
                </CardHeader>
                <CardContent>
                  {txnLoading ? (
                    <div className="flex justify-center py-8"><Loader2 className="animate-spin text-muted-foreground" /></div>
                  ) : txns.length === 0 ? (
                    <div className="text-center py-8 text-muted-foreground text-sm">
                      <Receipt size={32} className="mx-auto opacity-20 mb-2" />
                      Belum ada transaksi pada dana ini.
                    </div>
                  ) : (
                    <Table>
                      <TableHeader>
                        <TableRow className="bg-muted/30">
                          <TableHead className="w-8" />
                          <TableHead className="text-xs">Tanggal</TableHead>
                          <TableHead className="text-xs">Tipe</TableHead>
                          <TableHead className="text-xs">Keterangan</TableHead>
                          <TableHead className="text-xs text-right">Jumlah</TableHead>
                          <TableHead className="text-xs">GL Status</TableHead>
                          <TableHead className="w-16" />
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {txns.map(t => (
                          <TxnRow key={t.id} txn={t} canRetry={canManage} onRetry={handleRetryPosting} />
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </CardContent>
              </Card>
            </>
          ) : (
            <Card className="shadow-[var(--shadow-card)]">
              <CardContent className="flex flex-col items-center justify-center py-16 gap-3">
                <Eye size={40} className="opacity-20" />
                <p className="text-sm text-muted-foreground">Pilih dana untuk melihat detail & transaksi.</p>
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {/* Dialogs */}
      <CreateFundDialog open={createOpen} onClose={() => setCreateOpen(false)} onCreated={afterAction}
        accounts={sourceAccounts} accountsLoaded={cashLoaded} />
      {activeFund && (
        <>
          <ReplenishDialog open={replenishOpen} fund={activeFund} onClose={() => setReplenishOpen(false)} onDone={afterAction}
            accounts={sourceAccounts} accountsLoaded={cashLoaded} />
          <AddTxnDialog open={addTxnOpen} fund={activeFund} onClose={() => setAddTxnOpen(false)} onDone={afterAction} />
          <SettleAdvanceDialog advance={settleAdv} onClose={() => setSettleAdv(null)} onDone={afterAction} />
        </>
      )}
    </div>
  );
}

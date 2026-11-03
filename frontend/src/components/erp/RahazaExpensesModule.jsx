import { useState, useEffect, useCallback, useMemo } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Plus, RefreshCw, Receipt, CreditCard, BookOpen } from 'lucide-react';
import { GlassCard, GlassPanel, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { PageHeader, StatTile } from './moduleAtoms';
import { DataTable } from './DataTableV2';
import OnwardCTA from './OnwardCTA';
import { formatRupiah, formatDateID } from '@/lib/format';
import PeriodPicker, { periodFromPreset } from './finance/PeriodPicker';
import { MoneyInput } from '@/components/ui/money-input';
import { todayWIB } from '@/lib/waktu';
import CashAccountSelect, { usePaymentCashAccounts } from './SdmCashAccountSelect';

const fmt = formatRupiah;

// 2026-11-04 (owner: akun beban WAJIB dipilih). Dulu form tidak punya pilihan akun, jadi semua
// pengeluaran dari layar terjurnal ke 6-2900 Beban Umum. Tipe = EXPENSE_DEBIT_TYPES di backend.
const EXPENSE_ACCOUNT_TYPES = ['EXPENSE', 'COGS', 'OTHER_EXPENSE'];
const EXP_LIMIT = 5000;

export default function RahazaExpensesModule({ token, onNavigate }) {
  const [rows, setRows] = useState([]);
  const [centers, setCenters] = useState([]);
  const [coa, setCoa] = useState([]);
  const { accounts, loaded: accountsLoaded } = usePaymentCashAccounts(token);
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
  // 2026-11-04: periode dipilih (dulu 500 pengeluaran terbaru diam-diam, tanpa tanda terpotong)
  const [period, setPeriod] = useState(() => periodFromPreset('3m'));

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [e, c, a] = await Promise.all([
        fetch(`/api/rahaza/expenses?from_=${period.from}&to=${period.to}&limit=${EXP_LIMIT}`, { headers }).then(r => r.json()),
        fetch('/api/rahaza/cost-centers', { headers }).then(r => r.json()),
        fetch('/api/rahaza/coa/accounts', { headers }).then(r => (r.ok ? r.json() : [])),
      ]);
      setRows(Array.isArray(e) ? e : []); setCenters(Array.isArray(c) ? c : []); setCoa(Array.isArray(a) ? a : []);
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, period.from, period.to]);
  useEffect(() => { fetchAll(); }, [fetchAll]);

  // FIN-20f: kunci klik ganda + tampilkan galat posting GL
  const [savingExp, setSavingExp] = useState(false);
  const create = async (body) => {
    if (savingExp) return;
    setSavingExp(true);
    try {
      const r = await fetch('/api/rahaza/expenses', { method: 'POST', headers, body: JSON.stringify(body) });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) { window.alert(data?.detail || 'Gagal menyimpan pengeluaran'); return; }
      const pr = data?.posting_result || data?.gl_posting;
      if (pr && pr.ok === false) window.alert(`Pengeluaran tersimpan, tetapi jurnal GAGAL: ${pr.error || ''}`);
      setCreating(false); fetchAll();
    } finally { setSavingExp(false); }
  };

  const total = rows.reduce((s, r) => s + (Number(r.amount) || 0), 0);
  const expenseAccounts = useMemo(
    () => coa.filter(a => !a.is_group && a.active !== false && EXPENSE_ACCOUNT_TYPES.includes(a.type))
      .sort((x, y) => String(x.code).localeCompare(String(y.code))),
    [coa]);
  const coaName = useMemo(() => Object.fromEntries(coa.map(a => [a.code, a.name])), [coa]);

  // Kategori unik untuk filter dropdown
  const categoryOptions = useMemo(() => {
    const set = new Set();
    rows.forEach(r => { if (r.category) set.add(r.category); });
    return [...set].sort().map(c => ({ value: c, label: c }));
  }, [rows]);

  return (
    <div className="space-y-5" data-testid="rahaza-expenses-page">
      <PageHeader
        icon={CreditCard}
        title="Pengeluaran"
        subtitle="Catat biaya operasional: pilih akun beban dan rekening yang membayar; jurnal terbentuk otomatis."
        actions={
          <>
            <PeriodPicker value={period} onChange={setPeriod} testId="exp-period" />
            <Button variant="ghost" onClick={fetchAll} className="h-9 border border-[var(--glass-border)]" title="Muat ulang" aria-label="Muat ulang"><RefreshCw className="w-3.5 h-3.5" /></Button>
            <Button onClick={() => setCreating(true)} className="h-9" data-testid="exp-add"><Plus className="w-3.5 h-3.5 mr-1.5" />Pengeluaran baru</Button>
          </>
        }
      />
      <StatTile label={`Total pengeluaran ${formatDateID(period.from)} – ${formatDateID(period.to)}`} value={fmt(total)} accent="danger" />
      {rows.length >= EXP_LIMIT && (
        <p className="text-xs text-amber-600 dark:text-amber-400" data-testid="exp-truncated">
          Ditampilkan {EXP_LIMIT.toLocaleString('id-ID')} pengeluaran terbaru saja — persempit periode supaya semua terlihat.
        </p>
      )}
      <DataTable
        tableId="expenses"
        loading={loading}
        rows={rows}
        searchFields={['date', 'category', 'description', 'cost_center_code', 'cost_center_name']}
        filters={[
          { key: 'category', label: 'Kategori', type: 'select', options: categoryOptions },
          { key: 'cost_center_id', label: 'Pusat biaya', type: 'select',
            options: centers.map(c => ({ value: c.id, label: `${c.code} · ${c.name}` })) },
          { key: 'date', label: 'Tanggal', type: 'date-range' },
        ]}
        columns={[
          { key: 'date', label: 'Tanggal', sortable: true,
            render: (r, v) => <span className="text-xs whitespace-nowrap">{formatDateID(v)}</span> },
          { key: 'category', label: 'Kategori', sortable: true,
            render: (r, v) => <span className="text-xs">{v}</span> },
          { key: 'description', label: 'Deskripsi', sortable: true },
          { key: 'gl_debit_code', label: 'Akun beban',
            render: (r) => <span className="text-[11px] text-foreground/70">{r.gl_debit_code ? `${r.gl_debit_code} · ${coaName[r.gl_debit_code] || ''}` : 'bawaan (Beban Umum)'}</span> },
          { key: 'cost_center_code', label: 'Pusat biaya',
            render: (r) => <span className="text-[11px] text-foreground/60">{r.cost_center_code || '—'} {r.cost_center_name && `· ${r.cost_center_name}`}</span> },
          { key: 'amount', label: 'Jumlah', align: 'right', sortable: true,
            render: (r) => <span className="font-mono text-[hsl(var(--destructive))]">{fmt(r.amount)}</span> },
        ]}
        emptyTitle="Belum ada pengeluaran di periode ini"
        emptyDescription='Tekan "Pengeluaran baru" untuk mencatat biaya operasional.'
        emptyIcon={CreditCard}
        exportFilename={`expenses-${todayWIB()}.csv`}
      />
      <OnwardCTA
        onNavigate={onNavigate}
        title="Setelah Catat Biaya"
        actions={[
          { module: 'fin-journal-hub', label: 'Lihat Jurnal (GL)', icon: BookOpen, primary: true, hint: 'Cek jurnal akuntansi yang terbentuk dari biaya' },
          { module: 'fin-expense-settlement', label: 'Settlement Klaim', icon: CreditCard, hint: 'Proses pencairan klaim biaya karyawan' },
        ]}
      />
      {creating && <ExpEditor centers={centers} accounts={accounts} accountsLoaded={accountsLoaded}
                              expenseAccounts={expenseAccounts} onClose={() => setCreating(false)} onSave={create} saving={savingExp} />}
    </div>
  );
}

function ExpEditor({ centers, accounts, accountsLoaded, expenseAccounts, onClose, onSave, saving }) {
  const [s, setS] = useState({ date: todayWIB(), category: 'operasional', description: '', amount: 0, gl_debit_code: '', cost_center_id: '', account_id: '', notes: '' });
  const upd = (k, v) => setS(x => ({ ...x, [k]: v }));
  // Rekening pembayar juga wajib: bila kosong, jurnal dulu jatuh diam-diam ke rekening bawaan profil.
  const missing = !s.gl_debit_code ? 'Pilih akun beban.' : !s.account_id ? 'Pilih rekening yang membayar.'
    : !(Number(s.amount) > 0) ? 'Isi jumlah.' : '';
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <GlassCard className="p-6 max-w-md w-full" onClick={e => e.stopPropagation()}>
        <h2 className="text-xl font-bold text-foreground mb-4">Tambah Pengeluaran</h2>
        <div className="space-y-3">
          <div><label className="text-xs text-muted-foreground" htmlFor="exp-date">Tanggal</label><GlassInput id="exp-date" type="date" value={s.date} onChange={e => upd('date', e.target.value)} /></div>
          <div><label className="text-xs text-muted-foreground">Akun beban</label>
            <SmartNativeSelect value={s.gl_debit_code} onChange={e => upd('gl_debit_code', e.target.value)} searchable
              className="w-full h-10 px-3 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-sm text-foreground" data-testid="exp-gl-account">
              <option value="">— Pilih akun beban (ketik untuk mencari) —</option>
              {expenseAccounts.map(a => <option key={a.code} value={a.code}>{`${a.code} · ${a.name}`}</option>)}
            </SmartNativeSelect></div>
          <div><label className="text-xs text-muted-foreground" htmlFor="exp-desc">Deskripsi</label><GlassInput id="exp-desc" value={s.description} onChange={e => upd('description', e.target.value)} placeholder="mis. Listrik kantor Oktober" data-testid="exp-desc" /></div>
          <div><label className="text-xs text-muted-foreground" htmlFor="exp-amount">Jumlah</label><MoneyInput glass id="exp-amount" value={s.amount} onChange={e => upd('amount', Number(e.target.value))} data-testid="exp-amount" /></div>
          <div><label className="text-xs text-muted-foreground">Bayar dari rekening</label><CashAccountSelect accounts={accounts} loaded={accountsLoaded} value={s.account_id} onChange={v => upd('account_id', v)} testId="exp-cash-account" /></div>
          <div><label className="text-xs text-muted-foreground" htmlFor="exp-category">Kategori (untuk penyaring daftar)</label><GlassInput id="exp-category" value={s.category} onChange={e => upd('category', e.target.value)} placeholder="operasional | sewa | listrik | ..." /></div>
          <div><label className="text-xs text-muted-foreground">Cost Center (opsional)</label><SmartNativeSelect value={s.cost_center_id} onChange={e => upd('cost_center_id', e.target.value)} className="w-full h-10 px-3 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-sm text-foreground"><option value="">— Tanpa —</option>{centers.map(c => <option key={c.id} value={c.id}>{`${c.code} · ${c.name}`}</option>)}</SmartNativeSelect></div>
        </div>
        {missing && <p className="text-[11px] text-muted-foreground mt-3" data-testid="exp-missing">{missing}</p>}
        <div className="flex gap-2 mt-6 justify-end"><Button variant="ghost" onClick={onClose} className="border border-[var(--glass-border)]">Batal</Button><Button onClick={() => onSave(s)} disabled={saving || !!missing} data-testid="exp-save">{saving ? 'Menyimpan…' : 'Simpan'}</Button></div>
      </GlassCard>
    </div>
  );
}

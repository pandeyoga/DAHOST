import { useState, useEffect, useCallback, useMemo } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { toast } from 'sonner';
import { AlertTriangle, Plus, RefreshCw, CreditCard } from 'lucide-react';
import { GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import PageLayout from './layout/PageLayout';
import { Notice } from './moduleAtoms';
import { DataTable } from './DataTableV2';
import { formatRupiah, formatDateID } from '@/lib/format';
import PeriodPicker, { periodFromPreset } from './finance/PeriodPicker';
import { MoneyInput } from '@/components/ui/money-input';
import { todayWIB } from '@/lib/waktu';
import CashAccountSelect, { usePaymentCashAccounts } from './SdmCashAccountSelect';
import { cvAccountParam, useCv } from '@/lib/entitas';

const fmt = formatRupiah;

// 2026-11-04 (owner: akun beban WAJIB dipilih). Dulu form tidak punya pilihan akun, jadi semua
// pengeluaran dari layar terjurnal ke 6-2900 Beban Umum. Tipe = EXPENSE_DEBIT_TYPES di backend.
const EXPENSE_ACCOUNT_TYPES = ['EXPENSE', 'COGS', 'OTHER_EXPENSE'];
const EXP_LIMIT = 5000;
// kode kategori → kata biasa ("bahan_pembantu" → "Bahan pembantu") — PANDUAN_UI G6/G11
const humanize = (v) => (v ? String(v).replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase()) : '—');

export default function RahazaExpensesModule({ token, onNavigate }) {
  const [rows, setRows] = useState([]);
  const [centers, setCenters] = useState([]);
  const [coa, setCoa] = useState([]);
  const { accounts, loaded: accountsLoaded } = usePaymentCashAccounts(token);
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
  const coaCv = cvAccountParam(useCv()?.cv);  // Tahap 8: akun beban milik CV terpilih saja
  // 2026-11-04: periode dipilih (dulu 500 pengeluaran terbaru diam-diam, tanpa tanda terpotong)
  const [period, setPeriod] = useState(() => periodFromPreset('3m'));

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [e, c, a] = await Promise.all([
        fetch(`/api/rahaza/expenses?from_=${period.from}&to=${period.to}&limit=${EXP_LIMIT}`, { headers }).then(r => r.json()),
        fetch('/api/rahaza/cost-centers', { headers }).then(r => r.json()),
        fetch(`/api/rahaza/coa/accounts${coaCv ? `?${coaCv}` : ''}`, { headers }).then(r => (r.ok ? r.json() : [])),
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
      if (!r.ok) { toast.error(data?.detail || 'Gagal menyimpan pengeluaran'); return; }
      const pr = data?.posting_result || data?.gl_posting;
      if (pr && pr.ok === false) toast.error(`Pengeluaran tersimpan, tetapi jurnal GAGAL: ${pr.error || ''}`);
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
    return [...set].sort().map(c => ({ value: c, label: humanize(c) }));
  }, [rows]);

  // 2026-11-05 (PANDUAN_UI G1): cetakan PageLayout — periode di toolbar kiri, muat ulang di kanan, tombol utama
  // di kepala (di hub: baris tab). Dulu periode + muat ulang + tombol baru menumpuk di kepala halaman.
  return (
    <PageLayout
      testId="rahaza-expenses-page"
      title="Pengeluaran"
      subtitle="Biaya operasional: pilih akun beban dan rekening yang membayar; jurnal terbentuk otomatis."
      actions={<Button onClick={() => setCreating(true)} data-testid="exp-add"><Plus className="w-4 h-4" />Pengeluaran baru</Button>}
      filters={<PeriodPicker value={period} onChange={setPeriod} testId="exp-period" />}
      tools={<Button size="icon" variant="outline" onClick={fetchAll} title="Muat ulang" aria-label="Muat ulang"><RefreshCw className="w-4 h-4" /></Button>}
      summary={<>
        {/* PANDUAN_UI G5 (2026-11-04): total sebagai satu baris netral — dulu kartu selebar halaman dengan "Rp 0" merah */}
        <p className="text-sm text-muted-foreground" data-testid="exp-total">
          {formatDateID(period.from)} – {formatDateID(period.to)} · {rows.length} pengeluaran · total <b className="text-foreground tabular-nums">{fmt(total)}</b>
        </p>
        {rows.length >= EXP_LIMIT && (
          <Notice tone="warning" icon={AlertTriangle} testId="exp-truncated">
            Ditampilkan {EXP_LIMIT.toLocaleString('id-ID')} pengeluaran terbaru saja — persempit periode supaya semua terlihat.
          </Notice>
        )}
      </>}
    >
      {/* 2026-11-05 (galeri: SEL-TERLIPAT): sel tanggal/jumlah berisi teks langsung (tanpa <span>) dan tidak dipatah */}
      <DataTable
        tableId="expenses"
        loading={loading}
        rows={rows}
        searchFields={['date', 'category', 'description', 'cost_center_code', 'cost_center_name']}
        filters={[
          { key: 'category', label: 'Kategori', type: 'select', options: categoryOptions },
          { key: 'cost_center_id', label: 'Pusat biaya', type: 'select',
            options: centers.map(c => ({ value: c.id, label: `${c.code} · ${c.name}` })) },
        ]}
        columns={[
          { key: 'date', label: 'Tanggal', sortable: true, className: 'whitespace-nowrap',
            render: (r) => formatDateID(r.date) },
          { key: 'category', label: 'Kategori', sortable: true,
            render: (r, v) => humanize(v), accessor: (r) => humanize(r.category) },
          { key: 'description', label: 'Deskripsi', sortable: true },
          { key: 'gl_debit_code', label: 'Akun beban',
            accessor: (r) => (r.gl_debit_code ? `${r.gl_debit_code} · ${coaName[r.gl_debit_code] || ''}` : 'bawaan (Beban Umum)'),
            render: (r) => <span className="text-sm text-muted-foreground">{r.gl_debit_code ? `${r.gl_debit_code} · ${coaName[r.gl_debit_code] || ''}` : 'bawaan (Beban Umum)'}</span> },
          { key: 'cost_center_code', label: 'Pusat biaya',
            accessor: (r) => [r.cost_center_code, r.cost_center_name].filter(Boolean).join(' · '),
            render: (r) => <span className="text-sm text-muted-foreground">{r.cost_center_code || '—'} {r.cost_center_name && `· ${r.cost_center_name}`}</span> },
          { key: 'amount', label: 'Jumlah', align: 'right', sortable: true, className: 'whitespace-nowrap tabular-nums',
            render: (r) => fmt(r.amount), accessor: (r) => Number(r.amount) || 0 },
        ]}
        emptyTitle="Belum ada pengeluaran di periode ini"
        emptyDescription='Tekan "Pengeluaran baru" untuk mencatat biaya operasional.'
        emptyIcon={CreditCard}
        exportFilename={`pengeluaran-${todayWIB()}.csv`}
      />
      {creating && <ExpEditor centers={centers} accounts={accounts} accountsLoaded={accountsLoaded} categories={categoryOptions.map(c => c.value)}
                              expenseAccounts={expenseAccounts} onClose={() => setCreating(false)} onSave={create} saving={savingExp} />}
    </PageLayout>
  );
}

function ExpEditor({ centers, accounts, accountsLoaded, expenseAccounts, categories = [], onClose, onSave, saving }) {
  const [s, setS] = useState({ date: todayWIB(), category: 'operasional', description: '', amount: 0, gl_debit_code: '', cost_center_id: '', account_id: '', notes: '' });
  const upd = (k, v) => setS(x => ({ ...x, [k]: v }));
  // Rekening pembayar juga wajib: bila kosong, jurnal dulu jatuh diam-diam ke rekening bawaan profil.
  const missing = !s.gl_debit_code ? 'Pilih akun beban.' : !s.account_id ? 'Pilih rekening yang membayar.'
    : !(Number(s.amount) > 0) ? 'Isi jumlah.' : '';
  // 2026-11-08 (Standar UI/UX v2): popup form standar (FormPopup pendek, Isian, DatePicker, Simpan hijau).
  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="exp-dialog" judul="Pengeluaran baru"
      keterangan="Jurnal: debit akun beban, kredit rekening yang membayar."
      onSimpan={() => onSave(s)} menyimpan={saving} bisaSimpan={!missing}
      galat={missing && (s.gl_debit_code || s.account_id || Number(s.amount) > 0) ? missing : undefined}>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Isian label="Tanggal" wajib>
          <DatePicker id="exp-date" value={s.date} onChange={v => upd('date', v)} bolehKosong={false} testId="exp-date" />
        </Isian>
        <Isian label="Jumlah" wajib htmlFor="exp-amount">
          <MoneyInput glass id="exp-amount" value={s.amount} onChange={e => upd('amount', Number(e.target.value))} data-testid="exp-amount" />
        </Isian>
      </div>
      <Isian label="Akun beban" wajib>
        <SmartNativeSelect value={s.gl_debit_code} onChange={e => upd('gl_debit_code', e.target.value)} searchable
          className="w-full h-9" data-testid="exp-gl-account">
          <option value="">— Pilih akun beban (ketik untuk mencari) —</option>
          {expenseAccounts.map(a => <option key={a.code} value={a.code}>{`${a.code} · ${a.name}`}</option>)}
        </SmartNativeSelect>
      </Isian>
      <Isian label="Deskripsi" htmlFor="exp-desc">
        <GlassInput id="exp-desc" value={s.description} onChange={e => upd('description', e.target.value)} placeholder="mis. Listrik kantor Oktober" data-testid="exp-desc" />
      </Isian>
      <Isian label="Bayar dari rekening" wajib>
        <CashAccountSelect accounts={accounts} loaded={accountsLoaded} value={s.account_id} onChange={v => upd('account_id', v)} testId="exp-cash-account" />
      </Isian>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {/* 2026-11-07 (audit form Tahap 5): kategori = teks bebas (tidak ada master), dengan saran kategori yang sudah dipakai */}
        <Isian label="Kategori" htmlFor="exp-category" petunjuk="Untuk penyaring daftar.">
          <GlassInput id="exp-category" list="exp-category-list" value={s.category} onChange={e => upd('category', e.target.value)} placeholder="operasional, sewa, listrik…" data-testid="exp-category" />
          <datalist id="exp-category-list">{[...new Set(['operasional', ...categories])].map(c => <option key={c} value={c} />)}</datalist>
        </Isian>
        <Isian label="Pusat biaya (opsional)">
          <SmartNativeSelect value={s.cost_center_id} onChange={e => upd('cost_center_id', e.target.value)} className="w-full h-9" data-testid="exp-cost-center"><option value="">— Tanpa —</option>{centers.map(c => <option key={c.id} value={c.id}>{`${c.code} · ${c.name}`}</option>)}</SmartNativeSelect>
        </Isian>
      </div>
    </FormPopup>
  );
}

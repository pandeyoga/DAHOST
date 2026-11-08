/**
 * Employee Expense Approval Module
 * CV. Dewi Aditya — Employee Expense Management (EEM)
 *
 * Unified approval inbox untuk:
 *  - Klaim Biaya (Reimbursement) — Manager/HR approve/reject → Finance disburse
 *  - Perjalanan Dinas — Manager/HR approve → Finance bayar uang muka
 *
 * 2026-11-08 (Standar UI/UX v2): rincian = popup; tanggal bayar = DatePicker; Setujui/Bayar hijau, Tolak merah;
 * unduh Excel & CSV (dulu CSV saja); judul kolom tanpa huruf kapital dan tanpa tombol buatan sendiri.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import FilterChips from '@/components/ui/filter-chips';
import ViewToggle from '@/components/ui/view-toggle';
import { toast } from 'sonner';
import { FINANCE_PAY_PERMS, FINANCE_ROLES } from '../../lib/financeRoles'; // FIN-02
import { checkPerm } from '../../lib/rbac';
import {
  CheckCircle, XCircle, RefreshCw,
  Wallet, MapPin, Banknote, Search, ArrowUpDown,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { MoneyInput } from '@/components/ui/money-input';
import { Textarea } from '@/components/ui/textarea';
import { EmptyState, StatusBadge } from './moduleAtoms';
import PageLayout, { DetailPanel } from './layout/PageLayout';
import { formatRupiah } from '@/lib/format';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DatePicker from '@/components/ui/date-picker';
import { Isian } from '@/components/ui/form-popup';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import CashAccountSelect, { usePaymentCashAccounts } from './SdmCashAccountSelect';
import { todayWIB } from '../../lib/waktu';

/* F13 (sesi #11) — inbox UANG yang tidak bisa disempitkan maupun dibawa keluar.
   Layar ini dulu hanya punya 3 tab jenis: TIDAK ADA kotak pencarian sama sekali,
   tidak ada tabel, tidak ada unduhan. Untuk inbox yang isinya bisa puluhan klaim,
   "cari klaim Pak Budi" berarti menggulir dengan mata; dan pertanyaan Keuangan
   "total yang menunggu dibayar bulan ini berapa?" tidak bisa dijawab tanpa
   menjumlah kartu satu per satu. */
const EXPENSE_VIEW_KEY = 'hr_expense_approval_view';
const SORT_COLS = [
  { key: 'ref_number', label: 'No. referensi' }, { key: 'type_label', label: 'Jenis' },
  { key: 'title', label: 'Judul' }, { key: 'employee_name', label: 'Karyawan' },
  { key: 'employee_dept', label: 'Departemen' }, { key: 'submitted_at', label: 'Diajukan' },
  { key: 'status', label: 'Status' }, { key: 'amount', label: 'Jumlah' },
];

const API = process.env.REACT_APP_BACKEND_URL || '';
const fmt = formatRupiah;
const fmtDate = (s) => s ? new Date(s).toLocaleDateString('id-ID', { day:'2-digit', month:'short', year:'numeric' }) : '—';

// 2026-11-05 (PANDUAN_UI G8): jenis = teks netral berikon; status = StatusBadge bersama (dulu pil warna palet langsung)
function TypeBadge({ type }) {
  if (type === 'expense_claim') return <span className="inline-flex items-center gap-1 text-xs text-muted-foreground whitespace-nowrap"><Wallet className="w-3 h-3" />Klaim biaya</span>;
  return <span className="inline-flex items-center gap-1 text-xs text-muted-foreground whitespace-nowrap"><MapPin className="w-3 h-3" />Perjalanan dinas</span>;
}

const EXP_STATUS = {
  submitted: { label: 'Menunggu persetujuan', tone: 'warning' },
  approved: { label: 'Disetujui · menunggu dicairkan', tone: 'info' },
  advance_paid: { label: 'Uang muka dibayar', tone: 'success' },
};

function ExpStatusBadge({ status }) {
  const c = EXP_STATUS[status];
  return <StatusBadge status={status} label={c?.label} tone={c?.tone} />;
}

// 2026-11-05 (PANDUAN_UI G13): klik baris membuka rincian + tindakannya DI HALAMAN (DetailPanel) — dulu popup.
function ActionPanel({ item, token, onClose, onRefresh }) {
  const [rejectReason, setRejectReason] = useState('');
  const [showReject, setShowReject] = useState(false);
  const [note, setNote] = useState('');
  const [advanceAmount, setAdvanceAmount] = useState('');
  const [loading, setLoading] = useState(false);
  // 2026-11-02 (P5 butir 7): rekening sumber + tanggal bayar (WIB) dikirim ke backend; dulu "Bayar"
  // hanya mengirim {payment_method:'transfer'} sehingga jurnal selalu dari 1-1201 bertanggal hari ini.
  const { accounts, loaded: accLoaded } = usePaymentCashAccounts(token, 'DA');  // Tahap 8: klaim staf DA
  const [payAccount, setPayAccount] = useState('');
  const [payDate, setPayDate] = useState(todayWIB());
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const isClaim = item.type === 'expense_claim';
  const baseUrl = isClaim ? `${API}/api/hr/expenses/claims/${item.id}` : `${API}/api/hr/expenses/travel/${item.id}`;

  const doAction = async (endpoint, body = {}) => {
    setLoading(true);
    try {
      const r = await fetch(`${baseUrl}/${endpoint}`, {
        method: 'POST', headers, body: JSON.stringify(body),
      });
      if (!r.ok) { const d = await r.json(); throw new Error(d.detail || 'Gagal'); }
      onRefresh(); onClose();
    } catch (e) { toast.error(e.message); }
    finally { setLoading(false); }
  };

  return (
    <DetailPanel
      title={`Proses ${isClaim ? 'klaim biaya' : 'perjalanan dinas'}`}
      description={`${item.ref_number || '—'} · ${item.employee_name || '—'}`}
      onClose={onClose}
      testId="expense-action-panel"
    >
      <div className="space-y-4">
        <div className="flex items-center gap-2 flex-wrap">
          <TypeBadge type={item.type} />
          <ExpStatusBadge status={item.status} />
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
          <div>
            <p className="text-xs text-muted-foreground">Karyawan</p>
            <p className="font-medium">{item.employee_name}</p>
            <p className="text-xs text-muted-foreground">{item.employee_dept}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">{isClaim ? 'Judul klaim' : 'Tujuan'}</p>
            <p className="font-medium">{item.title}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Total</p>
            <p className="text-lg font-bold tabular-nums whitespace-nowrap">{fmt(item.amount)}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Diajukan</p>
            <p className="whitespace-nowrap">{fmtDate(item.submitted_at)}</p>
          </div>
        </div>

        {/* Persetujuan */}
        {item.status === 'submitted' && (
          showReject ? (
            <div className="space-y-2 max-w-xl">
              <label className="text-sm font-medium">Alasan penolakan *</label>
              <Textarea
                placeholder="Jelaskan alasan penolakan…"
                value={rejectReason}
                onChange={e => setRejectReason(e.target.value)}
                rows={3}
              />
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={() => setShowReject(false)}>Batal</Button>
                <Button variant="destructive" size="sm"
                  disabled={!rejectReason.trim() || loading}
                  onClick={() => doAction('reject', { reason: rejectReason })}>
                  <XCircle className="w-3.5 h-3.5" />Konfirmasi tolak
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <Input
                placeholder="Catatan persetujuan (opsional)"
                value={note}
                onChange={e => setNote(e.target.value)}
                className="text-sm max-w-md"
              />
              <Button variant="destructive" onClick={() => setShowReject(true)} disabled={loading}>
                <XCircle className="w-3.5 h-3.5" />Tolak
              </Button>
              <Button variant="success" onClick={() => doAction('approve', { note, cash_advance_approved: item.cash_advance_requested ?? item.amount })} disabled={loading}>
                <CheckCircle className="w-3.5 h-3.5" />Setujui
              </Button>
            </div>
          )
        )}

        {/* Pencairan oleh Keuangan */}
        {item.status === 'approved' && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-xl" data-testid="expense-pay-source">
            <Isian label="Dibayar dari rekening" wajib>
              <CashAccountSelect accounts={accounts} loaded={accLoaded} value={payAccount} onChange={setPayAccount}
                testId="expense-pay-account" />
            </Isian>
            <Isian label="Tanggal bayar">
              <DatePicker value={payDate} onChange={(v) => setPayDate(v || todayWIB())} bolehKosong={false} testId="expense-pay-date" />
            </Isian>
          </div>
        )}
        {!isClaim && item.status === 'approved' && (
          <div className="space-y-2 max-w-xl">
            <p className="text-sm font-medium">Bayar uang muka perjalanan dinas</p>
            <div className="flex gap-2">
              <MoneyInput
                placeholder={`Jumlah (estimasi: ${fmt(item.amount)})`}
                value={advanceAmount}
                onChange={e => setAdvanceAmount(e.target.value)}
                className="text-sm"
              />
              <Button variant="success" className="whitespace-nowrap"
                onClick={() => doAction('advance-paid', { amount_paid: parseFloat(advanceAmount) || item.amount, bank_account_id: payAccount, payment_date: payDate })}
                disabled={loading || !payAccount}>
                <Banknote className="w-3.5 h-3.5" />Bayar
              </Button>
            </div>
          </div>
        )}

        {isClaim && item.status === 'approved' && (
          <div className="space-y-2">
            <p className="text-sm font-medium">Pencairan klaim biaya</p>
            <Button variant="success"
              onClick={() => doAction('disburse', { payment_method: 'transfer', bank_account_id: payAccount, payment_date: payDate })}
              disabled={loading || !payAccount}>
              <Banknote className="w-3.5 h-3.5" />Bayar & catat jurnal
            </Button>
          </div>
        )}
      </div>
    </DetailPanel>
  );
}

export default function EmployeeExpenseApprovalModule({ token, user }) {
  const [items, setItems] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('all'); // all | expense_claim | travel_request
  const [selected, setSelected] = useState(null);
  const [search, setSearch] = useState('');
  const [view, setView] = useState(() => {
    try { return localStorage.getItem(EXPENSE_VIEW_KEY) || 'table'; } catch { return 'table'; }
  });
  // Default: yang PALING BESAR di atas. Inbox persetujuan uang dibaca dari
  // risiko terbesar, bukan dari urutan masuk.
  const [sort, setSort] = useState({ key: 'amount', dir: 'desc' });
  useEffect(() => {
    try { localStorage.setItem(EXPENSE_VIEW_KEY, view); } catch { /* penyimpanan diblokir */ }
  }, [view]);
  const headers = { Authorization: `Bearer ${token}` };
  // 2026-11-08: pembayar klaim = kode peran Keuangan ATAU izin bayar (sama dengan server `is_claim_payer`).
  const isFinance = checkPerm({ user, roles: FINANCE_ROLES, keys: FINANCE_PAY_PERMS }); // FIN-02

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [pr, sr] = await Promise.all([
        fetch(`${API}/api/hr/expenses/pending-approval`, { headers }).then(r => r.json()),
        fetch(`${API}/api/hr/expenses/summary`, { headers }).then(r => r.json()),
      ]);
      let allItems = Array.isArray(pr.items) ? pr.items : [];
      if (filter !== 'all') allItems = allItems.filter(i => i.type === filter);

      // Also include approved expense claims for finance disburse
      if (isFinance) {
        const approvedClaims = await fetch(`${API}/api/hr/expenses/claims?status=approved`, { headers }).then(r => r.json());
        const existing = new Set(allItems.map(i => i.id));
        (approvedClaims.items || []).forEach(c => {
          if (!existing.has(c.id)) {
            allItems.push({
              id: c.id, type: 'expense_claim', type_label: 'Klaim Biaya',
              ref_number: c.claim_number, employee_name: c.employee_name,
              employee_dept: c.employee_dept, title: c.title,
              amount: c.total_amount, status: 'approved',
              submitted_at: c.submitted_at,
            });
          }
        });
      }

      setItems(allItems);
      setSummary(sr);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [token, filter, isFinance]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { fetchData(); }, [fetchData]);

  const totalPending = (summary?.expense_claims?.total_pending_approval || 0) + (summary?.travel_requests?.total_pending_approval || 0);
  const pendingAdvance = summary?.travel_requests?.pending_advance || 0;

  // Menyempitkan + mengurutkan di layar, lalu MENGUNDUH YANG TERLIHAT
  // (aturan `lib/csv.js` — jangan kueri ulang saat unduh).
  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    const list = (items || []).filter((it) => !q || [
      it.ref_number, it.employee_name, it.employee_dept, it.title,
    ].some((v) => String(v || '').toLowerCase().includes(q)));
    const { key, dir } = sort;
    list.sort((a, b) => {
      const av = a?.[key], bv = b?.[key];
      const num = key === 'amount';
      const cmp = num ? (Number(av || 0) - Number(bv || 0))
        : String(av ?? '').localeCompare(String(bv ?? ''), 'id');
      return dir === 'asc' ? cmp : -cmp;
    });
    return list;
  }, [items, search, sort]);
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(rows, 12);
  const toggleSort = (key) => setSort((s) => (
    s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'desc' }));
  const sumVisible = rows.reduce((s, r) => s + Number(r.amount || 0), 0);
  const KOLOM_UNDUH = [
    { label: 'No. referensi', nilai: (r) => r.ref_number },
    { label: 'Jenis', nilai: (r) => (r.type === 'expense_claim' ? 'Klaim biaya' : 'Perjalanan dinas') },
    { label: 'Judul', nilai: (r) => r.title },
    { label: 'Karyawan', nilai: (r) => r.employee_name },
    { label: 'Departemen', nilai: (r) => r.employee_dept || '' },
    { label: 'Diajukan', nilai: (r) => fmtDate(r.submitted_at) },
    { label: 'Status', nilai: (r) => EXP_STATUS[r.status]?.label || r.status },
    { label: 'Jumlah', nilai: (r) => Number(r.amount) || 0 },
  ];

  const openItem = (item) => setSelected((cur) => (cur?.id === item.id ? null : item));
  const empty = items.length === 0;

  // 2026-11-05 (PANDUAN_UI G1/G6/G10, owner): cetakan PageLayout. Tabel/Kartu = ViewToggle di kanan (dulu pil
  // seperti penyaring), "Unduh CSV" (dulu "CSV"), pil jenis tersembunyi bila semua 0, tampilan kosong di kartu tabel.
  return (
    <PageLayout
      testId="expense-approval-page"
      title="Persetujuan klaim & perjalanan dinas"
      subtitle="SDM menyetujui klaim karyawan; Keuangan mencairkan uangnya."
      filters={<>
        <FilterChips value={filter} onChange={setFilter} testId="expense-filter" ariaLabel="Jenis" hideWhenEmpty={filter === 'all'}
          options={[{ key: 'all', label: 'Semua', count: totalPending }, { key: 'expense_claim', label: 'Klaim biaya', count: summary?.expense_claims?.total_pending_approval || 0 },
            { key: 'travel_request', label: 'Perjalanan dinas', count: summary?.travel_requests?.total_pending_approval || 0 }]} />
        <div className="relative w-full sm:w-64">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <GlassInput value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Cari no. referensi / karyawan / judul…"
            data-testid="expense-search" aria-label="Cari"
            className="pl-9 h-9" />
        </div>
      </>}
      tools={<>
        <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={fetchData}>
          <RefreshCw className="w-4 h-4" />
        </Button>
        <TombolUnduh namaBerkas="persetujuan-klaim-dinas" namaLembar="Klaim & dinas" baris={rows} kolom={KOLOM_UNDUH}
          testId="expense-export-csv" />
        <ViewToggle value={view} onChange={setView} testId="expense-view" />
      </>}
      summary={!loading && !empty && (
        /* RC-IA-2a — pintu bersama SDM/Keuangan. 2026-11-04: 4 kartu hitungan → satu baris ringkas */
        <p className="text-sm text-muted-foreground" data-testid="expense-approval-summary">
          {totalPending} menunggu persetujuan
          {' · '}{pendingAdvance + (summary?.expense_claims?.counts?.approved || 0)} menunggu dicairkan Keuangan
          {' · '}<span data-testid="expense-visible-sum">{rows.length} terlihat, total <strong className="text-foreground tabular-nums">{fmt(sumVisible)}</strong></span>
        </p>
      )}
      detail={selected && (
        <ActionPanel key={selected.id} item={selected} token={token} onClose={() => setSelected(null)} onRefresh={fetchData} />
      )}
      footer={!loading && rows.length > 0 && (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />
      )}
    >
      {loading ? (
        <div className="flex items-center justify-center h-48">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[hsl(var(--primary))]" />
        </div>
      ) : (empty || rows.length === 0 || view === 'table') ? (
        <GlassCard className="p-0 overflow-hidden">
          {empty ? (
            <EmptyState icon={CheckCircle} title="Tidak ada yang perlu diproses"
              description="Semua klaim dan perjalanan dinas sudah diproses." />
          ) : rows.length === 0 ? (
            <EmptyState icon={Search} testId="expense-search-empty" title={`Tidak ada yang cocok dengan «${search}»`}
              description={`Kosongkan pencarian untuk melihat ${items.length} item lagi.`} />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full" data-testid="expense-table">
                <thead>
                  <tr className="text-left">
                    {SORT_COLS.map(({ key: k, label }) => (
                      <th key={k} className={`whitespace-nowrap ${k === 'amount' ? 'text-right' : ''}`}>
                        <Button type="button" variant="ghost" size="sm" onClick={() => toggleSort(k)}
                          data-testid={`expense-sort-${k}`} title={`Urutkan menurut ${label.toLowerCase()}`}
                          className="h-auto p-0 font-semibold text-muted-foreground hover:bg-transparent hover:text-primary">
                          {label}
                          <ArrowUpDown size={12}
                            className={sort.key === k ? 'text-primary' : 'opacity-40'} />
                        </Button>
                      </th>
                    ))}
                    <th className="text-right">Tindakan</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {paged.map((item) => (
                    <tr key={item.id} className={`cursor-pointer hover:bg-muted/40 ${selected?.id === item.id ? 'bg-[hsl(var(--primary)/0.06)]' : ''}`}
                      onClick={() => openItem(item)}
                      data-testid={`expense-row-${item.ref_number}`}>
                      <td className="whitespace-nowrap">{item.ref_number}</td>
                      <td><TypeBadge type={item.type} /></td>
                      <td className="max-w-[18rem] truncate" title={item.title}>{item.title}</td>
                      <td className="font-medium whitespace-nowrap">{item.employee_name}</td>
                      <td className="text-muted-foreground whitespace-nowrap">{item.employee_dept || '—'}</td>
                      <td className="whitespace-nowrap">{fmtDate(item.submitted_at)}</td>
                      <td><ExpStatusBadge status={item.status} /></td>
                      <td className="text-right tabular-nums font-semibold whitespace-nowrap">{fmt(item.amount)}</td>
                      <td className="text-right whitespace-nowrap">
                        {item.status === 'submitted' && (
                          <Button size="sm" variant="outline"
                            onClick={(e) => { e.stopPropagation(); setSelected(item); }}>
                            Proses
                          </Button>
                        )}
                        {(item.status === 'approved' && isFinance) && (
                          <Button size="sm" variant="outline"
                            onClick={(e) => { e.stopPropagation(); setSelected(item); }}>
                            <Banknote className="w-3 h-3" />Bayar
                          </Button>
                        )}
                        {!(item.status === 'submitted' || (item.status === 'approved' && isFinance)) && (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassCard>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {paged.map(item => (
            <GlassCard key={item.id}
              className={`p-4 cursor-pointer ${selected?.id === item.id ? 'border-[hsl(var(--primary)/0.45)]' : ''}`}
              onClick={() => openItem(item)}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <TypeBadge type={item.type} />
                    <ExpStatusBadge status={item.status} />
                  </div>
                  <p className="font-medium mt-1">{item.title}</p>
                  <p className="text-sm text-muted-foreground">
                    {item.employee_name} · {item.employee_dept} · {fmtDate(item.submitted_at)}
                  </p>
                </div>
                <div className="text-right shrink-0">
                  <p className="text-lg font-bold tabular-nums whitespace-nowrap">{fmt(item.amount)}</p>
                  <p className="text-xs text-muted-foreground whitespace-nowrap">{item.ref_number}</p>
                </div>
              </div>
              <div className="mt-3 flex gap-2 justify-end">
                {item.status === 'submitted' && (
                  <>
                    <Button size="sm" variant="outline"
                      onClick={e => { e.stopPropagation(); setSelected(item); }}>
                      <XCircle className="w-3.5 h-3.5" />Tolak
                    </Button>
                    <Button size="sm" variant="outline"
                      onClick={e => { e.stopPropagation(); setSelected(item); }}>
                      <CheckCircle className="w-3.5 h-3.5" />Setujui
                    </Button>
                  </>
                )}
                {(item.status === 'approved' && isFinance) && (
                  <Button size="sm" variant="outline"
                    onClick={e => { e.stopPropagation(); setSelected(item); }}>
                    <Banknote className="w-3.5 h-3.5" />Proses pembayaran
                  </Button>
                )}
              </div>
            </GlassCard>
          ))}
        </div>
      )}
    </PageLayout>
  );
}

/**
 * FinanceKasbonModule — Finance Portal: Pencairan & Monitoring Kasbon/Pinjaman
 * Finance proses pencairan setelah HR approve, catat pembayaran, monitoring outstanding.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import FilterChips from '@/components/ui/filter-chips';
import ViewToggle from '@/components/ui/view-toggle';
import { toast } from 'sonner';
import {
  RefreshCw, Search, FileText, ArrowUpDown,
} from 'lucide-react';
import { formatRupiah } from '@/lib/format';
import { Button } from '@/components/ui/button';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Textarea } from '@/components/ui/textarea';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { MoneyInput } from '@/components/ui/money-input';
import ExportCsvButton from '@/components/ui/export-csv-button';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import CashAccountSelect, { usePaymentCashAccounts } from './SdmCashAccountSelect';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { monthOptions } from './finance/PeriodPicker';
import { todayWIB } from '../../lib/waktu';
import { EmptyState, StatusBadge as AtomStatusBadge } from './moduleAtoms';
import PageLayout from './layout/PageLayout';

/* F13 (sesi #11) — layar UANG yang tidak bisa dibawa ke rapat.
   Kasbon & pinjaman karyawan dulu hanya bisa dibaca sebagai KARTU: tidak ada
   tabel, tidak ada urutan, tidak ada unduhan. Akibatnya pertanyaan paling wajar
   dari Keuangan — "siapa saja yang masih punya sisa, urut dari yang terbesar?" —
   dijawab dengan menggulir 200 kartu lalu MENGETIK ULANG angkanya ke Excel
   (sumber salah-ketik paling umum). Angka yang benar di layar tetapi tidak bisa
   dibawa keluar sama saja dengan tidak punya angka. */
const KASBON_VIEW_KEY = 'finance_kasbon_view';
const SORT_COLS = [
  { key: 'request_number', label: 'No. pengajuan' }, { key: 'employee_name', label: 'Karyawan' },
  { key: 'department', label: 'Departemen' }, { key: 'type_label', label: 'Jenis' },
  { key: 'purpose', label: 'Keperluan' }, { key: 'status', label: 'Status' },
  { key: 'amount', label: 'Jumlah', num: true }, { key: 'paid_amount', label: 'Terbayar', num: true },
  { key: 'outstanding_balance', label: 'Sisa', num: true },
  { key: 'installment_amount', label: 'Cicilan/bulan', num: true },
  { key: 'deduction_start_period', label: 'Mulai potong' },
];
const CSV_HEAD = ['No. Pengajuan', 'Karyawan', 'Departemen', 'Jenis', 'Keperluan',
  'Status', 'Jumlah', 'Terbayar', 'Sisa', 'Cicilan/bulan', 'Jml cicilan',
  'Mulai potong'];

const API = process.env.REACT_APP_BACKEND_URL;
const authH = () => ({ Authorization: `Bearer ${localStorage.getItem('erp_token')}`, 'Content-Type': 'application/json' });
const fmt = formatRupiah;
// periode potong gaji 'YYYY-MM' → "Nov 2026" (PANDUAN_UI G7: bukan tanggal mentah)
const fmtPeriod = (ym) => {
  if (!/^\d{4}-\d{2}$/.test(ym || '')) return ym || '—';
  const [y, m] = ym.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString('id-ID', { month: 'short', year: 'numeric', timeZone: 'UTC' });
};

// 2026-11-05 (PANDUAN_UI G8): status memakai StatusBadge bersama + nada token (dulu palet warna langsung)
const STATUS_CFG = {
  submitted:   { label: 'Menunggu HR',    tone: 'muted' },
  hr_approved: { label: 'Siap dicairkan', tone: 'warning' },
  disbursed:   { label: 'Aktif',          tone: 'info' },
  paid_off:    { label: 'Lunas',          tone: 'success' },
  hr_rejected: { label: 'Ditolak HR',     tone: 'danger' },
  cancelled:   { label: 'Dibatalkan',     tone: 'muted' },
};

function StatusBadge({ status }) {
  const cfg = STATUS_CFG[status] || STATUS_CFG.submitted;
  return <AtomStatusBadge status={status} label={cfg.label} tone={cfg.tone} />;
}

// bulan mulai potong: 12 bulan ke depan s.d. 2 bulan lalu (terbaru di atas)
const DEDUCTION_MONTHS = monthOptions(3, 12);

// ─── Disburse Modal ───────────────────────────────────────────────────────────
function DisburseModal({ req, onClose, onDone }) {
  // 2026-11-02 (P5 butir 7): tanggal bawaan WIB; rekening sumber WAJIB dipilih dari rekening kas/bank
  // aktif (dulu tidak ada pilihan → jurnal selalu Cr 1-1201 bertanggal hari ini).
  const today = todayWIB();
  const { accounts, loaded } = usePaymentCashAccounts(undefined, 'DA');  // Tahap 8: kasbon = uang staf DA
  const [form, setForm] = useState({ disbursement_date: today, deduction_start_period: today.slice(0, 7), finance_notes: '', cash_account_id: '' });
  const [saving, setSaving] = useState(false);

  const handleSubmit = async () => {
    if (!form.cash_account_id) { toast.error('Pilih rekening sumber pencairan'); return; }
    setSaving(true);
    try {
      const r = await fetch(`${API}/api/dewi/kasbon/requests/${req.id}/disburse`, {
        method: 'PATCH', headers: authH(), body: JSON.stringify(form),
      });
      const d = await r.json();
      if (d.ok) { toast.success('Kasbon berhasil dicairkan'); onDone(); }
      else if (d.request) { toast.warning(d.message || 'Kasbon dicairkan, jurnal GL gagal', { duration: 8000 }); onDone(); }
      else toast.error(d.detail?.message || d.detail || 'Gagal');
    } catch (_e) { toast.error('Terjadi kesalahan'); }
    finally { setSaving(false); }
  };

  // 2026-11-05 (PANDUAN_UI G3/G9): formulir pendek = Dialog aplikasi + Button (dulu lapisan & tombol buatan sendiri)
  return (
    <Dialog open onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-md" data-testid="kasbon-disburse-dialog">
        <DialogHeader>
          <DialogTitle>Proses pencairan</DialogTitle>
          <DialogDescription>{req.request_number} · {req.employee_name}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="p-3 rounded-[var(--radius-md)] bg-[var(--glass-bg)] space-y-1 text-xs">
            <div className="flex justify-between"><span className="text-muted-foreground">Karyawan</span><strong>{req.employee_name}</strong></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Jenis</span><span>{req.type_label}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Jumlah</span><strong className="text-foreground text-sm tabular-nums">{fmt(req.amount)}</strong></div>
            {req.installment_count > 1 && <div className="flex justify-between"><span className="text-muted-foreground">Cicilan</span><span className="tabular-nums">{req.installment_count}x × {fmt(req.installment_amount)}/bulan</span></div>}
            <div className="flex justify-between"><span className="text-muted-foreground">Keperluan</span><span>{req.purpose}</span></div>
          </div>

          <div>
            <label className="text-xs font-medium text-muted-foreground block mb-1" htmlFor="kasbon-disburse-date">Tanggal pencairan</label>
            <GlassInput id="kasbon-disburse-date" type="date" value={form.disbursement_date} onChange={e => setForm(p => ({...p, disbursement_date: e.target.value}))}
              className="h-9" />
            <p className="text-xs text-muted-foreground mt-1">Tanggal ini menjadi tanggal jurnal.</p>
          </div>

          <div>
            <label className="text-xs font-medium text-muted-foreground block mb-1">Dicairkan dari rekening</label>
            <CashAccountSelect accounts={accounts} loaded={loaded} value={form.cash_account_id}
              onChange={v => setForm(p => ({...p, cash_account_id: v}))} testId="kasbon-disburse-account" />
          </div>

          <div>
            <label className="text-xs font-medium text-muted-foreground block mb-1">Mulai potongan gaji (bulan)</label>
            {/* 2026-11-07 (audit form Tahap 5, PANDUAN_UI G6): pilihan bulan berlabel — dulu input type="month" polos */}
            <SmartNativeSelect value={form.deduction_start_period} onChange={e => setForm(p => ({...p, deduction_start_period: e.target.value}))}
              searchable={false} className="h-9 w-full" aria-label="Mulai potongan gaji" data-testid="kasbon-deduction-start">
              {DEDUCTION_MONTHS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </SmartNativeSelect>
            <p className="text-xs text-muted-foreground mt-1">Potongan gaji mulai bulan ini.</p>
          </div>

          <div>
            <label className="text-xs font-medium text-muted-foreground block mb-1" htmlFor="kasbon-finance-notes">Catatan Keuangan</label>
            <Textarea id="kasbon-finance-notes" value={form.finance_notes} onChange={e => setForm(p => ({...p, finance_notes: e.target.value}))}
              placeholder="Nomor transfer, cara pencairan, dll."
              className="h-16 resize-none" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Batal</Button>
          <Button onClick={handleSubmit} disabled={saving || !form.cash_account_id} data-testid="kasbon-disburse-save">
            {saving ? 'Memproses…' : 'Cairkan sekarang'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── Repay Modal ──────────────────────────────────────────────────────────────
function RepayModal({ req, onClose, onDone }) {
  // 2026-11-02 (P5 butir 5): pilihan "Potong Gaji" DIHAPUS — dulu langsung melunasi kasbon lalu payroll
  // melewati potongannya (gaji dibayar penuh, uang kasbon hilang). Potongan gaji kini HANYA tercatat
  // otomatis saat run payroll difinalisasi; form ini khusus pembayaran uang nyata ke rekening yang dipilih.
  const today = todayWIB();
  const { accounts, loaded } = usePaymentCashAccounts(undefined, 'DA');  // Tahap 8: kasbon = uang staf DA
  const suggested = req.type === 'kasbon' ? req.outstanding_balance : req.installment_amount;
  const [form, setForm] = useState({ amount: String(suggested || ''), method: 'manual', date: today, notes: '', cash_account_id: '' });
  const [saving, setSaving] = useState(false);

  const handleSubmit = async () => {
    if (!form.amount || Number(form.amount) <= 0) { toast.error('Jumlah harus > 0'); return; }
    if (!form.cash_account_id) { toast.error('Pilih rekening penerima pembayaran'); return; }
    setSaving(true);
    try {
      const r = await fetch(`${API}/api/dewi/kasbon/requests/${req.id}/repay`, {
        method: 'POST', headers: authH(),
        body: JSON.stringify({ ...form, amount: Number(form.amount) }),
      });
      const d = await r.json();
      if (d.ok) { toast.success('Pembayaran berhasil dicatat'); onDone(); }
      else if (d.repayment) { toast.warning(d.message || 'Angsuran dicatat, jurnal GL gagal', { duration: 8000 }); onDone(); }
      else toast.error(d.detail?.message || d.detail || 'Gagal');
    } catch (_e) { toast.error('Terjadi kesalahan'); }
    finally { setSaving(false); }
  };

  return (
    <Dialog open onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-md" data-testid="kasbon-repay-dialog">
        <DialogHeader>
          <DialogTitle>Catat pembayaran</DialogTitle>
          <DialogDescription>{req.request_number} · {req.employee_name}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="p-3 rounded-[var(--radius-md)] bg-[var(--glass-bg)] text-xs space-y-1">
            <div className="flex justify-between"><span className="text-muted-foreground">Karyawan</span><strong>{req.employee_name}</strong></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Sisa pinjaman</span><strong className="text-[hsl(var(--warning))] tabular-nums">{fmt(req.outstanding_balance)}</strong></div>
            {req.installment_amount > 0 && <div className="flex justify-between"><span className="text-muted-foreground">Cicilan bulanan</span><span className="tabular-nums">{fmt(req.installment_amount)}</span></div>}
          </div>

          <p className="text-xs text-muted-foreground" data-testid="repay-payroll-note">
            Bayar manual (tunai/transfer) oleh karyawan. Potongan gaji tidak dicatat di sini — tercatat
            otomatis saat penggajian periode {req.deduction_start_period ? fmtPeriod(req.deduction_start_period) : 'berjalan'} difinalisasi.
          </p>

          <div>
            <label className="text-xs font-medium text-muted-foreground block mb-1">Jumlah pembayaran</label>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">Rp</span>
              <MoneyInput unstyled value={form.amount} onChange={e => setForm(p => ({...p, amount: e.target.value}))}
                className="w-full h-9 pl-10 pr-3 rounded-[var(--radius-sm)] border border-[var(--glass-border)] bg-[var(--input-surface)] text-sm" />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-muted-foreground block mb-1" htmlFor="kasbon-repay-date">Tanggal bayar</label>
              <GlassInput id="kasbon-repay-date" type="date" value={form.date} onChange={e => setForm(p => ({...p, date: e.target.value}))}
                className="h-9" />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground block mb-1">Diterima di rekening</label>
              <CashAccountSelect accounts={accounts} loaded={loaded} value={form.cash_account_id}
                onChange={v => setForm(p => ({...p, cash_account_id: v}))} testId="kasbon-repay-account" />
            </div>
          </div>

          <div>
            <label className="text-xs font-medium text-muted-foreground block mb-1" htmlFor="kasbon-repay-notes">Catatan</label>
            <GlassInput id="kasbon-repay-notes" value={form.notes} onChange={e => setForm(p => ({...p, notes: e.target.value}))}
              placeholder="Referensi pembayaran, dll."
              className="h-9" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Batal</Button>
          <Button onClick={handleSubmit} disabled={saving || !form.amount || !form.cash_account_id} data-testid="kasbon-repay-save">
            {saving ? 'Menyimpan…' : 'Catat pembayaran'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── Active Kasbon Row ─────────────────────────────────────────────────────────
function ActiveRow({ req, onRepay, onDisburse }) {
  const pct = req.amount > 0 ? Math.min(100, Math.round((req.paid_amount / req.amount) * 100)) : 0;

  return (
    <GlassCard className="p-4">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-0.5">
            <span className="text-xs text-muted-foreground whitespace-nowrap">{req.request_number}</span>
            <span className="text-xs text-muted-foreground">· {req.type_label}</span>
            <StatusBadge status={req.status} />
          </div>
          <p className="text-sm font-semibold text-foreground">{req.employee_name}</p>
          <p className="text-xs text-muted-foreground">{req.department} · {req.purpose}</p>
        </div>
        <div className="text-right shrink-0">
          <p className="text-sm font-bold text-foreground tabular-nums whitespace-nowrap">{fmt(req.amount)}</p>
          <p className="text-xs text-[hsl(var(--warning))] font-medium tabular-nums whitespace-nowrap">Sisa: {fmt(req.outstanding_balance)}</p>
        </div>
      </div>

      {req.status === 'disbursed' && (
        <>
          <div className="space-y-1 mb-3">
            <div className="flex justify-between text-xs text-muted-foreground">
              <span className="tabular-nums">Terbayar: {fmt(req.paid_amount)}</span><span className="tabular-nums">{pct}%</span>
            </div>
            <div className="h-1.5 rounded-full bg-[var(--glass-bg)] overflow-hidden">
              <div className="h-full rounded-full bg-[hsl(var(--success))] transition-all" style={{ width: `${pct}%` }} />
            </div>
          </div>
          <div className="flex justify-between text-xs text-muted-foreground mb-3">
            <span>Mulai potong: {fmtPeriod(req.deduction_start_period)}</span>
            {req.installment_count > 1 && <span className="tabular-nums">Cicilan: {fmt(req.installment_amount)}/bulan</span>}
          </div>
          <Button variant="outline" size="sm" className="w-full" onClick={() => onRepay(req)} data-testid={`repay-btn-${req.id}`}>
            Catat pembayaran
          </Button>
        </>
      )}

      {req.status === 'hr_approved' && (
        <Button variant="outline" size="sm" className="w-full mt-1" onClick={() => onDisburse(req)} data-testid={`disburse-btn-${req.id}`}>
          Proses pencairan
        </Button>
      )}
    </GlassCard>
  );
}

// ─── Main Module ──────────────────────────────────────────────────────────────
export default function FinanceKasbonModule() {
  const [requests, setRequests] = useState([]);
  const [stats, setStats] = useState({});
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('pending');
  const [search, setSearch] = useState('');
  const [disburseReq, setDisburseReq] = useState(null);
  const [repayReq, setRepayReq] = useState(null);
  const [view, setView] = useState(() => {
    try { return localStorage.getItem(KASBON_VIEW_KEY) || 'table'; } catch { return 'table'; }
  });
  // Urutan default: SISA terbesar di atas. Itu pertanyaan pertama Keuangan
  // ("siapa yang paling besar utangnya"), jadi tidak boleh perlu diklik dulu.
  const [sort, setSort] = useState({ key: 'outstanding_balance', dir: 'desc' });
  useEffect(() => {
    try { localStorage.setItem(KASBON_VIEW_KEY, view); } catch { /* penyimpanan diblokir */ }
  }, [view]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // 2026-11-04: dulu `limit=200` — pengajuan ke-201 dst. tidak pernah tampil. Sekarang semua halaman dimuat.
      const rStats = fetch(`${API}/api/dewi/kasbon/stats`, { headers: authH() }).then(r => r.json());
      const all = [];
      for (let page = 1; page <= 50; page += 1) {
        const d = await fetch(`${API}/api/dewi/kasbon/requests?limit=500&page=${page}`, { headers: authH() }).then(r => r.json());
        if (!d.ok) break;
        all.push(...(d.requests || []));
        if (all.length >= (d.total || 0) || !(d.requests || []).length) break;
      }
      setRequests(all);
      const dStats = await rStats;
      if (dStats.ok) setStats(dStats.stats || {});
    } catch (_e) { /* ignore */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const inTab = (r, t) => (t === 'pending' ? r.status === 'hr_approved'
    : t === 'active' ? r.status === 'disbursed'
    : t === 'done' ? ['paid_off', 'hr_rejected', 'cancelled'].includes(r.status)
    : true);
  // 2026-11-05 (owner): semua pil berangka — dihitung dari daftar yang sama dengan isi tabel (dulu "Selesai" &
  // "Semua" tanpa angka, dua lainnya dari ringkasan server).
  const tabCount = (t) => requests.filter((r) => inTab(r, t)).length;
  const filtered = requests.filter(r => {
    const matchTab = inTab(r, tab);
    const q = search.toLowerCase();
    const matchQ = !q || r.employee_name?.toLowerCase().includes(q) || r.request_number?.toLowerCase().includes(q);
    return matchTab && matchQ;
  });

  // Yang diurutkan = yang TERLIHAT, dan yang diunduh = yang terlihat juga
  // (aturan `lib/csv.js`). Kueri ulang saat unduh melahirkan berkas yang tidak
  // sama dengan layar — dan yang dipercaya biasanya justru yang salah.
  const rows = useMemo(() => {
    const list = [...filtered];
    const { key, dir } = sort;
    list.sort((a, b) => {
      const av = a?.[key], bv = b?.[key];
      const num = typeof av === 'number' || typeof bv === 'number';
      const cmp = num ? (Number(av || 0) - Number(bv || 0))
        : String(av ?? '').localeCompare(String(bv ?? ''), 'id');
      return dir === 'asc' ? cmp : -cmp;
    });
    return list;
  }, [filtered, sort]);
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(rows, 12);
  const toggleSort = (key) => setSort((s) => (
    s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'desc' }));
  const csvRows = rows.map((r) => [
    r.request_number, r.employee_name, r.department, r.type_label, r.purpose,
    STATUS_CFG[r.status]?.label || r.status, r.amount ?? 0, r.paid_amount ?? 0,
    r.outstanding_balance ?? 0, r.installment_amount ?? 0, r.installment_count ?? 0,
    r.deduction_start_period || '',
  ]);

  // 2026-11-05 (PANDUAN_UI G1/G6/G10, owner): cetakan PageLayout. Tabel/Kartu = ViewToggle di kanan (dulu pil
  // seperti penyaring), "Unduh CSV" (dulu "CSV"), tampilan kosong di kartu tabel, tombol muat ulang standar.
  return (
    <PageLayout
      testId="finance-kasbon-page"
      title="Kasbon & pinjaman"
      subtitle="Pencairan setelah disetujui HR dan pemantauan sisa pinjaman."
      filters={<>
        <FilterChips value={tab} onChange={setTab} testId="kasbon-tab" ariaLabel="Status kasbon"
          options={[{ key: 'pending', label: 'Siap dicairkan', count: tabCount('pending') }, { key: 'active', label: 'Aktif', count: tabCount('active') },
            { key: 'done', label: 'Selesai', count: tabCount('done') }, { key: 'all', label: 'Semua', count: requests.length }]} />
        <div className="relative w-72 max-w-full">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <GlassInput value={search} onChange={e => setSearch(e.target.value)} placeholder="Cari karyawan / no. pengajuan…"
            data-testid="kasbon-search" aria-label="Cari"
            className="h-9 pl-9" />
        </div>
      </>}
      tools={<>
        <Button variant="outline" size="icon" onClick={load} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className="w-4 h-4" />
        </Button>
        <ExportCsvButton filename="kasbon-pinjaman-karyawan" testId="kasbon-export-csv"
          head={CSV_HEAD} rows={csvRows} label="Unduh CSV" size="default" className=""
          note={`Rp ${(rows.reduce((s, r) => s + Number(r.outstanding_balance || 0), 0)).toLocaleString('id-ID')} sisa`} />
        <ViewToggle value={view} onChange={setView} testId="kasbon-view" />
      </>}
      summary={
        <p className="text-sm text-muted-foreground" data-testid="kasbon-summary">
          Sisa kasbon aktif <strong className="text-foreground tabular-nums">{fmt(stats.total_outstanding || 0)}</strong>
          {' · '}{stats.active_employees ?? 0} karyawan
          {(stats.pending_hr || 0) > 0 && <> · {stats.pending_hr} menunggu HR</>}
        </p>
      }
      footer={!loading && rows.length > 0 && (
        <PaginationLite page={page} totalPages={totalPages} total={total}
          pageSize={pageSize} onPageChange={setPage} />
      )}
    >
      {loading ? (
        <div className="space-y-3">{[1,2,3].map(i => <div key={i} className="h-28 rounded-[var(--radius-lg)] bg-[var(--glass-bg)] animate-pulse" />)}</div>
      ) : (filtered.length === 0 || view === 'table') ? (
        <GlassCard className="p-0 overflow-hidden">
          {filtered.length === 0 ? (
            <EmptyState icon={FileText} testId="kasbon-empty"
              title={search ? 'Tidak ada kasbon yang cocok'
                : tab === 'pending' ? 'Tidak ada pengajuan yang perlu dicairkan'
                : tab === 'active' ? 'Tidak ada kasbon aktif'
                : 'Belum ada kasbon di sini'}
              description={search ? 'Ubah atau kosongkan pencarian.' : 'Pengajuan muncul di sini setelah disetujui HR.'} />
          ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs" data-testid="kasbon-table">
              <thead className="bg-[var(--glass-bg)]">
                <tr className="text-left">
                  {SORT_COLS.map(({ key: k, label, num }) => (
                    <th key={k} className={`px-2.5 py-2 font-semibold whitespace-nowrap ${num ? 'text-right' : ''}`}>
                      <button type="button" onClick={() => toggleSort(k)}
                        data-testid={`kasbon-sort-${k}`}
                        className="inline-flex items-center gap-1 uppercase hover:text-primary">
                        {label}
                        <ArrowUpDown size={10}
                          className={sort.key === k ? 'text-primary' : 'opacity-40'} />
                      </button>
                    </th>
                  ))}
                  <th className="px-2.5 py-2 font-semibold text-right">Tindakan</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--glass-border)]">
                {paged.map((r) => (
                  <tr key={r.id} className="hover:bg-[var(--glass-bg)]"
                    data-testid={`kasbon-row-${r.request_number}`}>
                    <td className="px-2.5 py-2 whitespace-nowrap">{r.request_number}</td>
                    <td className="px-2.5 py-2 font-medium">{r.employee_name}</td>
                    <td className="px-2.5 py-2 text-muted-foreground">{r.department || '—'}</td>
                    <td className="px-2.5 py-2">{r.type_label}</td>
                    <td className="px-2.5 py-2 text-muted-foreground max-w-[16rem] truncate"
                      title={r.purpose}>{r.purpose || '—'}</td>
                    <td className="px-2.5 py-2"><StatusBadge status={r.status} /></td>
                    <td className="px-2.5 py-2 text-right tabular-nums font-semibold whitespace-nowrap">{fmt(r.amount)}</td>
                    <td className="px-2.5 py-2 text-right tabular-nums whitespace-nowrap">{fmt(r.paid_amount)}</td>
                    <td className="px-2.5 py-2 text-right tabular-nums font-semibold whitespace-nowrap text-[hsl(var(--warning))]">
                      {fmt(r.outstanding_balance)}
                    </td>
                    <td className="px-2.5 py-2 text-right tabular-nums whitespace-nowrap">
                      {r.installment_count > 1
                        ? `${fmt(r.installment_amount)} × ${r.installment_count}`
                        : '—'}
                    </td>
                    <td className="px-2.5 py-2 whitespace-nowrap">{fmtPeriod(r.deduction_start_period)}</td>
                    <td className="px-2.5 py-2 text-right whitespace-nowrap">
                      {r.status === 'hr_approved' && (
                        <Button variant="outline" size="sm" onClick={() => setDisburseReq(r)} data-testid={`disburse-btn-${r.id}`}>
                          Cairkan
                        </Button>
                      )}
                      {r.status === 'disbursed' && (
                        <Button variant="outline" size="sm" onClick={() => setRepayReq(r)} data-testid={`repay-btn-${r.id}`}>
                          Catat bayar
                        </Button>
                      )}
                      {!['hr_approved', 'disbursed'].includes(r.status) && (
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
          {paged.map(req => (
            <ActiveRow key={req.id} req={req} onDisburse={setDisburseReq} onRepay={setRepayReq} />
          ))}
        </div>
      )}

      {disburseReq && <DisburseModal req={disburseReq} onClose={() => setDisburseReq(null)} onDone={() => { setDisburseReq(null); load(); }} />}
      {repayReq && <RepayModal req={repayReq} onClose={() => setRepayReq(null)} onDone={() => { setRepayReq(null); load(); }} />}
    </PageLayout>
  );
}

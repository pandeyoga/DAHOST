import { useState, useEffect, useCallback, useReducer, useMemo } from 'react';
import { Plus, RefreshCw, Download, Eye, Lock, Calendar, DollarSign, AlertTriangle, CheckCircle, ShieldAlert, Copy, FileText, FilesIcon, BookOpen, ExternalLink, AlertCircle, X, CreditCard, RotateCcw } from 'lucide-react';
import OnwardCTA from './OnwardCTA';
import { GlassCard, GlassPanel, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { PageHeader, StatusBadge } from './moduleAtoms';
import { toast } from 'sonner';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatRupiah } from '@/lib/format';
import CashAccountSelect, { usePaymentCashAccounts } from './SdmCashAccountSelect';
import { todayWIB, lastMonthPeriodWIB } from '../../lib/waktu';
import { MoneyInput } from '@/components/ui/money-input';
import { confirmDialog } from '@/components/ui/confirm-dialog';

// 2026-11-02 (K22): BPJS dibayar per LEMBAGA (karyawan + iuran perusahaan yang sudah dijurnal).
const BPJS_AGENCIES = [['kes', 'BPJS Kesehatan'], ['tk', 'BPJS Ketenagakerjaan']];
const bpjsDue = (run, agency) => {
  const b = (run.bpjs_breakdown || {})[agency];
  return b ? Number(b.employee || 0) + Number(b.employer || 0) : null;
};
const bpjsPaid = (run, agency) => (run.bpjs_payments || {})[agency]?.status === 'paid';

const fmtIDR = formatRupiah;

const _PR_INIT = { runs: [], loading: true };
function _prReducer(s, a) {
  if (a.type === 'loaded') return { ...s, runs: a.runs, loading: false };
  if (a.type === 'loading') return { ...s, loading: true };
  return s;
}

/** GL Posting Status Badge */
function GLStatusBadge({ run, onNavigate }) {
  if (!run.gl_je_number && !run.post_error) {
    if (run.status !== 'finalized') return null;
    return <span className="text-[10px] text-muted-foreground italic">Belum diposting</span>;
  }
  return (
    <div className="flex flex-col gap-1">
      {/* Finalize JE */}
      {run.gl_je_number && (
        <span
          className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded font-medium bg-emerald-100 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-400 dark:border-emerald-500/30 cursor-pointer hover:bg-emerald-100 dark:bg-emerald-500/20"
          title={`Journal Entry Finalisasi: ${run.gl_je_number}`}
          onClick={() => onNavigate && onNavigate('fin-journal-list')}
          data-testid={`gl-badge-${run.run_number}`}
        >
          <BookOpen size={9} /> {run.gl_je_number}
        </span>
      )}
      {/* Payment JE */}
      {run.payment_gl_je_number && (
        <span
          className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded font-medium bg-blue-100 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-400 dark:border-blue-500/30 cursor-pointer hover:bg-blue-100 dark:bg-blue-500/20"
          title={`Journal Entry Pembayaran: ${run.payment_gl_je_number}`}
          onClick={() => onNavigate && onNavigate('fin-journal-list')}
          data-testid={`pay-je-badge-${run.run_number}`}
        >
          💸 {run.payment_gl_je_number}
        </span>
      )}
      {run.post_error && !run.gl_je_number && (
        <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded font-medium bg-red-100 dark:bg-red-500/10 text-red-700 dark:text-red-400 border border-red-400 dark:border-red-500/30" title={run.post_error}>
          <AlertCircle size={9} /> Error GL
        </span>
      )}
    </div>
  );
}

/* 2026-11-02 (P5 butir 7): daftar rekening bayar gaji kini dari rekening kas/bank AKTIF yang nyata
   (usePaymentCashAccounts) — daftar hard-code lama memuat "Bank Umum (1-1200)" = akun header
   (jurnal ditolak) dan tidak memuat 15 rekening lain (BRI, GoPay, dll.). */

/* Periode bulan lalu {from, to} menurut tanggal WIB = `lastMonthPeriodWIB()` (lib/waktu).
   2026-11-02 (P5 butir 11): dulu tanggal lokal dibuat lalu diformat `toISOString()` (UTC) → di browser
   WIB tanggal mundur sehari: tombol pada 1 Nov menghasilkan 30 Sep → 31 Okt (32 hari) dan kasbon
   periode Okt tidak terpotong. Helper lokal dihapus; SSOT tanggal ada di lib/waktu. */

/* Pesan galat backend (FastAPI `detail`) — supaya penolakan run ganda / jurnal gagal terbaca jelas. */
async function errDetail(r, fallback) {
  try { const d = await r.json(); return (typeof d.detail === 'string' ? d.detail : d.detail?.message) || fallback; }
  catch { return fallback; }
}

const API_BASE = process.env.REACT_APP_BACKEND_URL || '';

/** Download a file from a URL with auth token (triggers native browser download).
 *  URL relatif otomatis diberi REACT_APP_BACKEND_URL (aturan environment repo). */
async function downloadWithAuth(url, token, filename) {
  const full = url.startsWith('http') ? url : `${API_BASE}${url}`;
  const r = await fetch(full, { headers: { Authorization: `Bearer ${token}` } });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const blob = await r.blob();
  const href = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = href; a.download = filename; a.click();
  URL.revokeObjectURL(href);
}

export default function RahazaPayrollRunModule({ token, onNavigate }) {
  const [{ runs, loading }, dispatch] = useReducer(_prReducer, _PR_INIT);
  const [creating, setCreating] = useState(false);
  const [createInitial, setCreateInitial] = useState(null);
  const [viewing, setViewing] = useState(null);
  const [error, setError] = useState('');
  const [payDialog, setPayDialog] = useState(null);
  const [payForm, setPayForm] = useState({
    payment_date: todayWIB(),
    bank_account_code: '',
    payment_method: 'bank_transfer',
    notes: '',
    override_reason: '',
  });
  const [paying, setPaying] = useState(false);
  // 2026-11-02 (K22): dialog Bayar BPJS/PPh21 — rekening + tanggal (dulu window.prompt kode akun & tanggal hari ini).
  const [oblDialog, setOblDialog] = useState(null);   // { run, type: 'bpjs'|'pph21', agency }
  const [oblForm, setOblForm] = useState({ payment_date: todayWIB(), cash_account_id: '' });
  // 2026-11-02 (K34): dialog pembatalan run final (ajukan HR → setujui Keuangan, atau owner satu langkah).
  const [cancelDialog, setCancelDialog] = useState(null);
  const [cancelReason, setCancelReason] = useState('');
  const [tick, setTick] = useState(0);
  const { accounts: cashAccounts, loaded: cashLoaded } = usePaymentCashAccounts(token);
  // Rekening bawaan = BCA (1-1201) bila ada, selain itu rekening pertama yang aktif.
  useEffect(() => {
    if (!cashAccounts.length) return;
    setPayForm(f => (f.bank_account_code ? f : {
      ...f, bank_account_code: (cashAccounts.find(a => a.gl_account_code === '1-1201') || cashAccounts[0]).gl_account_code,
    }));
  }, [cashAccounts]);

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);
  const refresh = useCallback(() => setTick(t => t + 1), []);

  useEffect(() => {
    let x = false;
    dispatch({ type: 'loading' });
    const h = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
    fetch('/api/rahaza/payroll-runs', { headers: h })
      .then(r => r.json())
      .then(data => { if (!x) dispatch({ type: 'loaded', runs: Array.isArray(data) ? data : [] }); })
      .catch(() => { if (!x) dispatch({ type: 'loaded', runs: [] }); });
    return () => { x = true; };
  }, [token, tick]);

  const createRun = useCallback(async (payload) => {
    setError('');
    const r = await fetch('/api/rahaza/payroll-runs', { method: 'POST', headers, body: JSON.stringify(payload) });
    if (!r.ok) {
      // 2026-11-02: tampilkan alasan dari backend (mis. penolakan run ganda 409 + nomor run yang bentrok).
      const STATUS_MSG = { 400: 'Data tidak valid atau tidak ada profile aktif.', 403: 'Tidak ada akses.' };
      setError(await errDetail(r, STATUS_MSG[r.status] || `Gagal buat run (HTTP ${r.status})`));
      return;
    }
    setCreating(false);
    setCreateInitial(null);
    setTick(t => t + 1);
  }, [headers]);

  // 2026-11-06 (Tahap 2): konfirmasi finalisasi lewat dialog aplikasi (dulu window.confirm) + alasan
  // pengecualian pemisahan tugas (K25: pembuat run tidak memfinalisasi/membayar sendiri; admin/owner boleh
  // dengan alasan). Gaji bersih minus ditolak backend dengan daftar nama karyawan.
  const [finalizeDialog, setFinalizeDialog] = useState(null);
  const [overrideReason, setOverrideReason] = useState('');
  const finalizeRun = (id) => { setOverrideReason(''); setFinalizeDialog(runs.find(x => x.id === id) || { id }); };
  const submitFinalize = async () => {
    if (!finalizeDialog) return;
    const id = finalizeDialog.id;
    setPaying(true);
    try {
      const r = await fetch(`/api/rahaza/payroll-runs/${id}/finalize`, {
        method: 'POST', headers, body: JSON.stringify({ override_reason: overrideReason.trim() || undefined }),
      });
      if (r.ok) {
        toast.success('Run difinalisasi & jurnal GL dibuat'); setFinalizeDialog(null); refresh();
        if (viewing?.run?.id === id) openRun(id);
      } else {
        // 2026-11-02 (P5 butir 3): jurnal gagal → run tetap draft; tampilkan penyebabnya apa adanya.
        const msg = await errDetail(r, `Gagal finalisasi penggajian (HTTP ${r.status})`);
        toast.error(msg); setError(msg); refresh();
      }
    } finally { setPaying(false); }
  };

  // 2026-11-06 (Tahap 2): hitung ulang run draf — absensi/profil/pengaturan terkini, penyesuaian manual tetap.
  const recalcRun = async (id) => {
    const r = await fetch(`/api/rahaza/payroll-runs/${id}/recalculate`, { method: 'POST', headers });
    if (r.ok) { toast.success('Run dihitung ulang. Penyesuaian manual dipertahankan.'); refresh(); if (viewing?.run?.id === id) openRun(id); }
    else toast.error(await errDetail(r, `Gagal menghitung ulang (HTTP ${r.status})`));
  };

  const retryPost = async (id) => {
    try {
      const r = await fetch(`/api/rahaza/payroll-runs/${id}/retry-post`, { method: 'POST', headers });
      const d = await r.json();
      if (r.ok && d._posting_result?.ok) toast.success(`GL Posting berhasil: ${d._posting_result.je_number}`);
      else toast.error(d._posting_result?.error || 'Gagal posting ke GL');
      refresh();
    } catch { toast.error('Gagal retry posting'); }
  };

  const payGaji = async () => {
    if (!payDialog) return;
    setPaying(true);
    try {
      const r = await fetch(`/api/rahaza/payroll-runs/${payDialog.id}/pay`, {
        method: 'POST', headers, body: JSON.stringify(payForm),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      if (d._payment_result?.ok) {
        toast.success(`Gaji dibayar! Journal Entry: ${d.payment_gl_je_number}`);
      } else {
        toast.error(d._payment_result?.error || 'Pembayaran gagal');
      }
      setPayDialog(null);
      refresh();
    } catch (e) { toast.error(e.message); }
    finally { setPaying(false); }
  };

  const voidPayment = async (run) => {
    if (!(await confirmDialog({ title: `Batalkan pembayaran ${run.run_number}?`, body: 'Jurnal pembayaran gaji akan dibatalkan.', confirmLabel: 'Batalkan pembayaran', cancelLabel: 'Kembali', danger: true }))) return;
    try {
      const r = await fetch(`/api/rahaza/payroll-runs/${run.id}/void-payment`, {
        method: 'POST', headers, body: JSON.stringify({ reason: 'Void oleh admin' }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      toast.success('Pembayaran di-void');
      refresh();
    } catch (e) { toast.error(e.message); }
  };

  const openObligation = (run, type, agency = '') => {
    const bca = cashAccounts.find(a => a.gl_account_code === '1-1201') || cashAccounts[0];
    setOblForm({ payment_date: todayWIB(), cash_account_id: bca?.id || '' });
    setOblDialog({ run, type, agency });
  };

  const payObligation = async () => {
    if (!oblDialog) return;
    const { run, type, agency } = oblDialog;
    const label = type === 'bpjs' ? (BPJS_AGENCIES.find(([k]) => k === agency)?.[1] || 'BPJS') : 'PPh21 ke DJP';
    setPaying(true);
    try {
      const r = await fetch(`/api/rahaza/payroll-runs/${run.id}/pay-${type}`, {
        method: 'POST', headers,
        body: JSON.stringify({ ...oblForm, agency: type === 'bpjs' ? agency : undefined, notes: `Bayar ${label} ${run.run_number}` }),
      });
      if (!r.ok) throw new Error(await errDetail(r, `HTTP ${r.status}`));
      const d = await r.json();
      toast.success(`${label} dibayar. JE: ${d._payment_result?.je_number || ''}`);
      setOblDialog(null);
      refresh();
    } catch (e) { toast.error(e.message); }
    finally { setPaying(false); }
  };

  const voidObligation = async (run, type, agency = '') => {
    if (!(await confirmDialog({ title: `Batalkan pembayaran ${type === 'bpjs' ? agency.toUpperCase() : 'PPh21'} ${run.run_number}?`, body: 'Jurnal pembayarannya akan dibatalkan.', confirmLabel: 'Batalkan pembayaran', cancelLabel: 'Kembali', danger: true }))) return;
    const r = await fetch(`/api/rahaza/payroll-runs/${run.id}/void-obligation-payment`, {
      method: 'POST', headers, body: JSON.stringify({ type, agency, reason: 'Void oleh pengguna' }),
    });
    if (r.ok) { toast.success('Pembayaran dibatalkan'); refresh(); if (viewing?.run?.id === run.id) openRun(run.id); }
    else toast.error(await errDetail(r, `HTTP ${r.status}`));
  };

  const submitCancel = async (action) => {
    if (!cancelDialog) return;
    setPaying(true);
    try {
      const r = await fetch(`/api/rahaza/payroll-runs/${cancelDialog.id}/cancel`, {
        method: 'POST', headers, body: JSON.stringify({ action, reason: cancelReason }),
      });
      if (!r.ok) throw new Error(await errDetail(r, `HTTP ${r.status}`));
      const d = await r.json();
      toast.success(d.status === 'cancelled'
        ? `Run ${d.run_number} dibatalkan — ${(d.cancel_reversal_jes || []).length} jurnal pembalik dibuat`
        : (action === 'reject' ? 'Pengajuan pembatalan ditolak' : 'Pengajuan pembatalan dikirim ke Keuangan'));
      setCancelDialog(null);
      refresh();
    } catch (e) { toast.error(e.message); }
    finally { setPaying(false); }
  };

  const delRun = async (id) => {
    if (!(await confirmDialog({ title: 'Hapus proses gaji ini?', body: 'Hanya bisa selama masih draf.', confirmLabel: 'Hapus', danger: true }))) return;
    const r = await fetch(`/api/rahaza/payroll-runs/${id}`, { method: 'DELETE', headers });
    if (r.ok) refresh(); else setError(`Gagal hapus (HTTP ${r.status})`);
  };

  // FASE 20 — dulu `window.open('/api/rahaza/payroll-runs/{id}/export')`, dua bug
  // sekaligus: (1) endpoint-nya tidak terdaftar karena handler CSV-nya jadi kode
  // mati di dalam `export_run_excel()` (lihat backend), dan (2) `window.open`
  // TIDAK BISA mengirim header Authorization sehingga tetap 401 walau route ada.
  // Sekarang memakai pola `downloadWithAuth` yang sama dengan export Excel.
  const exportCsv = async (id, num) => {
    try {
      toast.info('Menyiapkan CSV...');
      await downloadWithAuth(
        `/api/rahaza/payroll-runs/${id}/export`,
        token,
        `payroll_${String(num || id).replace(/\//g, '-')}.csv`
      );
      toast.success('CSV berhasil diunduh.');
    } catch (e) { toast.error(`Gagal download CSV: ${e.message}`); }
  };

  const downloadRunExcel = async (id, num) => {
    try {
      toast.info('Menyiapkan Excel...');
      await downloadWithAuth(
        `/api/rahaza/payroll-runs/${id}/export-excel`,
        token,
        `payroll_${num}.xlsx`
      );
      toast.success('Excel berhasil diunduh.');
    } catch (e) { toast.error(`Gagal download Excel: ${e.message}`); }
  };

  const downloadRunPdf = async (id, num) => {
    try {
      toast.info('Menyiapkan PDF semua slip...');
      await downloadWithAuth(
        `/api/rahaza/payroll-runs/${id}/pdf`,
        token,
        `payroll_${num}_all_slips.pdf`
      );
      toast.success('PDF berhasil diunduh.');
    } catch (e) { toast.error(`Gagal download PDF: ${e.message}`); }
  };

  const openRun = async (id) => {
    const r = await fetch(`/api/rahaza/payroll-runs/${id}`, { headers });
    if (r.ok) setViewing(await r.json());
  };

  /* Salin Bulan Lalu — pre-fill modal dengan periode bulan lalu */
  const salinBulanLalu = () => {
    setCreateInitial(lastMonthPeriodWIB());
    setCreating(true);
  };

  const { page, setPage, totalPages, total, paged } = useClientPagination(runs, 10);
  return (
    <div className="space-y-5" data-testid="rahaza-payroll-run-page">
      <PageHeader
        icon={DollarSign}
        eyebrow="Portal SDM · Penggajian"
        title="Proses Penggajian"
        subtitle="Jalankan penggajian per periode. Gunakan &quot;Salin Bulan Lalu&quot; untuk isi otomatis periode sebelumnya."
        actions={
          <>
            {/* Salin Bulan Lalu — 1-click period pre-fill */}
            <Button
              variant="ghost"
              onClick={salinBulanLalu}
              className="h-9 border border-[var(--glass-border)] gap-1.5"
              data-testid="pr-copy-last-month"
              title={`Buat run untuk periode bulan lalu (${lastMonthPeriodWIB().from} → ${lastMonthPeriodWIB().to})`}
            >
              <Copy className="w-3.5 h-3.5" />
              Salin Bulan Lalu
            </Button>
            <Button variant="ghost" onClick={refresh} className="h-9 border border-[var(--glass-border)]" data-testid="pr-refresh">
              <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> Refresh
            </Button>
            <Button onClick={() => { setCreateInitial(null); setCreating(true); }} className="h-9" data-testid="pr-create">
              <Plus className="w-3.5 h-3.5 mr-1.5" /> Buat Penggajian Baru
            </Button>
          </>
        }
      />

      {/* RC-FLOW-UX Alur 6 — Payroll → Jurnal Gaji (GL) */}
      <OnwardCTA
        onNavigate={onNavigate}
        title="Langkah Berikutnya"
        actions={[
          { module: 'fin-journal-hub', label: 'Jurnal Gaji (GL)', icon: BookOpen, primary: true, hint: 'Lihat jurnal akuntansi hasil finalisasi penggajian' },
        ]}
      />

      {error && <div className="bg-[hsl(var(--destructive)/0.12)] border border-[hsl(var(--destructive)/0.22)] rounded-lg p-3 text-sm text-[hsl(var(--destructive))]">{error}</div>}

      {loading ? (
        <div className="flex items-center justify-center h-48"><div className="animate-spin rounded-full h-10 w-10 border-b-2 border-primary" /></div>
      ) : (
        <GlassCard className="p-0 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-[var(--glass-bg)]">
                <tr className="text-left text-xs text-muted-foreground">
                  <th className="px-4 py-3">Run #</th>
                  <th className="px-3 py-3">Periode</th>
                  <th className="px-3 py-3">Status</th>
                  <th className="px-3 py-3 text-right">Karyawan</th>
                  <th className="px-3 py-3 text-right">Gross</th>
                  <th className="px-3 py-3 text-right">Potongan</th>
                  <th className="px-3 py-3 text-right">Net</th>
                  <th className="px-3 py-3">GL Jurnal</th>
                  <th className="px-3 py-3 text-right">Aksi</th>
                </tr>
              </thead>
              <tbody>
                {runs.length === 0 ? (
                  <tr><td colSpan={9} className="text-center py-12 text-muted-foreground">
                    Belum ada proses penggajian. Klik &quot;Buat Penggajian Baru&quot; atau &quot;Salin Bulan Lalu&quot; untuk memulai.
                  </td></tr>
                ) : paged.map(r => (
                  <tr key={r.id} className="border-t border-[var(--glass-border)] hover:bg-[var(--glass-bg-hover)] transition-colors" data-testid={`pr-row-${r.run_number}`}>
                    <td className="px-4 py-2 font-mono text-xs text-foreground">{r.run_number}</td>
                    <td className="px-3 py-2 text-xs text-foreground">{r.period_from} → {r.period_to}</td>
                    <td className="px-3 py-2"><StatusBadge status={r.status} /></td>
                    <td className="px-3 py-2 text-right text-foreground">{r.total_employees}</td>
                    <td className="px-3 py-2 text-right font-mono text-foreground">{fmtIDR(r.total_gross)}</td>
                    <td className="px-3 py-2 text-right font-mono text-red-600 dark:text-red-300">{fmtIDR(r.total_deductions)}</td>
                    <td className="px-3 py-2 text-right font-mono text-emerald-600 dark:text-emerald-300 font-semibold">{fmtIDR(r.total_net)}</td>
                    {/* GL Posting Status */}
                    <td className="px-3 py-2">
                      <GLStatusBadge run={r} onNavigate={onNavigate} />
                    </td>
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      <button onClick={() => openRun(r.id)} className="text-xs text-primary hover:underline mr-2" data-testid={`pr-view-${r.run_number}`} title="Lihat detail"><Eye className="w-3 h-3 inline" /></button>
                      <button onClick={() => exportCsv(r.id, r.run_number)} className="text-xs text-foreground/50 hover:text-foreground hover:underline mr-2" title="Download CSV"><Download className="w-3 h-3 inline" /></button>
                      <button
                        onClick={() => downloadRunExcel(r.id, r.run_number)}
                        className="text-xs text-emerald-600 dark:text-emerald-400 hover:underline mr-2"
                        data-testid={`pr-excel-${r.run_number}`}
                        title="Download Excel (Rekapitulasi + Slip + Data Bank)"
                      >
                        <FileText className="w-3 h-3 inline" />
                      </button>
                      <button
                        onClick={() => downloadRunPdf(r.id, r.run_number)}
                        className="text-xs text-primary hover:underline mr-2"
                        data-testid={`pr-pdf-run-${r.run_number}`}
                        title="Download semua slip PDF"
                      >
                        <FilesIcon className="w-3 h-3 inline" />
                      </button>
                      {r.status === 'draft' && (
                        <>
                          <Button variant="ghost" size="icon-sm" onClick={() => recalcRun(r.id)} className="mr-1"
                            title="Hitung ulang (penyesuaian manual tetap)" aria-label="Hitung ulang" data-testid={`pr-recalc-${r.run_number}`}>
                            <RotateCcw className="w-3 h-3" />
                          </Button>
                          <button onClick={() => finalizeRun(r.id)} className="text-xs text-emerald-600 dark:text-emerald-300 hover:underline mr-2" data-testid={`pr-finalize-${r.run_number}`} title="Finalisasi"><Lock className="w-3 h-3 inline" /></button>
                          <button onClick={() => delRun(r.id)} className="text-xs text-red-600 dark:text-red-300 hover:underline" title="Hapus"><RefreshCw className="w-3 h-3 inline" /></button>
                        </>
                      )}
                      {r.status === 'finalized' && r.post_error && (
                        <button onClick={() => retryPost(r.id)} className="text-xs text-amber-600 dark:text-amber-300 hover:underline" title="Retry GL Posting"><AlertTriangle className="w-3 h-3 inline" /></button>
                      )}
                      {/* Bayar Gaji — tampil jika sudah finalized + GL posted + belum dibayar */}
                      {r.status === 'finalized' && r.gl_je_number && r.payment_status !== 'paid' && (
                        <button
                          onClick={() => { setPayDialog(r); setPayForm(f => ({ ...f, payment_date: todayWIB() })); }}
                          className="text-xs text-blue-600 dark:text-blue-300 hover:underline ml-1"
                          title="Bayar Gaji (buat payment JE)"
                          data-testid={`pay-btn-${r.run_number}`}
                        >
                          💸
                        </button>
                      )}
                      {r.payment_status === 'paid' && (
                        <button
                          onClick={() => voidPayment(r)}
                          className="text-xs text-muted-foreground hover:underline ml-1"
                          title="Void pembayaran"
                          data-testid={`void-pay-btn-${r.run_number}`}
                        >
                          <X className="w-3 h-3 inline" />
                        </button>
                      )}
                      {/* BPJS (per lembaga) + PPh21 payment buttons — 2026-11-02 (K22) */}
                      {r.status === 'finalized' && r.gl_je_number && (
                        <>
                          {r.bpjs_payment_status !== 'paid' && BPJS_AGENCIES.map(([ag, lbl]) => (
                            !bpjsPaid(r, ag) && bpjsDue(r, ag) !== 0 && (
                              <button
                                key={ag}
                                onClick={() => openObligation(r, 'bpjs', ag)}
                                className="text-xs text-teal-600 dark:text-teal-300 hover:underline ml-1"
                                title={`Bayar ${lbl}`}
                                data-testid={`bpjs-${ag}-btn-${r.run_number}`}
                              >{ag === 'kes' ? 'BK' : 'BT'}</button>
                            )
                          ))}
                          {r.pph21_payment_status !== 'paid' && (
                            <button
                              onClick={() => openObligation(r, 'pph21')}
                              className="text-xs text-purple-600 dark:text-purple-300 hover:underline ml-1"
                              title="Bayar PPh21 ke DJP"
                              data-testid={`pph21-btn-${r.run_number}`}
                            >P</button>
                          )}
                        </>
                      )}
                      {/* 2026-11-02 (K34): batalkan run final (jurnal pembalik) */}
                      {r.status === 'finalized' && (
                        <button
                          onClick={() => { setCancelReason(r.cancel_request?.reason || ''); setCancelDialog(r); }}
                          className={`text-xs ml-1 hover:underline ${r.cancel_request?.status === 'pending' ? 'text-amber-600 dark:text-amber-300 font-semibold' : 'text-red-600 dark:text-red-300'}`}
                          title={r.cancel_request?.status === 'pending' ? 'Pengajuan pembatalan menunggu Keuangan' : 'Batalkan run (jurnal pembalik)'}
                          data-testid={`cancel-run-btn-${r.run_number}`}
                        ><X className="w-3 h-3 inline" />{r.cancel_request?.status === 'pending' ? '?' : ''}</button>
                      )}
                      {(r.warnings || []).length > 0 && (
                        <span className="ml-1 text-amber-600 dark:text-amber-300" title={(r.warnings || []).map(w => `${w.employee_name}: ${w.message}`).join('\n')}
                          data-testid={`run-warn-${r.run_number}`}><AlertTriangle className="w-3 h-3 inline" /></span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} className="px-1" />
          </div>
        </GlassCard>
      )}

      {creating && (
        <CreateRunModal
          onClose={() => { setCreating(false); setCreateInitial(null); }}
          onCreate={createRun}
          token={token}
          initial={createInitial}
        />
      )}
      {viewing && (
        <RunDetailModal
          data={viewing}
          token={token}
          onClose={() => setViewing(null)}
          onRefresh={() => { openRun(viewing.run.id); refresh(); }}
          onDownloadExcel={downloadRunExcel}
          onVoidObligation={voidObligation}
          onRecalc={recalcRun}
        />
      )}

      {/* ── Payment Dialog ── */}
      <Dialog open={!!payDialog} onOpenChange={o => !o && setPayDialog(null)}>
        <DialogContent className="max-w-sm" data-testid="pay-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <CreditCard size={16} className="text-blue-600 dark:text-blue-400" />
              Bayar Gaji — {payDialog?.run_number}
            </DialogTitle>
            <p className="text-xs text-muted-foreground mt-1">
              Jurnal: Dr Hutang Gaji / Cr Bank
            </p>
          </DialogHeader>
          <div className="space-y-3 mt-2">
            {payDialog && (
              <div className="rounded-lg bg-blue-100 dark:bg-blue-500/10 border border-blue-400 dark:border-blue-500/30 px-3 py-2 text-sm">
                <span className="text-muted-foreground">Total dibayar:</span>
                <span className="ml-2 font-bold text-blue-600 dark:text-blue-300">
                  Rp {Number(payDialog.total_net || 0).toLocaleString('id-ID')}
                </span>
              </div>
            )}
            <div>
              <Label className="text-xs">Tanggal Pembayaran</Label>
              <GlassInput type="date" className="mt-1 h-9 text-sm"
                value={payForm.payment_date}
                onChange={e => setPayForm(f => ({ ...f, payment_date: e.target.value }))}
                data-testid="pay-date" />
            </div>
            <div>
              <Label className="text-xs">Rekening / Kas</Label>
              {/* Tahap 5: pemilih rekening yang sama dengan form bayar SDM lain (bisa dicari), nilai = kode akun GL */}
              <div className="mt-1">
                <CashAccountSelect accounts={cashAccounts} loaded={cashLoaded} valueKey="gl_account_code"
                  value={payForm.bank_account_code} testId="pay-bank-select"
                  onChange={v => setPayForm(f => ({ ...f, bank_account_code: v }))} />
              </div>
            </div>
            <div>
              <Label className="text-xs">Metode</Label>
              <Select value={payForm.payment_method}
                onValueChange={v => setPayForm(f => ({ ...f, payment_method: v }))}>
                <SelectTrigger className="mt-1 h-9 text-sm"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="bank_transfer">Transfer Bank</SelectItem>
                  <SelectItem value="cash">Tunai</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">Catatan (opsional)</Label>
              <GlassInput className="mt-1 h-9 text-sm" placeholder="Keterangan pembayaran..."
                value={payForm.notes}
                onChange={e => setPayForm(f => ({ ...f, notes: e.target.value }))} />
            </div>
            <div>
              <Label className="text-xs">Alasan pengecualian (hanya bila Anda sendiri yang membuat run ini)</Label>
              <GlassInput className="mt-1 h-9 text-sm" placeholder="Khusus admin/owner"
                value={payForm.override_reason || ''} data-testid="pay-override-reason"
                onChange={e => setPayForm(f => ({ ...f, override_reason: e.target.value }))} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPayDialog(null)}>Batal</Button>
            <Button
              onClick={payGaji}
              disabled={paying || !payForm.bank_account_code}
              className="bg-blue-600 hover:bg-blue-700"
              data-testid="pay-confirm-btn"
            >
              {paying ? '💸 Memproses...' : '💸 Bayar Gaji'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Bayar BPJS per lembaga / PPh21 — 2026-11-02 (K22): rekening + tanggal, bukan window.prompt ── */}
      <Dialog open={!!oblDialog} onOpenChange={o => !o && setOblDialog(null)}>
        <DialogContent className="max-w-sm" data-testid="obligation-dialog">
          <DialogHeader>
            <DialogTitle>
              {oblDialog?.type === 'bpjs'
                ? `Bayar ${BPJS_AGENCIES.find(([k]) => k === oblDialog?.agency)?.[1] || 'BPJS'}`
                : 'Bayar PPh21 ke DJP'} — {oblDialog?.run?.run_number}
            </DialogTitle>
          </DialogHeader>
          {oblDialog?.type === 'bpjs' && (() => {
            const b = (oblDialog.run.bpjs_breakdown || {})[oblDialog.agency];
            return b ? (
              <div className="rounded-lg bg-teal-50 dark:bg-teal-500/10 border border-teal-300 dark:border-teal-500/30 px-3 py-2 text-xs space-y-0.5">
                <div>Potongan karyawan: <strong>{fmtIDR(b.employee)}</strong></div>
                <div>Iuran perusahaan (sudah dijurnal): <strong>{fmtIDR(b.employer)}</strong></div>
                <div className="text-sm">Total dibayar: <strong>{fmtIDR(Number(b.employee || 0) + Number(b.employer || 0))}</strong> · Dr {b.payable_code}</div>
              </div>
            ) : <p className="text-xs text-muted-foreground">Run lama: nilai = potongan karyawan lembaga ini (akun hutang BPJS lama).</p>;
          })()}
          <div className="space-y-3">
            <div>
              <Label className="text-xs">Tanggal Pembayaran</Label>
              <GlassInput type="date" className="mt-1 h-9 text-sm"
                value={oblForm.payment_date} onChange={e => setOblForm(f => ({ ...f, payment_date: e.target.value }))}
                data-testid="obligation-date" />
            </div>
            <div>
              <Label className="text-xs">Rekening / Kas</Label>
              <CashAccountSelect accounts={cashAccounts} loaded={cashLoaded} value={oblForm.cash_account_id}
                onChange={v => setOblForm(f => ({ ...f, cash_account_id: v }))} testId="obligation-account" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOblDialog(null)}>Batal</Button>
            <Button onClick={payObligation} disabled={paying || !oblForm.cash_account_id || !oblForm.payment_date}
              data-testid="obligation-confirm">{paying ? 'Memproses…' : 'Bayar'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Batalkan run final — 2026-11-02 (K34) ── */}
      <Dialog open={!!cancelDialog} onOpenChange={o => !o && setCancelDialog(null)}>
        <DialogContent className="max-w-md" data-testid="cancel-run-dialog">
          <DialogHeader>
            <DialogTitle>Batalkan Run {cancelDialog?.run_number}</DialogTitle>
            <p className="text-xs text-muted-foreground mt-1">
              Semua jurnal run ini (gaji + potongan kasbon) dibalik dengan jurnal pembalik, potongan kasbon dikembalikan,
              dan status menjadi DIBATALKAN sehingga periode bisa dibuat ulang. Gaji/BPJS/PPh21 yang sudah dibayar harus
              di-void dulu. Alur: HR mengajukan → Keuangan (orang lain) menyetujui; owner bisa satu langkah.
            </p>
          </DialogHeader>
          {cancelDialog?.cancel_request?.status === 'pending' && (
            <div className="rounded-lg border border-amber-400 bg-amber-50 dark:bg-amber-500/10 px-3 py-2 text-xs">
              Diajukan oleh <strong>{cancelDialog.cancel_request.requested_by_name}</strong>: {cancelDialog.cancel_request.reason}
            </div>
          )}
          <div>
            <Label className="text-xs">Alasan</Label>
            <textarea value={cancelReason} onChange={e => setCancelReason(e.target.value)} rows={3}
              className="mt-1 w-full rounded border border-border bg-background px-3 py-2 text-sm" data-testid="cancel-run-reason" />
          </div>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setCancelDialog(null)}>Tutup</Button>
            {cancelDialog?.cancel_request?.status === 'pending' ? (
              <>
                <Button variant="outline" onClick={() => submitCancel('reject')} disabled={paying} data-testid="cancel-run-reject">Tolak Pengajuan</Button>
                <Button className="bg-red-600 hover:bg-red-700" onClick={() => submitCancel('approve')} disabled={paying} data-testid="cancel-run-approve">
                  Setujui & Batalkan Run
                </Button>
              </>
            ) : (
              <>
                <Button variant="outline" onClick={() => submitCancel('request')} disabled={paying || !cancelReason.trim()} data-testid="cancel-run-request">
                  Ajukan (HR)
                </Button>
                <Button className="bg-red-600 hover:bg-red-700" onClick={() => submitCancel('approve')} disabled={paying || !cancelReason.trim()}
                  title="Hanya owner/superadmin (satu langkah)" data-testid="cancel-run-owner">Batalkan Sekarang (owner)</Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Finalisasi — 2026-11-06 (Tahap 2): dialog aplikasi + alasan pengecualian pemisahan tugas ── */}
      <Dialog open={!!finalizeDialog} onOpenChange={o => !o && !paying && setFinalizeDialog(null)}>
        <DialogContent className="max-w-md" data-testid="finalize-dialog">
          <DialogHeader>
            <DialogTitle>Finalisasi {finalizeDialog?.run_number || 'run gaji'}</DialogTitle>
            <p className="text-xs text-muted-foreground mt-1">
              Jurnal gaji dibuat dan absensi periode ini dikunci. Sesudahnya slip tidak bisa diubah; koreksi absen masuk
              run berikutnya. Finalisasi harus oleh pengguna lain dari pembuat run.
            </p>
          </DialogHeader>
          <div>
            <Label className="text-xs">Alasan pengecualian (hanya admin/owner yang membuat run ini sendiri)</Label>
            <GlassInput className="mt-1 h-9 text-sm" value={overrideReason} onChange={e => setOverrideReason(e.target.value)}
              placeholder="Kosongkan bila Anda bukan pembuat run" data-testid="finalize-override-reason" />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setFinalizeDialog(null)} disabled={paying}>Batal</Button>
            <Button onClick={submitFinalize} disabled={paying} data-testid="finalize-confirm">{paying ? 'Memproses…' : 'Finalisasi'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function CreateRunModal({ onClose, onCreate, token, initial }) {
  const today = todayWIB(); // 2026-11-02: tanggal WIB (No.54(a)), bukan UTC
  const defaultFrom = initial?.from || (today.slice(0, 7) + '-01');
  const defaultTo = initial?.to || today;
  const [from, setFrom] = useState(defaultFrom);
  const [to, setTo] = useState(defaultTo);
  const [notes, setNotes] = useState('');
  const [validating, setValidating] = useState(false);
  const [validation, setValidation] = useState(null);
  const [showValidation, setShowValidation] = useState(false);

  const headers = { Authorization: `Bearer ${token}` };

  const validateAttendance = async () => {
    setValidating(true);
    try {
      const r = await fetch(
        `/api/rahaza/hr/reports/attendance-validation?period_from=${from}&period_to=${to}`,
        { headers }
      );
      if (r.ok) { setValidation(await r.json()); setShowValidation(true); }
    } finally { setValidating(false); }
  };

  const sevColor = (sev) => sev === 'high'
    ? 'text-red-600 dark:text-red-300 border-red-300 dark:border-red-300/20 bg-red-400/8'
    : 'text-amber-600 dark:text-amber-300 border-amber-300 dark:border-amber-300/20 bg-amber-400/8';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-foreground/50 backdrop-blur-sm" onClick={onClose}>
      <GlassCard className="p-6 max-w-xl w-full max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold text-foreground">Buat Proses Penggajian Baru</h2>
          {initial && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20">Periode bulan lalu</span>
          )}
        </div>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground uppercase block mb-1">Periode Dari</label>
              <GlassInput type="date" value={from} onChange={e => { setFrom(e.target.value); setValidation(null); setShowValidation(false); }} data-testid="pr-create-from" />
            </div>
            <div>
              <label className="text-xs text-muted-foreground uppercase block mb-1">Periode Sampai</label>
              <GlassInput type="date" value={to} onChange={e => { setTo(e.target.value); setValidation(null); setShowValidation(false); }} data-testid="pr-create-to" />
            </div>
          </div>
          <div>
            <label className="text-xs text-muted-foreground uppercase block mb-1">Catatan</label>
            <GlassInput value={notes} onChange={e => setNotes(e.target.value)} placeholder="Opsional" />
          </div>

          {/* Attendance Validation */}
          <div className="border border-[var(--glass-border)] rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold text-foreground/70 uppercase flex items-center gap-1.5">
                <ShieldAlert className="w-3.5 h-3.5" /> Validasi Attendance (Opsional)
              </span>
              <Button variant="ghost" size="sm" className="h-7 px-2 text-xs border border-[var(--glass-border)]"
                onClick={validateAttendance} disabled={validating} data-testid="pr-validate-att">
                {validating ? 'Memeriksa...' : 'Periksa Sekarang'}
              </Button>
            </div>
            {!showValidation && (
              <p className="text-xs text-muted-foreground">Klik &quot;Periksa Sekarang&quot; untuk melihat potensi masalah attendance sebelum run payroll.</p>
            )}
            {showValidation && validation && (
              <div className="space-y-2" data-testid="pr-validation-result">
                {validation.summary.total_warnings === 0 ? (
                  <div className="flex items-center gap-2 text-xs text-emerald-600 dark:text-emerald-300 bg-emerald-400/8 border border-emerald-300 dark:border-emerald-300/20 rounded-lg p-2.5">
                    <CheckCircle className="w-4 h-4 shrink-0" />
                    <span>Attendance lengkap untuk semua {validation.summary.total_employees} karyawan. Siap run payroll.</span>
                  </div>
                ) : (
                  <>
                    <div className="flex items-center gap-2 text-xs text-amber-600 dark:text-amber-300 bg-amber-400/8 border border-amber-300 dark:border-amber-300/20 rounded-lg p-2.5">
                      <AlertTriangle className="w-4 h-4 shrink-0" />
                      <span><strong>{validation.summary.total_warnings}</strong> karyawan punya attendance tidak lengkap. Payroll tetap bisa dijalankan.</span>
                    </div>
                    <div className="max-h-40 overflow-y-auto space-y-1">
                      {validation.warnings.slice(0, 10).map(w => (
                        <div key={w.employee_id} className={`text-[11px] rounded p-2 border ${sevColor(w.severity)}`}>
                          <span className="font-semibold">{w.employee_name}</span>
                          <span className="ml-2 font-normal">{w.warning_message}</span>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>

          <div className="bg-primary/10 border border-primary/20 rounded-lg p-3 text-xs text-foreground/80">
            <Calendar className="w-3.5 h-3.5 inline-block mr-1" />
            Run akan otomatis hitung slip untuk semua karyawan dengan profile payroll aktif.
          </div>
        </div>
        <div className="flex gap-2 mt-6 justify-end">
          <Button variant="ghost" onClick={onClose} className="border border-[var(--glass-border)]">Batal</Button>
          <Button onClick={() => onCreate({ period_from: from, period_to: to, notes })} data-testid="pr-create-submit">Buat Run</Button>
        </div>
      </GlassCard>
    </div>
  );
}

function RunDetailModal({ data, token, onClose, onRefresh, onDownloadExcel, onVoidObligation, onRecalc }) {
  const run = data.run;
  const payslips = data.payslips || [];
  const locked = run.status !== 'draft';
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
  const [dlSlipId, setDlSlipId] = useState(null);
  const [dlAllLoading, setDlAllLoading] = useState(false);

  // 2026-11-02 (K34): payload = { earning_adjustment, deduction, deduction_overrides, notes } — alasan wajib.
  const saveAdjustment = async (slipId, payload) => {
    // FASE 20 — dulu hasil `fetch` TIDAK diperiksa sama sekali, jadi ketika
    // endpoint-nya belum ada (404) UI tetap memanggil `onRefresh()` dan tampak
    // "berhasil" padahal tidak ada yang tersimpan. Sekarang error dimunculkan.
    try {
      const r = await fetch(`/api/rahaza/payroll-runs/${run.id}/payslips/${slipId}/adjust`, {
        method: 'POST', headers, body: JSON.stringify(payload),
      });
      if (!r.ok) {
        let detail = '';
        try { detail = (await r.json()).detail || ''; } catch { /* noop */ }
        throw new Error(detail || `HTTP ${r.status}`);
      }
      const d = await r.json();
      toast.success('Penyesuaian tersimpan.');
      if (d.warning) toast.warning(d.warning);
      onRefresh();
      return true;
    } catch (e) {
      toast.error(`Gagal menyimpan penyesuaian: ${e.message}`);
      return false;
    }
  };

  const downloadSlipPdf = async (slip) => {
    setDlSlipId(slip.id);
    try {
      await downloadWithAuth(
        `/api/rahaza/payslips/${slip.id}/pdf`,
        token,
        `slip_${slip.employee_code}_${slip.period_from}_${slip.period_to}.pdf`
      );
      toast.success(`Slip ${slip.employee_code} berhasil diunduh.`);
    } catch (e) {
      toast.error(`Gagal: ${e.message}`);
    } finally { setDlSlipId(null); }
  };

  const downloadAllPdf = async () => {
    setDlAllLoading(true);
    try {
      toast.info('Menyiapkan PDF semua slip gaji...');
      await downloadWithAuth(
        `/api/rahaza/payroll-runs/${run.id}/pdf`,
        token,
        `payroll_${run.run_number}_all_slips.pdf`
      );
      toast.success('PDF semua slip berhasil diunduh.');
    } catch (e) {
      toast.error(`Gagal: ${e.message}`);
    } finally { setDlAllLoading(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-foreground/50 backdrop-blur-sm" onClick={onClose}>
      <GlassCard className="p-6 max-w-5xl w-full max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <h2 className="text-xl font-bold text-foreground">{run.run_number}</h2>
            <p className="text-xs text-muted-foreground">{run.period_from} → {run.period_to} · Status: <span className={run.status === 'finalized' ? 'text-emerald-600 dark:text-emerald-300' : 'text-amber-600 dark:text-amber-300'}>{run.status}</span></p>
          </div>
          {/* PDF & Excel download actions */}
          <div className="flex items-center gap-2 shrink-0">
            {run.status === 'draft' && onRecalc && (
              <Button variant="outline" size="sm" onClick={() => onRecalc(run.id)} data-testid="pr-detail-recalc"
                title="Hitung ulang dari absensi, profil gaji, dan pengaturan terkini; penyesuaian manual tetap">
                <RotateCcw className="w-3.5 h-3.5 mr-1" /> Hitung ulang
              </Button>
            )}
            <button
              onClick={() => onDownloadExcel(run.id, run.run_number)}
              className="h-8 px-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/20 transition-colors flex items-center gap-1.5 text-xs font-semibold"
              data-testid="pr-download-excel"
              title="Download Excel: Rekapitulasi + Slip Individual + Data Transfer Bank"
            >
              <FileText className="w-3.5 h-3.5" />
              Export Excel
            </button>
            <button
              onClick={downloadAllPdf}
              disabled={dlAllLoading}
              className="h-8 px-3 rounded-lg border border-primary/30 bg-primary/10 text-primary hover:bg-primary/20 transition-colors flex items-center gap-1.5 text-xs font-semibold disabled:opacity-50"
              data-testid="pr-download-all-pdf"
              title="Download PDF semua slip gaji dalam satu file"
            >
              {dlAllLoading
                ? <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                : <FilesIcon className="w-3.5 h-3.5" />}
              {dlAllLoading ? 'Menyiapkan...' : 'Download Semua Slip PDF'}
            </button>
            <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-2xl leading-none">×</button>
          </div>
        </div>

        {/* Summary tiles */}
        <div className="grid grid-cols-3 gap-2 mb-4">
          <GlassPanel className="px-3 py-2"><div className="text-[10px] uppercase text-muted-foreground">Total Kotor</div><div className="text-lg font-bold text-foreground">{fmtIDR(run.total_gross)}</div></GlassPanel>
          <GlassPanel className="px-3 py-2"><div className="text-[10px] uppercase text-muted-foreground">Potongan</div><div className="text-lg font-bold text-red-600 dark:text-red-300">{fmtIDR(run.total_deductions)}</div></GlassPanel>
          <GlassPanel className="px-3 py-2"><div className="text-[10px] uppercase text-muted-foreground">Net</div><div className="text-lg font-bold text-emerald-600 dark:text-emerald-300">{fmtIDR(run.total_net)}</div></GlassPanel>
        </div>

        {/* 2026-11-02 (K24): peringatan lembur bertarif 0 */}
        {(run.warnings || []).length > 0 && (
          <div className="mb-4 rounded-lg border border-amber-400 bg-amber-50 dark:bg-amber-500/10 p-3 text-xs space-y-1" data-testid="run-warnings">
            <div className="font-semibold flex items-center gap-1"><AlertTriangle className="w-3.5 h-3.5" /> {run.warnings.length} peringatan — periksa sebelum finalisasi</div>
            {run.warnings.map((w, i) => <div key={`${w.employee_id}-${w.type}-${i}`}><strong>{w.employee_name}</strong> — {w.message}</div>)}
          </div>
        )}

        {/* 2026-11-02 (K22/K34): status pembayaran BPJS per lembaga & PPh21 (void diperlukan sebelum batal run) */}
        {run.status !== 'draft' && (
          <div className="mb-4 flex flex-wrap gap-2 text-xs" data-testid="run-obligations">
            {run.bpjs_employer_totals && (
              <span className="px-2 py-1 rounded border border-[var(--glass-border)]">
                Iuran BPJS perusahaan: {fmtIDR(run.bpjs_employer_totals.total)} {run.bpjs_employer_journal ? '(dijurnal)' : '(tidak dijurnal — saklar mati)'}
              </span>
            )}
            {BPJS_AGENCIES.map(([ag, lbl]) => bpjsPaid(run, ag) && (
              <span key={ag} className="px-2 py-1 rounded border border-teal-400 text-teal-700 dark:text-teal-300">
                {lbl} dibayar {run.bpjs_payments[ag].je_number}
                {run.status === 'finalized' && <button className="ml-1 underline" onClick={() => onVoidObligation(run, 'bpjs', ag)}>void</button>}
              </span>
            ))}
            {run.pph21_payment_status === 'paid' && (
              <span className="px-2 py-1 rounded border border-purple-400 text-purple-700 dark:text-purple-300">
                PPh21 dibayar {run.pph21_payment_je}
                {run.status === 'finalized' && <button className="ml-1 underline" onClick={() => onVoidObligation(run, 'pph21')}>void</button>}
              </span>
            )}
            {run.status === 'cancelled' && (
              <span className="px-2 py-1 rounded border border-red-400 text-red-700 dark:text-red-300">
                Dibatalkan {run.cancelled_by_name}: {run.cancel_reason} · pembalik {(run.cancel_reversal_jes || []).map(j => j.reversal).join(', ')}
              </span>
            )}
          </div>
        )}

        {/* Payslips table
            FASE 20 — kolom di sini DULU membaca skema payslip LAMA
            (`base_salary`, `transport_allowance`, `meal_allowance`,
            `production_bonus`, `overtime_pay`, `total_deductions`, `net_salary`).
            TIDAK SATU PUN field itu dihasilkan `_compute_payslip_for_employee()`,
            yang menulis `earnings_total`, `allowance_total`, `overtime_amount`,
            `gross_pay`, `deductions_total`, `net_pay`. Akibatnya SELURUH kolom
            uang menampilkan "Rp 0" padahal total run benar (kelas bug yang sama
            dengan 404 senyap: HTTP 200, tapi layar bohong).
            `Transport`/`Bonus Prod.` dihapus karena backend tidak memisahkannya —
            semuanya masuk `allowances[]`; menampilkan kolom yang mustahil terisi
            hanya membuat pengguna menduga datanya hilang.
            Fallback ke nama lama dipertahankan (backend sendiri melakukannya,
            mis. `slip.get("net_pay", slip.get("net_salary", 0))`) supaya payslip
            lama di DB produksi tetap tampil. */}
        <table className="w-full text-sm">
          <thead className="bg-[var(--glass-bg)]">
            <tr className="text-left text-xs text-muted-foreground">
              <th className="px-3 py-2">Karyawan</th>
              <th className="px-3 py-2 text-right">Upah</th>
              <th className="px-3 py-2 text-right">Tunjangan</th>
              <th className="px-3 py-2 text-right">Lembur</th>
              <th className="px-3 py-2 text-right">Bruto</th>
              <th className="px-3 py-2 text-right">Potongan</th>
              <th className="px-3 py-2 text-right font-semibold text-foreground">Net</th>
              <th className="px-3 py-2 text-center">Slip</th>
              {!locked && <th className="px-3 py-2">Adj.</th>}
            </tr>
          </thead>
          <tbody>
            {payslips.map(s => (
              <tr key={s.id} className="border-t border-[var(--glass-border)] hover:bg-[var(--glass-bg-hover)] transition-colors" data-testid={`slip-${s.employee_code}`}>
                <td className="px-3 py-2">
                  <div className="font-semibold text-xs">{s.employee_name}</div>
                  <div className="text-[10px] text-muted-foreground font-mono">{s.employee_code}</div>
                </td>
                <td className="px-3 py-2 text-right font-mono text-xs">{fmtIDR(s.earnings_total ?? s.base_salary)}</td>
                <td className="px-3 py-2 text-right font-mono text-xs">{fmtIDR(s.allowance_total ?? s.meal_allowance)}</td>
                <td className="px-3 py-2 text-right font-mono text-xs">{fmtIDR(s.overtime_amount ?? s.overtime_pay)}</td>
                <td className="px-3 py-2 text-right font-mono text-xs">{fmtIDR(s.gross_pay)}</td>
                <td className="px-3 py-2 text-right font-mono text-xs text-red-600 dark:text-red-300">{fmtIDR(s.deductions_total ?? s.total_deductions)}</td>
                <td className="px-3 py-2 text-right font-mono text-xs font-bold text-emerald-600 dark:text-emerald-300">{fmtIDR(s.net_pay ?? s.net_salary)}</td>
                {/* Per-slip PDF download */}
                <td className="px-3 py-2 text-center">
                  <button
                    onClick={() => downloadSlipPdf(s)}
                    disabled={dlSlipId === s.id}
                    className="h-7 w-7 rounded border border-primary/20 bg-primary/8 text-primary hover:bg-primary/20 transition-colors grid place-items-center disabled:opacity-50"
                    data-testid={`pr-pdf-slip-${s.employee_code}`}
                    title={`Download slip PDF ${s.employee_name}`}
                  >
                    {dlSlipId === s.id
                      ? <RefreshCw className="w-3 h-3 animate-spin" />
                      : <FileText className="w-3 h-3" />}
                  </button>
                </td>
                {!locked && (
                  <td className="px-3 py-2">
                    <AdjustCell slip={s} onSave={saveAdjustment} />
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>

        <div className="flex justify-between items-center gap-2 mt-4">
          <p className="text-xs text-muted-foreground">{payslips.length} slip gaji · Klik <FileText className="w-3 h-3 inline" /> untuk unduh per karyawan, atau <FilesIcon className="w-3 h-3 inline" /> untuk semua.</p>
          <Button variant="ghost" onClick={onClose} className="border border-[var(--glass-border)]">Tutup</Button>
        </div>
      </GlassCard>
    </div>
  );
}

/* 2026-11-02 (K34): penyesuaian slip sebelum finalisasi — tambah/kurangi PENDAPATAN, potongan tambahan,
   dan KURANGI baris potongan sistem (terlambat/LWOP/kasbon). BPJS & PPh21 tidak diubah manual. Alasan wajib. */
const NON_EDITABLE = (t) => /^(bpjs|pph21)/.test(String(t || '').toLowerCase());

function AdjustCell({ slip, onSave }) {
  const slipId = slip.id;
  const [open, setOpen] = useState(false);
  const [earning, setEarning] = useState(0);
  const [ded, setDed] = useState(0);
  const [lines, setLines] = useState([]);
  const [n, setN] = useState('');
  const [busy, setBusy] = useState(false);
  const curDed = Number(slip.manual_deduction || 0);
  const curAdd = Number(slip.manual_addition || 0);

  const start = () => {
    setEarning(curAdd); setDed(curDed); setN(slip.adjustment_notes || '');
    setLines((slip.deductions || []).map((d, index) => ({
      index, label: d.label || d.type, type: d.type, amount: Number(d.amount || 0),
      original: Number(d.original_amount ?? d.amount ?? 0),
    })));
    setOpen(true);
  };
  const submit = async () => {
    setBusy(true);
    try {
      const overrides = lines.filter(l => !NON_EDITABLE(l.type) && l.amount !== l.original)
        .map(l => ({ index: l.index, amount: l.amount }));
      const ok = await onSave(slipId, { earning_adjustment: earning, deduction: ded, deduction_overrides: overrides, notes: n });
      if (ok) setOpen(false);
    } finally { setBusy(false); }
  };
  const summary = [curAdd ? `+${curAdd.toLocaleString('id-ID')}` : '', curDed ? `−${curDed.toLocaleString('id-ID')}` : '']
    .filter(Boolean).join(' / ');
  return (
    <>
      <button onClick={start} className="text-xs text-primary hover:underline"
        title={slip.adjustment_notes ? `Alasan: ${slip.adjustment_notes}` : 'Penyesuaian pendapatan/potongan'}
        data-testid={`payslip-adjust-open-${slipId}`}>
        {summary ? `Adj: ${summary}` : 'Adj'}
      </button>
      <Dialog open={open} onOpenChange={o => !o && !busy && setOpen(false)}>
        <DialogContent className="max-w-md" data-testid={`payslip-adjust-dialog-${slipId}`}>
          <DialogHeader>
            <DialogTitle>Penyesuaian slip — {slip.employee_name}</DialogTitle>
            <p className="text-xs text-muted-foreground mt-1">
              Bruto sistem {fmtIDR(slip.gross_before_adjustment ?? (Number(slip.gross_pay || 0) - curAdd))}.
              BPJS &amp; PPh21 tidak dihitung ulang.
            </p>
          </DialogHeader>
          <div className="space-y-3 text-sm">
            <div>
              <Label className="text-xs">Penyesuaian pendapatan (Rp, minus = mengurangi)</Label>
              <MoneyInput unstyled allowNegative value={earning} onChange={e => setEarning(Number(e.target.value))}
                className="mt-1 w-full h-9 px-2 rounded border border-[var(--glass-border)] bg-[var(--input-surface)] font-mono"
                data-testid={`payslip-adjust-earning-${slipId}`} />
            </div>
            <div>
              <Label className="text-xs">Potongan tambahan (Rp, ≥ 0)</Label>
              <MoneyInput unstyled value={ded} onChange={e => setDed(Number(e.target.value))}
                className="mt-1 w-full h-9 px-2 rounded border border-[var(--glass-border)] bg-[var(--input-surface)] font-mono"
                data-testid={`payslip-adjust-amount-${slipId}`} />
            </div>
            {lines.length > 0 && (
              <div className="space-y-1">
                <Label className="text-xs">Kurangi potongan sistem (maks nilai asli)</Label>
                {lines.map(l => (
                  <div key={l.index} className="flex items-center gap-2 text-xs">
                    <span className="flex-1 truncate" title={l.label}>{l.label}</span>
                    {NON_EDITABLE(l.type)
                      ? <span className="font-mono text-muted-foreground">{fmtIDR(l.amount)} (wajib)</span>
                      : <MoneyInput unstyled value={l.amount}
                          onChange={e => setLines(ls => ls.map(x => x.index === l.index ? { ...x, amount: Math.min(Number(e.target.value), x.original) } : x))}
                          className="w-28 h-7 px-2 rounded border border-[var(--glass-border)] bg-[var(--input-surface)] font-mono"
                          data-testid={`payslip-adjust-line-${slipId}-${l.index}`} />}
                  </div>
                ))}
              </div>
            )}
            <div>
              <Label className="text-xs">Alasan *</Label>
              <input type="text" value={n} onChange={e => setN(e.target.value)} placeholder="Wajib bila ada penyesuaian"
                className="mt-1 w-full h-9 px-2 rounded border border-[var(--glass-border)] bg-[var(--input-surface)]"
                data-testid={`payslip-adjust-notes-${slipId}`} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={busy} data-testid={`payslip-adjust-cancel-${slipId}`}>Batal</Button>
            <Button onClick={submit} disabled={busy} data-testid={`payslip-adjust-save-${slipId}`}>{busy ? 'Menyimpan…' : 'Simpan'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

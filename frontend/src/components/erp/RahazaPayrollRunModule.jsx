/**
 * Proses gaji (tab di hub Penggajian) — run gaji per periode: buat, hitung ulang, finalisasi, bayar, batalkan.
 *
 * Standar UI/UX v2 (8 Nov 2026), tampilan saja — semua endpoint, isian, dan aturan (pemisahan tugas, jurnal,
 * BPJS per lembaga, PPh21, pembatalan dua langkah) TIDAK berubah:
 *  • cetakan PageLayout (dulu kepala bergaya kartu + kotak "Langkah Berikutnya" yang memakan tempat → tautan
 *    "Jurnal gaji" di baris alat);
 *  • daftar = TabelData + unduh Excel/CSV; aksi baris dulu 10+ ikon/huruf kecil tanpa label (ikon uang, BK, BT, P, ×) →
 *    paling banyak 1 tombol berlabel + menu "Lainnya" berlabel lengkap;
 *  • rincian run = DetailPopup; semua form (buat run, bayar gaji, bayar BPJS/PPh21, finalisasi, pembatalan,
 *    penyesuaian slip) = FormPopup standar; tanggal = DatePicker.
 */
import { useState, useEffect, useCallback, useReducer, useMemo } from 'react';
import {
  AlertTriangle, BookOpen, CheckCircle, Copy, Download, Eye, FileText, FilesIcon, Lock, MoreHorizontal, Plus,
  RefreshCw, RotateCcw, ShieldAlert, Trash2, Wallet, X,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import DatePicker, { formatTanggalID } from '@/components/ui/date-picker';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';
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
const RUN_STATUS = { draft: 'Draf', finalized: 'Final', cancelled: 'Dibatalkan' };
const runStatusLabel = (s) => RUN_STATUS[s] || s || '—';
const periodeLabel = (r) => `${formatTanggalID(r.period_from) || r.period_from || '—'} – ${formatTanggalID(r.period_to) || r.period_to || '—'}`;
const bayarLabel = (r) => (r.status !== 'finalized' ? '—' : r.payment_status === 'paid' ? 'Dibayar' : 'Belum dibayar');

const _PR_INIT = { runs: [], loading: true };
function _prReducer(s, a) {
  if (a.type === 'loaded') return { ...s, runs: a.runs, loading: false };
  if (a.type === 'loading') return { ...s, loading: true };
  return s;
}

/** Status jurnal buku besar satu run (nomor jurnal finalisasi & pembayaran → buka daftar jurnal). */
function GLStatusBadge({ run, onNavigate }) {
  if (!run.gl_je_number && !run.post_error) {
    if (run.status !== 'finalized') return <span className="text-sm text-muted-foreground">—</span>;
    return <span className="text-sm text-muted-foreground">Belum diposting</span>;
  }
  const buka = onNavigate ? () => onNavigate('fin-journal-list') : undefined;
  return (
    <div className="flex flex-col items-start gap-0.5">
      {run.gl_je_number && (
        <Button variant="link" size="sm" className="h-auto p-0 text-sm" onClick={buka} disabled={!buka}
          title={`Jurnal finalisasi: ${run.gl_je_number}`} data-testid={`gl-badge-${run.run_number}`}>
          {run.gl_je_number}
        </Button>
      )}
      {run.payment_gl_je_number && (
        <Button variant="link" size="sm" className="h-auto p-0 text-sm" onClick={buka} disabled={!buka}
          title={`Jurnal pembayaran: ${run.payment_gl_je_number}`} data-testid={`pay-je-badge-${run.run_number}`}>
          Bayar: {run.payment_gl_je_number}
        </Button>
      )}
      {run.post_error && !run.gl_je_number && (
        <span title={run.post_error}><StatusBadge status="error" label="Jurnal gagal" tone="danger" /></span>
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

  const [saringStatus, setSaringStatus] = useState('');
  const opsiStatus = [
    { key: '', label: 'Semua', count: runs.length },
    ...Object.entries(RUN_STATUS).map(([k, l]) => ({ key: k, label: l, count: runs.filter(r => r.status === k).length }))
      .filter(o => o.count > 0 || o.key === saringStatus),
  ];
  const baris = useMemo(() => runs.filter(r => !saringStatus || r.status === saringStatus), [runs, saringStatus]);
  const { page, setPage, totalPages, total, paged } = useClientPagination(baris, 10);

  /** Aksi baris (aturan tampil sama dengan versi lama; kini berlabel dan dikelompokkan). */
  const aksiUtama = (r) => {
    if (r.status === 'draft') {
      return (
        <Button size="sm" variant="success" onClick={() => finalizeRun(r.id)} data-testid={`pr-finalize-${r.run_number}`}>
          <Lock />Finalisasi
        </Button>
      );
    }
    if (r.status === 'finalized' && r.gl_je_number && r.payment_status !== 'paid') {
      return (
        <Button size="sm" variant="outline" onClick={() => { setPayDialog(r); setPayForm(f => ({ ...f, payment_date: todayWIB() })); }}
          data-testid={`pay-btn-${r.run_number}`}>
          <Wallet />Bayar gaji
        </Button>
      );
    }
    return null;
  };
  const menuLain = (r) => (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="icon-sm" variant="ghost" title="Lainnya" aria-label="Lainnya" data-testid={`pr-more-${r.run_number}`}>
          <MoreHorizontal />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={() => openRun(r.id)} data-testid={`pr-view-${r.run_number}`}>
          <Eye className="mr-2 h-4 w-4" />Lihat rincian slip
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => exportCsv(r.id, r.run_number)} data-testid={`pr-csv-${r.run_number}`}>
          <Download className="mr-2 h-4 w-4" />Unduh CSV
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => downloadRunExcel(r.id, r.run_number)} data-testid={`pr-excel-${r.run_number}`}>
          <FileText className="mr-2 h-4 w-4" />Unduh Excel (rekap, slip, data bank)
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => downloadRunPdf(r.id, r.run_number)} data-testid={`pr-pdf-run-${r.run_number}`}>
          <FilesIcon className="mr-2 h-4 w-4" />Unduh semua slip PDF
        </DropdownMenuItem>
        {r.status === 'draft' && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => recalcRun(r.id)} data-testid={`pr-recalc-${r.run_number}`}>
              <RotateCcw className="mr-2 h-4 w-4" />Hitung ulang (penyesuaian manual tetap)
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => delRun(r.id)} className="text-[hsl(var(--danger-text))]" data-testid={`pr-delete-${r.run_number}`}>
              <Trash2 className="mr-2 h-4 w-4" />Hapus run draf
            </DropdownMenuItem>
          </>
        )}
        {r.status === 'finalized' && r.post_error && (
          <DropdownMenuItem onSelect={() => retryPost(r.id)} data-testid={`pr-retry-${r.run_number}`}>
            <AlertTriangle className="mr-2 h-4 w-4" />Coba posting jurnal lagi
          </DropdownMenuItem>
        )}
        {r.status === 'finalized' && r.gl_je_number && (
          <>
            <DropdownMenuSeparator />
            {r.bpjs_payment_status !== 'paid' && BPJS_AGENCIES.map(([ag, lbl]) => (
              !bpjsPaid(r, ag) && bpjsDue(r, ag) !== 0 && (
                <DropdownMenuItem key={ag} onSelect={() => openObligation(r, 'bpjs', ag)} data-testid={`bpjs-${ag}-btn-${r.run_number}`}>
                  <Wallet className="mr-2 h-4 w-4" />Bayar {lbl}
                </DropdownMenuItem>
              )
            ))}
            {r.pph21_payment_status !== 'paid' && (
              <DropdownMenuItem onSelect={() => openObligation(r, 'pph21')} data-testid={`pph21-btn-${r.run_number}`}>
                <Wallet className="mr-2 h-4 w-4" />Bayar PPh21 ke DJP
              </DropdownMenuItem>
            )}
          </>
        )}
        {r.payment_status === 'paid' && (
          <DropdownMenuItem onSelect={() => voidPayment(r)} className="text-[hsl(var(--danger-text))]" data-testid={`void-pay-btn-${r.run_number}`}>
            <X className="mr-2 h-4 w-4" />Batalkan pembayaran gaji
          </DropdownMenuItem>
        )}
        {/* 2026-11-02 (K34): batalkan run final (jurnal pembalik) */}
        {r.status === 'finalized' && (
          <DropdownMenuItem onSelect={() => { setCancelReason(r.cancel_request?.reason || ''); setCancelDialog(r); }}
            className="text-[hsl(var(--danger-text))]" data-testid={`cancel-run-btn-${r.run_number}`}>
            <X className="mr-2 h-4 w-4" />{r.cancel_request?.status === 'pending' ? 'Tinjau pengajuan pembatalan' : 'Batalkan run (jurnal pembalik)'}
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );

  const kolom = [
    { kunci: 'run', label: 'Nomor run', hp: 'judul', isi: (r) => <span className="font-medium">{r.run_number}</span> },
    { kunci: 'periode', label: 'Periode', hp: 'keterangan', isi: (r) => <span className="text-sm md:whitespace-nowrap">{periodeLabel(r)}</span> },
    { kunci: 'status', label: 'Status', isi: (r) => (
      <div className="flex flex-wrap items-center gap-1">
        <StatusBadge status={r.status} label={runStatusLabel(r.status)} />
        {r.status === 'finalized' && r.payment_status === 'paid' && <StatusBadge status="paid" label="Dibayar" />}
        {r.cancel_request?.status === 'pending' && <StatusBadge status="pending" label="Pembatalan diajukan" tone="warning" />}
        {(r.warnings || []).length > 0 && (
          <span className="inline-flex items-center gap-1 text-xs text-[hsl(var(--warning-text))]"
            title={(r.warnings || []).map(w => `${w.employee_name}: ${w.message}`).join('\n')} data-testid={`run-warn-${r.run_number}`}>
            <AlertTriangle className="h-3.5 w-3.5" />{r.warnings.length} peringatan
          </span>
        )}
      </div>) },
    { kunci: 'karyawan', label: 'Karyawan', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.total_employees ?? '—'}</span> },
    { kunci: 'bruto', label: 'Bruto', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtIDR(r.total_gross)}</span> },
    { kunci: 'potongan', label: 'Potongan', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtIDR(r.total_deductions)}</span> },
    { kunci: 'bersih', label: 'Bersih', rata: 'kanan', isi: (r) => <span className="font-medium tabular-nums">{fmtIDR(r.total_net)}</span> },
    { kunci: 'jurnal', label: 'Jurnal', isi: (r) => <GLStatusBadge run={r} onNavigate={onNavigate} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <div className="flex items-center justify-end gap-1 md:whitespace-nowrap">{aksiUtama(r)}{menuLain(r)}</div>) },
  ];

  const tutupBuat = () => { setCreating(false); setCreateInitial(null); setError(''); };
  const lalu = lastMonthPeriodWIB();

  return (
    <PageLayout testId="rahaza-payroll-run-page" title="Proses gaji"
      subtitle="Buat run gaji per periode, hitung ulang, finalisasi, lalu catat pembayarannya."
      actions={<>
        {/* Salin Bulan Lalu — 1-click period pre-fill */}
        <Button variant="outline" onClick={salinBulanLalu} data-testid="pr-copy-last-month"
          title={`Buat run untuk periode bulan lalu (${formatTanggalID(lalu.from)} – ${formatTanggalID(lalu.to)})`}>
          <Copy />Salin bulan lalu
        </Button>
        <Button onClick={() => { setError(''); setCreateInitial(null); setCreating(true); }} data-testid="pr-create">
          <Plus />Buat proses gaji
        </Button>
      </>}
      filters={runs.length > 0 && <FilterChips options={opsiStatus} value={saringStatus} onChange={setSaringStatus} testId="pr-status" ariaLabel="Status run" />}
      tools={<>
        {/* RC-FLOW-UX Alur 6 — Payroll → Jurnal Gaji (GL); dulu kotak "Langkah Berikutnya" */}
        {typeof onNavigate === 'function' && (
          <Button variant="link" onClick={() => onNavigate('fin-journal-hub')} title="Lihat jurnal akuntansi hasil finalisasi penggajian"
            data-testid="onward-fin-journal-hub"><BookOpen />Jurnal gaji</Button>
        )}
        <TombolUnduh namaBerkas="proses-gaji" namaLembar="Run gaji" baris={baris} testId="pr-unduh"
          kolom={[
            { label: 'Nomor run', nilai: (r) => r.run_number },
            { label: 'Periode dari', nilai: (r) => formatTanggalID(r.period_from) || r.period_from || '' },
            { label: 'Periode sampai', nilai: (r) => formatTanggalID(r.period_to) || r.period_to || '' },
            { label: 'Status', nilai: (r) => runStatusLabel(r.status) },
            { label: 'Pembayaran', nilai: bayarLabel },
            { label: 'Karyawan', nilai: (r) => r.total_employees ?? '' },
            { label: 'Bruto (Rp)', nilai: (r) => Number(r.total_gross || 0) },
            { label: 'Potongan (Rp)', nilai: (r) => Number(r.total_deductions || 0) },
            { label: 'Bersih (Rp)', nilai: (r) => Number(r.total_net || 0) },
            { label: 'Jurnal finalisasi', nilai: (r) => r.gl_je_number || '' },
            { label: 'Jurnal pembayaran', nilai: (r) => r.payment_gl_je_number || '' },
            { label: 'Peringatan', nilai: (r) => (r.warnings || []).length },
          ]} />
        <Button variant="outline" size="icon" onClick={refresh} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="pr-refresh"><RefreshCw className={loading ? 'animate-spin' : ''} /></Button>
      </>}
      footer={baris.length > 10 && <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />}
    >
      {error && !creating && <Notice tone="danger" icon={AlertTriangle} title={error} testId="pr-error" />}

      {loading && runs.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat proses gaji…</p>
      ) : (
        <TabelData kolom={kolom} baris={paged} onKlikBaris={(r) => openRun(r.id)} testId="pr-table"
          kosong={<EmptyState title={runs.length ? 'Tidak ada run dengan status ini' : 'Belum ada proses gaji'}
            description={runs.length ? 'Pilih status lain.' : 'Tekan “Buat proses gaji” atau “Salin bulan lalu” untuk memulai.'} />} />
      )}

      {creating && (
        <CreateRunModal
          onClose={tutupBuat}
          onCreate={createRun}
          token={token}
          initial={createInitial}
          galat={error}
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

      {/* ── Bayar gaji ── */}
      <FormPopup open={!!payDialog} onClose={() => setPayDialog(null)} ukuran="pendek" onSimpan={payGaji} menyimpan={paying}
        bisaSimpan={!!payForm.bank_account_code} labelSimpan="Bayar gaji" testId="pay-dialog"
        judul={`Bayar gaji — ${payDialog?.run_number || ''}`}
        keterangan="Jurnal: debit hutang gaji, kredit rekening yang dipilih.">
        {payDialog && (
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Total dibayar"><span className="font-semibold tabular-nums">{fmtIDR(payDialog.total_net || 0)}</span></BarisDetail>
            <BarisDetail label="Periode">{periodeLabel(payDialog)}</BarisDetail>
          </dl>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Tanggal pembayaran" wajib>
            <DatePicker value={payForm.payment_date} onChange={v => setPayForm(f => ({ ...f, payment_date: v }))}
              bolehKosong={false} testId="pay-date" />
          </Isian>
          <Isian label="Metode">
            <SmartNativeSelect value={payForm.payment_method} searchable={false} data-testid="pay-method"
              onChange={e => setPayForm(f => ({ ...f, payment_method: e.target.value }))}>
              <option value="bank_transfer">Transfer bank</option>
              <option value="cash">Tunai</option>
            </SmartNativeSelect>
          </Isian>
        </div>
        <Isian label="Rekening / kas" wajib>
          {/* Tahap 5: pemilih rekening yang sama dengan form bayar SDM lain (bisa dicari), nilai = kode akun GL */}
          <CashAccountSelect accounts={cashAccounts} loaded={cashLoaded} valueKey="gl_account_code"
            value={payForm.bank_account_code} testId="pay-bank-select"
            onChange={v => setPayForm(f => ({ ...f, bank_account_code: v }))} />
        </Isian>
        <Isian label="Catatan (opsional)">
          <Input placeholder="Keterangan pembayaran" value={payForm.notes}
            onChange={e => setPayForm(f => ({ ...f, notes: e.target.value }))} />
        </Isian>
        <Isian label="Alasan pengecualian" petunjuk="Hanya bila Anda sendiri yang membuat run ini (khusus admin/owner).">
          <Input placeholder="Kosongkan bila Anda bukan pembuat run" value={payForm.override_reason || ''} data-testid="pay-override-reason"
            onChange={e => setPayForm(f => ({ ...f, override_reason: e.target.value }))} />
        </Isian>
      </FormPopup>

      {/* ── Bayar BPJS per lembaga / PPh21 — 2026-11-02 (K22): rekening + tanggal, bukan dialog bawaan peramban ── */}
      <FormPopup open={!!oblDialog} onClose={() => setOblDialog(null)} ukuran="pendek" onSimpan={payObligation} menyimpan={paying}
        bisaSimpan={!!oblForm.cash_account_id && !!oblForm.payment_date} labelSimpan="Bayar" testId="obligation-dialog"
        judul={`${oblDialog?.type === 'bpjs'
          ? `Bayar ${BPJS_AGENCIES.find(([k]) => k === oblDialog?.agency)?.[1] || 'BPJS'}`
          : 'Bayar PPh21 ke DJP'} — ${oblDialog?.run?.run_number || ''}`}>
        {oblDialog?.type === 'bpjs' && (() => {
          const b = (oblDialog.run.bpjs_breakdown || {})[oblDialog.agency];
          return b ? (
            <dl className="divide-y divide-[var(--glass-border)]">
              <BarisDetail label="Potongan karyawan"><span className="tabular-nums">{fmtIDR(b.employee)}</span></BarisDetail>
              <BarisDetail label="Iuran perusahaan"><span className="tabular-nums">{fmtIDR(b.employer)}</span> <span className="text-muted-foreground">(sudah dijurnal)</span></BarisDetail>
              <BarisDetail label="Total dibayar"><span className="font-semibold tabular-nums">{fmtIDR(Number(b.employee || 0) + Number(b.employer || 0))}</span> <span className="text-muted-foreground">· akun hutang {b.payable_code}</span></BarisDetail>
            </dl>
          ) : <p className="text-sm text-muted-foreground">Run lama: nilai = potongan karyawan lembaga ini (akun hutang BPJS lama).</p>;
        })()}
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Tanggal pembayaran" wajib>
            <DatePicker value={oblForm.payment_date} onChange={v => setOblForm(f => ({ ...f, payment_date: v }))}
              bolehKosong={false} testId="obligation-date" />
          </Isian>
          <Isian label="Rekening / kas" wajib>
            <CashAccountSelect accounts={cashAccounts} loaded={cashLoaded} value={oblForm.cash_account_id}
              onChange={v => setOblForm(f => ({ ...f, cash_account_id: v }))} testId="obligation-account" />
          </Isian>
        </div>
      </FormPopup>

      {/* ── Batalkan run final — 2026-11-02 (K34) ── */}
      {(() => {
        const pending = cancelDialog?.cancel_request?.status === 'pending';
        return (
          <FormPopup open={!!cancelDialog} onClose={() => setCancelDialog(null)} ukuran="pendek" menyimpan={paying}
            testId="cancel-run-dialog" judul={`Batalkan run ${cancelDialog?.run_number || ''}`}
            keterangan="Semua jurnal run ini (gaji + potongan kasbon) dibalik, potongan kasbon dikembalikan, dan status menjadi Dibatalkan sehingga periode bisa dibuat ulang. Gaji, BPJS, dan PPh21 yang sudah dibayar harus dibatalkan dulu pembayarannya. Alur: HR mengajukan, Keuangan (orang lain) menyetujui; owner bisa satu langkah."
            onSimpan={() => submitCancel(pending ? 'approve' : 'request')}
            labelSimpan={pending ? 'Setujui & batalkan run' : 'Ajukan pembatalan (HR)'}
            bisaSimpan={pending || !!cancelReason.trim()}
            aksiKiri={pending ? (
              <Button type="button" variant="outline" onClick={() => submitCancel('reject')} disabled={paying} data-testid="cancel-run-reject">
                Tolak pengajuan
              </Button>
            ) : (
              <Button type="button" variant="destructive" onClick={() => submitCancel('approve')} disabled={paying || !cancelReason.trim()}
                title="Hanya owner/superadmin (satu langkah)" data-testid="cancel-run-owner">Batalkan sekarang (owner)</Button>
            )}>
            {pending && (
              <Notice tone="warning" title={`Diajukan oleh ${cancelDialog.cancel_request.requested_by_name || '—'}`}>
                {cancelDialog.cancel_request.reason}
              </Notice>
            )}
            <Isian label="Alasan" wajib={!pending}>
              <Textarea value={cancelReason} onChange={e => setCancelReason(e.target.value)} rows={3} data-testid="cancel-run-reason" />
            </Isian>
          </FormPopup>
        );
      })()}

      {/* ── Finalisasi — 2026-11-06 (Tahap 2): dialog aplikasi + alasan pengecualian pemisahan tugas ── */}
      <FormPopup open={!!finalizeDialog} onClose={() => setFinalizeDialog(null)} ukuran="pendek" onSimpan={submitFinalize}
        menyimpan={paying} labelSimpan="Finalisasi" testId="finalize-dialog"
        judul={`Finalisasi ${finalizeDialog?.run_number || 'run gaji'}`}
        keterangan="Jurnal gaji dibuat dan absensi periode ini dikunci. Sesudahnya slip tidak bisa diubah; koreksi absen masuk run berikutnya. Finalisasi harus oleh pengguna lain dari pembuat run.">
        <Isian label="Alasan pengecualian" petunjuk="Hanya admin/owner yang membuat run ini sendiri.">
          <Input value={overrideReason} onChange={e => setOverrideReason(e.target.value)}
            placeholder="Kosongkan bila Anda bukan pembuat run" data-testid="finalize-override-reason" />
        </Isian>
      </FormPopup>
    </PageLayout>
  );
}

function CreateRunModal({ onClose, onCreate, token, initial, galat }) {
  const today = todayWIB(); // 2026-11-02: tanggal WIB (No.54(a)), bukan UTC
  const defaultFrom = initial?.from || (today.slice(0, 7) + '-01');
  const defaultTo = initial?.to || today;
  const [from, setFrom] = useState(defaultFrom);
  const [to, setTo] = useState(defaultTo);
  const [notes, setNotes] = useState('');
  const [validating, setValidating] = useState(false);
  const [validation, setValidation] = useState(null);
  const [showValidation, setShowValidation] = useState(false);
  const [menyimpan, setMenyimpan] = useState(false);

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
  const gantiPeriode = (setter) => (v) => { setter(v); setValidation(null); setShowValidation(false); };
  const simpan = async () => {
    setMenyimpan(true);
    try { await onCreate({ period_from: from, period_to: to, notes }); } finally { setMenyimpan(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="pendek" onSimpan={simpan} menyimpan={menyimpan} labelSimpan="Buat run"
      bisaSimpan={!!from && !!to} galat={galat} testId="pr-create-form"
      judul="Buat proses gaji baru"
      keterangan={initial ? 'Periode bulan lalu sudah terisi. Run menghitung slip untuk semua karyawan dengan profil gaji aktif.'
        : 'Run menghitung slip untuk semua karyawan dengan profil gaji aktif.'}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Periode dari" wajib>
          <DatePicker value={from} onChange={gantiPeriode(setFrom)} max={to || undefined} bolehKosong={false} testId="pr-create-from" />
        </Isian>
        <Isian label="Periode sampai" wajib>
          <DatePicker value={to} onChange={gantiPeriode(setTo)} min={from || undefined} bolehKosong={false} testId="pr-create-to" />
        </Isian>
      </div>
      <Isian label="Catatan">
        <Input value={notes} onChange={e => setNotes(e.target.value)} placeholder="Opsional" />
      </Isian>

      {/* Attendance Validation */}
      <Isian label="Periksa absensi (opsional)" petunjuk={!showValidation ? 'Lihat karyawan yang absensinya belum lengkap sebelum run dibuat.' : undefined}>
        <div className="space-y-2">
          <Button type="button" variant="outline" size="sm" onClick={validateAttendance} disabled={validating} data-testid="pr-validate-att">
            <ShieldAlert />{validating ? 'Memeriksa…' : 'Periksa sekarang'}
          </Button>
          {showValidation && validation && (
            <div className="space-y-2" data-testid="pr-validation-result">
              {validation.summary.total_warnings === 0 ? (
                <Notice tone="success" icon={CheckCircle}
                  title={`Absensi lengkap untuk semua ${validation.summary.total_employees} karyawan. Siap diproses.`} />
              ) : (
                <>
                  <Notice tone="warning" icon={AlertTriangle}
                    title={`${validation.summary.total_warnings} karyawan punya absensi tidak lengkap.`}>
                    Proses gaji tetap bisa dijalankan.
                  </Notice>
                  <ul className="max-h-40 divide-y divide-[var(--glass-border)] overflow-y-auto rounded-[var(--radius-md)] border border-[var(--glass-border)]">
                    {validation.warnings.slice(0, 10).map(w => (
                      <li key={w.employee_id} className="px-3 py-2 text-sm">
                        <span className={w.severity === 'high' ? 'font-medium text-[hsl(var(--danger-text))]' : 'font-medium text-[hsl(var(--warning-text))]'}>{w.employee_name}</span>
                        <span className="ml-2 text-foreground/80">{w.warning_message}</span>
                      </li>
                    ))}
                  </ul>
                  {validation.warnings.length > 10 && (
                    <p className="text-xs text-muted-foreground">Menampilkan 10 dari {validation.warnings.length} karyawan.</p>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </Isian>
    </FormPopup>
  );
}

const slipUpah = (s) => s.earnings_total ?? s.base_salary;
const slipTunjangan = (s) => s.allowance_total ?? s.meal_allowance;
const slipLembur = (s) => s.overtime_amount ?? s.overtime_pay;
const slipPotongan = (s) => s.deductions_total ?? s.total_deductions;
const slipBersih = (s) => s.net_pay ?? s.net_salary;

function RunDetailModal({ data, token, onClose, onRefresh, onDownloadExcel, onVoidObligation, onRecalc }) {
  const run = data.run;
  const payslips = data.payslips || [];
  // 2026-11-09 (Q8, keputusan owner): Keuangan hanya total run + nilai transfer per karyawan (tanpa komponen slip).
  const rincianTersembunyi = Boolean(data.detail_hidden);
  const transfers = data.transfers || [];
  const jumlahSlip = rincianTersembunyi ? transfers.length : payslips.length;
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

  /* Payslips table
     FASE 20 — kolom di sini DULU membaca skema payslip LAMA (`base_salary`, `transport_allowance`, …,
     `net_salary`). TIDAK SATU PUN field itu dihasilkan `_compute_payslip_for_employee()`, yang menulis
     `earnings_total`, `allowance_total`, `overtime_amount`, `gross_pay`, `deductions_total`, `net_pay`.
     Fallback ke nama lama dipertahankan (backend sendiri melakukannya) supaya payslip lama tetap tampil. */
  const kolomSlip = [
    { kunci: 'karyawan', label: 'Karyawan', hp: 'judul', isi: (s) => (
      <div className="min-w-0"><p className="font-medium">{s.employee_name}</p><p className="text-xs text-muted-foreground">{s.employee_code}</p></div>) },
    { kunci: 'upah', label: 'Upah', rata: 'kanan', isi: (s) => <span className="tabular-nums">{fmtIDR(slipUpah(s))}</span> },
    { kunci: 'tunjangan', label: 'Tunjangan', rata: 'kanan', isi: (s) => <span className="tabular-nums">{fmtIDR(slipTunjangan(s))}</span> },
    { kunci: 'lembur', label: 'Lembur', rata: 'kanan', isi: (s) => <span className="tabular-nums">{fmtIDR(slipLembur(s))}</span> },
    { kunci: 'bruto', label: 'Bruto', rata: 'kanan', isi: (s) => <span className="tabular-nums">{fmtIDR(s.gross_pay)}</span> },
    { kunci: 'potongan', label: 'Potongan', rata: 'kanan', isi: (s) => <span className="tabular-nums">{fmtIDR(slipPotongan(s))}</span> },
    { kunci: 'bersih', label: 'Bersih', rata: 'kanan', isi: (s) => <span className="font-semibold tabular-nums">{fmtIDR(slipBersih(s))}</span> },
    { kunci: 'slip', label: 'Slip', rata: 'tengah', hp: 'aksi', isi: (s) => (
      <Button variant="outline" size="icon-sm" onClick={() => downloadSlipPdf(s)} disabled={dlSlipId === s.id}
        data-testid={`pr-pdf-slip-${s.employee_code}`} title={`Unduh slip PDF ${s.employee_name}`} aria-label={`Unduh slip PDF ${s.employee_name}`}>
        {dlSlipId === s.id ? <RefreshCw className="animate-spin" /> : <FileText />}
      </Button>) },
    ...(!locked ? [{ kunci: 'adj', label: 'Penyesuaian', hp: 'aksi', isi: (s) => <AdjustCell slip={s} onSave={saveAdjustment} /> }] : []),
  ];

  return (
    <DetailPopup open onClose={onClose} judul={run.run_number} testId="pr-detail"
      status={<StatusBadge status={run.status} label={runStatusLabel(run.status)} />}
      keterangan={`${periodeLabel(run)} · ${jumlahSlip} slip gaji`}
      aksi={<>
        {run.status === 'draft' && onRecalc && (
          <Button variant="outline" size="sm" onClick={() => onRecalc(run.id)} data-testid="pr-detail-recalc"
            title="Hitung ulang dari absensi, profil gaji, dan pengaturan terkini; penyesuaian manual tetap">
            <RotateCcw />Hitung ulang
          </Button>
        )}
        <Button variant="outline" size="sm" onClick={() => onDownloadExcel(run.id, run.run_number)} data-testid="pr-download-excel"
          title={rincianTersembunyi ? 'Unduh Excel data transfer bank' : 'Unduh Excel: rekap, slip per karyawan, dan data transfer bank'}>
          <FileText />{rincianTersembunyi ? 'Excel transfer bank' : <>Excel rekap &amp; bank</>}
        </Button>
        {!rincianTersembunyi && (
          <Button variant="outline" size="sm" onClick={downloadAllPdf} disabled={dlAllLoading} data-testid="pr-download-all-pdf"
            title="Unduh PDF semua slip gaji dalam satu berkas">
            {dlAllLoading ? <RefreshCw className="animate-spin" /> : <FilesIcon />}
            {dlAllLoading ? 'Menyiapkan…' : 'PDF semua slip'}
          </Button>
        )}
      </>}>
      {/* Ringkasan = total yang tersimpan di run (sama dengan baris di daftar Proses gaji) */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatTile label="Total bruto" value={fmtIDR(run.total_gross)} sub={`Jumlah bruto ${jumlahSlip} slip`} />
        <StatTile label="Potongan" value={fmtIDR(run.total_deductions)} sub="BPJS, PPh21, kasbon, keterlambatan, dan potongan manual" />
        <StatTile label="Gaji bersih" value={fmtIDR(run.total_net)} accent="success" sub="Yang dibayarkan ke karyawan" />
      </div>

      {/* 2026-11-02 (K24): peringatan lembur bertarif 0 */}
      {(run.warnings || []).length > 0 && (
        <Notice tone="warning" icon={AlertTriangle} title={`${run.warnings.length} peringatan — periksa sebelum finalisasi`} testId="run-warnings">
          <ul className="space-y-0.5">
            {run.warnings.map((w, i) => <li key={`${w.employee_id}-${w.type}-${i}`}><strong>{w.employee_name}</strong> — {w.message}</li>)}
          </ul>
        </Notice>
      )}

      {/* 2026-11-02 (K22/K34): status pembayaran BPJS per lembaga & PPh21 (void diperlukan sebelum batal run) */}
      {run.status !== 'draft' && (
        <dl className="divide-y divide-[var(--glass-border)]" data-testid="run-obligations">
          {run.bpjs_employer_totals && (
            <BarisDetail label="Iuran BPJS perusahaan">
              <span className="tabular-nums">{fmtIDR(run.bpjs_employer_totals.total)}</span>{' '}
              <span className="text-muted-foreground">{run.bpjs_employer_journal ? '(dijurnal)' : '(tidak dijurnal — saklar mati)'}</span>
            </BarisDetail>
          )}
          {BPJS_AGENCIES.map(([ag, lbl]) => bpjsPaid(run, ag) && (
            <BarisDetail key={ag} label={lbl}>
              <span className="text-[hsl(var(--success-text))]">Dibayar · {run.bpjs_payments[ag].je_number}</span>
              {run.status === 'finalized' && (
                <Button variant="link" size="sm" className="ml-2 h-auto p-0" onClick={() => onVoidObligation(run, 'bpjs', ag)}>Batalkan pembayaran</Button>
              )}
            </BarisDetail>
          ))}
          {run.pph21_payment_status === 'paid' && (
            <BarisDetail label="PPh21">
              <span className="text-[hsl(var(--success-text))]">Dibayar · {run.pph21_payment_je}</span>
              {run.status === 'finalized' && (
                <Button variant="link" size="sm" className="ml-2 h-auto p-0" onClick={() => onVoidObligation(run, 'pph21')}>Batalkan pembayaran</Button>
              )}
            </BarisDetail>
          )}
          {run.status === 'cancelled' && (
            <BarisDetail label="Dibatalkan">
              <span className="text-[hsl(var(--danger-text))]">{run.cancelled_by_name}: {run.cancel_reason}</span>
              {(run.cancel_reversal_jes || []).length > 0 && (
                <span className="block text-muted-foreground">Jurnal pembalik: {(run.cancel_reversal_jes || []).map(j => j.reversal).join(', ')}</span>
              )}
            </BarisDetail>
          )}
        </dl>
      )}

      {rincianTersembunyi && (
        <div className="space-y-2">
          <Notice tone="info" icon={ShieldAlert} title="Rincian slip khusus penggajian" testId="pr-transfer-notice">
            Peran Anda melihat total dan nilai transfer per karyawan. Rincian komponen gaji hanya untuk owner, admin, dan HR penggajian.
          </Notice>
          <TabelData baris={transfers} kunci={(t) => t.id || t.employee_id} testId="pr-transfers"
            kolom={[
              { kunci: 'karyawan', label: 'Karyawan', hp: 'judul', isi: (t) => (
                <div className="min-w-0"><p className="font-medium">{t.employee_name}</p><p className="text-xs text-muted-foreground">{t.employee_code}</p></div>) },
              { kunci: 'bank', label: 'Bank', isi: (t) => t.bank_name || '—' },
              { kunci: 'rekening', label: 'No. rekening', isi: (t) => <span className="tabular-nums">{t.bank_account_number || '—'}</span> },
              { kunci: 'bersih', label: 'Gaji bersih', rata: 'kanan', isi: (t) => <span className="font-semibold tabular-nums">{fmtIDR(t.net_pay)}</span> },
            ]}
            kosong={<EmptyState title="Belum ada data transfer" description="Run ini tidak berisi slip gaji." />} />
        </div>
      )}

      {!rincianTersembunyi && <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm font-medium text-foreground">Slip gaji ({payslips.length})</p>
          <TombolUnduh namaBerkas={`slip-gaji-${run.run_number}`} namaLembar="Slip gaji" baris={payslips} testId="pr-slip-unduh"
            kolom={[
              { label: 'Kode karyawan', nilai: (s) => s.employee_code || '' },
              { label: 'Nama', nilai: (s) => s.employee_name || '' },
              { label: 'Upah (Rp)', nilai: (s) => Number(slipUpah(s) || 0) },
              { label: 'Tunjangan (Rp)', nilai: (s) => Number(slipTunjangan(s) || 0) },
              { label: 'Lembur (Rp)', nilai: (s) => Number(slipLembur(s) || 0) },
              { label: 'Bruto (Rp)', nilai: (s) => Number(s.gross_pay || 0) },
              { label: 'Potongan (Rp)', nilai: (s) => Number(slipPotongan(s) || 0) },
              { label: 'Bersih (Rp)', nilai: (s) => Number(slipBersih(s) || 0) },
              { label: 'Alasan penyesuaian', nilai: (s) => s.adjustment_notes || '' },
            ]} />
        </div>
        <TabelData kolom={kolomSlip} baris={payslips} testId="pr-slips"
          kosong={<EmptyState title="Belum ada slip gaji" description="Run ini tidak berisi slip. Periksa profil gaji karyawan lalu hitung ulang." />} />
      </div>}
    </DetailPopup>
  );
}

/* 2026-11-02 (K34): penyesuaian slip sebelum finalisasi — tambah/kurangi PENDAPATAN, potongan tambahan,
   dan KURANGI baris potongan sistem (terlambat/LWOP/kasbon). BPJS & PPh21 tidak diubah manual. Alasan wajib.
   2026-11-09 (H3): server menghitung ulang PPh21 bila penyesuaian mengubah bruto kena pajak (THR/bonus/rapel). */
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
      <Button variant="link" size="sm" className="h-auto p-0" onClick={start}
        title={slip.adjustment_notes ? `Alasan: ${slip.adjustment_notes}` : 'Penyesuaian pendapatan/potongan'}
        data-testid={`payslip-adjust-open-${slipId}`}>
        {summary || 'Sesuaikan'}
      </Button>
      <FormPopup open={open} onClose={() => setOpen(false)} ukuran="pendek" onSimpan={submit} menyimpan={busy}
        testId={`payslip-adjust-dialog-${slipId}`} judul={`Penyesuaian slip — ${slip.employee_name}`}
        keterangan={`Bruto sistem ${fmtIDR(slip.gross_before_adjustment ?? (Number(slip.gross_pay || 0) - curAdd))}. Penyesuaian pendapatan ikut dipotong PPh21 (dihitung ulang otomatis); BPJS tetap dari upah tetap.`}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Penyesuaian pendapatan (Rp)" petunjuk="Minus = mengurangi pendapatan.">
            <MoneyInput allowNegative value={earning} onChange={e => setEarning(Number(e.target.value))}
              data-testid={`payslip-adjust-earning-${slipId}`} />
          </Isian>
          <Isian label="Potongan tambahan (Rp)" petunjuk="Nol atau lebih.">
            <MoneyInput value={ded} onChange={e => setDed(Number(e.target.value))}
              data-testid={`payslip-adjust-amount-${slipId}`} />
          </Isian>
        </div>
        {lines.length > 0 && (
          <Isian label="Kurangi potongan sistem" petunjuk="Paling besar sama dengan nilai aslinya. BPJS dan PPh21 wajib, tidak bisa diubah.">
            <div className="divide-y divide-[var(--glass-border)] rounded-[var(--radius-md)] border border-[var(--glass-border)]">
              {lines.map(l => (
                <div key={l.index} className="flex items-center gap-2 px-3 py-1.5 text-sm">
                  <span className="min-w-0 flex-1 truncate" title={l.label}>{l.label}</span>
                  {NON_EDITABLE(l.type)
                    ? <span className="tabular-nums text-muted-foreground">{fmtIDR(l.amount)} (wajib)</span>
                    : <MoneyInput value={l.amount}
                        onChange={e => setLines(ls => ls.map(x => x.index === l.index ? { ...x, amount: Math.min(Number(e.target.value), x.original) } : x))}
                        className="h-8 w-32"
                        data-testid={`payslip-adjust-line-${slipId}-${l.index}`} />}
                </div>
              ))}
            </div>
          </Isian>
        )}
        <Isian label="Alasan" wajib petunjuk="Wajib bila ada penyesuaian.">
          <Input value={n} onChange={e => setN(e.target.value)} placeholder="Tulis alasan penyesuaian"
            data-testid={`payslip-adjust-notes-${slipId}`} />
        </Isian>
      </FormPopup>
    </>
  );
}

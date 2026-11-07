/**
 * Employee Expense Module — Klaim Biaya Karyawan (Reimbursement)
 * CV. Dewi Aditya — Employee Expense Management (EEM). Tab "Klaim biaya" di menu SDM › Klaim Dinas.
 *
 * Features:
 *  - Karyawan: submit klaim, upload receipt (base64), track status
 *  - Manager/HR: list semua klaim pending, approve/reject (satu per satu atau massal)
 *  - Finance: disburse (bayar) + GL posting otomatis
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout (di hub judul disembunyikan, tombol pindah ke baris tab),
 * penyaring satu baris, TabelData (kartu ringkas di HP), detail = DetailPopup, form = FormPopup
 * (buat klaim, setujui, bayar), tolak = konfirmasi beralasan, DatePicker, unduh Excel + CSV.
 * Perbaikan ikut: daftar dulu hanya 50 klaim pertama (bawaan `limit` server) — kini semua halaman dimuat.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { isFinanceRole } from '../../lib/financeRoles'; // FIN-02
import {
  Plus, RefreshCw, CheckCircle, XCircle, Send, Banknote, Trash2, Eye, Upload, Search, Download,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue
} from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import DatePicker, { formatTanggalID } from '@/components/ui/date-picker';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';
import { toast } from 'sonner';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatRupiah, formatDateID } from '@/lib/format';
import DocNumberField, { useDocNumberPolicy, docNumberPayload } from './docnum/DocNumberField';
import CashAccountSelect, { usePaymentCashAccounts } from './SdmCashAccountSelect';
import { todayWIB } from '../../lib/waktu';

const API = process.env.REACT_APP_BACKEND_URL || '';
const fmt = formatRupiah;
const fmtDate = (s) => formatDateID(s);
const PER_HALAMAN_SERVER = 200; // batas `limit` server /api/hr/expenses/claims

// Phase 4.5: kategori expense dimuat dinamis dari backend
// (`GET /api/hr/expenses/categories` → master `employee_expense_categories`,
//  fallback COA 6-3xxx, fallback konstanta backend).
// CATATAN BUG-FIX 2026-07-25: ClaimForm memuat sendiri kategorinya + fallback aman bila API kosong.
const CATEGORY_FALLBACK = [
  'Transportasi', 'Akomodasi', 'Konsumsi', 'Komunikasi',
  'Alat Tulis Kantor', 'Perjalanan Dinas', 'Lain-lain',
];

const STATUS_CONFIG = {
  draft:     { label: 'Draf',                    tone: 'muted' },
  submitted: { label: 'Menunggu persetujuan',    tone: 'warning' },
  approved:  { label: 'Disetujui',               tone: 'info' },
  rejected:  { label: 'Ditolak',                 tone: 'danger' },
  paid:      { label: 'Sudah dibayar',           tone: 'success' },
  posted:    { label: 'Dibayar & dijurnal',      tone: 'success' },
};
const labelStatus = (s) => STATUS_CONFIG[s]?.label || 'Status lain';

function KlaimStatus({ status }) {
  const c = STATUS_CONFIG[status] || { label: labelStatus(status), tone: 'default' };
  return <StatusBadge status={status} label={c.label} tone={c.tone} />;
}

/** Muat SEMUA klaim hasil saringan (server membatasi 200 per permintaan). */
async function ambilSemuaKlaim(params, headers) {
  const semua = [];
  for (let skip = 0; skip < 20000; skip += PER_HALAMAN_SERVER) {
    const p = new URLSearchParams(params);
    p.set('limit', String(PER_HALAMAN_SERVER));
    p.set('skip', String(skip));
    const r = await fetch(`${API}/api/hr/expenses/claims?${p}`, { headers });
    const d = await r.json();
    const items = Array.isArray(d.items) ? d.items : [];
    semua.push(...items);
    if (items.length < PER_HALAMAN_SERVER || semua.length >= Number(d.total || 0)) break;
  }
  return semua;
}

// ─── Form klaim baru (popup panjang) ─────────────────────────────────────────
function ClaimForm({ token, onClose, onSaved }) {
  const [title, setTitle] = useState('');
  const [items, setItems] = useState([{ date: '', category: '', amount: '', notes: '', receipt_url: '' }]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  // SESI #27 — kolom nomor mengikuti kebijakan Otomatis/Manual milik owner.
  const numPolicy = useDocNumberPolicy('rahaza_expense_claims.claim_number', token);
  const [claimNumber, setClaimNumber] = useState('');
  // Kategori dinamis (master → COA → fallback). Dimuat sekali saat form dibuka.
  const [categories, setCategories] = useState(CATEGORY_FALLBACK.map(n => ({ code: n, name: n, label: n })));

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await fetch(`${API}/api/hr/expenses/categories`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!r.ok) return;
        const d = await r.json();
        const rows = Array.isArray(d?.categories) ? d.categories : [];
        if (alive && rows.length) setCategories(rows);
      } catch {
        /* biarkan fallback dipakai — form tetap bisa diisi */
      }
    })();
    return () => { alive = false; };
  }, [token]);

  const addItem = () => setItems(prev => [...prev, { date: '', category: '', amount: '', notes: '', receipt_url: '' }]);
  const removeItem = (i) => setItems(prev => prev.filter((_, idx) => idx !== i));
  const updateItem = (i, field, val) => setItems(prev => prev.map((it, idx) => idx === i ? { ...it, [field]: val } : it));

  const handleReceiptUpload = (i, file) => {
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) { setError('Ukuran file maksimal 5MB'); return; }
    const reader = new FileReader();
    reader.onload = (e) => updateItem(i, 'receipt_url', e.target.result);
    reader.readAsDataURL(file);
  };

  const total = items.reduce((s, it) => s + (parseFloat(it.amount) || 0), 0);

  const handleSubmit = async () => {
    if (!title.trim()) { setError('Judul klaim wajib diisi'); return; }
    const validItems = items.filter(it => it.date && it.category && parseFloat(it.amount) > 0);
    if (!validItems.length) { setError('Minimal 1 item dengan tanggal, kategori, dan nominal'); return; }
    setSaving(true); setError('');
    try {
      const r = await fetch(`${API}/api/hr/expenses/claims`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title,
          ...docNumberPayload(numPolicy, 'claim_number', claimNumber),
          items: validItems.map(it => ({ ...it, amount: parseFloat(it.amount) })),
        }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'Gagal menyimpan');
      onSaved(d);
    } catch (e) { setError(e.message); }
    finally { setSaving(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" testId="claim-form"
      judul="Klaim biaya baru" keterangan="Disimpan sebagai draf. Ajukan dari rincian klaim agar diproses atasan."
      onSimpan={handleSubmit} labelSimpan="Simpan draf" menyimpan={saving} galat={error}>
      <Isian label="Judul klaim" wajib htmlFor="claim-title">
        <Input id="claim-title" placeholder="Contoh: Biaya perjalanan ke Surabaya" value={title}
          onChange={e => setTitle(e.target.value)} data-testid="claim-title" />
      </Isian>

      <DocNumberField
        policy={numPolicy} value={claimNumber} onChange={setClaimNumber}
        testId="claim-docnum" label="Nomor klaim" />

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-medium text-foreground">Rincian biaya<span className="ml-0.5 text-[hsl(var(--danger-text))]" aria-hidden="true">*</span></p>
          <Button type="button" size="sm" variant="outline" onClick={addItem} data-testid="claim-add-item"><Plus />Tambah baris</Button>
        </div>
        {items.map((it, i) => (
          <div key={i} className="space-y-3 rounded-lg border border-[var(--glass-border)] p-3" data-testid={`claim-item-${i}`}>
            <div className="grid gap-3 sm:grid-cols-2">
              <Isian label="Tanggal">
                <DatePicker value={it.date} onChange={(v) => updateItem(i, 'date', v)} max={todayWIB()}
                  testId={`claim-item-${i}-date`} />
              </Isian>
              <Isian label="Kategori">
                <Select value={it.category} onValueChange={v => updateItem(i, 'category', v)}>
                  <SelectTrigger data-testid={`claim-item-${i}-category`}>
                    <SelectValue placeholder="Pilih kategori" />
                  </SelectTrigger>
                  <SelectContent>{categories.map(c => (
                    <SelectItem key={c.code || c.name} value={c.name || c.code}
                      data-testid={`claim-item-${i}-category-option-${c.code || c.name}`}>
                      {c.label || c.name || c.code}
                    </SelectItem>
                  ))}</SelectContent>
                </Select>
              </Isian>
              <Isian label="Nominal (Rp)">
                <MoneyInput placeholder="0" value={it.amount} onChange={e => updateItem(i, 'amount', e.target.value)}
                  data-testid={`claim-item-${i}-amount`} />
              </Isian>
              <Isian label="Keterangan">
                <Input placeholder="Opsional" value={it.notes} onChange={e => updateItem(i, 'notes', e.target.value)}
                  data-testid={`claim-item-${i}-notes`} />
              </Isian>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button asChild type="button" size="sm" variant="outline">
                <label className="cursor-pointer">
                  <Upload />Foto struk
                  <input type="file" accept="image/*" className="hidden" onChange={e => handleReceiptUpload(i, e.target.files[0])} />
                </label>
              </Button>
              {it.receipt_url && <span className="text-xs font-medium text-[hsl(var(--success-text))]">Struk terunggah</span>}
              {items.length > 1 && (
                <Button type="button" size="icon-sm" variant="ghost" className="ml-auto" onClick={() => removeItem(i)}
                  aria-label={`Hapus baris ${i + 1}`} title="Hapus baris"><Trash2 /></Button>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between border-t border-[var(--glass-border)] pt-3">
        <span className="text-sm font-medium">Total klaim</span>
        <span className="text-base font-semibold tabular-nums" data-testid="claim-total">{fmt(total)}</span>
      </div>
    </FormPopup>
  );
}

// ─── Setujui (popup pendek, catatan opsional) ────────────────────────────────
function ApproveForm({ claim, onClose, aksi }) {
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);
  const simpan = async () => {
    setSaving(true);
    const ok = await aksi(claim, 'approve', { note });
    setSaving(false);
    if (ok) onClose();
  };
  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="claim-approve-form"
      judul={`Setujui klaim ${claim.claim_number || ''}`}
      keterangan={`${claim.employee_name || ''} · ${fmt(claim.total_amount)}`}
      onSimpan={simpan} labelSimpan="Setujui" menyimpan={saving}>
      <Isian label="Catatan" petunjuk="Opsional." htmlFor="claim-approve-note">
        <Textarea id="claim-approve-note" rows={3} value={note} onChange={e => setNote(e.target.value)}
          placeholder="Catatan untuk karyawan atau Keuangan" />
      </Isian>
    </FormPopup>
  );
}

// ─── Bayar (popup pendek) ────────────────────────────────────────────────────
function PayForm({ claim, token, onClose, aksi }) {
  // 2026-11-02 (P5 butir 7): "Bayar" mengirim rekening yang dipilih + tanggal cair (WIB).
  const { accounts, loaded: accLoaded } = usePaymentCashAccounts(token);
  const [payAccount, setPayAccount] = useState('');
  const [payDate, setPayDate] = useState(todayWIB());
  const [saving, setSaving] = useState(false);
  const doAction = async (endpoint, body) => {
    setSaving(true);
    const ok = await aksi(claim, endpoint, body);
    setSaving(false);
    if (ok) onClose();
  };
  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="claim-pay-form"
      judul={`Bayar klaim ${claim.claim_number || ''}`}
      keterangan={`${fmt(claim.total_amount)} untuk ${claim.employee_name || 'karyawan'}. Jurnal dibuat otomatis.`}
      onSimpan={() => doAction('disburse', { payment_method: 'transfer', bank_account_id: payAccount, payment_date: payDate })}
      labelSimpan="Bayar & catat jurnal" menyimpan={saving} bisaSimpan={!!payAccount && !!payDate}>
      <div data-testid="claim-pay-source" className="space-y-4">
        <Isian label="Rekening sumber" wajib>
          <CashAccountSelect accounts={accounts} loaded={accLoaded} value={payAccount} onChange={setPayAccount}
            testId="claim-pay-account" />
        </Isian>
        <Isian label="Tanggal bayar" wajib>
          <DatePicker value={payDate} onChange={setPayDate} bolehKosong={false} testId="claim-pay-date" />
        </Isian>
      </div>
    </FormPopup>
  );
}

// ─── Rincian klaim (popup detail) ────────────────────────────────────────────
function ClaimDetail({ claim, role, onClose, aksi, onApprove, onPay }) {
  const [busy, setBusy] = useState(false);
  const isApprover = ['superadmin','admin','owner','hr','manager','finance'].includes(role?.toLowerCase());
  const isFinance = isFinanceRole(role); // FIN-02
  const items = claim.items || [];

  const jalan = async (endpoint, body) => {
    setBusy(true);
    const ok = await aksi(claim, endpoint, body);
    setBusy(false);
    if (ok) onClose();
  };
  const tolak = async () => {
    const reason = await confirmDialog({
      title: 'Tolak klaim ini?', body: `${claim.claim_number} · ${fmt(claim.total_amount)}. Alasan dikirim ke karyawan.`,
      input: { label: 'Alasan penolakan', placeholder: 'Wajib diisi' }, confirmLabel: 'Tolak', danger: true,
    });
    if (reason) jalan('reject', { reason });
  };

  return (
    <DetailPopup open onClose={onClose} testId="claim-detail"
      judul={`${claim.claim_number} · ${claim.title}`} status={<KlaimStatus status={claim.status} />}
      aksi={<>
        {claim.status === 'draft' && (
          <Button size="sm" onClick={() => jalan('submit')} disabled={busy} data-testid="claim-submit">
            <Send />Ajukan
          </Button>
        )}
        {isApprover && claim.status === 'submitted' && (<>
          <Button size="sm" variant="destructive" onClick={tolak} disabled={busy} data-testid="claim-reject"><XCircle />Tolak</Button>
          <Button size="sm" variant="success" onClick={() => onApprove(claim)} disabled={busy} data-testid="claim-approve">
            <CheckCircle />Setujui
          </Button>
        </>)}
        {isFinance && claim.status === 'approved' && (
          <Button size="sm" variant="success" onClick={() => onPay(claim)} disabled={busy} data-testid="claim-pay">
            <Banknote />Bayar
          </Button>
        )}
      </>}>
      <dl className="divide-y divide-[var(--glass-border)]">
        <BarisDetail label="Nomor klaim"><span className="font-mono">{claim.claim_number}</span></BarisDetail>
        <BarisDetail label="Karyawan">{claim.employee_name}{claim.employee_dept ? ` · ${claim.employee_dept}` : ''}</BarisDetail>
        <BarisDetail label="Total"><span className="font-semibold tabular-nums">{fmt(claim.total_amount)}</span></BarisDetail>
        <BarisDetail label="Dibuat">{fmtDate(claim.created_at)}</BarisDetail>
        {claim.gl_je_number && (
          <BarisDetail label="Jurnal">
            <span className="font-mono">{claim.gl_je_number}</span>
            <span className="text-muted-foreground"> · dibayar oleh {claim.paid_by_name || '—'} pada {fmtDate(claim.paid_at)}</span>
          </BarisDetail>
        )}
      </dl>

      {claim.reject_reason && (
        <Notice tone="danger" title="Alasan ditolak">{claim.reject_reason}</Notice>
      )}

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-medium text-foreground">Rincian biaya ({items.length})</p>
          <TombolUnduh namaBerkas={`klaim-${claim.claim_number || 'rincian'}`} namaLembar="Rincian" baris={items}
            label="Unduh rincian" testId="claim-items-unduh"
            kolom={[
              { label: 'Tanggal', nilai: (it) => formatTanggalID(it.date) || it.date || '' },
              { label: 'Kategori', nilai: (it) => it.category || '' },
              { label: 'Keterangan', nilai: (it) => it.notes || '' },
              { label: 'Nominal', nilai: (it) => Number(it.amount || 0) },
              { label: 'Ada struk', nilai: (it) => (it.receipt_url ? 'Ya' : 'Tidak') },
            ]} />
        </div>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Tanggal</TableHead>
                <TableHead>Kategori</TableHead>
                <TableHead>Keterangan</TableHead>
                <TableHead className="text-right">Nominal</TableHead>
                <TableHead>Struk</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((it, i) => (
                <TableRow key={i}>
                  <TableCell className="whitespace-nowrap">{formatTanggalID(it.date) || it.date || '—'}</TableCell>
                  <TableCell>{it.category || '—'}</TableCell>
                  <TableCell className="text-muted-foreground">{it.notes || '—'}</TableCell>
                  <TableCell className="whitespace-nowrap text-right tabular-nums">{fmt(it.amount)}</TableCell>
                  <TableCell>
                    {it.receipt_url ? (
                      <Button asChild variant="link" size="sm" className="h-auto p-0">
                        <a href={it.receipt_url} target="_blank" rel="noreferrer">Lihat</a>
                      </Button>
                    ) : <span className="text-muted-foreground">—</span>}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>
    </DetailPopup>
  );
}

// ─── Unduh per tanggal (CSV dari server) ─────────────────────────────────────
function ExportForm({ onClose, onExport }) {
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [busy, setBusy] = useState(false);
  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="claim-export-form"
      judul="Unduh klaim per tanggal" keterangan="Berkas CSV dari server, mengikuti status yang sedang dipilih. Tanggal = tanggal klaim dibuat."
      galat={from && to && to < from ? 'Tanggal akhir tidak boleh sebelum tanggal awal.' : undefined}
      bisaSimpan={!(from && to && to < from)} menyimpan={busy} labelSimpan="Unduh CSV"
      onSimpan={async () => { setBusy(true); const ok = await onExport(from, to); setBusy(false); if (ok) onClose(); }}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Dari tanggal" petunjuk="Kosong = sejak awal.">
          <DatePicker value={from} onChange={setFrom} placeholder="Sejak awal" testId="claim-export-from" />
        </Isian>
        <Isian label="Sampai tanggal" petunjuk="Kosong = sampai hari ini.">
          <DatePicker value={to} onChange={setTo} min={from || undefined} placeholder="Sampai hari ini" testId="claim-export-to" />
        </Isian>
      </div>
    </FormPopup>
  );
}

export default function EmployeeExpenseModule({ token, user }) {
  const [claims, setClaims] = useState([]);
  const [loading, setLoading] = useState(true);
  const [summary, setSummary] = useState(null);
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [selected, setSelected] = useState(null);
  const [viewMode, setViewMode] = useState('my'); // 'my' | 'all'
  const [aksiForm, setAksiForm] = useState(null); // { jenis: 'approve'|'pay', claim }
  const [showExport, setShowExport] = useState(false);

  // Phase 4: Bulk
  const [selectedIds, setSelectedIds] = useState([]);
  const [bulkLoading, setBulkLoading] = useState(false);

  const role = user?.role || '';
  const isApprover = ['superadmin','admin','owner','hr','manager','finance'].includes(role.toLowerCase());

  const headers = { Authorization: `Bearer ${token}` };

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filter !== 'all') params.set('status', filter);
      if (search) params.set('search', search);
      if (viewMode === 'my') params.set('employee_id', user?.id || '');
      const [items, sr] = await Promise.all([
        ambilSemuaKlaim(params, headers),
        fetch(`${API}/api/hr/expenses/my-summary`, { headers }).then(r => r.json()),
      ]);
      setClaims(items);
      setSummary(sr);
    } catch (e) { console.error(e); toast.error('Gagal memuat klaim.'); }
    finally { setLoading(false); }
  }, [token, filter, search, viewMode, user?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { fetchData(); }, [fetchData]);

  /** Jalankan aksi klaim (submit/approve/reject/disburse). true bila berhasil. */
  const aksi = async (claim, endpoint, body = {}) => {
    try {
      const r = await fetch(`${API}/api/hr/expenses/claims/${claim.id}/${endpoint}`, {
        method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      if (!r.ok) { const d = await r.json(); throw new Error(typeof d.detail === 'string' ? d.detail : 'Gagal'); }
      fetchData();
      return true;
    } catch (e) { toast.error(e.message); return false; }
  };

  // Phase 4: Export CSV server (rentang tanggal) — RC-23: toast sukses hanya bila backend OK
  const handleExport = async (exportFromDate, exportToDate) => {
    const params = new URLSearchParams();
    if (filter !== 'all') params.set('status', filter);
    if (exportFromDate) params.set('from_date', exportFromDate);
    if (exportToDate) params.set('to_date', exportToDate);
    try {
      const res = await fetch(`${API}/api/hr/expenses/claims/export?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        toast.error(`Unduhan gagal (kode ${res.status}). Coba lagi atau hubungi admin.`);
        return false;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = 'claims-export.csv';
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
      toast.success('Berkas CSV terunduh.');
      return true;
    } catch (e) {
      toast.error('Unduhan gagal: ' + (e?.message || 'jaringan terputus'));
      return false;
    }
  };

  // Phase 4: Bulk approve
  const handleBulkApprove = async () => {
    if (!selectedIds.length) {
      toast.error('Pilih minimal 1 klaim untuk disetujui');
      return;
    }
    if (!(await confirmDialog({ title: `Setujui ${selectedIds.length} klaim?`, confirmLabel: 'Setujui' }))) return;

    setBulkLoading(true);
    try {
      const res = await fetch(`${API}/api/hr/expenses/claims/bulk-approve`, {
        method: 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ claim_ids: selectedIds, approval_note: 'Bulk approved from UI' })
      });
      const data = await res.json();
      if (res.ok) {
        toast.success(`${data.success_count} klaim berhasil disetujui`);
        if (data.failed_count > 0) {
          toast.warning(`${data.failed_count} klaim gagal disetujui (mis. bukan berstatus menunggu persetujuan).`);
          console.warn('Failed:', data.results.failed);
        }
        setSelectedIds([]);
        fetchData();
      } else {
        toast.error(data.detail || 'Gagal menyetujui massal');
      }
    } catch (err) {
      console.error(err);
      toast.error('Terjadi kesalahan');
    } finally {
      setBulkLoading(false);
    }
  };

  const filteredClaims = useMemo(() => claims.filter(c => {
    if (filter !== 'all' && c.status !== filter) return false;
    if (search && !c.claim_number?.toLowerCase().includes(search.toLowerCase()) &&
        !c.title?.toLowerCase().includes(search.toLowerCase()) &&
        !c.employee_name?.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  }), [claims, filter, search]);

  const toggleSelect = (id) => {
    setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  };
  const toggleSelectAll = () => {
    const eligibleIds = filteredClaims.map(c => c.id);
    setSelectedIds(prev => prev.length === eligibleIds.length ? [] : eligibleIds);
  };

  const handleClaimSaved = async (claim) => {
    setShowCreate(false);
    await fetchData();
    // Auto-select untuk detail view
    setSelected(claim);
  };

  const { page, setPage, totalPages, total, paged } = useClientPagination(filteredClaims, 10);

  const kolom = [
    ...(isApprover ? [{
      kunci: 'pilih', hp: 'aksi', lebar: 'w-10',
      label: (
        <Checkbox checked={selectedIds.length === filteredClaims.length && filteredClaims.length > 0}
          onCheckedChange={toggleSelectAll} aria-label="Pilih semua klaim" data-testid="select-all-claims-checkbox" />
      ),
      isi: (c) => (
        <Checkbox checked={selectedIds.includes(c.id)} onCheckedChange={() => toggleSelect(c.id)}
          aria-label={`Pilih ${c.claim_number}`} data-testid={`select-claim-${c.id}`} />
      ),
    }] : []),
    { kunci: 'judul', label: 'Klaim', hp: 'judul', isi: (c) => (
      <div className="min-w-0">
        <p className="font-medium text-foreground">{c.title}</p>
        <p className="font-mono text-xs text-muted-foreground">{c.claim_number}</p>
      </div>) },
    { kunci: 'karyawan', label: 'Karyawan', isi: (c) => (
      <div className="min-w-0">
        <p>{c.employee_name}</p>
        {c.employee_dept && <p className="text-xs text-muted-foreground">{c.employee_dept}</p>}
      </div>) },
    { kunci: 'total', label: 'Total', rata: 'kanan', isi: (c) => (
      <span className="whitespace-nowrap font-semibold tabular-nums">{fmt(c.total_amount)}</span>) },
    { kunci: 'item', label: 'Baris', rata: 'kanan', hp: false, isi: (c) => <span className="tabular-nums">{(c.items || []).length}</span> },
    { kunci: 'status', label: 'Status', isi: (c) => <KlaimStatus status={c.status} /> },
    { kunci: 'tanggal', label: 'Dibuat', isi: (c) => <span className="whitespace-nowrap">{fmtDate(c.created_at)}</span> },
    { kunci: 'lihat', label: '', rata: 'kanan', hp: 'aksi', isi: (c) => (
      <Button size="icon-sm" variant="ghost" onClick={() => setSelected(c)} aria-label="Lihat rincian" title="Lihat rincian"
        data-testid={`claim-open-${c.id}`}>
        <Eye />
      </Button>) },
  ];

  const ec = summary?.expense_claims || {};
  const adaAngka = summary && [ec.total, ec.pending, ec.approved, ec.total_claimed].some((v) => Number(v) > 0);

  return (
    <PageLayout testId="employee-expense-page" title="Klaim biaya"
      subtitle="Ajukan, pantau, dan proses klaim biaya (penggantian) karyawan."
      actions={<Button onClick={() => setShowCreate(true)} data-testid="btn-new-claim"><Plus />Klaim baru</Button>}
      filters={<>
        {isApprover && (
          <FilterChips value={viewMode} onChange={setViewMode} hideWhenEmpty={false} testId="claim-scope"
            ariaLabel="Klaim siapa" options={[{ key: 'my', label: 'Klaim saya' }, { key: 'all', label: 'Semua klaim' }]} />
        )}
        <SmartNativeSelect value={filter} onChange={e => setFilter(e.target.value)} searchable={false}
          className="h-9 w-full" wrapperClassName="w-full sm:w-52" aria-label="Status" data-testid="claim-filter-status">
          <option value="all">Semua status</option>
          <option value="draft">Draf</option>
          <option value="submitted">Menunggu persetujuan</option>
          <option value="approved">Disetujui</option>
          <option value="rejected">Ditolak</option>
          <option value="posted">Sudah dibayar</option>
        </SmartNativeSelect>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder="Cari nomor, judul, karyawan" value={search} onChange={e => setSearch(e.target.value)}
            className="pl-8" data-testid="claim-search" />
        </div>
      </>}
      tools={<>
        <TombolUnduh label={<span className="hidden sm:inline">Unduh</span>} namaBerkas="klaim-biaya" namaLembar="Klaim biaya" baris={filteredClaims} testId="claim-unduh"
          kolom={[
            { label: 'Nomor klaim', nilai: (c) => c.claim_number },
            { label: 'Judul', nilai: (c) => c.title },
            { label: 'Karyawan', nilai: (c) => c.employee_name || '' },
            { label: 'Departemen', nilai: (c) => c.employee_dept || '' },
            { label: 'Jumlah baris', nilai: (c) => (c.items || []).length },
            { label: 'Total', nilai: (c) => Number(c.total_amount || 0) },
            { label: 'Status', nilai: (c) => labelStatus(c.status) },
            { label: 'Dibuat', nilai: (c) => fmtDate(c.created_at) },
            { label: 'Nomor jurnal', nilai: (c) => c.gl_je_number || '' },
          ]} />
        <Button variant="outline" onClick={() => setShowExport(true)} data-testid="claim-export-range"
          title="Unduh CSV per tanggal" aria-label="Unduh per tanggal">
          <Download /><span className="hidden sm:inline">Unduh per tanggal</span>
        </Button>
        <Button variant="outline" size="icon" onClick={fetchData} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={adaAngka ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatTile label="Klaim saya" value={ec.total || 0} sub="Semua status, termasuk draf." />
          <StatTile label="Menunggu persetujuan" value={ec.pending || 0} accent="warning" sub="Klaim saya yang sudah diajukan." />
          <StatTile label="Disetujui" value={ec.approved || 0} accent="success" sub="Klaim saya yang disetujui atau sudah dibayar." />
          <StatTile label="Total diklaim" value={fmt(ec.total_claimed)} sub="Klaim saya yang diajukan, disetujui, dan dibayar." />
        </div>
      ) : null}
      footer={filteredClaims.length > 0 && (
        <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />
      )}>
      {/* Phase 4: baris aksi massal */}
      {selectedIds.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="claim-bulk-bar">
          <span className="font-medium">{selectedIds.length} klaim dipilih</span>
          <Button variant="outline" size="sm" onClick={() => setSelectedIds([])}>Batalkan pilihan</Button>
          {isApprover && (
            <Button size="sm" variant="success" onClick={handleBulkApprove} disabled={bulkLoading} data-testid="bulk-approve-claims-btn">
              <CheckCircle />Setujui terpilih
            </Button>
          )}
        </div>
      )}

      {loading && claims.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat klaim…</p>
      ) : (
        <TabelData kolom={kolom} baris={paged} onKlikBaris={setSelected} testId="claim-table"
          kosong={<EmptyState
            title={claims.length ? 'Tidak ada klaim yang cocok' : 'Belum ada klaim biaya'}
            description={claims.length ? 'Ubah status atau kata pencarian.' : 'Tekan "Klaim baru" untuk mengajukan penggantian biaya pertama.'} />} />
      )}

      {showCreate && (
        <ClaimForm token={token} onClose={() => setShowCreate(false)} onSaved={handleClaimSaved} />
      )}
      {selected && (
        <ClaimDetail claim={selected} role={role} onClose={() => setSelected(null)} aksi={aksi}
          onApprove={(c) => { setSelected(null); setAksiForm({ jenis: 'approve', claim: c }); }}
          onPay={(c) => { setSelected(null); setAksiForm({ jenis: 'pay', claim: c }); }} />
      )}
      {aksiForm?.jenis === 'approve' && (
        <ApproveForm claim={aksiForm.claim} onClose={() => setAksiForm(null)} aksi={aksi} />
      )}
      {aksiForm?.jenis === 'pay' && (
        <PayForm claim={aksiForm.claim} token={token} onClose={() => setAksiForm(null)} aksi={aksi} />
      )}
      {showExport && <ExportForm onClose={() => setShowExport(false)} onExport={handleExport} />}
    </PageLayout>
  );
}

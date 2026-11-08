/**
 * Employee Travel Module — Perjalanan Dinas
 * CV. Dewi Aditya — Employee Expense Management (EEM). Tab "Perjalanan dinas" di menu SDM › Klaim Dinas.
 *
 * Features:
 *  - Submit travel request dengan auto per diem calculation
 *  - Cash advance tracking
 *  - Status flow: draft → submitted → approved → advance_paid → on_trip → completed
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, penyaring satu baris, TabelData (kartu ringkas di HP),
 * detail = DetailPopup, form = FormPopup (pengajuan, setujui, bayar uang muka), tolak = konfirmasi beralasan,
 * DatePicker, unduh Excel + CSV. Perbaikan ikut: daftar dulu hanya 50 pengajuan pertama — kini semua dimuat.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { isFinanceRole } from '../../lib/financeRoles'; // FIN-02
import {
  Plus, RefreshCw, CheckCircle, XCircle, Send, Banknote, Eye, Search, Download,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue
} from '@/components/ui/select';
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
import { formatRupiah } from '@/lib/format';
import DocNumberField, { useDocNumberPolicy, docNumberPayload } from './docnum/DocNumberField';
import CashAccountSelect, { usePaymentCashAccounts } from './SdmCashAccountSelect';
import { todayWIB } from '../../lib/waktu';

const API = process.env.REACT_APP_BACKEND_URL || '';
const fmt = formatRupiah;
// start_date / end_date = tanggal kalender "YYYY-MM-DD" → tampil "10 Nov 2026" tanpa geser zona waktu.
const fmtDate = (s) => (s ? formatTanggalID(s) || s : '—');
const PER_HALAMAN_SERVER = 200; // batas `limit` server /api/hr/expenses/travel

const DEST_TYPES = [
  { value: 'dalam_kota', label: 'Dalam kota' },
  { value: 'luar_kota',  label: 'Luar kota' },
  { value: 'luar_negeri', label: 'Luar negeri' },
];
const labelTujuan = (r) => r.destination_label || DEST_TYPES.find((d) => d.value === r.destination_type)?.label || '—';

const STATUS_CONFIG = {
  draft:        { label: 'Draf',                 tone: 'muted' },
  submitted:    { label: 'Menunggu persetujuan', tone: 'warning' },
  approved:     { label: 'Disetujui',            tone: 'info' },
  rejected:     { label: 'Ditolak',              tone: 'danger' },
  advance_paid: { label: 'Uang muka dibayar',    tone: 'primary' },
  on_trip:      { label: 'Sedang perjalanan',    tone: 'primary' },
  completed:    { label: 'Selesai',              tone: 'success' },
};
const labelStatus = (s) => STATUS_CONFIG[s]?.label || 'Status lain';

function TripStatus({ status }) {
  const c = STATUS_CONFIG[status] || { label: labelStatus(status), tone: 'default' };
  return <StatusBadge status={status} label={c.label} tone={c.tone} />;
}

/** Muat SEMUA pengajuan hasil saringan (server membatasi 200 per permintaan). */
async function ambilSemuaPerjalanan(params, headers) {
  const semua = [];
  for (let skip = 0; skip < 20000; skip += PER_HALAMAN_SERVER) {
    const p = new URLSearchParams(params);
    p.set('limit', String(PER_HALAMAN_SERVER));
    p.set('skip', String(skip));
    const r = await fetch(`${API}/api/hr/expenses/travel?${p}`, { headers });
    const d = await r.json();
    const items = Array.isArray(d.items) ? d.items : [];
    semua.push(...items);
    if (items.length < PER_HALAMAN_SERVER || semua.length >= Number(d.total || 0)) break;
  }
  return semua;
}

// ─── Form pengajuan baru (popup panjang) ─────────────────────────────────────
function TravelForm({ token, onClose, onSaved }) {
  const [form, setForm] = useState({
    destination: '', destination_type: 'luar_kota', purpose: '',
    start_date: '', end_date: '', transport_estimate: '', accommodation_estimate: '',
    other_estimate: '', cash_advance_requested: '', notes: '', use_per_diem: true,
  });
  const [perDiemPreview, setPerDiemPreview] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  // SESI #27 — kolom nomor SPPD mengikuti kebijakan Otomatis/Manual milik owner.
  const numPolicy = useDocNumberPolicy('employee_travel_requests.trip_number', token);
  const [tripNumber, setTripNumber] = useState('');

  const set = (k, v) => setForm(p => ({ ...p, [k]: v }));

  // Tahap 5 (2026-11-07): tarif per diem dari Tarif uang harian (`/per-diem-rates`, bawaan ikut layar itu).
  const [perDiemRates, setPerDiemRates] = useState(null);
  useEffect(() => {
    fetch(`${API}/api/hr/expenses/per-diem-rates`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => (r.ok ? r.json() : { items: [] }))
      .then(d => setPerDiemRates(Object.fromEntries((d.items || []).filter(x => x.is_active !== false)
        .map(x => [x.destination_type, Number(x.daily_rate) || 0]))))
      .catch(() => setPerDiemRates({}));
  }, [token]);

  // Preview per diem
  const fetchPerDiemPreview = useCallback(async () => {
    if (!form.destination_type || !form.start_date || !form.end_date || !perDiemRates) return;
    const days = Math.max(1, Math.ceil((new Date(form.end_date) - new Date(form.start_date)) / 86400000) + 1);
    const daily = perDiemRates[form.destination_type];
    setPerDiemPreview(daily === undefined ? null : { per_diem_daily: daily, days_count: days, per_diem_total: daily * days });
  }, [form.destination_type, form.start_date, form.end_date, perDiemRates]);

  useEffect(() => { fetchPerDiemPreview(); }, [fetchPerDiemPreview]);

  const calcTotal = () => {
    const pd = form.use_per_diem ? (perDiemPreview?.per_diem_total || 0) : 0;
    return pd + (parseFloat(form.transport_estimate) || 0) +
      (parseFloat(form.accommodation_estimate) || 0) +
      (parseFloat(form.other_estimate) || 0);
  };

  const handleSubmit = async () => {
    if (!form.destination.trim() || !form.purpose.trim()) { setError('Destinasi dan tujuan wajib diisi'); return; }
    if (!form.start_date || !form.end_date) { setError('Tanggal berangkat dan pulang wajib diisi'); return; }
    if (new Date(form.end_date) < new Date(form.start_date)) { setError('Tanggal pulang tidak boleh sebelum tanggal berangkat'); return; }
    setSaving(true); setError('');
    try {
      const body = {
        ...form,
        ...docNumberPayload(numPolicy, 'trip_number', tripNumber),
        transport_estimate: parseFloat(form.transport_estimate) || 0,
        accommodation_estimate: parseFloat(form.accommodation_estimate) || 0,
        other_estimate: parseFloat(form.other_estimate) || 0,
        cash_advance_requested: parseFloat(form.cash_advance_requested) || 0,
      };
      const r = await fetch(`${API}/api/hr/expenses/travel`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'Gagal menyimpan');
      onSaved(d);
    } catch (e) { setError(e.message); }
    finally { setSaving(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" testId="travel-form"
      judul="Pengajuan perjalanan dinas" keterangan="Disimpan sebagai draf. Ajukan dari rincian agar diproses atasan."
      onSimpan={handleSubmit} labelSimpan="Simpan draf" menyimpan={saving} galat={error}>
      <DocNumberField
        policy={numPolicy} value={tripNumber} onChange={setTripNumber}
        testId="travel-docnum" label="Nomor perjalanan dinas" />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Isian label="Destinasi" wajib htmlFor="travel-destination">
          <Input id="travel-destination" placeholder="Contoh: Surabaya, Jawa Timur" value={form.destination}
            onChange={e => set('destination', e.target.value)} data-testid="travel-destination" />
        </Isian>
        <Isian label="Jenis perjalanan">
          <Select value={form.destination_type} onValueChange={v => set('destination_type', v)}>
            <SelectTrigger data-testid="travel-destination-type"><SelectValue /></SelectTrigger>
            <SelectContent>{DEST_TYPES.map(d => <SelectItem key={d.value} value={d.value}>{d.label}</SelectItem>)}</SelectContent>
          </Select>
        </Isian>
        <Isian label="Tanggal berangkat" wajib>
          <DatePicker value={form.start_date} onChange={v => set('start_date', v)} testId="travel-start-date" />
        </Isian>
        <Isian label="Tanggal kembali" wajib>
          <DatePicker value={form.end_date} onChange={v => set('end_date', v)} min={form.start_date || undefined}
            testId="travel-end-date" />
        </Isian>
      </div>

      <Isian label="Tujuan / agenda" wajib htmlFor="travel-purpose">
        <Textarea id="travel-purpose" placeholder="Jelaskan tujuan dan agenda perjalanan dinas" value={form.purpose}
          onChange={e => set('purpose', e.target.value)} rows={2} />
      </Isian>

      {/* Pratinjau uang harian (tarif dari tab Tarif uang harian) */}
      {perDiemPreview && (
        <div className="space-y-1 rounded-lg border border-[var(--glass-border)] p-3" data-testid="travel-perdiem-preview">
          <label className="flex items-center gap-2 text-sm font-medium" htmlFor="travel-use-perdiem">
            <Checkbox id="travel-use-perdiem" checked={form.use_per_diem} onCheckedChange={v => set('use_per_diem', v === true)} />
            Pakai uang harian
          </label>
          {form.use_per_diem && (
            <p className="text-sm text-muted-foreground">
              {fmt(perDiemPreview.per_diem_daily)} × {perDiemPreview.days_count} hari ={' '}
              <span className="font-semibold text-foreground tabular-nums">{fmt(perDiemPreview.per_diem_total)}</span>
            </p>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Isian label="Perkiraan transport (Rp)">
          <MoneyInput placeholder="0" value={form.transport_estimate} onChange={e => set('transport_estimate', e.target.value)} />
        </Isian>
        <Isian label="Perkiraan akomodasi (Rp)">
          <MoneyInput placeholder="0" value={form.accommodation_estimate} onChange={e => set('accommodation_estimate', e.target.value)} />
        </Isian>
        <Isian label="Biaya lain (Rp)">
          <MoneyInput placeholder="0" value={form.other_estimate} onChange={e => set('other_estimate', e.target.value)} />
        </Isian>
        <Isian label="Uang muka diminta (Rp)">
          <MoneyInput placeholder="0" value={form.cash_advance_requested} onChange={e => set('cash_advance_requested', e.target.value)} />
        </Isian>
      </div>

      <Isian label="Catatan" htmlFor="travel-notes">
        <Textarea id="travel-notes" placeholder="Informasi tambahan (opsional)" value={form.notes}
          onChange={e => set('notes', e.target.value)} rows={2} />
      </Isian>

      <div className="flex items-center justify-between border-t border-[var(--glass-border)] pt-3">
        <span className="text-sm font-medium">Perkiraan total anggaran</span>
        <span className="text-base font-semibold tabular-nums" data-testid="travel-total">{fmt(calcTotal())}</span>
      </div>
    </FormPopup>
  );
}

// ─── Setujui (popup pendek) ──────────────────────────────────────────────────
function ApproveForm({ req, onClose, aksi }) {
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);
  const simpan = async () => {
    setSaving(true);
    const ok = await aksi(req, 'approve', { note, cash_advance_approved: req.cash_advance_requested });
    setSaving(false);
    if (ok) onClose();
  };
  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="travel-approve-form"
      judul={`Setujui ${req.trip_number || 'perjalanan dinas'}`}
      keterangan={`${req.employee_name || ''} · ${req.destination || ''}. Uang muka disetujui sebesar yang diminta (${fmt(req.cash_advance_requested || 0)}).`}
      onSimpan={simpan} labelSimpan="Setujui" menyimpan={saving}>
      <Isian label="Catatan" petunjuk="Opsional." htmlFor="travel-approve-note">
        <Textarea id="travel-approve-note" rows={3} value={note} onChange={e => setNote(e.target.value)}
          placeholder="Catatan untuk karyawan atau Keuangan" />
      </Isian>
    </FormPopup>
  );
}

// ─── Bayar uang muka (popup pendek) ──────────────────────────────────────────
function AdvanceForm({ req, token, onClose, aksi }) {
  // 2026-11-02 (P5 butir 7): rekening sumber + tanggal bayar uang muka (WIB) dikirim ke backend.
  const { accounts, loaded: accLoaded } = usePaymentCashAccounts(token);
  const [payAccount, setPayAccount] = useState('');
  const [payDate, setPayDate] = useState(todayWIB());
  const [advanceAmount, setAdvanceAmount] = useState('');
  const [saving, setSaving] = useState(false);
  const doAction = async (endpoint, body) => {
    setSaving(true);
    const ok = await aksi(req, endpoint, body);
    setSaving(false);
    if (ok) onClose();
  };
  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="travel-advance-form"
      judul={`Bayar uang muka ${req.trip_number || ''}`}
      keterangan={`Disetujui ${fmt(req.cash_advance_approved || 0)} untuk ${req.employee_name || 'karyawan'}.`}
      onSimpan={() => doAction('advance-paid', { amount_paid: parseFloat(advanceAmount) || req.cash_advance_approved, bank_account_id: payAccount, payment_date: payDate })}
      labelSimpan="Bayar" menyimpan={saving} bisaSimpan={!!payAccount && !!payDate}>
      <Isian label="Rekening sumber" wajib>
        <CashAccountSelect accounts={accounts} loaded={accLoaded} value={payAccount} onChange={setPayAccount}
          testId="travel-advance-account" />
      </Isian>
      <Isian label="Tanggal bayar" wajib>
        <DatePicker value={payDate} onChange={setPayDate} bolehKosong={false} testId="travel-advance-date" />
      </Isian>
      <Isian label="Jumlah dibayar (Rp)" petunjuk={`Kosong = sebesar yang disetujui (${fmt(req.cash_advance_approved || 0)}).`}>
        <MoneyInput placeholder={String(req.cash_advance_approved || 0)} value={advanceAmount}
          onChange={e => setAdvanceAmount(e.target.value)} data-testid="travel-advance-amount" />
      </Isian>
    </FormPopup>
  );
}

// ─── Rincian perjalanan (popup detail) ───────────────────────────────────────
function TravelDetail({ req, role, onClose, aksi, onApprove, onPay }) {
  const [busy, setBusy] = useState(false);
  const isApprover = ['superadmin','admin','owner','hr','manager','finance'].includes(role?.toLowerCase());
  const isFinance = isFinanceRole(role); // FIN-02

  const jalan = async (endpoint, body) => {
    setBusy(true);
    const ok = await aksi(req, endpoint, body);
    setBusy(false);
    if (ok) onClose();
  };
  const tolak = async () => {
    const reason = await confirmDialog({
      title: 'Tolak pengajuan ini?', body: `${req.trip_number} · ${req.destination}. Alasan dikirim ke karyawan.`,
      input: { label: 'Alasan penolakan', placeholder: 'Wajib diisi' }, confirmLabel: 'Tolak', danger: true,
    });
    if (reason) jalan('reject', { reason });
  };

  return (
    <DetailPopup open onClose={onClose} testId="travel-detail"
      judul={`${req.trip_number} · ${req.destination}`} status={<TripStatus status={req.status} />}
      aksi={<>
        {req.status === 'draft' && (
          <Button size="sm" onClick={() => jalan('submit')} disabled={busy} data-testid="travel-submit"><Send />Ajukan</Button>
        )}
        {isApprover && req.status === 'submitted' && (<>
          <Button size="sm" variant="destructive" onClick={tolak} disabled={busy} data-testid="travel-reject"><XCircle />Tolak</Button>
          <Button size="sm" variant="success" onClick={() => onApprove(req)} disabled={busy} data-testid="travel-approve">
            <CheckCircle />Setujui
          </Button>
        </>)}
        {isFinance && req.status === 'approved' && (
          <Button size="sm" variant="success" onClick={() => onPay(req)} disabled={busy} data-testid="travel-pay-advance">
            <Banknote />Bayar uang muka
          </Button>
        )}
        {['approved', 'advance_paid', 'on_trip'].includes(req.status) && (
          <Button size="sm" variant="outline" onClick={() => jalan('complete')} disabled={busy} data-testid="travel-complete">
            <CheckCircle />Tandai selesai
          </Button>
        )}
      </>}>
      <dl className="divide-y divide-[var(--glass-border)]">
        <BarisDetail label="Nomor"><span className="tabular-nums">{req.trip_number}</span></BarisDetail>
        <BarisDetail label="Karyawan">{req.employee_name}{req.employee_dept ? ` · ${req.employee_dept}` : ''}</BarisDetail>
        <BarisDetail label="Jenis perjalanan">{labelTujuan(req)}</BarisDetail>
        <BarisDetail label="Destinasi">{req.destination}</BarisDetail>
        <BarisDetail label="Tanggal">{fmtDate(req.start_date)} s/d {fmtDate(req.end_date)}{req.days_count ? ` · ${req.days_count} hari` : ''}</BarisDetail>
        <BarisDetail label="Tujuan">{req.purpose || '—'}</BarisDetail>
        {req.notes && <BarisDetail label="Catatan">{req.notes}</BarisDetail>}
      </dl>

      <div>
        <p className="mb-1 text-sm font-medium text-foreground">Rincian anggaran</p>
        <dl className="divide-y divide-[var(--glass-border)] tabular-nums">
          {req.use_per_diem && <BarisDetail label={`Uang harian (${req.days_count} hari)`}>{fmt(req.per_diem_total)}</BarisDetail>}
          {req.transport_estimate > 0 && <BarisDetail label="Transport">{fmt(req.transport_estimate)}</BarisDetail>}
          {req.accommodation_estimate > 0 && <BarisDetail label="Akomodasi">{fmt(req.accommodation_estimate)}</BarisDetail>}
          {req.other_estimate > 0 && <BarisDetail label="Lain-lain">{fmt(req.other_estimate)}</BarisDetail>}
          <BarisDetail label="Total anggaran"><span className="font-semibold">{fmt(req.total_budget)}</span></BarisDetail>
          {req.cash_advance_requested > 0 && <BarisDetail label="Uang muka diminta">{fmt(req.cash_advance_requested)}</BarisDetail>}
          {req.cash_advance_approved > 0 && <BarisDetail label="Uang muka disetujui"><span className="font-semibold">{fmt(req.cash_advance_approved)}</span></BarisDetail>}
          {req.cash_advance_paid > 0 && <BarisDetail label="Uang muka dibayar"><span className="font-semibold text-[hsl(var(--success-text))]">{fmt(req.cash_advance_paid)}</span></BarisDetail>}
        </dl>
      </div>

      {req.reject_reason && (
        <Notice tone="danger" title="Alasan ditolak">{req.reject_reason}</Notice>
      )}
    </DetailPopup>
  );
}

// ─── Unduh per tanggal (CSV dari server) ─────────────────────────────────────
function ExportForm({ onClose, onExport }) {
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [busy, setBusy] = useState(false);
  const salah = from && to && to < from;
  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="travel-export-form"
      judul="Unduh perjalanan dinas per tanggal" keterangan="Berkas CSV dari server, mengikuti status yang sedang dipilih."
      galat={salah ? 'Tanggal akhir tidak boleh sebelum tanggal awal.' : undefined}
      bisaSimpan={!salah} menyimpan={busy} labelSimpan="Unduh CSV"
      onSimpan={async () => { setBusy(true); const ok = await onExport(from, to); setBusy(false); if (ok) onClose(); }}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Dari tanggal" petunjuk="Kosong = sejak awal.">
          <DatePicker value={from} onChange={setFrom} placeholder="Sejak awal" testId="travel-export-from" />
        </Isian>
        <Isian label="Sampai tanggal" petunjuk="Kosong = sampai hari ini.">
          <DatePicker value={to} onChange={setTo} min={from || undefined} placeholder="Sampai hari ini" testId="travel-export-to" />
        </Isian>
      </div>
    </FormPopup>
  );
}

export default function EmployeeTravelModule({ token, user }) {
  const [reqs, setReqs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [summary, setSummary] = useState(null);
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [selected, setSelected] = useState(null);
  const [viewMode, setViewMode] = useState('my');
  const [aksiForm, setAksiForm] = useState(null); // { jenis: 'approve'|'advance', req }
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
        ambilSemuaPerjalanan(params, headers),
        fetch(`${API}/api/hr/expenses/my-summary`, { headers }).then(r => r.json()),
      ]);
      setReqs(items);
      setSummary(sr);
    } catch (e) { console.error(e); toast.error('Gagal memuat perjalanan dinas.'); }
    finally { setLoading(false); }
  }, [token, filter, search, viewMode, user?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { fetchData(); }, [fetchData]);

  /** Jalankan aksi perjalanan (submit/approve/reject/advance-paid/complete). true bila berhasil. */
  const aksi = async (req, endpoint, body = {}) => {
    try {
      const r = await fetch(`${API}/api/hr/expenses/travel/${req.id}/${endpoint}`, {
        method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      if (!r.ok) { const d = await r.json(); throw new Error(typeof d.detail === 'string' ? d.detail : 'Gagal'); }
      fetchData();
      return true;
    } catch (e) { toast.error(e.message); return false; }
  };

  // Phase 4: Export CSV server — RC-23: toast sukses hanya bila backend OK
  const handleExport = async (exportFromDate, exportToDate) => {
    const params = new URLSearchParams();
    if (filter !== 'all') params.set('status', filter);
    if (exportFromDate) params.set('from_date', exportFromDate);
    if (exportToDate) params.set('to_date', exportToDate);
    try {
      const res = await fetch(`${API}/api/hr/expenses/travel/export?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        toast.error(`Unduhan gagal (kode ${res.status}). Coba lagi atau hubungi admin.`);
        return false;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = 'travel-export.csv';
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
      toast.error('Pilih minimal 1 pengajuan untuk disetujui');
      return;
    }
    if (!(await confirmDialog({ title: `Setujui ${selectedIds.length} pengajuan perjalanan dinas?`, confirmLabel: 'Setujui' }))) return;

    setBulkLoading(true);
    try {
      const res = await fetch(`${API}/api/hr/expenses/travel/bulk-approve`, {
        method: 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ travel_ids: selectedIds, approval_note: 'Bulk approved from UI' })
      });
      const data = await res.json();
      if (res.ok) {
        toast.success(`${data.success_count} pengajuan berhasil disetujui`);
        if (data.failed_count > 0) {
          toast.warning(`${data.failed_count} pengajuan gagal disetujui (mis. bukan berstatus menunggu persetujuan).`);
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

  const filteredReqs = useMemo(() => reqs.filter(r => {
    if (filter !== 'all' && r.status !== filter) return false;
    if (search && !r.trip_number?.toLowerCase().includes(search.toLowerCase()) &&
        !r.destination?.toLowerCase().includes(search.toLowerCase()) &&
        !r.employee_name?.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  }), [reqs, filter, search]);

  const toggleSelect = (id) => {
    setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  };
  const toggleSelectAll = () => {
    const eligibleIds = filteredReqs.map(r => r.id);
    setSelectedIds(prev => prev.length === eligibleIds.length ? [] : eligibleIds);
  };

  const { page, setPage, totalPages, total, paged } = useClientPagination(filteredReqs, 10);

  const kolom = [
    ...(isApprover ? [{
      kunci: 'pilih', hp: 'aksi', lebar: 'w-10',
      label: (
        <Checkbox checked={selectedIds.length === filteredReqs.length && filteredReqs.length > 0}
          onCheckedChange={toggleSelectAll} aria-label="Pilih semua pengajuan" data-testid="select-all-travel-checkbox" />
      ),
      isi: (r) => (
        <Checkbox checked={selectedIds.includes(r.id)} onCheckedChange={() => toggleSelect(r.id)}
          aria-label={`Pilih ${r.trip_number}`} data-testid={`select-travel-${r.id}`} />
      ),
    }] : []),
    { kunci: 'tujuan', label: 'Destinasi', hp: 'judul', isi: (r) => (
      <div className="min-w-0">
        <p className="font-medium text-foreground">{r.destination}</p>
        <p className="text-xs text-muted-foreground"><span className="tabular-nums">{r.trip_number}</span> · {labelTujuan(r)}</p>
      </div>) },
    { kunci: 'karyawan', label: 'Karyawan', isi: (r) => (
      <div className="min-w-0">
        <p>{r.employee_name}</p>
        {r.employee_dept && <p className="text-xs text-muted-foreground">{r.employee_dept}</p>}
      </div>) },
    { kunci: 'tanggal', label: 'Tanggal', isi: (r) => (
      <div className="whitespace-nowrap">
        <p>{fmtDate(r.start_date)} – {fmtDate(r.end_date)}</p>
        {r.days_count ? <p className="text-xs text-muted-foreground">{r.days_count} hari</p> : null}
      </div>) },
    { kunci: 'anggaran', label: 'Anggaran', rata: 'kanan', isi: (r) => (
      <div className="whitespace-nowrap">
        <p className="font-semibold tabular-nums">{fmt(r.total_budget)}</p>
        {r.cash_advance_requested > 0 && <p className="text-xs text-muted-foreground">Uang muka {fmt(r.cash_advance_requested)}</p>}
      </div>) },
    { kunci: 'status', label: 'Status', isi: (r) => <TripStatus status={r.status} /> },
    { kunci: 'lihat', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <Button size="icon-sm" variant="ghost" onClick={() => setSelected(r)} aria-label="Lihat rincian" title="Lihat rincian"
        data-testid={`travel-open-${r.id}`}>
        <Eye />
      </Button>) },
  ];

  const tr = summary?.travel_requests || {};
  const adaAngka = summary && [tr.total, tr.pending, tr.active].some((v) => Number(v) > 0);

  return (
    <PageLayout testId="employee-travel-page" title="Perjalanan dinas"
      subtitle="Ajukan, pantau, dan proses perjalanan dinas beserta uang mukanya."
      actions={<Button onClick={() => setShowCreate(true)} data-testid="btn-new-travel"><Plus />Pengajuan baru</Button>}
      filters={<>
        {isApprover && (
          <FilterChips value={viewMode} onChange={setViewMode} hideWhenEmpty={false} testId="travel-scope"
            ariaLabel="Pengajuan siapa" options={[{ key: 'my', label: 'Pengajuan saya' }, { key: 'all', label: 'Semua pengajuan' }]} />
        )}
        <SmartNativeSelect value={filter} onChange={e => setFilter(e.target.value)} searchable={false}
          className="h-9 w-full" wrapperClassName="w-full sm:w-52" aria-label="Status" data-testid="travel-filter-status">
          <option value="all">Semua status</option>
          <option value="draft">Draf</option>
          <option value="submitted">Menunggu persetujuan</option>
          <option value="approved">Disetujui</option>
          <option value="advance_paid">Uang muka dibayar</option>
          <option value="on_trip">Sedang perjalanan</option>
          <option value="completed">Selesai</option>
          <option value="rejected">Ditolak</option>
        </SmartNativeSelect>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder="Cari nomor, destinasi, karyawan" value={search} onChange={e => setSearch(e.target.value)}
            className="pl-8" data-testid="travel-search" />
        </div>
      </>}
      tools={<>
        <TombolUnduh label={<span className="hidden sm:inline">Unduh</span>} namaBerkas="perjalanan-dinas" namaLembar="Perjalanan dinas" baris={filteredReqs} testId="travel-unduh"
          kolom={[
            { label: 'Nomor', nilai: (r) => r.trip_number },
            { label: 'Karyawan', nilai: (r) => r.employee_name || '' },
            { label: 'Departemen', nilai: (r) => r.employee_dept || '' },
            { label: 'Destinasi', nilai: (r) => r.destination || '' },
            { label: 'Jenis perjalanan', nilai: (r) => labelTujuan(r) },
            { label: 'Berangkat', nilai: (r) => fmtDate(r.start_date) },
            { label: 'Kembali', nilai: (r) => fmtDate(r.end_date) },
            { label: 'Jumlah hari', nilai: (r) => Number(r.days_count || 0) },
            { label: 'Total anggaran', nilai: (r) => Number(r.total_budget || 0) },
            { label: 'Uang muka diminta', nilai: (r) => Number(r.cash_advance_requested || 0) },
            { label: 'Uang muka dibayar', nilai: (r) => Number(r.cash_advance_paid || 0) },
            { label: 'Status', nilai: (r) => labelStatus(r.status) },
          ]} />
        <Button variant="outline" onClick={() => setShowExport(true)} data-testid="travel-export-range"
          title="Unduh CSV per tanggal" aria-label="Unduh per tanggal">
          <Download /><span className="hidden sm:inline">Unduh per tanggal</span>
        </Button>
        <Button variant="outline" size="icon" onClick={fetchData} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={adaAngka ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
          <StatTile label="Pengajuan saya" value={tr.total || 0} sub="Semua status, termasuk draf." />
          <StatTile label="Menunggu persetujuan" value={tr.pending || 0} accent="warning" sub="Pengajuan saya yang sudah diajukan." />
          <StatTile label="Sedang berjalan" value={tr.active || 0} sub="Disetujui, uang muka dibayar, atau sedang perjalanan." />
        </div>
      ) : null}
      footer={filteredReqs.length > 0 && (
        <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />
      )}>
      {/* Phase 4: baris aksi massal */}
      {selectedIds.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="travel-bulk-bar">
          <span className="font-medium">{selectedIds.length} pengajuan dipilih</span>
          <Button variant="outline" size="sm" onClick={() => setSelectedIds([])}>Batalkan pilihan</Button>
          {isApprover && (
            <Button size="sm" variant="success" onClick={handleBulkApprove} disabled={bulkLoading} data-testid="bulk-approve-travel-btn">
              <CheckCircle />Setujui terpilih
            </Button>
          )}
        </div>
      )}

      {loading && reqs.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat perjalanan dinas…</p>
      ) : (
        <TabelData kolom={kolom} baris={paged} onKlikBaris={setSelected} testId="travel-table"
          kosong={<EmptyState
            title={reqs.length ? 'Tidak ada pengajuan yang cocok' : 'Belum ada pengajuan perjalanan dinas'}
            description={reqs.length ? 'Ubah status atau kata pencarian.' : 'Tekan "Pengajuan baru" untuk mengajukan perjalanan dinas.'} />} />
      )}

      {showCreate && (
        <TravelForm token={token} onClose={() => setShowCreate(false)}
          onSaved={(d) => { setShowCreate(false); fetchData(); setSelected(d); }} />
      )}
      {selected && (
        <TravelDetail req={selected} role={role} onClose={() => setSelected(null)} aksi={aksi}
          onApprove={(r) => { setSelected(null); setAksiForm({ jenis: 'approve', req: r }); }}
          onPay={(r) => { setSelected(null); setAksiForm({ jenis: 'advance', req: r }); }} />
      )}
      {aksiForm?.jenis === 'approve' && <ApproveForm req={aksiForm.req} onClose={() => setAksiForm(null)} aksi={aksi} />}
      {aksiForm?.jenis === 'advance' && (
        <AdvanceForm req={aksiForm.req} token={token} onClose={() => setAksiForm(null)} aksi={aksi} />
      )}
      {showExport && <ExportForm onClose={() => setShowExport(false)} onExport={handleExport} />}
    </PageLayout>
  );
}

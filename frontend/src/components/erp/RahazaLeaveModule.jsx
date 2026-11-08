/**
 * RahazaLeaveModule — pengajuan cuti, izin, sakit + master jenis cuti (Portal SDM › Cuti & Lembur).
 *
 * Standar UI/UX v2 (8 Nov 2026):
 *  • Di hub "Cuti & Lembur" modul ini dipakai dua kali (`bagian="pengajuan"` dan `bagian="jenis"`) — dulu tab
 *    Radix di dalam tab hub. Dibuka sendiri (menu lama `hr-leave`) → bagian pengajuan + tautan "Jenis cuti".
 *  • Daftar kartu berulang → tabel (kartu ringkas di HP) + unduh Excel/CSV; rincian = popup.
 *  • Form = FormPopup; tanggal = DatePicker; tolak/nonaktifkan = konfirmasi merah; label bahasa Indonesia
 *    tanpa emoji. Panggilan API, validasi, dan data yang dikirim tidak berubah.
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Plus, CheckCircle2, XCircle, RefreshCw, CheckCheck, FileText, Upload, Paperclip, X, Pencil, CalendarDays,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { toast } from 'sonner';
import { withFileAuth } from '@/lib/fileUrl';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import DatePicker, { formatTanggalID } from '@/components/ui/date-picker';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';
import { EmployeeSelect } from './hr/hrPickers';

const API = process.env.REACT_APP_BACKEND_URL;

// ─── Helpers ─────────────────────────────────────────────────────────────────
const fmt = (d) => (d ? formatTanggalID(String(d).slice(0, 10)) || '—' : '—');
const fmtDuration = (d, wd) => {
  if (!d) return '—';
  const wdStr = wd && wd !== d ? ` (${wd} hari kerja)` : '';
  return `${d} hari${wdStr}`;
};

// ─── Status & jenis ───────────────────────────────────────────────────────────
const STATUS_CFG = {
  pending_approval:    { label: 'Menunggu atasan', tone: 'warning' },
  pending_hr_approval: { label: 'Menunggu HR', tone: 'info' },
  approved:            { label: 'Disetujui', tone: 'success' },
  rejected:            { label: 'Ditolak', tone: 'danger' },
  cancelled:           { label: 'Dibatalkan', tone: 'muted' },
  draft:               { label: 'Draf', tone: 'muted' },
};
function LeaveBadge({ status }) {
  const cfg = STATUS_CFG[status] || STATUS_CFG.draft;
  return <StatusBadge status={status} label={cfg.label} tone={cfg.tone} />;
}

const REQ_TYPE_CFG = {
  cuti:  { label: 'Cuti',  tone: 'info' },
  sakit: { label: 'Sakit', tone: 'danger' },
  izin:  { label: 'Izin',  tone: 'warning' },
};
function RequestTypeBadge({ type }) {
  const cfg = REQ_TYPE_CFG[type] || REQ_TYPE_CFG.izin;
  return <StatusBadge status={type} label={cfg.label} tone={cfg.tone} />;
}
const PERIODE_SETENGAH = { AM: 'Pagi', PM: 'Siang' };

// ─── Unggah dokumen pendukung ─────────────────────────────────────────────────
function DocumentUpload({ value, onChange, required, docNote, token }) {
  const fileRef = useRef();
  const [uploading, setUploading] = useState(false);

  const handleFile = async (file) => {
    if (!file) return;
    setUploading(true);
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await fetch(`${API}/api/rahaza/leaves/upload-document`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Unggah gagal');
      onChange({ url: data.url, filename: file.name });
      toast.success('Dokumen terunggah');
    } catch (e) { toast.error(e.message); }
    finally { setUploading(false); }
  };

  return (
    <Isian label="Bukti / dokumen pendukung" wajib={Boolean(required)} petunjuk={docNote || 'Foto atau PDF, maksimal 8 MB.'}>
      {value?.url ? (
        <div className="flex items-center gap-2 rounded-md border border-[var(--glass-border)] px-3 py-2">
          <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1 truncate text-sm" title={value.filename}>{value.filename}</span>
          <a href={withFileAuth(`${API}${value.url}`)} target="_blank" rel="noreferrer" className="shrink-0 text-sm text-primary underline-offset-4 hover:underline">Lihat</a>
          <Button type="button" variant="ghost" size="icon-sm" onClick={() => onChange(null)} aria-label="Hapus lampiran" title="Hapus lampiran">
            <X />
          </Button>
        </div>
      ) : (
        <Button type="button" variant="outline" onClick={() => fileRef.current?.click()} disabled={uploading} data-testid="doc-upload-area">
          {uploading ? <RefreshCw className="animate-spin" /> : <Upload />}
          {uploading ? 'Mengunggah…' : 'Unggah foto/PDF'}
        </Button>
      )}
      <input
        ref={fileRef}
        type="file"
        className="hidden"
        accept="image/*,application/pdf"
        onChange={e => handleFile(e.target.files?.[0])}
      />
    </Isian>
  );
}

// ─── MAIN MODULE ──────────────────────────────────────────────────────────────
export default function RahazaLeaveModule({ token, onNavigate, bagian }) {
  const [leaves, setLeaves] = useState([]);
  const [totalServer, setTotalServer] = useState(0);   // jumlah pengajuan di server (daftar memuat 100 terbaru)
  const [dimuat, setDimuat] = useState(0);
  const [leaveTypes, setLeaveTypes] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [filterStatus, setFilterStatus] = useState('');
  const [filterReqType, setFilterReqType] = useState('');
  // Dalam hub bagian ditetapkan tab; dibuka sendiri → bisa pindah lewat tautan.
  const [bagianSendiri, setBagianSendiri] = useState('pengajuan');
  const activeTab = (bagian || bagianSendiri) === 'jenis' ? 'types' : 'requests';
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [bulkApproving, setBulkApproving] = useState(false);

  // Popup
  const [requestModal, setRequestModal] = useState(false);
  const [typeModal, setTypeModal] = useState(false);
  const [selectedLeave, setSelectedLeave] = useState(null);
  const [cancelModal, setCancelModal] = useState(null);
  const [cancelReason, setCancelReason] = useState('');
  // Tahap 2 (2026-11-06): dialog persetujuan — alasan, lampiran, hari kerja, saldo, dan keputusan dibayar/tidak.
  const [approveModal, setApproveModal] = useState(null);
  const [payDecision, setPayDecision] = useState('paid');
  const [approveNote, setApproveNote] = useState('');

  // Request form + working days preview
  const EMPTY_FORM = { employee_id: '', leave_type_id: '', from_date: '', to_date: '',
                       reason: '', is_half_day: false, half_day_period: 'AM', attachment: null };
  const [requestForm, setRequestForm] = useState(EMPTY_FORM);
  const [wdPreview, setWdPreview] = useState(null);
  const [wdLoading, setWdLoading] = useState(false);
  const [typeForm, setTypeForm] = useState({ code: '', name: '', paid: true, quota_default: 12, description: '',
    request_type: 'cuti', requires_document: false, max_days_without_doc: 0, doc_note: '' });

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  // Selected leave type info (for validation hints)
  const selectedLT = leaveTypes.find(lt => lt.id === requestForm.leave_type_id);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filterStatus) params.append('status', filterStatus);
      const [lr, lts, emps] = await Promise.all([
        fetch(`${API}/api/rahaza/leaves?${params}&limit=100`, { headers }).then(r => r.json()),
        fetch(`${API}/api/rahaza/leave-types`, { headers }).then(r => r.json()),
        // Tahap 5 (2026-11-07): hanya karyawan AKTIF (dulu 200 baris pertama termasuk yang sudah keluar)
        fetch(`${API}/api/rahaza/employees?active_only=true&limit=500`, { headers }).then(r => r.json()),
      ]);
      let allLeaves = lr?.items || (Array.isArray(lr) ? lr : []);
      setTotalServer(Number(lr?.total) || allLeaves.length);
      setDimuat(allLeaves.length);
      if (filterReqType) allLeaves = allLeaves.filter(l => l.request_type === filterReqType);
      setLeaves(allLeaves);
      setLeaveTypes(Array.isArray(lts) ? lts : []);
      setEmployees((emps?.items || emps?.employees || emps?.data || (Array.isArray(emps) ? emps : [])));
    } catch (e) { toast.error('Gagal memuat data'); }
    finally { setLoading(false); }
  }, [filterStatus, filterReqType, token]); // eslint-disable-line

  useEffect(() => { load(); }, [load]);

  const pendingCount = leaves.filter(l => l.status === 'pending_approval' || l.status === 'pending_hr_approval').length;

  // ── Live working days preview ────────────────────────────────────────────────
  useEffect(() => {
    const { from_date, to_date, is_half_day } = requestForm;
    if (!from_date || !to_date || is_half_day) { setWdPreview(null); return; }
    if (new Date(to_date) < new Date(from_date)) { setWdPreview(null); return; }
    setWdLoading(true);
    fetch(`${API}/api/rahaza/leaves/working-days?from_date=${from_date}&to_date=${to_date}`, { headers })
      .then(r => r.ok ? r.json() : null)
      .then(d => setWdPreview(d))
      .catch(() => setWdPreview(null))
      .finally(() => setWdLoading(false));
  }, [requestForm.from_date, requestForm.to_date, requestForm.is_half_day]); // eslint-disable-line

  // ── Submit request ──────────────────────────────────────────────────────────
  const submitRequest = async () => {
    const { employee_id, leave_type_id, from_date, to_date, reason,
            is_half_day, half_day_period, attachment } = requestForm;

    if (!employee_id || !leave_type_id || !from_date || !to_date)
      return toast.error('Lengkapi karyawan, jenis, dan tanggal');
    if (to_date < from_date) return toast.error('Tanggal selesai tidak boleh sebelum tanggal mulai');
    if (!reason?.trim()) return toast.error('Alasan wajib diisi');   // Tahap 2: alasan wajib

    // Validate document if required
    if (selectedLT?.requires_document) {
      const maxNoDoc = parseInt(selectedLT.max_days_without_doc || 0);
      const dur = is_half_day ? 0.5 : (new Date(to_date) - new Date(from_date)) / 86400000 + 1;
      if ((!attachment?.url) && (maxNoDoc === 0 || dur > maxNoDoc))
        return toast.error(`Dokumen wajib dilampirkan. ${selectedLT.doc_note || ''}`);
    }

    setSaving(true);
    try {
      const payload = {
        employee_id, leave_type_id, from_date, to_date, reason,
        is_half_day, half_day_period,
        attachment_url: attachment?.url || '',
        attachment_filename: attachment?.filename || '',
        request_type: selectedLT?.request_type || 'cuti',
      };
      const r = await fetch(`${API}/api/rahaza/leaves/request`, {
        method: 'POST', headers, body: JSON.stringify(payload) });
      if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || `HTTP ${r.status}`); }
      toast.success('Pengajuan terkirim');
      setRequestModal(false);
      setRequestForm(EMPTY_FORM);
      load();
    } catch (e) { toast.error(e.message); }
    finally { setSaving(false); }
  };

  // ── Approve ─────────────────────────────────────────────────────────────────
  const approveLeave = async (id) => {
    const r = await fetch(`${API}/api/rahaza/leaves/${id}/approval-preview`, { headers });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { toast.error(d.detail || 'Gagal memuat pengajuan'); return; }
    setApproveModal(d);
    setPayDecision(d.suggestion?.decision || 'paid');
    setApproveNote('');
  };

  const confirmApprove = async () => {
    if (!approveModal) return;
    setSaving(true);
    try {
      const body = approveModal.final_step ? { pay_decision: payDecision, notes: approveNote } : { notes: approveNote };
      const r = await fetch(`${API}/api/rahaza/leaves/${approveModal.leave.id}/approve`, {
        method: 'POST', headers, body: JSON.stringify(body) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || 'Gagal menyetujui');
      toast.success(d.status === 'pending_hr_approval' ? 'Disetujui atasan — diteruskan ke HR' : 'Pengajuan disetujui');
      setApproveModal(null);
      setSelectedLeave(null);
      load();
    } catch (e) { toast.error(e.message); }
    finally { setSaving(false); }
  };

  // ── Reject (konfirmasi merah; alasan bawaan sama dengan dulu: "Tidak disetujui") ──
  const rejectLeave = async (lv) => {
    const reason = await confirmDialog({
      title: 'Tolak pengajuan ini?',
      body: `Pengajuan ${lv.employee_name || ''} (${lv.leave_type_name || ''}) ditolak dan karyawan diberi tahu.`,
      confirmLabel: 'Tolak', danger: true,
      input: { label: 'Alasan penolakan', value: 'Tidak disetujui' },
    });
    if (!reason) return;
    const r = await fetch(`${API}/api/rahaza/leaves/${lv.id}/reject`, {
      method: 'POST', headers, body: JSON.stringify({ reason: reason || 'Tidak disetujui' }) });
    if (r.ok) { toast.success('Pengajuan ditolak'); setSelectedLeave(null); load(); }
    else toast.error('Gagal menolak');
  };

  // ── Cancel ──────────────────────────────────────────────────────────────────
  const cancelLeave = async () => {
    if (!cancelModal) return;
    setSaving(true);
    try {
      const r = await fetch(`${API}/api/rahaza/leaves/${cancelModal.id}/cancel`, {
        method: 'POST', headers, body: JSON.stringify({ reason: cancelReason }) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Gagal membatalkan');
      toast.success('Cuti dibatalkan, saldo dikembalikan');
      setCancelModal(null); setCancelReason(''); setSelectedLeave(null); load();
    } catch (e) { toast.error(e.message); }
    finally { setSaving(false); }
  };
  const bukaBatal = (lv) => { setCancelModal(lv); setCancelReason(''); };

  // ── Bulk approve ────────────────────────────────────────────────────────────
  const bulkApprove = async () => {
    setBulkApproving(true);
    try {
      const r = await fetch(`${API}/api/rahaza/leaves/bulk-approve`, {
        method: 'POST', headers, body: JSON.stringify({}) });
      const d = await r.json().catch(() => ({}));
      // 2026-11-06 (pola P6): dulu penolakan server (bukan approver, dsb.) tampil sebagai sukses
      if (!r.ok) { toast.error(typeof d.detail === 'string' ? d.detail : 'Gagal menyetujui sekaligus'); return; }
      toast.success(d.message || `${d.approved} pengajuan disetujui`);
      load();
    } catch { toast.error('Gagal menyetujui sekaligus'); }
    finally { setBulkApproving(false); }
  };

  // ── Save Leave Type ─────────────────────────────────────────────────────────
  const saveLeaveType = async () => {
    if (!typeForm.code || !typeForm.name) return toast.error('Kode & nama wajib diisi');
    setSaving(true);
    try {
      // BUG-4: backend dulu MEMBUANG request_type/requires_document/... yang
      // dikirim form ini. Sekarang seluruh field tersimpan; edit juga tersedia.
      const editing = Boolean(typeForm.id);
      const r = await fetch(`${API}/api/rahaza/leave-types${editing ? `/${typeForm.id}` : ''}`, {
        method: editing ? 'PUT' : 'POST', headers,
        body: JSON.stringify({
          ...typeForm,
          quota_default: parseInt(typeForm.quota_default, 10) || 0,
          max_days_without_doc: parseInt(typeForm.max_days_without_doc, 10) || 0,
        }) });
      if (!r.ok) { const e = await r.json(); throw new Error(e.detail || 'Gagal menyimpan'); }
      toast.success(editing ? 'Jenis cuti disimpan' : 'Jenis cuti ditambahkan');
      setTypeModal(false);
      load();
    } catch (e) { toast.error(e.message); }
    finally { setSaving(false); }
  };

  const deactivateLeaveType = async (lt) => {
    const ok = await confirmDialog({
      title: 'Nonaktifkan jenis cuti?',
      body: `"${lt.name}" tidak muncul lagi di formulir pengajuan. Riwayat pengajuan tetap tersimpan. Pengajuan yang masih menunggu keputusan harus diproses dulu.`,
      confirmLabel: 'Nonaktifkan', danger: true,
    });
    if (!ok) return;
    setSaving(true);
    try {
      const r = await fetch(`${API}/api/rahaza/leave-types/${lt.id}`, { method: 'DELETE', headers });
      if (!r.ok) { const e = await r.json(); throw new Error(e.detail || 'Gagal menonaktifkan'); }
      toast.success(`Jenis cuti "${lt.name}" dinonaktifkan`);
      load();
    } catch (e) { toast.error(e.message); }
    finally { setSaving(false); }
  };

  const tambahJenis = () => {
    setTypeForm({ code: '', name: '', paid: true, quota_default: 12, description: '',
      request_type: 'cuti', requires_document: false, max_days_without_doc: 0, doc_note: '' });
    setTypeModal(true);
  };

  const { page, setPage, totalPages, total, paged } = useClientPagination(leaves, 10);

  // Unduh: SEMUA pengajuan sesuai penyaring (bukan hanya 100 terbaru yang tampil) — API yang sama, per 500 baris.
  const ambilSemuaPengajuan = async () => {
    const semua = [];
    for (let skip = 0; skip < 20000; skip += 500) {
      const params = new URLSearchParams({ skip: String(skip), limit: '500' });
      if (filterStatus) params.append('status', filterStatus);
      const r = await fetch(`${API}/api/rahaza/leaves?${params}`, { headers });
      if (!r.ok) throw new Error('Gagal memuat pengajuan');
      const d = await r.json();
      const items = d?.items || [];
      semua.push(...items);
      if (!d?.has_more || items.length === 0) break;
    }
    return filterReqType ? semua.filter(l => l.request_type === filterReqType) : semua;
  };

  // ── Aksi per pengajuan (dipakai di tabel & popup rincian) ──
  const aksiPengajuan = (lv) => {
    if (lv.status === 'pending_approval' || lv.status === 'pending_hr_approval') {
      const hr = lv.status === 'pending_hr_approval';
      return (<>
        <Button size="sm" variant="success" onClick={() => approveLeave(lv.id)}
          data-testid={hr ? `approve-hr-${lv.id}` : `approve-${lv.id}`}>
          <CheckCircle2 />{hr ? 'Setujui (HR)' : 'Setujui (atasan)'}
        </Button>
        <Button size="sm" variant="destructive" onClick={() => rejectLeave(lv)}
          data-testid={hr ? `reject-hr-${lv.id}` : `reject-${lv.id}`}>
          <XCircle />Tolak
        </Button>
      </>);
    }
    // Tahap 2: HR juga boleh membatalkan cuti yang sudah dimulai (absensi dikembalikan)
    if (lv.status === 'approved') {
      return (
        <Button size="sm" variant="outline" onClick={() => bukaBatal(lv)} data-testid={`cancel-${lv.id}`}>
          <X />Batalkan
        </Button>
      );
    }
    return null;
  };

  const kolomPengajuan = [
    { kunci: 'karyawan', label: 'Karyawan', hp: 'judul', isi: (lv) => (
      <div className="min-w-0">
        <p className="font-medium text-foreground">{lv.employee_name || lv.employee_id}</p>
        <p className="text-xs text-muted-foreground">{lv.leave_type_name || '—'}</p>
      </div>) },
    { kunci: 'jenis', label: 'Jenis', isi: (lv) => (
      <div className="flex flex-wrap items-center gap-1">
        <RequestTypeBadge type={lv.request_type || 'cuti'} />
        {lv.is_half_day && <StatusBadge status="half" label={`½ hari ${PERIODE_SETENGAH[lv.half_day_period] || ''}`.trim()} tone="muted" />}
        {lv.attachment_url && <StatusBadge status="doc" label="Ada dokumen" tone="muted" />}
        {/* Multi-level indicator */}
        {lv.approval_level_required === 2 && <StatusBadge status="level2" label="2 tingkat" tone="primary" />}
      </div>) },
    { kunci: 'periode', label: 'Periode', isi: (lv) => <span className="whitespace-nowrap">{fmt(lv.from_date)} – {fmt(lv.to_date)}</span> },
    { kunci: 'durasi', label: 'Durasi', isi: (lv) => <span className="whitespace-nowrap">{fmtDuration(lv.duration_days, lv.duration_working_days)}</span> },
    { kunci: 'status', label: 'Status', isi: (lv) => <LeaveBadge status={lv.status} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (lv) => <div className="flex justify-end gap-2">{aksiPengajuan(lv)}</div> },
  ];

  const kolomJenis = [
    { kunci: 'nama', label: 'Jenis cuti', hp: 'judul', isi: (lt) => (
      <div className={lt.active === false ? 'min-w-0 opacity-60' : 'min-w-0'}>
        <p className="font-medium text-foreground">{lt.name}</p>
        <p className="text-xs text-muted-foreground">{lt.code}{lt.legal_basis ? ` · ${lt.legal_basis}` : ''}</p>
      </div>) },
    { kunci: 'kelompok', label: 'Kelompok', isi: (lt) => <RequestTypeBadge type={lt.request_type || 'cuti'} /> },
    { kunci: 'kuota', label: 'Kuota / tahun', rata: 'kanan', isi: (lt) => <span className="tabular-nums">{lt.quota_default} hari</span> },
    /* BUG-4: dulu hanya membaca `unpaid`; jenis buatan HR (yang menulis `paid`) tidak pernah menampilkan status apa pun. */
    { kunci: 'dibayar', label: 'Gaji', isi: (lt) => (lt.unpaid
      ? <span data-testid={`lt-unpaid-${lt.code}`}><StatusBadge status="unpaid" label="Tanpa gaji" tone="muted" /></span>
      : <span data-testid={`lt-paid-${lt.code}`}><StatusBadge status="paid" label="Dibayar" tone="success" /></span>) },
    { kunci: 'dokumen', label: 'Dokumen', isi: (lt) => (lt.requires_document
      ? <span className="text-sm">Wajib{lt.doc_note ? <span className="block text-xs text-muted-foreground">{lt.doc_note}</span> : null}</span>
      : <span className="text-muted-foreground">—</span>) },
    { kunci: 'status', label: 'Status', isi: (lt) => (lt.active === false
      ? <StatusBadge status="nonaktif" label="Nonaktif" tone="muted" />
      : <StatusBadge status="aktif" label="Aktif" tone="success" />) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (lt) => (
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="outline" data-testid={`leave-type-edit-${lt.code}`}
          onClick={() => { setTypeForm({ ...lt, paid: !lt.unpaid }); setTypeModal(true); }}>
          <Pencil />Ubah
        </Button>
        {lt.active !== false && (
          <Button size="sm" variant="outline" data-testid={`leave-type-off-${lt.code}`} disabled={saving}
            onClick={() => deactivateLeaveType(lt)}>
            <XCircle />Nonaktifkan
          </Button>
        )}
      </div>) },
  ];

  const muatUlang = (
    <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
      <RefreshCw className={loading ? 'animate-spin' : ''} />
    </Button>
  );
  const pindahBagian = !bagian && (
    <Button variant="link" className="px-1" onClick={() => setBagianSendiri(activeTab === 'types' ? 'pengajuan' : 'jenis')}
      data-testid={activeTab === 'types' ? 'tab-requests' : 'tab-types'}>
      {activeTab === 'types' ? 'Kembali ke pengajuan' : 'Jenis cuti'}
    </Button>
  );

  const halamanPengajuan = (
    <PageLayout testId="leave-module" title="Pengajuan cuti"
      subtitle="Pengajuan cuti, izin, dan sakit karyawan beserta persetujuannya."
      actions={<>
        {pendingCount > 0 && (
          <Button variant="outline" onClick={bulkApprove} disabled={bulkApproving} data-testid="bulk-approve-btn"
            title="Menyetujui SEMUA pengajuan yang menunggu (tidak terbatas pada penyaring)">
            <CheckCheck />{bulkApproving ? 'Menyetujui…' : 'Setujui semua yang menunggu'}
          </Button>
        )}
        <Button onClick={() => setRequestModal(true)} data-testid="new-request-btn">
          <Plus />Buat pengajuan
        </Button>
      </>}
      filters={<>
        <SmartNativeSelect value={filterStatus} onChange={e => setFilterStatus(e.target.value)} searchable={false}
          className="h-9 w-48" aria-label="Status" data-testid="filter-status">
          <option value="">Semua status</option>
          <option value="pending_approval">Menunggu atasan</option>
          <option value="pending_hr_approval">Menunggu HR</option>
          <option value="approved">Disetujui</option>
          <option value="rejected">Ditolak</option>
          <option value="cancelled">Dibatalkan</option>
        </SmartNativeSelect>
        <SmartNativeSelect value={filterReqType} onChange={e => setFilterReqType(e.target.value)} searchable={false}
          className="h-9 w-44" aria-label="Kelompok" data-testid="filter-reqtype">
          <option value="">Semua kelompok</option>
          <option value="cuti">Cuti</option>
          <option value="sakit">Sakit</option>
          <option value="izin">Izin</option>
        </SmartNativeSelect>
        {pindahBagian}
        {/* Unduh & muat ulang di ujung kanan; di HP turun ke baris sendiri (tidak menimpa penyaring) */}
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <TombolUnduh namaBerkas="pengajuan-cuti" namaLembar="Pengajuan cuti" baris={leaves} testId="leave-unduh"
            ambilSemua={ambilSemuaPengajuan}
            kolom={[
              { label: 'Karyawan', nilai: (lv) => lv.employee_name || lv.employee_id },
              { label: 'Kelompok', nilai: (lv) => (REQ_TYPE_CFG[lv.request_type || 'cuti'] || REQ_TYPE_CFG.izin).label },
              { label: 'Jenis cuti', nilai: (lv) => lv.leave_type_name || '' },
              { label: 'Dari', nilai: (lv) => fmt(lv.from_date) },
              { label: 'Sampai', nilai: (lv) => fmt(lv.to_date) },
              { label: 'Hari kalender', nilai: (lv) => Number(lv.duration_days) || 0 },
              { label: 'Hari kerja', nilai: (lv) => Number(lv.duration_working_days) || 0 },
              { label: 'Setengah hari', nilai: (lv) => (lv.is_half_day ? PERIODE_SETENGAH[lv.half_day_period] || 'Ya' : '') },
              { label: 'Alasan', nilai: (lv) => lv.reason || '' },
              { label: 'Status', nilai: (lv) => (STATUS_CFG[lv.status] || STATUS_CFG.draft).label },
              { label: 'Dokumen', nilai: (lv) => (lv.attachment_url ? 'Ada' : '') },
            ]} />
          {muatUlang}
        </div>
      </>}
      summary={(typeof onNavigate === 'function' || totalServer > dimuat) && (
        <p className="text-sm text-muted-foreground">
          {totalServer > dimuat && `Menampilkan ${dimuat} pengajuan terbaru dari ${totalServer}; unduhan berisi semuanya. `}
          {typeof onNavigate === 'function' && <>Saldo cuti berkurang otomatis setelah pengajuan disetujui.{' '}
          <Button variant="link" className="h-auto p-0" onClick={() => onNavigate('hr-leave-balances', {})}
            data-testid="onward-hr-leave-balances" title="Cek saldo cuti karyawan setelah pengajuan disetujui">
            Lihat saldo cuti
          </Button></>}
        </p>
      )}
      footer={leaves.length > 0 && <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />}>
      {loading && leaves.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat pengajuan…</p>
      ) : (
        <TabelData kolom={kolomPengajuan} baris={paged} onKlikBaris={setSelectedLeave} testId="leave-table"
          kosong={<EmptyState icon={CalendarDays} title="Belum ada pengajuan"
            description={filterStatus || filterReqType ? 'Ubah penyaring status atau kelompok.' : 'Pengajuan cuti, izin, dan sakit karyawan akan tampil di sini.'} />} />
      )}
    </PageLayout>
  );

  const halamanJenis = (
    <PageLayout testId="leave-type-page" title="Jenis cuti"
      subtitle="Kuota, dibayar atau tidak, dan kewajiban dokumen tiap jenis cuti, izin, dan sakit."
      actions={<Button onClick={tambahJenis} data-testid="leave-type-add"><Plus />Tambah jenis</Button>}
      tools={<>
        {pindahBagian}
        <TombolUnduh namaBerkas="jenis-cuti" namaLembar="Jenis cuti" baris={leaveTypes} testId="leave-type-unduh"
          kolom={[
            { label: 'Kode', nilai: (lt) => lt.code },
            { label: 'Nama', nilai: (lt) => lt.name },
            { label: 'Kelompok', nilai: (lt) => (REQ_TYPE_CFG[lt.request_type || 'cuti'] || REQ_TYPE_CFG.izin).label },
            { label: 'Kuota per tahun (hari)', nilai: (lt) => Number(lt.quota_default) || 0 },
            { label: 'Gaji', nilai: (lt) => (lt.unpaid ? 'Tanpa gaji' : 'Dibayar') },
            { label: 'Wajib dokumen', nilai: (lt) => (lt.requires_document ? 'Ya' : 'Tidak') },
            { label: 'Maks. hari tanpa dokumen', nilai: (lt) => Number(lt.max_days_without_doc) || 0 },
            { label: 'Catatan dokumen', nilai: (lt) => lt.doc_note || '' },
            { label: 'Dasar hukum', nilai: (lt) => lt.legal_basis || '' },
            { label: 'Status', nilai: (lt) => (lt.active === false ? 'Nonaktif' : 'Aktif') },
          ]} />
        {muatUlang}
      </>}
      summary={<p className="text-sm text-muted-foreground">Perubahan langsung dipakai formulir pengajuan dan penggajian.</p>}>
      {loading && leaveTypes.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat jenis cuti…</p>
      ) : (
        <TabelData kolom={kolomJenis} baris={leaveTypes} testId="leave-type-list"
          kosong={<EmptyState icon={CalendarDays} title="Belum ada jenis cuti"
            description="Tekan Tambah jenis untuk membuat jenis cuti, izin, atau sakit beserta kuota tahunannya." />} />
      )}
    </PageLayout>
  );

  const rf = requestForm;
  const setRf = (patch) => setRequestForm((f) => ({ ...f, ...patch }));

  return (
    <>
      {activeTab === 'types' ? halamanJenis : halamanPengajuan}

      {/* ── POPUP: PENGAJUAN BARU ── */}
      <FormPopup open={requestModal} onClose={() => setRequestModal(false)} ukuran="panjang" testId="new-request-dialog"
        judul="Buat pengajuan cuti, izin, atau sakit" onSimpan={submitRequest} menyimpan={saving} labelSimpan="Kirim pengajuan">
        <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Karyawan" wajib>
          <EmployeeSelect employees={employees} value={rf.employee_id}
            onChange={v => setRf({ employee_id: v })} testId="req-employee" />
        </Isian>
        <Isian label="Jenis" wajib petunjuk={selectedLT?.legal_basis || undefined}>
          {/* Tahap 5: hanya jenis AKTIF (jenis yang dinonaktifkan dulu tetap bisa dipilih lalu ditolak server) */}
          <SmartNativeSelect value={rf.leave_type_id} aria-label="Jenis"
            onChange={e => setRf({ leave_type_id: e.target.value })} data-testid="req-type">
            <option value="">— Pilih jenis cuti, izin, atau sakit —</option>
            {['cuti', 'sakit', 'izin'].map(rt => (
              <optgroup key={rt} label={REQ_TYPE_CFG[rt].label}>
                {leaveTypes.filter(lt => lt.active !== false && (lt.request_type || 'cuti') === rt).map(lt => (
                  <option key={lt.id} value={lt.id}>{`${REQ_TYPE_CFG[rt].label} · ${lt.name}${lt.quota_default ? ` (${lt.quota_default} hari)` : ''}`}</option>
                ))}
              </optgroup>
            ))}
          </SmartNativeSelect>
        </Isian>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Dari tanggal" wajib>
            <DatePicker value={rf.from_date} testId="req-from" bolehKosong={false}
              onChange={v => setRequestForm(f => ({ ...f, from_date: v, to_date: f.is_half_day || !f.to_date ? v : f.to_date }))} />
          </Isian>
          <Isian label="Sampai tanggal" wajib>
            <DatePicker value={rf.to_date} min={rf.from_date || undefined} disabled={rf.is_half_day} bolehKosong={false}
              onChange={v => setRf({ to_date: v })} testId="req-to" />
          </Isian>
        </div>

        {/* Hari kerja dalam rentang (libur & akhir pekan tidak dihitung) */}
        {(wdPreview || wdLoading) && !rf.is_half_day && (
          <div data-testid="wd-preview">
            {wdLoading ? (
              <p className="flex items-center gap-2 text-sm text-muted-foreground"><RefreshCw className="h-4 w-4 animate-spin" />Menghitung hari kerja…</p>
            ) : wdPreview ? (
              <Notice tone={wdPreview.holiday_days > 0 ? 'warning' : 'success'}
                title={wdPreview.working_days === wdPreview.calendar_days
                  ? `${wdPreview.working_days} hari kerja`
                  : `${wdPreview.working_days} hari kerja dari ${wdPreview.calendar_days} hari kalender`}>
                {(wdPreview.weekend_days > 0 || wdPreview.holiday_days > 0) && (
                  <>
                    {wdPreview.weekend_days > 0 && <span className="block">{wdPreview.weekend_days} hari akhir pekan tidak dihitung.</span>}
                    {wdPreview.holiday_days > 0 && (
                      <span className="block">{wdPreview.holiday_days} libur nasional dalam periode ini: {wdPreview.holidays.map(h => h.name).join(', ')}</span>
                    )}
                  </>
                )}
              </Notice>
            ) : null}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm" htmlFor="req-half-day">
            <Switch id="req-half-day" checked={rf.is_half_day} data-testid="req-half-day"
              onCheckedChange={v => setRequestForm(f => ({ ...f, is_half_day: v, to_date: v ? f.from_date : f.to_date }))} />
            Setengah hari
          </label>
          {rf.is_half_day && (
            <SmartNativeSelect value={rf.half_day_period} searchable={false} className="h-9 w-32" aria-label="Bagian hari"
              onChange={e => setRf({ half_day_period: e.target.value })}>
              <option value="AM">Pagi</option>
              <option value="PM">Siang</option>
            </SmartNativeSelect>
          )}
        </div>

        <Isian label="Alasan" wajib htmlFor="req-reason">
          <Textarea id="req-reason" rows={2} placeholder="Tulis alasan…" value={rf.reason}
            onChange={e => setRf({ reason: e.target.value })} data-testid="req-reason" />
        </Isian>

        <DocumentUpload
          value={rf.attachment}
          onChange={att => setRf({ attachment: att })}
          required={selectedLT?.requires_document}
          docNote={selectedLT?.doc_note}
          token={token}
        />
      </FormPopup>

      {/* ── POPUP: RINCIAN ── */}
      {selectedLeave && (
        <DetailPopup open onClose={() => setSelectedLeave(null)} testId="detail-dialog"
          judul={selectedLeave.employee_name || 'Rincian pengajuan'}
          keterangan={selectedLeave.leave_type_name}
          status={<><LeaveBadge status={selectedLeave.status} /><RequestTypeBadge type={selectedLeave.request_type} /></>}
          aksi={aksiPengajuan(selectedLeave)}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Jenis cuti">{selectedLeave.leave_type_name || '—'}</BarisDetail>
            <BarisDetail label="Periode">{fmt(selectedLeave.from_date)} – {fmt(selectedLeave.to_date)}</BarisDetail>
            <BarisDetail label="Durasi">{fmtDuration(selectedLeave.duration_days, selectedLeave.duration_working_days)}</BarisDetail>
            {selectedLeave.is_half_day && <BarisDetail label="Setengah hari">{PERIODE_SETENGAH[selectedLeave.half_day_period] || selectedLeave.half_day_period}</BarisDetail>}
            {selectedLeave.approval_level_required === 2 && <BarisDetail label="Persetujuan">2 tingkat (atasan lalu HR)</BarisDetail>}
            <BarisDetail label="Alasan">{selectedLeave.reason || '—'}</BarisDetail>
            {selectedLeave.rejected_reason && <BarisDetail label="Alasan ditolak"><span className="text-[hsl(var(--danger-text))]">{selectedLeave.rejected_reason}</span></BarisDetail>}
            {selectedLeave.cancel_reason && <BarisDetail label="Alasan dibatalkan">{selectedLeave.cancel_reason}</BarisDetail>}
            {selectedLeave.attachment_url && (
              <BarisDetail label="Dokumen">
                <a href={withFileAuth(`${API}${selectedLeave.attachment_url}`)} target="_blank" rel="noreferrer"
                  className="inline-flex items-center gap-1 text-primary underline-offset-4 hover:underline">
                  <Paperclip className="h-4 w-4" /> {selectedLeave.attachment_filename || 'Lihat dokumen'}
                </a>
              </BarisDetail>
            )}
          </dl>
        </DetailPopup>
      )}

      {/* ── POPUP: SETUJUI (Tahap 2) ── */}
      <FormPopup open={!!approveModal} onClose={() => setApproveModal(null)} ukuran="pendek" testId="approve-dialog"
        judul="Setujui pengajuan" onSimpan={confirmApprove} menyimpan={saving} labelSimpan="Setujui">
        {approveModal && (
          <>
            <div className="text-sm">
              <p><span className="font-medium">{approveModal.employee?.name}</span> · {approveModal.leave_type_name} ({approveModal.leave_kind})</p>
              <p className="text-muted-foreground">
                {fmt(approveModal.leave?.from_date)} – {fmt(approveModal.leave?.to_date)} · {approveModal.working_days} hari kerja
                {approveModal.half_day ? ' (setengah hari)' : ''}
              </p>
            </div>
            <dl className="divide-y divide-[var(--glass-border)]">
              <BarisDetail label="Alasan"><span data-testid="approve-reason">{approveModal.reason || '—'}</span></BarisDetail>
              <BarisDetail label="Lampiran">
                {approveModal.attachment_url ? (
                  <a href={withFileAuth(`${API}${approveModal.attachment_url}`)} target="_blank" rel="noreferrer"
                    className="inline-flex items-center gap-1 text-primary underline-offset-4 hover:underline" data-testid="approve-attachment">
                    <Paperclip className="h-4 w-4" />{approveModal.attachment_filename || 'Buka lampiran'}
                  </a>
                ) : <span className="text-muted-foreground">Tidak ada lampiran</span>}
              </BarisDetail>
              <BarisDetail label="Saldo">
                {(approveModal.balance_by_year || []).length > 1 ? (
                  <span data-testid="approve-balance-by-year">
                    {/* Tahap 7: cuti lintas tahun memakai saldo masing-masing tahun */}
                    {approveModal.balance_by_year.map((b) => (
                      `${b.year} dipakai ${b.days} hari (sisa ${b.remaining} dari ${b.allocated})`)).join(' · ')}
                  </span>
                ) : (
                  <span>Sisa {approveModal.balance?.remaining} dari {approveModal.balance?.allocated} hari</span>
                )}
              </BarisDetail>
            </dl>
            {approveModal.final_step ? (
              <Isian label="Keputusan pembayaran" petunjuk={`Usulan sistem: ${approveModal.suggestion?.reason || '—'}`}>
                <div className="flex flex-wrap gap-2">
                  <Button type="button" size="sm" variant={payDecision === 'paid' ? 'default' : 'outline'} aria-pressed={payDecision === 'paid'}
                    onClick={() => setPayDecision('paid')} data-testid="pay-decision-paid">Dibayar</Button>
                  <Button type="button" size="sm" variant={payDecision === 'unpaid' ? 'default' : 'outline'} aria-pressed={payDecision === 'unpaid'}
                    onClick={() => setPayDecision('unpaid')} data-testid="pay-decision-unpaid">Tidak dibayar</Button>
                </div>
              </Isian>
            ) : (
              <p className="text-sm text-muted-foreground">Persetujuan tingkat 1 — diteruskan ke HR untuk keputusan akhir.</p>
            )}
            <Isian label="Catatan (opsional)" htmlFor="approve-note">
              <Textarea id="approve-note" value={approveNote} rows={2}
                onChange={e => setApproveNote(e.target.value)} data-testid="approve-note" />
            </Isian>
          </>
        )}
      </FormPopup>

      {/* ── POPUP: BATALKAN CUTI (alasan opsional, sama seperti dulu) ── */}
      <FormPopup open={!!cancelModal} onClose={() => setCancelModal(null)} ukuran="pendek" testId="cancel-dialog"
        judul="Batalkan cuti" onSimpan={cancelLeave} menyimpan={saving} labelSimpan="Batalkan cuti" warnaSimpan="destructive"
        keterangan={cancelModal ? `Cuti ${cancelModal.employee_name} (${fmt(cancelModal.from_date)} – ${fmt(cancelModal.to_date)}) dibatalkan dan saldo cuti dikembalikan.` : ''}>
        <Isian label="Alasan pembatalan" htmlFor="cancel-reason">
          <Textarea id="cancel-reason" placeholder="Alasan pembatalan…" value={cancelReason}
            onChange={e => setCancelReason(e.target.value)} rows={2} />
        </Isian>
      </FormPopup>

      {/* ── POPUP: JENIS CUTI ── */}
      <FormPopup open={typeModal} onClose={() => setTypeModal(false)} ukuran="pendek" testId="new-type-dialog"
        judul={typeForm.id ? `Ubah jenis cuti — ${typeForm.name || typeForm.code}` : 'Tambah jenis cuti'}
        onSimpan={saveLeaveType} menyimpan={saving} labelSimpan={typeForm.id ? 'Simpan perubahan' : 'Simpan'}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Kode" wajib htmlFor="lt-code">
            <Input id="lt-code" placeholder="SICK" value={typeForm.code}
              onChange={e => setTypeForm(f => ({ ...f, code: e.target.value.toUpperCase() }))} />
          </Isian>
          <Isian label="Nama" wajib htmlFor="lt-name">
            <Input id="lt-name" placeholder="Izin sakit" value={typeForm.name}
              onChange={e => setTypeForm(f => ({ ...f, name: e.target.value }))} />
          </Isian>
          <Isian label="Kelompok">
            <SmartNativeSelect value={typeForm.request_type} searchable={false} aria-label="Kelompok"
              onChange={e => setTypeForm(f => ({ ...f, request_type: e.target.value }))}>
              <option value="cuti">Cuti</option>
              <option value="sakit">Sakit</option>
              <option value="izin">Izin</option>
            </SmartNativeSelect>
          </Isian>
          <Isian label="Kuota bawaan (hari)" htmlFor="lt-quota">
            <Input id="lt-quota" type="number" min={0} value={typeForm.quota_default}
              onChange={e => setTypeForm(f => ({ ...f, quota_default: e.target.value }))} />
          </Isian>
        </div>
        <div className="flex flex-wrap gap-6">
          <label className="flex items-center gap-2 text-sm" htmlFor="lt-paid">
            <Switch id="lt-paid" checked={typeForm.paid} onCheckedChange={v => setTypeForm(f => ({ ...f, paid: v }))} /> Dibayar
          </label>
          <label className="flex items-center gap-2 text-sm" htmlFor="lt-doc">
            <Switch id="lt-doc" checked={typeForm.requires_document}
              onCheckedChange={v => setTypeForm(f => ({ ...f, requires_document: v }))} /> Wajib dokumen
          </label>
        </div>
        {typeForm.requires_document && (
          <div className="grid gap-4 sm:grid-cols-2">
            <Isian label="Maks. hari tanpa dokumen" htmlFor="lt-maxdoc" petunjuk="0 = selalu wajib.">
              <Input id="lt-maxdoc" type="number" min={0} value={typeForm.max_days_without_doc}
                onChange={e => setTypeForm(f => ({ ...f, max_days_without_doc: e.target.value }))} />
            </Isian>
            <Isian label="Catatan dokumen" htmlFor="lt-docnote">
              <Input id="lt-docnote" placeholder="Contoh: lampirkan surat dokter" value={typeForm.doc_note}
                onChange={e => setTypeForm(f => ({ ...f, doc_note: e.target.value }))} />
            </Isian>
          </div>
        )}
      </FormPopup>
    </>
  );
}

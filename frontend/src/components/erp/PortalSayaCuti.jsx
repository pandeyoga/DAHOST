/**
 * Portal Saya › Cuti & Lembur — pengajuan cuti/izin/sakit dan lembur milik karyawan sendiri.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, saldo cuti = StatTile, daftar pengajuan & lembur = TabelData (kartu
 * ringkas di HP) + unduh Excel/CSV, form pengajuan = FormPopup (dulu form terbuka di halaman), tanggal pakai
 * DatePicker, status pakai StatusBadge bersama, tanpa emoji. Endpoint & validasi tidak berubah.
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Clock, Plus, Trash2, CheckCircle2, XCircle, HelpCircle,
  Loader2, Paperclip, Upload, FileText, X, RefreshCw,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { useToast } from '@/hooks/use-toast';
import axios from 'axios';
import { withFileAuth } from '@/lib/fileUrl';
import { formatDateID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { labelTahap } from '@/lib/tahapPersetujuan';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;
const fmt = (d) => (d ? formatDateID(String(d).slice(0, 10)) : '—');

const STATUS_CFG = {
  pending_approval: { label: 'Menunggu atasan', icon: HelpCircle, tone: 'warning' },
  pending_hr_approval: { label: 'Menunggu HR', icon: Clock, tone: 'info' },
  pending: { label: 'Menunggu persetujuan', icon: HelpCircle, tone: 'warning' },
  approved: { label: 'Disetujui', icon: CheckCircle2, tone: 'success' },
  rejected: { label: 'Ditolak', icon: XCircle, tone: 'danger' },
  cancelled: { label: 'Dibatalkan', icon: X, tone: 'muted' },
};
const labelStatus = (status) => (STATUS_CFG[status] || STATUS_CFG.pending_approval).label;
// 2026-11-09 (Q6): label tahap dari rute persetujuan (atasan langsung → HR; tanpa atasan → langsung HR).
function StatusPengajuan({ status, doc }) {
  const cfg = STATUS_CFG[status] || STATUS_CFG.pending_approval;
  return <StatusBadge status={status} label={(doc && labelTahap(doc)) || cfg.label} tone={cfg.tone} />;
}

const REQ_TYPE_CFG = {
  cuti:  { label: 'Cuti' },
  sakit: { label: 'Sakit' },
  izin:  { label: 'Izin' },
};

// ─── Document Upload ──────────────────────────────────────────────────────────
function DocUpload({ value, onChange, required, docNote, headers }) {
  const fileRef = useRef();
  const [uploading, setUploading] = useState(false);
  const { toast } = useToast();

  const handleFile = async (file) => {
    if (!file) return;
    setUploading(true);
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await fetch(`${API}/api/rahaza/leaves/upload-document`, {
        method: 'POST', headers: { Authorization: headers.Authorization }, body: form,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Unggah gagal');
      onChange({ url: data.url, filename: file.name });
      toast({ title: 'Dokumen berhasil diunggah' });
    } catch (e) { toast({ title: e.message, variant: 'destructive' }); }
    finally { setUploading(false); }
  };

  return (
    <Isian label="Bukti / dokumen pendukung" wajib={!!required} petunjuk={docNote}>
      {value?.url ? (
        <div className="flex items-center gap-2 rounded-md border border-[var(--glass-border)] p-2">
          <FileText className="h-4 w-4 shrink-0 text-[hsl(var(--success-text))]" />
          <span className="min-w-0 flex-1 truncate text-sm">{value.filename}</span>
          <Button asChild variant="link" size="sm" className="h-auto p-0">
            <a href={withFileAuth(`${API}${value.url}`)} target="_blank" rel="noreferrer">Lihat</a>
          </Button>
          <Button type="button" variant="ghost" size="icon-sm" onClick={() => onChange(null)} title="Hapus lampiran" aria-label="Hapus lampiran">
            <X />
          </Button>
        </div>
      ) : (
        <Button type="button" variant="outline" className="w-full border-dashed" onClick={() => fileRef.current?.click()}
          disabled={uploading} data-testid="portal-doc-upload">
          {uploading ? <Loader2 className="animate-spin" /> : <Upload />}
          {uploading ? 'Mengunggah…' : 'Unggah foto/PDF (maks 8 MB)'}
        </Button>
      )}
      <input ref={fileRef} type="file" className="hidden" accept="image/*,application/pdf"
        onChange={e => handleFile(e.target.files?.[0])} />
    </Isian>
  );
}

// ─── MAIN COMPONENT ───────────────────────────────────────────────────────────
export default function PortalSayaCuti({ user, headers }) {
  const { toast } = useToast();
  const [tab, setTab] = useState('leaves');

  const [employee, setEmployee] = useState(null);
  // Tahap 5 (2026-11-07): dulu akun tanpa tautan karyawan berhenti di "Mencari data karyawan..." selamanya
  // (loading hanya dimatikan setelah data cuti dimuat, yang tidak pernah terjadi tanpa karyawan).
  const [empChecked, setEmpChecked] = useState(false);
  const [leaves, setLeaves] = useState([]);
  const [leaveTypes, setLeaveTypes] = useState([]);
  const [balances, setBalances] = useState([]);
  const [overtimes, setOvertimes] = useState([]);
  const [loading, setLoading] = useState(true);

  const [showForm, setShowForm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const EMPTY = { leave_type_id: '', from_date: '', to_date: '', reason: '',
                  is_half_day: false, half_day_period: 'AM', attachment: null };
  const [form, setForm] = useState(EMPTY);
  const [wdPreview, setWdPreview] = useState(null);
  const [wdLoading, setWdLoading] = useState(false);

  // Tahap 2 (2026-11-06): karyawan mengisi tanggal, jumlah jam, dan alasan saja — pengali dari Pengaturan gaji.
  const OT_EMPTY = { date: '', hours: '', reason: '' };
  const [otForm, setOtForm] = useState(OT_EMPTY);
  const [showOtForm, setShowOtForm] = useState(false);

  // 2026-11-09 (Q6, keputusan owner): atasan langsung memutus tingkat 1 cuti/izin/sakit & lembur timnya di sini,
  // lalu HR. Tab hanya tampil bila akun ini atasan seseorang (manager_id karyawan) atau ada pengajuan menunggu.
  const [team, setTeam] = useState({ is_manager: false, items: [] });
  const [deciding, setDeciding] = useState(null);
  const [rejectItem, setRejectItem] = useState(null);
  const [rejectReason, setRejectReason] = useState('');
  const loadTeam = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/api/portal/team-approvals`, { headers });
      setTeam({ is_manager: Boolean(data?.is_manager), items: data?.items || [] });
    } catch { setTeam({ is_manager: false, items: [] }); }
  }, [headers]); // eslint-disable-line
  const decide = async (item, action, reason = '') => {
    setDeciding(`${item.kind}-${item.id}`);
    try {
      const { data } = await axios.post(`${API}/api/portal/team-approvals/${item.kind}/${item.id}/${action}`,
        action === 'reject' ? { reason } : { notes: reason }, { headers });
      toast({ title: data?.message || 'Tersimpan' });
      setRejectItem(null); setRejectReason('');
      loadTeam();
    } catch (e) {
      toast({ title: e.response?.data?.detail || 'Gagal menyimpan keputusan', variant: 'destructive' });
    } finally { setDeciding(null); }
  };

  // Resolve employee from current user — pakai endpoint /portal-saya/me/employee
  const loadEmployee = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/api/portal-saya/me/employee`, { headers });
      if (res.data && res.data.id) setEmployee(res.data);
    } catch (e) {
      // 404 = employee not linked, tampilkan pesan ke user
      if (e.response?.status !== 404) console.error('loadEmployee error', e);
    } finally { setEmpChecked(true); }
  }, [headers]); // eslint-disable-line

  const loadData = useCallback(async () => {
    if (!employee?.id) return;
    setLoading(true);
    try {
      const [lv, lt, bal, ot] = await Promise.all([
        axios.get(`${API}/api/portal-saya/me/leaves?limit=50`, { headers }),
        axios.get(`${API}/api/rahaza/leave-types`, { headers }),
        axios.get(`${API}/api/portal-saya/me/leave-balance`, { headers }),
        // FASE 20 — dulu '/api/rahaza/overtime-requests' (tidak pernah ada di
        // backend). Karena pemanggilnya memakai `.catch(...)`, 404-nya tertelan
        // total: kartu "Lembur Saya" selalu kosong tanpa satu pun pesan error.
        // Endpoint benar '/api/rahaza/overtime' membalas {ok, overtime:[...]}.
        axios.get(`${API}/api/rahaza/overtime?employee_id=${employee.id}&limit=30`, { headers })
          .catch(() => ({ data: { overtime: [] } })),
      ]);
      setLeaves(lv.data?.items || []);
      setLeaveTypes(Array.isArray(lt.data) ? lt.data : []);
      setBalances(bal.data?.balances || []);
      setOvertimes(ot.data?.overtime || ot.data?.items || []);
    } catch (e) { toast({ title: 'Gagal memuat data', variant: 'destructive' }); }
    finally { setLoading(false); }
  }, [employee?.id, headers]); // eslint-disable-line

  useEffect(() => { loadEmployee(); }, [loadEmployee]);
  useEffect(() => { loadData(); }, [loadData]);
  useEffect(() => { if (employee?.id) loadTeam(); }, [employee?.id, loadTeam]);

  // Live working days preview
  useEffect(() => {
    if (!form.from_date || !form.to_date || form.is_half_day) { setWdPreview(null); return; }
    if (new Date(form.to_date) < new Date(form.from_date)) { setWdPreview(null); return; }
    setWdLoading(true);
    axios.get(`${API}/api/rahaza/leaves/working-days?from_date=${form.from_date}&to_date=${form.to_date}`, { headers })
      .then(r => setWdPreview(r.data))
      .catch(() => setWdPreview(null))
      .finally(() => setWdLoading(false));
  }, [form.from_date, form.to_date, form.is_half_day]); // eslint-disable-line

  const selectedLT = leaveTypes.find(lt => lt.id === form.leave_type_id);

  const submitLeave = async () => {
    if (!form.leave_type_id || !form.from_date || !form.to_date)
      return toast({ title: 'Lengkapi jenis dan tanggal', variant: 'destructive' });
    if (form.to_date < form.from_date)
      return toast({ title: 'Tanggal selesai tidak boleh sebelum tanggal mulai', variant: 'destructive' });
    if (!form.reason.trim())
      return toast({ title: 'Alasan wajib diisi', variant: 'destructive' });
    if (form.is_half_day && form.to_date !== form.from_date)
      return toast({ title: 'Setengah hari hanya untuk satu tanggal', variant: 'destructive' });
    if (!employee?.id)
      return toast({ title: 'Data karyawan Anda tidak ditemukan. Hubungi HR.', variant: 'destructive' });

    // Validate document
    if (selectedLT?.requires_document) {
      const maxNoDoc = parseInt(selectedLT.max_days_without_doc || 0);
      const dur = form.is_half_day ? 0.5 : (new Date(form.to_date) - new Date(form.from_date)) / 86400000 + 1;
      if (!form.attachment?.url && (maxNoDoc === 0 || dur > maxNoDoc))
        return toast({ title: `Dokumen wajib: ${selectedLT.doc_note || 'Upload bukti pendukung.'}`, variant: 'destructive' });
    }

    setSubmitting(true);
    try {
      await axios.post(`${API}/api/rahaza/leaves/request`, {
        employee_id:       employee.id,
        leave_type_id:     form.leave_type_id,
        from_date:         form.from_date,
        to_date:           form.to_date,
        reason:            form.reason,
        is_half_day:       form.is_half_day,
        half_day_period:   form.half_day_period,
        attachment_url:    form.attachment?.url || '',
        attachment_filename: form.attachment?.filename || '',
        request_type:      selectedLT?.request_type || 'cuti',
        leave_kind:        selectedLT?.request_type || 'cuti',
      }, { headers });
      toast({ title: 'Pengajuan terkirim. Menunggu persetujuan.' });
      setShowForm(false);
      setForm(EMPTY);
      loadData();
    } catch (e) {
      toast({ title: e.response?.data?.detail || 'Gagal mengirim pengajuan', variant: 'destructive' });
    } finally { setSubmitting(false); }
  };

  const cancelLeave = async (id) => {
    if (!(await confirmDialog({ title: 'Batalkan pengajuan ini?', confirmLabel: 'Batalkan pengajuan', cancelLabel: 'Kembali', danger: true }))) return;
    try {
      await axios.post(`${API}/api/rahaza/leaves/${id}/cancel`, { reason: 'Dibatalkan oleh karyawan' }, { headers });
      toast({ title: 'Pengajuan dibatalkan' });
      loadData();
    } catch (e) {
      toast({ title: e.response?.data?.detail || 'Gagal membatalkan', variant: 'destructive' });
    }
  };

  // Tahap 7: tarik pengajuan lembur yang masih menunggu (409 bila HR baru saja memutusnya).
  const cancelOT = async (id) => {
    if (!(await confirmDialog({ title: 'Batalkan pengajuan lembur ini?', confirmLabel: 'Batalkan pengajuan',
      cancelLabel: 'Kembali', danger: true }))) return;
    try {
      await axios.delete(`${API}/api/rahaza/overtime/${id}`, { headers });
      toast({ title: 'Pengajuan lembur dibatalkan' });
      loadData();
    } catch (e) {
      toast({ title: e.response?.data?.detail || 'Gagal membatalkan', variant: 'destructive' });
      loadData();
    }
  };

  const submitOT = async () => {
    if (!otForm.date || !(Number(otForm.hours) > 0) || !otForm.reason.trim())
      return toast({ title: 'Isi tanggal, jumlah jam, dan alasan', variant: 'destructive' });
    if (!employee?.id)
      return toast({ title: 'Data karyawan tidak ditemukan', variant: 'destructive' });
    setSubmitting(true);
    try {
      // FASE 20 — POST-nya juga salah alamat: endpoint benar '/api/rahaza/overtime'
      // (body {employee_id, date, start_time, end_time, reason} sudah sesuai).
      // Sebelum ini setiap pengajuan lembur karyawan GAGAL dengan pesan generik.
      await axios.post(`${API}/api/rahaza/overtime`, {
        employee_id: employee.id, date: otForm.date, hours: Number(otForm.hours), reason: otForm.reason.trim(),
      }, { headers });
      toast({ title: 'Pengajuan lembur terkirim' });
      setShowOtForm(false);
      setOtForm(OT_EMPTY);
      loadData();
    } catch (e) {
      toast({ title: e.response?.data?.detail || 'Gagal mengirim pengajuan lembur', variant: 'destructive' });
    } finally { setSubmitting(false); }
  };

  if (!employee) {
    return (
      <PageLayout testId="portal-cuti" title="Cuti & lembur" subtitle="Ajukan cuti, izin, sakit, dan lembur, lalu pantau statusnya.">
        {!empChecked ? (
          <p className="py-6 text-center text-sm text-muted-foreground">Mencari data karyawan…</p>
        ) : (
          <EmptyState title="Akun belum terhubung ke data karyawan"
            description="Minta HR menautkannya di Data Karyawan › Tautkan akun. Setelah itu Anda bisa mengajukan cuti dan lembur di sini." />
        )}
      </PageLayout>
    );
  }

  const saldo = balances.filter(b => b.remaining > 0 || b.used > 0);
  const bukaFormCuti = () => { setForm(EMPTY); setShowForm(true); };
  const bukaFormLembur = () => { setOtForm(OT_EMPTY); setShowOtForm(true); };
  const durasi = (lv) => `${lv.duration_days} hari${lv.duration_working_days && lv.duration_working_days !== lv.duration_days ? ` (${lv.duration_working_days} hari kerja)` : ''}`;

  const kolomCuti = [
    { kunci: 'jenis', label: 'Jenis', hp: 'judul', isi: (lv) => (
      <div className="min-w-0" data-testid={`portal-leave-${lv.id}`}>
        <p className="font-medium">{lv.leave_type_name}{lv.is_half_day && <span className="text-muted-foreground"> · ½ hari ({lv.half_day_period === 'PM' ? 'siang' : 'pagi'})</span>}</p>
        {lv.reason && <p className="line-clamp-2 text-xs text-muted-foreground md:max-w-[18rem]">{lv.reason}</p>}
      </div>) },
    { kunci: 'tanggal', label: 'Tanggal', isi: (lv) => <span className="whitespace-nowrap text-sm">{fmt(lv.from_date)} – {fmt(lv.to_date)}</span> },
    { kunci: 'durasi', label: 'Durasi', isi: (lv) => <span className="text-sm">{durasi(lv)}</span> },
    { kunci: 'status', label: 'Status', isi: (lv) => (
      <div className="space-y-0.5">
        <StatusPengajuan status={lv.status} doc={lv} />
        {lv.rejected_reason && <p className="text-xs text-[hsl(var(--danger-text))]">Alasan: {lv.rejected_reason}</p>}
        {lv.holidays_in_period?.length > 0 && (
          <p className="text-xs text-muted-foreground">Libur: {lv.holidays_in_period.map(h => h.name).join(', ')}</p>
        )}
      </div>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (lv) => (
      <div className="flex flex-wrap items-center justify-end gap-1">
        {lv.attachment_url && (
          <Button asChild size="sm" variant="outline">
            <a href={withFileAuth(`${API}${lv.attachment_url}`)} target="_blank" rel="noreferrer"><Paperclip />Dokumen</a>
          </Button>
        )}
        {['pending_approval', 'pending_hr_approval'].includes(lv.status) && (
          <Button variant="outline" size="sm" onClick={() => cancelLeave(lv.id)} data-testid={`leave-cancel-${lv.id}`}>
            <Trash2 />Batalkan
          </Button>
        )}
        {lv.status === 'approved' && new Date(lv.from_date) > new Date() && (
          <Button variant="outline" size="sm" onClick={() => cancelLeave(lv.id)}>Batalkan</Button>
        )}
      </div>) },
  ];

  const kolomLembur = [
    { kunci: 'tanggal', label: 'Tanggal', hp: 'judul', isi: (ot) => <span className="whitespace-nowrap">{fmt(ot.date)}</span> },
    { kunci: 'jam', label: 'Jumlah jam', isi: (ot) => (
      <span className="text-sm">{ot.hours} jam{ot.start_time && ot.end_time ? ` (${ot.start_time}–${ot.end_time})` : ''}</span>) },
    { kunci: 'alasan', label: 'Alasan / pekerjaan', isi: (ot) => <p className="line-clamp-2 text-sm md:max-w-[22rem]">{ot.reason || '—'}</p> },
    { kunci: 'status', label: 'Status', isi: (ot) => <StatusPengajuan status={ot.status || 'pending_approval'} doc={ot} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (ot) => (ot.status === 'pending' ? (
      <Button size="sm" variant="outline" onClick={() => cancelOT(ot.id)} data-testid={`ot-cancel-${ot.id}`}>Batalkan</Button>
    ) : null) },
  ];

  const kolomTim = [
    { kunci: 'karyawan', label: 'Karyawan', hp: 'judul', isi: (it) => (
      <div className="min-w-0"><p className="font-medium">{it.employee_name}</p><p className="text-xs text-muted-foreground">{it.employee_code}</p></div>) },
    { kunci: 'pengajuan', label: 'Pengajuan', isi: (it) => (
      <div className="min-w-0">
        <p className="text-sm font-medium">{it.title} · {it.detail}</p>
        {(it.warnings || []).map((w) => <p key={w} className="text-xs text-[hsl(var(--warning-text))]">{w}</p>)}
      </div>) },
    { kunci: 'tanggal', label: 'Tanggal', isi: (it) => (
      <span className="whitespace-nowrap text-sm">{fmt(it.from_date)}{it.to_date && it.to_date !== it.from_date ? ` – ${fmt(it.to_date)}` : ''}</span>) },
    { kunci: 'alasan', label: 'Alasan', isi: (it) => <p className="line-clamp-2 text-sm md:max-w-[18rem]">{it.reason || '—'}</p> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (it) => (
      <div className="flex flex-wrap items-center justify-end gap-1">
        <Button size="sm" variant="success" disabled={deciding === `${it.kind}-${it.id}`} onClick={() => decide(it, 'approve')}
          data-testid={`team-approve-${it.kind}-${it.id}`}><CheckCircle2 />Setujui</Button>
        <Button size="sm" variant="outline" onClick={() => { setRejectItem(it); setRejectReason(''); }}
          data-testid={`team-reject-${it.kind}-${it.id}`}><XCircle />Tolak</Button>
      </div>) },
  ];

  return (
    <PageLayout testId="portal-cuti" title="Cuti & lembur"
      subtitle={`${employee.name} · ${employee.employee_code} — ajukan cuti, izin, sakit, dan lembur, lalu pantau statusnya.`}
      actions={tab === 'team' ? null : tab === 'leaves'
        ? <Button onClick={bukaFormCuti} data-testid="btn-ajukan-cuti"><Plus />Ajukan cuti/izin</Button>
        : <Button onClick={bukaFormLembur} data-testid="btn-ajukan-lembur"><Plus />Ajukan lembur</Button>}
      tools={(
        <Button variant="outline" size="icon" onClick={() => loadData()} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      )}
      summary={saldo.length > 0 && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="portal-cuti-saldo">
          {saldo.map(b => (
            /* Tahap 7: jenis tak dibayar tidak punya jatah — tampilkan pemakaian, bukan "sisa" minus */
            /* 2026-11-09 (Q7): jenis per bulan / per kejadian / sakit bersurat tanpa "sisa per tahun" → tampil terpakai + aturannya */
            <StatTile key={b.leave_type_id} label={b.leave_type_name}
              value={`${b.unpaid || b.remaining == null ? b.used : b.remaining} hari`}
              sub={b.unpaid ? 'terpakai · tidak dibayar'
                : b.remaining == null ? `terpakai · ${b.quota_note || 'tanpa jatah tahunan'}`
                  : `sisa dari ${b.quota} hari${b.quota_note ? ` · ${b.quota_note}` : ''}`} />
          ))}
        </div>
      )}>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="leaves" data-testid="tab-cuti">Cuti & izin ({leaves.length})</TabsTrigger>
          <TabsTrigger value="overtime" data-testid="tab-lembur">Lembur ({overtimes.length})</TabsTrigger>
          {team.is_manager && (
            <TabsTrigger value="team" data-testid="tab-tim">Persetujuan tim ({team.items.length})</TabsTrigger>
          )}
        </TabsList>

        {/* ── CUTI/IZIN TAB ── */}
        <TabsContent value="leaves" className="mt-4 space-y-3">
          {leaves.length > 0 && (
            <div className="flex justify-end">
              <TombolUnduh namaBerkas="pengajuan-cuti-saya" namaLembar="Cuti & izin" baris={leaves} testId="cuti-unduh" kolom={[
                { label: 'Jenis', nilai: (lv) => lv.leave_type_name }, { label: 'Dari', nilai: (lv) => fmt(lv.from_date) },
                { label: 'Sampai', nilai: (lv) => fmt(lv.to_date) }, { label: 'Durasi (hari)', nilai: (lv) => lv.duration_days },
                { label: 'Hari kerja', nilai: (lv) => lv.duration_working_days ?? '' },
                { label: 'Setengah hari', nilai: (lv) => (lv.is_half_day ? (lv.half_day_period === 'PM' ? 'Siang' : 'Pagi') : '') },
                { label: 'Status', nilai: (lv) => labelStatus(lv.status) }, { label: 'Alasan', nilai: (lv) => lv.reason || '' },
                { label: 'Alasan ditolak', nilai: (lv) => lv.rejected_reason || '' },
              ]} />
            </div>
          )}
          {loading && leaves.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">Memuat pengajuan…</p>
          ) : (
            <TabelData kolom={kolomCuti} baris={leaves} testId="portal-leave-table"
              kosong={<EmptyState title="Belum ada pengajuan" description="Tekan Ajukan cuti/izin untuk membuat pengajuan pertama." />} />
          )}
        </TabsContent>

        {/* ── LEMBUR TAB ── */}
        <TabsContent value="overtime" className="mt-4 space-y-3">
          {overtimes.length > 0 && (
            <div className="flex justify-end">
              <TombolUnduh namaBerkas="pengajuan-lembur-saya" namaLembar="Lembur" baris={overtimes} testId="lembur-unduh" kolom={[
                { label: 'Tanggal', nilai: (ot) => fmt(ot.date) }, { label: 'Jumlah jam', nilai: (ot) => Number(ot.hours) || 0 },
                { label: 'Mulai', nilai: (ot) => ot.start_time || '' }, { label: 'Selesai', nilai: (ot) => ot.end_time || '' },
                { label: 'Alasan', nilai: (ot) => ot.reason || '' }, { label: 'Status', nilai: (ot) => labelStatus(ot.status || 'pending_approval') },
              ]} />
            </div>
          )}
          <TabelData kolom={kolomLembur} baris={overtimes} testId="portal-ot-table"
            kosong={<EmptyState title="Belum ada pengajuan lembur" description="Tekan Ajukan lembur untuk mengajukan jam lembur." />} />
        </TabsContent>

        {/* ── PERSETUJUAN TIM (atasan langsung) ── */}
        {team.is_manager && (
          <TabsContent value="team" className="mt-4 space-y-3">
            <p className="text-sm text-muted-foreground">Pengajuan anggota tim yang menunggu keputusan Anda sebagai atasan langsung. Sesudah Anda setujui, HR memutus tahap berikutnya.</p>
            <TabelData kolom={kolomTim} baris={team.items} kunci={(it) => `${it.kind}-${it.id}`} testId="portal-team-table"
              kosong={<EmptyState title="Tidak ada pengajuan tim yang menunggu" description="Pengajuan cuti, izin, sakit, dan lembur anggota tim akan muncul di sini." />} />
          </TabsContent>
        )}
      </Tabs>

      <FormPopup open={Boolean(rejectItem)} onClose={() => setRejectItem(null)} ukuran="pendek" testId="team-reject-form"
        judul="Tolak pengajuan" keterangan={rejectItem ? `${rejectItem.employee_name} · ${rejectItem.title} ${rejectItem.detail}` : ''}
        onSimpan={() => decide(rejectItem, 'reject', rejectReason.trim())} menyimpan={Boolean(deciding)} labelSimpan="Tolak">
        <Isian label="Alasan penolakan" wajib htmlFor="team-reject-reason">
          <Textarea id="team-reject-reason" rows={2} value={rejectReason} onChange={e => setRejectReason(e.target.value)}
            data-testid="team-reject-reason" />
        </Isian>
      </FormPopup>

      {/* Form pengajuan cuti / izin */}
      <FormPopup open={showForm} onClose={() => setShowForm(false)} ukuran="panjang" testId="leave-form"
        judul="Ajukan cuti / izin" keterangan="Pengajuan diperiksa atasan lalu HR."
        onSimpan={submitLeave} menyimpan={submitting} labelSimpan="Kirim pengajuan">
        <Isian label="Jenis izin/cuti" wajib petunjuk={selectedLT?.legal_basis}>
          {/* Tahap 5: hanya jenis AKTIF, bisa dicari */}
          <SmartNativeSelect value={form.leave_type_id}
            onChange={e => setForm(f => ({ ...f, leave_type_id: e.target.value }))}
            data-testid="select-leave-type" className="w-full">
            <option value="">— Pilih jenis izin/cuti —</option>
            {['cuti', 'sakit', 'izin'].map(rt => (
              <optgroup key={rt} label={REQ_TYPE_CFG[rt].label}>
                {leaveTypes.filter(lt => lt.active !== false && (lt.request_type || 'cuti') === rt).map(lt => (
                  <option key={lt.id} value={lt.id}>{`${REQ_TYPE_CFG[rt].label} · ${lt.name}${lt.quota_default ? ` (${lt.quota_default} hari)` : ''}`}</option>
                ))}
              </optgroup>
            ))}
          </SmartNativeSelect>
        </Isian>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Isian label="Dari tanggal" wajib>
            <DatePicker value={form.from_date} testId="leave-from-date"
              onChange={(v) => setForm(f => ({ ...f, from_date: v || '', to_date: f.is_half_day || !f.to_date ? (v || '') : f.to_date }))} />
          </Isian>
          <Isian label="Sampai tanggal" wajib>
            <DatePicker value={form.to_date} min={form.from_date || undefined} disabled={form.is_half_day} testId="leave-to-date"
              onChange={(v) => setForm(f => ({ ...f, to_date: v || '' }))} />
          </Isian>
        </div>

        {/* Pratinjau hari kerja */}
        {(wdPreview || wdLoading) && !form.is_half_day && (
          <Notice tone={wdLoading ? 'info' : wdPreview?.holiday_days > 0 ? 'warning' : 'success'} testId="portal-wd-preview">
            {wdLoading ? 'Menghitung hari kerja…' : wdPreview ? (
              <>
                <span className="font-medium">
                  {wdPreview.working_days === wdPreview.calendar_days
                    ? `${wdPreview.working_days} hari kerja`
                    : `${wdPreview.working_days} hari kerja (dari ${wdPreview.calendar_days} hari)`}
                </span>
                {wdPreview.holiday_days > 0 && (
                  <span className="block">Libur dalam periode: {wdPreview.holidays.map(h => h.name).join(', ')}</span>
                )}
                {wdPreview.weekend_days > 0 && (
                  <span className="block">{wdPreview.weekend_days} hari akhir pekan tidak dihitung</span>
                )}
              </>
            ) : null}
          </Notice>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <label className="flex cursor-pointer items-center gap-2 text-sm">
            <input type="checkbox" checked={form.is_half_day} data-testid="leave-half-day" className="h-4 w-4 accent-[hsl(var(--primary))]"
              onChange={e => setForm(f => ({ ...f, is_half_day: e.target.checked, to_date: e.target.checked ? f.from_date : f.to_date }))} />
            Setengah hari
          </label>
          {form.is_half_day && (
            <SmartNativeSelect value={form.half_day_period} onChange={e => setForm(f => ({ ...f, half_day_period: e.target.value }))}
              searchable={false} className="w-full" wrapperClassName="w-40" aria-label="Bagian hari">
              <option value="AM">Pagi</option>
              <option value="PM">Siang</option>
            </SmartNativeSelect>
          )}
        </div>

        <Isian label="Alasan" wajib htmlFor="leave-reason">
          <Textarea id="leave-reason" rows={2} placeholder="Tulis alasan…"
            value={form.reason} onChange={e => setForm(f => ({ ...f, reason: e.target.value }))}
            data-testid="leave-reason" />
        </Isian>

        <DocUpload
          value={form.attachment}
          onChange={att => setForm(f => ({ ...f, attachment: att }))}
          required={selectedLT?.requires_document}
          docNote={selectedLT?.doc_note}
          headers={headers}
        />
      </FormPopup>

      {/* Form pengajuan lembur */}
      <FormPopup open={showOtForm} onClose={() => setShowOtForm(false)} ukuran="pendek" testId="ot-form"
        judul="Ajukan lembur" keterangan="Pengali upah lembur mengikuti Pengaturan gaji."
        onSimpan={submitOT} menyimpan={submitting} labelSimpan="Kirim pengajuan">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Isian label="Tanggal" wajib>
            <DatePicker value={otForm.date} onChange={(v) => setOtForm(f => ({ ...f, date: v || '' }))} testId="ot-date" />
          </Isian>
          <Isian label="Jumlah jam" wajib htmlFor="ot-hours">
            <Input id="ot-hours" type="number" min="0.5" max="12" step="0.5" data-testid="ot-hours"
              value={otForm.hours} onChange={e => setOtForm(f => ({ ...f, hours: e.target.value }))} />
          </Isian>
        </div>
        <Isian label="Alasan / pekerjaan" wajib htmlFor="ot-reason">
          <Textarea id="ot-reason" rows={2} data-testid="ot-reason"
            value={otForm.reason} onChange={e => setOtForm(f => ({ ...f, reason: e.target.value }))} />
        </Isian>
      </FormPopup>
    </PageLayout>
  );
}

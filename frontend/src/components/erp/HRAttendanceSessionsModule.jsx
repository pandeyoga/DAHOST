/**
 * HRAttendanceSessionsModule — REKAP ISTIRAHAT & IZIN + ANTREAN PERSETUJUAN.
 *
 * ════════════════════════════════════════════════════════════════════════════
 * KENAPA MODUL INI ADA
 * ════════════════════════════════════════════════════════════════════════════
 * Permintaan user 2026-07-26:
 *   · "Izin keluar butuh persetujuan atasan/HR dulu, bukan langsung tercatat."
 *   · "Buatkan menu Rekap Istirahat & Izin (filter tanggal/karyawan) + export Excel."
 *
 * Sebelum ini backend sudah menyimpan sesi keluar-masuk di
 * `rahaza_attendance_events.sessions[]`, tetapi TIDAK ADA satu pun layar yang
 * menampilkannya — jadi HR tidak punya cara melihat siapa istirahat berapa lama
 * atau menyetujui izin. Modul ini menutup celah FE↔BE tersebut.
 *
 * Endpoint yang dipakai (semuanya sudah ada di backend):
 *   GET  /api/rahaza/attendance/permits?status=pending
 *   POST /api/rahaza/attendance/permits/{id}/approve | /reject
 *   GET  /api/rahaza/attendance/sessions?from_date&to_date&employee_id&kind&status
 *   GET  /api/rahaza/attendance/sessions/export.xlsx
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout (dulu kepala buatan sendiri + "PORTAL SDM › KEHADIRAN"),
 * tab buatan sendiri → pil penyaring, penyaring satu baris (dulu 6 kotak selebar layar), periode lewat
 * PeriodPicker, tabel standar + unduh Excel/CSV, kartu angka standar (disembunyikan bila semua 0),
 * setujui = popup form hijau, tolak = konfirmasi merah dengan alasan wajib (sama seperti dulu).
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { EmployeeSelect } from './hr/hrPickers';
import { CheckCircle2, Download, Loader2, RefreshCw, Search, Timer, XCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { formatTanggalID } from '@/components/ui/date-picker';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { toast } from 'sonner';
import { todayWIB, daysAgoWIB, parseServerTime } from '@/lib/waktu';
import PageLayout from './layout/PageLayout';
import PeriodPicker from './finance/PeriodPicker';
import { EmptyState, StatTile, StatusBadge } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;

// Jam dari server tanpa zona = UTC (parseServerTime), ditampilkan WIB.
const fmtTime = (v) => {
  const d = parseServerTime(v);
  if (!d) return '—';
  try {
    return d.toLocaleTimeString('id-ID', {
      hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Jakarta',
    });
  } catch { return '—'; }
};

const fmtDur = (m) => {
  const x = Math.max(0, Math.round(Number(m) || 0));
  return x < 60 ? `${x} mnt` : `${Math.floor(x / 60)} j ${x % 60} mnt`;
};

const STATUS = {
  pending: { label: 'Menunggu', tone: 'warning' },
  approved: { label: 'Disetujui', tone: 'success' },
  rejected: { label: 'Ditolak', tone: 'danger' },
  cancelled: { label: 'Dibatalkan', tone: 'muted' },
  not_required: { label: 'Tercatat', tone: 'info' },
};
const JENIS = { istirahat: 'Istirahat', izin: 'Izin' };
const statusLabel = (s) => STATUS[s]?.label || s || '—';

export default function HRAttendanceSessionsModule({ token }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);
  const [tab, setTab] = useState('pending');

  const [pending, setPending] = useState([]);
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState({});
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [exporting, setExporting] = useState(false);

  const [filters, setFilters] = useState({
    from_date: daysAgoWIB(7), to_date: todayWIB(),
    employee_id: '', kind: '', status: '', q: '',
  });

  const [approve, setApprove] = useState(null);   // item yang sedang disetujui (popup form)
  const [notes, setNotes] = useState('');

  const loadPending = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/api/rahaza/attendance/permits?status=pending`, { headers });
      setPending(r.data?.items || []);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Gagal memuat antrean izin');
    }
  }, [headers]);

  const loadRows = useCallback(async () => {
    try {
      const p = new URLSearchParams();
      if (filters.from_date) p.set('from_date', filters.from_date);
      if (filters.to_date) p.set('to_date', filters.to_date);
      if (filters.employee_id) p.set('employee_id', filters.employee_id);
      if (filters.kind) p.set('kind', filters.kind);
      if (filters.status) p.set('status', filters.status);
      const r = await axios.get(`${API}/api/rahaza/attendance/sessions?${p}`, { headers });
      setRows(r.data?.items || []);
      setSummary(r.data?.summary || {});
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Gagal memuat rekap sesi');
    }
  }, [headers, filters]);

  const loadAll = useCallback(async () => {
    setLoading(true);
    await Promise.all([loadPending(), loadRows()]);
    setLoading(false);
  }, [loadPending, loadRows]);

  useEffect(() => {
    // Tahap 5 (2026-11-07): dulu tanpa limit → batas bawaan API 50 karyawan (penyaring rekap: termasuk yang sudah keluar)
    axios.get(`${API}/api/rahaza/employees?limit=500`, { headers })
      .then((r) => {
        const d = r.data;
        setEmployees(Array.isArray(d) ? d : (d?.items || d?.rows || d?.data || []));
      })
      .catch(() => setEmployees([]));
  }, [headers]);

  useEffect(() => { loadAll(); }, [loadAll]);

  const submitDecision = async (item, mode, catatan) => {
    if (mode === 'reject' && !catatan.trim()) {
      toast.error('Alasan penolakan wajib diisi.');
      return;
    }
    setBusy(item.id);
    try {
      await axios.post(
        `${API}/api/rahaza/attendance/permits/${item.id}/${mode}`,
        { notes: catatan.trim() }, { headers },
      );
      toast.success(mode === 'approve'
        ? `Izin ${item.employee_name} disetujui — durasi dihitung mulai sekarang.`
        : `Izin ${item.employee_name} ditolak.`);
      setApprove(null); setNotes('');
      await loadAll();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Gagal memproses keputusan');
    } finally { setBusy(''); }
  };

  const tolak = async (item) => {
    const alasan = await confirmDialog({
      title: 'Tolak izin keluar?',
      body: `${item.employee_name} (${item.employee_code}) — "${item.reason}". Alasan penolakan dikirim ke karyawan.`,
      confirmLabel: 'Tolak', danger: true,
      input: { label: 'Alasan penolakan', placeholder: 'mis. sedang tenggat produksi' },
    });
    if (!alasan) return;
    await submitDecision(item, 'reject', alasan);
  };

  const exportExcel = async () => {
    setExporting(true);
    try {
      const p = new URLSearchParams();
      if (filters.from_date) p.set('from_date', filters.from_date);
      if (filters.to_date) p.set('to_date', filters.to_date);
      if (filters.employee_id) p.set('employee_id', filters.employee_id);
      if (filters.kind) p.set('kind', filters.kind);
      if (filters.status) p.set('status', filters.status);
      const r = await axios.get(`${API}/api/rahaza/attendance/sessions/export.xlsx?${p}`,
        { headers, responseType: 'blob' });
      const url = URL.createObjectURL(new Blob([r.data]));
      const a = document.createElement('a');
      a.href = url;
      a.download = `rekap_istirahat_izin_${filters.from_date}_${filters.to_date}.xlsx`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
      toast.success('Rekap Excel diunduh.');
    } catch (e) {
      toast.error('Gagal mengunduh Excel');
    } finally { setExporting(false); }
  };

  const setF = (patch) => setFilters((f) => ({ ...f, ...patch }));
  const q = filters.q.trim().toLowerCase();
  const filtered = rows.filter((r) => {
    if (!q) return true;
    return [r.employee_name, r.employee_code, r.reason, r.decision_notes]
      .some((v) => String(v || '').toLowerCase().includes(q));
  });
  const pendingShown = pending.filter((it) => !q
    || [it.employee_name, it.employee_code, it.reason].some((v) => String(v || '').toLowerCase().includes(q)));

  const ditolakBatal = (summary.rejected || 0) + (summary.cancelled || 0);
  const adaRingkasan = (summary.istirahat_count || 0) + (summary.izin_count || 0) + (summary.pending || 0) + ditolakBatal > 0;

  const kolomPending = [
    { kunci: 'karyawan', label: 'Karyawan', hp: 'judul', isi: (it) => (
      <div className="min-w-0"><p className="font-medium text-foreground">{it.employee_name}</p>
        <p className="text-xs text-muted-foreground">{it.employee_code}</p></div>) },
    { kunci: 'tanggal', label: 'Tanggal', isi: (it) => <span className="whitespace-nowrap">{formatTanggalID(it.date)}</span> },
    { kunci: 'diajukan', label: 'Diajukan', rata: 'kanan', isi: (it) => <span className="tabular-nums">{fmtTime(it.requested_at)}</span> },
    { kunci: 'alasan', label: 'Alasan', isi: (it) => <span className="block max-w-[22rem] truncate" title={it.reason || ''}>{it.reason || '—'}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (it) => (
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="success" disabled={busy === it.id}
          onClick={() => { setApprove(it); setNotes(''); }} data-testid={`permit-approve-${it.id}`}>
          <CheckCircle2 /> Setujui
        </Button>
        <Button size="sm" variant="destructive" disabled={busy === it.id}
          onClick={() => tolak(it)} data-testid={`permit-reject-${it.id}`}>
          <XCircle /> Tolak
        </Button>
      </div>) },
  ];

  const kolomRekap = [
    { kunci: 'tanggal', label: 'Tanggal', hp: 'keterangan', isi: (r) => <span className="whitespace-nowrap">{formatTanggalID(r.date)}</span> },
    { kunci: 'karyawan', label: 'Karyawan', hp: 'judul', isi: (r) => (
      <div className="min-w-0"><p className="font-medium text-foreground">{r.employee_name}</p>
        <p className="text-xs text-muted-foreground">{r.employee_code}</p></div>) },
    { kunci: 'jenis', label: 'Jenis', isi: (r) => JENIS[r.kind] || r.kind },
    { kunci: 'keluar', label: 'Keluar', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtTime(r.out_at)}</span> },
    { kunci: 'kembali', label: 'Kembali', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtTime(r.in_at)}</span> },
    { kunci: 'durasi', label: 'Durasi', rata: 'kanan', isi: (r) => <span className="whitespace-nowrap tabular-nums">{r.minutes ? fmtDur(r.minutes) : '—'}</span> },
    { kunci: 'alasan', label: 'Alasan', isi: (r) => <span className="block max-w-[14rem] truncate" title={r.reason || ''}>{r.reason || '—'}</span> },
    { kunci: 'status', label: 'Status', isi: (r) => <StatusBadge status={r.approval_status} label={statusLabel(r.approval_status)} tone={STATUS[r.approval_status]?.tone} /> },
    { kunci: 'diputuskan', label: 'Diputuskan', isi: (r) => (
      <span className="text-sm text-muted-foreground">{r.approved_by_name || '—'}{r.decision_notes ? ` · ${r.decision_notes}` : ''}</span>) },
  ];

  const unduhRekap = [
    { label: 'Tanggal', nilai: (r) => formatTanggalID(r.date) },
    { label: 'Kode karyawan', nilai: (r) => r.employee_code },
    { label: 'Nama karyawan', nilai: (r) => r.employee_name },
    { label: 'Jenis', nilai: (r) => JENIS[r.kind] || r.kind },
    { label: 'Keluar', nilai: (r) => fmtTime(r.out_at) },
    { label: 'Kembali', nilai: (r) => fmtTime(r.in_at) },
    { label: 'Durasi (menit)', nilai: (r) => Math.round(Number(r.minutes) || 0) },
    { label: 'Alasan', nilai: (r) => r.reason || '' },
    { label: 'Status', nilai: (r) => statusLabel(r.approval_status) },
    { label: 'Diputuskan oleh', nilai: (r) => r.approved_by_name || '' },
    { label: 'Catatan keputusan', nilai: (r) => r.decision_notes || '' },
  ];
  const unduhPending = [
    { label: 'Tanggal', nilai: (it) => formatTanggalID(it.date) },
    { label: 'Kode karyawan', nilai: (it) => it.employee_code },
    { label: 'Nama karyawan', nilai: (it) => it.employee_name },
    { label: 'Diajukan', nilai: (it) => fmtTime(it.requested_at) },
    { label: 'Alasan', nilai: (it) => it.reason || '' },
  ];

  const cari = (
    <div className="relative w-full sm:w-64">
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
      <Input className="pl-8" placeholder="Cari nama, NIK, alasan" data-testid="filter-q" aria-label="Cari"
        value={filters.q} onChange={(e) => setF({ q: e.target.value })} />
    </div>
  );

  return (
    <PageLayout testId="hr-attendance-sessions" title="Istirahat & izin"
      subtitle="Setujui izin keluar karyawan dan lihat rekap istirahat. Hanya izin disetujui yang memotong jam kerja."
      filters={<>
        <FilterChips hideWhenEmpty={false} value={tab} onChange={setTab} testId="tab" ariaLabel="Tampilan"
          options={[
            { key: 'pending', label: 'Menunggu persetujuan', count: pending.length },
            { key: 'rekap', label: 'Rekap' },
          ]} />
        {cari}
        {tab === 'rekap' && <>
          <PeriodPicker testId="filter-period"
            value={{ preset: filters.preset || 'custom', from: filters.from_date, to: filters.to_date }}
            onChange={(p) => setF({ preset: p.preset, from_date: p.from, to_date: p.to })} />
          <EmployeeSelect employees={employees} value={filters.employee_id} allLabel="Semua karyawan"
            onChange={(v) => setF({ employee_id: v })} testId="filter-employee" className="h-9 w-56" />
          <SmartNativeSelect id="f-kind" data-testid="filter-kind" searchable={false} aria-label="Jenis"
            className="h-9 w-40" value={filters.kind} onChange={(e) => setF({ kind: e.target.value })}>
            <option value="">Semua jenis</option>
            <option value="istirahat">Istirahat</option>
            <option value="izin">Izin</option>
          </SmartNativeSelect>
          <SmartNativeSelect id="f-status" data-testid="filter-status" searchable={false} aria-label="Status"
            className="h-9 w-44" value={filters.status} onChange={(e) => setF({ status: e.target.value })}>
            <option value="">Semua status</option>
            <option value="pending">Menunggu</option>
            <option value="approved">Disetujui</option>
            <option value="rejected">Ditolak</option>
            <option value="cancelled">Dibatalkan</option>
            <option value="not_required">Istirahat (tercatat)</option>
          </SmartNativeSelect>
        </>}
        {/* Unduh & muat ulang di ujung kanan; di HP turun ke baris sendiri (tidak menimpa penyaring) */}
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {tab === 'rekap' ? <>
            <TombolUnduh namaBerkas={`rekap-istirahat-izin-${filters.from_date}-${filters.to_date}`} namaLembar="Rekap"
              baris={filtered} kolom={unduhRekap} testId="rekap-unduh" />
            <Button variant="outline" onClick={exportExcel} disabled={exporting} data-testid="export-excel"
              title="Rekap Excel dari server, sesuai penyaring periode, karyawan, jenis, dan status">
              {exporting ? <Loader2 className="animate-spin" /> : <Download />}
              Rekap Excel
            </Button>
          </> : (
            <TombolUnduh namaBerkas="izin-menunggu-persetujuan" namaLembar="Menunggu" baris={pendingShown}
              kolom={unduhPending} testId="pending-unduh" />
          )}
          <Button variant="outline" size="icon" onClick={loadAll} disabled={loading} title="Muat ulang" aria-label="Muat ulang" data-testid="sessions-refresh">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
        </div>
      </>}
      summary={tab === 'rekap' && !loading && adaRingkasan && (
        /* Angka dari server untuk periode & penyaring yang sama dengan tabel (kata cari tidak ikut dihitung). */
        <div className="grid grid-cols-2 gap-2 lg:grid-cols-4" data-testid="rekap-ringkasan">
          <StatTile label="Sesi istirahat" value={summary.istirahat_count || 0} sub={`${fmtDur(summary.istirahat_minutes)} total`}
            testId="stat-istirahat" />
          <StatTile label="Sesi izin" value={summary.izin_count || 0} sub={`${fmtDur(summary.izin_minutes)} disetujui`}
            testId="stat-izin" />
          <StatTile label="Menunggu" value={summary.pending || 0} accent={summary.pending ? 'warning' : 'muted'}
            sub="Izin menunggu keputusan dalam periode ini" testId="stat-pending" />
          <StatTile label="Ditolak / batal" value={ditolakBatal} sub="Tidak memotong jam kerja" testId="stat-rejected" />
        </div>
      )}>
      {loading ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat…</p>
      ) : tab === 'pending' ? (
        <TabelData kolom={kolomPending} baris={pendingShown} testId="pending-list"
          kosong={<EmptyState icon={CheckCircle2} testId="pending-empty"
            title={pending.length ? 'Tidak ada izin yang cocok' : 'Tidak ada pengajuan izin yang menunggu'}
            description={pending.length ? 'Ubah kata pencarian.' : 'Pengajuan izin keluar dari karyawan akan tampil di sini.'} />} />
      ) : (
        <div className="overflow-x-auto">
          <TabelData kolom={kolomRekap} baris={filtered} kunci={(r) => `${r.id}`} testId="rekap-table"
            kosong={<EmptyState icon={Timer} testId="rekap-empty" title="Tidak ada sesi istirahat atau izin"
              description={rows.length ? 'Ubah kata pencarian.' : 'Ubah periode atau penyaring lain.'} />} />
        </div>
      )}

      {/* Popup setujui izin (catatan opsional) */}
      <FormPopup open={Boolean(approve)} onClose={() => { setApprove(null); setNotes(''); }} ukuran="pendek"
        judul="Setujui izin keluar" testId="decide-dialog" labelSimpan="Setujui" menyimpan={Boolean(busy)}
        keterangan={approve ? `${approve.employee_name} (${approve.employee_code}) — "${approve.reason}". Durasi izin dihitung mulai saat disetujui dan tidak dibayar sebagai jam kerja.` : ''}
        onSimpan={() => submitDecision(approve, 'approve', notes)}>
        <Isian label="Catatan (opsional)" htmlFor="decide-notes">
          <Textarea id="decide-notes" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)}
            data-testid="decide-notes" placeholder="mis. maksimal 1 jam" />
        </Isian>
      </FormPopup>
    </PageLayout>
  );
}

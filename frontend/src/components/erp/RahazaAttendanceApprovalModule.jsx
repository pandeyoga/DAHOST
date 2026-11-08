/**
 * RahazaAttendanceApprovalModule — antrean pemeriksaan absen selfie oleh HR (tab "Persetujuan absen").
 *
 * Tahap 2 (2026-11-06):
 * · Foto selfie masuk & pulang TAMPIL saat HR memeriksa (dulu tidak ada fotonya sama sekali).
 * · Cetakan PageLayout; rincian lewat DetailPanel (sejak Standar UI/UX v2 tampil sebagai popup).
 * · Tanggal yang sudah masuk gaji final ditolak server dengan pesan (koreksi lewat pengajuan koreksi).
 * Standar UI/UX v2 (8 Nov 2026): rincian = popup (DetailPanel), tabel standar + unduh Excel/CSV,
 * tombol Setujui hijau / Tolak merah.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import axios from 'axios';
import { CheckCircle2, ClipboardCheck, Loader2, MapPin, RefreshCw, XCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import PageLayout, { DetailPanel } from './layout/PageLayout';
import PeriodPicker, { periodFromPreset } from './finance/PeriodPicker';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';
import { withFileAuth } from '@/lib/fileUrl';
import { parseServerTime } from '@/lib/waktu';

const BACKEND = process.env.REACT_APP_BACKEND_URL;
const TZ = 'Asia/Jakarta';
// Tahap 7 (2026-11-07): jam server tanpa zona = UTC (dulu di browser WIB tampil mundur 7 jam: 03.04 → 20.04).
const fmtTime = (ts) => { const d = parseServerTime(ts); if (!d) return '-'; try { return d.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', timeZone: TZ }); } catch { return '-'; } };
const fmtDate = (d) => { try { return new Date(`${d}T00:00:00+07:00`).toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric', timeZone: TZ }); } catch { return d; } };

const APPROVAL = {
  pending: { label: 'Menunggu', tone: 'warning' },
  approved: { label: 'Disetujui', tone: 'success' },
  rejected: { label: 'Ditolak', tone: 'danger' },
  auto_approved: { label: 'Otomatis', tone: 'info' },
};
const METHOD = { selfie_geo_ai: 'Selfie', webauthn: 'Biometrik HP', device_zkteco: 'Mesin sidik jari', manual: 'Manual HR' };
const geoText = (r) => (r.geo_status === 'in_range' ? `Di area kantor${r.geo_distance_m != null ? ` (${r.geo_distance_m} m)` : ''}`
  : r.geo_status === 'out_of_range' ? `Di luar area (${r.geo_distance_m} m)` : 'Tidak diperiksa');

function SelfiePhoto({ url, label, testId }) {
  if (!url) {
    return (
      <div className="space-y-1">
        <p className="text-xs text-muted-foreground">{label}</p>
        <div className="aspect-[3/4] w-full rounded-[var(--radius-md)] bg-muted grid place-items-center text-xs text-muted-foreground">
          Tanpa foto
        </div>
      </div>
    );
  }
  const src = withFileAuth(url.startsWith('http') ? url : `${BACKEND}${url}`);
  return (
    <div className="space-y-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <a href={src} target="_blank" rel="noreferrer" title="Buka foto ukuran penuh">
        <img src={src} alt={label} className="aspect-[3/4] w-full rounded-[var(--radius-md)] object-cover border border-[var(--glass-border)]"
          data-testid={testId} />
      </a>
    </div>
  );
}

export default function RahazaAttendanceApprovalModule({ token }) {
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState('pending');
  const [period, setPeriod] = useState(() => ({ ...periodFromPreset('custom'), preset: 'custom',
    from: new Date(Date.now() - 7 * 86400000).toLocaleDateString('en-CA', { timeZone: TZ }),
    to: new Date().toLocaleDateString('en-CA', { timeZone: TZ }) }));
  const [selected, setSelected] = useState(null);
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  const loadRecords = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ status: statusFilter });
      if (period.from) params.set('from_date', period.from);
      if (period.to) params.set('to_date', period.to);
      const res = await axios.get(`${BACKEND}/api/rahaza/attendance/approvals?${params}`, { headers });
      setRecords(res.data || []);
    } catch (e) {
      setMsg({ tone: 'danger', text: e.response?.data?.detail || 'Gagal memuat antrean absen' });
    } finally { setLoading(false); }
  }, [statusFilter, period.from, period.to, headers]);

  useEffect(() => { loadRecords(); }, [loadRecords]);

  const decide = async (approve) => {
    if (!approve && !notes.trim()) { setMsg({ tone: 'danger', text: 'Catatan wajib diisi untuk penolakan.' }); return; }
    setBusy(true);
    try {
      await axios.post(`${BACKEND}/api/rahaza/attendance/approvals/${selected.id}/${approve ? 'approve' : 'reject'}`,
        { notes }, { headers });
      setMsg({ tone: 'success', text: approve ? 'Absen disetujui.' : 'Absen ditolak (tercatat alpa).' });
      setSelected(null);
      setNotes('');
      await loadRecords();
    } catch (e) {
      setMsg({ tone: 'danger', text: e.response?.data?.detail || 'Gagal menyimpan keputusan' });
    } finally { setBusy(false); }
  };

  const { page, setPage, totalPages, total, paged } = useClientPagination(records, 10);
  const pendingCount = records.filter((r) => r.approval_status === 'pending').length;
  const buka = (rec) => { setSelected(rec); setNotes(''); setMsg(null); };
  const kolom = [
    { kunci: 'karyawan', label: 'Karyawan', hp: 'judul', isi: (rec) => (
      <div className="min-w-0">
        <p className="font-medium text-foreground">{rec.employee_name || '-'}</p>
        <p className="text-xs text-muted-foreground">{rec.employee_code}{rec.department && rec.department !== '-' ? ` · ${rec.department}` : ''}</p>
      </div>) },
    { kunci: 'tanggal', label: 'Tanggal', isi: (rec) => <span className="whitespace-nowrap">{fmtDate(rec.date)}</span> },
    { kunci: 'jam', label: 'Masuk / pulang', isi: (rec) => <span className="tabular-nums">{fmtTime(rec.clock_in)} / {fmtTime(rec.clock_out)}</span> },
    { kunci: 'foto', label: 'Foto', hp: false, isi: (rec) => (rec.photo_selfie_url ? (
      <img src={withFileAuth(`${BACKEND}${rec.photo_selfie_url}`)} alt="Selfie masuk"
        className="h-10 w-10 rounded-[var(--radius-sm)] border border-[var(--glass-border)] object-cover" />
    ) : <span className="text-xs text-muted-foreground">—</span>) },
    { kunci: 'lokasi', label: 'Lokasi', isi: (rec) => <span className="text-sm">{geoText(rec)}</span> },
    { kunci: 'status', label: pendingCount > 0 ? `Status (${pendingCount} menunggu)` : 'Status', isi: (rec) => (
      <StatusBadge status={rec.approval_status} label={APPROVAL[rec.approval_status]?.label}
        tone={APPROVAL[rec.approval_status]?.tone} />) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (rec) => (
      <Button size="sm" variant={rec.approval_status === 'pending' ? 'default' : 'outline'}
        onClick={() => buka(rec)} data-testid={`att-approval-open-${rec.id}`}>
        {rec.approval_status === 'pending' ? 'Periksa' : 'Lihat'}
      </Button>) },
  ];

  return (
    <PageLayout
      title="Persetujuan absen"
      subtitle="Periksa foto selfie dan lokasi absen karyawan, lalu setujui atau tolak."
      filters={(
        <>
          <SmartNativeSelect value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} searchable={false}
            className="h-9 w-56" aria-label="Status" data-testid="att-approval-status">
            <option value="pending">Menunggu pemeriksaan</option>
            <option value="approved">Disetujui</option>
            <option value="rejected">Ditolak</option>
            <option value="auto_approved">Otomatis</option>
            <option value="all">Semua</option>
          </SmartNativeSelect>
          <PeriodPicker value={period} onChange={setPeriod} testId="att-approval-period" />
          {/* Unduh & muat ulang di ujung kanan; di HP turun ke baris sendiri (tidak menimpa penyaring) */}
          <div className="ml-auto flex shrink-0 items-center gap-2">
          <TombolUnduh namaBerkas="persetujuan-absen" namaLembar="Persetujuan absen" baris={records} testId="att-approval-unduh"
            kolom={[
              { label: 'Kode karyawan', nilai: (r) => r.employee_code || '' },
              { label: 'Nama karyawan', nilai: (r) => r.employee_name || '' },
              { label: 'Departemen', nilai: (r) => r.department || '' },
              { label: 'Tanggal', nilai: (r) => fmtDate(r.date) },
              { label: 'Masuk', nilai: (r) => fmtTime(r.clock_in) },
              { label: 'Pulang', nilai: (r) => fmtTime(r.clock_out) },
              { label: 'Metode', nilai: (r) => METHOD[r.attendance_method] || 'Selfie' },
              { label: 'Lokasi', nilai: (r) => geoText(r) },
              { label: 'Terlambat (menit)', nilai: (r) => Number(r.late_minutes) || 0 },
              { label: 'Status', nilai: (r) => APPROVAL[r.approval_status]?.label || r.approval_status || '' },
              { label: 'Diperiksa oleh', nilai: (r) => r.approval_by_name || '' },
              { label: 'Catatan', nilai: (r) => r.approval_notes || '' },
            ]} />
          <Button variant="outline" size="icon" onClick={loadRecords} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
          </div>
        </>
      )}
      summary={msg && (
        <Notice tone={msg.tone} action={<Button size="sm" variant="outline" onClick={() => setMsg(null)}>Tutup</Button>}>
          {msg.text}
        </Notice>
      )}
      detail={selected && (
        <DetailPanel
          title={`${selected.employee_name || '-'} · ${fmtDate(selected.date)}`}
          description={`${selected.employee_code || '-'} · ${METHOD[selected.attendance_method] || 'Selfie'} · ${geoText(selected)}`}
          onClose={() => setSelected(null)}
          testId="att-approval-detail"
        >
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <SelfiePhoto url={selected.photo_selfie_url} label={`Selfie masuk · ${fmtTime(selected.clock_in)}`}
              testId="att-approval-photo-in" />
            <SelfiePhoto url={selected.photo_selfie_out_url} label={`Selfie pulang · ${fmtTime(selected.clock_out)}`}
              testId="att-approval-photo-out" />
            <div className="col-span-2 space-y-2 text-sm">
              <p className="flex items-center gap-1.5"><MapPin className="w-4 h-4 text-muted-foreground" /> {geoText(selected)}</p>
              {selected.clock_in_geo?.accuracy_m != null && (
                <p className="text-xs text-muted-foreground">Akurasi GPS ±{selected.clock_in_geo.accuracy_m} m</p>
              )}
              {selected.late_minutes > 0 && <p className="text-xs">Terlambat {selected.late_minutes} menit</p>}
              <div>
                <Label htmlFor="att-approval-notes">Catatan (wajib bila ditolak)</Label>
                <Textarea id="att-approval-notes" rows={3} className="mt-1" value={notes}
                  onChange={(e) => setNotes(e.target.value)} placeholder="Contoh: wajah tidak terlihat jelas"
                  data-testid="att-approval-notes" />
              </div>
              {selected.approval_status === 'pending' ? (
                <div className="flex flex-wrap gap-2">
                  <Button variant="destructive" onClick={() => decide(false)} disabled={busy} data-testid="att-approval-reject">
                    <XCircle className="w-4 h-4" /> Tolak
                  </Button>
                  <Button variant="success" onClick={() => decide(true)} disabled={busy} data-testid="att-approval-approve">
                    {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />} Setujui
                  </Button>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {APPROVAL[selected.approval_status]?.label || selected.approval_status}
                  {selected.approval_by_name ? ` oleh ${selected.approval_by_name}` : ''}
                  {selected.approval_notes ? ` — "${selected.approval_notes}"` : ''}
                </p>
              )}
            </div>
          </div>
        </DetailPanel>
      )}
      footer={records.length > 0 && <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />}
      testId="att-approval-page"
    >
      {loading ? (
        <p className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Memuat antrean absen…</p>
      ) : (
        <TabelData kolom={kolom} baris={paged} onKlikBaris={buka} testId="att-approval-table"
          kosong={<EmptyState icon={ClipboardCheck} title="Tidak ada absen untuk penyaring ini"
            description={statusFilter === 'pending' ? 'Semua absen sudah diperiksa.' : 'Ubah status atau periode.'} />} />
      )}
    </PageLayout>
  );
}

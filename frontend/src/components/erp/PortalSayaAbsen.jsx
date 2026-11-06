/**
 * PortalSayaAbsen — SATU layar absen di Portal Saya (menu "Absen Saya").
 *
 * Tahap 2 (2026-11-06):
 * · Cetakan PageLayout; tombol absen PALING ATAS (layar HP 390 px), jam server yang akan dicatat tampil.
 * · Lokasi GPS dibaca BARU saat tombol ditekan (maximumAge: 0) — dulu dibaca sekali saat halaman dibuka lalu
 *   dipakai ulang (buka halaman di kantor pagi, absen pulang dari rumah). Posisi basi / kurang akurat / di luar
 *   radius → pesan + tombol "Coba lagi". Server memeriksa ulang (utils/attendance_policy.check_gps_fix).
 * · Selfie HANYA dari kamera (getUserMedia, kamera depan). Tidak ada unggah dari galeri.
 * · Shift lewat tengah malam: record kemarin yang masih terbuka ditutup lewat tombol "Absen pulang".
 * · Riwayat 30 hari + "Ajukan koreksi absen" (diputus HR; tanggal yang sudah digaji jadi penyesuaian gaji).
 * · Menu "Kehadiran" lama digabung ke sini (satu menu absen).
 *
 * Identitas ditentukan server dari token (employee_id tidak dikirim ⇒ tidak bisa "titip absen").
 */
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import axios from 'axios';
import {
  LogIn, LogOut, Coffee, DoorOpen, MapPin, Camera, Loader2, RefreshCw, AlertCircle,
  CheckCircle2, Timer, Hourglass, XCircle, RotateCcw, CalendarClock, PencilLine,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from '@/components/ui/dialog';
import { Skeleton } from '@/components/ui/skeleton';
import { toast } from 'sonner';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;
const TZ = 'Asia/Jakarta';

const fmtTime = (v, seconds = false) => {
  if (!v) return '--:--';
  try {
    return new Date(v).toLocaleTimeString('id-ID', {
      hour: '2-digit', minute: '2-digit', ...(seconds ? { second: '2-digit' } : {}), timeZone: TZ,
    });
  } catch { return '--:--'; }
};
const fmtDay = (iso) => {
  try {
    return new Date(`${iso}T00:00:00+07:00`).toLocaleDateString('id-ID', {
      weekday: 'short', day: '2-digit', month: 'short', timeZone: TZ,
    });
  } catch { return iso; }
};
const fmtDur = (mins) => {
  const m = Math.max(0, Math.round(Number(mins) || 0));
  return m < 60 ? `${m} mnt` : `${Math.floor(m / 60)} j ${m % 60} mnt`;
};
const fmtMeter = (m) => (m == null ? '-' : (m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`));
const todayIso = () => new Date().toLocaleDateString('en-CA', { timeZone: TZ });
const daysAgoIso = (n) => new Date(Date.now() - n * 86400000).toLocaleDateString('en-CA', { timeZone: TZ });

/** Jarak hanya untuk PRATINJAU di layar — keputusan tetap di server. */
const distanceM = (a, b) => {
  if (!a || !b || a.lat == null || b.lat == null) return null;
  const R = 6371000, rad = (d) => (d * Math.PI) / 180;
  const dLat = rad(b.lat - a.lat), dLng = rad(b.lng - a.lng);
  const s = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
};

const STATUS_LABEL = { hadir: 'Hadir', izin: 'Izin', sakit: 'Sakit', cuti: 'Cuti', alpa: 'Alpa', alfa: 'Alpa', libur: 'Libur' };
const STATUS_TONE = { hadir: 'success', alpa: 'danger', alfa: 'danger', libur: 'muted' };
const CORR_LABEL = { pending: 'Koreksi menunggu HR', approved: 'Koreksi disetujui', rejected: 'Koreksi ditolak' };
const CORR_TONE = { pending: 'warning', approved: 'success', rejected: 'danger' };

/** Posisi GPS BARU (tidak memakai cache browser). */
const readFix = () => new Promise((resolve, reject) => {
  if (!navigator.geolocation) {
    reject(new Error('Perangkat/browser ini tidak mendukung lokasi GPS.'));
    return;
  }
  navigator.geolocation.getCurrentPosition(
    (p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy, gps_at: p.timestamp }),
    (err) => reject(new Error(err.code === 1
      ? 'Izin lokasi ditolak. Aktifkan izin lokasi untuk situs ini, lalu tekan Coba lagi.'
      : 'Lokasi belum terbaca. Pastikan GPS menyala, lalu tekan Coba lagi.')),
    { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 },
  );
});

export default function PortalSayaAbsen({ token, headers: headersProp }) {
  const headers = useMemo(() => headersProp || { Authorization: `Bearer ${token}` }, [headersProp, token]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [status, setStatus] = useState(null);
  const [office, setOffice] = useState(null);
  const [geo, setGeo] = useState(null);
  const [geoMsg, setGeoMsg] = useState('');
  const [actionError, setActionError] = useState(null);   // { text, retry }
  const [clockOffset, setClockOffset] = useState(0);
  const [tick, setTick] = useState(Date.now());
  const [history, setHistory] = useState([]);
  const [corrections, setCorrections] = useState([]);
  const [izinOpen, setIzinOpen] = useState(false);
  const [izinReason, setIzinReason] = useState('');
  const [camOpen, setCamOpen] = useState(false);
  const [camAction, setCamAction] = useState('in');
  const [camError, setCamError] = useState('');
  const [shot, setShot] = useState('');
  const [fix, setFix] = useState(null);
  const [corrOpen, setCorrOpen] = useState(null);         // tanggal yang dikoreksi
  const [corrForm, setCorrForm] = useState({ clock_in: '', clock_out: '', reason: '' });
  const videoRef = useRef(null);
  const streamRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const [s, o, h, c] = await Promise.all([
        axios.get(`${API}/api/rahaza/attendance/my-status`, { headers }),
        axios.get(`${API}/api/rahaza/attendance/office-location`, { headers }).catch(() => ({ data: null })),
        axios.get(`${API}/api/rahaza/self/attendance`, { headers, params: { from: daysAgoIso(30), to: todayIso() } })
          .catch(() => ({ data: { records: [] } })),
        axios.get(`${API}/api/rahaza/attendance/corrections/my`, { headers }).catch(() => ({ data: { items: [] } })),
      ]);
      setStatus(s.data || {});
      setOffice(o.data || null);
      setHistory(h.data?.records || []);
      setCorrections(c.data?.items || []);
      if (s.data?.server_time) setClockOffset(new Date(s.data.server_time).getTime() - Date.now());
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Gagal memuat status kehadiran');
    } finally { setLoading(false); }
  }, [headers]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { const t = setInterval(() => setTick(Date.now()), 1000); return () => clearInterval(t); }, []);

  // Pratinjau lokasi untuk baris status (tombol absen tetap membaca lokasi baru saat ditekan).
  const previewLocation = useCallback(async () => {
    setGeoMsg('');
    try { setGeo(await readFix()); } catch (e) { setGeoMsg(e.message); }
  }, []);
  useEffect(() => { previewLocation(); }, [previewLocation]);

  const stopCam = useCallback(() => {
    try { streamRef.current?.getTracks?.().forEach((t) => t.stop()); } catch { /* noop */ }
    streamRef.current = null;
  }, []);
  useEffect(() => () => stopCam(), [stopCam]);

  const startCam = useCallback(async () => {
    setCamError('');
    stopCam();
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('tidak didukung');
      const s = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }, audio: false });
      streamRef.current = s;
      setTimeout(() => { if (videoRef.current) videoRef.current.srcObject = s; }, 120);
    } catch {
      setCamError('Kamera tidak bisa dibuka. Izinkan akses kamera untuk situs ini di pengaturan browser, '
        + 'tutup aplikasi lain yang memakai kamera, lalu tekan Coba lagi. Foto dari galeri tidak diterima.');
    }
  }, [stopCam]);

  const closeCam = () => { stopCam(); setCamOpen(false); setShot(''); setCamError(''); };

  const capture = () => {
    const v = videoRef.current;
    if (!v || !v.videoWidth) { setCamError('Kamera belum siap. Tunggu sebentar lalu coba lagi.'); return; }
    const c = document.createElement('canvas');
    c.width = 640;
    c.height = Math.round((v.videoHeight / v.videoWidth) * 640) || 480;
    c.getContext('2d').drawImage(v, 0, 0, c.width, c.height);
    setShot(c.toDataURL('image/jpeg', 0.8).split(',')[1] || '');
    setCamError('');
  };

  const emp = status?.employee || {};
  const today = status?.today || null;
  const openPrev = status?.open_previous || null;
  const active = status?.active_session || null;
  const sessions = today?.sessions || [];
  const pendingPermit = status?.pending_permit
    || sessions.find((s) => s.kind === 'izin' && (s.approval_status || 'pending') === 'pending');
  const hasIn = Boolean(today?.clock_in);
  const hasOut = Boolean(today?.clock_out);
  const fullDayLeave = Boolean(today?.leave_request_id && !today?.half_day);
  const late = Number(today?.late_minutes ?? status?.late_minutes ?? 0);
  const requireGeo = office?.require_geofence !== false;
  const requireSelfie = office?.require_selfie !== false;
  const officeSet = Boolean(office?.configured);
  const radius = Number(office?.geofence_radius_m || 300);
  const maxAcc = Number(office?.gps_max_accuracy_m || 100);
  const dist = officeSet && geo ? distanceM(geo, { lat: office.lat, lng: office.lng }) : null;
  const serverNow = new Date(tick + clockOffset);
  const clockMode = openPrev ? 'out-prev' : (!hasIn ? 'in' : (!hasOut ? 'out' : 'done'));

  /** Baca lokasi BARU dan periksa (pratinjau) sebelum kamera dibuka / absen dikirim. */
  const checkLocation = async () => {
    if (!requireGeo) return null;
    if (!officeSet) throw new Error('Lokasi kantor belum diatur Admin HR (menu Absensi › Absen otomatis).');
    const f = await readFix();
    setGeo(f);
    if (f.accuracy > maxAcc) {
      throw new Error(`Lokasi GPS kurang akurat (±${Math.round(f.accuracy)} m, batas ${maxAcc} m). `
        + 'Pindah ke dekat jendela atau tempat terbuka, lalu tekan Coba lagi.');
    }
    const d = distanceM(f, { lat: office.lat, lng: office.lng });
    if (d != null && d > radius) {
      throw new Error(`Anda ${fmtMeter(d)} dari ${office?.name || 'kantor'} (batas ${fmtMeter(radius)}). `
        + 'Absen hanya bisa di area kantor. Bila Anda sudah di kantor, tekan Coba lagi.');
    }
    return f;
  };

  const send = async (action, photo, f0) => {
    setBusy('send');
    try {
      // Lokasi dibaca ulang bila pembacaan saat tombol ditekan sudah lebih dari 30 detik (mis. lama memotret).
      const f = requireGeo && (!f0 || Date.now() - f0.gps_at > 30000) ? await checkLocation() : f0;
      const url = action === 'in'
        ? `${API}/api/rahaza/attendance/selfie/clock-in`
        : `${API}/api/rahaza/attendance/selfie/clock-out`;
      const r = await axios.post(url, {
        lat: f?.lat ?? null, lng: f?.lng ?? null, accuracy: f?.accuracy ?? null,
        gps_at: f?.gps_at ?? null, gps_sent_at: Date.now(), photo_base64: photo,
      }, { headers });
      toast.success(r.data?.message || (action === 'in' ? 'Absen masuk tercatat' : 'Absen pulang tercatat'));
      setActionError(null);
      closeCam();
      load();
    } catch (e) {
      const msg = e.response?.data?.detail || e.message || 'Gagal mencatat absen';
      setActionError({ text: msg, retry: () => startClock(action) });
      closeCam();
    } finally { setBusy(''); }
  };

  const startClock = async (action) => {
    setActionError(null);
    setBusy('gps');
    let f = null;
    try {
      f = await checkLocation();
    } catch (e) {
      setActionError({ text: e.message, retry: () => startClock(action) });
      setBusy('');
      return;
    }
    setBusy('');
    setFix(f);
    setCamAction(action);
    if (!requireSelfie) { send(action, '', f); return; }
    setShot('');
    setCamOpen(true);
    startCam();
  };

  const startSession = async (kind, reason = '') => {
    setBusy(`start-${kind}`);
    try {
      const r = await axios.post(`${API}/api/rahaza/attendance/sessions/start`, {
        kind, reason, lat: geo?.lat ?? null, lng: geo?.lng ?? null,
      }, { headers });
      toast.success(r.data?.message || (kind === 'izin' ? 'Pengajuan izin terkirim' : 'Istirahat dimulai'));
      setIzinOpen(false); setIzinReason('');
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Gagal memulai sesi'); } finally { setBusy(''); }
  };

  const endSession = async () => {
    setBusy('end');
    try {
      const r = await axios.post(`${API}/api/rahaza/attendance/sessions/end`, {
        lat: geo?.lat ?? null, lng: geo?.lng ?? null,
      }, { headers });
      toast.success(`Kembali kerja — tercatat ${fmtDur(r.data?.minutes)}`);
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Gagal menutup sesi'); } finally { setBusy(''); }
  };

  const cancelPermit = async (id) => {
    setBusy('cancel');
    try {
      await axios.post(`${API}/api/rahaza/attendance/permits/${id}/cancel`, {}, { headers });
      toast.success('Pengajuan izin dibatalkan');
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Gagal membatalkan pengajuan'); } finally { setBusy(''); }
  };

  const openCorrection = (rec) => {
    setCorrOpen(rec.date);
    setCorrForm({ clock_in: rec.clock_in ? fmtTime(rec.clock_in).replace('.', ':') : '',
                  clock_out: rec.clock_out ? fmtTime(rec.clock_out).replace('.', ':') : '', reason: '' });
  };

  const submitCorrection = async () => {
    setBusy('corr');
    try {
      await axios.post(`${API}/api/rahaza/attendance/corrections`, { date: corrOpen, ...corrForm }, { headers });
      toast.success('Pengajuan koreksi terkirim ke HR');
      setCorrOpen(null);
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Gagal mengirim koreksi'); } finally { setBusy(''); }
  };

  const corrByDate = useMemo(() => {
    const m = {};
    corrections.forEach((c) => { if (!m[c.date] || c.status === 'pending') m[c.date] = c; });
    return m;
  }, [corrections]);

  // ── Render ─────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="space-y-4" data-testid="portal-absen-loading">
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  if (status && status.linked === false) {
    return (
      <PageLayout title="Absen saya" subtitle="Absen masuk dan pulang dengan selfie di area kantor."
        testId="portal-absen-unlinked">
        <Notice tone="warning" icon={AlertCircle} title="Akun belum ditautkan ke data karyawan">
          {status.message || 'Minta Admin HR menautkan akun Anda lewat menu Data Karyawan › Tautkan akun.'}
        </Notice>
      </PageLayout>
    );
  }

  const locLine = !requireGeo ? 'Lokasi tidak diwajibkan'
    : !officeSet ? 'Lokasi kantor belum diatur'
      : !geo ? (geoMsg || 'Membaca lokasi…')
        : dist <= radius ? `Di area kantor (${fmtMeter(dist)}, akurasi ±${Math.round(geo.accuracy)} m)`
          : `Di luar area kantor (${fmtMeter(dist)} dari ${office?.name || 'kantor'})`;
  const locTone = !geo || !officeSet ? 'text-muted-foreground'
    : dist <= radius ? 'text-[hsl(var(--success))]' : 'text-[hsl(var(--destructive))]';
  const mainLabel = {
    in: 'Absen masuk', out: 'Absen pulang', 'out-prev': `Absen pulang shift ${fmtDay(openPrev?.date)}`,
    done: 'Absen hari ini selesai',
  }[clockMode];
  const MainIcon = clockMode === 'in' ? LogIn : (clockMode === 'done' ? CheckCircle2 : LogOut);
  const outBlocked = Boolean(active) || Boolean(pendingPermit);

  return (
    <PageLayout
      title="Absen saya"
      subtitle={`${emp.name || '-'} · ${emp.employee_code || '-'}${emp.job_title ? ` · ${emp.job_title}` : ''}`}
      tools={(
        <Button variant="outline" size="icon" onClick={load} title="Muat ulang" aria-label="Muat ulang"
          data-testid="absen-refresh">
          <RefreshCw className="w-4 h-4" />
        </Button>
      )}
      testId="portal-absen-page"
    >
      {/* Tombol absen PALING ATAS + jam server */}
      <GlassCard className="p-4 space-y-3" data-testid="absen-action-card">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-xs text-muted-foreground flex items-center gap-1">
              <CalendarClock className="w-3.5 h-3.5" />
              {serverNow.toLocaleDateString('id-ID', { weekday: 'long', day: '2-digit', month: 'long', timeZone: TZ })}
            </p>
            <p className="text-3xl font-bold tabular-nums leading-tight" data-testid="absen-server-time"
              title="Jam server — jam inilah yang dicatat saat tombol ditekan">
              {fmtTime(serverNow, true)} <span className="text-sm font-medium text-muted-foreground">WIB</span>
            </p>
            <p className="text-xs text-muted-foreground">Jam server yang akan dicatat</p>
          </div>
          {today?.status && (
            <StatusBadge status={today.status} label={STATUS_LABEL[today.status] || today.status}
              tone={STATUS_TONE[today.status] || 'info'} />
          )}
        </div>

        <Button size="lg" className="w-full"
          variant={clockMode === 'in' ? 'default' : (clockMode === 'done' ? 'outline' : 'destructive')}
          onClick={() => startClock(clockMode === 'in' ? 'in' : 'out')}
          disabled={clockMode === 'done' || Boolean(busy) || (clockMode === 'in' && fullDayLeave)
            || (clockMode !== 'in' && outBlocked)}
          data-testid={clockMode === 'in' ? 'absen-btn-clock-in' : 'absen-btn-clock-out'}>
          {busy === 'gps' || busy === 'send' ? <Loader2 className="w-5 h-5 animate-spin" /> : <MainIcon className="w-5 h-5" />}
          {busy === 'gps' ? 'Membaca lokasi…' : mainLabel}
        </Button>

        <div className="flex items-center justify-between gap-2 text-sm" data-testid="absen-geo-status">
          <span className={`flex items-center gap-1.5 min-w-0 ${locTone}`}>
            <MapPin className="w-4 h-4 shrink-0" /> <span className="truncate">{locLine}</span>
          </span>
          {requireGeo && officeSet && (!geo || dist > radius) && (
            <Button size="sm" variant="outline" onClick={previewLocation} data-testid="absen-retry-geo">
              <RotateCcw className="w-3.5 h-3.5" /> Coba lagi
            </Button>
          )}
        </div>

        {actionError && (
          <Notice tone="danger" icon={AlertCircle} testId="absen-block-reason"
            action={actionError.retry && (
              <Button size="sm" variant="outline" onClick={actionError.retry} data-testid="absen-retry-action">
                <RotateCcw className="w-3.5 h-3.5" /> Coba lagi
              </Button>
            )}>
            {actionError.text}
          </Notice>
        )}
        {clockMode === 'in' && fullDayLeave && (
          <Notice tone="warning" icon={AlertCircle}>
            Hari ini Anda tercatat {STATUS_LABEL[today.status] || today.status} yang sudah disetujui.
            Bila Anda tetap masuk kerja, minta HR membatalkan pengajuan itu dulu.
          </Notice>
        )}
        {clockMode !== 'in' && clockMode !== 'done' && outBlocked && (
          <p className="text-xs text-muted-foreground">Tutup sesi istirahat/izin dulu sebelum absen pulang.</p>
        )}

        {hasIn && !hasOut && (
          <div className="grid grid-cols-2 gap-2">
            {active ? (
              <Button className="col-span-2" onClick={endSession} disabled={busy === 'end'} data-testid="absen-session-end">
                {busy === 'end' ? <Loader2 className="w-4 h-4 animate-spin" /> : <LogIn className="w-4 h-4" />}
                Kembali kerja
              </Button>
            ) : (
              <>
                <Button variant="outline" onClick={() => startSession('istirahat')}
                  disabled={Boolean(pendingPermit) || Boolean(busy)} data-testid="absen-btn-break-start">
                  {busy === 'start-istirahat' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Coffee className="w-4 h-4" />}
                  Istirahat
                </Button>
                <Button variant="outline" onClick={() => setIzinOpen(true)}
                  disabled={Boolean(pendingPermit) || Boolean(busy)} data-testid="absen-btn-permit-start">
                  <DoorOpen className="w-4 h-4" /> Izin keluar
                </Button>
              </>
            )}
          </div>
        )}
      </GlassCard>

      {/* Status hari ini */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2" data-testid="absen-today-status">
        <StatTile label="Masuk" value={fmtTime(today?.clock_in)} testId="absen-clock-in-time"
          sub={late > 0 ? `Terlambat ${fmtDur(late)}` : (hasIn ? 'Tepat waktu' : undefined)}
          subTone={late > 0 ? 'warning' : 'success'} />
        <StatTile label="Pulang" value={fmtTime(today?.clock_out)} testId="absen-clock-out-time" />
        <StatTile label="Istirahat" value={fmtDur(status?.break_minutes)} testId="absen-break-total" />
        <StatTile label="Izin keluar" value={fmtDur(status?.permit_minutes)} testId="absen-permit-total" />
      </div>

      {today?.approval_status === 'pending' && (
        <Notice tone="info" icon={Hourglass} testId="absen-hr-review-pending">
          Selfie absen hari ini menunggu pemeriksaan HR. Tetap dihitung hadir sampai HR memutuskan.
        </Notice>
      )}
      {pendingPermit && (
        <Notice tone="warning" icon={Hourglass} title="Izin keluar menunggu persetujuan atasan/HR"
          testId="absen-pending-permit"
          action={(
            <Button size="sm" variant="outline" onClick={() => cancelPermit(pendingPermit.id)}
              disabled={busy === 'cancel'} data-testid="absen-permit-cancel-pending">
              <XCircle className="w-4 h-4" /> Batalkan
            </Button>
          )}>
          &quot;{pendingPermit.reason}&quot; · diajukan {fmtTime(pendingPermit.requested_at)}. Anda belum dianggap keluar.
        </Notice>
      )}
      {active && (
        <Notice tone="info" icon={Timer} testId="absen-active-session"
          title={active.kind === 'izin' ? 'Sedang izin keluar (disetujui)' : 'Sedang istirahat'}>
          Keluar {fmtTime(active.out_at)}{active.reason ? ` · "${active.reason}"` : ''}
        </Notice>
      )}

      {/* Riwayat 30 hari + koreksi */}
      <GlassCard className="p-4 space-y-3" data-testid="absen-history">
        <div>
          <p className="text-base font-semibold">Riwayat 30 hari</p>
          <p className="text-xs text-muted-foreground">Jam salah atau lupa absen? Tekan Ajukan koreksi pada tanggalnya.</p>
        </div>
        {history.length === 0 ? (
          <EmptyState icon={CalendarClock} title="Belum ada catatan absen"
            description="Catatan muncul setelah Anda absen masuk." className="py-6" />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Tanggal</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Masuk</TableHead>
                <TableHead>Pulang</TableHead>
                <TableHead className="text-right">Koreksi</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {history.map((r) => {
                const c = corrByDate[r.date];
                return (
                  <TableRow key={r.id || r.date} data-testid={`absen-history-${r.date}`}>
                    <TableCell className="whitespace-nowrap">{fmtDay(r.date)}</TableCell>
                    <TableCell>
                      <StatusBadge status={r.status} label={`${STATUS_LABEL[r.status] || r.status || '-'}${r.half_day ? ' ½' : ''}`}
                        tone={STATUS_TONE[r.status] || 'info'} />
                    </TableCell>
                    <TableCell className="tabular-nums">{fmtTime(r.clock_in)}</TableCell>
                    <TableCell className="tabular-nums">{fmtTime(r.clock_out)}</TableCell>
                    <TableCell className="text-right">
                      {c && (
                        <StatusBadge status={c.status} label={CORR_LABEL[c.status] || c.status} tone={CORR_TONE[c.status]} />
                      )}
                      {(!c || c.status === 'rejected') && (
                        <Button size="sm" variant="link" onClick={() => openCorrection(r)} data-testid={`absen-correct-${r.date}`}>
                          <PencilLine className="w-3.5 h-3.5" /> Ajukan koreksi
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
        <Button size="sm" variant="outline" onClick={() => openCorrection({ date: daysAgoIso(1) })}
          data-testid="absen-correct-other">
          <PencilLine className="w-3.5 h-3.5" /> Ajukan koreksi absen tanggal lain
        </Button>
      </GlassCard>

      {/* Dialog alasan izin keluar */}
      <Dialog open={izinOpen} onOpenChange={(v) => { setIzinOpen(v); if (!v) setIzinReason(''); }}>
        <DialogContent data-testid="absen-permit-dialog">
          <DialogHeader>
            <DialogTitle>Ajukan izin keluar</DialogTitle>
            <DialogDescription>
              Alasan wajib. Anda baru dianggap keluar setelah disetujui atasan/HR, dan durasinya tidak dihitung jam kerja.
            </DialogDescription>
          </DialogHeader>
          <div>
            <Label htmlFor="izin-reason">Alasan</Label>
            <Textarea id="izin-reason" rows={3} className="mt-1" placeholder="Contoh: ke klinik, urusan keluarga"
              value={izinReason} onChange={(e) => setIzinReason(e.target.value)} data-testid="absen-permit-reason" />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIzinOpen(false)} data-testid="absen-permit-cancel">Batal</Button>
            <Button onClick={() => startSession('izin', izinReason.trim())}
              disabled={!izinReason.trim() || busy === 'start-izin'} data-testid="absen-permit-confirm">
              {busy === 'start-izin' && <Loader2 className="w-4 h-4 animate-spin" />} Kirim pengajuan
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dialog kamera — kamera depan saja, tanpa unggah dari galeri */}
      <Dialog open={camOpen} onOpenChange={(v) => { if (!v) closeCam(); }}>
        <DialogContent data-testid="absen-camera-dialog">
          <DialogHeader>
            <DialogTitle>{camAction === 'in' ? 'Absen masuk' : 'Absen pulang'} — selfie</DialogTitle>
            <DialogDescription>Foto langsung dari kamera depan sebagai bukti kehadiran; diperiksa HR.</DialogDescription>
          </DialogHeader>
          <div className="rounded-[var(--radius-md)] overflow-hidden bg-muted aspect-[3/4] sm:aspect-video flex items-center justify-center">
            {shot
              ? <img src={`data:image/jpeg;base64,${shot}`} alt="Pratinjau selfie" className="w-full h-full object-cover"
                data-testid="absen-selfie-preview" />
              : <video ref={videoRef} autoPlay playsInline muted className="w-full h-full object-cover"
                data-testid="absen-camera-video" />}
          </div>
          {camError && (
            <Notice tone="danger" icon={Camera} testId="absen-camera-error"
              action={(
                <Button size="sm" variant="outline" onClick={startCam} data-testid="absen-camera-retry">
                  <RotateCcw className="w-3.5 h-3.5" /> Coba lagi
                </Button>
              )}>
              {camError}
            </Notice>
          )}
          <DialogFooter className="gap-2">
            {!shot ? (
              <Button variant="outline" onClick={capture} disabled={Boolean(camError)} data-testid="absen-camera-capture">
                <Camera className="w-4 h-4" /> Ambil foto
              </Button>
            ) : (
              <Button variant="outline" onClick={() => setShot('')} data-testid="absen-camera-retake">
                <RotateCcw className="w-4 h-4" /> Ulangi
              </Button>
            )}
            <Button onClick={() => send(camAction, shot, fix)} disabled={!shot || Boolean(busy)} data-testid="absen-camera-confirm">
              {busy === 'send' ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
              {camAction === 'in' ? 'Kirim absen masuk' : 'Kirim absen pulang'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dialog koreksi absen (formulir pendek) */}
      <Dialog open={Boolean(corrOpen)} onOpenChange={(v) => { if (!v) setCorrOpen(null); }}>
        <DialogContent data-testid="absen-correction-dialog">
          <DialogHeader>
            <DialogTitle>Ajukan koreksi absen</DialogTitle>
            <DialogDescription>
              Isi jam yang benar. HR memeriksa dulu; bila tanggal itu sudah digaji, selisihnya dibayar di gaji berikutnya.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label htmlFor="corr-date">Tanggal</Label>
              <GlassInput id="corr-date" type="date" className="mt-1" value={corrOpen || ''} max={todayIso()}
                onChange={(e) => setCorrOpen(e.target.value)} data-testid="absen-correction-date" />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label htmlFor="corr-in">Jam masuk</Label>
                <GlassInput id="corr-in" type="time" className="mt-1" value={corrForm.clock_in}
                  onChange={(e) => setCorrForm((f) => ({ ...f, clock_in: e.target.value }))} data-testid="absen-correction-in" />
              </div>
              <div>
                <Label htmlFor="corr-out">Jam pulang</Label>
                <GlassInput id="corr-out" type="time" className="mt-1" value={corrForm.clock_out}
                  onChange={(e) => setCorrForm((f) => ({ ...f, clock_out: e.target.value }))} data-testid="absen-correction-out" />
              </div>
            </div>
            <div>
              <Label htmlFor="corr-reason">Alasan</Label>
              <Textarea id="corr-reason" rows={2} className="mt-1" placeholder="Contoh: lupa absen pulang, HP mati"
                value={corrForm.reason} onChange={(e) => setCorrForm((f) => ({ ...f, reason: e.target.value }))}
                data-testid="absen-correction-reason" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCorrOpen(null)}>Batal</Button>
            <Button onClick={submitCorrection}
              disabled={busy === 'corr' || !corrForm.reason.trim() || !(corrForm.clock_in || corrForm.clock_out)}
              data-testid="absen-correction-submit">
              {busy === 'corr' && <Loader2 className="w-4 h-4 animate-spin" />} Kirim ke HR
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageLayout>
  );
}

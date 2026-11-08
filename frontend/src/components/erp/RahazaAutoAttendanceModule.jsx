/**
 * RahazaAutoAttendanceModule — absen otomatis karyawan (Portal SDM › Absensi).
 *
 * Standar UI/UX v2 (8 Nov 2026): dulu satu tab hub berisi 4 tab buatan sendiri (tab di dalam tab, ikon emoji,
 * judul ganda "PORTAL SDM › KEHADIRAN"). Sekarang keempat bagian dinaikkan jadi tab hub "Absensi"
 * (`hubs/HRAttendanceHub.jsx`) dan masing-masing memakai cetakan PageLayout:
 *   • AbsenOtomatisHariIni     — absen otomatis hari ini (dulu "Live Feed": kartu berulang → tabel + unduh)
 *   • MesinSidikJari           — mesin ZKTeco/Fingerspot + impor file ekspor (form → popup standar)
 *   • BiometrikHP              — sidik jari / Face ID HP karyawan (tabel + unduh)
 *   • PengaturanAbsenOtomatis  — zona kantor, kebijakan, GPS, ambang wajah (ringkasan + form popup)
 * Fitur, panggilan API, dan data yang dikirim tidak berubah.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import axios from 'axios';
import {
  AlertTriangle, Fingerprint, LocateFixed, MoreHorizontal, Pencil, Plus, RefreshCw, Trash2, Upload, Wifi,
} from 'lucide-react';
import { toast } from 'sonner';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { todayWIB, parseServerTime } from '@/lib/waktu';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Slider } from '@/components/ui/slider';
import { GlassCard } from '@/components/ui/glass';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { BarisDetail } from '@/components/ui/detail-popup';
import { formatTanggalID } from '@/components/ui/date-picker';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';
import FingerprintImportPanel from './hr/FingerprintImportPanel';

const BACKEND = process.env.REACT_APP_BACKEND_URL;
const TZ = 'Asia/Jakarta';

const useHeaders = (token) => useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

function Memuat({ teks = 'Memuat…' }) {
  return <p className="py-6 text-center text-sm text-muted-foreground">{teks}</p>;
}

function MuatUlang({ onClick, memuat }) {
  return (
    <Button variant="outline" size="icon" onClick={onClick} disabled={memuat} title="Muat ulang" aria-label="Muat ulang">
      <RefreshCw className={memuat ? 'animate-spin' : ''} />
    </Button>
  );
}

// Tanggal/jam dari server: tanpa zona = UTC (lihat parseServerTime). Ditampilkan dalam WIB.
const fmtTanggal = (v) => {
  const d = parseServerTime(v);
  if (!d) return '—';
  try { return d.toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric', timeZone: TZ }); } catch { return '—'; }
};
const fmtWaktu = (v) => {
  const d = parseServerTime(v);
  if (!d) return '—';
  try { return d.toLocaleString('id-ID', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: TZ }); } catch { return '—'; }
};
const fmtJam = (v) => {
  const d = parseServerTime(v);
  if (!d) return '—';
  try { return d.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', timeZone: TZ }); } catch { return '—'; }
};

// ─── Pengaturan absen otomatis ────────────────────────────────────────────────
// FASE 16 — dua bug nyata diperbaiki di sini (tetap berlaku):
//  1. Kolom Latitude/Longitude MEMBACA `office_lat`/`office_lng` tapi dulu MENULIS `lat`/`lng`.
//  2. Tombol "Pakai lokasi saya sekarang" (navigator.geolocation) + tautan Google Maps.
// Ditambah: sakelar KEBIJAKAN WAJIB (selfie & lokasi) sesuai keputusan user.
const yaTidak = (v) => (v !== false ? 'Ya' : 'Tidak');

export function PengaturanAbsenOtomatis({ token }) {
  const headers = useHeaders(token);
  const [config, setConfig] = useState(null);
  const [gagal, setGagal] = useState('');
  const [form, setForm] = useState(null);       // null = popup tertutup
  const [saving, setSaving] = useState(false);
  const [locating, setLocating] = useState(false);
  const [lokasiMsg, setLokasiMsg] = useState(null);
  const [galat, setGalat] = useState('');

  const load = useCallback(async () => {
    setGagal('');
    try {
      const r = await axios.get(`${BACKEND}/api/rahaza/attendance/auto-config`, { headers });
      setConfig(r.data);
    } catch (e) { setGagal(e.response?.data?.detail || 'Pengaturan absen otomatis gagal dimuat.'); }
  }, [headers]);

  useEffect(() => { load(); }, [load]);

  const setField = (patch) => setForm((f) => ({ ...f, ...patch }));
  const buka = () => { setForm({ ...config }); setGalat(''); setLokasiMsg(null); };

  const useMyLocation = () => {
    if (!navigator.geolocation) {
      setLokasiMsg({ tone: 'danger', text: 'Peramban ini tidak bisa membaca lokasi.' });
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (p) => {
        setField({
          office_lat: Number(p.coords.latitude.toFixed(6)),
          office_lng: Number(p.coords.longitude.toFixed(6)),
        });
        setLokasiMsg({ tone: 'success', text: `Koordinat terisi dari lokasi Anda (akurasi ±${Math.round(p.coords.accuracy)} m). Jangan lupa simpan.` });
        setLocating(false);
      },
      (err) => {
        setLokasiMsg({ tone: 'danger', text: `Gagal membaca lokasi: ${err.message}. Isi manual dari Google Maps.` });
        setLocating(false);
      },
      { enableHighAccuracy: true, timeout: 10000 },
    );
  };

  const save = async () => {
    setSaving(true); setGalat('');
    try {
      await axios.put(`${BACKEND}/api/rahaza/attendance/auto-config`, {
        office_name: form.office_name,
        geofence_radius_m: form.geofence_radius_m,
        office_lat: form.office_lat,
        office_lng: form.office_lng,
        require_selfie: form.require_selfie !== false,
        require_geofence: form.require_geofence !== false,
        face_match_threshold: form.face_match_threshold,
        // Tahap 2 (2026-11-06): kesegaran & akurasi GPS saat tombol ditekan, jendela absen pulang lewat tengah malam
        gps_max_age_s: form.gps_max_age_s,
        gps_max_accuracy_m: form.gps_max_accuracy_m,
        clock_out_window_hours: form.clock_out_window_hours,
      }, { headers });
      toast.success('Pengaturan absen otomatis disimpan.');
      setForm(null);
      await load();
    } catch (e) {
      setGalat(e.response?.data?.detail || 'Gagal menyimpan');
    } finally { setSaving(false); }
  };

  const c = config || {};
  const belumDiatur = c.office_lat == null || c.office_lng == null;
  const peta = (lat, lng) => `https://www.google.com/maps?q=${lat},${lng}`;
  const f = form || {};

  return (
    <PageLayout testId="attendance-config-tab" title="Pengaturan absen otomatis"
      subtitle="Zona kantor, kebijakan selfie dan lokasi, serta ambang kecocokan wajah untuk absen lewat HP."
      actions={config && <Button onClick={buka} data-testid="cfg-edit"><Pencil />Ubah pengaturan</Button>}
      summary={<>
        {gagal && <Notice tone="danger">{gagal}</Notice>}
        {config && belumDiatur && c.require_geofence !== false && (
          <Notice tone="warning" icon={AlertTriangle} testId="attendance-config-warning"
            title="Koordinat kantor belum diisi, padahal lokasi diwajibkan">
            Selama kosong, karyawan tidak bisa absen (mereka melihat pesan &quot;Lokasi kantor belum diatur&quot;).
            Buka Ubah pengaturan lalu tekan &quot;Pakai lokasi saya sekarang&quot; saat Anda di kantor.
          </Notice>
        )}
      </>}>
      {!config && !gagal ? <Memuat /> : config && (
        <div className="grid gap-4 lg:grid-cols-2">
          <GlassCard className="p-4" hover={false}>
            <p className="text-base font-semibold text-foreground">Zona kantor</p>
            <dl className="mt-2 divide-y divide-[var(--glass-border)]">
              <BarisDetail label="Nama kantor">{c.office_name || '—'}</BarisDetail>
              <BarisDetail label="Koordinat">
                {belumDiatur ? <span className="text-muted-foreground">Belum diisi</span> : (
                  <span>
                    <span className="tabular-nums">{c.office_lat}, {c.office_lng}</span>{' · '}
                    <a className="text-primary underline-offset-4 hover:underline" target="_blank" rel="noreferrer"
                      href={peta(c.office_lat, c.office_lng)}>Lihat di Google Maps</a>
                  </span>
                )}
              </BarisDetail>
              <BarisDetail label="Radius">{c.geofence_radius_m ?? 300} meter</BarisDetail>
              <BarisDetail label="Umur lokasi maks.">{c.gps_max_age_s ?? 60} detik</BarisDetail>
              <BarisDetail label="Akurasi GPS terburuk">{c.gps_max_accuracy_m ?? 100} meter</BarisDetail>
              <BarisDetail label="Jendela absen pulang">{c.clock_out_window_hours ?? 6} jam sesudah jam pulang shift</BarisDetail>
            </dl>
          </GlassCard>
          <GlassCard className="p-4" hover={false}>
            <p className="text-base font-semibold text-foreground">Kebijakan absen</p>
            <dl className="mt-2 divide-y divide-[var(--glass-border)]">
              <BarisDetail label="Selfie wajib">{yaTidak(c.require_selfie)}
                <span className="block text-xs text-muted-foreground">Absen tanpa foto ditolak. Foto disimpan sebagai bukti untuk HR.</span>
              </BarisDetail>
              <BarisDetail label="Lokasi wajib">{yaTidak(c.require_geofence)}
                <span className="block text-xs text-muted-foreground">Absen di luar radius kantor ditolak.</span>
              </BarisDetail>
              <BarisDetail label="Kecocokan wajah min.">{Math.round((c.face_match_threshold || 0.65) * 100)}%
                <span className="block text-xs text-muted-foreground">Selfie di bawah angka ini masuk antrean Persetujuan absen. Saran: 60–70%.</span>
              </BarisDetail>
            </dl>
          </GlassCard>
        </div>
      )}

      <FormPopup open={form !== null} onClose={() => setForm(null)} ukuran="panjang" onSimpan={save} menyimpan={saving}
        judul="Ubah pengaturan absen otomatis" keterangan="Berlaku untuk semua karyawan yang absen lewat HP."
        labelSimpan="Simpan pengaturan" galat={galat} testId="cfg-form">
        <p className="text-base font-semibold text-foreground">Zona kantor</p>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Nama kantor" htmlFor="cfg-office-name">
            <Input id="cfg-office-name" data-testid="cfg-office-name" value={f.office_name || ''}
              onChange={(e) => setField({ office_name: e.target.value })} />
          </Isian>
          <Isian label="Radius (meter)" htmlFor="cfg-radius">
            <Input id="cfg-radius" data-testid="cfg-radius" type="number" value={f.geofence_radius_m ?? 300} min={10} max={20000}
              onChange={(e) => setField({ geofence_radius_m: parseInt(e.target.value, 10) })} />
          </Isian>
          <Isian label="Garis lintang kantor" htmlFor="cfg-lat">
            <Input id="cfg-lat" data-testid="cfg-lat" type="number" step="any" value={f.office_lat ?? ''} placeholder="-6.2088"
              onChange={(e) => setField({ office_lat: e.target.value === '' ? null : parseFloat(e.target.value) })} />
          </Isian>
          <Isian label="Garis bujur kantor" htmlFor="cfg-lng">
            <Input id="cfg-lng" data-testid="cfg-lng" type="number" step="any" value={f.office_lng ?? ''} placeholder="106.8456"
              onChange={(e) => setField({ office_lng: e.target.value === '' ? null : parseFloat(e.target.value) })} />
          </Isian>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" variant="outline" onClick={useMyLocation} disabled={locating} data-testid="cfg-use-my-location">
            <LocateFixed />{locating ? 'Membaca lokasi…' : 'Pakai lokasi saya sekarang'}
          </Button>
          {f.office_lat != null && f.office_lng != null && (
            <a className="text-sm text-primary underline-offset-4 hover:underline" target="_blank" rel="noreferrer"
              href={peta(f.office_lat, f.office_lng)}>Lihat titik ini di Google Maps</a>
          )}
        </div>
        {lokasiMsg && <Notice tone={lokasiMsg.tone} testId="attendance-config-msg">{lokasiMsg.text}</Notice>}
        <p className="text-xs text-muted-foreground">Cara lain: buka Google Maps, klik kanan titik kantor, lalu salin angka lintang dan bujurnya ke kolom di atas.</p>

        <p className="text-base font-semibold text-foreground">Kebijakan absen</p>
        <label className="flex items-start gap-3 text-sm" htmlFor="cfg-require-selfie">
          <Switch id="cfg-require-selfie" data-testid="cfg-require-selfie" checked={f.require_selfie !== false}
            onCheckedChange={(v) => setField({ require_selfie: v })} />
          <span>Selfie wajib
            <span className="block text-xs text-muted-foreground">Absen tanpa foto ditolak. Foto disimpan sebagai bukti dan bisa dibuka HR.</span>
          </span>
        </label>
        <label className="flex items-start gap-3 text-sm" htmlFor="cfg-require-geofence">
          <Switch id="cfg-require-geofence" data-testid="cfg-require-geofence" checked={f.require_geofence !== false}
            onCheckedChange={(v) => setField({ require_geofence: v })} />
          <span>Lokasi wajib (di dalam radius kantor)
            <span className="block text-xs text-muted-foreground">Absen di luar radius ditolak, bukan sekadar menunggu persetujuan.</span>
          </span>
        </label>
        <div className="grid gap-4 sm:grid-cols-3" data-testid="cfg-gps-rules">
          <Isian label="Umur lokasi maks. (detik)" htmlFor="cfg-gps-age" petunjuk="Lokasi lebih tua dari ini ditolak.">
            <Input id="cfg-gps-age" data-testid="cfg-gps-age" type="number" min={10} max={600} value={f.gps_max_age_s ?? 60}
              onChange={(e) => setField({ gps_max_age_s: parseInt(e.target.value, 10) })} />
          </Isian>
          <Isian label="Akurasi GPS terburuk (m)" htmlFor="cfg-gps-acc" petunjuk="Bacaan kurang akurat diminta coba lagi.">
            <Input id="cfg-gps-acc" data-testid="cfg-gps-acc" type="number" min={10} max={2000} value={f.gps_max_accuracy_m ?? 100}
              onChange={(e) => setField({ gps_max_accuracy_m: parseInt(e.target.value, 10) })} />
          </Isian>
          <Isian label="Jendela absen pulang (jam)" htmlFor="cfg-out-window" petunjuk="Pulang lewat tengah malam masih menutup absen kemarin.">
            <Input id="cfg-out-window" data-testid="cfg-out-window" type="number" min={0} max={24} step="0.5" value={f.clock_out_window_hours ?? 6}
              onChange={(e) => setField({ clock_out_window_hours: parseFloat(e.target.value) })} />
          </Isian>
        </div>

        <p className="text-base font-semibold text-foreground">Kecocokan wajah</p>
        <Isian label={`Kecocokan wajah minimum: ${Math.round((f.face_match_threshold || 0.65) * 100)}%`}
          petunjuk="Selfie di bawah angka ini masuk antrean Persetujuan absen. Saran: 60–70%.">
          <Slider min={0} max={100} step={5} value={[Math.round((f.face_match_threshold || 0.65) * 100)]}
            onValueChange={([v]) => setField({ face_match_threshold: v / 100 })} aria-label="Kecocokan wajah minimum"
            className="py-2" data-testid="cfg-face-threshold" />
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>0% (longgar)</span><span>100% (sangat ketat)</span>
          </div>
        </Isian>
      </FormPopup>
    </PageLayout>
  );
}

// ─── Biometrik HP (WebAuthn) ──────────────────────────────────────────────────
export function BiometrikHP({ token }) {
  const headers = useHeaders(token);
  const [devices, setDevices] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(false);
  const [revoking, setRevoking] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [d, e] = await Promise.all([
        axios.get(`${BACKEND}/api/rahaza/attendance/webauthn/devices`, { headers }),
        axios.get(`${BACKEND}/api/rahaza/employees?limit=500`, { headers }),   // Tahap 5: dulu batas bawaan 50
      ]);
      setDevices(d.data || []);
      setEmployees(Array.isArray(e.data) ? e.data : (e.data?.items || e.data?.rows || e.data?.data || []));
    } catch (e) { toast.error('Data biometrik gagal dimuat.'); }
    finally { setLoading(false); }
  }, [headers]);

  useEffect(() => { load(); }, [load]);

  const revoke = async (id) => {
    if (!(await confirmDialog({ title: 'Cabut data biometrik ini?', body: 'Karyawan harus mendaftar ulang di HP-nya untuk absen dengan sidik jari atau Face ID.', confirmLabel: 'Cabut', danger: true }))) return;
    setRevoking(id);
    try {
      await axios.delete(`${BACKEND}/api/rahaza/attendance/webauthn/devices/${id}`, { headers });
      toast.success('Data biometrik dicabut.');
      await load();
    } catch (e) { toast.error('Gagal mencabut data biometrik.'); }
    finally { setRevoking(null); }
  };

  const empMap = useMemo(() => Object.fromEntries(employees.map((e) => [e.id, e])), [employees]);
  const emp = (d) => empMap[d.employee_id] || {};
  const { page, setPage, totalPages, total, paged } = useClientPagination(devices, 10);

  const kolom = [
    { kunci: 'karyawan', label: 'Karyawan', hp: 'judul', isi: (d) => (
      <div className="min-w-0"><p className="font-medium text-foreground">{emp(d).name || d.employee_id}</p>
        <p className="text-xs text-muted-foreground">{emp(d).employee_code || '—'}</p></div>) },
    { kunci: 'device', label: 'Nama perangkat', isi: (d) => d.device_name || 'Perangkat' },
    { kunci: 'dibuat', label: 'Terdaftar', isi: (d) => <span className="whitespace-nowrap">{fmtTanggal(d.created_at)}</span> },
    { kunci: 'dipakai', label: 'Terakhir dipakai', isi: (d) => <span className="whitespace-nowrap">{fmtTanggal(d.last_used_at)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (d) => (
      <Button size="sm" variant="outline" onClick={() => revoke(d.id)} disabled={revoking === d.id}>
        <Trash2 />{revoking === d.id ? 'Mencabut…' : 'Cabut'}
      </Button>) },
  ];

  return (
    <PageLayout testId="attendance-webauthn-tab" title="Biometrik HP"
      subtitle="Sidik jari / Face ID yang didaftarkan karyawan di HP-nya untuk absen."
      tools={<>
        <TombolUnduh namaBerkas="biometrik-absen" namaLembar="Biometrik" baris={devices} testId="webauthn-unduh"
          kolom={[
            { label: 'Kode karyawan', nilai: (d) => emp(d).employee_code || '' },
            { label: 'Nama karyawan', nilai: (d) => emp(d).name || d.employee_id },
            { label: 'Nama perangkat', nilai: (d) => d.device_name || 'Perangkat' },
            { label: 'Terdaftar', nilai: (d) => fmtTanggal(d.created_at) },
            { label: 'Terakhir dipakai', nilai: (d) => fmtTanggal(d.last_used_at) },
          ]} />
        <MuatUlang onClick={load} memuat={loading} />
      </>}
      footer={devices.length > 0 && <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />}>
      {loading && devices.length === 0 ? <Memuat /> : (
        <TabelData kolom={kolom} baris={paged} testId="webauthn-table"
          kosong={<EmptyState icon={Fingerprint} title="Belum ada biometrik terdaftar"
            description="Karyawan mendaftarkan sidik jari atau Face ID sendiri di halaman absen pada HP-nya." />} />
      )}
    </PageLayout>
  );
}

// ─── Mesin sidik jari (ZKTeco/Fingerspot) ─────────────────────────────────────
const FORM_MESIN = { name: '', ip: '', port: 4370, password: 0, timezone: 8, enabled: true };
const STATUS_SINKRON = {
  success: { label: 'Berhasil', tone: 'success' },
  success_simulator: { label: 'Uji simulator', tone: 'info' },
  error: { label: 'Gagal', tone: 'danger' },
};

export function MesinSidikJari({ token }) {
  const headers = useHeaders(token);
  const [devices, setDevices] = useState([]);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(null);
  const [form, setForm] = useState(null);         // null = popup tertutup
  const [saving, setSaving] = useState(false);
  const [galat, setGalat] = useState('');
  const [impor, setImpor] = useState(false);
  const [syncResults, setSyncResults] = useState({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${BACKEND}/api/rahaza/devices/zkteco`, { headers });
      setDevices(r.data || []);
    } catch (e) { toast.error('Daftar mesin gagal dimuat.'); }
    finally { setLoading(false); }
  }, [headers]);

  useEffect(() => { load(); }, [load]);

  const saveDevice = async () => {
    if (!form.name || !form.ip) { setGalat('Nama dan alamat IP wajib diisi.'); return; }
    setSaving(true); setGalat('');
    try {
      await axios.post(`${BACKEND}/api/rahaza/devices/zkteco`, form, { headers });
      toast.success('Mesin ditambahkan.');
      setForm(null);
      await load();
    } catch (e) { setGalat(e.response?.data?.detail || 'Gagal menyimpan'); }
    finally { setSaving(false); }
  };

  const deleteDevice = async (d) => {
    if (!(await confirmDialog({ title: 'Hapus mesin ini?', body: `"${d.name}" dihapus dari daftar. Data absen yang sudah masuk tetap ada.`, confirmLabel: 'Hapus', danger: true }))) return;
    try {
      await axios.delete(`${BACKEND}/api/rahaza/devices/zkteco/${d.id}`, { headers });
      toast.success('Mesin dihapus.');
      await load();
    } catch (e) { toast.error('Gagal menghapus'); }
  };

  const syncDevice = async (id, simulator = false) => {
    setSyncing(id); setSyncResults((prev) => ({ ...prev, [id]: null }));
    try {
      const r = await axios.post(`${BACKEND}/api/rahaza/devices/zkteco/${id}/sync`, { simulator }, { headers });
      setSyncResults((prev) => ({ ...prev, [id]: { ok: true, data: r.data } }));
      await load();
    } catch (e) {
      const err = e.response?.data?.detail || 'Sinkron gagal';
      setSyncResults((prev) => ({ ...prev, [id]: { ok: false, error: err } }));
    } finally { setSyncing(null); }
  };

  const setF = (patch) => setForm((f) => ({ ...f, ...patch }));
  const statusSinkron = (d) => STATUS_SINKRON[d.last_sync_status];

  const kolom = [
    { kunci: 'mesin', label: 'Mesin', hp: 'judul', isi: (d) => {
      const hasil = syncResults[d.id];
      return (
        <div className="min-w-0">
          <p className="font-medium text-foreground">{d.name}</p>
          <p className="text-xs text-muted-foreground tabular-nums">{d.ip}:{d.port}{d.password ? ' · bersandi' : ''}</p>
          {d.last_error && <p className="text-xs text-[hsl(var(--danger-text))]">{d.last_error}</p>}
          {hasil && (
            <p className={`text-xs ${hasil.ok ? 'text-[hsl(var(--success-text))]' : 'text-[hsl(var(--danger-text))]'}`}>
              {hasil.ok ? `${hasil.data?.message || 'Sinkron berhasil'} (${hasil.data?.synced || 0} data)` : hasil.error}
            </p>
          )}
        </div>
      );
    } },
    { kunci: 'aktif', label: 'Aktif', isi: (d) => <StatusBadge status={d.enabled ? 'aktif' : 'nonaktif'} label={d.enabled ? 'Aktif' : 'Nonaktif'} tone={d.enabled ? 'success' : 'muted'} /> },
    { kunci: 'sinkron', label: 'Sinkron terakhir', isi: (d) => <span className="whitespace-nowrap">{d.last_sync_at ? fmtWaktu(d.last_sync_at) : 'Belum pernah'}</span> },
    { kunci: 'data', label: 'Data terakhir', rata: 'kanan', isi: (d) => <span className="tabular-nums">{d.last_sync_records || 0}</span> },
    { kunci: 'status', label: 'Hasil', isi: (d) => (statusSinkron(d)
      ? <StatusBadge status={d.last_sync_status} label={statusSinkron(d).label} tone={statusSinkron(d).tone} />
      : <span className="text-muted-foreground">—</span>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (d) => (
      <div className="flex items-center justify-end gap-1">
        <Button size="sm" variant="outline" onClick={() => syncDevice(d.id, false)} disabled={syncing === d.id}>
          <RefreshCw className={syncing === d.id ? 'animate-spin' : ''} />{syncing === d.id ? 'Menyinkron…' : 'Sinkron'}
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="icon-sm" variant="ghost" aria-label="Lainnya" title="Lainnya"><MoreHorizontal /></Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => syncDevice(d.id, true)} disabled={syncing === d.id}>
              <Wifi className="mr-2 h-4 w-4" />Uji dengan simulator
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => deleteDevice(d)} className="text-[hsl(var(--danger-text))]">
              <Trash2 className="mr-2 h-4 w-4" />Hapus mesin
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>) },
  ];

  return (
    <PageLayout testId="attendance-device-tab" title="Mesin sidik jari"
      subtitle="Mesin ZKTeco/Fingerspot di kantor. Bila server tidak menjangkau mesin, unggah file ekspornya."
      filters={<p className="text-sm text-muted-foreground">
        Sinkron langsung hanya bisa bila server menjangkau mesin di jaringan kantor. Bila tidak, pakai Impor file mesin.
      </p>}
      actions={<>
        <Button variant="outline" onClick={() => { setForm({ ...FORM_MESIN }); setGalat(''); }} data-testid="device-add"><Plus />Tambah mesin</Button>
        <Button onClick={() => setImpor(true)} data-testid="fingerprint-open"><Upload />Impor file mesin</Button>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="mesin-sidik-jari" namaLembar="Mesin" baris={devices} testId="device-unduh"
          kolom={[
            { label: 'Nama', nilai: (d) => d.name },
            { label: 'Alamat IP', nilai: (d) => d.ip },
            { label: 'Port', nilai: (d) => d.port },
            { label: 'Aktif', nilai: (d) => (d.enabled ? 'Aktif' : 'Nonaktif') },
            { label: 'Sinkron terakhir', nilai: (d) => (d.last_sync_at ? fmtWaktu(d.last_sync_at) : 'Belum pernah') },
            { label: 'Data terakhir', nilai: (d) => d.last_sync_records || 0 },
            { label: 'Hasil', nilai: (d) => statusSinkron(d)?.label || '' },
            { label: 'Galat terakhir', nilai: (d) => d.last_error || '' },
          ]} />
        <MuatUlang onClick={load} memuat={loading} />
      </>}
>
      {loading && devices.length === 0 ? <Memuat /> : (
        <TabelData kolom={kolom} baris={devices} testId="device-table"
          kosong={<EmptyState icon={Fingerprint} title="Belum ada mesin"
            description="Tambah mesin ZKTeco/Fingerspot untuk sinkron langsung, atau impor file ekspor dari mesin." />} />
      )}

      <FormPopup open={form !== null} onClose={() => setForm(null)} ukuran="pendek" onSimpan={saveDevice} menyimpan={saving}
        judul="Tambah mesin sidik jari" keterangan="Mesin harus satu jaringan dengan server agar bisa disinkron langsung."
        galat={galat} testId="device-form">
        {form && <>
          <Isian label="Nama mesin" wajib htmlFor="dev-name">
            <Input id="dev-name" value={form.name} onChange={(e) => setF({ name: e.target.value })} placeholder="Mesin absen lantai 1" />
          </Isian>
          <div className="grid gap-4 sm:grid-cols-2">
            <Isian label="Alamat IP" wajib htmlFor="dev-ip">
              <Input id="dev-ip" value={form.ip} onChange={(e) => setF({ ip: e.target.value })} placeholder="192.168.1.100" />
            </Isian>
            <Isian label="Port" htmlFor="dev-port">
              <Input id="dev-port" type="number" value={form.port} onChange={(e) => setF({ port: parseInt(e.target.value, 10) })} />
            </Isian>
          </div>
          <Isian label="Sandi mesin" htmlFor="dev-pass" petunjuk="Isi 0 bila mesin tidak bersandi.">
            <Input id="dev-pass" type="number" value={form.password} onChange={(e) => setF({ password: parseInt(e.target.value, 10) })} />
          </Isian>
          <label className="flex items-center gap-3 text-sm" htmlFor="dev-enabled">
            <Switch id="dev-enabled" checked={form.enabled} onCheckedChange={(v) => setF({ enabled: v })} />
            <span>Aktif</span>
          </label>
          <p className="text-xs text-muted-foreground">Untuk mencoba tanpa mesin, simpan lalu pilih Lainnya › Uji dengan simulator.</p>
        </>}
      </FormPopup>

      {/* Tahap 2 (2026-11-06): jalur utama — unggah file ekspor mesin */}
      <FingerprintImportPanel open={impor} onClose={() => setImpor(false)} headers={headers} />
    </PageLayout>
  );
}

// ─── Absen otomatis hari ini ──────────────────────────────────────────────────
const METODE = {
  selfie_geo_ai: 'Selfie + AI',
  webauthn: 'Biometrik HP',
  device_zkteco: 'Mesin sidik jari',
  manual: 'Manual',
};
const PERSETUJUAN = {
  auto_approved: { label: 'Otomatis', tone: 'success' },
  approved: { label: 'Disetujui', tone: 'success' },
  pending: { label: 'Menunggu', tone: 'warning' },
};
const persetujuan = (r) => PERSETUJUAN[r.approval_status] || { label: 'Ditolak', tone: 'danger' };
const lokasi = (r) => (r.geo_status === 'in_range' ? 'Di area kantor' : r.geo_status === 'out_of_range' ? 'Di luar area' : '—');
const wajah = (r) => (r.face_match_status === 'checked' ? `${Math.round((r.face_match_score || 0) * 100)}%` : '—');

export function AbsenOtomatisHariIni({ token }) {
  const headers = useHeaders(token);
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(false);
  const [methodFilter, setMethodFilter] = useState('auto');
  const today = todayWIB();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const hari = todayWIB();
      const params = new URLSearchParams({ status: 'all', from_date: hari, to_date: hari });
      const r = await axios.get(`${BACKEND}/api/rahaza/attendance/approvals?${params}`, { headers });
      let data = r.data || [];
      if (methodFilter === 'auto') {
        data = data.filter((x) => x.attendance_method && x.attendance_method !== 'manual' && x.source !== 'supervisor');
      }
      setRecords(data);
    } catch (e) { toast.error('Absen hari ini gagal dimuat.'); }
    finally { setLoading(false); }
  }, [methodFilter, headers]);

  useEffect(() => { load(); }, [load]);

  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(records, 15);
  const kolom = [
    { kunci: 'karyawan', label: 'Karyawan', hp: 'judul', isi: (r) => r.employee_name || r.employee_id },
    { kunci: 'metode', label: 'Metode', hp: 'keterangan', isi: (r) => METODE[r.attendance_method] || 'Manual' },
    { kunci: 'lokasi', label: 'Lokasi', isi: lokasi },
    { kunci: 'wajah', label: 'Kecocokan wajah', rata: 'kanan', isi: (r) => <span className="tabular-nums">{wajah(r)}</span> },
    { kunci: 'masuk', label: 'Masuk', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtJam(r.clock_in)}</span> },
    { kunci: 'pulang', label: 'Pulang', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.clock_out ? fmtJam(r.clock_out) : '—'}</span> },
    { kunci: 'status', label: 'Status', isi: (r) => <StatusBadge status={r.approval_status} label={persetujuan(r).label} tone={persetujuan(r).tone} /> },
  ];

  return (
    <PageLayout testId="attendance-live-tab" title="Absen otomatis hari ini"
      subtitle="Absen lewat selfie, biometrik HP, dan mesin sidik jari pada hari ini."
      filters={<>
        <SmartNativeSelect value={methodFilter} onChange={(e) => setMethodFilter(e.target.value)} searchable={false}
          data-testid="auto-att-method-filter" className="h-9 w-52" aria-label="Metode absen">
          <option value="auto">Hanya absen otomatis</option>
          <option value="all">Semua metode</option>
        </SmartNativeSelect>
        <span className="text-sm text-muted-foreground">{formatTanggalID(today)}</span>
        {/* Unduh & muat ulang di ujung kanan; di HP turun ke baris sendiri (tidak menimpa penyaring) */}
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <TombolUnduh namaBerkas={`absen-otomatis-${today}`} namaLembar="Absen hari ini" baris={records} testId="live-unduh"
            kolom={[
              { label: 'Karyawan', nilai: (r) => r.employee_name || r.employee_id },
              { label: 'Metode', nilai: (r) => METODE[r.attendance_method] || 'Manual' },
              { label: 'Lokasi', nilai: lokasi },
              { label: 'Kecocokan wajah', nilai: wajah },
              { label: 'Masuk', nilai: (r) => fmtJam(r.clock_in) },
              { label: 'Pulang', nilai: (r) => (r.clock_out ? fmtJam(r.clock_out) : '') },
              { label: 'Status', nilai: (r) => persetujuan(r).label },
            ]} />
          <MuatUlang onClick={load} memuat={loading} />
        </div>
      </>}
      footer={records.length > 0 && <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />}>
      {loading && records.length === 0 ? <Memuat /> : (
        <TabelData kolom={kolom} baris={paged} testId="live-table"
          kosong={<EmptyState icon={Fingerprint} title={methodFilter === 'auto' ? 'Belum ada absen otomatis hari ini' : 'Belum ada absen hari ini'}
            description="Absen lewat selfie, biometrik HP, atau mesin sidik jari akan tampil di sini." />} />
      )}
    </PageLayout>
  );
}

/** Bawaan: tab "Absen otomatis" (id lama `hr-auto-attendance` diarahkan ke tab ini). */
export default AbsenOtomatisHariIni;

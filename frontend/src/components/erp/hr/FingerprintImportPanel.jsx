/**
 * FingerprintImportPanel — unggah file EKSPOR mesin sidik jari (ZKTeco/Fingerspot) — Tahap 2 (2026-11-06).
 *
 * Dipasang di tab "Device Fisik" layar Absen Otomatis (tidak ada menu baru). Mesin di kantor tidak bisa
 * mengirim lewat https dan server tidak bisa menjangkau mesin di jaringan lokal, jadi HR mengunggah file
 * ekspornya: pilih file → petakan kolom → pratinjau hitungan → impor. Pemetaan bisa disimpan sebagai profil.
 * Aturan gabung (ketukan pertama = masuk, terakhir = pulang; selfie/HR tidak ditimpa; aman diulang) ada di
 * backend/core/fingerprint_import.py.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { FileUp, Loader2, Save, Upload } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Label } from '@/components/ui/label';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Notice, StatTile } from '../moduleAtoms';

const BACKEND = process.env.REACT_APP_BACKEND_URL;
const FIELDS = [
  { key: 'code', label: 'Kode karyawan / PIN', required: true },
  { key: 'datetime', label: 'Tanggal dan jam (satu kolom)' },
  { key: 'date', label: 'Tanggal (kolom terpisah)' },
  { key: 'time', label: 'Jam (kolom terpisah)' },
  { key: 'direction', label: 'Penanda masuk/pulang (opsional)' },
];
const ORDERS = [
  { value: 'dmy', label: 'Hari/bulan/tahun (31/12/2026)' },
  { value: 'ymd', label: 'Tahun-bulan-hari (2026-12-31)' },
  { value: 'mdy', label: 'Bulan/hari/tahun (12/31/2026)' },
];

export default function FingerprintImportPanel({ headers }) {
  const fileRef = useRef(null);
  const [file, setFile] = useState(null);
  const [mapping, setMapping] = useState({});
  const [order, setOrder] = useState('dmy');
  const [profiles, setProfiles] = useState([]);
  const [profileId, setProfileId] = useState('');
  const [profileName, setProfileName] = useState('');
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  const loadProfiles = useCallback(async () => {
    try {
      const r = await axios.get(`${BACKEND}/api/rahaza/devices/fingerprint/profiles`, { headers });
      setProfiles(r.data?.items || []);
    } catch { setProfiles([]); }
  }, [headers]);
  useEffect(() => { loadProfiles(); }, [loadProfiles]);

  const post = async (kind, f = file, map = mapping, prof = profileId) => {
    const fd = new FormData();
    fd.append('file', f);
    if (map && Object.keys(map).length) fd.append('mapping', JSON.stringify(map));
    if (prof) fd.append('profile_id', prof);
    fd.append('date_order', order);
    return axios.post(`${BACKEND}/api/rahaza/devices/fingerprint/${kind}`, fd, { headers });
  };

  const runPreview = async (f = file, map = mapping, prof = profileId) => {
    if (!f) return;
    setBusy('preview'); setError(''); setResult(null);
    try {
      const r = await post('preview', f, map, prof);
      setPreview(r.data);
      setMapping(r.data.mapping || {});
      if (r.data.mapping_error) setError(r.data.mapping_error);
    } catch (e) {
      setPreview(null);
      setError(e.response?.data?.detail || 'File tidak bisa dibaca.');
    } finally { setBusy(''); }
  };

  const onPick = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setFile(f);
    setMapping({});
    runPreview(f, {}, profileId);
    e.target.value = '';
  };

  const runImport = async () => {
    setBusy('import'); setError('');
    try {
      const r = await post('import');
      setResult(r.data);
      setPreview(r.data);
    } catch (e) { setError(e.response?.data?.detail || 'Impor gagal.'); } finally { setBusy(''); }
  };

  const saveProfile = async () => {
    if (!profileName.trim()) { setError('Isi nama profil dulu.'); return; }
    setBusy('profile');
    try {
      const r = await axios.post(`${BACKEND}/api/rahaza/devices/fingerprint/profiles`,
        { name: profileName.trim(), mapping, date_order: order }, { headers });
      setProfileId(r.data?.profile?.id || '');
      await loadProfiles();
    } catch (e) { setError(e.response?.data?.detail || 'Profil gagal disimpan.'); } finally { setBusy(''); }
  };

  const st = preview?.stats;
  const header = preview?.header || [];

  return (
    <GlassCard className="p-4 space-y-3" data-testid="fingerprint-import">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <p className="text-base font-semibold">Unggah file ekspor mesin</p>
          <p className="text-xs text-muted-foreground">
            Ekspor data absen dari mesin (CSV atau Excel), unggah di sini, cocokkan kolomnya, lalu impor.
            Ketukan pertama = jam masuk, terakhir = jam pulang. Selfie dan isian HR tidak ditimpa; unggah ulang aman.
          </p>
        </div>
        <Button variant="outline" onClick={() => fileRef.current?.click()} disabled={Boolean(busy)} data-testid="fingerprint-pick">
          <Upload className="w-4 h-4" /> Pilih file
        </Button>
        <input ref={fileRef} type="file" accept=".csv,.txt,.xlsx" className="hidden" onChange={onPick}
          data-testid="fingerprint-file" />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div>
          <Label className="text-xs">Profil pemetaan</Label>
          <SmartNativeSelect value={profileId} searchable={false} className="mt-1"
            onChange={(e) => { setProfileId(e.target.value); if (file) runPreview(file, {}, e.target.value); }}
            data-testid="fingerprint-profile">
            <option value="">Tebak otomatis dari nama kolom</option>
            {profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </SmartNativeSelect>
        </div>
        <div>
          <Label className="text-xs">Urutan tanggal di file</Label>
          <SmartNativeSelect value={order} searchable={false} className="mt-1" onChange={(e) => setOrder(e.target.value)}
            data-testid="fingerprint-order">
            {ORDERS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </SmartNativeSelect>
        </div>
        {file && <p className="text-xs text-muted-foreground self-end">File: {file.name}</p>}
      </div>

      {error && <Notice tone="danger" testId="fingerprint-error">{error}</Notice>}

      {header.length > 0 && (
        <div className="space-y-2" data-testid="fingerprint-mapping">
          <p className="text-sm font-medium">Cocokkan kolom</p>
          <div className="grid grid-cols-1 md:grid-cols-5 gap-2">
            {FIELDS.map((f) => (
              <div key={f.key}>
                <Label className="text-xs">{f.label}</Label>
                <SmartNativeSelect value={mapping[f.key] || ''} searchable={false} className="mt-1"
                  onChange={(e) => setMapping((m) => ({ ...m, [f.key]: e.target.value }))}
                  data-testid={`fingerprint-map-${f.key}`}>
                  <option value="">—</option>
                  {header.map((h) => <option key={h} value={h}>{h}</option>)}
                </SmartNativeSelect>
              </div>
            ))}
          </div>
          {preview?.sample_rows?.length > 0 && (
            <p className="text-xs text-muted-foreground">
              Contoh baris pertama: {preview.sample_rows[0].join(' · ')}
            </p>
          )}
          <div className="flex flex-wrap items-end gap-2">
            <Button variant="outline" onClick={() => runPreview()} disabled={Boolean(busy)} data-testid="fingerprint-preview">
              {busy === 'preview' ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileUp className="w-4 h-4" />} Hitung ulang pratinjau
            </Button>
            <div className="flex items-end gap-2">
              <div>
                <Label className="text-xs">Simpan pemetaan sebagai profil</Label>
                <GlassInput className="mt-1" value={profileName} placeholder="Contoh: Mesin lobi"
                  onChange={(e) => setProfileName(e.target.value)} data-testid="fingerprint-profile-name" />
              </div>
              <Button variant="outline" onClick={saveProfile} disabled={Boolean(busy)} data-testid="fingerprint-profile-save">
                <Save className="w-4 h-4" /> Simpan profil
              </Button>
            </div>
          </div>
        </div>
      )}

      {st && (
        <div className="space-y-2" data-testid="fingerprint-stats">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <StatTile label="Ketukan terbaca" value={st.punches} sub={st.invalid_rows ? `${st.invalid_rows} baris tidak terbaca` : undefined} />
            <StatTile label="Hari absen baru" value={st.new} accent="success" />
            <StatTile label="Dilengkapi" value={st.updated} sub={`${st.unchanged} tidak berubah`} />
            <StatTile label="Kode tidak dikenal" value={st.unmatched_count} accent={st.unmatched_count ? 'warning' : 'muted'}
              sub={st.unmatched_codes?.length ? st.unmatched_codes.slice(0, 5).join(', ') : undefined} />
          </div>
          {(st.conflict > 0 || st.locked > 0) && (
            <Notice tone="warning">
              {st.conflict > 0 && `${st.conflict} hari berstatus cuti/izin/sakit/alpa dari HR — statusnya tidak diubah. `}
              {st.locked > 0 && `${st.locked} hari sudah masuk gaji final dan dilewati.`}
            </Notice>
          )}
          {preview?.previous_import_at && !result && (
            <Notice tone="info">File yang sama pernah diimpor. Mengimpor ulang tidak membuat data dobel.</Notice>
          )}
          {result ? (
            <Notice tone="success" testId="fingerprint-done">
              Impor selesai: {st.new} hari baru, {st.updated} hari dilengkapi.
            </Notice>
          ) : (
            <Button onClick={runImport} disabled={Boolean(busy) || !preview?.ready} data-testid="fingerprint-import-btn">
              {busy === 'import' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />} Impor ke absensi
            </Button>
          )}
        </div>
      )}
    </GlassCard>
  );
}

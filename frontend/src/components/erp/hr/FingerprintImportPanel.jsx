/**
 * FingerprintImportPanel — unggah file EKSPOR mesin sidik jari (ZKTeco/Fingerspot) — Tahap 2 (2026-11-06).
 *
 * Dibuka dari tab "Mesin sidik jari" (hub Absensi) lewat tombol "Impor file mesin". Mesin di kantor tidak bisa
 * mengirim lewat https dan server tidak bisa menjangkau mesin di jaringan lokal, jadi HR mengunggah file
 * ekspornya: pilih file → petakan kolom → pratinjau hitungan → impor. Pemetaan bisa disimpan sebagai profil.
 * Aturan gabung (ketukan pertama = masuk, terakhir = pulang; selfie/HR tidak ditimpa; aman diulang) ada di
 * backend/core/fingerprint_import.py.
 *
 * Standar UI/UX v2 (8 Nov 2026): dulu panel tetap di halaman; sekarang popup form standar (FormPopup panjang).
 * Langkah, panggilan API, dan data yang dikirim tidak berubah.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { FileUp, Loader2, Save, Upload } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FormPopup, { Isian } from '@/components/ui/form-popup';
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

export default function FingerprintImportPanel({ open, onClose, headers }) {
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
  useEffect(() => { if (open) loadProfiles(); }, [open, loadProfiles]);

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
    <FormPopup open={open} onClose={onClose} ukuran="panjang" testId="fingerprint-import"
      judul="Impor file ekspor mesin"
      keterangan="Ketukan pertama = jam masuk, terakhir = jam pulang. Selfie dan isian HR tidak ditimpa; unggah ulang aman."
      onSimpan={runImport} labelSimpan={result ? 'Sudah diimpor' : 'Impor ke absensi'}
      menyimpan={busy === 'import'} bisaSimpan={Boolean(preview?.ready) && !result && !busy} galat={error}>
      <Isian label="File ekspor (CSV atau Excel)">
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" variant="outline" onClick={() => fileRef.current?.click()} disabled={Boolean(busy)} data-testid="fingerprint-pick">
            {busy === 'preview' ? <Loader2 className="animate-spin" /> : <Upload />} Pilih file
          </Button>
          <span className="text-sm text-muted-foreground">{file ? file.name : 'Belum ada file dipilih'}</span>
        </div>
        <input ref={fileRef} type="file" accept=".csv,.txt,.xlsx" className="hidden" onChange={onPick}
          data-testid="fingerprint-file" />
      </Isian>

      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Profil pemetaan">
          <SmartNativeSelect value={profileId} searchable={false} aria-label="Profil pemetaan"
            onChange={(e) => { setProfileId(e.target.value); if (file) runPreview(file, {}, e.target.value); }}
            data-testid="fingerprint-profile">
            <option value="">Tebak otomatis dari nama kolom</option>
            {profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Urutan tanggal di file">
          <SmartNativeSelect value={order} searchable={false} aria-label="Urutan tanggal di file" onChange={(e) => setOrder(e.target.value)}
            data-testid="fingerprint-order">
            {ORDERS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </SmartNativeSelect>
        </Isian>
      </div>

      {header.length > 0 && (
        <div className="space-y-3" data-testid="fingerprint-mapping">
          <p className="text-base font-semibold text-foreground">Cocokkan kolom</p>
          <div className="grid gap-3 sm:grid-cols-2">
            {FIELDS.map((f) => (
              <Isian key={f.key} label={f.label}>
                <SmartNativeSelect value={mapping[f.key] || ''} searchable={false} aria-label={f.label}
                  onChange={(e) => setMapping((m) => ({ ...m, [f.key]: e.target.value }))}
                  data-testid={`fingerprint-map-${f.key}`}>
                  <option value="">—</option>
                  {header.map((h) => <option key={h} value={h}>{h}</option>)}
                </SmartNativeSelect>
              </Isian>
            ))}
          </div>
          {preview?.sample_rows?.length > 0 && (
            <p className="text-xs text-muted-foreground">Contoh baris pertama: {preview.sample_rows[0].join(' · ')}</p>
          )}
          <div className="flex flex-wrap items-end gap-2">
            <Button type="button" variant="outline" onClick={() => runPreview()} disabled={Boolean(busy)} data-testid="fingerprint-preview">
              {busy === 'preview' ? <Loader2 className="animate-spin" /> : <FileUp />} Hitung ulang pratinjau
            </Button>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <Isian label="Simpan pemetaan sebagai profil" className="min-w-0 flex-1 sm:max-w-xs">
              <Input value={profileName} placeholder="Contoh: Mesin lobi" aria-label="Nama profil"
                onChange={(e) => setProfileName(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); saveProfile(); } }}
                data-testid="fingerprint-profile-name" />
            </Isian>
            <Button type="button" variant="outline" onClick={saveProfile} disabled={Boolean(busy)} data-testid="fingerprint-profile-save">
              <Save /> Simpan profil
            </Button>
          </div>
        </div>
      )}

      {st && (
        <div className="space-y-3" data-testid="fingerprint-stats">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <StatTile label="Ketukan terbaca" value={st.punches} hint="Baris ketukan yang terbaca dari file."
              sub={st.invalid_rows ? `${st.invalid_rows} baris tidak terbaca` : undefined} />
            <StatTile label="Hari absen baru" value={st.new} accent="success" hint="Hari karyawan yang belum punya absen." />
            <StatTile label="Dilengkapi" value={st.updated} sub={`${st.unchanged} tidak berubah`} hint="Absen yang sudah ada lalu dilengkapi jamnya." />
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
          {result && (
            <Notice tone="success" testId="fingerprint-done">
              Impor selesai: {st.new} hari baru, {st.updated} hari dilengkapi.
            </Notice>
          )}
        </div>
      )}
    </FormPopup>
  );
}

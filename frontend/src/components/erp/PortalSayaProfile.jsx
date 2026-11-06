/**
 * PortalSayaProfile — Portal Saya › Profil.
 *
 * 2026-11-07 (keputusan owner HR1, Tahap 6): No. HP, alamat, dan kontak darurat adalah DATA KARYAWAN (yang
 * dibaca HR, slip, laporan). Dulu isian ini hanya tersimpan di akun login sehingga HR tidak pernah melihatnya.
 * Sekarang:
 *  · nilai yang tampil = data karyawan (akun tanpa tautan karyawan tetap memakai isian akun);
 *  · "Simpan" mengirim PENGAJUAN perubahan ke HR (Kotak Masuk SDM › Perubahan data, lama → baru); data
 *    karyawan baru berubah setelah HR menyetujui. Selama menunggu, isian kontak dikunci dan pengajuan bisa
 *    ditarik. Hasil terakhir (ditolak + alasan / disetujui) tampil di sini;
 *  · nama panggilan dan foto tetap langsung tersimpan di akun (bukan data karyawan).
 * Cetakan PageLayout (PANDUAN_UI G1); hubungan kontak darurat dipilih dari daftar yang sama dengan Data Karyawan.
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';
import {
  Loader2, User, Save, AlertCircle, Phone, MapPin, Camera, Upload, X, Hourglass, CheckCircle2, XCircle, Info,
  ChevronRight,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { toast } from 'sonner';
import { withFileAuth } from '@/lib/fileUrl';
import PageLayout from './layout/PageLayout';
import { Notice, StatusBadge } from './moduleAtoms';
import { EMERGENCY_RELATIONS } from './hr/hrPickers';

const API = process.env.REACT_APP_BACKEND_URL;
const EMPTY_KD = { nama: '', hubungan: '', no_hp: '' };
const FROM_ACCOUNT_LABEL = {
  no_hp: 'No. HP', alamat: 'Alamat', 'kontak_darurat.nama': 'Nama kontak darurat',
  'kontak_darurat.hubungan': 'Hubungan kontak darurat', 'kontak_darurat.no_hp': 'No. HP kontak darurat',
};
const fmtDate = (v) => {
  if (!v) return '';
  try { return new Date(v).toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'Asia/Jakarta' }); }
  catch { return ''; }
};
const RECENT_MS = 14 * 86400000;

function ChangeList({ changes = [] }) {
  return (
    <ul className="mt-1 space-y-0.5" data-testid="profile-change-list">
      {changes.map((c) => (
        <li key={c.field} className="flex flex-wrap items-center gap-1">
          <span className="text-muted-foreground">{c.label}:</span>
          <span className="line-through text-muted-foreground">{c.old || '(kosong)'}</span>
          <ChevronRight className="w-3 h-3" aria-hidden="true" />
          <span className="font-medium">{c.new || '(dikosongkan)'}</span>
        </li>
      ))}
    </ul>
  );
}

export default function PortalSayaProfile({ user, headers }) {
  const fileInputRef = useRef(null);
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [form, setForm] = useState({ nama_panggilan: '', no_hp: '', alamat: '', foto_url: '', kontak_darurat: EMPTY_KD });

  const load = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/api/portal/profile`, { headers });
      setProfile(data);
      setPreviewUrl(data.foto_url || null);
      setForm({
        nama_panggilan: data.nama_panggilan || '',
        no_hp: data.no_hp || '',
        alamat: data.alamat || '',
        foto_url: data.foto_url || '',
        kontak_darurat: { ...EMPTY_KD, ...(data.kontak_darurat || {}) },
      });
    } catch (e) {
      toast.error('Gagal memuat profil', { description: e.response?.data?.detail || e.message });
    } finally {
      setLoading(false);
    }
  }, [headers]);

  useEffect(() => { load(); }, [load]);

  const change = profile?.data_change || null;
  const pending = change && ['pending', 'deciding'].includes(change.status);
  const recent = change && change.decided_at && (Date.now() - new Date(change.decided_at).getTime() < RECENT_MS);
  const linked = !!profile?.is_linked;
  const contactLocked = linked && pending;

  const handleSave = async () => {
    setSaving(true);
    try {
      const body = contactLocked ? { nama_panggilan: form.nama_panggilan } : form;
      const { data } = await axios.put(`${API}/api/portal/profile`, body, { headers });
      toast.success(data?.message || 'Profil tersimpan.');
      load();
    } catch (e) {
      toast.error('Gagal menyimpan', { description: e.response?.data?.detail || e.message });
    } finally {
      setSaving(false);
    }
  };

  const cancelChange = async () => {
    const ok = await confirmDialog({
      title: 'Tarik pengajuan perubahan data?',
      body: 'Data karyawan tidak berubah. Anda bisa mengajukan ulang kapan saja.',
      confirmLabel: 'Tarik pengajuan',
    });
    if (!ok) return;
    try {
      await axios.post(`${API}/api/portal/profile/data-change/cancel`, {}, { headers });
      toast.success('Pengajuan perubahan data ditarik.');
      load();
    } catch (e) {
      toast.error('Gagal menarik pengajuan', { description: e.response?.data?.detail || e.message });
    }
  };

  const uploadPhoto = async (file) => {
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const { data } = await axios.post(`${API}/api/portal/profile/photo`, fd, {
        headers: { ...headers, 'Content-Type': 'multipart/form-data' },
      });
      setForm(f => ({ ...f, foto_url: data.foto_url }));
      setPreviewUrl(`${API}${data.foto_url}`);
      toast.success('Foto profil berhasil diunggah.');
    } catch (e) {
      toast.error('Gagal mengunggah foto', { description: e.response?.data?.detail || e.message });
      setPreviewUrl(form.foto_url || null);
    } finally {
      setUploading(false);
    }
  };

  const handlePhotoSelect = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setPreviewUrl(URL.createObjectURL(file));
    uploadPhoto(file);
  };

  const removePhoto = async () => {
    setPreviewUrl(null);
    setForm(f => ({ ...f, foto_url: '' }));
    try {
      await axios.put(`${API}/api/portal/profile`, { foto_url: '' }, { headers });
      toast.success('Foto profil dihapus.');
    } catch (e) {
      toast.error('Gagal menghapus foto', { description: e.response?.data?.detail || e.message });
    }
  };

  const set = (field, val) => setForm(f => ({ ...f, [field]: val }));
  const setKD = (field, val) => setForm(f => ({ ...f, kontak_darurat: { ...(f.kontak_darurat || {}), [field]: val } }));

  if (loading) {
    return (
      <PageLayout title="Profil saya" subtitle="Data akun dan kontak Anda.">
        <Skeleton className="h-40 rounded-[var(--radius-lg)]" />
        <Skeleton className="h-56 rounded-[var(--radius-lg)]" />
      </PageLayout>
    );
  }

  const emp = profile?.employee;
  const relation = form.kontak_darurat?.hubungan || '';
  const relationOptions = relation && !EMERGENCY_RELATIONS.includes(relation)
    ? [...EMERGENCY_RELATIONS, relation] : EMERGENCY_RELATIONS;
  const fromAccount = pending ? [] : (profile?.contact_from_account || []);
  const photoSrc = previewUrl
    ? (previewUrl.startsWith('blob:') ? previewUrl : withFileAuth(previewUrl.startsWith('/api') ? `${API}${previewUrl}` : previewUrl))
    : null;

  return (
    <PageLayout
      title="Profil saya"
      subtitle={linked ? 'Perubahan No. HP, alamat, dan kontak darurat disetujui HR dulu.' : 'Data akun dan kontak Anda.'}
      testId="portal-profile-page"
      actions={(
        <Button onClick={handleSave} disabled={saving || uploading} data-testid="btn-save-profile">
          {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
          {saving ? 'Menyimpan…' : 'Simpan profil'}
        </Button>
      )}
    >
      {pending && (
        <Notice tone="warning" icon={Hourglass} title="Perubahan data menunggu persetujuan HR" testId="profile-change-pending">
          Diajukan {fmtDate(change.created_at)}. Isian kontak dikunci sampai HR memutuskan.
          <ChangeList changes={change.changes} />
          <Button variant="outline" size="sm" className="mt-2" onClick={cancelChange} data-testid="btn-cancel-change">
            Tarik pengajuan
          </Button>
        </Notice>
      )}
      {!pending && change?.status === 'rejected' && recent && (
        <Notice tone="danger" icon={XCircle} title="Perubahan data ditolak HR" testId="profile-change-rejected">
          {fmtDate(change.decided_at)}{change.decision_note ? ` — ${change.decision_note}` : ''}. Data karyawan tidak berubah.
          <ChangeList changes={change.changes} />
        </Notice>
      )}
      {!pending && change?.status === 'approved' && recent && (
        <Notice tone="success" icon={CheckCircle2} title="Perubahan data disetujui HR" testId="profile-change-approved">
          {fmtDate(change.decided_at)} — data karyawan sudah diperbarui.
        </Notice>
      )}
      {fromAccount.length > 0 && (
        <Notice tone="info" icon={Info} testId="profile-from-account">
          {fromAccount.map(k => FROM_ACCOUNT_LABEL[k]).join(', ')} berasal dari akun Anda dan belum tercatat di data
          karyawan. Tekan Simpan profil untuk mengajukannya ke HR.
        </Notice>
      )}

      <GlassCard className="p-4 space-y-3" data-testid="profile-account-card">
        <div className="flex items-start gap-4">
          <div className="relative shrink-0">
            <button type="button" aria-label="Ganti foto profil" title="Ganti foto profil"
              className="w-20 h-20 rounded-full bg-[hsl(var(--primary)/0.1)] flex items-center justify-center overflow-hidden border-2 border-[hsl(var(--primary)/0.2)]"
              onClick={() => fileInputRef.current?.click()}>
              {uploading ? <Loader2 className="w-7 h-7 animate-spin text-primary" />
                : photoSrc ? <img src={photoSrc} alt="foto profil" className="w-full h-full object-cover" onError={() => setPreviewUrl(null)} />
                  : <User className="w-10 h-10 text-primary/50" />}
            </button>
            {previewUrl && !uploading && (
              <Button variant="outline" size="icon" onClick={removePhoto} title="Hapus foto" aria-label="Hapus foto"
                className="absolute -top-1 -right-1 h-6 w-6 rounded-full" data-testid="btn-remove-photo">
                <X className="w-3 h-3" />
              </Button>
            )}
          </div>
          <div className="flex-1 min-w-0 space-y-1">
            <p className="font-semibold text-base truncate">{profile?.name || user?.name}</p>
            <p className="text-sm text-muted-foreground truncate">{profile?.email}</p>
            {emp && (
              <p className="text-sm text-muted-foreground" data-testid="profile-employee-line">
                {[emp.employee_code, emp.department, emp.job_title || emp.position].filter(Boolean).join(' · ')}
              </p>
            )}
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <Button variant="outline" size="sm" onClick={() => fileInputRef.current?.click()} disabled={uploading}
                data-testid="btn-upload-photo">
                {uploading ? <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" /> : <Upload className="w-3.5 h-3.5 mr-1" />}
                {uploading ? 'Mengunggah…' : 'Unggah foto'}
              </Button>
              <StatusBadge tone={linked ? 'success' : 'warning'} label={linked ? 'Terhubung ke data karyawan' : 'Belum terhubung'}
                testId="profile-linked-badge" />
            </div>
            <p className="text-xs text-muted-foreground">JPG, PNG, atau WEBP, paling besar 5 MB.</p>
          </div>
        </div>
        <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={handlePhotoSelect}
          data-testid="input-photo-file" />
        {!emp && (
          <Notice tone="warning" icon={AlertCircle}>
            Akun belum terhubung ke data karyawan. Hubungi HR untuk menghubungkan akun Anda.
          </Notice>
        )}
      </GlassCard>

      <GlassCard className="p-4 space-y-3" data-testid="profile-personal-card">
        <div className="space-y-1.5">
          <Label htmlFor="pf-nick">Nama panggilan</Label>
          <GlassInput id="pf-nick" data-testid="input-nama-panggilan" value={form.nama_panggilan}
            onChange={e => set('nama_panggilan', e.target.value)} placeholder="Nama yang sering dipanggil" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="pf-hp" className="flex items-center gap-1"><Phone className="w-3.5 h-3.5" /> No. HP</Label>
          <GlassInput id="pf-hp" data-testid="input-no-hp" inputMode="tel" value={form.no_hp} disabled={contactLocked}
            onChange={e => set('no_hp', e.target.value)} placeholder="08xx-xxxx-xxxx" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="pf-addr" className="flex items-center gap-1"><MapPin className="w-3.5 h-3.5" /> Alamat tinggal</Label>
          <Textarea id="pf-addr" data-testid="input-alamat" rows={2} value={form.alamat} disabled={contactLocked}
            onChange={e => set('alamat', e.target.value)} placeholder="Alamat tinggal saat ini" className="resize-none" />
        </div>
      </GlassCard>

      <GlassCard className="p-4 space-y-3" data-testid="profile-emergency-card">
        <p className="text-sm font-semibold">Kontak darurat</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="pf-kd-name">Nama</Label>
            <GlassInput id="pf-kd-name" data-testid="input-kd-nama" value={form.kontak_darurat?.nama || ''}
              disabled={contactLocked} onChange={e => setKD('nama', e.target.value)} placeholder="Nama kontak" />
          </div>
          <div className="space-y-1.5">
            <Label>Hubungan</Label>
            <SmartNativeSelect value={relation} onChange={e => setKD('hubungan', e.target.value)} disabled={contactLocked}
              searchable={false} data-testid="input-kd-hubungan" className="w-full">
              <option value="">— Pilih hubungan —</option>
              {relationOptions.map(r => <option key={r} value={r}>{r}</option>)}
            </SmartNativeSelect>
          </div>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="pf-kd-hp">No. HP kontak</Label>
          <GlassInput id="pf-kd-hp" data-testid="input-kd-hp" inputMode="tel" value={form.kontak_darurat?.no_hp || ''}
            disabled={contactLocked} onChange={e => setKD('no_hp', e.target.value)} placeholder="08xx-xxxx-xxxx" />
        </div>
      </GlassCard>
    </PageLayout>
  );
}

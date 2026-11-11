/**
 * Portal Saya › Dokumen — dokumen pribadi karyawan dan dokumen yang diterbitkan HR.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout (dulu kepala berikon + `p-6`), daftar = TabelData (dulu kisi kartu)
 * + unduh Excel/CSV, form unggah = FormPopup, tanggal berlaku pakai DatePicker (dulu input tanggal bawaan),
 * status berlaku pakai StatusBadge (dulu warna hex). Unggah & unduh berkas tetap lewat jalur yang sama.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import { toast } from 'sonner';
import { Download, Loader2, Trash2, Upload } from 'lucide-react';
import { withFileAuth } from '@/lib/fileUrl';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { formatDateID } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatusBadge } from '../moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL || '';
// berkas unggahan disimpan relatif (`/api/files/...`, sama dengan Data Karyawan › Dokumen) — dibuka lewat
// asal yang sama (caddy meneruskan /api); tautan luar (https://...) dibuka apa adanya.

const DOC_TYPE_LABEL = {
  ktp: 'KTP',
  ijazah: 'Ijazah',
  sertifikat: 'Sertifikat',
  kontrak: 'Kontrak kerja',
  other: 'Lainnya',
};


export default function MyDocumentsModule({ token }) {
  const [documents, setDocuments] = useState([]);
  const [hrDocuments, setHrDocuments] = useState([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [showUploadDialog, setShowUploadDialog] = useState(false);
  const [formData, setFormData] = useState({ title: '', doc_type: 'other', description: '', file_url: '', file_name: '', expiry_date: '' });
  // Tahap 5 (2026-11-07): formulir "Upload Dokumen" dulu TIDAK punya pemilih berkas — hanya kotak URL & nama
  // berkas yang diketik, jadi karyawan tidak bisa mengunggah KTP/ijazah dari HP. Kini berkas diunggah lewat
  // `/api/upload` yang sama dengan Data Karyawan › Dokumen (ditautkan ke karyawannya, terlihat juga oleh HR).
  const [fileBusy, setFileBusy] = useState(false);
  const [myEmployeeId, setMyEmployeeId] = useState('');

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);

  const fetchDocuments = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/portal-saya/documents`, { headers });
      if (!r.ok) throw new Error(`kode ${r.status}`);
      const data = await r.json();
      setDocuments(data?.data?.my_documents || []);
      setHrDocuments(data?.data?.hr_issued || []);
    } catch (e) {
      toast.error(`Gagal memuat dokumen: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [headers]);

  useEffect(() => { fetchDocuments(); }, [fetchDocuments]);
  useEffect(() => {
    fetch(`${API}/api/portal-saya/me/employee`, { headers })
      .then(r => (r.ok ? r.json() : null)).then(d => setMyEmployeeId(d?.id || '')).catch(() => setMyEmployeeId(''));
  }, [headers]);

  const handleFile = async (file) => {
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) { toast.error('Ukuran berkas maksimal 10 MB'); return; }
    setFileBusy(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const r = await fetch(`${API}/api/upload?entity_type=employee&entity_id=${encodeURIComponent(myEmployeeId)}`, {
        method: 'POST', headers: { Authorization: headers.Authorization }, body: fd,
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || !d.storage_path) throw new Error(typeof d.detail === 'string' ? d.detail : 'Berkas gagal diunggah');
      setFormData(f => ({ ...f, file_url: `/api/files/${d.storage_path}`, file_name: d.original_filename || file.name,
        title: f.title || file.name.replace(/\.[^.]+$/, '') }));
      toast.success('Berkas terunggah');
    } catch (e) { toast.error(e.message); }
    finally { setFileBusy(false); }
  };

  const handleUpload = async () => {
    if (!formData.title) {
      toast.error('Judul dokumen harus diisi');
      return;
    }
    if (!formData.file_url) {
      toast.error('Pilih berkas atau isi tautan dokumen');
      return;
    }
    setUploading(true);
    try {
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/portal-saya/documents`, {
        method: 'POST',
        headers,
        body: JSON.stringify(formData),
      });
      if (!r.ok) throw new Error(`kode ${r.status}`);
      toast.success('Dokumen tersimpan.');
      setShowUploadDialog(false);
      setFormData({ title: '', doc_type: 'other', description: '', file_url: '', file_name: '', expiry_date: '' });
      fetchDocuments();
    } catch (e) {
      toast.error(`Gagal menyimpan dokumen: ${e.message}`);
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (docId) => {
    if (!(await confirmDialog({ title: 'Hapus dokumen ini?', confirmLabel: 'Hapus', danger: true }))) return;
    try {
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/portal-saya/documents/${docId}`, {
        method: 'DELETE',
        headers,
      });
      if (!r.ok) throw new Error(`kode ${r.status}`);
      toast.success('Dokumen dihapus');
      fetchDocuments();
    } catch (e) {
      toast.error(`Hapus gagal: ${e.message}`);
    }
  };

  const isExpiringSoon = (expiryDate) => {
    if (!expiryDate) return false;
    const exp = new Date(expiryDate);
    const now = new Date();
    const diffDays = Math.ceil((exp - now) / (1000 * 60 * 60 * 24));
    return diffDays >= 0 && diffDays <= 30;
  };

  const isExpired = (expiryDate) => {
    if (!expiryDate) return false;
    return new Date(expiryDate) < new Date();
  };

  const statusBerlaku = (doc) => (!doc.expiry_date ? null
    : isExpired(doc.expiry_date) ? { label: 'Kedaluwarsa', tone: 'danger' }
      : isExpiringSoon(doc.expiry_date) ? { label: 'Segera habis', tone: 'warning' } : { label: 'Berlaku', tone: 'success' });
  const tgl = (v) => (v ? formatDateID(String(v).slice(0, 10)) : '—');
  const buka = (doc) => window.open(withFileAuth(doc.file_url), '_blank');

  const kolomSaya = [
    { kunci: 'title', label: 'Dokumen', hp: 'judul', isi: (doc) => (
      <div className="min-w-0 md:max-w-[20rem]">
        <p className="font-medium">{doc.title}</p>
        {doc.description && <p className="line-clamp-1 text-xs text-muted-foreground">{doc.description}</p>}
      </div>) },
    { kunci: 'jenis', label: 'Jenis', isi: (doc) => DOC_TYPE_LABEL[doc.doc_type] || doc.doc_type || '—' },
    { kunci: 'berkas', label: 'Berkas', isi: (doc) => <span className="block max-w-[14rem] truncate text-sm text-muted-foreground">{doc.file_name || '—'}</span> },
    { kunci: 'berlaku', label: 'Berlaku s/d', isi: (doc) => {
      const s = statusBerlaku(doc);
      return s ? <span className="inline-flex flex-wrap items-center gap-1.5 text-sm">{tgl(doc.expiry_date)} <StatusBadge status={s.tone} label={s.label} tone={s.tone} /></span> : '—';
    } },
    { kunci: 'diunggah', label: 'Diunggah', isi: (doc) => <span className="whitespace-nowrap text-sm">{tgl(doc.created_at)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (doc) => (
      <div className="flex justify-end gap-1">
        {doc.file_url && <Button size="sm" variant="outline" onClick={() => buka(doc)}><Download />Unduh</Button>}
        <Button size="icon-sm" variant="ghost" onClick={() => handleDelete(doc.id)} title="Hapus dokumen" aria-label="Hapus dokumen"><Trash2 /></Button>
      </div>) },
  ];

  return (
    <PageLayout testId="my-documents-module" title="Dokumen"
      subtitle="Simpan dokumen pribadi (KTP, ijazah, sertifikat, kontrak) dan unduh dokumen yang diterbitkan HR."
      actions={<Button onClick={() => setShowUploadDialog(true)} data-testid="mydoc-upload-btn"><Upload />Unggah dokumen</Button>}
      tools={documents.length > 0 && (
        <TombolUnduh namaBerkas="dokumen-saya" namaLembar="Dokumen" baris={documents} testId="mydoc-unduh" kolom={[
          { label: 'Judul', nilai: (d) => d.title }, { label: 'Jenis', nilai: (d) => DOC_TYPE_LABEL[d.doc_type] || d.doc_type || '' },
          { label: 'Berkas', nilai: (d) => d.file_name || '' }, { label: 'Keterangan', nilai: (d) => d.description || '' },
          { label: 'Berlaku s/d', nilai: (d) => (d.expiry_date ? tgl(d.expiry_date) : '') },
          { label: 'Status', nilai: (d) => statusBerlaku(d)?.label || '' }, { label: 'Diunggah', nilai: (d) => tgl(d.created_at) },
        ]} />
      )}>
      <GlassCard className="space-y-3 p-4">
        <h3 className="text-lg font-semibold text-foreground">Dokumen pribadi ({documents.length})</h3>
        {loading && documents.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">Memuat dokumen…</p>
        ) : (
          <TabelData kolom={kolomSaya} baris={documents} testId="mydoc-table"
            kosong={<EmptyState title="Belum ada dokumen yang diunggah" description="Tekan Unggah dokumen untuk menyimpan KTP, ijazah, atau sertifikat Anda." />} />
        )}
      </GlassCard>

      {hrDocuments.length > 0 && (
        <GlassCard className="space-y-3 p-4">
          <h3 className="text-lg font-semibold text-foreground">Dokumen dari HR ({hrDocuments.length})</h3>
          <TabelData baris={hrDocuments} testId="mydoc-hr-table" kolom={[
            { kunci: 'title', label: 'Dokumen', hp: 'judul', isi: (doc) => <span className="font-medium">{doc.title || doc.document_type}</span> },
            { kunci: 'terbit', label: 'Diterbitkan', isi: (doc) => <span className="whitespace-nowrap">{tgl(doc.issued_at)}</span> },
            { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (doc) => (doc.file_url
              ? <Button size="sm" variant="outline" onClick={() => window.open(withFileAuth(doc.file_url), '_blank')}><Download />Unduh</Button> : null) },
          ]} />
        </GlassCard>
      )}

      {/* Unggah dokumen */}
      <FormPopup open={showUploadDialog} onClose={() => setShowUploadDialog(false)} ukuran="pendek" testId="mydoc-form"
        judul="Unggah dokumen" keterangan="Dokumen tersimpan di data karyawan Anda dan bisa dilihat HR."
        onSimpan={handleUpload} menyimpan={uploading} labelSimpan="Simpan dokumen">
        <Isian label="Judul dokumen" wajib htmlFor="mydoc-title">
          <Input id="mydoc-title" placeholder="Misal: KTP asli" value={formData.title} onChange={e => setFormData({ ...formData, title: e.target.value })} />
        </Isian>
        <Isian label="Jenis dokumen">
          <SmartNativeSelect value={formData.doc_type} searchable={false} className="w-full"
            onChange={(e) => setFormData({ ...formData, doc_type: e.target.value })}>
            {Object.entries(DOC_TYPE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Keterangan (opsional)" htmlFor="mydoc-desc">
          <Textarea id="mydoc-desc" placeholder="Catatan tambahan…" value={formData.description} rows={2}
            onChange={e => setFormData({ ...formData, description: e.target.value })} />
        </Isian>
        <Isian label="Berkas" wajib petunjuk="Foto atau PDF, maksimal 10 MB.">
          <div className="flex flex-wrap items-center gap-2">
            <label className="inline-flex">
              <input type="file" className="hidden" accept="image/*,application/pdf" data-testid="mydoc-file"
                onChange={e => { handleFile(e.target.files?.[0]); e.target.value = ''; }} />
              <Button type="button" variant="outline" disabled={fileBusy}
                onClick={ev => ev.currentTarget.parentElement.querySelector('input').click()}>
                {fileBusy ? <Loader2 className="animate-spin" /> : <Upload />}
                {formData.file_name ? 'Ganti berkas' : 'Pilih berkas'}
              </Button>
            </label>
            <span className="min-w-0 truncate text-sm text-muted-foreground" data-testid="mydoc-file-name">{formData.file_name || 'Belum ada berkas'}</span>
          </div>
        </Isian>
        <Isian label="Atau tautan dokumen (opsional)" htmlFor="mydoc-url">
          <Input id="mydoc-url" placeholder="https://…" value={formData.file_url.startsWith('/api/') ? '' : formData.file_url}
            onChange={e => setFormData({ ...formData, file_url: e.target.value, file_name: formData.file_url.startsWith('/api/') ? '' : formData.file_name })} />
        </Isian>
        <Isian label="Berlaku sampai (opsional)">
          <DatePicker value={formData.expiry_date} onChange={(v) => setFormData({ ...formData, expiry_date: v || '' })}
            bolehKosong placeholder="Tanpa batas" pilihTahun testId="mydoc-expiry" />
        </Isian>
      </FormPopup>
    </PageLayout>
  );
}

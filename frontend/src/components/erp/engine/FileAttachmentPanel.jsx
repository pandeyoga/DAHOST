
import { useState, useEffect, useRef } from 'react';
import { Paperclip, Upload, Trash2, Download, File, FileImage, FileSpreadsheet, Archive } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { apiGet, apiPost, apiDelete, getToken } from '../../../lib/api';

function getFileIcon(ext) {
  if (['jpg','jpeg','png','webp','gif'].includes(ext)) return <FileImage className="w-4 h-4 text-[hsl(var(--primary))]" />;
  if (['xlsx','xls','csv'].includes(ext)) return <FileSpreadsheet className="w-4 h-4 text-[hsl(var(--success))]" />;
  if (['zip','rar'].includes(ext)) return <Archive className="w-4 h-4 text-[hsl(var(--warning))]" />;
  return <File className="w-4 h-4 text-muted-foreground" />;
}

// 2026-11-06 (pola P1): bentuk lampiran dari server = `attachments` (file_storage.py):
// original_filename, storage_path, created_at. Dulu layar membaca original_name / file_ext /
// uploaded_at / public_path yang tidak pernah ada → nama kosong & tombol unduh mati.
const attName = (a) => a.original_filename || a.original_name || '';
const attExt = (a) => (attName(a).split('.').pop() || '').toLowerCase();
const attUrl = (a) => (a.storage_path
  ? `/api/files/${a.storage_path}?auth=${encodeURIComponent(getToken() || '')}` : undefined);

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

export default function FileAttachmentPanel({ token, entityType, entityId, userRole }) {
  const [attachments, setAttachments] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef();

  const isSuperAdmin = userRole === 'superadmin';

  useEffect(() => {
    if (entityId) fetchAttachments();
  }, [entityId]);

  const fetchAttachments = async () => {
    try {
      const data = await apiGet(`/attachments?entity_type=${entityType}&entity_id=${entityId}`);
      setAttachments(Array.isArray(data) ? data : []);
    } catch (e) { console.error(e); setAttachments([]); }
  };

  const uploadFile = async (file) => {
    setUploading(true);
    const formData = new FormData();
    formData.append('file', file);
    try {
      // 2026-11-06 (pola P1): server membaca entity_type/entity_id dari QUERY, bukan isian form —
      // dulu lampiran tersimpan tanpa tautan dokumen sehingga tidak pernah muncul di daftar.
      const qs = `entity_type=${encodeURIComponent(entityType)}&entity_id=${encodeURIComponent(entityId)}`;
      const data = await apiPost(`/upload?${qs}`, formData);
      setAttachments(prev => [...prev, data]);
    } catch (e) {
      toast.error('Unggah gagal: ' + e.message);
    } finally {
      setUploading(false);
    }
  };

  const handleFileChange = (e) => {
    const files = Array.from(e.target.files || []);
    files.forEach(uploadFile);
    e.target.value = '';
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const files = Array.from(e.dataTransfer.files || []);
    files.forEach(uploadFile);
  };

  const handleDelete = async (att) => {
    if (!(await confirmDialog({ title: `Hapus file "${attName(att)}"?`, confirmLabel: 'Hapus', danger: true }))) return;
    try {
      // 2026-11-06 (pola P1): rute hapus = DELETE /api/attachments/{id} (dulu /upload?id= → 405)
      await apiDelete(`/attachments/${att.id}`);
      setAttachments(prev => prev.filter(a => a.id !== att.id));
    } catch (e) {
      toast.error(e.message || 'Gagal menghapus');
    }
  };

  if (!entityId) {
    return (
      <div className="border border-dashed border-border rounded-lg p-4 text-center text-sm text-muted-foreground/70">
        Simpan record terlebih dahulu untuk menambahkan lampiran.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold text-foreground/90 flex items-center gap-2">
          <Paperclip className="w-4 h-4" /> Lampiran ({attachments.length})
        </h4>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
        >
          <Upload className="w-3.5 h-3.5" />
          {uploading ? 'Mengunggah...' : 'Unggah file'}
        </Button>
        <input ref={fileInputRef} type="file" multiple className="hidden" onChange={handleFileChange}
          accept=".pdf,.jpg,.jpeg,.png,.webp,.xlsx,.xls,.zip" />
      </div>

      {/* Tahap 9: zona seret tanpa kartu — panel ini dipakai di dalam rincian (DetailPanel), tidak boleh kartu di dalam kartu */}
      <div
        className={`rounded-lg border-2 border-dashed border-border p-3 text-center text-xs transition-colors ${
          dragOver ? 'border-[hsl(var(--primary)/0.35)]' : ''
        }`}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
      >
        <Upload className="w-4 h-4 mx-auto mb-1 text-muted-foreground/70" />
        <span className="text-muted-foreground/70">Seret & lepas file di sini atau klik tombol Unggah file</span>
        <br />
        <span className="text-muted-foreground/50">PDF, JPG, PNG, XLSX, ZIP — maks. 10MB</span>
      </div>

      {attachments.length > 0 && (
        <div className="divide-y divide-border">
          {attachments.map(att => (
            <div key={att.id} className="flex items-center gap-2 py-2">
              {getFileIcon(attExt(att))}
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium text-foreground/90 truncate">{attName(att)}</p>
                <p className="text-xs text-muted-foreground/70">{formatSize(att.size)} • {new Date(att.created_at || att.uploaded_at).toLocaleDateString('id-ID')} • {att.uploaded_by}</p>
              </div>
              <a
                href={attUrl(att)}
                target="_blank"
                rel="noopener noreferrer"
                className="p-1 rounded hover:bg-[hsl(var(--primary)/0.1)] text-[hsl(var(--primary))]"
                title="Unduh"
                aria-label="Unduh"
              >
                <Download className="w-3.5 h-3.5" />
              </a>
              <Button type="button" variant="ghost" size="icon-sm" onClick={() => handleDelete(att)}
                className="text-[hsl(var(--destructive))]" title="Hapus" aria-label="Hapus">
                <Trash2 className="w-3.5 h-3.5" />
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

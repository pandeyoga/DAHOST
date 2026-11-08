/**
 * VersionHistoryDrawer — daftar versi tersimpan sebuah dokumen, bisa dipulihkan.
 *
 * Versi terbaru diberi tanda "Terbaru" dan tidak bisa dipulihkan (sudah berlaku). Versi lama punya tombol Pulihkan.
 * Standar UI/UX v2 (8 Nov 2026): DetailPopup + tabel standar (bisa diunduh); pulihkan lewat konfirmasi aplikasi.
 */
import { useState, useEffect } from 'react';
import { toast } from 'sonner';
import { Loader2, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import DetailPopup from '@/components/ui/detail-popup';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { EmptyState, StatusBadge } from '../moduleAtoms';

import { apicall, fmtIso } from './utils';

export default function VersionHistoryDrawer({ open, onClose, docId, token, onRestored }) {
  const [versions, setVersions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [restoring, setRestoring] = useState(null);

  useEffect(() => {
    if (open && docId) {
      setLoading(true);
      apicall('GET', `/api/workspace/documents/${docId}/versions`, token)
        .then(setVersions)
        .catch(() => toast.error('Gagal memuat versi'))
        .finally(() => setLoading(false));
    }
  }, [open, docId, token]);

  const handleRestore = async (v) => {
    if (!(await confirmDialog({ title: `Pulihkan ke "${v.label}"?`, body: 'Perubahan yang belum disimpan akan hilang.', confirmLabel: 'Pulihkan' }))) return;
    setRestoring(v.id);
    try {
      await apicall('POST', `/api/workspace/documents/${docId}/versions/${v.id}/restore`, token, {});
      toast.success(`Berhasil dipulihkan ke ${v.label}`);
      onRestored();
      onClose();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setRestoring(null);
    }
  };

  const kolom = [
    { kunci: 'label', label: 'Versi', hp: 'judul', isi: (v) => (
      <span className="inline-flex items-center gap-2"><span className="font-medium">{v.label}</span>
        {versions[0]?.id === v.id && <StatusBadge status="terbaru" label="Terbaru" tone="primary" />}</span>) },
    { kunci: 'waktu', label: 'Disimpan', isi: (v) => <span className="whitespace-nowrap">{fmtIso(v.saved_at)}</span> },
    { kunci: 'oleh', label: 'Oleh', isi: (v) => v.saved_by_name || '—' },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (v) => (versions[0]?.id === v.id ? null : (
      <Button variant="outline" size="sm" disabled={restoring === v.id} onClick={() => handleRestore(v)}
        data-testid={`restore-version-${versions.indexOf(v)}`}>
        {restoring === v.id ? <Loader2 className="animate-spin" /> : <RotateCcw />}Pulihkan
      </Button>)) },
  ];

  return (
    <DetailPopup open={open} onClose={onClose} judul="Riwayat versi" testId="version-history-dialog"
      keterangan="Versi dibuat setiap kali dokumen disimpan."
      aksi={<TombolUnduh namaBerkas="riwayat-versi" namaLembar="Versi" baris={versions} testId="version-unduh"
        kolom={[{ label: 'Versi', nilai: (v) => v.label }, { label: 'Disimpan', nilai: (v) => fmtIso(v.saved_at) },
          { label: 'Oleh', nilai: (v) => v.saved_by_name || '' }]} />}>
      {loading ? (
        <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
      ) : (
        <TabelData kolom={kolom} baris={versions} testId="version-table"
          kosong={<EmptyState title="Belum ada versi tersimpan" description='Klik "Simpan" di editor untuk membuat versi.' className="py-8" />} />
      )}
    </DetailPopup>
  );
}

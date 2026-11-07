/**
 * NewDocForm — form "Spreadsheet baru" (Standar UI/UX v2: FormPopup pendek; dulu isian di dalam Dialog biasa).
 * Props: { open, token, onCreated(doc), onClose }.
 */
import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Input } from '@/components/ui/input';
import FormPopup, { Isian } from '@/components/ui/form-popup';

import { apicall } from './utils';

export default function NewDocForm({ open = true, token, onCreated, onClose }) {
  const [name, setName] = useState('');
  const [loading, setLoading] = useState(false);
  useEffect(() => { if (open) setName(''); }, [open]);

  const handleCreate = async () => {
    if (!name.trim()) { toast.error('Nama dokumen wajib diisi'); return; }
    setLoading(true);
    try {
      const doc = await apicall('POST', '/api/workspace/documents', token, { name: name.trim() });
      toast.success('Spreadsheet baru dibuat');
      onCreated(doc);
    } catch (e) {
      toast.error(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <FormPopup open={open} onClose={onClose} ukuran="pendek" judul="Spreadsheet baru" testId="new-doc-dialog"
      onSimpan={handleCreate} menyimpan={loading} bisaSimpan={!!name.trim()} labelSimpan="Buat">
      <Isian label="Nama spreadsheet" wajib htmlFor="new-doc-name">
        <Input id="new-doc-name" placeholder="Mis. Rekap order November" value={name} onChange={(e) => setName(e.target.value)}
          autoFocus data-testid="new-doc-name-input" />
      </Isian>
    </FormPopup>
  );
}

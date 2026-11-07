/**
 * AddColumnDialog + ManageColumnsDialog — kelola kolom spreadsheet.
 *
 * Standar UI/UX v2 (8 Nov 2026): tambah kolom = FormPopup pendek; kelola kolom = DetailPopup berisi tabel standar;
 * hapus kolom lewat konfirmasi aplikasi (dulu window.confirm). Tambah kolom membuka form di atas daftar kolom
 * diganti: daftar disembunyikan sementara selama form terbuka (tidak ada popup bertumpuk).
 */
import { useState } from 'react';
import { toast } from 'sonner';
import { Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup from '@/components/ui/detail-popup';
import TabelData from '@/components/ui/tabel-data';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { EmptyState } from '../moduleAtoms';

const TIPE = { text: 'Teks', number: 'Angka' };

export function AddColumnDialog({ open, onClose, onAdd }) {
  const [name, setName] = useState('');
  const [type, setType] = useState('text');

  const handleAdd = () => {
    if (!name.trim()) { toast.error('Nama kolom wajib diisi'); return; }
    const key = `${name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') || 'col'}_${Date.now()}`;
    onAdd({ key, name: name.trim(), type, editable: true, width: 160 });
    setName(''); setType('text'); onClose();
  };

  return (
    <FormPopup open={open} onClose={onClose} ukuran="pendek" judul="Tambah kolom" onSimpan={handleAdd}
      labelSimpan="Tambah" testId="add-column-dialog">
      <Isian label="Nama kolom" wajib htmlFor="add-column-name">
        <Input id="add-column-name" placeholder="Contoh: Jumlah, Keterangan" value={name} onChange={(e) => setName(e.target.value)}
          autoFocus data-testid="add-column-name" />
      </Isian>
      <Isian label="Tipe data">
        <SmartNativeSelect value={type} onChange={(e) => setType(e.target.value)} searchable={false} className="h-9 w-full"
          aria-label="Tipe data" data-testid="add-column-type">
          <option value="text">Teks</option>
          <option value="number">Angka</option>
        </SmartNativeSelect>
      </Isian>
    </FormPopup>
  );
}

export function ManageColumnsDialog({ open, onClose, columns, onDelete, onAdd }) {
  const [showAdd, setShowAdd] = useState(false);
  const hapus = async (col) => {
    if (await confirmDialog({ title: `Hapus kolom "${col.name}"?`, body: 'Isi kolom ini di semua baris ikut hilang.', confirmLabel: 'Hapus', danger: true })) {
      onDelete(col.key);
    }
  };
  const kolom = [
    { kunci: 'nama', label: 'Kolom', hp: 'judul', isi: (c) => <span className="font-medium">{c.name}</span> },
    { kunci: 'tipe', label: 'Tipe', isi: (c) => TIPE[c.type || 'text'] || c.type },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (c) => (
      <Button variant="ghost" size="icon-sm" onClick={() => hapus(c)} title="Hapus kolom" aria-label="Hapus kolom"
        data-testid={`delete-col-${columns.indexOf(c)}`}><Trash2 /></Button>) },
  ];
  return (
    <>
      <DetailPopup open={open && !showAdd} onClose={onClose} judul="Kelola kolom" testId="manage-columns-dialog"
        keterangan={`${columns.length} kolom di spreadsheet ini.`}
        aksi={<Button size="sm" onClick={() => setShowAdd(true)} data-testid="open-add-column"><Plus />Tambah kolom</Button>}>
        <TabelData kolom={kolom} baris={columns} kunci={(c) => c.key} testId="manage-columns-table"
          kosong={<EmptyState title="Belum ada kolom" description="Tambah kolom pertama untuk mulai mengisi data." className="py-8" />} />
      </DetailPopup>
      <AddColumnDialog open={open && showAdd} onClose={() => setShowAdd(false)} onAdd={(col) => { onAdd(col); setShowAdd(false); }} />
    </>
  );
}

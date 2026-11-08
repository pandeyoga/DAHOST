/**
 * ImportFromModuleDialog — impor data modul sistem (Manajemen Aset atau Pengadaan) ke spreadsheet baru.
 * Pengguna memilih modul sumber, nama dokumen, saringan status/departemen (opsional), dan kolom yang ikut.
 *
 * Standar UI/UX v2 (8 Nov 2026): FormPopup pendek (dulu Dialog buatan sendiri); isian & panggilan server sama.
 */
import { useState, useEffect } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FormPopup, { Isian } from '@/components/ui/form-popup';

import {
  apicall, ASSET_FIELDS, PROCUREMENT_FIELDS, DEF_ASSET_FIELDS, DEF_PR_FIELDS,
} from './utils';

export default function ImportFromModuleDialog({ open, onClose, token, onImported }) {
  const [module, setModule] = useState('assets');
  const [docName, setDocName] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [deptFilter, setDeptFilter] = useState('');
  const [selFields, setSelFields] = useState(DEF_ASSET_FIELDS);
  const [importing, setImporting] = useState(false);

  const allFields = module === 'assets' ? ASSET_FIELDS : PROCUREMENT_FIELDS;

  useEffect(() => {
    setSelFields(module === 'assets' ? DEF_ASSET_FIELDS : DEF_PR_FIELDS);
    setStatusFilter('');
    setDeptFilter('');
  }, [module]);

  const handleImport = async () => {
    if (selFields.length === 0) { toast.error('Pilih minimal satu kolom'); return; }
    setImporting(true);
    try {
      const filters = {};
      if (statusFilter) filters.status = statusFilter;
      if (deptFilter) filters.department = deptFilter;
      const data = await apicall('POST', '/api/workspace/documents/import-from-module', token, {
        module, name: docName || undefined, filters, fields: selFields,
      });
      toast.success(`${data.imported_count} data berhasil diimpor ke "${data.name}"`);
      onImported(data);
      onClose();
    } catch (e) {
      toast.error(e.message || 'Impor gagal');
    } finally {
      setImporting(false);
    }
  };

  return (
    <FormPopup open={open} onClose={onClose} ukuran="pendek" testId="import-module-dialog"
      judul="Impor dari modul sistem" keterangan="Data modul disalin ke spreadsheet baru."
      onSimpan={handleImport} menyimpan={importing} bisaSimpan={selFields.length > 0}
      labelSimpan={`Impor ${module === 'assets' ? 'aset' : 'pengadaan'}`}>
      <Isian label="Modul sumber">
        <SmartNativeSelect value={module} onChange={(e) => setModule(e.target.value)} searchable={false}
          className="h-9 w-full" aria-label="Modul sumber" data-testid="import-module-select">
          <option value="assets">Manajemen Aset</option>
          <option value="procurement">Pengadaan (PR)</option>
        </SmartNativeSelect>
      </Isian>
      <Isian label="Nama dokumen" petunjuk="Kosongkan untuk nama otomatis." htmlFor="import-doc-name">
        <Input id="import-doc-name" value={docName} onChange={(e) => setDocName(e.target.value)} data-testid="import-doc-name" />
      </Isian>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Isian label="Saring status" htmlFor="import-status">
          <Input id="import-status" placeholder="Semua status" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} />
        </Isian>
        <Isian label="Saring departemen" htmlFor="import-dept">
          <Input id="import-dept" placeholder="Semua departemen" value={deptFilter} onChange={(e) => setDeptFilter(e.target.value)} />
        </Isian>
      </div>
      <Isian label="Kolom yang diimpor">
        <div className="mb-1 flex justify-end">
          <Button type="button" variant="ghost" size="sm" onClick={() => setSelFields(allFields.map((f) => f.key))}>Pilih semua</Button>
        </div>
        <div className="grid max-h-48 grid-cols-1 gap-1 overflow-y-auto rounded-md border border-[var(--glass-border)] p-2 sm:grid-cols-2">
          {allFields.map((f) => (
            <label key={f.key} className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 text-sm hover:bg-foreground/5">
              <Checkbox checked={selFields.includes(f.key)}
                onCheckedChange={() => setSelFields((prev) => (prev.includes(f.key) ? prev.filter((k) => k !== f.key) : [...prev, f.key]))} />
              {f.label}
            </label>
          ))}
        </div>
      </Isian>
    </FormPopup>
  );
}

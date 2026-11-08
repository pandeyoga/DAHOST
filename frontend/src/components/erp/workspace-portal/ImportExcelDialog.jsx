/**
 * ImportExcelDialog — impor Excel 2 langkah (pratinjau → pemetaan kolom → impor).
 *
 * Langkah 1: unggah .xlsx/.xls → server mengirim usulan kolom + contoh baris.
 * Langkah 2: pengguna boleh mengganti nama kolom, tipe, dan memilih kolom yang ikut, lalu impor.
 *
 * Standar UI/UX v2 (8 Nov 2026): FormPopup panjang (dulu Dialog + tabel buatan sendiri); alur & panggilan sama.
 */
import { useState, useRef } from 'react';
import { toast } from 'sonner';
import { ArrowLeft, FileSpreadsheet, Loader2, Upload } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

import { API, apicall } from './utils';

export default function ImportExcelDialog({ open, onClose, token, onImported }) {
  const [step, setStep] = useState(1);   // 1 = unggah, 2 = pemetaan
  const [preview, setPreview] = useState(null);   // { columns, preview_rows, total_rows, file_name }
  const [mapping, setMapping] = useState([]);     // [{ original_name, key, name, type, include }]
  const [docName, setDocName] = useState('');
  const [fileData, setFileData] = useState(null); // base64
  const [uploading, setUploading] = useState(false);
  const [importing, setImporting] = useState(false);
  const fileRef = useRef(null);

  const reset = () => {
    setStep(1); setPreview(null); setMapping([]);
    setDocName(''); setFileData(null);
  };

  const handleFileSelect = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.match(/\.xlsx?$/i)) { toast.error('File harus .xlsx atau .xls'); return; }
    setUploading(true);
    try {
      const fd = new FormData(); fd.append('file', file);
      const res = await fetch(`${API}/api/workspace/documents/preview-excel`, {
        method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: fd,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Pratinjau gagal');
      setPreview(data);
      setDocName(file.name.replace(/\.[^.]+$/, ''));
      setMapping(data.columns.map((c) => ({ ...c, key: c.suggested_key, name: c.suggested_name })));
      // Juga dibaca sebagai base64 untuk impor akhir
      const reader = new FileReader();
      reader.onload = () => setFileData(reader.result.split(',')[1]);
      reader.readAsDataURL(file);
      setStep(2);
    } catch (err) {
      toast.error(err.message || 'Unggah gagal');
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const handleImport = async () => {
    const included = mapping.filter((m) => m.include);
    if (included.length === 0) { toast.error('Pilih minimal satu kolom'); return; }
    setImporting(true);
    try {
      const doc = await apicall('POST', '/api/workspace/documents/import-excel-mapped', token, {
        file_data: fileData, column_mapping: mapping,
        doc_name: docName || 'Import Excel',
      });
      toast.success(`${doc.content?.rows?.length || 0} baris berhasil diimpor ke "${doc.name}"`);
      onImported(doc); onClose(); reset();
    } catch (err) {
      toast.error(err.message || 'Impor gagal');
    } finally {
      setImporting(false);
    }
  };

  const updateMapping = (idx, field, value) => {
    setMapping((prev) => prev.map((m, i) => (i === idx ? { ...m, [field]: value } : m)));
  };
  const terpilih = mapping.filter((m) => m.include);
  const tutup = () => { onClose(); reset(); };

  return (
    <FormPopup open={open} onClose={tutup} ukuran="panjang" testId="import-excel-dialog"
      judul={`Impor Excel · langkah ${step} dari 2`}
      keterangan={step === 1 ? 'Pilih berkas .xlsx atau .xls; kolom dan contoh datanya ditampilkan dulu sebelum diimpor.'
        : 'Atur nama dan tipe tiap kolom, lalu impor.'}
      onSimpan={handleImport} menyimpan={importing} bisaSimpan={step === 2 && terpilih.length > 0}
      labelSimpan={step === 2 ? `Impor ${terpilih.length} kolom` : 'Impor'}
      aksiKiri={step === 2 && (
        <Button type="button" variant="outline" onClick={() => { setStep(1); setPreview(null); }} disabled={importing}>
          <ArrowLeft />Kembali
        </Button>
      )}>
      {step === 1 && (
        <div className="flex flex-col items-center justify-center gap-3 py-8 text-center">
          <FileSpreadsheet className="h-10 w-10 text-primary" />
          <div>
            <p className="text-sm font-medium text-foreground">Pilih berkas Excel untuk diimpor</p>
            <p className="mt-1 text-sm text-muted-foreground">Format yang didukung: .xlsx, .xls</p>
          </div>
          <Button type="button" onClick={() => fileRef.current?.click()} disabled={uploading} data-testid="excel-file-btn">
            {uploading ? <Loader2 className="animate-spin" /> : <Upload />}
            {uploading ? 'Membaca berkas…' : 'Pilih berkas Excel'}
          </Button>
          <input ref={fileRef} type="file" accept=".xlsx,.xls" onChange={handleFileSelect} className="hidden" />
        </div>
      )}

      {step === 2 && preview && (
        <>
          <p className="text-sm text-muted-foreground">
            <b className="text-foreground">{preview.file_name}</b> · {preview.total_rows} baris data · {preview.columns.length} kolom
          </p>
          <Isian label="Nama dokumen" htmlFor="excel-doc-name">
            <Input id="excel-doc-name" value={docName} onChange={(e) => setDocName(e.target.value)}
              placeholder="Nama spreadsheet" data-testid="excel-doc-name" />
          </Isian>
          <div className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-medium text-foreground">Pemetaan kolom</p>
              <div className="flex gap-1">
                <Button type="button" variant="ghost" size="sm" onClick={() => setMapping((prev) => prev.map((m) => ({ ...m, include: true })))}>Pilih semua</Button>
                <Button type="button" variant="ghost" size="sm" onClick={() => setMapping((prev) => prev.map((m) => ({ ...m, include: false })))}>Kosongkan</Button>
              </div>
            </div>
            <div className="overflow-x-auto">
              <Table className="min-w-[560px]">
                <TableHeader><TableRow>
                  <TableHead className="w-14">Impor</TableHead><TableHead>Kolom Excel</TableHead><TableHead>Nama di spreadsheet</TableHead>
                  <TableHead className="w-32">Tipe</TableHead><TableHead>Contoh data</TableHead>
                </TableRow></TableHeader>
                <TableBody>
                  {mapping.map((m, idx) => (
                    <TableRow key={idx} className={!m.include ? 'opacity-50' : ''}>
                      <TableCell><Checkbox checked={m.include} onCheckedChange={(v) => updateMapping(idx, 'include', !!v)} aria-label="Impor kolom ini" /></TableCell>
                      <TableCell className="max-w-[10rem] truncate text-muted-foreground" title={m.original_name}>{m.original_name}</TableCell>
                      <TableCell><Input value={m.name} onChange={(e) => updateMapping(idx, 'name', e.target.value)} className="h-8" disabled={!m.include} aria-label="Nama kolom" /></TableCell>
                      <TableCell>
                        <SmartNativeSelect value={m.type} onChange={(e) => updateMapping(idx, 'type', e.target.value)} disabled={!m.include}
                          searchable={false} className="h-8 w-full" aria-label="Tipe kolom">
                          <option value="text">Teks</option>
                          <option value="number">Angka</option>
                        </SmartNativeSelect>
                      </TableCell>
                      <TableCell className="max-w-[10rem] truncate text-muted-foreground">{preview.preview_rows[0]?.[m.original_name] || '—'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
          <div className="space-y-2">
            <p className="text-sm font-medium text-foreground">Contoh data (10 baris pertama)</p>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader><TableRow>
                  {terpilih.map((m) => <TableHead key={m.original_name} className="whitespace-nowrap">{m.name}</TableHead>)}
                </TableRow></TableHeader>
                <TableBody>
                  {preview.preview_rows.map((row, ri) => (
                    <TableRow key={ri}>
                      {terpilih.map((m) => (
                        <TableCell key={m.original_name} className="max-w-[10rem] truncate whitespace-nowrap">{row[m.original_name] || ''}</TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        </>
      )}
    </FormPopup>
  );
}

/**
 * BulkImportDialog — impor aset dari CSV/Excel: unggah, cocokkan kolom, hasil.
 *
 * Standar UI/UX v2 (8 Nov 2026): popup form standar ukuran panjang; tombol kaki = Batal · Impor (hijau);
 * langkah ditulis dengan token warna (dulu hijau/emerald buatan sendiri); istilah Inggris (Bulk Import,
 * Upload, Column Mapping, Download Template) → bahasa Indonesia; hasil memakai kartu angka standar, tanpa emoji.
 * Alur, endpoint, dan pemetaan kolom tidak berubah.
 */
import { useState, useEffect, useRef } from 'react';
import { Download, Upload } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { StatTile } from '../../moduleAtoms';
import { API } from '../utils';

const LANGKAH = ['Unggah berkas', 'Cocokkan kolom', 'Hasil'];

export function BulkImportDialog({ open, onClose, token, categories, onImported }) {
  const [step, setStep] = useState(1); // 1=upload, 2=mapping, 3=result
  const [loading, setLoading] = useState(false);
  const [previewData, setPreviewData] = useState(null); // { columns, preview, total_rows }
  const [mapping, setMapping] = useState({});  // assetField → csvColumn
  const [categoryId, setCategoryId] = useState('');
  const [result, setResult] = useState(null);
  const [rawRows, setRawRows] = useState([]); // eslint-disable-line no-unused-vars
  const [galat, setGalat] = useState('');
  const fileRef = useRef(null);

  const ASSET_FIELDS = [
    { key: 'name', label: 'Nama aset', required: true },
    { key: 'purchase_date', label: 'Tanggal beli (TTTT-BB-HH)', required: true },
    { key: 'purchase_cost', label: 'Harga beli', required: true },
    { key: 'useful_life_months', label: 'Umur manfaat (bulan)' },
    { key: 'residual_value', label: 'Nilai residu' },
    { key: 'serial_number', label: 'No. seri' },
    { key: 'brand', label: 'Merek' },
    { key: 'model', label: 'Model' },
    { key: 'location', label: 'Lokasi' },
    { key: 'department', label: 'Departemen' },
    { key: 'notes', label: 'Catatan' },
    { key: 'warranty_expiry_date', label: 'Garansi berakhir' },
    { key: 'warranty_provider', label: 'Penyedia garansi' },
    { key: 'insurance_policy_number', label: 'Nomor polis asuransi' },
    { key: 'insurance_provider', label: 'Penyedia asuransi' },
    { key: 'insurance_expiry_date', label: 'Asuransi berakhir' },
    { key: 'insurance_value', label: 'Nilai pertanggungan' },
  ];

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setLoading(true);
    setGalat('');
    try {
      const form = new FormData();
      form.append('file', file);
      const r = await fetch(`${API}/api/assets/bulk-import/preview`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || 'Gagal membaca berkas');
      setPreviewData(data);
      // Auto-map: try to match column names to asset fields
      const autoMap = {};
      ASSET_FIELDS.forEach(f => {
        const match = data.columns.find(c =>
          c.toLowerCase().replace(/[^a-z0-9]/g,'') === f.key.toLowerCase().replace(/[^a-z0-9]/g,'')
          || c.toLowerCase().includes(f.key.toLowerCase())
        );
        if (match) autoMap[f.key] = match;
      });
      setMapping(autoMap);
      setStep(2);
    } catch (err) {
      setGalat(err.message || 'Gagal mengunggah berkas');
      toast.error(err.message || 'Gagal mengunggah berkas');
    } finally {
      setLoading(false);
    }
  };

  const downloadTemplate = () => {
    const url = `${API}/api/assets/bulk-import/template`;
    const a = document.createElement('a');
    a.href = url;
    a.setAttribute('download', 'template_import_aset.xlsx');
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  const reset = () => {
    setStep(1); setPreviewData(null); setMapping({}); setCategoryId('');
    setResult(null); setRawRows([]); setGalat('');
    if (fileRef.current) fileRef.current.value = '';
  };

  // When previewData arrives, also fetch full raw rows for import execution
  useEffect(() => {
    if (previewData && fileRef.current?.files[0]) {
      const file = fileRef.current.files[0];
      const reader = new FileReader();
      reader.onload = async () => {
        // Note: the redesigned flow re-uploads the file in handleImportWithFile.
        // rawRows kept for legacy compatibility only.
      };
      reader.readAsArrayBuffer(file);
    }
  }, [previewData]);

  // Re-upload file for full data
  const handleImportWithFile = async () => {
    if (!categoryId) { setGalat('Pilih kategori lebih dulu.'); return; }
    const requiredMaps = ['name', 'purchase_date', 'purchase_cost'];
    if (requiredMaps.some(k => !mapping[k])) {
      setGalat('Kolom Nama aset, Tanggal beli, dan Harga beli wajib dicocokkan.');
      return;
    }
    const file = fileRef.current?.files[0];
    if (!file) { setGalat('Berkas tidak ditemukan, unggah ulang.'); return; }
    setGalat('');
    setLoading(true);
    try {
      const execForm = new FormData();
      execForm.append('file', file);
      execForm.append('mapping', JSON.stringify(mapping));
      execForm.append('category_id', categoryId);
      const execR = await fetch(`${API}/api/assets/bulk-import/execute-file`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: execForm,
      });
      const data = await execR.json();
      if (!execR.ok) throw new Error(data.detail || 'Gagal mengimpor');
      setResult(data);
      setStep(3);
      if (data.created_count > 0) onImported?.();
      toast.success(`${data.created_count} aset berhasil diimpor`);
    } catch (err) {
      setGalat(err.message || 'Gagal mengimpor');
    } finally {
      setLoading(false);
    }
  };

  const tutup = () => { reset(); onClose(); };
  const simpan = step === 2 ? handleImportWithFile : step === 3 ? reset : () => fileRef.current?.click();
  const labelSimpan = step === 2 ? `Impor ${previewData?.total_rows || 0} aset`
    : step === 3 ? 'Impor lagi' : 'Pilih berkas';

  return (
    <FormPopup open={open} onClose={tutup} ukuran="panjang" testId="bulk-import-form"
      judul="Impor aset dari CSV/Excel"
      keterangan="Unggah berkas CSV/Excel berisi data aset, cocokkan kolomnya, lalu impor."
      onSimpan={simpan} labelSimpan={labelSimpan} menyimpan={loading} galat={galat}
      aksiKiri={step === 2 ? (
        <Button type="button" variant="outline" onClick={() => { setStep(1); setGalat(''); }} disabled={loading}>Ganti berkas</Button>
      ) : null}>
      {/* Langkah */}
      <ol className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm" aria-label="Langkah impor">
        {LANGKAH.map((s, i) => (
          <li key={s} className={cn('flex items-center gap-1.5',
            step === i + 1 ? 'font-medium text-primary' : 'text-muted-foreground')}>
            <span className={cn('grid h-5 w-5 place-items-center rounded-full border text-xs',
              step === i + 1 ? 'border-primary bg-primary text-primary-foreground'
                : step > i + 1 ? 'border-[hsl(var(--success))] text-[hsl(var(--success-text))]' : 'border-[var(--glass-border)]')}>
              {i + 1}
            </span>
            {s}
          </li>
        ))}
      </ol>

      {/* Langkah 1: unggah */}
      {step === 1 && (
        <div className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Unggah berkas CSV atau Excel (.xlsx). Kolom wajib: <span className="font-medium text-foreground">nama aset, tanggal beli, harga beli</span>.
          </p>
          <Button type="button" variant="outline" onClick={downloadTemplate}>
            <Download />Unduh templat Excel
          </Button>
          <Button type="button" variant="outline"
            className="h-auto w-full flex-col gap-1 whitespace-normal min-h-32 border-2 border-dashed px-4 py-4"
            onClick={() => fileRef.current?.click()} data-testid="bulk-import-pick">
            <Upload className="text-muted-foreground" />
            <span className="text-sm font-medium text-foreground">Klik untuk memilih berkas</span>
            <span className="text-xs font-normal text-muted-foreground">CSV atau Excel (.xlsx, .xls)</span>
          </Button>
          {loading && <p className="text-center text-sm text-muted-foreground">Memproses berkas…</p>}
        </div>
      )}
      <input
        ref={fileRef}
        type="file"
        accept=".csv,.xlsx,.xls"
        className="hidden"
        onChange={handleFileUpload}
      />

      {/* Langkah 2: cocokkan kolom */}
      {step === 2 && previewData && (
        <div className="space-y-4">
          <p className="text-sm"><span className="font-medium tabular-nums">{previewData.total_rows}</span> baris ditemukan. Contoh isi berkas:</p>
          <Table>
            <TableHeader>
              <TableRow>{previewData.columns.map(c => <TableHead key={c} className="max-w-[10rem] truncate">{c}</TableHead>)}</TableRow>
            </TableHeader>
            <TableBody>
              {previewData.preview.map((row, ri) => (
                <TableRow key={ri}>
                  {previewData.columns.map(c => <TableCell key={c} className="max-w-[10rem] truncate" title={row[c]}>{row[c] || '—'}</TableCell>)}
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <Isian label="Kategori aset" wajib petunjuk="Semua aset dari berkas ini masuk ke kategori terpilih.">
            <SmartNativeSelect value={categoryId} onChange={e => setCategoryId(e.target.value)} className="h-9 w-full"
              data-testid="bulk-import-category">
              <option value="">Pilih kategori…</option>
              {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </SmartNativeSelect>
          </Isian>
          <div className="space-y-2">
            <p className="text-sm font-medium text-foreground">Cocokkan kolom</p>
            <div className="grid gap-x-4 gap-y-2 sm:grid-cols-2">
              {ASSET_FIELDS.map(f => (
                <div key={f.key} className="flex items-center gap-2">
                  <span className="w-40 shrink-0 text-sm">
                    {f.label}{f.required && <span className="text-[hsl(var(--danger-text))]">*</span>}
                  </span>
                  <SmartNativeSelect value={mapping[f.key] || ''} onChange={e => setMapping(p => ({ ...p, [f.key]: e.target.value }))}
                    className="h-9 w-full" aria-label={`Kolom untuk ${f.label}`}>
                    <option value="">— abaikan —</option>
                    {previewData.columns.map(c => <option key={c} value={c}>{c}</option>)}
                  </SmartNativeSelect>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Langkah 3: hasil */}
      {step === 3 && result && (
        <div className="space-y-4">
          <p className="text-base font-semibold text-foreground">Impor selesai</p>
          <div className="grid grid-cols-2 gap-3 sm:max-w-md">
            <StatTile label="Berhasil diimpor" value={result.created_count} accent="success" />
            <StatTile label="Gagal" value={result.error_count} accent={result.error_count ? 'danger' : 'default'} />
          </div>
          {result.errors?.length > 0 && (
            <div className="space-y-1">
              <p className="text-sm font-medium text-foreground">Baris yang gagal</p>
              <ul className="max-h-40 space-y-0.5 overflow-y-auto text-sm text-[hsl(var(--danger-text))]">
                {result.errors.map((e, i) => <li key={i}>Baris {e.row}: {e.error}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}
    </FormPopup>
  );
}

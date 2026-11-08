
import { useState, useRef } from 'react';
import { Upload, Download, FileSpreadsheet, Loader2, CheckCircle, AlertCircle } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Notice } from '../moduleAtoms';
import { apiFetch, apiPost } from '../../../lib/api';
import { todayWIB } from '../../../lib/waktu';

// Standar UI/UX v2 (8 Nov 2026): label tombol unduh bisa diatur (exportLabel/exportTitle); popup impor = FormPopup.
export default function ImportExportPanel({ token, importType, exportType, exportFilters = {}, onImportSuccess, exportLabel = 'Unduh Excel', exportTitle }) {
  const [showImportModal, setShowImportModal] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState(null);
  const [exporting, setExporting] = useState(false);
  const fileRef = useRef(null);
  const [namaBerkas, setNamaBerkas] = useState('');

  const downloadTemplate = async () => {
    if (!importType) return;
    try {
      const res = await apiFetch(`/import-template?type=${importType}`);
      if (!res.ok) throw new Error('Gagal download template');
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `template_${importType}.xlsx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error('Gagal mengunduh template: ' + err.message);
    }
  };

  const handleImport = async (e) => {
    e?.preventDefault?.();
    const file = fileRef.current?.files?.[0];
    if (!file) { toast.error('Pilih file terlebih dahulu'); return; }

    setImporting(true);
    setImportResult(null);
    try {
      const formData = new FormData();
      formData.append('type', importType);
      formData.append('file', file);
      const data = await apiPost('/import-data', formData);
      setImportResult(data);
      if (onImportSuccess) onImportSuccess();
    } catch (err) {
      setImportResult({ error: err.message });
    } finally {
      setImporting(false);
    }
  };

  const handleExport = async () => {
    if (!exportType) return;
    setExporting(true);
    try {
      const params = new URLSearchParams({ type: exportType });
      Object.entries(exportFilters).forEach(([k, v]) => { if (v) params.set(k, v); });

      const res = await apiFetch(`/export-excel?${params.toString()}`);
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.error || errData.detail || 'Export gagal');
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `export_${exportType}_${todayWIB()}.xlsx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error('Unduh gagal: ' + err.message);
    } finally {
      setExporting(false);
    }
  };

  return (
    <>
      <div className="flex gap-2">
        {importType && (
          <Button type="button" variant="outline" onClick={() => { setShowImportModal(true); setImportResult(null); setNamaBerkas(''); }}>
            <Upload className="w-4 h-4" />
            Impor
          </Button>
        )}
        {exportType && (
          <Button type="button" variant="outline" onClick={handleExport} disabled={exporting} title={exportTitle} data-testid="export-excel-btn">
            {exporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileSpreadsheet className="w-4 h-4" />}
            {exportLabel}
          </Button>
        )}
      </div>

      {/* Popup impor — FormPopup pendek */}
      {showImportModal && (
        <FormPopup open onClose={() => setShowImportModal(false)} ukuran="pendek" judul="Impor data"
          keterangan="Unduh template, isi, lalu unggah berkasnya." onSimpan={handleImport} menyimpan={importing}
          labelSimpan="Unggah & impor" testId="import-panel-form">
              <Isian label="Langkah 1 · template Excel">
                <div>
                  <Button type="button" variant="outline" size="sm" onClick={downloadTemplate}>
                    <Download className="w-4 h-4" />
                    Unduh templat
                  </Button>
                </div>
              </Isian>
              <Isian label="Langkah 2 · berkas yang sudah diisi" htmlFor="import-panel-file">
                {/* Standar UI/UX v2: tombol baku "Pilih berkas" (teks bawaan peramban berbahasa Inggris); input tetap sama. */}
                <input
                  id="import-panel-file"
                  type="file"
                  ref={fileRef}
                  accept=".xlsx,.xls"
                  className="sr-only"
                  onChange={(e) => setNamaBerkas(e.target.files?.[0]?.name || '')}
                />
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <Button type="button" variant="outline" size="sm" onClick={() => fileRef.current?.click()}>
                    <Upload className="w-4 h-4" />Pilih berkas
                  </Button>
                  <span className="min-w-0 break-all text-xs text-muted-foreground">{namaBerkas || 'Belum ada berkas (.xlsx/.xls)'}</span>
                </div>
              </Isian>

              {/* Import Result */}
              {importResult && (
                importResult.error ? (
                  <Notice tone="danger" icon={AlertCircle} title="Impor gagal">{importResult.error}</Notice>
                ) : (
                  <Notice tone="success" icon={CheckCircle} title="Impor berhasil">
                      <div className="space-y-1">
                        {importResult.imported_products !== undefined && (
                          <p>{importResult.imported_products} produk diimpor</p>
                        )}
                        {importResult.imported_variants !== undefined && (
                          <p>{importResult.imported_variants} varian diimpor</p>
                        )}
                        {importResult.imported_garments !== undefined && (
                          <p>{importResult.imported_garments} vendor diimpor</p>
                        )}
                        {importResult.imported_pos !== undefined && (
                          <p>{importResult.imported_pos} PO diimpor</p>
                        )}
                        {importResult.imported_items !== undefined && (
                          <p>{importResult.imported_items} item PO diimpor</p>
                        )}
                        {importResult.skipped > 0 && (
                          <p className="text-[hsl(var(--warning-text))]">{importResult.skipped} baris dilewati (kosong)</p>
                        )}
                        {importResult.errors?.length > 0 && (
                          <div className="mt-2 pt-2 border-t border-[hsl(var(--success)/0.35)]">
                            <p className="font-medium text-[hsl(var(--warning-text))] mb-1">{importResult.errors.length} peringatan:</p>
                            <ul className="list-disc list-inside text-xs text-[hsl(var(--warning-text))] max-h-32 overflow-auto">
                              {importResult.errors.map((err, i) => <li key={i}>{err}</li>)}
                            </ul>
                          </div>
                        )}
                        {/* Show vendor accounts if garments import */}
                        {importResult.vendor_accounts?.length > 0 && (
                          <div className="mt-2 pt-2 border-t border-[hsl(var(--success)/0.35)]">
                            <p className="font-medium text-[hsl(var(--success-text))] mb-1">Akun Vendor yang Dibuat:</p>
                            <div className="max-h-40 overflow-auto">
                              <Table>
                                <TableHeader>
                                  <TableRow className="text-left">
                                    <TableHead className="pb-1">Vendor</TableHead>
                                    <TableHead className="pb-1">Email</TableHead>
                                    <TableHead className="pb-1">Password</TableHead>
                                  </TableRow>
                                </TableHeader>
                                <TableBody>
                                  {importResult.vendor_accounts.map((acc, i) => (
                                    <TableRow key={i} className="border-t border-[hsl(var(--success)/0.35)]">
                                      <TableCell className="py-1">{acc.garment_name}</TableCell>
                                      <TableCell className="py-1 tabular-nums">{acc.email}</TableCell>
                                      <TableCell className="py-1 tabular-nums">{acc.password}</TableCell>
                                    </TableRow>
                                  ))}
                                </TableBody>
                              </Table>
                            </div>
                          </div>
                        )}
                      </div>
                  </Notice>
                )
              )}
        </FormPopup>
      )}
    </>
  );
}

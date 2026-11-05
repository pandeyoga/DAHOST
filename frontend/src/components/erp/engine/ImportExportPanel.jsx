
import { useState, useRef } from 'react';
import { Upload, Download, FileSpreadsheet, Loader2, CheckCircle, AlertCircle, X } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Notice } from '../moduleAtoms';
import { apiFetch, apiPost } from '../../../lib/api';
import { todayWIB } from '../../../lib/waktu';

export default function ImportExportPanel({ token, importType, exportType, exportFilters = {}, onImportSuccess }) {
  const [showImportModal, setShowImportModal] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState(null);
  const [exporting, setExporting] = useState(false);
  const fileRef = useRef(null);

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
    e.preventDefault();
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
          <Button variant="outline" onClick={() => { setShowImportModal(true); setImportResult(null); }}>
            <Upload className="w-4 h-4" />
            Impor
          </Button>
        )}
        {exportType && (
          <Button variant="outline" onClick={handleExport} disabled={exporting}>
            {exporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileSpreadsheet className="w-4 h-4" />}
            Unduh Excel
          </Button>
        )}
      </div>

      {/* Import Modal */}
      {showImportModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-card rounded-xl shadow-2xl max-w-lg w-full max-h-[80vh] overflow-auto">
            <div className="flex items-center justify-between p-4 border-b">
              <h3 className="text-lg font-bold text-gray-800">
                <Upload className="w-5 h-5 inline mr-2 text-[hsl(var(--success))]" />
                Impor data
              </h3>
              <Button variant="ghost" size="icon-sm" onClick={() => setShowImportModal(false)} title="Tutup" aria-label="Tutup">
                <X className="w-5 h-5" />
              </Button>
            </div>

            <div className="p-4 space-y-4">
              {/* Template Download */}
              <div className="bg-[hsl(var(--primary)/0.1)] border border-[hsl(var(--primary)/0.35)] rounded-lg p-3">
                <p className="text-sm text-[hsl(var(--primary))] mb-2">
                  <strong>Langkah 1:</strong> Unduh template Excel terlebih dahulu
                </p>
                <Button variant="outline" size="sm" onClick={downloadTemplate}>
                  <Download className="w-4 h-4" />
                  Unduh template
                </Button>
              </div>

              {/* File Upload */}
              <form onSubmit={handleImport} className="space-y-3">
                <div className="bg-gray-50 border border-gray-200 rounded-lg p-3">
                  <p className="text-sm text-gray-700 mb-2">
                    <strong>Langkah 2:</strong> Isi template lalu unggah filenya
                  </p>
                  <input
                    type="file"
                    ref={fileRef}
                    accept=".xlsx,.xls"
                    className="block w-full text-sm text-gray-700 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-[hsl(var(--success)/0.1)] file:text-[hsl(var(--success))] hover:file:bg-[hsl(var(--success)/0.15)]"
                  />
                </div>

                <Button type="submit" disabled={importing} className="w-full">
                  {importing ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Mengimpor...
                    </>
                  ) : (
                    <>
                      <Upload className="w-4 h-4" />
                      Unggah & impor
                    </>
                  )}
                </Button>
              </form>

              {/* Import Result */}
              {importResult && (
                importResult.error ? (
                  <Notice tone="danger" icon={AlertCircle} title="Impor gagal">{importResult.error}</Notice>
                ) : (
                  <Notice tone="success" icon={CheckCircle} title="Impor berhasil">
                      <div className="space-y-1">
                        {importResult.imported_products !== undefined && (
                          <p>✅ {importResult.imported_products} produk diimpor</p>
                        )}
                        {importResult.imported_variants !== undefined && (
                          <p>✅ {importResult.imported_variants} varian diimpor</p>
                        )}
                        {importResult.imported_garments !== undefined && (
                          <p>✅ {importResult.imported_garments} vendor diimpor</p>
                        )}
                        {importResult.imported_pos !== undefined && (
                          <p>✅ {importResult.imported_pos} PO diimpor</p>
                        )}
                        {importResult.imported_items !== undefined && (
                          <p>✅ {importResult.imported_items} item PO diimpor</p>
                        )}
                        {importResult.skipped > 0 && (
                          <p className="text-[hsl(var(--warning))]">⚠️ {importResult.skipped} baris dilewati (kosong)</p>
                        )}
                        {importResult.errors?.length > 0 && (
                          <div className="mt-2 pt-2 border-t border-[hsl(var(--success)/0.35)]">
                            <p className="font-medium text-[hsl(var(--warning))] mb-1">⚠️ {importResult.errors.length} peringatan:</p>
                            <ul className="list-disc list-inside text-xs text-[hsl(var(--warning))] max-h-32 overflow-auto">
                              {importResult.errors.map((err, i) => <li key={i}>{err}</li>)}
                            </ul>
                          </div>
                        )}
                        {/* Show vendor accounts if garments import */}
                        {importResult.vendor_accounts?.length > 0 && (
                          <div className="mt-2 pt-2 border-t border-[hsl(var(--success)/0.35)]">
                            <p className="font-medium text-[hsl(var(--success))] mb-1">Akun Vendor yang Dibuat:</p>
                            <div className="max-h-40 overflow-auto">
                              <table className="w-full text-xs">
                                <thead>
                                  <tr className="text-left">
                                    <th className="pb-1">Vendor</th>
                                    <th className="pb-1">Email</th>
                                    <th className="pb-1">Password</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {importResult.vendor_accounts.map((acc, i) => (
                                    <tr key={i} className="border-t border-[hsl(var(--success)/0.35)]">
                                      <td className="py-1">{acc.garment_name}</td>
                                      <td className="py-1 tabular-nums">{acc.email}</td>
                                      <td className="py-1 tabular-nums">{acc.password}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        )}
                      </div>
                  </Notice>
                )
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

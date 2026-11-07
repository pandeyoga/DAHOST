/**
 * WorkspacePortal — Spreadsheet (Portal Kolaborasi): daftar dokumen + editor.
 *
 * UI lain ada di `./workspace-portal/*` (utils, AccessBadge, ShareDialog, ColumnsDialog, ImportExcelDialog,
 * ImportFromModuleDialog, VersionHistoryDrawer, FormulaBar, FormattingToolbar, DocCard, NewDocForm, GridEditorView).
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout · daftar dokumen = tabel standar (dulu kartu berulang) yang bisa
 * diunduh · tiga kartu "aksi cepat" besar diganti tombol di kepala halaman · spreadsheet baru = FormPopup ·
 * hapus = konfirmasi aplikasi (dulu window.confirm).
 *
 * Props: { token, user, onBack? } — `onBack` hanya dipakai saat menu Spreadsheet dibuka sendiri (Portal
 * Kolaborasi tampil tanpa kerangka portal, jadi tanpa tombol ini tidak ada jalan kembali).
 * Dipakai oleh: CollaborationPortal, StudyGroupDetail, moduleRegistry (collab-workspace).
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { toast } from 'sonner';
import { ArrowLeft, FileSpreadsheet, Package, Plus, RefreshCw, Search, Share2, Trash2, Upload } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PageLayout from './layout/PageLayout';
import { EmptyState } from './moduleAtoms';

import { API, ACCESS_CONFIG, apicall, canShare, fmtTime } from './workspace-portal/utils';
import AccessBadge from './workspace-portal/AccessBadge';
import NewDocForm from './workspace-portal/NewDocForm';
import ShareDialog from './workspace-portal/ShareDialog';
import ImportExcelDialog from './workspace-portal/ImportExcelDialog';
import ImportFromModuleDialog from './workspace-portal/ImportFromModuleDialog';
import GridEditorView from './workspace-portal/GridEditorView';

const KOLOM_UNDUH = [
  { label: 'Nama', nilai: (d) => d.name },
  { label: 'Akses', nilai: (d) => (ACCESS_CONFIG[d.access_level] || ACCESS_CONFIG.view).label },
  { label: 'Pemilik', nilai: (d) => d.owner_name || '' },
  { label: 'Diubah', nilai: (d) => (d.updated_at ? new Date(d.updated_at).toLocaleString('id-ID') : '') },
  { label: 'Baris', nilai: (d) => Number(d.metadata?.row_count ?? 0) },
  { label: 'Kolom', nilai: (d) => Number(d.metadata?.column_count ?? 0) },
];

export default function WorkspacePortal({ token, onBack, moduleId }) {
  const [documents, setDocuments] = useState({ owned: [], shared: [] });
  const [loading, setLoading] = useState(true);
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [showNewDoc, setShowNewDoc] = useState(false);
  const [showImportExcel, setShowImportExcel] = useState(false);
  const [showImportModule, setShowImportModule] = useState(false);
  const [shareTarget, setShareTarget] = useState(null);
  const [, setImportingExcel] = useState(false);
  const fileInputRef = useRef(null);

  const loadDocuments = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apicall('GET', '/api/workspace/documents', token);
      setDocuments(data);
    } catch {
      toast.error('Gagal memuat dokumen');
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { loadDocuments(); }, [loadDocuments]);

  const handleDocOpen = async (docId) => {
    try {
      const doc = await apicall('GET', `/api/workspace/documents/${docId}`, token);
      setSelectedDoc(doc);
    } catch (e) {
      toast.error(e.message || 'Gagal membuka dokumen');
    }
  };

  const handleDocDelete = async (docId, docName) => {
    if (!(await confirmDialog({ title: `Hapus "${docName}"?`, body: 'Dokumen dan isinya hilang untuk semua orang yang diberi akses.',
      confirmLabel: 'Hapus', danger: true }))) return;
    try {
      await apicall('DELETE', `/api/workspace/documents/${docId}`, token);
      toast.success('Dokumen dihapus');
      loadDocuments();
    } catch (e) {
      toast.error(e.message);
    }
  };

  // Impor Excel cepat (1 langkah, versi lama) — tetap ada lewat input berkas tersembunyi.
  const handleQuickExcelImport = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.match(/\.xlsx?$/i)) { toast.error('File harus .xlsx atau .xls'); return; }
    setImportingExcel(true);
    const fd = new FormData();
    fd.append('file', file);
    try {
      const res = await fetch(`${API}/api/workspace/documents/import-excel`, {
        method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: fd,
      });
      const doc = await res.json();
      if (!res.ok) throw new Error(doc.detail || 'Impor gagal');
      toast.success(`Excel berhasil diimpor: "${doc.name}"`);
      loadDocuments();
      setSelectedDoc(doc);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setImportingExcel(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const q = searchQuery.toLowerCase();
  const filteredOwned = documents.owned.filter((d) => d.name.toLowerCase().includes(q));
  const filteredShared = documents.shared.filter((d) => d.name.toLowerCase().includes(q));

  // Editor (bila dokumen dipilih)
  if (selectedDoc) {
    return (
      <GridEditorView document={selectedDoc} token={token} onBack={() => setSelectedDoc(null)} onUpdated={loadDocuments} />
    );
  }

  const kolom = (milikSendiri) => [
    { kunci: 'nama', label: 'Nama', hp: 'judul', isi: (doc) => (
      <span className="inline-flex flex-wrap items-center gap-2" data-testid={`doc-card-${doc.id}`}>
        <FileSpreadsheet className="h-4 w-4 shrink-0 text-primary" />
        <span className="font-medium text-foreground">{doc.name}</span>
        <AccessBadge level={doc.access_level} />
      </span>) },
    ...(milikSendiri ? [] : [{ kunci: 'pemilik', label: 'Pemilik', isi: (doc) => doc.owner_name || '—' }]),
    { kunci: 'diubah', label: 'Diubah', isi: (doc) => <span className="whitespace-nowrap text-muted-foreground">{fmtTime(doc.updated_at)}</span> },
    { kunci: 'ukuran', label: 'Isi', rata: 'kanan', isi: (doc) => (
      <span className="tabular-nums whitespace-nowrap">{doc.metadata?.row_count ?? 0} baris · {doc.metadata?.column_count ?? 0} kolom</span>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (doc) => {
      const bisaBagi = milikSendiri || canShare(doc.access_level);
      const bisaHapus = milikSendiri || doc.is_owner;
      return (
        <div className="flex justify-end gap-1">
          {bisaBagi && (
            <Button variant="ghost" size="icon-sm" onClick={() => setShareTarget(doc)} title="Bagikan" aria-label="Bagikan"
              data-testid={`share-doc-${doc.id}`}><Share2 /></Button>
          )}
          {bisaHapus && (
            <Button variant="ghost" size="icon-sm" onClick={() => handleDocDelete(doc.id, doc.name)} title="Hapus dokumen" aria-label="Hapus dokumen"
              data-testid={`delete-doc-${doc.id}`}><Trash2 /></Button>
          )}
        </div>
      );
    } },
  ];

  return (
    <div className="h-full overflow-y-auto" data-testid="workspace-portal">
      <div className="p-4 sm:px-6">
        <PageLayout title="Spreadsheet" subtitle="Dokumen spreadsheet bersama: buat baru, impor dari Excel atau dari modul, lalu bagikan."
          actions={<>
            <Button variant="outline" onClick={() => setShowImportExcel(true)} data-testid="quick-import-excel"><Upload />Impor Excel</Button>
            <Button variant="outline" onClick={() => setShowImportModule(true)} data-testid="quick-import-module"><Package />Impor dari modul</Button>
            <Button onClick={() => setShowNewDoc(true)} data-testid="new-doc-btn"><Plus />Spreadsheet baru</Button>
          </>}
          filters={<div className="relative w-full sm:w-64">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input placeholder="Cari dokumen" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-8" data-testid="doc-search" />
          </div>}
          tools={<>
            <TombolUnduh namaBerkas="daftar-spreadsheet" namaLembar="Dokumen" baris={[...filteredOwned, ...filteredShared]}
              kolom={KOLOM_UNDUH} testId="workspace-unduh" />
            <Button variant="outline" size="icon" onClick={loadDocuments} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
              <RefreshCw className={loading ? 'animate-spin' : ''} />
            </Button>
            {onBack && moduleId === 'collab-workspace' && (
              <Button variant="outline" size="icon" onClick={onBack} title="Kembali ke pilihan portal" aria-label="Kembali ke pilihan portal"
                data-testid="workspace-back"><ArrowLeft /></Button>
            )}
          </>}>
          <input type="file" ref={fileInputRef} onChange={handleQuickExcelImport} accept=".xlsx,.xls" className="hidden" />
          {loading ? (
            <div className="space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
          ) : (
            <>
              <div className="space-y-2">
                <p className="text-base font-semibold text-foreground">Dokumen saya ({filteredOwned.length})</p>
                <TabelData kolom={kolom(true)} baris={filteredOwned} onKlikBaris={(doc) => handleDocOpen(doc.id)} testId="workspace-owned"
                  kosong={<EmptyState icon={FileSpreadsheet} className="py-10"
                    title={searchQuery ? 'Tidak ada dokumen yang cocok' : 'Belum ada dokumen'}
                    description={searchQuery ? 'Ubah kata pencarian.' : 'Buat spreadsheet baru atau impor dari Excel.'}
                    action={!searchQuery && <Button variant="outline" onClick={() => setShowNewDoc(true)} data-testid="quick-new-spreadsheet"><Plus />Buat sekarang</Button>} />} />
              </div>
              {filteredShared.length > 0 && (
                <div className="space-y-2">
                  <p className="text-base font-semibold text-foreground">Dibagikan ke saya ({filteredShared.length})</p>
                  <TabelData kolom={kolom(false)} baris={filteredShared} onKlikBaris={(doc) => handleDocOpen(doc.id)} testId="workspace-shared" />
                </div>
              )}
            </>
          )}
        </PageLayout>
      </div>

      <NewDocForm open={showNewDoc} token={token} onClose={() => setShowNewDoc(false)}
        onCreated={(doc) => { loadDocuments(); setSelectedDoc(doc); setShowNewDoc(false); }} />
      <ImportExcelDialog open={showImportExcel} onClose={() => setShowImportExcel(false)} token={token}
        onImported={(doc) => { loadDocuments(); setSelectedDoc(doc); }} />
      <ImportFromModuleDialog open={showImportModule} onClose={() => setShowImportModule(false)} token={token}
        onImported={(doc) => { loadDocuments(); setSelectedDoc(doc); }} />
      <ShareDialog open={!!shareTarget} onClose={() => setShareTarget(null)} document={shareTarget} token={token}
        onShared={() => loadDocuments()} />
    </div>
  );
}

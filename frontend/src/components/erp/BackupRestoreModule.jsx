/**
 * Backup Data (Administrasi Sistem) — backup, unggah, unduh, pulihkan, dan kosongkan koleksi database.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, daftar backup = tabel (kartu ringkas di HP) + unduh daftar, aksi baris
 * Unduh + "Lainnya" (pulihkan sebagian / seluruhnya / hapus), konfirmasi pulihkan = popup standar, pulihkan sebagian
 * = FormPopup dengan tabel koleksi, istilah Indonesia (Restore → Pulihkan, Overwrite/Merge → Timpa/Gabung).
 * Kartu "Total ukuran" diperbaiki: ukuran "512K" dulu terbaca 512 MB.
 */
import { useState, useEffect, useCallback } from 'react';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { CheckSquare, Database, Download, FileUp, MoreHorizontal, RefreshCw, RotateCcw, Trash2 } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import FilterChips from '@/components/ui/filter-chips';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';
import { useToast } from '@/hooks/use-toast';
import { downloadBackup, uploadBackup, listCollections, restoreSelective, labelKoleksi } from './backupRestoreHelpers';
import DatabaseCollectionsPanel from './DatabaseCollectionsPanel';

const formatDate = (isoStr) => {
  if (!isoStr) return '-';
  const d = new Date(isoStr);
  return d.toLocaleString('id-ID', { dateStyle: 'medium', timeStyle: 'short' });
};

export default function BackupRestoreModule({ token }) {
  const [backups, setBackups] = useState([]);
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(null);
  const [restoreTarget, setRestoreTarget] = useState(null);
  // Rincian kegagalan restore (sebab + saran + log) — ditampilkan di dialog,
  // bukan cuma toast, supaya user tahu APA yang salah dan APA yang harus dilakukan.
  const [restoreError, setRestoreError] = useState(null);
  const [selectiveRestore, setSelectiveRestore] = useState(null);
  const [collections, setCollections] = useState([]);
  const [selectedCollections, setSelectedCollections] = useState([]);
  const [restoreMode, setRestoreMode] = useState('overwrite');
  const [uploadFile, setUploadFile] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadStage, setUploadStage] = useState(null);
  // Tautan unduh manual — jaring pengaman kalau browser memblokir unduhan
  // otomatis (preview berjalan di dalam iframe).
  const [downloadHint, setDownloadHint] = useState(null);
  const [tab, setTab] = useState('backup');
  const { toast } = useToast();
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchBackups = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch('/api/admin/backup/list', { headers });
      if (r.ok) {
        const data = await r.json();
        setBackups(data.backups || []);
      } else {
        toast({ title: 'Gagal', description: 'Gagal memuat daftar backup', variant: 'destructive' });
      }
    } catch (e) {
      toast({ title: 'Gagal', description: 'Gagal memuat data', variant: 'destructive' });
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const fetchConfig = useCallback(async () => {
    try {
      const r = await fetch('/api/admin/backup/config', { headers });
      if (r.ok) setConfig(await r.json());
    } catch (e) {
      // Silent fail
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => {
    fetchBackups();
    fetchConfig();
  }, [fetchBackups, fetchConfig]);

  const createBackup = async () => {
    setProcessing('create');
    try {
      const r = await fetch('/api/admin/backup/create', {
        method: 'POST',
        headers,
        body: JSON.stringify({ notify: true })
      });
      if (r.ok) {
        const data = await r.json();
        toast({
          title: 'Backup dimulai',
          description: `Backup '${data.backup_name}' sedang diproses di latar belakang. Anda akan menerima notifikasi saat selesai.`
        });
        setTimeout(fetchBackups, 3000); // Refresh after 3 seconds
      } else {
        const err = await r.json();
        toast({ title: 'Gagal', description: err.detail || 'Gagal membuat backup', variant: 'destructive' });
      }
    } catch (e) {
      toast({ title: 'Gagal', description: 'Gagal membuat backup', variant: 'destructive' });
    } finally {
      setProcessing(null);
    }
  };

  const restoreBackup = async () => {
    if (!restoreTarget) return;
    setProcessing('restore');
    setRestoreError(null);
    try {
      const r = await fetch('/api/admin/backup/restore', {
        method: 'POST',
        headers,
        body: JSON.stringify({ backup_id: restoreTarget.backup_id, confirm: true })
      });
      if (r.ok) {
        toast({
          title: 'Pemulihan berhasil',
          description: `Database berhasil dipulihkan dari '${restoreTarget.backup_name}'. Halaman akan dimuat ulang…`
        });
        setRestoreTarget(null);
        setTimeout(() => window.location.reload(), 2000);
        return;
      }
      // GAGAL — backend mengirim detail terstruktur:
      // { message, reason, hint, returncode, log_lines[], log_path }
      // (dulu hanya "Restore failed: " tanpa sebab apa pun).
      let info = {};
      try {
        const body = await r.json();
        const d = body?.detail;
        info = typeof d === 'string' ? { reason: d } : (d || {});
      } catch (parseErr) {
        info = { reason: `Server mengirim respons yang tidak bisa dibaca (${parseErr?.message || 'gagal parse JSON'}).` };
      }
      const err = {
        message: info.message || `Pemulihan gagal (kode ${r.status})`,
        reason: info.reason || 'Server tidak mengirim rincian sebab kegagalan.',
        hint: info.hint || '',
        returncode: info.returncode ?? null,
        logLines: Array.isArray(info.log_lines) ? info.log_lines : [],
        logPath: info.log_path || ''
      };
      setRestoreError(err);
      toast({ title: 'Pemulihan gagal', description: err.reason, variant: 'destructive' });
    } catch (e) {
      const err = {
        message: 'Pemulihan gagal',
        reason: `Tidak bisa menghubungi server: ${e?.message || e}`,
        hint: 'Periksa status backend (sudo supervisorctl status backend) lalu coba lagi.',
        returncode: null,
        logLines: [],
        logPath: ''
      };
      setRestoreError(err);
      toast({ title: 'Pemulihan gagal', description: err.reason, variant: 'destructive' });
    } finally {
      setProcessing(null);
      // Dialog SENGAJA dibiarkan terbuka saat gagal agar rincian sebab terbaca.
    }
  };

  const deleteBackup = async (backup) => {
    if (!(await confirmDialog({ title: `Hapus backup '${backup.backup_name}'?`, body: 'Berkas backup dihapus permanen dari server.', confirmLabel: 'Hapus', danger: true }))) return;
    setProcessing(backup.backup_id);
    try {
      const r = await fetch(`/api/admin/backup/${backup.backup_id}`, {
        method: 'DELETE',
        headers
      });
      if (r.ok) {
        toast({ title: 'Berhasil', description: `Backup '${backup.backup_name}' dihapus` });
        fetchBackups();
      } else {
        toast({ title: 'Gagal', description: 'Gagal menghapus backup', variant: 'destructive' });
      }
    } catch (e) {
      toast({ title: 'Gagal', description: 'Gagal menghapus backup', variant: 'destructive' });
    } finally {
      setProcessing(null);
    }
  };

  const cleanup = async () => {
    if (!(await confirmDialog({ title: `Hapus semua backup yang lebih lama dari ${config?.retention_days || 30} hari?`, confirmLabel: 'Bersihkan', danger: true }))) return;
    setProcessing('cleanup');
    try {
      const r = await fetch('/api/admin/backup/cleanup', {
        method: 'POST',
        headers
      });
      if (r.ok) {
        toast({ title: 'Berhasil', description: 'Backup lama dibersihkan' });
        fetchBackups();
      } else {
        toast({ title: 'Gagal', description: 'Pembersihan backup lama gagal', variant: 'destructive' });
      }
    } catch (e) {
      toast({ title: 'Gagal', description: 'Pembersihan backup lama gagal', variant: 'destructive' });
    } finally {
      setProcessing(null);
    }
  };

  const handleDownload = async (backup) => {
    setProcessing(backup.backup_id);
    setDownloadHint(null);
    toast({ title: 'Menyiapkan unduhan...', description: `${backup.backup_name}.zip` });
    const result = await downloadBackup(backup.backup_id, token);
    setProcessing(null);
    if (result.ok) {
      // Preview dijalankan di dalam iframe; unduhan otomatis BISA diblokir browser.
      // Karena itu tautan langsung selalu ditampilkan sebagai jalan pasti.
      if (result.url) {
        setDownloadHint({ name: `${backup.backup_id}.zip`, url: result.url });
        toast({
          title: 'Unduhan dimulai di tab baru',
          description: 'Jika tab tidak terbuka, klik tautan unduh manual yang muncul di atas daftar.',
        });
      } else {
        toast({ title: 'Berhasil', description: 'Backup berhasil diunduh' });
      }
    } else {
      if (result.url) setDownloadHint({ name: `${backup.backup_id}.zip`, url: result.url });
      toast({ title: 'Gagal', description: result.error || 'Download gagal', variant: 'destructive' });
    }
  };

  // Unggah LANGSUNG jalan saat berkas dipilih (dulu perlu klik tombol kedua yang
  // sering terlewat) + progress persen + input di-reset supaya memilih berkas
  // yang SAMA dua kali tetap memicu unggahan.
  const handleUpload = async (file) => {
    if (!file) {
      toast({ title: 'Gagal', description: 'Pilih file ZIP terlebih dahulu', variant: 'destructive' });
      return;
    }
    setUploadFile(file);
    setProcessing('upload');
    setUploadProgress(0);
    setUploadStage('menyiapkan');
    const sizeMb = (file.size / 1048576).toFixed(1);
    toast({ title: 'Mengunggah...', description: `${file.name} (${sizeMb} MB)` });

    const result = await uploadBackup(file, token, (percent, stage) => {
      setUploadProgress(percent);
      setUploadStage(stage);
    });

    setProcessing(null);
    setUploadFile(null);
    setUploadProgress(0);
    setUploadStage(null);
    const input = document.getElementById('backup-upload-input');
    if (input) input.value = '';

    if (result.ok) {
      toast({
        title: 'Upload berhasil',
        description: `${result.backup_name} — ${result.collections_found ?? '?'} koleksi `
          + `(database '${result.database_in_backup ?? '-'}'). Pakai menu Lainnya › Pulihkan untuk memulihkan.`,
      });
      fetchBackups();
    } else {
      toast({ title: 'Upload gagal', description: result.error || 'Upload gagal', variant: 'destructive' });
    }
  };

  const openSelectiveRestore = async (backup) => {
    setProcessing(backup.backup_id);
    const result = await listCollections(backup.backup_id, token);
    setProcessing(null);
    if (result.error) {
      toast({ title: 'Gagal', description: result.error, variant: 'destructive' });
      return;
    }
    setCollections(result.collections || []);
    setSelectedCollections([]);
    setRestoreMode('overwrite');
    setSelectiveRestore(backup);
  };

  const toggleCollection = (collectionName) => {
    setSelectedCollections(prev =>
      prev.includes(collectionName)
        ? prev.filter(c => c !== collectionName)
        : [...prev, collectionName]
    );
  };

  const selectAllCollections = () => {
    setSelectedCollections(collections.map(c => c.name));
  };

  const clearSelections = () => {
    setSelectedCollections([]);
  };

  const confirmSelectiveRestore = async () => {
    if (selectedCollections.length === 0) {
      toast({ title: 'Belum ada pilihan', description: 'Pilih minimal 1 koleksi', variant: 'destructive' });
      return;
    }
    setProcessing('selective-restore');
    const result = await restoreSelective(selectiveRestore.backup_id, selectedCollections, restoreMode, token);
    setProcessing(null);
    if (result.ok) {
      toast({
        title: 'Pemulihan selesai',
        description: `${result.total_restored}/${result.total_requested} koleksi berhasil dipulihkan`
      });
      setSelectiveRestore(null);
    } else {
      toast({ title: 'Gagal', description: result.error || 'Pemulihan gagal', variant: 'destructive' });
    }
  };

  const latestBackup = backups[0];
  // Ukuran dari server berbentuk keluaran `du -sh` ("512K", "12M", "1.2G", "unknown"). Dulu "512K" dihitung
  // 512 MB (hanya G yang dikenali) → total ukuran bisa jauh salah. Kini satuan K/M/G/T dikenali; "unknown" dilewati.
  const keMB = (s) => {
    const m = /^\s*([\d.,]+)\s*([KMGT]?)i?B?\s*$/i.exec(String(s || ''));
    if (!m) return null;
    const n = parseFloat(m[1].replace(',', '.'));
    const f = { '': 1 / 1048576, K: 1 / 1024, M: 1, G: 1024, T: 1048576 }[m[2].toUpperCase()];
    return Number.isFinite(n) ? n * f : null;
  };
  const ukuranDikenal = backups.map((b) => keMB(b.size)).filter((v) => v !== null);
  const totalSize = ukuranDikenal.reduce((a, b) => a + b, 0);
  const ukuranTakDikenal = backups.length - ukuranDikenal.length;
  const labelStatus = (s) => (s === 'success' ? { label: 'Berhasil', tone: 'success' }
    : s === 'failed' ? { label: 'Gagal', tone: 'danger' }
      : s === 'in_progress' || s === 'running' ? { label: 'Sedang diproses', tone: 'info' }
        : { label: 'Perlu dicek', tone: 'warning' });
  const jadwal = (j) => {
    const m = /Daily at (\d{1,2}):(\d{2})\s*(Asia\/Jakarta)?/i.exec(String(j || ''));
    return m ? `Setiap hari pukul ${m[1].padStart(2, '0')}.${m[2]}${m[3] ? ' WIB' : ''}` : (j || '—');
  };
  const penyimpanan = (t) => (t === 'local_filesystem' ? 'Berkas di server' : (t || '—'));

  const kolomBackup = [
    { kunci: 'nama', label: 'Backup', hp: 'judul', isi: (b) => (
      <span className="break-all font-mono text-sm font-medium" data-testid={`backup-item-${b.backup_id}`}>{b.backup_name}</span>) },
    { kunci: 'dibuat', label: 'Dibuat', isi: (b) => <span className="whitespace-nowrap text-sm">{formatDate(b.created_at)}</span> },
    { kunci: 'ukuran', label: 'Ukuran', rata: 'kanan', isi: (b) => <span className="tabular-nums">{b.size === 'unknown' ? '—' : b.size}</span> },
    { kunci: 'db', label: 'Database', isi: (b) => <span className="text-sm text-muted-foreground">{b.database || '—'}</span> },
    { kunci: 'status', label: 'Status', isi: (b) => <StatusBadge status={b.status} label={labelStatus(b.status).label} tone={labelStatus(b.status).tone} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (b) => (
      <div className="flex items-center justify-end gap-1">
        <Button size="sm" variant="outline" onClick={() => handleDownload(b)} disabled={processing === b.backup_id}
          data-testid={`backup-download-${b.backup_id}`} title="Unduh sebagai ZIP">
          {processing === b.backup_id ? <RefreshCw className="animate-spin" /> : <Download />}Unduh
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="icon-sm" variant="ghost" title="Lainnya" aria-label="Lainnya" data-testid={`backup-more-${b.backup_id}`}>
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => openSelectiveRestore(b)} disabled={processing === b.backup_id}
              data-testid={`backup-selective-${b.backup_id}`}>
              <CheckSquare className="mr-2 h-4 w-4" />Pulihkan koleksi terpilih
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => { setRestoreError(null); setRestoreTarget(b); }} disabled={processing === 'restore'}
              data-testid={`backup-restore-${b.backup_id}`}>
              <RotateCcw className="mr-2 h-4 w-4" />Pulihkan seluruh database
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => deleteBackup(b)} disabled={processing === b.backup_id}
              className="text-[hsl(var(--danger-text))]" data-testid={`backup-delete-${b.backup_id}`}>
              <Trash2 className="mr-2 h-4 w-4" />Hapus backup
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>) },
  ];

  return (
    <PageLayout testId="backup-restore-page" title="Backup data"
      subtitle="Cadangan database untuk pemulihan. Backup otomatis tiap hari pukul 02.00 WIB."
      actions={(
        <Button onClick={createBackup} data-testid="backup-create" disabled={processing === 'create'}>
          <Database />{processing === 'create' ? 'Membuat…' : 'Buat backup'}
        </Button>
      )}
      tools={<>
        <input
          type="file"
          accept=".zip,application/zip"
          onChange={e => {
            const f = e.target.files?.[0];
            if (f) handleUpload(f);   // langsung unggah, tanpa klik kedua
          }}
          style={{ display: 'none' }}
          id="backup-upload-input"
        />
        <Button variant="outline" onClick={() => document.getElementById('backup-upload-input').click()}
          data-testid="backup-upload" disabled={processing === 'upload'}>
          <FileUp />
          {processing === 'upload' ? `Mengunggah ${uploadProgress}%` : 'Unggah ZIP'}
        </Button>
        <TombolUnduh namaBerkas="daftar-backup" namaLembar="Backup" baris={backups} testId="backup-unduh-daftar" kolom={[
          { label: 'Backup', nilai: (b) => b.backup_name }, { label: 'Dibuat', nilai: (b) => formatDate(b.created_at) },
          { label: 'Ukuran', nilai: (b) => b.size }, { label: 'Database', nilai: (b) => b.database || '' },
          { label: 'Status', nilai: (b) => labelStatus(b.status).label },
        ]} />
        <Button variant="outline" size="icon" onClick={fetchBackups} data-testid="backup-refresh" disabled={loading}
          title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}>
      {processing === 'upload' && (
        <GlassCard className="p-4" data-testid="backup-upload-progress">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-sm">
            <span className="font-medium text-foreground">
              Mengunggah {uploadFile?.name || 'berkas'}
              {uploadFile ? ` (${(uploadFile.size / 1048576).toFixed(1)} MB)` : ''}
            </span>
            <span className="text-muted-foreground">
              {uploadProgress}%{uploadStage ? ` · ${uploadStage}` : ''}
            </span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-primary transition-[width] duration-300" style={{ width: `${uploadProgress}%` }} />
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            Berkas di atas 8 MB diunggah berpotong 5 MB agar tidak tertolak proxy. Jangan tutup halaman ini.
          </p>
        </GlassCard>
      )}

      {downloadHint && (
        <Notice tone="info" title={`Unduhan siap: ${downloadHint.name}`} testId="backup-download-link"
          action={<Button size="sm" variant="outline" onClick={() => setDownloadHint(null)}>Tutup</Button>}>
          Unduhan otomatis bisa diblokir browser. Kalau berkas belum turun,{' '}
          <a href={downloadHint.url} target="_blank" rel="noopener noreferrer" className="font-medium text-primary underline"
            data-testid="backup-download-manual">klik di sini untuk unduh manual</a>{' '}
          (tautan berlaku 5 menit — tekan Unduh lagi bila kedaluwarsa).
        </Notice>
      )}

      <FilterChips value={tab} onChange={(k) => setTab(k || 'backup')} hideWhenEmpty={false} testId="backup-tab"
        ariaLabel="Bagian backup" className="w-full min-w-0 flex-wrap overflow-visible pb-0 sm:w-auto" options={[
          { key: 'backup', label: 'Backup & pemulihan', count: backups.length },
          { key: 'collections', label: 'Koleksi database' },
        ]} />

      {tab === 'collections' && <DatabaseCollectionsPanel token={token} />}

      {tab === 'backup' && (<>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatTile label="Jumlah backup" value={backups.length} sub="Tersimpan di server" />
          <StatTile label="Backup terakhir" value={latestBackup ? formatDate(latestBackup.created_at).split(',')[0] : '—'}
            sub={latestBackup ? (formatDate(latestBackup.created_at).split(',').slice(1).join(',').trim() || null) : 'Belum ada backup'} />
          <StatTile label="Total ukuran" value={backups.length ? `${totalSize.toFixed(1)} MB` : '—'}
            sub={ukuranTakDikenal ? `${ukuranTakDikenal} backup tanpa data ukuran` : (backups.length ? 'Semua backup' : 'Belum ada backup')} />
          <StatTile label="Retensi" value={`${config?.retention_days || 30} hari`} sub="Backup otomatis lebih lama dihapus" />
        </div>

        {config && (
          <Notice tone="info" title="Backup otomatis"
            action={(
              <Button variant="outline" size="sm" onClick={cleanup} disabled={processing === 'cleanup'} data-testid="backup-cleanup">
                {processing === 'cleanup' ? 'Memproses…' : 'Bersihkan backup lama'}
              </Button>
            )}>
            Jadwal: {jadwal(config.auto_backup_schedule)} · Retensi: {config.retention_days} hari · Penyimpanan: {penyimpanan(config.storage_type)}
          </Notice>
        )}

        {loading && backups.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">Memuat daftar backup…</p>
        ) : (
          <TabelData kolom={kolomBackup} baris={backups} kunci={(b) => b.backup_id} testId="backup-table"
            kosong={<EmptyState title="Belum ada backup" description="Tekan Buat backup untuk membuat backup pertama." />} />
        )}
      </>)}

      {restoreTarget && (
        <DetailPopup open onClose={() => { if (processing !== 'restore') { setRestoreTarget(null); setRestoreError(null); } }}
          testId="restore-dialog" judul="Pulihkan seluruh database?"
          keterangan="Seluruh database saat ini diganti dengan isi backup ini. Semua perubahan setelah backup dibuat akan hilang."
          aksi={<>
            <Button variant="outline" size="sm" onClick={() => { setRestoreTarget(null); setRestoreError(null); }}
              data-testid="restore-cancel" disabled={processing === 'restore'}>Batal</Button>
            <Button variant="destructive" size="sm" onClick={restoreBackup} disabled={processing === 'restore'} data-testid="restore-confirm">
              {processing === 'restore' ? <><RefreshCw className="animate-spin" />Memulihkan…</> : <><RotateCcw />Pulihkan sekarang</>}
            </Button>
          </>}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Backup"><span className="break-all font-mono">{restoreTarget.backup_name}</span></BarisDetail>
            <BarisDetail label="Dibuat">{formatDate(restoreTarget.created_at)}</BarisDetail>
            <BarisDetail label="Ukuran">{restoreTarget.size}</BarisDetail>
          </dl>
          <Notice tone="warning" title="Proses pemulihan akan:">
            <ul className="mt-1 list-inside list-disc space-y-0.5">
              <li>Menghapus database saat ini</li>
              <li>Memulihkan data dari backup</li>
              <li>Menyalakan ulang semua layanan</li>
              <li>Berlangsung 30 detik – 5 menit (tergantung ukuran database)</li>
            </ul>
          </Notice>
          {restoreError && (
            <Notice tone="danger" title={<span data-testid="restore-error-title">{restoreError.message}</span>} testId="restore-error-panel">
              <div className="space-y-2 text-sm">
                <p><span className="font-medium">Sebab: </span><span data-testid="restore-error-reason">{restoreError.reason}</span></p>
                {restoreError.hint && (
                  <p><span className="font-medium">Saran perbaikan: </span><span data-testid="restore-error-hint">{restoreError.hint}</span></p>
                )}
                {(restoreError.returncode !== null && restoreError.returncode !== undefined) && (
                  <p><span className="font-medium">Kode keluar proses: </span><code className="font-mono">{restoreError.returncode}</code></p>
                )}
                {restoreError.logLines && restoreError.logLines.length > 0 && (
                  <details>
                    <summary className="cursor-pointer select-none font-medium">Log teknis ({restoreError.logLines.length} baris)</summary>
                    <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded border border-[var(--glass-border)] bg-[var(--glass-bg)] p-2 text-xs leading-relaxed"
                      data-testid="restore-error-log">{restoreError.logLines.join('\n')}</pre>
                  </details>
                )}
                {restoreError.logPath && (
                  <p>Log lengkap: <code className="break-all font-mono">{restoreError.logPath}</code></p>
                )}
              </div>
            </Notice>
          )}
        </DetailPopup>
      )}

      <FormPopup open={!!selectiveRestore} onClose={() => setSelectiveRestore(null)} ukuran="panjang" testId="selective-restore-dialog"
        judul={`Pulihkan koleksi terpilih: ${selectiveRestore?.backup_name || ''}`}
        keterangan="Pilih koleksi yang ingin dipulihkan dari backup ini dan cara pemulihannya."
        onSimpan={confirmSelectiveRestore} menyimpan={processing === 'selective-restore'} bisaSimpan={selectedCollections.length > 0}
        labelSimpan={`Pulihkan ${selectedCollections.length} koleksi`}>
        <Isian label="Cara pemulihan">
          <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Cara pemulihan">
            {[
              ['overwrite', 'Timpa (hapus lalu pulihkan)', 'Koleksi yang ada dihapus, lalu diisi dari backup (bawaan).'],
              ['merge', 'Gabung (hanya tambah)', 'Data dari backup ditambahkan tanpa menghapus data yang sudah ada.'],
            ].map(([m, judul, ket]) => (
              <label key={m} className={`cursor-pointer rounded-lg border p-3 text-sm ${restoreMode === m ? 'border-primary bg-primary/10' : 'border-[var(--glass-border)]'}`}
                data-testid={`mode-${m}`}>
                <span className="flex items-center gap-2 font-medium">
                  <input type="radio" name="restore-mode" checked={restoreMode === m} onChange={() => setRestoreMode(m)}
                    className="accent-[hsl(var(--primary))]" />
                  {judul}
                </span>
                <span className="mt-1 block text-xs text-muted-foreground">{ket}</span>
              </label>
            ))}
          </div>
        </Isian>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" size="sm" variant="outline" onClick={selectAllCollections} data-testid="select-all-collections">
            Pilih semua ({collections.length})
          </Button>
          <Button type="button" size="sm" variant="outline" onClick={clearSelections}>Kosongkan pilihan</Button>
          <span className="text-sm text-muted-foreground">{selectedCollections.length} dari {collections.length} koleksi dipilih</span>
        </div>
        <div className="max-h-96 overflow-y-auto rounded-lg border border-[var(--glass-border)]">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10"><span className="sr-only">Pilih</span></TableHead>
                <TableHead>Koleksi</TableHead>
                <TableHead className="text-right">Dokumen</TableHead>
                <TableHead className="text-right">Ukuran</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {collections.map(collection => {
                const on = selectedCollections.includes(collection.name);
                return (
                  <TableRow key={collection.name} onClick={() => toggleCollection(collection.name)} className="cursor-pointer"
                    data-testid={`collection-${collection.name}`}>
                    <TableCell>
                      <input type="checkbox" checked={on} readOnly className="h-4 w-4 accent-[hsl(var(--primary))]"
                        aria-label={`Pilih ${labelKoleksi(collection.name)}`} />
                    </TableCell>
                    <TableCell className="text-sm" title={collection.name}>{labelKoleksi(collection.name)}</TableCell>
                    <TableCell className="text-right tabular-nums">{Number(collection.document_count || 0).toLocaleString('id-ID')}</TableCell>
                    <TableCell className="whitespace-nowrap text-right tabular-nums">{collection.size_mb} MB</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      </FormPopup>
    </PageLayout>
  );
}

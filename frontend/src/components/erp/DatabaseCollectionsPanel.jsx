/**
 * DatabaseCollectionsPanel — jelajah koleksi database aktif & pengosongan terpilih.
 * Dipakai di dalam BackupRestoreModule (tab "Koleksi database").
 *
 * Sengaja berlapis pengaman: koleksi fondasi (pengguna, hak akses, counter,
 * bagan akun) terkunci, wajib mengetik KOSONGKAN, dan cadangan pengaman dibuat
 * lebih dulu secara bawaan.
 *
 * Standar UI/UX v2 (8 Nov 2026): satu baris penyaring (cari + kelompok), daftar 268 koleksi = tabel bercentang
 * (dulu kisi kotak per kelompok), unduh Excel/CSV, konfirmasi = popup standar dengan tombol merah. Nama koleksi
 * tetap tampil apa adanya karena itulah yang dikosongkan (API tidak punya nama tampilan).
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Loader2, Lock, RefreshCw, Search, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup from '@/components/ui/detail-popup';
import { GlassCard } from '@/components/ui/glass';
import { Notice, StatusBadge } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL || '';

export default function DatabaseCollectionsPanel({ token }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState([]);
  const [filter, setFilter] = useState('');
  const [kelompok, setKelompok] = useState('');
  const [showConfirm, setShowConfirm] = useState(false);
  const [confirmText, setConfirmText] = useState('');
  const [createBackup, setCreateBackup] = useState(true);
  const [allowProtected, setAllowProtected] = useState(false);
  const [unlocked, setUnlocked] = useState(false);
  const [busy, setBusy] = useState(false);

  const h = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/admin/backup/live-collections`, { headers: h });
      if (!r.ok) throw new Error((await r.json()).detail || `Kode ${r.status}`);
      setData(await r.json());
      setSelected([]);
    } catch (e) { toast.error(e.message); } finally { setLoading(false); }
  }, [h]);

  useEffect(() => { load(); }, [load]);

  const toggle = (name) => setSelected(s => s.includes(name) ? s.filter(x => x !== name) : [...s, name]);

  // Koleksi fondasi tetap terlihat, tapi baru bisa dicentang setelah kunci dibuka
  // secara sadar. Backend juga menolaknya lagi (pengaman berlapis).
  const lockedFor = (c) => c.protected && !unlocked;

  const visible = (data?.collections || []).filter(c => {
    const q = filter.trim().toLowerCase();
    return (!kelompok || c.group === kelompok) && (!q || c.name.toLowerCase().includes(q) || c.group.toLowerCase().includes(q));
  });

  // "Pilih semua yang boleh" untuk baris yang sedang tampil (bukan koleksi terlindungi).
  const pilihTampil = () => {
    const names = visible.filter(c => !c.protected).map(c => c.name);
    const allOn = names.length > 0 && names.every(n => selected.includes(n));
    setSelected(s => allOn ? s.filter(n => !names.includes(n)) : [...new Set([...s, ...names])]);
  };

  const selectedDocs = selected.reduce((sum, n) =>
    sum + ((data?.collections || []).find(c => c.name === n)?.count || 0), 0);
  const selectedProtected = selected.filter(n =>
    (data?.collections || []).find(c => c.name === n)?.protected);

  const runClear = async () => {
    setBusy(true);
    try {
      const r = await fetch(`${API}/api/admin/backup/clear-collections`, {
        method: 'POST', headers: h,
        body: JSON.stringify({
          collections: selected, confirm_text: confirmText,
          create_backup: createBackup, allow_protected: allowProtected,
        }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `Kode ${r.status}`);
      toast.success(`${d.cleared.length} koleksi dikosongkan · ${d.total_deleted} dokumen dihapus`
        + (d.safety_backup ? ` · cadangan: ${d.safety_backup}` : ''));
      if (d.failed?.length) toast.error(`${d.failed.length} koleksi gagal dikosongkan`);
      setShowConfirm(false); setConfirmText(''); setAllowProtected(false);
      await load();
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };

  if (loading && !data) {
    return <p className="py-10 text-center text-sm text-muted-foreground" data-testid="collections-loading">Memuat koleksi…</p>;
  }

  return (
    <div className="space-y-4" data-testid="db-collections-panel">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder="Cari koleksi" value={filter} onChange={e => setFilter(e.target.value)} className="pl-8"
            data-testid="collections-search" />
        </div>
        <SmartNativeSelect value={kelompok} onChange={(e) => setKelompok(e.target.value)} className="w-full"
          wrapperClassName="w-full sm:w-52" aria-label="Kelompok" data-testid="collections-group-filter">
          <option value="">Semua kelompok</option>
          {(data?.groups || []).map((g) => <option key={g} value={g}>{g}</option>)}
        </SmartNativeSelect>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input type="checkbox" checked={unlocked} className="h-4 w-4 accent-[hsl(var(--primary))]"
            onChange={e => { setUnlocked(e.target.checked); if (!e.target.checked) setSelected(sel => sel.filter(n => !(data?.collections || []).find(c => c.name === n)?.protected)); }}
            data-testid="collections-unlock-protected" />
          <Lock className="h-3.5 w-3.5" />Buka kunci koleksi terlindungi
        </label>
        <div className="ml-auto flex items-center gap-2">
          <TombolUnduh namaBerkas="koleksi-database" namaLembar="Koleksi" baris={visible} testId="collections-unduh" kolom={[
            { label: 'Koleksi', nilai: (c) => c.name }, { label: 'Kelompok', nilai: (c) => c.group },
            { label: 'Dokumen', nilai: (c) => c.count }, { label: 'Terlindungi', nilai: (c) => (c.protected ? 'Ya' : 'Tidak') },
          ]} />
          <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
            data-testid="collections-refresh">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
        </div>
      </div>

      <p className="text-sm text-muted-foreground" data-testid="collections-summary">
        {data?.total_collections} koleksi · {data?.total_documents?.toLocaleString('id-ID')} dokumen · database aktif{' '}
        <span className="font-mono">{data?.database}</span>
        {visible.length !== (data?.collections || []).length && ` · ${visible.length} tampil`}
      </p>

      {selected.length > 0 && (
        <Notice tone="danger" testId="collections-action-bar"
          action={(
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onClick={() => setSelected([])} data-testid="collections-clear-selection">Batal pilih</Button>
              <Button variant="destructive" size="sm" onClick={() => setShowConfirm(true)} data-testid="collections-clear-btn">
                <Trash2 />Kosongkan
              </Button>
            </div>
          )}>
          <b>{selected.length}</b> koleksi dipilih · <b>{selectedDocs.toLocaleString('id-ID')}</b> dokumen akan dihapus
          {selectedProtected.length > 0 && <> · {selectedProtected.length} di antaranya koleksi terlindungi</>}
        </Notice>
      )}

      <GlassCard className="overflow-hidden p-0">
        <div className="max-h-[70vh] overflow-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">
                  <input type="checkbox" className="h-4 w-4 accent-[hsl(var(--destructive))]" aria-label="Pilih semua yang boleh"
                    title="Pilih semua yang boleh (yang tampil)" onChange={pilihTampil}
                    checked={visible.some(c => !c.protected) && visible.filter(c => !c.protected).every(c => selected.includes(c.name))} />
                </TableHead>
                <TableHead>Koleksi</TableHead>
                <TableHead>Kelompok</TableHead>
                <TableHead className="text-right">Dokumen</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.length === 0 ? (
                <TableRow><TableCell colSpan={4} className="py-8 text-center text-sm text-muted-foreground">Tidak ada koleksi yang cocok.</TableCell></TableRow>
              ) : visible.map(c => (
                <TableRow key={c.name} data-testid={`collection-item-${c.name}`}
                  className={lockedFor(c) ? 'opacity-60' : 'cursor-pointer'}
                  title={lockedFor(c) ? 'Koleksi fondasi — buka kuncinya dulu di atas' : undefined}
                  onClick={() => { if (!lockedFor(c)) toggle(c.name); }}>
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={selected.includes(c.name)} onChange={() => toggle(c.name)}
                      disabled={lockedFor(c)} aria-label={`Pilih ${c.name}`}
                      className="h-4 w-4 accent-[hsl(var(--destructive))]" data-testid={`collection-check-${c.name}`} />
                  </TableCell>
                  <TableCell>
                    <span className="break-all font-mono text-sm">{c.name}</span>
                    {c.protected && <StatusBadge status="lock" label="Terlindungi" tone="warning" className="ml-2" />}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">{c.group}</TableCell>
                  <TableCell className="text-right tabular-nums">{c.count.toLocaleString('id-ID')}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </GlassCard>

      {showConfirm && (
        <DetailPopup open onClose={() => { if (!busy) setShowConfirm(false); }} testId="clear-confirm-dialog"
          judul={`Kosongkan ${selected.length} koleksi?`}
          keterangan={`${selectedDocs.toLocaleString('id-ID')} dokumen akan dihapus permanen dari database aktif. Struktur koleksi tetap ada, isinya saja yang dikosongkan.`}
          aksi={<>
            <Button variant="outline" size="sm" onClick={() => setShowConfirm(false)} disabled={busy} data-testid="clear-cancel">Batal</Button>
            <Button variant="destructive" size="sm" onClick={runClear}
              disabled={busy || confirmText.trim().toUpperCase() !== 'KOSONGKAN'} data-testid="clear-confirm">
              {busy ? <><Loader2 className="animate-spin" />Memproses…</> : 'Kosongkan sekarang'}
            </Button>
          </>}>
          <div className="max-h-32 space-y-0.5 overflow-y-auto rounded-md border border-[var(--glass-border)] p-2 font-mono text-xs">
            {selected.map(n => <div key={n}>{n}</div>)}
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={createBackup} onChange={e => setCreateBackup(e.target.checked)}
              className="h-4 w-4 accent-[hsl(var(--primary))]" data-testid="clear-backup-toggle" />
            Buat cadangan pengaman dulu <span className="text-xs text-muted-foreground">(sangat disarankan)</span>
          </label>

          {selectedProtected.length > 0 && (
            <label className="flex items-start gap-2 text-sm text-[hsl(var(--danger-text))]">
              <input type="checkbox" checked={allowProtected} onChange={e => setAllowProtected(e.target.checked)}
                className="mt-0.5 h-4 w-4 accent-[hsl(var(--destructive))]" data-testid="clear-protected-toggle" />
              <span>Izinkan koleksi terlindungi ({selectedProtected.join(', ')}). Ini bisa membuat sistem tidak bisa dipakai.</span>
            </label>
          )}

          <div className="space-y-1">
            <label htmlFor="clear-confirm-input" className="text-sm text-muted-foreground">Ketik <b>KOSONGKAN</b> untuk melanjutkan:</label>
            <Input id="clear-confirm-input" value={confirmText} onChange={e => setConfirmText(e.target.value)}
              placeholder="KOSONGKAN" className="font-mono sm:w-64" data-testid="clear-confirm-input" />
          </div>
        </DetailPopup>
      )}
    </div>
  );
}

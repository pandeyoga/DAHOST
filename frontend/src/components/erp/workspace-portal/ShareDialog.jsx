/**
 * ShareDialog — beri/cabut akses dokumen Workspace.
 *
 * Cari pengguna (jeda 300 ms) → beri akses lihat/ubah → daftar akses saat ini (ubah akses + cabut).
 * Standar UI/UX v2 (8 Nov 2026): DetailPopup standar, pilihan SmartNativeSelect, cabut lewat konfirmasi aplikasi
 * (dulu window.confirm), label Indonesia. Panggilan server tidak berubah.
 */
import { useState, useEffect, useRef } from 'react';
import { toast } from 'sonner';
import { Crown, Eye, Loader2, Pencil, Search, X } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import DetailPopup from '@/components/ui/detail-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { StatusBadge } from '../moduleAtoms';

import { apicall } from './utils';

const LABEL_AKSES = { view: 'lihat saja', edit: 'bisa ubah', admin: 'admin' };

export default function ShareDialog({ open, onClose, document: doc, token, onShared }) {
  const [search, setSearch] = useState('');
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [shares, setShares] = useState([]);
  const [busy, setBusy] = useState(null);
  const timerRef = useRef(null);

  useEffect(() => {
    if (open && doc) {
      setShares(doc.permissions?.shared_with || []);
      setSearch('');
      setResults([]);
    }
  }, [open, doc]);

  const handleSearch = (q) => {
    setSearch(q);
    clearTimeout(timerRef.current);
    if (!q.trim()) { setResults([]); return; }
    timerRef.current = setTimeout(async () => {
      setSearching(true);
      try {
        const data = await apicall('GET', `/api/auth/users?search=${encodeURIComponent(q)}&limit=10`, token);
        const ex = new Set([...(shares.map((s) => s.user_id)), doc?.owner_id]);
        setResults(Array.isArray(data) ? data.filter((u) => !ex.has(u.id)) : []);
      } catch {
        setResults([]);
      } finally {
        setSearching(false);
      }
    }, 300);
  };

  const handleAdd = async (user, access = 'view') => {
    setBusy(user.id);
    try {
      await apicall('POST', `/api/workspace/documents/${doc.id}/share`, token, { user_id: user.id, access });
      const ns = { user_id: user.id, user_name: user.name, access };
      const newShares = [...shares, ns];
      setShares(newShares);
      setResults((prev) => prev.filter((u) => u.id !== user.id));
      toast.success(`${user.name} diberi akses ${LABEL_AKSES[access] || access}`);
      if (onShared) onShared({ ...doc, permissions: { ...doc.permissions, shared_with: newShares } });
    } catch (e) { toast.error(e.message); } finally { setBusy(null); }
  };

  const handleChangeAccess = async (userId, access) => {
    setBusy(userId);
    try {
      await apicall('POST', `/api/workspace/documents/${doc.id}/share`, token, { user_id: userId, access });
      setShares((prev) => prev.map((s) => (s.user_id === userId ? { ...s, access } : s)));
    } catch (e) { toast.error(e.message); } finally { setBusy(null); }
  };

  const handleRevoke = async (userId, name) => {
    if (!(await confirmDialog({ title: `Cabut akses ${name}?`, body: 'Orang ini tidak bisa membuka dokumen ini lagi.',
      confirmLabel: 'Cabut akses', danger: true }))) return;
    setBusy(userId);
    try {
      await apicall('DELETE', `/api/workspace/documents/${doc.id}/share/${userId}`, token);
      setShares((prev) => prev.filter((s) => s.user_id !== userId));
      toast.success(`Akses ${name} dicabut`);
    } catch (e) { toast.error(e.message); } finally { setBusy(null); }
  };

  if (!doc) return null;
  return (
    <DetailPopup open={open} onClose={onClose} judul={`Bagikan "${doc.name}"`} testId="share-dialog"
      keterangan="Cari nama pengguna, lalu beri akses lihat saja atau bisa ubah.">
      <div className="space-y-2">
        <div className="relative w-full sm:w-80">
          {searching
            ? <Loader2 className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-muted-foreground" />
            : <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />}
          <Input placeholder="Cari pengguna" value={search} onChange={(e) => handleSearch(e.target.value)}
            className="pl-8" data-testid="share-search-input" />
        </div>
        {results.length > 0 && (
          <div className="divide-y divide-[var(--glass-border)] rounded-lg border border-[var(--glass-border)]">
            {results.map((u) => (
              <div key={u.id} className="flex flex-wrap items-center justify-between gap-2 p-2.5">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-foreground">{u.name}</p>
                  <p className="text-xs text-muted-foreground">{u.email}</p>
                </div>
                <div className="flex gap-1.5">
                  <Button size="sm" variant="outline" disabled={busy === u.id} onClick={() => handleAdd(u, 'view')}><Eye />Lihat saja</Button>
                  <Button size="sm" disabled={busy === u.id} onClick={() => handleAdd(u, 'edit')}><Pencil />Bisa ubah</Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="space-y-1">
        <p className="text-sm font-medium text-foreground">Akses saat ini</p>
        <div className="flex items-center justify-between gap-2 rounded-md px-2 py-2">
          <div className="flex items-center gap-2">
            <Crown className="h-4 w-4 text-primary" />
            <div>
              <p className="text-sm font-medium text-foreground">{doc.owner_name || 'Pemilik'}</p>
              <p className="text-xs text-muted-foreground">Pemilik dokumen</p>
            </div>
          </div>
          <StatusBadge status="pemilik" label="Pemilik" tone="primary" />
        </div>
        {shares.length === 0 && <p className="py-3 text-center text-sm text-muted-foreground">Belum dibagikan ke siapa pun.</p>}
        {shares.map((s) => (
          <div key={s.user_id} className="flex flex-wrap items-center justify-between gap-2 rounded-md px-2 py-2">
            <p className="text-sm text-foreground">{s.user_name}</p>
            <div className="flex items-center gap-2">
              <SmartNativeSelect value={s.access} onChange={(e) => handleChangeAccess(s.user_id, e.target.value)} disabled={!!busy}
                searchable={false} className="h-8 w-32" wrapperClassName="w-32" aria-label={`Akses ${s.user_name}`}>
                <option value="view">Lihat saja</option>
                <option value="edit">Bisa ubah</option>
                <option value="admin">Admin</option>
              </SmartNativeSelect>
              <Button variant="ghost" size="icon-sm" disabled={busy === s.user_id} onClick={() => handleRevoke(s.user_id, s.user_name)}
                title="Cabut akses" aria-label="Cabut akses" data-testid={`share-revoke-${s.user_id}`}>
                {busy === s.user_id ? <Loader2 className="animate-spin" /> : <X />}
              </Button>
            </div>
          </div>
        ))}
      </div>
    </DetailPopup>
  );
}

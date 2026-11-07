/**
 * Popup Pusat komunikasi: buat kanal dan mulai pesan langsung.
 * Standar UI/UX v2 (8 Nov 2026): buat kanal = FormPopup pendek; pilih pengguna = DetailPopup berisi daftar
 * (dulu Dialog buatan sendiri + tombol mentah). Isian & panggilan server tidak berubah.
 */
import { useState, useEffect } from 'react';
import { toast } from 'sonner';
import { Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup from '@/components/ui/detail-popup';

import { apicall, initials, avatarColor } from './utils';

export function CreateChannelDialog({ open, onClose, token, onCreated }) {
  const [form, setForm] = useState({ name: '', description: '', type: 'public' });
  const [loading, setLoading] = useState(false);

  const submit = async () => {
    if (!form.name.trim()) {
      toast.error('Nama kanal wajib diisi');
      return;
    }
    setLoading(true);
    try {
      const data = await apicall('POST', '/api/comm/channels', token, form);
      if (data.id) {
        toast.success(`Kanal #${data.name} dibuat`);
        onCreated(data);
        onClose();
      } else {
        toast.error(data.detail || 'Gagal membuat kanal');
      }
    } catch {
      toast.error('Gagal membuat kanal');
    } finally {
      setLoading(false);
    }
  };

  return (
    <FormPopup open={open} onClose={onClose} ukuran="pendek" judul="Kanal baru" onSimpan={submit} menyimpan={loading}
      labelSimpan="Buat kanal" testId="create-channel-dialog">
      <Isian label="Nama kanal" wajib htmlFor="channel-name">
        <Input id="channel-name" placeholder="Mis. umum, produksi, keuangan" value={form.name}
          onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))} data-testid="channel-name-input" />
      </Isian>
      <Isian label="Deskripsi" petunjuk="Opsional." htmlFor="channel-desc">
        <Input id="channel-desc" placeholder="Deskripsi singkat" value={form.description}
          onChange={(e) => setForm((p) => ({ ...p, description: e.target.value }))} />
      </Isian>
      <Isian label="Jenis">
        <SmartNativeSelect value={form.type} onChange={(e) => setForm((p) => ({ ...p, type: e.target.value }))} searchable={false}
          className="h-9 w-full" aria-label="Jenis kanal">
          <option value="public">Publik (semua anggota)</option>
          <option value="private">Privat (anggota pilihan)</option>
          <option value="department">Departemen</option>
        </SmartNativeSelect>
      </Isian>
    </FormPopup>
  );
}

export function NewDMDialog({ open, onClose, token, currentUserId, onStartDM }) {
  const [users, setUsers] = useState([]);
  const [search, setSearch] = useState('');

  useEffect(() => {
    if (!open) return;
    apicall('GET', '/api/auth/users?limit=100', token)
      .then((d) => setUsers(Array.isArray(d) ? d.filter((u) => u.id !== currentUserId) : []))
      .catch(() => {});
  }, [open, token, currentUserId]);

  const filtered = users.filter(
    (u) => u.name?.toLowerCase().includes(search.toLowerCase()) || u.email?.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <DetailPopup open={open} onClose={onClose} judul="Pesan langsung" keterangan="Pilih pengguna untuk memulai percakapan."
      testId="new-dm-dialog">
      <div className="relative w-full sm:w-72">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input placeholder="Cari pengguna" value={search} onChange={(e) => setSearch(e.target.value)} className="pl-8" />
      </div>
      <ScrollArea className="h-72">
        <div className="space-y-1">
          {filtered.map((u) => (
            <Button key={u.id} type="button" variant="ghost" onClick={() => { onStartDM(u); onClose(); }}
              className="h-auto w-full justify-start gap-3 px-3 py-2 text-left font-normal">
              <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold text-foreground ${avatarColor(u.id)}`}>
                {initials(u.name)}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium">{u.name}</span>
                <span className="block truncate text-xs text-muted-foreground">{u.email}</span>
              </span>
            </Button>
          ))}
          {filtered.length === 0 && <p className="py-4 text-center text-sm text-muted-foreground">Tidak ada pengguna ditemukan</p>}
        </div>
      </ScrollArea>
    </DetailPopup>
  );
}

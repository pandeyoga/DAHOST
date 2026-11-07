/**
 * NotificationPrefsDialog — "Notifikasi Saya" (preferensi per pengguna).
 *
 * MENGAPA ADA: backend sudah lama punya `GET/PUT /api/notifications/my-category-prefs`
 * (setiap orang boleh membisukan kategori untuk dirinya sendiri) tetapi TIDAK ADA
 * layarnya, jadi fiturnya tidak pernah bisa dipakai. Dialog ini dibuka dari ikon
 * gerigi di dropdown bel sehingga bisa dijangkau dari portal mana pun.
 *
 * ATURAN YANG DITAMPILKAN JUJUR KE PENGGUNA:
 *   · Kategori yang tidak dibuka admin untuk peran Anda tidak muncul di sini.
 *   · Kategori "Untuk Saya" selalu aktif dan tidak bisa dibisukan — isinya
 *     notifikasi yang memang dialamatkan langsung kepada Anda.
 *
 * Standar UI/UX v2 (8 Nov 2026): FormPopup standar (Batal · Simpan hijau), saklar per kategori, warna token.
 */
import { useCallback, useEffect, useState } from 'react';
import { Lock } from 'lucide-react';
import { toast } from 'sonner';
import { Switch } from '@/components/ui/switch';
import FormPopup from '@/components/ui/form-popup';
import { Notice } from './moduleAtoms';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

export default function NotificationPrefsDialog({ token, onClose, onSaved }) {
  const [data, setData] = useState(null);
  const [muted, setMuted] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  const load = useCallback(async () => {
    setLoading(true); setErr('');
    try {
      const r = await fetch(`${BACKEND_URL}/api/notifications/my-category-prefs`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body.detail || `Kode ${r.status}`);
      setData(body);
      setMuted(body.muted_categories || []);
    } catch (e) {
      setErr(e.message || 'Gagal memuat preferensi notifikasi');
    } finally { setLoading(false); }
     
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const locked = data?.locked_categories || ['personal'];
  const cats = data?.categories || [];

  const toggle = (key) => {
    if (locked.includes(key)) return;
    setMuted((m) => (m.includes(key) ? m.filter((x) => x !== key) : [...m, key]));
  };

  const save = async () => {
    setSaving(true);
    try {
      const r = await fetch(`${BACKEND_URL}/api/notifications/my-category-prefs`, {
        method: 'PUT',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ muted_categories: muted.filter((c) => !locked.includes(c)) }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body.detail || `Kode ${r.status}`);
      const off = (body.muted_categories || []).length;
      toast.success('Preferensi notifikasi disimpan', {
        description: off
          ? `${off} kategori dibisukan untuk akun Anda`
          : 'Semua kategori yang tersedia aktif',
      });
      onSaved?.();
      onClose?.();
    } catch (e) {
      toast.error('Gagal menyimpan preferensi', { description: e.message });
    } finally { setSaving(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="notif-prefs-dialog" judul="Notifikasi saya"
      keterangan="Matikan kategori yang tidak Anda perlukan. Yang dimatikan berhenti muncul di lonceng hanya untuk akun Anda."
      onSimpan={save} menyimpan={saving} bisaSimpan={!loading} galat={err || null}>
      <p className="text-xs text-muted-foreground">
        Rekan lain tidak terpengaruh. Kategori yang belum dibuka admin untuk peran Anda tidak ditampilkan di sini.
      </p>
      {loading ? (
        <p className="py-8 text-center text-sm text-muted-foreground">Memuat preferensi…</p>
      ) : cats.length === 0 ? (
        <Notice tone="info">Belum ada kategori notifikasi yang dibuka untuk peran Anda.</Notice>
      ) : (
        <ul className="divide-y divide-[var(--glass-border)] rounded-lg border border-[var(--glass-border)]">
          {cats.map((c) => {
            const isLocked = locked.includes(c.key);
            const isOff = muted.includes(c.key) && !isLocked;
            return (
              <li key={c.key} className="flex items-center justify-between gap-3 px-3 py-2.5">
                <div className="min-w-0">
                  <p className="flex items-center gap-1.5 text-sm font-medium text-foreground">
                    {c.label}
                    {isLocked && (
                      <span className="inline-flex items-center gap-1 text-xs font-normal text-muted-foreground">
                        <Lock className="h-3 w-3" /> selalu aktif
                      </span>
                    )}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {isLocked
                      ? 'Notifikasi yang dialamatkan langsung kepada Anda — tidak bisa dibisukan.'
                      : isOff ? 'Dibisukan — tidak muncul di lonceng Anda.' : 'Aktif — muncul di lonceng Anda.'}
                  </p>
                </div>
                <Switch checked={!isOff} disabled={isLocked} onCheckedChange={() => toggle(c.key)}
                  aria-label={`${c.label} ${isOff ? 'dibisukan' : 'aktif'}`} data-testid={`notif-pref-${c.key}`} />
              </li>
            );
          })}
        </ul>
      )}
    </FormPopup>
  );
}

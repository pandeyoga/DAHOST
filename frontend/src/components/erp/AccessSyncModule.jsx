// Cek Sinkron Akun — audit akun <-> peran <-> hak akses efektif (superadmin).
import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, RefreshCw, Wrench, Eye } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../ui/dialog';

const API = process.env.REACT_APP_BACKEND_URL;
const ACT = { view: 'Lihat', create: 'Tambah', edit: 'Ubah', delete: 'Hapus', approve: 'Approve', export: 'Export' };

function UserDetail({ uid, token, onClose }) {
  const [d, setD] = useState(null);
  useEffect(() => {
    if (!uid) return;
    setD(null);
    fetch(`${API}/api/admin/access-sync/user/${uid}`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.json()).then(setD).catch(() => setD({ error: true }));
  }, [uid, token]);
  const byModule = {};
  (d?.granular || []).forEach((g) => { (byModule[g.module] ||= { ...g, acts: [] }).acts.push(g.action); });
  return (
    <Dialog open={!!uid} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto" data-testid="access-sync-detail">
        <DialogHeader><DialogTitle>Akses efektif {d?.email || ''}</DialogTitle></DialogHeader>
        {!d ? <p className="text-sm text-muted-foreground">Memuat…</p> : (
          <div className="space-y-4 text-sm">
            <p>Peran: <b data-testid="access-sync-detail-role">{d.role}</b>{d.is_super && ' (akses penuh)'}</p>
            <div>
              <p className="mb-1 text-xs font-semibold uppercase text-muted-foreground">Portal yang bisa dibuka</p>
              <div className="flex flex-wrap gap-1.5" data-testid="access-sync-detail-portals">
                {(d.portals || []).map((p) => <Badge key={p} variant="outline">{p}</Badge>)}
              </div>
            </div>
            <div>
              <p className="mb-1 text-xs font-semibold uppercase text-muted-foreground">
                Izin per modul ({Object.keys(byModule).length} modul)
              </p>
              {Object.keys(byModule).length === 0 ? (
                <p className="text-xs text-muted-foreground">Belum ada izin per modul — aturan bawaan peran yang berlaku.</p>
              ) : (
                <ul className="space-y-1" data-testid="access-sync-detail-modules">
                  {Object.values(byModule).map((m) => (
                    <li key={m.module} className="flex flex-wrap items-center gap-1.5 text-xs">
                      <span className="font-medium">{m.label}</span>
                      <span className="text-muted-foreground">({m.portal})</span>
                      {m.acts.map((a) => <Badge key={a} className="text-[10px]">{ACT[a] || a}</Badge>)}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              Menu disembunyikan: {d.hidden_count} · Total izin: {d.perm_count}
            </p>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default function AccessSyncModule({ token }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [detail, setDetail] = useState(null);
  const headers = { Authorization: `Bearer ${token}` };

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const r = await fetch(`${API}/api/admin/access-sync/audit`, { headers: { Authorization: `Bearer ${token}` } });
      if (!r.ok) throw new Error((await r.json()).detail || 'Gagal memuat');
      setData(await r.json());
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const fixAll = async () => {
    setBusy(true);
    try {
      const r = await fetch(`${API}/api/admin/access-sync/fix`, { method: 'POST', headers });
      const j = await r.json();
      toast.success(`${j.fixed} akun disinkronkan`);
      await load();
    } catch { toast.error('Gagal menyinkronkan'); setBusy(false); }
  };

  const s = data?.summary;
  return (
    <div className="space-y-4" data-testid="access-sync-module">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold">Cek Sinkron Akun</h3>
          <p className="text-xs text-muted-foreground">
            Memastikan setiap akun memakai peran & hak akses yang sama dengan yang diatur. Perubahan peran berlaku
            langsung (tanpa login ulang) — layar pengguna menyegarkan akses otomatis.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={load} disabled={busy} data-testid="access-sync-refresh">
            <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${busy ? 'animate-spin' : ''}`} /> Cek ulang
          </Button>
          <Button size="sm" onClick={fixAll} disabled={busy || !s?.fixable} data-testid="access-sync-fix">
            <Wrench className="mr-1.5 h-3.5 w-3.5" /> Sinkronkan ({s?.fixable || 0})
          </Button>
        </div>
      </div>
      {s && (
        <div className="flex flex-wrap gap-2 text-xs" data-testid="access-sync-summary">
          <Badge variant="outline">Total {s.total}</Badge>
          <Badge className="bg-emerald-600/15 text-emerald-600" data-testid="access-sync-ok">Sinkron {s.ok}</Badge>
          <Badge className="bg-red-600/15 text-red-600" data-testid="access-sync-error">Bermasalah {s.error}</Badge>
        </div>
      )}
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-xs">
          <thead className="bg-muted/40 text-left text-muted-foreground">
            <tr><th className="p-2">Akun</th><th className="p-2">Peran</th><th className="p-2">Portal</th>
              <th className="p-2">Izin</th><th className="p-2">Status</th><th className="p-2" /></tr>
          </thead>
          <tbody>
            {(data?.users || []).map((u) => (
              <tr key={u.id} className="border-t border-border/60" data-testid={`access-sync-row-${u.email}`}>
                <td className="p-2"><div className="font-medium">{u.name}</div><div className="text-muted-foreground">{u.email}</div></td>
                <td className="p-2">{u.role}{!u.active && <Badge variant="outline" className="ml-1 text-[10px]">nonaktif</Badge>}</td>
                <td className="p-2 max-w-[260px]">{u.is_super ? 'Semua' : u.portals.filter((p) => !['self', 'collaboration'].includes(p)).join(', ') || '—'}</td>
                <td className="p-2">{u.is_super ? 'Penuh' : u.perm_count}{u.granular_portals.length > 0 && <span className="text-muted-foreground"> · per modul: {u.granular_portals.join(', ')}</span>}</td>
                <td className="p-2">
                  {u.status === 'ok' ? (
                    <span className="inline-flex items-center gap-1 text-emerald-600"><CheckCircle2 className="h-3.5 w-3.5" /> Sinkron</span>
                  ) : (
                    <span className="inline-flex flex-col gap-0.5 text-red-600">
                      {u.issues.filter((i) => i.severity !== 'info').map((i) => (
                        <span key={i.code} className="inline-flex items-center gap-1"><AlertTriangle className="h-3.5 w-3.5" />{i.message}</span>
                      ))}
                    </span>
                  )}
                </td>
                <td className="p-2 text-right">
                  <Button variant="ghost" size="sm" onClick={() => setDetail(u.id)} data-testid={`access-sync-view-${u.email}`}>
                    <Eye className="mr-1 h-3.5 w-3.5" /> Lihat akses
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <UserDetail uid={detail} token={token} onClose={() => setDetail(null)} />
    </div>
  );
}

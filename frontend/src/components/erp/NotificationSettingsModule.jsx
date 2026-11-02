/**
 * NotificationSettingsModule — matriks Kategori × Role.
 * Admin menentukan kategori notifikasi (per portal sumber) mana yang boleh
 * diterima tiap role. Default diturunkan dari hak akses portal (RBAC) supaya
 * tidak ada dua sumber kebenaran.
 *
 * 2026-11-02 (K31) — retensi notifikasi (`retention_days`, bawaan 90) diatur di
 * layar & dokumen pengaturan yang SAMA (notif_category_config), bukan layar baru.
 */
import { useCallback, useEffect, useState } from 'react';
import { Bell, Save, RefreshCw, Loader2, AlertCircle, ShieldCheck, Clock } from 'lucide-react';
import { toast } from 'sonner';
import { GlassCard } from '@/components/ui/glass';

const API = process.env.REACT_APP_BACKEND_URL || '';
const RETENTION_MIN = 7;
const RETENTION_MAX = 3650;

export default function NotificationSettingsModule({ token }) {
  const [data, setData] = useState(null);
  const [matrix, setMatrix] = useState({});
  const [retention, setRetention] = useState('90');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  const h = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const load = useCallback(async () => {
    setLoading(true); setErr('');
    try {
      const r = await fetch(`${API}/api/notifications/category-config`, { headers: h });
      if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`);
      const d = await r.json();
      setData(d); setMatrix(d.matrix || {});
      setRetention(String(d.retention_days || d.retention_default_days || 90));
    } catch (e) { setErr(e.message); } finally { setLoading(false); }
     
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const toggle = (role, cat) => {
    setMatrix((m) => {
      const cur = new Set(m[role] || []);
      if (cur.has(cat)) cur.delete(cat); else cur.add(cat);
      return { ...m, [role]: Array.from(cur).sort() };
    });
  };

  const retentionNum = Number(retention);
  const retentionValid = Number.isInteger(retentionNum) && retentionNum >= RETENTION_MIN && retentionNum <= RETENTION_MAX;

  const save = async () => {
    if (!retentionValid) {
      toast.error(`Masa simpan harus ${RETENTION_MIN}–${RETENTION_MAX} hari.`);
      return;
    }
    setSaving(true);
    try {
      const r = await fetch(`${API}/api/notifications/category-config`, {
        method: 'PUT', headers: h, body: JSON.stringify({ matrix, retention_days: retentionNum }),
      });
      if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`);
      toast.success('Konfigurasi notifikasi tersimpan.');
      load();
    } catch (e) { toast.error(e.message); } finally { setSaving(false); }
  };

  const cats = data?.categories || [];
  const locked = data?.locked_categories || ['personal'];
  const roles = (data?.roles || []).filter((r) => !['superadmin', 'admin', 'owner'].includes(r));

  return (
    <div className="space-y-5" data-testid="notification-settings-module">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-2xl bg-[hsl(var(--primary)/0.12)] border border-[hsl(var(--primary)/0.25)] grid place-items-center">
            <Bell className="w-5 h-5 text-[hsl(var(--primary))]" />
          </div>
          <div>
            <h2 className="text-2xl font-bold text-foreground">Pengaturan Notifikasi</h2>
            <p className="text-sm text-muted-foreground">
              Tentukan kategori notifikasi (per portal sumber) yang boleh diterima tiap peran.
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <button onClick={load}
            className="inline-flex items-center gap-2 h-9 px-3 rounded-lg border border-[var(--glass-border)] bg-[var(--card-surface)] text-sm text-foreground hover:bg-[var(--nav-pill-active)]"
            data-testid="notif-cfg-reload">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /> Muat Ulang
          </button>
          <button onClick={save} disabled={saving}
            className="inline-flex items-center gap-2 h-9 px-4 rounded-lg bg-[hsl(var(--primary))] text-white text-sm font-medium disabled:opacity-60"
            data-testid="notif-cfg-save">
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />} Simpan
          </button>
        </div>
      </div>

      <GlassCard className="p-3 flex items-start gap-2">
        <ShieldCheck className="w-4 h-4 mt-0.5 text-[hsl(var(--primary))] shrink-0" />
        <p className="text-xs text-muted-foreground">
          Peran <b className="text-foreground">super_admin / admin / owner</b> selalu menerima semua kategori
          dan tidak bisa dibatasi. Kategori <b className="text-foreground">Untuk Saya</b> juga selalu aktif —
          isinya notifikasi yang dialamatkan langsung ke orang tersebut (tugas, cuti, approval miliknya),
          jadi tidak boleh ditutup. Setiap pengguna dapat membisukan kategori lain untuk dirinya sendiri
          (ikon gerigi di bel) — tetapi tidak bisa membuka kategori yang sudah ditutup di sini.
        </p>
      </GlassCard>

      <GlassCard className="p-4 flex flex-wrap items-end gap-4" data-testid="notif-retention-card">
        <div className="flex items-start gap-2 min-w-[240px] flex-1">
          <Clock className="w-4 h-4 mt-0.5 text-[hsl(var(--primary))] shrink-0" />
          <div>
            <p className="text-sm font-semibold text-foreground">Masa simpan notifikasi</p>
            <p className="text-xs text-muted-foreground">
              Pemberitahuan yang <b className="text-foreground">sudah dibaca</b> dan tindakan yang
              <b className="text-foreground"> sudah selesai</b> dihapus otomatis setelah jumlah hari ini
              (dicek tiap hari pukul 02:30). Notifikasi <b className="text-foreground">Perlu Tindakan</b> yang
              masih terbuka tidak pernah dihapus.
            </p>
          </div>
        </div>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Hari
          <input
            type="number" inputMode="numeric" min={RETENTION_MIN} max={RETENTION_MAX} step={1}
            value={retention}
            onChange={(e) => setRetention(e.target.value)}
            className={`w-28 h-9 px-2 rounded-lg border bg-[var(--card-surface)] text-sm text-foreground tabular-nums ${retentionValid ? 'border-[var(--glass-border)]' : 'border-red-400'}`}
            aria-invalid={!retentionValid}
            data-testid="notif-retention-days"
          />
        </label>
        {!retentionValid && (
          <p className="text-xs text-red-600 w-full">Isi {RETENTION_MIN}–{RETENTION_MAX} hari.</p>
        )}
      </GlassCard>

      {err && (
        <div className="flex items-center gap-2 p-3 rounded-lg border border-red-300 bg-red-50 text-sm text-red-700">
          <AlertCircle className="w-4 h-4" /> {err}
        </div>
      )}

      <GlassCard className="p-0 overflow-hidden">
        {loading && !data ? (
          <div className="p-8 text-center"><Loader2 className="w-5 h-5 animate-spin mx-auto text-muted-foreground" /></div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="notif-matrix-table">
              <thead>
                <tr className="border-b border-[var(--glass-border)] bg-[var(--nav-pill-bg)]">
                  <th className="px-3 py-2.5 text-left text-xs font-semibold text-foreground sticky left-0 bg-[var(--nav-pill-bg)]">Peran</th>
                  {cats.map((c) => (
                    <th key={c.key} className="px-2 py-2.5 text-center text-[11px] font-medium text-muted-foreground whitespace-nowrap">
                      {c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {roles.map((role) => (
                  <tr key={role} className="border-b border-[var(--glass-border)] last:border-0 hover:bg-[var(--nav-pill-active)]/30">
                    <td className="px-3 py-2 font-mono text-xs text-foreground sticky left-0 bg-[var(--card-surface)]">{role}</td>
                    {cats.map((c) => (
                      <td key={c.key} className="px-2 py-2 text-center">
                        <input
                          type="checkbox"
                          checked={locked.includes(c.key) || (matrix[role] || []).includes(c.key)}
                          disabled={locked.includes(c.key)}
                          onChange={() => toggle(role, c.key)}
                          className={`w-4 h-4 accent-[hsl(var(--primary))] ${locked.includes(c.key) ? 'cursor-not-allowed opacity-70' : 'cursor-pointer'}`}
                          data-testid={`notif-cell-${role}-${c.key}`}
                          title={locked.includes(c.key)
                            ? 'Selalu aktif — notifikasi yang dialamatkan langsung ke orang tersebut'
                            : `${role} menerima ${c.label}`}
                          aria-label={`${role} menerima ${c.label}`}
                        />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
    </div>
  );
}

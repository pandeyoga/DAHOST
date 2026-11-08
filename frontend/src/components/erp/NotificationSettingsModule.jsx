/**
 * NotificationSettingsModule — matriks Kategori × Role.
 * Admin menentukan kategori notifikasi (per portal sumber) mana yang boleh
 * diterima tiap role. Default diturunkan dari hak akses portal (RBAC) supaya
 * tidak ada dua sumber kebenaran.
 *
 * 2026-11-02 (K31) — retensi notifikasi (`retention_days`, bawaan 90) diatur di
 * layar & dokumen pengaturan yang SAMA (notif_category_config), bukan layar baru.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, nama peran manusiawi (dulu kode `admin_gudang`), masa simpan diubah
 * lewat FormPopup (dulu isian di halaman), matriks bisa diunduh Excel/CSV. Data yang disimpan tetap sama.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Pencil, RefreshCw, Save } from 'lucide-react';
import { toast } from 'sonner';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import PageLayout from './layout/PageLayout';
import { Notice } from './moduleAtoms';
import { petaLabelPeran } from './akses/labelPeran';

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
  const [daftarPeran, setDaftarPeran] = useState([]);
  const [formSimpan, setFormSimpan] = useState(false);

  const h = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const load = useCallback(async () => {
    setLoading(true); setErr('');
    try {
      const r = await fetch(`${API}/api/notifications/category-config`, { headers: h });
      if (!r.ok) throw new Error((await r.json()).detail || `Kode ${r.status}`);
      const d = await r.json();
      setData(d); setMatrix(d.matrix || {});
      setRetention(String(d.retention_days || d.retention_default_days || 90));
    } catch (e) { setErr(e.message); } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => { load(); }, [load]);
  // Nama peran untuk tampilan saja (keterangan peran dari data).
  useEffect(() => {
    fetch(`${API}/api/roles`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.json() : []))
      .then((d) => setDaftarPeran(Array.isArray(d) ? d : []))
      .catch(() => {});
  }, [token]);
  const namaPeran = useMemo(() => petaLabelPeran(daftarPeran), [daftarPeran]);

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
      return false;
    }
    setSaving(true);
    try {
      const r = await fetch(`${API}/api/notifications/category-config`, {
        method: 'PUT', headers: h, body: JSON.stringify({ matrix, retention_days: retentionNum }),
      });
      if (!r.ok) throw new Error((await r.json()).detail || `Kode ${r.status}`);
      toast.success('Konfigurasi notifikasi tersimpan.');
      load();
      return true;
    } catch (e) { toast.error(e.message); return false; } finally { setSaving(false); }
  };

  const cats = data?.categories || [];
  const locked = data?.locked_categories || ['personal'];
  const roles = (data?.roles || []).filter((r) => !['superadmin', 'admin', 'owner'].includes(r));
  const tersimpan = String(data?.retention_days || data?.retention_default_days || 90);
  const berubah = !!data && (JSON.stringify(data.matrix || {}) !== JSON.stringify(matrix));
  const menerima = (role, key) => locked.includes(key) || (matrix[role] || []).includes(key);

  return (
    <PageLayout testId="notification-settings-module" title="Aturan notifikasi"
      subtitle="Tentukan kategori notifikasi (per portal sumber) yang boleh diterima tiap peran."
      actions={(
        <Button variant="success" onClick={save} disabled={saving || loading} data-testid="notif-cfg-save">
          <Save />{saving ? 'Menyimpan…' : 'Simpan'}
        </Button>
      )}
      tools={<>
        <TombolUnduh namaBerkas="aturan-notifikasi" namaLembar="Peran x kategori" baris={roles.map((r) => ({ role: r }))}
          testId="notif-cfg-unduh"
          kolom={[
            { label: 'Peran', nilai: (x) => namaPeran(x.role) },
            ...cats.map((c) => ({ label: c.label, nilai: (x) => (menerima(x.role, c.key) ? 'Ya' : 'Tidak') })),
          ]} />
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="notif-cfg-reload">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}>
      <Notice tone="info" title="Yang tidak bisa dibatasi">
        Superadmin, admin, dan owner selalu menerima semua kategori; kategori <b>Untuk Saya</b> selalu aktif. Pengguna
        bisa membisukan kategori lain untuk dirinya (gerigi di lonceng), tetapi tidak bisa membuka kategori yang ditutup di sini.
      </Notice>

      <GlassCard className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3" data-testid="notif-retention-card">
        <p className="min-w-0 flex-1 text-sm text-foreground">
          Masa simpan notifikasi: <span className="font-medium tabular-nums" data-testid="notif-retention-value">{data ? `${tersimpan} hari` : '—'}</span>
          <span className="hidden text-muted-foreground sm:inline"> · yang sudah dibaca/selesai dihapus otomatis setelah masa ini.</span>
        </p>
        <Button variant="outline" size="sm" onClick={() => { setRetention(tersimpan); setFormSimpan(true); }}
          disabled={!data} data-testid="notif-retention-edit">
          <Pencil />Ubah masa simpan
        </Button>
      </GlassCard>

      {err && <Notice tone="danger" title="Pengaturan tidak bisa dimuat">{err}</Notice>}
      {berubah && (
        <Notice tone="warning" testId="notif-cfg-unsaved">Ada perubahan centang yang belum disimpan. Tekan Simpan agar berlaku.</Notice>
      )}

      <GlassCard className="overflow-hidden p-0">
        {loading && !data ? (
          <p className="py-6 text-center text-sm text-muted-foreground">Memuat pengaturan…</p>
        ) : (
          <div className="overflow-x-auto">
            <Table data-testid="notif-matrix-table">
              <TableHeader>
                <TableRow>
                  <TableHead className="sticky left-0 z-[1] bg-[var(--card-surface)]">Peran</TableHead>
                  {cats.map((c) => (
                    <TableHead key={c.key} className="whitespace-nowrap text-center">{c.label}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {roles.map((role) => (
                  <TableRow key={role}>
                    <TableCell className="sticky left-0 z-[1] whitespace-nowrap bg-[var(--card-surface)] text-sm font-medium" title={role}>
                      {namaPeran(role)}
                    </TableCell>
                    {cats.map((c) => (
                      <TableCell key={c.key} className="text-center">
                        <input
                          type="checkbox"
                          checked={menerima(role, c.key)}
                          disabled={locked.includes(c.key)}
                          onChange={() => toggle(role, c.key)}
                          className={`h-4 w-4 accent-[hsl(var(--primary))] ${locked.includes(c.key) ? 'cursor-not-allowed opacity-70' : 'cursor-pointer'}`}
                          data-testid={`notif-cell-${role}-${c.key}`}
                          title={locked.includes(c.key)
                            ? 'Selalu aktif — notifikasi yang dialamatkan langsung ke orang tersebut'
                            : `${namaPeran(role)} menerima ${c.label}`}
                          aria-label={`${namaPeran(role)} menerima ${c.label}`}
                        />
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </GlassCard>

      <FormPopup open={formSimpan} onClose={() => setFormSimpan(false)} ukuran="pendek" testId="notif-retention-form"
        judul="Masa simpan notifikasi" menyimpan={saving} bisaSimpan={retentionValid}
        keterangan="Centang peran yang belum disimpan ikut tersimpan bersama masa simpan ini."
        galat={!retentionValid ? `Isi ${RETENTION_MIN}–${RETENTION_MAX} hari.` : null}
        onSimpan={async () => { if (await save()) setFormSimpan(false); }}>
        <p className="text-sm text-muted-foreground">
          Pemberitahuan yang sudah dibaca dan tindakan yang sudah selesai dihapus otomatis setelah jumlah hari ini (dicek
          tiap hari pukul 02.30). Notifikasi Perlu Tindakan yang masih terbuka tidak pernah dihapus.
        </p>
        <Isian label="Jumlah hari" wajib htmlFor="notif-retention-days"
          petunjuk={`${RETENTION_MIN}–${RETENTION_MAX} hari. Bawaan 90 hari.`}>
          <Input id="notif-retention-days" type="number" inputMode="numeric" min={RETENTION_MIN} max={RETENTION_MAX} step={1}
            value={retention} onChange={(e) => setRetention(e.target.value)} className="w-32 tabular-nums"
            aria-invalid={!retentionValid} data-testid="notif-retention-days" />
        </Isian>
      </FormPopup>
    </PageLayout>
  );
}

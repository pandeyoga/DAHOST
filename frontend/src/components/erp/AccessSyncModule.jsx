// Cek Sinkron Akun — audit akun <-> peran <-> hak akses efektif (superadmin).
//
// Standar UI/UX v2 (8 Nov 2026): PageLayout (di hub judul disembunyikan), jumlah per status di pil penyaring (dari
// daftar yang sama), tabel (kartu ringkas di HP) + unduh Excel/CSV, nama peran & portal manusiawi (dulu kode `finance`,
// `admin_gudang`), pesan masalah tanpa istilah program (`role_id`), detail akses = DetailPopup, sinkronkan lewat
// konfirmasi. Logika audit & perbaikan di server tidak berubah.
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Eye, RefreshCw, Search, Wrench } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import FilterChips from '../ui/filter-chips';
import TabelData from '../ui/tabel-data';
import TombolUnduh from '../ui/tombol-unduh';
import DetailPopup, { BarisDetail } from '../ui/detail-popup';
import { confirmDialog } from '../ui/confirm-dialog';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatusBadge } from './moduleAtoms';
import { NAMA_PORTAL } from './portalAccess';
import { petaLabelPeran } from './akses/labelPeran';

const API = process.env.REACT_APP_BACKEND_URL;
const ACT = { view: 'Lihat', create: 'Tambah', edit: 'Ubah', delete: 'Hapus', approve: 'Setujui', export: 'Unduh' };
const PORTAL = Object.fromEntries(NAMA_PORTAL.map((p) => [p.id, p.nama]));
const namaPortal = (p) => PORTAL[p] || p;
const PESAN = {
  role_id_dangling: 'Tautan peran menunjuk peran yang sudah dihapus',
  role_mismatch: 'Tautan peran masih menunjuk peran lama',
  role_case: 'Nama peran beda huruf besar/kecil dengan data peran',
  role_unknown: 'Peran tidak terdaftar — akun tidak punya hak akses apa pun',
  role_unlinked: 'Belum tertaut ke data peran (dicocokkan lewat nama)',
};
const pesan = (i) => PESAN[i.code] || i.message;
const masalah = (u) => (u.issues || []).filter((i) => i.severity !== 'info');
const catatan = (u) => (u.issues || []).filter((i) => i.severity === 'info');
const bisaDirapikan = (u) => (u.issues || []).some((i) => i.fixable);
const portalTampil = (u) => (u.is_super ? 'Semua portal'
  : u.portals.filter((p) => !['self', 'collaboration'].includes(p)).map(namaPortal).join(', ') || '—');

function UserDetail({ uid, token, onClose, namaPeran }) {
  const [d, setD] = useState(null);
  useEffect(() => {
    if (!uid) return;
    setD(null);
    fetch(`${API}/api/admin/access-sync/user/${uid}`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.json()).then(setD).catch(() => setD({ error: true }));
  }, [uid, token]);
  const byModule = {};
  (d?.granular || []).forEach((g) => { (byModule[g.module] ||= { ...g, acts: [] }).acts.push(g.action); });
  const modul = Object.values(byModule);
  if (!uid) return null;
  return (
    <DetailPopup open onClose={onClose} testId="access-sync-detail"
      judul={`Akses efektif ${d?.email || ''}`} keterangan="Portal dan izin yang benar-benar berlaku untuk akun ini.">
      {!d ? <p className="text-sm text-muted-foreground">Memuat…</p> : d.error ? (
        <p className="text-sm text-[hsl(var(--danger-text))]">Akses akun ini tidak bisa dimuat.</p>
      ) : (
        <>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Peran">
              <span data-testid="access-sync-detail-role">{namaPeran(d.role)}</span>{d.is_super && ' (akses penuh)'}
            </BarisDetail>
            <BarisDetail label="Portal yang bisa dibuka">
              <div className="flex flex-wrap gap-1.5" data-testid="access-sync-detail-portals">
                {(d.portals || []).map((p) => <StatusBadge key={p} status={p} label={namaPortal(p)} tone="default" />)}
              </div>
            </BarisDetail>
            <BarisDetail label="Menu disembunyikan">{d.hidden_count}</BarisDetail>
            <BarisDetail label="Total izin">{d.perm_count}</BarisDetail>
          </dl>
          <div className="space-y-2">
            <p className="text-sm font-medium">Izin per modul ({modul.length} modul)</p>
            {modul.length === 0 ? (
              <p className="text-sm text-muted-foreground">Belum ada izin per modul — aturan bawaan peran yang berlaku.</p>
            ) : (
              <TabelData baris={modul} kunci={(m) => m.module} testId="access-sync-detail-modules" kolom={[
                { kunci: 'label', label: 'Modul', hp: 'judul', isi: (m) => <span className="font-medium">{m.label}</span> },
                { kunci: 'portal', label: 'Portal', isi: (m) => namaPortal(m.portal) },
                { kunci: 'acts', label: 'Izin', isi: (m) => (
                  <div className="flex flex-wrap gap-1">
                    {m.acts.map((a) => <StatusBadge key={a} status={a} label={ACT[a] || a} tone="primary" />)}
                  </div>) },
              ]} />
            )}
          </div>
        </>
      )}
    </DetailPopup>
  );
}

export default function AccessSyncModule({ token }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [detail, setDetail] = useState(null);
  const [peran, setPeran] = useState([]);
  const [saring, setSaring] = useState('');
  const [cari, setCari] = useState('');
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
  useEffect(() => {
    fetch(`${API}/api/roles`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.json() : [])).then((d) => setPeran(Array.isArray(d) ? d : [])).catch(() => {});
  }, [token]);
  const namaPeran = useMemo(() => petaLabelPeran(peran), [peran]);

  const users = useMemo(() => data?.users || [], [data]);
  const nOk = users.filter((u) => u.status === 'ok').length;
  const nError = users.filter((u) => u.status === 'error').length;
  const nRapikan = users.filter(bisaDirapikan).length;

  const fixAll = async () => {
    const ok = await confirmDialog({
      title: `Sinkronkan ${nRapikan} akun?`,
      body: 'Tautan peran tiap akun dirapikan sesuai data peran. Hak akses yang sudah diatur tidak berubah.',
      confirmLabel: 'Sinkronkan',
    });
    if (!ok) return;
    setBusy(true);
    try {
      const r = await fetch(`${API}/api/admin/access-sync/fix`, { method: 'POST', headers });
      const j = await r.json().catch(() => ({}));
      // 2026-11-06 (pola P6): dulu "undefined akun disinkronkan" muncul walau server menolak
      if (!r.ok) throw new Error(j.detail || 'Gagal menyinkronkan');
      toast.success(`${j.fixed} akun disinkronkan`);
      await load();
    } catch (e) { toast.error(typeof e.message === 'string' && e.message ? e.message : 'Gagal menyinkronkan'); setBusy(false); }
  };

  const q = cari.trim().toLowerCase();
  const tampil = users
    .filter((u) => !saring || (saring === 'rapikan' ? bisaDirapikan(u) : u.status === saring))
    .filter((u) => !q || `${u.name} ${u.email} ${u.role} ${namaPeran(u.role)}`.toLowerCase().includes(q));

  const kolom = [
    { kunci: 'akun', label: 'Akun', hp: 'judul', isi: (u) => (
      <div className="min-w-0" data-testid={`access-sync-row-${u.email}`}>
        <p className="font-medium">{u.name}</p>
        <p className="truncate text-xs text-muted-foreground">{u.email}</p>
      </div>) },
    { kunci: 'peran', label: 'Peran', isi: (u) => (
      <span className="text-sm">{namaPeran(u.role)}{!u.active && <StatusBadge status="inactive" label="Nonaktif" tone="muted" className="ml-1" />}</span>) },
    { kunci: 'portal', label: 'Portal', isi: (u) => <p className="line-clamp-2 text-sm md:max-w-[16rem]" title={portalTampil(u)}>{portalTampil(u)}</p> },
    { kunci: 'izin', label: 'Izin', isi: (u) => (
      <span className="text-sm">{u.is_super ? 'Penuh' : u.perm_count}
        {u.granular_portals.length > 0 && <span className="text-muted-foreground"> · per modul: {u.granular_portals.map(namaPortal).join(', ')}</span>}
      </span>) },
    { kunci: 'status', label: 'Status', isi: (u) => (u.status === 'ok' ? (
      <div className="space-y-0.5">
        <StatusBadge status="ok" label="Sinkron" tone="success" />
        {catatan(u).map((i) => <p key={i.code} className="text-xs text-muted-foreground">{pesan(i)}</p>)}
      </div>
    ) : (
      <div className="space-y-0.5">
        <StatusBadge status="error" label="Bermasalah" tone="danger" />
        {masalah(u).map((i) => <p key={i.code} className="text-xs text-[hsl(var(--danger-text))]">{pesan(i)}</p>)}
      </div>
    )) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (u) => (
      <Button variant="outline" size="sm" onClick={() => setDetail(u.id)} data-testid={`access-sync-view-${u.email}`}>
        <Eye />Lihat akses
      </Button>) },
  ];

  return (
    <PageLayout testId="access-sync-module" title="Cek sinkron akun"
      subtitle="Memastikan setiap akun memakai peran dan hak akses yang sama dengan yang diatur; perubahan peran berlaku tanpa masuk ulang."
      actions={(
        <Button onClick={fixAll} disabled={busy || !data?.summary?.fixable} data-testid="access-sync-fix"
          title="Rapikan tautan peran akun yang bisa diperbaiki otomatis">
          <Wrench />Sinkronkan ({data?.summary?.fixable || 0})
        </Button>
      )}
      filters={data && <>
        <FilterChips className="w-full min-w-0 sm:w-auto" value={saring} onChange={setSaring} hideWhenEmpty={false} testId="access-sync-filter" options={[
          { key: '', label: 'Semua', count: users.length },
          { key: 'ok', label: 'Sinkron', count: nOk },
          { key: 'error', label: 'Bermasalah', count: nError },
          { key: 'rapikan', label: 'Bisa dirapikan', count: nRapikan },
        ]} />
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={cari} onChange={(e) => setCari(e.target.value)} placeholder="Cari nama, email, peran" className="pl-8"
            data-testid="access-sync-search" />
        </div>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="cek-sinkron-akun" namaLembar="Akun" baris={tampil} testId="access-sync-unduh" kolom={[
          { label: 'Nama', nilai: (u) => u.name }, { label: 'Email', nilai: (u) => u.email },
          { label: 'Peran', nilai: (u) => namaPeran(u.role) }, { label: 'Aktif', nilai: (u) => (u.active ? 'Ya' : 'Tidak') },
          { label: 'Portal', nilai: (u) => portalTampil(u) }, { label: 'Jumlah izin', nilai: (u) => (u.is_super ? 'Penuh' : u.perm_count) },
          { label: 'Status', nilai: (u) => (u.status === 'ok' ? 'Sinkron' : 'Bermasalah') },
          { label: 'Catatan', nilai: (u) => (u.issues || []).map(pesan).join('; ') },
        ]} />
        <Button variant="outline" size="icon" onClick={load} disabled={busy} title="Cek ulang" aria-label="Cek ulang"
          data-testid="access-sync-refresh">
          <RefreshCw className={busy ? 'animate-spin' : ''} />
        </Button>
      </>}
      >
      {!data ? (
        <p className="py-10 text-center text-sm text-muted-foreground">{busy ? 'Memeriksa akun…' : 'Data akun belum bisa dimuat.'}</p>
      ) : (
        <TabelData kolom={kolom} baris={tampil} onKlikBaris={(u) => setDetail(u.id)} testId="access-sync-table"
          kosong={<EmptyState title="Tidak ada akun yang cocok" description="Ubah saringan atau kata pencarian." />} />
      )}
      <UserDetail uid={detail} token={token} onClose={() => setDetail(null)} namaPeran={namaPeran} />
    </PageLayout>
  );
}

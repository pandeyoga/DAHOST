/**
 * RoleManagementModule — SATU-SATUNYA layar konfigurasi akses (Peran & Hak Akses).
 *
 * LATAR BELAKANG (2026-08-06)
 * ---------------------------
 * Sebelumnya ada DUA tempat mengatur akses dan owner bingung:
 *   1) tab "Peran"     -> dialog Edit Role berisi chip permission
 *   2) tab "Hak Akses" -> "Matriks Role & Permission" (tabel raksasa, sulit dipakai)
 * `RoleMatrixModule.jsx` DIHAPUS. Semua pengaturan sekarang di sini, memakai
 * layout master–detail: kiri daftar peran, kanan panel konfigurasi bertahap.
 *
 * SUMBER DATA (tanpa katalog kedua di frontend)
 *   GET  /api/permissions?grouped=1   -> katalog izin (backend/data/permission_catalog.py)
 *   GET  /api/roles                   -> peran + portals + hidden_modules + permission_keys + user_count
 *   GET  /api/roles/audit?role_id=..  -> riwayat perubahan peran
 *   POST /api/roles                   -> buat peran
 *   PUT  /api/roles/{id}              -> SATU jalur simpan (identitas + portal + menu + izin)
 *   DELETE /api/roles/{id}
 *
 * Daftar portal & menu diambil dari SSOT navigasi `portal-shell/portalNav.js`.
 *
 * Standar UI/UX v2 (8 Nov 2026): daftar peran = tabel (kartu ringkas di HP) + unduh Excel/CSV; pengaturan satu
 * peran (5 langkah: identitas, portal, izin, menu, riwayat) dibuka sebagai popup form panjang (dulu panel kanan
 * di samping daftar); tambah peran = FormPopup; hapus & buang perubahan lewat confirmDialog; bandingkan = popup
 * (dulu panel samping). Nama peran tampil dari keterangannya (dulu kode `admin_gudang`). Logika simpan tidak berubah.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Plus, Trash2, Search, RotateCcw, Loader2, History, Check, Columns3, X, Pencil, Eye, RefreshCw,
} from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Accordion, AccordionItem, AccordionTrigger, AccordionContent,
} from '@/components/ui/accordion';
import {
  Collapsible, CollapsibleContent, CollapsibleTrigger,
} from '@/components/ui/collapsible';
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '@/components/ui/select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { formatDateTimeID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';
import { PORTAL_NAV, PORTAL_LABEL } from './portal-shell/portalNav';
import GranularModuleRow from './GranularModuleRow';
import { labelPeran, peranTidakDitawarkan } from './akses/labelPeran';

const API = process.env.REACT_APP_BACKEND_URL || '';
const instan = (ts) => (typeof ts === 'string' && /T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(ts) ? `${ts}Z` : ts);

/* Preset cepat — dihitung dari metadata `action` katalog, bukan daftar hardcode. */
const PRESETS = [
  { id: 'view', label: 'Lihat saja', actions: ['view'], hint: 'Hanya membaca data' },
  { id: 'operator', label: 'Operator', actions: ['view', 'input', 'create', 'edit'], hint: 'Baca + tambah/ubah data harian' },
  { id: 'approver', label: 'Penyetuju', actions: ['view', 'approve', 'export'], hint: 'Baca + setujui dokumen + unduh' },
  { id: 'full', label: 'Penuh', actions: ['view', 'input', 'create', 'edit', 'delete', 'manage', 'approve', 'run', 'export'], hint: 'Semua izin' },
];

const LEVELS = [
  { id: 'none', label: 'Tidak ada' },
  { id: 'view', label: 'Lihat saja' },
  { id: 'full', label: 'Penuh' },
];

const emptyDraft = () => ({ name: '', description: '', portals: [], hidden_modules: [], permissions: [] });

const sameSet = (a = [], b = []) => {
  if (a.length !== b.length) return false;
  const sb = new Set(b);
  return a.every((x) => sb.has(x));
};

/* Semua menu (pintu modul) per portal, dari SSOT navigasi. */
const menusOfPortal = (pid) => {
  const sections = PORTAL_NAV[pid]?.sections || [];
  return sections.flatMap((sec) => (sec.items || []).concat(
    (sec.groups || []).flatMap((g) => g.items || []),
  ));
};

export default function RoleManagementModule({ token, userRole }) {
  const canEdit = userRole === 'superadmin';

  const [groups, setGroups] = useState([]);      // katalog izin (portal > modul > izin)
  const [roles, setRoles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [selectedId, setSelectedId] = useState(null);
  const [draft, setDraft] = useState(emptyDraft());
  const [roleSearch, setRoleSearch] = useState('');
  const [permSearch, setPermSearch] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [newRole, setNewRole] = useState({ name: '', description: '' });
  const [auditRows, setAuditRows] = useState([]);
  const [auditOpen, setAuditOpen] = useState(false);
  const [compareWith, setCompareWith] = useState('');
  const [compareOpen, setCompareOpen] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);

  const headers = useMemo(() => ({
    'Content-Type': 'application/json', Authorization: `Bearer ${token}`,
  }), [token]);

  /* Ref supaya `load()` tidak perlu bergantung pada selectedId (mencegah refetch
     tiap kali peran diklik, yang akan menghapus perubahan yang belum disimpan). */
  const selectedIdRef = useRef(null);
  useEffect(() => { selectedIdRef.current = selectedId; }, [selectedId]);

  /* ── memuat data ─────────────────────────────────────────────────────── */
  const load = useCallback(async (keepId) => {
    setLoading(true);
    try {
      const [rRoles, rPerms] = await Promise.all([
        fetch(`${API}/api/roles`, { headers }),
        fetch(`${API}/api/permissions?grouped=1`, { headers }),
      ]);
      if (!rRoles.ok) throw new Error(`Gagal memuat peran (HTTP ${rRoles.status})`);
      if (!rPerms.ok) throw new Error(`Gagal memuat katalog izin (HTTP ${rPerms.status})`);
      const rolesData = await rRoles.json();
      const permData = await rPerms.json();
      setRoles(Array.isArray(rolesData) ? rolesData : []);
      setGroups(permData.groups || []);
      const list = Array.isArray(rolesData) ? rolesData : [];
      const next = list.find((r) => r.id === (keepId || selectedIdRef.current)) || list[0];
      if (next) {
        setSelectedId(next.id);
        setDraft({
          name: next.name || '',
          description: next.description || '',
          portals: [...(next.portals || [])],
          hidden_modules: [...(next.hidden_modules || [])],
          permissions: [...(next.permission_keys || [])],
        });
      }
    } catch (e) {
      toast.error(e.message);
    } finally {
      setLoading(false);
    }
  }, [headers]);

  useEffect(() => { load(); }, [load]);

  const selected = useMemo(
    () => roles.find((r) => r.id === selectedId) || null, [roles, selectedId],
  );

  const selectRole = (role) => {
    setEditorOpen(true);
    setSelectedId(role.id);
    setPermSearch('');
    setAuditOpen(false);
    setAuditRows([]);
    setDraft({
      name: role.name || '',
      description: role.description || '',
      portals: [...(role.portals || [])],
      hidden_modules: [...(role.hidden_modules || [])],
      permissions: [...(role.permission_keys || [])],
    });
  };

  const dirty = useMemo(() => {
    if (!selected) return false;
    return draft.name !== (selected.name || '')
      || (draft.description || '') !== (selected.description || '')
      || !sameSet(draft.portals, selected.portals || [])
      || !sameSet(draft.hidden_modules, selected.hidden_modules || [])
      || !sameSet(draft.permissions, selected.permission_keys || []);
  }, [draft, selected]);

  /* ── katalog izin: indeks bantu ──────────────────────────────────────── */
  const allPerms = useMemo(
    () => groups.flatMap((g) => g.modules.flatMap((m) => m.permissions)), [groups],
  );
  const [legacyOpen, setLegacyOpen] = useState({});
  const permSet = useMemo(() => new Set(draft.permissions), [draft.permissions]);

  const visibleGroups = useMemo(() => {
    const q = permSearch.trim().toLowerCase();
    if (!q) return groups;
    const filt = (g, list) => (list || [])
      .map((m) => ({
        ...m,
        permissions: m.permissions.filter((p) => (
          p.key.toLowerCase().includes(q)
          || (p.description || '').toLowerCase().includes(q)
          || (m.label || '').toLowerCase().includes(q)
          || (g.portal_label || '').toLowerCase().includes(q)
        )),
      }))
      .filter((m) => m.permissions.length);
    return groups
      .map((g) => ({ ...g, modules: filt(g, g.modules), legacy_modules: filt(g, g.legacy_modules) }))
      .filter((g) => g.modules.length || g.legacy_modules.length);
  }, [groups, permSearch]);

  /* ── aksi izin ───────────────────────────────────────────────────────── */
  const setPerms = (updater) => setDraft((d) => ({ ...d, permissions: updater(new Set(d.permissions)) }));

  // Izin granular `mod.<modul>.<aksi>`: aksi apa pun butuh `view`; mencabut `view` mencabut semua aksi modul itu.
  const togglePerm = (key) => setPerms((s) => {
    const g = /^mod\.([^.]+)\.([^.]+)$/.exec(key);
    if (s.has(key)) {
      s.delete(key);
      if (g && g[2] === 'view') Array.from(s).filter((k) => k.startsWith(`mod.${g[1]}.`)).forEach((k) => s.delete(k));
    } else {
      s.add(key);
      if (g && g[2] !== 'view') s.add(`mod.${g[1]}.view`);
    }
    return Array.from(s);
  });

  const applyLevelToModule = (mod, level) => setPerms((s) => {
    mod.permissions.forEach((p) => s.delete(p.key));
    if (level === 'view') mod.permissions.filter((p) => p.action === 'view').forEach((p) => s.add(p.key));
    if (level === 'full') mod.permissions.forEach((p) => s.add(p.key));
    return Array.from(s);
  });

  const applyLevelToGroup = (grp, level) => setPerms((s) => {
    grp.modules.forEach((m) => m.permissions.forEach((p) => s.delete(p.key)));
    if (level === 'view') {
      grp.modules.forEach((m) => m.permissions.filter((p) => p.action === 'view').forEach((p) => s.add(p.key)));
    }
    if (level === 'full') grp.modules.forEach((m) => m.permissions.forEach((p) => s.add(p.key)));
    return Array.from(s);
  });

  const applyPreset = (preset) => {
    const scope = draft.portals.length ? new Set(draft.portals) : null;
    const keys = allPerms
      .filter((p) => (!scope || scope.has(p.portal)) && preset.actions.includes(p.action))
      .map((p) => p.key);
    setDraft((d) => ({ ...d, permissions: keys }));
    toast.success(`Preset "${preset.label}" diterapkan (${keys.length} izin)`, {
      description: scope ? 'Dibatasi pada portal yang dipilih peran ini.' : 'Berlaku untuk semua portal.',
    });
  };

  const clearPerms = () => setDraft((d) => ({ ...d, permissions: [] }));

  // Konversi izin lama + akses portal draf -> izin per modul (hanya menambah, belum tersimpan).
  const [converting, setConverting] = useState('');
  const convertLegacy = async (portal) => {
    setConverting(portal || 'all');
    try {
      const res = await fetch(`${API}/api/roles/granular-suggestion`, {
        method: 'POST', headers,
        body: JSON.stringify({ role_name: draft.name, portals: draft.portals, permissions: draft.permissions, portal }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
      const before = new Set(draft.permissions);
      const added = (body.keys || []).filter((k) => !before.has(k));
      if (!added.length) {
        toast.info('Tidak ada izin per modul baru', { description: 'Izin lama peran ini sudah tercermin, atau peran belum punya akses ke portal ini.' });
        return;
      }
      setDraft((d) => ({ ...d, permissions: Array.from(new Set([...d.permissions, ...added])) }));
      const mods = (body.portals || []).reduce((n, p) => n + p.modules, 0);
      toast.success(`${added.length} izin per modul ditambahkan (${mods} modul)`, {
        description: 'Belum tersimpan — periksa matriks lalu tekan Simpan.',
      });
    } catch (e) {
      toast.error('Gagal mengonversi izin lama', { description: e.message });
    } finally {
      setConverting('');
    }
  };

  const copyFromRole = (rid) => {
    const src = roles.find((r) => r.id === rid);
    if (!src) return;
    setDraft((d) => ({
      ...d,
      portals: [...(src.portals || [])],
      hidden_modules: [...(src.hidden_modules || [])],
      permissions: [...(src.permission_keys || [])],
    }));
    toast.success(`Disalin dari peran "${src.name}"`, { description: 'Belum tersimpan — tekan Simpan bila sudah sesuai.' });
  };

  const levelOfModule = (mod) => {
    const total = mod.permissions.length;
    const on = mod.permissions.filter((p) => permSet.has(p.key)).length;
    if (on === 0) return 'none';
    if (on === total) return 'full';
    const views = mod.permissions.filter((p) => p.action === 'view');
    if (views.length && on === views.length && views.every((p) => permSet.has(p.key))) return 'view';
    return 'partial';
  };

  /* ── portal & menu ───────────────────────────────────────────────────── */
  const togglePortal = (pid) => setDraft((d) => ({
    ...d,
    portals: d.portals.includes(pid) ? d.portals.filter((x) => x !== pid) : [...d.portals, pid],
  }));

  const toggleMenu = (mid) => setDraft((d) => ({
    ...d,
    hidden_modules: d.hidden_modules.includes(mid)
      ? d.hidden_modules.filter((x) => x !== mid)
      : [...d.hidden_modules, mid],
  }));

  /* ── simpan / buat / hapus ───────────────────────────────────────────── */
  const save = async () => {
    if (!selected) return;
    if (!draft.name.trim()) { toast.error('Nama peran wajib diisi.'); return; }
    setSaving(true);
    try {
      const res = await fetch(`${API}/api/roles/${selected.id}`, {
        method: 'PUT', headers, body: JSON.stringify(draft),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || body.error || `HTTP ${res.status}`);
      toast.success(`Peran "${draft.name}" tersimpan`, {
        description: `${draft.permissions.length} izin · ${draft.portals.length || 'bawaan'} portal · ${draft.hidden_modules.length} menu disembunyikan`,
      });
      await load(selected.id);
    } catch (e) {
      toast.error('Gagal menyimpan', { description: e.message });
    } finally {
      setSaving(false);
    }
  };

  const createRole = async () => {
    const name = newRole.name.trim();
    if (!name) { toast.error('Nama peran wajib diisi.'); return; }
    setSaving(true);
    try {
      const res = await fetch(`${API}/api/roles`, {
        method: 'POST', headers,
        body: JSON.stringify({ name, description: newRole.description, portals: [], hidden_modules: [], permissions: [] }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || body.error || `HTTP ${res.status}`);
      toast.success(`Peran "${name}" dibuat`, { description: 'Sekarang atur portal & hak aksesnya di panel kanan.' });
      setShowCreate(false);
      setNewRole({ name: '', description: '' });
      await load(body.id);
      setEditorOpen(true);
    } catch (e) {
      toast.error('Gagal membuat peran', { description: e.message });
    } finally {
      setSaving(false);
    }
  };

  const removeRole = async (role) => {
    if (!role) return;
    const ok = await confirmDialog({
      title: `Hapus peran "${labelPeran(role.name, role.description)}"?`,
      body: 'Peran beserta izinnya akan dihapus permanen. Peran yang masih dipakai pengguna tidak bisa dihapus.',
      confirmLabel: 'Hapus', danger: true,
    });
    if (!ok) return;
    setSaving(true);
    try {
      const res = await fetch(`${API}/api/roles/${role.id}`, { method: 'DELETE', headers });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || body.error || `HTTP ${res.status}`);
      toast.success(`Peran "${role.name}" dihapus`);
      setEditorOpen(false);
      setSelectedId(null);
      await load(null);
    } catch (e) {
      toast.error('Gagal menghapus peran', { description: e.message });
    } finally {
      setSaving(false);
    }
  };

  const loadAudit = async () => {
    if (!selected) return;
    try {
      const res = await fetch(`${API}/api/roles/audit?role_id=${selected.id}&limit=20`, { headers });
      const body = await res.json();
      setAuditRows(body.items || []);
    } catch (e) {
      toast.error('Gagal memuat riwayat', { description: e.message });
    }
  };

  /* ── daftar peran (tabel) ────────────────────────────────────────────── */
  const filteredRoles = useMemo(() => {
    const q = roleSearch.trim().toLowerCase();
    if (!q) return roles;
    return roles.filter((r) => (r.name || '').toLowerCase().includes(q)
      || (r.description || '').toLowerCase().includes(q));
  }, [roles, roleSearch]);

  const compareRole = roles.find((r) => r.id === compareWith) || null;
  const namaPeran = (r) => labelPeran(r?.name, r?.description);
  const labelIzin = useMemo(() => Object.fromEntries(allPerms.map((p) => [p.key, p.description || p.key])), [allPerms]);
  const jumlahPortal = (r) => ((r.portals || []).length ? `${r.portals.length} portal` : 'Bawaan sistem');

  const tutupEditor = async () => {
    if (dirty && canEdit) {
      const ok = await confirmDialog({
        title: 'Buang perubahan?', body: 'Perubahan pada peran ini belum disimpan dan akan hilang.',
        confirmLabel: 'Buang perubahan', danger: true,
      });
      if (!ok) return;
      if (selected) selectRole(selected);
    }
    setEditorOpen(false);
  };

  const bukaBandingkan = () => {
    if (!compareWith) {
      const other = roles.find((r) => r.id !== selectedId);
      if (other) setCompareWith(other.id);
    }
    setCompareOpen(true);
  };

  const kolomPeran = [
    { kunci: 'nama', label: 'Peran', hp: 'judul', isi: (r) => (
      <div className="min-w-0" data-testid={`role-item-${r.name}`}>
        <p className="font-medium text-foreground">{namaPeran(r)}</p>
        {r.is_system && <p className="text-xs text-muted-foreground">Peran sistem</p>}
        {peranTidakDitawarkan(r) && (
          <p className="text-xs text-muted-foreground" data-testid={`role-tersembunyi-${r.name}`}>
            Belum diatur · tidak muncul di pilihan peran pengguna
          </p>
        )}
      </div>) },
    { kunci: 'pengguna', label: 'Pengguna', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.user_count || 0}</span> },
    { kunci: 'portal', label: 'Portal', isi: (r) => <span className="text-sm">{jumlahPortal(r)}</span> },
    { kunci: 'izin', label: 'Izin', rata: 'kanan', isi: (r) => <span className="tabular-nums">{(r.permission_keys || []).length}</span> },
    { kunci: 'menu', label: 'Menu disembunyikan', rata: 'kanan', isi: (r) => <span className="tabular-nums">{(r.hidden_modules || []).length}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <Button size="sm" variant="outline" onClick={() => selectRole(r)} data-testid={`role-open-${r.name}`}>
        {canEdit ? <><Pencil />Atur</> : <><Eye />Lihat</>}
      </Button>) },
  ];

  /* ── render ──────────────────────────────────────────────────────────── */
  return (
    <PageLayout testId="role-access-page" headerTestId="role-access-header" title="Peran & hak akses"
      subtitle="Satu tempat untuk portal yang boleh dibuka, menu yang disembunyikan, dan izin aksi/persetujuan tiap peran."
      actions={canEdit && (
        <Button onClick={() => setShowCreate(true)} data-testid="add-role-btn"><Plus />Tambah peran</Button>
      )}
      filters={(
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={roleSearch} onChange={(e) => setRoleSearch(e.target.value)} placeholder="Cari peran"
            className="pl-8" data-testid="role-search-input" />
        </div>
      )}
      tools={<>
        <TombolUnduh namaBerkas="peran-dan-hak-akses" namaLembar="Peran" baris={filteredRoles} testId="role-unduh" kolom={[
          { label: 'Peran', nilai: (r) => namaPeran(r) }, { label: 'Kode peran', nilai: (r) => r.name },
          { label: 'Pengguna', nilai: (r) => r.user_count || 0 },
          { label: 'Portal', nilai: (r) => ((r.portals || []).length ? r.portals.map((p) => PORTAL_LABEL?.[p] || p).join(', ') : 'Bawaan sistem') },
          { label: 'Jumlah izin', nilai: (r) => (r.permission_keys || []).length },
          { label: 'Menu disembunyikan', nilai: (r) => (r.hidden_modules || []).length },
        ]} />
        <Button variant="outline" size="icon" onClick={() => load()} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}>
      {loading && roles.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat peran…</p>
      ) : (
        <TabelData kolom={kolomPeran} baris={filteredRoles} onKlikBaris={selectRole} testId="role-list"
          kosong={<EmptyState title={roles.length ? 'Tidak ada peran yang cocok' : 'Belum ada peran'}
            description={roles.length ? 'Ubah kata pencarian.' : 'Buat peran pertama untuk mulai mengatur akses.'}
            testId="role-detail-empty" />} />
      )}

      <Notice tone="info" testId="role-access-notice">
        Selama daftar izin sebuah peran <b>masih kosong</b>, sistem memakai aturan bawaan (tidak ada fitur yang mati).
        Begitu minimal satu izin dicentang, peran itu mengikuti daftar izinnya.
        Peran yang belum diatur (tanpa portal dan izin) dan tidak dipakai siapa pun tidak ditawarkan saat menambah
        pengguna; peran itu muncul lagi begitu portal atau izinnya diisi.
      </Notice>


      {/* ── Popup atur peran (5 langkah) ─────────────────────────────────── */}
      <FormPopup open={editorOpen && !!selected} onClose={tutupEditor} ukuran="panjang" testId="role-detail-panel"
        judul={<span data-testid="role-detail-name">{selected ? namaPeran(selected) : '—'}</span>}
        keterangan={(
          <span data-testid="role-detail-summary">
            Boleh membuka {draft.portals.length ? `${draft.portals.length} portal` : 'portal bawaan sistem'} · {draft.permissions.length} izin
            {' '}· {draft.hidden_modules.length} menu disembunyikan · dipakai {selected?.user_count || 0} pengguna
            {dirty && <span className="ml-1 font-medium text-[hsl(var(--warning-text))]" data-testid="role-dirty-badge">· belum disimpan</span>}
          </span>
        )}
        onSimpan={save} menyimpan={saving} bisaSimpan={canEdit && dirty} labelSimpan="Simpan"
        aksiKiri={<>
          <Button type="button" variant="outline" size="sm" onClick={bukaBandingkan} data-testid="compare-roles-btn">
            <Columns3 />Bandingkan
          </Button>
          {canEdit && (
            <Button type="button" variant="outline" size="sm" disabled={!dirty || saving}
              onClick={() => selected && selectRole(selected)} data-testid="role-reset-btn">
              <RotateCcw />Batalkan perubahan
            </Button>
          )}
          {canEdit && selected && !selected.is_system && (
            <Button type="button" variant="destructive" size="sm" onClick={() => removeRole(selected)} data-testid="role-delete-btn">
              <Trash2 />Hapus
            </Button>
          )}
        </>}>
        {!canEdit && (
          <Notice tone="info">Hanya Super Admin yang boleh mengubah konfigurasi peran. Anda melihat mode baca.</Notice>
        )}

        {/* 1. Identitas */}
        <section className="space-y-3">
          <SectionTitle step="1" title="Identitas peran" desc="Kode dipakai pada akun pengguna; keterangan tampil sebagai nama peran." />
          <div className="grid gap-3 sm:grid-cols-2">
            <Isian label="Kode peran" htmlFor="role-name">
              <Input id="role-name" value={draft.name} disabled={!canEdit}
                onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
                placeholder="cth. approver_material" data-testid="role-name" />
            </Isian>
            <Isian label="Keterangan" htmlFor="role-desc">
              <Input id="role-desc" value={draft.description} disabled={!canEdit}
                onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
                placeholder="cth. Menyetujui pengeluaran material" data-testid="role-description" />
            </Isian>
          </div>
          {canEdit && roles.length > 1 && (
            <Isian label="Salin pengaturan dari peran lain" petunjuk="Portal, menu, dan izin disalin; belum tersimpan sampai Anda menekan Simpan.">
              <Select onValueChange={copyFromRole}>
                <SelectTrigger className="w-full sm:w-72" data-testid="copy-from-role">
                  <SelectValue placeholder="Pilih peran sumber…" />
                </SelectTrigger>
                <SelectContent>
                  {roles.filter((r) => r.id !== selectedId).map((r) => (
                    <SelectItem key={r.id} value={r.id}>
                      {namaPeran(r)} ({(r.permission_keys || []).length} izin)
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Isian>
          )}
        </section>

        {/* 2. Akses portal */}
        <section className="space-y-3 border-t border-[var(--glass-border)] pt-4">
          <SectionTitle
            step="2" title="Portal yang boleh dibuka"
            desc="Kosongkan semua bila ingin memakai aturan bawaan sistem untuk peran ini."
            right={canEdit && (
              <div className="flex gap-1.5">
                <Button type="button" variant="outline" size="sm" data-testid="portal-select-all"
                  onClick={() => setDraft((d) => ({ ...d, portals: Object.keys(PORTAL_NAV) }))}>
                  Pilih semua
                </Button>
                <Button type="button" variant="outline" size="sm" data-testid="portal-clear"
                  onClick={() => setDraft((d) => ({ ...d, portals: [] }))}>
                  Pakai bawaan
                </Button>
              </div>
            )}
          />
          <div className="flex flex-wrap gap-2" data-testid="role-portals">
            {Object.keys(PORTAL_NAV).map((pid) => {
              const on = draft.portals.includes(pid);
              return (
                <button
                  key={pid} type="button" disabled={!canEdit}
                  onClick={() => togglePortal(pid)}
                  data-testid={`role-portal-${pid}`}
                  aria-pressed={on}
                  className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60 ${
                    on
                      ? 'border-primary bg-primary text-primary-foreground'
                      : 'border-[var(--glass-border)] bg-[var(--card-surface)] text-foreground hover:border-[hsl(var(--primary)/0.4)]'
                  }`}
                >
                  {on && <Check className="h-3.5 w-3.5" />}
                  {PORTAL_LABEL?.[pid] || pid}
                </button>
              );
            })}
          </div>
        </section>

        {/* 3. Hak akses */}
        <section className="space-y-3 border-t border-[var(--glass-border)] pt-4">
          <SectionTitle
            step="3" title="Hak akses (izin aksi & persetujuan)"
            desc="Per modul: Lihat / Tambah / Ubah / Hapus / Setujui / Unduh. Begitu satu izin per modul dicentang di sebuah portal, semua modul portal itu wajib izinnya (menu tanpa Lihat disembunyikan, aksi tanpa izin ditolak server)."
            right={<StatusBadge status="izin" label={`${draft.permissions.length} izin dipilih`} tone="primary" testId="perm-count-badge" />}
          />

          {canEdit && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="mr-1 text-sm text-muted-foreground">Preset:</span>
              {PRESETS.map((p) => (
                <Button type="button" key={p.id} variant="outline" size="sm" title={p.hint}
                  onClick={() => applyPreset(p)} data-testid={`preset-${p.id}`}>
                  {p.label}
                </Button>
              ))}
              <Button type="button" variant="outline" size="sm" disabled={!!converting}
                title="Isi izin per modul (Lihat/Tambah/Ubah/...) dari izin lama & portal peran ini"
                onClick={() => convertLegacy(null)} data-testid="convert-legacy-all-btn">
                {converting === 'all' ? <Loader2 className="animate-spin" /> : <RotateCcw />} Konversi izin lama → per modul
              </Button>
              <Button type="button" variant="outline" size="sm" onClick={clearPerms} data-testid="preset-clear">
                <X />Kosongkan
              </Button>
            </div>
          )}

          {draft.permissions.length > 0 && (
            <Notice tone="warning">
              Peran ini memakai daftar izin di bawah. Aturan bawaan lama tidak lagi dipakai untuk peran ini —
              pastikan izin yang dibutuhkan sudah dicentang sebelum menyimpan.
            </Notice>
          )}

          <div className="relative w-full sm:w-72">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input value={permSearch} onChange={(e) => setPermSearch(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') e.preventDefault(); }}
              placeholder="Cari izin, modul, atau portal" className="pl-8"
              data-testid="perm-search-input" />
          </div>

          {loading ? (
            <p className="py-6 text-center text-sm text-muted-foreground">Memuat katalog izin…</p>
          ) : visibleGroups.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">Tidak ada izin yang cocok dengan pencarian.</p>
          ) : (
            <Accordion type="multiple" className="space-y-2" data-testid="perm-accordion">
              {visibleGroups.map((grp) => {
                const total = grp.modules.reduce((n, m) => n + m.permissions.length, 0);
                const on = grp.modules.reduce(
                  (n, m) => n + m.permissions.filter((p) => permSet.has(p.key)).length, 0,
                );
                const inScope = !draft.portals.length || draft.portals.includes(grp.portal);
                return (
                  <AccordionItem key={grp.portal} value={grp.portal}
                    className="overflow-hidden rounded-lg border border-[var(--glass-border)] px-3">
                    <AccordionTrigger className="py-3 hover:no-underline" data-testid={`perm-group-${grp.portal}`}>
                      <div className="flex w-full items-center justify-between gap-3 pr-2">
                        <span className="flex items-center gap-2 text-sm font-medium text-foreground">
                          {grp.portal_label}
                          {!inScope && <StatusBadge status="luar" label="Portal tidak dipilih" tone="muted" />}
                        </span>
                        <StatusBadge status="jumlah" label={`${on}/${total}`} tone={on ? 'primary' : 'muted'} className="shrink-0 tabular-nums" />
                      </div>
                    </AccordionTrigger>
                    <AccordionContent className="pb-3">
                      {canEdit && (
                        <div className="mb-3 flex flex-wrap items-center gap-1.5">
                          <span className="text-xs text-muted-foreground">Seluruh portal ini:</span>
                          {LEVELS.map((lv) => (
                            <Button type="button" key={lv.id} variant="outline" size="sm"
                              onClick={() => applyLevelToGroup(grp, lv.id)}
                              data-testid={`group-${grp.portal}-level-${lv.id}`}>
                              {lv.label}
                            </Button>
                          ))}
                          {grp.modules.some((m) => m.granular) && (
                            <Button type="button" variant="outline" size="sm" disabled={!!converting}
                              onClick={() => convertLegacy(grp.portal)}
                              data-testid={`group-${grp.portal}-convert-legacy`}>
                              {converting === grp.portal ? <Loader2 className="animate-spin" /> : <RotateCcw />} Konversi izin lama
                            </Button>
                          )}
                        </div>
                      )}
                      <div className="space-y-2">
                        {[...grp.modules, ...(legacyOpen[grp.portal] ? (grp.legacy_modules || []) : [])].map((mod, idx) => {
                          const lvl = levelOfModule(mod);
                          const levelControl = canEdit && (
                            <div className="inline-flex overflow-hidden rounded-md border border-[var(--glass-border)]"
                              role="group" aria-label={`Tingkat akses ${mod.label}`}>
                              {LEVELS.map((lv) => (
                                <button
                                  key={lv.id} type="button"
                                  onClick={() => applyLevelToModule(mod, lv.id)}
                                  data-testid={`module-${mod.id}-level-${lv.id}`}
                                  aria-pressed={lvl === lv.id}
                                  className={`px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring ${
                                    lvl === lv.id
                                      ? 'bg-primary text-primary-foreground'
                                      : 'bg-[var(--card-surface)] text-muted-foreground hover:text-foreground'
                                  }`}
                                >
                                  {lv.label}
                                </button>
                              ))}
                            </div>
                          );
                          const legacyHeader = idx === grp.modules.length && (
                            <p className="pt-1 text-xs font-medium text-muted-foreground">Izin lama (kompatibilitas)</p>
                          );
                          if (mod.granular) {
                            return (
                              <GranularModuleRow key={mod.id} mod={mod} permSet={permSet} canEdit={canEdit}
                                onToggle={togglePerm} levelControl={levelControl} />
                            );
                          }
                          return (
                            <div key={mod.id}>
                              {legacyHeader}
                              <div className="rounded-lg border border-[var(--glass-border)] p-2.5"
                                data-testid={`perm-module-${mod.id}`}>
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                  <span className="text-sm font-medium text-foreground">{mod.label}</span>
                                  {levelControl}
                                </div>
                                <div className="mt-2 flex flex-wrap gap-1.5">
                                  {mod.permissions.map((p) => {
                                    const on2 = permSet.has(p.key);
                                    return (
                                      <button
                                        key={p.key} type="button" disabled={!canEdit}
                                        onClick={() => togglePerm(p.key)}
                                        title={p.description}
                                        data-testid={`perm-${p.key}`}
                                        aria-pressed={on2}
                                        className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60 ${
                                          on2
                                            ? 'border-primary bg-primary/15 text-primary'
                                            : 'border-[var(--glass-border)] text-muted-foreground hover:border-[hsl(var(--primary)/0.4)] hover:text-foreground'
                                        }`}
                                      >
                                        {on2 && <Check className="h-3 w-3" />}
                                        {p.description}
                                        <span className="opacity-60">· {AKSI_IZIN[p.action] || p.action}</span>
                                      </button>
                                    );
                                  })}
                                </div>
                              </div>
                            </div>
                          );
                        })}
                        {(grp.legacy_modules || []).length > 0 && (
                          <Button type="button" variant="link" size="sm" className="h-auto px-0"
                            onClick={() => setLegacyOpen((o) => ({ ...o, [grp.portal]: !o[grp.portal] }))}
                            data-testid={`legacy-toggle-${grp.portal}`}>
                            {legacyOpen[grp.portal] ? 'Sembunyikan' : 'Tampilkan'} izin lama ({grp.legacy_modules.reduce((n, m) => n + m.permissions.length, 0)})
                            {' '}— otomatis diberikan oleh izin per modul di atas
                          </Button>
                        )}
                      </div>
                    </AccordionContent>
                  </AccordionItem>
                );
              })}
            </Accordion>
          )}
        </section>

        {/* 4. Menu disembunyikan */}
        <section className="border-t border-[var(--glass-border)] pt-4">
          <Collapsible>
            <CollapsibleTrigger asChild>
              <button type="button" className="flex w-full items-center justify-between gap-2 text-left"
                data-testid="hidden-menus-toggle">
                <SectionTitle step="4" title="Sembunyikan menu tertentu (opsional)"
                  desc="Untuk kasus khusus: menu tetap ada di sistem tapi tidak muncul untuk peran ini." />
                <StatusBadge status="menu" label={`${draft.hidden_modules.length} disembunyikan`} tone="muted" className="shrink-0" />
              </button>
            </CollapsibleTrigger>
            <CollapsibleContent className="mt-3 space-y-3" data-testid="role-hidden-modules">
              {(draft.portals.length ? draft.portals : Object.keys(PORTAL_NAV)).map((pid) => {
                const items = menusOfPortal(pid);
                if (!items.length) return null;
                return (
                  <div key={pid}>
                    <p className="mb-1.5 text-sm font-medium text-foreground">{PORTAL_LABEL?.[pid] || pid}</p>
                    <div className="flex flex-wrap gap-1.5">
                      {items.map((it) => {
                        const off = draft.hidden_modules.includes(it.id);
                        return (
                          <button
                            key={`${pid}-${it.id}`} type="button" disabled={!canEdit}
                            onClick={() => toggleMenu(it.id)}
                            data-testid={`role-menu-${it.id}`}
                            aria-pressed={off}
                            className={`rounded-md border px-2 py-1 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60 ${
                              off
                                ? 'border-[hsl(var(--destructive)/0.4)] bg-[hsl(var(--destructive)/0.1)] text-[hsl(var(--danger-text))] line-through'
                                : 'border-[var(--glass-border)] text-muted-foreground hover:border-[hsl(var(--primary)/0.4)] hover:text-foreground'
                            }`}
                          >
                            {it.label}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </CollapsibleContent>
          </Collapsible>
        </section>

        {/* 5. Riwayat perubahan */}
        <section className="border-t border-[var(--glass-border)] pt-4">
          <Collapsible open={auditOpen} onOpenChange={(v) => { setAuditOpen(v); if (v) loadAudit(); }}>
            <CollapsibleTrigger asChild>
              <button type="button" className="flex w-full items-center justify-between gap-2 text-left"
                data-testid="role-audit-toggle">
                <SectionTitle step="5" title="Riwayat perubahan" desc="Siapa mengubah akses peran ini dan kapan." />
                <History className="h-4 w-4 shrink-0 text-muted-foreground" />
              </button>
            </CollapsibleTrigger>
            <CollapsibleContent className="mt-3" data-testid="role-audit-list">
              {auditRows.length === 0 ? (
                <p className="py-4 text-center text-sm text-muted-foreground">Belum ada perubahan tercatat.</p>
              ) : (
                <ul className="divide-y divide-[var(--glass-border)]">
                  {auditRows.map((row) => (
                    <li key={row.id} className="py-2 text-sm">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="font-medium text-foreground">
                          {row.action === 'create' ? 'Dibuat' : row.action === 'delete' ? 'Dihapus' : 'Diubah'}
                          {' '}oleh {row.user_name || '—'}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {row.timestamp ? formatDateTimeID(instan(row.timestamp)) : ''}
                        </span>
                      </div>
                      <AuditDiff row={row} labelIzin={labelIzin} />
                    </li>
                  ))}
                </ul>
              )}
            </CollapsibleContent>
          </Collapsible>
        </section>
      </FormPopup>

      {/* Tambah peran */}
      <FormPopup open={showCreate} onClose={() => setShowCreate(false)} ukuran="pendek" testId="create-role-dialog"
        judul="Tambah peran" keterangan="Beri nama dulu. Portal dan hak aksesnya diatur setelah peran dibuat."
        onSimpan={createRole} menyimpan={saving} bisaSimpan={!!newRole.name.trim()} labelSimpan="Buat peran">
        <Isian label="Kode peran" wajib htmlFor="new-role-name" petunjuk="Huruf kecil dan garis bawah, mis. approver_material.">
          <Input id="new-role-name" value={newRole.name} data-testid="new-role-name"
            onChange={(e) => setNewRole((s) => ({ ...s, name: e.target.value }))}
            placeholder="cth. approver_material" />
        </Isian>
        <Isian label="Keterangan" htmlFor="new-role-desc" petunjuk="Tampil sebagai nama peran di layar.">
          <Input id="new-role-desc" value={newRole.description} data-testid="new-role-description"
            onChange={(e) => setNewRole((s) => ({ ...s, description: e.target.value }))}
            placeholder="cth. Menyetujui pengeluaran material" />
        </Isian>
      </FormPopup>

      {/* Bandingkan peran */}
      {compareOpen && (
        <DetailPopup open onClose={() => setCompareOpen(false)} testId="compare-sheet" judul="Bandingkan peran"
          keterangan="Selisih izin antara peran terpilih (termasuk perubahan yang belum disimpan) dan peran lain.">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status="a" label={selected ? namaPeran(selected) : '—'} tone="primary" />
            <span className="text-sm text-muted-foreground">dibandingkan dengan</span>
            <Select value={compareWith} onValueChange={setCompareWith}>
              <SelectTrigger className="w-full sm:w-60" data-testid="compare-role-select">
                <SelectValue placeholder="Pilih peran…" />
              </SelectTrigger>
              <SelectContent>
                {roles.filter((r) => r.id !== selectedId).map((r) => (
                  <SelectItem key={r.id} value={r.id}>{namaPeran(r)}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {compareRole ? (
            <CompareBody
              a={{ name: selected ? namaPeran(selected) : 'A', portals: draft.portals, perms: draft.permissions }}
              b={{ name: namaPeran(compareRole), portals: compareRole.portals || [], perms: compareRole.permission_keys || [] }}
              allPerms={allPerms}
            />
          ) : (
            <p className="py-6 text-center text-sm text-muted-foreground">Pilih peran pembanding di atas.</p>
          )}
        </DetailPopup>
      )}
    </PageLayout>
  );
}

/* ── potongan UI kecil ───────────────────────────────────────────────────── */
const AKSI_IZIN = {
  view: 'lihat', input: 'input', create: 'tambah', edit: 'ubah', delete: 'hapus', manage: 'kelola',
  approve: 'setujui', run: 'jalankan', export: 'unduh',
};
const namaPortalIzin = (list) => list.map((p) => PORTAL_LABEL?.[p] || p).join(', ');

function SectionTitle({ step, title, desc, right }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div className="flex items-start gap-2">
        {step && (
          <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/15 text-xs font-semibold text-primary">
            {step}
          </span>
        )}
        <div>
          <h4 className="text-base font-semibold text-foreground">{title}</h4>
          {desc && <p className="mt-0.5 text-sm text-muted-foreground">{desc}</p>}
        </div>
      </div>
      {right}
    </div>
  );
}

function AuditDiff({ row, labelIzin = {} }) {
  const before = (row.before?.permissions) || [];
  const after = (row.after?.permissions) || [];
  const added = after.filter((k) => !before.includes(k));
  const removed = before.filter((k) => !after.includes(k));
  const pBefore = (row.before?.portals) || [];
  const pAfter = (row.after?.portals) || [];
  const portalChanged = pBefore.join(',') !== pAfter.join(',');
  if (!added.length && !removed.length && !portalChanged) return null;
  const nama = (k) => labelIzin[k] || k;
  return (
    <div className="mt-1.5 space-y-1 text-xs">
      {portalChanged && (
        <p className="text-muted-foreground">
          Portal: <span className="line-through">{namaPortalIzin(pBefore) || 'bawaan'}</span>
          {' → '}<span className="text-foreground">{namaPortalIzin(pAfter) || 'bawaan'}</span>
        </p>
      )}
      {added.length > 0 && (
        <p className="text-[hsl(var(--success-text))]">Ditambah: {added.map(nama).join(', ')}</p>
      )}
      {removed.length > 0 && (
        <p className="text-[hsl(var(--danger-text))]">Dicabut: {removed.map(nama).join(', ')}</p>
      )}
    </div>
  );
}

function CompareBody({ a, b, allPerms }) {
  const setA = new Set(a.perms);
  const setB = new Set(b.perms);
  const onlyA = allPerms.filter((p) => setA.has(p.key) && !setB.has(p.key));
  const onlyB = allPerms.filter((p) => setB.has(p.key) && !setA.has(p.key));
  const both = allPerms.filter((p) => setA.has(p.key) && setB.has(p.key));
  return (
    <div className="space-y-4" data-testid="compare-body">
      <div className="grid grid-cols-3 gap-2">
        <StatTile label={`Hanya ${a.name || 'A'}`} value={onlyA.length} />
        <StatTile label="Sama" value={both.length} />
        <StatTile label={`Hanya ${b.name || 'B'}`} value={onlyB.length} />
      </div>
      <dl className="divide-y divide-[var(--glass-border)]">
        <BarisDetail label={`Portal ${a.name}`}>{a.portals.length ? namaPortalIzin(a.portals) : 'Bawaan sistem'}</BarisDetail>
        <BarisDetail label={`Portal ${b.name}`}>{b.portals.length ? namaPortalIzin(b.portals) : 'Bawaan sistem'}</BarisDetail>
      </dl>
      {[[`Hanya ada di ${a.name}`, onlyA], [`Hanya ada di ${b.name}`, onlyB]].map(([label, list]) => (
        <div key={label} className="space-y-1.5">
          <p className="text-sm font-medium text-foreground">{label} ({list.length})</p>
          {list.length === 0 ? (
            <p className="text-sm text-muted-foreground">Tidak ada.</p>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {list.map((p) => <StatusBadge key={p.key} status="izin" label={p.description} tone="default" />)}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

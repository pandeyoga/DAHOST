/**
 * CMTOverridePortalModule — menu **"Input atas nama CMT"** (Portal Produksi & Maklon, layar yang sama).
 *
 * MASALAH NYATA: sebagian vendor CMT tidak memakai sistem, padahal tagihan CMT dihitung dari progress yang
 * mereka isi. Layar ini memberi staf DA jalan resmi untuk mengisi 11 modul Portal Vendor ATAS NAMA vendor —
 * tanpa akun bayangan, dan jejak "diinput staf DA" tetap tercatat & terlihat (badge di pantau/tagihan).
 *
 * KEPUTUSAN OWNER (2026-08-08): 1a semua 11 modul di-mirror · 2b hanya admin · superadmin · admin_produksi ·
 * supervisor_produksi · ppic · 3a jejak tercatat + kelihatan · 4a daftar = vendor aktif di master CMT ·
 * 5a vendor yang punya akun portal aktif tetap boleh diisi, dengan peringatan dobel input.
 *
 * Tahap 9 (7 Nov 2026, "menu & tampilan dua portal identik"):
 *   • Vendor dipilih dari TABEL (cari, hanya vendor aktif) — dulu kartu tinggi per vendor (±58 kartu).
 *   • Rekap harian/mingguan pindah ke tab "Rekap pengisian" (penyaring Harian · Mingguan).
 *   • Mode isi: cetakan PageLayout + tab standar (HubTabs) untuk 11 modul + Jejak audit — dulu deret tombol
 *     buatan sendiri dan judul h1 sendiri.
 *
 * CARA KERJA: komponen `engine/Vendor*.jsx` dipakai ULANG APA ADANYA. Konteks "mewakili vendor X" dikirim lewat
 * satu header (`setCmtOverrideVendor`) dan scoping-nya dikerjakan backend (`core/cmt_override.py`), jadi angka
 * di sini MUSTAHIL berbeda dari yang vendor lihat. Header di-SET saat vendor dipilih dan DI-CLEAR saat keluar.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, ArrowLeft, RefreshCw, Search, ShieldCheck, UserCog, Users, X } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatDateTimeID } from '@/lib/format';
import { apiGet, setCmtOverrideVendor, clearCmtOverrideVendor } from '../../lib/api';
import PageLayout from './layout/PageLayout';
import { PageLayoutSatuBaris } from './engine/DataTable';
import HubTabs from './hubs/HubTabs';
import { EmptyState, Notice, StatTile } from './moduleAtoms';

import VendorDashboard from './engine/VendorDashboard';
import VendorReceiving from './engine/VendorReceiving';
import VendorMaterialInspection from './engine/VendorMaterialInspection';
import VendorMaterialRequests from './engine/VendorMaterialRequests';
import VendorProductionJobs from './engine/VendorProductionJobs';
import VendorProductionGuide from './engine/VendorProductionGuide';
import VendorProgress from './engine/VendorProgress';
import VendorBuyerShipments from './engine/VendorBuyerShipments';
import VendorSerialTracking from './engine/VendorSerialTracking';
import VendorVarianceReport from './engine/VendorVarianceReport';
import VendorReminderInbox from './engine/VendorReminderInbox';
import CMTOverrideRecapPanel from './cmt-override/CMTOverrideRecapPanel';

// Role yang berwenang (harus sama dengan core/cmt_override.OVERRIDE_ROLES).
const ALLOWED_ROLES = ['admin', 'superadmin', 'admin_produksi', 'supervisor_produksi', 'ppic'];
const ROLE_LABEL = {
  admin: 'Admin', superadmin: 'Superadmin', admin_produksi: 'Admin produksi',
  supervisor_produksi: 'Supervisor produksi', ppic: 'PPIC',
};

// 11 modul — urutan & label sama dengan Portal Vendor CMT (VendorPortalApp.jsx), supaya staf yang memandu
// vendor lewat telepon tidak perlu belajar ulang.
const MODULES = [
  { id: 'dashboard', label: 'Ringkasan', Comp: VendorDashboard },
  { id: 'receiving', label: 'Penerimaan material', Comp: VendorReceiving },
  { id: 'inspeksi', label: 'Inspeksi material', Comp: VendorMaterialInspection },
  { id: 'material-requests', label: 'Permintaan material', Comp: VendorMaterialRequests },
  { id: 'production-jobs', label: 'Pekerjaan produksi', Comp: VendorProductionJobs },
  { id: 'production-guide', label: 'Panduan produksi', Comp: VendorProductionGuide },
  { id: 'progress', label: 'Progress produksi', Comp: VendorProgress },
  { id: 'buyer-shipments', label: 'Kirim ke DA', Comp: VendorBuyerShipments },
  { id: 'serial-tracking', label: 'Lacak serial', Comp: VendorSerialTracking },
  { id: 'variance-report', label: 'Laporan selisih', Comp: VendorVarianceReport },
  { id: 'reminders', label: 'Pengingat', Comp: VendorReminderInbox },
];

// Standar UI/UX v2 (8 Nov 2026): 11 modul + jejak audit dikelompokkan menjadi 6 tab (dulu 12 tab bertumpuk dua
// baris). Modul dalam satu kelompok dipilih dengan pil di bawah tab — urutan & label modul tetap sama.
const GROUPS = [
  { key: 'g-ringkasan', label: 'Ringkasan', modules: ['dashboard'] },
  { key: 'g-bahan', label: 'Bahan', modules: ['receiving', 'inspeksi', 'material-requests'] },
  { key: 'g-produksi', label: 'Produksi', modules: ['production-jobs', 'production-guide', 'progress'] },
  { key: 'g-kirim', label: 'Kirim & lacak', modules: ['buyer-shipments', 'serial-tracking', 'variance-report'] },
  { key: 'g-pengingat', label: 'Pengingat', modules: ['reminders'] },
  { key: 'g-audit', label: 'Jejak audit', modules: ['__audit'] },
];
const groupOf = (moduleId) => GROUPS.find((g) => g.modules.includes(moduleId)) || GROUPS[0];

/** Isi satu tab kelompok: pil modul (bila > 1) lalu modul aktif. Modul bisa pindah ke modul lain (onNavigate). */
function ModuleGroup({ group, activeModule, setActiveModule, token, user, vendorName }) {
  const current = group.modules.includes(activeModule) ? activeModule : group.modules[0];
  const render = (id) => {
    if (id === '__audit') return <AuditPanel vendorName={vendorName} />;
    const m = MODULES.find((x) => x.id === id);
    return m ? <m.Comp token={token} user={user} onNavigate={setActiveModule} /> : null;
  };
  if (group.modules.length === 1) return render(current);
  return (
    <div className="space-y-4" data-testid={`cmt-override-group-${group.key}`}>
      {/* Pil modul (penyaring), bukan tab di dalam tab. */}
      <FilterChips value={current} onChange={setActiveModule} hideWhenEmpty={false} ariaLabel={`Modul ${group.label}`}
        testId="cmt-override-module" options={group.modules.map((id) => ({ key: id, label: MODULES.find((x) => x.id === id)?.label || id }))} />
      {render(current)}
    </div>
  );
}

const fmtDT = (v) => (v ? formatDateTimeID(v) : '—');
const fmtNum = (v) => Number(v || 0).toLocaleString('id-ID');

function AccessDenied({ role }) {
  return (
    <PageLayoutSatuBaris testId="cmt-override-denied" title="Input atas nama CMT"
      subtitle="Mengisi data atas nama vendor CMT berpengaruh langsung ke tagihan CMT.">
      <GlassCard>
        <EmptyState icon={ShieldCheck} title="Tidak berwenang"
          description={`Layar ini hanya untuk: ${ALLOWED_ROLES.map((r) => ROLE_LABEL[r]).join(', ')}. Peran Anda: ${ROLE_LABEL[role] || role || '—'}.`} />
      </GlassCard>
    </PageLayoutSatuBaris>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Tab "Pilih vendor" — tabel vendor aktif
// ══════════════════════════════════════════════════════════════════════════════
function VendorPicker({ vendors, loading, err, onPick, onReload }) {
  const [search, setSearch] = useState('');
  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    const list = q ? vendors.filter((v) => `${v.name} ${v.code} ${v.contact_name}`.toLowerCase().includes(q)) : vendors.slice();
    list.sort((a, b) => (Number(b.pending_actions || 0) - Number(a.pending_actions || 0)) || String(a.name).localeCompare(String(b.name)));
    return list;
  }, [vendors, search]);
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(rows, 25);
  const withAccount = vendors.filter((v) => v.has_active_portal_account).length;

  const akun = (v) => (v.has_active_portal_account
    ? `Aktif · ${v.last_login_at ? `login ${fmtDT(v.last_login_at)}` : 'belum pernah login'}`
    : 'Tanpa akun');
  const kolom = [
    { kunci: 'vendor', label: 'Vendor', hp: 'judul', isi: (v) => (
      <div className="min-w-0">
        <span className="block font-medium text-foreground">{v.name}</span>
        <span className="block text-xs text-muted-foreground">{[v.code, v.contact_name, v.contact_phone].filter(Boolean).join(' · ') || '—'}</span>
      </div>) },
    { kunci: 'masuk', label: 'Kiriman masuk', rata: 'kanan', isi: (v) => <span className="tabular-nums">{fmtNum(v.incoming_shipments)}</span> },
    { kunci: 'inspeksi', label: 'Belum inspeksi', rata: 'kanan', isi: (v) => <span className="tabular-nums">{fmtNum(v.uninspected_shipments)}</span> },
    { kunci: 'job', label: 'Job jalan', rata: 'kanan', isi: (v) => <span className="tabular-nums">{fmtNum(v.active_jobs)}</span> },
    { kunci: 'ingat', label: 'Pengingat', rata: 'kanan', isi: (v) => <span className="tabular-nums">{fmtNum(v.open_reminders)}</span> },
    { kunci: 'perlu', label: 'Perlu diisi', rata: 'kanan', isi: (v) => (Number(v.pending_actions || 0) > 0
      ? <span className="font-semibold tabular-nums text-[hsl(var(--warning-text))]">{fmtNum(v.pending_actions)}</span>
      : <span className="tabular-nums text-muted-foreground">0</span>) },
    { kunci: 'akun', label: 'Akun Portal Vendor', isi: (v) => (
      <span className={`text-xs ${v.has_active_portal_account ? 'text-[hsl(var(--warning-text))]' : 'text-muted-foreground'}`}
        data-testid={`cmt-override-account-${v.id}`}>{akun(v)}</span>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (v) => (
      <Button type="button" size="sm" variant="outline" onClick={() => onPick(v)} data-testid={`cmt-override-pick-${v.id}`}>
        <UserCog className="w-3.5 h-3.5" />Isi atas nama
      </Button>) },
  ];

  return (
    <PageLayoutSatuBaris testId="cmt-override-picker" title="Pilih vendor" subtitle="Vendor CMT aktif yang bisa diisi atas namanya."
      filters={<div className="relative w-full sm:w-64">
        <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari nama, kode, kontak"
          className="pl-8" data-testid="cmt-override-search" />
      </div>}
      tools={<>
        <TombolUnduh namaBerkas="vendor-cmt-input-atas-nama" namaLembar="Vendor" baris={rows} testId="cmt-override-unduh"
          kolom={[
            { label: 'Vendor', nilai: (v) => v.name }, { label: 'Kode', nilai: (v) => v.code || '' },
            { label: 'Kontak', nilai: (v) => v.contact_name || '' }, { label: 'Telepon', nilai: (v) => v.contact_phone || '' },
            { label: 'Kiriman masuk', nilai: (v) => Number(v.incoming_shipments) || 0 },
            { label: 'Belum inspeksi', nilai: (v) => Number(v.uninspected_shipments) || 0 },
            { label: 'Job jalan', nilai: (v) => Number(v.active_jobs) || 0 },
            { label: 'Pengingat', nilai: (v) => Number(v.open_reminders) || 0 },
            { label: 'Perlu diisi', nilai: (v) => Number(v.pending_actions) || 0 },
            { label: 'Akun Portal Vendor', nilai: akun },
          ]} />
        <Button type="button" variant="outline" size="icon" onClick={onReload} title="Muat ulang" aria-label="Muat ulang" data-testid="cmt-override-refresh">
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </>}
      summary={<>
        {err && <Notice tone="danger" icon={AlertTriangle} testId="cmt-override-error">{err}</Notice>}
        <p className="text-sm text-muted-foreground" data-testid="cmt-override-summary">
          {fmtNum(vendors.length)} vendor aktif{withAccount > 0 ? ` · ${fmtNum(withAccount)} punya akun Portal Vendor (hati-hati dobel input)` : ''}.
          Dokumen yang Anda simpan tercatat atas nama vendor, dengan nama Anda dan tanda “diinput staf DA”.
        </p>
      </>}
      footer={rows.length > pageSize && <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />}>
      {loading && !vendors.length ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat vendor…</p>
      ) : (
        <TabelData kolom={kolom} baris={paged} testId="cmt-override-vendor-table"
          kosong={<div data-testid="cmt-override-empty">
            <EmptyState icon={Users} title={vendors.length ? 'Tidak ada vendor yang cocok' : 'Belum ada vendor CMT aktif'}
              description={vendors.length ? 'Ubah kata pencarian.' : 'Tambahkan vendor lewat menu Vendor CMT.'}
              action={search ? <Button type="button" variant="outline" size="sm" onClick={() => setSearch('')}><X className="w-3.5 h-3.5" />Hapus pencarian</Button> : null} />
          </div>} />
      )}
    </PageLayoutSatuBaris>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Tab "Jejak audit" (mode isi)
// ══════════════════════════════════════════════════════════════════════════════
function AuditPanel({ vendorName }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    setLoading(true);
    try { setData(await apiGet('/cmt-override/audit?limit=100')); }
    catch (e) { toast.error(e.message || 'Gagal memuat jejak audit'); setData({ entries: [], totals: { staff: 0, vendor: 0 } }); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);
  const totals = data?.totals || { staff: 0, vendor: 0 };
  const entries = data?.entries || [];
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(entries, 25);

  return (
    <div className="space-y-4" data-testid="cmt-override-audit-panel">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="text-sm text-muted-foreground max-w-3xl">
          Tagihan CMT dihitung dari dokumen-dokumen ini. Daftar ini memisahkan yang diketik staf DA dari yang diisi
          {` ${vendorName} `}sendiri, supaya selisih tagihan bisa ditelusuri.
        </p>
        <div className="flex items-center gap-2">
          <TombolUnduh namaBerkas={`jejak-input-${vendorName}`} namaLembar="Jejak" baris={entries} testId="cmt-override-audit-unduh"
            kolom={[
              { label: 'Modul', nilai: (e) => e.module || '' }, { label: 'Dokumen', nilai: (e) => e.reference || '' },
              { label: 'Diinput oleh', nilai: (e) => e.entered_by || '' },
              { label: 'Peran', nilai: (e) => ROLE_LABEL[e.entered_by_role] || e.entered_by_role || '' },
              { label: 'Waktu', nilai: (e) => fmtDT(e.entered_at) },
            ]} />
          <Button type="button" size="icon" variant="outline" onClick={load} title="Muat ulang" aria-label="Muat ulang" data-testid="cmt-override-audit-refresh">
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </Button>
        </div>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <StatTile label="Diinput staf DA" accent={Number(totals.staff) ? 'warning' : 'muted'} sub="Diketik staf DA atas nama vendor" 
          value={<span data-testid="cmt-override-audit-staff">{totals.staff}</span>} />
        <StatTile label="Diisi vendor sendiri" accent={Number(totals.vendor) ? 'success' : 'muted'} sub="Lewat Portal Vendor" 
          value={<span data-testid="cmt-override-audit-vendor">{totals.vendor}</span>} />
        <StatTile label="Total dokumen" value={(totals.staff || 0) + (totals.vendor || 0)} sub="Staf DA + vendor sendiri" />
      </div>
      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <div className="p-4 text-sm text-muted-foreground">Memuat jejak…</div>
        ) : !entries.length ? (
          <div data-testid="cmt-override-audit-empty">
            <EmptyState icon={UserCog} title="Belum ada input staf DA untuk vendor ini"
              description="Dokumen yang Anda simpan atas nama vendor akan tercatat di sini." />
          </div>
        ) : (
          <Table>
            <TableHeader><TableRow>
              <TableHead>Modul</TableHead><TableHead>Dokumen</TableHead><TableHead>Diinput oleh</TableHead>
              <TableHead>Peran</TableHead><TableHead>Waktu</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {paged.map((e, i) => (
                <TableRow key={`${e.collection}-${e.doc_id}-${i}`}>
                  <TableCell className="font-medium">{e.module}</TableCell>
                  <TableCell className="text-xs text-[hsl(var(--primary))]">{e.reference || '—'}</TableCell>
                  <TableCell>{e.entered_by || '—'}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{ROLE_LABEL[e.entered_by_role] || e.entered_by_role || '—'}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{fmtDT(e.entered_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </GlassCard>
      {entries.length > pageSize && <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
export default function CMTOverridePortalModule({ user, token }) {
  const role = (user?.role || '').toLowerCase();
  const allowed = ALLOWED_ROLES.includes(role);

  const [vendors, setVendors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [selected, setSelected] = useState(null);
  const [activeModule, setActiveModuleRaw] = useState('dashboard');
  // Tab hub = KELOMPOK modul; memilih kelompok membuka modul pertamanya. Id modul (dari Rekap / Ringkasan) langsung dipakai.
  const setActiveModule = useCallback((key) => {
    const grp = GROUPS.find((x) => x.key === key);
    setActiveModuleRaw(grp ? grp.modules[0] : key);
  }, []);
  const [warnOpen, setWarnOpen] = useState(true);
  const mounted = useRef(true);

  const loadVendors = useCallback(async () => {
    setLoading(true); setErr('');
    // Daftar vendor dibaca TANPA konteks override (kita belum memilih siapa pun). Hanya vendor aktif (4a).
    clearCmtOverrideVendor();
    try {
      const d = await apiGet('/cmt-override/vendors');
      if (!mounted.current) return;
      setVendors(Array.isArray(d?.vendors) ? d.vendors.filter((v) => v.is_active !== false) : []);
    } catch (e) {
      if (!mounted.current) return;
      setErr(e.message || 'Gagal memuat daftar vendor CMT');
      setVendors([]);
    } finally { if (mounted.current) setLoading(false); }
  }, []);

  useEffect(() => {
    mounted.current = true;
    if (allowed) loadVendors();
    // Jaring pengaman MUTLAK: begitu layar ini ditinggalkan, konteks override WAJIB hilang — kalau tidak,
    // layar staf berikutnya bisa diam-diam ter-scope ke satu vendor dan menampilkan angka yang salah.
    return () => { mounted.current = false; clearCmtOverrideVendor(); };
  }, [allowed, loadVendors]);

  // Header di-set SINKRON sebelum state berubah: efek komponen ANAK berjalan lebih dulu daripada efek induk,
  // jadi menunggu useEffect membuat permintaan pertama tiap modul terkirim tanpa header.
  // `moduleId` opsional: dari Rekap Harian, kotak "belum diisi" membawa modul tujuannya.
  const pickVendor = useCallback((v, moduleId = null) => {
    setCmtOverrideVendor(v.id);
    setSelected(v);
    setActiveModule(MODULES.some((m) => m.id === moduleId) ? moduleId : 'dashboard');
    setWarnOpen(true);
  }, []);

  const pickFromRecap = useCallback((row, moduleId) => {
    if (!row?.vendor_id) return;
    const known = vendors.find((v) => v.id === row.vendor_id);
    pickVendor(known || {
      id: row.vendor_id, name: row.vendor_name, code: row.vendor_code,
      has_active_portal_account: row.has_active_portal_account, last_login_at: row.last_login_at, accounts: [],
    }, moduleId);
  }, [vendors, pickVendor]);

  const backToPicker = () => {
    clearCmtOverrideVendor();
    setSelected(null);
    loadVendors();
  };

  // `user` sintetis untuk komponen vendor: mereka hanya memakai `user.vendor_id` (payload) dan `user.name` (judul).
  const vendorUser = useMemo(() => (selected ? {
    id: user?.id, name: selected.name, role: 'cmt_vendor', vendor_id: selected.id, cmt_vendor_id: selected.id,
  } : null), [selected, user?.id]);

  const groupTabs = useMemo(() => (selected ? GROUPS.map((g) => ({
    key: g.key, label: g.label, Component: ModuleGroup,
    props: { group: g, activeModule, setActiveModule, token, user: vendorUser, vendorName: selected.name },
  })) : []), [selected, activeModule, setActiveModule, token, vendorUser]);

  const pickerTabs = useMemo(() => [
    { key: 'vendor', label: 'Pilih vendor', Component: VendorPicker,
      props: { vendors, loading, err, onPick: pickVendor, onReload: loadVendors } },
    { key: 'rekap', label: 'Rekap pengisian', Component: CMTOverrideRecapPanel, props: { onOpenVendor: pickFromRecap } },
  ], [vendors, loading, err, pickVendor, loadVendors, pickFromRecap]);

  if (!allowed) return <AccessDenied role={role} />;

  // ── LAYAR 1: pilih vendor / rekap ───────────────────────────────────────
  if (!selected) {
    return <HubTabs hubId="cmt-override-portal" title="Input atas nama CMT" compactHeaders tabs={pickerTabs} />;
  }

  // ── LAYAR 2: mode isi atas nama vendor ──────────────────────────────────
  return (
    <PageLayoutSatuBaris testId="cmt-override-active" title={`Atas nama ${selected.name}`}
      subtitle={`Layar ini sama persis dengan Portal Vendor milik ${selected.name}. Yang Anda simpan tercatat dengan nama Anda.`}
      actions={<Button type="button" variant="outline" onClick={backToPicker} data-testid="cmt-override-change-vendor"><ArrowLeft className="h-4 w-4" />Ganti vendor</Button>}
      summary={<>
        {/* Penanda mode isi — satu baris tipis (dulu spanduk lengket yang memakan layar). Nama vendor juga di judul. */}
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-[hsl(var(--warning-text))]" data-testid="cmt-override-mode-line">
          <UserCog className="h-4 w-4 shrink-0" />
          <span>Mode isi atas nama <span data-testid="cmt-override-vendor-name" className="font-semibold">{selected.name}</span>
            {selected.code ? ` · ${selected.code}` : ''} — diinput oleh{' '}
            <span data-testid="cmt-override-staff-name" className="font-semibold">{user?.name || '—'}</span>{` (${ROLE_LABEL[role] || role})`}</span>
        </p>
        {/* Peringatan dobel input (keputusan 5a) — memberi tahu, TIDAK memblokir. */}
        {selected.has_active_portal_account && warnOpen && (
          <Notice tone="warning" icon={AlertTriangle} title="Hati-hati dobel input" testId="cmt-override-double-warning"
            action={<Button type="button" size="sm" variant="outline" onClick={() => setWarnOpen(false)} data-testid="cmt-override-warning-dismiss">Mengerti</Button>}>
            Vendor ini punya akun Portal Vendor aktif ({selected.last_login_at ? `terakhir login ${fmtDT(selected.last_login_at)}` : 'belum pernah login'}). Kalau vendor juga
            mengisi sendiri, progress bisa terhitung dua kali dan tagihan CMT ikut salah.
            {Array.isArray(selected.accounts) && selected.accounts.length > 0 && (
              <span className="block mt-1 text-xs text-muted-foreground">
                {selected.accounts.map((a) => `${a.email} (${a.is_active ? 'aktif' : 'nonaktif'}, ${a.last_login_at ? `login ${fmtDT(a.last_login_at)}` : 'belum pernah login'})`).join(' · ')}
              </span>
            )}
          </Notice>
        )}
      </>}>
      <HubTabs hubId="cmt-override-modules" tabs={groupTabs} value={groupOf(activeModule).key} onValueChange={setActiveModule} />
    </PageLayoutSatuBaris>
  );
}

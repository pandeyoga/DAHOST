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
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatDateTimeID } from '@/lib/format';
import { apiGet, setCmtOverrideVendor, clearCmtOverrideVendor } from '../../lib/api';
import PageLayout from './layout/PageLayout';
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

const fmtDT = (v) => (v ? formatDateTimeID(v) : '—');
const fmtNum = (v) => Number(v || 0).toLocaleString('id-ID');

function AccessDenied({ role }) {
  return (
    <PageLayout testId="cmt-override-denied" title="Input atas nama CMT"
      subtitle="Mengisi data atas nama vendor CMT berpengaruh langsung ke tagihan CMT.">
      <GlassCard>
        <EmptyState icon={ShieldCheck} title="Tidak berwenang"
          description={`Layar ini hanya untuk: ${ALLOWED_ROLES.map((r) => ROLE_LABEL[r]).join(', ')}. Peran Anda: ${ROLE_LABEL[role] || role || '—'}.`} />
      </GlassCard>
    </PageLayout>
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

  return (
    <PageLayout testId="cmt-override-picker" title="Pilih vendor" subtitle="Vendor CMT aktif yang bisa diisi atas namanya."
      filters={<div className="relative w-72 max-w-full">
        <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <GlassInput value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari nama / kode / kontak vendor…"
          className="pl-8 h-9" data-testid="cmt-override-search" />
      </div>}
      tools={<Button variant="outline" size="icon" onClick={onReload} title="Muat ulang" aria-label="Muat ulang" data-testid="cmt-override-refresh">
        <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
      </Button>}
      summary={<>
        {err && <Notice tone="danger" icon={AlertTriangle} testId="cmt-override-error">{err}</Notice>}
        <p className="text-sm text-muted-foreground" data-testid="cmt-override-summary">
          {fmtNum(vendors.length)} vendor aktif{withAccount > 0 ? ` · ${fmtNum(withAccount)} punya akun Portal Vendor (hati-hati dobel input)` : ''}.
          Setiap dokumen yang Anda simpan tercatat atas nama vendor, dengan nama Anda dan tanda “diinput staf DA”.
        </p>
      </>}
      footer={rows.length > pageSize && <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />}>
      <GlassCard className="p-0 overflow-hidden">
        {loading && !vendors.length ? (
          <div className="p-4 text-sm text-muted-foreground">Memuat vendor…</div>
        ) : !paged.length ? (
          <div data-testid="cmt-override-empty">
            <EmptyState icon={Users} title={vendors.length ? 'Tidak ada vendor yang cocok' : 'Belum ada vendor CMT aktif'}
              description={vendors.length ? 'Ubah kata pencarian.' : 'Tambahkan vendor lewat menu Vendor CMT.'}
              action={search ? <Button variant="outline" size="sm" onClick={() => setSearch('')}><X className="w-3.5 h-3.5" />Hapus pencarian</Button> : null} />
          </div>
        ) : (
          <Table data-testid="cmt-override-vendor-table">
            <TableHeader><TableRow>
              <TableHead>Vendor</TableHead><TableHead>Kontak</TableHead>
              <TableHead className="text-right">Kiriman masuk</TableHead><TableHead className="text-right">Belum inspeksi</TableHead>
              <TableHead className="text-right">Job jalan</TableHead><TableHead className="text-right">Pengingat</TableHead>
              <TableHead className="text-right">Perlu diisi</TableHead><TableHead>Akun Portal Vendor</TableHead>
              <TableHead className="text-right">Aksi</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {paged.map((v) => (
                <TableRow key={v.id} data-testid={`cmt-override-vendor-${v.id}`}>
                  <TableCell>
                    <span className="block font-semibold text-foreground">{v.name}</span>
                    <span className="block text-xs text-muted-foreground">{v.code || '—'}</span>
                  </TableCell>
                  <TableCell className="text-sm">{v.contact_name || '—'}{v.contact_phone ? <span className="block text-xs text-muted-foreground">{v.contact_phone}</span> : null}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNum(v.incoming_shipments)}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNum(v.uninspected_shipments)}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNum(v.active_jobs)}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNum(v.open_reminders)}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {Number(v.pending_actions || 0) > 0
                      ? <span className="font-semibold text-[hsl(var(--warning-text))]">{fmtNum(v.pending_actions)}</span>
                      : <span className="text-muted-foreground">0</span>}
                  </TableCell>
                  <TableCell className="text-xs" data-testid={`cmt-override-account-${v.id}`}>
                    {v.has_active_portal_account ? (
                      <span className="text-[hsl(var(--warning-text))]">Aktif · {v.last_login_at ? `login terakhir ${fmtDT(v.last_login_at)}` : 'belum pernah login'}</span>
                    ) : <span className="text-muted-foreground">Tanpa akun — memang diisi staf</span>}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button size="sm" variant="outline" onClick={() => onPick(v)} data-testid={`cmt-override-pick-${v.id}`}>
                      <UserCog className="w-3.5 h-3.5" />Isi atas nama
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </GlassCard>
    </PageLayout>
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
        <Button size="icon" variant="outline" onClick={load} title="Muat ulang" aria-label="Muat ulang" data-testid="cmt-override-audit-refresh">
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <StatTile label="Diinput staf DA" accent={Number(totals.staff) ? 'warning' : 'muted'}
          value={<span data-testid="cmt-override-audit-staff">{totals.staff}</span>} />
        <StatTile label="Diisi vendor sendiri" accent={Number(totals.vendor) ? 'success' : 'muted'}
          value={<span data-testid="cmt-override-audit-vendor">{totals.vendor}</span>} />
        <StatTile label="Total dokumen" value={(totals.staff || 0) + (totals.vendor || 0)} />
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
  const [activeModule, setActiveModule] = useState('dashboard');
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

  const moduleTabs = useMemo(() => (selected ? [
    ...MODULES.map((m) => ({
      key: m.id, label: m.label, Component: m.Comp,
      props: { token, user: vendorUser, onNavigate: setActiveModule },
    })),
    { key: '__audit', label: 'Jejak audit', Component: AuditPanel, props: { vendorName: selected.name } },
  ] : []), [selected, token, vendorUser]);

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
    <PageLayout testId="cmt-override-active" title={`Atas nama ${selected.name}`}
      subtitle={`Layar ini sama persis dengan Portal Vendor milik ${selected.name}. Yang Anda simpan tercatat dengan nama Anda.`}
      actions={<Button variant="outline" onClick={backToPicker} data-testid="cmt-override-change-vendor"><ArrowLeft className="h-4 w-4" />Ganti vendor</Button>}
      summary={<>
        {/* Spanduk mode override — SELALU terlihat (sticky) supaya tidak ada yang mengisi tanpa sadar. */}
        <Notice tone="warning" icon={UserCog} title="Mode isi atas nama vendor" className="sticky top-0 z-30 shadow-sm">
          <span data-testid="cmt-override-vendor-name" className="font-semibold">{selected.name}</span>
          {selected.code ? ` · ${selected.code}` : ''} — diinput oleh{' '}
          <span data-testid="cmt-override-staff-name" className="font-semibold">{user?.name || '—'}</span>
          {` (${ROLE_LABEL[role] || role})`}
        </Notice>
        {/* Peringatan dobel input (keputusan 5a) — memberi tahu, TIDAK memblokir. */}
        {selected.has_active_portal_account && warnOpen && (
          <Notice tone="warning" icon={AlertTriangle} title="Hati-hati dobel input" testId="cmt-override-double-warning"
            action={<Button size="sm" variant="outline" onClick={() => setWarnOpen(false)} data-testid="cmt-override-warning-dismiss">Mengerti</Button>}>
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
      <HubTabs hubId="cmt-override-modules" tabs={moduleTabs} value={activeModule} onValueChange={setActiveModule} />
    </PageLayout>
  );
}

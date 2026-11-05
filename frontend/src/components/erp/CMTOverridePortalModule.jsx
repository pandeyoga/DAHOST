/**
 * CMTOverridePortalModule — pintu **"Input Vendor CMT"** (Portal CMT Override).
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * MASALAH NYATA
 * ═══════════════════════════════════════════════════════════════════════════
 * Sebagian vendor CMT (sub-kontraktor jahit) TIDAK memakai sistem — tidak mau
 * atau tidak bisa login portal. Akibatnya seluruh rantai CMT berhenti di ERP,
 * padahal **tagihan CMT dihitung dari progress produksi**. Data yang tidak
 * masuk = uang yang tidak bisa ditagih/diverifikasi.
 *
 * Layar ini memberi staf DA jalan resmi untuk MENGISI 11 modul Portal Vendor
 * CMT **atas nama** vendor — tanpa akun bayangan, tanpa menyamar, dan tanpa
 * menghilangkan jejak siapa yang mengetik.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * KEPUTUSAN OWNER (2026-08-08)
 * ═══════════════════════════════════════════════════════════════════════════
 *  1a  SEMUA 11 modul di-mirror (bukan sebagian) — kalau satu modul hilang,
 *      staf tetap mentok dan harus mengejar vendor lewat WhatsApp lagi.
 *  2b  Hanya admin · superadmin · admin_produksi · supervisor_produksi · ppic.
 *  3a  Jejak "diinput staf DA" TERCATAT + KELIHATAN (badge di monitoring/invoice).
 *  4a  Dropdown = SEMUA vendor aktif di master CMT (tanpa flag tambahan).
 *  5a  Vendor yang punya akun portal aktif TETAP BOLEH diisi, tapi diberi
 *      peringatan dobel input + tanggal login terakhirnya.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * CARA KERJA (kenapa 11 komponen vendor TIDAK disalin ulang)
 * ═══════════════════════════════════════════════════════════════════════════
 * Komponen `engine/Vendor*.jsx` dipakai ULANG APA ADANYA. Konteks "sedang
 * mewakili vendor X" dikirim lewat satu header (`setCmtOverrideVendor`) dan
 * scoping-nya dikerjakan backend (`backend/core/cmt_override.py`). Jadi layar
 * ini MUSTAHIL menampilkan angka berbeda dari yang vendor lihat — kodenya sama.
 * Header di-SET saat vendor dipilih dan DI-CLEAR saat keluar/unmount, supaya
 * layar staf yang lain tidak pernah ikut ter-scope tanpa sadar.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle, ArrowLeft, BarChart2, Bell, BookOpen, Briefcase, Building2,
  ClipboardCheck, ClipboardList, Hash, Info, Package, RefreshCw, Search, Send,
  ShieldCheck, TrendingUp, UserCog, Users, Loader2, CheckCircle2,
} from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { GlassCard } from '@/components/ui/glass';
import { EmptyState, Notice, StatTile } from './moduleAtoms';
import { apiGet, setCmtOverrideVendor, clearCmtOverrideVendor } from '../../lib/api';

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

// 11 modul — urutan & label PERSIS Portal Vendor CMT (VendorPortalApp.jsx),
// supaya staf yang pernah memandu vendor lewat telepon tidak perlu belajar ulang.
const MODULES = [
  { id: 'dashboard', label: 'Ringkasan', icon: BarChart2, Comp: VendorDashboard },
  { id: 'receiving', label: 'Penerimaan Material', icon: Package, Comp: VendorReceiving },
  { id: 'inspeksi', label: 'Inspeksi Material', icon: ClipboardCheck, Comp: VendorMaterialInspection },
  { id: 'material-requests', label: 'Permintaan Material', icon: ClipboardList, Comp: VendorMaterialRequests },
  { id: 'production-jobs', label: 'Pekerjaan Produksi', icon: Briefcase, Comp: VendorProductionJobs },
  { id: 'production-guide', label: 'Panduan Produksi', icon: BookOpen, Comp: VendorProductionGuide },
  { id: 'progress', label: 'Progress Produksi', icon: TrendingUp, Comp: VendorProgress },
  { id: 'buyer-shipments', label: 'Kirim ke Buyer', icon: Send, Comp: VendorBuyerShipments },
  { id: 'serial-tracking', label: 'Serial Tracking', icon: Hash, Comp: VendorSerialTracking },
  { id: 'variance-report', label: 'Laporan Variance', icon: AlertTriangle, Comp: VendorVarianceReport },
  { id: 'reminders', label: 'Inbox Reminder', icon: Bell, Comp: VendorReminderInbox },
];

const fmtDateTime = (v) => {
  if (!v) return '—';
  try {
    return new Date(v).toLocaleString('id-ID', {
      day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  } catch { return String(v); }
};

// ═════════════════════════════════════════════════════════════════════════════
function AccessDenied({ role }) {
  return (
    <div data-testid="cmt-override-denied">
      <GlassCard className="p-4 text-center">
        <ShieldCheck className="mx-auto mb-3 h-10 w-10 text-muted-foreground" />
        <h2 className="text-lg font-semibold text-foreground">Tidak berwenang</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Mengisi data atas nama vendor CMT berpengaruh langsung ke <b>tagihan CMT</b>,
          jadi hanya dibuka untuk staf yang memang memegang CMT harian.
        </p>
        <p className="mt-3 text-xs text-muted-foreground">
          Role Anda: <span className="tabular-nums font-semibold text-foreground">{role || '—'}</span>
          <br />Role yang diizinkan: <span className="tabular-nums">{ALLOWED_ROLES.join(' · ')}</span>
        </p>
      </GlassCard>
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════════
function VendorCard({ v, onPick }) {
  const pending = Number(v.pending_actions || 0);
  return (
    <button
      type="button"
      onClick={() => onPick(v)}
      data-testid={`cmt-override-vendor-${v.id}`}
      className="group flex w-full flex-col gap-3 rounded-xl border border-border bg-card p-4 text-left shadow-sm transition-all hover:border-[hsl(var(--primary)/0.35)] hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))]"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-semibold text-foreground">{v.name}</p>
          <p className="mt-0.5 tabular-nums text-xs text-muted-foreground">{v.code || '—'}</p>
        </div>
        <div className="flex flex-col items-end gap-1">
          {pending > 0 && (
            <span className="inline-flex items-center rounded-full bg-[hsl(var(--primary)/0.15)] px-2 py-0.5 text-[11px] font-bold text-[hsl(var(--primary))]">
              {pending} perlu diisi
            </span>
          )}
          {!v.is_active && (
            <span className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
              non-aktif
            </span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-lg bg-muted/50 px-2 py-1.5">
          <p className="text-muted-foreground">Kiriman masuk</p>
          <p className="font-bold text-foreground">{v.incoming_shipments || 0}</p>
        </div>
        <div className="rounded-lg bg-muted/50 px-2 py-1.5">
          <p className="text-muted-foreground">Belum inspeksi</p>
          <p className="font-bold text-foreground">{v.uninspected_shipments || 0}</p>
        </div>
        <div className="rounded-lg bg-muted/50 px-2 py-1.5">
          <p className="text-muted-foreground">Job jalan</p>
          <p className="font-bold text-foreground">{v.active_jobs || 0}</p>
        </div>
        <div className="rounded-lg bg-muted/50 px-2 py-1.5">
          <p className="text-muted-foreground">Reminder</p>
          <p className="font-bold text-foreground">{v.open_reminders || 0}</p>
        </div>
      </div>

      {v.has_active_portal_account ? (
        <Notice tone="warning" icon={AlertTriangle} testId={`cmt-override-warn-${v.id}`}
          className="px-2.5 py-2 text-[11px] leading-snug">
          Punya akun portal aktif — terakhir login <b>{fmtDateTime(v.last_login_at)}</b>.
          Hati-hati dobel input.
        </Notice>
      ) : (
        <Notice tone="success" icon={CheckCircle2} className="px-2.5 py-2 text-[11px] font-medium">
          Tanpa akun portal — memang harus diisi staf
        </Notice>
      )}

      <span className="mt-auto text-xs font-semibold text-[hsl(var(--primary))] group-hover:underline">
        Isi atas nama vendor ini →
      </span>
    </button>
  );
}

// ═════════════════════════════════════════════════════════════════════════════
function AuditPanel({ vendorName }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await apiGet('/cmt-override/audit?limit=100'));
    } catch (e) {
      toast.error(e.message || 'Gagal memuat jejak audit');
      setData({ entries: [], totals: { staff: 0, vendor: 0 } });
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const totals = data?.totals || { staff: 0, vendor: 0 };
  const entries = data?.entries || [];

  return (
    <div className="space-y-4" data-testid="cmt-override-audit-panel">
      <GlassCard className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="font-semibold text-foreground">Jejak input — {vendorName}</h3>
            <p className="mt-1 max-w-2xl text-xs text-muted-foreground">
              Tagihan CMT dihitung dari angka di dokumen-dokumen ini. Panel ini memisahkan
              mana yang <b>diketik staf DA</b> dan mana yang <b>diisi vendor sendiri</b>,
              supaya kalau nanti ada selisih tagihan sumbernya bisa ditelusuri.
            </p>
          </div>
          <Button size="icon" variant="outline" onClick={load} title="Muat ulang" aria-label="Muat ulang"
            data-testid="cmt-override-audit-refresh">
            <RefreshCw className="h-4 w-4" />
          </Button>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
          <StatTile label="Diinput staf DA" accent={Number(totals.staff) ? 'warning' : 'muted'}
            value={<span data-testid="cmt-override-audit-staff">{totals.staff}</span>} />
          <StatTile label="Diisi vendor sendiri" accent={Number(totals.vendor) ? 'success' : 'muted'}
            value={<span data-testid="cmt-override-audit-vendor">{totals.vendor}</span>} />
          <StatTile label="Total dokumen" value={(totals.staff || 0) + (totals.vendor || 0)} />
        </div>
      </GlassCard>

      <GlassCard className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted/60">
              <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th className="px-4 py-2.5">Modul</th>
                <th className="px-4 py-2.5">Dokumen</th>
                <th className="px-4 py-2.5">Diinput oleh</th>
                <th className="px-4 py-2.5">Role</th>
                <th className="px-4 py-2.5">Waktu</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {loading && (
                <tr><td colSpan={5} className="py-4 text-center text-muted-foreground">
                  <Loader2 className="mx-auto h-5 w-5 animate-spin" />
                </td></tr>
              )}
              {!loading && entries.length === 0 && (
                <tr><td colSpan={5} data-testid="cmt-override-audit-empty">
                  <EmptyState icon={UserCog} title="Belum ada input staf DA untuk vendor ini"
                    description="Dokumen yang Anda simpan atas nama vendor akan tercatat di sini." />
                </td></tr>
              )}
              {!loading && entries.map((e, i) => (
                <tr key={`${e.collection}-${e.doc_id}-${i}`} className="hover:bg-muted/40">
                  <td className="px-4 py-2.5 font-medium text-foreground">{e.module}</td>
                  <td className="px-4 py-2.5 tabular-nums text-xs text-[hsl(var(--primary))]">{e.reference || '—'}</td>
                  <td className="px-4 py-2.5">
                    <span className="inline-flex items-center gap-1.5">
                      <UserCog className="h-3.5 w-3.5 text-[hsl(var(--warning))]" />
                      <span className="font-medium text-foreground">{e.entered_by || '—'}</span>
                    </span>
                  </td>
                  <td className="px-4 py-2.5 tabular-nums text-xs text-muted-foreground">{e.entered_by_role || '—'}</td>
                  <td className="px-4 py-2.5 text-xs text-muted-foreground">{fmtDateTime(e.entered_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassCard>
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════════
export default function CMTOverridePortalModule({ user, token }) {
  const role = (user?.role || '').toLowerCase();
  const allowed = ALLOWED_ROLES.includes(role);

  const [vendors, setVendors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [search, setSearch] = useState('');
  const [showInactive, setShowInactive] = useState(false);
  const [selected, setSelected] = useState(null);
  const [activeModule, setActiveModule] = useState('dashboard');
  const [warnOpen, setWarnOpen] = useState(true);
  const mounted = useRef(true);

  const loadVendors = useCallback(async (inactive) => {
    setLoading(true); setErr('');
    // Daftar vendor dibaca TANPA konteks override (kita belum memilih siapa pun).
    clearCmtOverrideVendor();
    try {
      const d = await apiGet(`/cmt-override/vendors${inactive ? '?include_inactive=true' : ''}`);
      if (!mounted.current) return;
      setVendors(Array.isArray(d?.vendors) ? d.vendors : []);
    } catch (e) {
      if (!mounted.current) return;
      setErr(e.message || 'Gagal memuat daftar vendor CMT');
      setVendors([]);
    } finally { if (mounted.current) setLoading(false); }
  }, []);

  useEffect(() => {
    mounted.current = true;
    if (allowed) loadVendors(showInactive);
    // Jaring pengaman MUTLAK: begitu layar ini ditinggalkan, konteks override
    // WAJIB hilang — kalau tidak, layar staf berikutnya bisa diam-diam ter-scope
    // ke satu vendor dan menampilkan angka yang salah tanpa ada yang sadar.
    return () => { mounted.current = false; clearCmtOverrideVendor(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allowed, showInactive]);

  // Dipanggil dari klik: header di-set SINKRON sebelum state berubah, karena
  // efek komponen ANAK berjalan LEBIH DULU daripada efek komponen induk di React
  // — kalau menunggu useEffect, permintaan pertama tiap modul akan terkirim
  // tanpa header dan staf melihat data seluruh vendor sekejap.
  //
  // `moduleId` opsional: dari **Rekap Harian**, chip "belum diisi" membawa modul
  // tujuannya, jadi satu klik langsung membuka tab yang tepat. Tanpa ini staf
  // harus mengingat kolom mana yang merah lalu menebak tabnya — dan rekapnya
  // berhenti jadi alat kerja, cuma jadi laporan.
  const pickVendor = (v, moduleId = null) => {
    setCmtOverrideVendor(v.id);
    setSelected(v);
    setActiveModule(MODULES.some(m => m.id === moduleId) ? moduleId : 'dashboard');
    setWarnOpen(true);
  };

  // Dari Rekap Harian: barisnya dikirim UTUH, tapi kartu vendor yang sudah dimuat
  // lebih lengkap (daftar akun untuk peringatan dobel input) ⇒ pakai itu bila ada.
  const pickFromRecap = (row, moduleId) => {
    if (!row?.vendor_id) return;
    const known = vendors.find(v => v.id === row.vendor_id);
    pickVendor(known || {
      id: row.vendor_id,
      name: row.vendor_name,
      code: row.vendor_code,
      has_active_portal_account: row.has_active_portal_account,
      last_login_at: row.last_login_at,
      accounts: [],
    }, moduleId);
  };

  const backToPicker = () => {
    clearCmtOverrideVendor();
    setSelected(null);
    loadVendors(showInactive);
  };

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const rows = q
      ? vendors.filter(v => `${v.name} ${v.code} ${v.contact_name}`.toLowerCase().includes(q))
      : vendors.slice();
    rows.sort((a, b) => (Number(b.pending_actions || 0) - Number(a.pending_actions || 0))
      || String(a.name).localeCompare(String(b.name)));
    return rows;
  }, [vendors, search]);

  // `user` sintetis untuk komponen vendor: mereka hanya memakai `user.vendor_id`
  // (payload) dan `user.name` (judul). Sumber kebenaran tetap backend.
  const vendorUser = useMemo(() => (selected ? {
    id: user?.id,
    name: selected.name,
    role: 'cmt_vendor',
    vendor_id: selected.id,
    cmt_vendor_id: selected.id,
  } : null), [selected, user?.id]);

  if (!allowed) return <AccessDenied role={user?.role} />;

  // ── LAYAR 1: pilih vendor ────────────────────────────────────────────────
  if (!selected) {
    const withAccount = vendors.filter(v => v.has_active_portal_account).length;
    return (
      <div className="space-y-4" data-testid="cmt-override-picker">
        <GlassCard className="p-4">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="flex items-start gap-3">
              <div className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-xl bg-[hsl(var(--primary))]">
                <UserCog className="h-6 w-6 text-white" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-foreground">Input Vendor CMT</h1>
                <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
                  Untuk vendor CMT yang <b>tidak memakai sistem</b>. Anda membuka portal
                  vendor mereka dan mengisinya <b>atas nama vendor</b> — 11 modul, sama
                  persis dengan yang vendor lihat. Setiap dokumen yang Anda simpan
                  menyimpan nama Anda dan muncul dengan badge{' '}
                  <span className="whitespace-nowrap rounded-full border border-[hsl(var(--warning)/0.35)] bg-[hsl(var(--warning)/0.15)] px-1.5 py-0.5 text-[11px] font-semibold text-[hsl(var(--warning))]">
                    diinput staf DA
                  </span>{' '}
                  di layar monitoring &amp; invoice.
                </p>
              </div>
            </div>
            <Button variant="outline" size="icon" onClick={() => loadVendors(showInactive)}
              title="Muat ulang" aria-label="Muat ulang" data-testid="cmt-override-refresh">
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            </Button>
          </div>
        </GlassCard>

        {/* ══ REKAP — blok PERTAMA (keputusan owner 4a) ══════════════════════
            Staf membuka pintu ini tiap pagi. Yang pertama dia butuh bukan daftar
            vendor, tapi jawaban "siapa yang belum diisi hari ini" — lalu klik
            langsung dari situ. Kartu pilih vendor turun ke bawah sebagai
            pelengkap (mencari vendor tertentu di luar urusan harian).

            FASE 4: panelnya kini punya DUA tab — **Harian** (tetap yang pertama
            tampil) dan **Mingguan** ("siapa yang sering bolong 7 hari terakhir").
            Panel yang memegang tanggal, supaya klik kotak hari di tab Mingguan
            bisa membuka tab Harian pada tanggal itu. */}
        <CMTOverrideRecapPanel onOpenVendor={pickFromRecap} />

        <GlassCard className="p-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2">
              <Building2 className="h-4 w-4 text-muted-foreground" />
              <h2 className="text-sm font-bold text-foreground">Semua vendor CMT</h2>
            </div>
            <div className="relative min-w-[240px] flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Cari nama / kode / kontak vendor…"
                className="pl-9"
                data-testid="cmt-override-search"
              />
            </div>
            <label className="flex cursor-pointer select-none items-center gap-2 text-sm text-muted-foreground">
              <input
                type="checkbox"
                checked={showInactive}
                onChange={e => setShowInactive(e.target.checked)}
                className="h-4 w-4 rounded border-border"
                data-testid="cmt-override-show-inactive"
              />
              Tampilkan vendor non-aktif
            </label>
            <span className="inline-flex items-center gap-1.5 rounded-lg bg-muted/60 px-2.5 py-1.5 text-xs text-muted-foreground">
              <Building2 className="h-3.5 w-3.5" /> {vendors.length} vendor
            </span>
            {withAccount > 0 && (
              <span className="inline-flex items-center gap-1.5 rounded-lg border border-[hsl(var(--warning)/0.35)] bg-[hsl(var(--warning)/0.1)] px-2.5 py-1.5 text-xs font-medium text-[hsl(var(--warning))]">
                <AlertTriangle className="h-3.5 w-3.5" /> {withAccount} punya akun portal aktif
              </span>
            )}
          </div>
        </GlassCard>

        {err && (
          <Notice tone="danger" icon={AlertTriangle} testId="cmt-override-error">{err}</Notice>
        )}

        {loading ? (
          <GlassCard className="flex items-center justify-center p-4">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </GlassCard>
        ) : filtered.length === 0 ? (
          <GlassCard data-testid="cmt-override-empty">
            <EmptyState icon={Users} title="Tidak ada vendor CMT yang cocok"
              description={<>Ubah kata pencarian, atau tambahkan vendor lewat menu <b>Vendor CMT</b>.</>} />
          </GlassCard>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {filtered.map(v => <VendorCard key={v.id} v={v} onPick={pickVendor} />)}
          </div>
        )}
      </div>
    );
  }

  // ── LAYAR 2: mode isi atas nama vendor ───────────────────────────────────
  const Active = MODULES.find(m => m.id === activeModule);

  return (
    <div className="space-y-4" data-testid="cmt-override-active">
      {/* Spanduk mode override — SELALU terlihat (sticky) supaya tidak ada yang
          mengisi tanpa sadar sedang mewakili vendor. */}
      <Notice tone="warning" icon={UserCog} title="Mode isi atas nama vendor"
        className="sticky top-0 z-30 items-center shadow-sm"
        action={
          <Button size="sm" variant="outline" onClick={backToPicker}
            className="border-[hsl(var(--warning)/0.35)] bg-card text-[hsl(var(--warning))] hover:bg-[hsl(var(--warning)/0.15)]"
            data-testid="cmt-override-change-vendor">
            <ArrowLeft className="h-3.5 w-3.5" /> Ganti vendor
          </Button>
        }>
        <p className="truncate">
          <b data-testid="cmt-override-vendor-name">{selected.name}</b>
          {selected.code ? <span className="tabular-nums text-xs"> · {selected.code}</span> : null}
          <span> — diinput oleh </span>
          <b data-testid="cmt-override-staff-name">{user?.name || '—'}</b>
          <span className="tabular-nums text-xs"> ({role})</span>
        </p>
      </Notice>

      {/* Peringatan dobel input (keputusan 5a) — memberi tahu, TIDAK memblokir. */}
      {selected.has_active_portal_account && warnOpen && (
        <Notice tone="warning" icon={AlertTriangle} title="Hati-hati dobel input"
          testId="cmt-override-double-warning"
          action={
            <Button size="sm" variant="outline" onClick={() => setWarnOpen(false)}
              data-testid="cmt-override-warning-dismiss">
              Mengerti
            </Button>
          }>
          <p>
            Vendor ini <b>punya akun portal aktif</b> (terakhir login{' '}
            <b>{fmtDateTime(selected.last_login_at)}</b>). Kalau vendor juga mengisi
            sendiri, angka progress bisa terhitung dua kali — dan tagihan CMT ikut
            salah. Pastikan sudah sepakat siapa yang mengisi hari ini.
          </p>
          {Array.isArray(selected.accounts) && selected.accounts.length > 0 && (
            <ul className="mt-2 space-y-0.5 text-xs text-muted-foreground">
              {selected.accounts.map(a => (
                <li key={a.email} className="tabular-nums">
                  {a.email} — {a.is_active ? 'aktif' : 'non-aktif'} · login terakhir {fmtDateTime(a.last_login_at)}
                </li>
              ))}
            </ul>
          )}
        </Notice>
      )}

      {/* Tab 11 modul + jejak audit */}
      <GlassCard className="p-2">
        <div className="flex gap-1 overflow-x-auto pb-1">
          {MODULES.map(m => {
            const Icon = m.icon;
            const on = activeModule === m.id;
            return (
              <button
                key={m.id}
                type="button"
                onClick={() => setActiveModule(m.id)}
                data-testid={`cmt-override-tab-${m.id}`}
                className={`flex flex-shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-2 text-xs font-medium transition-colors ${
                  on ? 'bg-[hsl(var(--primary))] text-white shadow-sm' : 'text-muted-foreground hover:bg-muted'
                }`}
              >
                <Icon className="h-3.5 w-3.5" /> {m.label}
              </button>
            );
          })}
          <button
            type="button"
            onClick={() => setActiveModule('__audit')}
            data-testid="cmt-override-tab-audit"
            className={`flex flex-shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-2 text-xs font-semibold transition-colors ${
              activeModule === '__audit'
                ? 'bg-[hsl(var(--warning))] text-white shadow-sm'
                : 'text-[hsl(var(--warning))] hover:bg-[hsl(var(--warning)/0.1)]'
            }`}
          >
            <ShieldCheck className="h-3.5 w-3.5" /> Jejak audit
          </button>
        </div>
      </GlassCard>

      <GlassCard className="p-4">
        <div className="mb-3 flex items-center gap-2 border-b border-border pb-3">
          <Info className="h-4 w-4 flex-shrink-0 text-[hsl(var(--primary))]" />
          <p className="text-xs text-muted-foreground">
            {activeModule === '__audit'
              ? 'Transparansi: dokumen mana yang diketik staf DA vs diisi vendor sendiri.'
              : <>Layar ini <b>persis</b> yang dilihat vendor di portalnya. Yang Anda simpan
                  tercatat atas nama <b>{selected.name}</b> dengan jejak nama Anda.</>}
          </p>
        </div>

        {activeModule === '__audit'
          ? <AuditPanel vendorName={selected.name} />
          : Active
            ? <Active.Comp token={token} user={vendorUser} onNavigate={setActiveModule} />
            : null}
      </GlassCard>
    </div>
  );
}

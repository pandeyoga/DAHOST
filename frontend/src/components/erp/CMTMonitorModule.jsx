/**
 * CMTMonitorModule — Monitoring CMT (Fase 2): Dashboard Owner + Kejar CMT.
 *
 * READ-ONLY, sumber tunggal SSOT via /api/dewi/cmt-kejar/* (services/cmt_kejar.py).
 * - Dashboard Owner (M2): KPI potongan masuk/disetor/sisa di CMT/TELAT/ongkos jahit/komponen kurang/biaya permak.
 * - Kejar CMT (S3/M4/M5): tabel aging per PO (bucket, sisa di CMT, kali setor, target CMT vs deadline).
 */
import { useEffect, useMemo, useState, useCallback } from 'react';
import {
  Siren, RefreshCw, LayoutDashboard, ListChecks, AlertTriangle, Truck, PackageCheck,
  Boxes, Wallet, Wrench, Clock, Loader2, CalendarClock,
  PackageSearch, ScanLine, ShieldCheck, Copy, ShoppingCart, Gauge, Factory, TrendingUp, GitCompare, CheckCircle2,
  Trash2, XCircle, ChevronDown, Warehouse,
} from 'lucide-react';
import { toast } from 'sonner';
import { apiGet } from '../../lib/api';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import FilterChips from '@/components/ui/filter-chips';
import { EmptyState, Notice, StatTile } from './moduleAtoms';

const fmt = (n) => Number(n || 0).toLocaleString('id-ID');
const fmtRp = (n) => 'Rp' + Number(n || 0).toLocaleString('id-ID');
const fmtDate = (v) => {
  if (!v) return '—';
  try {
    const d = new Date(v);
    if (isNaN(d.getTime())) return String(v).slice(0, 10);
    return d.toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' });
  } catch { return String(v).slice(0, 10); }
};

const BUCKET_META = {
  telat:         { label: 'TELAT', cls: 'bg-[hsl(var(--destructive)/0.15)] text-[hsl(var(--destructive))]', dot: 'bg-[hsl(var(--destructive))]' },
  jatuh_tempo:   { label: 'Jatuh Tempo', cls: 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]', dot: 'bg-[hsl(var(--warning))]' },
  mendekati:     { label: 'Mendekati', cls: 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]', dot: 'bg-[hsl(var(--warning))]' },
  on_track:      { label: 'On Track', cls: 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]', dot: 'bg-[hsl(var(--success))]' },
  aman:          { label: 'Aman (sudah balik)', cls: 'bg-slate-100 text-slate-600', dot: 'bg-slate-400' },
  tanpa_deadline:{ label: 'Tanpa Deadline', cls: 'bg-slate-100 text-slate-500', dot: 'bg-slate-300' },
};

const CAP_STATUS = {
  over:        { label: 'Kelebihan Beban', cls: 'bg-[hsl(var(--destructive)/0.15)] text-[hsl(var(--destructive))]', bar: 'bg-[hsl(var(--destructive))]' },
  near:        { label: 'Hampir Penuh', cls: 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]', bar: 'bg-[hsl(var(--warning))]' },
  ok:          { label: 'Aman', cls: 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]', bar: 'bg-[hsl(var(--success))]' },
  no_capacity: { label: 'Kapasitas Belum Diisi', cls: 'bg-slate-100 text-slate-500', bar: 'bg-slate-300' },
};

const BUCKET_FILTERS = [
  { key: '', label: 'Semua' },
  { key: 'telat', label: 'TELAT' },
  { key: 'jatuh_tempo', label: 'Jatuh Tempo' },
  { key: 'mendekati', label: 'Mendekati' },
  { key: 'on_track', label: 'On Track' },
  { key: 'aman', label: 'Aman' },
];

// PANDUAN_UI G5: kartu angka = StatTile (ikon tidak dipakai; nada lama dipetakan ke token).
const KPI_ACCENT = { default: 'default', red: 'danger', amber: 'warning', emerald: 'success', blue: 'primary', violet: 'primary' };
function Kpi({ label, value, sub, tone = 'default', testid }) {
  return <StatTile label={label} value={value} sub={sub} accent={KPI_ACCENT[tone] || 'default'} testId={testid} />;
}

function BucketBadge({ bucket }) {
  const m = BUCKET_META[bucket] || { label: bucket, cls: 'bg-muted text-foreground/70' };
  return <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${m.cls}`}>{m.label}</span>;
}

export default function CMTMonitorModule() {
  const [tab, setTab] = useState('dashboard');
  const [dash, setDash] = useState(null);
  const [kejar, setKejar] = useState(null);
  const [intake, setIntake] = useState(null);
  const [seri, setSeri] = useState(null);
  const [belanja, setBelanja] = useState(null);
  const [kapasitas, setKapasitas] = useState(null);
  const [recon, setRecon] = useState(null);
  const [bucket, setBucket] = useState('');
  // ── SUDUT PANDANG PO (keluhan pemilik 2026-06, INV-F28) ───────────────────
  // Dulu kartu selalu menghitung PO `Completed` juga, jadi angka "berjalan" tidak
  // pernah bisa dilihat. Sekarang pemakai memilih: PO Berjalan (default) atau
  // Semua PO — dan SELURUH kartu + papan ikut berubah.
  const [scope, setScope] = useState('running');
  const [openBalance, setOpenBalance] = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [d, k, ib, cs, ba, kap, rc] = await Promise.all([
        apiGet(`/dewi/cmt-kejar/dashboard?scope=${scope}`),
        apiGet(`/dewi/cmt-kejar?scope=${scope}${bucket ? `&bucket=${bucket}` : ''}`),
        apiGet('/dewi/cmt-intake/batches?scope=maklon'),
        apiGet('/dewi/cmt-intake/cek-seri?scope=maklon'),
        apiGet('/dewi/cmt-belanja/rekap-aksesoris'),
        apiGet('/dewi/cmt-belanja/kapasitas'),
        apiGet('/dewi/cmt-recon/dispatch'),
      ]);
      setDash(d);
      setKejar(k);
      setIntake(ib);
      setSeri(cs);
      setBelanja(ba);
      setKapasitas(kap);
      setRecon(rc);
    } catch (e) {
      toast.error(`Gagal memuat monitoring CMT: ${e.message || e}`);
    } finally {
      setLoading(false);
    }
  }, [bucket, scope]);

  useEffect(() => { load(); }, [load]);

  const b = dash?.buckets || {};

  return (
    <div className="space-y-4" data-testid="cmt-monitor-module">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <Siren size={26} className="text-[hsl(var(--destructive))]" /> Monitoring CMT
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Ringkasan pemilik &amp; kejar CMT — pantau setoran, sisa di CMT, keterlambatan (Target CMT = Deadline Mitra − buffer).
          </p>
        </div>
        <Button size="icon" variant="outline" onClick={load} title="Muat ulang" aria-label="Muat ulang" data-testid="btn-refresh-monitor">
          <RefreshCw size={14} />
        </Button>
      </div>

      {/* Sudut pandang PO — seluruh kartu & papan ikut berubah (INV-F28) */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-muted-foreground">Sudut pandang:</span>
        <FilterChips value={scope} onChange={setScope} testId="monitor-scope" ariaLabel="Sudut pandang PO"
          options={[
            { key: 'running', label: 'PO berjalan' },
            { key: 'all', label: 'Semua PO' },
          ]} />
        <span className="text-xs text-muted-foreground/70">
          {scope === 'running'
            ? 'PO yang sudah selesai/ditutup tidak dihitung.'
            : 'Menghitung SEMUA PO maklon, termasuk yang sudah selesai.'}
        </span>
      </div>

      {/* Tab isi modul — PANDUAN_UI G4: pil standar, state `tab` tetap */}
      <FilterChips value={tab} onChange={setTab} testId="tab-monitor" ariaLabel="Bagian monitoring CMT"
        options={[
          { key: 'dashboard', label: 'Ringkasan pemilik', icon: LayoutDashboard },
          { key: 'kejar', label: 'Kejar CMT', icon: ListChecks },
          { key: 'intake', label: 'Potongan masuk', icon: PackageSearch },
          { key: 'seri', label: 'Cek seri', icon: ScanLine, count: seri?.duplicate_count > 0 ? seri.duplicate_count : undefined },
          { key: 'belanja', label: 'Rekap aksesoris', icon: ShoppingCart },
          { key: 'kapasitas', label: 'Kapasitas CMT', icon: Gauge, count: kapasitas?.totals?.over_count > 0 ? kapasitas.totals.over_count : undefined },
          { key: 'recon', label: 'Rekonsiliasi', icon: GitCompare, count: recon?.overlap_count > 0 ? recon.overlap_count : undefined },
        ]} />

      {loading && !dash && (
        <div className="py-8 text-center text-muted-foreground"><Loader2 className="inline animate-spin mr-2" size={18} /> Memuat...</div>
      )}

      {/* ── DASHBOARD OWNER ── */}
      {tab === 'dashboard' && dash && (
        <div className="space-y-4" data-testid="monitor-dashboard-panel">
          {/* ══ 12 KARTU, URUT SESUAI ALUR PROSES (permintaan pemilik 2026-06) ══
              Order → gudang → CMT → setor → QC → permak/scrap → siap kirim →
              terkirim → biaya. Angkanya SEIMBANG (lihat baris pemeriksa di bawah). */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-3">
            <Kpi label="1. Order (Qty PO)" testid="kpi-order" value={fmt(dash.qty_ordered)}
              sub={`${fmt(dash.total_po)} PO ${dash.scope === 'all' ? '(semua)' : 'berjalan'} · ${fmt(dash.po_draft)} draft`}
              icon={ListChecks} tone="default" />
            <Kpi label="2. Belum Dikirim ke CMT" testid="kpi-belum-ke-cmt" value={fmt(dash.qty_not_sent_cmt)}
              sub={`masih di gudang · dari PO Draft: ${fmt(dash.qty_not_sent_draft)} pcs`}
              icon={Warehouse} tone="amber" />
            <Kpi label="3. Potongan ke CMT" testid="kpi-potongan-ke-cmt" value={fmt(dash.qty_sent_cmt)}
              sub={dash.qty_sent_extra
                ? `sesuai order · +${fmt(dash.qty_sent_extra)} pengganti/tambahan`
                : 'pcs sesuai order (kiriman NORMAL)'}
              icon={Truck} tone="blue" />
            <Kpi label="4. Sisa di CMT" testid="kpi-sisa-di-cmt" value={fmt(dash.qty_outstanding_cmt)}
              sub={dash.qty_short_open
                ? `belum disetor · selisih belum sampai: ${fmt(dash.qty_short_open)} pcs`
                : 'belum disetor ke DA'}
              icon={Boxes} tone="amber" />
            <Kpi label="5. Disetor dari CMT" testid="kpi-disetor" value={fmt(dash.qty_returned)}
              sub={`${fmt(dash.kali_setor)}x setor · yang benar-benar sampai`}
              icon={PackageSearch} tone="blue" />
            <Kpi label="6. Lolos QC" testid="kpi-lolos-qc" value={fmt(dash.qty_accepted)}
              sub="langsung bagus · masuk stok FG" icon={ShieldCheck} tone="emerald" />
            <Kpi label="7. Reject Belum Jelas" testid="kpi-reject-belum-jelas" value={fmt(dash.qty_reject_open)}
              sub={`dari ${fmt(dash.qty_reject)} reject · masih dipermak / belum diputuskan`}
              icon={Clock} tone="amber" />
            <Kpi label="8. Permak Berhasil" testid="kpi-permak-berhasil" value={fmt(dash.qty_repaired)}
              sub="reject jadi bagus lagi · boleh dikirim" icon={Wrench} tone="blue" />
            <Kpi label="9. Scrap / Hilang" testid="kpi-scrap" value={fmt(dash.qty_scrap)}
              sub="dibuang · permak gagal (rugi)" icon={Trash2} tone="red" />
            <Kpi label="10. Sisa Bisa Kirim" testid="kpi-sisa-bisa-kirim" value={fmt(dash.qty_shippable_buyer)}
              sub="siap dikirim ke buyer (lolos QC + permak − terkirim)"
              icon={PackageCheck} tone="emerald" />
            <Kpi label="11. Sudah Dikirim ke Buyer" testid="kpi-ke-buyer" value={fmt(dash.qty_shipped_buyer)}
              sub="sudah keluar dari gudang FG" icon={Truck} tone="emerald" />
            {/* 12 — dua biaya dalam satu kartu, tetap terpisah angkanya */}
            <GlassCard className="px-4 py-3" data-testid="kpi-biaya">
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase tracking-wider text-foreground/50 font-semibold">12. Biaya</span>
                <Wallet size={16} className="text-muted-foreground/60" />
              </div>
              <div className="mt-1">
                <div className="text-lg font-bold text-[hsl(var(--primary))]" data-testid="kpi-biaya-jahit">{fmtRp(dash.ongkos_jahit_terhitung)}</div>
                <div className="text-[11px] text-muted-foreground">ongkos jahit (dari qty lolos QC)</div>
              </div>
              <div className="mt-1.5 pt-1.5 border-t border-border">
                <div className="text-lg font-bold text-[hsl(var(--primary))]" data-testid="kpi-biaya-permak">{fmtRp(dash.biaya_permak)}</div>
                <div className="text-[11px] text-muted-foreground">biaya permak · {fmt(dash.permak_open)} permak aktif</div>
              </div>
            </GlassCard>
          </div>

          {/* ── PEMERIKSA KESEIMBANGAN — 5 identitas, klik untuk lihat PO penyebab ── */}
          <Notice tone={dash.balance?.all_ok ? 'success' : 'danger'}
            icon={dash.balance?.all_ok ? CheckCircle2 : XCircle}
            testId="monitor-balance-strip"
            title={dash.balance?.all_ok
              ? 'Semua angka seimbang — 5 identitas cocok'
              : 'Ada angka yang tidak seimbang — klik barisnya untuk lihat PO penyebab'}>
            <div className="space-y-1 mt-1">
              {(dash.balance?.checks || []).map(c => (
                <div key={c.key}>
                  <button type="button"
                    onClick={() => setOpenBalance(openBalance === c.key ? '' : c.key)}
                    disabled={c.ok}
                    data-testid={`balance-check-${c.key}`}
                    className={`w-full flex items-center gap-2 text-left text-xs px-2 py-1.5 rounded-lg border transition-colors ${
                      c.ok ? 'border-[hsl(var(--success)/0.35)] bg-card/60 cursor-default'
                           : 'border-[hsl(var(--destructive)/0.35)] bg-card hover:bg-[hsl(var(--destructive)/0.1)]'}`}>
                    <span className={c.ok ? 'text-[hsl(var(--success))]' : 'text-[hsl(var(--destructive))]'}>{c.ok ? '✓' : '✗'}</span>
                    <span className="text-foreground/90 flex-1">{c.label}</span>
                    <span className="tabular-nums text-muted-foreground">{fmt(c.left)} vs {fmt(c.right)}</span>
                    {!c.ok && (
                      <>
                        <span className="tabular-nums font-bold text-[hsl(var(--destructive))]">selisih {fmt(c.diff)}</span>
                        <ChevronDown size={13} className={`text-[hsl(var(--destructive))] transition-transform ${openBalance === c.key ? 'rotate-180' : ''}`} />
                      </>
                    )}
                  </button>
                  {!c.ok && openBalance === c.key && (
                    <GlassCard className="mt-1 ml-6 px-3 py-2 text-xs"
                      data-testid={`balance-offenders-${c.key}`}>
                      <p className="text-muted-foreground mb-1">PO yang membuat identitas ini pecah:</p>
                      <div className="flex flex-wrap gap-1.5">
                        {(c.offenders || []).length === 0
                          ? <span className="text-muted-foreground italic">tidak ada PO tertentu (selisih dari pembulatan data lama)</span>
                          : c.offenders.map(no => (
                            <span key={no} className="px-1.5 py-0.5 rounded bg-[hsl(var(--destructive)/0.15)] text-[hsl(var(--destructive))] tabular-nums text-[11px] font-semibold">{no}</span>
                          ))}
                      </div>
                      <p className="text-muted-foreground/80 mt-1.5">
                        Penyebab paling umum: dispatch ke buyer dibuat sebelum ada QC penerimaan
                        (data lama), atau penerimaan belum disetujui.
                      </p>
                    </GlassCard>
                  )}
                </div>
              ))}
            </div>
          </Notice>

          {/* Rincian kiriman anak — supaya tidak ada yang merasa angkanya "hilang" */}
          {dash.qty_sent_extra > 0 && (
            <Notice tone="info" testId="monitor-extra-breakdown">
              <strong>{fmt(dash.qty_sent_extra)} pcs</strong> kiriman di luar order (tidak ikut
              menambah "Potongan ke CMT" supaya potongan tetap sesuai order):{' '}
              {Object.entries(dash.qty_sent_extra_by_type || {})
                .map(([k, v]) => `${k === 'REPLACEMENT' ? 'Pengganti' : k === 'ADDITIONAL' ? 'Tambahan' : k} ${fmt(v)} pcs`)
                .join(' · ')}
            </Notice>
          )}

          {/* Distribusi bucket */}
          <GlassCard className="p-4">
            <h3 className="text-sm font-semibold text-foreground mb-3">
              Distribusi Status Kejar ({fmt(dash.total_po)} PO {dash.scope === 'all' ? 'semua' : 'berjalan'})
            </h3>
            <div className="flex flex-wrap gap-3 items-center">
              {Object.entries(BUCKET_META).map(([k, m]) => (
                <div key={k} className="flex items-center gap-2 text-sm">
                  <span className={`inline-block h-2.5 w-2.5 rounded-full ${m.dot}`} />
                  <span className="text-muted-foreground">{m.label}:</span>
                  <span className="font-semibold text-foreground">{fmt(b[k])}</span>
                </div>
              ))}
              {/* Dua penanda yang turun dari kartu (tetap terlihat, tidak dihapus) */}
              <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full border border-[hsl(var(--destructive)/0.35)] bg-[hsl(var(--destructive)/0.1)] text-xs font-semibold text-[hsl(var(--destructive))]"
                data-testid="chip-po-telat">
                <AlertTriangle size={12} /> PO TELAT: {fmt(b.telat)}
                <span className="font-normal text-[hsl(var(--destructive)/0.8)]">({fmt(b.jatuh_tempo)} jatuh tempo)</span>
              </span>
              <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full border border-[hsl(var(--warning)/0.35)] bg-[hsl(var(--warning)/0.1)] text-xs font-semibold text-[hsl(var(--warning))]"
                data-testid="chip-komponen-kurang">
                <AlertTriangle size={12} /> Komponen Kurang: {fmt(dash.komponen_kurang_open?.requests)}
                <span className="font-normal text-[hsl(var(--warning)/0.9)]">({fmt(dash.komponen_kurang_open?.qty)} pcs belum diterima)</span>
              </span>
            </div>
          </GlassCard>

          {/* PO Telat highlight */}
          <GlassCard className="p-4">
            <h3 className="text-sm font-semibold text-[hsl(var(--destructive))] mb-2 flex items-center gap-1.5">
              <AlertTriangle size={15} /> PO Perlu Dikejar (TELAT)
            </h3>
            {(dash.telat_pos || []).length === 0 ? (
              <p className="text-sm text-muted-foreground">Tidak ada PO telat. 👍</p>
            ) : (
              <div className="space-y-1">
                {dash.telat_pos.map((p) => (
                  <div key={p.po_id} className="flex items-center justify-between text-sm bg-card rounded-md px-3 py-2 border border-border" data-testid={`telat-po-${p.po_id}`}>
                    <div>
                      <span className="font-medium text-foreground">{p.po_number}</span>
                      <span className="text-muted-foreground"> · {p.customer_name}</span>
                    </div>
                    <div className="flex items-center gap-4 text-xs">
                      <span className="text-[hsl(var(--destructive))] font-semibold">Telat {p.overdue_days} hari</span>
                      <span className="text-muted-foreground">Sisa di CMT: <span className="font-semibold text-foreground">{fmt(p.qty_outstanding_cmt)}</span></span>
                      <span className="text-muted-foreground inline-flex items-center gap-1"><CalendarClock size={12} /> {p.target_cmt_date}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </GlassCard>
        </div>
      )}

      {/* ── KEJAR CMT ── */}
      {tab === 'kejar' && (
        <div className="space-y-3" data-testid="monitor-kejar-panel">
          <FilterChips value={bucket} onChange={setBucket} testId="filter-bucket" ariaLabel="Status kejar"
            options={BUCKET_FILTERS} />

          <div className="rounded-md border border-border overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left">PO / Mitra</th>
                  <th className="px-3 py-2 text-left">Status Kejar</th>
                  <th className="px-3 py-2 text-right">Order</th>
                  <th className="px-3 py-2 text-right">Ke CMT</th>
                  <th className="px-3 py-2 text-right">Disetor</th>
                  <th className="px-3 py-2 text-right">Sisa di CMT</th>
                  <th className="px-3 py-2 text-right">Kali Setor</th>
                  <th className="px-3 py-2 text-left">Deadline Mitra</th>
                  <th className="px-3 py-2 text-left">Target CMT</th>
                  <th className="px-3 py-2 text-right">Umur / Telat</th>
                </tr>
              </thead>
              <tbody data-testid="kejar-table-body">
                {loading ? (
                  <tr><td colSpan={10} className="px-3 py-8 text-center text-muted-foreground"><Loader2 className="inline animate-spin mr-2" size={16} /> Memuat...</td></tr>
                ) : !kejar || kejar.rows.length === 0 ? (
                  <tr><td colSpan={10}>
                    <EmptyState icon={ListChecks} title="Tidak ada PO pada penyaring ini"
                      description="Pilih status kejar lain atau Semua untuk melihat PO lainnya." />
                  </td></tr>
                ) : kejar.rows.map((r) => (
                  <tr key={r.po_id} className="border-t border-border hover:bg-muted/30" data-testid={`kejar-row-${r.po_id}`}>
                    <td className="px-3 py-2">
                      <div className="font-medium text-foreground">{r.po_number}</div>
                      <div className="text-xs text-muted-foreground">{r.customer_name}</div>
                    </td>
                    <td className="px-3 py-2"><BucketBadge bucket={r.bucket} /></td>
                    <td className="px-3 py-2 text-right tabular-nums">{fmt(r.qty_ordered)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{fmt(r.qty_sent_cmt)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-[hsl(var(--success))]">{fmt(r.qty_returned)}</td>
                    <td className={`px-3 py-2 text-right tabular-nums font-semibold ${r.qty_outstanding_cmt > 0 ? 'text-[hsl(var(--warning))]' : 'text-muted-foreground'}`}>{fmt(r.qty_outstanding_cmt)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{fmt(r.kali_setor)}x</td>
                    <td className="px-3 py-2 text-xs">{r.delivery_deadline || '—'}</td>
                    <td className="px-3 py-2 text-xs">{r.target_cmt_date || '—'}</td>
                    <td className="px-3 py-2 text-right text-xs">
                      {r.bucket === 'telat' || r.bucket === 'jatuh_tempo' ? (
                        <span className="text-[hsl(var(--destructive))] font-semibold inline-flex items-center gap-1 justify-end"><Clock size={11} /> +{r.overdue_days} hr</span>
                      ) : r.days_at_cmt != null ? (
                        <span className="text-muted-foreground">{r.days_at_cmt} hr di CMT</span>
                      ) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {kejar?.config && (
            <p className="text-xs text-muted-foreground">
              Buffer Target CMT: <strong>{kejar.config.buffer_days} hari</strong> · Ambang TELAT: <strong>H+{kejar.config.late_grace_days}</strong>
              {' '}(ubah di Administrasi Sistem → Pengaturan Sistem).
            </p>
          )}
        </div>
      )}

      {/* ── POTONGAN MASUK (batch view atas vendor_shipments) ── */}
      {tab === 'intake' && (
        <div className="space-y-3" data-testid="monitor-intake-panel">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <p className="text-sm text-muted-foreground">
              Batch potongan yang dikirim DA → CMT (SSOT <code className="text-xs">vendor_shipments</code>). Total terkirim:
              {' '}<strong className="text-foreground">{fmt(intake?.total_sent)}</strong> pcs dalam <strong className="text-foreground">{fmt(intake?.count)}</strong> batch.
            </p>
          </div>
          {loading && !intake ? (
            <div className="py-8 text-center text-muted-foreground"><Loader2 className="inline animate-spin mr-2" size={16} /> Memuat...</div>
          ) : !intake || intake.batches.length === 0 ? (
            <GlassCard>
              <EmptyState icon={PackageSearch} testId="intake-empty" title="Belum ada batch potongan masuk"
                description="Batch muncul di sini setelah potongan PO maklon dikirim ke CMT." />
            </GlassCard>
          ) : (
            <div className="space-y-3">
              {intake.batches.map((batch) => (
                <GlassCard key={batch.shipment_id} className="overflow-hidden" data-testid={`intake-batch-${batch.shipment_id}`}>
                  <div className="flex items-center justify-between flex-wrap gap-2 px-4 py-3 bg-muted/40 border-b border-border">
                    <div className="flex items-center gap-2">
                      <PackageSearch size={16} className="text-[hsl(var(--primary))]" />
                      <span className="font-semibold text-foreground">{batch.shipment_number || batch.shipment_id}</span>
                      <span className="text-xs px-2 py-0.5 rounded-full bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))]">{batch.shipment_type || 'NORMAL'}</span>
                      {batch.status && <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">{batch.status}</span>}
                    </div>
                    <div className="flex items-center gap-4 text-xs text-muted-foreground">
                      <span>{batch.po_number} · {batch.customer_name || batch.vendor_name}</span>
                      {batch.shipment_date && <span className="inline-flex items-center gap-1"><CalendarClock size={12} /> {fmtDate(batch.shipment_date)}</span>}
                    </div>
                  </div>
                  <div className="grid grid-cols-3 gap-px bg-border text-center text-xs">
                    <div className="bg-card py-2"><div className="text-muted-foreground">Dikirim</div><div className="font-bold text-[hsl(var(--primary))] text-base">{fmt(batch.total_sent)}</div></div>
                    <div className="bg-card py-2"><div className="text-muted-foreground">Diterima CMT</div><div className="font-bold text-[hsl(var(--success))] text-base">{batch.total_received == null ? '—' : fmt(batch.total_received)}</div></div>
                    <div className="bg-card py-2"><div className="text-muted-foreground">Kurang</div><div className={`font-bold text-base ${batch.total_missing ? 'text-[hsl(var(--destructive))]' : 'text-muted-foreground'}`}>{batch.total_missing == null ? '—' : fmt(batch.total_missing)}</div></div>
                  </div>
                  <table className="w-full text-sm">
                    <thead className="bg-muted/30 text-[11px] uppercase text-muted-foreground">
                      <tr>
                        <th className="px-3 py-1.5 text-left">Produk / SKU</th>
                        <th className="px-3 py-1.5 text-left">Size / Warna</th>
                        <th className="px-3 py-1.5 text-left">Seri (SN)</th>
                        <th className="px-3 py-1.5 text-right">Kirim</th>
                        <th className="px-3 py-1.5 text-right">Terima</th>
                        <th className="px-3 py-1.5 text-right">Kurang</th>
                      </tr>
                    </thead>
                    <tbody>
                      {batch.items.map((it) => (
                        <tr key={it.vsi_id} className="border-t border-border">
                          <td className="px-3 py-1.5"><span className="text-foreground">{it.product_name}</span> <span className="text-xs text-muted-foreground">{it.sku}</span></td>
                          <td className="px-3 py-1.5 text-xs text-muted-foreground">{it.size} · {it.color}</td>
                          <td className="px-3 py-1.5 tabular-nums text-xs text-[hsl(var(--warning))] font-semibold">{it.serial_number || <span className="text-muted-foreground/50">—</span>}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{fmt(it.qty_sent)}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums text-[hsl(var(--success))]">{it.received_qty == null ? '—' : fmt(it.received_qty)}</td>
                          <td className={`px-3 py-1.5 text-right tabular-nums ${it.missing_qty ? 'text-[hsl(var(--destructive))] font-semibold' : 'text-muted-foreground'}`}>{it.missing_qty == null ? '—' : fmt(it.missing_qty)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </GlassCard>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── CEK SERI (deteksi seri dobel antar baris PO) ── */}
      {tab === 'seri' && (
        <div className="space-y-3" data-testid="monitor-seri-panel">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Kpi label="Total Seri Unik" value={fmt(seri?.total_serials)} sub="di baris PO maklon" icon={ScanLine} tone="blue" />
            <Kpi label="Baris Ber-Seri" value={fmt(seri?.total_items_with_serial)} sub="po_items dgn SN" icon={ListChecks} />
            <Kpi label="Seri DOBEL" value={fmt(seri?.duplicate_count)} sub="perlu diperiksa" icon={Copy} tone={seri?.duplicate_count ? 'red' : 'emerald'} />
            <Kpi label="Baris Terdampak" value={fmt(seri?.duplicate_item_count)} sub="baris pakai seri dobel" icon={AlertTriangle} tone={seri?.duplicate_item_count ? 'amber' : 'emerald'} />
          </div>

          <Notice tone="info" icon={ShieldCheck}>
            Sumber seri = <code>po_items.serial_number</code> (diinput saat BUAT ORDER). Deteksi ini <strong>read-only</strong> — tidak mengubah data. Seri yang mewaris ke shipment/job/pengiriman <strong>bukan</strong> dianggap dobel.
          </Notice>

          {loading && !seri ? (
            <div className="py-8 text-center text-muted-foreground"><Loader2 className="inline animate-spin mr-2" size={16} /> Memuat...</div>
          ) : (seri?.duplicates || []).length === 0 ? (
            <GlassCard>
              <EmptyState icon={ShieldCheck} testId="seri-clean" title="Tidak ada seri dobel"
                description="Semua nomor seri unik antar baris PO." />
            </GlassCard>
          ) : (
            <div className="space-y-3">
              {seri.duplicates.map((d) => (
                <GlassCard key={d.serial} className="overflow-hidden" data-testid={`seri-dup-${d.serial}`}>
                  <div className="flex items-center justify-between flex-wrap gap-2 px-4 py-2.5 bg-[hsl(var(--destructive)/0.6)] border-b border-[hsl(var(--destructive)/0.35)]">
                    <div className="flex items-center gap-2">
                      <Copy size={15} className="text-[hsl(var(--destructive))]" />
                      <span className="tabular-nums font-bold text-[hsl(var(--destructive))]">{d.serial}</span>
                      <span className="text-xs px-2 py-0.5 rounded-full bg-[hsl(var(--destructive))] text-white font-medium">{d.count}× dipakai</span>
                      {d.has_case_variant && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]" title={`Variasi penulisan: ${d.raw_variants.join(' | ')}`}>beda kapital/spasi</span>
                      )}
                    </div>
                  </div>
                  <table className="w-full text-sm">
                    <thead className="bg-muted/30 text-[11px] uppercase text-muted-foreground">
                      <tr>
                        <th className="px-3 py-1.5 text-left">PO / Mitra</th>
                        <th className="px-3 py-1.5 text-left">Seri (ditulis)</th>
                        <th className="px-3 py-1.5 text-left">Produk / SKU</th>
                        <th className="px-3 py-1.5 text-left">Size / Warna</th>
                        <th className="px-3 py-1.5 text-right">Qty</th>
                        <th className="px-3 py-1.5 text-left">Status PO</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.usages.map((u) => (
                        <tr key={u.po_item_id} className="border-t border-[hsl(var(--destructive)/0.35)]" data-testid={`seri-usage-${u.po_item_id}`}>
                          <td className="px-3 py-1.5"><span className="font-medium text-foreground">{u.po_number}</span> <span className="text-xs text-muted-foreground">{u.customer_name}</span></td>
                          <td className="px-3 py-1.5 tabular-nums text-xs text-[hsl(var(--destructive))]">{u.serial_raw}</td>
                          <td className="px-3 py-1.5"><span className="text-foreground">{u.product_name}</span> <span className="text-xs text-muted-foreground">{u.sku}</span></td>
                          <td className="px-3 py-1.5 text-xs text-muted-foreground">{u.size} · {u.color}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{fmt(u.qty)}</td>
                          <td className="px-3 py-1.5 text-xs text-muted-foreground">{u.po_status}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </GlassCard>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── REKAP AKSESORIS (Belanja) ── */}
      {tab === 'belanja' && (
        <div className="space-y-3" data-testid="monitor-belanja-panel">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Kpi label="Total Kebutuhan" value={fmt(belanja?.totals?.accessory_qty)} sub="pcs aksesoris" icon={ShoppingCart} tone="violet" />
            <Kpi label="Jenis Aksesoris" value={fmt(belanja?.totals?.distinct_accessories)} sub="item berbeda" icon={Boxes} tone="blue" />
            <Kpi label="Dari PO (eksplisit)" value={fmt(belanja?.totals?.from_po_accessory)} sub="po_accessories" icon={PackageCheck} tone="emerald" />
            <Kpi label="Dari BOM (turunan)" value={fmt(belanja?.totals?.from_bom)} sub="qty/pcs × order" icon={Factory} tone="amber" />
          </div>
          <Notice tone="info" icon={ShieldCheck}>
            Kebutuhan aksesoris <strong>read-only</strong> = gabungan <code>po_accessories</code> (yang diisi manual di PO) + turunan BOM aktif (<code>qty_per_pcs × qty order</code>). Untuk {fmt(belanja?.po_count)} PO maklon aktif.
          </Notice>
          {loading && !belanja ? (
            <div className="py-8 text-center text-muted-foreground"><Loader2 className="inline animate-spin mr-2" size={16} /> Memuat...</div>
          ) : (belanja?.accessories || []).length === 0 ? (
            <GlassCard>
              <EmptyState icon={ShoppingCart} testId="belanja-empty" title="Belum ada kebutuhan aksesoris"
                description="Isi aksesoris di PO maklon atau aktifkan BOM produknya supaya kebutuhan terhitung." />
            </GlassCard>
          ) : (
            <>
              <div className="rounded-md border border-border overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-muted/50 text-xs uppercase text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 text-left">Aksesoris</th>
                      <th className="px-3 py-2 text-left">Satuan</th>
                      <th className="px-3 py-2 text-right">Dari PO</th>
                      <th className="px-3 py-2 text-right">Dari BOM</th>
                      <th className="px-3 py-2 text-right">Total Kebutuhan</th>
                      <th className="px-3 py-2 text-left">Dipakai di PO</th>
                    </tr>
                  </thead>
                  <tbody data-testid="belanja-table-body">
                    {belanja.accessories.map((a) => (
                      <tr key={a.name} className="border-t border-border hover:bg-muted/30" data-testid={`belanja-row-${a.name}`}>
                        <td className="px-3 py-2">
                          <span className="font-medium text-foreground">{a.name}</span>
                          {a.code && <span className="text-xs text-muted-foreground ml-1 tabular-nums">{a.code}</span>}
                        </td>
                        <td className="px-3 py-2 text-xs text-muted-foreground">{a.unit}</td>
                        <td className="px-3 py-2 text-right tabular-nums text-[hsl(var(--success))]">{fmt(a.sources?.po_accessory)}</td>
                        <td className="px-3 py-2 text-right tabular-nums text-[hsl(var(--warning))]">{fmt(a.sources?.bom)}</td>
                        <td className="px-3 py-2 text-right tabular-nums font-bold text-[hsl(var(--primary))]">{fmt(a.total_qty)}</td>
                        <td className="px-3 py-2 text-xs text-muted-foreground">{(a.by_po || []).map(p => p.po_number).join(', ')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {(belanja?.bom_materials || []).some(m => !m.is_accessory) && (
                <details className="rounded-md border border-border overflow-hidden">
                  <summary className="px-3 py-2 text-xs font-semibold text-muted-foreground cursor-pointer bg-muted/30">Bahan lain dari BOM (non-aksesoris, mis. kain) — referensi</summary>
                  <table className="w-full text-sm">
                    <tbody>
                      {belanja.bom_materials.filter(m => !m.is_accessory).map((m) => (
                        <tr key={m.name} className="border-t border-border">
                          <td className="px-3 py-1.5 text-foreground">{m.name} <span className="text-xs text-muted-foreground">({m.category || '—'})</span></td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{fmt(m.total_qty)} {m.unit}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </details>
              )}
            </>
          )}
        </div>
      )}

      {/* ── KAPASITAS CMT ── */}
      {tab === 'kapasitas' && (
        <div className="space-y-3" data-testid="monitor-kapasitas-panel">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Kpi label="Total Kapasitas" value={fmt(kapasitas?.totals?.capacity_pcs)} sub="pcs (semua CMT)" icon={Gauge} tone="blue" />
            <Kpi label="Beban Sekarang" value={fmt(kapasitas?.totals?.load_pcs)} sub="sisa di CMT" icon={Boxes} tone="amber" />
            <Kpi label="Sisa Kapasitas" value={fmt(kapasitas?.totals?.available_pcs)} sub={kapasitas?.totals?.utilization_pct != null ? `utilisasi ${kapasitas.totals.utilization_pct}%` : 'kapasitas belum diisi'} icon={TrendingUp} tone="emerald" />
            <Kpi label="CMT Kelebihan Beban" value={fmt(kapasitas?.totals?.over_count)} sub={`${fmt(kapasitas?.totals?.no_capacity_count)} belum set kapasitas`} icon={AlertTriangle} tone={kapasitas?.totals?.over_count ? 'red' : 'emerald'} />
          </div>
          {loading && !kapasitas ? (
            <div className="py-8 text-center text-muted-foreground"><Loader2 className="inline animate-spin mr-2" size={16} /> Memuat...</div>
          ) : (kapasitas?.vendors || []).length === 0 ? (
            <GlassCard>
              <EmptyState icon={Gauge} testId="kapasitas-empty" title="Belum ada vendor CMT"
                description="Tambahkan vendor CMT di Master Data supaya kapasitasnya bisa dipantau." />
            </GlassCard>
          ) : (
            <div className="rounded-md border border-border overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-muted/50 text-xs uppercase text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 text-left">Vendor CMT</th>
                    <th className="px-3 py-2 text-right">Kapasitas</th>
                    <th className="px-3 py-2 text-right">Beban</th>
                    <th className="px-3 py-2 text-right">Sisa</th>
                    <th className="px-3 py-2 text-left w-40">Utilisasi</th>
                    <th className="px-3 py-2 text-right">PO Aktif</th>
                    <th className="px-3 py-2 text-left">Status</th>
                  </tr>
                </thead>
                <tbody data-testid="kapasitas-table-body">
                  {kapasitas.vendors.map((v) => {
                    const meta = CAP_STATUS[v.status] || CAP_STATUS.ok;
                    const pct = v.utilization_pct;
                    return (
                      <tr key={v.vendor_id} className="border-t border-border hover:bg-muted/30" data-testid={`kapasitas-row-${v.vendor_id}`}>
                        <td className="px-3 py-2">
                          <span className="font-medium text-foreground">{v.name}</span>
                          {v.code && <span className="text-xs text-muted-foreground ml-1 tabular-nums">{v.code}</span>}
                          {v.capacity_note && <div className="text-[11px] text-muted-foreground/70">{v.capacity_note}</div>}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">{v.capacity_pcs > 0 ? fmt(v.capacity_pcs) : <span className="text-muted-foreground/50">—</span>}</td>
                        <td className="px-3 py-2 text-right tabular-nums text-[hsl(var(--warning))]">{fmt(v.current_load_pcs)}</td>
                        <td className={`px-3 py-2 text-right tabular-nums ${v.available_pcs != null && v.available_pcs < 0 ? 'text-[hsl(var(--destructive))] font-semibold' : 'text-[hsl(var(--success))]'}`}>{v.available_pcs == null ? '—' : fmt(v.available_pcs)}</td>
                        <td className="px-3 py-2">
                          {pct == null ? <span className="text-xs text-muted-foreground">—</span> : (
                            <div className="flex items-center gap-2">
                              <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
                                <div className={`h-full ${meta.bar}`} style={{ width: `${Math.min(pct, 100)}%` }} />
                              </div>
                              <span className={`text-xs tabular-nums ${pct > 100 ? 'text-[hsl(var(--destructive))] font-bold' : 'text-muted-foreground'}`}>{pct}%</span>
                            </div>
                          )}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">{fmt(v.active_po_count)}</td>
                        <td className="px-3 py-2"><span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${meta.cls}`}>{meta.label}</span></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <p className="text-xs text-muted-foreground">Kapasitas diisi di <strong>Master Data → Vendor CMT (vendor-admin)</strong>. Beban = sisa di CMT (dikirim − disetor) dari PO maklon aktif.</p>
        </div>
      )}

      {/* ── REKONSILIASI DISPATCH (Fase 5) ── */}
      {tab === 'recon' && (
        <div className="space-y-3" data-testid="monitor-recon-panel">
          {loading && !recon ? (
            <div className="py-8 text-center text-muted-foreground"><Loader2 className="inline animate-spin mr-2" size={16} /> Memuat...</div>
          ) : (
            <>
              <Notice tone={recon?.verdict === 'separated_clean' ? 'success' : 'danger'}
                icon={recon?.verdict === 'separated_clean' ? CheckCircle2 : AlertTriangle}
                testId="recon-verdict"
                title={recon?.verdict === 'separated_clean' ? 'Terpisah bersih ✓' : `Tumpang-tindih terdeteksi (${recon?.overlap_count})`}>
                {recon?.verdict_label}
              </Notice>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <GlassCard className="p-4" data-testid="recon-maklon-domain">
                  <div className="flex items-center gap-2 mb-2">
                    <PackageSearch size={16} className="text-[hsl(var(--primary))]" />
                    <span className="font-semibold text-foreground">Domain MAKLON (pcs)</span>
                  </div>
                  <p className="text-xs text-muted-foreground mb-3">SSOT KPI maklon · <code>{recon?.maklon_domain?.collection}</code></p>
                  <div className="grid grid-cols-2 gap-2 text-sm">
                    <div><span className="text-muted-foreground">Terkirim</span><div className="font-bold text-[hsl(var(--primary))]">{fmt(recon?.maklon_domain?.total_pcs_sent)} pcs</div></div>
                    <div><span className="text-muted-foreground">Batch kirim</span><div className="font-bold">{fmt(recon?.maklon_domain?.shipment_count)}</div></div>
                    <div><span className="text-muted-foreground">PO</span><div className="font-bold">{fmt(recon?.maklon_domain?.distinct_po)}</div></div>
                    <div><span className="text-muted-foreground">Vendor</span><div className="font-bold">{fmt(recon?.maklon_domain?.distinct_vendor)}</div></div>
                  </div>
                </GlassCard>
                <GlassCard className="p-4" data-testid="recon-wms-domain">
                  <div className="flex items-center gap-2 mb-2">
                    <Factory size={16} className="text-slate-500" />
                    <span className="font-semibold text-foreground">Domain WMS/Internal (meter)</span>
                  </div>
                  <p className="text-xs text-muted-foreground mb-3">Bukan KPI maklon · <code>{recon?.wms_domain?.collection}</code></p>
                  <div className="grid grid-cols-2 gap-2 text-sm">
                    <div><span className="text-muted-foreground">Dispatch kain</span><div className="font-bold text-slate-600">{fmt(recon?.wms_domain?.total_meter_dispatched)} m</div></div>
                    <div><span className="text-muted-foreground">Jml dispatch</span><div className="font-bold">{fmt(recon?.wms_domain?.dispatch_count)}</div></div>
                    <div><span className="text-muted-foreground">Work Order</span><div className="font-bold">{fmt(recon?.wms_domain?.distinct_wo)}</div></div>
                    <div><span className="text-muted-foreground">Nama CMT</span><div className="font-bold">{fmt(recon?.wms_domain?.distinct_cmt_name)}</div></div>
                  </div>
                </GlassCard>
              </div>

              {(recon?.overlaps || []).length > 0 && (
                <GlassCard className="overflow-hidden">
                  <div className="px-4 py-2.5 bg-[hsl(var(--destructive)/0.6)] border-b border-[hsl(var(--destructive)/0.35)] font-semibold text-[hsl(var(--destructive))] text-sm flex items-center gap-2">
                    <AlertTriangle size={15} /> PO Maklon yang muncul di KEDUA sistem (perlu ditinjau)
                  </div>
                  <table className="w-full text-sm">
                    <thead className="bg-muted/30 text-[11px] uppercase text-muted-foreground">
                      <tr>
                        <th className="px-3 py-1.5 text-left">PO Maklon</th>
                        <th className="px-3 py-1.5 text-left">Dispatch (WMS)</th>
                        <th className="px-3 py-1.5 text-left">Work Order</th>
                        <th className="px-3 py-1.5 text-left">Nama CMT</th>
                        <th className="px-3 py-1.5 text-right">Meter</th>
                      </tr>
                    </thead>
                    <tbody>
                      {recon.overlaps.map((o, i) => (
                        <tr key={i} className="border-t border-[hsl(var(--destructive)/0.35)]" data-testid={`recon-overlap-${i}`}>
                          <td className="px-3 py-1.5 font-medium text-foreground">{o.po_number}</td>
                          <td className="px-3 py-1.5 tabular-nums text-xs">{o.dispatch_no}</td>
                          <td className="px-3 py-1.5 text-xs text-muted-foreground">{o.wo_number}</td>
                          <td className="px-3 py-1.5 text-xs">{o.cmt_name}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{fmt(o.meter)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </GlassCard>
              )}

              {(recon?.cmt_name_matches || []).length > 0 && (
                <p className="text-xs text-muted-foreground">Nama CMT di WMS yang cocok dengan master vendor: <strong>{recon.cmt_name_matches.join(', ')}</strong> (informasi saja).</p>
              )}

              {(recon?.notes || []).length > 0 && (
                <Notice tone="info" className="text-xs">
                  <div className="space-y-1">
                    {recon.notes.map((n, i) => (
                      <p key={i} className="flex items-start gap-1.5"><ShieldCheck size={13} className="mt-0.5 flex-shrink-0 text-slate-400" /> {n}</p>
                    ))}
                  </div>
                </Notice>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

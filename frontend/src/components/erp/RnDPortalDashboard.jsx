/**
 * Ringkasan & Approval RnD — DIROMBAK 2026-08-06.
 *
 * KELUHAN OWNER: "ringkasan rnd juga tidak jelas, hanya cards yang besar sangat
 * buruk secara ui ux dan fungsionalitasnya tidak ada padahal ini step lifecycle
 * crusial yang butuh approve koordinasi antara staff rnd dengan manajement."
 *
 * Dulu: 3 baris × 4 kartu gradien raksasa, murni angka, tanpa satu pun aksi.
 * Sekarang: LAYAR KEPUTUSAN.
 *   1. Antrean Keputusan — style / permintaan sample / tech pack yang menunggu,
 *      dengan umur tunggu (SLA) + tombol Setujui / Tolak (alasan wajib untuk style).
 *   2. Tahapan Lifecycle — posisi antrean Draft → Menunggu → Disetujui → Naik Produksi.
 *   3. Ringkasan angka dalam tile kecil (bukan kartu raksasa).
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, 4 kartu angka StatTile (+ satu kalimat), antrean & riwayat &
 * posisi style = tabel standar yang bisa diunduh (posisi style berhalaman 25, disaring lewat pil tahap — dulu 7 kotak
 * HURUF BESAR), detail & pembanding revisi = popup standar, keputusan = popup form (Setujui hijau, Tolak merah),
 * tanpa warna mentah / kode status di layar. Kartu "Style aktif" (selalu 0: status itu tidak dipakai alur sekarang)
 * tidak ditampilkan.
 *
 * Endpoint approval-nya sudah ada sejak lama tapi tidak pernah dipakai UI:
 *   POST /api/dewi/rnd/styles/{id}/owner-approve · /owner-reject
 *   POST /api/dewi/rnd/sample-requests/{id}/approve · /reject
 *   POST /api/dewi/rnd/tech-packs/{id}/approve
 * Daftar antrean: GET /api/dewi/rnd/approvals/pending
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  RefreshCw, CheckCircle2, XCircle, ArrowRight, Loader2, Eye, ImageOff, Paperclip, GitCompare, Send,
} from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Skeleton } from '@/components/ui/skeleton';
import { GlassCard } from '@/components/ui/glass';
import FilterChips from '@/components/ui/filter-chips';
import PaginationLite from '@/components/ui/pagination-lite';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from './moduleAtoms';
import RnDRevisionCompare, { authImageUrl } from './RnDRevisionCompare';
import { RnDCompletenessBoard } from './RnDCompletenessBoard';

const API = process.env.REACT_APP_BACKEND_URL || '';

const KIND_TONE = { style: 'primary', sample: 'info', tech_pack: 'success' };
const SLA_LABEL = {
  baru: { label: 'baru', tone: 'muted' },
  'perlu perhatian': { label: 'perlu perhatian', tone: 'warning' },
  terlambat: { label: 'terlambat', tone: 'danger' },
};
// Nada tahap lifecycle (7 langkah) — dipakai tabel "Posisi tiap style".
const STAGE_TONE = {
  draft: 'muted', pending_owner_review: 'warning', approved_for_launch: 'info', techpack: 'primary',
  pattern: 'primary', sample: 'info', promoted: 'success',
};
const NAMA_SUMBER = {
  dewi_rnd_styles: 'Style RnD', dewi_rnd_sample_requests: 'Permintaan sample', dewi_rnd_tech_packs: 'Tech pack',
  dewi_rnd_patterns: 'Pola',
};
// Teks dari server → kalimat biasa: huruf besar hanya di awal, singkatan umum tetap (BOM, HPP, SOP, SKU, PIC, RnD).
const SINGKATAN = { bom: 'BOM', hpp: 'HPP', sop: 'SOP', sku: 'SKU', pic: 'PIC', rnd: 'RnD', po: 'PO', qc: 'QC' };
const kalimat = (s) => {
  const t = String(s || '').replace(/_/g, ' ').toLowerCase().replace(/[a-z]+/g, (w) => SINGKATAN[w] || w);
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : t;
};
const labelTahap = (s) => kalimat(s).replace(/^Draft/, 'Draf');

const fmtNum = (v) => Number(v || 0).toLocaleString('id-ID');
const STATUS_DOK = { draft: 'draf', approved: 'disetujui', rejected: 'ditolak', pending: 'menunggu', submitted: 'diajukan', in_progress: 'dikerjakan', done: 'selesai', completed: 'selesai' };
const statusDok = (s) => STATUS_DOK[String(s || '').toLowerCase()] || String(s || '-').replace(/_/g, ' ');

export default function RnDPortalDashboard({ token, onNavigate }) {
  const [pending, setPending] = useState(null);
  const [history, setHistory] = useState(null);
  const [lifecycle, setLifecycle] = useState(null);
  const [weekly, setWeekly] = useState(null);
  const [sending, setSending] = useState(false);
  const [detail, setDetail] = useState(null);   // item yang dibuka detailnya
  const [kpi, setKpi] = useState({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [decision, setDecision] = useState(null); // {item, action}
  const [notes, setNotes] = useState('');
  const [compareStyleId, setCompareStyleId] = useState(null);

  const headers = useMemo(() => ({
    'Content-Type': 'application/json', Authorization: `Bearer ${token}`,
  }), [token]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [p, d, h, lc, wk] = await Promise.all([
        fetch(`${API}/api/dewi/rnd/approvals/pending`, { headers }).then((r) => r.json()),
        fetch(`${API}/api/dewi/rnd/dashboard`, { headers }).then((r) => r.json()),
        fetch(`${API}/api/dewi/rnd/approvals/history?limit=50`, { headers }).then((r) => r.json()),
        fetch(`${API}/api/dewi/rnd/lifecycle`, { headers }).then((r) => r.json()),
        fetch(`${API}/api/dewi/rnd/reports/weekly-decisions`, { headers }).then((r) => r.json()),
      ]);
      setPending(p);
      setHistory(h);
      setLifecycle(lc);
      setWeekly(wk);
      setKpi(d?.kpi || {});
    } catch (e) {
      toast.error('Gagal memuat data RnD', { description: e.message });
    } finally {
      setLoading(false);
    }
  }, [headers]);

  useEffect(() => { load(); }, [load]);

  const sendWeeklyReport = async () => {
    setSending(true);
    try {
      const r = await fetch(`${API}/api/dewi/rnd/reports/weekly-decisions/send`, {
        method: 'POST', headers, body: JSON.stringify({}),
      });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(b.detail || `HTTP ${r.status}`);
      toast.success(`Rapor ${b.week_key} dikirim ke ${b.recipients} penerima`, {
        description: `${b.counts?.approved || 0} disetujui · ${b.counts?.rejected || 0} ditolak · `
          + `${b.counts?.stale || 0} menunggu terlalu lama`,
      });
      setWeekly(b);
    } catch (e) {
      toast.error('Gagal mengirim rapor', { description: e.message });
    } finally {
      setSending(false);
    }
  };

  const submitDecision = async () => {
    if (!decision) return;
    const { item, action } = decision;
    const url = action === 'approve' ? item.approve_url : item.reject_url;
    if (!url) { toast.error('Aksi ini belum tersedia untuk jenis dokumen tersebut.'); return; }
    if (action === 'reject' && item.reject_requires_notes && !notes.trim()) {
      toast.error('Alasan penolakan wajib diisi.');
      return;
    }
    setBusy(item.id);
    try {
      const r = await fetch(`${API}${url}`, {
        method: 'POST', headers, body: JSON.stringify({ notes: notes.trim() }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
      toast.success(
        action === 'approve' ? `${item.kind_label} "${item.title}" disetujui`
          : `${item.kind_label} "${item.title}" ditolak`,
        { description: item.next_step },
      );
      setDecision(null);
      setNotes('');
      setDetail(null);
      await load();
    } catch (e) {
      toast.error('Keputusan gagal disimpan', { description: e.message });
    } finally {
      setBusy('');
    }
  };

  const items = pending?.items || [];
  const [tahap, setTahap] = useState('');
  const [hal, setHal] = useState(1);
  const PER_HAL = 25;
  const semuaStyle = lifecycle?.styles || [];
  const styleTersaring = tahap ? semuaStyle.filter((r) => r.stage === tahap) : semuaStyle;
  const styleTampil = styleTersaring.slice((hal - 1) * PER_HAL, hal * PER_HAL);
  const stages = lifecycle?.stages || pending?.funnel || [];
  const bukaKeputusan = (it, action) => { setDecision({ item: it, action }); setNotes(''); };

  return (
    <PageLayout
      testId="rnd-approval-cockpit"
      headerTestId="rnd-cockpit-header"
      title="Dashboard RnD"
      subtitle="Yang menunggu keputusan manajemen, sudah berapa lama, dan langkah berikutnya."
      actions={onNavigate ? (
        <Button variant="outline" onClick={() => onNavigate('rnd-styles')} data-testid="rnd-open-styles">Buka style RnD<ArrowRight /></Button>
      ) : null}
      tools={(
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang" data-testid="rnd-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      )}
      summary={(
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="rnd-kpis" data-konten-utama="">
            <StatTile testId="rnd-kpi-Menunggu" label="Menunggu keputusan" value={loading && !pending ? '…' : fmtNum(items.length)}
              accent={pending?.overdue > 0 ? 'danger' : items.length ? 'warning' : 'default'}
              sub={pending?.overdue > 0 ? `${fmtNum(pending.overdue)} terlambat (≥ ${pending?.thresholds?.stale_days ?? 7} hari)` : 'Style, sample, dan tech pack'} />
            <StatTile testId="rnd-kpi-Total Style" label="Total style" value={fmtNum(kpi.total_styles)} sub={`${fmtNum(kpi.total_variants)} varian`} />
            <StatTile testId="rnd-kpi-Sample" label="Sample" value={fmtNum(kpi.total_samples)} sub={`${fmtNum(kpi.approved_samples)} disetujui`} />
            <StatTile testId="rnd-kpi-Tech Pack" label="Tech pack" value={fmtNum(lifecycle?.totals?.tech_packs)}
              sub={`${fmtNum(lifecycle?.totals?.tech_packs_approved)} disetujui`} />
          </div>
          <p className="text-xs text-muted-foreground">
            Revisi {fmtNum(kpi.total_revisions)} · pola {fmtNum(kpi.total_patterns)} · HPP tersimpan {fmtNum(kpi.total_hpp)}
            {pending?.thresholds && (
              <span data-testid="rnd-sla-threshold-note">
                {' · '}tanda kuning ≥ {pending.thresholds.attention_days} hari, merah ≥ {pending.thresholds.stale_days} hari (diatur di Ringkasan Bisnis › Atur ambang)
              </span>
            )}
          </p>
        </div>
      )}
    >
      {/* ── 1. Antrean keputusan ─────────────────────────────────────────── */}
      <GlassCard className="space-y-3 p-4">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <p className="text-base font-semibold text-foreground">Antrean keputusan</p>
            <p className="text-sm text-muted-foreground">Setujui atau tolak langsung dari sini; klik baris untuk detail dan foto.</p>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground" data-testid="rnd-pending-count">{fmtNum(items.length)} menunggu</span>
            {pending?.overdue > 0 && (
              <span data-testid="rnd-overdue-count">
                <StatusBadge status="terlambat" label={`${fmtNum(pending.overdue)} terlambat`} tone="danger" />
              </span>
            )}
            <TombolUnduh namaBerkas="rnd-antrean-keputusan" namaLembar="Antrean keputusan" baris={items} testId="rnd-pending-unduh"
              kolom={[
                { label: 'Jenis', nilai: (it) => it.kind_label },
                { label: 'Kode', nilai: (it) => it.code },
                { label: 'Judul', nilai: (it) => it.title },
                { label: 'Keterangan', nilai: (it) => it.subtitle || '' },
                { label: 'Diajukan oleh', nilai: (it) => it.requested_by || '' },
                { label: 'Menunggu (hari)', nilai: (it) => it.age_days },
                { label: 'Status tunggu', nilai: (it) => SLA_LABEL[it.sla]?.label || it.sla || '' },
                { label: 'Langkah berikutnya', nilai: (it) => it.next_step || '' },
              ]} />
          </div>
        </div>

        {loading && !pending ? (
          <div className="space-y-2">{[...Array(3)].map((_, i) => <Skeleton key={i} className="h-12 rounded-lg" />)}</div>
        ) : (
          <div className="overflow-x-auto" data-testid="rnd-pending-list">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Dokumen</TableHead>
                  <TableHead className="hidden md:table-cell">Diajukan oleh</TableHead>
                  <TableHead>Menunggu</TableHead>
                  <TableHead className="text-right"><span className="sr-only">Aksi</span></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.length === 0 && (
                  <TableRow className="hover:bg-transparent">
                    <TableCell colSpan={4} className="p-0 [&>div]:py-8">
                      <EmptyState icon={CheckCircle2} testId="rnd-pending-empty" title="Tidak ada yang menunggu keputusan"
                        description="Item muncul di sini ketika staf RnD mengirim style untuk ditinjau, mengajukan permintaan sample, atau menyiapkan tech pack." />
                    </TableCell>
                  </TableRow>
                )}
                {items.map((it) => (
                  <TableRow key={`${it.kind}-${it.id}`} className="cursor-pointer" onClick={() => setDetail(it)}
                    data-testid={`rnd-pending-${it.kind}-${it.id}`}>
                    <TableCell className="whitespace-normal">
                      <div className="flex flex-wrap items-center gap-2">
                        <StatusBadge status={it.kind} label={it.kind_label} tone={KIND_TONE[it.kind] || 'default'} />
                        <span className="text-xs text-muted-foreground">{it.code}</span>
                        {it.images?.length > 0 && <span className="text-xs text-muted-foreground">{it.images.length} foto</span>}
                      </div>
                      <p className="mt-0.5 font-medium text-foreground">{it.title}</p>
                      <p className="text-xs text-muted-foreground">{it.subtitle}{it.next_step ? ` · ${it.next_step}` : ''}</p>
                    </TableCell>
                    <TableCell className="hidden md:table-cell">{it.requested_by}</TableCell>
                    <TableCell className="whitespace-nowrap">
                      <StatusBadge status={it.sla} label={`${fmtNum(it.age_days)} hari · ${SLA_LABEL[it.sla]?.label || it.sla}`} tone={SLA_LABEL[it.sla]?.tone || 'muted'} />
                    </TableCell>
                    <TableCell className="text-right" onClick={(e) => e.stopPropagation()}>
                      <div className="inline-flex flex-wrap justify-end gap-2">
                        <Button variant="ghost" size="icon-sm" onClick={() => setDetail(it)} title="Lihat detail" aria-label="Lihat detail"
                          data-testid={`rnd-detail-${it.id}`}>
                          <Eye />
                        </Button>
                        {it.reject_url && (
                          <Button variant="destructive" size="sm" disabled={busy === it.id} onClick={() => bukaKeputusan(it, 'reject')}
                            data-testid={`rnd-reject-${it.id}`}>
                            <XCircle />Tolak
                          </Button>
                        )}
                        <Button variant="success" size="sm" disabled={busy === it.id} onClick={() => bukaKeputusan(it, 'approve')}
                          data-testid={`rnd-approve-${it.id}`}>
                          {busy === it.id ? <Loader2 className="animate-spin" /> : <CheckCircle2 />}Setujui
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </GlassCard>

      {/* ── 2. Tahapan & posisi tiap style (pil tahap menyaring tabel) ───── */}
      <GlassCard className="space-y-3 p-4" data-testid="rnd-lifecycle-card">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-base font-semibold text-foreground">Posisi tiap style</p>
            <p className="text-sm text-muted-foreground">
              Draf → menunggu keputusan → disetujui → tech pack → pola → sample → naik produksi. Satu style menempati tahap terjauh yang sudah dicapai.
            </p>
            {lifecycle?.totals && (
              <p className="mt-1 text-xs text-muted-foreground" data-testid="rnd-lifecycle-totals">
                {fmtNum(lifecycle.totals.tech_packs)} tech pack ({fmtNum(lifecycle.totals.tech_packs_approved)} disetujui) ·
                {' '}{fmtNum(lifecycle.totals.samples)} sample · {fmtNum(lifecycle.totals.sample_pics)} PIC · {fmtNum(lifecycle.totals.patterns)} pola
              </p>
            )}
          </div>
          <TombolUnduh namaBerkas="rnd-posisi-style" namaLembar="Posisi style" baris={styleTersaring} testId="rnd-lifecycle-unduh"
            kolom={[
              { label: 'Kode', nilai: (r) => r.style_code },
              { label: 'Nama', nilai: (r) => r.style_name },
              { label: 'Tahap', nilai: (r) => labelTahap(r.stage_label) },
              { label: 'Menunggu (hari)', nilai: (r) => r.waiting_days || 0 },
              { label: 'Varian', nilai: (r) => r.variants || 0 },
              { label: 'Foto', nilai: (r) => r.photos || 0 },
              { label: 'Tech pack', nilai: (r) => (r.techpack?.count ? `${r.techpack.version || '-'} · ${statusDok(r.techpack.status || 'draft')}` : 'Belum ada') },
              { label: 'Pola', nilai: (r) => r.patterns || 0 },
              { label: 'Sample', nilai: (r) => (r.sample?.count ? `${r.sample.code || '-'} · ${statusDok(r.sample.status)} · PIC ${r.sample.pic || '(belum ditentukan)'}` : 'Belum ada') },
              { label: 'HPP', nilai: (r) => r.hpp || 0 },
              { label: 'Langkah berikutnya', nilai: (r) => r.next_action || '' },
            ]} />
        </div>
        {stages.length > 0 && (
          <FilterChips testId="rnd-funnel" ariaLabel="Saring tahap" hideWhenEmpty={false} value={tahap}
            onChange={(k) => { setTahap(k); setHal(1); }}
            options={[{ key: '', label: 'Semua', count: lifecycle?.total_styles ?? semuaStyle.length },
              ...stages.map((f) => ({ key: f.key, label: labelTahap(f.stage), count: f.count }))]} />
        )}
        {!lifecycle ? (
          <Skeleton className="h-28 rounded-lg" />
        ) : (
          <>
            <div className="overflow-x-auto">
              <Table data-testid="rnd-lifecycle-table">
                <TableHeader>
                  <TableRow>
                    <TableHead>Style</TableHead>
                    <TableHead>Tahap</TableHead>
                    <TableHead className="hidden text-right xl:table-cell">Varian</TableHead>
                    <TableHead className="hidden text-right xl:table-cell">Foto</TableHead>
                    <TableHead className="hidden lg:table-cell">Tech pack</TableHead>
                    <TableHead className="hidden lg:table-cell">Sample (PIC)</TableHead>
                    <TableHead className="hidden md:table-cell">Langkah berikutnya</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {styleTersaring.length === 0 && (
                    <TableRow data-testid="rnd-lifecycle-empty" className="hover:bg-transparent">
                      <TableCell colSpan={7} className="p-0 [&>div]:py-8">
                        <EmptyState title={semuaStyle.length ? 'Tidak ada style di tahap ini' : 'Belum ada style RnD'}
                          description={semuaStyle.length ? undefined : 'Setelah staf RnD membuat style, posisinya muncul di sini.'} />
                      </TableCell>
                    </TableRow>
                  )}
                  {styleTampil.map((r) => (
                    <TableRow key={r.id} data-testid={`rnd-lifecycle-row-${r.id}`}>
                      <TableCell className="whitespace-nowrap"><span className="mr-2 text-xs text-muted-foreground">{r.style_code}</span>{r.style_name}</TableCell>
                      <TableCell className="whitespace-nowrap">
                        <StatusBadge status={r.stage} label={labelTahap(r.stage_label)} tone={STAGE_TONE[r.stage] || 'default'} />
                        {r.waiting_days > 0 && <span className="ml-1 text-xs text-muted-foreground">{r.waiting_days} hari</span>}
                      </TableCell>
                      <TableCell className="hidden text-right tabular-nums xl:table-cell">{fmtNum(r.variants)}</TableCell>
                      <TableCell className="hidden text-right tabular-nums xl:table-cell">{fmtNum(r.photos)}</TableCell>
                      <TableCell className="hidden lg:table-cell">
                        {r.techpack?.count ? `${r.techpack.version || '-'} · ${statusDok(r.techpack.status || 'draft')}` : <span className="text-muted-foreground">Belum ada</span>}
                      </TableCell>
                      <TableCell className="hidden lg:table-cell">
                        {r.sample?.count ? `${r.sample.code || '-'} · ${statusDok(r.sample.status)} · PIC ${r.sample.pic || '(belum ditentukan)'}`
                          : <span className="text-muted-foreground">Belum ada</span>}
                      </TableCell>
                      <TableCell className="hidden max-w-[280px] whitespace-normal text-muted-foreground md:table-cell">{r.next_action}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            {styleTersaring.length > PER_HAL && (
              <PaginationLite page={hal} totalPages={Math.ceil(styleTersaring.length / PER_HAL)} total={styleTersaring.length}
                pageSize={PER_HAL} onPageChange={setHal} />
            )}
          </>
        )}
      </GlassCard>

      {/* ── 3. Rapor keputusan mingguan ─────────────────────────────────── */}
      <GlassCard className="space-y-3 p-4" data-testid="rnd-weekly-card">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <p className="text-base font-semibold text-foreground">Rapor keputusan mingguan</p>
            <p className="text-sm text-muted-foreground">
              Dikirim otomatis setiap Senin pukul 08.00 WIB ke manajemen: style disetujui, ditolak, dan yang menunggu lebih dari {weekly?.stale_days ?? 7} hari.
            </p>
          </div>
          <Button variant="outline" onClick={sendWeeklyReport} disabled={sending || !weekly} data-testid="rnd-weekly-send">
            {sending ? <Loader2 className="animate-spin" /> : <Send />}Kirim sekarang
          </Button>
        </div>
        {!weekly ? (
          <Skeleton className="h-20 rounded-lg" />
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="rnd-weekly-counts">
              <StatTile testId="rnd-weekly-Disetujui" label="Disetujui" value={fmtNum(weekly.counts?.approved)} />
              <StatTile testId="rnd-weekly-Ditolak" label="Ditolak" value={fmtNum(weekly.counts?.rejected)} />
              <StatTile testId="rnd-weekly-Masih Menunggu" label="Masih menunggu" value={fmtNum(weekly.counts?.pending)} />
              <StatTile testId="rnd-weekly-Menunggu Terlalu Lama" label="Menunggu terlalu lama" value={fmtNum(weekly.counts?.stale)}
                accent={weekly.counts?.stale ? 'warning' : 'default'} />
            </div>
            <p className="text-xs text-muted-foreground">Periode rapor: {weekly.period_from} s.d. {weekly.period_to} · pekan {weekly.week_key}</p>
            {(weekly.stale || []).length > 0 && (
              <Table data-testid="rnd-weekly-stale-list">
                <TableHeader>
                  <TableRow><TableHead>Style menunggu terlalu lama</TableHead><TableHead className="text-right">Menunggu</TableHead><TableHead className="hidden sm:table-cell">Diajukan oleh</TableHead></TableRow>
                </TableHeader>
                <TableBody>
                  {weekly.stale.slice(0, 5).map((r) => (
                    <TableRow key={r.id}>
                      <TableCell><span className="mr-2 text-xs text-muted-foreground">{r.style_code}</span>{r.style_name}</TableCell>
                      <TableCell className="text-right tabular-nums">{r.age_days} hari</TableCell>
                      <TableCell className="hidden sm:table-cell">{r.requested_by}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </>
        )}
      </GlassCard>

      {/* ── 4. Riwayat keputusan ─────────────────────────────────────────── */}
      <GlassCard className="space-y-3 p-4" data-testid="rnd-history-card">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <p className="text-base font-semibold text-foreground">Riwayat keputusan</p>
            <p className="text-sm text-muted-foreground">
              Siapa menyetujui atau menolak, kapan, dan alasannya · {fmtNum(history?.approved)} disetujui · {fmtNum(history?.rejected)} ditolak.
            </p>
          </div>
          <TombolUnduh namaBerkas="rnd-riwayat-keputusan" namaLembar="Riwayat keputusan" baris={history?.items || []} testId="rnd-history-unduh"
            kolom={[
              { label: 'Jenis', nilai: (r) => r.kind_label },
              { label: 'Kode', nilai: (r) => r.code },
              { label: 'Judul', nilai: (r) => r.title },
              { label: 'Hasil', nilai: (r) => (r.result === 'approved' ? 'Disetujui' : 'Ditolak') + (r.promoted ? ' · naik produksi' : '') },
              { label: 'Diputuskan oleh', nilai: (r) => r.decided_by || '' },
              { label: 'Tanggal', nilai: (r) => (r.decided_at ? new Date(r.decided_at).toLocaleString('id-ID') : '') },
              { label: 'Alasan / catatan', nilai: (r) => r.notes || '' },
            ]} />
        </div>
        {!history ? (
          <Skeleton className="h-24 rounded-lg" />
        ) : (
          <div className="overflow-x-auto">
            <Table data-testid="rnd-history-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Dokumen</TableHead>
                  <TableHead>Hasil</TableHead>
                  <TableHead className="hidden md:table-cell">Diputuskan oleh</TableHead>
                  <TableHead className="hidden sm:table-cell">Tanggal</TableHead>
                  <TableHead className="hidden lg:table-cell">Alasan / catatan</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(history.items || []).length === 0 && (
                  <TableRow data-testid="rnd-history-empty" className="hover:bg-transparent">
                    <TableCell colSpan={5} className="p-0 [&>div]:py-8">
                      <EmptyState title="Belum ada keputusan tercatat"
                        description="Setiap persetujuan/penolakan dari layar ini muncul di sini beserta nama pemutus dan alasannya." />
                    </TableCell>
                  </TableRow>
                )}
                {(history.items || []).map((r) => (
                  <TableRow key={`${r.kind}-${r.id}`} data-testid={`rnd-history-${r.id}`}>
                    <TableCell className="whitespace-normal">
                      <span className="text-xs text-muted-foreground">{r.kind_label} · {r.code}</span>
                      <span className="block max-w-[240px] truncate text-foreground" title={r.title}>{r.title}</span>
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      <StatusBadge status={r.result} label={r.result === 'approved' ? 'Disetujui' : 'Ditolak'} tone={r.result === 'approved' ? 'success' : 'danger'} />
                      {r.promoted && <span className="ml-1 text-xs text-muted-foreground">naik produksi</span>}
                    </TableCell>
                    <TableCell className="hidden md:table-cell">{r.decided_by || '—'}</TableCell>
                    <TableCell className="hidden whitespace-nowrap sm:table-cell">{r.decided_at ? new Date(r.decided_at).toLocaleString('id-ID') : '—'}</TableCell>
                    <TableCell className="hidden max-w-[280px] whitespace-normal text-muted-foreground lg:table-cell">{r.notes || '—'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </GlassCard>

      {/* ── 5. Kelengkapan data produk (owner 2026-09-12) ─────────────────── */}
      <RnDCompletenessBoard token={token} onNavigate={onNavigate} />

      {pending?.sources?.length > 0 && (
        <p className="text-xs text-muted-foreground" data-testid="rnd-source-trace">
          Sumber data: {pending.sources.map((s) => `${NAMA_SUMBER[s.collection] || 'Data lain'} ${fmtNum(s.count)}`).join(' · ')}.
        </p>
      )}

      {/* ── Detail item (spesifikasi + foto) — popup ─────────────────────── */}
      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} testId="rnd-detail-dialog"
          judul={`${detail.title}${detail.code ? ` · ${detail.code}` : ''}`}
          keterangan={`${detail.kind_label} · diajukan oleh ${detail.requested_by} · menunggu ${detail.age_days} hari`}
          aksi={(
            <>
              {detail.reject_url && (
                <Button size="sm" variant="destructive" data-testid="rnd-detail-reject" onClick={() => bukaKeputusan(detail, 'reject')}>
                  <XCircle />Tolak
                </Button>
              )}
              <Button size="sm" variant="success" data-testid="rnd-detail-approve" onClick={() => bukaKeputusan(detail, 'approve')}>
                <CheckCircle2 />Setujui
              </Button>
            </>
          )}>
          <dl className="grid grid-cols-1 gap-x-6 divide-y divide-[var(--glass-border)] sm:grid-cols-2 sm:divide-y-0">
            {Object.entries(detail.detail || {}).map(([k, v]) => (
              <BarisDetail key={k} label={kalimat(k)}>
                {v === null || v === undefined || v === '' ? '—'
                  : (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}/.test(v) ? new Date(v).toLocaleString('id-ID') : String(v))}
              </BarisDetail>
            ))}
          </dl>

          <div className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-medium text-foreground">Foto / gambar desain ({detail.images?.length || 0})</p>
              {detail.kind === 'style' && (
                <Button variant="outline" size="sm" data-testid="rnd-detail-compare" onClick={() => setCompareStyleId(detail.id)}>
                  <GitCompare />Bandingkan revisi{detail.revisions_count > 0 ? ` (${detail.revisions_count})` : ''}
                </Button>
              )}
            </div>
            {(detail.images || []).length === 0 ? (
              <p className="flex items-center gap-2 rounded-md border border-dashed border-[var(--glass-border)] px-3 py-4 text-sm text-muted-foreground"
                data-testid="rnd-detail-no-image">
                <ImageOff className="h-4 w-4" />Belum ada gambar dilampirkan. Staf RnD dapat menambahkannya di modul RnD.
              </p>
            ) : (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3" data-testid="rnd-detail-images">
                {detail.images.map((img, i) => (
                  <a key={i} href={authImageUrl(img.url, token)} target="_blank" rel="noreferrer"
                    className="group overflow-hidden rounded-lg border border-[var(--glass-border)]" title={img.caption || 'Buka gambar'}>
                    <img src={authImageUrl(img.url, token)} alt={img.caption || `Gambar ${i + 1}`} loading="lazy"
                      className="h-32 w-full object-cover transition-transform duration-200 group-hover:scale-105" />
                    {img.caption && <p className="truncate px-2 py-1 text-xs text-muted-foreground">{img.caption}</p>}
                  </a>
                ))}
              </div>
            )}
          </div>

          {detail.attachment_url && (
            <Button variant="outline" size="sm" asChild data-testid="rnd-detail-attachment">
              <a href={authImageUrl(detail.attachment_url, token)} target="_blank" rel="noreferrer">
                <Paperclip />{detail.attachment_name || 'Buka lampiran / tech pack'}
              </a>
            </Button>
          )}
          <p className="text-sm text-muted-foreground">Langkah berikutnya: {detail.next_step}</p>
        </DetailPopup>
      )}

      {/* ── Keputusan setujui/tolak — popup form pendek ─────────────────── */}
      <PopupKeputusan decision={decision} notes={notes} setNotes={setNotes} busy={!!busy}
        onBatal={() => { setDecision(null); setNotes(''); }} onKirim={submitDecision} />

      {/* ── Pembanding revisi style (dibuka dari detail) ─────────────────── */}
      {compareStyleId && (
        <RnDRevisionCompare token={token} styleId={compareStyleId} onClose={() => setCompareStyleId(null)} />
      )}
    </PageLayout>
  );
}

/** Popup keputusan = FormPopup pendek; tombol simpan hijau untuk "Setujui", merah untuk "Tolak" (warnaSimpan). */
function PopupKeputusan({ decision, notes, setNotes, busy, onBatal, onKirim }) {
  const tolak = decision?.action === 'reject';
  return (
    <FormPopup open={!!decision} onClose={onBatal} testId="rnd-decision-dialog"
      judul={`${tolak ? 'Tolak' : 'Setujui'} ${decision?.item?.kind_label?.toLowerCase() || ''}`}
      keterangan={`${decision?.item?.code || ''} — ${decision?.item?.title || ''}${!tolak && decision?.item?.next_step ? ` · ${decision.item.next_step}` : ''}`}
      onSimpan={onKirim} menyimpan={busy} labelSimpan={tolak ? 'Tolak' : 'Setujui'} warnaSimpan={tolak ? 'destructive' : 'success'}>
      <Isian htmlFor="rnd-notes" wajib={tolak && !!decision?.item?.reject_requires_notes}
        label={tolak ? 'Alasan penolakan' : 'Catatan persetujuan'}
        petunjuk={tolak ? (decision?.item?.reject_requires_notes ? 'Wajib diisi.' : 'Opsional.') : 'Opsional.'}>
        <Textarea id="rnd-notes" value={notes} rows={3} data-testid="rnd-decision-notes" onChange={(e) => setNotes(e.target.value)}
          placeholder={tolak ? 'Mis. proporsi lengan perlu diperbaiki, bahan terlalu tebal untuk musim ini' : 'Mis. lanjutkan ke pembuatan sample'} />
      </Isian>
    </FormPopup>
  );
}

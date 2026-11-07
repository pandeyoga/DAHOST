/**
 * Kesehatan data stok — Portal Gudang (FASE 6.6-A, diperluas FASE 12)
 *
 * MASALAH YANG DIJAGA MODUL INI
 * Koleksi stok kanonik `rahaza_material_stock` dulu ditulis 3 kelompok writer dengan
 * bentuk berbeda:
 *   • Skema A (kanonik)        {material_id, location_id, qty}
 *   • Skema B (aksesoris lama) lokasi tersimpan BERSARANG (location.id) + total_qty
 *   • Skema C (barang jadi)    TANPA lokasi + available_quantity terpisah
 * Sejak konsolidasi, semua tulisan baru sudah kanonik — TAPI baris warisan di database
 * yang sudah berjalan bisa masih berbentuk B/C. Akibatnya layar yang membaca stok
 * PER LOKASI (Put-Away, Opname per-bin, peta gudang) tidak melihat baris itu, dan bisa
 * muncul baris kembar untuk material+lokasi yang sama.
 *
 * FASE 12 menambah penyakit ke-8 `unmapped_location`: baris stok yang duduk di lokasi
 * yang BUKAN zona penyimpanan. Modul ini menampilkan peta lokasi + usulan zona tujuan, dan
 * rekonsiliasi memindahkan baris tersebut ke zona kanonik sesuai kategori material.
 * Lantai produksi & karantina QC SENGAJA dikecualikan.
 *
 * Modul ini: diagnosa (read-only) + rekonsiliasi (pratinjau dulu, lalu terapkan) +
 * rollback presisi lewat jurnal. Rekonsiliasi TIDAK PERNAH mengubah total stok.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, StatTile, tabel TabelData + unduh Excel/CSV, konfirmasi terapkan
 * lewat confirmDialog (dulu panel di halaman), kode masalah (`negative_qty` …) diganti label Indonesia.
 * Verifikasi angka: kartu "Baris stok" dulu berketerangan "Total on-hand −1" = jumlah qty lintas satuan → dihapus.
 *
 * Sumber data: /api/wms/stock-schema/{health,reconcile,reconcile/rollback,logs}
 */

import { useState, useEffect, useCallback } from 'react';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { RefreshCw, Wrench, Undo2, AlertTriangle, Info, CheckCircle2, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import { Skeleton } from '@/components/ui/skeleton';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { BarisDetail } from '@/components/ui/detail-popup';
import { formatDateTimeID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL || '';

async function api(method, path, token, body) {
  const opts = { method, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(`${API}${path}`, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const err = new Error(data.detail || `HTTP ${r.status}`);
    err.status = r.status;
    throw err;
  }
  return data;
}

const fmtNum = (n) => Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 4 });

const SCHEMA_LABEL = {
  A: 'kanonik (lokasi datar)',
  B: 'warisan, lokasi bersarang',
  C: 'warisan, tanpa lokasi',
};

// FASE 12 — klasifikasi lokasi (SSOT backend: core/location_resolver.KIND_*)
const KIND_BADGE = {
  storage: { label: 'Zona penyimpanan', tone: 'success' },
  exempt: { label: 'Produksi / karantina', tone: 'info' },
  unmapped: { label: 'Bukan zona penyimpanan', tone: 'warning' },
};
const PERAN = { bahan: 'Bahan', aksesoris: 'Aksesoris', fg: 'Produk jadi', sample: 'Sampel' };
// Label pendek untuk kode masalah dari server (label panjangnya tetap di `title`).
const MASALAH = {
  nested_location: 'Lokasi bersarang', missing_location: 'Tanpa lokasi', unmapped_location: 'Bukan zona penyimpanan',
  alias_drift: 'Alias qty beda', available_drift: 'Qty tersedia tidak cocok', duplicate_rows: 'Baris kembar',
  negative_qty: 'Stok minus', orphan_material: 'Material tidak ada di master',
};

function Bagian({ judul, keterangan, alat, children, testId }) {
  return (
    <GlassCard className="space-y-3 p-4" data-testid={testId}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-base font-semibold text-foreground">{judul}</p>
          {keterangan && <p className="text-sm text-muted-foreground">{keterangan}</p>}
        </div>
        {alat && <div className="flex flex-wrap items-center gap-2">{alat}</div>}
      </div>
      {children}
    </GlassCard>
  );
}

export default function StockSchemaHealthModule({ token }) {
  const [health, setHealth] = useState(null);
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  const [msg, setMsg] = useState('');
  const [plan, setPlan] = useState(null);
  const [canReconcile, setCanReconcile] = useState(true);

  const load = useCallback(async () => {
    setLoading(true); setErr('');
    try {
      const h = await api('GET', '/api/wms/stock-schema/health', token);
      setHealth(h);
      try {
        const l = await api('GET', '/api/wms/stock-schema/logs?limit=20', token);
        setLogs(Array.isArray(l) ? l : []);
      } catch { setLogs([]); }
    } catch (e) { setErr(e.message); }
    finally { setLoading(false); }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const preview = async () => {
    setBusy('preview'); setErr(''); setMsg('');
    try {
      const res = await api('POST', '/api/wms/stock-schema/reconcile', token, { dry_run: true });
      setPlan(res);
      setMsg('Pratinjau selesai — belum ada data yang diubah.');
    } catch (e) {
      if (e.status === 403) setCanReconcile(false);
      setErr(e.message);
    } finally { setBusy(''); }
  };

  const apply = async () => {
    const ok = await confirmDialog({
      title: 'Terapkan rekonsiliasi sekarang?',
      body: 'Bentuk baris stok dinormalkan, baris di luar zona penyimpanan dipindah ke zona kanonik sesuai kategori '
        + 'material, dan baris kembar digabung. Total stok tidak berubah; setiap perubahan dicatat di riwayat dan bisa dikembalikan.',
      confirmLabel: 'Ya, terapkan',
    });
    if (!ok) return;
    setBusy('apply'); setErr(''); setMsg('');
    try {
      const res = await api('POST', '/api/wms/stock-schema/reconcile', token, { dry_run: false });
      const s = res.summary || {};
      setMsg(
        `Rekonsiliasi diterapkan · ${s.rows_normalized || 0} baris dinormalkan · `
        + `${s.rows_relocated || 0} baris dipindah ke zona yang benar · `
        + `${s.rows_merged || 0} baris kembar digabung · total stok ${s.total_qty_preserved ? 'tidak berubah' : 'BERUBAH (periksa!)'}`
        + (res.log_id ? ` · log ${String(res.log_id).slice(0, 8)}` : ''),
      );
      setPlan(null);
      await load();
    } catch (e) {
      if (e.status === 403) setCanReconcile(false);
      setErr(e.message);
    } finally { setBusy(''); }
  };

  const rollback = async (logId) => {
    setBusy(`rb-${logId}`); setErr(''); setMsg('');
    try {
      const res = await api('POST', '/api/wms/stock-schema/reconcile/rollback', token, { log_id: logId });
      setMsg(`Pengembalian selesai · ${res.rows_restored || 0} baris dipulihkan · ${res.rows_reinserted || 0} baris dihidupkan kembali.`);
      await load();
    } catch (e) {
      if (e.status === 403) setCanReconcile(false);
      setErr(e.message);
    } finally { setBusy(''); }
  };

  const details = health?.details || [];
  const detailsPg = useClientPagination(details, 25);
  const locations = health?.locations || [];
  const unmappedLocations = locations.filter((l) => l.kind === 'unmapped');
  const roleTargets = (health?.role_targets || []).filter((r) => r.location_id);
  const counts = health?.counts || {};
  const labels = health?.labels || {};
  const hints = health?.hints || {};
  const reportOnly = health?.report_only || [];
  const issueRows = Object.keys(counts).filter((k) => counts[k] > 0);
  const lokasiBaris = (d) => (d.location_id || d.nested_location_id
    ? `${d.location_code || d.location_id || d.nested_location_id}${d.location_name && d.location_name !== d.location_code ? ` · ${d.location_name}` : ''}`
    : 'Tanpa lokasi');

  const kolomLokasi = [
    { kunci: 'lokasi', label: 'Lokasi', hp: 'judul', isi: (l) => (
      <div className="min-w-0" data-testid={`stock-loc-${l.location_id}`}>
        <p className="font-medium">{l.name || l.code || l.location_id}</p>
        <p className="text-xs text-muted-foreground">{l.code || l.location_id}</p>
      </div>) },
    { kunci: 'status', label: 'Status', isi: (l) => { const b = KIND_BADGE[l.kind] || KIND_BADGE.unmapped; return <StatusBadge status={l.kind} label={b.label} tone={b.tone} />; } },
    { kunci: 'baris', label: 'Baris', rata: 'kanan', isi: (l) => <span className="tabular-nums">{fmtNum(l.rows)}</span> },
    { kunci: 'qty', label: 'Total qty', rata: 'kanan', isi: (l) => <span className="tabular-nums">{fmtNum(l.qty)}</span> },
  ];

  const kolomDetail = [
    { kunci: 'material', label: 'Material', hp: 'judul', isi: (d) => (
      <div className="min-w-0 md:max-w-[18rem]" data-testid={`schema-row-${d.row_id}`}>
        <p className="font-medium">{d.material_name}</p>
        <p className="text-xs text-muted-foreground">{d.material_code || d.material_id}</p>
      </div>) },
    { kunci: 'skema', label: 'Skema', hp: false, rata: 'tengah', isi: (d) => (
      <StatusBadge status={d.schema} label={d.schema} tone={d.schema === 'A' ? 'success' : 'warning'} />) },
    { kunci: 'lokasi', label: 'Lokasi', isi: (d) => (d.location_id || d.nested_location_id
      ? <span className="text-sm">{lokasiBaris(d)}</span>
      : <span className="text-sm text-[hsl(var(--warning-text))]">Tanpa lokasi</span>) },
    { kunci: 'usulan', label: 'Usulan zona', hp: false, isi: (d) => (
      <span className="text-sm" data-testid={`schema-suggest-${d.row_id}`}>{d.suggested_location_code ? `→ ${d.suggested_location_code}` : '—'}</span>) },
    { kunci: 'qty', label: 'Qty', rata: 'kanan', isi: (d) => (
      <span className="tabular-nums font-medium md:whitespace-nowrap">{fmtNum(d.qty)} <span className="text-xs font-normal text-muted-foreground">{d.unit}</span></span>) },
    { kunci: 'reserved', label: 'Dicadangkan', hp: false, rata: 'kanan', isi: (d) => <span className="tabular-nums text-muted-foreground">{fmtNum(d.reserved)}</span> },
    { kunci: 'masalah', label: 'Masalah', isi: (d) => (
      <div className="flex flex-wrap gap-1">
        {(d.issues || []).map((i) => (
          <span key={i} title={labels[i] || ''}>
            <StatusBadge status={i} label={MASALAH[i] || labels[i] || 'Lainnya'} tone={reportOnly.includes(i) ? 'danger' : 'warning'} />
          </span>
        ))}
      </div>) },
  ];

  const kolomLog = [
    { kunci: 'waktu', label: 'Waktu', hp: 'judul', isi: (l) => (
      <span className="md:whitespace-nowrap" data-testid={`schema-log-${l.id}`}>{formatDateTimeID(l.created_at)}</span>) },
    { kunci: 'oleh', label: 'Oleh', hp: 'keterangan', isi: (l) => l.actor?.name || '—' },
    { kunci: 'norm', label: 'Dinormalkan', hp: false, rata: 'kanan', isi: (l) => <span className="tabular-nums">{fmtNum(l.summary?.rows_normalized)}</span> },
    { kunci: 'pindah', label: 'Dipindah', hp: false, rata: 'kanan', isi: (l) => <span className="tabular-nums">{fmtNum(l.summary?.rows_relocated)}</span> },
    { kunci: 'gabung', label: 'Digabung', hp: false, rata: 'kanan', isi: (l) => <span className="tabular-nums">{fmtNum(l.summary?.rows_merged)}</span> },
    { kunci: 'status', label: 'Status', isi: (l) => (l.rolled_back_at
      ? <StatusBadge status="rolled_back" label="Sudah dikembalikan" tone="muted" />
      : <StatusBadge status="aktif" label="Berlaku" tone="success" />) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (l) => (!l.rolled_back_at && canReconcile ? (
      <Button size="sm" variant="outline" onClick={() => rollback(l.id)} disabled={busy === `rb-${l.id}`}
        data-testid={`schema-rollback-${l.id}`}>
        {busy === `rb-${l.id}` ? <Loader2 className="animate-spin" /> : <Undo2 />}Kembalikan
      </Button>) : null) },
  ];

  if (loading && !health) {
    return (
      <div className="space-y-4" data-testid="stock-schema-loading">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-20 rounded-xl" />)}
        </div>
        <Skeleton className="h-40 rounded-xl" />
      </div>
    );
  }

  return (
    <PageLayout testId="stock-schema-module" title="Kesehatan data stok"
      subtitle="Memastikan setiap baris stok berbentuk kanonik dan berada di zona penyimpanan yang benar. Rekonsiliasi tidak mengubah total stok."
      tools={
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="stock-schema-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      }
      summary={<>
        {err && <Notice tone="danger" icon={AlertTriangle} testId="stock-schema-error" title="Gagal">{err}</Notice>}
        {msg && <Notice tone="success" icon={CheckCircle2} testId="stock-schema-msg" title={msg} />}
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Baris stok" value={fmtNum(health?.total_rows)} sub="Semua baris barang × lokasi yang diperiksa." />
          <StatTile label="Baris bermasalah" value={fmtNum(health?.affected_rows)} accent={health?.healthy ? 'default' : 'warning'}
            sub={health?.healthy ? 'Semua baris kanonik.' : 'Punya satu masalah atau lebih.'} />
          <StatTile label="Bisa diperbaiki otomatis" value={fmtNum(health?.fixable_issues)} accent={health?.fixable_issues ? 'warning' : 'default'}
            sub="Lewat tombol Terapkan rekonsiliasi." />
          <StatTile label="Perlu keputusan manual" value={fmtNum(health?.manual_issues)} accent={health?.manual_issues ? 'danger' : 'default'}
            sub="Stok minus atau material tidak ada di master." />
        </div>
      </>}>
      {/* Status + aksi */}
      {health?.healthy ? (
        <Notice tone="success" icon={CheckCircle2} testId="stock-schema-healthy" title="Data stok sehat">
          Semua {fmtNum(health?.total_rows)} baris memakai bentuk kanonik. Tidak ada tindakan yang diperlukan.
        </Notice>
      ) : (
        <Bagian testId="stock-schema-issues" judul={`${fmtNum(health?.affected_rows)} baris perlu perhatian`}
          keterangan={`Bentuk baris: skema A ${SCHEMA_LABEL.A} ${fmtNum(health?.by_schema?.A)} · skema B ${SCHEMA_LABEL.B} ${fmtNum(health?.by_schema?.B)} · skema C ${SCHEMA_LABEL.C} ${fmtNum(health?.by_schema?.C)}.`}
          alat={canReconcile ? <>
            <Button variant="outline" onClick={preview} disabled={!!busy} data-testid="stock-schema-preview-btn">
              {busy === 'preview' ? <Loader2 className="animate-spin" /> : <Info />}Pratinjau rekonsiliasi
            </Button>
            <Button onClick={apply} disabled={!!busy || !health?.fixable_issues} data-testid="stock-schema-apply-btn">
              {busy === 'apply' ? <Loader2 className="animate-spin" /> : <Wrench />}Terapkan rekonsiliasi
            </Button>
          </> : null}>
          <ul className="space-y-2">
            {issueRows.map((k) => (
              <li key={k} className="flex items-start gap-3 text-sm" data-testid={`issue-${k}`}>
                <StatusBadge status={k} label={fmtNum(counts[k])} tone={reportOnly.includes(k) ? 'danger' : 'warning'} />
                <div className="min-w-0">
                  <p className="font-medium text-foreground">{labels[k] || MASALAH[k] || 'Masalah lain'}
                    {reportOnly.includes(k) && <span className="ml-1 font-normal text-[hsl(var(--danger-text))]">· perlu keputusan manual</span>}
                  </p>
                  {hints[k] && <p className="text-xs text-muted-foreground">{hints[k]}</p>}
                </div>
              </li>
            ))}
          </ul>
          {canReconcile && !health?.fixable_issues && (
            <p className="text-sm text-muted-foreground">Tidak ada yang bisa diperbaiki otomatis — sisa masalah perlu Opname atau Penyesuaian resmi.</p>
          )}
          {!canReconcile && (
            <p className="text-sm text-muted-foreground">Akun Anda tidak berwenang menjalankan rekonsiliasi. Ajukan ke Admin Gudang / Admin sistem.</p>
          )}
        </Bagian>
      )}

      {/* Hasil pratinjau */}
      {plan && (
        <Bagian testId="stock-schema-plan" judul="Rencana rekonsiliasi (belum diterapkan)"
          keterangan={`${fmtNum(plan.summary?.rows_normalized)} baris dinormalkan · ${fmtNum(plan.summary?.rows_relocated)} dipindah zona · `
            + `${fmtNum(plan.summary?.rows_merged)} kembar digabung · ${fmtNum(plan.summary?.unresolved_location)} lokasi tak terselesaikan · `
            + `${fmtNum(plan.summary?.manual_attention)} perlu keputusan manual.`}
          alat={(plan.relocations || []).length > 0 ? (
            <TombolUnduh namaBerkas="rencana-pindah-zona" namaLembar="Rencana" baris={plan.relocations} testId="plan-unduh"
              kolom={[
                { label: 'Dari', nilai: (r) => r.from_location_code || r.from_location_id },
                { label: 'Ke', nilai: (r) => r.to_location_code || r.to_location_id },
                { label: 'Qty', nilai: (r) => Number(r.qty || 0) },
              ]} />
          ) : null}>
          <span className="sr-only" data-testid="plan-relocated">{fmtNum(plan.summary?.rows_relocated)}</span>
          {(plan.relocations || []).length > 0 && (
            <div data-testid="plan-relocation-list">
              <TabelData baris={plan.relocations} kunci={(r) => r.row_id} testId="plan-relocation-tabel"
                kolom={[
                  { kunci: 'dari', label: 'Dari', hp: 'judul', isi: (r) => r.from_location_code || r.from_location_id },
                  { kunci: 'ke', label: 'Ke', isi: (r) => r.to_location_code || r.to_location_id },
                  { kunci: 'qty', label: 'Qty', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtNum(r.qty)}</span> },
                ]} />
            </div>
          )}
          {plan.summary?.unresolved_location > 0 && (
            <Notice tone="warning">Sebagian baris tanpa lokasi belum bisa diselesaikan karena zona penyimpanan kanonik belum ada — buat dulu di menu Struktur Gudang.</Notice>
          )}
        </Bagian>
      )}

      {/* Peta lokasi stok (FASE 12) */}
      <Bagian testId="stock-location-map" judul="Peta lokasi stok"
        keterangan="Setiap baris stok harus berada di zona penyimpanan resmi agar terlihat di Penyimpanan, Opname per bin, dan peta gudang. Lantai produksi & karantina QC sengaja dikecualikan."
        alat={locations.length > 0 ? (
          <TombolUnduh namaBerkas="peta-lokasi-stok" namaLembar="Lokasi" baris={locations} testId="stock-loc-unduh"
            kolom={[
              { label: 'Lokasi', nilai: (l) => l.name || l.code || '' },
              { label: 'Kode', nilai: (l) => l.code || '' },
              { label: 'Status', nilai: (l) => (KIND_BADGE[l.kind] || KIND_BADGE.unmapped).label },
              { label: 'Baris', nilai: (l) => Number(l.rows || 0) },
              { label: 'Total qty', nilai: (l) => Number(l.qty || 0) },
            ]} />
        ) : null}>
        <TabelData kolom={kolomLokasi} baris={locations} kunci={(l) => l.location_id} testId="stock-loc-tabel"
          kosong={<EmptyState title="Belum ada baris stok" description="Peta terisi setelah ada stok tercatat." />} />
        {unmappedLocations.length > 0 && (
          <p className="text-sm text-[hsl(var(--warning-text))]" data-testid="stock-loc-unmapped-note">
            {unmappedLocations.length} lokasi bukan zona penyimpanan. Rekonsiliasi akan memindahkan barisnya ke zona kanonik
            sesuai kategori material (total stok tidak berubah).
          </p>
        )}
        {roleTargets.length > 0 && (
          <div>
            <p className="text-sm font-medium text-foreground">Zona tujuan rekonsiliasi</p>
            <dl className="divide-y divide-[var(--glass-border)]">
              {roleTargets.map((r) => (
                <div key={r.role} data-testid={`role-target-${r.role}`}>
                  <BarisDetail label={PERAN[r.role] || 'Lainnya'}>{r.code || r.name}{r.name && r.code ? ` · ${r.name}` : ''}</BarisDetail>
                </div>
              ))}
            </dl>
          </div>
        )}
      </Bagian>

      {/* Detail baris bermasalah */}
      <Bagian testId="stock-schema-details" judul="Detail baris bermasalah"
        keterangan={health?.details_truncated ? 'Hanya sebagian baris ditampilkan — jalankan rekonsiliasi untuk membenahi semuanya.' : undefined}
        alat={details.length > 0 ? (
          <TombolUnduh namaBerkas="baris-stok-bermasalah" namaLembar="Baris bermasalah" baris={details} testId="schema-detail-unduh"
            kolom={[
              { label: 'Kode material', nilai: (d) => d.material_code || '' },
              { label: 'Material', nilai: (d) => d.material_name || '' },
              { label: 'Skema', nilai: (d) => d.schema },
              { label: 'Lokasi', nilai: (d) => lokasiBaris(d) },
              { label: 'Usulan zona', nilai: (d) => d.suggested_location_code || '' },
              { label: 'Qty', nilai: (d) => Number(d.qty || 0) },
              { label: 'Satuan', nilai: (d) => d.unit || '' },
              { label: 'Dicadangkan', nilai: (d) => Number(d.reserved || 0) },
              { label: 'Masalah', nilai: (d) => (d.issues || []).map((i) => MASALAH[i] || labels[i] || i).join(', ') },
            ]} />
        ) : null}>
        <TabelData kolom={kolomDetail} baris={detailsPg.paged} kunci={(d) => d.row_id} testId="schema-detail-tabel"
          kosong={<EmptyState title="Tidak ada baris bermasalah" description="Semua baris stok sudah memakai bentuk kanonik." />} />
        {details.length > 25 && (
          <PaginationLite page={detailsPg.page} totalPages={detailsPg.totalPages} total={detailsPg.total}
            pageSize={detailsPg.pageSize} onPageChange={detailsPg.setPage} />
        )}
      </Bagian>

      {/* Riwayat rekonsiliasi */}
      <Bagian testId="stock-schema-logs" judul="Riwayat rekonsiliasi"
        alat={logs.length > 0 ? (
          <TombolUnduh namaBerkas="riwayat-rekonsiliasi-stok" namaLembar="Riwayat" baris={logs} testId="schema-log-unduh"
            kolom={[
              { label: 'Waktu', nilai: (l) => formatDateTimeID(l.created_at) },
              { label: 'Oleh', nilai: (l) => l.actor?.name || '' },
              { label: 'Dinormalkan', nilai: (l) => Number(l.summary?.rows_normalized || 0) },
              { label: 'Dipindah', nilai: (l) => Number(l.summary?.rows_relocated || 0) },
              { label: 'Digabung', nilai: (l) => Number(l.summary?.rows_merged || 0) },
              { label: 'Status', nilai: (l) => (l.rolled_back_at ? 'Sudah dikembalikan' : 'Berlaku') },
            ]} />
        ) : null}>
        <TabelData kolom={kolomLog} baris={logs} kunci={(l) => l.id} testId="schema-log-tabel"
          kosong={<EmptyState title="Belum pernah direkonsiliasi" description="Riwayat muncul setelah rekonsiliasi pertama dijalankan." />} />
      </Bagian>
    </PageLayout>
  );
}

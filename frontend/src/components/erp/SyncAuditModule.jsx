/**
 * SyncAuditModule — **Kesehatan Sinkronisasi Data** lintas portal (Sesi #20)
 * ═══════════════════════════════════════════════════════════════════════════
 * KENAPA LAYAR INI ADA
 * ───────────────────────────────────────────────────────────────────────────
 * Ketidaksinkronan yang membuat pemilik kehilangan kepercayaan ("id gudang dan
 * marketing tidak sama") baru ketahuan setelah seseorang menjalankan skrip
 * forensik di komputer pengembang. Pemilik tidak punya cara memeriksa sendiri,
 * jadi kerusakan senyap bisa berumur berbulan-bulan.
 *
 * Layar ini memindahkan pengukuran itu ke dalam aplikasi: 5 bagian (A–E),
 * temuan berperingkat, dan perbaikan yang **selalu bisa dipratinjau** sebelum
 * menulis. Angka datang dari `/api/sync-audit/report` (core/sync_audit.py) —
 * dihitung dari data hidup, bukan disalin dari laporan lama.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, 4 kartu angka StatTile (skor + jumlah per tingkat), temuan dan
 * rujukan antar data = tabel dengan unduh Excel/CSV, kode program (nama koleksi, `material_id`) tidak tampil di
 * layar (tetap ikut di berkas unduhan untuk admin), perbaikan diterapkan lewat konfirmasi.
 */
import { useCallback, useEffect, useState } from 'react';
import { ArrowRight, Boxes, Eye, Link2, Loader2, RefreshCw, Wrench } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { toast } from 'sonner';
import { apiGet, apiPost } from '@/lib/api';
import { formatDateTimeID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from './moduleAtoms';

const fmt = (v) => Number(v || 0).toLocaleString('id-ID');

const SEV = {
  CRITICAL: { label: 'Kritis', tone: 'danger' },
  HIGH: { label: 'Tinggi', tone: 'warning' },
  MED: { label: 'Sedang', tone: 'info' },
  INFO: { label: 'Catatan', tone: 'muted' },
};
const sev = (k) => SEV[k] || SEV.INFO;

const VERDICT = {
  HIJAU: { text: 'Sinkron', tone: 'success' },
  KUNING: { text: 'Perlu perhatian', tone: 'warning' },
  MERAH: { text: 'Ada kerusakan tautan', tone: 'danger' },
};

const METRIC_LABEL = {
  orders: 'Pesanan marketing', lines: 'Baris pesanan', lines_linked: 'Baris tertaut',
  lines_linked_pct: 'Baris tertaut (%)', pcs: 'Total pcs', pcs_linked: 'Pcs tertaut',
  pcs_linked_pct: 'Pcs tertaut (%)', orders_ready: 'Pesanan siap dikerjakan',
  orders_partial: 'Pesanan sebagian tertaut', orders_blocked: 'Pesanan terhambat',
  queue_orders: 'Antrean gudang', queue_ready: 'Antrean siap',
  need_ship_not_in_queue: 'Perlu dikirim tapi di luar antrean',
  unmapped_sku_count: 'SKU platform belum dikenal', bridge_mappings: 'Pemetaan jembatan SKU',
  legacy_platform_sku_map: 'Pemetaan cara lama',
  items: 'Item katalog', linked: 'Item tertaut FG', dangling: 'Tautan FG rusak',
  fixable_by_sku: 'Bisa ditautkan lewat SKU', no_link: 'Tanpa tautan FG',
  stock_cache_drift: 'Cache stok melenceng', linked_without_stock_rows: 'Tertaut tanpa baris stok',
  variants: 'Varian model', fg_materials: 'Master FG', variants_with_fg: 'Varian punya FG',
  orphan_variants: 'Varian tanpa FG', fg_without_variant: 'FG tanpa varian',
  variants_with_fg_no_stock: 'Varian belum ada stok', variants_not_in_catalog: 'Varian belum dijual',
  sessions: 'Sesi opname', unknown_material_id: 'Kode material tidak dikenal',
  unknown_location_id: 'Kode lokasi tidak dikenal', stock_dangling_material: 'Baris stok material hilang',
  stock_dangling_location: 'Baris stok lokasi hilang',
  rules_checked: 'Aturan diperiksa', broken_rules: 'Aturan rusak', empty_link_rules: 'Tautan tak pernah diisi',
};
const labelMetrik = (k, bagian) => (bagian === 'D' && k === 'lines' ? 'Baris opname' : METRIC_LABEL[k]) || (k.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase()));
const nilaiMetrik = (k, v) => {
  if (typeof v !== 'number') return String(v);
  if (k.endsWith('_pct')) return `${v.toLocaleString('id-ID', { maximumFractionDigits: 1 })}%`;
  return fmt(v);
};

// Teks perbaikan dari server masih memuat istilah program; diterjemahkan untuk tampilan saja.
const GANTI = [
  [/\(unallocated → pending_fulfillment\)/g, '(belum dialokasikan → menunggu dikirim)'],
  [/\s*lewat SSOT core\/catalog_stock/g, ' dari sumber stok resmi'],
  [/\bSSOT\b/g, 'sumber data resmi'],
  [/\bfulfillment\b/g, 'pemenuhan pesanan'],
  [/Stock Opname/g, 'Stok opname'],
  [/stock opname/gi, 'stok opname'],
  [/Integritas Rujukan Lintas Koleksi/g, 'Keutuhan rujukan antar data'],
  [/option_code\s*=\s*['"]NA['"]/g, 'kode opsi "NA"'],
  [/\boption_code\b/g, 'kode opsi'],
  // "marketing_catalog_items.variant_id kosong di SELURUH 682 dokumen (item katalog → varian)"
  [/\b[a-z0-9_]+\.[a-z0-9_]+ kosong di SELURUH (\d+) dokumen \(([^)]+)\)/g, 'Tautan $2 kosong di seluruh $1 dokumen'],
];
const manusiawi = (s) => GANTI.reduce((t, [re, ke]) => t.replace(re, ke), String(s || ''));

function MetricGrid({ metrics, bagian }) {
  const entries = Object.entries(metrics || {}).filter(
    ([, v]) => typeof v === 'number' || typeof v === 'string');
  if (!entries.length) return null;
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3 lg:grid-cols-4">
      {entries.map(([k, v]) => (
        <div key={k} className="min-w-0">
          <dt className="text-xs text-muted-foreground">{labelMetrik(k, bagian)}</dt>
          <dd className="text-sm font-semibold tabular-nums text-foreground">{nilaiMetrik(k, v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function Bagian({ judul, keterangan, alat, children, testId }) {
  return (
    <GlassCard className="space-y-3 p-4" data-testid={testId}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-lg font-semibold text-foreground">{judul}</h3>
          {keterangan && <p className="text-sm text-muted-foreground">{keterangan}</p>}
        </div>
        {alat && <div className="flex flex-wrap items-center gap-2">{alat}</div>}
      </div>
      {children}
    </GlassCard>
  );
}

function TabelPerbaikan({ repairs, onRan }) {
  const [hasil, setHasil] = useState({});
  const [sibuk, setSibuk] = useState('');

  const run = async (repair, apply) => {
    if (apply) {
      const ok = await confirmDialog({
        title: 'Terapkan perbaikan ini?',
        body: `${manusiawi(repair.label)}. Hasil pratinjau: ${manusiawi(hasil[repair.action]?.message) || '—'}`,
        confirmLabel: 'Terapkan',
      });
      if (!ok) return;
    }
    setSibuk(repair.action);
    try {
      const d = await apiPost('/sync-audit/repair', { action: repair.action, apply });
      setHasil((h) => ({ ...h, [repair.action]: d }));
      if (apply) { toast.success(d.message); onRan(); }
    } catch (e) { toast.error(e.message); } finally { setSibuk(''); }
  };

  return (
    <TabelData baris={repairs} kunci={(r) => r.action} testId="sync-repairs"
      kosong={<p className="text-sm text-muted-foreground">Belum ada perbaikan yang tersedia.</p>}
      kolom={[
        { kunci: 'label', label: 'Perbaikan', hp: 'judul', isi: (r) => (
          <div className="min-w-0 md:max-w-[34rem]" data-testid={`repair-${r.action}`}>
            <p className="font-medium">{manusiawi(r.label)}</p>
            <p className="text-xs text-muted-foreground">{manusiawi(r.explain)}</p>
          </div>) },
        { kunci: 'hasil', label: 'Hasil pratinjau', isi: (r) => (hasil[r.action]
          ? <p className="text-sm md:max-w-[18rem]" data-testid={`repair-result-${r.action}`}>{manusiawi(hasil[r.action].message)}</p>
          : <span className="text-sm text-muted-foreground">Belum dipratinjau</span>) },
        { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" onClick={() => run(r, false)} disabled={!!sibuk}
              data-testid={`repair-preview-${r.action}`}>
              {sibuk === r.action ? <Loader2 className="animate-spin" /> : <Eye />}Pratinjau
            </Button>
            <Button size="sm" onClick={() => run(r, true)} disabled={!!sibuk || !hasil[r.action]}
              title={hasil[r.action] ? 'Terapkan perbaikan' : 'Pratinjau dulu sebelum menerapkan'}
              data-testid={`repair-apply-${r.action}`}>
              <Wrench />Terapkan
            </Button>
          </div>) },
      ]} />
  );
}

export default function SyncAuditModule({ onNavigate }) {
  const [report, setReport] = useState(null);
  const [repairs, setRepairs] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [r, rp] = await Promise.all([
        apiGet('/sync-audit/report'),
        apiGet('/sync-audit/repairs'),
      ]);
      setReport(r); setRepairs(rp.repairs || []);
    } catch (e) { toast.error(`Gagal memuat audit: ${e.message}`); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const v = VERDICT[report?.verdict] || VERDICT.KUNING;
  const score = Number(report?.score || 0);
  const sc = report?.severity_counts || {};
  const findings = report?.findings || [];
  const sections = Object.entries(report?.sections || {});

  return (
    <PageLayout testId="sync-audit-module" title="Sinkronisasi data"
      subtitle="Memeriksa apakah data yang saling menunjuk memang tersambung (Marketing, Katalog, Varian, Stok, Opname)."
      tools={<>
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Periksa ulang" aria-label="Periksa ulang"
          data-testid="refresh-audit">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={report && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="audit-verdict">
          <StatTile label="Skor sinkron" value={score} suffix="/ 100" accent={v.tone === 'danger' ? 'danger' : v.tone}
            sub={<StatusBadge status={report.verdict} label={v.text} tone={v.tone} testId="verdict-badge" />} />
          <StatTile label="Temuan kritis" value={fmt(sc.CRITICAL)} accent={sc.CRITICAL ? 'danger' : 'default'} sub="Tautan rusak yang harus segera diperbaiki" />
          <StatTile label="Temuan tinggi" value={fmt(sc.HIGH)} accent={sc.HIGH ? 'warning' : 'default'} sub="Data tidak bisa dihitung dengan benar" />
          <StatTile label="Temuan sedang" value={fmt(sc.MED)} sub={`Ditambah ${fmt(sc.INFO)} catatan`} />
        </div>
      )}>
      {loading && !report ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Mengukur tautan antar data…</p>
      ) : !report ? (
        <EmptyState title="Hasil pemeriksaan belum bisa dimuat" description="Coba periksa ulang beberapa saat lagi."
          action={{ label: 'Periksa ulang', onClick: load }} />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <p className="min-w-0 flex-1 text-xs text-muted-foreground">
              Diperiksa {report.generated_at ? formatDateTimeID(report.generated_at) : '—'}. Skor turun 25 per temuan kritis,
              10 per tinggi, 3 per sedang.
            </p>
            {onNavigate && (
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" size="sm" onClick={() => onNavigate('sku-bridge')} data-testid="audit-goto-bridge">
                  <Link2 />Jembatan SKU<ArrowRight />
                </Button>
                <Button variant="outline" size="sm" onClick={() => onNavigate('fulfillment')} data-testid="audit-goto-fulfillment">
                  <Boxes />Antrean gudang<ArrowRight />
                </Button>
              </div>
            )}
          </div>

          <Bagian judul={`Temuan (${fmt(findings.length)})`} testId="audit-findings-section"
            alat={findings.length > 0 && (
              <TombolUnduh namaBerkas="sinkronisasi-data-temuan" namaLembar="Temuan" baris={findings} testId="sync-findings-unduh"
                kolom={[
                  { label: 'Tingkat', nilai: (f) => sev(f.severity).label }, { label: 'Temuan', nilai: (f) => manusiawi(f.text) },
                  { label: 'Bagian', nilai: (f) => `${f.section}. ${f.section_title}` }, { label: 'Kode', nilai: (f) => f.code },
                ]} />
            )}>
            <TabelData baris={findings} kunci={(f) => `${f.code}-${f.text}`} testId="audit-findings"
              kosong={<p className="py-6 text-center text-sm text-muted-foreground" data-testid="audit-no-findings">
                Tidak ada ketidaksinkronan yang terdeteksi.</p>}
              kolom={[
                { kunci: 'sev', label: 'Tingkat', hp: 'keterangan', isi: (f) => <StatusBadge status={f.severity} label={sev(f.severity).label} tone={sev(f.severity).tone} /> },
                { kunci: 'text', label: 'Temuan', hp: 'judul', isi: (f) => <p className="text-sm md:max-w-[40rem]">{manusiawi(f.text)}</p> },
                { kunci: 'bagian', label: 'Bagian', isi: (f) => <span className="text-sm text-muted-foreground">{f.section}. {manusiawi(f.section_title)} · {f.code}</span> },
                { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (f) => (f.action === 'sku_bridge' && onNavigate ? (
                  <Button size="sm" variant="outline" onClick={() => onNavigate('sku-bridge')} data-testid={`finding-action-${f.code}`}>
                    Buka Jembatan SKU
                  </Button>) : null) },
              ]} />
          </Bagian>

          {sections.map(([key, sec]) => {
            const rujukan = key === 'E' ? (sec.rows || []) : [];
            const drift = sec.samples?.drift || [];
            return (
              <Bagian key={key} judul={`${key}. ${manusiawi(sec.title)}`} testId={`audit-section-${key}`}
                keterangan={(sec.findings || []).length > 0 ? `${sec.findings.length} temuan di bagian ini.` : null}
                alat={rujukan.length > 0 && (
                  <TombolUnduh namaBerkas="sinkronisasi-data-rujukan" namaLembar="Rujukan" baris={rujukan} testId="sync-rujukan-unduh"
                    kolom={[
                      { label: 'Rujukan', nilai: (r) => r.note }, { label: 'Tabel.field', nilai: (r) => `${r.collection}.${r.field}` },
                      { label: 'Menunjuk ke', nilai: (r) => r.target }, { label: 'Dokumen', nilai: (r) => r.docs },
                      { label: 'Terisi', nilai: (r) => r.filled }, { label: 'Rusak', nilai: (r) => r.dangling },
                    ]} />
                )}>
                <MetricGrid metrics={sec.metrics} bagian={key} />
                {rujukan.length > 0 && (
                  <TabelData baris={rujukan} kunci={(r) => `${r.collection}.${r.field}`} testId="sync-rujukan"
                    kolom={[
                      { kunci: 'note', label: 'Rujukan', hp: 'judul', isi: (r) => <span title={`${r.collection}.${r.field}`}>{r.note}</span> },
                      { kunci: 'docs', label: 'Dokumen', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmt(r.docs)}</span> },
                      { kunci: 'filled', label: 'Terisi', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmt(r.filled)}</span> },
                      { kunci: 'dangling', label: 'Rusak', rata: 'kanan', isi: (r) => (
                        <span className={`font-semibold tabular-nums ${r.dangling ? 'text-[hsl(var(--danger-text))]' : 'text-muted-foreground'}`}>{fmt(r.dangling)}</span>) },
                    ]} />
                )}
                {drift.length > 0 && (
                  <div className="space-y-2">
                    <p className="text-sm font-medium">Contoh cache stok melenceng</p>
                    <TabelData baris={drift.slice(0, 8)} kunci={(d) => d.sku} kolom={[
                      { kunci: 'sku', label: 'SKU', hp: 'judul', isi: (d) => <span className="font-mono text-xs">{d.sku}</span> },
                      { kunci: 'name', label: 'Nama', isi: (d) => d.name },
                      { kunci: 'cache', label: 'Stok katalog', rata: 'kanan', isi: (d) => <span className="tabular-nums">{fmt(d.cache)}</span> },
                      { kunci: 'live', label: 'Stok gudang', rata: 'kanan', isi: (d) => <span className="tabular-nums">{fmt(d.live)}</span> },
                    ]} />
                  </div>
                )}
              </Bagian>
            );
          })}

          <Bagian judul="Perbaikan aman" testId="sync-repairs-section"
            keterangan="Setiap perbaikan bisa dipratinjau lebih dulu (tidak menulis apa pun) dan aman dijalankan berulang. Tidak ada perbaikan yang menebak identitas barang — itu pekerjaan manusia di Jembatan SKU.">
            <TabelPerbaikan repairs={repairs} onRan={load} />
          </Bagian>
        </>
      )}
    </PageLayout>
  );
}

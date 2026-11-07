/**
 * Alert & Reorder (Portal Gudang) — alert stok/rak, usulan titik pesan ulang, dan pembatalan penyesuaian stok.
 *
 * Standar UI/UX v2 (8 Nov 2026): HubTabs bersama (satu kepala, tab rata kiri), tiap tab memakai PageLayout,
 * daftar = tabel (kartu ringkas di HP), unduh Excel/CSV, label Indonesia (dulu "Smart Warehouse", "Undo Stock",
 * "Apply", "Refresh", "Soft-Deleted").
 *
 * Angka yang tampil (diverifikasi 8 Nov 2026 terhadap DB uji):
 *  • Pil "Stok (43)" / "Rak (0)" = jumlah baris /api/warehouse/alerts per `type` (sama dengan isi tabel).
 *  • "1.683 dari 1.726 barang belum punya ambang" = metadata.materials_missing_threshold / materials_total.
 *  • Usulan pesan ulang: server hanya menghitung paling banyak 200 barang aktif pertama (`limit` maks 200);
 *    dulu layar meminta 100 tanpa keterangan. Kini 200 dan kalimat ringkasan menyebut batas itu.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Brain, RefreshCw, RotateCw, Search, ShoppingCart, Undo2 } from 'lucide-react';
import apiFetch from '@/lib/apiFetch';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { useToast } from '@/hooks/use-toast';
import { formatDateTimeID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import HubTabs from './hubs/HubTabs';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';

const angka = (v) => (v === null || v === undefined || v === '' ? '—' : Number(v).toLocaleString('id-ID', { maximumFractionDigits: 2 }));
const SMART_LIMIT = 200; // batas maksimum parameter `limit` di GET /warehouse/smart-reorder

const KEPARAHAN = {
  critical: { label: 'Kritis', tone: 'danger' },
  warning: { label: 'Perlu perhatian', tone: 'warning' },
};
const STATUS_STOK = {
  no_threshold: { label: 'Belum ada ambang', tone: 'muted' },
  critical: { label: 'Kritis', tone: 'danger' },
  low: { label: 'Stok menipis', tone: 'warning' },
  ok: { label: 'Aman', tone: 'success' },
};
const JENIS_PENYESUAIAN = { opname: 'Opname', adjustment: 'Penyesuaian' };

function bukaMenu(hash, hubTab) {
  // Kontrak tab hub yang sudah ada (`hub_tab_<moduleId>`) supaya mendarat langsung di tab yang dituju.
  // Hash dikosongkan dulu bila sudah sama, karena tanpa perubahan hash tidak ada `hashchange`.
  if (hubTab) { try { sessionStorage.setItem(hubTab[0], hubTab[1]); } catch (e) { /* noop */ } }
  if (window.location.hash === `#${hash}`) window.location.hash = '';
  window.location.hash = `#${hash}`;
}

function TombolMuat({ onClick, memuat, testId }) {
  return (
    <Button variant="outline" size="icon" onClick={onClick} disabled={memuat} title="Muat ulang" aria-label="Muat ulang"
      data-testid={testId}>
      <RefreshCw className={memuat ? 'animate-spin' : ''} />
    </Button>
  );
}

function KotakCari({ value, onChange, placeholder, testId }) {
  return (
    <div className="relative w-full sm:w-64">
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
      <Input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="pl-8"
        data-testid={testId} />
    </div>
  );
}

const Memuat = ({ teks }) => <p className="py-10 text-center text-sm text-muted-foreground">{teks}</p>;

// ─── Tab 1: Alert stok & rak ──────────────────────────────────────────────────
function AlertsTab() {
  const { toast } = useToast();
  const [alerts, setAlerts] = useState([]);
  const [meta, setMeta] = useState({});
  const [loading, setLoading] = useState(true);
  const [jenis, setJenis] = useState('');
  const [cari, setCari] = useState('');

  const loadAlerts = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch('/warehouse/alerts?threshold=90');
      setAlerts(res.data || []);
      setMeta(res.metadata || {});
    } catch (err) {
      toast({ title: 'Gagal memuat alert', variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { loadAlerts(); }, [loadAlerts]);

  const nStok = alerts.filter((a) => a.type === 'low_stock').length;
  const nRak = alerts.filter((a) => a.type === 'rack_occupancy').length;
  const q = cari.trim().toLowerCase();
  const baris = alerts
    .filter((a) => !jenis || a.type === jenis)
    .filter((a) => !q || `${a.material_name || ''} ${a.code || a.sku || ''} ${a.message || ''}`.toLowerCase().includes(q));
  const nama = (a) => (a.type === 'rack_occupancy' ? (a.rack_name || a.message) : (a.material_name || a.message));
  const kode = (a) => (a.type === 'rack_occupancy' ? (a.rack_code || '') : (a.code || a.sku || ''));
  const posisi = (a) => (a.type === 'rack_occupancy'
    ? `${angka(a.occupied)} / ${angka(a.total)} slot (${angka(a.occupancy_pct)}%)`
    : `${angka(a.current_qty)} ${a.unit || ''}`);
  const ambang = (a) => (a.type === 'rack_occupancy' ? `${angka(meta.threshold_pct ?? 90)}%` : `${angka(a.alert_at ?? a.reorder_point)} ${a.unit || ''}`);

  const kolom = [
    { kunci: 'barang', label: 'Barang / rak', hp: 'judul', isi: (a) => (
      <div className="min-w-0 md:max-w-[26rem]">
        <p className="truncate font-medium text-foreground" title={nama(a)}>{nama(a)}</p>
        {kode(a) && <p className="truncate text-xs text-muted-foreground">{kode(a)}</p>}
      </div>) },
    { kunci: 'jenis', label: 'Jenis', isi: (a) => (a.type === 'rack_occupancy' ? 'Rak' : 'Stok') },
    { kunci: 'posisi', label: 'Sekarang', rata: 'kanan', isi: (a) => <span className="tabular-nums">{posisi(a)}</span> },
    { kunci: 'ambang', label: 'Ambang', rata: 'kanan', isi: (a) => <span className="tabular-nums">{ambang(a)}</span> },
    { kunci: 'kurang', label: 'Kurang', rata: 'kanan', isi: (a) => (
      a.type === 'low_stock' && a.shortage > 0
        ? <span className="tabular-nums font-medium text-[hsl(var(--danger-text))]">{angka(a.shortage)} {a.unit || ''}</span>
        : <span className="text-muted-foreground">—</span>) },
    { kunci: 'keparahan', label: 'Status', isi: (a) => {
      const k = KEPARAHAN[a.severity] || KEPARAHAN.warning;
      return <StatusBadge status={a.severity} label={k.label} tone={k.tone} />;
    } },
  ];

  const belumAmbang = meta.materials_missing_threshold > 0;
  return (
    <PageLayout testId="wh-smart-alerts" title="Alert gudang"
      subtitle="Barang di bawah ambang stok dan rak yang hampir penuh."
      filters={<>
        <FilterChips hideWhenEmpty={false} value={jenis} onChange={setJenis} testId="wh-smart-alert-jenis"
          options={[
            { key: '', label: 'Semua', count: alerts.length },
            { key: 'low_stock', label: 'Stok', count: nStok },
            { key: 'rack_occupancy', label: 'Rak', count: nRak },
          ]} />
        <KotakCari value={cari} onChange={setCari} placeholder="Cari barang atau kode" testId="wh-smart-alert-cari" />
      </>}
      tools={<>
        <TombolUnduh namaBerkas="alert-gudang" namaLembar="Alert" baris={baris} testId="wh-smart-alert-unduh"
          kolom={[
            { label: 'Barang / rak', nilai: (a) => nama(a) },
            { label: 'Kode', nilai: (a) => kode(a) },
            { label: 'Jenis', nilai: (a) => (a.type === 'rack_occupancy' ? 'Rak' : 'Stok') },
            { label: 'Sekarang', nilai: (a) => (a.type === 'rack_occupancy' ? a.occupancy_pct : a.current_qty) },
            { label: 'Ambang', nilai: (a) => (a.type === 'rack_occupancy' ? (meta.threshold_pct ?? 90) : (a.alert_at ?? a.reorder_point)) },
            { label: 'Kurang', nilai: (a) => (a.type === 'low_stock' ? a.shortage : '') },
            { label: 'Satuan', nilai: (a) => (a.type === 'rack_occupancy' ? '%' : (a.unit || '')) },
            { label: 'Status', nilai: (a) => (KEPARAHAN[a.severity] || KEPARAHAN.warning).label },
          ]} />
        {/* SESI #33 — alert stok tidak jalan buntu: langsung ke Daftar Belanja Mingguan (usul beli + PR). */}
        <Button variant="outline" onClick={() => bukaMenu('wh-shopping-list')} data-testid="wh-smart-goto-shopping">
          <ShoppingCart />Belanja mingguan
        </Button>
        <TombolMuat onClick={loadAlerts} memuat={loading} testId="wh-smart-alerts-refresh" />
      </>}
      summary={!loading && belumAmbang ? (
        // W3 — "tidak ada alert" TIDAK sama dengan "stok aman" bila ambangnya belum diisi.
        <Notice tone="warning" testId="wh-smart-threshold-notice"
          title={`${angka(meta.materials_missing_threshold)} dari ${angka(meta.materials_total)} barang belum punya ambang stok`}
          action={<Button variant="link" className="h-auto p-0" data-testid="wh-smart-goto-thresholds"
            onClick={() => bukaMenu('wh-master=thresholds', ['hub_tab_wh-master', 'thresholds'])}>Isi ambang stok</Button>}>
          {meta.materials_with_threshold === 0
            ? 'Selama ambangnya kosong, alert stok tidak akan pernah muncul walau stok habis.'
            : 'Barang tanpa ambang tidak akan pernah memicu alert. Isi di Master Item › Ambang stok.'}
        </Notice>
      ) : null}>
      {loading && alerts.length === 0 ? <Memuat teks="Memuat alert…" /> : (
        <TabelData kolom={kolom} baris={baris} kunci={(a) => `${a.type}-${a.material_id || a.rack_id || a.message}`}
          testId="wh-smart-alert-tabel"
          kosong={<EmptyState
            title={alerts.length ? 'Tidak ada alert yang cocok'
              : meta.materials_with_threshold === 0 ? 'Belum ada yang bisa dipantau' : 'Tidak ada alert'}
            description={alerts.length ? 'Ubah saringan atau kata pencarian.'
              : meta.materials_with_threshold === 0 ? 'Isi ambang stok dulu di Master Item › Ambang stok, baru alert bisa muncul.'
                : `Tidak ada rak di atas 90%; ${angka(meta.materials_with_threshold)} barang berambang dan semuanya di atas ambang.`} />} />
      )}
    </PageLayout>
  );
}

// ─── Tab 2: Usulan titik pesan ulang ─────────────────────────────────────────
function SmartReorderTab() {
  const { toast } = useToast();
  const [items, setItems] = useState([]);
  const [meta, setMeta] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(null);
  const [saring, setSaring] = useState('');
  const [cari, setCari] = useState('');

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch(`/warehouse/smart-reorder?limit=${SMART_LIMIT}`);
      setItems(res.data || []);
      setMeta(res.metadata || {});
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const applySmartRP = async (item) => {
    setSaving(item.material_id);
    try {
      await apiFetch(`/warehouse/smart-reorder/${item.material_id}`, {
        method: 'PUT',
        body: { reorder_point: item.smart_reorder_point },
      });
      toast({ title: `Titik pesan ulang ${item.name} diubah ke ${item.smart_reorder_point}` });
      loadData();
    } catch (err) {
      toast({ title: 'Gagal menyimpan', description: err.message, variant: 'destructive' });
    } finally {
      setSaving(null);
    }
  };

  const hitung = (fn) => items.filter(fn).length;
  const PENYARING = {
    perlu: (i) => i.needs_update,
    kritis: (i) => i.status === 'critical' || i.status === 'low',
    tanpa: (i) => i.status === 'no_threshold',
  };
  const q = cari.trim().toLowerCase();
  const baris = items
    .filter((i) => !saring || PENYARING[saring](i))
    .filter((i) => !q || `${i.name || ''} ${i.sku || ''}`.toLowerCase().includes(q));
  const status = (i) => STATUS_STOK[i.status] || { label: i.status || '—', tone: 'muted' };

  const kolom = [
    { kunci: 'barang', label: 'Barang', hp: 'judul', isi: (i) => (
      <div className="min-w-0 md:max-w-[22rem]">
        <p className="truncate font-medium text-foreground" title={i.name}>{i.name}</p>
        <p className="truncate text-xs text-muted-foreground">{i.sku}</p>
      </div>) },
    { kunci: 'stok', label: 'Stok', rata: 'kanan', isi: (i) => <span className="tabular-nums">{angka(i.current_qty)} {i.unit}</span> },
    { kunci: 'rp', label: 'Titik pesan ulang', rata: 'kanan', isi: (i) => <span className="tabular-nums">{angka(i.current_reorder_point)}</span> },
    { kunci: 'usulan', label: 'Usulan', rata: 'kanan', isi: (i) => (i.smart_reorder_point > 0
      ? <span className="tabular-nums font-medium text-[hsl(var(--primary))]">{angka(i.smart_reorder_point)}</span>
      : <span className="text-muted-foreground" title="Belum ada pemakaian 30 hari terakhir">—</span>) },
    { kunci: 'pakai', label: 'Pakai/hari', rata: 'kanan', isi: (i) => (i.no_usage_data
      ? <span className="text-muted-foreground" title="Belum ada pemakaian 30 hari terakhir">—</span>
      : <span className="tabular-nums">{angka(i.avg_daily_consumption)}</span>) },
    { kunci: 'status', label: 'Status', isi: (i) => <StatusBadge status={i.status} label={status(i).label} tone={status(i).tone} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (i) => (i.needs_update && i.smart_reorder_point > 0 ? (
      <Button size="sm" variant="outline" onClick={() => applySmartRP(i)} disabled={saving === i.material_id}
        data-testid={`wh-smart-apply-${i.material_id}`}>
        {saving === i.material_id ? <RefreshCw className="animate-spin" /> : <Brain />}Terapkan usulan
      </Button>) : null) },
  ];

  return (
    <PageLayout testId="wh-smart-reorder" title="Usulan pesan ulang"
      subtitle="Usulan titik pesan ulang dari pemakaian 30 hari terakhir, waktu tunggu, dan stok pengaman."
      filters={<>
        <FilterChips hideWhenEmpty={false} value={saring} onChange={setSaring} testId="wh-smart-reorder-saring"
          options={[
            { key: '', label: 'Semua', count: items.length },
            { key: 'perlu', label: 'Perlu diubah', count: hitung(PENYARING.perlu) },
            { key: 'kritis', label: 'Kritis / menipis', count: hitung(PENYARING.kritis) },
            { key: 'tanpa', label: 'Belum ada ambang', count: hitung(PENYARING.tanpa) },
          ]} />
        <KotakCari value={cari} onChange={setCari} placeholder="Cari barang atau kode" testId="wh-smart-reorder-cari" />
      </>}
      tools={<>
        <TombolUnduh namaBerkas="usulan-pesan-ulang" namaLembar="Usulan" baris={baris} testId="wh-smart-reorder-unduh"
          kolom={[
            { label: 'Barang', nilai: (i) => i.name },
            { label: 'Kode', nilai: (i) => i.sku },
            { label: 'Satuan', nilai: (i) => i.unit },
            { label: 'Stok', nilai: (i) => i.current_qty },
            { label: 'Titik pesan ulang', nilai: (i) => i.current_reorder_point },
            { label: 'Usulan', nilai: (i) => i.smart_reorder_point },
            { label: 'Pakai per hari', nilai: (i) => (i.no_usage_data ? '' : i.avg_daily_consumption) },
            { label: 'Waktu tunggu (hari)', nilai: (i) => i.lead_time_days },
            { label: 'Stok pengaman', nilai: (i) => i.safety_stock },
            { label: 'Status', nilai: (i) => status(i).label },
            { label: 'Perlu diubah', nilai: (i) => (i.needs_update ? 'Ya' : 'Tidak') },
          ]} />
        <TombolMuat onClick={loadData} memuat={loading} testId="wh-smart-reorder-refresh" />
      </>}
      summary={!loading && items.length > 0 ? (
        <p className="text-sm text-muted-foreground" data-testid="wh-smart-reorder-ringkas">
          Dihitung untuk {angka(items.length)} barang aktif{items.length >= SMART_LIMIT ? ` (batas ${SMART_LIMIT} barang pertama per hitungan)` : ''};{' '}
          {angka(meta.needs_update || 0)} perlu diubah titik pesan ulangnya.
        </p>
      ) : null}>
      {loading && items.length === 0 ? <Memuat teks="Menghitung usulan…" /> : (
        <TabelData kolom={kolom} baris={baris} kunci={(i) => i.material_id} testId="wh-smart-reorder-tabel"
          kosong={<EmptyState title={items.length ? 'Tidak ada barang yang cocok' : 'Belum ada barang terdaftar'}
            description={items.length ? 'Ubah saringan atau kata pencarian.' : 'Daftarkan barang di Master Item dulu.'} />} />
      )}
    </PageLayout>
  );
}

// ─── Tab 3: Batalkan penyesuaian stok ────────────────────────────────────────
function UndoStockTab() {
  const { toast } = useToast();
  const [data, setData] = useState({ undoable: [], soft_deleted: [] });
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(null);
  const [tampil, setTampil] = useState('undoable');

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch('/warehouse/stock-adjustments/undo-history?days=7');
      setData(res.data || { undoable: [], soft_deleted: [] });
    } catch {
      setData({ undoable: [], soft_deleted: [] });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const doUndo = async (id) => {
    setProcessing(id);
    try {
      await apiFetch(`/warehouse/stock-adjustments/${id}/undo`, { method: 'POST' });
      toast({ title: 'Penyesuaian dibatalkan' });
      loadData();
    } catch (err) {
      toast({ title: 'Gagal membatalkan', description: err.message, variant: 'destructive' });
    } finally {
      setProcessing(null);
    }
  };

  const doRestore = async (id) => {
    setProcessing(id);
    try {
      await apiFetch(`/warehouse/stock-adjustments/${id}/restore`, { method: 'POST' });
      toast({ title: 'Penyesuaian dipulihkan' });
      loadData();
    } catch (err) {
      toast({ title: 'Gagal memulihkan', description: err.message, variant: 'destructive' });
    } finally {
      setProcessing(null);
    }
  };

  const undoable = data.undoable || [];
  const terhapus = data.soft_deleted || [];
  const baris = tampil === 'undoable' ? undoable : terhapus;
  const waktu = (m) => (m.created_at ? formatDateTimeID(m.created_at) : '—');

  const kolom = [
    { kunci: 'barang', label: 'Barang', hp: 'judul', isi: (m) => (
      <div className="min-w-0 md:max-w-[22rem]">
        <p className={`truncate font-medium text-foreground ${tampil === 'soft_deleted' ? 'line-through' : ''}`}
          title={m.material_name || m.sku}>{m.material_name || m.sku}</p>
        <p className="truncate text-xs text-muted-foreground">{m.sku}</p>
      </div>) },
    { kunci: 'jenis', label: 'Jenis', isi: (m) => JENIS_PENYESUAIAN[m.movement_type] || 'Penyesuaian' },
    { kunci: 'qty', label: 'Perubahan', rata: 'kanan', isi: (m) => <span className="tabular-nums">{angka(m.qty)} {m.unit}</span> },
    { kunci: 'waktu', label: 'Waktu', hp: 'keterangan', isi: (m) => <span className="text-sm md:whitespace-nowrap">{waktu(m)}</span> },
    ...(tampil === 'soft_deleted'
      ? [{ kunci: 'oleh', label: 'Dibatalkan oleh', isi: (m) => m.deleted_by || '—' }] : []),
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (m) => (tampil === 'undoable' ? (
      <Button size="sm" variant="outline" onClick={() => doUndo(m.id)} disabled={processing === m.id}
        data-testid={`wh-smart-undo-${m.id}`}>
        {processing === m.id ? <RefreshCw className="animate-spin" /> : <Undo2 />}Batalkan
      </Button>
    ) : (
      <Button size="sm" variant="outline" onClick={() => doRestore(m.id)} disabled={processing === m.id}
        data-testid={`wh-smart-restore-${m.id}`}>
        {processing === m.id ? <RefreshCw className="animate-spin" /> : <RotateCw />}Pulihkan
      </Button>
    )) },
  ];

  return (
    <PageLayout testId="wh-smart-undo" title="Batalkan penyesuaian"
      subtitle="Penyesuaian stok 7 hari terakhir yang masih bisa dibatalkan atau dipulihkan."
      filters={
        <FilterChips hideWhenEmpty={false} value={tampil} onChange={setTampil} testId="wh-smart-undo-tampil"
          options={[
            { key: 'undoable', label: 'Bisa dibatalkan', count: undoable.length },
            { key: 'soft_deleted', label: 'Sudah dibatalkan', count: terhapus.length },
          ]} />
      }
      tools={<>
        <TombolUnduh namaBerkas={tampil === 'undoable' ? 'penyesuaian-bisa-dibatalkan' : 'penyesuaian-dibatalkan'}
          namaLembar="Penyesuaian" baris={baris} testId="wh-smart-undo-unduh"
          kolom={[
            { label: 'Barang', nilai: (m) => m.material_name || m.sku },
            { label: 'Kode', nilai: (m) => m.sku },
            { label: 'Jenis', nilai: (m) => JENIS_PENYESUAIAN[m.movement_type] || 'Penyesuaian' },
            { label: 'Perubahan', nilai: (m) => m.qty },
            { label: 'Satuan', nilai: (m) => m.unit },
            { label: 'Waktu', nilai: (m) => waktu(m) },
            { label: 'Dibatalkan oleh', nilai: (m) => m.deleted_by || '' },
          ]} />
        <TombolMuat onClick={loadData} memuat={loading} testId="wh-smart-undo-refresh" />
      </>}>
      {loading && undoable.length + terhapus.length === 0 ? <Memuat teks="Memuat penyesuaian…" /> : (
        <TabelData kolom={kolom} baris={baris} kunci={(m) => m.id} testId="wh-smart-undo-tabel"
          kosong={<EmptyState
            title={tampil === 'undoable' ? 'Tidak ada penyesuaian yang bisa dibatalkan' : 'Belum ada penyesuaian yang dibatalkan'}
            description="Hanya penyesuaian dan opname 7 hari terakhir yang tampil di sini." />} />
      )}
    </PageLayout>
  );
}

export default function WarehouseSmartModule(props) {
  const tabs = useMemo(() => [
    { key: 'alerts', label: 'Alert gudang', Component: AlertsTab },
    { key: 'reorder', label: 'Usulan pesan ulang', Component: SmartReorderTab },
    { key: 'undo', label: 'Batalkan penyesuaian', Component: UndoStockTab },
  ], []);
  return (
    <HubTabs {...props} hubId="warehouse-smart" title="Alert & Reorder"
      subtitle="Alert stok dan rak, usulan titik pesan ulang, dan pembatalan penyesuaian stok."
      tabs={tabs} />
  );
}

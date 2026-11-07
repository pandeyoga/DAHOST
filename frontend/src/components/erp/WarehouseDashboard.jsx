/**
 * Dashboard Gudang — ringkasan stok, penerimaan terbuka, barang di bawah ambang, dan isi rak.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, StatTile berketerangan, daftar = tabel + unduh, warna token.
 *
 * Verifikasi angka (keluhan owner: kartu dashboard menyesatkan) — 8 Nov 2026 terhadap DB uji:
 *  • "Total SKU" dulu = jumlah SEMUA baris saldo stok (termasuk baris minus/nol) dari /material-stock/summary
 *    → tampil "1" padahal satu-satunya baris berisi −1 (tidak ada stok sama sekali). Kini "Baris stok terisi"
 *    = `total_items` /api/wms/legacy/dashboard-kpi (baris barang × lokasi dengan qty > 0) → 0.
 *  • "Lokasi Aktif" dulu mencampur jumlah zona WMS dengan lokasi berstok. Kini "Lokasi berisi stok"
 *    = `total_locations` dari endpoint yang sama (lokasi yang punya qty > 0).
 *  • "Stok Kritis 86" dulu menjumlah /materials?low_stock=true (43) + /materials/reorder-alerts (43) —
 *    keduanya daftar 43 barang YANG SAMA, jadi terhitung dua kali dan daftar berisi pasangan LOW/REORDER
 *    kembar. Kini digabung per barang (unik) → 43 "Di bawah ambang stok".
 *  • Kartu antrean WMS (masuk/keluar) & isi rak hanya tampil bila Struktur Gudang punya gedung.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { AlertTriangle, ArrowRight, RefreshCw } from 'lucide-react';
import { toast } from '../ui/sonner';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { GlassCard } from '@/components/ui/glass';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;
const angka = (v) => (v === null || v === undefined || v === '' ? '—' : Number(v).toLocaleString('id-ID', { maximumFractionDigits: 2 }));
const JENIS_BARANG = { fabric: 'Kain', yarn: 'Benang', accessory: 'Aksesoris', packaging: 'Kemasan', interlining: 'Kain keras', fg: 'Produk jadi' };
const BARIS_RINGKAS = 10;

function bukaMenu(hash) {
  if (window.location.hash === `#${hash}`) window.location.hash = '';
  window.location.hash = `#${hash}`;
}

function nadaIsi(pct) {
  if (pct >= 85) return { tone: 'danger', bar: 'bg-[hsl(var(--destructive))]', label: 'Hampir penuh' };
  if (pct >= 55) return { tone: 'warning', bar: 'bg-[hsl(var(--warning))]', label: 'Sedang' };
  return { tone: 'success', bar: 'bg-[hsl(var(--success))]', label: 'Longgar' };
}

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

export default function WarehouseDashboard({ token }) {
  const [kpi, setKpi] = useState(null);
  const [lowStock, setLowStock] = useState([]);
  const [reorderAlerts, setReorderAlerts] = useState([]);
  const [stockByLoc, setStockByLoc] = useState([]);
  const [loading, setLoading] = useState(true);
  // ── WMS multi-gedung ───────────────────────────────────────────────────────
  const [wmsBuildings, setWmsBuildings] = useState([]);
  const [selectedBldg, setSelectedBldg] = useState('');
  const [wmsPending, setWmsPending] = useState({ pending_inbound: 0, pending_outbound_rm: 0, pending_outbound_fg: 0, total_pending: 0 });
  const [occupancyAlerts, setOccupancyAlerts] = useState({ critical: [], warning: [], total_alerts: 0, critical_count: 0, warning_count: 0 });
  const hdrs = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  const loadWMS = useCallback(async () => {
    try {
      const buildingFilter = selectedBldg ? `?building_id=${selectedBldg}` : '';
      const [bRes, pRes, aRes] = await Promise.all([
        fetch(`${API}/api/wms/buildings`, { headers: hdrs }).then(r => r.json()),
        fetch(`${API}/api/wms/pending/summary${buildingFilter}`, { headers: hdrs }).then(r => r.json()),
        fetch(`${API}/api/wms/alerts/occupancy?threshold=90${selectedBldg ? `&building_id=${selectedBldg}` : ''}`, { headers: hdrs }).then(r => r.json()),
      ]);
      const buildings = Array.isArray(bRes) ? bRes : [];
      setWmsBuildings(buildings);
      setWmsPending(pRes || {});
      setOccupancyAlerts(aRes || { critical: [], warning: [], total_alerts: 0 });

      // Isi rak kanonik (SSOT wh_*): utilisasi bin per zona dari /api/wms/map/{building}
      const targets = selectedBldg ? buildings.filter(b => b.id === selectedBldg) : buildings;
      const maps = await Promise.all(
        targets.map(b =>
          fetch(`${API}/api/wms/map/${b.id}`, { headers: hdrs })
            .then(r => (r.ok ? r.json() : null))
            .catch(() => null)
        )
      );
      const tiles = [];
      for (const m of maps) {
        if (!m || !Array.isArray(m.zones)) continue;
        for (const z of m.zones) {
          tiles.push({
            location_id: z.id,
            gedung: m.name || m.code || '',
            name: `${m.code || m.name || ''} · ${z.code || z.name || ''}`,
            total_positions: z.total_positions || 0,
            occupied: z.occupied_positions || 0,
            pct: z.occupancy_pct || 0,
          });
        }
      }
      tiles.sort((a, b) => b.pct - a.pct);
      setStockByLoc(tiles);
    } catch { /* senyap: bagian WMS opsional */ }
  }, [hdrs, selectedBldg]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [kpiRes, lowRes, reorderRes] = await Promise.allSettled([
        axios.get(`${API}/api/wms/legacy/dashboard-kpi`, { headers: hdrs }),
        axios.get(`${API}/api/rahaza/materials?low_stock=true`, { headers: hdrs }),
        axios.get(`${API}/api/rahaza/materials/reorder-alerts`, { headers: hdrs }),
      ]);
      setKpi(kpiRes.status === 'fulfilled' ? (kpiRes.value.data || {}) : null);
      if (lowRes.status === 'fulfilled') setLowStock(Array.isArray(lowRes.value.data) ? lowRes.value.data : []);
      if (reorderRes.status === 'fulfilled') setReorderAlerts(Array.isArray(reorderRes.value.data) ? reorderRes.value.data : []);
    } catch (err) {
      toast.error('Gagal memuat data dashboard');
    } finally {
      setLoading(false);
    }
  }, [hdrs]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadWMS(); }, [loadWMS]);

  // Gabungan unik per barang: dua endpoint mengembalikan barang yang sama (dulu dijumlah → angka ganda).
  const kritis = useMemo(() => {
    const peta = new Map();
    for (const m of [...lowStock, ...reorderAlerts]) {
      const k = m.id || m.code;
      if (!k || peta.has(k)) continue;
      const min = Number(m.alert_at ?? m.min_stock_qty ?? m.min_stock ?? 0);
      const qty = Number(m.current_qty || 0);
      peta.set(k, { ...m, _min: min, _kurang: m.shortage !== undefined ? Number(m.shortage) : Math.max(0, min - qty) });
    }
    return [...peta.values()].sort((a, b) => b._kurang - a._kurang);
  }, [lowStock, reorderAlerts]);

  const adaGedung = wmsBuildings.length > 0;
  const namaGedung = selectedBldg ? wmsBuildings.find(b => b.id === selectedBldg)?.name : '';
  const rakAlert = [...(occupancyAlerts.critical || []), ...(occupancyAlerts.warning || [])];

  const kolomKritis = [
    { kunci: 'barang', label: 'Barang', hp: 'judul', isi: (m) => (
      <div className="min-w-0 md:max-w-[24rem]">
        <p className="truncate font-medium text-foreground" title={m.name}>{m.name}</p>
        <p className="truncate text-xs text-muted-foreground">{m.code}</p>
      </div>) },
    { kunci: 'jenis', label: 'Jenis', isi: (m) => JENIS_BARANG[m.type] || m.category_name || '—' },
    { kunci: 'stok', label: 'Stok', rata: 'kanan', isi: (m) => <span className="tabular-nums">{angka(m.current_qty ?? 0)} {m.unit}</span> },
    { kunci: 'min', label: 'Ambang', rata: 'kanan', isi: (m) => <span className="tabular-nums">{m._min ? `${angka(m._min)} ${m.unit}` : '—'}</span> },
    { kunci: 'kurang', label: 'Kurang', rata: 'kanan', isi: (m) => (m._kurang > 0
      ? <span className="tabular-nums font-medium text-[hsl(var(--danger-text))]">{angka(m._kurang)} {m.unit}</span>
      : <span className="text-muted-foreground">—</span>) },
  ];

  const kolomRak = [
    { kunci: 'zona', label: 'Gedung · zona', hp: 'judul', isi: (z) => <span className="font-medium">{z.name}</span> },
    { kunci: 'isi', label: 'Bin terisi', rata: 'kanan', isi: (z) => <span className="tabular-nums">{angka(z.occupied)} / {angka(z.total_positions)}</span> },
    { kunci: 'pct', label: 'Terisi', isi: (z) => {
      const n = nadaIsi(z.pct || 0);
      return (
        <div className="flex items-center gap-2">
          <div className="h-1.5 w-24 overflow-hidden rounded-full bg-foreground/10" aria-hidden="true">
            <div className={`h-full rounded-full ${n.bar}`} style={{ width: `${Math.min(100, z.pct || 0)}%` }} />
          </div>
          <span className="tabular-nums text-sm">{angka(z.pct || 0)}%</span>
        </div>);
    } },
    { kunci: 'status', label: 'Status', isi: (z) => { const n = nadaIsi(z.pct || 0); return <StatusBadge status={n.tone} label={n.label} tone={n.tone} />; } },
  ];

  const kolomRakAlert = [
    { kunci: 'rak', label: 'Rak', hp: 'judul', isi: (r) => (
      <div className="min-w-0">
        <p className="font-medium tabular-nums">{r.building_code}-{r.zone_code}-{r.rack_code}</p>
        {r.rack_name && <p className="truncate text-xs text-muted-foreground">{r.rack_name}</p>}
      </div>) },
    { kunci: 'pct', label: 'Terisi', rata: 'kanan', isi: (r) => <span className="tabular-nums">{angka(r.occupancy_pct)}%</span> },
    { kunci: 'kosong', label: 'Slot kosong', rata: 'kanan', isi: (r) => <span className="tabular-nums">{angka(r.free_slots)}</span> },
    { kunci: 'status', label: 'Status', isi: (r) => (r.severity === 'critical'
      ? <StatusBadge status="critical" label="Kritis (≥ 95%)" tone="danger" />
      : <StatusBadge status="warning" label="Perlu perhatian" tone="warning" />) },
  ];

  return (
    <PageLayout testId="warehouse-dashboard" title="Dashboard Gudang"
      subtitle="Ringkasan stok, penerimaan terbuka, barang di bawah ambang stok, dan isi rak."
      filters={adaGedung ? (
        <SmartNativeSelect data-testid="warehouse-building-selector" value={selectedBldg}
          onChange={e => setSelectedBldg(e.target.value)} className="w-full" wrapperClassName="w-full sm:w-56" title="Saring antrean & isi rak per gedung">
          <option value="">Semua gedung</option>
          {wmsBuildings.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
        </SmartNativeSelect>
      ) : null}
      tools={
        <Button variant="outline" size="icon" onClick={() => { load(); loadWMS(); }} disabled={loading}
          title="Muat ulang" aria-label="Muat ulang" data-testid="dashboard-refresh-btn">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      }
      summary={
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="dashboard-kpi">
            <StatTile label="Baris stok terisi" testId="kpi-baris-stok"
              value={kpi ? angka(kpi.total_items) : '—'}
              sub={kpi ? 'Barang × lokasi dengan stok > 0.' : 'Gagal memuat ringkasan stok.'} />
            <StatTile label="Lokasi berisi stok" testId="kpi-lokasi"
              value={kpi ? angka(kpi.total_locations) : '—'}
              sub={kpi ? 'Lokasi dengan stok > 0.' : 'Gagal memuat ringkasan stok.'} />
            <StatTile label="Penerimaan terbuka" testId="kpi-gr"
              value={kpi ? angka(kpi.pending_gr) : '—'} accent={kpi?.pending_gr > 0 ? 'warning' : 'default'}
              sub="GR draf / diperiksa / diproses." />
            <StatTile label="Di bawah ambang stok" testId="kpi-kritis"
              value={angka(kritis.length)} accent={kritis.length > 0 ? 'danger' : 'default'}
              sub="Stok di bawah minimum / titik pesan ulang." />
          </div>
          {adaGedung && (
            <p className="text-sm text-muted-foreground" data-testid="wms-pending-strip">
              Antrean gudang{namaGedung ? ` ${namaGedung}` : ' (semua gedung)'}:{' '}
              <span className="font-medium text-foreground tabular-nums">{angka(wmsPending.pending_inbound ?? 0)}</span> menunggu masuk ·{' '}
              <span className="font-medium text-foreground tabular-nums">{angka(wmsPending.pending_outbound_rm ?? 0)}</span> menunggu keluar bahan ·{' '}
              <span className="font-medium text-foreground tabular-nums">{angka(wmsPending.pending_outbound_fg ?? 0)}</span> menunggu keluar produk jadi.
            </p>
          )}
          {occupancyAlerts.total_alerts > 0 && (
            <Notice tone="danger" icon={AlertTriangle} testId="dashboard-occupancy-alert"
              title={`${angka(occupancyAlerts.total_alerts)} rak terisi 90% atau lebih${occupancyAlerts.critical_count > 0 ? ` · ${angka(occupancyAlerts.critical_count)} kritis (≥ 95%)` : ''}`}>
              Pindahkan sebagian isi rak atau siapkan rak baru sebelum penerimaan berikutnya.
            </Notice>
          )}
        </div>
      }>
      <Bagian testId="low-stock-panel" judul={`Di bawah ambang stok (${angka(kritis.length)})`}
        keterangan={kritis.length > BARIS_RINGKAS
          ? `${BARIS_RINGKAS} barang dengan kekurangan terbesar. Unduhan berisi semua ${angka(kritis.length)} barang.`
          : 'Barang yang perlu dibeli atau diisi ulang.'}
        alat={<>
          <TombolUnduh namaBerkas="stok-di-bawah-ambang" namaLembar="Di bawah ambang" baris={kritis} testId="low-stock-unduh"
            kolom={[
              { label: 'Kode', nilai: (m) => m.code },
              { label: 'Barang', nilai: (m) => m.name },
              { label: 'Jenis', nilai: (m) => JENIS_BARANG[m.type] || m.category_name || '' },
              { label: 'Stok', nilai: (m) => Number(m.current_qty || 0) },
              { label: 'Ambang', nilai: (m) => m._min || '' },
              { label: 'Kurang', nilai: (m) => m._kurang || '' },
              { label: 'Satuan', nilai: (m) => m.unit },
            ]} />
          <Button variant="outline" onClick={() => bukaMenu('warehouse-smart')} data-testid="low-stock-lihat-semua">
            Alert & Reorder<ArrowRight />
          </Button>
        </>}>
        {loading && kritis.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">Memuat…</p>
        ) : (
          <TabelData kolom={kolomKritis} baris={kritis.slice(0, BARIS_RINGKAS)} kunci={(m) => m.id || m.code}
            testId="low-stock-tabel"
            kosong={<EmptyState title="Tidak ada barang di bawah ambang"
              description="Hanya barang yang sudah punya stok minimum atau titik pesan ulang yang dipantau." />} />
        )}
      </Bagian>

      {rakAlert.length > 0 && (
        <Bagian testId="rak-hampir-penuh" judul={`Rak hampir penuh (${angka(rakAlert.length)})`}
          keterangan="Rak dengan isi 90% atau lebih."
          alat={<TombolUnduh namaBerkas="rak-hampir-penuh" namaLembar="Rak" baris={rakAlert} testId="rak-alert-unduh"
            kolom={[
              { label: 'Rak', nilai: (r) => `${r.building_code}-${r.zone_code}-${r.rack_code}` },
              { label: 'Nama rak', nilai: (r) => r.rack_name || '' },
              { label: 'Terisi (%)', nilai: (r) => r.occupancy_pct },
              { label: 'Slot kosong', nilai: (r) => r.free_slots },
              { label: 'Status', nilai: (r) => (r.severity === 'critical' ? 'Kritis' : 'Perlu perhatian') },
            ]} />}>
          <TabelData kolom={kolomRakAlert} baris={rakAlert} kunci={(r) => r.rack_id} testId="rak-alert-tabel" />
        </Bagian>
      )}

      <Bagian testId="stock-heatmap" judul="Isi rak per zona"
        keterangan={adaGedung ? 'Bin terisi dibanding seluruh bin di tiap zona (Struktur Gudang).' : 'Diambil dari Struktur Gudang.'}
        alat={stockByLoc.length > 0 ? (
          <TombolUnduh namaBerkas="isi-rak-per-zona" namaLembar="Zona" baris={stockByLoc} testId="heatmap-unduh"
            kolom={[
              { label: 'Gedung · zona', nilai: (z) => z.name },
              { label: 'Bin terisi', nilai: (z) => z.occupied },
              { label: 'Total bin', nilai: (z) => z.total_positions },
              { label: 'Terisi (%)', nilai: (z) => z.pct },
            ]} />
        ) : null}>
        <TabelData kolom={kolomRak} baris={stockByLoc} kunci={(z) => z.location_id} testId="heatmap-tabel"
          kosong={<EmptyState title={adaGedung ? 'Belum ada zona' : 'Belum ada gedung'}
            description={adaGedung ? 'Tambahkan zona dan rak di Struktur Gudang.' : 'Buat gedung, zona, dan rak di Struktur Gudang agar isi rak bisa dipantau.'}
            action={<Button variant="outline" onClick={() => bukaMenu('wh-structure')}>Buka Struktur Gudang</Button>} />} />
      </Bagian>
    </PageLayout>
  );
}

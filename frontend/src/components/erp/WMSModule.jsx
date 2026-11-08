/**
 * WMS Module — bagian gudang yang dibuka per menu lewat prop `section` (registry `withProps`):
 *   structure → Struktur Gudang (wh-structure) · units → Satuan & Konversi (wh-units)
 *   audit → Audit Trail (wh-audit) · receiving → Scan Gudang (wh-scan, tautan lama)
 *   PositionsTab (ekspor bernama) → tab "Posisi & cari" di hub Stok & Akurasi.
 *
 * Standar UI/UX v2 (8 Nov 2026): setiap bagian = PageLayout (kepala ikon besar + `p-6` dihapus), daftar kartu
 * (gedung, zona, rak, satuan, antrean scan) → tabel (kartu ringkas di HP), unduh Excel/CSV di setiap tabel,
 * semua form (gedung/zona/rak, satuan, konversi, kalkulator, scan) → FormPopup, analisa AI → DetailPopup,
 * konfirmasi → confirmDialog, tanggal → PeriodPicker, kode mentah (count/length, adjust_in, occupied,
 * pending) → label Indonesia. API, field, dan validasi tidak berubah.
 * Tab "Dashboard" lama (DashboardTab) dihapus dari berkas: sudah tidak dirender sejak Fase E (kode mati).
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Plus, Pencil, Ban, RefreshCw, Scan, MapPin, AlertCircle, ChevronRight, Printer, Calculator,
  MoreHorizontal, Sparkles, Search,
} from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { GlassCard } from '@/components/ui/glass';
import PaginationLite from '@/components/ui/pagination-lite';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { formatDateTimeID } from '@/lib/format';
// Sprint A.1: UniversalScanner SSOT replaces inline ScannerInput
import UniversalScanner from './scanner/UniversalScanner';
import useUomOptions from '@/hooks/useUomOptions';
import { UomSelect, UomConversionHint } from './uom/UomPicker';
import StorageLocationSelect from './StorageLocationSelect';
import { MATERIAL_UNITS } from '@/lib/uom';
import ImportExportToolbar from './ImportExportToolbar';
import PeriodPicker, { ALL_TIME, PERIOD_PRESETS } from './finance/PeriodPicker';
import PageLayout from './layout/PageLayout';
import HubTabs from './hubs/HubTabs';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;

const fmt = (n) => new Intl.NumberFormat('id-ID').format(n ?? 0);

const ZONE_TYPE_LABELS = { rm: 'Bahan baku', fg: 'Produk jadi', wip: 'Barang setengah jadi', transit: 'Transit', general: 'Umum' };
const ZONE_TYPE_TONE = { rm: 'primary', fg: 'success', wip: 'warning', transit: 'info', general: 'muted' };
const UNIT_CATEGORY_LABELS = {
  weight: 'Berat', length: 'Panjang', count: 'Hitungan', roll: 'Gulungan', pack: 'Kemasan', volume: 'Volume', other: 'Lainnya',
};
const kategoriSatuan = (c) => UNIT_CATEGORY_LABELS[c] || 'Lainnya';
const POSITION_STATUS = { occupied: { label: 'Terisi', tone: 'success' }, empty: { label: 'Kosong', tone: 'muted' } };
const MOVE_STATUS = {
  pending: { label: 'Menunggu', tone: 'warning' }, partial: { label: 'Sebagian', tone: 'info' },
  confirmed: { label: 'Selesai', tone: 'success' }, cancelled: { label: 'Dibatalkan', tone: 'muted' },
};
const moveStatus = (s) => MOVE_STATUS[s] || { label: s ? 'Lainnya' : '—', tone: 'muted' };
const ARAH = { adjust_in: { label: 'Lebih', tone: 'success' }, adjust_out: { label: 'Kurang', tone: 'danger' } };
const arahDari = (d) => ARAH[d] || { label: d ? 'Lainnya' : '—', tone: 'muted' };

const SelectPenyaring = ({ lebar = 'sm:w-44', className, ...props }) => (
  <SmartNativeSelect className={className || 'w-full'} wrapperClassName={`w-full ${lebar}`} {...props} />
);

function Alat({ children }) {
  return <div className="ml-auto flex shrink-0 items-center gap-2">{children}</div>;
}

function MuatUlang({ onClick, loading, testId }) {
  return (
    <Button variant="outline" size="icon" onClick={onClick} disabled={loading} title="Muat ulang" aria-label="Muat ulang" data-testid={testId}>
      <RefreshCw className={loading ? 'animate-spin' : ''} />
    </Button>
  );
}

// ─── Scanner Input Wrapper (Sprint A.1: uses UniversalScanner inline) ──────
// Backward-compat shim — converts onScan(value) + loading to UniversalScanner inline
function ScannerInput({ placeholder = 'Scan atau ketik barcode', onScan, loading, className = '' }) {
  return (
    <div className={`relative ${className}`}>
      <UniversalScanner
        variant="inline"
        onScan={(code) => onScan(code)}
        placeholder={placeholder}
        disabled={loading}
        autoFocus
        data-testid="scanner-input"
      />
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────────
// STRUKTUR GUDANG (wh-structure)
// ──────────────────────────────────────────────────────────────────────────────
const JUDUL_TIPE = { building: 'gedung', zone: 'zona', rack: 'rak' };

function StructureTab({ token }) {
  const [buildings, setBuildings] = useState([]);
  const [zones, setZones] = useState([]);
  const [racks, setRacks] = useState([]);
  const [selectedBldg, setSelectedBldg] = useState(null);
  const [selectedZone, setSelectedZone] = useState(null);
  const [view, setView] = useState('buildings'); // buildings | zones | racks
  const [modal, setModal] = useState(null); // {type: 'building'|'zone'|'rack', data: null|obj}
  const [saving, setSaving] = useState(false);
  const [galat, setGalat] = useState('');
  const [form, setForm] = useState({});
  const [loading, setLoading] = useState(false);
  // 2026-11-02 (K9): pilihan lokasi gudang untuk menautkan zona (`zone.location_id`, dibaca mesin opname)
  const [locations, setLocations] = useState([]);
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  const loadBuildings = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/wms/buildings`, { headers });
      const d = await r.json(); setBuildings(Array.isArray(d) ? d : []);
    } finally { setLoading(false); }
  }, [headers]);

  const loadZones = useCallback(async (bldgId) => {
    const r = await fetch(`${API}/api/wms/zones?building_id=${bldgId}`, { headers });
    const d = await r.json(); setZones(Array.isArray(d) ? d : []);
  }, [headers]);

  const loadRacks = useCallback(async (zoneId) => {
    const r = await fetch(`${API}/api/wms/racks?zone_id=${zoneId}`, { headers });
    const d = await r.json(); setRacks(Array.isArray(d) ? d : []);
  }, [headers]);

  useEffect(() => { loadBuildings(); }, [loadBuildings]);
  useEffect(() => {
    fetch(`${API}/api/rahaza/locations`, { headers }).then(r => (r.ok ? r.json() : []))
      // 2026-11-07 (Tahap 5): zona gudang hanya ditautkan ke lokasi penyimpan — ruang kantor tidak ditawarkan
      .then(d => setLocations((Array.isArray(d) ? d : []).filter(l => l.type !== 'kantor' && l.active !== false))).catch(() => setLocations([]));
  }, [headers]);

  function openBldgModal(data = null) { setGalat(''); setForm(data || { code: '', name: '', address: '' }); setModal({ type: 'building', data }); }
  function openZoneModal(data = null) { setGalat(''); setForm(data ? { ...data, location_id: data.location_id || '' } : { code: '', name: '', zone_type: 'rm', building_id: selectedBldg, location_id: '' }); setModal({ type: 'zone', data }); }
  function openRackModal(data = null) { setGalat(''); setForm(data || { code: '', name: '', zone_id: selectedZone, num_shelves: 4, slots_per_shelf: 6, capacity_per_slot: 0, capacity_unit: '' }); setModal({ type: 'rack', data }); }

  async function handleSave() {
    setSaving(true); setGalat('');
    try {
      const t = modal.type;
      const url = modal.data
        ? `${API}/api/wms/${t}s/${modal.data.id}`
        : `${API}/api/wms/${t}s`;
      const method = modal.data ? 'PUT' : 'POST';
      const r = await fetch(url, { method, headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(form) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Gagal menyimpan');
      toast.success(d.message || 'Berhasil');
      setModal(null);
      if (t === 'building') loadBuildings();
      if (t === 'zone') loadZones(selectedBldg);
      if (t === 'rack') loadRacks(selectedZone);
    } catch (e) { setGalat(e.message); toast.error(e.message); }
    finally { setSaving(false); }
  }

  async function handleDelete(type, row) {
    const ok = await confirmDialog({
      title: `Nonaktifkan ${JUDUL_TIPE[type]} ${row.code}?`,
      body: `"${row.name}" tidak lagi dipakai untuk penempatan barang.`,
      confirmLabel: 'Nonaktifkan', danger: true,
    });
    if (!ok) return;
    try {
      const r = await fetch(`${API}/api/wms/${type}s/${row.id}`, { method: 'DELETE', headers });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail);
      toast.success(d.message || 'Berhasil');
      if (type === 'building') loadBuildings();
      if (type === 'zone') loadZones(selectedBldg);
      if (type === 'rack') loadRacks(selectedZone);
    } catch (e) { toast.error(e.message); }
  }

  const bukaGedung = (b) => { setSelectedBldg(b.id); loadZones(b.id); setView('zones'); };
  const bukaZona = (z) => { setSelectedZone(z.id); loadRacks(z.id); setView('racks'); };
  const cetakLabel = (rack) => window.open(`${API}/api/wms/racks/${rack.id}/labels-pdf?token=${encodeURIComponent(token)}`, '_blank');
  const namaGedung = buildings.find(b => b.id === selectedBldg)?.name;
  const namaZona = zones.find(z => z.id === selectedZone)?.name;

  const kolomGedung = [
    { kunci: 'code', label: 'Kode', hp: 'judul', isi: (b) => <span className="tabular-nums font-medium" data-testid="building-card">{b.code}</span> },
    { kunci: 'name', label: 'Nama', hp: 'keterangan', isi: (b) => b.name },
    { kunci: 'address', label: 'Alamat', hp: false, isi: (b) => <span className="text-muted-foreground">{b.address || '—'}</span> },
    { kunci: 'zone_count', label: 'Zona', rata: 'kanan', isi: (b) => <span className="tabular-nums">{fmt(b.zone_count)}</span> },
    { kunci: 'rack_count', label: 'Rak', rata: 'kanan', isi: (b) => <span className="tabular-nums">{fmt(b.rack_count)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (b) => (
      <Button variant="ghost" size="icon-sm" onClick={() => openBldgModal(b)} title="Ubah gedung" aria-label={`Ubah gedung ${b.code}`}><Pencil /></Button>) },
  ];
  const kolomZona = [
    { kunci: 'code', label: 'Kode', hp: 'judul', isi: (z) => <span className="tabular-nums font-medium" data-testid="zone-card">{z.code}</span> },
    { kunci: 'name', label: 'Nama', hp: 'keterangan', isi: (z) => z.name },
    { kunci: 'zone_type', label: 'Jenis zona', hp: false, isi: (z) => (
      <StatusBadge status={z.zone_type} label={ZONE_TYPE_LABELS[z.zone_type] || 'Umum'} tone={ZONE_TYPE_TONE[z.zone_type] || 'muted'} />) },
    { kunci: 'rack_count', label: 'Rak', rata: 'kanan', isi: (z) => <span className="tabular-nums">{fmt(z.rack_count)}</span> },
    { kunci: 'location', label: 'Lokasi gudang (opname)', isi: (z) => (
      <span data-testid="zone-location" className={z.location_id ? 'text-foreground' : 'text-[hsl(var(--warning-text))]'}>
        {z.location_id ? `${z.location_code || ''} ${z.location_name || ''}`.trim() : 'Belum ditautkan — opname tidak menjangkau rak zona ini'}
      </span>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (z) => (
      <div className="inline-flex items-center gap-1">
        <Button variant="ghost" size="icon-sm" onClick={() => openZoneModal(z)} title="Ubah zona" aria-label={`Ubah zona ${z.code}`}><Pencil /></Button>
        <Button variant="ghost" size="icon-sm" onClick={() => handleDelete('zone', z)} title="Nonaktifkan zona" aria-label={`Nonaktifkan zona ${z.code}`}><Ban /></Button>
      </div>) },
  ];
  const kolomRak = [
    { kunci: 'code', label: 'Kode', hp: 'judul', isi: (r) => <span className="tabular-nums font-medium" data-testid="rack-card">{r.code}</span> },
    { kunci: 'name', label: 'Nama', hp: 'keterangan', isi: (r) => r.name },
    { kunci: 'susunan', label: 'Tingkat × slot', hp: false, rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.num_shelves} × {r.slots_per_shelf}</span> },
    { kunci: 'total', label: 'Total posisi', hp: false, rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmt(r.total_positions)}</span> },
    { kunci: 'terisi', label: 'Terisi', rata: 'kanan', isi: (r) => (
      <span className="tabular-nums">{fmt(r.occupied_positions)} <span className="text-muted-foreground">({r.occupancy_pct ?? 0}%)</span></span>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <div className="inline-flex items-center gap-1">
        <Button variant="ghost" size="icon-sm" onClick={() => cetakLabel(r)} data-testid="print-rack-labels-btn"
          title="Cetak label barcode semua posisi di rak ini" aria-label={`Cetak label rak ${r.code}`}><Printer /></Button>
        <Button variant="ghost" size="icon-sm" onClick={() => openRackModal(r)} title="Ubah rak" aria-label={`Ubah rak ${r.code}`}><Pencil /></Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" title="Lainnya" aria-label={`Aksi lain rak ${r.code}`}><MoreHorizontal /></Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => handleDelete('rack', r)}><Ban className="mr-2 h-4 w-4" />Nonaktifkan rak</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>) },
  ];

  const unduh = view === 'buildings' ? (
    <TombolUnduh namaBerkas="gedung-gudang" namaLembar="Gedung" baris={buildings} testId="wms-building-unduh"
      kolom={[
        { label: 'Kode', nilai: (b) => b.code }, { label: 'Nama', nilai: (b) => b.name },
        { label: 'Alamat', nilai: (b) => b.address || '' },
        { label: 'Zona', nilai: (b) => Number(b.zone_count || 0) }, { label: 'Rak', nilai: (b) => Number(b.rack_count || 0) },
      ]} />
  ) : view === 'zones' ? (
    <TombolUnduh namaBerkas={`zona-${namaGedung || 'gedung'}`} namaLembar="Zona" baris={zones} testId="wms-zone-unduh"
      kolom={[
        { label: 'Kode', nilai: (z) => z.code }, { label: 'Nama', nilai: (z) => z.name },
        { label: 'Jenis zona', nilai: (z) => ZONE_TYPE_LABELS[z.zone_type] || 'Umum' },
        { label: 'Rak', nilai: (z) => Number(z.rack_count || 0) },
        { label: 'Lokasi gudang', nilai: (z) => (z.location_id ? `${z.location_code || ''} ${z.location_name || ''}`.trim() : 'Belum ditautkan') },
      ]} />
  ) : (
    <TombolUnduh namaBerkas={`rak-${namaZona || 'zona'}`} namaLembar="Rak" baris={racks} testId="wms-rack-unduh"
      kolom={[
        { label: 'Kode', nilai: (r) => r.code }, { label: 'Nama', nilai: (r) => r.name },
        { label: 'Tingkat', nilai: (r) => Number(r.num_shelves || 0) }, { label: 'Slot per tingkat', nilai: (r) => Number(r.slots_per_shelf || 0) },
        { label: 'Total posisi', nilai: (r) => Number(r.total_positions || 0) }, { label: 'Terisi', nilai: (r) => Number(r.occupied_positions || 0) },
        { label: 'Terisi (%)', nilai: (r) => Number(r.occupancy_pct || 0) },
        { label: 'Kapasitas per slot', nilai: (r) => Number(r.capacity_per_slot || 0) }, { label: 'Satuan kapasitas', nilai: (r) => r.capacity_unit || '' },
      ]} />
  );

  const tombolTambah = view === 'buildings'
    ? <Button data-testid="add-building-btn" onClick={() => openBldgModal()}><Plus />Tambah gedung</Button>
    : view === 'zones'
      ? <Button data-testid="add-zone-btn" onClick={() => openZoneModal()}><Plus />Tambah zona</Button>
      : <Button data-testid="add-rack-btn" onClick={() => openRackModal()}><Plus />Tambah rak</Button>;

  return (
    <PageLayout testId="wms-section-structure" title="Struktur gudang"
      subtitle="Gedung, zona, dan rak gudang — sumber tunggal lokasi rak & bin."
      actions={<>
        {view === 'buildings' && <ImportExportToolbar collectionKey="wh_bins" label="Rak & Bin Gudang" onImported={loadBuildings} size="default" caption="rak & bin" />}
        {tombolTambah}
      </>}
      filters={<>
        <nav aria-label="Tingkat struktur" className="flex flex-wrap items-center gap-1 text-sm">
          <Button variant="link" className="h-auto px-0" onClick={() => { setView('buildings'); setSelectedBldg(null); setSelectedZone(null); }}
            aria-current={view === 'buildings' ? 'page' : undefined}>
            Gedung ({buildings.length})
          </Button>
          {selectedBldg && <>
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
            <Button variant="link" className="h-auto px-0" onClick={() => { setView('zones'); setSelectedZone(null); }}
              aria-current={view === 'zones' ? 'page' : undefined}>
              {namaGedung} · zona ({zones.length})
            </Button>
          </>}
          {selectedZone && <>
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
            <span className="font-medium text-foreground">{namaZona} · rak ({racks.length})</span>
          </>}
        </nav>
        <Alat>
          {unduh}
          <MuatUlang loading={loading} onClick={() => { if (view === 'buildings') loadBuildings(); else if (view === 'zones') loadZones(selectedBldg); else loadRacks(selectedZone); }} />
        </Alat>
      </>}>
      {view === 'buildings' && (
        <TabelData kolom={kolomGedung} baris={buildings} onKlikBaris={bukaGedung} testId="wms-building-table"
          kosong={<EmptyState title="Belum ada gedung" description='Klik "Tambah gedung" untuk mulai menyusun struktur gudang.' />} />
      )}
      {view === 'zones' && selectedBldg && (
        <TabelData kolom={kolomZona} baris={zones} onKlikBaris={bukaZona} testId="wms-zone-table"
          kosong={<EmptyState title="Belum ada zona di gedung ini" description='Klik "Tambah zona".' />} />
      )}
      {view === 'racks' && selectedZone && (
        <TabelData kolom={kolomRak} baris={racks} testId="wms-rack-table"
          kosong={<EmptyState title="Belum ada rak di zona ini" description='Klik "Tambah rak"; barcode posisi dibuat otomatis per slot.' />} />
      )}

      <FormPopup open={!!modal} onClose={() => setModal(null)} onSimpan={handleSave} menyimpan={saving} galat={galat}
        judul={modal ? `${modal.data ? 'Ubah' : 'Tambah'} ${JUDUL_TIPE[modal.type]}` : ''} testId="modal-save"
        labelSimpan={modal?.data ? 'Simpan perubahan' : 'Simpan'}>
        {modal?.type === 'building' && <>
          <div className="grid gap-4 sm:grid-cols-2">
            <Isian label="Kode" wajib htmlFor="wms-b-kode"><Input id="wms-b-kode" value={form.code || ''} onChange={e => setForm(f => ({ ...f, code: e.target.value }))} placeholder="WH1" /></Isian>
            <Isian label="Nama" wajib htmlFor="wms-b-nama"><Input id="wms-b-nama" value={form.name || ''} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="Gudang Utama" /></Isian>
          </div>
          <Isian label="Alamat" htmlFor="wms-b-alamat"><Input id="wms-b-alamat" value={form.address || ''} onChange={e => setForm(f => ({ ...f, address: e.target.value }))} /></Isian>
        </>}
        {modal?.type === 'zone' && <>
          <div className="grid gap-4 sm:grid-cols-2">
            <Isian label="Kode" wajib htmlFor="wms-z-kode"><Input id="wms-z-kode" value={form.code || ''} onChange={e => setForm(f => ({ ...f, code: e.target.value }))} placeholder="RM" /></Isian>
            <Isian label="Nama" wajib htmlFor="wms-z-nama"><Input id="wms-z-nama" value={form.name || ''} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} /></Isian>
          </div>
          <Isian label="Jenis zona">
            <SmartNativeSelect value={form.zone_type || 'general'} searchable={false} className="w-full"
              onChange={e => setForm(f => ({ ...f, zone_type: e.target.value }))}>
              <option value="rm">Bahan baku</option><option value="fg">Produk jadi</option><option value="wip">Barang setengah jadi</option>
              <option value="transit">Transit</option><option value="general">Umum</option>
            </SmartNativeSelect>
          </Isian>
          <Isian label="Lokasi gudang (untuk opname)" petunjuk="Rak & bin zona ini ikut dihitung saat opname lokasi yang dipilih.">
            <SmartNativeSelect data-testid="zone-location-select" value={form.location_id || ''} className="w-full"
              onChange={e => setForm(f => ({ ...f, location_id: e.target.value }))}>
              <option value="">Belum ditautkan</option>
              {locations.map(l => <option key={l.id} value={l.id}>{`${l.code} · ${l.name}`}</option>)}
            </SmartNativeSelect>
          </Isian>
        </>}
        {modal?.type === 'rack' && <>
          <div className="grid gap-4 sm:grid-cols-2">
            <Isian label="Kode" wajib htmlFor="wms-r-kode"><Input id="wms-r-kode" value={form.code || ''} onChange={e => setForm(f => ({ ...f, code: e.target.value }))} placeholder="R01" /></Isian>
            <Isian label="Nama" wajib htmlFor="wms-r-nama"><Input id="wms-r-nama" value={form.name || ''} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} /></Isian>
            <Isian label="Jumlah tingkat (shelf)" htmlFor="wms-r-shelf"><Input id="wms-r-shelf" type="number" min="1" max="50" value={form.num_shelves || 4} onChange={e => setForm(f => ({ ...f, num_shelves: +e.target.value }))} /></Isian>
            <Isian label="Slot per tingkat" htmlFor="wms-r-slot"><Input id="wms-r-slot" type="number" min="1" max="100" value={form.slots_per_shelf || 6} onChange={e => setForm(f => ({ ...f, slots_per_shelf: +e.target.value }))} /></Isian>
            <Isian label="Kapasitas per slot" htmlFor="wms-r-kap"><Input id="wms-r-kap" type="number" min="0" value={form.capacity_per_slot || 0} onChange={e => setForm(f => ({ ...f, capacity_per_slot: +e.target.value }))} /></Isian>
            <Isian label="Satuan kapasitas">
              <SmartNativeSelect value={form.capacity_unit || ''} onChange={e => setForm(f => ({ ...f, capacity_unit: e.target.value }))} className="w-full" data-testid="rack-capacity-unit">
                {/* 2026-11-07 (Tahap 5): satuan dari daftar satuan sah (dulu teks bebas "kg, pcs, ...") */}
                <option value="">Tanpa satuan</option>
                {form.capacity_unit && !MATERIAL_UNITS.includes(form.capacity_unit) && <option value={form.capacity_unit}>{form.capacity_unit}</option>}
                {MATERIAL_UNITS.map(u => <option key={u} value={u}>{u}</option>)}
              </SmartNativeSelect>
            </Isian>
          </div>
          <p className="text-sm text-muted-foreground">
            Total posisi yang akan dibuat: <span className="font-semibold text-foreground">{(form.num_shelves || 4) * (form.slots_per_shelf || 6)}</span> slot
            {!modal.data && ' — barcode otomatis dibuat per slot.'}
          </p>
        </>}
      </FormPopup>
    </PageLayout>
  );
}

// ──────────────────────────────────────────────────────────────────────────────
// SATUAN & KONVERSI (wh-units)
// ──────────────────────────────────────────────────────────────────────────────
function UnitsTab({ token }) {
  const [units, setUnits] = useState([]);
  const [conversions, setConversions] = useState([]);
  const [subTab, setSubTab] = useState('units');
  const [kategori, setKategori] = useState('');
  const [cari, setCari] = useState('');
  const [calcOpen, setCalcOpen] = useState(false);
  const [calcForm, setCalcForm] = useState({ qty: 1, from_unit: '', to_unit: '' });
  const [calcResult, setCalcResult] = useState(null);
  const [modal, setModal] = useState(null);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [galat, setGalat] = useState('');
  const [loading, setLoading] = useState(false);
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [u, c] = await Promise.all([
        fetch(`${API}/api/wms/units`, { headers }).then(r => r.json()),
        fetch(`${API}/api/wms/unit-conversions`, { headers }).then(r => r.json()),
      ]);
      setUnits(Array.isArray(u) ? u : []);
      setConversions(Array.isArray(c) ? c : []);
    } finally { setLoading(false); }
  }, [headers]);
  useEffect(() => { load(); }, [load]);

  async function handleSave() {
    setSaving(true); setGalat('');
    try {
      const url = modal.type === 'unit'
        ? (modal.data ? `${API}/api/wms/units/${modal.data.id}` : `${API}/api/wms/units`)
        : (modal.data ? `${API}/api/wms/unit-conversions/${modal.data.id}` : `${API}/api/wms/unit-conversions`);
      const r = await fetch(url, { method: modal.data ? 'PUT' : 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(form) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Gagal');
      toast.success(d.message || 'Berhasil'); setModal(null); load();
    } catch (e) { setGalat(e.message); toast.error(e.message); }
    finally { setSaving(false); }
  }

  async function handleCalc() {
    try {
      const r = await fetch(`${API}/api/wms/units/convert`, { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify({ qty: +calcForm.qty, from_unit: calcForm.from_unit, to_unit: calcForm.to_unit }) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail);
      setCalcResult(d);
    } catch (e) { toast.error(e.message); }
  }

  const seed = async () => {
    await fetch(`${API}/api/wms/units/seed`, { method: 'POST', headers });
    toast.success('Satuan bawaan selesai diisi');
    load();
  };

  const CATEGORIES = [...new Set(units.map(u => u.category))].sort();
  const q = cari.trim().toLowerCase();
  const unitTampil = units
    .filter(u => !kategori || u.category === kategori)
    .filter(u => !q || `${u.code} ${u.name} ${u.symbol || ''}`.toLowerCase().includes(q));
  const konversiTampil = conversions
    .filter(c => !q || `${c.from_unit_code} ${c.to_unit_code} ${c.notes || ''}`.toLowerCase().includes(q));

  const kolomSatuan = [
    { kunci: 'code', label: 'Kode', hp: 'judul', isi: (u) => <span className="font-medium" data-testid="unit-card">{u.code}</span> },
    { kunci: 'hp-ket', label: '', hp: 'keterangan', lebar: 'hidden', isi: (u) => `${u.name} · ${kategoriSatuan(u.category)}${u.is_base ? ' · satuan dasar' : ''}` },
    { kunci: 'name', label: 'Nama', hp: false, isi: (u) => u.name },
    { kunci: 'symbol', label: 'Simbol', hp: false, isi: (u) => u.symbol || '—' },
    { kunci: 'category', label: 'Kategori', hp: false, isi: (u) => kategoriSatuan(u.category) },
    { kunci: 'is_base', label: 'Satuan dasar', hp: false, isi: (u) => (u.is_base ? <StatusBadge status="dasar" label="Dasar" tone="primary" /> : <span className="text-muted-foreground">—</span>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (u) => (
      <Button variant="ghost" size="icon-sm" onClick={() => { setGalat(''); setForm({ ...u }); setModal({ type: 'unit', data: u }); }}
        title="Ubah satuan" aria-label={`Ubah satuan ${u.code}`}><Pencil /></Button>) },
  ];
  const kolomKonversi = [
    { kunci: 'from', label: 'Dari', hp: false, isi: (c) => <span className="font-medium" data-testid="conversion-row">{c.from_unit_code}</span> },
    { kunci: 'to', label: 'Ke', hp: false, isi: (c) => <span className="font-medium">{c.to_unit_code}</span> },
    { kunci: 'factor', label: 'Faktor', hp: false, rata: 'kanan', isi: (c) => <span className="tabular-nums">{String(c.factor).replace('.', ',')}</span> },
    { kunci: 'rumus', label: 'Rumus', hp: 'judul', isi: (c) => <span className="text-muted-foreground">1 {c.from_unit_code} = {String(c.factor).replace('.', ',')} {c.to_unit_code}</span> },
    { kunci: 'notes', label: 'Catatan', hp: false, isi: (c) => <span className="text-muted-foreground">{c.notes || '—'}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (c) => (
      <Button variant="ghost" size="icon-sm" onClick={() => { setGalat(''); setForm({ ...c }); setModal({ type: 'conversion', data: c }); }}
        title="Ubah konversi" aria-label={`Ubah konversi ${c.from_unit_code} ke ${c.to_unit_code}`}><Pencil /></Button>) },
  ];

  return (
    <PageLayout testId="wms-section-units" title="Satuan & konversi"
      subtitle="Master satuan gudang dan aturan konversinya."
      actions={<>
        <Button variant="outline" onClick={() => { setCalcResult(null); setCalcOpen(true); }} data-testid="calculate-open-btn"><Calculator />Kalkulator</Button>
        <Button variant="outline" onClick={seed}><RefreshCw />Isi satuan bawaan</Button>
        {subTab === 'units' ? (
          <Button data-testid="add-unit-btn" onClick={() => { setGalat(''); setForm({ code: '', name: '', category: 'count', symbol: '', is_base: false }); setModal({ type: 'unit', data: null }); }}>
            <Plus />Tambah satuan
          </Button>
        ) : (
          <Button data-testid="add-conversion-btn" onClick={() => { setGalat(''); setForm({ from_unit_code: '', to_unit_code: '', factor: 1, notes: '' }); setModal({ type: 'conversion', data: null }); }}>
            <Plus />Tambah konversi
          </Button>
        )}
      </>}
      filters={<>
        <FilterChips value={subTab} onChange={setSubTab} hideWhenEmpty={false} className="w-full sm:w-auto" ariaLabel="Tampilan" testId="wms-units-view"
          options={[{ key: 'units', label: 'Master satuan', count: units.length }, { key: 'conversions', label: 'Aturan konversi', count: conversions.length }]} />
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={cari} onChange={e => setCari(e.target.value)} placeholder={subTab === 'units' ? 'Cari kode atau nama satuan' : 'Cari satuan'} className="pl-8" />
        </div>
        {subTab === 'units' && (
          <SelectPenyaring value={kategori} onChange={e => setKategori(e.target.value)} searchable={false} aria-label="Kategori">
            <option value="">Semua kategori</option>
            {CATEGORIES.map(c => <option key={c} value={c}>{kategoriSatuan(c)}</option>)}
          </SelectPenyaring>
        )}
        <Alat>
          {subTab === 'units' ? (
            <TombolUnduh namaBerkas="satuan-gudang" namaLembar="Satuan" baris={unitTampil} testId="wms-units-unduh"
              kolom={[
                { label: 'Kode', nilai: (u) => u.code }, { label: 'Nama', nilai: (u) => u.name }, { label: 'Simbol', nilai: (u) => u.symbol || '' },
                { label: 'Kategori', nilai: (u) => kategoriSatuan(u.category) }, { label: 'Satuan dasar', nilai: (u) => (u.is_base ? 'Ya' : 'Tidak') },
              ]} />
          ) : (
            <TombolUnduh namaBerkas="konversi-satuan" namaLembar="Konversi" baris={konversiTampil} testId="wms-conv-unduh"
              kolom={[
                { label: 'Dari', nilai: (c) => c.from_unit_code }, { label: 'Ke', nilai: (c) => c.to_unit_code },
                { label: 'Faktor', nilai: (c) => Number(c.factor) }, { label: 'Catatan', nilai: (c) => c.notes || '' },
              ]} />
          )}
          <MuatUlang loading={loading} onClick={load} />
        </Alat>
      </>}>
      {subTab === 'units' ? (
        <TabelData kolom={kolomSatuan} baris={unitTampil} testId="wms-units-table"
          kosong={<EmptyState title={units.length ? 'Tidak ada satuan yang cocok' : 'Belum ada satuan'}
            description={units.length ? 'Ubah kategori atau kata pencarian.' : 'Klik "Isi satuan bawaan" atau "Tambah satuan".'} />} />
      ) : (
        <TabelData kolom={kolomKonversi} baris={konversiTampil} testId="wms-conv-table"
          kosong={<EmptyState title={conversions.length ? 'Tidak ada konversi yang cocok' : 'Belum ada aturan konversi'} />} />
      )}

      {/* Form satuan / konversi */}
      <FormPopup open={!!modal} onClose={() => setModal(null)} onSimpan={handleSave} menyimpan={saving} galat={galat}
        judul={modal ? `${modal.data ? 'Ubah' : 'Tambah'} ${modal.type === 'unit' ? 'satuan' : 'konversi'}` : ''} testId="wms-unit-form"
        labelSimpan={modal?.data ? 'Simpan perubahan' : 'Simpan'}>
        {modal?.type === 'unit' && <>
          <div className="grid gap-4 sm:grid-cols-2">
            <Isian label="Kode" wajib htmlFor="wms-u-kode"><Input id="wms-u-kode" value={form.code || ''} onChange={e => setForm(f => ({ ...f, code: e.target.value }))} placeholder="rol" /></Isian>
            <Isian label="Simbol" wajib htmlFor="wms-u-simbol"><Input id="wms-u-simbol" value={form.symbol || ''} onChange={e => setForm(f => ({ ...f, symbol: e.target.value }))} /></Isian>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Isian label="Nama" wajib htmlFor="wms-u-nama"><Input id="wms-u-nama" value={form.name || ''} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} /></Isian>
            <Isian label="Kategori">
              <SmartNativeSelect value={form.category || 'count'} searchable={false} className="w-full" onChange={e => setForm(f => ({ ...f, category: e.target.value }))}>
                {['weight', 'length', 'count', 'roll', 'pack', 'volume', 'other'].map(c => <option key={c} value={c}>{kategoriSatuan(c)}</option>)}
              </SmartNativeSelect>
            </Isian>
          </div>
        </>}
        {modal?.type === 'conversion' && <>
          <div className="grid gap-4 sm:grid-cols-2">
            <Isian label="Dari" wajib>
              <SmartNativeSelect value={form.from_unit_code || ''} className="w-full" onChange={e => setForm(f => ({ ...f, from_unit_code: e.target.value }))}>
                <option value="">Pilih</option>{units.map(u => <option key={u.id} value={u.code}>{u.code}</option>)}
              </SmartNativeSelect>
            </Isian>
            <Isian label="Ke" wajib>
              <SmartNativeSelect value={form.to_unit_code || ''} className="w-full" onChange={e => setForm(f => ({ ...f, to_unit_code: e.target.value }))}>
                <option value="">Pilih</option>{units.map(u => <option key={u.id} value={u.code}>{u.code}</option>)}
              </SmartNativeSelect>
            </Isian>
          </div>
          <Isian label="Faktor pengali" wajib htmlFor="wms-c-faktor"
            petunjuk={form.from_unit_code && form.to_unit_code ? `1 ${form.from_unit_code} = ${form.factor || 1} ${form.to_unit_code}` : undefined}>
            <Input id="wms-c-faktor" type="number" step="0.000001" value={form.factor || 1} onChange={e => setForm(f => ({ ...f, factor: +e.target.value }))} />
          </Isian>
          <Isian label="Catatan" htmlFor="wms-c-catatan"><Input id="wms-c-catatan" value={form.notes || ''} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} /></Isian>
        </>}
      </FormPopup>

      {/* Kalkulator konversi */}
      <FormPopup open={calcOpen} onClose={() => setCalcOpen(false)} judul="Kalkulator konversi satuan" testId="calculate"
        onSimpan={handleCalc} labelSimpan="Hitung konversi" bisaSimpan={!!calcForm.from_unit && !!calcForm.to_unit}>
        <Isian label="Jumlah" htmlFor="wms-calc-qty">
          <Input id="wms-calc-qty" type="number" value={calcForm.qty} onChange={e => setCalcForm(f => ({ ...f, qty: e.target.value }))} />
        </Isian>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Dari">
            <SmartNativeSelect value={calcForm.from_unit} className="w-full" onChange={e => setCalcForm(f => ({ ...f, from_unit: e.target.value }))}>
              <option value="">Pilih</option>{units.map(u => <option key={u.id} value={u.code}>{`${u.code} (${u.name})`}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Ke">
            <SmartNativeSelect value={calcForm.to_unit} className="w-full" onChange={e => setCalcForm(f => ({ ...f, to_unit: e.target.value }))}>
              <option value="">Pilih</option>{units.map(u => <option key={u.id} value={u.code}>{`${u.code} (${u.name})`}</option>)}
            </SmartNativeSelect>
          </Isian>
        </div>
        {calcResult && (
          <div className="rounded-md border border-[var(--glass-border)] p-3 text-center" data-testid="calculate-result">
            <p className="text-lg font-semibold tabular-nums text-foreground">{fmt(calcResult.result)} {calcResult.to}</p>
            <p className="text-xs text-muted-foreground">{calcResult.input} {calcResult.from} × {calcResult.factor}</p>
          </div>
        )}
      </FormPopup>
    </PageLayout>
  );
}

// ──────────────────────────────────────────────────────────────────────────────
// SCAN GUDANG (wh-scan — tautan lama, tidak lagi di navigasi sejak Fase H-4)
// ──────────────────────────────────────────────────────────────────────────────
// Lokasi wajib dipilih, kecuali dokumen antrean sudah menunjuk lokasinya
// (fulfillment ber-stock_id / location_id) — No.18(a), 2026-11-02.
function needsScanLocation(scanModal) {
  const m = scanModal?.movement || {};
  if (scanModal?.mode === 'out' && m.source_type === 'fulfillment' && m.stock_id) return false;
  return !m.location_id;
}

const TYPE_LABEL = { inbound: 'Masuk barang jadi', outbound_rm: 'Keluar bahan', outbound_fg: 'Keluar barang jadi' };
const TYPE_TONE = { inbound: 'success', outbound_rm: 'warning', outbound_fg: 'warning' };

function ReceivingTab({ token }) {
  const [pending, setPending] = useState([]);
  const [filter, setFilter] = useState('all');
  const [buildingFilter, setBuildingFilter] = useState('');
  const [buildings, setBuildings] = useState([]);
  const [scanModal, setScanModal] = useState(null); // {movement, mode: 'in'|'out'}
  const [scanQty, setScanQty] = useState('');
  const [scanUom, setScanUom] = useState('');       // satuan hitung fisik operator (ROADMAP P1)
  const [positionBarcode, setPositionBarcode] = useState('');
  const [positionInfo, setPositionInfo] = useState(null);
  // 2026-11-02 — No.18(a): lokasi stok masuk/keluar WAJIB dipilih (dulu backend memakai
  // "lokasi aktif pertama"). Fulfillment ber-stock_id tidak perlu (barisnya sudah tertentu).
  const [scanLocation, setScanLocation] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [loading, setLoading] = useState(false);
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  // Satuan sah untuk material pada movement yang sedang di-scan
  const { options: uomOpts } = useUomOptions(
    scanModal?.movement?.material_id ? [scanModal.movement.material_id] : []);
  const scanUomOpt = scanModal?.movement?.material_id ? uomOpts[scanModal.movement.material_id] : null;
  const docUnit = String(scanModal?.movement?.unit || '').toLowerCase();
  const effScanUom = scanUom || docUnit;

  useEffect(() => {
    fetch(`${API}/api/wms/buildings`, { headers }).then(r => r.json()).then(d => setBuildings(Array.isArray(d) ? d : [])).catch(() => {});
  }, [headers]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filter !== 'all') params.set('type', filter);
      if (buildingFilter) params.set('building_id', buildingFilter);
      const qs = params.toString() ? `?${params.toString()}` : '';
      const r = await fetch(`${API}/api/wms/pending${qs}`, { headers });
      const d = await r.json();
      setPending(Array.isArray(d) ? d.filter(m => m.status !== 'cancelled' && m.status !== 'confirmed') : []);
    } catch { toast.error('Gagal memuat data'); }
    finally { setLoading(false); }
  }, [headers, filter, buildingFilter]);
  useEffect(() => { load(); }, [load]);

  async function lookupPosition(barcode) {
    if (!barcode) return;
    try {
      const r = await fetch(`${API}/api/wms/positions/by-barcode/${encodeURIComponent(barcode)}`, { headers });
      if (r.ok) setPositionInfo(await r.json());
      else setPositionInfo(null);
    } catch { setPositionInfo(null); }
  }

  const bukaScan = (m, mode) => {
    setScanModal({ movement: m, mode }); setScanQty(String(m.expected_qty - (m.scanned_qty || 0)));
    setPositionBarcode(''); setPositionInfo(null); setScanLocation('');
  };

  async function handleScan() {
    if (!scanModal || !scanQty || +scanQty <= 0) { toast.error('Masukkan jumlah yang valid'); return; }
    if (needsScanLocation(scanModal) && !scanLocation) { toast.error('Pilih lokasi terlebih dahulu'); return; }
    setSubmitting(true);
    try {
      const { movement, mode } = scanModal;
      const endpoint = mode === 'in' ? 'scan-in' : 'scan-out';
      const body = { scanned_qty: +scanQty, position_barcode: positionBarcode || undefined,
                     location_id: scanLocation || undefined };
      // ROADMAP P1 — operator boleh menghitung dalam satuan lain (box/rol/gram);
      // backend menerjemahkannya ke satuan dokumen & satuan dasar.
      if (mode === 'in' && effScanUom && effScanUom !== docUnit) body.input_uom = effScanUom;
      const r = await fetch(`${API}/api/wms/pending/${movement.id}/${endpoint}`, {
        method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Gagal');
      const u = d.uom_applied;
      toast.success(
        `${mode === 'in' ? 'Scan masuk' : 'Scan keluar'} berhasil: ${d.ref_number} — ${moveStatus(d.status).label}`
        + (u ? ` · ${fmt(u.input_qty)} ${u.input_uom} = ${fmt(u.qty_base)} ${u.base_unit}` : ''));
      setScanModal(null); setScanQty(''); setScanUom(''); setPositionBarcode(''); setPositionInfo(null); setScanLocation('');
      load();
    } catch (e) { toast.error(e.message); }
    finally { setSubmitting(false); }
  }

  const kolom = [
    { kunci: 'ref', label: 'Ref', hp: 'judul', isi: (m) => <span className="tabular-nums" data-testid="pending-movement-row">{m.ref_number}</span> },
    { kunci: 'type', label: 'Jenis', hp: false, isi: (m) => <StatusBadge status={m.type} label={TYPE_LABEL[m.type] || 'Lainnya'} tone={TYPE_TONE[m.type] || 'muted'} /> },
    { kunci: 'material', label: 'Barang', hp: 'keterangan', isi: (m) => m.material_name },
    { kunci: 'source', label: 'Sumber', hp: false, isi: (m) => <span className="text-muted-foreground">{m.source_ref || '—'}</span> },
    { kunci: 'progres', label: 'Terscan / diharapkan', rata: 'kanan', isi: (m) => <span className="tabular-nums">{fmt(m.scanned_qty || 0)} / {fmt(m.expected_qty)} {m.unit}</span> },
    { kunci: 'status', label: 'Status', isi: (m) => { const s = moveStatus(m.status); return <StatusBadge status={m.status} label={s.label} tone={s.tone} />; } },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (m) => (
      m.type === 'inbound'
        ? <Button size="sm" variant="outline" data-testid="scan-in-btn" onClick={() => bukaScan(m, 'in')}><Scan />Scan masuk</Button>
        : (m.type === 'outbound_rm' || m.type === 'outbound_fg')
          ? <Button size="sm" variant="outline" data-testid="scan-out-btn" onClick={() => bukaScan(m, 'out')}><Scan />Scan keluar</Button>
          : null) },
  ];

  return (
    <PageLayout testId="wms-section-receiving" title="Scan gudang"
      subtitle="Eksekusi fisik: scan masuk penerimaan dan scan keluar pengeluaran dari antrean pergerakan."
      filters={<>
        <FilterChips value={filter} onChange={setFilter} hideWhenEmpty={false} className="w-full sm:w-auto" ariaLabel="Jenis pergerakan"
          options={[{ key: 'all', label: 'Semua' }, ...Object.entries(TYPE_LABEL).map(([k, l]) => ({ key: k, label: l }))]} />
        {buildings.length > 0 && (
          <SelectPenyaring data-testid="receiving-building-filter" value={buildingFilter} onChange={e => setBuildingFilter(e.target.value)} aria-label="Gedung">
            <option value="">Semua gedung</option>
            {buildings.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
          </SelectPenyaring>
        )}
        <Alat>
          <TombolUnduh namaBerkas="antrean-scan-gudang" namaLembar="Antrean" baris={pending} testId="wms-pending-unduh"
            kolom={[
              { label: 'Ref', nilai: (m) => m.ref_number }, { label: 'Jenis', nilai: (m) => TYPE_LABEL[m.type] || '' },
              { label: 'Barang', nilai: (m) => m.material_name }, { label: 'Sumber', nilai: (m) => m.source_ref || '' },
              { label: 'Terscan', nilai: (m) => Number(m.scanned_qty || 0) }, { label: 'Diharapkan', nilai: (m) => Number(m.expected_qty || 0) },
              { label: 'Satuan', nilai: (m) => m.unit || '' }, { label: 'Status', nilai: (m) => moveStatus(m.status).label },
            ]} />
          <MuatUlang loading={loading} onClick={load} />
        </Alat>
      </>}>
      {loading && pending.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat antrean…</p>
      ) : (
        <TabelData kolom={kolom} baris={pending} testId="wms-pending-table"
          kosong={<EmptyState title={`Tidak ada antrean pergerakan${filter !== 'all' ? ` untuk ${TYPE_LABEL[filter].toLowerCase()}` : ''}`} />} />
      )}

      <FormPopup open={!!scanModal} onClose={() => setScanModal(null)} testId="confirm-scan" menyimpan={submitting}
        judul={scanModal?.mode === 'in' ? 'Scan masuk — terima barang' : 'Scan keluar — keluarkan barang'}
        keterangan={scanModal ? `${scanModal.movement.material_name} · ref ${scanModal.movement.ref_number} · diharapkan ${scanModal.movement.expected_qty} ${scanModal.movement.unit}, terscan ${scanModal.movement.scanned_qty || 0}` : undefined}
        onSimpan={handleScan} labelSimpan={scanModal?.mode === 'in' ? 'Konfirmasi terima' : 'Konfirmasi keluar'}
        bisaSimpan={!!scanQty && !(scanModal && needsScanLocation(scanModal) && !scanLocation)}>
        {scanModal && <>
          <Isian label={`Jumlah yang ${scanModal.mode === 'in' ? 'diterima' : 'dikeluarkan'}`} wajib htmlFor="wms-scan-qty">
            <div className="flex gap-2">
              <Input id="wms-scan-qty" type="number" min="0.0001" step="0.0001" value={scanQty} onChange={e => setScanQty(e.target.value)}
                data-testid="wms-scan-qty-input" />
              {scanModal.mode === 'in' && (
                <UomSelect opt={scanUomOpt} value={effScanUom} fallbackUnit={scanModal.movement.unit}
                  onChange={e => setScanUom(e.target.value)} testId="wms-scan-uom-select" className="w-24 shrink-0" />
              )}
            </div>
            {scanModal.mode === 'in' && (
              <UomConversionHint opt={scanUomOpt} qty={scanQty} unit={effScanUom}
                fallbackUnit={scanModal.movement.unit} className="mt-1.5" testId="wms-scan-uom-hint" />
            )}
            {scanModal.mode === 'in' && effScanUom && docUnit && effScanUom !== docUnit && (
              <p className="mt-0.5 text-xs text-muted-foreground" data-testid="wms-scan-doc-unit-note">
                Dokumen memakai satuan <b>{docUnit}</b> — sistem menerjemahkan otomatis.
              </p>
            )}
          </Isian>
          {needsScanLocation(scanModal) && (
            <Isian label={scanModal.mode === 'in' ? 'Lokasi tujuan' : 'Lokasi asal'} wajib>
              <StorageLocationSelect token={token} value={scanLocation} onChange={setScanLocation}
                testId="wms-scan-location-select" className="w-full" />
            </Isian>
          )}
          <Isian label={scanModal.mode === 'in' ? 'Barcode posisi tujuan (scan rak)' : 'Barcode posisi asal (scan rak)'} petunjuk="Opsional">
            <ScannerInput placeholder="Scan label rak (mis. WH1-RM-R01-S01-P01)"
              onScan={v => { setPositionBarcode(v); lookupPosition(v); }} />
            {positionBarcode && (
              <p className="mt-1 text-xs">
                {positionInfo ? (
                  <span className="text-[hsl(var(--success-text))]"><MapPin className="mr-1 inline h-3 w-3" />{positionInfo.label} — {positionInfo.building_code}/{positionInfo.zone_code}/{positionInfo.rack_code}</span>
                ) : (
                  <span className="text-[hsl(var(--warning-text))]"><AlertCircle className="mr-1 inline h-3 w-3" />Posisi tidak ditemukan: {positionBarcode}</span>
                )}
              </p>
            )}
          </Isian>
        </>}
      </FormPopup>
    </PageLayout>
  );
}

// ──────────────────────────────────────────────────────────────────────────────
// POSISI & CARI (tab di hub Stok & Akurasi)
// ──────────────────────────────────────────────────────────────────────────────
export function PositionsTab({ token }) {
  const [searchQ, setSearchQ] = useState('');
  const [searchResult, setSearchResult] = useState(null);
  const [searching, setSearching] = useState(false);
  const [buildings, setBuildings] = useState([]);
  const [selectedBldg, setSelectedBldg] = useState('');
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  useEffect(() => {
    fetch(`${API}/api/wms/buildings`, { headers }).then(r => r.json()).then(d => setBuildings(Array.isArray(d) ? d : []));
  }, [headers]);

  async function doSearch(q) {
    if (!q?.trim()) return;
    setSearchQ(q);
    setSearching(true);
    try {
      const url = `${API}/api/wms/search?q=${encodeURIComponent(q)}${selectedBldg ? `&building_id=${selectedBldg}` : ''}`;
      const r = await fetch(url, { headers });
      const d = await r.json();
      setSearchResult(d);
    } catch { toast.error('Pencarian gagal'); }
    finally { setSearching(false); }
  }

  const posisi = searchResult?.type === 'position' ? null : (searchResult?.positions || []);
  const material = searchResult?.type === 'position' ? [] : (searchResult?.materials || []);
  const kolomPosisi = [
    { kunci: 'barcode', label: 'Barcode posisi', hp: 'judul', isi: (p) => <span className="tabular-nums" data-testid="position-result">{p.barcode}</span> },
    { kunci: 'lokasi', label: 'Lokasi', hp: 'keterangan', isi: (p) => `${p.building_code} / ${p.zone_code} / ${p.rack_code} / ${p.label}` },
    { kunci: 'qty', label: 'Stok', rata: 'kanan', isi: (p) => <span className="tabular-nums font-medium">{fmt(p.qty)} {p.unit}</span> },
  ];
  const kolomMaterial = [
    { kunci: 'code', label: 'Kode', hp: 'judul', isi: (m) => <span className="tabular-nums">{m.code}</span> },
    { kunci: 'name', label: 'Nama', hp: 'keterangan', isi: (m) => m.name },
  ];
  const res = searchResult?.result;
  const statusPosisi = res ? (POSITION_STATUS[res.status] || { label: res.status ? 'Lainnya' : '—', tone: 'muted' }) : null;

  return (
    <PageLayout testId="wms-section-positions" title="Posisi & cari"
      subtitle="Cari letak barang: scan barcode rak atau material, atau ketik nama/kode produk lalu Enter."
      filters={<>
        {buildings.length > 1 && (
          <SelectPenyaring value={selectedBldg} onChange={e => setSelectedBldg(e.target.value)} aria-label="Gedung">
            <option value="">Semua gedung</option>
            {buildings.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
          </SelectPenyaring>
        )}
        <ScannerInput className="w-full sm:w-96" placeholder="Scan barcode atau ketik nama/kode, lalu Enter" onScan={doSearch} />
        {posisi && posisi.length > 0 && (
          <Alat>
            <TombolUnduh namaBerkas={`posisi-${searchQ}`} namaLembar="Posisi" baris={posisi} testId="wms-positions-unduh"
              kolom={[
                { label: 'Barcode posisi', nilai: (p) => p.barcode }, { label: 'Gedung', nilai: (p) => p.building_code },
                { label: 'Zona', nilai: (p) => p.zone_code }, { label: 'Rak', nilai: (p) => p.rack_code }, { label: 'Posisi', nilai: (p) => p.label },
                { label: 'Stok', nilai: (p) => Number(p.qty || 0) }, { label: 'Satuan', nilai: (p) => p.unit || '' },
              ]} />
          </Alat>
        )}
      </>}>
      {searching && <p className="py-6 text-center text-sm text-muted-foreground">Mencari…</p>}

      {!searching && !searchResult && (
        <EmptyState title="Belum ada pencarian" description="Scan label rak untuk melihat isinya, atau scan/ketik barang untuk melihat letaknya." />
      )}

      {searchResult && !searching && searchResult.type === 'position' && res && (
        <GlassCard className="p-4">
          <p className="mb-2 text-sm font-medium text-foreground">Posisi ditemukan</p>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Barcode"><span className="tabular-nums">{res.barcode}</span></BarisDetail>
            <BarisDetail label="Label">{res.label}</BarisDetail>
            <BarisDetail label="Lokasi">{res.building_code}/{res.zone_code}/{res.rack_code}</BarisDetail>
            <BarisDetail label="Status"><StatusBadge status={res.status} label={statusPosisi.label} tone={statusPosisi.tone} /></BarisDetail>
            {res.material_name && <>
              <BarisDetail label="Barang">{res.material_name}</BarisDetail>
              <BarisDetail label="Stok"><span className="font-medium tabular-nums">{fmt(res.qty)} {res.unit}</span></BarisDetail>
            </>}
          </dl>
        </GlassCard>
      )}

      {searchResult && !searching && searchResult.type !== 'position' && (
        <div className="space-y-4">
          {material.length > 0 && (
            <div className="space-y-2">
              <p className="text-sm font-medium text-foreground">
                Barang cocok ({material.length}) · total stok di gudang <span className="tabular-nums">{fmt(searchResult.total_qty)}</span>
              </p>
              <TabelData kolom={kolomMaterial} baris={material} testId="wms-search-materials" />
            </div>
          )}
          <div className="space-y-2">
            <p className="text-sm font-medium text-foreground">Lokasi penyimpanan</p>
            <TabelData kolom={kolomPosisi} baris={posisi || []} testId="wms-search-positions"
              kosong={<EmptyState title="Tidak ada data posisi tersimpan untuk barang ini" />} />
          </div>
        </div>
      )}
    </PageLayout>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// AUDIT TRAIL — riwayat penyesuaian opname per operator/posisi (wh-audit)
// ══════════════════════════════════════════════════════════════════════════════
const FILTER_KOSONG = { operator: '', position_barcode: '', building_id: '', date_from: '', date_to: '', direction: '' };

function AuditTrailTab({ token }) {
  const [items, setItems] = useState([]);
  const [stats, setStats] = useState(null);
  const [buildings, setBuildings] = useState([]);
  const [loading, setLoading] = useState(false);
  const [rcaModal, setRcaModal] = useState(null); // {barcode, loading, result, error}
  const [filters, setFilters] = useState(FILTER_KOSONG);
  const [ketik, setKetik] = useState({ operator: '', position_barcode: '' });
  const [period, setPeriod] = useState({ preset: 'all', from: '', to: '' });
  const [page, setPage] = useState({ limit: 50, skip: 0, total: 0 });
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  useEffect(() => {
    fetch(`${API}/api/wms/buildings`, { headers }).then(r => r.json()).then(d => setBuildings(Array.isArray(d) ? d : [])).catch(() => {});
  }, [headers]);

  // Kotak ketik diteruskan ke penyaring setelah jeda singkat; periode → date_from/date_to (YYYY-MM-DD).
  useEffect(() => {
    const t = setTimeout(() => setFilters(f => (f.operator === ketik.operator && f.position_barcode === ketik.position_barcode
      ? f : { ...f, operator: ketik.operator, position_barcode: ketik.position_barcode })), 300);
    return () => clearTimeout(t);
  }, [ketik]);
  useEffect(() => {
    setFilters(f => (f.date_from === (period.from || '') && f.date_to === (period.to || '')
      ? f : { ...f, date_from: period.from || '', date_to: period.to || '' }));
  }, [period]);
  useEffect(() => { setPage(p => (p.skip === 0 ? p : { ...p, skip: 0 })); }, [filters]);

  const qs = useCallback(() => {
    const p = new URLSearchParams();
    if (filters.operator) p.set('operator', filters.operator);
    if (filters.position_barcode) p.set('position_barcode', filters.position_barcode);
    if (filters.building_id) p.set('building_id', filters.building_id);
    if (filters.date_from) p.set('date_from', filters.date_from);
    if (filters.date_to) p.set('date_to', filters.date_to);
    if (filters.direction) p.set('direction', filters.direction);
    return p.toString();
  }, [filters]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qStr = qs();
      const extra = qStr ? `&${qStr}` : '';
      const [listRes, statsRes] = await Promise.all([
        fetch(`${API}/api/wms/audit/adjustments?limit=${page.limit}&skip=${page.skip}${extra}`, { headers }).then(r => r.json()),
        fetch(`${API}/api/wms/audit/adjustments/stats${qStr ? `?${qStr}` : ''}`, { headers }).then(r => r.json()),
      ]);
      setItems(listRes.items || []);
      setPage(p => ({ ...p, total: listRes.total || 0 }));
      setStats(statsRes);
    } catch { toast.error('Gagal memuat audit trail'); }
    finally { setLoading(false); }
  }, [headers, qs, page.limit, page.skip]);

  useEffect(() => { load(); }, [load]);

  const resetFilters = () => {
    setKetik({ operator: '', position_barcode: '' });
    setPeriod({ preset: 'all', from: '', to: '' });
    setFilters(FILTER_KOSONG);
    setPage({ limit: 50, skip: 0, total: 0 });
  };

  // CSV buatan server (fitur lama) — kini lewat header Authorization (dulu token di alamat URL).
  const unduhCsvServer = async () => {
    const qStr = qs();
    try {
      const res = await fetch(`${API}/api/wms/audit/adjustments/export-csv${qStr ? `?${qStr}` : ''}`, { headers });
      if (!res.ok) { toast.error(`Unduhan gagal (HTTP ${res.status}).`); return; }
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement('a');
      a.href = url; a.download = 'audit-penyesuaian-gudang.csv'; a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast.error('Unduhan gagal: ' + (e?.message || 'jaringan bermasalah'));
    }
  };

  // Unduh: SEMUA baris hasil saringan (bukan hanya halaman ini) — API yang sama, 500 per permintaan.
  const ambilSemua = async () => {
    const semua = [];
    const qStr = qs();
    for (let skip = 0; skip < 50000; skip += 500) {
      const d = await fetch(`${API}/api/wms/audit/adjustments?limit=500&skip=${skip}${qStr ? `&${qStr}` : ''}`, { headers }).then(r => r.json());
      const rows = d.items || [];
      semua.push(...rows);
      if (rows.length < 500 || semua.length >= (d.total || 0)) break;
    }
    return semua;
  };

  const jalankanRca = async (barcode) => {
    setRcaModal({ barcode, loading: true, result: null, error: null });
    try {
      const r = await fetch(`${API}/api/wms/audit/hotspot/${encodeURIComponent(barcode)}/rca`, { method: 'POST', headers });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Gagal analisa');
      setRcaModal({ barcode, loading: false, result: d, error: null });
    } catch (e) {
      setRcaModal({ barcode, loading: false, result: null, error: e.message });
    }
  };

  const lokasiDari = (r) => (r.building_code ? `${r.building_code}/${r.zone_code}/${r.rack_code}` : (r.location_code || '—'));
  const kolom = [
    { kunci: 'waktu', label: 'Waktu', hp: false, isi: (r) => <span className="whitespace-nowrap" data-testid="audit-row">{formatDateTimeID(r.timestamp)}</span> },
    { kunci: 'session', label: 'Sesi', hp: 'judul', isi: (r) => <span className="tabular-nums">{r.session_ref || '—'}</span> },
    { kunci: 'hp-ket', label: '', hp: 'keterangan', lebar: 'hidden', isi: (r) => `${formatDateTimeID(r.timestamp)} · ${r.fg_code || '—'}` },
    { kunci: 'operator', label: 'Operator', hp: false, isi: (r) => r.created_by || '—' },
    { kunci: 'lokasi', label: 'Lokasi', hp: false, isi: (r) => lokasiDari(r) },
    { kunci: 'barcode', label: 'Barcode posisi', hp: false, isi: (r) => <span className="tabular-nums">{r.position_barcode || '—'}</span> },
    { kunci: 'material', label: 'Barang', hp: false, isi: (r) => r.fg_code || '—' },
    { kunci: 'arah', label: 'Arah', isi: (r) => { const a = arahDari(r.direction); return <StatusBadge status={r.direction} label={a.label} tone={a.tone} />; } },
    { kunci: 'qty', label: 'Qty', rata: 'kanan', isi: (r) => <span className="tabular-nums font-medium">{fmt(r.qty || 0)}</span> },
    { kunci: 'notes', label: 'Catatan', hp: false, isi: (r) => <span className="line-clamp-1 max-w-[16rem] text-muted-foreground" title={r.notes}>{r.notes || '—'}</span> },
  ];
  const kolomOperator = [
    { kunci: 'operator', label: 'Operator', hp: 'judul', isi: (op) => <span data-testid="audit-operator-row">{op.operator}</span> },
    { kunci: 'count', label: 'Penyesuaian', rata: 'kanan', isi: (op) => <span className="tabular-nums">{fmt(op.count)}</span> },
    { kunci: 'surplus', label: 'Lebih', hp: false, rata: 'kanan', isi: (op) => <span className="tabular-nums">{fmt(op.surplus_qty)}</span> },
    { kunci: 'shortage', label: 'Kurang', hp: false, rata: 'kanan', isi: (op) => <span className="tabular-nums">{fmt(op.shortage_qty)}</span> },
    { kunci: 'last', label: 'Terakhir aktif', hp: 'keterangan', isi: (op) => formatDateTimeID(op.last_activity) },
  ];
  const kolomHotspot = [
    { kunci: 'barcode', label: 'Barcode posisi', hp: 'judul', isi: (p) => <span className="tabular-nums" data-testid="audit-hotspot-row">{p.position_barcode}</span> },
    { kunci: 'count', label: 'Kali disesuaikan', rata: 'kanan', isi: (p) => <span className="tabular-nums">{fmt(p.count)}</span> },
    { kunci: 'net', label: 'Selisih bersih', rata: 'kanan', isi: (p) => <span className="tabular-nums">{p.net_qty > 0 ? '+' : ''}{fmt(p.net_qty)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (p) => (p.count >= 3 ? (
      <Button size="sm" variant="outline" data-testid={`rca-btn-${p.position_barcode}`} onClick={() => jalankanRca(p.position_barcode)}
        title="Analisa penyebab dengan AI"><Sparkles />Analisa AI</Button>) : null) },
  ];

  const adaStat = stats && Number(stats.total_adjustments || 0) > 0;
  const totalHalaman = Math.max(1, Math.ceil((page.total || 0) / page.limit));
  const rca = rcaModal?.result;

  return (
    <PageLayout testId="wms-section-audit" title="Audit trail gudang"
      subtitle="Riwayat penyesuaian stok hasil opname, per operator dan per posisi rak."
      filters={<>
        <Input data-testid="audit-filter-operator" placeholder="Operator (email)" value={ketik.operator}
          onChange={e => setKetik(k => ({ ...k, operator: e.target.value }))} className="w-full sm:w-52" />
        <Input data-testid="audit-filter-position" placeholder="Barcode posisi" value={ketik.position_barcode}
          onChange={e => setKetik(k => ({ ...k, position_barcode: e.target.value }))} className="w-full sm:w-44" />
        <SelectPenyaring data-testid="audit-filter-building" value={filters.building_id} aria-label="Gedung"
          onChange={e => setFilters(f => ({ ...f, building_id: e.target.value }))}>
          <option value="">Semua gedung</option>
          {buildings.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
        </SelectPenyaring>
        <SelectPenyaring data-testid="audit-filter-direction" value={filters.direction} searchable={false} aria-label="Arah"
          onChange={e => setFilters(f => ({ ...f, direction: e.target.value }))}>
          <option value="">Semua arah</option>
          <option value="adjust_in">Lebih (stok bertambah)</option>
          <option value="adjust_out">Kurang (stok berkurang)</option>
        </SelectPenyaring>
        <PeriodPicker value={period} onChange={setPeriod} presets={[ALL_TIME, ...PERIOD_PRESETS]} testId="audit-period" />
        <Button variant="link" className="px-1" onClick={resetFilters} data-testid="audit-reset">Atur ulang</Button>
        <Alat>
          <TombolUnduh namaBerkas="audit-trail-gudang" namaLembar="Audit trail" baris={items} ambilSemua={ambilSemua} testId="audit-export-csv"
            aksiTambahan={[{ label: 'CSV lengkap dari server', onClick: unduhCsvServer }]}
            kolom={[
              { label: 'Waktu', nilai: (r) => formatDateTimeID(r.timestamp, { fallback: '' }) },
              { label: 'Sesi', nilai: (r) => r.session_ref || '' },
              { label: 'Operator', nilai: (r) => r.created_by || '' },
              { label: 'Gedung', nilai: (r) => r.building_code || r.location_code || '' },
              { label: 'Zona', nilai: (r) => r.zone_code || '' },
              { label: 'Rak', nilai: (r) => r.rack_code || '' },
              { label: 'Barcode posisi', nilai: (r) => r.position_barcode || '' },
              { label: 'Barang', nilai: (r) => r.fg_code || '' },
              { label: 'Arah', nilai: (r) => arahDari(r.direction).label },
              { label: 'Qty', nilai: (r) => Number(r.qty || 0) },
              { label: 'Catatan', nilai: (r) => r.notes || '' },
            ]} />
          <MuatUlang loading={loading} onClick={load} testId="audit-apply-filters" />
        </Alat>
      </>}
      summary={adaStat ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Total penyesuaian" value={fmt(stats.total_adjustments)} sub="sesuai saringan" />
          <StatTile label="Lebih (surplus)" value={fmt(stats.surplus_qty)} accent="success" sub={`${fmt(stats.surplus_count)} kali`} />
          <StatTile label="Kurang (selisih hilang)" value={fmt(stats.shortage_qty)} accent="danger" sub={`${fmt(stats.shortage_count)} kali`} />
          <StatTile label="Selisih bersih" value={`${stats.net_qty > 0 ? '+' : ''}${fmt(stats.net_qty)}`}
            accent={(stats.net_qty || 0) < 0 ? 'danger' : 'default'} sub="lebih dikurangi kurang" />
        </div>
      ) : null}
      footer={page.total > page.limit ? (
        <PaginationLite page={Math.floor(page.skip / page.limit) + 1} totalPages={totalHalaman} total={page.total} pageSize={page.limit}
          onPageChange={(n) => setPage(p => ({ ...p, skip: (n - 1) * p.limit }))} />
      ) : null}>

      {adaStat && (stats.by_operator?.length > 0 || stats.by_position_hotspots?.length > 0) && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-medium text-foreground">Operator teratas</p>
              <TombolUnduh namaBerkas="audit-operator" namaLembar="Operator" baris={stats.by_operator || []} testId="audit-operator-unduh"
                kolom={[
                  { label: 'Operator', nilai: (o) => o.operator }, { label: 'Penyesuaian', nilai: (o) => Number(o.count || 0) },
                  { label: 'Lebih', nilai: (o) => Number(o.surplus_qty || 0) }, { label: 'Kurang', nilai: (o) => Number(o.shortage_qty || 0) },
                  { label: 'Terakhir aktif', nilai: (o) => formatDateTimeID(o.last_activity, { fallback: '' }) },
                ]} />
            </div>
            <TabelData kolom={kolomOperator} baris={stats.by_operator || []} kunci={(o) => o.operator} testId="audit-operator-table"
              kosong={<p className="text-sm text-muted-foreground">Tidak ada data.</p>} />
          </div>
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-medium text-foreground">Posisi paling sering disesuaikan</p>
              <TombolUnduh namaBerkas="audit-hotspot" namaLembar="Hotspot" baris={stats.by_position_hotspots || []} testId="audit-hotspot-unduh"
                kolom={[
                  { label: 'Barcode posisi', nilai: (p) => p.position_barcode }, { label: 'Kali disesuaikan', nilai: (p) => Number(p.count || 0) },
                  { label: 'Selisih bersih', nilai: (p) => Number(p.net_qty || 0) },
                ]} />
            </div>
            <TabelData kolom={kolomHotspot} baris={stats.by_position_hotspots || []} kunci={(p) => p.position_barcode} testId="audit-hotspot-table"
              kosong={<p className="text-sm text-muted-foreground">Tidak ada data.</p>} />
          </div>
        </div>
      )}

      <div className="space-y-2">
        <p className="text-sm font-medium text-foreground">Rincian penyesuaian ({fmt(page.total)})</p>
        <TabelData kolom={kolom} baris={items} testId="audit-table"
          kunci={(r) => r.id || `${r.session_id || r.session_ref}|${r.fg_code}|${r.timestamp}|${r.direction}|${r.qty}`}
          kosong={<EmptyState title={loading ? 'Memuat…' : 'Tidak ada penyesuaian pada saringan ini'}
            description={loading ? undefined : 'Penyesuaian muncul setelah hasil opname disetujui.'} />} />
      </div>

      {/* Analisa AI (popup detail) */}
      {rcaModal && (
        <DetailPopup open onClose={() => setRcaModal(null)} judul="Analisa penyebab dengan AI" keterangan={`Posisi ${rcaModal.barcode}`}
          testId="rca-modal">
          {rcaModal.loading && <p className="py-6 text-center text-sm text-muted-foreground">AI sedang menganalisis pola penyesuaian…</p>}
          {rcaModal.error && <Notice tone="danger" icon={AlertCircle}>{rcaModal.error}</Notice>}
          {rca && <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <StatTile label="Jumlah data" value={fmt(rca.data_points)} />
              <StatTile label="Lebih" value={fmt(rca.stats.surplus_qty)} />
              <StatTile label="Kurang" value={fmt(rca.stats.shortage_qty)} />
              <StatTile label="Selisih bersih" value={`${rca.stats.net_qty > 0 ? '+' : ''}${fmt(rca.stats.net_qty)}`} />
            </div>
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-sm font-medium text-foreground">Dugaan penyebab</p>
                <StatusBadge status="keyakinan" label={`Keyakinan: ${rca.analysis.confidence}`}
                  tone={rca.analysis.confidence === 'tinggi' ? 'success' : rca.analysis.confidence === 'sedang' ? 'warning' : 'muted'} />
                <StatusBadge status="risiko" label={`Risiko: ${rca.analysis.risk_level}`}
                  tone={rca.analysis.risk_level === 'tinggi' ? 'danger' : rca.analysis.risk_level === 'sedang' ? 'warning' : 'success'} />
              </div>
              <p className="text-base font-medium text-foreground">{rca.analysis.root_cause_hypothesis}</p>
              <p className="text-sm text-muted-foreground">{rca.analysis.reasoning}</p>
            </div>
            <div className="space-y-2">
              <p className="text-sm font-medium text-foreground">Tindakan yang disarankan</p>
              <ol className="list-decimal space-y-1 pl-5 text-sm">
                {(rca.analysis.recommended_actions || []).map((a, i) => <li key={i}>{a}</li>)}
              </ol>
            </div>
            <p className="text-right text-xs text-muted-foreground">Dibuat {formatDateTimeID(rca.generated_at)}</p>
          </>}
        </DetailPopup>
      )}
    </PageLayout>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// MAIN MODULE
// ══════════════════════════════════════════════════════════════════════════════
const SECTIONS = {
  structure: StructureTab,
  units: UnitsTab,
  receiving: ReceivingTab,
  audit: AuditTrailTab,
  positions: PositionsTab,
};

export default function WMSModule({ token, section, ...rest }) {
  // ── FASE E: monolit "Scanner Barcode" dipecah jadi menu terpisah ──────────────
  // Bila `section` diberikan (via registry withProps), render SATU bagian saja (kepala dari PageLayout bagian itu).
  if (section && SECTIONS[section]) {
    const Comp = SECTIONS[section];
    return <Comp token={token} />;
  }

  // ── LEGACY MONOLITH (fallback; tidak lagi ada di navigasi setelah Fase E) ──────
  return (
    <HubTabs
      {...rest}
      token={token}
      hubId="wms-module"
      title="Gudang (WMS)"
      subtitle="Struktur gudang, satuan, scan gudang, audit trail, dan posisi barang."
      tabs={[
        { key: 'structure', label: 'Struktur gudang', Component: StructureTab },
        { key: 'units', label: 'Satuan & konversi', Component: UnitsTab },
        { key: 'receiving', label: 'Scan gudang', Component: ReceivingTab },
        { key: 'audit', label: 'Audit trail', Component: AuditTrailTab },
        { key: 'positions', label: 'Posisi & cari', Component: PositionsTab },
      ]}
    />
  );
}

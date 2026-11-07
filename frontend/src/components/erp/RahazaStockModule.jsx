/**
 * Stok & pergerakan (tab di hub Stok & Akurasi) — stok kanonik per barang × lokasi, penerimaan, pindah lokasi,
 * penyesuaian cepat, dan mutasi terakhir.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout (di hub judul tersembunyi, tombol pindah ke baris tab), penyaring
 * satu baris, StatTile berketerangan, form Penerimaan / Pindah lokasi / Sesuaikan stok = FormPopup pendek
 * (dulu Modal dan popover kecil), mutasi terakhir = tabel + unduh Excel/CSV, label Indonesia.
 *
 * Verifikasi angka (8 Nov 2026, DB uji):
 *  • Kartu Bahan/Aksesoris/Produk jadi dulu menampilkan JUMLAH qty lintas satuan (kg + m + yard; pcs + pack + roll)
 *    → angka tanpa arti ("0.00", "-1"). Kini nilainya = jumlah baris stok (`row_count` /material-stock/summary);
 *    total qty hanya disebut untuk produk jadi (selalu pcs).
 *  • "Low Stock 0" dulu memakai `low_stock_count` yang hanya melihat barang yang SUDAH punya baris stok, padahal
 *    43 barang berambang stoknya 0 (tanpa baris) → 0 menyesatkan. Kini = jumlah /materials/reorder-alerts (43),
 *    aturan yang sama dengan Alert & Reorder dan notifikasi.
 *  • Kolom Status dulu "OK" (hijau) untuk barang berambang yang stoknya 0, karena server tidak mengisi `below_min`
 *    pada baris tanpa stok. Kini status dihitung dari qty & stok minimum yang sudah dikirim server.
 */
import { useState, useEffect, useCallback } from 'react';
import { Package, ArrowDown, ArrowRightLeft, AlertTriangle, PlusCircle, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { GlassCard } from '@/components/ui/glass';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { typeToCategory } from '@/lib/itemTaxonomy';
import { todayWIB } from '@/lib/waktu';
import { formatDateTimeID } from '@/lib/format';
import { DataTable } from './DataTableV2';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';

// Tampilan per 3 kategori bisnis (Bahan/Aksesoris/Produk jadi).
const CAT_LABEL = { bahan: 'Bahan', aksesoris: 'Aksesoris', fg: 'Produk jadi' };
const JENIS_MUTASI = { receive: 'Terima', issue: 'Keluar', transfer: 'Pindah lokasi', adjust: 'Penyesuaian', opname: 'Opname' };
const fmtNum = (v, d = 2) => Number(v || 0).toLocaleString('id-ID', { maximumFractionDigits: d });

// W1 (sesi #29) — pilihan filter dibangun dari nilai yang BENAR-BENAR ADA di data.
// Daftar hardcode akan menyesatkan (mis. warna yang tidak dipakai satu pun barang),
// dan menghitungnya dari string SKU akan salah — sumbernya master barang.
function uniqOptions(rows, field) {
  const seen = new Set();
  (rows || []).forEach(r => {
    const v = (r?.[field] || '').trim();
    if (v) seen.add(v);
  });
  return [...seen].sort((a, b) => a.localeCompare(b)).map(v => ({ value: v, label: v }));
}

// Status baris dihitung dari qty & stok minimum yang dikirim server (lihat catatan verifikasi di atas).
const minStok = (r) => Number(r.min_stock_qty || r.min_stock || 0);
function statusBaris(r) {
  const qty = Number(r.qty || 0);
  const min = minStok(r);
  if (qty < 0) return 'minus';
  if (min > 0 && qty < min) return 'kurang';
  if (qty === 0) return 'kosong';
  if (min > 0) return 'aman';
  return 'ada';
}
const STATUS = {
  minus: { label: 'Minus', tone: 'danger' },
  kurang: { label: 'Di bawah minimum', tone: 'warning' },
  kosong: { label: 'Kosong', tone: 'muted' },
  aman: { label: 'Aman', tone: 'success' },
  ada: { label: 'Ada stok', tone: 'default' },
};

/** Sesuaikan stok ± (dulu popover kecil di baris) — kini FormPopup pendek; isian & kiriman sama. */
function QuickAdjustPopover({ row, token, onClose, onDone }) {
  const [delta, setDelta] = useState('');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [galat, setGalat] = useState('');

  useEffect(() => { setDelta(''); setNotes(''); setGalat(''); }, [row]);

  const submit = async () => {
    const qty = Number(delta);
    if (!qty || qty === 0) { setGalat('Perubahan qty tidak boleh 0.'); return; }
    setSaving(true); setGalat('');
    try {
      const r = await fetch('/api/rahaza/material-adjust', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        // 2026-11-06 (pola P1): server (rahaza_inventory_stock.material_adjust) membaca `qty` dan `reason`.
        // Dulu dikirim `qty_delta`/`notes` → qty terbaca 0 → server selalu menolak "qty (≠0) wajib".
        body: JSON.stringify({
          material_id: row.material_id,
          location_id: row.location_id,
          qty,
          reason: notes || (qty > 0 ? 'Penyesuaian cepat +' : 'Penyesuaian cepat -'),
        }),
      });
      if (r.ok) {
        toast.success(`Stok ${row.material_code} disesuaikan ${qty > 0 ? '+' : ''}${qty} ${row.unit}.`);
        onClose();
        onDone();
      } else {
        const d = await r.json().catch(() => ({}));
        setGalat(typeof d.detail === 'string' ? d.detail : `Gagal menyesuaikan (HTTP ${r.status})`);
      }
    } finally { setSaving(false); }
  };

  return (
    <FormPopup open={!!row} onClose={onClose} ukuran="pendek" judul="Sesuaikan stok" onSimpan={submit}
      menyimpan={saving} galat={galat} bisaSimpan={!!delta} testId="stock-adjust-form"
      keterangan={row ? `${row.material_code} · ${row.location_code || ''} · stok sekarang ${fmtNum(row.qty, 3)} ${row.unit || ''}` : ''}>
      {row && <>
        <Isian label="Perubahan qty (+/−)" wajib htmlFor="stock-adjust-delta" petunjuk="Contoh: 10 untuk menambah, -5 untuk mengurangi.">
          <Input id="stock-adjust-delta" type="number" step="0.001" inputMode="decimal" placeholder="+10 atau -5" value={delta}
            onChange={e => setDelta(e.target.value)} className="tabular-nums" autoFocus
            data-testid={`stock-adjust-delta-${row.material_code}`} />
        </Isian>
        <Isian label="Alasan" htmlFor="stock-adjust-notes">
          <Input id="stock-adjust-notes" placeholder="Opsional" value={notes} onChange={e => setNotes(e.target.value)}
            data-testid={`stock-adjust-notes-${row.material_code}`} />
        </Isian>
      </>}
    </FormPopup>
  );
}

export default function RahazaStockModule({ token }) {
  const [stocks, setStocks] = useState([]);
  const [summary, setSummary] = useState(null);
  const [movements, setMovements] = useState([]);
  const [materials, setMaterials] = useState([]);
  const [locations, setLocations] = useState([]);
  const [reorderAlerts, setReorderAlerts] = useState([]);
  const [filterLocation, setFilterLocation] = useState('');  // U5
  // W1 (sesi #29) — saklar "tampilkan juga yang stoknya 0". Layar ini menampilkan
  // BARIS STOK, dan hanya ±26 dari 321 barang jadi punya baris stok ⇒ daftarnya
  // tampak "tidak sinkron" dengan Master Item Produk Jadi. Dengan saklar ini
  // barang master yang belum pernah punya stok ikut tampil (qty 0).
  // 2026-09-24 keputusan owner: barang master ber-qty 0 ikut tampil secara bawaan
  const [showZero, setShowZero] = useState(true);
  const [loading, setLoading] = useState(true);
  const [termuat, setTermuat] = useState(false);
  const [receiveOpen, setReceiveOpen] = useState(false);
  const [transferOpen, setTransferOpen] = useState(false);
  const [adjustRow, setAdjustRow] = useState(null);
  const [receiveForm, setReceiveForm] = useState({ material_id: '', location_id: '', qty: '', notes: '' });
  const [transferForm, setTransferForm] = useState({ material_id: '', from_location_id: '', to_location_id: '', qty: '', notes: '' });
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState('');

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [stkRes, sumRes, mvRes, reorderRes] = await Promise.all([
        fetch(`/api/rahaza/material-stock${showZero ? '?include_zero=1' : ''}`, { headers }).then(r => r.ok ? r.json() : []),
        fetch('/api/rahaza/material-stock/summary', { headers }).then(r => r.ok ? r.json() : null),
        fetch('/api/rahaza/material-movements?limit=30', { headers }).then(r => r.ok ? r.json() : []),
        fetch('/api/rahaza/materials/reorder-alerts', { headers }).then(r => r.ok ? r.json() : []),
      ]);
      // Ensure each stock row has a stable unique key (id may be missing in some seed rows).
      const normalizedStocks = (Array.isArray(stkRes) ? stkRes : []).map((s, i) => ({
        ...s,
        _key: s.id || `${s.material_id || 'm'}-${s.location_id || 'l'}-${i}`,
        _status: statusBaris(s),
      }));
      setStocks(normalizedStocks); setSummary(sumRes);
      setMovements(Array.isArray(mvRes) ? mvRes : []); setReorderAlerts(Array.isArray(reorderRes) ? reorderRes : []);
    } finally { setLoading(false); setTermuat(true); }
  }, [token, showZero]);

  useEffect(() => {
    const h = { Authorization: `Bearer ${token}` };
    Promise.all([
      fetch('/api/rahaza/materials', { headers: h }).then(r => r.ok ? r.json() : []),
      // FASE C: sumber lokasi = daftar STORAGE terpadu (zona kanonik wh_* + legacy storage
      // yang belum termigrasi). Zona produksi (cutting/sewing/qc/packing) TIDAK muncul.
      fetch('/api/rahaza/storage-locations', { headers: h }).then(r => r.ok ? r.json() : []),
    ]).then(([m, l]) => { setMaterials((m || []).filter(x => x.active)); setLocations(Array.isArray(l) ? l : []); });
  }, [token]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // Fase C: filter lokasi = lokasi yang benar-benar punya stok. Nama/kode diambil dari
  // baris stok (sudah di-resolve backend lintas skema: rahaza_locations LAMA + wh_* BARU),
  // fallback ke daftar storage. Form receive/transfer/adjust pakai daftar storage terpadu.
  const locById = Object.fromEntries(locations.map(l => [l.id, l]));
  const stockLocMeta = {};
  stocks.forEach(s => {
    if (s.location_id && !stockLocMeta[s.location_id]) {
      stockLocMeta[s.location_id] = {
        code: s.location_code || locById[s.location_id]?.code || String(s.location_id).slice(0, 12),
        name: s.location_name || locById[s.location_id]?.name || '',
      };
    }
  });
  const stockFilterLocations = Object.entries(stockLocMeta)
    .map(([id, meta]) => ({ id, ...meta }))
    .sort((a, b) => a.code.localeCompare(b.code));

  // 2026-11-07 (Tahap 5): transfer — material DIBATASI pada yang punya stok di lokasi asal (dulu semua 1.700+
  // material tampil, lalu server menolak "stok kurang"), dan stok tersedianya ditampilkan.
  const stockAt = (matId, locId) => stocks
    .filter(s => s.material_id === matId && s.location_id === locId)
    .reduce((t, s) => t + Number(s.qty || 0), 0);
  // Baris stok bisa tercatat pada id lokasi lama (sebelum migrasi zona); bila lokasi asal TIDAK punya satu
  // pun baris stok ber-id sama, daftar tetap lengkap (perilaku lama) dan server yang memeriksa stoknya.
  const fromHasRows = !!transferForm.from_location_id && stocks.some(s => s.location_id === transferForm.from_location_id);
  const transferMaterials = fromHasRows
    ? materials.filter(m => stockAt(m.id, transferForm.from_location_id) > 0)
    : materials;
  const transferAvail = fromHasRows && transferForm.material_id
    ? stockAt(transferForm.material_id, transferForm.from_location_id) : null;

  const openReceive = () => { setReceiveForm({ material_id: '', location_id: '', qty: '', notes: '' }); setFormError(''); setReceiveOpen(true); };
  const openTransfer = () => { setTransferForm({ material_id: '', from_location_id: '', to_location_id: '', qty: '', notes: '' }); setFormError(''); setTransferOpen(true); };

  const doReceive = async () => {
    setSaving(true); setFormError('');
    try {
      if (!receiveForm.material_id || !receiveForm.location_id || !(Number(receiveForm.qty) > 0)) throw new Error('Pilih material, lokasi, dan isi qty > 0.');
      const r = await fetch('/api/rahaza/material-receive', { method: 'POST', headers, body: JSON.stringify({ ...receiveForm, qty: Number(receiveForm.qty) }) });
      if (!r.ok) {
        // 2026-11-07 (Tahap 5): tampilkan alasan dari server (dulu disamarkan "Data tidak valid.")
        const d = await r.json().catch(() => ({}));
        const STATUS_MSG = { 400: 'Data tidak valid.', 403: 'Tidak ada akses.', 404: 'Material/Lokasi tidak ditemukan.' };
        throw new Error(typeof d.detail === 'string' ? d.detail : (STATUS_MSG[r.status] || `Gagal simpan (HTTP ${r.status})`));
      }
      setReceiveOpen(false); fetchAll();
    } catch (e) { setFormError(e.message); }
    finally { setSaving(false); }
  };

  const doTransfer = async () => {
    setSaving(true); setFormError('');
    try {
      if (!transferForm.material_id || !transferForm.from_location_id || !transferForm.to_location_id) throw new Error('Lengkapi material & kedua lokasi.');
      if (transferForm.from_location_id === transferForm.to_location_id) throw new Error('Lokasi asal dan tujuan tidak boleh sama.');
      if (!(Number(transferForm.qty) > 0)) throw new Error('Qty harus > 0.');
      if (transferAvail != null && Number(transferForm.qty) > transferAvail + 1e-9) {
        throw new Error(`Stok di lokasi asal hanya ${transferAvail.toLocaleString('id-ID')} — qty transfer melebihi stok.`);
      }
      const r = await fetch('/api/rahaza/material-transfer', { method: 'POST', headers, body: JSON.stringify({ ...transferForm, qty: Number(transferForm.qty) }) });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        const STATUS_MSG = { 400: 'Data tidak valid / stok kurang.', 403: 'Tidak ada akses.' };
        throw new Error(typeof d.detail === 'string' ? d.detail : (STATUS_MSG[r.status] || `Gagal transfer (HTTP ${r.status})`));
      }
      setTransferOpen(false); fetchAll();
    } catch (e) { setFormError(e.message); }
    finally { setSaving(false); }
  };

  const nKosong = stocks.filter(s => s.no_stock_row).length;
  const cat = (t) => summary?.by_category?.[t] || {};
  const barisTampil = filterLocation ? stocks.filter(s => s.location_id === filterLocation) : stocks;

  const kolomMutasi = [
    { kunci: 'waktu', label: 'Waktu', hp: 'keterangan', isi: (m) => <span className="text-sm md:whitespace-nowrap">{formatDateTimeID(m.timestamp)}</span> },
    // 2026-11-02 (K9): mutasi mesin opname tunggal tampil sebagai 'Opname'
    { kunci: 'jenis', label: 'Jenis', isi: (m) => (m.type === 'opname' ? 'Opname' : (JENIS_MUTASI[m.type] || 'Mutasi')) },
    { kunci: 'barang', label: 'Barang', hp: 'judul', isi: (m) => <span className="font-medium">{m.material_code}</span> },
    { kunci: 'qty', label: 'Qty', rata: 'kanan', isi: (m) => <span className="tabular-nums md:whitespace-nowrap">{fmtNum(m.qty, 3)} {m.unit || ''}</span> },
    { kunci: 'dari', label: 'Dari', isi: (m) => <span className="text-sm text-muted-foreground">{m.from_location_name || '—'}</span> },
    { kunci: 'ke', label: 'Ke', isi: (m) => <span className="text-sm text-muted-foreground">{m.to_location_name || '—'}</span> },
    { kunci: 'ref', label: 'Catatan', isi: (m) => <span className="block max-w-[14rem] truncate text-sm text-muted-foreground" title={m.notes || m.ref_type || ''}>{m.notes || m.ref_type || '—'}</span> },
  ];

  return (
    <PageLayout testId="rahaza-stock-page" title="Stok & pergerakan"
      subtitle="Stok bahan, aksesoris, dan produk jadi per lokasi. Penerimaan dan pindah lokasi tercatat di buku stok."
      actions={<>
        <Button variant="outline" onClick={openTransfer} data-testid="stock-transfer-btn"><ArrowRightLeft />Pindah lokasi</Button>
        <Button onClick={openReceive} data-testid="stock-receive-btn"><ArrowDown />Penerimaan</Button>
      </>}
      filters={<>
        <SmartNativeSelect value={filterLocation} onChange={e => setFilterLocation(e.target.value)} className="w-full" wrapperClassName="w-full sm:w-52"
          aria-label="Lokasi" data-testid="stock-loc-filter" searchable={stockFilterLocations.length > 8}>
          <option value="">Semua lokasi</option>
          {stockFilterLocations.map(l => <option key={l.id} value={l.id}>{l.name ? `${l.code} · ${l.name}` : l.code}</option>)}
        </SmartNativeSelect>
        <label className="inline-flex h-9 cursor-pointer select-none items-center gap-2 text-sm text-foreground/80"
          title="Barang master yang belum punya baris stok ikut ditampilkan dengan qty 0 — supaya daftar bisa disamakan dengan Master Item Produk jadi.">
          <Checkbox checked={showZero} onCheckedChange={v => setShowZero(v === true)} data-testid="stock-show-zero-toggle"
            aria-label="Tampilkan juga yang stoknya 0" />
          Tampilkan juga yang stoknya 0
          {showZero && termuat && (
            <span className="text-xs text-muted-foreground" data-testid="stock-zero-count">({fmtNum(nKosong, 0)} barang belum punya stok)</span>
          )}
        </label>
      </>}
      tools={
        <Button variant="outline" size="icon" onClick={fetchAll} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="stock-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      }
      summary={<>
        {summary && (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {['bahan', 'aksesoris'].map(t => (
              <StatTile key={t} testId={`stock-summary-${t}`} label={`${CAT_LABEL[t]} · baris stok`}
                value={fmtNum(cat(t).row_count, 0)}
                sub="Baris barang × lokasi. Qty tidak dijumlah karena satuannya berbeda." />
            ))}
            <StatTile testId="stock-summary-fg" label="Produk jadi · baris stok" value={fmtNum(cat('fg').row_count, 0)}
              sub={`Total ${fmtNum(cat('fg').total_qty, 0)} pcs di semua lokasi.`}
              subTone={Number(cat('fg').total_qty || 0) < 0 ? 'danger' : undefined} />
            <StatTile testId="stock-summary-low" label="Di bawah ambang stok" value={fmtNum(reorderAlerts.length, 0)}
              accent={reorderAlerts.length > 0 ? 'warning' : 'default'}
              sub="Barang berambang yang stoknya di bawah minimum / titik pesan ulang." />
          </div>
        )}
        {/* U8 — dulu deretan 43 pil kode barang; rinciannya ada di Alert & Reorder (tabel + unduh). */}
        {reorderAlerts.length > 0 && (
          <Notice tone="warning" icon={AlertTriangle} testId="reorder-alert-banner"
            title={`${fmtNum(reorderAlerts.length, 0)} barang perlu dipesan ulang`}
            action={<Button variant="link" className="h-auto p-0" onClick={() => {
              if (window.location.hash === '#warehouse-smart') window.location.hash = '';
              window.location.hash = '#warehouse-smart';
            }}>Lihat di Alert & Reorder</Button>}>
            Terbesar: {reorderAlerts.slice(0, 3).map(a => `${a.code} (butuh ${fmtNum(a.shortage)} ${a.unit})`).join(', ')}.
          </Notice>
        )}
      </>}>
      {!termuat ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat stok…</p>
      ) : (
        <DataTable
          tableId="stock"
          loading={loading}
          rowKey="_key"
          rows={barisTampil}
          searchFields={['material_code', 'material_name', 'location_code', 'location_name',
                         'category_name', 'color_name', 'option_name', 'size_code']}
          filters={[
            { key: 'material_type', label: 'Jenis', type: 'select',
              accessor: (r) => typeToCategory(r.material_type),
              options: [
                { value: 'bahan', label: 'Bahan' },
                { value: 'aksesoris', label: 'Aksesoris' },
                { value: 'fg', label: 'Produk jadi' },
              ] },
            // W1 — filter identitas barang. Pilihannya dibangun dari data yang benar-benar
            // ada (bukan daftar hardcode) supaya tidak ada opsi kosong yang menyesatkan.
            { key: 'category_name', label: 'Kategori', type: 'select',
              accessor: (r) => r.category_name || '—',
              options: uniqOptions(stocks, 'category_name') },
            { key: 'color_name', label: 'Warna', type: 'select',
              accessor: (r) => r.color_name || '—',
              options: uniqOptions(stocks, 'color_name') },
            { key: 'option_name', label: 'Opsi', type: 'select',
              accessor: (r) => r.option_name || '—',
              options: uniqOptions(stocks, 'option_name') },
            { key: 'status', label: 'Status', type: 'select',
              accessor: (r) => r._status,
              options: Object.entries(STATUS).map(([value, s]) => ({ value, label: s.label })) },
          ]}
          columns={[
            { key: 'material_code', label: 'Barang', sortable: true,
              render: (r) => (
                <div className="min-w-0 max-w-[18rem]">
                  <div className="font-medium">{r.material_code}</div>
                  <div className="text-xs text-muted-foreground">{r.material_name}</div>
                </div>
              ) },
            { key: 'category_name', label: 'Kategori', sortable: true,
              accessor: (r) => r.category_name || '',
              render: (r) => <span className="text-sm">{r.category_name || '—'}</span> },
            { key: 'color_name', label: 'Warna', sortable: true,
              accessor: (r) => r.color_name || '',
              render: (r) => (
                <span className="text-sm">
                  {r.color_name || '—'}
                  {r.size_code ? <span className="text-muted-foreground"> · {r.size_code}</span> : null}
                </span>
              ) },
            { key: 'option_name', label: 'Opsi', sortable: true,
              accessor: (r) => r.option_name || '',
              render: (r) => <span className="text-sm text-muted-foreground">{r.option_name || '—'}</span> },
            { key: 'material_type', label: 'Jenis', sortable: true,
              accessor: (r) => CAT_LABEL[typeToCategory(r.material_type)] || '',
              render: (r) => <span className="text-sm">{CAT_LABEL[typeToCategory(r.material_type)] || '—'}</span> },
            { key: 'location', label: 'Lokasi', sortable: true,
              accessor: (r) => r.location_code ? `${r.location_code} · ${r.location_name || ''}` : '',
              render: (r) => r.location_code
                ? <span className="text-sm">{r.location_code} · {r.location_name}</span>
                : <span className="text-sm text-muted-foreground">Belum ada baris stok</span> },
            { key: 'qty', label: 'Qty', align: 'right', sortable: true,
              render: (r) => (
                <span className={`tabular-nums font-medium whitespace-nowrap ${Number(r.qty) < 0 ? 'text-[hsl(var(--danger-text))]' : ''}`}>
                  {fmtNum(r.qty, r.unit === 'kg' ? 3 : 2)} <span className="text-xs font-normal text-muted-foreground">{r.unit}</span>
                </span>) },
            { key: 'min_stock', label: 'Stok minimum', align: 'right', sortable: true,
              accessor: (r) => minStok(r),
              render: (r) => <span className="tabular-nums text-muted-foreground">{minStok(r) ? fmtNum(minStok(r)) : '—'}</span> },
            { key: 'status', label: 'Status',
              accessor: (r) => STATUS[r._status]?.label || '',
              render: (r) => <StatusBadge status={r._status} label={STATUS[r._status]?.label} tone={STATUS[r._status]?.tone} /> },
            { key: '_adjust', label: 'Sesuaikan', align: 'right',
              accessor: () => '',
              render: (r) => (
                // Baris tanpa lokasi (belum punya baris stok) tidak bisa disesuaikan:
                // penyesuaian WAJIB menyebut lokasi. Pakai "Penerimaan" untuk memulai.
                r.location_id
                  ? <Button size="icon-sm" variant="ghost" onClick={() => setAdjustRow(r)}
                      title="Sesuaikan stok ±" aria-label="Sesuaikan stok" data-testid={`stock-adjust-btn-${r.material_code}`}>
                      <PlusCircle />
                    </Button>
                  : <span className="text-xs text-muted-foreground" title="Penyesuaian butuh lokasi. Mulai dari Penerimaan.">—</span>
              ) },
          ]}
          emptyTitle="Belum ada stok"
          emptyDescription='Mulai dari "Penerimaan" untuk menambah stok ke lokasi.'
          emptyIcon={Package}
          exportFilename={`stok-material-${todayWIB()}.csv`}
        />
      )}

      {/* Mutasi terakhir (buku stok) */}
      <GlassCard className="space-y-3 p-4" data-testid="stock-movements">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <p className="text-base font-semibold text-foreground">Mutasi terakhir</p>
            <p className="text-sm text-muted-foreground">30 mutasi stok terbaru dari buku stok.</p>
          </div>
          <TombolUnduh namaBerkas="mutasi-stok-terakhir" namaLembar="Mutasi" baris={movements} testId="stock-movements-unduh"
            kolom={[
              { label: 'Waktu', nilai: (m) => formatDateTimeID(m.timestamp) },
              { label: 'Jenis', nilai: (m) => JENIS_MUTASI[m.type] || 'Mutasi' },
              { label: 'Kode barang', nilai: (m) => m.material_code },
              { label: 'Qty', nilai: (m) => Number(m.qty || 0) },
              { label: 'Satuan', nilai: (m) => m.unit || '' },
              { label: 'Dari', nilai: (m) => m.from_location_name || '' },
              { label: 'Ke', nilai: (m) => m.to_location_name || '' },
              { label: 'Catatan', nilai: (m) => m.notes || m.ref_type || '' },
            ]} />
        </div>
        <TabelData kolom={kolomMutasi} baris={movements} kunci={(m) => m.id || `${m.timestamp}-${m.material_code}`}
          testId="stock-movements-tabel"
          kosong={<EmptyState title="Belum ada mutasi" description="Mutasi tercatat saat barang diterima, dipindah, dikeluarkan, atau disesuaikan." />} />
      </GlassCard>

      {/* Penerimaan (FormPopup pendek) */}
      <FormPopup open={receiveOpen} onClose={() => setReceiveOpen(false)} ukuran="pendek" judul="Penerimaan material"
        keterangan="Menambah stok barang ke lokasi tujuan." onSimpan={doReceive} menyimpan={saving} galat={formError}
        labelSimpan="Simpan penerimaan" testId="receive-form">
        <Isian label="Material" wajib htmlFor="receive-material">
          <SmartNativeSelect id="receive-material" value={receiveForm.material_id} onChange={e => setReceiveForm({ ...receiveForm, material_id: e.target.value })}
            className="w-full" data-testid="receive-material">
            <option value="">Pilih material</option>
            {materials.map(m => <option key={m.id} value={m.id}>{`${m.code} · ${m.name} (${m.unit})`}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Lokasi tujuan" wajib htmlFor="receive-location">
          <SmartNativeSelect id="receive-location" value={receiveForm.location_id} onChange={e => setReceiveForm({ ...receiveForm, location_id: e.target.value })}
            className="w-full" data-testid="receive-location">
            <option value="">Pilih lokasi</option>
            {locations.map(l => <option key={l.id} value={l.id}>{`${l.code} · ${l.name}`}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Qty" wajib htmlFor="receive-qty">
          <Input id="receive-qty" type="number" step="0.001" inputMode="decimal" value={receiveForm.qty}
            onChange={e => setReceiveForm({ ...receiveForm, qty: e.target.value })} placeholder="0" data-testid="receive-qty" />
        </Isian>
        <Isian label="Catatan" htmlFor="receive-notes">
          <Input id="receive-notes" value={receiveForm.notes} onChange={e => setReceiveForm({ ...receiveForm, notes: e.target.value })}
            placeholder="No. surat jalan, pemasok, dsb." />
        </Isian>
      </FormPopup>

      {/* Pindah lokasi (FormPopup pendek) */}
      <FormPopup open={transferOpen} onClose={() => setTransferOpen(false)} ukuran="pendek" judul="Pindah lokasi"
        keterangan="Memindahkan stok dari satu lokasi gudang ke lokasi lain." onSimpan={doTransfer} menyimpan={saving}
        galat={formError} labelSimpan="Pindahkan" testId="transfer-form">
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Dari lokasi" wajib htmlFor="transfer-from">
            <SmartNativeSelect id="transfer-from" value={transferForm.from_location_id} onChange={e => {
              const v = e.target.value;
              // material yang sudah dipilih tetap bila masih ada stoknya di lokasi asal baru
              const rows = stocks.some(s => s.location_id === v);
              setTransferForm(f => ({ ...f, from_location_id: v,
                material_id: f.material_id && (!rows || stockAt(f.material_id, v) > 0) ? f.material_id : '' }));
            }} className="w-full" data-testid="transfer-from">
              <option value="">Pilih lokasi</option>
              {locations.map(l => <option key={l.id} value={l.id}>{`${l.code} · ${l.name}`}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Ke lokasi" wajib htmlFor="transfer-to">
            <SmartNativeSelect id="transfer-to" value={transferForm.to_location_id} onChange={e => setTransferForm({ ...transferForm, to_location_id: e.target.value })}
              className="w-full" data-testid="transfer-to">
              <option value="">Pilih lokasi</option>
              {locations.filter(l => l.id !== transferForm.from_location_id).map(l => <option key={l.id} value={l.id}>{`${l.code} · ${l.name}`}</option>)}
            </SmartNativeSelect>
          </Isian>
        </div>
        <Isian label="Material" wajib htmlFor="transfer-material"
          petunjuk={transferAvail != null ? undefined : 'Pilih lokasi asal dulu agar daftar hanya berisi barang yang ada stoknya.'}>
          <SmartNativeSelect id="transfer-material" value={transferForm.material_id} onChange={e => setTransferForm({ ...transferForm, material_id: e.target.value })}
            className="w-full" data-testid="transfer-material">
            <option value="">{fromHasRows && !transferMaterials.length ? 'Tidak ada stok di lokasi asal' : 'Pilih material'}</option>
            {transferMaterials.map(m => <option key={m.id} value={m.id}>{`${m.code} · ${m.name} (${m.unit})`}</option>)}
          </SmartNativeSelect>
          {transferAvail != null && (
            <p className="text-xs text-muted-foreground" data-testid="transfer-available">
              Stok di lokasi asal: <span className="tabular-nums font-medium text-foreground">{transferAvail.toLocaleString('id-ID')}</span>
            </p>
          )}
        </Isian>
        <Isian label="Qty" wajib htmlFor="transfer-qty">
          <Input id="transfer-qty" type="number" step="0.001" inputMode="decimal" value={transferForm.qty}
            onChange={e => setTransferForm({ ...transferForm, qty: e.target.value })} placeholder="0" data-testid="transfer-qty" />
        </Isian>
        <Isian label="Catatan" htmlFor="transfer-notes">
          <Input id="transfer-notes" value={transferForm.notes} onChange={e => setTransferForm({ ...transferForm, notes: e.target.value })} placeholder="Opsional" />
        </Isian>
      </FormPopup>

      <QuickAdjustPopover row={adjustRow} token={token} onClose={() => setAdjustRow(null)} onDone={fetchAll} />
    </PageLayout>
  );
}

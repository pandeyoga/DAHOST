/**
 * Penyimpanan (put-away) — tempatkan stok yang belum dirak ke gudang › zona › rak › bin.
 *
 * Standar UI/UX v2 (8 Nov 2026): daftar barang belum dirak = tabel (kartu ringkas di HP, dulu kartu besar
 * berulang di kolom sempit); memilih barang (klik baris atau scan kodenya) membuka FORM POPUP "Tempatkan di
 * bin" berisi scan bin, pilihan manual, dan qty — dulu tiga kartu berdampingan di halaman. Aturan, API,
 * dan pesan sama seperti sebelumnya.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { BarisDetail } from '@/components/ui/detail-popup';
import { toast } from 'sonner';
import { MapPin, Search, RefreshCw, Warehouse, ArrowDownToLine, CheckCircle2, PackageOpen } from 'lucide-react';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice } from './moduleAtoms';
import useUomOptions from '@/hooks/useUomOptions';
import { UomSelect, UomConversionHint, toBaseQty, baseUnitOf } from './uom/UomPicker';
import UniversalScanner from './scanner/UniversalScanner';
import { sameScanCode, scanFeedback } from './scanner/scanCode';

const fmtNum = (v) => (v || 0).toLocaleString('id-ID');
const CAT_ORDER = ['bahan', 'aksesoris', 'fg'];

/**
 * Kotak scan di dalam FormPopup: kamera/ketik manual punya <form> sendiri (portal) yang kirimnya merambat
 * lewat pohon React ke form popup — ditahan di sini supaya scan TIDAK ikut menekan "Simpan". Enter di kotak
 * scan juga tidak mengirim form popup (scanner sendiri yang memproses Enter).
 */
function PenahanKirim({ children }) {
  return (
    <div onSubmit={(e) => e.stopPropagation()}
      onKeyDown={(e) => { if (e.key === 'Enter' && e.target.tagName === 'INPUT') e.preventDefault(); }}>
      {children}
    </div>
  );
}

export default function PutAwayModule({ token, onNavigate }) {
  const [groups, setGroups] = useState({ bahan: [], aksesoris: [], fg: [] });
  const [labels, setLabels] = useState({ bahan: 'Bahan', aksesoris: 'Aksesoris', fg: 'Produk Jadi' });
  const [loc, setLoc] = useState({ buildings: [], zones: [], racks: [], positions: [] });
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState(null);       // pending item → popup terbuka
  const [placements, setPlacements] = useState(null);    // {onhand,placed,unshelved,positions}
  const [bldg, setBldg] = useState('');
  const [zone, setZone] = useState('');
  const [rack, setRack] = useState('');
  const [binId, setBinId] = useState('');
  const [qty, setQty] = useState(0);
  const [inputUom, setInputUom] = useState('');   // satuan hitung fisik operator
  const [message, setMessage] = useState(null);   // hasil simpan terakhir (berhasil) — di atas daftar
  const [galat, setGalat] = useState('');         // galat simpan — di kaki popup
  const [saving, setSaving] = useState(false);
  // 2026-11-06 (audit layar scan Gudang): hasil scan tampil TEPAT di bawah kotak scannya (ScanResult).
  const [itemScan, setItemScan] = useState(null);   // kotak scan barang (halaman)
  const [binScan, setBinScan] = useState(null);     // kotak scan bin (popup)

  // Satuan yang sah untuk material terpilih (kemasan master + konversi global)
  const { options: uomOpts } = useUomOptions(selected ? [selected.material_id] : []);
  const uomOpt = selected ? uomOpts[selected.material_id] : null;
  const baseUnit = baseUnitOf(uomOpt, selected?.unit || '');
  const effUom = inputUom || baseUnit;
  const qtyBase = uomOpt ? toBaseQty(uomOpt, qty, effUom) : Number(qty || 0);
  const overLimit = selected && qtyBase != null && qtyBase > Number(selected.unshelved || 0) + 1e-6;

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const flash = (type, text) => {
    if (type === 'error') { setGalat(text); return; }
    setMessage({ type, text });
    setTimeout(() => setMessage(null), 6000);
  };

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const qs = search ? `?search=${encodeURIComponent(search)}` : '';
      const [pRes, lRes] = await Promise.all([
        fetch(`/api/wms/putaway/pending${qs}`, { headers: { Authorization: `Bearer ${token}` } }),
        fetch('/api/wms/putaway/locations', { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      if (pRes.ok) { const d = await pRes.json(); setGroups(d.groups || { bahan: [], aksesoris: [], fg: [] }); setLabels(d.labels || labels); }
      if (lRes.ok) setLoc(await lRes.json());
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, search]);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { fetchData(); }, []);

  const loadPlacements = useCallback(async (materialId) => {
    try {
      const r = await fetch(`/api/wms/putaway/placements/${materialId}`, { headers: { Authorization: `Bearer ${token}` } });
      if (r.ok) setPlacements(await r.json());
    } catch (e) { console.error(e); }
  }, [token]);

  const selectItem = (item) => {
    setSelected(item); setQty(item.unshelved); setInputUom('');
    setBldg(''); setZone(''); setRack(''); setBinId('');
    setPlacements(null); loadPlacements(item.material_id);
    setBinScan(null);   // hasil scan bin milik barang sebelumnya
    setGalat('');
  };
  const tutupPopup = () => {
    if (saving) return;
    setSelected(null); setBinId(''); setBinScan(null); setGalat(''); setPlacements(null);
  };

  // Cascade filtering
  const zonesForBldg = useMemo(() => loc.zones.filter((z) => !bldg || z.building_id === bldg), [loc.zones, bldg]);
  const racksForZone = useMemo(() => loc.racks.filter((r) => !zone || r.zone_id === zone), [loc.racks, zone]);
  const binsForRack = useMemo(() => {
    let list = loc.positions.filter((p) => !rack || p.rack_id === rack);
    if (selected) list = list.filter((p) => p.is_empty || p.material_id === selected.material_id);
    return list;
  }, [loc.positions, rack, selected]);

  const selectedBin = useMemo(() => loc.positions.find((p) => p.id === binId) || null, [loc.positions, binId]);
  // 2026-11-06 (Tahap 2): stok belum dirak dihitung PER ZONA; bin hanya boleh diisi dari zona bin itu.
  const zonesOfSelected = selected?.zones || [];
  const binZoneLeft = selectedBin
    ? (zonesOfSelected.find((z) => z.zone_id === selectedBin.zone_id)?.unshelved || 0) : null;

  // 2026-11-02 (Paket 3a): komponen scanner bersama + aturan kode yang sama dengan
  // backend (`sameScanCode`: tanpa beda huruf, prefix/suffix scanner dibuang).
  const findBin = (code) => loc.positions.find((p) => sameScanCode(p.barcode, code));
  // Pilih bin dari barcode; mengembalikan hasil untuk ScanResult.
  const applyBin = (pos, code) => {
    if (!pos) return { tone: 'error', title: `Ditolak: bin "${code}" tidak ditemukan`, detail: 'Periksa label bin, atau pilih bin secara manual.' };
    if (selected && !pos.is_empty && pos.material_id !== selected.material_id) {
      return { tone: 'error', title: `Ditolak: bin ${pos.barcode} sudah berisi ${pos.material_code || 'material lain'}`, detail: 'Pilih bin kosong.' };
    }
    setBldg(pos.building_id || ''); setZone(pos.zone_id || ''); setRack(pos.rack_id || ''); setBinId(pos.id);
    return { tone: 'ok', title: `Bin dipilih: ${pos.full_label}`, detail: selected ? `Untuk ${selected.code} · ${selected.name}` : undefined };
  };
  const handleScanBarcode = (raw) => {
    const code = (raw || '').trim();
    if (!code) return;
    const res = applyBin(findBin(code), code);
    scanFeedback(res.tone === 'ok' ? 'ok' : 'error');
    setBinScan(res);
  };

  // Scan kode barang → barang dipilih seperti klik di daftar (popup terbuka, lanjut scan label bin).
  const pendingItems = useMemo(() => CAT_ORDER.flatMap((c) => (groups[c] || []).map((it) => ({ ...it, _cat: c }))), [groups]);
  const handleScanItem = (raw) => {
    const code = (raw || '').trim();
    if (!code) return;
    const it = pendingItems.find((x) => sameScanCode(x.code, code) || x.material_id === code);
    let res;
    if (it) {
      selectItem(it);
      res = { tone: 'ok', title: `Dipilih: ${it.code} · ${it.name}`,
        detail: `Belum dirak ${fmtNum(it.unshelved)} ${it.unit}. Lanjut scan label bin tujuan.` };
    } else {
      const pos = findBin(code);
      if (pos && selected) res = applyBin(pos, code);
      else if (pos) res = { tone: 'error', title: `Ini label bin ${pos.full_label}`, detail: 'Scan barangnya dulu, baru label bin tujuan.' };
      else {
        res = { tone: 'error', title: `Ditolak: "${code}" tidak ada di daftar belum dirak`,
          detail: search ? 'Daftar sedang disaring — kosongkan pencarian, lalu scan ulang.'
            : 'Barang ini sudah dirak semua, atau kodenya bukan kode barang.' };
      }
    }
    scanFeedback(res.tone === 'ok' ? 'ok' : 'error');
    setItemScan(res);
  };

  const handlePlace = async () => {
    if (!selected || !binId || qty <= 0) return;
    if (qtyBase == null) {
      flash('error', `Satuan '${effUom}' belum punya faktor konversi — lengkapi kemasannya di Master Material.`);
      return;
    }
    if (overLimit) {
      flash('error', `Qty melebihi sisa belum dirak (${fmtNum(selected.unshelved)} ${baseUnit}).`);
      return;
    }
    setSaving(true); setGalat('');
    try {
      const payload = { material_id: selected.material_id, qty, position_id: binId };
      if (effUom && effUom !== baseUnit) payload.input_uom = effUom;
      const res = await fetch('/api/wms/putaway/place', {
        method: 'POST', headers,
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (res.ok) {
        const conv = (effUom && effUom !== baseUnit)
          ? ` (${fmtNum(qty)} ${effUom} = ${fmtNum(qtyBase)} ${baseUnit})` : '';
        const teks = `Berhasil menempatkan ${fmtNum(qtyBase)} ${baseUnit || selected.unit || 'pcs'} ${selected.code}${conv} → ${selectedBin?.full_label || 'bin'}. Sisa belum dirak: ${fmtNum(data.remaining_unshelved)}`;
        flash('success', teks);
        toast.success(teks);
        setSelected(null); setBinId(''); setQty(0); setInputUom(''); setPlacements(null);
        setItemScan(null); setBinScan(null);
        fetchData();
      } else { flash('error', data.detail || 'Gagal menyimpan ke bin'); }
    } catch (e) { flash('error', e.message); }
    finally { setSaving(false); }
  };

  const totalPending = pendingItems.length;

  const kolom = [
    { kunci: 'barang', label: 'Barang', hp: 'judul', isi: (it) => (
      <div className="min-w-0">
        <p className="font-medium text-foreground">{it.name}</p>
        <p className="text-xs tabular-nums text-muted-foreground">{it.code}</p>
      </div>) },
    { kunci: 'kategori', label: 'Kategori', hp: 'keterangan', isi: (it) => labels[it._cat] || it._cat },
    { kunci: 'belum', label: 'Belum dirak', rata: 'kanan', isi: (it) => (
      <span className="font-medium tabular-nums text-[hsl(var(--warning-text))]">{fmtNum(it.unshelved)} {it.unit}</span>) },
    { kunci: 'sudah', label: 'Sudah dirak', rata: 'kanan', isi: (it) => (
      <span className="tabular-nums text-muted-foreground">{fmtNum(it.placed)} {it.unit}</span>) },
    { kunci: 'zona', label: 'Ada di', isi: (it) => (
      <span className="text-sm text-muted-foreground">
        {(it.zones || []).map((z) => `${z.zone_label || 'lokasi lain'} ${fmtNum(z.unshelved)}`).join(' · ') || '—'}
      </span>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (it) => (
      <Button size="sm" variant="outline" onClick={() => { selectItem(it); setItemScan(null); }}
        data-testid={`putaway-item-${it.code}`}>
        <MapPin />Tempatkan
      </Button>) },
  ];

  const siapSimpan = !!(selected && binId && qty > 0);

  return (
    <PageLayout
      testId="wh-putaway-module"
      title="Penyimpanan"
      subtitle="Tempatkan barang yang belum dirak ke gudang, zona, rak, dan bin."
      filters={<>
        {(
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder="Cari kode / nama, lalu Enter" value={search} onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && fetchData()} className="pl-8" data-testid="putaway-search" />
        </div>
      )}
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {(
        <>
          <TombolUnduh namaBerkas="barang-belum-dirak" namaLembar="Belum dirak" baris={pendingItems} testId="putaway-unduh"
            kolom={[
              { label: 'Kategori', nilai: (it) => labels[it._cat] || it._cat },
              { label: 'Kode', nilai: (it) => it.code },
              { label: 'Nama', nilai: (it) => it.name },
              { label: 'Satuan', nilai: (it) => it.unit },
              { label: 'Belum dirak', nilai: (it) => Number(it.unshelved || 0) },
              { label: 'Sudah dirak', nilai: (it) => Number(it.placed || 0) },
              { label: 'Ada di', nilai: (it) => (it.zones || []).map((z) => `${z.zone_label || 'lokasi lain'} ${z.unshelved}`).join('; ') },
            ]} />
          <Button variant="outline" size="icon" onClick={fetchData} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
            data-testid="putaway-refresh">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
        </>
      )}
        </div>
      </>}
      summary={message ? (
        <Notice tone="success" icon={CheckCircle2} testId="putaway-message" title={message.text} />
      ) : null}
      footer={(
        // Dulu OnwardCTA bersama (judul HURUF BESAR "LANGKAH BERIKUTNYA"); tujuan & tombolnya sama.
        onNavigate ? (
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground" data-testid="onward-cta">
            <span>Langkah berikutnya:</span>
            <Button size="sm" variant="outline" onClick={() => onNavigate('wms-stock-hub')} title="Cek posisi stok setelah disimpan"
              data-testid="onward-cta-wms-stock-hub"><Warehouse />Lihat stok terkini</Button>
            <Button size="sm" variant="outline" onClick={() => onNavigate('wh-receiving')} title="Terima barang lain"
              data-testid="onward-cta-wh-receiving"><ArrowDownToLine />Kembali ke penerimaan</Button>
          </div>
        ) : null
      )}
    >
      {/* Scan kode barang → popup penempatan terbuka. Di HP tombol kamera besar tampil otomatis. */}
      <div className="w-full sm:max-w-md">
        <UniversalScanner variant="inline" onScan={handleScanItem} keepFocus result={itemScan}
          placeholder="Scan barang / label" data-testid="putaway-scan-item" />
      </div>

      {loading && totalPending === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat barang yang belum dirak…</p>
      ) : (
        <TabelData kolom={kolom} baris={pendingItems} kunci={(it) => `${it._cat}-${it.material_id}`}
          onKlikBaris={(it) => { selectItem(it); setItemScan(null); }} testId="putaway-table"
          kosong={<EmptyState icon={PackageOpen}
            title={search ? 'Tidak ada barang yang cocok' : 'Tidak ada stok yang perlu dirak'}
            description={search ? 'Ubah kata pencarian, lalu tekan Enter.' : 'Semua stok sudah ditempatkan di bin.'} />} />
      )}

      <FormPopup open={!!selected} onClose={tutupPopup} ukuran="panjang" testId="putaway-form"
        judul={selected ? `Tempatkan ${selected.code}` : 'Tempatkan di bin'}
        keterangan={selected ? `${selected.name} · belum dirak ${fmtNum(selected.unshelved)} ${selected.unit}` : undefined}
        onSimpan={handlePlace} menyimpan={saving} bisaSimpan={siapSimpan} galat={galat}
        labelSimpan="Tempatkan di bin">
        {selected && (
          <>
            {zonesOfSelected.length > 0 && (
              <p className="text-sm text-muted-foreground" data-testid="putaway-zones">
                Ada di: {zonesOfSelected.map((z) => `${z.zone_label || 'lokasi lain'} ${fmtNum(z.unshelved)}`).join(' · ')}
              </p>
            )}

            <Isian label="Scan atau ketik barcode bin" petunjuk="Atau pilih bin secara manual di bawah.">
              <PenahanKirim>
                <UniversalScanner variant="inline" onScan={handleScanBarcode} keepFocus autoFocus result={binScan}
                  placeholder="GD-01-ZN-01-RK-01-S01-P01" data-testid="putaway-barcode-input" />
              </PenahanKirim>
            </Isian>

            <div className="grid gap-4 sm:grid-cols-2">
              <Isian label="Gudang" htmlFor="pa-gudang">
                <SmartNativeSelect id="pa-gudang" value={bldg} onChange={(e) => { setBldg(e.target.value); setZone(''); setRack(''); setBinId(''); }}
                  data-testid="putaway-building-select">
                  <option value="">Pilih gudang…</option>
                  {loc.buildings.map((b) => <option key={b.id} value={b.id}>{b.code} - {b.name}</option>)}
                </SmartNativeSelect>
              </Isian>
              <Isian label="Zona" htmlFor="pa-zona">
                <SmartNativeSelect id="pa-zona" value={zone} onChange={(e) => { setZone(e.target.value); setRack(''); setBinId(''); }}
                  data-testid="putaway-zone-select">
                  <option value="">Pilih zona…</option>
                  {zonesForBldg.map((z) => <option key={z.id} value={z.id}>{z.code} - {z.name}</option>)}
                </SmartNativeSelect>
              </Isian>
              <Isian label="Rak" htmlFor="pa-rak">
                <SmartNativeSelect id="pa-rak" value={rack} onChange={(e) => { setRack(e.target.value); setBinId(''); }}
                  data-testid="putaway-rack-select">
                  <option value="">Pilih rak…</option>
                  {racksForZone.map((r) => <option key={r.id} value={r.id}>{r.code} - {r.name}</option>)}
                </SmartNativeSelect>
              </Isian>
              <Isian label="Bin / slot" wajib htmlFor="pa-bin"
                galat={selectedBin && binZoneLeft <= 0
                  ? 'Bin ini tidak berada di zona tempat stok barang ini disimpan — pilih bin di zona di atas.' : undefined}>
                <SmartNativeSelect id="pa-bin" value={binId} onChange={(e) => setBinId(e.target.value)} data-testid="putaway-bin-select">
                  <option value="">Pilih bin…</option>
                  {binsForRack.map((p) => <option key={p.id} value={p.id}>{p.label}{p.material_id === selected.material_id ? ` (isi ${fmtNum(p.qty)})` : ''}</option>)}
                </SmartNativeSelect>
                {selectedBin && binZoneLeft <= 0 && <span className="sr-only" data-testid="putaway-zone-mismatch">Zona tidak cocok</span>}
              </Isian>
            </div>

            <Isian label={`Jumlah ditempatkan (maks ${fmtNum(selected.unshelved)} ${baseUnit})`} wajib htmlFor="pa-qty"
              galat={overLimit ? `Melebihi sisa belum dirak (${fmtNum(selected.unshelved)} ${baseUnit}).` : undefined}>
              <div className="flex gap-2">
                <Input id="pa-qty" type="number" value={qty} min={0} step="0.0001"
                  onChange={(e) => setQty(Math.max(0, parseFloat(e.target.value) || 0))}
                  data-testid="putaway-qty-input" />
                <UomSelect opt={uomOpt} value={effUom} fallbackUnit={selected.unit}
                  onChange={(e) => setInputUom(e.target.value)}
                  testId="putaway-uom-select" className="w-28 shrink-0" />
              </div>
              <UomConversionHint opt={uomOpt} qty={qty} unit={effUom} fallbackUnit={selected.unit}
                className="mt-1" testId="putaway-uom-hint" />
              {overLimit && <span className="sr-only" data-testid="putaway-over-limit">Melebihi sisa</span>}
            </Isian>

            {siapSimpan && (
              <dl className="divide-y divide-[var(--glass-border)] rounded-lg border border-[var(--glass-border)] px-3" data-testid="putaway-summary">
                <BarisDetail label="Tujuan">{selectedBin?.full_label || '—'}</BarisDetail>
                <BarisDetail label="Qty">{fmtNum(qty)} {effUom || selected.unit}</BarisDetail>
                {effUom && baseUnit && effUom !== baseUnit && (
                  <BarisDetail label="Masuk stok">
                    <span className="font-medium text-[hsl(var(--success-text))]" data-testid="putaway-confirm-conv">{fmtNum(qtyBase)} {baseUnit}</span>
                  </BarisDetail>
                )}
              </dl>
            )}

            {placements?.positions?.length > 0 && (
              <div>
                <p className="mb-1 text-xs font-medium text-muted-foreground">Sudah ditempatkan di</p>
                <ul className="max-h-32 space-y-1 overflow-y-auto text-sm">
                  {placements.positions.map((p) => (
                    <li key={p.id} className="flex items-center gap-1.5 text-foreground">
                      <MapPin className="h-3.5 w-3.5 text-muted-foreground" /> {p.barcode} — {fmtNum(p.qty)} {p.unit}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </FormPopup>
    </PageLayout>
  );
}

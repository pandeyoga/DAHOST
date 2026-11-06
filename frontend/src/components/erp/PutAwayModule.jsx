import { useState, useEffect, useCallback, useMemo } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { MapPin, ArrowRight, Boxes, Search, RefreshCw, Check, Warehouse, ArrowDownToLine, ScanLine, PackageOpen, CheckCircle2, XCircle } from 'lucide-react';
import OnwardCTA from './OnwardCTA';
import PageLayout from './layout/PageLayout';
import { Notice } from './moduleAtoms';
import useUomOptions from '@/hooks/useUomOptions';
import { UomSelect, UomConversionHint, toBaseQty, baseUnitOf } from './uom/UomPicker';
import UniversalScanner from './scanner/UniversalScanner';
import { sameScanCode, scanFeedback } from './scanner/scanCode';

const fmtNum = (v) => (v || 0).toLocaleString('id-ID');
const CAT_ORDER = ['bahan', 'aksesoris', 'fg'];

export default function PutAwayModule({ token, onNavigate }) {
  const [groups, setGroups] = useState({ bahan: [], aksesoris: [], fg: [] });
  const [labels, setLabels] = useState({ bahan: 'Bahan', aksesoris: 'Aksesoris', fg: 'Produk Jadi' });
  const [loc, setLoc] = useState({ buildings: [], zones: [], racks: [], positions: [] });
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState(null);       // pending item
  const [placements, setPlacements] = useState(null);    // {onhand,placed,unshelved,positions}
  const [bldg, setBldg] = useState('');
  const [zone, setZone] = useState('');
  const [rack, setRack] = useState('');
  const [binId, setBinId] = useState('');
  const [qty, setQty] = useState(0);
  const [inputUom, setInputUom] = useState('');   // satuan hitung fisik operator
  const [message, setMessage] = useState(null);
  const [saving, setSaving] = useState(false);
  // 2026-11-06 (audit layar scan Gudang): hasil scan tampil TEPAT di bawah kotak scannya (ScanResult).
  const [itemScan, setItemScan] = useState(null);   // kotak scan langkah 1 (barang / label bin)
  const [binScan, setBinScan] = useState(null);     // kotak scan bin langkah 2

  // Satuan yang sah untuk material terpilih (kemasan master + konversi global)
  const { options: uomOpts } = useUomOptions(selected ? [selected.material_id] : []);
  const uomOpt = selected ? uomOpts[selected.material_id] : null;
  const baseUnit = baseUnitOf(uomOpt, selected?.unit || '');
  const effUom = inputUom || baseUnit;
  const qtyBase = uomOpt ? toBaseQty(uomOpt, qty, effUom) : Number(qty || 0);
  const overLimit = selected && qtyBase != null && qtyBase > Number(selected.unshelved || 0) + 1e-6;

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const flash = (type, text) => { setMessage({ type, text }); setTimeout(() => setMessage(null), 4000); };

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

  // 2026-11-02 (Paket 3a): komponen scanner bersama + aturan kode yang sama dengan
  // backend (`sameScanCode`: tanpa beda huruf, prefix/suffix scanner dibuang).
  const findBin = (code) => loc.positions.find((p) => sameScanCode(p.barcode, code));
  // Pilih bin dari barcode; mengembalikan hasil untuk ScanResult (dipakai kotak scan langkah 1 & 2).
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

  // Langkah 1: scan kode barang → barang dipilih seperti klik di daftar. Kalau barang sudah dipilih,
  // kotak yang sama menerima label bin (petugas tidak perlu pindah kotak di antara dua scan).
  const pendingItems = useMemo(() => CAT_ORDER.flatMap((c) => groups[c] || []), [groups]);
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
    setSaving(true);
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
        flash('success', `Berhasil menempatkan ${fmtNum(qtyBase)} ${baseUnit || selected.unit || 'pcs'} ${selected.code}${conv} → ${selectedBin?.full_label || 'bin'}. Sisa belum dirak: ${fmtNum(data.remaining_unshelved)}`);
        setSelected(null); setBinId(''); setQty(0); setInputUom(''); setPlacements(null);
        setItemScan(null); setBinScan(null);
        fetchData();
      } else { flash('error', data.detail || 'Gagal menyimpan ke bin'); }
    } catch (e) { flash('error', e.message); }
    finally { setSaving(false); }
  };

  const totalPending = CAT_ORDER.reduce((s, c) => s + (groups[c]?.length || 0), 0);

  if (loading) return <div className="flex items-center justify-center h-64"><div className="animate-spin rounded-full h-10 w-10 border-b-2 border-primary" /></div>;

  return (
    <PageLayout
      testId="wh-putaway-module"
      title="Penyimpanan"
      subtitle="Tempatkan barang yang belum dirak ke gudang, zona, rak, dan bin."
      tools={(
        <Button variant="outline" size="icon" onClick={fetchData} title="Muat ulang" aria-label="Muat ulang"
          data-testid="putaway-refresh">
          <RefreshCw className="w-4 h-4" />
        </Button>
      )}
    >
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Step 1: Pilih barang belum dirak — scan kode barang (atau klik di daftar) */}
        <GlassCard hover={false} className="p-5">
          <h3 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2"><PackageOpen className="w-4 h-4 text-primary" /> 1. Barang belum dirak <span className="ml-auto text-xs text-muted-foreground">{totalPending} item</span></h3>
          <div className="mb-3">
            <UniversalScanner variant="inline" onScan={handleScanItem} keepFocus result={itemScan}
              placeholder="Scan barang / label" data-testid="putaway-scan-item" />
          </div>
          <div className="relative mb-3">
            <Search className="w-4 h-4 text-muted-foreground absolute left-2.5 top-1/2 -translate-y-1/2" />
            <GlassInput placeholder="Cari kode / nama..." value={search} onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && fetchData()} className="pl-8" data-testid="putaway-search" />
          </div>
          <div className="space-y-3 max-h-[440px] overflow-y-auto">
            {totalPending === 0 ? (
              <p className="text-xs text-muted-foreground text-center py-6">Tidak ada stok yang perlu dirak. Semua sudah ditempatkan.</p>
            ) : CAT_ORDER.map((cat) => (groups[cat]?.length ? (
              <div key={cat}>
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground font-semibold mb-1.5">{labels[cat]}</p>
                <div className="space-y-2">
                  {groups[cat].map((it) => (
                    <button key={it.material_id} onClick={() => { selectItem(it); setItemScan(null); }}
                      className={`w-full text-left p-3 rounded-xl border transition-colors ${selected?.material_id === it.material_id ? 'border-primary/40 bg-primary/10' : 'border-[var(--glass-border)] bg-[var(--glass-bg)] hover:bg-[var(--glass-bg-hover)]'}`}
                      data-testid={`putaway-item-${it.code}`}>
                      <p className="text-sm font-medium text-foreground">{it.name}</p>
                      <p className="text-xs text-muted-foreground tabular-nums">{it.code}</p>
                      <div className="flex items-center gap-3 mt-1 text-[11px]">
                        <span className="text-[hsl(var(--warning))] font-semibold">Belum dirak: {fmtNum(it.unshelved)} {it.unit}</span>
                        {it.placed > 0 && <span className="text-muted-foreground">Sudah dirak: {fmtNum(it.placed)}</span>}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            ) : null))}
          </div>
        </GlassCard>

        {/* Step 2: Lokasi tujuan */}
        <GlassCard hover={false} className="p-5">
          <h3 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2"><MapPin className="w-4 h-4 text-primary" /> 2. Lokasi tujuan</h3>
          {!selected ? (
            <p className="text-xs text-muted-foreground text-center py-8">Pilih barang dulu di langkah 1</p>
          ) : (
            <div className="space-y-3">
              <div className="p-3 rounded-xl bg-primary/10 border border-primary/20">
                <p className="text-sm font-medium text-foreground">{selected.name}</p>
                <p className="text-xs text-muted-foreground tabular-nums">{selected.code}</p>
                <p className="text-xs text-[hsl(var(--warning))] mt-1">Belum dirak: {fmtNum(selected.unshelved)} {selected.unit}</p>
              </div>

              {/* Scan bin */}
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1 flex items-center gap-1"><ScanLine className="w-3 h-3" /> Scan / ketik barcode bin</label>
                <UniversalScanner variant="inline" onScan={handleScanBarcode} keepFocus result={binScan}
                  placeholder="GD-01-ZN-01-RK-01-S01-P01" data-testid="putaway-barcode-input" />
              </div>

              <div className="text-[11px] text-muted-foreground text-center">&mdash; atau pilih manual &mdash;</div>

              {/* Cascade */}
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Gudang</label>
                  <SmartNativeSelect value={bldg} onChange={(e) => { setBldg(e.target.value); setZone(''); setRack(''); setBinId(''); }} className="w-full border border-[var(--glass-border)] bg-[var(--input-surface)] rounded-lg px-3 py-2 text-sm text-foreground" data-testid="putaway-building-select">
                    <option value="">Pilih gudang...</option>
                    {loc.buildings.map((b) => <option key={b.id} value={b.id}>{b.code} - {b.name}</option>)}
                  </SmartNativeSelect>
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Zona</label>
                  <SmartNativeSelect value={zone} onChange={(e) => { setZone(e.target.value); setRack(''); setBinId(''); }} className="w-full border border-[var(--glass-border)] bg-[var(--input-surface)] rounded-lg px-3 py-2 text-sm text-foreground" data-testid="putaway-zone-select">
                    <option value="">Pilih zona...</option>
                    {zonesForBldg.map((z) => <option key={z.id} value={z.id}>{z.code} - {z.name}</option>)}
                  </SmartNativeSelect>
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Rak</label>
                  <SmartNativeSelect value={rack} onChange={(e) => { setRack(e.target.value); setBinId(''); }} className="w-full border border-[var(--glass-border)] bg-[var(--input-surface)] rounded-lg px-3 py-2 text-sm text-foreground" data-testid="putaway-rack-select">
                    <option value="">Pilih rak...</option>
                    {racksForZone.map((r) => <option key={r.id} value={r.id}>{r.code} - {r.name}</option>)}
                  </SmartNativeSelect>
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Bin / Slot</label>
                  <SmartNativeSelect value={binId} onChange={(e) => setBinId(e.target.value)} className="w-full border border-[var(--glass-border)] bg-[var(--input-surface)] rounded-lg px-3 py-2 text-sm text-foreground" data-testid="putaway-bin-select">
                    <option value="">Pilih bin...</option>
                    {binsForRack.map((p) => <option key={p.id} value={p.id}>{p.label}{p.material_id === selected.material_id ? ` (isi ${fmtNum(p.qty)})` : ''}</option>)}
                  </SmartNativeSelect>
                </div>
              </div>

              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1 block">
                  Jumlah ditempatkan (maks {fmtNum(selected.unshelved)} {baseUnit})
                </label>
                <div className="flex gap-2">
                  <GlassInput type="number" value={qty} min={0} step="0.0001"
                    onChange={(e) => setQty(Math.max(0, parseFloat(e.target.value) || 0))}
                    data-testid="putaway-qty-input" />
                  <UomSelect opt={uomOpt} value={effUom} fallbackUnit={selected.unit}
                    onChange={(e) => setInputUom(e.target.value)}
                    testId="putaway-uom-select" className="w-24 shrink-0" />
                </div>
                <UomConversionHint opt={uomOpt} qty={qty} unit={effUom} fallbackUnit={selected.unit}
                  className="mt-1" testId="putaway-uom-hint" />
                {overLimit && (
                  <p className="text-[11px] text-[hsl(var(--destructive))] mt-1" data-testid="putaway-over-limit">
                    Melebihi sisa belum dirak ({fmtNum(selected.unshelved)} {baseUnit}).
                  </p>
                )}
              </div>

              {placements?.positions?.length > 0 && (
                <div className="pt-2 border-t border-[var(--glass-border)]">
                  <p className="text-[11px] text-muted-foreground mb-1">Sudah ditempatkan di:</p>
                  <div className="space-y-1 max-h-24 overflow-y-auto">
                    {placements.positions.map((p) => (
                      <div key={p.id} className="text-[11px] text-foreground flex items-center gap-1"><MapPin className="w-2.5 h-2.5 text-muted-foreground" /> {p.barcode} &mdash; {fmtNum(p.qty)} {p.unit}</div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </GlassCard>

        {/* Step 3: Konfirmasi */}
        <GlassCard hover={false} className="p-5">
          <h3 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2"><ArrowRight className="w-4 h-4 text-primary" /> 3. Konfirmasi</h3>
          {selected && binId && qty > 0 ? (
            <div className="space-y-4">
              <div className="p-3 rounded-xl bg-[var(--glass-bg)] border border-[var(--glass-border)] space-y-2">
                <div className="flex justify-between text-xs"><span className="text-muted-foreground">Barang</span><span className="text-foreground font-medium">{selected.name}</span></div>
                <div className="flex justify-between text-xs"><span className="text-muted-foreground">Kode</span><span className="text-foreground tabular-nums">{selected.code}</span></div>
                <div className="flex justify-between text-xs"><span className="text-muted-foreground">Tujuan</span><span className="text-foreground text-right">{selectedBin?.full_label || '-'}</span></div>
                <div className="flex justify-between text-xs"><span className="text-muted-foreground">Qty</span><span className="text-foreground font-bold">{fmtNum(qty)} {effUom || selected.unit}</span></div>
                {effUom && baseUnit && effUom !== baseUnit && (
                  <div className="flex justify-between text-xs" data-testid="putaway-confirm-conv">
                    <span className="text-muted-foreground">Masuk stok</span>
                    <span className="text-[hsl(var(--success))] font-bold">{fmtNum(qtyBase)} {baseUnit}</span>
                  </div>
                )}
              </div>
              <Button onClick={handlePlace} disabled={saving} className="w-full" data-testid="putaway-confirm-btn">
                <Check className="w-4 h-4 mr-1" /> {saving ? 'Menyimpan...' : 'Tempatkan di bin'}
              </Button>
            </div>
          ) : (
            <div className="text-xs text-muted-foreground text-center py-8 flex flex-col items-center gap-2">
              <Boxes className="w-8 h-8 text-muted-foreground/40" />
              Lengkapi langkah 1 &amp; 2 dulu
            </div>
          )}
          {/* Hasil simpan tampil di kartu tempat tombolnya ditekan — dulu di atas halaman (di HP di luar layar). */}
          {message && (
            <Notice tone={message.type === 'success' ? 'success' : 'danger'} className="mt-3"
              icon={message.type === 'success' ? CheckCircle2 : XCircle} testId="putaway-message"
              title={message.text} />
          )}
        </GlassCard>
      </div>

      {/* Navigasi lanjutan di akhir halaman — dulu di atas dan memenuhi layar pertama HP sebelum pekerjaannya. */}
      <OnwardCTA
        onNavigate={onNavigate}
        title="Langkah berikutnya"
        actions={[
          { module: 'wms-stock-hub', label: 'Lihat stok terkini', icon: Warehouse, primary: true, hint: 'Cek posisi stok setelah disimpan' },
          { module: 'wh-receiving', label: 'Kembali ke penerimaan', icon: ArrowDownToLine, hint: 'Terima barang lain' },
        ]}
      />
    </PageLayout>
  );
}

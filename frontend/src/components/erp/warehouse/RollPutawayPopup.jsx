/**
 * Simpan roll kain ke posisi rak (put-away) — 10 Nov 2026, keputusan owner.
 *
 * Dulu: dua kotak ketik bebas "ID posisi" dan "Barcode posisi", disimpan server apa adanya — roll bisa
 * "berada" di posisi yang tidak ada di peta gudang. Kini posisi DIPILIH dari master struktur gudang secara
 * bertingkat (gudang → zona → rak → posisi, endpoint baca `/api/wms/buildings|zones|racks|positions`) ATAU
 * di-scan dengan pemindai bersama (`UniversalScanner`, dicek ke `/api/wms/positions/by-barcode`). Server
 * (`POST /api/wms/fabric-rolls/{id}/putaway`) tetap memeriksa ulang posisinya ke master.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { apiFetch } from '@/lib/api';
import { toast } from 'sonner';
import UniversalScanner from '../scanner/UniversalScanner';
import { scanFeedback } from '../scanner/scanCode';

const KOSONG = { building_id: '', zone_id: '', rack_id: '', position_id: '', notes: '' };
const errText = (d, fb) => (typeof d?.detail === 'string' ? d.detail : d?.detail?.message || fb);
const labelPosisi = (p) => `Tingkat ${p.shelf_no ?? '-'} · slot ${p.slot_no ?? '-'} — ${p.barcode}`
  + (p.material_code ? ` (isi ${p.material_code})` : '');
const jalurPosisi = (p) => [p.building_code, p.zone_code, p.rack_code].filter(Boolean).join(' / ')
  + (p.barcode ? ` · ${p.barcode}` : '');

/**
 * Kotak scan di dalam FormPopup: kamera/ketik manual punya <form> sendiri (portal) yang kirimnya merambat
 * lewat pohon React ke form popup — ditahan supaya scan TIDAK ikut menekan "Simpan" (pola PutAwayModule).
 */
function PenahanKirim({ children }) {
  return (
    <div onSubmit={(e) => e.stopPropagation()}
      onKeyDown={(e) => { if (e.key === 'Enter' && e.target.tagName === 'INPUT') e.preventDefault(); }}>
      {children}
    </div>
  );
}

export default function RollPutawayPopup({ roll, onClose, onDone }) {
  const [pa, setPa] = useState(KOSONG);
  const [opsi, setOpsi] = useState({ buildings: [], zones: [], racks: [], positions: [] });
  const [memuat, setMemuat] = useState('');      // tingkat yang sedang dimuat: gudang|zona|rak|posisi
  const [scan, setScan] = useState(null);        // hasil scan → ScanResult di bawah kotak scan
  const [galat, setGalat] = useState('');
  const [saving, setSaving] = useState(false);
  const paRef = useRef(pa);
  paRef.current = pa;

  const ambil = useCallback(async (url) => {
    const r = await apiFetch(url);
    const d = await r.json().catch(() => null);
    if (!r.ok) throw new Error(errText(d, `HTTP ${r.status}`));
    return Array.isArray(d) ? d : (d?.items || []);
  }, []);

  // Setiap popup dibuka untuk roll lain: kosongkan pilihan, muat daftar gudang.
  useEffect(() => {
    if (!roll) return undefined;
    let alive = true;
    setPa(KOSONG); setScan(null); setGalat('');
    setOpsi({ buildings: [], zones: [], racks: [], positions: [] });
    setMemuat('gudang');
    ambil('/api/wms/buildings')
      .then((buildings) => { if (alive) setOpsi((o) => ({ ...o, buildings })); })
      .catch((e) => { if (alive) setGalat(`Daftar gudang gagal dimuat: ${e.message}`); })
      .finally(() => { if (alive) setMemuat(''); });
    return () => { alive = false; };
  }, [roll, ambil]);

  const pilihGudang = async (building_id) => {
    setPa((f) => ({ ...f, building_id, zone_id: '', rack_id: '', position_id: '' }));
    setOpsi((o) => ({ ...o, zones: [], racks: [], positions: [] }));
    setScan(null);
    if (!building_id) return;
    setMemuat('zona');
    try {
      const zones = await ambil(`/api/wms/zones?building_id=${encodeURIComponent(building_id)}`);
      if (paRef.current.building_id === building_id) setOpsi((o) => ({ ...o, zones }));
    } catch (e) { setGalat(`Daftar zona gagal dimuat: ${e.message}`); } finally { setMemuat(''); }
  };
  const pilihZona = async (zone_id) => {
    setPa((f) => ({ ...f, zone_id, rack_id: '', position_id: '' }));
    setOpsi((o) => ({ ...o, racks: [], positions: [] }));
    setScan(null);
    if (!zone_id) return;
    setMemuat('rak');
    try {
      const racks = await ambil(`/api/wms/racks?zone_id=${encodeURIComponent(zone_id)}`);
      if (paRef.current.zone_id === zone_id) setOpsi((o) => ({ ...o, racks }));
    } catch (e) { setGalat(`Daftar rak gagal dimuat: ${e.message}`); } finally { setMemuat(''); }
  };
  const pilihRak = async (rack_id) => {
    setPa((f) => ({ ...f, rack_id, position_id: '' }));
    setOpsi((o) => ({ ...o, positions: [] }));
    setScan(null);
    if (!rack_id) return;
    setMemuat('posisi');
    try {
      const positions = await ambil(`/api/wms/positions?rack_id=${encodeURIComponent(rack_id)}`);
      if (paRef.current.rack_id === rack_id) setOpsi((o) => ({ ...o, positions }));
    } catch (e) { setGalat(`Daftar posisi gagal dimuat: ${e.message}`); } finally { setMemuat(''); }
  };

  // Scan label posisi → cari di master, lalu isi keempat pilihan (gudang, zona, rak, posisi) sekaligus.
  const scanPosisi = async (raw) => {
    const code = (raw || '').trim();
    if (!code) return;
    let hasil;
    try {
      const r = await apiFetch(`/api/wms/positions/by-barcode/${encodeURIComponent(code)}`);
      const p = await r.json().catch(() => null);
      if (!r.ok || !p?.id) {
        hasil = { tone: 'error', title: `Ditolak: posisi "${code}" tidak ada di master gudang`,
          detail: 'Periksa label posisi, atau pilih posisinya dari daftar di bawah.' };
      } else {
        const [zones, racks, positions] = await Promise.all([
          p.building_id ? ambil(`/api/wms/zones?building_id=${encodeURIComponent(p.building_id)}`) : [],
          p.zone_id ? ambil(`/api/wms/racks?zone_id=${encodeURIComponent(p.zone_id)}`) : [],
          p.rack_id ? ambil(`/api/wms/positions?rack_id=${encodeURIComponent(p.rack_id)}`) : [],
        ]);
        // Daftar gudang/zona/rak hanya berisi yang AKTIF — posisi di induk nonaktif ditolak di sini (dan di server).
        const nonaktif = !opsi.buildings.some((x) => x.id === p.building_id) ? 'Gudang'
          : !zones.some((x) => x.id === p.zone_id) ? 'Zona'
            : !racks.some((x) => x.id === p.rack_id) ? 'Rak' : '';
        if (nonaktif) {
          hasil = { tone: 'error', title: `Ditolak: ${nonaktif.toLowerCase()} posisi ${p.barcode} sudah dinonaktifkan`,
            detail: 'Pilih posisi lain yang masih aktif.' };
        } else {
          setOpsi((o) => ({ ...o, zones, racks, positions }));
          setPa((f) => ({ ...f, building_id: p.building_id || '', zone_id: p.zone_id || '', rack_id: p.rack_id || '',
            position_id: p.id }));
          setGalat('');
          hasil = { tone: 'ok', title: `Posisi dipilih: ${jalurPosisi(p)}` };
        }
      }
    } catch (e) {
      hasil = { tone: 'error', title: 'Barcode posisi gagal diperiksa', detail: e.message };
    }
    scanFeedback(hasil.tone === 'ok' ? 'ok' : 'error');
    setScan(hasil);
  };

  const posisi = opsi.positions.find((p) => p.id === pa.position_id) || null;

  const simpan = async () => {
    if (!posisi) { setGalat('Pilih posisi dari daftar, atau scan barcode posisinya.'); return; }
    setSaving(true); setGalat('');
    try {
      const r = await apiFetch(`/api/wms/fabric-rolls/${roll.id}/putaway`, {
        method: 'POST',
        body: JSON.stringify({ position_id: posisi.id, position_barcode: posisi.barcode || '', notes: pa.notes || '' }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(errText(d, `HTTP ${r.status}`));
      toast.success(`Roll ${roll.roll_no} disimpan di ${d.position_barcode || posisi.barcode}`);
      onDone?.();
      onClose();
    } catch (e) {
      setGalat(e.message || 'Roll gagal disimpan ke posisi');
    } finally {
      setSaving(false);
    }
  };

  if (!roll) return null;
  return (
    <FormPopup open onClose={() => { if (!saving) onClose(); }} ukuran="pendek" testId="putaway-dialog"
      judul={`Simpan roll ${roll.roll_no} ke posisi`}
      keterangan={[roll.material_name, roll.location_name && `diterima di ${roll.location_name}`,
        roll.position_barcode && `posisi sekarang ${roll.position_barcode}`].filter(Boolean).join(' · ')}
      onSimpan={simpan} menyimpan={saving} bisaSimpan={!!posisi} galat={galat} labelSimpan="Simpan">
      <Isian label="Scan barcode posisi" petunjuk="Atau pilih posisinya dari daftar gudang › zona › rak › posisi.">
        <PenahanKirim>
          <UniversalScanner variant="inline" onScan={scanPosisi} result={scan} keepFocus
            placeholder="Scan atau ketik barcode posisi" data-testid="putaway-scan-posisi" />
        </PenahanKirim>
      </Isian>
      <div className="grid gap-4 sm:grid-cols-2" data-testid="putaway-pemilih-posisi">
        <Isian label="Gudang" htmlFor="pa-roll-gudang">
          <SmartNativeSelect id="pa-roll-gudang" value={pa.building_id} onChange={(e) => pilihGudang(e.target.value)}
            data-testid="putaway-building-select">
            <option value="">{memuat === 'gudang' ? 'Memuat gudang…' : 'Pilih gudang'}</option>
            {opsi.buildings.map((b) => <option key={b.id} value={b.id}>{`${b.code} — ${b.name}`}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Zona" htmlFor="pa-roll-zona">
          <SmartNativeSelect id="pa-roll-zona" value={pa.zone_id} onChange={(e) => pilihZona(e.target.value)}
            disabled={!pa.building_id} data-testid="putaway-zone-select">
            <option value="">{memuat === 'zona' ? 'Memuat zona…' : 'Pilih zona'}</option>
            {opsi.zones.map((z) => <option key={z.id} value={z.id}>{`${z.code} — ${z.name}`}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Rak" htmlFor="pa-roll-rak">
          <SmartNativeSelect id="pa-roll-rak" value={pa.rack_id} onChange={(e) => pilihRak(e.target.value)}
            disabled={!pa.zone_id} data-testid="putaway-rack-select">
            <option value="">{memuat === 'rak' ? 'Memuat rak…' : 'Pilih rak'}</option>
            {opsi.racks.map((r) => <option key={r.id} value={r.id}>{`${r.code} — ${r.name}`}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Posisi" wajib htmlFor="pa-roll-posisi">
          <SmartNativeSelect id="pa-roll-posisi" value={pa.position_id}
            onChange={(e) => { setPa((f) => ({ ...f, position_id: e.target.value })); setScan(null); setGalat(''); }}
            disabled={!pa.rack_id} data-testid="putaway-position-select">
            <option value="">{memuat === 'posisi' ? 'Memuat posisi…' : 'Pilih posisi'}</option>
            {opsi.positions.map((p) => <option key={p.id} value={p.id}>{labelPosisi(p)}</option>)}
          </SmartNativeSelect>
        </Isian>
      </div>
      <Isian label="Catatan" htmlFor="pa-roll-catatan">
        <Input id="pa-roll-catatan" value={pa.notes} onChange={(e) => setPa((f) => ({ ...f, notes: e.target.value }))}
          data-testid="input-putaway-notes" />
      </Isian>
    </FormPopup>
  );
}
